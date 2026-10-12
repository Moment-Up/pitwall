"""Position (group ``position``; every game with a race position, in race mode).

* **Grid** - F1: the position before lights out (the LapData position on the grid; real F1 25 sends
  ``gridPosition`` 0-based on PS5 - the pole sitter reads 0 - so it is not used [M]); GT7: the position at the race
  session's first frame (the rolling-start slot, P8 of 14 on the recording [M]); Forza: lap 1's first frame.
* **Lap-1 summary** - at the first line crossing of the race: the position and the gain or loss against the grid. No
  single position call before it: lap 1 churns (up to 42 changes on a real online start [M]).
* **Position change** - after lap 1, once the position has held for ``SETTLE_S`` [H], at most every ``COOLDOWN_S`` [H]
  (several changes merge into one call: "Down to P12, lost 4."), not within ``FLBK_S`` of a flashback, not in the pits.
  After lap 1 real races had 0-14 changes, at most 2 reverted within 3 s [M]. A move into P1 is outside the per-lap
  race allowance: taking the lead is always heard. A flashback also retracts unsaid position calls (the engine's
  ``take_retractions``).
* **Pit exit** - ``PIT_EXIT_S`` after leaving the pit lane in a race: "Out of the pits in P9."
* **Clean pass** (F1) - instead of the change call: a gain of exactly one place, the player's own OVTK in the settle
  window, no collision involving the player within ``COLL_WINDOW_S`` of it, no penalty for the player within
  ``PENA_AFTER_S`` after it (real penalties came 0.7-4.1 s after the contact [M]; Monza: a pass to P1 then a 3 s
  corner-cutting penalty 0.9 s later), the place held for ``PRAISE_HOLD_S``; at most one praise every
  ``PRAISE_EVERY_S`` [H]. Names the overtaken car when the roster has an official AI driver name.

GT7 and Forza send no overtake or collision events: position changes only (GT7: recorded, not compared with the game's
screen; Forza: community docs only).
"""

from __future__ import annotations

import math
from collections import deque

from pitwall.model.telemetry import CarFrame, GameEvent
from pitwall.raceradio import wording as W
from pitwall.raceradio.model import CallSpec
from pitwall.raceradio.state import RaceState

SETTLE_S = 3.0  # [H]
COOLDOWN_S = 20.0  # [H]
FLBK_S = 5.0
PIT_EXIT_S = 10.0  # [H]
OVTK_LEAD_S = 1.0  # an OVTK this long before the position change still belongs to it [M: same 0.1 s]
COLL_WINDOW_S = 2.0  # [H; M]
PENA_AFTER_S = 5.0  # [H; M: penalties 0.7-4.1 s after the contact]
PRAISE_HOLD_S = 5.0  # [H]
PRAISE_EVERY_S = 60.0  # [H]
POSITION_TTL_S = 15.0
LAP1_TTL_S = 30.0
EVENTS_KEPT_S = 30.0


