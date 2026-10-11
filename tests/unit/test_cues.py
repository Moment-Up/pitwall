"""Live braking cues: planning (evidence, modes, safety filters), the per-frame trigger (timing at 20/60 Hz, lap
wrap, rewinds, distance jumps, pit/standing-start/safety-car/quiet suppression, one cue per corner per lap) and the
radio hub's delivery path (pre-synthesised audio, priorities, latency + timing-error measurement).

Constant-speed synthetic inputs make every expected fire point exact: at speed v with lead L and margin M a cue's
key word should start at ``target - v * L - M``; the trigger may quantise that by at most half a frame spacing.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import FactSheet
from pitwall.analysis.distance import DistanceTrace
from pitwall.coach import cues as cues_mod
from pitwall.coach.cues import (
    MARGIN_M,
    NEW_DRIVER,
    NO_DRIVER_REFERENCE,
    CueApproach,
    CueEngine,
    CueEvent,
    CueKind,
    CueLabel,
    CuePlan,
    CueSpec,
    CueTiming,
    FocusLimits,
    FrameSample,
    build_cue_plan,
    cue_labels,
    cue_timing_error_m,
    estimate_word_offset,
    parse_cue_mode,
    reference_braking_zones,
    select_focus_corners,
)
from pitwall.core.live import LiveState
from pitwall.drivers import coaching_limits
from pitwall.model.telemetry import CarFrame, FrameQuality, Game, SessionInfo
from pitwall.voice.hub import (
    CUE_OUTPUT_ALLOWANCE_S,
    CUE_PART_GAP_S,
    CUE_TAIL_PAD_S,
    RadioClient,
    RadioHub,
    compose_cue_clip,
    trim_silence,
)
from pitwall.voice.scheduler import RadioScheduler
from pitwall.voice.speech import to_speech
from pitwall.voice.types import AudioClip, MessageKind, Priority, RadioMessage, SttResult

LENGTH = 3000.0
V = 80.0  # m/s
V_KPH = V * 3.6
REF_ID = 11


# ---------------------------------------------------------------------------------------------- builders
def flat_trace(length: float = LENGTH, v: float = V) -> DistanceTrace:
    """Reference lap at constant speed: time to go over k metres is exactly k / v."""
    d = np.arange(0.0, length, 1.0)
    return DistanceTrace(
        d=d, t_s=d / v, ch={"speed_kph": np.full_like(d, v * 3.6), "brake": np.zeros_like(d)}, lap_number=3
    )


def reference(length: float = LENGTH, v: float = V, lap_id: int = REF_ID) -> dict[str, Any]:
    return {"lap_id": lap_id, "lap_number": 3, "lap_time_ms": round(length / v * 1000)}


def comparison(
    zones: dict[str, float] | None = None,
    *,
    ok: bool = True,
    ref_lap_id: int = REF_ID,
    peak: float = 0.95,
    entry: float | None = V_KPH,
    vmin: float | None = 90.0,
) -> dict[str, Any]:
    zones = {"T1": 1000.0, "T2": 2000.0} if zones is None else zones
    return {
        "compatibility": {"ok": ok, "blocking": [] if ok else ["different car: reference 'a' vs lap 'b'"]},
        "ref_lap_id": ref_lap_id,
        "ref_lap_number": 3,
        "cmp_lap_number": 5,
        "corners": [
            {
                "corner": c,
                "ref": {"brake_start_m": b, "brake_peak": peak, "entry_speed_kph": entry, "min_speed_kph": vmin},
            }
            for c, b in zones.items()
        ],
    }


def obs(
    corner: str, kind: str = "brake_early", conf: float = 0.9, prio: float = 0.2, positive: bool = False
) -> dict[str, Any]:
    return {
        "id": f"L5:{corner}:{kind}",
        "kind": kind,
        "corner": corner,
        "confidence": conf,
        "priority": prio,
        "impact_s": 0.2,
        "positive": positive,
    }


def engine_with(
    mode: str = "all",
    zones: dict[str, float] | None = None,
    observations: list[dict[str, Any]] | None = None,
    latency: float = 0.3,
    margin: float = 5.0,
    trace: DistanceTrace | None = None,
) -> tuple[CueEngine, list[CueEvent]]:
    e = CueEngine(mode, margin_m=margin)
    e.on_reference(reference(), trace if trace is not None else flat_trace())
    e.on_lap_result(observations or [], comparison(zones), LENGTH)
    e.set_timing(CueTiming(latency_s=latency))
    fired: list[CueEvent] = []
    e.set_sink(fired.append)
    return e, fired


def frame(
    lap: int | None,
    d: float | None,
    t: float | None,
    v_kph: float | None = V_KPH,
    *,
    lap_time_ms: int | None = 5000,
    quality: FrameQuality = FrameQuality.OK,
    pit: int | None = 0,
) -> CarFrame:
    return CarFrame(
        game=Game.F1_25,
        t_recv_ns=0,
        session_time_s=t,
        lap_number=lap,
        lap_distance_m=d,
        speed_kph=v_kph,
        current_lap_time_ms=lap_time_ms,
        quality=quality,
        pit_status=pit,
    )


def run(
    e: CueEngine,
    lap: int,
    d0: float,
    d1: float,
    t0: float,
    *,
    hz: float = 60.0,
    v_kph: float = V_KPH,
    lap_t0_ms: int = 5000,
    quality: FrameQuality = FrameQuality.OK,
    pit: int = 0,
) -> float:
    """Constant-speed frames from d0 (inclusive) to d1 (exclusive); now = session time. Returns the end time."""
    v = v_kph / 3.6
    dt = 1.0 / hz
    d, t = d0, t0
    while d < d1:
        lap_ms = lap_t0_ms + round((d - d0) / v * 1000)
        e.on_frame(frame(lap, d, t, v_kph, lap_time_ms=lap_ms, quality=quality, pit=pit), t)
        d += v * dt
        t += dt
    return t


def laps(e: CueEngine, n: int, *, hz: float = 60.0, v_kph: float = V_KPH, start_lap: int = 1) -> None:
    """Drive whole laps continuously (distance carries across the line, like the game)."""
    v = v_kph / 3.6
    dt = 1.0 / hz
    t, d = 100.0, 0.0
    for lap in range(start_lap, start_lap + n):
        while d < LENGTH:
            e.on_frame(frame(lap, d, t, v_kph, lap_time_ms=round(d / v * 1000)), t)
            d += v * dt
            t += dt
        d -= LENGTH


def ideal_fire_m(target: float, lead_s: float, margin: float = 5.0, v: float = V) -> float:
    return target - v * lead_s - margin


# ============================================================================================== planning
def test_parse_cue_mode() -> None:
    assert parse_cue_mode(" Focus ") == "focus"
    assert [parse_cue_mode(m) for m in ("off", "markers", "all")] == ["off", "markers", "all"]
    with pytest.raises(ValueError, match="unknown cue mode"):
        parse_cue_mode("loud")


def test_estimate_word_offset_counts_spoken_words_and_errs_long() -> None:
    w = cues_mod.DEFAULT_WORD_S
    # "T9" is spoken "turn 9" (two words) before "brake", plus the comma pause
    assert estimate_word_offset(("T9", "brake"), 1) == pytest.approx(2 * w + cues_mod.PART_PAUSE_S)
    assert estimate_word_offset(("brake",), 0) == 0.0
    # 2.6 words/s is slower than the TTS voices: the estimate is >= what a voice needs, so cues err early
    assert estimate_word_offset(("T9", "brake"), 1) > 2 / 3.2


def test_reference_braking_zones_only_measured_substantial_braking() -> None:
    comp = comparison({"T1": 1000.0, "T2": 2000.0})
    comp["corners"] += [
        {"corner": "T3", "ref": {"brake_start_m": None, "brake_peak": None}},  # lift corner: no braking event
        {"corner": "T4", "ref": {"brake_start_m": 2500.0, "brake_peak": 0.15}},  # a dab
        {
            "corner": "T5",
            "ref": {"brake_start_m": 2700.0, "brake_peak": 0.9, "entry_speed_kph": 200.0, "min_speed_kph": 192.0},
        },  # barely slows: not a braking zone
        {"corner": "T6", "ref": {"brake_start_m": 3500.0, "brake_peak": 0.9}},  # beyond the lap
        {"corner": "T7", "ref": {"brake_start_m": float("nan"), "brake_peak": 0.9}},
        {"corner": "T8", "ref": {"brake_start_m": True, "brake_peak": 0.9}},  # not a number
        "garbage",
    ]
    zones = reference_braking_zones(comp, LENGTH)
    assert [z.corner for z in zones] == ["T1", "T2"]
    assert zones[0].brake_m == 1000.0 and zones[0].peak == 0.95


def test_select_focus_ranks_braking_evidence_with_decay() -> None:
    zones = ["T1", "T2", "T3", "T4", "T5"]
    history = [
        [obs("T1", prio=0.5)],  # oldest: 0.5 * 0.36
        [obs("T2", prio=0.2), obs("T4", "late_throttle", prio=0.9)],  # throttle problems get no brake cue
        [
            obs("T3", prio=0.25),
            obs("T2", "overspeed_apex", prio=0.1),
            obs("T5", prio=0.9, conf=0.5),  # below the confidence bar
            obs("T1", "exit_gain", prio=0.9, positive=True),  # praise is not a correction
            obs("T9", prio=0.9),  # no reference braking zone there
        ],
    ]
    picked = select_focus_corners(history, zones, max_corners=3)
    # T2: 0.2*0.6 + 0.1 = 0.22, T3: 0.25, T1: 0.5*0.36 = 0.18
    assert [c for c, _ in picked] == ["T3", "T2", "T1"]
    assert dict(picked)["T2"] == "overspeed_apex on 2 of the last 3 lap(s)"
    assert [c for c, _ in select_focus_corners(history, zones, max_corners=1)] == ["T3"]
    assert select_focus_corners(history, zones, max_corners=99)[:3] == picked  # never more than 3
    assert select_focus_corners([], zones) == []


def test_focus_plan_cues_only_the_evidence_corner_at_its_reference_point() -> None:
    plan = build_cue_plan(
        "focus",
        comparison({"T1": 1000.0, "T2": 2000.0, "T3": 2600.0}),
        length_m=LENGTH,
        history=[[obs("T2"), obs("T1", "late_throttle")]],
        reference=reference(),
        trace=flat_trace(),
    )
    assert plan.reason is None and plan.focus == ("T2",)
    (c,) = plan.cues
    assert (c.corner, c.kind, c.target_m, c.parts, c.key_index, c.focus) == (
        "T2",
        CueKind.BRAKE,
        2000.0,
        ("T2", "brake"),
        1,
        True,
    )
    assert c.text == "T2 brake" and plan.ref_lap_id == REF_ID and plan.targets == (2000.0,)


def _austria_payload(**kw: Any) -> dict[str, Any]:
    """Live track model payload of the real Austria learned model (tests/unit/test_track_identity.py), mapped by
    the verified track sheet: learned T2 is Turn 1's exit (T1 (2)), T8 is Turn 9, T9 is Turn 10."""
    from pitwall.analysis.track_identity import identify, track_model_payload
    from tests.unit.test_track_identity import AUSTRIA_ZONES, _austria

    out, mapping = identify(_austria(), zones=AUSTRIA_ZONES, **kw)
    assert mapping is not None
    return track_model_payload(out)


