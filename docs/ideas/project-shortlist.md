# Project shortlist
Saved 2026-09-17. Based on C:\Users\aryam\Downloads\Resume july 2026.pdf.
Status: research only; no implementation.

## 1. Relay — retained first idea
Reliable background-job system: FastAPI API, Typer CLI, persistent queue, workers, React dashboard. Local MVP: predefined handlers, retries/backoff, idempotent submission, heartbeats, interrupted-job recovery, attempt history and metrics. SQLite initially; at-least-once execution requires repeat-safe handlers. Include tests and crash/recovery demo. Exclude Kubernetes, clustering, billing and production multi-tenancy.

## 2. ShowYourWork — recommendation, not yet user-approved
Working name; availability not checked. Local verification CLI/MCP for AI-written bug fixes.
Pitch: the agent says fixed; show reproducible evidence rather than a reassuring sentence.

Demo: run the selected regression test on the original code plus test-only changes and on the candidate. If both pass, label evidence non-discriminating, not the fix wrong. With a better regression test, show the expected assertion failure on the original and a pass on the candidate. Export snapshot hashes, command, environment metadata, test IDs/counts/skips, exit codes and logs. Further code changes mark the receipt stale.

MVP: trusted local Git repositories; Python/pytest only. Explicit base revision, candidate snapshot, selected tests and approved command. Disposable working copies; never reset/discard user changes. Capture tracked modifications and explicitly selected untracked inputs or reject unsupported layouts. Parse structured test reports; distinguish assertion failures from import/collection errors, zero tests, skips and timeouts. CLI engine, thin MCP adapter, SQLite history, JSON/Markdown receipts. Optional small dashboard after engine validation. Test pass/pass, fail/pass, fail/fail, collection errors and stale results.

Boundaries: a red/green pair is evidence about tested behavior, not proof of overall correctness. New APIs absent on the base or incompatible fixtures can make comparison inconclusive. Repeated runs cannot prove no flakiness. Working copies are NOT a security sandbox; execute only approved trusted code with no production credentials or destructive live integrations. Hashes detect mismatches but do not provide independent attestation against someone controlling the machine. Protected CI verification is later work. No universal language support, automatic bug fixing or production sandbox in v1.

Fit: Python/Typer tooling, FastAPI, infrastructure lifecycle handling and observability map to process supervision, snapshots, result parsing, provenance and MCP. A narrow tested MVP is a plausible one-pass target, not a guaranteed flawless universal verifier.

## Research evidence and competitors
Used agent-reach Exa search and GitHub CLI. Limited search; no claim of an empty market. Logged-in social channels were unavailable and not used. Agent Reach v1.5.0 reported current.
- User request for inspectable verification evidence: https://github.com/anthropics/claude-code/issues/79107 . A pain-point signal, not market-size proof.
- https://github.com/ardev-lab/verify-action-mcp checks supplied evidence; README says it does not independently access repositories/databases/APIs. Proposed distinction: actually execute checks.
- https://github.com/MSBeni/trust_ai already packages evaluation evidence and release gates. Receipts themselves are not novel.
- https://arxiv.org/html/2607.28871v1 describes related buggy-state/candidate-state/gold-fix replay. Supports the technique but rules out claiming its invention. MVP has no gold fix and cannot establish gold-aligned correctness.
- Undo tools already exist: https://github.com/mohithhhh/mcp-compensator and https://github.com/LokeyDev0/UndoMCP-Tool . Rejected as an allegedly empty niche.
- Runtime observability exists: https://github.com/perception30/browser-connect-mcp and https://www.npmjs.com/package/gasoline-mcp . Rejected as an allegedly empty niche.

Hypothesis: focused, easy-to-install local regression verification may help coding-agent users and maintainers reviewing AI fixes. Validate with users before expanding; adoption and novelty are not guaranteed.