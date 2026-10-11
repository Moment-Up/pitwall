"""Badges and streaks, worked out in time order from the driver's real driving (pure).

Nothing is stored: a badge's date is when the session that earned it started (``earned_unix``), and its key is
stable, so the same data always gives the same badges. Replays never count; synthetic sessions only when the caller
asks (and such a badge says ``synthetic``).

Track badges (first clean lap, under a time, PB streak) need an identified track (``model.track_identified``: no
``unknown_`` id, no "Unknown track" and no GT7 "Unidentified GT7 circuit (…)" placeholder) and a lap of at least
30 s; anything else is a glitch or a placeholder, never an achievement. Being computed, badges that older code awarded
for such tracks simply stop being listed (nothing is deleted). Car names go through ``model.display_car``: a raw id
("team_214") is never shown. ``fact`` is the key the Session complete card de-duplicates on (``pb:<lap id>``,
``first_clean:<game>:<track>:<car>``, ``pb_streak:<game>:<track>:<car>:<n>``, ``goal:<id>``; the recap's things
carry the same keys).

Badges (key, earned when):

* ``first_clean_lap:{game}:{track_id}`` - the first session with a clean lap at a track.
* ``under_time:{game}:{track_id}:{car_id}:{ms}`` - a session's best beats the best from *earlier sessions* in that
  car and crosses at least one whole second; the lowest second crossed, one per session [H]. Laps within one
  session never count against each other.
* ``clean_streak:{n}`` (3, 5, 10, 20) - the first session whose best run of clean laps reaches ``n``.
* ``ten_clean_session`` - the first session with 10 clean laps.
* ``pb_streak:{n}`` (2, 3, 5) - any game + track + car's PB streak first reaches ``n`` sessions in a row.
* ``weekly_streak:{n}`` (2, 4, 8, 12) - Monday-to-Sunday weeks in a row (server local time) with a timed session.
* ``busy_week:{n}`` (3, 5) - the first week with ``n`` timed sessions.
* ``clean_race:{rule}`` - the first evaluable F1 race with no penalties / without contact.
* ``goals_reached:{n}`` (1, 3, 10) - goals reached (stored ``achieved_unix``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from pitwall.motivation import rules
from pitwall.motivation.model import (
    GoalRow,
    History,
    LapRow,
    Scope,
    SessionRow,
    in_car,
    lap_time,
    lap_time_radio,
    local_date,
    track_identified,
)

CLEAN_STREAK_LEVELS = (3, 5, 10, 20)
PB_STREAK_LEVELS = (2, 3, 5)
WEEKLY_LEVELS = (2, 4, 8, 12)
BUSY_WEEK_LEVELS = (3, 5)
GOALS_LEVELS = (1, 3, 10)
TEN_CLEAN = 10
PB_SCOPES_SHOWN = 3
MIN_TRACK_BADGE_LAP_MS = 30_000  # a shorter "lap" is a lap-counter glitch or a test loop, not a lap of a circuit
TIMED_RULE = "Counting sessions with a timed lap"  # 5.7: the count says which rule it uses


@dataclass(slots=True, frozen=True)
class Badge:
    key: str
    kind: str
    level: int | str | None
    title: str
    title_simple: str
    detail: str | None
    earned_unix: float
    session_id: str | None
    lap_id: int | None
    scope: Scope | None
    synthetic: bool
    fact: str | None = None  # de-duplication key shared with the recap (module docstring)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "level": self.level,
            "title": self.title,
            "title_simple": self.title_simple,
            "detail": self.detail,
            "earned_unix": self.earned_unix,
            "session_id": self.session_id,
            "lap_id": self.lap_id,
            "scope": None if self.scope is None else self.scope.to_dict(),
            "synthetic": self.synthetic,
            "fact_key": self.fact,
        }


def _track(s: SessionRow) -> str:
    return s.track_name or s.track_id or "this track"


def _car_scope(s: SessionRow) -> Scope:
    return Scope(game=s.game, track_id=s.track_id, track_name=s.track_name, car_id=s.car_id, car_name=s.car_name)


def _in_car(s: SessionRow) -> str:
    return in_car(s.car_name)


def track_badges_allowed(s: SessionRow) -> bool:
    """A session that may earn track badges: real driving (never a replay) at an identified track."""
    return not s.replay and track_identified(s.track_id, s.track_name)


def badge_laps(laps: Sequence[LapRow]) -> list[LapRow]:
    """The laps that count for track badges: clean, timed and at least 30 s."""
    return [
        lap for lap in laps if lap.clean and lap.lap_time_ms is not None and lap.lap_time_ms >= MIN_TRACK_BADGE_LAP_MS
    ]


def first_clean_fact(s: SessionRow) -> str:
    return f"first_clean:{s.game}:{s.track_id}:{s.car_id}"


def _badge(
    kind: str,
    key: str,
    level: int | str | None,
    title: str,
    simple: str,
    s: SessionRow,
    lap: LapRow | None,
    *,
    detail: str | None = None,
    scope: Scope | None = None,
    fact: str | None = None,
) -> Badge:
    lap_id = None if lap is None else lap.id
    return Badge(key, kind, level, title, simple, detail, s.started_unix, s.id, lap_id, scope, s.synthetic, fact)


def _timed_sessions(history: History) -> list[SessionRow]:
    return [s for s in history.sessions if rules.is_timed_session(history.laps_of(s.id))]


def badges(history: History, achieved_goals: Sequence[GoalRow] = ()) -> list[Badge]:
    """Every badge the history has earned, newest first (ties by key)."""
    out: list[Badge] = []
    seen: set[str] = set()

    def add(b: Badge) -> None:
        if b.key not in seen:
            seen.add(b.key)
            out.append(b)

    pb: dict[tuple[str, str, str | None], int] = {}
    pb_streaks: dict[tuple[str, str, str | None], int] = {}
    week_counts: dict[date, int] = {}
    last_week: date | None = None
    weeks_in_row = 0
    for s in history.sessions:
        laps = history.laps_of(s.id)
        clean = [lap for lap in laps if lap.clean and lap.lap_time_ms is not None]
        track = _track(s)
        tracked = badge_laps(laps) if track_badges_allowed(s) else []
        if tracked:
            add(
                _badge(
                    "first_clean_lap",
                    f"first_clean_lap:{s.game}:{s.track_id}",
                    None,
                    f"First clean lap at {track}",
                    f"Your first clean lap at {track}",
                    s,
                    tracked[0],
                    detail=f"{lap_time(tracked[0].lap_time_ms)} on lap {tracked[0].lap_number}{_in_car(s)}",
                    scope=Scope(game=s.game, track_id=s.track_id, track_name=s.track_name),
                    fact=first_clean_fact(s),
                )
            )
        key = s.pb_key
        best = rules.fastest_clean(tracked)
        if key is not None and best is not None and best.lap_time_ms is not None:
            prev = pb.get(key)
            ms = best.lap_time_ms
            beat = prev is not None and ms < prev
            if beat and prev is not None:
                boundary = (ms // 1000 + 1) * 1000
                if boundary <= prev:
                    t = lap_time_radio(boundary)
                    add(
                        _badge(
                            "under_time",
                            f"under_time:{s.game}:{s.track_id}:{s.car_id}:{boundary}",
                            boundary,
                            # the best is per car: the title names it ("under 1:19 at Austria" alone is false
                            # for a driver who went faster there in another car)
                            f"First time under {t} at {track}{_in_car(s)}",
                            f"You beat {t} at {track}{_in_car(s)} for the first time",
                            s,
                            best,
                            detail=f"{lap_time(ms)} on lap {best.lap_number}",
                            scope=_car_scope(s),
                            fact=f"pb:{best.id}",
                        )
                    )
            streak = pb_streaks.get(key, 0) + 1 if beat else 0
            pb_streaks[key] = streak
            pb[key] = ms if prev is None else min(prev, ms)
            for level in PB_STREAK_LEVELS:
                if streak >= level:
                    add(
                        _badge(
                            "pb_streak",
                            f"pb_streak:{level}",
                            level,
                            f"New best in {level} sessions in a row",
                            f"Faster than ever, {level} times in a row",
                            s,
                            best,
                            detail=f"{track}{_in_car(s)}",
                            scope=_car_scope(s),
                            fact=f"pb_streak:{s.game}:{s.track_id}:{s.car_id}:{level}",
                        )
                    )
        run = rules.best_run(laps)
        for level in CLEAN_STREAK_LEVELS:
            if len(run) >= level:
                add(
                    _badge(
                        "clean_streak",
                        f"clean_streak:{level}",
                        level,
                        f"{level} clean laps in a row",
                        f"{level} clean laps in a row",
                        s,
                        run[level - 1],
                        detail=f"{track}, laps {run[0].lap_number}-{run[level - 1].lap_number}",
                    )
                )
        if len(clean) >= TEN_CLEAN:
            add(
                _badge(
                    "ten_clean_session",
                    "ten_clean_session",
                    TEN_CLEAN,
                    f"{TEN_CLEAN} clean laps in one session",
                    f"{TEN_CLEAN} clean laps in one session",
                    s,
                    clean[TEN_CLEAN - 1],
                    detail=track,
                )
            )
        if rules.is_timed_session(laps):
            week = rules.week_of(s.started_unix)
            week_counts[week] = week_counts.get(week, 0) + 1
            if week != last_week:
                weeks_in_row = weeks_in_row + 1 if last_week is not None and week - last_week == timedelta(7) else 1
                last_week = week
            for level in WEEKLY_LEVELS:
                if weeks_in_row >= level:
                    add(
                        _badge(
                            "weekly_streak",
                            f"weekly_streak:{level}",
                            level,
                            f"{level} weeks in a row",
                            f"You drove {level} weeks in a row",
                            s,
                            None,
                            detail=TIMED_RULE,
                        )
                    )
            for level in BUSY_WEEK_LEVELS:
                if week_counts[week] >= level:
                    add(
                        _badge(
                            "busy_week",
                            f"busy_week:{level}",
                            level,
                            f"{level} sessions in one week",
                            f"{level} drives in one week",
                            s,
                            None,
                            detail=TIMED_RULE,
                        )
                    )
        if s.is_race and s.is_f1:
            outcome = rules.race_outcome(s, laps, history.events.get(s.id, ()))
            last = next((lap for lap in laps if lap.id == outcome.final_lap_id), None)
            for rule, title, simple in (
                ("no_penalties", "Race finished with no penalties", "A whole race with no penalties"),
                (
                    "no_contact",
                    "Race finished without touching another car",
                    "A whole race without touching another car",
                ),
            ):
                if outcome.meets(rule):
                    add(_badge("clean_race", f"clean_race:{rule}", rule, title, simple, s, last, detail=track))
    reached = sorted((g for g in achieved_goals if g.achieved_unix is not None), key=lambda g: (g.achieved_unix, g.id))
    for level in GOALS_LEVELS:
        if len(reached) >= level:
            g = reached[level - 1]
            assert g.achieved_unix is not None
            title = "First goal reached" if level == 1 else f"{level} goals reached"
            out.append(
                Badge(
                    f"goals_reached:{level}",
                    "goals_reached",
                    level,
                    title,
                    title,
                    None,
                    g.achieved_unix,
                    g.achieved_session_id,
                    g.achieved_lap_id,
                    None,
                    False,
                    f"goal:{g.id}",
                )
            )
    out.sort(key=lambda b: (-b.earned_unix, b.key))
    return out


# ---------------------------------------------------------------------------------------------- streaks
def _weeks_in_row(weeks: set[date], end: date) -> int:
    n = 0
    w = end
    while w in weeks:
        n += 1
        w -= timedelta(7)
    return n


def streaks(history: History, now_unix: float) -> dict[str, Any]:
    """Streaks as at ``now_unix`` (sessions started after it are ignored). The weekly streak still counts this week
    until the week ends: with no session yet this week it is the run that ended last week."""
    sessions = [s for s in history.sessions if s.started_unix <= now_unix]
    timed = [s for s in sessions if rules.is_timed_session(history.laps_of(s.id))]
    this_week = rules.week_start(local_date(now_unix))
    weeks = {rules.week_of(s.started_unix) for s in timed}
    current = _weeks_in_row(weeks, this_week) or _weeks_in_row(weeks, this_week - timedelta(7))
    best_weeks = 0
    for w in weeks:
        if w - timedelta(7) not in weeks:
            best_weeks = max(best_weeks, _run_from(weeks, w))
    best_run = 0
    best_run_sid: str | None = None
    for s in timed:
        n = len(rules.best_run(history.laps_of(s.id)))
        if n > best_run:
            best_run, best_run_sid = n, s.id
    last = timed[-1] if timed else None
    pbs: list[tuple[int, int, float, dict[str, Any]]] = []
    scoped = History(sessions, history.laps, history.events)
    for scoped_group in rules.pb_scopes(scoped).values():
        group = [s for s in scoped_group if track_badges_allowed(s)]
        if not group:
            continue
        bests = rules.session_bests(group, {s.id: badge_laps(history.laps_of(s.id)) for s in group})
        st = rules.pb_streak(bests)
        if st.best < 1:
            continue
        s = group[-1]
        scope = _car_scope(s)
        pbs.append(
            (
                st.current,
                st.best,
                s.started_unix,
                {
                    "scope": scope.to_dict(),
                    "scope_text": scope.text() or _track(s),
                    "current_sessions": st.current,
                    "best_sessions": st.best,
                },
            )
        )
    pbs.sort(key=lambda t: (-t[0], -t[1], -t[2]))
    return {
        "week_start": this_week.isoformat(),
        "weekly": {
            "current_weeks": current,
            "best_weeks": best_weeks,
            "this_week_sessions": sum(1 for s in timed if rules.week_of(s.started_unix) == this_week),
        },
        "clean_laps": {
            "best": best_run,
            "best_session_id": best_run_sid,
            "last_session": None if last is None else len(rules.best_run(history.laps_of(last.id))),
            "last_session_id": None if last is None else last.id,
        },
        "pb": [t[3] for t in pbs[:PB_SCOPES_SHOWN]],
    }


def _run_from(weeks: set[date], start: date) -> int:
    n = 0
    w = start
    while w in weeks:
        n += 1
        w += timedelta(7)
    return n
