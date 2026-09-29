"""Versioned control routes; all blocking SQLite work stays in sync endpoints."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import StreamingResponse

from relay.api import operations, queries, schemas
from relay.domain.clock import SystemClock
from relay.domain.validation import bounded_json
from relay.services.cancel import cancel_job
from relay.services.cron import (
    add_schedule,
    delete_schedule,
    list_schedules,
    pause_schedule,
    resume_schedule,
    trigger_schedule_now,
)
from relay.services.dlq import list_dlq_jobs, redrive_bulk, redrive_job
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
        "version": "0.2.0",
        "schema_version": schema_version,
        "database_size_bytes": size,
        "maintenance_last_at": queries.timestamp(last) if last is not None else None,
        "as_of": queries.timestamp(clock.now_ms()),
    }


# Cron schedules
@router.get("/schedules")
def get_schedules(request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return {"items": list_schedules(conn)}


@router.post("/schedules", status_code=201)
def create_schedule(body: schemas.ScheduleCreate, request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return add_schedule(conn, clock=clock, **body.model_dump())


@router.post("/schedules/{name}/pause")
def pause_sched(name: str, request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        ok = pause_schedule(conn, name=name)
    return {"name": name, "paused": ok}


@router.post("/schedules/{name}/resume")
def resume_sched(name: str, request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        ok = resume_schedule(conn, clock=clock, name=name)
    return {"name": name, "resumed": ok}


@router.post("/schedules/{name}/trigger")
def trigger_sched(name: str, request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return trigger_schedule_now(conn, clock=clock, name=name)


@router.delete("/schedules/{name}")
def delete_sched(name: str, request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        ok = delete_schedule(conn, name=name)
    return {"name": name, "deleted": ok}


# DLQ endpoints
@router.get("/dlq")
def get_dlq(
    request: Request,
    queue: str | None = None,
    handler: str | None = None,
    error_code: str | None = None,
    limit: Limit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return list_dlq_jobs(
            conn, queue=queue, handler=handler, error_code=error_code, limit=limit, offset=offset
        )


@router.post("/dlq/{job_id}/redrive")
def redrive_one(job_id: str, body: schemas.RedriveRequest, request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return redrive_job(
            conn,
            clock=clock,
            job_id=job_id,
            reset_attempts=body.reset_attempts,
            updated_payload=body.updated_payload,
        )


@router.post("/dlq/redrive-all")
def redrive_all(body: schemas.RedriveBulkRequest, request: Request) -> dict[str, Any]:
    with closing(connection(request)) as conn:
        return redrive_bulk(
            conn,
            clock=clock,
            queue=body.queue,
            handler=body.handler,
            error_code=body.error_code,
            limit=body.limit,
        )


# Realtime Events SSE stream
@router.get("/events/stream")
def events_stream(
    request: Request, last_event_id: Annotated[int, Query(ge=0)] = 0
) -> StreamingResponse:
    def _generator() -> Iterator[str]:
        seq = last_event_id
        db_path = str(request.app.state.db_path)
        for _ in range(60):
            with closing(connect(db_path)) as conn:
                rows = conn.execute(
                    "SELECT seq, job_id, attempt_id, kind, created_at, detail_json "
                    "FROM job_events WHERE seq > ? ORDER BY seq ASC LIMIT 50",
                    (seq,),
                ).fetchall()
            for r in rows:
                seq = r["seq"]
                payload = {
                    "seq": r["seq"],
                    "job_id": r["job_id"],
                    "attempt_id": r["attempt_id"],
                    "kind": r["kind"],
                    "created_at": r["created_at"],
                    "detail": json.loads(r["detail_json"]) if r["detail_json"] else None,
                }
                yield f"id: {seq}\nevent: {r['kind']}\ndata: {json.dumps(payload)}\n\n"
            time.sleep(0.5)

    return StreamingResponse(_generator(), media_type="text/event-stream")
