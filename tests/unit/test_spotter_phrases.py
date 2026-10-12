"""What the spotter says: both wording sets complete, no numbers, short, key word early, British spelling."""

from __future__ import annotations

import re

import pytest

from pitwall.spotter.model import CALL_KINDS, STILL_THERE
from pitwall.spotter.phrases import (
    PHRASE_IDS,
    PHRASES,
    all_texts,
    heard_mismatch,
    onset_phrase_id,
    phrase_id,
    phrase_text,
)


def test_every_id_has_both_wordings_and_every_call_a_phrase() -> None:
    assert set(PHRASE_IDS) == {
        "car_left",
        "car_right",
        "clear_left",
        "clear_right",
        "three_wide",
        "clear_all_round",
        "still_there_left",
        "still_there_right",
        "hold_your_line",
    }
    assert len(all_texts()) == 18
    for kind in CALL_KINDS:
        for side in ("left", "right"):
            assert phrase_id(kind, side if kind == STILL_THERE else None) in PHRASES
    with pytest.raises(ValueError):
        phrase_id("box_box", None)


@pytest.mark.parametrize(("pid", "wording", "text"), all_texts())
def test_no_numbers_short_and_side_first(pid: str, wording: str, text: str) -> None:
    assert not re.search(r"\d", text)
    words = re.findall(r"[A-Za-z']+", text)
    if wording == "standard":
        assert len(words) <= 6
    lower = [w.lower() for w in words]
    for side in ("left", "right"):
        if side in lower and pid not in ("still_there_left", "still_there_right"):
            assert lower.index(side) <= 3, text  # the key word arrives early
    assert text.endswith(".")
    for american in ("center", "color", "program"):
        assert american not in text.lower()


def test_standard_and_simple_texts() -> None:
    assert phrase_text("car_left", False) == "Car left."
    assert phrase_text("car_left", True) == "Car on your left."
    assert phrase_text("three_wide", False) == "Three wide, you're in the middle."
    assert phrase_text("still_there_right", True) == "Still on your right."
    assert onset_phrase_id("right") == "car_right"


@pytest.mark.parametrize(
    ("pid", "simple", "heard", "ok"),
    [
        ("car_left", False, "Car left.", True),
        ("car_left", False, "car right", False),  # never left heard as right
        ("car_left", False, "car left and right", False),
        ("clear_right", True, "Right side clear", True),
        ("still_there_left", False, "Still there.", True),
        ("still_there_left", False, "Still there left", False),  # no side expected
        ("three_wide", False, "Three wide, you're in the middle.", True),
        ("three_wide", False, "Free wide", False),
        ("clear_all_round", False, "Clear, all around.", True),
        ("hold_your_line", True, "keep it steady car very close", True),
    ],
)
def test_heard_check(pid: str, simple: bool, heard: str, ok: bool) -> None:
    assert (heard_mismatch(pid, simple, heard) is None) is ok
