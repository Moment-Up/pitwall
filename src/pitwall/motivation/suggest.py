"""Goal suggestions from the driver's own history: nothing invented, every number is one they drove.

At most four, in this order: a lap time (the scope asked for, else the scope of the driver's latest session with a
clean lap), a clean-lap run, steady laps, and a clean race (F1). A suggestion that would duplicate an active goal is
left out. Each carries ``create``: the exact ``POST /api/drivers/{id}/goals`` body that sets it.

Rules ([H] = heuristic):

* **Lap time** - steps: best lap minus the ideal lap (best sectors combined) and the recent gain (median of the
  last three new bests). The smaller step [H], clamped to 0.1 s .. 2.0 s for beginners / 1.0 s otherwise [H]; under
  50 ms there is no suggestion. Target = best - step, rounded up to a tenth, and at least 0.1 s under the best.
* **Clean laps** - best run in the last 30 days, plus one for beginners, else plus a quarter (at least one) [H];
  2 to 30 laps.
* **Steady laps** - 3 laps for beginners, else 5 (3 when no 5-lap window exists); 90 % of the best spread in the
  last 30 days, rounded down to a tenth, at least 0.3 s [H]. At one track: the scope's track when one is asked for,
  else the steadiest session for its lap length (spread / median lap) [H]; the goal is tied to that track.
* **Clean race** - F1 only, from races of the last 30 days with their length stored or the flag recorded: no
  penalties until one such finish exists, then no contact.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from pitwall.motivation import goals as G
from pitwall.motivation import rules
from pitwall.motivation.model import (
    GoalRow,
    History,
    Scope,
    SessionRow,
    gap_s,
    is_f1_game,
    lap_time,
    seconds,
    session_car_class,
    short_date,
)

MAX_SUGGESTIONS = 4
RECENT_DAYS = 30
MIN_STEP_MS = 50
STEP_FLOOR_MS = 100
STEP_CAP_MS = {"beginner": 2000}
DEFAULT_STEP_CAP_MS = 1000
STREAK_MAX_SUGGESTED = 30
SPREAD_FLOOR_MS = 300
NOT_ENOUGH_HERE = (
    "Not enough history here yet: Pitwall needs your best sectors or a recent improvement to suggest a target."
)
NO_CLEAN_LAP_HERE = "No clean lap here yet: set one and Pitwall can suggest a target."
NO_DRIVING = "Drive a few clean laps first: Pitwall suggests goals from your own driving."
ALL_SET = "Every goal Pitwall would suggest here is already set."


@dataclass(slots=True, frozen=True)
class Suggestion:
    kind: str
    target: float
    params: dict[str, Any]
    scope: Scope
    basis: dict[str, Any]
    from_session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        title, simple = G.titles(self.kind, self.target, self.params)
        create: dict[str, Any] = {
            "kind": self.kind,
            "target": self.target,
            "params": dict(self.params),
            "game": self.scope.game,
            "track_id": self.scope.track_id,
            "car_id": self.scope.car_id,
            "car_class": self.scope.car_class,
            "from_session_id": self.from_session_id,
            "source": "suggested",
            "basis": self.basis,
        }
        return {
            "kind": self.kind,
            "target": self.target,
            "params": dict(self.params),
            "scope": self.scope.to_dict(),
            "title": title,
            "title_simple": simple,
            "scope_text": self.scope.text(),
            "basis": self.basis,
            "create": create,
        }


def _basis(kind: str, text: str, simple: str, values: dict[str, Any], sessions: Sequence[str]) -> dict[str, Any]:
    return {
        "kind": kind,
        "text": text,
        "text_simple": simple,
        "values": values,
        "session_ids": list(dict.fromkeys(s for s in sessions if s)),
    }


def _where(s: SessionRow) -> str:
    return f"{s.track_name or 'unknown track'}, {short_date(s.started_unix)}"


# ---------------------------------------------------------------------------------------------- lap time
def lap_time_suggestion(
    history: History, scope: Scope, skill: str, now_unix: float, scope_session_id: str | None = None
) -> tuple[Suggestion | None, str | None]:
    """``(suggestion, none_reason)``."""
    sessions = [s for s in history.sessions if rules.scope_matches(scope, s)]
    laps = [lap for s in sessions for lap in history.laps_of(s.id)]
    pb = rules.fastest_clean(laps)
    if pb is None or pb.lap_time_ms is None:
        return None, NO_CLEAN_LAP_HERE
    pb_ms = pb.lap_time_ms
    ideal = rules.ideal_lap(laps)
    bests = rules.session_bests(sessions, history.laps)
    gain = rules.recent_gain_ms(bests, now_unix)
    steps: list[tuple[int, str]] = []
    if ideal is not None and ideal <= pb_ms:
        steps.append((pb_ms - ideal, "ideal_lap"))
    if gain is not None and gain > 0:
        steps.append((gain, "recent_gain"))
    if not steps:
        return None, NOT_ENOUGH_HERE
    step, kind = min(steps)
    if step < MIN_STEP_MS:
        return None, NOT_ENOUGH_HERE
    cap = STEP_CAP_MS.get(skill, DEFAULT_STEP_CAP_MS)
    clamped = max(STEP_FLOOR_MS, min(cap, step))
    t = pb_ms - clamped
    target = math.ceil(t / 100) * 100
    floored = target > pb_ms - 100
    if floored:
        target = math.floor((pb_ms - 100) / 100) * 100
    if target < G.LAP_TIME_MIN_MS:
        return None, NOT_ENOUGH_HERE
    gain_sessions = [b.session.id for b in bests if b.gain_ms is not None][-rules.RECENT_GAIN_SESSIONS :]
    parts: list[str] = []
    if ideal is not None and ideal <= pb_ms:
        parts.append(
            f"Your best sectors here add up to {lap_time(ideal)}, {gap_s(pb_ms - ideal)} s quicker than your best "
            f"lap ({lap_time(pb_ms)})."
        )
    if gain is not None and gain > 0:
        n_gains = len(gain_sessions)
        if n_gains <= 1:
            parts.append(f"Your last new best was {gap_s(gain)} s quicker than the one before.")
        else:
            parts.append(f"Your last {n_gains} new bests here were {gap_s(gain)} s quicker each, as a median.")
    kept = f" (a step is kept between {STEP_FLOOR_MS / 1000:.1f} and {cap / 1000:.1f} s)" if clamped != step else ""
    if floored:
        parts.append(f"Target: at least 0.1 s under your best lap, in tenths of a second{kept}.")
    else:
        parts.append(f"Target: your best lap minus {gap_s(clamped)} s{kept}, rounded up to a tenth.")
    simple = (
        f"Your best lap here is {lap_time(pb_ms)}. Your best sectors add up to {lap_time(ideal)}, so "
        f"{lap_time(target)} is within reach."
        if kind == "ideal_lap" and ideal is not None
        else f"Your best lap here is {lap_time(pb_ms)} and you keep getting faster, so {lap_time(target)} is next."
    )
    basis = _basis(
        kind,
        " ".join(parts),
        simple,
        {"pb_ms": pb_ms, "ideal_ms": ideal, "recent_gain_ms": gain, "step_ms": clamped, "cap_ms": cap},
        [pb.session_id, *gain_sessions],
    )
    return Suggestion("lap_time", float(target), {}, scope, basis, scope_session_id), None


# ---------------------------------------------------------------------------------------------- clean laps, steady laps
def _recent(history: History, now_unix: float) -> list[SessionRow]:
    return [s for s in history.sessions if s.started_unix >= now_unix - RECENT_DAYS * 86_400]


def clean_streak_suggestion(history: History, skill: str, now_unix: float) -> Suggestion | None:
    best: tuple[int, SessionRow] | None = None
    for s in _recent(history, now_unix):
        n = len(rules.best_run(history.laps_of(s.id)))
        if n and (best is None or n > best[0]):
            best = (n, s)
    if best is None:
        return None
    b, s = best
    target = b + 1 if skill == "beginner" else b + max(1, round(b / 4))
    target = max(2, min(STREAK_MAX_SUGGESTED, target))
    if target <= b:
        return None
    basis = _basis(
        "best_streak",
        f"Your best run is {b} clean laps in a row ({_where(s)}).",
        f"Your best is {b} clean laps in a row.",
        {"best_run": b},
        [s.id],
    )
    return Suggestion("clean_streak", float(target), {}, Scope(), basis)


def _track_scope(s: SessionRow) -> Scope:
    return Scope(game=s.game, track_id=s.track_id, track_name=s.track_name, track_length_m=s.track_length_m)


def _class_scope(s: SessionRow) -> Scope:
    """The track and, in an F1 game that reports its formula, the car class (``f1_25:formula:F2``): an F2 car's lap
    spread says nothing about an F1 car's at the same track (F2 support). Other games: the track only."""
    cc = session_car_class(s) if is_f1_game(s.game) else None
    return replace(_track_scope(s), car_class=cc, car_name=s.car_name if cc else None)


