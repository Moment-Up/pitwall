"""Controls catalogue: the controls research (verbatim) plus Pitwall's overlay, validated and indexed.

Three files in ``data/`` (the rig module's pattern):

* ``research_games.json``: a byte-for-byte copy of ``docs/research/controls-games.json`` (30 function ids, 11 games,
  142 rows, sources). Never edited; a new research revision is copied in whole (a unit test keeps the copies equal).
* ``research_wheels.json``: a byte-for-byte copy of ``docs/research/controls-wheels.json`` (wheel model, 23 brand
  templates plus "custom", platform rules, sources).
* ``controls_pitwall.json``: Pitwall's normalisation, all design choices [D]: the taxonomy's shapes, frequencies and
  synonyms, per-game ``in_race`` / ``binding`` / conditions / action labels / menu groups / what Pitwall sees,
  presets, templates normalised into control lists with zones and per-platform signals, diagram geometry, reason
  and warning templates and the not-possible sentences.

The loader joins the three and fails on the first problem with its JSON path: every overlay (game, function) has a
research row and every research row an overlay entry; every source key resolves; no preset holds a function the game
does not allow mid-race; every template exists in the research, every control's kind, zone and slots are valid.

Evidence: research ``official`` -> V, ``official+community`` -> A, ``community`` -> U, ``not_found`` -> no letter.
Wheel facts keep their letters; the driver's entries are H; a signal seen by the F1 button test is ``seen``. An
assignment's evidence is the weakest of the game row and the wheel signal (``weakest``, built on the rig catalogue's
ranking). The words shown are "Official", "Inferred", "Community", "Pitwall's suggestion", "Your entry" and
"Seen by Pitwall": "validated" never appears.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, cast

from pitwall.controls.model import (
    EVIDENCE,
    KIND_SLOTS,
    PLATFORMS,
    SIGNAL_PLATFORMS,
    ZONE_REACH,
    ControlsValidationError,
    WheelControl,
    WheelPart,
    parse_control,
)
from pitwall.rig.catalog import EVIDENCE_RANK as RIG_EVIDENCE_RANK
from pitwall.rig.catalog import weakest as rig_weakest

DATA_DIR = Path(str(resources.files("pitwall.controls") / "data"))
GAMES_PATH = DATA_DIR / "research_games.json"
WHEELS_PATH = DATA_DIR / "research_wheels.json"
OVERLAY_PATH = DATA_DIR / "controls_pitwall.json"

IN_RACE = ("yes", "conditional", "pause_menu", "no", "unverified")
BINDINGS = ("direct", "mfd", "game_fixed", "menu", "none")
SHAPES = ("pair", "toggle", "hold", "momentary", "cycle", "menu", "direct")
FREQS = ("often", "sometimes", "stop", "rare")
GROUPS = ("brakes", "electronics", "power", "aero", "chassis", "car", "comms", "info", "view", "other")
COMPLETENESS = ("full", "controls", "counts")
TEMPLATE_TYPES = ("rim", "wheel_bundle", "hub", "button_module", "custom")
PTT_FUNCTION = "ptt_pitwall"
MFD_FUNCTION = "mfd"
# "seen" (Pitwall observed it live) ranks above an official document; an owner's entry (H) like community.
EVIDENCE_RANK: Mapping[str, int] = {**RIG_EVIDENCE_RANK, "seen": 4, "H": 1}


class CatalogError(ValueError):
    """The controls catalogue files do not match the expected schema."""


def in_sentence(label: str) -> str:
    """A function's label inside a sentence: "Brake bias" -> "brake bias", but acronyms stay ("ABS", "DRS / active
    aero", "ERS / hybrid mode", "MFD / black box"), so the radio never says "abs"."""
    first = label.partition(" ")[0]
    if len(first) >= 2 and first.replace("-", "").isupper():
        return label
    return label[:1].lower() + label[1:]


def weakest(*labels: str | None) -> str | None:
    """The least certain of several evidence labels; ``None`` (research found nothing) is weakest of all. V/A/U/D
    are ranked by the rig catalogue's ``weakest``; "seen" and "H" are ranked by ``EVIDENCE_RANK``."""
    if any(x is None for x in labels):
        return None
    present = [cast(str, x) for x in labels]
    if not present:
        return None
    if all(x in ("V", "A", "U", "D") for x in present):
        return rig_weakest(*cast(list[Any], present))
    return min(present, key=lambda e: EVIDENCE_RANK.get(e, 0))


# ---------------------------------------------------------------------------------------------- records
@dataclass(frozen=True, slots=True)
class Source:
    key: str
    url: str
    title: str | None
    community: bool

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"url": self.url, "community": self.community}
        if self.title:
            out["title"] = self.title
        return out


