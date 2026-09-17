# Relay Distribution Specification

Status: requirements for Phase F. Nothing is published yet; every artifact below is a gate for v1.0.

## 1. Python package
- Name `relay-jobs` pending Phase A collision check (ADR-0004); fallbacks recorded there.
- `pyproject.toml`: hatchling backend (or setuptools if pinned reasons emerge); `relay` console script entry point; package data includes `relay/web/dist/**` (built UI) with correct wheel builder config.
- Version single-source from package metadata; SemVer; tags `vX.Y.Z`.
- Wheel contents tested from a fresh environment: no source dir, no Node required, UI assets present, `relay doctor` passes.
- sdist excluded from first release unless build reproducibility is proven.
- TestPyPI full rehearsal (upload, clean-VM pipx install, demo) before real PyPI publish; trusted publishing (OIDC), 2FA enforced; no long-lived API tokens in CI.

## 2. GitHub Releases
- Automated on tag: changelog entry check (Keep a Changelog format), wheel build, sha256 checksums file, Sigstore signing (cosign/gitsign via GitHub artifact signing), SBOM (CycloneDX) attachment, OCI provenance.
- Release notes generated from changelog; breaking changes highlighted; upgrade/rollback notes linked to the runbook.
- Releases are immutable after publish; hotfix policy: patch tag, never mutate a published release.

## 3. Docker
- Multi-stage build: node stage builds web/dist, python stage installs the wheel; final image runs uvicorn + worker entrypoints, non-root user, read-only rootfs compatible.
- Healthcheck hits /health/live; /health/ready documented for orchestrators.
- Multi-arch amd64/arm64 via buildx; published to GHCR as `ghcr.io/<owner>/relay-jobs`, tagged SemVer + major-minor + sha.
- Image includes no build toolchain, no Node; size budget documented after first build (no invented number).

## 4. Docs site
- MkDocs Material, built from repo docs; nav: Getting started, Concepts (jobs/attempts/leases), Failure model, API reference (from OpenAPI), CLI reference, Security, Runbook, Design, Benchmarks, Changelog.
- Published to GitHub Pages on release; versioned via mkdocs versions plugin if friction is low, otherwise latest-only with changelog (decision recorded in ADR-0005 at Phase F).
- Screenshots from the demo dataset only; every number shown is measured.

## 5. Installation paths (docs must show all three)
1. `pipx install relay-jobs` then `relay init && relay serve && relay worker start` (primary).
2. Docker compose example for Linux servers.
3. From source (contributors): uv + npm commands, under 30 minutes measured.

## 6. Distribution acceptance
Clean Windows VM and clean Linux VM: install from PyPI, complete the 10-step demo, upgrade to next patch, rollback; Docker image runs the demo; docs site renders all pages; every release artifact reproducible from tag by a third party.
