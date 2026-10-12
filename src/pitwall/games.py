"""What are you playing? The game catalogue and what each game's telemetry can and cannot give Pitwall.

The household tells Pitwall which game (and platform) it plays, so setup flows, the dashboard and the race engineer
can say "GT7 doesn't send tyre wear" instead of showing an empty tile that looks like data that has not arrived yet.
Two different facts must never be confused:

* **a capability of the game** ("not sent", known in advance, from this module), and
* **runtime state** ("not arrived yet / unknown right now", from the live snapshot).

Design decisions:

* **Derived, never stronger than the evidence (D1, D2).** One entry per ``capabilities.PLANNED`` row x platform,
  plus ``other:any``; labels are display data, every support claim comes from the row and from the adapter's
  ``AdapterInfo``. An entry's level is the weaker of the row's status and the adapter's level for that platform; a
  feature's evidence is the weakest of the entry level and every field it needs. A field the adapter does not
  declare is ``unknown``, never "not sent"; an unverified entry or field makes the feature ``unknown``.
* **A few code facts** (corner sheets, outlines, car-setup catalogue, the NOT_IMPLEMENTED / PARTIAL tables) restate
  what the code does; each is pinned by a unit test to the code it describes (``tests/unit/test_games.py``).
* **Pure and cached.** No I/O except reading packaged data once (track sheets, rig catalogue); ``resolve`` is
  memoised on plain strings because the live snapshot calls it (web thread, never the ingest thread).
* **Two roles (D5).** The *selected* entry (``SettingsStore`` section ``"game"``) drives setup; the *effective* entry
  (the live session's detected game, else the selection) drives what screens and the engineer say about data.
* **The backend writes every sentence** (``short``, ``reason``, mismatch and suggestion texts); the dashboard never
  composes reasons.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pitwall.adapters.base import AdapterInfo, FieldSupport, SupportLevel
from pitwall.capabilities import ADAPTER_INFOS, PLANNED, CapabilityRow
from pitwall.compat import this_machine
from pitwall.model.telemetry import Game

if TYPE_CHECKING:
    from pitwall.ai.facts import FactSheet
    from pitwall.config import Settings
    from pitwall.integrations import IntegrationConfig
    from pitwall.settings_store import SettingsStore

log = logging.getLogger(__name__)

S = SupportLevel
SCHEMA = 1
SECTION = "game"  # SettingsStore section: {"selected": id, "since_unix": float, "source": "dashboard" | "cli" | ...}
SOURCES = ("dashboard", "cli", "driver_default")
BUSY_S = 10.0  # an input that received a packet this recently is "in use": never modified under the driver
PAUSED_S = 600.0  # stale data this young is a pause (game menu, replay screen): another game's mismatch stays shown

FeatureStatus = Literal["supported", "partial", "not_sent", "not_implemented", "unknown"]
AVAILABLE: frozenset[str] = frozenset({"supported", "partial"})
UNAVAILABLE: frozenset[str] = frozenset({"not_sent", "not_implemented"})

# ---------------------------------------------------------------------------------------------- evidence order
LEVEL_ORDER: tuple[SupportLevel, ...] = (
    S.LIVE_VALIDATED,
    S.RECORDED_VALIDATED,
    S.SPEC_IMPLEMENTED,
    S.COMMUNITY_DOCUMENTED,
    S.PARTIAL,
    S.UNVERIFIED,
    S.UNSUPPORTED,
)
_RANK: dict[SupportLevel, int] = {lvl: i for i, lvl in enumerate(LEVEL_ORDER)}


def weakest(first: SupportLevel, *levels: SupportLevel) -> SupportLevel:
    """The weakest evidence of the given levels (the one latest in ``LEVEL_ORDER``)."""
    return max((first, *levels), key=_RANK.__getitem__)


def stronger(a: SupportLevel, b: SupportLevel) -> bool:
    """``a`` is stronger evidence than ``b``."""
    return _RANK[a] < _RANK[b]


# README "Status words" (README.md: Supported games)
SUPPORT_WORDS: dict[SupportLevel, str] = {
    S.LIVE_VALIDATED: "Tested live",
    S.RECORDED_VALIDATED: "Tested on a recording",
    S.SPEC_IMPLEMENTED: "Built from the official spec",
    S.COMMUNITY_DOCUMENTED: "Built from community docs",
    S.PARTIAL: "Partial",
    S.UNVERIFIED: "Unverified",
    S.UNSUPPORTED: "Not supported",
}
WORDS_PARTIAL_NOT_IMPLEMENTED = "Not in Pitwall yet"  # researched (partial), no reader
WORDS_RECORD_ONLY = "Records packets only"
OTHER_NOTE = "Raw packets are saved so a decoder can be written later. No analysis."
# One plain sentence per level for a game Pitwall reads (README "Status words"); ``support.note`` keeps the details.
SUPPORT_SUMMARY: dict[SupportLevel, str] = {
    S.LIVE_VALIDATED: "Checked end to end with the real game on this platform.",
    S.RECORDED_VALIDATED: "Checked against real game output recorded on this platform; not yet run end to end.",
    S.SPEC_IMPLEMENTED: "Built from the game's official telemetry spec and tested with generated data; not yet "
    "checked with the real game on this platform.",
    S.COMMUNITY_DOCUMENTED: "Built from community documentation and tested with generated data; not yet checked with "
    "the real game on this platform.",
    S.PARTIAL: "Only partly researched, and Pitwall has no reader for it yet.",
    S.UNVERIFIED: "Nobody has confirmed that this version sends telemetry.",
    S.UNSUPPORTED: "Pitwall can't read this game's telemetry.",
}
OTHER_SUMMARY = (
    "Pitwall doesn't know what this game sends. It can record its packets so a decoder can be written later."
)

PLATFORM_WORDS = {"ps5": "PS5", "ps4": "PS4", "xbox": "Xbox", "pc": "PC"}


# ---------------------------------------------------------------------------------------------- display data
@dataclass(frozen=True, slots=True)
class _GameText:
    label: str  # "Gran Turismo 7"
    short_label: str  # chips: "GT7"
    text_name: str  # sentences: "GT7"
    integration: str | None  # integrations.SPECS key (None: Pitwall cannot read this game)
    guide_id: str | None  # connect.GameGuide.id


_GAMES: dict[str, _GameText] = {
    "f1_25": _GameText("F1 25", "F1 25", "F1 25", "f1", "f1_25"),
    "f1_25_2026": _GameText("F1 25 (2026 Season Pack)", "F1 25", "F1 25", "f1", "f1_25"),
    "f1_24": _GameText("F1 24 or older", "F1 24", "F1 24", None, None),
    "gt7": _GameText("Gran Turismo 7", "GT7", "GT7", "gt7", "gt7"),
    "forza_motorsport": _GameText("Forza Motorsport (2023)", "Forza M", "Forza Motorsport", "forza", "forza"),
    "forza_horizon": _GameText("Forza Horizon 4 / 5", "Forza H", "Forza Horizon", "forza", "forza"),
    "ac": _GameText("Assetto Corsa", "AC", "Assetto Corsa", "ac", "ac"),
    "acc": _GameText("Assetto Corsa Competizione", "ACC", "ACC", None, None),
    "iracing": _GameText("iRacing", "iRacing", "iRacing", None, None),
    "other": _GameText("Another game", "Other", "this game", "record", "record"),
}

# Catalogue order (picker and resolve preference): (game_key, platform, capability row key, group, platform_label).
_ENTRY_TABLE: tuple[tuple[str, str, str | None, str, str], ...] = (
    ("f1_25", "ps5", "f1_25_2025_ps5", "main", "PS5"),
    ("f1_25", "xbox", "f1_25_2025_pc_xbox", "main", "Xbox Series"),
    ("f1_25", "pc", "f1_25_2025_pc_xbox", "main", "PC"),
    ("f1_25_2026", "ps5", "f1_25_2026", "more", "PS5"),
    ("f1_25_2026", "xbox", "f1_25_2026", "more", "Xbox Series"),
    ("f1_25_2026", "pc", "f1_25_2026", "more", "PC"),
    ("f1_24", "any", "f1_24", "more", "any"),
    ("gt7", "ps5", "gt7_ps5", "main", "PS5"),
    ("gt7", "ps4", "gt7_ps4", "main", "PS4"),
    ("forza_motorsport", "xbox", "forza_motorsport", "main", "Xbox Series"),
    ("forza_motorsport", "pc", "forza_motorsport", "main", "PC"),
    ("forza_horizon", "xbox", "forza_horizon", "main", "Xbox"),
    ("forza_horizon", "pc", "forza_horizon", "main", "PC"),
    ("forza_horizon", "ps5", "forza_horizon", "more", "PS5"),
    ("ac", "ps5", "ac_ps5", "main", "PS5 (PS4 version)"),
    ("ac", "ps4", "ac_ps4", "main", "PS4"),
    ("ac", "pc", "ac_pc", "main", "PC"),
    ("ac", "xbox", "ac_xbox", "more", "Xbox One"),
    ("acc", "pc", "acc_pc", "more", "PC"),
    ("acc", "ps5", "acc_console", "more", "PS5"),
    ("acc", "xbox", "acc_console", "more", "Xbox Series"),
    ("iracing", "pc", "iracing_pc", "more", "PC"),
    ("other", "any", None, "main", "any"),
)


# ---------------------------------------------------------------------------------------------- features
@dataclass(frozen=True, slots=True)
class FeatureDef:
    id: str
    label: str
    group: str
    noun: str  # for sentences: "{text_name} doesn't send {noun}."
    required: tuple[str, ...] = ()  # AdapterInfo.fields keys
    optional: tuple[str, ...] = ()  # counted only when the adapter declares them
    ground_plane: bool = False  # needs the two AdapterInfo.ground_plane fields too
    code_fact: bool = False  # decided by what Pitwall ships, not by a telemetry field


FEATURES: tuple[FeatureDef, ...] = (
    FeatureDef(
        "lap_timing",
        "Lap times",
        "timing",
        "lap times",
        ("lap_number", "current_lap_time_ms"),
        ("last_lap_time_ms", "lap_completion"),
    ),
    FeatureDef("sectors", "Sector times", "timing", "sector times", ("sector",)),
    FeatureDef("delta", "Live delta", "timing", "a live delta", ("lap_distance_m", "current_lap_time_ms")),
    FeatureDef("braking_cues", "Braking cues", "coaching", "braking cues", ("brake", "speed_kph", "lap_distance_m")),
    FeatureDef(
        "corner_coaching",
        "Corner coaching",
        "coaching",
        "corner coaching",
        ("brake", "throttle", "speed_kph", "lap_distance_m"),
    ),
    FeatureDef("track_map", "Track map", "track", "a track map", ("lap_distance_m",), ground_plane=True),
    FeatureDef("official_corner_names", "Official corner names", "track", "official corner names", code_fact=True),
    FeatureDef("ai_field", "AI field braking model", "track", "the AI field's braking points", ("field_samples",)),
    FeatureDef("flags", "Flags & marshal zones", "track", "flags", ("track_zones",)),
    FeatureDef("fuel", "Fuel", "car", "fuel", ("fuel_kg",)),
    FeatureDef("tyre_temps", "Tyre temperatures", "car", "tyre temperatures", ("tyre_surface_temp_c",)),
    FeatureDef("tyre_wear", "Tyre wear", "car", "tyre wear", ("tyre_wear_pct",)),
    FeatureDef("tyre_pressures", "Tyre pressures", "car", "tyre pressures", ("tyre_pressure_psi",)),
    FeatureDef("brake_temps", "Brake temperatures", "car", "brake temperatures", ("brake_temp_c",)),
    FeatureDef("damage", "Car damage", "car", "damage", ("damage",)),
    FeatureDef("ers", "ERS / hybrid", "car", "ERS", ("ers_store_j",)),
    FeatureDef("drs", "DRS", "car", "DRS", ("drs_open",)),
    FeatureDef("weather", "Weather", "session", "weather", ("weather",)),
    FeatureDef("session_info", "Session type & results", "session", "the session type", ("session_type",)),
    FeatureDef("field_data", "Other cars' data", "session", "data about the other cars", ("field_samples",)),
    # --- spotter ---
    FeatureDef("spotter", "Spotter (cars alongside)", "session", "every car's position and heading", ("field_motion",)),
    FeatureDef("setup_telemetry", "Car setup from the game", "setup_radio", "its car setup", ("setup",)),
    FeatureDef(
        "setup_recommendations",
        "Car setup recommendations",
        "setup_radio",
        "car setup recommendations",
        code_fact=True,
    ),
    FeatureDef("wheel_ptt", "Push-to-talk on a wheel button", "setup_radio", "wheel button presses", ("buttons",)),
)
FEATURE_IDS: tuple[str, ...] = tuple(f.id for f in FEATURES)
_FEATURE_BY_ID: dict[str, FeatureDef] = {f.id: f for f in FEATURES}

GROUPS: tuple[tuple[str, str], ...] = (
    ("timing", "Timing"),
    ("coaching", "Coaching"),
    ("track", "Track"),
    ("car", "Car & tyres"),
    ("session", "Session & race"),
    ("setup_radio", "Setup & radio"),
)

# Features computed from the lap distance: partial distance makes them estimates.
DISTANCE_FEATURES = frozenset({"delta", "braking_cues", "corner_coaching", "track_map"})

# ---------------------------------------------------------------------------------------------- code facts
# Each entry restates the code; tests/unit/test_games.py pins it to the code it describes.
ESTIMATED: frozenset[tuple[str, str]] = frozenset({("gt7", "lap_distance_m")})  # GT7: integrated from the velocity
DISTANCE_REASON: dict[str, str] = {
    "gt7": "GT7 sends no lap distance: Pitwall works it out from the car's speed and direction (within about 0.2 % "
    "per lap on real PS5 laps).",
    "forza_motorsport": "Forza sends no lap distance: Pitwall measures the distance you drive from the start line.",
    "forza_horizon": "Forza sends no lap distance: Pitwall measures the distance you drive from the start line.",
    "ac": "Assetto Corsa sends no lap distance: Pitwall works it out from the track position once the track length "
    "is known (your first full lap measures it).",
}
_FORZA_FUEL = "Forza sends only how full the tank is, not its size, so Pitwall doesn't show fuel yet."
NOT_IMPLEMENTED: dict[tuple[str, str], str] = {
    ("f1_25", "damage"): "F1 25 sends car damage, but Pitwall reads only tyre wear from it so far.",
    ("gt7", "fuel"): "GT7 sends a fuel level, but sources disagree on its unit (litres or per cent), so Pitwall "
    "doesn't show fuel yet.",
    ("forza_motorsport", "fuel"): _FORZA_FUEL,
    ("forza_horizon", "fuel"): _FORZA_FUEL,
    ("gt7", "ers"): "GT7 may send an energy-recovery value of unknown units; Pitwall doesn't read it.",
    ("gt7", "setup_telemetry"): "GT7 sends only its gear ratios, not the rest of its car setup, and Pitwall doesn't "
    "read them as a setup.",
}
NOT_IMPLEMENTED_FIELD: dict[tuple[str, str], str] = {  # (adapter_game, feature) -> the field whose source is the detail
    ("gt7", "fuel"): "fuel_litres",
    ("forza_motorsport", "fuel"): "fuel_kg",
    ("forza_horizon", "fuel"): "fuel_kg",
    ("gt7", "ers"): "ers_store_j",
    ("gt7", "setup_telemetry"): "setup",
}
F1_DAMAGE_DETAIL = "CarDamage (adapters/f1/packets.py) is decoded; only tyresWear is mapped (adapters/f1/adapter.py)"
PARTIAL_FACTS: dict[tuple[str, str], str] = {
    ("f1_25", "session_info"): "The session type comes from the game; the final classification isn't read yet.",
    ("forza_horizon", "lap_timing"): "Free roam and sprints have no laps; circuit races are timed.",
}
PARTIAL_REASON: dict[str, str] = {  # a partial field behind a feature (not distance, not a PARTIAL_FACTS entry)
    "lap_timing": "{name} sends lap times, but Pitwall works out where each lap ends, so a lap can stay untimed.",
}
# Data the game has, but only through a local interface Pitwall does not read: (capability row key) -> feature id ->
# the noun to say (None: the feature's own). Assetto Corsa on PC exposes these in its Windows shared memory
# (docs/research/forza-ac-acc-iracing.md section 2.1, matrix row "AC, PC, shared memory"); Pitwall reads the UDP
# remote telemetry, which has none of them. Consoles have no shared memory, so there they stay "not sent".
LOCAL_ONLY: dict[str, dict[str, str | None]] = {
    "ac_pc": {
        "sectors": None,
        "flags": None,
        "fuel": None,
        "tyre_temps": None,
        "tyre_wear": None,
        "tyre_pressures": None,
        "brake_temps": None,
        "damage": None,
        "ers": None,
        "drs": None,
        "weather": "air and track temperatures",
        "session_info": None,
    },
}
LOCAL_ONLY_INTERFACE: dict[str, str] = {
    "ac_pc": "shared memory (docs/research/forza-ac-acc-iracing.md section 2.1)",
}


def local_only_reason(e: GameEntry, nouns: Sequence[str]) -> str:
    """For example: "Assetto Corsa on PC has fuel and tyre wear only in its shared memory, which Pitwall can't read
    yet (it uses the UDP remote telemetry)."."""
    return (
        f"{e.text_name} on {e.platform_label} has {_join(list(nouns)).replace(' or ', ' and ')} only in its shared "
        "memory, which Pitwall can't read yet (it uses the UDP remote telemetry)."
    )


