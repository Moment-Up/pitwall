"""Physics brake prior (layer L1c): "heavy stop ahead" windows before the driver has a lap.

Pipeline (``docs/research/track-knowledge-sources.md`` section 2 "L1c", section 5, section 8 phase 4):

1. The Pits n' Giggles outline (``track_geometry``, tier ``shipped_seed``) re-sampled at ~1 m of arc length, curvature
   from the heading derivative, smoothed with a periodic Gaussian of sigma in {5, 10, 15, 20} m.
2. pitwall's own forward/backward quasi-steady-state solver (``sim.driver.solve_lap``) with the default
   ``VehicleModel`` (or a caller-supplied brake envelope, e.g. one fitted from the AI field).
3. Braking zones found by ``analysis.braking.detect_braking`` itself, run on the solved profile, so the prior uses
   exactly the thresholds that find the driver's own braking (BRAKE_ON 0.10, BRAKE_OFF 0.05, 0.15 s, 0.25 s merge).
4. The sigma-ensemble gate: a zone is a *heavy stop* only if, at **every** sigma, the solved speed drop is
   >= 100 km/h **and** the apex radius is < 90 m. Fast corners (R ~ 100-200 m: Pouhon, Copse, Scheivlak) are where
   the probe produced its false zones, because v^2 = mu g R / (1 - aero R) is hypersensitive there.
5. Positions mapped back to game lap distance through the outline's knot table (never arc length).

Design decisions:

* **Heads-up windows, never targets.** Every window carries ``tier = "physics_predicted"`` (the research doc's tier
  name, ``core.track_knowledge.TIER_PHYSICS``), ``positional = False`` and a window margin ``uncertainty_m``; every
  position in the payload is an ``est_*`` field. A window runs from ``est_onset - uncertainty`` to the estimated apex,
  and consumers may use only the non-positional severity tag ("heavy stop next, Turn 1", >= 2 s before the window
  start). Coaching never tells the driver to brake at a predicted point, and never later.
* **Measured onset error (``ONSET_EVIDENCE``).** On pitwall's real PS5 F1 25 races (2026-10-10/11: 19 clean flying
  laps, 10 layouts, 75 stops; Miami and Melbourne were out of sample) the default model, which brakes harder than
  F1 25's cars (5.5 g at 300 km/h against ~4 g), predicts the onset *later* than the driver's first brake
  application at 81 % of stops: median +18 m, p90 |error| 70 m, worst +148 m. The driver's onset is the first
  application of the braking chain (``_chain``'s rule: no re-acceleration between events) that contains the stop's
  speed minimum, never the nearest or lowest minimum: at Monza T1-2 (lap 3, clean) the driver brakes at 718 m from
  337 km/h against a predicted 806 m (+88 m); matching the later 956 m event (93 -> 28 km/h) instead would report a
  spurious -150 m. The window
  margin ``ONSET_UNCERTAINTY_M = 100 m`` covers every observed stop except three where the driver braked for an
  adjacent corner that the solve takes flat and never re-accelerated (Suzuka T1 -> T2 twice, +106/+101 m; Silverstone
  Reverse, +148 m). The research section 5.3 calibrated envelope (23.6 + 0.00228 v^2) gives p90 |error| 62 m, worst
  +141 m. Displays state the error as "p90 70 m", never as a symmetric +/-.
* **Estimates are named as such.** Entry/apex speeds are ``est_*`` fields: the apex minimum moves by tens of km/h
  with sigma (Monza T1: 72 -> 124 km/h for sigma 0 -> 20 m) and is not a target.
* **Identity only from verified sheets.** A window inherits an official label (``"T1"``) only when its apex lies
  inside a *hand-verified* track-sheet turn window (scaled to the lap length, length gate 1.5 %), else None.
* **Unknown stays unknown.** No outline (unsupported game/track, failed length gate) -> ``OutlineError`` from
  ``build_brake_prior``; a non-physical ``BrakeEnvelope`` (non-finite, b0 <= 0, b1 < 0, implausible decel) ->
  ``ValueError`` at construction (``OutlineError`` subclasses ``ValueError``: callers catch ``ValueError``); no zone
  passes the gate -> an empty ``windows`` list (with ``rejected`` saying why).
* **Lap-order stops, chained.** ``detect_braking`` ends an event when the pedal falls below BRAKE_OFF; consecutive
  events with no re-acceleration in between are one stop (``_chain``), so a solve that lifts for a moment does not
  split one heavy stop into two light ones. Across sigmas a stop is matched by apex (60 m) or by an apex inside the
  primary zone's braking phase, judging the biggest part; the primary-sigma zone itself must pass the gate.
* **Off the hot path.** Solving costs ~0.1 s per track (4 sigmas, pure NumPy/Python, holds the GIL): call it from a
  background worker, never the ingest thread. ``build_brake_prior`` is cached per (game, track, lap length to 0.1 m,
  envelope rounded by ``BrakeEnvelope.rounded``); the envelope's ``source`` is part of the key, so a refitting caller
  passes a constant source (e.g. "AI field", not a sample count) and re-solves only when
  ``BrakeEnvelope.differs_from`` says the decel curve moved.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import numpy as np

from pitwall.analysis.braking import BrakingEvent, detect_braking
from pitwall.analysis.laps import LapTrace
from pitwall.analysis.track_geometry import (
    OUTLINE_SOURCE,
    TIER_SHIPPED_SEED,
    ArcTrack,
    OutlineError,
    TrackOutline,
    build_outline,
    direction_of,
    resample_arc,
)
from pitwall.sim.driver import G, VehicleModel, solve_lap

TIER_PHYSICS_PREDICTED = "physics_predicted"  # research section 2 "Representing confidence"; track_knowledge's name
PRIOR_LABEL = "braking estimate (physics)"
SIGMA_ENSEMBLE_M: tuple[float, ...] = (5.0, 10.0, 15.0, 20.0)
PRIMARY_SIGMA_M = 10.0
HEAVY_DROP_KPH = 100.0  # solved entry -> minimum speed drop, at every sigma
MAX_APEX_RADIUS_M = 90.0  # apex radius at every sigma (fast corners are where the false zones come from)
APEX_MATCH_M = 60.0  # the same zone across sigmas: apexes within this lap distance (pitwall's corner spacing)
CHAIN_REACCEL_KPH = 3.0  # events closer than this re-acceleration are one stop (see ``_chain``)
APEX_RADIUS_WINDOW_M = 30.0  # apex radius = 1 / peak |curvature| within this distance of the solved minimum
MIN_LEAD_S = 2.0  # coach rule for the severity tag (research section 2 "Representing confidence")
# Window margin (m): the heads-up band starts this far before the estimated onset (or the sigma spread, if larger).
# It covers every real stop in ONSET_EVIDENCE except three adjacent-corner chains (see the module docstring).
ONSET_UNCERTAINTY_M = 100.0
ONSET_ERROR_P90_M = 70.0  # p90 |estimated onset - driver's first application|, default envelope (ONSET_EVIDENCE)
# Predicted minus driver onset (m) on pitwall's own real PS5 F1 25 races, default envelope; positive = predicted late.
# Reproduce: decode the captures, take clean laps >= 2 with no flags and compare each window's est_onset_m with
# ``driver_onset(detect_braking(lap), window, length).start_m`` (the first application of the driver's stop).
ONSET_EVIDENCE: Mapping[str, Any] = MappingProxyType(
    {
        "captures": "data/captures 2026-10-10/11 (PS5 F1 25 races, F1 Generic car)",
        "layouts": 10,
        "clean_flying_laps": 19,
        "stops": 75,
        "median_m": 18.0,
        "p90_abs_m": ONSET_ERROR_P90_M,
        "worst_late_m": 148.0,
        "worst_early_m": -88.0,
        "predicted_late_share": 0.81,
        "outside_window": 3,  # driver's first application before est_onset - ONSET_UNCERTAINTY_M
        "calibrated_envelope_p90_abs_m": 62.0,  # research section 5.3 envelope, 23.6 + 0.00228 v^2
    }
)
# Plausible full-brake decel (g) of a BrakeEnvelope: F1 25's AI field is ~4.0 g at 300 km/h and ~2.6 g at 100 km/h;
# pitwall's default VehicleModel 5.5 g / 1.9 g. Outside these the fit is noise, not a car.
ENVELOPE_PLAUSIBLE_G: dict[float, tuple[float, float]] = {100.0: (1.0, 7.0), 300.0: (2.0, 7.0)}
ENVELOPE_REFIT_REL = 0.03  # re-solve only when the decel at 100/200/300 km/h moved by more than this
CAVEAT = (
    "Physics estimate from the game outline: a heads-up that a heavy stop is coming, never a braking point. "
    f"Estimated onsets are usually late (p90 error {ONSET_ERROR_P90_M:.0f} m on real laps); brake where your own "
    "laps say."
)
POSITIONAL_REASON = (
    "V5 not passed: onset placement is unvalidated on >= 3 tracks of Time Trial captures (research section 5.4), and "
    f"on real races its p90 error is {ONSET_ERROR_P90_M:.0f} m; only the non-positional severity tag may be voiced"
)

__all__ = [
    "CAVEAT",
    "ENVELOPE_PLAUSIBLE_G",
    "HEAVY_DROP_KPH",
    "MAX_APEX_RADIUS_M",
    "ONSET_ERROR_P90_M",
    "ONSET_EVIDENCE",
    "ONSET_UNCERTAINTY_M",
    "SIGMA_ENSEMBLE_M",
    "TIER_PHYSICS_PREDICTED",
    "BrakeEnvelope",
    "BrakePrior",
    "OutlineError",
    "PriorRefresher",
    "PriorWindow",
    "SolvedZone",
    "brake_prior_from_outline",
    "build_brake_prior",
    "driver_onset",
    "solve_zones",
]


@dataclass(frozen=True, slots=True)
class BrakeEnvelope:
    """Braking decel ``b0 + b1 * v^2`` (m/s^2, v in m/s), e.g. fitted per game from AI full-brake samples.

    Validated at construction (``ValueError``): finite, ``brake_base > 0``, ``brake_aero >= 0`` and a plausible decel
    at 100 and 300 km/h (``ENVELOPE_PLAUSIBLE_G``). ``source`` is part of equality, hash and so the
    ``build_brake_prior`` cache key: pass a constant (e.g. "AI field"), never a changing sample count.
    """

    brake_base: float
    brake_aero: float
    source: str = "caller"

    def __post_init__(self) -> None:
        b0, b1 = self.brake_base, self.brake_aero
        if not (math.isfinite(b0) and math.isfinite(b1)):
            raise ValueError(f"brake envelope must be finite (brake_base={b0!r}, brake_aero={b1!r})")
        if b0 <= 0.0 or b1 < 0.0:
            raise ValueError(f"brake envelope needs brake_base > 0 and brake_aero >= 0 (got {b0!r}, {b1!r})")
        for kph, (lo, hi) in ENVELOPE_PLAUSIBLE_G.items():
            g = self.decel_g(kph)
            if not lo <= g <= hi:
                raise ValueError(f"brake envelope gives {g:.2f} g at {kph:.0f} km/h (plausible {lo:g}-{hi:g} g)")

    def decel_g(self, speed_kph: float) -> float:
        v = speed_kph / 3.6
        return (self.brake_base + self.brake_aero * v * v) / G

    def rounded(self) -> BrakeEnvelope:
        """The cache key's resolution: 0.1 m/s^2 and 1e-5 1/m (0.07 m/s^2 at 300 km/h), below a fit's own noise."""
        return BrakeEnvelope(round(self.brake_base, 1), round(self.brake_aero, 5), self.source)

    def differs_from(self, other: BrakeEnvelope | None, rel: float = ENVELOPE_REFIT_REL) -> bool:
        """True when ``other`` is None or its decel at 100/200/300 km/h differs by more than ``rel``: the point at
        which a caller holding a prior for ``other`` should re-solve."""
        if other is None:
            return True
        return any(abs(self.decel_g(k) / other.decel_g(k) - 1.0) > rel for k in (100.0, 200.0, 300.0))

    def apply(self, vehicle: VehicleModel) -> VehicleModel:
        return dataclasses.replace(vehicle, brake_base=self.brake_base, brake_aero=self.brake_aero)


@dataclass(frozen=True, slots=True)
class SolvedZone:
    """One braking zone of one QSS solve, in the solve's arc length and in game lap distance."""

    sigma_m: float
    onset_s: float
    end_s: float
    apex_s: float
    onset_m: float  # lap distance
    end_m: float
    apex_m: float
    entry_kph: float
    apex_kph: float
    apex_radius_m: float
    apex_curvature: float
    duration_s: float

    @property
    def drop_kph(self) -> float:
        return self.entry_kph - self.apex_kph

    @property
    def heavy(self) -> bool:
        return self.drop_kph >= HEAVY_DROP_KPH and self.apex_radius_m < MAX_APEX_RADIUS_M


