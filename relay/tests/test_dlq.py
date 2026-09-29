"""Tests for Dead-Letter Queue (DLQ) and remediation."""

from __future__ import annotations

import sqlite3

from walflow.domain.clock import FakeClock
from walflow.domain.policies import DeterministicRandom
from walflow.services.claim import claim_job
from walflow.services.complete import fail_job
from walflow.services.dlq import list_dlq_jobs, redrive_bulk, redrive_job
from walflow.services.submit import submit_job


def test_dlq_query_and_redrive(db: sqlite3.Connection, default_queue: str) -> None:
    clock = FakeClock()
    rng = DeterministicRandom()

    # Submit a job with max_attempts = 1 so it fails permanently on first error
    sub = submit_job(
        db,
        clock=clock,
        handler="text_summary",
        payload={"text": "flaky input"},
        max_attempts=1,
    )
    job_id = sub["job_id"]

    # Claim and fail the job
    claim = claim_job(
        db,
        clock=clock,
        worker_id="w-1",
        queues=["default"],
        handlers=["text_summary"],
    )
    assert claim is not None
    fail_job(
        db,
        clock=clock,
        job_id=claim["job_id"],
        attempt_id=claim["attempt_id"],
        owner_token=claim["owner_token"],
        error_code="TEST_ERROR",
        error_summary="something blew up",
        rng=rng,
    )

    # 1. Verify job is in DLQ
    dlq = list_dlq_jobs(db, queue="default")
    assert dlq["total"] == 1
    assert dlq["items"][0]["id"] == job_id
    assert dlq["items"][0]["last_error_code"] == "TEST_ERROR"

    # 2. Redrive job with updated payload
    res = redrive_job(
        db,
        clock=clock,
        job_id=job_id,
        reset_attempts=True,
        updated_payload={"text": "fixed input"},
    )
    assert res["state"] == "queued"
    assert res["redriven"] is True

    # 3. Verify DLQ is now empty
    dlq_after = list_dlq_jobs(db)
    assert dlq_after["total"] == 0

    # 4. Verify job state in DB
    row = db.execute(
        "SELECT state, attempt_count, payload_json, last_error_code FROM jobs WHERE id=?",
        (job_id,),
    ).fetchone()
    assert row["state"] == "queued"
    assert row["attempt_count"] == 0
    assert row["last_error_code"] is None
    assert "fixed input" in row["payload_json"]


def test_dlq_bulk_redrive(db: sqlite3.Connection, default_queue: str) -> None:
    clock = FakeClock()
    rng = DeterministicRandom()

    # Create 3 failed jobs
    for i in range(3):
        submit_job(
            db,
            clock=clock,
            handler="text_summary",
            payload={"text": f"job {i}"},
            max_attempts=1,
        )
        claim = claim_job(
            db,
            clock=clock,
            worker_id="w-1",
            queues=["default"],
            handlers=["text_summary"],
        )
        assert claim is not None
        fail_job(
            db,
            clock=clock,
            job_id=claim["job_id"],
            attempt_id=claim["attempt_id"],
            owner_token=claim["owner_token"],
            error_code="BATCH_ERR",
            error_summary="err",
            rng=rng,
        )

    assert list_dlq_jobs(db)["total"] == 3

    # Bulk redrive
    bulk_res = redrive_bulk(db, clock=clock, handler="text_summary")
    assert bulk_res["redriven_count"] == 3
    assert list_dlq_jobs(db)["total"] == 0