def _local_only_noun(e: GameEntry, feature_id: str) -> str | None:
    """The noun when ``feature_id`` is local-only data of ``e`` (see ``LOCAL_ONLY``), else None."""
    table = LOCAL_ONLY.get(e.row.key) if e.row is not None else None
    if table is None or feature_id not in table:
        return None
    return table[feature_id] or _FEATURE_BY_ID[feature_id].noun


@functools.cache
def official_name_sheets(adapter_game: str, variant: str | None = None) -> tuple[int, int]:
    """(sheets with a hand-checked turn, shipped sheets) for a game and F1 UDP format: ``analysis.track_identity``
    shows only verified turns by default, and a sheet verified against other wire formats counts as unchecked in a
    session of this format (its ``verified_formats``)."""
    from pitwall import trackdata
    from pitwall.analysis.track_identity import SheetError, load_sheets

    fmt = int(variant) if variant is not None and variant.isdigit() else None
    verified = total = 0
    for family in trackdata.sheet_families():
        try:
            sheets = load_sheets(family)
        except SheetError:  # a packaging bug: the test-suite checks the shipped sheets
            log.exception("track sheets for %r are unreadable", family)
            continue
        for sheet in sheets:
            if adapter_game not in sheet.games:
                continue
            total += 1
            format_ok = not sheet.verified_formats or fmt is None or fmt in sheet.verified_formats
            if format_ok and any(t.verified for t in sheet.turns):
                verified += 1
    return verified, total


