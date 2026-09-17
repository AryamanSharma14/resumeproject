"""Lease fencing and retry requirements T07-T11, T18-T19."""

import pytest

from relay.domain.errors import StaleOwnerError
from relay.services.claim import claim_job
from relay.services.complete import complete_job, fail_job, heartbeat
from relay.services.recovery import recover_expired_jobs
from relay.services.setup import pause_queue, resume_queue
from relay.services.submit import submit_job


def submit(db, clock, **kwargs):
    return submit_job(db, clock=clock, handler="text_summary", payload={"text": "hello"}, **kwargs)


def claim(db, clock, **kwargs):
    return claim_job(
        db, clock=clock, worker_id="worker", queues=["default"], handlers=["text_summary"], **kwargs
    )


def owner(c):
    return {k: c[k] for k in ("job_id", "attempt_id", "owner_token")}


def test_timeout_records_attempt_and_retry_deadline(db, clock, rng, default_queue):
    submit(db, clock)
    c = claim(db, clock)
    assert c["timeout_ms"] == 30_000
    outcome = fail_job(
        db,
        clock=clock,
        rng=rng,
        **owner(c),
        error_code="TIMEOUT",
        error_summary="watchdog",
        timed_out=True,
    )
    assert db.execute("SELECT state FROM attempts").fetchone()[0] == "timed_out"
    assert outcome == {"outcome": "retry_wait", "retry_at": clock.now_ms() + 500}
    assert claim(db, clock) is None
    clock.advance(499)
    assert claim(db, clock) is None
    clock.advance(1)
    assert claim(db, clock)["attempt_number"] == 2


def test_t08_t09_heartbeat_and_completion_fenced(db, clock, rng, default_queue):
    submit(db, clock)
    c = claim(db, clock, lease_ms=100)
    clock.advance(50)
    assert heartbeat(db, clock=clock, **owner(c), lease_ms=100)
    clock.advance(100)
    assert not heartbeat(db, clock=clock, **owner(c))
    with pytest.raises(StaleOwnerError):
        complete_job(db, clock=clock, **owner(c), result={"ok": True})
    recover_expired_jobs(db, clock=clock, rng=rng)
    clock.advance(500)
    current = claim(db, clock)
    assert current["attempt_number"] == 2
    assert not heartbeat(db, clock=clock, **owner(c))
    with pytest.raises(StaleOwnerError):
        complete_job(db, clock=clock, **owner(c), result={"bad": True})
    complete_job(db, clock=clock, **owner(current), result={"ok": True})
    assert db.execute("SELECT state FROM jobs").fetchone()[0] == "succeeded"


def test_t07_t11_recovery_exhaustion(db, clock, rng, default_queue):
    submit(db, clock, max_attempts=1)
    claim(db, clock, lease_ms=100)
    clock.advance(100)
    assert recover_expired_jobs(db, clock=clock, rng=rng)[0]["outcome"] == "failed"
    assert recover_expired_jobs(db, clock=clock, rng=rng) == []
    assert (
        db.execute("SELECT COUNT(*) FROM job_events WHERE kind='attempt_lost'").fetchone()[0] == 1
    )
    assert db.execute("SELECT state FROM attempts").fetchone()[0] == "lost"
    assert db.execute("SELECT finished_at FROM jobs").fetchone()[0] == clock.now_ms()
    assert claim(db, clock) is None


def test_paused_and_unsupported_version(db, clock, default_queue):
    submit(db, clock)
    pause_queue(db, clock=clock, name="default")
    assert claim(db, clock) is None
    resume_queue(db, clock=clock, name="default")
    assert claim(db, clock, handler_versions={"text_summary": "other"}) is None
    c = claim(db, clock)
    assert c["handler_version"] == "1"
    pause_queue(db, clock=clock, name="default")
    complete_job(db, clock=clock, **owner(c), result={})


def test_permanent_failure_does_not_retry(db, clock, rng, default_queue):
    submit(db, clock)
    c = claim(db, clock)
    assert fail_job(
        db,
        clock=clock,
        rng=rng,
        **owner(c),
        error_code="PERMANENT",
        error_summary="invalid",
        retryable=False,
    ) == {"outcome": "failed"}


@pytest.mark.parametrize("payload", [[], None, "text", 1])
def test_non_object_payload_is_typed_validation_error(db, clock, default_queue, payload):
    from relay.domain.errors import ValidationError

    with pytest.raises(ValidationError):
        submit_job(db, clock=clock, handler="text_summary", payload=payload)
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
