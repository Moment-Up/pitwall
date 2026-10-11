"""Live state shared between the ingest thread (single writer) and the web layer (readers).

The dashboard pulls ``snapshot()`` at a fixed rate instead of being pushed every frame, so slow clients can
never apply backpressure to telemetry ingest. Discrete notifications (lap completed, new observations) are
delivered to subscribers through bounded per-client queues by the web layer.

``cues`` is the live braking-cue engine (``coach.cues``). LiveState feeds it everything it needs, so no other
module has to know about it: every frame (O(1) hook on the ingest thread), the reference lap and each lap's
comparison/observations (analysis thread), session conditions (safety car, race length), session resets and
the seated driver (``on_driver``). The radio hub attaches the sink that actually speaks cues; without one the
engine plans but never fires.

Snapshot additions for the dashboard (docs/ui/design-spec.md section 13, all additive, ``None`` when unknown):

* ``session_state`` (D4): ``running`` / ``ended`` / ``red_flag``, kept here from game events, so it survives the
  10-event window of ``events``. ``ended`` comes from ``session_ended`` only: F1 sends ``chequered_flag`` when the
  *leader* takes the flag (in a real F1 25 capture 3.5 s before the player crossed the line), so it is reported
  as ``session_state_info.chequered_flag`` and never ends the session on its own. A red flag clears on
  ``lights_out``, ``session_started`` or ``session_ended``; no "red flag cleared" event is decoded and F1 practice
  and qualifying resume without a lights-out, so it also clears (``red_flag_resume``) when the player's car, seen
  in the pits since the flag, is back on track with no safety car (cause ``red_flag_pit_exit``), or, as a
  backstop, ``RED_FLAG_TIMEOUT_S`` after the flag while the car is not in the pits (cause ``red_flag_timeout``).
  No real red-flag capture exists yet (spec section 16, question 6), so these two rules are unconfirmed.
  After ``session_ended`` F1 stops sending at once, so ``connection`` turns ``stale`` two seconds later while
  ``session_state`` stays ``ended`` until the next session starts.
* ``coach`` (D6): the coaching points the radio picks for a lap under the seated driver's limits
  (``coach.selection``), and per corner the point the coach card shows. The same selection travels with the
  ``lap`` notification (``coach``) so the radio speaks exactly what the screen shows.
* ``bests`` (D2, every snapshot): session / driver / household bests for this game + track + car, published by
  the lap processor after each lap and when the session's context changes (``set_bests_requester``). A few hundred
  bytes, so it rides every snapshot: a lap that sets a record is coloured as set on the next frame, not up to
  5 s later with the static payload.
* ``strategy`` (every snapshot): the race strategy engineer's ``StrategyView`` (``pitwall.strategy.view``),
  published by the strategy worker at most twice a second; ``None`` until it has one for the live session.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from pitwall.analysis.distance import DistanceTrace
from pitwall.analysis.track_skeleton import build_track_skeleton
from pitwall.coach.cues import CoachingProfile, CueEngine, CuePlan, cue_labels
from pitwall.coach.selection import CoachSelection
from pitwall.core.track_knowledge import TrackKnowledge, TrackKnowledgeResolver, heads_up_cue_plan
from pitwall.drivers import CoachingLimits
from pitwall.model.telemetry import CarFrame, GameEvent, SessionInfo, Wheels

SESSION_RUNNING = "running"
SESSION_ENDED = "ended"
SESSION_RED_FLAG = "red_flag"
# game event kind -> the session state it starts (D4). Anything else leaves the state alone.
SESSION_STATE_EVENTS: dict[str, str] = {
    "session_started": SESSION_RUNNING,
    "lights_out": SESSION_RUNNING,  # a (re)start: also clears a red flag
    "red_flag": SESSION_RED_FLAG,
    "session_ended": SESSION_ENDED,
}
CHEQUERED_FLAG_EVENT = "chequered_flag"
# D4 red flag ends with no event (red_flag_resume): the causes, and the backstop's age
RED_FLAG_PIT_EXIT = "red_flag_pit_exit"
RED_FLAG_TIMEOUT = "red_flag_timeout"
RED_FLAG_TIMEOUT_S = 300.0  # longer than a slow lap back to the pits on any F1 circuit (Spa at 90 km/h: 280 s)
_IN_PITS = (1, 2)  # CarFrame.pit_status: 1 pitting / in the pit lane, 2 in the pit area
_NO_SAFETY_CAR = (None, "none")  # unknown counts as none, like the cue engine (coach.cues)


@dataclass(frozen=True, slots=True)
class SessionState:
    """D4: ``state`` and what set it (``cause`` = event kind, ``RED_FLAG_PIT_EXIT`` / ``RED_FLAG_TIMEOUT`` for a red
    flag that ended without an event, ``None`` = the session's start), when (unix s), and whether the chequered flag
    has been shown since the last (re)start. Immutable: replaced, never mutated, so a reader on another thread
    always sees one consistent value."""

    state: str
    cause: str | None
    since_unix: float
    chequered_flag: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "cause": self.cause,
            "since_unix": round(self.since_unix, 3),
            "chequered_flag": self.chequered_flag,
        }


def next_session_state(current: SessionState | None, event_kind: str, t_unix: float) -> SessionState | None:
    """Pure D4 transition for one game event (``GameEvent.kind.value``)."""
    if event_kind == CHEQUERED_FLAG_EVENT:
        base = current or SessionState(SESSION_RUNNING, None, t_unix)
        return SessionState(base.state, base.cause, base.since_unix, chequered_flag=True)
    state = SESSION_STATE_EVENTS.get(event_kind)
    if state is None:
        return current
    chequered = current.chequered_flag if current is not None and state != SESSION_RUNNING else False
    return SessionState(state, event_kind, t_unix, chequered_flag=chequered)


def red_flag_resume(
    pitted: bool, pit_status: int | None, safety_car_status: str | None, age_s: float
) -> tuple[bool, str | None]:
    """Pure D4 rule, per player frame while the session is red-flagged: has the session resumed without an event?

    ``pitted``: the player's car has been in the pits since the flag. Returns ``(pitted, cause)``; ``cause`` is
    ``RED_FLAG_PIT_EXIT`` when the car, after being in the pits, is back on track with no safety car (a practice
    or qualifying session resumed; a race restart behind the safety car waits for it to come in, or for the
    lights-out), ``RED_FLAG_TIMEOUT`` when the flag is ``RED_FLAG_TIMEOUT_S`` old and the car has not been in the
    pits since (the backstop, also for games that do not report pit status), else ``None`` (still red)."""
    if pit_status in _IN_PITS:
        return True, None
    if pitted:
        resumed = pit_status == 0 and safety_car_status in _NO_SAFETY_CAR
        return True, RED_FLAG_PIT_EXIT if resumed else None
    return False, RED_FLAG_TIMEOUT if age_s >= RED_FLAG_TIMEOUT_S else None


@dataclass(frozen=True, slots=True)
class BestsRequest:
    """The live session's context changed (new session, track, car, layout or seated driver): its D2 bests must
    be (re)computed off the ingest thread (``core.lap_processor.AnalysisWorker`` registers the requester)."""

    session_id: str
    game: str
    track_id: str
    car_id: str | None
    track_length_m: float | None
    driver_id: int | None


def _wheels(w: Wheels[float] | None, nd: int = 1) -> list[float] | None:
    return None if w is None else [round(v, nd) for v in w.as_tuple()]


def frame_to_dict(f: CarFrame) -> dict[str, Any]:
    def r(v: float | None, nd: int = 3) -> float | None:
        return None if v is None else round(v, nd)

    return {
        "t_recv_ns": f.t_recv_ns,
        "session_time_s": r(f.session_time_s),
        "speed_kph": r(f.speed_kph, 1),
        "throttle": r(f.throttle),
        "brake": r(f.brake),
        "steering": r(f.steering),
        "clutch": r(f.clutch),
        "gear": f.gear,
        "rpm": r(f.rpm, 0),
        "max_rpm": r(f.max_rpm, 0),
        "drs_open": f.drs_open,
        "pos": [r(f.pos_x_m, 2), r(f.pos_y_m, 2), r(f.pos_z_m, 2)],
        "g_lat": r(f.g_lat, 2),
        "g_lon": r(f.g_lon, 2),
        "lap_number": f.lap_number,
        "lap_distance_m": r(f.lap_distance_m, 1),
        "current_lap_time_ms": f.current_lap_time_ms,
        "last_lap_time_ms": f.last_lap_time_ms,
        "sector": f.sector,
        "lap_invalid": f.lap_invalid,
        "pit_status": f.pit_status,
        "race_position": f.race_position,
        "tyre_surface_temp_c": _wheels(f.tyre_surface_temp_c, 0),
        "tyre_inner_temp_c": _wheels(f.tyre_inner_temp_c, 0),
        "tyre_pressure_psi": _wheels(f.tyre_pressure_psi, 1),
        "brake_temp_c": _wheels(f.brake_temp_c, 0),
        "tyre_wear_pct": _wheels(f.tyre_wear_pct, 1),
        "tyre_compound": f.tyre_compound,
        "tyre_age_laps": f.tyre_age_laps,
        "fuel_kg": r(f.fuel_kg, 2),
        "fuel_remaining_laps_game": r(f.fuel_remaining_laps_game, 2),
        "ers_store_j": r(f.ers_store_j, 0),
        "brake_bias_front_pct": f.brake_bias_front_pct,
        "quality": int(f.quality),
    }


class LiveState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.frame: CarFrame | None = None
        self.session: SessionInfo | None = None
        self.session_id: str | None = None
        self.source: str | None = None
        self.synthetic = False
        self.packets = 0
        self.rejected = 0
        self.unrecognised = 0
        self._pps = 0.0
        self._pps_window_start = time.monotonic()
        self._pps_count = 0
        self.last_packet_mono = 0.0
        self.decode_stats: dict[str, Any] = {}
        self.laps: deque[dict[str, Any]] = deque(maxlen=60)
        self.observations: list[dict[str, Any]] = []
        self.last_comparison: dict[str, Any] | None = None
        self.events: deque[dict[str, Any]] = deque(maxlen=30)
        self.reference: dict[str, Any] | None = None
        self._ref_trace: DistanceTrace | None = None
        self.delta_s: float | None = None
        self.track_model: dict[str, Any] | None = None
        self.skeleton: dict[str, Any] | None = None  # game-native sectors / zones (analysis/track_skeleton.py)
        self._skeleton_key: tuple[Any, ...] | None = None
        self.marshal_flags: list[dict[str, Any]] = []
        self.session_state: SessionState | None = None  # D4; None = no session yet
        self._red_flag_pitted = False  # D4: the player's car has been in the pits since the red flag
        self.coach = CoachSelection()  # D6: one coaching selection for the screen and the radio
        self.bests: dict[str, Any] | None = None  # D2 (repo.lap_bests), static payload
        self._bests_requester: Callable[[BestsRequest], None] | None = None
        self._bests_requested: tuple[Any, ...] | None = None
        self._driver_id: int | None = None  # seated driver (on_driver)
        # Track knowledge (core/track_knowledge.py): layers L3 > L0b > L1c resolved into one JSON view. The runtime
        # attaches the resolver; set_track_model feeds it layer L3, the field worker layer L0b.
        self.knowledge: TrackKnowledgeResolver | None = None
        self.track_knowledge: dict[str, Any] | None = None
        self._heads_up_key: tuple[tuple[str, int], ...] | None = None
        self.cues = CueEngine()
        self.strategy: dict[str, Any] | None = None  # race strategy (pitwall.strategy): StrategyView of this session
        self.version = 0
        self._listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._button_listeners: list[Callable[[int], None]] = []

    # ------------------------------------------------------------- notifications
    def subscribe(self, fn: Callable[[str, dict[str, Any]], None]) -> None:
        self._listeners.append(fn)

    def unsubscribe(self, fn: Callable[[str, dict[str, Any]], None]) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def subscribe_buttons(self, fn: Callable[[int], None]) -> None:
        """Raw game button bit-flags (F1 BUTN events), e.g. for wheel push-to-talk."""
        self._button_listeners.append(fn)

    def unsubscribe_buttons(self, fn: Callable[[int], None]) -> None:
        if fn in self._button_listeners:
            self._button_listeners.remove(fn)

    def on_button(self, status: int) -> None:
        for fn in list(self._button_listeners):
            with contextlib.suppress(Exception):
                fn(status)

    def notify(self, kind: str, payload: dict[str, Any]) -> None:
        for fn in list(self._listeners):
            with contextlib.suppress(Exception):  # a broken listener must never affect ingest
                fn(kind, payload)

    # ------------------------------------------------------------- writers (ingest thread)
    def on_packet(self, accepted: bool) -> None:
        now = time.monotonic()
        self.packets += 1
        if not accepted:
            self.rejected += 1
        self.last_packet_mono = now
        self._pps_count += 1
        span = now - self._pps_window_start
        if span >= 1.0:
            self._pps = self._pps_count / span
            self._pps_count = 0
            self._pps_window_start = now

    def on_frame(self, f: CarFrame) -> None:
        self.frame = f
        ref = self._ref_trace
        if ref is not None and f.lap_distance_m is not None and f.current_lap_time_ms is not None:
            d = f.lap_distance_m
            if 0 <= d < ref.d[-1]:
                t_ref = float(np.interp(d, ref.d, ref.t_s))
                self.delta_s = f.current_lap_time_ms / 1000.0 - t_ref if np.isfinite(t_ref) else None
            else:
                self.delta_s = None
        self.cues.on_frame(f)  # O(1); catches its own errors so a cue bug can never stop ingest
        st = self.session_state
        if st is not None and st.state == SESSION_RED_FLAG:  # O(1), only while red-flagged
            self._red_flag_tick(f, st)
        self.version += 1

    def _red_flag_tick(self, f: CarFrame, st: SessionState) -> None:
        """D4: end a red flag that the game ends without an event (``red_flag_resume``). Ingest thread."""
        now = time.time()
        s = self.session
        sc = None if s is None else s.safety_car_status
        self._red_flag_pitted, cause = red_flag_resume(self._red_flag_pitted, f.pit_status, sc, now - st.since_unix)
        if cause is not None:
            self.session_state = SessionState(SESSION_RUNNING, cause, now)

    def on_session(self, info: SessionInfo) -> None:
        self.session = info
        self.cues.on_session_info(info.safety_car_status, info.total_laps, info.session_type.value)
        z = info.track_zones
        key = (
            info.track_id,
            info.track_length_m,
            info.pit_speed_limit_kph,
            None if z is None else z.geometry_key(),
            bool(info.extra.get("synthetic")),
        )
        if key != self._skeleton_key:  # geometry is static: rebuild at most when it changes (2 Hz packets)
            self._skeleton_key = key
            sk = build_track_skeleton(info)
            self.skeleton = sk.to_dict() if sk is not None else None
        # Marshal flags are live state: a tiny list sent with every snapshot (the skeleton itself only every 5 s).
        self.marshal_flags = (
            [
                {"game_number": i + 1, "flag": m.flag}
                for i, m in enumerate(z.marshal_zones)
                if m.flag not in (None, "none", "green")
            ]
            if z is not None and z.marshal_zones
            else []
        )
        self._request_bests()  # O(1) unless the session's context changed

    def on_event(self, e: GameEvent) -> None:
        if e.kind.value == "button":
            return
        now = time.time()
        item = {"kind": e.kind.value, "code": e.code, "session_time_s": e.session_time_s, "t": now}
        self.events.appendleft(item)
        self.session_state = next_session_state(self.session_state, e.kind.value, now)  # O(1), D4
        if e.kind.value == "red_flag":
            self._red_flag_pitted = False  # a (new) flag: the car must be seen in the pits after it
        self.notify("event", item)

    # ------------------------------------------------------------- writers (analysis thread)
    def on_lap_result(
        self,
        lap: dict[str, Any],
        observations: list[dict[str, Any]],
        comparison: dict[str, Any] | None,
    ) -> None:
        compat = (comparison or {}).get("compatibility")
        compared = isinstance(compat, dict) and bool(compat.get("ok"))
        coach = self.coach.select(lap, observations, compared)  # once per lap: the radio speaks this pick
        with self._lock:
            self.laps.appendleft(lap)
            self.observations = observations
            self.last_comparison = comparison
        # replan before notifying, so the radio's speak window already knows the next lap's cues
        self.cues.on_lap_result(observations, comparison, self._track_length_m())
        self.notify("lap", {"lap": lap, "observations": observations[:5], "coach": coach})

    def set_reference(self, summary: dict[str, Any] | None, trace: DistanceTrace | None) -> None:
        with self._lock:
            self.reference = summary
            self._ref_trace = trace
        self.cues.on_reference(summary, trace)

    def set_track_model(self, model: dict[str, Any] | None) -> None:
        with self._lock:
            self.track_model = model
        self.cues.set_track_length(self._track_length_m())
        self.cues.set_corner_labels(cue_labels(model))  # cues name corners as the track view does
        knowledge = self.knowledge
        if knowledge is not None:
            # layer L3 (a model of another track is ignored). O(1) when the resolver already holds this object,
            # which is what the session manager re-installs on the INGEST thread after a driver change.
            knowledge.set_learned(model)

    def set_track_knowledge(self, k: TrackKnowledge | None) -> None:
        """``TrackKnowledgeResolver`` callback (field worker or analysis thread, never ingest): the dashboard's view,
        and the AI field's heads-ups for the cue engine (used only while the driver has no reference plan). The cue
        plan is replaced only when its calls actually moved (snapshots arrive every 5 s)."""
        d = None if k is None else k.to_dict()
        with self._lock:
            self.track_knowledge = d
        plan = heads_up_cue_plan(k)
        key = None if plan is None else tuple((c.corner, round(c.target_m)) for c in plan.cues)
        if key != self._heads_up_key:
            self._heads_up_key = key
            self.cues.set_fallback_plan(plan)

    # --- race strategy (pitwall.strategy) ---
    def set_strategy(self, session_id: str, view: dict[str, Any] | None) -> None:
        """Publish the strategy worker's view of ``session_id``; dropped if another session went live meanwhile."""
        with self._lock:
            if session_id == self.session_id:
                self.strategy = view

    def set_cue_plan(self, plan: CuePlan | None) -> None:
        """Install a cue plan built outside the engine (normally the engine plans from ``on_lap_result``)."""
        self.cues.set_plan(plan)

    # ------------------------------------------------------------- writers (driver registry, any thread)
    def on_driver(self, driver_id: int | None, profile: CoachingProfile | None) -> None:
        """The driver in the seat changed or edited their profile (``drivers`` listener). Cues follow them: their
        coaching profile filters the focus corners, and a different driver drops the previous one's cue plan
        until the analysis publishes a lap against their own reference. Call once at start with the seated
        driver. The coaching selection (D6) follows the same limits (``drivers.CoachingLimits``; any other
        profile object means the default limits). Takes only the planners' locks (never blocks ingest)."""
        self.cues.set_driver(driver_id, profile)
        self.coach.set_limits(driver_id, profile if isinstance(profile, CoachingLimits) else None)
        self._driver_id = driver_id
        self._request_bests()  # a re-tagged session's personal bests are the new driver's

    # ------------------------------------------------------------- D2 bests
    def set_bests_requester(self, fn: Callable[[BestsRequest], None] | None) -> None:
        """``fn`` computes the live session's bests off the ingest thread (``AnalysisWorker.request_bests``). It
        is called whenever the session's context changes (session, game, track, car, known length, seated
        driver) and must never block: it runs on the ingest thread."""
        self._bests_requester = fn
        self._bests_requested = None
        self._request_bests()

    def set_bests(self, session_id: str, bests: dict[str, Any] | None) -> None:
        """Publish ``repo.lap_bests`` for ``session_id``; dropped if another session went live meanwhile."""
        with self._lock:
            if session_id == self.session_id:
                self.bests = bests

    def bests_request(self) -> BestsRequest | None:
        """The live session's bests context, or None while the session or its track is unknown."""
        s, sid = self.session, self.session_id
        if s is None or sid is None or not s.track_id:
            return None
        return BestsRequest(sid, s.game.value, s.track_id, s.car_id, s.track_length_m, self._driver_id)

    def _request_bests(self) -> None:
        fn = self._bests_requester
        req = self.bests_request()
        if fn is None or req is None:
            return
        # the length only decides the layout: an estimate refining every packet (AC, GT7) is not a new context
        key = (req.session_id, req.game, req.track_id, req.car_id, req.track_length_m is not None, req.driver_id)
        if key == self._bests_requested:
            return
        self._bests_requested = key
        with contextlib.suppress(Exception):  # never let a requester break ingest
            fn(req)

    def _track_length_m(self) -> float | None:
        """Lap length the analysis distance grid uses (track model), else the game's reported track length."""
        tm = self.track_model
        length = tm.get("length_m") if tm else None
        if isinstance(length, int | float) and not isinstance(length, bool):
            return float(length)
        s = self.session
        return s.track_length_m if s is not None else None

    def reset_session(self, session_id: str | None, source: str | None, synthetic: bool) -> None:
        with self._lock:
            self.session_id = session_id
            self.source = source
            self.synthetic = synthetic
            self.session = None
            self.frame = None
            self.laps.clear()
            self.observations = []
            self.last_comparison = None
            self.events.clear()
            self.reference = None
            self._ref_trace = None
            self.delta_s = None
            self.track_model = None
            self.skeleton = None
            self._skeleton_key = None
            self.marshal_flags = []
            self.session_state = None if session_id is None else SessionState(SESSION_RUNNING, None, time.time())
            self._red_flag_pitted = False
            self.bests = None
            self.strategy = None  # race strategy (pitwall.strategy)
            self._bests_requested = None  # the next session packet asks for the new session's bests
            self._heads_up_key = None  # the cue engine drops its heads-ups on reset; the next knowledge re-installs
        self.coach.reset()
        self.cues.reset_session()

    # ------------------------------------------------------------- readers
    def connection(self) -> dict[str, Any]:
        age = time.monotonic() - self.last_packet_mono if self.last_packet_mono else None
        status = "no_data" if age is None else ("live" if age < 2.0 else "stale")
        return {
            "status": status,
            "last_packet_age_s": None if age is None else round(age, 2),
            "packets": self.packets,
            "packets_per_s": round(self._pps if age is not None and age < 2.0 else 0.0, 1),
            "rejected": self.rejected,
            "unrecognised": self.unrecognised,
            "source": self.source,
            "synthetic": self.synthetic,
            "decode": self.decode_stats,
        }

    def snapshot(self, include_static: bool = False) -> dict[str, Any]:
        f = self.frame
        s = self.session
        with self._lock:
            out: dict[str, Any] = {
                "version": self.version,
                "connection": self.connection(),
                "session_id": self.session_id,
                "session": None
                if s is None
                else {
                    "game": s.game.value,
                    "platform": s.platform.value,
                    "track_id": s.track_id,
                    "track_name": s.track_name,
                    "track_length_m": s.track_length_m,
                    "session_type": s.session_type_raw or s.session_type.value,
                    "car_name": s.car_name,
                    "weather": asdict(s.weather),
                    "total_laps": s.total_laps,
                    "safety_car_status": s.safety_car_status,
                },
                "frame": None if f is None else frame_to_dict(f),
                "delta_s": None if self.delta_s is None else round(self.delta_s, 3),
                "reference": self.reference,
                "laps": list(self.laps)[:20],
                "observations": self.observations[:8],
                "events": list(self.events)[:10],
            }
            out["marshal_flags"] = self.marshal_flags
            st = self.session_state
            out["session_state"] = None if st is None else st.state
            out["session_state_info"] = None if st is None else st.to_dict()
            out["coach"] = self.coach.current
            out["bests"] = self.bests  # D2: small, so every snapshot (a record shows as set, not 5 s later)
            out["strategy"] = self.strategy  # race strategy (pitwall.strategy): about 2-3.5 kB, every snapshot
            if include_static:
                out["track_model"] = self.track_model
                out["last_comparison"] = self.last_comparison
                out["skeleton"] = self.skeleton
                out["track_knowledge"] = self.track_knowledge  # ~35 kB with the field line: static cadence
        out["cues"] = self.cues.snapshot()
        return out
