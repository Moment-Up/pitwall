"""ACC shared-memory adapter: generated pages -> CarFrame / SessionInfo / GameEvent / LapCompletion.

Synthetic tier only: every page here is packed by ``packets.py`` itself, so these tests prove the decoding logic
(field mapping, sentinels, wheel order, sessions, laps, lap distance, the runtime evidence checks) against our
reading of Kunos' "ACC Shared Memory v1.8.12" - not that a real ACC page matches. Layout conformance with that
document is ``test_acc_protocol.py``; real-game evidence needs a recorded capture.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast

import pytest

from pitwall.adapters.acc import adapter as A
from pitwall.adapters.acc import packets as P
from pitwall.adapters.acc import tracks
from pitwall.adapters.acc.adapter import (
    ACC_INFO,
    EVIDENCE_CHECKS,
    LAST_LAP_HOLD_S,
    LENGTH_SPLINE,
    LENGTH_TABLE,
    LENGTH_UNKNOWN,
    AccAdapter,
    resolve_track_length,
)
from pitwall.adapters.base import PacketRejected, SupportLevel
from pitwall.analysis.laps import LapAssembler, LapFlag, LapTrace
from pitwall.core.lap_processor import AnalysisWorker, LapJob
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.games import FEATURES
from pitwall.ingest.capture import CapturedPacket
from pitwall.ingest.router import PacketRouter
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID
from pitwall.model.telemetry import (
    CarFrame,
    Emitted,
    EventKind,
    FrameQuality,
    Game,
    GameEvent,
    LapCompletion,
    Platform,
    SessionInfo,
    SessionType,
)
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

G = 9.80665
DT = 1 / 60
PLAYER_ID = 1001
SPA = tracks.TRACK_LENGTH_M["spa"]

GRAPHICS_DEFAULTS: dict[str, Any] = {
    "status": int(P.AccStatus.LIVE),
    "session": int(P.AccSessionType.PRACTICE),
    "sessionIndex": 0,
    "completedLaps": 0,
    "position": 3,
    "iCurrentTime": 1234,
    "iLastTime": P.INT32_MAX,
    "iBestTime": P.INT32_MAX,
    "isValidLap": 1,
    "normalizedCarPosition": 0.25,
    "activeCars": 2,
    "carID": [7, PLAYER_ID] + [0] * 58,
    "carCoordinates": [1.0, 2.0, 3.0, 111.0, 4.5, -333.0] + [0.0] * 174,
    "playerCarID": PLAYER_ID,
    "TC": 3,
    "ABS": 2,
    "rainTyres": 0,
    "fuelEstimatedLaps": 12.5,
    "currentSectorIndex": 1,
    "rainIntensity": 0,
}
PHYSICS_DEFAULTS: dict[str, Any] = {
    "gas": 0.5,
    "brake": 0.0,
    "clutch": 0.0,
    "steerAngle": 0.0,
    "speedKmh": 100.0,
    "gear": 4,
    "rpm": 6500,
    "wheelPressure": [27.1, 27.2, 27.3, 27.4],
    "TyreCoreTemp": [81.0, 82.0, 83.0, 84.0],
    "brakeTemp": [301.0, 302.0, 303.0, 304.0],
    "airTemp": 22.4,
    "roadTemp": 30.6,
    "localVelocity": [0.0, 0.0, 100 / 3.6],
}


def static_page(track: str = "spa", car: str = "mclaren_720s_gt3", **kw: Any) -> bytes:
    values: dict[str, Any] = {
        "smVersion": P.encode_wstring("1.9", 15),
        "acVersion": P.encode_wstring("1.10.2", 15),
        "carModel": P.encode_wstring(car, 33),
        "track": P.encode_wstring(track, 33),
        "sectorCount": 3,
        "maxRpm": 7700,
        "isOnline": 0,
    }
    values.update(kw)
    return P.encode(P.STATIC_PAGE, values)


class Sim:
    """Feeds generated pages to one adapter on a host clock (ns)."""

    def __init__(self, adapter: AccAdapter | None = None, t0: int = 1_000_000_000) -> None:
        self.a = adapter or AccAdapter()
        self.t = t0
        self.out: list[Emitted] = []
        self.ppid = 0
        self.gpid = 0
        self.g = dict(GRAPHICS_DEFAULTS)
        self.p = dict(PHYSICS_DEFAULTS)

    def feed(self, data: bytes) -> list[Emitted]:
        out = self.a.decode(data, self.t)
        self.out += out
        return out

    def static(self, track: str = "spa", car: str = "mclaren_720s_gt3", **kw: Any) -> list[Emitted]:
        return self.feed(static_page(track, car, **kw))

    def graphics(self, **kw: Any) -> list[Emitted]:
        self.g.update(kw)
        self.gpid += 1
        return self.feed(P.encode(P.GRAPHICS_PAGE, {**self.g, "packetId": self.gpid}))

    def physics(self, **kw: Any) -> list[Emitted]:
        self.ppid += 1
        return self.feed(P.encode(P.PHYSICS_PAGE, {**self.p, **kw, "packetId": self.ppid}))

    def advance(self, dt_s: float = DT) -> None:
        self.t += round(dt_s * 1e9)

    def tick(self, dt_s: float = DT, graphics: dict[str, Any] | None = None, **phys: Any) -> list[Emitted]:
        """Advance the clock, send a Graphics page (fresh lap data), then a Physics page."""
        self.advance(dt_s)
        out = self.graphics(**(graphics or {}))
        return out + self.physics(**phys)

    def start(self, track: str = "spa", car: str = "mclaren_720s_gt3", **static_kw: Any) -> list[Emitted]:
        return self.static(track, car, **static_kw) + self.graphics()


def frames(out: list[Emitted]) -> list[CarFrame]:
    return [e for e in out if isinstance(e, CarFrame)]


def frame(out: list[Emitted]) -> CarFrame:
    fs = frames(out)
    assert len(fs) == 1, out
    return fs[0]


def infos(out: list[Emitted]) -> list[SessionInfo]:
    return [e for e in out if isinstance(e, SessionInfo)]


def completions(out: list[Emitted]) -> list[LapCompletion]:
    return [e for e in out if isinstance(e, LapCompletion)]


def events(out: list[Emitted], kind: EventKind) -> list[GameEvent]:
    return [e for e in out if isinstance(e, GameEvent) and e.kind == kind]


# ============================================================================================== structure
def test_can_decode_accepts_exactly_the_three_snapshots() -> None:
    a = AccAdapter()
    for page in P.PAGES:
        assert a.can_decode(P.encode(page))
    assert not a.can_decode(b"PHYS" + bytes(799))
    assert not a.can_decode(b"XXXX" + bytes(800))
    assert not a.can_decode(b"")
    assert not a.can_decode(bytes(328))  # another game's datagram size


def test_wrong_size_or_tag_is_rejected_and_counted() -> None:
    a = AccAdapter()
    with pytest.raises(PacketRejected, match="not an ACC snapshot"):
        a.decode(b"GRPH" + bytes(100), 1)
    with pytest.raises(PacketRejected):
        a.decode(b"NOPE" + bytes(800), 2)
    assert a.stats.rejected == 2 and a.stats.packets == 2


def test_info_declares_pc_only_and_every_feature_key() -> None:
    assert ACC_INFO.game is Game.ACC
    assert ACC_INFO.platforms[Platform.PC] is SupportLevel.SPEC_IMPLEMENTED
    assert all(ACC_INFO.platforms[p] is SupportLevel.UNSUPPORTED for p in (Platform.PS5, Platform.PS4, Platform.XBOX))
    feature_keys = {k for fd in FEATURES for k in (*fd.required, *fd.optional)}
    assert feature_keys <= set(ACC_INFO.fields)  # the Setup / Connect pages never say "not declared" for ACC
    # what Kunos leaves undefined is never claimed stronger than UNVERIFIED (the spec's rule)
    for key in (
        "g_lat",
        "g_lon",
        "g_vert",
        "yaw_rate_rps",
        "body_slip_rad",
        "wheel_slip_ratio",
        "wheel_slip_angle_rad",
    ):
        assert ACC_INFO.fields[key].level is SupportLevel.UNVERIFIED
    for key in ("fuel_kg", "brake_bias_front_pct", "abs_active"):
        assert ACC_INFO.fields[key].level is SupportLevel.UNVERIFIED
    assert "tester's report" in ACC_INFO.fields["steering"].source


# ============================================================================================== sessions
def test_menus_produce_nothing_and_physics_outside_a_session_is_ignored() -> None:
    sim = Sim()
    sim.static()
    assert sim.graphics(status=int(P.AccStatus.OFF)) == []
    assert sim.physics() == []
    assert sim.graphics(status=int(P.AccStatus.REPLAY)) == []  # a replay from the menus opens no session
    assert sim.physics() == []
    assert sim.a.stats.by_type["physics_outside_session"] == 2
    assert sim.a.stats.ignored == 4


def test_live_graphics_opens_a_session_with_info_first() -> None:
    sim = Sim()
    sim.static()
    out = sim.graphics()
    assert isinstance(out[0], SessionInfo)
    assert [e.kind for e in out if isinstance(e, GameEvent)] == [EventKind.SESSION_STARTED]
    info = out[0]
    assert info.session_uid == f"acc:{sim.t}"
    assert info.platform is Platform.PC
    assert info.track_id == "acc:spa" and info.track_length_m == SPA
    assert info.track_name == "Spa-Francorchamps"  # a label for people (tracks.TRACK_NAMES); the id keeps "spa"
    assert info.car_id == "acc:car:mclaren_720s_gt3" and info.car_name == "McLaren 720S GT3 2019"
    assert info.session_type is SessionType.PRACTICE and info.session_type_raw == "Practice"
    assert info.network_game is False
    assert info.extra["sm_version"] == "1.9" and info.extra["sector_count"] == 3
    assert info.extra["track_length_source"] == LENGTH_TABLE
    assert set(info.extra["acc_evidence"]) == set(EVIDENCE_CHECKS)


def test_unknown_car_keeps_its_id_as_name_and_player_names_are_never_decoded() -> None:
    sim = Sim()
    names = {
        "playerName": P.encode_wstring("Edward", 33),
        "playerSurname": P.encode_wstring("Example", 33),
        "playerNick": P.encode_wstring("EdX", 33),
    }
    sim.static("monza", "ford_mustang_gt3", **names)
    info = infos(sim.graphics())[0]
    assert info.car_name == "ford_mustang_gt3"
    text = repr(sim.out)
    assert "Edward" not in text and "Example" not in text and "EdX" not in text


@pytest.mark.parametrize(
    ("raw", "expected", "name"),
    [
        (P.AccSessionType.PRACTICE, SessionType.PRACTICE, "Practice"),
        (P.AccSessionType.QUALIFY, SessionType.QUALIFYING, "Qualifying"),
        (P.AccSessionType.RACE, SessionType.RACE, "Race"),
        (P.AccSessionType.HOTLAP, SessionType.TIME_TRIAL, "Hotlap"),
        (P.AccSessionType.TIMEATTACK, SessionType.TIME_TRIAL, "Time attack"),
        (P.AccSessionType.HOTSTINT, SessionType.UNKNOWN, "Hotstint"),
        (P.AccSessionType.UNKNOWN, SessionType.UNKNOWN, "unknown_-1"),
        (42, SessionType.UNKNOWN, "unknown_42"),  # not in Kunos' enum: no name
    ],
)
def test_session_types(raw: int, expected: SessionType, name: str) -> None:
    """The session's name in words, as F1's are (the dashboard, the report and the boards show it); never a number."""
    sim = Sim()
    sim.static()
    info = infos(sim.graphics(session=int(raw)))[0]
    assert info.session_type is expected and info.session_type_raw == name
    assert set(A.SESSION_NAMES) == set(P.AccSessionType) - {P.AccSessionType.UNKNOWN}


def test_session_labels_follow_the_names() -> None:
    """carclass shows the game's own session name; an unknown session type has none (never "unknown_42")."""
    from pitwall import carclass

    assert carclass.session_label(None, "Qualifying") == "Qualifying"
    assert carclass.session_label(None, "unknown_42", SessionType.UNKNOWN.value) is None
    assert carclass.session_label(None, "Hotlap", SessionType.TIME_TRIAL.value) == "Hotlap"


