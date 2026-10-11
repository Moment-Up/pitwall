"""Update status: the ``<data_dir>/update_check.json`` cache and the ``UpdateStatus`` JSON contract.

``PITWALL_UPDATE_CHECK``:

- ``auto`` (default): ``GET /api/update`` refreshes the cache in the background when the last successful check is
  more than 24 h old, the last attempt more than 10 min ago, and nobody is driving (telemetry not live);
- ``manual``: only Settings > System's "Check now" (``POST /api/update/check``) or ``pitwall update --check``;
- ``off``: the server never contacts GitHub (the CLI still does when someone runs it).

The status is computed when it is read, against the running version, so it is right straight after an update. The
dashboard's TypeScript contract is ``web-react/src/lib/endpoints/update.ts`` (``UpdateStatus``).
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pitwall.install.github import CACHED_RELEASES, DOCS_URL, ReleaseError, ReleaseInfo, fetch_releases
from pitwall.install.layout import write_json_atomic
from pitwall.install.versions import InstallKind, current_version, install_kind, parse_version

CACHE_NAME = "update_check.json"
STALE_S = 24 * 3600.0
RETRY_S = 600.0
RATE_LIMIT_S = 60.0
MAX_NEWER = 5
MODES = ("auto", "manual", "off")


@dataclass(slots=True)
class CheckCache:
    checked_unix: float | None = None  # the last attempt
    ok_unix: float | None = None  # the last successful check
    error: str | None = None
    releases: list[ReleaseInfo] = field(default_factory=list)
    schema: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "checked_unix": self.checked_unix,
            "ok_unix": self.ok_unix,
            "error": self.error,
            "releases": [r.to_dict() for r in self.releases[:CACHED_RELEASES]],
        }

    @classmethod
    def from_dict(cls, d: Any) -> CheckCache:
        if not isinstance(d, dict) or d.get("schema") != 1:
            return cls()

        def num(v: Any) -> float | None:
            return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

        releases = [r for r in (ReleaseInfo.from_dict(x) for x in (d.get("releases") or [])) if r is not None]
        err = d.get("error")
        return cls(num(d.get("checked_unix")), num(d.get("ok_unix")), err if isinstance(err, str) else None, releases)


def cache_path(data_dir: Path) -> Path:
    return data_dir / CACHE_NAME


def read_cache(data_dir: Path) -> CheckCache:
    import json

    try:
        return CheckCache.from_dict(json.loads(cache_path(data_dir).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return CheckCache()


def write_cache(data_dir: Path, cache: CheckCache) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(cache_path(data_dir), cache.to_dict())


def run_check(data_dir: Path, fetcher: Callable[[], list[ReleaseInfo]], now: float | None = None) -> CheckCache:
    """Fetch the releases and write the cache (also when the check fails: the attempt and its error)."""
    old = read_cache(data_dir)
    t = time.time() if now is None else now
    try:
        releases = fetcher()
    except ReleaseError as e:
        cache = CheckCache(t, old.ok_unix, str(e), old.releases)
    except Exception as e:  # never let a check crash a request handler or the CLI
        cache = CheckCache(t, old.ok_unix, f"Couldn't check for updates ({type(e).__name__}).", old.releases)
    else:
        cache = CheckCache(t, t, None, releases[:CACHED_RELEASES])
    write_cache(data_dir, cache)
    return cache


def how_to_update(kind: InstallKind, root: Path, platform: str = sys.platform) -> dict[str, Any] | None:
    if kind == "git":
        return {"command": "git pull", "folder": str(root), "docs_url": DOCS_URL}
    if kind in ("managed", "release"):
        sep = "; " if platform == "win32" else " && "
        return {"command": f'cd "{root}"{sep}uv run pitwall update', "folder": str(root), "docs_url": DOCS_URL}
    return None


def compute_status(
    cache: CheckCache,
    *,
    current: str,
    kind: InstallKind,
    mode: str,
    root: Path,
    checking: bool = False,
    hide_when_off: bool = True,
    platform: str = sys.platform,
) -> dict[str, Any]:
    """The ``UpdateStatus`` JSON (web-react/src/lib/endpoints/update.ts). Pre-releases count only when the running
    version is itself a pre-release."""
    cur = parse_version(current)
    off = mode == "off" and hide_when_off
    failed = cache.error is not None
    allow_pre = cur is not None and cur.is_pre
    rs = [r for r in cache.releases if allow_pre or not r.prerelease]
    rs.sort(key=lambda r: r.parsed.key(), reverse=True)
    known = not off and not failed and cache.ok_unix is not None
    latest = rs[0] if known and rs else None
    newer = [r for r in rs if cur is None or r.parsed > cur] if known else []
    update_available: bool | None = None
    if known:
        update_available = bool(newer)
    return {
        "schema": 1,
        "current": current,
        "install_kind": kind,
        "mode": mode if mode in MODES else "auto",
        "checked_unix": None if off else cache.checked_unix,
        "checking": checking,
        "update_available": update_available,
        "latest": latest.to_dict() if latest else None,
        "newer": [r.to_dict() for r in newer[:MAX_NEWER]],
        "error": None if off else cache.error,
        "how": how_to_update(kind, root, platform),
    }


class UpdateChecker:
    """Single-flight checks for the API: one at a time, at most one a minute, never while telemetry is live in
    ``auto`` mode. The fetch runs in a worker thread (``asyncio.to_thread``); handlers only read memory and stat
    one small file."""

    def __init__(
        self,
        data_dir: Path,
        mode: str,
        root: Path,
        fetcher: Callable[[], list[ReleaseInfo]] = fetch_releases,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.data_dir = data_dir
        self.mode = mode if mode in MODES else "auto"
        self.root = root
        self.fetcher = fetcher
        self.clock = clock
        self._lock = threading.Lock()
        self._running = False
        self._finished: float | None = None
        self._cache: CheckCache | None = None
        self._cache_mtime: float | None = None
        self.kind: InstallKind = install_kind(root)
        self.current = current_version(root)

    @property
    def checking(self) -> bool:
        return self._running

    def cache(self) -> CheckCache:
        """The cache file, re-read only when it changed (``pitwall update --check`` may write it)."""
        p = cache_path(self.data_dir)
        try:
            mtime: float | None = p.stat().st_mtime
        except OSError:
            mtime = None
        if self._cache is None or mtime != self._cache_mtime:
            self._cache = read_cache(self.data_dir) if mtime is not None else CheckCache()
            self._cache_mtime = mtime
        return self._cache

    def status(self) -> dict[str, Any]:
        return compute_status(
            self.cache(), current=self.current, kind=self.kind, mode=self.mode, root=self.root, checking=self._running
        )

    def wants_auto_refresh(self, live: bool) -> bool:
        if self.mode != "auto" or live or self._running:
            return False
        c = self.cache()
        now = self.clock()
        stale = c.ok_unix is None or now - c.ok_unix > STALE_S
        retry_ok = c.checked_unix is None or now - c.checked_unix > RETRY_S
        return stale and retry_ok

    def recently_finished(self) -> bool:
        return self._finished is not None and self.clock() - self._finished < RATE_LIMIT_S

    def try_begin(self) -> bool:
        """Claim the single check slot (False: one is running)."""
        with self._lock:
            if self._running:
                return False
            self._running = True
            return True

    def run_claimed(self) -> None:
        """Run the check claimed with ``try_begin`` (blocking: call it in a worker thread)."""
        try:
            run_check(self.data_dir, self.fetcher, self.clock())
        finally:
            with self._lock:
                self._running = False
                self._finished = self.clock()
            self._cache = None  # re-read on the next status
