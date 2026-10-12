"""The weekly digest: one driver's week (Monday 00:00 to the next Monday, server local time), pure.

Sessions with at least one timed lap (the counting rule, said wherever a count is shown: "2 sessions with a timed
lap"); totals against the week before; the best improvements (per game + track + car: this week's best against the
best before the week, faster only); new tracks (a first clean lap this week at an identified track, as the first
clean lap badge: the session that first set one there, in its own car, and how much faster that car got there by the
end of the week); goals reached this week and how far the active ones moved; badges earned this week; streaks as at
the end of the week. The same content as Markdown (``markdown``) and as a printable page (``motivation.html``).
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
    count_words,
    display_car,
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
    return f"{minutes // 60} h {minutes % 60} min" if minutes % 60 else f"{minutes // 60} h"


def improvements(history: History, start: float, end: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(gains, new_tracks)``: per game + track + car, this week's best against the best before the week (faster
    only, biggest gain first); and every new track this week, in the order first driven (``_new_tracks``)."""
    before: dict[tuple[str, str, str | None], int] = {}
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
            continue
        have = week.get(key)
        if have is None or best.lap_time_ms < (have[1].lap_time_ms or 0):
            week[key] = (s, best)
    gains: list[dict[str, Any]] = []
    for key, (s, lap) in sorted(week.items(), key=lambda kv: kv[1][0].started_unix):
        assert lap.lap_time_ms is not None
        prev = before.get(key)
        if prev is not None and lap.lap_time_ms < prev:
            item = {**_item(s, lap, prev), "gain_ms": prev - lap.lap_time_ms}
            item["text"] = gain_text(item)
            gains.append(item)
    gains.sort(key=lambda d: (-d["gain_ms"], d["scope_text"]))
    return gains, _new_tracks(history, start, end)


def _new_tracks(history: History, start: float, end: float) -> list[dict[str, Any]]:
    """A track with its first clean lap this week (none there before, in any car; identified tracks and laps of 30 s
    or more only, as the first clean lap badge). The item is the session that first set a clean lap there, its own
    best in its own car (another car's faster lap that week is not "the first clean laps"); ``best_ms`` is that car's
    best there by the end of the week, so "New this week: 1:11.745 -> 1:10.549 (1.2 s faster)"."""
    seen_before: set[tuple[str, str]] = set()
    firsts: dict[tuple[str, str], dict[str, Any]] = {}
    for s in history.sessions:
        if s.started_unix >= end or s.track_id is None or not B.track_badges_allowed(s):
            continue
        best = rules.fastest_clean(B.badge_laps(history.laps_of(s.id)))
        if best is None or best.lap_time_ms is None:
            continue
        track = (s.game, s.track_id)
        if s.started_unix < start:
            seen_before.add(track)
            continue
        if track in seen_before:
            continue
        item = firsts.get(track)
        if item is None:
            item = {**_item(s, best, None), "new_track": True, "first_ms": best.lap_time_ms}
            item.update(best_session_id=s.id, best_lap_id=best.id, week_gain_ms=None)
            firsts[track] = item
        elif s.pb_key == (item["scope"]["game"], item["scope"]["track_id"], item["scope"]["car_id"]):
            if best.lap_time_ms < item["best_ms"]:
                item.update(best_ms=best.lap_time_ms, best_session_id=s.id, best_lap_id=best.id)
                item["week_gain_ms"] = item["first_ms"] - best.lap_time_ms
    out = list(firsts.values())
    for item in out:
        item["text"] = new_track_text(item)
    return out


def _gap_words(ms: int) -> str:
    """A gain in seconds: a tenth from 0.1 s (``1.2``), three decimals below (``0.040``)."""
    return f"{ms / 1000:.1f}" if ms >= 100 else f"{ms / 1000:.3f}"


def gain_text(i: dict[str, Any]) -> str:
    """``1:10.549, 1.196 s faster than before``."""
    return f"{lap_time(i['best_ms'])}, {gap_s(i['gain_ms'])} s faster than before"


def new_track_text(i: dict[str, Any]) -> str:
    """``New this week: 1:11.745 → 1:10.549 (1.2 s faster)``, or ``New this week: 1:11.745``."""
    first, best, gain = i["first_ms"], i["best_ms"], i.get("week_gain_ms")
    if gain:
        return f"New this week: {lap_time(first)} → {lap_time(best)} ({_gap_words(gain)} s faster)"
    return f"New this week: {lap_time(first)}"


