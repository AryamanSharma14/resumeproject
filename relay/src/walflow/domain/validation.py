"""Shared strict input validation at durable service boundaries."""

import json
import re
from collections.abc import Mapping

from walflow.domain.errors import ValidationError


def integer(value: int, name: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{name} must be an integer in {minimum}..{maximum}")


def queue_name(name: str) -> None:
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name) is None:
        raise ValidationError("queue must be 1..64 ASCII letters, digits, '.', '_' or '-'")


def bounded_json(value: Mapping[str, object], *, cap: int = 65_536) -> str:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValidationError("expected a JSON object with string keys")

    def check(item: object, depth: int = 0) -> None:
        if depth > 64:
            raise ValidationError("JSON nesting exceeds 64 levels")
        if item is None or type(item) in (str, int, float, bool):
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValidationError("JSON keys must be strings")
                check(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check(child, depth + 1)
        else:
            raise ValidationError("value contains a non-JSON type")

    check(value)
    try:
        encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))
        size = len(encoded.encode("utf-8"))
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValidationError("value must be finite, serializable JSON") from exc
    if size > cap:
        raise ValidationError(f"JSON exceeds {cap} byte cap")
    return encoded
