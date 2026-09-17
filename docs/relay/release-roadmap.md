# Relay — Release Roadmap: Zero to Deployable and Distributable

Date: 2026-09-17. Status: planning document. Extends implementation-plan.md (same folder); engineering milestones M0-M6, database design and acceptance scenarios T01-T24 are defined there and are not duplicated here. Nothing is implemented yet; all gates below are requirements, not achievements.

## 1. Purpose and use
This roadmap takes Relay from an empty directory to a v1.0 that a stranger can install, run and audit, and that can be published as open source with a credible path to monetization. It is written as a one-shot execution contract: an implementer (human or coding agent) should be able to complete each phase without user intervention except at the checkpoints listed in section 10.

## 2. Ground rules for the whole roadmap
- The application is implemented in `C:/Users/aryam/Desktop/yee/coding/resumeproject/relay/` per AGENTS.md. Planning docs stay in `docs/relay/`.
- Engineering work follows `docs/relay/implementation-plan.md` sections 4-13 (layout, libraries, schema, worker, API/CLI, UX, security, tests, benchmarks, milestones). This roadmap adds the product, release and community layers.
- Scope discipline: no feature from the implementation plan's defer list enters v1. Scope changes require an ADR.
- Security requirements live in `docs/relay/security.md`; every phase gate includes the security acceptance criteria relevant to that phase. Operating procedures live in `docs/relay/operations-runbook.md`.
- Honesty discipline: no claimed benchmarks, uptime, adoption or security guarantees that have not been executed and recorded. Every public claim maps to a test, measurement or explicit limitation.
- Each phase ends with: green gates, a short handoff note (files changed, commands run with exit codes, open limitations, exact next step) in the repo under `docs/devlog/`.

## 3. Phase A — Foundation (engineering M0)
Objective: a real repository, not a folder of files.
Tasks: git init with main-default; `pyproject.toml` + committed `uv.lock`; Ruff + mypy + pytest configuration that fails loudly; `web/` Vite + TypeScript + React scaffold with Vitest; GitHub Actions CI on ubuntu-latest and windows-latest running lint, typecheck, backend tests, web tests and builds; ADR directory seeded from `docs/relay/adr/`; license decision recorded ([ADR-0002](adr/0002-license-apache-2-dco.md), proposed Apache-2.0, user confirms at checkpoint); project name collision check (PyPI, GitHub, simple trademark search; results recorded in [ADR-0004](adr/0004-project-naming.md)); README, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT skeletons; `.editorconfig`, `.gitignore`, `CODEOWNERS`.
Exit gate: fresh clone on a clean machine runs `uv sync --locked`, lint, typecheck and smoke tests green; CI green on both OSes; no placeholder code advertised as a feature.

## 4. Phase B — Durable core (M1)
Implement schema, migrations, idempotent submission, atomic claims, fenced completion, expiry recovery, retry policy, pending cancellation, attempts and events, per implementation-plan sections 6 and 11.
Exit gate: scenarios T01-T11 automated and green on Windows and Linux; injected-clock property tests pass; the failure model is documented from the code, not aspiration.

## 5. Phase C — Workers and CLI (M2+M3)
Spawn-based supervised children, watchdog, drain, bounded IPC; full API surface with authentication; complete CLI per implementation-plan section 8.2.
Exit gate: T12-T16 and T19 pass on Windows and Linux; the terminal-only portion of the demo script (section 13.2 there) works end to end; CLI exit codes and JSON modes are tested.

## 6. Phase D — Dashboard (M4)
Implement the UI per implementation-plan section 9 and `docs/relay/design-system.md`. Jobs table, submit, attempt timeline, workers, queues, stale and error states.
Exit gate: T20-T21 pass; Playwright E2E against real API and worker; keyboard and screen-reader smoke pass; visual screenshots produced from demo data only.

## 7. Phase E — Production hardening (M5+M6)
Backup/restore, prune safeguards, metrics exposition, benchmark report with measured numbers and methodology, static UI served by FastAPI with deep-link fallback, documentation site build, demo recording.
Exit gate: T22-T24 pass; benchmark report published with environment and method; every README claim traceable to a test or measurement.

