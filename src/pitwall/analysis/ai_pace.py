"""Pace vs AI difficulty: the driver's best clean lap against the typical AI car of the same session (pure).

Input: the game's own lap list of every car (F1 Session History, ``CarLapHistory``) collected on the ingest thread by
``core.ai_pace.AiPaceCollector``, plus the session's stored laps of the driver. Output: one ``AiPaceSummary`` per
session (``session_ai_pace`` row, ``snapshot.ai_pace``). Nothing here estimates or fills in a missing value: an AI
level the game did not report, or too few representative AI laps, gives a status with null metrics.

AI laps that count (first failing check names the reason, counted in ``excluded``):

1. ``race_lap_1``           race lap 1 (standing start)
2. ``not_observed``         ``lap_number <= first_seen_lap``: not seen from its start (joined mid-session, a restart,
                            a scenario's pre-filled laps)
3. ``not_ai_driven``        ``lap_number <= ai_from_lap``: the car was seen not AI-controlled and the AI took it over
                            later (a human left a real online lobby): those laps were a human's, at least in part
4. ``results_skip``         ``lap_number >= ended_lap``: the game ended the car's lap away from the line (LapData) and
                            filled its time in (the driver skipped to the results; a retirement)
5. ``invalid``              the game's lap-valid bit is not set
6. ``pit_in_out``           an in- or out-lap (``CarLapHistory.pit_laps``: tyre stints and LapData's pit lane)
7. ``safety_car``           the lap's window [done - lap - ``SC_SLACK_S``, done] overlaps a SC / VSC / formation period
8. ``red_flag``             the window overlaps a red flag (from the red flag event to the next lights out; open
                            until the end when no restart was seen)
9. ``flashback``            the window overlaps a flashback's rewound span
10. ``timing_inconsistent`` the time between this lap's completion and the previous one's differs from the lap time by
                            more than ``TIMING_TOL_S`` (or either completion was not seen): a backstop for filled-in
                            times that ``results_skip`` did not see (real F1 25 fills them in 1.7-16 s early)
11. ``fast_outlier``        faster than ``FAST_OUTLIER`` x the typical AI car's best (a garbage guard; never seen)

Each AI car's best is the fastest of its remaining laps; cars slower than ``SLOW_CAR_CUTOFF`` x the fastest AI best are
dropped (``slow_car``, counted per car). The reference is the median of the remaining bests ("the typical AI car").
Human opponents and cars whose control is unknown are never used; neither is the player's own history (the driver's
laps come from pitwall's own clean-lap rules).
"""

from __future__ import annotations

import math
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pitwall.model.telemetry import CarLapHistory, SessionType

# 2: takeover / results-skip / red-flag / fast-outlier checks, LapData pit laps, in-lap = stint end + 1, 1.3 s timing
AI_PACE_METHOD_VERSION = 2
MIN_AI_CARS = 5  # AI cars with a representative lap needed for a reference
SLOW_CAR_CUTOFF = 1.10  # a car best slower than 110% of the fastest AI best is not representative (garbage guard)
FAST_OUTLIER = 0.90  # a lap faster than 90% of the typical AI car's best is not a lap (garbage guard)
# Completion-time delta vs lap time. Each completion is seen up to one Session History cycle late (20 packets/s cycling
# through the cars: 1.1 s for 22 cars), so driven laps agree within +-1.1 s (real F1 25: 9 races, ~560 laps, max 1.10
# s); laps the game filled in at a results skip were 1.70 s or more early. 24-car fields (format 2026, spec only) get
# 0.1 s of margin.
TIMING_TOL_S = 1.3
SC_SLACK_S = 2.0  # an AI lap window is widened by this before checking for safety car / red flag periods
MIN_DRIVER_LAPS_FOR_MEDIAN = 3  # clean laps needed for the driver's median (race pace)
MIN_DIFFICULTY_READINGS = 10  # Session packets with a known aiDifficulty needed to resolve the session's level
# Share of those readings the level needs. 1.0: a second known value means the level changed during the session (it
# can be changed from the pause menu), and laps at the old and the new level cannot be told apart. Real F1 25 never
# needed a tolerance: once the unfilled tail is ignored every session read one value (16 sessions).
DIFFICULTY_MODE_SHARE = 1.0

STATUS_OK = "ok"
STATUS_NO_DRIVER_LAP = "no_driver_lap"
STATUS_TOO_FEW_AI_CARS = "too_few_ai_cars"
STATUS_UNKNOWN_DIFFICULTY = "unknown_difficulty"
STATUS_DIFFICULTY_CHANGED = "difficulty_changed"
STATUS_TIME_TRIAL = "time_trial"
STATUSES = (
    STATUS_OK,
    STATUS_NO_DRIVER_LAP,
    STATUS_TOO_FEW_AI_CARS,
    STATUS_UNKNOWN_DIFFICULTY,
    STATUS_DIFFICULTY_CHANGED,
    STATUS_TIME_TRIAL,
)
METRIC_STATUSES = (STATUS_OK, STATUS_NO_DRIVER_LAP)  # statuses whose AI metrics are filled

