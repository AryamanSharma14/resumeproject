# Relay — Detailed Implementation Plan

Date: 2026-09-17
Status: researched design proposal, not an implemented or benchmarked application.
Owner: Aryaman Sharma. Resume basis: C:\Users\aryam\Downloads\Resume july 2026.pdf.
This document supersedes earlier informal Relay suggestions where they conflict.

## 1. Executive decision

Build a local-first background-job processing system consisting of a durable SQLite queue, a separate Python worker supervisor, a FastAPI control API, a Typer CLI, and a React operations dashboard. Its main demonstration is failure recovery that people can inspect: submit a job, observe attempts and retries, stop a worker, recover an expired lease, and reject a stale completion.

Positioning: an understandable, inspectable job system for a single developer machine or single-host service, with unusually clear execution history. This is a backend/infrastructure portfolio project with a usable product surface, not a claim to replace Celery, Temporal, or hosted workflow platforms.

Recommended first release: one host, one installation, a small set of trusted built-in handlers, one API process and one or more worker supervisors. No Redis, Docker, paid API or cloud account required for the normal local demo. A desktop web application is the primary UI; no native mobile app, Electron wrapper, or separate marketing website in the first release.

Core guarantee: at-least-once execution under documented recovery assumptions, with bounded automatic attempts. Submission idempotency prevents duplicate job records for the same request key; it does NOT make external side effects exactly-once. Leases and attempt tokens prevent stale owners from overwriting queue state; they cannot undo an email, charge, network call or arbitrary file write.

Build in vertical milestones. A narrow MVP is feasible, but a polished queue engine, cross-platform process supervision, dashboard and complete failure testing should not be sold as a guaranteed flawless one-shot implementation.

## 2. Product requirements and scope

### 2.1 Primary users and jobs to be done
- Developer: enqueue work from a terminal or HTTP client without installing a broker.
- Operator: find why a job is waiting, failing, retrying or no longer owned by a live worker.
- Reviewer/interviewer: understand the failure model and reproduce correctness checks locally.

The three essential journeys are submit-to-success, failure-to-retry, and worker-loss-to-recovery. Every feature must improve one of these journeys or the safety of operating them.

### 2.2 Release boundaries
MVP includes: validated submission; named queues; bounded priorities; delayed availability; idempotency keys; atomic claims; attempt history; expiring leases; worker heartbeats; capped retries with jitter; watchdog timeouts; pending-only cancellation; manual rerun with lineage; job/worker queries; a useful dashboard; structured logs; basic metrics; documentation and automated tests.

Defer: cron schedules and DST policy; DAGs and dependent jobs; workflows/checkpointed function execution; multi-tenant users/RBAC; multi-host SQLite; distributed/global concurrency quotas; arbitrary user code submission; shell job handlers; webhook targets; plugin marketplaces; running-job cancellation; bulk destructive operations; general-purpose sandboxing; SSO; billing; Kubernetes; Redis; automatic scaling; MCP interface; AI diagnosis; hosted public demo with write access.

V1.1 candidates, only after correctness gates: controlled developer handler registration, retention automation, richer charts, read-only event streaming, Python SDK convenience layer, PostgreSQL adapter, protected remote deployment.

### 2.3 Concrete demonstration handlers
Use pre-registered, deterministic, bounded handlers with Pydantic input/output schemas:
- text_summary: count characters, words and lines in a bounded string; no LLM or network.
- batch_statistics: calculate count/min/max/mean for a bounded numeric list; reject non-finite numbers.
- demo_flaky: fail the first N attempts, then return success; attempt number is explicit execution context. Clearly labelled demonstration-only.
- demo_delay: wait a bounded interval in small increments so watchdog behavior is demonstrable.
A separate test-only hanging handler exercises timeout cleanup; it is never exposed by the normal registry.

First prove the infrastructure with pure handlers. Developer-supplied handlers later run trusted local code, not untrusted sandboxed code. Financial/email examples belong in explanatory docs, not runnable side-effecting demos.

### 2.4 Success criteria
- A clean supported machine follows documented steps without an external service account.
- Completed submission remains queryable after API restart.
- Duplicate concurrent submissions with identical keys resolve to one job.
- Two supervisors cannot create two current ownership records for the same job.
- A stale attempt cannot commit a result after ownership expires or changes.
- Under a running recovery loop and writable DB, expired jobs transition according to their attempt budget.
- A first-time user can find the latest failure and its next scheduled attempt without reading terminal logs.
- Test results and measured limits are published honestly; no invented throughput or availability figures.

## 3. Research conclusions and alternatives

The job-queue category is mature. Existing tools include Celery, RQ, Huey, Taskiq and Procrastinate. Huey's README explicitly lists SQLite storage, retries, priorities and multiple execution models. Therefore, SQLite-based queuing is not a novelty claim.

| Alternative | Best reason to use it | Why not the Relay engine |
|---|---|---|
| Celery + Flower | Established task ecosystem and monitoring | Broker/operational setup; a wrapper demonstrates less ownership of queue correctness |
| RQ | Straightforward Python queue ecosystem | Existing queue semantics and external broker; would make this primarily a UI wrapper |
| Huey | Lightweight queue, including SQLite support | Excellent practical alternative; Relay's educational value is explicitly implementing and exposing leases/attempts |
| Taskiq | Async task ecosystem | A different runtime abstraction rather than a reason to grow Relay's initial scope |
| Procrastinate | PostgreSQL-based durable task processing | Strong practical choice when PostgreSQL already exists; adds a service to the zero-broker local demo |
| Trigger.dev / Inngest | Rich execution observability and workflow UX | Design references, not feature-parity targets |

If the goal changes from portfolio learning to urgent production business tasks, reconsider adopting an established queue rather than implementing one. Relay should win on setup clarity, inspectability and documentation, not unsupported claims of being faster or safer.

Verified source takeaways: FastAPI documents BackgroundTasks as in-process post-response work and points to larger task systems for multi-process workloads; it is not the durable engine here. SQLite WAL permits reader/writer overlap but only one writer. Celery documents repeat execution and idempotency concerns around late acknowledgments. Trigger.dev separates runs from attempts. Inngest exposes payload, execution timeline and retry detail. W3C recommends native HTML tables when appropriate. These sources inform the design; none validate Relay's future implementation.

## 4. Architecture and ownership

