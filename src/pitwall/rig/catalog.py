"""Rig catalogue: research revision 2 (verbatim) plus pitwall's curation overlay, validated and indexed.

Source of truth, two files in ``data/``:

* ``rig_research.json``: a byte-for-byte copy of ``docs/research/rig-presets-draft.json`` (schema revision 2). Every
  value is ``{value, min, max, evidence, as_published?, note?}``; presets carry ``applies_to_platforms``,
  ``applies_to_torque_nm``, ``torque_basis``, ``pedal_settings`` and staleness; ``recommendations`` holds the
  game x torque x style wheel table and the game x pedals x style pedal table; ``pedal_reports`` are the BRF reports
  of owners of the exact pedal kit; ``rig_check`` lists 19 metrics. pitwall never edits this file: a new research
  revision is copied in as a whole (a unit test keeps the two copies identical).
* ``rig_pitwall.json``: what the app adds on top: preset codes, platforms and styles for the pickers, rims, the
  on-wheel menu order, value attributions the research left implicit, instruction texts for "values" that are not
  numbers (FFS after the Boost Kit: check on your base), driver rules, the section 5 consensus, known issues, open
  questions, the firmware/game timeline, guide steps and the rig-check display metadata (labels, units, thresholds
  in display units). The loader checks the overlay's thresholds against the research thresholds.

Design decisions:

* **Provenance is computed and enforced here, once.** For every recommended value that is not a pitwall derivation
  (evidence V/A/U), the loader finds the published values behind it: a basis preset that publishes the same value
  (``sourced``), a basis preset whose published *range* contains it (``range_pick``: the range is sourced, the
  start value inside it is pitwall's choice and is labelled D), an overlay attribution, a non-preset citation, or
  an instruction. A value with none of these fails loading, so a number can never be shown as verified against a
  source that says something else. A value backed only by presets written for another torque is flagged as a
  torque transfer (e.g. GT7 realism at 5 Nm comes from an 8 Nm setup).
* **Evidence is never upgraded.** A value's label is the weakest of the research label and the best label among the
  presets that publish it; a pick inside a range is D.
* **Stdlib-only validation** with typed readers that raise ``CatalogError`` with the JSON path of the first problem.
* **Immutable, cached**: ``load_catalog()`` parses once per process; records are frozen dataclasses.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal, cast, get_args

Evidence = Literal["V", "A", "U", "D", "H"]
StyleId = Literal["official_default", "balanced", "competitive", "realism", "comfort"]
GameId = Literal["f1_25", "gt7"]
PedalsId = Literal["csl", "csl_load_cell"]  # the app's ids (stored in rig profiles); research ids via the overlay
Confidence = Literal["high", "medium", "low"]
BackingKind = Literal["sourced", "range_pick", "derived", "cited", "instruction"]
RangeBasis = Literal["published", "across_sources", "derived"]
Direction = Literal["lower_better", "higher_better", "abs_lower_better", "driver_relative", "info"]

EVIDENCE: tuple[str, ...] = get_args(Evidence)
VALUE_EVIDENCE: tuple[str, ...] = ("V", "A", "U", "D")
EVIDENCE_RANK: Mapping[str, int] = {"V": 3, "A": 2, "U": 1, "D": 0}
STYLES: tuple[StyleId, ...] = get_args(StyleId)
GAMES: tuple[GameId, ...] = get_args(GameId)
PEDALS: tuple[PedalsId, ...] = get_args(PedalsId)
DIRECTIONS: tuple[str, ...] = get_args(Direction)
TORQUES_NM: tuple[int, ...] = (5, 8)
# Research convention ``off_encoding``: numeric Tuning Menu parameters whose range starts with OFF encode OFF as 0.
OFF_KEYS: frozenset[str] = frozenset({"FF", "NDP", "NFR", "NIN", "INT", "FOR", "SPR", "DPR", "FUL", "BLI"})
STATUSES = ("current", "stale", "superseded", "not_for_ps5")
_DATE = re.compile(r"\d{4}-\d{2}(-\d{2})?")

DATA_DIR = Path(str(resources.files("pitwall.rig") / "data"))
RESEARCH_PATH = DATA_DIR / "rig_research.json"
OVERLAY_PATH = DATA_DIR / "rig_pitwall.json"


class CatalogError(ValueError):
    """The catalogue files do not match the expected schema."""


# ---------------------------------------------------------------------------------------------- typed readers
class _R:
    """Typed accessors over a JSON object that report the JSON path of the first schema violation."""

    def __init__(self, data: object, path: str) -> None:
        if not isinstance(data, dict):
            raise CatalogError(f"{path}: expected an object")
        self.d: dict[str, Any] = data
        self.path = path

    def _get(self, key: str, optional: bool) -> Any:
        if key not in self.d:
            if optional:
                return None
            raise CatalogError(f"{self.path}.{key}: missing")
        return self.d[key]

    def text(self, key: str) -> str:
        v = self._get(key, False)
        if not isinstance(v, str) or not v:
            raise CatalogError(f"{self.path}.{key}: expected a non-empty string")
        return v

    def opt_text(self, key: str) -> str | None:
        v = self._get(key, True)
        if v is None:
            return None
        if not isinstance(v, str):
            raise CatalogError(f"{self.path}.{key}: expected a string or null")
        return v or None

    def flag(self, key: str, default: bool | None = None) -> bool:
        v = self._get(key, default is not None)
        if v is None and default is not None:
            return default
        if not isinstance(v, bool):
            raise CatalogError(f"{self.path}.{key}: expected a boolean")
        return v

    def opt_num(self, key: str) -> float | None:
        v = self._get(key, True)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise CatalogError(f"{self.path}.{key}: expected a number or null")
        return float(v)

    def choice(self, key: str, options: Sequence[str]) -> str:
        v = self.text(key)
        if v not in options:
            raise CatalogError(f"{self.path}.{key}: {v!r} is not one of {list(options)}")
        return v

    def seq(self, key: str, optional: bool = False) -> list[Any]:
        v = self._get(key, optional)
        if v is None and optional:
            return []
        if not isinstance(v, list):
            raise CatalogError(f"{self.path}.{key}: expected a list")
        return v

    def texts(self, key: str, optional: bool = False) -> tuple[str, ...]:
        items = self.seq(key, optional)
        if not all(isinstance(x, str) for x in items):
            raise CatalogError(f"{self.path}.{key}: expected a list of strings")
        return tuple(items)

    def ints(self, key: str, optional: bool = False) -> tuple[int, ...]:
        items = self.seq(key, optional)
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in items):
            raise CatalogError(f"{self.path}.{key}: expected a list of integers")
        return tuple(items)

    def obj(self, key: str, optional: bool = False) -> _R:
        v = self._get(key, optional)
        return _R({} if v is None else v, f"{self.path}.{key}")

    def items(self) -> Iterable[tuple[str, Any]]:
        return self.d.items()


def _evidence(r: _R, key: str = "evidence", allowed: Sequence[str] = EVIDENCE) -> Evidence:
    return cast(Evidence, r.choice(key, allowed))


def weakest(*labels: Evidence) -> Evidence:
    """The least certain of several value labels (V > A > U > D)."""
    return min(labels, key=lambda e: EVIDENCE_RANK.get(e, 0))


def first_date(text: str | None) -> str | None:
    """The first YYYY-MM(-DD) in a free-text publication field ("2026-05-29 (modified 2026-09-27)")."""
    m = _DATE.search(text or "")
    return m.group(0) if m else None


# ---------------------------------------------------------------------------------------------- values
Scalar = str | int | float


@dataclass(frozen=True, slots=True)
class SettingValue:
    """One value as the research records it: a single ``value``, a published ``min``-``max`` range, or both (a
    start value inside a range). ``value`` None with no range means the setting does not exist in that
    configuration; ``as_published`` keeps the source's own label."""

    value: Scalar | None
    min: float | None
    max: float | None
    evidence: Evidence
    as_published: str | None = None
    note: str | None = None

    @property
    def number(self) -> float | None:
        v = self.value
        return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

    @property
    def has_range(self) -> bool:
        return self.min is not None and self.max is not None

    def same_value(self, other: SettingValue) -> bool:
        """Same single value (numbers by value, strings case-insensitively)."""
        a, b = self.value, other.value
        if a is None or b is None:
            return False
        na, nb = self.number, other.number
        if na is not None and nb is not None:
            return math.isclose(na, nb, abs_tol=1e-9)
        return str(a).strip().lower() == str(b).strip().lower()

    def contains(self, x: float) -> bool:
        return self.min is not None and self.max is not None and self.min - 1e-9 <= x <= self.max + 1e-9

    def same_range(self, other: SettingValue) -> bool:
        return (
            self.has_range
            and other.has_range
            and math.isclose(cast(float, self.min), cast(float, other.min), abs_tol=1e-9)
            and math.isclose(cast(float, self.max), cast(float, other.max), abs_tol=1e-9)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "min": self.min,
            "max": self.max,
            "evidence": self.evidence,
            "as_published": self.as_published,
            "note": self.note,
        }


def format_number(key: str, x: float) -> str:
    """Menu display of one number: OFF for 0 on OFF-encoded Tuning Menu keys, BRF as three digits ("050")."""
    if key in OFF_KEYS and x == 0:
        return "OFF"
    s = str(int(x)) if float(x).is_integer() else f"{x:g}"
    if key == "BRF" and float(x).is_integer() and 0 <= x < 100:
        return f"{int(x):03d}"
    return s


