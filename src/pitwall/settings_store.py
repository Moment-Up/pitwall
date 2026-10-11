"""Runtime-editable settings and secrets, persisted under the data directory.

``Settings`` (config.py) is the deploy-time configuration (environment / ``.env``), read once at start-up. Things
the user changes from the dashboard - rig hardware, game integrations, the AI provider - live here instead, so
they survive restarts without editing files and take effect without a restart.

- ``SettingsStore``: ``data/settings.json``, one JSON object per *section* (``"rig"``, ``"llm"``, ...). Each
  section is owned and validated by one module; the store only persists, versions and notifies.
- ``SecretStore``: ``data/secrets.json`` with mode 0600, for API keys. Values are never returned by the API: use
  ``masked()`` for display. An environment variable ``PITWALL_<NAME>`` (upper case) always wins, so deployments can
  keep keys out of the file entirely. Windows has no mode bits: there the file is private only when the data
  folder's ACL is private (``scripts/windows/install.ps1`` sets it; ``pitwall doctor`` warns when other accounts
  can read the folder, e.g. a repository cloned to ``C:\\pitwall`` that inherits the drive root's access).

Both are thread-safe (API handlers, the ingest thread and workers may read concurrently) and write atomically
(temp file + rename), so a crash mid-write never leaves a truncated file.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pitwall.compat import replace_file, set_private_mode

log = logging.getLogger(__name__)

Listener = Callable[[str, dict[str, Any]], None]


def _atomic_write_json(path: Path, data: Mapping[str, Any], mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        set_private_mode(fd, mode)  # os.fchmod; no-op on Windows (no mode bits; Python 3.12 has no os.fchmod there)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        replace_file(Path(tmp), path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Keep the unreadable file for inspection instead of silently overwriting the user's settings.
        backup = path.with_suffix(path.suffix + ".corrupt")
        replace_file(path, backup)
        log.error("unreadable %s moved to %s; starting from defaults", path, backup)
        return {}
    return data if isinstance(data, dict) else {}


class SettingsStore:
    """Sectioned JSON settings. Sections are plain JSON objects; the owning module validates them."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, dict[str, Any]] = {k: v for k, v in _load_json(path).items() if isinstance(v, dict)}
        self._listeners: dict[str, list[Listener]] = {}

    def get(self, section: str) -> dict[str, Any]:
        """A deep copy of the section (empty if never written). Mutating it does not change the store."""
        with self._lock:
            return copy.deepcopy(self._data.get(section, {}))

    def sections(self) -> list[str]:
        with self._lock:
            return sorted(self._data)

    def update(self, section: str, values: Mapping[str, Any]) -> dict[str, Any]:
        """Shallow-merge ``values`` into the section; a value of ``None`` deletes that key. Returns the new section."""
        with self._lock:
            cur = dict(self._data.get(section, {}))
            for k, v in values.items():
                if v is None:
                    cur.pop(k, None)
                else:
                    cur[k] = copy.deepcopy(v)
            return self._commit(section, cur)

    def replace(self, section: str, values: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._commit(section, copy.deepcopy(dict(values)))

    def subscribe(self, section: str, listener: Listener) -> Callable[[], None]:
        """Call ``listener(section, new_values)`` after every change to ``section``. Returns an unsubscribe function.

        Listeners run synchronously on the writer's thread after the file is saved; keep them cheap and
        non-blocking (hand work to your own thread or event loop if needed).
        """
        with self._lock:
            self._listeners.setdefault(section, []).append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners.get(section, []):
                    self._listeners[section].remove(listener)

        return unsubscribe

    def _commit(self, section: str, values: dict[str, Any]) -> dict[str, Any]:
        json.dumps(values)  # fail before touching disk if a caller passed something unserialisable
        new = {**self._data, section: values}
        _atomic_write_json(self.path, new, 0o600)
        self._data = new
        snapshot = copy.deepcopy(values)
        for listener in list(self._listeners.get(section, [])):
            try:
                listener(section, copy.deepcopy(snapshot))
            except Exception:
                log.exception("settings listener for %r failed", section)
        return snapshot


def mask_secret(value: str) -> str:
    """Show enough to recognise a key without revealing it: ``sk-ant-…a1b2``."""
    if len(value) <= 8:
        return "•" * len(value)
    head = value[: min(7, len(value) // 4)]
    return f"{head}…{value[-4:]}"


class SecretStore:
    """API keys and other credentials. File mode 0600; environment variables override the file."""

    ENV_PREFIX = "PITWALL_"

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, str] = {k: v for k, v in _load_json(path).items() if isinstance(v, str)}
        if path.exists():
            path.chmod(0o600)

    @classmethod
    def env_name(cls, name: str) -> str:
        return cls.ENV_PREFIX + name.upper()

    def get(self, name: str) -> str | None:
        env = os.environ.get(self.env_name(name))
        if env:
            return env
        with self._lock:
            return self._data.get(name)

    def source(self, name: str) -> str | None:
        """Where the active value comes from: ``"env"``, ``"file"`` or ``None`` (not set)."""
        if os.environ.get(self.env_name(name)):
            return "env"
        with self._lock:
            return "file" if name in self._data else None

    def set(self, name: str, value: str | None) -> None:
        """Store (or with ``None``/empty, delete) a secret. Never logs the value."""
        with self._lock:
            new = dict(self._data)
            if value:
                new[name] = value.strip()
            else:
                new.pop(name, None)
            _atomic_write_json(self.path, new, 0o600)
            self._data = new
        log.info("secret %r %s", name, "updated" if value else "removed")

    def masked(self) -> dict[str, dict[str, str | None]]:
        """``{name: {"masked": "sk-…abcd", "source": "file"|"env"}}`` for every secret that is set."""
        with self._lock:
            names = set(self._data)
        names |= {
            k[len(self.ENV_PREFIX) :].lower()
            for k, v in os.environ.items()
            if k.startswith(self.ENV_PREFIX) and k.endswith(("_API_KEY", "_TOKEN_SECRET")) and v
        }
        out: dict[str, dict[str, str | None]] = {}
        for n in sorted(names):
            v = self.get(n)
            if v:
                out[n] = {"masked": mask_secret(v), "source": self.source(n)}
        return out
