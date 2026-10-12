"""What a stored session says about the setup it needs: car format, session kind and track conditions.

Every answer says how it was reached, and ambiguity stays unknown (``None`` with a reason) instead of a guess:

* **Car format.** The car's class comes from ``pitwall.carclass`` (one module decides it). F1 cars: the 2026 Season
  Pack cars report formula 13 ("F1 26") and team ids 476-486 in UDP format 2026 (EA 2026 spec,
  ``docs/research/f1-udp-spec.md`` section 7). In format 2025 a 2026 car can only show up as the generic car (team
  41, "F1 Generic"; F1Laps' format guide), which is also the F1 World car, so a generic car in format 2025 is
  ambiguous and the driver picks. A real 2025 team id (0-9) in format 2025 cannot be a 2026 car (2026 team ids do
  not fit the 2025 field), so it is a 2025 car. F2 cars: the 2024 teams (158-168) and, with formula F2, the 2025
  teams (209-219 in format 2025, 465-475 in format 2026) are the ``f2`` format; the 2026 F2 cars (489-499) and an F2
  car whose team is not known have no setups, and the driver is never asked to pick an F1 format for them. Classic
  cars and the beta formula have no catalogue setups.
* **Session kind.** Race and qualifying map directly. Time trial is one-lap pace, so it uses the qualifying setup;
  practice prepares the race, so it uses the race setup. Both say so in ``notes``.
* **Conditions.** The game's current weather: rain and storm are wet, clear and cloud are dry. A forecast is not
  the current track, so it is never used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pitwall import carclass
from pitwall.carsetup.catalog import F2_NONE_AT_TRACK, CarFormat, Conditions, SessionKind

F1_GAMES = carclass.F1_GAMES
TEAMS_2025 = carclass.TEAMS_F1_2025  # Mercedes .. Sauber (EA appendix, both formats)
TEAMS_2026 = carclass.TEAMS_F1_2026  # Mercedes '26 .. Cadillac '26 (format 2026 only)
TEAMS_F2_2026 = carclass.TEAMS_F2_2026  # F2 2026 teams (format 2026, PDF v1.2)
GENERIC_TEAMS = carclass.TEAMS_F1_GENERIC  # F1 Generic, F1 Custom Team (My Team)
FORMULA_2026 = carclass.FORMULA_2026
FORMULAS_2025 = carclass.FORMULAS_F1
FORMULAS_UNSUPPORTED = frozenset({carclass.FORMULA_CLASSIC, carclass.FORMULA_BETA})
# F2 cars with catalogue setups (format "f2"): the 2024 teams always, the 2025 teams with formula F2
F2_TEAMS_ALWAYS = carclass.TEAMS_F2_2024
F2_TEAMS_WITH_FORMULA = carclass.TEAMS_F2_2025_OBSERVED | carclass.TEAMS_F2_2025
F2_2026_REASON = "No setups for the 2026 F2 cars in Pitwall yet."
F2_UNKNOWN_REASON = "Pitwall can't tell which F2 car this is, so it shows no setups."
__all__ = [
    "F2_2026_REASON",
    "F2_NONE_AT_TRACK",
    "F2_UNKNOWN_REASON",
    "SetupContext",
    "guess_car_format",
    "session_context",
]
WET = frozenset({"light_rain", "heavy_rain", "storm"})
DRY = frozenset({"clear", "light_cloud", "overcast"})


@dataclass(frozen=True, slots=True)
class CarFormatGuess:
    car_format: CarFormat | None
    certain: bool
    reason: str


@dataclass(frozen=True, slots=True)
class SetupContext:
    """The catalogue key a session maps to. ``None`` fields are unknown; ``reasons`` explains every field."""

    track_id: int | None
    track_name: str | None
    car_format: CarFormat | None
    car_format_certain: bool
    session: SessionKind | None
    conditions: Conditions | None
    reasons: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    car_class: carclass.CarClass | None = None

    @property
    def family(self) -> str | None:
        """The car class family (``f1`` / ``f2`` / ``other``); None when the class is not known."""
        return None if self.car_class is None else self.car_class.family

    @property
    def asks_car_format(self) -> bool:
        """The driver may be asked to pick the car format: only an F1 car (or a car of unknown class) whose
        generation the game does not tell. An F2 or classic car never is."""
        return self.car_format is None and self.family in (None, "f1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "track_name": self.track_name,
            "car_format": self.car_format,
            "car_format_certain": self.car_format_certain,
            "car_class": None if self.car_class is None else self.car_class.to_dict(),
            "session": self.session,
            "conditions": self.conditions,
            "reasons": dict(self.reasons),
            "notes": list(self.notes),
        }


def _team_id(car_id: object) -> int | None:
    return carclass.team_id(car_id)


def f1_track_id(track_id: object) -> int | None:
    """EA track id from pitwall's ``"f1:<id>"`` (``None`` for other games, synthetic tracks and unknown)."""
    if isinstance(track_id, str) and track_id.startswith("f1:"):
        tail = track_id[3:]
        if tail.isdigit():
            return int(tail)
    return None


