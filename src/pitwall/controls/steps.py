"""How-to steps ("Map it"): the game's own words next to Pitwall's, and what to do with which control.

``guide(...)`` -> ``MapGuide`` (contract): where the game's controls screen is (with its evidence), short intro lines,
one step per assignment in the game's menu-group order (F1 25: Control Scheme -> MFD Shortcuts -> UDP Custom
Actions), and an outro. The research ``native_name`` is printed verbatim; Pitwall's plain label beside it is a
paraphrase [D] and never presented as the game's wording. Physical words come from the control's label and slot
("Press TRIANGLE", "Push MENU STICK up", "Turn LEFT ENCODER (12) anticlockwise"); platform words from its signal
(PlayStation names, Xbox names, or "button 12" on PC). "Other game" uses the generic steps and the synonyms.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pitwall.controls.catalog import PTT_FUNCTION, Catalog, in_sentence, native_parts, split_name, weakest

__all__ = ["guide", "physical", "split_name"]
from pitwall.controls.model import Assignment, WheelControl, WheelDef, signal_platform
from pitwall.controls.recommend import ACTION_SUFFIX, DIRECTION_WORDS, other_rows

F1_REBIND = (
    "F1 25 may drop or swap an action that was already on a button when you rebind it (unverified): check the list "
    "after each change."
)


def _platform_words(cat: Catalog, c: WheelControl, slot: str | None, sp: str | None) -> str | None:
    sig = c.signal(sp)
    if sig is None:
        return None
    kind, value = sig.slot(slot)
    if kind == "pad" and value and sp is not None:
        pd = cat.pad_def(sp, value)
        if pd is not None:
            return pd.label
        if value == "dpad" and slot in DIRECTION_WORDS:
            return f"D-pad {DIRECTION_WORDS[slot]}"
        return value
    if kind == "hid_button" and value:
        return f"button {value.replace('/', ' or ')}" if "/" in value and " " not in value else f"button {value}"
    if kind == "game_specific" and value:
        return f"{value}, game-specific"
    if kind == "folded" and value:
        shown = cat.pad_def(sp or "", value)
        return f"sends {shown.label if shown else value}, like another control"
    return None


def _same_words(words: str, c: WheelControl, slot: str | None) -> bool:
    """ "Press SQUARE (Square)": the platform's words add nothing when they are the control's own name."""
    w = words.strip().lower()
    names = {c.label.lower(), f"{c.label} {slot}".lower(), f"{c.label} {DIRECTION_WORDS.get(slot or '', '')}".lower()}
    return w in names


def physical(cat: Catalog, c: WheelControl, slot: str | None, sp: str | None) -> str:
    name = c.label.upper()
    k = c.kind
    if slot in ("cw", "ccw"):
        text = f"Turn {name} {DIRECTION_WORDS[slot]}"
    elif slot in ("up", "down", "left", "right"):
        text = f"Flick {name} {slot}" if k == "toggle_momentary" else f"Push {name} {slot}"
    elif slot == "push":
        text = f"Press {name} in"
    elif slot in ("on", "off"):
        text = f"Switch {name} {slot}"
    elif slot is not None and slot.startswith("pos_"):
        text = f"Turn {name} to position {slot[4:]}"
    else:
        text = f"Press {name}"
    words = _platform_words(cat, c, slot, sp)
    return f"{text} ({words})" if words and not _same_words(words, c, slot) else text


def _label(cat: Catalog, a: Assignment) -> str:
    if a.function == PTT_FUNCTION:
        return "Talk to Pitwall"
    base = cat.label(a.function)
    if a.action in ACTION_SUFFIX:
        return base + ACTION_SUFFIX[a.action]
    return f"{base} {DIRECTION_WORDS.get(a.action, a.action)}"


def _capped(evidence: str | None, unverified: bool) -> str | None:
    """A row the research couldn't confirm in the game is at most Community, however official its source."""
    return weakest(evidence, "U") if unverified and evidence is not None else evidence


