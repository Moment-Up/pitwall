"""Recommended rig settings for (game, platform, hardware, driver style, driver skill), with provenance on every value.

The engine is a pure function of the catalogue (``catalog.py``) and its inputs: no I/O, no LLM, no randomness, so
the same request always yields the same table and tests can pin it down exactly.

Pipeline for one request (rig-setup-sources.md section 6, research revision 2):

1. Look up ``recommendations.wheel[game, torque, style]`` and ``recommendations.pedals[game, pedals, style]``. A
   wheel entry with no source for that game (GT7 balanced/competitive) falls back to the style the research names
   and says so; nothing is invented to fill the gap. The pedal entry always uses the requested style (BRF by style
   comes from owner data for every style).
2. Build rows in the order the driver meets them: the Tuning Menu in on-wheel order (slot first, BRF last), then the
   game menus. Each row carries the provenance the catalogue computed: the presets that publish the value (or the
   range it was picked from), every other platform-compatible preset's value for comparison, the section 5
   consensus, owner reports and citations, a torque-transfer flag when only presets for the other torque back it,
   and the evidence label (never stronger than the weakest source).
3. Hardware: the 8 Nm entries already encode revision 2's rule (keep the in-game strength; only Comfort scales by
   5/8). Step and safety texts compare the 5 Nm and 8 Nm rows, so they say "lowered" only when the value really is
   lower, and "stays" only when it is equal; the peak torque they quote comes from the FF rows actually shown. FFS
   after the Boost Kit is an instruction ("check on your base"). The Load Cell Kit adds BRF and the load-cell
   calibration rows.
4. Driver rules (pitwall, evidence D): a strength scale (the driver's own, or the beginner default) lowers base FF in
   the driver's own custom slot; beginners get at least NDP 20. GT7's A SET values are copied to a custom slot first
   (A SET locks the menu). Every such change keeps the value it replaced in ``original``.

Why base FF for the driver scale (not in-game strength): FF caps every force the base sends, it lives in a custom
slot so switching drivers is one menu change, and it works with games that lock the menu. The endstop does not
depend on FF on current firmware.

The beginner default is a weight, not a ratio: it was set on the 5 Nm base (60%, about 3 Nm). On a stronger base the
default shrinks by the ratio of the two tables' peak torques (``weight_factor``: 5/8 for most tables, so 40% at 8 Nm)
so fitting the Boost Kit never makes a beginner's wheel heavier unnoticed. A scale the driver set explicitly is
applied as given (it is a share of the table's FF, the same number the slider shows); when the Boost Kit raises that
driver's peak, a safety step and the upgrade preview say so and give the scale that keeps the old weight.

The rig profile (``RigProfile``) also lives here because it is the input to every recommendation; the API module
persists it in the ``SettingsStore`` section ``"rig"``.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal, cast, get_args

from pitwall.rig.catalog import (
    PEDALS,
    STYLES,
    Backing,
    Catalog,
    Consensus,
    Evidence,
    GuideStep,
    Param,
    PedalEntry,
    PedalsId,
    Preset,
    SettingValue,
    Source,
    StyleId,
    WheelEntry,
    derivation_text,
    format_range,
    format_value,
    load_catalog,
    weakest,
)

log = logging.getLogger(__name__)

SkillLevel = Literal["beginner", "intermediate", "advanced"]
SKILL_LEVELS: tuple[SkillLevel, ...] = get_args(SkillLevel)
UpgradeChange = Literal["boost_kit_180", "load_cell_kit", "firmware", "rim", "other"]
UPGRADE_CHANGES: tuple[UpgradeChange, ...] = get_args(UpgradeChange)
HARDWARE_CHANGES: tuple[UpgradeChange, ...] = ("boost_kit_180", "load_cell_kit")
STRENGTH_KEY: Mapping[str, str] = {"f1_25": "VIB_FFB_STRENGTH", "gt7": "FFB_MAX_TORQUE"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RigValidationError(ValueError):
    """Invalid rig profile or preference input (the API maps it to 422)."""


class RecommendationUnavailable(ValueError):
    """The catalogue has no curated settings for this combination (the API maps it to 422)."""


def supported(cat: Catalog | None = None) -> frozenset[tuple[str, str]]:
    """(game, platform) pairs the curated tables cover (F1 25 on PS5 and PC, GT7 on PS5)."""
    return (cat or load_catalog()).supported


# ---------------------------------------------------------------------------------------------- profile
@dataclass(frozen=True, slots=True)
class Hardware:
    platform: str = "ps5"
    wheel_base: str = "fanatec_gt_dd_pro"
    torque_nm: int = 5
    pedals: PedalsId = "csl"
    rim: str = "gt_dd_pro_bundled"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class UpgradeEvent:
    """One entry of the upgrade history: lets a later rig check compare sessions before and after a change."""

    date: str  # YYYY-MM-DD (the day the change was made)
    change: UpgradeChange
    fitted: bool = True  # False records a removal (e.g. Boost Kit taken off again)
    note: str | None = None
    recorded_unix: float = 0.0  # when pitwall recorded it; used to split sessions before/after

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DriverRigPrefs:
    style: StyleId = "official_default"
    # 0.2-1.0 multiplies base FF in the driver's own slot (e.g. 0.6 for a younger driver); None = skill default.
    strength_scale: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RigProfile:
    """The family rig. Defaults are James's rig today: PS5, GT DD Pro 5 Nm, stock CSL Pedals, bundled rim."""

    platform: str = "ps5"
    wheel_base: str = "fanatec_gt_dd_pro"
    torque_nm: int = 5
    pedals: PedalsId = "csl"
    rim: str = "gt_dd_pro_bundled"
    upgrades: tuple[UpgradeEvent, ...] = ()
    drivers: Mapping[str, DriverRigPrefs] = field(default_factory=dict)  # key: str(driver_id)

    @property
    def hardware(self) -> Hardware:
        return Hardware(self.platform, self.wheel_base, self.torque_nm, self.pedals, self.rim)

    def prefs_for(self, driver_id: int | str | None) -> DriverRigPrefs:
        if driver_id is None:
            return DriverRigPrefs()
        return self.drivers.get(str(driver_id), DriverRigPrefs())

    def with_prefs(self, driver_id: int | str, prefs: DriverRigPrefs) -> RigProfile:
        return replace(self, drivers={**self.drivers, str(driver_id): prefs})

    def with_upgrade(self, event: UpgradeEvent) -> RigProfile:
        """Record ``event`` and apply its hardware effect (Boost Kit -> 8 Nm, Load Cell Kit -> load-cell pedals)."""
        p = replace(self, upgrades=(*self.upgrades, event))
        if event.change == "boost_kit_180":
            p = replace(p, torque_nm=8 if event.fitted else 5)
        elif event.change == "load_cell_kit":
            p = replace(p, pedals="csl_load_cell" if event.fitted else "csl")
        return p

    def last_hardware_upgrade(self) -> UpgradeEvent | None:
        hw = [u for u in self.upgrades if u.change in HARDWARE_CHANGES]
        return max(hw, key=lambda u: (u.recorded_unix, u.date)) if hw else None

    def hardware_at(self, unix: float | None) -> Hardware:
        """The hardware at ``unix`` (e.g. when a session started): today's hardware with every recorded Boost Kit /
        Load Cell Kit change made after that moment undone. Events without a recording time cannot be placed and
        are ignored."""
        hw = self.hardware
        if unix is None:
            return hw
        later = sorted(
            (u for u in self.upgrades if u.change in HARDWARE_CHANGES and u.recorded_unix > unix),
            key=lambda u: u.recorded_unix,
            reverse=True,
        )
        for u in later:
            if u.change == "boost_kit_180":
                hw = replace(hw, torque_nm=5 if u.fitted else 8)
            else:
                hw = replace(hw, pedals="csl" if u.fitted else "csl_load_cell")
        return hw

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "wheel_base": self.wheel_base,
            "torque_nm": self.torque_nm,
            "pedals": self.pedals,
            "rim": self.rim,
            "upgrades": [u.to_dict() for u in self.upgrades],
            "drivers": {k: v.to_dict() for k, v in sorted(self.drivers.items())},
        }

    @classmethod
    def from_stored(cls, raw: Mapping[str, Any], catalog: Catalog | None = None) -> RigProfile:
        """Lenient parse of the stored section: a bad field falls back to its default (logged) so one bad value
        never hides the whole profile."""
        cat = catalog or load_catalog()
        out = cls()

        def take(key: str, parse: Callable[[object], Any]) -> None:
            nonlocal out
            if key not in raw:
                return
            try:
                out = replace(out, **{key: parse(raw[key])})
            except RigValidationError as e:
                log.warning("rig profile: ignoring stored %s (%s)", key, e)

        take("platform", lambda v: parse_platform(v, cat))
        take("wheel_base", lambda v: parse_wheel_base(v, cat))
        take("torque_nm", lambda v: parse_torque(v, cat, out.wheel_base))
        take("pedals", parse_pedals)
        take("rim", lambda v: parse_rim(v, cat))
        events = []
        for i, e in enumerate(raw.get("upgrades") or []):
            try:
                events.append(parse_upgrade(e))
            except RigValidationError as err:
                log.warning("rig profile: ignoring stored upgrade %d (%s)", i, err)
        drivers = {}
        stored = raw.get("drivers")
        for k, v in stored.items() if isinstance(stored, Mapping) else []:
            try:
                drivers[str(k)] = parse_driver_prefs(v, cat)
            except RigValidationError as err:
                log.warning("rig profile: ignoring stored prefs for driver %s (%s)", k, err)
        return replace(out, upgrades=tuple(events), drivers=drivers)


