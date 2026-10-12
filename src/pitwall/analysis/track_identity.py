"""Corner identity (layer L2): official turn numbers and names for a learned ``TrackModel``.

The learned model (``analysis/track.py``) finds corners as speed minima and numbers them ``T1..Tn`` in
detection order. That is not the official numbering: flat kinks have no minimum, complexes merge, and a
double apex splits one turn in two. On the real Austria race, pitwall's "T9" was the official Turn 10.
This module attaches the official identity from a pitwall-authored *track sheet* without touching any
position (research: ``docs/research/track-knowledge-sources.md`` sections 2 and 8, phase 2;
``docs/research/track-reference-sources.md`` section 6.3 steps 4-5).

Design decisions:

- **Labels only, never positions.** The learned apex/entry/exit distances stay authoritative (layer L3).
  Mapping copies the model and fills the optional identity fields at the end of ``Corner``; ``Corner.name``
  (``T1..Tn``) stays the join key used by comparisons, observations and the database. Identity is derived on
  use and never persisted (``TrackModel.to_dict()`` leaves it out).
- **Only verified turns by default.** ``identity_tier`` is ``"sheet_verified"`` when a maintainer checked the
  turn against recorded game telemetry and an authoritative numbering reference (``verified = true``), else
  ``"sheet_seeded"`` (imported, unreviewed). ``identify``/``map_identity`` attach only turns at or above
  ``min_tier``, default ``"sheet_verified"``: a seeded number can be wrong (the first Pits n' Giggles pin used
  Melbourne's pre-2022 numbering) and would then be shown, written into coaching text and spoken as fact.
  Learned corners in a seeded window stay unlabelled (``below_min_tier``), so a fully seeded sheet changes
  nothing and the model keeps its learned names everywhere. ``min_tier="sheet_seeded"`` is for review tooling.
- **Segment membership, not nearest metre.** Each sheet turn carries a coarse window in game lap metres
  (``game_segment_m``, seeded from Pits n' Giggles, 100-600 m long). A learned corner takes the label of the
  window that contains its apex. Many learned corners in one window share the label (a double apex or a
  complex), told apart by ``label_part``.
- **Absent turns: merged or reported, never invented.** A sheet turn with no learned apex in its window is
  either a flat kink (no minimum at all) or a turn whose minimum merged into a neighbour's (a chicane under the
  60 m spacing rule; research section 6.3 step 5: "several official corners can map to one pitwall corner").
  It is merged into a learned corner when the centre of its window lies in that corner's braking/turn-in
  phase, ``[entry_m, apex_m + 60 m]``: the driver is slowing for that minimum while passing through the absent
  turn, so coaching about the minimum concerns both ("Turns 1-2"). ``exit_m`` is deliberately not used: it is
  the first full-throttle point, which on the real Austria lap lies 1000 m after Turn 4 and would swallow the
  part-throttle Turns 5 and 8. Otherwise the turn is reported absent and gets no corner.
- **Length scaling with a gate.** Windows are scaled by ``model.length_m / sheet.lap_length_m`` so a
  +/-1 % length difference (another game build, rounding) shifts nothing. Beyond ``MAX_LENGTH_MISMATCH``
  (1.5 %, the layout gate of track-reference-sources.md section 6.2) the sheet is for a different layout and
  nothing is labelled.
- **Sector gate and wire format (game-native cross-checks, layer L0a).** When the caller passes the session's
  ``TrackZones``, the game's own S2/S3 start metres must agree with the sheet's (scaled) within
  ``MAX_SECTOR_MISMATCH_M`` (25 m) or nothing is labelled: a moved timing line exposes a changed layout that the
  length gate can miss. A sheet may list the wire formats its verification used (``verified_formats``, F1 UDP
  ``packetFormat``); in a session of another *known* format its verified turns count as seeded (so, by
  default, are not attached). F1 25 and its 2026 Season Pack share ``Game.F1_25`` but not the evidence.
- **Edge margin.** Window edges are hand-placed and coarse. On real F1 25 data a learned minimum sat 20 m
  past the end of Austria's Turn 1 window (a lift on the exit) and 10 m past Red Bull Mobile's window in the
  reverse layout, in the gap before the next window. An apex that is in *no* window takes the nearest window
  within ``EDGE_MARGIN_M`` (25 m); an apex inside a window always keeps that window. Edge and merged matches
  are uncertain (research section 6.3 step 4): they keep the number but their names are never voiced.
- **Direction veto.** When both the sheet turn and the learned corner know their direction and disagree, no
  label is attached (reported as ``direction_conflict``): a mislabelled corner is worse than an unlabelled
  one. Complexes with mixed directions leave ``direction`` unset in the sheet and are never vetoed.
- **Speech.** Names reach the radio only when the sheet says ``voice_ok`` (seeded sheets never do) and the
  match is ``inside``; otherwise speech uses "Turn N" or a distance.
- **Reverse layouts** have no official numbering: their sheets carry names only and never inherit the
  forward layout's numbers.
- **Synthetic tracks never match.** Sheets are keyed by game and ``<family>:<id>`` track ids; synthetic
  replays use ``synthetic:`` ids, so evidence tiers cannot mix.
- **Never fails the caller.** ``identify`` runs inside model loading and lap analysis: any error (a broken
  sheet, an unexpected model) is logged once and yields the model with identity cleared.
- **Pure.** No I/O at import time. ``load_sheets`` reads the packaged TOML once per family and caches the
  validated, immutable result; everything else is a pure function of its arguments.

Track-sheet schema (TOML, read with stdlib ``tomllib``; unknown keys are errors so typos cannot hide)::

    schema_version = 1
    game_family = "f1"                  # track ids are "<game_family>:<game_track_id>"
    games = ["f1_25"]                   # Game values this sheet's metres were validated for
    game_track_id = 17
    layout = "Red Bull Ring (Grand Prix circuit)"
    lap_length_m = 4323                 # lap length the segment metres are expressed in
    official_turn_count = 10            # 0 for reverse layouts (no official numbering)
    reverse_of = 17                     # optional: forward layout id; then no turn may carry numbers
    sector_starts_m = [1204, 2935]      # optional: S2 and S3 start in the same metres (sector gate)
    verified_formats = [2025]           # optional: wire formats the verified turns were checked against
    sources = ["pits_n_giggles@72f78aa"]
    checked_against = ["..."]           # optional: references a maintainer checked the sheet against
    notes = "..."                       # optional

    [[turns]]                           # in lap order, windows must not overlap
    numbers = [2, 3, 4]                 # contiguous official numbers; omitted = names only
    # label = "T5a"                     # optional, lettered sub-turns only: numbers = [5]; may directly follow
                                        # the turn numbered 5 (or "T5a" before "T5b")
    names = [{ text = "Eau Rouge", kind = "traditional", sources = ["..."] }]  # names[0] is displayed
    game_segment_m = [980, 1360]
    direction = "left"                  # optional: "left" | "right" (single-direction turns only)
    voice_ok = false                    # names may be spoken
    verified = false                    # see "Only verified turns" above; requires checked_against
    sources = ["pits_n_giggles@72f78aa"]
    checked_against = ["..."]
    notes = "..."

Name kinds: ``official`` (the circuit's/FIA's current name), ``traditional`` (long-standing name),
``sponsor`` (changes with sponsorship), ``nickname``, ``unclassified`` (seeded, not yet reviewed; not
allowed on a verified turn). A name a reviewer cannot confirm is left out (and recorded in ``notes``): every
listed name of a verified turn is displayed as fact.
"""

