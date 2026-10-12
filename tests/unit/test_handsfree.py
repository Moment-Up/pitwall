"""Hands-free talking, pure rules (lane handsfree, docs/research/handsfree.md): the wake-word matcher, the echo guard,
the budgets and the motion gate (the server's port of web-react/src/lib/drive/motion.ts)."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from pitwall.model.telemetry import CarFrame, FrameQuality, Game
from pitwall.voice.handsfree import (
    MOVE_ABOVE_KPH,
    STOP_AFTER_S,
    STOP_BELOW_KPH,
    MotionGate,
    RateBudget,
    is_echo,
    levenshtein,
    match_wake,
    tokens,
)

INTENTS = Path(__file__).resolve().parents[1] / "fixtures" / "intents.json"

# Every way the real speech engines wrote "Pitwall" in the synthetic probe (docs/research/handsfree.md section 3.3).
OBSERVED = [
    "Pitwall",
    "Pit wall",
    "Pitwal",
    "Pittwall",
    "Pitball",
    "Pitbull",
    "Pit well",
    "Pigwall",
    "Bidwall",
    "Big wall",
    "Bit wall",
    "Tidwall",
    "Pidwall",
    "Hitwall",
    "It wall",
    "Fit wall",
    "Pitfall",
    "Pitmull",
]


# ---------------------------------------------------------------------------------------------- wake word
@pytest.mark.parametrize("heard", OBSERVED)
def test_every_observed_spelling_of_pitwall_is_the_wake_word(heard: str) -> None:
    m = match_wake(f"{heard}, what's my fuel?", "pitwall")
    assert m is not None and m.question == "what's my fuel?" and not m.trigger_only
    alone = match_wake(f"{heard}.", "pitwall")
    assert alone is not None and alone.trigger_only


@pytest.mark.parametrize(
    "text",
    [
        "It all! What's my fuel?",  # a real miss: "It all" is not "it wall"
        "The pit wall told him to box this lap.",  # not at the start
        "That corner is a real pitfall.",
        "I think the radio is too loud.",
        "Pass me the water, would you?",
        "Box box, box box.",
        "What's for dinner tonight?",
        "Fedwall, what's my fuel?",  # starts with "f" but 3 edits away? no: f-e-d vs p-i-t
        "",
        "...",
    ],
)
def test_speech_that_does_not_start_with_the_wake_word_is_not_addressed(text: str) -> None:
    assert match_wake(text, "pitwall") is None
    assert match_wake(text, "radio") is None


@pytest.mark.parametrize(
    ("text", "question"),
    [
        ("Hey Pitwall, when should I pit?", "when should I pit?"),
        ("OK Pitwall, gap to the car ahead?", "gap to the car ahead?"),
        ("Um, uh, Pitwall, tyres?", "tyres?"),  # two fillers at most
        ("Pitwall... how was that lap?", "how was that lap?"),
        ("Pitwall – what’s my fuel?", "what’s my fuel?"),  # dash stripped, original apostrophe kept
        ("Pitwall, OK?", "OK?"),  # "pitwallok" is further from "pitwall" than "pitwall" alone: OK is the question
        ("Pit wall, radio check.", "radio check."),
        ("PITWALL WHAT'S MY GAP", "WHAT'S MY GAP"),
    ],
)
def test_the_question_is_the_original_text_after_the_wake_word(text: str, question: str) -> None:
    m = match_wake(text, "pitwall")
    assert m is not None and m.word == "pitwall" and m.question == question


def test_three_fillers_are_too_many() -> None:
    assert match_wake("Um uh er Pitwall, fuel?", "pitwall") is None


def test_the_wake_word_alone_is_a_trigger() -> None:
    for text in ("Pitwall.", "Pitwall?", "Pit wall!", "Hey, Pitwall", "Pitwall —"):
        m = match_wake(text, "pitwall")
        assert m is not None and m.trigger_only, text


def test_radio_is_one_word_and_a_radio_check_keeps_the_whole_text() -> None:
    m = match_wake("Radio, what's my gap to the car ahead?", "radio")
    assert m is not None and m.question == "what's my gap to the car ahead?"
    check = match_wake("Radio check.", "radio")
    assert check is not None and check.question == "Radio check." and not check.trigger_only
    alone = match_wake("Radio.", "radio")
    assert alone is not None and alone.trigger_only
    for spelling in ("Radios", "Radio's", "Radi", "Radioo"):
        assert match_wake(f"{spelling}, fuel?", "radio") is not None, spelling
    assert match_wake("Ra dio, fuel?", "radio") is None  # one word only
    assert match_wake("Pitwall, fuel?", "radio") is None  # each device listens for its own word
    assert match_wake("Radio, fuel?", "pitwall") is None
    with pytest.raises(ValueError):
        match_wake("Engineer, fuel?", "engineer")


def test_no_question_in_the_engineer_intents_table_is_addressed() -> None:
    """A5 (text): 0 of the intents fixture's questions start with "Pitwall"; "Radio" only "Radio check"."""
    questions = [q["question"] for q in json.loads(INTENTS.read_text(encoding="utf-8"))["questions"]]
    assert len(questions) >= 200
    assert [q for q in questions if match_wake(q, "pitwall") is not None] == []
    assert [q for q in questions if match_wake(q, "radio") is not None] == ["Radio check"]


