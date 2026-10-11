"""The install home: ``install.json``, the shared lock, ``.env`` editing and disk space.

``install.json`` (schema 1) is written atomically (temporary file + ``os.replace``) by the installers' Python half
and ``pitwall update`` only. The lock is a folder (``mkdir`` is atomic everywhere), shared with install.sh and
install.ps1; one older than two hours is stale (a crashed run) and is taken over.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, Literal

from pitwall.install.versions import is_valid_tag, parse_version

INSTALL_JSON = "install.json"
LOCK_DIR = ".install.lock"
READY_MARKER = ".pitwall-ready"
LOCK_STALE_S = 2 * 3600
MIN_FREE_BYTES = 2 * 1024**3
ServiceKind = Literal["launchd", "task", "none"]

# Exit codes shared by install.sh, install.ps1, `pitwall install-finish` and `pitwall update`.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2  # usage error, or unsupported (OS, git checkout, release too old)
EXIT_LIVE = 3  # telemetry live: refused
EXIT_NEEDS_USER = 4  # data conflict, unknown running server, no terminal for a question, low disk
EXIT_VERIFY = 5  # SHA-256 or zip safety check failed


class InstallError(Exception):
    """A failure with its exit code and a plain sentence for the person running the command."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def default_home() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "Pitwall"
    return Path.home() / "Pitwall"


def version_dir(home: Path, tag: str) -> Path:
    if not is_valid_tag(tag):
        raise InstallError(EXIT_USAGE, f"not a release version: {tag!r}")
    return home / f"pitwall-{tag}"


def tag_of_dir(path: Path) -> str | None:
    """``v0.2.0`` for a folder named ``pitwall-v0.2.0``."""
    name = path.name
    if not name.startswith("pitwall-"):
        return None
    tag = name[len("pitwall-") :]
    return tag if is_valid_tag(tag) else None


# ------------------------------------------------------------------------------------------- install.json
@dataclass(slots=True)
class InstallState:
    home: str
    data_dir: str
    current: str
    previous: str | None = None
    staged: str | None = None
    versions: list[str] = field(default_factory=list)
    service: ServiceKind = "none"
    installed_by: str = "pitwall update"
    updated_unix: float = 0.0
    schema: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "home": self.home,
            "data_dir": self.data_dir,
            "current": self.current,
            "previous": self.previous,
            "staged": self.staged,
            "versions": list(self.versions),
            "service": self.service,
            "installed_by": self.installed_by,
            "updated_unix": self.updated_unix,
        }

    @classmethod
    def from_dict(cls, d: Any) -> InstallState | None:
        if not isinstance(d, dict) or d.get("schema") != 1:
            return None
        current = d.get("current")
        if not isinstance(current, str) or not is_valid_tag(current):
            return None

        def tag(v: Any) -> str | None:
            return v if isinstance(v, str) and is_valid_tag(v) else None

        service = d.get("service")
        versions = [v for v in (d.get("versions") or []) if isinstance(v, str) and is_valid_tag(v)]
        return cls(
            home=str(d.get("home") or ""),
            data_dir=str(d.get("data_dir") or ""),
            current=current,
            previous=tag(d.get("previous")),
            staged=tag(d.get("staged")),
            versions=sort_tags(versions),
            service=service if service in ("launchd", "task", "none") else "none",
            installed_by=str(d.get("installed_by") or ""),
            updated_unix=float(d.get("updated_unix") or 0.0),
        )


def sort_tags(tags: list[str]) -> list[str]:
    parsed = {t: parse_version(t) for t in set(tags)}
    return sorted((t for t, v in parsed.items() if v is not None), key=lambda t: parsed[t].key())  # type: ignore[union-attr]


def load_state(home: Path) -> InstallState | None:
    try:
        raw = (home / INSTALL_JSON).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return InstallState.from_dict(json.loads(raw))
    except ValueError:
        return None


def write_json_atomic(path: Path, data: Any) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def save_state(home: Path, state: InstallState) -> None:
    state.versions = sort_tags(state.versions)
    write_json_atomic(home / INSTALL_JSON, state.to_dict())


# ------------------------------------------------------------------------------------------- lock
@contextlib.contextmanager
def install_lock(home: Path, *, stale_s: float = LOCK_STALE_S) -> Iterator[Path]:
    """Hold ``<home>/.install.lock`` (a folder) for the duration. A lock older than ``stale_s`` is taken over."""
    lock = home / LOCK_DIR
    home.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            lock.mkdir()
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0.0
            if attempt == 0 and age > stale_s:
                shutil.rmtree(lock, ignore_errors=True)
                continue
            raise InstallError(
                EXIT_NEEDS_USER,
                f"another Pitwall install or update is running ({lock} exists). If none is, delete that folder "
                "and try again.",
            ) from None
    try:
        with contextlib.suppress(OSError):
            (lock / "owner").write_text(f"python {os.getpid()}\n", encoding="utf-8")
        yield lock
    finally:
        shutil.rmtree(lock, ignore_errors=True)


