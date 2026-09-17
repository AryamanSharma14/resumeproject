# Release tooling evidence and open gates

Date: 2026-09-17. No commit, publishing, workflow dispatch, registry upload,
visibility change or Docker execution was performed.

## Implemented

- Stdlib build script: requires real web index/JS/CSS, rejects unsafe assets,
  copies static bundle, checks uv lock and pinned build backend, builds wheel,
  verifies bundled assets/SQL, writes SHA256SUMS, input hashes, dependency inventory
  and CycloneDX 1.5. Stable timestamps and LF output; no sdist or fake dashboard.
- Multi-stage Dockerfile, locked production deps, non-root UID 10001, stdlib
  healthcheck; separate init/API/worker Compose, read-only rootfs, dropped caps,
  private local named volume and allowlisted build context excluding credentials.
- Eight MkDocs Material pages describing current CLI/config and untested gates.
- Manual build-only-default workflow with pinned actions, repeat-build comparison,
  isolated wheel probe, docs preview, approval-gated OIDC TestPyPI/PyPI jobs.
- Dependabot (actions/uv/npm/Docker), sanitized bug and scoped feature issue forms.

## Executed checks

| Check | Evidence/result |
|---|---|
| Script help | Exit 0; no writes |
| Script `--check` | Exit 0; 11 real dashboard files, 299 lock records |
| Missing dashboard | ValueError for missing index; negative assertion passed |
| Inventory determinism | In-memory generations equal; 299 records / 297 distinct components |
| Ruff lint/format | Passed after formatting and fixing one long line |
| Docs links/nav | Eight pages resolved; local Markdown links valid |
| CLI contracts | serve/backup/prune help exit 0; port 8000, positional backup destination, explicit prune execute/yes |
| Full build | **Exit 1**: `Pin every build-system requirement with == before building a release`; no generated writes |
| MkDocs rendering | **Blocked**: mkdocs/material absent; docs dependency approval requested |
| Docker/Compose | **Untested**: Docker unavailable; content review only |
| YAML/CycloneDX schemas | Not validated yet; PyYAML/jsonschema absent |

Web dist was inspected read-only. Lead owns manifests and generated static/release
outputs. Build cannot proceed until lead pins hatchling and runs script. No package
installation performed by release agent. No full-wheel success is claimed.

## Verified action pins

`git ls-remote URL refs/tags/TAG` returned these SHAs, exit 0:

| Repository / tag | SHA |
|---|---|
| actions/checkout v4.2.2 | `11bd71901bbe5b1630ceea73d27597364c9af683` |
| actions/setup-python v5.6.0 | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| actions/setup-node v4.4.0 | `49933ea5288caeca8642d1e84afbd3f7d6820020` |
| actions/upload-artifact v4.6.2 | `ea165f8d65b6e75b540449e92b4886f43607fa02` |
| actions/download-artifact v4.3.0 | `d3f86a106a0bac45b974a628896c90dbdf5c8093` |
| pypa/gh-action-pypi-publish v1.13.0 | `106e0b0b7c337fa67ed433972f777c6357f78598` |

Tag resolution is not a security audit. No workflow executed.

## Boundary decisions

Runtime confirmed `serve` deliberately has no remote-bind override. Compose uses
Linux host networking for API, preserving 127.0.0.1:8000; worker/init have no network.
Do not add wildcard published ports or bypass CLI safety. Docker Desktop support
is not claimed. Host networking is not isolation from host network services.
Image bases have version tags, **not immutable digests**; resolution remains a gate.

SBOM covers uv/npm lock entries including dev/platform alternatives. It is not a
resolved runtime graph, OS inventory, vulnerability scan, full license/notice bundle.
Python lock metadata lacks license clearance. Checksums are not signatures. Repeat
build logic is not independent reproduction proof; backend transitive dependencies,
OS and toolchain must also be controlled.

## Public-release blockers

1. Lead pins approved hatchling and docs dependencies, locks them; runs two bundles
   and isolated wheel probe. Validate YAML/CycloneDX schemas and actual CI runner.
2. Linux amd64/arm64 container builds, volume ownership, read-only operation, probes,
   graceful drain, backup/restore/upgrade/rollback drills. Pin base digests, scan image,
   generate OS SBOM/provenance and measure image size.
3. Clean Windows/Linux install/demo and runbook rehearsal; accessibility/E2E evidence.
4. Independent reproducibility, third-party licenses/notices and security review.
5. Owner confirms name/license and explicitly authorizes public transition/publishing.
6. Owner configures required reviewers and tag restrictions for `testpypi`/`pypi`
   environments, OIDC trust and 2FA. YAML cannot create protection. Do not set approval
   variables before reviewed evidence and settings. TestPyPI is public too.
7. TestPyPI rehearsal; signed GitHub Release attachments, GHCR multi-arch push and
   Pages hosting/versioning are not implemented by this workflow.
8. Private security disclosure rehearsal; owner reviews any public performance or
   security claim. No invented screenshot, demo, timing or benchmark evidence.

After pinning, lead runs from `relay/`:
`python scripts/build_release.py --uv <uv-executable> --output dist` (empty output),
then a second empty output and compares SHA256SUMS; runs standalone wheel probe.
