"""Shared fixtures: temp DB, applied schema, clock, RNG, default queue."""

from __future__ import annotations

import sqlite3

import pytest

from relay.domain.clock import FakeClock
from relay.domain.policies import DeterministicRandom
from relay.storage import migrations
from relay.storage.transactions import connect


@pytest.fixture()
def db(tmp_path):
    """File-backed WAL database with migrations applied."""
    path = tmp_path / "relay.db"
    setup = sqlite3.connect(str(path), isolation_level=None)
    setup.row_factory = sqlite3.Row
    migrations.apply_migrations(setup)
    setup.close()
    conn = connect(str(path))
    yield conn
    conn.close()


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def rng():
    return DeterministicRandom()


@pytest.fixture()
def default_queue(db, clock):
    from relay.services.setup import ensure_queue

    ensure_queue(db, clock=clock, name="default")
    return "default"
