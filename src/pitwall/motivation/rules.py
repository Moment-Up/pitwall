"""Pure motivation rules: lap classes, clean runs, steady-lap windows, scope matching, race outcomes, personal bests,
ideal laps, PB streaks and week arithmetic. No I/O; every number comes from the driver's stored laps.

Thresholds marked [H] are heuristics (documented in docs/features.md).

Lap classes (a run is the longest stretch of clean laps in one session, in lap-number order):

* **breaker** - a mistake or a reset ends a run: ``invalid``, ``flashback`` or ``distance_jump``, or the game said
  the lap was not valid.
* **neutral** - not the driver's lap: skipped, it neither breaks nor counts (``pit_in``, ``pit_out``,
  ``standing_start``, ``incomplete``, or no lap time). Anything else that is not clean is neutral too (defensive).
* **clean** - ``laps.clean``.

A gap in stored lap numbers also ends a run: nobody knows what happened on the missing lap. For the same reason an
``incomplete`` lap (lost packets, a lap cut short) ends a run unless it is the session's first or last stored lap
(joined mid-lap, or the session ended mid-lap) or a pit lap.

Steady-lap windows use stretches of a run (``window_segments``): race lap 1 is left out [H], and a lap behind the
safety car or the virtual safety car ends a stretch [H] (following it makes laps naturally even). F1 says when the
safety car comes out and goes in (``SCAR`` events); ``LapRow.safety_car`` marks the laps that overlap it.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from pitwall.motivation.model import History, LapRow, Scope, SessionRow, local_date, session_car_class

BREAKER_FLAGS = frozenset({"invalid", "flashback", "distance_jump"})
NEUTRAL_FLAGS = frozenset({"pit_in", "pit_out", "standing_start", "incomplete"})
PIT_FLAGS = frozenset({"pit_in", "pit_out"})
CLEAN, BREAKER, NEUTRAL = "clean", "breaker", "neutral"
LAYOUT_TOLERANCE = 0.03  # = repo.BESTS_LENGTH_TOLERANCE: layouts that share a track id differ in length

# F1 PENA penaltyType (docs/research/f1-udp-spec.md section 8.10) that count as a penalty [H]: drive through,
# stop go, grid penalty, time penalty, disqualified, removed from formation lap, black flag timer. A warning (5)
# or a penalty reminder (3) is shown but never counted.
PENALTY_TYPES = frozenset({0, 1, 2, 4, 6, 7, 17})
CHEQUERED_FLAG = "chequered_flag"  # EventKind values (F1 CHQF, SCAR)
SAFETY_CAR = "safety_car"
WARNING_TYPES = frozenset({3, 5})
RECENT_GAIN_DAYS = 60  # [H]
RECENT_GAIN_SESSIONS = 3  # [H]


# ---------------------------------------------------------------------------------------------- laps and runs
def lap_class(lap: LapRow) -> str:
    if lap.flags & BREAKER_FLAGS or lap.valid is False:
        return BREAKER
    if lap.flags & NEUTRAL_FLAGS or lap.lap_time_ms is None:
        return NEUTRAL
    return CLEAN if lap.clean else NEUTRAL


def _breaks_run(lap: LapRow, edges: tuple[int, int]) -> bool:
    """A breaker, or an ``incomplete`` lap in the middle of a session (what happened on it is unknown)."""
    cls = lap_class(lap)
    if cls == BREAKER:
        return True
    return "incomplete" in lap.flags and lap.id not in edges and not lap.flags & PIT_FLAGS


def runs(laps: Sequence[LapRow], after_lap_id: int = 0) -> list[list[LapRow]]:
    """Runs of consecutive clean laps of one session (``laps``: the session's stored laps in lap order). Only laps
    with ``id > after_lap_id`` count; breakers, gaps in lap numbers and mid-session incomplete laps end a run, neutral
    laps are skipped."""
    out: list[list[LapRow]] = []
    cur: list[LapRow] = []
    prev: int | None = None
    edges = (laps[0].id, laps[-1].id) if laps else (0, 0)
    for lap in laps:
        if lap.id <= after_lap_id:
            continue
        if prev is not None and lap.lap_number - prev > 1 and cur:
            out.append(cur)
            cur = []
        prev = lap.lap_number
        cls = lap_class(lap)
        if _breaks_run(lap, edges):
            if cur:
                out.append(cur)
            cur = []
        elif cls == CLEAN:
            cur.append(lap)
    if cur:
        out.append(cur)
    return out


def best_run(laps: Sequence[LapRow], after_lap_id: int = 0) -> list[LapRow]:
    """The longest run (the earliest one on a tie); empty when the session has no clean lap."""
    best: list[LapRow] = []
    for r in runs(laps, after_lap_id):
        if len(r) > len(best):
            best = r
    return best


def run_ending_at(laps: Sequence[LapRow], lap_id: int, after_lap_id: int = 0) -> list[LapRow]:
    """The run that ends with lap ``lap_id`` (empty when that lap is not clean or not counted)."""
    for r in runs(laps, after_lap_id):
        if r and r[-1].id == lap_id:
            return r
        if any(lap.id == lap_id for lap in r):
            return r[: [lap.id for lap in r].index(lap_id) + 1]
    return []


def standing_start(lap: LapRow, session_type: str | None) -> bool:
    """Race lap 1 [H]: from the grid, not comparable with flying laps (a standing start is not always flagged in
    real F1 25 data)."""
    return session_type == "race" and lap.lap_number == 1


def window_segments(run: Sequence[LapRow], session_type: str | None) -> list[list[LapRow]]:
    """The stretches of a run that steady-lap windows may use: race lap 1 is skipped, a safety-car lap ends a
    stretch (both [H])."""
    out: list[list[LapRow]] = []
    cur: list[LapRow] = []
    for lap in run:
        if standing_start(lap, session_type):
            continue
        if lap.safety_car:
            if cur:
                out.append(cur)
            cur = []
            continue
        cur.append(lap)
    if cur:
        out.append(cur)
    return out


@dataclass(slots=True, frozen=True)
class Window:
    spread_ms: int
    laps: tuple[LapRow, ...]

    @property
    def last(self) -> LapRow:
        return self.laps[-1]


def windows(laps: Sequence[LapRow], k: int, session_type: str | None, after_lap_id: int = 0) -> list[Window]:
    """Every window of ``k`` consecutive clean laps of one run (in lap order), with its spread (max - min)."""
    out: list[Window] = []
    if k < 2:
        return out
    for r in runs(laps, after_lap_id):
        for usable in window_segments(r, session_type):
            for i in range(len(usable) - k + 1):
                w = usable[i : i + k]
                times = [lap.lap_time_ms for lap in w if lap.lap_time_ms is not None]
                if len(times) == k:
                    out.append(Window(max(times) - min(times), tuple(w)))
    return out


def best_window(laps: Sequence[LapRow], k: int, session_type: str | None, after_lap_id: int = 0) -> Window | None:
    """The steadiest window (smallest spread; the earliest on a tie)."""
    best: Window | None = None
    for w in windows(laps, k, session_type, after_lap_id):
        if best is None or w.spread_ms < best.spread_ms:
            best = w
    return best


def fastest_clean(laps: Iterable[LapRow], after_lap_id: int = 0) -> LapRow | None:
    """The fastest clean lap (the earliest on a tie)."""
    best: LapRow | None = None
    for lap in laps:
        if lap.id <= after_lap_id or not lap.clean or lap.lap_time_ms is None:
            continue
        if best is None or lap.lap_time_ms < best.lap_time_ms:  # type: ignore[operator]
            best = lap
    return best


# ---------------------------------------------------------------------------------------------- scopes
def lengths_match(a: float | None, b: float | None, tolerance: float = LAYOUT_TOLERANCE) -> bool:
    if a is None or b is None or a <= 0 or b <= 0:
        return True
    return abs(a - b) <= tolerance * max(a, b)


def scope_matches(scope: Scope, s: SessionRow) -> bool:
    """Each field the scope sets must match the session; known layout lengths must agree within 3 %."""
    if scope.game is not None and scope.game != s.game:
        return False
    if scope.track_id is not None and scope.track_id != s.track_id:
        return False
    if scope.car_id is not None and scope.car_id != s.car_id:
        return False
    if scope.car_class is not None and scope.car_class != session_car_class(s):
        return False
    return scope.track_id is None or lengths_match(scope.track_length_m, s.track_length_m)


def scope_laps(history: History, scope: Scope, after_lap_id: int = 0) -> list[tuple[SessionRow, LapRow]]:
    return [(s, lap) for s, lap in history.all_laps() if lap.id > after_lap_id and scope_matches(scope, s)]


def ideal_lap(laps: Iterable[LapRow]) -> int | None:
    """Best sectors combined over clean laps: ``min(s1) + min(s2) + min(s3)``; None if a sector is unknown."""
    best: list[int | None] = [None, None, None]
    for lap in laps:
        if not lap.clean:
            continue
        for i, v in enumerate((lap.s1_ms, lap.s2_ms, lap.s3_ms)):
            if v is not None and (best[i] is None or v < best[i]):  # type: ignore[operator]
                best[i] = v
    if any(v is None for v in best):
        return None
    return sum(v for v in best if v is not None)


@dataclass(slots=True, frozen=True)
class SessionBest:
    """One session's best clean lap against the best from earlier sessions in the same scope."""

    session: SessionRow
    lap: LapRow
    previous_ms: int | None  # best before this session; None = first session with a clean lap here

    @property
    def best_ms(self) -> int:
        assert self.lap.lap_time_ms is not None
        return self.lap.lap_time_ms

    @property
    def is_pb(self) -> bool:
        """Beat an earlier session's best (the first session in a scope is never a gain)."""
        return self.previous_ms is not None and self.best_ms < self.previous_ms

    @property
    def gain_ms(self) -> int | None:
        return self.previous_ms - self.best_ms if self.is_pb and self.previous_ms is not None else None


def session_bests(
    sessions: Iterable[SessionRow], laps: Mapping[str, Sequence[LapRow]], after_lap_id: int = 0
) -> list[SessionBest]:
    """Per session with a clean lap (in the given order, one scope): its best and the best before it."""
    out: list[SessionBest] = []
    pb: int | None = None
    for s in sessions:
        best = fastest_clean(laps.get(s.id, ()), after_lap_id)
        if best is None or best.lap_time_ms is None:
            continue
        out.append(SessionBest(s, best, pb))
        pb = best.lap_time_ms if pb is None else min(pb, best.lap_time_ms)
    return out


def recent_gain_ms(bests: Sequence[SessionBest], now_unix: float) -> int | None:
    """Median gain of the last ``RECENT_GAIN_SESSIONS`` sessions (within ``RECENT_GAIN_DAYS``) that set a new
    best against an earlier session [H]. None when there is none."""
    horizon = now_unix - RECENT_GAIN_DAYS * 86_400
    gains = [b.gain_ms for b in bests if b.gain_ms is not None and b.session.started_unix >= horizon]
    recent = [g for g in gains if g is not None][-RECENT_GAIN_SESSIONS:]
    return round(statistics.median(recent)) if recent else None


@dataclass(slots=True, frozen=True)
class PbStreak:
    current: int  # sessions in a row (ending with the latest) that beat the best before them
    best: int
    per_session: tuple[int, ...]  # the streak value at each session of ``bests``


def pb_streak(bests: Sequence[SessionBest]) -> PbStreak:
    streak = 0
    best = 0
    values: list[int] = []
    for b in bests:
        streak = streak + 1 if b.is_pb else 0
        best = max(best, streak)
        values.append(streak)
    return PbStreak(streak, best, tuple(values))


def pb_scopes(history: History) -> dict[tuple[str, str, str | None], list[SessionRow]]:
    """Sessions grouped by ``SessionRow.pb_key`` (game, track, car), each in time order."""
    out: dict[tuple[str, str, str | None], list[SessionRow]] = {}
    for s in history.sessions:
        key = s.pb_key
        if key is not None:
            out.setdefault(key, []).append(s)
    return out


# ---------------------------------------------------------------------------------------------- races (F1)
@dataclass(slots=True, frozen=True)
class RaceOutcome:
    session_id: str
    race: bool
    # Taken the flag: the race's last lap (``total_laps``) is stored with a time and is not incomplete, or - a lapped
    # car, a race shortened by a red flag - F1's chequered flag was shown and the player's last stored lap is complete
    # and ended after it.
    finished: bool
    from_start: bool  # lap 1 is stored (the session was recorded from the start)
    incidents_known: bool  # every incident event names the player's car (``player_idx``)
    contacts: int
    penalties: int
    warnings: int
    flashbacks: int
    resets: int
    total_laps: int | None
    final_lap_id: int | None = None  # the lap the player took the flag on (when finished)
    final_lap_number: int | None = None

    @property
    def evaluable(self) -> bool:
        return self.race and self.finished and self.from_start and self.incidents_known

    @property
    def no_penalties(self) -> bool:
        return self.evaluable and self.penalties == 0 and self.flashbacks == 0 and self.resets == 0

    @property
    def no_contact(self) -> bool:
        return self.no_penalties and self.contacts == 0

    def meets(self, rule: str) -> bool:
        return self.no_contact if rule == "no_contact" else self.no_penalties


def _idx(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def race_outcome(s: SessionRow, laps: Sequence[LapRow], events: Sequence[Mapping[str, Any]]) -> RaceOutcome:
    """F1 races only: was the race recorded from lap 1 and driven to the flag, and what incidents did the player
    have? A race that is not ``evaluable`` counts neither way (unknown stays unknown)."""
    race = s.is_race and s.is_f1
    total = s.total_laps if s.total_laps is not None and s.total_laps > 0 else None
    final = _flag_lap(laps, events, total) if race else None
    finished = final is not None
    from_start = any(lap.lap_number == 1 for lap in laps)
    known = True
    contacts = penalties = warnings = event_flashbacks = 0
    for e in events:
        kind = e.get("kind")
        payload = e.get("payload") or {}
        if not isinstance(payload, Mapping):
            payload = {}
        if kind == "flashback":
            event_flashbacks += 1
            continue
        player = _idx(payload.get("player_idx"))
        if kind in ("collision", "penalty") and player is None:
            known = False
            continue
        if kind == "collision" and player in (_idx(payload.get("vehicle1Idx")), _idx(payload.get("vehicle2Idx"))):
            contacts += 1
        elif kind == "penalty" and _idx(payload.get("vehicleIdx")) == player:
            ptype = _idx(payload.get("penaltyType"))
            if ptype in PENALTY_TYPES:
                penalties += 1
            elif ptype in WARNING_TYPES:
                warnings += 1
    lap_flashbacks = sum(1 for lap in laps if "flashback" in lap.flags)
    resets = sum(1 for lap in laps if "distance_jump" in lap.flags)
    return RaceOutcome(
        session_id=s.id,
        race=race,
        finished=finished,
        from_start=from_start,
        incidents_known=known,
        contacts=contacts,
        penalties=penalties,
        warnings=warnings,
        flashbacks=max(event_flashbacks, lap_flashbacks),  # one flashback is both an event and a flagged lap
        resets=resets,
        total_laps=total,
        final_lap_id=None if final is None else final.id,
        final_lap_number=None if final is None else final.lap_number,
    )


def _complete(lap: LapRow) -> bool:
    return lap.lap_time_ms is not None and "incomplete" not in lap.flags


def _flag_lap(laps: Sequence[LapRow], events: Sequence[Mapping[str, Any]], total: int | None) -> LapRow | None:
    """The lap the player took the chequered flag on, or None (not finished, or unknown)."""
    if total is not None:
        last = next((lap for lap in laps if lap.lap_number == total and _complete(lap)), None)
        if last is not None:
            return last
    flag = next((t for e in events if e.get("kind") == CHEQUERED_FLAG and (t := _idx(e.get("t_recv_ns")))), None)
    if flag is None or not laps:
        return None
    last = max(laps, key=lambda lap: lap.lap_number)
    if _complete(last) and last.t_end_ns is not None and last.t_end_ns >= flag:
        return last
    return None


def safety_car_spans(events: Sequence[Mapping[str, Any]]) -> list[tuple[int, int | None]]:
    """When the safety car or the VSC was out (receive clock, ns): from "deployed" to "returned" or "resume race"
    (F1 ``SCAR`` eventType 0 / 2 / 3; the formation-lap safety car, safetyCarType 3, is before lap 1 and ignored).
    Still out at the end = open-ended (unknown stays unknown: it counts as out)."""
    spans: list[tuple[int, int | None]] = []
    start: int | None = None
    for e in events:
        if e.get("kind") != SAFETY_CAR:
            continue
        payload = e.get("payload") or {}
        t = _idx(e.get("t_recv_ns"))
        what = _idx(payload.get("eventType")) if isinstance(payload, Mapping) else None
        if t is None or what is None or (isinstance(payload, Mapping) and payload.get("safetyCarType") == 3):
            continue
        if what == 0 and start is None:
            start = t
        elif what in (2, 3) and start is not None:
            spans.append((start, t))
            start = None
    if start is not None:
        spans.append((start, None))
    return spans


def behind_safety_car(lap: LapRow, spans: Sequence[tuple[int, int | None]]) -> bool:
    """The lap overlaps a safety-car span (a lap without its receive times overlaps none: not guessed)."""
    if lap.t_start_ns is None or lap.t_end_ns is None:
        return False
    return any(lap.t_end_ns >= a and (b is None or lap.t_start_ns <= b) for a, b in spans)


# ---------------------------------------------------------------------------------------------- weeks
def week_start(d: date) -> date:
    """Monday of the week containing ``d`` (local calendar arithmetic: a clock change never shifts a week)."""
    return d - timedelta(days=d.weekday())


def week_of(unix: float) -> date:
    return week_start(local_date(unix))


def timed(laps: Iterable[LapRow]) -> list[LapRow]:
    return [lap for lap in laps if lap.lap_time_ms is not None]


def is_timed_session(laps: Sequence[LapRow]) -> bool:
    return any(lap.lap_time_ms is not None for lap in laps)
