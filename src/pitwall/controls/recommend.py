"""Deterministic button recommendations (no LLM): which function goes on which control of the driver's wheel.

``recommend(catalog, wheel, game, platform, preset, kept, ...)`` (spec 3):

1. Resolve the game's rows for the platform (a row with a ``platform_note`` is unverified off PC).
2. Partition: ``not_on_wheel`` (pause menu / menu / set before the race), ``not_in_game`` (the game has no such
   control; the owner's topics - ride height, stability, ABS, TC, aero - are always answered), candidates
   (``yes`` / ``conditional`` / ``unverified``, the last two with conditions or warnings).
3. The preset's functions (overlay), plus what the driver keeps. Talk to Pitwall comes first in F1 25; elsewhere it
   is the iPad's talk button (``pitwall_ptt.path == "screen"``), never a wheel control.
4. The wheel's slots on this platform: signal ``none`` is dropped; game-specific signals are used last (a second
   pass) with a warning, folded signals (shared with another control) score -4 and are never push-to-talk, unknown
   ones -2 with "check it in the game". Gear paddles, the wheel's own menu, mode and layer switches, analogue paddles
   and console system buttons are kept for driving. Where the game's MFD default is the D-pad, the first D-pad (or
   funky directions) is the MFD's.
5. Fixed by the game first (GT7's coloured sticks on the GT DD Pro), then what the driver keeps.
6. Talk to Pitwall (F1 only): a plain button whose signal is its own, thumb first; UDP Action from the driver's
   layout or the deploy setting, else 1.
7. The rest in priority order (frequency weight, then preset order), each on its best free slot or slot pair:
   ``SUIT[shape][pattern] + 2 x reach x frequency + signal penalty``; ties break on the wheel's control order, then
   slot order. F1's pit limiter shares the DRS button (the game's own default) only when no button is left.
8. What does not fit is listed: "No free control left for {fn}. Use the MFD." where the game has one.
9. Every assignment has a one-sentence reason (<= 160 characters), conditions, warnings, evidence and what Pitwall
   sees. Pitwall never suggests a value (brake bias etc.), only a place.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pitwall.controls.catalog import MFD_FUNCTION, PTT_FUNCTION, Catalog, GameDef, GameFunction, weakest
from pitwall.controls.model import (
    Assignment,
    Origin,
    Signal,
    WheelControl,
    WheelDef,
    signal_platform,
)

MAX_REASON = 160
RESERVED_KINDS = {
    "shift_paddle": "gear",
    "device_menu": "wheel_menu",
    "mode_selector": "mode_switch",
    "virtual_layer": "mode_switch",
    "analogue_paddle": "clutch",
}
RESERVED_LABELS = {
    "gear_up": "Gear up",
    "gear_down": "Gear down",
    "clutch": "Clutch / analogue paddle",
    "system": "Console button",
    "wheel_menu": "The wheel's own menu",
    "mode_switch": "The wheel's mode switch",
    "mfd": "The game's MFD (D-pad)",
}
DIRECTIONS = ("up", "down", "left", "right")
MIRROR = {
    "left_thumb": "right_thumb",
    "right_thumb": "left_thumb",
    "left_top": "right_top",
    "right_top": "left_top",
    "left_lower": "right_lower",
    "right_lower": "left_lower",
    "back_left": "back_right",
    "back_right": "back_left",
}
MFD_GROUPS = frozenset({"brakes", "electronics", "power", "chassis"})  # car settings a game's MFD usually holds
PAIR_ACTIONS = ("inc", "dec")
SINGLE_ORDER = ("press", "hold")
ACTION_SUFFIX = {"inc": " +", "dec": " −", "press": "", "hold": "", "select": " (open)"}
DIRECTION_WORDS = {
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "cw": "clockwise",
    "ccw": "anticlockwise",
}


# ---------------------------------------------------------------------------------------------- results
@dataclass(frozen=True, slots=True)
class RecommendedAssignment:
    assignment: Assignment
    label: str
    native: str
    menu_group: str | None
    control_label: str | None
    signal: Signal | None
    reason: str
    evidence: str | None
    evidence_game: str | None
    evidence_wheel: str | None
    source_ids: tuple[str, ...]
    conditions: tuple[str, ...]
    warnings: tuple[str, ...]
    pitwall_sees: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.assignment.to_dict(),
            "label": self.label,
            "native": self.native,
            "menu_group": self.menu_group,
            "control_label": self.control_label,
            "signal": None if self.signal is None else self.signal.to_dict(),
            "reason": self.reason,
            "evidence": self.evidence,
            "evidence_parts": {"game": self.evidence_game, "wheel": self.evidence_wheel},
            "source_ids": list(self.source_ids),
            "conditions": list(self.conditions),
            "warnings": list(self.warnings),
            "pitwall_sees": self.pitwall_sees,
        }


@dataclass(frozen=True, slots=True)
class Recommendation:
    game: str
    platform: str
    wheel_id: str
    preset: str
    driver_id: int | None
    catalogue_version: str
    assignments: tuple[RecommendedAssignment, ...]
    pitwall_ptt: Mapping[str, Any]
    not_on_wheel: tuple[Mapping[str, str], ...]
    not_in_game: tuple[Mapping[str, str], ...]
    unplaced: tuple[Mapping[str, str], ...]
    reserved: tuple[Mapping[str, str], ...]
    notes: tuple[str, ...]

    def plain_assignments(self) -> tuple[Assignment, ...]:
        return tuple(r.assignment for r in self.assignments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game,
            "platform": self.platform,
            "wheel_id": self.wheel_id,
            "preset": self.preset,
            "driver_id": self.driver_id,
            "catalogue_version": self.catalogue_version,
            "status": "research_only",
            "assignments": [a.to_dict() for a in self.assignments],
            "pitwall_ptt": dict(self.pitwall_ptt),
            "not_on_wheel": [dict(x) for x in self.not_on_wheel],
            "not_in_game": [dict(x) for x in self.not_in_game],
            "unplaced": [dict(x) for x in self.unplaced],
            "reserved": [dict(x) for x in self.reserved],
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------------------------- slots
@dataclass(frozen=True, slots=True)
class SlotRef:
    control: WheelControl
    index: int  # the control's order in the wheel (tie-break)
    slot: str
    slot_index: int
    kind: str  # signal kind for this slot on the platform
    value: str | None
    folded: bool
    fold_key: tuple[str, str] | None = None  # slots sharing one signal: using one uses them all

    @property
    def key(self) -> tuple[str, str]:
        return (self.control.id, self.slot)

    @property
    def game_specific(self) -> bool:
        return self.kind == "game_specific"


def _norm(v: str | None) -> str | None:
    return None if v is None else v.strip().lower()


def expand_slots(wheel: WheelDef, sp: str | None, skip: set[str]) -> list[SlotRef]:
    """Every usable slot of the wheel on this platform (signal ``none`` dropped), with folding worked out."""
    raw: list[tuple[WheelControl, int, str, int, str, str | None]] = []
    for idx, c in enumerate(wheel.controls):
        if c.id in skip:
            continue
        sig = c.signal(sp)
        for si, slot in enumerate(c.slots()):
            kind, value = sig.slot(slot) if sig is not None else ("unknown", None)
            if kind == "none":
                continue
            raw.append((c, idx, slot, si, kind, value))
    owners: dict[tuple[str, str], set[str]] = {}
    for c, _i, _s, _si, kind, value in raw:
        v = _norm(value)
        if v is None or kind in ("unknown", "none", "hid_axis", "hid_hat"):
            continue
        if kind == "game_specific" and not any(ch.isdigit() for ch in v):
            continue  # a bare "GSB" (no number) says nothing about sharing
        base = "pad" if kind == "folded" else kind
        owners.setdefault((base, v), set()).add(c.id)
    out: list[SlotRef] = []
    for c, idx, slot, si, kind, value in raw:
        v = _norm(value)
        base = "pad" if kind == "folded" else kind
        shared = v is not None and len(owners.get((base, v), ())) > 1
        folded = kind == "folded" or shared
        out.append(SlotRef(c, idx, slot, si, kind, value, folded, (base, v) if folded and v is not None else None))
    return out


# ---------------------------------------------------------------------------------------------- needs
@dataclass(frozen=True, slots=True)
class Need:
    function: str
    kind: str  # "pair" | "menu" | "single"
    shape: str  # taxonomy-style shape used for SUIT
    actions: tuple[str, ...]
    priority: tuple[float, int]


def needs_of(fn: str, row: GameFunction | None, cat: Catalog, prio: tuple[float, int]) -> list[Need]:
    fdef = cat.functions[fn]
    acts = dict(row.actions) if row is not None else {}
    if not acts:
        if fdef.shape == "pair":
            return [Need(fn, "pair", "pair", PAIR_ACTIONS, prio)]
        if fdef.shape == "menu" and fn == MFD_FUNCTION:
            return [Need(fn, "menu", "menu", DIRECTIONS, prio)]
        single = fdef.shape if fdef.shape in ("toggle", "hold", "momentary", "cycle") else "momentary"
        return [Need(fn, "single", single, ("hold" if single == "hold" else "press",), prio)]
    out: list[Need] = []
    if "inc" in acts and "dec" in acts:
        out.append(Need(fn, "pair", "pair", PAIR_ACTIONS, prio))
    elif "inc" in acts:  # only one direction is bindable (AMS2 "ERS Mode Increase")
        out.append(Need(fn, "single", "cycle", ("inc",), prio))
    dirs = tuple(d for d in DIRECTIONS if d in acts)
    if dirs:
        out.append(Need(fn, "menu", "menu", dirs, prio))
    single = fdef.shape if fdef.shape in ("toggle", "hold", "momentary", "cycle") else "momentary"
    for a in ("select", *SINGLE_ORDER):
        if a in acts:
            shape = "hold" if a == "hold" and fdef.shape == "hold" else ("momentary" if a == "select" else single)
            out.append(Need(fn, "single", shape, (a,), prio))
    return out


# ---------------------------------------------------------------------------------------------- the engine
@dataclass(slots=True)
class _Ctx:
    cat: Catalog
    game: GameDef | None
    game_label: str
    sp: str | None
    platform: str
    wheel: WheelDef
    rows: dict[str, GameFunction | None]
    slots: list[SlotRef] = field(default_factory=list)
    used: set[tuple[str, str]] = field(default_factory=set)
    placed: list[RecommendedAssignment] = field(default_factory=list)
    placed_fns: dict[str, list[RecommendedAssignment]] = field(default_factory=dict)


def _reach_w(cat: Catalog, c: WheelControl) -> float:
    return cat.reach_weight.get(c.effective_reach, 0.5)


def _penalty(cat: Catalog, s: SlotRef) -> float:
    if s.folded:
        return float(cat.signal_penalty.get("folded") or -4.0)
    p = cat.signal_penalty.get(s.kind, 0.0)
    return float(p or 0.0)


def _fmt(template: str, **kw: Any) -> str:
    text = template.format(**kw)
    return text if len(text) <= MAX_REASON else text[: MAX_REASON - 1].rstrip() + "…"


def _signal_for(c: WheelControl, sp: str | None) -> Signal | None:
    return c.signal(sp)


def _warnings(ctx: _Ctx, slots: Sequence[SlotRef], row: GameFunction | None) -> list[str]:
    cat = ctx.cat
    out: list[str] = []
    if ctx.game is not None:
        out.append(ctx.game.preset_warning)
    plat = {"ps": "PlayStation", "xbox": "Xbox", "pc": "PC"}.get(ctx.sp or "", ctx.platform)
    for s in slots:
        if s.game_specific:
            out.append(cat.warnings["game_specific"].format(game=ctx.game_label))
        elif s.folded:
            out.append(cat.warnings["folded"])
        elif s.kind == "unknown":
            out.append(cat.warnings["unknown"].format(platform=plat))
        if s.control.kind == "multi_position" and s.slot in ("cw", "ccw") and s.control.mps_mode != "enc":
            out.append(cat.warnings["mps_mode"])
    if row is not None and row.platform_note and ctx.platform != "pc":
        out.append(row.platform_note)
    return list(dict.fromkeys(out))


def _action_label(cat: Catalog, fn: str, action: str) -> str:
    base = cat.label(fn)
    if fn == PTT_FUNCTION:
        return "Talk to Pitwall"
    if action in ACTION_SUFFIX:
        return base + ACTION_SUFFIX[action]
    return f"{base} {DIRECTION_WORDS.get(action, action)}"


def _native(row: GameFunction | None, fn: str, udp: int | None) -> str:
    if fn == PTT_FUNCTION and udp is not None:
        return f"UDP Action {udp}"
    return row.native_name if row is not None else ""


def _emit(
    ctx: _Ctx,
    fn: str,
    action: str,
    slot: SlotRef | None,
    reason: str,
    *,
    origin: Origin = "recommended",
    udp: int | None = None,
    extra_warnings: Iterable[str] = (),
    control_id: str | None = None,
    slot_name: str | None = None,
    check: Any = None,
) -> RecommendedAssignment:
    row = ctx.rows.get(fn)
    c = slot.control if slot is not None else ctx.wheel.control(control_id)
    sig = _signal_for(c, ctx.sp) if c is not None else None
    wheel_ev: str | None = sig.evidence if sig is not None else (c.evidence if c is not None else None)
    game_ev = row.evidence if row is not None else None
    evidence = weakest(game_ev, wheel_ev) if c is not None else game_ev
    warnings = _warnings(ctx, [slot] if slot is not None else [], row) + list(extra_warnings)
    a = Assignment(
        key=f"{fn}.{action}",
        function=fn,
        action=action,
        control_id=c.id if c is not None else None,
        slot=slot.slot if slot is not None else slot_name,
        udp_action=udp,
        origin=origin,
        check=check,
    )
    sees = row.pitwall_sees if row is not None else None
    if fn == PTT_FUNCTION and udp is not None:
        sees = f"BUTN bit (UDP Action {udp})"
    ra = RecommendedAssignment(
        assignment=a,
        label=_action_label(ctx.cat, fn, action),
        native=_native(row, fn, udp),
        menu_group=row.menu_group if row is not None else None,
        control_label=c.label if c is not None else None,
        signal=sig,
        reason=reason,
        evidence=evidence,
        evidence_game=game_ev,
        evidence_wheel=wheel_ev,
        source_ids=tuple(dict.fromkeys([*(row.source_ids if row else ()), *(sig.source_ids if sig else ())])),
        conditions=row.conditions if row is not None else (),
        warnings=tuple(dict.fromkeys(warnings)),
        pitwall_sees=sees,
    )
    ctx.placed.append(ra)
    ctx.placed_fns.setdefault(fn, []).append(ra)
    if slot is not None:
        ctx.used.add(slot.key)
        if slot.fold_key is not None:  # one control per fold group: the game can't tell the others apart
            ctx.used.update(s.key for s in ctx.slots if s.fold_key == slot.fold_key and s.control.id != slot.control.id)
    return ra


# --- candidate search ------------------------------------------------------------------------------------------
def _single_pattern(s: SlotRef) -> str | None:
    k = s.control.kind
    if k == "button" and s.slot == "press":
        return "button"
    if s.slot == "push" and k in ("dpad_hat", "funky_7way", "encoder"):
        return f"{k}:push"
    if s.slot in DIRECTIONS and k in ("dpad_hat", "funky_7way"):
        return f"{k}:direction"
    if k == "toggle_latching" and s.slot == "on":
        return "toggle_latching:on/off"
    return None


def _best_single(ctx: _Ctx, need: Need, slots: Sequence[SlotRef], allow_gs: bool) -> SlotRef | None:
    suit = ctx.cat.suitability.get(need.shape, {})
    fw = ctx.cat.freq_weight.get(ctx.cat.functions[need.function].freq, 1.0)
    best: tuple[float, int, int, SlotRef] | None = None
    for s in slots:
        if s.key in ctx.used or (s.game_specific and not allow_gs):
            continue
        pat = _single_pattern(s)
        if pat is None or pat not in suit:
            continue
        score = suit[pat] + 2 * _reach_w(ctx.cat, s.control) * fw + _penalty(ctx.cat, s)
        cand = (-score, s.index, s.slot_index, s)
        if best is None or cand[:3] < best[:3]:
            best = cand
    return None if best is None else best[3]


def _pair_candidates(ctx: _Ctx, slots: Sequence[SlotRef], allow_gs: bool) -> list[tuple[str, SlotRef, SlotRef]]:
    by_ctl: dict[str, dict[str, SlotRef]] = {}
    for s in slots:
        if s.key in ctx.used or (s.game_specific and not allow_gs):
            continue
        by_ctl.setdefault(s.control.id, {})[s.slot] = s
    out: list[tuple[str, SlotRef, SlotRef]] = []
    for cs in by_ctl.values():
        c = next(iter(cs.values())).control
        k = c.kind
        if k in ("encoder", "funky_7way", "multi_position") and "cw" in cs and "ccw" in cs:
            out.append((f"{k}:cw/ccw", cs["cw"], cs["ccw"]))
        if k == "toggle_momentary" and "up" in cs and "down" in cs:
            out.append(("toggle_momentary:up/down", cs["up"], cs["down"]))
        if k in ("dpad_hat", "funky_7way", "thumbstick"):
            pat = "dpad_hat:opposite" if k == "dpad_hat" else f"{k}:opposite"
            for d1, d2 in (("up", "down"), ("right", "left")):
                if d1 in cs and d2 in cs:
                    if k == "thumbstick" and (cs[d1].kind == "unknown" or cs[d2].kind == "unknown"):
                        continue  # stick directions count only where the platform reports them as buttons
                    out.append((pat, cs[d1], cs[d2]))
    buttons = [
        s
        for s in slots
        if s.control.kind == "button"
        and s.slot == "press"
        and s.key not in ctx.used
        and (allow_gs or not s.game_specific)
    ]
    for a, b in itertools.combinations(buttons, 2):
        za, zb = a.control.zone, b.control.zone
        if za == zb and za != "unplaced":
            out.append(("button+button:same_zone", a, b))
        elif MIRROR.get(za) == zb:
            right, left = (a, b) if za.startswith("right") or za == "back_right" else (b, a)
            out.append(("button+button:mirrored", right, left))  # + on the right-hand one [D]
        else:
            out.append(("button+button:any", a, b))
    return out


def _best_pair(ctx: _Ctx, need: Need, slots: Sequence[SlotRef], allow_gs: bool) -> tuple[str, SlotRef, SlotRef] | None:
    suit = ctx.cat.suitability.get("pair", {})
    fw = ctx.cat.freq_weight.get(ctx.cat.functions[need.function].freq, 1.0)
    best: tuple[tuple[float, int, int, int, int], tuple[str, SlotRef, SlotRef]] | None = None
    for pat, a, b in _pair_candidates(ctx, slots, allow_gs):
        if pat not in suit:
            continue
        reach = min(_reach_w(ctx.cat, a.control), _reach_w(ctx.cat, b.control))
        score = suit[pat] + 2 * reach * fw + min(_penalty(ctx.cat, a), _penalty(ctx.cat, b))
        key = (-score, a.index, a.slot_index, b.index, b.slot_index)
        if best is None or key < best[0]:
            best = (key, (pat, a, b))
    return None if best is None else best[1]


def _best_menu(
    ctx: _Ctx, need: Need, slots: Sequence[SlotRef], allow_gs: bool, only: str | None = None
) -> list[SlotRef] | None:
    suit = ctx.cat.suitability.get("menu", {})
    by_ctl: dict[str, dict[str, SlotRef]] = {}
    for s in slots:
        if s.key in ctx.used or (s.game_specific and not allow_gs):
            continue
        if only is not None and s.control.id != only:
            continue
        by_ctl.setdefault(s.control.id, {})[s.slot] = s
    best: tuple[tuple[float, int], list[SlotRef]] | None = None
    for cs in by_ctl.values():
        c = next(iter(cs.values())).control
        pat = {
            "dpad_hat": "dpad_hat",
            "funky_7way": "funky_7way:directions",
            "thumbstick": "thumbstick:directions",
        }.get(c.kind)
        if pat is None or pat not in suit or not all(d in cs for d in need.actions):
            continue
        chosen = [cs[d] for d in need.actions]
        score = suit[pat] + 2 * _reach_w(ctx.cat, c) * 3.0 + min(_penalty(ctx.cat, s) for s in chosen)
        key = (-score, chosen[0].index)
        if best is None or key < best[0]:
            best = (key, chosen)
    return None if best is None else best[1]


# --- reasons ---------------------------------------------------------------------------------------------------
def _pair_reason(ctx: _Ctx, fn: str, pat: str, a: SlotRef, b: SlotRef) -> str:
    r = ctx.cat.reasons
    label = ctx.cat.label(fn)
    if pat == "encoder:cw/ccw":  # "under your thumb" only when it is (a button box's encoder is a reach away)
        key = "pair:encoder" if a.control.effective_reach == "thumb" else "pair:encoder_far"
        return _fmt(r[key], fn=label, ctl=a.control.label)
    if pat == "funky_7way:cw/ccw":
        return _fmt(r["pair:funky"], fn=label, ctl=a.control.label)
    if pat == "multi_position:cw/ccw":
        return _fmt(r["pair:rotary"], fn=label, ctl=a.control.label)
    if pat == "toggle_momentary:up/down":
        return _fmt(r["pair:rocker"], fn=label, ctl=a.control.label)
    if pat.endswith(":opposite"):
        return _fmt(r["pair:dpad"], fn=label, ctl=a.control.label, a=a.slot, b=b.slot)
    key = {"button+button:same_zone": "pair:buttons_same_zone", "button+button:mirrored": "pair:buttons_mirrored"}.get(
        pat, "pair:buttons"
    )
    return _fmt(r[key], fn=label, a_ctl=a.control.label, b_ctl=b.control.label)


def _single_reason(ctx: _Ctx, fn: str, shape: str, s: SlotRef) -> str:
    r = ctx.cat.reasons
    fdef = ctx.cat.functions[fn]
    reach = s.control.effective_reach
    words = ctx.cat.freq_words.get(fdef.freq, fdef.freq)
    if shape == "hold" and reach == "thumb":
        return _fmt(r["hold:thumb"], fn=fdef.label, ctl=s.control.label)
    if fdef.freq == "rare" and reach != "thumb":
        return _fmt(r["single:far"], fn=fdef.label, ctl=s.control.label)
    if reach == "thumb":
        return _fmt(r["single:thumb"], fn=fdef.label, ctl=s.control.label, freq=words)
    return _fmt(r["single:near"], fn=fdef.label, ctl=s.control.label, freq=words)


# --- placement -------------------------------------------------------------------------------------------------
def _place(ctx: _Ctx, need: Need, slots: Sequence[SlotRef], allow_gs: bool) -> bool:
    fn = need.function
    if need.kind == "pair":
        got = _best_pair(ctx, need, slots, allow_gs)
        if got is None:
            return False
        pat, a, b = got
        reason = _pair_reason(ctx, fn, pat, a, b)
        _emit(ctx, fn, "inc", a, reason)
        _emit(ctx, fn, "dec", b, reason)
        return True
    if need.kind == "menu":
        got_m = _best_menu(ctx, need, slots, allow_gs)
        if got_m is None:
            return False
        reason = _fmt(ctx.cat.reasons["menu:control"], fn=ctx.cat.label(fn), ctl=got_m[0].control.label)
        for d, s in zip(need.actions, got_m, strict=True):
            _emit(ctx, fn, d, s, reason)
        return True
    s1 = _best_single(ctx, need, slots, allow_gs)
    if s1 is None:
        return False
    _emit(ctx, fn, need.actions[0], s1, _single_reason(ctx, fn, need.shape, s1))
    return True


def _menu_text(ctx: _Ctx, fn: str, label: str | None = None) -> str:
    has_mfd = ctx.game is not None and MFD_FUNCTION in ctx.game.functions
    on_mfd = ctx.cat.functions[fn].group in MFD_GROUPS
    fallback = (
        "Use the MFD."
        if has_mfd and on_mfd and fn != MFD_FUNCTION
        else ("Add a control, or swap it for something you use less.")
    )
    return _fmt(ctx.cat.reasons["unplaced"], fn=label or ctx.cat.label(fn), fallback=fallback)


def _row_text(cat: Catalog, game_label: str, row: GameFunction, why: str) -> str:
    if row.text:
        return row.text
    if row.not_possible:
        return cat.not_possible[row.not_possible].replace("{game}", game_label)
    label = cat.label(row.function)
    if why == "pause_menu":
        return f"In {game_label}, {label.lower()} is only in the pause menu, so it can't go on a button."
    if why == "menu":
        return f"In {game_label}, {label.lower()} is a menu setting, so it can't go on a button."
    if why == "no":
        return f"In {game_label}, {label.lower()} is set before the race, not while driving."
    if row.in_race == "unverified":
        return f"No {label.lower()} control was found for {game_label} (unverified)."
    return f"{game_label} has no {label.lower()} control."


def other_rows(cat: Catalog, functions: Sequence[str]) -> dict[str, GameFunction | None]:
    """ "Other game": the functions the driver ticked, all unverified, generic actions from the taxonomy shape."""
    out: dict[str, GameFunction | None] = {}
    for fn in functions:
        if fn not in cat.functions:
            continue
        f = cat.functions[fn]
        actions: dict[str, str] = {}
        if f.shape == "pair":
            actions = {"inc": f"{f.label} +", "dec": f"{f.label} −"}
        elif fn == MFD_FUNCTION:
            actions = {"up": "up", "down": "down", "left": "left", "right": "right"}
        elif f.shape == "hold":
            actions = {"hold": f.label}
        else:
            actions = {"press": f.label}
        out[fn] = GameFunction(
            function=fn,
            in_race="unverified",
            binding="direct",
            conditions=(),
            actions=actions,
            native_name="",
            menu_group=None,
            shares_with=(),
            pitwall_sees=None,
            evidence=None,
            source_ids=(),
            platform_note=None,
        )
    return out


def recommend(
    cat: Catalog,
    wheel: WheelDef,
    game_id: str,
    platform: str,
    preset: str = "advanced",
    kept: Sequence[Assignment] = (),
    *,
    driver_id: int | None = None,
    udp_action: int = 1,
    other_functions: Sequence[str] = (),
    game_name: str | None = None,
) -> Recommendation:
    game = cat.games.get(game_id)
    if game is None and game_id != "other":
        raise KeyError(f"unknown game {game_id!r}")
    sp = signal_platform(platform)
    game_label = game.label if game is not None else (game_name or "this game")
    rows: dict[str, GameFunction | None] = (
        dict(game.functions) if game is not None else dict(other_rows(cat, other_functions))
    )
    ctx = _Ctx(cat, game, game_label, sp, platform, wheel, rows)
    notes: list[str] = []
    template = cat.templates.get(wheel.template or "")
    if wheel.platforms and sp is not None and sp not in wheel.platforms:
        notes.append(f"{wheel.name} isn't listed for this console: every control is shown as unknown.")
    if game is not None and platform not in game.platforms:
        notes.append(f"{game.label} wasn't researched on this platform.")

    # 2. partition
    not_on_wheel: list[dict[str, str]] = []
    not_in_game: list[dict[str, str]] = []
    candidates: dict[str, GameFunction | None] = {}
    for fn, row in rows.items():
        if fn == PTT_FUNCTION:
            continue
        if row is None:
            continue
        in_race = row.in_race
        if row.platform_note and platform != "pc" and in_race == "yes":
            in_race = "unverified"
        if row.in_race == "pause_menu" or row.binding == "menu":
            why = "pause_menu" if row.in_race == "pause_menu" else "menu"
            not_on_wheel.append(
                {"function": fn, "label": cat.label(fn), "why": why, "text": _row_text(cat, game_label, row, why)}
            )
        elif row.in_race == "no" or row.binding == "none":
            if row.absent or row.in_race != "no":
                not_in_game.append(
                    {"function": fn, "label": cat.label(fn), "text": _row_text(cat, game_label, row, "")}
                )
            else:
                not_on_wheel.append(
                    {"function": fn, "label": cat.label(fn), "why": "no", "text": _row_text(cat, game_label, row, "no")}
                )
        else:
            candidates[fn] = replace(row, in_race=in_race) if in_race != row.in_race else row
    if game is not None:
        for topic in cat.owner_topics:
            if topic in rows:
                continue
            text = (
                cat.not_possible["ride_height"]
                if topic == "ride_height"
                else cat.not_possible["aero"]
                if topic == "drs_aero"
                else f"No {cat.label(topic).lower()} control was found for {game_label} in the research."
            )
            not_in_game.append({"function": topic, "label": cat.label(topic), "text": text})

    # 3. what to place
    base = list(game.presets.get(preset, ())) if game is not None else _other_order(cat, list(rows), preset)
    kept_fns = [a.function for a in kept if a.function in candidates and a.function not in base]
    wanted = [fn for fn in dict.fromkeys([*base, *kept_fns]) if fn in candidates and fn != PTT_FUNCTION]
    wanted_set = set(wanted)

    # 4. reserved controls and the wheel's slots
    reserved: list[dict[str, str]] = []
    skip: set[str] = set()
    only_excluded: list[str] = []
    for c in wheel.controls:
        role = RESERVED_KINDS.get(c.kind)
        if role == "gear":
            role = "gear_up" if c.zone == "back_right" else ("gear_down" if c.zone == "back_left" else "gear_up")
        sig = c.signal(sp)
        if role is None and sig is not None and sig.kind == "pad" and sig.value in cat.system_pad.get(sp or "", ()):
            role = "system"
        if role is None and template is not None and c.id in template.system_controls:
            role = "system"
        if role is not None:
            reserved.append({"control_id": c.id, "as": role, "label": RESERVED_LABELS[role]})
            skip.add(c.id)
            continue
        if template is not None and c.id in template.only_in_games and game_id not in template.only_in_games[c.id]:
            skip.add(c.id)
            only_excluded.append(c.label)
    if only_excluded:
        games_words = ", ".join(
            sorted(
                {
                    cat.games[g].label
                    for c in wheel.controls
                    if template is not None
                    for g in template.only_in_games.get(c.id, ())
                    if g in cat.games
                }
            )
        )
        notes.append(
            f"Not used in {game_label}: {', '.join(only_excluded)}. "
            + cat.warnings["only_games"].format(games=games_words or "another game")
            + (" Use Test › Identify to check in F1 25." if game_id == "f1_25" else "")
        )
    slots = expand_slots(wheel, sp, skip)
    ctx.slots = slots

    # MFD on the D-pad: the first D-pad sending the D-pad (else the first D-pad, else funky directions)
    mfd_control: WheelControl | None = None
    if game is not None and game.mfd_on_dpad:
        cands = [c for c in wheel.controls if c.id not in skip and c.kind in ("dpad_hat", "funky_7way")]
        cands.sort(key=lambda c: (_dpad_rank(c, sp), wheel.controls.index(c)))
        mfd_control = cands[0] if cands else None

    # 5. fixed by the game, then what the driver keeps
    for fx in cat.fixed_by_game:
        if fx.game != game_id or wheel.template != fx.template:
            continue
        for fn, cid in fx.controls.items():
            wc = wheel.control(cid)
            if wc is None or fn not in rows:
                continue
            for s in slots:
                if s.control.id == cid:
                    ctx.used.add(s.key)
            colour = fx.colours.get(fn)
            text = (
                f"{game_label} sets the {colour}-ring stick itself, so Pitwall can't change it (which colour does "
                "what is community-reported)."
                if colour
                else fx.text
            )
            _emit(
                ctx,
                fn,
                "fixed",
                None,
                _fmt(cat.reasons["fixed:game"], fn=cat.label(fn), text=text),
                origin="game_fixed",
                control_id=cid,
            )
    ptt_kept: Assignment | None = None
    for a in kept:
        if a.function == PTT_FUNCTION:
            ptt_kept = a
            continue
        if a.function not in candidates or a.key in {p.assignment.key for p in ctx.placed}:
            continue
        wc = wheel.control(a.control_id)
        sref = next((s for s in slots if wc is not None and s.control.id == wc.id and s.slot == a.slot), None)
        label = wc.label if wc is not None else "a button"
        _emit(
            ctx,
            a.function,
            a.action,
            sref,
            _fmt(cat.reasons["kept"], fn=cat.label(a.function), ctl=label),
            origin="kept",
            control_id=a.control_id,
            slot_name=a.slot,
            check=a.check,
        )
        if sref is None and wc is not None and a.slot is not None:
            ctx.used.add((wc.id, a.slot))

    # 6. Talk to Pitwall
    if game is not None and game.button_path == "f1_butn":
        n = ptt_kept.udp_action if ptt_kept is not None and ptt_kept.udp_action else udp_action
        if ptt_kept is not None:
            wc = wheel.control(ptt_kept.control_id)
            ra = _emit(
                ctx,
                PTT_FUNCTION,
                "hold",
                None,
                _fmt(cat.reasons["kept"], fn="Talk to Pitwall", ctl=wc.label if wc else "your UDP Action button"),
                origin="kept",
                udp=n,
                control_id=ptt_kept.control_id,
                slot_name=ptt_kept.slot,
                check=ptt_kept.check,
            )
            if wc is not None and ptt_kept.slot:
                ctx.used.add((wc.id, ptt_kept.slot))
            ptt_cid = ra.assignment.control_id
        else:
            ptt_cid = _place_ptt(ctx, slots, n)
        ptt_ctl = wheel.control(ptt_cid)
        ctl_label = ptt_ctl.label if ptt_ctl is not None else None
        pitwall_ptt: dict[str, Any] = {
            "path": "udp_action",
            "udp_action": n,
            "control_id": ptt_cid,
            "text": (
                f"Hold {ctl_label} to talk to Pitwall: map it to UDP Action {n} in F1 25 "
                "(Controls > your wheel's preset > UDP Custom Actions)."
                if ctl_label
                else f"Map a spare button to UDP Action {n} in F1 25 to talk to Pitwall from the wheel."
            ),
        }
    else:
        pitwall_ptt = {
            "path": "screen",
            "text": cat.not_possible["wheel_ptt_no_telemetry"].replace("{game}", game_label),
        }

    # 6b. the MFD on its D-pad (also kept for the MFD when the preset does not list it)
    if mfd_control is not None:
        mfd_row = candidates.get(MFD_FUNCTION)
        if mfd_row is not None and MFD_FUNCTION in wanted_set and MFD_FUNCTION not in ctx.placed_fns:
            for need in needs_of(MFD_FUNCTION, mfd_row, cat, (0.0, 0)):
                if need.kind == "menu":
                    got = _best_menu(ctx, need, slots, True, only=mfd_control.id)
                    if got is not None:
                        reason = _fmt(cat.reasons["mfd:dpad"], ctl=mfd_control.label, game=game_label)
                        for d, s in zip(need.actions, got, strict=True):
                            _emit(ctx, MFD_FUNCTION, d, s, reason)
                elif need.actions == ("select",):
                    push = next((s for s in slots if s.control.id == mfd_control.id and s.slot == "push"), None)
                    if push is not None and push.key not in ctx.used:
                        _emit(
                            ctx,
                            MFD_FUNCTION,
                            "select",
                            push,
                            _fmt(cat.reasons["mfd:dpad"], ctl=mfd_control.label, game=game_label),
                        )
        if MFD_FUNCTION not in ctx.placed_fns:
            reserved.append({"control_id": mfd_control.id, "as": "mfd", "label": RESERVED_LABELS["mfd"]})
        for s in slots:
            if s.control.id == mfd_control.id and s.slot in DIRECTIONS:
                ctx.used.add(s.key)

    # 7. the rest, by priority
    order = {fn: i for i, fn in enumerate(wanted)}
    queue: list[Need] = []
    for fn in wanted:
        if fn in ctx.placed_fns and fn != MFD_FUNCTION:
            continue
        row = candidates[fn]
        if row is not None and row.binding == "mfd":
            continue
        prio = (-cat.freq_weight.get(cat.functions[fn].freq, 1.0), order[fn])
        for need in needs_of(fn, row, cat, prio):
            if any(p.assignment.key == f"{fn}.{need.actions[0]}" for p in ctx.placed):
                continue
            queue.append(need)
    queue.sort(key=lambda n: n.priority)
    leftovers: list[Need] = []
    for need in queue:
        if not _place(ctx, need, slots, allow_gs=False):
            leftovers.append(need)
    still: list[Need] = []
    for need in leftovers:  # the game's own shared button (F1: pit limiter with DRS) before game-specific controls
        if not _share(ctx, need):
            still.append(need)
    unplaced: list[dict[str, str]] = []
    for need in still:
        if not _place(ctx, need, slots, allow_gs=True):
            if any(u["function"] == need.function for u in unplaced):
                continue
            partly = need.function in ctx.placed_fns  # e.g. ignition placed, its starter (hold) not
            label = _action_label(cat, need.function, need.actions[0]) if partly else cat.label(need.function)
            if partly and need.actions[0] == "hold":
                label += " (hold)"
            unplaced.append({"function": need.function, "label": label, "text": _menu_text(ctx, need.function, label)})
    for fn, row in candidates.items():  # changed on the MFD pages: no button of its own
        if row is not None and row.binding == "mfd" and fn not in ctx.placed_fns:
            unplaced.append(
                {
                    "function": fn,
                    "label": cat.label(fn),
                    "text": _fmt(cat.reasons["mfd_binding"], fn=cat.label(fn), game=game_label),
                }
            )
    if game_id == "other":
        notes.append("Pitwall can't see your wheel in this game: check each button on track.")
    notes.append("Pitwall suggests where things go, never the values to use.")
    return Recommendation(
        game=game_id,
        platform=platform,
        wheel_id=wheel.id,
        preset=preset,
        driver_id=driver_id,
        catalogue_version=cat.version,
        assignments=tuple(ctx.placed),
        pitwall_ptt=pitwall_ptt,
        not_on_wheel=tuple(not_on_wheel),
        not_in_game=tuple(not_in_game),
        unplaced=tuple(unplaced),
        reserved=tuple(reserved),
        notes=tuple(notes),
    )


def _dpad_rank(c: WheelControl, sp: str | None) -> int:
    """MFD control preference: a D-pad that sends the pad's D-pad, then any D-pad, then funky directions."""
    sig = c.signal(sp)
    if c.kind == "dpad_hat":
        return 0 if sig is not None and sig.kind == "pad" else 1
    return 2


