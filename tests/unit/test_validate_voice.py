"""Rig validation kit: radio command parsing and reply texts (pure)."""

from __future__ import annotations

import re

import pytest

from pitwall.validate import voice as V
from pitwall.validate.catalog import BY_ID

AMERICAN = re.compile(r"\b(color|center|favorite|behavior|analyze|meter|tire|license|gray)s?\b", re.IGNORECASE)


@pytest.mark.parametrize(
    ("text", "cmd"),
    [
        ("Start validation", "start"),
        ("OK, start validation please.", "start"),
        ("Pitwall, begin a rig test", "start"),
        ("start a test run", "start"),
        ("Next test", "next"),
        ("skip this check", "next"),
        ("Radio, next test please", "next"),
        ("worked", "worked"),
        ("It worked!", "worked"),
        ("test passed", "worked"),
        ("didn't work", "didnt"),
        ("That didn’t work", "didnt"),
        ("it did not work", "didnt"),
        ("failed", "didnt"),
        ("What's the test?", "status"),
        ("what is the current test", "status"),
        ("repeat the instructions", "status"),
        ("validation status", "status"),
        ("Finish validation", "finish"),
        ("engineer, stop the validation", "finish"),
        ("end validation", "finish"),
    ],
)
def test_commands(text: str, cmd: str) -> None:
    assert V.parse_command(text) == cmd


@pytest.mark.parametrize(
    "text",
    [
        "where should I brake in turn 3",
        "start talking",
        "radio check",
        "give me a report",
        "how did that go",
        "how are my tyres",
        "what's the gap to the car ahead",
        "",
        "please",
    ],
)
def test_ordinary_questions_are_not_commands(text: str) -> None:
    assert V.parse_command(text) is None


def test_replies_are_short_british_and_use_digits() -> None:
    texts = [
        V.started(BY_ID["cues_timing"].radio_brief),
        V.next_test(BY_ID["radio_ptt"].radio_brief),
        V.next_test(None),
        V.marked("braking calls", True),
        V.marked("braking calls", False),
        V.status(3, 9, "braking calls", BY_ID["cues_timing"].radio_brief),
        V.finished(5, 1, 3),
        V.verdict_prompt("braking calls", "pass"),
        V.back_to(BY_ID["ipad_one_message"].radio_brief),
        V.marked("glance test", False, "Sam"),
        V.FINISHING,
        V.FINISH_FAILED,
    ]
    assert texts[0] == (
        "Validation started. First test: braking calls. Three laps with braking calls off, then three with them on."
    )
    assert texts[3] == "Braking calls: noted as worked."
    assert texts[5] == "Test 3 of 9: braking calls. Three laps with braking calls off, then three with them on."
    assert texts[6] == "Validation finished. 5 passed, 1 failed, 3 to check. Report saved."
    assert texts[8] == "Back to the one message test. Five laps; check the coach card matches what I say."
    assert texts[9] == "Glance test: noted as didn't work for Sam. Add a note on the iPad when you stop."
    for t in texts:
        assert len(t.split()) <= 25 and not AMERICAN.search(t)
    long = V.status(1, 9, "braking calls", "Validation: braking calls. " + " ".join(["word"] * 40))
    assert len(long.split()) <= 25 and long.endswith(".")
