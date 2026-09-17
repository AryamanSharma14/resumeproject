# Contributing to Relay

Thanks for looking at Relay. This is a local-first background-job system; the
design contract lives in `docs/` at the repository root (implementation plan,
release roadmap, security spec, ADRs).

## Development setup

```text
uv sync --locked
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
```

All five must pass for every change. CI runs the same commands on Linux and
Windows; do not merge red.

## Ground rules

- Every behavior change ships with a test that fails without it.
- Scenario IDs (T01-T24 in the implementation plan) are the acceptance
  contract: name test functions after the scenario they verify.
- No placeholder or stub modules; a feature exists only when implemented
  and tested.
- Parameterized SQL only; no network calls or handler execution inside
  database transactions; UTC integer milliseconds everywhere internal.
- Scope changes require an ADR under `docs/adr/`.

## Submitting changes

1. Open an issue describing the behavior change before large refactors.
2. Keep commits atomic with imperative messages ("Add X", "Fix Y").
3. Sign off your commits (`git commit -s`) - the DCO applies (license ADR).
4. CI must be green; maintainers review on a best-effort cadence.

## Reporting security issues

Do not open public issues for security problems. See SECURITY.md.