def _cyc(a: float, b: float, length: float) -> float:
    """Signed cyclic difference a - b on a loop of ``length`` (in [-L/2, L/2))."""
    return (a - b + length / 2) % length - length / 2


def _same_stop(c: SolvedZone, z: SolvedZone, length: float) -> bool:
    """``c`` (another sigma) is the stop ``z``: apexes within APEX_MATCH_M, or c's apex inside z's braking phase."""
    if abs(_cyc(c.apex_m, z.apex_m, length)) <= APEX_MATCH_M:
        return True
    return 0.0 <= _cyc(c.apex_m, z.onset_m, length) <= (z.apex_m - z.onset_m) % length


def _segments(a: float, b: float, length: float) -> list[tuple[float, float]]:
    """Non-wrapping pieces of the cyclic interval [a, b)."""
    a, b = a % length, b % length
    if a <= b:
        return [(round(a, 1), round(b, 1))]
    return [(round(a, 1), round(length, 1)), (0.0, round(b, 1))]


def _profile_trace(arc: ArcTrack, vehicle: VehicleModel) -> tuple[LapTrace, int, float]:
    """Solve the loop and return it as a LapTrace starting at its fastest sample (so no zone straddles the
    trace's start), with the roll index and the lap time."""
    prof = solve_lap(arc.to_sim_track(), vehicle)
    r = int(np.argmax(prof.v))
    n = len(arc.s)
    ds = arc.step_m
    v = np.roll(prof.v, -r)
    t = np.concatenate([[0.0], np.cumsum(ds / ((v[:-1] + v[1:]) / 2))])
    channels = {
        "distance_m": np.arange(n, dtype=np.float64) * ds,
        "session_time_s": t,
        "lap_time_ms": t * 1000.0,
        "speed_kph": v * 3.6,
        "throttle": np.roll(prof.throttle, -r),
        "brake": np.roll(prof.brake, -r),
        "steering": np.zeros(n),
    }
    return LapTrace(lap_number=0, channels=channels, lap_time_ms=round(prof.lap_time_s * 1000)), r, prof.lap_time_s


