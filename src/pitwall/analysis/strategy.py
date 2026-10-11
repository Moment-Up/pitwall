"""Deterministic fuel / tyre / pit-window calculations. The AI explains these numbers; it never computes them.

The race strategy engine (``pitwall.strategy``) uses the keyword-only extensions below; the defaults keep the
original behaviour for ``core.report`` and ``carsetup.experiments``:

* ``tyre_estimate(..., stint_only=True)`` projects wear over the *current stint* only (a pit stop or a tyre change
  starts a new one), from the sum of per-lap wear increments, with bounds for whole-percent wear quantisation (real
  F1 25 on PS5 sends integer wear) and an ``enough_laps`` gate.
* ``pit_window(..., new_set_life_laps=, game_laps_left=, ideal_lap=)`` closes the window at the earlier of the
  measured projection and the game's own laps-left figure, opens it when a new set reaches the flag, and reports a
  two-stop case; ``ideal_stop_lap`` is the game-model ideal in-lap (heuristic, ``[H]``).
* ``fit_burn_model`` fits fuel burn against throttle (``[R]`` gates calibrated on a real Austria race) and
  ``lift_coast_target`` turns a fuel deficit into seconds of lift per lap. Lifting is always *before* the normal
  braking point with braking at the same point: nothing here ever suggests braking later.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Collection, Sequence
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
    laps_remaining_in_race: float | None
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
    # --- race strategy (stint_only=True) ---
    stint_start_lap: int | None = None
    rate_low_pct_per_lap: float | None = None  # limiting wheel, whole-percent quantisation bounds
    rate_high_pct_per_lap: float | None = None
    laps_to_limit_low: float | None = None  # at rate_high
    laps_to_limit_high: float | None = None  # at rate_low (None when rate_low is 0)
    enough_laps: bool = True  # stint_only: >= MIN_STINT_LAPS green laps and >= MIN_WEAR_PP of wear


def _green_laps(laps: list[dict[str, Any]], exclude_laps: Collection[int] = ()) -> list[dict[str, Any]]:
    return [
        lap
        for lap in laps
        if not (set(lap.get("flags") or []) & EXCLUDE_FLAGS) and lap.get("lap_number") not in exclude_laps
    ]


def fuel_estimate(
    laps: list[dict[str, Any]],
    fuel_now_kg: float | None,
    game_estimate_laps: float | None,
    laps_remaining_in_race: float | None,
    *,
    exclude_laps: Collection[int] = frozenset(),
) -> FuelEstimate:
    """``exclude_laps``: lap numbers that are not representative (safety car, lap 1) besides the flagged ones."""
    used = []
    for lap in _green_laps(laps, exclude_laps):
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
WHEEL_CODES = ("FL", "FR", "RL", "RR")

# --- race strategy (stint projection) ---------------------------------------------------------------------------
WEAR_LIMIT_PCT = 70.0  # [H] the wear the projection runs to (existing)
STINT_BREAK_PP = 2.0  # [R] a wheel starting a lap this far below the previous lap's end = new tyres (integer wear)
MIN_STINT_LAPS = 3  # [H] green laps of the stint before a projection is made
MIN_WEAR_PP = 2.0  # [H] ... and at least this much summed wear (whole-percent steps)
NEGATIVE_INCREMENT_PP = -0.5  # a lap whose wear goes down by more than this is not a wear lap (tyre change)


def _wear4(v: Any) -> list[float] | None:
    if isinstance(v, list | tuple) and len(v) == 4 and all(isinstance(x, int | float) for x in v):
        return [float(x) for x in v]
    return None


def stint_start_lap(laps: Sequence[dict[str, Any]]) -> int | None:
    """First lap of the current stint: the last lap whose compound differs from the previous lap's, whose tyre age
    went down, or on which any wheel started ``STINT_BREAK_PP`` below the previous lap's end. None without laps."""
    ordered = sorted((lap for lap in laps if lap.get("lap_number") is not None), key=lambda lap: int(lap["lap_number"]))
    if not ordered:
        return None
    start = int(ordered[0]["lap_number"])
    for prev, cur in itertools.pairwise(ordered):
        pm, cm = prev.get("meta") or {}, cur.get("meta") or {}
        pc, cc = pm.get("tyre_compound"), cm.get("tyre_compound")
        pa, ca = pm.get("tyre_age_laps"), cm.get("tyre_age_laps")
        pe, cs = _wear4(pm.get("wear_end")), _wear4(cm.get("wear_start"))
        broke = (pc is not None and cc is not None and pc != cc) or (
            isinstance(pa, int) and isinstance(ca, int) and ca < pa
        )
        if not broke and pe is not None and cs is not None:
            broke = any(s < e - STINT_BREAK_PP for s, e in zip(cs, pe, strict=True))
        if broke:
            start = int(cur["lap_number"])
    return start