def consistency_suggestion(
    history: History, skill: str, now_unix: float, scope: Scope | None = None
) -> Suggestion | None:
    """Steady laps at one track: a spread learned on a 23-second lap means nothing on a 95-second one, so the
    suggestion is tied to the track it was learned at (the scope's track when one is asked for; else the steadiest
    session for its lap length, as spread / median lap time) and, in F1 games, to the car class it was driven in
    (``_class_scope``)."""
    recent = [s for s in _recent(history, now_unix) if s.track_id is not None]
    if scope is not None and scope.track_id is not None:
        recent = [s for s in recent if rules.scope_matches(_track_scope_of(scope), s)]

    def steadiest(k: int) -> tuple[int, SessionRow] | None:
        best: tuple[float, int, SessionRow] | None = None
        for s in recent:
            w = rules.best_window(history.laps_of(s.id), k, s.session_type)
            if w is None:
                continue
            times = sorted(lap.lap_time_ms for lap in w.laps if lap.lap_time_ms is not None)
            rel = w.spread_ms / times[len(times) // 2] if times else float(w.spread_ms)
            if best is None or rel < best[0]:
                best = (rel, w.spread_ms, s)
        return None if best is None else (best[1], best[2])

    k = 3 if skill == "beginner" else 5
    found = steadiest(k)
    if found is None and k == 5:
        k, found = 3, steadiest(3)
    if found is None:
        return None
    spread, s = found
    if spread <= SPREAD_FLOOR_MS:
        return None
    target = max(SPREAD_FLOOR_MS, math.floor(spread * 0.9 / 100) * 100)
    if target >= spread:
        target = math.floor((spread - 100) / 100) * 100
    if target < G.SPREAD_MIN_MS:
        return None
    basis = _basis(
        "best_window",
        f"Your steadiest {k} clean laps in a row were within {seconds(spread, tenths_when_whole=False)} s "
        f"({_where(s)}).",
        f"Your {k} steadiest laps at {s.track_name or 'this track'} were within {spread / 1000:.1f} s of each other.",
        {"best_spread_ms": spread, "window_laps": k},
        [s.id],
    )
    return Suggestion("consistency", float(target), {"window_laps": k}, _class_scope(s), basis)


def _track_scope_of(scope: Scope) -> Scope:
    return Scope(
        game=scope.game, track_id=scope.track_id, track_length_m=scope.track_length_m, car_class=scope.car_class
    )


# ---------------------------------------------------------------------------------------------- clean race (F1)
def _judgeable(s: SessionRow, history: History) -> bool:
    """A race Pitwall could judge: its length is stored (schema v3) or the chequered flag was recorded."""
    if s.total_laps is not None and s.total_laps > 0:
        return True
    return any(e.get("kind") == rules.CHEQUERED_FLAG for e in history.events.get(s.id, ()))


def race_suggestion(history: History, now_unix: float) -> Suggestion | None:
    races = [s for s in _recent(history, now_unix) if s.is_f1 and s.is_race and _judgeable(s, history)]
    if not races:
        return None
    outcomes = [rules.race_outcome(s, history.laps_of(s.id), history.events.get(s.id, ())) for s in races]
    done = [o for o in outcomes if o.evaluable]
    n_np = sum(1 for o in done if o.no_penalties)
    n_nc = sum(1 for o in done if o.no_contact)
    if n_np == 0:
        rule = "no_penalties"
    elif n_nc == 0:
        rule = "no_contact"
    else:
        return None
    n = len(done)

    def count(k: int) -> str:
        return "none" if k == 0 else str(k)

    if n == 0:
        text = (
            f"{len(races)} race{'s' if len(races) != 1 else ''} in the last {RECENT_DAYS} days, none recorded "
            "from lap 1 to the flag."
        )
    else:
        text = (
            f"{n} race{'s' if n != 1 else ''} finished in the last {RECENT_DAYS} days: {count(n_np)} without a penalty"
        )
        text += "." if rule == "no_penalties" else f", {count(n_nc)} without contact."
    simple = (
        "Next: a whole race with no penalties." if rule == "no_penalties" else "Next: a whole race with no contact."
    )
    basis = _basis(
        "race_history",
        text,
        simple,
        {"races": n, "no_penalties": n_np, "no_contact": n_nc},
        [o.session_id for o in done],
    )
    return Suggestion("race_clean", 1.0, {"rule": rule}, Scope(), basis)


# ---------------------------------------------------------------------------------------------- all
def _duplicates_active(s: Suggestion, active: Sequence[GoalRow]) -> bool:
    for g in active:
        if g.status != "active" or g.kind != s.kind or not G.same_scope(g.scope, s.scope):
            continue
        if s.kind in ("lap_time", "clean_streak"):
            return True
        if g.params == s.params:
            return True
    return False


def suggestions(
    history: History,
    scope: Scope | None,
    skill: str,
    active: Sequence[GoalRow],
    now_unix: float,
    scope_session_id: str | None = None,
) -> tuple[list[Suggestion], str | None]:
    """``(suggestions, none_reason)``; ``none_reason`` says why there is no lap-time suggestion."""
    out: list[Suggestion] = []
    reason: str | None = None
    if scope is None:
        reason = NO_DRIVING
    else:
        lt, reason = lap_time_suggestion(history, scope, skill, now_unix, scope_session_id)
        if lt is not None:
            out.append(lt)
    for s in (
        clean_streak_suggestion(history, skill, now_unix),
        consistency_suggestion(history, skill, now_unix, scope),
        race_suggestion(history, now_unix),
    ):
        if s is not None:
            out.append(s)
    kept = [s for s in out if not _duplicates_active(s, active)]
    if scope is not None and not any(s.kind == "lap_time" for s in out) and reason is None:
        reason = NOT_ENOUGH_HERE
    if out and not kept:
        reason = ALL_SET
    return kept[:MAX_SUGGESTIONS], reason
