"""What a stored session says about the setup it needs: car format, session kind and track conditions.

Every answer says how it was reached, and ambiguity stays unknown (``None`` with a reason) instead of a guess:

* **Car format.** The 2026 Season Pack cars report formula 13 ("F1 26") and team ids 476-486 in UDP format 2026
  (EA 2026 spec, ``docs/research/f1-udp-spec.md`` section 7). In format 2025 a 2026 car can only show up as the
  generic car (team 41, "F1 Generic"; F1Laps' format guide), which is also the F1 World car, so a generic car in
  format 2025 is ambiguous and the driver picks. A real 2025 team id (0-9) in format 2025 cannot be a 2026 car
  (2026 team ids do not fit the 2025 field), so it is a 2025 car. Classic cars, F2 and the beta formula have no
  catalogue setups.
* **Session kind.** Race and qualifying map directly. Time trial is one-lap pace, so it uses the qualifying setup;
  practice prepares the race, so it uses the race setup. Both say so in ``notes``.
* **Conditions.** The game's current weather: rain and storm are wet, clear and cloud are dry. A forecast is not
  the current track, so it is never used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pitwall.carsetup.catalog import CarFormat, Conditions, SessionKind

F1_GAMES = frozenset({"f1_25"})
TEAMS_2025 = frozenset(range(10))  # Mercedes .. Sauber (EA appendix, both formats)
TEAMS_2026 = frozenset(range(476, 487))  # Mercedes '26 .. Cadillac '26 (format 2026 only)
TEAMS_F2_2026 = frozenset(range(489, 500))  # F2 2026 teams (format 2026, PDF v1.2)
GENERIC_TEAMS = frozenset({41, 104})  # F1 Generic, F1 Custom Team (My Team)
FORMULA_2026 = "F1 26"
FORMULAS_2025 = frozenset({"F1 Modern", "F1 Generic", "Esports", "F1 World", "F1 Elimination"})
FORMULAS_UNSUPPORTED = frozenset({"F1 Classic", "F2", "Beta"})
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "track_name": self.track_name,
            "car_format": self.car_format,
            "car_format_certain": self.car_format_certain,
            "session": self.session,
            "conditions": self.conditions,
            "reasons": dict(self.reasons),
            "notes": list(self.notes),
        }


def _team_id(car_id: object) -> int | None:
    if isinstance(car_id, str) and car_id.startswith("f1:team:"):
        tail = car_id.rsplit(":", 1)[1]
        if tail.isdigit():
            return int(tail)
    return None


def f1_track_id(track_id: object) -> int | None:
    """EA track id from pitwall's ``"f1:<id>"`` (``None`` for other games, synthetic tracks and unknown)."""
    if isinstance(track_id, str) and track_id.startswith("f1:"):
        tail = track_id[3:]
        if tail.isdigit():
            return int(tail)
    return None


def guess_car_format(packet_format: object, formula: object, car_id: object) -> CarFormatGuess:
    team = _team_id(car_id)
    fmt = packet_format if isinstance(packet_format, int) and not isinstance(packet_format, bool) else None
    form = formula if isinstance(formula, str) else None
    if form in FORMULAS_UNSUPPORTED:
        return CarFormatGuess(None, True, f"formula {form}: pitwall has no setups for these cars")
    if team in TEAMS_F2_2026:
        return CarFormatGuess(None, True, f"team id {team} is an F2 2026 team: pitwall has no F2 setups")
    if form == FORMULA_2026 or team in TEAMS_2026:
        why = "formula F1 26" if form == FORMULA_2026 else f"2026 team id {team}"
        return CarFormatGuess("f1_2026", True, f"{why} (2026 Season Pack car)")
    if fmt == 2026:
        if form in FORMULAS_2025 or team in TEAMS_2025:
            return CarFormatGuess(
                "f1_2025", True, "UDP format 2026 reports 2026 cars as formula F1 26; this is not one"
            )
        return CarFormatGuess(None, False, "UDP format 2026 without a formula or team that identifies the car")
    if team in TEAMS_2025:
        return CarFormatGuess(
            "f1_2025", True, f"2025 team id {team} (in UDP format 2025 a 2026 car reports as the generic car)"
        )
    if team in GENERIC_TEAMS or team is None:
        what = "the generic car" if team is not None else "an unknown car"
        return CarFormatGuess(
            None,
            False,
            f"{what} in UDP format {fmt or 'unknown'}: 2025 and 2026 cars cannot be told apart, choose the car "
            "format (or set the game's UDP format to 2026)",
        )
    return CarFormatGuess(None, False, f"team id {team} is not a known F1 team")


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
    )
