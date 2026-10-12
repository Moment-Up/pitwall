"""Instant (no-LLM) radio answers from the car health facts (``carhealth.facts``): built only from the facts' own
sentences, so they are grounded by construction. A beginner (session fact ``skill_level``) hears ``data["simple"]``.

* ``car_health``:
  - a question naming the brakes or the engine ("how are my brakes?", "is my engine overheating?") is answered about
    that part alone; when the game never sends it, with the game's own sentence ("GT7 doesn't send brake
    temperatures ..."), and in F1 before the first full lap with ``NO_BRAKE_LAP_YET`` - never with the tyres instead;
  - "are my tyres overheating?": a yes or a no about the tyres first;
  - "how's the car?": only what stands out (cold or hot tyres, brakes or engine hotter or cooler than usual), else
    "All normal: tyres, brakes and engine." (the parts already judged against this session's normal; "so far" while
    one is not yet); never a "need another lap" sentence after another fact (10-13 s at speed was too long).
* ``attack`` / ``defend``: the racecraft fact for that side, else why there is none.
* ``tyres`` (wrapped, ``tyres_answer``): "are my tyres cold?" / "... hot?" is answered yes or no against the warm laps;
  any other temperature question with the temperature sentence; any other tyre question keeps its answer (race strategy
  or the per-lap one), followed by the temperature sentence only when the tyres are cold or one is hot. A beginner
  hears the plain temperature sentence for a general tyre question ("are my tyres ok?"), not wear percentages.
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
_COLD_Q = re.compile(r"\bcold\b", re.I)
_HOT_Q = re.compile(r"\b(?:hot|overheat\w*|too warm)\b", re.I)
_TYRE_Q = re.compile(r"\b(?:tyres?|tires?)\b", re.I)
_BRAKE_Q = re.compile(r"\bbrak\w*", re.I)
_ENGINE_Q = re.compile(r"\bengine\b", re.I)
# a tyre question about the set, its wear or its age keeps the strategy / per-lap answer even for a beginner
_WEAR_Q = re.compile(r"\b(?:wear\w*|worn|laps?|last|old|age|deg\w*|compound|softs?|mediums?|hards?|change|new)\b", re.I)
MAX_SAID = 160
# F1 sends brake temperatures (the engine fact is there), but the brakes are judged per lap: before the first full lap
# a brake question gets this, not the tyres
NO_BRAKE_LAP_YET = "I need a full lap of brake temperatures first."
NO_ENGINE_YET = "No engine temperature from the car yet."
_PARTS = (("tyre_temps", "tyres"), ("brakes", "brakes"), ("engine", "engine"))


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


def _game_sentence(sheet: FactSheet) -> str | None:
    """What this game never sends among the car health temperatures (the sheet's ``game`` fact for the intent)."""
    f = next((f for f in sheet.facts if f.topic == "game" and f.data.get("group") == "car_health"), None)
    return None if f is None else f.plain


def _standing_out(kind: str, f: Fact) -> bool | None:
    """True: worth saying on its own (cold / hot tyres, brakes or engine away from their normal); False: normal for this
    session; None: not judged yet (no baseline)."""
    d = f.data
    if kind == "tyre_temps":
        if d.get("state") == "cold" or d.get("hot_over_c") is not None:
            return True
        return False if d.get("baseline_c") is not None and d.get("state") == "ok" else None
    word = d.get("word")
    if word in ("hotter", "cooler"):
        return True
    return False if word in ("normal", "steady") else None


def _words(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _tyre_yes_no(temps: Fact, question: str, simple: bool) -> str | None:
    """ "Are my tyres cold?" / "... hot?" / "... overheating?": a yes or a no against the warm laps, None when there is
    no normal to judge against yet."""
    d = temps.data
    key = "cold" if _COLD_Q.search(question) else "hot" if _HOT_Q.search(question) else None
    if key is None:
        return None
    for answer in (f"yes_{key}", f"no_{key}"):
        said = d.get(f"{answer}_simple" if simple else answer)
        if isinstance(said, str) and said:
            return said
    return None


def _car(sheet: FactSheet, k: dict[str, Fact], question: str, simple: bool) -> str | None:
    brakes, engine, tyres = k.get("brakes"), k.get("engine"), k.get("tyre_temps")
    if _BRAKE_Q.search(question):
        if brakes is not None:
            return _said(brakes, simple)
        return _game_sentence(sheet) or (NO_BRAKE_LAP_YET if engine is not None else None)
    if _ENGINE_Q.search(question):
        if engine is not None:
            return _said(engine, simple)
        return _game_sentence(sheet) or (NO_ENGINE_YET if tyres is not None or brakes is not None else None)
    if tyres is not None and _TYRE_Q.search(question):
        said = _tyre_yes_no(tyres, question, simple)
        if said is not None:
            return said
    parts = [(name, f, _standing_out(kind, f)) for kind, name in _PARTS if (f := k.get(kind)) is not None]
    if not parts:
        return None
    notable = [f for _, f, s in parts if s is True]
    if notable:
        return _join(list(notable), simple)
    normal = [name for name, _, s in parts if s is False]
    if not normal:
        return _said(parts[0][1], simple)  # nothing judged yet: the first part's own sentence, nothing after it
    so_far = len(normal) < len(parts)
    lead = "No. " if _HOT_Q.search(question) else ""
    if simple:
        return lead + ("The car looks fine so far." if so_far else "The car's fine.")
    return f"{lead}All normal{' so far' if so_far else ''}: {_words(normal)}."


def health_radio_answer(intent: str, sheet: FactSheet, question: str | None = None) -> str | None:
    if intent not in INTENTS:
        return None
    k = _facts(sheet)
    simple = _beginner(sheet)
    if intent == "car_health":
        q = question or ""
        if not k:
            # nothing measured: a brake / engine question still gets what the game never sends
            return _game_sentence(sheet) if _BRAKE_Q.search(q) or _ENGINE_Q.search(q) else None
        return _car(sheet, k, q, simple)
    if not k:
        return None
    side = "ahead" if intent == "attack" else "behind"
    f = k.get(f"racecraft_{side}") or k.get(f"racecraft_{side}_unknown") or k.get("racecraft_unknown")
    return None if f is None else _said(f, simple)


def names_part(question: str | None) -> bool:
    """The question is about the brakes or the engine (the answer is about that part, or why there is none)."""
    q = question or ""
    return bool(_BRAKE_Q.search(q) or _ENGINE_Q.search(q))


def tyres_answer(sheet: FactSheet, question: str | None, base: Callable[[FactSheet], str | None] | None) -> str | None:
    """The tyres intent with the temperature sentence (see the module docstring)."""
    k = _facts(sheet)
    temps = k.get("tyre_temps")
    said = base(sheet) if base is not None else None
    if temps is None:
        return said
    simple = _beginner(sheet)
    q = question or ""
    if _TEMP_Q.search(q):
        return _tyre_yes_no(temps, q, simple) or _said(temps, simple)
    if simple and not _WEAR_Q.search(q):
        return _said(temps, True)  # "are my tyres ok?": the plain temperature sentence, not wear percentages
    notable = temps.data.get("state") == "cold" or temps.data.get("hot_over_c") is not None
    if not notable:
        return said
    if said is None:
        return _said(temps, simple)
    if simple:
        return _said(temps, True)  # one idea: the cold tyres matter now
    return f"{said} {_said(temps, False)}"