def test_cues_name_corners_as_the_track_view_does() -> None:
    """Regression (README screenshots): a cue said "T2 brake" while the Austria track view lists T1, T3, T4, T6, T7,
    T9 and T10 - the cue used the learned key, the view the official labels. Text and speech now follow the view."""
    payload = _austria_payload()
    labels = cue_labels(payload)
    assert labels["T2"] == CueLabel("T1 (2)", "Turn 1", "Turn 1, second part")
    assert labels["T8"] == CueLabel("T9", "Turn 9", "Turn 9, Rindt Kurve")
    assert labels["T9"] == CueLabel("T10", "Turn 10", "Turn 10")
    view = {t["short"] for t in payload["corner_text"].values()}  # what the track view shows
    zones = {"T2": 335.0, "T3": 1250.0, "T8": 3700.0, "T9": 3944.0}
    length = 4323.0
    kw: dict[str, Any] = {"length_m": length, "reference": reference(length), "trace": flat_trace(length)}
    history = [[obs(c) for c in ("T2", "T8", "T9")]]
    focus = build_cue_plan("focus", comparison(zones), history=history, labels=labels, **kw)
    assert {(c.corner, c.text, c.parts) for c in focus.cues} == {
        ("T2", "T1 (2) brake", ("Turn 1", "brake")),
        ("T8", "T9 brake", ("Turn 9", "brake")),
        ("T9", "T10 brake", ("Turn 10", "brake")),
    }
    assert all(c.key_index == 1 for c in focus.cues)
    markers = build_cue_plan("markers", comparison(zones), labels=labels, **kw)
    assert [(c.text, c.parts) for c in markers.cues] == [
        ("T1 (2)", ("Turn 1",)),
        ("T3", ("Turn 3",)),
        ("T9", ("Turn 9",)),
        ("T10", ("Turn 10",)),
    ]
    every = build_cue_plan("all", comparison(zones), labels=labels, **kw)
    assert [c.text for c in every.cues] == ["T1 (2) brake", "T3 brake", "T9 brake", "T10 brake"]
    for plan in (focus, markers, every):  # every name a cue shows is one the track view shows
        assert {c.text.removesuffix(" brake") for c in plan.cues} <= view
        assert "T2 brake" not in {c.text for c in plan.cues}
        assert all(to_speech(p) != "turn 2" for c in plan.cues for p in c.parts)


def test_two_parts_of_one_turn_never_sound_the_same() -> None:
    """Learned T1 and T2 are Turn 1 and its second part ("T1", "T1 (2)"): both have the short spoken name "Turn 1".
    A call for each would sound identical for two different braking points; the later one says "second part"."""
    labels = cue_labels(_austria_payload())
    assert labels["T1"].spoken == labels["T2"].spoken == "Turn 1"
    zones = {"T1": 250.0, "T2": 335.0, "T3": 1250.0}
    length = 4323.0
    kw: dict[str, Any] = {"length_m": length, "reference": reference(length), "trace": flat_trace(length)}
    focus = build_cue_plan("focus", comparison(zones), history=[[obs("T2"), obs("T1")]], labels=labels, **kw)
    said = {c.corner: c.parts for c in focus.cues}
    assert said == {"T1": ("Turn 1", "brake"), "T2": ("Turn 1, second part", "brake")}
    assert {c.text for c in focus.cues} == {"T1 (1) brake", "T1 (2) brake"}  # the displays already differed
    assert all(c.key_index == 1 for c in focus.cues)
    markers = build_cue_plan("markers", comparison(zones), labels=labels, **kw)
    assert [c.parts for c in markers.cues] == [("Turn 1",), ("Turn 1, second part",), ("Turn 3",)]
    alone = build_cue_plan("focus", comparison(zones), history=[[obs("T2")]], labels=labels, **kw)
    assert [c.parts for c in alone.cues] == [("Turn 1", "brake")]  # no other Turn 1 call: the short name is enough


def test_cue_labels_need_identity_and_never_fail() -> None:
    from pitwall.analysis.track_identity import track_model_payload
    from tests.unit.test_track_identity import _austria

    learned = track_model_payload(_austria())  # no sheet applied: learned names everywhere, as before
    assert cue_labels(learned) == {} and cue_labels(None) == {}
    for broken in ({"corners": "x"}, {"corners": [None, {"name": 3}], "corner_text": {}}, {"corner_text": []}):
        assert cue_labels(broken) == {}
    names_only = {
        "corners": [
            {"name": "T1", "identity_tier": "sheet_verified", "display_name": "Rindt Kurve", "voice_ok": True},
            {"name": "T2", "identity_tier": None},
        ],
        "corner_text": {
            "T1": {"short": "Rindt Kurve", "long": "Rindt Kurve", "voice": "Rindt Kurve"},
            "T2": {"short": "565 m", "long": "Corner at 565 m", "voice": "Corner at 570 metres"},
        },
    }
    labels = cue_labels(names_only)
    assert labels == {
        "T1": CueLabel("Rindt Kurve", "Rindt Kurve", "Rindt Kurve"),
        "T2": CueLabel("565 m", None, "Corner at 570 metres"),  # unlabelled on a mapped model: never "T2"
    }
    kw: dict[str, Any] = {"length_m": LENGTH, "reference": reference(), "trace": flat_trace(), "labels": labels}
    plan = build_cue_plan("focus", comparison(), history=[[obs("T2")]], **kw)
    assert [(c.text, c.parts, c.key_index) for c in plan.cues] == [("565 m brake", ("brake",), 0)]
    plan = build_cue_plan("markers", comparison(), **kw)
    assert [c.parts for c in plan.cues] == [("Rindt Kurve",), ("Corner at 570 metres",)]


def test_live_state_passes_the_track_views_names_to_the_cues() -> None:
    live = LiveState()
    live.set_track_model({**_austria_payload(), "length_m": LENGTH})
    live.set_reference(reference(), flat_trace())
    live.cues.set_mode("all")
    live.on_lap_result({"lap_id": 1}, [], comparison({"T8": 1000.0, "T9": 2000.0}))
    assert [c.text for c in live.cues.plan.cues] == ["T9 brake", "T10 brake"]
    live.set_track_model({"length_m": LENGTH, "corners": []})  # a model without identity: learned names again
    assert [c.text for c in live.cues.plan.cues] == ["T8 brake", "T9 brake"]
    live.set_track_model({**_austria_payload(), "length_m": LENGTH})
    live.reset_session("s2", "udp", False)  # another session may be another track: its model brings its names
    live.on_session(SessionInfo(game=Game.F1_25, safety_car_status="none", track_length_m=LENGTH))
    live.set_reference(reference(), flat_trace())
    live.on_lap_result({"lap_id": 1}, [], comparison({"T8": 1000.0, "T9": 2000.0}))
    assert [c.text for c in live.cues.plan.cues] == ["T8 brake", "T9 brake"]


def test_markers_and_all_modes_cover_every_braking_zone() -> None:
    kw: dict[str, Any] = {"length_m": LENGTH, "reference": reference(), "trace": flat_trace()}
    markers = build_cue_plan("markers", comparison({"T2": 2000.0, "T1": 1000.0}), **kw)
    assert [(c.corner, c.kind, c.parts, c.anticipation_s) for c in markers.cues] == [
        ("T1", CueKind.MARKER, ("T1",), cues_mod.MARKER_LEAD_S),
        ("T2", CueKind.MARKER, ("T2",), cues_mod.MARKER_LEAD_S),
    ]
    all_ = build_cue_plan("all", comparison(), **kw)
    assert [(c.text, c.parts, c.key_index) for c in all_.cues] == [
        ("T1 brake", ("brake",), 0),
        ("T2 brake", ("brake",), 0),
    ]


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"mode": "off"}, "cues off"),
        ({"comparison": None}, "no reference lap yet"),
        ({"comparison": comparison(ok=False)}, "reference not usable: different car"),
        ({"comparison": {"corners": []}}, "reference not usable: compatibility unknown"),
        ({"length_m": None}, "track length unknown"),
        ({"trace": None}, "reference lap trace not available"),
        ({"reference": reference(lap_id=99)}, "reference lap trace not available"),  # trace of another lap
        ({"comparison": comparison({})}, "no measured braking zones"),
        ({"mode": "focus", "history": []}, "no braking corrections to focus on"),
        ({"mode": "focus", "history": [[obs("T1", conf=0.4)]]}, "no braking corrections to focus on"),
    ],
)
def test_no_cues_without_evidence(kwargs: dict[str, Any], reason: str) -> None:
    args: dict[str, Any] = {
        "mode": "all",
        "comparison": comparison(),
        "length_m": LENGTH,
        "reference": reference(),
        "trace": flat_trace(),
        **kwargs,
    }
    mode, comp = args.pop("mode"), args.pop("comparison")
    plan = build_cue_plan(mode, comp, **args)
    assert plan.cues == ()
    assert plan.reason is not None and plan.reason.startswith(reason)


def test_reapplication_inside_a_braking_zone_is_never_called() -> None:
    """The analysis matches a corner to its *latest* braking event; a re-application while already slowing (real
    braking began earlier) is not a braking point."""
    d = np.arange(0.0, LENGTH, 1.0)
    v = np.full_like(d, V)
    v[(d >= 1700) & (d < 1850)] = np.linspace(V, 25.0, int(np.sum((d >= 1700) & (d < 1850))))
    v[d >= 1850] = 25.0
    t = np.concatenate([[0.0], np.cumsum(1.0 / v[:-1])])
    trace = DistanceTrace(d=d, t_s=t, ch={"speed_kph": v * 3.6}, lap_number=3)
    plan = build_cue_plan(
        "all",
        comparison({"T1": 1000.0, "T3": 1856.0}),
        length_m=LENGTH,
        reference={"lap_id": REF_ID, "lap_time_ms": round(float(t[-1]) * 1000)},
        trace=trace,
    )
    assert [c.corner for c in plan.cues] == ["T1"]


def test_approach_table_constant_speed_and_wrap() -> None:
    plan = build_cue_plan("all", comparison({"T1": 30.0}), length_m=LENGTH, reference=reference(), trace=flat_trace())
    app = plan.approaches[0]
    assert app is not None
    assert app.ttg_s[0] == pytest.approx(0.0)
    assert app.ttg_s[20] == pytest.approx(20 / V)
    # 100 m before a target 30 m past the line: 70 m on the previous lap + 30 m, via the reference lap time
    assert app.ttg_s[100] == pytest.approx(100 / V, abs=0.02)
    assert app.v_mps[100] == pytest.approx(V)


