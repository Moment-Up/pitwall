"""Controls and button mapping: the driver's wheels, layouts and choices (SettingsStore section ``"controls"``).

Four layers (docs/controls.md): the physical control on the wheel or box (``WheelControl``), the signal it sends on
each platform (``Signal``, per ``SignalPlatform``), the game binding (an ``Assignment`` of a function's action to a
control slot) and what Pitwall can see (F1 25's ``BUTN`` bits or a telemetry effect, recorded as ``Assignment.check``).

Storage: one section in ``data/settings.json`` (no SQLite change), the same way the rig profile is stored::

    {"schema": 1, "wheels": [WheelDef], "layouts": [Layout], "household": DriverControls,
     "drivers": {"<driver_id>": DriverControls}, "updated_unix": 0}

* ``ControlsState.from_stored`` is lenient (like ``RigProfile.from_stored``): a bad wheel, layout, control or
  assignment is skipped and logged, never hiding the rest. A missing section means defaults; nothing is written on
  start-up. v0.2.1 keeps and ignores the unknown section, so a downgrade is safe.
* API input goes through the strict parsers (``parse_wheel`` / ``parse_layout``), which raise
  ``ControlsValidationError`` with a plain-English message (422).
* Every wheel and layout carries ``rev``: a PUT must send the rev it read (``StaleRevision`` -> 409), so two iPads
  editing the same layout cannot silently overwrite each other. ``write_lock`` guards read-modify-write.

Frozen slots dataclasses; JSON names are the wire names of the API contract (snake_case).
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast, get_args

log = logging.getLogger(__name__)

SECTION = "controls"
SCHEMA = 1
write_lock = threading.Lock()  # read-modify-write of the section (two iPads saving at once)

# ---------------------------------------------------------------------------------------------- vocabulary
PlatformId = Literal["ps5", "ps4", "xbox", "pc"]
SignalPlatform = Literal["ps", "xbox", "pc"]
Evidence = Literal["V", "A", "U", "D", "H", "seen"]
Preset = Literal["beginner", "advanced"]
Origin = Literal["recommended", "driver", "game_fixed", "kept", "game_default"]
CheckResult = Literal["detected", "effect_seen", "other_bits", "not_seen"]

PLATFORMS: tuple[str, ...] = get_args(PlatformId)
SIGNAL_PLATFORMS: tuple[str, ...] = get_args(SignalPlatform)
EVIDENCE: tuple[str, ...] = get_args(Evidence)
PRESETS: tuple[str, ...] = get_args(Preset)
ORIGINS: tuple[str, ...] = get_args(Origin)
CHECK_RESULTS: tuple[str, ...] = get_args(CheckResult)
SHAPES: tuple[str, ...] = ("round", "d", "formula", "box")
PART_KINDS: tuple[str, ...] = ("rim", "hub", "button_box", "wheel_bundle")
MPS_MODES: tuple[str, ...] = ("enc", "pulse", "constant", "auto", "unknown")
SIGNAL_KINDS: tuple[str, ...] = (
    "pad",
    "game_specific",
    "folded",
    "hid_button",
    "hid_hat",
    "hid_axis",
    "none",
    "unknown",
)
REACHES: tuple[str, ...] = ("thumb", "finger", "stretch", "hand_off", "unknown")
# Slots each control kind can have (multi_position adds pos_1..pos_N in PULSE/CONST mode).
KIND_SLOTS: Mapping[str, tuple[str, ...]] = {
    "button": ("press",),
    "shift_paddle": ("press",),
    "toggle_latching": ("on", "off"),
    "toggle_momentary": ("up", "down"),
    "encoder": ("cw", "ccw", "push"),
    "multi_position": ("cw", "ccw"),
    "funky_7way": ("up", "down", "left", "right", "push", "cw", "ccw"),
    "dpad_hat": ("up", "down", "left", "right", "push"),
    "thumbstick": ("up", "down", "left", "right", "push"),
    "analogue_paddle": ("axis",),
    "mode_selector": (),
    "device_menu": (),
    "virtual_layer": (),
}
KINDS: tuple[str, ...] = tuple(KIND_SLOTS)
ALL_SLOTS: frozenset[str] = frozenset(s for slots in KIND_SLOTS.values() for s in slots)
PUSH_OPTIONAL = frozenset({"encoder", "dpad_hat", "thumbstick"})  # "push" only when the control has one
ZONE_REACH: Mapping[str, str] = {
    "left_thumb": "thumb",
    "right_thumb": "thumb",
    "left_top": "thumb",
    "right_top": "thumb",
    "back_left": "finger",
    "back_right": "finger",
    "left_lower": "stretch",
    "right_lower": "stretch",
    "centre_top": "stretch",
    "centre": "stretch",
    "centre_bottom": "stretch",
    "box": "hand_off",
    "hub": "hand_off",
    "unplaced": "unknown",
}
ZONES: tuple[str, ...] = tuple(ZONE_REACH)
_POS_SLOT = re.compile(r"^pos_([1-9]\d?)$")
_WHEEL_ID = re.compile(r"^w_[0-9a-f]{8}$")
_LAYOUT_ID = re.compile(r"^l_[0-9a-f]{8}$")
_CONTROL_ID = re.compile(r"^[a-z0-9_]{1,40}$")
_GAME_ID = re.compile(r"^[a-z0-9_]{1,32}$")

# ---------------------------------------------------------------------------------------------- caps (spec 8)
MAX_WHEELS = 12
MAX_CONTROLS = 96
MAX_LAYOUTS = 32
MAX_ASSIGNMENTS = 48
MAX_NAME = 40
MAX_LABEL = 32
MAX_NOTE = 200
MAX_POSITIONS = 24
MAX_DETAIL = 120  # a stored test result's detail
UDP_ACTIONS = range(1, 13)


class ControlsValidationError(ValueError):
    """Input that does not fit the controls model (shown to the driver as a plain-English 422)."""


class StaleRevision(Exception):
    """A PUT that sent an older ``rev`` than the stored one (409): someone else saved in between."""


class NotFound(KeyError):
    """An unknown wheel, layout or control id (404)."""


def signal_platform(platform: str | None) -> SignalPlatform | None:
    """PS4 and PS5 wheels report the same PlayStation set."""
    if platform in ("ps5", "ps4"):
        return "ps"
    if platform in ("xbox", "pc"):
        return cast(SignalPlatform, platform)
    return None


def new_wheel_id() -> str:
    return "w_" + secrets.token_hex(4)


def new_layout_id() -> str:
    return "l_" + secrets.token_hex(4)


def is_wheel_id(v: object) -> bool:
    return isinstance(v, str) and bool(_WHEEL_ID.match(v))


def is_layout_id(v: object) -> bool:
    return isinstance(v, str) and bool(_LAYOUT_ID.match(v))


def valid_slot(kind: str, slot: str, positions: int | None = None) -> bool:
    if slot in KIND_SLOTS.get(kind, ()):
        return True
    m = _POS_SLOT.match(slot)
    return kind == "multi_position" and m is not None and positions is not None and 1 <= int(m.group(1)) <= positions


# ---------------------------------------------------------------------------------------------- small readers
def _err(path: str, msg: str) -> ControlsValidationError:
    return ControlsValidationError(f"{path}: {msg}" if path else msg)


def _obj(v: object, path: str) -> Mapping[str, Any]:
    if not isinstance(v, Mapping):
        raise _err(path, "expected an object")
    return v


def _text(v: object, path: str, max_len: int, *, allow_empty: bool = False) -> str:
    if not isinstance(v, str):
        raise _err(path, "expected text")
    s = v.strip()
    if not s and not allow_empty:
        raise _err(path, "must not be empty")
    if len(s) > max_len:
        raise _err(path, f"is longer than {max_len} characters")
    return s


def _opt_text(v: object, path: str, max_len: int) -> str | None:
    return None if v is None else (_text(v, path, max_len, allow_empty=True) or None)


def _choice(v: object, options: Sequence[str], path: str) -> str:
    if not isinstance(v, str) or v not in options:
        raise _err(path, f"{v!r} is not one of {', '.join(options)}")
    return v


def _int(v: object, path: str, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise _err(path, f"expected a whole number from {lo} to {hi}")
    return v


def clip(text: str, max_len: int = MAX_DETAIL) -> str:
    """At most ``max_len`` characters, ending in "…" when cut (a stored detail must never be dropped for length)."""
    text = text.strip()
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def _num(v: object, default: float = 0.0) -> float:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else default


def _texts(v: object, path: str, max_len: int = 200, max_items: int = 64) -> tuple[str, ...]:
    if v is None:
        return ()
    if not isinstance(v, list) or len(v) > max_items:
        raise _err(path, f"expected a list of at most {max_items} texts")
    return tuple(_text(x, f"{path}[{i}]", max_len) for i, x in enumerate(v))


# ---------------------------------------------------------------------------------------------- signals
@dataclass(frozen=True, slots=True)
class Seen:
    """When Pitwall's F1 25 button test saw this signal (BUTN bit names). Still not "validated"."""

    t_unix: float
    bits: tuple[str, ...]
    game: str = "f1_25"
    platform: str = "ps5"

    def to_dict(self) -> dict[str, Any]:
        return {"t_unix": self.t_unix, "bits": list(self.bits), "game": self.game, "platform": self.platform}


