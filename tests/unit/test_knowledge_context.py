"""The driver's Context and style for the technique graph (spec: technique knowledge graph, section 2): where each
Context value comes from (unknown stays unknown), which channels each game sends (from the adapters' declared fields),
and the braking style and coasting detected from the driver's own clean laps.

Pure: plain session values and hand-made corner metrics; no game, LLM or database.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any

import numpy as np
import pytest

from pitwall.analysis.braking import detect_braking
from pitwall.analysis.compare import CornerMetrics
from pitwall.analysis.laps import CHANNELS as LAP_CHANNELS
from pitwall.analysis.laps import LapTrace
from pitwall.knowledge.context import (
    CHANNEL_WORDS,
    GAME_KEYS,
    Context,
    build_context,
    channel_status,
    channels_payload,
    fuel_saving_of,
    session_row_context,
)
from pitwall.knowledge.facts import _context_fact
from pitwall.knowledge.graph import CHANNELS, CONTEXT_KEYS, CONTEXT_VALUES, load_graph
from pitwall.knowledge.style import (
    COAST_M,
    MIN_BRAKING_CORNERS,
    MIN_LAPS,
    TRAIL_BRAKE_M,
    Style,
    braking_assist_of,
    detect_style,
)
from pitwall.model.telemetry import Game


def test_the_context_has_one_field_per_graph_key() -> None:
    assert tuple(f.name for f in fields(Context)) == CONTEXT_KEYS
    assert Context().to_dict() == dict.fromkeys(CONTEXT_KEYS)  # everything unknown by default
    assert set(GAME_KEYS.values()) <= set(CONTEXT_VALUES["game"] or ())
    assert set(CHANNEL_WORDS) == set(CHANNELS)


F1_ROW: dict[str, Any] = {
    "game": "f1_25",
    "car_id": "f1:team:3",
    "info": {"formula": "F1 Modern", "packet_format": 2025},
    "weather": {"condition": "light_rain"},
    "assists": {"braking": 0, "gearbox": 1},
}


def test_an_f1_car_on_f1_25() -> None:
    laps = [{"meta": {"abs_active": False, "traction_control": 1}} for _ in range(3)]
    ctx = session_row_context(F1_ROW, laps, skill="beginner", style=Style(braking_style="trail", coasting="rare"))
    assert ctx == Context(
        skill="beginner",
        braking_style="trail",
        coasting="rare",
        game="f1",
        car_family="f1",
        downforce="high",
        abs=False,
        traction_control=True,
        gearbox="paddle_autoblip",
        fuel_saving=None,
        wet=True,
    )


def test_unknown_stays_unknown() -> None:
    # laps that disagree on the assists, no driver, no style, an unknown skill word, no weather
    laps = [{"meta": {"abs_active": True, "traction_control": 0}}, {"meta": {"abs_active": False}}]
    ctx = session_row_context({**F1_ROW, "weather": None}, laps, skill="expert")
    assert ctx.abs is None and ctx.traction_control is False  # TC agreed (0 = off); ABS changed
    assert ctx.skill is None and ctx.braking_style is None and ctx.coasting is None and ctx.wet is None
    assert session_row_context({**F1_ROW, "weather": {"condition": "overcast"}}).wet is False
    # an F2 car: high downforce, but Pitwall does not claim its gearbox
    f2 = build_context(game="f1_25", formula="F2", car_id="f1:team:160", packet_format=2025)
    assert (f2.car_family, f2.downforce, f2.gearbox) == ("f2", "high", None)
    # the game's automatic gearbox assist is known whatever the car
    auto = build_context(game="f1_25", formula="F2", car_id="f1:team:160", assists={"gearbox": 3})
    assert auto.gearbox == "auto"
    # GT7 reports no car class, no assists: nothing about the car is known
    gt7 = build_context(game="gt7", car_id="gt7:car:3390", lap_metas=[{"abs_active": True}])
    assert (gt7.game, gt7.car_family, gt7.downforce, gt7.gearbox, gt7.abs) == ("gt7", None, None, None, None)
    assert build_context(game="synthetic").game is None and build_context(game=None).game is None


def test_assetto_corsa_reads_its_session_assists_not_abs_intervention() -> None:
    """AC's per-frame abs_active is ABS *intervention* (isAbsInAction): only the session's enabled flags count."""
    ctx = build_context(game="ac", assists={"abs": True, "tc": False}, lap_metas=[{"abs_active": False}])
    assert (ctx.abs, ctx.traction_control) == (True, False)
    assert build_context(game="ac", lap_metas=[{"abs_active": False}]).abs is None


def test_fuel_saving_comes_from_the_strategy_view() -> None:
    lnc = {"save_kg_per_lap": 0.05, "seconds_per_lap": 1.2, "feasible": True, "corners": ["T1"]}
    assert fuel_saving_of({"fuel": {"per_lap_kg": 1.5, "lift_coast": lnc}}) is True
    assert fuel_saving_of({"fuel": {"per_lap_kg": 1.5, "lift_coast": None}}) is False
    assert fuel_saving_of({"fuel": None}) is None and fuel_saving_of(None) is None
    g = load_graph()
    ctx = build_context(game="f1_25", fuel_saving=fuel_saving_of({"fuel": {"lift_coast": lnc}}))
    assert g.holds("fuel_saving", ctx) and not g.holds("fuel_saving", build_context(game="f1_25"))


def test_channels_come_from_the_adapters_declared_fields() -> None:
    f1 = channel_status(Game.F1_25.value)
    assert set(f1) == set(CHANNELS) and set(f1.values()) == {"sent"}  # F1 25 declares every channel
    gt7 = channel_status(Game.GT7.value)
    assert gt7["g_lat"] == "not_sent"  # UNSUPPORTED: GT7 sends no lateral g
    assert gt7["wheel_slip"] == "unknown" and gt7["yaw_rate"] == "unknown"  # not declared: never assumed absent
    assert gt7["brake"] == gt7["throttle"] == gt7["position"] == gt7["lap_distance"] == "sent"
    assert channel_status(Game.AC.value)["steering"] == "unknown"  # declared UNVERIFIED (AC sends no unit)
    assert set(channel_status(None).values()) == {"unknown"} == set(channel_status("synthetic").values())
    payload = channels_payload("gt7")
    assert payload["g_lat"] == {"status": "not_sent", "words": "lateral g", "caveat": None}
    assert "traction control" in (payload["throttle"]["caveat"] or "")  # variants A/B: throttle after TCS


def test_acc_channels_and_context_come_from_its_adapter() -> None:
    """ACC (feat/acc): the graph's game value is "acc"; inputs, speed, position and lap distance are sent; g-forces,
    yaw, body slip and tyre slip stay unknown (mapped only after runtime checks, UNVERIFIED), never "not sent"; no
    class, downforce, gearbox or assists are claimed (the TC level setting is not "TC on")."""
    st = channel_status(Game.ACC.value)
    sent = {"brake", "throttle", "steering", "clutch", "gear", "rpm", "speed", "position", "lap_distance"}
    assert {ch for ch, v in st.items() if v == "sent"} == sent
    assert {ch for ch, v in st.items() if v == "unknown"} == {"g_lat", "g_lon", "wheel_slip", "yaw_rate", "body_slip"}
    assert "not_sent" not in st.values()
    assert channels_payload("acc")["yaw_rate"] == {"status": "unknown", "words": "yaw rate", "caveat": None}
    laps = [{"meta": {"traction_control": 3, "abs_active": None}} for _ in range(3)]
    ctx = build_context(
        game="acc", car_id="acc:car:mclaren_720s_gt3", lap_metas=laps, weather={"condition": "light_rain"}
    )
    assert ctx.game == "acc" and ctx.wet is True
    assert (ctx.car_family, ctx.downforce, ctx.gearbox, ctx.abs, ctx.traction_control) == (None,) * 5


@pytest.mark.parametrize("game", [g.value for g in (Game.F1_25, Game.GT7, Game.FORZA_MOTORSPORT, Game.AC, Game.ACC)])
def test_every_game_sends_the_live_coaching_channels(game: str) -> None:
    """The eight live coaching kinds read brake, throttle, speed and lap distance: every adapter sends them, so no
    game loses coaching to the graph."""
    st = channel_status(game)
    assert all(st[ch] == "sent" for ch in ("brake", "throttle", "speed", "lap_distance"))


# ---------------------------------------------------------------------------------------------- style
def _m(corner: str, trail: float | None, coast: float | None = 0.0) -> CornerMetrics:
    braked = trail is not None
    return CornerMetrics(
        corner=corner,
        segment_time_s=10.0,
        brake_start_m=100.0 if braked else None,
        trail_brake_m=trail,
        coast_m=coast if braked else None,
    )


def _laps(per_lap: list[tuple[float | None, float | None]], laps: int) -> dict[str, list[CornerMetrics]]:
    """``laps`` laps of the same corners: ``per_lap`` = (trail braking m, coasting m) per corner."""
    return {f"T{i + 1}": [_m(f"T{i + 1}", t, c) for _ in range(laps)] for i, (t, c) in enumerate(per_lap)}


def test_the_owners_style_is_trail_braking_with_rare_coasting() -> None:
    """The owner's fastest F1 25 laps: trail braking into 40 of 41 braking corners, coasting at 15 % of them."""
    metrics = {f"T{i}": [_m(f"T{i}", 33.0 if i < 40 else 2.0, 12.0 if i < 6 else 0.0)] for i in range(41)}
    metrics["T0"].append(_m("T0", 30.0))  # a second lap
    s = detect_style(metrics)
    assert (s.braking_style, s.coasting, s.laps) == ("trail", "rare", 2)
    assert (s.trail_corners, s.braking_corners) == (41, 42) and s.to_dict()["trail_share"] == pytest.approx(0.976)


