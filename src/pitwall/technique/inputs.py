"""Brake and throttle technique per corner, on a lap's native samples, and descriptive notes against the reference.

Per corner (``corner_inputs``): how the brake was applied (peak, time to peak, time held at the peak), how it was
released (time, and the shape: in one go, steadily, dropped then trailed, or held then dropped late), brake still
on at turn-in and at the slowest point, time braking while turning (trail braking), coasting off both pedals,
throttle pick-up relative to the slowest point, the ramp to full throttle and lifts on the way, lock-ups and
wheelspin (tyre slip ratio, F1 MotionEx only).

Notes (``compare_inputs``) describe a difference to the reference lap in words. They never tell the driver to brake
later (or earlier): coaching on the braking point lives in ``analysis.coaching`` with its own rules. A note is made
only when both laps have the value; ``notable`` uses the pedal-aware tolerances of ``technique.rig``. With the
game's braking assist on, the brake notes are ``muted`` (the game adds its own braking) and never become facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from pitwall.analysis.braking import BrakingEvent
from pitwall.analysis.laps import FloatArray
from pitwall.technique import thresholds as T
from pitwall.technique.samples import Native, m2, rnd, runs, s2

SlipStatus = Literal["measured", "abs_on", "no_data", "not_applicable"]
ReleaseShape = Literal["step", "steady", "drop_then_trail", "late_drop"]
NoteMetric = Literal[
    "brake_peak",
    "time_to_peak",
    "release",
    "brake_at_turn_in",
    "trail_overlap",
    "coast",
    "throttle_pickup",
    "throttle_ramp",
    "throttle_lifts",
    "lockup",
    "wheelspin",
]
BRAKE_METRICS: frozenset[str] = frozenset(
    {"release", "brake_at_turn_in", "trail_overlap", "brake_peak", "time_to_peak"}
)
WHEEL_NAMES = {"fl": "front left", "fr": "front right", "rl": "rear left", "rr": "rear right"}
SHAPE_WORDS: dict[str, str] = {
    "step": "let off in one go",
    "steady": "eased off steadily",
    "drop_then_trail": "dropped most of it, then trailed the rest",
    "late_drop": "held it, then let go late",
}
TC_WORDS = {0: "off", 1: "medium", 2: "full"}


@dataclass(slots=True)
class SlipEvents:
    status: SlipStatus
    events: int | None = None
    total_s: float | None = None
    peak_slip: float | None = None
    wheels: list[str] = field(default_factory=list)
    at_m: list[float] = field(default_factory=list)
    tc_level: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "events": self.events,
            "total_s": s2(self.total_s),
            "peak_slip": rnd(self.peak_slip, 2),
            "wheels": list(self.wheels),
            "at_m": [round(x, 2) for x in self.at_m],
            "tc_level": self.tc_level,
        }


@dataclass(slots=True)
class CornerInputs:
    braked: bool
    brake_start_m: float | None = None
    brake_peak: float | None = None
    time_to_peak_s: float | None = None
    peak_hold_s: float | None = None
    release_s: float | None = None
    release_shape: ReleaseShape | None = None
    brake_at_turn_in: float | None = None
    brake_at_apex: float | None = None
    trail_overlap_s: float | None = None
    coast_s: float | None = None
    coast_m: float | None = None
    pickup_m: float | None = None
    pickup_vs_apex_m: float | None = None
    full_throttle_m: float | None = None
    throttle_ramp_s: float | None = None
    throttle_lifts: int | None = None
    lockup: SlipEvents = field(default_factory=lambda: SlipEvents("no_data"))
    wheelspin: SlipEvents = field(default_factory=lambda: SlipEvents("no_data"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "braked": self.braked,
            "brake_start_m": m2(self.brake_start_m),
            "brake_peak": rnd(self.brake_peak, 2),
            "time_to_peak_s": s2(self.time_to_peak_s),
            "peak_hold_s": s2(self.peak_hold_s),
            "release_s": s2(self.release_s),
            "release_shape": self.release_shape,
            "brake_at_turn_in": rnd(self.brake_at_turn_in, 2),
            "brake_at_apex": rnd(self.brake_at_apex, 2),
            "trail_overlap_s": s2(self.trail_overlap_s),
            "coast_s": s2(self.coast_s),
            "coast_m": m2(self.coast_m),
            "pickup_m": m2(self.pickup_m),
            "pickup_vs_apex_m": m2(self.pickup_vs_apex_m),
            "full_throttle_m": m2(self.full_throttle_m),
            "throttle_ramp_s": s2(self.throttle_ramp_s),
            "throttle_lifts": self.throttle_lifts,
            "lockup": self.lockup.to_dict(),
            "wheelspin": self.wheelspin.to_dict(),
        }


@dataclass(slots=True)
class TechniqueNote:
    metric: NoteMetric
    lap_value: float | None
    ref_value: float | None
    delta: float | None
    unit: str
    notable: bool
    muted: bool
    text: str
    text_simple: str
    laps: int | None = None
    laps_total: int | None = None
    score: float = 0.0  # |delta| relative to its notable threshold (ranking only, not serialised)

    def to_dict(self) -> dict[str, Any]:
        nd = 2
        return {
            "metric": self.metric,
            "lap_value": rnd(self.lap_value, nd),
            "ref_value": rnd(self.ref_value, nd),
            "delta": rnd(self.delta, nd),
            "unit": self.unit,
            "notable": self.notable,
            "muted": self.muted,
            "laps": self.laps,
            "laps_total": self.laps_total,
            "text": self.text,
            "text_simple": self.text_simple,
        }


@dataclass(frozen=True, slots=True)
class Tolerances:
    peak_tol: float
    time_tol_s: float


# ---------------------------------------------------------------------------------------------- measurement
def _cross(x: FloatArray, y: FloatArray, i: int, thr: float) -> float:
    """``x`` where ``y`` crosses ``thr`` between samples i-1 and i (``x[i]`` at the first sample)."""
    if i <= 0:
        return float(x[0])
    a, b = y[i - 1], y[i]
    if b == a:
        return float(x[i])
    w = float(np.clip((thr - a) / (b - a), 0.0, 1.0))
    return float(x[i - 1] + w * (x[i] - x[i - 1]))


def _steer_peak(nat: Native, apex_m: float) -> float:
    w = np.abs(nat.d - apex_m) <= T.STEER_PEAK_WINDOW_M
    vals = np.abs(nat.steer[w])
    return float(np.percentile(vals, 95)) if len(vals) >= 5 else 0.0


def _slip_channels(nat: Native) -> dict[str, FloatArray] | None:
    out = {}
    for w in ("fl", "fr", "rl", "rr"):
        arr = nat.get(f"wheel_slip_{w}")
        if arr is None:
            return None
        out[w] = arr
    return out


def _lockups(nat: Native, slip: dict[str, FloatArray] | None, abs_on: bool | None, i0: int, i1: int) -> SlipEvents:
    if abs_on:
        return SlipEvents("abs_on")
    if slip is None:
        return SlipEvents("no_data")
    sl = slice(i0, i1 + 1)
    dt = nat.dt()
    with np.errstate(invalid="ignore"):
        locked = {w: slip[w][sl] <= T.LOCKUP_SLIP for w in slip}
        any_locked = (locked["fl"] | locked["fr"] | locked["rl"] | locked["rr"]) & (nat.brake[sl] >= T.TRAIL_BRAKE_MIN)
    events = 0
    total = 0.0
    peak: float | None = None
    wheels: set[str] = set()
    at: list[float] = []
    for a, b in runs(any_locked):
        dur = float(np.sum(dt[i0 + a : i0 + b + 1]))
        if dur < T.LOCKUP_MIN_S:
            continue
        events += 1
        total += dur
        at.append(float(nat.d[i0 + a]))
        for w in slip:
            seg = slip[w][i0 + a : i0 + b + 1]
            if np.any(locked[w][a : b + 1]):
                wheels.add(w)
                mn = float(np.nanmin(seg))
                peak = mn if peak is None else min(peak, mn)
    return SlipEvents("measured", events, total, peak, [w for w in ("fl", "fr", "rl", "rr") if w in wheels], at)


def _wheelspin(nat: Native, slip: dict[str, FloatArray] | None, tc: int | None, j0: int, j1: int) -> SlipEvents:
    if slip is None:
        return SlipEvents("no_data", tc_level=tc)
    if j1 < j0:
        return SlipEvents("measured", 0, 0.0, None, [], [], tc)
    sl = slice(j0, j1 + 1)
    dt = nat.dt()
    with np.errstate(invalid="ignore"):
        spin = {w: slip[w][sl] >= T.SPIN_SLIP for w in ("rl", "rr")}
        any_spin = (spin["rl"] | spin["rr"]) & (nat.throttle[sl] >= T.SPIN_THROTTLE)
    events = 0
    total = 0.0
    peak: float | None = None
    wheels: set[str] = set()
    at: list[float] = []
    for a, b in runs(any_spin):
        dur = float(np.sum(dt[j0 + a : j0 + b + 1]))
        if dur < T.SPIN_MIN_S:
            continue
        events += 1
        total += dur
        at.append(float(nat.d[j0 + a]))
        for w in ("rl", "rr"):
            if np.any(spin[w][a : b + 1]):
                wheels.add(w)
                mx = float(np.nanmax(slip[w][j0 + a : j0 + b + 1]))
                peak = mx if peak is None else max(peak, mx)
    return SlipEvents("measured", events, total, peak, [w for w in ("rl", "rr") if w in wheels], at, tc)


def corner_inputs(
    nat: Native,
    event: BrakingEvent | None,
    apex_m: float,
    turn_in_m: float | None,
    track_out_m: float | None,
    next_brake_m: float | None,
    *,
    abs_on: bool | None = None,
    tc_level: int | None = None,
) -> CornerInputs:
    """Inputs of one corner. ``apex_m`` is this lap's slowest point; ``next_brake_m`` the next braking onset after
    it (caps the throttle and wheelspin windows)."""
    n = nat.n
    if n < 3 or not np.isfinite(apex_m):
        return CornerInputs(braked=event is not None)
    d, t, br, th = nat.d, nat.t, nat.brake, nat.throttle
    dt = nat.dt()
    ia = nat.index_at(apex_m)
    i_next = nat.index_at(next_brake_m) if next_brake_m is not None and next_brake_m > apex_m else n - 1
    slip = _slip_channels(nat)
    out = CornerInputs(braked=event is not None)
    steer_peak = _steer_peak(nat, apex_m)

    # ------------------------------------------------------------------ brake
    i1 = ia
    if event is not None:
        i0 = int(np.searchsorted(d, event.start_m))
        i1 = max(i0, min(n - 1, int(np.searchsorted(d, event.end_m))))
        seg = br[i0 : i1 + 1]
        peak = float(seg.max()) if len(seg) else 0.0
        out.brake_start_m = event.start_m
        if peak > 0:
            hi_idx = np.flatnonzero(seg >= T.PEAK_FRAC * peak)
            i_pk = i0 + int(hi_idx[0])
            last_hi = i0 + int(hi_idx[-1])
            out.brake_peak = peak
            out.time_to_peak_s = float(t[i_pk] - t[i0])
            out.peak_hold_s = float(np.sum(dt[i0 : i1 + 1][seg >= T.PEAK_FRAC * peak]))
            after = np.flatnonzero(br[last_hi:] < T.RELEASE_END_FRAC * peak)
            end = last_hi + int(after[0]) if len(after) else n - 1
            end = max(last_hi, min(end, ia)) if ia > last_hi else last_hi
            out.release_s = float(t[end] - t[last_hi])
            rel = br[last_hi : end + 1]
            if out.release_s < T.STEP_RELEASE_S or len(rel) < 2:
                out.release_shape = "step"
            else:
                area = float(np.mean(rel) / (T.PEAK_FRAC * peak))
                out.release_shape = (
                    "drop_then_trail"
                    if area < T.SHAPE_DROP_TRAIL_MAX
                    else "late_drop"
                    if area > T.SHAPE_LATE_DROP_MIN
                    else "steady"
                )
        if i0 <= ia:
            sl = slice(i0, ia + 1)
            trail = (br[sl] >= T.TRAIL_BRAKE_MIN) & (np.abs(nat.steer[sl]) >= T.TRAIL_STEER_FRAC * steer_peak)
            out.trail_overlap_s = float(np.sum(dt[sl][trail])) if steer_peak > 0 else 0.0
        else:
            out.trail_overlap_s = 0.0
        out.brake_at_apex = float(np.interp(apex_m, d, br))
        if turn_in_m is not None:
            out.brake_at_turn_in = float(np.interp(turn_in_m, d, br))
        out.lockup = _lockups(nat, slip, abs_on, i0, i1)
    else:
        out.lockup = SlipEvents("not_applicable")

    # ------------------------------------------------------------------ throttle
    hit = np.flatnonzero(th[ia : i_next + 1] >= T.THROTTLE_PICKUP)
    pickup_i: int | None = ia + int(hit[0]) if len(hit) else None
    if pickup_i is not None:
        out.pickup_m = _cross(d, th, pickup_i, T.THROTTLE_PICKUP) if pickup_i > ia else float(d[pickup_i])
        out.pickup_vs_apex_m = out.pickup_m - apex_m
        t_pick = _cross(t, th, pickup_i, T.THROTTLE_PICKUP) if pickup_i > ia else float(t[pickup_i])
        cap_t = t_pick + T.RAMP_MAX_S
        window = np.flatnonzero(t[pickup_i : i_next + 1] <= cap_t)
        k_end = pickup_i + (int(window[-1]) if len(window) else 0)
        full = np.flatnonzero(th[pickup_i : k_end + 1] >= T.THROTTLE_FULL)
        if len(full):
            k = pickup_i + int(full[0])
            out.full_throttle_m = _cross(d, th, k, T.THROTTLE_FULL) if k > pickup_i else float(d[k])
            t_full = _cross(t, th, k, T.THROTTLE_FULL) if k > pickup_i else float(t[k])
            out.throttle_ramp_s = max(0.0, t_full - t_pick)
            k_end = k
        seg = th[pickup_i : k_end + 1]
        if len(seg):
            drop = (np.maximum.accumulate(seg) - seg) >= T.LIFT_DROP
            out.throttle_lifts = len(runs(drop))
    # coasting: from the end of braking (or the slowest point when there was no braking) to the pick-up
    c0 = i1 if event is not None else ia
    c1 = pickup_i if pickup_i is not None else i_next
    if c1 > c0:
        sl = slice(c0, c1)
        coast = (br[sl] < T.COAST_PEDAL) & (th[sl] < T.COAST_PEDAL)
        out.coast_s = float(np.sum(dt[sl][coast]))
        dd = np.diff(d[c0 : c1 + 1])
        out.coast_m = float(np.sum(dd[coast])) if len(dd) == len(coast) else None
    else:
        out.coast_s, out.coast_m = 0.0, 0.0

    # ------------------------------------------------------------------ wheelspin on the exit
    spin_end_m = (track_out_m if track_out_m is not None else apex_m) + T.SPIN_AFTER_TRACK_OUT_M
    j1 = min(nat.index_at(spin_end_m), i_next)
    out.wheelspin = _wheelspin(nat, slip, tc_level, ia, j1)
    return out


# ---------------------------------------------------------------------------------------------- notes
def _pct(x: float) -> str:
    return f"{x * 100:.0f} %"


def _s(x: float) -> str:
    return f"{x:.2f} s"


def _more_less(delta: float, more: str, less: str) -> str:
    return more if delta > 0 else less


def _note(
    metric: NoteMetric,
    lap_v: float,
    ref_v: float,
    unit: str,
    notable: bool,
    score: float,
    text: str,
    simple: str,
    muted: bool = False,
) -> TechniqueNote:
    return TechniqueNote(
        metric=metric,
        lap_value=lap_v,
        ref_value=ref_v,
        delta=lap_v - ref_v,
        unit=unit,
        notable=notable,
        muted=muted,
        text=text,
        text_simple=simple,
        score=score,
    )


def _wheels_words(ws: list[str]) -> str:
    return ", ".join(WHEEL_NAMES[w] for w in ws) if ws else "a wheel"


def compare_inputs(
    lap: CornerInputs, ref: CornerInputs, tol: Tolerances, resolution_m: float = 1.5, *, muted: bool = False
) -> list[TechniqueNote]:
    """Every metric both laps have, as a note (``notable`` says whether it is called out). Fixed metric order."""
    notes: list[TechniqueNote] = []

    # release
    if lap.release_s is not None and ref.release_s is not None:
        d = lap.release_s - ref.release_s
        thr = max(tol.time_tol_s, T.RELEASE_NOTE_FRAC * ref.release_s)
        shapes = ""
        if lap.release_shape and ref.release_shape and lap.release_shape != ref.release_shape:
            shapes = f" ({SHAPE_WORDS[lap.release_shape]} vs {SHAPE_WORDS[ref.release_shape]})"
        notes.append(
            _note(
                "release",
                lap.release_s,
                ref.release_s,
                "s",
                abs(d) >= thr,
                abs(d) / thr if thr > 0 else 0.0,
                f"Released the brake over {_s(lap.release_s)} vs {_s(ref.release_s)} on your reference{shapes}.",
                "You let off the brake " + _more_less(d, "more slowly", "more quickly") + " than on your reference.",
                muted,
            )
        )
    # brake at turn-in
    if lap.brake_at_turn_in is not None and ref.brake_at_turn_in is not None:
        d = lap.brake_at_turn_in - ref.brake_at_turn_in
        notes.append(
            _note(
                "brake_at_turn_in",
                lap.brake_at_turn_in,
                ref.brake_at_turn_in,
                "fraction",
                abs(d) >= tol.peak_tol,
                abs(d) / tol.peak_tol,
                f"Brake at turn-in {_pct(lap.brake_at_turn_in)} vs {_pct(ref.brake_at_turn_in)} on your reference.",
                "You carried " + _more_less(d, "more", "less") + " brake into the turn than on your reference.",
                muted,
            )
        )
    # trail braking
    if lap.trail_overlap_s is not None and ref.trail_overlap_s is not None:
        d = lap.trail_overlap_s - ref.trail_overlap_s
        notes.append(
            _note(
                "trail_overlap",
                lap.trail_overlap_s,
                ref.trail_overlap_s,
                "s",
                abs(d) >= T.TRAIL_OVERLAP_NOTE_S,
                abs(d) / T.TRAIL_OVERLAP_NOTE_S,
                f"Braked while turning for {_s(lap.trail_overlap_s)} vs {_s(ref.trail_overlap_s)} on your reference.",
                "You trail-braked " + _more_less(d, "for longer", "for less time") + " than on your reference.",
                muted,
            )
        )
    # brake peak
    if lap.brake_peak is not None and ref.brake_peak is not None:
        d = lap.brake_peak - ref.brake_peak
        both_full = lap.brake_peak >= T.FULL_BRAKE and ref.brake_peak >= T.FULL_BRAKE
        notes.append(
            _note(
                "brake_peak",
                lap.brake_peak,
                ref.brake_peak,
                "fraction",
                (not both_full) and abs(d) >= tol.peak_tol,
                0.0 if both_full else abs(d) / tol.peak_tol,
                f"Peak brake {_pct(lap.brake_peak)} vs {_pct(ref.brake_peak)} on your reference.",
                "You pressed the brake " + _more_less(d, "harder", "less hard") + " than on your reference.",
                muted,
            )
        )
    # time to peak
    if lap.time_to_peak_s is not None and ref.time_to_peak_s is not None:
        d = lap.time_to_peak_s - ref.time_to_peak_s
        notes.append(
            _note(
                "time_to_peak",
                lap.time_to_peak_s,
                ref.time_to_peak_s,
                "s",
                abs(d) >= tol.time_tol_s,
                abs(d) / tol.time_tol_s,
                f"Reached peak brake in {_s(lap.time_to_peak_s)} vs {_s(ref.time_to_peak_s)} on your reference.",
                "You built up the brake " + _more_less(d, "more gradually", "more quickly") + " than on your "
                "reference.",
                muted,
            )
        )
    # coasting
    if lap.coast_s is not None and ref.coast_s is not None:
        d = lap.coast_s - ref.coast_s
        notes.append(
            _note(
                "coast",
                lap.coast_s,
                ref.coast_s,
                "s",
                d >= T.COAST_NOTE_S,
                max(0.0, d) / T.COAST_NOTE_S,
                f"Off both pedals (coasting) for {_s(lap.coast_s)} vs {_s(ref.coast_s)} on your reference.",
                "You spent " + _more_less(d, "longer", "less time") + " off both pedals than on your reference.",
            )
        )
    # throttle pick-up relative to the slowest point
    if lap.pickup_vs_apex_m is not None and ref.pickup_vs_apex_m is not None:
        d = lap.pickup_vs_apex_m - ref.pickup_vs_apex_m
        thr = max(T.PICKUP_NOTE_M, 2 * resolution_m)

        def where(x: float) -> str:
            return f"{abs(x):.0f} m {'after' if x >= 0 else 'before'} the slowest point"

        notes.append(
            _note(
                "throttle_pickup",
                lap.pickup_vs_apex_m,
                ref.pickup_vs_apex_m,
                "m",
                abs(d) >= thr,
                abs(d) / thr,
                f"Picked up the throttle {where(lap.pickup_vs_apex_m)} vs {where(ref.pickup_vs_apex_m)} on your "
                "reference.",
                "You got back on the throttle " + _more_less(d, "later", "sooner") + " after the slowest point "
                "than on your reference.",
            )
        )
    # throttle ramp
    if lap.throttle_ramp_s is not None and ref.throttle_ramp_s is not None:
        d = lap.throttle_ramp_s - ref.throttle_ramp_s
        rel = abs(d) / ref.throttle_ramp_s if ref.throttle_ramp_s > 0 else float("inf")
        notes.append(
            _note(
                "throttle_ramp",
                lap.throttle_ramp_s,
                ref.throttle_ramp_s,
                "s",
                abs(d) >= T.RAMP_NOTE_S and rel >= T.RAMP_NOTE_FRAC,
                abs(d) / T.RAMP_NOTE_S,
                f"From throttle pick-up to full throttle in {_s(lap.throttle_ramp_s)} vs "
                f"{_s(ref.throttle_ramp_s)} on your reference.",
                "You took " + _more_less(d, "longer", "less time") + " to reach full throttle than on your reference.",
            )
        )
    # throttle lifts
    if lap.throttle_lifts is not None and ref.throttle_lifts is not None:
        d = lap.throttle_lifts - ref.throttle_lifts
        notes.append(
            _note(
                "throttle_lifts",
                lap.throttle_lifts,
                ref.throttle_lifts,
                "count",
                d >= 1,
                float(max(0, d)),
                f"Lifted {lap.throttle_lifts} time{'s' if lap.throttle_lifts != 1 else ''} on the way to full "
                f"throttle vs {ref.throttle_lifts} on your reference.",
                "You lifted off the throttle on the exit " + _more_less(d, "more", "less") + " than on your reference.",
            )
        )
    # lock-ups (only when both laps were measured: with ABS on the game prevents them)
    lk, rk = lap.lockup, ref.lockup
    if lk.status == "measured" and rk.status == "measured" and lk.events is not None and rk.events is not None:
        detail = f" ({_wheels_words(lk.wheels)}, {_s(lk.total_s or 0.0)})" if lk.events else ""
        notes.append(
            _note(
                "lockup",
                lk.events,
                rk.events,
                "events",
                lk.events > 0,
                float(lk.events),
                f"Locked a wheel {lk.events} time{'s' if lk.events != 1 else ''} under braking{detail} vs "
                f"{rk.events} on your reference.",
                "You locked a wheel under braking." if lk.events else "No lock-ups under braking.",
            )
        )
    # wheelspin
    ls, rs = lap.wheelspin, ref.wheelspin
    if ls.status == "measured" and rs.status == "measured" and ls.total_s is not None and rs.total_s is not None:
        d = ls.total_s - rs.total_s
        tc = f" (traction control {TC_WORDS.get(ls.tc_level, str(ls.tc_level))})" if ls.tc_level else ""
        notes.append(
            _note(
                "wheelspin",
                ls.total_s,
                rs.total_s,
                "s",
                d >= T.WHEELSPIN_NOTE_S,
                max(0.0, d) / T.WHEELSPIN_NOTE_S,
                f"Wheelspin on the exit for {_s(ls.total_s)} vs {_s(rs.total_s)} on your reference{tc}.",
                "The rear wheels spun " + _more_less(d, "more", "less") + " on the exit than on your reference.",
            )
        )
    return notes


def top_notes(notes: list[TechniqueNote], limit: int = T.MAX_NOTES_PER_CORNER) -> list[TechniqueNote]:
    """The notable notes, unmuted first, then by how far they clear their threshold."""
    chosen = [n for n in notes if n.notable]
    chosen.sort(key=lambda n: (n.muted, -n.score))
    return chosen[:limit]


HABIT_TEXT: dict[str, tuple[str, str]] = {
    # metric: (wording when the lap value is higher than the reference, when lower)
    "release": ("released the brake more slowly", "released the brake more quickly"),
    "brake_at_turn_in": ("carried more brake into the turn", "carried less brake into the turn"),
    "trail_overlap": ("trail-braked for longer", "trail-braked for less time"),
    "brake_peak": ("pressed the brake harder", "pressed the brake less hard"),
    "time_to_peak": ("built up the brake more gradually", "built up the brake more quickly"),
    "coast": ("spent longer off both pedals", "spent less time off both pedals"),
    "throttle_pickup": (
        "got back on the throttle later after the slowest point",
        "got back on the throttle sooner after the slowest point",
    ),
    "throttle_ramp": ("took longer to reach full throttle", "reached full throttle more quickly"),
    "throttle_lifts": ("lifted off the throttle on the exit more", "lifted off the throttle less"),
    "lockup": ("locked a wheel under braking more often", "locked a wheel under braking less often"),
    "wheelspin": ("had more wheelspin on the exit", "had less wheelspin on the exit"),
}


def habits(per_lap: list[list[TechniqueNote]]) -> list[TechniqueNote]:
    """Metrics notable with the same sign on at least half the laps that have them (and at least 2 laps)."""
    by_metric: dict[str, list[TechniqueNote]] = {}
    for notes in per_lap:
        for n in notes:
            by_metric.setdefault(n.metric, []).append(n)
    out: list[TechniqueNote] = []
    for metric, ns in by_metric.items():
        total = len(ns)
        for sign in (1, -1):
            hits = [n for n in ns if n.notable and n.delta is not None and n.delta * sign > 0]
            if len(hits) < T.HABIT_MIN_LAPS or len(hits) < T.HABIT_MIN_FRAC * total:
                continue
            lap_v = float(np.median([n.lap_value for n in hits if n.lap_value is not None]))
            ref_v = hits[0].ref_value
            delta = float(np.median([n.delta for n in hits if n.delta is not None]))
            words = HABIT_TEXT[metric][0 if sign > 0 else 1]
            unit = hits[0].unit
            fmt = _fmt_value(lap_v, unit)
            ref_fmt = _fmt_value(ref_v, unit) if ref_v is not None else "unknown"
            out.append(
                TechniqueNote(
                    metric=hits[0].metric,
                    lap_value=lap_v,
                    ref_value=ref_v,
                    delta=delta,
                    unit=unit,
                    notable=True,
                    muted=all(n.muted for n in hits),
                    laps=len(hits),
                    laps_total=total,
                    text=f"On {len(hits)} of {total} laps you {words} than on your reference (median {fmt} vs "
                    f"{ref_fmt}).",
                    text_simple=f"On {len(hits)} of {total} laps you {words} than on your reference.",
                    score=float(len(hits)) / total,
                )
            )
    out.sort(key=lambda n: (n.muted, -(n.laps or 0), -n.score))
    return out


def _fmt_value(v: float, unit: str) -> str:
    if unit == "fraction":
        return _pct(v)
    if unit == "s":
        return _s(v)
    if unit == "m":
        return f"{v:.0f} m"
    return f"{v:.0f}"
