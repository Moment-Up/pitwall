"""Multi-game ingest: integration settings, validation and live listener management (no real console traffic)."""

from __future__ import annotations

import re
import socket
import time
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest
from fastapi.testclient import TestClient

from pitwall import integrations as I
from pitwall.adapters.ac import packets as P
from pitwall.adapters.ac.adapter import AcTrackGeometry
from pitwall.adapters.base import SupportLevel
from pitwall.capabilities import PLANNED, CapabilityRow
from pitwall.config import Settings
from pitwall.core import runtime as runtime_mod
from pitwall.core.runtime import Runtime
from pitwall.games import LEVEL_ORDER
from pitwall.model.telemetry import Game


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class FakeHeartbeat:
    instances: ClassVar[list[FakeHeartbeat]] = []

    def __init__(self, console_ip: str | None, variant: str = "C", **_: Any) -> None:
        self.console_ip, self.variant = console_ip, variant
        self.started = self.stopped = False
        FakeHeartbeat.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self, timeout_s: float = 2.0) -> None:
        self.stopped = True

    def set_console_ip(self, ip: str | None) -> None:
        self.console_ip = ip

    def set_variant(self, v: str) -> None:
        self.variant = v

    def snapshot(self) -> dict[str, Any]:
        return {"console_ip": self.console_ip, "variant": self.variant}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path, f1_udp_port=free_port(), forza_udp_port=free_port(), udp_bind="127.0.0.1", record_raw=False
    )


