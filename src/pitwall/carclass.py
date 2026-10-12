"""Car classes: which kind of car a session was driven in (F1 2025, F1 2026, F2, classic F1...), worked out at read
time from what the game reported. Nothing here is stored: the class follows from ``SessionInfo.formula`` (F1
``m_formula``, EA spec appendix 8.12) and the car id (``"f1:team:<id>"``, appendix 8.1), so an old row is classified
the same way as a live session.

One module decides the class; everything else asks it (labels, track models, the physics heavy-stop warning, car
setups, the engineer's facts):

* **Formula first.** ``F2`` (``m_formula`` 2) is an F2 car, ``F1 26`` (13) a 2026 Season Pack car, ``F1 Classic`` a
  classic car; ``F1 Modern``, ``F1 Generic``, ``Esports``, ``F1 World`` and ``F1 Elimination`` are F1 cars whose
  generation (2025 or 2026) follows the car format rules below. ``Beta`` is ``other``.
* **Team ids for rows without a formula** (sessions stored before the formula was kept): the spec's F2 teams
  (158-168, 465-475, 489-499) and the F2 team ids seen on a real PS5 in UDP format 2025 (209-219, see
  ``enums.OBSERVED_F2_TEAMS_FMT2025``) are F2; the spec's F1 teams are F1. Any other id is unknown (no class).
* **Generation of an F1 car.** In UDP format 2026 a 2026 car reports formula ``F1 26`` and team ids 476-486. In
  format 2025 a 2026 car can only show up as the generic car (team 41), which is also the F1 World car, so the
  generic car in format 2025 is an F1 car of unknown generation (``f1``, ``certain`` False). A real 2025 team id
  (0-9) in format 2025 is a 2025 car.
* **Families** (``f1``, ``f2``, ``other``) are what track models, the physics brake prior and setup formats key on.
* Non-F1 games (GT7, Forza, Assetto Corsa) report no formula: they get no class at all, never a guess.

Pure: standard library and ``adapters.f1.enums`` only. The capability status of a class (``evidence``) is looked up
lazily in ``pitwall.capabilities`` when a class is serialised, so this module never imports the adapters.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pitwall.adapters.f1 import enums

CarClassId = Literal["f1_2025", "f1_2026", "f1", "f2", "f1_classic", "other"]
CarFamily = Literal["f1", "f2", "other"]
Generation = Literal["f1_2025", "f1_2026"]

F1_GAMES = frozenset({"f1_25"})
FAMILIES: tuple[CarFamily, ...] = ("f1", "f2", "other")

# --- formulas (EA spec appendix 8.12, as enums.FORMULA names them) ----------------------------------------------
FORMULA_F2 = "F2"
FORMULA_2026 = "F1 26"
FORMULA_CLASSIC = "F1 Classic"
FORMULA_BETA = "Beta"
FORMULAS_F1 = frozenset({"F1 Modern", "F1 Generic", "Esports", "F1 World", "F1 Elimination"})

# --- team ids (EA spec appendix 8.1; 209-219 observed, see enums.OBSERVED_F2_TEAMS_FMT2025) ---------------------
TEAMS_F1_2025 = frozenset(range(10))  # Mercedes .. Sauber (both formats)
TEAMS_F1_2026 = frozenset(range(476, 487))  # Mercedes '26 .. Cadillac '26 (format 2026 only)
TEAMS_F1_GENERIC = frozenset({41, 104})  # F1 Generic, F1 Custom Team (My Team)
TEAMS_F1_OTHER = frozenset({129, 142, 154, 155, *range(185, 195)})  # Konnersport, APXGP, the '24 F1 teams
TEAMS_F1 = TEAMS_F1_2025 | TEAMS_F1_2026 | TEAMS_F1_GENERIC | TEAMS_F1_OTHER
TEAMS_F2_2024 = frozenset(range(158, 169))  # Art GP '24 .. Invicta '24
TEAMS_F2_2025_OBSERVED = frozenset(enums.OBSERVED_F2_TEAMS_FMT2025)  # 209-219, format 2025 (observed on PS5)
TEAMS_F2_2025 = frozenset(range(465, 476))  # Art GP '25 .. Invicta '25 (format 2026 ids)
TEAMS_F2_2026 = frozenset(range(489, 500))  # Art GP '26 .. Invicta '26 (2026 doc v1.2)
TEAMS_F2 = TEAMS_F2_2024 | TEAMS_F2_2025_OBSERVED | TEAMS_F2_2025 | TEAMS_F2_2026

CLASS_LABELS: Mapping[CarClassId, str | None] = {
    "f1_2025": "F1",
    "f1": "F1",
    "f1_2026": "F1 (2026)",
    "f2": "F2",
    "f1_classic": "Classic F1",
    "other": None,
}
FAMILY_LABELS: Mapping[CarFamily, str | None] = {"f1": "F1", "f2": "F2", "other": None}
_FAMILY: Mapping[CarClassId, CarFamily] = {
    "f1_2025": "f1",
    "f1_2026": "f1",
    "f1": "f1",
    "f2": "f2",
    "f1_classic": "other",
    "other": "other",
}
_HAS_ERS: Mapping[CarClassId, bool | None] = {
    "f1_2025": True,
    "f1_2026": True,
    "f1": True,
    "f2": False,  # recorded: F1 25 on PS5 sends 0 for every ERS and hybrid field of an F2 car
    "f1_classic": None,
    "other": None,
}
F2_NO_ERS_NOTE = "F2 cars have no ERS: F1 25 sends 0 for them."
_NOTES: Mapping[CarClassId, tuple[str, ...]] = {"f2": (F2_NO_ERS_NOTE,)}

# session types the F2 weekend names differently (spec appendix 8.5 "Race" 15 / "Race 2" 16). Recorded in F1 25 on PS5
# (2026-10-11): Session.weekendStructure listed (15, 16) at Melbourne and (one-shot qualifying, 16) at Sakhir and
# Jeddah; sessionDuration was 2700 s (45 minutes) for 15 and 3600 s (60 minutes) for 16, and the 16 races paid feature
# points (25 to the winner at Jeddah). So 16 is the feature race, and 15 is the sprint only in a weekend whose
# structure also has a 16 (a race-only weekend's 15 stays "Race": not recorded).
SESSION_TYPE_RACE_2 = 16  # spec 8.5 "Race 2"
F2_SESSION_LABELS: Mapping[str, str] = {"Race": "Sprint race", "Race 2": "Feature race"}
F2_RACE_KIND: Mapping[str, str] = {"Race": "sprint", "Race 2": "feature"}
# the F1 games' own session names (spec appendix 8.5), shown in sentence case ("One-Shot Qualifying" -> "One-shot
# qualifying", as Drive writes them)
F1_SESSION_NAMES = frozenset(label for label, _ in enums.SESSION_TYPES.values())
_SESSION_WORDS: Mapping[str, str] = {
    "race": "Race",
    "qualifying": "Qualifying",
    "practice": "Practice",
    "time_trial": "Time trial",
}


@dataclass(frozen=True, slots=True)
class CarClass:
    """The class of the car a session was driven in. ``formula`` is the game's own word (None = not reported);
    ``certain`` is False only for an F1 car whose generation the game does not tell (``f1``)."""

    id: CarClassId
    formula: str | None
    certain: bool = True
    game: str = "f1_25"
    # what the evidence status depends on (``evidence``): the car's team id and the UDP format it reported
    team: int | None = field(default=None, compare=False)
    packet_format: int | None = field(default=None, compare=False)

    @property
    def family(self) -> CarFamily:
        return _FAMILY[self.id]

    @property
    def label(self) -> str | None:
        return CLASS_LABELS[self.id]

    @property
    def has_ers(self) -> bool | None:
        return _HAS_ERS[self.id]

    @property
    def chip(self) -> bool:
        """Show a class chip next to the car / track: anything but an F1 car, when it has a name."""
        return self.family != "f1" and self.label is not None

    @property
    def notes(self) -> tuple[str, ...]:
        return _NOTES.get(self.id, ())

    @property
    def evidence(self) -> str | None:
        """``capabilities.CAR_CLASSES`` status of this class in its game, for this car (a variant that was never
        recorded, such as a 2026 F2 car, is only spec_implemented). Looked up lazily: no import cycle."""
        from pitwall.capabilities import car_class_status

        return car_class_status(self.game, self.id, team=self.team, packet_format=self.packet_format)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family": self.family,
            "label": self.label,
            "formula": self.formula,
            "certain": self.certain,
            "has_ers": self.has_ers,
            "chip": self.chip,
            "evidence": self.evidence,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------------------------- helpers
def team_id(car_id: object) -> int | None:
    """EA team id from pitwall's ``"f1:team:<id>"`` (None for other games and unknown cars)."""
    if isinstance(car_id, str) and car_id.startswith("f1:team:"):
        tail = car_id.rsplit(":", 1)[1]
        if tail.isdigit():
            return int(tail)
    return None


