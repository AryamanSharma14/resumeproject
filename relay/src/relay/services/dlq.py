"""Dead-Letter Queue (DLQ) and remediation services."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from relay.domain.clock import Clock
from relay.domain.errors import JobNotFoundError, ValidationError
from relay.domain.registry import validate_payload
from relay.domain.states import EVENT_REDRIVEN
from relay.domain.validation import bounded_json, integer, queue_name
from relay.storage.transactions import write_tx


def list_dlq_jobs(
    conn: sqlite3.Connection,
    *,
    queue: str | None = None,
    handler: str | None = None,
    error_code: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Query failed jobs that exhausted their attempt budget."""
    integer(limit, "limit", 1, 500)
    integer(offset, "offset", 0, 100_000)
    conditions = ["state = 'failed'", "attempt_count >= max_attempts"]
    params: list[Any] = []

    if queue is not None:
        queue_name(queue)
        conditions.append("queue = ?")
        params.append(queue)
    if handler is not None:
        conditions.append("handler = ?")
        params.append(handler)
    if error_code is not None:
        conditions.append("last_error_code = ?")
        params.append(error_code)

    where_clause = " AND ".join(conditions)
    count_row = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {where_clause}", params).fetchone()
    total = int(count_row[0]) if count_row else 0

    rows = conn.execute(
        f"""SELECT id, handler, queue, payload_json, priority, created_at, updated_at,
                   finished_at, attempt_count, max_attempts, last_error_code, last_error_summary
            FROM jobs
            WHERE {where_clause}
            ORDER BY finished_at DESC, id ASC
            LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    ).fetchall()

    items = [
        {
            "id": r["id"],
            "handler": r["handler"],
            "queue": r["queue"],
            "payload": json.loads(r["payload_json"]),
            "priority": r["priority"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "finished_at": r["finished_at"],
            "attempt_count": r["attempt_count"],
            "max_attempts": r["max_attempts"],
            "last_error_code": r["last_error_code"],
            "last_error_summary": r["last_error_summary"],
        }
        for r in rows
    ]
    return {"total": total, "items": items, "limit": limit, "offset": offset}


def redrive_job(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    job_id: str,
    reset_attempts: bool = True,
    updated_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically reset a failed job back to queued for execution."""
    if not isinstance(job_id, str) or not job_id:
        raise ValidationError("job_id must be a non-empty string")

    def _body(c: sqlite3.Connection) -> dict[str, Any]:
        now = clock.now_ms()
        row = c.execute(
            "SELECT id, handler, state, attempt_count, max_attempts FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise JobNotFoundError(f"job {job_id} not found")
        if row["state"] != "failed":
            raise ValidationError(f"cannot redrive job in state '{row['state']}'; must be 'failed'")

        payload_json = None
        if updated_payload is not None:
            validate_payload(row["handler"], updated_payload)
            payload_json = bounded_json(updated_payload)

        new_attempt_count = 0 if reset_attempts else row["attempt_count"]
        cur = c.execute(
            """UPDATE jobs
               SET state='queued', updated_at=?, available_at=?, finished_at=NULL,
                   last_error_code=NULL, last_error_summary=NULL,
                   attempt_count=?,
                   payload_json=COALESCE(?, payload_json)
               WHERE id=? AND state='failed'""",
            (now, now, new_attempt_count, payload_json, job_id),
        )
        if cur.rowcount != 1:
            raise ValidationError("job transitioned concurrently; redrive aborted")

        c.execute(
            """INSERT INTO job_events(job_id, attempt_id, kind, created_at, detail_json)
               VALUES(?,NULL,?,?,?)""",
            (
                job_id,
                EVENT_REDRIVEN,
                now,
                json.dumps(
                    {
                        "reset_attempts": reset_attempts,
                        "payload_updated": updated_payload is not None,
                    }
                ),
            ),
        )
        return {"job_id": job_id, "state": "queued", "redriven": True}

    return write_tx(conn, _body)


def redrive_bulk(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    queue: str | None = None,
    handler: str | None = None,
    error_code: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Bulk redrive failed jobs matching criteria."""
    integer(limit, "limit", 1, 500)
    conditions = ["state = 'failed'", "attempt_count >= max_attempts"]
    params: list[Any] = []

    if queue is not None:
        queue_name(queue)
        conditions.append("queue = ?")
        params.append(queue)
    if handler is not None:
        conditions.append("handler = ?")
        params.append(handler)
    if error_code is not None:
        conditions.append("last_error_code = ?")
        params.append(error_code)

    where_clause = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT id FROM jobs WHERE {where_clause} ORDER BY finished_at ASC LIMIT ?",
        (*params, limit),
    ).fetchall()
    redriven_ids: list[str] = []
    for r in rows:
        redrive_job(conn, clock=clock, job_id=r["id"], reset_attempts=True)
        redriven_ids.append(r["id"])

    return {"redriven_count": len(redriven_ids), "job_ids": redriven_ids}
