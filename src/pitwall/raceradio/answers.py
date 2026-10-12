"""Deterministic radio answers for the race questions: who is ahead / behind, the position (any game), penalties,
damage and sector deltas. No LLM: every number comes from a fact's data (``ai.facts`` topic ``race``, built from the
live snapshot's ``race`` block, and the lap facts' ``sectors_ms``), so the answers are grounded by construction.
Labels are the race radio's non-personal ones (``raceradio.roster``): an official AI driver name, a team, "car 23" or
"the car ahead"; never an online ID.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pitwall.raceradio.wording import WHEEL_WORDS, cap, part_words

if TYPE_CHECKING:
    from pitwall.ai.facts import FactSheet

RACE_TOPIC = "race"
_BEHIND = re.compile(r"\b(behind|chasing|following)\b", re.I)
_LEAD = re.compile(r"\b(leading|in the lead|leader)\b", re.I)
_SECTOR = re.compile(r"\bsector\s*(1|2|3|one|two|three)\b", re.I)
_SECTOR_WORDS = {"1": 1, "2": 2, "3": 3, "one": 1, "two": 2, "three": 3}


def race_fact(sheet: FactSheet, kind: str) -> dict[str, Any] | None:
    for f in sheet.facts:
        if f.topic == RACE_TOPIC and f.data.get("kind") == kind:
            return f.data
    return None


def _gap_words(gap: object) -> str | None:
    return f"{gap:.1f} seconds" if isinstance(gap, int | float) and not isinstance(gap, bool) else None


def neighbour_text(d: Mapping[str, Any], side: str) -> str:
    """ "Norris is ahead, P4, 1.2 seconds." / "The car ahead is P4." from an ``ahead`` / ``behind`` fact's data."""
    label = str(d.get("label") or f"the car {side}")
    kind = d.get("label_kind")
    pos = d.get("position")
    gap = _gap_words(d.get("gap_s"))
    where = "ahead" if side == "ahead" else "behind"
    named = kind in ("driver", "team", "number", "name")
    shown = cap(label) if kind in ("team", "number") else label  # a name keeps its own spelling
    head = f"{shown} is {where}" if named else f"The car {where}"
    parts = [head]
    if isinstance(pos, int):
        parts.append(f"P{pos}")
    if gap is not None:
        parts.append(gap)
    if len(parts) == 1:
        return f"{head}."
    if not named:
        return f"The car {where} is " + ", ".join(parts[1:]) + "."
    return ", ".join(parts) + "."


def who(sheet: FactSheet, question: str | None = None) -> str | None:
    """ "Norris is ahead, P4, 1.2 seconds." / behind; at the front: "You're leading, 2.4 seconds clear." """
    pos = race_fact(sheet, "position")
    me = None if pos is None else pos.get("position")
    q = question or ""
    if me == 1 and (_LEAD.search(q) or not _BEHIND.search(q)):
        behind = race_fact(sheet, "behind")
        gap = None if behind is None else _gap_words(behind.get("gap_s"))
        return f"You're leading, {gap} clear." if gap else "You're leading."
    side = "behind" if _BEHIND.search(q) else "ahead"
    d = race_fact(sheet, side)
    if d is None:
        return None  # no field data (GT7, Forza): the game's capability sentence answers
    return neighbour_text(d, side)


def position(sheet: FactSheet) -> str | None:
    """ "P5 of 14, 3 laps to go." (+ GT7 / Forza: the evidence note)."""
    d = race_fact(sheet, "position")
    if d is None or not isinstance(d.get("position"), int):
        return None
    msg = f"P{d['position']}" + (f" of {d['cars']}" if isinstance(d.get("cars"), int) else "")
    laps = d.get("laps_to_go")
    if isinstance(laps, int) and laps > 1:
        msg += f", {laps} laps to go"
    elif laps == 1:
        msg += ", last lap"
    msg += "."
    note = d.get("note")
    if isinstance(note, str) and note:
        msg += f" {note}"
    return msg


