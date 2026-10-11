"""Goals: validation, titles, progress and the moment a goal is reached (pure; the service does the I/O).

Four kinds (``target`` units in brackets):

* ``lap_time`` [ms] - a clean lap under the target, at one game + track (+ layout) in one car or car class.
* ``clean_streak`` [laps] - that many clean laps in a row (``rules.runs``), optionally in a scope.
* ``consistency`` [ms spread] - ``window_laps`` (3, 5 or 10) clean laps in a row within the target of each other.
* ``race_clean`` [races, always 1] - an F1 race from lap 1 to the flag with no penalties (``no_penalties``) or with
  no penalties and no contact either (``no_contact``).

Only the driver's real, owned driving counts (the service loads that history: never replays, never synthetic), and
only laps stored after the goal was set (``after_lap_id``). Progress is derived when read; the worker flips a goal
to achieved once (``first_hit``). A stored baseline is the progress bar's start; when it is unknown the first
measurement after creation is used (the worker stores it, a read only uses it in memory).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pitwall.motivation import rules
from pitwall.motivation.model import (
    GOAL_KINDS,
    RACE_RULES,
    SYNTHETIC_TRACK_PREFIX,
    WINDOW_LAPS,
    GoalRow,
    History,
    LapRow,
    Scope,
    SessionRow,
    about_s,
    gap_s,
    is_f1_game,
    lap_time,
    number_word,
    seconds,
    short_date,
)

MAX_ACTIVE = 6
LAP_TIME_MIN_MS, LAP_TIME_MAX_MS = 10_000, 3_600_000
STREAK_MIN, STREAK_MAX = 2, 50
SPREAD_MIN_MS, SPREAD_MAX_MS = 100, 10_000
BASELINE_DAYS = 30  # clean-streak / consistency baselines look at the last 30 days


class GoalError(Exception):
    """A refused goal request: ``status`` 409 (conflicts with existing state) or 422 (bad value), ``code`` for
    the dashboard, ``detail`` in plain words."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def invalid(detail: str, code: str = "invalid") -> GoalError:
    return GoalError(422, code, detail)


def conflict(code: str, detail: str) -> GoalError:
    return GoalError(409, code, detail)


# ---------------------------------------------------------------------------------------------- titles
RACE_TITLES = {
    "no_penalties": "Finish a race with no penalties",
    "no_contact": "Finish a race without touching another car",
}


def titles(kind: str, target: float, params: Mapping[str, Any]) -> tuple[str, str]:
    """``(title, title_simple)``, server-made so every screen says the same thing."""
    if kind == "lap_time":
        t = lap_time(target)
        return f"A lap under {t}", f"Beat {t}"
    if kind == "clean_streak":
        n = round(target)
        return f"{n} clean laps in a row", f"{n} clean laps in a row"
    if kind == "consistency":
        k = params.get("window_laps", 5)
        s = seconds(target)
        return f"{k} clean laps within {s} s of each other", f"{k} steady laps, all within {s} s"
    rule = params.get("rule") if params.get("rule") in RACE_RULES else "no_penalties"
    title = RACE_TITLES[str(rule)]
    return title, title


def goal_titles(g: GoalRow) -> tuple[str, str]:
    return titles(g.kind, g.target, g.params)


# ---------------------------------------------------------------------------------------------- validation
@dataclass(slots=True, frozen=True)
class NewGoal:
    """A validated create request (before the checks against stored state, which run in the writer job)."""

    kind: str
    target: float
    params: dict[str, Any]
    scope: Scope
    source: str
    basis: dict[str, Any] | None


