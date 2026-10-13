"""Start and countdown (group ``start``): grid brief, lights out, laps to go, last lap, the finish, minutes left.

* **Grid brief** - F1 race: at SSTA (or the first STLG when SSTA was missed) while the car stands on the grid (under
  ``GRID_MAX_KPH``, lap 1 or before): "P20 of 22, 3 laps." No speak window (stationary; the driver may hold the brake)
  and a TTL of ``GRID_TTL_S`` from SSTA [M: SSTA -> lights out is 5.3-10.4 s on 16 of 17 real standing starts]. A
  formation-lap session (``safety_car_status`` "formation_lap": a separate session UID [M]) gets the brief at its first
  frames with a speak window, and the race session that follows within ``FORMATION_MEMO_S`` skips its own (the worker's
  memo, keyed by track and race length). GT7 lap race: "Rolling start. P8 of 14, 10 laps." at the session's first
  frames before lap 1, with a speak window [recorded: P8 of 14 before the start].
* **Lights out** - F1 LGOT in a race on lap 1: "Go, go." No speak window, ``LIGHTS_TTL_S``; it is motivation, not a
  reaction aid (about 0.4-0.6 s after the lights).
* **Laps to go** - at each line crossing in a race, with ``strategy.laps_left`` (F1: the lapped-car rule on the
  field's timing; GT7: laps only): five laps to go (races of 10 laps or more), two laps to go (races of 5 laps or more:
  a 3-lap race heard its length in the grid brief and gets "Last lap" next), last lap (the lapped variant when the
  leader finishes first). CHQF while the player is still racing and the last lap was not said: "Flag's out. Last lap."
  Each once per session.
* **Finish** - F1: the final ``LapCompletion``; GT7: the completion of lap ``total_laps``: the position and the change
  from the grid; with time penalties still to add (F1 LapData), the position "on the road" and the seconds instead of
  the change. Then the session is ``finished`` (only urgent calls after it).
* **Allowance** - the grid brief, lights out, the countdown and the finish are never held by the radio's per-lap
  budget (``allowance=False``; they still spend it): said standing still, at the line (inside the lap summary) or
  after the flag, they must not wait behind a lap's position news or warnings (a 3-lap race heard 7 of 14 calls with
  them held [M]).
* **Evidence** - "Flag's out. Last lap." and the lapped last lap came from no real capture: tagged synthetic whatever
  the call's name. The formation-lap brief is recorded (Imola, 2026-10-11: "P3 of 20, 32 laps." in the formation-lap
  session; the race session after it skipped its own).
* **Minutes left** - F1 practice and qualifying: five minutes and one minute left, only for a positive time left
  (one-shot qualifying sends 0 [M]). [synthetic]
"""

from __future__ import annotations

from typing import Any

from pitwall.model.telemetry import CarFrame, Game, GameEvent, LapCompletion, SessionInfo
from pitwall.raceradio import wording as W
from pitwall.raceradio.model import CallSpec
from pitwall.raceradio.state import RaceState

GRID_TTL_S = 2.0  # [M] from SSTA
GRID_MAX_KPH = 5.0
FORMATION_TTL_S = 30.0
GT7_BRIEF_TTL_S = 20.0
FORMATION_MEMO_S = 600.0  # [H] a race session this soon after its formation-lap session skips the grid brief
LIGHTS_TTL_S = 1.5
COUNTDOWN_TTL_S = 30.0
FINISH_TTL_S = 60.0
MINUTES_TTL_S = 30.0
LAPS_5_MIN_TOTAL = 10
LAPS_2_MIN_TOTAL = 5
MINUTE_MARKS = (300.0, 60.0)
Memo = dict[tuple[str | None, int | None], float]


