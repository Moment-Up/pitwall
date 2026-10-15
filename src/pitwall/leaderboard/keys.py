"""Board keys (pure): which laps race each other on a family board.

A board key is game + track + layout + car + session category + conditions + assist class. Every part is exact, and
an UNKNOWN value is its own bucket, never a wildcard: a lap whose ABS setting was not sent is on the "ABS unknown"
board, never on the "ABS on" one. (Reference matching, ``core.coachref``, stays looser: there unknown matches
anything, because a lap to drive against is better than none; a ranking must not compare unlike laps.)

* layout - a track's stored lengths within ``repo.BESTS_LENGTH_TOLERANCE`` (3 %) of a group's shortest length are
  one layout (``layout_clusters``), named by that length in whole metres; an unknown length is its own layout.
* car - the exact car id (an unknown car is its own board). F1 games add the car class family (``carclass``: F1, F2,
  other) and the "equal car performance" setting, each unknown until the game sent it.
* category - ``time_trial``, ``qualifying``, ``race`` or ``practice``; else ``unknown`` (GT7 and AC send none).
* conditions - ``dry`` or ``wet`` from the game's weather (light rain, heavy rain and storm are wet, as
  ``analysis.compare.check_compatibility``), else ``unknown``.
* assist class - F1: braking assist, gearbox and racing line from the Session packet, trusted only once its tail is
  filled (gearbox 1-3: F1 25 sends an unfilled tail for the first ~1.5 s of a session), and ABS and traction control
  from the lap itself (``LapTrace.meta``: the value on 90 % of the moving frames). AC: ABS and TC on / off. GT7,
  Forza and the other games report no assists: one "not reported" class.

String form (``encode`` / ``decode``: the API's ``key``, the badge key, the lap card's ``board.key``): nine
``~``-separated parts ``game~track~layout~car~class~equal~category~conditions~assists``. ``?`` is unknown and ``-``
"this game has no such setting"; ids are percent-escaped (``%``, ``~`` and ``?`` only). Assists: F1 ``b2.a1.t2.g3.l2``
(braking, ABS, TC, gearbox, racing line), AC ``a1.t0``, other games ``-``. Example (Austria in the Haas, a race in
the dry, braking assist medium, ABS and TC not sent, automatic gears, full racing line):
``f1_25~f1:17~4318~f1:team:7~f1~0~race~dry~b2.a?.t?.g3.l2``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pitwall import carclass
from pitwall.storage.repo import BESTS_LENGTH_TOLERANCE

CATEGORIES = ("time_trial", "qualifying", "race", "practice")
CONDITIONS = ("dry", "wet")
UNKNOWN = "unknown"
WET = frozenset({"light_rain", "heavy_rain", "storm"})
SEP = "~"
UNKNOWN_MARK = "?"
NOT_APPLICABLE = "-"
AC_GAMES = frozenset({"ac"})
F1_ASSISTS = ("braking", "abs", "tc", "gearbox", "racing_line")  # display order
AC_ASSISTS = ("abs", "tc")
_ASSIST_CODES = {"braking": "b", "abs": "a", "tc": "t", "gearbox": "g", "racing_line": "l"}
_CODE_ASSISTS = {v: k for k, v in _ASSIST_CODES.items()}
_GEARBOX_DEFINED = frozenset({1, 2, 3})  # F1 Session.gearboxAssist; 0 = the unfilled tail
_RANGES: dict[str, range] = {
    "braking": range(4),
    "abs": range(2),
    "tc": range(3),
    "gearbox": range(1, 4),
    "racing_line": range(3),
}
_AC_RANGES: dict[str, range] = {"abs": range(2), "tc": range(2)}

CATEGORY_LABELS = {
    "time_trial": "Time trial",
    "qualifying": "Qualifying",
    "race": "Race",
    "practice": "Practice",
    UNKNOWN: "Session type unknown",
}
CONDITION_LABELS = {"dry": "Dry", "wet": "Wet", UNKNOWN: "Weather unknown"}
_BRAKING_WORDS = {0: "off", 1: "low", 2: "medium", 3: "high"}
_ON_OFF = {0: "off", 1: "on"}
_TC_F1_WORDS = {0: "off", 1: "medium", 2: "full"}
_GEARBOX_LABELS = {1: "Manual gears", 2: "Manual gears, suggested gear", 3: "Automatic gears"}
_LINE_WORDS = {0: "off", 1: "corners only", 2: "full"}
NOT_REPORTED_LABEL = "Assists not reported by this game"


class BadKey(ValueError):
    """A key string or key field that does not parse (the API's 422)."""


def is_f1_game(game: str | None) -> bool:
    return bool(game) and str(game).startswith("f1")


def _int(v: object) -> int | None:
    """An int from a JSON / SQLite value (JSON true / false are 1 / 0), else None."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float) and math.isfinite(v) and v == int(v):
        return int(v)
    return None


def _in(v: object, allowed: range) -> int | None:
    n = _int(v)
    return n if n is not None and n in allowed else None


@dataclass(slots=True, frozen=True)
class BoardKey:
    game: str
    track_id: str
    layout_m: int | None  # the layout's shortest stored length in whole metres; None = length unknown
    car_id: str | None  # None = car unknown
    car_class: str | None  # F1 games: "f1" | "f2" | "other", None unknown; other games: always None
    equal_performance: int | None  # F1 games: 0 realistic / 1 equal, None unknown; other games: always None
    category: str  # CATEGORIES or "unknown"
    conditions: str  # "dry" | "wet" | "unknown"
    assists: tuple[tuple[str, int | None], ...]  # F1 / AC: every setting in display order; other games: ()

    @property
    def f1(self) -> bool:
        return is_f1_game(self.game)

    @property
    def assists_reported(self) -> bool:
        return bool(self.assists)

    def assist(self, name: str) -> int | None:
        return dict(self.assists).get(name)

    def encode(self) -> str:
        return encode(self)

    def fields(self) -> dict[str, Any]:
        """The key as JSON: every part, ``None`` for unknown (the API's ``fields``, the lap card's ``board``)."""
        return {
            "game": self.game,
            "track_id": self.track_id,
            "layout_m": self.layout_m,
            "car_id": self.car_id,
            "car_class": self.car_class,
            "equal_performance": self.equal_performance,
            "category": self.category,
            "conditions": self.conditions,
            "assists": dict(self.assists) if self.assists else None,
            "assists_code": assists_code(self),
        }


# ---------------------------------------------------------------------------------------------- from raw values
def category_of(session_type: object) -> str:
    return session_type if isinstance(session_type, str) and session_type in CATEGORIES else UNKNOWN


def conditions_of(weather_condition: object) -> str:
    if not isinstance(weather_condition, str) or not weather_condition:
        return UNKNOWN
    return "wet" if weather_condition in WET else "dry"


def assists_of(game: str, raw: Mapping[str, Any]) -> tuple[tuple[str, int | None], ...]:
    """The assist class from the raw columns (``repo._BOARD_COLUMNS``: ``a_braking``, ``a_gearbox``, ``a_line``,
    ``a_abs``, ``a_tc`` from the session, ``lap_abs``, ``lap_tc`` from the lap)."""
    if is_f1_game(game):
        tail_ok = _int(raw.get("a_gearbox")) in _GEARBOX_DEFINED
        values = {
            "braking": _in(raw.get("a_braking"), _RANGES["braking"]) if tail_ok else None,
            "abs": _in(raw.get("lap_abs"), _RANGES["abs"]),
            "tc": _in(raw.get("lap_tc"), _RANGES["tc"]),
            "gearbox": _in(raw.get("a_gearbox"), _RANGES["gearbox"]) if tail_ok else None,
            "racing_line": _in(raw.get("a_line"), _RANGES["racing_line"]) if tail_ok else None,
        }
        return tuple((name, values[name]) for name in F1_ASSISTS)
    if game in AC_GAMES:
        return (("abs", _in(raw.get("a_abs"), _AC_RANGES["abs"])), ("tc", _in(raw.get("a_tc"), _AC_RANGES["tc"])))
    return ()


def key_of(raw: Mapping[str, Any], layout_m: int | None) -> BoardKey:
    """The board key of a lap from its raw columns (a ``repo.board_bests`` / ``board_record_laps`` / ``board_lap`` row,
    or ``raw_of_session``) and its layout (``layout_clusters``)."""
    game = str(raw.get("game") or "")
    f1 = is_f1_game(game)
    family = raw.get("family")
    tail_ok = _int(raw.get("a_gearbox")) in _GEARBOX_DEFINED
    car = raw.get("car_id")
    return BoardKey(
        game=game,
        track_id=str(raw.get("track_id") or ""),
        layout_m=layout_m,
        car_id=car if isinstance(car, str) and car else None,
        car_class=family if f1 and isinstance(family, str) and family in carclass.FAMILIES else None,
        equal_performance=_in(raw.get("a_ecp"), range(2)) if f1 and tail_ok else None,
        category=category_of(raw.get("session_type")),
        conditions=conditions_of(raw.get("weather_condition")),
        assists=assists_of(game, raw),
    )


def raw_of_session(session: Mapping[str, Any], lap_meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The raw key columns of a stored session row (``repo.get_session``: parsed ``weather``, ``assists``, ``info``)
    plus one of its laps' ``meta`` (ABS and TC are per lap in F1; None = not known)."""
    weather = session.get("weather") if isinstance(session.get("weather"), Mapping) else {}
    assists = session.get("assists") if isinstance(session.get("assists"), Mapping) else {}
    info = session.get("info") if isinstance(session.get("info"), Mapping) else {}
    meta = lap_meta if isinstance(lap_meta, Mapping) else {}
    assert isinstance(weather, Mapping) and isinstance(assists, Mapping) and isinstance(info, Mapping)
    return {
        "game": session.get("game"),
        "track_id": session.get("track_id"),
        "track_name": session.get("track_name"),
        "track_length_m": session.get("track_length_m"),
        "car_id": session.get("car_id"),
        "car_name": session.get("car_name"),
        "family": carclass.family_of(
            session.get("game"), info.get("formula"), session.get("car_id"), info.get("packet_format")
        ),
        "session_type": session.get("session_type"),
        "session_type_raw": session.get("session_type_raw"),
        "weather_condition": weather.get("condition"),
        "a_braking": assists.get("braking"),
        "a_gearbox": assists.get("gearbox"),
        "a_line": assists.get("dynamic_racing_line"),
        "a_ecp": assists.get("equal_car_performance"),
        "a_abs": assists.get("abs"),
        "a_tc": assists.get("tc"),
        "lap_abs": meta.get("abs_active"),
        "lap_tc": meta.get("traction_control"),
        "formula": info.get("formula"),
        "packet_format": info.get("packet_format"),
        "game_version": info.get("game_version"),
    }


# ---------------------------------------------------------------------------------------------- layouts
def layout_clusters(lengths: Iterable[float | None]) -> dict[float, int]:
    """One track's stored lengths -> the layout each belongs to, named by the shortest length of its group in whole
    metres. Lengths are grouped in increasing order: a length more than ``BESTS_LENGTH_TOLERANCE`` (3 %) longer than
    its group's shortest starts a new layout. Unknown (None, non-positive) lengths are left out: their own layout."""
    out: dict[float, int] = {}
    start: float | None = None
    for length in sorted({float(v) for v in lengths if isinstance(v, int | float) and v > 0}):
        if start is None or abs(length - start) > BESTS_LENGTH_TOLERANCE * max(length, start):
            start = length
        out[length] = round(start)
    return out


def layout_for(length: object, clusters: Mapping[float, int]) -> int | None:
    """The layout of one length: its cluster, else the nearest layout within the tolerance (a length stored after
    the clusters were made), else the length itself in whole metres; None when unknown."""
    if not isinstance(length, int | float) or isinstance(length, bool) or length <= 0:
        return None
    v = float(length)
    if v in clusters:
        return clusters[v]
    near = [m for m in set(clusters.values()) if abs(v - m) <= BESTS_LENGTH_TOLERANCE * max(v, m)]
    return min(near, key=lambda m: (abs(v - m), m)) if near else round(v)


# ---------------------------------------------------------------------------------------------- string form
_ESCAPES = (("%", "%25"), (SEP, "%7E"), (UNKNOWN_MARK, "%3F"))


def _esc(v: str) -> str:
    for raw, code in _ESCAPES:
        v = v.replace(raw, code)
    return v


def _unesc(v: str) -> str:
    for raw, code in reversed(_ESCAPES):
        v = v.replace(code, raw).replace(code.lower(), raw)
    return v


def _mark(v: int | None) -> str:
    return UNKNOWN_MARK if v is None else str(v)


def assists_code(k: BoardKey) -> str:
    if not k.assists:
        return NOT_APPLICABLE
    return ".".join(f"{_ASSIST_CODES[name]}{_mark(v)}" for name, v in k.assists)


def parts(k: BoardKey) -> dict[str, str]:
    """The key's string parts by name, unescaped (``?`` unknown, ``-`` not applicable): what ``encode`` joins."""
    f1 = k.f1
    return {
        "game": k.game,
        "track_id": k.track_id,
        "layout_m": _mark(k.layout_m),
        "car_id": UNKNOWN_MARK if k.car_id is None else k.car_id,
        "car_class": (UNKNOWN_MARK if k.car_class is None else k.car_class) if f1 else NOT_APPLICABLE,
        "equal_performance": _mark(k.equal_performance) if f1 else NOT_APPLICABLE,
        "category": k.category,
        "conditions": k.conditions,
        "assists": assists_code(k),
    }


def encode(k: BoardKey) -> str:
    p = parts(k)
    p["game"], p["track_id"] = _esc(k.game), _esc(k.track_id)
    if k.car_id is not None:
        p["car_id"] = _esc(k.car_id)
    return SEP.join(p.values())


def _parse_int(v: str, what: str, allowed: range | None = None) -> int | None:
    if v == UNKNOWN_MARK:
        return None
    if not v.isdigit():
        raise BadKey(f"{what} must be a whole number or '?'")
    n = int(v)
    if allowed is not None and n not in allowed:
        raise BadKey(f"{what} out of range")
    return n


def parse_assists(game: str, code: str) -> tuple[tuple[str, int | None], ...]:
    """An assist code (``b2.a1.t2.g3.l2`` / ``a1.t0`` / ``-``) for ``game``; every setting the game has, in display
    order. Raises ``BadKey`` when it does not fit the game."""
    names: tuple[str, ...]
    if is_f1_game(game):
        names, ranges = F1_ASSISTS, _RANGES
    elif game in AC_GAMES:
        names, ranges = AC_ASSISTS, _AC_RANGES
    else:
        if code != NOT_APPLICABLE:
            raise BadKey("this game reports no assists: the assist class is '-'")
        return ()
    values: dict[str, int | None] = {}
    for part in code.split("."):
        name = _CODE_ASSISTS.get(part[:1])
        if name is None or name not in names or name in values:
            raise BadKey(f"unknown assist '{part}'")
        values[name] = _parse_int(part[1:], f"assist '{name}'", ranges[name])
    if set(values) != set(names):
        raise BadKey("the assist class must name every setting the game has")
    return tuple((name, values[name]) for name in names)


def decode(text: str) -> BoardKey:
    """The ``BoardKey`` of an ``encode``d string. Raises ``BadKey`` for anything that does not parse."""
    parts = text.split(SEP)
    if len(parts) != 9:
        raise BadKey("a board key has 9 parts separated by '~'")
    game, track, layout, car, cls, equal, category, conditions, assists = parts
    game, track = _unesc(game), _unesc(track)
    if not game or not track:
        raise BadKey("the key needs a game and a track")
    f1 = is_f1_game(game)
    if category not in (*CATEGORIES, UNKNOWN):
        raise BadKey("unknown session category")
    if conditions not in (*CONDITIONS, UNKNOWN):
        raise BadKey("conditions must be dry, wet or unknown")
    if f1:
        if cls != UNKNOWN_MARK and cls not in carclass.FAMILIES:
            raise BadKey("car class must be f1, f2, other or '?'")
        car_class = None if cls == UNKNOWN_MARK else cls
        equal_performance = _parse_int(equal, "equal performance", range(2))
    else:
        if cls != NOT_APPLICABLE or equal != NOT_APPLICABLE:
            raise BadKey("car class and equal performance are '-' outside F1 games")
        car_class, equal_performance = None, None
    return BoardKey(
        game=game,
        track_id=track,
        layout_m=_parse_int(layout, "layout"),
        car_id=None if car == UNKNOWN_MARK else _unesc(car),
        car_class=car_class,
        equal_performance=equal_performance,
        category=category,
        conditions=conditions,
        assists=parse_assists(game, assists),
    )


# ---------------------------------------------------------------------------------------------- words
def assist_chips(k: BoardKey) -> list[dict[str, Any]]:
    """One chip per setting: ``{key, value, known, label}`` ("Braking assist medium", "ABS unknown"); a game that
    reports none has one chip saying so."""
    if not k.assists:
        return [{"key": "assists", "value": None, "known": False, "label": NOT_REPORTED_LABEL}]
    out = []
    for name, v in k.assists:
        out.append({"key": name, "value": v, "known": v is not None, "label": _assist_label(name, v, k.f1)})
    return out


def _assist_label(name: str, v: int | None, f1: bool) -> str:
    if name == "braking":
        return f"Braking assist {_BRAKING_WORDS.get(v, 'unknown') if v is not None else 'unknown'}"
    if name == "abs":
        return f"ABS {_ON_OFF.get(v, 'unknown') if v is not None else 'unknown'}"
    if name == "tc":
        words = _TC_F1_WORDS if f1 else _ON_OFF
        return f"Traction control {words.get(v, 'unknown') if v is not None else 'unknown'}"
    if name == "gearbox":
        return _GEARBOX_LABELS.get(v, "Gears unknown") if v is not None else "Gears unknown"
    if name == "racing_line":
        return f"Racing line {_LINE_WORDS.get(v, 'unknown') if v is not None else 'unknown'}"
    return name


def car_class_label(k: BoardKey) -> str | None:
    """F1 games: "F1 car" / "F2 car" / "Other car class" / "Car class unknown"; None elsewhere."""
    if not k.f1:
        return None
    if k.car_class is None:
        return "Car class unknown"
    return {"f1": "F1 car", "f2": "F2 car"}.get(k.car_class, "Other car class")


def equal_performance_label(k: BoardKey) -> str | None:
    if not k.f1:
        return None
    if k.equal_performance is None:
        return "Car performance setting unknown"
    return "Equal car performance" if k.equal_performance == 1 else "Realistic car performance"


def assists_text(k: BoardKey) -> str:
    """``Braking assist medium, ABS unknown, ...`` (the chips in one line)."""
    return ", ".join(c["label"] for c in assist_chips(k))
