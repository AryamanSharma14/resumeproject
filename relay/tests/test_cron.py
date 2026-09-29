"""Tests for SQLite Cron Engine."""

from __future__ import annotations

import sqlite3

import pytest

from relay.domain.clock import FakeClock
from relay.services.cron import (
    CronParseError,
    add_schedule,
    compute_next_run,
    delete_schedule,
    evaluate_due_schedules,
    list_schedules,
    pause_schedule,
    resume_schedule,
    trigger_schedule_now,
)


def test_cron_compute_next_run() -> None:
    # 2026-09-29 12:00:00 UTC = 1790683200000 ms
    base_ms = 1790683200000

    # Hourly: next run should be at 13:00:00
    next_hourly = compute_next_run("0 * * * *", base_ms)
    assert next_hourly > base_ms
    assert (next_hourly - base_ms) == 3600 * 1000

    # Shortcut: @daily -> 0 0 * * *
    next_daily = compute_next_run("@daily", base_ms)
    assert next_daily > base_ms

    # Invalid expressions
    with pytest.raises(CronParseError):
        compute_next_run("invalid expression", base_ms)
    with pytest.raises(CronParseError):
        compute_next_run("65 * * * *", base_ms)


def test_cron_schedules_crud_and_evaluation(db: sqlite3.Connection, default_queue: str) -> None:
    clock = FakeClock(start_ms=1790683200000)

    # 1. Add schedule
    res = add_schedule(
        db,
        clock=clock,
        name="daily_summary",
        expression="0 * * * *",
        handler="text_summary",
        payload={"text": "cron daily data"},
    )
    assert res["name"] == "daily_summary"
    assert res["paused"] is False

    # 2. List schedules
    schedules = list_schedules(db)
    assert len(schedules) == 1
    assert schedules[0]["name"] == "daily_summary"

    # 3. Before due time, evaluation spawns nothing
    spawned = evaluate_due_schedules(db, clock=clock)
    assert len(spawned) == 0

    # 4. Advance clock past next_run_at
    due_time = schedules[0]["next_run_at"]
    clock.advance(due_time - clock.now_ms() + 1000)

    # 5. Evaluate: should spawn 1 job
    spawned = evaluate_due_schedules(db, clock=clock)
    assert len(spawned) == 1
    assert spawned[0]["schedule_name"] == "daily_summary"
    job_id = spawned[0]["job_id"]

    # Verify job is queued in database
    job_row = db.execute("SELECT state, handler FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert job_row["state"] == "queued"
    assert job_row["handler"] == "text_summary"

    # 6. Immediate second evaluation at same time spawns nothing (next_run_at was advanced)
    spawned2 = evaluate_due_schedules(db, clock=clock)
    assert len(spawned2) == 0

    # 7. Pause and resume
    assert pause_schedule(db, name="daily_summary") is True
    schedules = list_schedules(db)
    assert schedules[0]["paused"] is True

    assert resume_schedule(db, clock=clock, name="daily_summary") is True
    schedules = list_schedules(db)
    assert schedules[0]["paused"] is False

    # 8. Manual trigger
    manual = trigger_schedule_now(db, clock=clock, name="daily_summary")
    assert "job_id" in manual

    # 9. Delete
    assert delete_schedule(db, name="daily_summary") is True
    assert len(list_schedules(db)) == 0
