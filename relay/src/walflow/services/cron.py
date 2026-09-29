"""Drift-free SQLite Cron Engine: multi-worker safe periodic scheduling."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from walflow.domain.clock import Clock
from walflow.domain.errors import ValidationError
from walflow.domain.registry import validate_payload
from walflow.domain.validation import bounded_json, integer, queue_name
from walflow.services.submit import submit_job
from walflow.storage.transactions import write_tx


class CronParseError(ValidationError):
    """Raised when a cron expression is malformed."""


def _parse_field(field: str, min_val: int, max_val: int) -> set[int]:
    """Parse one cron field containing numbers, *, /, -, and commas."""
    field = field.strip()
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            range_part, step_str = part.split("/", 1)
            try:
                step = int(step_str)
                if step <= 0:
                    raise ValueError
            except ValueError:
                raise CronParseError(f"invalid step in cron field: {part}") from None
        else:
            range_part = part

        if range_part == "*":
            low, high = min_val, max_val
        elif "-" in range_part:
            pieces = range_part.split("-", 1)
            try:
                low, high = int(pieces[0]), int(pieces[1])
            except ValueError:
                raise CronParseError(f"invalid range in cron field: {part}") from None
        else:
            try:
                low = high = int(range_part)
            except ValueError:
                raise CronParseError(f"invalid integer in cron field: {part}") from None

        if low < min_val or high > max_val or low > high:
            raise CronParseError(f"value {range_part} outside legal bounds {min_val}..{max_val}")
        for v in range(low, high + 1, step):
            values.add(v)
    if not values:
        raise CronParseError(f"empty cron field: {field}")
    return values


_SHORTCUTS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


def compute_next_run(expression: str, from_ms: int) -> int:
    """Compute the next UTC execution timestamp in milliseconds from a cron expression."""
    expr = expression.strip()
    if expr in _SHORTCUTS:
        expr = _SHORTCUTS[expr]

    parts = expr.split()
    if len(parts) != 5:
        raise CronParseError("cron expression must contain exactly 5 space-separated fields")

    minutes = _parse_field(parts[0], 0, 59)
    hours = _parse_field(parts[1], 0, 23)
    days = _parse_field(parts[2], 1, 31)
    months = _parse_field(parts[3], 1, 12)
    weekdays = _parse_field(parts[4], 0, 7)  # 0 or 7 = Sunday
    if 7 in weekdays:
        weekdays.add(0)

    # Search forward minute by minute up to 366 days
    current = datetime.fromtimestamp(from_ms / 1000, UTC).replace(second=0, microsecond=0)
    current += timedelta(minutes=1)
    limit = current + timedelta(days=366)

    while current < limit:
        if (
            current.month in months
            and current.day in days
            and current.weekday() in weekdays
            and current.hour in hours
            and current.minute in minutes
        ):
            return int(current.timestamp() * 1000)
        # Advance minute
        current += timedelta(minutes=1)

    raise CronParseError("could not find next execution time within 1 year")


def add_schedule(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    name: str,
    expression: str,
    handler: str,
    payload: dict[str, Any],
    queue: str = "default",
    priority: int = 0,
    timeout_ms: int = 60_000,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Register or replace a recurring cron schedule."""
    if not isinstance(name, str) or not 1 <= len(name) <= 64:
        raise ValidationError("schedule name must be 1..64 characters")
    queue_name(queue)
    integer(priority, "priority", -100, 100)
    integer(timeout_ms, "timeout_ms", 1, 600_000)
    integer(max_attempts, "max_attempts", 1, 10)
    validate_payload(handler, payload)
    payload_json = bounded_json(payload)
    now = clock.now_ms()
    next_run_at = compute_next_run(expression, now)

    def _body(c: sqlite3.Connection) -> dict[str, Any]:
        c.execute(
            """INSERT INTO cron_schedules(
                name, expression, handler, payload_json, queue, priority,
                timeout_ms, max_attempts, next_run_at, paused, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,0,?)
            ON CONFLICT(name) DO UPDATE SET
                expression=excluded.expression,
                handler=excluded.handler,
                payload_json=excluded.payload_json,
                queue=excluded.queue,
                priority=excluded.priority,
                timeout_ms=excluded.timeout_ms,
                max_attempts=excluded.max_attempts,
                next_run_at=excluded.next_run_at""",
            (
                name,
                expression,
                handler,
                payload_json,
                queue,
                priority,
                timeout_ms,
                max_attempts,
                next_run_at,
                now,
            ),
        )
        return {
            "name": name,
            "expression": expression,
            "handler": handler,
            "next_run_at": next_run_at,
            "paused": False,
        }

    return write_tx(conn, _body)


