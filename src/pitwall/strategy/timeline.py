"""Review > Strategy: one stored race session as a ``StrategyTimeline`` (``GET /api/sessions/{sid}/strategy``).

Built only from what the strategy worker stored (``strategy_laps``, ``pit_stops``) and the session row; nothing is
recomputed from traces. Sessions that are not races, races of another game, races recorded before strategy tracking
and race fragments that ended before a lap was complete (a short split) come back with ``available: false`` and the
reason in words.
"""

from __future__ import annotations

import sqlite3
import statistics
from typing import Any

from pitwall.storage import repo

REASON_NOT_RACE = "not a race"
REASON_OLD = "recorded before strategy tracking"
REASON_NO_LAPS_YET = "no strategy laps yet"
REASON_NO_COMPLETE_LAP = "no complete lap in this session"  # ended before a lap was done (e.g. a short split)
REASON_NOT_F1 = "race strategy needs F1 25 timing"  # as strategy.engine.REASON_NOT_F1
F1_GAMES = ("f1_25",)
NEUTRAL = ("full", "virtual")


def _s(ms: Any) -> float | None:
    return None if not isinstance(ms, int | float) else round(ms / 1000, 2)


def pit_stop_row(r: dict[str, Any]) -> dict[str, Any]:
    """``PitStopRow`` (seconds) from a ``pit_stops`` row (milliseconds)."""
    return {
        "car_index": r["car_index"],
        "is_player": bool(r["is_player"]),
        "entry_lap": r["entry_lap"],
        "exit_lap": r.get("exit_lap"),
        "lane_time_s": _s(r.get("lane_time_ms")),
        "stationary_s": _s(r.get("stationary_ms")),
        "pit_loss_s": _s(r.get("pit_loss_ms")),
        "neutralised": r.get("neutralised"),
        "excluded": r.get("excluded"),
        "compound_before": r.get("compound_before"),
        "compound_after": r.get("compound_after"),
    }


def _max_wear(rec: dict[str, Any]) -> float | None:
    w = rec.get("wear_pct")
    vals = [float(x) for x in w if isinstance(x, int | float)] if isinstance(w, list) else []
    return max(vals) if vals else None


def stints(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consecutive laps on one set: a new stint when the compound changes or the tyre age goes down."""
    out: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []

    def close() -> None:
        if not cur:
            return
        first, last = cur[0], cur[-1]
        n = int(last["lap"]) - int(first["lap"]) + 1
        w0, w1 = _max_wear(first), _max_wear(last)
        green = [
            int(r["lap_time_ms"])
            for r in cur
            if isinstance(r.get("lap_time_ms"), int)
            and not r.get("pit")
            and r.get("safety_car") in (None, "none")
            and r.get("lap") != 1
        ]
        out.append(
            {
                "compound": last.get("compound"),
                "start_lap": int(first["lap"]),
                "end_lap": int(last["lap"]),
                "laps": n,
                "wear_end_pct": w1,
                "wear_rate_pct_per_lap": round((w1 - w0) / (n - 1), 2)
                if w0 is not None and w1 is not None and n > 1
                else None,
                "median_lap_ms": round(statistics.median(green)) if green else None,
            }
        )

    for r in records:
        if cur:
            prev = cur[-1]
            new_compound = r.get("compound") is not None and r.get("compound") != prev.get("compound")
            age, prev_age = r.get("tyre_age_laps"), prev.get("tyre_age_laps")
            reset = isinstance(age, int) and isinstance(prev_age, int) and age < prev_age
            if new_compound or reset:
                close()
                cur = []
        cur.append(r)
    close()
    return out


def safety_car_periods(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        sc = r.get("safety_car")
        if sc not in NEUTRAL:
            continue
        lap = int(r["lap"])
        if out and out[-1]["status"] == sc and out[-1]["end_lap"] == lap - 1:
            out[-1]["end_lap"] = lap
        else:
            out.append({"status": sc, "start_lap": lap, "end_lap": lap})
    return out


def weather_changes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        w = r.get("weather")
        if not out or out[-1]["weather"] != w:
            out.append({"lap": int(r["lap"]), "weather": w, "rain_pct": r.get("rain_pct")})
    return out


def pit_loss(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    losses = [
        int(r["pit_loss_ms"])
        for r in rows
        if isinstance(r.get("pit_loss_ms"), int) and not r.get("excluded") and not r.get("neutralised")
    ]
    if not losses:
        return None
    return {
        "median_s": round(statistics.median(losses) / 1000, 1),
        "range": {"low": round(min(losses) / 1000, 1), "high": round(max(losses) / 1000, 1)},
        "n": len(losses),
    }


def _no_records_reason(c: sqlite3.Connection, session_id: str, s: dict[str, Any]) -> str:
    """Why a race session has no strategy records. The engine records every complete lap of an F1 race, so an ended
    F1 race with complete laps but no records was recorded by an older Pitwall."""
    if s.get("game") not in F1_GAMES:
        return REASON_NOT_F1
    if s.get("ended_unix") is None:
        return REASON_NO_LAPS_YET
    if not repo.has_complete_lap(c, session_id):
        return REASON_NO_COMPLETE_LAP
    return REASON_OLD


def build_timeline(c: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    """``StrategyTimeline`` of a stored session; None when the session does not exist."""
    s = repo.get_session(c, session_id)
    if s is None:
        return None
    records = sorted(repo.list_strategy_laps(c, session_id), key=lambda r: int(r.get("lap") or 0))
    rows = repo.list_pit_stops(c, session_id)
    is_race = s.get("session_type") == "race"
    available = is_race and bool(records)
    reason = None
    if not is_race:
        reason = REASON_NOT_RACE
    elif not records:
        reason = _no_records_reason(c, session_id, s)
    total = next((r.get("total_laps") for r in reversed(records) if isinstance(r.get("total_laps"), int)), None)
    grid = next((r.get("grid_position") for r in records if isinstance(r.get("grid_position"), int)), None)
    finish = next((r.get("position") for r in reversed(records) if isinstance(r.get("position"), int)), None)
    calls = [
        {**call, "lap": call.get("lap", r.get("lap"))}
        for r in records
        for call in (r.get("calls") or [])
        if isinstance(call, dict)
    ]
    return {
        "session_id": session_id,
        "available": available,
        "reason": reason,
        "total_laps": total,
        "grid_position": grid,
        "finish_position": finish,
        "laps": records,
        "stints": stints(records),
        "stops": [pit_stop_row(r) for r in rows if r["is_player"]],
        "field_stops": [pit_stop_row(r) for r in rows if not r["is_player"]],
        "pit_loss": pit_loss(rows),
        "safety_car_periods": safety_car_periods(records),
        "weather": weather_changes(records),
        "calls": calls,
    }