from __future__ import annotations

import functools
import logging
import math
import re
import threading
import tomllib
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

from pitwall import trackdata
from pitwall.analysis.track import MIN_CORNER_SPACING_M, Corner, TrackModel

if TYPE_CHECKING:
    from pitwall.model.telemetry import TrackZones

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
NAME_KINDS = frozenset({"official", "traditional", "sponsor", "nickname", "unclassified"})
DIRECTIONS = frozenset({"left", "right"})
TIER_VERIFIED = "sheet_verified"
TIER_SEEDED = "sheet_seeded"
_TIER_RANK = {TIER_SEEDED: 0, TIER_VERIFIED: 1}
DEFAULT_MIN_TIER = TIER_VERIFIED
MAX_LENGTH_MISMATCH = 0.015  # |model length / sheet length - 1| above this = different layout, no labels
MAX_SECTOR_MISMATCH_M = 25.0  # game S2/S3 start vs sheet (scaled) above this = moved/changed layout, no labels
EDGE_MARGIN_M = 25.0  # an apex in no window may join the nearest window this close (coarse hand-placed edges)
MERGE_AFTER_APEX_M = MIN_CORNER_SPACING_M  # an absent turn this far past a minimum may have merged into it

MATCH_INSIDE = "inside"
MATCH_EDGE = "edge"
MATCH_MERGED = "merged"  # Corner.identity_match only: the label also carries absent turns merged into it
MATCH_NONE = "none"
MATCH_DIRECTION_CONFLICT = "direction_conflict"
MATCH_BELOW_TIER = "below_min_tier"

STATUS_MAPPED = "mapped"
STATUS_LENGTH_MISMATCH = "length_mismatch"
STATUS_SECTOR_MISMATCH = "sector_mismatch"

_OVERRIDE_RE = re.compile(r"^T(\d{1,2})([a-z])$")
_LETTERED_RE = re.compile(r"^T\d{1,2}[a-z]$")
_FAMILY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_FORMAT_RE = re.compile(r"^[a-z][a-z0-9_]*@(\d{4})$")  # TrackZones.source, e.g. "f1_session@2025"
_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth")
_REF_RE = re.compile(r"^\s*(?:t|turns?|corner)?\s*(\d{1,2})([a-z]?)\s*$", re.IGNORECASE)

Style = Literal["short", "long", "voice"]

__all__ = [
    "DEFAULT_MIN_TIER",
    "EDGE_MARGIN_M",
    "MAX_LENGTH_MISMATCH",
    "MAX_SECTOR_MISMATCH_M",
    "MERGE_AFTER_APEX_M",
    "TIER_SEEDED",
    "TIER_VERIFIED",
    "CornerAssignment",
    "CornerText",
    "IdentityMapping",
    "SheetError",
    "SheetTurn",
    "TrackSheet",
    "TurnName",
    "apply_identity",
    "corner_display",
    "corner_texts",
    "find_sheet",
    "format_label",
    "identify",
    "load_sheets",
    "map_identity",
    "parse_sheet",
    "parse_sheet_text",
    "resolve_corner_ref",
    "sector_mismatch_m",
    "track_model_payload",
]


class SheetError(ValueError):
    """A track sheet violates the schema. The message names the sheet and the offending field."""


# ============================================================================================ sheet model
@dataclass(frozen=True, slots=True)
class TurnName:
    text: str
    kind: str  # one of NAME_KINDS
    sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SheetTurn:
    numbers: tuple[int, ...]  # official numbers, contiguous; () for names-only turns (reverse layouts)
    label: str | None  # "T3", "T2-4" (or a lettered override such as "T5a"); None when names-only
    names: tuple[TurnName, ...]
    segment_m: tuple[float, float]  # [start, end) in the sheet's lap metres
    direction: str | None
    voice_ok: bool
    verified: bool
    sources: tuple[str, ...]
    checked_against: tuple[str, ...] = ()
    notes: str | None = None

    @property
    def display_name(self) -> str | None:
        return self.names[0].text if self.names else None

    @property
    def tier(self) -> str:
        return TIER_VERIFIED if self.verified else TIER_SEEDED

    @property
    def lettered(self) -> bool:
        """A sub-turn such as "T5a" (FIA numbering of Madrid's 5A/20A)."""
        return self.label is not None and _LETTERED_RE.match(self.label) is not None

    @property
    def ref(self) -> str:
        """Human reference for reports: the label, else the name."""
        return self.label or self.display_name or "?"


@dataclass(frozen=True, slots=True)
class TrackSheet:
    source: str  # resource name the sheet was read from (for messages)
    game_family: str
    games: tuple[str, ...]
    game_track_id: int
    layout: str
    lap_length_m: float
    official_turn_count: int
    turns: tuple[SheetTurn, ...]
    sources: tuple[str, ...]
    reverse_of: int | None = None
    sector_starts_m: tuple[float, float] | None = None
    verified_formats: tuple[int, ...] = ()  # () = verification not tied to a wire format
    checked_against: tuple[str, ...] = ()
    notes: str | None = None
    schema_version: int = SCHEMA_VERSION

    @property
    def track_id(self) -> str:
        """The pitwall track id this sheet describes, e.g. ``"f1:17"``."""
        return f"{self.game_family}:{self.game_track_id}"

    @property
    def is_reverse(self) -> bool:
        return self.reverse_of is not None