@dataclass(frozen=True, slots=True)
class Signal:
    """What a control sends on one platform. ``per_slot`` overrides the value per slot (encoder cw/ccw); a per-slot
    value written ``"<kind>:<value>"`` also overrides the kind for that slot (a funky switch whose directions are the
    D-pad but whose push is game-specific: ``{"up": "pad:dpad_up", "push": "GSB 1"}``). ``"unknown:"`` means not
    known; ``"none:"`` means that slot sends nothing."""

    kind: str
    value: str | None = None
    per_slot: Mapping[str, str] = field(default_factory=dict)
    evidence: Evidence = "U"
    source_ids: tuple[str, ...] = ()
    seen: Seen | None = None

    def slot(self, slot: str | None) -> tuple[str, str | None]:
        """(kind, value) for one slot, applying ``per_slot``."""
        raw = self.per_slot.get(slot) if slot is not None else None
        if raw is None:
            return self.kind, self.value
        head, sep, tail = raw.partition(":")
        if sep and head in SIGNAL_KINDS:
            return head, (tail or None)
        return self.kind, raw

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "value": self.value,
            "evidence": self.evidence,
            "source_ids": list(self.source_ids),
        }
        if self.per_slot:
            out["per_slot"] = dict(self.per_slot)
        out["seen"] = None if self.seen is None else self.seen.to_dict()
        return out


