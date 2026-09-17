"""Relay command line entry point."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated

import typer

from relay.domain.errors import RelayError
from relay.storage.migrations import apply_migrations, current_version
from relay.storage.transactions import connect

app = typer.Typer(no_args_is_help=True, help="Local-first durable background jobs.")


@app.callback()
def main() -> None:
    """Operate a local Relay installation."""


@app.command()
def migrate(db: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")]) -> None:
    """Apply pending checksummed migrations atomically; safe to repeat."""
    try:
        conn = connect(str(db))
        try:
            applied = apply_migrations(conn)
            version = current_version(conn)
        finally:
            conn.close()
    except (sqlite3.Error, RelayError, OSError) as exc:
        typer.echo(f"Migration failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps({"applied": applied, "schema_version": version}))
