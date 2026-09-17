# ADR-0004 — Project name and identity

Date: 2026-09-17. Status: proposed — collision check required at Phase A before any public artifact.

## Context
"Relay" is a working name chosen for the job-system concept (relaying work between API and workers).

## Decision
Working name Relay; package name `relay-jobs`; check before Phase A completes: PyPI availability, GitHub repo/org name, general trademark search for developer-tool category. Record findings here; pick fallback (`relayqueue`, `jobrelay`, or similar) if conflicts exist.

## Consequences
Rename after public artifacts is expensive; this ADR must be resolved first. The name must not imply a connection to existing products named Relay (e.g., other dev tools) — README positioning states the project's scope explicitly.
