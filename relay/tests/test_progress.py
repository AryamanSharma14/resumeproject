"""Tests for execution progress tracking and heartbeat payloads."""

from __future__ import annotations

import json
import sqlite3

from walflow.api.queries import get_job
from walflow.domain.clock import FakeClock
from walflow.services.claim import claim_job
from walflow.services.complete import heartbeat
from walflow.services.submit import submit_job


def test_heartbeat_persists_progress(db: sqlite3.Connection, default_queue: str) -> None:
    clock = FakeClock()
    sub = submit_job(db, clock=clock, handler="text_summary", payload={"text": "hello"})
    claim = claim_job(
        db,
        clock=clock,
        worker_id="w-1",
        queues=["default"],
        handlers=["text_summary"],
    )
    assert claim is not None

    # Initial state: progress fields are None
    job_data = get_job(db, sub["job_id"])
    assert job_data.get("progress_percent") is None
    assert job_data.get("progress_message") is None

    # Heartbeat with progress update
    ok = heartbeat(
        db,
        clock=clock,
        job_id=claim["job_id"],
        attempt_id=claim["attempt_id"],
        owner_token=claim["owner_token"],
        lease_ms=30_000,
        progress_percent=45,
        progress_message="Processing step 4 of 10",
        progress_json=json.dumps({"current_step": 4, "total_steps": 10}),
    )
    assert ok is True

    # Verify updated fields in DB read model
    updated = get_job(db, sub["job_id"])
    assert updated["progress_percent"] == 45
    assert updated["progress_message"] == "Processing step 4 of 10"
    assert updated["progress"] == {"current_step": 4, "total_steps": 10}