def test_track_names_are_labels_and_the_id_keeps_the_games_string() -> None:
    sim = Sim()
    sim.static("brands_hatch")
    info = infos(sim.graphics())[0]
    assert (info.track_id, info.track_name) == ("acc:brands_hatch", "Brands Hatch")
    other = Sim()
    other.static("some_dlc_track")
    info2 = infos(other.graphics())[0]
    assert (info2.track_id, info2.track_name, info2.track_length_m) == ("acc:some_dlc_track", "some_dlc_track", None)
    assert set(tracks.TRACK_NAMES) == set(tracks.TRACK_LENGTH_M)  # one name per listed circuit, no more
    assert tracks.track_label("SPA") == "Spa-Francorchamps" and tracks.track_label(None) is None


def test_status_off_ends_the_session() -> None:
    sim = Sim()
    sim.start()
    sim.tick()
    sim.advance()
    out = sim.graphics(status=int(P.AccStatus.OFF))
    ended = events(out, EventKind.SESSION_ENDED)
    assert len(ended) == 1 and ended[0].payload["reason"] == "status_off"
    assert sim.physics() == []  # no frames until the next live session


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"session": int(P.AccSessionType.QUALIFY), "sessionIndex": 1}, "session_changed"),
        ({"sessionIndex": 1}, "session_changed"),
    ],
)
def test_next_session_of_an_event_opens_at_once(change: dict[str, Any], reason: str) -> None:
    sim = Sim()
    first = infos(sim.start())[0].session_uid
    sim.advance()
    out = sim.graphics(**change)
    assert [type(e).__name__ for e in out][:3] == ["GameEvent", "SessionInfo", "GameEvent"]
    assert events(out, EventKind.SESSION_ENDED)[0].payload["reason"] == reason
    assert events(out, EventKind.SESSION_STARTED)
    assert infos(out)[0].session_uid not in (None, first)