```text
 Browser dashboard ---- same-origin HTTP ---- FastAPI control service
 Typer CLI ------------ authenticated HTTP ---^       |
                                                     | short transactions
                                                     v
                                              local SQLite DB
                                                     ^
                                                     | short transactions
                                         worker supervisor process(es)
                                               | spawn / bounded IPC
                                               v
                                       trusted job child processes

 API maintenance loop ---- bounded expired-lease recovery ---- DB
 Worker maintenance ------ same idempotent recovery routine --- DB
```

API, workers and migration command share a queue domain/storage package. Children do not get queue DB connections or commit queue state. CLI job operations use HTTP so validation, authentication and error semantics stay consistent. Lifecycle commands (initialize DB, start server, start worker, backup) execute locally and say so explicitly.

One API process initially, with an explicitly supervised maintenance loop. Worker supervisors also perform bounded recovery so an API outage does not prevent existing work from completing or recovering. Concurrent recovery is safe because the database serializes conditional transitions. If all API/worker processes are stopped, recovery pauses until one resumes; the DB is durable storage, not a running scheduler.

Use sync FastAPI endpoints for sync SQLite operations, keeping blocking DB calls out of async event-loop code. Async lifespan maintenance delegates blocking transactions to a thread, with bounded cadence, shutdown signaling and visible error reporting. Never share a sqlite3 connection concurrently across threads. Keep the domain/state machine independent of FastAPI and Typer.

### 4.1 Proposed repository layout
Proposed root: C:\Users\aryam\Desktop\yee\coding\relay . Do not create or overwrite it until implementation begins and existing contents are inspected.

Relative layout below is a specification, not files created by this task:
- pyproject.toml, uv.lock, README.md, LICENSE, SECURITY.md
- src/relay/domain/: states, policies, typed domain errors, clock interfaces
- src/relay/storage/: connection factory, transaction helper, repositories, numbered SQL migrations
- src/relay/services/: submit, claim, complete, fail, recover, cancel, rerun
- src/relay/api/: app factory, dependencies, schemas, routes, authentication
- src/relay/worker/: supervisor, child runner, registry, watchdog, bounded IPC
- src/relay/cli/: lifecycle and HTTP job commands
- src/relay/observability/: logs, metrics, request IDs
- src/relay/builtin_handlers/: pure bounded demo tasks
- tests/: unit, integration, concurrency, process, contract, fixtures
- web/: React application, package.json, package-lock.json, component and browser tests
- docs/: architecture decisions, state machine, failure model, benchmark method
- scripts/: portable developer/test helpers, not shell-only setup assumptions

Architecture rule: UI/CLI depend on API contracts; API depends on services; services depend on storage interfaces and domain policies. Do not build generic repositories or plugin frameworks before a concrete use case needs them.

## 5. Libraries, versions and coding practices

No Relay repository exists in this task, so the following is a PROPOSED greenfield stack, not a claim these dependencies are already installed or used. FastAPI, Typer, Python and React are confirmed by the resume. Confirm actual project conventions at implementation before adopting additions.

| Area | Decision | Reason / limit |
|---|---|---|
| Python | Start development on installed CPython 3.13; proposed CI 3.12 and 3.13 | Avoid accidentally using MSYS2 Python; validate dependencies before locking |
| API | FastAPI, Uvicorn | Familiar stack, validation and generated OpenAPI; not a job executor |
| Validation | Pydantic v2; pydantic-settings if configuration merits it | Explicit request, result and settings validation; reject extra fields where appropriate |
| CLI | Typer, HTTPX; Rich for human output | Familiar command UX; timeouts, structured failures and JSON automation |
| Storage | Standard-library sqlite3, explicit SQL | Small schema; visible transaction semantics; no ORM magic in claims |
| Migrations | Numbered SQL files plus schema_migrations table | Single-engine scope; checksums and tests; explicit migration command |
| Processes | Standard-library multiprocessing with explicit spawn context | Cross-platform process startup; bounded owned child processes |
| Packaging | uv, pyproject.toml, committed uv.lock | Reproducible dependency resolution; CI uses locked sync |
| Backend quality | pytest, pytest-cov, Hypothesis, Ruff, mypy | Behavior tests, property tests, formatting/lint and typed boundaries |
| Metrics | prometheus-client | Standard exposition; bounded labels and carefully defined counters |
| Frontend | React + TypeScript + Vite | Local operations SPA needs no SSR; TS is a new deliberate learning choice |
| Routing | React Router | Durable list/detail routes and URL filter state |
| Server data | TanStack Query | Polling, invalidation, deduplication and stale/error state |
| UI primitives | Radix for dialogs/tabs/menus; native HTML controls otherwise | Accessible interaction foundations without a complete visual-template dependency |
| Styling | CSS Modules + shared CSS custom properties | Small explicit visual system; no styling runtime; Tailwind optional only if existing conventions favor it |
| Tables | Native semantic table initially | 50-row pages do not require a headless table framework or virtualization |
| Icons | lucide-react, selectively imported | Consistent functional icon set; accessible labels still required |
| Frontend tests | Vitest, React Testing Library, Playwright; axe-core integration | Unit/interaction and real-browser behavior; manual accessibility checks remain necessary |
| Frontend packaging | npm with committed package-lock.json | Already available; avoid introducing a second JS package manager |

Do NOT add Celery/RQ underneath a custom lease engine, Redis as a speculative optimization, Next.js just for fashion, Redux for server-state duplication, WebSockets for one-way status updates, Monaco for read-only JSON, or a chart library before an actual chart is needed.

SQLAlchemy/Alembic are reasonable alternatives if PostgreSQL becomes a committed near-term requirement. They are not required for this explicit single-engine MVP. SQLAlchemy's SQLite docs warn about driver transaction-mode differences: whichever layer is used, own transaction behavior deliberately. Do not mix autocommit modes, implicit transactions and BEGIN IMMEDIATE blindly.

Version policy: select compatible stable releases at implementation time, inspect declared Python/Node requirements and licenses, then lock exact resolution. Do not label an untested collection of newest versions 'best'. Observed environment: Node v24.20.0, Git 2.50.1.windows.1, CPython 3.13 and 3.10, and uv are available. This does not prove all chosen packages are compatible. GitHub metadata reported permissive licenses for several core selections; full direct/transitive license audit remains a release task.

Coding rules: typed public boundaries; small explicit services; parameterized SQL; no blanket exception swallowing; domain errors mapped centrally; UTC timestamps; injectable clock/randomness; named constants and configuration limits; no network calls inside DB transactions; bounded loops; structured redacted logging; no secrets in examples; no unfinished TODOs in the advertised feature path. Comments explain invariants and tradeoffs, not restate code.
## 6. Database schema and transaction design

