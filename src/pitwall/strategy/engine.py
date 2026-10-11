"""The race strategy engine: one per session, pure and deterministic, driven by the game clock.

``feed`` takes the session's items in stream order (``CarFrame``, ``LapCompletion``, ``SessionInfo``, ``GameEvent``,
``RaceTiming``, ``TyreSetsInfo``); ``view`` is the live ``StrategyView`` (``strategy.view``); ``take_calls`` /
``take_records`` / ``take_stops`` hand out what happened since the last call (proactive calls, finished
``StrategyLapRecord``s, changed pit-stop rows). The engine never does I/O and never blocks: the worker owns it.

Mode: ``race`` (F1 race: everything), ``practice`` (tyres, fuel and weather; no gaps, pit window, safety car or
calls) or ``off`` (qualifying, time trial, unknown, other games), with the reason in words.

Player lap ledger: per lap the first and last fuel and wear, compound, tyre age, pit in/out, the worst safety-car
state seen and whether a flashback hit it; the lap time comes from ``LapCompletion``. A lap is *green* when it is
complete, not lap 1, has no pit visit, no safety car / VSC and no flashback. The ledger feeds the analysis
functions in ``analysis.strategy`` in the same shape as stored laps.

Flashbacks (``FLBK``, or the game clock going back more than ``REWIND_S``): ledger laps after the rewind point are
rebuilt, gap samples, pit visits and fuel windows after it are dropped, and records are written again.
"""

from __future__ import annotations

import math
import statistics
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pitwall.analysis.strategy import (
    WEAR_LIMIT_PCT,
    WHEEL_CODES,
    WHEELS,
    BurnModel,
    FuelEstimate,
    LiftCoast,
    TyreEstimate,
    fuel_estimate,
    ideal_stop_lap,
    lift_coast_target,
    pit_window,
    tyre_estimate,
)
from pitwall.model.telemetry import (
    CarFrame,
    CarTiming,
    Game,
    GameEvent,
    LapCompletion,
    RaceTiming,
    SessionInfo,
    SessionType,
    TyreSetsInfo,
)
from pitwall.strategy import cuts
from pitwall.strategy.calls import CallContext, CallPlanner, StrategyCall
from pitwall.strategy.fuel import BurnWindows, fuel_status, lift_corners
from pitwall.strategy.gaps import GapEvent, GapTracker, laps_to_within
from pitwall.strategy.pitloss import PitTracker
from pitwall.strategy.safety_car import SafetyCarState, box_opportunity, entry_ttl_s
from pitwall.strategy.tyres import GameTyres
from pitwall.strategy.view import build_view, call_entry
from pitwall.strategy.weather import WeatherTracker

REWIND_S = 0.5  # the game clock going back more than this is a flashback / restart
LAP_START_M = 50.0  # a lap first seen this close after the line counts as seen from its start
RED_FLAG_TIMEOUT_S = 300.0  # as core.live: a red flag with no "resume" event is assumed over after this
CALLS_SHOWN = 3
RECORD_VERSION = 1
_SEVERITY: dict[str | None, int] = {None: 0, "virtual": 1, "full": 2}

MODE_REASONS = {
    SessionType.TIME_TRIAL: "time trial",
    SessionType.QUALIFYING: "qualifying",
}
REASON_NOT_F1 = "race strategy needs F1 25 timing"
REASON_NO_INFO = "no session information yet"


