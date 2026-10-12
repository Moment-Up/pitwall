"""Radio scheduler (priority, quiet mode, intensity, speak window, pacing, dedupe) and proactive message builders."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import pytest

from pitwall.analysis.coaching import Observation
from pitwall.voice.proactive import (
    LAP_MESSAGE_TTL_S,
    coaching_text,
    fmt_lap_time,
    intensity_ack,
    lap_messages,
    lap_summary_text,
    quiet_ack,
    resume_ack,
)
from pitwall.voice.scheduler import (
    MAX_SPEECH_LATENCY_S,
    SPEECH_LATENCY_S,
    RadioScheduler,
    estimate_speech_s,
    parse_intensity,
    speak_window_ok,
    spoken_word_count,
)
from pitwall.voice.speech import to_speech
from pitwall.voice.types import DrivingState, MessageKind, Priority, RadioMessage

CALM = DrivingState(
    on_track=True,
    speed_kph=250.0,
    brake=0.0,
    steering=0.01,
    lap_number=5,
    lap_distance_m=800.0,
    time_to_next_braking_s=None,
)
BRAKING = replace(CALM, brake=0.9, speed_kph=180.0)
CORNERING = replace(CALM, steering=-0.4)
IN_MENUS = replace(BRAKING, on_track=False)


def mk(
    msg_id: str,
    kind: MessageKind = MessageKind.LAP_SUMMARY,
    priority: Priority = Priority.NORMAL,
    text: str | None = None,
    created: float = 0.0,
    expires: float | None = None,
    lap: int | None = None,
    bypass: bool = False,
    window: bool = True,
    meta: dict[str, object] | None = None,
) -> RadioMessage:
    t = text if text is not None else f"Message {msg_id}."
    return RadioMessage(
        id=msg_id,
        kind=kind,
        priority=priority,
        text=t,
        speech=t,
        created_mono=created,
        expires_mono=expires,
        lap_number=lap,
        bypass_quiet=bypass,
        needs_speak_window=window,
        meta=meta or {},
    )


def drain(s: RadioScheduler, state: DrivingState = CALM, start: float = 0.0, step: float = 5.0) -> list[str]:
    """Dispatch until the queue yields nothing, leaving enough time between calls for the pacing gap."""
    out: list[str] = []
    t = start
    for _ in range(50):
        m = s.next_message(state, t, speaking=False)
        if m is None:
            break
        out.append(m.id)
        t += step
    return out


# ================================================================ speech duration and speak window
def test_speech_duration_from_word_count_with_floor() -> None:
    assert estimate_speech_s("Copy.") == 1.0
    assert estimate_speech_s(" ".join(["word"] * 26)) == pytest.approx(10.0)
    assert estimate_speech_s("") == 1.0


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("turn 4: minimum speed 8 k p h down, costing 0.08 seconds.", 15),  # 0.08 = zero point zero eight
        ("Lap 12, one twenty-nine point four.", 7),  # hyphenated words are said as two
        ("you're 105 metres", 6),  # one hundred and five
        ("plus 0.2 laps", 5),
        ("12.3 percent", 4),
        ("lap 1,000", 3),
        ("", 0),
        ("1" * 40, 40),  # absurd digit runs: one word per digit, and no giant int is built
    ],
)
def test_spoken_word_count_expands_numbers(text: str, words: int) -> None:
    assert spoken_word_count(text) == words


# Durations of the default TTS (``say -v Daniel -r 200``), measured on the M4 Max for real radio lines.
MEASURED_SAY_S = [
    ("turn 4: minimum speed 8 k p h down, costing 0.08 seconds.", 5.27),
    ("Lap 4, one oh five point seven, plus zero point zero eight to your reference.", 4.75),
    ("Lap 12, one twenty-nine point four, personal best, minus zero point one two to your reference. "
     "Flashback used.", 7.19),
    ("Fuel critical: 0.8 laps short to the finish.", 3.17),
    ("turn 11: full throttle 22 metres later than your reference, costing 0.10 seconds. "
     "Same on 4 of the last 5 laps.", 8.55),
    ("Copy, quiet until lap 8. Urgent calls only.", 3.01),
    ("Red flag, red flag.", 1.40),
    ("Brake.", 0.47),
]  # fmt: skip


@pytest.mark.parametrize(("speech", "measured_s"), MEASURED_SAY_S)
def test_speech_estimate_is_not_shorter_than_measured_tts(speech: str, measured_s: float) -> None:
    assert measured_s <= estimate_speech_s(speech) <= measured_s * 1.5 + 0.6


def test_speak_window_always_open_off_track() -> None:
    assert speak_window_ok(IN_MENUS, 30.0)
    assert speak_window_ok(replace(IN_MENUS, brake=None, steering=None, time_to_next_braking_s=0.1), 5.0)


@pytest.mark.parametrize(
    ("brake", "steering", "ok"),
    [
        (0.0, 0.0, True),
        (0.049, 0.119, True),
        (0.05, 0.0, False),  # boundary: must be strictly below
        (0.9, 0.0, False),
        (0.0, 0.12, False),
        (0.0, -0.3, False),  # steering magnitude, either direction
        (0.0, -0.11, True),
    ],
)
def test_speak_window_needs_off_brake_and_straight(brake: float, steering: float, ok: bool) -> None:
    assert speak_window_ok(replace(CALM, brake=brake, steering=steering), 2.0) is ok


@pytest.mark.parametrize(
    "state",
    [
        replace(CALM, brake=None),
        replace(CALM, steering=None),
        replace(CALM, brake=math.nan),
        replace(CALM, steering=math.nan),
        replace(CALM, time_to_next_braking_s=math.nan),
    ],
)
def test_speak_window_unknown_inputs_on_track_are_not_calm(state: DrivingState) -> None:
    assert not speak_window_ok(state, 1.0)


def test_speak_window_must_finish_before_next_braking_zone() -> None:
    assert speak_window_ok(replace(CALM, time_to_next_braking_s=None), 3.0)  # no track model yet
    assert speak_window_ok(replace(CALM, time_to_next_braking_s=4.0), 3.0)  # 3 s + 1 s margin
    assert not speak_window_ok(replace(CALM, time_to_next_braking_s=3.9), 3.0)


def test_speak_window_counts_time_before_audio_starts() -> None:
    assert speak_window_ok(replace(CALM, time_to_next_braking_s=4.6), 3.0, lead_s=0.6)
    assert not speak_window_ok(replace(CALM, time_to_next_braking_s=4.5), 3.0, lead_s=0.6)
    assert speak_window_ok(replace(IN_MENUS, time_to_next_braking_s=0.0), 3.0, lead_s=0.6)


def test_scheduler_leaves_time_for_synthesis_and_number_heavy_speech() -> None:
    """Review case: a 5.27 s coaching line (+0.37 s synthesis) was approved with 5.62 s to the braking zone."""
    (coach,) = [
        m for m in lap_messages(lap(), OBSERVATIONS, None, None, "normal", 0.0) if m.kind is MessageKind.COACHING
    ]
    s = RadioScheduler()
    assert s.enqueue(coach)
    measured_end = 0.37 + 5.27  # synthesis + audio of this sentence with ``say``
    for ttb in (5.62, 5.7, measured_end + 1.0):
        assert s.next_message(replace(CALM, time_to_next_braking_s=ttb), 0.0, speaking=False) is None
    needed = s.speech_latency_s + estimate_speech_s(coach.speech) + 1.0
    assert needed >= measured_end + 1.0
    m = s.next_message(replace(CALM, time_to_next_braking_s=needed), 0.0, speaking=False)
    assert m is not None and m.id == coach.id


def test_speech_latency_allowance_is_configurable_and_learns() -> None:
    s = RadioScheduler()
    assert s.speech_latency_s == SPEECH_LATENCY_S
    assert s.observe_speech_latency(1.6) == pytest.approx(SPEECH_LATENCY_S + 0.3 * (1.6 - SPEECH_LATENCY_S))
    before = s.speech_latency_s
    for bad in (math.nan, math.inf, -1.0):
        assert s.observe_speech_latency(bad) == before  # ignored
    for _ in range(50):
        s.observe_speech_latency(60.0)  # a stalled measurement is capped
    assert s.speech_latency_s <= MAX_SPEECH_LATENCY_S
    assert RadioScheduler(speech_latency_s=0.0).speech_latency_s == 0.0
    for bad in (-0.1, math.nan, MAX_SPEECH_LATENCY_S + 1):
        with pytest.raises(ValueError):
            RadioScheduler(speech_latency_s=bad)


# ================================================================ basic dispatch
def test_nothing_while_speaking_then_gap_after_speech() -> None:
    s = RadioScheduler()
    s.enqueue(mk("a"))
    assert s.next_message(CALM, 10.0, speaking=True) is None
    assert s.next_message(CALM, 11.0, speaking=False) is None  # 2 s of silence after speech ended at 10.0
    m = s.next_message(CALM, 12.0, speaking=False)
    assert m is not None and m.id == "a"
    assert s.pending() == []


def test_answers_wait_for_speech_to_end_but_not_for_the_gap() -> None:
    s = RadioScheduler()
    s.enqueue(mk("ans", MessageKind.ANSWER, Priority.HIGH, window=False))
    assert s.next_message(CALM, 10.0, speaking=True) is None
    m = s.next_message(CALM, 10.1, speaking=False)
    assert m is not None and m.id == "ans"


def test_expired_messages_are_dropped() -> None:
    s = RadioScheduler()
    s.enqueue(mk("old", created=0.0, expires=5.0))
    assert s.next_message(BRAKING, 4.0, speaking=False) is None  # held by the speak window
    assert len(s.pending()) == 1
    assert s.next_message(CALM, 6.0, speaking=False) is None
    assert s.pending() == []


def test_highest_priority_first_fifo_within_priority() -> None:
    s = RadioScheduler("detailed")
    s.enqueue(mk("info", MessageKind.INFO, Priority.LOW))
    s.enqueue(mk("sum4", MessageKind.LAP_SUMMARY, Priority.NORMAL, lap=4))
    s.enqueue(mk("coach-a", MessageKind.COACHING, Priority.NORMAL, lap=4))
    s.enqueue(mk("alert", MessageKind.ALERT, Priority.HIGH))
    s.enqueue(mk("coach-b", MessageKind.COACHING, Priority.NORMAL, lap=4))
    assert [m.id for m in s.pending()] == ["alert", "sum4", "coach-a", "coach-b", "info"]
    assert drain(s) == ["alert", "sum4", "coach-a", "coach-b", "info"]


def test_pending_is_a_snapshot() -> None:
    s = RadioScheduler()
    s.enqueue(mk("a"))
    snap = s.pending()
    snap.clear()
    assert [m.id for m in s.pending()] == ["a"]


def test_clear_drops_everything() -> None:
    s = RadioScheduler()
    s.enqueue(mk("a", lap=1))
    s.enqueue(mk("b", MessageKind.ALERT))
    assert s.clear() == 2
    assert s.next_message(CALM, 0.0, speaking=False) is None


# ================================================================ quiet mode
def test_quiet_until_lap_suppresses_all_but_bypass_messages() -> None:
    s = RadioScheduler()
    s.set_quiet(until_lap=8, indefinite=False)  # e.g. "quiet for 3 laps" on lap 5
    assert s.is_quiet(5) and s.is_quiet(7)
    assert not s.is_quiet(8)
    s.enqueue(mk("sum", lap=6))
    s.enqueue(mk("fuel", MessageKind.ALERT, Priority.HIGH, bypass=True))
    on_lap_6 = replace(CALM, lap_number=6)
    m = s.next_message(on_lap_6, 0.0, speaking=False)
    assert m is not None and m.id == "fuel"
    assert s.next_message(on_lap_6, 10.0, speaking=False) is None
    assert s.quiet_state(6) == {"until_lap": 8, "indefinite": False}
    # lap 8 starts: quiet lapses on its own and the queued summary goes out
    m = s.next_message(replace(CALM, lap_number=8), 20.0, speaking=False)
    assert m is not None and m.id == "sum"
    assert s.quiet is None
    assert s.quiet_state(8) == {"until_lap": None, "indefinite": False}


def test_quiet_state_reports_elapsed_period_as_off_before_next_tick() -> None:
    s = RadioScheduler()
    s.set_quiet(until_lap=8)
    assert s.quiet_state(9) == {"until_lap": None, "indefinite": False}
    assert s.quiet_state(None) == {"until_lap": 8, "indefinite": False}


def test_quiet_indefinite_until_resume() -> None:
    s = RadioScheduler()
    s.set_quiet(until_lap=None, indefinite=True)
    assert s.is_quiet(1) and s.is_quiet(500) and s.is_quiet(None)
    assert s.quiet_state(3) == {"until_lap": None, "indefinite": True}
    s.enqueue(mk("sum", lap=4))
    assert s.next_message(replace(CALM, lap_number=99), 0.0, speaking=False) is None
    s.resume()
    assert not s.is_quiet(99)
    m = s.next_message(CALM, 5.0, speaking=False)
    assert m is not None and m.id == "sum"


def test_quiet_with_unknown_lap_stays_quiet() -> None:
    s = RadioScheduler()
    s.set_quiet(until_lap=3)
    s.enqueue(mk("sum", lap=2))
    assert s.next_message(replace(CALM, lap_number=None), 0.0, speaking=False) is None
    assert s.quiet is not None


def test_quiet_needs_a_lap_or_indefinite() -> None:
    with pytest.raises(ValueError):
        RadioScheduler().set_quiet(until_lap=None, indefinite=False)


def test_indefinite_wins_over_until_lap() -> None:
    s = RadioScheduler()
    s.set_quiet(until_lap=4, indefinite=True)
    assert s.is_quiet(10)
    assert s.quiet_state(10) == {"until_lap": None, "indefinite": True}


# ================================================================ intensity
def test_parse_intensity() -> None:
    assert parse_intensity(" Detailed ") == "detailed"
    with pytest.raises(ValueError):
        parse_intensity("chatty")
    with pytest.raises(ValueError):
        RadioScheduler("loud")
    s = RadioScheduler()
    with pytest.raises(ValueError):
        s.set_intensity("max")
    assert s.intensity == "normal"  # unchanged by the rejected value
    t = RadioScheduler("detailed")
    assert t.set_intensity("QUIET") == "quiet"
    assert t.intensity == "quiet"


def test_quiet_intensity_only_answers_controls_alerts() -> None:
    s = RadioScheduler("quiet")
    s.enqueue(mk("sum", MessageKind.LAP_SUMMARY, lap=4))
    s.enqueue(mk("coach", MessageKind.COACHING, lap=4))
    s.enqueue(mk("info", MessageKind.INFO, Priority.LOW))
    s.enqueue(mk("alert", MessageKind.ALERT))
    s.enqueue(mk("ctl", MessageKind.CONTROL, window=False))
    s.enqueue(mk("ans", MessageKind.ANSWER, window=False))
    assert drain(s) == ["ctl", "ans", "alert"]  # same priority: answers and acknowledgements rank first
    assert {m.id for m in s.pending()} == {"sum", "coach", "info"}  # kept: the setting may change
    s.set_intensity("normal")
    assert drain(s, start=100.0) == ["sum", "coach"]


def test_normal_intensity_one_coaching_point_per_lap() -> None:
    s = RadioScheduler("normal")
    s.enqueue(mk("sum4", MessageKind.LAP_SUMMARY, lap=4))
    s.enqueue(mk("c4a", MessageKind.COACHING, lap=4))
    s.enqueue(mk("c4b", MessageKind.COACHING, lap=4))
    s.enqueue(mk("info", MessageKind.INFO, Priority.LOW))
    assert drain(s) == ["sum4", "c4a"]
    assert {m.id for m in s.pending()} == {"c4b", "info"}
    s.enqueue(mk("c5", MessageKind.COACHING, lap=5, created=100.0))
    # a new lap has its own budget (and superseded c4b); said while driving the next lap
    assert drain(s, replace(CALM, lap_number=6), start=100.0) == ["c5"]
    assert [m.id for m in s.pending()] == ["info"]


def test_coaching_budget_falls_back_to_current_lap() -> None:
    s = RadioScheduler("normal")
    s.enqueue(mk("a", MessageKind.COACHING))
    s.enqueue(mk("b", MessageKind.COACHING))
    assert drain(s, replace(CALM, lap_number=7)) == ["a"]
    assert drain(s, replace(CALM, lap_number=8), start=50.0) == ["b"]


def test_detailed_intensity_all_coaching_and_info() -> None:
    s = RadioScheduler("detailed")
    for i in range(3):
        s.enqueue(mk(f"c{i}", MessageKind.COACHING, lap=4))
    s.enqueue(mk("info", MessageKind.INFO, Priority.LOW))
    assert drain(s) == ["c0", "c1", "c2", "info"]


def test_cues_are_not_filtered_by_coaching_intensity_or_gap() -> None:
    s = RadioScheduler("quiet")
    s.enqueue(mk("alert", MessageKind.ALERT, text="Yellow flag."))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    s.enqueue(mk("cue", MessageKind.CUE, Priority.HIGH, text="Brake.", window=False, created=0.5))
    m = s.next_message(BRAKING, 0.5, speaking=False)
    assert m is not None and m.id == "cue"


# ================================================================ speak window and urgency
def test_proactive_waits_for_speak_window() -> None:
    s = RadioScheduler()
    s.enqueue(mk("sum", lap=4))
    assert s.next_message(BRAKING, 0.0, speaking=False) is None
    assert s.next_message(CORNERING, 0.5, speaking=False) is None
    m = s.next_message(CALM, 1.0, speaking=False)
    assert m is not None and m.id == "sum"


def test_menus_and_pits_are_a_speak_window() -> None:
    s = RadioScheduler()
    s.enqueue(mk("sum", lap=4))
    m = s.next_message(IN_MENUS, 0.0, speaking=False)
    assert m is not None


def test_urgent_ignores_speak_window_and_gap() -> None:
    s = RadioScheduler()
    s.enqueue(mk("sum", lap=4, text="Lap 4, 1:05.706."))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    s.enqueue(mk("flag", MessageKind.ALERT, Priority.URGENT, text="Red flag, red flag.", created=0.2))
    m = s.next_message(BRAKING, 0.2, speaking=False)
    assert m is not None and m.id == "flag"


def test_high_priority_alert_still_needs_speak_window() -> None:
    s = RadioScheduler()
    s.enqueue(mk("fuel", MessageKind.ALERT, Priority.HIGH))
    assert s.next_message(BRAKING, 0.0, speaking=False) is None


def test_messages_without_window_requirement_go_while_braking() -> None:
    s = RadioScheduler()
    s.enqueue(mk("ack", MessageKind.CONTROL, Priority.HIGH, window=False, bypass=True))
    assert s.next_message(BRAKING, 0.0, speaking=False) is not None


def test_highest_priority_eligible_message_wins_when_top_one_is_too_long() -> None:
    s = RadioScheduler()
    long_text = "Turn four, minimum speed eight kilometres an hour down, costing nought point oh eight seconds."
    s.enqueue(mk("long", MessageKind.ALERT, Priority.HIGH, text=long_text))
    s.enqueue(mk("short", MessageKind.LAP_SUMMARY, Priority.NORMAL, text="Good lap.", lap=4))
    straight_before_t1 = replace(CALM, time_to_next_braking_s=3.0)  # long needs ~7.4 s incl. margin, short 2.6 s
    m = s.next_message(straight_before_t1, 0.0, speaking=False)
    assert m is not None and m.id == "short"
    m = s.next_message(replace(CALM, time_to_next_braking_s=8.0), 10.0, speaking=False)
    assert m is not None and m.id == "long"


# ================================================================ pacing
def test_minimum_gap_after_estimated_speech_end() -> None:
    s = RadioScheduler()
    text = "Lap 4, one oh five point seven."  # 7 words -> 2.69 s
    s.enqueue(mk("a", text=text, lap=4))
    s.enqueue(mk("b", MessageKind.COACHING, text="Turn four, minimum speed down."))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    end = s.speech_latency_s + estimate_speech_s(text)  # audio starts after synthesis + transport
    assert s.next_message(CALM, 1.0, speaking=False) is None
    assert s.next_message(CALM, end + 1.99, speaking=False) is None
    m = s.next_message(CALM, end + 2.0, speaking=False)
    assert m is not None and m.id == "b"


def test_reported_playback_extends_the_gap() -> None:
    s = RadioScheduler()
    s.enqueue(mk("a", lap=4))
    s.enqueue(mk("b", MessageKind.COACHING))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    assert s.next_message(CALM, 8.0, speaking=True) is None  # TTS took longer than estimated
    assert s.next_message(CALM, 9.9, speaking=False) is None
    m = s.next_message(CALM, 10.0, speaking=False)
    assert m is not None and m.id == "b"


def test_custom_gap() -> None:
    s = RadioScheduler(min_gap_s=0.0, speech_latency_s=0.0)
    s.enqueue(mk("a", lap=4, text="One."))
    s.enqueue(mk("b", MessageKind.COACHING, text="Two."))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    assert s.next_message(CALM, 1.0, speaking=False) is not None


# ================================================================ dedupe / supersede
def test_later_lap_summary_supersedes_unspoken_one() -> None:
    s = RadioScheduler()
    assert s.enqueue(mk("sum4", lap=4))
    assert s.enqueue(mk("c4", MessageKind.COACHING, lap=4))
    assert s.enqueue(mk("sum5", lap=5))
    assert [m.id for m in s.pending()] == ["sum5", "c4"]  # coaching only superseded by later coaching
    assert s.enqueue(mk("c5", MessageKind.COACHING, lap=5))
    assert [m.id for m in s.pending()] == ["sum5", "c5"]


def test_newest_lap_supersedes_whatever_its_number() -> None:
    """Laps arrive in completion order; lap numbers restart at 1 in the next session (or a time-trial restart)."""
    s = RadioScheduler()
    assert s.enqueue(mk("sum12", lap=12))
    assert s.enqueue(mk("next-session-sum1", lap=1))
    assert [m.id for m in s.pending()] == ["next-session-sum1"]


def test_lap_identity_prefers_lap_id_over_number() -> None:
    s = RadioScheduler("detailed")
    assert s.enqueue(mk("a-sum", lap=3, meta={"lap_id": 103}))
    assert s.enqueue(mk("a-c", MessageKind.COACHING, lap=3, meta={"lap_id": 103}))
    assert s.enqueue(mk("b-c", MessageKind.COACHING, lap=3, meta={"lap_id": 203}))  # same number, other session
    assert [m.id for m in s.pending()] == ["a-sum", "b-c"]


def test_same_lap_does_not_supersede() -> None:
    s = RadioScheduler("detailed")
    s.enqueue(mk("c4a", MessageKind.COACHING, lap=4))
    s.enqueue(mk("c4b", MessageKind.COACHING, lap=4))
    assert len(s.pending()) == 2


def test_identical_text_not_repeated_within_60_s() -> None:
    s = RadioScheduler()
    text = "Fuel is tight: plus 0.2 laps to the finish."
    s.enqueue(mk("f1", MessageKind.ALERT, text=text))
    assert not s.enqueue(mk("f2", MessageKind.ALERT, text=f"  {text.upper()} "))  # identical while pending
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    assert not s.enqueue(mk("f3", MessageKind.ALERT, text=text, created=30.0))
    assert not s.enqueue(mk("f4", MessageKind.ALERT, text=text, created=59.9))
    assert s.enqueue(mk("f5", MessageKind.ALERT, text=text, created=60.0))


def test_driver_initiated_messages_may_repeat() -> None:
    s = RadioScheduler()
    text = "Plus 1.2 laps of fuel."
    s.enqueue(mk("a1", MessageKind.ANSWER, text=text, window=False))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    assert s.enqueue(mk("a2", MessageKind.ANSWER, text=text, window=False, created=5.0))


def test_proactive_repeat_of_what_an_answer_just_said_is_dropped() -> None:
    s = RadioScheduler()
    text = "Fuel is tight: plus 0.2 laps to the finish."
    s.enqueue(mk("alert", MessageKind.ALERT, Priority.NORMAL, text=text))
    s.enqueue(mk("ans", MessageKind.ANSWER, Priority.HIGH, text=text, window=False))
    m = s.next_message(CALM, 0.0, speaking=False)
    assert m is not None and m.id == "ans"
    assert s.next_message(CALM, 20.0, speaking=False) is None
    assert s.pending() == []


def test_duplicate_id_and_stale_messages_rejected() -> None:
    s = RadioScheduler()
    assert s.enqueue(mk("x", text="One."))
    assert not s.enqueue(mk("x", text="Two."))
    assert not s.enqueue(mk("stale", created=10.0, expires=9.0))


def test_queue_is_bounded_least_important_oldest_evicted() -> None:
    s = RadioScheduler("detailed", max_pending=3)
    for i in range(3):
        assert s.enqueue(mk(f"n{i}", MessageKind.ALERT))
    assert not s.enqueue(mk("low", MessageKind.INFO, Priority.LOW))  # least important: itself evicted
    assert s.enqueue(mk("high", MessageKind.ALERT, Priority.HIGH))
    assert [m.id for m in s.pending()] == ["high", "n1", "n2"]


def test_cues_and_urgent_alerts_may_repeat() -> None:
    """Review case: a second "Brake." 20 s later and a second yellow at the same corner were rejected."""
    s = RadioScheduler()
    s.enqueue(mk("cue1", MessageKind.CUE, Priority.HIGH, text="Brake.", window=False))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    assert s.enqueue(mk("cue2", MessageKind.CUE, Priority.HIGH, text="Brake.", window=False, created=20.0))
    m = s.next_message(CALM, 20.0, speaking=False)
    assert m is not None and m.id == "cue2"
    s.enqueue(mk("y1", MessageKind.ALERT, Priority.URGENT, text="Yellow flag, turn 4.", created=21.0))
    m = s.next_message(CALM, 21.0, speaking=False)
    assert m is not None and m.id == "y1"
    assert s.enqueue(mk("y2", MessageKind.ALERT, Priority.URGENT, text="Yellow flag, turn 4.", created=40.0))
    m = s.next_message(CALM, 40.0, speaking=False)
    assert m is not None and m.id == "y2"
    # ordinary proactive messages keep the repeat window
    s.enqueue(mk("tight1", MessageKind.ALERT, text="Fuel is tight.", created=41.0))
    m = s.next_message(CALM, 45.0, speaking=False)
    assert m is not None and m.id == "tight1"
    assert not s.enqueue(mk("tight2", MessageKind.ALERT, text="Fuel is tight.", created=50.0))


# ================================================================ order within a lap
LONG_SUMMARY = "Lap 4, one oh five point seven, plus zero point zero eight to your reference."
SHORT_COACHING = "Turn 4, minimum speed down."


def test_coaching_waits_for_its_own_lap_summary() -> None:
    """Review case: on a short straight the shorter coaching point used to jump ahead of the lap time."""
    s = RadioScheduler()
    s.enqueue(mk("sum4", lap=4, text=LONG_SUMMARY))
    s.enqueue(mk("c4", MessageKind.COACHING, lap=4, text=SHORT_COACHING))
    need_summary = s.speech_latency_s + estimate_speech_s(LONG_SUMMARY) + 1.0
    need_coaching = s.speech_latency_s + estimate_speech_s(SHORT_COACHING) + 1.0
    short_straight = replace(CALM, time_to_next_braking_s=(need_coaching + need_summary) / 2)
    assert s.next_message(short_straight, 0.0, speaking=False) is None
    m = s.next_message(replace(CALM, time_to_next_braking_s=need_summary), 1.0, speaking=False)
    assert m is not None and m.id == "sum4"
    released = 1.0 + s.speech_latency_s + estimate_speech_s(LONG_SUMMARY) + 2.0
    m = s.next_message(short_straight, released, speaking=False)
    assert m is not None and m.id == "c4"


def test_summary_blocks_only_its_own_lap_and_only_while_it_can_be_said() -> None:
    s = RadioScheduler()
    s.enqueue(mk("c4", MessageKind.COACHING, lap=4, text=SHORT_COACHING))
    s.enqueue(mk("sum5", lap=5, text=LONG_SUMMARY))
    short_straight = replace(CALM, time_to_next_braking_s=4.0)
    m = s.next_message(short_straight, 0.0, speaking=False)
    assert m is not None and m.id == "c4"  # another lap's summary does not hold it

    q = RadioScheduler()
    q.set_quiet(indefinite=True)
    q.enqueue(mk("sum4", lap=4, text=LONG_SUMMARY))  # held by quiet mode: it would block forever
    q.enqueue(mk("c4", MessageKind.COACHING, lap=4, text=SHORT_COACHING, bypass=True))
    m = q.next_message(short_straight, 0.0, speaking=False)
    assert m is not None and m.id == "c4"


# ================================================================ interrupting playback
def test_urgent_alert_interrupts_a_lap_summary() -> None:
    """Review case: a red flag waited for a ~6 s lap summary to finish."""
    s = RadioScheduler()
    s.enqueue(mk("sum", lap=4, text=LONG_SUMMARY))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    s.enqueue(mk("red", MessageKind.ALERT, Priority.URGENT, text="Red flag, red flag.", created=1.0))
    m = s.next_message(BRAKING, 1.0, speaking=True)
    assert m is not None and m.id == "red"


def test_cue_interrupts_coaching() -> None:
    s = RadioScheduler()
    s.enqueue(mk("c4", MessageKind.COACHING, lap=4, text=SHORT_COACHING))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    s.enqueue(mk("cue", MessageKind.CUE, Priority.HIGH, text="Brake.", window=False, created=1.0))
    m = s.next_message(BRAKING, 1.0, speaking=True)
    assert m is not None and m.id == "cue"


def test_nothing_else_interrupts() -> None:
    s = RadioScheduler("detailed")
    s.enqueue(mk("sum", lap=4))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    others = [
        (MessageKind.ALERT, Priority.HIGH),
        (MessageKind.ANSWER, Priority.HIGH),
        (MessageKind.CONTROL, Priority.HIGH),
        (MessageKind.COACHING, Priority.NORMAL),
        (MessageKind.INFO, Priority.LOW),
    ]
    for i, (kind, prio) in enumerate(others):
        s.enqueue(mk(f"x{i}", kind, prio, window=False, bypass=True))
    assert s.next_message(CALM, 1.0, speaking=True) is None
    assert len(s.pending()) == len(others)


def test_equal_or_lower_rank_never_cuts_off_the_message_on_air() -> None:
    s = RadioScheduler()
    s.enqueue(mk("red", MessageKind.ALERT, Priority.URGENT, text="Red flag."))
    s.enqueue(mk("yellow", MessageKind.ALERT, Priority.URGENT, text="Yellow flag, turn 4."))
    first = s.next_message(CALM, 0.0, speaking=False)
    assert first is not None and first.id == "red"
    s.enqueue(mk("cue", MessageKind.CUE, Priority.HIGH, text="Brake.", window=False))
    assert s.next_message(CALM, 0.5, speaking=True) is None  # neither the second urgent call nor a cue
    m = s.next_message(CALM, 2.0, speaking=False)
    assert m is not None and m.id == "yellow"  # straight after: urgent ignores the gap
    assert s.next_message(CALM, 2.1, speaking=True) is None
    m = s.next_message(CALM, 4.0, speaking=False)
    assert m is not None and m.id == "cue"


def test_cue_does_not_cut_a_cue_but_urgent_does() -> None:
    s = RadioScheduler()
    s.enqueue(mk("cue1", MessageKind.CUE, Priority.HIGH, text="Brake.", window=False))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    s.enqueue(mk("cue2", MessageKind.CUE, Priority.HIGH, text="Lift.", window=False, created=0.2))
    assert s.next_message(CALM, 0.2, speaking=True) is None
    s.enqueue(mk("red", MessageKind.ALERT, Priority.URGENT, text="Red flag.", created=0.3))
    m = s.next_message(CALM, 0.3, speaking=True)
    assert m is not None and m.id == "red"


def test_urgent_interrupts_playback_the_scheduler_did_not_start() -> None:
    """Answers are said by the hub directly: whatever is playing, an urgent call outranks it."""
    s = RadioScheduler()
    s.enqueue(mk("red", MessageKind.ALERT, Priority.URGENT, text="Red flag."))
    m = s.next_message(CALM, 0.0, speaking=True)
    assert m is not None and m.id == "red"


def test_urgent_is_said_in_quiet_mode() -> None:
    """The quiet acknowledgement promises "urgent calls only", with or without the producer's bypass flag."""
    s = RadioScheduler()
    s.set_quiet(indefinite=True)
    s.enqueue(mk("red", MessageKind.ALERT, Priority.URGENT, text="Red flag."))
    s.enqueue(mk("cue", MessageKind.CUE, Priority.HIGH, text="Brake.", window=False))
    m = s.next_message(CALM, 0.0, speaking=False)
    assert m is not None and m.id == "red"
    assert s.next_message(CALM, 5.0, speaking=False) is None  # a cue needs bypass_quiet


