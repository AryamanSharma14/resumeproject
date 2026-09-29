"""Unit and integration tests for Relay Python SDK."""

from __future__ import annotations

from pathlib import Path

from relay import Relay
from relay.domain.registry import HANDLERS
from relay.storage.transactions import connect


def test_sdk_task_decorator_registers_and_runs_sync(tmp_path: Path) -> None:
    app = Relay(tmp_path / "sdk.db")

    @app.task(name="math_multiply", queue="compute", timeout_ms=15_000)
    def multiply(x: int, y: int) -> int:
        return x * y

    # Test sync execution
    assert multiply(3, 7) == 21

    # Verify registration in registry
    assert "math_multiply" in HANDLERS
    spec = HANDLERS["math_multiply"]
    assert spec.name == "math_multiply"
    assert spec.run({"x": 4, "y": 5}) == {"result": 20}


def test_sdk_task_delay_submits_job(tmp_path: Path, default_queue: str) -> None:
    db_file = tmp_path / "sdk_delay.db"
    conn = connect(str(db_file))
    from relay.domain.clock import SystemClock
    from relay.services.setup import ensure_queue
    from relay.storage.migrations import apply_migrations

    apply_migrations(conn)
    ensure_queue(conn, clock=SystemClock(), name="default")
    conn.close()

    app = Relay(db_file)

    @app.task(name="greeting_task")
    def greet(name: str) -> dict[str, str]:
        return {"message": f"Hello, {name}!"}

    res = greet.delay(name="Alice")
    assert "job_id" in res
    assert res["replayed"] is False

    conn = connect(str(db_file))
    row = conn.execute(
        "SELECT handler, payload_json, state FROM jobs WHERE id=?", (res["job_id"],)
    ).fetchone()
    assert row["handler"] == "greeting_task"
    assert "Alice" in row["payload_json"]
    assert row["state"] == "queued"
    conn.close()