def test_laps_going_back_is_a_restart() -> None:
    sim = Sim()
    sim.start()
    sim.tick(graphics={"completedLaps": 2})
    sim.advance()
    out = sim.graphics(completedLaps=0)
    assert events(out, EventKind.SESSION_ENDED)[0].payload["reason"] == "laps_went_back"
    assert events(out, EventKind.SESSION_STARTED)


def test_new_track_in_static_starts_a_new_session() -> None:
    sim = Sim()
    sim.start()
    sim.tick()
    sim.advance()
    out = sim.static("monza")
    assert events(out, EventKind.SESSION_ENDED)[0].payload["reason"] == "static_changed"
    assert infos(out)[0].track_id == "acc:monza"


def test_static_arriving_after_the_session_opened_fills_it_in() -> None:
    sim = Sim()
    first = infos(sim.graphics())[0]
    assert first.track_id is None and first.track_length_m is None
    sim.advance()
    out = sim.static()
    assert not events(out, EventKind.SESSION_ENDED)
    info = infos(out)[0]
    assert info.session_uid == first.session_uid and info.track_id == "acc:spa" and info.track_length_m == SPA


def test_static_layout_is_checked_against_appendix_7() -> None:
    sim = Sim()
    assert infos(sim.start())[0].extra["static_layout_check"] == "max_rpm_matches_appendix_7"  # 720S: 7700
    sim = Sim()
    info = infos(sim.start(maxRpm=196_608))[0]  # a misread value (a page laid out unlike the document)
    assert info.extra["static_layout_check"] == "max_rpm_differs_from_appendix_7"
    assert sim.a.stats.by_type["max_rpm_differs_from_appendix_7"] == 1
    assert infos(Sim().start(car="ford_mustang_gt3"))[0].extra["static_layout_check"] is None  # not in the PDF


def test_a_zeroed_static_page_is_ignored() -> None:
    sim = Sim()
    sim.start()
    sim.advance()
    assert sim.feed(P.encode(P.STATIC_PAGE)) == []
    assert sim.a.stats.by_type["static_empty"] == 1
    f = frame(sim.tick())
    assert f.max_rpm == 7700.0  # the real page is still known


def test_synthetic_marker_gives_the_synthetic_session_uid() -> None:
    sim = Sim()
    info = infos(sim.start(car=P.SYNTHETIC_CAR_MODEL))[0]
    assert info.session_uid == str(SYNTHETIC_SESSION_UID)


