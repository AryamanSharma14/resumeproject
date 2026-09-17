"""Spawn supervisor: fenced writes, independent recovery and bounded drain."""

from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import socket
import sqlite3
import time
import uuid
from dataclasses import dataclass
from multiprocessing.process import BaseProcess
from types import FrameType
from typing import Any

from relay.domain.clock import SystemClock
from relay.domain.contracts import ClaimResult
from relay.domain.errors import RelayError, StaleOwnerError
from relay.domain.policies import SystemRandom
from relay.domain.registry import HANDLERS
from relay.services.claim import claim_job
from relay.services.complete import complete_job, fail_job, heartbeat
from relay.services.recovery import recover_expired_jobs
from relay.storage.migrations import current_version, known_latest_version
from relay.storage.transactions import connect, immediate_transaction
from relay.worker.ipc import Exchange, child_main, encode

LOG = logging.getLogger("relay.worker")


@dataclass(frozen=True)
class WorkerConfig:
    db_path: str
    queues: tuple[str, ...] = ("default",)
    concurrency: int = 2
    lease_ms: int = 30_000
    heartbeat_ms: int = 5_000
    recovery_ms: int = 2_000
    poll_ms: int = 250
    grace_ms: int = 30_000

    def __post_init__(self) -> None:
        if not 1 <= self.concurrency <= 8 or not self.queues:
            raise ValueError("concurrency must be 1..8 and queues nonempty")
        if not 100 <= self.lease_ms <= 600_000:
            raise ValueError("lease_ms must be 100..600000")
        if not 0 < self.heartbeat_ms < self.lease_ms / 2:
            raise ValueError("heartbeat must be less than half the lease")
        if min(self.recovery_ms, self.poll_ms) <= 0 or self.grace_ms < 0:
            raise ValueError("invalid polling or grace duration")


@dataclass
class Slot:
    claim: ClaimResult
    process: BaseProcess
    exchange: Exchange
    deadline: float
    renew_at: float
    safe_until: float
    response: dict[str, Any] | None = None


def stop_child(process: BaseProcess) -> None:
    if process.is_alive():
        process.terminate()
    process.join(timeout=0.5)
    if process.is_alive():
        process.kill()
        process.join(timeout=0.5)


