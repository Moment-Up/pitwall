"""Handling balance per corner phase from tyre slip at the limit (F1 MotionEx only; other games stay unknown).

Per lap and corner, the window [slowest point - 200 m, + 200 m] (clipped to the corner's segment) is split into
entry, mid-corner (the slowest point +/- max(10 m, half a second of travel)) and exit. Only *at-limit* samples count
(lateral g at least 60 % of the corner's 95th percentile, above 40 km/h). The balance measure is the median of
(front slip angle - rear slip angle) in degrees: clearly positive means the fronts are working harder (the car
pushes wide: understeer), negative means the rears are (oversteer). A slide (body slip of 5 degrees or more *towards
oversteer* for 0.1 s, or a counter-steer run) is oversteer whatever the slip angles say. Body slip counts only in
the tail-out direction: the kinematic body slip of a slow, tight turn has the opposite sign and is not a slide.

These thresholds are heuristics (``thresholds``): real F1 25 corners that felt neutral read +0.4 to +2.9 degrees.
A session symptom needs to *recur* (2+ laps and half the laps with data) and its verdict separates the car from the
driving: a symptom that also shows on the session's best lap is the car's; one the best lap did not have points at
how the corner was driven (entry speed or line). Only the car's symptoms get setup suggestions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from pitwall.technique import thresholds as T
from pitwall.technique.samples import Native, deg1, runs

Phase = Literal["entry", "mid", "exit"]
BalanceClass = Literal["understeer", "neutral", "oversteer"]
SpeedClass = Literal["slow", "medium", "fast"]
Verdict = Literal["car", "driving"]
PHASES: tuple[Phase, ...] = ("entry", "mid", "exit")
PROBLEMS: tuple[Literal["understeer", "oversteer"], ...] = ("understeer", "oversteer")
PHASE_WORDS: dict[str, str] = {"entry": "Entry", "mid": "Mid-corner", "exit": "Exit"}
PHASE_SIMPLE: dict[str, str] = {"entry": "on entry", "mid": "mid-corner", "exit": "on the exit"}


@dataclass(slots=True)
class PhaseBalance:
    cls: BalanceClass | None
    slip_diff_deg: float | None
    body_slip_max_deg: float | None
    slide: bool
    samples: int
    brake_share: float | None = None  # share of the phase's samples with brake >= 0.2 (entry: "with braking")
    slide_deg: float | None = None  # largest body slip towards oversteer (tail out) in the phase, degrees

    def to_dict(self) -> dict[str, Any]:
        return {
            "cls": self.cls,
            "slip_diff_deg": deg1(self.slip_diff_deg),
            "body_slip_max_deg": deg1(self.body_slip_max_deg),
            "slide": self.slide,
            "samples": self.samples,
        }


def speed_class(min_speed_kph: float | None) -> SpeedClass | None:
    if min_speed_kph is None or not np.isfinite(min_speed_kph):
        return None
    if min_speed_kph < T.SPEED_SLOW_KPH:
        return "slow"
    return "fast" if min_speed_kph >= T.SPEED_FAST_KPH else "medium"


def _long_runs(mask: np.ndarray, dt: np.ndarray, min_s: float) -> bool:
    return any(float(np.sum(dt[a : b + 1])) >= min_s for a, b in runs(mask))


def lap_balance(
    nat: Native, apex_m: float, seg_start_m: float, seg_end_m: float
) -> dict[Phase, PhaseBalance | None] | None:
    """Balance of one corner on one lap; None when the lap has no slip-angle data (old lap, or not F1)."""
    front = nat.get("slip_angle_front_abs_rad")
    rear = nat.get("slip_angle_rear_abs_rad")
    glat = nat.get("g_lat")
    if front is None or rear is None or glat is None or nat.n < 3 or not np.isfinite(apex_m):
        return None
    d, v = nat.d, nat.speed
    lo, hi = max(seg_start_m, apex_m - T.PHASE_SPAN_M), min(seg_end_m, apex_m + T.PHASE_SPAN_M)
    win = (d >= lo) & (d <= hi)
    if not win.any():
        return {p: None for p in PHASES}
    v_apex = float(np.interp(apex_m, d, np.nan_to_num(v, nan=0.0))) / 3.6
    mid_half = max(T.MID_HALF_MIN_M, T.MID_HALF_S * v_apex)
    g = np.abs(glat)
    gw = g[win & np.isfinite(g)]
    p95 = float(np.percentile(gw, 95)) if len(gw) else float("nan")
    with np.errstate(invalid="ignore"):
        fast = np.nan_to_num(v, nan=0.0) >= T.AT_LIMIT_MIN_KPH
        at_limit = win & (g >= T.AT_LIMIT_FRAC * p95) & fast
        diff = np.degrees(front - rear)
        beta_raw = np.degrees(nat.channels.get("body_slip_rad", np.full(nat.n, np.nan)))
        beta = np.abs(beta_raw)
        yaw = nat.channels.get("yaw_rate_rps", np.full(nat.n, np.nan))
        # Body slip towards oversteer: F1 25 reports chassisYaw with the same sign as yaw_rate_rps when the tail is
        # out (recorded Austria slides at 154-205 km/h, rear slip angle above the front) and the opposite sign for
        # the kinematic slip of a slow, tight turn (recorded Monza Rettifilo at 29 km/h on full lock: 8.1 deg, rear
        # slip angle 0.5 deg). Without rotation to compare with, the magnitude counts.
        turning = np.where(np.abs(yaw) >= T.SLIDE_YAW_MIN_RPS, np.sign(yaw), np.sign(beta_raw))
        beta_os = beta_raw * turning
        counter = (
            (np.abs(nat.steer) >= T.COUNTERSTEER_STEER)
            & (np.abs(yaw) >= T.COUNTERSTEER_YAW_RPS)
            & (np.sign(nat.steer) != np.sign(yaw))
        )
    dt = nat.dt()
    phase_mask: dict[Phase, np.ndarray] = {
        "entry": win & (d < apex_m - mid_half),
        "mid": win & (np.abs(d - apex_m) <= mid_half),
        "exit": win & (d > apex_m + mid_half),
    }
    out: dict[Phase, PhaseBalance | None] = {}
    for p, pm in phase_mask.items():
        if not pm.any():
            out[p] = None
            continue
        m = pm & at_limit & np.isfinite(diff)
        samples = int(m.sum())
        slip_diff = float(np.median(diff[m])) if samples >= T.MIN_PHASE_SAMPLES else None
        with np.errstate(invalid="ignore"):
            slid = _long_runs(pm & fast & (beta_os >= T.SLIDE_BODY_SLIP_DEG), dt, T.SLIDE_MIN_S)
            countered = _long_runs(pm & fast & counter, dt, T.COUNTERSTEER_MIN_S)
        slide = slid or countered
        bphase = beta[pm]
        bmax = float(np.nanmax(bphase)) if np.isfinite(bphase).any() else None
        os_phase = beta_os[pm & fast]
        slide_deg = float(np.nanmax(os_phase)) if np.isfinite(os_phase).any() else None
        cls: BalanceClass | None
        if slide or (slip_diff is not None and slip_diff <= T.OS_DIFF_DEG):
            cls = "oversteer"
        elif slip_diff is None:
            cls = None
        elif slip_diff >= T.US_DIFF_DEG:
            cls = "understeer"
        else:
            cls = "neutral"
        brake_share = float(np.mean(nat.brake[pm] >= T.WITH_BRAKING_PEDAL)) if p == "entry" else None
        out[p] = PhaseBalance(cls, slip_diff, bmax, slide, samples, brake_share, slide_deg)
    return out


# ---------------------------------------------------------------------------------------------- session summary
@dataclass(slots=True)
class LapPhase:
    """One lap's balance in one corner phase (input of ``summarise``)."""

    lap_id: int
    lap_number: int
    lap_time_ms: int | None
    clean: bool
    pb: PhaseBalance
    wheelspin: bool = False  # the lap had wheelspin events on this corner's exit