def _item(s: SessionRow, lap: LapRow, before_ms: int | None) -> dict[str, Any]:
    scope = Scope(game=s.game, track_id=s.track_id, track_name=s.track_name, car_id=s.car_id, car_name=s.car_label)
    return {
        "scope": scope.to_dict(),
        "scope_text": scope.text() or s.track_name or "this track",
        "before_ms": before_ms,
        "best_ms": lap.lap_time_ms,
        "gain_ms": None,
        "new_track": False,
        "session_id": s.id,
        "lap_id": lap.id,
    }


def sessions_words(n: int) -> str:
    """The counting rule in the words (plan 5.7): ``1 session with a timed lap`` / ``3 sessions with a timed lap``."""
    return f"{count_words(n, 'session')} with a timed lap"


def _track_names(items: Sequence[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for i in items:
        name = str(i["scope"]["track_name"] or i["scope_text"])
        if name not in names:
            names.append(name)
    return names


def _headline(counts: _Counts, gains: Sequence[dict[str, Any]], firsts: Sequence[dict[str, Any]]) -> tuple[str, str]:
    if counts.sessions == 0:
        return "No driving this week.", "No driving this week."
    parts = [sessions_words(counts.sessions), count_words(counts.laps, "lap")]
    gain_tracks, new_tracks = _track_names(gains), _track_names(firsts)
    if len(gain_tracks) == 1:  # two cars at one track are one track
        parts.append(f"a new best at {gain_tracks[0]}")
    elif gain_tracks:
        parts.append(f"new bests at {len(gain_tracks)} tracks")
    elif len(new_tracks) == 1:
        parts.append(f"first laps at {new_tracks[0]}")
    elif new_tracks:
        parts.append(f"first laps at {len(new_tracks)} tracks")
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
                "car_name": display_car(s.car_label),  # "F2 · Art GP '24" (carclass), never a raw id
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
IMPROVEMENTS_TITLE = "Improvements"
NEW_TRACKS_TITLE = "New tracks"


def possessive(name: str) -> str:
    return f"{name}'s"


def headline_text(d: dict[str, Any]) -> str:
    """The headline in the driver's wording, as a sentence."""
    h = str(d["headline_simple"] if d["simple"] else d["headline"])
    return h if h.endswith(".") else h + "."


def totals_line(d: dict[str, Any]) -> str | None:
    """What the headline does not say already (the same words as the dashboard's week card): ``9 clean laps ·
    55 min driving · 2 tracks``; None in an empty week."""
    t = d["totals"]
    if not t["sessions"]:
        return None
    parts = [count_words(t["clean_laps"], "clean lap")]
    if t["lap_time_s"] > 0:
        parts.append(f"{_duration(round(t['lap_time_s'] * 1000))} driving")
    parts.append(count_words(t["tracks"], "track"))
    return " · ".join(parts)


def previous_line(d: dict[str, Any]) -> str | None:
    """``Week before: 3 sessions with a timed lap, 12 laps, 9 clean``; None when it had no driving."""
    p = d["previous_week"]
    if not p["sessions"]:
        return None
    return f"Week before: {sessions_words(p['sessions'])}, {count_words(p['laps'], 'lap')}, {p['clean_laps']} clean"


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
    """``Austria · Haas: 1:10.549, 1.196 s faster than before`` / ``Suzuka · F1 Generic: New this week: 1:36.360``."""
    text = i.get("text") or (new_track_text(i) if i.get("new_track") else gain_text(i))
    return f"{i['scope_text']}: {text}"


def improvement_groups(d: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(improvements, new tracks) as lines, each group in the digest's order."""
    items = d["improvements"]
    return (
        [improvement_line(i) for i in items if not i.get("new_track")],
        [improvement_line(i) for i in items if i.get("new_track")],
    )


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
    lines = [f"# {possessive(name)} week: {week_range_text(start, end)}", ""]
    for x in (headline_text(d), totals_line(d), previous_line(d)):
        if x:
            lines += [md_escape(x), ""]  # one paragraph each
    lines += ["## Sessions"]
    lines += [f"- {md_escape(session_line(r))}" for r in d["sessions"]] or ["- None this week."]
    gains, new_tracks = improvement_groups(d)
    lines += ["", f"## {IMPROVEMENTS_TITLE}"]
    lines += [f"- {md_escape(x)}" for x in gains] or ["- None this week."]
    lines += ["", f"## {NEW_TRACKS_TITLE}"]
    lines += [f"- {md_escape(x)}" for x in new_tracks] or ["- None this week."]
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
        f"Weeks in a row with a timed lap: {w['current_weeks']} (best {w['best_weeks']})",
        f"Best run of clean laps: {c['best']}",
    ]
    for p in st["pb"]:
        n = p["current_sessions"]
        out.append(
            f"New best in a row at {p['scope_text']}: {n} session{'s' if n != 1 else ''} (best {p['best_sessions']})"
        )
    return out