class Supervisor:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self.worker_id = str(uuid.uuid4())
        self.clock = SystemClock()
        self.rng = SystemRandom()
        self.slots: list[Slot] = []
        self.drain_at: float | None = None
        self.conn: sqlite3.Connection | None = None
        self.context = multiprocessing.get_context("spawn")

    def request_stop(self, signum: int = 0, frame: FrameType | None = None) -> None:
        if self.drain_at is None:
            self.drain_at = time.monotonic() + self.config.grace_ms / 1000

    def _register(self, state: str) -> None:
        assert self.conn is not None
        now = self.clock.now_ms()
        with immediate_transaction(self.conn):
            self.conn.execute(
                "INSERT INTO workers VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "heartbeat_at=excluded.heartbeat_at,state=excluded.state",
                (
                    self.worker_id,
                    socket.gethostname(),
                    os.getpid(),
                    now,
                    now,
                    state,
                    self.config.concurrency,
                    encode({"queues": self.config.queues})
                    .decode()
                    .removeprefix('{"queues":')
                    .removesuffix("}"),
                    encode({name: spec.version for name, spec in HANDLERS.items()}).decode(),
                ),
            )

    def _fence(self, slot: Slot) -> dict[str, str]:
        return {
            "job_id": slot.claim["job_id"],
            "attempt_id": slot.claim["attempt_id"],
            "owner_token": slot.claim["owner_token"],
        }

    def _launch(self, claim: ClaimResult) -> None:
        parent, child = self.context.Pipe(duplex=True)
        process = self.context.Process(target=child_main, args=(child,), daemon=True)
        now = time.monotonic()
        try:
            process.start()
            exchange = Exchange(
                parent,
                encode(
                    {
                        "handler": claim["handler"],
                        "version": claim["handler_version"],
                        "payload": claim["payload_data"],
                        "job_id": claim["job_id"],
                        "attempt_number": claim["attempt_number"],
                    }
                ),
            )
        except Exception:
            parent.close()
            if process.pid is not None:
                stop_child(process)
            assert self.conn is not None
            fail_job(
                self.conn,
                clock=self.clock,
                job_id=claim["job_id"],
                attempt_id=claim["attempt_id"],
                owner_token=claim["owner_token"],
                error_code="CHILD_START_FAILED",
                error_summary="child startup failed",
                rng=self.rng,
                retryable=True,
            )
            return
        finally:
            child.close()
        self.slots.append(
            Slot(
                claim,
                process,
                exchange,
                now + claim["timeout_ms"] / 1000,
                now + self.config.heartbeat_ms / 1000,
                now + self.config.lease_ms / 1000,
            )
        )

    def _dispose(self, slot: Slot) -> None:
        stop_child(slot.process)
        slot.exchange.close()
        slot.process.close()
        self.slots.remove(slot)

    def _service(self, slot: Slot) -> None:
        assert self.conn is not None
        now = time.monotonic()
        if now >= slot.safe_until:
            LOG.warning("ownership uncertain; abandoning child job=%s", slot.claim["job_id"])
            self._dispose(slot)
            return
        if slot.response is None:
            if now >= slot.deadline:
                stop_child(slot.process)
                slot.response = {"ok": False, "code": "TIMED_OUT", "retryable": True}
            elif self.drain_at is not None and now >= self.drain_at:
                stop_child(slot.process)
                slot.response = {"ok": False, "code": "WORKER_STOPPED", "retryable": True}
            elif slot.exchange.done.is_set():
                slot.response = slot.exchange.response
        try:
            if now >= slot.renew_at:
                if not heartbeat(
                    self.conn, clock=self.clock, **self._fence(slot), lease_ms=self.config.lease_ms
                ):
                    self._dispose(slot)
                    return
                slot.safe_until = now + self.config.lease_ms / 1000
                slot.renew_at = now + self.config.heartbeat_ms / 1000
            response = slot.response
            if response is None:
                return
            if response.get("ok") is True and isinstance(response.get("result"), dict):
                complete_job(
                    self.conn, clock=self.clock, **self._fence(slot), result=response["result"]
                )
                LOG.info("job succeeded job=%s", slot.claim["job_id"])
            else:
                code = str(response.get("code", "CHILD_PROTOCOL_ERROR"))[:100]
                fail_job(
                    self.conn,
                    clock=self.clock,
                    **self._fence(slot),
                    rng=self.rng,
                    error_code=code,
                    error_summary=code,
                    retryable=response.get("retryable") is True,
                    timed_out=code == "TIMED_OUT",
                )
            self._dispose(slot)
        except StaleOwnerError:
            LOG.warning("stale result rejected job=%s", slot.claim["job_id"])
            self._dispose(slot)

    def run(self, *, install_signals: bool = True, max_runtime: float | None = None) -> None:
        """Run until signal/drain; max_runtime supports bounded embedding/tests."""
        previous: dict[int, Any] = {}
        if install_signals:
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, self.request_stop)
        started = time.monotonic()
        maintenance = registration = 0.0
        try:
            self.conn = connect(self.config.db_path, busy_timeout_ms=50)
            if current_version(self.conn) != known_latest_version():
                raise ValueError("incompatible schema; run relay db migrate")
            while True:
                now = time.monotonic()
                if max_runtime is not None and now - started >= max_runtime:
                    self.request_stop()
                try:
                    for slot in list(self.slots):
                        self._service(slot)
                    if now >= registration:
                        self._register("draining" if self.drain_at is not None else "online")
                        registration = now + self.config.heartbeat_ms / 1000
                    if now >= maintenance:
                        recover_expired_jobs(self.conn, clock=self.clock, rng=self.rng)
                        maintenance = now + self.config.recovery_ms / 1000
                    if self.drain_at is None:
                        while len(self.slots) < self.config.concurrency:
                            claim = claim_job(
                                self.conn,
                                clock=self.clock,
                                worker_id=self.worker_id,
                                queues=list(self.config.queues),
                                handlers=list(HANDLERS),
                                lease_ms=self.config.lease_ms,
                            )
                            if claim is None:
                                break
                            self._launch(claim)
                except (sqlite3.Error, RelayError):
                    LOG.warning("database operation failed; no new claims this cycle")
                    for slot in list(self.slots):
                        if time.monotonic() >= slot.safe_until:
                            self._dispose(slot)
                if self.drain_at is not None and not self.slots:
                    break
                time.sleep(min(self.config.poll_ms / 1000, 0.25))
        finally:
            for slot in list(self.slots):
                self._dispose(slot)
            if self.conn is not None:
                try:
                    self._register("offline")
                except (sqlite3.Error, RelayError):
                    LOG.warning("could not mark worker offline")
                self.conn.close()
            for previous_sig, handler in previous.items():
                signal.signal(previous_sig, handler)