# ------------------------------------------------------------------------------------------- disk
def free_bytes(path: Path) -> int:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


# ------------------------------------------------------------------------------------------- .env
_ENV_LINE_RE = re.compile(r"^(\s*)(export\s+)?([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\r?)$")
DATA_KEY = "PITWALL_DATA_DIR"


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] in "\"'":
        end = raw.find(raw[0], 1)
        if end > 0:
            return raw[1:end]
    hash_at = raw.find(" #")
    return (raw[:hash_at] if hash_at >= 0 else raw).strip()


def read_env_value(path: Path, name: str) -> str | None:
    """The last ``NAME=value`` in a .env file (``export`` prefix, quotes and `` #`` comments handled; names match
    without regard to case, like the server's settings). ``None`` when absent or unreadable."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    value: str | None = None
    for line in text.splitlines():
        m = _ENV_LINE_RE.match(line)
        if m and m.group(3).upper() == name.upper():
            value = _unquote(m.group(5))
    return value


def env_port(path: Path, default: int = 8770) -> int:
    raw = os.environ.get("PITWALL_HTTP_PORT") or read_env_value(path, "PITWALL_HTTP_PORT")
    try:
        port = int(str(raw).strip()) if raw else default
    except ValueError:
        return default
    return port if 0 < port < 65536 else default


def is_anchored(path: PurePath) -> bool:
    """Absolute, or rooted on Windows (``\\data`` or ``/data``: on the current drive). Either way it does not
    depend on the folder Pitwall starts in, so an update must keep it rather than rewrite it."""
    return path.is_absolute() or bool(path.root)


def managed_env_text(data_dir: Path, date: str) -> str:
    return (
        f"# Written by the Pitwall installer on {date}. Add your settings below (see .env.example).\n"
        f"{DATA_KEY}={data_dir}\n"
    )


@dataclass(slots=True)
class EnvEdit:
    text: str
    changed: bool
    note: str  # what happened, without any value from the file


def ensure_data_dir_line(text: str, data_dir: Path, *, base: Path | None, rewrite_relative: bool, date: str) -> EnvEdit:
    """Make the .env text name exactly one ``PITWALL_DATA_DIR``:

    - none: append ``PITWALL_DATA_DIR=<data_dir>`` with a comment;
    - absolute: kept as it is;
    - relative (to ``base``, the folder the file came from): rewritten to ``data_dir`` with a comment line saying
      so, when ``rewrite_relative`` (a relative path would resolve inside the new version folder, not to the data);
    - more than one line: the earlier ones are commented out (the last one wins, as it does for the server).

    Comments, quotes, ``export`` prefixes and the file's line endings (CRLF or LF) are kept. The returned note
    never contains a value from the file.
    """
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    idx = [i for i, ln in enumerate(lines) if (m := _ENV_LINE_RE.match(ln)) and m.group(3).upper() == DATA_KEY]
    notes: list[str] = []
    changed = False
    for i in idx[:-1]:
        lines[i] = f"# disabled by the Pitwall installer on {date} (a later line sets it): {lines[i]}"
        changed = True
        notes.append("an earlier duplicate PITWALL_DATA_DIR line was commented out")
    if not idx:
        lines += [
            f"# Added by the Pitwall installer on {date}: where your sessions and settings live.",
            f"{DATA_KEY}={data_dir}",
        ]
        changed = True
        notes.append("PITWALL_DATA_DIR was added")
    else:
        i = idx[-1]
        m = _ENV_LINE_RE.match(lines[i])
        assert m is not None
        value = _unquote(m.group(5))
        if not is_anchored(Path(value).expanduser()) and rewrite_relative:
            where = f" (relative to {base})" if base is not None else ""
            lines[i : i + 1] = [
                f"# Rewritten by the Pitwall installer on {date}: this line said {value!r}{where}; the data folder "
                f"is now {data_dir}.",
                f"{m.group(1)}{m.group(2) or ''}{DATA_KEY}{m.group(4)}{data_dir}",
            ]
            changed = True
            notes.append("a relative PITWALL_DATA_DIR was rewritten to the absolute data folder")
        else:
            notes.append("PITWALL_DATA_DIR kept as it was")
    return EnvEdit(eol.join(lines) + eol, changed, "; ".join(notes))


def write_private_text(path: Path, data: bytes) -> None:
    """Write ``data`` byte for byte with mode 0600 (POSIX), atomically. ``O_BINARY`` on Windows: ``os.open`` is in
    text mode there by default, which would turn every LF into CRLF (and CRLF into CR CR LF)."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        view = memoryview(data)
        while view:  # os.write may write less than asked
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    finally:
        os.close(fd)
    if sys.platform != "win32":
        tmp.chmod(0o600)
    tmp.replace(path)