### 6.1 Connection and durability
Use platform-local app data; Windows default: C:\Users\aryam\AppData\Local\Relay . Never default to OneDrive, a network share or synced storage. WAL is single-host, not distributed shared storage. Use sqlite3 explicit transaction control (isolation_level=None), foreign_keys=ON, verified WAL mode, synchronous=FULL initially, and bounded busy_timeout. Document performance/durability tradeoffs. Short writes start BEGIN IMMEDIATE; every path commits or rolls back. No handler, network call or streamed response holds a transaction open. No connection is concurrently shared across threads.

Retry whole transactions only for retryable lock contention, with bounded jitter and a total deadline. SQLITE_BUSY can still occur; return explicit temporary failure on exhaustion. Disk-full, read-only and corruption errors are not ordinary contention. Do not promise zero database lock errors.

### 6.2 Schema
IDs: random application-generated UUIDs. Internal time: UTC integer milliseconds; API: RFC3339 UTC. Use CHECK constraints on states and numeric ranges, parameterized SQL, and bounded validated JSON.

| Table | Columns / constraints |
|---|---|
| schema_migrations | version PK, checksum, applied_at |
| queues | name PK, paused, created_at; bounded configured queue names |
| jobs | id PK, handler, handler_version, queue FK, payload_json, state, priority, created_at, updated_at, available_at, started_at, finished_at, attempt_count, max_attempts, timeout_ms, active_attempt_id, owner_token, lease_expires_at, result_json, last_error_code, last_error_summary, rerun_of nullable FK jobs |
| attempts | id PK, job_id FK, number, owner_token, worker_id, state, started_at, finished_at, lease_expires_at, error_code, error_summary, bounded_result_json; UNIQUE(job_id,number), UNIQUE(owner_token) |
| job_events | seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id FK, attempt_id nullable FK, kind, created_at, bounded_detail_json |
| workers | id PK per supervisor boot, hostname, process_id, started_at, heartbeat_at, state, concurrency, queues_json, handler_versions_json; PID alone is not identity |
| idempotency_records | scope, key, request_hash, job_id FK, created_at; UNIQUE(scope,key) |

Nullable lifecycle fields are populated only when meaningful. Job, attempt and event changes commit atomically. Enforce at most one active attempt via a partial UNIQUE index on attempts(job_id) WHERE state='running'. Index jobs(state,available_at,priority,created_at,id), jobs(queue,state,available_at), jobs(state,lease_expires_at), jobs(created_at,id), attempts(job_id,number), job_events(job_id,seq), workers(heartbeat_at). Inspect query plans on real seeded data rather than assume this index list is optimal.

### 6.3 State machine
Persist job states: queued, running, retry_wait, succeeded, failed, canceled. Future queued jobs display as Scheduled. Lease-expired running jobs display Awaiting recovery until a maintenance transaction changes state; stored running does NOT prove a live process exists.

- submit -> queued
- due queued/retry_wait -> running
- valid running completion -> succeeded
- retryable running failure/loss/timeout with budget -> retry_wait
- permanent failure or exhausted budget -> failed
- conditional queued/retry_wait cancellation -> canceled
- terminal states are immutable; manual rerun creates a new job

Attempt states: running, succeeded, failed, timed_out, lost. Attempt failure is not necessarily job failure. State detail uses reason codes, not an ever-growing collection of loosely defined states.

### 6.4 Submission idempotency
CLI and dashboard generate a bounded key per user submission and reuse it after ambiguous HTTP failures. API submissions without a key are explicitly non-idempotent. Scope keys by operation and queue; hash canonical validated handler/version, payload, schedule, priority and retry policy. Same key/same request returns the original job; same key/different request is 409. Resolve insertion under a write transaction and unique constraint, not a check-then-insert race. Retain keys with their job in v1; explicitly pruning a job ends this protection. Rerun has its own operation scope including original job ID.

### 6.5 Atomic claim
Inside BEGIN IMMEDIATE, select a due queued/retry_wait job in a non-paused queue compatible with the worker handler/version registry. Order priority DESC, available_at ASC, created_at ASC, id ASC. This is FIFO only within the stated constraints; low priorities may starve under continuous high-priority load.

Conditional update verifies eligibility, increments attempt_count and assigns fresh attempt ID/token and expiry. Insert attempt and claimed event only when update rowcount is one, then commit. Claim only when a worker slot is free. No prefetch. max_attempts includes initial execution and every claim lost before/after child startup. Attempt numbering is assigned in the transaction, never via MAX outside it.

### 6.6 Lease fencing, completion and recovery
Every heartbeat and completion checks job state running, matching active attempt/token and lease_expires_at > now. A stale completion is rejected and recorded in process logs; it never changes the recovered attempt or the current job. Event insertion is conditional on a successful transition. Checks occur inside the write transaction, not before acquiring the write lock.

Recovery selects a bounded batch of expired running jobs and conditionally transitions each using its current token/expiry. It closes the attempt as lost, then fails the job or schedules retry according to budget, in the same transaction. Two recoverers must produce exactly one transition/event. Owner identity is an integrity guard, not external-service fencing. Overlapping old/new execution remains possible after process stalls or lease loss.

Proposed starting defaults, to be validated: heartbeat every 5 seconds, lease 30 seconds, recovery every 2 seconds, claim polling 250 ms with idle backoff capped at 2 seconds, concurrency 2 per supervisor, maximum configured concurrency 8. Recovery latency is approximately lease duration plus maintenance delay and DB contention, not an unconditional SLA. Use wall clock for persisted deadlines and monotonic time for local durations/watchdogs; detect/report major wall-clock changes. Inject clocks in tests.

### 6.7 Retries, cancellation and reruns
Default max_attempts=3, configurable 1..10. Exponential cap after attempt n: min(60s, 1s * 2^(n-1)); sample full jitter uniformly from zero to cap. Persist sampled available_at once; do not resample when merely reading. Tests inject randomness. Explicit RetryableJobError retries; PermanentJobError does not. Unexpected handler exceptions fail permanently by default; worker loss/timeouts use bounded retry policy. Never retry forever.

Pending cancellation is an atomic conditional update. Repeated cancellation of canceled job returns its state; running or another final state returns 409 with explanation. API/UI never imply a running process was stopped. Running-job cancellation is deferred.

Rerun is permitted for failed/canceled jobs in v1 and creates a new ID with rerun_of lineage and a fresh attempt budget. Original history is unchanged. Warn that re-execution may repeat side effects. Network retries of the rerun request reuse a key to avoid multiple clones.