def guess_car_format(packet_format: object, formula: object, car_id: object) -> CarFormatGuess:
    """The catalogue car format of a car (``carclass`` decides its class), with the reason. ``certain`` False means the
    driver may pick (an F1 car whose generation is not known); an F2 or classic car without setups is certain."""
    team = _team_id(car_id)
    form = formula if isinstance(formula, str) else None
    cls = carclass.classify("f1_25", formula, car_id, packet_format)
    if form in FORMULAS_UNSUPPORTED:
        return CarFormatGuess(None, True, f"formula {form}: pitwall has no setups for these cars")
    if cls is not None and cls.family == "f2":
        return _f2_format(team, form)
    if cls is not None and cls.family != "f1":
        return CarFormatGuess(None, True, f"formula {form}: pitwall has no setups for these cars")
    gen, certain, why = carclass.f1_generation(packet_format, formula, car_id)
    return CarFormatGuess(gen, certain, why)


def _f2_format(team: int | None, formula: str | None) -> CarFormatGuess:
    """F2 cars: format ``f2`` for the 2024 teams, and for the 2025 teams when the formula says F2 (the observed ids
    209-219 are named only with it); none for the 2026 F2 cars or an F2 car whose team is not known."""
    if team in F2_TEAMS_ALWAYS:
        return CarFormatGuess("f2", True, f"F2 team id {team} (2024 season car)")
    if team in F2_TEAMS_WITH_FORMULA and formula == carclass.FORMULA_F2:
        return CarFormatGuess("f2", True, f"F2 team id {team} with formula F2 (2025 season car)")
    if team in TEAMS_F2_2026:
        return CarFormatGuess(None, True, F2_2026_REASON)
    return CarFormatGuess(None, True, F2_UNKNOWN_REASON)


def session_kind(session_type: object) -> tuple[SessionKind | None, str | None]:
    """Catalogue session for pitwall's ``SessionType`` value, and a note when it is a stand-in."""
    if session_type == "race":
        return "race", None
    if session_type == "qualifying":
        return "qualifying", None
    if session_type == "time_trial":
        return "qualifying", "Time trial is one-lap pace, so the qualifying setup is shown."
    if session_type == "practice":
        return "race", "Practice usually prepares the race, so the race setup is shown (qualifying is available)."
    return None, None


def conditions_for(weather: object) -> Conditions | None:
    cond = weather.get("condition") if isinstance(weather, dict) else None
    if cond in WET:
        return "wet"
    if cond in DRY:
        return "dry"
    return None


def session_context(session: dict[str, Any]) -> SetupContext:
    """Map a stored session row (``repo.get_session``) to the catalogue key, with a reason for every field."""
    reasons: dict[str, str] = {}
    notes: list[str] = []
    info = session.get("info") or {}
    if session.get("game") not in F1_GAMES:
        reasons["game"] = f"game {session.get('game')!r} has no car setup catalogue"
    track = f1_track_id(session.get("track_id"))
    if track is None:
        reasons["track_id"] = f"track {session.get('track_id')!r} is not an F1 25 track id"
    guess = guess_car_format(info.get("packet_format"), info.get("formula"), session.get("car_id"))
    reasons["car_format"] = guess.reason
    cls = carclass.classify_row(session)
    kind, note = session_kind(session.get("session_type"))
    if kind is None:
        reasons["session"] = f"session type {session.get('session_type')!r} is unknown"
    if note:
        notes.append(note)
    cond = conditions_for(session.get("weather"))
    if cond is None:
        reasons["conditions"] = "the game has not reported the weather"
    if session.get("synthetic"):
        notes.append("This is a synthetic test session, not real driving.")
    return SetupContext(
        track_id=track,
        track_name=session.get("track_name"),
        car_format=guess.car_format,
        car_format_certain=guess.certain,
        session=kind,
        conditions=cond,
        reasons=reasons,
        notes=tuple(notes),
        car_class=cls,
    )
