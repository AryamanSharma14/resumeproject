"""T22 consistent backup and T23 terminal-only, lineage-aware retention."""

from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relay.api import create_app
from relay.api.operations import backup_database, prune_jobs
from relay.domain.clock import SystemClock
from relay.services.claim import claim_job
from relay.storage.transactions import connect

AUTH = {"Authorization": "Bearer test-maintenance-token"}
BODY = {"handler": "text_summary", "payload": {"text": "durable history"}}


def test_t22_online_backup_restore_preserves_history_and_keys(tmp_path: Path) -> None:
    db, backup = str(tmp_path / "relay.db"), str(tmp_path / "backup.db")
    with TestClient(create_app(db, "test-maintenance-token"), headers=AUTH) as client:
        submitted = client.post("/api/v1/jobs", json=BODY, headers={"Idempotency-Key": "key"})
        job_id = submitted.json()["job_id"]
        client.post(f"/api/v1/jobs/{job_id}/cancel")
        assert backup_database(db, backup)["path"] == str(Path(backup).resolve())
        with pytest.raises(FileExistsError):
            backup_database(db, backup)
        with closing(connect(backup)) as restored:
            assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
            assert restored.execute("SELECT count(*) FROM job_events").fetchone()[0] == 2
        if os.name != "nt":
            assert Path(backup).stat().st_mode & 0o077 == 0
    with TestClient(create_app(backup, "test-maintenance-token"), headers=AUTH) as restored_api:
        replay = restored_api.post("/api/v1/jobs", json=BODY, headers={"Idempotency-Key": "key"})
        assert replay.status_code == 200 and replay.json()["job_id"] == job_id
        assert restored_api.get(f"/api/v1/jobs/{job_id}").json()["state"] == "canceled"


def test_t23_prune_preserves_running_and_retained_lineage_then_expires_keys(tmp_path: Path) -> None:
    db = str(tmp_path / "relay.db")
    with TestClient(create_app(db, "test-maintenance-token"), headers=AUTH) as client:
        original = client.post("/api/v1/jobs", json=BODY, headers={"Idempotency-Key": "original"})
        parent = original.json()["job_id"]
        client.post(f"/api/v1/jobs/{parent}/cancel")
        child = client.post(
            f"/api/v1/jobs/{parent}/rerun", headers={"Idempotency-Key": "rerun"}
        ).json()["job_id"]
        running = client.post("/api/v1/jobs", json={**BODY, "priority": 100}).json()["job_id"]
        with closing(connect(db)) as conn:
            claim = claim_job(
                conn,
                clock=SystemClock(),
                worker_id="retained-worker",
                queues=["default"],
                handlers=["text_summary"],
            )
            assert claim is not None and claim["job_id"] == running
        cutoff = SystemClock().now_ms() + 1000
        assert prune_jobs(db, cutoff) == {"dry_run": True, "jobs": 0}
        assert prune_jobs(db, cutoff, False)["jobs"] == 0
        assert client.get(f"/api/v1/jobs/{parent}").status_code == 200
        client.post(f"/api/v1/jobs/{child}/cancel")
        assert prune_jobs(db, cutoff)["jobs"] == 2
        assert client.get(f"/api/v1/jobs/{parent}").status_code == 200
        assert prune_jobs(db, cutoff, False) == {"dry_run": False, "jobs": 2}
        assert client.get(f"/api/v1/jobs/{parent}").status_code == 404
        assert client.get(f"/api/v1/jobs/{running}").json()["state"] == "running"
        with closing(connect(db)) as conn:
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM idempotency_records").fetchone()[0] == 0
        new = client.post("/api/v1/jobs", json=BODY, headers={"Idempotency-Key": "original"})
        assert new.status_code == 201 and new.json()["job_id"] != parent


def test_startup_maintenance_recovers_expired_attempt_without_worker(tmp_path: Path) -> None:
    from relay.domain.clock import FakeClock

    db = str(tmp_path / "relay.db")
    app = create_app(db, "test-maintenance-token")
    client = TestClient(app, headers=AUTH)
    job_id = client.post("/api/v1/jobs", json=BODY).json()["job_id"]
    with closing(connect(db)) as conn:
        # Move availability into the fake past, then create a genuinely fenced claim.
        conn.execute("UPDATE jobs SET available_at=0 WHERE id=?", (job_id,))
        claim = claim_job(
            conn,
            clock=FakeClock(),
            worker_id="lost-worker",
            queues=["default"],
            handlers=["text_summary"],
        )
        assert claim is not None
    with TestClient(app, headers=AUTH) as running_api:
        job = running_api.get(f"/api/v1/jobs/{job_id}").json()
        assert job["state"] == "retry_wait" and job["last_error_code"] == "ATTEMPT_LOST"
        assert job["lease_expires_at"] is None
        attempts = running_api.get(f"/api/v1/jobs/{job_id}/attempts").json()["items"]
        assert attempts[0]["state"] == "lost"
        assert running_api.get("/health/ready").status_code == 200


def test_readiness_detects_stale_maintenance(tmp_path: Path) -> None:
    app = create_app(str(tmp_path / "relay.db"), "test-maintenance-token")
    client = TestClient(app, headers=AUTH)
    app.state.maintenance_ok = True
    app.state.maintenance_last_ms = 0
    assert client.get("/health/ready").status_code == 503
    assert client.get("/health/live").status_code == 200