def _number(v: object, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(float(v)):
        raise invalid(f"{what} must be a number")
    return float(v)


def _whole(v: float, what: str) -> int:
    if v != int(v):
        raise invalid(f"{what} must be a whole number")
    return int(v)


def validate_new(
    kind: object,
    target: object,
    params: Mapping[str, Any] | None,
    scope: Scope,
    source: object = "manual",
    basis: Mapping[str, Any] | None = None,
) -> NewGoal:
    """Value checks (422). ``scope`` is already filled from ``from_session_id`` when one was given."""
    if kind not in GOAL_KINDS:
        raise invalid(f"kind must be one of {', '.join(GOAL_KINDS)}", "invalid_kind")
    k = str(kind)
    value = _number(target, "target")
    p = dict(params or {})
    if source not in ("manual", "suggested"):
        raise invalid("source must be manual or suggested")
    if scope.track_id is not None and scope.track_id.startswith(SYNTHETIC_TRACK_PREFIX):
        raise invalid("Synthetic test tracks cannot have goals: only real driving counts", "synthetic_scope")
    if scope.track_id is not None and scope.game is None:
        raise invalid("a track needs its game")
    if scope.car_id is not None and scope.car_class is not None:
        raise invalid("pick one car or one car class, not both", "invalid_scope")
    if scope.car_class is not None:
        parts = scope.car_class.split(":", 2)
        if len(parts) != 3 or parts[1] not in ("formula", "class") or parts[0] != scope.game:
            raise invalid("unknown car class for this game", "invalid_scope")
    out_params: dict[str, Any] = {}
    if k == "lap_time":
        ms = _whole(value, "target")
        if not LAP_TIME_MIN_MS <= ms <= LAP_TIME_MAX_MS or ms % 100:
            raise invalid(
                "A lap-time target must be between 0:10.0 and 60:00.0, in tenths of a second", "invalid_target"
            )
        if scope.game is None or scope.track_id is None:
            raise invalid("A lap-time goal needs a game and a track", "invalid_scope")
        if (scope.car_id is None) == (scope.car_class is None):
            raise invalid("A lap-time goal needs one car or one car class", "invalid_scope")
        value = float(ms)
    elif k == "clean_streak":
        n = _whole(value, "target")
        if not STREAK_MIN <= n <= STREAK_MAX:
            raise invalid(f"A clean-lap goal must be {STREAK_MIN} to {STREAK_MAX} laps", "invalid_target")
        value = float(n)
    elif k == "consistency":
        ms = _whole(value, "target")
        if not SPREAD_MIN_MS <= ms <= SPREAD_MAX_MS or ms % 100:
            raise invalid("A steady-laps target must be 0.1 to 10.0 seconds, in tenths", "invalid_target")
        window = p.get("window_laps")
        if isinstance(window, bool) or window not in WINDOW_LAPS:
            raise invalid("window_laps must be 3, 5 or 10", "invalid_params")
        out_params["window_laps"] = int(window)
        value = float(ms)
    else:  # race_clean
        if value != 1:
            raise invalid("A clean-race goal is one race (target 1)", "invalid_target")
        rule = p.get("rule")
        if rule not in RACE_RULES:
            raise invalid("rule must be no_penalties or no_contact", "invalid_params")
        if scope.game is not None and not is_f1_game(scope.game):
            raise invalid("Pitwall can only check this in F1 races", "unsupported_game")
        out_params["rule"] = str(rule)
        value = 1.0
    extra = set(p) - set(out_params)
    if extra:
        raise invalid(f"unexpected params for {k}: {', '.join(sorted(extra))}", "invalid_params")
    return NewGoal(k, value, out_params, scope, str(source), dict(basis) if basis is not None else None)


def same_scope(a: Scope, b: Scope) -> bool:
    return (a.game, a.track_id, a.car_id, a.car_class) == (b.game, b.track_id, b.car_id, b.car_class) and (
        a.track_id is None or rules.lengths_match(a.track_length_m, b.track_length_m)
    )


def conflicts(new: NewGoal, active: Sequence[GoalRow], pb_ms: int | None) -> GoalError | None:
    """The checks against stored state (409), run inside the writer job by the service."""
    if len(active) >= MAX_ACTIVE:
        return conflict("too_many", f"{MAX_ACTIVE} goals are already active: archive or delete one first.")
    for g in active:
        if g.kind == new.kind and g.params == new.params and same_scope(g.scope, new.scope) and g.target == new.target:
            return conflict("duplicate", "This goal is already set.")
    if new.kind == "lap_time":
        for g in active:
            if g.kind == "lap_time" and same_scope(g.scope, new.scope):
                return conflict("duplicate_scope", "There is already a lap-time goal here: archive it first.")
        if pb_ms is not None and pb_ms < new.target:
            return conflict("already_beaten", f"Your best here is already {lap_time(pb_ms)}.")
    return None


# ---------------------------------------------------------------------------------------------- measurements
@dataclass(slots=True, frozen=True)
class Hit:
    """Where a goal was (or would be) reached: the session, the lap and the achieved value."""

    session_id: str
    lap_id: int | None
    lap_number: int | None
    value: float


def _scope_sessions(g: GoalRow, history: History) -> list[SessionRow]:
    return [s for s in history.sessions if rules.scope_matches(g.scope, s)]


def _counted_since(g: GoalRow, history: History, s: SessionRow) -> bool:
    """The session has a lap stored after the goal was set."""
    return any(lap.id > g.after_lap_id for lap in history.laps_of(s.id))


def races_since(g: GoalRow, history: History) -> list[tuple[SessionRow, rules.RaceOutcome]]:
    """Evaluable F1 races since the goal was set (their lap-1 row is newer than the goal)."""
    out: list[tuple[SessionRow, rules.RaceOutcome]] = []
    for s in _scope_sessions(g, history):
        if not (s.is_race and s.is_f1):
            continue
        laps = history.laps_of(s.id)
        first = next((lap for lap in laps if lap.lap_number == 1), None)
        if first is None or first.id <= g.after_lap_id:
            continue
        outcome = rules.race_outcome(s, laps, history.events.get(s.id, ()))
        if outcome.evaluable:
            out.append((s, outcome))
    return out


def first_hit(g: GoalRow, history: History) -> Hit | None:
    """The first lap (or race) in ``history`` that reaches the goal, in the order driven."""
    after = g.after_lap_id
    if g.kind == "race_clean":
        for s, outcome in races_since(g, history):
            if outcome.meets(g.rule):
                return Hit(s.id, outcome.final_lap_id, outcome.final_lap_number, 1.0)
        return None
    for s in _scope_sessions(g, history):
        laps = history.laps_of(s.id)
        if g.kind == "lap_time":
            for lap in laps:
                if lap.id > after and lap.clean and lap.lap_time_ms is not None and lap.lap_time_ms < g.target:
                    return Hit(s.id, lap.id, lap.lap_number, float(lap.lap_time_ms))
        elif g.kind == "clean_streak":
            n = round(g.target)
            for r in rules.runs(laps, after):
                if len(r) >= n:
                    return Hit(s.id, r[n - 1].id, r[n - 1].lap_number, float(n))
        elif g.kind == "consistency":
            for w in rules.windows(laps, g.window_laps, s.session_type, after):
                if w.spread_ms <= g.target:
                    return Hit(s.id, w.last.id, w.last.lap_number, float(w.spread_ms))
    return None


@dataclass(slots=True, frozen=True)
class Measure:
    """The goal's current value since it was set, where it came from, and how many sessions counted."""

    value: float | None
    session_id: str | None
    lap_id: int | None
    sessions_since: int


def measure(g: GoalRow, history: History) -> Measure:
    after = g.after_lap_id
    sessions = [s for s in _scope_sessions(g, history) if any(lap.id > after for lap in history.laps_of(s.id))]
    best: tuple[float, str, int | None] | None = None
    if g.kind == "race_clean":
        races = races_since(g, history)
        met = next(((s, o) for s, o in races if o.meets(g.rule)), None)
        value = 1.0 if met else 0.0
        return Measure(value, met[0].id if met else None, None, len(races))
    for s in sessions:
        laps = history.laps_of(s.id)
        if g.kind == "lap_time":
            lap = rules.fastest_clean(laps, after)
            if lap is not None and lap.lap_time_ms is not None and (best is None or lap.lap_time_ms < best[0]):
                best = (float(lap.lap_time_ms), s.id, lap.id)
        elif g.kind == "clean_streak":
            r = rules.best_run(laps, after)
            if r and (best is None or len(r) > best[0]):
                best = (float(len(r)), s.id, r[-1].id)
        elif g.kind == "consistency":
            w = rules.best_window(laps, g.window_laps, s.session_type, after)
            if w is not None and (best is None or w.spread_ms < best[0]):
                best = (float(w.spread_ms), s.id, w.last.id)
    if best is None:
        return Measure(0.0 if g.kind == "clean_streak" else None, None, None, len(sessions))
    return Measure(best[0], best[1], best[2], len(sessions))


def first_measurement(g: GoalRow, history: History) -> float | None:
    """The first value measured after the goal was set (lap-time and steady-lap goals): the progress bar's start
    when no baseline was known at creation."""
    after = g.after_lap_id
    for s in _scope_sessions(g, history):
        laps = history.laps_of(s.id)
        if g.kind == "lap_time":
            first = next((lap for lap in laps if lap.id > after and lap.clean and lap.lap_time_ms is not None), None)
            if first is not None and first.lap_time_ms is not None:
                return float(first.lap_time_ms)
        elif g.kind == "consistency":
            ws = rules.windows(laps, g.window_laps, s.session_type, after)
            if ws:
                return float(ws[0].spread_ms)
    return None


def creation_baseline(
    kind: str, scope: Scope, params: Mapping[str, Any], history: History, now_unix: float
) -> float | None:
    """The stored baseline: lap time - the PB in scope; clean laps - the best run in the last 30 days; steady laps
    - the steadiest window in the last 30 days; clean race - none."""
    sessions = [s for s in history.sessions if rules.scope_matches(scope, s)]
    if kind == "lap_time":
        lap = rules.fastest_clean(lap for s in sessions for lap in history.laps_of(s.id))
        return None if lap is None or lap.lap_time_ms is None else float(lap.lap_time_ms)
    recent = [s for s in sessions if s.started_unix >= now_unix - BASELINE_DAYS * 86_400]
    if kind == "clean_streak":
        best = max((len(rules.best_run(history.laps_of(s.id))) for s in recent), default=0)
        return float(best) if best else None
    if kind == "consistency":
        k = params.get("window_laps", 5)
        spreads = [
            w.spread_ms for s in recent if (w := rules.best_window(history.laps_of(s.id), int(k), s.session_type))
        ]
        return float(min(spreads)) if spreads else None
    return None


def pb_in_scope(scope: Scope, history: History) -> LapRow | None:
    return rules.fastest_clean(
        lap for s in history.sessions if rules.scope_matches(scope, s) for lap in history.laps_of(s.id)
    )


# ---------------------------------------------------------------------------------------------- progress
@dataclass(slots=True, frozen=True)
class Progress:
    baseline: float | None
    current: float | None
    target: float
    fraction: float | None
    to_go: float | None
    met: bool
    best_session_id: str | None
    best_lap_id: int | None
    sessions_since: int
    text: str
    text_simple: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline,
            "current": self.current,
            "target": self.target,
            "fraction": None if self.fraction is None else round(self.fraction, 4),
            "to_go": self.to_go,
            "met": self.met,
            "best_session_id": self.best_session_id,
            "best_lap_id": self.best_lap_id,
            "sessions_since": self.sessions_since,
            "text": self.text,
            "text_simple": self.text_simple,
        }


