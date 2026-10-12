"""The engineer's "which button is ...?" answers (intent ``controls_where``): deterministic, never the LLM.

Answered at once from the seated driver's saved layout for the session's (or the selected) game, in at most 30 words,
for the radio and Review › Ask alike:

* "In your layout, brake bias + is R3 tab and − is L3 tab. It's 56 percent front now." The value is added only for
  F1 brake bias or ERS mode, from a fresh frame (<= 2 s) of a real, non-replay session.
* "In GT7, ASM is only in the pause menu, under Assistance Settings. It can't go on a button." (the catalogue's
  not-possible sentence).
* "You haven't saved buttons for F1 25 yet. Open Setup, then Controls."
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from pitwall.adapters.f1.enums import ERS_DEPLOY_MODE
from pitwall.controls.catalog import PTT_FUNCTION, Catalog, GameDef, in_sentence
from pitwall.controls.model import Assignment, ControlsState, WheelDef
from pitwall.controls.recommend import DIRECTION_WORDS

MAX_WORDS = 30
_PTT_WORDS = re.compile(r"\b(?:push[ -]?to[ -]?talk|ptt|talk to (?:you|pitwall|the engineer)|radio button)\b", re.I)
_GAME_PTT = re.compile(r"\b(?:game'?s?|voice chat|in-?game)\b", re.I)


@dataclass(frozen=True, slots=True)
class LiveValues:
    """What the live stream says now (only filled for a real, fresh F1 stream)."""

    brake_bias_front_pct: float | None = None
    ers_deploy_mode: int | None = None


def _phrases(cat: Catalog) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for f in cat.functions.values():
        for p in (f.label, f.id.replace("_", " "), *f.synonyms):
            for part in re.split(r"\s*/\s*", p):
                part = part.strip().lower()
                if len(part) >= 2:
                    out.append((part, f.id))
    out.sort(key=lambda x: -len(x[0]))
    return out


def match_function(cat: Catalog, question: str) -> str | None:
    """The function a question names (labels and the names games use; the longest match wins)."""
    q = question.lower()
    if _PTT_WORDS.search(q):
        return "ptt_game" if _GAME_PTT.search(q) else PTT_FUNCTION
    for phrase, fid in _phrases(cat):
        if re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", q):
            return fid
    return None


def _where(wheel: WheelDef | None, a: Assignment) -> str:
    c = wheel.control(a.control_id) if wheel is not None else None
    if c is None:
        return "your button" if a.function == PTT_FUNCTION else "a control"
    if a.slot in ("cw", "ccw", "up", "down", "left", "right"):
        return f"{c.label} {DIRECTION_WORDS[a.slot]}"
    if a.slot == "push":
        return f"{c.label} pushed in"
    return c.label


def _trim(text: str) -> str:
    """At most ``MAX_WORDS`` words, ending at the last whole sentence or clause that fits (never mid-clause)."""
    words = text.split()
    if len(words) <= MAX_WORDS:
        return text
    cut = " ".join(words[:MAX_WORDS])
    end = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:end] if end > 0 else cut).rstrip(",.;") + "."


def answer(
    cat: Catalog,
    state: ControlsState,
    question: str,
    *,
    game: GameDef | None,
    platform: str | None,
    driver_id: int | None,
    live: LiveValues | None = None,
) -> str:
    if game is None:
        return "Tell me which game you're playing: open Setup, then Game."
    fn = match_function(cat, question)
    if fn is None:
        return "Which control? Ask me, for example, which button is brake bias."
    label = cat.label(fn)
    row = game.functions.get(fn)
    if fn == PTT_FUNCTION and game.button_path != "f1_butn":
        return _trim(cat.not_possible["wheel_ptt_no_telemetry"].replace("{game}", game.label))
    if row is not None and (row.in_race in ("pause_menu", "no") or row.binding in ("menu", "none")):
        if row.text:
            return _trim(row.text)
        if row.not_possible:
            return _trim(cat.not_possible[row.not_possible].replace("{game}", game.label))
        if row.in_race == "pause_menu" or row.binding == "menu":
            return _trim(f"In {game.label}, {in_sentence(label)} is a menu setting. It can't go on a button.")
        return _trim(f"In {game.label}, {in_sentence(label)} is set before the race, not while driving.")
    if row is None and fn != PTT_FUNCTION:
        return _trim(f"{game.label} has no {in_sentence(label)} control in Pitwall's research.")
    layout = None
    if platform is not None:
        layout = state.layout_for(driver_id, game.id, platform)
    if layout is None:
        layout = next((x for p in game.platforms if (x := state.layout_for(driver_id, game.id, p)) is not None), None)
    if layout is None:
        return f"You haven't saved buttons for {game.label} yet. Open Setup, then Controls."
    wheel = state.wheel(layout.wheel_id)
    mine = [a for a in layout.assignments if a.function == fn]
    if not mine:
        if row is not None and row.binding == "mfd":  # GT7 TC / brake balance / fuel map, ACC engine map
            return _trim(f"{label} isn't on your wheel: in {game.label} you change it on the MFD.")
        tail = " Use the MFD." if row is not None and row.menu_group == "MFD Shortcuts" else ""
        return _trim(f"{label} isn't on your wheel in your {game.label} layout.{tail}")
    by_action: Mapping[str, Assignment] = {a.action: a for a in mine}
    if fn == PTT_FUNCTION:
        a = mine[0]
        n = f", UDP Action {a.udp_action}" if a.udp_action else ""
        text = f"Talk to me with {_where(wheel, a)}{n}."
    elif "inc" in by_action and "dec" in by_action:
        text = (
            f"In your layout, {in_sentence(label)} + is {_where(wheel, by_action['inc'])} "
            f"and − is {_where(wheel, by_action['dec'])}."
        )
    elif mine[0].origin == "game_fixed":
        fx = cat.fixed_for(game.id, wheel.template if wheel is not None else None, fn)
        community = " (community-reported)" if fx is None or fx.evidence != "V" else ""
        text = f"{label} is on {_where(wheel, mine[0])}{community}: {game.label} sets it itself."
    else:
        text = f"In your layout, {in_sentence(label)} is {_where(wheel, mine[0])}."
    if live is not None:
        if fn == "brake_bias" and live.brake_bias_front_pct is not None:
            text += f" It's {live.brake_bias_front_pct:g} percent front now."
        elif fn == "ers_mode" and live.ers_deploy_mode is not None:
            text += f" ERS mode is {ERS_DEPLOY_MODE.get(live.ers_deploy_mode, str(live.ers_deploy_mode))} now."
    return _trim(text)


def speech(text: str) -> str:
    """The same for TTS: the plus and minus signs as words."""
    return re.sub(r"\s\+\s", " plus ", re.sub(r"\s−\s", " minus ", text))
