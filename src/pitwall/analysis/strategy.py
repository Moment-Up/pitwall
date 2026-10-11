"""Deterministic fuel / tyre / pit-window calculations. The AI explains these numbers; it never computes them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

EXCLUDE_FLAGS = {"flashback", "pit_in", "pit_out", "incomplete"}


@dataclass(slots=True)
class FuelEstimate:
    per_lap_kg: float | None
    laps_used: int
    fuel_now_kg: float | None
    laps_of_fuel: float | None  # how many laps the current fuel lasts at per_lap_kg
    game_estimate_laps: float | None
    laps_remaining_in_race: int | None
    margin_laps: float | None  # laps_of_fuel - laps_remaining (negative = short)
    margin_kg: float | None


@dataclass(slots=True)
class TyreEstimate:
    compound: str | None
    age_laps: int | None
    wear_now_pct: list[float] | None  # FL, FR, RL, RR
    wear_rate_pct_per_lap: list[float] | None
    laps_to_limit: float | None  # until the most-worn tyre reaches ``limit_pct``
    limiting_wheel: str | None
    limit_pct: float
    laps_used: int


def _green_laps(laps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [lap for lap in laps if not (set(lap.get("flags") or []) & EXCLUDE_FLAGS)]


def fuel_estimate(
    laps: list[dict[str, Any]],
    fuel_now_kg: float | None,
    game_estimate_laps: float | None,
    laps_remaining_in_race: int | None,
) -> FuelEstimate:
    used = []
    for lap in _green_laps(laps):
        m = lap.get("meta") or {}
        a, b = m.get("fuel_start_kg"), m.get("fuel_end_kg")
        if a is not None and b is not None and 0 < a - b < 10:
            used.append(a - b)
    per_lap = float(np.median(used)) if used else None
    laps_of_fuel = fuel_now_kg / per_lap if (per_lap and fuel_now_kg is not None) else None
    margin = margin_kg = None
    if laps_of_fuel is not None and laps_remaining_in_race is not None and per_lap:
        margin = laps_of_fuel - laps_remaining_in_race
        margin_kg = margin * per_lap
    return FuelEstimate(
        per_lap_kg=None if per_lap is None else round(per_lap, 3),
        laps_used=len(used),
        fuel_now_kg=None if fuel_now_kg is None else round(fuel_now_kg, 2),
        laps_of_fuel=None if laps_of_fuel is None else round(laps_of_fuel, 2),
        game_estimate_laps=None if game_estimate_laps is None else round(game_estimate_laps, 2),
        laps_remaining_in_race=laps_remaining_in_race,
        margin_laps=None if margin is None else round(margin, 2),
        margin_kg=None if margin_kg is None else round(margin_kg, 2),
    )


WHEELS = ("front-left", "front-right", "rear-left", "rear-right")


def tyre_estimate(laps: list[dict[str, Any]], limit_pct: float = 70.0) -> TyreEstimate:
    pts: list[tuple[int, list[float]]] = []
    compound = age = None
    for lap in _green_laps(laps):
        m = lap.get("meta") or {}
        w = m.get("wear_end")
        if w and len(w) == 4:
            pts.append((int(lap["lap_number"]), [float(x) for x in w]))
        compound = m.get("tyre_compound") or compound
        age = m.get("tyre_age_laps") if m.get("tyre_age_laps") is not None else age
    if not pts:
        return TyreEstimate(compound, age, None, None, None, None, limit_pct, 0)
    pts.sort()
    now = pts[-1][1]
    rates = None
    to_limit = None
    limiting = None
    if len(pts) >= 2:
        x = np.array([p[0] for p in pts], dtype=float)
        rates = []
        for k in range(4):
            y = np.array([p[1][k] for p in pts])
            slope = float(np.polyfit(x, y, 1)[0])
            rates.append(round(slope, 3))
        cands = [((limit_pct - now[k]) / rates[k], k) for k in range(4) if rates[k] > 1e-6]
        if cands:
            laps_left, k = min(cands)
            to_limit = round(max(0.0, laps_left), 1)
            limiting = WHEELS[k]
    return TyreEstimate(
        compound=compound,
        age_laps=age,
        wear_now_pct=[round(v, 1) for v in now],
        wear_rate_pct_per_lap=rates,
        laps_to_limit=to_limit,
        limiting_wheel=limiting,
        limit_pct=limit_pct,
        laps_used=len(pts),
    )


def pit_window(
    current_lap: int | None, total_laps: int | None, tyres: TyreEstimate, fuel: FuelEstimate
) -> dict[str, Any] | None:
    """Simple one-stop window from tyre life; None when not a race or data is insufficient."""
    if not current_lap or not total_laps or tyres.laps_to_limit is None:
        return None
    remaining = total_laps - current_lap + 1
    latest = current_lap + int(tyres.laps_to_limit)
    if latest >= total_laps:
        return {
            "stop_needed_for_tyres": False,
            "remaining_laps": remaining,
            "reason": f"tyres projected to stay under {tyres.limit_pct:.0f}% wear to the finish",
        }
    earliest = max(current_lap + 1, latest - 3)
    return {
        "stop_needed_for_tyres": True,
        "remaining_laps": remaining,
        "window_open_lap": earliest,
        "window_close_lap": latest,
        "limiting_wheel": tyres.limiting_wheel,
        "fuel_margin_laps": fuel.margin_laps,
    }