@dataclass(slots=True)
class LapEntry:
    lap: int
    t_start: float | None = None
    fuel_start: float | None = None
    fuel_end: float | None = None
    wear_start: tuple[float, float, float, float] | None = None
    wear_end: tuple[float, float, float, float] | None = None
    compound: str | None = None
    age: int | None = None
    pit_in: bool = False
    pit_out: bool = False
    on_track_seen: bool = False
    sc: str | None = None
    flashback: bool = False
    lap_time_ms: int | None = None
    complete: bool = False
    position: int | None = None
    stops: int | None = None
    # Seen from the line: the engine watched the line crossing, or its first frame was within LAP_START_M of it. A
    # session that starts mid-lap (a split or resumed session, a late join) sees only part of its first lap: that
    # lap's fuel and wear are partial, so it never counts for fuel use or wear rate ("incomplete").
    from_start: bool = False

    def as_lap(self) -> dict[str, Any]:
        """The ``analysis.strategy`` lap shape (stored laps: ``lap_number``, ``flags``, ``meta``)."""
        flags: list[str] = []
        if self.pit_in:
            flags.append("pit_in")
        if self.pit_out:
            flags.append("pit_out")
        if self.flashback:
            flags.append("flashback")
        if not self.complete or not self.from_start:
            flags.append("incomplete")
        return {
            "lap_number": self.lap,
            "flags": flags,
            "lap_time_ms": self.lap_time_ms,
            "meta": {
                "fuel_start_kg": self.fuel_start,
                "fuel_end_kg": self.fuel_end,
                "tyre_compound": self.compound,
                "tyre_age_laps": self.age,
                "wear_start": self.wear_start,
                "wear_end": self.wear_end,
            },
        }

    @property
    def green(self) -> bool:
        return (
            self.complete
            and self.lap != 1
            and not (self.pit_in or self.pit_out)
            and self.sc is None
            and not self.flashback
        )


@dataclass(slots=True)
class Derived:
    """Everything worked out on one tick, shared by the view, the call planner and the lap records."""

    lap: int | None = None
    laps_remaining: float | None = None
    fuel: FuelEstimate | None = None
    fuel_now: float | None = None
    game_margin: float | None = None
    fuel_status: str = "unknown"
    lift_coast: LiftCoast | None = None
    lift_corners: list[str] = field(default_factory=list)
    # The fuel verdict as judged at the last lap line (the first tick of the lap, again when the lap's time came in):
    # burn within a lap is uneven (flat out, then lifting), so the per-tick margin swings; the view and the calls use
    # this one, the tank (``fuel_now``) stays live.
    fuel_line: FuelEstimate | None = None
    fuel_line_status: str = "unknown"
    lift_line: LiftCoast | None = None
    lift_line_corners: list[str] = field(default_factory=list)
    burn: BurnModel | None = None
    tyres: TyreEstimate | None = None
    game_gain: tuple[str, float, float | None] | None = None
    new_set_life: int | None = None
    game_laps_left: int | None = None
    window: dict[str, Any] | None = None
    stop_needed: bool | None = None
    gain: tuple[float, str] | None = None
    loss_green: dict[str, Any] | None = None
    loss_sc: dict[str, Any] = field(default_factory=dict)
    rejoin: dict[str, Any] | None = None
    undercut: dict[str, Any] | None = None
    threat: dict[str, Any] | None = None
    neighbour: dict[str, Any] | None = None
    sc_box: dict[str, Any] | None = None
    entry_ttl: float | None = None
    lap_time_s: float | None = None


def _wheel_code(name: str | None) -> str | None:
    return None if name is None or name not in WHEELS else WHEEL_CODES[WHEELS.index(name)]


