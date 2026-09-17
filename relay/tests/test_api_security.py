"""T24 HTTP boundary: auth, Host/Origin, bounded JSON, safe static deep links."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relay.api import create_app
from relay.api.security import MAX_BODY_BYTES

TOKEN = "test-security-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/jobs"),
        ("GET", "/api/v1/jobs"),
        ("GET", "/api/v1/jobs/id"),
        ("GET", "/api/v1/jobs/id/attempts"),
        ("GET", "/api/v1/jobs/id/events"),
        ("POST", "/api/v1/jobs/id/cancel"),
        ("POST", "/api/v1/jobs/id/rerun"),
        ("GET", "/api/v1/workers"),
        ("GET", "/api/v1/queues"),
        ("POST", "/api/v1/queues/default/pause"),
        ("POST", "/api/v1/queues/default/resume"),
        ("GET", "/api/v1/handlers"),
        ("GET", "/api/v1/overview"),
        ("GET", "/api/v1/system"),
        ("GET", "/api/v1/openapi.json"),
        ("GET", "/metrics"),
        ("GET", "/api/not-real"),
    ],
)
def test_every_control_endpoint_requires_bearer(tmp_path: Path, method: str, path: str) -> None:
    client = TestClient(create_app(str(tmp_path / "relay.db"), TOKEN))
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}):
        response = client.request(method, path, headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        error = response.json()["error"]
        assert error["code"] == "UNAUTHORIZED" and error["request_id"]
        assert TOKEN not in response.text
    assert client.request(method, path, params={"token": TOKEN}).status_code == 401


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "127.0.0.1.evil",
        "localhost@evil.example",
        "localhost/path",
        "localhost:bad",
        "evil.localhost",
    ],
)
def test_invalid_host(tmp_path: Path, host: str) -> None:
    client = TestClient(create_app(str(tmp_path / "relay.db"), TOKEN))
    assert client.get("/health/live", headers={"Host": host}).status_code == 400


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "null",
        "http://testserver:9999",
        "https://testserver",
        "http://testserver/path",
    ],
)
def test_cross_origin_and_preflight_rejected(tmp_path: Path, origin: str) -> None:
    client = TestClient(create_app(str(tmp_path / "relay.db"), TOKEN), headers=AUTH)
    for method in ("GET", "OPTIONS"):
        response = client.request(method, "/api/v1/jobs", headers={"Origin": origin})
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers
    assert client.get("/api/v1/jobs", headers={"Origin": "http://testserver"}).status_code == 200


def test_streaming_size_limit_and_safe_validation(tmp_path: Path) -> None:
    client = TestClient(create_app(str(tmp_path / "relay.db"), TOKEN), headers=AUTH)
    assert client.post("/api/v1/jobs", content=b"x" * (MAX_BODY_BYTES + 1)).status_code == 413

    def chunks() -> Iterator[bytes]:
        yield b"x" * 40000
        yield b"y" * 40000

    assert client.post("/api/v1/jobs", content=chunks()).status_code == 413
    assert client.post("/api/v1/jobs", headers={"Content-Length": "nope"}).status_code == 400
    payload = {"handler": "text_summary", "payload": {"text": "x" * 66000}}
    assert client.post("/api/v1/jobs", json=payload).status_code == 413
    for body in (
        {"handler": "shell", "payload": {}},
        {"handler": "text_summary", "payload": {"text": "hello"}, "priority": True},
        {"handler": "text_summary", "payload": {"text": "hello"}, "extra": TOKEN},
    ):
        response = client.post("/api/v1/jobs", json=body)
        assert response.status_code == 422 and TOKEN not in response.text
    malformed = client.post(
        "/api/v1/jobs", content='{"token":"' + TOKEN, headers={"Content-Type": "application/json"}
    )
    assert malformed.status_code == 422 and TOKEN not in malformed.text


def test_t24_safe_spa_and_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text('<!doctype html><div id="root"></div>', encoding="utf-8")
    (static / "assets").mkdir()
    (static / "assets" / "app.js").write_text("console.log('test');", encoding="utf-8")
    (tmp_path / "secret.txt").write_text(TOKEN, encoding="utf-8")
    monkeypatch.setattr("relay.api.app.STATIC_DIR", static)
    client = TestClient(create_app(str(tmp_path / "relay.db"), TOKEN), headers=AUTH)
    for route in ("/", "/jobs", "/jobs/example", "/queues/default", "/system"):
        response = client.get(route)
        assert response.status_code == 200 and 'id="root"' in response.text
        assert "default-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/assets/app.js").status_code == 200
    for route in (
        "/api/v1/missing",
        "/assets/missing.js",
        "/health/missing",
        "/%2e%2e/secret.txt",
        "/..%5csecret.txt",
        "/C:%5csecret.txt",
        "/.env",
    ):
        response = client.get(route)
        assert response.status_code == 404, route
        assert 'id="root"' not in response.text and TOKEN not in response.text
    assert client.post("/api/v1/db/backup", json={"path": str(tmp_path)}).status_code == 405
