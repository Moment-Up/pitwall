"""Session manager: turns the decoded stream into persisted sessions, laps and events.

Runs on the ingest thread, so every operation here is O(1) per frame; anything heavier (lap analysis,
database writes) is handed to background workers.

Driver ownership: each session is tagged at start with the active driver. The driver source
(``pitwall.drivers.DriverService``) publishes an immutable ``SeatState``; the manager loads it once per item and,
only when its ``version`` moved (someone else got in the seat, the live session was re-assigned, an owner was
deleted), re-checks ownership from that one consistent snapshot:

* a session with no completed lap that is on track (or has not seen a car frame yet) is simply re-tagged to the
  new driver: nothing has been attributed yet;
* a session with laps whose car is on track is split: it ends (the lap in progress is flushed as incomplete under
  the previous driver) and a new one starts at once for the new driver, carrying the game session's context
  (track, car, weather, setup), so no lap is ever stored against the wrong person;
* if the car is *not* on track (no car frame for ``ON_TRACK_WINDOW_S``: the game is in its menus, where button
  events keep arriving) the session just ends. Carrying the old track, car and game UID into a new session there
  would create a junk session for the new driver, who will start their own game session; the next item starts
  a fresh session tagged with them (and, if it turns out to be the same game session, its setup is carried).

The manager remembers the seat version it last acted on, so a re-assignment it has already taken into account can
never override a later re-tag of its own (``SeatState.owner``).

Replays are nobody's driving: a replay manager ignores the seat and its sessions are stored without a driver.
Without a driver source (headless tools) live sessions are still tagged: ``repo.insert_session`` falls back to the
persisted active driver.

Pace vs AI (``core.ai_pace``): the other cars' lap lists (``CarLapHistory``) and the session's AI difficulty are
collected per *game* session (O(1) per item). The collector is reset when the game session UID changes, never when a
pitwall session ends (a driver split keeps the game session); after every lap of the player and when the session ends
its snapshot goes to the analysis worker, which stores ``session_ai_pace``. ``sessions.ai_difficulty`` is written
whenever the resolved level of the session changes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any, Protocol

from pitwall.analysis.ai_pace import DIFFICULTY_UNKNOWN
from pitwall.analysis.laps import LapAssembler, LapTrace
from pitwall.core.ai_pace import AiPaceCollector
from pitwall.core.lap_processor import AnalysisWorker, LapJob
from pitwall.core.live import LiveState
from pitwall.drivers import SeatState
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID
from pitwall.model.telemetry import (
    CarFrame,
    CarLapHistory,
    CarSetup,
    Emitted,
    EventKind,
    FieldSample,
    GameEvent,
    LapCompletion,
    SessionInfo,
)
from pitwall.storage import repo
from pitwall.storage.db import DbWriter

log = logging.getLogger(__name__)

RESUME_WINDOW_S = 900.0  # a restart this soon after the session's last write may continue it (same game UID)
ON_TRACK_WINDOW_S = 2.0  # a car frame this recent means the car is on track (paused games still send frames)
_ON_TRACK_WINDOW_NS = int(ON_TRACK_WINDOW_S * 1e9)


class ActiveDriverSource(Protocol):
    """What the ingest thread needs from ``pitwall.drivers.DriverService``: one lock-free snapshot load."""

    @property
    def seat(self) -> SeatState: ...


class FieldSink(Protocol):
    """Where the other cars' samples go (``core.track_knowledge.FieldWorker``): O(1), never blocks ingest."""

    def submit(self, item: FieldSample | SessionInfo) -> bool: ...

    def end_session(self) -> None: ...


