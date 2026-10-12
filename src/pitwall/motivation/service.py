"""The motivation service: the database side of goals, badges, recaps and digests.

Shared by the API (``api/routes_motivation.py``), the CLI and the worker (``motivation.worker``). Reads use
short-lived read connections; every write goes through the single ``DbWriter`` (goal create / patch / delete,
marking a goal reached, storing a baseline). Business-rule refusals are decided inside the writer job and returned,
then raised on the caller's thread (the ``drivers.py`` pattern): the writer logs every exception as a failed write,
and a 409 is not one.

History: a driver's real driving only - never replays (``repo._DRIVEN``) and never synthetic sessions, unless a
caller opts in (the API's ``synthetic=true`` for development, flagged in the result; the worker's test-only flag).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING, Any

from pitwall.drivers import Driver, coaching_limits
from pitwall.motivation import badges as B
from pitwall.motivation import digest as D
from pitwall.motivation import goals as G
from pitwall.motivation import recap as R
from pitwall.motivation import rules
from pitwall.motivation import suggest as S
from pitwall.motivation.model import (
    GOAL_STATUSES,
    GoalRow,
    History,
    LapRow,
    Scope,
    SessionRow,
    local_date,
)
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

if TYPE_CHECKING:
    from pitwall.core.live import LiveState
    from pitwall.core.session_analysis import SessionAnalysis, SessionAnalyzer

log = logging.getLogger(__name__)

ACHIEVED_DAYS = 30
RECONCILED_KEPT = 64


class MotivationNotFound(LookupError):
    """Unknown driver, goal or session (404)."""


@dataclass(slots=True, frozen=True)
class _Refused:
    error: Exception


def _refuse(conn: sqlite3.Connection, error: Exception) -> _Refused:
    conn.rollback()
    return _Refused(error)


def _needs_timing(evs: list[dict[str, Any]], laps: list[LapRow], total: int | None) -> bool:
    """A safety car, or a chequered flag in a race whose last lap (``total_laps``) is not stored complete (a lapped
    finish to judge). Every F1 race has a flag: the full distance needs no lap times."""
    kinds = {e.get("kind") for e in evs}
    if rules.SAFETY_CAR in kinds:
        return True
    if rules.CHEQUERED_FLAG not in kinds:
        return False
    return not any(
        lap.lap_number == total and lap.lap_time_ms is not None and "incomplete" not in lap.flags for lap in laps
    )


def _race_timing(
    conn: sqlite3.Connection,
    laps: dict[str, list[LapRow]],
    events: Mapping[str, list[dict[str, Any]]],
    totals: Mapping[str, int | None],
) -> None:
    """F1 races with a safety car or a lapped finish to judge: give their laps their receive times (lap meta) and mark
    the laps behind the safety car (``rules.behind_safety_car``). Other sessions are left as they are."""
    need = [sid for sid, evs in events.items() if _needs_timing(evs, laps.get(sid, []), totals.get(sid))]
    if not need:
        return
    times = repo.motivation_lap_times(conn, need)
    for sid in need:
        spans = rules.safety_car_spans(events[sid])
        marked: list[LapRow] = []
        for lap in laps.get(sid, []):
            start, end = times.get(lap.id, (None, None))
            timed = replace(lap, t_start_ns=start, t_end_ns=end)
            marked.append(replace(timed, safety_car=rules.behind_safety_car(timed, spans)))
        laps[sid] = marked


def load_history(conn: sqlite3.Connection, driver_id: int, *, include_synthetic: bool = False) -> History:
    """A driver's real driving, oldest first, with laps (columns before ``meta``) and F1 race events (incidents,
    the chequered flag, the safety car)."""
    sessions = [
        SessionRow.from_row(r) for r in repo.motivation_sessions(conn, driver_id, include_synthetic=include_synthetic)
    ]
    raw = repo.motivation_laps(conn, [s.id for s in sessions])
    laps = {sid: [LapRow.from_row(d) for d in rows] for sid, rows in raw.items()}
    races = [s.id for s in sessions if s.is_race and s.is_f1]
    events = repo.motivation_events(conn, races) if races else {}
    _race_timing(conn, laps, events, {s.id: s.total_laps for s in sessions})
    return History(sessions, laps, events)


def session_history(conn: sqlite3.Connection, s: SessionRow) -> History:
    """One session on its own (the worker's per-lap view)."""
    raw = repo.motivation_laps(conn, [s.id])
    events = repo.motivation_events(conn, [s.id]) if s.is_race and s.is_f1 else {}
    laps = {s.id: [LapRow.from_row(d) for d in raw.get(s.id, [])]}
    _race_timing(conn, laps, events, {s.id: s.total_laps})
    return History([s], laps, events)


class MotivationService:
    def __init__(
        self,
        db: Database,
        writer: DbWriter | None = None,
        *,
        analyzer: SessionAnalyzer | None = None,
        live: LiveState | None = None,
        include_synthetic: bool = False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db = db
        self.writer = writer
        self._analyzer = analyzer
        self.live = live
        self.include_synthetic = include_synthetic  # worker only (tests): synthetic sessions count for goals
        self.clock = clock
        self._lock = threading.Lock()
        self._reconciled: OrderedDict[str, None] = OrderedDict()

    # ------------------------------------------------------------------ helpers
    @property
    def analyzer(self) -> SessionAnalyzer:
        if self._analyzer is None:
            from pitwall.core.session_analysis import SessionAnalyzer

            with self._lock:
                if self._analyzer is None:
                    self._analyzer = SessionAnalyzer(self.db)
        return self._analyzer

    def _write(self, job: Callable[[sqlite3.Connection], Any]) -> Any:
        if self.writer is None:
            raise RuntimeError("this motivation service is read-only (no DbWriter)")
        out = self.writer.call(job)
        if isinstance(out, _Refused):
            raise out.error
        return out

    def driver(self, driver_id: int) -> Driver:
        with self.db.read() as c:
            row = repo.get_driver(c, driver_id)
        if row is None:
            raise MotivationNotFound(f"driver {driver_id} not found")
        return Driver.from_row(row)

    def history(self, driver_id: int, *, include_synthetic: bool = False) -> History:
        with self.db.read() as c:
            return load_history(c, driver_id, include_synthetic=include_synthetic)

    def _goals(self, c: sqlite3.Connection, driver_id: int, statuses: tuple[str, ...] | None = None) -> list[GoalRow]:
        return [GoalRow.from_row(r) for r in repo.list_goals(c, driver_id, statuses)]

    @staticmethod
    def _owned_and_laps(c: sqlite3.Connection, driver_id: int, goals: list[GoalRow]) -> tuple[set[str], dict[int, int]]:
        owned = {
            g.achieved_session_id
            for g in goals
            if g.achieved_session_id is not None and repo.session_driver_id(c, g.achieved_session_id) == driver_id
        }
        ids = [g.achieved_lap_id for g in goals if g.achieved_lap_id is not None]
        return owned, repo.lap_numbers(c, ids) if ids else {}

    def _goal_json_fn(
        self, c: sqlite3.Connection, driver_id: int, goals: list[GoalRow]
    ) -> Callable[[GoalRow, History], dict[str, Any]]:
        owned, laps = self._owned_and_laps(c, driver_id, goals)

        def fn(g: GoalRow, history: History) -> dict[str, Any]:
            return G.goal_json(g, history, owned=owned, lap_numbers=laps)

        return fn

    # ------------------------------------------------------------------ goals: reads
    def goals_response(
        self, driver_id: int, statuses: tuple[str, ...] = ("active", "achieved"), achieved_days: int = ACHIEVED_DAYS
    ) -> dict[str, Any]:
        driver = self.driver(driver_id)
        bad = [s for s in statuses if s not in GOAL_STATUSES]
        if bad:
            raise G.invalid(f"unknown status {bad[0]!r}; expected active, achieved or archived")
        now = self.clock()
        with self.db.read() as c:
            goals = self._goals(c, driver_id, statuses)
            history = load_history(c, driver_id)
            fn = self._goal_json_fn(c, driver_id, goals)
            active = repo.count_goals(c, driver_id, "active")
        horizon = now - achieved_days * 86_400
        shown = [g for g in goals if g.status != "achieved" or (g.achieved_unix or 0.0) >= horizon]
        return {
            "driver_id": driver_id,
            "simple": driver.coaching.simple_wording,
            "goals": [fn(g, history) for g in shown],
            "limits": {"max_active": G.MAX_ACTIVE, "active": active},
        }

    def goal(self, driver_id: int, goal_id: int) -> dict[str, Any]:
        with self.db.read() as c:
            row = repo.get_goal(c, goal_id)
            if row is None or int(row["driver_id"]) != driver_id:
                raise MotivationNotFound(f"goal {goal_id} not found")
            g = GoalRow.from_row(row)
            history = load_history(c, driver_id)
            fn = self._goal_json_fn(c, driver_id, [g])
        return fn(g, history)

    # ------------------------------------------------------------------ goals: writes
    def _resolve_scope(
        self, c: sqlite3.Connection, driver_id: int, body: Mapping[str, Any]
    ) -> tuple[Scope, str | None]:
        kind = body.get("kind")

        def text(key: str) -> str | None:
            v = body.get(key)
            if v is None:
                return None
            if not isinstance(v, str) or not v.strip():
                raise G.invalid(f"{key} must be a non-empty string or null")
            return v.strip()

        game, track_id, car_id, car_class = text("game"), text("track_id"), text("car_id"), text("car_class")
        track_name = car_name = None
        length: float | None = None
        sid = text("from_session_id")
        if sid is not None:
            row = repo.motivation_session(c, sid)
            if row is None or row.get("driver_id") != driver_id:
                raise G.invalid("from_session_id is not one of this driver's sessions", "unknown_session")
            s = SessionRow.from_row(row)
            if s.replay:
                raise G.invalid("a replay is not anyone's driving: pick one of the driver's own sessions", "replay")
            game = game or s.game
            if kind != "race_clean":
                track_id = track_id or s.track_id
                if car_class is None:
                    car_id = car_id or s.car_id
            if track_id == s.track_id:
                track_name, length, car_name = s.track_name, s.track_length_m, s.car_name
        if track_id is not None and game is not None and track_name is None:
            labels = repo.track_labels(c, game, track_id, car_id)
            if labels is not None:
                track_name = labels.get("track_name")
                length = labels.get("track_length_m")
                car_name = labels.get("car_name") if (car_id or car_class) else None
        scope = Scope(
            game=game,
            track_id=track_id,
            track_name=track_name,
            track_length_m=length if track_id is not None else None,
            car_id=car_id,
            car_class=car_class,
            car_name=car_name if (car_id or car_class) else None,
        )
        return scope, sid

    def create_goal(self, driver_id: int, body: Mapping[str, Any]) -> dict[str, Any]:
        """Validate (422), check against stored state inside the writer job (409), insert; returns the Goal."""
        self.driver(driver_id)
        now = self.clock()
        with self.db.read() as c:
            scope, _sid = self._resolve_scope(c, driver_id, body)
            history = load_history(c, driver_id)
        params = body.get("params")
        if params is not None and not isinstance(params, Mapping):
            raise G.invalid("params must be an object")
        basis = body.get("basis")
        if basis is not None and not isinstance(basis, Mapping):
            raise G.invalid("basis must be an object")
        new = G.validate_new(body.get("kind"), body.get("target"), params, scope, body.get("source", "manual"), basis)
        pb = G.pb_in_scope(new.scope, history) if new.kind == "lap_time" else None
        pb_ms = None if pb is None else pb.lap_time_ms
        baseline = G.creation_baseline(new.kind, new.scope, new.params, history, now)

        def job(c: sqlite3.Connection) -> int | _Refused:
            if repo.get_driver(c, driver_id) is None:
                return _refuse(c, MotivationNotFound(f"driver {driver_id} not found"))
            active = self._goals(c, driver_id, ("active",))
            err = G.conflicts(new, active, pb_ms)
            if err is not None:
                return _refuse(c, err)
            sc = new.scope
            return repo.insert_goal(
                c,
                driver_id=driver_id,
                kind=new.kind,
                target=new.target,
                params=new.params,
                game=sc.game,
                track_id=sc.track_id,
                track_name=sc.track_name,
                track_length_m=sc.track_length_m,
                car_id=sc.car_id,
                car_class=sc.car_class,
                car_name=sc.car_name,
                baseline=baseline,
                source=new.source,
                basis=new.basis,
            )

        goal_id = int(self._write(job))
        log.info("goal %s set for driver %s (%s, target %s)", goal_id, driver_id, new.kind, new.target)
        return self.goal(driver_id, goal_id)

    def patch_goal(self, driver_id: int, goal_id: int, status: object) -> dict[str, Any]:
        """``active`` (unarchive, or reopen a reached goal: its stored achievement is cleared) or ``archived``.

        Reopening is for a goal reached in a session that now belongs to someone else: when the driver's own driving
        since the goal was set still reaches it, it is refused (409 ``still_reached``) - reopened, the same lap would
        reach it again and be celebrated twice. To go again, the driver sets it as a new goal."""
        if status not in ("active", "archived"):
            raise G.invalid("status must be active or archived")

        def job(c: sqlite3.Connection) -> _Refused | None:
            row = repo.get_goal(c, goal_id)
            if row is None or int(row["driver_id"]) != driver_id:
                return _refuse(c, MotivationNotFound(f"goal {goal_id} not found"))
            g = GoalRow.from_row(row)
            if g.status == status:
                return None
            if status == "archived":
                repo.set_goal_status(c, goal_id, "archived", clear_achievement=False)
                return None
            active = [x for x in self._goals(c, driver_id, ("active",)) if x.id != goal_id]
            err = G.conflicts(G.NewGoal(g.kind, g.target, g.params, g.scope, g.source, g.basis), active, None)
            if err is not None:
                return _refuse(c, err)
            if g.achieved_unix is not None and G.first_hit(g, load_history(c, driver_id)) is not None:
                msg = "Your own driving still reaches this goal. To go for it again, add it as a new goal."
                return _refuse(c, G.conflict("still_reached", msg))
            repo.set_goal_status(c, goal_id, "active", clear_achievement=g.achieved_unix is not None)
            return None

        self.driver(driver_id)
        self._write(job)
        return self.goal(driver_id, goal_id)

    def delete_goal(self, driver_id: int, goal_id: int) -> int:
        def job(c: sqlite3.Connection) -> _Refused | None:
            row = repo.get_goal(c, goal_id)
            if row is None or int(row["driver_id"]) != driver_id:
                return _refuse(c, MotivationNotFound(f"goal {goal_id} not found"))
            repo.delete_goal(c, goal_id)
            return None

        self.driver(driver_id)
        self._write(job)
        return goal_id

    # ------------------------------------------------------------------ suggestions
    def suggestions_response(
        self,
        driver_id: int,
        *,
        game: str | None = None,
        track_id: str | None = None,
        car: str | None = None,
        from_session_id: str | None = None,
    ) -> dict[str, Any]:
        driver = self.driver(driver_id)
        now = self.clock()
        with self.db.read() as c:
            history = load_history(c, driver_id)
            active = self._goals(c, driver_id, ("active",))
        scope_session: SessionRow | None = None
        if from_session_id is not None:
            scope_session = next((s for s in history.sessions if s.id == from_session_id), None)
            if scope_session is None:
                raise G.invalid("from_session_id is not one of this driver's real sessions", "unknown_session")
        elif game is not None and track_id is not None:
            for s in reversed(history.sessions):
                if s.game == game and s.track_id == track_id and (car is None or s.car_id == car):
                    scope_session = s
                    break
        elif game is None and track_id is None:
            for s in reversed(history.sessions):
                if s.track_id is not None and rules.fastest_clean(history.laps_of(s.id)) is not None:
                    scope_session = s
                    break
        scope: Scope | None
        if scope_session is not None:
            scope = Scope.of_session(scope_session)
        elif game is not None and track_id is not None:
            scope = Scope(game=game, track_id=track_id, car_id=car)
        else:
            scope = None
        if scope is not None and scope.track_id is not None and scope.track_id.startswith("synthetic:"):
            scope = None
        items, reason = S.suggestions(
            history, scope, driver.preferences.skill_level, active, now, scope_session.id if scope_session else None
        )
        scope_json: dict[str, Any] | None = None
        if scope is not None:
            scope_json = scope.to_dict()
            if scope_session is not None:
                # the class of this car when the game reports one: the form's "any {class} car" option
                cc = Scope.of_session(scope_session, by_class=True)
                scope_json["car_class"] = cc.car_class
        return {
            "driver_id": driver_id,
            "simple": driver.coaching.simple_wording,
            "scope": scope_json,
            "suggestions": [s.to_dict() for s in items],
            "none_reason": reason,
        }

    # ------------------------------------------------------------------ badges and streaks
    def badges_response(self, driver_id: int, *, include_synthetic: bool = False) -> dict[str, Any]:
        driver = self.driver(driver_id)
        now = self.clock()
        with self.db.read() as c:
            history = load_history(c, driver_id, include_synthetic=include_synthetic)
            goals = self._goals(c, driver_id)
        return {
            "driver_id": driver_id,
            "simple": driver.coaching.simple_wording,
            "include_synthetic": include_synthetic,
            "badges": [b.to_dict() for b in B.badges(history, goals)],
            "streaks": B.streaks(history, now),
        }

    # ------------------------------------------------------------------ digest
    def digest(self, driver_id: int, week: date | None = None, *, include_synthetic: bool = False) -> dict[str, Any]:
        driver = self.driver(driver_id)
        now = self.clock()
        this_week = rules.week_start(local_date(now))
        start = rules.week_start(week) if week is not None else this_week
        if start > this_week:
            raise G.invalid("That week has not started yet", "future_week")
        with self.db.read() as c:
            history = load_history(c, driver_id, include_synthetic=include_synthetic)
            goals = self._goals(c, driver_id)
            fn = self._goal_json_fn(c, driver_id, goals)
        return D.build_digest(
            {"id": driver.id, "name": driver.name, "skill_level": driver.preferences.skill_level},
            history,
            goals,
            start,
            now,
            include_synthetic=include_synthetic,
            goal_json=fn,
        )

    # ------------------------------------------------------------------ recap
    def recap(self, session_id: str, *, analysis: SessionAnalysis | None = None) -> dict[str, Any] | None:
        """``SessionRecap`` for a session, or None when it does not exist. ``analysis``: the session's analysis when
        the caller has it already (the session report), so it is not computed twice."""
        with self.db.read() as c:
            row = repo.motivation_session(c, session_id)
            if row is None:
                return None
            s = SessionRow.from_row(row)
            laps = [LapRow.from_row(d) for d in repo.motivation_laps(c, [session_id]).get(session_id, [])]
            drow = repo.get_driver(c, s.driver_id) if s.driver_id is not None else None
            driver = Driver.from_row(drow) if drow is not None else None
            counts = driver is not None and not s.synthetic and not s.replay
            history = load_history(c, driver.id) if driver is not None and counts else None
            goals = self._goals(c, driver.id) if driver is not None else []
            fn = self._goal_json_fn(c, driver.id, goals) if driver is not None else None
            lap_nums = repo.lap_numbers(c, [g.achieved_lap_id for g in goals if g.achieved_lap_id is not None])
        why = None
        if s.synthetic:
            why = R.WHY_SYNTHETIC
        elif s.replay:
            why = R.WHY_REPLAY
        elif driver is None:
            why = R.WHY_NO_OWNER
        sa = analysis if analysis is not None and analysis.session.get("id") == session_id else None
        if sa is None:
            sa = self.analyzer.analyse(session_id)
        limits = driver.coaching if driver is not None else coaching_limits("advanced")
        inp = R.RecapInput(
            session=s,
            laps=laps,
            observations=sa.observations if sa is not None else {},
            compared=len(sa.comparisons) if sa is not None else 0,
            limits=limits,
            counts=counts,
            history=history.until(session_id) if history is not None else None,
            goals=goals if counts else [],
            why_progress=why,
            now_unix=time.time(),
        )
        rec = R.build_recap(inp, lap_nums)
        full = history if history is not None else History([s], {s.id: laps}, {})
        achieved = [g for g in goals if g.achieved_session_id == session_id] if counts else []
        in_scope = [g for g in goals if g.status == "active" and rules.scope_matches(g.scope, s)] if counts else []
        in_scope.sort(key=lambda g: (g.kind != "lap_time", -g.created_unix, g.id))
        earned = [b for b in B.badges(history, goals) if b.session_id == session_id] if history is not None else []
        live = self.live
        st = live.session_state if live is not None and live.session_id == session_id else None
        return {
            "session_id": session_id,
            "driver_id": None if driver is None else driver.id,
            "driver_name": None if driver is None else driver.name,
            "simple": limits.simple_wording,
            "synthetic": s.synthetic,
            "replay": s.replay,
            "ended": s.ended_unix is not None or (st is not None and st.state == "ended"),
            "laps": len(laps),
            "clean_laps": sum(1 for lap in laps if lap.clean),
            "things": {
                "went_well": None if rec.went_well is None else rec.went_well.to_dict(),
                "work_on": None if rec.work_on is None else rec.work_on.to_dict(),
                "progress": None if rec.progress is None else rec.progress.to_dict(),
            },
            "why_empty": rec.why,
            "goals_achieved": [fn(g, full) for g in achieved] if fn is not None else [],
            "goals_progress": [fn(g, full) for g in in_scope] if fn is not None else [],
            "badges_earned": [b.to_dict() for b in earned],
        }

    # ------------------------------------------------------------------ worker hooks (worker thread only)
    def _counting_session(self, c: sqlite3.Connection, session_id: str) -> SessionRow | None:
        row = repo.motivation_session(c, session_id)
        if row is None:
            return None
        s = SessionRow.from_row(row)
        if s.replay or s.driver_id is None or (s.synthetic and not self.include_synthetic):
            return None
        return s

    def _mark(self, g: GoalRow, hit: G.Hit) -> bool:
        assert self.writer is not None
        unix = self.clock()
        return bool(
            self.writer.call(
                lambda c: repo.mark_goal_achieved(
                    c, g.id, unix=unix, session_id=hit.session_id, lap_id=hit.lap_id, value=hit.value
                )
            )
        )

    def _set_baseline(self, g: GoalRow, value: float) -> None:
        assert self.writer is not None
        self.writer.call(lambda c: repo.set_goal_baseline_if_unknown(c, g.id, value))

    def _reconcile(self, s: SessionRow, goals: list[GoalRow]) -> None:
        """Once per session: a goal already met by driving outside this session is marked reached silently (a
        session re-assigned to the driver, a note the worker missed); unknown baselines are filled in."""
        if s.id in self._reconciled:
            return
        self._reconciled[s.id] = None
        while len(self._reconciled) > RECONCILED_KEPT:
            self._reconciled.popitem(last=False)
        assert s.driver_id is not None
        with self.db.read() as c:
            history = load_history(c, s.driver_id, include_synthetic=self.include_synthetic)
        others = history.without(s.id)
        for g in goals:
            hit = G.first_hit(g, others)
            if hit is not None:
                if self._mark(g, hit):
                    log.info(
                        "goal %s was already reached in session %s: marked without a celebration", g.id, hit.session_id
                    )
                continue
            if g.baseline is None and g.kind in ("lap_time", "consistency"):
                first = G.first_measurement(g, history)
                if first is not None:
                    self._set_baseline(g, first)

    def _note(self, s: SessionRow, hits: list[tuple[GoalRow, G.Hit]], lap: LapRow | None) -> dict[str, Any]:
        goals = []
        for g0, hit in hits:
            g = G.labelled(g0, History([s], {}, {}))
            title, simple = G.goal_titles(g)
            goals.append(
                {
                    "id": g.id,
                    "kind": g.kind,
                    "title": title,
                    "title_simple": simple,
                    "scope_text": g.scope.text(),
                    "track_name": g.scope.track_name or s.track_name,
                    "target": g.target,
                    "params": dict(g.params),
                    "value": hit.value,
                }
            )
        return {
            "kind": "goals_achieved",
            "session_id": s.id,
            "driver_id": s.driver_id,
            "lap_id": None if lap is None else lap.id,
            "lap_number": None if lap is None else lap.lap_number,
            "t": self.clock(),
            "goals": goals,
        }

    def on_lap(self, session_id: str, lap_id: int | None) -> dict[str, Any] | None:
        """After a live lap was stored: mark the goals this session reached (exactly once). Returns the note to
        publish, or None."""
        with self.db.read() as c:
            s = self._counting_session(c, session_id)
            if s is None or s.driver_id is None:
                return None
            if not repo.count_goals(c, s.driver_id, "active"):
                return None
            goals = self._goals(c, s.driver_id, ("active",))
        self._reconcile(s, goals)
        with self.db.read() as c:
            goals = [g for g in self._goals(c, s.driver_id, ("active",)) if rules.scope_matches(g.scope, s)]
            if not goals:
                return None
            current = session_history(c, s)
        laps = current.laps_of(s.id)
        lap = next((x for x in laps if x.id == lap_id), None)
        if lap_id is not None:  # this lap and the ones before it: a later lap has its own note coming
            current.laps[s.id] = [x for x in laps if x.id <= lap_id]
        hits: list[tuple[GoalRow, G.Hit]] = []
        for g in goals:
            if g.kind == "race_clean":
                continue
            hit = G.first_hit(g, current)
            if hit is not None:
                if self._mark(g, hit):
                    hits.append((g, hit))
            elif g.baseline is None and g.kind in ("lap_time", "consistency"):
                first = G.first_measurement(g, current)
                if first is not None:
                    self._set_baseline(g, first)
        return self._note(s, hits, lap) if hits else None

    def on_session_end(self, session_id: str) -> dict[str, Any] | None:
        """At (or after) the end of a live session: clean-race goals. Idempotent."""
        if self.writer is not None:
            self.writer.flush()  # the session's last events and laps were queued just before the end
        with self.db.read() as c:
            s = self._counting_session(c, session_id)
            if s is None or s.driver_id is None or not (s.is_race and s.is_f1):
                return None
            goals = self._goals(c, s.driver_id, ("active",))
        if not goals:
            return None
        self._reconcile(s, goals)
        with self.db.read() as c:
            goals = [
                g
                for g in self._goals(c, s.driver_id, ("active",))
                if g.kind == "race_clean" and rules.scope_matches(g.scope, s)
            ]
            if not goals:
                return None
            current = session_history(c, s)
        hits: list[tuple[GoalRow, G.Hit]] = []
        for g in goals:
            hit = G.first_hit(g, current)
            if hit is not None and self._mark(g, hit):
                hits.append((g, hit))
        return self._note(s, hits, None) if hits else None
