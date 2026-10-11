"""Suggested AI level (``analysis.ai_level``): measured fit, estimate from other tracks, direction only."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from pitwall.analysis.ai_level import N_MAX, AiLevelKey, suggest_for_key, suggestions

T0 = 1_790_000_000.0


def pt(
    level: int,
    gap: float,
    *,
    track: str = "f1:17",
    name: str = "Austria",
    car_class: str = "F1 World",
    category: str = "race",
    weather: str | None = "dry",
    status: str = "ok",
    k: int = 0,
) -> dict[str, Any]:
    return {
        "session_id": f"s{k}",
        "started_unix": T0 + k,
        "game": "f1_25",
        "track_id": track,
        "track_name": name,
        "car_class": car_class,
        "session_category": category,
        "weather_class": weather,
        "status": status,
        "ai_difficulty": level,
        "gap_pct": gap if status == "ok" else None,
    }


def series(*pairs: tuple[int, float], k0: int = 0, **kw: Any) -> list[dict[str, Any]]:
    return [pt(d, g, k=k0 + i, **kw) for i, (d, g) in enumerate(pairs)]


KEY = AiLevelKey("f1_25", "f1:17", "F1 World", "race", "dry")


def suggest(points: list[dict[str, Any]], key: AiLevelKey = KEY, target: float = 0.0) -> dict[str, Any]:
    s = suggest_for_key(key, points, target_gap_pct=target)
    assert s is not None
    return s


def test_exact_two_point_fit() -> None:
    s = suggest(series((30, -5.0), (40, 5.0)))
    assert s["basis"] == "measured" and s["level"] == 35 and s["range"] == [33, 37] and s["bound"] is None
    assert s["confidence"] == "medium" and s["slope_pct_per_level"] == 1.0 and s["note"] is None
    assert s["latest_level"] == 40 and s["latest_gap_pct"] == 5.0 and s["direction"] == "lower"
    assert s["sessions_used"] == 2 and s["levels_used"] == [30, 40] and s["slope_sources"] == []
    assert s["text"] == "Try AI 35 here (33-37). Measured from 2 races at levels 30 and 40."
    assert s["key"] == {
        "game": "f1_25",
        "track_id": "f1:17",
        "track_name": "Austria",
        "car_class": "F1 World",
        "session_category": "race",
        "weather_class": "dry",
    }


def test_four_noisy_points_match_least_squares() -> None:
    pairs = [(25, -3.1), (30, -0.4), (35, 1.2), (40, 4.9)]
    s = suggest(series(*pairs))
    d = np.array([p[0] for p in pairs], dtype=float)
    g = np.array([p[1] for p in pairs])
    b, a = np.polyfit(d, g, 1)
    sigma = math.sqrt(float(np.sum((g - (a + b * d)) ** 2)) / 2)
    h = max(2, math.ceil(sigma / b))
    level = math.floor(-a / b + 0.5)
    assert s["level"] == level and s["range"] == [level - h, level + h]
    assert s["slope_pct_per_level"] == round(float(b), 3)
    assert s["confidence"] == "high"  # 4 sessions, 4 levels over 15, inside the levels raced, tight band


def test_levels_that_disagree_give_direction_only() -> None:
    s = suggest(series((30, 2.0), (40, 2.1)))  # 0.01 %-points per level: the AI did not get faster
    assert s["basis"] == "direction_only" and s["note"] == "levels_disagree" and s["level"] is None
    assert s["direction"] == "lower" and s["range"] is None and s["confidence"] is None
    assert "30 and 40" in s["text"]


def test_bounds_and_clamps() -> None:
    at_least = suggest(series((30, -10.0), (35, -9.0)))  # d* = 80: far above the levels raced
    assert at_least["level"] == 45 and at_least["bound"] == "at_least" and at_least["confidence"] == "low"
    assert at_least["text"] == "Try AI 45 or higher here: you were faster than the typical AI car even at 35."
    assert at_least["direction"] == "higher"
    at_most = suggest(series((70, 10.0), (75, 11.0)))  # d* = 20
    assert at_most["level"] == 60 and at_most["bound"] == "at_most"
    assert at_most["text"] == "Try AI 60 or lower here: you were slower than the typical AI car even at 70."
    top = suggest(series((100, -10.0), (105, -9.0)))
    assert top["level"] == 110 and top["range"][1] == 110
    bottom = suggest(series((0, 10.0), (5, 11.0)))
    assert bottom["level"] == 0 and bottom["range"][0] == 0


def test_round_half_up_and_target_gap() -> None:
    assert suggest(series((30, -2.5), (40, 7.5)))["level"] == 33  # d* = 32.5 -> 33
    pts = series((30, -5.0), (40, 5.0))
    assert suggest(pts, target=2.0)["level"] == 37  # want the AI 2 % faster than me: a higher level
    assert suggest(pts, target=-2.0)["level"] == 33
    with pytest.raises(ValueError):
        suggest_for_key(KEY, pts, target_gap_pct=5.5)


def test_estimate_from_other_tracks() -> None:
    other = series((30, -2.5), (40, 2.5), track="f1:7", name="Silverstone")  # slope 0.5
    here = [pt(35, 5.0, k=10)]
    s = suggest(other + here)
    assert s["basis"] == "estimate_other_tracks" and s["confidence"] == "low"
    assert s["slope_pct_per_level"] == 0.5 and s["slope_sources"] == ["Silverstone"]
    assert s["level"] == 25 and s["range"] == [22, 28] and s["direction"] == "lower"  # a = 5 - 17.5; h = 3
    assert s["text"] == (
        "Estimated AI level here: 25 (22-28). Based on how the AI's pace changed with level at Silverstone; "
        "race here at another level to measure it."
    )
    # extrapolation is limited to 15 levels beyond the levels raced here
    far = suggest([*other, pt(35, 20.0, k=11)])
    assert far["level"] == 20 and far["bound"] == "at_most"
    # another car class never lends its slope
    f2 = series((30, -2.5), (40, 2.5), track="f1:7", name="Silverstone", car_class="F2")
    assert suggest(f2 + here)["basis"] == "direction_only"


def test_mixed_weather_is_shown_not_used() -> None:
    mixed = series((30, -5.0), (40, 5.0), weather="mixed")
    assert suggest_for_key(AiLevelKey("f1_25", "f1:17", "F1 World", "race", "mixed"), mixed) is None
    assert suggest_for_key(KEY, mixed) is None  # no dry point at all
    s = suggest([*mixed, pt(35, 3.0, k=5)])
    assert s["basis"] == "direction_only" and s["sessions_used"] == 1  # the mixed points do not count
    assert suggestions(mixed, mixed) == []


def test_direction_thresholds() -> None:
    assert suggest([pt(35, 1.0)])["direction"] == "about_right"
    assert suggest([pt(35, -1.0)])["direction"] == "about_right"
    assert suggest([pt(35, 1.01)])["direction"] == "lower"
    assert suggest([pt(35, -1.01)])["direction"] == "higher"
    assert suggest([pt(35, 3.0)], target=2.5)["direction"] == "about_right"
    ok = suggest([pt(35, 0.4)])
    assert ok["text"] == (
        "At AI 35 you were level with the typical AI car here (+0.4%). Race at a couple of difficulty levels here "
        "and Pitwall can suggest one."
    )
    faster = suggest([pt(35, -3.26)])
    assert faster["text"] == (
        "At AI 35 your best lap here was 3.3% faster than the typical AI car, so try a higher level. Race at a "
        "couple of difficulty levels here and Pitwall can suggest one."
    )


def test_spec_fixture_austria() -> None:
    s = suggest([pt(35, 5.06), pt(35, 0.0, status="no_driver_lap", k=1)])
    assert s == {
        "key": {
            "game": "f1_25",
            "track_id": "f1:17",
            "track_name": "Austria",
            "car_class": "F1 World",
            "session_category": "race",
            "weather_class": "dry",
        },
        "basis": "direction_only",
        "level": None,
        "range": None,
        "bound": None,
        "confidence": None,
        "direction": "lower",
        "note": None,
        "latest_level": 35,
        "latest_gap_pct": 5.06,
        "target_gap_pct": 0.0,
        "sessions_used": 1,
        "levels_used": [35],
        "slope_pct_per_level": None,
        "slope_sources": [],
        "text": "At AI 35 your best lap here was 5.1% slower than the typical AI car, so a lower level should give "
        "closer racing. Race at a couple of difficulty levels here and Pitwall can suggest one.",
    }


def test_low_confidence_when_the_band_is_wide_and_newest_points_only() -> None:
    s = suggest(series((30, -1.0), (35, 1.5), (40, 0.0)))  # slope 0.1, residual std 1.6 -> band 17 > 10
    assert s["basis"] == "measured" and s["confidence"] == "low"
    many = series(*[(20 + 5 * i, -5.0 + i) for i in range(10)])
    s = suggest(many)
    assert s["sessions_used"] == N_MAX and s["levels_used"][0] == 30  # the two oldest are left out


def test_suggestions_per_key_newest_first() -> None:
    austria = series((35, 5.06))
    melbourne = [pt(35, -3.26, track="f1:0", name="Melbourne", car_class="F2", k=5)]
    other = series((30, -2.5), (40, 2.5), track="f1:7", name="Silverstone", k0=-10)
    every = austria + melbourne + other
    out = suggestions(every, austria + melbourne)
    assert [s["key"]["track_name"] for s in out] == ["Melbourne", "Austria"]
    assert out[1]["basis"] == "estimate_other_tracks"  # Silverstone's slope is available, though out of scope
    assert out[0]["direction"] == "higher"
