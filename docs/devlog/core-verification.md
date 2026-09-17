# Durable core verification and bounded benchmark

Date: 2026-09-17. Development evidence, not a production capacity claim.

## Verified scope

The core checkpoint passed **46 core tests**; with the existing discovery smoke test,
**47 total tests passed in 2.11 s**. Scoped strict mypy checked 19 core source files;
Ruff lint and format checks passed (27 owned Python files). Exit codes were all zero.
After adding two release regressions, **48 core + release tests passed in 3.54 s**
(final rerun). Strict mypy, Ruff lint and format checks passed for the three new
benchmark/release Python files; all four command exit codes were zero.
API, runtime and web are developed separately and are not covered by this checkpoint.

Commands from `relay/` (PowerShell):

```powershell
$tests = @(Get-ChildItem tests/test_core*.py,tests/test_release*.py | ForEach-Object FullName)
.\.venv\Scripts\python.exe -m pytest @tests
.\.venv\Scripts\python.exe -m mypy --strict src/relay/domain src/relay/storage src/relay/services
.\.venv\Scripts\ruff.exe check src/relay/domain src/relay/storage src/relay/services
.\.venv\Scripts\python.exe -m pytest tests/test_release_cli.py
```

## Scenario map

| Scenario | Executed evidence | Boundary / limitation |
|---|---|---|
| T01 fresh migration, restart, newer schema | `test_core_migrations.py`; release CLI bootstrap/restart/999 refusal | SQL and checksum ledger rollback tested, including injected ledger failure in `test_core_atomicity.py`; no production upgrade corpus |
| T02 concurrent same-key/body | `test_t02_t03_concurrent_duplicate_and_conflict` | Independent WAL connections, two submitters; one ID and one replay |
| T03 same-key/different body | Same test + namespace test | Core raises typed conflict; HTTP 409 belongs to API tests |
| T04 eight claim contenders | `test_t04_eight_claim_contenders` | Four jobs/eight contenders, unique jobs/tokens and four running attempts |
| T05 transition rollback | `test_t05_real_service_event_failure_rolls_back` (submit, claim, complete, fail, recover) | Trigger-injected error restores job/attempt/event/idempotency snapshots; not OS power-loss proof |
| T06 claim/cancel race | `test_t06_actual_claim_cancel_race` | 20 iterations, legal outcomes asserted; running cancellation rejected |
| T07 double recovery | `test_t07_actual_double_recovery`; lifecycle test | One lost event and one retry transition; fresh-attempt interleaving also tested |
| T08 stale heartbeat/completion | `test_t08_t09_heartbeat_and_completion_fenced` | Old token rejected after recovery and new claim |
| T09 expiry before recovery | Same test and `test_owner_recovery_races` | Equality is expired; completion rejected; heartbeat cannot resurrect |
| T10 retry deadline | Timeout lifecycle and backoff/property tests | Before deadline unclaimable, equality claimable; persisted deadline checked |
| T11 exhausted attempts | `test_t07_t11_recovery_exhaustion`; fresh-preselection test | Terminal failed/finished_at, no further claims; loss counts toward budget |
| T18 pause | `test_t18_paused_queue_blocks_new_claims_only`, eight blocked contenders | Existing claim can finish; paused queue burns no attempts |
| T19 unsupported version | Validation/lifecycle and eight blocked contenders | Stored version 999 stays queued; no attempts/events; advertised override cannot bypass registry |

Concurrency helpers capture `BaseException` in each thread and re-raise a group in
the test thread. A sentinel test verifies that propagation. Tests use independent
file-backed connections, bounded barriers/joins, and explicit connection cleanup.
Randomized stdlib `random.Random(20260917)` runs 1,000 transitions across 75 submissions,
checking active job/attempt matching, budgets, ownership, numbering and terminal-row
snapshot immutability. This is deterministic property-style testing, not exhaustive
model checking. Fake time avoids sleep-based unit assertions.

## Measured benchmark