# ============================================================================================== frame mapping
def test_every_mapped_physics_and_graphics_field_round_trips() -> None:
    sim = Sim()
    sim.start()
    f = frame(
        sim.tick(
            gas=0.8,
            brake=0.25,
            clutch=0.1,
            steerAngle=0.3,
            speedKmh=187.5,
            gear=5,
            rpm=7200,
            graphics={"iCurrentTime": 61_234, "iLastTime": 98_765, "position": 4, "fuelEstimatedLaps": 7.5},
        )
    )
    assert f.game is Game.ACC and f.frame_id == sim.ppid
    assert f.throttle == pytest.approx(0.8) and f.brake == pytest.approx(0.25) and f.clutch == pytest.approx(0.1)
    assert f.steering == pytest.approx(-0.3)  # negated: Pitwall + = right (Ed's tester report)
    assert f.speed_kph == pytest.approx(187.5)
    assert f.gear == 4  # raw 5 = 4th (0 = R, 1 = N, 2 = 1st)
    assert f.rpm == 7200.0 and f.max_rpm == 7700.0
    assert f.lap_number == 1 and f.current_lap_time_ms == 61_234 and f.last_lap_time_ms == 98_765
    assert f.race_position == 4 and f.lap_invalid is False and f.sector == 1 and f.pit_status == 0
    assert f.traction_control == 3
    # fuelEstimatedLaps is laps of fuel on board, not F1's margin at the finish that this field means: never mapped
    assert f.fuel_remaining_laps_game is None
    assert f.tyre_compound == "dry"
    assert (f.pos_x_m, f.pos_y_m, f.pos_z_m) == (111.0, 4.5, -333.0)  # the player's row, not row 0
    assert f.lap_distance_m == pytest.approx(0.25 * SPA)
    assert f.session_time_s == pytest.approx(DT, abs=1e-9)
    assert f.quality == FrameQuality.OK


def test_wheel_arrays_are_fl_fr_rl_rr() -> None:
    sim = Sim()
    sim.start()
    f = frame(sim.tick())
    assert f.tyre_core_temp_c is not None and f.tyre_core_temp_c.as_tuple() == (81.0, 82.0, 83.0, 84.0)
    assert f.tyre_pressure_psi is not None
    assert f.tyre_pressure_psi.as_tuple() == pytest.approx((27.1, 27.2, 27.3, 27.4))
    assert f.brake_temp_c is not None and f.brake_temp_c.as_tuple() == (301.0, 302.0, 303.0, 304.0)
    assert f.tyre_core_temp_c.fl == 81.0 and f.tyre_core_temp_c.rr == 84.0


def test_unmapped_and_not_provided_fields_stay_unknown() -> None:
    sim = Sim()
    sim.start()
    f = frame(sim.tick(fuel=55.0, brakeBias=0.62, abs=0.7, tc=0.4, tyreTempI=[90.0] * 4, tyreWear=[1.0] * 4))
    assert f.fuel_kg is None and f.fuel_litres is None  # Kunos: kg; HUD: litres -> not mapped
    assert f.brake_bias_front_pct is None  # needs the per-car offset
    assert f.abs_active is None  # intervention, not the assist being on
    assert f.tyre_surface_temp_c is None and f.tyre_inner_temp_c is None and f.tyre_wear_pct is None
    assert f.drs_open is None and f.ers_store_j is None and f.engine_temp_c is None
    assert f.vel_x_mps is None and f.yaw_rad is None and f.total_distance_m is None


def test_int32_max_and_negative_times_are_unknown() -> None:
    sim = Sim()
    sim.start()
    f = frame(sim.tick(graphics={"iCurrentTime": P.INT32_MAX, "iLastTime": -1, "iBestTime": P.INT32_MAX}))
    assert f.current_lap_time_ms is None and f.last_lap_time_ms is None
    assert infos(sim.out)[-1].extra["best_lap_ms"] is None


@pytest.mark.parametrize(
    ("in_pit", "in_lane", "status"),
    [(0, 0, 0), (0, 1, 1), (1, 1, 2), (1, 0, 2), (2, 0, None)],
)
def test_pit_status(in_pit: int, in_lane: int, status: int | None) -> None:
    sim = Sim()
    sim.start()
    assert frame(sim.tick(graphics={"isInPit": in_pit, "isInPitLane": in_lane})).pit_status == status


@pytest.mark.parametrize(("raw", "gear"), [(0, -1), (1, 0), (2, 1), (8, 7), (-1, None), (12, None)])
def test_gear_offset(raw: int, gear: int | None) -> None:
    sim = Sim()
    sim.start()
    assert frame(sim.tick(gear=raw)).gear == gear


def test_pedals_and_steering_out_of_range() -> None:
    sim = Sim()
    sim.start()
    f = frame(sim.tick(gas=1.01, brake=-0.01, steerAngle=-1.015))
    assert f.throttle == 1.0 and f.brake == 0.0 and f.steering == 1.0  # within tolerance: clamped
    f = frame(sim.tick(gas=1.5, brake=float("nan"), steerAngle=3.0))
    assert f.throttle is None and f.brake is None and f.steering is None


def test_gates_on_wheel_values() -> None:
    sim = Sim()
    sim.start()
    f = frame(sim.tick(wheelPressure=[1.9, 1.9, 1.8, 1.8], TyreCoreTemp=[0.0] * 4, brakeTemp=[0.0] * 4))
    assert f.tyre_pressure_psi is None  # bar, not psi
    assert f.tyre_core_temp_c is None and f.brake_temp_c is None  # all zero: no data yet
    f = frame(sim.tick(wheelPressure=[190.0, 190.0, 185.0, 185.0], TyreCoreTemp=[80.0, 80.0, float("nan"), 80.0]))
    assert f.tyre_pressure_psi is None and f.tyre_core_temp_c is None


