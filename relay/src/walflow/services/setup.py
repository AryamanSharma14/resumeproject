"""Queue setup helpers (bounded configured queue names)."""

from __future__ import annotations

import sqlite3

from walflow.domain.clock import Clock
from walflow.domain.errors import UnknownQueueError
from walflow.domain.validation import queue_name
from walflow.storage.transactions import immediate_transaction

MAX_QUEUE_NAME = 64


def ensure_queue(conn: sqlite3.Connection, *, clock: Clock, name: str) -> None:
    queue_name(name)
    with immediate_transaction(conn):
        conn.execute(
            "INSERT INTO queues(name, paused, created_at) VALUES(?, 0, ?)"
            " ON CONFLICT(name) DO NOTHING",
            (name, clock.now_ms()),
        )


def pause_queue(conn: sqlite3.Connection, *, clock: Clock, name: str) -> None:
    queue_name(name)
    with immediate_transaction(conn):
        if conn.execute("UPDATE queues SET paused=1 WHERE name=?", (name,)).rowcount != 1:
            raise UnknownQueueError(f"unknown queue: {name}")


def resume_queue(conn: sqlite3.Connection, *, clock: Clock, name: str) -> None:
    queue_name(name)
    with immediate_transaction(conn):
        if conn.execute("UPDATE queues SET paused=0 WHERE name=?", (name,)).rowcount != 1:
            raise UnknownQueueError(f"unknown queue: {name}")