### 6.8 Migration, backup, retention
Explicit migrate command before starting incompatible binaries; checksum numbered migrations, test fresh and upgrade paths, refuse newer unknown schemas. API readiness fails on incompatibility rather than silently migrating under live workers.

Use SQLite backup API, not copying only the main DB while WAL is active. Before upgrade: stop writers, back up, migrate, validate, restart. V1 retention is explicit dry-run prune, only terminal jobs older than a chosen cutoff, bounded batches, with lineage/idempotency handling documented; no surprise background deletion. Monitor DB/WAL sizes and long read transactions. Results/payloads proposed cap 64 KiB each, error text 8 KiB, retained logs 256 KiB per attempt, event details 8 KiB. These are configurable validated limits, not current measurements.

## 7. Worker runtime and process lifecycle

A supervisor owns job lifecycle and SQLite writes. Each slot owns one child created through an explicit spawn context. Child entrypoints are importable top-level functions; protect executable entry with the standard main guard. Do not rely on fork defaults or inherit DB connections. Cross-platform lifecycle tests are required on Windows and Linux.

Child receives bounded validated payload, handler ID/version and execution context (job ID, attempt number, deadlines). Only pre-registered trusted handlers are executable. No API-supplied dotted imports, pickle files, eval or shell command strings. A spawn transport's internal trusted-process serialization is not an accepted remote code format. Prefer bounded JSON protocol messages over internal byte pipes for job/result messages.

Supervisor drains output without blocking heartbeats, checks child liveness, applies a monotonic runtime watchdog and stops claiming at capacity. Structured job logging is explicit and capped; do not promise arbitrary stdout capture until its pipe-drain behavior is tested. Reject oversized results, malformed child messages and unknown handlers as defined failures.

A healthy supervisor must NOT renew a hung job forever. Default handler timeout 30s, configurable within a documented bounded range. On timeout: stop child, join with deadline, escalate termination if needed, then conditionally record timed_out and retry/fail. Terminating a child with active IPC can damage that channel: dedicate and dispose channels per attempt; do not reuse a potentially corrupted shared queue.

Graceful stop: mark draining, stop new claims, keep leases alive for in-flight children, wait a bounded grace period, terminate remaining owned children, record failures only if still owner, close resources. Abrupt supervisor death may leave children temporarily orphaned. Child wrapper should monitor parent/IPC liveness for cooperative built-ins. Arbitrary native-code hangs and descendant process-tree cleanup are outside this first release's guarantee. Built-ins create no descendants or external side effects. Strong Windows Job Object / OS containment support is a separate milestone, not a marketing claim.

If DB becomes unavailable: stop claiming; preserve bounded child results temporarily; never emit success until the fenced commit succeeds. Stop/abandon owned children when ownership cannot safely be maintained. On restart, expired attempts are recovered; do not resurrect old tokens. If an external effect occurred before a lost completion, duplicate effects are possible: explain this prominently.

## 8. API and CLI contract

### 8.1 HTTP endpoints
| Method/path | Contract |
|---|---|
| POST /api/v1/jobs | Validate registered handler and policy; create (201), replay same key (200), mismatch (409), invalid input (422), too large (413) |
| GET /api/v1/jobs | Cursor pagination, filters state/queue/handler/time; default 50, maximum 100; deterministic created_at/id ordering |
| GET /api/v1/jobs/{id} | State, policy, result/error summary, lease/retry details; no ownership secrets |
| GET /api/v1/jobs/{id}/attempts | Ordered attempt history, paginated when needed |
| GET /api/v1/jobs/{id}/events | seq cursor, bounded limit; durable lifecycle timeline |
| POST /api/v1/jobs/{id}/cancel | Pending-only atomic cancellation; conflict for running |
| POST /api/v1/jobs/{id}/rerun | New linked job; request-idempotent operation |
| GET /api/v1/workers | Heartbeat age, availability, capacity, queue/handler compatibility |
| GET /api/v1/queues | Queue status, due depth and oldest due age |
| POST /api/v1/queues/{name}/pause or resume | Pause new claims only; existing attempts continue |
| GET /api/v1/handlers | Built-in schemas, versions and capabilities |
| GET /api/v1/overview | Consistent bounded summary for dashboard; documented time window |
| GET /health/live | Process is responsive, not a durability promise |
| GET /health/ready | Schema/database access and maintenance-loop freshness |
| GET /metrics | Auth-protected local Prometheus exposition |

Errors: stable code, safe message, request_id, optional field details. Examples: IDEMPOTENCY_CONFLICT, JOB_NOT_CANCELABLE, DATABASE_BUSY, HANDLER_UNAVAILABLE. UTC timestamps and explicit nullable fields. Never expose stack traces, tokens or raw internal SQL in HTTP errors. Document that a list traversed during writes is not a frozen snapshot; stable cursor keys avoid offset drift but filters may change.

### 8.2 CLI commands (planned interface, not executable yet)
- relay init: create local data/config directory and token with restricted permissions; non-destructive and explicit output.
- relay db migrate / backup / prune --dry-run: local maintenance with safeguards.
- relay serve: bind loopback, serve API and built UI; no worker hidden inside request handlers.
- relay worker start --queues default --concurrency 2: dedicated supervised process.
- relay jobs submit text_summary --payload-file INPUT --idempotency-key KEY
- relay jobs list --state failed --queue default --json
- relay jobs inspect JOB_ID; relay jobs attempts JOB_ID
- relay jobs watch JOB_ID --timeout 120: polling with bounded deadline.
- relay jobs cancel JOB_ID; relay jobs rerun JOB_ID --idempotency-key KEY
- relay workers list; relay queues pause NAME; relay queues resume NAME
- relay doctor: paths, versions, schema, endpoint reachability, permissions; never prints secrets.

All job operations use HTTPX with explicit connect/read/write/pool timeouts. --json emits only JSON on stdout, logs/errors on stderr; colors disabled for non-TTY. Proposed exit codes: 0 success, 1 API/operational failure, 2 usage/validation, 3 watch deadline exceeded. Non-interactive destructive actions require explicit flags; never block CI awaiting a prompt. Credentials come from configured environment or permission-restricted config, not command-line arguments or URLs.
## 9. Dashboard UX and visual specification

### 9.1 Design direction: an operations instrument panel
Use a restrained industrial/utilitarian aesthetic: precise spacing, readable dense data, fine borders, clear status indicators, no decorative purple gradients, glass cards, animated backgrounds or fake activity. The defining visual feature is the attempt timeline: execution, delay and recovery made understandable in one place. Beauty comes from hierarchy and clarity under failure, not from dashboard ornament.

