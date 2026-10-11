"""The live ``StrategyView`` JSON (``snapshot["strategy"]``, ``GET /api/strategy/live``).

Contract (``web-react/src/lib/strategy/types.ts`` mirrors it; ``version`` 1): every key is always present, unknown
values are ``null`` (never ``NaN``), units live in the key names, and tiers say where a number comes from:
``measured`` (this session's data), ``game`` (the game's own estimate) or ``heuristic`` (a rule of thumb). Kept
small because it rides every live snapshot: about 2-3.5 kB in a race with three calls shown (measured as compact
JSON: the real Austria and Monza excerpts 2.0-2.1 kB, the full Austria race up to 2.4 kB, the synthetic race with a
rain forecast and three calls with their plain words 3.1-3.6 kB).

The fuel margin, status and lift and coast are the ones judged at the last lap line (``Derived.fuel_line``): burn
within a lap is uneven, so a per-tick margin would swing (and the tile with it) while the radio judges at the line.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from pitwall.analysis.strategy import MIN_STINT_LAPS, WHEEL_CODES, WHEELS
from pitwall.strategy.gaps import car_gap_view

if TYPE_CHECKING:
    from pitwall.strategy.calls import StrategyCall
    from pitwall.strategy.engine import StrategyEngine

VIEW_VERSION = 1
NOTE_NOT_ENOUGH_LAPS = f"not enough laps on this set yet: {MIN_STINT_LAPS} green laps needed"
NOTE_NO_TREND = "not enough laps for a trend yet"
NOTE_NO_PIT_LOSS = "no pit stop measured in this race yet"


def clean(v: Any) -> Any:
    """NaN / infinity -> None, recursively (strict JSON, as the API's orjson responses)."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [clean(x) for x in v]
    return v


def off_view(reason: str | None, session_id: str | None = None, synthetic: bool = False) -> dict[str, Any]:
    """The view when strategy does not run (no live session, qualifying, time trial, another game)."""
    return {
        "version": VIEW_VERSION,
        "mode": "off",
        "reason": reason,
        "session_id": session_id,
        "synthetic": synthetic,
        "lap": None,
        "total_laps": None,
        "laps_remaining": None,
        "position": None,
        "cars": None,
        "gaps": None,
        "tyres": None,
        "fuel": None,
        "pit": None,
        "safety_car": None,
        "weather": None,
        "calls": [],
    }


def _r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None or not math.isfinite(v) else round(float(v), nd)


def build_view(e: StrategyEngine) -> dict[str, Any]:
    if e.mode == "off":
        return off_view(e.reason, e.session_id, e.synthetic)
    d = e.d
    race = e.mode == "race"
    me = e.player
    out = off_view(None, e.session_id, e.synthetic)
    out.update(
        mode=e.mode,
        lap=d.lap,
        total_laps=e.total_laps if race else None,
        laps_remaining=_r(d.laps_remaining),
        position=None if me is None or not race else me.position,
        cars=None if e.timing is None or not race else len(e.timing.cars),
        tyres=_tyres(e),
        fuel=_fuel(e),
        weather=e.weather.view(d.lap_time_s),
    )
    if race:
        out.update(gaps=_gaps(e), pit=_pit(e), safety_car=_safety_car(e))
        out["calls"] = [call_entry(c) for c in e.recent_calls]
    return clean(out)  # type: ignore[no-any-return]


def call_entry(c: StrategyCall) -> dict[str, Any]:
    """A call as the view and the lap records carry it: the words (and the plain ones), who it is for (a call for
    experienced drivers is never shown to a driver with simple wording) and how long it holds (``ttl_s``)."""
    return {
        "id": c.id,
        "topic": c.topic,
        "level": c.level,
        "text": c.text,
        "text_simple": c.text_simple,
        "audience": c.audience,
        "lap": c.lap,
        "ttl_s": round(c.ttl_s, 1),
        "t_unix": round(c.t_unix, 3),
    }


def _gaps(e: StrategyEngine) -> dict[str, Any] | None:
    if e.player is None:
        return None
    g = e.gaps
    ahead = car_gap_view(g, g.ahead, e.d.laps_remaining, e.drs_enabled, e.packet_format)
    behind = car_gap_view(g, g.behind, e.d.laps_remaining, e.drs_enabled, e.packet_format)
    note = None
    if (ahead is not None and ahead["trend_s_per_lap"] is None) or (
        behind is not None and behind["trend_s_per_lap"] is None
    ):
        note = NOTE_NO_TREND
    if e.player.position == 1:
        note = "leading" if note is None else f"leading; {note}"
    return {"ahead": ahead, "behind": behind, "leader_s": _r(g.leader_s, 3), "note": note}


def _tyres(e: StrategyEngine) -> dict[str, Any] | None:
    f = e.frame
    te = e.d.tyres
    if f is None and te is None:
        return None
    wear = None if f is None or f.tyre_wear_pct is None else [round(w, 1) for w in f.tyre_wear_pct.as_tuple()]
    limiting = None
    rate = rng = to_limit = None
    enough = False
    stint_laps = 0
    if te is not None:
        enough = te.enough_laps
        if te.limiting_wheel is not None:
            k = WHEELS.index(te.limiting_wheel)
            limiting = WHEEL_CODES[k]
            if te.wear_rate_pct_per_lap is not None:
                rate = _r(te.wear_rate_pct_per_lap[k], 3)
            if te.rate_low_pct_per_lap is not None and te.rate_high_pct_per_lap is not None:
                rng = {"low": _r(te.rate_low_pct_per_lap, 3), "high": _r(te.rate_high_pct_per_lap, 3)}
        if enough and te.laps_to_limit_low is not None:
            to_limit = {"low": _r(te.laps_to_limit_low, 1), "high": _r(te.laps_to_limit_high, 1)}
        if te.stint_start_lap is not None and e.d.lap is not None:
            stint_laps = max(0, e.d.lap - te.stint_start_lap + 1)
    gain = e.d.game_gain
    new_set = None
    if gain is not None:
        new_set = {"compound": gain[0], "gain_s": _r(gain[1], 3), "deg_s_per_lap": _r(gain[2], 4), "tier": "game"}
    return {
        "compound": None if f is None else f.tyre_compound,
        "age_laps": None if f is None else f.tyre_age_laps,
        "stint_laps": stint_laps,
        "wear_pct": wear,
        "limiting_wheel": limiting,
        "rate_pct_per_lap": rate,
        "rate_range": rng,
        "limit_pct": te.limit_pct if te is not None else 70.0,
        "laps_to_limit": to_limit,
        "enough_laps": enough,
        "note": None if enough else NOTE_NOT_ENOUGH_LAPS,
        "game_laps_left": e.d.game_laps_left,
        "game_usable_life": e.game_tyres.usable_life(),
        "new_set": new_set,
    }


def _fuel(e: StrategyEngine) -> dict[str, Any] | None:
    d = e.d
    fe = d.fuel_line or d.fuel  # judged at the last lap line (the tank stays live)
    if fe is None:
        return None
    lnc = d.lift_line
    burn = d.burn
    return {
        "fuel_kg": _r(d.fuel_now, 2),
        "per_lap_kg": fe.per_lap_kg,
        "laps_used": fe.laps_used,
        "margin_laps": fe.margin_laps,
        "margin_kg": fe.margin_kg,
        "game_margin_laps": _r(d.game_margin, 2),
        "status": d.fuel_line_status if d.fuel_line is not None else d.fuel_status,
        "lift_coast": None
        if lnc is None
        else {
            "save_kg_per_lap": lnc.save_kg_per_lap,
            "seconds_per_lap": lnc.seconds_per_lap,
            "feasible": lnc.feasible,
            "corners": list(d.lift_line_corners),
        },
        "burn_model": None
        if burn is None
        else {
            "full_throttle_kg_per_s": _r(burn.full_throttle_kg_per_s, 4),
            "r2": _r(burn.r2, 2),
            "windows": burn.windows,
        },
    }


def _pit(e: StrategyEngine) -> dict[str, Any]:
    d = e.d
    me = e.player
    win = d.window
    window = None
    if win is not None and win.get("stop_needed_for_tyres"):
        window = {
            "open_lap": win["window_open_lap"],
            "close_lap": win["window_close_lap"],
            "ideal_lap": win.get("ideal_lap"),
            "close_source": win["close_source"],
            "tier": win.get("tier", "heuristic"),
            "overdue": bool(win.get("overdue")),  # at or past the wear limit already: the window is this lap
        }
    extra = e.info.extra if e.info is not None else {}
    gi, gl = extra.get("pit_window_ideal_lap"), extra.get("pit_window_latest_lap")
    game_window = {"ideal_lap": gi, "latest_lap": gl} if isinstance(gi, int) and isinstance(gl, int) and gl else None
    sc = d.loss_sc
    note = None
    if d.stop_needed is None:
        note = NOTE_NOT_ENOUGH_LAPS
    elif d.loss_green is None:
        note = NOTE_NO_PIT_LOSS
    return {
        "stops_done": None if me is None else me.num_pit_stops,  # unknown before the first timing tick
        "stop_needed": d.stop_needed,
        "two_stops": None if win is None or not win.get("stop_needed_for_tyres") else bool(win.get("two_stops")),
        "window": window,
        "game_window": game_window,
        "pit_loss": d.loss_green,
        "pit_loss_sc": None
        if sc.get("full_s") is None and sc.get("virtual_s") is None
        else {"full_s": sc.get("full_s"), "virtual_s": sc.get("virtual_s"), "tier": sc.get("tier", "heuristic")},
        "pit_entry_m": e.pits.pit_entry_m(),
        "rejoin": d.rejoin,
        "undercut_ahead": d.undercut,
        "undercut_threat": d.threat,
        "neighbour_stop": d.neighbour,
        "note": note,
    }


def _safety_car(e: StrategyEngine) -> dict[str, Any]:
    status = e.sc.status
    return {
        "status": status if status in ("none", "full", "virtual", "formation_lap") else None,
        "since_lap": e.sc.since_lap if e.sc.neutral is not None else None,
        "box": e.d.sc_box,
    }