def official_name_games() -> frozenset[str]:
    """Game values with at least one hand-checked track sheet (official corner names shown somewhere)."""
    return frozenset(
        e.adapter_game
        for e in entries()
        if e.adapter_game is not None and official_name_sheets(e.adapter_game, e.variant)[0] > 0
    )


@functools.cache
def outline_games() -> frozenset[str]:
    """Games with a shipped circuit outline before the first lap (``analysis.track_geometry.OUTLINE_GAMES``)."""
    from pitwall.analysis.track_geometry import OUTLINE_GAMES

    return frozenset(OUTLINE_GAMES)


@functools.cache
def setup_games() -> frozenset[str]:
    """Games with car setup recommendations (``carsetup.context.F1_GAMES``)."""
    from pitwall.carsetup.context import F1_GAMES

    return frozenset(F1_GAMES)


@functools.cache
def rig_supported() -> frozenset[tuple[str, str]]:
    """(game, platform) pairs the rig walkthrough covers (``rig.catalog``); empty if the catalogue is broken."""
    try:
        from pitwall.rig.catalog import load_catalog

        return frozenset(load_catalog().supported)
    except Exception:  # never let the rig data break game selection
        log.exception("rig catalogue unavailable")
        return frozenset()


# ---------------------------------------------------------------------------------------------- entries
@dataclass(frozen=True, slots=True)
class GameFeature:
    id: str
    label: str
    group: str
    status: FeatureStatus
    evidence: SupportLevel | None  # supported / partial telemetry features only; never stronger than the entry
    short: str
    reason: str
    detail: str
    note: str | None
    fields: tuple[str, ...]

    @property
    def available(self) -> bool:
        return self.status in AVAILABLE

    @property
    def noun(self) -> str:
        return _FEATURE_BY_ID[self.id].noun

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "group": self.group,
            "status": self.status,
            "evidence": None if self.evidence is None else self.evidence.value,
            "short": self.short,
            "reason": self.reason,
            "detail": self.detail,
            "note": self.note,
            "fields": list(self.fields),
        }


