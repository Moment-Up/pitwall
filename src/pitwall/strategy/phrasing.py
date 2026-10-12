"""Instant (no-LLM) radio answers from the strategy facts (``strategy.facts``): the one or two things a race engineer
would say, built only from the facts' own sentences and numbers, so they are grounded by construction.

``strategy_radio_answer`` returns None when the sheet has no strategy facts (no live race / practice view): the
caller then uses the per-lap phrasing of ``ai.radio_phrasing``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pitwall.strategy.facts import SRC

if TYPE_CHECKING:
    from pitwall.ai.facts import Fact, FactSheet

INTENTS = frozenset({"strategy", "gaps", "fuel", "tyres", "weather", "safety_car"})


def _facts(sheet: FactSheet) -> dict[str, Fact]:
    out: dict[str, Fact] = {}
    for f in sheet.facts:
        if f.data.get("src") == SRC and isinstance(f.data.get("kind"), str):
            out.setdefault(str(f.data["kind"]), f)
    return out


def _say(*fs: Fact | None) -> str | None:
    parts = [f.plain for f in fs if f is not None and f.say is not None]
    return " ".join(parts) if parts else None


def strategy_position_answer(sheet: FactSheet) -> str | None:
    """ "What position am I?": the race position first, then the gap to the car ahead (None without strategy facts)."""
    k = _facts(sheet)
    pos = k.get("position")
    if pos is None:
        return None
    return _say(pos, k.get("gap_ahead"))


def strategy_radio_answer(intent: str, sheet: FactSheet) -> str | None:
    if intent not in INTENTS:
        return None
    k = _facts(sheet)
    if not k:
        return None
    if intent == "strategy":
        if "practice" in k:
            return _say(k["practice"], k.get("tyres"))
        if "sc_box" in k:
            return _say(k["sc_box"])
        first = k.get("window") or k.get("no_stop") or k.get("window_unknown")
        cut = k.get("undercut_ahead")
        threat = k.get("undercut_threat")
        extra: Any = cut if cut is not None and cut.data.get("status") in ("likely", "marginal") else None
        if extra is None and threat is not None and threat.data.get("status") in ("likely", "marginal"):
            extra = threat
        return _say(first, extra or k.get("neighbour_stop"))
    if intent == "gaps":
        pos = k.get("position")
        # leading: no car ahead, so say so first ("P1, leading.") instead of answering only about the car behind
        lead = pos if pos is not None and pos.data.get("position") == 1 and "gap_ahead" not in k else None
        ans = _say(lead, k.get("gap_ahead"), k.get("gap_behind"))
        return ans or _say(pos)
    if intent == "fuel":
        fuel = k.get("fuel")
        if fuel is None:
            return None
        m = fuel.data.get("margin_laps")
        if isinstance(m, int | float) and m < 0 and "lift_coast" in k:
            return _say(fuel, k["lift_coast"])
        return _say(fuel)
    if intent == "tyres":
        return _say(k.get("tyres"), k.get("game_tyres"))
    if intent == "weather":
        return _say(k.get("weather"), k.get("crossover"))
    if intent == "safety_car":  # the safety car's own intent (plan 4.1): the box-or-stay call while one is out
        return _say(k.get("sc_box"))
    return None
