"""Relay command line entry point."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated

import typer

from relay.cli.client import request
from relay.cli.cron import app as cron_app
from relay.cli.dlq import app as dlq_app
from relay.cli.jobs import app as jobs_app
from relay.cli.jobs import emit
from relay.config import data_directory, database_path, initialize, read_token
from relay.domain.clock import SystemClock
from relay.domain.errors import RelayError
from relay.services.setup import ensure_queue
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


db_app = typer.Typer(no_args_is_help=True)
worker_app = typer.Typer(no_args_is_help=True)
workers_app = typer.Typer(no_args_is_help=True)
queues_app = typer.Typer(no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(worker_app, name="worker")
app.add_typer(workers_app, name="workers")
app.add_typer(queues_app, name="queues")
app.add_typer(jobs_app, name="jobs")
app.add_typer(cron_app, name="cron")
app.add_typer(dlq_app, name="dlq")
db_app.command("migrate")(migrate)


@app.command()
def init(data_dir: Annotated[Path | None, typer.Option()] = None) -> None:
    """Create restricted local credentials and initialize a default queue."""
    try:
        path = initialize(data_dir or data_directory())
        migrate(path)
        conn = connect(str(path))
        try:
            ensure_queue(conn, clock=SystemClock(), name="default")
        finally:
            conn.close()
        emit({"database": str(path), "token_file": str(path.parent / "token")})
    except (OSError, ValueError, sqlite3.Error, RelayError) as exc:
        typer.echo(f"Initialization failed: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from None


@app.command("serve")
def serve(
    db: Annotated[Path | None, typer.Option()] = None,
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
) -> None:
    """Serve API/UI on loopback only. Start workers separately."""
    import uvicorn

    from relay.api import create_app

    try:
        api = create_app(str(db or database_path()), read_token())
        uvicorn.run(api, host="127.0.0.1", port=port, access_log=False)
    except (OSError, ValueError, RelayError):
        typer.echo("Server could not start; check local configuration.", err=True)
        raise typer.Exit(1) from None


app.command("server")(serve)


@worker_app.command("start")
def worker_start(
    db: Annotated[Path | None, typer.Option()] = None,
    queues: str = "default",
    concurrency: Annotated[int, typer.Option(min=1, max=8)] = 2,
    grace_seconds: Annotated[float, typer.Option(min=0, max=600)] = 30,
) -> None:
    """Start a spawned-child supervisor. SIGINT/SIGTERM initiate bounded drain."""
    import logging

    from relay.worker import Supervisor, WorkerConfig

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        Supervisor(
            WorkerConfig(
                str(db or database_path()),
                queues=tuple(q.strip() for q in queues.split(",") if q.strip()),
                concurrency=concurrency,
                grace_ms=int(grace_seconds * 1000),
            )
        ).run()
    except (OSError, ValueError, sqlite3.Error, RelayError):
        typer.echo("Worker could not start; check schema and configuration.", err=True)
        raise typer.Exit(1) from None


@workers_app.command("list")
def workers_list(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    """List worker heartbeats and capacity."""
    emit(request("GET", "workers"))


@queues_app.command("list")
def queues_list(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    """List queues and ready depths."""
    emit(request("GET", "queues"))


@queues_app.command()
def pause(name: str) -> None:
    """Pause new claims; existing attempts continue."""
    from urllib.parse import quote

    emit(request("POST", f"queues/{quote(name, safe='')}/pause"))


@queues_app.command()
def resume(name: str) -> None:
    """Resume new claims."""
    from urllib.parse import quote

    emit(request("POST", f"queues/{quote(name, safe='')}/resume"))


@db_app.command("backup")
def backup(destination: Path, db: Annotated[Path | None, typer.Option()] = None) -> None:
    """Consistent SQLite backup to a new file; never overwrite."""
    from relay.api.operations import backup_database

    try:
        emit(backup_database(str(db or database_path()), str(destination)))
    except (OSError, ValueError, sqlite3.Error, RelayError):
        typer.echo("Backup failed; destination must be new and source readable.", err=True)
        raise typer.Exit(1) from None


@db_app.command("prune")
def prune(
    before: Annotated[str, typer.Option(help="UTC cutoff, e.g. 2026-01-01T00:00:00Z")],
    db: Annotated[Path | None, typer.Option()] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run/--execute")] = True,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Prune old terminal history; ends its idempotency protection. Default dry-run."""
    from datetime import datetime

    from relay.api.operations import prune_jobs

    if not dry_run and not yes:
        typer.echo("Destructive prune requires --execute --yes; no interactive prompt.", err=True)
        raise typer.Exit(2)
    try:
        cutoff = datetime.fromisoformat(before.replace("Z", "+00:00"))
        if cutoff.tzinfo is None:
            raise ValueError("timezone required")
        emit(prune_jobs(str(db or database_path()), int(cutoff.timestamp() * 1000), dry_run))
    except ValueError:
        typer.echo("Invalid timezone-aware cutoff.", err=True)
        raise typer.Exit(2) from None
    except (OSError, sqlite3.Error, RelayError):
        typer.echo("Prune failed; database unavailable or incompatible.", err=True)
        raise typer.Exit(1) from None


@app.command()
def doctor(db: Annotated[Path | None, typer.Option()] = None) -> None:
    """Report local paths, schema and credential status without printing secrets."""
    import os

    import httpx

    from relay import __version__
    from relay.storage.migrations import known_latest_version

    path = db or database_path()
    report: dict[str, object] = {
        "version": __version__,
        "database": str(path),
        "data_directory": str(data_directory()),
    }
    healthy = True
    try:
        read_token()
        report["credential"] = "available"
    except (OSError, ValueError):
        healthy = False
        report["credential"] = "missing or unsafe"
    try:
        if not path.is_file():
            raise ValueError("missing database")
        conn = connect(str(path))
        try:
            version = current_version(conn)
        finally:
            conn.close()
        report["schema_version"] = version
        healthy = healthy and version == known_latest_version()
    except (OSError, ValueError, sqlite3.Error, RelayError):
        healthy = False
        report["database_status"] = "unavailable"
    try:
        endpoint = os.environ.get("RELAY_URL", "http://127.0.0.1:8000")
        from urllib.parse import urlsplit

        parsed = urlsplit(endpoint)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username:
            raise ValueError("nonlocal endpoint")
        with httpx.Client(timeout=2, trust_env=False) as client:
            response = client.get(endpoint.rstrip("/") + "/health/ready")
        report["api_ready"] = response.status_code == 200
        healthy = healthy and response.status_code == 200
    except (httpx.HTTPError, ValueError):
        report["api_ready"] = False
        healthy = False
    emit(report)
    if not healthy:
        raise typer.Exit(1)
