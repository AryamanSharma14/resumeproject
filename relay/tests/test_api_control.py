"""Real HTTP/storage integration: T17 rerun atomicity, T18 pause, read contracts."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from walflow.api import create_app
from walflow.api.operations import rerun_job
from walflow.domain.clock import SystemClock
from walflow.services.claim import claim_job
from walflow.services.complete import complete_job
from walflow.storage.transactions import connect

TOKEN = "test-only-installation-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"handler": "text_summary", "payload": {"text": "hello world"}}


def client_for(tmp_path: Path) -> TestClient:
    return TestClient(create_app(str(tmp_path / "relay.db"), TOKEN), headers=AUTH)


def submit(client: TestClient, key: str | None = None) -> str:
    response = client.post(
        "/api/v1/jobs", json=BODY, headers={"Idempotency-Key": key} if key else {}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["job_id"])


def test_submit_replay_conflict_and_rfc3339(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        job_id = submit(client, "submission-key")
        replay = client.post(
            "/api/v1/jobs", json=BODY, headers={"Idempotency-Key": "submission-key"}
        )
        assert replay.status_code == 200
        assert replay.json() == {"job_id": job_id, "replayed": True}
        conflict = client.post(
            "/api/v1/jobs",
            json={**BODY, "priority": 2},
            headers={"Idempotency-Key": "submission-key"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        assert job["payload"] == BODY["payload"]
        assert "owner_token" not in job
        assert job["created_at"].endswith("Z") and "T" in job["created_at"]
        assert job["result"] is None and job["lease_expires_at"] is None
        assert client.get("/health/ready").json() == {
            "status": "ready",
            "database": True,
            "maintenance": True,
        }
    with client_for(tmp_path) as restarted:
        assert restarted.get(f"/api/v1/jobs/{job_id}").status_code == 200


def test_t17_rerun_response_loss_concurrent_replay_and_lineage(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        source = submit(client)
        assert (
            client.post(
                f"/api/v1/jobs/{source}/rerun", headers={"Idempotency-Key": "run"}
            ).status_code
            == 409
        )
        assert client.post(f"/api/v1/jobs/{source}/cancel").status_code == 200
        assert client.post(f"/api/v1/jobs/{source}/rerun").status_code == 422

        def rerun(_: int) -> dict[str, Any]:
            result = client.post(f"/api/v1/jobs/{source}/rerun", headers={"Idempotency-Key": "run"})
            assert result.status_code in (200, 201), result.text
            return dict(result.json())

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(rerun, range(8)))
        ids = {result["job_id"] for result in results}
        assert len(ids) == 1
        assert sum(not result["replayed"] for result in results) == 1
        new_id = ids.pop()
        job = client.get(f"/api/v1/jobs/{new_id}").json()
        assert job["rerun_of"] == source and job["attempt_count"] == 0
        assert job["payload"] == BODY["payload"] and job["state"] == "queued"
        assert client.get(f"/api/v1/jobs/{new_id}/events").json()["items"][0]["detail"] == {
            "rerun_of": source
        }
        other = submit(client)
        client.post(f"/api/v1/jobs/{other}/cancel")
        assert (
            client.post(
                f"/api/v1/jobs/{other}/rerun", headers={"Idempotency-Key": "run"}
            ).status_code
            == 409
        )
    with client_for(tmp_path) as client:
        retry = client.post(f"/api/v1/jobs/{source}/rerun", headers={"Idempotency-Key": "run"})
        assert retry.status_code == 200 and retry.json()["job_id"] == new_id


def test_t17_rerun_rolls_back_lineage_event_and_key(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        source = submit(client)
        client.post(f"/api/v1/jobs/{source}/cancel")
    with closing(connect(str(tmp_path / "relay.db"))) as conn:
        conn.execute("""CREATE TRIGGER break_rerun BEFORE INSERT ON idempotency_records
                     WHEN NEW.scope='rerun' BEGIN SELECT RAISE(ABORT,'injected'); END""")
        with pytest.raises(sqlite3.IntegrityError):
            rerun_job(conn, clock=SystemClock(), job_id=source, idempotency_key="rollback")
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM job_events").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM idempotency_records").fetchone()[0] == 0


def test_t18_pause_blocks_claims_not_completion(tmp_path: Path) -> None:
    with client_for(tmp_path) as client, closing(connect(str(tmp_path / "relay.db"))) as conn:
        first = submit(client)
        claim = claim_job(
            conn,
            clock=SystemClock(),
            worker_id="test-worker",
            queues=["default"],
            handlers=["text_summary"],
        )
        assert claim is not None and claim["job_id"] == first
        second = submit(client)
        assert client.post("/api/v1/queues/default/pause").json() == {
            "name": "default",
            "paused": True,
        }
        assert (
            claim_job(
                conn,
                clock=SystemClock(),
                worker_id="second-worker",
                queues=["default"],
                handlers=["text_summary"],
            )
            is None
        )
        assert client.post(f"/api/v1/jobs/{first}/cancel").status_code == 409
        complete_job(
            conn,
            clock=SystemClock(),
            job_id=first,
            attempt_id=claim["attempt_id"],
            owner_token=claim["owner_token"],
            result={"words": 2},
        )
        assert client.get(f"/api/v1/jobs/{first}").json()["state"] == "succeeded"
        history = client.get(f"/api/v1/jobs/{first}/attempts").json()["items"]
        assert history[0]["result"] == {"words": 2}
        assert history[0]["started_at"].endswith("Z")
        assert "owner_token" not in history[0]
        assert client.post("/api/v1/queues/default/resume").status_code == 200
        next_claim = claim_job(
            conn,
            clock=SystemClock(),
            worker_id="second-worker",
            queues=["default"],
            handlers=["text_summary"],
        )
        assert next_claim is not None and next_claim["job_id"] == second


def test_queries_pagination_validation_overview_and_openapi(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        ids = {submit(client) for _ in range(5)}
        seen: list[str] = []
        params: dict[str, str | int] = {"limit": 2}
        while True:
            page = client.get("/api/v1/jobs", params=params).json()
            seen.extend(item["id"] for item in page["items"])
            if page["next_cursor"] is None:
                break
            params["cursor"] = page["next_cursor"]
        assert len(seen) == len(set(seen)) == 5 and set(seen) == ids
        for params_bad in (
            {"limit": 101},
            {"limit": 0},
            {"cursor": "bad"},
            {"state": "bad"},
            {"created_after": "yesterday"},
            {"created_after": "2026-01-01T00:00:00"},
        ):
            assert client.get("/api/v1/jobs", params=params_bad).status_code == 422
        assert client.get("/api/v1/jobs", params={"handler": "' OR 1=1--"}).json()["items"] == []
        assert client.get("/api/v1/jobs/missing/events").status_code == 404
        source = seen[0]
        client.post(f"/api/v1/jobs/{source}/cancel")
        events = client.get(f"/api/v1/jobs/{source}/events?limit=1").json()
        assert len(events["items"]) == 1 and events["next_cursor"]
        next_events = client.get(
            f"/api/v1/jobs/{source}/events", params={"cursor": events["next_cursor"]}
        ).json()
        assert next_events["items"][0]["kind"] == "canceled"
        summary = client.get("/api/v1/overview").json()
        assert summary["window"] == "retained" and summary["jobs"]["queued"] == 4
        assert summary["queues"][0]["due_depth"] == 4
        assert client.get("/api/v1/system").json()["schema_version"] == 2
        assert 'relay_jobs{queue="default",state="queued"} 4' in client.get("/metrics").text
        assert len(client.get("/api/v1/handlers").json()["items"]) == 4
        assert "/api/v1/jobs" in client.get("/api/v1/openapi.json").json()["paths"]


def test_workers_real_capacity_and_stale_availability(tmp_path: Path) -> None:
    with client_for(tmp_path) as client, closing(connect(str(tmp_path / "relay.db"))) as conn:
        now = SystemClock().now_ms()
        conn.execute(
            """INSERT INTO workers VALUES('worker','local',1,?,?,'online',2,
                     '["default"]','{"text_summary":"1"}')""",
            (now, now),
        )
        item = client.get("/api/v1/workers").json()["items"][0]
        assert item["availability"] == "online" and item["available_slots"] == 2
        assert item["queues"] == ["default"] and item["handler_versions"] == {"text_summary": "1"}
        conn.execute("UPDATE workers SET heartbeat_at=?", (now - 31_000,))
        stale = client.get("/api/v1/workers").json()["items"][0]
        assert stale["availability"] == "stale" and stale["available_slots"] == 0
