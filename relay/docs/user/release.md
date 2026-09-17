# Build and release gates

## Local bundle

Run from `relay/` after `npm ci && npm run build` in `web/`:

```sh
uv run --locked python scripts/build_release.py --check
uv run --locked python scripts/build_release.py --output dist
uv run --locked python scripts/build_release.py --output dist-repeat
```

The script fails if the real index/JavaScript/CSS is missing, assets are external,
symlinks appear, locks are stale, the build backend is not pinned, or an output
folder is nonempty. It replaces generated `src/relay/static/`, runs `uv build --wheel`,
and verifies every dashboard file plus migration SQL inside the wheel. No sdist is
produced. Keep the checkout idle while building.

Outputs:

- Wheel with Python code, SQL migrations and dashboard assets.
- `SHA256SUMS`: hashes of the other bundle files (not a signature).
- `sbom.cdx.json`: CycloneDX 1.5 inventory from uv and npm lock metadata.
- `dependency-inventory.json`: source/artifact hashes and available npm licenses.
- `build-inputs.json`: lock/input hashes, asset hashes, Python/uv and stable timestamp.

SBOM includes dev dependencies and platform alternatives: it is not a resolved
runtime graph, OS-package image inventory, vulnerability scan, or legal clearance.
Python lock metadata lacks license/notice coverage; review remains mandatory.

`SOURCE_DATE_EPOCH` defaults to 2000-01-01 UTC and can be set explicitly to a stable
commit timestamp. Reuse the exact Python, uv, Node/npm, dependencies, OS and source
for comparison. Compare `SHA256SUMS` between builds. Stable generation is implemented;
third-party/cross-platform reproducibility is not claimed until independently tested.

```sh
uv run --locked python tests/test_release_wheel.py --wheel dist/relay_jobs-0.1.0-py3-none-any.whl
uv run --locked --group docs mkdocs build --strict
uv run --locked --group docs mkdocs serve --dev-addr 127.0.0.1:8001
```

The isolated wheel probe installs dependencies and therefore may use the package
index. It is not a clean operating-system VM or a TestPyPI rehearsal.

## Workflow safety

`.github/workflows/release.yml` runs only on manual dispatch; default `build-only`
builds private workflow artifacts and a docs preview. It never automatically reacts
to a tag or makes the repository public. There are no GHCR, Pages, or GitHub Release
publishing steps in this snapshot.

Before even requesting `testpypi`/`pypi`, the owner must configure **required reviewers**
and allowed tag rules for both environments, configure trusted OIDC publishing, and
explicitly set `RELAY_RELEASE_GATES_APPROVED=true`. Environment protection is a GitHub
setting, not something YAML can establish. Without configured protection, do not set
that variable. TestPyPI uploads are public too and require approval.

PyPI additionally requires a public repository, `RELAY_PUBLIC_RELEASE_APPROVED=true`
and `RELAY_TESTPYPI_REHEARSAL_PASSED=true`. The publish job requires a SemVer tag equal
to the wheel version and checks artifact hashes. There are no long-lived PyPI tokens.
No workflow has been dispatched and nothing has been published by this implementation.

## Open launch gates

- Owner confirms project name/license, public repository transition and publication.
- Clean Linux/Windows install, complete demo, backup/restore, upgrade/rollback.
- Linux container builds and non-root/read-only runtime drills; multi-arch validation.
- Independent reproducibility, complete licenses/notices, image SBOM, signatures and provenance.
- Security-channel rehearsal, protected environments, TestPyPI rehearsal and CI evidence.
- Web accessibility/end-to-end review, truthful screenshots and benchmark report.
- Public docs hosting/versioning, signed GitHub Releases and container publication design.

Latest-only docs are generated locally; no versioned site or deployment is claimed.
The internal evidence ledger is `docs/devlog/release-gates.md` at repository root.