Desktop-first responsive SPA, not a mobile native application. Default route is Jobs, not a landing page. Show a persistent installation label (LOCAL), connection freshness, and a prominent Submit job action. Avoid paid fonts/external font calls. Suggested self-hosted IBM Plex Sans plus IBM Plex Mono; verify font licensing and bundle size before adoption. Provide ordinary system fallbacks.

Draft tokens (not contrast-validated yet): background #101416, surface #181E21, elevated #222A2E, border #344047, primary text #E7EEF0, muted text #A6B3B9, accent #65D4C5, failure #FF8E8E, warning #EBC06A. Status includes icon and text; never rely on color. Validate WCAG AA text/non-text contrast before freezing tokens. Dark first, with a tested light theme in polish; do not ship an untested theme toggle.

Spacing scale 4/8/12/16/24/32 px; body 14-16 px, metadata 12-13 px, page heading 24 px; monospaced tabular numerals for IDs/durations. Desktop row height about 44 px; touch targets at least 44 px where feasible. Small radius, visible focus ring, no hover-only essential controls. Respect reduced motion; transitions approximately 120-180ms, never animate row order during investigation.

### 9.2 Information architecture
Navigation: Jobs, Queues, Workers, System. Overview statistics appear within Jobs; a separate analytics product is unnecessary. Initial widths: sidebar approximately 208px on wide screens, collapsible below 1024px, single-column views around 640px. Breakpoints must be checked against real content rather than assumed device categories.

Wide-screen Jobs wireframe:
```text
Relay / LOCAL                 Connected - updated 2s ago       Submit job
Jobs  Queues  Workers  System
Ready 12 | Running 2 | Retry waiting 3 | Failed 1 | Oldest due 9s
Search ID/handler   Queue [all]  State [all]  Time [24h]  Reset
Status       Handler          Job ID       Queue   Attempt   Age   Duration
Retry in 8s  demo_flaky        ab12...       default 2 / 3     20s   120ms
Succeeded    text_summary     cd34...       default 1 / 3     25s   14ms
50 per page                                    Previous  Next
```

Use native table semantics, sortable header controls with aria-sort, real job links, and keyboard-accessible row action buttons. No div pretending to be a table, and no complex ARIA grid unless actual grid keyboard interaction is implemented. Keep a default 50-row page; add TanStack Table/virtualization only if real interaction needs or measured rendering cost justify it.

### 9.3 Job detail: the key screen
Route /jobs/:id, with back navigation preserving list filters. On wide displays an optional preview panel can accelerate inspection; the same detail must have a full-page URL. First show state and reason, handler, queue, job ID copy button, submitted time, attempt budget, current owner/lease age where relevant, retry schedule and available actions.

Primary content: chronological attempt timeline. Each attempt displays start/end/duration, worker, result state, concise error and retry delay. Expand for bounded logs and safe formatted input/output. Distinguish running attempt, waiting for retry, lost ownership and terminal failure. A worker lost event is not shown as a normal handler exception. Show UTC absolute times plus relative age and clarify timezone. No secret ownership tokens in UI.

Tabs: Attempts (default), Input, Output, Events. Lightweight preformatted JSON with copy control and byte size; no Monaco dependency. Payloads/logs are rendered as text, never injected HTML. Collapse long values and offer bounded pagination, not unlimited downloads.

Mutation safety: Cancel enabled only when the last fetched state allows it; server remains authoritative if a race occurs. A 409 updates state and explains why the operation could not apply. Rerun confirms new-job creation and repeated-side-effect risk, shows original lineage, and navigates to the returned new ID. Never optimistically label a job canceled/succeeded before server acceptance.

### 9.4 Other screens
Submit: choose built-in handler, show description and explicit schema-driven fields for the small supported set, validate JSON if advanced mode is offered, select queue, priority, attempts and delay. Avoid generic form-builder complexity. Persist a submission key until success/explicit restart; double clicks cannot create duplicate requests.

Workers: boot ID, host, configured capacity, current attempts, heartbeat age, draining/stale/offline interpretation and handler versions. A fresh supervisor heartbeat does not prove every handler is healthy. Do not expose arbitrary process kill controls in the browser.

Queues: ready depth, retry-wait count, oldest due age, paused status. Pause confirmation explains that running attempts continue. System: version/schema, DB size, maintenance freshness, local-only boundary and diagnostic copy without secrets. Backup/prune remain local CLI operations initially.

### 9.5 Loading, empty, stale and error states
- First load: dimension-matched skeleton or quiet loading indicator, never fake sample jobs.
- Empty installation: explain starting worker and submitting first built-in job.
- Filtered empty: show active filters and Clear filters.
- No compatible worker: explicit waiting reason, not an infinite spinner.
- Connection lost: retain last known data with timestamp and stale banner; disable uncertain mutations.
- Slow request: show ongoing fetch without blanking the table.
- 401: explain local access token requirement, not a generic error toast.
- 409: inline current state and action explanation.
- 5xx/busy: bounded retry for reads and a visible failure after exhaustion.
- Malformed/missing job: proper not-found view and route back.

Avoid continuously reordered rows while users inspect them: keep list ordering by creation, preserve focus/scroll/selection, and optionally show New jobs available before replacing the first page. Polling status updates may change cells but should not steal focus. Relative timestamps update at a coarse shared interval, not a timer per row.

### 9.6 React architecture and data flow
Use Vite SPA and React Router. Store filters/sort/cursor in URL; server state in TanStack Query; form/dialog state locally. No duplicate global job store. Query keys include all relevant filters. Request independent detail/attempt reads in parallel, or provide a deliberate backend detail aggregate; avoid chains caused only by component nesting.

Proposed active view polling: jobs/detail 2s while active; workers/summary 5s; stop aggressive polling for terminal detail and hidden tabs. Use one polling owner per logical query, since observer timers can multiply even when in-flight requests deduplicate. Explicit staleTime, retry count/backoff and AbortSignal handling. Do not blindly retry 401/404 or POST operations. Invalidate affected queries after accepted mutations.

Polling first; SSE later only if latency or request volume measurements justify it. Future SSE uses durable event sequence cursors, reconnect/backfill, bounded retention and fallback polling. Native EventSource authentication requires an intentional cookie/session or alternative design, not tokens in URLs. WebSockets are unnecessary for read-mostly status.

Lazy-load heavy detail features only if needed; avoid loading a chart/editor library for the Jobs screen. Do not add useMemo/useCallback everywhere without profiling. Keep rendering pure, derive simple state directly, and use stable job IDs as keys. Bound API payloads and log lists before optimizing rendering.