# ============================================================================================== trigger timing
@pytest.mark.parametrize("hz", [60.0, 20.0])
def test_fires_within_half_a_frame_of_the_intended_point(hz: float) -> None:
    e, fired = engine_with("all", latency=0.3)
    laps(e, 1, hz=hz)
    assert [ev.cue.corner for ev in fired] == ["T1", "T2"]
    half_frame_m = 0.5 * V / hz
    for ev in fired:
        late_m = ev.d_m - ideal_fire_m(ev.cue.target_m, 0.3)  # + = key word after the aim point
        assert abs(late_m) <= half_frame_m + 1e-6
        # one-sided: it may use the margin, never pass the reference point (coaching never pushes braking later)
        assert late_m <= MARGIN_M and ev.d_m + V * 0.3 <= ev.cue.target_m
        assert ev.aim_m == pytest.approx(ev.cue.target_m - 5.0)
        assert ev.lap == ev.fired_lap == 1 and ev.path == "pcm" and ev.word_offset_s == 0.0


def test_key_word_offset_and_latency_move_the_fire_point() -> None:
    e, fired = engine_with("focus", observations=[obs("T2")], latency=0.4)
    e.set_timing(CueTiming(latency_s=0.4, offsets_s={("T2", "brake"): 0.55}))
    laps(e, 1)
    (ev,) = fired
    assert ev.word_offset_s == 0.55 and ev.latency_s == 0.4
    assert abs(ev.d_m - ideal_fire_m(2000.0, 0.4 + 0.55)) <= 0.5 * V / 60 + 1e-6


def test_unmeasured_phrase_falls_back_to_the_long_word_estimate() -> None:
    e, fired = engine_with("focus", observations=[obs("T2")], latency=0.3)
    laps(e, 1)
    (ev,) = fired
    assert ev.word_offset_s == pytest.approx(estimate_word_offset(("T2", "brake"), 1))


def test_marker_aim_uses_time_not_distance() -> None:
    e, fired = engine_with("markers", latency=0.3)
    laps(e, 1)
    assert [ev.cue.corner for ev in fired] == ["T1", "T2"]
    for ev in fired:
        # constant speed: 2 s of anticipation is 160 m
        assert ev.aim_m == pytest.approx(ev.cue.target_m - 5.0 - 2.0 * V, abs=1.0)
        assert abs(ev.d_m - ideal_fire_m(ev.cue.target_m, 0.3 + 2.0)) <= 0.5 * V / 60 + 1e-6


def test_late_frame_after_lost_frames_is_dropped_not_said_past_the_reference_point() -> None:
    """Target 1000 m at 80 m/s, latency 0.3 s: the ideal call is at 971 m. The last frame before a 0.26 s gap
    (lost UDP frames) is at 960 m, the next at 981 m: calling there would put "brake" at 1005 m, 5 m past the
    point. Dropped."""
    e, fired = engine_with("all", zones={"T1": 1000.0, "T2": 2000.0}, latency=0.3)
    t = run(e, 1, 0.0, 961.0, 100.0)
    assert fired == []
    e.on_frame(frame(1, 981.0, t + 0.26), t + 0.26)
    run(e, 1, 982.0, LENGTH, t + 0.27)
    assert [ev.cue.corner for ev in fired] == ["T2"] and e.missed == 1


def test_late_frame_inside_the_margin_still_calls_before_the_point() -> None:
    """A late frame that leaves the key word between the aim point and the reference point uses the margin."""
    e, fired = engine_with("all", zones={"T1": 1000.0, "T2": 2000.0}, latency=0.3)
    t = run(e, 1, 0.0, 961.0, 100.0)
    e.on_frame(frame(1, 974.0, t + 0.17), t + 0.17)  # word at 974 + 24 = 998 m: 3 m late vs the aim, 2 m early
    (ev,) = fired
    assert ev.d_m == 974.0 and ev.d_m + V * 0.3 <= ev.cue.target_m and e.missed == 0
    assert ev.deadline_mono == pytest.approx(ev.fired_mono + (26.0 / V - 0.3))  # 25 ms of hand-off slack left


def test_markers_dropped_when_the_name_would_land_inside_the_anticipation() -> None:
    e, fired = engine_with("markers", zones={"T1": 1000.0, "T2": 2000.0}, latency=0.3)
    t = run(e, 1, 0.0, 780.0, 100.0)  # marker call point: 1000 - 80 * 2.3 - 5 = 811 m
    e.on_frame(frame(1, 830.0, t + 0.3), t + 0.3)  # name at 854 m: less than 2 s (160 m) before the point
    run(e, 1, 831.0, LENGTH, t + 0.31)
    assert [ev.cue.corner for ev in fired] == ["T2"] and e.missed == 1


def test_time_to_go_uses_the_earlier_of_constant_speed_and_reference() -> None:
    ttg = np.array([0.0, 0.5, 1.0])
    vel = np.array([90.0, 90.0, 90.0])
    from array import array

    app = CueApproach(array("d", ttg.tolist()), array("d", vel.tolist()))
    # reference still accelerating: k=2 m takes 1.0 s * 90/80 there vs 2/80 at constant speed -> min
    ttg_s, v_ref = cues_mod._time_to_go(app, 2.0, 80.0)
    assert ttg_s == pytest.approx(2.0 / 80.0) and v_ref == 90.0
    assert cues_mod._time_to_go(None, 160.0, 80.0) == (2.0, None)
    assert cues_mod._time_to_go(app, 50.0, 80.0) == (50.0 / 80.0, None)  # beyond the table


# ============================================================================================== lap handling
def test_lap_wrap_calls_the_next_laps_first_corner_before_the_line_once() -> None:
    # T1 30 m past the line, lead 1 s at 80 m/s: the call is due 55 m before the line, on the previous lap
    e, fired = engine_with("all", zones={"T1": 30.0, "T2": 1500.0}, latency=1.0)
    laps(e, 3)
    got = [(ev.cue.corner, ev.lap, ev.fired_lap) for ev in fired]
    # lap 1 starts at the line, already too late for its T1: skipped, not called late
    assert got == [("T2", 1, 1), ("T1", 2, 1), ("T2", 2, 2), ("T1", 3, 2), ("T2", 3, 3), ("T1", 4, 3)]
    wrapped = fired[1]
    assert wrapped.d_m == pytest.approx(LENGTH + ideal_fire_m(30.0, 1.0), abs=0.5 * V / 60 + 1e-6)
    assert wrapped.aim_m == pytest.approx(25.0)
    assert e.missed == 1


@pytest.mark.parametrize("order", ["lap_first", "distance_first"])
def test_line_crossing_in_either_field_order_never_repeats_a_call(order: str) -> None:
    """Lap number and distance may disagree for a frame at the line; the lap token must stay consistent."""
    e, fired = engine_with("all", zones={"T1": 30.0, "T2": 1500.0}, latency=1.0)
    t = run(e, 1, 0.0, LENGTH - 10.0, 100.0)  # T1 of lap 2 called before the line
    assert [(ev.cue.corner, ev.lap) for ev in fired] == [("T2", 1), ("T1", 2)]
    if order == "lap_first":  # lap number advances while the distance still reads the end of the lap
        e.on_frame(frame(2, LENGTH - 5.0, t), t)
    else:  # distance wraps while the lap number still reads lap 1
        e.on_frame(frame(1, 2.0, t), t)
    run(e, 2, 3.0, 1000.0, t + 0.1)
    assert [(ev.cue.corner, ev.lap) for ev in fired] == [("T2", 1), ("T1", 2)]


def test_flashback_after_the_call_does_not_repeat_it() -> None:
    e, fired = engine_with("all", latency=0.3)
    t = run(e, 1, 0.0, 1500.0, 100.0)
    assert [ev.cue.corner for ev in fired] == ["T1"]
    # flashback: game clock and distance go back to before T1's call point
    t = run(e, 1, 600.0, LENGTH, t - 12.0)
    assert [ev.cue.corner for ev in fired] == ["T1", "T2"]  # T1 once per lap, T2 still called


def test_rewind_before_the_call_point_still_calls_once() -> None:
    e, fired = engine_with("all", latency=0.3)
    t = run(e, 1, 0.0, 850.0, 100.0)
    t = run(e, 1, 500.0, LENGTH, t - 4.0)
    assert [ev.cue.corner for ev in fired] == ["T1", "T2"]
    assert abs(fired[0].d_m - ideal_fire_m(1000.0, 0.3)) <= 0.5 * V / 60 + 1e-6


def test_distance_jump_over_the_call_point_skips_instead_of_calling_late() -> None:
    """Real F1 data can jump ~150 m in one frame (reset to track)."""
    e, fired = engine_with("all", latency=1.0)  # T1 call point at 915 m
    t = run(e, 1, 0.0, 880.0, 100.0)
    e.on_frame(frame(1, 960.0, t), t)  # 45 m past the call point: the word would land late
    run(e, 1, 961.0, LENGTH, t + 1 / 60)
    assert [ev.cue.corner for ev in fired] == ["T2"]
    assert e.missed == 1


def test_jump_past_the_target_counts_as_missed() -> None:
    e, fired = engine_with("all", latency=0.3)
    t = run(e, 1, 0.0, 700.0, 100.0)
    run(e, 1, 1150.0, LENGTH, t)
    assert [ev.cue.corner for ev in fired] == ["T2"] and e.missed == 1


def test_plan_swap_mid_lap_keeps_one_call_per_corner() -> None:
    e, fired = engine_with("all", latency=0.3)
    t = run(e, 1, 0.0, 1200.0, 100.0)
    e.on_lap_result([], comparison(), LENGTH)  # a new plan object for the same corners
    run(e, 1, 1200.0, LENGTH, t)
    laps(e, 1, start_lap=2)
    assert [(ev.cue.corner, ev.lap) for ev in fired] == [("T1", 1), ("T2", 1), ("T1", 2), ("T2", 2)]


def test_pit_lane_blocks_the_rest_of_that_lap() -> None:
    e, fired = engine_with("all", latency=0.3)
    t = run(e, 1, 0.0, 200.0, 100.0, pit=1)  # out lap: pit exit
    t = run(e, 1, 200.0, LENGTH, t)
    assert fired == []
    run(e, 2, 0.0, LENGTH, t)
    assert [(ev.cue.corner, ev.lap) for ev in fired] == [("T1", 2), ("T2", 2)]


def test_standing_start_lap_one_has_no_cues() -> None:
    e, fired = engine_with("all", latency=0.3)
    t = run(e, 1, 132.0, LENGTH, 100.0, lap_t0_ms=0)  # grid 132 m past the line, lap clock at 0
    assert fired == []
    run(e, 2, 0.0, LENGTH, t)
    assert len(fired) == 2


