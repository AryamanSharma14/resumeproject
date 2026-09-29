"""Injected failures exercise actual service and migration transaction boundaries."""

import sqlite3
from contextlib import closing, contextmanager

import pytest

from walflow.services import recovery
from walflow.services.claim import claim_job
from walflow.services.complete import complete_job, fail_job
from walflow.services.submit import submit_job
from walflow.storage.migrations import runner
from walflow.storage.transactions import connect, immediate_transaction


def claim(db, clock):
    return claim_job(
        db, clock=clock, worker_id="w", queues=["default"], handlers=["text_summary"], lease_ms=100
    )


def owner(c):
    return {k: c[k] for k in ("job_id", "attempt_id", "owner_token")}


def snapshot(db):
    return {
        table: [tuple(r) for r in db.execute(f"SELECT * FROM {table}")]
        for table in ("jobs", "attempts", "job_events", "idempotency_records")
    }


@pytest.mark.parametrize("transition", ["submit", "claim", "complete", "fail", "recover"])
def test_t05_real_service_event_failure_rolls_back(db, clock, rng, default_queue, transition):
    if transition != "submit":
        submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"})
    c = claim(db, clock) if transition in ("complete", "fail", "recover") else None
    if transition == "recover":
        clock.advance(100)
    before = snapshot(db)
    db.execute(
        "CREATE TEMP TRIGGER reject_event BEFORE INSERT ON job_events "
        "BEGIN SELECT RAISE(ABORT, 'injected event failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected event failure"):
        if transition == "submit":
            submit_job(
                db,
                clock=clock,
                handler="text_summary",
                payload={"text": "x"},
                idempotency_key="atomic",
            )
        elif transition == "claim":
            claim(db, clock)
        elif transition == "complete":
            complete_job(db, clock=clock, **owner(c), result={})
        elif transition == "fail":
            fail_job(db, clock=clock, **owner(c), rng=rng, error_code="E", error_summary="x")
        else:
            recovery.recover_expired_jobs(db, clock=clock, rng=rng)
    assert not db.in_transaction
    assert snapshot(db) == before


def test_recovery_uses_fresh_attempt_after_preselection(db, clock, rng, default_queue, monkeypatch):
    submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"}, max_attempts=2)
    old = claim(db, clock)
    clock.advance(100)
    path = db.execute("PRAGMA database_list").fetchone()[2]
    entered = False
    current = None

    @contextmanager
    def interleave(conn):
        nonlocal entered, current
        if not entered:
            entered = True
            with closing(connect(path)) as other:
                recovery.recover_expired_jobs(other, clock=clock, rng=rng)
                clock.advance(500)
                current = claim(other, clock)
                clock.advance(100)
        with immediate_transaction(conn):
            yield conn

    monkeypatch.setattr(recovery, "immediate_transaction", interleave)
    result = recovery.recover_expired_jobs(db, clock=clock, rng=rng)
    assert result == [{"job_id": old["job_id"], "outcome": "failed"}]
    assert current["attempt_number"] == 2
    assert [r[0] for r in db.execute("SELECT state FROM attempts ORDER BY number")] == [
        "lost",
        "lost",
    ]
    assert db.execute("SELECT finished_at FROM jobs").fetchone()[0] == clock.now_ms()


def test_migration_checksum_insert_failure_rolls_back_ddl(db, monkeypatch):
    current_ver = runner.known_latest_version()
    next_ver = current_ver + 1
    monkeypatch.setitem(runner._FILES, next_ver, "unused.sql")
    original = runner._load_sql
    monkeypatch.setattr(
        runner,
        "_load_sql",
        lambda v: (
            original(v)
            if v <= current_ver
            else "CREATE TABLE atomic_probe(id INTEGER); INSERT INTO atomic_probe VALUES(1);"
        ),
    )
    db.execute(
        "CREATE TEMP TRIGGER reject_ledger BEFORE INSERT ON schema_migrations "
        "BEGIN SELECT RAISE(ABORT, 'ledger failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="ledger failure"):
        runner.apply_migrations(db)
    assert runner.current_version(db) == current_ver
    assert not db.in_transaction
    assert db.execute("SELECT name FROM sqlite_master WHERE name='atomic_probe'").fetchone() is None