@dataclass(frozen=True, slots=True)
class GameEntry:
    id: str
    game_key: str
    label: str
    short_label: str
    text_name: str
    platform: str
    platform_label: str
    group: str
    row: CapabilityRow | None  # None: other:any
    integration: str | None
    guide_id: str | None

    @property
    def adapter_game(self) -> str | None:
        r = self.row
        return None if r is None or r.adapter_game is None else r.adapter_game.value

    @property
    def variant(self) -> str | None:
        return None if self.row is None else self.row.variant

    @property
    def implemented(self) -> bool:
        return self.row is not None and self.row.implemented

    @property
    def info(self) -> AdapterInfo | None:
        r = self.row
        return None if r is None or r.adapter_game is None else ADAPTER_INFOS.get(r.adapter_game)

    @property
    def level(self) -> SupportLevel | None:
        """Never stronger than the row, nor than the adapter's level for this platform (D2)."""
        r = self.row
        if r is None:
            return None
        info = self.info
        if r.status is S.UNSUPPORTED or info is None:
            return r.status
        return weakest(r.status, _adapter_platform_level(info, self.platform))

    @property
    def support_words(self) -> str:
        lvl = self.level
        if lvl is None:
            return WORDS_RECORD_ONLY
        if lvl is S.PARTIAL and not self.implemented:
            return WORDS_PARTIAL_NOT_IMPLEMENTED
        return SUPPORT_WORDS[lvl]

    @property
    def support_summary(self) -> str:
        """One plain sentence about how far this entry is tested (the dashboard's header; ``support.note`` has the
        technical details). A game Pitwall cannot read gets the reason why."""
        lvl = self.level
        if lvl is None:
            return OTHER_SUMMARY
        if not self.implemented:
            return self.feature("lap_timing").reason
        return SUPPORT_SUMMARY[lvl]

    @property
    def where(self) -> str:
        """``"Gran Turismo 7 (PS5)"``; ``"Forza Motorsport (2023) on PC"``, ``"Assetto Corsa on PS5 (PS4 version)"``
        (no double brackets); the label alone for ``any``."""
        if self.platform == "any":
            return self.label
        if self.label.endswith(")") or self.platform_label.endswith(")"):
            return f"{self.label} on {self.platform_label}"
        return f"{self.label} ({self.platform_label})"

    @property
    def features(self) -> tuple[GameFeature, ...]:
        return _features(self.id)

    def feature(self, feature_id: str) -> GameFeature:
        return next(f for f in self.features if f.id == feature_id)

    def rig(self) -> dict[str, Any] | None:
        ag = self.adapter_game
        if ag is None or not self.implemented:
            return None
        pairs = rig_supported()
        if ag not in {g for g, _ in pairs}:
            return None
        return {"game": ag, "platform": self.platform if (ag, self.platform) in pairs else None}

    def fields_dict(self) -> dict[str, dict[str, str]]:
        """``AdapterInfo.fields`` with each level capped by the entry level (never stronger than the entry)."""
        info, lvl = self.info, self.level
        if info is None or lvl is None or not self.implemented:
            return {}
        out: dict[str, dict[str, str]] = {}
        for k, fs in info.fields.items():
            capped = weakest(lvl, fs.level)
            out[k] = {"level": capped.value, "status": _field_status(capped), "source": fs.source}
        return out

    def to_dict(
        self,
        configs: Mapping[str, IntegrationConfig] | None = None,
        *,
        with_fields: bool = False,
        guide: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        info = self.info
        out: dict[str, Any] = {
            "id": self.id,
            "game_key": self.game_key,
            "label": self.label,
            "short_label": self.short_label,
            "text_name": self.text_name,
            "platform": self.platform,
            "platform_label": self.platform_label,
            "group": self.group,
            "adapter_game": self.adapter_game,
            "variant": self.variant,
            "implemented": self.implemented,
            "integration": self.integration,
            "support": {
                "level": None if self.level is None else self.level.value,
                "words": self.support_words,
                "summary": self.support_summary,
                "note": OTHER_NOTE if self.row is None else self.row.notes,
                "capability_row": None if self.row is None else self.row.key,
            },
            "transport": transport(self.integration, configs),
            "guide_id": self.guide_id,
            "rig": self.rig(),
            "features": [f.to_dict() for f in self.features],
            "notes": list(info.notes) if info is not None and self.implemented else [],
        }
        if with_fields:
            out["fields"] = self.fields_dict()
            out["guide"] = None if guide is None else dict(guide)
        return out


def _adapter_platform_level(info: AdapterInfo, platform: str) -> SupportLevel:
    from pitwall.model.telemetry import Platform

    try:
        return info.platforms.get(Platform(platform), S.UNVERIFIED)
    except ValueError:
        return S.UNVERIFIED


def _field_status(level: SupportLevel) -> str:
    if level is S.UNSUPPORTED:
        return "not_sent"
    if level is S.UNVERIFIED:
        return "unknown"
    if level is S.PARTIAL:
        return "partial"
    return "sent"


@functools.cache
def entries() -> tuple[GameEntry, ...]:
    """Every catalogue entry, in catalogue order."""
    rows = {r.key: r for r in PLANNED}
    out: list[GameEntry] = []
    for game_key, platform, row_key, group, platform_label in _ENTRY_TABLE:
        t = _GAMES[game_key]
        row = rows[row_key] if row_key is not None else None
        readable = row is None or row.implemented
        out.append(
            GameEntry(
                id=f"{game_key}:{platform}",
                game_key=game_key,
                label=t.label,
                short_label=t.short_label,
                text_name=t.text_name,
                platform=platform,
                platform_label=platform_label,
                group=group,
                row=row,
                integration=t.integration if readable else None,
                guide_id=t.guide_id if readable else None,
            )
        )
    return tuple(out)


@functools.cache
def _by_id() -> dict[str, GameEntry]:
    return {e.id: e for e in entries()}


def entry(entry_id: str | None) -> GameEntry | None:
    """The entry with this id; None for None or an unknown id."""
    return None if entry_id is None else _by_id().get(entry_id)


def feature_def(feature_id: str) -> FeatureDef:
    return _FEATURE_BY_ID[feature_id]


# ---------------------------------------------------------------------------------------------- feature status
def _row_tag(e: GameEntry) -> str:
    return "" if e.row is None else f" (row {e.row.key})"


def _feature(e: GameEntry, fd: FeatureDef, level: SupportLevel | None) -> GameFeature:
    name, ag, row, info = e.text_name, e.adapter_game, e.row, e.info
    keys: tuple[str, ...] = ()
    if not fd.code_fact:
        keys = (*(info.ground_plane if (fd.ground_plane and info is not None) else ()), *fd.required)

    def make(
        status: FeatureStatus,
        short: str,
        reason: str,
        detail: str,
        evidence: SupportLevel | None = None,
        note: str | None = None,
        fields: tuple[str, ...] = keys,
    ) -> GameFeature:
        return GameFeature(fd.id, fd.label, fd.group, status, evidence, short, reason, detail, note, fields)

    not_sent_short = f"Not sent by {name}"
    # 1. another game: nothing is known about it
    if row is None:
        return make(
            "unknown",
            "Unknown",
            "Pitwall doesn't know what this game sends.",
            "no decoder for this game: Pitwall can only record its packets",
        )
    # 2. the game/platform has no telemetry output at all
    if row.no_output:
        return make(
            "not_sent",
            not_sent_short,
            f"{name} on {e.platform_label} has no telemetry output.",
            f"{row.notes}{_row_tag(e)}",
        )
    # 3. researched, not implemented
    if not row.implemented or info is None or ag is None or level is None:
        return make(
            "not_implemented",
            "Not in Pitwall yet",
            f"Pitwall can't read {name} telemetry yet.",
            f"{row.notes}{_row_tag(e)}",
        )
    # 4. the game sends it, Pitwall doesn't read it yet
    ni = NOT_IMPLEMENTED.get((ag, fd.id))
    if ni is not None:
        if (ag, fd.id) == ("f1_25", "damage"):
            detail = F1_DAMAGE_DETAIL
        else:
            field_key = NOT_IMPLEMENTED_FIELD[(ag, fd.id)]
            detail = f"{field_key}: {info.fields[field_key].source}"
        return make("not_implemented", "Not in Pitwall yet", ni, detail + _row_tag(e))
    # 5. code facts
    if fd.id == "official_corner_names":
        verified, total = official_name_sheets(ag, e.variant)
        sheets = f"{verified} of {total} track sheets hand-checked (analysis.track_identity.load_sheets)"
        if verified and verified == total:
            return make(
                "supported",
                "",
                f"Pitwall ships hand-checked official corner names for {name} circuits.",
                sheets + _row_tag(e),
            )
        if verified:
            return make(
                "partial",
                "Partial",
                f"Pitwall has hand-checked official corner names for some {name} circuits; elsewhere corners are "
                "numbered from your laps.",
                sheets + _row_tag(e),
            )
        if total and e.variant is not None:
            return make(
                "not_implemented",
                "Not in Pitwall yet",
                f"Pitwall's official corner names were checked with another UDP format, not format {e.variant}; "
                "corners are numbered from your laps.",
                sheets + _row_tag(e),
            )
        covered = official_name_games()
        which = f"cover {_labels(covered)} only" if covered else "cover no game yet"
        return make(
            "not_implemented",
            "Not in Pitwall yet",
            f"Pitwall's official corner names {which}; {name} corners are numbered from your laps.",
            "no hand-checked track sheet for this game (analysis.track_identity.load_sheets)" + _row_tag(e),
        )
    if fd.id == "setup_recommendations":
        if ag in setup_games():
            return make(
                "partial",
                "Partial",
                "Pitwall recommends setups from its catalogue; some cars, tracks and sessions have none.",
                "car setup catalogue (carsetup.context.F1_GAMES)" + _row_tag(e),
            )
        return make(
            "not_implemented",
            "Not in Pitwall yet",
            f"Pitwall's car setup recommendations exist for {_labels(setup_games())} only.",
            "carsetup.context.F1_GAMES" + _row_tag(e),
        )
    # 6. the adapter's declared fields
    declared: list[tuple[str, FieldSupport]] = []
    for k in keys:
        fs = info.fields.get(k)
        if fs is None:
            return make(
                "unknown",
                "Unknown",
                f"Not known whether {name} sends {fd.noun}.",
                f"{k}: not declared by the adapter{_row_tag(e)}",
            )
        declared.append((k, fs))
    for _k, fs in declared:
        if fs.level is S.UNSUPPORTED:
            local = _local_only_noun(e, fd.id)
            if local is not None:  # the game has it, through an interface Pitwall does not read (LOCAL_ONLY)
                return make(
                    "not_implemented",
                    "Not in Pitwall yet",
                    local_only_reason(e, [local]),
                    f"{LOCAL_ONLY_INTERFACE[row.key]}; UDP remote telemetry: {fs.source}{_row_tag(e)}",
                )
            reason = (
                f"{name} doesn't send the other cars' positions, so there is no AI field braking model."
                if fd.id == "ai_field"
                else f"{name} doesn't send {fd.noun}."
            )
            return make("not_sent", not_sent_short, reason, f"{fs.source}{_row_tag(e)}")
    if level is S.UNVERIFIED:
        return make(
            "unknown",
            "Unknown",
            f"Not known whether {name} on {e.platform_label} sends any telemetry.",
            f"{row.notes}{_row_tag(e)}",
        )
    for k, fs in declared:
        if fs.level is S.UNVERIFIED:
            return make(
                "unknown",
                "Unknown",
                f"Not known whether {name} sends {fd.noun}.",
                f"{k}: {fs.source}{_row_tag(e)}",
            )
    for k in fd.optional:  # optional fields count only when declared with real evidence
        fs = info.fields.get(k)
        if fs is not None and fs.level not in (S.UNSUPPORTED, S.UNVERIFIED):
            declared.append((k, fs))
    # 7. supported or partial, with the weakest evidence behind it
    evidence = weakest(level, *(fs.level for _, fs in declared))
    detail = "; ".join(f"{k}: {fs.source}" for k, fs in declared) + _row_tag(e)
    fields = tuple(k for k, _ in declared)
    partial = [k for k, fs in declared if fs.level is S.PARTIAL or (ag, k) in ESTIMATED]
    fact = PARTIAL_FACTS.get((ag, fd.id))
    note = None
    if fd.id == "track_map" and ag in outline_games():
        note = f"Pitwall ships the {name} circuit outlines, so the map shows before your first lap."
    if fact is not None:
        return make("partial", "Partial", fact, detail, evidence, note, fields)
    if partial:
        if "lap_distance_m" in partial and fd.id in DISTANCE_FEATURES:
            reason = DISTANCE_REASON.get(ag, f"{name} sends no lap distance: Pitwall works it out, so it is estimated.")
            return make("partial", "Estimated", reason, detail, evidence, note, fields)
        reason = PARTIAL_REASON.get(fd.id, "{name} sends " + fd.noun + ", but only in part.").format(name=name)
        return make("partial", "Partial", reason, detail, evidence, note, fields)
    return make("supported", "", _supported_reason(fd, name), detail, evidence, note, fields)


def _labels(adapter_games: Iterable[str]) -> str:
    names = sorted({_label_of(g) for g in adapter_games}) or ["no game"]
    return _join(names).replace(" or ", " and ")


def _supported_reason(fd: FeatureDef, name: str) -> str:
    special = {
        "delta": f"{name} sends the lap distance a live delta needs.",
        "braking_cues": f"{name} sends the brake, speed and lap distance that braking cues need.",
        "corner_coaching": f"{name} sends the inputs, speed and lap distance that corner coaching needs.",
        "track_map": f"{name} sends the car's position on track for the map.",
        "ai_field": f"{name} sends the other cars' data that the AI field braking model learns from.",
    }
    return special.get(fd.id, f"{name} sends {fd.noun}.")


@functools.cache
def _features(entry_id: str) -> tuple[GameFeature, ...]:
    e = _by_id()[entry_id]
    lvl = e.level
    return tuple(_feature(e, fd, lvl) for fd in FEATURES)


def feature_status(e: GameEntry, feature_id: str) -> GameFeature:
    """The status of one feature for one entry (section 2.5 of the design spec)."""
    return e.feature(feature_id)


# ---------------------------------------------------------------------------------------------- transport
def transport(integration: str | None, configs: Mapping[str, IntegrationConfig] | None = None) -> dict[str, Any]:
    """How the telemetry reaches Pitwall for an integration (ports from the current configuration when given)."""
    from pitwall.integrations import AC_GAME_PORT, SPECS

    def port(key: str) -> int:
        cfg = (configs or {}).get(key)
        return cfg.port if cfg is not None else SPECS[key].default_port

    mac = this_machine()
    if integration == "f1":
        p = port("f1")
        return _transport(
            "udp_listen",
            f"The game sends UDP telemetry to {mac}'s IP, port {p} (Settings › Telemetry Settings).",
            p,
            None,
            "no",
            True,
        )
    if integration == "gt7":
        from pitwall.adapters.gt7.packets import CONSOLE_PORT

        p = port("gt7")
        return _transport(
            "udp_heartbeat",
            f"Pitwall asks the console for telemetry (heartbeat to UDP {CONSOLE_PORT}); it arrives on UDP {p}.",
            p,
            CONSOLE_PORT,
            "optional",
            False,
        )
    if integration == "forza":
        p = port("forza")
        return _transport(
            "udp_listen",
            f"The game sends Data Out telemetry to {mac}'s IP, port {p} (Settings › Gameplay & HUD › "
            "UDP Race Telemetry).",
            p,
            None,
            "no",
            True,
        )
    if integration == "ac":
        return _transport(
            "udp_client",
            f"Pitwall registers with the game (UDP {AC_GAME_PORT}); nothing to set in the game.",
            None,
            AC_GAME_PORT,
            "required",
            False,
        )
    if integration == "record":
        p = port("record")
        return _transport(
            "udp_listen",
            f"The game sends its UDP packets to {mac}'s IP, port {p}; Pitwall records them for a future decoder.",
            p,
            None,
            "no",
            True,
        )
    return _transport("none", "Pitwall can't read this game's telemetry.", None, None, "no", False)


def _transport(
    kind: str, summary: str, port: int | None, console_port: int | None, console_ip: str, in_game: bool
) -> dict[str, Any]:
    return {
        "kind": kind,
        "summary": summary,
        "port": port,
        "console_port": console_port,
        "console_ip": console_ip,
        "in_game_setting": in_game,
    }


def console_ip_need(e: GameEntry) -> str:
    return str(transport(e.integration)["console_ip"])


# ---------------------------------------------------------------------------------------------- responses
def games_response(configs: Mapping[str, IntegrationConfig] | None = None) -> dict[str, Any]:
    """``GET /api/games``: every entry with its features (no ``fields`` / ``guide``)."""
    return {
        "schema": SCHEMA,
        "entries": [e.to_dict(configs) for e in entries()],
        "features": [{"id": f.id, "label": f.label, "group": f.group, "noun": f.noun} for f in FEATURES],
        "groups": [{"id": g, "label": label} for g, label in GROUPS],
        "support_words": {lvl.value: SUPPORT_WORDS[lvl] for lvl in LEVEL_ORDER},
    }


# ---------------------------------------------------------------------------------------------- selection
@dataclass(frozen=True, slots=True)
class Selection:
    id: str
    since_unix: float
    source: str  # "dashboard" | "cli" | "driver_default"
    # source "driver_default": the driver whose usual game it is, so Setup › Game can say "Selected because Sam
    # usually plays GT7" (v0.2.0 plan 1.3). None for any other source, and from a settings.json written before it.
    by_driver_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "since_unix": round(self.since_unix, 3),
            "source": self.source,
            "by_driver_id": self.by_driver_id,
        }

    def section(self) -> dict[str, Any]:
        """The ``SettingsStore`` section ``"game"``."""
        out: dict[str, Any] = {"selected": self.id, "since_unix": self.since_unix, "source": self.source}
        if self.by_driver_id is not None:
            out["by_driver_id"] = self.by_driver_id
        return out