class SessionManager:
    def __init__(
        self,
        writer: DbWriter,
        live: LiveState,
        worker: AnalysisWorker,
        source: str,
        synthetic: bool = False,
        capture_path: str | None = None,
        overrides: dict[str, Any] | None = None,
        drivers: ActiveDriverSource | None = None,
        resume_candidate: Mapping[str, Any] | None = None,
        field: FieldSink | None = None,
    ) -> None:
        self.writer = writer
        self.live = live
        self.field = field  # layer L0b: the field model learns the track from the other cars (off this thread)
        self.worker = worker
        self.source = source
        self.synthetic = synthetic
        self._synthetic_source = synthetic  # set by the caller (a synthetic replay): never cleared by the stream
        self.capture_path = capture_path
        self.overrides = overrides or {}  # e.g. track_name for synthetic captures
        self.session_id: str | None = None
        self._game_uid: str | None = None
        self._info: SessionInfo | None = None
        self._info_key: tuple[Any, ...] | None = None
        self._setup_fp: str | None = None
        self._ground_plane: tuple[str, str] = ("pos_x_m", "pos_z_m")
        self._assembler = LapAssembler(self._on_lap)
        self._last_t_ns: int | None = None
        self.sessions_started = 0
        # a replay re-processes recorded laps: it never follows (or splits for) whoever is in the seat now
        self.drivers = None if repo.is_replay_source(source) else drivers
        self.driver_id: int | None = None  # owner of the current session as far as this manager knows
        self._driver_version = self.drivers.seat.version if self.drivers is not None else 0
        self._owner_version = self._driver_version  # seat version self.driver_id is up to date with
        self._game: str | None = None
        self._last_setup: CarSetup | None = None
        self._last_frame_ns: int | None = None  # latest car frame of the current session (on-track test)
        self._carry_setup: tuple[str, CarSetup] | None = None  # (game uid, setup) of a session ended off track
        self._laps_in_session = 0
        self.driver_splits = 0
        # The last session this live source wrote before the service (re)started. If the game is still in that
        # same session (same session UID) the restart must not split the driver's race: see ``_maybe_resume``.
        self._resume: Mapping[str, Any] | None = None if repo.is_replay_source(source) else resume_candidate
        self.sessions_resumed = 0
        self._ai = AiPaceCollector()  # pace vs AI inputs of the current game session (core.ai_pace)
        self._ai_written: tuple[str | None, int | None] = (None, None)  # (session id, ai_difficulty) last stored

    def set_ground_plane(self, plane: tuple[str, str]) -> None:
        self._ground_plane = plane

    # ------------------------------------------------------------------ lifecycle
    def _start(self, game: str, t_ns: int) -> None:
        sid = repo.new_session_id()
        self.session_id = sid
        self.sessions_started += 1
        self._assembler = LapAssembler(self._on_lap)
        self._info = None
        self._info_key = None
        self._setup_fp = None
        self._last_setup = None
        self._game = game
        self._laps_in_session = 0
        self._last_frame_ns = None
        self._ai_written = (sid, None)  # a new row's ai_difficulty is NULL
        driver: int | None = None
        if self.drivers is not None:
            seat = self.drivers.seat
            driver = seat.active_id
            self._driver_version = self._owner_version = seat.version
        self.driver_id = driver
        synthetic = self.synthetic  # bound now: the writer runs later, after the flag may have changed
        self.writer.submit(
            lambda c: repo.insert_session(
                c, sid, game, self.source, synthetic, self.capture_path, t_ns, driver_id=driver
            )
        )
        self.live.reset_session(sid, self.source, self.synthetic, game)
        log.info(
            "session %s started (%s, source=%s, synthetic=%s, driver=%s)",
            sid,
            game,
            self.source,
            self.synthetic,
            driver,
        )

    def end(self) -> None:
        if self.session_id is None:
            return
        self._assembler.flush()
        self._submit_ai(final=True)  # the collector is kept: a new pitwall session of the same game session reuses it
        sid, t_end = self.session_id, self._last_t_ns
        self.writer.submit(lambda c: repo.end_session(c, sid, t_end))
        if self.field is not None:
            self.field.end_session()
        log.info("session %s ended", sid)
        self.session_id = None
        self._game_uid = None

    # ------------------------------------------------------------------ stream
    def handle(self, e: Emitted) -> None:
        if isinstance(e, FieldSample):
            # Another car's sample (layer L0b): not the player's data - it never starts or splits a session and is
            # never persisted. Straight to the field worker (a lock-free append) or nowhere.
            if self.field is not None:
                self.field.submit(e)
            return
        if isinstance(e, CarLapHistory):
            # A car's lap list (pace vs AI): never starts a session or counts as activity; O(1) dict store.
            if self.session_id is not None:
                self._ai.on_history(e)
            return
        self._last_t_ns = e.t_recv_ns
        if self.drivers is not None:
            seat = self.drivers.seat  # one attribute load per item; all decisions below use this snapshot
            if seat.version != self._driver_version:
                self._sync_driver(seat, e)  # rare: only after a driver change, never per frame
        if isinstance(e, SessionInfo):
            self._on_session(e)
            return
        if isinstance(e, GameEvent) and self.session_id is None:
            # menus send button events with no session: drive PTT but don't create an empty session
            self.live.on_event(e)
            if e.kind == EventKind.BUTTON and isinstance(e.payload.get("buttonStatus"), int):
                self.live.on_button(e.payload["buttonStatus"])
            return
        if self.session_id is None:
            self._start(e.game.value, e.t_recv_ns)
        if isinstance(e, CarFrame):
            self._last_frame_ns = e.t_recv_ns
            self.live.on_frame(e)
            self._assembler.feed(e)
        elif isinstance(e, LapCompletion):
            self._assembler.feed_completion(e)
        elif isinstance(e, GameEvent):
            self._on_event(e)
        elif isinstance(e, CarSetup):
            self._setup_fp = e.fingerprint()
            self._last_setup = e
            sid = self.session_id
            assert sid is not None
            self.writer.submit(lambda c: repo.insert_setup(c, sid, e))

    def _on_session(self, info: SessionInfo) -> None:
        uid = info.session_uid
        if self.synthetic and not self._synthetic_source and uid and uid != str(SYNTHETIC_SESSION_UID):
            # The synthetic demo was streamed into this live listener and now a real game is: the demo session ends
            # (with its synthetic track id) and what follows is real.
            log.info("real session UID after a synthetic stream: the next session is not synthetic")
            self.end()
            self.synthetic = False
            self.live.synthetic = False
        if uid == str(SYNTHETIC_SESSION_UID) and not self.synthetic:
            log.warning("stream carries the synthetic generator's session UID: flagging session as SYNTHETIC")
            self.synthetic = True
            self.live.synthetic = True
            sid = self.session_id
            if sid is not None:
                self.writer.submit(lambda c: c.execute("UPDATE sessions SET synthetic=1 WHERE id=?", (sid,)))
        if self.overrides.get("track_name"):
            info.track_name = self.overrides["track_name"]
        if self.synthetic:
            # Synthetic geometry lives in its own namespace so it can never pollute a real track's model,
            # corners or reference laps.
            info.extra["synthetic"] = True
            info.track_id = f"synthetic:{self.overrides.get('scenario') or 'unknown'}"
        if self.session_id is not None and self._game_uid is not None and uid and uid != self._game_uid:
            self.end()
        if self.session_id is None:
            self._start(info.game.value, info.t_recv_ns)
        self._game_uid = uid or self._game_uid
        if uid and uid != self._ai.game_uid:
            self._ai.reset(uid)  # after any end() above: the old session's final AI job used the old collector
        self._ai.on_info(info)
        self._store_ai_difficulty()
        if self._resume is not None and uid:
            cand, self._resume = self._resume, None  # only the first session after start-up can be a resume
            self._maybe_resume(cand, uid)
        if uid and self._carry_setup is not None:
            self._resume_setup(uid)
        self._info = info
        self._assembler.set_track_length(info.track_length_m)
        self.live.on_session(info)
        if self.field is not None:
            self.field.submit(info)  # after the synthetic re-keying above: the field model uses the same track id
        key = (
            info.track_id,
            info.track_length_m,  # GT7/Forza learn it after the first lap
            None if info.track_zones is None else info.track_zones.geometry_key(),  # first packets carry no zones
            info.extra.get("ac_line_norm"),  # AC: a confirmed start/finish line must be saved with the session
            info.extra.get("ac_geometry_rejected"),
            info.extra.get("track_length_quality"),  # AC: an estimate a full lap confirmed keeps its value
            info.session_type,
            info.car_id,
            info.weather.condition,
            info.weather.track_temp_c,
            info.platform,
            tuple(sorted(info.assists.items())),
        )
        if key != self._info_key:
            self._info_key = key
            sid = self.session_id
            assert sid is not None
            self.writer.submit(lambda c: repo.update_session_info(c, sid, info))

    def _maybe_resume(self, cand: Mapping[str, Any], uid: str) -> None:
        """Continue ``cand`` instead of the session just started, when the service restarted mid-session.

        Only when the game reports the same session UID (F1: a random 64-bit id per game session), nothing has
        been completed in the new session yet, the old session belongs to the same driver, and it ended (or the
        process died) within ``RESUME_WINDOW_S``. All in memory: the merge itself is a writer job.
        """
        old, new = cand.get("id"), self.session_id
        if not old or new is None or old == new or cand.get("game_session_uid") != uid or self.synthetic:
            return
        if self._laps_in_session or cand.get("driver_id") != self.driver_id:
            return
        last_unix = cand.get("ended_unix") or cand.get("started_unix") or 0.0
        if time.time() - float(last_unix) > RESUME_WINDOW_S and cand.get("ended_unix") is not None:
            return
        self.session_id = old
        self.sessions_resumed += 1
        self.writer.submit(lambda c: repo.resume_session(c, old, new))
        self.live.reset_session(old, self.source, self.synthetic, self._game)
        self._ai_written = (old, None)  # never erase the resumed row's level with this run's early "unknown"
        self._info_key = None  # re-store the session info on the resumed row
        log.info("session %s resumed after a restart (same game session %s); %s merged into it", old, uid, new)

    # ------------------------------------------------------------------ driver changes
    def _sync_driver(self, seat: SeatState, e: Emitted) -> None:
        self._driver_version = seat.version
        sid = self.session_id
        if sid is None:
            return  # the next session is tagged with whoever is active when it starts
        owner = seat.owner(sid, self.driver_id, self._owner_version)
        self.driver_id = owner
        self._owner_version = seat.version
        active = seat.active_id
        if active is None or active == owner:
            return
        if _ends_session(e, self._game_uid):
            return  # this item ends the session anyway; the next one starts with the new driver (no empty split)
        on_track = self._last_frame_ns is not None and e.t_recv_ns - self._last_frame_ns <= _ON_TRACK_WINDOW_NS
        if self._laps_in_session == 0 and (on_track or self._last_frame_ns is None):
            log.info("session %s re-tagged from driver %s to %s (no laps yet)", sid, owner, active)
            self.driver_id = active
            self.writer.submit(lambda c: repo.set_session_driver(c, sid, active))
        elif on_track:
            self._split_for_driver(e.t_recv_ns)
        else:
            self._end_for_driver()

    def _split_for_driver(self, t_ns: int) -> None:
        """End the current session and start a new one for the active driver, keeping the game context."""
        old, game = self.session_id, self._game
        info, uid, setup, setup_fp = self._info, self._game_uid, self._last_setup, self._setup_fp
        track_model = self.live.track_model  # geometry is shared by all drivers: keep the live map
        self.end()
        if game is None:
            return
        self._start(game, t_ns)  # resets live state, including the previous driver's reference (never shown again)
        if track_model is not None:
            self.live.set_track_model(track_model)
        self.driver_splits += 1
        sid = self.session_id
        assert sid is not None
        self._game_uid = uid
        self._setup_fp = setup_fp
        self._last_setup = setup
        if setup is not None:
            self.writer.submit(lambda c: repo.insert_setup(c, sid, setup))
        if info is not None:
            self._on_session(info)
        log.info("driver change: session %s split, continuing as %s for driver %s", old, sid, self.driver_id)

    def _end_for_driver(self) -> None:
        """The car is not on track (game menus): end the session without starting one in the menus. Remember the
        setup in case the new driver continues the same game session (the game only re-sends setup changes)."""
        old, uid, setup = self.session_id, self._game_uid, self._last_setup
        self.end()
        self._carry_setup = (uid, setup) if uid and setup is not None else None
        log.info("driver change off track: session %s ended; the next session starts for the new driver", old)

    def _resume_setup(self, uid: str) -> None:
        """First game UID of a session after an off-track driver change: same game session -> same setup."""
        carry, self._carry_setup = self._carry_setup, None
        sid = self.session_id
        if carry is None or carry[0] != uid or self._last_setup is not None or sid is None:
            return
        setup = carry[1]
        self._last_setup = setup
        self._setup_fp = setup.fingerprint()
        self.writer.submit(lambda c: repo.insert_setup(c, sid, setup))

    def _store_ai_difficulty(self) -> None:
        """Write ``sessions.ai_difficulty`` when the resolved level of this pitwall session changed. Too few
        readings so far ("unknown") never writes: a fresh row is NULL already, and a resumed one keeps its level."""
        sid = self.session_id
        level, status = self._ai.difficulty
        if sid is None or status == DIFFICULTY_UNKNOWN or self._ai_written == (sid, level):
            return
        self._ai_written = (sid, level)
        self.writer.submit(lambda c: repo.set_session_ai_difficulty(c, sid, level))

    def _submit_ai(self, *, final: bool) -> None:
        """Hand the AI pace inputs to the analysis worker (never blocks; F1 only: other games collect nothing)."""
        sid = self.session_id
        if sid is None or not self._ai.has_data:
            return
        self.worker.submit_ai_pace(self._ai.job(sid, synthetic=self.synthetic, final=final))

    def _on_event(self, e: GameEvent) -> None:
        self.live.on_event(e)
        if e.kind == EventKind.FLASHBACK:
            self._ai.on_flashback(e)
        if e.kind == EventKind.BUTTON:
            status = e.payload.get("buttonStatus")
            if isinstance(status, int):
                self.live.on_button(status)  # wheel push-to-talk etc.
            return  # very frequent; not useful to persist
        sid = self.session_id
        assert sid is not None
        if _involves_player(e):
            self.writer.submit(lambda c: repo.insert_event(c, sid, e))
        if e.kind == EventKind.SESSION_ENDED:
            self.end()

    def _on_lap(self, lap: LapTrace) -> None:
        sid = self.session_id
        if sid is None:
            return
        self._laps_in_session += 1
        info = self._info
        ctx: dict[str, Any] = {
            "game": info.game.value if info else None,
            "track_id": info.track_id if info else None,
            "track_name": info.track_name if info else None,
            "track_length_m": info.track_length_m if info else None,
            "car_id": info.car_id if info else None,
            "weather": info.weather.condition if info else None,
            "track_temp_c": info.weather.track_temp_c if info else None,
            "assists": dict(info.assists) if info else {},
            "setup_fp": self._setup_fp,
        }
        self.worker.submit(LapJob(session_id=sid, lap=lap, context=ctx, ground_plane=self._ground_plane))
        self._submit_ai(final=False)


def _ends_session(e: Emitted, game_uid: str | None) -> bool:
    if isinstance(e, SessionInfo):
        return bool(e.session_uid and game_uid and e.session_uid != game_uid)
    return isinstance(e, GameEvent) and e.kind == EventKind.SESSION_ENDED


_PER_CAR_FIELDS = (
    "vehicleIdx",
    "otherVehicleIdx",
    "overtakingVehicleIdx",
    "beingOvertakenVehicleIdx",
    "vehicle1Idx",
    "vehicle2Idx",
)


def _involves_player(e: GameEvent) -> bool:
    """Per-car events (overtakes, collisions, penalties, speed traps) are stored only when they concern the
    player's car - a 20-car race produces hundreds of AI-vs-AI overtakes."""
    player = e.payload.get("player_idx")
    idxs = [e.payload[k] for k in _PER_CAR_FIELDS if k in e.payload]
    return not idxs or player is None or player in idxs