def _other_order(cat: Catalog, functions: list[str], preset: str) -> list[str]:
    """ "Other game": every ticked function by frequency (beginner: the six most frequent)."""
    order = sorted(
        (fn for fn in functions if fn in cat.functions and fn != PTT_FUNCTION),
        key=lambda fn: (-cat.freq_weight.get(cat.functions[fn].freq, 1.0), list(cat.functions).index(fn)),
    )
    return order[:6] if preset == "beginner" else order


def _share(ctx: _Ctx, need: Need) -> bool:
    """A single-action function the game puts on the same button as another (F1: pit limiter and DRS)."""
    row = ctx.rows.get(need.function)
    if row is None or need.kind != "single" or not row.shares_with:
        return False
    for other in row.shares_with:
        placed = [p for p in ctx.placed_fns.get(other, []) if p.assignment.control_id is not None]
        if len(placed) == 1:
            host = placed[0].assignment
            fn_label, other_label = ctx.cat.label(need.function), ctx.cat.label(other)
            reason = (
                ctx.cat.reasons["shared:f1_drs_pit"]
                if ctx.game is not None and ctx.game.id == "f1_25"
                else f"{fn_label} on the same control as {other_label}: the game shares it."
            )
            _emit(
                ctx, need.function, need.actions[0], None, _fmt(reason), control_id=host.control_id, slot_name=host.slot
            )
            return True
    return False


def _place_ptt(ctx: _Ctx, slots: Sequence[SlotRef], n: int) -> str | None:
    """A plain button whose signal on this platform is its own; thumb first; never an encoder, rotary switch,
    funky turn, gear paddle or a folded signal. Game-specific buttons only when nothing else is left."""
    best: tuple[tuple[float, int], SlotRef] | None = None
    for allow_gs in (False, True):
        for s in slots:
            if s.key in ctx.used or s.control.kind != "button" or s.slot != "press" or s.folded:
                continue
            if s.game_specific and not allow_gs:
                continue
            score = 10 + 2 * _reach_w(ctx.cat, s.control) * 3.0 + _penalty(ctx.cat, s)
            key = (-score, s.index)
            if best is None or key < best[0]:
                best = (key, s)
        if best is not None:
            break
    if best is None:
        return None
    s = best[1]
    reason_key = "ptt:f1" if s.control.effective_reach == "thumb" else "ptt:f1_far"
    _emit(ctx, PTT_FUNCTION, "hold", s, _fmt(ctx.cat.reasons[reason_key], ctl=s.control.label, n=n), udp=n)
    return s.control.id