def test_braking_style_thresholds_are_inclusive() -> None:
    """Share of braking corners trail-braked: >= 0.6 trail, <= 0.2 straight-line, in between mixed."""
    ten = [(TRAIL_BRAKE_M, 0.0)] * 3 + [(0.0, 0.0)] * 2  # 3 of 5 corners = 0.6
    assert detect_style(_laps(ten, 2)).braking_style == "trail"
    one = [(TRAIL_BRAKE_M, 0.0)] + [(0.0, 0.0)] * 4  # 1 of 5 = 0.2
    assert detect_style(_laps(one, 2)).braking_style == "straight_line"
    two = [(TRAIL_BRAKE_M, 0.0)] * 2 + [(0.0, 0.0)] * 3  # 2 of 5 = 0.4
    assert detect_style(_laps(two, 2)).braking_style == "mixed"
    short = [(TRAIL_BRAKE_M - 0.1, 0.0)] * 5  # just under 10 m with the wheel turned: not trail braking
    assert detect_style(_laps(short, 2)).braking_style == "straight_line"


def test_coasting_thresholds() -> None:
    often = [(0.0, COAST_M)] * 3 + [(0.0, 0.0)] * 3  # half
    assert detect_style(_laps(often, 2)).coasting == "often"
    rare = [(0.0, COAST_M)] + [(0.0, 0.0)] * 4  # one in five
    assert detect_style(_laps(rare, 2)).coasting == "rare"
    between = [(0.0, COAST_M)] * 2 + [(0.0, 0.0)] * 3  # 0.4: neither, unknown
    assert detect_style(_laps(between, 2)).coasting is None


