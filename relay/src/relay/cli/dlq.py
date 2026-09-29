"""CLI commands for Dead-Letter Queue (DLQ) inspection and remediation."""

from __future__ import annotations

import json
from typing import Annotated, Any
from urllib.parse import quote

import typer

from relay.cli.client import request

app = typer.Typer(no_args_is_help=True, help="Manage dead-letter queue and job remediation.")


def emit(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, allow_nan=False))


@app.command("list")
def list_dlq(
    queue: str | None = None,
    handler: str | None = None,
    error_code: str | None = None,
    limit: Annotated[int, typer.Option(min=1, max=100)] = 50,
) -> None:
    """List failed jobs in the dead-letter queue."""
    params: dict[str, Any] = {"limit": limit}
    if queue:
        params["queue"] = queue
    if handler:
        params["handler"] = handler
    if error_code:
        params["error_code"] = error_code
    emit(request("GET", "dlq", params=params))


@app.command("redrive")
def redrive(
    job_id: str,
    payload: Annotated[
        str | None, typer.Option("--payload", "-p", help="Updated JSON payload.")
    ] = None,
    reset_attempts: Annotated[bool, typer.Option("--reset-attempts/--keep-attempts")] = True,
) -> None:
    """Redrive a specific failed job back to queued."""
    body: dict[str, Any] = {"reset_attempts": reset_attempts}
    if payload:
        try:
            body["updated_payload"] = json.loads(payload)
        except Exception as exc:
            typer.echo(f"Invalid JSON payload: {exc}", err=True)
            raise typer.Exit(1) from None
    emit(request("POST", f"dlq/{quote(job_id, safe='')}/redrive", body=body))


@app.command("redrive-all")
def redrive_all(
    queue: str | None = None,
    handler: str | None = None,
    error_code: str | None = None,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 100,
) -> None:
    """Bulk redrive failed jobs."""
    body: dict[str, Any] = {"limit": limit}
    if queue:
        body["queue"] = queue
    if handler:
        body["handler"] = handler
    if error_code:
        body["error_code"] = error_code
    emit(request("POST", "dlq/redrive-all", body=body))
