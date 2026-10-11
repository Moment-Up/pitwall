"""The weekly digest: one driver's week (Monday 00:00 to the next Monday, server local time), pure.

Sessions with at least one timed lap; totals against the week before; the best improvements (per game + track + car:
this week's best against the best before the week, faster only; then tracks driven for the first time); goals
reached this week and how far the active ones moved; badges earned this week; streaks as at the end of the week. The
same content as Markdown (``markdown``) and as a printable page (``motivation.html``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from pitwall.motivation import badges as B
from pitwall.motivation import goals as G
from pitwall.motivation import rules
from pitwall.motivation.model import (
    GoalRow,
    History,
    LapRow,
    Scope,
    SessionRow,
    gap_s,
    lap_time,
    short_date,
    week_range_text,
)

MAX_GAINS = 3
MAX_NEW_TRACKS = 3
_MD_SPECIAL = str.maketrans({c: f"\\{c}" for c in "*_[]#`"})


def md_escape(text: str) -> str:
    """Names are user input: escape Markdown emphasis, links and headings."""
    return text.translate(_MD_SPECIAL)


def week_bounds(week_start: date) -> tuple[float, float]:
    """Unix times of Monday 00:00 and the next Monday 00:00, local time (a clock change does not move them)."""
    start = datetime.combine(week_start, time()).timestamp()
    end = datetime.combine(week_start + timedelta(7), time()).timestamp()
    return start, end


@dataclass(slots=True, frozen=True)
class _Counts:
    sessions: int
    laps: int
    clean_laps: int
    lap_time_ms: int
    tracks: int


def _counts(history: History, sessions: Sequence[SessionRow]) -> _Counts:
    laps = [lap for s in sessions for lap in rules.timed(history.laps_of(s.id))]
    return _Counts(
        sessions=len(sessions),
        laps=len(laps),
        clean_laps=sum(1 for lap in laps if lap.clean),
        lap_time_ms=sum(lap.lap_time_ms or 0 for lap in laps),
        tracks=len({(s.game, s.track_id) for s in sessions if s.track_id is not None}),
    )


def _in(history: History, start: float, end: float) -> list[SessionRow]:
    return [
        s for s in history.sessions if start <= s.started_unix < end and rules.is_timed_session(history.laps_of(s.id))
    ]


def _duration(ms: int) -> str:
    minutes = round(ms / 60_000)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def improvements(history: History, start: float, end: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(gains, first_tracks)``: per game + track + car, this week's best against the best before the week (faster
    only, biggest gain first); and every track with a first clean lap this week (in the order first driven)."""
    before: dict[tuple[str, str, str | None], int] = {}
    tracks_before: set[tuple[str, str]] = set()
    week: dict[tuple[str, str, str | None], tuple[SessionRow, LapRow]] = {}
    for s in history.sessions:
        key = s.pb_key
        if key is None or s.started_unix >= end:
            continue
        best = rules.fastest_clean(history.laps_of(s.id))
        if best is None or best.lap_time_ms is None:
            continue
        if s.started_unix < start:
            before[key] = min(before.get(key, best.lap_time_ms), best.lap_time_ms)
            tracks_before.add((key[0], key[1]))
            continue
        have = week.get(key)
        if have is None or best.lap_time_ms < (have[1].lap_time_ms or 0):
            week[key] = (s, best)
    gains: list[dict[str, Any]] = []
    new_tracks: dict[tuple[str, str], dict[str, Any]] = {}
    first_seen: dict[tuple[str, str], int] = {}
    for key, (s, lap) in sorted(week.items(), key=lambda kv: kv[1][0].started_unix):
        assert lap.lap_time_ms is not None
        scope = Scope(game=s.game, track_id=s.track_id, track_name=s.track_name, car_id=s.car_id, car_name=s.car_name)
        prev = before.get(key)
        item = {
            "scope": scope.to_dict(),
            "scope_text": scope.text() or s.track_id or "",
            "before_ms": prev,
            "best_ms": lap.lap_time_ms,
            "gain_ms": None,
            "new_track": False,
            "session_id": s.id,
            "lap_id": lap.id,
        }
        if prev is not None and lap.lap_time_ms < prev:
            gains.append({**item, "gain_ms": prev - lap.lap_time_ms})
        track = (key[0], key[1])
        first_seen.setdefault(track, len(first_seen))
        if track not in tracks_before:
            have_new = new_tracks.get(track)
            if have_new is None or lap.lap_time_ms < have_new["best_ms"]:
                track_scope = Scope(game=s.game, track_id=s.track_id, track_name=s.track_name)
                new_tracks[track] = {
                    **item,
                    "scope": track_scope.to_dict(),
                    "scope_text": track_scope.text() or s.track_id or "",
                    "new_track": True,
                }
    gains.sort(key=lambda d: (-d["gain_ms"], d["scope_text"]))
    order = {s.id: i for i, s in enumerate(history.sessions)}

    def seen(d: dict[str, Any]) -> tuple[int, int]:
        return first_seen.get((d["scope"]["game"], d["scope"]["track_id"]), 0), order.get(d["session_id"], 0)

    firsts = sorted(new_tracks.values(), key=seen)
    return gains, firsts


