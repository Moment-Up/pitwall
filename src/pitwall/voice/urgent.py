"""The urgent path: a call that must be said now, past every filter (the red flag; reusable by any producer).

Any thread calls ``live.notify(URGENT_NOTE, payload)``::

    {"id": "...", "source": "raceradio", "text": "...", "text_simple": "..." | null, "speech_source": null | "...",
     "ttl_s": 15, "t_mono": <time.monotonic() at the notify> | null, "meta": {...}}

The radio hub marshals it onto its loop (``call_soon_threadsafe``) and queues ``urgent_message(payload, ...)``: kind
ALERT, ``Priority.URGENT``, ``bypass_quiet``, no speak window, ``meta.urgent = True``. No group toggle and no name
addressing. The scheduler and hub already give urgent messages their contract (``voice.scheduler``: past quiet mode,
intensity, the speak window and the gap; ``voice.hub``: cuts a cue or a proactive message - which is said again once -
waits only for the driver's own transmission and never cuts another urgent call; dropped, on screen only, when voice is
off). ``created_mono`` is the notify time when the payload carries it, so the TTL and the latency record
(``LatencyRecord(kind="urgent")``: notify -> first audio, ``/api/voice/status``) count from the event, not from when the
loop got to it.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from pitwall.voice.speech import to_speech
from pitwall.voice.types import MessageKind, Priority, RadioMessage

URGENT_NOTE = "radio_urgent"
DEFAULT_TTL_S = 15.0
MAX_TTL_S = 60.0
NOTIFY_SKEW_S = 5.0  # a notify time further back than this (or in the future) is not believed


def urgent_message(payload: Mapping[str, Any], now_mono: float | None = None, *, simple: bool = False) -> RadioMessage:
    """The radio message of a ``radio_urgent`` note. ``simple``: the plain words (``text_simple``) when it has them."""
    now = time.monotonic() if now_mono is None else now_mono
    plain = payload.get("text_simple")
    text = str(plain) if simple and isinstance(plain, str) and plain else str(payload["text"])
    source = payload.get("speech_source")
    speech_from = text if simple or not isinstance(source, str) or not source else source
    ttl = payload.get("ttl_s")
    ttl_s = float(ttl) if isinstance(ttl, int | float) and 0 < ttl <= MAX_TTL_S else DEFAULT_TTL_S
    t = payload.get("t_mono")
    created = float(t) if isinstance(t, int | float) and 0.0 <= now - float(t) <= NOTIFY_SKEW_S else now
    meta = payload.get("meta")
    return RadioMessage(
        id=f"urgent-{payload['id']}",
        kind=MessageKind.ALERT,
        priority=Priority.URGENT,
        text=text,
        speech=to_speech(speech_from),
        created_mono=created,
        expires_mono=created + ttl_s,
        bypass_quiet=True,
        needs_speak_window=False,
        meta={
            **(dict(meta) if isinstance(meta, Mapping) else {}),
            "urgent": True,
            "source": payload.get("source"),
        },
    )