# ================================================================ session change
def test_coaching_budget_survives_lap_numbers_restarting_in_a_new_session() -> None:
    """Review case: laps 1-5 of session B were silent because session A had used up those lap numbers."""
    s = RadioScheduler("normal")
    t = 0.0
    for lap_id_base in (100, 200):  # session A, then session B (no reset: lap ids keep them apart)
        for n in range(1, 6):
            o = obs("low_min_speed", -7.6, 0.081, lap_number=n)
            msgs = lap_messages(lap(n, lap_id=lap_id_base + n), [o], None, None, "normal", t)
            for m in msgs:
                assert s.enqueue(m)
            assert drain(s, replace(CALM, lap_number=n + 1), start=t, step=10.0) == [m.id for m in msgs]
            t += 100.0


def test_reset_session_forgets_the_old_session() -> None:
    s = RadioScheduler("normal")
    for n in range(1, 4):  # each point said while driving the next lap
        s.enqueue(mk(f"a{n}", MessageKind.COACHING, lap=n, text=f"Point {n}.", created=10.0 * n))
        assert drain(s, replace(CALM, lap_number=n + 1), start=10.0 * n) == [f"a{n}"]
    s.enqueue(mk("a-sum", lap=3, text="Lap 3.", created=40.0))  # still queued at the session change
    s.set_quiet(until_lap=9)
    assert s.reset_session() == 1
    assert s.pending() == [] and s.quiet is None
    for n in range(1, 4):  # same lap numbers, same sentences, well inside the repeat window
        t = 40.0 + 5.0 * n
        assert s.enqueue(mk(f"b{n}", MessageKind.COACHING, lap=n, text=f"Point {n}.", created=t))
        assert drain(s, replace(CALM, lap_number=n + 1), start=t) == [f"b{n}"]


