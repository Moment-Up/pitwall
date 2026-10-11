"""Engineer facts about goals and progress (topics ``goals`` and ``progress``), deterministic.

``add_motivation_facts`` appends to a fact sheet built by ``ai.facts.build_fact_sheet`` (which is not edited): the
API's ask/facts endpoints, the radio's fact sheet and ``pitwall ask`` call it right after building the sheet. It
opens its own read connection, never breaks an answer (every error is logged and swallowed) and adds nothing for a
session without a driver. Times use ``ai.facts.fmt_lap`` in both ``text`` and ``say``, so a deterministic answer
built from ``say`` passes ``check_grounding`` by construction.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from pitwall.ai.facts import FactSheet, fmt_lap
from pitwall.motivation import badges as B
from pitwall.motivation import goals as G
from pitwall.motivation import rules
from pitwall.motivation.model import GoalRow, History, LapRow, SessionRow, local_date, lower_first, seconds, short_date
from pitwall.motivation.service import load_history
from pitwall.storage import repo
from pitwall.storage.db import Database

if TYPE_CHECKING:
    from pitwall.core.session_analysis import SessionAnalysis

log = logging.getLogger(__name__)

MAX_ACTIVE_FACTS = 3


def _scope_words(g: GoalRow) -> tuple[str, str]:
    """(text, say): `` at Austria (Haas)`` / `` at Austria``."""
    track = g.scope.track_label
    car = g.scope.car_label
    if not track:
        return "", ""
    return (f" at {track} ({car})" if car else f" at {track}"), f" at {track}"


def _value(g: GoalRow, v: float) -> str:
    if g.kind == "lap_time":
        return fmt_lap(round(v))
    if g.kind == "consistency":
        return f"within {seconds(v, tenths_when_whole=False)}s"
    if g.kind == "clean_streak":
        return f"{round(v)} clean laps in a row"
    return "a clean race"


def _reached_fact(sheet: FactSheet, g: GoalRow, name: str, lap_number: int | None) -> None:
    title = lower_first(G.goal_titles(g)[0])
    if g.kind == "lap_time":
        title = f"a lap under {fmt_lap(round(g.target))}"
    where_text, where_say = _scope_words(g)
    v = g.achieved_value
    on = f" on lap {lap_number}" if lap_number is not None else ""
    if v is not None and g.kind in ("lap_time", "consistency"):
        text = f"Goal reached this session by {name}: {title}{where_text}; {_value(g, v)}{on}."
        say = f"Goal reached this session: {title}{where_say}, with {_value(g, v)}{on}."
    else:
        text = f"Goal reached this session by {name}: {title}{where_text}{on}."
        say = f"Goal reached this session: {title}{where_say}{on}."
    data = {"goal_id": g.id, "kind": g.kind, "target": g.target, "value": v, "lap": lap_number}
    sheet.add("goals", text, data, say=say)


def _active_fact(sheet: FactSheet, g: GoalRow, history: History, name: str) -> None:
    title = lower_first(G.goal_titles(g)[0])
    if g.kind == "lap_time":
        title = f"a lap under {fmt_lap(round(g.target))}"
    where_text, where_say = _scope_words(g)
    p = G.progress(g, history)
    since = short_date(g.created_unix)
    data: dict[str, object] = {"goal_id": g.id, "kind": g.kind, "target": g.target, "current": p.current}
    if g.kind == "lap_time" and p.current is not None:
        gap = max(0.0, p.current - g.target) / 1000
        data["to_go_s"] = round(gap, 3)
        text = (
            f"{name}'s goal (active since {since}): {title}{where_text}; best since set {fmt_lap(round(p.current))}, "
            f"{gap:.3f}s to go."
        )
        say = (
            f"Your goal is {title}{where_say}. Your best since you set it is {fmt_lap(round(p.current))}, "
            f"{gap:.3f}s to go."
        )
    elif g.kind == "clean_streak":
        cur = round(p.current or 0)
        text = f"{name}'s goal (active since {since}): {title}{where_text}; best since set {cur} of {round(g.target)}."
        say = f"Your goal is {title}{where_say}. Your best since you set it is {cur} of {round(g.target)}."
    elif g.kind == "consistency" and p.current is not None:
        text = (
            f"{name}'s goal (active since {since}): {title}{where_text}; steadiest since set "
            f"within {seconds(p.current, tenths_when_whole=False)}s."
        )
        say = (
            f"Your goal is {title}{where_say}. Your steadiest laps since you set it were within "
            f"{seconds(p.current, tenths_when_whole=False)}s."
        )
    else:
        text = f"{name}'s goal (active since {since}): {title}{where_text}; {lower_first(p.text)}."
        say = f"Your goal is {title}{where_say}. {p.text_simple}."
    sheet.add("goals", text, data, say=say)


def add_motivation_facts(sheet: FactSheet, db: Database, sa: SessionAnalysis) -> None:
    """Append goal and progress facts for the session's driver (nothing for a session without one)."""
    try:
        _add(sheet, db, sa)
    except Exception:
        log.exception("motivation facts failed (answer continues without them)")


