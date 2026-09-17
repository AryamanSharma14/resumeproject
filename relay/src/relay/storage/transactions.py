"""Connection factory and transaction discipline.

Rules (implementation-plan 6.1): explicit transaction control, WAL verified,
foreign keys on, bounded busy timeout. Every write starts BEGIN IMMEDIATE as
the first statement. Transactions are short: never held across handler runs,
network calls or streaming responses. Connections are per-call here (thread
locality via sqlite3's check_same_thread default); the service layer owns
transaction boundaries.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

from relay.domain.errors import StorageBusyError, ValidationError

T = TypeVar("T")

BUSY_TIMEOUT_MS = 5_000
BUSY_RETRY_ATTEMPTS = 5
BUSY_RETRY_BASE_DELAY_S = 0.05  # exponential with jitter up to ~0.5s total


def connect(path: str, *, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """Open a connection with Relay's durability contract.

    isolation_level=None: autocommit mode; we issue explicit BEGIN IMMEDIATE.
    """
    if type(busy_timeout_ms) is not int or busy_timeout_ms < 0:
        raise ValidationError("busy_timeout_ms must be a non-negative integer")
    conn = sqlite3.connect(path, timeout=busy_timeout_ms / 1000.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
    if row is None or str(row[0]).lower() != "wal":
        conn.close()
        raise StorageBusyError("could not enable WAL mode")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


@contextmanager
def immediate_transaction(
    conn: sqlite3.Connection,
) -> Iterator[sqlite3.Connection]:
    """One fenced write transaction. Caller commits or rolls back implicitly.

    BEGIN IMMEDIATE takes the write lock up front, avoiding the deferred-
    upgrade SQLITE_BUSY_SNAPSHOT trap documented for WAL databases.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def run_write[S](conn: sqlite3.Connection, fn: Callable[[sqlite3.Connection], S]) -> S:
    """Execute `fn` inside a write transaction with bounded BUSY retry.

    Whole-transaction retry only: partial work is rolled back before retrying,
    so `fn` must be idempotent with respect to its own side effects (it should
    have none outside the transaction).
    """
    import time

    last_exc: Exception | None = None
    for attempt in range(BUSY_RETRY_ATTEMPTS):
        try:
            return fn(conn)
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc) and "database is busy" not in str(exc):
                raise
            last_exc = exc
            time.sleep(BUSY_RETRY_BASE_DELAY_S * (2**attempt))
    raise StorageBusyError("database stayed busy after retries") from last_exc


def write_tx[S](conn: sqlite3.Connection, fn: Callable[[sqlite3.Connection], S]) -> S:
    """One fenced write transaction with bounded BUSY retry.

    The service layer's standard wrapper: `fn` runs inside BEGIN IMMEDIATE
    and the whole transaction is retried (after rollback) on SQLITE_BUSY,
    bounded by BUSY_RETRY_ATTEMPTS. `fn` must have no side effects outside
    the transaction.
    """

    def wrapped(c: sqlite3.Connection) -> S:
        with immediate_transaction(c):
            return fn(c)

    return run_write(conn, wrapped)


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return conn.execute(sql, params).fetchone()[0]