def tyre_estimate(
    laps: list[dict[str, Any]],
    limit_pct: float = WEAR_LIMIT_PCT,
    *,
    stint_only: bool = False,
    exclude_laps: Collection[int] = frozenset(),
) -> TyreEstimate:
    if stint_only:
        return _stint_tyre_estimate(laps, limit_pct, exclude_laps)
    pts: list[tuple[int, list[float]]] = []
    compound = age = None
    for lap in _green_laps(laps, exclude_laps):
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


def _stint_tyre_estimate(laps: list[dict[str, Any]], limit_pct: float, exclude_laps: Collection[int]) -> TyreEstimate:
    """Wear projection over the current stint: per wheel, rate = sum of (wear_end - wear_start) over the stint's green
    laps / n. Consecutive laps telescope, so the whole-percent quantisation of the game's wear costs at most one
    step per run of consecutive green laps (a safety-car, pit or flashback lap in between starts another run):
    ``rate_low/high = (sum -/+ runs) / n`` bound the limiting wheel's rate."""
    start = stint_start_lap(laps)
    ordered = sorted((lap for lap in laps if lap.get("lap_number") is not None), key=lambda lap: int(lap["lap_number"]))
    stint = [lap for lap in ordered if start is not None and int(lap["lap_number"]) >= start]
    compound = age = None
    now: list[float] | None = None
    for lap in stint:
        m = lap.get("meta") or {}
        compound = m.get("tyre_compound") or compound
        age = m.get("tyre_age_laps") if m.get("tyre_age_laps") is not None else age
        w = _wear4(m.get("wear_end"))
        if w is not None:
            now = w
    sums = [0.0, 0.0, 0.0, 0.0]
    n = 0
    runs = 0  # runs of consecutive laps summed: each costs up to one whole-percent step
    prev: int | None = None
    for lap in _green_laps(stint, exclude_laps):
        m = lap.get("meta") or {}
        ws, we = _wear4(m.get("wear_start")), _wear4(m.get("wear_end"))
        if ws is None or we is None:
            continue
        inc = [e - s for s, e in zip(ws, we, strict=True)]
        if any(d < NEGATIVE_INCREMENT_PP for d in inc):
            continue
        sums = [a + d for a, d in zip(sums, inc, strict=True)]
        n += 1
        num = int(lap["lap_number"])
        if prev is None or num != prev + 1:
            runs += 1
        prev = num
    base = TyreEstimate(
        compound=compound,
        age_laps=age,
        wear_now_pct=None if now is None else [round(v, 1) for v in now],
        wear_rate_pct_per_lap=None,
        laps_to_limit=None,
        limiting_wheel=None,
        limit_pct=limit_pct,
        laps_used=n,
        stint_start_lap=start,
        enough_laps=False,
    )
    if n == 0 or now is None:
        return base
    rates = [s / n for s in sums]
    base.wear_rate_pct_per_lap = [round(r, 3) for r in rates]
    base.enough_laps = n >= MIN_STINT_LAPS and max(sums) >= MIN_WEAR_PP
    cands = [((limit_pct - now[k]) / rates[k], k) for k in range(4) if rates[k] > 1e-6]
    if not cands:
        return base
    laps_left, k = min(cands)
    base.limiting_wheel = WHEELS[k]
    rate_low = max(0.0, (sums[k] - runs) / n)
    rate_high = (sums[k] + runs) / n
    base.rate_low_pct_per_lap = round(rate_low, 3)
    base.rate_high_pct_per_lap = round(rate_high, 3)
    if base.enough_laps:
        left = max(0.0, limit_pct - now[k])
        base.laps_to_limit = round(max(0.0, laps_left), 1)
        base.laps_to_limit_low = round(left / rate_high, 1)
        base.laps_to_limit_high = round(left / rate_low, 1) if rate_low > 1e-9 else None
    return base