def test_reset_session_keeps_standing_preferences() -> None:
    s = RadioScheduler("detailed", speech_latency_s=0.4)
    s.set_quiet(indefinite=True)  # "until you call me" outlives the session
    assert s.reset_session() == 0
    assert s.quiet is not None and s.quiet.indefinite
    assert s.intensity == "detailed" and s.speech_latency_s == 0.4


# ================================================================ proactive: lap summary
def lap(
    n: int = 4,
    ms: int | None = 65_706,
    *,
    lap_id: int = 104,
    clean: bool = True,
    valid: bool | None = True,
    flags: list[str] | None = None,
    final: bool | None = False,
) -> dict[str, Any]:
    return {
        "lap_id": lap_id,
        "lap_number": n,
        "lap_time_ms": ms,
        "sector_times_ms": [20_000, 25_000, 20_706],
        "valid": valid,
        "clean": clean,
        "flags": flags or [],
        "final": final,
        "tyre_compound": "soft",
        "fuel_used_kg": 1.4,
    }


REF = {"lap_id": 101, "lap_number": 2, "lap_time_ms": 65_626, "session_id": "s1"}


def test_fmt_lap_time() -> None:
    assert fmt_lap_time(65_706) == "1:05.706"
    assert fmt_lap_time(59_123) == "59.123"
    assert fmt_lap_time(600_000) == "10:00.000"


