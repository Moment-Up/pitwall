"""Thresholds and pure verdict functions of the rig validation kit (no I/O, no clock, no LLM).

Every constant has a comment. **H** marks a heuristic threshold (a first guess, tunable; the report says
"heuristic"), **C** a contract constant imported from the code it checks. The inputs are evidence records that
``validate.evidence`` has already filtered to one evidence tier; ``evidence.compute_auto`` decides which tier counts
(only ``live`` can pass).
"""

from __future__ import annotations

import ipaddress
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pitwall.analysis.braking import BRAKE_ON
from pitwall.coach.cues import FALLBACK_REASONS, MARGIN_M, MIN_REF_BRAKE_PEAK
from pitwall.validate.model import (
    AutoState,
    AutoVerdict,
    Check,
    CheckStatus,
    CueRecord,
    DriverMark,
    GameTransition,
    InputPhaseRecord,
    ItemResult,
    ProactiveRecord,
    PttRecord,
    SwitchRecord,
    Tier,
)

# ------------------------------------------------------------------------------------------------ braking calls
CUE_MARGIN_M = MARGIN_M  # C: coach.cues.MARGIN_M - an error above it means the word landed past the reference point
MIN_ONSET_PEAK = MIN_REF_BRAKE_PEAK  # C: coach.cues.MIN_REF_BRAKE_PEAK - lighter applications are dabs, not zones
ONSET_WINDOW_M = 100.0  # H: driver onset searched within +/-100 m of the call's target (real Austria race: 84/86)
EARLY_MAX_S = 0.6  # H: a key word more than 0.6 s before the intended point counts as early
ZONE_BIN_M = 50.0  # distinct braking zones = targets rounded to 50 m (corner names shift while the model learns)
CUE_MIN_MEASURED = 8  # H: calls measured before a pass
CUE_MIN_ZONES = 3  # H: over at least this many braking zones
CUE_MAX_EARLY_SHARE = 0.10  # H
CUE_MAX_LATE_SHARE = 0.10  # H: fail above this share of late calls (or at 2 late calls)
CUE_FAIL_LATE = 2  # two late calls fail the item whatever the share
CUE_MAX_DROP_SHARE = 0.20  # H: delivery failures per fired call
DELIVERY_DROPS = frozenset({"late hand-off", "audio not ready"})  # C: voice.hub - the radio failed to deliver
DELAY_MIN_SAMPLES = 8  # H: onsets needed on cued and on baseline laps before the delay flag can be raised
DELAY_FLAG_M = 10.0  # H: real-data spread without audio was p10 -11.7 m / p90 +16.1 m, so a baseline is required
DELAY_FLAG_ID = "review_delay"  # a check whose id starts with "review_" forces needs_review when not met
BASELINE_EXCLUDED_FLAGS = frozenset({"flashback", "pit_in", "pit_out"})

# ------------------------------------------------------------------------------------------------ push-to-talk
PTT_MIN_ROUNDTRIPS = 2  # H
PTT_FAIL_ATTEMPTS = 3  # three attempts and no round trip fail the item
SAY_AGAIN_MAX_SHARE = 1 / 3  # H: empty transcripts ("Say again?") per attempt
FAST_ANSWER_MAX_MS = 4000  # H: deterministic answers, release -> playback started
LLM_ANSWER_MAX_MS = 20000  # H: docs/status.md measures 9-12 s for LLM answers

# ------------------------------------------------------------------------------------------------ speak windows
OVERLAP_BRAKE = BRAKE_ON  # C: analysis.braking.BRAKE_ON - the pedal level that starts a braking event
OVERLAP_STEER = 0.25  # H: about twice voice.scheduler.CALM_STEERING
TIGHT_GAP_S = 0.5  # H: half of voice.scheduler.SPEAK_WINDOW_MARGIN_S
HEAVY_BRAKE = 0.5  # H: one overlap into braking this hard fails the item
SPEAK_MIN_MEASURED = 6  # H
SPEAK_MIN_LAPS = 3  # H
SPEAK_MAX_TIGHT = 1

# ------------------------------------------------------------------------------------------------ natural voice
KOKORO_MIN_MESSAGES = 5  # H
KOKORO_MAX_FALLBACK_SHARE = 0.20  # H

# ------------------------------------------------------------------------------------------------ iPad
GAP_S = 45.0  # a report gap longer than this breaks a streak (reports every REPORT_INTERVAL_S)
REPORT_INTERVAL_S = 15.0
WAKE_MIN_S = 300.0  # H: longer than the 2-minute Auto-Lock the driver sets for the test
WAKE_BUG_SAFARI = (18, 4)  # lib/wake.ts: before Safari 18.4 a Home Screen app's lock can resolve and still sleep
GLANCE_MIN_LAPS = 3  # H: spec 14.5 #1
ONE_MESSAGE_MIN = 3  # spoken coaching points needed
ENDURANCE_MIN_WINDOWS = 360  # 10 s windows: one hour
ENDURANCE_MIN_FPS = 45.0  # H
ENDURANCE_MIN_SHARE = 0.90  # H

# ------------------------------------------------------------------------------------------------ games
GAME_MIN_RATE_HZ = 50.0  # H: both games send about 60 Hz
GAME_MIN_TIMED_LAPS = 3  # H (AC_MIN_TIMED_LAPS in the spec; GT7 uses the same)
GAME_MIN_CLEAN_LAPS = 2  # H
AC_MIN_CORNERS = 3
AC_FAIL_STREAM_S = 300.0  # five minutes streaming on a known line with no timed lap fails AC
STEER_SIGN_MIN = 0.5  # input check: full lock reads beyond +/-0.5 in the CarFrame convention (-1 left, +1 right)
INPUT_CHECK_IDS = ("steer_sign", "steer_raw", "reverse", "pedals")  # input check: for the maintainer, never gating

# ------------------------------------------------------------------------------------------------ drivers
SWITCH_SETTLE_S = 2.0  # the new session / cue plan is read this long after a switch
DRIVER_RESET_REASONS = FALLBACK_REASONS  # C: coach.cues - empty-plan reasons of a fresh driver

NOT_LIVE_TEXT: dict[Tier, str] = {
    "recorded": "This data is from a replay: it is shown but does not count",
    "synthetic": "This data is synthetic: it is shown but does not count",
    "loopback": "This data came from a recording sent on this computer: it is shown but does not count",
    "unknown": "Telemetry was not live from a console: shown but does not count",
    "live": "",
}


# ================================================================================================ helpers
def sender_class(ip: str | None) -> Literal["loopback", "lan"] | None:
    """Only the class of a sender is kept, never its address."""
    if not ip:
        return None
    try:
        return "loopback" if ipaddress.ip_address(ip.split("%", 1)[0]).is_loopback else "lan"
    except ValueError:
        return None


def tier_of(synthetic: bool, source: str | None, sender: str | None, telemetry: str) -> Tier:
    """Evidence tier of a moment (spec 5.1). ``sender`` is ``sender_class`` of the active input's freshest sender."""
    if synthetic:
        return "synthetic"
    if source is not None and source.startswith("replay:"):
        return "recorded"
    if sender == "loopback":
        return "loopback"
    if telemetry == "live" and sender == "lan":
        return "live"
    return "unknown"


