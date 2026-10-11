"""Short, engineer-style radio phrasing for the instant (no-LLM) answers.

The fact sheet is written for completeness ("wear FL 13.3%, FR 14.7%, RL 9.8%, RR 10.5%; wear rate per lap ..."),
which is far too long over the radio. These templates pick the one or two numbers a race engineer would say,
using ONLY values from the facts' structured data, so answers stay grounded by construction.
"""

from __future__ import annotations

from typing import Any

from pitwall.ai.facts import LAST_LAP_PREFIX, FactSheet, fmt_lap

WHEEL_NAMES = ("front left", "front right", "rear left", "rear right")
COMPOUND_PLURAL = {"soft": "Softs", "medium": "Mediums", "hard": "Hards", "inter": "Inters", "wet": "Wets"}


def _fact(sheet: FactSheet, topic: str, key: str) -> dict[str, Any] | None:
    for f in sheet.facts:
        if f.topic == topic and key in f.data:
            return f.data
    return None


def _num(v: float, nd: int = 1) -> str:
    s = f"{v:.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def tyres(sheet: FactSheet) -> str | None:
    d = _fact(sheet, "tyres", "wear")
    if not d or not d.get("wear"):
        return None
    wear = list(d["wear"])
    i = max(range(4), key=lambda k: wear[k])
    compound = COMPOUND_PLURAL.get(str(d.get("compound") or ""), "Tyres")
    age = d.get("age_laps")
    head = f"{compound}, {age} laps old." if age is not None else f"{compound}."
    msg = f"{head} {WHEEL_NAMES[i].capitalize()} is the most worn at {_num(wear[i])} percent"
    rate = d.get("rate")
    if rate and rate[i] and rate[i] > 0:
        msg += f", about {_num(rate[i])} a lap"
    msg += "."
    if d.get("laps_to_limit") is not None:
        msg += f" Around {_num(d['laps_to_limit'], 0)} laps until {_num(d.get('limit_pct') or 70, 0)} percent."
    return msg


def fuel(sheet: FactSheet) -> str | None:
    d = _fact(sheet, "fuel", "per_lap_kg")
    if not d or d.get("per_lap_kg") is None:
        return None
    msg = f"Using {_num(d['per_lap_kg'])} kilos a lap"
    if d.get("fuel_now_kg") is not None and d.get("laps_of_fuel") is not None:
        msg += f", {_num(d['fuel_now_kg'], 0)} in the tank, good for {_num(d['laps_of_fuel'], 0)} laps"
    msg += "."
    m = d.get("margin_laps")
    if m is not None:
        msg += f" We're {'plus' if m >= 0 else 'minus'} {_num(abs(m))} laps to the finish."
        if m < 0:
            msg += " We need to save fuel."
    return msg


def lap_times(sheet: FactSheet) -> str | None:
    best = next((f for f in sheet.facts if f.topic == "laps" and f.text.startswith("Best clean lap")), None)
    if best is None:
        return None
    msg = f"Best lap is a {fmt_lap(round(best.data['lap_time_s'] * 1000))}, lap {best.data['lap']}."
    theo = next((f for f in sheet.facts if f.topic == "laps" and f.text.startswith("Theoretical")), None)
    if theo is not None and theo.data.get("gap_s", 0) > 0.05:
        msg += f" Your best sectors add up to {_num(theo.data['gap_s'], 2)} quicker."
    return msg


def last_lap(sheet: FactSheet) -> str | None:
    """The lap just driven (not the best one): its time, whether it was clean, and the gap to the best clean lap."""
    f = next((f for f in sheet.facts if f.topic == "laps" and f.text.startswith(LAST_LAP_PREFIX)), None)
    if f is None:
        return None
    d = f.data
    msg = f"Last lap, lap {d['lap']}, a {fmt_lap(round(d['lap_time_s'] * 1000))}"
    msg += "." if d.get("clean") else ", not clean."
    gap = d.get("gap_to_best_s")
    if gap is None:
        if d.get("clean") and "best clean lap this session" in f.text:
            msg += " That's your best lap."
    elif gap >= 0.0005:
        msg += f" {_num(gap, 3)} off your best, lap {d['best_lap']}."
    elif gap <= -0.0005:
        msg += f" {_num(-gap, 3)} quicker than your best clean lap, lap {d['best_lap']}."
    return msg


PHRASERS = {"tyres": tyres, "fuel": fuel, "lap_times": lap_times, "last_lap": last_lap}


def radio_answer(intent: str, sheet: FactSheet) -> str | None:
    # race strategy (pitwall.strategy): live strategy facts first; None without them (other games, post-session)
    from pitwall.strategy.phrasing import strategy_radio_answer

    short = strategy_radio_answer(intent, sheet)
    if short is not None:
        return short
    fn = PHRASERS.get(intent)
    return fn(sheet) if fn else None
