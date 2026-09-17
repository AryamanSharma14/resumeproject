# Relay (relay-jobs)

Local-first durable background job system: SQLite queue with fenced leases,
bounded retries, and inspectable attempt history. At-least-once execution —
not exactly-once side effects.

Status: v0.1.0 development. Design contract lives in `../docs/relay/implementation-plan.md`.

## Development

```text
uv sync            # create venv + install locked deps
uv run pytest      # test suite (matrix T01-T11 for the durable core)
uv run ruff check .
uv run mypy
```
