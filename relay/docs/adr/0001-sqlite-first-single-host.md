# ADR-0001 — SQLite-first single-host queue engine

Date: 2026-09-17. Status: accepted.

## Context
Relay needs durable, inspectable job storage with zero broker setup on a developer machine. Options: Redis/RabbitMQ (external service), PostgreSQL (service), SQLite (in-process), in-memory (not durable).

## Decision
Standard-library sqlite3 with WAL, explicit `BEGIN IMMEDIATE` write transactions, fenced lease/token state machine, numbered SQL migrations. One host, one writer at a time (SQLite single-writer constraint). PostgreSQL becomes an adapter only when measured contention or multi-host need exists (implementation-plan section 12 exit criteria).

## Consequences
No service dependency for install/demo; transaction semantics visible and testable; writer contention is the main scalability ceiling and must be measured, not assumed. Multi-host workers are out of scope until a reviewed adapter exists.

## Alternatives
Celery/RQ under a custom engine: adds broker ops, hides the correctness work that is the project's point. Huey SQLite: good tool, but wrapping it would not produce the inspectable lease/attempt engine (positioning in implementation-plan section 3). Procrastinate: strong if PostgreSQL is already present; it is not, for the local-first demo.