def new_selection(entry_id: str, source: str, by_driver_id: int | None = None) -> Selection:
    if entry(entry_id) is None:
        raise ValueError(f"unknown game {entry_id!r}: see GET /api/games (or uv run pitwall game list)")
    src = source if source in SOURCES else "dashboard"
    return Selection(entry_id, time.time(), src, by_driver_id if src == "driver_default" else None)


def parse_selection(section: Mapping[str, Any] | None) -> Selection | None:
    """Lenient: no section, no id or an id the catalogue no longer has reads as None (the latter logged)."""
    if not section:
        return None
    sel = section.get("selected")
    if not isinstance(sel, str) or not sel:
        return None
    if entry(sel) is None:
        log.warning("ignoring the stored game selection %r: not in this version's catalogue", sel)
        return None
    since = section.get("since_unix")
    since_f = float(since) if isinstance(since, int | float) and not isinstance(since, bool) else 0.0
    src = section.get("source")
    source = src if isinstance(src, str) and src in SOURCES else "dashboard"
    by = section.get("by_driver_id")
    by_id = by if isinstance(by, int) and not isinstance(by, bool) and source == "driver_default" else None
    return Selection(sel, since_f, source, by_id)


# ---------------------------------------------------------------------------------------------- detection
@functools.lru_cache(maxsize=64)
def resolve(
    adapter_game: str | None,
    platform: str | None,
    variant: str | None,
    prefer: str | None = None,
    configured: str | None = None,
) -> str | None:
    """The catalogue entry id for a detected game: implemented entries of ``adapter_game``, kept to ``variant``, to
    ``platform`` (reported by the game) and to ``configured`` (the platform the input is set to, e.g. Assetto Corsa's:
    not evidence, so never a mismatch, but it says which entry is in use) when those narrow the list; ``prefer`` (the
    selection) wins if it is still a candidate. Otherwise, while the platform stays ambiguous, the candidate with the
    weakest evidence among the main catalogue entries (then catalogue order): an unknown platform never shows
    stronger support than the weakest it could be. Memoised: the live snapshot calls it on the web thread."""
    if not adapter_game:
        return None
    cands = [e for e in entries() if e.implemented and e.adapter_game == adapter_game]
    if variant:
        narrowed = [e for e in cands if e.variant == variant]
        cands = narrowed or cands
    for p in (platform, configured):
        if p and p not in ("unknown", "any"):
            narrowed = [e for e in cands if e.platform == p]
            cands = narrowed or cands
    if prefer is not None and any(e.id == prefer for e in cands):
        return prefer
    pool = [e for e in cands if e.group == "main"] or cands
    if not pool:
        return None
    return max(pool, key=lambda e: _RANK[e.level] if e.level is not None else len(LEVEL_ORDER)).id


