"""Local non-roaming paths and private bearer credential storage."""

from __future__ import annotations

import os
import secrets
import stat
import subprocess
from pathlib import Path

from platformdirs import user_data_path


def data_directory() -> Path:
    override = os.environ.get("RELAY_DATA_DIR")
    return Path(override) if override else user_data_path("Relay", appauthor=False, roaming=False)


def database_path() -> Path:
    return Path(os.environ.get("RELAY_DB", str(data_directory() / "relay.db")))


def _restrict(path: Path) -> None:
    if os.name == "nt":
        # Replace inherited ACL with the current user's SID, never a display name.
        who = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"], check=True, capture_output=True, text=True
        )
        import csv

        sid = next(csv.reader([who.stdout.strip()]))[1]
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:F"],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def read_token(path: Path | None = None) -> str:
    token = os.environ.get("RELAY_TOKEN")
    if token is None:
        path = path or data_directory() / "token"
        if path.is_symlink() or not path.is_file():
            raise ValueError("restricted token file missing; run relay init")
        stats = path.stat()
        if os.name != "nt" and (stats.st_mode & 0o077 or stats.st_uid != path.parent.stat().st_uid):
            raise ValueError("token file must match the restricted data directory owner")
        if os.name == "nt":
            _restrict(path)
        if path.stat().st_size > 4096:
            raise ValueError("invalid token file")
        token = path.read_text(encoding="utf-8").strip()
    if not token or len(token) > 4096 or any(c.isspace() for c in token):
        raise ValueError("invalid Relay credential")
    return token


def initialize(directory: Path) -> Path:
    if directory.is_symlink():
        raise ValueError("data directory cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    _restrict(directory)
    token_path = directory / "token"
    if token_path.is_symlink():
        raise ValueError("token cannot be a symlink")
    if not token_path.exists():
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        try:
            _restrict(token_path)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = -1
                stream.write(secrets.token_urlsafe(32) + "\n")
        finally:
            if fd >= 0:
                os.close(fd)
    else:
        _restrict(token_path)
    return directory / "relay.db"
