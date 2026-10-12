"""Row shapes and wording helpers shared by the motivation modules (pure, no I/O).

``SessionRow`` / ``LapRow`` are the history reads of ``storage.repo.motivation_sessions`` / ``motivation_laps``
(lap columns before ``meta`` only). ``History`` is one driver's real driving in time order. ``Scope`` is what a
goal or a suggestion is about (game, track, layout length, car or car class). ``GoalRow`` is a stored goal.

Wording is plain British English. Lap times are ``m:ss.SSS``; a lap-time spread or a gap is in seconds, written
``1.1 s`` when the value is a whole tenth and ``1.230 s`` otherwise. Dates are short and local: ``Sat 10 Oct``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from pitwall import carclass
from pitwall.storage.repo import REPLAY_SOURCE_PREFIX

GOAL_KINDS = ("lap_time", "clean_streak", "consistency", "race_clean")
GOAL_STATUSES = ("active", "achieved", "archived")
RACE_RULES = ("no_penalties", "no_contact")
WINDOW_LAPS = (3, 5, 10)
SYNTHETIC_TRACK_PREFIX = "synthetic:"
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MONTHS_LONG = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
LONG_TRACK_NAME = 24  # the radio leaves out a track name longer than this ("Unidentified GT7 circuit ...")


def _int(v: object) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and math.isfinite(v) and v == int(v):
        return int(v)
    return None


def _float(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _str(v: object) -> str | None:
    return v if isinstance(v, str) and v else None


# ---------------------------------------------------------------------------------------------- rows
@dataclass(slots=True, frozen=True)
class SessionRow:
    id: str
    started_unix: float
    ended_unix: float | None
    game: str
    track_id: str | None
    track_name: str | None
    track_length_m: float | None
    car_id: str | None
    car_name: str | None
    session_type: str | None
    synthetic: bool
    source: str
    driver_id: int | None
    total_laps: int | None  # race length (F1 sends it); stored from schema v3 only
    formula: str | None  # F1 "F1 World" / "F2" ...
    car_class_raw: int | None  # Forza CarClass
    packet_format: int | None = None  # F1 UDP format (names the observed F2 team ids 209-219 in format 2025)

    @classmethod
    def from_row(cls, d: Mapping[str, Any]) -> SessionRow:
        return cls(
            id=str(d["id"]),
            started_unix=float(d["started_unix"]),
            ended_unix=_float(d.get("ended_unix")),
            game=str(d.get("game") or ""),
            track_id=_str(d.get("track_id")),
            track_name=_str(d.get("track_name")),
            track_length_m=_float(d.get("track_length_m")),
            car_id=_str(d.get("car_id")),
            car_name=_str(d.get("car_name")),
            session_type=_str(d.get("session_type")),
            synthetic=bool(d.get("synthetic")),
            source=str(d.get("source") or ""),
            driver_id=_int(d.get("driver_id")),
            total_laps=_int(d.get("total_laps")),
            formula=_str(d.get("formula")),
            car_class_raw=_int(d.get("car_class")),
            packet_format=_int(d.get("packet_format")),
        )

    @property
    def car_label(self) -> str | None:
        """The car as the dashboard names it (``carclass.car_label``): "F2 · Art GP '24", "McLaren"; never a raw id."""
        cls = carclass.classify(self.game, self.formula, self.car_id, self.packet_format)
        return display_car(carclass.car_label(cls, self.car_name, self.car_id, self.packet_format))

    @property
    def replay(self) -> bool:
        return self.source.startswith(REPLAY_SOURCE_PREFIX)

    @property
    def is_race(self) -> bool:
        return self.session_type == "race"

    @property
    def is_f1(self) -> bool:
        return is_f1_game(self.game)

    @property
    def pb_key(self) -> tuple[str, str, str | None] | None:
        """Personal bests, PB streaks and badges are per game + track + car (as ``repo.pb_history``)."""
        return None if self.track_id is None else (self.game, self.track_id, self.car_id)


@dataclass(slots=True, frozen=True)
class LapRow:
    id: int
    session_id: str
    lap_number: int
    lap_time_ms: int | None
    s1_ms: int | None
    s2_ms: int | None
    s3_ms: int | None
    valid: bool | None
    clean: bool
    flags: frozenset[str]
    # F1 races with a chequered flag or a safety car only (``service.load_history``): the lap's first and last
    # receive times (lap meta, same clock as the events) and whether it overlapped the safety car / VSC.
    t_start_ns: int | None = None
    t_end_ns: int | None = None
    safety_car: bool = False

    @classmethod
    def from_row(cls, d: Mapping[str, Any]) -> LapRow:
        raw_flags = d.get("flags") or ()
        valid = d.get("valid")
        return cls(
            id=int(d["id"]),
            session_id=str(d["session_id"]),
            lap_number=int(d["lap_number"]),
            lap_time_ms=_positive_ms(d.get("lap_time_ms")),
            s1_ms=_positive_ms(d.get("s1_ms")),
            s2_ms=_positive_ms(d.get("s2_ms")),
            s3_ms=_positive_ms(d.get("s3_ms")),
            valid=None if valid is None else bool(valid),
            clean=bool(d.get("clean")),
            flags=frozenset(str(f) for f in raw_flags if isinstance(f, str)),
        )

    @property
    def timed(self) -> bool:
        return self.lap_time_ms is not None

    @property
    def clean_ms(self) -> int | None:
        """The lap time of a clean lap, else None (only clean laps count for times)."""
        return self.lap_time_ms if self.clean else None


def _positive_ms(v: object) -> int | None:
    n = _int(v)
    return n if n is not None and n > 0 else None


@dataclass(slots=True)
class History:
    """One driver's driving in time order, with laps per session (lap order) and incident events for races."""

    sessions: list[SessionRow] = field(default_factory=list)
    laps: dict[str, list[LapRow]] = field(default_factory=dict)
    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def laps_of(self, session_id: str) -> list[LapRow]:
        return self.laps.get(session_id, [])

    def index_of(self, session_id: str) -> int | None:
        for i, s in enumerate(self.sessions):
            if s.id == session_id:
                return i
        return None

    def until(self, session_id: str) -> History:
        """History as it was at the end of ``session_id``: sessions started before it, plus the session itself."""
        i = self.index_of(session_id)
        if i is None:
            return History([], self.laps, self.events)
        return History(self.sessions[: i + 1], self.laps, self.events)

    def before(self, unix: float) -> History:
        """Sessions started before ``unix``."""
        return History([s for s in self.sessions if s.started_unix < unix], self.laps, self.events)

    def without(self, session_id: str) -> History:
        return History([s for s in self.sessions if s.id != session_id], self.laps, self.events)

    def only(self, session_id: str) -> History:
        return History([s for s in self.sessions if s.id == session_id], self.laps, self.events)

    def all_laps(self) -> Iterable[tuple[SessionRow, LapRow]]:
        for s in self.sessions:
            for lap in self.laps.get(s.id, ()):
                yield s, lap