@dataclass(frozen=True, slots=True)
class FunctionDef:
    id: str
    label: str
    short: str
    group: str
    shape: str
    freq: str
    synonyms: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "short": self.short,
            "group": self.group,
            "shape": self.shape,
            "freq": self.freq,
            "synonyms": list(self.synonyms),
        }


@dataclass(frozen=True, slots=True)
class KindDef:
    id: str
    label: str
    slots: tuple[str, ...]
    pairs: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "slots": list(self.slots), "pairs": [list(p) for p in self.pairs]}


@dataclass(frozen=True, slots=True)
class GameFunction:
    function: str
    in_race: str
    binding: str
    conditions: tuple[str, ...]
    actions: Mapping[str, str]
    native_name: str
    menu_group: str | None
    shares_with: tuple[str, ...]
    pitwall_sees: str | None
    evidence: str | None
    source_ids: tuple[str, ...]
    platform_note: str | None
    absent: bool = False
    not_possible: str | None = None
    text: str | None = None
    research_note: str = ""
    always_shared: bool = False  # the game has one button for both (GT7: DRS is the Overtake button)
    native_found: bool = True  # False: the research found no binding name (``native_name`` describes the setting)

    def to_dict(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "in_race": self.in_race,
            "binding": self.binding,
            "conditions": list(self.conditions),
            "actions": dict(self.actions),
            "native_name": self.native_name,
            "menu_group": self.menu_group,
            "shares_with": list(self.shares_with),
            "pitwall_sees": self.pitwall_sees,
            "evidence": self.evidence,
            "source_ids": list(self.source_ids),
            "platform_note": self.platform_note,
            "native_found": self.native_found,  # additive
        }


@dataclass(frozen=True, slots=True)
class GameMenu:
    where: str
    evidence: str | None
    groups: tuple[str, ...]
    note: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"where": self.where, "evidence": self.evidence, "groups": list(self.groups), "note": self.note}


@dataclass(frozen=True, slots=True)
class GameDef:
    id: str
    label: str
    research_name: str
    telemetry_keys: tuple[str, ...]
    platforms: tuple[str, ...]
    button_path: str
    menu: GameMenu
    research_depth: Mapping[str, str]
    functions: Mapping[str, GameFunction]  # research order
    presets: Mapping[str, tuple[str, ...]]
    mfd_on_dpad: bool
    preset_warning: str
    platform_labels: Mapping[str, str] = field(default_factory=dict)  # Forza on PS5 is Forza Horizon
    platform_notes: Mapping[str, str] = field(default_factory=dict)

    def label_on(self, platform: str | None) -> str:
        """The game's name on this platform ("Forza Horizon (PS5)")."""
        return self.platform_labels.get(platform or "", self.label)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "platform_labels": dict(self.platform_labels),  # additive
            "telemetry_keys": list(self.telemetry_keys),
            "platforms": list(self.platforms),
            "button_path": self.button_path,
            "menu": self.menu.to_dict(),
            "research_depth": dict(self.research_depth),
            "functions": [f.to_dict() for f in self.functions.values()],
            "presets": {k: list(v) for k, v in self.presets.items()},
        }


@dataclass(frozen=True, slots=True)
class TemplateDef:
    id: str
    brand: str
    name: str
    type: str
    platforms_text: Mapping[str, str]
    completeness: str
    shape: str
    signal_platforms: tuple[str, ...]
    parts: tuple[WheelPart, ...]
    controls: tuple[WheelControl, ...]
    notes: tuple[str, ...]
    source_ids: tuple[str, ...]
    system_controls: frozenset[str] = frozenset()
    only_in_games: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    display_name: str = ""  # plain words for the picker (the research ``name`` keeps its notes)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "brand": self.brand,
            "name": self.name,
            "type": self.type,
            "platforms": dict(self.platforms_text),
            "completeness": self.completeness,
            "shape": self.shape,
            # additive: the picker's words, the consoles the wheel's signals are known for, and how many of its
            # controls the research places on the wheel
            "display_name": self.display_name or self.name,
            "signal_platforms": list(self.signal_platforms),
            "controls_total": len(self.controls),
            "controls_placed": sum(1 for c in self.controls if c.zone != "unplaced"),
        }


@dataclass(frozen=True, slots=True)
class FixedByGame:
    game: str
    template: str
    controls: Mapping[str, str]  # function -> control id
    colours: Mapping[str, str]  # function -> colour word (community)
    evidence: str
    source_ids: tuple[str, ...]
    text: str


@dataclass(frozen=True, slots=True)
class GameDefault:
    """A game's own published default buttons for one wheel template (F1 25: EA's Logitech G923 list)."""

    game: str
    template: str
    platforms: tuple[str, ...]
    evidence: str
    source_ids: tuple[str, ...]
    assignments: tuple[tuple[str, str, str, str], ...]  # (function, action, control id, slot)


