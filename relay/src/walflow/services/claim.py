"""Atomic claim with lease fencing (scenarios T04, T10).

Claim order: priority DESC, available_at ASC, created_at ASC, id ASC - FIFO
within the stated constraints. The conditional UPDATE verifies eligibility
inside BEGIN IMMEDIATE; rowcount decides success. The attempt row and claimed
event are inserted only when rowcount == 1.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping

from walflow.domain.clock import Clock
from walflow.domain.contracts import ClaimResult
from walflow.domain.errors import ValidationError
from walflow.domain.registry import HANDLERS, get_handler
from walflow.domain.states import CLAIMABLE_STATES, EVENT_CLAIMED
from walflow.domain.validation import integer, queue_name
from walflow.storage.transactions import immediate_transaction


def claim_job(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    worker_id: str,
    queues: list[str],
    handlers: list[str],
    lease_ms: int = 30_000,
    handler_versions: Mapping[str, str] | None = None,
) -> ClaimResult | None:
    """Try to claim one due job; return claim info or None.

    Attempt numbering happens in-transaction from attempt_count (never MAX()
    outside the fence). The attempt token is unique per attempt and gates all
    later completion/heartbeat writes.
    """
    integer(lease_ms, "lease_ms", 1, 600_000)
    if not isinstance(worker_id, str) or not 1 <= len(worker_id) <= 200:
        raise ValidationError("worker_id must be 1..200 characters")
    if not isinstance(queues, list) or not isinstance(handlers, list):
        raise ValidationError("queues and handlers must be lists")
    if not queues or not handlers:
        raise ValidationError("queues and handlers must be non-empty")
    for queue in queues:
        queue_name(queue)
    for name in handlers:
        get_handler(name)
    versions = (
        handler_versions
        if handler_versions is not None
        else {name: spec.version for name, spec in HANDLERS.items()}
    )
    if not isinstance(versions, Mapping):
        raise ValidationError("handler_versions must be a mapping")
    for name in handlers:
        version = versions.get(name)
        if not isinstance(version, str) or not 1 <= len(version) <= 32:
            raise ValidationError("each advertised handler needs a version of 1..32 characters")
    if not queues or not handlers:
        raise ValidationError("queues and handlers must be non-empty")
    pairs = [
        (name, versions[name])
        for name in dict.fromkeys(handlers)
        if versions[name] == HANDLERS[name].version
    ]
    if not pairs:
        return None
    placeholders_q = ",".join("?" for _ in queues)
    compatible = " OR ".join("(handler=? AND handler_version=?)" for _ in pairs)
    state_list = ",".join("?" for _ in CLAIMABLE_STATES)
    token = uuid.uuid4().hex
    attempt_id = str(uuid.uuid4())

    def _body(c: sqlite3.Connection) -> ClaimResult | None:
        now = clock.now_ms()
        lease_expires_at = now + lease_ms
        row = c.execute(
            f"""SELECT id, handler, handler_version, payload_json, attempt_count, timeout_ms, queue
                FROM jobs
                WHERE state IN ({state_list})
                  AND available_at <= ? AND attempt_count < max_attempts
                  AND queue IN ({placeholders_q})
                  AND queue IN (SELECT name FROM queues WHERE paused=0)
                  AND ({compatible})
                ORDER BY priority DESC, available_at ASC, created_at ASC, id ASC
                LIMIT 1""",
            (*CLAIMABLE_STATES, now, *queues, *(v for pair in pairs for v in pair)),
        ).fetchone()
        if row is None:
            return None

        job_id = row["id"]
        number = row["attempt_count"] + 1
        updated = c.execute(
            f"""UPDATE jobs
               SET state='running', updated_at=?, started_at=COALESCE(started_at, ?),
                   active_attempt_id=?, owner_token=?, lease_expires_at=?,
                   attempt_count=attempt_count+1
               WHERE id=? AND state IN ({state_list}) AND available_at <= ?""",
            (now, now, attempt_id, token, lease_expires_at, job_id, *CLAIMABLE_STATES, now),
        )
        if updated.rowcount != 1:
            return None  # concurrent transition won the race; caller re-polls

        c.execute(
            """INSERT INTO attempts(id, job_id, number, owner_token, worker_id, state,
                 started_at, lease_expires_at)
               VALUES(?,?,?,?,?, 'running', ?, ?)""",
            (attempt_id, job_id, number, token, worker_id, now, lease_expires_at),
        )
        c.execute(
            "INSERT INTO job_events(job_id, attempt_id, kind, created_at) VALUES(?,?,?,?)",
            (job_id, attempt_id, EVENT_CLAIMED, now),
        )
        return {
            "job_id": job_id,
            "attempt_id": attempt_id,
            "attempt_number": number,
            "owner_token": token,
            "handler": row["handler"],
            "handler_version": row["handler_version"],
            "timeout_ms": row["timeout_ms"],
            "payload": row["payload_json"],
            "payload_data": json.loads(row["payload_json"]),
            "queue": row["queue"],
            "lease_expires_at": lease_expires_at,
        }

    with immediate_transaction(conn):
        return _body(conn)
