"""F1 25 car setup catalogue: parameter ranges per car format, cited community setups, and the recommendations
pitwall builds from them.

Source of truth: ``data/f1_25_setups.json``, curated from ``docs/research/f1-car-setups.md``. This module loads and
validates it (stdlib only) so ``recommend``/``compare`` and the API can rely on its shape. Nothing here invents a
value.

Layout of the file (``schema_version`` 1):

* ``formats``: one entry per car format (``f1_2025`` = the base-game 2025 cars, ``f1_2026`` = the 2026 Season Pack
  cars). Each has its own parameter ranges and steps (with sources), its drivable track ids and the latest patch
  that changed handling. The two formats are never mixed: a setup, a range or a recommendation belongs to exactly
  one.
* ``parameters``: the setup-sheet parameters in the game's menu order, with plain-words effects (sourced).
* ``sources``: every website / driver / creator cited, with a summary of its terms and pitwall's use policy.
* ``source_setups``: the evidence, one record per published setup, values recorded as facts with attribution.
  A parameter the source did not give is absent (unknown), never filled in.
* ``rules``: pitwall's own derivation rules (e.g. how a stable variant is derived), each with its sources.
* ``recommendations`` are **not stored** in the packaged file: ``load_catalog_file`` builds them from the evidence
  with ``carsetup.build`` (about 40 ms, once per process) and validates the result like any other section, so they
  always follow from the cited setups and a hand edit cannot slip in. Every value names the setup(s) it came from,
  their patch(es), a confidence and whether pitwall derived it. (A file may still carry a ``recommendations``
  section, e.g. in tests; it is then validated as given.)

Values are stored as the game's setup menu shows them; ``Parameter.udp_to_menu`` converts what the UDP CarSetups
packet sends (identity for every parameter whose mapping research established as identity).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal, cast, get_args

CarFormat = Literal["f1_2025", "f1_2026"]
SessionKind = Literal["race", "qualifying"]
SourceSession = Literal["race", "qualifying", "both"]
Conditions = Literal["dry", "wet"]
Style = Literal["balanced", "stable", "aggressive"]
Confidence = Literal["high", "medium", "low"]
InputDevice = Literal["wheel", "controller"]
SourceKind = Literal["setup_site", "esports_driver", "creator", "community_db", "ea_official", "press"]
UsePolicy = Literal["use", "use_limited", "do_not_use"]
SelectionRule = Literal["single_source", "medoid", "derived"]

CAR_FORMATS: tuple[CarFormat, ...] = get_args(CarFormat)
SESSIONS: tuple[SessionKind, ...] = get_args(SessionKind)
SOURCE_SESSIONS: tuple[SourceSession, ...] = get_args(SourceSession)
CONDITIONS: tuple[Conditions, ...] = get_args(Conditions)
STYLES: tuple[Style, ...] = get_args(Style)
CONFIDENCES: tuple[Confidence, ...] = get_args(Confidence)
INPUT_DEVICES: tuple[InputDevice, ...] = get_args(InputDevice)
SOURCE_KINDS: tuple[SourceKind, ...] = get_args(SourceKind)
USE_POLICIES: tuple[UsePolicy, ...] = get_args(UsePolicy)
SELECTION_RULES: tuple[SelectionRule, ...] = get_args(SelectionRule)

SCHEMA_VERSION = 1
DEFAULT_PATH = Path(str(resources.files("pitwall.carsetup") / "data" / "f1_25_setups.json"))
_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
_PATCH = re.compile(r"^\d+\.\d+$")
_ID = re.compile(r"^[a-z0-9][a-z0-9_.:-]*$")
RANGE_TOLERANCE = 1e-6  # relative to the step, for the range ends
STEP_TOLERANCE = 1e-3  # fraction of a step: JSON floats such as 0.05 are not exact in binary


class CatalogError(ValueError):
    """The setup catalogue does not match the expected schema."""


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
        if not isinstance(v, str) or not v.strip():
            raise CatalogError(f"{self.path}.{key}: expected a non-empty string")
        return v

    def opt_text(self, key: str) -> str | None:
        v = self._get(key, True)
        if v is None:
            return None
        if not isinstance(v, str) or not v.strip():
            raise CatalogError(f"{self.path}.{key}: expected a non-empty string or null")
        return v

    def num(self, key: str) -> float:
        v = self._get(key, False)
        if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
            raise CatalogError(f"{self.path}.{key}: expected a finite number")
        return float(v)

    def integer(self, key: str) -> int:
        v = self._get(key, False)
        if isinstance(v, bool) or not isinstance(v, int):
            raise CatalogError(f"{self.path}.{key}: expected an integer")
        return v

    def flag(self, key: str) -> bool:
        v = self._get(key, False)
        if not isinstance(v, bool):
            raise CatalogError(f"{self.path}.{key}: expected a boolean")
        return v

    def choice(self, key: str, options: Sequence[str]) -> str:
        v = self.text(key)
        if v not in options:
            raise CatalogError(f"{self.path}.{key}: {v!r} is not one of {list(options)}")
        return v

    def opt_choice(self, key: str, options: Sequence[str]) -> str | None:
        v = self.opt_text(key)
        if v is not None and v not in options:
            raise CatalogError(f"{self.path}.{key}: {v!r} is not one of {list(options)}")
        return v

    def date(self, key: str) -> str:
        v = self.text(key)
        if not _DATE.match(v):
            raise CatalogError(f"{self.path}.{key}: {v!r} is not YYYY-MM(-DD)")
        return v

    def opt_date(self, key: str) -> str | None:
        return None if self.d.get(key) is None else self.date(key)

    def opt_patch(self, key: str) -> str | None:
        v = self.opt_text(key)
        if v is not None and not _PATCH.match(v):
            raise CatalogError(f"{self.path}.{key}: {v!r} is not a game version like 1.12")
        return v

    def ident(self, key: str) -> str:
        v = self.text(key)
        if not _ID.match(v):
            raise CatalogError(f"{self.path}.{key}: {v!r} is not a lower-case id")
        return v

    def seq(self, key: str) -> list[Any]:
        v = self._get(key, False)
        if not isinstance(v, list):
            raise CatalogError(f"{self.path}.{key}: expected a list")
        return v

    def texts(self, key: str) -> tuple[str, ...]:
        items = self.seq(key)
        if not all(isinstance(x, str) and x.strip() for x in items):
            raise CatalogError(f"{self.path}.{key}: expected a list of non-empty strings")
        return tuple(items)

    def obj(self, key: str) -> _R:
        return _R(self._get(key, False), f"{self.path}.{key}")

    def objs(self, key: str) -> list[_R]:
        return [_R(x, f"{self.path}.{key}[{i}]") for i, x in enumerate(self.seq(key))]

    def mapping(self, key: str) -> list[tuple[str, Any]]:
        v = self._get(key, False)
        if not isinstance(v, dict):
            raise CatalogError(f"{self.path}.{key}: expected an object")
        return list(v.items())


def patch_key(patch: str | None) -> tuple[int, ...]:
    """Sort key for game versions ("1.9" < "1.12"); unknown sorts first."""
    return tuple(int(p) for p in patch.split(".")) if patch else ()


# ---------------------------------------------------------------------------------------------- records
@dataclass(frozen=True, slots=True)
class Range:
    """A parameter's range for one car format. An end is *confirmed* when it is the game menu's own limit; otherwise
    it is the bound of the published values pitwall has seen (the true limit is unknown and may be wider)."""

    min: float
    max: float
    step: float
    confidence: Confidence
    sources: tuple[str, ...]
    note: str | None = None
    min_confirmed: bool = True
    max_confirmed: bool = True

    def contains(self, v: float) -> bool:
        return self.min - RANGE_TOLERANCE * self.step <= v <= self.max + RANGE_TOLERANCE * self.step

    def outside_menu(self, v: float) -> bool:
        """True only when ``v`` is beyond a confirmed menu limit (impossible for this car format)."""
        tol = RANGE_TOLERANCE * self.step
        return (self.min_confirmed and v < self.min - tol) or (self.max_confirmed and v > self.max + tol)

    def on_step(self, v: float) -> bool:
        k = (v - self.min) / self.step
        return abs(k - round(k)) <= STEP_TOLERANCE

    def steps_between(self, a: float, b: float) -> float:
        return (b - a) / self.step

    def snap(self, v: float) -> float:
        """Nearest on-step value inside the range (used only by derivation rules, never on sourced values)."""
        k = round((v - self.min) / self.step)
        snapped = self.min + k * self.step
        return round(min(self.max, max(self.min, snapped)), 6)


@dataclass(frozen=True, slots=True)
class Patch:
    version: str
    date: str
    source: str
    note: str


@dataclass(frozen=True, slots=True)
class FormatInfo:
    id: CarFormat
    label: str
    description: str
    latest_handling_patch: Patch
    tracks: tuple[int, ...]
    ranges: Mapping[str, Range]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Parameter:
    key: str
    label: str  # the game's menu label
    group: str  # menu section
    order: int  # position in the game's setup menu, top to bottom
    unit: str | None
    decimals: int
    udp_to_menu: Literal["identity"]
    higher: str  # plain words: what raising it changes in the car's behaviour
    lower: str
    sources: tuple[str, ...]

    def menu_value(self, udp_value: float) -> float:
        """The value the game's menu shows for a value the UDP CarSetups packet sent."""
        return round(udp_value, self.decimals)

    def fmt(self, v: float | None) -> str:
        if v is None:
            return "unknown"
        s = f"{v:.{self.decimals}f}"
        return f"{s} {self.unit}" if self.unit else s


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    name: str
    url: str
    kind: SourceKind
    terms_url: str | None
    terms: str
    use_policy: UsePolicy
    accessed: str


