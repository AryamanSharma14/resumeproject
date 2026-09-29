"""Retry policy: bounded attempts with capped exponential backoff and jitter.

Budget semantics (per implementation-plan 6.7): max_attempts counts the initial
claim and every subsequent claim, including attempts lost to crashes. Backoff
cap after attempt n is min(60s, 1s * 2^(n-1)); the actual delay is sampled
uniformly from [0, cap] by the injected RNG and persisted once.
"""

from __future__ import annotations

import random
from typing import Final, Protocol

from walflow.domain.validation import integer

MAX_ATTEMPTS_FLOOR: Final = 1
MAX_ATTEMPTS_CEILING: Final = 10
BACKOFF_CAP_MS: Final = 60_000
BACKOFF_BASE_MS: Final = 1_000


class RandomSource(Protocol):
    """Injectable randomness so tests are deterministic."""

    def uniform(self, a: float, b: float) -> float: ...


class SystemRandom:
    """random.Random-backed source for production."""

    def __init__(self) -> None:
        self._rng = random.SystemRandom()

    def uniform(self, a: float, b: float) -> float:
        return self._rng.uniform(a, b)


class DeterministicRandom:
    """Always returns the midpoint: useful for assertions."""

    def uniform(self, a: float, b: float) -> float:
        return (a + b) / 2.0


def backoff_delay_ms(attempt_number: int, rng: RandomSource) -> int:
    """Delay before the retry that follows `attempt_number` (1-based).

    attempt_number=1 is the first execution; its failure schedules retry 2.
    """
    integer(attempt_number, "attempt_number", 1, MAX_ATTEMPTS_CEILING)
    cap = min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * (2 ** (attempt_number - 1)))
    return int(rng.uniform(0, cap))


def clamp_max_attempts(value: int) -> int:
    """Raise outside 1..10 rather than silently clamping user intent."""
    integer(value, "max_attempts", MAX_ATTEMPTS_FLOOR, MAX_ATTEMPTS_CEILING)
    return value
