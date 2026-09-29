"""T24 standalone release gate, intentionally not a skipped pytest placeholder.

Run only after the lead packages the built UI:
  python tests/test_release_wheel.py --wheel dist/relay_jobs-0.1.0-py3-none-any.whl
Missing UI, migration resources, CLI, dependencies or routes FAIL the gate.
Creates an isolated venv, installs the supplied wheel and its declared dependencies
(pip may use network), then probes outside the checkout without PYTHONPATH.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import subprocess
import tempfile
import venv
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


class AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        source = values.get("src") if tag == "script" else values.get("href")
        if source and tag in ("script", "link"):
            self.assets.append(source)


def inspect_wheel(wheel: Path) -> dict[str, object]:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert "walflow/static/index.html" in names, "built UI index missing from wheel"
        assert "walflow/storage/migrations/0001_initial.sql" in names, "migration SQL missing"
        entry_file = next(n for n in names if n.endswith(".dist-info/entry_points.txt"))
        entry = configparser.ConfigParser()
        entry.read_string(archive.read(entry_file).decode())
        assert entry["console_scripts"]["walflow"].replace(" ", "") == "walflow.cli:app"
        parser = AssetParser()
        parser.feed(archive.read("walflow/static/index.html").decode("utf-8"))
        local: list[str] = []
        for source in parser.assets:
            url = urlsplit(source)
            assert not url.scheme and not url.netloc, f"external asset not self-contained: {source}"
            path = unquote(url.path).lstrip("/")
            assert ".." not in PurePosixPath(path).parts, "unsafe asset reference"
            assert f"walflow/static/{path}" in names, f"asset missing from wheel: {path}"
            local.append(path)
        assert any(p.endswith(".js") for p in local), "UI JavaScript missing"
        assert any(p.endswith(".css") for p in local), "UI stylesheet missing"
        return {"wheel": wheel.name, "assets": local, "files": len(names)}


PROBE = r"""
import importlib.resources
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from fastapi.testclient import TestClient
import walflow
from walflow.api import create_app
from walflow.storage.migrations import apply_migrations
from walflow.storage.transactions import connect
assert Path(walflow.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert (importlib.resources.files('walflow.storage.migrations') / '0001_initial.sql').is_file()
db = str(Path.cwd() / 'fresh.db')
with closing(connect(db)) as conn:
    assert apply_migrations(conn) == [1]
with closing(connect(db)) as conn:
    assert apply_migrations(conn) == []
with TestClient(create_app(db, 'release-test-token')) as client:
    root = client.get('/')
    assert root.status_code == 200, root.text
    deep = client.get('/jobs/release-probe')
    assert deep.status_code == 200 and deep.content == root.content
    for asset in json.loads(sys.argv[1]):
        response = client.get('/' + asset)
        assert response.status_code == 200 and response.content
    missing = client.get('/api/v1/not-a-route',
                         headers={'Authorization': 'Bearer release-test-token'})
    assert missing.status_code == 404
with closing(sqlite3.connect(db)) as conn:
    assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
print(json.dumps({'fresh_install': True, 'static_routes': True, 'migration_restart': True}))
"""


def run(command: list[str], cwd: Path, env: dict[str, str], timeout: int = 60) -> str:
    result = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command}\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    inspection = inspect_wheel(wheel)
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    with tempfile.TemporaryDirectory(
        prefix="release-", dir=Path(__file__).resolve().parents[1]
    ) as d:
        root = Path(d)
        target = root / "venv"
        venv.EnvBuilder(with_pip=True).create(target)
        binary = target / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        cli = binary / ("walflow.exe" if os.name == "nt" else "walflow")
        run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                str(wheel),
            ],
            root,
            env,
            timeout=180,
        )
        assert "migrate" in run([str(cli), "--help"], root, env)
        probe = run([str(python), "-I", "-c", PROBE, json.dumps(inspection["assets"])], root, env)
        print(json.dumps({"inspection": inspection, "probe": json.loads(probe)}, indent=2))


if __name__ == "__main__":
    main()