def guide(
    cat: Catalog,
    game_id: str,
    platform: str,
    wheel: WheelDef,
    assignments: Sequence[Assignment],
    *,
    game_name: str | None = None,
    other_functions: Sequence[str] = (),
) -> dict[str, Any]:
    game = cat.games.get(game_id)
    sp = signal_platform(platform)
    label = game.label_on(platform) if game is not None else (game_name or "this game")
    rows: Mapping[str, Any] = game.functions if game is not None else other_rows(cat, other_functions)
    groups = list(game.menu.groups) if game is not None else []
    intro: list[str] = []
    if game is not None:
        if game.menu.evidence is None:
            intro.append(f"In {label}, open {game.menu.where} (exact menu path not researched).")
        else:
            intro.append(f"In {label}, open {game.menu.where}.")
        if game.menu.note and game.menu.evidence is not None:
            intro.append(game.menu.note[0].upper() + game.menu.note[1:] + ".")
        defaults = [a for a in assignments if a.origin == "game_default"]
        if defaults:
            names = ", ".join(dict.fromkeys(cat.label(a.function) for a in defaults))
            intro.append(f"Already set by {label} for this wheel (its own defaults): {names}. Nothing to change there.")
        else:
            intro.append(game.preset_warning)
        if game.id == "f1_25":
            intro.append(F1_REBIND)
        fixed = [a for a in assignments if a.origin == "game_fixed"]
        if fixed:
            names = ", ".join(dict.fromkeys(cat.label(a.function) for a in fixed))
            community = any(
                (fx := cat.fixed_for(game.id, wheel.template, a.function)) is not None and fx.evidence != "V"
                for a in fixed
            )
            tail = " (which coloured stick does what is community-reported)" if community else ""
            intro.append(f"Nothing to map for {names}: {label} sets those itself{tail}.")
    else:
        intro.extend(cat.other_game_steps)
    order = {fn: i for i, fn in enumerate(rows)}
    todo = [
        a
        for a in assignments
        if a.origin not in ("game_fixed", "game_default") and (a.control_id is not None or a.udp_action)
    ]

    def sort_key(a: Assignment) -> tuple[int, int, str]:
        row = rows.get(a.function)
        grp = getattr(row, "menu_group", None)
        gi = groups.index(grp) if grp in groups else len(groups)
        return (gi, order.get(a.function, 999), a.action)

    steps: list[dict[str, Any]] = []
    for a in sorted(todo, key=sort_key):
        row = rows.get(a.function)
        c = wheel.control(a.control_id)
        native_note: str | None = None
        if a.function == PTT_FUNCTION and a.udp_action:
            native = f"UDP Action {a.udp_action}"
        elif game is not None:
            native, native_note = native_parts(row, a.action)
        else:
            native = ""  # "Other game": no research, so no name of the game's is claimed
        lab = _label(cat, a)
        if c is not None:
            phys = physical(cat, c, a.slot, sp)
        elif a.function == PTT_FUNCTION:
            phys = "Press the button you already use to talk to Pitwall"
        else:
            phys = "Use the control you already have for it"
        notes: list[str] = []
        conds = list(getattr(row, "conditions", ()) or ()) if row is not None else []
        if conds:  # "Only: 2025 cars: DRS, in DRS zones; 2026 cars: ..."
            notes.append("Only: " + "; ".join(conds) + ".")
        if game is not None and row is not None and not getattr(row, "native_found", True):
            notes.append(f"The research found no name for this in {label}: look for {in_sentence(lab)} in its list.")
        unverified = game is not None and getattr(row, "in_race", None) == "unverified"
        if unverified:
            notes.append(f"Unverified in {label}: it may not be in the game's list at all.")
        if game is None:
            syn = cat.functions[a.function].synonyms if a.function in cat.functions else ()
            if syn:
                notes.append("The game may call it: " + ", ".join(syn) + ".")
        sig = c.signal(sp) if c is not None else None
        if sig is not None:
            kind, _v = sig.slot(a.slot)
            name = c.label if c is not None else "this control"
            if kind == "game_specific":
                notes.append(cat.warnings["game_specific"].format(game=label, ctl=name))
            elif kind == "unknown":
                notes.append(f"What {name} sends isn't known: check it in the game.")
        game_ev = getattr(row, "evidence", None)
        wheel_ev = (sig.evidence if sig is not None else c.evidence) if c is not None else None
        steps.append(
            {
                "n": len(steps) + 1,
                "group": getattr(row, "menu_group", None),
                "native": native,
                "native_note": native_note,  # additive: the bracketed part of the game's name, for a second line
                "label": lab,
                "physical": phys,
                "evidence": _capped(weakest(game_ev, wheel_ev) if c is not None else game_ev, unverified),
                "note": " ".join(notes) or None,
            }
        )
    outro = (
        ["Open Test to check each button reaches Pitwall."]
        if game is not None and game.button_path == "f1_butn"
        else [f"Check each one on track: Pitwall can't see your wheel in {label}."]
    )
    return {
        "where": game.menu.where if game is not None else "the game's Controls screen",
        "where_evidence": game.menu.evidence if game is not None else None,
        "intro": intro,
        "steps": steps,
        "outro": outro,
    }