def test_joined_mid_lap_one_is_not_a_standing_start() -> None:
    e, fired = engine_with("all", latency=0.3)
    run(e, 1, 500.0, LENGTH, 100.0, lap_t0_ms=20_000)
    assert len(fired) == 2


def test_standing_start_lap_still_calls_lap_two_first_corner_before_the_line() -> None:
    """Lap 1 from the grid gets no cues, but its end is a flying approach to lap 2's T1."""
    e, fired = engine_with("all", zones={"T1": 30.0, "T2": 1500.0}, latency=1.0)
    t = run(e, 1, 132.0, LENGTH, 100.0, lap_t0_ms=0)
    assert [(ev.cue.corner, ev.lap, ev.fired_lap) for ev in fired] == [("T1", 2, 1)]
    run(e, 2, 0.0, LENGTH, t)
    assert [(ev.cue.corner, ev.lap) for ev in fired] == [("T1", 2), ("T2", 2), ("T1", 3)]


def test_final_race_lap_makes_no_call_for_a_lap_that_is_never_driven() -> None:
    """A 3-lap race: lap 3's end gets no pre-line call for lap 4, and nothing is called after the flag (the real
    F1 25 distance wraps one frame before the car is marked finished)."""
    e, fired = engine_with("markers", zones={"T1": 120.0, "T2": 1500.0}, latency=0.3)
    e.on_session_info("none", 3, "race")
    laps(e, 3)
    assert [(ev.cue.corner, ev.lap) for ev in fired] == [
        ("T2", 1), ("T1", 2), ("T2", 2), ("T1", 3), ("T2", 3)
    ]  # fmt: skip
    t = 100.0 + 3 * LENGTH / V
    assert e.on_frame(frame(3, 2.0, t), t) is None  # the wrap frame: token 4 is past the flag
    run(e, 4, 3.0, 400.0, t + 0.02)  # cool-down lap at racing speed
    assert len(fired) == 5 and e.snapshot()["next"] is None and e.seconds_to_next_cue() is None


def test_race_length_unknown_keeps_every_lap_open() -> None:
    e, fired = engine_with("markers", zones={"T1": 120.0, "T2": 1500.0}, latency=0.3)
    e.on_session_info("none", 3, "unknown")  # not known to be a race: lap 4 may follow
    laps(e, 3)
    assert ("T1", 4) in [(ev.cue.corner, ev.lap) for ev in fired]
    e2, fired2 = engine_with("markers", zones={"T1": 120.0, "T2": 1500.0}, latency=0.3)
    e2.on_session_info("none", None, "race")  # race of unknown length
    laps(e2, 3)
    assert ("T1", 4) in [(ev.cue.corner, ev.lap) for ev in fired2]


AUSTRIA_RACE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
)


@pytest.mark.recorded
@pytest.mark.skipif(not AUSTRIA_RACE.exists(), reason="real PS5 Austria excerpt not present")
@pytest.mark.parametrize("race_info", [True, False])
def test_recorded_austria_race_final_lap_gets_no_call_for_lap_four(race_info: bool) -> None:
    """RECORDED frames (real F1 25 PS5 3-lap Austria race excerpt: standing start, both line crossings and the
    chequered flag) through LiveState; the cue plan itself is hand-made (a T1 marker 120 m past the line, the
    case where the pre-line call falls ~45 m before the flag). With the game's SessionInfo (race, 3 laps) the
    final lap makes no call for lap 4; without it (control) the same frames would."""
    from pitwall.adapters.f1.adapter import F1Adapter
    from pitwall.ingest.capture import CaptureReader

    live = LiveState()
    spec = CueSpec("T1", CueKind.MARKER, 120.0, "T1", ("T1",), 0, anticipation_s=cues_mod.MARKER_LEAD_S)
    live.set_cue_plan(CuePlan(mode="markers", cues=(spec,), approaches=(None,), targets=(120.0,), length_m=4323.0))
    live.cues.set_timing(CueTiming(latency_s=0.3))
    fired: list[CueEvent] = []
    live.cues.set_sink(fired.append)
    adapter = F1Adapter()
    for p in CaptureReader(AUSTRIA_RACE):
        for item in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(item, CarFrame):
                live.on_frame(item)
            elif isinstance(item, SessionInfo) and race_info:
                live.on_session(item)
    calls = [(ev.lap, ev.fired_lap) for ev in fired]
    # lap 1 is a standing start, but its end is a flying approach to lap 2's T1
    assert calls[:2] == [(2, 1), (3, 2)]
    assert calls == ([(2, 1), (3, 2)] if race_info else [(2, 1), (3, 2), (4, 3)])
    assert live.cues.errors == 0


@pytest.mark.parametrize("status", ["full", "virtual", "formation_lap"])
def test_safety_car_suppresses_cues(status: str) -> None:
    e, fired = engine_with("all", latency=0.3)
    e.on_session_info(status)
    t = run(e, 1, 0.0, LENGTH, 100.0)
    assert fired == [] and e.suppressed == 2
    e.on_session_info("none")
    run(e, 2, 0.0, LENGTH, t)
    assert len(fired) == 2
    e.on_session_info(None)  # unknown is not assumed to be a safety car
    assert e.snapshot()["muted"] is None


def test_muted_cues_are_resolved_not_said_late() -> None:
    e, fired = engine_with("all", latency=0.3)
    e.set_muted("quiet mode")
    t = run(e, 1, 0.0, 1500.0, 100.0)
    e.set_muted(None)  # unmuted after T1's call point: T1 must not be said late
    t = run(e, 1, 1500.0, LENGTH, t)
    assert [ev.cue.corner for ev in fired] == ["T2"] and e.suppressed == 1
    run(e, 2, 0.0, LENGTH, t)
    assert [ev.cue.corner for ev in fired] == ["T2", "T1", "T2"]


def test_no_sink_means_no_firing() -> None:
    e, fired = engine_with("all")
    e.set_sink(None)
    laps(e, 1)
    assert fired == [] and e.fired == 0 and e.suppressed == 2
    assert e.snapshot()["armed"] is False


@pytest.mark.parametrize(
    "kw",
    [
        {"v_kph": 40.0},
        {"quality": FrameQuality.PAUSED},
        {"quality": FrameQuality.NOT_RACING},
        {"quality": FrameQuality.REPLAY_OR_SPECTATING},
    ],
)
def test_no_cues_when_not_racing_at_speed(kw: dict[str, Any]) -> None:
    e, fired = engine_with("all")
    run(e, 1, 0.0, LENGTH, 100.0, **kw)
    assert fired == []


def test_faster_than_reference_approach_suppresses_brake_calls_not_markers() -> None:
    """DRS / a tow: the reference braking point would be too late for this speed (never cue later braking)."""
    e, fired = engine_with("all", latency=0.3)
    laps(e, 1, v_kph=V_KPH * 1.06)
    assert fired == [] and e.suppressed == 2
    e2, fired2 = engine_with("markers", latency=0.3)
    laps(e2, 1, v_kph=V_KPH * 1.06)
    assert len(fired2) == 2
    e3, fired3 = engine_with("all", latency=0.3)
    laps(e3, 1, v_kph=V_KPH * 1.02)  # inside the tolerance
    assert len(fired3) == 2


def test_one_cue_per_corner_per_lap_over_many_laps() -> None:
    e, fired = engine_with("all", latency=0.3)
    laps(e, 5)
    per_lap: dict[tuple[int, str], int] = {}
    for ev in fired:
        per_lap[(ev.lap, ev.cue.corner)] = per_lap.get((ev.lap, ev.cue.corner), 0) + 1
    assert per_lap == {(lap, c): 1 for lap in range(1, 6) for c in ("T1", "T2")}


def test_engine_never_raises_into_ingest() -> None:
    e, _ = engine_with("all")

    def broken(ev: CueEvent) -> None:
        raise RuntimeError("radio exploded")

    e.set_sink(broken)
    assert e.on_frame(frame(None, 10.0, 1.0)) is None
    assert e.on_frame(frame(1, float("nan"), 1.0)) is None
    assert e.on_frame(frame(1, 10.0, 1.0, v_kph=None)) is None
    assert e.on_frame(frame(1, 10.0, None, v_kph=float("inf"))) is None
    run(e, 1, 0.0, LENGTH, 100.0)  # the broken sink is called and contained
    assert e.fired == 2 and e.errors == 2
    e2 = CueEngine("all")
    e2._leads = []  # corrupt internal state: the hook must still not raise
    e2.set_plan(
        CuePlan(
            mode="all",
            cues=(CueSpec("T1", CueKind.BRAKE, 10.0, "T1 brake", ("brake",), 0),),
            approaches=(None,),
            targets=(10.0,),
            length_m=LENGTH,
        )
    )
    e2._timing_used = e2._timing  # skip the recompute so the bad state is used
    e2._active = e2.plan
    e2.set_sink(lambda ev: None)
    assert e2.on_frame(frame(1, 5.0, 1.0), 1.0) is None and e2.errors == 1


def test_low_speed_does_not_consume_the_corner() -> None:
    """Crawling past the call point (spin, yellow) resolves nothing; the corner is then passed = missed."""
    e, fired = engine_with("all", latency=0.3)
    t = run(e, 1, 0.0, 950.0, 100.0)
    t = run(e, 1, 950.0, 1100.0, t, v_kph=30.0)
    run(e, 1, 1100.0, LENGTH, t)
    assert [ev.cue.corner for ev in fired] == ["T2"] and e.missed == 1


# ============================================================================================== planner state
def test_history_resets_when_the_reference_changes() -> None:
    e, _ = engine_with("focus", observations=[obs("T1")])
    assert [c.corner for c in e.plan.cues] == ["T1"]
    e.on_reference(reference(lap_id=12), flat_trace())
    e.on_lap_result([], comparison(ref_lap_id=12), LENGTH)  # new reference: old evidence is not comparable
    assert e.plan.cues == () and e.plan.reason == "no braking corrections to focus on"