def format_value(key: str, v: SettingValue) -> str | None:
    """The value as a driver types it on the wheel or in the game, or None when there is no single value."""
    if v.value is None:
        if v.has_range:
            return format_range(key, v)
        return None
    n = v.number
    return format_number(key, n) if n is not None else str(v.value)


def format_range(key: str, v: SettingValue) -> str | None:
    if not v.has_range:
        return None
    return f"{format_number(key, cast(float, v.min))}-{format_number(key, cast(float, v.max))}"


# ---------------------------------------------------------------------------------------------- records
@dataclass(frozen=True, slots=True)
class Source:
    url: str
    author: str
    published: str  # free text as researched ("2026-05-29 (modified 2026-09-27)")
    verified: bool  # an adversarial verifier re-checked it in the research round
    values_evidence: str | None = None
    game_version: str | None = None
    software: str | None = None
    source_hardware: str | None = None
    note: str | None = None

    @property
    def date(self) -> str | None:
        return first_date(self.published)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "author": self.author,
            "published": self.published,
            "verified": self.verified,
            "values_evidence": self.values_evidence,
            "game_version": self.game_version,
            "software": self.software,
            "source_hardware": self.source_hardware,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Param:
    """A setting that exists on the hardware or in a game menu (range, default and meaning as documented)."""

    key: str
    label: str
    range: str
    default: str
    meaning: str
    evidence: Evidence
    unit: str | None = None
    menu: str | None = None  # wheel base: both | advanced | hardware (some carry a qualifier)
    value_type: str | None = None
    min: float | None = None
    max: float | None = None
    standard_min: float | None = None
    enum_values: tuple[str, ...] = ()
    default_value: Scalar | None = None
    section: str | None = None
    pedal_dependent: bool = False
    source_url: str | None = None
    availability: str | None = None

    @property
    def factory_default(self) -> str | None:
        if self.default_value is None:
            return None
        v = self.default_value
        if isinstance(v, int | float) and not isinstance(v, bool):
            return format_number(self.key, float(v))
        return str(v)

    @property
    def advanced_only(self) -> bool:
        return (self.menu or "").startswith("advanced")


@dataclass(frozen=True, slots=True)
class FirmwareEra:
    id: str
    label: str
    app: str
    base_fw: str
    start: str | None
    changes: str


@dataclass(frozen=True, slots=True)
class WheelBase:
    id: str
    name: str
    torque_variants_nm: tuple[int, ...]
    platforms: tuple[str, ...]
    firmware_eras: Mapping[str, FirmwareEra]
    params: Mapping[str, Param]


@dataclass(frozen=True, slots=True)
class PedalModel:
    id: str  # research id (fanatec_csl_pedals, ...)
    name: str
    brake_sensor: str
    user_rig: str | None  # "now" | "arriving" | None (reference only)
    params: Mapping[str, Param]


@dataclass(frozen=True, slots=True)
class GameVersion:
    id: str
    label: str
    date: str
    ffb_relevant: bool
    notes: str


@dataclass(frozen=True, slots=True)
class Game:
    id: GameId
    name: str
    platforms: tuple[str, ...]
    versions: Mapping[str, GameVersion]
    params: Mapping[str, Param]  # insertion order = menu order


@dataclass(frozen=True, slots=True)
class PedalSettings:
    pedal_model: str
    transferable_to_pedals: tuple[str, ...]
    values: Mapping[str, SettingValue]


@dataclass(frozen=True, slots=True)
class Preset:
    id: str
    code: str
    name: str
    game: GameId
    platform: str  # where pitwall offers it (one of the game's platforms)
    applies_to_platforms: tuple[str, ...]
    source_platform: str  # where the author configured it: pc | ps5 | pc_ps5 | xbox | playstation | ...
    ps5_reachable: bool
    ps5_note: str | None
    wheel_base: str
    source_wheel_base: str | None
    torque_nm: int | None  # the source's own torque (None: not stated)
    applies_to_torque_nm: tuple[int, ...]
    torque_basis: str
    pedals: str | None  # research pedal model id
    pedals_basis: str
    preference: StyleId
    preference_basis: str
    preference_source_words: str | None
    game_version: str
    game_version_predates: tuple[str, ...]
    firmware_era: str
    firmware_era_basis: str
    firmware_note: str | None
    status: str
    stale: bool
    stale_reasons: tuple[str, ...]
    superseded_by: str | None
    wheel_settings: Mapping[str, SettingValue]
    ingame_settings: Mapping[str, SettingValue]
    pedal_settings: PedalSettings | None
    sources: tuple[Source, ...]
    confidence: Confidence
    notes: str

    @property
    def published(self) -> str:
        return self.sources[0].date or self.sources[0].published

    def setting(self, key: str) -> SettingValue | None:
        if key in self.wheel_settings:
            return self.wheel_settings[key]
        if key in self.ingame_settings:
            return self.ingame_settings[key]
        if self.pedal_settings is not None:
            return self.pedal_settings.values.get(key)
        return None

    def available_on(self, platform: str) -> bool:
        """Offered on ``platform``: its values are valid there (``applies_to_platforms``) and, on PS5, every item
        can be set from the Tuning Menu and the game menu. The Xbox column is never offered on PS5."""
        return platform in self.applies_to_platforms and (platform != "ps5" or self.ps5_reachable)

    def applies_at(self, torque_nm: int) -> bool:
        return torque_nm in self.applies_to_torque_nm

    def summary(self) -> dict[str, Any]:
        def values(m: Mapping[str, SettingValue]) -> dict[str, Any]:
            return {k: {**v.to_dict(), "display": format_value(k, v)} for k, v in m.items()}

        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "game": self.game,
            "platform": self.platform,
            "applies_to_platforms": list(self.applies_to_platforms),
            "source_platform": self.source_platform,
            "ps5_reachable": self.ps5_reachable,
            "torque_nm": self.torque_nm,
            "applies_to_torque_nm": list(self.applies_to_torque_nm),
            "torque_basis": self.torque_basis,
            "pedals": self.pedals,
            "pedals_basis": self.pedals_basis,
            "preference": self.preference,
            "preference_inferred": self.preference_basis != "source_words",
            "source_words": self.preference_source_words,
            "published": self.published,
            "game_version": self.game_version,
            "firmware_era": self.firmware_era,
            "status": self.status,
            "stale": self.stale,
            "stale_reasons": list(self.stale_reasons),
            "superseded_by": self.superseded_by,
            "confidence": self.confidence,
            "notes": self.notes,
            "sources": [s.to_dict() for s in self.sources],
            "wheel_settings": values(self.wheel_settings),
            "ingame_settings": values(self.ingame_settings),
            "pedal_settings": None
            if self.pedal_settings is None
            else {
                "pedal_model": self.pedal_settings.pedal_model,
                "transferable_to_pedals": list(self.pedal_settings.transferable_to_pedals),
                "values": values(self.pedal_settings.values),
            },
        }


@dataclass(frozen=True, slots=True)
class PedalReport:
    """A BRF value reported by an owner of a pedal kit (only CSL Pedals Load Cell Kit reports are catalogued)."""

    id: str
    owner: str
    pedals: str
    stock: bool
    modification: str | None
    values: Mapping[str, SettingValue]
    game: str | None
    torque_nm: int | None
    latest_for_owner: bool
    preference: str | None
    source_words: str | None
    sources: tuple[Source, ...]
    notes: str

    @property
    def published(self) -> str:
        return self.sources[0].date or self.sources[0].published

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "owner": self.owner,
            "pedals": self.pedals,
            "stock": self.stock,
            "modification": self.modification,
            "values": {k: {**v.to_dict(), "display": format_value(k, v)} for k, v in self.values.items()},
            "game": self.game,
            "torque_nm": self.torque_nm,
            "latest_for_owner": self.latest_for_owner,
            "preference": self.preference,
            "source_words": self.source_words,
            "published": self.published,
            "sources": [s.to_dict() for s in self.sources],
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class Backing:
    """Where one recommended value comes from (computed and validated at load time).

    ``kind``: ``sourced`` (a preset publishes this value), ``range_pick`` (a preset publishes a range that contains
    it; the start value is pitwall's, so ``evidence`` is D and ``range_evidence`` labels the range), ``derived``
    (pitwall derivation), ``cited`` (a non-preset source such as a manual or a single expert), ``instruction`` (not
    a number: e.g. "check on your base")."""

    kind: BackingKind
    evidence: Evidence
    presets: tuple[str, ...] = ()  # presets whose published value or range backs the value
    range_basis: RangeBasis | None = None
    range_evidence: Evidence | None = None
    range_presets: tuple[str, ...] = ()
    transfer_from_nm: tuple[int, ...] = ()  # set when only presets for another torque back the value
    attribution: str | None = None  # overlay note when the research left the source implicit


@dataclass(frozen=True, slots=True)
class WheelEntry:
    """``recommendations.wheel[game, torque, style]``: Tuning Menu and in-game values for one combination."""

    id: str
    game: GameId
    torque_nm: int
    preference: StyleId
    sourced: bool
    fallback_to: StyleId | None
    basis_presets: tuple[str, ...]
    wheel_settings: Mapping[str, SettingValue]
    ingame_settings: Mapping[str, SettingValue]
    confidence: str
    notes: str
    backing: Mapping[str, Backing] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.wheel_settings and not self.ingame_settings

    def value(self, key: str) -> SettingValue | None:
        return self.wheel_settings.get(key) or self.ingame_settings.get(key)


