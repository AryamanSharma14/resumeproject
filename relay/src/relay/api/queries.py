"""Bounded read models. Cursors are stable keys, not snapshot promises."""

from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from relay.domain.errors import JobNotFoundError, ValidationError
from relay.domain.states import JOB_STATES
from relay.domain.validation import queue_name


def timestamp(ms: int) -> str:
    return (
        datetime.fromtimestamp(ms / 1000, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def parse_timestamp(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or "T" not in value:
            raise ValueError
        return int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError):
        raise ValidationError("time must be an RFC3339 timestamp with timezone") from None


def serialize(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in row.keys():  # noqa: SIM118 -- sqlite3.Row iteration yields values, not keys
        value = row[key]
        if key == "owner_token":
            continue
        if key.endswith("_json"):
            result[key.removesuffix("_json")] = json.loads(value) if value is not None else None
        elif key.endswith("_at"):
            result[key] = timestamp(value) if value is not None else None
        elif key == "paused":
            result[key] = bool(value)
        else:
            result[key] = value
    return result


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise JobNotFoundError("job not found")
    return serialize(row)


def list_jobs(
    conn: sqlite3.Connection,
    *,
    state: str | None = None,
    queue: str | None = None,
    handler: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    conditions: list[str] = []
    values: list[Any] = []
    if state is not None and state not in JOB_STATES:
        raise ValidationError("unknown job state")
    if queue is not None:
        queue_name(queue)
    for column, value in (("state", state), ("queue", queue), ("handler", handler)):
        if value is not None:
            conditions.append(f"{column}=?")
            values.append(value)
    for name, value, operator in (
        ("created_at", created_after, ">="),
        ("created_at", created_before, "<"),
    ):
        if value is not None:
            conditions.append(f"{name}{operator}?")
            values.append(parse_timestamp(value))
    if cursor is not None:
        try:
            key = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if (
                not isinstance(key, list)
                or len(key) != 2
                or type(key[0]) is not int
                or not isinstance(key[1], str)
            ):
                raise ValueError
        except (ValueError, binascii.Error, UnicodeError):
            raise ValidationError("invalid jobs cursor") from None
        conditions.append("(created_at < ? OR (created_at = ? AND id < ?))")
        values.extend((key[0], key[0], key[1]))
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        "SELECT * FROM jobs" + where + " ORDER BY created_at DESC,id DESC LIMIT ?",
        (*values, limit + 1),
    ).fetchall()
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps([last["created_at"], last["id"]]).encode()
        ).decode()
    return {"items": [serialize(row) for row in rows[:limit]], "next_cursor": next_cursor}


def history(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    events: bool,
    cursor: int,
    limit: int,
) -> dict[str, Any]:
    get_job(conn, job_id)
    table, key = ("job_events", "seq") if events else ("attempts", "number")
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE job_id=? AND {key}>? ORDER BY {key} LIMIT ?",
        (job_id, cursor, limit + 1),
    ).fetchall()
    return {
        "items": [serialize(row) for row in rows[:limit]],
        "next_cursor": str(rows[limit - 1][key]) if len(rows) > limit else None,
    }


def queues(conn: sqlite3.Connection, now: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT q.*, count(j.id) AS due_depth, min(j.available_at) AS oldest_due
        FROM queues q LEFT JOIN jobs j ON j.queue=q.name
        AND j.state IN ('queued','retry_wait') AND j.available_at<=?
        GROUP BY q.name ORDER BY q.name""",
        (now,),
    ).fetchall()
    result = []
    for row in rows:
        item = serialize(row)
        oldest = item.pop("oldest_due")
        item["oldest_due_age_ms"] = max(0, now - oldest) if oldest is not None else None
        result.append(item)
    return result


def workers(
    conn: sqlite3.Connection,
    now: int,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT w.*, (SELECT count(*) FROM attempts a WHERE a.worker_id=w.id
        AND a.state='running' AND a.lease_expires_at>?) AS active_attempts
        FROM workers w WHERE w.id>? ORDER BY w.id LIMIT ?""",
        (now, cursor or "", limit + 1),
    ).fetchall()
    items = []
    for row in rows[:limit]:
        item = serialize(row)
        age = max(0, now - row["heartbeat_at"])
        availability = "stale" if age > 30_000 and row["state"] != "offline" else row["state"]
        item.update(
            heartbeat_age_ms=age,
            availability=availability,
            available_slots=max(0, row["concurrency"] - row["active_attempts"])
            if availability == "online"
            else 0,
        )
        items.append(item)
    return {"items": items, "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None}


def overview(conn: sqlite3.Connection, now: int) -> dict[str, Any]:
    conn.execute("BEGIN")
    try:
        counts = dict.fromkeys(sorted(JOB_STATES), 0)
        counts.update(dict(conn.execute("SELECT state,count(*) FROM jobs GROUP BY state")))
        worker_counts = dict(
            conn.execute(
                """SELECT CASE WHEN state!='offline' AND heartbeat_at<? THEN 'stale' ELSE state END,
            count(*) FROM workers GROUP BY 1""",
                (now - 30_000,),
            )
        )
        result = {
            "as_of": timestamp(now),
            "window": "retained",
            "jobs": counts,
            "queues": queues(conn, now),
            "workers": worker_counts,
        }
        conn.execute("COMMIT")
        return result
    except BaseException:
        conn.execute("ROLLBACK")
        raise
