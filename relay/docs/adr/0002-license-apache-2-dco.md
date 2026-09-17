# ADR-0002 — License Apache-2.0, contributions via DCO

Date: 2026-09-17. Status: proposed — requires user confirmation at Phase A checkpoint before any public artifact.

## Context
Relay may later be monetized (open-core or support) while accepting community contributions now.

## Decision
Apache-2.0 for the whole project. Contributions accepted under DCO 1.1 sign-off; no CLA.

## Consequences
Patent grant protects users and any future commercial pack; compatibility with later proprietary additions is preserved. DCO keeps contribution friction low but, unlike a CLA, does not centralize relicense rights — future dual-license or license changes would need consent from all contributors or a relicense strategy early. AGPL rejected: it would complicate Path 2 (open-core) without adding value for a local-first tool.

## Alternatives
MIT (no explicit patent grant), AGPL (copyleft friction for future packs), dual AGPL/commercial (heavy process for a solo maintainer).