def test_lap_summary_against_reference() -> None:
    assert lap_summary_text(lap(), 65_000, REF) == "That lap, 1:05.706, plus 0.080 to your reference."
    assert lap_summary_text(lap(ms=65_506), 65_000, REF) == "That lap, 1:05.506, minus 0.120 to your reference."
    assert lap_summary_text(lap(ms=65_626), 65_000, REF) == "That lap, 1:05.626, level with your reference."


def test_lap_summary_without_usable_reference() -> None:
    assert lap_summary_text(lap(), None, None) == "That lap, 1:05.706."
    assert lap_summary_text(lap(), None, {**REF, "lap_time_ms": None}) == "That lap, 1:05.706."
    assert lap_summary_text(lap(), None, {**REF, "lap_id": 104}) == "That lap, 1:05.706."  # the lap is the reference


def test_lap_summary_personal_best() -> None:
    # best_clean_ms may already include this lap (the hub computes it after the lap is published)
    assert (
        lap_summary_text(lap(ms=65_506), 65_506, REF)
        == (
            "That lap, 1:05.506, personal best, 0.120 faster than before."  # never "personal best, minus 0.120 to your best"
        )
    )
    sam = {**REF, "own": False, "label_to": "Sam's best"}  # another driver's lap: the delta to them stays
    assert (
        lap_summary_text(lap(ms=65_506), 65_506, sam) == "That lap, 1:05.506, personal best, minus 0.120 to Sam's best."
    )
    assert "personal best" in (lap_summary_text(lap(ms=65_400), 65_506, REF) or "")
    assert "personal best" not in (lap_summary_text(lap(ms=65_600), 65_506, REF) or "")
    assert "personal best" not in (lap_summary_text(lap(ms=65_400), None, REF) or "")
    # the lap is the reference, or there is none yet: the best clean lap there is
    assert lap_summary_text(lap(), 65_706, {**REF, "lap_id": 104}) == "That lap, 1:05.706, personal best."
    assert lap_summary_text(lap(), 65_706, None) == "That lap, 1:05.706, personal best."


