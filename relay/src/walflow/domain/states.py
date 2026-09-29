"""Domain states and the legal transition table.

Job states are persisted exactly as defined here. The state machine is the
correctness core: every service transition must go through a conditional
UPDATE gated on the job's current state (see storage.transactions).
"""

from __future__ import annotations

from typing import Final


class JobState:
    """String constants so SQL CHECK constraints and code agree."""

    QUEUED: Final = "queued"
    RUNNING: Final = "running"
    RETRY_WAIT: Final = "retry_wait"
    SUCCEEDED: Final = "succeeded"
    FAILED: Final = "failed"
    CANCELED: Final = "canceled"


JOB_STATES: Final[frozenset[str]] = frozenset(
    {
        JobState.QUEUED,
        JobState.RUNNING,
        JobState.RETRY_WAIT,
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.CANCELED,
    }
)

CLAIMABLE_STATES: Final[frozenset[str]] = frozenset({JobState.QUEUED, JobState.RETRY_WAIT})
CANCELABLE_STATES: Final[frozenset[str]] = CLAIMABLE_STATES
TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELED}
)


class AttemptState:
    RUNNING: Final = "running"
    SUCCEEDED: Final = "succeeded"
    FAILED: Final = "failed"
    TIMED_OUT: Final = "timed_out"
    LOST: Final = "lost"


ATTEMPT_STATES: Final[frozenset[str]] = frozenset(
    {
        AttemptState.RUNNING,
        AttemptState.SUCCEEDED,
        AttemptState.FAILED,
        AttemptState.TIMED_OUT,
        AttemptState.LOST,
    }
)

# kinds used in job_events; keep closed so consumers can rely on them
EVENT_SUBMITTED: Final = "submitted"
EVENT_CLAIMED: Final = "claimed"
EVENT_SUCCEEDED: Final = "succeeded"
EVENT_FAILED: Final = "failed"
EVENT_RETRY_SCHEDULED: Final = "retry_scheduled"
EVENT_ATTEMPT_LOST: Final = "attempt_lost"
EVENT_TIMED_OUT: Final = "timed_out"
EVENT_CANCELED: Final = "canceled"
EVENT_PROGRESS: Final = "progress"
EVENT_REDRIVEN: Final = "redriven"