@dataclass(frozen=True, slots=True)
class KgEstimate:
    value_kg: float
    evidence: Evidence
    note: str


@dataclass(frozen=True, slots=True)
class PedalEntry:
    """``recommendations.pedals[game, pedals, style]``: BRF and in-game pedal calibration for one combination."""

    id: str
    game: GameId
    pedals: str  # research pedal model id
    preference: StyleId
    sourced: bool
    basis_presets: tuple[str, ...]
    basis_pedal_reports: tuple[str, ...]
    basis_sources: tuple[Source, ...]
    pedal_settings: PedalSettings | None
    ingame_settings: Mapping[str, SettingValue]
    kg_estimate: KgEstimate | None
    confidence: str
    notes: str
    backing: Mapping[str, Backing] = field(default_factory=dict)

    @property
    def pedal_values(self) -> Mapping[str, SettingValue]:
        return self.pedal_settings.values if self.pedal_settings is not None else {}


@dataclass(frozen=True, slots=True)
class ResearchRule:
    id: str
    game: str  # f1_25 | gt7 | any
    applies_to_preferences: tuple[str, ...]  # style ids or "any"
    rule: str
    evidence: Evidence
    basis_presets: tuple[str, ...]
    factor: float | None = None

    def applies(self, game: str, style: str) -> bool:
        return self.game in ("any", game) and (
            "any" in self.applies_to_preferences or style in self.applies_to_preferences
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game": self.game,
            "applies_to_preferences": list(self.applies_to_preferences),
            "rule": self.rule,
            "evidence": self.evidence,
            "basis_presets": list(self.basis_presets),
            "factor": self.factor,
        }


@dataclass(frozen=True, slots=True)
class BrfOwnerStats:
    population: str
    n: int
    values: tuple[float, ...]
    median: float
    min: float
    max: float
    evidence: Evidence
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "population": self.population,
            "n": self.n,
            "values": list(self.values),
            "median": self.median,
            "min": self.min,
            "max": self.max,
            "evidence": self.evidence,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Platform:
    id: str
    name: str
    base_mode: str
    base_mode_note: str
    tuning_interface: str


@dataclass(frozen=True, slots=True)
class Style:
    id: StyleId
    label: str
    description: str
    sourced: bool


@dataclass(frozen=True, slots=True)
class Rim:
    id: str
    name: str
    note: str
    has_items: tuple[str, ...]  # rim-dependent Tuning Menu items this rim is known to have
    unknown_items: tuple[str, ...]  # items whose presence on this rim is unverified


@dataclass(frozen=True, slots=True)
class Instruction:
    display: str
    rule: str | None
    note: str


@dataclass(frozen=True, slots=True)
class Consensus:
    n: int | None
    median: str | None
    range: str | None
    status: str  # consensus | strong | split | moot
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {"n": self.n, "median": self.median, "range": self.range, "status": self.status, "note": self.note}


@dataclass(frozen=True, slots=True)
class AppliesTo:
    """Filter for issues/questions/steps. Empty tuple = applies to every value of that dimension."""

    games: tuple[str, ...] = ()
    pedals: tuple[str, ...] = ()
    torque_nm: tuple[int, ...] = ()

    def matches(self, game: str | None = None, pedals: str | None = None, torque_nm: int | None = None) -> bool:
        return (
            (not self.games or game is None or game in self.games)
            and (not self.pedals or pedals is None or pedals in self.pedals)
            and (not self.torque_nm or torque_nm is None or torque_nm in self.torque_nm)
        )

    def to_dict(self) -> dict[str, Any]:
        return {"games": list(self.games), "pedals": list(self.pedals), "torque_nm": list(self.torque_nm)}


@dataclass(frozen=True, slots=True)
class KnownIssue:
    id: str
    title: str
    detail: str
    applies_to: AppliesTo
    evidence: Evidence
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "detail": self.detail,
            "applies_to": self.applies_to.to_dict(),
            "evidence": self.evidence,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class OpenQuestion:
    id: int
    question: str
    verify: str
    applies_to: AppliesTo

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "verify": self.verify,
            "applies_to": self.applies_to.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class GuideStep:
    id: str
    text: str
    evidence: Evidence
    source: str
    detail: str | None = None
    games: tuple[str, ...] = ()  # empty = every game

    def for_game(self, game: str) -> bool:
        return not self.games or game in self.games


@dataclass(frozen=True, slots=True)
class RigCheckSpec:
    """One telemetry rig-check metric: the research definition plus pitwall's display metadata."""

    metric: str
    label: str
    description: str
    unit: str
    direction: Direction
    thresholds: Mapping[str, float]  # pass_max / fail_above / pass_min / fail_below (display unit)
    threshold_evidence: Evidence
    good_range: str
    action_if_high: str
    action_if_low: str
    sources: tuple[str, ...]
    games: tuple[str, ...]
    pedals: tuple[str, ...]  # app pedal ids the thresholds apply to; empty = any pedals
    requires: tuple[str, ...]  # LapTrace channels the metric needs
    threshold_note: str | None = None
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class DriverRules:
    scale_min: float
    scale_max: float
    skill_scale: Mapping[str, float]
    scale_round_to: int
    scale_explanation: str
    ndp_floor: int
    ndp_floor_explanation: str
    driver_slot: str
    driver_slot_explanation: str


@dataclass(frozen=True, slots=True)
class Catalog:
    schema_revision: int
    research_date: str
    evidence_labels: Mapping[str, str]
    firmware: Mapping[str, str]
    wheel_base_id: str
    torque_labels: Mapping[int, str]
    pedal_models: Mapping[str, PedalModel]  # research ids
    pedals: Mapping[str, str]  # app id -> research id
    supported: frozenset[tuple[str, str]]
    platforms: Mapping[str, Platform]
    styles: Mapping[str, Style]
    wheel_bases: Mapping[str, WheelBase]
    rims: Mapping[str, Rim]
    rim_items: Mapping[str, str]
    games: Mapping[str, Game]
    presets: Mapping[str, Preset]
    pedal_reports: Mapping[str, PedalReport]
    wheel_entries: Mapping[tuple[str, int, str], WheelEntry]
    pedal_entries: Mapping[tuple[str, str, str], PedalEntry]  # (game, app pedals id, style)
    rules: Mapping[str, ResearchRule]
    common_steps: tuple[str, ...]
    brf_owner_stats: BrfOwnerStats
    instructions: Mapping[str, Instruction]
    derivations: Mapping[str, str]
    driver_rules: DriverRules
    menu_order: tuple[str, ...]
    menu_order_note: str
    consensus: Mapping[str, Mapping[str, Consensus]]
    known_issues: tuple[KnownIssue, ...]
    open_questions: tuple[OpenQuestion, ...]
    timeline: tuple[Mapping[str, str], ...]
    boost_kit_steps: tuple[GuideStep, ...]
    pedal_steps: Mapping[str, tuple[GuideStep, ...]]
    rig_check: Mapping[str, RigCheckSpec]

    # ------------------------------------------------------------------ queries
    def preset(self, preset_id: str) -> Preset:
        try:
            return self.presets[preset_id]
        except KeyError:
            raise KeyError(f"unknown preset {preset_id!r}") from None

    def presets_for(
        self,
        game: str | None = None,
        platform: str | None = None,
        wheel_base: str | None = None,
        torque_nm: int | None = None,
        pedals: str | None = None,
        preference: str | None = None,
        include_stale: bool = True,
    ) -> list[Preset]:
        """Presets matching every given filter. Torque filters on ``applies_to_torque_nm`` (the torques the values
        may be used at); ``pedals`` (an app id) keeps presets whose pedal-specific values transfer to those pedals or
        that state no pedals."""
        research_pedals = self.pedals.get(pedals) if pedals is not None else None
        out = []
        for p in self.presets.values():
            if game is not None and p.game != game:
                continue
            if platform is not None and not p.available_on(platform):
                continue
            if wheel_base is not None and p.wheel_base != wheel_base:
                continue
            if torque_nm is not None and not p.applies_at(torque_nm):
                continue
            if research_pedals is not None and p.pedals not in (None, research_pedals):
                ps = p.pedal_settings
                if ps is None or research_pedals not in ps.transferable_to_pedals:
                    continue
            if preference is not None and p.preference != preference:
                continue
            if not include_stale and p.stale:
                continue
            out.append(p)
        return out

    def wheel_entry(self, game: str, torque_nm: int, style: str) -> WheelEntry:
        try:
            return self.wheel_entries[(game, torque_nm, style)]
        except KeyError:
            raise KeyError(f"no wheel recommendation for {game}/{torque_nm} Nm/{style}") from None

    def pedal_entry(self, game: str, pedals: str, style: str) -> PedalEntry:
        try:
            return self.pedal_entries[(game, pedals, style)]
        except KeyError:
            raise KeyError(f"no pedal recommendation for {game}/{pedals}/{style}") from None

    def consensus_for(self, game: str, key: str) -> Consensus | None:
        return self.consensus.get(game, {}).get(key)

    def known_issues_for(self, game: str, pedals: str | None = None, torque_nm: int | None = None) -> list[KnownIssue]:
        return [i for i in self.known_issues if i.applies_to.matches(game, pedals, torque_nm)]

    def open_questions_for(
        self, game: str, pedals: str | None = None, torque_nm: int | None = None
    ) -> list[OpenQuestion]:
        return [q for q in self.open_questions if q.applies_to.matches(game, pedals, torque_nm)]

    def param(self, key: str, game: str | None = None, wheel_base: str | None = None) -> Param | None:
        """A wheel-base, pedal (BRF) or game parameter by key."""
        wb = self.wheel_bases.get(wheel_base or self.wheel_base_id)
        if wb is not None and key in wb.params:
            return wb.params[key]
        if game is not None and game in self.games and key in self.games[game].params:
            return self.games[game].params[key]
        lc = self.pedal_models.get(self.pedals["csl_load_cell"])
        return lc.params.get(key) if lc else None

    def summary(self) -> dict[str, Any]:
        """Everything the Setup UI needs to build its pickers (no per-value tables)."""
        wb = self.wheel_bases[self.wheel_base_id]
        return {
            "schema_revision": self.schema_revision,
            "research_date": self.research_date,
            "evidence_labels": dict(self.evidence_labels),
            "firmware": dict(self.firmware),
            "platforms": [
                {"id": p.id, "name": p.name, "base_mode": p.base_mode, "tuning_interface": p.tuning_interface}
                for p in self.platforms.values()
            ],
            "styles": [
                {"id": s.id, "label": s.label, "description": s.description, "sourced": s.sourced}
                for s in self.styles.values()
            ],
            "games": [
                {
                    "id": g.id,
                    "name": g.name,
                    "platforms": list(g.platforms),
                    "versions": [{"id": v.id, "label": v.label, "date": v.date} for v in g.versions.values()],
                }
                for g in self.games.values()
            ],
            "hardware": {
                "wheel_bases": [
                    {
                        "id": wb.id,
                        "name": wb.name,
                        "torque_variants": [
                            {"torque_nm": t, "label": self.torque_labels.get(t, f"{t} Nm")}
                            for t in wb.torque_variants_nm
                        ],
                        "firmware_eras": [
                            {"id": e.id, "label": e.label, "app": e.app, "base_fw": e.base_fw, "from": e.start}
                            for e in wb.firmware_eras.values()
                        ],
                    }
                ],
                "pedals": [
                    {
                        "id": app_id,
                        "model": rid,
                        "name": self.pedal_models[rid].name,
                        "brake_sensor": self.pedal_models[rid].brake_sensor,
                    }
                    for app_id, rid in self.pedals.items()
                ],
                "rims": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "note": r.note,
                        "has_items": list(r.has_items),
                        "unknown_items": list(r.unknown_items),
                    }
                    for r in self.rims.values()
                ],
            },
            "timeline": [dict(t) for t in self.timeline],
            "brf_owner_stats": self.brf_owner_stats.to_dict(),
            "rules": [r.to_dict() for r in self.rules.values()],
            "rig_check_metrics": [
                {
                    "metric": m.metric,
                    "label": m.label,
                    "unit": m.unit,
                    "good_range": m.good_range,
                    "threshold_evidence": m.threshold_evidence,
                    "games": list(m.games),
                    "pedals": list(m.pedals),
                }
                for m in self.rig_check.values()
            ],
        }


