"""Suggested AI difficulty per driver x track x car class x session category x weather (pure).

Input: the driver's own AI pace points (``repo.driver_ai_pace_points``: real driving only, never synthetic or
replays). Only points with status ``ok`` and a dry or wet session count; mixed (or unknown) weather points are shown in
the series but never used here. Per key the newest ``N_MAX`` points are used: ``g`` = gap to the typical AI car in %
(positive = the driver is slower), ``d`` = the game's AI difficulty.

Three tiers, and no number is ever produced without the driver's own data at that key:

* ``measured``: a least-squares line of g against d at this key (at least 2 sessions at 2 levels spanning
  ``MIN_SPAN`` or more), solved for the target gap (default 0 %: level with the typical AI car). The AI must get faster
  as the level rises (slope >= ``MIN_SLOPE`` %-points per level), otherwise ``direction_only`` with
  ``note="levels_disagree"``. Extrapolation is limited to ``MEASURED_EXTRAPOLATION`` levels beyond the levels raced.
* ``estimate_other_tracks``: one or more sessions here but no fit; the slope is the median of the driver's own measured
  slopes at *other* keys of the same game, car class and category, the offset comes from this key's points. Always
  low confidence; extrapolation is limited to ``ESTIMATE_EXTRAPOLATION`` levels.
* ``direction_only``: no level, only whether a lower or higher level should give closer racing, from the newest point.

Assumption (docs: follow-ups): gap % is roughly linear in the AI level over the levels raced. ``SIGMA0`` (1 %-point)
is a nominal noise level used until there are three or more sessions to measure it.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

N_MAX = 8  # newest points per key used for a suggestion
MIN_SLOPE = 0.02  # %-points of gap per AI level: below this the levels raced do not show the AI getting faster
MIN_SPAN = 5  # AI levels between the lowest and highest level raced, for a measured fit
MEASURED_EXTRAPOLATION = 10
ESTIMATE_EXTRAPOLATION = 15
SIGMA0 = 1.0  # %-points: nominal residual noise until there are 3+ sessions to measure it
DIRECTION_BAND = 1.0  # |g - target| <= this: the level is about right
TARGET_GAP_MIN = -5.0
TARGET_GAP_MAX = 5.0
LEVEL_MIN = 0
LEVEL_MAX = 110
USED_WEATHER = ("dry", "wet")

CATEGORY_PLURAL = {
    "race": "races",
    "qualifying": "qualifying sessions",
    "practice": "practice sessions",
    "time_trial": "time trials",
    "unknown": "sessions",
}


@dataclass(slots=True, frozen=True)
class AiLevelKey:
    game: str
    track_id: str
    car_class: str | None
    session_category: str
    weather_class: str | None

    @classmethod
    def of(cls, p: Mapping[str, Any]) -> AiLevelKey:
        return cls(
            game=str(p["game"]),
            track_id=str(p["track_id"]),
            car_class=p.get("car_class"),
            session_category=str(p.get("session_category") or "unknown"),
            weather_class=p.get("weather_class"),
        )

    def to_dict(self, track_name: str | None) -> dict[str, Any]:
        return {
            "game": self.game,
            "track_id": self.track_id,
            "track_name": track_name,
            "car_class": self.car_class,
            "session_category": self.session_category,
            "weather_class": self.weather_class,
        }


@dataclass(slots=True, frozen=True)
class _Fit:
    a: float
    b: float
    sigma: float | None  # residual std (n >= 3), else None


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _clamp(v: int) -> int:
    return max(LEVEL_MIN, min(LEVEL_MAX, v))


def _levels_text(levels: Sequence[int]) -> str:
    items = [str(v) for v in levels]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _usable(p: Mapping[str, Any]) -> bool:
    return (
        p.get("status") == "ok"
        and p.get("weather_class") in USED_WEATHER
        and isinstance(p.get("gap_pct"), int | float)
        and isinstance(p.get("ai_difficulty"), int)
    )


def _fit(gs: Sequence[float], ds: Sequence[int]) -> _Fit | None:
    """Ordinary least squares g = a + b d, or None when the levels do not span ``MIN_SPAN``."""
    n = len(gs)
    if n < 2 or len(set(ds)) < 2 or max(ds) - min(ds) < MIN_SPAN:
        return None
    d_mean = sum(ds) / n
    g_mean = sum(gs) / n
    sxx = sum((d - d_mean) ** 2 for d in ds)
    b = sum((d - d_mean) * (g - g_mean) for d, g in zip(ds, gs, strict=True)) / sxx
    a = g_mean - b * d_mean
    sigma = None
    if n >= 3:
        sigma = math.sqrt(sum((g - (a + b * d)) ** 2 for d, g in zip(ds, gs, strict=True)) / (n - 2))
    return _Fit(a, b, sigma)


def _newest(points: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The newest ``N_MAX`` usable points (input is oldest first), oldest first."""
    return [p for p in points if _usable(p)][-N_MAX:]


