# Resume Projects

Project workspace: this repository (local path intentionally not embedded; see AGENTS.md).

Store future project documents, research and implementation here, not in Downloads.

## Current structure

```text
resumeproject/
  README.md
  AGENTS.md
  docs/
    ideas/
      project-shortlist.md
    relay/
      implementation-plan.md    (engineering: architecture, schema, tests, milestones M0-M6)
      release-roadmap.md        (phase plan: zero to deployable v1.0 + distribution + OSS)
      design-system.md          (premium UI design spec for the dashboard)
      security.md               (threat model, controls, acceptance criteria)
      distribution.md           (PyPI, releases, Docker, docs site)
      operations-runbook.md     (install, services, backup, monitoring, incidents)
      open-source-operations.md (governance, contributions, release process)
      adr/
        README.md
        0001-sqlite-first-single-host.md
        0002-license-apache-2-dco.md
        0003-open-core-interfaces.md
        0004-project-naming.md
```

Reading order for an implementer: [release roadmap](docs/relay/release-roadmap.md) → [implementation plan](docs/relay/implementation-plan.md) → phase-specific specs (design, security, distribution, runbook, OSS ops) → ADRs.

## Status

All documents above are plans/specifications. No Relay application code exists yet. Implementation starts at Phase A (repo scaffold) in `relay/` when authorized, per [AGENTS.md](AGENTS.md) and the roadmap's checkpoint list.

Personal documents (e.g., a résumé PDF) are not stored in this repository.