DIFFICULTY_KNOWN = "known"
DIFFICULTY_UNKNOWN = "unknown"
DIFFICULTY_CHANGED = "changed"

EXCLUSIONS = (
    "race_lap_1",
    "not_observed",
    "not_ai_driven",
    "results_skip",
    "invalid",
    "pit_in_out",
    "safety_car",
    "red_flag",
    "flashback",
    "timing_inconsistent",
    "fast_outlier",
    "slow_car",
)
WET_CONDITIONS = frozenset({"light_rain", "heavy_rain", "storm"})


@dataclass(slots=True, frozen=True)
class ScPeriod:
    """A safety car / virtual safety car / formation lap period: game session time (AI laps) and host receive time
    (the driver's stored laps carry ``t_recv_*_ns``). ``end_*`` None = still open (counts as +infinity)."""

    start_s: float | None
    start_ns: int
    end_s: float | None = None
    end_ns: int | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class AiPaceJob:
    """Everything the summary needs, copied off the ingest thread's collector (bounded by the number of cars)."""

    session_id: str
    histories: tuple[CarLapHistory, ...]
    sc_periods: tuple[ScPeriod, ...] = ()
    red_flags: tuple[ScPeriod, ...] = ()  # red flag to the next lights out (open = no restart seen)
    flashbacks: tuple[tuple[float, float], ...] = ()  # (target session time, session time of the rewind)
    ai_difficulty: int | None = None  # the session's resolved level (None unless difficulty_status is "known")
    difficulty_status: str = DIFFICULTY_UNKNOWN  # known | unknown | changed
    session_type: str = SessionType.UNKNOWN.value
    car_class: str | None = None  # SessionInfo.formula ("F1 World", "F2", ...)
    weather_class: str | None = None  # dry | wet | mixed
    network_game: bool | None = None
    run_id: str = ""
    synthetic: bool = False
    final: bool = False


def resolve_difficulty(counts: Mapping[int, int]) -> tuple[int | None, str]:
    """``(level, status)`` from the known aiDifficulty readings of a session: the most common value when there are at
    least ``MIN_DIFFICULTY_READINGS`` and it has at least ``DIFFICULTY_MODE_SHARE`` of them; otherwise unknown (too
    few readings) or changed (no dominant value). Ties go to the lower level (deterministic)."""
    total = sum(counts.values())
    if total < MIN_DIFFICULTY_READINGS:
        return None, DIFFICULTY_UNKNOWN
    mode, k = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if k / total >= DIFFICULTY_MODE_SHARE:
        return mode, DIFFICULTY_KNOWN
    return None, DIFFICULTY_CHANGED


def weather_class(conditions: set[str] | frozenset[str]) -> str | None:
    """dry (no rain seen), wet (only rain seen), mixed, or None when no condition was reported."""
    seen = {c for c in conditions if c}
    if not seen:
        return None
    wet = seen & WET_CONDITIONS
    if not wet:
        return "dry"
    return "wet" if wet == seen else "mixed"


def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _pct(x: float) -> float:
    return round(x, 2)


def _overlaps_open(a0: float, a1: float, b0: float | None, b1: float | None) -> bool:
    """Open-interval overlap; a None start is -inf, a None end +inf."""
    lo = -math.inf if b0 is None else b0
    hi = math.inf if b1 is None else b1
    return a0 < hi and lo < a1


