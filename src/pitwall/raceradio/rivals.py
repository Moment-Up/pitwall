"""Rivals (group ``rivals``; F1 races): gap reports, the car ahead pitting, fastest laps and retirements.

* **Gap report** - at the line on lap ``GAP_FIRST_LAP`` and every ``GAP_EVERY_LAPS`` after [H], with at least one
  settled gap (the race strategy's own ``GapTracker`` rules, a second instance), not under a safety car / VSC, not on
  the last lap, not in the pits. Trend words ("closing") when the line gaps' slope is at least
  ``TREND_MIN_S_PER_LAP`` [H] over 3 or more laps. Topic ``strategy:gap``: shared with strategy's gap calls, the newest
  queued one wins.
* **Car ahead pitting** - the tracker's pit entry of the car ahead, from lap 2, the player not in the pits. Marked
  ``defer_to_strategy_detail``: at detailed intensity strategy's richer neighbour call is said instead.
* **Fastest laps** - the player's own (FTLP) from lap 2, at most every ``FL_EVERY_LAPS`` laps (real short races give the
  player FTLP on every lap [M]); another car's from race lap ``RIVAL_FL_MIN_LAP`` (INFO: detailed intensity only).
* **Retirements** - RTMT for another car, or its result status leaving "active" for retired / DNF / DSQ / not
  classified; once per car, ignored within ``IGNORE_AFTER_FLBK_S`` of a flashback and in the session's first
  ``IGNORE_AT_START_S``, and for a car never seen racing in this session (F1 re-sends RTMT for cars already out after
  every flashback and at a mid-race join [M]).
  RACE when the car ran within ``NEAR_PLACES`` of the player, INFO otherwise. The reason only when the game gives a
  meaningful one (RTMT reason was 0 on every real retirement [M]: never said).
"""

from __future__ import annotations

import math

from pitwall.model.telemetry import GameEvent, RaceTiming
from pitwall.raceradio import wording as W
from pitwall.raceradio.model import CallSpec
from pitwall.raceradio.state import OUT_OF_RACE, RaceState
from pitwall.strategy.gaps import GapTracker, Side
from pitwall.voice.proactive import fmt_lap_time

GAP_FIRST_LAP = 3  # [H]
GAP_EVERY_LAPS = 3  # [H]
TREND_MIN_S_PER_LAP = 0.1  # [H]
FL_EVERY_LAPS = 3  # [M]
RIVAL_FL_MIN_LAP = 3
NEAR_PLACES = 3
IGNORE_AFTER_FLBK_S = 5.0  # [M]
IGNORE_AT_START_S = 5.0  # [M]
FTLP_AFTER_LINE_S = 2.0  # an FTLP this soon after the player's line crossing is about the lap just done
GAP_TTL_S = 30.0
PITTING_TTL_S = 20.0
FL_TTL_S = 20.0
RETIRE_TTL_S = 30.0


