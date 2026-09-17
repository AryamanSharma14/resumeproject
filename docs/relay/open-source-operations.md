# Relay Open-Source Operations

Status: process requirements. Files listed are created in Phase A; policies take effect at first public release.

## 1. Governance
Single maintainer (Aryaman) with BDFL-style decisions documented via ADRs; no foundation claims. Decision rule: behavior/correctness changes need an ADR; typos/docs don't. Governance text honest about single-maintainer reality (bus factor declared, roadmap ownership stated).

## 2. Contribution rules
- DCO 1.1 (`Signed-off-by`), enforced by CI (dco app), chosen over CLA for low friction (rationale in ADR-0002).
- PRs: small, tests for behavior changes, ADR required for contract/schema/scope changes.
- CONTRIBUTING.md: dev setup (uv/npm), test layout, scenario-matrix pointers (T01-T24), commit message convention, build-time expectation (<30 min from clean clone, measured and stated).

## 3. Triage and labels
Labels: `type/bug`, `type/feature`, `type/docs`, `area/api`, `area/worker`, `area/ui`, `area/docs`, `status/triaged`, `good-first-issue`, `needs-adr`, `scope/v1` vs `scope/later`.
Cadence declared as best-effort weekly; issues triaged to one of those labels or closed with reason. Feature requests outside the defer list get `needs-adr` and an honest maybe; nothing is promised by acceptance.

## 4. Release process
1. Changelog updated (Keep a Changelog), version bump, tag.
2. CI green on both OS; release workflow builds wheel+image, signs, SBOM, checksums.
3. GitHub Release from changelog; PyPI trusted publish; docs site redeploy.
4. Post-release: announce (repo discussions), close milestone, start next.
Cadence: feature releases when ready, patches as needed; no date promises.

## 5. Security disclosure
GitHub private security advisory as primary channel; SECURITY.md (Phase A) defines acknowledgment/triage targets per security.md section 6; advisories published with releases; CVE requested when warranted. Maintainers coordinate fixes privately; credit reporters by default unless asked otherwise.

## 6. License and compliance
- Apache-2.0 (ADR-0002); third-party inventory generated per release (license + notice bundle in distribution artifacts; uv/npm license report generated in CI).
- No CLA; no contributor agreement beyond DCO; notice files preserved.

## 7. Community health files (Phase A checklist)
README (value prop in first screen, honest positioning), CONTRIBUTING.md, CODE_OF_CONDUCT.md (Contributor Covenant), SECURITY.md, SUPPORT.md (points to Discussions), FUNDING.yml optional, .github/ISSUE_TEMPLATE (bug/feature), .github/PULL_REQUEST_TEMPLATE.md, CODEOWNERS.

## 8. Scope guards (anti-overload policy)
The defer list (implementation-plan 2.2) is normative: issues proposing it get `scope/later` + ADR requirement, with a kind redirect. Maintainer may mark issues `not-planned` without debate when they conflict with the failure-model honesty rules.

## 9. OSS acceptance criteria
All health files live; DCO bot green; templates exercised by a test issue/PR; one full release run end-to-end (changelog→tag→artifacts→publish→docs redeploy) rehearsed on a prerelease tag; contributor-from-clean-clone time measured and recorded.