@dataclass(frozen=True, slots=True)
class PadDef:
    value: str
    label: str
    glyph: str
    bit: int | None  # F1 25 BUTN bit (spec 8.9), None: not in the BUTN table


@dataclass(frozen=True, slots=True)
class Catalog:
    version: str
    status: str
    functions: Mapping[str, FunctionDef]
    reserved: tuple[tuple[str, str, str], ...]  # (id, label, kind)
    kinds: Mapping[str, KindDef]
    zones: tuple[tuple[str, str, str], ...]  # (id, label, reach)
    games: Mapping[str, GameDef]
    templates: Mapping[str, TemplateDef]
    fixed_by_game: tuple[FixedByGame, ...]
    game_defaults: tuple[GameDefault, ...]
    not_possible: Mapping[str, str]
    evidence_labels: Mapping[str, str]
    sources: Mapping[str, Source]
    reasons: Mapping[str, str]
    warnings: Mapping[str, str]
    reach_weight: Mapping[str, float]
    freq_weight: Mapping[str, float]
    freq_words: Mapping[str, str]
    suitability: Mapping[str, Mapping[str, float]]
    signal_penalty: Mapping[str, float | None]
    pad: Mapping[str, Mapping[str, PadDef]]
    system_pad: Mapping[str, frozenset[str]]
    owner_topics: tuple[str, ...]
    other_game_steps: tuple[str, ...]
    diagram: Mapping[str, Any]
    research_date: str

    # -------------------------------------------------------------- lookups
    def game_for_key(self, game_key: str | None) -> GameDef | None:
        """The controls game covering a ``games.py`` game key (``f1_25_2026`` -> F1 25)."""
        if game_key is None:
            return None
        return next((g for g in self.games.values() if game_key in g.telemetry_keys), None)

    def fixed_for(self, game: str, template: str | None, function: str) -> FixedByGame | None:
        """The game's fixed control for this function on this wheel template (GT7's coloured sticks)."""
        return next(
            (
                fx
                for fx in self.fixed_by_game
                if fx.game == game and fx.template == template and function in fx.controls
            ),
            None,
        )

    def default_for(self, game: str, template: str | None, platform: str) -> GameDefault | None:
        """The game's own published default buttons for this wheel on this platform, if the research has them."""
        return next(
            (d for d in self.game_defaults if d.game == game and d.template == template and platform in d.platforms),
            None,
        )

    def label(self, function: str) -> str:
        f = self.functions.get(function)
        return f.label if f is not None else function.replace("_", " ")

    def pad_def(self, platform: str, value: str | None) -> PadDef | None:
        return None if value is None else self.pad.get(platform, {}).get(value)

    def bit_value(self, platform: str, bit: int) -> str | None:
        """The pad value whose BUTN bit is ``bit`` on this signal platform (Identify: bit -> signal)."""
        return next((p.value for p in self.pad.get(platform, {}).values() if p.bit == bit), None)

    def to_api(self) -> dict[str, Any]:
        """``ControlsCatalog`` of the API contract, plus the additive ``diagram`` geometry."""
        return {
            "version": self.version,
            "status": self.status,
            "functions": [f.to_dict() for f in self.functions.values()],
            "reserved": [{"id": i, "label": la, "kind": k} for i, la, k in self.reserved],
            "kinds": {k: v.to_dict() for k, v in self.kinds.items()},
            "zones": [{"id": i, "label": la, "reach": r} for i, la, r in self.zones],
            "games": [g.to_dict() for g in self.games.values()],
            "other_game": {"steps": list(self.other_game_steps)},
            "templates": [t.summary() for t in self.templates.values()],
            "not_possible": [{"topic": k, "text": v} for k, v in self.not_possible.items()],
            "evidence_labels": dict(self.evidence_labels),
            "sources": {k: s.to_dict() for k, s in self.sources.items()},
            "diagram": self.diagram,
        }


_TRAILING_NOTE = re.compile(r"\s*\(([^()]*)\)\s*$")


def split_name(text: str) -> tuple[str, str | None]:
    """ "Activate/Deactivate DRS/S Mode (2026 cars: ...)" -> the name, and the bracketed note for a second line."""
    m = _TRAILING_NOTE.search(text)
    if m is None or m.start() == 0:
        return text.strip(), None
    return text[: m.start()].strip(), m.group(1).strip() or None


def native_parts(row: GameFunction | None, action: str) -> tuple[str, str | None]:
    """The game's own name for one action (the big heading of a step) and its bracketed note, without the research's
    long row name ("MFD + MFD Menu Up/Down/Left/Right; panel shortcuts (...)" becomes "MFD Menu Down")."""
    if row is None or not row.native_found:
        return "", None
    full = row.native_name
    plain = row.actions.get(action) if action in row.actions else None
    head, n1 = split_name(plain or full)
    n2 = split_name(full)[1] if plain and ";" not in full else None
    notes = [n for n in (n1, n2) if n and n.lower() not in ("mfd shortcut",) and n.lower() not in head.lower()]
    note = "; ".join(dict.fromkeys(notes)) or None
    return head, (note[0].upper() + note[1:]) if note else None


