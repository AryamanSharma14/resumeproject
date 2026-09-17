"""Pending-only cancellation (scenario T06, T18 partial).

Cancellation is a conditional transition; rowcount decides the response.
Running jobs are NOT cancelable in v1 (409 semantics at the API layer).
"""

from __future__ import annotations

import sqlite3

from relay.domain.clock import Clock
from relay.domain.errors import JobNotCancelableError, JobNotFoundError
from relay.domain.states import CANCELABLE_STATES, EVENT_CANCELED
from relay.storage.transactions import immediate_transaction


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
    return {"job_id": job_id, "state": "canceled"}