def test_lap_summary_session_best_when_the_reference_is_faster() -> None:
    """Real F1 25 Austria scenario (20261010-221749): the session's best clean lap, still 4.6 s off a faster
    reference from another session, was called a personal best ("..., personal best, plus 4.580 ...")."""
    ref = {"lap_id": 7, "lap_number": 63, "lap_time_ms": 71_745, "session_id": "earlier"}
    assert lap_summary_text(lap(62, 76_325, lap_id=200), 76_325, ref) == (
        "That lap, 1:16.325, session best, plus 4.580 to your reference."
    )


def test_lap_summary_notes_and_no_best_for_compromised_laps() -> None:
    invalid = lap(ms=64_000, clean=False, valid=False, flags=["invalid"])
    assert lap_summary_text(invalid, 65_506, REF) == (
        "That lap, 1:04.000, minus 1.626 to your reference. That lap was invalidated."
    )
    fb = lap(clean=False, flags=["flashback"])
    assert lap_summary_text(fb, 70_000, REF) == "That lap, 1:05.706, plus 0.080 to your reference. Flashback used."


# Real F1 25 lap times from the owner's captures (the game's own lap history; the drive-through is made up, no capture
# has one), worded as the radio now says them.
@pytest.mark.parametrize(
    ("the_lap", "want"),
    [
        # Imola race lap 1 from the grid (20261011-195612)
        (lap(1, 86_788, clean=False, flags=["standing_start"]), "Opening lap, 1:26.788."),
        # Imola lap 14: into the pits at 4810 m
        (lap(14, 94_412, clean=False, flags=["pit_in"]), "In-lap, 1:34.412."),
        # Imola lap 15: out of the pit lane at 449 m (the game's driverStatus: 3 = out lap)
        (lap(15, 105_838, clean=False, flags=["pit_out"]), "Out-lap, 1:45.838."),
        # a drive-through: into and out of the pit lane within one lap
        (lap(9, 98_000, clean=False, flags=["pit_in", "pit_out"]), "Pit lap, 1:38.000."),
        # Imola lap 32 at the chequered flag: the game kept the lap number and set resultStatus "finished"
        (lap(32, 80_886, clean=True, final=True), "Final lap, 1:20.886."),
        # Suzuka one-shot qualifying (flying lap 1, invalidated)
        (lap(1, 96_228, clean=False, valid=False, flags=["invalid"]), "That lap, 1:36.228. That lap was invalidated."),
        # Austria scenario lap 65 (20261010-221749, a flashback)
        (lap(65, 74_344, clean=False, flags=["flashback"]), "That lap, 1:14.344. Flashback used."),
    ],
)
def test_lap_summary_names_the_finished_lap_never_its_bare_number(the_lap: dict[str, Any], want: str) -> None:
    """The summary is said after the line, when the game's HUD already shows the next lap: "Lap 66, 1:13.897" sounded
    one lap out. The lap is named by what it was; its game number stays on the message (``lap_number``, meta)."""
    (m,) = lap_messages(the_lap, [], None, None, "normal", 0.0)
    assert m.text == want
    n = the_lap["lap_number"]
    for said in (m.text, m.speech):
        assert not said.startswith(f"Lap {n}") and f"Lap {n}," not in said
    assert m.lap_number == n and m.meta["lap_number"] == n
    assert m.speech == to_speech(want)


