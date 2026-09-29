"""Built-in handler registry.

Handlers are declared, not imported arbitrarily: payload/output contracts are
explicit and everything is pure and bounded. This registry is the single place
a handler ID becomes executable code. v1 scope: four demonstration handlers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from relay.domain.errors import UnknownHandlerError, ValidationError


@dataclass(frozen=True)
class HandlerSpec:
    name: str
    version: str
    description: str
    validate: Callable[[dict[str, Any]], None]
    run: Callable[[dict[str, Any]], dict[str, Any]]


def _require(d: dict[str, Any], key: str, typ: type, cap: int) -> Any:
    if key not in d:
        raise ValidationError(f"payload field '{key}' is required")
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, typ):
        raise ValidationError(f"payload field '{key}' must be {typ.__name__}")
    if isinstance(v, str) and len(v) > cap:
        raise ValidationError(f"payload field '{key}' exceeds {cap} characters")
    return v


def _run_text_summary(payload: dict[str, Any]) -> dict[str, Any]:
    text: str = payload["text"]
    words = text.split()
    return {
        "characters": len(text),
        "words": len(words),
        "lines": text.count("\n") + 1 if text else 0,
    }


def _run_batch_statistics(payload: dict[str, Any]) -> dict[str, Any]:
    numbers = payload["numbers"]
    if not numbers:
        raise ValidationError("numbers must be a non-empty list")
    import math

    for n in numbers:
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n):
            raise ValidationError("payload 'numbers' must contain finite numbers only")
    count = len(numbers)
    total = float(sum(numbers))
    return {
        "count": count,
        "min": min(numbers),
        "max": max(numbers),
        "mean": total / count,
    }


def _run_demo_flaky(payload: dict[str, Any]) -> dict[str, Any]:
    fail_times = payload["fail_times"]
    attempt = payload["__attempt_number"]
    if attempt <= fail_times:
        raise RuntimeError(f"demo_flaky induced failure on attempt {attempt}")
    return {"succeeded_on_attempt": attempt}


def _run_demo_delay(payload: dict[str, Any]) -> dict[str, Any]:
    import time

    total_ms = payload["duration_ms"]
    slept = 0
    while slept < total_ms:
        step = min(50, total_ms - slept)
        time.sleep(step / 1000.0)
        slept += step
    return {"slept_ms": slept}


def _validate_text_summary(payload: dict[str, Any]) -> None:
    _require(payload, "text", str, 100_000)
    unknown = set(payload) - {"text"}
    if unknown:
        raise ValidationError(f"unknown payload fields: {sorted(unknown)}")


def _validate_batch_statistics(payload: dict[str, Any]) -> None:
    numbers = _require(payload, "numbers", list, 0)
    import math

    if not 1 <= len(numbers) <= 10_000:
        raise ValidationError("payload 'numbers' must contain 1..10000 items")
    for n in numbers:
        try:
            finite = not isinstance(n, bool) and isinstance(n, (int, float)) and math.isfinite(n)
        except OverflowError:
            finite = False
        if not finite:
            raise ValidationError("payload 'numbers' must contain finite numbers only")
    unknown = set(payload) - {"numbers"}
    if unknown:
        raise ValidationError(f"unknown payload fields: {sorted(unknown)}")


def _validate_demo_flaky(payload: dict[str, Any]) -> None:
    ft = _require(payload, "fail_times", int, 0)
    if not 0 <= ft <= 5:
        raise ValidationError("payload 'fail_times' must be 0..5")
    unknown = set(payload) - {"fail_times"}
    if unknown:
        raise ValidationError(f"unknown payload fields: {sorted(unknown)}")


def _validate_demo_delay(payload: dict[str, Any]) -> None:
    d = _require(payload, "duration_ms", int, 0)
    if not 0 <= d <= 30_000:
        raise ValidationError("payload 'duration_ms' must be 0..30000")
    unknown = set(payload) - {"duration_ms"}
    if unknown:
        raise ValidationError(f"unknown payload fields: {sorted(unknown)}")


HANDLERS: Final[dict[str, HandlerSpec]] = {
    "text_summary": HandlerSpec(
        "text_summary",
        "1",
        "Count characters, words and lines of a bounded string.",
        _validate_text_summary,
        _run_text_summary,
    ),
    "batch_statistics": HandlerSpec(
        "batch_statistics",
        "1",
        "Count/min/max/mean over a bounded numeric list.",
        _validate_batch_statistics,
        _run_batch_statistics,
    ),
    "demo_flaky": HandlerSpec(
        "demo_flaky",
        "1",
        "Fail the first N attempts then succeed (demonstration).",
        _validate_demo_flaky,
        _run_demo_flaky,
    ),
    "demo_delay": HandlerSpec(
        "demo_delay",
        "1",
        "Sleep a bounded duration in increments (watchdog demo).",
        _validate_demo_delay,
        _run_demo_delay,
    ),
}


def get_handler(name: str) -> HandlerSpec:
    if not isinstance(name, str):
        raise UnknownHandlerError("handler name must be text")
    try:
        return HANDLERS[name]
    except KeyError:
        raise UnknownHandlerError(f"unknown handler: {name}") from None


def register_handler(spec: HandlerSpec) -> None:
    if not isinstance(spec, HandlerSpec):
        raise ValidationError("handler must be a HandlerSpec instance")
    HANDLERS[spec.name] = spec


def validate_payload(name: str, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict) or any(not isinstance(k, str) for k in payload):
        raise ValidationError("payload must be a JSON object with string keys")
    get_handler(name).validate(payload)
