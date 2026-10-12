"""Race calls as radio messages for the ``RadioScheduler`` (the radio hub's side of a ``race_call`` live note).

``race_message`` applies the seated driver's preferences, then maps the call onto the one radio policy:

1. a group the driver switched off (``drivers.RadioCallPrefs``) gives None; the red flag ignores the toggles (it comes
   as an urgent note anyway, ``voice.urgent``);
2. ``defer_to_strategy_detail`` calls (the car ahead pitting) give None at detailed intensity for a driver without
   simple wording: they hear strategy's richer neighbour call instead;
3. ``audience: "experienced"`` calls (INFO: a rival's fastest lap, a far retirement) give None for simple wording,
   and so does a lost place (``position_change`` down): a beginner hears places gained, the lap-one position and the
   result, never a running count of places lost;
4. text: ``text_simple`` for simple wording when the call has it, else ``text``; speech: ``to_speech`` of the speech
   source (``P 5``, so the lexicon spells the number) or of the text;
5. kind (alert -> ALERT, race -> RACE, info -> INFO), priority, speak window, ``bypass_quiet``, TTL and topic from the
   call (docs/voice-protocol.md); ``meta``: ``topic, group, call, urgent, tier, synthetic, addressable, race_call``
   (and ``race_allowance: false`` for calls outside the per-lap race allowance: the grid brief, lights out, the
   countdown, the finish, a move into the lead; ``repeat_ok: true`` for flags, penalties and damage, whose rules
   have their own cooldowns; ``merge_into_summary: true`` for a countdown call made at the line).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pitwall.voice.scheduler import RACE_ALLOWANCE_KEY, REPEAT_OK_KEY, SUMMARY_MERGE_KEY, TOPIC_KEY
from pitwall.voice.speech import to_speech
from pitwall.voice.types import MessageKind, Priority, RadioMessage

KINDS = {"alert": MessageKind.ALERT, "race": MessageKind.RACE, "info": MessageKind.INFO}
PRIORITIES = {"urgent": Priority.URGENT, "high": Priority.HIGH, "normal": Priority.NORMAL, "low": Priority.LOW}
DEFAULT_TTL_S = 20.0
ALWAYS_ON = frozenset({"red_flag"})
REPEATABLE_GROUPS = frozenset({"flags", "penalties", "damage"})  # their rules have cooldowns of their own


def group_enabled(prefs: object | None, group: str) -> bool:
    """The driver's toggle for ``group`` (``RadioCallPrefs`` attribute); on when unknown or no driver is seated."""
    if prefs is None:
        return True
    value = getattr(prefs, group, True)
    return value is not False


def race_message(
    payload: Mapping[str, Any],
    now_mono: float,
    *,
    prefs: object | None = None,
    simple: bool = False,
    intensity: str = "normal",
) -> RadioMessage | None:
    """The radio message of a ``race_call`` note, or None when this driver does not get it."""
    call = str(payload.get("call") or "")
    group = str(payload.get("group") or "")
    if call not in ALWAYS_ON and not group_enabled(prefs, group):
        return None
    if payload.get("defer_to_strategy_detail") and intensity == "detailed" and not simple:
        return None
    if payload.get("audience") == "experienced" and simple:
        return None
    data = payload.get("data")
    data = data if isinstance(data, Mapping) else {}
    if simple and call == "position_change":
        pos, before = data.get("position"), data.get("before")
        if isinstance(pos, int) and isinstance(before, int) and pos > before:
            return None  # simple words: places lost are not counted out loud
    plain = payload.get("text_simple")
    use_plain = simple and isinstance(plain, str) and bool(plain)
    text = str(plain) if use_plain else str(payload["text"])
    source = payload.get("speech_source")
    speech_from = source if not use_plain and isinstance(source, str) and source else text
    ttl = payload.get("ttl_s")
    ttl_s = float(ttl) if isinstance(ttl, int | float) and ttl > 0 else DEFAULT_TTL_S
    lap = payload.get("lap")
    meta: dict[str, object] = {
        "group": group,
        "call": call,
        "urgent": False,
        "tier": payload.get("tier"),
        "synthetic": bool(payload.get("synthetic")),
        "addressable": payload.get("addressable") is True,
        "race_call": payload.get("id"),
    }
    if payload.get("allowance") is False:
        meta[RACE_ALLOWANCE_KEY] = False  # outside the per-lap race allowance (start, countdown, finish, the lead)
    if group in REPEATABLE_GROUPS:
        meta[REPEAT_OK_KEY] = True  # a second blue flag or penalty within a minute is news, not a repeat
    if data.get("at_line") is True:
        meta[SUMMARY_MERGE_KEY] = True  # a countdown call at the line: said inside the lap summary
    topic = payload.get("topic")
    if isinstance(topic, str) and topic:
        meta[TOPIC_KEY] = topic
    return RadioMessage(
        id=f"race-{payload['id']}",
        kind=KINDS.get(str(payload.get("kind")), MessageKind.RACE),
        priority=PRIORITIES.get(str(payload.get("priority")), Priority.NORMAL),
        text=text,
        speech=to_speech(speech_from),
        created_mono=now_mono,
        expires_mono=now_mono + ttl_s,
        lap_number=lap if isinstance(lap, int) and not isinstance(lap, bool) else None,
        bypass_quiet=bool(payload.get("bypass_quiet")),
        needs_speak_window=payload.get("needs_window") is not False,
        meta=meta,
    )