class Rivals:
    def __init__(self) -> None:
        self.gaps = GapTracker()
        self._last_own_fl: int | None = None
        self._last_rival_fl: int | None = None
        self._retired: set[int] = set()
        self._last_pos: dict[int, int] = {}
        self._result: dict[int, str | None] = {}
        self._seen_active: set[int] = set()  # cars seen racing in this session (a retirement must be news)

    # ------------------------------------------------------------------ timing
    def on_timing(self, st: RaceState, rt: RaceTiming, out: list[CallSpec]) -> None:
        events = self.gaps.update(rt)
        if st.neutral is not None and st.lap is not None:
            self.gaps.mark_neutral_lap(st.lap)
        for c in rt.cars:
            before = self._result.get(c.car_index)
            self._result[c.car_index] = c.result_status
            if not c.is_player and before == "active" and c.result_status in OUT_OF_RACE:
                self._retirement(st, c.car_index, None, out)
            if c.result_status == "active":
                self._last_pos[c.car_index] = c.position
                self._seen_active.add(c.car_index)
        if not st.race:
            return
        for ev in events:
            if ev.kind == "pit_entry" and ev.side == "ahead" and (st.lap or 0) >= 2 and not st.in_pits:
                kind, label = st.roster.label(ev.car_index, "the car ahead")
                text, simple = W.car_ahead_pitting(kind, label)
                out.append(
                    CallSpec(
                        group="rivals",
                        call="car_ahead_pitting",
                        kind="race",
                        priority="normal",
                        text=text,
                        text_simple=simple,
                        ttl_s=PITTING_TTL_S,
                        defer_to_strategy_detail=True,
                        data={"car_index": ev.car_index, "label_kind": kind},
                    )
                )

    # ------------------------------------------------------------------ events
    def on_event(self, st: RaceState, e: GameEvent, out: list[CallSpec]) -> None:
        p = e.payload
        me = p.get("player_idx")
        if e.code == "FLBK":
            target = p.get("flashbackSessionTime")
            if isinstance(target, int | float):
                self.gaps.rewind(float(target))
        elif e.code == "RTMT":
            car = p.get("vehicleIdx")
            if isinstance(car, int) and car != me:
                reason = p.get("reason")
                self._retirement(st, car, reason if isinstance(reason, int) else None, out)
        elif e.code == "FTLP" and st.race:
            self._fastest_lap(st, p.get("vehicleIdx"), p.get("lapTime"), me, out)

    def _fastest_lap(self, st: RaceState, car: object, lap_time: object, me: object, out: list[CallSpec]) -> None:
        lap = st.lap
        if lap is None or not isinstance(car, int):
            return
        if car == me:
            done = lap - 1 if st.t - st.crossing_t <= FTLP_AFTER_LINE_S else lap  # the lap the time was set on
            if done < 2 or (self._last_own_fl is not None and done - self._last_own_fl < FL_EVERY_LAPS):
                return
            self._last_own_fl = done
            text, simple = W.OWN_FASTEST_LAP
            out.append(
                CallSpec(
                    group="rivals",
                    call="own_fastest_lap",
                    kind="race",
                    priority="normal",
                    text=text,
                    text_simple=simple,
                    ttl_s=FL_TTL_S,
                    addressable=True,
                    data={"lap": done},
                )
            )
            return
        if lap < RIVAL_FL_MIN_LAP or (self._last_rival_fl is not None and lap - self._last_rival_fl < FL_EVERY_LAPS):
            return
        if not isinstance(lap_time, int | float) or not math.isfinite(lap_time) or lap_time <= 0:
            return
        self._last_rival_fl = lap
        kind, label = st.roster.label(car)
        out.append(
            CallSpec(
                group="rivals",
                call="rival_fastest_lap",
                kind="info",
                priority="low",
                text=W.rival_fastest_lap(kind, label, fmt_lap_time(round(lap_time * 1000))),
                text_simple=None,
                ttl_s=FL_TTL_S,
                audience="experienced",
                data={"car_index": car, "label_kind": kind, "lap_time_ms": round(lap_time * 1000)},
            )
        )

    def _retirement(self, st: RaceState, car: int, reason: int | None, out: list[CallSpec]) -> None:
        if car in self._retired:
            return
        self._retired.add(car)
        t0 = st.t0 if st.t0 is not None else st.t
        if st.t - st.flbk_t < IGNORE_AFTER_FLBK_S or st.t - t0 < IGNORE_AT_START_S or not st.race:
            return  # re-sends after a flashback / at a mid-race join [M]: remembered, never said
        if car not in self._seen_active:
            return  # never seen racing in this session: out before it started (a re-send), or no timing yet [M]
        last = self._last_pos.get(car)
        me = st.position
        near = last is not None and me is not None and abs(last - me) <= NEAR_PLACES
        kind, label = st.roster.label(car)
        text, simple = W.retirement(kind, label, last if near else None, W.RETIREMENT_REASONS.get(reason or 0))
        out.append(
            CallSpec(
                group="rivals",
                call="retirement",
                kind="race" if near else "info",
                priority="normal" if near else "low",
                text=text,
                text_simple=simple if near else None,
                ttl_s=RETIRE_TTL_S,
                audience=None if near else "experienced",
                data={"car_index": car, "label_kind": kind, "position": last, "near": near},
            )
        )

    # ------------------------------------------------------------------ the line
    def on_crossing(self, st: RaceState, new_lap: int, out: list[CallSpec]) -> None:
        if not st.race or not st.f1 or new_lap < GAP_FIRST_LAP or (new_lap - GAP_FIRST_LAP) % GAP_EVERY_LAPS:
            return
        if st.neutral is not None or st.in_pits:
            return
        left, _source = st.laps_left(lap=new_lap, lap_frac=0.0)
        if left is not None and round(left) <= 1:
            return  # the last lap: the countdown speaks
        ahead, behind = self.gaps.ahead, self.gaps.behind
        a, a_slope = self._gap(ahead)
        b, b_slope = self._gap(behind)
        leading = st.position == 1
        built = W.gap_report(None if leading else a, a_slope, b, b_slope, leading)
        if built is None:
            return
        text, simple = built
        out.append(
            CallSpec(
                group="rivals",
                call="gap_report",
                kind="race",
                priority="normal",
                text=text,
                text_simple=simple,
                ttl_s=GAP_TTL_S,
                topic="strategy:gap",
                data={"ahead_s": a, "behind_s": b, "ahead_trend": a_slope, "behind_trend": b_slope},
            )
        )

    def _gap(self, side: Side) -> tuple[float | None, float | None]:
        """(the last settled gap to the current car, its trend when strong enough) of one side."""
        if side.car_index is None or side.value_s is None:
            return None, None
        slope, _n = self.gaps.trend(side)
        if slope is None or abs(slope) < TREND_MIN_S_PER_LAP:
            slope = None
        return round(side.value_s, 1), None if slope is None else round(slope, 2)

    def side_view(self, st: RaceState, side: Side) -> dict[str, object] | None:
        """The view's ``ahead`` / ``behind`` (non-personal label only)."""
        car = side.car
        if car is None or side.car_index is None:
            return None
        kind, label = st.roster.label(side.car_index, "the car " + side.name)
        return {
            "label": label,
            "label_kind": kind,
            "position": car.position,
            "gap_s": None if side.value_s is None else round(side.value_s, 1),
            "settled": side.settled,
        }