def ideal_stop_lap(current_lap: int, total_laps: int, d0_s: float | None, g_s_per_lap2: float | None) -> int | None:
    """[H] Game-model ideal in-lap: laps ``k`` still to drive on the old set minimise
    ``k*d0 + g*k(k+1)/2 + g*(R-k)(R-k-1)/2`` (R = laps after this one): the old set gives away ``d0`` now and ``g`` more
    every lap, the new one degrades by ``g`` a lap too. Pit loss does not depend on ``k``. Unclamped (``pit_window``
    clamps it to the window); None without a usable degradation slope."""
    if d0_s is None or g_s_per_lap2 is None or g_s_per_lap2 <= 0 or not (math.isfinite(d0_s)):
        return None
    r = total_laps - current_lap
    k = round((g_s_per_lap2 * (r - 1) - d0_s) / (2 * g_s_per_lap2))
    return current_lap + int(k)


def pit_window(
    current_lap: int | None,
    total_laps: int | None,
    tyres: TyreEstimate,
    fuel: FuelEstimate,
    *,
    new_set_life_laps: float | None = None,
    game_laps_left: float | None = None,
    ideal_lap: int | None = None,
    in_lap_now: bool = False,
) -> dict[str, Any] | None:
    """One-stop window from tyre life; None when not a race or data is insufficient. "Box on lap s" means lap s is
    the in-lap. The window closes at the earlier of the measured projection (``tyres.laps_to_limit``) and the game's
    laps-left figure (``close_source``); it opens when a new set reaches the flag (``new_set_life_laps``), else three
    laps before the close (heuristic). A window that would open after it closes is a two-stop case.

    ``in_lap_now``: the current lap can still be the in-lap (the live strategy engine), so the heuristic window may
    open on it; by default it opens on the next lap at the earliest. ``overdue``: the tyres are at or past the limit
    already (the window is "this lap" and nothing later)."""
    if not current_lap or not total_laps:
        return None
    measured = tyres.laps_to_limit
    cands: list[tuple[float, str]] = []
    if measured is not None:
        cands.append((measured, "measured"))
    if game_laps_left is not None:
        cands.append((float(game_laps_left), "game"))
    if not cands:
        return None
    life, source = min(cands, key=lambda c: (c[0], c[1] != "measured"))
    remaining = total_laps - current_lap + 1
    latest = current_lap + math.floor(life)
    base: dict[str, Any] = {
        "remaining_laps": remaining,
        "close_source": source,
        "new_set_life_laps": new_set_life_laps,
        "game_laps_left": game_laps_left,
        "overdue": life <= 0,
    }
    if latest >= total_laps:
        return {
            "stop_needed_for_tyres": False,
            **base,
            "two_stops": False,
            "ideal_lap": None,
            "reason": f"tyres projected to stay under {tyres.limit_pct:.0f}% wear to the finish",
        }
    if new_set_life_laps is not None:
        earliest = max(current_lap, total_laps - math.floor(new_set_life_laps))
        tier = "game"
    else:
        earliest = max(current_lap + (0 if in_lap_now else 1), latest - 3)
        tier = "heuristic"
    two_stops = earliest > latest
    if two_stops:
        earliest = current_lap
    ideal = None
    if ideal_lap is not None:
        ideal = min(max(ideal_lap, earliest), latest)
    return {
        "stop_needed_for_tyres": True,
        **base,
        "window_open_lap": earliest,
        "window_close_lap": latest,
        "limiting_wheel": tyres.limiting_wheel,
        "fuel_margin_laps": fuel.margin_laps,
        "two_stops": two_stops,
        "ideal_lap": ideal,
        "tier": "game" if source == "game" else tier,
    }