def parse_platform(v: object, cat: Catalog) -> str:
    if not isinstance(v, str) or v not in cat.platforms:
        raise RigValidationError(f"platform must be one of {sorted(cat.platforms)}")
    return v


def parse_wheel_base(v: object, cat: Catalog) -> str:
    if not isinstance(v, str) or v not in cat.wheel_bases:
        raise RigValidationError(f"wheel_base must be one of {sorted(cat.wheel_bases)}")
    return v


def parse_torque(v: object, cat: Catalog, wheel_base: str) -> int:
    wb = cat.wheel_bases.get(wheel_base)
    options = list(wb.torque_variants_nm) if wb else []
    if isinstance(v, bool) or not isinstance(v, int | float) or int(v) != v or int(v) not in options:
        raise RigValidationError(f"torque_nm must be one of {options}")
    return int(v)


def parse_pedals(v: object) -> PedalsId:
    if not isinstance(v, str) or v not in PEDALS:
        raise RigValidationError(f"pedals must be one of {list(PEDALS)}")
    return v


def parse_rim(v: object, cat: Catalog) -> str:
    if not isinstance(v, str) or v not in cat.rims:
        raise RigValidationError(f"rim must be one of {sorted(cat.rims)}")
    return v


def parse_style(v: object) -> StyleId:
    if not isinstance(v, str) or v not in STYLES:
        raise RigValidationError(f"style must be one of {list(STYLES)}")
    return v


def parse_skill(v: object) -> SkillLevel:
    if isinstance(v, str) and v.strip().lower() in SKILL_LEVELS:
        return cast(SkillLevel, v.strip().lower())
    raise RigValidationError(f"skill_level must be one of {list(SKILL_LEVELS)}")


def parse_strength_scale(v: object, cat: Catalog) -> float | None:
    if v is None:
        return None
    rules = cat.driver_rules
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise RigValidationError(f"strength_scale must be between {rules.scale_min} and {rules.scale_max} (or null)")
    if not rules.scale_min <= v <= rules.scale_max:
        raise RigValidationError(f"strength_scale must be between {rules.scale_min} and {rules.scale_max} (or null)")
    return round(float(v), 2)


def parse_driver_prefs(v: object, cat: Catalog) -> DriverRigPrefs:
    if not isinstance(v, Mapping):
        raise RigValidationError("driver prefs must be an object")
    return DriverRigPrefs(
        style=parse_style(v.get("style", "official_default")),
        strength_scale=parse_strength_scale(v.get("strength_scale"), cat),
    )


def parse_upgrade(v: object) -> UpgradeEvent:
    if not isinstance(v, Mapping):
        raise RigValidationError("an upgrade event must be an object")
    date, change = v.get("date"), v.get("change")
    if not isinstance(date, str) or not _DATE.match(date):
        raise RigValidationError("upgrade date must be YYYY-MM-DD")
    if change not in UPGRADE_CHANGES:
        raise RigValidationError(f"upgrade change must be one of {list(UPGRADE_CHANGES)}")
    note = v.get("note")
    recorded = v.get("recorded_unix", 0.0)
    fitted = v.get("fitted", True)
    if not isinstance(fitted, bool):
        raise RigValidationError("fitted must be true or false")
    if note is not None and not isinstance(note, str):
        raise RigValidationError("note must be a string")
    if isinstance(recorded, bool) or not isinstance(recorded, int | float):
        raise RigValidationError("recorded_unix must be a number")
    return UpgradeEvent(date, cast(UpgradeChange, change), fitted, note, float(recorded))


# ---------------------------------------------------------------------------------------------- output types
@dataclass(frozen=True, slots=True)
class PresetRef:
    """A preset as cited by a row: its own published value for that setting. Details (name, URL, date,
    confidence) are in ``Recommendation.presets`` so each preset is described once per response."""

    id: str
    code: str
    value: str | None
    evidence: Evidence | None
    note: str | None
    applies_at_torque: bool  # the preset's values are meant for the rig's torque


@dataclass(frozen=True, slots=True)
class ReportRef:
    """An owner report (BRF on the exact pedal kit) behind a value."""

    id: str
    owner: str
    value: str | None
    stock: bool
    latest_for_owner: bool
    published: str
    url: str


@dataclass(frozen=True, slots=True)
class Citation:
    """A non-preset source: a manual or help article, a single expert, a research rule."""

    label: str
    url: str | None
    evidence: Evidence | None


@dataclass(frozen=True, slots=True)
class PresetInfo:
    id: str
    code: str
    name: str
    preference: str
    preference_inferred: bool
    torque_nm: int | None
    applies_to_torque_nm: tuple[int, ...]
    source_platform: str
    pedals: str | None
    confidence: str
    published: str
    game_version: str
    status: str
    stale: bool
    url: str
    author: str
    verified: bool


@dataclass(frozen=True, slots=True)
class Provenance:
    kind: str  # sourced | range_pick | derived | cited | instruction | locked
    evidence: Evidence  # of the value as shown (a pick inside a published range is D)
    derived: bool  # True only for values pitwall computed or chose (evidence D)
    basis: tuple[PresetRef, ...]  # presets whose published value (or range) is behind this value
    others: tuple[PresetRef, ...]  # every other platform-compatible preset that sets this key
    consensus: Consensus | None
    source: str | None
    reports: tuple[ReportRef, ...] = ()
    citations: tuple[Citation, ...] = ()
    derivation: str | None = None  # how pitwall derived or chose it
    original: Mapping[str, str] | None = None  # the value a driver rule replaced: {"value", "evidence"}
    range_basis: str | None = None  # published | across_sources | derived
    range_evidence: Evidence | None = None
    transfer: str | None = None  # set when only presets for the other torque publish this value
    stale: bool = False  # every preset behind the value predates a game update that changed FFB