@dataclass(slots=True)
class AiPaceSummary:
    """One session's pace vs the AI (the ``session_ai_pace`` row and ``SessionAiPace`` JSON)."""

    session_id: str
    status: str
    run_id: str
    method_version: int = AI_PACE_METHOD_VERSION
    updated_unix: float = 0.0
    synthetic: bool = False
    final: bool = False
    ai_difficulty: int | None = None
    car_class: str | None = None
    weather_class: str | None = None
    online: bool | None = None
    ai_cars: int = 0
    ai_laps: int = 0
    ai_ref_ms: int | None = None
    ai_best_ms: int | None = None
    ai_p25_ms: int | None = None
    ai_p75_ms: int | None = None
    ai_median_lap_ms: int | None = None
    ai_bests_ms: list[int] = field(default_factory=list)
    driver_best_ms: int | None = None
    driver_best_lap_id: int | None = None
    driver_median_ms: int | None = None
    driver_clean_laps: int = 0
    gap_ms: int | None = None
    gap_pct: float | None = None
    gap_to_best_ai_ms: int | None = None
    race_pace_gap_pct: float | None = None
    field_rank: int | None = None
    field_size: int | None = None
    excluded: dict[str, int] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        """The stored row (``repo.upsert_session_ai_pace``)."""
        return {
            "status": self.status,
            "ai_difficulty": self.ai_difficulty,
            "car_class": self.car_class,
            "weather_class": self.weather_class,
            "online": self.online,
            "ai_cars": self.ai_cars,
            "ai_laps": self.ai_laps,
            "ai_ref_ms": self.ai_ref_ms,
            "ai_best_ms": self.ai_best_ms,
            "ai_p25_ms": self.ai_p25_ms,
            "ai_p75_ms": self.ai_p75_ms,
            "ai_median_lap_ms": self.ai_median_lap_ms,
            "ai_bests_ms": list(self.ai_bests_ms),
            "driver_best_ms": self.driver_best_ms,
            "driver_best_lap_id": self.driver_best_lap_id,
            "driver_median_ms": self.driver_median_ms,
            "driver_clean_laps": self.driver_clean_laps,
            "gap_ms": self.gap_ms,
            "gap_pct": self.gap_pct,
            "gap_to_best_ai_ms": self.gap_to_best_ai_ms,
            "race_pace_gap_pct": self.race_pace_gap_pct,
            "field_rank": self.field_rank,
            "field_size": self.field_size,
            "excluded": dict(self.excluded),
            "run_id": self.run_id,
            "method_version": self.method_version,
            "updated_unix": self.updated_unix,
        }

    def live_payload(self) -> dict[str, Any]:
        """``snapshot.ai_pace`` (``LiveAiPace``): small, sent with every snapshot."""
        return {
            "session_id": self.session_id,
            "status": self.status,
            "synthetic": self.synthetic,
            "ai_difficulty": self.ai_difficulty,
            "ai_cars": self.ai_cars,
            "ai_ref_ms": self.ai_ref_ms,
            "driver_best_ms": self.driver_best_ms,
            "gap_ms": self.gap_ms,
            "gap_pct": self.gap_pct,
            "field_rank": self.field_rank,
            "field_size": self.field_size,
        }


def _ai_laps(job: AiPaceJob, race: bool) -> tuple[dict[int, list[int]], dict[str, int]]:
    """Eligible lap times per AI car index, and the exclusion counts (lap-level reasons)."""
    excluded: dict[str, int] = {}
    per_car: dict[int, list[int]] = {}
    flashbacks = [(min(a, b), max(a, b)) for a, b in job.flashbacks]

    def drop(reason: str) -> None:
        excluded[reason] = excluded.get(reason, 0) + 1

    for h in job.histories:
        if h.ai_controlled is not True or h.is_player:
            continue
        done_at = {lap.lap_number: lap.completed_session_time_s for lap in h.laps}
        eligible: list[int] = []
        for lap in h.laps:
            ms = lap.lap_time_ms
            if ms is None:
                continue
            n = lap.lap_number
            lap_s = ms / 1000.0
            t_done = lap.completed_session_time_s
            if race and n == 1:
                drop("race_lap_1")
                continue
            if n <= h.first_seen_lap:
                drop("not_observed")
                continue
            if n <= h.ai_from_lap:
                drop("not_ai_driven")
                continue
            if h.ended_lap is not None and n >= h.ended_lap:
                drop("results_skip")
                continue
            if lap.valid is not True:
                drop("invalid")
                continue
            if n in h.pit_laps:
                drop("pit_in_out")
                continue
            if t_done is None:  # never seen completing: it cannot be placed in time
                drop("timing_inconsistent")
                continue
            w0, w1 = t_done - lap_s - SC_SLACK_S, t_done
            if any(_overlaps_open(w0, w1, p.start_s, p.end_s) for p in job.sc_periods):
                drop("safety_car")
                continue
            if any(_overlaps_open(w0, w1, p.start_s, p.end_s) for p in job.red_flags):
                drop("red_flag")
                continue
            if any(w0 <= hi and lo <= w1 for lo, hi in flashbacks):
                drop("flashback")
                continue
            t_prev = done_at.get(n - 1)
            if t_prev is None or abs((t_done - t_prev) - lap_s) > TIMING_TOL_S:
                drop("timing_inconsistent")
                continue
            eligible.append(ms)
        if eligible:
            per_car[h.car_index] = eligible
    return per_car, excluded