def test_cleared_reference_never_leaves_the_previous_drivers_cues() -> None:
    """LapProcessor's sequence when the session's owner changes to a driver with no reference at this track:
    ``set_reference(None, None)`` then a lap published with no comparison. The previous driver's plan must not
    survive (or be rebuilt from the cached trace of their reference lap)."""
    live = LiveState()
    live.set_track_model({"length_m": LENGTH, "corners": []})
    live.cues.set_mode("focus")
    live.set_reference(reference(), flat_trace())
    live.on_lap_result({"lap_id": 5}, [obs("T2")], comparison())
    assert [c.text for c in live.cues.plan.cues] == ["T2 brake"]
    fired: list[CueEvent] = []
    live.cues.set_sink(fired.append)
    live.cues.set_timing(CueTiming(latency_s=0.3))
    live.set_reference(None, None)
    assert not live.cues.plan.cues and live.cues.plan.reason == NO_DRIVER_REFERENCE
    live.on_lap_result({"lap_id": 6}, [], None)  # the new owner's lap: no reference, no comparison
    assert not live.cues.plan.cues and live.cues.plan.reason == NO_DRIVER_REFERENCE
    live.cues.set_mode("all")  # a replan from the stored inputs has nothing of the old reference left
    assert not live.cues.plan.cues and live.cues.plan.reason == NO_DRIVER_REFERENCE
    v, dt, d, t = V, 1 / 60, 0.0, 10.0
    while d < LENGTH:
        live.on_frame(frame(4, d, t))
        d, t = d + v * dt, t + dt
    assert fired == []
    # the new owner's own reference and comparison bring their own cues
    live.set_reference(reference(lap_id=20), flat_trace())
    live.on_lap_result({"lap_id": 7}, [], comparison({"T1": 900.0}, ref_lap_id=20))
    assert [(c.corner, c.target_m) for c in live.cues.plan.cues] == [("T1", 900.0)]
    assert live.cues.plan.ref_lap_id == 20


def test_new_reference_makes_the_comparison_against_the_old_one_stale() -> None:
    e, _ = engine_with("all")
    assert e.plan.ref_lap_id == REF_ID
    e.on_reference(reference(lap_id=12), flat_trace())  # published right before the comparison against it
    assert not e.plan.cues and e.plan.ref_lap_id is None
    e.on_lap_result([], comparison({"T1": 1200.0}, ref_lap_id=12), LENGTH)
    assert [c.target_m for c in e.plan.cues] == [1200.0] and e.plan.ref_lap_id == 12


def test_a_different_driver_in_the_seat_drops_the_plan_until_their_own_lap() -> None:
    e, fired = engine_with("all")
    e.set_driver(1)  # first call: only records who is seated
    assert [c.corner for c in e.plan.cues] == ["T1", "T2"]
    e.set_driver(1, coaching_limits("advanced"))  # a profile edit of the same driver keeps the plan
    assert [c.corner for c in e.plan.cues] == ["T1", "T2"]
    e.set_driver(2, coaching_limits("beginner"))
    assert not e.plan.cues and e.plan.reason == NEW_DRIVER
    laps(e, 1)
    assert fired == []
    # the analysis compares the new owner's lap against a reference it does not republish (cached by lap id)
    e.on_lap_result([], comparison(), LENGTH)
    assert [c.corner for c in e.plan.cues] == ["T1", "T2"]
    e.reset_session()
    assert e.focus_limits == FocusLimits.from_profile(coaching_limits("beginner"))  # profile survives sessions


def test_live_state_passes_the_seated_driver_to_the_cues() -> None:
    live = LiveState()
    live.on_driver(1, coaching_limits("beginner"))
    assert live.cues.focus_limits.max_corners == 1 and live.cues.focus_limits.min_confidence == 0.75
    live.set_track_model({"length_m": LENGTH, "corners": []})
    live.set_reference(reference(), flat_trace())
    live.on_lap_result({"lap_id": 2}, [], comparison())
    live.cues.set_mode("all")
    assert len(live.cues.plan.cues) == 2
    live.on_driver(2, None)  # someone else got in: default limits, and nothing of driver 1's left to call
    assert live.cues.focus_limits == FocusLimits() and not live.cues.plan.cues


def test_focus_corners_follow_the_drivers_coaching_profile() -> None:
    """A beginner's radio would never voice a 0.65-confidence, 0.04 s point; neither does their cue."""
    weak = obs("T3", conf=0.65)
    weak["impact_s"] = 0.04
    strong = [obs("T1", conf=0.8, prio=0.3), obs("T2", conf=0.8, prio=0.2)]
    zones = {"T1": 1000.0, "T2": 2000.0, "T3": 2600.0}
    e, _ = engine_with("focus", zones=zones, observations=[weak, *strong])
    assert list(e.plan.focus) == ["T1", "T2", "T3"]  # default limits (the advanced profile)
    e.set_focus_limits(FocusLimits.from_profile(coaching_limits("beginner")))
    assert list(e.plan.focus) == ["T1"]  # weak point filtered out, and one focus corner a lap
    e.set_focus_limits(FocusLimits.from_profile(coaching_limits("intermediate")))
    assert list(e.plan.focus) == ["T1", "T2"]  # 0.65 meets intermediate confidence, but 0.04 s is under its 0.05 s
    unknown = obs("T3")
    del unknown["impact_s"]
    unknown["priority"] = 0.9
    assert select_focus_corners([[unknown]], zones, limits=FocusLimits(min_impact_s=0.1)) == []  # unknown != small
    assert [c for c, _ in select_focus_corners([[unknown]], zones)] == ["T3"]
    narrowed = FocusLimits(allowed_kinds=frozenset({"overspeed_apex", "late_throttle"}))
    assert select_focus_corners([[obs("T1"), obs("T2", "overspeed_apex"), obs("T3", "late_throttle")]], zones,
                                limits=narrowed) == [("T2", "overspeed_apex on 1 of the last 1 lap(s)")]  # fmt: skip
    assert FocusLimits(min_confidence=0.1).to_dict()["min_confidence"] == 0.1
    assert select_focus_corners([[obs("T1", conf=0.5)]], zones, limits=FocusLimits(min_confidence=0.1)) == []
    e.set_focus_limits(None)
    assert list(e.plan.focus) == ["T1", "T2", "T3"] and e.snapshot()["focus_limits"]["max_corners"] == 3
    for bad in ({"min_confidence": 1.5}, {"min_impact_s": float("nan")}, {"max_corners": 0}):
        with pytest.raises(ValueError):
            FocusLimits(**bad)


def test_focus_follows_recent_laps() -> None:
    e, _ = engine_with("focus", observations=[obs("T1")])
    for _ in range(3):
        e.on_lap_result([obs("T2", prio=0.05)], comparison(), LENGTH)
    assert e.plan.focus == ("T2",)  # T1 fixed three laps ago dropped out of the window


def test_lap_without_comparison_keeps_the_plan() -> None:
    e, _ = engine_with("all")
    plan = e.plan
    e.on_lap_result([], None, LENGTH)  # incomplete lap
    assert e.plan is plan


def test_set_mode_replans_from_stored_inputs() -> None:
    e, _ = engine_with("all", observations=[obs("T2")])
    assert e.set_mode("focus") == "focus" and [c.corner for c in e.plan.cues] == ["T2"]
    e.set_mode("markers")
    assert [c.kind for c in e.plan.cues] == [CueKind.MARKER, CueKind.MARKER]
    e.set_mode("off")
    assert e.plan.cues == () and e.plan.reason == "cues off" and e.seconds_to_next_cue() is None
    with pytest.raises(ValueError):
        e.set_mode("shout")
    assert e.mode == "off"


def test_reset_session_clears_plan_but_cached_reference_trace_survives() -> None:
    e, fired = engine_with("all")
    laps(e, 1)
    e.reset_session()
    assert e.plan.cues == () and e.snapshot()["last"] is None
    # next session, same reference lap (LapProcessor caches it and does not republish the trace)
    e.on_lap_result([], comparison(), LENGTH)
    replanned: tuple[CueSpec, ...] = e.plan.cues
    assert [c.corner for c in replanned] == ["T1", "T2"]
    laps(e, 1)  # lap numbers restart at 1: old lap tokens must not block them
    assert len(fired) == 4


def test_stale_build_does_not_overwrite_a_newer_state(monkeypatch: pytest.MonkeyPatch) -> None:
    e, _ = engine_with("all")
    real = cues_mod.build_cue_plan

    def racing_build(*a: Any, **kw: Any) -> CuePlan:
        plan = real(*a, **kw)
        e.reset_session()  # a session reset lands while this build is in flight
        return plan

    monkeypatch.setattr(cues_mod, "build_cue_plan", racing_build)
    e.on_lap_result([], comparison(), LENGTH)
    assert e.plan.cues == ()


def test_planning_errors_keep_the_previous_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    e, _ = engine_with("all")
    plan = e.plan

    def boom(*a: Any, **kw: Any) -> CuePlan:
        raise RuntimeError("bad comparison")

    monkeypatch.setattr(cues_mod, "build_cue_plan", boom)
    e.on_lap_result([], comparison(), LENGTH)  # must not raise into the analysis thread
    e.on_reference(reference(), flat_trace())
    assert e.plan is plan and e.errors == 2


def test_plan_listener_sees_every_plan_and_cannot_break_planning() -> None:
    e, _ = engine_with("all")
    seen: list[CuePlan] = []
    e.set_plan_listener(seen.append)
    e.set_mode("markers")
    assert seen and seen[-1] is e.plan

    def broken(plan: CuePlan) -> None:
        raise RuntimeError

    e.set_plan_listener(broken)
    e.set_mode("all")
    assert [c.parts for c in e.plan.cues] == [("brake",), ("brake",)]


def test_timing_validation() -> None:
    e = CueEngine()
    with pytest.raises(ValueError):
        e.set_timing(CueTiming(latency_s=-0.1))
    with pytest.raises(ValueError):
        e.set_timing(CueTiming(latency_s=float("nan")))
    with pytest.raises(ValueError):
        CueEngine(margin_m=-1.0)


# ============================================================================================== readers
def test_snapshot_next_and_last_cue() -> None:
    e, fired = engine_with("all", latency=0.3)
    t = run(e, 1, 0.0, 500.0, 100.0)
    snap = e.snapshot()
    assert snap["mode"] == "all" and snap["armed"] and snap["muted"] is None and snap["reason"] is None
    assert snap["next"]["corner"] == "T1" and 495 <= snap["next"]["in_m"] <= 505
    assert snap["last"] is None and len(snap["cues"]) == 2
    run(e, 1, 500.0, 1000.0, t)
    snap = e.snapshot()
    assert snap["next"]["corner"] == "T2"
    assert snap["last"]["corner"] == "T1" and snap["last"]["status"] == "pending"
    e.record_outcome(fired[0].seq, "sent", "audio not ready: text only")
    e.record_timing(fired[0].seq, error_m=2.345, latency_s=0.31)
    last = e.snapshot()["last"]
    assert (last["status"], last["reason"], last["error_m"], last["latency_measured_ms"]) == (
        "sent",
        "audio not ready: text only",
        2.3,
        310,
    )
    e.record_outcome(999, "dropped", "late")  # another cue: counted, display unchanged
    assert e.snapshot()["stats"]["dropped"] == 1 and e.snapshot()["last"]["status"] == "sent"
    import orjson

    orjson.dumps(e.snapshot())  # JSON-able for /ws/live