def penalties(sheet: FactSheet) -> str | None:
    """ "5 seconds of penalties, 2 warnings, 1 for track limits." / "No penalties and no warnings." """
    d = race_fact(sheet, "penalties")
    if d is None:
        return None
    time_s, warnings, limits = d.get("time_s"), d.get("warnings"), d.get("track_limits")
    dts, sgs = d.get("drive_throughs"), d.get("stop_gos")
    parts: list[str] = []
    if isinstance(dts, int) and dts > 0:
        parts.append("a drive-through to serve" if dts == 1 else f"{dts} drive-throughs to serve")
    if isinstance(sgs, int) and sgs > 0:
        parts.append("a stop-go to serve" if sgs == 1 else f"{sgs} stop-gos to serve")
    if isinstance(time_s, int) and time_s > 0:
        parts.append(f"{time_s} seconds of penalties")
    if isinstance(warnings, int) and warnings > 0:
        w = "1 warning" if warnings == 1 else f"{warnings} warnings"
        if isinstance(limits, int) and limits > 0:
            w += f", {limits} for track limits"
        parts.append(w)
    if not parts:
        return "No penalties and no warnings."
    return cap(", ".join(parts)) + "."


def damage(sheet: FactSheet) -> str | None:
    """ "Front wing, left, major. Puncture, rear left." / "No damage." """
    d = race_fact(sheet, "damage")
    if d is None:
        return None
    out: list[str] = []
    for w in d.get("puncture") or []:
        if w in WHEEL_WORDS:
            out.append(f"Puncture, {WHEEL_WORDS[w]}.")
    for p in (d.get("parts") or [])[:3]:
        if isinstance(p, Mapping) and isinstance(p.get("part"), str) and isinstance(p.get("grade"), str):
            try:
                words = part_words(p["part"])
            except KeyError:
                continue
            out.append(f"{cap(words)} damage, {p['grade']}.")
    return " ".join(out) if out else "No damage."


def _sector_s(ms: int) -> str:
    return f"{ms / 1000:.2f}" if ms < 60_000 else f"{ms // 60_000}:{(ms % 60_000) / 1000:05.2f}"


def _delta(ms: int, best: int) -> str:
    d = (ms - best) / 1000
    mag = f"{abs(d):.2f}"
    if mag == "0.00":
        return "level with your best"
    return f"{'plus' if d > 0 else 'minus'} {mag} to your best"


def sector(sheet: FactSheet, question: str | None = None) -> str | None:
    """The last completed lap's sectors against the session's best clean sectors (the lap facts' data): "Sector 2,
    31.55: plus 0.21 to your best." / "Sectors: plus 0.10, minus 0.05, plus 0.30." None without sector times."""
    from pitwall.ai.facts import LAST_LAP_PREFIX

    last = next((f for f in sheet.facts if f.topic == "laps" and f.text.startswith(LAST_LAP_PREFIX)), None)
    if last is None:
        return None
    n = last.data.get("lap")
    lap = next(
        (f for f in sheet.facts if f.topic == "laps" and f.data.get("lap") == n and "sectors_ms" in f.data), None
    )
    best_f = next((f for f in sheet.facts if f.topic == "laps" and "best_sectors_ms" in f.data), None)
    secs = None if lap is None else lap.data.get("sectors_ms")
    best = None if best_f is None else best_f.data.get("best_sectors_ms")
    if not isinstance(secs, list) or len(secs) != 3 or not all(isinstance(x, int) and x > 0 for x in secs):
        return None
    m = _SECTOR.search(question or "")
    if m is not None:
        k = _SECTOR_WORDS[m.group(1).lower()] - 1
        msg = f"Sector {k + 1}, {_sector_s(secs[k])}"
        if isinstance(best, list) and len(best) == 3 and isinstance(best[k], int) and best[k] > 0:
            msg += f": {_delta(secs[k], best[k])}"
        return msg + "."
    if not (isinstance(best, list) and len(best) == 3 and all(isinstance(x, int) and x > 0 for x in best)):
        return "Sectors: " + ", ".join(_sector_s(x) for x in secs) + "."
    deltas = [
        _delta(x, b).replace(" to your best", "").replace("level with your best", "level")
        for x, b in zip(secs, best, strict=True)
    ]
    return "Sectors: " + ", ".join(deltas) + " to your best."
