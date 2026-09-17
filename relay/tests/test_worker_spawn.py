"""Real Windows/Linux spawn acceptance tests; no API process is required."""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from relay.domain.clock import SystemClock
from relay.services.setup import ensure_queue
from relay.services.submit import submit_job
from relay.storage.migrations import apply_migrations
from relay.storage.transactions import connect
from relay.worker import Supervisor, WorkerConfig
from relay.worker.ipc import MAX_MESSAGE_BYTES, child_main, encode


def run_worker(path: str, duration: float, grace: int = 2000) -> None:
    Supervisor(
        WorkerConfig(
            path,
            concurrency=1,
            lease_ms=1200,
            heartbeat_ms=200,
            recovery_ms=100,
            poll_ms=20,
            grace_ms=grace,
        )
    ).run(max_runtime=duration)


def wait_for(check: Callable[[], bool], timeout: float = 12) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.03)
    raise AssertionError("bounded process condition did not become true")


def database(tmp_path: Path) -> tuple[str, sqlite3.Connection]:
    path = str(tmp_path / "relay.db")
    conn = connect(path)
    apply_migrations(conn)
    ensure_queue(conn, clock=SystemClock(), name="default")
    return path, conn


def submit(
    conn: sqlite3.Connection,
    handler: str = "text_summary",
    payload: dict[str, object] | None = None,
    timeout: int = 5000,
    attempts: int = 1,
) -> str:
    return submit_job(
        conn,
        clock=SystemClock(),
        handler=handler,
        payload=payload or {"text": "spawn hello"},
        timeout_ms=timeout,
        max_attempts=attempts,
    )["job_id"]


def state(conn: sqlite3.Connection, job: str) -> str:
    return str(conn.execute("SELECT state FROM jobs WHERE id=?", (job,)).fetchone()[0])


def test_t13_real_child_timeout_frees_slot(tmp_path: Path) -> None:
    path, conn = database(tmp_path)
    process = multiprocessing.get_context("spawn").Process(target=run_worker, args=(path, 3))
    try:
        hung = submit(conn, "demo_delay", {"duration_ms": 5000}, timeout=350)
        next_job = submit(conn)
        process.start()
        wait_for(lambda: state(conn, next_job) == "succeeded")
        assert state(conn, hung) == "failed"
        assert (
            conn.execute("SELECT state FROM attempts WHERE job_id=?", (hung,)).fetchone()[0]
            == "timed_out"
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM job_events WHERE job_id=? AND kind='timed_out'", (hung,)
            ).fetchone()[0]
            == 1
        )
        process.join(8)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.kill()
        process.join(3)
        conn.close()


def test_t12_t14_t15_kill_and_restart_recovers_without_api(tmp_path: Path) -> None:
    path, conn = database(tmp_path)
    context = multiprocessing.get_context("spawn")
    first = context.Process(target=run_worker, args=(path, 30))
    second = context.Process(target=run_worker, args=(path, 4))
    try:
        job = submit(conn, "demo_delay", {"duration_ms": 10000}, timeout=20000)
        first.start()
        wait_for(lambda: state(conn, job) == "running")
        first.kill()
        first.join(3)
        # No maintenance is alive: persisted state does not magically change.
        time.sleep(1.4)
        assert state(conn, job) == "running"
        second.start()
        wait_for(lambda: state(conn, job) == "failed")
        assert (
            conn.execute("SELECT state FROM attempts WHERE job_id=?", (job,)).fetchone()[0]
            == "lost"
        )
        assert (
            conn.execute("SELECT count(*) FROM job_events WHERE kind='attempt_lost'").fetchone()[0]
            == 1
        )
        second.join(8)
        assert second.exitcode == 0
    finally:
        for process in (first, second):
            if process.is_alive():
                process.kill()
            if process.pid is not None:
                process.join(3)
        conn.close()


def test_drain_finishes_inflight_without_claiming_next(tmp_path: Path) -> None:
    path, conn = database(tmp_path)
    process = multiprocessing.get_context("spawn").Process(target=run_worker, args=(path, 0.3))
    try:
        job = submit(conn, "demo_delay", {"duration_ms": 800})
        pending = submit(conn)
        process.start()
        process.join(8)
        assert process.exitcode == 0
        assert state(conn, job) == "succeeded"
        assert state(conn, pending) == "queued"
        assert conn.execute("SELECT state FROM workers").fetchone()[0] == "offline"
    finally:
        if process.is_alive():
            process.kill()
        process.join(3)
        conn.close()


def test_t19_bounded_json_ipc_rejects_oversize_and_garbage(tmp_path: Path) -> None:
    """Oversized and malformed messages fail as CHILD_PROTOCOL_ERROR, no pickle."""
    parent, child = multiprocessing.Pipe(duplex=True)
    process = multiprocessing.get_context("spawn").Process(target=child_main, args=(child,))

    try:
        process.start()
        child.close()
        with pytest.raises(ValueError):
            encode(
                {
                    "handler": "text_summary",
                    "version": "1",
                    "payload": {"text": "x" * (MAX_MESSAGE_BYTES + 10)},
                }
            )
        parent.send_bytes(b"\x80\x81\x82 definitely not json"[:MAX_MESSAGE_BYTES])
        response = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if parent.poll(0.1):
                response = json.loads(parent.recv_bytes(MAX_MESSAGE_BYTES))
                break
        assert response is not None and response["ok"] is False
        assert response["code"] == "CHILD_PROTOCOL_ERROR"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(2)
        if process.pid is not None:
            process.close()
        parent.close()


def test_flaky_handler_retries_then_succeeds(tmp_path: Path) -> None:
    path, conn = database(tmp_path)
    process = multiprocessing.get_context("spawn").Process(target=run_worker, args=(path, 4))
    try:
        job = submit(conn, "demo_flaky", {"fail_times": 1}, attempts=2)
        process.start()
        wait_for(lambda: state(conn, job) == "succeeded")
        assert (
            conn.execute("SELECT count(*) FROM attempts WHERE job_id=?", (job,)).fetchone()[0] == 2
        )
        process.join(8)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.kill()
        process.join(3)
        conn.close()