def solve_zones(arc: ArcTrack, vehicle: VehicleModel | None = None) -> list[SolvedZone]:
    """All braking zones (``detect_braking`` thresholds) of the QSS lap on ``arc``, in lap order from the line."""
    return _solve(arc, vehicle or VehicleModel())[0]


def _solve(arc: ArcTrack, vehicle: VehicleModel) -> tuple[list[SolvedZone], float]:
    trace, r, lap_time = _profile_trace(arc, vehicle)
    A = arc.arc_length_m
    s0 = float(arc.s[r])
    zones = [_zone(arc, ev, s0, A) for ev in _chain(detect_braking(trace))]
    zones.sort(key=lambda z: z.onset_m)
    return zones, lap_time


def _chain_groups(events: Sequence[BrakingEvent]) -> list[list[BrakingEvent]]:
    """Lap-order braking events grouped into stops: the next event starts before the car has re-accelerated
    (its start speed is at most ``CHAIN_REACCEL_KPH`` above the stop's lowest speed so far)."""
    groups: list[list[BrakingEvent]] = []
    for ev in events:
        if groups and ev.start_speed_kph <= min(e.min_speed_kph for e in groups[-1]) + CHAIN_REACCEL_KPH:
            groups[-1].append(ev)
        else:
            groups.append([ev])
    return groups