UNKNOWN_SIGNAL = Signal("unknown", None, {}, "H", ())


def parse_signal(raw: object, path: str, *, default_evidence: Evidence = "H") -> Signal:
    d = _obj(raw, path)
    kind = _choice(d.get("kind"), SIGNAL_KINDS, f"{path}.kind")
    value = d.get("value")
    if value is not None and not isinstance(value, str | int):
        raise _err(f"{path}.value", "expected text or a number")
    val = None if value is None else _text(str(value), f"{path}.value", 60, allow_empty=True) or None
    per_raw = d.get("per_slot") or {}
    per = _obj(per_raw, f"{path}.per_slot")
    per_slot: dict[str, str] = {}
    for k, v in per.items():
        if not isinstance(k, str) or not (k in ALL_SLOTS or _POS_SLOT.match(k)):
            raise _err(f"{path}.per_slot", f"{k!r} is not a slot")
        per_slot[k] = _text(v, f"{path}.per_slot.{k}", 60, allow_empty=True)
    ev = d.get("evidence", default_evidence)
    evidence = cast(Evidence, _choice(ev, EVIDENCE, f"{path}.evidence"))
    src = _texts(d.get("source_ids"), f"{path}.source_ids", 64, 16)
    seen_raw = d.get("seen")
    seen = None
    if seen_raw is not None:
        s = _obj(seen_raw, f"{path}.seen")
        seen = Seen(
            _num(s.get("t_unix")),
            _texts(s.get("bits"), f"{path}.seen.bits", 40, 32),
            str(s.get("game") or "f1_25")[:32],
            _choice(s.get("platform", "ps5"), PLATFORMS, f"{path}.seen.platform"),
        )
    return Signal(kind, val, per_slot, evidence, src, seen)


# ---------------------------------------------------------------------------------------------- wheels
@dataclass(frozen=True, slots=True)
class WheelPart:
    id: str
    kind: str
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "name": self.name}


@dataclass(frozen=True, slots=True)
class WheelControl:
    id: str
    part: str
    kind: str
    label: str
    zone: str
    order: int = 0
    reach: str | None = None  # None: from the zone
    push: bool = False
    positions: int | None = None
    mps_mode: str | None = None
    signals: Mapping[str, Signal] = field(default_factory=dict)
    evidence: Evidence = "H"
    note: str = ""

    @property
    def effective_reach(self) -> str:
        return self.reach or ZONE_REACH.get(self.zone, "unknown")

    def slots(self) -> tuple[str, ...]:
        """The slots this control actually has (push only when it has one; rotary-switch positions in PULSE/CONST)."""
        base = KIND_SLOTS.get(self.kind, ())
        out = [s for s in base if s != "push" or self.push or self.kind not in PUSH_OPTIONAL]
        if self.kind == "funky_7way" and not self.push:
            out = [s for s in out if s != "push"]
        if self.kind == "multi_position" and self.positions and self.mps_mode in ("pulse", "constant"):
            out = [f"pos_{i}" for i in range(1, self.positions + 1)]
        return tuple(out)

    def signal(self, platform: str | None) -> Signal | None:
        return None if platform is None else self.signals.get(platform)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "part": self.part,
            "kind": self.kind,
            "label": self.label,
            "zone": self.zone,
            "order": self.order,
            "reach": self.reach,
            "push": self.push,
            "positions": self.positions,
            "mps_mode": self.mps_mode,
            "signals": {p: s.to_dict() for p, s in sorted(self.signals.items())},
            "evidence": self.evidence,
            "note": self.note,
        }