def _direction(g_latest: float, target: float) -> str:
    if abs(g_latest - target) <= DIRECTION_BAND:
        return "about_right"
    return "lower" if g_latest > target + DIRECTION_BAND else "higher"


def _vs_latest(level: int, latest: int) -> str:
    return "about_right" if level == latest else ("higher" if level > latest else "lower")


def _base(key: AiLevelKey, track_name: str | None, used: Sequence[Mapping[str, Any]], target: float) -> dict[str, Any]:
    latest = used[-1]
    return {
        "key": key.to_dict(track_name),
        "basis": "direction_only",
        "level": None,
        "range": None,
        "bound": None,
        "confidence": None,
        "direction": None,
        "note": None,
        "latest_level": int(latest["ai_difficulty"]),
        "latest_gap_pct": latest.get("gap_pct"),
        "target_gap_pct": target,
        "sessions_used": len(used),
        "levels_used": sorted({int(p["ai_difficulty"]) for p in used}),
        "slope_pct_per_level": None,
        "slope_sources": [],
        "text": "",
    }


def _direction_only(out: dict[str, Any], target: float, note: str | None = None) -> dict[str, Any]:
    d, g = out["latest_level"], float(out["latest_gap_pct"])
    direction = _direction(g, target)
    out.update(basis="direction_only", direction=direction, note=note)
    tail = "Race at a couple of difficulty levels here and Pitwall can suggest one."
    if note == "levels_disagree":
        tail = (
            f"Your races here at levels {_levels_text(out['levels_used'])} do not yet show the AI getting faster "
            "with level, so Pitwall cannot suggest one yet."
        )
    if direction == "about_right":
        out["text"] = f"At AI {d} you were level with the typical AI car here ({g:+.1f}%). {tail}"
    else:
        pace = "slower" if g > 0 else "faster"
        advice = "a lower level should give closer racing" if direction == "lower" else "try a higher level"
        out["text"] = (
            f"At AI {d} your best lap here was {abs(g):.1f}% {pace} than the typical AI car, so {advice}. {tail}"
        )
    return out


def _place(d_star: float, d_min: int, d_max: int, limit: int) -> tuple[int, str | None]:
    """The suggested level for an exact solution ``d_star``, limited to ``limit`` levels beyond the levels raced."""
    if d_star > d_max + limit:
        return _clamp(d_max + limit), "at_least"
    if d_star < d_min - limit:
        return _clamp(d_min - limit), "at_most"
    return _clamp(_round_half_up(d_star)), None


def _measured(
    out: dict[str, Any], fit: _Fit, used: Sequence[Mapping[str, Any]], target: float, category: str
) -> dict[str, Any]:
    ds = [int(p["ai_difficulty"]) for p in used]
    d_min, d_max = min(ds), max(ds)
    d_star = (target - fit.a) / fit.b
    level, bound = _place(d_star, d_min, d_max, MEASURED_EXTRAPOLATION)
    sigma = fit.sigma if fit.sigma is not None else SIGMA0
    h = max(2, math.ceil(sigma / fit.b))
    n = len(used)
    distinct = len(set(ds))
    if bound is not None or h > 10:
        confidence = "low"
    elif n >= 4 and distinct >= 3 and d_max - d_min >= 10 and d_min <= d_star <= d_max and h <= 5:
        confidence = "high"
    else:
        confidence = "medium"
    lo, hi = _clamp(level - h), _clamp(level + h)
    out.update(
        basis="measured",
        level=level,
        range=[lo, hi],
        bound=bound,
        confidence=confidence,
        direction=_vs_latest(level, out["latest_level"]),
        slope_pct_per_level=round(fit.b, 3),
    )
    if bound == "at_least":
        out["text"] = f"Try AI {level} or higher here: you were faster than the typical AI car even at {d_max}."
    elif bound == "at_most":
        out["text"] = f"Try AI {level} or lower here: you were slower than the typical AI car even at {d_min}."
    else:
        plural = CATEGORY_PLURAL.get(category, "sessions")
        out["text"] = (
            f"Try AI {level} here ({lo}-{hi}). Measured from {n} {plural} at levels {_levels_text(out['levels_used'])}."
        )
    return out


