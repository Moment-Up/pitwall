"""The update-status cache and the ``UpdateStatus`` contract (web-react/src/lib/endpoints/update.ts)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pitwall.install.check import (
    CheckCache,
    UpdateChecker,
    compute_status,
    read_cache,
    run_check,
)
from pitwall.install.github import ReleaseError, ReleaseInfo

ROOT = Path(__file__).resolve().parents[2]
TS_CONTRACT = ROOT / "web-react" / "src" / "lib" / "endpoints" / "update.ts"
STATUS_KEYS = {
    "schema", "current", "install_kind", "mode", "checked_unix", "checking", "update_available", "latest", "newer",
    "error", "how",
}  # fmt: skip
RELEASE_KEYS = {"version", "published_at", "url", "prerelease", "notes"}


def info(tag: str, notes: list[str] | None = None) -> ReleaseInfo:
    r = ReleaseInfo.from_dict({"version": tag, "published_at": "2026-10-12T09:00:00Z", "notes": notes or ["x"]})
    assert r is not None
    return r


RELEASES = [info("v0.4.0-rc.1"), info("v0.3.0"), info("v0.2.0"), info("v0.1.0")]


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def checker(
    tmp_path: Path, mode: str = "auto", fetch: list[ReleaseInfo] | Exception = RELEASES, **kw: object
) -> UpdateChecker:
    root = tmp_path / "Pitwall" / "pitwall-v0.2.0"
    root.mkdir(parents=True, exist_ok=True)
    (root / "RELEASE.txt").write_text("Pitwall v0.2.0\n", encoding="utf-8")
    calls: list[int] = []

    def fetcher() -> list[ReleaseInfo]:
        calls.append(1)
        if isinstance(fetch, Exception):
            raise fetch
        return list(fetch)

    c = UpdateChecker(tmp_path / "data", mode, root, fetcher=fetcher, **kw)  # type: ignore[arg-type]
    c.calls = calls  # type: ignore[attr-defined]
    return c


def test_status_keys_match_the_typescript_contract(tmp_path: Path) -> None:
    c = checker(tmp_path)
    run_check(c.data_dir, c.fetcher, 1000.0)
    st = c.status()
    assert set(st) == STATUS_KEYS
    assert st["schema"] == 1 and st["current"] == "v0.2.0" and st["install_kind"] == "release" and st["mode"] == "auto"
    assert st["update_available"] is True and st["latest"]["version"] == "v0.3.0"  # stable: no rc for a stable install
    assert [r["version"] for r in st["newer"]] == ["v0.3.0"]
    assert set(st["latest"]) == RELEASE_KEYS and st["checked_unix"] == 1000.0 and st["error"] is None
    assert st["how"]["command"].endswith("uv run pitwall update") and st["how"]["docs_url"].endswith("#updating")
    json.dumps(st)  # serialisable
    if TS_CONTRACT.exists():  # the dashboard lane's file: every key the backend sends is declared there
        ts = TS_CONTRACT.read_text(encoding="utf-8")
        for key in STATUS_KEYS | RELEASE_KEYS | {"command", "folder", "docs_url"}:
            assert re.search(rf"\b{key}\??:", ts), key


def test_never_checked_failed_and_off(tmp_path: Path) -> None:
    c = checker(tmp_path)
    st = c.status()
    assert st["update_available"] is None and st["checked_unix"] is None and st["latest"] is None
    c2 = checker(tmp_path, fetch=ReleaseError("Couldn't reach GitHub (timed out)."))
    run_check(c2.data_dir, c2.fetcher, 2000.0)
    st = c2.status()
    assert st["update_available"] is None and st["error"] == "Couldn't reach GitHub (timed out)." and st["newer"] == []
    off = compute_status(read_cache(c2.data_dir), current="v0.2.0", kind="managed", mode="off", root=tmp_path)
    assert (
        off["mode"] == "off"
        and off["update_available"] is None
        and off["error"] is None
        and off["checked_unix"] is None
    )


def test_a_failed_check_keeps_the_last_good_releases(tmp_path: Path) -> None:
    c = checker(tmp_path)
    run_check(c.data_dir, c.fetcher, 1000.0)
    run_check(c.data_dir, lambda: (_ for _ in ()).throw(RuntimeError("boom")), 2000.0)
    cache = read_cache(c.data_dir)
    assert cache.ok_unix == 1000.0 and cache.checked_unix == 2000.0 and cache.error and len(cache.releases) == 4


def test_status_is_recomputed_after_an_update(tmp_path: Path) -> None:
    c = checker(tmp_path)
    run_check(c.data_dir, c.fetcher, 1000.0)
    cache = read_cache(c.data_dir)
    after = compute_status(cache, current="v0.3.0", kind="managed", mode="auto", root=tmp_path)
    assert after["update_available"] is False and after["latest"]["version"] == "v0.3.0" and after["newer"] == []
    pre = compute_status(cache, current="v0.3.1-rc.1", kind="managed", mode="auto", root=tmp_path)
    assert pre["latest"]["version"] == "v0.4.0-rc.1" and pre["update_available"] is True  # a pre-release user sees rcs


def test_how_to_update_per_kind(tmp_path: Path) -> None:
    cache = CheckCache()
    win = compute_status(
        cache, current="v0.2.0", kind="managed", mode="auto", root=Path("C:/P/pitwall-v0.2.0"), platform="win32"
    )
    assert win["how"]["command"] == 'cd "C:/P/pitwall-v0.2.0"; uv run pitwall update'
    git = compute_status(cache, current="v0.1.0", kind="git", mode="auto", root=tmp_path)
    assert git["how"]["command"] == "git pull"
    assert compute_status(cache, current="v0.1.0", kind="unknown", mode="auto", root=tmp_path)["how"] is None


def test_auto_refresh_only_when_stale_idle_and_not_retried_recently(tmp_path: Path) -> None:
    clock = Clock()
    c = checker(tmp_path, clock=clock)
    assert c.wants_auto_refresh(live=False)
    assert not c.wants_auto_refresh(live=True)  # never while someone is driving
    assert c.try_begin() and not c.try_begin()  # single flight
    c.run_claimed()
    assert c.calls == [1] and not c.checking  # type: ignore[attr-defined]
    assert not c.wants_auto_refresh(live=False)  # fresh
    clock.t += 23 * 3600
    assert not c.wants_auto_refresh(live=False)
    clock.t += 2 * 3600
    assert c.wants_auto_refresh(live=False)  # older than 24 h
    # a failed attempt waits 10 min before the next automatic one
    c.fetcher = lambda: (_ for _ in ()).throw(ReleaseError("Couldn't reach GitHub (no connection)."))
    assert c.try_begin()
    c.run_claimed()
    assert not c.wants_auto_refresh(live=False)
    clock.t += 601
    assert c.wants_auto_refresh(live=False)
    assert not checker(tmp_path / "m", mode="manual").wants_auto_refresh(live=False)
    assert not checker(tmp_path / "o", mode="off").wants_auto_refresh(live=False)


def test_rate_limit_after_a_finished_check(tmp_path: Path) -> None:
    clock = Clock()
    c = checker(tmp_path, clock=clock)
    assert not c.recently_finished()
    c.try_begin()
    c.run_claimed()
    assert c.recently_finished()
    clock.t += 61
    assert not c.recently_finished()


def test_cache_file_is_reread_when_the_cli_writes_it(tmp_path: Path) -> None:
    c = checker(tmp_path)
    assert c.status()["update_available"] is None
    run_check(c.data_dir, lambda: RELEASES, 5000.0)  # e.g. `pitwall update --check` in a terminal
    assert c.status()["update_available"] is True


@pytest.mark.parametrize("bad", ["{", '{"schema": 2}', '{"schema": 1, "releases": [{"version": "../x"}, 3]}'])
def test_a_bad_cache_file_reads_as_never_checked(tmp_path: Path, bad: str) -> None:
    (tmp_path / "update_check.json").write_text(bad, encoding="utf-8")
    cache = read_cache(tmp_path)
    assert cache.releases == [] and cache.checked_unix is None


def test_pitwall_update_refreshes_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``pitwall update`` writes its own GitHub answer into the cache: an older failed check does not linger in
    Settings > System after an update, the full list is returned (a --version pin may be beyond the cached ten), and
    a failure is remembered too. No cache is created in a data folder that does not exist."""
    from pitwall.install import commands, github

    data = tmp_path / "data"
    data.mkdir()
    run_check(data, lambda: (_ for _ in ()).throw(ReleaseError("Couldn't reach GitHub (no connection).")), now=1.0)
    assert read_cache(data).error is not None
    many = [info(f"v0.{n}.0") for n in range(1, 15)]
    monkeypatch.setattr(github, "fetch_releases", lambda: list(many))
    assert len(commands.fetch_and_remember(data)) == 14
    cache = read_cache(data)
    assert cache.error is None and cache.ok_unix is not None and len(cache.releases) == 10
    st = compute_status(cache, current="v0.14.0", kind="managed", mode="manual", root=tmp_path)
    assert st["update_available"] is False and st["error"] is None

    def down() -> list[ReleaseInfo]:
        raise ReleaseError("Couldn't reach GitHub (timed out).")

    monkeypatch.setattr(github, "fetch_releases", down)
    with pytest.raises(ReleaseError, match="timed out"):
        commands.fetch_and_remember(data)
    assert read_cache(data).error == "Couldn't reach GitHub (timed out)."
    monkeypatch.setattr(github, "fetch_releases", lambda: list(many))
    missing = tmp_path / "nowhere"
    assert len(commands.fetch_and_remember(missing)) == 14 and not missing.exists()