def parse_control(raw: object, path: str, parts: Iterable[str], *, default_evidence: Evidence = "H") -> WheelControl:
    d = _obj(raw, path)
    cid = d.get("id")
    if not isinstance(cid, str) or not _CONTROL_ID.match(cid):
        raise _err(f"{path}.id", "expected a short id of lower-case letters, digits and _")
    part_ids = list(parts)
    part = d.get("part") or (part_ids[0] if part_ids else "rim")
    if part_ids and part not in part_ids:
        raise _err(f"{path}.part", f"{part!r} is not a part of this wheel")
    kind = _choice(d.get("kind"), KINDS, f"{path}.kind")
    label = _text(d.get("label"), f"{path}.label", MAX_LABEL)
    zone = _choice(d.get("zone", "unplaced"), ZONES, f"{path}.zone")
    order = _int(d.get("order", 0), f"{path}.order", 0, 999)
    reach_raw = d.get("reach")
    reach = None if reach_raw is None else _choice(reach_raw, REACHES, f"{path}.reach")
    push = bool(d.get("push", False))
    pos_raw = d.get("positions")
    positions = None if pos_raw is None else _int(pos_raw, f"{path}.positions", 2, MAX_POSITIONS)
    if kind != "multi_position" and positions is not None and kind != "encoder":
        raise _err(f"{path}.positions", "only rotary switches and dials have positions")
    mps_raw = d.get("mps_mode")
    mps_mode = None if mps_raw is None else _choice(mps_raw, MPS_MODES, f"{path}.mps_mode")
    sig_raw = _obj(d.get("signals") or {}, f"{path}.signals")
    signals: dict[str, Signal] = {}
    for p, s in sig_raw.items():
        _choice(p, SIGNAL_PLATFORMS, f"{path}.signals")
        sig = parse_signal(s, f"{path}.signals.{p}", default_evidence=default_evidence)
        for slot in sig.per_slot:
            if not valid_slot(kind, slot, positions):
                raise _err(f"{path}.signals.{p}.per_slot", f"{slot!r} is not a slot of a {kind}")
        signals[str(p)] = sig
    evidence = cast(Evidence, _choice(d.get("evidence", default_evidence), EVIDENCE, f"{path}.evidence"))
    note = _text(d.get("note") or "", f"{path}.note", MAX_NOTE, allow_empty=True)
    return WheelControl(
        cid, str(part), kind, label, zone, order, reach, push, positions, mps_mode, signals, evidence, note
    )


@dataclass(frozen=True, slots=True)
class WheelDef:
    id: str
    rev: int
    name: str
    template: str | None
    template_version: str | None
    shape: str
    platforms: tuple[str, ...]
    parts: tuple[WheelPart, ...]
    controls: tuple[WheelControl, ...]
    created_unix: float = 0.0
    updated_unix: float = 0.0

    def control(self, cid: str | None) -> WheelControl | None:
        return None if cid is None else next((c for c in self.controls if c.id == cid), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rev": self.rev,
            "name": self.name,
            "template": self.template,
            "template_version": self.template_version,
            "shape": self.shape,
            "platforms": list(self.platforms),
            "parts": [p.to_dict() for p in self.parts],
            "controls": [c.to_dict() for c in self.controls],
            "created_unix": self.created_unix,
            "updated_unix": self.updated_unix,
        }