def _add(sheet: FactSheet, db: Database, sa: SessionAnalysis) -> None:
    driver = sa.driver
    if not driver or driver.get("id") is None:
        return
    driver_id = int(driver["id"])
    name = str(driver.get("name") or "The driver")
    sid = str(sa.session.get("id") or "")
    with db.read() as c:
        history = load_history(c, driver_id)
        goals = [G.labelled(GoalRow.from_row(r), history) for r in repo.list_goals(c, driver_id)]
        row = repo.motivation_session(c, sid) if sid else None
        laps_by_id = repo.lap_numbers(c, [g.achieved_lap_id for g in goals if g.achieved_lap_id is not None])
    session = SessionRow.from_row(row) if row is not None else None
    for g in goals:
        if g.achieved_session_id == sid and g.achieved_unix is not None:
            _reached_fact(sheet, g, name, laps_by_id.get(g.achieved_lap_id) if g.achieved_lap_id else None)
    active = [g for g in goals if g.status == "active"]
    if session is not None:
        active.sort(key=lambda g: (not rules.scope_matches(g.scope, session), g.kind != "lap_time", g.id))
    for g in active[:MAX_ACTIVE_FACTS]:
        _active_fact(sheet, g, history, name)
    if not active and not any(g.achieved_session_id == sid for g in goals):
        sheet.add(
            "goals", f"{name} has no active goals.", {"active_goals": 0}, say="You have no goals set at the moment."
        )
    # progress: this week, and clean-lap runs
    now = time.time()
    week = rules.week_start(local_date(now))
    timed = [s for s in history.sessions if rules.is_timed_session(history.laps_of(s.id))]
    this_week = [s for s in timed if rules.week_of(s.started_unix) == week]
    laps = [lap for s in this_week for lap in rules.timed(history.laps_of(s.id))]
    clean = sum(1 for lap in laps if lap.clean)
    n_s, n_l = len(this_week), len(laps)
    sheet.add(
        "progress",
        f"This week (from Monday): {n_s} sessions, {n_l} laps, {clean} clean.",
        {"sessions_this_week": n_s, "laps_this_week": n_l, "clean_laps_this_week": clean},
        say=f"This week: {n_s} sessions and {n_l} laps, {clean} of them clean.",
    )
    streaks = B.streaks(history, now)
    best_ever = int(streaks["clean_laps"]["best"])
    this_session = len(rules.best_run([LapRow.from_row(d) for d in sa.laps if d.get("id") is not None]))
    weeks = int(streaks["weekly"]["current_weeks"])
    sheet.add(
        "progress",
        f"Clean laps in a row: best this session {this_session}, best ever {best_ever}; "
        f"weeks in a row with a session: {weeks}.",
        {"run_this_session": this_session, "run_best": best_ever, "weeks_in_row": weeks},
        say=f"Your best run of clean laps this session was {this_session}; your best ever is {best_ever}.",
    )
