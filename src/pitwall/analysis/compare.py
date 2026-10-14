"""Per-corner lap metrics and distance-aligned lap comparison against a reference."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from pitwall.analysis.braking import BrakingEvent, detect_braking
from pitwall.analysis.distance import DistanceTrace, to_distance_domain
from pitwall.analysis.laps import LapTrace
from pitwall.analysis.track import Corner, TrackModel

BRAKE_MATCH_BEFORE_APEX_M = 450.0
BRAKE_MATCH_APEX_TOL_M = 80.0
# Two laps whose sessions report track lengths this far apart (relative) are on different layouts, or one of them is
# scaled wrongly: distances cannot be aligned. Assetto Corsa on a console sends no layout name, so its layouts share a
# track id (PS5: trackConfig == trackName); the length is the only thing that tells them apart. Derived lengths of one
# layout (GT7/Forza driven laps, AC full laps) agree to about 1 %.
LAYOUT_LENGTH_TOLERANCE = 0.03


def lengths_compatible(a: Any, b: Any, tol: float = LAYOUT_LENGTH_TOLERANCE) -> bool:
    """False only when both track lengths are known and differ by more than ``tol`` (relative); unknown = no veto."""
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return True
    if not (np.isfinite(fa) and np.isfinite(fb)) or fa <= 0.0 or fb <= 0.0:
        return True
    return abs(fa - fb) <= tol * max(fa, fb)


@dataclass(slots=True)
class CornerMetrics:
    corner: str
    segment_time_s: float | None
    brake_start_m: float | None = None
    brake_end_m: float | None = None
    brake_peak: float | None = None
    time_to_peak_s: float | None = None
    release_s: float | None = None
    trail_brake_m: float | None = None
    coast_m: float | None = None
    entry_speed_kph: float | None = None  # speed at the model's entry point
    min_speed_kph: float | None = None
    min_speed_m: float | None = None
    exit_speed_kph: float | None = None  # speed at the model's exit point
    throttle_pickup_m: float | None = None
    throttle_full_m: float | None = None


@dataclass(slots=True)
class LapAnalysis:
    lap: LapTrace
    dtrace: DistanceTrace
    braking: list[BrakingEvent]
    corners: dict[str, CornerMetrics]


def _match_event(events: list[BrakingEvent], c: Corner) -> BrakingEvent | None:
    best: BrakingEvent | None = None
    for e in events:
        if (
            c.apex_m - BRAKE_MATCH_BEFORE_APEX_M <= e.start_m <= c.apex_m
            and (abs(e.min_speed_m - c.apex_m) <= BRAKE_MATCH_APEX_TOL_M)
            and (best is None or e.start_m > best.start_m)
        ):
            best = e
    return best


def analyse_lap(lap: LapTrace, model: TrackModel) -> LapAnalysis:
    dt = to_distance_domain(lap, model.length_m)
    events = detect_braking(lap)
    out: dict[str, CornerMetrics] = {}
    v = dt.ch["speed_kph"]
    for c in model.corners:
        t0, t1 = dt.at("t_s", c.seg_start_m), dt.at("t_s", min(c.seg_end_m, model.length_m - 1))
        seg_t = t1 - t0 if np.isfinite(t0) and np.isfinite(t1) else None
        m = CornerMetrics(corner=c.name, segment_time_s=seg_t)
        lo = int(max(0, c.apex_m - BRAKE_MATCH_APEX_TOL_M))
        hi = int(min(len(v) - 1, c.apex_m + BRAKE_MATCH_APEX_TOL_M))
        window = v[lo : hi + 1]
        if np.isfinite(window).any():
            k = int(np.nanargmin(window))
            m.min_speed_kph = float(window[k])
            m.min_speed_m = float(dt.d[lo + k])
        m.entry_speed_kph = _finite(dt.at("speed_kph", c.entry_m))
        m.exit_speed_kph = _finite(dt.at("speed_kph", c.exit_m))
        e = _match_event(events, c)
        if e is not None:
            m.brake_start_m = e.start_m
            m.brake_end_m = e.end_m
            m.brake_peak = e.peak_brake
            m.time_to_peak_s = e.time_to_peak_s
            m.release_s = e.release_s
            m.trail_brake_m = e.trail_brake_m
            m.coast_m = e.coast_m
            m.throttle_pickup_m = e.throttle_pickup_m
            m.throttle_full_m = e.throttle_full_m
        out[c.name] = m
    return LapAnalysis(lap=lap, dtrace=dt, braking=events, corners=out)


def _finite(x: float | None) -> float | None:
    return float(x) if x is not None and np.isfinite(x) else None


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


@dataclass(slots=True)
class CornerDelta:
    """``cmp - ref`` for each metric. Negative brake_point_delta_m = braking EARLIER than reference."""

    corner: str
    time_delta_s: float | None
    brake_point_delta_m: float | None
    brake_release_delta_m: float | None
    min_speed_delta_kph: float | None
    min_speed_pos_delta_m: float | None
    entry_speed_delta_kph: float | None
    exit_speed_delta_kph: float | None
    throttle_pickup_delta_m: float | None
    throttle_full_delta_m: float | None
    coast_delta_m: float | None
    release_time_delta_s: float | None
    ref: CornerMetrics
    cmp: CornerMetrics


@dataclass(slots=True)
class Compatibility:
    ok: bool
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LapComparison:
    ref_lap_number: int
    cmp_lap_number: int
    total_delta_s: float | None
    delta_d: list[float]  # distances (m), downsampled
    delta_s: list[float]  # cumulative time delta at those distances (cmp - ref)
    corners: list[CornerDelta]
    compatibility: Compatibility

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compat_meta(m: dict[str, Any]) -> dict[str, Any]:
    """Normalise lap/session context into the keys ``check_compatibility`` understands."""
    weather = m.get("weather")
    if isinstance(weather, dict):
        weather = weather.get("condition")
    assists = m.get("assists") or {}
    return {
        "game": m.get("game"),
        "track_id": m.get("track_id"),
        "track_length_m": m.get("track_length_m"),
        "car_id": m.get("car_id"),
        "weather": weather,
        "track_temp_c": m.get("track_temp_c"),
        "tyre_compound": m.get("tyre_compound"),
        "setup_fp": m.get("setup_fp"),
        "fuel_start_kg": m.get("fuel_start_kg"),
        "braking_assist": assists.get("braking"),
        "gearbox_assist": assists.get("gearbox"),
    }


def check_compatibility(ref_meta: dict[str, Any], cmp_meta: dict[str, Any], ref_clean: bool) -> Compatibility:
    """Decide whether comparing two laps is meaningful. ``*_meta`` are lap/session context dicts."""
    blocking: list[str] = []
    warnings: list[str] = []
    if not ref_clean:
        blocking.append("reference lap is not clean (invalid, incomplete, flashback or pit lap)")
    for key, label in (("game", "game"), ("track_id", "track"), ("car_id", "car")):
        a, b = ref_meta.get(key), cmp_meta.get(key)
        if a is not None and b is not None and a != b:
            blocking.append(f"different {label}: reference {a!r} vs lap {b!r}")
    la, lb = ref_meta.get("track_length_m"), cmp_meta.get("track_length_m")
    if la is not None and lb is not None and not lengths_compatible(la, lb):
        blocking.append(
            f"different track length (another layout?): reference {float(la):.0f} m vs lap {float(lb):.0f} m"
        )
    wet = {"light_rain", "heavy_rain", "storm"}
    wa, wb = ref_meta.get("weather"), cmp_meta.get("weather")
    if wa and wb and ((wa in wet) != (wb in wet)):
        blocking.append(f"wet/dry mismatch: reference {wa} vs lap {wb}")
    for key in ("braking_assist", "abs", "traction_control", "gearbox_assist"):
        a, b = ref_meta.get(key), cmp_meta.get(key)
        if a is not None and b is not None and a != b:
            blocking.append(f"assist '{key}' differs ({a} vs {b})")
    ca, cb = ref_meta.get("tyre_compound"), cmp_meta.get("tyre_compound")
    if ca and cb and ca != cb:
        warnings.append(f"tyre compound differs ({ca} vs {cb}) - grip-related deltas are less reliable")
    sa, sb = ref_meta.get("setup_fp"), cmp_meta.get("setup_fp")
    if sa and sb and sa != sb:
        warnings.append("car setup differs from the reference lap")
    fa, fb = ref_meta.get("fuel_start_kg"), cmp_meta.get("fuel_start_kg")
    if fa is not None and fb is not None and abs(fa - fb) > 15:
        warnings.append(f"fuel load differs by {abs(fa - fb):.0f} kg")
    ta, tb = ref_meta.get("track_temp_c"), cmp_meta.get("track_temp_c")
    if ta is not None and tb is not None and abs(ta - tb) > 8:
        warnings.append(f"track temperature differs by {abs(ta - tb):.0f} C")
    return Compatibility(ok=not blocking, blocking=blocking, warnings=warnings)


def corner_delta(name: str, ref: CornerMetrics, cmp: CornerMetrics) -> CornerDelta:
    """``cmp - ref`` for one corner's metrics. Pure: the lap processor also uses it to re-base a corner's recent laps
    on a new reference lap (their own metrics stay as measured; only the reference they are compared with moves)."""
    return CornerDelta(
        corner=name,
        time_delta_s=_diff(cmp.segment_time_s, ref.segment_time_s),
        brake_point_delta_m=_diff(cmp.brake_start_m, ref.brake_start_m),
        brake_release_delta_m=_diff(cmp.brake_end_m, ref.brake_end_m),
        min_speed_delta_kph=_diff(cmp.min_speed_kph, ref.min_speed_kph),
        min_speed_pos_delta_m=_diff(cmp.min_speed_m, ref.min_speed_m),
        entry_speed_delta_kph=_diff(cmp.entry_speed_kph, ref.entry_speed_kph),
        exit_speed_delta_kph=_diff(cmp.exit_speed_kph, ref.exit_speed_kph),
        throttle_pickup_delta_m=_diff(cmp.throttle_pickup_m, ref.throttle_pickup_m),
        throttle_full_delta_m=_diff(cmp.throttle_full_m, ref.throttle_full_m),
        coast_delta_m=_diff(cmp.coast_m, ref.coast_m),
        release_time_delta_s=_diff(cmp.release_s, ref.release_s),
        ref=ref,
        cmp=cmp,
    )


def compare(ref: LapAnalysis, cmp: LapAnalysis, compat: Compatibility, downsample_m: float = 10.0) -> LapComparison:
    d = ref.dtrace.d
    delta = cmp.dtrace.t_s - ref.dtrace.t_s
    stride = max(1, int(downsample_m / float(d[1] - d[0])))
    keep = np.arange(0, len(d), stride)
    finite = np.isfinite(delta[keep])
    total = None
    if ref.lap.lap_time_ms is not None and cmp.lap.lap_time_ms is not None:
        total = (cmp.lap.lap_time_ms - ref.lap.lap_time_ms) / 1000.0
    corners = [corner_delta(name, r, c) for name, r in ref.corners.items() if (c := cmp.corners.get(name)) is not None]
    return LapComparison(
        ref_lap_number=ref.lap.lap_number,
        cmp_lap_number=cmp.lap.lap_number,
        total_delta_s=total,
        delta_d=[float(x) for x in d[keep][finite]],
        delta_s=[round(float(x), 4) for x in delta[keep][finite]],
        corners=corners,
        compatibility=compat,
    )