@dataclass(slots=True)
class PhaseSummary:
    laps: int
    understeer: int
    neutral: int
    oversteer: int
    median_slip_diff_deg: float | None
    slides: int
    recurring: BalanceClass | None
    best_lap: BalanceClass | None
    verdict: Verdict | None
    best_lap_number: int | None = None
    lap_numbers: dict[str, list[int]] = field(default_factory=dict)  # class -> lap numbers (for texts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "laps": self.laps,
            "understeer": self.understeer,
            "neutral": self.neutral,
            "oversteer": self.oversteer,
            "median_slip_diff_deg": deg1(self.median_slip_diff_deg),
            "slides": self.slides,
            "recurring": self.recurring,
            "best_lap": self.best_lap,
            "verdict": self.verdict,
        }


def summarise(rows: Sequence[LapPhase], session_best: int | None = None) -> PhaseSummary:
    """A corner phase over the session. ``session_best``: the lap id of the session's best clean lap. The verdict is
    about *that* lap: when it has no class here (an incident at this corner, no data at the limit), there is no
    verdict, rather than calling the fastest remaining lap "your best lap". Without it, the fastest clean lap of the
    rows is the best."""
    with_cls = [r for r in rows if r.pb.cls is not None]
    n = len(with_cls)
    counts = {c: sum(1 for r in with_cls if r.pb.cls == c) for c in ("understeer", "neutral", "oversteer")}
    diffs = [r.pb.slip_diff_deg for r in with_cls if r.pb.slip_diff_deg is not None]
    recurring: BalanceClass | None = None
    for c in PROBLEMS:
        k = counts[c]
        if k >= T.RECURRING_MIN_LAPS and k >= T.RECURRING_MIN_FRAC * n and (recurring is None or k > counts[recurring]):
            recurring = c
    if session_best is not None:
        best = next((r for r in with_cls if r.lap_id == session_best), None)
    else:
        clean = [r for r in with_cls if r.clean and r.lap_time_ms]
        best = min(clean, key=lambda r: int(r.lap_time_ms or 0)) if clean else None
    best_cls = best.pb.cls if best is not None else None
    verdict: Verdict | None = None
    if recurring is not None and best_cls is not None:
        verdict = "car" if best_cls == recurring else "driving"
    return PhaseSummary(
        laps=n,
        understeer=counts["understeer"],
        neutral=counts["neutral"],
        oversteer=counts["oversteer"],
        median_slip_diff_deg=float(np.median(diffs)) if diffs else None,
        slides=sum(1 for r in with_cls if r.pb.slide),
        recurring=recurring,
        best_lap=best_cls,
        verdict=verdict,
        best_lap_number=best.lap_number if best is not None else None,
        lap_numbers={c: sorted(r.lap_number for r in with_cls if r.pb.cls == c) for c in counts},
    )


