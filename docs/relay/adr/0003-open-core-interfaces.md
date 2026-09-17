# ADR-0003 — Extension interfaces kept open for open-core

Date: 2026-09-17. Status: accepted.

## Context
Roadmap keeps monetization (open-core) possible without building any paid feature in v1.

## Decision
Storage access lives behind a storage interface owned by the core (driver adapters possible later); retention/pruning is a service with policy injected; metrics aggregation is defined so a commercial pack could add sinks without touching the state machine. No code under alternative licenses may live in this repository; separate distribution only.

## Consequences
Slight interface discipline cost now; avoids a painful retrofit if Path 2 is exercised; guarantees the free repo stays complete and buildable on its own — no crippleware.
