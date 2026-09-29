"""Job submission with idempotency (scenarios T02, T03).

Same key + same request -> original job (replay). Same key + different
request -> IdempotencyConflictError. Resolution happens inside one
BEGIN IMMEDIATE transaction guarded by UNIQUE(scope, key) - never a
check-then-insert race.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any, Final

from walflow.domain import policies as retry_policy
from walflow.domain.clock import Clock
from walflow.domain.contracts import SubmitResult
from walflow.domain.errors import (
    IdempotencyConflictError,
    UnknownQueueError,
    ValidationError,
)
from walflow.domain.registry import HANDLERS, validate_payload
from walflow.domain.validation import bounded_json, integer, queue_name
from walflow.storage.transactions import write_tx

MAX_IDEMPOTENCY_KEY_LEN: Final = 200
DEFAULT_QUEUE: Final = "default"
DEFAULT_MAX_ATTEMPTS: Final = 3
DEFAULT_TIMEOUT_MS: Final = 30_000
MAX_DELAY_MS: Final = 3_600_000


def _request_hash(
    handler: str,
    payload: dict[str, Any],
    queue: str,
    priority: int,
    delay_ms: int,
    max_attempts: int,
    timeout_ms: int,
) -> str:
    canonical = json.dumps(
        {
            "handler": handler,
            "payload": payload,
            "queue": queue,
            "priority": priority,
            "delay_ms": delay_ms,
            "max_attempts": max_attempts,
            "timeout_ms": timeout_ms,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def submit_job(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    handler: str,
    payload: dict[str, Any],
    queue: str = DEFAULT_QUEUE,
    priority: int = 0,
    delay_ms: int = 0,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    idempotency_scope: str = "submit",
    idempotency_key: str | None = None,
    depends_on: list[str] | None = None,
) -> SubmitResult:
    """Validate, insert one queued job (+submitted event), resolve idempotency.

    Returns {"job_id": str, "replayed": bool}.
    """
    payload_json = bounded_json(payload)
    validate_payload(handler, payload)
    queue_name(queue)
    queue_name(idempotency_scope)
    integer(delay_ms, "delay_ms", 0, MAX_DELAY_MS)
    integer(priority, "priority", -100, 100)
    retry_policy.clamp_max_attempts(max_attempts)
    integer(timeout_ms, "timeout_ms", 1, 600_000)
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str)
        or not 1 <= len(idempotency_key) <= MAX_IDEMPOTENCY_KEY_LEN
    ):
        raise ValidationError("idempotency key must be 1..200 characters")
    if depends_on is not None and (
        not isinstance(depends_on, list)
        or not all(isinstance(pid, str) and 1 <= len(pid) <= 64 for pid in depends_on)
    ):
        raise ValidationError("depends_on must be a list of job ID strings")
    request_hash = _request_hash(
        handler, payload, queue, priority, delay_ms, max_attempts, timeout_ms
    )

    def _body(c: sqlite3.Connection) -> SubmitResult:
        now = clock.now_ms()
        q = c.execute("SELECT 1 FROM queues WHERE name=?", (queue,)).fetchone()
        if q is None:
            raise UnknownQueueError(f"unknown queue: {queue}")

        if idempotency_key is not None:
            row = c.execute(
                "SELECT request_hash, job_id FROM idempotency_records WHERE scope=? AND key=?",
                (idempotency_scope, idempotency_key),
            ).fetchone()
            if row is not None:
                if row["request_hash"] != request_hash:
                    raise IdempotencyConflictError(
                        "idempotency key reused with a different request"
                    )
                return {"job_id": row["job_id"], "replayed": True}

        pending_deps = 0
        actual_available_at = now + delay_ms
        if depends_on:
            placeholders = ",".join("?" for _ in depends_on)
            parent_rows = c.execute(
                f"SELECT id, state FROM jobs WHERE id IN ({placeholders})", depends_on
            ).fetchall()
            found_ids = {r["id"] for r in parent_rows}
            for pid in depends_on:
                if pid not in found_ids:
                    raise ValidationError(f"prerequisite job {pid} not found")
            for r in parent_rows:
                if r["state"] in ("failed", "canceled"):
                    raise ValidationError(f"prerequisite job {r['id']} has already {r['state']}")
                if r["state"] != "succeeded":
                    pending_deps += 1
            if pending_deps > 0:
                actual_available_at = 9_223_372_036_854_775_807  # Sentinel: future blocked

        job_id = str(uuid.uuid4())
        c.execute(
            """INSERT INTO jobs(id, handler, handler_version, queue, payload_json, state,
                 priority, created_at, updated_at, available_at, attempt_count, max_attempts,
                 timeout_ms, pending_dependencies_count)
               VALUES(?,?,?,?,?,'queued',?,?,?,?,0,?,?,?)""",
            (
                job_id,
                handler,
                HANDLERS[handler].version,
                queue,
                payload_json,
                priority,
                now,
                now,
                actual_available_at,
                max_attempts,
                timeout_ms,
                pending_deps,
            ),
        )
        c.execute(
            """INSERT INTO job_events(job_id, attempt_id, kind, created_at)
               VALUES(?,NULL,'submitted',?)""",
            (job_id, now),
        )
        if depends_on:
            for pid in set(depends_on):
                c.execute(
                    "INSERT OR IGNORE INTO job_dependencies(parent_id, child_id, created_at) "
                    "VALUES(?,?,?)",
                    (pid, job_id, now),
                )
        if idempotency_key is not None:
            c.execute(
                """INSERT INTO idempotency_records(scope, key, request_hash, job_id, created_at)
                   VALUES(?,?,?,?,?)""",
                (idempotency_scope, idempotency_key, request_hash, job_id, now),
            )
        return {"job_id": job_id, "replayed": False}

    return write_tx(conn, _body)
