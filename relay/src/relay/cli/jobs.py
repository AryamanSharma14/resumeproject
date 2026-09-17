"""HTTP-only job commands with stable mutation keys and JSON stdout."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import typer

from relay.cli.client import request

app = typer.Typer(no_args_is_help=True)
JsonOption = Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")]


def emit(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, allow_nan=False))


def resource(job_id: str, suffix: str = "") -> str:
    return "jobs/" + quote(job_id, safe="") + suffix


@app.command("list")
def list_jobs(
    state: str | None = None,
    queue: str | None = None,
    handler: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, typer.Option(min=1, max=100)] = 50,
    json_output: JsonOption = False,
) -> None:
    """List jobs with stable cursor pagination."""
    emit(
        request(
            "GET",
            "jobs",
            params={
                k: v
                for k, v in {
                    "state": state,
                    "queue": queue,
                    "handler": handler,
                    "cursor": cursor,
                    "limit": limit,
                }.items()
                if v is not None
            },
        )
    )


@app.command()
def submit(
    handler: str,
    payload_file: Annotated[Path, typer.Option()],
    queue: str = "default",
    priority: int = 0,
    delay_ms: int = 0,
    max_attempts: int = 3,
    timeout_ms: int = 30_000,
    idempotency_key: str | None = None,
    json_output: JsonOption = False,
) -> None:
    """Submit bounded JSON; retries reuse the generated or supplied key."""
    try:
        with payload_file.open("rb") as stream:
            raw = stream.read(65_537)
        if len(raw) > 65_536:
            raise ValueError("payload file exceeds 64 KiB")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
    except (OSError, ValueError) as exc:
        typer.echo(f"Invalid payload file: {exc}", err=True)
        raise typer.Exit(2) from None
    emit(
        request(
            "POST",
            "jobs",
            body={
                "handler": handler,
                "payload": payload,
                "queue": queue,
                "priority": priority,
                "delay_ms": delay_ms,
                "max_attempts": max_attempts,
                "timeout_ms": timeout_ms,
            },
            key=idempotency_key or str(uuid.uuid4()),
        )
    )


@app.command()
def inspect(job_id: str, json_output: JsonOption = False) -> None:
    """Inspect one job."""
    emit(request("GET", resource(job_id)))


@app.command()
def attempts(job_id: str, cursor: str | None = None, json_output: JsonOption = False) -> None:
    """Read attempt history without ownership credentials."""
    emit(
        request("GET", resource(job_id, "/attempts"), params={"cursor": cursor} if cursor else None)
    )


@app.command()
def events(job_id: str, cursor: str | None = None, json_output: JsonOption = False) -> None:
    """Read durable transition events."""
    emit(request("GET", resource(job_id, "/events"), params={"cursor": cursor} if cursor else None))


@app.command()
def cancel(job_id: str, json_output: JsonOption = False) -> None:
    """Cancel pending work only; running work returns a conflict."""
    emit(request("POST", resource(job_id, "/cancel")))


@app.command()
def rerun(job_id: str, idempotency_key: str | None = None, json_output: JsonOption = False) -> None:
    """Create a linked new job; external effects may repeat."""
    emit(request("POST", resource(job_id, "/rerun"), key=idempotency_key or str(uuid.uuid4())))


@app.command()
def watch(
    job_id: str,
    timeout: Annotated[float, typer.Option(min=0.0)] = 120,
    json_output: JsonOption = False,
) -> None:
    """Poll until terminal; exit 3 when the watch deadline expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = request("GET", resource(job_id))
        if result["state"] in {"succeeded", "failed", "canceled"}:
            emit(result)
            return
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    typer.echo("Watch deadline exceeded", err=True)
    raise typer.Exit(3)