# ---------------------------------------------------------------------------------------------- scope
def is_f1_game(game: str | None) -> bool:
    return bool(game) and str(game).startswith("f1")


def is_forza_game(game: str | None) -> bool:
    return bool(game) and str(game).startswith("forza")


def car_class_of(game: str | None, formula: str | None, car_class_raw: int | None) -> str | None:
    """A car-class key the game itself reports: F1 formula, Forza CarClass. Other games: None (never guessed)."""
    if game and is_f1_game(game) and formula:
        return f"{game}:formula:{formula}"
    if game and is_forza_game(game) and car_class_raw is not None:
        return f"{game}:class:{car_class_raw}"
    return None


def session_car_class(s: SessionRow) -> str | None:
    return car_class_of(s.game, s.formula, s.car_class_raw)


def car_class_label(car_class: str | None, car_name: str | None = None) -> str | None:
    """``any F1 World car``; Forza: ``any car of the same class as the <car>`` (no letter mapping: not guessed)."""
    if not car_class:
        return None
    parts = car_class.split(":", 2)
    if len(parts) != 3:
        return None
    _game, kind, value = parts
    if kind == "formula" and value:
        return f"any {value} car"
    if kind == "class":
        return f"any car of the same class as the {car_name}" if car_name else "any car of the same class"
    return None