def _fraction_lower_better(baseline: float | None, current: float | None, target: float, met: bool) -> float | None:
    """0..1 from the baseline to the target; None (no bar) until something was measured since the goal was set."""
    if met:
        return 1.0
    if baseline is None or current is None:
        return None
    span = baseline - target
    if span <= 0:
        return 0.0
    return max(0.0, min(1.0, (baseline - current) / span))


def _race_issues(outcomes: Sequence[rules.RaceOutcome], rule: str) -> str:
    """``a penalty in one, contact in both`` for the races since a goal was set."""
    n = len(outcomes)
    checks: list[tuple[str, str, int]] = [
        ("a penalty", "penalties", sum(1 for o in outcomes if o.penalties)),
        ("a flashback", "flashbacks", sum(1 for o in outcomes if o.flashbacks)),
        ("a reset to the track", "resets to the track", sum(1 for o in outcomes if o.resets)),
    ]
    if rule == "no_contact":
        checks.append(("contact", "contact", sum(1 for o in outcomes if o.contacts)))
    parts = []
    for one, many, k in checks:
        if not k:
            continue
        if n == 1:
            parts.append(one)
            continue
        where = ("both" if n == 2 else f"all {n}") if k == n else ("one" if k == 1 else number_word(k))
        parts.append(f"{one if k == 1 else many} in {where}")
    if n == 1:
        return "with " + " and ".join(parts) if parts else ""
    return ", ".join(parts)