@dataclass(frozen=True, slots=True)
class SourceSetup:
    """One published setup, as the source published it (menu values, attribution, date and patch)."""

    id: str
    source: str
    url: str
    author: str | None
    published: str | None  # None when the source gives no date
    patch: str | None
    car_format: CarFormat
    track_id: int
    session: SourceSession
    conditions: Conditions
    style: Style | None  # the source's own label mapped to pitwall's styles; None = unlabelled
    input: InputDevice | None
    values: Mapping[str, float]
    verified: str  # date the values were checked against the source page
    notes: str | None

    def covers(self, session: SessionKind) -> bool:
        return self.session == session or self.session == "both"


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    description: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecValue:
    value: float | None  # None = no candidate setup gave this parameter (unknown)
    from_setup: str | None  # the setup the value was taken from (None when derived from scratch or unknown)
    sources: tuple[str, ...]  # candidate setups whose value agrees (within tolerance) with this one
    patches: tuple[str, ...]  # game versions of ``sources`` (empty when none is stated)
    confidence: Confidence
    derived: bool  # True when pitwall computed or changed the value (consensus selection, style rule)
    rule: str | None  # derivation rule id when derived
    spread: tuple[float, float] | None  # min/max across the candidate setups (None with fewer than two)


@dataclass(frozen=True, slots=True)
class Recommendation:
    id: str
    car_format: CarFormat
    track_id: int
    session: SessionKind
    conditions: Conditions
    style: Style
    selection: SelectionRule
    from_setup: str | None
    candidates: tuple[str, ...]
    base: str | None  # recommendation a derived one starts from
    values: Mapping[str, RecValue]
    disagreements: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def key(self) -> tuple[CarFormat, int, SessionKind, Conditions, Style]:
        return (self.car_format, self.track_id, self.session, self.conditions, self.style)