def test_sector_needs_a_valid_index_for_the_track() -> None:
    sim = Sim()
    sim.start()
    assert frame(sim.tick(graphics={"currentSectorIndex": 2})).sector == 2
    assert frame(sim.tick(graphics={"currentSectorIndex": 3})).sector is None  # sectorCount 3: 0..2
    sim2 = Sim()
    sim2.graphics()  # no Static yet: the sector count is unknown
    assert frame(sim2.tick()).sector is None


def test_wet_tyres_and_rain() -> None:
    sim = Sim()
    sim.start()
    sim.tick()
    out = sim.tick(graphics={"rainTyres": 1, "rainIntensity": int(P.AccRainIntensity.MEDIUM_RAIN)})
    assert frame(out).tyre_compound == "wet"
    info = infos(sim.out)[-1]
    assert info.weather.condition == "heavy_rain" and info.extra["acc_rain_intensity"] == 3
    assert info.weather.air_temp_c == 22 and info.weather.track_temp_c == 31


def test_player_position_unknown_when_not_among_the_active_cars() -> None:
    sim = Sim()
    sim.start()
    f = frame(sim.tick(graphics={"activeCars": 1}))  # the player's row (index 1) is past activeCars
    assert f.pos_x_m is None and f.pos_y_m is None and f.pos_z_m is None


def test_malformed_values_never_raise() -> None:
    sim = Sim()
    sim.start()
    nan = float("nan")
    f = frame(sim.tick(speedKmh=nan, accG=[nan] * 3, localVelocity=[nan] * 3, slipAngle=[nan] * 4))
    assert f.speed_kph is None
    assert sim.a.stats.errors == 0


# ============================================================================================== quality and clock
def test_pause_flags_frames_and_holds_the_clock() -> None:
    sim = Sim()
    sim.start()
    assert frame(sim.tick(1.0)).session_time_s == pytest.approx(1.0)
    sim.tick(graphics={"status": int(P.AccStatus.PAUSE)})
    sim.advance(2.0)
    paused = frame(sim.tick(0.0))
    assert paused.quality & FrameQuality.PAUSED
    assert paused.session_time_s == pytest.approx(1.0 + DT)
    sim.tick(graphics={"status": int(P.AccStatus.LIVE)})
    f = frame(sim.tick(0.5))
    assert not f.quality & FrameQuality.PAUSED
    assert f.session_time_s == pytest.approx(1.5 + DT)


def test_replay_inside_a_session_keeps_it_open_and_flags_frames() -> None:
    sim = Sim()
    sim.start()
    sim.tick(graphics={"completedLaps": 3})
    out = sim.tick(graphics={"status": int(P.AccStatus.REPLAY), "completedLaps": 1, "session": 2})
    f = frame(out)
    assert f.quality & FrameQuality.REPLAY_OR_SPECTATING and f.lap_distance_m is None
    assert not events(sim.out, EventKind.SESSION_ENDED) and not completions(sim.out)
    out = sim.tick(graphics={"status": int(P.AccStatus.LIVE), "completedLaps": 3, "session": 0})
    assert not events(out, EventKind.SESSION_ENDED) and frame(out).quality == FrameQuality.OK


def test_stale_graphics_are_flagged() -> None:
    sim = Sim()
    sim.start()
    assert frame(sim.tick()).quality == FrameQuality.OK
    sim.advance(0.5)
    assert frame(sim.physics()).quality & FrameQuality.STALE_LAP_DATA


# ============================================================================================== laps
def test_lap_completion_takes_validity_from_the_page_before_the_line() -> None:
    sim = Sim()
    sim.start()
    sim.tick(graphics={"isValidLap": 0, "iLastTime": P.INT32_MAX})  # the lap got a track-limits strike
    out = sim.tick(graphics={"completedLaps": 1, "iLastTime": 101_234, "isValidLap": 1, "normalizedCarPosition": 0.0})
    (c,) = completions(out)
    assert c.lap_number == 1 and c.lap_time_ms == 101_234 and c.valid is False
    assert out.index(c) < out.index(frame(out))  # the completion precedes the next lap's frames
    assert frame(out).lap_number == 2 and frame(out).lap_invalid is False


def test_lap_time_that_lags_the_counter_is_held_with_the_frames_behind_it() -> None:
    sim = Sim()
    sim.start()
    sim.tick(graphics={"iLastTime": 99_000})
    out = sim.tick(graphics={"completedLaps": 1, "normalizedCarPosition": 0.001})
    assert completions(out) == [] and frames(out) == []
    out = sim.tick(graphics={"normalizedCarPosition": 0.003})
    assert completions(out) == [] and frames(out) == []
    out = sim.tick(graphics={"iLastTime": 100_500, "normalizedCarPosition": 0.005})
    (c,) = completions(out)
    assert c.lap_time_ms == 100_500 and c.valid is True
    assert [f.lap_number for f in frames(out)] == [2, 2, 2]  # the held frames, then the new one
    assert out.index(c) < out.index(frames(out)[0])


def test_held_completion_times_out_untimed() -> None:
    sim = Sim()
    sim.start()
    sim.tick(graphics={"iLastTime": 99_000})
    sim.tick(graphics={"completedLaps": 1})
    out = sim.tick(LAST_LAP_HOLD_S + 0.01)
    (c,) = completions(out)
    assert c.lap_time_ms is None and len(frames(out)) == 2
    assert sim.a.stats.by_type["last_lap_untimed"] == 1


