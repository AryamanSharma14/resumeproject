"""Property/invariant tests: randomized legal transitions keep invariants (T10, T12 style)."""

import contextlib
import random

from walflow.domain.errors import StaleOwnerError
from walflow.domain.policies import backoff_delay_ms
from walflow.services.cancel import cancel_job
from walflow.services.claim import claim_job
from walflow.services.complete import complete_job, fail_job, heartbeat
from walflow.services.recovery import recover_expired_jobs
from walflow.services.submit import submit_job


def _owner(claim: dict) -> dict:
    return {k: claim[k] for k in ("job_id", "attempt_id", "owner_token")}


def _invariants(conn) -> None:
    # ownership consistency: running iff lease fields set; at most one running attempt
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE state='running' AND (owner_token IS NULL"
            " OR active_attempt_id IS NULL OR lease_expires_at IS NULL)"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE state!='running' AND owner_token IS NOT NULL"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM (SELECT job_id FROM attempts WHERE state='running'"
            " GROUP BY job_id HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM jobs j LEFT JOIN attempts a ON a.id=j.active_attempt_id "
            "WHERE j.state='running' AND (a.id IS NULL OR a.state!='running' "
            "OR a.owner_token!=j.owner_token OR a.lease_expires_at!=j.lease_expires_at "
            "OR a.job_id!=j.id OR a.number!=j.attempt_count)"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM attempts a JOIN jobs j ON j.id=a.job_id "
            "WHERE a.state='running' AND j.state!='running'"
        ).fetchone()[0]
        == 0
    )
    # attempt bookkeeping matches job budget exactly, numbered 1..n
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM jobs j WHERE attempt_count !="
            " (SELECT COUNT(*) FROM attempts a WHERE a.job_id=j.id)"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM (SELECT job_id, MIN(number) AS lo, MAX(number) AS hi,"
            " COUNT(*) AS n FROM attempts GROUP BY job_id HAVING hi - lo + 1 != n)"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM jobs j JOIN attempts a ON a.job_id=j.id"
            " WHERE a.number > j.max_attempts"
        ).fetchone()[0]
        == 0
    )
    # terminal immutability evidence: terminal jobs own no lease and, when succeeded, a result
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE state IN ('succeeded','failed','canceled')"
            " AND (active_attempt_id IS NOT NULL OR lease_expires_at IS NOT NULL)"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE state='succeeded' AND result_json IS NULL"
        ).fetchone()[0]
        == 0
    )


def test_randomized_transition_sequences_preserve_invariants(db, clock, default_queue):
    seed_rng = random.Random(20260917)
    terminal_snapshots = {}
    for seed in range(25):
        # fresh queue content per seed inside the same DB
        for j in range(3):
            submit_job(
                db,
                clock=clock,
                handler="text_summary",
                payload={"text": f"s{seed}j{j}"},
                max_attempts=seed_rng.randint(1, 3),
                idempotency_key=f"prop-{seed}-{j}",
            )
        owned: dict[str, dict] = {}
        for _ in range(40):
            action = seed_rng.random()
            running = [
                r["id"] for r in db.execute("SELECT id FROM jobs WHERE state='running'").fetchall()
            ]
            if action < 0.30 or (running and action < 0.45):
                c = claim_job(
                    db,
                    clock=clock,
                    worker_id="prop",
                    queues=["default"],
                    handlers=["text_summary"],
                    lease_ms=seed_rng.choice([50, 500]),
                )
                if c is not None:
                    assert c["job_id"] not in owned  # one active owner per job
                    owned[c["job_id"]] = c
            elif action < 0.55 and running:
                job = seed_rng.choice(running)
                if job in owned:
                    # A lease may legally expire first: StaleOwner is a legal outcome.
                    with contextlib.suppress(StaleOwnerError):
                        complete_job(db, clock=clock, **_owner(owned[job]), result={"done": job})
                    del owned[job]
            elif action < 0.70 and running:
                job = seed_rng.choice(running)
                if job in owned:
                    with contextlib.suppress(StaleOwnerError):
                        fail_job(
                            db,
                            clock=clock,
                            rng=seed_rng,
                            **_owner(owned[job]),
                            error_code="E",
                            error_summary="prop",
                            timed_out=seed_rng.random() < 0.3,
                        )
                    del owned[job]
            elif action < 0.78 and running:
                job = seed_rng.choice(running)
                if job in owned:
                    with contextlib.suppress(StaleOwnerError):
                        heartbeat(db, clock=clock, **_owner(owned[job]), lease_ms=400)
            elif action < 0.84:
                cancelable = db.execute(
                    "SELECT id FROM jobs WHERE state IN ('queued','retry_wait') LIMIT 1"
                ).fetchone()
                if cancelable is not None:
                    cancel_job(db, clock=clock, job_id=cancelable["id"])
            elif action < 0.92:
                recover_expired_jobs(db, clock=clock, rng=seed_rng, batch_limit=10)
                for job_id in list(owned):
                    row = db.execute(
                        "SELECT state, owner_token FROM jobs WHERE id=?", (job_id,)
                    ).fetchone()
                    if row["state"] != "running" or row["owner_token"] is None:
                        del owned[job_id]
            else:
                clock.advance(seed_rng.randint(0, 700))
            _invariants(db)
            for row in db.execute(
                "SELECT * FROM jobs WHERE state IN ('succeeded','failed','canceled')"
            ):
                snapshot = tuple(row)
                assert terminal_snapshots.setdefault(row["id"], snapshot) == snapshot
    _invariants(db)


def test_backoff_delay_bounds_and_retry_deadline(db, clock, rng, default_queue):
    for n in range(1, 11):
        cap = min(60_000, 1_000 * 2 ** (n - 1))
        for _ in range(20):
            assert 0 <= backoff_delay_ms(n, rng) <= cap
    submit_job(db, clock=clock, handler="text_summary", payload={"text": "d"})
    assert (
        claim_job(
            db,
            clock=clock,
            worker_id="w",
            queues=["default"],
            handlers=["text_summary"],
            lease_ms=100,
        )
        is not None
    )
    clock.advance(100)
    outcome = recover_expired_jobs(db, clock=clock, rng=rng)[0]
    assert outcome["outcome"] == "retry_scheduled"
    assert db.execute("SELECT available_at FROM jobs").fetchone()[0] == outcome["retry_at"]


def test_real_clock_end_to_end(tmp_path):
    """Small end-to-end pass with the production wall clock (no injection)."""
    from walflow.domain.clock import SystemClock
    from walflow.storage.migrations import apply_migrations
    from walflow.storage.transactions import connect

    path = str(tmp_path / "wall.db")
    conn = connect(path)
    try:
        assert apply_migrations(conn) == [1, 2]
        from walflow.services.setup import ensure_queue

        ensure_queue(conn, clock=SystemClock(), name="default")
        clock = SystemClock()
        before = clock.now_ms()
        submit_job(conn, clock=clock, handler="text_summary", payload={"text": "real"})
        c = claim_job(
            conn,
            clock=clock,
            worker_id="wall",
            queues=["default"],
            handlers=["text_summary"],
            lease_ms=30_000,
        )
        assert c is not None and c["timeout_ms"] == 30_000
        assert before <= c["lease_expires_at"] <= clock.now_ms() + 30_000
        complete_job(conn, clock=clock, **_owner(c), result={"ok": True})
        row = conn.execute("SELECT state, finished_at FROM jobs").fetchone()
        assert row["state"] == "succeeded"
        assert row["finished_at"] >= before
    finally:
        conn.close()