# ---------------------------------------------------------------------------------------------- parsing helpers
def _sv(r: _R) -> SettingValue:
    raw_value = r.d.get("value")
    if raw_value is not None and (isinstance(raw_value, bool) or not isinstance(raw_value, str | int | float)):
        raise CatalogError(f"{r.path}.value: expected a string, a number or null")
    sv = SettingValue(
        value=raw_value,
        min=r.opt_num("min"),
        max=r.opt_num("max"),
        evidence=_evidence(r, allowed=VALUE_EVIDENCE),
        as_published=r.opt_text("as_published"),
        note=r.opt_text("note"),
    )
    if (sv.min is None) != (sv.max is None):
        raise CatalogError(f"{r.path}: min and max must both be set or both be null")
    if sv.has_range and cast(float, sv.min) > cast(float, sv.max):
        raise CatalogError(f"{r.path}: min > max")
    if sv.has_range and sv.number is not None and not sv.contains(sv.number):
        raise CatalogError(f"{r.path}: value {sv.value} outside its own range {sv.min}-{sv.max}")
    return sv


def _values(r: _R, key: str, params: Mapping[str, Param], what: str) -> dict[str, SettingValue]:
    out: dict[str, SettingValue] = {}
    for k, raw in r.obj(key, optional=True).items():
        path = f"{r.path}.{key}.{k}"
        if k not in params:
            raise CatalogError(f"{path}: not a {what} parameter")
        sv = _sv(_R(raw, path))
        _check_in_param_range(sv, params[k], path)
        out[k] = sv
    return out


def _check_in_param_range(sv: SettingValue, p: Param, path: str) -> None:
    """Numbers must lie inside the parameter's documented range; enum strings must be documented values."""
    numbers = [x for x in (sv.number, sv.min, sv.max) if x is not None]
    for x in numbers:
        if (p.min is not None and x < p.min - 1e-9) or (p.max is not None and x > p.max + 1e-9):
            raise CatalogError(f"{path}: {x:g} outside {p.key}'s range {p.min}-{p.max}")
    if isinstance(sv.value, str) and p.enum_values:
        allowed = {e.lower() for e in p.enum_values}
        if sv.value.lower() not in allowed:
            raise CatalogError(f"{path}: {sv.value!r} is not one of {list(p.enum_values)}")


def _param(r: _R) -> Param:
    dv = r.d.get("default_value")
    if dv is not None and (isinstance(dv, bool) or not isinstance(dv, str | int | float)):
        raise CatalogError(f"{r.path}.default_value: expected a string, a number or null")
    return Param(
        key=r.text("key"),
        label=r.text("label"),
        range=r.opt_text("range") or "",
        default=r.opt_text("default") or "",
        meaning=r.opt_text("meaning") or "",
        evidence=_evidence(r, allowed=VALUE_EVIDENCE),
        unit=r.opt_text("unit"),
        menu=r.opt_text("menu"),
        value_type=r.opt_text("value_type"),
        min=r.opt_num("min"),
        max=r.opt_num("max"),
        standard_min=r.opt_num("standard_min"),
        enum_values=r.texts("enum_values", optional=True),
        default_value=dv,
        section=r.opt_text("section"),
        pedal_dependent=r.flag("pedal_dependent", False),
        source_url=r.opt_text("source_url"),
        availability=r.opt_text("availability"),
    )


def _params(r: _R, key: str) -> dict[str, Param]:
    out: dict[str, Param] = {}
    for i, raw in enumerate(r.seq(key, optional=True)):
        p = _param(_R(raw, f"{r.path}.{key}[{i}]"))
        if p.key in out:
            raise CatalogError(f"{r.path}.{key}: duplicate param {p.key}")
        out[p.key] = p
    return out


def _source(r: _R) -> Source:
    url = r.text("url")
    if not url.startswith(("http://", "https://")):
        raise CatalogError(f"{r.path}.url: not an http(s) URL")
    return Source(
        url=url,
        author=r.text("author"),
        published=r.text("published"),
        verified=r.flag("verified"),
        values_evidence=r.opt_text("values_evidence"),
        game_version=r.opt_text("game_version"),
        software=r.opt_text("software"),
        source_hardware=r.opt_text("source_hardware"),
        note=r.opt_text("note"),
    )


def _sources(r: _R, key: str, *, required: bool) -> tuple[Source, ...]:
    out = tuple(_source(_R(s, f"{r.path}.{key}[{j}]")) for j, s in enumerate(r.seq(key, optional=not required)))
    if required and not out:
        raise CatalogError(f"{r.path}.{key}: at least one source is needed")
    return out


def _pedal_settings(r: _R, key: str, models: Mapping[str, PedalModel]) -> PedalSettings | None:
    raw = r.d.get(key)
    if raw is None:
        return None
    pr = _R(raw, f"{r.path}.{key}")
    model = pr.text("pedal_model")
    if model not in models:
        raise CatalogError(f"{pr.path}.pedal_model: unknown pedal model {model!r}")
    transfer = pr.texts("transferable_to_pedals", optional=True)
    for t in transfer:
        if t not in models:
            raise CatalogError(f"{pr.path}.transferable_to_pedals: unknown pedal model {t!r}")
    return PedalSettings(model, transfer, _values(pr, "values", models[model].params, model))


def _applies(r: _R) -> AppliesTo:
    torque = r.ints("torque_nm", optional=True)
    if not all(t in TORQUES_NM for t in torque):
        raise CatalogError(f"{r.path}.torque_nm: expected values from {TORQUES_NM}")
    games = r.texts("games", optional=True)
    pedals = r.texts("pedals", optional=True)
    for g in games:
        if g not in GAMES:
            raise CatalogError(f"{r.path}.games: unknown game {g!r}")
    for p in pedals:
        if p not in PEDALS:
            raise CatalogError(f"{r.path}.pedals: unknown pedals {p!r}")
    return AppliesTo(games=games, pedals=pedals, torque_nm=torque)