@dataclass(slots=True, frozen=True)
class Scope:
    """What a goal or suggestion is about. Unset fields mean "any"; a set length matches within 3 %."""

    game: str | None = None
    track_id: str | None = None
    track_name: str | None = None
    track_length_m: float | None = None
    car_id: str | None = None
    car_class: str | None = None
    car_name: str | None = None  # label of the car (or of the car the class was taken from)

    @property
    def empty(self) -> bool:
        return self.game is None and self.track_id is None and self.car_id is None and self.car_class is None

    @property
    def car_label(self) -> str | None:
        name = display_car(self.car_name)
        if self.car_class:
            return car_class_label(self.car_class, name)
        return name if self.car_id else None

    @property
    def track_label(self) -> str | None:
        return self.track_name or self.track_id

    def text(self) -> str | None:
        """``Austria · Haas``, ``Austria · any F1 World car``, or None for "anywhere"."""
        parts = [p for p in (self.track_label, self.car_label) if p]
        if not parts and self.game and not self.empty:
            return game_label(self.game)
        return " · ".join(parts) if parts else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game,
            "track_id": self.track_id,
            "track_name": self.track_name,
            "track_length_m": self.track_length_m,
            "car_id": self.car_id,
            "car_class": self.car_class,
            "car_label": self.car_label,
        }

    @classmethod
    def of_session(cls, s: SessionRow, *, by_class: bool = False) -> Scope:
        """The session's game + track + layout + car (or the car's class)."""
        cc = session_car_class(s) if by_class else None
        return cls(
            game=s.game,
            track_id=s.track_id,
            track_name=s.track_name,
            track_length_m=s.track_length_m,
            car_id=None if cc else s.car_id,
            car_class=cc,
            car_name=s.car_name,
        )

    def with_labels(self, track_name: str | None, car_name: str | None, length: float | None) -> Scope:
        return replace(
            self,
            track_name=self.track_name or track_name,
            car_name=self.car_name or car_name,
            track_length_m=self.track_length_m if self.track_length_m is not None else length,
        )


UNKNOWN_CAR_PREFIX = "Unknown team"  # F1's label for a team id its spec does not name ("Unknown team (id 214)")
# Raw ids stored as a car name by older adapters or other games: "team_214", "car_12", "gt7:car:123", "f1:team:7".
_RAW_CAR_ID = re.compile(r"^(?:(?:team|car)_\d+|[a-z0-9_]+(?::[a-z0-9_.-]+)+)$", re.I)
# Track names that do not identify a track: F1's "Unknown track" / "Unknown track (id 99)" (adapters/f1/enums.py)
# and GT7's "Unidentified GT7 circuit (3.80 km)" (adapters/gt7/adapter.py: GT7 sends no track id).
UNKNOWN_TRACK_NAMES = ("Unknown track", "Unidentified GT7 circuit")


def display_car(name: str | None) -> str | None:
    """A car name a driver can read, or None: an id-only label ("Unknown team (id 214)") or a raw id ("team_214",
    "gt7:car:123") is left out, never shown."""
    if not name or name.startswith(UNKNOWN_CAR_PREFIX) or _RAW_CAR_ID.match(name.strip()):
        return None
    return name


def track_identified(track_id: str | None, track_name: str | None) -> bool:
    """The track is known by id *and* has a readable name: not an ``unknown_…`` / ``…:-1`` id, not F1's "Unknown
    track (id n)" and not GT7's placeholder "Unidentified GT7 circuit (…)". Badges and the digest's new tracks name
    only such tracks."""
    if not track_id or track_id.startswith("unknown") or track_id.endswith(":-1"):
        return False
    return bool(track_name) and not str(track_name).startswith(UNKNOWN_TRACK_NAMES)


def in_car(name: str | None) -> str:
    """`` in the Haas`` (empty when the car has no readable name); a class label (``carclass.car_label``) reads
    `` in the Art GP '24 F2 car`` / `` in an F2 car``."""
    shown = display_car(name)
    if not shown:
        return ""
    if " · " in shown:
        cls, team = shown.split(" · ", 1)
        return f" in the {team} {cls} car"
    if shown.endswith(" car"):
        return f" in {'an' if shown[:1] in 'AEFHILMNORSX' else 'a'} {shown}"
    return f" in the {shown}"


def game_label(game: str | None) -> str:
    return {
        "f1_25": "F1 25",
        "f1_24": "F1 24",
        "gt7": "Gran Turismo 7",
        "forza_motorsport": "Forza Motorsport",
        "forza_horizon": "Forza Horizon",
        "ac": "Assetto Corsa",
        "acc": "Assetto Corsa Competizione",
    }.get(str(game), str(game or "this game"))