@pytest.fixture
def rt(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Any:
    FakeHeartbeat.instances.clear()
    monkeypatch.setattr(runtime_mod, "GT7Heartbeat", FakeHeartbeat)
    monkeypatch.setattr(I, "GT7_RECEIVE_PORT", free_port())  # never bind the real 33740 in tests
    r = Runtime(settings)
    yield r
    r.close()


# ---------------------------------------------------------------------------------------------- validation
@pytest.mark.parametrize(
    ("key", "values", "msg"),
    [
        ("gt7", {"console_ip": "not-an-ip"}, "console IP"),
        ("gt7", {"console_ip": "8.8.8.8"}, "private"),
        ("gt7", {"console_ip": "127.0.0.1"}, "private"),
        # Python's is_private says yes to these, but none is a console on the LAN: same gate as AC's handshake
        ("gt7", {"console_ip": "255.255.255.255"}, "private"),  # broadcast
        ("gt7", {"console_ip": "198.18.0.5"}, "private"),  # benchmarking
        ("gt7", {"console_ip": "192.0.2.1"}, "private"),  # documentation
        ("gt7", {"console_ip": "198.51.100.7"}, "private"),
        ("gt7", {"console_ip": "203.0.113.9"}, "private"),
        ("gt7", {"console_ip": "240.0.0.1"}, "private"),  # reserved
        ("gt7", {"console_ip": "0.1.2.3"}, "private"),  # "this network"
        ("gt7", {"console_ip": "100.101.1.2"}, "private"),  # Tailscale / CGNAT
        ("gt7", {"console_ip": "192.168.1.255"}, "private"),  # broadcast-looking
        ("gt7", {"port": 40000}, "always replies"),
        ("gt7", {"variant": "Z"}, "variant"),
        ("forza", {"port": 5250}, "5200-5300"),
        ("forza", {"port": 8081}, "another service"),
        ("forza", {"port": 80}, "between"),
        ("forza", {"console_ip": "192.168.1.2"}, "does not need"),
        ("f1", {"enabled": False}, "primary"),
        ("nope", {}, "unknown integration"),
        ("forza", {"enabled": "yes"}, "true or false"),
        ("forza", {"colour": "red"}, "unknown setting"),
    ],
)
def test_invalid_updates_rejected(key: str, values: dict[str, Any], msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        I.validate_update(key, values)


def test_valid_update_normalised() -> None:
    assert I.validate_update("gt7", {"enabled": True, "console_ip": " 192.168.1.100 ", "variant": "~"}) == {
        "enabled": True,
        "console_ip": "192.168.1.100",
        "variant": "~",
    }
    assert I.validate_update("gt7", {"console_ip": ""}) == {"console_ip": None}


def test_resolve_overlays_store_and_ignores_corrupt_entries(settings: Settings) -> None:
    cfg = I.resolve_configs(settings, {"gt7": {"enabled": True, "console_ip": "10.0.0.5"}, "forza": {"port": 1}})
    assert cfg["gt7"].enabled and cfg["gt7"].console_ip == "10.0.0.5"
    assert cfg["forza"].port == settings.forza_udp_port and not cfg["forza"].enabled  # invalid entry ignored
    assert cfg["f1"].enabled and cfg["f1"].port == settings.f1_udp_port
    # a hand-edited broadcast address is ignored: the heartbeat is never aimed at it
    cfg = I.resolve_configs(settings, {"gt7": {"enabled": True, "console_ip": "255.255.255.255"}})
    assert not cfg["gt7"].enabled and cfg["gt7"].console_ip is None


def test_gt7_environment_console_ip_passes_the_same_gate(settings: Settings) -> None:
    ok = settings.model_copy(update={"gt7_enabled": True, "gt7_console_ip": " 192.168.1.100 "})
    cfg = I.resolve_configs(ok, {})["gt7"]
    assert cfg.enabled and cfg.console_ip == "192.168.1.100"
    for bad in ("198.18.0.5", "255.255.255.255", "8.8.8.8", "nonsense"):
        cfg = I.resolve_configs(settings.model_copy(update={"gt7_enabled": True, "gt7_console_ip": bad}), {})["gt7"]
        assert not cfg.enabled and cfg.console_ip is None, bad  # off, not silently switched to broadcast
    cfg = I.resolve_configs(settings.model_copy(update={"gt7_enabled": True, "gt7_console_ip": None}), {})["gt7"]
    assert cfg.enabled and cfg.console_ip is None  # no IP configured = broadcast discovery, as before


def test_port_conflicts() -> None:
    a = I.IntegrationConfig("f1", True, 5301)
    b = I.IntegrationConfig("forza", True, 5301)
    c = I.IntegrationConfig("gt7", False, 5301)
    assert I.port_conflicts([a, b, c]) == ["port 5301: f1, forza"]
    assert I.port_conflicts([a, c]) == []


_PLATFORM_IDS = {"PS5": "ps5", "PS4": "ps4", "PC": "pc", "Xbox": "xbox"}  # status-string names -> catalogue ids
_INTEGRATION_GAMES = {
    "f1": {Game.F1_25},
    "gt7": {Game.GT7},
    "forza": {Game.FORZA_MOTORSPORT, Game.FORZA_HORIZON},
    "ac": {Game.AC},
}


def _status_parts(status: str) -> list[tuple[SupportLevel, list[str]]]:
    """``"live_validated (PS5) · community_documented (PS4)"`` -> [(level, [platform, ...]), ...]; a part names its
    platforms in brackets or after "on" (then the brackets are a note); a bare level names none."""
    parts: list[tuple[SupportLevel, list[str]]] = []
    for part in status.split(" · "):
        m = re.fullmatch(r"([a-z_]+)(?: on (\w+))?(?: \(([^)]*)\))?", part)
        assert m is not None, part
        names = [m[2]] if m[2] else [n.strip() for n in m[3].split(",")] if m[3] else []
        parts.append((SupportLevel(m[1]), names))
    return parts


@pytest.mark.parametrize("key", sorted(_INTEGRATION_GAMES))
def test_integration_status_strings_match_the_capability_matrix(key: str) -> None:
    """The Connect tab's evidence chip reads the integration's status string: it must say what capabilities.py says,
    per platform and in its headline (the strongest level of the game's rows, which the chip shows)."""
    rows = [r for r in PLANNED if r.adapter_game in _INTEGRATION_GAMES[key]]
    assert rows, key

    def strongest(rs: list[CapabilityRow]) -> SupportLevel:
        return min((r.status for r in rs), key=LEVEL_ORDER.index)

    parts = _status_parts(I.SPECS[key].status)
    assert parts[0][0] == strongest(rows), I.SPECS[key].status
    for level, names in parts:
        for name in names:
            covering = [r for r in rows if _PLATFORM_IDS[name] in r.platform_ids]
            assert covering and strongest(covering) == level, (key, name, level)
    assert set(I.SPECS) == {*_INTEGRATION_GAMES, *I.CAPTURE_ONLY}  # a new integration needs its entry here


def test_gt7_status_shows_the_live_ps5_and_the_untested_ps4() -> None:
    by_key = {r.key: r for r in PLANNED}
    assert (
        I.SPECS["gt7"].status
        == (f"{by_key['gt7_ps5'].status.value} (PS5) · {by_key['gt7_ps4'].status.value} (PS4)")
        == "live_validated (PS5) · community_documented (PS4)"
    )


def test_every_integration_has_an_adapter_and_detection_is_exclusive() -> None:
    ads = I.all_adapters()
    assert {a.info.game.value.split("_")[0] for a in ads} >= {"f1", "gt7", "forza"}
    # A Forza-sized datagram of zeros must not be claimed by the F1 or GT7 decoders (and vice versa).
    for size in (232, 311, 324, 331):
        claims = [type(a).__name__ for a in ads if a.can_decode(bytes(size))]
        assert "F1Adapter" not in claims and "GT7Adapter" not in claims


# ---------------------------------------------------------------------------------------------- runtime
def _wait(pred: Any, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_runtime_starts_f1_only_by_default(rt: Runtime, settings: Settings) -> None:
    rt.start_udp()
    assert set(rt.inputs) == {settings.f1_udp_port}
    assert rt.udp is not None and rt.gt7_heartbeat is None
    rows = {r["key"]: r for r in rt.input_status()}
    assert rows["f1"]["listening"] and not rows["forza"]["listening"] and rows["gt7"]["heartbeat"] is None


def test_enabling_forza_live_starts_and_stops_a_listener(rt: Runtime, settings: Settings) -> None:
    rt.start_udp()
    rt.store.update("integrations", {"forza": {"enabled": True}})
    assert settings.forza_udp_port in rt.inputs
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(bytes(331), ("127.0.0.1", settings.forza_udp_port))
    assert _wait(lambda: rt.inputs[settings.forza_udp_port].listener.received == 1)
    rt.store.update("integrations", {"forza": {"enabled": False}})
    assert settings.forza_udp_port not in rt.inputs and rt.udp is not None


def test_gt7_heartbeat_follows_settings(rt: Runtime) -> None:
    rt.start_udp()
    rt.store.update("integrations", {"gt7": {"enabled": True, "console_ip": "192.168.1.100", "variant": "C"}})
    hb = rt.gt7_heartbeat
    assert isinstance(hb, FakeHeartbeat) and hb.started and hb.console_ip == "192.168.1.100"
    rt.store.update("integrations", {"gt7": {"enabled": True, "console_ip": "192.168.1.231", "variant": "B"}})
    assert rt.gt7_heartbeat is hb and hb.console_ip == "192.168.1.231" and hb.variant == "B"
    rt.store.update("integrations", {"gt7": {"enabled": False}})
    assert rt.gt7_heartbeat is None and hb.stopped


def test_bind_failure_is_reported_not_raised(rt: Runtime, settings: Settings) -> None:
    rt.start_udp()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", settings.forza_udp_port))
    try:
        rt.store.update("integrations", {"forza": {"enabled": True}})
    finally:
        blocker.close()
    row = next(r for r in rt.input_status() if r["key"] == "forza")
    # SO_REUSEADDR on macOS may still allow the bind; either way the state must be consistent.
    assert row["listening"] or (row["error"] and "could not listen" in row["error"])


# ---------------------------------------------------------------------------------------------- API
def test_integrations_api(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from pitwall.api.app import create_app

    monkeypatch.setattr(runtime_mod, "GT7Heartbeat", FakeHeartbeat)
    monkeypatch.setattr(I, "GT7_RECEIVE_PORT", free_port())
    s = settings.model_copy(update={"llm_enabled": False, "voice_enabled": False, "tailscale_trust_owner": False})
    app = create_app(s, start_udp=True)
    with TestClient(app) as c:
        assert c.put("/api/integrations/gt7", json={"console_ip": "8.8.8.8"}).status_code == 422
        rows = c.put("/api/integrations/gt7", json={"enabled": True, "console_ip": "192.168.1.100"}).json()
        gt7 = next(r for r in rows if r["key"] == "gt7")
        assert gt7["enabled"] and gt7["listening"] and gt7["heartbeat"]["console_ip"] == "192.168.1.100"
        clash = c.put("/api/integrations/forza", json={"enabled": True, "port": s.f1_udp_port})
        assert clash.status_code == 409
        info = c.get("/api/connect").json()
        assert {r["key"] for r in info["integrations"]} == {"f1", "gt7", "forza", "ac", "record"}
        assert next(g for g in info["guides"] if g["id"] == "gt7")["supported"]
        # Assetto Corsa: only private LAN addresses are accepted; the guide's probe command uses the saved IP
        for bad in ("8.8.8.8", "100.100.1.1", "127.0.0.1", "192.168.1.255"):
            assert c.put("/api/integrations/ac", json={"console_ip": bad}).status_code == 422, bad
        assert c.put("/api/integrations/ac", json={"port": 9997}).status_code == 422
        rows = c.put("/api/integrations/ac", json={"console_ip": "192.168.1.50", "platform": "PS4"}).json()
        ac = next(r for r in rows if r["key"] == "ac")
        assert ac["console_ip"] == "192.168.1.50" and ac["platform"] == "ps4" and not ac["enabled"]
        assert ac["listens"] is False and ac["client"] is None
        guide = next(g for g in c.get("/api/connect").json()["guides"] if g["id"] == "ac")
        assert guide["supported"] and "--ip 192.168.1.50 --platform ps4" in guide["extras"][0]["value"]
        caps = {(r["game"], r["platform"]): r for r in c.get("/api/capabilities").json()}
        assert (
            caps[("Assetto Corsa (original, PS4 version)", "PS5 (backward compatibility)")]["status"]
            == "recorded_validated"  # protocol probed live; pitwall's own service path not yet run on the console
        )
        assert caps[("Assetto Corsa (original)", "Xbox One")]["status"] == "unsupported"


# ---------------------------------------------------------------------------------------------- derived distance
def test_end_of_lap_tolerance_scales_only_for_derived_distance_games() -> None:
    from pitwall.analysis.laps import EDGE_TOLERANCE_M, LapAssembler
    from pitwall.model.telemetry import Game

    asm = LapAssembler(lambda _lap: None, track_length_m=7004.0)  # Spa
    assert asm._end_tolerance_m(Game.F1_25) == EDGE_TOLERANCE_M  # F1 reports exact lap distance
    assert asm._end_tolerance_m(Game.GT7) == pytest.approx(105.06)
    assert asm._end_tolerance_m(Game.FORZA_MOTORSPORT) == pytest.approx(105.06)
    short = LapAssembler(lambda _lap: None, track_length_m=2000.0)
    assert short._end_tolerance_m(Game.GT7) == EDGE_TOLERANCE_M  # never tighter than the F1 tolerance


# ---------------------------------------------------------------------------------------------- incidents
def test_incident_corner_is_reported_once_and_never_coached_as_technique() -> None:
    from pitwall.analysis.coaching import is_incident, observations_for_comparison
    from pitwall.analysis.compare import Compatibility, CornerDelta, CornerMetrics, LapComparison

    def delta(name: str, loss: float, ref_min: float, cmp_min: float) -> CornerDelta:
        ref = CornerMetrics(name, 10.0, brake_start_m=100.0, min_speed_kph=ref_min)
        cmp = CornerMetrics(name, 10.0 + loss, brake_start_m=20.0, min_speed_kph=cmp_min)
        return CornerDelta(
            name, loss, -80.0, None, cmp_min - ref_min, None, None, None, None, None, None, None, ref, cmp
        )

    spun = delta("T1", 9.4, 249.0, 12.0)  # Silverstone lap 3: contact at Abbey
    slow = delta("T3", 0.3, 120.0, 110.0)
    assert is_incident(spun) and not is_incident(slow)
    assert is_incident(delta("T5", 0.8, 200.0, 70.0))  # crawled through a fast corner
    assert not is_incident(delta("T6", 0.8, 50.0, 20.0))  # hairpin: reference itself is slow
    comp = LapComparison(
        cmp_lap_number=3,
        ref_lap_number=2,
        corners=[spun, slow],
        compatibility=Compatibility(True),
        total_delta_s=9.7,
        delta_d=[0.0],  # declared list[float]
        delta_s=[0.0],
    )
    obs = observations_for_comparison(comp)
    t1 = [o for o in obs if o.corner == "T1"]
    assert [o.kind for o in t1] == ["incident"] and "incident" in t1[0].text  # no "brake 80 m earlier" tip


def test_record_another_game_captures_raw_packets_without_decoding(
    rt: Runtime, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pitwall.ingest.capture import CaptureReader

    port = free_port()
    monkeypatch.setattr(I, "RECORD_DEFAULT_PORT", port)
    rt.start_udp()
    rt.store.update("integrations", {"record": {"enabled": True, "port": port}})
    inp = rt.inputs[port]
    assert inp.router is None and inp.keys == ("record",)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for i in range(3):
            s.sendto(bytes([2, 2, 0, i]), ("127.0.0.1", port))  # e.g. Project Motor Racing type 2, unknown to us
    assert _wait(lambda: inp.listener.received == 3)
    rt.store.update("integrations", {"record": {"enabled": False}})  # closes the capture file
    caps = list(settings.capture_dir.glob(f"*_udp{port}.pwcap"))
    assert len(caps) == 1 and [p.data[3] for p in CaptureReader(caps[0])] == [0, 1, 2]
    assert rt.live.unrecognised == 0  # raw recording never shows up as "unrecognised" F1 traffic


# ---------------------------------------------------------------------------------------------- Assetto Corsa
# The AC integration has no bound port: the runtime starts an AcRemoteClient that handshakes with the console. These
# tests run the real client against SYNTHETIC fake game servers on 127.0.0.1; ``LoopbackRedirect`` lets the client
# believe it targets a LAN console (so the private-IP gate and the 1 s LAN handshake floor apply) while every
# datagram stays on loopback. Nothing here is evidence that AC on a real console works.
AC_A, AC_B, AC_REFUSING = "192.168.1.50", "192.168.1.51", "192.168.1.60"


def _closed_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


@pytest.fixture
def ac_lab(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Two fake AC games (A, B) and a refusing address, reachable only through the client's socket factory."""
    from pitwall.ingest.ac_client import AcRemoteClient
    from pitwall.sim.ac_stream import FakeAcServer, LoopbackRedirect

    with FakeAcServer(rate_hz=200.0) as a, FakeAcServer(rate_hz=200.0) as b:
        redirect = LoopbackRedirect({AC_A: a.port, AC_B: b.port, AC_REFUSING: _closed_udp_port()})
        made: list[AcRemoteClient] = []

        def factory(console_ip: str | None, handler: Any, **kw: Any) -> AcRemoteClient:
            kw.update(socket_factory=redirect, stream_timeout_s=0.5, handshake_interval_s=0.2)
            kw.update(min_handshake_interval_s=0.1)  # the client still enforces 1 s for these LAN targets
            c = AcRemoteClient(console_ip, handler, **kw)
            made.append(c)
            return c

        monkeypatch.setattr(runtime_mod, "AcRemoteClient", factory)
        yield {"a": a, "b": b, "redirect": redirect, "made": made}


def _ac_row(rt: Runtime) -> dict[str, Any]:
    return next(r for r in rt.input_status() if r["key"] == "ac")


def _assert_lan_only(redirect: Any) -> None:
    from pitwall.ingest.ac_client import validate_console_ip

    assert redirect.connects, "the client never connected"
    for ip, port in redirect.connects:
        assert validate_console_ip(ip, allow_loopback=False) == ip and port == 9996


def test_ac_validation_and_defaults(settings: Settings) -> None:
    cfg = I.resolve_configs(settings, {})
    assert cfg["ac"].enabled is False and cfg["ac"].platform == "ps5" and cfg["ac"].port == 9996
    assert cfg["f1"].platform is None  # the platform choice is AC's alone
    assert I.validate_update("ac", {"enabled": True, "console_ip": " 10.0.0.7 ", "platform": "PC"}) == {
        "enabled": True,
        "console_ip": "10.0.0.7",
        "platform": "pc",
    }
    for bad in (
        {"console_ip": "8.8.8.8"},  # public
        {"console_ip": "100.101.1.2"},  # Tailscale / CGNAT
        {"console_ip": "192.0.2.10"},  # documentation range (is_private in Python, but not a LAN)
        {"console_ip": "127.0.0.1"},  # this Mac
        {"console_ip": "10.0.0.255"},  # broadcast-looking
        {"platform": "xbox"},
        {"port": 9997},
        {"variant": "C"},
    ):
        with pytest.raises(ValueError):
            I.validate_update("ac", bad)
    with pytest.raises(ValueError, match="platform"):
        I.validate_update("gt7", {"platform": "ps5"})
    # a stored public address (hand-edited settings.json) is ignored, so the client is never aimed at it
    assert I.resolve_configs(settings, {"ac": {"enabled": True, "console_ip": "8.8.8.8"}})["ac"].enabled is False


def test_ac_never_binds_or_conflicts_on_its_game_port() -> None:
    ac = I.IntegrationConfig("ac", True, 9996, AC_A, platform="ps5")
    rec = I.IntegrationConfig("record", True, 9996)
    assert I.port_conflicts([ac, rec]) == [] and not I.listens("ac") and I.listens("record")


def test_ac_enable_retarget_platform_and_disable(rt: Runtime, ac_lab: dict[str, Any]) -> None:
    from pitwall.ingest.ac_client import AcClientState
    from pitwall.model.telemetry import Platform

    a, b, redirect = ac_lab["a"], ac_lab["b"], ac_lab["redirect"]
    rt.start_udp()
    assert rt.ac is None and _ac_row(rt)["client"] is None and not _ac_row(rt)["listening"]
    inputs_before = set(rt.inputs)

    rt.store.update("integrations", {"ac": {"enabled": True}})  # no console IP yet: nothing is sent anywhere
    assert rt.ac is None and not ac_lab["made"] and set(rt.inputs) == inputs_before

    rt.store.update("integrations", {"ac": {"enabled": True, "console_ip": AC_A}})
    cur = rt.ac
    assert cur is not None and set(rt.inputs) == inputs_before  # no UDP port bound for AC
    client = cur.client
    assert _wait(lambda: client.state is AcClientState.STREAMING and a.subscribers == 1)
    assert _wait(lambda: rt.live.session_id is not None)  # decoded by the AC router into a (synthetic) session
    adapter = cur.router.adapters[0]
    assert type(adapter).__name__ == "AcAdapter" and adapter.platform is Platform.PS5
    row = _ac_row(rt)
    assert row["enabled"] and row["listening"] and row["listens"] is False and row["received"] > 0
    assert row["client"]["state"] == "streaming" and row["client"]["platform"] == "ps5"
    assert row["client"]["console_ip"] == AC_A and row["client"]["last_handshake"]["size"] == 408
    assert row["error"] is None

    # retarget: the same client DISMISSes A and registers with B
    rt.store.update("integrations", {"ac": {"enabled": True, "console_ip": AC_B}})
    assert rt.ac is cur
    assert _wait(lambda: b.subscribers == 1 and client.state is AcClientState.STREAMING, timeout=5.0)
    assert _wait(lambda: a.subscribers == 0 and a.ops_of(P.Operation.DISMISS) == 1)
    assert _ac_row(rt)["client"]["console_ip"] == AC_B

    # another platform: the adapter is rebuilt, so the client is replaced (old one DISMISSed)
    rt.store.update("integrations", {"ac": {"enabled": True, "console_ip": AC_B, "platform": "ps4"}})
    assert rt.ac is not None and rt.ac is not cur and client.state is AcClientState.STOPPED
    assert rt.ac.router.adapters[0].platform is Platform.PS4
    assert _wait(lambda: b.ops_of(P.Operation.DISMISS) >= 1)
    second = rt.ac.client

    # disable: DISMISS, socket closed, no client left
    rt.store.update("integrations", {"ac": {"enabled": False}})
    assert rt.ac is None and second.state is AcClientState.STOPPED and second.local_port is None
    assert _wait(lambda: b.subscribers == 0)
    row = _ac_row(rt)
    assert not row["listening"] and row["client"] is None
    assert rt.udp is not None and set(rt.inputs) == inputs_before  # F1 untouched throughout
    _assert_lan_only(redirect)


def test_ac_refused_state_is_reported_not_raised(rt: Runtime, ac_lab: dict[str, Any]) -> None:
    rt.start_udp()
    rt.store.update("integrations", {"ac": {"enabled": True, "console_ip": AC_REFUSING}})
    assert _wait(lambda: (_ac_row(rt)["client"] or {}).get("state") == "refused")
    row = _ac_row(rt)
    assert row["listening"] and row["error"] is None  # a refusal is a game state, not a pitwall error
    assert "refused" in row["client"]["last_error"] and row["client"]["refused"] >= 1
    sent = row["client"]["sent"]
    time.sleep(1.2)
    assert _ac_row(rt)["client"]["sent"] - sent <= 2  # LAN target: at most one HANDSHAKE per second
    _assert_lan_only(ac_lab["redirect"])


def test_ac_client_is_stopped_with_the_runtime(settings: Settings, ac_lab: dict[str, Any]) -> None:
    from pitwall.ingest.ac_client import AcClientState
    from pitwall.ingest.capture import CaptureReader

    rt = Runtime(settings.model_copy(update={"record_raw": True}))
    try:
        rt.start_udp()
        rt.store.update("integrations", {"ac": {"enabled": True, "console_ip": AC_A, "platform": "pc"}})
        assert rt.ac is not None
        client = rt.ac.client
        assert _wait(lambda: client.state is AcClientState.STREAMING and client.received > 20)
        assert client.capture is not None
    finally:
        rt.close()
    assert rt.ac is None and client.state is AcClientState.STOPPED
    assert _wait(lambda: ac_lab["a"].ops_of(P.Operation.DISMISS) == 1)
    (cap,) = settings.capture_dir.glob("*_ac9996.pwcap")
    r = CaptureReader(cap)
    assert r.meta.game_hint == "ac-remote" and r.meta.extra["platform"] == "pc" and not r.meta.synthetic
    pkts = list(r)
    assert len(pkts[0].data) == 408 and sum(len(p.data) == 328 for p in pkts) > 5


def test_ac_known_tracks_from_stored_sessions() -> None:
    from pitwall.core.runtime import ac_known_tracks

    rows: list[dict[str, Any]] = [
        {"game": "ac", "synthetic": False, "track_id": "ac:ks_monza", "track_length_m": 5758.0, "info": {}},
        {
            "game": "ac",
            "synthetic": False,
            "track_id": "ac:ks_monza",
            "track_length_m": 5760.0,
            "info": {"ac_line_norm": 0.1},
        },
        {
            "game": "ac",
            "synthetic": False,
            "track_id": "ac:ks_monza",
            "track_length_m": 5000.0,
            "info": {"ac_line_norm": 0.5},
        },  # older: the most recent usable line wins
        {"game": "ac", "synthetic": True, "track_id": "ac:synthetic", "track_length_m": 3000.0, "info": {}},
        {"game": "ac", "synthetic": False, "track_id": "ac:spa", "track_length_m": None, "info": {}},
        {"game": "ac", "synthetic": False, "track_id": "ac:tiny", "track_length_m": 12.0, "info": {}},
        {"game": "gt7", "synthetic": False, "track_id": "ac:fake", "track_length_m": 4000.0, "info": {}},
        {"game": "ac", "synthetic": False, "track_id": None, "track_length_m": 4000.0, "info": {}},
    ]
    known = ac_known_tracks(rows)
    assert set(known) == {"ac:ks_monza"}
    assert known["ac:ks_monza"].length_m == 5760.0 and known["ac:ks_monza"].line_norm == 0.1


def test_ac_known_tracks_stop_at_a_session_that_rejected_the_stored_geometry() -> None:
    from pitwall.core.runtime import ac_known_tracks

    def row(length: float | None, line: float | None, rejected: bool | None = None) -> dict[str, Any]:
        info: dict[str, Any] = {"ac_line_norm": line}
        if rejected is not None:
            info["ac_geometry_rejected"] = rejected
        return {
            "game": "ac",
            "synthetic": False,
            "track_id": "ac:ks_vallelunga",
            "track_length_m": length,
            "info": info,
        }

    bad = row(4100.0, 0.1)  # the wrong entry, re-published by every session that was seeded with it
    # the newest session rejected it and relearned: its own geometry wins, the older ones are never used
    assert ac_known_tracks([row(4050.0, 0.4, True), bad, bad])["ac:ks_vallelunga"] == AcTrackGeometry(4050.0, 0.4)
    # it rejected it but ended before relearning the length: unknown, not the rejected values
    assert ac_known_tracks([row(None, 0.4, True), bad, bad]) == {}
    # sessions after the rejecting one count as usual
    newer = row(4052.0, 0.41, False)
    assert ac_known_tracks([newer, row(None, 0.4, True), bad])["ac:ks_vallelunga"] == AcTrackGeometry(4052.0, 0.41)
    assert ac_known_tracks([row(4100.0, 0.1, False), bad])["ac:ks_vallelunga"] == AcTrackGeometry(4100.0, 0.1)


def _feed_ac(rt: Runtime, packets: list[Any]) -> None:
    """Run packets through a live-style AC router (own SessionManager, geometry seeded from the database)."""
    from pitwall.core.runtime import finish_router
    from pitwall.core.session import SessionManager
    from pitwall.ingest.router import PacketRouter

    sessions = SessionManager(rt.writer, rt.live, rt.worker, source=runtime_mod.AC_SOURCE)
    router = PacketRouter(I.adapters_for(("ac",), ac_tracks=rt._ac_known_tracks()), sessions, rt.live)
    for p in packets:
        router.handle(p)
    finish_router(router)
    rt.worker.join()
    rt.writer.flush()


def test_ac_geometry_round_trips_through_the_database_and_rejections_stick(settings: Settings) -> None:
    """SessionInfo.extra -> repo.update_session_info -> repo.list_sessions -> Runtime._ac_known_tracks -> adapter.

    Generated packets with a real-looking car name so the rows are not synthetic (a tmp database only).
    """
    from pitwall.sim.ac_stream import AcScenario, generate_ac_session
    from pitwall.storage import repo

    def scenario(spline_offset: float, start_ns: int) -> AcScenario:
        return AcScenario(
            flying_laps=3,
            car_name="ks_ferrari_458",
            driver_name="Tester",
            track_name="ks_test_ring",
            spline_offset=spline_offset,
            start_ns=start_ns,
        )

    rt = Runtime(settings)
    try:
        packets, truth = generate_ac_session(scenario(0.3, 10**12))
        _feed_ac(rt, packets)
        known = rt._ac_known_tracks()
        geo = known["ac:ks_test_ring"]
        assert geo.length_m == pytest.approx(truth.lap_length_m, rel=2e-3)
        assert geo.line_norm == pytest.approx(truth.line_norm, abs=2e-3)

        # a track update moved the spline origin under the same name: the stored line is contradicted twice,
        # rejected, relearned - and the old rows can no longer seed anything
        packets, truth2 = generate_ac_session(scenario(0.6, 10**15))
        _feed_ac(rt, packets)
        geo2 = rt._ac_known_tracks()["ac:ks_test_ring"]
        assert geo2.line_norm == pytest.approx(truth2.line_norm, abs=2e-3)
        assert geo2.length_m == pytest.approx(truth2.lap_length_m, rel=2e-3)
        with rt.db.read() as c:
            rows = [r for r in repo.list_sessions(c) if r["track_id"] == "ac:ks_test_ring"]
        assert len(rows) == 2 and all(r["game"] == "ac" and not r["synthetic"] for r in rows)
        assert rows[0]["info"]["ac_geometry_rejected"] is True and rows[1]["info"]["ac_geometry_rejected"] is False
        assert rows[0]["lap_count"] >= 1
    finally:
        rt.close()


def test_finish_router_releases_a_held_lap_before_the_session_ends() -> None:
    from pitwall.adapters.ac.adapter import AcAdapter
    from pitwall.core.live import LiveState
    from pitwall.core.runtime import finish_router
    from pitwall.ingest.capture import CapturedPacket
    from pitwall.ingest.router import PacketRouter
    from pitwall.model.telemetry import LapCompletion

    seen: list[Any] = []

    class Sessions:
        def handle(self, e: Any) -> None:
            seen.append(e)

        def end(self) -> None:
            seen.append("end")

        def set_ground_plane(self, _plane: Any) -> None:
            pass

    a = AcAdapter()
    router = PacketRouter([a], cast(Any, Sessions()), LiveState())
    t = 1_000_000_000
    router.handle(CapturedPacket(t, 9996, P.encode_handshake_response("ks_bmw_m3_e30", "D", "ks_vallelunga", "")))
    for i, lap in enumerate((0, 0, 1)):  # lapCount increments, lastLap not yet updated: the completion is held
        lap_ms = 60_000 + i * 20 if lap == 0 else 10  # the lap clock restarts at the line
        values = {"lapCount": lap, "lapTime": lap_ms, "carPositionNormalized": 0.99 + i * 0.004}
        router.handle(CapturedPacket(t + (i + 1) * 20_000_000, 9996, P.encode_rt_car_info(values)))
    assert not any(isinstance(e, LapCompletion) for e in seen)
    finish_router(router)
    comps = [e for e in seen if isinstance(e, LapCompletion)]
    assert [(c.lap_number, c.lap_time_ms) for c in comps] == [(1, None)]
    assert seen.index(comps[0]) < seen.index("end") and seen[-1] == "end"


def test_ac_detection_is_exclusive_and_replays_route_ac_captures(tmp_path: Path) -> None:
    import random

    from pitwall.ingest.capture import CaptureMeta, CaptureReader, write_capture
    from pitwall.sim.ac_stream import AcScenario, write_ac_capture
    from pitwall.storage import repo

    ads = I.all_adapters()
    names = [type(a).__name__ for a in ads]
    assert names[-1] == "AcAdapter"  # exact-size detection goes last
    ac = ads[-1]
    rng = random.Random(0)
    for size in (208, 212, 328, 408):  # AC sizes are claimed by nobody else, whatever their content
        payloads = [b"a" + bytes(size - 1)] + [rng.randbytes(size) for _ in range(50)]
        for data in payloads:
            claims = [type(a).__name__ for a in ads if a.can_decode(data)]
            assert claims in ([], ["AcAdapter"]), (size, claims)
        assert ac.can_decode(payloads[0])
    for size in (45, 101, 231, 232, 273, 296, 311, 316, 324, 331, 344, 368, 753, 1349, 1352):
        assert not ac.can_decode(b"a" + bytes(size - 1)), size
        assert not any(ac.can_decode(rng.randbytes(size)) for _ in range(10)), size
    # the runtime's replay path decodes an AC capture (SYNTHETIC) end to end, flagged synthetic everywhere
    path = tmp_path / "ac.pwcap"
    write_ac_capture(path, AcScenario(flying_laps=2))
    s = Settings(data_dir=tmp_path / "d", llm_enabled=False)
    r = Runtime(s)
    try:
        rep = r.start_replay(path, speed=None)
        assert rep.done.wait(30)
        assert r.live.session_id is not None and r.live.synthetic
        sid = r.live.session_id
        r.worker.join()
        r.writer.flush()
        with r.db.read() as c:
            row = repo.get_session(c, sid)
            (listed,) = [x for x in repo.list_sessions(c) if x["id"] == sid]
        assert row is not None and row["game"] == "ac" and row["synthetic"]
        assert str(row["track_id"]).startswith("synthetic:") and row["info"]["synthetic"] is True
        assert listed["lap_count"] >= 2  # out-lap + flying laps decoded and stored
        assert r._ac_known_tracks() == {}  # synthetic geometry never seeds a real track

        # the same datagrams in a capture without AC's game_hint (a raw "record another game" file): never AC
        raw = tmp_path / "raw.pwcap"
        write_capture(raw, list(CaptureReader(path)), CaptureMeta(source="udp:7576", synthetic=True))
        rep = r.start_replay(raw, speed=None)
        assert rep.done.wait(30)
        r.writer.flush()
        with r.db.read() as c:
            assert [x["id"] for x in repo.list_sessions(c)] == [sid]  # no session decoded from it
        assert r.live.unrecognised > 0
    finally:
        r.close()


def test_real_f1_capture_is_never_claimed_by_the_ac_decoder() -> None:
    """Recorded tier: the real F1 25 PS5 excerpt still routes to F1 with AC in the replay decoder set."""
    from pitwall.adapters.ac.adapter import AcAdapter
    from pitwall.ingest.capture import CaptureReader

    path = Path(__file__).resolve().parents[1] / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
    if not path.exists():
        pytest.skip("recorded F1 fixture not present")
    ac = AcAdapter()
    ads = I.all_adapters()
    n = 0
    for pkt in CaptureReader(path):
        n += 1
        assert not ac.can_decode(pkt.data)
        assert next(type(a).__name__ for a in ads if a.can_decode(pkt.data)) == "F1Adapter"
    assert n > 1000