def _headline(counts: _Counts, gains: Sequence[dict[str, Any]], firsts: Sequence[dict[str, Any]]) -> tuple[str, str]:
    if counts.sessions == 0:
        return "No driving this week.", "No driving this week."
    parts = [
        f"{counts.sessions} session{'s' if counts.sessions != 1 else ''}",
        f"{counts.laps} lap{'s' if counts.laps != 1 else ''}",
    ]
    if len(gains) == 1:
        parts.append(f"a new best at {gains[0]['scope']['track_name'] or gains[0]['scope_text']}")
    elif gains:
        parts.append(f"new bests at {len(gains)} tracks")
    elif len(firsts) == 1:
        parts.append(f"first laps at {firsts[0]['scope']['track_name'] or firsts[0]['scope_text']}")
    elif firsts:
        parts.append(f"first laps at {len(firsts)} tracks")
    n = counts.sessions
    return ", ".join(parts), f"You drove {n} time{'s' if n != 1 else ''} this week"


def build_digest(
    driver: dict[str, Any],
    history: History,
    goals: Sequence[GoalRow],
    week_start: date,
    now_unix: float,
    *,
    include_synthetic: bool,
    goal_json: Callable[[GoalRow, History], dict[str, Any]],
) -> dict[str, Any]:
    """The ``WeeklyDigest`` object (``history`` = the driver's driving, ``goal_json`` = the API goal shape)."""
    start, end = week_bounds(week_start)
    as_of = min(end - 0.001, now_unix)
    sessions = _in(history, start, end)
    counts = _counts(history, sessions)
    prev = _counts(history, _in(history, *week_bounds(week_start - timedelta(7))))
    gains, firsts = improvements(history, start, end)
    items = gains[:MAX_GAINS] + firsts[:MAX_NEW_TRACKS]
    simple = driver.get("skill_level") == "beginner"
    headline, headline_simple = _headline(counts, gains, firsts)
    rows = []
    order = {x.id: i for i, x in enumerate(history.sessions)}
    for s in sessions:
        laps = rules.timed(history.laps_of(s.id))
        best = rules.fastest_clean(laps)
        key = s.pb_key
        prior = [x for x in history.sessions[: order[s.id]] if x.pb_key == key and key is not None]
        prior_best = rules.fastest_clean(lap for x in prior for lap in history.laps_of(x.id))
        rows.append(
            {
                "session_id": s.id,
                "started_unix": s.started_unix,
                "game": s.game,
                "track_name": s.track_name,
                "car_name": s.car_name,
                "session_type": s.session_type,
                "laps": len(laps),
                "clean_laps": sum(1 for lap in laps if lap.clean),
                "best_clean_ms": None if best is None else best.lap_time_ms,
                "pb": best is not None
                and prior_best is not None
                and (best.lap_time_ms or 0) < (prior_best.lap_time_ms or 0),
                "synthetic": s.synthetic,
            }
        )
    upto = history.before(as_of + 0.001)
    achieved = [g for g in goals if g.achieved_unix is not None and start <= g.achieved_unix < end]
    active = []
    for g in goals:
        if g.status != "active" or g.created_unix >= end:
            continue
        frm = G.progress(g, history.before(start)).fraction
        to = G.progress(g, upto).fraction
        active.append({"goal": goal_json(g, history), "from_fraction": frm, "to_fraction": to})
    earned = [b for b in B.badges(upto, goals) if start <= b.earned_unix < end]
    streaks = B.streaks(history, as_of)
    out: dict[str, Any] = {
        "driver": {"id": driver["id"], "name": driver["name"], "skill_level": driver.get("skill_level")},
        "simple": simple,
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(6)).isoformat(),
        "is_current_week": rules.week_of(now_unix) == week_start,
        "generated_unix": now_unix,
        "include_synthetic": include_synthetic,
        "totals": {
            "sessions": counts.sessions,
            "laps": counts.laps,
            "clean_laps": counts.clean_laps,
            "lap_time_s": round(counts.lap_time_ms / 1000, 3),
            "tracks": counts.tracks,
        },
        "previous_week": {"sessions": prev.sessions, "laps": prev.laps, "clean_laps": prev.clean_laps},
        "headline": headline,
        "headline_simple": headline_simple,
        "sessions": rows,
        "improvements": items,
        "goals": {"achieved": [goal_json(g, history) for g in achieved], "active": active},
        "badges": [b.to_dict() for b in earned],
        "streaks": streaks,
    }
    out["markdown"] = markdown(out)
    return out