def _estimate(
    out: dict[str, Any], used: Sequence[Mapping[str, Any]], target: float, slopes: Sequence[tuple[float, str]]
) -> dict[str, Any]:
    b_est = statistics.median(b for b, _ in slopes)
    ds = [int(p["ai_difficulty"]) for p in used]
    a = statistics.fmean(float(p["gap_pct"]) - b_est * d for p, d in zip(used, ds, strict=True))
    d_star = (target - a) / b_est
    level, bound = _place(d_star, min(ds), max(ds), ESTIMATE_EXTRAPOLATION)
    h = max(3, math.ceil(SIGMA0 / b_est))
    lo, hi = _clamp(level - h), _clamp(level + h)
    sources = sorted({name for _, name in slopes})
    out.update(
        basis="estimate_other_tracks",
        level=level,
        range=[lo, hi],
        bound=bound,
        confidence="low",
        direction=_vs_latest(level, out["latest_level"]),
        slope_pct_per_level=round(b_est, 3),
        slope_sources=sources,
    )
    shown = f"{level} or higher" if bound == "at_least" else f"{level} or lower" if bound == "at_most" else f"{level}"
    out["text"] = (
        f"Estimated AI level here: {shown} ({lo}-{hi}). Based on how the AI's pace changed with level at "
        f"{_levels_names(sources)}; race here at another level to measure it."
    )
    return out


def _levels_names(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _group(points: Sequence[Mapping[str, Any]]) -> dict[AiLevelKey, list[Mapping[str, Any]]]:
    groups: dict[AiLevelKey, list[Mapping[str, Any]]] = {}
    for p in points:
        groups.setdefault(AiLevelKey.of(p), []).append(p)
    return groups


def _measured_slopes(groups: Mapping[AiLevelKey, list[Mapping[str, Any]]]) -> dict[AiLevelKey, tuple[float, str]]:
    """Per key: the measured slope (>= ``MIN_SLOPE``) and the track's name, where the driver has one."""
    out: dict[AiLevelKey, tuple[float, str]] = {}
    for key, pts in groups.items():
        used = _newest(pts)
        fit = _fit([float(p["gap_pct"]) for p in used], [int(p["ai_difficulty"]) for p in used])
        if fit is not None and fit.b >= MIN_SLOPE:
            name = next((str(p["track_name"]) for p in reversed(pts) if p.get("track_name")), key.track_id)
            out[key] = (fit.b, name)
    return out


def suggest_for_key(
    key: AiLevelKey,
    points: Sequence[Mapping[str, Any]],
    *,
    target_gap_pct: float = 0.0,
    _groups: Mapping[AiLevelKey, list[Mapping[str, Any]]] | None = None,
    _slopes: Mapping[AiLevelKey, tuple[float, str]] | None = None,
) -> dict[str, Any] | None:
    """The ``AiLevelSuggestion`` for one key from all of the driver's points (oldest first), or None when the key
    has no usable point (no ok point, or mixed / unknown weather)."""
    if not TARGET_GAP_MIN <= target_gap_pct <= TARGET_GAP_MAX:
        raise ValueError(f"target_gap_pct must be {TARGET_GAP_MIN}..{TARGET_GAP_MAX}, got {target_gap_pct}")
    if key.weather_class not in USED_WEATHER:
        return None
    groups = _groups if _groups is not None else _group(points)
    used = _newest(groups.get(key, []))
    if not used:
        return None
    track_name = next((p.get("track_name") for p in reversed(groups[key]) if p.get("track_name")), None)
    out = _base(key, track_name, used, target_gap_pct)
    fit = _fit([float(p["gap_pct"]) for p in used], [int(p["ai_difficulty"]) for p in used])
    if fit is not None:
        if fit.b < MIN_SLOPE:
            return _direction_only(out, target_gap_pct, note="levels_disagree")
        return _measured(out, fit, used, target_gap_pct, key.session_category)
    slopes_all = _slopes if _slopes is not None else _measured_slopes(groups)
    others = [
        v
        for k, v in slopes_all.items()
        if k != key
        and k.game == key.game
        and k.car_class == key.car_class
        and k.session_category == key.session_category
    ]
    if others:
        return _estimate(out, used, target_gap_pct, others)
    return _direction_only(out, target_gap_pct)


def suggestions(
    all_points: Sequence[Mapping[str, Any]],
    scope_points: Sequence[Mapping[str, Any]],
    *,
    target_gap_pct: float = 0.0,
) -> list[dict[str, Any]]:
    """One suggestion per key present in ``scope_points`` (newest key first), each computed from ``all_points``
    (all of the driver's points, so other tracks' slopes are available). Keys without a usable point are left out."""
    groups = _group(all_points)
    slopes = _measured_slopes(groups)
    newest: dict[AiLevelKey, float] = {}
    for p in scope_points:
        k = AiLevelKey.of(p)
        newest[k] = max(newest.get(k, -math.inf), float(p.get("started_unix") or 0.0))
    out: list[dict[str, Any]] = []
    for k in sorted(newest, key=lambda k: -newest[k]):
        s = suggest_for_key(k, all_points, target_gap_pct=target_gap_pct, _groups=groups, _slopes=slopes)
        if s is not None:
            out.append(s)
    return out