class PositionTracker:
    def __init__(self) -> None:
        self.pos: int | None = None
        self.pos_since = -math.inf
        self.spoken: int | None = None
        self.lap1_done = False
        self._last_call = -math.inf
        self._pit_exit_at: float | None = None
        self._was_in_pits = False
        self._overtakes: deque[tuple[float, int | None]] = deque()  # (t, the car the player passed)
        self._collisions: deque[float] = deque()
        self._penalties: deque[float] = deque()
        self._last_praise = -math.inf

    def _said(self, st: RaceState, pos: int) -> None:
        self.spoken = pos
        self._last_call = st.t

    # ------------------------------------------------------------------ events (F1)
    def on_event(self, st: RaceState, e: GameEvent, out: list[CallSpec]) -> None:
        p = e.payload
        me = p.get("player_idx")
        if e.code == "OVTK" and p.get("overtakingVehicleIdx") == me:
            self._overtakes.append((st.t, p.get("beingOvertakenVehicleIdx")))
        elif e.code == "COLL" and me in (p.get("vehicle1Idx"), p.get("vehicle2Idx")):
            self._collisions.append(st.t)
        elif e.code == "PENA" and p.get("vehicleIdx") == me:
            self._penalties.append(st.t)
        elif e.code == "FLBK":
            self.pos_since = st.t
        for q in (self._collisions, self._penalties):
            while q and st.t - q[0] > EVENTS_KEPT_S:
                q.popleft()
        while self._overtakes and st.t - self._overtakes[0][0] > EVENTS_KEPT_S:
            self._overtakes.popleft()

    # ------------------------------------------------------------------ frames
    def on_frame(self, st: RaceState, f: CarFrame, out: list[CallSpec]) -> None:
        if not st.race:
            return
        pos = st.position
        if pos != self.pos:
            self.pos = pos
            self.pos_since = st.t
        if not self.lap1_done and f.lap_number is not None and f.lap_number >= 2 and st.crossing_t == -math.inf:
            # joined after lap 1 (no crossing seen in this session): the first position is the baseline, unsaid
            self.lap1_done = True
            self.spoken = pos
        in_pits = st.in_pits
        if self._was_in_pits and not in_pits:
            self._pit_exit_at = st.t + PIT_EXIT_S
        self._was_in_pits = in_pits
        if in_pits:
            self._pit_exit_at = None
        if self._pit_exit_at is not None and st.t >= self._pit_exit_at:
            self._pit_exit_at = None
            if pos is not None and f.lap_number is not None and f.lap_number >= 1:
                text, simple = W.pit_exit(pos)
                out.append(self._spec("pit_exit_position", text, simple, {"position": pos}))
                self._said(st, pos)
                self.lap1_done = True
            return
        self._change(st, out)

    def _change(self, st: RaceState, out: list[CallSpec]) -> None:
        pos, spoken, t = self.pos, self.spoken, st.t
        if not self.lap1_done or pos is None or spoken is None or pos == spoken:
            return
        held = t - self.pos_since
        if held < SETTLE_S or t - self._last_call < COOLDOWN_S or t - st.flbk_t < FLBK_S:
            return
        if st.in_pits or self._pit_exit_at is not None or st.finished or st.retired:
            return
        gain = spoken - pos
        ovtk = self._pass_of(st) if gain == 1 and st.f1 else None
        if ovtk is not None:
            t_ovtk, passed = ovtk
            if held < PRAISE_HOLD_S or t - t_ovtk < PENA_AFTER_S:
                return  # wait: a penalty for the move may still come
            clean = not any(abs(tc - t_ovtk) <= COLL_WINDOW_S for tc in self._collisions) and not any(
                0.0 <= tp - t_ovtk <= PENA_AFTER_S for tp in self._penalties
            )
            if clean and t - self._last_praise >= PRAISE_EVERY_S:
                self._last_praise = t
                name = st.roster.driver_name(passed)
                text, simple = W.clean_pass(pos, name)
                spec = self._spec(
                    "clean_pass",
                    text,
                    simple,
                    {"position": pos, "before": spoken, "passed": passed, "passed_name": name},
                    addressable=True,
                )
                spec.allowance = pos != 1  # taking the lead always gets through
                out.append(spec)
                self._said(st, pos)
                return
        text, simple = W.position_change(pos, spoken)
        spec = self._spec("position_change", text, simple, {"position": pos, "before": spoken}, addressable=gain > 0)
        spec.allowance = pos != 1  # a move into the lead always gets through
        out.append(spec)
        self._said(st, pos)

    def _pass_of(self, st: RaceState) -> tuple[float, int | None] | None:
        """The player's own overtake that made the current position, if any (in the settle window)."""
        for t_ovtk, passed in reversed(self._overtakes):
            if self.pos_since - OVTK_LEAD_S <= t_ovtk <= st.t:
                return t_ovtk, passed
        return None

    # ------------------------------------------------------------------ the line
    def on_crossing(self, st: RaceState, new_lap: int, out: list[CallSpec]) -> None:
        if not st.race or self.lap1_done or new_lap != 2:
            return
        self.lap1_done = True
        pos = st.position
        if pos is None:
            return
        text, simple = W.lap1_summary(pos, st.grid)
        out.append(
            CallSpec(
                group="position",
                call="lap1_summary",
                kind="race",
                priority="high",
                text=text,
                text_simple=simple,
                ttl_s=LAP1_TTL_S,
                topic="race:position",
                addressable=st.grid is not None and pos < st.grid,
                data={"position": pos, "grid": st.grid},
            )
        )
        self._said(st, pos)
        self.pos, self.pos_since = pos, st.t

    @staticmethod
    def _spec(call: str, text: str, simple: str, data: dict[str, object], *, addressable: bool = False) -> CallSpec:
        return CallSpec(
            group="position",
            call=call,
            kind="race",
            priority="normal",
            text=text,
            text_simple=simple,
            ttl_s=POSITION_TTL_S,
            topic="race:position",
            addressable=addressable,
            data=dict(data),
        )