### 9.7 Accessibility and visual acceptance
Keyboard-only submit/filter/detail/cancel/rerun paths; visible focus; Escape closes dialogs; dialog focus restored to trigger; labelled fields with associated errors; reduced-motion mode; 200% zoom; 320px viewport content access; screen-reader-friendly status summaries. Do not announce every polling update through aria-live. Native tables retain readable labels on narrow layouts, with deliberate horizontal scrolling or a separate small-screen card layout.

Run automated axe checks, but also manual keyboard and screen-reader smoke checks. Verify contrast for every status/theme. Record screenshots at 1440, 1024, 768 and 390px with deterministic fixtures. Visual screenshots must be labelled demo data where published; no claimed performance numbers in them.

## 10. Security, observability and operational practices

### 10.1 Trust boundary
Local trusted-code developer tool, not a public multi-tenant service. Bind 127.0.0.1 by default. Require authentication for job data/mutations; local binding alone is not authentication. Explicit allowed Host values and same-origin policy defend against unintended browser access. No wildcard credentialed CORS. Vite development uses a deliberate same-origin proxy.

Generate a strong random installation API token locally, store with restricted OS permissions, and never include it in URL/query logs or process arguments. CLI uses bearer authentication. Dashboard can start with manually entered bearer token held in memory (not localStorage); do not embed installation secrets in the static bundle. A later session-cookie flow requires CSRF protection, session lifetime and logout design. For remote operation, require a separate reviewed TLS/auth deployment plan; v1 should reject unsafe non-loopback binding without an explicit unsupported-mode warning/override policy.

Request limits, validated queue/handler IDs, bounded pagination, parameterized SQL, restrictive payload/result size caps, safe static-file routing, log redaction and HTML escaping are baseline. No raw SQL endpoint, uploaded code, arbitrary shell commands or user-selected filesystem paths for handlers. Redact known sensitive keys, but do not claim redaction guarantees protection from secrets embedded in arbitrary text. Do not collect production secrets in demo payloads.

### 10.2 Metrics and logs
Structured logs: timestamp, level, event, request_id, job_id/attempt_id where appropriate, worker_id, error_code, duration. Logs are bounded/rotated; API errors reveal summaries rather than tracebacks. Correlation IDs belong in logs, NOT unbounded Prometheus labels.

Start with DB-backed gauges: relay_jobs{state,queue}, relay_queue_oldest_due_age_seconds{queue}, relay_workers{state}. Queue/handler names must be bounded. Add API request counters/histograms with route-template labels. Never label by job ID, raw URL, exception message, idempotency key or user text.

Attempt success/failure counters and duration histograms need defined ownership across processes. Do not increment only API memory when workers finish elsewhere. Either maintain durable aggregate buckets/counts in the same transition transaction and expose them, or defer those metrics. Retention must not make a metric advertised as a counter decrease. Use seconds/bytes units and _total for counters. Dashboard database summaries and Prometheus scrape windows must have distinct documented meanings.

Readiness includes DB/schema/maintenance-loop status; liveness is process responsiveness. Proposed operator alerts to validate later: due queue age growing with no compatible worker, persistent lease losses, recovery loop stale, repeated DB busy exhaustion, disk space low. No alert percentages before defining denominator and time window.

### 10.3 Packaging and operations
Development: separate API, worker and Vite processes. Release: build static UI and package/serve it from FastAPI with correct deep-link fallback that never intercepts /api paths. No Node runtime required by the built local UI. Test wheel contents and static assets from a fresh environment. Source-only distribution is an acceptable first milestone if binary packaging is not proven.

Use versioned API, schema compatibility check, committed lockfiles and reproducible build instructions. Linux CI plus Windows CI from the first worker milestone; cross-platform shutdown cannot be left to the final day. Docker is optional Linux deployment documentation, not the Windows installation prerequisite. Logs/data survive application upgrades. Backups and restoration must be tested, not just described.
## 11. Testing strategy and executable acceptance criteria

### 11.1 Test pyramid
Unit tests: state transition rules, retry budget and jitter bounds, canonical request hashes, payload limits, schedule calculations, typed error mapping. Inject clock/randomness; no sleep-based unit assertions.

Storage integration: file-backed temporary SQLite, real transactions and independent connections. In-memory SQLite alone cannot validate WAL/concurrent connection behavior. Test migrations and constraints, rollback after injected failures, job/attempt/event atomicity, idempotency conflicts and cursor ordering.

Concurrency: controlled barriers and separate connections/processes for duplicate submit, claim/claim, claim/cancel, recovery/recovery, heartbeat/recovery and completion/recovery races. Assert legal outcomes rather than one preferred thread ordering.

Process: real spawn supervisors/children on Windows and Linux, bounded waits, hanging handler timeout, abrupt worker loss, stale owner completion, graceful drain, child startup error and output limit. Each test owns its temporary directory and processes and cleans them in finally blocks. Do not terminate unrelated system processes.

API/CLI: OpenAPI shapes, auth failures, validated errors, HTTP retries with stable keys, JSON stdout, stderr separation, no prompts without TTY, watch timeout exit code and same-origin static routes.

Frontend: user-visible component interactions with React Testing Library; network failure/stale states with controlled fixtures; Playwright against real API+worker for essential journeys. Prefer getByRole/label locators and web-first assertions, not fixed sleeps or CSS implementation selectors. Each browser test owns deterministic seeded data.

Property tests: randomized allowed transition sequences maintain attempt budget, terminal immutability, at most one active ownership record and matching job/attempt state. Simulated clock advances test expiry and retries. Model tests complement, not replace, actual process/DB race tests.