def progress(g: GoalRow, history: History) -> Progress:
    """Progress since the goal was set (``history`` = the driver's real driving)."""
    m = measure(g, history)
    if g.status == "achieved" and g.achieved_value is not None:
        return _achieved_progress(g, history, m)
    target = g.target
    if g.kind == "lap_time":
        baseline = g.baseline if g.baseline is not None else first_measurement(g, history)
        cur = m.value
        met = cur is not None and cur < target
        to_go = None if cur is None else max(0.0, cur - target)
        if cur is None and baseline is not None and baseline > target:
            text = f"{gap_s(baseline - target)} s to go from your best {lap_time(baseline)}"
            simple = f"{about_s(baseline - target).capitalize()} to go"
        elif cur is None:
            text, simple = "No clean lap here since you set it", "No clean lap here yet"
        elif met:
            text, simple = f"Reached: {lap_time(cur)}", f"Done: {lap_time(cur)}"
        else:
            assert to_go is not None
            text = f"{gap_s(to_go)} s to go · best since you set it {lap_time(cur)}"
            simple = f"{about_s(to_go).capitalize()} to go"
        frac = _fraction_lower_better(baseline, cur, target, met)
        return Progress(baseline, cur, target, frac, to_go, met, m.session_id, m.lap_id, m.sessions_since, text, simple)
    if g.kind == "clean_streak":
        n = round(target)
        cur = m.value or 0.0
        met = cur >= target
        if cur <= 0:
            text, simple = "No clean laps since you set it", "No clean laps yet"
        elif met:
            text, simple = f"Reached: {round(cur)} clean laps in a row", f"Done: {round(cur)} clean laps in a row"
        else:
            text = f"Best since you set it: {round(cur)} of {n} laps"
            simple = f"{round(cur)} of {n} clean laps in a row so far"
        frac = 1.0 if met else None if cur <= 0 or target <= 0 else min(1.0, cur / target)  # no empty bar
        to_go = max(0.0, target - cur)
        return Progress(
            g.baseline, cur, target, frac, to_go, met, m.session_id, m.lap_id, m.sessions_since, text, simple
        )
    if g.kind == "consistency":
        k = g.window_laps
        baseline = g.baseline if g.baseline is not None else first_measurement(g, history)
        cur = m.value
        met = cur is not None and cur <= target
        if cur is None:
            # race lap 1 never counts for steady laps: say so, or a clean start looks forgotten
            raced = any(s.is_race for s in _scope_sessions(g, history) if _counted_since(g, history, s))
            note = " (race lap 1 does not count)" if raced else ""
            text = f"No run of {k} clean laps to measure since you set it{note}"
            simple = f"No run of {k} clean laps to measure yet{note}"
        elif met:
            text = f"Reached: {k} laps within {seconds(cur, tenths_when_whole=False)} s"
            simple = f"Done: {k} steady laps"
        else:
            text = (
                f"Steadiest {k} laps since you set it: within {seconds(cur, tenths_when_whole=False)} s "
                f"(target {seconds(target)} s)"
            )
            simple = f"Your steadiest {k} laps so far were within {cur / 1000:.1f} s (goal {seconds(target)} s)"
        to_go = None if cur is None else max(0.0, cur - target)
        frac = _fraction_lower_better(baseline, cur, target, met)
        return Progress(baseline, cur, target, frac, to_go, met, m.session_id, m.lap_id, m.sessions_since, text, simple)
    # race_clean
    races = races_since(g, history)
    met_race = next(((s, o) for s, o in races if o.meets(g.rule)), None)
    if met_race is not None:
        s = met_race[0]
        where = f"{s.track_name or 'a race'}, {short_date(s.started_unix)}"
        text = simple = f"Done: {where}"
    elif not races:
        text, simple = "No race recorded from lap 1 to the flag since you set it", "No whole race recorded yet"
    else:
        n = len(races)
        issues = _race_issues([o for _, o in races], g.rule)
        head = f"{n} race{'s' if n != 1 else ''} finished since you set it"
        text = (f"{head}: {issues}" if n > 1 else f"{head}, {issues}") if issues else head
        simple = f"Not yet: {n} race{'s' if n != 1 else ''} finished since you set it"
    met = met_race is not None
    return Progress(
        None,
        1.0 if met else 0.0,
        target,
        1.0 if met else None,  # a race is reached or not: no part-way bar
        0.0 if met else 1.0,
        met,
        met_race[0].id if met_race else None,
        None,
        len(races),
        text,
        simple,
    )


