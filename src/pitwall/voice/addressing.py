"""Name addressing: the radio says the seated driver's first name now and then ("Up to P5, Sam.").

``NameCaller.set_driver(name, enabled, seat_changed)`` (the hub's ``apply_driver``) and ``NameCaller.apply(msg, now)``
right after the scheduler hands a message out (``voice.hub._tick``), before synthesis: ``_after_synthesis`` re-checks
the speak window with the real clip duration, so the extra ~0.4 s can never push a message into a braking zone - at
worst it is held.

* **The name** - the first word of the seated driver's profile name, only if it looks like a name (2-20 letters,
  apostrophes and hyphens), never the default "Driver" or "Driver NN". A TTS engine that can say which words its G2P
  would drop (``g2p_dropped(text) -> list[str]``) is asked once, off the loop (``hub``); a name it would drop disables
  addressing (logged without the name). The macOS ``say`` voice and device voices always say it.
* **Which messages** - those whose builder marked them ``meta["addressable"]`` (the lap-1 summary, a gained place, a
  clean pass, the finish, the last lap, the driver's own fastest lap), or, once, the first proactive non-urgent message
  after a seat change (it confirms who is in the seat). Never an urgent call, a cue, an answer, an acknowledgement or a
  validation prompt.
* **How often** - at most once every ``RATE_S`` [H; the brief: "at most once a minute"].
* **Where** - ``", Sam"`` before the first sentence end of the display text and of the speech ("Good move, Sam. P5.");
  when that first sentence already has a comma or a colon the name goes first ("Sam, that lap 1:15.5. Flashback
  used." - never "That lap, 1:15.5, Sam."), lower-casing the first word unless it is a name or an abbreviation.
"""

from __future__ import annotations

import dataclasses
import math
import re

from pitwall.voice.types import MessageKind, Priority, RadioMessage

RATE_S = 60.0  # [H]
NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,20}$")
DEFAULT_NAMES = frozenset({"driver", "player"})
NEVER = frozenset({MessageKind.CUE, MessageKind.ANSWER, MessageKind.CONTROL, MessageKind.VALIDATION})
ADDRESSABLE_KEY = "addressable"
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
# first words lower-cased when the name goes first ("That lap, 1:15.5." -> "Sam, that lap, 1:15.5."); any other word
# keeps its capital (an AI driver's or a team's name, "I", "P5", "T3")
_LOWER_FIRST = frozenset(
    {
        *("that", "this", "the", "a", "an", "lap", "opening", "up", "down", "good", "nice", "chequered", "gap"),
        *("leading", "behind", "fastest", "track", "warning", "damage", "box", "safety", "virtual", "green", "blue"),
        *("yellow", "last", "five", "two", "penalty", "time", "drive-through", "stop-go", "grid", "out", "after"),
        *("you", "you're", "your", "still", "next", "front", "rear", "left", "right", "new", "personal", "session"),
        *("best", "brake", "lift", "carry", "turn", "corner", "sector"),
    }
)


def first_name(profile_name: str | None) -> str | None:
    """The word to say: the first word of the profile name when it looks like a name, else None."""
    if not profile_name:
        return None
    words = profile_name.split()
    first = words[0] if words else ""
    if not NAME_RE.match(first) or first.casefold() in DEFAULT_NAMES:
        return None
    return first


def with_name(text: str, name: str) -> str:
    """``", {name}"`` before the first sentence end ("Up to P5." -> "Up to P5, Sam."); appended when there is none.
    A first sentence with a comma or colon gets the name first ("Sam, 3 second penalty: cutting the track.")."""
    m = _SENTENCE_END.search(text)
    head = text if m is None else text[: m.start()]
    if "," in head or ":" in head:
        lead = text.lstrip()
        word = lead.split(maxsplit=1)[0].rstrip(",:;.!?") if lead else ""
        if word.casefold() in _LOWER_FIRST and word[:1].isupper():
            lead = lead[:1].lower() + lead[1:]
        return f"{name}, {lead}"
    if m is None:
        return f"{text.rstrip()}, {name}"
    return f"{text[: m.start()]}, {name}{text[m.start() :]}"


class NameCaller:
    """Event loop only (the hub)."""

    __slots__ = ("_after_seat", "_last", "enabled", "name", "rate_s")

    def __init__(self, rate_s: float = RATE_S) -> None:
        self.rate_s = rate_s
        self.name: str | None = None
        self.enabled = True
        self._last = -math.inf
        self._after_seat = False

    def set_driver(self, name: str | None, enabled: bool, seat_changed: bool) -> None:
        self.name = first_name(name)
        self.enabled = enabled
        if seat_changed:
            self._after_seat = self.name is not None and enabled

    def disable_name(self) -> None:
        """The TTS engine would drop the name: no addressing for this driver."""
        self.name = None
        self._after_seat = False

    def apply(self, msg: RadioMessage, now_mono: float) -> RadioMessage:
        """``msg`` with the driver's name worked in, or ``msg`` unchanged."""
        name = self.name
        if name is None or not self.enabled or msg.priority >= Priority.URGENT or msg.kind in NEVER:
            return msg
        if not (msg.meta.get(ADDRESSABLE_KEY) is True or self._after_seat):
            return msg
        if now_mono - self._last < self.rate_s:
            return msg
        self._last = now_mono
        self._after_seat = False
        return dataclasses.replace(msg, text=with_name(msg.text, name), speech=with_name(msg.speech, name))
