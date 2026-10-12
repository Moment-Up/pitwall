"""Strategy calls as radio messages for the ``RadioScheduler`` (always in speak windows).

Level -> kind: ``alert`` -> ``MessageKind.ALERT`` (every intensity), ``normal`` -> ``MessageKind.STRATEGY`` (normal and
detailed), ``detailed`` -> ``MessageKind.INFO`` (detailed only). Priority comes from the call; ``bypass_quiet`` only
for the safety-car box-or-stay call and critical fuel. ``meta["topic"] = "strategy:<topic>"``, so a newer call on the
same topic replaces an unsaid older one ("fuel critical" replaces "fuel is tight").
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pitwall.voice.scheduler import TOPIC_KEY
from pitwall.voice.speech import to_speech
from pitwall.voice.types import MessageKind, Priority, RadioMessage

LEVEL_KIND = {"alert": MessageKind.ALERT, "normal": MessageKind.STRATEGY, "detailed": MessageKind.INFO}
PRIORITY = {"high": Priority.HIGH, "normal": Priority.NORMAL, "low": Priority.LOW}
DEFAULT_TTL_S = 60.0


def strategy_message(call: Mapping[str, Any], now_mono: float, *, simple: bool = False) -> RadioMessage:
    """A ``StrategyCall.to_dict()`` (the ``strategy_call`` live notification) as a radio message; ``simple``: the
    call's plain words (``text_simple``) when it has them (a driver whose profile asks for simple wording)."""
    plain = call.get("text_simple")
    text = str(plain) if simple and isinstance(plain, str) and plain else str(call["text"])
    ttl = call.get("ttl_s")
    ttl_s = float(ttl) if isinstance(ttl, int | float) and ttl > 0 else DEFAULT_TTL_S
    lap = call.get("lap")
    return RadioMessage(
        id=f"strategy-{call['id']}",
        kind=LEVEL_KIND.get(str(call.get("level")), MessageKind.INFO),
        priority=PRIORITY.get(str(call.get("priority")), Priority.NORMAL),
        text=text,
        speech=to_speech(text),
        created_mono=now_mono,
        expires_mono=now_mono + ttl_s,
        lap_number=lap if isinstance(lap, int) else None,
        bypass_quiet=bool(call.get("bypass_quiet")),
        needs_speak_window=True,
        meta={
            TOPIC_KEY: f"strategy:{call.get('topic')}",
            "strategy_call": call["id"],
            "level": call.get("level"),
            "audience": call.get("audience"),
        },
    )