### 11.2 Required scenario matrix
| ID | Scenario | Pass condition |
|---|---|---|
| T01 | Fresh migration + restart | Schema persists, duplicate migration is safe, unknown newer schema refused |
| T02 | Concurrent same-key same-body submission | Exactly one job; all successful responses reference it |
| T03 | Same key, different request | 409; existing job unchanged |
| T04 | Eight claim contenders | One active attempt/token for each selected job; no double claim record |
| T05 | Crash inside transition before commit | No partial job/attempt/event transition |
| T06 | Claim vs pending cancel | Either canceled without execution claim, or running with cancel conflict; no contradictory success responses |
| T07 | Recover same expired attempt twice | One lost event and one next-state transition |
| T08 | Old owner heartbeat/completion after recovery | Both rejected; current ownership/result unchanged |
| T09 | Lease expires before completion but before recovery | Completion rejected; expired token cannot resurrect ownership |
| T10 | Retry available_at in future | Not claimable before deadline; claimable at/after deadline |
| T11 | Attempts exhausted | Terminal failed; repeated recovery does not create more attempts |
| T12 | Supervisor killed while child active | Lease recovers under live maintenance; old child cannot commit state; cleanup limitation explicitly tested/reported |
| T13 | Hung child with live supervisor | Runtime watchdog ends owned attempt and frees slot, bounded retry policy applies |
| T14 | API stopped, workers alive | Existing work and worker recovery continue; CLI reports API unavailability honestly |
| T15 | All processes stopped/restarted | No recovery while stopped; eligible work recovers after restart |
| T16 | SQLite held busy / disk unavailable | Bounded wait/retry and safe failure; no false success or infinite hot loop |
| T17 | Rerun request response lost | Retry with same key produces only one linked new job |
| T18 | Paused queue | No new claims; existing attempt can finish |
| T19 | Handler version unsupported | Job remains visibly unclaimable, no retry storm burning budget |
| T20 | Dashboard network disconnect | Last data visibly stale; no fabricated live status |
| T21 | Keyboard-only job workflow | Submit/filter/inspect/confirm works and focus is preserved |
| T22 | Backup and restore | Consistent DB opens, history/idempotency preserved |
| T23 | Prune terminal history | Running jobs untouched, lineage/key-expiry behavior documented and verified |
| T24 | Fresh release install | CLI works; static UI assets and deep links work without Node at runtime |

Coverage is a diagnostic, not correctness proof. Require every listed transition/race test; an approximate 85% domain/service branch-coverage target can be a guardrail after initial measurement, never a replacement for these scenarios.

### 11.3 Proposed validation commands after scaffolding
These are planned commands, not commands claimed to work before the repository exists. Define matching package scripts/configuration in milestone M0:
- uv sync --locked
- uv run --locked ruff check .
- uv run --locked ruff format --check .
- uv run --locked mypy src
- uv run --locked pytest -q
- uv run --locked pytest -m process -q
- npm --prefix web ci
- npm --prefix web run lint
- npm --prefix web run typecheck
- npm --prefix web run test -- --run
- npm --prefix web run build
- npm --prefix web run test:e2e

CI executes from the proposed repository root. Use a Python script or explicit cross-platform environment configuration to launch owned test services; do not assume bash command syntax on Windows. Commit lockfiles, pin CI action revisions when practical, restrict job permissions and never expose secrets to untrusted PR execution. Dependency auditing is defensive maintenance, not evidence of zero vulnerabilities.

## 12. Benchmarks and performance budgets

No throughput measurements exist for Relay. Proposed engineering budgets are targets to validate, not advertised results.

Use a reproducible script with fixed seed, recorded CPU/RAM/OS/Python/SQLite versions, durability settings, worker count and payload sizes. Separate submission latency, claim latency, queue wait, handler runtime and completion commit time. Test 1/2/4 supervisors with bounded concurrency and 1k/10k retained jobs. Include short pure tasks and 100ms simulated work. Child spawn overhead will dominate tiny tasks; document it rather than selecting a flattering benchmark.

Report p50/p95/p99 where sample size supports them, jobs/sec, DB busy retries, CPU/RAM, WAL size, and lost/recovered attempts. Measure under polling dashboard load and without it. Correctness invariant failures invalidate a speed result. Do not compare to another queue without matching durability, execution isolation and workload settings.

Initial UX targets on a declared reference machine: 50-row Jobs screen interactive promptly, local list/detail p95 around 200ms under modest load, no UI response body unbounded, initial compressed JS approximately <=250KiB as a starting budget. These are negotiable budgets, not hard guarantees. A missed budget triggers profiling, pagination/index fixes and scope review before introducing Redis or virtualization.

SQLite exit criteria: measured writer contention prevents chosen workload/recovery goals despite short transactions and tuned indexes, or users need multi-host workers. Then propose PostgreSQL, backed by adapter contract tests and explicit claim SQL using row-level locking/SKIP LOCKED. Merely swapping the database URL is not a migration plan. No second backend until the first is correct.

## 13. Implementation milestones and dependency order

| Milestone | Deliverable | Exit gate |
|---|---|---|
| M0 — project contract | Inspect/create repo safely; finalize dependency decisions; lockfiles; minimal API/CLI/web scaffolds; CI and ADRs | Fresh environment runs lint/typecheck/smoke tests; no unfinished placeholder feature claims |
| M1 — durable state core | Schema/migrations, explicit transaction helper, idempotent submit, claim, complete/fail/recover, pending cancel, attempts/events | T01-T11 via service/storage tests; no UI required; toy executor cannot be called the production worker |
| M2 — real worker | Spawn children, registry, slots, heartbeat, watchdog, drain, recovery and bounded IPC | T12-T16/T19 on Windows and Linux; orphan/process limits documented |
| M3 — usable CLI/API | Auth, complete HTTP contracts, CLI JSON/human modes, queue control, rerun lineage, diagnostic command | API/CLI tests and T17-T18; full submit/retry/crash demo works without browser |
| M4 — dashboard | Jobs table, submit, job attempts, worker/queue pages, stale/error UX and accessible dialogs | T20-T21; actual API data; screenshot checks; no mocked shipped functionality |
| M5 — operational hardening | Metrics, backup/restore, prune safeguards, limits, package assets, benchmark harness | T22-T24; published measured results and known limits |
| M6 — release polish | Documentation, architecture diagram, demo recording, accessibility fixes, installation verification | Full clean-room demo and CI green; claims match evidence |

Dependency graph: M0 -> M1 -> M2 -> M3 -> M4 -> M5 -> M6. UI static design may proceed alongside M2 after API contract stabilizes, but it must not delay queue correctness. Avoid simultaneous database schema edits by multiple coding agents; assign ownership boundaries if parallelizing.

If time is constrained, ship M0-M3 as a complete CLI-first alpha, then a read-only M4 subset. Do not cut fencing/watchdog tests to add charts. Estimates should be made after M1 and the cross-platform worker spike; no promise that every milestone fits a single uninterrupted generation.

### 13.1 Build-session handoff checklist
At each milestone record: files changed, actual commands and exit statuses, tests passed/failed/skipped, schema/API changes, open limitations and exact next step. Preserve user edits; inspect git status/diff before and after. Never report 'tested' based on generated test files without running them. Use small reviewable commits only if requested/authorized by the implementation workflow.

