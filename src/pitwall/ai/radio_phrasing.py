"""Short, engineer-style radio phrasing for the instant (no-LLM) answers.

The fact sheet is written for completeness ("wear FL 13.3%, FR 14.7%, RL 9.8%, RR 10.5%; wear rate per lap ..."),
which is far too long over the radio. These templates pick the one or two numbers a race engineer would say,
using ONLY values from the facts' structured data, so answers stay grounded by construction.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from pitwall.ai.facts import (
    AI_LEVEL_PREFIX,
    AI_PACE_PREFIX,
    DRS_PREFIX,
    ERS_CLASS_PREFIX,
    FLAGS_PREFIX,
    LAST_LAP_PREFIX,
    RULES_PREFIX,
    FactSheet,
    fmt_lap,
)

WHEEL_NAMES = ("front left", "front right", "rear left", "rear right")
COMPOUND_PLURAL = {
    "super_soft": "Super softs",  # F2 cars
    "soft": "Softs",
    "medium": "Mediums",
    "hard": "Hards",
    "inter": "Inters",
    "wet": "Wets",
}


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


def capability(group: str) -> Callable[[FactSheet], str | None]:
    """What the game does not send for this question group (the sheet's ``game`` fact, already one short sentence)."""

    def phrase(sheet: FactSheet) -> str | None:
        f = next((f for f in sheet.facts if f.topic == "game" and f.data.get("group") == group), None)
        return None if f is None else f.plain

    return phrase


def flags_now(sheet: FactSheet) -> str | None:
    """The safety car and yellow flags now (the sheet's live ``flags`` fact, already short)."""
    f = next((f for f in sheet.facts if f.topic == "flags" and f.text.startswith(FLAGS_PREFIX)), None)
    return None if f is None else f.plain


def class_ers(sheet: FactSheet) -> str | None:
    """A car class without ERS (F2): the sheet's class fact, already one short sentence."""
    f = next((f for f in sheet.facts if f.topic == "ers" and f.text.startswith(ERS_CLASS_PREFIX)), None)
    return None if f is None else f.plain


def drs_now(sheet: FactSheet) -> str | None:
    """DRS now (allowed, or in how many metres), then the car ahead when it is in DRS range."""
    now = next((f for f in sheet.facts if f.topic == "drs" and f.text.startswith(DRS_PREFIX)), None)
    ahead = next((f for f in sheet.facts if f.topic == "gaps" and "DRS range" in f.text), None)
    parts = [f.plain for f in (now, ahead) if f is not None]
    return " ".join(parts) if parts else None


def stop_rules(sheet: FactSheet) -> str | None:
    """The race's stop rules over the radio: under a safety car its box call first, then not known (the game doesn't
    send them), then the tyre statement. Never "no" (the F2 note stays for Review). None outside a race (no rules
    fact): the engineer's own short answer then."""
    from pitwall.ai.engineer import sc_box_fact, tyre_statement  # the engineer imports this module: keep it lazy

    rules = next((f for f in sheet.facts if f.topic == "rules" and f.text.startswith(RULES_PREFIX)), None)
    if rules is None:
        return None
    box = sc_box_fact(sheet.facts)
    if box is not None:
        return f"{box.plain} {rules.plain}"
    tyre = tyre_statement(sheet.facts)
    return rules.plain if tyre is None else f"{rules.plain} {tyre.plain}"


def _either(*fns: Callable[[FactSheet], str | None]) -> Callable[[FactSheet], str | None]:
    """The first phrasing that has something to say."""

    def phrase(sheet: FactSheet) -> str | None:
        return next((said for fn in fns if (said := fn(sheet)) is not None), None)

    return phrase


def ai_pace(sheet: FactSheet) -> str | None:
    """Against the AI: the gap to the typical AI car and the position on best laps (or why there is none)."""
    f = next((f for f in sheet.facts if f.topic == "ai" and f.text.startswith(AI_PACE_PREFIX)), None)
    if f is None:
        return None
    d = f.data
    if d.get("status") == "ok" and d.get("gap_s") is not None:
        gap = float(d["gap_s"])
        if abs(gap) < 0.05:
            versus = "level with the typical AI car"
        else:
            versus = f"{abs(gap):.1f} {'off' if gap > 0 else 'up on'} the typical AI car"
        return (
            f"Against the AI at {d['ai_difficulty']}: {versus}, position {d['rank']} of {d['field_size']} on best laps."
        )
    if d.get("status") == "no_driver_lap" and d.get("ai_ref_s") is not None:
        ref = fmt_lap(round(float(d["ai_ref_s"]) * 1000))
        return f"Typical AI best at {d['ai_difficulty']} is a {ref}. No clean lap yet to compare."
    return f.plain


def ai_level(sheet: FactSheet) -> str | None:
    """The suggested AI level here, or which way to move it when there is no level yet."""
    f = next((f for f in sheet.facts if f.topic == "ai" and f.text.startswith(AI_LEVEL_PREFIX)), None)
    if f is None:
        return ai_pace(sheet)
    d = f.data
    if d.get("level") is not None:
        bound = {"at_least": " or higher", "at_most": " or lower"}.get(str(d.get("bound")), "")
        msg = f"Try AI {d['level']}{bound} here."
        return msg + " Rough estimate." if d.get("confidence") == "low" else msg
    level, g = d.get("latest_level"), d.get("latest_gap_pct")
    if d.get("direction") == "about_right":
        return f"AI {level} looks about right here."
    if not isinstance(g, int | float):
        return f.plain
    pace = "slower" if g > 0 else "faster"
    move = "lower" if d.get("direction") == "lower" else "higher"
    nxt = d.get("next_level")
    try_next = f"Try {nxt} or {move} next time" if isinstance(nxt, int) else f"Try a {move} level"
    return (
        f"Not enough levels yet. At {level} you're {abs(g):.1f} percent {pace} than the AI here. "
        f"{try_next}, then I can suggest one."
    )


def _strategy_first(
    intent: str, fallback: Callable[[FactSheet], str | None] | None
) -> Callable[[FactSheet], str | None]:
    """Race strategy's instant answer (``strategy.phrasing``, from a live race / practice StrategyView) when the sheet
    has strategy facts, else ``fallback`` (the per-lap phrasing, or what the game never sends)."""

    def phrase(sheet: FactSheet) -> str | None:
        from pitwall.strategy.phrasing import strategy_radio_answer  # strategy imports ai.facts: keep this lazy

        short = strategy_radio_answer(intent, sheet)
        if short is not None:
            return short
        return fallback(sheet) if fallback is not None else None

    return phrase


# One explicit table (plan 4.5): race strategy for the race questions (the safety car: strategy's box-or-stay call,
# else the flags now), then pace vs AI, then the game's capability sentence for data it never sends. An intent with
# no phrasing here (or a phrasing with nothing to say) is answered with ``engineer.deterministic_answer``.
PHRASERS: dict[str, Callable[[FactSheet], str | None]] = {
    "fuel": _strategy_first("fuel", fuel),
    "tyres": _strategy_first("tyres", tyres),
    "strategy": _strategy_first("strategy", None),
    "gaps": _strategy_first("gaps", capability("gaps")),
    "weather": _strategy_first("weather", capability("weather")),
    "safety_car": _strategy_first("safety_car", _either(flags_now, capability("safety_car"))),
    "flags": _either(flags_now, capability("flags")),
    "lap_times": lap_times,
    "last_lap": last_lap,
    "ai_pace": ai_pace,
    "ai_level": ai_level,
    "ers": _either(class_ers, capability("ers")),
    "drs": _either(drs_now, capability("drs")),
    "stop_rules": stop_rules,
    **{g: capability(g) for g in ("damage", "sectors")},
}


def radio_answer(intent: str, sheet: FactSheet, question: str | None = None) -> str | None:
    """The instant radio phrasing of ``intent``, else None. ``question``: a race position question ("what position
    am I?") is answered with the position first (``strategy.phrasing``)."""
    if intent == "gaps" and question is not None and _POSITION_Q.search(question):
        from pitwall.strategy.phrasing import strategy_position_answer  # strategy imports ai.facts: keep this lazy

        said = strategy_position_answer(sheet)
        if said is not None:
            return said
    fn = PHRASERS.get(intent)
    return fn(sheet) if fn else None


_POSITION_Q = re.compile(r"\b(?:position|place|p\d{1,2})\b", re.I)