def test_flush_releases_a_held_completion() -> None:
    sim = Sim()
    sim.start()
    sim.tick(graphics={"iLastTime": 99_000})
    sim.tick(graphics={"completedLaps": 1})
    out = sim.a.flush()
    assert [type(e) for e in out] == [LapCompletion, CarFrame]
    assert sim.a.flush() == []


def test_a_jump_of_two_laps_completes_nothing() -> None:
    sim = Sim()
    sim.start()
    sim.tick()
    out = sim.tick(graphics={"completedLaps": 2, "iLastTime": 90_000})
    assert completions(out) == [] and sim.a.stats.by_type["lap_jump"] == 1
    out = sim.tick(graphics={"completedLaps": 3, "iLastTime": 91_000})
    assert [c.lap_number for c in completions(out)] == [3]


def test_first_live_page_with_laps_done_completes_nothing() -> None:
    sim = Sim()
    sim.static()
    sim.graphics(completedLaps=5, iLastTime=95_000)
    assert completions(sim.out) == []
    assert frame(sim.tick()).lap_number == 6


# ============================================================================================== lap distance
def test_track_length_resolution() -> None:
    assert resolve_track_length("spa", None) == (SPA, LENGTH_TABLE)
    assert resolve_track_length("Spa", 7010.0) == (7010.0, LENGTH_SPLINE)  # within 3 % of the table
    assert resolve_track_length("spa", 9000.0) == (SPA, LENGTH_TABLE)  # implausible for Spa
    assert resolve_track_length("some_dlc_track", None) == (None, LENGTH_UNKNOWN)
    assert resolve_track_length("some_dlc_track", 4200.0) == (4200.0, LENGTH_SPLINE)
    assert resolve_track_length("some_dlc_track", 50.0) == (None, LENGTH_UNKNOWN)
    assert resolve_track_length(None, None) == (None, LENGTH_UNKNOWN)


def test_spline_length_from_static_when_plausible() -> None:
    sim = Sim()
    info = infos(sim.start(trackSplineLength=7010.0))[0]
    assert info.track_length_m == 7010.0 and info.extra["track_length_source"] == LENGTH_SPLINE
    assert frame(sim.tick()).lap_distance_m == pytest.approx(0.25 * 7010.0)


def test_unknown_track_has_lap_times_but_no_distance() -> None:
    sim = Sim()
    info = infos(sim.start("some_future_dlc_track"))[0]
    assert info.track_length_m is None and info.extra["lap_distance_status"] == "track_length_unknown"
    f = frame(sim.tick())
    assert f.lap_distance_m is None and f.lap_number == 1


def _distances(sim: Sim, positions: list[tuple[float, int]]) -> list[float | None]:
    """Lap distance of one frame per ``(normalizedCarPosition, completedLaps)``; each lap gets its own time."""
    out: list[float | None] = []
    for p, n in positions:
        g = {"normalizedCarPosition": p, "completedLaps": n, "iLastTime": 90_000 + n if n else P.INT32_MAX}
        out.append(frame(sim.tick(graphics=g)).lap_distance_m)
    return out


def test_spline_that_wraps_after_the_counter() -> None:
    sim = Sim()
    sim.start()
    d = _distances(sim, [(0.5, 0), (0.75, 0), (0.98, 0), (0.995, 0), (0.999, 1), (0.002, 1), (0.01, 1)])
    assert d[2] == pytest.approx(0.98 * SPA)
    assert d[4] == pytest.approx(
        -0.001 * SPA, abs=0.01
    )  # float32 spline; lap 2 began at the counter, the spline still says 0.999
    assert d[5] == pytest.approx(0.002 * SPA) and d[6] == pytest.approx(0.01 * SPA)


def test_spline_that_wraps_before_the_counter() -> None:
    sim = Sim()
    sim.start()
    d = _distances(sim, [(0.5, 0), (0.75, 0), (0.98, 0), (0.999, 0), (0.001, 0), (0.003, 1), (0.01, 1)])
    assert d[4] == pytest.approx(1.001 * SPA)  # still lap 1, just past the line
    assert d[5] == pytest.approx(0.003 * SPA)


def test_grid_behind_the_line_is_negative() -> None:
    sim = Sim()
    sim.static()
    sim.graphics(normalizedCarPosition=0.97, session=int(P.AccSessionType.RACE))
    d = _distances(sim, [(0.97, 0), (0.995, 0), (0.002, 0), (0.1, 0)])
    assert d[0] == pytest.approx(-0.03 * SPA) and d[2] == pytest.approx(0.002 * SPA)


def test_wrap_without_a_lap_and_teleports_stop_the_trace_until_the_next_lap() -> None:
    sim = Sim()
    sim.start()
    d = _distances(sim, [(0.3, 0), (0.5, 0), (0.7, 0), (0.9, 0), (0.99, 0), (0.02, 0), (0.08, 0), (0.1, 0)])
    assert d[5] == pytest.approx(1.02 * SPA)
    assert d[6] is None and d[7] is None  # 8 % past the line and still no lap: not trustworthy
    d = _distances(sim, [(0.12, 1), (0.13, 1), (0.6, 1), (0.61, 1), (0.1, 2)])
    assert d[0] == pytest.approx(0.12 * SPA) and d[2] is None and d[3] is None  # teleport
    assert d[4] == pytest.approx(0.1 * SPA)  # the next lap starts afresh
    assert sim.a.stats.by_type["distance_out_of_lap"] == 1 and sim.a.stats.by_type["distance_jump"] == 1


