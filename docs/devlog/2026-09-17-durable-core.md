# Durable core verification — 2026-09-17

## Verified locally (Windows, CPython 3.13)

- Full existing suite: 47 passed, pytest exit 0.
- Scoped core/CLI Ruff check: exit 0; format check: exit 0.
- Strict mypy over domain/storage/services/CLI: 20 files, exit 0.
- Lockfile check: exit 0.
- Fresh non-editable package installation into a temporary virtual environment: exit 0.
- Installed `relay migrate --db <temporary-file>`: exit 0, schema version 1.
- Repeat migration: exit 0, no migrations applied.
- Verified jobs, attempts, events, queues, workers, idempotency and migration tables.
- Temporary database and environment cleanup: passed with explicit connection close.

Tests cover T01–T11, paused queues, version mismatch, real independent-connection
races, injected transition failures, migration ledger failure rollback, and
randomized state invariants. These are local results, not Linux CI evidence.

## Boundary

This is a verified core milestone, not a completed product or release. API,
worker supervision, full CLI, dashboard, distribution and public release gates
remain separate. The initial migration-only CLI is intentionally limited to
an implemented command; no placeholder commands are advertised.

The name and Apache-2.0 remain proposed in ADRs pending explicit approval before
public distribution. The repository stays private. No public package was uploaded.

## Next

Integrate and verify supervised runtime, API and CLI, then dashboard and packaged
installation. Run the full suite after integration and cross-platform CI before
claiming the corresponding roadmap gates complete.
