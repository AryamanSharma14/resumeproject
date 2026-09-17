"""Local operations shared by HTTP and CLI; maintenance paths are never HTTP inputs.

Pruning preserves ancestors of retained reruns (including their keys/history).
Deleting a complete terminal lineage expires all keys pointing to deleted jobs.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from relay.domain.clock import Clock
from relay.domain.contracts import SubmitResult
from relay.domain.errors import (
    IdempotencyConflictError,
    JobNotFoundError,
    RelayError,
    ValidationError,
)
from relay.domain.registry import HANDLERS, validate_payload
from relay.domain.states import TERMINAL_STATES
from relay.storage.transactions import connect, write_tx


class JobNotRerunnableError(RelayError):
    code = "JOB_NOT_RERUNNABLE"


def rerun_job(
    conn: sqlite3.Connection, *, clock: Clock, job_id: str, idempotency_key: str
) -> SubmitResult:
    if not 1 <= len(idempotency_key) <= 200:
        raise ValidationError("idempotency key must be 1..200 characters")
    digest = hashlib.sha256(job_id.encode()).hexdigest()

    def operation(c: sqlite3.Connection) -> SubmitResult:
        previous = c.execute(
            "SELECT request_hash,job_id FROM idempotency_records WHERE scope='rerun' AND key=?",
            (idempotency_key,),
        ).fetchone()
        if previous is not None:
            if previous["request_hash"] != digest:
                raise IdempotencyConflictError("key reused for a different rerun")
            return {"job_id": str(previous["job_id"]), "replayed": True}
        source = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if source is None:
            raise JobNotFoundError("job not found")
        if source["state"] not in TERMINAL_STATES:
            raise JobNotRerunnableError("only terminal jobs may be rerun")
        validate_payload(source["handler"], json.loads(source["payload_json"]))
        if HANDLERS[source["handler"]].version != source["handler_version"]:
            raise JobNotRerunnableError("original handler version is unavailable")
        new_id, now = str(uuid.uuid4()), clock.now_ms()
        c.execute(
            """INSERT INTO jobs(id,handler,handler_version,queue,payload_json,state,
            priority,created_at,updated_at,available_at,max_attempts,timeout_ms,rerun_of)
            VALUES(?,?,?,?,?,'queued',?,?,?,?,?,?,?)""",
            (
                new_id,
                source["handler"],
                source["handler_version"],
                source["queue"],
                source["payload_json"],
                source["priority"],
                now,
                now,
                now,
                source["max_attempts"],
                source["timeout_ms"],
                job_id,
            ),
        )
        c.execute(
            "INSERT INTO job_events(job_id,kind,created_at,detail_json) VALUES(?,'submitted',?,?)",
            (new_id, now, json.dumps({"rerun_of": job_id})),
        )
        c.execute(
            "INSERT INTO idempotency_records(scope,key,request_hash,job_id,created_at) "
            "VALUES('rerun',?,?,?,?)",
            (idempotency_key, digest, new_id, now),
        )
        return {"job_id": new_id, "replayed": False}

    return write_tx(conn, operation)


def backup_database(db_path: str, destination: str) -> dict[str, str]:
    """Exclusive-create a consistent online SQLite backup; never overwrite files."""
    source, target = Path(db_path).resolve(), Path(destination).resolve()
    if source == target or not source.is_file():
        raise ValidationError("backup requires an existing source and a distinct destination")
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    deadline = time.monotonic() + 15

    def progress(status: int, remaining: int, total: int) -> None:
        if time.monotonic() > deadline:
            raise TimeoutError("backup exceeded bounded deadline")

    try:
        # Restrict the empty file before writing any queue data (POSIX mode / Windows ACL).
        from relay.config import _restrict

        _restrict(target)
        with closing(connect(str(source))) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst, pages=128, progress=progress, sleep=0.05)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValidationError("backup integrity check failed")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"path": str(target)}


def prune_jobs(db_path: str, before_ms: int, dry_run: bool = True) -> dict[str, int | bool]:
    """Terminal-only retention. Retained descendants protect their entire ancestry."""
    if type(before_ms) is not int or before_ms < 0:
        raise ValidationError("before_ms must be a nonnegative integer")

    def operation(c: sqlite3.Connection) -> dict[str, int | bool]:
        c.execute("CREATE TEMP TABLE prune_candidates(id TEXT PRIMARY KEY)")
        c.execute(
            """INSERT INTO prune_candidates SELECT id FROM jobs
            WHERE state IN ('succeeded','failed','canceled') AND finished_at < ?""",
            (before_ms,),
        )
        while c.execute(
            """DELETE FROM prune_candidates WHERE id IN
            (SELECT rerun_of FROM jobs WHERE id NOT IN (SELECT id FROM prune_candidates)
            AND rerun_of IS NOT NULL)"""
        ).rowcount:
            pass
        count = int(c.execute("SELECT count(*) FROM prune_candidates").fetchone()[0])
        if not dry_run:
            for table in ("job_events", "attempts", "idempotency_records"):
                c.execute(f"DELETE FROM {table} WHERE job_id IN (SELECT id FROM prune_candidates)")
            c.execute("DELETE FROM jobs WHERE id IN (SELECT id FROM prune_candidates)")
        c.execute("DROP TABLE prune_candidates")
        return {"dry_run": dry_run, "jobs": count}

    with closing(connect(db_path)) as conn:
        return write_tx(conn, operation)