def _chain(events: Sequence[BrakingEvent]) -> list[BrakingEvent]:
    """Merge braking events that are one deceleration: the next event starts before the car has re-accelerated.

    ``detect_braking`` ends an event when the pedal drops below BRAKE_OFF; on the solved profile a short lift between
    two braking phases (noise at small sigma, a coasting kink) splits one stop in two, and each half would then fail
    the 100 km/h drop gate on its own.
    """
    out: list[BrakingEvent] = []
    for group in _chain_groups(events):
        first, last = group[0], group[-1]
        lowest = min(reversed(group), key=lambda e: e.min_speed_kph)  # ties: the later minimum
        out.append(
            first
            if len(group) == 1
            else dataclasses.replace(
                first,
                end_m=last.end_m,
                end_speed_kph=last.end_speed_kph,
                min_speed_kph=lowest.min_speed_kph,
                min_speed_m=lowest.min_speed_m,
                peak_brake=max(e.peak_brake for e in group),
                duration_s=sum(e.duration_s for e in group),
            )
        )
    return out


def driver_onset(events: Sequence[BrakingEvent], window: PriorWindow, length: float) -> BrakingEvent | None:
    """The driver's first brake application for ``window``'s stop on a real lap: the rule behind ``ONSET_EVIDENCE``.

    ``events`` are ``detect_braking`` events of one lap, in lap order. They are grouped into stops by ``_chain``'s
    rule; the stop is the group that has an event minimum inside ``[est_onset - 50, est_apex + 100]`` with the biggest
    drop (group entry speed minus the lowest such minimum), and the answer is that group's *first* event. So a chicane
    the driver brakes into from 337 km/h is matched at its first application, never at a later, nearer or slower
    minimum. None when the driver had no braking there.
    """
    span = (window.est_apex_m - window.est_onset_m) % length + 100.0
    best: tuple[float, BrakingEvent] | None = None
    for group in _chain_groups(events):
        inside = [e.min_speed_kph for e in group if -50.0 <= _cyc(e.min_speed_m, window.est_onset_m, length) <= span]
        if inside:
            drop = group[0].start_speed_kph - min(inside)
            if best is None or drop > best[0]:
                best = (drop, group[0])
    return None if best is None else best[1]


