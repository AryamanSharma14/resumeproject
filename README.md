# Resume Projects: Relay (`relay-jobs`)

This repository contains **Relay** (`relay-jobs`), an inspectable, local-first background job processing system built with Python (FastAPI, Typer, SQLite WAL) and a bundled React/TypeScript operations dashboard.

Relay is engineered around **verifiable failure guarantees**: atomic state transitions, lease-fenced execution, watchdog timeouts, bounded child-process IPC, and tamper-resistant attempt histories.

---

## Repository Structure

```text
resumeproject/
  README.md                 # Workspace overview and quickstart
  AGENTS.md                 # Agent and engineering conventions
  relay/                    # Relay application package
    pyproject.toml          # Python package manifest (hatchling backend)
    uv.lock                 # Locked Python dependencies
    Dockerfile              # Multi-stage production container
    compose.yaml            # Compose spec (init, API, worker isolation)
    src/relay/              # Application source
      domain/               # Domain contracts, error types, handler registry
      storage/              # SQLite transactions and atomic migrations
      services/             # Submit, claim, complete, cancel, recover
      worker/               # Supervised child process runtime & bounded IPC
      api/                  # FastAPI control routes, security middleware, static SPA
      cli/                  # Typer CLI (init, serve, worker, db, jobs, doctor)
      static/               # Bundled production dashboard assets
    tests/                  # Automated verification suite (T01-T24 matrix)
    web/                    # Operations dashboard (React 19, TypeScript, Vite)
    scripts/                # Fullstack E2E, benchmarks, release builder
  docs/
    devlog/                 # Measured benchmarks and release verification logs
    relay/                  # Engineering specifications & ADRs
      implementation-plan.md # Architecture, schema, milestones M0-M6
      release-roadmap.md     # Release phases and acceptance gates
      design-system.md       # Dashboard design specification
      security.md            # Threat model, STRIDE, security acceptance criteria
      operations-runbook.md  # Runbook (systemd/Windows, backup/restore, pruning)
      open-source-operations.md # Open-source governance and policies
      adr/                   # Architecture Decision Records (0001-0004)
```

---

## Status & Verification

Relay has implemented and verified Milestones **M0 through M5** (Phases A–E):

- **Durable Core (M1)**: Atomic migrations, idempotent submission, atomic claims, fenced completion, lease recovery, and attempt budgets.
- **Supervised Worker (M2)**: Isolated child execution via `multiprocessing` spawn context, bounded pipe IPC, watchdog deadlines, and graceful drain.
- **HTTP API & CLI (M3)**: Authenticated loopback API, Typer CLI (`init`, `serve`, `worker`, `db`, `jobs`, `queues`, `doctor`), Prometheus metrics (`/metrics`), and health endpoints.
- **Operations Dashboard (M4)**: React 19 + TypeScript SPA with job timeline inspection, queue controls, and accessible interaction flows.
- **Production Packaging (M5)**: Zero-Node static SPA serving with deep-link fallback, deterministic wheel build script (`build_release.py`), and full-stack E2E automation.

### Test Matrix

All test suites pass cleanly:
```powershell
cd relay
.\.venv\Scripts\python.exe -m pytest                  # 94 Python tests pass
npm --prefix web test                                # 11 Vitest dashboard tests pass
.\.venv\Scripts\python.exe scripts/e2e_fullstack.py   # Live full-stack E2E pass
```

---

## Quickstart

### 1. Initialize Database and Credentials

```powershell
cd relay
.\.venv\Scripts\relay.exe init
```
This initializes the local data directory, creates a cryptographically secure 256-bit bearer token with restricted OS permissions, runs migrations, and configures the default queue.

### 2. Start the Loopback API Server & Dashboard

```powershell
.\.venv\Scripts\relay.exe serve --port 8000
```
Visit `http://127.0.0.1:8000/` in your browser. Enter your installation token (found in the local data directory) to authenticate into the dashboard.

### 3. Start a Worker Supervisor

In a separate terminal:
```powershell
.\.venv\Scripts\relay.exe worker start --concurrency 2
```

### 4. Submit Jobs via CLI

```powershell
# Submit a text summary task
.\.venv\Scripts\relay.exe jobs submit text_summary --payload '{"text": "Relay background jobs"}'

# Submit with idempotency key
.\.venv\Scripts\relay.exe jobs submit text_summary --payload '{"text": "Sample"}' --idempotency-key "req-001"

# Check system health
.\.venv\Scripts\relay.exe doctor
```

---

## Core Guarantees & Boundaries

1. **At-Least-Once Execution**: Fenced lease expiration guarantees that stale workers cannot commit results or overwrite active ownership. Handlers must be idempotent or side-effect safe.
2. **Single-Host Loopback Boundary**: By default, Relay binds strictly to `127.0.0.1` and enforces strict `Host` and `Origin` headers to protect against DNS rebinding and cross-site request forgery.
3. **No External Broker Required**: Runs on SQLite WAL mode with zero Redis, RabbitMQ, or Docker daemon dependencies for standard local operation.