# ---------------------------------------------------------------------------------------------- symptoms
@dataclass(slots=True)
class CornerPhaseInput:
    """What ``build_symptoms`` needs about one corner phase."""

    corner: str
    corner_label: str  # how texts name the corner ("Turn 3 (Remus)" / "T3")
    speed_class: SpeedClass | None
    phase: Phase
    summary: PhaseSummary
    rows: list[LapPhase]


@dataclass(slots=True)
class BalanceSymptom:
    id: str
    phase: Phase
    cls: Literal["understeer", "oversteer"]
    verdict: Verdict
    speed_class: SpeedClass | Literal["mixed"]
    corners: list[str]
    corner_labels: list[str]
    laps: int
    laps_total: int
    median_slip_diff_deg: float
    with_braking: bool
    with_wheelspin: bool
    text: str
    text_simple: str
    # setup qualification helpers (not serialised)
    corner_speed_classes: set[str] = field(default_factory=set)
    per_corner_laps: dict[str, int] = field(default_factory=dict)
    slide_every_lap: bool = False
    body_slip_max_deg: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "phase": self.phase,
            "cls": self.cls,
            "verdict": self.verdict,
            "speed_class": self.speed_class,
            "corners": list(self.corners),
            "corner_labels": list(self.corner_labels),
            "laps": self.laps,
            "laps_total": self.laps_total,
            "median_slip_diff_deg": deg1(self.median_slip_diff_deg),
            "with_braking": self.with_braking,
            "with_wheelspin": self.with_wheelspin,
            "text": self.text,
            "text_simple": self.text_simple,
        }


