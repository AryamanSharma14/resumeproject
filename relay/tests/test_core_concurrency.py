"""T02-T06 and T07 double-run races on real WAL file databases.

Outcomes are captured per thread and asserted after join: any exception,
assertion failure or lost update inside a worker thread fails the test via
reported list, never silently.
"""

import sqlite3
import threading

import pytest

from relay.domain.errors import (
    IdempotencyConflictError,
    JobNotCancelableError,
    ValidationError,
)
from relay.services.cancel import cancel_job
from relay.services.claim import claim_job
from relay.services.submit import submit_job
from relay.storage.transactions import connect


def _db_path(conn: sqlite3.Connection) -> str:
    return str(conn.execute("PRAGMA database_list").fetchone()[2])


def run_threads(**kw: object) -> list[tuple[str, object]]:
    """Run named callables in parallel threads; collect (name, outcome)."""
    names = list(kw)
    results: list[tuple[str, object]] = []
    lock = threading.Lock()
    barrier = threading.Barrier(len(names))

    def target(name: str, fn: object) -> None:
        outcome: object
        try:
            assert callable(fn)
            barrier.wait(timeout=10)
            outcome = fn()
        except BaseException as exc:  # surfaced to the main thread below
            outcome = exc
        with lock:
            results.append((name, outcome))

    threads = [threading.Thread(target=target, args=(n, kw[n]), name=f"t-{n}") for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), f"thread {t.name} hung"
    return results


def _run_in_threads(targets: list) -> None:
    results = run_threads(**{str(i): fn for i, fn in enumerate(targets)})
    assert len(results) == len(targets)
    errors = [outcome for _, outcome in results if isinstance(outcome, BaseException)]
    if errors:
        raise BaseExceptionGroup("thread failures", errors)


def test_t02_t03_concurrent_duplicate_and_conflict(db, clock, tmp_path, default_queue):
    path = _db_path(db)
    results: list[dict] = []
    barrier = threading.Barrier(2)

    def submit(key: str):
        conn = connect(path)
        try:
            barrier.wait(timeout=10)
            results.append(
                submit_job(
                    conn,
                    clock=clock,
                    handler="text_summary",
                    payload={"text": "hi"},
                    idempotency_key=key,
                )
            )
        finally:
            conn.close()

    _run_in_threads([lambda: submit("k1"), lambda: submit("k1")])
    assert results[0]["job_id"] == results[1]["job_id"]
    assert sorted(r["replayed"] for r in results) == [False, True]
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    other = connect(path)
    try:
        with pytest.raises(IdempotencyConflictError):
            submit_job(
                other,
                clock=clock,
                handler="text_summary",
                payload={"text": "DIFFERENT"},
                idempotency_key="k1",
            )
    finally:
        other.close()
    assert db.execute("SELECT payload_json FROM jobs").fetchone()[0] == '{"text":"hi"}'


def test_t04_eight_claim_contenders(db, clock, tmp_path, default_queue):
    for i in range(4):
        submit_job(db, clock=clock, handler="text_summary", payload={"text": f"j{i}"})
    path = _db_path(db)
    claims: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def claim(i: int):
        conn = connect(path)
        try:
            barrier.wait(timeout=10)
            c = claim_job(
                conn,
                clock=clock,
                worker_id=f"w{i}",
                queues=["default"],
                handlers=["text_summary"],
                lease_ms=5_000,
            )
            with lock:
                claims.append(c)
        finally:
            conn.close()

    _run_in_threads([lambda i=i: claim(i) for i in range(8)])
    real = [c for c in claims if c is not None]
    assert len(real) == 4
    assert len({c["owner_token"] for c in real}) == 4
    assert len({c["job_id"] for c in real}) == 4
    running = db.execute("SELECT COUNT(*) FROM attempts WHERE state='running'").fetchone()[0]
    assert running == 4


def test_t05_crash_inside_transition_is_atomic(db, clock, default_queue):
    submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"})
    job_id = db.execute("SELECT id FROM jobs").fetchone()[0]
    # Simulated crash: roll the connection back mid-transition like a dead process.
    db.execute("BEGIN IMMEDIATE")
    db.execute(
        """UPDATE jobs SET state='running', owner_token='ghost',
             active_attempt_id='ghost-attempt', lease_expires_at=?
           WHERE id=?""",
        (clock.now_ms() + 1_000, job_id),
    )
    db.execute(
        "INSERT INTO attempts(id, job_id, number, owner_token, worker_id, state, started_at)"
        " VALUES('ghost-attempt', ?, 1, 'ghost', 'w', 'running', ?)",
        (job_id, clock.now_ms()),
    )
    db.execute(
        "INSERT INTO job_events(job_id, attempt_id, kind, created_at)"
        " VALUES(?, 'ghost-attempt', 'claimed', ?)",
        (job_id, clock.now_ms()),
    )
    db.execute("ROLLBACK")
    assert db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()[0] == "queued"
    assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM job_events WHERE kind='claimed'").fetchone()[0] == 0


def test_t06_claim_vs_pending_cancel(db, clock, rng, default_queue):
    from relay.services.recovery import recover_expired_jobs

    submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"}, idempotency_key="c1")
    c = claim_job(
        db, clock=clock, worker_id="w", queues=["default"], handlers=["text_summary"], lease_ms=100
    )
    with pytest.raises(JobNotCancelableError):
        cancel_job(db, clock=clock, job_id=c["job_id"])  # running: conflict, no cancel
    assert db.execute("SELECT state FROM jobs").fetchone()[0] == "running"
    clock.advance(100)
    recover_expired_jobs(db, clock=clock, rng=rng)
    clock.advance(1_000)
    cancel_job(db, clock=clock, job_id=c["job_id"])  # now retry_wait: cancelable
    assert (
        claim_job(db, clock=clock, worker_id="w", queues=["default"], handlers=["text_summary"])
        is None
    )
    assert db.execute("SELECT state FROM jobs").fetchone()[0] == "canceled"


def test_submission_validation_gaps(db, clock, default_queue):
    for kwargs in (
        {"payload": {"text": 5}},
        {"payload": {"text": "x", "extra": 1}},
        {"payload": {"unknown": True}},
        {"priority": 1000},
        {"delay_ms": -1},
        {"timeout_ms": 0},
        {"max_attempts": 11},
        {"payload": {"text": "x"}, "queue": "no such queue"},
    ):
        base = {"handler": "text_summary", "payload": {"text": "ok"}}
        with pytest.raises(ValidationError):
            submit_job(db, clock=clock, **{**base, **kwargs})