def _zone(arc: ArcTrack, ev: BrakingEvent, s0: float, arc_len: float) -> SolvedZone:
    onset_s = (ev.start_m + s0) % arc_len
    end_s = (ev.end_m + s0) % arc_len
    apex_s = (ev.min_speed_m + s0) % arc_len
    ds = arc.step_m
    i = round(apex_s / ds)
    w = max(1, round(APEX_RADIUS_WINDOW_M / ds))
    idx = np.arange(i - w, i + w + 1) % len(arc.s)
    k = arc.curvature[idx]
    j = int(np.argmax(np.abs(k)))
    peak = float(k[j])
    radius = 1.0 / abs(peak) if abs(peak) > 1e-9 else math.inf
    d = arc.lap_distance_at(np.array([onset_s, end_s, apex_s]))
    return SolvedZone(
        sigma_m=arc.sigma_m,
        onset_s=onset_s,
        end_s=end_s,
        apex_s=apex_s,
        onset_m=float(d[0]),
        end_m=float(d[1]),
        apex_m=float(d[2]),
        entry_kph=ev.start_speed_kph,
        apex_kph=ev.min_speed_kph,
        apex_radius_m=radius,
        apex_curvature=peak,
        duration_s=ev.duration_s,
    )


@dataclass(slots=True)
class PriorWindow:
    """A gated heavy stop: where a heads-up applies, with its margin. Never a braking target: every position is an
    estimate (``est_*``) from the QSS solve, not a measurement."""

    index: int  # 1-based, lap order
    est_onset_m: float  # estimated brake onset (primary sigma), game lap distance
    est_apex_m: float  # estimated speed minimum
    est_end_m: float  # estimated brake release
    uncertainty_m: float  # window margin: the heads-up band starts this far before the estimated onset
    onset_spread_m: float  # onset range across the sigma ensemble
    est_entry_kph: float
    est_apex_kph: float
    est_drop_kph: float  # smallest drop across sigmas
    apex_radius_m: float  # largest apex radius across sigmas (closest to the gate)
    est_braking_distance_m: float
    duration_s: float
    direction: str | None
    turn: dict[str, Any] | None  # {"label", "name", "voice_ok"} from a hand-verified sheet turn, else None
    per_sigma: list[dict[str, float]] = field(default_factory=list)

    @property
    def window_start_m(self) -> float:
        return self.est_onset_m - self.uncertainty_m  # may be negative before wrapping; see window_m

    def window_m(self, length: float) -> tuple[float, float]:
        return (round((self.est_onset_m - self.uncertainty_m) % length, 1), round(self.est_apex_m % length, 1))

    def to_dict(self, length: float) -> dict[str, Any]:
        a, b = self.window_m(length)
        return {
            "index": self.index,
            "tier": TIER_PHYSICS_PREDICTED,
            "positional": False,
            "window_m": [a, b],
            "wraps": b < a,
            "segments_m": _segments(a, b, length),
            "uncertainty_m": round(self.uncertainty_m, 1),
            "onset_error_p90_m": ONSET_ERROR_P90_M,
            "onset_spread_m": round(self.onset_spread_m, 1),
            "est_onset_m": round(self.est_onset_m, 1),
            "est_apex_m": round(self.est_apex_m, 1),
            "est_end_m": round(self.est_end_m, 1),
            "est_braking_distance_m": round(self.est_braking_distance_m, 1),
            "est_entry_kph": round(self.est_entry_kph),
            "est_apex_kph": round(self.est_apex_kph),
            "est_drop_kph": round(self.est_drop_kph),
            "apex_radius_m": round(self.apex_radius_m, 1),
            "duration_s": round(self.duration_s, 2),
            "direction": self.direction,
            "turn": self.turn,
            "per_sigma": self.per_sigma,
        }


