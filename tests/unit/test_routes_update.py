"""``/api/update``: TestClient with a fake fetcher (no network); handlers are fast and never touch ingest."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import pitwall.api.app as app_module
from pitwall.config import Settings
from pitwall.install.check import UpdateChecker
from pitwall.install.github import ReleaseInfo


def _release(tag: str) -> ReleaseInfo:
    r = ReleaseInfo.from_dict({"version": tag, "published_at": "2026-10-12T09:00:00Z", "notes": ["New"]})
    assert r is not None
    return r


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[int]:
    made: list[int] = []

    def fetcher() -> list[ReleaseInfo]:
        made.append(1)
        return [_release("v99.0.0"), _release("v0.1.0")]

    original = UpdateChecker.__init__

    def init(self: UpdateChecker, data_dir: Path, mode: str, root: Path, **kw: Any) -> None:
        original(self, data_dir, mode, root, fetcher=fetcher)

    monkeypatch.setattr(UpdateChecker, "__init__", init)
    monkeypatch.setattr(app_module, "WEB_REACT_DIST", tmp_path / "no-react")
    monkeypatch.setattr(app_module, "WEB_DIST", tmp_path / "no-svelte")
    return made


def client(tmp_path: Path, mode: str) -> TestClient:
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path / "data",
        llm_enabled=False,
        voice_enabled=False,
        update_check=mode,
    )
    return TestClient(app_module.create_app(s, start_udp=False), client=("127.0.0.1", 40000))


def wait_checked(c: TestClient) -> dict[str, Any]:
    for _ in range(100):
        st = c.get("/api/update").json()
        if not st["checking"] and st["checked_unix"] is not None:
            return st
        time.sleep(0.02)
    raise AssertionError("the background check never finished")


def test_auto_mode_refreshes_in_the_background(tmp_path: Path, calls: list[int]) -> None:
    with client(tmp_path, "auto") as c:
        t0 = time.perf_counter()
        first = c.get("/api/update")
        assert (time.perf_counter() - t0) < 0.5
        assert first.status_code == 200 and first.json()["mode"] == "auto"
        st = wait_checked(c)
        assert st["update_available"] is True and st["latest"]["version"] == "v99.0.0"
        assert calls == [1]
        c.get("/api/update")
        assert calls == [1]  # fresh: no second check
        assert (tmp_path / "data" / "update_check.json").is_file()


def test_manual_mode_checks_only_when_asked_and_rate_limits(tmp_path: Path, calls: list[int]) -> None:
    with client(tmp_path, "manual") as c:
        st = c.get("/api/update").json()
        assert st["update_available"] is None and calls == []
        r = c.post("/api/update/check", json={})
        assert r.status_code == 200
        wait_checked(c)
        assert calls == [1]
        again = c.post("/api/update/check", json={})
        assert again.status_code == 200 and not again.json()["checking"]
        assert calls == [1]  # finished less than 60 s ago: the current status, no new check
        assert c.post("/api/update/check", content=b"{}").status_code == 415  # JSON only (no CORS-simple POSTs)
        assert c.post("/api/update/check", json={"x": 1}).status_code == 422


def test_off_mode_never_contacts_github(tmp_path: Path, calls: list[int]) -> None:
    with client(tmp_path, "off") as c:
        st = c.get("/api/update").json()
        assert st["mode"] == "off" and st["update_available"] is None
        r = c.post("/api/update/check", json={})
        assert r.status_code == 409 and r.json() == {"detail": "Update checks are off (PITWALL_UPDATE_CHECK=off)."}
        time.sleep(0.05)
    assert calls == []


def test_no_auto_check_while_telemetry_is_live(tmp_path: Path, calls: list[int]) -> None:
    """The real runtime: a packet just arrived (connection "live"), so the automatic check waits."""
    with client(tmp_path, "auto") as c:
        live = c.app.state.runtime.live  # type: ignore[attr-defined]
        live.last_packet_mono = time.monotonic()
        assert c.get("/api/health").json()["connection"]["status"] == "live"
        assert c.get("/api/update").json()["checking"] is False
        time.sleep(0.05)
        assert calls == []
        live.last_packet_mono = time.monotonic() - 10  # stale: the check may run now
        c.get("/api/update")
        wait_checked(c)
    assert calls == [1]


def test_running_version_never_contacts_github(tmp_path: Path, calls: list[int]) -> None:
    """``pitwall install-finish`` polls this after a switch: the running version, no check started."""
    with client(tmp_path, "auto") as c:
        r = c.get("/api/update/version")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"current", "install_kind"} and body["current"].startswith("v")
        time.sleep(0.05)
    assert calls == []


def test_lan_devices_need_the_token(tmp_path: Path, calls: list[int]) -> None:
    s = Settings(_env_file=None, data_dir=tmp_path / "data", llm_enabled=False, voice_enabled=False)  # type: ignore[call-arg]
    with TestClient(app_module.create_app(s, start_udp=False), client=("192.168.1.30", 40000)) as c:
        assert c.get("/api/update").status_code == 401
