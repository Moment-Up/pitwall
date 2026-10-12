"""The race radio engine: one per session, pure and deterministic, clocked by the items' receive time.

``feed`` takes the session's items in stream order (``CarFrame``, ``LapCompletion``, ``SessionInfo``, ``GameEvent``,
``RaceTiming``, ``Participants``); ``take_calls`` hands out the calls made since the last call; ``view`` is the live
``RaceView``. No I/O, never blocks: the worker owns it.

Mode: ``race`` (F1 race; GT7 with a race length, a field and a race position; Forza with a race position),
``session`` (F1 practice and qualifying: flags, penalties, damage, minutes left) or ``off`` (time trial, spectating,
another game), with the reason in words.

Common suppression: while the player is ``retired`` (PENA 16, or a result status out of the race; a flashback clears
it - real data: a terminal-damage retirement followed by a flashback 14 s later [M]) or ``finished`` (after the finish
call), and while the latest frame is paused, a replay or out of the race, only urgent calls go out (the grid brief and
the finish are made on the grid and at the flag). Synthetic sessions make every call, tagged ``synthetic``.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from pitwall.analysis.track_skeleton import build_track_skeleton
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID
from pitwall.model.telemetry import (
    CarFrame,
    EventKind,
    FrameQuality,
    Game,
    GameEvent,
    LapCompletion,
    Participants,
    RaceTiming,
    SessionInfo,
    SessionType,
)
from pitwall.raceradio.countdown import Countdown, Memo
from pitwall.raceradio.damage import DamageWatcher
from pitwall.raceradio.flags import SLOW_KPH, FlagWatcher
from pitwall.raceradio.model import CALLS_SHOWN, RECORDED_CALLS, VIEW_VERSION, CallSpec, RaceCall, clean, off_view
from pitwall.raceradio.penalties import PenaltyWatcher
from pitwall.raceradio.positions import PositionTracker
from pitwall.raceradio.rivals import Rivals
from pitwall.raceradio.state import F1_GAMES, IN_PITS, OUT_OF_RACE, RaceState
from pitwall.raceradio.wording import speech_source

REASON_NO_INFO = "no session information yet"
REASON_SPECTATING = "spectating or a replay"
REASON_TIME_TRIAL = "time trial"
REASON_F1_OTHER = "not a race, practice or qualifying session"
REASON_GT7 = "GT7 sends a race position only in races"
REASON_FORZA = "Forza sends a race position only in races"
REASON_OTHER = "the race radio needs F1, GT7 or Forza race data"
FORZA_GAMES = (Game.FORZA_MOTORSPORT, Game.FORZA_HORIZON)
GRID_MAX_KPH = 5.0
NOT_DRIVING = FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING | FrameQuality.NOT_RACING
RACING_EXEMPT = frozenset({"grid_brief", "finish", "lights_out"})  # made on the grid / at the flag
NOTES = {
    Game.GT7: "From GT7's race position; not yet checked against the game's screen.",
    Game.FORZA_MOTORSPORT: "From Forza's race position (community docs); not checked on a real recording.",
    Game.FORZA_HORIZON: "From Forza's race position (community docs); not checked on a real recording.",
}


def _position_tier(game: Game | None) -> str | None:
    if game is None:
        return None
    from pitwall.capabilities import ADAPTER_INFOS  # light, but only needed for the view

    info = ADAPTER_INFOS.get(game)
    fs = None if info is None else info.fields.get("race_position")
    return None if fs is None else fs.level.value


class RaceRadioEngine:
    def __init__(
        self,
        session_id: str,
        *,
        track_model: Callable[[], Mapping[str, Any] | None] | None = None,
        memo: Memo | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.session_id = session_id
        self._clock = clock
        self.st = RaceState(session_id=session_id, track_model=track_model)
        self.flags = FlagWatcher()
        self.countdown = Countdown(memo)
        self.positions = PositionTracker()
        self.rivals = Rivals()
        self.penalties = PenaltyWatcher()
        self.damage = DamageWatcher()
        self._seq = 0
        self._max_crossed: int | None = None
        self._pending: list[RaceCall] = []
        self.recent: deque[RaceCall] = deque(maxlen=CALLS_SHOWN)
        self.dropped = 0  # calls suppressed (retired, finished, not driving, mode off)
        self.ended = False

    # ================================================================== input
    def feed(self, item: object) -> None:
        st = self.st
        t = getattr(item, "t_recv_ns", None)
        if isinstance(t, int):
            st.t = t / 1e9
            if st.t0 is None:
                st.t0 = st.t
        game = getattr(item, "game", None)
        if isinstance(game, Game) and st.game is None:
            st.game = game
        out: list[CallSpec] = []
        if isinstance(item, CarFrame):
            self._on_frame(item, out)
        elif isinstance(item, RaceTiming):
            self._on_timing(item, out)
        elif isinstance(item, GameEvent):
            self._on_event(item, out)
        elif isinstance(item, LapCompletion):
            self._on_lap(item, out)
        elif isinstance(item, SessionInfo):
            self._on_session(item, out)
        elif isinstance(item, Participants):
            st.roster.update(item)
        self.countdown.tick(st, out)
        self.penalties.tick(st, out)
        self.damage.tick(st, out)
        for spec in out:
            self._emit(spec)

    # ------------------------------------------------------------------ session
    def _on_session(self, info: SessionInfo, out: list[CallSpec]) -> None:
        st = self.st
        st.info = info
        st.game = info.game
        st.synthetic = bool(info.extra.get("synthetic")) or info.session_uid == str(SYNTHETIC_SESSION_UID)
        st.skeleton = build_track_skeleton(info) if info.track_zones is not None else None
        self._update_mode()
        self.flags.on_session(st, info, out)
        self.countdown.on_session(st, info, out)

    def _update_mode(self) -> None:
        st = self.st
        info, f, game = st.info, st.frame, st.game
        mode: str = "off"
        reason: str | None = REASON_OTHER
        if game in F1_GAMES:
            if info is None:
                mode, reason = "off", REASON_NO_INFO
            elif f is not None and f.quality & FrameQuality.REPLAY_OR_SPECTATING:
                mode, reason = "off", REASON_SPECTATING
            elif info.session_type is SessionType.RACE:
                mode, reason = "race", None
            elif info.session_type in (SessionType.PRACTICE, SessionType.QUALIFYING):
                mode, reason = "session", None
            elif info.session_type is SessionType.TIME_TRIAL:
                mode, reason = "off", REASON_TIME_TRIAL
            else:
                mode, reason = "off", REASON_F1_OTHER
        elif game is Game.GT7:
            cars = None if info is None else info.extra.get("num_cars_pre_race")
            ok = (
                info is not None
                and (info.total_laps or 0) >= 1
                and isinstance(cars, int)
                and cars >= 2
                and st.position is not None
            )
            mode, reason = ("race", None) if ok else ("off", REASON_GT7)
        elif game in FORZA_GAMES:
            mode, reason = ("race", None) if f is not None and f.race_position else ("off", REASON_FORZA)
        elif game is None:
            mode, reason = "off", REASON_NO_INFO
        st.mode, st.reason = mode, reason

    # ------------------------------------------------------------------ the player's car
    def _on_frame(self, f: CarFrame, out: list[CallSpec]) -> None:
        st = self.st
        st.frame = f
        st.racing = not (f.quality & NOT_DRIVING)
        st.in_pits = f.pit_status in IN_PITS
        if f.speed_kph is not None and f.speed_kph < SLOW_KPH:
            st.slow_t = st.t
        pos = f.race_position
        st.position = pos if isinstance(pos, int) and pos >= 1 else None
        self._update_mode()
        self._grid(f)
        lap = f.lap_number
        crossed = lap is not None and st.lap is not None and lap == st.lap + 1
        if lap is not None:
            st.lap = lap
        if crossed and lap is not None:
            self._crossing(lap, out)
        self.flags.on_frame(st, f, out)
        self.positions.on_frame(st, f, out)
        self.damage.on_frame(st, f, out)

    def _grid(self, f: CarFrame) -> None:
        """The player's starting position: on the grid before lights out (F1; LapData gridPosition is 0-based on real
        PS5 data [M], so the grid-time position is used), the first race frame (GT7), lap 1's first frame (Forza)."""
        st = self.st
        if not st.race or st.position is None:
            return
        if st.f1:
            standing = f.speed_kph is not None and f.speed_kph < GRID_MAX_KPH and (f.lap_number or 1) <= 1
            if st.lights_out_t is None and standing:
                st.grid = st.position
        elif st.grid is None and (st.game is Game.GT7 or (f.lap_number or 0) <= 1):
            st.grid = st.position

    def _crossing(self, new_lap: int, out: list[CallSpec]) -> None:
        st = self.st
        st.crossing_t = st.t
        if self._max_crossed is not None and new_lap <= self._max_crossed:
            return  # the same line again after a flashback
        self._max_crossed = new_lap
        self.positions.on_crossing(st, new_lap, out)  # "P8 after lap one", then "Two laps to go"
        self.countdown.on_crossing(st, new_lap, out)
        self.rivals.on_crossing(st, new_lap, out)

    def _on_lap(self, lc: LapCompletion, out: list[CallSpec]) -> None:
        self.countdown.on_lap(self.st, lc, out)
        if self.st.lap == lc.lap_number and not lc.final:
            # the line seen in the lap record before any frame of the new lap (F1 and GT7 send it first)
            self.st.lap = lc.lap_number + 1
            self._crossing(lc.lap_number + 1, out)

    # ------------------------------------------------------------------ field and events
    def _on_timing(self, rt: RaceTiming, out: list[CallSpec]) -> None:
        st = self.st
        st.timing = rt
        st.me = next((c for c in rt.cars if c.is_player), None)
        if st.me is not None and st.me.result_status in OUT_OF_RACE:
            st.retired = True
        self.rivals.on_timing(st, rt, out)

    def _on_event(self, e: GameEvent, out: list[CallSpec]) -> None:
        if e.kind is EventKind.BUTTON:
            return
        st = self.st
        code = e.code
        if code == "FLBK":
            st.flbk_t = st.t
            st.retired = False
        elif code == "LGOT":
            if st.grid is None:
                st.grid = st.position
            st.lights_out_t = st.t
        self.flags.on_event(st, e, out)
        self.countdown.on_event(st, e, out)
        self.positions.on_event(st, e, out)
        self.rivals.on_event(st, e, out)
        self.penalties.on_event(st, e, out)
        self.damage.on_event(st, e, out)

    # ================================================================== output
    def _emit(self, spec: CallSpec) -> None:
        st = self.st
        if not spec.urgent:
            blocked = (
                st.mode == "off"
                or st.retired
                or (st.finished and spec.call != "finish")
                or (not st.racing and spec.call not in RACING_EXEMPT)
            )
            if blocked:
                self.dropped += 1
                return
        self._seq += 1
        lap = st.lap
        if st.synthetic:
            tier = "synthetic"
        elif st.game in (Game.FORZA_MOTORSPORT, Game.FORZA_HORIZON):
            tier = "community"
        elif spec.tier is not None:
            tier = spec.tier
        else:
            tier = "recorded" if spec.call in RECORDED_CALLS else "synthetic"
        source = speech_source(spec.text)
        call = RaceCall(
            id=f"rc-{self._seq}-{lap if lap is not None else 0}",
            session_id=self.session_id,
            group=spec.group,
            call=spec.call,
            kind=spec.kind,
            priority=spec.priority,
            text=spec.text,
            text_simple=spec.text_simple,
            speech_source=source if source != spec.text else None,
            ttl_s=spec.ttl_s,
            needs_window=spec.needs_window,
            bypass_quiet=spec.bypass_quiet,
            topic=spec.topic,
            lap=lap,
            addressable=spec.addressable,
            defer_to_strategy_detail=spec.defer_to_strategy_detail,
            audience=spec.audience,
            allowance=spec.allowance,
            data=clean(spec.data),
            tier=tier,
            synthetic=st.synthetic,
            t_unix=self._clock(),
        )
        self._pending.append(call)
        self.recent.appendleft(call)

    def take_calls(self) -> list[RaceCall]:
        out, self._pending = self._pending, []
        return out

    def end(self) -> None:
        self.ended = True

    def view(self) -> dict[str, Any]:
        """The live ``RaceView`` (``raceradio.model``)."""
        st = self.st
        game = None if st.game is None else st.game.value
        out = off_view(st.reason, self.session_id, st.synthetic, game)
        out["calls"] = [c.entry() for c in self.recent]
        if st.mode == "off":
            return out
        info = st.info
        left, _source = st.laps_left() if st.race else (None, None)
        sc = None if info is None else info.safety_car_status
        if st.red_flag_t is not None:
            track = "red"
        elif st.neutral is not None:
            track = "sc" if st.neutral == "full" else "vsc"
        elif sc == "formation_lap":
            track = "formation"
        elif sc == "none":
            track = "green"
        else:
            track = None
        f = st.frame
        pen = None if f is None else f.penalties
        time_left = None if info is None else info.session_time_left_s
        out.update(
            mode=st.mode,
            reason=None,
            position=st.position,
            cars=st.cars,
            grid_position=st.grid,
            position_tier=_position_tier(st.game) if st.position is not None else None,
            position_note=NOTES.get(st.game) if st.game is not None and st.position is not None else None,
            lap=st.lap,
            total_laps=st.total_laps if st.race else None,
            laps_left=None if left is None else round(left, 1),
            final_lap=bool(st.race and left is not None and 0 < left <= 1.0 and not st.finished),
            time_left_s=round(time_left) if st.mode == "session" and time_left and time_left > 0 else None,
            flags={
                "track": track if st.f1 else None,
                "you": None if f is None else f.fia_flag,
                "yellow_ahead": self.flags.yellow_ahead,
            },
            penalties=None
            if pen is None
            else {
                "time_s": pen.time_penalties_s,
                "warnings": pen.warnings,
                "track_limits": pen.corner_cutting_warnings,
                "drive_throughs": pen.unserved_drive_throughs,
                "stop_gos": pen.unserved_stop_gos,
                "serve_at_stop": pen.serve_at_stop,
            },
            damage=self.damage.view(),
            ahead=self.rivals.side_view(st, self.rivals.gaps.ahead) if st.f1 and st.race else None,
            behind=self.rivals.side_view(st, self.rivals.gaps.behind) if st.f1 and st.race else None,
        )
        out["version"] = VIEW_VERSION
        view: dict[str, Any] = clean(out)
        return view
