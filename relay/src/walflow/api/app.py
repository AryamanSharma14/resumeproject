"""Application factory, supervised recovery, safe errors and packaged SPA."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from walflow.api import queries
from walflow.api.operations import JobNotRerunnableError
from walflow.api.routes import router
from walflow.api.security import SecurityMiddleware, error_response
from walflow.domain.clock import SystemClock
from walflow.domain.errors import (
    IdempotencyConflictError,
    JobNotCancelableError,
    JobNotFoundError,
    RelayError,
    ValidationError,
)
from walflow.domain.policies import SystemRandom
from walflow.services.recovery import recover_expired_jobs
from walflow.services.setup import ensure_queue
from walflow.storage.migrations.runner import (
    apply_migrations,
    current_version,
    known_latest_version,
)
from walflow.storage.transactions import connect

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
clock = SystemClock()
logger = logging.getLogger("relay.api")


def create_app(db_path: str, token: str) -> FastAPI:
    if not token or token.strip() != token or len(token) > 4096:
        raise ValueError("a nonempty installation token is required")
    if db_path == ":memory:":
        raise ValueError("the API requires a file-backed database")
    with closing(connect(db_path)) as conn:
        apply_migrations(conn)
        ensure_queue(conn, clock=clock, name="default")

    def recover() -> None:
        with closing(connect(db_path)) as conn:
            recover_expired_jobs(conn, clock=clock, rng=SystemRandom(), batch_limit=50)

    async def maintenance(app: FastAPI, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.to_thread(recover)
                app.state.maintenance_last_ms = clock.now_ms()
                app.state.maintenance_ok = True
            except (sqlite3.Error, RelayError, OSError):
                app.state.maintenance_ok = False
                logger.error("maintenance_failed")
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=1.0)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        await asyncio.to_thread(recover)
        app.state.maintenance_last_ms = clock.now_ms()
        app.state.maintenance_ok = True
        task = asyncio.create_task(maintenance(app, stop))
        try:
            yield
        finally:
            stop.set()
            await task
            app.state.maintenance_ok = False

    app = FastAPI(
        title="Relay control API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.db_path = db_path
    app.state.maintenance_last_ms = None
    app.state.maintenance_ok = False
    app.add_middleware(SecurityMiddleware, token=token)
    app.include_router(router)

    @app.exception_handler(RelayError)
    async def domain_error(request: Request, exc: RelayError) -> JSONResponse:
        status = 422 if isinstance(exc, ValidationError) else 503
        if isinstance(exc, JobNotFoundError):
            status = 404
        elif isinstance(
            exc, (IdempotencyConflictError, JobNotCancelableError, JobNotRerunnableError)
        ):
            status = 409
        elif isinstance(exc, ValidationError) and "byte cap" in str(exc):
            status = 413
        message = str(exc) if status < 500 else "database operation unavailable"
        return error_response(status, exc.code, message, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo submitted values, credentials or parser internals.
        return error_response(422, "VALIDATION_ERROR", "invalid request", request.state.request_id)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
        busy = isinstance(exc, sqlite3.OperationalError) and (
            "locked" in str(exc) or "busy" in str(exc)
        )
        return error_response(
            503,
            "DATABASE_BUSY" if busy else "DATABASE_UNAVAILABLE",
            "database operation unavailable",
            request.state.request_id,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error_response(
            exc.status_code,
            "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
            "not found" if exc.status_code == 404 else "request rejected",
            request.state.request_id,
        )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        database = False
        try:
            with closing(connect(db_path)) as conn:
                database = current_version(conn) == known_latest_version()
                conn.execute("SELECT 1 FROM jobs LIMIT 1")
        except (sqlite3.Error, RelayError, OSError):
            pass
        last = app.state.maintenance_last_ms
        healthy = bool(
            app.state.maintenance_ok and last is not None and clock.now_ms() - last < 15_000
        )
        ok = database and healthy
        return JSONResponse(
            {
                "status": "ready" if ok else "not_ready",
                "database": database,
                "maintenance": healthy,
            },
            status_code=200 if ok else 503,
        )

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:
        with closing(connect(db_path)) as conn:
            summary = queries.overview(conn, clock.now_ms())
            rows = conn.execute("SELECT queue,state,count(*) FROM jobs GROUP BY queue,state")
            lines = [
                "# HELP relay_jobs Retained jobs by state and queue.",
                "# TYPE relay_jobs gauge",
            ]
            for queue, state, count in rows:
                lines.append(f'relay_jobs{{queue="{queue}",state="{state}"}} {count}')
        lines.extend(
            [
                "# HELP relay_queue_oldest_due_age_seconds Age of oldest due job.",
                "# TYPE relay_queue_oldest_due_age_seconds gauge",
            ]
        )
        for queue in summary["queues"]:
            age = (queue["oldest_due_age_ms"] or 0) / 1000
            lines.append(f'relay_queue_oldest_due_age_seconds{{queue="{queue["name"]}"}} {age}')
        lines.extend(
            ["# HELP relay_workers Workers by observed availability.", "# TYPE relay_workers gauge"]
        )
        for state, count in summary["workers"].items():
            lines.append(f'relay_workers{{state="{state}"}} {count}')
        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    @app.get("/{path:path}", include_in_schema=False)
    def static(path: str) -> Response:
        parts = Path(path).parts
        if (
            path.split("/", 1)[0] in {"api", "health", "metrics"}
            or "\\" in path
            or ":" in path
            or any(part.startswith(".") for part in parts)
        ):
            raise HTTPException(404)
        root = STATIC_DIR.resolve()
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(404)
        if candidate.is_file():
            return FileResponse(candidate)
        # Missing assets must not silently become HTML; only extensionless UI links fall back.
        index = (root / "index.html").resolve()
        if Path(path).suffix or not index.is_relative_to(root) or not index.is_file():
            raise HTTPException(404)
        return FileResponse(index, media_type="text/html")

    return app