def parse_wheel(raw: object, path: str = "wheel", *, default_evidence: Evidence = "H") -> WheelDef:
    """Strict: the first problem raises ``ControlsValidationError``."""
    d = _obj(raw, path)
    wid = d.get("id")
    if not is_wheel_id(wid):
        raise _err(f"{path}.id", "expected w_ and 8 hex digits")
    rev = _int(d.get("rev", 1), f"{path}.rev", 0, 10**9)
    name = _text(d.get("name"), f"{path}.name", MAX_NAME)
    template = _opt_text(d.get("template"), f"{path}.template", 64)
    template_version = _opt_text(d.get("template_version"), f"{path}.template_version", 32)
    shape = _choice(d.get("shape", "round"), SHAPES, f"{path}.shape")
    plats = d.get("platforms") or []
    if not isinstance(plats, list):
        raise _err(f"{path}.platforms", "expected a list")
    platforms = tuple(dict.fromkeys(_choice(p, SIGNAL_PLATFORMS, f"{path}.platforms") for p in plats))
    parts_raw = d.get("parts") or [{"id": "rim", "kind": "rim", "name": "Wheel"}]
    if not isinstance(parts_raw, list) or not 1 <= len(parts_raw) <= 8:
        raise _err(f"{path}.parts", "expected 1 to 8 parts")
    parts: list[WheelPart] = []
    for i, p in enumerate(parts_raw):
        pd = _obj(p, f"{path}.parts[{i}]")
        pid = pd.get("id")
        if not isinstance(pid, str) or not _CONTROL_ID.match(pid):
            raise _err(f"{path}.parts[{i}].id", "expected a short id")
        parts.append(
            WheelPart(
                pid,
                _choice(pd.get("kind", "rim"), PART_KINDS, f"{path}.parts[{i}].kind"),
                _text(pd.get("name") or pid, f"{path}.parts[{i}].name", MAX_NAME),
            )
        )
    if len({p.id for p in parts}) != len(parts):
        raise _err(f"{path}.parts", "part ids must be different")
    ctrl_raw = d.get("controls") or []
    if not isinstance(ctrl_raw, list):
        raise _err(f"{path}.controls", "expected a list")
    if len(ctrl_raw) > MAX_CONTROLS:
        raise _err(f"{path}.controls", f"at most {MAX_CONTROLS} controls on one wheel")
    controls = tuple(
        parse_control(c, f"{path}.controls[{i}]", [p.id for p in parts], default_evidence=default_evidence)
        for i, c in enumerate(ctrl_raw)
    )
    ids = [c.id for c in controls]
    if len(set(ids)) != len(ids):
        dup = next(x for x in ids if ids.count(x) > 1)
        raise _err(f"{path}.controls", f"two controls have the id {dup!r}")
    return WheelDef(
        str(wid),
        rev,
        name,
        template,
        template_version,
        shape,
        platforms,
        tuple(parts),
        controls,
        _num(d.get("created_unix")),
        _num(d.get("updated_unix")),
    )


# ---------------------------------------------------------------------------------------------- layouts
@dataclass(frozen=True, slots=True)
class Check:
    """The last live test result of one assignment (only live presses are stored)."""

    result: CheckResult
    t_unix: float
    detail: str
    origin: str = "live"

    def to_dict(self) -> dict[str, Any]:
        return {"result": self.result, "t_unix": self.t_unix, "detail": self.detail, "origin": self.origin}


@dataclass(frozen=True, slots=True)
class Assignment:
    key: str  # "<function>.<action>"
    function: str
    action: str
    control_id: str | None
    slot: str | None
    udp_action: int | None = None
    origin: Origin = "recommended"
    check: Check | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "function": self.function,
            "action": self.action,
            "control_id": self.control_id,
            "slot": self.slot,
            "udp_action": self.udp_action,
            "origin": self.origin,
            "check": None if self.check is None else self.check.to_dict(),
        }


_KEY = re.compile(r"^([a-z0-9_]{1,32})\.([a-z0-9_]{1,16})$")


def parse_assignment(raw: object, path: str, *, lenient: bool = False) -> Assignment:
    """Strict for API input; ``lenient`` (stored data) shortens an over-long test detail instead of failing."""
    d = _obj(raw, path)
    function = d.get("function")
    action = d.get("action")
    if not isinstance(function, str) or not _GAME_ID.match(function):
        raise _err(f"{path}.function", "expected a function id")
    if not isinstance(action, str) or not re.match(r"^[a-z0-9_]{1,16}$", action):
        raise _err(f"{path}.action", "expected an action id")
    key = d.get("key") or f"{function}.{action}"
    if key != f"{function}.{action}":
        raise _err(f"{path}.key", "must be <function>.<action>")
    cid = d.get("control_id")
    if cid is not None and (not isinstance(cid, str) or not _CONTROL_ID.match(cid)):
        raise _err(f"{path}.control_id", "expected a control id or null")
    slot = d.get("slot")
    if slot is not None and (not isinstance(slot, str) or not re.match(r"^[a-z0-9_]{1,10}$", slot)):
        raise _err(f"{path}.slot", "expected a slot or null")
    udp_raw = d.get("udp_action")
    udp = None if udp_raw is None else _int(udp_raw, f"{path}.udp_action", 1, 12)
    origin = cast(Origin, _choice(d.get("origin", "driver"), ORIGINS, f"{path}.origin"))
    check = None
    if d.get("check") is not None:
        c = _obj(d["check"], f"{path}.check")
        detail_raw = c.get("detail") or ""
        if lenient and isinstance(detail_raw, str):
            detail_raw = clip(detail_raw)
        check = Check(
            cast(CheckResult, _choice(c.get("result"), CHECK_RESULTS, f"{path}.check.result")),
            _num(c.get("t_unix")),
            _text(detail_raw, f"{path}.check.detail", MAX_DETAIL, allow_empty=True),
            "live",
        )
    return Assignment(key, function, action, cid, slot, udp, origin, check)


