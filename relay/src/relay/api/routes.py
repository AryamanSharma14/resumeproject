"""Versioned control routes; all blocking SQLite work stays in sync endpoints."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, Response

from relay.api import operations, queries, schemas
from relay.domain.clock import SystemClock
from relay.domain.validation import bounded_json
from relay.services.cancel import cancel_job
from relay.services.setup import pause_queue, resume_queue
from relay.services.submit import submit_job
from relay.storage.migrations.runner import current_version
from relay.storage.transactions import connect

Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=512)]
Key = Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=200)]
router = APIRouter(prefix="/api/v1")
clock = SystemClock()


def connection(request: Request) -> sqlite3.Connection:
    return connect(str(request.app.state.db_path))


@router.post("/jobs", status_code=201)
def submit(
    body: schemas.Submission, request: Request, response: Response, idempotency_key: Key = None
) -> dict[str, Any]:
    bounded_json(body.payload)
    with closing(connection(request)) as conn:
        result = submit_job(conn, clock=clock, **body.model_dump(), idempotency_key=idempotency_key)
    response.status_code = 200 if result["replayed"] else 201
    return dict(result)


@router.get("/jobs")
def jobs(
    request: Request,
    state: str | None = None,
    queue: str | None = None,
    handler: Annotated[str | None, Query(max_length=64)] = None,
    created_after: str | None = None,
    created_before: str | None = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return queries.list_jobs(
            conn,
            state=state,
            queue=queue,
            handler=handler,
            created_after=created_after,
            created_before=created_before,
            cursor=cursor,
            limit=limit,
        )


@router.get("/jobs/{job_id}")
def job(job_id: str, request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return queries.get_job(conn, job_id)


@router.get("/jobs/{job_id}/attempts")
def attempts(
    job_id: str, request: Request, cursor: Annotated[int, Query(ge=0)] = 0, limit: Limit = 50
) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return queries.history(conn, job_id, events=False, cursor=cursor, limit=limit)


@router.get("/jobs/{job_id}/events")
def events(
    job_id: str, request: Request, cursor: Annotated[int, Query(ge=0)] = 0, limit: Limit = 50
) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return queries.history(conn, job_id, events=True, cursor=cursor, limit=limit)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str, request: Request) -> dict[str, str]:
    with closing(connection(request)) as conn:
        return cancel_job(conn, clock=clock, job_id=job_id)


@router.post("/jobs/{job_id}/rerun", status_code=201)
def rerun(
    job_id: str,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        result = operations.rerun_job(
            conn, clock=clock, job_id=job_id, idempotency_key=idempotency_key
        )
    response.status_code = 200 if result["replayed"] else 201
    return dict(result)


@router.get("/queues")
def queues(request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return {"items": queries.queues(conn, clock.now_ms())}


@router.post("/queues/{name}/pause")
def pause(name: str, request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        pause_queue(conn, clock=clock, name=name)
    return {"name": name, "paused": True}


@router.post("/queues/{name}/resume")
def resume(name: str, request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        resume_queue(conn, clock=clock, name=name)
    return {"name": name, "paused": False}


@router.get("/workers")
def workers(request: Request, cursor: Cursor = None, limit: Limit = 50) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return queries.workers(conn, clock.now_ms(), cursor=cursor, limit=limit)


@router.get("/handlers")
def handlers() -> dict[str, Any]:
    return schemas.handlers()


@router.get("/overview")
def overview(request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return queries.overview(conn, clock.now_ms())


@router.get("/system")
def system(request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        schema_version = current_version(conn)
    db = Path(request.app.state.db_path)
    size = db.stat().st_size
    wal = Path(str(db) + "-wal")
    if wal.exists():
        size += wal.stat().st_size
    last = request.app.state.maintenance_last_ms
    return {
        "version": "0.1.0",
        "schema_version": schema_version,
        "database_size_bytes": size,
        "maintenance_last_at": queries.timestamp(last) if last is not None else None,
        "as_of": queries.timestamp(clock.now_ms()),
    }