def evaluate_due_schedules(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    batch_limit: int = 20,
) -> list[dict[str, Any]]:
    """Atomically evaluate due schedules and submit idempotent jobs."""
    now = clock.now_ms()
    spawned: list[dict[str, Any]] = []

    rows = conn.execute(
        """SELECT name, expression, handler, payload_json, queue, priority,
                  timeout_ms, max_attempts, next_run_at
           FROM cron_schedules
           WHERE paused=0 AND next_run_at <= ?
           ORDER BY next_run_at ASC LIMIT ?""",
        (now, batch_limit),
    ).fetchall()

    for row in rows:
        name = row["name"]
        scheduled_ts = row["next_run_at"]
        next_ts = compute_next_run(row["expression"], now)

        def _claim(
            c: sqlite3.Connection, n: str = name, n_ts: int = next_ts, s_ts: int = scheduled_ts
        ) -> bool:
            cur = c.execute(
                """UPDATE cron_schedules
                   SET next_run_at=?, last_run_at=?
                   WHERE name=? AND next_run_at<=? AND paused=0""",
                (n_ts, now, n, s_ts),
            )
            return cur.rowcount == 1

        if not write_tx(conn, _claim):
            continue

        # Enqueue the job with deterministic idempotency
        idemp_key = f"cron:{name}:{scheduled_ts}"
        payload = json.loads(row["payload_json"])
        result = submit_job(
            conn,
            clock=clock,
            handler=row["handler"],
            payload=payload,
            queue=row["queue"],
            priority=row["priority"],
            timeout_ms=row["timeout_ms"],
            max_attempts=row["max_attempts"],
            idempotency_key=idemp_key,
        )
        spawned.append(
            {
                "schedule_name": name,
                "job_id": result["job_id"],
                "scheduled_at": scheduled_ts,
                "next_run_at": next_ts,
            }
        )

    return spawned


def list_schedules(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all configured cron schedules."""
    rows = conn.execute(
        """SELECT name, expression, handler, payload_json, queue, priority,
                  timeout_ms, max_attempts, next_run_at, last_run_at, paused, created_at
           FROM cron_schedules
           ORDER BY name ASC"""
    ).fetchall()
    return [
        {
            "name": r["name"],
            "expression": r["expression"],
            "handler": r["handler"],
            "payload": json.loads(r["payload_json"]),
            "queue": r["queue"],
            "priority": r["priority"],
            "timeout_ms": r["timeout_ms"],
            "max_attempts": r["max_attempts"],
            "next_run_at": r["next_run_at"],
            "last_run_at": r["last_run_at"],
            "paused": bool(r["paused"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def pause_schedule(conn: sqlite3.Connection, *, name: str) -> bool:
    """Pause an existing schedule."""
    cur = conn.execute("UPDATE cron_schedules SET paused=1 WHERE name=?", (name,))
    return cur.rowcount == 1


def resume_schedule(conn: sqlite3.Connection, *, clock: Clock, name: str) -> bool:
    """Resume a paused schedule and compute the next run time."""
    now = clock.now_ms()
    row = conn.execute("SELECT expression FROM cron_schedules WHERE name=?", (name,)).fetchone()
    if row is None:
        return False
    next_run = compute_next_run(row["expression"], now)
    cur = conn.execute(
        "UPDATE cron_schedules SET paused=0, next_run_at=? WHERE name=?",
        (next_run, name),
    )
    return cur.rowcount == 1


def delete_schedule(conn: sqlite3.Connection, *, name: str) -> bool:
    """Delete a schedule."""
    cur = conn.execute("DELETE FROM cron_schedules WHERE name=?", (name,))
    return cur.rowcount == 1


def trigger_schedule_now(conn: sqlite3.Connection, *, clock: Clock, name: str) -> dict[str, Any]:
    """Trigger an immediate execution of a schedule."""
    now = clock.now_ms()
    row = conn.execute(
        """SELECT name, handler, payload_json, queue, priority, timeout_ms, max_attempts
           FROM cron_schedules WHERE name=?""",
        (name,),
    ).fetchone()
    if row is None:
        raise ValidationError(f"schedule {name} not found")

    idemp_key = f"cron-manual:{name}:{now}"
    payload = json.loads(row["payload_json"])
    result = submit_job(
        conn,
        clock=clock,
        handler=row["handler"],
        payload=payload,
        queue=row["queue"],
        priority=row["priority"],
        timeout_ms=row["timeout_ms"],
        max_attempts=row["max_attempts"],
        idempotency_key=idemp_key,
    )
    return {"schedule_name": name, "job_id": result["job_id"]}