Reproduce from the installed project environment:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark.py --jobs 1000 --workers 1 --seed 20260917
.\.venv\Scripts\python.exe scripts/benchmark.py --jobs 1000 --workers 4 --seed 20260917
```

Environment: CPython **3.13.5**, MSC v.1943 64-bit AMD64; SQLite **3.49.1**;
Windows **11 / 10.0.26200-SP0**; CPU reported as AMD64 Family 25 Model 116 Stepping 1,
AuthenticAMD; **12 logical CPUs**. Storage hardware/filesystem and background load
were not measured. Each run creates a fresh temporary database under `relay/` and
removes it after explicitly closing all connections.

Configuration: WAL, `synchronous=2` (**FULL**), foreign keys ON, busy timeout 5,000 ms.
1,000 `text_summary` v1 jobs, each with 16 seeded words, unique submission key,
one maximum attempt. Submit all jobs serially, then drain with independent thread
connections. Actual handler runs are included in drain/total time. There is no API,
spawn supervisor, child IPC or UI workload. Defaults bounded to 10,000 jobs, 8 threads
and 300 seconds maximum requested budget; deadline checks occur between operations,
so a SQLite blocking call can overrun the deadline. No throughput JSON on failure.

| Threads | Submit seconds | Submit jobs/s | Drain seconds | Drain jobs/s | Total seconds | Total jobs/s |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 1.011692 | 988.44 | 2.351525 | 425.26 | 3.363216 | 297.33 |
| 4 | 1.044065 | 957.79 | 3.529343 | 283.34 | 4.573408 | 218.66 |

| Threads / operation | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|
| 1 / submit | 0.9456 | 1.2832 | 2.7998 |
| 1 / claim | 1.2131 | 1.6607 | 4.4838 |
| 1 / complete | 0.9499 | 1.2812 | 3.5801 |
| 4 / submit | 0.9645 | 1.4232 | 2.7525 |
| 4 / claim | 1.3103 | 4.6779 | 10.2630 |
| 4 / complete | 1.0041 | 3.9133 | 6.6025 |

Percentiles are nearest-rank over 1,000 successful operations. The final empty poll
is included in drain time but excluded from claim latency samples. Each run verified
exactly 1,000 succeeded jobs, 1,000 attempts, 3,000 events, SQLite integrity `ok` and
zero FK violations; both exited 0. DB/WAL/SHM bytes before connection close:
1 thread = 1,691,648 / 4,185,952 / 32,768; 4 threads = 1,712,128 / 4,358,992 / 32,768.

These are **one run per setting**, no warmup, no confidence intervals and no retained
history background load. Four threads were slower here; this is compatible with
SQLite's single-writer design, not evidence of a general scaling curve. Seeded input
is reproducible; UUIDs, timing, DB layout and scheduling are not. Do not market these
as worker throughput, sustained capacity, comparative benchmarks or availability.

## T24 packaging gate and CLI regression

`test_release_cli.py` launches actual Python CLI subprocesses from outside the checkout,
checks fresh migration, restart idempotence and unknown-version refusal. Parent-side
SQLite connections use `contextlib.closing` (a SQLite connection context manager alone
does not close a handle). Database deletion is also exercised after explicit closure.
A second test executes the real benchmark at 12 jobs / 2 threads, verifies measurements
and invariants, then rejects an oversized job count.

The UI is still being implemented at this checkpoint. T24 is **not yet passed**.
`test_release_wheel.py` is an explicit standalone gate, with no fake skip flag:

```powershell
.\.venv\Scripts\python.exe tests/test_release_wheel.py --wheel dist/relay_jobs-0.1.0-py3-none-any.whl
```

It requires an actual wheel containing `relay/static/index.html`, local JS/CSS assets,
SQL resources and the `relay` console entry point. Missing assets fail. It creates a
fresh venv, installs the wheel plus declared dependencies, runs CLI help, checks imports
come from that venv, exercises migrations/restart, serves the index/assets/deep link,
and ensures unknown API routes remain 404. It runs outside the checkout without
PYTHONPATH; dependency installation may require network. No Node runtime is used.
Lead must build the UI and wheel before running this gate. The attempted
`python -m build --wheel` could not run because `build` is absent from this environment;
no manifest change or fake wheel was made to claim success.

## Read-only follow-up findings reported to lead

Core is frozen under this task; these concerns were reported rather than edited:

- `connect()` closes on non-WAL result but not on every PRAGMA exception; setup failures
  can leak a connection until GC. Error mapping must cover raw SQLite operational errors.
- Retry behavior differs: submit/complete/fail/heartbeat use `write_tx`; claim/cancel/
  setup/recovery/migration currently use only `immediate_transaction`. All have the
  SQLite busy timeout, but only the former get additional retries and typed busy error.
- Five 5-second SQLite busy waits plus exponential sleeps can total approximately
  26.55 seconds, not the stale approximately-0.5-second comment. `run_write` itself
  does not start a transaction; callers should use `write_tx` for that guarantee.
- Finite `batch_statistics` inputs may overflow `sum` (for example two `1e308` values),
  yielding non-finite output rejected at completion. This needs a numerical policy.
- DB constraints enforce unique running attempts but not all cross-table invariants;
  job budget/ownership equivalence is enforced by services and tests, not arbitrary SQL.

T12–T17 process/API availability, actual OS crash/power loss, disks/network filesystems,
Windows/Linux process cleanup, retention/backup lifecycle and built-UI release install
remain separate gates. At-least-once is not exactly-once external side effects.

