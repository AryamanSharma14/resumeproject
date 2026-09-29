"""T01 and migration atomicity on a real file-backed database."""

import os
import sqlite3
import tempfile

import pytest

from walflow.storage.migrations import runner
from walflow.storage.transactions import connect


def test_original_schema_query_before_creation_defect_is_fixed():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "repro.db")
        raw = sqlite3.connect(path, isolation_level=None)
        try:
            raw.execute("SELECT MAX(version) FROM schema_migrations")
            raise AssertionError("expected the pre-fix defect to reproduce here")
        except sqlite3.OperationalError as exc:
            assert "no such table: schema_migrations" in str(exc)
        finally:
            raw.close()
        conn = connect(path)
        try:
            assert runner.current_version(conn) == 0
            assert runner.apply_migrations(conn) == [1, 2]
            assert runner.apply_migrations(conn) == []
        finally:
            conn.close()


def test_t01_fresh_restart_and_newer_schema(tmp_path):
    path = str(tmp_path / "fresh.db")
    conn = connect(path)
    assert runner.current_version(conn) == 0
    assert runner.apply_migrations(conn) == [1, 2]
    conn.close()
    conn = connect(path)
    try:
        assert runner.current_version(conn) == 2
        assert runner.apply_migrations(conn) == []
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        conn.execute("INSERT INTO schema_migrations VALUES (999, 'future', 1)")
        with pytest.raises(runner.MigrationError):
            runner.apply_migrations(conn)
    finally:
        conn.close()


def test_migration_ddl_and_ledger_rollback(tmp_path, monkeypatch):
    conn = connect(str(tmp_path / "broken.db"))
    original = runner._load_sql
    monkeypatch.setattr(runner, "_load_sql", lambda v: original(v) + "\nINVALID SQL;")
    try:
        with pytest.raises(sqlite3.OperationalError):
            runner.apply_migrations(conn)
        assert not conn.in_transaction
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        monkeypatch.setattr(runner, "_load_sql", original)
        assert runner.apply_migrations(conn) == [1, 2]
        conn.execute("UPDATE schema_migrations SET checksum='changed'")
        with pytest.raises(runner.MigrationError):
            runner.apply_migrations(conn)
    finally:
        conn.close()