class StrategyEngine:
    def __init__(
        self,
        session_id: str,
        *,
        track_model: Callable[[], Mapping[str, Any] | None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.session_id = session_id
        self.track_model = track_model
        self._clock = clock
        self.info: SessionInfo | None = None
        self.mode = "off"
        self.reason: str | None = REASON_NO_INFO
        self.synthetic = False
        self.packet_format: int | None = None
        self.total_laps: int | None = None
        self.track_length_m: float | None = None
        self.frame: CarFrame | None = None
        self.timing: RaceTiming | None = None
        self.player: CarTiming | None = None
        self.grid_position: int | None = None
        self.ledger: dict[int, LapEntry] = {}
        self.gaps = GapTracker()
        self.pits = PitTracker()
        self.weather = WeatherTracker()
        self.game_tyres = GameTyres()
        self.burn = BurnWindows()
        self.sc = SafetyCarState()
        self.planner = CallPlanner(clock)
        self.drs_enabled: bool | None = None
        self._red_flag_t: float | None = None
        self._t: float | None = None  # latest game clock seen (rewind detection)
        self._lap: int | None = None
        self._calls_lap: int | None = None  # the player's lap at the last call planning (lap-start triggers)
        self.d = Derived()
        self._dirty = True
        self._fuel_key: tuple[int | None, int] | None = None  # (lap, green laps used) of the line-judged fuel
        self.recent_calls: deque[StrategyCall] = deque(maxlen=CALLS_SHOWN)
        self._calls_by_lap: dict[int, list[StrategyCall]] = {}
        self._pending_calls: list[StrategyCall] = []
        self._pending_records: dict[int, dict[str, Any]] = {}
        self._recorded: set[int] = set()
        self._pending_stops: list[dict[str, Any]] = []
        self.ended = False

    # ================================================================== input
    def feed(self, item: object) -> None:
        if isinstance(item, CarFrame):
            self._on_frame(item)
        elif isinstance(item, RaceTiming):
            self._on_timing(item)
        elif isinstance(item, LapCompletion):
            self._on_completion(item)
        elif isinstance(item, SessionInfo):
            self._on_session(item)
        elif isinstance(item, GameEvent):
            self._on_event(item)
        elif isinstance(item, TyreSetsInfo):
            self.game_tyres.on_tyre_sets(item, self._lap)
            self.weather.on_tyre_sets(item)
            self._dirty = True

    def _clock_check(self, t: float | None) -> None:
        if t is None:
            return
        if self._t is not None and t < self._t - REWIND_S:
            self.rewind(t)
        self._t = t if self._t is None or t > self._t else self._t

    # ------------------------------------------------------------------ session
    def _on_session(self, info: SessionInfo) -> None:
        self.info = info
        if info.game is not Game.F1_25:
            self.mode, self.reason = "off", REASON_NOT_F1
        elif info.session_type is SessionType.RACE:
            self.mode, self.reason = "race", None
        elif info.session_type is SessionType.PRACTICE:
            self.mode, self.reason = "practice", None
        else:
            self.mode, self.reason = "off", MODE_REASONS.get(info.session_type, "not a race or practice session")
        self.synthetic = bool(info.extra.get("synthetic"))
        fmt = info.extra.get("packet_format")
        self.packet_format = fmt if isinstance(fmt, int) else None
        self.total_laps = info.total_laps or None
        self.track_length_m = info.track_length_m
        before = self.sc.neutral
        self.sc.on_session(info, self._lap)
        if self.sc.neutral is not None or before != self.sc.neutral:
            self._mark_neutral()
        self.weather.on_session(info)
        self._dirty = True

    def _on_event(self, e: GameEvent) -> None:
        code = e.code
        if code == "FLBK":
            target = e.payload.get("flashbackSessionTime")
            if isinstance(target, int | float):
                self.rewind(float(target))
                self._t = float(target)
        elif code == "SCAR":
            self.sc.on_event(e, self._lap)
            self._mark_neutral()
        elif code == "DRSE":
            self.drs_enabled = True
        elif code == "DRSD":
            self.drs_enabled = False
        elif code == "RDFL":
            self._red_flag_t = e.session_time_s if e.session_time_s is not None else (self._t or 0.0)
        elif code in ("LGOT", "SSTA", "SEND"):
            self._red_flag_t = None
        self._dirty = True

    def _mark_neutral(self) -> None:
        status = self.sc.neutral
        lap = self._lap
        if status is None or lap is None:
            return
        entry = self.ledger.get(lap)
        if entry is not None and _SEVERITY[status] > _SEVERITY[entry.sc]:
            entry.sc = status
        self.gaps.mark_neutral_lap(lap)

    # ------------------------------------------------------------------ player
    def _on_frame(self, f: CarFrame) -> None:
        self._clock_check(f.session_time_s)
        self.frame = f
        lap = f.lap_number
        if lap is None:
            return
        crossed = self._lap is not None and lap == self._lap + 1
        if self._lap is not None and lap > self._lap:
            self.game_tyres.on_line(lap)
        self._lap = lap
        e = self.ledger.get(lap)
        if e is None:
            near_line = f.lap_distance_m is not None and 0.0 <= f.lap_distance_m <= LAP_START_M
            e = self.ledger[lap] = LapEntry(lap=lap, t_start=f.session_time_s, from_start=crossed or near_line)
        if f.fuel_kg is not None:
            if e.fuel_start is None:
                e.fuel_start = f.fuel_kg
            e.fuel_end = f.fuel_kg
        if f.tyre_wear_pct is not None:
            w = f.tyre_wear_pct.as_tuple()
            if e.wear_start is None:
                e.wear_start = w
            e.wear_end = w
        if f.tyre_compound is not None:
            e.compound = f.tyre_compound
        if f.tyre_age_laps is not None:
            e.age = f.tyre_age_laps
        if f.pit_status:
            if e.on_track_seen:
                e.pit_in = True
            else:
                e.pit_out = True
        elif (f.lap_distance_m or 0.0) > 100.0:
            e.on_track_seen = True
        neutral = self.sc.neutral
        if neutral is not None and _SEVERITY[neutral] > _SEVERITY[e.sc]:
            e.sc = neutral
        self.burn.feed(f, neutral is not None)
        self._dirty = True

    def _on_completion(self, c: LapCompletion) -> None:
        self._clock_check(c.session_time_s)
        e = self.ledger.get(c.lap_number)
        if e is None:
            e = self.ledger[c.lap_number] = LapEntry(lap=c.lap_number)
        e.lap_time_ms = c.lap_time_ms
        e.complete = c.lap_time_ms is not None
        self._dirty = True
        if self.mode == "race" and self.total_laps is not None and c.lap_number >= self.total_laps:
            self._derive()
            self._finish_record(c.lap_number)  # the chequered flag: no next lap to take a line gap in

    # ------------------------------------------------------------------ field
    def _on_timing(self, rt: RaceTiming) -> None:
        self._clock_check(rt.session_time_s)
        self.timing = rt
        me = next((c for c in rt.cars if c.is_player), None)
        self.player = me
        events = self.gaps.update(rt)
        self.pits.update(rt, self.sc.neutral)
        if me is not None:
            if self.grid_position is None and me.grid_position is not None:
                self.grid_position = me.grid_position
            if self._lap is None:
                self._lap = me.lap_number
            entry = self.ledger.get(me.lap_number)
            if entry is not None:
                entry.position = me.position
                entry.stops = me.num_pit_stops
        if self.sc.neutral is not None:
            self._mark_neutral()
        for v in self.pits.take_changed():
            self._pending_stops.append(v.row())
        threat_before = self.d.threat  # the assessment before the car behind (maybe) turned into the pit lane
        self._dirty = True
        self._derive()
        if self.mode == "race":
            calls = self.planner.plan(self._context(events, threat_before))
            for call in calls:
                self._pending_calls.append(call)
                self.recent_calls.appendleft(call)
                self._calls_by_lap.setdefault(call.lap or 0, []).append(call)
            for ev in events:
                if ev.kind == "line" and ev.lap is not None:
                    self._finish_record(ev.lap)

    # ------------------------------------------------------------------ rewind
    def rewind(self, t: float) -> None:
        starts = [(e.t_start, e.lap) for e in self.ledger.values() if e.t_start is not None and e.t_start <= t]
        lap_at = max(starts)[1] if starts else None
        if lap_at is not None:
            for n in [n for n in self.ledger if n > lap_at]:
                del self.ledger[n]
            self.ledger[lap_at].flashback = True
            self.ledger[lap_at].complete = False
            self._recorded = {n for n in self._recorded if n < lap_at}
            self.game_tyres.rewind_to_lap(lap_at + 1)
            self._lap = lap_at
        self.gaps.rewind(t)
        self.pits.rewind(t)
        self.burn.rewind(t)
        self._t = t
        self._dirty = True

    # ================================================================== derived state
    def laps_for_analysis(self) -> list[dict[str, Any]]:
        return [self.ledger[n].as_lap() for n in sorted(self.ledger)]

    def excluded_laps(self) -> frozenset[int]:
        return frozenset(n for n, e in self.ledger.items() if n == 1 or e.sc is not None)

    def green_lap_times(self, last: int = 5) -> list[int]:
        return [e.lap_time_ms for n, e in sorted(self.ledger.items()) if e.green and e.lap_time_ms is not None][-last:]

    def laps_remaining(self) -> float | None:
        if self.mode != "race" or self.total_laps is None or self._lap is None:
            return None
        last = self.ledger.get(self.total_laps)
        if (last is not None and last.complete) or (
            self.player is not None and self.player.result_status not in (None, "active")
        ):
            return 0.0  # took the flag (or out of the race): nothing left to run
        f = self.frame
        frac = 0.0
        if f is not None and f.lap_distance_m is not None and self.track_length_m and f.lap_distance_m > 0:
            frac = min(1.0, f.lap_distance_m / self.track_length_m)
        base = self.total_laps - self._lap + 1 - frac
        to_line = 1.0 - frac
        cars = () if self.timing is None else self.timing.cars
        if any(c.result_status == "finished" for c in cars):
            return max(0.0, min(base, to_line))  # the flag is out: the race ends at the next line
        # Lapped: the race ends at the first line crossing after the leader takes the flag (the leader's laps left,
        # in its own laps, at about the player's pace).
        lead = next((c for c in cars if c.position == 1 and c.result_status == "active"), None)
        if lead is not None and not lead.is_player and self.track_length_m:
            lead_frac = min(1.0, max(0.0, lead.lap_distance_m) / self.track_length_m)
            lead_left = self.total_laps - lead.lap_number + 1 - lead_frac
            if lead_left < base:
                base = to_line + max(0, math.ceil(lead_left - to_line - 1e-9))
        return max(0.0, base)

    def _derive(self) -> Derived:
        if not self._dirty:
            return self.d
        self._dirty = False
        d = Derived(lap=self._lap)
        laps = self.laps_for_analysis()
        excl = self.excluded_laps()
        f = self.frame
        d.laps_remaining = self.laps_remaining()
        d.fuel_now = None if f is None else f.fuel_kg
        d.game_margin = None if f is None else f.fuel_remaining_laps_game
        d.fuel = fuel_estimate(laps, d.fuel_now, d.game_margin, d.laps_remaining, exclude_laps=excl)
        d.fuel_status = fuel_status(d.fuel.margin_laps, d.fuel.laps_used) if self.mode == "race" else "unknown"
        d.burn = self.burn.model()
        prev = self.d
        key = (d.lap, d.fuel.laps_used)
        if key == self._fuel_key and prev.fuel_line is not None:
            d.fuel_line, d.fuel_line_status = prev.fuel_line, prev.fuel_line_status
            d.lift_coast, d.lift_corners = d.lift_line, d.lift_line_corners = prev.lift_line, prev.lift_line_corners
        else:
            if self.mode == "race":
                d.lift_coast = lift_coast_target(d.fuel.margin_laps, d.fuel.per_lap_kg, d.laps_remaining, d.burn)
                if d.lift_coast is not None:
                    d.lift_corners = lift_corners(self.track_model() if self.track_model else None)
            self._fuel_key = key
            d.fuel_line, d.fuel_line_status = d.fuel, d.fuel_status
            d.lift_line, d.lift_line_corners = d.lift_coast, d.lift_corners
        d.tyres = tyre_estimate(laps, WEAR_LIMIT_PCT, stint_only=True, exclude_laps=excl)
        times = self.green_lap_times()
        if times:
            d.lap_time_s = statistics.median(times) / 1000
        elif f is not None and f.last_lap_time_ms:
            d.lap_time_s = f.last_lap_time_ms / 1000
        d.game_gain = self.game_tyres.gain(d.laps_remaining)
        d.new_set_life = self.game_tyres.new_set_life()
        d.game_laps_left = self.game_tyres.game_laps_left(self._lap)
        if self.mode != "race":
            self.d = d
            return d
        lap, total = self._lap, self.total_laps
        if lap is not None and total is not None:
            g = d.game_gain
            ideal = ideal_stop_lap(lap, total, g[1], g[2]) if g is not None else None
            d.window = pit_window(
                lap,
                total,
                d.tyres,
                d.fuel,
                new_set_life_laps=d.new_set_life,
                game_laps_left=d.game_laps_left,
                ideal_lap=ideal,
                in_lap_now=True,  # the current lap can still be the in-lap
            )
        d.stop_needed = None if d.window is None else bool(d.window["stop_needed_for_tyres"])
        d.gain = cuts.tyre_gain(d.game_gain, self.pits.measured_gains())
        d.loss_green = self.pits.green_loss()
        d.loss_sc = self.pits.neutral_loss()
        me = self.player
        rt = self.timing
        game_rejoin = None if self.info is None else self.info.extra.get("pit_rejoin_position")
        loss_now = d.loss_green["median_s"] if d.loss_green else None
        neutral = self.sc.neutral
        if neutral is not None:
            loss_now = d.loss_sc.get("full_s" if neutral == "full" else "virtual_s")
        if me is not None and rt is not None:
            d.rejoin = cuts.rejoin(me, rt.cars, loss_now, game_rejoin if isinstance(game_rejoin, int) else None)
            stops = me.num_pit_stops
            traffic = None if d.rejoin is None else d.rejoin.get("traffic")
            a, b = self.gaps.ahead, self.gaps.behind
            d.undercut = cuts.cut_view(
                "undercut",
                a.value_s,
                a.settled,
                d.gain,
                car=a.car,
                player_stops=stops,
                stop_needed=d.stop_needed,
                rejoin_traffic=traffic,
            )
            d.threat = cuts.cut_view(
                "threat", b.value_s, b.settled, d.gain, car=b.car, player_stops=stops, stop_needed=d.stop_needed
            )
            for side in (a, b):
                if side.car is not None and side.car.pit_status:
                    visit = self.pits.in_lane(side.car.car_index)
                    entry_leader = None if visit is None else visit.entry_leader_ms
                    d.neighbour = cuts.neighbour_stop(side.name, side.car, entry_leader, me, rt.cars, loss_now)
                    break
        d.entry_ttl = entry_ttl_s(
            self.pits.pit_entry_m(), None if f is None else f.lap_distance_m, None if f is None else f.speed_kph
        )
        win = d.window
        reaches = d.new_set_life is not None and d.laps_remaining is not None and d.new_set_life >= d.laps_remaining
        d.sc_box = box_opportunity(
            self.sc,
            laps_remaining=d.laps_remaining,
            player_in_pit=bool(f is not None and f.pit_status),
            stop_needed=d.stop_needed,
            window_open_lap=None if not win or not win.get("stop_needed_for_tyres") else win["window_open_lap"],
            lap=lap,
            new_set_reaches_flag=reaches,
            loss=d.loss_sc,
            green_loss_s=None if d.loss_green is None else d.loss_green["median_s"],
            ttl_s=d.entry_ttl,
        )
        self.d = d
        return d

    def blocked(self) -> str | None:
        if self.info is not None and self.info.safety_car_status == "formation_lap":
            return "formation lap"
        if self._red_flag_t is not None:
            if self._t is not None and self._t - self._red_flag_t > RED_FLAG_TIMEOUT_S:
                self._red_flag_t = None
            else:
                return "red flag"
        return None

    def _context(self, events: list[GapEvent], threat_before: dict[str, Any] | None = None) -> CallContext:
        d = self.d
        f = self.frame
        me = self.player
        win = d.window
        window = None
        if win is not None and win.get("stop_needed_for_tyres"):
            window = {
                "open_lap": win["window_open_lap"],
                "close_lap": win["window_close_lap"],
                "ideal_lap": win.get("ideal_lap"),
                "overdue": bool(win.get("overdue")),
                "close_source": win.get("close_source"),
            }
        start = None if d.tyres is None else d.tyres.stint_start_lap
        new_lap = self._lap is not None and self._lap != self._calls_lap
        self._calls_lap = self._lap
        ctx = CallContext(
            t=self._t or 0.0,
            lap=self._lap,
            new_lap=new_lap,
            total_laps=self.total_laps,
            laps_remaining=d.laps_remaining,
            player_in_pit=bool((f is not None and f.pit_status) or (me is not None and me.pit_status)),
            blocked=self.blocked(),
            stops_done=None if me is None else me.num_pit_stops,
            stint_laps=None if start is None or self._lap is None else self._lap - start + 1,
            sc_status=self.sc.neutral,
            sc_period=self.sc.period,
            sc_box=d.sc_box,
            entry_ttl_s=d.entry_ttl,
            fuel_margin_laps=None if d.fuel_line is None else d.fuel_line.margin_laps,
            fuel_status=d.fuel_line_status,
            lift_coast=None
            if d.lift_line is None
            else {"seconds_per_lap": d.lift_line.seconds_per_lap, "corners": d.lift_line_corners},
            window=window,
            undercut_ahead=d.undercut,
            undercut_threat=d.threat,
            gain_s=None if d.gain is None else round(d.gain[0], 2),
            next_weather=self.weather.view(d.lap_time_s)["next_change"],
            weather_now=self.weather.now,
            crossover=None
            if self.weather.crossover is None
            else {"compound": self.weather.crossover.compound, "gain_s": self.weather.crossover.gain_s},
        )
        for ev in events:
            side = self.gaps.ahead if ev.side == "ahead" else self.gaps.behind
            if ev.kind == "pit_entry" and ev.side == "behind" and side.car is not None:
                ctx.behind_pitting = ev.car_index
                ctx.behind_stops = side.car.num_pit_stops
                ctx.undercut_threat = threat_before  # now that it is in the lane, its threat reads "unknown"
            elif ev.kind == "pit_entry" and ev.side == "ahead" and d.neighbour is not None:
                ctx.ahead_pitting = d.neighbour if d.neighbour.get("car") == "ahead" else None
            elif ev.kind == "within" and ev.side == "behind":
                ctx.within_behind = ev.car_index
                ctx.drs_behind = self._drs(self.gaps.behind.within)
            elif ev.kind == "line":
                for s in (self.gaps.ahead, self.gaps.behind):
                    slope, n = self.gaps.trend(s)
                    ctx.trends.append(
                        {
                            "side": s.name,
                            "car_index": s.car_index,
                            "gap_s": s.value_s,
                            "slope": slope,
                            "laps": n,
                            "laps_to_1s": laps_to_within(s.value_s, slope, d.laps_remaining),
                        }
                    )
        return ctx

    def _drs(self, within: bool | None) -> bool | None:
        if self.packet_format != 2025 or self.drs_enabled is None or within is None:
            return None
        return bool(within and self.drs_enabled)

    # ================================================================== records
    def _finish_record(self, lap: int) -> None:
        if self.mode != "race" or lap in self._recorded:
            return
        e = self.ledger.get(lap)
        if e is None or (self.total_laps is not None and lap > self.total_laps):
            return
        rec = self.record(lap)
        self._recorded.add(lap)
        self._pending_records[lap] = rec

    def record(self, lap: int) -> dict[str, Any]:
        """``StrategyLapRecord`` (stored as ``strategy_laps.data``): the lap as the engine saw it at its end."""
        e = self.ledger.get(lap) or LapEntry(lap=lap)
        d = self.d
        ga, gb = self.gaps.line_gap("ahead", lap), self.gaps.line_gap("behind", lap)
        if ga is None and gb is None and lap == self._lap:
            # the last lap (chequered flag, session end): no next lap to take a line gap in, so the last settled gaps
            ga = self.gaps.settled_gap(self.gaps.ahead, lap, self._t or 0.0)
            gb = self.gaps.settled_gap(self.gaps.behind, lap, self._t or 0.0)

        def car_stops(idx: int | None) -> int | None:
            if idx is None or self.timing is None:
                return None
            return next((c.num_pit_stops for c in self.timing.cars if c.car_index == idx), None)

        pit = "in_out" if (e.pit_in and e.pit_out) else "in" if e.pit_in else "out" if e.pit_out else None
        fuel = d.fuel
        win = d.window
        window = None
        if win is not None and win.get("stop_needed_for_tyres"):
            window = {"open": win["window_open_lap"], "close": win["window_close_lap"], "ideal": win.get("ideal_lap")}
        weather = self.weather.view(d.lap_time_s)
        nc = weather["next_change"]
        calls = [call_entry(c) for c in self._calls_by_lap.get(lap, [])]
        return {
            "v": RECORD_VERSION,
            "lap": lap,
            "total_laps": self.total_laps,
            "grid_position": self.grid_position,
            "position": e.position,
            "cars": None if self.timing is None else len(self.timing.cars),
            "lap_time_ms": e.lap_time_ms,
            "gap_ahead_ms": None if ga is None or ga.gap_s is None else round(ga.gap_s * 1000),
            "ahead_car": None if ga is None else ga.car_index,
            "ahead_stops": car_stops(None if ga is None else ga.car_index),
            "gap_behind_ms": None if gb is None or gb.gap_s is None else round(gb.gap_s * 1000),
            "behind_car": None if gb is None else gb.car_index,
            "behind_stops": car_stops(None if gb is None else gb.car_index),
            "gap_leader_ms": None if self.gaps.leader_s is None else round(self.gaps.leader_s * 1000),
            "neutralised_gaps": bool((ga is not None and ga.neutralised) or (gb is not None and gb.neutralised)),
            "pit": pit,
            "stops": e.stops,
            "compound": e.compound,
            "tyre_age_laps": e.age,
            "wear_pct": None if e.wear_end is None else [round(w, 1) for w in e.wear_end],
            "fuel_kg": None if e.fuel_end is None else round(e.fuel_end, 2),
            "fuel_per_lap_kg": None if fuel is None else fuel.per_lap_kg,
            "fuel_margin_laps": None if fuel is None else fuel.margin_laps,
            "game_fuel_margin_laps": None if d.game_margin is None else round(d.game_margin, 2),
            "safety_car": e.sc or "none",
            "weather": weather["now"],
            "rain_pct": weather["rain_pct"],
            "next_weather": None if nc is None else nc.get("weather"),
            "window": window,
            "undercut_ahead": None if d.undercut is None else d.undercut.get("status"),
            "undercut_threat": None if d.threat is None else d.threat.get("status"),
            "tyre_gain_s": None if d.gain is None else round(d.gain[0], 2),
            # additive (not in the first contract draft): the stint projection at the end of the lap
            "laps_to_limit": None
            if d.tyres is None or not d.tyres.enough_laps or d.tyres.laps_to_limit_low is None
            else {"low": d.tyres.laps_to_limit_low, "high": d.tyres.laps_to_limit_high},  # as TyresView.laps_to_limit
            "limiting_wheel": None if d.tyres is None else _wheel_code(d.tyres.limiting_wheel),
            "calls": calls,
        }

    # ================================================================== output
    def take_calls(self) -> list[StrategyCall]:
        out, self._pending_calls = self._pending_calls, []
        return out

    def take_records(self) -> list[tuple[int, dict[str, Any]]]:
        out = sorted(self._pending_records.items())
        self._pending_records = {}
        return out

    def take_stops(self) -> list[dict[str, Any]]:
        out, self._pending_stops = self._pending_stops, []
        return out

    def end(self) -> None:
        """The session ended: finish open line windows and records, write unfinished pit visits as excluded."""
        if self.ended:
            return
        self.ended = True
        self.gaps.flush(self._t or 0.0)
        self.pits.end_session()
        for v in self.pits.take_changed():
            self._pending_stops.append(v.row())
        self._dirty = True
        self._derive()
        for n in sorted(self.ledger):
            if self.ledger[n].complete:
                self._finish_record(n)

    def view(self) -> dict[str, Any]:
        """The live ``StrategyView`` (``strategy.view``)."""
        self._derive()
        return build_view(self)
