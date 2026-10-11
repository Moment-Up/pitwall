"""Proactive strategy calls: when the race engineer speaks up, and what it says (deterministic templates).

The engine hands the planner one ``CallContext`` per timing tick; the planner returns the calls due now. Calls are
said only through the radio scheduler's speak windows (``strategy.radio``). Rules:

* Races only. Nothing on a formation lap, under a red flag, on the final lap (the player's own: a lapped player's
  race ends a lap early) or while the player is in the pit lane; nothing on lap 1 except the safety car and a
  critical fuel call. Nothing about the gaps while a safety car or VSC bunches the field.
* Budget per player lap: at most one ``normal`` and two ``detailed`` calls; ``alert`` calls are limited per topic
  by their cooldowns.
* Several calls due on the same tick go in priority order: safety car > fuel critical > last laps of the tyre
  window > undercut threat > weather / crossover > fuel tight > pit window open > undercut chance > a neighbour
  pitting > gaps.
* Every text is at most ``MAX_TEXT`` characters and built only from numbers in ``data``. Lift and coast is always
  "lift before your braking point, brake at your normal point": nothing here tells the driver to brake later.
* ``text_simple``: the same call without the jargon (box, undercut, DRS, lift and coast), for a driver whose profile
  asks for simple wording; None where the call is only for experienced drivers (``audience``).
* A figure that is only the game's own (the window closing on its tyre laps-left figure) says so on the radio, and
  the window calls wait until the stint has ``MIN_STINT_LAPS`` laps after a stop: just after a stop the game's figure
  for a used set is all there is, and it is often far more cautious than the wear the set then shows.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any

from pitwall.analysis.strategy import MIN_STINT_LAPS

MAX_TEXT = 120
NORMAL_PER_LAP = 1
DETAILED_PER_LAP = 2

ORDER = (
    "sc_box",
    "sc_stay",
    "fuel_critical",
    "pit_window_last",
    "undercut_threat",
    "weather",
    "crossover",
    "fuel_tight",
    "pit_window_open",
    "undercut_chance",
    "neighbour_stop",
    "gap_within",
    "gap_trend",
)
TOPIC = {
    "sc_box": "sc_box",
    "sc_stay": "sc_stay",
    "fuel_critical": "fuel",
    "fuel_tight": "fuel",
    "pit_window_last": "pit_window",
    "pit_window_open": "pit_window",
    "undercut_threat": "undercut_threat",
    "undercut_chance": "undercut_chance",
    "neighbour_stop": "neighbour_stop",
    "gap_within": "gap",
    "gap_trend": "gap",
    "weather": "weather",
    "crossover": "crossover",
}
FUEL_CRIT_WORSEN_LAPS = 0.2
FUEL_CRIT_REPEAT_LAPS = 3
FUEL_TIGHT_REPEAT_LAPS = 4
WINDOW_MOVE_LAPS = 3
CHANCE_REPEAT_LAPS = 3
GAP_REPEAT_LAPS = 3
GAP_WITHIN_REPEAT_LAPS = 10  # the same car
GAP_WITHIN_ANY_LAPS = 3  # any car: in a pack the car behind changes every lap or two
TREND_MIN_CLOSING = 0.2  # s/lap
TREND_AHEAD_MAX_LAPS = 5.0
TREND_BEHIND_MAX_GAP_S = 3.0
WEATHER_REPEAT_S = 300.0
CROSSOVER_REPEAT_LAPS = 3
_ids = itertools.count(1)


@dataclass(slots=True, frozen=True)
class StrategyCall:
    id: str
    topic: str
    level: str  # "alert" | "normal" | "detailed"
    priority: str  # "high" | "normal" | "low"
    text: str
    lap: int | None
    ttl_s: float
    bypass_quiet: bool
    audience: str  # "all" | "experienced"
    data: dict[str, Any]
    t_unix: float
    text_simple: str | None = None  # the same call in plain words (simple wording); None: experienced drivers only

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "level": self.level,
            "priority": self.priority,
            "text": self.text,
            "text_simple": self.text_simple,
            "lap": self.lap,
            "ttl_s": round(self.ttl_s, 1),
            "bypass_quiet": self.bypass_quiet,
            "audience": self.audience,
            "data": self.data,
            "t_unix": round(self.t_unix, 3),
        }


@dataclass(slots=True)
class CallContext:
    """What the planner needs on one tick (the engine fills it)."""

    t: float  # game clock (s)
    lap: int | None
    total_laps: int | None
    laps_remaining: float | None
    player_in_pit: bool
    blocked: str | None  # "formation lap" | "red flag" | None
    new_lap: bool = False  # the first tick of a player lap: lap-level estimates (fuel) are judged only then
    stops_done: int | None = None  # None until the first timing tick
    stint_laps: int | None = None  # laps of the current stint, this one included
    # safety car
    sc_status: str | None = None  # "full" | "virtual" while neutralised
    sc_period: int = 0
    sc_box: dict[str, Any] | None = None
    entry_ttl_s: float | None = None
    # fuel
    fuel_margin_laps: float | None = None
    fuel_status: str = "unknown"
    lift_coast: dict[str, Any] | None = None
    # pit window
    # {"open_lap","close_lap","ideal_lap","overdue","close_source"} while a stop is needed
    window: dict[str, Any] | None = None
    # cuts
    undercut_ahead: dict[str, Any] | None = None
    undercut_threat: dict[str, Any] | None = None
    gain_s: float | None = None
    # events since the last tick
    behind_pitting: int | None = None  # car index of the car behind that just entered the pit lane
    behind_stops: int | None = None
    ahead_pitting: dict[str, Any] | None = None  # NeighbourStopView of the car ahead that just entered the lane
    within_behind: int | None = None  # car index of the car behind that just came within a second
    drs_behind: bool | None = None
    trends: list[dict[str, Any]] = field(default_factory=list)  # line gaps just taken: {side, car, gap_s, slope}
    # weather
    next_weather: dict[str, Any] | None = None
    weather_now: str | None = None
    crossover: dict[str, Any] | None = None


def _num(v: float, nd: int = 1) -> str:
    s = f"{v:.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _join_corners(corners: list[str]) -> str:
    if not corners:
        return ""
    if len(corners) == 1:
        return corners[0]
    return ", ".join(corners[:-1]) + " and " + corners[-1]


_SC_NAME = {"full": "Safety car", "virtual": "Virtual safety car"}
_WET_NAME = {"inter": "inters", "wet": "wets"}
_WET_SIMPLE = {"inter": "intermediate rain tyres", "wet": "full wet tyres"}
_RAINY = frozenset({"light_rain", "heavy_rain", "storm"})


class CallPlanner:
    def __init__(self, clock: Any = time.time) -> None:
        self._clock = clock
        self._spent: dict[tuple[int, str], int] = {}  # (lap, level) -> calls made
        self._sc_box: set[int] = set()
        self._sc_stay: set[int] = set()
        self._fuel_crit: tuple[int, float] | None = None  # (lap, margin) of the last critical call
        self._fuel_tight: int | None = None
        self._window_open: tuple[int | None, int] | None = None  # (stops done, close lap) of the last call
        self._window_last: tuple[int | None, int] | None = None  # (stops done, close lap) of the last call
        self._threat_stops: set[tuple[int, int | None]] = set()
        self._chance: int | None = None
        self._chance_prev: str | None = None
        self._neighbour: set[tuple[int, int]] = set()
        self._within: dict[int, int] = {}  # car -> lap of the last call
        self._trend: dict[tuple[str, int], int] = {}
        self._weather: tuple[float, tuple[Any, ...]] | None = None
        self._crossover: dict[str, int] = {}

    # ------------------------------------------------------------------ main
    def plan(self, ctx: CallContext) -> list[StrategyCall]:
        if ctx.blocked is not None or ctx.player_in_pit or ctx.lap is None:
            return []
        lap = ctx.lap
        if ctx.total_laps is not None and lap >= ctx.total_laps:
            return []  # the final lap: nothing to act on
        if ctx.laps_remaining is not None and ctx.laps_remaining <= 1.0:
            return []  # the player's own final lap (lapped: the leader takes the flag first)
        cands: list[tuple[str, StrategyCall]] = []
        for key in ORDER:
            if lap <= 1 and key not in ("sc_box", "sc_stay", "fuel_critical"):
                continue
            call = getattr(self, "_t_" + key)(ctx)
            if call is not None:
                cands.append((key, call))
        out: list[StrategyCall] = []
        for _key, call in cands:
            if call.level in ("normal", "detailed"):
                cap = NORMAL_PER_LAP if call.level == "normal" else DETAILED_PER_LAP
                spent = self._spent.get((lap, call.level), 0)
                if spent >= cap:
                    continue
                self._spent[(lap, call.level)] = spent + 1
            self._commit(_key, call, ctx)
            out.append(call)
        for k in [k for k in self._spent if k[0] < lap - 2]:
            del self._spent[k]
        return out

    def _make(
        self,
        key: str,
        ctx: CallContext,
        level: str,
        priority: str,
        text: str,
        ttl_s: float,
        *,
        bypass: bool = False,
        audience: str = "all",
        data: dict[str, Any] | None = None,
        simple: str | None = None,
    ) -> StrategyCall:
        if len(text) > MAX_TEXT:
            text = text[: MAX_TEXT - 1].rstrip(" ,:;") + "."
        if simple is not None and len(simple) > MAX_TEXT:
            simple = simple[: MAX_TEXT - 1].rstrip(" ,:;") + "."
        return StrategyCall(
            id=f"st-{TOPIC[key]}-{ctx.lap}-{next(_ids)}",
            topic=TOPIC[key],
            level=level,
            priority=priority,
            text=text,
            lap=ctx.lap,
            ttl_s=ttl_s,
            bypass_quiet=bypass,
            audience=audience,
            data=data or {},
            t_unix=self._clock(),
            text_simple=simple if audience == "all" else None,
        )

    def _commit(self, key: str, call: StrategyCall, ctx: CallContext) -> None:
        """Remember a call that was actually made (cooldowns start here, not when a candidate lost the budget)."""
        lap = ctx.lap or 0
        d = call.data
        if key == "sc_box":
            self._sc_box.add(ctx.sc_period)
        elif key == "sc_stay":
            self._sc_stay.add(ctx.sc_period)
        elif key == "fuel_critical":
            self._fuel_crit = (lap, float(d["margin_laps"]))
        elif key == "fuel_tight":
            self._fuel_tight = lap
        elif key == "pit_window_open":
            self._window_open = (ctx.stops_done, int(d["close_lap"]))
        elif key == "pit_window_last":
            self._window_last = (ctx.stops_done, int(d["close_lap"]))
        elif key == "undercut_threat":
            self._threat_stops.add((int(d["car_index"]), d.get("stops")))
        elif key == "undercut_chance":
            self._chance = lap
        elif key == "neighbour_stop":
            self._neighbour.add((int(d["car_index"]), lap))
        elif key == "gap_within":
            self._within[int(d["car_index"])] = lap
        elif key == "gap_trend":
            self._trend[(str(d["side"]), int(d["car_index"]))] = lap
        elif key == "weather":
            self._weather = (ctx.t, (d.get("in_min"), d.get("weather")))
        elif key == "crossover":
            self._crossover[str(d["compound"])] = lap

    # ------------------------------------------------------------------ triggers
    def _t_sc_box(self, ctx: CallContext) -> StrategyCall | None:
        box = ctx.sc_box
        if ctx.sc_status is None or box is None or not box.get("stop_needed") or ctx.sc_period in self._sc_box:
            return None
        name = _SC_NAME[ctx.sc_status]
        this_lap = box.get("this_lap")  # None: the pit entry is not known yet (no stop seen in this race)
        when = "this lap " if this_lap else "next lap " if this_lap is False else ""
        loss, green = box.get("pit_loss_s"), box.get("green_pit_loss_s")
        data: dict[str, Any] = {"status": ctx.sc_status, "this_lap": None if this_lap is None else bool(this_lap)}
        you_can = " You can pit this lap." if this_lap else " You can pit next lap." if this_lap is False else ""
        if loss is not None and green is not None:
            text = (
                f"{name}. Pitting {when}is an option: a stop costs about {_num(loss, 0)} s now, "
                f"{_num(green, 0)} s under green."
            )
            simple = (
                f"{name}: a pit stop is cheap now, about {_num(loss, 0)} seconds instead of {_num(green, 0)}.{you_can}"
            )
            data.update(pit_loss_s=loss, green_pit_loss_s=green)
        else:
            text = f"{name}. Pitting {when}is an option."
            simple = f"{name}: a pit stop costs less now.{you_can}"
        ttl = ctx.entry_ttl_s if (this_lap and ctx.entry_ttl_s and ctx.entry_ttl_s > 0) else 60.0
        return self._make("sc_box", ctx, "alert", "high", text, ttl, bypass=True, data=data, simple=simple)

    def _t_sc_stay(self, ctx: CallContext) -> StrategyCall | None:
        box = ctx.sc_box
        if ctx.sc_status is None or box is None or box.get("stop_needed") is not False:
            return None
        if ctx.sc_period in self._sc_stay:
            return None
        name = _SC_NAME[ctx.sc_status]
        text = f"{name}. Tyres reach the finish: no stop needed."
        simple = f"{name}: your tyres last to the finish, so no pit stop."
        return self._make("sc_stay", ctx, "normal", "normal", text, 30.0, data={"status": ctx.sc_status}, simple=simple)

    def _t_fuel_critical(self, ctx: CallContext) -> StrategyCall | None:
        m = ctx.fuel_margin_laps
        if not ctx.new_lap or ctx.fuel_status != "short" or m is None:
            return None  # judged at the line: fuel burn within a lap is uneven (flat out, then lifting)
        lap = ctx.lap or 0
        last = self._fuel_crit
        if last is not None and not (m <= last[1] - FUEL_CRIT_WORSEN_LAPS or lap - last[0] >= FUEL_CRIT_REPEAT_LAPS):
            return None
        short = abs(m)
        data: dict[str, Any] = {"margin_laps": round(m, 2), "short_laps": round(short, 1)}
        lnc = ctx.lift_coast
        head = f"Fuel critical: {_num(short)} laps short."
        if lnc is not None:
            secs = float(lnc["seconds_per_lap"])
            data["lift_s_per_lap"] = secs
            corners = list(lnc.get("corners") or [])
            text = f"{head} Lift and coast about {_num(secs)} s a lap, brake at your normal point."
            if corners:
                with_corners = (
                    f"{head} Lift and coast about {_num(secs)} s a lap before {_join_corners(corners)}, "
                    "brake at your normal point."
                )
                if len(with_corners) <= MAX_TEXT:
                    text = with_corners
        else:
            text = f"{head} Lift and coast before your braking points, brake at your normal point."
        simple = "Fuel is short. Lift off a little before each braking point, then brake as normal."
        return self._make("fuel_critical", ctx, "alert", "high", text, 120.0, bypass=True, data=data, simple=simple)

    def _t_fuel_tight(self, ctx: CallContext) -> StrategyCall | None:
        m = ctx.fuel_margin_laps
        if not ctx.new_lap or ctx.fuel_status != "tight" or m is None:
            return None
        lap = ctx.lap or 0
        if self._fuel_tight is not None and lap - self._fuel_tight < FUEL_TIGHT_REPEAT_LAPS:
            return None
        if abs(m) < 0.05:
            text = "Fuel is tight: right on the limit to the finish."
            simple = "Fuel is tight: only just enough to finish."
        else:
            text = f"Fuel is tight: plus {_num(m)} laps to the finish."
            simple = "Fuel is tight, but there is just enough to finish."
        data = {"margin_laps": round(m, 2)}
        return self._make("fuel_tight", ctx, "normal", "normal", text, 120.0, data=data, simple=simple)

    @staticmethod
    def _window_too_early(ctx: CallContext, w: dict[str, Any]) -> bool:
        """Just after a stop, a window that closes on the game's laps-left figure is not called yet."""
        return (
            bool(ctx.stops_done)
            and w.get("close_source") != "measured"
            and ctx.stint_laps is not None
            and ctx.stint_laps <= MIN_STINT_LAPS
        )

    def _t_pit_window_open(self, ctx: CallContext) -> StrategyCall | None:
        w = ctx.window
        if w is None or ctx.lap != w["open_lap"] or w.get("overdue") or ctx.lap is None:
            return None
        o, c = int(w["open_lap"]), int(w["close_lap"])
        if c <= ctx.lap or self._window_too_early(ctx, w):
            return None  # a window of this lap only is the "last laps" call's, or none at all once overdue
        last = self._window_open
        # once per stint; again only when the window's close moved WINDOW_MOVE_LAPS earlier
        if last is not None and last[0] == ctx.stops_done and c > last[1] - WINDOW_MOVE_LAPS:
            return None
        ideal = w.get("ideal_lap")
        game = w.get("close_source") == "game"
        text = f"Pit window is open: laps {o} to {c}" + (f", best around {ideal}" if ideal is not None else "")
        text += ", on the game's tyre figure." if game else "."
        simple = f"Pit stop window open: any lap from {o} to {c}" + (
            f", best lap {ideal}." if ideal is not None else "."
        )
        data = {"open_lap": o, "close_lap": c, "ideal_lap": ideal, "close_source": w.get("close_source")}
        return self._make("pit_window_open", ctx, "normal", "normal", text, 90.0, data=data, simple=simple)

    def _t_pit_window_last(self, ctx: CallContext) -> StrategyCall | None:
        w = ctx.window
        if w is None or w.get("overdue") or ctx.lap != int(w["close_lap"]) - 1 or self._window_too_early(ctx, w):
            return None
        c = int(w["close_lap"])
        last = self._window_last
        if last is not None and last[0] == ctx.stops_done and abs(c - last[1]) < WINDOW_MOVE_LAPS:
            return None  # said for this stint already (the close moving a lap or two is not news)
        if w.get("close_source") == "game":
            text = "The game's tyre figure says last laps of the window: box this lap or next."
            simple = "Pit this lap or next: the game says your tyres are nearly worn out."
        else:
            text = "Last laps of the tyre window: box this lap or next."
            simple = "Pit this lap or next: your tyres are nearly worn out."
        data = {"close_lap": c, "close_source": w.get("close_source")}
        return self._make("pit_window_last", ctx, "alert", "normal", text, 60.0, data=data, simple=simple)

    def _t_undercut_threat(self, ctx: CallContext) -> StrategyCall | None:
        idx = ctx.behind_pitting
        threat = ctx.undercut_threat
        w = ctx.window
        if idx is None or threat is None or w is None or (idx, ctx.behind_stops) in self._threat_stops:
            return None
        if threat.get("status") not in ("likely", "marginal"):
            return None
        if not (int(w["open_lap"]) <= (ctx.lap or 0) <= int(w["close_lap"])):
            return None
        # the pit entry is learned from the stops seen in this race: unknown before the first one, so no lap is named
        this_lap = None if ctx.entry_ttl_s is None else ctx.entry_ttl_s > 0
        when = "this lap " if this_lap else "next lap " if this_lap is False else ""
        text = f"Car behind is pitting. Box {when}to cover the undercut."
        ttl = float(ctx.entry_ttl_s) if this_lap and ctx.entry_ttl_s is not None else 45.0
        data = {"car_index": idx, "stops": ctx.behind_stops, "status": threat.get("status"), "this_lap": this_lap}
        return self._make("undercut_threat", ctx, "normal", "high", text, ttl, audience="experienced", data=data)

    def _t_undercut_chance(self, ctx: CallContext) -> StrategyCall | None:
        cut = ctx.undercut_ahead
        status = None if cut is None else cut.get("status")
        prev, self._chance_prev = self._chance_prev, status
        w = ctx.window
        if cut is None or status != "likely" or prev == "likely" or w is None or ctx.gain_s is None:
            return None
        if not (int(w["open_lap"]) <= (ctx.lap or 0) <= int(w["close_lap"])):
            return None
        lap = ctx.lap or 0
        if self._chance is not None and lap - self._chance < CHANCE_REPEAT_LAPS:
            return None
        gap = cut.get("gap_s")
        if gap is None:
            return None
        text = (
            f"Undercut on the car ahead looks on: gap {_num(gap)} s, new tyres worth about {_num(ctx.gain_s)} s a lap."
        )
        data = {"gap_s": gap, "gain_s": ctx.gain_s}
        return self._make("undercut_chance", ctx, "detailed", "normal", text, 45.0, audience="experienced", data=data)

    def _t_neighbour_stop(self, ctx: CallContext) -> StrategyCall | None:
        ns = ctx.ahead_pitting
        if ns is None or (int(ns["car_index"]), ctx.lap or 0) in self._neighbour:
            return None
        gap, status = ns.get("rejoin_gap_s"), ns.get("status")
        if status == "covered" and gap is not None:
            text = f"Car ahead is pitting: it rejoins about {_num(gap, 0)} s behind you."
        elif status == "ahead" and gap is not None:
            text = f"Car ahead is pitting: it rejoins about {_num(abs(gap), 0)} s ahead of you."
        elif status == "close":
            text = "Car ahead is pitting: it rejoins close to you."
        else:
            text = "Car ahead is pitting."
        if ns.get("traffic") and status != "unknown":
            text += " It rejoins in traffic."
        data = {"car_index": int(ns["car_index"]), "rejoin_gap_s": gap, "status": status}
        return self._make("neighbour_stop", ctx, "detailed", "low", text, 30.0, audience="experienced", data=data)

    def _t_gap_within(self, ctx: CallContext) -> StrategyCall | None:
        # Detail, not a call to act on: the detailed radio setting only, once per car every GAP_WITHIN_REPEAT_LAPS and
        # for any car every GAP_WITHIN_ANY_LAPS (real Austria: four times in ten laps at the normal setting was
        # chatter). Never under SC / VSC (bunched).
        idx = ctx.within_behind
        lap = ctx.lap or 0
        if idx is None or lap < 2 or ctx.sc_status is not None:
            return None
        last = self._within.get(idx)
        if last is not None and lap - last < GAP_WITHIN_REPEAT_LAPS:
            return None
        if self._within and lap - max(self._within.values()) < GAP_WITHIN_ANY_LAPS:
            return None
        text = "Car behind is within a second" + (", DRS range." if ctx.drs_behind else ".")
        data = {"car_index": idx, "drs_range": bool(ctx.drs_behind)}
        return self._make("gap_within", ctx, "detailed", "low", text, 20.0, data=data, simple="Car close behind you.")

    def _t_gap_trend(self, ctx: CallContext) -> StrategyCall | None:
        lap = ctx.lap or 0
        if ctx.sc_status is not None:
            return None  # the field is bunched up behind the safety car: the gaps say nothing
        for tr in ctx.trends:
            side, idx, gap, slope = tr["side"], tr["car_index"], tr.get("gap_s"), tr.get("slope")
            if idx is None or gap is None or slope is None or tr.get("laps", 0) < 3:
                continue
            closing = -float(slope)
            if closing < TREND_MIN_CLOSING:
                continue
            last = self._trend.get((side, idx))
            if last is not None and lap - last < GAP_REPEAT_LAPS:
                continue
            if side == "ahead":
                to1 = tr.get("laps_to_1s")
                if to1 is None or to1 > TREND_AHEAD_MAX_LAPS:
                    continue
                text = f"Catching the car ahead: {_num(gap)} s, about {_num(closing)} s a lap."
            else:
                if gap >= TREND_BEHIND_MAX_GAP_S:
                    continue
                text = f"Car behind closing: {_num(gap)} s, {_num(closing)} s a lap."
            data = {"side": side, "car_index": idx, "gap_s": round(gap, 2), "closing_s_per_lap": round(closing, 2)}
            return self._make("gap_trend", ctx, "detailed", "low", text, 30.0, audience="experienced", data=data)
        return None

    def _t_weather(self, ctx: CallContext) -> StrategyCall | None:
        nc = ctx.next_weather
        if nc is None or ctx.weather_now is None:
            return None
        to_rain = nc.get("weather") in _RAINY and ctx.weather_now not in _RAINY
        to_dry = nc.get("weather") not in _RAINY and ctx.weather_now in _RAINY
        if not (to_rain or to_dry):
            return None
        if self._weather is not None and ctx.t - self._weather[0] < WEATHER_REPEAT_S:
            return None
        mins = int(nc["in_min"])
        laps = nc.get("in_laps")
        if laps is not None and ctx.laps_remaining is not None and laps >= ctx.laps_remaining:
            return None  # the change comes after the chequered flag: nothing to act on
        data = {"in_min": mins, "weather": nc.get("weather"), "in_laps": laps, "rain_pct": nc.get("rain_pct")}
        if to_rain:
            what = "Heavy rain" if nc.get("weather") in ("heavy_rain", "storm") else "Rain"
            text = f"{what} forecast in about {mins} minutes" + (f", around {laps} laps." if laps else ".")
            simple = f"{what} is coming in about {mins} minutes."
            return self._make("weather", ctx, "alert", "normal", text, 120.0, data=data, simple=simple)
        text = f"Forecast says dry in about {mins} minutes."
        simple = f"The rain should stop in about {mins} minutes."
        return self._make("weather", ctx, "normal", "normal", text, 120.0, data=data, simple=simple)

    def _t_crossover(self, ctx: CallContext) -> StrategyCall | None:
        cx = ctx.crossover
        if cx is None:
            return None
        compound = str(cx["compound"])
        last = self._crossover.get(compound)
        if last is not None and (ctx.lap or 0) - last < CROSSOVER_REPEAT_LAPS:
            return None
        gain = float(cx["gain_s"])
        if compound in _WET_NAME:
            text = f"Game's tyre model now has {_WET_NAME[compound]} {_num(gain)} s a lap faster than your slicks."
            simple = (
                f"The game says {_WET_SIMPLE[compound]} are now {_num(gain)} seconds a lap faster than your dry tyres."
            )
            level = "alert"
        else:
            text = f"Game's tyre model now has slicks {_num(gain)} s a lap faster than your wet tyres."
            simple = f"The game says dry tyres are now {_num(gain)} seconds a lap faster than your rain tyres."
            level = "normal"
        data = {"compound": compound, "gain_s": gain}
        return self._make("crossover", ctx, level, "normal", text, 60.0, data=data, simple=simple)