@dataclass(frozen=True, slots=True)
class Catalog:
    game: str
    updated: str
    research_doc: str
    formats: Mapping[CarFormat, FormatInfo]
    parameters: tuple[Parameter, ...]  # menu order
    sources: Mapping[str, Source]
    source_setups: Mapping[str, SourceSetup]
    rules: Mapping[str, Rule]
    recommendations: Mapping[tuple[CarFormat, int, SessionKind, Conditions, Style], Recommendation]
    _params_by_key: Mapping[str, Parameter] = field(default_factory=dict, repr=False)

    def param(self, key: str) -> Parameter | None:
        return self._params_by_key.get(key)

    def range(self, car_format: CarFormat, key: str) -> Range | None:
        return self.formats[car_format].ranges.get(key)

    def setups_for(self, car_format: CarFormat, track_id: int) -> list[SourceSetup]:
        return [s for s in self.source_setups.values() if s.car_format == car_format and s.track_id == track_id]

    def find(
        self, car_format: CarFormat, track_id: int, session: SessionKind, conditions: Conditions, style: Style
    ) -> Recommendation | None:
        return self.recommendations.get((car_format, track_id, session, conditions, style))


# ---------------------------------------------------------------------------------------------- parsing
def _parse_range(r: _R) -> Range:
    lo, hi, step = r.num("min"), r.num("max"), r.num("step")
    if not lo < hi or step <= 0 or step > hi - lo:
        raise CatalogError(f"{r.path}: need min < max and 0 < step <= max - min")
    k = (hi - lo) / step
    if abs(k - round(k)) > 1e-3:
        raise CatalogError(f"{r.path}: max is not reachable from min in steps of {step}")
    sources = r.texts("sources")
    if not sources:
        raise CatalogError(f"{r.path}.sources: a range needs at least one source")
    min_ok, max_ok = r.flag("min_confirmed"), r.flag("max_confirmed")
    note = r.opt_text("note")
    if not (min_ok and max_ok) and note is None:
        raise CatalogError(f"{r.path}.note: say where an unconfirmed (observed) range end comes from")
    return Range(lo, hi, step, cast(Confidence, r.choice("confidence", CONFIDENCES)), sources, note, min_ok, max_ok)


