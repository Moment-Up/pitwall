"""Proactive car health calls: when the engineer speaks up about the car, and what it says (deterministic templates).

A ``HealthCall`` has the same dict shape as ``strategy.calls.StrategyCall.to_dict()`` (id ``hc-<topic>-<lap>-<n>``), so
the radio treats both alike (``carhealth.radio``: existing message kinds, the scheduler's speak windows and budget).

| Topic | When | Level / priority / TTL |
|---|---|---|
| ``tyres_cold`` | the cold-tyre rule turns cold (pit exit, safety car / VSC end) | normal / high / 40 s, once per arm |
| ``tyres_warm`` | cold -> warm again | detailed / low / 30 s, once per arm |
| ``wear_high`` | most-worn tyre at ``WEAR_CALL_PCT``, outside F1 races | normal / normal / 90 s, once per stint |
| ``fuel_low`` | tank-level fuel (Forza) ``low`` | normal / normal / 120 s; again after 3 laps or 0.5 lap worse |
| ``fuel_critical`` | ``critical`` | alert / high / 60 s, bypasses quiet; again after 2 laps |
| ``slip_lockups`` | >= ``SLIP_CALL_LOCKUPS`` lock-ups in a lap (ABS off) | detailed (or normal) / low / 45 s, 3 laps |
| ``slip_wheelspin`` | >= ``SLIP_CALL_SPINS`` spoken-eligible spins (TC off / medium) | as lock-ups |

Rules: nothing on a formation lap, under a red flag, in the pit lane or on a race's final lap; nothing on lap 1 but
``tyres_cold``; at most one ``normal`` and one ``detailed`` health call per lap (alerts: their cooldowns); in F1 races
no wear or fuel calls (race strategy owns them); the household settings switch topics off (``carhealth.settings``).
Every text is at most ``MAX_TEXT`` characters, built only from numbers in ``data``, British English, and never tells
the driver to brake later (``tests/unit/test_carhealth_calls.py`` lints every template). ``text_simple`` is the same
call in plain words, one idea per message, for a driver whose profile asks for simple wording.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pitwall.carhealth import thresholds as T
from pitwall.carhealth.settings import DEFAULTS, HealthSettings
from pitwall.carhealth.slip import SlipCounter, SlipEvent
from pitwall.carhealth.tyres import REASON_SC_END, TyreEvent

NORMAL_PER_LAP = 1
DETAILED_PER_LAP = 1
WHEEL_WORDS = ("front left", "front right", "rear left", "rear right")
_NUM_WORDS = (
    "no",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
)
_ids = itertools.count(1)


def count_word(n: int) -> str:
    return _NUM_WORDS[n] if 0 <= n < len(_NUM_WORDS) else str(n)


def _num(v: float, nd: int = 1) -> str:
    s = f"{v:.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


@dataclass(slots=True, frozen=True)
class HealthCall:
    id: str
    topic: str
    level: str  # "alert" | "normal" | "detailed"
    priority: str  # "high" | "normal" | "low"
    text: str
    lap: int | None
    ttl_s: float
    bypass_quiet: bool
    audience: str
    data: dict[str, Any]
    t_unix: float
    text_simple: str | None = None

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
    lap: int | None
    blocked: str | None = None  # "formation lap" | "red flag" | None
    in_pit: bool = False
    final_lap: bool = False  # a race's final lap: nothing to act on
    f1_race: bool = False  # race strategy owns wear and fuel there


@dataclass(slots=True)
class HealthCallPlanner:
    clock: Callable[[], float] = time.time
    settings: HealthSettings = DEFAULTS
    _spent: dict[tuple[int, str], int] = field(default_factory=dict)
    _wear_stint: int | None = None  # the stint a wear call was made in
    _fuel_low: tuple[int, float] | None = None  # (lap, laps of fuel) of the last fuel_low call
    _fuel_crit: int | None = None
    _slip: dict[str, int] = field(default_factory=dict)  # topic -> lap of the last call

    # ------------------------------------------------------------------ gate
    def _allowed(self, ctx: CallContext, topic: str, level: str) -> bool:
        if ctx.blocked is not None or ctx.in_pit or ctx.lap is None or ctx.final_lap:
            return False
        if ctx.lap <= 1 and topic != "tyres_cold":
            return False
        if level in ("normal", "detailed"):
            cap = NORMAL_PER_LAP if level == "normal" else DETAILED_PER_LAP
            if self._spent.get((ctx.lap, level), 0) >= cap:
                return False
        return True

    def _spend(self, ctx: CallContext, level: str) -> None:
        lap = ctx.lap or 0
        if level in ("normal", "detailed"):
            self._spent[(lap, level)] = self._spent.get((lap, level), 0) + 1
        for k in [k for k in self._spent if k[0] < lap - 2]:
            del self._spent[k]

    def _make(
        self,
        ctx: CallContext,
        topic: str,
        level: str,
        priority: str,
        text: str,
        simple: str,
        ttl_s: float,
        data: dict[str, Any],
        *,
        bypass: bool = False,
    ) -> HealthCall:
        if len(text) > T.MAX_TEXT:
            text = text[: T.MAX_TEXT - 1].rstrip(" ,:;") + "."
        if len(simple) > T.MAX_TEXT:
            simple = simple[: T.MAX_TEXT - 1].rstrip(" ,:;") + "."
        self._spend(ctx, level)
        return HealthCall(
            id=f"hc-{topic}-{ctx.lap}-{next(_ids)}",
            topic=topic,
            level=level,
            priority=priority,
            text=text,
            lap=ctx.lap,
            ttl_s=ttl_s,
            bypass_quiet=bypass,
            audience="all",
            data=data,
            t_unix=self.clock(),
            text_simple=simple,
        )

    # ------------------------------------------------------------------ tyres
    def tyres(self, ctx: CallContext, ev: TyreEvent) -> HealthCall | None:
        if not self.settings.tyre_calls:
            return None
        if ev.topic == "tyres_cold":
            if not self._allowed(ctx, "tyres_cold", "normal"):
                return None
            if ev.reason == REASON_SC_END:
                text = "Tyres have cooled behind the safety car: careful on the restart."
            else:
                text = "New tyres are cold: give them a lap or two before you push."
            simple = "Your tyres are cold, so there's less grip. Take the first corners gently."
            data = {**ev.data, "reason": ev.reason}
            return self._make(ctx, "tyres_cold", "normal", "high", text, simple, 40.0, data)
        if ev.topic == "tyres_warm":
            if not self._allowed(ctx, "tyres_warm", "detailed"):
                return None
            data = {**ev.data, "reason": ev.reason}
            return self._make(
                ctx,
                "tyres_warm",
                "detailed",
                "low",
                "Tyres are up to temperature now.",
                "Your tyres are warm now.",
                30.0,
                data,
            )
        return None

    def wear(self, ctx: CallContext, wear: tuple[float, ...] | None, stint: int) -> HealthCall | None:
        """The most-worn tyre at ``WEAR_CALL_PCT``, once per stint, never in an F1 race (race strategy owns wear)."""
        if not self.settings.wear_calls or ctx.f1_race or wear is None or self._wear_stint == stint:
            return None
        k = max(range(4), key=lambda i: wear[i])
        pct = wear[k]
        if pct < T.WEAR_CALL_PCT or not self._allowed(ctx, "wear_high", "normal"):
            return None
        self._wear_stint = stint
        w = WHEEL_WORDS[k]
        p = _num(pct, 0)
        data = {"wheel": ("FL", "FR", "RL", "RR")[k], "wear_pct": round(pct, 1), "limit_pct": T.WEAR_CALL_PCT}
        return self._make(
            ctx,
            "wear_high",
            "normal",
            "normal",
            f"{_cap(w)} is at {p} percent wear.",
            f"Your {w} tyre is getting worn: {p} percent.",
            90.0,
            data,
        )

    # ------------------------------------------------------------------ fuel
    def fuel(self, ctx: CallContext, status: str, laps: float | None, per_lap_frac: float | None) -> HealthCall | None:
        """Tank-level fuel (Forza; GT7 once enabled), judged at the line. Never in an F1 race."""
        if not self.settings.fuel_calls or ctx.f1_race or laps is None:
            return None
        lap = ctx.lap or 0
        if status == "critical":
            if self._fuel_crit is not None and lap - self._fuel_crit < T.FUEL_CRITICAL_REPEAT_LAPS:
                return None
            if not self._allowed(ctx, "fuel_critical", "alert"):
                return None
            self._fuel_crit = lap
            if laps < 0.75:
                text, simple = "Fuel is almost gone: less than a lap left.", "Almost out of fuel: less than a lap left."
            else:
                text, simple = "Fuel for about one more lap.", "Almost out of fuel: about one lap left."
            crit = {"laps_of_fuel": round(laps, 1), "status": status}
            return self._make(ctx, "fuel_critical", "alert", "high", text, simple, 60.0, crit, bypass=True)
        if status != "low":
            return None
        last = self._fuel_low
        if last is not None and not (
            lap - last[0] >= T.FUEL_LOW_REPEAT_LAPS or laps <= last[1] - T.FUEL_LOW_WORSEN_LAPS
        ):
            return None
        if not self._allowed(ctx, "fuel_low", "normal"):
            return None
        self._fuel_low = (lap, laps)
        n = max(1, round(laps))
        unit = "lap" if n == 1 else "laps"
        text = f"Fuel for about {n} more {unit}"
        data: dict[str, Any] = {"laps_of_fuel": round(laps, 1), "laps_said": n, "status": status}
        if per_lap_frac is not None and per_lap_frac > 0:
            pct = per_lap_frac * 100
            text += f", at {_num(pct, 0 if pct >= 10 else 1)} percent a lap"
            data["per_lap_pct"] = round(pct, 1)
        return self._make(
            ctx, "fuel_low", "normal", "normal", text + ".", f"You've got fuel for about {n} more {unit}.", 120.0, data
        )

    # ------------------------------------------------------------------ slip
    def slip(self, ctx: CallContext, last_lap: dict[str, Any] | None, events: list[SlipEvent]) -> list[HealthCall]:
        """Lock-ups / wheelspin of the lap just finished: never on lap 1, a pit lap or a flashback lap."""
        mode = self.settings.slip_calls
        if mode == "off" or last_lap is None or last_lap.get("pit") or last_lap.get("flashback"):
            return []
        if int(last_lap.get("lap") or 0) <= 1:
            return []
        level = "normal" if mode == "normal" else "detailed"
        lap = ctx.lap or 0
        out: list[HealthCall] = []
        n_lock = int(last_lap.get("lockups") or 0)
        last = self._slip.get("slip_lockups")
        due = n_lock >= T.SLIP_CALL_LOCKUPS and (last is None or lap - last >= T.SLIP_COOLDOWN_LAPS)
        if due and self._allowed(ctx, "slip_lockups", level):
            top = SlipCounter.top_corner(events, "lockup")
            c = _cap(count_word(n_lock))
            data: dict[str, Any] = {"lockups": n_lock, "lap": last_lap.get("lap")}
            if top is not None:
                where = "all" if top[2] == n_lock else count_word(top[2])
                text = f"{c} lock-ups that lap, {where} into {top[1]}."
                simple = (
                    f"The wheels locked {count_word(n_lock)} times, mostly into {top[1]}. "
                    "Squeeze the brake more gently there."
                )
                data.update(corner=top[0], corner_text=top[1], at_corner=top[2])
            else:
                text = f"{c} lock-ups that lap."
                simple = f"The wheels locked {count_word(n_lock)} times that lap. Squeeze the brake more gently."
            self._slip["slip_lockups"] = lap
            out.append(self._make(ctx, "slip_lockups", level, "low", text, simple, 45.0, data))
        n_spin = int(last_lap.get("wheelspin_spoken") or 0)
        last = self._slip.get("slip_wheelspin")
        due = n_spin >= T.SLIP_CALL_SPINS and (last is None or lap - last >= T.SLIP_COOLDOWN_LAPS)
        if due and self._allowed(ctx, "slip_wheelspin", level):
            top = SlipCounter.top_corner(events, "wheelspin", spoken_only=True)
            c = count_word(n_spin)
            data = {"wheelspin": n_spin, "lap": last_lap.get("lap")}
            if top is not None:
                text = f"Wheelspin {c} times that lap, most out of {top[1]}."
                simple = f"The rear wheels spun {c} times, mostly out of {top[1]}. Ease onto the throttle there."
                data.update(corner=top[0], corner_text=top[1], at_corner=top[2])
            else:
                text = f"Wheelspin {c} times that lap."
                simple = f"The rear wheels spun {c} times that lap. Ease onto the throttle."
            self._slip["slip_wheelspin"] = lap
            out.append(self._make(ctx, "slip_wheelspin", level, "low", text, simple, 45.0, data))
        return out


# Every template the planner can say (the wording lint in the tests walks these with sample values).
def sample_calls() -> list[HealthCall]:
    """One call per template and branch, for the wording lint (``tests/unit/test_carhealth_calls.py``)."""
    out: list[HealthCall] = []
    p = HealthCallPlanner(clock=lambda: 0.0)
    for k, ev in enumerate(
        (
            TyreEvent("tyres_cold", "pit_exit", 2, {}),
            TyreEvent("tyres_cold", "sc_end", 2, {}),
            TyreEvent("tyres_warm", "pit_exit", 2, {}),
        )
    ):
        c = p.tyres(CallContext(lap=10 + k), ev)
        if c is not None:
            out.append(c)
    c = p.wear(CallContext(lap=20), (72.0, 60.0, 50.0, 50.0), 1)
    if c is not None:
        out.append(c)
    for k, (st, laps) in enumerate((("low", 2.6), ("critical", 1.1), ("critical", 0.5))):
        q = HealthCallPlanner(clock=lambda: 0.0)
        c = q.fuel(CallContext(lap=30 + k), st, laps, 0.041)
        if c is not None:
            out.append(c)
    corner = ("T1", "Turn 1")
    ev_l = [SlipEvent("lockup", 100.0, 0.3, ("FL",), 1, corner)] * 3
    ev_s = [SlipEvent("wheelspin", 900.0, 0.4, ("RR",), 1, ("T9", "Turn 9"))] * 4
    lock_lap = {"lap": 3, "lockups": 3, "wheelspin": 0, "wheelspin_spoken": 0}
    spin_lap = {"lap": 3, "lockups": 0, "wheelspin": 4, "wheelspin_spoken": 4}
    for mode in ("detailed", "normal"):
        for lap, events in ((lock_lap, ev_l), (lock_lap, []), (spin_lap, ev_s), (spin_lap, [])):
            q = HealthCallPlanner(clock=lambda: 0.0, settings=HealthSettings(slip_calls=mode))
            out += q.slip(CallContext(lap=4), lap, events)
    return out
