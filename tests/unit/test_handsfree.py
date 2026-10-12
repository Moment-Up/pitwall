"""Hands-free talking, pure rules (lane handsfree, docs/research/handsfree.md): the wake-word matcher, the echo guard,
the budgets and the motion gate (the server's port of web-react/src/lib/drive/motion.ts)."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall.ai.engineer import detect_intent
from pitwall.model.telemetry import CarFrame, FrameQuality, Game
from pitwall.voice.handsfree import (
    MOVE_ABOVE_KPH,
    STALE_STILL_AFTER_S,
    STOP_AFTER_S,
    STOP_BELOW_KPH,
    MotionGate,
    RateBudget,
    _starts_with_wake,
    is_echo,
    levenshtein,
    match_wake,
    no_session_sheet,
    segment_level,
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
        "It all went wrong in turn three.",  # "It all" counts only with punctuation after it
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
        ("Pitwall, um, what's my fuel?", "what's my fuel?"),  # fillers after the wake word are not the question
        ("Pitwall, right front tyre?", "right front tyre?"),  # "right" stays when more follows
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


@pytest.mark.parametrize(
    "text",
    [
        "Pitwall, um.",
        "Pitwall, uh...",
        "Pitwall, er, um",
        "Pitwall, okay.",
        "Pitwall, right.",
        "Pitwall, yeah?",
        "Pitwall, OK?",
        "Pitwall, hmm.",
    ],
)
def test_the_wake_word_and_fillers_only_is_the_wake_word_alone(text: str) -> None:
    """Review finding 2: "Pitwall, um." is not a question about "um": it is the wake word alone ("Go ahead.")."""
    m = match_wake(text, "pitwall")
    assert m is not None and m.trigger_only and m.question == "", text
    radio = match_wake(text.replace("Pitwall", "Radio"), "radio")
    assert radio is not None and radio.trigger_only, text


@pytest.mark.parametrize(
    "text",
    [
        "Hit all the apexes this time",  # two words only count as "pit wall" when the second sounds like "wall"
        "Fit all four tyres",
        "Bit well done",  # two edits away ("bitwell"): only before a racing question
        "Hit well that one",
        "Paywall is up again",
        "Pinball tonight?",
        "Pitbull is playing",
        "A big wall on the left",
        "Tidwell called",
        "He pitwall wins a ditch.",
    ],
)
def test_ordinary_sentence_starts_are_not_the_wake_word(text: str) -> None:
    """Review finding 8: a weak match (two edits from "pitwall") needs a racing question after it."""
    assert match_wake(text, "pitwall") is None


def test_weak_matches_need_a_racing_question_and_strong_ones_take_anything() -> None:
    assert match_wake("Big wall, what's my fuel?", "pitwall") is not None  # weak, a fuel question
    assert match_wake("Pitbull, how are my tyres?", "pitwall") is not None
    assert match_wake("Big wall.", "pitwall") is not None  # weak, alone: the wake word alone
    assert match_wake("Pitwall, what do you think?", "pitwall") is not None  # strong: any question
    m = match_wake("Pit wall says box", "pitwall")  # strong and at the start: taken (documented in research 3.3)
    assert m is not None and m.question == "says box"
    assert match_wake("Ratio is wrong", "radio") is None  # one edit from "radio": weak
    assert match_wake("Ratio, how much fuel have I got?", "radio") is not None
    hey = match_wake("Hey, radio", "radio")  # the driver calls the radio by name: the wake word alone
    assert hey is not None and hey.trigger_only


@pytest.mark.parametrize(
    ("text", "clipped", "question"),
    [
        ("It all, what's my fuel?", False, "what's my fuel?"),  # the first sound of "Pitwall" lost
        ("It all! What's my fuel?", False, "What's my fuel?"),
        ("A pit wall, gap to the car ahead.", False, "gap to the car ahead."),
        ("K Pit wall, gap to the car ahead.", False, "gap to the car ahead."),
        ("Kit wall, how are my tyres?", False, "how are my tyres?"),
        ("Well, how are my tires?", True, "how are my tires?"),  # little pre-roll: "Wall" / "Well" with a question
        ("Twell, what's my fuel?", True, "what's my fuel?"),
        ("Wall. What's my fuel?", True, "What's my fuel?"),
    ],
)
def test_a_clipped_onset_is_still_the_wake_word(text: str, clipped: bool, question: str) -> None:
    """UX review H3 (synthetic onset probe: 80-150 ms of the onset removed)."""
    m = match_wake(text, "pitwall", clipped=clipped)
    assert m is not None and m.question == question


@pytest.mark.parametrize(
    "text", ["Well done mate.", "Wall! I hit the wall.", "Well, that was rubbish.", "Well.", "Well, how was that?"]
)
def test_clipped_forms_need_a_racing_question(text: str) -> None:
    assert match_wake(text, "pitwall", clipped=True) is None
    assert match_wake(text, "pitwall") is None
    assert detect_intent("how are my tires?").name != "general"  # what the accepted clipped question above relies on


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


def test_starts_with_wake_tells_which_spoken_lines_can_echo_an_addressed_transcript() -> None:
    """Review finding 3: "Pitwall, box this lap?" repeats "Box this lap." (ratio 0.86) but is a question; the hub only
    compares a transcript that starts with the wake word with lines that start with it too."""
    assert is_echo(tokens("Pitwall, box this lap?"), tokens("Box this lap."))  # the rule alone would drop it
    assert not _starts_with_wake(tokens("Box this lap."), "pitwall")
    assert _starts_with_wake(tokens("Pitwall works with Gran Turismo 7 lap times."), "pitwall")
    assert _starts_with_wake(tokens("Radio check, loud and clear."), "radio")
    assert _starts_with_wake(tokens("Big wall ahead"), "pitwall")  # however weakly: the echo guard errs on dropping


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


def test_a_stream_that_stops_while_the_car_moves_is_still_moving_for_a_while() -> None:
    """Review findings 1 and 9: real incident gaps (2.4-3.7 s) were heard as stops; a stale stream after a moving
    frame counts as moving for STALE_STILL_AFTER_S, then stationary (a menu, a pause)."""
    g = MotionGate()
    assert not g.update(_frame(150.0), True, 0.0)
    assert not g.update(_frame(150.0), False, 2.0)  # the hub sees "stale" 2 s after the last packet
    assert not g.update(_frame(150.0), False, 2.0 + STALE_STILL_AFTER_S - 0.1)
    assert g.update(_frame(150.0), False, 2.0 + STALE_STILL_AFTER_S)
    assert not g.update(_frame(95.0), True, 9.0)  # driving on: moving at once
    assert not g.update(_frame(95.0), False, 11.0)
    assert not g.update(_frame(95.0), True, 12.0)  # the stream came back within the hold: the hold starts over
    assert not g.update(_frame(95.0), False, 13.0)
    assert not g.update(_frame(95.0), False, 13.0 + STALE_STILL_AFTER_S - 0.1)
    # a stopped car, a paused game or no data at all is stationary at once, as before
    assert MotionGate(stationary=True).update(_frame(0.0), False, 0.0)
    assert MotionGate(stationary=False).update(_frame(150.0, quality=FrameQuality.PAUSED), False, 0.0)
    assert MotionGate(stationary=False).update(None, False, 0.0)


# ---------------------------------------------------------------------------------------------- odds and ends
def test_a_radio_check_and_quiet_need_no_session() -> None:
    """UX review H4: before any session, "Radio check" and "Stop talking" are answered (an empty fact sheet)."""
    for q in ("Radio check.", "Stop talking.", "You can talk again."):
        sheet = no_session_sheet(detect_intent(q))
        assert sheet is not None and sheet.facts == [], q
    assert no_session_sheet(detect_intent("Quiet for three laps.")) is None  # needs a lap to count from
    assert no_session_sheet(detect_intent("What's my fuel?")) is None


def test_segment_level_for_the_diagnostics() -> None:
    sr = 16_000
    t = np.arange(sr) / sr
    tone = (0.1 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)  # std 0.0707: -23 dBFS
    peak, voiced = segment_level(tone)
    assert peak == pytest.approx(-23.0, abs=0.1) and voiced == pytest.approx(1.0, abs=0.02)
    quiet = (10 ** (-55 / 20) * np.sqrt(2) * np.sin(2 * np.pi * 300 * t)).astype(np.float32)  # -55 dBFS
    assert segment_level(quiet) == (pytest.approx(-55.0, abs=0.1), 0.0)
    assert segment_level(np.zeros(10, dtype=np.float32)) == (-120.0, 0.0)


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