@functools.cache
def platform_on_wire(adapter_game: str) -> bool:
    """Whether this adapter's ``SessionInfo.platform`` is reported by the game (F1) rather than configured (AC)."""
    try:
        info = ADAPTER_INFOS.get(Game(adapter_game))
    except ValueError:
        return False
    fs = None if info is None else info.fields.get("platform")
    return info is not None and (fs is None or fs.level is not S.UNSUPPORTED)


def variant_of(adapter_game: str | None, packet_format: object) -> str | None:
    """F1 UDP format as a catalogue variant ("2025" / "2026"); None otherwise."""
    if adapter_game != Game.F1_25.value:
        return None
    v = str(packet_format) if isinstance(packet_format, int | str) and not isinstance(packet_format, bool) else ""
    return v if v in ("2025", "2026") else None


def entry_for_session(row: Mapping[str, Any] | None) -> GameEntry | None:
    """The catalogue entry of a stored session row (``game``, ``platform``, ``info.packet_format``); None when the
    game has no implemented entry (synthetic / unknown)."""
    if not row:
        return None
    game = row.get("game")
    if not isinstance(game, str):
        return None
    info = row.get("info")
    fmt = info.get("packet_format") if isinstance(info, Mapping) else None
    platform = row.get("platform")
    return entry(resolve(game, platform if isinstance(platform, str) else None, variant_of(game, fmt)))


def session_platform_known(row: Mapping[str, Any] | None) -> bool:
    p = None if not row else row.get("platform")
    return isinstance(p, str) and p in PLATFORM_WORDS


def display_label(game: str | None, platform: str | None = None) -> str:
    """A stored session's game for people: ``F1 25 · PS5`` (game, then the platform the game reported). The game alone
    when the platform is unknown (GT7 on PS4 and PS5 sends the same packets: never guessed); ``Synthetic data`` for
    generated telemetry; ``Unknown game`` when there is none. Used by the session report."""
    if not game or game == Game.UNKNOWN.value:
        return "Unknown game"
    if game == Game.SYNTHETIC.value:
        return "Synthetic data"
    text = _GAMES.get(game)
    name = text.text_name if text is not None else game
    word = PLATFORM_WORDS.get(platform or "")
    return f"{name} · {word}" if word else name


def _platform_phrase(platform: str | None) -> str:
    word = PLATFORM_WORDS.get(platform or "")
    if word is None:
        return ""
    return f" from {'an' if word.startswith('X') else 'a'} {word}"


def _label_of(adapter_game: str) -> str:
    e = next((x for x in entries() if x.adapter_game == adapter_game and x.implemented), None)
    return e.label if e is not None else adapter_game


def mismatch(
    selected_id: str | None, detected: Mapping[str, Any] | None, status: str | None = None
) -> dict[str, Any] | None:
    """D6: real data from another game, platform (F1) or F1 UDP format than the selection, arriving now or paused
    (stale: the driver picks up the iPad exactly then); else None."""
    sel = entry(selected_id)
    if sel is None or not detected or not detected.get("real"):
        return None
    if (status or detected.get("status")) not in ("live", "stale"):
        return None
    det_ag = detected.get("adapter_game")
    det_id = detected.get("entry_id")
    det = entry(det_id if isinstance(det_id, str) else None)
    det_label = det.label if det is not None else _label_of(str(det_ag))
    if sel.adapter_game != det_ag:
        kind, text = "game", f"Receiving {det_label}, but {sel.where} is selected."
    else:
        platform = detected.get("platform")
        if isinstance(platform, str) and platform in PLATFORM_WORDS and platform != sel.platform:
            kind = "platform"
            text = f"Receiving {sel.text_name}{_platform_phrase(platform)}, but {sel.platform_label} is selected."
        else:
            variant = detected.get("variant")
            if not variant or not sel.variant or variant == sel.variant:
                return None
            kind = "variant"
            pack = " (2026 Season Pack)" if variant == "2026" else ""
            text = f"Receiving UDP format {variant}{pack}, but {sel.text_name} (format {sel.variant}) is selected."
    return {"kind": kind, "selected_id": sel.id, "detected_id": det.id if det else None, "text": text}