def dominant_tier(tiers: Iterable[Tier]) -> Tier | None:
    counts: dict[Tier, int] = {}
    for t in tiers:
        counts[t] = counts.get(t, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def zone_key(target_m: float) -> int:
    return round(target_m / ZONE_BIN_M)


def _median(xs: Sequence[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(x, nd)


def n_of(n: int, word: str, many: str | None = None) -> str:
    """``"1 lap"`` / ``"3 laps"``: a count in plain words."""
    return f"{n} {word if n == 1 else (many or word + 's')}"


def check(
    cid: str,
    label: str,
    ok: bool | None,
    value: str | None = None,
    target: str | None = None,
    heuristic: bool = False,
) -> Check:
    status: CheckStatus = "unknown" if ok is None else ("met" if ok else "not_met")
    return Check(cid, label, status, value, target, heuristic)


def fmt_m(x: float | None) -> str:
    return "-" if x is None else f"{x:+.1f} m"


def state(
    verdict: AutoVerdict,
    reasons: list[str],
    checks: list[Check],
    metrics: dict[str, float | int | str | None],
    now: float,
) -> AutoState:
    return AutoState(verdict, reasons, checks, metrics, None, now)


def forces_review(auto: AutoState) -> bool:
    """A ``review_*`` check that is not met forces ``needs_review`` on a pass (e.g. calls may delay braking)."""
    return any(c.id.startswith("review_") and c.status == "not_met" for c in auto.checks)


# ================================================================================================ cues (5.2)
def classify_cue(c: CueRecord) -> str:
    """``dropped`` / ``unmeasured`` / ``late`` (error above the margin: past the reference point) / ``early`` (key
    word more than ``EARLY_MAX_S`` before the intended point: the target for a brake call, the target less the
    anticipation for a marker) / ``on_time``."""
    if c.outcome == "dropped":
        return "dropped"
    if c.error_m is None:
        return "unmeasured"
    if c.error_m > CUE_MARGIN_M:
        return "late"
    v = c.speed_kph / 3.6
    if v > 0 and (CUE_MARGIN_M - c.error_m) > EARLY_MAX_S * v:
        return "early"
    return "on_time"


def match_onset(target_m: float, onsets: Sequence[float]) -> float | None:
    """The driver's braking onset for a call: the nearest onset within ``ONSET_WINDOW_M`` of the call's target, by
    distance only (never by corner name: learned names shift while the track model versions)."""
    best: float | None = None
    for o in onsets:
        d = abs(o - target_m)
        if d <= ONSET_WINDOW_M and (best is None or d < abs(best - target_m)):
            best = o
    return best


def cues_verdict(cues: Sequence[CueRecord], baseline: Sequence[float], now: float) -> AutoState:
    """``baseline``: onset - target on laps driven with calls off, same sessions, same zones."""
    own = [c for c in cues if c.kind == "brake" and not c.heads_up]
    heads_up = [c for c in cues if c.heads_up]
    markers = [c for c in cues if c.kind == "marker" and not c.heads_up]
    fired = len(own)
    sent = sum(1 for c in own if c.outcome == "sent")
    dropped_delivery = sum(1 for c in own if c.outcome == "dropped" and c.drop_reason in DELIVERY_DROPS)
    dropped_expected = sum(1 for c in own if c.outcome == "dropped" and c.drop_reason not in DELIVERY_DROPS)
    measured = [c for c in own if c.cls in ("on_time", "late", "early")]
    late = sum(1 for c in measured if c.cls == "late")
    early = sum(1 for c in measured if c.cls == "early")
    zones = len({zone_key(c.target_m) for c in measured})
    n = len(measured)
    cued_onsets = [c.onset_vs_point_m for c in own if c.onset_vs_point_m is not None]
    heard = [c.heard_vs_point_m for c in measured if c.heard_vs_point_m is not None]
    words = [c.onset_vs_word_s for c in own if c.onset_vs_word_s is not None]
    lat = [float(c.latency_ms) for c in measured if c.latency_ms is not None]
    metrics: dict[str, float | int | str | None] = {
        "fired": fired,
        "sent": sent,
        "dropped_delivery": dropped_delivery,
        "dropped_expected": dropped_expected,
        "measured": n,
        "late": late,
        "early": early,
        "zones": zones,
        "median_heard_vs_point_m": _r(_median(heard)),
        "median_latency_ms": None if not lat else round(statistics.median(lat)),
        "median_onset_vs_point_m": _r(_median(cued_onsets)),
        "median_onset_vs_word_s": _r(_median(words), 2),
        "baseline_median_onset_vs_point_m": _r(_median(baseline)),
        "heads_up_fired": len(heads_up),
        "markers_fired": len(markers),
    }
    drop_share = dropped_delivery / fired if fired else 0.0
    checks = [
        check("measured", "Calls measured", n >= CUE_MIN_MEASURED, str(n), f">= {CUE_MIN_MEASURED}", True),
        check("late", "Calls heard past your braking point", late == 0, str(late), "0"),
        check("zones", "Different braking zones", zones >= CUE_MIN_ZONES, str(zones), f">= {CUE_MIN_ZONES}", True),
        check(
            "early",
            "Calls more than 0.6 s early",
            None if n == 0 else early / n <= CUE_MAX_EARLY_SHARE,
            f"{early} of {n}",
            "<= 10 %",
            True,
        ),
        check(
            "drops",
            "Calls lost in delivery",
            None if fired == 0 else drop_share <= CUE_MAX_DROP_SHARE,
            f"{dropped_delivery} of {fired}",
            "<= 20 %",
            True,
        ),
    ]
    reasons: list[str] = []
    delayed = None
    if len(cued_onsets) >= DELAY_MIN_SAMPLES and len(baseline) >= DELAY_MIN_SAMPLES:
        diff = statistics.median(cued_onsets) - statistics.median(baseline)
        delayed = diff >= DELAY_FLAG_M
        checks.append(
            check(
                DELAY_FLAG_ID,
                "Calls not delaying your braking",
                not delayed,
                f"{diff:+.1f} m vs calls off",
                f"< +{DELAY_FLAG_M:.0f} m",
                True,
            )
        )
        if delayed:
            reasons.append(
                f"Calls may be delaying your braking: median onset {diff:+.1f} m later than with calls off (heuristic)"
            )
    else:
        checks.append(
            check(
                DELAY_FLAG_ID,
                "Calls not delaying your braking",
                None,
                f"{len(cued_onsets)} cued, {len(baseline)} baseline onsets",
                f">= {DELAY_MIN_SAMPLES} each",
                True,
            )
        )
    if baseline:
        reasons.append(f"Baseline: {len(baseline)} braking points on laps with calls off")
    if not cues:
        return state("no_evidence", ["No braking calls yet"], [], metrics, now)
    if fired == 0:
        what = n_of(len(heads_up), "AI-field heads-up") if heads_up else n_of(len(markers), "corner marker")
        return state(
            "inconclusive",
            [f"Only {what} so far: no calls from your own reference lap", *reasons],
            checks,
            metrics,
            now,
        )
    if late >= CUE_FAIL_LATE or (n and late / n > CUE_MAX_LATE_SHARE):
        return state("fail", [f"{late} of {n} calls landed past your braking point", *reasons], checks, metrics, now)
    missing: list[str] = []
    if n < CUE_MIN_MEASURED:
        missing.append(f"{n} calls measured, {CUE_MIN_MEASURED} needed")
    if zones < CUE_MIN_ZONES:
        missing.append(f"{zones} braking zones, {CUE_MIN_ZONES} needed")
    if late:
        missing.append(f"{late} call landed past your braking point")
    if n and early / n > CUE_MAX_EARLY_SHARE:
        missing.append(f"{early} of {n} calls were early")
    if fired and drop_share > CUE_MAX_DROP_SHARE:
        missing.append(f"{dropped_delivery} of {fired} calls lost in delivery")
    if not missing:
        return state("pass", [f"{n} calls over {zones} zones, none late", *reasons], checks, metrics, now)
    return state("inconclusive", missing + reasons, checks, metrics, now)


# ================================================================================================ push-to-talk (5.3)
def ptt_verdict(
    ptt: Sequence[PttRecord],
    ipad_tailscale: bool | None,
    ipad_airpods: bool | None,
    attest_airpod: bool | None,
    now: float,
) -> AutoState:
    """``ipad_tailscale``: an iPad reported ``origin_kind == tailscale_https``; ``ipad_airpods``: its microphone
    label classified as AirPods (``None`` = no iPad report)."""
    voice = [p for p in ptt if p.source != "typed"]
    attempts = len(voice)
    say_again = sum(1 for p in voice if not p.transcript.strip())
    trips = [p for p in voice if p.transcript.strip() and p.answer_source != "none" and p.to_playback_ms is not None]
    ipad_trips = [p for p in trips if p.client == "ipad"]
    screen = sum(1 for p in trips if p.source == "screen")
    wheel = sum(1 for p in trips if p.source == "wheel")
    typed = len(ptt) - attempts
    fast = [p.to_playback_ms for p in trips if p.answer_source in ("deterministic", "command") and p.to_playback_ms]
    llm = [p.to_playback_ms for p in trips if p.answer_source in ("llm", "fallback") and p.to_playback_ms]
    marked = [p for p in ptt if p.heard_right is not None]
    metrics: dict[str, float | int | str | None] = {
        "attempts": attempts,
        "roundtrips": len(trips),
        "ipad_roundtrips": len(ipad_trips),
        "screen": screen,
        "wheel": wheel,
        "typed": typed,
        "say_again": say_again,
        "n_marked": len(marked),
        "n_wrong": sum(1 for p in marked if p.heard_right is False),
        "median_fast_to_playback_ms": None if not fast else round(statistics.median(fast)),
        "max_llm_to_playback_ms": max(llm) if llm else None,
    }
    airpod = (
        True if (ipad_airpods or attest_airpod) else (None if ipad_airpods is None and not attest_airpod else False)
    )
    share = say_again / attempts if attempts else 0.0
    checks = [
        check(
            "roundtrips",
            "Questions heard and answered on the iPad",
            len(ipad_trips) >= PTT_MIN_ROUNDTRIPS,
            str(len(ipad_trips)),
            f">= {PTT_MIN_ROUNDTRIPS}",
            True,
        ),
        check("origin", "Over Tailscale HTTPS", ipad_tailscale, "tailscale_https" if ipad_tailscale else None),
        check(
            "airpod",
            "AirPod microphone",
            airpod,
            "airpods" if ipad_airpods else ("you said so" if attest_airpod else None),
            "airpods",
            True,
        ),
        check(
            "say_again",
            "Questions not heard",
            None if not attempts else share <= SAY_AGAIN_MAX_SHARE,
            f"{say_again} of {attempts}",
            "<= 1 in 3",
            True,
        ),
    ]
    reasons: list[str] = []
    slow_fast = [x for x in fast if x > FAST_ANSWER_MAX_MS]
    slow_llm = [x for x in llm if x > LLM_ANSWER_MAX_MS]
    if fast:
        checks.append(
            check(
                "fast_latency",
                "Quick answers within 4 s",
                not slow_fast,
                f"{max(fast) / 1000:.1f} s",
                f"<= {FAST_ANSWER_MAX_MS // 1000} s",
                True,
            )
        )
    if llm:
        checks.append(
            check(
                "llm_latency",
                "Engineer answers within 20 s",
                not slow_llm,
                f"{max(llm) / 1000:.1f} s",
                f"<= {LLM_ANSWER_MAX_MS // 1000} s",
                True,
            )
        )
    if slow_fast:
        reasons.append(f"{n_of(len(slow_fast), 'quick answer')} took longer than 4 s (heuristic)")
    if slow_llm:
        longest = max(llm) / 1000
        reasons.append(f"{n_of(len(slow_llm), 'answer')} took longer than 20 s, longest {longest:.1f} s (heuristic)")
    if not ptt:
        return state("no_evidence", ["No push-to-talk questions yet"], [], metrics, now)
    if attempts >= PTT_FAIL_ATTEMPTS and not trips:
        return state("fail", [f"{attempts} attempts, none heard and answered", *reasons], checks, metrics, now)
    ok = (
        len(ipad_trips) >= PTT_MIN_ROUNDTRIPS
        and ipad_tailscale is True
        and airpod is True
        and (not attempts or share <= SAY_AGAIN_MAX_SHARE)
    )
    summary = f"{n_of(wheel, 'round trip')} from the wheel button, {screen} from the screen"
    if ok:
        return state("pass", [summary, *reasons], checks, metrics, now)
    missing = [summary]
    if len(ipad_trips) < PTT_MIN_ROUNDTRIPS:
        missing.append(f"{n_of(len(ipad_trips), 'round trip')} on the iPad, {PTT_MIN_ROUNDTRIPS} needed")
    if ipad_tailscale is not True:
        missing.append("No iPad report over Tailscale HTTPS yet")
    if airpod is not True:
        missing.append("AirPod microphone not seen (tick the AirPod box if it was)")
    if attempts and share > SAY_AGAIN_MAX_SHARE:
        missing.append(f"{say_again} of {attempts} questions were not heard")
    return state("inconclusive", missing + reasons, checks, metrics, now)


# ================================================================================================ speak windows (5.4)
def classify_playback(
    on_track: bool, max_brake: float | None, max_abs_steering: float | None, gap_to_brake_s: float | None
) -> str:
    if not on_track:
        return "off_track"
    if max_brake is None or max_abs_steering is None:
        return "unmeasured"
    if max_brake >= OVERLAP_BRAKE or max_abs_steering >= OVERLAP_STEER:
        return "overlap"
    if gap_to_brake_s is not None and gap_to_brake_s < TIGHT_GAP_S:
        return "tight"
    return "clean"


def speak_windows_verdict(proactive: Sequence[ProactiveRecord], now: float) -> AutoState:
    measured = [p for p in proactive if p.cls in ("clean", "tight", "overlap")]
    overlap = [p for p in measured if p.cls == "overlap"]
    tight = sum(1 for p in measured if p.cls == "tight")
    heavy = [p for p in overlap if (p.max_brake or 0.0) >= HEAVY_BRAKE]
    laps = len({(p.session_id, p.start_frame.get("lap") if p.start_frame else p.lap) for p in measured})
    cut = sum(1 for p in proactive if p.cut)
    metrics: dict[str, float | int | str | None] = {
        "messages": len(proactive),
        "measured": len(measured),
        "laps": laps,
        "clean": sum(1 for p in measured if p.cls == "clean"),
        "tight": tight,
        "overlap": len(overlap),
        "off_track": sum(1 for p in proactive if p.cls == "off_track"),
        "unmeasured": sum(1 for p in proactive if p.cls == "unmeasured"),
        "cut": cut,
    }
    checks = [
        check(
            "measured",
            "Messages measured on track",
            len(measured) >= SPEAK_MIN_MEASURED,
            str(len(measured)),
            f">= {SPEAK_MIN_MEASURED}",
            True,
        ),
        check("laps", "Laps with a message", laps >= SPEAK_MIN_LAPS, str(laps), f">= {SPEAK_MIN_LAPS}", True),
        check("overlap", "Messages into braking or cornering", not overlap, str(len(overlap)), "0"),
        check(
            "tight", "Messages ending under 0.5 s before braking", tight <= SPEAK_MAX_TIGHT, str(tight), "<= 1", True
        ),
    ]
    reasons = [f"{n_of(cut, 'message')} cut by a braking call or an urgent call (by design)"] if cut else []
    if not proactive:
        return state("no_evidence", ["No lap summaries or coaching messages yet"], [], metrics, now)
    if len(overlap) >= 2 or heavy:
        worst = max((p.max_brake or 0.0) for p in overlap)
        return state(
            "fail",
            [f"{n_of(len(overlap), 'message')} overlapped braking or cornering (brake up to {worst:.2f})", *reasons],
            checks,
            metrics,
            now,
        )
    if len(measured) >= SPEAK_MIN_MEASURED and laps >= SPEAK_MIN_LAPS and not overlap and tight <= SPEAK_MAX_TIGHT:
        return state(
            "pass",
            [f"{len(measured)} messages over {laps} laps, none into a braking zone", *reasons],
            checks,
            metrics,
            now,
        )
    missing: list[str] = []
    if len(measured) < SPEAK_MIN_MEASURED:
        missing.append(f"{len(measured)} messages measured on track, {SPEAK_MIN_MEASURED} needed")
    if laps < SPEAK_MIN_LAPS:
        missing.append(f"{laps} laps with a message, {SPEAK_MIN_LAPS} needed")
    if overlap:
        missing.append("1 message overlapped braking or cornering")
    if tight > SPEAK_MAX_TIGHT:
        missing.append(f"{tight} messages ended under 0.5 s before braking")
    return state("inconclusive", missing + reasons, checks, metrics, now)


# ================================================================================================ natural voice (5.5)
def kokoro_verdict(
    kokoro_messages: int,
    synth_total: int,
    synth_fallback: int,
    restarts: int | None,
    ipad_server_voice: bool | None,
    synth_p95_ms: float | None,
    now: float,
) -> AutoState:
    share = synth_fallback / synth_total if synth_total else 0.0
    metrics: dict[str, float | int | str | None] = {
        "kokoro_messages": kokoro_messages,
        "synthesised": synth_total,
        "fallback_share": round(share, 3) if synth_total else None,
        "restarts": restarts,
        "synth_p95_ms": synth_p95_ms,
    }
    checks = [
        check(
            "messages",
            "Natural-voice messages heard on an iPad",
            kokoro_messages >= KOKORO_MIN_MESSAGES,
            str(kokoro_messages),
            f">= {KOKORO_MIN_MESSAGES}",
            True,
        ),
        check(
            "fallback",
            "Messages in the fallback voice",
            None if not synth_total else share <= KOKORO_MAX_FALLBACK_SHARE,
            f"{synth_fallback} of {synth_total}",
            "<= 20 %",
            True,
        ),
        check(
            "restarts",
            "Voice worker restarts",
            None if restarts is None else restarts == 0,
            None if restarts is None else str(restarts),
            "0",
        ),
        check("server_voice", "iPad set to the Mac's voice", ipad_server_voice, None, "server"),
    ]
    if not synth_total and not kokoro_messages:
        return state("no_evidence", ["Nothing spoken on the radio yet"], [], metrics, now)
    ok = (
        kokoro_messages >= KOKORO_MIN_MESSAGES
        and share <= KOKORO_MAX_FALLBACK_SHARE
        and restarts == 0
        and ipad_server_voice is True
    )
    if ok:
        return state("pass", [f"{kokoro_messages} messages in the natural voice"], checks, metrics, now)
    missing: list[str] = []
    if kokoro_messages < KOKORO_MIN_MESSAGES:
        missing.append(f"{kokoro_messages} natural-voice messages heard, {KOKORO_MIN_MESSAGES} needed")
    if synth_total and share > KOKORO_MAX_FALLBACK_SHARE:
        missing.append(f"{synth_fallback} of {synth_total} messages in the fallback voice")
    if restarts:
        missing.append(f"The voice worker restarted {n_of(restarts, 'time')}")
    if ipad_server_voice is not True:
        missing.append("No iPad report with the Mac's voice selected")
    return state("inconclusive", missing, checks, metrics, now)


# ================================================================================================ iPad (5.6-5.9)
@dataclass(slots=True)
class ScreenFacts:
    """What the device reports of iPads say about the screen staying on (``evidence.screen_facts``)."""

    n_reports: int = 0
    best_streak_s: float = 0.0  # longest stretch on Drive, visible, wake lock on, telemetry live
    installed_streak_s: float = 0.0  # the same, opened from the Home Screen icon in a secure context
    drive_hidden: int = 0
    drive_gaps: int = 0
    safari_version: str | None = None
    standalone: bool | None = None


def _version_tuple(v: str | None) -> tuple[int, ...] | None:
    if not v:
        return None
    try:
        return tuple(int(p) for p in v.split(".")[:2])
    except ValueError:
        return None


def home_screen_verdict(f: ScreenFacts, did_not_touch: bool | None, now: float) -> AutoState:
    metrics: dict[str, float | int | str | None] = {
        "wake_on_streak_s": round(f.best_streak_s, 1),
        "gaps": f.drive_gaps,
        "hidden_transitions": f.drive_hidden,
        "safari_version": f.safari_version,
    }
    checks = [
        check(
            "standalone",
            "Opened from the Home Screen",
            f.standalone,
            None if f.standalone is None else ("yes" if f.standalone else "no"),
            "yes",
        ),
        check(
            "wake_streak",
            "Screen kept on while driving",
            f.best_streak_s >= WAKE_MIN_S,
            f"{f.best_streak_s:.0f} s",
            f">= {WAKE_MIN_S:.0f} s",
            True,
        ),
        check("hidden", "Page hidden while driving", f.drive_hidden == 0, f"{f.drive_hidden} times", "0"),
        check("gaps", "Reports missing while driving", f.drive_gaps == 0, f"{f.drive_gaps} gaps", "0"),
    ]
    reasons: list[str] = []
    ver = _version_tuple(f.safari_version)
    if f.standalone and ver is not None and ver < WAKE_BUG_SAFARI:
        reasons.append(
            f"Safari {f.safari_version}: the screen can sleep although the wake lock reports on (WebKit bug fixed in "
            "18.4); your verdict decides"
        )
    if not f.n_reports:
        return state("no_evidence", ["No reports from an iPad yet"], [], metrics, now)
    if (f.drive_hidden or f.drive_gaps) and did_not_touch is True:
        return state(
            "fail",
            [
                f"The page went away while driving ({f.drive_hidden} hidden, {f.drive_gaps} gaps) and you did not "
                "touch the iPad",
                *reasons,
            ],
            checks,
            metrics,
            now,
        )
    if f.installed_streak_s >= WAKE_MIN_S:
        mins, secs = divmod(int(f.installed_streak_s), 60)
        return state(
            "pass",
            [
                f"Screen kept on for {mins}:{secs:02d} on Drive with telemetry live ({WAKE_MIN_S / 60:.0f}:00 needed)",
                *reasons,
            ],
            checks,
            metrics,
            now,
        )
    missing = [f"Longest stretch on Drive with the screen on: {f.best_streak_s:.0f} s ({WAKE_MIN_S:.0f} s needed)"]
    if f.best_streak_s >= WAKE_MIN_S > f.installed_streak_s:
        missing.append("Not opened from the Home Screen icon (or not over HTTPS)")
    if f.drive_hidden or f.drive_gaps:
        missing.append("The page went away while driving: tick 'I did not touch the iPad' if you did not")
    return state("inconclusive", missing + reasons, checks, metrics, now)


def glance_verdict(laps_by_driver: Mapping[int | None, int], coach_report: bool, now: float) -> AutoState:
    """Only the driver can judge a glance; both checks are ``review_*``: a "worked" without the laps or without the
    iPad on Drive › Coach in this test needs review, so the test cannot pass without live evidence."""
    best = max(laps_by_driver.values(), default=0)
    checks = [
        check(
            "review_laps",
            "Laps driven in this test (per driver)",
            best >= GLANCE_MIN_LAPS,
            str(best),
            f">= {GLANCE_MIN_LAPS}",
            True,
        ),
        check("review_coach_page", "iPad on Drive › Coach", coach_report, "yes" if coach_report else "no", "yes"),
    ]
    metrics: dict[str, float | int | str | None] = {
        f"laps_driver_{'none' if k is None else k}": v
        for k, v in sorted(laps_by_driver.items(), key=lambda kv: str(kv[0]))
    }
    return state("driver_only", ["Only you can judge what you read at a glance"], checks, metrics, now)


def one_message_verdict(
    spoken: Sequence[tuple[int, str | None, Sequence[str]]], now: float, *, drill_breaches: int = 0
) -> AutoState:
    """``spoken``: (lap_id, observation_id, that lap's picked ids) per coaching message whose playback started.
    ``drill_breaches`` (coachref): coaching messages on drill laps that were not the lap's one drill point."""
    inside = [s for s in spoken if s[1] is not None and s[1] in s[2]]
    outside = [s for s in spoken if s[1] is None or s[1] not in s[2]]
    metrics: dict[str, float | int | str | None] = {
        "spoken": len(spoken),
        "same_as_card": len(inside),
        "different": len(outside),
        "drill_breaches": drill_breaches,
    }
    checks = [
        check(
            "spoken",
            "Coaching points spoken",
            len(spoken) >= ONE_MESSAGE_MIN,
            str(len(spoken)),
            f">= {ONE_MESSAGE_MIN}",
        ),
        check("same", "Spoken point is the card's point", not outside, f"{len(inside)} of {len(spoken)}", "all"),
        check("drill", "Drill laps: only the drill point", drill_breaches == 0, str(drill_breaches), "0"),
    ]
    if not spoken:
        return state("no_evidence", ["No coaching point spoken yet"], [], metrics, now)
    if outside:
        verb = "was" if len(outside) == 1 else "were"
        why = f"{n_of(len(outside), 'spoken point')} {verb} not the coach card's pick"
        return state("fail", [why], checks, metrics, now)
    if drill_breaches:
        why = f"{n_of(drill_breaches, 'coaching message')} on drill laps besides the drill point"
        return state("fail", [why], checks, metrics, now)
    if len(inside) >= ONE_MESSAGE_MIN:
        return state("pass", [f"{len(inside)} spoken points, each the coach card's pick"], checks, metrics, now)
    return state("inconclusive", [f"{len(inside)} spoken points, {ONE_MESSAGE_MIN} needed"], checks, metrics, now)


def endurance_verdict(fps_windows: Sequence[float], reloads: int, now: float) -> AutoState:
    n = len(fps_windows)
    good = sum(1 for x in fps_windows if x >= ENDURANCE_MIN_FPS)
    share = good / n if n else 0.0
    ordered = sorted(fps_windows)
    metrics: dict[str, float | int | str | None] = {
        "windows": n,
        "median_fps": _r(_median(fps_windows)),
        "p5_fps": None if not n else round(ordered[int(0.05 * (n - 1))], 1),
        "smooth_share": round(share, 3) if n else None,
        "reloads": reloads,
        "memory": "-",
    }
    checks = [
        check(
            "windows", "Ten-second windows on Drive", n >= ENDURANCE_MIN_WINDOWS, str(n), f">= {ENDURANCE_MIN_WINDOWS}"
        ),
        check(
            "smooth",
            "Windows at 45 fps or more",
            None if not n else share >= ENDURANCE_MIN_SHARE,
            f"{share * 100:.0f} %",
            ">= 90 %",
            True,
        ),
        check("reloads", "Page reloads", reloads == 0, str(reloads), "0"),
    ]
    if not n:
        return state(
            "no_evidence",
            ["No frame-rate reports yet (Drive must be open while this test is current)"],
            [],
            metrics,
            now,
        )
    if n >= ENDURANCE_MIN_WINDOWS and share >= ENDURANCE_MIN_SHARE and reloads == 0:
        return state(
            "pass",
            [f"{n / 360:.1f} hours on Drive, {share * 100:.0f} % of the time at 45 fps or more"],
            checks,
            metrics,
            now,
        )
    missing: list[str] = []
    if n < ENDURANCE_MIN_WINDOWS:
        missing.append(f"{n * 10 // 60} of 60 minutes measured")
    if share < ENDURANCE_MIN_SHARE:
        missing.append(f"{share * 100:.0f} % of windows at 45 fps or more (90 % needed)")
    if reloads:
        missing.append(f"The page reloaded {n_of(reloads, 'time')}")
    return state("inconclusive", missing, checks, metrics, now)


# ================================================================================================ games (5.10, 5.11)
@dataclass(slots=True)
class GameFacts:
    """Everything the game rules read, aggregated over every session of one game in the run (``evidence``)."""

    game: str
    sessions: int = 0
    driving_sessions: int = 0
    menu_sessions: int = 0  # streaming, not driving (no lap stored)
    streaming_s: float = 0.0
    # best track: the derived / handshake track id with the most timed laps
    track_id: str | None = None
    track_name: str | None = None
    track_length_m: float | None = None
    timed_laps: list[int] = field(default_factory=list)  # lap times (ms) on that track
    clean_laps: int = 0
    observations: int = 0
    corners: int | None = None
    best_lap_ms_game: int | None = None  # SessionInfo.extra best_lap_ms on that track (GT7: unstable raw field)
    variants: list[str] = field(default_factory=list)
    rejected: int | None = None
    errors: int | None = None
    # live inputs (Connect page counters)
    heartbeat_sent: int | None = None
    heartbeat_errors: int | None = None
    lan_sender: bool | None = None
    median_rate_hz: float | None = None
    handshakes: int | None = None
    # AC session extras (latest session)
    handshake_status: int | None = None
    handshake_encoding: str | None = None
    rtcarinfo_size: int | None = None
    track_length_quality: str | None = None
    lap_distance_status: str | None = None
    steer_raw_range: list[float] | None = None
    platform: str | None = None


def _dash(x: float | None) -> str:
    return "-" if x is None else f"{x:.2f}"


def _fmt_lap(ms: int) -> str:
    m, s = divmod(ms / 1000.0, 60)
    return f"{int(m)}:{s:06.3f}"


def _decode_checks(f: GameFacts) -> list[Check]:
    return [
        check(
            "decode",
            "Packets decoded without rejects or errors",
            None if f.rejected is None else (f.rejected == 0 and (f.errors or 0) == 0),
            None if f.rejected is None else f"{f.rejected} rejected, {f.errors or 0} errors",
            "0",
        ),
        check(
            "rate",
            "Packets a second",
            None if f.median_rate_hz is None else f.median_rate_hz >= GAME_MIN_RATE_HZ,
            None if f.median_rate_hz is None else f"{f.median_rate_hz:.1f}",
            f">= {GAME_MIN_RATE_HZ:.0f}",
            True,
        ),
    ]


def _lap_checks(f: GameFacts) -> list[Check]:
    track = f.track_name or f.track_id
    times = ", ".join(_fmt_lap(x) for x in f.timed_laps[:6]) if f.timed_laps else "none"
    return [
        check(
            "timed_laps",
            f"Laps timed on one circuit ({track})" if track else "Laps timed on one circuit",
            len(f.timed_laps) >= GAME_MIN_TIMED_LAPS,
            f"{len(f.timed_laps)}: {times}",
            f">= {GAME_MIN_TIMED_LAPS}",
            True,
        ),
        check(
            "clean_laps",
            "Clean laps",
            f.clean_laps >= GAME_MIN_CLEAN_LAPS,
            str(f.clean_laps),
            f">= {GAME_MIN_CLEAN_LAPS}",
            True,
        ),
        check("coaching", "Coaching point produced", f.observations >= 1, str(f.observations), ">= 1"),
    ]


_TRACK_LENGTH_WORDS = {"full_lap": "measured from a full lap", "estimate": "estimated"}  # adapter words


def ac_verdict(f: GameFacts, times_match: bool | None, phases: Sequence[InputPhaseRecord], now: float) -> AutoState:
    """The handshake's status and encoding stay in the metrics (for the maintainer), not in the check's value."""
    seen = (f.handshakes or 0) >= 1 or f.handshake_status is not None
    answered = True if seen else (None if f.handshakes is None else False)
    checks = [
        check(
            "handshake",
            "Handshake answered",
            answered,
            None if answered is None else ("answered" if answered else "not answered"),
            "answered",
        ),
        *_decode_checks(f),
        *_lap_checks(f),
        check(
            "track_length",
            "Track length",
            None if f.track_length_quality is None else f.track_length_quality == "full_lap",
            None if f.track_length_quality is None else _TRACK_LENGTH_WORDS.get(f.track_length_quality, "unknown"),
            _TRACK_LENGTH_WORDS["full_lap"],
        ),
        check(
            "corners",
            "Corners learned",
            None if f.corners is None else f.corners >= AC_MIN_CORNERS,
            None if f.corners is None else str(f.corners),
            f">= {AC_MIN_CORNERS}",
        ),
        check("times_match", "Lap times match the game's (your tick)", times_match, None, "yes"),
        *input_check_checks(phases, "ac"),
    ]
    metrics: dict[str, float | int | str | None] = {
        "sessions": f.sessions,
        "timed_laps": len(f.timed_laps),
        "clean_laps": f.clean_laps,
        "rejected": f.rejected,
        "handshake_status": f.handshake_status,
        "handshake_encoding": f.handshake_encoding,
        "rtcarinfo_size": f.rtcarinfo_size,
        "track_length_quality": f.track_length_quality,
        "steer_raw_range": None
        if not f.steer_raw_range
        else f"{f.steer_raw_range[0]:.1f} .. {f.steer_raw_range[1]:.1f}",
        "platform": f.platform,
    }
    if not f.sessions:
        return state("no_evidence", ["No Assetto Corsa data in this run yet"], [], metrics, now)
    if (f.rejected or 0) > 0:
        return state("fail", [f"{f.rejected} packets rejected"], checks, metrics, now)
    if f.streaming_s >= AC_FAIL_STREAM_S and f.lap_distance_status == "ok" and not f.timed_laps:
        return state(
            "fail", [f"{f.streaming_s / 60:.0f} minutes on a known line and no lap timed"], checks, metrics, now
        )
    # the optional input check has no verdict of its own (the steer unit is the maintainer's call)
    gating = [c for c in checks if c.id not in INPUT_CHECK_IDS]
    if all(c.status == "met" for c in gating):
        return state("pass", [f"{len(f.timed_laps)} laps timed and coached"], checks, metrics, now)
    # the checks list what is not met: the reasons only count them and say what to do next
    reasons = [] if f.timed_laps else ["No timed lap yet"]
    reasons.append(f"{sum(1 for c in gating if c.status == 'met')} of {len(gating)} checks met")
    if times_match is not True:
        reasons.append("Tick 'lap times match the game's' when you have compared them")
    return state("inconclusive", reasons, checks, metrics, now)


def gt7_verdict(f: GameFacts, times_match: bool | None, phases: Sequence[InputPhaseRecord], now: float) -> AutoState:
    best = min(f.timed_laps) if f.timed_laps else None
    best_ok = None if best is None or f.best_lap_ms_game is None else f.best_lap_ms_game == best
    checks = [
        check(
            "heartbeat",
            "Heartbeat sent to the PS5",
            None if f.heartbeat_sent is None else (f.heartbeat_sent > 0 and (f.heartbeat_errors or 0) == 0),
            None if f.heartbeat_sent is None else f"{f.heartbeat_sent} sent, {f.heartbeat_errors or 0} errors",
            "> 0 sent, 0 errors",
        ),
        check("lan", "Packets from the console on the network", f.lan_sender, None, "yes"),
        check(
            "variant",
            "Packet variant recorded",
            bool(f.variants) or None,
            ", ".join(f.variants) or None,
            "A, B, ~ or C",
        ),
        *_decode_checks(f),
        *_lap_checks(f),
        check(
            "best_lap",
            "Game's best lap equals Pitwall's",
            best_ok,
            None
            if f.best_lap_ms_game is None
            else f"game {_fmt_lap(f.best_lap_ms_game)} vs Pitwall {_fmt_lap(best) if best else '-'}",
            "equal",
        ),
        check("times_match", "Lap times match the game's (your tick)", times_match, None, "yes"),
        check(
            "menus",
            "Streaming, not driving (menus, loading, retries)",
            None,
            f"{f.menu_sessions} of {f.sessions} sessions",
            "not counted",
        ),
        *input_check_checks(phases, "gt7"),
    ]
    metrics: dict[str, float | int | str | None] = {
        "sessions": f.sessions,
        "driving_sessions": f.driving_sessions,
        "menu_sessions": f.menu_sessions,
        "timed_laps": len(f.timed_laps),
        "clean_laps": f.clean_laps,
        "best_lap_ms": best,
        "best_lap_ms_game": f.best_lap_ms_game,
        "track": f.track_name,
        "rejected": f.rejected,
        "variants": ", ".join(f.variants) or None,
    }
    if not f.sessions:
        return state("no_evidence", ["No Gran Turismo 7 data in this run yet"], [], metrics, now)
    if (f.rejected or 0) > 0 or (f.errors or 0) > 0:
        return state(
            "fail", [f"{f.rejected or 0} packets rejected, {f.errors or 0} decode errors"], checks, metrics, now
        )
    reasons: list[str] = []
    if best_ok is False:
        reasons.append(
            "The game's best lap differs from Pitwall's (the raw field is known to be unstable: warning only)"
        )
    if f.menu_sessions:
        menus = n_of(f.menu_sessions, "session")
        reasons.append(f"{menus} streamed from menus or loading screens: not counted as driving")
    gating = [c for c in checks if c.id not in ("best_lap", "menus", *INPUT_CHECK_IDS)]
    if all(c.status == "met" for c in gating):
        where = f.track_name or f.track_id
        laps = f"{len(f.timed_laps)} laps timed" + (f" at {where}" if where else "")
        return state("pass", [laps, *reasons], checks, metrics, now)
    missing = [] if f.timed_laps else ["No timed lap yet"]
    missing.append(f"{sum(1 for c in gating if c.status == 'met')} of {len(gating)} checks met")
    if times_match is not True:
        missing.append("Tick 'lap times match the game's' when you have compared them")
    return state("inconclusive", missing + reasons, checks, metrics, now)


# ================================================================================================ F2 (F1 25 on PS5)
F2_MIN_TIMED_LAPS = 2  # H


@dataclass(slots=True)
class F2Facts:
    """The F1 25 sessions of the run whose formula is F2 (``evidence.f2_facts``)."""

    sessions: int = 0
    timed_laps: list[int] = field(default_factory=list)  # lap times (ms), every F2 session
    duplicates: list[str] = field(default_factory=list)  # "lap 2 (1:56.133)": the same time as the lap before it
    ers_published: bool | None = None  # an ERS value was published while the formula was F2; None = no frame seen
    tracks: list[str] = field(default_factory=list)


def f2_verdict(f: F2Facts, drive_f2_no_ers: bool | None, setup_f2: bool | None, now: float) -> AutoState:
    times = ", ".join(_fmt_lap(x) for x in f.timed_laps[:6]) if f.timed_laps else "none"
    checks = [
        check("f2_session", "An F1 25 session with formula F2", f.sessions > 0, str(f.sessions), ">= 1"),
        check(
            "timed_laps",
            "Laps timed in an F2 car",
            len(f.timed_laps) >= F2_MIN_TIMED_LAPS,
            f"{len(f.timed_laps)}: {times}",
            f">= {F2_MIN_TIMED_LAPS}",
            True,
        ),
        check(
            "no_duplicate",
            "No lap stored twice with the same time",
            not f.duplicates,
            ", ".join(f.duplicates) or "none",
            "none",
        ),
        check(
            "no_ers",
            "No ERS value published while the formula is F2",
            None if f.ers_published is None else not f.ers_published,
            None if f.ers_published is None else ("published" if f.ers_published else "none"),
            "none",
        ),
        check("drive_f2_no_ers", "Drive showed F2 and no ERS (your tick)", drive_f2_no_ers, None, "yes"),
        check("setup_f2", "Car setup showed F2 setups or said there are none (your tick)", setup_f2, None, "yes"),
    ]
    metrics: dict[str, float | int | str | None] = {
        "sessions": f.sessions,
        "timed_laps": len(f.timed_laps),
        "duplicates": len(f.duplicates),
        "tracks": ", ".join(f.tracks) or None,
    }
    if not f.sessions:
        return state("no_evidence", ["No F2 session (F1 25, formula F2) in this run yet"], [], metrics, now)
    if f.duplicates:
        return state("fail", [f"A lap was stored twice: {', '.join(f.duplicates)}"], checks, metrics, now)
    if f.ers_published:
        return state("fail", ["An ERS value was published for an F2 car"], checks, metrics, now)
    if all(c.status == "met" for c in checks):
        return state("pass", [f"{len(f.timed_laps)} laps timed in an F2 car, each stored once"], checks, metrics, now)
    missing = [] if f.timed_laps else ["No timed lap in an F2 car yet"]
    missing.append(f"{sum(1 for c in checks if c.status == 'met')} of {len(checks)} checks met")
    if drive_f2_no_ers is not True or setup_f2 is not True:
        missing.append("Tick the two checks when you have looked at Drive and Car setup")
    return state("inconclusive", missing, checks, metrics, now)


def steer_sign(left: InputPhaseRecord, right: InputPhaseRecord) -> tuple[bool | None, str] | None:
    """(sign as expected, value) from the left and right phases, or None without their readings.

    Full lock, not the phase's mean: the right phase starts from full left lock, so its mean can sit near 0. The
    left phase starts from the centre: as expected its minimum is beyond -0.5 and the right phase's maximum beyond
    +0.5; inverted the other way round. Both or neither: unknown."""
    if None in (left.steer_min, left.steer_max, right.steer_min, right.steer_max):
        return None
    assert left.steer_min is not None and left.steer_max is not None
    assert right.steer_min is not None and right.steer_max is not None
    ok = left.steer_min < -STEER_SIGN_MIN and right.steer_max > STEER_SIGN_MIN
    inverted = left.steer_max > STEER_SIGN_MIN and right.steer_min < -STEER_SIGN_MIN
    if inverted and not ok:
        return False, f"left {left.steer_max:+.2f}, right {right.steer_min:+.2f} (steering sign looks inverted)"
    return (True if ok and not inverted else None), f"left {left.steer_min:+.2f}, right {right.steer_max:+.2f}"


def input_check_checks(phases: Sequence[InputPhaseRecord], game: str) -> list[Check]:
    """Evidence from the optional input check (no verdict of its own: the steer unit is the maintainer's call)."""
    by = {p.phase: p for p in phases if p.samples > 0}
    out: list[Check] = []
    left, right = by.get("left"), by.get("right")
    sign = None if left is None or right is None else steer_sign(left, right)
    if sign is not None:
        out.append(
            check("steer_sign", "Steering sign (left negative, right positive)", sign[0], sign[1], "< -0.5 / > +0.5")
        )
    if game == "ac":
        rng = next((p.steer_raw_range for p in (right, left) if p is not None and p.steer_raw_range), None)
        rot = next((p.rotation_deg for p in phases if p.rotation_deg), None)
        if rng is not None:
            out.append(
                check(
                    "steer_raw",
                    "Raw steer at full lock (unit undocumented)",
                    None,
                    f"{rng[0]:.1f} .. {rng[1]:.1f}" + (f" at {rot:.0f}° rotation" if rot else ""),
                    "for the maintainer",
                )
            )
        rev = by.get("reverse")
        if rev is not None:
            out.append(
                check(
                    "reverse",
                    "Reverse gear seen",
                    rev.gear_min == -1 if rev.gear_min is not None else None,
                    None if rev.gear_min is None else str(rev.gear_min),
                    "-1",
                )
            )
    pedals = by.get("pedals")
    if pedals is not None:
        out.append(
            check(
                "pedals",
                "Full throttle and full brake read",
                None
                if pedals.throttle_max is None or pedals.brake_max is None
                else (pedals.throttle_max >= 0.95 and pedals.brake_max >= 0.95),
                f"throttle {_dash(pedals.throttle_max)}, brake {_dash(pedals.brake_max)}",
                ">= 0.95 each",
            )
        )
    return out


# ================================================================================================ game choice, drivers
def game_selection_verdict(transitions: Sequence[GameTransition], now: float) -> AutoState:
    """Cleared means the banner went because the chosen game became the detected one (clearing the choice, or the
    game stopping, also hides the banner: that does not count)."""
    on_then_off = False
    seen_on = False
    for t in transitions:
        if t.mismatch:
            seen_on = True
        elif seen_on and t.detected_id is not None and t.selected_id == t.detected_id:
            on_then_off = True
    metrics: dict[str, float | int | str | None] = {
        "samples": len(transitions),
        "mismatch_seen": int(seen_on),
        "cleared": int(on_then_off),
    }
    checks = [
        check("banner_on", "Wrong-game banner shown", seen_on, "yes" if seen_on else "no", "yes"),
        check("banner_off", "Banner gone after choosing that game", on_then_off, "yes" if on_then_off else "no", "yes"),
    ]
    if not transitions:
        return state("no_evidence", ["No game choice sampled yet (this test must be current)"], [], metrics, now)
    if on_then_off:
        return state("pass", ["The banner came on for the other game and went once you chose it"], checks, metrics, now)
    return state(
        "inconclusive",
        ["Banner seen, not yet cleared" if seen_on else "No mismatch between the chosen and the detected game yet"],
        checks,
        metrics,
        now,
    )


def switch_ok(s: SwitchRecord) -> tuple[bool | None, list[str]]:
    """Checks of one driver switch (spec 5.12). ``None`` = not decided yet (laps still to come)."""
    problems: list[str] = []
    unknown = False
    if s.before_driver_id is not None and s.from_driver_id is not None and s.before_driver_id != s.from_driver_id:
        problems.append(f"session before the switch belongs to driver #{s.before_driver_id}, not #{s.from_driver_id}")
    if s.after_driver_id is None or s.session_after is None:
        unknown = True
    elif s.after_driver_id != s.to_driver_id:
        problems.append(f"session after the switch belongs to driver #{s.after_driver_id}, not #{s.to_driver_id}")
    if s.laps_before_after_switch:
        problems.append(f"{n_of(s.laps_before_after_switch, 'lap')} after the switch stored under the previous driver")
    if not s.laps_after:
        unknown = True
    if s.cue_reason_after not in DRIVER_RESET_REASONS:
        if s.cue_plan_owner is not None and s.cue_plan_owner == s.from_driver_id and s.from_driver_id != s.to_driver_id:
            problems.append("the previous driver's braking calls stayed armed")
        elif s.cue_plan_owner is None:
            unknown = True
    if problems:
        return False, problems
    return (None if unknown else True), []


def switch_verdict(switches: Sequence[SwitchRecord], now: float) -> AutoState:
    results = [(s, *switch_ok(s)) for s in switches]
    good = [s for s, ok, _ in results if ok is True]
    bad = [(s, p) for s, ok, p in results if ok is False]
    metrics: dict[str, float | int | str | None] = {"switches": len(switches), "ok": len(good), "problems": len(bad)}
    checks = [
        check("switches", "Switches with laps on both sides", bool(good), str(len(good)), ">= 1"),
        check("attribution", "Laps under the right driver", not bad, str(len(bad)), "0 problems"),
    ]
    if not switches:
        return state("no_evidence", ["No driver switch in this test yet"], [], metrics, now)
    if bad:
        return state("fail", [p for _, ps in bad for p in ps][:4], checks, metrics, now)
    if good:
        why = f"{n_of(len(good), 'switch', 'switches')}: each driver's laps under their own name"
        return state("pass", [why], checks, metrics, now)
    return state("inconclusive", ["Waiting for laps on both sides of the switch"], checks, metrics, now)


# ================================================================================================ result (5.13)
def item_result(auto: AutoState, marks: Sequence[DriverMark], per_driver: bool, skipped: bool) -> ItemResult:
    """The one table that combines the automatic verdict with the driver's (spec 5.13).

    Not in the spec's table: with no driver verdict a ``driver_only`` item is ``not_run`` (nothing to review), and so
    is a ``not_live`` one (replays never count, so there is nothing to check either)."""
    if skipped:
        return "skipped"
    verdicts = [m.verdict for m in marks]
    if per_driver:
        driver = None if not verdicts else ("didnt" if "didnt" in verdicts else "worked")
    else:
        driver = verdicts[-1] if verdicts else None
    a = auto.verdict
    if driver is None:
        if a in ("no_evidence", "unavailable", "driver_only", "not_live"):
            return "not_run"
        if a == "fail":
            return "fail"
        return "needs_review"
    if driver == "didnt" or a == "fail":
        return "fail"
    if a in ("pass", "driver_only"):
        return "needs_review" if forces_review(auto) else "pass"
    return "needs_review"
