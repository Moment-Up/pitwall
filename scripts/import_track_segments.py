"""Seed pitwall track sheets from the vendored Pits n' Giggles ``track-segments`` (dev-only, run by hand).

    uv run python scripts/import_track_segments.py            # write sheets that are still unreviewed
    uv run python scripts/import_track_segments.py --check    # report drift, write nothing (exit 1 on drift)
    uv run python scripts/import_track_segments.py --only 17  # one layout

Input: ``src/pitwall/trackdata/third_party/pits_n_giggles/track-segments/*.json`` (MIT, pinned commit, see
PROVENANCE.md there). Output: ``src/pitwall/trackdata/track_sheets/f1/<NN>_<slug>.toml``, one per F1 track id,
validated with ``pitwall.analysis.track_identity.parse_sheet_text`` before anything is written.

What the conversion does (and deliberately does not do):

- Corner and complex segments become ``[[turns]]`` with their numbers, window and name. Straights are dropped
  (no identity to attach). ``official_turn_count`` is the highest number PnG uses - *not* an official count.
- Everything is ``verified = false`` and ``voice_ok = false``, names are ``kind = "unclassified"``: seeding is
  not review, and the runtime attaches only verified turns (``track_identity.DEFAULT_MIN_TIER``), so a seeded
  sheet changes nothing the driver sees or hears. A maintainer reviews a sheet by hand (FIA map, recorded
  telemetry) and then flips the flags.
- Sheets that contain any verified turn are hand-reviewed and are never overwritten (``--force`` overrides).
- Reverse layouts (ids 39-41) get names only: there is no official reverse numbering, and PnG's numbers are
  invented, so they are dropped and unnamed reverse corners are skipped.
- A turn number PnG lists twice is ambiguous (which segment is the real one?): both entries lose the number
  and are kept only if named. Generic numbered "names" ("Bocht 9") are dropped - they restate a number, and on
  a reverse layout they would smuggle the forward numbering back in.
- A few spelling fixes and per-track review notes (the research flags of
  docs/research/track-knowledge-sources.md section 4) are pitwall curation, listed below and recorded in the
  sheet so the provenance stays visible.

No third-party code is used; the JSON is read as data with the stdlib.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from pitwall.adapters.f1.enums import TRACKS
from pitwall.analysis.track_identity import SheetError, parse_sheet_text
from pitwall.trackdata import PITS_N_GIGGLES_COMMIT, PITS_N_GIGGLES_SOURCE

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "pitwall" / "trackdata"
PNG_SEGMENTS = DATA / "third_party" / "pits_n_giggles" / "track-segments"
OUT_DIR = DATA / "track_sheets" / "f1"

GAMES = ["f1_25"]  # the segment metres are F1 25 lap distances (Austria/Bahrain checked against real captures)
REVERSE_OF = {39: 7, 40: 17, 41: 26}  # F1 25 reverse layout id -> forward layout id (enums.TRACKS)
GENERIC_NAME = re.compile(r"^(?:bocht|turn|curva|virage|kurve|corner)\s*\d+[a-z]?$", re.IGNORECASE)
SPELLING_FIXES = {  # PnG text -> pitwall text (obvious misspellings only; recorded in the turn notes)
    "Maggots & Becketts": "Maggotts & Becketts",
    "Fagnes Chicaine": "Fagnes Chicane",
    "Nouvelle Chicaine": "Nouvelle Chicane",
    "Wall Of Champions": "Wall of Champions",
}
REVIEW_NOTES = {  # track id -> what a reviewer must resolve (research doc sections 1 and 4 + import findings)
    0: "PnG release-v5.0.0 renumbered Albert Park to the 2022+ layout (turns 1-14, Ascari = T11); numbers, names "
    "and windows are not yet checked against the FIA map or a capture.",
    4: "Catalunya names are sponsor/historic names that change by season - classify before voicing.",
    5: "PnG track_length 3067 m is truncated (the F1 25 lap is probably about 3323 m; unverified) and turns 17-19 "
    "are mislabelled (research Action 2): the length gate refuses this sheet if the game reports another length. "
    "Never rescale these windows - fix them from a capture.",
    6: "PnG release-v5.0.0 fixed the duplicate turn 5, the missing turn 11 and the Wall of Champions numbering "
    "(13-14); not yet checked against the FIA map or a capture.",
    7: "Check Chapel = T14 against the FIA map.",
    9: "PnG names include the 2026 renames (Piquet, Hamilton, ...); F1 25's base season is 2025 - check before "
    "voicing.",
    11: "'Parabolica' is officially 'Curva Alboreto' (alias) - classify before voicing.",
    13: "PnG numbers turns 1-17; FIA/F1DB list 18 turns: turn 18 is folded into the pit straight (research "
    "Action 2). 'Casio Triangle' is the old chicane name.",
    19: "PnG lap length 4525 m vs 4304 m for the real circuit: probably F1 25's own m_trackLength (research "
    "section 4; unverified) - confirm against a capture.",
    20: "PnG's highest number is 16; the Baku layout has 20 official turns: turns 17-20 (flat kinks after turn 16) "
    "are missing (research Action 2) - add them after review.",
    42: "The FIA 2026 map numbers 22 turns plus sub-turns 5A and 20A, which PnG's integer schema cannot represent: "
    'after review add each as its own [[turns]] entry with numbers = [5] / [20] and label = "T5a" / "T20a", '
    "directly after turn 5 / turn 20.",
}
HEADER = """\
# Pitwall track sheet: corner identity (layer L2) for one game layout.
# Schema and rules: src/pitwall/analysis/track_identity.py.
# Seeded by scripts/import_track_segments.py from Pits n' Giggles assets/track-segments ({source}), MIT licence,
# Copyright (c) 2024 Ashwin Natarajan - see src/pitwall/trackdata/third_party/pits_n_giggles/.
# NOT hand-reviewed: every turn is verified = false and names are unclassified, so pitwall attaches nothing from
# this sheet at runtime (identity min tier sheet_verified). Review by hand (FIA circuit map, recorded game
# telemetry) before setting verified / voice_ok; the importer then leaves this file alone.
"""


def q(s: str) -> str:
    """A TOML basic string (JSON string escapes are a subset of TOML's)."""
    return json.dumps(s, ensure_ascii=False)


def num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def slug(circuit_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", circuit_name.lower()).strip("_")


def convert(doc: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """PnG JSON -> (file name, sheet dict in schema order)."""
    track_no = int(doc["circuit_number"])
    if track_no not in TRACKS:
        raise SystemExit(f"{doc['circuit_name']}: unknown F1 track id {track_no}")
    reverse_of = REVERSE_OF.get(track_no)
    corners = [s for s in doc["segments"] if s["type"] in ("corner", "complex_corner")]
    unknown = {s["type"] for s in doc["segments"]} - {"corner", "complex_corner", "straight"}
    if unknown:
        raise SystemExit(f"{doc['circuit_name']}: unknown segment types {sorted(unknown)}")

    def numbers_of(seg: dict[str, Any]) -> list[int]:
        n = seg.get("corner_numbers", seg.get("corner_number"))
        return [int(n)] if isinstance(n, int) else [int(x) for x in (n or [])]

    counts = Counter(n for s in corners for n in numbers_of(s))
    dup = sorted(n for n, k in counts.items() if k > 1)
    notes: list[str] = []
    if REVIEW_NOTES.get(track_no):
        notes.append(REVIEW_NOTES[track_no])
    turns: list[dict[str, Any]] = []
    for seg in corners:
        numbers = numbers_of(seg)
        turn_notes: list[str] = []
        if reverse_of is not None:
            numbers = []
        elif any(n in dup for n in numbers):
            turn_notes.append(f"PnG lists turn {'/'.join(map(str, numbers))} more than once; number dropped.")
            numbers = []
        raw_name = str(seg.get("name") or "").strip()
        name = SPELLING_FIXES.get(raw_name, raw_name)
        if name != raw_name:
            turn_notes.append(f"Name spelling corrected from PnG {raw_name!r}.")
        if name and GENERIC_NAME.match(name):
            turn_notes.append(f"Generic PnG name {name!r} dropped.")
            name = ""
        if not numbers and not name:
            continue  # nothing to identify it by
        turn: dict[str, Any] = {}
        if numbers:
            turn["numbers"] = numbers
        if name:
            turn["names"] = [{"text": name, "kind": "unclassified"}]
        turn["game_segment_m"] = [seg["start_m"], seg["end_m"]]
        turn["voice_ok"] = False
        turn["verified"] = False
        turn["sources"] = [PITS_N_GIGGLES_SOURCE]
        if turn_notes:
            turn["notes"] = " ".join(turn_notes)
        turns.append(turn)

    max_no = max((n for t in turns for n in t.get("numbers", [])), default=0)
    if reverse_of is not None:
        notes.append(
            "Reverse layout: there is no official numbering, so PnG's numbers are dropped and only names are "
            "kept (they name the same physical corners driven the other way). PnG's reverse windows look like "
            "mirrored forward windows, so check them against recorded reverse laps before verifying."
        )
    notes.append(
        "official_turn_count is the highest turn number PnG uses, not checked against an official source."
        if reverse_of is None
        else "official_turn_count = 0: reverse layouts are not officially numbered."
    )
    if dup:
        notes.append(f"Turn number(s) {dup} appear more than once in PnG.")
    sheet: dict[str, Any] = {
        "schema_version": 1,
        "game_family": "f1",
        "games": GAMES,
        "game_track_id": track_no,
        "layout": TRACKS[track_no],
        "lap_length_m": doc["track_length"],
        "official_turn_count": 0 if reverse_of is not None else max_no,
    }
    if reverse_of is not None:
        sheet["reverse_of"] = reverse_of
    sectors = doc.get("sectors") or {}
    if isinstance(sectors.get("s1"), int | float) and isinstance(sectors.get("s2"), int | float):
        sheet["sector_starts_m"] = [sectors["s1"], sectors["s2"]]
    sheet["sources"] = [PITS_N_GIGGLES_SOURCE]
    sheet["notes"] = " ".join(notes)
    sheet["turns"] = turns
    return f"{track_no:02d}_{slug(str(doc['circuit_name']))}.toml", sheet


def render(sheet: dict[str, Any]) -> str:
    def value(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int | float):
            return num(v)
        if isinstance(v, str):
            return q(v)
        if isinstance(v, list):
            return "[" + ", ".join(value(x) for x in v) + "]"
        if isinstance(v, dict):
            return "{ " + ", ".join(f"{k} = {value(x)}" for k, x in v.items()) + " }"
        raise TypeError(type(v))

    lines = [HEADER.format(source=f"{PITS_N_GIGGLES_SOURCE}, commit {PITS_N_GIGGLES_COMMIT}")]
    lines += [f"{k} = {value(v)}" for k, v in sheet.items() if k != "turns"]
    for t in sheet["turns"]:
        lines.append("")
        lines.append("[[turns]]")
        lines += [f"{k} = {value(v)}" for k, v in t.items()]
    return "\n".join(lines) + "\n"


def reviewed(path: Path) -> bool:
    """A sheet with any verified turn has been reviewed by hand and must not be regenerated."""
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return any(isinstance(t, dict) and t.get("verified") is True for t in doc.get("turns", []))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report drift against the files on disk; write nothing")
    ap.add_argument("--force", action="store_true", help="also overwrite hand-reviewed sheets")
    ap.add_argument("--only", type=int, action="append", help="F1 track id(s) to process")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args()

    drift = 0
    for src in sorted(PNG_SEGMENTS.glob("*.json")):
        doc = json.loads(src.read_text(encoding="utf-8"))
        if a.only and int(doc["circuit_number"]) not in a.only:
            continue
        name, sheet = convert(doc)
        text = render(sheet)
        try:
            parse_sheet_text(text, name)
        except SheetError as e:
            print(f"INVALID {name}: {e}", file=sys.stderr)
            return 2
        dest = a.out / name
        if dest.exists() and reviewed(dest) and not a.force:
            print(f"keep     {name} (hand-reviewed)")
            continue
        same = dest.exists() and dest.read_text(encoding="utf-8") == text
        if a.check:
            if not same:
                drift += 1
                print(f"drift    {name}")
            continue
        if same:
            print(f"same     {name}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"wrote    {name} ({len(sheet['turns'])} turns)")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