def live_suggestion(detected: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Nothing selected and real telemetry arrives: suggest its entry."""
    if not detected or not detected.get("real"):
        return None
    e = entry(detected.get("entry_id") if isinstance(detected.get("entry_id"), str) else None)
    if e is None:
        return None
    platform = detected.get("platform")
    return {
        "id": e.id,
        "source": "live",
        "text": f"Pitwall sees {e.label} telemetry{_platform_phrase(platform if isinstance(platform, str) else None)}.",
    }


def history_suggestion(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The most recent real session's entry (not synthetic, not a replay of a recording): "You last drove F1 25 on
    PS5."."""
    for row in rows:
        if row.get("synthetic") or str(row.get("source") or "").startswith("replay:"):
            continue
        e = entry_for_session(row)
        if e is None:
            continue
        on = f" on {e.platform_label}" if session_platform_known(row) else ""
        return {"id": e.id, "source": "history", "text": f"You last drove {e.label}{on}."}
    return None


def snapshot_block(
    selected_id: str | None,
    adapter_game: str | None,
    platform: str | None,
    variant: str | None,
    real: bool,
    status: str,
    configured: str | None = None,
    stale_mismatch: bool = True,
) -> dict[str, Any]:
    """``Snapshot.game``: a handful of attribute reads and one memoised lookup (web thread, never ingest).

    ``status``: of the decoded data ("live" / "stale" / "no_data"). ``configured``: the platform the input is set to
    when the game does not report it (Assetto Corsa): it picks the entry, never a mismatch. ``stale_mismatch``: a
    stale detection is a pause (the mismatch stays) rather than data long gone."""
    detected = None
    if adapter_game and adapter_game not in (Game.SYNTHETIC.value, Game.UNKNOWN.value) and status in ("live", "stale"):
        detected = {
            "entry_id": resolve(adapter_game, platform, variant, selected_id, configured),
            "adapter_game": adapter_game,
            "platform": platform if platform in PLATFORM_WORDS else "unknown",
            "variant": variant,
            "real": real,
            "status": status,
        }
    effective = (detected or {}).get("entry_id") or selected_id
    return {
        "selected_id": selected_id,
        "effective_id": effective,
        "detected": detected,
        "mismatch": mismatch(selected_id, detected, status) if status == "live" or stale_mismatch else None,
        "suggestion": live_suggestion(detected) if selected_id is None else None,
    }


# ---------------------------------------------------------------------------------------------- inputs
def busy(row: Mapping[str, Any] | None) -> bool:
    """The input received a packet in the last ``BUSY_S`` seconds (a source, or the AC client)."""
    if not row:
        return False
    for src in row.get("sources") or ():
        age = src.get("last_seen_s") if isinstance(src, Mapping) else None
        if isinstance(age, int | float) and age < BUSY_S:
            return True
    client = row.get("client")
    age = client.get("last_rx_s_ago") if isinstance(client, Mapping) else None
    return isinstance(age, int | float) and age < BUSY_S


def receiving(row: Mapping[str, Any] | None) -> bool:
    """The input's decoder accepted a packet in the last ``BUSY_S`` seconds (``decoded_s_ago``): telemetry is really
    arriving, not stray packets. Without a decoder (raw recording) any packet counts (``busy``)."""
    if not row:
        return False
    if "decoded_s_ago" not in row:
        return busy(row)
    age = row.get("decoded_s_ago")
    return isinstance(age, int | float) and not isinstance(age, bool) and age < BUSY_S


def game_input(e: GameEntry | None, rows: Sequence[Mapping[str, Any]] | None) -> dict[str, Any] | None:
    """``GameState.input``: the selected entry's integration as ``Runtime.input_status`` reports it."""
    from pitwall.integrations import SPECS, listens

    if e is None or e.integration is None:
        return None
    key = e.integration
    row = next((r for r in rows or () if r.get("key") == key), None) or {}
    ip = row.get("console_ip")
    platform = row.get("platform") if key == "ac" else None
    port = row.get("port") if listens(key) else None
    return {
        "key": key,
        "name": SPECS[key].name,
        "enabled": bool(row.get("enabled")),
        "listening": bool(row.get("listening")),
        "received": int(row.get("received") or 0),
        "console_ip": ip if isinstance(ip, str) else None,
        "console_ip_need": console_ip_need(e),
        "port": port if isinstance(port, int) else None,
        "platform": platform if isinstance(platform, str) else None,
        "error": row.get("error") if isinstance(row.get("error"), str) else None,
        "in_use": receiving(row),  # "Receiving" only for decoded telemetry
    }


def other_inputs(e: GameEntry | None, rows: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Every other enabled input; only ever *offered* for switching off (F1 never, an input in use never)."""
    from pitwall.integrations import SPECS

    mine = e.integration if e is not None else None
    out: list[dict[str, Any]] = []
    for r in rows or ():
        key = r.get("key")
        if not isinstance(key, str) or key == mine or key not in SPECS or not r.get("enabled"):
            continue
        in_use = busy(r)
        out.append(
            {
                "key": key,
                "name": SPECS[key].name,
                "enabled": True,
                "in_use": in_use,
                "can_disable": key != "f1" and not in_use,
            }
        )
    return out


def game_state(
    selection: Selection | None,
    block: Mapping[str, Any] | None,
    rows: Sequence[Mapping[str, Any]] | None,
    configs: Mapping[str, IntegrationConfig] | None = None,
    history: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """``GameState`` (``GET /api/game``): the selection, its input, the live detection (``LiveState.game_block``)
    and a suggestion (live first, else ``history``) while nothing is selected."""
    e = entry(selection.id) if selection is not None else None
    b = dict(block or {})
    suggestion = b.get("suggestion") if selection is None else None
    if selection is None and suggestion is None:
        suggestion = history
    return {
        "selected": None if selection is None else selection.to_dict(),
        "entry": None if e is None else e.to_dict(configs),
        "effective_id": b.get("effective_id", None if selection is None else selection.id),
        "first_run": selection is None,
        "detected": b.get("detected"),
        "mismatch": b.get("mismatch"),
        "suggestion": suggestion,
        "input": game_input(e, rows),
        "other_inputs": other_inputs(e, rows),
        "driver_defaults": True,  # DriverPreferences.default_game ("Usually plays") is supported
    }


# ---------------------------------------------------------------------------------------------- selecting a game
SHORT_INPUT = {"f1": "F1 25", "gt7": "GT7", "forza": "Forza", "ac": "Assetto Corsa", "record": "Recorder"}
GT7_NEEDS_IP = (
    "Enter the {platform}'s IP address to switch the GT7 input on. Without one, Pitwall can search the network for "
    "the console instead: Search the network on Setup › Game, or switch GT7 on at Setup › Connect."
)


def _action(key: str | None, action: str, message: str) -> dict[str, Any]:
    return {"key": key, "action": action, "message": message}


def validate_console_ip(e: GameEntry, console_ip: str | None) -> str | None:
    """The cleaned console IP for ``e`` (None when not given). Raises ``ValueError`` with a user-readable message."""
    from pitwall.integrations import AC_IP_EXAMPLE, GT7_IP_EXAMPLE, _console_ip

    if console_ip in (None, ""):
        return None
    if console_ip_need(e) == "no":
        raise ValueError(f"{e.where} does not need a console IP")
    return _console_ip(console_ip, AC_IP_EXAMPLE if e.integration == "ac" else GT7_IP_EXAMPLE)


def ensure_input(
    e: GameEntry,
    settings: Settings,
    store: SettingsStore,
    rows: Sequence[Mapping[str, Any]] | None,
    console_ip: str | None = None,
) -> list[dict[str, Any]]:
    """D7: make sure the selected game's input is on (and its AC platform / console IP set). Never disables
    anything; an action that would modify an input receiving packets right now is skipped (``skipped_live``).
    ``console_ip`` must already be validated (``validate_console_ip``). ``rows``: ``Runtime.input_status()``, or
    None without a running server (nothing can be busy then)."""
    from pitwall.integrations import SECTION as INTEGRATIONS_SECTION
    from pitwall.integrations import PortConflict, apply_update, resolve_configs

    key = e.integration
    if key is None:
        return [_action(None, "none", e.feature("lap_timing").reason)]
    if key == "record":
        return [
            _action(
                "record",
                "none",
                "Turn on 'Record another game' on Setup › Connect to save its packets for a future decoder.",
            )
        ]
    cfg = resolve_configs(settings, store.get(INTEGRATIONS_SECTION))[key]
    name = SHORT_INPUT[key]
    row = next((r for r in rows or () if r.get("key") == key), None)
    if key == "f1":
        msg = f"The F1 25 input is always on (UDP {cfg.port})."
        if e.variant == "2026":
            msg += " Set the game's UDP Format to 2026."
        return [_action("f1", "already_enabled", msg)]
    updates: dict[str, Any] = {}
    if key == "gt7" and not cfg.enabled and console_ip is None and cfg.console_ip is None:
        # Without a console IP the GT7 input searches the network (a heartbeat broadcast every 1.6 s): only ever on an
        # explicit request (Setup › Game "Search the network", Setup › Connect), never as a side effect of a choice.
        return [_action("gt7", "needs_console_ip", GT7_NEEDS_IP.format(platform=e.platform_label))]
    if not cfg.enabled:
        updates["enabled"] = True
    if key == "ac" and cfg.platform != e.platform:
        updates["platform"] = e.platform
    if key in ("gt7", "ac") and console_ip is not None and console_ip != cfg.console_ip:
        updates["console_ip"] = console_ip
    actions: list[dict[str, Any]] = []
    modifying = {k: v for k, v in updates.items() if k != "enabled"}
    if modifying and busy(row):
        what = " and ".join("its platform" if k == "platform" else "its console IP" for k in modifying)
        actions.append(
            _action(key, "skipped_live", f"{name} is streaming: change {what} on Setup › Connect after the session.")
        )
        updates = {k: v for k, v in updates.items() if k == "enabled"}
    if updates:
        try:
            apply_update(settings, store, key, updates)
        except PortConflict as err:
            return [*actions, _action(key, "error", str(err))]
        except ValueError as err:
            return [*actions, _action(key, "error", str(err))]
        if "enabled" in updates:
            where = f" (UDP {cfg.port})" if key in ("gt7", "forza") else ""
            actions.append(_action(key, "enabled", f"{name} input switched on{where}."))
        if "platform" in updates:
            actions.append(_action(key, "set_platform", f"Assetto Corsa platform set to {e.platform_label}."))
        if "console_ip" in updates:
            actions.append(_action(key, "set_console_ip", f"Console IP set to {updates['console_ip']}."))
    if cfg.enabled and "enabled" not in updates:
        actions.insert(0, _action(key, "already_enabled", f"The {name} input is on."))
    stored_ip = console_ip or cfg.console_ip
    if key == "gt7" and stored_ip is None:
        actions.append(
            _action("gt7", "needs_console_ip", "Optional: without it Pitwall searches the network for the console.")
        )
    if key == "ac" and stored_ip is None:
        actions.append(
            _action(
                "ac",
                "needs_console_ip",
                "Required: Pitwall must contact the console. Enter its IP address (PS5: Settings › Network › "
                "Connection Status).",
            )
        )
    return actions


# ---------------------------------------------------------------------------------------------- engineer / radio
INTENT_FEATURES: dict[str, tuple[str, ...]] = {
    "fuel": ("fuel",),
    "tyres": ("tyre_temps", "tyre_wear", "tyre_pressures", "brake_temps"),
    "strategy": ("fuel", "tyre_wear"),
    "damage": ("damage",),
    "ers": ("ers", "drs"),
    "sectors": ("sectors",),
    "flags": ("flags",),
    "safety_car": ("flags",),  # the safety car and VSC come with the flags (F1 Session.safetyCarStatus)
    "gaps": ("field_data",),  # gaps and race position need the other cars' timing
    "weather": ("weather",),
    "setup": ("setup_telemetry", "setup_recommendations"),
}
CAPABILITY_ONLY_INTENTS: frozenset[str] = frozenset(INTENT_FEATURES) - {"setup"}  # setup: technique first


def _join(words: Sequence[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " or " + words[-1]


def capability_sentence(e: GameEntry | None, feature_ids: Iterable[str]) -> str | None:
    """What the game does not send / Pitwall does not read among ``feature_ids``, in plain words; None if nothing.

    ``"GT7 doesn't send tyre wear, tyre pressures or brake temperatures."``; not-implemented features add their own
    reason ("GT7 sends a fuel level, but ..."). Unknown features are left out (they stay "-")."""
    if e is None:
        return None
    feats = [e.feature(f) for f in feature_ids]
    not_sent = [f for f in feats if f.status == "not_sent"]
    not_impl = [f for f in feats if f.status == "not_implemented"]
    if not not_sent and not not_impl:
        return None
    parts: list[str] = []
    if not_sent:
        if e.row is not None and e.row.no_output:
            parts.append(not_sent[0].reason)
        else:
            parts.append(f"{e.text_name} doesn't send {_join([f.noun for f in not_sent])}.")
    local = [n for f in not_impl if (n := _local_only_noun(e, f.id)) is not None]  # one sentence, not one per noun
    if local:
        parts.append(local_only_reason(e, local))
    for reason in dict.fromkeys(f.reason for f in not_impl if _local_only_noun(e, f.id) is None):
        parts.append(reason)
    return " ".join(parts)


def capability_only(intent: str, e: GameEntry | None) -> bool:
    """Every feature this question is about is not sent / not read for this game: the answer is a known fact, not
    data (no LLM, no "Copy, checking.")."""
    if e is None or intent not in CAPABILITY_ONLY_INTENTS:
        return False
    return all(e.feature(f).status in UNAVAILABLE for f in INTENT_FEATURES[intent])


def capability_facts(e: GameEntry, platform_known: bool = True) -> list[tuple[str, str, str, dict[str, Any]]]:
    """(group, text, say, data) per ``INTENT_FEATURES`` group with an unavailable feature. The text carries the
    game label, so a number in it ("F1 25") is grounded by the fact itself."""
    out: list[tuple[str, str, str, dict[str, Any]]] = []
    where = f"{e.label}, {e.platform_label}" if platform_known and e.platform != "any" else e.label
    for group, feature_ids in INTENT_FEATURES.items():
        sentence = capability_sentence(e, feature_ids)
        if sentence is None:
            continue
        feats = [e.feature(f) for f in feature_ids]
        data = {
            "game": e.id,
            "group": group,
            "not_sent": [f.id for f in feats if f.status == "not_sent"],
            "not_implemented": [f.id for f in feats if f.status == "not_implemented"],
        }
        out.append((group, f"Game capability ({where}): {sentence}", sentence, data))
    return out


def capability_sheet(e: GameEntry) -> FactSheet:
    """A fact sheet of only the game's capability facts (no session recorded yet)."""
    from pitwall.ai.facts import FactSheet

    fs = FactSheet()
    for _group, text, say, data in capability_facts(e):
        fs.add("game", text, data, say=say)
    return fs


def entry_of_sheet(sheet: FactSheet | None) -> GameEntry | None:
    """The catalogue entry a fact sheet is about (session fact ``game_entry``, else a game fact's ``game``)."""
    if sheet is None:
        return None
    for f in sheet.facts:
        if f.topic == "session" and isinstance(f.data.get("game_entry"), str):
            return entry(f.data["game_entry"])
    for f in sheet.facts:
        if f.topic == "game" and isinstance(f.data.get("game"), str):
            return entry(f.data["game"])
    return None
