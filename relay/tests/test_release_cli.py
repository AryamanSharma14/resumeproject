"""Release regressions exercised through actual CLI subprocesses, not CliRunner."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cli(db: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-c", "from walflow.cli import app; app()", "migrate", "--db", str(db)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_migration_cli_bootstrap_restart_unknown_version(tmp_path: Path) -> None:
    db = tmp_path / "release.db"
    first = cli(db, tmp_path)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout) == {"applied": [1, 2], "schema_version": 2}
    restarted = cli(db, tmp_path)
    assert restarted.returncode == 0, restarted.stderr
    assert json.loads(restarted.stdout) == {"applied": [], "schema_version": 2}
    # sqlite connection context managers commit/rollback but do NOT close connections.
    # Explicit closing is essential for Windows teardown and subprocess restart checks.
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT length(checksum) FROM schema_migrations").fetchone()[0] == 64
        conn.execute("INSERT INTO schema_migrations VALUES(999, 'future', 1)")
        conn.commit()
    rejected = cli(db, tmp_path)
    assert rejected.returncode != 0
    assert "Migration failed" in rejected.stderr
    assert not rejected.stdout.strip()
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 999
    db.unlink()  # proves no still-open parent handle prevents deletion on Windows


def test_benchmark_real_subprocess_and_bounds(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "benchmark.py"
    result = subprocess.run(
        [sys.executable, str(script), "--jobs", "12", "--workers", "2", "--seed", "42"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["verified"] == {"jobs": 12, "succeeded": 12, "attempts": 12, "events": 36}
    assert report["config"]["sqlite"] == {
        "journal_mode": "wal",
        "synchronous": 2,
        "foreign_keys": 1,
        "busy_timeout": 5000,
    }
    assert report["total"]["seconds"] > 0
    assert report["total"]["jobs_per_second"] > 0
    for phase in ("submit", "claim", "complete"):
        assert 0 <= report[phase]["p50_ms"] <= report[phase]["p95_ms"] <= report[phase]["p99_ms"]
    invalid = subprocess.run(
        [sys.executable, str(script), "--jobs", "10001"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert invalid.returncode != 0
    assert not invalid.stdout.strip()
