"""Rig validation kit: known-answer tables for every rule (spec section 5), with boundary values."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from pitwall.validate import evidence as E
from pitwall.validate import rules as R
from pitwall.validate.model import (
    AutoState,
    Check,
    ClientSample,
    CueRecord,
    DriverMark,
    GameTransition,
    InputPhaseRecord,
    ProactiveRecord,
    PttRecord,
    SwitchRecord,
)

NOW = 1_800_000_000.0


def cue(
    error_m: float | None = 0.0,
    target_m: float = 1000.0,
    *,
    speed_kph: float = 288.0,
    outcome: str = "sent",
    reason: str | None = None,
    kind: str = "brake",
    heads_up: bool = False,
    onset_vs_point_m: float | None = None,
    session: str = "s1",
    lap: int = 5,
) -> CueRecord:
    c = CueRecord(
        t_unix=NOW,
        tier="live",
        session_id=session,
        driver_id=1,
        seq=1,
        msg_id="m1",
        lap=lap,
        corner="T1",
        kind=kind,
        heads_up=heads_up,
        focus=False,
        target_m=target_m,
        aim_m=target_m - 5.0,
        d_m=target_m - 100.0,
        speed_kph=speed_kph,
        ttg_s=1.2,
        path="pcm",
        outcome=outcome,
        drop_reason=reason,
        error_m=error_m,
        latency_ms=300,
    )
    E.enrich_cue(c, None)
    c.onset_vs_point_m = onset_vs_point_m
    return c


# ------------------------------------------------------------------------------------------------ tiers
@pytest.mark.parametrize(
    ("synthetic", "source", "sender", "telemetry", "tier"),
    [
        (True, "udp:20777", "lan", "live", "synthetic"),
        (False, "replay:x.pwcap", "lan", "live", "recorded"),
        (False, "replay:x.pwcap", None, "stale", "recorded"),
        (False, "udp:20777", "loopback", "live", "loopback"),
        (False, "udp:20777", "lan", "live", "live"),
        (False, "udp:20777", "lan", "stale", "unknown"),
        (False, "udp:20777", None, "live", "unknown"),
        (False, None, None, "no_data", "unknown"),
    ],
)
def test_tier_of(synthetic: bool, source: str | None, sender: str | None, telemetry: str, tier: str) -> None:
    assert R.tier_of(synthetic, source, sender, telemetry) == tier


@pytest.mark.parametrize(
    ("ip", "cls"),
    [
        ("127.0.0.1", "loopback"),
        ("::1", "loopback"),
        ("192.168.1.40", "lan"),
        ("100.101.102.103", "lan"),
        ("not-an-ip", None),
        (None, None),
        ("", None),
    ],
)
def test_sender_class(ip: str | None, cls: str | None) -> None:
    assert R.sender_class(ip) == cls


# ------------------------------------------------------------------------------------------------ cues (5.2)
@pytest.mark.parametrize(
    ("error_m", "outcome", "cls"),
    [
        (5.0, "sent", "on_time"),  # the margin may be used, the point never passed
        (5.01, "sent", "late"),
        (0.0, "sent", "on_time"),
        (-43.0, "sent", "on_time"),  # 288 km/h = 80 m/s: 0.6 s = 48 m before the point (margin 5 - error)
        (-43.1, "sent", "early"),
        (None, "sent", "unmeasured"),
        (1.0, "dropped", "dropped"),
    ],
)
def test_classify_cue(error_m: float | None, outcome: str, cls: str) -> None:
    c = cue(error_m, outcome=outcome)
    assert R.classify_cue(c) == cls
    if error_m is not None:
        assert c.heard_m == pytest.approx(995.0 + error_m, abs=0.05)
        assert c.heard_vs_point_m == pytest.approx(error_m - 5.0, abs=0.05)


def test_match_onset_nearest_within_window_by_distance() -> None:
    assert R.match_onset(1000.0, [850.0, 1090.0, 1101.0]) == 1090.0
    assert R.match_onset(1000.0, [900.0, 1100.0]) == 900.0  # tie at exactly 100 m: first one kept
    assert R.match_onset(1000.0, [899.9, 1100.1]) is None
    assert R.match_onset(1000.0, []) is None
    assert R.match_onset(1000.0, [995.0, 1004.0]) == 1004.0


def _zones(n: int, zones: int = 3, **kw: Any) -> list[CueRecord]:
    return [cue(0.0, target_m=500.0 + 400.0 * (i % zones), **kw) for i in range(n)]


def test_cues_pass_needs_eight_measured_over_three_zones() -> None:
    assert R.cues_verdict(_zones(7), [], NOW).verdict == "inconclusive"
    st = R.cues_verdict(_zones(8), [], NOW)
    assert st.verdict == "pass" and st.metrics["measured"] == 8 and st.metrics["zones"] == 3
    st2 = R.cues_verdict(_zones(8, zones=2), [], NOW)
    assert st2.verdict == "inconclusive" and any("2 braking zones" in r for r in st2.reasons)
    assert "7 calls measured, 8 needed" in R.cues_verdict(_zones(7), [], NOW).reasons


def test_cues_late_rules() -> None:
    one_late = [*_zones(9), cue(6.0)]
    st = R.cues_verdict(one_late, [], NOW)
    assert st.verdict == "inconclusive" and st.metrics["late"] == 1  # 1 of 10 = 10 %: not above it
    assert R.cues_verdict([*_zones(9), cue(6.0), cue(7.0)], [], NOW).verdict == "fail"
    assert R.cues_verdict([*_zones(4), cue(6.0)], [], NOW).verdict == "fail"  # 1 of 5 > 10 %


def test_cues_delivery_drop_share_boundary() -> None:
    measured = _zones(16)
    ok = [*measured, *[cue(None, outcome="dropped", reason="late hand-off") for _ in range(4)]]  # 4 / 20 = 0.20
    assert R.cues_verdict(ok, [], NOW).verdict == "pass"
    measured = _zones(79)
    bad = [*measured, *[cue(None, outcome="dropped", reason="audio not ready") for _ in range(21)]]  # 21 / 100
    st = R.cues_verdict(bad, [], NOW)
    assert st.verdict == "inconclusive" and st.metrics["dropped_delivery"] == 21
    expected_holds = [*_zones(8), *[cue(None, outcome="dropped", reason="quiet mode") for _ in range(10)]]
    st = R.cues_verdict(expected_holds, [], NOW)
    assert st.verdict == "pass" and st.metrics["dropped_expected"] == 10  # listed, never counted


def test_cues_early_share_boundary() -> None:
    ten = [*_zones(9), cue(-50.0)]  # 1 of 10 early: 10 %, allowed
    assert R.cues_verdict(ten, [], NOW).verdict == "pass"
    assert R.cues_verdict([*_zones(8), cue(-50.0), cue(-50.0)], [], NOW).verdict == "inconclusive"


def test_cues_heads_up_and_markers_are_counted_apart() -> None:
    st = R.cues_verdict([cue(0.0, heads_up=True) for _ in range(20)], [], NOW)
    assert st.verdict == "inconclusive" and st.metrics["heads_up_fired"] == 20 and st.metrics["fired"] == 0
    assert "heads-up" in st.reasons[0]
    st = R.cues_verdict([*_zones(8), *[cue(0.0, kind="marker") for _ in range(5)]], [], NOW)
    assert st.verdict == "pass" and st.metrics["markers_fired"] == 5
    assert R.cues_verdict([], [], NOW).verdict == "no_evidence"


def test_cues_delay_flag_forces_review() -> None:
    cued = [cue(0.0, target_m=500.0 + 400.0 * (i % 3), onset_vs_point_m=12.0) for i in range(8)]
    st = R.cues_verdict(cued, [1.0] * 8, NOW)
    assert st.verdict == "pass"
    flag = next(c for c in st.checks if c.id == R.DELAY_FLAG_ID)
    assert flag.status == "not_met" and any("delaying your braking" in r for r in st.reasons)
    assert R.forces_review(st)
    worked = [DriverMark(1, "worked")]
    assert R.item_result(st, worked, False, False) == "needs_review"
    # 9.9 m later is not flagged; fewer than 8 baseline points cannot raise the flag
    st2 = R.cues_verdict(
        [cue(0.0, target_m=500.0 + 400.0 * (i % 3), onset_vs_point_m=10.9) for i in range(8)], [1.0] * 8, NOW
    )
    assert not R.forces_review(st2) and R.item_result(st2, worked, False, False) == "pass"
    st3 = R.cues_verdict(cued, [1.0] * 7, NOW)
    assert next(c for c in st3.checks if c.id == R.DELAY_FLAG_ID).status == "unknown"


# ------------------------------------------------------------------------------------------------ PTT (5.3)
def ptt(
    text: str = "how are my tyres",
    src: str = "screen",
    client: str | None = "ipad",
    playback: int | None = 1500,
    answer_source: str = "deterministic",
) -> PttRecord:
    return PttRecord(
        NOW,
        "live",
        "s1",
        1,
        "m1",
        src,
        client,
        text,
        answer_source=answer_source if text else "none",
        to_playback_ms=playback if text else None,
    )


def test_ptt_rules() -> None:
    two = [ptt(), ptt(src="wheel")]
    assert R.ptt_verdict(two, True, True, None, NOW).verdict == "pass"
    assert R.ptt_verdict(two, True, False, True, NOW).verdict == "pass"  # the AirPod tick stands in for the label
    assert R.ptt_verdict(two, True, False, None, NOW).verdict == "inconclusive"
    assert R.ptt_verdict(two, None, True, None, NOW).verdict == "inconclusive"  # no Tailscale report
    assert R.ptt_verdict([ptt()], True, True, None, NOW).verdict == "inconclusive"
    assert (
        R.ptt_verdict([ptt(client="browser"), ptt(client="browser")], True, True, None, NOW).verdict == "inconclusive"
    )
    # say-again share: 1 of 3 is allowed, 2 of 4 is not
    assert R.ptt_verdict([*two, ptt("")], True, True, None, NOW).verdict == "pass"
    assert R.ptt_verdict([*two, ptt(""), ptt("")], True, True, None, NOW).verdict == "inconclusive"
    # three attempts and nothing answered fail; typed questions are not attempts
    assert R.ptt_verdict([ptt(""), ptt(""), ptt("")], True, True, None, NOW).verdict == "fail"
    assert R.ptt_verdict([ptt(playback=None)] * 3, True, True, None, NOW).verdict == "fail"
    typed = [ptt(src="typed")] * 5
    assert R.ptt_verdict(typed, True, True, None, NOW).metrics["typed"] == 5
    assert R.ptt_verdict([], True, True, None, NOW).verdict == "no_evidence"


def test_ptt_latency_warnings_do_not_change_the_verdict() -> None:
    recs = [ptt(playback=4001), ptt(src="wheel", playback=21400, answer_source="llm")]
    st = R.ptt_verdict(recs, True, True, None, NOW)
    assert st.verdict == "pass"
    by = {c.id: c for c in st.checks}
    assert by["fast_latency"].status == "not_met" and by["llm_latency"].status == "not_met"
    assert st.metrics["max_llm_to_playback_ms"] == 21400
    ok = R.ptt_verdict(
        [ptt(playback=4000), ptt(src="wheel", playback=20000, answer_source="llm")], True, True, None, NOW
    )
    assert all(c.status == "met" for c in ok.checks if c.id.endswith("latency"))


# ------------------------------------------------------------------------------------------------ speak windows (5.4)
@pytest.mark.parametrize(
    ("on_track", "brake", "steer", "gap", "cls"),
    [
        (False, 0.9, 0.9, 0.0, "off_track"),
        (True, 0.10, 0.0, 3.0, "overlap"),  # C: analysis.braking.BRAKE_ON
        (True, 0.0999, 0.0, 3.0, "clean"),
        (True, 0.0, 0.25, 3.0, "overlap"),
        (True, 0.0, 0.2499, 3.0, "clean"),
        (True, 0.0, 0.0, 0.49, "tight"),
        (True, 0.0, 0.0, 0.5, "clean"),
        (True, 0.0, 0.0, None, "clean"),
        (True, None, 0.0, 1.0, "unmeasured"),
    ],
)
def test_classify_playback(
    on_track: bool, brake: float | None, steer: float | None, gap: float | None, cls: str
) -> None:
    assert R.classify_playback(on_track, brake, steer, gap) == cls


def pro(cls: str, lap: int, max_brake: float = 0.0) -> ProactiveRecord:
    p = ProactiveRecord(
        NOW,
        "live",
        "s1",
        1,
        f"m{lap}",
        "coaching",
        "x",
        lap,
        None,
        None,
        0.0,
        {"on_track": True},
        started=True,
        start_frame={"lap": lap},
    )
    p.cls, p.max_brake = cls, max_brake
    return p


def test_speak_window_verdicts() -> None:
    six = [pro("clean", lap) for lap in (1, 1, 2, 2, 3, 3)]
    assert R.speak_windows_verdict(six, NOW).verdict == "pass"
    assert R.speak_windows_verdict(six[:5], NOW).verdict == "inconclusive"
    assert R.speak_windows_verdict([pro("clean", 1)] * 6, NOW).verdict == "inconclusive"  # one lap
    assert R.speak_windows_verdict([*six, pro("tight", 4)], NOW).verdict == "pass"
    assert R.speak_windows_verdict([*six, pro("tight", 4), pro("tight", 5)], NOW).verdict == "inconclusive"
    assert R.speak_windows_verdict([*six, pro("overlap", 4, 0.2)], NOW).verdict == "inconclusive"
    assert R.speak_windows_verdict([*six, pro("overlap", 4, 0.5)], NOW).verdict == "fail"  # heavy
    assert R.speak_windows_verdict([*six, pro("overlap", 4, 0.2), pro("overlap", 5, 0.2)], NOW).verdict == "fail"
    assert R.speak_windows_verdict([], NOW).verdict == "no_evidence"


# ------------------------------------------------------------------------------------------------ iPad (5.6-5.9)
def sample(
    t: float,
    *,
    visible: bool = True,
    route: str = "drive/coach",
    wake: str = "on",
    telemetry: str = "live",
    tier: str = "live",
    standalone: bool = True,
    seq: int = 0,
) -> ClientSample:
    return ClientSample(NOW + t, seq, visible, route, True, wake, telemetry, tier, standalone, True)  # type: ignore[arg-type]


def every(seconds: float, step: float = 15.0, **kw: Any) -> list[ClientSample]:
    n = int(seconds // step)
    out = [sample(i * step, **kw) for i in range(n + 1)]
    if out[-1].t_unix - NOW < seconds:
        out.append(sample(seconds, **kw))
    return out


def test_streak_boundaries() -> None:
    live = lambda t: t == "live"  # noqa: E731
    best, inst, hidden, gaps = E.client_streaks(every(299), live)
    assert best == pytest.approx(299) and inst == pytest.approx(299) and hidden == gaps == 0
    assert E.client_streaks(every(300), live)[1] == pytest.approx(300)
    # a 45 s gap keeps the streak, 46 s breaks it (and counts as a gap while driving)
    ok = [sample(0), sample(45), sample(90), sample(135), sample(180), sample(225), sample(270), sample(315)]
    assert E.client_streaks(ok, live)[0] == pytest.approx(315)
    broken = [sample(0), sample(46), *[sample(46 + 15 * i) for i in range(1, 20)]]
    best, _, _, gaps = E.client_streaks(broken, live)
    assert gaps == 1 and best == pytest.approx(285)
    # hidden while driving breaks the streak and is counted; menus or replays never count
    hid = [*every(200), sample(201, visible=False), *[sample(215 + 15 * i) for i in range(10)]]
    best, _, hidden, _ = E.client_streaks(hid, live)
    assert hidden == 1 and best == pytest.approx(200)
    assert E.client_streaks(every(600, tier="recorded"), live)[0] == 0.0
    assert E.client_streaks(every(600, route="setup/validation"), live)[0] == 0.0
    assert E.client_streaks(every(600, wake="refused"), live)[0] == 0.0
    best, inst, _, _ = E.client_streaks(every(600, standalone=False), live)
    assert best == pytest.approx(600) and inst == 0.0


def test_home_screen_verdict() -> None:
    f = R.ScreenFacts(n_reports=30, best_streak_s=300, installed_streak_s=300, standalone=True, safari_version="18.6")
    assert R.home_screen_verdict(f, None, NOW).verdict == "pass"
    f.installed_streak_s = 299
    assert R.home_screen_verdict(f, None, NOW).verdict == "inconclusive"
    f.drive_hidden = 1
    assert R.home_screen_verdict(f, None, NOW).verdict == "inconclusive"  # maybe the driver's own doing
    assert R.home_screen_verdict(f, True, NOW).verdict == "fail"  # "I did not touch the iPad"
    old = R.ScreenFacts(n_reports=30, best_streak_s=400, installed_streak_s=400, standalone=True, safari_version="18.3")
    st = R.home_screen_verdict(old, None, NOW)
    assert st.verdict == "pass" and any("18.4" in r for r in st.reasons)
    assert R.home_screen_verdict(R.ScreenFacts(), None, NOW).verdict == "no_evidence"


def test_glance_one_message_endurance() -> None:
    st = R.glance_verdict({1: 3, 2: 1}, True, NOW)
    assert st.verdict == "driver_only" and all(c.status == "met" for c in st.checks)
    assert R.one_message_verdict([(1, "a", ["a"]), (2, "b", ["b", "c"]), (3, "c", ["c"])], NOW).verdict == "pass"
    assert R.one_message_verdict([(1, "a", ["a"]), (2, "b", ["b"])], NOW).verdict == "inconclusive"
    assert R.one_message_verdict([(1, "a", ["a"]), (2, "x", ["b"])], NOW).verdict == "fail"
    assert R.one_message_verdict([], NOW).verdict == "no_evidence"
    # coachref: a drill lap's one coaching message is its drill point; anything else on a drill lap fails
    drill_ok = [(1, "drill12:a1", ["drill12:a1"]), (2, "drill12:a2", ["drill12:a2"]), (3, "c", ["c"])]
    assert R.one_message_verdict(drill_ok, NOW, drill_breaches=0).verdict == "pass"
    v = R.one_message_verdict(drill_ok, NOW, drill_breaches=1)
    assert v.verdict == "fail" and v.metrics["drill_breaches"] == 1
    assert R.endurance_verdict([60.0] * 360, 0, NOW).verdict == "pass"
    assert R.endurance_verdict([60.0] * 359, 0, NOW).verdict == "inconclusive"
    assert R.endurance_verdict([60.0] * 324 + [30.0] * 36, 0, NOW).verdict == "pass"  # exactly 90 %
    assert R.endurance_verdict([60.0] * 323 + [30.0] * 37, 0, NOW).verdict == "inconclusive"
    assert R.endurance_verdict([60.0] * 360, 1, NOW).verdict == "inconclusive"
    assert R.endurance_verdict([], 0, NOW).verdict == "no_evidence"


# ------------------------------------------------------------------------------------------------ games (5.10-5.11)
def gt7(**kw: Any) -> R.GameFacts:
    base: dict[str, Any] = {
        "game": "gt7",
        "sessions": 3,
        "driving_sessions": 1,
        "menu_sessions": 2,
        "track_id": "gt7:abc",
        "track_name": "Unidentified GT7 circuit (3.80 km)",
        "timed_laps": [105151, 105596, 103358],
        "clean_laps": 3,
        "observations": 2,
        "best_lap_ms_game": 103358,
        "variants": ["C"],
        "rejected": 0,
        "errors": 0,
        "heartbeat_sent": 900,
        "heartbeat_errors": 0,
        "lan_sender": True,
        "median_rate_hz": 59.9,
    }
    base.update(kw)
    return R.GameFacts(**base)


def test_gt7_verdict() -> None:
    assert R.gt7_verdict(gt7(), True, [], NOW).verdict == "pass"
    st = R.gt7_verdict(gt7(), None, [], NOW)
    assert st.verdict == "inconclusive" and any("Tick" in r for r in st.reasons)
    assert R.gt7_verdict(gt7(timed_laps=[105151, 105596]), True, [], NOW).verdict == "inconclusive"
    assert R.gt7_verdict(gt7(clean_laps=1), True, [], NOW).verdict == "inconclusive"
    assert R.gt7_verdict(gt7(median_rate_hz=49.9), True, [], NOW).verdict == "inconclusive"
    assert R.gt7_verdict(gt7(rejected=1), True, [], NOW).verdict == "fail"
    assert R.gt7_verdict(gt7(errors=2), True, [], NOW).verdict == "fail"
    mismatch = R.gt7_verdict(gt7(best_lap_ms_game=103000), True, [], NOW)
    assert mismatch.verdict == "pass" and any("unstable" in r for r in mismatch.reasons)  # warning only
    # a replay has no heartbeat / sender / rate: those checks stay unknown
    replay = gt7(heartbeat_sent=None, lan_sender=None, median_rate_hz=None)
    by = {c.id: c.status for c in R.gt7_verdict(replay, None, [], NOW).checks}
    assert by["heartbeat"] == by["lan"] == by["rate"] == "unknown" and by["best_lap"] == "met"
    assert R.gt7_verdict(R.GameFacts(game="gt7"), None, [], NOW).verdict == "no_evidence"


def ac(**kw: Any) -> R.GameFacts:
    base: dict[str, Any] = {
        "game": "ac",
        "sessions": 1,
        "driving_sessions": 1,
        "track_id": "ac:ks_silverstone",
        "timed_laps": [138817, 137000, 136500],
        "clean_laps": 2,
        "observations": 1,
        "corners": 12,
        "rejected": 0,
        "errors": 0,
        "handshakes": 1,
        "median_rate_hz": 59.8,
        "lan_sender": True,
        "track_length_quality": "full_lap",
        "lap_distance_status": "ok",
        "handshake_status": 4242,
        "handshake_encoding": "utf-16le",
    }
    base.update(kw)
    return R.GameFacts(**base)


def test_ac_verdict() -> None:
    assert R.ac_verdict(ac(), True, [], NOW).verdict == "pass"
    assert R.ac_verdict(ac(track_length_quality="estimate"), True, [], NOW).verdict == "inconclusive"
    assert R.ac_verdict(ac(corners=2), True, [], NOW).verdict == "inconclusive"
    assert R.ac_verdict(ac(rejected=3), True, [], NOW).verdict == "fail"
    stuck = ac(timed_laps=[], clean_laps=0, streaming_s=300.0)
    assert R.ac_verdict(stuck, None, [], NOW).verdict == "fail"
    assert R.ac_verdict(ac(timed_laps=[], clean_laps=0, streaming_s=299.0), None, [], NOW).verdict == "inconclusive"
    recorded = ac(
        timed_laps=[],
        clean_laps=0,
        handshakes=None,
        median_rate_hz=None,
        track_length_quality="estimate",
        lap_distance_status="waiting",
    )
    st = R.ac_verdict(recorded, None, [], NOW)
    assert st.verdict == "inconclusive" and st.reasons[0] == "No timed lap yet"
    by = {c.id: c for c in st.checks}
    assert by["handshake"].status == "met" and by["handshake"].value == "answered"
    assert st.metrics["handshake_status"] == 4242 and st.metrics["handshake_encoding"] == "utf-16le"  # maintainer
    # the checks list what is missing; the reasons only count them and say what to do (no repeated check rows)
    gating = [c for c in st.checks if c.id not in R.INPUT_CHECK_IDS]
    met = sum(1 for c in gating if c.status == "met")
    assert st.reasons == [
        "No timed lap yet",
        f"{met} of {len(gating)} checks met",
        "Tick 'lap times match the game's' when you have compared them",
    ]
    unnamed = R.ac_verdict(ac(track_id=None, track_name=None, timed_laps=[]), None, [], NOW)
    assert {c.id: c.label for c in unnamed.checks}["timed_laps"] == "Laps timed on one circuit"  # no "(-)"


def test_ac_optional_pedal_check_never_gates() -> None:
    """The input check has no verdict of its own: soft pedals (0.94) leave AC passing, as GT7."""
    pedals = [InputPhaseRecord("ac_ps5", "pedals", NOW, NOW + 6, samples=40, throttle_max=0.94, brake_max=1.0)]
    st = R.ac_verdict(ac(), True, pedals, NOW)
    assert st.verdict == "pass" and {c.id: c.status for c in st.checks}["pedals"] == "not_met"


def test_input_check_evidence() -> None:
    def ph(phase: str, lo: float | None = None, hi: float | None = None, **kw: Any) -> InputPhaseRecord:
        mean = None if lo is None or hi is None else (lo + hi) / 2
        return InputPhaseRecord(
            "gt7_ps5", phase, NOW, NOW + 3, samples=30, steer_mean=mean, steer_min=lo, steer_max=hi, **kw
        )

    # the left phase starts from the centre; the right phase from full left lock (its mean can sit near 0)
    ok = {c.id: c for c in R.input_check_checks([ph("left", -0.98, 0.0), ph("right", -0.98, 0.97)], "gt7")}
    assert ok["steer_sign"].status == "met" and ok["steer_sign"].value == "left -0.98, right +0.97"
    inv = {c.id: c for c in R.input_check_checks([ph("left", 0.0, 0.9), ph("right", -0.92, 0.9)], "gt7")}
    assert inv["steer_sign"].status == "not_met" and "inverted" in (inv["steer_sign"].value or "")
    short = {c.id: c for c in R.input_check_checks([ph("left", -0.3, 0.0), ph("right", -0.3, 0.4)], "gt7")}
    assert short["steer_sign"].status == "unknown"  # full lock not reached: no verdict either way
    acs = {
        c.id: c
        for c in R.input_check_checks(
            [ph("right", 0.9, steer_raw_range=[-144.9, 211.9], rotation_deg=900.0), ph("reverse", 0.0, gear_min=-1)],
            "ac",
        )
    }
    assert acs["steer_raw"].status == "unknown" and "211.9" in (acs["steer_raw"].value or "")
    assert acs["reverse"].status == "met"


# ------------------------------------------------------------------------------------------------ game choice, switches
def test_game_selection_verdict() -> None:
    g = lambda m: GameTransition(NOW, "f1_25_ps5", "gt7_ps5", m)  # noqa: E731
    chosen = GameTransition(NOW, "gt7_ps5", "gt7_ps5", False)
    assert R.game_selection_verdict([g(False), g(True), chosen], NOW).verdict == "pass"
    assert R.game_selection_verdict([g(False), g(True)], NOW).verdict == "inconclusive"
    # the banner going because the choice was cleared, or the game stopped, is not "chose that game"
    cleared = GameTransition(NOW, None, "gt7_ps5", False)
    stopped = GameTransition(NOW, "f1_25_ps5", None, False)
    assert R.game_selection_verdict([g(True), cleared], NOW).verdict == "inconclusive"
    assert R.game_selection_verdict([g(True), stopped], NOW).verdict == "inconclusive"
    assert R.game_selection_verdict([], NOW).verdict == "no_evidence"


def sw(**kw: Any) -> SwitchRecord:
    base: dict[str, Any] = {
        "t_unix": NOW,
        "tier": "live",
        "session_id": "a",
        "driver_id": 2,
        "from_driver_id": 1,
        "to_driver_id": 2,
        "session_before": "a",
        "session_after": "b",
        "laps_before_after_switch": 0,
        "laps_after": 2,
        "cue_reason_after": "new driver: waiting for a lap against their reference",
        "before_driver_id": 1,
        "after_driver_id": 2,
        "settled": True,
    }
    base.update(kw)
    return SwitchRecord(**base)


def test_switch_rules() -> None:
    assert R.switch_ok(sw()) == (True, [])
    assert R.switch_verdict([sw()], NOW).verdict == "pass"
    assert R.switch_verdict([sw(), sw()], NOW).reasons == ["2 switches: each driver's laps under their own name"]
    assert R.switch_verdict([sw()], NOW).reasons == ["1 switch: each driver's laps under their own name"]
    assert R.switch_verdict([sw(laps_after=0)], NOW).verdict == "inconclusive"
    assert R.switch_verdict([sw(laps_before_after_switch=1)], NOW).verdict == "fail"
    assert R.switch_verdict([sw(after_driver_id=1)], NOW).verdict == "fail"
    survived = sw(cue_reason_after=None, cue_plan_owner=1)
    assert R.switch_verdict([survived], NOW).verdict == "fail"
    own_ref = sw(cue_reason_after=None, cue_plan_owner=2)
    assert R.switch_verdict([own_ref], NOW).verdict == "pass"
    assert R.switch_verdict([], NOW).verdict == "no_evidence"


# ------------------------------------------------------------------------------------------------ result table (5.13)
AUTOS = ("pass", "fail", "inconclusive", "no_evidence", "not_live", "unavailable", "driver_only")


def expected(driver: str | None, auto: str, skipped: bool) -> str:
    if skipped:
        return "skipped"
    if driver is None:
        if auto in ("no_evidence", "unavailable", "driver_only", "not_live"):
            return "not_run"
        return "fail" if auto == "fail" else "needs_review"
    if driver == "didnt" or auto == "fail":
        return "fail"
    return "pass" if auto in ("pass", "driver_only") else "needs_review"


@pytest.mark.parametrize(
    ("driver", "auto", "skipped"), list(itertools.product((None, "worked", "didnt"), AUTOS, (False, True)))
)
def test_result_table_exhaustive(driver: str | None, auto: str, skipped: bool) -> None:
    marks = [] if driver is None else [DriverMark(1, driver)]  # type: ignore[arg-type]
    assert R.item_result(AutoState(auto), marks, False, skipped) == expected(driver, auto, skipped)  # type: ignore[arg-type]


def test_result_per_driver_and_review_flag() -> None:
    a = AutoState("driver_only")
    assert R.item_result(a, [DriverMark(1, "worked"), DriverMark(2, "worked")], True, False) == "pass"
    assert R.item_result(a, [DriverMark(1, "worked"), DriverMark(2, "didnt")], True, False) == "fail"
    flagged = AutoState("pass", checks=[Check("review_delay", "x", "not_met")])
    assert R.item_result(flagged, [DriverMark(1, "worked")], False, False) == "needs_review"
    latest = [DriverMark(1, "didnt"), DriverMark(1, "worked")]
    assert R.item_result(AutoState("pass"), latest, False, False) == "pass"  # newest mark wins


def test_counts_read_as_plain_words() -> None:
    assert R.n_of(1, "lap") == "1 lap" and R.n_of(3, "lap") == "3 laps" and R.n_of(0, "session") == "0 sessions"
    assert R.n_of(2, "heads-up", "heads-ups") == "2 heads-ups"
