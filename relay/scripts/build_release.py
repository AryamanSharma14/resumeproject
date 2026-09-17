"""Build a local wheel with real dashboard assets and deterministic inventories.

Requires Python >=3.12, uv on PATH, a current uv.lock and an already-built web/dist.
No publishing occurs. Generated static assets replace src/relay/static; output must
be empty. The SBOM is a lockfile inventory, NOT an installed-environment attestation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


class Assets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        ref = values.get("src") if tag == "script" else values.get("href")
        if ref and tag in {"script", "link"}:
            self.references.append(ref)


def inspect_web(dist: Path) -> dict[str, str]:
    if not dist.is_dir() or not (dist / "index.html").is_file():
        raise ValueError(f"Missing {dist / 'index.html'}; run npm ci && npm run build in web first")
    files = sorted(dist.rglob("*"))
    if dist.is_symlink() or any(p.is_symlink() for p in files):
        raise ValueError("Dashboard build must not contain symlinks")
    manifest = {p.relative_to(dist).as_posix(): sha256(p) for p in files if p.is_file()}
    parser = Assets()
    parser.feed((dist / "index.html").read_text(encoding="utf-8"))
    local = []
    for ref in parser.references:
        url = urlsplit(ref)
        name = unquote(url.path).lstrip("/")
        if url.scheme or url.netloc or ".." in PurePosixPath(name).parts or "\\" in name:
            raise ValueError(f"Dashboard has an unsafe or external asset reference: {ref}")
        if name not in manifest:
            raise ValueError(f"Dashboard asset missing: {ref}")
        local.append(name)
    if not any(n.endswith(".js") for n in local) or not any(n.endswith(".css") for n in local):
        raise ValueError("Dashboard index must reference built JavaScript and CSS")
    return manifest


def inventories(root: Path, project: dict) -> tuple[dict, dict]:
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    npm = json.loads((root / "web/package-lock.json").read_text(encoding="utf-8"))
    records = []
    components = {}
    for package in sorted(lock["package"], key=lambda p: (p["name"], p["version"])):
        name, version = package["name"], package["version"]
        purl = f"pkg:pypi/{quote(name, safe='')}@{quote(version, safe='')}"
        artifacts = ([package["sdist"]] if "sdist" in package else []) + package.get("wheels", [])
        record = {
            "ecosystem": "pypi",
            "name": name,
            "version": version,
            "source": package["source"],
            "artifacts": artifacts,
            "dependencies": package.get("dependencies", []),
            "license_status": "not supplied by uv.lock; review required",
        }
        records.append(record)
        component = {
            "type": "library",
            "bom-ref": purl,
            "purl": purl,
            "name": name,
            "version": version,
            "properties": [{"name": "relay:inventory-scope", "value": "uv.lock union"}],
        }
        refs = []
        for artifact in artifacts:
            if "url" in artifact and "hash" in artifact:
                algorithm, digest = artifact["hash"].split(":", 1)
                if algorithm != "sha256":
                    raise ValueError(f"Unexpected lock hash algorithm: {algorithm}")
                refs.append(
                    {
                        "type": "distribution",
                        "url": artifact["url"],
                        "hashes": [{"alg": "SHA-256", "content": digest}],
                    }
                )
        if refs:
            component["externalReferences"] = refs
        components[purl] = component
    for location, package in sorted(npm["packages"].items()):
        if not location:
            continue
        name = package.get("name") or location.rsplit("node_modules/", 1)[-1]
        version = package["version"]
        purl = f"pkg:npm/{quote(name, safe='/')}@{quote(version, safe='')}"
        records.append(
            {
                "ecosystem": "npm",
                "name": name,
                "version": version,
                "location": location,
                "resolved": package.get("resolved"),
                "integrity": package.get("integrity"),
                "license": package.get("license"),
                "dev": package.get("dev", False),
            }
        )
        components[purl] = {
            "type": "library",
            "bom-ref": purl,
            "purl": purl,
            "name": name,
            "version": version,
            "properties": [{"name": "relay:inventory-scope", "value": "package-lock.json union"}],
        }
    note = (
        "All Python and npm lock entries, including development and platform alternatives. "
        "Not the resolved runtime dependency graph, license clearance, or OS image SBOM."
    )
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": project["name"],
                "version": project["version"],
            },
            "properties": [{"name": "relay:limitations", "value": note}],
        },
        "components": [components[key] for key in sorted(components)],
    }
    return {"scope": note, "packages": records}, sbom


def build(root: Path, output: Path, epoch: int, uv: str) -> None:
    # Missing UI/locks must fail before touching static/output.
    manifest = inspect_web(root / "web/dist")
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = config["build-system"]["requires"]
    if not requirements or any("==" not in requirement for requirement in requirements):
        raise ValueError("Pin every build-system requirement with == before building a release")
    inventory, sbom = inventories(root, config["project"])
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"Output must be an empty directory: {output}")
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch), PYTHONHASHSEED="0")
    subprocess.run([uv, "lock", "--check"], cwd=root, env=env, check=True)
    static = root / "src/relay/static"
    if static.is_symlink():
        raise ValueError("Refusing to replace a symlink at src/relay/static")
    if static.exists():
        shutil.rmtree(static)
    shutil.copytree(root / "web/dist", static)
    if inspect_web(static) != manifest:
        raise ValueError("Dashboard changed during copying; rebuild from an idle checkout")
    for path in static.rglob("*"):
        if path.is_file():
            path.chmod(0o644)
            os.utime(path, (epoch, epoch))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".release-", dir=output.parent) as temporary:
        staging = Path(temporary)
        subprocess.run(
            [uv, "build", "--wheel", "--out-dir", str(staging)], cwd=root, env=env, check=True
        )
        wheels = list(staging.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError(f"Expected one wheel, got {len(wheels)}")
        with zipfile.ZipFile(wheels[0]) as wheel:
            bundled = {
                name.removeprefix("relay/static/"): hashlib.sha256(wheel.read(name)).hexdigest()
                for name in wheel.namelist()
                if name.startswith("relay/static/") and not name.endswith("/")
            }
            if bundled != manifest:
                raise ValueError("Wheel dashboard contents differ from web/dist")
            if "relay/storage/migrations/0001_initial.sql" not in wheel.namelist():
                raise ValueError("Wheel is missing required migration SQL")
        write_json(staging / "dependency-inventory.json", inventory)
        write_json(staging / "sbom.cdx.json", sbom)
        write_json(
            staging / "build-inputs.json",
            {
                "source_date_epoch": epoch,
                "dashboard": manifest,
                "inputs": {
                    name: sha256(root / name)
                    for name in ("pyproject.toml", "uv.lock", "web/package-lock.json")
                },
                "python": sys.version.split()[0],
                "uv": subprocess.check_output([uv, "--version"], text=True).strip(),
                "note": "Pin OS/Python/Node/npm/uv; compare independent builds before release.",
            },
        )
        sums = "".join(f"{sha256(p)}  {p.name}\n" for p in sorted(staging.iterdir()))
        (staging / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
        output.mkdir(exist_ok=True)
        for path in staging.iterdir():
            shutil.move(str(path), output / path.name)
    print(f"Built and verified local release bundle: {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist",
        help="Empty artifact directory (default: relay/dist)",
    )
    parser.add_argument(
        "--source-date-epoch",
        type=int,
        default=os.environ.get("SOURCE_DATE_EPOCH", "946684800"),
        help="Stable ZIP timestamp, default 2000-01-01 UTC",
    )
    parser.add_argument("--uv", default="uv", help="uv executable path")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only dashboard and inventory preflight; does not build",
    )
    args = parser.parse_args()
    try:
        if not 315532800 <= args.source_date_epoch <= 4354819198:
            raise ValueError("SOURCE_DATE_EPOCH must fit ZIP timestamps (1980 through 2107)")
        if args.check:
            manifest = inspect_web(ROOT / "web/dist")
            project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
            inventory, _ = inventories(ROOT, project)
            print(f"Preflight: {len(manifest)} assets; {len(inventory['packages'])} lock entries")
        else:
            build(ROOT, args.output.resolve(), args.source_date_epoch, args.uv)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Release build FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