def _int(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _str(v: object) -> str | None:
    return v if isinstance(v, str) and v else None


def f1_generation(packet_format: object, formula: object, car_id: object) -> tuple[Generation | None, bool, str]:
    """``(generation, certain, reason)`` of an F1 car (formula 2025-family, F1 26, or an F1 team without a formula).

    The rules of ``carsetup.context`` (the car setup catalogue keys on them): formula F1 26 or a 2026 team id is a
    2026 car; in UDP format 2026 anything else that is an F1 car is a 2025 car; in format 2025 a real 2025 team id
    (0-9) is a 2025 car and the generic car (or an unknown one) cannot be told apart."""
    team = team_id(car_id)
    fmt = _int(packet_format)
    form = _str(formula)
    if form == FORMULA_2026 or team in TEAMS_F1_2026:
        why = "formula F1 26" if form == FORMULA_2026 else f"2026 team id {team}"
        return "f1_2026", True, f"{why} (2026 Season Pack car)"
    if fmt == 2026:
        if form in FORMULAS_F1 or team in TEAMS_F1_2025:
            return "f1_2025", True, "UDP format 2026 reports 2026 cars as formula F1 26; this is not one"
        return None, False, "UDP format 2026 without a formula or team that identifies the car"
    if team in TEAMS_F1_2025:
        return "f1_2025", True, f"2025 team id {team} (in UDP format 2025 a 2026 car reports as the generic car)"
    if team in TEAMS_F1_GENERIC or team is None:
        what = "the generic car" if team is not None else "an unknown car"
        return (
            None,
            False,
            f"{what} in UDP format {fmt or 'unknown'}: 2025 and 2026 cars cannot be told apart, choose the car "
            "format (or set the game's UDP format to 2026)",
        )
    return None, False, f"team id {team} is not a known F1 team"


# ---------------------------------------------------------------------------------------------- classification
def classify(game: object, formula: object, car_id: object, packet_format: object = None) -> CarClass | None:
    """The class of a car, or None when it cannot be told (a non-F1 game, or an F1 row with neither a formula nor a
    known team id)."""
    g = _str(game)
    if g not in F1_GAMES:
        return None
    assert g is not None
    form = _str(formula)
    team = team_id(car_id)
    fmt = _int(packet_format)
    if form is not None:
        if form == FORMULA_F2:
            return CarClass("f2", form, game=g, team=team, packet_format=fmt)
        if form == FORMULA_CLASSIC:
            return CarClass("f1_classic", form, game=g, team=team, packet_format=fmt)
        if form == FORMULA_2026 or form in FORMULAS_F1:
            return _f1_class(g, packet_format, form, car_id)
        return CarClass("other", form, game=g, team=team, packet_format=fmt)  # Beta, or a formula not in this table
    if team in TEAMS_F2:
        return CarClass("f2", None, game=g, team=team, packet_format=fmt)
    if team in TEAMS_F1:
        return _f1_class(g, packet_format, None, car_id)
    return None


def _f1_class(game: str, packet_format: object, formula: str | None, car_id: object) -> CarClass:
    gen, certain, _ = f1_generation(packet_format, formula, car_id)
    team, fmt = team_id(car_id), _int(packet_format)
    if gen == "f1_2026":
        return CarClass("f1_2026", formula, game=game, team=team, packet_format=fmt)
    if gen == "f1_2025" and certain:
        return CarClass("f1_2025", formula, game=game, team=team, packet_format=fmt)
    return CarClass("f1", formula, certain=False, game=game, team=team, packet_format=fmt)


def classify_row(row: Mapping[str, Any] | None) -> CarClass | None:
    """The class of a stored session row (``repo.get_session`` / ``list_sessions``: ``info`` holds the formula and
    the packet format)."""
    if not row:
        return None
    info = row.get("info")
    extra: Mapping[str, Any] = info if isinstance(info, Mapping) else {}
    return classify(row.get("game"), extra.get("formula"), row.get("car_id"), extra.get("packet_format"))


def classify_info(info: Any) -> CarClass | None:
    """The class of a live ``SessionInfo`` (duck-typed: ``game``, ``formula``, ``car_id``, ``extra``)."""
    if info is None:
        return None
    game = getattr(info, "game", None)
    game_v = getattr(game, "value", game)
    extra = getattr(info, "extra", None) or {}
    return classify(game_v, getattr(info, "formula", None), getattr(info, "car_id", None), extra.get("packet_format"))


def family_of(game: object, formula: object, car_id: object, packet_format: object = None) -> CarFamily | None:
    cls = classify(game, formula, car_id, packet_format)
    return None if cls is None else cls.family


def family_of_row(row: Mapping[str, Any] | None) -> CarFamily | None:
    cls = classify_row(row)
    return None if cls is None else cls.family


def family_label(family: object) -> str | None:
    """ "F1", "F2"; None for ``other`` and unknown families."""
    return FAMILY_LABELS.get(family) if isinstance(family, str) else None  # type: ignore[call-overload]


# ---------------------------------------------------------------------------------------------- labels
def f2_team_name(team: int | None, packet_format: object, formula: object) -> str | None:
    """The readable name of an F2 team id: the spec's name (158-168, 465-475, 489-499), else, in UDP format 2025 with
    formula F2 or no formula, the 2025 F2 team pitwall's PS5 recording places at 209-219. Never a raw id."""
    if team is None:
        return None
    if team in TEAMS_F2 and team in enums.TEAMS:
        return enums.TEAMS[team]
    form = _str(formula)
    if team in enums.OBSERVED_F2_TEAMS_FMT2025 and _int(packet_format) == 2025 and form in (None, FORMULA_F2):
        return enums.OBSERVED_F2_TEAMS_FMT2025[team]
    return None


_RAW_TEAM = re.compile(r"^(?:team_\d+|f1:team:\d+|Unknown team.*)$")


def _readable(car_name: object) -> str | None:
    """A stored car name unless it is a raw id: the adapter's neutral fallback for an unknown team id ("Unknown team
    (id 214)"), or the older "team_214" form some stored sessions still carry."""
    name = _str(car_name)
    if name is None or _RAW_TEAM.match(name):
        return None
    return name


def car_label(cls: CarClass | None, car_name: object, car_id: object, packet_format: object = None) -> str | None:
    """What to call the car: "F2 · Art GP '24", "F2 car" (team not known), "Classic F1 · Ferrari", "McLaren", the
    car's own name in other games. None when nothing readable is known; never a raw id."""
    if cls is None:
        return _readable(car_name)
    team = team_id(car_id)
    if cls.id == "f2":
        name = f2_team_name(team, packet_format, cls.formula)
        return f"F2 · {name}" if name else "F2 car"
    if cls.id == "f1_classic":
        name = enums.TEAMS.get(team) if team is not None else None
        return f"Classic F1 · {name}" if name else "Classic F1 car"
    return _readable(car_name)


def weekend_types(weekend: object) -> tuple[int, ...] | None:
    """The session type ids of the game's weekend structure (``SessionInfo.extra["weekend_structure"]``, F1
    ``m_weekendStructure``); None when not known (an older stored session, or the game sent none)."""
    if not isinstance(weekend, list | tuple) or not weekend:
        return None
    ids = tuple(v for v in weekend if isinstance(v, int) and not isinstance(v, bool))
    return ids if len(ids) == len(weekend) else None


def f2_race_kind(cls: CarClass | None, session_type_raw: object, weekend: object = None) -> str | None:
    """``"feature"`` for an F2 car's "Race 2"; ``"sprint"`` for its "Race" when the weekend also has a "Race 2" (the
    game's weekend structure says so); None otherwise (a race-only weekend, or the structure not known)."""
    raw = _str(session_type_raw)
    if cls is None or cls.id != "f2" or raw is None:
        return None
    kind = F2_RACE_KIND.get(raw)
    if kind == "sprint":
        types = weekend_types(weekend)
        return kind if types is not None and SESSION_TYPE_RACE_2 in types else None
    return kind


def _sentence(name: str) -> str:
    return name[:1].upper() + name[1:].lower()


def session_label(
    cls: CarClass | None, session_type_raw: object, session_type: object = None, weekend: object = None
) -> str | None:
    """The session's name: an F2 weekend's "Feature race" (the game's "Race 2") and "Sprint race" (its "Race", when
    the weekend has a "Race 2": ``f2_race_kind``); else the F1 game's own name in sentence case ("One-shot
    qualifying"), another game's own name unchanged; else pitwall's session type in words. None when unknown."""
    raw = _str(session_type_raw)
    if raw is not None:
        kind = f2_race_kind(cls, raw, weekend)
        if kind is not None:
            return F2_SESSION_LABELS[raw]
        if raw == "Unknown" or raw.startswith("unknown_"):
            return None
        return _sentence(raw) if raw in F1_SESSION_NAMES else raw
    st = getattr(session_type, "value", session_type)
    return _SESSION_WORDS.get(st) if isinstance(st, str) else None


def compound_words(label: object) -> str | None:
    """A tyre compound label in words: "super_soft" -> "super soft". None stays None."""
    s = _str(label)
    return None if s is None else s.replace("_", " ")


def session_fields(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """``car_class``, ``car_label`` and ``session_label`` of a stored session row (the API's session rows)."""
    if not row:
        return {"car_class": None, "car_label": None, "session_label": None}
    cls = classify_row(row)
    info = row.get("info")
    extra: Mapping[str, Any] = info if isinstance(info, Mapping) else {}
    return {
        "car_class": None if cls is None else cls.to_dict(),
        "car_label": car_label(cls, row.get("car_name"), row.get("car_id"), extra.get("packet_format")),
        "session_label": session_label(
            cls, row.get("session_type_raw"), row.get("session_type"), extra.get("weekend_structure")
        ),
    }


def info_fields(info: Any) -> dict[str, Any]:
    """The same three fields for a live ``SessionInfo``."""
    if info is None:
        return {"car_class": None, "car_label": None, "session_label": None}
    cls = classify_info(info)
    extra = getattr(info, "extra", None) or {}
    return {
        "car_class": None if cls is None else cls.to_dict(),
        "car_label": car_label(
            cls, getattr(info, "car_name", None), getattr(info, "car_id", None), extra.get("packet_format")
        ),
        "session_label": session_label(
            cls,
            getattr(info, "session_type_raw", None),
            getattr(info, "session_type", None),
            extra.get("weekend_structure"),
        ),
    }