def _driver_laps(job: AiPaceJob, laps: Sequence[Mapping[str, Any]]) -> list[tuple[int, int, int]]:
    """``(lap_time_ms, lap_number, lap_id)`` of the driver's clean laps that ran under green (pitwall's own clean
    rules: race lap 1, pit, flashback and game-invalid laps are already not clean). A lap without receive times is
    kept: it cannot be placed against a safety car period."""
    out: list[tuple[int, int, int]] = []
    for lap in laps:
        ms = lap.get("lap_time_ms")
        if not lap.get("clean") or not isinstance(ms, int) or ms <= 0:
            continue
        t0, t1 = lap.get("t_recv_start_ns"), lap.get("t_recv_end_ns")
        if isinstance(t0, int) and isinstance(t1, int):
            periods = (*job.sc_periods, *job.red_flags)
            if any(t0 < (math.inf if p.end_ns is None else p.end_ns) and p.start_ns < t1 for p in periods):
                continue
        out.append((ms, int(lap.get("lap_number") or 0), int(lap["id"])))
    return out


def summarise(job: AiPaceJob, laps: Sequence[Mapping[str, Any]], *, now: float | None = None) -> AiPaceSummary:
    """The session's pace vs the AI from ``job`` and the session's stored laps (``repo.session_lap_times``)."""
    category = job.session_type
    race = category == SessionType.RACE.value
    out = AiPaceSummary(
        session_id=job.session_id,
        status=STATUS_OK,
        run_id=job.run_id,
        updated_unix=time.time() if now is None else now,
        synthetic=job.synthetic,
        final=job.final,
        ai_difficulty=job.ai_difficulty if job.difficulty_status == DIFFICULTY_KNOWN else None,
        car_class=job.car_class,
        weather_class=job.weather_class,
        online=job.network_game,
    )
    per_car, excluded = _ai_laps(job, race)
    if per_car:
        floor = FAST_OUTLIER * statistics.median(min(times) for times in per_car.values())
        for car in list(per_car):
            keep = [ms for ms in per_car[car] if ms >= floor]
            if len(keep) < len(per_car[car]):
                excluded["fast_outlier"] = excluded.get("fast_outlier", 0) + len(per_car[car]) - len(keep)
                if keep:
                    per_car[car] = keep
                else:
                    del per_car[car]
    bests = {car: min(times) for car, times in per_car.items()}
    if bests:
        fastest = min(bests.values())
        slow = [car for car, b in bests.items() if b > SLOW_CAR_CUTOFF * fastest]
        for car in slow:
            del bests[car]
            del per_car[car]
        if slow:
            excluded["slow_car"] = len(slow)
    out.excluded = {k: excluded[k] for k in EXCLUSIONS if excluded.get(k)}
    out.ai_cars = len(bests)
    all_laps = [ms for times in per_car.values() for ms in times]
    out.ai_laps = len(all_laps)

    driver = _driver_laps(job, laps)
    out.driver_clean_laps = len(driver)
    if driver:
        best_ms, _, best_id = min(driver, key=lambda x: (x[0], x[1], x[2]))
        out.driver_best_ms, out.driver_best_lap_id = best_ms, best_id
        if len(driver) >= MIN_DRIVER_LAPS_FOR_MEDIAN:
            out.driver_median_ms = round_half_up(statistics.median(ms for ms, _, _ in driver))

    if category == SessionType.TIME_TRIAL.value:
        out.status = STATUS_TIME_TRIAL
    elif job.difficulty_status == DIFFICULTY_CHANGED:
        out.status = STATUS_DIFFICULTY_CHANGED
    elif job.difficulty_status != DIFFICULTY_KNOWN or job.ai_difficulty is None:
        out.status = STATUS_UNKNOWN_DIFFICULTY
    elif out.ai_cars < MIN_AI_CARS:
        out.status = STATUS_TOO_FEW_AI_CARS
    elif out.driver_best_ms is None:
        out.status = STATUS_NO_DRIVER_LAP
    else:
        out.status = STATUS_OK
    if out.status not in METRIC_STATUSES:
        return out

    b = sorted(bests.values())
    q = statistics.quantiles(b, n=4, method="inclusive")
    ref = round_half_up(statistics.median(b))
    out.ai_ref_ms = ref
    out.ai_best_ms = b[0]
    out.ai_p25_ms = round_half_up(q[0])
    out.ai_p75_ms = round_half_up(q[2])
    out.ai_bests_ms = b
    if race:
        out.ai_median_lap_ms = round_half_up(statistics.median(all_laps))
    db = out.driver_best_ms
    if db is None:
        return out
    out.gap_ms = db - ref
    out.gap_pct = _pct(100.0 * (db / ref - 1.0))
    out.gap_to_best_ai_ms = db - b[0]
    out.field_rank = 1 + sum(1 for x in b if x < db)
    out.field_size = out.ai_cars + 1
    if race and out.driver_median_ms is not None and out.ai_median_lap_ms is not None:
        out.race_pace_gap_pct = _pct(100.0 * (out.driver_median_ms / out.ai_median_lap_ms - 1.0))
    return out