@dataclass(frozen=True, slots=True)
class SettingRow:
    key: str
    label: str
    value: str
    range: str | None  # the published range (or pitwall's range for derived values)
    menu_range: str | None  # what the menu/hardware allows
    factory_default: str | None
    changed_from_default: bool
    needs_advanced: bool  # GT DD Pro: the Standard Tuning Menu cannot show this value
    locked: bool  # pushed by the game (A SET): read-only on the wheel
    instruction: bool  # the value is a check to make, not a number to type (FFS after the Boost Kit)
    notes: tuple[str, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class Step:
    id: str
    text: str
    evidence: Evidence
    derived: bool
    source: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Section:
    id: str  # base | wheel | ingame | pedals
    title: str
    steps: tuple[Step, ...] = ()
    rows: tuple[SettingRow, ...] = ()


@dataclass(frozen=True, slots=True)
class Recommendation:
    game: str
    game_name: str
    platform: str
    hardware: Hardware
    requested_style: StyleId
    style: StyleId  # the wheel table actually used (differs when the requested style has no source for this game)
    style_label: str
    sourced: bool  # the wheel table has a published source (False: every value derived by pitwall)
    skill_level: SkillLevel
    strength_scale: float  # effective scale applied to base FF (1.0 = none)
    strength_scale_source: str  # "driver" | "skill_default" | "none"
    peak_torque_nm: float  # hardware torque x FF / 100
    confidence: str
    pedal_confidence: str
    summary: str
    a_set: bool  # wheel values come from the game's Auto Setup
    stale: bool  # a basis preset predates a game update that changed FFB
    basis: tuple[str, ...]  # preset ids behind the wheel table
    presets: Mapping[str, PresetInfo]  # every preset cited anywhere in this response
    sections: tuple[Section, ...]
    safety: tuple[Step, ...]
    notes: tuple[str, ...]
    warnings: tuple[str, ...]
    rules: tuple[dict[str, Any], ...]  # research rules that apply to this game and style
    known_issues: tuple[dict[str, Any], ...]
    verify: tuple[dict[str, Any], ...]  # open questions to check on this hardware

    def rows(self) -> list[tuple[str, SettingRow]]:
        return [(s.id, r) for s in self.sections for r in s.rows]

    def row(self, key: str, section: str | None = None) -> SettingRow | None:
        for sid, r in self.rows():
            if r.key == key and (section is None or sid == section):
                return r
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RowDiff:
    section: str
    key: str
    label: str
    before: str | None
    after: str | None
    derived: bool
    evidence: Evidence | None


@dataclass(frozen=True, slots=True)
class UpgradePreview:
    """What changes when an upgrade that is not fitted yet arrives (e.g. the Boost Kit 180)."""

    change: UpgradeChange
    label: str
    hardware: Hardware
    diffs: tuple[RowDiff, ...]
    steps: tuple[Step, ...]
    peak_before_nm: float = 0.0  # the driver's peak wheel torque now (hardware torque x FF row / 100)
    peak_after_nm: float = 0.0  # and with the upgrade fitted
    notes: tuple[str, ...] = ()  # what the change means for this driver (e.g. the peak torque change)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------------------------- helpers
def _num(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _num_or_off(value: str | None) -> float | None:
    return 0.0 if value is not None and value.upper() == "OFF" else _num(value)


def round_to(x: float, step: int) -> int:
    """Round half up to a multiple of ``step`` (menus step in 5s; Python's round() would round 37.5 to 40 but
    32.5 to 30)."""
    return int(math.floor(x / step + 0.5) * step)


def effective_strength_scale(
    skill_level: SkillLevel, strength_scale: float | None, cat: Catalog, factor: float = 1.0
) -> tuple[float, str]:
    """The driver's explicit scale wins (applied as given); otherwise the skill default (beginner 0.6, others 1.0)
    applies. ``factor`` (``weight_factor``) shrinks a lighter-wheel default on a stronger base so it keeps the weight
    it had on the reference base; the result is rounded to the slider's 5% steps so the UI and the table agree."""
    rules = cat.driver_rules
    if strength_scale is not None:
        return min(rules.scale_max, max(rules.scale_min, strength_scale)), "driver"
    default = float(rules.skill_scale.get(skill_level, 1.0))
    if default < 1.0 and factor < 1.0:
        default = max(rules.scale_min, round_to(default * factor * 100.0, rules.scale_round_to) / 100.0)
    return default, ("skill_default" if default < 1.0 else "none")


def reference_torque(cat: Catalog, wheel_base: str | None = None) -> int:
    """The base torque the skill defaults were set on: the wheel base's lowest torque variant (5 Nm)."""
    wb = cat.wheel_bases.get(wheel_base or cat.wheel_base_id)
    return min(wb.torque_variants_nm) if wb is not None and wb.torque_variants_nm else 5


def _table(cat: Catalog, game: str, torque_nm: int, style: str) -> WheelEntry:
    """The wheel table a style really uses (an empty entry falls back to the style the research names)."""
    e = cat.wheel_entry(game, torque_nm, style)
    if e.empty and e.fallback_to is not None:
        e = cat.wheel_entry(game, torque_nm, e.fallback_to)
    return e


def _a_set_readout_of(cat: Catalog, entry: WheelEntry) -> Preset | None:
    """The basis preset that records what A SET pushes (GT7: the community readout after 1.71)."""
    setup = entry.wheel_settings.get("SETUP")
    if setup is None or str(setup.value).upper() != "A SET":
        return None
    for pid in entry.basis_presets:
        p = cat.presets[pid]
        sv = p.wheel_settings.get("SETUP")
        if sv is not None and str(sv.value).upper() == "A SET":
            return p
    return None


def table_ff(cat: Catalog, game: str, torque_nm: int, style: str) -> float | None:
    """The base FF a style's wheel table runs at ``torque_nm`` (A SET: the readout's FF, which the game pushes).
    None when the table sets no FF."""
    e = _table(cat, game, torque_nm, style)
    sv = e.wheel_settings.get("FF")
    if sv is None:
        readout = _a_set_readout_of(cat, e)
        sv = readout.wheel_settings.get("FF") if readout is not None else None
    return sv.number if sv is not None else None


def weight_factor(cat: Catalog, game: str, torque_nm: int, style: str, wheel_base: str | None = None) -> float:
    """How much a lighter-wheel default shrinks on ``torque_nm`` so it keeps the weight it had on the reference base:
    the ratio of the two tables' peak torques (torque x FF / 100), capped at 1. 1.0 on the reference base, when an FF
    is unknown, and when the table itself lowers the in-game strength to keep the reference weight (F1 Comfort at
    8 Nm: scaling FF as well would make the wheel lighter twice)."""
    ref = reference_torque(cat, wheel_base)
    if torque_nm <= ref:
        return 1.0
    key = STRENGTH_KEY.get(game)
    if key is not None:
        s_ref, s_now = _table(cat, game, ref, style).value(key), _table(cat, game, torque_nm, style).value(key)
        n_ref, n_now = (s_ref.number if s_ref else None), (s_now.number if s_now else None)
        if n_ref is not None and n_now is not None and n_now < n_ref:
            return 1.0
    ff_ref, ff_now = table_ff(cat, game, ref, style), table_ff(cat, game, torque_nm, style)
    if ff_ref is None or ff_now is None or ff_now <= 0:
        return 1.0
    return min(1.0, (ref * ff_ref) / (torque_nm * ff_now))


def _step(s: GuideStep, text: str | None = None) -> Step:
    return Step(s.id, text if text is not None else s.text, s.evidence, s.evidence == "D", s.source, s.detail)


@dataclass(slots=True)
class _Ctx:
    cat: Catalog
    game: str
    hw: Hardware
    wheel: WheelEntry
    pedal: PedalEntry
    skill: SkillLevel
    scale: float
    scale_source: str
    driver: str
    a_set: bool  # the wheel table is A SET (values pushed by the game)
    a_set_copied: bool  # A SET values copied into a custom slot (needed for a lighter wheel)
    factor: float = 1.0  # weight_factor for this table (1.0 on the reference base)
    ref_torque: int = 5  # the base torque the skill defaults were set on
    platform_presets: list[Preset] = field(default_factory=list)
    skipped_items: list[str] = field(default_factory=list)

    @property
    def locked(self) -> bool:
        """The game pushes the wheel values (A SET, not copied): nothing can be changed on the wheel."""
        return self.a_set and not self.a_set_copied


def _published(key: str, sv: SettingValue | None) -> str | None:
    if sv is None:
        return None
    return format_value(key, sv) or sv.as_published


def _ref(ctx: _Ctx, p: Preset, key: str) -> PresetRef:
    sv = p.setting(key)
    return PresetRef(
        id=p.id,
        code=p.code,
        value=_published(key, sv),
        evidence=sv.evidence if sv else None,
        note=(sv.note or (sv.as_published if sv.as_published and sv.as_published != _published(key, sv) else None))
        if sv
        else None,
        applies_at_torque=p.applies_at(ctx.hw.torque_nm),
    )


def _info(p: Preset) -> PresetInfo:
    src = p.sources[0]
    return PresetInfo(
        id=p.id,
        code=p.code,
        name=p.name,
        preference=p.preference,
        preference_inferred=p.preference_basis != "source_words",
        torque_nm=p.torque_nm,
        applies_to_torque_nm=p.applies_to_torque_nm,
        source_platform=p.source_platform,
        pedals=p.pedals,
        confidence=p.confidence,
        published=p.published,
        game_version=p.game_version,
        status=p.status,
        stale=p.stale,
        url=src.url,
        author=src.author,
        verified=all(x.verified for x in p.sources),
    )


def _others(ctx: _Ctx, key: str, exclude: Sequence[str]) -> tuple[PresetRef, ...]:
    """Every other platform-compatible preset that sets ``key``. BRF only from presets whose pedal values transfer
    to the rig's pedals (BRF does not transfer between Fanatec pedal models)."""
    model = ctx.cat.pedals[ctx.hw.pedals]
    out = []
    for p in ctx.platform_presets:
        if p.id in exclude or p.setting(key) is None:
            continue
        if key == "BRF" and (p.pedal_settings is None or model not in p.pedal_settings.transferable_to_pedals):
            continue
        out.append(_ref(ctx, p, key))
    return tuple(out)


def _codes(ctx: _Ctx, ids: Sequence[str]) -> str:
    return ", ".join(ctx.cat.presets[i].code for i in ids)


_VALUE_LABELS: frozenset[str] = frozenset({"V", "A", "U", "D"})


def _cites(sources: Sequence[Source], b: Backing) -> tuple[Citation, ...]:
    """A pedal entry's non-preset sources, as citations of one row. Only a row the catalogue backs as ``cited``
    shows them: a derived row (pitwall's own value) never borrows a source that did not publish it. The citation's
    label is the row's backing label, weakened further by the source's own label for its values when it has one,
    so a citation is never stronger than the value it stands behind."""
    if b.kind != "cited":
        return ()
    out = []
    for s in sources:
        ev = b.evidence
        if s.values_evidence in _VALUE_LABELS:
            ev = weakest(ev, cast(Evidence, s.values_evidence))
        out.append(Citation(s.author, s.url, ev))
    return tuple(out)


def _provenance(
    ctx: _Ctx,
    key: str,
    sv: SettingValue,
    b: Backing,
    entry_notes: str,
    *,
    reports: Sequence[str] = (),
    citations: Sequence[Citation] = (),
) -> Provenance:
    cat = ctx.cat
    ids = list(dict.fromkeys((*b.presets, *b.range_presets)))
    basis = tuple(_ref(ctx, cat.presets[i], key) for i in ids)
    rng = format_range(key, sv)
    derivation = None
    if b.kind == "derived":
        derivation = derivation_text(cat, key, sv, entry_notes)
        published = [cat.presets[i].setting(key) for i in b.presets]
        label = next((p.as_published for p in published if p is not None and p.as_published), None)
        if b.presets and sv.evidence != "D":
            # the value matches presets whose own entry is an inference (D): e.g. a source label mapped to a key
            derivation = (
                f"{_codes(ctx, b.presets)} publish{'es' if len(b.presets) == 1 else ''} "
                + (f"'{label}'" if label else "this value")
                + f", which the research reads as {key}: an inference, so pitwall marks it derived."
            )
    elif b.kind == "range_pick":
        derivation = f"pitwall's start value inside the published range {rng} ({_codes(ctx, b.presets)})." + (
            f" {sv.note}" if sv.note else ""
        )
    source = b.attribution
    cites = list(citations)
    if b.kind == "instruction":
        ins = cat.instructions[key]
        source = ins.note
        if ins.rule is not None:
            rule = cat.rules[ins.rule]
            cites.append(Citation(f"research rule {rule.id}: {rule.rule}", None, rule.evidence))
        param = cat.param(key, ctx.game)
        if param is not None and param.source_url and key == "FFS":
            cites.append(Citation("Fanatec App 1.5.1.2 release notes", param.source_url, "V"))
    transfer = None
    if b.transfer_from_nm:
        torques = " and ".join(f"{t} Nm" for t in b.transfer_from_nm)
        transfer = f"Published for {torques} only; used unchanged at {ctx.hw.torque_nm} Nm."
    backing_presets = [cat.presets[i] for i in b.presets]
    stale = bool(backing_presets) and all(p.stale for p in backing_presets)
    report_refs = tuple(_report_ref(ctx, r, key) for r in reports)
    return Provenance(
        kind=b.kind,
        evidence=b.evidence,
        derived=b.evidence == "D",
        basis=basis,
        others=_others(ctx, key, ids),
        consensus=cat.consensus_for(ctx.game, key),
        source=source,
        reports=report_refs,
        citations=tuple(cites),
        derivation=derivation,
        range_basis=b.range_basis,
        range_evidence=b.range_evidence,
        transfer=transfer,
        stale=stale,
    )


def _report_ref(ctx: _Ctx, rid: str, key: str) -> ReportRef:
    r = ctx.cat.pedal_reports[rid]
    return ReportRef(
        id=r.id,
        owner=r.owner,
        value=_published(key, r.values.get(key)),
        stock=r.stock,
        latest_for_owner=r.latest_for_owner,
        published=r.published,
        url=r.sources[0].url,
    )


def _needs_advanced(param: Param | None, key: str, value: str) -> bool:
    if key == "SETUP":
        return value.upper() not in ("A SET", "C SET")  # the Standard menu has A SET and one custom slot (C SET)
    if param is None or (param.menu or "").startswith("hardware") or value == param.factory_default:
        return False
    if param.advanced_only:
        return True
    if value.upper() == "OFF":
        return True  # the Standard menu has no OFF for FF or NDP
    n = _num(value)
    return n is not None and param.standard_min is not None and n < param.standard_min


def _make_row(
    ctx: _Ctx,
    key: str,
    sv: SettingValue,
    b: Backing,
    entry_notes: str,
    *,
    wheel: bool,
    reports: Sequence[str] = (),
    citations: Sequence[Citation] = (),
    extra_notes: Sequence[str] = (),
) -> SettingRow:
    param = ctx.cat.param(key, ctx.game)
    prov = _provenance(ctx, key, sv, b, entry_notes, reports=reports, citations=citations)
    instruction = b.kind == "instruction"
    value = ctx.cat.instructions[key].display if instruction else (format_value(key, sv) or "")
    default = param.factory_default if param else None
    notes = [n for n in (sv.note if b.kind not in ("derived", "range_pick") else None,) if n]
    if prov.transfer:
        notes.append(prov.transfer)
    notes.extend(extra_notes)
    return SettingRow(
        key=key,
        label=param.label if param else key,
        value=value,
        range=format_range(key, sv),
        menu_range=param.range if param else None,
        factory_default=default,
        changed_from_default=default is not None and not instruction and value != default,
        needs_advanced=wheel and not instruction and _needs_advanced(param, key, value),
        locked=False,
        instruction=instruction,
        notes=tuple(notes),
        provenance=prov,
    )


def _derive(row: SettingRow, value: str, derivation: str, *, note: str | None = None) -> SettingRow:
    """Replace a row's value with a pitwall derivation (a driver rule), keeping the replaced value visible."""
    prov = row.provenance
    original = prov.original or {"value": row.value, "evidence": prov.evidence}
    notes = (*row.notes, note) if note else row.notes
    return replace(
        row,
        value=value,
        range=None,
        notes=notes,
        changed_from_default=row.factory_default is not None and value != row.factory_default,
        locked=False,
        provenance=replace(
            prov,
            kind="derived",
            evidence="D",
            derived=True,
            derivation=derivation,
            original=original,
            range_basis=None,
            range_evidence=None,
        ),
    )


# ---------------------------------------------------------------------------------------------- rows
def _a_set_readout(ctx: _Ctx) -> Preset | None:
    """The basis preset that records what A SET pushes (GT7: the community readout after 1.71)."""
    return _a_set_readout_of(ctx.cat, ctx.wheel)


def _wheel_rows(ctx: _Ctx) -> list[SettingRow]:
    cat, e = ctx.cat, ctx.wheel
    rim = cat.rims.get(ctx.hw.rim)
    rows: dict[str, SettingRow] = {}
    for key, sv in e.wheel_settings.items():
        rows[key] = _make_row(ctx, key, sv, e.backing[key], e.notes, wheel=True)
    readout = _a_set_readout(ctx) if ctx.a_set else None
    if readout is not None:
        # What A SET pushes (read-only on the wheel), or, for a lighter wheel, the values to copy into a custom slot.
        for key, sv in readout.wheel_settings.items():
            if key == "SETUP" or key in rows:
                continue
            row = _make_row(ctx, key, sv, Backing("sourced", sv.evidence, (readout.id,)), "", wheel=True)
            if not ctx.a_set_copied:
                row = replace(row, locked=True, needs_advanced=False, provenance=replace(row.provenance, kind="locked"))
            rows[key] = row
    if ctx.hw.pedals == "csl_load_cell":
        for key, sv in ctx.pedal.pedal_values.items():
            notes = []
            if ctx.pedal.kg_estimate is not None:
                kg = ctx.pedal.kg_estimate
                notes.append(f"About {kg.value_kg:g} kg at the pedal for 100% (unverified linear estimate: {kg.note})")
            b = ctx.pedal.backing[key]
            rows[key] = _make_row(
                ctx,
                key,
                sv,
                b,
                ctx.pedal.notes,
                wheel=True,
                reports=ctx.pedal.basis_pedal_reports,
                citations=_cites(ctx.pedal.basis_sources, b),
                extra_notes=notes,
            )
    out: list[SettingRow] = []
    for key in cat.menu_order:
        found = rows.get(key)
        if found is not None:
            out.append(_driver_rules(ctx, found))
    for key in cat.rim_items:
        if rim is None or key not in rim.has_items:
            ctx.skipped_items.append(key)
    return out


def _driver_rules(ctx: _Ctx, row: SettingRow) -> SettingRow:
    rules = ctx.cat.driver_rules
    param = ctx.cat.param(row.key, ctx.game)
    if row.key == "SETUP" and ctx.scale < 1.0:
        row = _derive(
            row,
            rules.driver_slot,
            f"{rules.driver_slot_explanation} Replaces {row.value} for {ctx.driver}.",
            note=f"Use {ctx.driver}'s own slot so other drivers keep theirs.",
        )
        return replace(row, needs_advanced=True)
    if row.key == "FF" and ctx.scale < 1.0:
        base = _num(row.value)
        if base is not None:
            step = rules.scale_round_to
            ff = max(5, round_to(base * ctx.scale, step))
            why = "driver strength preference" if ctx.scale_source == "driver" else f"{ctx.skill} default"
            if ctx.scale_source == "skill_default" and ctx.factor < 1.0:
                at_ref = float(rules.skill_scale.get(ctx.skill, 1.0))
                why = (
                    f"{ctx.skill} default: {at_ref:.0%} on the {ctx.ref_torque} Nm base, {ctx.scale:.0%} at "
                    f"{ctx.hw.torque_nm} Nm so the wheel keeps about the weight it had on the {ctx.ref_torque} Nm base"
                )
            row = _derive(
                row,
                str(ff),
                f"{row.value} x {ctx.scale:g} = {ff} ({why}; rounded to {step}). Peak torque about "
                f"{ctx.hw.torque_nm * ff / 100:.1f} Nm instead of {ctx.hw.torque_nm * base / 100:.1f} Nm.",
                note=f"Set it in {ctx.driver}'s own custom slot so other drivers keep their FF.",
            )
            return replace(row, needs_advanced=_needs_advanced(param, row.key, row.value))
    if row.key == "NDP" and ctx.skill == "beginner":
        cur = _num_or_off(row.value)
        if cur is not None and cur < rules.ndp_floor:
            row = _derive(row, str(rules.ndp_floor), f"beginner floor: {row.value} raised to NDP {rules.ndp_floor}.")
            return replace(row, needs_advanced=_needs_advanced(param, row.key, row.value))
    return row


def _ingame_rows(ctx: _Ctx) -> list[SettingRow]:
    game = ctx.cat.games[ctx.game]
    w, p = ctx.wheel, ctx.pedal
    rows = []
    for key in game.params:
        if key in p.ingame_settings:  # the pedal entry wins on brake/throttle calibration keys
            b = p.backing[key]
            cites = _cites(p.basis_sources, b)
            rows.append(_make_row(ctx, key, p.ingame_settings[key], b, p.notes, wheel=False, citations=cites))
        elif key in w.ingame_settings:
            rows.append(_make_row(ctx, key, w.ingame_settings[key], w.backing[key], w.notes, wheel=False))
    return rows


# ---------------------------------------------------------------------------------------------- steps
def _peak_sentence(ff5: float | None, ff8: float | None) -> str:
    """The base's peak torque at 5 and 8 Nm from the FF actually set (arithmetic: torque x FF / 100). Empty when an
    FF is unknown."""
    if ff5 is None or ff8 is None:
        return ""
    p5, p8 = 5.0 * ff5 / 100.0, 8.0 * ff8 / 100.0
    if math.isclose(p5, p8, abs_tol=0.05):
        return f" At FF {ff8:g} the base peaks at about {p8:.1f} Nm, the same as at FF {ff5:g} on the 5 Nm base."
    return (
        f" At FF {ff8:g} the base peaks at about {p8:.1f} Nm, against {p5:.1f} Nm at FF {ff5:g} on the 5 Nm base"
        f" ({p8 / p5:.1f}x)."
    )


def strength_at_8nm(
    cat: Catalog, game: str, style: StyleId, ff: tuple[float | None, float | None] | None = None
) -> tuple[str, Evidence, str]:
    """What the 8 Nm table does with the in-game strength, worded from the two tables (never from intent):
    "stays" only when equal, "lowered" only when lower. Returns (text, evidence, change) with change one of
    kept | lowered | raised | none. ``ff``: the driver's (5 Nm, 8 Nm) FF for the peak-torque sentence (default: the
    tables' own FF). The evidence is never stronger than either table's value or the research rule behind the
    wording."""
    key = STRENGTH_KEY[game]
    e5, e8 = _table(cat, game, 5, style), _table(cat, game, 8, style)
    s5, s8 = e5.value(key), e8.value(key)
    param = cat.games[game].params[key]
    if s5 is None or s8 is None:
        return "This style sets no in-game strength.", "D", "none"
    ff5, ff8 = ff if ff is not None else (table_ff(cat, game, 5, e5.preference), table_ff(cat, game, 8, e8.preference))
    peak = _peak_sentence(ff5, ff8)
    v5, v8 = format_value(key, s5) or "", format_value(key, s8) or ""
    n5, n8 = _num(v5), _num(v8)
    b5, b8 = e5.backing[key], e8.backing[key]
    label = param.label
    if v5 == v8:
        if game == "f1_25":
            rule = cat.rules["f1_torque_5_to_8_keep_strength"]
            return (
                f"{label} stays at {v8} at 8 Nm: every source that publishes values for both torques keeps the "
                f"in-game value, and none lowers it.{peak}",
                weakest(rule.evidence, b5.evidence, b8.evidence),
                "kept",
            )
        gt7_rule = cat.rules.get("gt7_torque_5_to_8")
        ev = weakest(gt7_rule.evidence if gt7_rule else "U", b5.evidence, b8.evidence)
        lo = param.min if param.min is not None else 1.0
        hi = param.max if param.max is not None else 10.0
        if e8.preference == "official_default":
            # research rule gt7_torque_5_to_8 (section 6.4), written for the Official (A SET) entry
            return (
                f"{label} stays at {v8}: GT7's scale ({lo:g}-{hi:g}) is not in Nm and not linear, and Fanatec's GT7"
                " values are stated to suit both torques. After fitting the kit, restart at Max. Torque 5 (4-5 with"
                f" A SET) and step up by feel; post-hotfix 8 Nm reports range 5-10 with no consensus.{peak}",
                ev,
                "kept",
            )
        src = sorted({cat.presets[i].code for i in (*b8.presets, *b8.range_presets)})
        torques = sorted({t for i in (*b8.presets, *b8.range_presets) if (t := cat.presets[i].torque_nm)})
        made = (
            f" ({', '.join(src)}, set up at {'/'.join(str(t) for t in torques)} Nm)"
            if src and torques
            else (f" ({', '.join(src)})" if src else "")
        )
        return (
            f"{label} stays at {v8}{made}: GT7's scale ({lo:g}-{hi:g}) is not in Nm and not linear, so adjust it by"
            f" feel.{peak}",
            ev,
            "kept",
        )
    if n5 is not None and n8 is not None and n8 < n5:
        factor = cat.rules["f1_torque_5_to_8_comfort"].factor or 0.625
        why = (
            f"{v5} x 5/8, pitwall derived, to keep the 5 Nm weight"
            if round_to(n5 * factor, 5) == int(n8)
            else "pitwall derived"
        )
        return f"{label} is lowered from {v5} to {v8} ({why}).", "D", "lowered"
    rng = format_range(key, s8)
    src_ids = dict.fromkeys((*b8.presets, *b8.range_presets))
    codes = ", ".join(cat.presets[i].code for i in src_ids) or "pitwall"
    return (
        f"{label} goes up from {v5} to {v8} at 8 Nm"
        + (f" (start value inside the 8 Nm range {rng}, {codes})" if rng else f" ({codes})")
        + f".{peak}",
        weakest(b5.evidence, b8.evidence),
        "raised",
    )


def tiring_tail(cat: Catalog, game: str, style: StyleId, *, locked: bool = False) -> str:
    """What to do if the first sessions after the Boost Kit are tiring (research rule first_session_after_boost_kit,
    "lower in-game strength in steps of 5-10 or use the comfort entry"), in the game's own scale. GT7's Max. Torque
    runs 1-10, so steps of 5-10 make no sense there: pitwall translates them to 1-2 steps (or 10-20 FF in a custom
    slot; not under A SET, which locks the wheel). "Use Comfort" is left out when Comfort is already the style."""
    key = STRENGTH_KEY[game]
    param = cat.games[game].params[key]
    if game == "gt7":
        lo = param.min if param.min is not None else 1.0
        hi = param.max if param.max is not None else 10.0
        options = [f"lower {param.label} by 1-2 (its scale runs {lo:g}-{hi:g})"]
        if not locked:
            options.append("lower FF by 10-20 in your custom slot")
    else:
        options = [f"step {param.label} down by 5-10"]
    if style != "comfort":
        options.append("use Comfort")
    joined = options[0] if len(options) == 1 else ", ".join(options[:-1]) + " or " + options[-1]
    return f" If the first sessions are tiring, {joined}."


def _driver_ff_pair(ctx: _Ctx, ff_row: SettingRow | None) -> tuple[float | None, float | None]:
    """The driver's FF on the 5 Nm base and on this one (for the peak-torque sentence): the 5 Nm table's FF with the
    same driver rule applied (the reference base has factor 1, so the reference skill default)."""
    ff_now = _num(ff_row.value) if ff_row is not None else None
    base5 = table_ff(ctx.cat, ctx.game, ctx.ref_torque, ctx.wheel.preference)
    if base5 is None:
        return None, ff_now
    scale5, _ = effective_strength_scale(ctx.skill, ctx.scale if ctx.scale_source == "driver" else None, ctx.cat)
    ff5 = float(max(5, round_to(base5 * scale5, ctx.cat.driver_rules.scale_round_to))) if scale5 < 1.0 else base5
    return ff5, ff_now


def _exact_ab(ctx: _Ctx, s: GuideStep) -> Step | None:
    """Research rule exact_5nm_feel_at_8nm: FF 63 with the 5 Nm in-game values reproduces the 5 Nm torque map. Only
    for a driver on the full table (a lighter slot already runs a lower FF, so "return to FF 100" would be wrong),
    and only for F1 25 (GT7's Official slot is A SET, which cannot be changed on the wheel)."""
    if ctx.game != "f1_25" or ctx.scale < 1.0:
        return None
    cat, key = ctx.cat, STRENGTH_KEY[ctx.game]
    label = cat.games[ctx.game].params[key].label
    e5, e8 = _table(cat, ctx.game, ctx.ref_torque, ctx.wheel.preference), ctx.wheel
    ff5 = table_ff(cat, ctx.game, ctx.ref_torque, ctx.wheel.preference)
    ff8 = table_ff(cat, ctx.game, ctx.hw.torque_nm, ctx.wheel.preference)
    s5, s8 = e5.value(key), e8.value(key)
    if ff5 is None or ff8 is None or s5 is None or s8 is None:
        return None
    v5, v8 = format_value(key, s5) or "", format_value(key, s8) or ""
    ab = math.floor(ff5 * ctx.ref_torque / ctx.hw.torque_nm + 0.5)  # 100 x 5/8 = 62.5 -> 63 (the research's value)
    same = v5 == v8
    text = (
        f"For an exact A/B with the old {ctx.ref_torque} Nm feel, set FF {ab}"
        + (" with every in-game value unchanged" if same else f" and {label} back to {v5} (the 5 Nm value)")
        + " for one back-to-back test (it reproduces the 5 Nm torque map, including its clipping), then return to"
        + f" FF {ff8:g}"
        + ("" if same else f" and {label} {v8}")
        + "."
    )
    return _step(s, text)


def _boost_kit_steps(ctx: _Ctx, wheel_rows: Sequence[SettingRow]) -> list[Step]:
    out = []
    ff_row = next((r for r in wheel_rows if r.key == "FF"), None)
    for s in ctx.cat.boost_kit_steps:
        if not s.for_game(ctx.game):
            continue
        if s.id == "strength":
            text, ev, _ = strength_at_8nm(ctx.cat, ctx.game, ctx.wheel.preference, _driver_ff_pair(ctx, ff_row))
            out.append(Step(s.id, text, ev, ev == "D", s.source, s.detail))
            continue
        if s.id == "exact_ab":
            step = _exact_ab(ctx, s)
            if step is not None:
                out.append(step)
            continue
        if s.id == "holding_torque":
            out.append(_step(s, s.text + tiring_tail(ctx.cat, ctx.game, ctx.wheel.preference, locked=ctx.locked)))
            continue
        out.append(_step(s))
    return out


def _base_steps(ctx: _Ctx, wheel_rows: Sequence[SettingRow], ingame_rows: Sequence[SettingRow]) -> list[Step]:
    cat, hw = ctx.cat, ctx.hw
    plat = cat.platforms[hw.platform]
    fw = cat.firmware
    steps = [
        Step(
            "mode",
            f"Put the base in {plat.base_mode} mode (power-button LED). {plat.base_mode_note}",
            "V",
            False,
            "GT DD Pro manual 5.6; Fanatec help",
        ),
        Step(
            "firmware",
            f"Firmware: the current set is base {fw['base']} (Fanatec App {fw['app']}, {fw['date']}). Updating needs a"
            " Windows PC with the base in RED mode; afterwards switch back, recalibrate the wheel centre and recheck"
            " your slot values.",
            "V",
            False,
            f"Fanatec App {fw['app']} release notes",
        ),
    ]
    advanced = [f"{r.key} {r.value}" for r in wheel_rows if r.needs_advanced]
    readout = _a_set_readout(ctx) if ctx.a_set else None
    readout_detail = (
        f"The A SET rows are {readout.code}'s community readout"
        + (f" ({readout.firmware_note.rstrip('.')})" if readout.firmware_note else "")
        + ". Whether A SET differs between 5 and 8 Nm is unknown: read yours on the wheel while the game runs."
        if readout is not None
        else None
    )
    if ctx.a_set and not ctx.a_set_copied:
        steps.append(
            Step(
                "slot",
                "Select A SET: the game pushes its own values to the base and the menu shows LOCKED. The rows below"
                " are what A SET is reported to push; you cannot change them there.",
                "V",
                False,
                "GT7 1.71 notice; GT DD Pro manual 5.6.1",
                readout_detail,
            )
        )
    else:
        if advanced:
            steps.append(
                Step(
                    "menu",
                    "Switch to the Advanced Tuning Menu: hold the Tuning button for about 4 s (Fanatec's FAQ says"
                    f" 3 s). The Standard menu cannot show: {', '.join(advanced)}.",
                    "V",
                    False,
                    "GT DD Pro manual 5.6.1",
                )
            )
        else:
            steps.append(
                Step(
                    "menu", "The Standard Tuning Menu can show every value below.", "V", False, "GT DD Pro manual 5.6.1"
                )
            )
        if ctx.a_set_copied:
            steps.append(
                Step(
                    "slot",
                    "A SET locks the menu, so read its values on the wheel while the game runs, copy them into"
                    f" {ctx.driver}'s own custom slot and lower FF there.",
                    "D",
                    True,
                    "rig-setup-sources.md 6.4 (A SET readout method) and pitwall's driver strength rule",
                    readout_detail,
                )
            )
        if ctx.game == "f1_25":
            steps.append(
                Step(
                    "no_a_set_f1",
                    "Do not use A SET for F1 25: it hands control to the game and locks the values, and F1 25"
                    " support for it is undocumented.",
                    "U",
                    False,
                    "GT DD Pro manual 5.6.1; rig-setup-sources.md 2",
                )
            )
    if ctx.scale < 1.0:
        steps.append(
            Step(
                "driver_slot",
                f"Give {ctx.driver} their own spare slot ({cat.driver_rules.driver_slot} or 5 SET) with the lighter FF"
                " below, so switching drivers is one menu change.",
                "D",
                True,
                "pitwall driver rule",
            )
        )
    rot = next((r for r in ingame_rows if r.key == "MAX_WHEEL_ROTATION"), None)
    sen = next((r for r in wheel_rows if r.key == "SEN"), None)
    if rot is not None and sen is not None:
        steps.append(
            Step(
                "sen_match",
                f"Set SEN on the wheel to {sen.value}, the same as Maximum Wheel Rotation in the game. Do not rely"
                " on AUTO in F1 (known issue). Turn the wheel 90 degrees and check the on-screen wheel matches.",
                "V",
                False,
                "Fanatec App 1.6.1.3 known issues; Fanatec F1 25 pages",
            )
        )
    if ctx.game == "f1_25" and hw.torque_nm != 8:  # at 8 Nm the Boost Kit steps carry it
        steps.append(
            Step(
                "v125_bug",
                "F1 25 v1.25 known bug: if the wheel oscillates or loses force feedback after a session change"
                " (for example Qualifying to Race), pause and power-cycle the base. Do not tune NDP, INT or the damper"
                " against it. Every report that states a torque is at 8 Nm.",
                "V",
                False,
                "EA forums threads 13695137 / 13701405; forum.fanatec.com topic 20597",
            )
        )
    if hw.torque_nm == 8:
        steps.extend(_boost_kit_steps(ctx, wheel_rows))
    steps.append(
        Step(
            "one_change",
            "Change one thing at a time, then drive the same car and track and run the rig check to compare.",
            "V",
            False,
            "Fanatec F1 25 and oscillation pages; SimXPro (rig-setup-sources.md 7)",
        )
    )
    return steps


def _rim_step(ctx: _Ctx) -> Step | None:
    if not ctx.skipped_items:
        return None
    rim = ctx.cat.rims.get(ctx.hw.rim)
    name = rim.name if rim else "this rim"
    missing = [k for k in ctx.skipped_items if rim is None or k not in rim.unknown_items]
    unknown = [k for k in ctx.skipped_items if rim is not None and k in rim.unknown_items]
    parts = []
    if missing:
        what = " or ".join(ctx.cat.rim_items[k] for k in missing)
        parts.append(
            f"{' and '.join(missing)} are left out: the {name} has no {what}. Skip them if the menu shows them."
        )
    if unknown:
        what = ", ".join(f"{k} ({ctx.cat.rim_items[k]})" for k in unknown)
        parts.append(
            f"Not recommended here because it is not known whether the {name} has them: {what}. If the menu shows"
            " them, leave them at their defaults."
        )
    return Step("rim_items", " ".join(parts), "V" if missing and not unknown else "U", False, "GT DD Pro manual 5.6")


def _brf_owner_step(ctx: _Ctx, s: GuideStep) -> Step:
    """The owner reports and the BRF start value of every style, read from the pedal table (never retyped, so the
    step cannot drift from the rows when the research changes)."""
    cat = ctx.cat
    st = cat.brf_owner_stats
    vals = ", ".join(f"{v:g}" for v in st.values)
    param = cat.param("BRF", ctx.game)
    starts = []
    for sid in STYLES:
        entry = cat.pedal_entries.get((ctx.game, "csl_load_cell", sid))
        sv = entry.pedal_values.get("BRF") if entry is not None else None
        if sv is None:
            continue
        v, rng = format_value("BRF", sv) or "", format_range("BRF", sv)
        extra = " (factory default)" if param is not None and v == param.factory_default else ""
        starts.append(f"{cat.styles[sid].label} {v}{extra}" + (f" ({rng})" if rng else ""))
    return _step(
        s,
        f"Owners of this exact kit (CSL Pedals Load Cell Kit, stock, latest value each, n={st.n}) run BRF {vals}: "
        f"median {st.median:g}. pitwall's starting points by style are derived from them: {', '.join(starts)}.",
    )


def _pedal_steps(ctx: _Ctx) -> list[Step]:
    out = []
    for s in ctx.cat.pedal_steps[ctx.hw.pedals]:
        if not s.for_game(ctx.game):
            continue
        out.append(_brf_owner_step(ctx, s) if s.id == "brf_owners" else _step(s))
    return out


def _safety(ctx: _Ctx, wheel_rows: Sequence[SettingRow], requested: StyleId) -> list[Step]:
    rules = ctx.cat.driver_rules
    out = []
    ff = next((r for r in wheel_rows if r.key == "FF" and r.provenance.original is not None), None)
    if ff is not None:
        out.append(
            Step(
                "lighter_wheel",
                f"Lighter wheel for {ctx.driver}: FF {ff.value} in their own slot, a peak of about "
                f"{ctx.hw.torque_nm * float(ff.value) / 100:.1f} Nm instead of "
                f"{ctx.hw.torque_nm * float(_num((ff.provenance.original or {}).get('value')) or 100) / 100:.1f} Nm.",
                "D",
                True,
                "pitwall rule (no published source)",
                rules.scale_explanation,
            )
        )
    ndp = next((r for r in wheel_rows if r.key == "NDP" and r.provenance.original is not None), None)
    if ndp is not None:
        out.append(
            Step(
                "calmer_wheel",
                f"Calmer wheel: NDP {ndp.value} instead of {(ndp.provenance.original or {}).get('value')}.",
                "D",
                True,
                "pitwall rule",
                rules.ndp_floor_explanation,
            )
        )
    if ctx.skill == "beginner" or ctx.scale < 1.0:
        out.append(
            Step(
                "hands",
                "Keep thumbs on the front of the rim, not hooked behind the spokes: a direct-drive wheel can snap"
                " round when the car spins or hits a wall.",
                "D",
                True,
                "general direct-drive safety advice (pitwall)",
            )
        )
    if ctx.skill == "beginner" and requested == "competitive":
        out.append(
            Step(
                "competitive_beginner",
                "Competitive settings assume an experienced driver (no damping, high strength). The beginner"
                " adjustments above still apply; consider Official or Comfort to start.",
                "D",
                True,
                "pitwall rule",
            )
        )
    driver_force = _driver_force_after_kit(ctx, ff)
    if driver_force is not None:
        out.append(driver_force)
    if ctx.hw.torque_nm == 8 and ctx.skill != "advanced":
        ff_row = next((r for r in wheel_rows if r.key == "FF"), None)
        text, _ev, change = strength_at_8nm(ctx.cat, ctx.game, ctx.wheel.preference, _driver_ff_pair(ctx, ff_row))
        tail = (
            tiring_tail(ctx.cat, ctx.game, ctx.wheel.preference, locked=ctx.locked)
            if change in ("kept", "raised")
            else ""
        )
        out.append(
            Step(
                "boost_kit_force",
                f"After the Boost Kit: {text}{tail}",
                "D",
                True,
                "rig-setup-sources.md 5.2, 6.2 and 6.4 (peak torque is arithmetic: base torque x FF / 100)",
            )
        )
    return out


def _driver_force_after_kit(ctx: _Ctx, ff: SettingRow | None) -> Step | None:
    """A force scale the driver set explicitly is applied as given, so on a stronger base their peak rises. Say so,
    with the scale that keeps the weight they had on the reference base (the skill default does that by itself)."""
    if ff is None or ctx.scale_source != "driver" or ctx.factor >= 1.0 or ctx.hw.torque_nm <= ctx.ref_torque:
        return None
    ff5, ff_now = _driver_ff_pair(ctx, ff)
    if ff5 is None or ff_now is None:
        return None
    p_ref, p_now = ctx.ref_torque * ff5 / 100.0, ctx.hw.torque_nm * ff_now / 100.0
    if p_now <= p_ref * 1.05:
        return None
    rules = ctx.cat.driver_rules
    keep = max(rules.scale_min, round_to(ctx.scale * ctx.factor * 100.0, rules.scale_round_to) / 100.0)
    return Step(
        "boost_kit_driver_force",
        f"Heavier wheel for {ctx.driver} after the Boost Kit: their force setting ({ctx.scale:.0%}) now applies to"
        f" the {ctx.hw.torque_nm} Nm base, a peak of about {p_now:.1f} Nm instead of {p_ref:.1f} Nm on the"
        f" {ctx.ref_torque} Nm base. Set their force to {keep:.0%} to keep the old weight.",
        "D",
        True,
        "pitwall rule (arithmetic: base torque x FF / 100)",
        ctx.cat.driver_rules.scale_explanation,
    )


# ---------------------------------------------------------------------------------------------- entry points
def recommend(
    game: str,
    hardware: Hardware,
    style: str = "official_default",
    skill_level: str = "intermediate",
    strength_scale: float | None = None,
    driver_name: str | None = None,
    catalog: Catalog | None = None,
) -> Recommendation:
    """Ordered, provenance-carrying settings for one driver on one rig in one game."""
    cat = catalog or load_catalog()
    if game not in cat.games:
        raise RecommendationUnavailable(f"unknown game {game!r}; options: {sorted(cat.games)}")
    if (game, hardware.platform) not in cat.supported:
        raise RecommendationUnavailable(
            f"no curated {cat.games[game].name} settings for {hardware.platform}; supported: "
            + ", ".join(f"{g}/{p}" for g, p in sorted(cat.supported))
        )
    parse_wheel_base(hardware.wheel_base, cat)
    parse_torque(hardware.torque_nm, cat, hardware.wheel_base)
    parse_pedals(hardware.pedals)
    parse_rim(hardware.rim, cat)
    requested = parse_style(style)
    skill = parse_skill(skill_level)
    if strength_scale is not None:
        strength_scale = parse_strength_scale(strength_scale, cat)

    warnings: list[str] = []
    entry = cat.wheel_entry(game, hardware.torque_nm, requested)
    used: StyleId = requested
    if entry.empty:
        assert entry.fallback_to is not None  # validated by the catalogue loader
        used = entry.fallback_to
        warnings.append(f"{entry.notes} Showing {cat.styles[used].label} instead.")
        entry = cat.wheel_entry(game, hardware.torque_nm, used)
    pedal = cat.pedal_entry(game, hardware.pedals, requested)
    factor = weight_factor(cat, game, hardware.torque_nm, used, hardware.wheel_base)
    scale, scale_source = effective_strength_scale(skill, strength_scale, cat, factor)
    setup = entry.wheel_settings.get("SETUP")
    a_set = setup is not None and str(setup.value).upper() == "A SET"
    ctx = _Ctx(
        cat=cat,
        game=game,
        hw=hardware,
        wheel=entry,
        pedal=pedal,
        skill=skill,
        scale=scale,
        scale_source=scale_source,
        driver=driver_name or "this driver",
        a_set=a_set,
        a_set_copied=a_set and scale < 1.0,
        factor=factor,
        ref_torque=reference_torque(cat, hardware.wheel_base),
        platform_presets=cat.presets_for(game=game, platform=hardware.platform, wheel_base=hardware.wheel_base),
    )
    wheel = _wheel_rows(ctx)
    ingame = _ingame_rows(ctx)
    basis = [cat.presets[b] for b in entry.basis_presets]
    stale = any(p.stale for p in basis)
    for p in basis:
        if p.stale:
            warnings.append(f"{p.code} ({p.name}) is stale: {' '.join(p.stale_reasons)} Treat it as a starting point.")
    transferred = any(r.provenance.transfer for r in (*wheel, *ingame))
    if transferred and basis and not any(p.applies_at(hardware.torque_nm) for p in basis):
        made = sorted({t for p in basis for t in p.applies_to_torque_nm})
        warnings.append(
            f"The source for this style was made for {' and '.join(f'{t} Nm' for t in made)}, not "
            f"{hardware.torque_nm} Nm: rows marked as transferred use its values unchanged."
        )
    if not entry.sourced and not entry.empty:
        warnings.append(f"No published source for {cat.styles[used].label} here: {entry.notes}")
    rim_step = _rim_step(ctx)
    ff = next((r for r in wheel if r.key == "FF"), None)
    ff_val = _num(ff.value) if ff is not None else None
    sections = (
        Section("base", "1. Base mode and Tuning Menu", steps=tuple(_base_steps(ctx, wheel, ingame))),
        Section(
            "wheel",
            "2. Wheel base Tuning Menu (on-wheel order)",
            steps=(rim_step,) if rim_step else (),
            rows=tuple(wheel),
        ),
        Section("ingame", f"3. {cat.games[game].name}: in-game settings", rows=tuple(ingame)),
        Section(
            "pedals", f"4. Pedals: {cat.pedal_models[cat.pedals[hardware.pedals]].name}", steps=tuple(_pedal_steps(ctx))
        ),
    )
    notes = tuple(n for n in (pedal.notes,) if n)
    return Recommendation(
        game=game,
        game_name=cat.games[game].name,
        platform=hardware.platform,
        hardware=hardware,
        requested_style=requested,
        style=used,
        style_label=cat.styles[used].label,
        sourced=entry.sourced,
        skill_level=skill,
        strength_scale=scale,
        strength_scale_source=scale_source,
        peak_torque_nm=round(hardware.torque_nm * (ff_val if ff_val is not None else 100.0) / 100.0, 2),
        confidence=entry.confidence,
        pedal_confidence=pedal.confidence,
        summary=entry.notes,
        a_set=ctx.a_set and not ctx.a_set_copied,
        stale=stale,
        basis=entry.basis_presets,
        presets=_cited(cat, entry, sections),
        sections=sections,
        safety=tuple(_safety(ctx, wheel, requested)),
        notes=notes,
        warnings=tuple(warnings),
        rules=tuple(r.to_dict() for r in cat.rules.values() if r.applies(game, used)),
        known_issues=tuple(i.to_dict() for i in cat.known_issues_for(game, hardware.pedals, hardware.torque_nm)),
        verify=tuple(q.to_dict() for q in cat.open_questions_for(game, hardware.pedals, hardware.torque_nm)),
    )


def _cited(cat: Catalog, entry: WheelEntry, sections: Sequence[Section]) -> dict[str, PresetInfo]:
    ids = set(entry.basis_presets)
    for s in sections:
        for r in s.rows:
            ids.update(ref.id for ref in (*r.provenance.basis, *r.provenance.others))
    return {pid: _info(cat.preset(pid)) for pid in sorted(ids)}


def diff_recommendations(before: Recommendation, after: Recommendation) -> list[RowDiff]:
    """Rows whose value appears, disappears or changes between two recommendations (same game)."""
    a = {(s, r.key): r for s, r in before.rows()}
    b = {(s, r.key): r for s, r in after.rows()}
    out = []
    for k in [*a, *(k for k in b if k not in a)]:
        ra, rb = a.get(k), b.get(k)
        va, vb = (ra.value if ra else None), (rb.value if rb else None)
        if va == vb:
            continue
        row = rb if rb is not None else ra
        assert row is not None  # every key comes from one of the two maps
        out.append(
            RowDiff(
                section=k[0],
                key=k[1],
                label=row.label,
                before=va,
                after=vb,
                derived=bool(rb and rb.provenance.derived),
                evidence=rb.provenance.evidence if rb else None,
            )
        )
    return out


_UPGRADE_LABELS: Mapping[str, str] = {
    "boost_kit_180": "Boost Kit 180 (8 Nm)",
    "load_cell_kit": "CSL Pedals Load Cell Kit",
}


def upcoming_upgrades(
    game: str,
    hardware: Hardware,
    style: str = "official_default",
    skill_level: str = "intermediate",
    strength_scale: float | None = None,
    driver_name: str | None = None,
    catalog: Catalog | None = None,
) -> list[UpgradePreview]:
    """For each hardware upgrade not fitted yet, the setting changes it will bring (section 6.2 / 6.3). The steps
    come from the recommendation after the upgrade, so their wording matches what that table really does."""
    cat = catalog or load_catalog()
    current = recommend(game, hardware, style, skill_level, strength_scale, driver_name, cat)
    out = []
    targets: list[tuple[UpgradeChange, Hardware]] = []
    if hardware.torque_nm < 8:
        targets.append(("boost_kit_180", replace(hardware, torque_nm=8)))
    if hardware.pedals == "csl":
        targets.append(("load_cell_kit", replace(hardware, pedals="csl_load_cell")))
    for change, hw in targets:
        after = recommend(game, hw, style, skill_level, strength_scale, driver_name, cat)
        notes: list[str] = []
        if change == "boost_kit_180":
            ids = {s.id for s in cat.boost_kit_steps}
            steps = tuple(s for s in after.sections[0].steps if s.id in ids)
            notes = _peak_notes(current, after, driver_name)
        else:
            steps = after.sections[3].steps
        out.append(
            UpgradePreview(
                change,
                _UPGRADE_LABELS[change],
                hw,
                tuple(diff_recommendations(current, after)),
                steps,
                peak_before_nm=current.peak_torque_nm,
                peak_after_nm=after.peak_torque_nm,
                notes=tuple(notes),
            )
        )
    return out


def _peak_notes(current: Recommendation, after: Recommendation, driver_name: str | None) -> list[str]:
    """What the Boost Kit does to this driver's peak wheel torque (arithmetic from the FF rows), so a lighter wheel
    can never get heavier without the preview saying so."""
    who = f" for {driver_name}" if driver_name else ""
    head = (
        f"Peak wheel torque{who}: about {current.peak_torque_nm:.1f} Nm now, {after.peak_torque_nm:.1f} Nm with the kit"
    )
    if after.strength_scale_source == "skill_default" and after.strength_scale != current.strength_scale:
        return [
            f"{head}. The {after.skill_level} default force goes from {current.strength_scale:.0%} to "
            f"{after.strength_scale:.0%} so the wheel keeps about the weight it has now (pitwall rule)."
        ]
    key = STRENGTH_KEY.get(after.game)
    lowered = next(
        (
            d
            for d in diff_recommendations(current, after)
            if d.key == key and (b := _num(d.before)) is not None and (a := _num(d.after)) is not None and a < b
        ),
        None,
    )
    if lowered is not None:
        head += f"; {lowered.label} drops from {lowered.before} to {lowered.after} to keep about the same weight"
    notes = [f"{head}."]
    notes.extend(s.text for s in after.safety if s.id == "boost_kit_driver_force")
    return notes


__all__ = [
    "HARDWARE_CHANGES",
    "SKILL_LEVELS",
    "STRENGTH_KEY",
    "UPGRADE_CHANGES",
    "Citation",
    "DriverRigPrefs",
    "Hardware",
    "PresetInfo",
    "PresetRef",
    "Provenance",
    "Recommendation",
    "RecommendationUnavailable",
    "ReportRef",
    "RigProfile",
    "RigValidationError",
    "RowDiff",
    "Section",
    "SettingRow",
    "SkillLevel",
    "Step",
    "UpgradeChange",
    "UpgradeEvent",
    "UpgradePreview",
    "diff_recommendations",
    "effective_strength_scale",
    "parse_driver_prefs",
    "parse_pedals",
    "parse_platform",
    "parse_rim",
    "parse_skill",
    "parse_strength_scale",
    "parse_style",
    "parse_torque",
    "parse_upgrade",
    "parse_wheel_base",
    "recommend",
    "reference_torque",
    "round_to",
    "strength_at_8nm",
    "supported",
    "table_ff",
    "tiring_tail",
    "upcoming_upgrades",
    "weight_factor",
]
