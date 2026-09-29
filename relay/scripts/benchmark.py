"""Bounded core-only benchmark; run with the installed Relay environment.

python scripts/benchmark.py --jobs 1000 --workers 1 --seed 20260917
No API, child spawning or network is included. JSON stdout contains measurements,
not performance promises. Each run owns and removes a fresh file-backed database.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

from walflow.domain.clock import SystemClock
from walflow.domain.registry import get_handler
from walflow.services.claim import claim_job
from walflow.services.complete import complete_job
from walflow.services.setup import ensure_queue
from walflow.services.submit import submit_job
from walflow.storage.migrations import apply_migrations
from walflow.storage.transactions import connect


def percentiles(samples: list[float]) -> dict[str, float]:
    """Nearest-rank percentiles in milliseconds; no interpolated fake samples."""
    ordered = sorted(samples)
    if not ordered:
        raise ValueError("cannot summarize empty samples")
    return {
        f"p{p}_ms": round(ordered[max(0, math.ceil(p * len(ordered) / 100) - 1)] * 1000, 4)
        for p in (50, 95, 99)
    }


def benchmark(jobs: int, workers: int, seed: int, timeout_s: int) -> dict[str, Any]:
    if not 1 <= jobs <= 10_000 or not 1 <= workers <= 8 or not 1 <= timeout_s <= 300:
        raise ValueError("jobs 1..10000, workers 1..8 and timeout_s 1..300 required")
    clock = SystemClock()
    rng = random.Random(seed)
    # Keep temporary artifacts in the workspace rather than the user's general temp folder.
    with tempfile.TemporaryDirectory(
        prefix="relay-bench-", dir=Path(__file__).resolve().parents[1]
    ) as d:
        path = str(Path(d) / "benchmark.db")
        with closing(connect(path)) as conn:
            apply_migrations(conn)
            ensure_queue(conn, clock=clock, name="default")
            settings = {
                name: conn.execute(f"PRAGMA {name}").fetchone()[0]
                for name in ("journal_mode", "synchronous", "foreign_keys", "busy_timeout")
            }
            start = time.perf_counter()
            deadline = start + timeout_s
            submissions: list[float] = []
            for i in range(jobs):
                if time.perf_counter() >= deadline:
                    raise TimeoutError("benchmark exceeded its time budget during submission")
                text = " ".join(
                    rng.choice(("durable", "queue", "lease", "retry")) for _ in range(16)
                )
                before = time.perf_counter()
                submit_job(
                    conn,
                    clock=clock,
                    handler="text_summary",
                    payload={"text": text},
                    idempotency_key=f"benchmark-{seed}-{i}",
                    max_attempts=1,
                )
                submissions.append(time.perf_counter() - before)
            submitted_at = time.perf_counter()

            def drain(worker: int) -> tuple[list[float], list[float], int]:
                claims: list[float] = []
                completions: list[float] = []
                count = 0
                with closing(connect(path)) as own:
                    while True:
                        if time.perf_counter() >= deadline:
                            raise TimeoutError("benchmark exceeded its time budget during drain")
                        before = time.perf_counter()
                        claim = claim_job(
                            own,
                            clock=clock,
                            worker_id=f"benchmark-{worker}",
                            queues=["default"],
                            handlers=["text_summary"],
                        )
                        claim_elapsed = time.perf_counter() - before
                        if claim is None:
                            break
                        claims.append(claim_elapsed)
                        result = get_handler(claim["handler"]).run(json.loads(claim["payload"]))
                        before = time.perf_counter()
                        complete_job(
                            own,
                            clock=clock,
                            job_id=claim["job_id"],
                            attempt_id=claim["attempt_id"],
                            owner_token=claim["owner_token"],
                            result=result,
                        )
                        completions.append(time.perf_counter() - before)
                        count += 1
                return claims, completions, count

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(drain, worker) for worker in range(workers)]
                # result() propagates every worker failure; failed runs never emit throughput JSON.
                batches = [future.result() for future in futures]
            finished_at = time.perf_counter()
            claims = [sample for batch in batches for sample in batch[0]]
            completions = [sample for batch in batches for sample in batch[1]]
            verified = {
                "jobs": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                "succeeded": conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE state='succeeded'"
                ).fetchone()[0],
                "attempts": conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0],
                "events": conn.execute("SELECT COUNT(*) FROM job_events").fetchone()[0],
            }
            if verified != {"jobs": jobs, "succeeded": jobs, "attempts": jobs, "events": 3 * jobs}:
                raise AssertionError(f"invalid benchmark state: {verified}")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise AssertionError("SQLite integrity check failed")
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise AssertionError("foreign key check failed")
            return {
                "scope": "core services; submit phase then threaded claim/handler/complete drain",
                "environment": {
                    "python": sys.version,
                    "sqlite": sqlite3.sqlite_version,
                    "platform": platform.platform(),
                    "processor": platform.processor(),
                    "logical_cpus": os.cpu_count(),
                },
                "config": {
                    "jobs": jobs,
                    "workers": workers,
                    "seed": seed,
                    "timeout_s": timeout_s,
                    "sqlite": settings,
                    "payload": "16 seeded words; text_summary v1; max_attempts=1",
                },
                "submit": {
                    "seconds": round(submitted_at - start, 6),
                    "jobs_per_second": round(jobs / (submitted_at - start), 2),
                    **percentiles(submissions),
                },
                "claim": percentiles(claims),
                "complete": percentiles(completions),
                "drain": {
                    "seconds": round(finished_at - submitted_at, 6),
                    "jobs_per_second": round(jobs / (finished_at - submitted_at), 2),
                },
                "total": {
                    "seconds": round(finished_at - start, 6),
                    "jobs_per_second": round(jobs / (finished_at - start), 2),
                },
                "verified": verified,
                "bytes_before_close": {
                    p.name: p.stat().st_size for p in Path(d).glob("benchmark.db*")
                },
                "limitations": [
                    "Not supervisor/process throughput",
                    "No API or UI load",
                    "No warmup; fresh database; no retention load",
                    "Single run; machine and filesystem dependent",
                    "Timeout checked between calls; SQLite waits may exceed deadline",
                ],
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--timeout-s", type=int, default=120)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.jobs, args.workers, args.seed, args.timeout_s), indent=2))


if __name__ == "__main__":
    main()