@dataclass(slots=True)
class BrakePrior:
    game: str
    track_id: str
    layout_key: str
    track_length_m: float
    track_length_source: str
    vehicle: VehicleModel
    envelope_source: str  # "default" | the BrakeEnvelope's source
    sigmas_m: tuple[float, ...]
    windows: list[PriorWindow]
    rejected: list[dict[str, Any]]
    lap_time_s: float  # primary-sigma QSS lap time: a diagnostic, not a validation metric

    @property
    def source(self) -> str:
        """``qss@<model hash>``: changes whenever a vehicle parameter does."""
        raw = repr(dataclasses.astuple(self.vehicle)).encode()
        return f"qss@{hashlib.sha1(raw).hexdigest()[:8]}"

    def windows_ahead(self, lap_distance_m: float, horizon_m: float) -> list[tuple[float, PriorWindow]]:
        """``(metres to the window start, window)`` for windows starting within ``horizon_m`` ahead (wrap-aware),
        nearest first. A window already entered is not "ahead"."""
        L = self.track_length_m
        out: list[tuple[float, PriorWindow]] = []
        for w in self.windows:
            gap = (w.window_start_m - lap_distance_m) % L
            if gap <= horizon_m:
                out.append((gap, w))
        return sorted(out, key=lambda p: p[0])

    def to_payload(self) -> dict[str, Any]:
        L = self.track_length_m
        return {
            "game": self.game,
            "track_id": self.track_id,
            "layout_key": self.layout_key,
            "tier": TIER_PHYSICS_PREDICTED,
            "source": self.source,
            "licence": "pitwall",
            "label": PRIOR_LABEL,
            "inputs": {"outline_source": OUTLINE_SOURCE, "outline_tier": TIER_SHIPPED_SEED},
            "length_m": L,
            "track_length_source": self.track_length_source,
            "envelope": {
                "brake_base": self.vehicle.brake_base,
                "brake_aero": self.vehicle.brake_aero,
                "source": self.envelope_source,
            },
            "sigmas_m": list(self.sigmas_m),
            "primary_sigma_m": PRIMARY_SIGMA_M,
            "gate": {"min_drop_kph": HEAVY_DROP_KPH, "max_apex_radius_m": MAX_APEX_RADIUS_M, "every_sigma": True},
            "positional": False,
            "positional_reason": POSITIONAL_REASON,
            "min_lead_s": MIN_LEAD_S,
            "onset_error": {k: v for k, v in ONSET_EVIDENCE.items() if k != "captures"},
            "caveat": CAVEAT,
            "windows": [w.to_dict(L) for w in self.windows],
            "rejected": self.rejected,
            "diagnostics": {"qss_lap_time_s": round(self.lap_time_s, 2)},
        }


