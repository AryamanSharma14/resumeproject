# Relay operator guide

Relay is a local-first, single-host background job system backed by SQLite.
Jobs retain attempt history; workers execute registered, trusted handlers in child
processes. The dashboard and HTTP API inspect that same local database.

**Unreleased development snapshot.** No PyPI package, container registry image,
public documentation deployment, availability guarantee, or production certification
is claimed here. Package naming and public publication require owner approval.

Start with [local source installation](getting-started.md), then read the
[failure model](concepts.md) and [security boundary](security.md). Container
instructions are an [unverified Linux recipe](docker.md), not a tested alternative.

## What this is not

- A hosted service, distributed queue, or hostile multi-tenant execution platform.
- A sandbox for arbitrary code or an exactly-once side-effect guarantee.
- A replacement for backups and restore drills.

The [release checklist](release.md) distinguishes tooling that exists from gates
that remain open. This snapshot does not publish benchmark numbers, installation
timing, screenshots, or a changelog for releases that have not happened.
