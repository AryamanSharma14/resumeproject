"""Typed domain errors mapped to stable API codes later."""

from __future__ import annotations


class RelayError(Exception):
    """Base class for all Relay domain errors."""

    code = "RELAY_ERROR"


class ValidationError(RelayError):
    code = "VALIDATION_ERROR"


class UnknownHandlerError(ValidationError):
    code = "HANDLER_UNAVAILABLE"


class UnknownQueueError(ValidationError):
    code = "QUEUE_UNAVAILABLE"


class IdempotencyConflictError(RelayError):
    """Same idempotency key reused with a different request body."""

    code = "IDEMPOTENCY_CONFLICT"


class JobNotFoundError(RelayError):
    code = "JOB_NOT_FOUND"


class JobNotCancelableError(RelayError):
    code = "JOB_NOT_CANCELABLE"


class StaleOwnerError(RelayError):
    """Completion/heartbeat rejected: ownership expired or superseded."""

    code = "STALE_OWNER"


class StorageBusyError(RelayError):
    code = "DATABASE_BUSY"
