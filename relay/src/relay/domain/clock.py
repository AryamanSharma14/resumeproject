"""Injectable time. Production uses wall clock; tests use a fake."""

from __future__ import annotations

from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int: ...


class SystemClock:
    """Wall clock, UTC integer milliseconds (persistence convention)."""

    def now_ms(self) -> int:
        import datetime as _dt

        return int(_dt.datetime.now(tz=_dt.UTC).timestamp() * 1000)


class FakeClock:
    """Manually advanced clock for deterministic tests."""

    def __init__(self, start_ms: int = 1_000_000_000_000) -> None:
        self._now = start_ms

    def now_ms(self) -> int:
        return self._now

    def advance(self, ms: int) -> None:
        self._now += ms