## 8. Phase F — Distribution (new)
Full requirements in `docs/relay/distribution.md`. Summary:
- PyPI package `relay-jobs` (name confirmed in Phase A): wheel bundles the built UI, `pipx install relay-jobs` works with no Node at runtime; TestPyPI rehearsal first.
- GitHub Releases: tagged SemVer, Keep-a-Changelog entries, sha256 checksums, Sigstore artifact signing, OCI provenance.
- Docker image: multi-stage, non-root, healthcheck, multi-arch (amd64/arm64), published to GHCR; optional for users, required for release completeness.
- Docs site: MkDocs Material from repo docs, published to GitHub Pages (quickstart, concepts, failure model, API reference, security, runbook, screenshots).
- Service installation guides: systemd (Linux) and NSSM/Task Scheduler (Windows) in `docs/relay/operations-runbook.md`.
Exit gate: a stranger on a clean VM installs from PyPI in under 5 minutes using only the README, completes the demo, and the release artifacts are reproducible from the tagged commit.

## 9. Phase G — Open-source operations (new)
Full requirements in `docs/relay/open-source-operations.md`. Governance, DCO over CLA, issue/PR templates, triage labels and cadence, release process, security disclosure workflow, third-party license inventory, contributor build-time target (under 30 minutes, measured and stated), scope-guard policy.

## 10. Human checkpoints (the only required user actions)
1. Phase A start: confirm license (Apache-2.0 recommended) and project name.
2. Phase F: create/verify accounts — PyPI (with 2FA and trusted publishing), GitHub Packages/GHCR; approve the first public publish.
3. Any public claim about performance or security: user reviews the report before it ships.
Everything else proceeds autonomously with per-phase handoff notes.

## 11. Monetization paths (decision kept open by design)
- Path 1 — pure OSS (default for v1): Apache-2.0, everything free. Value: credibility, portfolio, adoption.
- Path 2 — open-core (enabled, not built yet): keep storage/driver and retention interfaces clean so a future commercial pack (PostgreSQL adapter, retention/compliance tooling, priority support) can exist without license conflicts. Apache-2.0 permits this; AGPL would not without a dual-license strategy. Interface discipline per [ADR-0003](adr/0003-open-core-interfaces.md).
- Path 3 — hosted service: out of scope until the PostgreSQL adapter and a multi-tenancy security review exist; treated as a separate product decision with its own threat model.
Decision policy: nothing is paywalled in v1; no paid tier is announced before it exists; the codebase is structured (per ADR-0003) so Path 2 remains available.

## 12. Definition of done for v1.0 (sellable/givable-away)
- All scenarios T01-T24 green in CI on Windows and Linux.
- `pipx install` demo works on clean VMs; Docker path tested.
- Security doc published with threat model and tested controls; disclosure channel live.
- Runbook tested end to end including backup restore and upgrade rollback.
- Benchmark report with real numbers and honest limitations.
- Docs site live; demo recording matches documented behavior.
- License, DCO, contributor and governance files complete; third-party license inventory clean.
- Name/branding cleared; PyPI/GitHub names consistent.

## 13. Timeline honesty
Phase A: one focused session. Phases B and C are the bulk of the work; elapsed time should be estimated after M1 and the cross-platform worker spike, not invented now. Phases D-F each add meaningfully. No claim is made that the whole roadmap fits one uninterrupted session; the plan is structured so any pause point leaves a working, tested state.

## 14. Roadmap-level risks
| Risk | Mitigation |
|---|---|
| Name collision discovered late | Check in Phase A (ADR-0004) before any public artifact |
| License regret after contributions | Apache-2.0 + DCO from the start (ADR-0002) |
| Cross-platform process bugs late | Windows+Linux CI from Phase A (ground rules) |
| Supply-chain incident | Locked deps, pinned actions, signing, SBOM (security doc) |
| Scope creep kills v1 | Defer list enforced; every addition needs an ADR |
| Maintainer overload | Triage cadence declared as best-effort; scope guards |