@dataclass(frozen=True, slots=True)
class Layout:
    id: str
    rev: int
    game: str  # controls game id, or "other"
    game_name: str | None
    platform: str
    wheel_id: str
    owner: str | int  # "household" or a driver id
    preset: Preset
    other_functions: tuple[str, ...] | None
    assignments: tuple[Assignment, ...]
    created_unix: float = 0.0
    updated_unix: float = 0.0

    @property
    def slot_key(self) -> str:
        return f"{self.game}:{self.platform}"

    def assignment(self, key: str) -> Assignment | None:
        return next((a for a in self.assignments if a.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rev": self.rev,
            "game": self.game,
            "game_name": self.game_name,
            "platform": self.platform,
            "wheel_id": self.wheel_id,
            "owner": self.owner,
            "preset": self.preset,
            "other_functions": None if self.other_functions is None else list(self.other_functions),
            "assignments": [a.to_dict() for a in self.assignments],
            "created_unix": self.created_unix,
            "updated_unix": self.updated_unix,
        }


def parse_owner(v: object, path: str = "owner") -> str | int:
    if v == "household" or v is None:
        return "household"
    if isinstance(v, int) and not isinstance(v, bool) and v > 0:
        return v
    if isinstance(v, str) and v.isdigit() and int(v) > 0:
        return int(v)
    raise _err(path, 'expected "household" or a driver id')


def parse_layout(raw: object, path: str = "layout") -> Layout:
    d = _obj(raw, path)
    lid = d.get("id")
    if not is_layout_id(lid):
        raise _err(f"{path}.id", "expected l_ and 8 hex digits")
    game = d.get("game")
    if not isinstance(game, str) or not _GAME_ID.match(game):
        raise _err(f"{path}.game", "expected a game id")
    game_name = _opt_text(d.get("game_name"), f"{path}.game_name", MAX_NAME)
    if game == "other" and not game_name:
        raise _err(f"{path}.game_name", "name the game")
    platform = _choice(d.get("platform"), PLATFORMS, f"{path}.platform")
    wheel_id = d.get("wheel_id")
    if not is_wheel_id(wheel_id):
        raise _err(f"{path}.wheel_id", "expected a wheel id")
    owner = parse_owner(d.get("owner"), f"{path}.owner")
    preset = cast(Preset, _choice(d.get("preset", "advanced"), PRESETS, f"{path}.preset"))
    of_raw = d.get("other_functions")
    other_functions = None if of_raw is None else _texts(of_raw, f"{path}.other_functions", 32, 40)
    asg_raw = d.get("assignments") or []
    if not isinstance(asg_raw, list) or len(asg_raw) > MAX_ASSIGNMENTS:
        raise _err(f"{path}.assignments", f"at most {MAX_ASSIGNMENTS} assignments in one layout")
    assignments = tuple(parse_assignment(a, f"{path}.assignments[{i}]") for i, a in enumerate(asg_raw))
    keys = [a.key for a in assignments]
    if len(set(keys)) != len(keys):
        dup = next(k for k in keys if keys.count(k) > 1)
        raise _err(f"{path}.assignments", f"{dup} is assigned twice")
    return Layout(
        str(lid),
        _int(d.get("rev", 1), f"{path}.rev", 0, 10**9),
        game,
        game_name,
        platform,
        str(wheel_id),
        owner,
        preset,
        other_functions,
        assignments,
        _num(d.get("created_unix")),
        _num(d.get("updated_unix")),
    )


def check_layout_against_wheel(layout: Layout, wheel: WheelDef) -> None:
    """Every control id and slot of the layout exists on its wheel (strict; 422). A slot must be one the control has
    now (``WheelControl.slots``: a push only when the control has one, rotary positions in their modes)."""
    for a in layout.assignments:
        if a.udp_action is not None and layout.game != "f1_25":
            raise ControlsValidationError(f"{a.key}: UDP Actions exist only in F1 25")
        if a.control_id is None:
            if a.slot is not None:
                raise ControlsValidationError(f"{a.key}: a slot needs a control")
            continue
        c = wheel.control(a.control_id)
        if c is None:
            raise ControlsValidationError(f"{a.key}: {wheel.name} has no control {a.control_id!r}")
        if a.slot is not None and a.slot not in c.slots():
            raise ControlsValidationError(f"{a.key}: {a.slot!r} is not a slot of {c.label}")


# ---------------------------------------------------------------------------------------------- per-driver choices
@dataclass(frozen=True, slots=True)
class DriverControls:
    wheel_id: str | None = None
    preset: Preset | None = None
    layouts: Mapping[str, str] = field(default_factory=dict)  # "<game>:<platform>" -> layout id

    def to_dict(self) -> dict[str, Any]:
        return {"wheel_id": self.wheel_id, "preset": self.preset, "layouts": dict(sorted(self.layouts.items()))}


def _parse_driver_controls(raw: object, path: str) -> DriverControls:
    d = _obj(raw, path)
    wid = d.get("wheel_id")
    preset_raw = d.get("preset")
    layouts_raw = _obj(d.get("layouts") or {}, f"{path}.layouts")
    layouts = {str(k): str(v) for k, v in layouts_raw.items() if isinstance(k, str) and ":" in k and is_layout_id(v)}
    return DriverControls(
        str(wid) if is_wheel_id(wid) else None,
        cast(Preset, preset_raw) if preset_raw in PRESETS else None,
        layouts,
    )


# ---------------------------------------------------------------------------------------------- the section
@dataclass(frozen=True, slots=True)
class ControlsState:
    wheels: tuple[WheelDef, ...] = ()
    layouts: tuple[Layout, ...] = ()
    household: DriverControls = field(default_factory=DriverControls)
    drivers: Mapping[str, DriverControls] = field(default_factory=dict)  # key: str(driver_id)
    updated_unix: float = 0.0

    def wheel(self, wid: str | None) -> WheelDef | None:
        return None if wid is None else next((w for w in self.wheels if w.id == wid), None)

    def layout(self, lid: str | None) -> Layout | None:
        return None if lid is None else next((x for x in self.layouts if x.id == lid), None)

    def driver(self, driver_id: int | str | None) -> DriverControls:
        if driver_id is None:
            return DriverControls()
        return self.drivers.get(str(driver_id), DriverControls())

    def layout_for(self, driver_id: int | str | None, game: str, platform: str) -> Layout | None:
        """The driver's layout for this game and platform, else the household's, else None."""
        key = f"{game}:{platform}"
        for choice in (self.driver(driver_id), self.household):
            lay = self.layout(choice.layouts.get(key))
            if lay is not None:
                return lay
        return None

    def layouts_using(self, wheel_id: str) -> list[Layout]:
        return [x for x in self.layouts if x.wheel_id == wheel_id]

    def to_section(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "wheels": [w.to_dict() for w in self.wheels],
            "layouts": [x.to_dict() for x in self.layouts],
            "household": self.household.to_dict(),
            "drivers": {k: v.to_dict() for k, v in sorted(self.drivers.items())},
            "updated_unix": self.updated_unix,
        }

    @classmethod
    def from_stored(cls, raw: Mapping[str, Any] | None) -> ControlsState:
        """Lenient: a bad wheel, layout or driver entry is skipped (logged); the rest is kept."""
        if not raw:
            return cls()
        if raw.get("schema") not in (None, SCHEMA):
            log.warning("controls: unknown section schema %r; reading what this version understands", raw.get("schema"))
        wheels = _lenient(raw.get("wheels"), lambda x, p: _lenient_wheel(x, p), "wheels", MAX_WHEELS)
        ids = set()
        uniq_w: list[WheelDef] = []
        for w in wheels:
            if w.id not in ids:
                ids.add(w.id)
                uniq_w.append(w)
        layouts = _lenient(raw.get("layouts"), lambda x, p: _lenient_layout(x, p), "layouts", MAX_LAYOUTS)
        lids = set()
        uniq_l: list[Layout] = []
        for lay in layouts:
            if lay.id not in lids and lay.wheel_id in ids:
                lids.add(lay.id)
                uniq_l.append(lay)
            elif lay.wheel_id not in ids:
                log.warning("controls: layout %s refers to a missing wheel %s; skipped", lay.id, lay.wheel_id)
        household = DriverControls()
        try:
            household = _parse_driver_controls(raw.get("household") or {}, "household")
        except ControlsValidationError as e:
            log.warning("controls: ignoring stored household choices (%s)", e)
        drivers: dict[str, DriverControls] = {}
        draw = raw.get("drivers")
        if isinstance(draw, Mapping):
            for k, v in draw.items():
                if not (isinstance(k, str) and k.isdigit()):
                    continue
                try:
                    drivers[k] = _parse_driver_controls(v, f"drivers.{k}")
                except ControlsValidationError as e:
                    log.warning("controls: ignoring stored choices of driver %s (%s)", k, e)
        return cls(tuple(uniq_w), tuple(uniq_l), household, drivers, _num(raw.get("updated_unix")))

    # -------------------------------------------------------------- edits (return a new state)
    def with_wheel(self, wheel: WheelDef) -> ControlsState:
        exists = any(w.id == wheel.id for w in self.wheels)
        if not exists and len(self.wheels) >= MAX_WHEELS:
            raise ControlsValidationError(f"at most {MAX_WHEELS} wheels: delete one first")
        wheels = tuple(wheel if w.id == wheel.id else w for w in self.wheels) if exists else (*self.wheels, wheel)
        return replace(self, wheels=wheels)

    def without_wheel(self, wid: str) -> ControlsState:
        drivers = {k: replace(v, wheel_id=None) if v.wheel_id == wid else v for k, v in self.drivers.items()}
        hh = replace(self.household, wheel_id=None) if self.household.wheel_id == wid else self.household
        return replace(self, wheels=tuple(w for w in self.wheels if w.id != wid), drivers=drivers, household=hh)

    def with_layout(self, layout: Layout) -> ControlsState:
        exists = any(x.id == layout.id for x in self.layouts)
        if not exists and len(self.layouts) >= MAX_LAYOUTS:
            raise ControlsValidationError(f"at most {MAX_LAYOUTS} layouts: delete one first")
        layouts = tuple(layout if x.id == layout.id else x for x in self.layouts) if exists else (*self.layouts, layout)
        return replace(self, layouts=layouts)

    def without_layout(self, lid: str) -> ControlsState:
        def drop(dc: DriverControls) -> DriverControls:
            return replace(dc, layouts={k: v for k, v in dc.layouts.items() if v != lid})

        return replace(
            self,
            layouts=tuple(x for x in self.layouts if x.id != lid),
            household=drop(self.household),
            drivers={k: drop(v) for k, v in self.drivers.items()},
        )

    def with_owner_choice(self, layout: Layout) -> ControlsState:
        """Point the layout's owner (household or the driver) at it for its game and platform."""
        if layout.owner == "household":
            hh = replace(self.household, layouts={**self.household.layouts, layout.slot_key: layout.id})
            return replace(self, household=hh)
        key = str(layout.owner)
        cur = self.driver(key)
        return replace(
            self, drivers={**self.drivers, key: replace(cur, layouts={**cur.layouts, layout.slot_key: layout.id})}
        )

    def with_driver(self, driver_id: int | str, dc: DriverControls) -> ControlsState:
        return replace(self, drivers={**self.drivers, str(driver_id): dc})


def _lenient[T](raw: object, parse: Callable[[object, str], T | None], what: str, cap: int) -> list[T]:
    if not isinstance(raw, list):
        return []
    out: list[T] = []
    for i, item in enumerate(raw[: cap * 2]):
        got = parse(item, f"{what}[{i}]")
        if got is not None:
            out.append(got)
    if len(out) > cap:
        log.warning("controls: more than %d %s stored; the rest are ignored", cap, what)
    return out[:cap]


def _lenient_wheel(raw: object, path: str) -> WheelDef | None:
    """A stored wheel: bad controls are dropped one by one; a wheel without a usable id or name is skipped."""
    try:
        d = dict(_obj(raw, path))
        ctrls = d.get("controls")
        good: list[Any] = []
        if isinstance(ctrls, list):
            parts = d.get("parts") or [{"id": "rim"}]
            part_ids = [p.get("id") for p in parts if isinstance(p, Mapping)] if isinstance(parts, list) else ["rim"]
            seen: set[str] = set()
            for i, c in enumerate(ctrls[:MAX_CONTROLS]):
                try:
                    pc = parse_control(c, f"{path}.controls[{i}]", [str(x) for x in part_ids])
                except ControlsValidationError as e:
                    log.warning("controls: skipping a stored control (%s)", e)
                    continue
                if pc.id not in seen:
                    seen.add(pc.id)
                    good.append(c)
        d["controls"] = good
        return parse_wheel(d, path)
    except ControlsValidationError as e:
        log.warning("controls: skipping a stored wheel (%s)", e)
        return None


def _lenient_layout(raw: object, path: str) -> Layout | None:
    try:
        d = dict(_obj(raw, path))
        asg = d.get("assignments")
        good: list[Any] = []
        keys: set[str] = set()
        if isinstance(asg, list):
            for i, a in enumerate(asg[:MAX_ASSIGNMENTS]):
                try:
                    pa = parse_assignment(a, f"{path}.assignments[{i}]", lenient=True)
                except ControlsValidationError as e:
                    log.warning("controls: skipping a stored assignment (%s)", e)
                    continue
                if pa.key not in keys:
                    keys.add(pa.key)
                    good.append(pa.to_dict())
        d["assignments"] = good
        return parse_layout(d, path)
    except ControlsValidationError as e:
        log.warning("controls: skipping a stored layout (%s)", e)
        return None


# ---------------------------------------------------------------------------------------------- store access
def load_state(store: Any) -> ControlsState:
    return ControlsState.from_stored(store.get(SECTION))


def save_state(store: Any, state: ControlsState) -> ControlsState:
    """Write the whole section (the first save creates it). Callers hold ``write_lock``."""
    out = replace(state, updated_unix=time.time())
    store.replace(SECTION, out.to_section())
    return out


def bump(rev: int) -> int:
    return rev + 1
