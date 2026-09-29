"""Fenced completion, failure and heartbeat (scenarios T08, T09).

Every write verifies inside BEGIN IMMEDIATE: job state == running, active
attempt matches, owner token matches, lease unexpired. A stale owner is
rejected without any state change (StaleOwnerError).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from relay.domain.clock import Clock
from relay.domain.contracts import FailureResult
from relay.domain.errors import StaleOwnerError, ValidationError
from relay.domain.policies import RandomSource, backoff_delay_ms
from relay.domain.states import EVENT_FAILED, EVENT_RETRY_SCHEDULED, EVENT_SUCCEEDED
from relay.domain.validation import bounded_json, integer
from relay.storage.transactions import write_tx

MAX_RESULT_BYTES = 65_536
MAX_ERROR_SUMMARY = 500

_FENCE = " AND active_attempt_id=? AND owner_token=? AND lease_expires_at > ?"


def complete_job(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    job_id: str,
    attempt_id: str,
    owner_token: str,
    result: Mapping[str, object],
) -> None:
    """Commit success if (and only if) this attempt still owns the lease."""
    result_json = bounded_json(result, cap=MAX_RESULT_BYTES)

    def _body(c: sqlite3.Connection) -> None:
        now = clock.now_ms()
        cur = c.execute(
            """UPDATE jobs
               SET state='succeeded', updated_at=?, finished_at=?, result_json=?,
                   owner_token=NULL, lease_expires_at=NULL, active_attempt_id=NULL
               WHERE id=? AND state='running'"""
            + _FENCE,
            (now, now, result_json, job_id, attempt_id, owner_token, now),
        )
        if cur.rowcount != 1:
            raise StaleOwnerError("completion rejected: not the current lease owner")
        c.execute(
            """UPDATE attempts SET state='succeeded', finished_at=?, result_json=?
               WHERE id=? AND state='running'""",
            (now, result_json, attempt_id),
        )
        c.execute(
            "INSERT INTO job_events(job_id, attempt_id, kind, created_at) VALUES(?,?,?,?)",
            (job_id, attempt_id, EVENT_SUCCEEDED, now),
        )
        child_rows = c.execute(
            "SELECT child_id FROM job_dependencies WHERE parent_id=?", (job_id,)
        ).fetchall()
        for cr in child_rows:
            cid = cr["child_id"]
            c.execute(
                """UPDATE jobs
                   SET pending_dependencies_count = MAX(0, pending_dependencies_count - 1),
                       available_at = CASE
                           WHEN pending_dependencies_count - 1 <= 0 THEN ?
                           ELSE available_at
                       END,
                       updated_at = ?
                   WHERE id=?""",
                (now, now, cid),
            )

    return write_tx(conn, _body)


def heartbeat(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    job_id: str,
    attempt_id: str,
    owner_token: str,
    lease_ms: int = 30_000,
    progress_percent: int | None = None,
    progress_message: str | None = None,
    progress_json: str | None = None,
) -> bool:
    """Extend the lease if (and only if) still the fenced owner."""
    integer(lease_ms, "lease_ms", 1, 600_000)
    if progress_percent is not None:
        integer(progress_percent, "progress_percent", 0, 100)
    if progress_message is not None and len(progress_message) > 500:
        progress_message = progress_message[:500]
    if progress_json is not None and len(progress_json) > 4096:
        progress_json = progress_json[:4096]

    def _beat(c: sqlite3.Connection) -> bool:
        now = clock.now_ms()
        cur = c.execute(
            """UPDATE jobs SET lease_expires_at=?, updated_at=?,
                   progress_percent=COALESCE(?, progress_percent),
                   progress_message=COALESCE(?, progress_message),
                   progress_json=COALESCE(?, progress_json)
               WHERE id=? AND state='running'"""
            + _FENCE,
            (
                now + lease_ms,
                now,
                progress_percent,
                progress_message,
                progress_json,
                job_id,
                attempt_id,
                owner_token,
                now,
            ),
        )
        if cur.rowcount == 1:
            c.execute(
                "UPDATE attempts SET lease_expires_at=? WHERE id=? AND state='running'",
                (now + lease_ms, attempt_id),
            )
        return cur.rowcount == 1

    return write_tx(conn, _beat)


def fail_job(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    job_id: str,
    attempt_id: str,
    owner_token: str,
    error_code: str,
    error_summary: str,
    rng: RandomSource,
    timed_out: bool = False,
    retryable: bool = True,
) -> FailureResult:
    """Record attempt failure; schedule retry within budget, else fail job.

    Returns {"outcome": "retry_wait" | "failed", "retry_at"?}.
    """
    if type(timed_out) is not bool or type(retryable) is not bool:
        raise ValidationError("timed_out and retryable must be booleans")
    if not isinstance(error_code, str) or not 1 <= len(error_code) <= 100:
        raise ValidationError("error_code must be 1..100 characters")
    if not isinstance(error_summary, str):
        raise ValidationError("error_summary must be text")

    def _body(c: sqlite3.Connection) -> FailureResult:
        now = clock.now_ms()
        row = c.execute(
            "SELECT attempt_count, max_attempts FROM jobs WHERE id=? AND state='running'" + _FENCE,
            (job_id, attempt_id, owner_token, now),
        ).fetchone()
        if row is None:
            raise StaleOwnerError("failure rejected: not the current lease owner")
        summary = error_summary[:MAX_ERROR_SUMMARY]

        if timed_out:
            c.execute(
                "INSERT INTO job_events(job_id, attempt_id, kind, created_at) VALUES(?,?,?,?)",
                (job_id, attempt_id, "timed_out", now),
            )
        if not retryable or row["attempt_count"] >= row["max_attempts"]:
            cur = c.execute(
                """UPDATE jobs SET state='failed', updated_at=?, finished_at=?,
                     owner_token=NULL, lease_expires_at=NULL, active_attempt_id=NULL,
                     last_error_code=?, last_error_summary=?
                   WHERE id=? AND state='running'"""
                + _FENCE,
                (now, now, error_code, summary, job_id, attempt_id, owner_token, now),
            )
            if cur.rowcount != 1:
                raise StaleOwnerError("concurrent transition won the race")
            c.execute(
                """UPDATE attempts SET state=?, finished_at=?, error_code=?,
                     error_summary=? WHERE id=? AND state='running'""",
                ("timed_out" if timed_out else "failed", now, error_code, summary, attempt_id),
            )
            c.execute(
                "INSERT INTO job_events(job_id, attempt_id, kind, created_at) VALUES(?,?,?,?)",
                (job_id, attempt_id, EVENT_FAILED, now),
            )
            child_rows = c.execute(
                "SELECT child_id FROM job_dependencies WHERE parent_id=?", (job_id,)
            ).fetchall()
            for cr in child_rows:
                cid = cr["child_id"]
                c.execute(
                    """UPDATE jobs
                       SET state='canceled', finished_at=?, updated_at=?,
                           last_error_code='UPSTREAM_FAILED',
                           last_error_summary='Prerequisite parent job failed'
                       WHERE id=? AND state='queued' AND pending_dependencies_count > 0""",
                    (now, now, cid),
                )
            return {"outcome": "failed"}

        delay = backoff_delay_ms(row["attempt_count"], rng)
        cur = c.execute(
            """UPDATE jobs SET state='retry_wait', updated_at=?, available_at=?,
                 owner_token=NULL, lease_expires_at=NULL, active_attempt_id=NULL,
                 last_error_code=?, last_error_summary=?
               WHERE id=? AND state='running'"""
            + _FENCE,
            (now, now + delay, error_code, summary, job_id, attempt_id, owner_token, now),
        )
        if cur.rowcount != 1:
            raise StaleOwnerError("concurrent transition won the race")
        c.execute(
            """UPDATE attempts SET state=?, finished_at=?, error_code=?,
                 error_summary=? WHERE id=? AND state='running'""",
            ("timed_out" if timed_out else "failed", now, error_code, summary, attempt_id),
        )
        c.execute(
            """INSERT INTO job_events(job_id, attempt_id, kind, created_at, detail_json)
               VALUES(?,?,?,?,?)""",
            (
                job_id,
                attempt_id,
                EVENT_RETRY_SCHEDULED,
                now,
                json.dumps({"retry_at": now + delay, "attempt": row["attempt_count"]}),
            ),
        )
        return {"outcome": "retry_wait", "retry_at": now + delay}

    return write_tx(conn, _body)
