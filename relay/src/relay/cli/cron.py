"""CLI commands for cron schedules."""

from __future__ import annotations

import json
from typing import Annotated, Any
from urllib.parse import quote

import typer

from relay.cli.client import request

app = typer.Typer(no_args_is_help=True, help="Manage recurring cron schedules.")


def emit(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, allow_nan=False))


@app.command("list")
def list_schedules() -> None:
    """List all configured cron schedules."""
    emit(request("GET", "schedules"))


@app.command("add")
def add_schedule(
    name: str,
    expression: Annotated[str, typer.Option("--expression", "-e", help="5-part cron expression.")],
    handler: Annotated[str, typer.Option("--handler", "-h", help="Handler name.")],
    payload: Annotated[str, typer.Option("--payload", "-p", help="JSON payload.")] = "{}",
    queue: str = "default",
    priority: int = 0,
    timeout_ms: int = 60_000,
    max_attempts: int = 3,
) -> None:
    """Register or replace a cron schedule."""
    try:
        payload_data = json.loads(payload)
    except Exception as exc:
        typer.echo(f"Invalid JSON payload: {exc}", err=True)
        raise typer.Exit(1) from None

    body = {
        "name": name,
        "expression": expression,
        "handler": handler,
        "payload": payload_data,
        "queue": queue,
        "priority": priority,
        "timeout_ms": timeout_ms,
        "max_attempts": max_attempts,
    }
    emit(request("POST", "schedules", body=body))


@app.command("pause")
def pause(name: str) -> None:
    """Pause an active cron schedule."""
    emit(request("POST", f"schedules/{quote(name, safe='')}/pause"))


@app.command("resume")
def resume(name: str) -> None:
    """Resume a paused cron schedule."""
    emit(request("POST", f"schedules/{quote(name, safe='')}/resume"))


@app.command("trigger")
def trigger(name: str) -> None:
    """Trigger an immediate execution of a cron schedule."""
    emit(request("POST", f"schedules/{quote(name, safe='')}/trigger"))


@app.command("remove")
def remove(name: str) -> None:
    """Delete a cron schedule."""
    emit(request("DELETE", f"schedules/{quote(name, safe='')}"))
