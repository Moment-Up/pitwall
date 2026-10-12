"""Today's 3 things: one thing that went well, one to work on, and one piece of progress, for one session (pure).

Deterministic, from the session analysis (``core.session_analysis``: observations against the owner's reference)
and the owner's history *as at that session* (sessions started before it, plus the session itself), so a later
session never changes a recap's progress. Like the Summary tab, the observations follow the analyser's current
reference.

Observation picking ports the dashboard's Work on / Went well ranking (``web-react/src/lib/review/coaching.ts``):
grouped by corner + kind (incidents left out), score = summed priority / laps compared, ties to the point seen on
more laps, then the larger mean impact, then corner and kind names. The latest occurrence must clear the session
owner's coaching limits (confidence, impact, allowed kinds; no owner = advanced). Observation text is the coach's,
verbatim. No generated sentence here ever tells the driver to brake later.

Order of choices: went well - personal best, or the first clean laps here in this car (real, owned sessions: a best
always comes first), the top positive point, a run of 3+ clean laps, the gain from the first clean lap to the best
(0.1 s+, race lap 1 left out), every lap clean; for a beginner, else the laps driven. Work on - the top corrective
point, laps that did not count, no clean lap, a single clean lap. Progress (real, owned sessions only) - the goals
reached, a PB streak of 2+, a goal this session moved closer, the gap to the best here, first clean laps at a track
(unless Went well already says so), the count of sessions with a timed lap this week. A session with no timed lap
has no things at all (it is not one of the week's sessions either). Personal bests are per game + track + car, and
their sentences name the car (``model.in_car``: never a raw id).

``fact_key`` names the fact a thing reports, as the badges do (``pb:<lap id>``, ``first_clean:<game>:<track>:<car>``,
``pb_streak:<game>:<track>:<car>:<n>``, ``goal:<id>``): the Session complete card shows each fact once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pitwall.drivers import CoachingLimits
from pitwall.motivation import goals as G
from pitwall.motivation import rules
from pitwall.motivation.model import (
    GoalRow,
    History,
    LapRow,
    SessionRow,
    about_s,
    count_words,
    gap_s,
    in_car,
    lap_time,
    lower_first,
    seconds,
    short_date,
)

INCIDENT_KIND = "incident"
MIN_RUN = 3
MIN_GAIN_MS = 100
WITHIN_PB_MS = 100

WHY_SYNTHETIC = "Synthetic sessions do not count towards progress"
WHY_REPLAY = "Replays are not anyone's driving"
WHY_NO_OWNER = "This session has no driver profile"
WHY_NO_LAPS = "No timed laps in this session"
WHY_NOTHING_WELL = "Nothing stood out this time: no new best, no run of 3 clean laps and no strong corner"
WHY_NOTHING_WORK = "Nothing clear to work on this time"


@dataclass(slots=True)
class Thing:
    kind: str  # went_well | work_on | progress
    source: str
    text: str
    text_simple: str
    evidence: str | None = None
    corner: str | None = None
    corner_label: str | None = None
    lap_id: int | None = None
    lap_number: int | None = None
    observation_kind: str | None = None
    observation_key: str | None = None
    goal_id: int | None = None
    values: dict[str, Any] = field(default_factory=dict)
    fact_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "text": self.text,
            "text_simple": self.text_simple,
            "evidence": self.evidence,
            "corner": self.corner,
            "corner_label": self.corner_label,
            "lap_id": self.lap_id,
            "lap_number": self.lap_number,
            "observation_kind": self.observation_kind,
            "observation_key": self.observation_key,
            "goal_id": self.goal_id,
            "values": self.values,
            "fact_key": self.fact_key,
        }


# ---------------------------------------------------------------------------------------------- observations
@dataclass(slots=True, frozen=True)
class RankedPoint:
    corner: str
    kind: str
    latest: Mapping[str, Any]
    latest_lap_id: int | None
    seen: int
    compared: int
    score: float
    mean_impact_s: float | None


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v)


def rank_points(
    observations: Mapping[int, Sequence[Mapping[str, Any]]],
    compared: int,
    positive: bool,
    limits: CoachingLimits,
) -> list[RankedPoint]:
    """Grouped and ranked points (the dashboard's ranking), each group judged by its latest occurrence."""
    groups: dict[tuple[str, str], list[tuple[int | None, Mapping[str, Any]]]] = {}
    for key, obs in observations.items():
        for o in obs:
            if o.get("kind") == INCIDENT_KIND or bool(o.get("positive")) != positive:
                continue
            groups.setdefault((str(o.get("corner")), str(o.get("kind"))), []).append((key, o))
    out: list[RankedPoint] = []
    for (corner, kind), items in groups.items():
        items.sort(key=lambda e: int(e[1].get("lap_number") or 0))
        latest_lap_id, last = items[-1]
        conf = _num(last.get("confidence"))
        impact = _num(last.get("impact_s"))
        if conf is None or conf < limits.min_confidence or impact is None or abs(impact) < limits.min_impact_s:
            continue
        if limits.allowed_kinds is not None and kind not in limits.allowed_kinds:
            continue
        laps = {int(o.get("lap_number") or 0) for _, o in items}
        denom = max(compared, len(laps), 1)
        priorities = [p for _, o in items if (p := _num(o.get("priority"))) is not None]
        impacts = [i for _, o in items if (i := _num(o.get("impact_s"))) is not None]
        out.append(
            RankedPoint(
                corner=corner,
                kind=kind,
                latest=last,
                latest_lap_id=latest_lap_id,
                seen=len(laps),
                compared=max(compared, len(laps)),
                score=sum(priorities) / denom,
                mean_impact_s=sum(impacts) / len(impacts) if impacts else None,
            )
        )
    out.sort(key=lambda p: (-p.score, -p.seen, -abs(p.mean_impact_s or 0.0), p.corner, p.kind))
    return out


def _point_thing(kind: str, p: RankedPoint) -> Thing:
    o = p.latest
    text = str(o.get("text") or "")
    lap_word = "lap" if p.compared == 1 else "laps"
    return Thing(
        kind=kind,
        source="observation",
        text=text,
        text_simple=str(o.get("text_simple") or text),
        evidence=f"Seen on {p.seen} of {p.compared} {lap_word} compared with your reference",
        corner=p.corner,
        corner_label=o.get("corner_label") if isinstance(o.get("corner_label"), str) else None,
        lap_id=p.latest_lap_id,
        lap_number=int(o["lap_number"]) if isinstance(o.get("lap_number"), int) else None,
        observation_kind=p.kind,
        observation_key=f"{p.corner}:{p.kind}",
        values={
            "impact_s": _num(o.get("impact_s")),
            "confidence": _num(o.get("confidence")),
            "seen": p.seen,
            "compared": p.compared,
        },
    )


# ---------------------------------------------------------------------------------------------- inputs
@dataclass(slots=True)
class RecapInput:
    session: SessionRow
    laps: list[LapRow]
    observations: Mapping[int, Sequence[Mapping[str, Any]]]
    compared: int
    limits: CoachingLimits
    counts: bool  # real, owned driving: progress applies
    history: History | None  # the owner's driving (None when the session does not count)
    goals: Sequence[GoalRow] = ()  # the owner's goals (any status)
    why_progress: str | None = None  # why progress is empty when ``counts`` is False
    # when the recap is read: an older session's week is "the week of Mon 5 Oct", not "this week" (None: its own week)
    now_unix: float | None = None


def _track(s: SessionRow) -> str:
    return s.track_name or s.track_id or "this track"


def first_clean_key(s: SessionRow) -> str:
    """The same key as the first clean lap badge's fact (``badges.first_clean_fact``)."""
    return f"first_clean:{s.game}:{s.track_id}:{s.car_id}"


def _scope_bests(history: History, s: SessionRow) -> list[rules.SessionBest]:
    key = s.pb_key
    if key is None:
        return []
    group = [x for x in history.sessions if x.pb_key == key]
    return rules.session_bests(group, history.laps)


# ---------------------------------------------------------------------------------------------- went well
def went_well(inp: RecapInput, bests: Sequence[rules.SessionBest]) -> Thing | None:
    s, laps = inp.session, inp.laps
    mine = next((b for b in bests if b.session.id == s.id), None)
    car = in_car(s.car_label)  # bests are per car: "at Austria" alone is false after a faster lap in another car
    if inp.counts and mine is not None and mine.is_pb and mine.previous_ms is not None:
        track = _track(s)
        return Thing(
            "went_well",
            "pb",
            f"New personal best at {track}{car}: {lap_time(mine.best_ms)} on lap {mine.lap.lap_number}, "
            f"{gap_s(mine.previous_ms - mine.best_ms)} s faster than before.",
            f"Your fastest lap ever at {track}{car}: {lap_time(mine.best_ms)}.",
            lap_id=mine.lap.id,
            lap_number=mine.lap.lap_number,
            values={"lap_ms": mine.best_ms, "previous_ms": mine.previous_ms, "gain_ms": mine.gain_ms},
            fact_key=f"pb:{mine.lap.id}",
        )
    if inp.counts and mine is not None and mine.previous_ms is None:
        # a first-ever best here in this car counts as a best (plan 2.6): it comes first too
        n_clean = sum(1 for lap in laps if lap.clean and lap.lap_time_ms is not None)
        t = lap_time(mine.best_ms)
        if n_clean > 1:
            text = f"First clean laps here{car}: best {t} on lap {mine.lap.lap_number}."
        else:
            text = f"First clean lap here{car}: {t}."
        return Thing(
            "went_well",
            "first_clean",
            text,
            f"Your first clean lap here{car}: {t}." if n_clean == 1 else f"Your first clean laps here{car}: best {t}.",
            lap_id=mine.lap.id,
            lap_number=mine.lap.lap_number,
            values={"lap_ms": mine.best_ms, "clean_laps": n_clean},
            fact_key=first_clean_key(s),
        )
    top = rank_points(inp.observations, inp.compared, True, inp.limits)
    if top:
        return _point_thing("went_well", top[0])
    run = rules.best_run(laps)
    if len(run) >= MIN_RUN:
        return Thing(
            "went_well",
            "clean_streak",
            f"{len(run)} clean laps in a row.",
            f"{len(run)} laps in a row that all counted.",
            lap_id=run[-1].id,
            lap_number=run[-1].lap_number,
            values={"run": len(run), "from_lap": run[0].lap_number, "to_lap": run[-1].lap_number},
        )
    # race lap 1 is a standing start (not always flagged): from the grid it is no measure of getting faster
    clean = [
        lap
        for lap in laps
        if lap.clean and lap.lap_time_ms is not None and not rules.standing_start(lap, s.session_type)
    ]
    best = rules.fastest_clean(clean)
    if clean and best is not None and best.lap_time_ms is not None and clean[0].lap_time_ms is not None:
        gain = clean[0].lap_time_ms - best.lap_time_ms
        if gain >= MIN_GAIN_MS:
            return Thing(
                "went_well",
                "in_session_gain",
                f"Your laps got {gain / 1000:.2f} s faster from your first clean lap to your best.",
                f"You got {gain / 1000:.1f} s faster during the session.",
                lap_id=best.id,
                lap_number=best.lap_number,
                values={"first_ms": clean[0].lap_time_ms, "best_ms": best.lap_time_ms, "gain_ms": gain},
            )
    counted = [lap for lap in laps if lap.lap_time_ms is not None and rules.lap_class(lap) != rules.NEUTRAL]
    if len(counted) >= 2 and all(rules.lap_class(lap) == rules.CLEAN for lap in counted):
        n = len(counted)
        return Thing(
            "went_well",
            "all_clean",
            "Both timed laps were clean." if n == 2 else f"All {n} timed laps were clean.",
            "Every lap counted.",
            values={"laps": n},
        )
    return None


# ---------------------------------------------------------------------------------------------- work on
def _hygiene(laps: Sequence[LapRow]) -> Thing | None:
    counted = [lap for lap in laps if lap.lap_time_ms is not None and rules.lap_class(lap) != rules.NEUTRAL]
    bad = [lap for lap in counted if rules.lap_class(lap) == rules.BREAKER]
    if not bad:
        return None
    invalid = sum(1 for lap in bad if "invalid" in lap.flags or lap.valid is False)
    flashback = sum(1 for lap in bad if "flashback" in lap.flags)
    reset = sum(1 for lap in bad if "distance_jump" in lap.flags)
    n, total = len(bad), len(counted)
    if n == 1:
        lap = bad[0]
        if "invalid" in lap.flags or lap.valid is False:
            why, plain = "the game invalidated it", "the game cancelled it"
        elif "flashback" in lap.flags:
            why, plain = "a flashback was used on it", "a flashback"
        else:
            why, plain = "the car was reset to the track", "a reset to the track"
        text = f"Lap {lap.lap_number} did not count: {why}."
        # a beginner's Work on is advice, not only a count (UX review)
        simple = f"Lap {lap.lap_number} did not count ({plain}): keep it on the track next time."
    else:
        reasons = []
        if invalid:
            reasons.append(f"{invalid} invalidated by the game")
        if flashback:
            reasons.append(f"{flashback} with a flashback")
        if reset:
            reasons.append(f"{reset} reset to the track")
        text = f"{n} of {total} laps did not count: {', '.join(reasons)}."
        simple = f"{n} timed laps did not count this time: keep them on the track next time."
    return Thing(
        "work_on",
        "lap_hygiene",
        text,
        simple,
        lap_id=bad[0].id,
        lap_number=bad[0].lap_number,
        values={"not_counted": n, "laps": total, "invalidated": invalid, "flashbacks": flashback, "resets": reset},
    )


def work_on(inp: RecapInput) -> Thing | None:
    top = rank_points(inp.observations, inp.compared, False, inp.limits)
    if top:
        return _point_thing("work_on", top[0])
    hygiene = _hygiene(inp.laps)
    if hygiene is not None:
        return hygiene
    clean = [lap for lap in inp.laps if lap.clean and lap.lap_time_ms is not None]
    if not clean:
        return Thing(
            "work_on",
            "no_clean_lap",
            "No clean lap this time, so there is nothing to compare yet.",
            "No clean lap this time.",
        )
    if len(clean) == 1:
        if inp.session.one_shot:  # one timed lap by design: "drive two or more" would be impossible advice
            return Thing(
                "work_on",
                "single_clean_lap",
                "One-shot qualifying has one timed lap, so there is no second lap in this session to compare it with.",
                "One-shot qualifying: one timed lap, nothing to compare it with.",
                lap_id=clean[0].id,
                lap_number=clean[0].lap_number,
            )
        return Thing(
            "work_on",
            "single_clean_lap",
            "Only one clean lap: drive two or more next time so they can be compared.",
            "Only one clean lap: try for two or more next time.",
            lap_id=clean[0].id,
            lap_number=clean[0].lap_number,
        )
    return None


# ---------------------------------------------------------------------------------------------- progress
def _goal_reached(inp: RecapInput, lap_numbers: Mapping[int, int]) -> Thing | None:
    """Every goal this session reached: the first in full, the others named ("And 1 more: ..."), so a second goal is
    celebrated too. The card's heading already says "Goal reached": the text does not repeat it."""
    reached = sorted(
        (g for g in inp.goals if g.achieved_session_id == inp.session.id and g.achieved_unix is not None),
        key=lambda x: (x.achieved_unix or 0.0, x.id),
    )
    if not reached:
        return None
    g, others = reached[0], reached[1:]
    title = G.goal_titles(g)[0]
    n = lap_numbers.get(g.achieved_lap_id) if g.achieved_lap_id is not None else None
    on_lap = f" on lap {n}" if n is not None else ""
    v = g.achieved_value
    if g.kind == "lap_time" and v is not None:
        detail = f" ({lap_time(v)}{on_lap})"
    elif g.kind == "consistency" and v is not None:
        detail = f" (within {seconds(v, tenths_when_whole=False)} s{on_lap})"
    elif g.kind == "clean_streak" and n is not None:
        detail = f" ({on_lap.strip()})"
    else:
        detail = ""
    text = f"{title}{detail}."
    if others:
        text += f" And {len(others)} more: {', '.join(lower_first(G.goal_titles(o)[0]) for o in others)}."
    simple = " and ".join(lower_first(G.goal_titles(x)[1]) for x in reached)
    return Thing(
        "progress",
        "goal_reached",
        text,
        f"You did it: {simple}.",
        lap_id=g.achieved_lap_id,
        lap_number=n,
        goal_id=g.id,
        # goal_kind: the card shows "8 clean laps in a row" once, not again as a clean-run badge (complete.ts)
        values={"target": g.target, "value": v, "goals": len(reached), "goal_kind": g.kind},
        fact_key=f"goal:{g.id}",
    )


def _goal_progress(inp: RecapInput, history: History) -> Thing | None:
    s = inp.session
    before = history.without(s.id)
    active = [g for g in inp.goals if g.status == "active" and rules.scope_matches(g.scope, s)]
    active.sort(key=lambda g: (g.kind != "lap_time", g.id))
    for g in active:
        if g.kind == "race_clean":
            continue
        now = G.measure(g, history)
        if now.value is None or now.session_id != s.id:
            continue  # this session did not set the goal's best since it was set
        was = G.measure(g, before)
        p = G.progress(g, history)
        if p.met:
            continue
        better = (
            was.value is None
            or (g.kind == "clean_streak" and now.value > was.value)
            or (g.kind != "clean_streak" and now.value < was.value)
        )
        if not better:
            continue
        title = G.goal_titles(g)[0]
        cur = now.value
        if g.kind == "lap_time":
            to_go = cur - g.target
            text = f"{title}: {gap_s(to_go)} s to go (best since you set it {lap_time(cur)})."
            simple = f"{about_s(to_go).capitalize()} to go to your goal."
        elif g.kind == "clean_streak":
            text = f"{title}: best since you set it {round(cur)} of {round(g.target)} laps."
            simple = f"{round(cur)} of {round(g.target)} clean laps in a row so far."
        else:
            k = g.window_laps
            within = seconds(cur, tenths_when_whole=False)
            text = f"{title}: your steadiest {k} laps since you set it were within {within} s."
            simple = f"Your steadiest {k} laps were within {cur / 1000:.1f} s."
        return Thing(
            "progress",
            "goal_progress",
            text,
            simple,
            lap_id=now.lap_id,
            goal_id=g.id,
            values={"target": g.target, "current": cur, "previous": was.value},
        )
    return None


def progress_thing(
    inp: RecapInput,
    bests: Sequence[rules.SessionBest],
    lap_numbers: Mapping[int, int],
    said: frozenset[str] = frozenset(),
) -> Thing | None:
    """``said``: the fact keys Went well already reports (they are not repeated here)."""
    s = inp.session
    history = inp.history
    if not inp.counts or history is None:
        return None
    reached = _goal_reached(inp, lap_numbers)
    if reached is not None:
        return reached
    track = _track(s)
    streak = rules.pb_streak(bests)
    idx = next((i for i, b in enumerate(bests) if b.session.id == s.id), None)
    if idx is not None and streak.per_session[idx] >= 2:
        n = streak.per_session[idx]
        return Thing(
            "progress",
            "pb_streak",
            f"New best at {track}{in_car(s.car_label)} in {n} sessions in a row.",
            f"Faster than ever at {track}{in_car(s.car_label)}, {n} times in a row.",
            lap_id=bests[idx].lap.id,
            lap_number=bests[idx].lap.lap_number,
            values={"sessions": n},
            # a streak is its own fact (Went well already says the new best: ``pb:<lap>``)
            fact_key=f"pb_streak:{s.game}:{s.track_id}:{s.car_id}:{n}",
        )
    moved = _goal_progress(inp, history)
    if moved is not None:
        return moved
    mine = bests[idx] if idx is not None else None
    if mine is not None and mine.previous_ms is not None and not mine.is_pb:
        pb_session = next((b.session for b in bests[:idx] if b.best_ms == mine.previous_ms), None)
        when = f", {short_date(pb_session.started_unix)}" if pb_session is not None else ""
        gap = mine.best_ms - mine.previous_ms
        if gap < WITHIN_PB_MS:
            text = f"Your best in this session was within 0.1 s of your best here ({lap_time(mine.previous_ms)}{when})."
            simple = "Within 0.1 s of your best here."
        else:
            text = (
                f"Your best in this session was {gap_s(gap)} s off your best here ({lap_time(mine.previous_ms)}{when})."
            )
            simple = f"{about_s(gap).capitalize()} off your best here."
        return Thing(
            "progress",
            "gap_to_pb",
            text,
            simple,
            lap_id=mine.lap.id,
            lap_number=mine.lap.lap_number,
            values={"best_ms": mine.best_ms, "pb_ms": mine.previous_ms, "gap_ms": gap},
        )
    if mine is not None and mine.previous_ms is None and first_clean_key(s) not in said:
        car = in_car(s.car_label)
        return Thing(
            "progress",
            "first_session",
            f"Your first clean laps at {track}{car}: {lap_time(mine.best_ms)} is the time to beat next time.",
            f"Your first clean laps at {track}{car}: {lap_time(mine.best_ms)} to beat next time.",
            lap_id=mine.lap.id,
            lap_number=mine.lap.lap_number,
            values={"best_ms": mine.best_ms},
            fact_key=first_clean_key(s),
        )
    week = rules.week_of(s.started_unix)
    upto = history.until(s.id).sessions
    in_week = [  # timed sessions only, as the digest, badges and streaks count them (and the words say so)
        x for x in upto if rules.week_of(x.started_unix) == week and rules.is_timed_session(history.laps_of(x.id))
    ]
    n_laps = sum(len(rules.timed(history.laps_of(x.id))) for x in in_week)
    n = len(in_week)
    current = inp.now_unix is None or rules.week_of(inp.now_unix) == week
    if current:
        text = f"{count_words(n, 'session')} with a timed lap this week, {count_words(n_laps, 'lap')} so far."
        simple = f"You set lap times in {count_words(n, 'session')} this week."
    else:  # read later: the week the session was driven in, counted up to it
        when = f"the week of {week:%a} {week.day} {week:%b}"
        text = f"{count_words(n, 'session')} with a timed lap in {when}, {count_words(n_laps, 'lap')} by then."
        simple = f"You set lap times in {count_words(n, 'session')} in {when}."
    return Thing(
        "progress",
        "sessions_week",
        text,
        simple,
        values={"sessions": n, "laps": n_laps, "week_start": week.isoformat(), "this_week": current},
    )


# ---------------------------------------------------------------------------------------------- recap
@dataclass(slots=True)
class Recap:
    went_well: Thing | None
    work_on: Thing | None
    progress: Thing | None
    why: dict[str, str | None]


def _drove(inp: RecapInput) -> Thing | None:
    """A beginner's Went well when nothing else stood out: true, and kind (never "nothing stood out")."""
    n = len(rules.timed(inp.laps))
    if not n:
        return None
    s = inp.session
    return Thing(
        "went_well",
        "drove",
        f"You drove {count_words(n, 'timed lap')} at {_track(s)}.",
        f"You drove {count_words(n, 'lap')} at {_track(s)}.",
        values={"laps": n},
    )


def build_recap(inp: RecapInput, lap_numbers: Mapping[int, int] | None = None) -> Recap:
    """The three things for ``inp.session``; ``inp.history`` must already be cut at that session. A session with no
    timed lap gets none of them (nothing to say about it, and it is not one of the week's sessions)."""
    timed = any(lap.lap_time_ms is not None for lap in inp.laps)
    if not timed:
        why_none = inp.why_progress or WHY_NO_LAPS
        return Recap(None, None, None, {"went_well": WHY_NO_LAPS, "work_on": WHY_NO_LAPS, "progress": why_none})
    bests = _scope_bests(inp.history, inp.session) if inp.history is not None else []
    good = went_well(inp, bests)
    if good is None and inp.limits.simple_wording:
        good = _drove(inp)
    work = work_on(inp)
    said = frozenset(k for k in (good.fact_key if good is not None else None,) if k)
    prog = progress_thing(inp, bests, lap_numbers or {}, said)
    why: dict[str, str | None] = {"went_well": None, "work_on": None, "progress": None}
    if good is None:
        why["went_well"] = WHY_NOTHING_WELL
    if work is None:
        why["work_on"] = WHY_NOTHING_WORK
    if prog is None:
        why["progress"] = inp.why_progress or "No progress to show yet"
    return Recap(good, work, prog, why)