def _parse_patch(r: _R) -> Patch:
    version = r.text("version")
    if not _PATCH.match(version):
        raise CatalogError(f"{r.path}.version: {version!r} is not a game version like 1.12")
    return Patch(version, r.date("date"), r.text("source"), r.text("note"))


def _parse_format(fid: str, r: _R, param_keys: set[str]) -> FormatInfo:
    if fid not in CAR_FORMATS:
        raise CatalogError(f"{r.path}: unknown car format {fid!r}")
    ranges: dict[str, Range] = {}
    for key, raw in r.mapping("ranges"):
        if key not in param_keys:
            raise CatalogError(f"{r.path}.ranges.{key}: not a catalogue parameter")
        ranges[key] = _parse_range(_R(raw, f"{r.path}.ranges.{key}"))
    tracks = r.seq("tracks")
    if not tracks or not all(isinstance(t, int) and not isinstance(t, bool) and t >= 0 for t in tracks):
        raise CatalogError(f"{r.path}.tracks: expected a non-empty list of EA track ids")
    if len(set(tracks)) != len(tracks):
        raise CatalogError(f"{r.path}.tracks: duplicate track id")
    return FormatInfo(
        id=fid,
        label=r.text("label"),
        description=r.text("description"),
        latest_handling_patch=_parse_patch(r.obj("latest_handling_patch")),
        tracks=tuple(tracks),
        ranges=ranges,
        notes=r.texts("notes"),
    )


def _parse_parameter(r: _R) -> Parameter:
    decimals = r.integer("decimals")
    if not 0 <= decimals <= 3:
        raise CatalogError(f"{r.path}.decimals: expected 0..3")
    return Parameter(
        key=r.ident("key"),
        label=r.text("label"),
        group=r.text("group"),
        order=r.integer("order"),
        unit=r.opt_text("unit"),
        decimals=decimals,
        udp_to_menu=cast(Literal["identity"], r.choice("udp_to_menu", ("identity",))),
        higher=r.text("higher"),
        lower=r.text("lower"),
        sources=r.texts("sources"),
    )


def _parse_source(r: _R) -> Source:
    return Source(
        id=r.ident("id"),
        name=r.text("name"),
        url=r.text("url"),
        kind=cast(SourceKind, r.choice("kind", SOURCE_KINDS)),
        terms_url=r.opt_text("terms_url"),
        terms=r.text("terms"),
        use_policy=cast(UsePolicy, r.choice("use_policy", USE_POLICIES)),
        accessed=r.date("accessed"),
    )


def _check_value(path: str, key: str, v: object, rng: Range | None) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise CatalogError(f"{path}.{key}: expected a finite number")
    if rng is None:
        raise CatalogError(f"{path}.{key}: the car format has no range for this parameter")
    if not rng.contains(float(v)):
        raise CatalogError(f"{path}.{key}: {v} is outside {rng.min}..{rng.max}")
    if not rng.on_step(float(v)):
        raise CatalogError(f"{path}.{key}: {v} is not on the {rng.step} step from {rng.min}")
    return float(v)