# --- race strategy: fuel burn and lift-and-coast --------------------------------------------------------------------
BURN_MIN_WINDOWS = 120  # [R] gates calibrated on the real 71-lap Austria race (734 windows, R^2 0.85)
BURN_MIN_LOW = 20  # windows with mean throttle < 0.2
BURN_MIN_HIGH = 20  # windows with mean throttle > 0.9
BURN_MIN_R2 = 0.6
LNC_TARGET_MARGIN_LAPS = 0.1  # [H] lift and coast aims for this margin at the flag
LNC_MAX_S = 6.0  # [H] more lift than this per lap is not a realistic save


@dataclass(slots=True, frozen=True)
class BurnModel:
    """Fuel burn rate (kg/s) = ``b0 + b1 * throttle``: ``b1`` is what full throttle costs over coasting."""

    b0: float
    b1: float
    r2: float
    windows: int

    @property
    def full_throttle_kg_per_s(self) -> float:
        return self.b0 + self.b1


def fit_burn_model(windows: Sequence[tuple[float, float]]) -> BurnModel | None:
    """Least squares over ``(rate_kg_per_s, mean_throttle)`` windows; None unless the gates hold (enough windows,
    enough of them lifting and flat out, a positive throttle term and a good fit)."""
    if len(windows) < BURN_MIN_WINDOWS:
        return None
    arr = np.asarray(windows, dtype=np.float64)
    rate, thr = arr[:, 0], arr[:, 1]
    if int((thr < 0.2).sum()) < BURN_MIN_LOW or int((thr > 0.9).sum()) < BURN_MIN_HIGH:
        return None
    a = np.column_stack([np.ones_like(thr), thr])
    coef, *_ = np.linalg.lstsq(a, rate, rcond=None)
    b0, b1 = float(coef[0]), float(coef[1])
    pred = a @ coef
    ss_res = float(((rate - pred) ** 2).sum())
    ss_tot = float(((rate - rate.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    if b1 <= 0 or r2 < BURN_MIN_R2 or not (math.isfinite(b0) and math.isfinite(b1)):
        return None
    return BurnModel(b0=b0, b1=b1, r2=r2, windows=len(windows))


@dataclass(slots=True, frozen=True)
class LiftCoast:
    save_kg_per_lap: float
    seconds_per_lap: float  # of lifting off full throttle (before the normal braking point)
    feasible: bool


def lift_coast_target(
    margin_laps: float | None,
    per_lap_kg: float | None,
    laps_remaining: float | None,
    model: BurnModel | None,
    target_margin_laps: float = LNC_TARGET_MARGIN_LAPS,
) -> LiftCoast | None:
    """[H] Seconds of lift per lap that bring the fuel margin to ``target_margin_laps``: the fuel still needed, spread
    over the laps left, divided by what full throttle burns over coasting (``model.b1``). The driver lifts *before*
    the braking point and brakes at the same point. None when no saving is needed or an input is unknown."""
    if margin_laps is None or per_lap_kg is None or laps_remaining is None or model is None or laps_remaining <= 0:
        return None
    need_kg = (target_margin_laps - margin_laps) * per_lap_kg
    if need_kg <= 0:
        return None
    save = need_kg / laps_remaining
    seconds = save / model.b1
    return LiftCoast(save_kg_per_lap=round(save, 3), seconds_per_lap=round(seconds, 1), feasible=seconds <= LNC_MAX_S)