def _verified_turn(game: str, track_id: str, length: float, apex_m: float) -> dict[str, Any] | None:
    from pitwall.analysis.track_identity import MAX_LENGTH_MISMATCH, SheetError, find_sheet

    try:
        sheet = find_sheet(game, track_id)
    except SheetError:
        return None
    if sheet is None or sheet.lap_length_m <= 0:
        return None
    scale = length / sheet.lap_length_m
    if abs(scale - 1.0) > MAX_LENGTH_MISMATCH:
        return None
    for t in sheet.turns:
        a, b = t.segment_m[0] * scale, t.segment_m[1] * scale
        if t.verified and a <= apex_m < b:
            return {"label": t.label, "name": t.display_name, "voice_ok": bool(t.voice_ok and t.display_name)}
    return None


def brake_prior_from_outline(
    outline: TrackOutline,
    *,
    vehicle: VehicleModel | None = None,
    envelope: BrakeEnvelope | None = None,
    sigmas_m: Sequence[float] = SIGMA_ENSEMBLE_M,
    primary_sigma_m: float = PRIMARY_SIGMA_M,
) -> BrakePrior:
    """Gated heavy-stop windows for ``outline`` (see the module docstring)."""
    sigmas = tuple(float(s) for s in sigmas_m)
    if primary_sigma_m not in sigmas:
        raise ValueError("primary_sigma_m must be one of sigmas_m")
    veh = vehicle or VehicleModel()
    env_source = "default"
    if envelope is not None:
        veh = envelope.apply(veh)
        env_source = envelope.source
    L = outline.track_length_m
    solved: dict[float, list[SolvedZone]] = {}
    lap_time = math.nan
    primary_arc_m = math.nan
    for sg in sigmas:
        arc = resample_arc(outline, sg)
        solved[sg], t_lap = _solve(arc, veh)
        if sg == primary_sigma_m:
            lap_time, primary_arc_m = t_lap, arc.arc_length_m
    windows: list[PriorWindow] = []
    rejected: list[dict[str, Any]] = []
    for z in solved[primary_sigma_m]:
        matches: dict[float, SolvedZone] = {primary_sigma_m: z}  # the zone itself must pass at the primary sigma
        for sg in sigmas:
            cands = [c for c in solved[sg] if _same_stop(c, z, L)]
            if sg != primary_sigma_m and cands:  # split differently at this sigma: judge the biggest part
                matches[sg] = max(cands, key=lambda c: c.drop_kph)
        reasons = [f"no zone at sigma {sg:g} m" for sg in sigmas if sg not in matches]
        for sg, c in matches.items():
            if c.drop_kph < HEAVY_DROP_KPH:
                reasons.append(f"drop {c.drop_kph:.0f} km/h < {HEAVY_DROP_KPH:.0f} at sigma {sg:g} m")
            if c.apex_radius_m >= MAX_APEX_RADIUS_M:
                reasons.append(f"apex R {c.apex_radius_m:.0f} m >= {MAX_APEX_RADIUS_M:.0f} at sigma {sg:g} m")
        if reasons:
            rejected.append(
                {
                    "est_onset_m": round(z.onset_m, 1),
                    "est_apex_m": round(z.apex_m, 1),
                    "est_drop_kph": round(z.drop_kph),
                    "apex_radius_m": round(z.apex_radius_m, 1) if math.isfinite(z.apex_radius_m) else None,
                    "reasons": reasons,
                }
            )
            continue
        onsets = [_cyc(c.onset_m, z.onset_m, L) for c in matches.values()]
        spread = max(onsets) - min(onsets)
        windows.append(
            PriorWindow(
                index=0,
                est_onset_m=z.onset_m,
                est_apex_m=z.apex_m,
                est_end_m=z.end_m,
                uncertainty_m=max(ONSET_UNCERTAINTY_M, spread),
                onset_spread_m=spread,
                est_entry_kph=z.entry_kph,
                est_apex_kph=z.apex_kph,
                est_drop_kph=min(c.drop_kph for c in matches.values()),
                apex_radius_m=max(c.apex_radius_m for c in matches.values()),
                est_braking_distance_m=(z.end_s - z.onset_s) % primary_arc_m,
                duration_s=z.duration_s,
                direction=direction_of(z.apex_curvature),
                turn=_verified_turn(outline.game, outline.track_id, L, z.apex_m),
                per_sigma=[
                    {
                        "sigma_m": sg,
                        "est_onset_m": round(c.onset_m, 1),
                        "est_apex_kph": round(c.apex_kph),
                        "est_drop_kph": round(c.drop_kph),
                        "apex_radius_m": round(c.apex_radius_m, 1),
                    }
                    for sg, c in sorted(matches.items())
                ],
            )
        )
    windows.sort(key=lambda w: w.est_onset_m)
    for i, w in enumerate(windows, start=1):
        w.index = i
    return BrakePrior(
        game=outline.game,
        track_id=outline.track_id,
        layout_key=outline.key,
        track_length_m=L,
        track_length_source=outline.track_length_source,
        vehicle=veh,
        envelope_source=env_source,
        sigmas_m=sigmas,
        windows=windows,
        rejected=rejected,
        lap_time_s=lap_time,
    )


