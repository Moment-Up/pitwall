"""The live JSON blocks (``CarHealthView`` v1, ``RacecraftView`` v1): snapshot keys ``car_health`` / ``racecraft``.

Unknown is null (never 0); NaN never leaves (orjson writes it as null, and nothing here produces one). A section the
game cannot fill is ``{"available": false, "reason": <the games catalogue sentence>}``. Slow values only: the live
temperatures stay in the snapshot's ``frame``. Budget: ~1.5 kB (1.36-1.40 kB on the real F1 / F2 races; up to ~2 kB
with two recent calls and a lap of lock-ups in three corners: 2018 bytes on F2 Bahrain, before each call
carried its whole-second ``t_unix``) and ~0.6 kB.
"""

from __future__ import annotations

import functools
import math
from typing import TYPE_CHECKING, Any

from pitwall import games
from pitwall.carhealth import thresholds as T
from pitwall.carhealth.fuel import STATUS_NOT_SENT
from pitwall.carhealth.racecraft import REASON_NOT_RACE
from pitwall.carhealth.tyres import MODEL_SURFACE
from pitwall.model.telemetry import Game

if TYPE_CHECKING:
    from pitwall.carhealth.engine import CarHealthEngine

VERSION = 1
NOTE_SURFACE_ONLY = (
    "this session's tyre model is surface only: the game holds the inside temperatures and pressures fixed"
)
NOTE_SURFACE_UNKNOWN = "the tyre model setting is not known yet: surface temperatures"


def _r(v: float | None, nd: int = 1) -> float | None:
    if v is None or not math.isfinite(v):
        return None
    return round(v) if nd == 0 else round(v, nd)


@functools.lru_cache(maxsize=32)
def _reason(game: str | None, platform: str | None, packet_format: int | None, features: tuple[str, ...]) -> str:
    """The games catalogue's sentence for features this game does not send / Pitwall does not read."""
    if not game:
        return "no game detected yet"
    try:
        entry = games.entry(games.resolve(game, platform, games.variant_of(game, packet_format)))
    except Exception:  # a catalogue problem must never break the view
        entry = None
    sentence = games.capability_sentence(entry, features) if entry is not None else None
    return sentence or "not sent by this game"


def _unavailable(e: CarHealthEngine, *features: str) -> dict[str, Any]:
    info = e.info
    fmt = None if info is None else info.extra.get("packet_format")
    return {
        "available": False,
        "reason": _reason(
            None if e.game is None else e.game.value,
            None if info is None else info.platform.value,
            fmt if isinstance(fmt, int) else None,
            features,
        ),
    }


def _tyres(e: CarHealthEngine) -> dict[str, Any]:
    t = e.tyres
    model = e.tyre_model()
    f = e.frame
    if model is None or (f is not None and f.tyre_surface_temp_c is None):
        return _unavailable(e, "tyre_temps")
    if f is None:
        return {"available": False, "reason": "no car data yet"}
    pressure = t.pressure_now
    wear = t.wear_now
    wheels = []
    for k, b in enumerate(t.bands()):
        wheels.append(
            {
                "wheel": b["wheel"],
                "band": b["band"],
                "window_c": _r(b["window_c"], 0),  # whole degrees: the size budget, and no false precision
                "lap_median_c": _r(b["lap_median_c"], 0),
                "baseline_c": _r(b["baseline_c"], 0),
                "pressure_psi": None if pressure is None else _r(pressure[k]),
                "wear_pct": None if wear is None else _r(wear[k]),
            }
        )
    note = None
    if e.game is Game.F1_25 and model == MODEL_SURFACE:
        known = e.info is not None and e.info.extra.get("tyre_temperature_model") is not None
        note = NOTE_SURFACE_ONLY if known else NOTE_SURFACE_UNKNOWN
    return {
        "available": True,
        "model": model,
        "compound": t.compound,
        "age_laps": t.age_laps,
        "state": t.state,
        "armed": t.armed,
        "since": t.since,
        "index_c": _r(t.index_c),
        "baseline_c": _r(t.baseline_index()),
        "baseline_source": t.baseline_source(),
        "wheels": wheels,
        "pressures_fixed": e.game is Game.F1_25 and model == MODEL_SURFACE,
        "note": note,
        "tier": "heuristic",
    }


def _brakes(e: CarHealthEngine) -> dict[str, Any]:
    if not e.temps.brakes_seen:
        return (
            _unavailable(e, "brake_temps") if e.frame is not None else {"available": False, "reason": "no car data yet"}
        )
    return e.temps.brakes_view()