def format_label(numbers: Sequence[int]) -> str | None:
    """``[3]`` -> ``"T3"``, ``[2, 3, 4]`` -> ``"T2-4"``, ``[]`` -> ``None``."""
    if not numbers:
        return None
    if len(numbers) == 1:
        return f"T{numbers[0]}"
    return f"T{numbers[0]}-{numbers[-1]}"


def _contiguous(numbers: Sequence[int]) -> bool:
    return bool(numbers) and list(numbers) == list(range(numbers[0], numbers[0] + len(numbers)))


# ============================================================================================ validation
_SHEET_KEYS = frozenset(
    {
        "schema_version",
        "game_family",
        "games",
        "game_track_id",
        "layout",
        "lap_length_m",
        "official_turn_count",
        "reverse_of",
        "sector_starts_m",
        "verified_formats",
        "sources",
        "checked_against",
        "notes",
        "turns",
    }
)
_SHEET_REQUIRED = frozenset(
    {
        "schema_version",
        "game_family",
        "games",
        "game_track_id",
        "layout",
        "lap_length_m",
        "official_turn_count",
        "sources",
        "turns",
    }
)
_TURN_KEYS = frozenset(
    {
        "numbers",
        "label",
        "names",
        "game_segment_m",
        "direction",
        "voice_ok",
        "verified",
        "sources",
        "checked_against",
        "notes",
    }
)
_TURN_REQUIRED = frozenset({"game_segment_m", "sources"})
_NAME_KEYS = frozenset({"text", "kind", "sources"})
_NAME_REQUIRED = frozenset({"text", "kind"})


def _keys(d: Any, allowed: frozenset[str], required: frozenset[str], where: str) -> Mapping[str, Any]:
    if not isinstance(d, Mapping):
        raise SheetError(f"{where}: expected a table, got {type(d).__name__}")
    unknown = sorted(str(k) for k in set(d) - allowed)
    if unknown:
        raise SheetError(f"{where}: unknown key(s) {unknown}")
    missing = sorted(required - set(d))
    if missing:
        raise SheetError(f"{where}: missing key(s) {missing}")
    return d


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return (isinstance(v, int | float) and not isinstance(v, bool)) and math.isfinite(v)