def test_next_cue_wraps_to_the_next_lap() -> None:
    e, _ = engine_with("all", latency=0.3)
    run(e, 1, 2100.0, 2500.0, 100.0)
    nxt = e.snapshot()["next"]
    assert nxt["corner"] == "T1" and nxt["in_m"] == pytest.approx(LENGTH - 2500.0 + 1000.0, abs=2.0)


def test_next_cue_never_shows_a_lap_length_distance_for_the_point_just_passed() -> None:
    """Regression (README screenshots, Austria): with one cue on the lap, the car in that corner was shown
    "T3 brake in 4311 m" - the next lap's call for the corner it was in. A next-lap call shows only once the car is
    the approach window past that point; same-lap calls and the speak window are unchanged."""
    e, fired = engine_with("all", zones={"T2": 2000.0}, latency=0.3)
    t = run(e, 1, 0.0, 1990.0, 100.0)
    assert len(fired) == 1 and fired[0].cue.corner == "T2"  # called, the car is not at the point yet
    assert e.snapshot()["next"] is None  # not "T2 brake in 3010 m"
    t = run(e, 1, 1990.0, 2007.0, t)  # in the corner, just past the point
    assert e.snapshot()["next"] is None  # not "T2 brake in 2993 m"
    s = e.seconds_to_next_cue()
    assert s is not None and s > 30.0  # the radio still knows a call is coming next lap
    run(e, 1, 2007.0, 2850.0, t)  # the approach window past the point: the next lap's call is a forecast again
    nxt = e.snapshot()["next"]
    assert nxt["corner"] == "T2" and nxt["in_m"] == pytest.approx(LENGTH - 2850.0 + 2000.0, abs=2.0)
    assert nxt["in_m"] < LENGTH - 800.0


def test_next_cue_after_the_last_corner_of_the_lap_is_the_next_laps_first() -> None:
    e, fired = engine_with("all", latency=0.3)  # T1 at 1000 m, T2 at 2000 m
    run(e, 1, 0.0, 2010.0, 100.0)
    assert [c.cue.corner for c in fired] == ["T1", "T2"]
    nxt = e.snapshot()["next"]  # T1 lies 1010 m behind the car: next lap's T1 is the honest next call
    assert nxt["corner"] == "T1" and nxt["in_m"] == pytest.approx(LENGTH - 2010.0 + 1000.0, abs=2.0)


def test_seconds_to_next_cue_for_the_speak_window() -> None:
    e, _ = engine_with("all", latency=0.3)
    run(e, 1, 0.0, 200.0, 100.0)
    s = e.seconds_to_next_cue()
    assert s is not None
    d = e.sample()
    assert d is not None
    assert s == pytest.approx((1000.0 - d.d_m) / V - 0.3 - 5.0 / V, abs=1e-6)
    e.set_muted("voice off")
    assert e.seconds_to_next_cue() is None


def test_cue_timing_error_measurement() -> None:
    spec = CueSpec("T1", CueKind.BRAKE, 1000.0, "T1 brake", ("T1", "brake"), 1)
    ev = CueEvent(1, spec, 4, 4, 50.0, None, 900.0, V, 1.0, 0.3, 0.5, "pcm", 995.0, REF_ID)
    # report at 50.4 s; last frame at 50.39 s at 950 m: car at 950.8 m, key word 0.5 s later at 990.8 m
    sample = FrameSample(50.39, 4, 950.0, V)
    assert cue_timing_error_m(ev, sample, 50.4, LENGTH) == pytest.approx(950.8 + 40.0 - 995.0)
    assert cue_timing_error_m(ev, FrameSample(49.0, 4, 950.0, V), 50.4, LENGTH) is None  # stale frame
    assert cue_timing_error_m(ev, FrameSample(50.39, 6, 950.0, V), 50.4, LENGTH) is None  # unrelated lap
    assert cue_timing_error_m(ev, None, 50.4, LENGTH) is None
    wrapped = CueEvent(2, spec, 5, 4, 50.0, None, 2950.0, V, 1.0, 0.3, 0.5, "pcm", -5.0, REF_ID)
    # audio started 20 m before the line (previous lap): key word at -20 + 40 = 20 m vs aim -5 m
    assert cue_timing_error_m(wrapped, FrameSample(50.4, 4, LENGTH - 20.0, V), 50.4, LENGTH) == pytest.approx(25.0)


# ============================================================================================== LiveState hook
def test_live_state_feeds_the_engine() -> None:
    live = LiveState()
    live.set_track_model({"length_m": LENGTH, "corners": []})
    live.set_reference(reference(), flat_trace())
    live.on_lap_result({"lap_id": 1}, [], comparison())
    assert live.cues.mode == "focus" and live.cues.plan.reason == "no braking corrections to focus on"
    live.cues.set_mode("all")
    fired: list[CueEvent] = []
    live.cues.set_sink(fired.append)
    live.cues.set_timing(CueTiming(latency_s=0.3))
    live.on_session(SessionInfo(game=Game.F1_25, safety_car_status="none", track_length_m=LENGTH))
    v, dt, d, t = V, 1 / 60, 0.0, 10.0
    while d < LENGTH:
        live.on_frame(frame(1, d, t))
        d, t = d + v * dt, t + dt
    assert [ev.cue.corner for ev in fired] == ["T1", "T2"]
    snap = live.snapshot()
    assert snap["cues"]["mode"] == "all" and snap["cues"]["last"]["corner"] == "T2"
    live.reset_session("s2", "udp", False)
    assert live.cues.plan.cues == () and live.snapshot()["cues"]["last"] is None
    live.set_cue_plan(build_cue_plan("all", comparison(), length_m=LENGTH, reference=reference(), trace=flat_trace()))
    assert len(live.cues.plan.cues) == 2


def test_live_state_track_length_falls_back_to_the_session() -> None:
    live = LiveState()
    live.on_session(SessionInfo(game=Game.F1_25, track_length_m=LENGTH))
    live.set_reference(reference(), flat_trace())
    live.cues.set_mode("all")
    live.on_lap_result({"lap_id": 1}, [], comparison())
    assert live.cues.plan.length_m == LENGTH and len(live.cues.plan.cues) == 2


# ============================================================================================== audio composition
SR = 22_050


def tone(seconds: float, amp: int = 3000) -> bytes:
    return int(amp).to_bytes(2, "little", signed=True) * round(seconds * SR)


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * round(seconds * SR)


def test_trim_silence_starts_at_speech_onset() -> None:
    clip = AudioClip(silence(0.12) + tone(0.3) + silence(0.2), SR)
    out = trim_silence(clip)
    assert out.duration_s == pytest.approx(0.3 + CUE_TAIL_PAD_S, abs=1 / SR)
    assert out.pcm[:2] == tone(1 / SR)[:2]
    quiet = AudioClip(tone(0.2, amp=100), SR)
    assert trim_silence(quiet) is quiet  # nothing above threshold: unchanged
    empty = AudioClip(b"", SR)
    assert trim_silence(empty) is empty
    neg = AudioClip(silence(0.1) + (-4000).to_bytes(2, "little", signed=True) * 100, SR)
    assert trim_silence(neg).n_samples == 100  # negative peaks count too


def test_compose_cue_clip_key_offset_is_exact() -> None:
    a, b = AudioClip(tone(0.4), SR), AudioClip(tone(0.25), SR)
    clip, offset = compose_cue_clip([a, b], 1)
    assert offset == pytest.approx(0.4 + CUE_PART_GAP_S, abs=1 / SR)
    assert clip.duration_s == pytest.approx(0.4 + CUE_PART_GAP_S + 0.25, abs=1 / SR)
    key = round(offset * SR) * 2
    assert clip.pcm[key - 2 : key] == b"\x00\x00" and clip.pcm[key : key + 2] != b"\x00\x00"
    assert compose_cue_clip([a], 0)[1] == 0.0
    with pytest.raises(ValueError):
        compose_cue_clip([], 0)
    with pytest.raises(ValueError):
        compose_cue_clip([a], 1)
    with pytest.raises(ValueError):
        compose_cue_clip([a, AudioClip(tone(0.1), 16_000)], 1)


# ============================================================================================== radio hub
class CountingTts:
    """0.1 s silence + speech (0.05 s per character) + 0.1 s silence, like a real engine's padding."""

    name = "counting-tts"
    sample_rate = SR

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str) -> AudioClip:
        self.calls.append(text)
        return AudioClip(silence(0.1) + tone(0.05 * len(text)) + silence(0.1), SR)


class NoStt:
    name = "none"

    def warmup(self) -> None:
        return None

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        return SttResult("", self.name, 0, clip.duration_s)


async def make_hub(
    mode: str = "all", *, device: bool = False, tts: Any = None
) -> tuple[RadioHub, RadioClient, list[Any], Any]:
    live = LiveState()
    live.set_track_model({"length_m": LENGTH, "corners": []})
    engine_tts = tts or CountingTts()
    hub = RadioHub(
        live,
        RaceEngineer(None),
        NoStt(),
        engine_tts,
        RadioScheduler("normal"),
        fact_sheet=FactSheet,
        to_speech=to_speech,
        lap_messages=None,
        cue_mode=mode,
    )
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    client = RadioClient(send=send, device_tts=device)
    await hub.connect(client)
    return hub, client, sent, engine_tts


def install_plan(hub: RadioHub, observations: list[dict[str, Any]] | None = None) -> None:
    hub.live.set_reference(reference(), flat_trace())
    hub.live.on_lap_result({"lap_id": 2}, observations or [], comparison())


async def settle(n: int = 40) -> None:
    for _ in range(n):
        await asyncio.sleep(0.01)


def says(sent: list[Any], kind: str | None = None) -> list[dict[str, Any]]:
    return [m for m in sent if isinstance(m, dict) and m.get("type") == "say" and (kind is None or m["kind"] == kind)]


def ready_audio(hub: RadioHub, parts: tuple[str, ...] = ("T1", "brake")) -> float:
    """Pre-synthesised audio for a phrase, as ``_prepare_cue_audio`` leaves it; returns the key offset."""
    hub._cue_tts = hub.tts  # bound to the current engine, so a preparation pass keeps it
    hub._cue_phrases[parts] = compose_cue_clip([AudioClip(tone(0.3), SR) for _ in parts], len(parts) - 1)
    return hub._cue_phrases[parts][1]


AUDIO = AudioClip(tone(0.5), SR)


def make_event(seq: int = 1, fired: float | None = None, corner: str = "T1", focus_parts: bool = True) -> CueEvent:
    parts = (corner, "brake") if focus_parts else ("brake",)
    spec = CueSpec(corner, CueKind.BRAKE, 1000.0, f"{corner} brake", parts, len(parts) - 1, focus=focus_parts)
    return CueEvent(
        seq, spec, 3, 3, time.monotonic() if fired is None else fired, None, 900.0, V, 1.0, 0.3, 0.5, "pcm", 995.0, 1
    )