def build_brake_prior(
    game: str, track_id: str, track_length_m: float | None = None, envelope: BrakeEnvelope | None = None
) -> BrakePrior:
    """Cached prior for ``(game, track_id)``; ``track_length_m`` should be the session's ``m_trackLength``.

    The cache key is the lap length to 0.1 m and ``envelope.rounded()`` (its ``source`` included: keep it constant).
    A miss costs ~0.1 s of solving with the GIL held, so call this from a background worker, never from ingest.
    Raises ``OutlineError`` (a ``ValueError``) when there is no usable outline (see ``track_geometry.build_outline``).
    """
    length = None if track_length_m is None else round(float(track_length_m), 1)
    return _build_brake_prior(game, track_id, length, None if envelope is None else envelope.rounded())


@functools.lru_cache(maxsize=64)
def _build_brake_prior(
    game: str, track_id: str, track_length_m: float | None, envelope: BrakeEnvelope | None
) -> BrakePrior:
    outline = build_outline(game, track_id, track_length_m)
    return brake_prior_from_outline(outline, envelope=envelope)


class PriorRefresher:
    """When to (re)build the live session's physics prior, and the build itself, for one background thread.

    ``refresh`` is O(1) when nothing changed, so it can sit on a 2 Hz session hook; it rebuilds (a ~0.1 s solve, GIL
    held: never call it from the ingest thread) only on a new game/track/lap length, or when a supplied envelope
    ``differs_from`` the one the current prior was built with. A missing envelope keeps the current one (the AI field
    calibrates once it has data; losing a snapshot does not un-calibrate). Not thread-safe: one owner thread.
    """

    __slots__ = ("_envelope", "_prior", "_track")

    def __init__(self) -> None:
        self._track: tuple[str, str, float] | None = None
        self._envelope: BrakeEnvelope | None = None
        self._prior: BrakePrior | None = None

    @property
    def prior(self) -> BrakePrior | None:
        return self._prior

    def refresh(
        self, game: str, track_id: str | None, track_length_m: float | None, envelope: BrakeEnvelope | None = None
    ) -> tuple[bool, BrakePrior | None]:
        """``(changed, prior)``. ``changed`` False: the caller's current prior still stands. Otherwise ``prior`` is the
        new one, or None when this track has no usable outline or no lap length is known (unknown stays unknown:
        clear the layer)."""
        if not track_id or track_length_m is None or not math.isfinite(track_length_m) or track_length_m <= 0.0:
            changed = self._track is not None
            self._track, self._envelope, self._prior = None, None, None
            return changed, None
        key = (game, track_id, round(float(track_length_m), 1))
        same_track = key == self._track
        if same_track and (
            self._prior is None  # no outline for this track: an envelope cannot create one
            or envelope is None
            or (self._envelope is not None and not envelope.differs_from(self._envelope))
        ):
            return False, self._prior
        use = envelope
        try:
            prior: BrakePrior | None = build_brake_prior(game, track_id, key[2], use)
        except ValueError:  # OutlineError: no outline for this game/track, or the length gate refused it
            prior = None
        self._track, self._envelope, self._prior = key, use, prior
        return True, prior