def test_tokens_and_levenshtein() -> None:
    assert tokens("Loud and clear. Radio check OK.") == ["loud", "and", "clear", "radio", "check", "ok"]
    assert tokens("Turn 9 — Café's apex") == ["turn", "9", "cafe's", "apex"]
    assert levenshtein("pitwall", "pitwall") == 0
    assert levenshtein("bidwall", "pitwall") == 2
    assert levenshtein("", "abc") == 3


# ---------------------------------------------------------------------------------------------- echo guard
def test_echo_guard_recognises_the_radios_own_words() -> None:
    said = tokens("Radio check, loud and clear. Box this lap for mediums.")
    assert is_echo(tokens("Radio check, loud and clear."), said)  # a contiguous run of 5 words
    assert is_echo(tokens("Radio check loud and clear box this lap for medium"), said)  # ratio >= 0.8
    assert not is_echo(tokens("Radio check."), said)  # two words: too short to be called an echo
    assert not is_echo(tokens("Radio, box this lap?"), said)  # a question, not a run of what was said
    assert not is_echo([], said) and not is_echo(tokens("fuel"), [])
    answer = tokens("Pitwall works with Gran Turismo 7 lap times.")
    assert is_echo(tokens("Pitwall works with Gran Turismo"), answer)
    assert not is_echo(tokens("Pitwall, what's my fuel?"), answer)


# ---------------------------------------------------------------------------------------------- budgets
def test_rate_budget_is_a_sliding_window() -> None:
    b = RateBudget(2, 60.0)
    assert b.take(0.0) and b.take(10.0)
    assert not b.take(30.0) and not b.available(59.9)
    assert b.count(60.0) == 1 and b.take(60.0)  # the first one left the window
    assert not b.take(65.0)
    b.clear()
    assert b.available(65.0)


# ---------------------------------------------------------------------------------------------- motion
def _frame(speed: float | None, pit: int | None = None, quality: FrameQuality = FrameQuality.OK) -> CarFrame:
    return CarFrame(game=Game.F1_25, t_recv_ns=0, speed_kph=speed, pit_status=pit, quality=quality)


def _run(speeds: list[float | None], start: MotionGate, step_s: float = 0.05, pit: int | None = None) -> list[bool]:
    return [start.update(_frame(v, pit), True, 100 + i * step_s) for i, v in enumerate(speeds)]


def test_motion_thresholds_match_drive() -> None:
    assert (STOP_BELOW_KPH, STOP_AFTER_S, MOVE_ABOVE_KPH) == (3.0, 1.5, 8.0)


def test_no_flicker_between_4_and_6_kph_whichever_way_the_car_was_going() -> None:
    crawl: list[float | None] = [4, 6, 4.5, 5.9, 4.1, 6, 5, 4]
    assert _run(crawl, MotionGate(stationary=True)) == [True] * len(crawl)
    assert _run(crawl, MotionGate(stationary=False)) == [False] * len(crawl)
    g = MotionGate()
    g.update(_frame(0), True, 0.0)  # stopped
    assert _run([4.9, 5.1, 4.9, 5.1, 4.9], g) == [True] * 5


def test_stops_after_1_5_s_under_3_kph_and_a_burst_starts_the_wait_over() -> None:
    slow: list[float | None] = [1.0] * 40
    assert _run(slow, MotionGate(stationary=False)).index(True) == 30  # 30 x 50 ms
    bumpy: list[float | None] = [*([1.0] * 20), 4.0, *([1.0] * 40)]
    assert _run(bumpy, MotionGate(stationary=False)).index(True) == 51