def _text(v: Any, where: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise SheetError(f"{where}: expected a non-empty string")
    if v != v.strip():
        raise SheetError(f"{where}: leading/trailing whitespace in {v!r}")
    return v


def _choice(v: Any, allowed: frozenset[str], where: str) -> str:
    """A string from ``allowed``; type-checked first so a list or table is a SheetError, not a TypeError."""
    if not isinstance(v, str) or v not in allowed:
        raise SheetError(f"{where}: {v!r} is not one of {sorted(allowed)}")
    return v


def _opt_text(d: Mapping[str, Any], key: str, where: str) -> str | None:
    return _text(d[key], f"{where}.{key}") if key in d else None


def _texts(d: Mapping[str, Any], key: str, where: str, *, nonempty: bool = False) -> tuple[str, ...]:
    raw = d.get(key, [])
    if not isinstance(raw, list):
        raise SheetError(f"{where}.{key}: expected a list of strings")
    out = tuple(_text(v, f"{where}.{key}[{i}]") for i, v in enumerate(raw))
    if nonempty and not out:
        raise SheetError(f"{where}.{key}: must not be empty")
    return out


def _bool(d: Mapping[str, Any], key: str, where: str, default: bool) -> bool:
    v = d.get(key, default)
    if not isinstance(v, bool):
        raise SheetError(f"{where}.{key}: expected true/false")
    return v


def _pair(v: Any, where: str) -> tuple[float, float]:
    if not (isinstance(v, list) and len(v) == 2 and all(_is_num(x) for x in v)):
        raise SheetError(f"{where}: expected [start, end] in metres")
    a, b = float(v[0]), float(v[1])
    if not 0.0 <= a < b:
        raise SheetError(f"{where}: need 0 <= start < end, got [{a:g}, {b:g}]")
    return a, b


def _parse_name(d: Any, where: str) -> TurnName:
    d = _keys(d, _NAME_KEYS, _NAME_REQUIRED, where)
    kind = _choice(d["kind"], NAME_KINDS, f"{where}.kind")
    return TurnName(text=_text(d["text"], f"{where}.text"), kind=kind, sources=_texts(d, "sources", where))


def _parse_turn(d: Any, where: str, *, lap_length_m: float, turn_count: int, reverse: bool) -> SheetTurn:
    d = _keys(d, _TURN_KEYS, _TURN_REQUIRED, where)
    raw_numbers = d.get("numbers", [])
    if not (isinstance(raw_numbers, list) and all(_is_int(n) for n in raw_numbers)):
        raise SheetError(f"{where}.numbers: expected a list of integers")
    numbers = tuple(int(n) for n in raw_numbers)
    if reverse and numbers:
        raise SheetError(f"{where}.numbers: reverse layouts have no official numbering (names only)")
    if numbers:
        if any(not 1 <= n <= turn_count for n in numbers):
            raise SheetError(f"{where}.numbers: {list(numbers)} outside 1..official_turn_count ({turn_count})")
        if not _contiguous(numbers):
            raise SheetError(f"{where}.numbers: {list(numbers)} must be ascending and contiguous")

    label = format_label(numbers)
    if "label" in d:
        override = _text(d["label"], f"{where}.label")
        m = _OVERRIDE_RE.match(override)
        if not numbers or m is None:
            raise SheetError(f"{where}.label: {override!r} needs numbers and the form T5a (lettered sub-turns only)")
        if numbers != (int(m.group(1)),):
            raise SheetError(f"{where}.label: {override!r} does not match numbers {list(numbers)}")
        label = override

    raw_names = d.get("names", [])
    if not isinstance(raw_names, list):
        raise SheetError(f"{where}.names: expected a list of {{text, kind}} tables")
    names = tuple(_parse_name(n, f"{where}.names[{i}]") for i, n in enumerate(raw_names))
    if not numbers and not names:
        raise SheetError(f"{where}: a turn needs official numbers or at least one name")

    segment = _pair(d["game_segment_m"], f"{where}.game_segment_m")
    if segment[1] > lap_length_m:
        raise SheetError(f"{where}.game_segment_m: end {segment[1]:g} beyond lap_length_m {lap_length_m:g}")

    direction = d.get("direction")
    if direction is not None:
        direction = _choice(direction, DIRECTIONS, f"{where}.direction")

    voice_ok = _bool(d, "voice_ok", where, False)
    verified = _bool(d, "verified", where, False)
    checked = _texts(d, "checked_against", where)
    if voice_ok and not names:
        raise SheetError(f"{where}.voice_ok: true but the turn has no names to speak")
    if verified and not checked:
        raise SheetError(f"{where}.verified: true requires checked_against (what it was checked against)")
    if verified and any(n.kind == "unclassified" for n in names):
        raise SheetError(f"{where}: a verified turn must classify every name (kind 'unclassified')")
    return SheetTurn(
        numbers=numbers,
        label=label,
        names=names,
        segment_m=segment,
        direction=direction,
        voice_ok=voice_ok,
        verified=verified,
        sources=_texts(d, "sources", where, nonempty=True),
        checked_against=checked,
        notes=_opt_text(d, "notes", where),
    )


def _order_key(t: SheetTurn, *, last: bool) -> tuple[int, str]:
    """Lap-order key of a numbered turn: (number, sub-turn letter); "T5" < "T5a" < "T5b" < "T6"."""
    n = t.numbers[-1] if last else t.numbers[0]
    return n, (t.label[-1] if t.lettered and t.label else "")


def parse_sheet(doc: Mapping[str, Any], source: str = "<sheet>") -> TrackSheet:
    """Validate one parsed TOML document and return the immutable sheet. Raises ``SheetError``."""
    d = _keys(doc, _SHEET_KEYS, _SHEET_REQUIRED, source)
    if not _is_int(d["schema_version"]) or d["schema_version"] != SCHEMA_VERSION:
        raise SheetError(f"{source}.schema_version: expected {SCHEMA_VERSION}, got {d['schema_version']!r}")
    family = _text(d["game_family"], f"{source}.game_family")
    if not _FAMILY_RE.match(family):
        raise SheetError(f"{source}.game_family: {family!r} must be lower-case [a-z0-9_]")
    games = _texts(d, "games", source, nonempty=True)
    track_no = d["game_track_id"]
    if not _is_int(track_no) or track_no < 0:
        raise SheetError(f"{source}.game_track_id: expected an integer >= 0")
    length = d["lap_length_m"]
    if not _is_num(length) or length <= 0:
        raise SheetError(f"{source}.lap_length_m: expected a positive number of metres")
    lap_length_m = float(length)
    turn_count = d["official_turn_count"]
    if not _is_int(turn_count) or turn_count < 0:
        raise SheetError(f"{source}.official_turn_count: expected an integer >= 0")

    reverse_of = d.get("reverse_of")
    if reverse_of is not None and (not _is_int(reverse_of) or reverse_of < 0 or reverse_of == track_no):
        raise SheetError(f"{source}.reverse_of: expected another layout's game_track_id")
    reverse = reverse_of is not None
    if reverse and turn_count != 0:
        raise SheetError(f"{source}.official_turn_count: must be 0 for a reverse layout (no official numbering)")
    if not reverse and not 1 <= turn_count <= 40:
        raise SheetError(f"{source}.official_turn_count: {turn_count} is not a plausible turn count (1..40)")

    sectors: tuple[float, float] | None = None
    if "sector_starts_m" in d:
        sectors = _pair(d["sector_starts_m"], f"{source}.sector_starts_m")
        if sectors[0] <= 0 or sectors[1] >= lap_length_m:
            raise SheetError(f"{source}.sector_starts_m: must lie strictly inside the lap")

    formats: tuple[int, ...] = ()
    if "verified_formats" in d:
        raw_formats = d["verified_formats"]
        if not (isinstance(raw_formats, list) and raw_formats and all(_is_int(f) and f > 0 for f in raw_formats)):
            raise SheetError(f"{source}.verified_formats: expected a non-empty list of positive integers")
        formats = tuple(sorted({int(f) for f in raw_formats}))

    raw_turns = d["turns"]
    if not isinstance(raw_turns, list) or not raw_turns:
        raise SheetError(f"{source}.turns: expected at least one [[turns]] entry")
    turns = tuple(
        _parse_turn(t, f"{source}.turns[{i}]", lap_length_m=lap_length_m, turn_count=turn_count, reverse=reverse)
        for i, t in enumerate(raw_turns)
    )
    for i in range(1, len(turns)):
        prev, cur = turns[i - 1], turns[i]
        if cur.segment_m[0] < prev.segment_m[1]:
            raise SheetError(
                f"{source}.turns[{i}].game_segment_m: starts at {cur.segment_m[0]:g}, before turns[{i - 1}] "
                f"ends ({prev.segment_m[1]:g}); turns must be in lap order without overlap"
            )
        if prev.numbers and cur.numbers and _order_key(cur, last=False) <= _order_key(prev, last=True):
            raise SheetError(
                f"{source}.turns[{i}].numbers: {cur.ref} after {prev.ref}; official numbers must increase along "
                "the lap and appear once (a lettered sub-turn such as T5a may follow T5)"
            )
    if formats and not any(t.verified for t in turns):
        raise SheetError(f"{source}.verified_formats: set, but no turn is verified")
    return TrackSheet(
        source=source,
        game_family=family,
        games=games,
        game_track_id=int(track_no),
        layout=_text(d["layout"], f"{source}.layout"),
        lap_length_m=lap_length_m,
        official_turn_count=int(turn_count),
        turns=turns,
        sources=_texts(d, "sources", source, nonempty=True),
        reverse_of=None if reverse_of is None else int(reverse_of),
        sector_starts_m=sectors,
        verified_formats=formats,
        checked_against=_texts(d, "checked_against", source),
        notes=_opt_text(d, "notes", source),
    )


def parse_sheet_text(text: str, source: str = "<sheet>") -> TrackSheet:
    """Parse and validate TOML text (used by the seeding tool to check what it writes)."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SheetError(f"{source}: invalid TOML: {e}") from e
    return parse_sheet(doc, source)


# ============================================================================================ loading
@functools.cache
def load_sheets(family: str) -> tuple[TrackSheet, ...]:
    """All packaged sheets of a game family (e.g. ``"f1"``), validated; cached for the process lifetime.

    Raises ``SheetError`` if any sheet is unreadable or invalid, or two sheets claim the same layout for the
    same game: shipped data is checked by the test-suite, so this indicates a packaging bug, not a runtime
    condition (``identify`` turns it into "no identity" and does not retry).
    """
    sheets: list[TrackSheet] = []
    for name, doc in _documents(family):
        sheet = parse_sheet(doc, name)
        if sheet.game_family != family:
            raise SheetError(f"{name}: game_family {sheet.game_family!r} filed under {family!r}")
        sheets.append(sheet)
    seen: dict[tuple[int, str], str] = {}
    for s in sheets:
        for g in s.games:
            key = (s.game_track_id, g)
            if key in seen:
                raise SheetError(f"{s.source}: layout {s.track_id} for {g} is also defined in {seen[key]}")
            seen[key] = s.source
    return tuple(sheets)


def _documents(family: str) -> list[tuple[str, dict[str, Any]]]:
    try:
        return trackdata.sheet_documents(family)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as e:
        raise SheetError(f"track sheets for {family!r}: unreadable: {e}") from e


def find_sheet(game: str | None, track_id: str | None) -> TrackSheet | None:
    """The sheet for a model's ``(game, track_id)``, e.g. ``("f1_25", "f1:17")``; ``None`` when there is none.

    Synthetic (``synthetic:...``) and unknown/negative ids never match. Raises ``SheetError`` when the family's
    sheets are broken (see ``load_sheets``).
    """
    family, number = _parse_track_id(track_id)
    if not game or family is None or number is None:
        return None
    return next((s for s in load_sheets(family) if s.game_track_id == number and game in s.games), None)


def _parse_track_id(track_id: str | None) -> tuple[str | None, int | None]:
    if not isinstance(track_id, str):
        return None, None
    family, sep, raw = track_id.partition(":")
    if not sep or not _FAMILY_RE.match(family) or not raw.isascii() or not raw.isdigit():
        return None, None
    return family, int(raw)


def sector_mismatch_m(
    sheet: TrackSheet, sector2_start_m: float | None, sector3_start_m: float | None, *, scale: float = 1.0
) -> float | None:
    """Largest difference in metres between the sheet's (scaled) and the game's S2/S3 start; ``None`` without data.

    A cheap layout cross-check with game-native data (layer L0a: the F1 Session packet's sector 2/3 lap-distance
    starts, ``SessionInfo.track_zones``). On the real F1 25 Austria capture the sheet's starts agree to 0.07 m; the
    research found 0.5 m for Bahrain. ``scale`` is the model/sheet length ratio the windows are scaled by.
    """
    if sheet.sector_starts_m is None or sector2_start_m is None or sector3_start_m is None:
        return None
    s2, s3 = sheet.sector_starts_m
    diff = max(abs(s2 * scale - float(sector2_start_m)), abs(s3 * scale - float(sector3_start_m)))
    return diff if math.isfinite(diff) else None


def _format_of(zones: TrackZones | None) -> int | None:
    """The wire format recorded in ``TrackZones.source`` ("f1_session@2025" -> 2025); ``None`` if unknown."""
    source = getattr(zones, "source", None)
    m = _FORMAT_RE.match(source) if isinstance(source, str) else None
    return int(m.group(1)) if m else None


# ============================================================================================ mapping
@dataclass(frozen=True, slots=True)
class CornerAssignment:
    """How one learned corner was identified (one row of the learned -> official table)."""

    corner: str  # learned (pitwall) name, the join key
    apex_m: float
    direction: str | None
    turn_index: int | None  # index into sheet.turns, None = unlabelled
    label: str | None
    numbers: tuple[int, ...]
    display_name: str | None
    voice_ok: bool
    tier: str | None
    part: int | None  # 1-based when several learned corners share the turn
    match: str  # MATCH_INSIDE | MATCH_EDGE | MATCH_NONE | MATCH_DIRECTION_CONFLICT | MATCH_BELOW_TIER
    merged_turns: tuple[int, ...] = ()  # absent sheet turns merged into this corner's label (indices)
    candidate: str | None = None  # below_min_tier: the sheet turn it would have taken (for review tooling)


@dataclass(frozen=True, slots=True)
class IdentityMapping:
    """Result of mapping a sheet onto one learned model version (the record to log or persist)."""

    sheet: TrackSheet
    game: str
    track_id: str
    model_version: int
    scale: float  # model length / sheet length, applied to the windows
    status: str  # STATUS_MAPPED | STATUS_LENGTH_MISMATCH | STATUS_SECTOR_MISMATCH
    assignments: tuple[CornerAssignment, ...]
    absent_turns: tuple[int, ...]  # sheet turn indices with no learned corner (flat kinks), merges excluded
    min_tier: str = DEFAULT_MIN_TIER
    packet_format: int | None = None  # the session's wire format, when known
    format_verified: bool = True  # False: the session's format is not among sheet.verified_formats
    sector_mismatch_m: float | None = None  # game vs sheet S2/S3 start, when the caller passed the zones

    @property
    def ok(self) -> bool:
        return self.status == STATUS_MAPPED

    @property
    def labelled(self) -> int:
        return sum(1 for a in self.assignments if a.turn_index is not None)

    def table(self) -> list[dict[str, Any]]:
        """Learned -> official rows, for logs, reports and tests."""
        rows: list[dict[str, Any]] = []
        for a in self.assignments:
            seg = None
            if a.turn_index is not None:
                lo, hi = self.sheet.turns[a.turn_index].segment_m
                seg = [round(lo * self.scale, 1), round(hi * self.scale, 1)]
            rows.append(
                {
                    "corner": a.corner,
                    "apex_m": round(a.apex_m, 1),
                    "direction": a.direction,
                    "label": a.label,
                    "part": a.part,
                    "name": a.display_name,
                    "tier": a.tier,
                    "match": a.match,
                    "merged": [self.sheet.turns[i].ref for i in a.merged_turns],
                    "candidate": a.candidate,
                    "voice_ok": a.voice_ok,
                    "segment_m": seg,
                }
            )
        return rows

    def summary(self) -> str:
        head = f"{self.track_id} {self.sheet.layout} (model v{self.model_version}, min tier {self.min_tier})"
        if self.status == STATUS_LENGTH_MISMATCH:
            return (
                f"{head}: no labels, {self.status} (model/sheet length scale {self.scale:.4f}, "
                f"gate +/-{MAX_LENGTH_MISMATCH:.1%})"
            )
        if self.status == STATUS_SECTOR_MISMATCH:
            return (
                f"{head}: no labels, {self.status} (game vs sheet S2/S3 start differ by "
                f"{self.sector_mismatch_m:.1f} m, gate {MAX_SECTOR_MISMATCH_M:g} m)"
            )

        def row(a: CornerAssignment) -> str:
            if a.turn_index is not None:
                part = f" ({a.part})" if a.part else ""
                how = "" if a.match == MATCH_INSIDE else f" [{a.match}]"
                how += " [merged]" if a.merged_turns else ""
                return f"{a.corner}->{a.label or a.display_name or '?'}{part}{how}"
            if a.candidate:
                return f"{a.corner}->{a.match}:{a.candidate}"
            return f"{a.corner}->{a.match}@{a.apex_m:.0f}m"

        got = ", ".join(row(a) for a in self.assignments)
        absent = ", ".join(self.sheet.turns[i].ref for i in self.absent_turns) or "none"
        fmt = "" if self.format_verified else f"; format {self.packet_format} not verified (tier downgraded)"
        return f"{head}: {self.labelled}/{len(self.assignments)} labelled [{got}]; no learned corner for: {absent}{fmt}"


def _locate(apex: float, spans: Sequence[tuple[float, float]], margin: float) -> tuple[int | None, str]:
    for i, (lo, hi) in enumerate(spans):
        if lo <= apex < hi:
            return i, MATCH_INSIDE
    best: tuple[float, int] | None = None
    for i, (lo, hi) in enumerate(spans):
        gap = max(lo - apex, apex - hi, 0.0)
        if gap <= margin and (best is None or gap < best[0]):
            best = (gap, i)
    return (best[1], MATCH_EDGE) if best is not None else (None, MATCH_NONE)


def _unlabelled(c: Corner, match: str, candidate: str | None = None) -> CornerAssignment:
    return CornerAssignment(
        c.name, c.apex_m, c.direction, None, None, (), None, False, None, None, match, (), candidate
    )


def map_identity(
    model: TrackModel,
    sheet: TrackSheet,
    *,
    zones: TrackZones | None = None,
    packet_format: int | None = None,
    min_tier: str = DEFAULT_MIN_TIER,
    edge_margin_m: float = EDGE_MARGIN_M,
    max_length_mismatch: float = MAX_LENGTH_MISMATCH,
    max_sector_mismatch_m: float = MAX_SECTOR_MISMATCH_M,
) -> IdentityMapping:
    """Assign sheet turns to the model's learned corners by apex membership. Pure; does not modify ``model``.

    ``zones`` (the session's ``TrackZones``) enables the sector gate and supplies the wire format unless
    ``packet_format`` is given. Only turns at or above ``min_tier`` label anything (see the module docstring).
    """
    if min_tier not in _TIER_RANK:
        raise ValueError(f"min_tier must be one of {sorted(_TIER_RANK)}, got {min_tier!r}")
    scale = model.length_m / sheet.lap_length_m if sheet.lap_length_m > 0 else math.nan
    corners = list(model.corners)
    fmt = packet_format if packet_format is not None else _format_of(zones)
    format_verified = not sheet.verified_formats or fmt is None or fmt in sheet.verified_formats

    def result(
        status: str, rows: Sequence[CornerAssignment], absent: Sequence[int], mismatch: float | None
    ) -> IdentityMapping:
        return IdentityMapping(
            sheet=sheet,
            game=model.game,
            track_id=model.track_id,
            model_version=model.version,
            scale=scale,
            status=status,
            assignments=tuple(rows),
            absent_turns=tuple(absent),
            min_tier=min_tier,
            packet_format=fmt,
            format_verified=format_verified,
            sector_mismatch_m=mismatch,
        )

    refused_rows = [_unlabelled(c, MATCH_NONE) for c in corners]
    if not (math.isfinite(scale) and abs(scale - 1.0) <= max_length_mismatch):
        return result(STATUS_LENGTH_MISMATCH, refused_rows, range(len(sheet.turns)), None)
    mismatch = None
    if zones is not None:
        mismatch = sector_mismatch_m(sheet, zones.sector2_start_m, zones.sector3_start_m, scale=scale)
        if mismatch is not None and mismatch > max_sector_mismatch_m:
            return result(STATUS_SECTOR_MISMATCH, refused_rows, range(len(sheet.turns)), mismatch)

    turns = sheet.turns
    tiers = [TIER_VERIFIED if t.verified and format_verified else TIER_SEEDED for t in turns]
    eligible = [_TIER_RANK[tier] >= _TIER_RANK[min_tier] for tier in tiers]
    spans = [(t.segment_m[0] * scale, t.segment_m[1] * scale) for t in turns]

    # 1. Apex membership (every window, so an apex inside a seeded window is never pulled into a verified one).
    picks: list[tuple[int | None, str]] = []
    for c in corners:
        idx, match = _locate(c.apex_m, spans, edge_margin_m)
        if idx is not None:
            want = turns[idx].direction
            if want is not None and c.direction is not None and want != c.direction:
                idx, match = None, MATCH_DIRECTION_CONFLICT
        picks.append((idx, match))
    taken = {i for i, _ in picks if i is not None}  # geometric presence, whatever the tier

    # 2. Learned corners sharing one usable sheet turn are numbered in lap order (by apex, whatever the list order).
    share = Counter(i for i, _ in picks if i is not None and eligible[i])
    part_of: dict[int, int] = {}
    running: Counter[int] = Counter()
    for k in sorted(range(len(corners)), key=lambda k: corners[k].apex_m):
        idx = picks[k][0]
        if idx is not None and eligible[idx] and share[idx] > 1:
            running[idx] += 1
            part_of[k] = running[idx]

    # 3. Absent numbered turns whose window centre lies in a labelled corner's braking/turn-in phase merge into it
    #    (only into a sole, inside-matched, unlettered corner, and only while the combined numbers stay contiguous).
    hosts = [
        k
        for k, (idx, match) in enumerate(picks)
        if idx is not None and match == MATCH_INSIDE and eligible[idx] and k not in part_of and not turns[idx].lettered
    ]
    merged: dict[int, list[int]] = {}
    for i, t in enumerate(turns):
        if i in taken or not eligible[i] or not t.numbers or t.lettered:
            continue
        mid = (spans[i][0] + spans[i][1]) / 2.0
        near = [k for k in hosts if corners[k].entry_m <= mid <= corners[k].apex_m + MERGE_AFTER_APEX_M]
        if not near:
            continue
        k = min(near, key=lambda h: abs(corners[h].apex_m - mid))
        host_turn = picks[k][0]
        assert host_turn is not None
        group = [host_turn, *merged.get(k, []), i]
        if _contiguous(sorted({n for j in group for n in turns[j].numbers})):
            merged.setdefault(k, []).append(i)

    rows: list[CornerAssignment] = []
    for k, (c, (idx, match)) in enumerate(zip(corners, picks, strict=True)):
        if idx is None:
            rows.append(_unlabelled(c, match))
            continue
        t = turns[idx]
        if not eligible[idx]:
            rows.append(_unlabelled(c, MATCH_BELOW_TIER, f"{t.ref} ({tiers[idx]})"))
            continue
        extra = tuple(sorted(merged.get(k, [])))
        if extra:
            numbers = tuple(sorted({*t.numbers, *(n for j in extra for n in turns[j].numbers)}))
            label = format_label(numbers)
            tier = min((tiers[j] for j in (idx, *extra)), key=_TIER_RANK.__getitem__)
        else:
            numbers, label, tier = t.numbers, t.label, tiers[idx]
        rows.append(
            CornerAssignment(
                corner=c.name,
                apex_m=c.apex_m,
                direction=c.direction,
                turn_index=idx,
                label=label,
                numbers=numbers,
                display_name=t.display_name,
                # uncertain matches (edge, merged) keep the number but never speak the name (research 6.3 step 4)
                voice_ok=t.voice_ok and t.display_name is not None and match == MATCH_INSIDE and not extra,
                tier=tier,
                part=part_of.get(k),
                match=match,
                merged_turns=extra,
            )
        )
    merged_all = {j for js in merged.values() for j in js}
    absent = [i for i in range(len(turns)) if i not in taken and i not in merged_all]
    return result(STATUS_MAPPED, rows, absent, mismatch)


def _cleared(c: Corner) -> Corner:
    return replace(
        c,
        label=None,
        official_numbers=[],
        display_name=None,
        voice_ok=False,
        identity_tier=None,
        label_part=None,
        identity_match=None,
    )


def apply_identity(model: TrackModel, mapping: IdentityMapping | None) -> TrackModel:
    """A copy of ``model`` whose corners carry the identity in ``mapping``; positions are untouched.

    ``None`` or a mapping that did not pass the gates returns a copy with every identity field cleared, so
    the result never carries labels from an older sheet. Raises ``ValueError`` if ``mapping`` was made for a
    different model (other track or corner list).
    """
    corners: list[Corner] = []
    if mapping is not None and mapping.ok:
        if (mapping.game, mapping.track_id) != (model.game, model.track_id) or [
            (a.corner, a.apex_m) for a in mapping.assignments
        ] != [(c.name, c.apex_m) for c in model.corners]:
            raise ValueError(f"identity mapping for {mapping.track_id} does not belong to this model")
        for c, a in zip(model.corners, mapping.assignments, strict=True):
            if a.turn_index is None:
                corners.append(_cleared(c))
            else:
                corners.append(
                    replace(
                        c,
                        label=a.label,
                        official_numbers=list(a.numbers),
                        display_name=a.display_name,
                        voice_ok=a.voice_ok,
                        identity_tier=a.tier,
                        label_part=a.part,
                        identity_match=MATCH_MERGED if a.merged_turns else a.match,
                    )
                )
    else:
        corners = [_cleared(c) for c in model.corners]
    return replace(
        model,
        corners=corners,
        centreline=list(model.centreline),
        source_lap_ids=list(model.source_lap_ids),
    )


_failure_lock = threading.Lock()
_failed_families: set[str] = set()  # families whose sheets failed to load: identity stays off for the process
_failed_models: set[tuple[str, ...]] = set()  # (game, track id, version) whose mapping raised (log once)


def identify(
    model: TrackModel,
    *,
    zones: TrackZones | None = None,
    packet_format: int | None = None,
    min_tier: str = DEFAULT_MIN_TIER,
) -> tuple[TrackModel, IdentityMapping | None]:
    """Look up the sheet for the model's game/track, map it and apply it: ``(labelled copy, mapping)``.

    Pass the session's ``zones`` (``SessionInfo.track_zones``, or ``TrackZones.from_dict`` of a stored session
    row's ``info["track_zones"]``) wherever they are known: they enable the sector gate and the wire-format check.

    Never raises: no sheet, a failed gate, a broken sheet (a packaging bug) or any unexpected error return the
    model with identity cleared, so lap analysis can never fail because of track knowledge. Errors are logged
    once (per family for broken sheets, which are not re-read; per model version for mapping errors). The mapping
    is returned when a sheet was found (also when its gate failed) so the caller can log ``summary()``.
    """
    family, _ = _parse_track_id(getattr(model, "track_id", None))
    if family is not None and family not in _failed_families:
        try:
            sheet = find_sheet(model.game, model.track_id)
        except Exception:
            with _failure_lock:
                first = family not in _failed_families
                _failed_families.add(family)
            if first:
                log.exception("track sheets for %r failed to load; corner identity disabled for them", family)
            sheet = None
        if sheet is not None:
            try:
                mapping = map_identity(model, sheet, zones=zones, packet_format=packet_format, min_tier=min_tier)
                return apply_identity(model, mapping), mapping
            except Exception:
                key = tuple(str(getattr(model, a, None)) for a in ("game", "track_id", "version"))
                with _failure_lock:
                    first = key not in _failed_models
                    _failed_models.add(key)
                if first:
                    log.exception("corner identity failed for %s %s v%s; corners stay unlabelled", *key)
    try:
        return apply_identity(model, None), None
    except Exception:  # a model too broken even to copy: hand it back untouched rather than fail the caller
        return model, None


# ============================================================================================ display
@dataclass(frozen=True, slots=True)
class CornerText:
    """Ways to refer to one corner. ``short`` for tables/charts, ``long`` for sentences, ``voice`` for radio."""

    short: str
    long: str
    voice: str


def turn_words(label: str, *, voice: bool) -> str:
    """An official short label in words: "T3" -> "Turn 3", "T2-4" -> "Turns 2-4" (voice: "Turns 2 to 4")."""
    body = label[1:]  # "3", "2-4", "5a"
    if "-" in body:
        lo, hi = body.split("-", 1)
        return f"Turns {lo} to {hi}" if voice else f"Turns {lo}-{hi}"
    return f"Turn {body}"


def _ordinal_part(part: int) -> str:
    return f"{_ORDINALS[part - 1]} part" if 1 <= part <= len(_ORDINALS) else f"part {part}"


def _distance(c: Corner, style: Style) -> str:
    if style == "short":
        return f"{c.apex_m:.0f} m"
    if style == "long":
        return f"Corner at {c.apex_m:.0f} m"
    return f"Corner at {round(c.apex_m, -1):.0f} metres"


def corner_display(c: Corner, style: Style = "long", *, mapped: bool | None = None) -> str:
    """How to refer to a corner in text or speech (``style``: ``short`` | ``long`` | ``voice``).

    - official, named: ``T3`` / ``Turn 3 (Remus)`` / ``Turn 3, Remus``
    - complex: ``T2-4`` / ``Turns 2-4 (Eau Rouge)`` / ``Turns 2 to 4, Eau Rouge``
    - second of two learned corners in one turn: ``T6 (2)`` / ``Turn 6, part 2 (Rauch)`` / ``Turn 6, second part``
    - names only (reverse layouts): ``Remus`` / ``Remus`` / ``Remus``
    - unlabelled corner of a mapped model: ``565 m`` / ``Corner at 565 m`` / ``Corner at 570 metres``
    - no identity at all (no sheet, or only unverified turns): the learned name, ``T2``, in every style

    Names are spoken only when ``voice_ok`` (verified sheets, inside matches); otherwise the voice form is
    "Turn 3", or the distance form for a names-only corner. An unlabelled corner on a *mapped* model is referred
    to by distance because its learned name (``T2``) would collide with an official turn number. ``mapped`` says
    whether the corner's model was mapped; ``None`` infers it from the corner alone, which is only right for
    labelled corners, so callers holding the whole model should use ``corner_texts``.
    """
    if mapped is None:
        mapped = c.identity_tier is not None
    name = c.display_name
    part = c.label_part
    if c.label:
        if style == "short":
            return f"{c.label} ({part})" if part else c.label
        head = turn_words(c.label, voice=style == "voice")
        if style == "long":
            return head + (f", part {part}" if part else "") + (f" ({name})" if name else "")
        bits = [head]
        if name and c.voice_ok:
            bits.append(name)
        if part:
            bits.append(_ordinal_part(part))
        return ", ".join(bits)
    if name:
        if style == "short":
            return f"{name} ({part})" if part else name
        if style == "long":
            return name + (f", part {part}" if part else "")
        if c.voice_ok:
            return name + (f", {_ordinal_part(part)}" if part else "")
        return _distance(c, style)
    if mapped:
        return _distance(c, style)
    return c.name


def corner_texts(model: TrackModel) -> dict[str, CornerText]:
    """``{learned corner name: CornerText}`` for every corner of ``model`` (labelled or not)."""
    mapped = any(c.identity_tier is not None for c in model.corners)
    return {
        c.name: CornerText(
            short=corner_display(c, "short", mapped=mapped),
            long=corner_display(c, "long", mapped=mapped),
            voice=corner_display(c, "voice", mapped=mapped),
        )
        for c in model.corners
    }


BORROWED_CAPTION = "Corners from {other_label} laps until your first clean {label} lap here."
# a model from before car classes whose laps' car was never recorded (no formula, no car id): it stands in too
LEGACY_CAPTION = "Corners from older laps (car class not recorded) until your first clean {label} lap here."


def track_model_payload(model: TrackModel, family: str | None = None) -> dict[str, Any]:
    """``model.to_dict(identity=True)`` plus ``corner_text`` ({learned name: {short, long, voice}}) for the API and
    live state, so the dashboard shows the same labels as coaching and speech without re-implementing these rules.

    Car class families (``pitwall.carclass``): ``car_family`` (from the model) and ``car_family_match`` - False when
    ``family`` (the session's) has no model of its own yet and this model of another family (or a legacy model whose
    family was never recorded) stands in, None when the session's family is unknown (non-F1 games) - with
    ``car_family_note``, the caption that says so.
    """
    from pitwall.carclass import family_label

    match: bool | None = None
    note: str | None = None
    if family is not None and model.car_family is not None:
        match = model.car_family == family
        other, own = family_label(model.car_family), family_label(family)
        if not match and other and own:
            note = BORROWED_CAPTION.format(other_label=other, label=own)
    elif family is not None:
        # a legacy model of unknown family stands in until this family's first clean lap (``LapProcessor._track_model``
        # replaces it then): said so, never taken for the family's own model
        match = False
        own = family_label(family)
        if own:
            note = LEGACY_CAPTION.format(label=own)
    return {
        **model.to_dict(identity=True),
        "corner_text": {
            k: {"short": v.short, "long": v.long, "voice": v.voice} for k, v in corner_texts(model).items()
        },
        "car_family_match": match,
        "car_family_note": note,
    }


def _fold(text: str) -> str:
    """Lower-case, accent-free, punctuation-free words ("Würth Kurve" -> "wurth kurve")."""
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", plain.lower()).split())


def resolve_corner_ref(model: TrackModel, ref: str) -> list[str]:
    """Learned corner names (the join keys, in lap order) that a driver's or LLM's reference means.

    ``ref`` is "T10", "Turn 10", "10", "T5a" or a curated name ("Remus", "lauda", "Wurth"). On a *mapped* model
    numbers are official numbers - the dashboard and radio show official labels, so "Turn 10" is the official
    Turn 10 (learned "T9" on the real Austria model), a number inside a complex finds the complex, "Turn 5" does
    not find the sub-turn "T5a", and an official turn with no learned corner (a flat kink) resolves to nothing.
    On an unmapped model numbers are the learned names, as before. Names match when every word of ``ref`` occurs
    in the corner's name (accent-insensitive).
    """
    mapped = any(c.identity_tier is not None for c in model.corners)
    m = _REF_RE.match(ref)
    if m:
        number, letter = int(m.group(1)), m.group(2).lower()
        if not mapped:
            return [c.name for c in model.corners if c.name.lower() == f"t{number}{letter}"]
        if letter:
            return [c.name for c in model.corners if c.label is not None and c.label.lower() == f"t{number}{letter}"]
        return [
            c.name
            for c in model.corners
            if number in c.official_numbers and not (c.label and _LETTERED_RE.match(c.label))
        ]
    words = _fold(ref).split()
    if not words:
        return []
    return [c.name for c in model.corners if c.display_name and set(words) <= set(_fold(c.display_name).split())]
