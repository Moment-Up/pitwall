"""The engineer's family-record fact (topic ``records``), deterministic.

``add_record_facts`` appends one fact to a fact sheet: the family record of the board the session drives on
(``service.session_board``: same game, track, layout, car, session category, conditions and assists), who holds it,
the other drivers' gaps, and where the session's own driver stands. Called by ``motivation.facts
.add_motivation_facts``, so the API's ask / facts endpoints, the radio's fact sheet and ``pitwall ask`` all get it. It
opens its own read connection and never breaks an answer (errors are logged and swallowed). Nothing for a synthetic
session or one without a track. Household names go in the fact like the rest of the sheet (a cloud provider gets
them redacted, ``ai.provider_registry``). Every number in ``say`` is in ``text`` or ``data`` (``check_grounding``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pitwall.ai.facts import FactSheet, fmt_lap
from pitwall.leaderboard import board as B
from pitwall.leaderboard import keys as K
from pitwall.leaderboard import service
from pitwall.storage.db import Database

if TYPE_CHECKING:
    from pitwall.core.session_analysis import SessionAnalysis

log = logging.getLogger(__name__)

TOPIC = "records"
OTHERS_LISTED = 3
NO_RECORD_SAY = "There's no family record here yet: the first clean lap sets it."


def add_record_facts(sheet: FactSheet, db: Database, sa: SessionAnalysis) -> None:
    try:
        _add(sheet, db, sa)
    except Exception:
        log.exception("family record facts failed (answer continues without them)")


def _add(sheet: FactSheet, db: Database, sa: SessionAnalysis) -> None:
    s = sa.session
    if s.get("synthetic"):
        return
    with db.read() as c:
        found = service.session_board(c, s, sa.laps)
    if found is None:
        return
    key, view = found
    driver_id = (sa.driver or {}).get("id")
    if view is None or not view.get("rows"):
        lab = B.labels(key, K.raw_of_session(s))
        sheet.add(
            TOPIC,
            f"Family record on this board ({lab['title']}; {lab['assists_text']}): none yet; the first clean, valid "
            "lap of real driving sets it.",
            {"drivers_on_board": 0, "board": key.encode()},
            say=NO_RECORD_SAY,
        )
        return
    lab = view["labels"]
    rows: list[dict[str, Any]] = view["rows"]
    rec = rows[0]
    ms = int(rec["lap_ms"])
    text = (
        f"Family record on this board ({lab['title']}; {lab['assists_text']}): {fmt_lap(ms)} by "
        f"{rec['driver_name']}, set {rec['date_text']}."
    )
    others = [f"{r['driver_name']} {fmt_lap(r['lap_ms'])} ({r['gap_ms'] / 1000:.3f}s behind)" for r in rows[1:]]
    if others:
        text += " Others: " + "; ".join(others[:OTHERS_LISTED]) + "."
    data: dict[str, Any] = {"record_s": ms / 1000, "drivers_on_board": len(rows), "board": view["key"]}
    mine = next((r for r in rows if driver_id is not None and r["driver_id"] == driver_id), None)
    if mine is not None and mine["leader"]:
        say = f"You hold the family record here: {fmt_lap(ms)}."
    elif mine is not None:
        gap = int(mine["gap_ms"]) / 1000
        data["gap_s"] = gap
        if mine not in rows[1 : 1 + OTHERS_LISTED]:
            text += f" {mine['driver_name']}'s best here is {gap:.3f}s behind."
        say = f"The family record here is {fmt_lap(ms)}, by {rec['driver_name']}. Your best here is {gap:.3f}s off it."
    else:
        say = f"The family record here is {fmt_lap(ms)}, by {rec['driver_name']}."
    sheet.add(TOPIC, text, data, say=say)
