"""Strict boundary validation: typed errors, no raw exceptions, no silent coercions."""

import pytest

from relay.domain.errors import (
    IdempotencyConflictError,
    UnknownHandlerError,
    UnknownQueueError,
    ValidationError,
)
from relay.domain.validation import bounded_json, integer, queue_name
from relay.services.claim import claim_job
from relay.services.complete import complete_job
from relay.services.setup import pause_queue, resume_queue
from relay.services.submit import submit_job


def test_integer_rejects_bools_and_coercions():
    for bad in (True, False, 1.0, "3", None):
        try:
            integer(bad, "x", 0, 10)  # type: ignore[arg-type]
        except ValidationError:
            pass
        else:
            raise AssertionError(f"integer accepted {bad!r}")
    integer(3, "x", 0, 10)


def test_queue_name_rules():
    for bad in ("", " spaced", "uniçode", "x" * 65, ".hidden", 5, None):
        try:
            queue_name(bad)  # type: ignore[arg-type]
        except ValidationError:
            pass
        else:
            raise AssertionError(f"queue_name accepted {bad!r}")
    queue_name("Aa0._-9")


def test_bounded_json_rejects_non_json_and_cycles():
    assert bounded_json({"a": [1, {"b": None}]}) == '{"a":[1,{"b":null}]}'
    for bad in (set(), {1: "int-key"}, {"x": object()}, {"x": float("nan")}, 5, "str"):
        try:
            bounded_json(bad)  # type: ignore[arg-type]
        except ValidationError:
            pass
        else:
            raise AssertionError(f"bounded_json accepted {bad!r}")
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    try:
        bounded_json(cyclic)
    except ValidationError:
        pass
    else:
        raise AssertionError("bounded_json accepted a cyclic value")


def test_submit_rejects_non_object_payloads(db, clock, default_queue):
    for payload in ([], "text", 7, None, [("text", "x")]):
        try:
            submit_job(db, clock=clock, handler="text_summary", payload=payload)  # type: ignore[arg-type]
        except ValidationError:
            pass
        else:
            raise AssertionError(f"submit accepted payload {payload!r}")
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_submit_rejects_bool_int_fields_and_bad_scope(db, clock, default_queue):
    cases = [
        {"delay_ms": True},
        {"priority": False},
        {"timeout_ms": True},
        {"max_attempts": False},
        {"idempotency_scope": "has space"},
        {"idempotency_scope": ""},
        {"idempotency_key": 5},
        {"idempotency_key": ""},
    ]
    for overrides in cases:
        kwargs: dict[str, object] = {
            "handler": "text_summary",
            "payload": {"text": "ok"},
            **overrides,
        }
        try:
            submit_job(db, clock=clock, **kwargs)  # type: ignore[arg-type]
        except ValidationError:
            pass
        else:
            raise AssertionError(f"submit accepted {overrides}")
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_claim_rejects_bad_worker_queues_handlers(db, clock, default_queue):
    submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"})
    bad_calls = [
        {"worker_id": ""},
        {"worker_id": 7},
        {"queues": ["bad queue"]},
        {"queues": [5]},
        {"queues": []},
        {"handlers": ["nope"]},
        {"handlers": [5]},
        {"handlers": []},
        {"handler_versions": {"text_summary": 1}},
        {"handler_versions": {"text_summary": ""}},
        {"handler_versions": {"text_summary": "1"}, "handlers": ["demo_flaky"]},
        {"lease_ms": 0},
    ]
    for overrides in bad_calls:
        kwargs: dict[str, object] = {
            "worker_id": "w",
            "queues": ["default"],
            "handlers": ["text_summary"],
            **overrides,
        }
        try:
            claim_job(db, clock=clock, **kwargs)  # type: ignore[arg-type]
        except (ValidationError, UnknownHandlerError):
            pass
        else:
            raise AssertionError(f"claim accepted {overrides}")
    assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


def test_t19_unsupported_version_is_silently_unclaimable(db, clock, default_queue):
    submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"})
    for _ in range(5):
        assert (
            claim_job(
                db,
                clock=clock,
                worker_id="w",
                queues=["default"],
                handlers=["text_summary"],
                handler_versions={"text_summary": "999"},
            )
            is None
        )
    row = db.execute("SELECT attempt_count, state FROM jobs").fetchone()
    assert row["attempt_count"] == 0  # no budget burned by the unsupported version
    assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM job_events WHERE kind='claimed'").fetchone()[0] == 0
    c = claim_job(db, clock=clock, worker_id="w", queues=["default"], handlers=["text_summary"])
    assert c is not None and c["handler_version"] == "1"


def test_t18_paused_queue_blocks_new_claims_only(db, clock, default_queue):
    submit_job(db, clock=clock, handler="text_summary", payload={"text": "x"})
    c = claim_job(
        db,
        clock=clock,
        worker_id="w",
        queues=["default"],
        handlers=["text_summary"],
        lease_ms=10_000,
    )
    assert c is not None
    pause_queue(db, clock=clock, name="default")
    submit_job(db, clock=clock, handler="text_summary", payload={"text": "y"})
    assert (
        claim_job(db, clock=clock, worker_id="w", queues=["default"], handlers=["text_summary"])
        is None
    )
    complete_job(
        db,
        clock=clock,
        job_id=c["job_id"],
        attempt_id=c["attempt_id"],
        owner_token=c["owner_token"],
        result={"done": True},
    )
    resume_queue(db, clock=clock, name="default")
    resumed = claim_job(
        db, clock=clock, worker_id="w", queues=["default"], handlers=["text_summary"]
    )
    assert resumed is not None


def test_pause_resume_unknown_queue_typed_error(db, clock, default_queue):
    with pytest.raises(UnknownQueueError):
        pause_queue(db, clock=clock, name="never-created")
    with pytest.raises(UnknownQueueError):
        resume_queue(db, clock=clock, name="never-created")
    pause_queue(db, clock=clock, name="default")  # idempotent for existing queue
    pause_queue(db, clock=clock, name="default")
    resume_queue(db, clock=clock, name="default")
    resume_queue(db, clock=clock, name="default")


def test_same_scope_namespaces_are_independent(db, clock, default_queue):
    submit_job(
        db,
        clock=clock,
        handler="text_summary",
        payload={"text": "a"},
        idempotency_scope="submit",
        idempotency_key="shared",
    )
    submit_job(
        db,
        clock=clock,
        handler="text_summary",
        payload={"text": "b"},
        idempotency_scope="rerun",
        idempotency_key="shared",
    )
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
    with pytest.raises(IdempotencyConflictError):
        submit_job(
            db,
            clock=clock,
            handler="text_summary",
            payload={"text": "c"},
            idempotency_scope="submit",
            idempotency_key="shared",
        )
