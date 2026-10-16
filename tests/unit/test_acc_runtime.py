"""ACC in the running service: the reader starts only on Windows and only while ACC is enabled or selected, reports
its state on the Connect page, and a closed, idle or paused ACC never makes ``/api/health`` say "live".

The pages are ``pitwall.sim.acc_stream.FakeAccMemory`` behind the runtime's ``acc_opener`` test seam (which is
also what lets the reader run off Windows here); no real shared memory, no real game (SYNTHETIC tier). F1's UDP
listener binds a free loopback port, never 20777.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from pitwall import cli, games
from pitwall import integrations as I
from pitwall.adapters.acc import packets as P
from pitwall.api import app as app_mod
from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.ingest import acc_shm_reader as R
from pitwall.settings_store import SettingsStore
from pitwall.sim.acc_stream import AccScenario, FakeAccMemory, write_acc_capture

LIVE = int(P.AccStatus.LIVE)
OFF = int(P.AccStatus.OFF)
PAUSE = int(P.AccStatus.PAUSE)
REPLAY = int(P.AccStatus.REPLAY)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def settings_for(tmp_path: Path, **kw: Any) -> Settings:
    values: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "f1_udp_port": free_port(),
        "forza_udp_port": free_port(),
        "udp_bind": "127.0.0.1",
        "record_raw": False,
        "llm_enabled": False,
        "voice_enabled": False,
        "tailscale_trust_owner": False,
        "http_port": 8798,
    }
    values.update(kw)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def physics(pid: int) -> bytes:
    return P.PHYSICS.pack({"packetId": pid, "speedKmh": 140.0, "gas": 1.0, "gear": 5, "rpm": 7000})


def graphics(pid: int, status: int = LIVE) -> bytes:
    return P.GRAPHICS.pack({"packetId": pid, "status": status, "normalizedCarPosition": 0.5})


def static() -> bytes:
    return P.STATIC.pack(
        {"carModel": P.encode_wstring("mclaren_720s_gt3", 33), "track": P.encode_wstring("spa", 33), "sectorCount": 3}
    )


def wait_for(cond: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


def acc_row(rt: Runtime) -> dict[str, Any]:
    return next(r for r in rt.input_status() if r["key"] == "acc")


@pytest.fixture
def mem() -> FakeAccMemory:
    return FakeAccMemory()


@pytest.fixture
def rt(tmp_path: Path, mem: FakeAccMemory) -> Iterator[Runtime]:
    r = Runtime(settings_for(tmp_path))
    r.acc_opener = mem.opener
    r.start_udp()
    try:
        yield r
    finally:
        r.close()


def hurry(rt: Runtime) -> None:
    """Test speed only: poll faster and look for the pages now (the defaults are 60 Hz and every 2 s)."""
    assert rt.acc is not None
    rt.acc.reader.poll_s = 0.002
    rt.acc.reader.retry_s = 0.01
    rt.acc.reader._next_open = 0.0


def select(rt: Runtime, entry_id: str) -> None:
    rt.store.replace(games.SECTION, games.new_selection(entry_id, "dashboard").section())


# ============================================================================================== runtime
def test_reader_runs_while_acc_is_selected_or_enabled(rt: Runtime, mem: FakeAccMemory) -> None:
    row = acc_row(rt)
    assert rt.acc is None and row["reader"]["state"] == "off" and not row["active"] and not row["selected"]
    assert row["listens"] is False and row["port"] == I.ACC_NO_PORT and row["needs_console_ip"] is False
    assert row["status"] == "partial (PC)" and row["platforms"] == ["PC"] and row["supported"] is True
    select(rt, "acc:pc")
    assert rt.acc is not None
    wait_for(lambda: acc_row(rt)["reader"]["state"] == "not_running")
    row = acc_row(rt)
    assert row["selected"] and row["active"] and not row["enabled"] and row["listening"]
    assert "not running" in row["reader"]["message"] and row["error"] is None
    select(rt, "gt7:ps5")  # another game, ACC switched off: the reader stops
    assert rt.acc is None and acc_row(rt)["reader"]["state"] == "off"
    I.apply_update(rt.settings, rt.store, "acc", {"enabled": True})
    assert rt.acc is not None and acc_row(rt)["active"] and not acc_row(rt)["selected"]
    hurry(rt)
    mem.start_game()
    wait_for(lambda: acc_row(rt)["reader"]["pages_open"])
    assert mem.views_open == 3
    I.apply_update(rt.settings, rt.store, "acc", {"enabled": False})
    assert rt.acc is None and mem.views_open == 0  # stopped: our views closed, ACC's pages are untouched
    assert mem.exists(P.PHYSICS_MAPPING)


def test_a_session_is_stored_from_the_shared_memory(rt: Runtime, mem: FakeAccMemory) -> None:
    from pitwall.storage import repo

    mem.start_game()
    mem.write(physics(1), graphics(1, OFF), static())
    select(rt, "acc:pc")
    hurry(rt)
    assert rt.acc is not None
    reader = rt.acc.reader
    wait_for(lambda: reader.pages_open and reader.polls > 2)
    for pid in range(2, 40):
        mem.write(physics(pid), graphics(pid))
        n = reader.polls
        wait_for(lambda n=n: reader.polls > n + 1)
    wait_for(lambda: rt.live.session_id is not None)
    assert rt.live.session is not None and rt.live.session.game.value == "acc"
    assert rt.live.session.track_id == "acc:spa" and rt.live.connection()["source"] in (None, "acc-shm")
    row = acc_row(rt)
    assert row["reader"]["state"] == "reading" and row["decoded_s_ago"] is not None and row["received"] >= 77
    assert games.receiving(row) and games.busy(row)
    sid = rt.live.session_id
    rt.writer.flush()
    with rt.db.read() as c:
        stored = repo.get_session(c, sid) if sid else None
    assert stored is not None and stored["game"] == "acc" and stored["source"] == "acc-shm" and not stored["synthetic"]


@pytest.mark.skipif(sys.platform == "win32", reason="off Windows only")
def test_off_windows_nothing_starts_and_the_row_says_why(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    r = Runtime(settings_for(tmp_path))  # no test opener: the real platform decides
    r.start_udp()
    try:
        row = acc_row(r)
        assert row["reader"]["state"] == "not_windows" and row["supported"] is False  # even while switched off
        I.apply_update(r.settings, r.store, "acc", {"enabled": True})
        select(r, "acc:pc")
        row = acc_row(r)
        assert r.acc is None and row["active"] and row["error"] is None and not row["listening"]
        assert row["reader"]["state"] == "not_windows" and "Windows PC that runs it" in row["reader"]["message"]
        assert not [rec for rec in caplog.records if rec.levelname == "ERROR"]
    finally:
        r.close()


def test_replay_of_a_synthetic_acc_capture(tmp_path: Path) -> None:
    from pitwall.storage import repo

    path = tmp_path / "acc.pwcap"
    write_acc_capture(path, AccScenario(flying_laps=1, menu_s=0.2, cooldown_s=0.5), name="acc-replay")
    r = Runtime(settings_for(tmp_path))
    try:
        rep = r.start_replay(path, speed=None)
        assert rep.done.wait(60)
        sid = r.live.session_id
        r.worker.join()
        r.writer.flush()
        with r.db.read() as c:
            row = repo.get_session(c, sid) if sid else None
    finally:
        r.close()
    assert row is not None and row["game"] == "acc" and row["synthetic"] and row["track_id"] == "synthetic:acc-replay"
    assert row["source"] == "replay:acc.pwcap"


# ============================================================================================== API
@pytest.fixture
def client(tmp_path: Path, mem: FakeAccMemory, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    class AccRuntime(Runtime):
        def __init__(self, s: Settings) -> None:
            super().__init__(s)
            self.acc_opener = mem.opener  # the fake pages (and the reader may run off Windows)

    monkeypatch.setattr(app_mod, "Runtime", AccRuntime)
    with TestClient(app_mod.create_app(settings_for(tmp_path), start_udp=True)) as c:
        yield c


def test_health_is_never_live_from_a_closed_idle_or_paused_acc(client: TestClient, mem: FakeAccMemory) -> None:
    """ACC closed, ACC frozen on track (crashed, or closed while another app keeps its pages), in its menus, paused
    or in a replay: no snapshot reaches the router, so ``/api/health`` never says "live" and the
    never-restart-while-someone-drives guard releases. Driving (the positive control) is "live" at once."""
    rt: Runtime = client.app.state.runtime  # type: ignore[attr-defined]

    def health() -> str:
        return str(client.get("/api/health").json()["connection"]["status"])

    def polls(n: int = 6) -> None:
        reader = rt.acc.reader if rt.acc is not None else None
        assert reader is not None
        start = reader.polls
        wait_for(lambda: reader.polls >= start + n)

    put = client.put("/api/game", json={"id": "acc:pc"}).json()
    assert put["actions"][0]["action"] == "enabled"
    assert put["state"]["input"]["key"] == "acc" and put["state"]["input"]["reader"]["state"] in (
        "not_running",
        "stopped",
    )
    assert rt.acc is not None
    hurry(rt)
    # 1. closed: no pages - and the reader never creates any
    polls()
    assert health() == "no_data" and rt.acc.reader.state is R.AccReaderState.NOT_RUNNING
    assert not any(mem.exists(p.mapping) for p in P.PAGES)
    # 2. frozen on track: pages with status LIVE that never change (they were there before we looked)
    mem.start_game()
    mem.write(physics(500), graphics(500), static())
    wait_for(lambda: rt.acc is not None and rt.acc.reader.pages_open)
    polls(30)
    assert health() == "no_data" and rt.acc.reader.state is R.AccReaderState.WAITING
    # 3. menus, 4. paused, 5. replay: Graphics keeps stepping (and Physics too, for good measure)
    pid = 501
    for status in (OFF, PAUSE, REPLAY):
        for _ in range(20):
            mem.write(physics(pid), graphics(pid, status))
            pid += 1
            polls(2)
        assert health() == "no_data", P.AccStatus(status).name
    assert rt.acc.reader.received == 0 and rt.live.connection()["packets"] == 0
    row = next(r for r in client.get("/api/integrations").json() if r["key"] == "acc")
    assert row["reader"]["state"] == "waiting" and row["reader"]["acc_status"] == "replay"
    assert not games.busy(row) and not games.receiving(row)
    # positive control: driving is live within a poll or two
    for _ in range(10):
        mem.write(physics(pid), graphics(pid))
        pid += 1
        polls(2)
    assert health() == "live"
    conn = client.get("/api/health").json()["connection"]
    assert conn["rejected"] == 0 and conn["unrecognised"] == 0
    # ... and stops being live once the game pauses (no more snapshots)
    for _ in range(5):
        mem.write(graphics=graphics(pid, PAUSE))
        pid += 1
        polls(2)
    wait_for(lambda: health() == "stale", timeout_s=5.0)
    # 6. ACC quits (we hold the pages): nothing new ever arrives
    mem.quit_game()
    polls(20)
    assert health() == "stale"


def test_connect_page_lists_acc_with_its_guide(client: TestClient) -> None:
    info = client.get("/api/connect").json()
    row = next(r for r in info["integrations"] if r["key"] == "acc")
    assert row["name"] == "Assetto Corsa Competizione (PC, shared memory)" and row["reader"]["state"] == "off"
    guide = next(g for g in info["guides"] if g["id"] == "acc")
    assert guide["supported"] and guide["platforms"] == ["PC"] and "Run Pitwall on the gaming PC" in json.dumps(guide)
    assert client.put("/api/integrations/acc", json={"port": 9000}).status_code == 422
    assert client.put("/api/integrations/acc", json={"console_ip": "192.168.1.50"}).status_code == 422
    rows = client.put("/api/integrations/acc", json={"enabled": True}).json()
    assert next(r for r in rows if r["key"] == "acc")["enabled"] is True
    one = client.get("/api/games/acc:pc").json()
    assert one["integration"] == "acc" and one["guide"]["id"] == "acc" and one["transport"]["kind"] == "shared_memory"


# ============================================================================================== games / CLI
def test_transport_and_game_input() -> None:
    t = games.transport("acc")
    assert t["kind"] == "shared_memory" and t["port"] is None and t["console_ip"] == "no" and not t["in_game_setting"]
    assert "same PC" in t["summary"]
    e = games.entry("acc:pc")
    assert e is not None and games.entry_for_game_key("acc") is e
    assert games.entry_for_game_key("gt7") is None and games.entry_for_game_key("nope") is None
    row = {
        "key": "acc",
        "enabled": False,
        "active": True,
        "listening": True,
        "port": 0,
        "reader": {"state": "reading", "last_rx_s_ago": 0.1},
        "decoded_s_ago": 0.1,
    }
    gi = games.game_input(e, [row])
    assert gi is not None and gi["port"] is None and gi["active"] and gi["reader"]["state"] == "reading"
    assert gi["in_use"] and games.busy(row)
    assert "reader" not in (games.game_input(games.entry("gt7:ps5"), []) or {})  # only ACC's input has one


@pytest.mark.parametrize(("platform", "needs_windows"), [("darwin", True), ("win32", False)])
def test_ensure_input_switches_acc_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, needs_windows: bool
) -> None:
    from pitwall import compat

    monkeypatch.setattr(compat.sys, "platform", platform)
    s = settings_for(tmp_path)
    store = SettingsStore(tmp_path / "settings.json")
    e = games.entry("acc:pc")
    assert e is not None
    actions = games.ensure_input(e, s, store, None)
    assert [a["action"] for a in actions] == ["enabled", *(["needs_windows"] if needs_windows else [])]
    assert "nothing to set in the game" in actions[0]["message"]
    assert store.get(I.SECTION)["acc"] == {"enabled": True}
    again = games.ensure_input(e, s, store, None)
    assert again[0]["action"] == "already_enabled"
    if needs_windows:
        assert "Windows PC that runs it" in actions[1]["message"] and "this Mac" in actions[1]["message"]


runner = CliRunner()


def test_cli_game_set_acc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings_for(tmp_path, http_port=8797)
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    calls: list[str] = []

    def no_server(method: str, url: str, body: Any = None, timeout_s: float = 10.0) -> None:
        calls.append(url)
        assert url.startswith("http://127.0.0.1:8797/")
        return None

    monkeypatch.setattr(cli, "_http", no_server)
    r = runner.invoke(cli.app, ["game", "set", "acc", "--json"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["selected"] == "acc:pc" and out["via"] == "file"
    assert out["actions"][0]["action"] == "enabled"
    stored = json.loads((s.data_dir / "settings.json").read_text(encoding="utf-8"))
    assert stored["game"]["selected"] == "acc:pc" and stored["integrations"]["acc"] == {"enabled": True}
    r = runner.invoke(cli.app, ["game", "set", "ACC"])
    assert r.exit_code == 0 and "Selected Assetto Corsa Competizione (PC) (acc:pc)" in r.output
    bad = runner.invoke(cli.app, ["game", "set", "gt7"])
    assert bad.exit_code == 2 and "did you mean gt7:ps5 or gt7:ps4" in bad.output
    assert runner.invoke(cli.app, ["game", "set", "acc:ps5", "--console-ip", "192.168.1.5"]).exit_code == 1


def test_cli_send_refuses_an_acc_capture(tmp_path: Path) -> None:
    path = tmp_path / "acc.pwcap"
    write_acc_capture(path, AccScenario(flying_laps=1, menu_s=0.1, cooldown_s=0.2))
    r = runner.invoke(cli.app, ["send", str(path), "--port", str(free_port())])
    assert r.exit_code == 2 and "pitwall replay" in r.output