def _steps(items: Sequence[Any], path: str) -> tuple[GuideStep, ...]:
    out = []
    ids: set[str] = set()
    for i, raw in enumerate(items):
        s = _R(raw, f"{path}[{i}]")
        sid = s.text("id")
        if sid in ids:
            raise CatalogError(f"{s.path}.id: duplicate step {sid}")
        ids.add(sid)
        games = s.texts("games", optional=True)
        for g in games:
            if g not in GAMES:
                raise CatalogError(f"{s.path}.games: unknown game {g!r}")
        text = s.d.get("text")
        if not isinstance(text, str):
            raise CatalogError(f"{s.path}.text: expected a string (empty only for computed steps)")
        out.append(
            GuideStep(
                id=sid,
                text=text,
                evidence=_evidence(s),
                source=s.text("source"),
                detail=s.opt_text("detail"),
                games=games,
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------------------------- provenance
def _backing(
    key: str,
    v: SettingValue,
    pool: Sequence[Preset],
    torque_nm: int | None,
    *,
    attribution: str | None,
    cited: bool,
    instruction: Instruction | None,
    path: str,
) -> Backing:
    """Reconcile one recommended value with the published values behind it (see the module docstring)."""
    if v.evidence == "D":
        rng = _range_backing(key, v, pool, torque_nm, derived=True)
        return Backing("derived", "D", **rng)
    if v.value is None and not v.has_range:
        if instruction is None:
            raise CatalogError(f"{path}: {key} has no value and no instruction text in the overlay")
        return Backing("instruction", v.evidence, attribution=attribution)

    def at(p: Preset) -> bool:
        return torque_nm is None or p.applies_at(torque_nm)

    setters = [(p, p.setting(key)) for p in pool]
    published = [(p, sv) for p, sv in setters if sv is not None]
    n = v.number
    exact = [(p, sv) for p, sv in published if v.value is not None and sv.same_value(v)]
    if v.value is None:  # a range with no start value: backed by the same published range
        exact = [(p, sv) for p, sv in published if sv.same_range(v)]
    containing = [(p, sv) for p, sv in published if n is not None and sv.contains(n)]
    rng = _range_backing(key, v, pool, torque_nm, derived=False)
    exact_at = [(p, sv) for p, sv in exact if at(p)]
    cont_at = [(p, sv) for p, sv in containing if at(p)]

    def best(items: Sequence[tuple[Preset, SettingValue]]) -> Evidence:
        return max((sv.evidence for _, sv in items), key=lambda e: EVIDENCE_RANK.get(e, 0))

    def transfer(items: Sequence[tuple[Preset, SettingValue]]) -> tuple[int, ...]:
        return tuple(sorted({t for p, _ in items for t in (p.applies_to_torque_nm or ())}))

    def sourced(items: Sequence[tuple[Preset, SettingValue]], **extra: Any) -> Backing:
        # A value whose only publishers carry D (a key mapping the research inferred) is a derivation, not a source.
        ev = weakest(v.evidence, best(items))
        kind: BackingKind = "derived" if ev == "D" else "sourced"
        return Backing(kind, ev, tuple(p.id for p, _ in items), attribution=attribution, **rng, **extra)

    if exact_at:
        return sourced(exact_at)
    if cont_at:
        return Backing("range_pick", "D", tuple(p.id for p, _ in cont_at), attribution=attribution, **rng)
    if exact:
        return sourced(exact, transfer_from_nm=transfer(exact))
    if containing:
        return Backing(
            "range_pick",
            "D",
            tuple(p.id for p, _ in containing),
            transfer_from_nm=transfer(containing),
            attribution=attribution,
            **rng,
        )
    if cited:
        return Backing("cited", v.evidence, attribution=attribution, **rng)
    raise CatalogError(
        f"{path}: {key}={v.value} ({v.evidence}) is not published by any basis preset "
        f"({', '.join(p.id for p in pool) or 'none'}) and has no other citation"
    )


def _range_backing(
    key: str, v: SettingValue, pool: Sequence[Preset], torque_nm: int | None, *, derived: bool
) -> dict[str, Any]:
    """How the value's published range (min-max) is backed: one preset publishes it, the basis presets' values span
    it, or it is pitwall's own range."""
    if not v.has_range:
        return {}
    lo, hi = cast(float, v.min), cast(float, v.max)
    published = [(p, sv) for p in pool if (sv := p.setting(key)) is not None]
    same = [(p, sv) for p, sv in published if sv.same_range(v)]
    if same:
        ev = max((sv.evidence for _, sv in same), key=lambda e: EVIDENCE_RANK.get(e, 0))
        return {"range_basis": "published", "range_evidence": ev, "range_presets": tuple(p.id for p, _ in same)}

    def touches(sv: SettingValue, x: float) -> bool:
        return (sv.number is not None and math.isclose(sv.number, x, abs_tol=1e-9)) or (
            sv.has_range and (math.isclose(cast(float, sv.min), x) or math.isclose(cast(float, sv.max), x))
        )

    low = [(p, sv) for p, sv in published if touches(sv, lo)]
    high = [(p, sv) for p, sv in published if touches(sv, hi)]
    if low and high and not derived:
        ev = weakest(
            max((sv.evidence for _, sv in low), key=lambda e: EVIDENCE_RANK.get(e, 0)),
            max((sv.evidence for _, sv in high), key=lambda e: EVIDENCE_RANK.get(e, 0)),
        )
        ids = tuple(dict.fromkeys(p.id for p, _ in (*low, *high)))
        return {"range_basis": "across_sources", "range_evidence": ev, "range_presets": ids}
    return {"range_basis": "derived", "range_evidence": "D", "range_presets": ()}


# ---------------------------------------------------------------------------------------------- parse
def parse_catalog(research: object, overlay: object) -> Catalog:
    """Validate and index the research document and the pitwall overlay. Raises ``CatalogError`` on the first
    problem."""
    root = _R(research, "$research")
    if root.d.get("version") != 1 or root.d.get("schema_revision") != 2:
        raise CatalogError("$research.schema_revision: only research schema revision 2 (version 1) is supported")
    ov = _R(overlay, "$overlay")
    if ov.d.get("overlay_version") != 1 or ov.d.get("research_schema_revision") != 2:
        raise CatalogError("$overlay.research_schema_revision: the overlay must target research schema revision 2")
    conv = root.obj("conventions")
    labels = conv.obj("evidence_labels")
    if set(labels.d) != set(EVIDENCE):
        raise CatalogError(f"$research.conventions.evidence_labels: expected exactly {list(EVIDENCE)}")

    # --- hardware
    hw = root.obj("hardware")
    wheel_bases: dict[str, WheelBase] = {}
    for i, raw in enumerate(hw.seq("wheel_bases")):
        r = _R(raw, f"$research.hardware.wheel_bases[{i}]")
        eras: dict[str, FirmwareEra] = {}
        for j, e in enumerate(r.seq("firmware_eras")):
            er = _R(e, f"{r.path}.firmware_eras[{j}]")
            eras[er.text("id")] = FirmwareEra(
                er.text("id"),
                er.text("label"),
                er.text("app"),
                er.text("base_fw"),
                er.opt_text("from"),
                er.text("changes"),
            )
        torques = r.ints("torque_variants_nm")
        if set(torques) != set(TORQUES_NM):
            raise CatalogError(f"{r.path}.torque_variants_nm: expected {list(TORQUES_NM)}")
        wheel_bases[r.text("id")] = WheelBase(
            r.text("id"), r.text("name"), torques, r.texts("platforms"), eras, _params(r, "params")
        )
    models: dict[str, PedalModel] = {}
    for i, raw in enumerate(hw.seq("pedals")):
        r = _R(raw, f"$research.hardware.pedals[{i}]")
        ur = r.d.get("user_rig")
        models[r.text("id")] = PedalModel(
            r.text("id"),
            r.text("name"),
            r.text("brake_sensor"),
            ur if isinstance(ur, str) else None,
            _params(r, "params"),
        )

    wb_id = ov.text("wheel_base")
    if wb_id not in wheel_bases:
        raise CatalogError(f"$overlay.wheel_base: unknown wheel base {wb_id!r}")
    wb = wheel_bases[wb_id]
    pedal_map: dict[str, str] = {}
    for app_id, rid in ov.obj("pedals").items():
        if app_id not in PEDALS:
            raise CatalogError(f"$overlay.pedals.{app_id}: not an app pedals id {list(PEDALS)}")
        if not isinstance(rid, str) or rid not in models:
            raise CatalogError(f"$overlay.pedals.{app_id}: unknown research pedal model {rid!r}")
        pedal_map[app_id] = rid
    if set(pedal_map) != set(PEDALS):
        raise CatalogError(f"$overlay.pedals: expected {list(PEDALS)}")
    research_to_app = {v: k for k, v in pedal_map.items()}

    # --- games
    games: dict[str, Game] = {}
    for i, raw in enumerate(root.seq("games")):
        r = _R(raw, f"$research.games[{i}]")
        gid = cast(GameId, r.choice("id", GAMES))
        versions: dict[str, GameVersion] = {}
        for j, v in enumerate(r.seq("versions")):
            vr = _R(v, f"{r.path}.versions[{j}]")
            versions[vr.text("id")] = GameVersion(
                vr.text("id"), vr.text("label"), vr.text("date"), vr.flag("ffb_relevant"), vr.opt_text("notes") or ""
            )
        games[gid] = Game(gid, r.text("name"), r.texts("platforms"), versions, _params(r, "params"))
    if set(games) != set(GAMES):
        raise CatalogError(f"$research.games: expected {list(GAMES)}")

    styles: dict[str, Style] = {}
    for i, raw in enumerate(ov.seq("styles")):
        r = _R(raw, f"$overlay.styles[{i}]")
        sid = cast(StyleId, r.choice("id", STYLES))
        styles[sid] = Style(sid, r.text("label"), r.text("description"), r.flag("sourced"))
    if tuple(styles) != STYLES:
        raise CatalogError(f"$overlay.styles: expected {list(STYLES)} in that order")

    # --- presets
    codes = ov.obj("preset_codes")
    presets: dict[str, Preset] = {}
    seen_codes: set[str] = set()
    for i, raw in enumerate(root.seq("presets")):
        r = _R(raw, f"$research.presets[{i}]")
        pid = r.text("id")
        if pid in presets:
            raise CatalogError(f"{r.path}.id: duplicate preset {pid}")
        code = codes.d.get(pid)
        if not isinstance(code, str) or not code:
            raise CatalogError(f"$overlay.preset_codes.{pid}: every preset needs a code")
        if code in seen_codes:
            raise CatalogError(f"$overlay.preset_codes.{pid}: duplicate code {code}")
        seen_codes.add(code)
        game = games[cast(GameId, r.choice("game", GAMES))]
        platform = r.choice("platform", game.platforms)
        applies = r.texts("applies_to_platforms")
        for pl in applies:
            if pl not in game.platforms:
                raise CatalogError(f"{r.path}.applies_to_platforms: {pl!r} is not a {game.id} platform")
        if platform not in applies:
            raise CatalogError(f"{r.path}.platform: {platform!r} must be one of applies_to_platforms")
        wbr = r.text("wheel_base")
        if wbr not in wheel_bases:
            raise CatalogError(f"{r.path}.wheel_base: unknown {wbr!r}")
        torque = r.opt_num("torque_nm")
        applies_t = r.ints("applies_to_torque_nm")
        if not applies_t or not all(t in TORQUES_NM for t in applies_t):
            raise CatalogError(f"{r.path}.applies_to_torque_nm: expected values from {TORQUES_NM}")
        pedals = r.opt_text("pedals")
        if pedals is not None and pedals not in models:
            raise CatalogError(f"{r.path}.pedals: unknown pedal model {pedals!r}")
        gv = r.obj("game_version")
        gv_id = gv.text("id")
        if gv_id not in game.versions:
            raise CatalogError(f"{gv.path}.id: unknown {game.id} version {gv_id!r}")
        fw = r.obj("firmware")
        era = fw.text("era")
        if era not in wheel_bases[wbr].firmware_eras:
            raise CatalogError(f"{fw.path}.era: unknown firmware era {era!r}")
        status = r.choice("status", STATUSES)
        stale = r.flag("stale")
        reasons = r.texts("stale_reasons", optional=True)
        if stale and not reasons:
            raise CatalogError(f"{r.path}.stale_reasons: a stale preset must say why")
        wheel_params = dict(wheel_bases[wbr].params)
        presets[pid] = Preset(
            id=pid,
            code=code,
            name=r.text("name"),
            game=game.id,
            platform=platform,
            applies_to_platforms=applies,
            source_platform=r.text("source_platform"),
            ps5_reachable=r.flag("ps5_reachable"),
            ps5_note=r.opt_text("ps5_note"),
            wheel_base=wbr,
            source_wheel_base=r.opt_text("source_wheel_base"),
            torque_nm=None if torque is None else int(torque),
            applies_to_torque_nm=applies_t,
            torque_basis=r.text("torque_basis"),
            pedals=pedals,
            pedals_basis=r.text("pedals_basis"),
            preference=cast(StyleId, r.choice("preference", STYLES)),
            preference_basis=r.text("preference_basis"),
            preference_source_words=r.opt_text("preference_source_words"),
            game_version=gv_id,
            game_version_predates=gv.texts("predates", optional=True),
            firmware_era=era,
            firmware_era_basis=fw.text("era_basis"),
            firmware_note=fw.opt_text("note"),
            status=status,
            stale=stale,
            stale_reasons=reasons,
            superseded_by=r.opt_text("superseded_by"),
            wheel_settings=_values(r, "wheel_settings", wheel_params, f"{wbr} Tuning Menu"),
            ingame_settings=_values(r, "ingame_settings", game.params, game.id),
            pedal_settings=_pedal_settings(r, "pedal_settings", models),
            sources=_sources(r, "sources", required=True),
            confidence=cast(Confidence, r.choice("confidence", ("high", "medium", "low"))),
            notes=r.opt_text("notes") or "",
        )
    for pid, p in presets.items():
        if p.superseded_by is not None and p.superseded_by not in presets:
            raise CatalogError(f"$research.presets.{pid}.superseded_by: unknown preset {p.superseded_by!r}")
    for pid in codes.d:
        if pid not in presets:
            raise CatalogError(f"$overlay.preset_codes.{pid}: not a research preset")

    # --- pedal reports
    reports: dict[str, PedalReport] = {}
    for i, raw in enumerate(root.seq("pedal_reports")):
        r = _R(raw, f"$research.pedal_reports[{i}]")
        model = r.text("pedals")
        if model not in models:
            raise CatalogError(f"{r.path}.pedals: unknown pedal model {model!r}")
        t = r.opt_num("torque_nm")
        reports[r.text("id")] = PedalReport(
            id=r.text("id"),
            owner=r.text("owner"),
            pedals=model,
            stock=r.flag("stock"),
            modification=r.opt_text("modification"),
            values=_values(r, "pedal_settings", models[model].params, model),
            game=r.opt_text("game"),
            torque_nm=None if t is None else int(t),
            latest_for_owner=r.flag("latest_for_owner"),
            preference=r.opt_text("preference"),
            source_words=r.opt_text("source_words"),
            sources=_sources(r, "sources", required=True),
            notes=r.opt_text("notes") or "",
        )

    # --- overlay pieces the recommendation tables need
    instructions: dict[str, Instruction] = {}
    for k, raw in ov.obj("instructions").items():
        ir = _R(raw, f"$overlay.instructions.{k}")
        instructions[k] = Instruction(ir.text("display"), ir.opt_text("rule"), ir.text("note"))
    derivations = {k: str(v) for k, v in ov.obj("derivations").items()}
    attributions: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {}
    for i, raw in enumerate(ov.seq("value_sources")):
        vr = _R(raw, f"$overlay.value_sources[{i}]")
        for pid in vr.texts("presets"):
            if pid not in presets:
                raise CatalogError(f"{vr.path}.presets: unknown preset {pid!r}")
        for eid in vr.texts("entries"):
            attributions[(eid, vr.text("key"))] = (vr.texts("presets"), vr.text("note"))

    rec = root.obj("recommendations")
    rules: dict[str, ResearchRule] = {}
    for i, raw in enumerate(rec.seq("rules")):
        r = _R(raw, f"$research.recommendations.rules[{i}]")
        for b in r.texts("basis_presets", optional=True):
            if b not in presets:
                raise CatalogError(f"{r.path}.basis_presets: unknown preset {b!r}")
        rules[r.text("id")] = ResearchRule(
            id=r.text("id"),
            game=r.choice("game", (*GAMES, "any")),
            applies_to_preferences=r.texts("applies_to_preferences"),
            rule=r.text("rule"),
            evidence=_evidence(r, allowed=VALUE_EVIDENCE),
            basis_presets=r.texts("basis_presets", optional=True),
            factor=r.opt_num("factor"),
        )
    for k, ins in instructions.items():
        if ins.rule is not None and ins.rule not in rules:
            raise CatalogError(f"$overlay.instructions.{k}.rule: unknown research rule {ins.rule!r}")
    for required in ("f1_torque_5_to_8_keep_strength", "f1_torque_5_to_8_comfort", "exact_5nm_feel_at_8nm"):
        if required not in rules:
            raise CatalogError(f"$research.recommendations.rules: missing {required}")
    if rules["f1_torque_5_to_8_comfort"].factor is None:
        raise CatalogError("$research.recommendations.rules.f1_torque_5_to_8_comfort.factor: missing")

    # --- wheel recommendation entries: the full game x torque x style grid
    wheel_entries: dict[tuple[str, int, str], WheelEntry] = {}
    for i, raw in enumerate(rec.seq("wheel")):
        r = _R(raw, f"$research.recommendations.wheel[{i}]")
        game = games[cast(GameId, r.choice("game", GAMES))]
        torque = r.opt_num("torque_nm")
        if torque is None or int(torque) not in TORQUES_NM:
            raise CatalogError(f"{r.path}.torque_nm: expected one of {TORQUES_NM}")
        style = cast(StyleId, r.choice("preference", STYLES))
        key = (game.id, int(torque), style)
        if key in wheel_entries:
            raise CatalogError(f"{r.path}: duplicate entry for {key}")
        basis = r.texts("basis_presets", optional=True)
        for b in basis:
            if b not in presets or presets[b].game != game.id:
                raise CatalogError(f"{r.path}.basis_presets: {b!r} is not a {game.id} preset")
        fb = r.d.get("fallback_to")
        entry = WheelEntry(
            id=r.text("id"),
            game=game.id,
            torque_nm=int(torque),
            preference=style,
            sourced=r.flag("sourced"),
            fallback_to=None if fb is None else cast(StyleId, r.choice("fallback_to", STYLES)),
            basis_presets=basis,
            wheel_settings=_values(r, "wheel_settings", wheel_bases[wb_id].params, f"{wb_id} Tuning Menu"),
            ingame_settings=_values(r, "ingame_settings", game.params, game.id),
            confidence=r.text("confidence"),
            notes=r.opt_text("notes") or "",
        )
        backing: dict[str, Backing] = {}
        pool = [presets[b] for b in basis]
        for k, v in (*entry.wheel_settings.items(), *entry.ingame_settings.items()):
            attr = attributions.get((entry.id, k))
            kpool = [*pool, *(presets[p] for p in attr[0])] if attr else pool
            backing[k] = _backing(
                k,
                v,
                kpool,
                entry.torque_nm,
                attribution=attr[1] if attr else None,
                cited=False,
                instruction=instructions.get(k),
                path=f"{r.path}.{k}",
            )
            _check_derivation(k, v, entry.notes, derivations, f"{r.path}.{k}", sourced=entry.sourced)
        wheel_entries[key] = replace(entry, backing=backing)
    for g in GAMES:
        for t in TORQUES_NM:
            for s in STYLES:
                if (g, t, s) not in wheel_entries:
                    raise CatalogError(f"$research.recommendations.wheel: missing {g}/{t} Nm/{s}")
    for e in wheel_entries.values():
        if e.empty:
            if e.fallback_to is None:
                raise CatalogError(f"$research.recommendations.wheel.{e.id}: an empty entry needs fallback_to")
            target = wheel_entries[(e.game, e.torque_nm, e.fallback_to)]
            if target.empty:
                raise CatalogError(f"$research.recommendations.wheel.{e.id}: fallback {e.fallback_to} is empty too")
        elif e.sourced and not e.basis_presets:
            raise CatalogError(f"$research.recommendations.wheel.{e.id}: a sourced entry needs basis presets")

    # --- pedal recommendation entries: game x pedals x style
    pedal_entries: dict[tuple[str, str, str], PedalEntry] = {}
    for i, raw in enumerate(rec.seq("pedals")):
        r = _R(raw, f"$research.recommendations.pedals[{i}]")
        game = games[cast(GameId, r.choice("game", GAMES))]
        model = r.text("pedals")
        if model not in research_to_app:
            raise CatalogError(f"{r.path}.pedals: {model!r} is not one of the rig's pedal models")
        style = cast(StyleId, r.choice("preference", STYLES))
        pkey = (game.id, research_to_app[model], style)
        if pkey in pedal_entries:
            raise CatalogError(f"{r.path}: duplicate entry for {pkey}")
        basis = r.texts("basis_presets", optional=True)
        for b in basis:
            if b not in presets or presets[b].game != game.id:
                raise CatalogError(f"{r.path}.basis_presets: {b!r} is not a {game.id} preset")
        rep = r.texts("basis_pedal_reports", optional=True)
        for b in rep:
            if b not in reports or reports[b].pedals != model:
                raise CatalogError(f"{r.path}.basis_pedal_reports: {b!r} is not a {model} report")
        ps = _pedal_settings(r, "pedal_settings", models)
        if ps is not None and model not in ps.transferable_to_pedals and ps.pedal_model != model:
            raise CatalogError(f"{r.path}.pedal_settings: values do not transfer to {model}")
        kg_raw = r.d.get("kg_estimate")
        kg = None
        if kg_raw is not None:
            kr = _R(kg_raw, f"{r.path}.kg_estimate")
            kv = kr.opt_num("value_kg")
            if kv is None:
                raise CatalogError(f"{kr.path}.value_kg: missing")
            kg = KgEstimate(kv, _evidence(kr, allowed=VALUE_EVIDENCE), kr.text("note"))
        pentry = PedalEntry(
            id=r.text("id"),
            game=game.id,
            pedals=model,
            preference=style,
            sourced=r.flag("sourced"),
            basis_presets=basis,
            basis_pedal_reports=rep,
            basis_sources=_sources(r, "basis_sources", required=False),
            pedal_settings=ps,
            ingame_settings=_values(r, "ingame_settings", game.params, game.id),
            kg_estimate=kg,
            confidence=r.text("confidence"),
            notes=r.opt_text("notes") or "",
        )
        pbacking: dict[str, Backing] = {}
        pool = [presets[b] for b in basis]
        for k, v in (*pentry.pedal_values.items(), *pentry.ingame_settings.items()):
            pbacking[k] = _backing(
                k,
                v,
                pool,
                None,
                attribution=None,
                cited=bool(pentry.basis_sources),
                instruction=instructions.get(k),
                path=f"{r.path}.{k}",
            )
            _check_derivation(k, v, pentry.notes, derivations, f"{r.path}.{k}", sourced=pentry.sourced)
        pedal_entries[pkey] = replace(pentry, backing=pbacking)
    for g in GAMES:
        for pid_app in PEDALS:
            for s in STYLES:
                if (g, pid_app, s) not in pedal_entries:
                    raise CatalogError(f"$research.recommendations.pedals: missing {g}/{pid_app}/{s}")

    br = rec.obj("brf_owner_stats")
    vals = br.seq("values")
    if not vals or not all(isinstance(x, int | float) and not isinstance(x, bool) for x in vals):
        raise CatalogError(f"{br.path}.values: expected numbers")
    stats = BrfOwnerStats(
        population=br.text("population"),
        n=int(br.opt_num("n") or 0),
        values=tuple(float(x) for x in vals),
        median=float(br.opt_num("median") or 0.0),
        min=float(br.opt_num("min") or 0.0),
        max=float(br.opt_num("max") or 0.0),
        evidence=_evidence(br, allowed=VALUE_EVIDENCE),
        note=br.text("note"),
    )
    if stats.n != len(stats.values) or not math.isclose(stats.median, sorted(stats.values)[len(vals) // 2]):
        raise CatalogError(f"{br.path}: n/median do not match the values")

    # --- overlay: pickers, rims, rules, issues, steps
    platforms: dict[str, Platform] = {}
    for i, raw in enumerate(ov.seq("platforms")):
        r = _R(raw, f"$overlay.platforms[{i}]")
        platforms[r.text("id")] = Platform(
            r.text("id"), r.text("name"), r.text("base_mode"), r.text("base_mode_note"), r.text("tuning_interface")
        )
    supported: set[tuple[str, str]] = set()
    for i, raw in enumerate(ov.seq("supported")):
        r = _R(raw, f"$overlay.supported[{i}]")
        sg, pl = r.choice("game", GAMES), r.choice("platform", tuple(platforms))
        if pl not in games[sg].platforms:
            raise CatalogError(f"{r.path}: {pl} is not a {sg} platform")
        for e in wheel_entries.values():
            for b in e.basis_presets if e.game == sg else ():
                if pl not in presets[b].applies_to_platforms:
                    raise CatalogError(f"{r.path}: {e.id} relies on {b}, which does not apply to {pl}")
        supported.add((sg, pl))

    rim_items = {k: str(v) for k, v in ov.obj("rim_items").items()}
    for k in rim_items:
        if k not in wb.params:
            raise CatalogError(f"$overlay.rim_items.{k}: not a {wb_id} parameter")
    rims: dict[str, Rim] = {}
    for i, raw in enumerate(ov.seq("rims")):
        r = _R(raw, f"$overlay.rims[{i}]")
        has, unknown = r.texts("has_items", optional=True), r.texts("unknown_items", optional=True)
        for k in (*has, *unknown):
            if k not in rim_items:
                raise CatalogError(f"{r.path}: {k} is not a rim-dependent item {sorted(rim_items)}")
        rims[r.text("id")] = Rim(r.text("id"), r.text("name"), r.text("note"), has, unknown)

    menu_order = ov.texts("menu_order")
    for k in menu_order:
        if k not in wb.params and k != "BRF":
            raise CatalogError(f"$overlay.menu_order: {k} is not a {wb_id} parameter")
    for e in wheel_entries.values():
        for k in e.wheel_settings:
            if k not in menu_order:
                raise CatalogError(f"$overlay.menu_order: {k} (used by {e.id}) has no place in the menu order")

    dr = ov.obj("driver_rules")
    bounds = dr.obj("strength_scale_bounds")
    sk = dr.obj("skill_strength_scale")
    floor = dr.obj("beginner_ndp_floor")
    slot = dr.obj("driver_slot")
    lo, hi = bounds.opt_num("min"), bounds.opt_num("max")
    if lo is None or hi is None or not 0 < lo < hi <= 1:
        raise CatalogError(f"{bounds.path}: expected 0 < min < max <= 1")
    skill_scale: dict[str, float] = {}
    for level in ("beginner", "intermediate", "advanced"):
        x = sk.opt_num(level)
        if x is None or not lo <= x <= hi:
            raise CatalogError(f"{sk.path}.{level}: expected a scale between {lo} and {hi}")
        skill_scale[level] = x
    ndp = floor.opt_num("value")
    rnd = sk.opt_num("round_to")
    if ndp is None or rnd is None:
        raise CatalogError(f"{dr.path}: beginner_ndp_floor.value and skill_strength_scale.round_to are required")
    driver_rules = DriverRules(
        scale_min=lo,
        scale_max=hi,
        skill_scale=skill_scale,
        scale_round_to=int(rnd),
        scale_explanation=sk.text("explanation"),
        ndp_floor=int(ndp),
        ndp_floor_explanation=floor.text("explanation"),
        driver_slot=slot.text("value"),
        driver_slot_explanation=slot.text("explanation"),
    )

    consensus: dict[str, dict[str, Consensus]] = {}
    for cg, raw in ov.obj("consensus").items():
        if cg not in games:
            raise CatalogError(f"$overlay.consensus.{cg}: unknown game")
        consensus[cg] = {}
        for k, c in _R(raw, f"$overlay.consensus.{cg}").items():
            cr = _R(c, f"$overlay.consensus.{cg}.{k}")
            if k not in games[cg].params and k not in wb.params and k != "BRF":
                raise CatalogError(f"{cr.path}: unknown setting")
            n = cr.opt_num("n")
            consensus[cg][k] = Consensus(
                n=None if n is None else int(n),
                median=cr.opt_text("median"),
                range=cr.opt_text("range"),
                status=cr.choice("status", ("consensus", "strong", "split", "moot")),
                note=cr.opt_text("note") or "",
            )

    issues = []
    for i, raw in enumerate(ov.seq("known_issues")):
        r = _R(raw, f"$overlay.known_issues[{i}]")
        issues.append(
            KnownIssue(
                r.text("id"),
                r.text("title"),
                r.text("detail"),
                _applies(r.obj("applies_to")),
                _evidence(r),
                r.text("source"),
            )
        )
    questions = []
    for i, raw in enumerate(ov.seq("open_questions")):
        r = _R(raw, f"$overlay.open_questions[{i}]")
        qid = r.opt_num("id")
        if qid is None:
            raise CatalogError(f"{r.path}.id: missing")
        questions.append(OpenQuestion(int(qid), r.text("question"), r.text("verify"), _applies(r.obj("applies_to"))))
    timeline = []
    for i, raw in enumerate(ov.seq("timeline")):
        r = _R(raw, f"$overlay.timeline[{i}]")
        d = r.text("date")
        if not _DATE.fullmatch(d):
            raise CatalogError(f"{r.path}.date: {d!r} is not YYYY-MM(-DD)")
        timeline.append({"date": d, "event": r.text("event"), "effect": r.text("effect")})

    st = ov.obj("steps")
    boost_steps = _steps(st.seq("boost_kit"), "$overlay.steps.boost_kit")
    if "strength" not in {s.id for s in boost_steps}:
        raise CatalogError("$overlay.steps.boost_kit: the computed 'strength' step is required")
    ps_raw = st.obj("pedals")
    pedal_steps: dict[str, tuple[GuideStep, ...]] = {
        p: _steps(ps_raw.seq(p), f"$overlay.steps.pedals.{p}") for p in PEDALS
    }
    for steps in (boost_steps, *pedal_steps.values()):
        for step in steps:
            if not step.text and step.id not in ("strength", "exact_ab", "brf_owners"):  # computed steps
                raise CatalogError(f"$overlay.steps: step {step.id} has no text")

    rig_check = _rig_check(root, ov, research_to_app)

    research_date = ov.text("research_date")
    if research_date != root.text("generated_on"):
        raise CatalogError("$overlay.research_date: does not match the research document's generated_on")
    return Catalog(
        schema_revision=2,
        research_date=research_date,
        evidence_labels={k: str(v) for k, v in labels.items()},
        firmware={k: str(v) for k, v in ov.obj("firmware").items()},
        wheel_base_id=wb_id,
        torque_labels={int(k): str(v) for k, v in ov.obj("torque_labels").items()},
        pedal_models=models,
        pedals=pedal_map,
        supported=frozenset(supported),
        platforms=platforms,
        styles=styles,
        wheel_bases=wheel_bases,
        rims=rims,
        rim_items=rim_items,
        games=games,
        presets=presets,
        pedal_reports=reports,
        wheel_entries=wheel_entries,
        pedal_entries=pedal_entries,
        rules=rules,
        common_steps=rec.texts("common_steps"),
        brf_owner_stats=stats,
        instructions=instructions,
        derivations=derivations,
        driver_rules=driver_rules,
        menu_order=menu_order,
        menu_order_note=ov.text("menu_order_note"),
        consensus=consensus,
        known_issues=tuple(issues),
        open_questions=tuple(questions),
        timeline=tuple(timeline),
        boost_kit_steps=boost_steps,
        pedal_steps=pedal_steps,
        rig_check=rig_check,
    )


def _check_derivation(
    key: str, v: SettingValue, entry_notes: str, derivations: Mapping[str, str], path: str, *, sourced: bool
) -> None:
    """A derived value must say how it was derived: its own note, the overlay's text for that key, or (for an entry
    with no source at all) the entry's notes."""
    if v.evidence != "D" or v.note or key in derivations or (not sourced and entry_notes):
        return
    raise CatalogError(f"{path}: derived value {key}={v.value} has no derivation (note, overlay text or entry notes)")


def derivation_text(cat: Catalog, key: str, v: SettingValue, entry_notes: str) -> str:
    return v.note or cat.derivations.get(key) or entry_notes


def _rig_check(root: _R, ov: _R, research_to_app: Mapping[str, str]) -> dict[str, RigCheckSpec]:
    """Merge the research metric definitions with the overlay's display metadata, checking that the overlay's
    thresholds are the research thresholds in display units (or say why not)."""
    research: dict[str, _R] = {}
    for i, raw in enumerate(root.seq("rig_check")):
        rr = _R(raw, f"$research.rig_check[{i}]")
        research[rr.text("metric")] = rr
    out: dict[str, RigCheckSpec] = {}
    for i, raw in enumerate(ov.seq("rig_check")):
        o = _R(raw, f"$overlay.rig_check[{i}]")
        metric = o.text("metric")
        if metric in out:
            raise CatalogError(f"{o.path}.metric: duplicate {metric}")
        found = research.get(metric)
        if found is None:
            raise CatalogError(f"{o.path}.metric: {metric} is not a research rig-check metric")
        r = found
        th = r.obj("threshold")
        thresholds: dict[str, float] = {}
        for k, v in o.obj("thresholds").items():
            if k not in ("pass_max", "fail_above", "pass_min", "fail_below"):
                raise CatalogError(f"{o.path}.thresholds: unknown threshold {k!r}")
            if isinstance(v, bool) or not isinstance(v, int | float):
                raise CatalogError(f"{o.path}.thresholds.{k}: expected a number")
            thresholds[k] = float(v)
        direction = cast(Direction, o.choice("direction", DIRECTIONS))
        if thresholds:
            scale = o.opt_num("research_scale")
            if scale is None:
                raise CatalogError(f"{o.path}.research_scale: needed to compare thresholds with the research")
            pairs = (("pass_max", "good_max"), ("pass_min", "good_min"), ("fail_below", "hard_min"))
            for mine, theirs in pairs:
                if mine in thresholds and th.opt_num(theirs) is not None:
                    expected = cast(float, th.opt_num(theirs)) * scale
                    if not math.isclose(thresholds[mine], expected, abs_tol=1e-9) and not o.opt_text("deviation"):
                        raise CatalogError(
                            f"{o.path}.thresholds.{mine}: {thresholds[mine]:g} differs from the research "
                            f"{theirs} {expected:g} (explain it in 'deviation')"
                        )
        pedals = o.texts("pedals", optional=True)
        for p in pedals:
            if p not in PEDALS:
                raise CatalogError(f"{o.path}.pedals: unknown pedals {p!r}")
        research_pedals = r.texts("applies_to_pedals", optional=True)
        expected_pedals = () if "any" in research_pedals else tuple(research_to_app.get(p, p) for p in research_pedals)
        if set(pedals) != set(expected_pedals) and set(expected_pedals) != set(PEDALS):
            raise CatalogError(f"{o.path}.pedals: {list(pedals)} differs from the research {list(research_pedals)}")
        games = o.texts("games")
        if set(games) != set(r.texts("applies_to_games")):
            raise CatalogError(f"{o.path}.games: differs from the research applies_to_games")
        sources = []
        for j, s in enumerate(r.seq("sources", optional=True)):
            sources.append(_source(_R(s, f"{r.path}.sources[{j}]")).url)
        out[metric] = RigCheckSpec(
            metric=metric,
            label=o.text("label"),
            description=r.text("description"),
            unit=o.opt_text("unit") or "",
            direction=direction,
            thresholds=thresholds,
            threshold_evidence=_evidence(th),
            good_range=r.text("good_range"),
            action_if_high=r.text("action_if_high"),
            action_if_low=r.text("action_if_low"),
            sources=tuple(sources),
            games=games,
            pedals=pedals,
            requires=o.texts("requires"),
            threshold_note=o.opt_text("threshold_note") or o.opt_text("deviation"),
            reference=o.opt_text("reference"),
        )
    if list(out) != list(research):
        raise CatalogError(f"$overlay.rig_check: expected the research metrics {list(research)} in that order")
    return out


def load_catalog_files(research_path: Path, overlay_path: Path) -> Catalog:
    docs = []
    for path in (research_path, overlay_path):
        try:
            docs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            raise CatalogError(f"cannot read {path}: {e}") from e
    return parse_catalog(docs[0], docs[1])


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    """The packaged catalogue, parsed and validated once per process."""
    return load_catalog_files(RESEARCH_PATH, OVERLAY_PATH)
