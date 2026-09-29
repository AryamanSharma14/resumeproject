"""Exercise real domain behavior while verifying pytest discovery."""

from walflow.domain.clock import FakeClock
from walflow.domain.policies import DeterministicRandom, backoff_delay_ms


def test_retry_deadline_uses_injected_clock_and_randomness() -> None:
    clock = FakeClock(start_ms=10_000)
    delay = backoff_delay_ms(attempt_number=1, rng=DeterministicRandom())

    assert delay == 500
    retry_at = clock.now_ms() + delay
    clock.advance(delay - 1)
    assert clock.now_ms() < retry_at
    clock.advance(1)
    assert clock.now_ms() == retry_at