def _join(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _lap_list(nums: list[int]) -> str:
    return ("lap " if len(nums) == 1 else "laps ") + _join([str(n) for n in nums])


def build_symptoms(items: Sequence[CornerPhaseInput]) -> list[BalanceSymptom]:
    """Group recurring corner-phase classes with a verdict by (phase, class, verdict)."""
    groups: dict[tuple[Phase, Literal["understeer", "oversteer"], Verdict], list[CornerPhaseInput]] = {}
    for it in items:
        s = it.summary
        rec = s.recurring
        if (rec == "understeer" or rec == "oversteer") and s.verdict is not None:
            groups.setdefault((it.phase, rec, s.verdict), []).append(it)
    out: list[BalanceSymptom] = []
    for (phase, cls, verdict), its in groups.items():
        hit_rows = [r for it in its for r in it.rows if r.pb.cls == cls]
        all_rows = [r for it in its for r in it.rows if r.pb.cls is not None]
        laps = len({r.lap_id for r in hit_rows})
        laps_total = len({r.lap_id for r in all_rows})
        diffs = [r.pb.slip_diff_deg for r in hit_rows if r.pb.slip_diff_deg is not None]
        median = float(np.median(diffs)) if diffs else 0.0
        classes = {it.speed_class for it in its if it.speed_class is not None}
        sc: SpeedClass | Literal["mixed"] = "mixed"
        if len(classes) == 1:
            sc = next(iter(classes))
        shares = [r.pb.brake_share for r in hit_rows if r.pb.brake_share is not None]
        with_braking = phase == "entry" and bool(shares) and float(np.mean(shares)) >= T.WITH_BRAKING_FRAC
        with_spin = phase == "exit" and cls == "oversteer" and any(r.wheelspin for r in hit_rows)
        bmax = [r.pb.slide_deg for r in hit_rows if r.pb.slide and r.pb.slide_deg is not None]
        labels = [it.corner_label for it in its]
        sym = BalanceSymptom(
            id=f"{phase}-{cls}-{verdict}",
            phase=phase,
            cls=cls,
            verdict=verdict,
            speed_class=sc,
            corners=[it.corner for it in its],
            corner_labels=labels,
            laps=laps,
            laps_total=laps_total,
            median_slip_diff_deg=median,
            with_braking=with_braking,
            with_wheelspin=with_spin,
            text="",
            text_simple="",
            corner_speed_classes={str(c) for c in classes},
            per_corner_laps={
                it.corner: (it.summary.understeer if cls == "understeer" else it.summary.oversteer) for it in its
            },
            slide_every_lap=bool(all_rows) and all(r.pb.slide for r in all_rows),
            body_slip_max_deg=max(bmax) if bmax else None,
        )
        sym.text, sym.text_simple = _symptom_texts(sym, its)
        out.append(sym)
    # car symptoms first, then by how many laps they cover
    out.sort(key=lambda s: (s.verdict != "car", -s.laps, -abs(s.median_slip_diff_deg)))
    return out


def _symptom_texts(s: BalanceSymptom, its: Sequence[CornerPhaseInput]) -> tuple[str, str]:
    where = _join(s.corner_labels)
    speed = "mixed speeds" if s.speed_class == "mixed" else f"{s.speed_class} speed"
    head = f"{PHASE_WORDS[s.phase]} {s.cls} at {where} ({speed})"
    if s.cls == "understeer":
        measure = (
            f"at the limit the front tyres ran {s.median_slip_diff_deg:.1f}° more slip angle than the rears "
            f"(heuristic threshold {T.US_DIFF_DEG:.0f}°)"
        )
        simple_what = "pushed wide (understeer)"
    else:
        if s.body_slip_max_deg is not None and s.body_slip_max_deg >= T.SLIDE_BODY_SLIP_DEG:
            measure = (
                f"the rear stepped out, the car pointing up to {s.body_slip_max_deg:.1f}° away from where it was "
                f"going (heuristic threshold {T.SLIDE_BODY_SLIP_DEG:.0f}°)"
            )
        else:
            measure = (
                f"at the limit the rear tyres ran {abs(s.median_slip_diff_deg):.1f}° more slip angle than the "
                f"fronts (heuristic threshold {abs(T.OS_DIFF_DEG):.0f}°)"
            )
        simple_what = "stepped out at the rear (oversteer)"
        if s.with_wheelspin:
            measure += ", with wheelspin"
    if s.verdict == "car":
        text = f"{head} on {s.laps} of {s.laps_total} laps, including your best lap this session: {measure}."
        simple = (
            f"At {where} the car {simple_what} {PHASE_SIMPLE[s.phase]} on {s.laps} of {s.laps_total} laps, even "
            "on your best lap."
        )
        return text, simple
    hit = sorted({r.lap_number for it in its for r in it.rows if r.pb.cls == s.cls})
    best = next((it.summary.best_lap_number for it in its if it.summary.best_lap_number is not None), None)
    best_txt = f" (lap {best})" if best is not None else ""
    text = (
        f"{head} on {_lap_list(hit)} but not on your best lap{best_txt}: that points at how the corner was driven "
        f"(entry speed or line) more than the car; {measure}."
    )
    simple = (
        f"At {where} the car {simple_what} {PHASE_SIMPLE[s.phase]} on some laps but not on your best lap, so it "
        "is more about how the corner was driven than the car."
    )
    return text, simple