def test_a_full_lap_assembles_with_its_time_and_validity() -> None:
    sim = Sim()
    sim.start()
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=SPA)
    feed = [*sim.out]
    n = 600
    for i in range(n + 1):
        lap_done = i == n
        g = {
            "normalizedCarPosition": 0.0 if lap_done else i / n,
            "completedLaps": 1 if lap_done else 0,
            "iCurrentTime": 0 if lap_done else round(i * DT * 1000),
            "iLastTime": round(n * DT * 1000) if lap_done else P.INT32_MAX,
        }
        feed += sim.tick(graphics=g, speedKmh=SPA / (n * DT) * 3.6)
    for e in feed:
        if isinstance(e, CarFrame):
            asm.feed(e)
        elif isinstance(e, LapCompletion):
            asm.feed_completion(e)
    sim.tick(graphics={"normalizedCarPosition": 0.01})
    asm.feed(frames(sim.out)[-1])
    (lap,) = laps
    assert lap.lap_number == 1 and lap.lap_time_ms == 10_000 and lap.valid is True
    assert LapFlag.INCOMPLETE not in lap.flags and LapFlag.DISTANCE_JUMP not in lap.flags


# ============================================================================================== runtime evidence
def _drive(
    sim: Sim,
    *,
    cycles: int = 2,
    handed: str = "left",
    acc_scale: float = 1.0,
    slip_angle_scale: float = 1.0,
    slip_ratio_abs: bool = False,
) -> None:
    """Straights (accelerate, brake) and corners (right, left) with physically consistent pages.

    ``handed``: "left" = Kunos' local axes x right, y up, z forward (a yaw that is + for right turns); "right" = x
    left (a yaw that is + for left turns). ``acc_scale`` 9.81 = accG in m/s^2 instead of g.
    """
    sx = 1.0 if handed == "left" else -1.0  # raw x component of a vector pointing right
    v = 20.0

    def step(a_lon_g: float, yaw: float, steer: float, gas: float, brake: float, vx_right: float) -> None:
        nonlocal v
        v += a_lon_g * G * DT
        lat_g = v * yaw / G  # centripetal, towards the inside (right for a right turn)
        front_sa = 0.06 * slip_angle_scale if yaw else 0.002 * slip_angle_scale
        sr_front = -0.08 if brake > 0.5 else 0.0
        sr_rear = 0.05 if gas > 0.8 else 0.0
        if slip_ratio_abs:
            sr_front, sr_rear = abs(sr_front), abs(sr_rear)
        sim.tick(
            speedKmh=v * 3.6,
            gas=gas,
            brake=brake,
            steerAngle=-steer,  # raw is the opposite of Pitwall's sign
            accG=[sx * lat_g * acc_scale, 0.0, a_lon_g * acc_scale],
            localAngularVel=[0.0, sx * yaw, 0.0],
            localVelocity=[sx * vx_right, 0.0, v],
            slipAngle=[front_sa, -front_sa, 0.03, -0.03],
            slipRatio=[sr_front, sr_front, sr_rear, sr_rear],
        )

    for _ in range(cycles):
        for _ in range(round(8 / DT)):
            step(0.4, 0.0, 0.0, 1.0, 0.0, 0.0)
        for _ in range(round(2 / DT)):
            step(-1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        for yaw, steer in ((0.6, 0.2), (-0.6, -0.2)):
            for _ in range(round(3 / DT)):
                step(0.0, yaw, steer, 0.5, 0.0, -0.5 if yaw > 0 else 0.5)  # tail slightly out


def test_dynamics_stay_unknown_until_the_evidence_is_in() -> None:
    sim = Sim()
    sim.start()
    f = frame(sim.tick(accG=[1.2, 0.1, -0.3], localAngularVel=[0.0, 0.4, 0.0], slipAngle=[0.05] * 4))
    assert (f.g_lat, f.g_lon, f.g_vert, f.yaw_rate_rps, f.body_slip_rad) == (None, None, None, None, None)
    assert f.wheel_slip_angle_rad is None and f.wheel_slip_ratio is None


@pytest.mark.parametrize("handed", ["left", "right"])
def test_consistent_driving_settles_every_check(handed: str) -> None:
    sim = Sim()
    sim.start()
    _drive(sim, handed=handed)
    a = sim.a
    sign = 1 if handed == "left" else -1
    assert {k: a.verdict(k) for k in EVIDENCE_CHECKS} == {
        "g_lon": 1,
        "centripetal": 1,
        "yaw": sign,
        "forward": 1,
        "slip_angle_unit": 1,
        "slip_ratio_braking": 1,
        "slip_ratio_traction": 1,
    }
    # a right-hand corner at 30 m/s, 0.6 rad/s, the tail 0.5 m/s out
    sx = 1.0 if handed == "left" else -1.0
    f = frame(
        sim.tick(
            speedKmh=108.0,
            accG=[sx * 30 * 0.6 / G, 0.02, -0.3],
            localAngularVel=[0.0, sx * 0.6, 0.0],
            localVelocity=[sx * -0.5, 0.0, 30.0],
            slipAngle=[0.06, -0.06, 0.03, -0.03],
            slipRatio=[-0.02, -0.02, 0.01, 0.01],
            steerAngle=-0.2,
        )
    )
    assert f.g_lon == pytest.approx(-0.3)
    assert f.g_lat == pytest.approx(sx * 30 * 0.6 / G)  # sign per game
    assert f.g_vert == pytest.approx(0.02)
    assert f.yaw_rate_rps == pytest.approx(0.6)  # + = turning right, in both axis conventions
    assert f.body_slip_rad == pytest.approx(math.atan2(0.5, 30.0))  # tail out: same sign as the yaw rate
    assert f.wheel_slip_angle_rad is not None and f.wheel_slip_angle_rad.fl == pytest.approx(0.06)
    assert f.wheel_slip_ratio is not None and f.wheel_slip_ratio.fl == pytest.approx(-0.02)
    assert infos(sim.out)[-1].extra["acc_evidence"]["yaw"]["verdict"] == sign


def test_slip_angles_in_degrees_are_converted() -> None:
    sim = Sim()
    sim.start()
    _drive(sim, slip_angle_scale=180 / math.pi)
    assert sim.a.verdict("slip_angle_unit") == -1
    f = frame(sim.tick(slipAngle=[3.0, -3.0, 1.5, -1.5]))
    assert f.wheel_slip_angle_rad is not None and f.wheel_slip_angle_rad.fl == pytest.approx(math.radians(3.0))


def test_acceleration_in_metres_per_second_squared_is_never_mapped() -> None:
    sim = Sim()
    sim.start()
    _drive(sim, acc_scale=G)
    assert sim.a.verdict("g_lon") is None and sim.a.verdict("centripetal") is None
    f = frame(sim.tick(accG=[5.0, 0.0, 3.0], localAngularVel=[0.0, 0.5, 0.0]))
    assert f.g_lon is None and f.g_lat is None and f.yaw_rate_rps is None and f.wheel_slip_angle_rad is None
    assert sim.a.evidence["g_lon"].bad > 0


def test_slip_ratio_reported_as_a_magnitude_is_never_mapped() -> None:
    sim = Sim()
    sim.start()
    _drive(sim, slip_ratio_abs=True)
    assert sim.a.verdict("slip_ratio_braking") == -1 and sim.a.verdict("slip_ratio_traction") == 1
    assert frame(sim.tick(slipRatio=[0.1] * 4)).wheel_slip_ratio is None


def test_evidence_is_kept_across_reset_and_ignores_paused_frames() -> None:
    sim = Sim()
    sim.start()
    _drive(sim, cycles=1)
    verdicts = {k: sim.a.verdict(k) for k in EVIDENCE_CHECKS}
    sim.a.reset()
    assert {k: sim.a.verdict(k) for k in EVIDENCE_CHECKS} == verdicts
    sim2 = Sim()
    sim2.start()
    sim2.tick(graphics={"status": int(P.AccStatus.PAUSE)})
    before = {k: v.as_dict() for k, v in sim2.a.evidence.items()}
    for _ in range(50):
        sim2.tick(accG=[1.0, 0.0, 1.0], localAngularVel=[0.0, 0.5, 0.0], steerAngle=-0.3, speedKmh=150.0)
    assert {k: v.as_dict() for k, v in sim2.a.evidence.items()} == before


# ============================================================================================== pipeline
class _Worker:
    def __init__(self) -> None:
        self.jobs: list[Any] = []

    def submit(self, job: Any) -> None:
        self.jobs.append(job)

    def submit_ai_pace(self, job: Any) -> None:
        self.jobs.append(job)


def test_router_and_session_manager_store_an_acc_session_and_its_lap(tmp_path: Path) -> None:
    """Generated pages through the real router and session manager into a scratch database, as the reader would
    hand them over (one tagged page per packet)."""
    n = 300  # one lap in 300 Graphics/Physics pairs
    packets = [static_page(), P.encode(P.GRAPHICS_PAGE, {**GRAPHICS_DEFAULTS, "packetId": 1})]
    for i in range(n + 2):
        done = i >= n
        g = {
            **GRAPHICS_DEFAULTS,
            "packetId": i + 2,
            "normalizedCarPosition": (i - n) / n if done else i / n,
            "completedLaps": 1 if done else 0,
            "iLastTime": 5_000 if done else P.INT32_MAX,
        }
        packets.append(P.encode(P.GRAPHICS_PAGE, g))
        packets.append(P.encode(P.PHYSICS_PAGE, {**PHYSICS_DEFAULTS, "packetId": i + 1, "speedKmh": 300.0}))
    db = Database(tmp_path / "pitwall.sqlite3")
    writer = DbWriter(db)
    try:
        live = LiveState()
        worker = _Worker()
        sessions = SessionManager(writer, live, cast(AnalysisWorker, worker), source="acc-shm")
        router = PacketRouter([AccAdapter()], sessions, live)
        for k, data in enumerate(packets):
            router.handle(CapturedPacket(1_000_000_000 + k * 8_333_333, 0, data))
        assert router.unrecognised == 0 and live.last_detected_game == "acc"
        sid = sessions.session_id
        assert sid is not None
        lap_jobs = [j for j in worker.jobs if isinstance(j, LapJob)]
        assert [j.lap.lap_number for j in lap_jobs] == [1]
        assert lap_jobs[0].lap.lap_time_ms == 5_000 and lap_jobs[0].context["track_id"] == "acc:spa"
        writer.flush()
        with db.read() as c:
            row = repo.get_session(c, sid)
        assert row is not None and row["game"] == "acc" and row["track_id"] == "acc:spa"
        assert row["car_id"] == "acc:car:mclaren_720s_gt3" and row["platform"] == "pc"
        stored = row["info"] if isinstance(row["info"], dict) else json.loads(row["info"])
        assert set(stored["acc_evidence"]) == set(EVIDENCE_CHECKS)
        router.finish()
    finally:
        writer.close()
