"""Tests for job pipelines and dependency DAGs."""

from __future__ import annotations

import sqlite3

from walflow.domain.clock import FakeClock
from walflow.domain.policies import DeterministicRandom
from walflow.services.cancel import cancel_job
from walflow.services.claim import claim_job
from walflow.services.complete import complete_job, fail_job
from walflow.services.submit import submit_job


def test_pipeline_dependency_unblocks_on_success(
    db: sqlite3.Connection, default_queue: str
) -> None:
    clock = FakeClock()

    # 1. Submit parent job
    parent = submit_job(db, clock=clock, handler="text_summary", payload={"text": "stage 1"})
    parent_id = parent["job_id"]

    # 2. Submit child job dependent on parent
    child = submit_job(
        db,
        clock=clock,
        handler="text_summary",
        payload={"text": "stage 2"},
        depends_on=[parent_id],
    )
    child_id = child["job_id"]

    # 3. Verify child cannot be claimed while parent is unfinished
    claim1 = claim_job(
        db,
        clock=clock,
        worker_id="w-1",
        queues=["default"],
        handlers=["text_summary"],
    )
    assert claim1 is not None
    assert claim1["job_id"] == parent_id  # Only parent can be claimed

    # Second claim attempt finds nothing because child is blocked
    claim_none = claim_job(
        db,
        clock=clock,
        worker_id="w-2",
        queues=["default"],
        handlers=["text_summary"],
    )
    assert claim_none is None

    # 4. Complete parent job
    complete_job(
        db,
        clock=clock,
        job_id=parent_id,
        attempt_id=claim1["attempt_id"],
        owner_token=claim1["owner_token"],
        result={"status": "stage 1 done"},
    )

    # 5. Now child is unblocked and claimable!
    claim_child = claim_job(
        db,
        clock=clock,
        worker_id="w-1",
        queues=["default"],
        handlers=["text_summary"],
    )
    assert claim_child is not None
    assert claim_child["job_id"] == child_id


def test_pipeline_failure_cancels_dependent_child(
    db: sqlite3.Connection, default_queue: str
) -> None:
    clock = FakeClock()
    rng = DeterministicRandom()

    # Submit parent with max_attempts=1
    parent = submit_job(
        db, clock=clock, handler="text_summary", payload={"text": "parent"}, max_attempts=1
    )
    child = submit_job(
        db,
        clock=clock,
        handler="text_summary",
        payload={"text": "child"},
        depends_on=[parent["job_id"]],
    )

    # Claim and fail parent permanently
    claim = claim_job(
        db, clock=clock, worker_id="w-1", queues=["default"], handlers=["text_summary"]
    )
    assert claim is not None
    fail_job(
        db,
        clock=clock,
        job_id=claim["job_id"],
        attempt_id=claim["attempt_id"],
        owner_token=claim["owner_token"],
        error_code="FATAL_ERR",
        error_summary="fatal",
        rng=rng,
    )

    # Child should be automatically canceled with UPSTREAM_FAILED
    child_row = db.execute(
        "SELECT state, last_error_code FROM jobs WHERE id=?", (child["job_id"],)
    ).fetchone()
    assert child_row["state"] == "canceled"
    assert child_row["last_error_code"] == "UPSTREAM_FAILED"


def test_pipeline_cancellation_cancels_dependent_child(
    db: sqlite3.Connection, default_queue: str
) -> None:
    clock = FakeClock()

    parent = submit_job(db, clock=clock, handler="text_summary", payload={"text": "parent"})
    child = submit_job(
        db,
        clock=clock,
        handler="text_summary",
        payload={"text": "child"},
        depends_on=[parent["job_id"]],
    )

    # Cancel parent before it starts
    cancel_job(db, clock=clock, job_id=parent["job_id"])

    # Child should also be canceled
    child_row = db.execute(
        "SELECT state, last_error_code FROM jobs WHERE id=?", (child["job_id"],)
    ).fetchone()
    assert child_row["state"] == "canceled"
    assert child_row["last_error_code"] == "UPSTREAM_CANCELED"