def _parse_source_setup(r: _R, formats: Mapping[CarFormat, FormatInfo], sources: Mapping[str, Source]) -> SourceSetup:
    source = r.text("source")
    if source not in sources:
        raise CatalogError(f"{r.path}.source: unknown source {source!r}")
    if sources[source].use_policy == "do_not_use":
        raise CatalogError(f"{r.path}.source: {source!r} is marked do_not_use (its terms forbid it)")
    fmt = cast(CarFormat, r.choice("car_format", CAR_FORMATS))
    info = formats.get(fmt)
    if info is None:
        raise CatalogError(f"{r.path}.car_format: {fmt!r} has no format entry")
    track = r.integer("track_id")
    if track not in info.tracks:
        raise CatalogError(f"{r.path}.track_id: {track} is not drivable with {fmt}")
    values: dict[str, float] = {}
    for key, v in r.mapping("values"):
        values[key] = _check_value(f"{r.path}.values", key, v, info.ranges.get(key))
    if not values:
        raise CatalogError(f"{r.path}.values: a source setup needs at least one value")
    return SourceSetup(
        id=r.ident("id"),
        source=source,
        url=r.text("url"),
        author=r.opt_text("author"),
        published=r.opt_date("published"),
        patch=r.opt_patch("patch"),
        car_format=fmt,
        track_id=track,
        session=cast(SourceSession, r.choice("session", SOURCE_SESSIONS)),
        conditions=cast(Conditions, r.choice("conditions", CONDITIONS)),
        style=cast(Style | None, r.opt_choice("style", STYLES)),
        input=cast(InputDevice | None, r.opt_choice("input", INPUT_DEVICES)),
        values=values,
        verified=r.date("verified"),
        notes=r.opt_text("notes"),
    )


def _parse_rule(r: _R) -> Rule:
    sources = r.texts("sources")
    if not sources:
        raise CatalogError(f"{r.path}.sources: a derivation rule needs at least one source")
    return Rule(r.ident("id"), r.text("description"), sources)


def _parse_rec_value(
    r: _R, key: str, rng: Range | None, setups: Mapping[str, SourceSetup], rules: Mapping[str, Rule]
) -> RecValue:
    raw = r.d.get("value")
    value = None if raw is None else _check_value(r.path, "value", raw, rng)
    from_setup = r.opt_text("from_setup")
    if from_setup is not None and from_setup not in setups:
        raise CatalogError(f"{r.path}.from_setup: unknown setup {from_setup!r}")
    agreeing = r.texts("sources")
    for sid in agreeing:
        if sid not in setups:
            raise CatalogError(f"{r.path}.sources: unknown setup {sid!r}")
    derived = r.flag("derived")
    rule = r.opt_text("rule")
    if derived != (rule is not None):
        raise CatalogError(f"{r.path}: derived values need a rule and only derived values have one")
    if rule is not None and rule.split(":")[0] not in rules:
        raise CatalogError(f"{r.path}.rule: unknown rule {rule!r}")
    # a value that is not derived must be exactly a cited source's published value
    if value is not None and not derived and (from_setup is None or setups[from_setup].values.get(key) != value):
        raise CatalogError(f"{r.path}: non-derived value {value} is not what {from_setup!r} published")
    if value is not None and not agreeing and not derived:
        raise CatalogError(f"{r.path}.sources: a sourced value must cite at least one setup")
    patches = r.texts("patches")
    spread_raw = r.d.get("spread")
    spread: tuple[float, float] | None = None
    if spread_raw is not None:
        if (
            not isinstance(spread_raw, list)
            or len(spread_raw) != 2
            or not all(isinstance(x, int | float) and not isinstance(x, bool) for x in spread_raw)
        ):
            raise CatalogError(f"{r.path}.spread: expected [min, max] or null")
        spread = (float(spread_raw[0]), float(spread_raw[1]))
    return RecValue(
        value=value,
        from_setup=from_setup,
        sources=agreeing,
        patches=patches,
        confidence=cast(Confidence, r.choice("confidence", CONFIDENCES)),
        derived=derived,
        rule=rule,
        spread=spread,
    )