async def test_hub_presynthesises_each_part_once_and_pushes_exact_offsets() -> None:
    hub, _client, _sent, tts = await make_hub("focus")
    install_plan(hub, [obs("T1"), obs("T2", prio=0.1)])
    await settle()
    assert sorted(tts.calls) == ["brake", "turn 1", "turn 2"]  # "brake" shared by both phrases
    _clip, offset = hub._cue_phrases[("T1", "brake")]
    assert offset == pytest.approx(0.05 * len("turn 1") + CUE_TAIL_PAD_S + CUE_PART_GAP_S, abs=2 / SR)
    timing = hub.cues.timing
    assert timing.path == "pcm" and timing.offsets_s[("T1", "brake")] == offset
    # seeded: scheduler latency minus measured synthesis (floor 0.2 s), plus the output path to the ear
    assert CUE_OUTPUT_ALLOWANCE_S < timing.latency_s <= 0.6 + CUE_OUTPUT_ALLOWANCE_S
    install_plan(hub, [obs("T1")])  # next lap: same focus corners (T2 is still in the window), all cached
    await settle()
    assert len(tts.calls) == 3 and hub.cues.plan.focus == ("T1", "T2")
    new_tts = CountingTts()
    hub.tts = new_tts  # a new engine (voice change): cache rebuilt for it
    install_plan(hub, [obs("T1")])
    await settle()
    assert sorted(new_tts.calls) == ["brake", "turn 1", "turn 2"]
    await hub.stop()


async def test_hub_fires_cue_from_the_ingest_hook_with_ready_audio() -> None:
    hub, _client, sent, _ = await make_hub("all")
    install_plan(hub)
    await settle()
    v, dt, d, t = V, 1 / 60, 0.0, 10.0
    while d < 1100.0:  # the engine fires on the "ingest" side; the hub delivers on its loop
        hub.live.on_frame(frame(3, d, t))
        d, t = d + v * dt, t + dt
    await settle(5)
    (say,) = says(sent, "cue")
    assert say["text"] == "T1 brake" and say["speech"] == "brake" and say["n_bytes"] > 0
    assert say["meta"]["corner"] == "T1" and say["meta"]["cue"] == "brake"
    assert hub.speaking_id == say["id"]
    assert hub.cues.snapshot()["last"]["status"] == "sent"
    await hub.stop()


