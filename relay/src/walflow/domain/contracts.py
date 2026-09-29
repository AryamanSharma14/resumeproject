"""Typed service results; payload stays JSON text in a claim for worker IPC."""

from typing import NotRequired, TypedDict


class SubmitResult(TypedDict):
    job_id: str
    replayed: bool


class ClaimResult(TypedDict):
    job_id: str
    attempt_id: str
    attempt_number: int
    owner_token: str
    handler: str
    handler_version: str
    payload: str
    payload_data: dict[str, object]
    queue: str
    timeout_ms: int
    lease_expires_at: int


class FailureResult(TypedDict):
    outcome: str
    retry_at: NotRequired[int]


class RecoveryResult(FailureResult):
    job_id: str


class CancelResult(TypedDict):
    job_id: str
    state: str


class RecoveryOutcome(TypedDict):
    job_id: str
    outcome: str
    retry_at: NotRequired[int]