def achieved_value_text(kind: str, value: float, params: Mapping[str, Any]) -> str:
    if kind == "lap_time":
        return lap_time(value)
    if kind == "clean_streak":
        return f"{round(value)} clean laps in a row"
    if kind == "consistency":
        return f"{params.get('window_laps', 5)} laps within {seconds(value, tenths_when_whole=False)} s"
    return "a clean race"


def _achieved_progress(g: GoalRow, history: History, m: Measure) -> Progress:
    value = g.achieved_value
    assert value is not None
    if g.kind == "race_clean":
        s = next((x for x in history.sessions if x.id == g.achieved_session_id), None)
        when = g.achieved_unix if s is None else s.started_unix
        where = f"{(s.track_name if s else None) or 'a race'}, {short_date(when or g.created_unix)}"
        text = simple = f"Done: {where}"
    else:
        shown = achieved_value_text(g.kind, value, g.params)
        text, simple = f"Reached: {shown}", f"Done: {shown}"
    return Progress(
        g.baseline,
        value,
        g.target,
        1.0,
        0.0,
        True,
        g.achieved_session_id,
        g.achieved_lap_id,
        m.sessions_since,
        text,
        simple,
    )


# ---------------------------------------------------------------------------------------------- JSON (API shape)
def labelled(g: GoalRow, history: History) -> GoalRow:
    """A goal set before any session at its track has no labels: take them from the driver's latest session there
    (display only; the scope itself never changes)."""
    sc = g.scope
    if sc.track_id is None or sc.track_name:
        return g
    track = next((s for s in reversed(history.sessions) if s.game == sc.game and s.track_id == sc.track_id), None)
    if track is None:
        return g
    car_name = sc.car_name
    if car_name is None and sc.car_id is not None:
        car = next((s for s in reversed(history.sessions) if s.car_id == sc.car_id and s.car_name), None)
        car_name = None if car is None else car.car_name
    elif car_name is None and sc.car_class is not None:
        car_name = track.car_name
    return replace(g, scope=replace(sc, track_name=track.track_name, car_name=car_name))


