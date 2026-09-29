"""Expiry recovery (scenarios T07, T11, T12 core semantics).

One fenced transition per job: the single UPDATE flips state running ->
retry_wait/failed, clears ownership, and re-verifies staleness inside
BEGIN IMMEDIATE. All follow-up writes (attempt lost, events) happen only
after that UPDATE won, so two concurrent recoverers produce exactly one
lost event and one next-state transition (T07). Fresh data is re-read
inside the same transaction - the outer pre-selection snapshot is never
trusted for budget decisions.
"""

from __future__ import annotations

import json
import sqlite3

from walflow.domain.clock import Clock
from walflow.domain.contracts import RecoveryOutcome
from walflow.domain.policies import RandomSource, backoff_delay_ms
from walflow.domain.states import (
    EVENT_ATTEMPT_LOST,
    EVENT_FAILED,
    EVENT_RETRY_SCHEDULED,
    AttemptState,
)
from walflow.domain.validation import integer
from walflow.storage.transactions import immediate_transaction

_DRAIN = """UPDATE jobs
   SET state=?, updated_at=?,
       available_at=CASE WHEN ?='retry_wait' THEN ? ELSE available_at END,
       finished_at=CASE WHEN ?='failed' THEN ? ELSE NULL END,
       last_error_code='ATTEMPT_LOST', last_error_summary='lease expired',
       owner_token=NULL, lease_expires_at=NULL, active_attempt_id=NULL
   WHERE id=? AND state='running' AND lease_expires_at IS NOT NULL
     AND lease_expires_at <= ?"""


def recover_expired_jobs(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    rng: RandomSource,
    batch_limit: int = 50,
) -> list[RecoveryOutcome]:
    """Recover up to batch_limit expired-lease jobs; one outcome per job."""
    integer(batch_limit, "batch_limit", 1, 500)
    now = clock.now_ms()
    rows = conn.execute(
        """SELECT id FROM jobs
           WHERE state='running' AND lease_expires_at IS NOT NULL
             AND lease_expires_at <= ?
           ORDER BY lease_expires_at ASC LIMIT ?""",
        (now, batch_limit),
    ).fetchall()
    outcomes: list[RecoveryOutcome] = []
    for row in rows:
        with immediate_transaction(conn):
            outcomes.append(_recover_one(conn, now=clock.now_ms(), job_id=str(row["id"]), rng=rng))
    return outcomes


def _recover_one(
    conn: sqlite3.Connection, *, now: int, job_id: str, rng: RandomSource
) -> RecoveryOutcome:
    # Fresh read inside this transaction; state may have changed since selection.
    fresh = conn.execute(
        """SELECT active_attempt_id, attempt_count, max_attempts
           FROM jobs WHERE id=? AND state='running'
             AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?""",
        (job_id, now),
    ).fetchone()
    if fresh is None:
        return {"job_id": job_id, "outcome": "already_transitioned"}
    attempt_id: str | None = fresh["active_attempt_id"]
    attempt_count: int = fresh["attempt_count"]
    max_attempts: int = fresh["max_attempts"]

    state = "failed" if attempt_count >= max_attempts else "retry_wait"
    delay = backoff_delay_ms(attempt_count, rng) if state == "retry_wait" else 0
    cur = conn.execute(_DRAIN, (state, now, state, now + delay, state, now, job_id, now))
    if cur.rowcount != 1:
        return {"job_id": job_id, "outcome": "already_transitioned"}
    if attempt_id is not None:
        conn.execute(
            "UPDATE attempts SET state=?, finished_at=? WHERE id=? AND state='running'",
            (AttemptState.LOST, now, attempt_id),
        )
        conn.execute(
            "INSERT INTO job_events(job_id, attempt_id, kind, created_at) VALUES(?,?,?,?)",
            (job_id, attempt_id, EVENT_ATTEMPT_LOST, now),
        )
    if state == "failed":
        conn.execute(
            """UPDATE jobs SET last_error_code='ATTEMPT_LOST',
                 last_error_summary='lease expired; attempt budget exhausted'
               WHERE id=?""",
            (job_id,),
        )
        conn.execute(
            "INSERT INTO job_events(job_id, attempt_id, kind, created_at) VALUES(?,?,?,?)",
            (job_id, attempt_id, EVENT_FAILED, now),
        )
        return {"job_id": job_id, "outcome": "failed"}
    conn.execute(
        "INSERT INTO job_events(job_id, attempt_id, kind, created_at, detail_json)"
        " VALUES(?,?,?,?,?)",
        (
            job_id,
            attempt_id,
            EVENT_RETRY_SCHEDULED,
            now,
            json.dumps({"retry_at": now + delay, "attempt": attempt_count}),
        ),
    )
    return {"job_id": job_id, "outcome": "retry_scheduled", "retry_at": now + delay}
