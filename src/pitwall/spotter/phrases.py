"""What the spotter says (plain British English). Two wording sets: standard and simple (beginner).

Rules (tests/unit/test_spotter_phrases.py): no numbers; a standard phrase has at most 6 words; "left" / "right" come
first or second so the key word arrives early. The simple set is used when the seated driver's profile asks for
simple wording (``drivers.CoachingLimits.simple_wording``) or the spotter's ``wording`` setting is "simple".
"""

from __future__ import annotations

from pitwall.spotter.model import (
    CAR_LEFT,
    CAR_RIGHT,
    CLEAR_ALL_ROUND,
    CLEAR_LEFT,
    CLEAR_RIGHT,
    HOLD_YOUR_LINE,
    STILL_THERE,
    THREE_WIDE,
)

# phrase id -> (standard, simple)
PHRASES: dict[str, tuple[str, str]] = {
    "car_left": ("Car left.", "Car on your left."),
    "car_right": ("Car right.", "Car on your right."),
    "clear_left": ("Clear left.", "Left side clear."),
    "clear_right": ("Clear right.", "Right side clear."),
    "three_wide": ("Three wide, you're in the middle.", "Cars on both sides. Stay in the middle."),
    "clear_all_round": ("Clear all round.", "All clear."),
    "still_there_left": ("Still there.", "Still on your left."),
    "still_there_right": ("Still there.", "Still on your right."),
    "hold_your_line": ("Hold your line.", "Keep it steady, car very close."),
}
PHRASE_IDS: tuple[str, ...] = tuple(PHRASES)
WORDINGS: tuple[str, ...] = ("standard", "simple")

# Words the STT check must hear, in order, for each phrase (left/right must match exactly: mishearing one for the
# other would be dangerous). Lower case, punctuation stripped.
KEY_WORDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "car_left": (("car", "left"), ("car", "left")),
    "car_right": (("car", "right"), ("car", "right")),
    "clear_left": (("clear", "left"), ("left", "clear")),
    "clear_right": (("clear", "right"), ("right", "clear")),
    "three_wide": (("three", "wide", "middle"), ("both", "sides", "middle")),
    "clear_all_round": (("clear", "all"), ("all", "clear")),
    "still_there_left": (("still", "there"), ("still", "left")),
    "still_there_right": (("still", "there"), ("still", "right")),
    "hold_your_line": (("hold", "line"), ("steady", "close")),
}


def phrase_id(kind: str, side: str | None) -> str:
    """The phrase for a call. A ``still_there`` without a side uses the left phrase (both are "Still there.")."""
    if kind == STILL_THERE:
        return f"still_there_{side or 'left'}"
    if kind in (CAR_LEFT, CAR_RIGHT, CLEAR_LEFT, CLEAR_RIGHT, THREE_WIDE, CLEAR_ALL_ROUND, HOLD_YOUR_LINE):
        return kind
    raise ValueError(f"unknown spotter call {kind!r}")


def onset_phrase_id(side: str) -> str:
    """A ``still_there`` the driver has not heard the onset of is said as the onset (spec section 5.3)."""
    return CAR_LEFT if side == "left" else CAR_RIGHT


def phrase_text(pid: str, simple: bool) -> str:
    standard, beginner = PHRASES[pid]
    return beginner if simple else standard


def key_words(pid: str, simple: bool) -> tuple[str, ...]:
    standard, beginner = KEY_WORDS[pid]
    return beginner if simple else standard


def all_texts() -> list[tuple[str, str, str]]:
    """(phrase id, wording, text) for every phrase in both sets."""
    return [(pid, w, phrase_text(pid, w == "simple")) for pid in PHRASE_IDS for w in WORDINGS]


_LR = ("left", "right")


def heard_words(heard: str) -> list[str]:
    """Lower-case words of an STT transcript (letters and apostrophes only)."""
    out: list[str] = []
    word: list[str] = []
    for ch in heard.lower():
        if ch.isalpha() or ch == "'":
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def heard_mismatch(pid: str, simple: bool, heard: str) -> str | None:
    """Why the STT transcript of a rendered phrase is not acceptable (None = it is).

    The key words must be heard in order, and "left" / "right" must match exactly: a phrase about the left must
    never be heard with "right" in it (and the other way round), and a phrase with no side must contain neither."""
    words = heard_words(heard)
    expected = key_words(pid, simple)
    want_lr = {w for w in expected if w in _LR}
    got_lr = {w for w in words if w in _LR}
    if got_lr != want_lr:
        return f"left/right heard as {sorted(got_lr) or 'neither'}, expected {sorted(want_lr) or 'neither'}"
    k = 0
    for w in words:
        if k < len(expected) and w == expected[k]:
            k += 1
    if k < len(expected):
        return f"missing {expected[k]!r}"
    return None