def test_style_needs_enough_laps_and_braking_corners() -> None:
    assert MIN_LAPS == 2 and MIN_BRAKING_CORNERS == 6
    one_lap = detect_style(_laps([(30.0, 0.0)] * 10, 1))
    assert one_lap.braking_style is None and one_lap.coasting is None and not one_lap.enough
    few = detect_style(_laps([(30.0, 0.0)] * 2 + [(None, None)] * 6, 2))  # 4 braking corner-laps
    assert few.braking_corners == 4 and few.braking_style is None
    enough = detect_style(_laps([(30.0, 0.0)] * 3 + [(None, None)] * 6, 2))  # 6: corners with no braking ignored
    assert enough.braking_corners == 6 and enough.braking_style == "trail" and enough.enough
    assert detect_style({}) == Style()


def test_the_braking_assist_flags_the_style_without_changing_it() -> None:
    """The F1 braking assist brakes for the driver: the style is kept and flagged (the screens and the AI engineer say
    some of the braking was the game's), never presented as all the driver's."""
    laps = _laps([(30.0, 0.0)] * 6, 2)
    plain, assisted = detect_style(laps), detect_style(laps, braking_assist=2)
    assert assisted.braking_style == plain.braking_style == "trail" and assisted.assisted and not plain.assisted
    assert assisted.to_dict()["braking_assist"] == 2 and plain.to_dict()["braking_assist"] is None
    assert braking_assist_of({"braking": 1, "gearbox": 3}) == 1
    assert braking_assist_of({"braking": 0}) is None  # off
    assert braking_assist_of({"braking": True}) is None and braking_assist_of(None) is None
    g = load_graph()
    _, text, _, say = _context_fact(g, build_context(game="f1_25", style=assisted), assisted, [])
    assert (
        "braking assist was on" in text
        and say is not None
        and say.endswith("some of that braking was the game's, not yours.")
    )
    _, text, _, say = _context_fact(g, build_context(game="f1_25", style=plain), plain, [])
    assert "assist" not in text and say is not None and "assist" not in say