def test_lap_summary_final_lap_wins_and_unknown_final_is_not_final() -> None:
    assert (lap_summary_text(lap(5, 80_000, clean=False, flags=["pit_out"], final=True), None, None) or "").startswith(
        "Final lap,"
    )
    assert lap_summary_text(lap(final=None), None, None) == "That lap, 1:05.706."  # the game does not say
    no_flags = {k: v for k, v in lap().items() if k not in ("flags", "final")}  # an older payload
    assert lap_summary_text(no_flags, None, None) == "That lap, 1:05.706."


def test_no_summary_without_lap_time() -> None:
    assert lap_summary_text(lap(ms=None), None, REF) is None
    assert lap_messages(lap(ms=None, flags=["incomplete"]), [], None, REF, "normal", 0.0) == []


# ================================================================ proactive: coaching
def obs(
    kind: str,
    value: float,
    impact: float | None,
    confidence: float = 0.9,
    corner: str = "T4",
    *,
    lap_number: int = 4,
    positive: bool = False,
    exit_delta: float | None = None,
    consistency: tuple[float, str] | None = None,
) -> dict[str, Any]:
    ev: dict[str, Any] = {"time_delta_s": impact}
    if exit_delta is not None:
        ev["exit_speed_delta_kph"] = exit_delta
    return Observation(
        id=f"L{lap_number}:{corner}:{kind}",
        kind=kind,
        corner=corner,
        lap_number=lap_number,
        ref_lap_number=2,
        metric="m",
        value=value,
        unit="",
        impact_s=impact,
        confidence=confidence,
        text=f"{corner}: long dashboard sentence about {kind}.",
        evidence=ev,
        consistency=consistency[1] if consistency else None,
        consistency_ratio=consistency[0] if consistency else None,
        positive=positive,
    ).to_dict()


