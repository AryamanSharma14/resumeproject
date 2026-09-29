"""Bounded HTTP client. Credentials never enter argv, URLs or error output."""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
import typer

from walflow.config import read_token


def request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    key: str | None = None,
) -> Any:
    try:
        endpoint = os.environ.get("WALFLOW_URL") or os.environ.get(
            "RELAY_URL", "http://127.0.0.1:8000"
        )
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("WALFLOW_URL must be a plain loopback HTTP origin without credentials")
        headers = {"Authorization": f"Bearer {read_token()}"}
        if key:
            headers["Idempotency-Key"] = key
        with httpx.Client(
            base_url=endpoint,
            headers=headers,
            follow_redirects=False,
            timeout=httpx.Timeout(10, connect=2, pool=2),
            trust_env=False,
        ) as client:
            for attempt in range(3):
                try:
                    response = client.request(method, "/api/v1/" + path, json=body, params=params)
                except httpx.TransportError:
                    if attempt == 2 or (method != "GET" and key is None):
                        raise
                    time.sleep(0.1 * (attempt + 1))
                    continue
                response.raise_for_status()
                return response.json()
        raise RuntimeError("request exhausted")
    except httpx.HTTPStatusError as exc:
        typer.echo(f"API request failed (HTTP {exc.response.status_code})", err=True)
        raise typer.Exit(2 if exc.response.status_code == 422 else 1) from None
    except (httpx.HTTPError, OSError, ValueError):
        typer.echo("API unavailable or local configuration invalid; check relay doctor.", err=True)
        raise typer.Exit(1) from None