def _parse_recommendation(
    r: _R,
    formats: Mapping[CarFormat, FormatInfo],
    params: Mapping[str, Parameter],
    setups: Mapping[str, SourceSetup],
    rules: Mapping[str, Rule],
) -> Recommendation:
    fmt = cast(CarFormat, r.choice("car_format", CAR_FORMATS))
    info = formats[fmt]
    track = r.integer("track_id")
    if track not in info.tracks:
        raise CatalogError(f"{r.path}.track_id: {track} is not drivable with {fmt}")
    candidates = r.texts("candidates")
    for sid in candidates:
        s = setups.get(sid)
        if s is None:
            raise CatalogError(f"{r.path}.candidates: unknown setup {sid!r}")
        if s.car_format != fmt or s.track_id != track:
            raise CatalogError(f"{r.path}.candidates: {sid!r} is for another car format or track")
    values: dict[str, RecValue] = {}
    for key, raw in r.mapping("values"):
        if key not in params:
            raise CatalogError(f"{r.path}.values.{key}: not a catalogue parameter")
        values[key] = _parse_rec_value(_R(raw, f"{r.path}.values.{key}"), key, info.ranges.get(key), setups, rules)
    return Recommendation(
        id=r.text("id"),
        car_format=fmt,
        track_id=track,
        session=cast(SessionKind, r.choice("session", SESSIONS)),
        conditions=cast(Conditions, r.choice("conditions", CONDITIONS)),
        style=cast(Style, r.choice("style", STYLES)),
        selection=cast(SelectionRule, r.choice("selection", SELECTION_RULES)),
        from_setup=r.opt_text("from_setup"),
        candidates=candidates,
        base=r.opt_text("base"),
        values=values,
        disagreements=r.texts("disagreements"),
        notes=r.texts("notes"),
    )


def parse_catalog(data: object) -> Catalog:
    root = _R(data, "$")
    if root.integer("schema_version") != SCHEMA_VERSION:
        raise CatalogError(f"$.schema_version: expected {SCHEMA_VERSION}")
    params = tuple(_parse_parameter(p) for p in root.objs("parameters"))
    by_key = {p.key: p for p in params}
    if len(by_key) != len(params):
        raise CatalogError("$.parameters: duplicate key")
    if [p.order for p in params] != sorted(p.order for p in params) or len({p.order for p in params}) != len(params):
        raise CatalogError("$.parameters: must be listed in strictly increasing menu order")
    formats: dict[CarFormat, FormatInfo] = {}
    for fid, raw in root.mapping("formats"):
        info = _parse_format(fid, _R(raw, f"$.formats.{fid}"), set(by_key))
        formats[info.id] = info
    sources: dict[str, Source] = {}
    for sr in root.objs("sources"):
        s = _parse_source(sr)
        if s.id in sources:
            raise CatalogError(f"{sr.path}.id: duplicate source {s.id!r}")
        sources[s.id] = s
    setups: dict[str, SourceSetup] = {}
    for ssr in root.objs("source_setups"):
        ss = _parse_source_setup(ssr, formats, sources)
        if ss.id in setups:
            raise CatalogError(f"{ssr.path}.id: duplicate setup {ss.id!r}")
        setups[ss.id] = ss
    rules: dict[str, Rule] = {}
    for rr in root.objs("rules"):
        rule = _parse_rule(rr)
        rules[rule.id] = rule
    recs: dict[tuple[CarFormat, int, SessionKind, Conditions, Style], Recommendation] = {}
    for rec_r in root.objs("recommendations") if "recommendations" in root.d else []:
        rec = _parse_recommendation(rec_r, formats, by_key, setups, rules)
        if rec.key in recs:
            raise CatalogError(f"{rec_r.path}: duplicate recommendation {rec.key}")
        recs[rec.key] = rec
    return Catalog(
        game=root.text("game"),
        updated=root.date("updated"),
        research_doc=root.text("research_doc"),
        formats=formats,
        parameters=params,
        sources=sources,
        source_setups=setups,
        rules=rules,
        recommendations=recs,
        _params_by_key=by_key,
    )


def load_catalog_file(path: Path) -> Catalog:
    """Parse and validate a catalogue file; without a ``recommendations`` section, build them from the evidence."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CatalogError(f"cannot read {path}: {e}") from e
    cat = parse_catalog(data)
    if isinstance(data, dict) and "recommendations" not in data:
        from pitwall.carsetup.build import build_recommendations  # build imports this module

        cat = parse_catalog({**data, "recommendations": build_recommendations(cat)})
    return cat


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    """The packaged catalogue, parsed and validated once per process."""
    return load_catalog_file(DEFAULT_PATH)
