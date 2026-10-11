"""``Snapshot.game`` (LiveState only): selection, detection, effective game, mismatch and live suggestion; and the
ingest thread never calls into ``pitwall.games`` (one attribute write per newly detected sender port)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from pitwall import games
from pitwall.adapters.base import DecodeStats
from pitwall.adapters.f1.adapter import F1_25_INFO
from pitwall.core.live import LiveState
from pitwall.ingest.capture import CapturedPacket
from pitwall.ingest.router import PacketRouter
from pitwall.model.telemetry import CarFrame, Game, Platform, SessionInfo


def sel(entry_id: str) -> games.Selection:
    return games.Selection(entry_id, 1_760_000_000.0, "dashboard")


def live_f1(
    platform: Platform = Platform.PS5,
    fmt: int = 2025,
    source: str = "udp:20796",
    synthetic: bool = False,
    game: Game = Game.F1_25,
) -> LiveState:
    live = LiveState()
    live.reset_session("s1", source, synthetic)
    live.on_session(SessionInfo(game=game, platform=platform, extra={"packet_format": fmt}))
    live.on_packet(True)  # connection: live
    return live


def test_nothing_selected_and_real_f1_is_detected_and_suggested() -> None:
    g = live_f1().snapshot()["game"]
    assert g["selected_id"] is None and g["effective_id"] == "f1_25:ps5"
    assert g["detected"] == {
        "entry_id": "f1_25:ps5",
        "adapter_game": "f1_25",
        "platform": "ps5",
        "variant": "2025",
        "real": True,
        "status": "live",
    }
    assert g["mismatch"] is None
    assert g["suggestion"] == {"id": "f1_25:ps5", "source": "live", "text": "Pitwall sees F1 25 telemetry from a PS5."}


def test_another_game_selected_is_a_game_mismatch() -> None:
    live = live_f1()
    live.set_game_selection(sel("gt7:ps5"))
    g = live.snapshot()["game"]
    assert g["selected_id"] == "gt7:ps5" and g["effective_id"] == "f1_25:ps5"  # the screens follow the data
    assert g["mismatch"] == {
        "kind": "game",
        "selected_id": "gt7:ps5",
        "detected_id": "f1_25:ps5",
        "text": "Receiving F1 25, but Gran Turismo 7 (PS5) is selected.",
    }
    assert g["suggestion"] is None
    assert live.effective_game_id() == "f1_25:ps5"


def test_variant_and_platform_mismatches() -> None:
    live = live_f1(fmt=2026)
    live.set_game_selection(sel("f1_25:ps5"))
    g = live.snapshot()["game"]
    assert g["detected"]["entry_id"] == "f1_25_2026:ps5"
    assert g["mismatch"]["kind"] == "variant"
    assert g["mismatch"]["text"] == (
        "Receiving UDP format 2026 (2026 Season Pack), but F1 25 (format 2025) is selected."
    )
    live = live_f1(platform=Platform.PC)
    live.set_game_selection(sel("f1_25:ps5"))
    m = live.snapshot()["game"]["mismatch"]
    assert m["kind"] == "platform" and m["text"] == "Receiving F1 25 from a PC, but PS5 is selected."
    live = live_f1(platform=Platform.XBOX)
    live.set_game_selection(sel("f1_25:pc"))
    assert "from an Xbox" in live.snapshot()["game"]["mismatch"]["text"]
    live = live_f1(platform=Platform.UNKNOWN)  # participants not seen yet: no platform claim
    live.set_game_selection(sel("f1_25:pc"))
    g = live.snapshot()["game"]
    assert g["mismatch"] is None and g["detected"]["platform"] == "unknown" and g["effective_id"] == "f1_25:pc"


def test_ac_platform_is_configuration_not_evidence() -> None:
    live = live_f1(game=Game.AC, platform=Platform.PS4, source="ac-remote")
    live.set_game_selection(sel("ac:ps5"))
    g = live.snapshot()["game"]
    # the configured platform picks the entry in use (the AC client is set to PS4), but it is no platform evidence
    assert g["detected"]["platform"] == "unknown" and g["detected"]["entry_id"] == "ac:ps4"
    assert g["mismatch"] is None


def test_an_ac_stream_follows_its_configured_platform() -> None:
    live = live_f1(game=Game.AC, platform=Platform.PC, source="ac-remote")
    g = live.snapshot()["game"]
    assert g["effective_id"] == "ac:pc" and g["suggestion"]["id"] == "ac:pc"  # never the stronger-rated PS5 entry
    live.set_game_selection(sel("f1_25:ps5"))
    assert live.snapshot()["game"]["mismatch"]["detected_id"] == "ac:pc"  # "Switch to" picks the PC entry


@pytest.mark.parametrize(("source", "synthetic"), [("udp:20796", True), ("replay:austria.pwcap", False)])
def test_synthetic_or_replay_never_mismatches_but_is_effective(source: str, synthetic: bool) -> None:
    live = live_f1(source=source, synthetic=synthetic)
    live.set_game_selection(sel("gt7:ps5"))
    g = live.snapshot()["game"]
    assert g["detected"]["real"] is False and g["mismatch"] is None
    assert g["effective_id"] == "f1_25:ps5"
    live.set_game_selection(None)
    assert live.snapshot()["game"]["suggestion"] is None  # never suggest a game from the demo or a replay


def test_a_paused_game_keeps_its_mismatch_and_a_newer_choice_wins_over_old_data() -> None:
    live = live_f1()
    live.set_game_selection(sel("gt7:ps5"))  # chosen long before the data
    live.last_accepted_mono = time.monotonic() - 5.0  # paused: the driver picks up the iPad now
    g = live.snapshot()["game"]
    assert g["detected"]["status"] == "stale" and g["mismatch"]["kind"] == "game"
    live.last_accepted_mono = time.monotonic() - games.PAUSED_S - 1.0  # long gone: the old data stays F1's ...
    g = live.snapshot()["game"]
    assert g["effective_id"] == "f1_25:ps5" and g["mismatch"] is None  # ... but nothing says "Receiving"
    live.last_accepted_mono = time.monotonic() - 30.0
    live.set_game_selection(games.Selection("gt7:ps5", time.time(), "dashboard"))  # chosen after the data stopped
    g = live.snapshot()["game"]
    assert g["detected"] is None and g["effective_id"] == "gt7:ps5" and g["mismatch"] is None


def test_stray_packets_never_make_old_data_live() -> None:
    live = live_f1()
    live.set_game_selection(sel("ac:ps5"))
    live.last_accepted_mono = time.monotonic() - 30.0  # the F1 session ended a while ago
    for _ in range(5):
        live.on_packet(False)  # another game's packets on the F1 port: rejected
    assert live.connection()["status"] == "live"  # the port is busy ...
    g = live.snapshot()["game"]
    assert g["detected"]["status"] == "stale"  # ... but no F1 telemetry is arriving: not "Receiving F1 25"


def test_no_data_detects_nothing() -> None:
    fresh = LiveState()
    fresh.set_game_selection(sel("gt7:ps5"))
    g = fresh.snapshot()["game"]
    assert g == {
        "selected_id": "gt7:ps5",
        "effective_id": "gt7:ps5",
        "detected": None,
        "mismatch": None,
        "suggestion": None,
    }


def test_a_new_session_names_its_own_game_not_another_ports() -> None:
    """The router's detection is per sender port and written once: a new F1 session after GT7 was seen on another
    port must not read as GT7 before the F1 session packet arrives."""
    live = LiveState()
    live.last_detected_game = "gt7"  # GT7 was auto-detected on its port earlier
    live.set_game_selection(sel("f1_25:ps5"))
    live.reset_session("s2", "udp:20777", False, "f1_25")  # the session manager starts an F1 session
    live.on_packet(True)
    g = live.snapshot()["game"]
    assert g["detected"]["adapter_game"] == "f1_25" and g["mismatch"] is None and g["effective_id"] == "f1_25:ps5"
    live.reset_session("s3", "udp:20777", False)  # an older caller without the game: the frame decides
    live.on_frame(CarFrame(game=Game.F1_25, t_recv_ns=1))
    g = live.snapshot()["game"]
    assert g["detected"]["adapter_game"] == "f1_25" and g["mismatch"] is None
    live.reset_session(None, None, False, "f1_25")
    assert live.session_game is None


def test_router_detection_before_the_first_session_packet() -> None:
    live = LiveState()
    live.last_detected_game = "gt7"
    live.on_packet(True)
    live.set_game_selection(sel("forza_motorsport:pc"))
    g = live.snapshot()["game"]
    assert g["detected"]["entry_id"] == "gt7:ps5" and g["mismatch"]["kind"] == "game"


# ---------------------------------------------------------------------------------------------- ingest untouched
class _Adapter:
    info = F1_25_INFO

    def __init__(self) -> None:
        self.stats = DecodeStats()

    def can_decode(self, data: bytes) -> bool:
        return True

    def decode(self, data: bytes, t_recv_ns: int) -> list[Any]:
        self.stats.packets += 1
        return []

    def reset(self) -> None:
        return None


class _Sessions:
    def set_ground_plane(self, _plane: tuple[str, str]) -> None:
        return None

    def handle(self, _item: Any) -> None:
        return None


class _CountingLive(LiveState):
    detections = 0

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "last_detected_game" and value is not None:
            type(self).detections += 1
        super().__setattr__(name, value)


def test_ingest_never_calls_into_games(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("games called on the ingest path")

    for name in ("resolve", "snapshot_block", "entry", "mismatch", "platform_on_wire", "variant_of"):
        monkeypatch.setattr(games, name, boom)
    _CountingLive.detections = 0
    live = _CountingLive()
    router = PacketRouter([_Adapter()], _Sessions(), live)  # type: ignore[list-item, arg-type]
    for port, n in ((50001, 5), (50002, 3), (50001, 2)):
        for i in range(n):
            router.handle(CapturedPacket(t_recv_ns=i, src_port=port, data=b"x"))
    live.on_frame(CarFrame(game=Game.F1_25, t_recv_ns=1))
    live.on_session(SessionInfo(game=Game.F1_25, platform=Platform.PS5, extra={"packet_format": 2025}))
    assert _CountingLive.detections == 2  # once per newly detected sender port, never per packet
    assert live.last_detected_game == "f1_25"


class _Writer:
    def submit(self, _fn: Any) -> None:
        return None


def test_the_session_manager_tells_live_state_which_game_started_the_session() -> None:
    from typing import cast

    from pitwall.core.lap_processor import AnalysisWorker
    from pitwall.core.session import SessionManager
    from pitwall.storage.db import DbWriter

    live = LiveState()
    live.last_detected_game = "gt7"
    sm = SessionManager(cast(DbWriter, _Writer()), live, cast(AnalysisWorker, None), source="udp:20777")
    sm.handle(CarFrame(game=Game.F1_25, t_recv_ns=1))
    assert live.session_game == "f1_25" and live.session_id == sm.session_id