async def test_cue_cuts_a_lap_summary_which_is_said_again_later() -> None:
    hub, _client, sent, _ = await make_hub("all")
    ready_audio(hub)
    summary = RadioMessage("p1", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap 4, 1:05.7.", "Lap 4", time.monotonic())
    hub._deliver(summary, AUDIO, None, None)
    assert hub.speaking_id == "p1"
    assert hub.deliver_cue(make_event(), time.monotonic()) is None
    await settle(3)
    assert any(isinstance(m, dict) and m.get("type") == "cancel" and m["id"] == "p1" for m in sent)
    assert says(sent, "cue") and hub.speaking_id == says(sent, "cue")[0]["id"]
    assert hub._held is not None
    held, clip, synth = hub._held
    assert held.text == summary.text and held.id != "p1" and clip is AUDIO and synth is None
    await hub.stop()


@pytest.mark.parametrize(
    ("kind", "priority", "reason"),
    [
        (MessageKind.ANSWER, Priority.HIGH, "answer on air"),
        (MessageKind.CONTROL, Priority.HIGH, "answer on air"),
        (MessageKind.ALERT, Priority.URGENT, "urgent message on air"),
        (MessageKind.CUE, Priority.HIGH, "previous cue still playing"),
    ],
)
async def test_cue_never_cuts_answers_urgent_calls_or_another_cue(
    kind: MessageKind, priority: Priority, reason: str
) -> None:
    hub, _client, sent, _ = await make_hub("all")
    ready_audio(hub)
    hub._deliver(
        RadioMessage("a1", kind, priority, "Tyres are fine.", "Tyres are fine.", time.monotonic()), AUDIO, None, None
    )
    ev = make_event()
    assert hub.deliver_cue(ev, time.monotonic()) == reason
    await settle(3)
    assert [m["id"] for m in says(sent)] == ["a1"]  # only what was already on air
    assert hub.speaking_id == "a1"
    assert hub.cues.snapshot()["stats"]["dropped"] == 1
    await hub.stop()


async def test_cue_gates() -> None:
    hub, client, sent, _ = await make_hub("all")
    ready_audio(hub)
    now = time.monotonic()
    assert hub.deliver_cue(make_event(fired=now - 1.0), now) == "late hand-off"
    await hub.on_text(client, {"type": "ptt", "down": True})
    assert hub.deliver_cue(make_event(), time.monotonic()) == "driver transmitting"
    await hub.on_text(client, {"type": "ptt", "down": False})
    hub.scheduler.set_quiet(indefinite=True)
    hub._sync_cue_gate()
    assert hub.cues.snapshot()["muted"] == "quiet mode"
    assert hub.deliver_cue(make_event(), time.monotonic()) == "quiet mode"
    hub.scheduler.resume()
    await hub.on_text(client, {"type": "settings", "intensity": "quiet"})
    assert hub.cues.snapshot()["muted"] == "minimal radio (quiet intensity)"
    await hub.on_text(client, {"type": "settings", "intensity": "normal", "voice_enabled": False})
    assert hub.deliver_cue(make_event(), time.monotonic()) == "voice off"
    await hub.on_text(client, {"type": "settings", "voice_enabled": True})
    assert hub.cues.snapshot()["muted"] is None
    assert hub.deliver_cue(make_event(), time.monotonic()) is None
    await settle(3)
    assert len(says(sent, "cue")) == 1
    await hub.disconnect(client)
    assert hub.cues.snapshot()["muted"] == "no radio connected"
    await hub.stop()


async def test_device_voice_clients_get_text_and_estimated_offsets() -> None:
    tts = CountingTts()
    hub, _client, sent, _ = await make_hub("focus", device=True, tts=tts)
    install_plan(hub, [obs("T1")])
    await settle()
    assert tts.calls == []  # every radio speaks for itself: no server synthesis at all
    timing = hub.cues.timing
    assert timing.path == "device"
    # "turn 1" = two spoken words at 2.6 words/s plus the comma pause
    assert timing.offsets_s[("T1", "brake")] == pytest.approx(2 / 2.6 + 0.15)
    hub.deliver_cue(make_event(), time.monotonic())
    await settle(3)
    (say,) = says(sent, "cue")
    assert say["device_tts"] is True and say["n_bytes"] == 0 and say["speech"] == "turn 1, brake"
    assert not [x for x in sent if isinstance(x, bytes)]
    assert hub.speaking_id == say["id"]  # the device's speech still holds the gate
    await hub.stop()


async def test_pcm_cue_without_ready_audio_is_dropped_and_never_cuts_what_is_on_air() -> None:
    """Audio still being prepared (or synthesis failed): text alone would cut a lap summary for silence."""
    hub, _client, sent, _ = await make_hub("all")
    summary = RadioMessage("p1", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap 4, 1:05.7.", "Lap 4", time.monotonic())
    hub._deliver(summary, AUDIO, None, None)
    assert hub.deliver_cue(make_event(), time.monotonic()) == "audio not ready"
    await settle(3)
    assert says(sent, "cue") == [] and hub.speaking_id == "p1" and hub._held is None
    assert not [m for m in sent if isinstance(m, dict) and m.get("type") == "cancel"]
    last = hub.cues.snapshot()
    assert last["stats"]["dropped"] == 1
    await hub.stop()


async def test_mixed_radios_get_the_cue_as_text_when_server_audio_is_not_ready() -> None:
    """A device voice can still speak it, so the cue goes out (PCM radios get the text)."""
    hub, _client, sent, _ = await make_hub("all")

    async def send(item: Any) -> None:
        sent.append(item)

    await hub.connect(RadioClient(send=send, name="ipad", device_tts=True))
    assert hub.deliver_cue(make_event(), time.monotonic()) is None
    await settle(3)
    cue_says = says(sent, "cue")
    assert len(cue_says) == 2 and {m["n_bytes"] for m in cue_says} == {0}
    assert hub.speaking_id == cue_says[0]["id"]  # the device voice is audible: it holds the radio
    await hub.stop()


async def test_cue_handed_over_after_its_deadline_is_dropped() -> None:
    """The engine stamps how much hand-off slack is left before the key word would pass the reference point; a
    loop stalled longer (e.g. by a slow request on the same loop) must drop the cue, even within the hard cap."""
    hub, _client, sent, _ = await make_hub("all")
    ready_audio(hub)
    fired = time.monotonic()
    ev = make_event(fired=fired)  # ttg 1.0 s, latency 0.3 s, key word at 0.5 s: 0.2 s of slack
    assert ev.deadline_mono == pytest.approx(fired + 0.2)
    assert hub.deliver_cue(ev, fired + 0.21) == "late hand-off"
    assert hub.deliver_cue(make_event(seq=2, fired=fired), fired + 0.19) is None
    await settle(3)
    assert len(says(sent, "cue")) == 1
    await hub.stop()


async def test_playback_report_measures_latency_and_timing_error() -> None:
    hub, client, sent, _ = await make_hub("all")
    ready_audio(hub)
    seed = hub.cues.timing.latency_s
    fired = time.monotonic()
    ev = make_event(fired=fired)
    hub.deliver_cue(ev, fired)
    await settle(3)
    msg_id = says(sent, "cue")[0]["id"]
    # deterministic measurement: report 0.42 s after the decision, last frame 10 ms before it at 960 m
    hub.cues._sample = FrameSample(fired + 0.41, 3, 960.0, V)
    hub._cue_inflight.pop(msg_id)
    hub._measure_cue(ev, fired + 0.42, "pcm")
    rec = hub.cue_timing[0]
    out = CUE_OUTPUT_ALLOWANCE_S  # device "started" -> the driver's ear, until a device reports it
    assert rec["latency_ms"] == round((0.42 + out) * 1000) and rec["predicted_latency_ms"] == 300
    assert rec["output_ms"] == round(out * 1000) and rec["output_reported"] is False
    # car at 960.8 m when the device started playing; heard `out` later, key word 0.5 s after that:
    # 960.8 + 80 * (0.05 + 0.5) = 1004.8 m, aimed at 995 m: 9.8 m late (past the 5 m margin: past the point)
    assert rec["error_m"] == pytest.approx(960.8 + V * (out + 0.5) - 995.0, abs=0.05)
    # first measurement replaces the seed; the engine times with what reaches the ear
    assert hub.cues.timing.latency_s == pytest.approx(0.42 + out) != seed
    hub._measure_cue(ev, fired + 0.32, "pcm")
    assert hub.cues.timing.latency_s == pytest.approx(0.42 + 0.3 * (0.32 - 0.42) + out)
    hub._measure_cue(ev, fired + 9.0, "pcm")  # absurd outlier: logged, not learnt
    assert hub.cues.timing.latency_s == pytest.approx(0.39 + out)
    # a device that reports a longer output delay replaces the allowance...
    hub._measure_cue(ev, fired + 0.39, "pcm", 0.08)
    assert hub.cue_timing[0]["output_reported"] is True and hub.cue_timing[0]["output_ms"] == 80
    assert hub.cues.timing.latency_s == pytest.approx(0.39 + 0.08)
    # ...a shorter one never lowers it (Web Audio outputLatency may leave out the Bluetooth link)
    hub._cue_output["pcm"] = type(hub._cue_output["pcm"])()
    hub._measure_cue(ev, fired + 0.39, "pcm", 0.01)
    assert hub.cue_timing[0]["output_ms"] == round(out * 1000)
    assert hub.cues.timing.latency_s == pytest.approx(0.39 + out)
    # wiring: a real playback report for an in-flight cue lands in the log
    ev2 = make_event(seq=2)
    hub.speaking_id = None
    hub.deliver_cue(ev2, time.monotonic())
    await settle(3)
    await hub.on_text(
        client,
        {"type": "playback", "id": says(sent, "cue")[-1]["id"], "state": "started", "output_latency_s": "fast"},
    )  # a malformed output delay is ignored
    assert len(hub.cue_timing) == 6 and hub.status()["cues"]["timing_log"][0]["corner"] == "T1"
    assert hub.cue_timing[0]["output_reported"] is False
    await hub.stop()


async def test_cue_mode_setting_over_the_radio_protocol() -> None:
    hub, client, sent, _ = await make_hub("focus")
    await hub.on_text(client, {"type": "settings", "cue_mode": "markers"})
    await settle(3)
    assert hub.cues.mode == "markers"
    state = [m for m in sent if isinstance(m, dict) and m.get("type") == "state"][-1]
    assert state["cue_mode"] == "markers"
    await hub.on_text(client, {"type": "settings", "cue_mode": "very loud"})
    await settle(3)
    assert hub.cues.mode == "markers"
    assert any(isinstance(m, dict) and m.get("type") == "error" and "cue mode" in m["message"] for m in sent)
    with pytest.raises(ValueError):
        RadioHub(
            LiveState(),
            RaceEngineer(None),
            NoStt(),
            CountingTts(),
            RadioScheduler(),
            FactSheet,
            to_speech,
            cue_mode="sometimes",
        )
    await hub.stop()


async def test_speak_window_treats_the_next_cue_as_a_braking_zone() -> None:
    hub, _client, _sent, _ = await make_hub("all")
    install_plan(hub)
    await settle()
    hub.live.on_packet(accepted=True)
    hub.live.on_frame(frame(3, 700.0, 50.0))
    ttb = hub.driving_state().time_to_next_braking_s
    lead = hub.cues.timing.latency_s
    assert ttb is not None and ttb == pytest.approx((1000.0 - 700.0) / V - lead - 5.0 / V, abs=1e-3)
    await hub.stop()


async def test_proactive_message_synthesised_while_a_cue_plays_is_held_not_cut_over_it() -> None:
    class SlowTts(CountingTts):
        def synthesize(self, text: str) -> AudioClip:
            time.sleep(0.15)
            return super().synthesize(text)

    hub, _client, sent, _ = await make_hub("all", tts=SlowTts())
    ready_audio(hub)
    assert hub._tick_task is not None
    hub._tick_task.cancel()
    loop = asyncio.get_running_loop()
    hub.scheduler.enqueue(
        RadioMessage("p7", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap 3, 1:05.9.", "Lap 3", time.monotonic())
    )
    loop.call_later(0.05, lambda: hub.deliver_cue(make_event(), time.monotonic()))
    await hub._tick(time.monotonic())
    await settle(3)
    cue = says(sent, "cue")
    assert cue and hub.speaking_id == cue[0]["id"]  # the cue is still on air
    assert not [m for m in says(sent) if m["id"] == "p7"]
    assert hub._held is not None and hub._held[0].id == "p7"
    synth_s = hub._held[2]
    assert synth_s is not None and synth_s >= 0.15  # latency feedback will be synthesis, not time held


class SlowTts(CountingTts):
    """Synthesis that takes long enough for a cue to fire meanwhile (`say` takes ~0.4 s on the Mac)."""

    def synthesize(self, text: str) -> AudioClip:
        time.sleep(0.15)
        return super().synthesize(text)


def red_flag(mid: str = "u1") -> RadioMessage:
    return RadioMessage(
        mid,
        MessageKind.ALERT,
        Priority.URGENT,
        "Red flag, red flag.",
        "Red flag, red flag.",
        time.monotonic(),
        needs_speak_window=False,
    )


def driving(hub: RadioHub, brake: float, steering: float, d: float = 950.0) -> None:
    """A live frame: on track, at speed, with these pedal / wheel inputs."""
    hub.live.on_packet(accepted=True)
    hub.live.on_frame(
        CarFrame(
            game=Game.F1_25,
            t_recv_ns=0,
            session_time_s=50.0,
            lap_number=3,
            lap_distance_m=d,
            speed_kph=V_KPH,
            brake=brake,
            steering=steering,
            current_lap_time_ms=20_000,
        )
    )


async def test_urgent_call_synthesised_while_a_cue_plays_cuts_it_and_skips_the_speak_window() -> None:
    """Urgent outranks a cue (scheduler contract): it is never held for a speak window that may not come."""
    hub, _client, sent, _ = await make_hub("all", tts=SlowTts())
    ready_audio(hub)
    assert hub._tick_task is not None
    hub._tick_task.cancel()
    hub.scheduler.enqueue(red_flag())
    loop = asyncio.get_running_loop()
    loop.call_later(0.05, lambda: hub.deliver_cue(make_event(), time.monotonic()))
    driving(hub, brake=0.9, steering=0.3)  # hard on the brakes, turning in
    await hub._tick(time.monotonic())
    await settle(3)
    cue_id = says(sent, "cue")[0]["id"]
    assert [m["id"] for m in says(sent, "alert")] == ["u1"] and hub.speaking_id == "u1"
    assert any(isinstance(m, dict) and m.get("type") == "cancel" and m["id"] == cue_id for m in sent)
    assert hub._held is None and hub._held_urgent is None
    await hub.stop()


async def test_urgent_call_waits_only_for_the_drivers_transmission_not_for_a_speak_window() -> None:
    hub, client, sent, _ = await make_hub("all", tts=SlowTts())
    assert hub._tick_task is not None
    hub._tick_task.cancel()
    hub.scheduler.enqueue(red_flag())
    loop = asyncio.get_running_loop()
    loop.call_later(0.05, lambda: hub._ptt_down_now("screen", client))  # driver keys the mic during synthesis
    await hub._tick(time.monotonic())
    assert hub._held_urgent is not None and not says(sent, "alert")
    await hub._tick(time.monotonic())  # still transmitting: waits
    assert not says(sent, "alert")
    await hub.on_text(client, {"type": "ptt", "down": False})
    driving(hub, brake=0.9, steering=0.3)  # mid-corner: a speak window would be closed
    await hub._tick(time.monotonic())
    await settle(3)
    assert [m["id"] for m in says(sent, "alert")] == ["u1"] and hub._held_urgent is None
    await hub.stop()


async def test_urgent_call_never_queues_behind_a_held_message() -> None:
    hub, client, sent, _ = await make_hub("all", tts=SlowTts())
    assert hub._tick_task is not None
    hub._tick_task.cancel()
    driving(hub, brake=0.0, steering=0.0, d=200.0)  # calm straight: the summary is handed out...
    hub.scheduler.enqueue(
        RadioMessage("p7", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap 3, 1:05.9.", "Lap 3", time.monotonic())
    )
    asyncio.get_running_loop().call_later(0.05, lambda: driving(hub, brake=0.9, steering=0.3))
    await hub._tick(time.monotonic())
    assert hub._held is not None and hub._held[0].id == "p7"  # ...but the car turned in during synthesis
    hub.scheduler.enqueue(red_flag())
    await hub._tick(time.monotonic())
    await settle(3)
    assert [m["id"] for m in says(sent, "alert")] == ["u1"]  # out at once, still mid-corner
    assert hub._held is not None and hub._held[0].id == "p7"  # the summary keeps waiting for its window
    await hub.on_text(client, {"type": "playback", "id": "u1", "state": "ended"})
    driving(hub, brake=0.0, steering=0.0, d=200.0)  # calm straight again (no cue plan: no cue ahead)
    await hub._tick(time.monotonic())
    await settle(3)
    assert [m["id"] for m in says(sent, "lap_summary")] == ["p7"] and hub._held is None
    await hub.stop()


async def test_urgent_calls_never_cut_each_other() -> None:
    hub, _client, sent, _ = await make_hub("all")
    assert hub._tick_task is not None
    hub._tick_task.cancel()
    hub._deliver(red_flag("u0"), AUDIO, None, None)
    hub.scheduler.enqueue(red_flag("u1"))
    await hub._tick(time.monotonic())
    assert hub.speaking_id == "u0" and hub._held_urgent is not None and hub._held_urgent[0].id == "u1"
    await hub.on_text(_client, {"type": "playback", "id": "u0", "state": "ended"})
    await hub._tick(time.monotonic())
    await settle(3)
    assert [m["id"] for m in says(sent, "alert")] == ["u0", "u1"]
    await hub.stop()


async def test_answer_waits_for_the_cue_on_air_instead_of_cutting_its_key_word() -> None:
    hub, client, sent, _ = await make_hub("all")
    ready_audio(hub)
    assert hub.deliver_cue(make_event(), time.monotonic()) is None
    cue_id = hub.speaking_id
    assert cue_id is not None
    ack = hub._msg(MessageKind.CONTROL, Priority.HIGH, "Copy, checking.", bypass=True)
    task = asyncio.create_task(hub.say(ack, None, None))
    await settle(5)
    assert not says(sent, "control") and hub.speaking_id == cue_id  # still waiting: the cue plays on
    await hub.on_text(client, {"type": "playback", "id": cue_id, "state": "ended"})
    await task
    assert [m["id"] for m in says(sent, "control")] == [ack.id]
    assert not any(isinstance(m, dict) and m.get("type") == "cancel" and m["id"] == cue_id for m in sent)
    # bounded: a cue whose end is never reported holds an answer only until its speaking deadline
    await hub.on_text(client, {"type": "playback", "id": ack.id, "state": "ended"})
    assert hub.deliver_cue(make_event(seq=2), time.monotonic()) is None
    hub._speaking_deadline = time.monotonic() + 0.05
    t0 = time.monotonic()
    await hub.say(hub._msg(MessageKind.ANSWER, Priority.HIGH, "Tyres are fine.", bypass=True), None, None)
    assert time.monotonic() - t0 < 1.0
    await settle(3)
    assert says(sent, "answer")
    await hub.stop()