def achievement_json(g: GoalRow, history: History, owned: set[str], lap_numbers: Mapping[int, int]) -> dict[str, Any]:
    assert g.achieved_unix is not None
    n = lap_numbers.get(g.achieved_lap_id) if g.achieved_lap_id is not None else None
    when = short_date(g.achieved_unix)
    v = g.achieved_value
    if g.kind == "race_clean":
        s = next((x for x in history.sessions if x.id == g.achieved_session_id), None)
        shown = (s.track_name if s is not None else None) or "a race"
        text = f"Reached {when}: {shown}"
    else:
        shown = achieved_value_text(g.kind, v, g.params) if v is not None else "reached"
        text = f"Reached {when}: {shown}" + (f" on lap {n}" if n is not None else "")
    return {
        "unix": g.achieved_unix,
        "session_id": g.achieved_session_id,
        "lap_id": g.achieved_lap_id,
        "lap_number": n,
        "value": v,
        "session_owned": g.achieved_session_id is not None and g.achieved_session_id in owned,
        "text": text,
        "text_simple": f"Done {when}",
    }


def goal_json(
    g: GoalRow,
    history: History,
    *,
    owned: set[str] | None = None,
    lap_numbers: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    """The ``Goal`` object of the API contract (docs/ui/design-spec.md section 13, M2)."""
    g = labelled(g, history)
    title, simple = goal_titles(g)
    mine = owned if owned is not None else {s.id for s in history.sessions}
    return {
        "id": g.id,
        "driver_id": g.driver_id,
        "kind": g.kind,
        "status": g.status,
        "target": g.target,
        "params": dict(g.params),
        "scope": g.scope.to_dict(),
        "title": title,
        "title_simple": simple,
        "scope_text": g.scope.text(),
        "source": g.source,
        "basis": g.basis,
        "created_unix": g.created_unix,
        "achieved": None if g.achieved_unix is None else achievement_json(g, history, mine, lap_numbers or {}),
        "progress": progress(g, history).to_dict(),
    }