def _braking_lap(steering: float) -> LapTrace:
    """One 1 km lap at 10 m a sample: a stop from 250 to 90 km/h over 300-420 m with the wheel turned (``steering``,
    NaN = the game sends none), a 30 m roll off both pedals, then full throttle."""
    d = np.arange(0.0, 1000.0, 10.0)
    t = np.cumsum(np.full(len(d), 0.12))
    speed = np.where(d < 300, 250.0, np.where(d < 450, 250.0 - (d - 300) * (160 / 150), 90.0 + (d - 450) * 0.3))
    brake = np.where((d >= 300) & (d < 420), 0.9, 0.0)
    throttle = np.where(d >= 450, 1.0, np.where(d < 290, 1.0, 0.0))
    ch = {k: np.full(len(d), np.nan) for k in LAP_CHANNELS}
    ch.update(
        distance_m=d,
        session_time_s=t,
        lap_time_ms=t * 1000,
        speed_kph=speed,
        brake=brake,
        throttle=throttle,
        steering=np.where((d >= 360) & (d < 470), steering, 0.0 if steering == steering else np.nan),
    )
    return LapTrace(lap_number=1, channels=ch, lap_time_ms=int(t[-1] * 1000), valid=True)


def test_trail_braking_is_unknown_when_the_game_sends_no_steering() -> None:
    """Assetto Corsa (steering not mapped) and GT7 variant A send no steering: a lap's trail braking is then not
    measured (None), never a measured 0 m - and the braking style stays unknown instead of "straight-line"."""
    (with_steering,) = detect_braking(_braking_lap(0.3))
    (no_steering,) = detect_braking(_braking_lap(float("nan")))
    assert with_steering.trail_brake_m is not None and with_steering.trail_brake_m >= TRAIL_BRAKE_M
    assert no_steering.trail_brake_m is None
    assert no_steering.coast_m == pytest.approx(with_steering.coast_m) and no_steering.coast_m >= COAST_M
    # an AC-shaped session: every braking corner without steering, a roll off both pedals at each
    ac = {f"T{i}": [_m(f"T{i}", None, 25.0), _m(f"T{i}", None, 25.0)] for i in range(8)}
    for laps in ac.values():
        for m in laps:
            m.brake_start_m = 100.0
            m.coast_m = 25.0
    s = detect_style(ac)
    assert s.braking_style is None and not s.enough and s.no_steering
    assert (s.braking_corners, s.unsteered_corners, s.coast_measured) == (0, 16, 16)
    assert s.coasting == "often"  # coasting needs only the pedals: still detected
    ctx = build_context(game="ac", style=s)
    g = load_graph()
    assert not g.holds("braking_style_straight_line", ctx) and not g.holds("braking_style_trail", ctx)
    _, text, data, say = _context_fact(g, ctx, s, [])
    assert "braking style not known" in text and "no steering" in text and "straight-line" not in text
    assert say == "I can't tell your braking style here: this game sends no steering."
    assert data["style"]["no_steering"] is True and data["style"]["braking_style"] is None


def test_a_detected_style_satisfies_the_graphs_style_conditions() -> None:
    g = load_graph()
    s = detect_style(_laps([(30.0, 0.0)] * 6, 2))
    ctx = build_context(game="f1_25", style=s)
    assert g.holds("braking_style_trail", ctx) and g.holds("coasting_rare", ctx)
    assert not g.holds("braking_style_straight_line", ctx)
    unknown = build_context(game="f1_25", style=detect_style({}))
    assert not g.holds("braking_style_trail", unknown) and not g.holds("braking_style_straight_line", unknown)