def test_in_the_pits_under_3_kph_is_stationary_at_once() -> None:
    assert _run([2.0], MotionGate(stationary=False), pit=1) == [True]
    assert _run([2.0], MotionGate(stationary=False), pit=2) == [True]
    assert _run([5.0], MotionGate(stationary=False), pit=1) == [False]


def test_moves_at_once_over_8_kph() -> None:
    assert _run([9.0], MotionGate(stationary=True)) == [False]
    assert _run([8.0], MotionGate(stationary=True)) == [True]


def test_no_frame_stale_data_or_a_paused_frame_is_stationary_and_unknown_speed_keeps_the_answer() -> None:
    assert MotionGate(stationary=False).update(None, True, 0.0)
    assert MotionGate().update(_frame(250.0), False, 0.0)  # not live: the frame on screen is not current
    assert MotionGate(stationary=False).update(_frame(250.0, quality=FrameQuality.PAUSED), True, 0.0)
    assert MotionGate(stationary=False).update(_frame(250.0, quality=FrameQuality.REPLAY_OR_SPECTATING), True, 0.0)
    assert not MotionGate(stationary=False).update(_frame(250.0, quality=FrameQuality.STALE_LAP_DATA), True, 0.0)
    assert MotionGate(stationary=True).update(_frame(None), True, 0.0)
    assert not MotionGate(stationary=False).update(_frame(float("nan")), True, 0.0)
    assert not MotionGate().update(_frame(None), True, 0.0)  # not known to be stopped: the safe side
    assert MotionGate().update(_frame(0.0), True, 0.0)  # a stopped car with nothing before it: stationary


# ---------------------------------------------------------------------------------------------- scripts/handsfree_check.py
ROOT = Path(__file__).resolve().parents[2]
VAD_FIXTURE = ROOT / "tests" / "fixtures" / "handsfree" / "vad_rms.json.gz"


def _check_script() -> Any:
    spec = importlib.util.spec_from_file_location("handsfree_check", ROOT / "scripts" / "handsfree_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["handsfree_check"] = mod  # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


def test_reference_vad_reproduces_the_synthetic_acceptance_table() -> None:
    """A6 (synthetic): the RMS traces the dashboard's TypeScript VAD is tested on, run through the script's reference
    VAD (section 4.2 rules): quiet >= 236/238 single segments, 20 dB SNR >= 115/119, 0 dB -> nothing, never a
    false segment. The fixture's ``expected`` block is what the TypeScript VAD must reproduce."""
    mod = _check_script()
    doc = json.loads(gzip.decompress(VAD_FIXTURE.read_bytes()))
    assert doc["frame_samples"] == 512 and doc["sample_rate"] == 16_000 and len(doc["traces"]) == 714
    stats = mod.score_vad(doc["traces"])
    assert stats == doc["expected"]
    assert stats["quiet"]["single"] >= 236 and stats["snr20"]["single"] >= 115
    assert stats["snr0"]["single"] == stats["snr0"]["split"] == 0
    assert all(s["false"] == 0 for s in stats.values())


def test_reference_vad_rules() -> None:
    vad = _check_script().EnergyVad()
    quiet, loud = 10 ** (-70 / 20), 10 ** (-20 / 20)
    assert vad.run([quiet] * 31) == []  # calibration only
    one = vad.run([quiet] * 40 + [loud] * 30 + [quiet] * 40)
    assert one == [(39, 91, "silence")]  # starts with the 5-frame window that held 4 voiced, ends after 22 silent
    fan = 10 ** (-40 / 20)  # a fan switched on: the floor follows it up during the segment, which then ends
    assert [seg[2] for seg in vad.run([quiet] * 40 + [fan] * 400)] == ["silence"]
    hum = 10 ** (-30 / 20)  # louder: the floor cannot catch up within 8 s, so the cap ends it
    capped = vad.run([quiet] * 40 + [hum] * 400)
    assert capped[0][2] == "max" and capped[0][1] - capped[0][0] == 250
    assert len(capped) == 1  # after the cap, the continuous noise became the floor: no second segment
    roar = vad.run([quiet] * 40 + [loud] * 400)  # louder than the floor may ever rise: refused again and again
    assert [seg[2] for seg in roar] == ["max", "eof"]