@pytest.mark.parametrize(
    ("o", "expected"),
    [
        (obs("low_min_speed", -7.6, 0.081), "T4, losing 0.08 s: minimum speed 8 km/h down."),
        (obs("brake_early", -12.2, 0.05), "T4, losing 0.05 s: braking 12 m earlier than your reference."),
        (
            obs("brake_late_overdrive", 10.0, 0.06, exit_delta=-5.2),
            "T4, losing 0.06 s: braking 10 m later but exiting 5 km/h slower.",
        ),
        (
            obs("overspeed_apex", 6.0, 0.04, exit_delta=-4.0),
            "T4, losing 0.04 s: 6 km/h too much into the apex, exit 4 km/h down.",
        ),
        (obs("late_throttle", 22.0, 0.1), "T4, losing 0.10 s: full throttle 22 m later than your reference."),
        (obs("coasting", 18.0, 0.03), "T4, losing 0.03 s: 18 m more coasting than your reference."),
        (obs("exit_gain", 5.0, -0.05, positive=True), "T4, gaining 0.05 s: good exit, 5 km/h up."),
        (obs("low_min_speed", -5.0, None), "T4: minimum speed 5 km/h down."),
        (obs("low_min_speed", -5.0, 0.004), "T4: minimum speed 5 km/h down."),  # rounds to 0.00: not said
        (obs("mystery", 1.0, 0.1), "T4: long dashboard sentence about mystery."),
    ],
)
def test_coaching_text_for_radio(o: dict[str, Any], expected: str) -> None:
    assert coaching_text(o) == expected


def test_coaching_text_without_impact() -> None:
    assert coaching_text(obs("brake_early", -12.2, 0.05), with_impact=False) == (
        "T4: braking 12 m earlier than your reference."
    )


def test_coaching_text_mentions_habit_in_detailed_mode_only() -> None:
    o = obs("low_min_speed", -7.6, 0.081, consistency=(0.8, "4 of the last 5 laps"))
    assert coaching_text(o) == "T4, losing 0.08 s: minimum speed 8 km/h down."
    assert coaching_text(o, detailed=True) == (
        "T4, losing 0.08 s: minimum speed 8 km/h down. Same on 4 of the last 5 laps."
    )
    one_off = obs("low_min_speed", -7.6, 0.081, consistency=(0.33, "1 of the last 3 laps"))
    assert "Same on" not in coaching_text(one_off, detailed=True)


OBSERVATIONS = [
    obs("late_throttle", 30.0, 0.30, confidence=0.55, corner="T2"),  # biggest but not confident enough
    obs("low_min_speed", -7.6, 0.081, corner="T4"),
    obs("brake_early", -10.0, 0.05, corner="T1"),
    obs("exit_gain", 5.0, -0.06, corner="T3", positive=True),
    obs("coasting", 20.0, 0.02, corner="T5", lap_number=3),  # another lap: ignored
]


def test_lap_messages_normal_summary_plus_top_confident_point() -> None:
    msgs = lap_messages(lap(), OBSERVATIONS, 65_000, REF, "normal", 100.0)
    assert [m.text for m in msgs] == [
        "That lap, 1:05.706, plus 0.080 to your reference.",
        "T4, losing 0.08 s: minimum speed 8 km/h down.",
    ]
    summary, coach = msgs
    assert summary.kind is MessageKind.LAP_SUMMARY and coach.kind is MessageKind.COACHING
    assert summary.priority is Priority.NORMAL and coach.priority is Priority.NORMAL
    assert coach.corner == "T4" and coach.meta["observation_id"] == "L4:T4:low_min_speed"
    assert summary.meta["delta_ms"] == 80
    assert summary.meta["lap_id"] == coach.meta["lap_id"] == 104
    for m in msgs:
        assert m.lap_number == 4
        assert m.created_mono == 100.0 and m.expires_mono == 100.0 + LAP_MESSAGE_TTL_S
        assert m.needs_speak_window and not m.bypass_quiet
    assert len({m.id for m in msgs}) == 2
    # display keeps three decimals; speech says the delta the radio way and normalises units / corner names
    assert summary.speech == to_speech("That lap, 1:05.706, +0.080s to your reference.")
    assert "0.080" not in summary.speech and "1:05" not in summary.speech
    assert coach.speech == to_speech(coach.text) and "T4" not in coach.speech


def test_lap_summary_speech_keeps_notes_and_level_wording() -> None:
    (m,) = lap_messages(lap(ms=65_626, clean=False, flags=["flashback"]), [], None, REF, "normal", 0.0)
    assert m.text == "That lap, 1:05.626, level with your reference. Flashback used."
    assert m.speech == to_speech(m.text)


def test_lap_messages_detailed_adds_second_point_and_positive() -> None:
    msgs = lap_messages(lap(), OBSERVATIONS, 65_000, REF, "detailed", 0.0)
    assert [m.corner for m in msgs[1:]] == ["T4", "T1", "T3"]
    assert msgs[-1].priority is Priority.LOW and msgs[-1].meta["positive"] is True


def test_lap_messages_detailed_states_a_corner_loss_once() -> None:
    """impact_s is the whole corner's loss: two points at T4 must not add up to twice the validated loss."""
    same_corner = [obs("low_min_speed", -7.6, 0.081), obs("brake_early", -12.2, 0.081, confidence=0.8)]
    msgs = lap_messages(lap(), same_corner, None, None, "detailed", 0.0)
    assert [m.text for m in msgs[1:]] == [
        "T4, losing 0.08 s: minimum speed 8 km/h down.",
        "T4: braking 12 m earlier than your reference.",
    ]
    assert sum(m.text.count("0.08 s") for m in msgs) == 1


