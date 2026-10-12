"""Instant (no-LLM) radio answers from the car health facts (``carhealth.facts``): built only from the facts' own
sentences, so they are grounded by construction. A beginner (session fact ``skill_level``) hears ``data["simple"]``.

* ``car_health`` ("how are my brakes?", "how's the car?"): the tyre temperatures, then brakes / engine - the one asked
  about alone when the question names it (brakes before F1's first full lap: that a lap is needed, not the tyres).
* ``attack`` / ``defend``: the racecraft fact for that side, else why there is none.
* ``tyres`` (wrapped, ``tyres_answer``): a question about temperatures ("are my tyres cold?") is answered with the
  temperature sentence; any other tyre question keeps its answer (race strategy or the per-lap one), followed by the
  temperature sentence only when the tyres are cold or one is hot.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from pitwall.carhealth.facts import SRC

if TYPE_CHECKING:
    from pitwall.ai.facts import Fact, FactSheet

INTENTS = frozenset({"car_health", "attack", "defend"})
_TEMP_Q = re.compile(r"\b(?:temp\w*|cold|hot|warm\w*|heat\w*|overheat\w*)\b", re.I)
_BRAKE_Q = re.compile(r"\bbrak\w*", re.I)
_ENGINE_Q = re.compile(r"\bengine\b", re.I)
MAX_SAID = 160
# F1 sends brake temperatures (the engine fact is there), but the brakes are judged per lap: before the first full lap
# a brake question gets this, not the tyres
NO_BRAKE_LAP_YET = "I need a full lap of brake temperatures first."


def _facts(sheet: FactSheet) -> dict[str, Fact]:
    out: dict[str, Fact] = {}
    for f in sheet.facts:
        if f.data.get("src") == SRC and isinstance(f.data.get("kind"), str):
            out.setdefault(str(f.data["kind"]), f)
    return out


def _beginner(sheet: FactSheet) -> bool:
    return any(f.topic == "session" and f.data.get("skill_level") == "beginner" for f in sheet.facts)


def _said(f: Fact, simple: bool) -> str:
    s = f.data.get("simple")
    return str(s) if simple and isinstance(s, str) and s else f.plain


def _join(fs: list[Fact | None], simple: bool) -> str | None:
    chosen = [f for f in fs if f is not None and (f.say is not None or f.data.get("simple"))]
    if not chosen:
        return None
    if simple:
        return _said(chosen[0], True)  # one idea per message
    out = _said(chosen[0], False)
    for f in chosen[1:]:
        nxt = _said(f, False)
        if len(out) + 1 + len(nxt) > MAX_SAID:
            break
        out += " " + nxt
    return out


def health_radio_answer(intent: str, sheet: FactSheet, question: str | None = None) -> str | None:
    if intent not in INTENTS:
        return None
    k = _facts(sheet)
    if not k:
        return None
    simple = _beginner(sheet)
    if intent == "car_health":
        q = question or ""
        brakes, engine, tyres = k.get("brakes"), k.get("engine"), k.get("tyre_temps")
        if _BRAKE_Q.search(q):
            if brakes is not None:
                return _join([brakes], simple)
            if engine is not None:
                return NO_BRAKE_LAP_YET
        if _ENGINE_Q.search(q) and engine is not None:
            return _join([engine], simple)
        return _join([tyres, brakes, engine], simple)
    side = "ahead" if intent == "attack" else "behind"
    f = k.get(f"racecraft_{side}") or k.get(f"racecraft_{side}_unknown") or k.get("racecraft_unknown")
    return None if f is None else _said(f, simple)


def tyres_answer(sheet: FactSheet, question: str | None, base: Callable[[FactSheet], str | None] | None) -> str | None:
    """The tyres intent with the temperature sentence (see the module docstring)."""
    k = _facts(sheet)
    temps = k.get("tyre_temps")
    said = base(sheet) if base is not None else None
    if temps is None:
        return said
    simple = _beginner(sheet)
    if question and _TEMP_Q.search(question):
        return _said(temps, simple)
    notable = temps.data.get("state") == "cold" or temps.data.get("hot_over_c") is not None
    if not notable:
        return said
    if said is None:
        return _said(temps, simple)
    if simple:
        return _said(temps, True)  # one idea: the cold tyres matter now
    return f"{said} {_said(temps, False)}"