# ---------------------------------------------------------------------------------------------- markdown
def possessive(name: str) -> str:
    return f"{name}'s"


def totals_line(d: dict[str, Any]) -> str:
    t = d["totals"]
    if not t["sessions"]:
        return "No driving this week."
    parts = [
        f"{t['sessions']} session{'s' if t['sessions'] != 1 else ''}",
        f"{t['laps']} timed lap{'s' if t['laps'] != 1 else ''} ({t['clean_laps']} clean)",
        f"{_duration(round(t['lap_time_s'] * 1000))} of timed laps",
        f"{t['tracks']} track{'s' if t['tracks'] != 1 else ''}",
    ]
    p = d["previous_week"]
    parts.append(f"week before: {p['sessions']} session{'s' if p['sessions'] != 1 else ''}, {p['laps']} laps")
    return " · ".join(parts)


def session_line(r: dict[str, Any]) -> str:
    bits = [short_date(r["started_unix"]), r["track_name"] or "unknown track"]
    if r["car_name"]:
        bits.append(r["car_name"])
    if r["session_type"] and r["session_type"] != "unknown":
        bits.append(str(r["session_type"]).replace("_", " ").capitalize())
    bits.append(f"{r['laps']} lap{'s' if r['laps'] != 1 else ''} ({r['clean_laps']} clean)")
    if r["best_clean_ms"] is not None:
        bits.append(f"best {lap_time(r['best_clean_ms'])}" + (" (new best)" if r["pb"] else ""))
    if r["synthetic"]:
        bits.append("synthetic")
    return " · ".join(bits)


def improvement_line(i: dict[str, Any]) -> str:
    if i["gain_ms"] is not None:
        return f"{i['scope_text']}: {lap_time(i['best_ms'])}, {gap_s(i['gain_ms'])} s faster than before"
    return f"First clean laps at {i['scope_text']}: {lap_time(i['best_ms'])}"


def goal_line(goal: dict[str, Any], simple: bool, frm: float | None = None, to: float | None = None) -> str:
    title = goal["title_simple"] if simple else goal["title"]
    where = f" ({goal['scope_text']})" if goal.get("scope_text") else ""
    if goal.get("achieved"):
        a = goal["achieved"]
        return f"Reached: {title}{where}, {short_date(a['unix'])}"
    p = goal["progress"]
    moved = ""
    if frm is not None and to is not None and to > frm:
        moved = f" (from {round(frm * 100)} % to {round(to * 100)} %)"
    return f"{title}{where}: {p['text_simple'] if simple else p['text']}{moved}"


def markdown(d: dict[str, Any]) -> str:
    name = md_escape(str(d["driver"]["name"]))
    start = date.fromisoformat(d["week_start"])
    end = date.fromisoformat(d["week_end"])
    simple = bool(d["simple"])
    lines = [f"# {possessive(name)} week: {week_range_text(start, end)}", "", totals_line(d), ""]
    lines.append("## Sessions")
    lines += [f"- {md_escape(session_line(r))}" for r in d["sessions"]] or ["- None this week."]
    lines += ["", "## Best improvements"]
    lines += [f"- {md_escape(improvement_line(i))}" for i in d["improvements"]] or ["- None this week."]
    lines += ["", "## Goals"]
    goal_lines = [f"- {md_escape(goal_line(g, simple))}" for g in d["goals"]["achieved"]]
    goal_lines += [
        f"- {md_escape(goal_line(a['goal'], simple, a['from_fraction'], a['to_fraction']))}"
        for a in d["goals"]["active"]
    ]
    lines += goal_lines or ["- No goals set."]
    lines += ["", "## Badges this week"]
    lines += [
        f"- {md_escape(b['title_simple'] if simple else b['title'])} ({short_date(b['earned_unix'])})"
        for b in d["badges"]
    ] or ["- None this week."]
    lines += ["", "## Streaks"]
    lines += [f"- {md_escape(x)}" for x in streak_lines(d["streaks"])]
    return "\n".join(lines) + "\n"


def streak_lines(st: dict[str, Any]) -> list[str]:
    w = st["weekly"]
    c = st["clean_laps"]
    out = [
        f"Weeks in a row with a session: {w['current_weeks']} (best {w['best_weeks']})",
        f"Best run of clean laps: {c['best']}",
    ]
    for p in st["pb"]:
        n = p["current_sessions"]
        out.append(
            f"New best in a row at {p['scope_text']}: {n} session{'s' if n != 1 else ''} (best {p['best_sessions']})"
        )
    return out
