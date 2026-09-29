"""Relay Python SDK: @task decorator and programmatic client."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from relay.config import database_path
from relay.domain.clock import Clock, SystemClock
from relay.domain.contracts import SubmitResult
from relay.domain.registry import HandlerSpec, register_handler
from relay.services.submit import submit_job
from relay.storage.transactions import connect

P = ParamSpec("P")
R = TypeVar("R")


class Task:
    """A registered background task with .delay() support."""

    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        name: str,
        queue: str = "default",
        version: str = "1",
        description: str = "",
        timeout_ms: int = 30_000,
        max_attempts: int = 3,
        priority: int = 0,
        relay: Relay | None = None,
    ) -> None:
        self.fn = fn
        self.name = name
        self.queue = queue
        self.version = version
        self.description = description or (fn.__doc__ or "").strip()
        self.timeout_ms = timeout_ms
        self.max_attempts = max_attempts
        self.priority = priority
        self.relay = relay
        self._register()

    def _register(self) -> None:
        def _validate(payload: dict[str, Any]) -> None:
            return

        def _run(payload: dict[str, Any]) -> dict[str, Any]:
            res = self.fn(**payload)
            if isinstance(res, dict):
                return res
            return {"result": res}

        register_handler(
            HandlerSpec(
                name=self.name,
                version=self.version,
                description=self.description,
                validate=_validate,
                run=_run,
            )
        )

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Execute synchronously in the current process."""
        return self.fn(*args, **kwargs)

    def delay(self, *args: Any, **kwargs: Any) -> SubmitResult:
        """Enqueue this task asynchronously using the associated or default Relay instance."""
        sig = inspect.signature(self.fn)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        payload = dict(bound.arguments)
        r = self.relay or Relay()
        return r.submit(
            handler=self.name,
            payload=payload,
            queue=self.queue,
            priority=self.priority,
            timeout_ms=self.timeout_ms,
            max_attempts=self.max_attempts,
        )


class Relay:
    """Programmatic client for Relay."""

    def __init__(self, db: str | Path | None = None, *, clock: Clock | None = None) -> None:
        self.db_path = str(db or database_path())
        self.clock = clock or SystemClock()

    def task(
        self,
        name: str | None = None,
        *,
        queue: str = "default",
        version: str = "1",
        description: str = "",
        timeout_ms: int = 30_000,
        max_attempts: int = 3,
        priority: int = 0,
    ) -> Callable[[Callable[..., Any]], Task]:
        """Decorator to register a function as a background task."""

        def decorator(fn: Callable[..., Any]) -> Task:
            task_name = name or fn.__name__
            return Task(
                fn,
                name=task_name,
                queue=queue,
                version=version,
                description=description,
                timeout_ms=timeout_ms,
                max_attempts=max_attempts,
                priority=priority,
                relay=self,
            )

        return decorator

    def submit(
        self,
        handler: str,
        payload: dict[str, Any],
        *,
        queue: str = "default",
        priority: int = 0,
        delay_ms: int = 0,
        max_attempts: int = 3,
        timeout_ms: int = 30_000,
        idempotency_key: str | None = None,
        depends_on: list[str] | None = None,
    ) -> SubmitResult:
        conn = connect(self.db_path)
        try:
            return submit_job(
                conn,
                clock=self.clock,
                handler=handler,
                payload=payload,
                queue=queue,
                priority=priority,
                delay_ms=delay_ms,
                max_attempts=max_attempts,
                timeout_ms=timeout_ms,
                idempotency_key=idempotency_key,
                depends_on=depends_on,
            )
        finally:
            conn.close()


def task(
    name: str | None = None,
    *,
    queue: str = "default",
    version: str = "1",
    description: str = "",
    timeout_ms: int = 30_000,
    max_attempts: int = 3,
    priority: int = 0,
) -> Callable[[Callable[..., Any]], Task]:
    """Standalone @task decorator bound to the default Relay database."""
    r = Relay()
    return r.task(
        name=name,
        queue=queue,
        version=version,
        description=description,
        timeout_ms=timeout_ms,
        max_attempts=max_attempts,
        priority=priority,
    )
