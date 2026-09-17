"""Actual races: independent connections and captured failures."""

from contextlib import closing

import pytest

from relay.domain.errors import JobNotCancelableError, StaleOwnerError
from relay.services.cancel import cancel_job
from relay.services.claim import claim_job
from relay.services.complete import complete_job, heartbeat
from relay.services.recovery import recover_expired_jobs
from relay.services.setup import pause_queue
from relay.services.submit import submit_job
from relay.storage.transactions import connect
from test_core_concurrency import _db_path, _run_in_threads


def _claim(conn, clock):
    return claim_job(
        conn,
        clock=clock,
        worker_id="w",
        queues=["default"],
        handlers=["text_summary"],
        lease_ms=100,
    )


def _owner(c):
    return {k: c[k] for k in ("job_id", "attempt_id", "owner_token")}


def test_thread_failures_are_captured():
    def broken():
        raise AssertionError("captured sentinel")

    with pytest.raises(BaseExceptionGroup, match="thread failures") as exc:
        _run_in_threads([broken])
    assert str(exc.value.exceptions[0]) == "captured sentinel"


def test_t06_actual_claim_cancel_race(db, clock, default_queue):
    path = _db_path(db)
    for _ in range(20):
        job = submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"})
        results = {}

        def claim(results=results):
            with closing(connect(path)) as conn:
                results["claim"] = _claim(conn, clock)

        def cancel(results=results, job=job):
            with closing(connect(path)) as conn:
                try:
                    cancel_job(conn, clock=clock, job_id=job["job_id"])
                    results["cancel"] = True
                except JobNotCancelableError:
                    results["cancel"] = False

        _run_in_threads([claim, cancel])
        if results["cancel"]:
            assert results["claim"] is None
        else:
            assert results["claim"]["job_id"] == job["job_id"]
            complete_job(db, clock=clock, **_owner(results["claim"]), result={})


def test_t07_actual_double_recovery(db, clock, rng, default_queue):
    submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"})
    c = _claim(db, clock)
    clock.advance(100)
    path = _db_path(db)

    def recover():
        with closing(connect(path)) as conn:
            recover_expired_jobs(conn, clock=clock, rng=rng)

    _run_in_threads([recover, recover])
    assert (
        db.execute("SELECT state FROM attempts WHERE id=?", (c["attempt_id"],)).fetchone()[0]
        == "lost"
    )
    assert (
        db.execute("SELECT COUNT(*) FROM job_events WHERE kind='attempt_lost'").fetchone()[0] == 1
    )
    assert (
        db.execute("SELECT COUNT(*) FROM job_events WHERE kind='retry_scheduled'").fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("operation", ["heartbeat", "complete"])
@pytest.mark.parametrize("expired", [False, True])
def test_owner_recovery_races(db, clock, rng, default_queue, operation, expired):
    submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"})
    c = _claim(db, clock)
    clock.advance(100 if expired else 99)
    path = _db_path(db)

    def owner():
        with closing(connect(path)) as conn:
            if operation == "heartbeat":
                assert heartbeat(conn, clock=clock, **_owner(c)) is not expired
            elif expired:
                with pytest.raises(StaleOwnerError):
                    complete_job(conn, clock=clock, **_owner(c), result={})
            else:
                complete_job(conn, clock=clock, **_owner(c), result={})

    def recover():
        with closing(connect(path)) as conn:
            recover_expired_jobs(conn, clock=clock, rng=rng)

    _run_in_threads([owner, recover])
    state = db.execute("SELECT state FROM jobs").fetchone()[0]
    assert state == (
        "retry_wait" if expired else "running" if operation == "heartbeat" else "succeeded"
    )


@pytest.mark.parametrize("blocked", ["paused", "version"])
def test_t18_t19_eight_blocked_claimants(db, clock, default_queue, blocked):
    for _ in range(4):
        submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"})
    if blocked == "paused":
        pause_queue(db, clock=clock, name="default")
    else:
        db.execute("UPDATE jobs SET handler_version='999'")
    path = _db_path(db)

    def claim():
        with closing(connect(path)) as conn:
            for _ in range(5):
                assert _claim(conn, clock) is None

    _run_in_threads([claim] * 8)
    assert db.execute("SELECT SUM(attempt_count) FROM jobs").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM job_events").fetchone()[0] == 4