class Countdown:
    def __init__(self, memo: Memo | None = None) -> None:
        self.memo: Memo = memo if memo is not None else {}
        self._brief_until: float | None = None
        self._brief_done = False
        self._formation = False
        self._said: set[str] = set()
        self._crossed: int | None = None  # the highest lap number a crossing was handled for
        self._time_left: float | None = None

    # ------------------------------------------------------------------ helpers
    def _once(self, name: str) -> bool:
        if name in self._said:
            return False
        self._said.add(name)
        return True

    @staticmethod
    def _memo_key(st: RaceState) -> tuple[str | None, int | None]:
        info = st.info
        return (None if info is None else info.track_id, st.total_laps)

    # ------------------------------------------------------------------ session
    def on_session(self, st: RaceState, info: SessionInfo, out: list[CallSpec]) -> None:
        if st.f1 and st.race and info.safety_car_status == "formation_lap" and not self._brief_done:
            self._formation = True
        if st.f1 and st.mode == "session":
            left = info.session_time_left_s
            prev, self._time_left = self._time_left, left
            if left is not None and prev is not None and left > 0:
                for mark in MINUTE_MARKS:
                    n = round(mark / 60)
                    if prev > mark >= left and self._once(f"minutes_{n}"):
                        text, simple = W.minutes_left(n)
                        out.append(
                            CallSpec(
                                group="start",
                                call=f"minutes_{n}",
                                kind="race",
                                priority="normal",
                                text=text,
                                text_simple=simple,
                                ttl_s=MINUTES_TTL_S,
                                topic="race:countdown",
                                data={"time_left_s": round(left)},
                            )
                        )

    # ------------------------------------------------------------------ events
    def on_event(self, st: RaceState, e: GameEvent, out: list[CallSpec]) -> None:
        code = e.code
        if code == "SSTA" or (code == "STLG" and self._brief_until is None):
            if not self._brief_done:
                self._brief_until = st.t + GRID_TTL_S
        elif code == "LGOT":
            self._brief_until = None
            if st.f1 and st.race and (st.lap or 1) <= 1 and self._once("lights_out"):
                text, simple = W.LIGHTS_OUT
                out.append(
                    CallSpec(
                        group="start",
                        call="lights_out",
                        kind="race",
                        priority="high",
                        text=text,
                        text_simple=simple,
                        ttl_s=LIGHTS_TTL_S,
                        needs_window=False,
                        allowance=False,  # said at the start, not part of lap 1's race news
                    )
                )
        elif (
            # CHQF: the leader took the flag, so a player who is still racing (and not the leader) is on the last lap
            code == "CHQF"
            and st.race
            and st.f1
            and not st.finished
            and not st.retired
            and st.position not in (None, 1)
            and self._once("last_lap")
        ):
            spec = self._last_lap(W.LAST_LAP_FLAG, "flag")
            spec.tier = "synthetic"  # no real capture made it (the countdown said "Last lap" at the line first)
            out.append(spec)

    # ------------------------------------------------------------------ frames and laps
    def tick(self, st: RaceState, out: list[CallSpec]) -> None:
        """Per item: the grid brief while it is due."""
        if self._brief_done:
            return
        f = st.frame
        if f is None or not st.race:
            return
        if st.game is Game.GT7:
            if f.lap_number is None and st.position is not None and st.cars:  # before the rolling start
                self._brief(st, out, rolling=True, ttl=GT7_BRIEF_TTL_S, window=True)
            elif f.lap_number is not None:
                self._brief_done = True  # joined after the start: no brief
            return
        if not st.f1:
            return
        if self._formation:
            if (f.lap_number or 1) <= 1:
                self._brief(st, out, rolling=False, ttl=FORMATION_TTL_S, window=True)
                self.memo[self._memo_key(st)] = st.t
            return
        until = self._brief_until
        if until is None:
            return
        if st.t > until:
            self._brief_until = None
            return
        speed = f.speed_kph
        if speed is None or speed >= GRID_MAX_KPH or (f.lap_number or 1) > 1:
            return
        seen = self.memo.get(self._memo_key(st))
        if seen is not None and 0.0 <= st.t - seen <= FORMATION_MEMO_S:
            self._brief_done = True  # said at the formation lap
            return
        self._brief(st, out, rolling=False, ttl=max(0.5, until - st.t), window=False)

    def _brief(self, st: RaceState, out: list[CallSpec], *, rolling: bool, ttl: float, window: bool) -> None:
        grid = st.position if st.position is not None else st.grid
        built = W.grid_brief(grid, st.cars, st.total_laps, rolling=rolling)
        self._brief_done = True
        self._brief_until = None
        if built is None:
            return
        text, simple = built
        out.append(
            CallSpec(
                group="start",
                call="grid_brief",
                kind="race",
                priority="high",
                text=text,
                text_simple=simple,
                ttl_s=ttl,
                needs_window=window,
                allowance=False,  # said standing on the grid (or before the rolling start)
                data={"grid": grid, "cars": st.cars, "laps": st.total_laps, "rolling": rolling},
            )
        )

    def on_crossing(self, st: RaceState, new_lap: int, out: list[CallSpec]) -> None:
        """The player crossed the line onto ``new_lap`` (a race)."""
        if not st.race or (self._crossed is not None and new_lap <= self._crossed):
            return
        self._crossed = new_lap
        left, source = st.laps_left(lap=new_lap, lap_frac=0.0)
        if left is None:
            return
        n = round(left)
        total = st.total_laps or 0
        if n == 5 and total >= LAPS_5_MIN_TOTAL and self._once("laps_5"):
            out.append(self._laps(5, "normal"))
        elif n == 2 and total >= LAPS_2_MIN_TOTAL and self._once("laps_2"):
            out.append(self._laps(2, "high"))
        elif n == 1 and self._once("last_lap"):
            lapped = source == "leader"
            spec = self._last_lap(W.LAST_LAP_LAPPED if lapped else W.LAST_LAP, source or "laps")
            spec.data["at_line"] = True
            if lapped:
                spec.tier = "synthetic"  # no real capture had the leader finish first
            out.append(spec)

    @staticmethod
    def _laps(n: int, priority: Any) -> CallSpec:
        text, simple = W.laps_to_go(n)
        return CallSpec(
            group="start",
            call=f"laps_{n}",
            kind="race",
            priority=priority,
            text=text,
            text_simple=simple,
            ttl_s=COUNTDOWN_TTL_S,
            topic="race:countdown",
            allowance=False,  # at the line: never starves the lap's position news
            data={"laps_left": n, "at_line": True},
        )

    @staticmethod
    def _last_lap(text: str, source: str) -> CallSpec:
        return CallSpec(
            group="start",
            call="last_lap",
            kind="race",
            priority="high",
            text=text,
            text_simple=W.LAST_LAP_SIMPLE,
            ttl_s=COUNTDOWN_TTL_S,
            topic="race:countdown",
            addressable=True,
            allowance=False,  # at the line: never starves the lap's position news
            data={"source": source},
        )

    def on_lap(self, st: RaceState, lc: LapCompletion, out: list[CallSpec]) -> None:
        if not st.race:
            return
        if st.f1:
            done = lc.final is True
        elif st.game is Game.GT7:
            done = st.total_laps is not None and lc.lap_number == st.total_laps
        else:
            done = False
        if not done or not self._once("finish"):
            return
        pen = None if st.frame is None or st.frame.penalties is None else st.frame.penalties.time_penalties_s
        to_add = pen if isinstance(pen, int) and pen > 0 and st.f1 else None
        text, simple = W.finish(st.position, st.grid, to_add)
        out.append(
            CallSpec(
                group="start",
                call="finish",
                kind="race",
                priority="high",
                text=text,
                text_simple=simple,
                ttl_s=FINISH_TTL_S,
                topic="race:countdown",
                addressable=True,
                allowance=False,  # after the flag: never starved by the last lap's race allowance
                data={"position": st.position, "grid": st.grid, "time_penalties_s": to_add},
            )
        )
        st.finished = True

    def on_frame(self, st: RaceState, f: CarFrame, out: list[CallSpec]) -> None:
        """Nothing per frame beyond ``tick`` (kept for the engine's uniform dispatch)."""