# ---------------------------------------------------------------------------------------------- parsing helpers
def _obj(v: object, path: str) -> Mapping[str, Any]:
    if not isinstance(v, Mapping):
        raise CatalogError(f"{path}: expected an object")
    return v


def _list(v: object, path: str) -> list[Any]:
    if not isinstance(v, list):
        raise CatalogError(f"{path}: expected a list")
    return v


def _str(v: object, path: str, *, optional: bool = False) -> str:
    if v is None and optional:
        return ""
    if not isinstance(v, str) or (not v and not optional):
        raise CatalogError(f"{path}: expected a non-empty string")
    return v


def _strs(v: object, path: str) -> tuple[str, ...]:
    items = [] if v is None else _list(v, path)
    if not all(isinstance(x, str) for x in items):
        raise CatalogError(f"{path}: expected a list of strings")
    return tuple(items)


def _choice(v: object, options: Sequence[str], path: str) -> str:
    if v not in options:
        raise CatalogError(f"{path}: {v!r} is not one of {list(options)}")
    return cast(str, v)


# ---------------------------------------------------------------------------------------------- the loader
def parse_catalog(games_doc: object, wheels_doc: object, overlay_doc: object) -> Catalog:
    g = _obj(games_doc, "$games")
    w = _obj(wheels_doc, "$wheels")
    ov = _obj(overlay_doc, "$overlay")
    community = set(_strs(ov.get("community_sources"), "$overlay.community_sources"))

    # sources: games research (key -> url) and wheels research (key -> {title, url, kind})
    sources: dict[str, Source] = {}
    for k, v in _obj(g.get("sources"), "$games.sources").items():
        sources[k] = Source(k, _str(v, f"$games.sources.{k}"), None, k in community)
    for k, v in _obj(w.get("sources"), "$wheels.sources").items():
        sv = _obj(v, f"$wheels.sources.{k}")
        if k in sources:
            raise CatalogError(f"$wheels.sources.{k}: the key is also a games source")
        sources[k] = Source(
            k, _str(sv.get("url"), f"$wheels.sources.{k}.url"), sv.get("title"), sv.get("kind") == "community"
        )
    for k in community:
        if k not in sources:
            raise CatalogError(f"$overlay.community_sources: unknown source {k!r}")

    def check_sources(keys: Sequence[str], path: str) -> tuple[str, ...]:
        for s in keys:
            if s not in sources:
                raise CatalogError(f"{path}: unknown source {s!r}")
        return tuple(keys)

    # taxonomy
    tax_ids = [
        _str(_obj(t, f"$games.taxonomy[{i}]").get("id"), f"$games.taxonomy[{i}].id")
        for i, t in enumerate(_list(g.get("taxonomy"), "$games.taxonomy"))
    ]
    functions: dict[str, FunctionDef] = {}
    for i, f in enumerate(_list(ov.get("functions"), "$overlay.functions")):
        fd = _obj(f, f"$overlay.functions[{i}]")
        p = f"$overlay.functions[{i}]"
        fid = _str(fd.get("id"), f"{p}.id")
        functions[fid] = FunctionDef(
            fid,
            _str(fd.get("label"), f"{p}.label"),
            _str(fd.get("short"), f"{p}.short"),
            _choice(fd.get("group"), GROUPS, f"{p}.group"),
            _choice(fd.get("shape"), SHAPES, f"{p}.shape"),
            _choice(fd.get("freq"), FREQS, f"{p}.freq"),
            _strs(fd.get("synonyms"), f"{p}.synonyms"),
        )
    if sorted(tax_ids) != sorted(functions):
        raise CatalogError(
            f"$overlay.functions: research-only {sorted(set(tax_ids) - set(functions))}, "
            f"overlay-only {sorted(set(functions) - set(tax_ids))}"
        )
    reserved = tuple(
        (
            _str(r.get("id"), f"$overlay.reserved[{i}].id"),
            _str(r.get("label"), f"$overlay.reserved[{i}].label"),
            _choice(r.get("kind"), tuple(KIND_SLOTS), f"$overlay.reserved[{i}].kind"),
        )
        for i, r in enumerate(
            _obj(x, f"$overlay.reserved[{j}]") for j, x in enumerate(_list(ov.get("reserved"), "$overlay.reserved"))
        )
    )

    # wheel model
    research_kinds = _obj(_obj(w.get("model"), "$wheels.model").get("control_kinds"), "$wheels.model.control_kinds")
    kinds: dict[str, KindDef] = {}
    for k, v in _obj(ov.get("kinds"), "$overlay.kinds").items():
        p = f"$overlay.kinds.{k}"
        if k not in KIND_SLOTS:
            raise CatalogError(f"{p}: not a control kind of the model")
        if k not in research_kinds:
            raise CatalogError(f"{p}: not in the wheel research model")
        kv = _obj(v, p)
        pairs = tuple((str(a), str(b)) for a, b in (_list(x, f"{p}.pairs") for x in kv.get("pairs") or []))
        kinds[k] = KindDef(k, _str(kv.get("label"), f"{p}.label"), _strs(kv.get("slots"), f"{p}.slots"), pairs)
    if set(kinds) != set(KIND_SLOTS):
        raise CatalogError(f"$overlay.kinds: expected {sorted(KIND_SLOTS)}")
    zones = tuple(
        (
            _choice(z.get("id"), tuple(ZONE_REACH), f"$overlay.zones[{i}].id"),
            _str(z.get("label"), f"$overlay.zones[{i}].label"),
            _str(z.get("reach"), f"$overlay.zones[{i}].reach"),
        )
        for i, z in enumerate(
            _obj(x, f"$overlay.zones[{j}]") for j, x in enumerate(_list(ov.get("zones"), "$overlay.zones"))
        )
    )
    for zid, _la, reach in zones:
        if ZONE_REACH[zid] != reach:
            raise CatalogError(f"$overlay.zones.{zid}: reach {reach!r} differs from the model's {ZONE_REACH[zid]!r}")
    if {z[0] for z in zones} != set(ZONE_REACH):
        raise CatalogError("$overlay.zones: every zone of the model must be listed once")

    # not-possible sentences
    not_possible = {
        _str(_obj(x, f"$overlay.not_possible[{i}]").get("topic"), f"$overlay.not_possible[{i}].topic"): _str(
            x.get("text"), f"$overlay.not_possible[{i}].text"
        )
        for i, x in enumerate(_list(ov.get("not_possible"), "$overlay.not_possible"))
    }

    # games: research rows joined with the overlay
    evmap = {k: v for k, v in _obj(ov.get("evidence_map"), "$overlay.evidence_map").items()}
    research_games = {
        _str(_obj(gm, f"$games.games[{i}]").get("id"), f"$games.games[{i}].id"): gm
        for i, gm in enumerate(_list(g.get("games"), "$games.games"))
    }
    games: dict[str, GameDef] = {}
    for i, raw in enumerate(_list(ov.get("games"), "$overlay.games")):
        p = f"$overlay.games[{i}]"
        go = _obj(raw, p)
        gid = _str(go.get("id"), f"{p}.id")
        rg = research_games.get(gid)
        if rg is None:
            raise CatalogError(f"{p}.id: {gid!r} is not a research game")
        rows = {c["function"]: c for c in _list(rg.get("controls"), f"$games.{gid}.controls")}
        mine = _obj(go.get("functions"), f"{p}.functions")
        if set(rows) != set(mine):
            only_r, only_o = sorted(set(rows) - set(mine)), sorted(set(mine) - set(rows))
            raise CatalogError(f"{p}.functions: research-only {only_r}, overlay-only {only_o}")
        fns: dict[str, GameFunction] = {}
        for fn, r in rows.items():  # research order
            fp = f"{p}.functions.{fn}"
            if fn not in functions:
                raise CatalogError(f"{fp}: not a taxonomy function")
            spec = _obj(mine[fn], fp)
            ev_raw = r.get("evidence")
            if ev_raw not in evmap:
                raise CatalogError(f"$games.{gid}.{fn}.evidence: {ev_raw!r} is not mapped")
            np_topic = spec.get("not_possible")
            if np_topic is not None and np_topic not in not_possible:
                raise CatalogError(f"{fp}.not_possible: unknown topic {np_topic!r}")
            actions = {
                str(k): _str(v, f"{fp}.actions.{k}")
                for k, v in _obj(spec.get("actions") or {}, f"{fp}.actions").items()
            }
            shares = _strs(spec.get("shares_with"), f"{fp}.shares_with")
            for s in shares:
                if s not in rows:
                    raise CatalogError(f"{fp}.shares_with: {s!r} is not a function of {gid}")
            fns[fn] = GameFunction(
                function=fn,
                in_race=_choice(spec.get("in_race"), IN_RACE, f"{fp}.in_race"),
                binding=_choice(spec.get("binding"), BINDINGS, f"{fp}.binding"),
                conditions=_strs(spec.get("conditions"), f"{fp}.conditions"),
                actions=actions,
                native_name=_str(r.get("native_name"), f"$games.{gid}.{fn}.native_name"),
                menu_group=spec.get("menu_group"),
                shares_with=shares,
                pitwall_sees=spec.get("pitwall_sees"),
                evidence=evmap[ev_raw],
                source_ids=check_sources(
                    _strs(r.get("sources"), f"$games.{gid}.{fn}.sources"), f"$games.{gid}.{fn}.sources"
                ),
                platform_note=spec.get("platform_note"),
                absent=bool(spec.get("absent", False)),
                not_possible=np_topic,
                text=spec.get("text"),
                research_note=str(r.get("note") or ""),
                always_shared=bool(spec.get("always_shared", False)),
                native_found=bool(spec.get("native_found", True)),
            )
        presets_raw = _obj(go.get("presets"), f"{p}.presets")
        presets: dict[str, tuple[str, ...]] = {}
        for level in ("beginner", "advanced"):
            items = _strs(presets_raw.get(level), f"{p}.presets.{level}")
            for fn in items:
                row = fns.get(fn)
                if row is None:
                    raise CatalogError(f"{p}.presets.{level}: {fn!r} is not a function of {gid}")
                if row.in_race in ("no", "pause_menu") or row.binding in ("menu", "none"):
                    raise CatalogError(f"{p}.presets.{level}: {fn} is not assignable mid-race in {gid}")
            presets[level] = items
        menu = _obj(go.get("menu"), f"{p}.menu")
        menu_ev = menu.get("evidence")
        if menu_ev is not None:
            _choice(menu_ev, EVIDENCE, f"{p}.menu.evidence")
        platforms = tuple(_choice(x, PLATFORMS, f"{p}.platforms") for x in _strs(go.get("platforms"), f"{p}.platforms"))
        groups = _strs(menu.get("groups"), f"{p}.menu.groups")
        for fn, row in fns.items():
            if row.menu_group is not None and groups and row.menu_group not in groups:
                raise CatalogError(f"{p}.functions.{fn}.menu_group: {row.menu_group!r} is not one of {list(groups)}")
        games[gid] = GameDef(
            id=gid,
            label=_str(go.get("label"), f"{p}.label"),
            research_name=_str(rg.get("name"), f"$games.{gid}.name"),
            telemetry_keys=_strs(go.get("telemetry_keys"), f"{p}.telemetry_keys"),
            platforms=platforms,
            button_path=_choice(go.get("button_path"), ("f1_butn", "none"), f"{p}.button_path"),
            menu=GameMenu(_str(menu.get("where"), f"{p}.menu.where"), menu_ev, groups, menu.get("note")),
            research_depth={str(k): str(v) for k, v in _obj(rg.get("research_depth") or {}, f"$games.{gid}").items()},
            functions=fns,
            presets=presets,
            mfd_on_dpad=bool(go.get("mfd_on_dpad")),
            preset_warning=_str(go.get("preset_warning"), f"{p}.preset_warning"),
            platform_labels={
                str(k): str(v)
                for k, v in _obj(go.get("platform_labels") or {}, f"{p}.platform_labels").items()
                if _choice(k, PLATFORMS, f"{p}.platform_labels")
            },
            platform_notes={
                str(k): str(v)
                for k, v in _obj(go.get("platform_notes") or {}, f"{p}.platform_notes").items()
                if _choice(k, PLATFORMS, f"{p}.platform_notes")
            },
        )
    if set(games) != set(research_games):
        raise CatalogError(f"$overlay.games: expected every research game {sorted(research_games)}")

    # templates
    research_tmpl = {
        _str(_obj(t, f"$wheels.templates[{i}]").get("id"), f"$wheels.templates[{i}].id"): t
        for i, t in enumerate(_list(w.get("templates"), "$wheels.templates"))
    }
    templates: dict[str, TemplateDef] = {}
    for i, raw in enumerate(_list(ov.get("templates"), "$overlay.templates")):
        p = f"$overlay.templates[{i}]"
        to = _obj(raw, p)
        tid = _str(to.get("id"), f"{p}.id")
        rt = research_tmpl.get(tid)
        if rt is None:
            raise CatalogError(f"{p}.id: {tid!r} is not a research template")
        parts = tuple(
            WheelPart(
                _str(pt.get("id"), f"{p}.parts[{j}].id"),
                _str(pt.get("kind"), f"{p}.parts[{j}].kind"),
                _str(pt.get("name"), f"{p}.parts[{j}].name"),
            )
            for j, pt in enumerate(
                _obj(x, f"{p}.parts[{k}]") for k, x in enumerate(_list(to.get("parts"), f"{p}.parts"))
            )
        )
        controls: list[WheelControl] = []
        for j, c in enumerate(_list(to.get("controls"), f"{p}.controls")):
            try:
                ctl = parse_control(c, f"{p}.controls[{j}]", [x.id for x in parts], default_evidence="A")
            except ControlsValidationError as e:
                raise CatalogError(str(e)) from e
            for plat, sig in ctl.signals.items():
                check_sources(sig.source_ids, f"{p}.controls[{j}].signals.{plat}.source_ids")
            controls.append(ctl)
        ids = [c.id for c in controls]
        if len(set(ids)) != len(ids):
            raise CatalogError(f"{p}.controls: duplicate control ids")
        sig_plats = tuple(
            _choice(x, SIGNAL_PLATFORMS, f"{p}.platforms") for x in _strs(to.get("platforms"), f"{p}.platforms")
        )
        system = frozenset(_strs(to.get("system_controls"), f"{p}.system_controls"))
        only = {str(k): _strs(v, f"{p}.only_in_games.{k}") for k, v in _obj(to.get("only_in_games") or {}, p).items()}
        for cid in (*system, *only):
            if cid not in ids:
                raise CatalogError(f"{p}: {cid!r} is not a control of {tid}")
        for cid, gl in only.items():
            for gname in gl:
                if gname not in games:
                    raise CatalogError(f"{p}.only_in_games.{cid}: unknown game {gname!r}")
        templates[tid] = TemplateDef(
            id=tid,
            brand=_str(rt.get("brand"), f"$wheels.{tid}.brand"),
            name=_str(rt.get("name"), f"$wheels.{tid}.name"),
            type=_choice(rt.get("type"), TEMPLATE_TYPES, f"$wheels.{tid}.type"),
            platforms_text={
                str(k): str(v) for k, v in _obj(rt.get("platforms") or {}, f"$wheels.{tid}.platforms").items()
            },
            completeness=_choice(to.get("completeness"), COMPLETENESS, f"{p}.completeness"),
            shape=_choice(to.get("shape"), ("round", "d", "formula", "box"), f"{p}.shape"),
            signal_platforms=sig_plats,
            parts=parts,
            controls=tuple(controls),
            notes=_strs(to.get("notes"), f"{p}.notes"),
            source_ids=check_sources(_strs(rt.get("sources"), f"$wheels.{tid}.sources"), f"$wheels.{tid}.sources"),
            system_controls=system,
            only_in_games=only,
            display_name=_str(to.get("display_name"), f"{p}.display_name", optional=True),
        )
    if list(templates) != list(research_tmpl):
        raise CatalogError("$overlay.templates: expected every research template, in research order")

    fixed: list[FixedByGame] = []
    for i, raw in enumerate(_list(ov.get("fixed_by_game"), "$overlay.fixed_by_game")):
        p = f"$overlay.fixed_by_game[{i}]"
        fx = _obj(raw, p)
        game = _str(fx.get("game"), f"{p}.game")
        tid = _str(fx.get("template"), f"{p}.template")
        if game not in games or tid not in templates:
            raise CatalogError(f"{p}: unknown game or template")
        ctrl_map = {str(k): str(v) for k, v in _obj(fx.get("controls"), f"{p}.controls").items()}
        tids = {c.id for c in templates[tid].controls}
        for fn, cid in ctrl_map.items():
            if fn not in games[game].functions or cid not in tids:
                raise CatalogError(f"{p}.controls.{fn}: unknown function or control")
        fixed.append(
            FixedByGame(
                game,
                tid,
                ctrl_map,
                {str(k): str(v) for k, v in _obj(fx.get("functions"), f"{p}.functions").items()},
                _choice(fx.get("evidence"), EVIDENCE, f"{p}.evidence"),
                check_sources(_strs(fx.get("sources"), f"{p}.sources"), f"{p}.sources"),
                _str(fx.get("text"), f"{p}.text"),
            )
        )

    defaults: list[GameDefault] = []
    for i, raw in enumerate(_list(ov.get("game_defaults") or [], "$overlay.game_defaults")):
        p = f"$overlay.game_defaults[{i}]"
        gd = _obj(raw, p)
        game = _str(gd.get("game"), f"{p}.game")
        tid = _str(gd.get("template"), f"{p}.template")
        if game not in games or tid not in templates:
            raise CatalogError(f"{p}: unknown game or template")
        tctl = {c.id: c for c in templates[tid].controls}
        asg: list[tuple[str, str, str, str]] = []
        for j, a in enumerate(_list(gd.get("assignments"), f"{p}.assignments")):
            ad = _obj(a, f"{p}.assignments[{j}]")
            fn, act = _str(ad.get("function"), f"{p}.assignments[{j}].function"), _str(ad.get("action"), f"{p}")
            cid, slot = _str(ad.get("control"), f"{p}.assignments[{j}].control"), _str(ad.get("slot"), f"{p}")
            row = games[game].functions.get(fn)
            if row is None or act not in row.actions:
                raise CatalogError(f"{p}.assignments[{j}]: {fn}.{act} is not an action of {game}")
            if cid not in tctl or slot not in tctl[cid].slots():
                raise CatalogError(f"{p}.assignments[{j}]: {cid}:{slot} is not a slot of {tid}")
            asg.append((fn, act, cid, slot))
        defaults.append(
            GameDefault(
                game,
                tid,
                tuple(_choice(x, PLATFORMS, f"{p}.platforms") for x in _strs(gd.get("platforms"), f"{p}.platforms")),
                _choice(gd.get("evidence"), EVIDENCE, f"{p}.evidence"),
                check_sources(_strs(gd.get("sources"), f"{p}.sources"), f"{p}.sources"),
                tuple(asg),
            )
        )

    pad: dict[str, dict[str, PadDef]] = {}
    for plat, table in _obj(ov.get("pad"), "$overlay.pad").items():
        _choice(plat, ("ps", "xbox"), "$overlay.pad")
        pad[plat] = {}
        for value, row in _obj(table, f"$overlay.pad.{plat}").items():
            label, glyph, bit = _list(row, f"$overlay.pad.{plat}.{value}")
            if bit is not None and (not isinstance(bit, int) or bit <= 0 or bit & (bit - 1)):
                raise CatalogError(f"$overlay.pad.{plat}.{value}: the BUTN bit must be one bit")
            pad[plat][str(value)] = PadDef(str(value), str(label), str(glyph), bit)
    system_pad = {
        k: frozenset(_strs(v, f"$overlay.system_pad.{k}")) for k, v in _obj(ov.get("system_pad"), "$overlay").items()
    }
    evidence_labels = {str(k): str(v) for k, v in _obj(ov.get("evidence_labels"), "$overlay.evidence_labels").items()}
    if set(evidence_labels) != set(EVIDENCE) or any("validat" in v.lower() for v in evidence_labels.values()):
        raise CatalogError("$overlay.evidence_labels: one word per evidence letter, and never 'validated'")
    diagram = _obj(ov.get("diagram"), "$overlay.diagram")
    for shape, sd in _obj(diagram.get("shapes"), "$overlay.diagram.shapes").items():
        zb = _obj(_obj(sd, f"$overlay.diagram.shapes.{shape}").get("zones"), f"$overlay.diagram.shapes.{shape}.zones")
        if set(zb) != set(ZONE_REACH):
            raise CatalogError(f"$overlay.diagram.shapes.{shape}.zones: every zone needs a box")
    owner_topics = _strs(ov.get("owner_topics"), "$overlay.owner_topics")
    for t in owner_topics:
        if t not in functions:
            raise CatalogError(f"$overlay.owner_topics: {t!r} is not a function")

    return Catalog(
        version=_str(ov.get("version"), "$overlay.version"),
        status=_str(ov.get("status"), "$overlay.status"),
        functions=functions,
        reserved=reserved,
        kinds=kinds,
        zones=zones,
        games=games,
        templates=templates,
        fixed_by_game=tuple(fixed),
        game_defaults=tuple(defaults),
        not_possible=not_possible,
        evidence_labels=evidence_labels,
        sources=sources,
        reasons={str(k): str(v) for k, v in _obj(ov.get("reasons"), "$overlay.reasons").items()},
        warnings={str(k): str(v) for k, v in _obj(ov.get("warnings"), "$overlay.warnings").items()},
        reach_weight={str(k): float(v) for k, v in _obj(ov.get("reach_weight"), "$overlay.reach_weight").items()},
        freq_weight={str(k): float(v) for k, v in _obj(ov.get("freq_weight"), "$overlay.freq_weight").items()},
        freq_words={str(k): str(v) for k, v in _obj(ov.get("freq_words"), "$overlay.freq_words").items()},
        suitability={
            str(k): {str(a): float(b) for a, b in _obj(v, f"$overlay.suitability.{k}").items()}
            for k, v in _obj(ov.get("suitability"), "$overlay.suitability").items()
        },
        signal_penalty={
            str(k): (None if v is None else float(v))
            for k, v in _obj(ov.get("signal_penalty"), "$overlay.signal_penalty").items()
        },
        pad=pad,
        system_pad=system_pad,
        owner_topics=owner_topics,
        other_game_steps=_strs(
            _obj(ov.get("other_game"), "$overlay.other_game").get("steps"), "$overlay.other_game.steps"
        ),
        diagram=diagram,
        research_date=_str(g.get("generated_on"), "$games.generated_on"),
    )


def load_catalog_files(games_path: Path, wheels_path: Path, overlay_path: Path) -> Catalog:
    docs = []
    for path in (games_path, wheels_path, overlay_path):
        try:
            docs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            raise CatalogError(f"cannot read {path}: {e}") from e
    return parse_catalog(docs[0], docs[1], docs[2])


@cache
def load_catalog() -> Catalog:
    """The packaged catalogue, parsed and validated once per process."""
    return load_catalog_files(GAMES_PATH, WHEELS_PATH, OVERLAY_PATH)