### 13.2 Release demonstration script
1. Initialize a new local instance and start API and worker separately.
2. Submit text_summary from CLI; find identical ID/result in dashboard.
3. Repeat same request key; show no duplicate job.
4. Submit demo_flaky configured to fail twice; inspect its three attempts and persisted backoff.
5. Run bounded demo_delay, terminate only the demo supervisor, observe lease expiration/recovery and a new attempt.
6. Display automated stale-owner rejection evidence, not merely a screenshot saying safe.
7. Pause queue, submit pending work, cancel it, resume queue.
8. Rerun an eligible failed job and show linked new ID with unchanged original history.
9. Restart application and show durable history; demonstrate backup restoration in an isolated instance.
10. Explain at-least-once limits, single-writer SQLite and what would trigger PostgreSQL adoption.

## 14. Risk register and decisions still requiring a spike

| Risk | Mitigation / decision gate |
|---|---|
| SQLite contention from claims/heartbeats/UI | Short transactions, bounded polling, indexes, measured concurrency; T16 and benchmark |
| Stale process performs side effect | Pure built-ins; fenced DB writes; no exactly-once claim; external idempotency for future handlers |
| Hung/orphan process on Windows | Watchdog and owned-child cleanup tests; no arbitrary descendants; OS containment deferred explicitly |
| Dependency version drift | Confirm supported versions, lock resolution, clean install and CI matrix |
| Incomplete transaction/migration behavior | Explicit sqlite3 control, atomicity fault tests, upgrade/restore tests |
| Fast UI hides stale backend | Data freshness banner, state-derived actions, server authoritative mutations |
| Feature creep overwhelms core | Scope boundary and milestone exit gates; no workflows/AI/remote multi-tenancy in v1 |
| Token UX hurts local setup | Document one-time local token entry; secure convenience flow only after threat review |
| Retention invalidates lineage/counters | Explicit prune semantics, durable aggregates if needed, referential tests |
| Market duplication | Position as inspectable educational local tool; do not claim no alternatives |
| Name collision | Relay is a working name; check package/repository/trademark suitability before publishing |

Before M0 finalize: handler input caps, token storage ACL behavior, supported Python floor, package name, whether light theme is release-blocking, and target reference hardware. Before M2 finalize: IPC framing, timeout termination order, parent-liveness monitoring and OS-specific test expectations. Before M5 finalize: retention/key expiry and metrics aggregate design. Defaults in this document are recommendations, not already validated production tuning.

## 15. Research sources, provenance and limitations

Research performed through agent-reach's Exa search, GitHub CLI and Jina documentation reader. Agent-reach doctor timed out during this pass; earlier availability is not treated as a fresh comprehensive health check. Exa returned useful source excerpts, then HTTP 429 free-tier limit. No credentials were changed and no paid access purchased. Continued only with direct documentation/GitHub reads. No logged-in social research, product user interviews, live competitor usability tests or pixel-level screenshot audit occurred. Frontend-design and React best-practices guidance informed recommendations. A separate architecture reviewer challenged lease, timeout and process assumptions; its suggestions were reviewed rather than treated as tested facts.

Sources actually consulted (2026-09-17; mutable docs may change):
1. FastAPI background-task caveat: https://fastapi.tiangolo.com/tutorial/background-tasks/
2. SQLite WAL: https://www.sqlite.org/wal.html and https://github.com/sqlite/sqlite/blob/master/doc/wal-lock.md . Main Jina response partially returned HTML; single-writer claim was also present in retrieved search excerpts.
3. SQLite transaction-upgrade explanation (secondary): https://simonwillison.net/2025/Feb/17/sqlite-busy/
4. Celery acknowledgment/idempotency documentation: https://docs.celeryq.dev/en/main/userguide/tasks.html and https://docs.celeryq.dev/en/stable/reference/celery.app.task.html
5. SQLite driver transaction behavior: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html
6. Python spawn/process lifecycle: https://docs.python.org/3/library/multiprocessing.html
7. PostgreSQL SELECT: https://www.postgresql.org/docs/current/sql-select.html . Retrieved excerpts were limited; future adapter needs a dedicated locking review.
8. Queue alternatives: https://github.com/rq/rq ; https://github.com/coleifer/huey ; https://github.com/taskiq-python/taskiq ; https://github.com/procrastinate-org/procrastinate ; https://github.com/mher/flower . Huey and Procrastinate READMEs read; others primarily metadata. Initial celery/flower lookup failed; mher/flower is the verified repository.
9. Runs versus attempts: https://trigger.dev/docs/runs
10. Failure-investigation UX: https://www.inngest.com/docs/platform/monitor/inspecting-function-runs
11. Query defaults and polling: https://tanstack.com/query/v5/docs/framework/react/guides/important-defaults and https://tanstack.com/query/latest/docs/framework/react/guides/polling
12. Native table accessibility: https://www.w3.org/WAI/ARIA/apg/patterns/table/
13. Accessible primitive behavior: https://www.radix-ui.com/primitives/docs/overview/accessibility
14. Reproducible Python environments: https://docs.astral.sh/uv/concepts/projects/sync/
15. Browser testing practices: https://playwright.dev/docs/best-practices
16. Metric units and cardinality: https://prometheus.io/docs/practices/naming/
17. Core project metadata/license checks: https://github.com/fastapi/fastapi ; https://github.com/pydantic/pydantic ; https://github.com/fastapi/typer ; https://github.com/encode/httpx ; https://github.com/vitejs/vite ; https://github.com/TanStack/query ; https://github.com/microsoft/playwright . Metadata is not a transitive license audit.

Agent Reach reported installed v1.5.0 current; no update performed. Research is a bounded pass, not a claimed two-hour uninterrupted session or exhaustive survey. Library and design choices optimize for this project's constraints, not an objective universal 'best'.

## 16. Validation performed during planning

Ran a disposable, standard-library SQLite experiment with installed CPython 3.13 / SQLite 3.49.1. Eight threads with independent file-backed WAL connections raced to claim a single queued row under BEGIN IMMEDIATE. Exactly one claim/attempt succeeded. A controlled expiry/recovery cleared the old owner; old-owner completions were rejected both before and after a new claim. An early retry was rejected; the new owner completed, with total attempts equal to two. Temporary database was cleaned up.

The first experiment invocation failed from Windows command-line quoting before execution; re-running via Python stdin succeeded. This is a transaction-semantics smoke experiment ONLY. It did not test the future Relay implementation, full schema/events, multiprocess workers, crashes, auth, API, UI, deadlines, migrations or throughput. No application code was created and no full Relay tests could run because the application does not yet exist.

Final document verification checks the required sections, source links, balanced code fences and absence of incomplete placeholder markers. Next authorized implementation step is M0, followed by the tested durable state core in M1.