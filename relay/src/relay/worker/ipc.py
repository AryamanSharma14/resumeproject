"""One bounded JSON exchange per spawned child; never unpickle job messages."""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
from contextlib import suppress
from typing import Any, Protocol

from relay.domain.registry import get_handler


class Connection(Protocol):
    def send_bytes(self, buf: bytes) -> None: ...
    def recv_bytes(self, maxlength: int) -> bytes: ...
    def close(self) -> None: ...


MAX_MESSAGE_BYTES = 70_000
MAX_RESULT_BYTES = 65_536


def encode(message: dict[str, Any], cap: int = MAX_MESSAGE_BYTES) -> bytes:
    data = json.dumps(message, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(data) > cap:
        raise ValueError("JSON message exceeds byte limit")
    return data


def decode(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("JSON message exceeds byte limit")
    value = json.loads(data, parse_constant=lambda _: None)
    if not isinstance(value, dict):
        raise ValueError("JSON message must be an object")
    return value


def _watch_parent(done: threading.Event) -> None:
    parent = multiprocessing.parent_process()
    while not done.wait(0.1):
        if parent is not None and not parent.is_alive():
            # Built-ins have no external effects or descendants. Native hangs/process
            # trees are not an OS-containment guarantee; this is wrapper best effort.
            os._exit(72)


def child_main(channel: Connection) -> None:
    """Importable spawn target. No database path, connection or owner token."""
    done = threading.Event()
    threading.Thread(target=_watch_parent, args=(done,), daemon=True).start()
    try:
        request = decode(channel.recv_bytes(MAX_MESSAGE_BYTES))
        spec = get_handler(request["handler"])
        if request["version"] != spec.version:
            raise ValueError("unsupported handler version")
        payload = request["payload"]
        spec.validate(payload)
        if spec.name == "demo_flaky":
            payload["__attempt_number"] = request["attempt_number"]
        try:
            result = spec.run(payload)
        except Exception:
            response = {
                "ok": False,
                "code": "HANDLER_ERROR",
                "retryable": spec.name == "demo_flaky",
            }
        else:
            encode(result, MAX_RESULT_BYTES)
            response = {"ok": True, "result": result}
        channel.send_bytes(encode(response))
    except (Exception, KeyboardInterrupt):
        with suppress(OSError, ValueError):
            channel.send_bytes(
                encode({"ok": False, "code": "CHILD_PROTOCOL_ERROR", "retryable": False})
            )
    finally:
        done.set()
        channel.close()


class Exchange:
    """A single receiver thread bounds memory and isolates partial pipe reads."""

    def __init__(self, channel: Connection, request: bytes) -> None:
        self.done = threading.Event()
        self.response: dict[str, Any] | None = None
        self.channel = channel
        self.thread = threading.Thread(target=self._run, args=(request,), daemon=True)
        self.thread.start()

    def _run(self, request: bytes) -> None:
        try:
            self.channel.send_bytes(request)
            self.response = decode(self.channel.recv_bytes(MAX_MESSAGE_BYTES))
        except (OSError, EOFError, ValueError):
            self.response = {"ok": False, "code": "CHILD_PROTOCOL_ERROR", "retryable": False}
        finally:
            self.done.set()

    def close(self) -> None:
        self.channel.close()
        self.thread.join(timeout=0.2)