def test_lap_messages_quiet_intensity_builds_nothing() -> None:
    """Quiet intensity is "alerts and answers only": a summary would only sit in the queue unsaid."""
    assert lap_messages(lap(), OBSERVATIONS, 65_000, REF, "quiet", 0.0) == []
    ack = intensity_ack("quiet", 0.0)
    assert "alerts and answers only" in ack.text
    s = RadioScheduler("quiet")
    s.enqueue(mk("sum", MessageKind.LAP_SUMMARY, lap=4))
    assert s.next_message(CALM, 0.0, speaking=False) is None  # the scheduler agrees


def test_lap_messages_no_confident_observation_means_no_coaching() -> None:
    weak = [obs("low_min_speed", -4.5, 0.03, confidence=0.59)]
    msgs = lap_messages(lap(), weak, None, REF, "detailed", 0.0)
    assert [m.kind for m in msgs] == [MessageKind.LAP_SUMMARY]


def test_lap_messages_ids_unique_across_laps() -> None:
    a = lap_messages(lap(4, lap_id=104), OBSERVATIONS, None, REF, "detailed", 0.0)
    b = lap_messages(lap(5, lap_id=105), [], None, REF, "detailed", 70.0)
    ids = [m.id for m in a + b]
    assert len(ids) == len(set(ids))


def test_lap_messages_rejects_unknown_intensity() -> None:
    with pytest.raises(ValueError):
        lap_messages(lap(), [], None, None, "max", 0.0)


# ================================================================ proactive: topics and control
def test_newer_topic_message_replaces_one_held_by_quiet_mode() -> None:
    """Review case: a "fuel is tight" held by quiet mode used to block the same lap's critical call. Fuel calls are
    race strategy's now (``strategy.radio``, topic ``strategy:fuel``); the topic rule is the scheduler's."""
    s = RadioScheduler()
    s.set_quiet(until_lap=20)
    meta: dict[str, object] = {"topic": "strategy:fuel"}
    tight = mk("fuel-tight", MessageKind.ALERT, text="Fuel is tight.", lap=12, meta=meta)
    critical = mk("fuel-crit", MessageKind.ALERT, Priority.HIGH, "Fuel critical.", 5.0, lap=12, bypass=True, meta=meta)
    assert s.enqueue(tight)
    on_lap_12 = replace(CALM, lap_number=12)
    assert s.next_message(on_lap_12, 1.0, speaking=False) is None  # held by quiet mode
    assert s.enqueue(critical)
    m = s.next_message(on_lap_12, 5.0, speaking=False)
    assert m is not None and m.id == critical.id
    assert s.pending() == []  # the outdated "tight" is never said after "critical", not even when quiet ends
    assert s.next_message(replace(CALM, lap_number=20), 30.0, speaking=False) is None


def test_newest_topic_message_replaces_older_even_when_itself_a_repeat() -> None:
    s = RadioScheduler()
    meta: dict[str, object] = {"topic": "fuel"}
    assert s.enqueue(mk("f1", MessageKind.ALERT, text="Fuel plus 0.2.", meta=meta))
    assert s.next_message(CALM, 0.0, speaking=False) is not None
    assert s.enqueue(mk("f2", MessageKind.ALERT, text="Fuel plus 0.1.", created=1.0, meta=meta))
    # back to the estimate the driver just heard: the stale 0.1 must not follow it
    assert not s.enqueue(mk("f3", MessageKind.ALERT, text="Fuel plus 0.2.", created=2.0, meta=meta))
    assert s.pending() == []


def test_control_acknowledgements_are_immediate_and_bypass_quiet() -> None:
    q = quiet_ack(8, False, 5.0)
    assert q.text == "Copy, quiet until lap 8. Urgent calls only."
    assert quiet_ack(None, True, 5.0).text == "Copy, going quiet until you call me. Urgent calls only."
    r = resume_ack(5.0)
    assert r.text == "Copy, radio back on."
    i = intensity_ack("Detailed", 5.0)
    assert i.text == "Copy, detailed coaching." and i.meta["intensity"] == "detailed"
    for m in (q, r, i):
        assert m.kind is MessageKind.CONTROL and m.bypass_quiet and not m.needs_speak_window
        assert m.expires_mono == pytest.approx(15.0)
    assert len({q.id, r.id, i.id}) == 3


# ================================================================ end to end
def test_lap_flow_through_scheduler() -> None:
    s = RadioScheduler("normal")
    for m in lap_messages(lap(), OBSERVATIONS, 65_000, REF, "normal", 0.0):
        assert s.enqueue(m)
    on_lap_5 = replace(CALM, lap_number=5)
    assert s.next_message(replace(on_lap_5, brake=1.0), 0.5, speaking=False) is None  # braking into T1
    first = s.next_message(on_lap_5, 1.0, speaking=False)
    assert first is not None and first.kind is MessageKind.LAP_SUMMARY
    assert s.next_message(on_lap_5, 2.0, speaking=True) is None
    assert s.next_message(on_lap_5, 3.0, speaking=False) is None  # pacing gap
    released = 1.0 + s.speech_latency_s + estimate_speech_s(first.speech) + 2.0
    assert s.next_message(on_lap_5, released - 0.1, speaking=False) is None
    second = s.next_message(on_lap_5, released, speaking=False)
    assert second is not None and second.text.startswith("T4,")
    assert s.next_message(on_lap_5, 20.0, speaking=False) is None


def test_quiet_request_flow() -> None:
    s = RadioScheduler()
    s.set_quiet(until_lap=8)
    assert s.enqueue(quiet_ack(8, False, 0.0))
    for m in lap_messages(lap(5, lap_id=105), OBSERVATIONS, None, REF, "normal", 0.0):
        s.enqueue(m)
    braking_on_lap_5 = replace(BRAKING, lap_number=5)
    ack = s.next_message(braking_on_lap_5, 0.0, speaking=False)
    assert ack is not None and ack.kind is MessageKind.CONTROL
    assert s.next_message(replace(CALM, lap_number=5), 10.0, speaking=False) is None
    # quiet period outlasts the lap messages: they expire unspoken
    assert s.next_message(replace(CALM, lap_number=8), 60.0, speaking=False) is None
    assert s.pending() == []


def test_the_final_lap_gets_its_summary_but_no_coaching_point() -> None:
    """UX review: "T3, losing 0.12 s" was said after the chequered flag. The session ended on that lap: no next lap
    can use a coaching point, so the radio says the lap and stops there."""
    final = lap(32, 80_886, clean=True, final=True)
    msgs = lap_messages(final, OBSERVATIONS, 65_000, REF, "normal", 100.0)
    assert [m.kind for m in msgs] == [MessageKind.LAP_SUMMARY] and msgs[0].text.startswith("Final lap")
    assert any(m.kind is MessageKind.COACHING for m in lap_messages(lap(), OBSERVATIONS, 65_000, REF, "normal", 0.0))
