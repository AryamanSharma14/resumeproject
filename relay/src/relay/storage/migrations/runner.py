"""Checksummed migrations: schema and ledger commit atomically."""

from __future__ import annotations

import hashlib
import importlib.resources
import sqlite3
import time
from typing import Final

from relay.domain.errors import RelayError
from relay.storage.transactions import immediate_transaction


class MigrationError(RelayError):
    code = "MIGRATION_ERROR"


_FILES: Final[dict[int, str]] = {
    1: "0001_initial.sql",
    2: "0002_cron_dlq_pipelines.sql",
}


def _load_sql(version: int) -> str:
    if version not in _FILES:
        raise MigrationError(f"unknown migration {version}")
    ref = importlib.resources.files("relay.storage.migrations") / _FILES[version]
    return ref.read_text(encoding="utf-8")


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def current_version(conn: sqlite3.Connection) -> int:
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        is None
    ):
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def known_latest_version() -> int:
    return max(_FILES)


def _execute_sql(conn: sqlite3.Connection, sql: str) -> None:
    # executescript commits pending transactions. Execute complete statements
    # individually to keep DDL and the ledger inside the same atomic boundary.
    statement = ""
    for char in sql:
        statement += char
        if char == ";" and sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        conn.execute(statement)


def apply_migrations(conn: sqlite3.Connection) -> list[int]:
    applied: list[int] = []
    with immediate_transaction(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at INTEGER NOT NULL)"
        )
        history = dict(conn.execute("SELECT version, checksum FROM schema_migrations"))
        if set(history) - set(_FILES):
            raise MigrationError("database contains an unknown schema version")
        for version in sorted(_FILES):
            sql = _load_sql(version)
            checksum = _checksum(sql)
            if version in history:
                if history[version] != checksum:
                    raise MigrationError(f"migration {version} changed after application")
                continue
            if any(v > version for v in history):
                raise MigrationError("migration history contains a gap")
            _execute_sql(conn, sql)
            conn.execute(
                "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES(?,?,?)",
                (version, checksum, time.time_ns() // 1_000_000),
            )
            applied.append(version)
    return applied