# ---------------------------------------------------------------------------------------------- goals (stored)
@dataclass(slots=True, frozen=True)
class GoalRow:
    id: int
    driver_id: int
    kind: str
    status: str
    target: float
    params: dict[str, Any]
    scope: Scope
    baseline: float | None
    after_lap_id: int
    source: str
    basis: dict[str, Any] | None
    created_unix: float
    achieved_unix: float | None
    achieved_session_id: str | None
    achieved_lap_id: int | None
    achieved_value: float | None

    @classmethod
    def from_row(cls, d: Mapping[str, Any]) -> GoalRow:
        params = d.get("params")
        basis = d.get("basis")
        return cls(
            id=int(d["id"]),
            driver_id=int(d["driver_id"]),
            kind=str(d["kind"]),
            status=str(d["status"]),
            target=float(d["target"]),
            params=dict(params) if isinstance(params, Mapping) else {},
            scope=Scope(
                game=_str(d.get("game")),
                track_id=_str(d.get("track_id")),
                track_name=_str(d.get("track_name")),
                track_length_m=_float(d.get("track_length_m")),
                car_id=_str(d.get("car_id")),
                car_class=_str(d.get("car_class")),
                car_name=_str(d.get("car_name")),
            ),
            baseline=_float(d.get("baseline")),
            after_lap_id=int(d.get("after_lap_id") or 0),
            source=str(d.get("source") or "manual"),
            basis=dict(basis) if isinstance(basis, Mapping) else None,
            created_unix=float(d["created_unix"]),
            achieved_unix=_float(d.get("achieved_unix")),
            achieved_session_id=_str(d.get("achieved_session_id")),
            achieved_lap_id=_int(d.get("achieved_lap_id")),
            achieved_value=_float(d.get("achieved_value")),
        )

    @property
    def window_laps(self) -> int:
        k = _int(self.params.get("window_laps"))
        return k if k in WINDOW_LAPS else 5

    @property
    def rule(self) -> str:
        r = self.params.get("rule")
        return r if r in RACE_RULES else "no_penalties"

    @property
    def target_ms(self) -> int:
        return round(self.target)


# ---------------------------------------------------------------------------------------------- wording
def lap_time(ms: float | None) -> str:
    """``70549`` -> ``1:10.549`` (three decimals; minutes always shown)."""
    if ms is None:
        return "no time"
    total = round(ms)
    m, rem = divmod(total, 60_000)
    return f"{m}:{rem / 1000:06.3f}"


def lap_time_radio(ms: float) -> str:
    """Radio form of a target: ``1:10`` for whole seconds, else ``1:10.3`` (targets are whole tenths); under a minute
    ``23 seconds`` / ``23.5 seconds`` ("0:23" would be spoken "twenty-three")."""
    total = round(ms)
    m, rem = divmod(total, 60_000)
    if m == 0:
        return f"{rem // 1000} seconds" if rem % 1000 == 0 else f"{rem / 1000:.1f} seconds"
    if rem % 1000 == 0:
        return f"{m}:{rem // 1000:02d}"
    return f"{m}:{rem / 1000:04.1f}"


def seconds(ms: float, *, tenths_when_whole: bool = True) -> str:
    """A duration in seconds: ``1100`` -> ``1.1``, ``1230`` -> ``1.230`` (unit not included)."""
    v = round(ms)
    if tenths_when_whole and v % 100 == 0:
        return f"{v / 1000:.1f}"
    return f"{v / 1000:.3f}"


def gap_s(ms: float) -> str:
    """A gap in seconds with three decimals: ``549`` -> ``0.549``."""
    return f"{abs(round(ms)) / 1000:.3f}"


def about_s(ms: float) -> str:
    """Plain wording of a gap: ``About 0.5 s`` (``Less than 0.1 s`` under 50 ms)."""
    v = abs(ms)
    if v < 50:
        return "less than 0.1 s"
    return f"about {v / 1000:.1f} s"


def local_dt(unix: float) -> datetime:
    return datetime.fromtimestamp(unix)


def local_date(unix: float) -> date:
    return datetime.fromtimestamp(unix).date()


def short_date(unix: float | date) -> str:
    """``Sat 10 Oct`` (server local time)."""
    d = unix if isinstance(unix, date) else local_date(unix)
    return f"{_DAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]}"


def long_date(d: date) -> str:
    return f"{d.day} {MONTHS_LONG[d.month - 1]} {d.year}"


def week_range_text(start: date, end: date) -> str:
    """``5 to 11 October 2026``; across months / years the earlier end carries its month / year."""
    if start.year != end.year:
        return f"{long_date(start)} to {long_date(end)}"
    if start.month != end.month:
        return f"{start.day} {MONTHS_LONG[start.month - 1]} to {long_date(end)}"
    return f"{start.day} to {long_date(end)}"


def count_words(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def number_word(n: int) -> str:
    """Small counts in words for plain sentences: ``one``, ``both`` is up to the caller."""
    words = ("none", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
    return words[n] if 0 <= n < len(words) else str(n)


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text
