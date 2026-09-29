"""Pending-only cancellation (scenario T06, T18 partial).

Cancellation is a conditional transition; rowcount decides the response.
Running jobs are NOT cancelable in v1 (409 semantics at the API layer).
"""

from __future__ import annotations

import sqlite3

from walflow.domain.clock import Clock
from walflow.domain.errors import JobNotCancelableError, JobNotFoundError
from walflow.domain.states import CANCELABLE_STATES, EVENT_CANCELED
from walflow.storage.transactions import immediate_transaction


def cancel_job(conn: sqlite3.Connection, *, clock: Clock, job_id: str) -> dict[str, str]:
    if not isinstance(job_id, str) or not job_id:
        raise JobNotFoundError("job_id must be a non-empty string")
    with immediate_transaction(conn):
        now = clock.now_ms()
        row = conn.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        if row["state"] == "canceled":
            return {"job_id": job_id, "state": "canceled"}
        if row["state"] not in CANCELABLE_STATES:
            raise JobNotCancelableError(
                f"job is {row['state']}; only queued/retry_wait jobs can be canceled"
            )
        cur = conn.execute(
            """UPDATE jobs SET state='canceled', updated_at=?, finished_at=?,
                 owner_token=NULL, lease_expires_at=NULL, active_attempt_id=NULL
               WHERE id=? AND state IN ('queued','retry_wait')""",
            (now, now, job_id),
        )
        if cur.rowcount != 1:
            raise JobNotCancelableError("job transitioned concurrently; retry cancel")
        conn.execute(
            "INSERT INTO job_events(job_id, attempt_id, kind, created_at) VALUES(?,NULL,?,?)",
            (job_id, EVENT_CANCELED, now),
        )
        child_rows = conn.execute(
            "SELECT child_id FROM job_dependencies WHERE parent_id=?", (job_id,)
        ).fetchall()
        for cr in child_rows:
            cid = cr["child_id"]
            conn.execute(
                """UPDATE jobs
                   SET state='canceled', finished_at=?, updated_at=?,
                       last_error_code='UPSTREAM_CANCELED',
                       last_error_summary='Prerequisite parent job was canceled'
                   WHERE id=? AND state='queued' AND pending_dependencies_count > 0""",
                (now, now, cid),
            )
    return {"job_id": job_id, "state": "canceled"}