def _engine(e: CarHealthEngine) -> dict[str, Any]:
    if not e.temps.engine_seen:
        return (
            _unavailable(e, "engine_temp") if e.frame is not None else {"available": False, "reason": "no car data yet"}
        )
    return e.temps.engine_view()


def _slip(e: CarHealthEngine) -> dict[str, Any]:
    s = e.slip
    if not s.seen:
        if e.frame is None:
            return {"available": False, "reason": "no car data yet"}
        reason = (
            "lock-ups and wheelspin need the game's wheel slip (F1 sends it; other games are not read for it yet)"
            if e.game is not Game.F1_25
            else "no wheel slip data yet"
        )
        return {"available": False, "reason": reason}
    applicable = s.abs_on is False
    last = s.last_lap
    return {
        "available": True,
        "abs": s.abs_on,
        "tc": s.tc,
        "lockups_applicable": applicable,
        "last_lap": None
        if last is None
        else {
            "lap": last["lap"],
            "lockups": last["lockups"],
            "lockup_s": last["lockup_s"],
            "wheelspin": last["wheelspin"],
            "wheelspin_s": last["wheelspin_s"],
            "corners": [{k: c[k] for k in ("corner", "text", "lockups", "wheelspin")} for c in last["corners"][:3]],
        },
        "current": s.current(),
        "session": {"laps": s.session_laps, "lockups": s.session_lockups, "wheelspin": s.session_wheelspin},
        "reason": None if applicable else "ABS is on: lock-ups are not counted",
    }


def _fuel(e: CarHealthEngine) -> dict[str, Any] | None:
    if e.game is Game.F1_25 or e.game is None:
        return None  # race strategy and the per-lap facts own F1 fuel
    if e.fuel is None:
        return {
            "source": None,
            "status": STATUS_NOT_SENT,
            "fraction": None,
            "per_lap": None,
            "laps_of_fuel": None,
            "laps_used": None,
            "tier": None,
            "reason": _unavailable(e, "fuel")["reason"],
        }
    reason = games.GT7_FUEL_REASON if e.game is Game.GT7 and not e.fuel.enabled else None
    return e.fuel.view(reason)


def build_view(e: CarHealthEngine, *, thresholds: bool = False) -> dict[str, Any]:
    """The live ``CarHealthView``; ``thresholds`` (the API, not the snapshot: they never change) adds the table."""
    info = e.info
    out = {
        "version": VERSION,
        "session_id": e.session_id,
        "game": None if e.game is None else e.game.value,
        "synthetic": bool(info is not None and info.extra.get("synthetic")),
        "tyres": _tyres(e),
        "brakes": _brakes(e),
        "engine": _engine(e),
        "slip": _slip(e),
        "fuel": _fuel(e),
        "calls": [
            {
                "id": c.id,
                "topic": c.topic,
                "level": c.level,
                "text": c.text,
                "text_simple": c.text_simple,
                "lap": c.lap,
                "t_unix": round(c.t_unix),  # whole seconds: the dashboard's TYRES COLD chip times itself from it
            }
            for c in e.recent_calls
        ],
    }
    if thresholds:
        out["thresholds"] = list(T.THRESHOLDS)
    return out


def build_racecraft_view(e: CarHealthEngine) -> dict[str, Any]:
    if not (e.f1 and e.race) or e.ended:
        reason = "the session ended" if e.ended else REASON_NOT_RACE
        return off_racecraft(e.session_id, reason)
    rc = e.racecraft.compute()
    return {
        "version": VERSION,
        "session_id": e.session_id,
        "mode": "race",
        "reason": rc["reason"],
        "corners_source": None if e.racecraft.seg is None else "learned",
        "ahead": rc["ahead"],
        "behind": rc["behind"],
    }


def off_racecraft(session_id: str | None, reason: str) -> dict[str, Any]:
    return {
        "version": VERSION,
        "session_id": session_id,
        "mode": "off",
        "reason": reason,
        "corners_source": None,
        "ahead": None,
        "behind": None,
    }


def with_thresholds(view: dict[str, Any]) -> dict[str, Any]:
    return {**view, "thresholds": list(T.THRESHOLDS)}


def off_car_health(session_id: str | None, reason: str) -> dict[str, Any]:
    """The ``/api/car-health/live`` shape without a live session or before the worker published one."""
    na = {"available": False, "reason": reason}
    return {
        "version": VERSION,
        "session_id": session_id,
        "game": None,
        "synthetic": False,
        "tyres": na,
        "brakes": na,
        "engine": na,
        "slip": na,
        "fuel": None,
        "calls": [],
        "thresholds": list(T.THRESHOLDS),
    }
