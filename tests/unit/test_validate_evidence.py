"""Rig validation kit: pure evidence extractors (onsets, speak windows, devices, games, switches, tiers)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from pitwall.analysis.laps import CHANNELS, LapTrace
from pitwall.validate import evidence as E
from pitwall.validate import rules as R
from pitwall.validate.model import (
    ClientSample,
    ClientState,
    CueRecord,
    Evidence,
    ItemState,
    LapRecord,
    Run,
    ServerInfo,
    SessionSummary,
    SwitchRecord,
    Window,
)

NOW = 1_800_000_000.0


def trace(
    lap: int,
    d: np.ndarray[Any, Any],
    *,
    t0: float | None = 0.0,
    brake: np.ndarray[Any, Any] | None = None,
    steer: np.ndarray[Any, Any] | None = None,
    speed_kph: float = 216.0,
    flags: set[str] | None = None,
) -> LapTrace:
    n = len(d)
    v = speed_kph / 3.6
    ch = {k: np.full(n, np.nan) for k in CHANNELS}
    ch["distance_m"] = d.astype(float)
    ch["session_time_s"] = np.full(n, np.nan) if t0 is None else t0 + (d - d[0]) / v
    ch["speed_kph"] = np.full(n, speed_kph)
    ch["throttle"] = np.ones(n) if brake is None else np.where(brake > 0.05, 0.0, 1.0)
    ch["brake"] = np.zeros(n) if brake is None else brake.astype(float)
    ch["steering"] = np.zeros(n) if steer is None else steer.astype(float)
    return LapTrace(lap_number=lap, channels=ch, lap_time_ms=60000, flags=flags or set())


def brake_profile(d: np.ndarray[Any, Any], zones: list[tuple[float, float, float]]) -> np.ndarray[Any, Any]:
    b = np.zeros(len(d))
    for start, end, peak in zones:
        b[(d >= start) & (d <= end)] = peak
    return b


# ------------------------------------------------------------------------------------------------ onsets
def test_braking_onsets_keep_real_braking_only() -> None:
    d = np.arange(0.0, 3000.0, 1.0)
    b = brake_profile(d, [(500, 600, 0.9), (1200, 1260, 0.2), (2000, 2100, 0.35)])  # a 0.2 dab is not a zone
    onsets = E.braking_onsets(trace(1, d, brake=b))
    assert onsets == pytest.approx([500.0, 2000.0], abs=1.0)


def test_cue_matched_by_distance_never_by_corner_name() -> None:
    """Silverstone (Reverse): the call named T8 targeted 2936 m while the same lap's comparison named a different
    corner T8 (onset 3758.7 m) because the track model was still versioning. The match must follow the distance."""
    ev = Evidence()
    ev.laps.append(
        LapRecord(NOW, "live", "s1", 1, 42, 3, 90000, True, [], "f1_25", "f1:7", "Silverstone", "all", 4, [])
    )
    ev.lap_onsets["42"] = [2941.5, 3758.7]
    c = CueRecord(
        NOW,
        "live",
        "s1",
        1,
        7,
        "m9",
        3,
        "T8",
        "brake",
        False,
        False,
        2936.0,
        2931.0,
        2830.0,
        250.0,
        1.4,
        "pcm",
        "sent",
        error_m=1.0,
    )
    ev.cues.append(c)
    E.enrich_cues(ev)
    assert c.onset_m == 2941.5 and c.onset_vs_point_m == pytest.approx(5.5)
    assert c.heard_m == pytest.approx(2932.0) and c.onset_vs_word_m == pytest.approx(9.5)
    assert c.onset_vs_word_s == pytest.approx(9.5 / (250 / 3.6), abs=0.01)
    c2 = CueRecord(
        NOW,
        "live",
        "s1",
        1,
        8,
        "m10",
        3,
        "T8",
        "brake",
        False,
        False,
        3200.0,
        3195.0,
        3100.0,
        250.0,
        1.4,
        "pcm",
        "sent",
    )
    ev.cues.append(c2)
    E.enrich_cues(ev)
    assert c2.onset_m is None and c2.cls == "unmeasured"  # nothing within 100 m: unknown stays unknown


def test_baseline_offsets_use_calls_off_laps_of_the_same_sessions() -> None:
    ev = Evidence()
    for i, mode in enumerate(("off", "off", "all", "off")):
        sid = "s1" if i < 3 else "other"
        ev.laps.append(LapRecord(NOW, "live", sid, 1, 100 + i, i + 1, 90000, True, [], "f1_25", "t", "T", mode, 1, []))
        ev.lap_onsets[str(100 + i)] = [995.0 + i, 1802.0]
    ev.laps.append(
        LapRecord(NOW, "live", "s1", 1, 200, 9, 90000, False, ["flashback"], "f1_25", "t", "T", "off", 1, [])
    )
    ev.lap_onsets["200"] = [900.0]
    cues = [
        CueRecord(
            NOW, "live", "s1", 1, i, "m", 3, "T1", "brake", False, False, t, t - 5, t - 100, 250.0, 1.0, "pcm", "sent"
        )
        for i, t in enumerate((1000.0, 1001.0, 1800.0))
    ]
    out = E.baseline_offsets(cues, ev.laps, ev.lap_onsets)
    # zones 1000 (targets 1000, 1001: median 1000.5) and 1800, laps 100 and 101 only (mode off, same session)
    assert sorted(out) == pytest.approx(sorted([995.0 - 1000.5, 2.0, 996.0 - 1000.5, 2.0]))


# ------------------------------------------------------------------------------------------------ speak windows
def test_measure_playback_in_time_and_across_the_line() -> None:
    d1 = np.arange(0.0, 1000.0, 1.0)
    b1 = brake_profile(d1, [(900, 990, 0.8)])
    lap1 = trace(1, d1, t0=0.0, brake=b1)  # 60 m/s: t = d / 60
    d2 = np.arange(0.0, 1000.0, 1.0)
    b2 = brake_profile(d2, [(300, 380, 0.8)])
    lap2 = trace(2, d2, t0=1000.0 / 60.0, brake=b2)
    traces = {1: lap1, 2: lap2}
    clean = E.measure_playback(traces, {"lap": 1, "session_time_s": 2.0}, {"lap": 1, "session_time_s": 5.0}, None)
    assert clean is not None and clean.max_brake == 0.0 and clean.complete
    assert clean.gap_to_brake_s == pytest.approx(900 / 60 - 5.0, abs=0.05)
    over = E.measure_playback(traces, {"lap": 1, "session_time_s": 14.0}, {"lap": 1, "session_time_s": 16.0}, None)
    assert over is not None and over.max_brake == pytest.approx(0.8)
    across = E.measure_playback(traces, {"lap": 1, "session_time_s": 16.6}, {"lap": 2, "session_time_s": 18.0}, None)
    assert across is not None and across.max_brake == 0.0
    assert across.gap_to_brake_s == pytest.approx(1000 / 60 + 300 / 60 - 18.0, abs=0.05)
    est = E.measure_playback(traces, {"lap": 1, "session_time_s": 2.0}, None, 3.0)  # end missing: start + duration
    assert est is not None and est.gap_to_brake_s == pytest.approx(900 / 60 - 5.0, abs=0.05)
    assert E.measure_playback(traces, None, None, 3.0) is None
    assert E.measure_playback(traces, {"lap": 7, "session_time_s": 2.0}, None, 3.0) is None
    fb = {1: trace(1, d1, t0=0.0, brake=b1, flags={"flashback"})}
    assert E.measure_playback(fb, {"lap": 1, "session_time_s": 2.0}, None, 1.0) is None


def test_measure_playback_distance_fallback_without_game_clock() -> None:
    d = np.arange(0.0, 1000.0, 1.0)
    b = brake_profile(d, [(600, 700, 0.9)])
    steer = np.where((d > 200) & (d < 260), 0.4, 0.0)
    lap = trace(1, d, t0=None, brake=b, steer=steer)
    m = E.measure_playback({1: lap}, {"lap": 1, "lap_distance_m": 100.0}, {"lap": 1, "lap_distance_m": 300.0}, None)
    assert m is not None and m.max_abs_steering == pytest.approx(0.4) and m.max_brake == 0.0
    assert m.gap_to_brake_s == pytest.approx(300 / 60, abs=0.05)
    p = E.measure_playback({1: lap}, {"lap": 1, "lap_distance_m": 550.0}, {"lap": 1, "lap_distance_m": 610.0}, None)
    assert p is not None and p.max_brake == pytest.approx(0.9)
    assert R.classify_playback(True, p.max_brake, p.max_abs_steering, p.gap_to_brake_s) == "overlap"


# ------------------------------------------------------------------------------------------------ devices
def test_client_summary_counts_hidden_reloads_and_fps() -> None:
    samples = [
        ClientSample(
            NOW + i * 15,
            i,
            i != 3,
            "drive/coach",
            True,
            "on",
            "live",
            "live",
            True,
            True,
            fps_10s=58.0 if i < 4 else None,
        )
        for i in range(6)
    ]
    c = ClientState(
        "abc",
        "ipad",
        NOW,
        {
            "origin_kind": "tailscale_https",
            "standalone": True,
            "secure_context": True,
            "route": "drive/coach",
            "visibility": "visible",
            "wake": {"wanted": True, "state": "on"},
        },
        NOW + 75,
        reports=6,
        reloads=1,
        samples=samples,
    )
    s = E.client_summary(c, NOW + 80)
    assert s["hidden_transitions"] == 1 and s["reloads"] == 1 and s["last_seen_s"] == pytest.approx(5.0)
    assert s["fps"] == {"median": 58.0, "p5": 58.0, "windows": 4} and s["origin_kind"] == "tailscale_https"
    f = E.screen_facts([c], lambda t: t == "live")
    assert f.drive_hidden == 1 and f.best_streak_s == pytest.approx(30.0)


# ------------------------------------------------------------------------------------------------ games
def test_tally_decode_banks_previous_adapter_instances() -> None:
    store: dict[str, dict[str, Any]] = {}
    assert E.tally_decode(
        store, "live|gt7", {"packets": 200, "rejected": 0, "errors": 0, "by_type": {"variant_C": 200}}
    )
    assert not E.tally_decode(
        store, "live|gt7", {"packets": 200, "rejected": 0, "errors": 0, "by_type": {"variant_C": 200}}
    )
    E.tally_decode(store, "live|gt7", {"packets": 400, "rejected": 1, "errors": 0, "by_type": {"variant_C": 400}})
    E.tally_decode(
        store, "live|gt7", {"packets": 200, "rejected": 0, "errors": 0, "by_type": {"variant_C": 200}}
    )  # new
    E.tally_decode(store, "recorded|gt7", {"packets": 999, "rejected": 5, "errors": 0, "by_type": {}})
    tot = E.decode_totals(store, "gt7", lambda t: t == "live")
    assert tot == {"packets": 600, "rejected": 1, "errors": 0, "variants": {"C": 600}}
    assert E.decode_totals(store, "ac", lambda t: True) is None
    assert E.adapter_game("Gran Turismo 7 (Simulator Interface, variants A/B/~/C)") == "gt7"
    assert E.adapter_game("Assetto Corsa Remote Telemetry (UDP 9996)") == "ac"


def gt7_session(
    sid: str,
    start: float,
    laps: list[tuple[int, bool]],
    track: str | None = "gt7:3800",
    tier: str = "recorded",
    best: int | None = None,
) -> SessionSummary:
    return SessionSummary(
        session_id=sid,
        game="gt7",
        tier=tier,
        source="replay",
        started_unix=start,
        ended_unix=start + 60,
        track_id=track,  # type: ignore[arg-type]
        track_name=None if track is None else "Unidentified GT7 circuit (3.80 km)",
        track_length_m=3800.0,
        platform="unknown",
        driver_id=1,
        game_session_uid=sid,
        laps=[{"lap_number": i + 1, "lap_time_ms": t, "clean": c} for i, (t, c) in enumerate(laps)],
        n_observations=1 if laps else 0,
        extra={"packet_variant": "C", "best_lap_ms": best},
    )


def test_game_facts_aggregate_sessions_and_count_menus_apart() -> None:
    sessions = [
        gt7_session("a", NOW, [], track=None),
        gt7_session("b", NOW + 100, [(105151, True), (105596, True), (103358, True)], best=103358),
        gt7_session("c", NOW + 500, [], track=None),
        gt7_session("d", NOW + 900, [(23222, True)], track="gt7:920"),
    ]
    f = E.game_facts("gt7", sessions, {}, None, lambda t: True, NOW + 2000)
    assert f.sessions == 4 and f.menu_sessions == 2 and f.driving_sessions == 2
    assert f.timed_laps == [105151, 105596, 103358] and f.track_id == "gt7:3800" and f.clean_laps == 3
    assert f.best_lap_ms_game == 103358 and f.variants == ["C"] and f.heartbeat_sent is None
    st = R.gt7_verdict(f, None, [], NOW)
    assert {c.id: c.status for c in st.checks}["best_lap"] == "met"
    assert E.game_facts("gt7", sessions, {}, None, lambda t: t == "live", NOW).sessions == 0


# ------------------------------------------------------------------------------------------------ switches
def test_settle_switch_split_and_retag() -> None:
    split = SwitchRecord(NOW, "live", "a", 2, 1, 2, "a", session_after="b", settled=True)
    E.settle_switch(
        split,
        {"driver_id": 1, "game_session_uid": "u"},
        {"driver_id": 2, "game_session_uid": "u"},
        [{"created_unix": NOW - 60}, {"created_unix": NOW + 1}],
        [{"created_unix": NOW + 90}, {"created_unix": NOW + 180}],
        None,
    )
    assert split.laps_before_after_switch == 0 and split.laps_after == 2 and split.same_game_uid is True
    assert split.ok is None  # cue plan reason unknown and no plan owner: not decided
    split.cue_reason_after = "new driver: waiting for a lap against their reference"
    assert R.switch_ok(split)[0] is True
    late = SwitchRecord(
        NOW, "live", "a", 2, 1, 2, "a", session_after="b", settled=True, cue_reason_after="no reference lap yet"
    )
    E.settle_switch(
        late, {"driver_id": 1}, {"driver_id": 2}, [{"created_unix": NOW + 3}], [{"created_unix": NOW + 90}], None
    )
    assert late.laps_before_after_switch == 1 and late.ok is False
    retag = SwitchRecord(
        NOW, "live", "a", 2, 1, 2, "a", session_after="a", settled=True, cue_reason_after="no reference lap yet"
    )
    E.settle_switch(retag, {"driver_id": 2}, {"driver_id": 2}, [], [{"created_unix": NOW + 90}], None)
    assert retag.laps_after == 1 and retag.before_driver_id is None and retag.ok is True


# ------------------------------------------------------------------------------------------------ tiers
def _run(ev: Evidence, items: list[str]) -> Run:
    return Run(
        "20261012-193012-a3f1",
        None,
        "active",
        NOW,
        ServerInfo("0.1.0", None, "darwin", False, False, None, None),
        items,
        [ItemState(i, windows=[Window(NOW - 1)]) for i in items],
        evidence=ev,
    )


def test_compute_auto_live_only_and_not_live() -> None:
    ev = Evidence()
    ev.sessions = [gt7_session("b", NOW, [(105151, True), (105596, True), (103358, True)], best=103358)]
    vs = E.views(_run(ev, ["gt7_ps5"]))
    ctx = E.AutoContext(NOW, [], {"times_match": True})
    st = E.compute_auto("gt7_ps5", vs, ctx)
    assert st.verdict == "not_live" and st.tier == "recorded" and st.reasons[0] == R.NOT_LIVE_TEXT["recorded"]
    assert st.metrics["timed_laps"] == 3  # what was seen is still shown
    ev.sessions.append(gt7_session("live1", NOW, [(90000, True)], tier="live"))
    st = E.compute_auto("gt7_ps5", E.views(_run(ev, ["gt7_ps5"])), ctx)
    assert st.tier == "live" and st.verdict == "inconclusive" and any("ignored" in r for r in st.reasons)
    un = E.compute_auto("radio_ptt", vs, E.AutoContext(NOW, [], {}, False, "Voice is off on this server."))
    assert un.verdict == "unavailable" and un.reasons == ["Voice is off on this server."]
    assert E.compute_auto("cues_timing", vs, ctx).verdict == "no_evidence"
