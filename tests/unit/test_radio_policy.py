"""v0.3.0: the radio as ONE engineer. One policy table (``voice.scheduler.POLICY``) that every producer's message maps
onto, one per-lap budget by intensity, the race order, who may interrupt (spotter calls, the red flag and a puncture
only) and one message per piece of news across producers (the line, the safety car, fuel, answered topics). The table
in docs/voice-protocol.md is the code's (``policy_markdown``). Every test runs on an injected clock."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pitwall.carhealth.radio import health_message
from pitwall.motivation.radio import GoalLineGate, goal_message
from pitwall.raceradio.radio import race_message
from pitwall.strategy.radio import strategy_message
from pitwall.voice.proactive import lap_messages
from pitwall.voice.scheduler import (
    ALLOWED_KINDS,
    ANNOUNCE_WINDOW_S,
    ANSWER_HOLD_S,
    BUDGETED,
    KIND_RANK,
    MERGE_MAX_WORDS,
    POLICY,
    POLICY_BY_KEY,
    RACE_PER_LAP,
    SUMMARY_MERGE_HOLD_S,
    TALK_PER_LAP,
    YIELDS_TO_CUE_KEY,
    RadioScheduler,
    family_of,
    interrupt_rank,
    may_interrupt,
    policy_markdown,
    policy_table,
    spoken_word_count,
)
from pitwall.voice.speech import to_speech
from pitwall.voice.types import DrivingState, MessageKind, Priority, RadioMessage
from pitwall.voice.urgent import urgent_message

ROOT = Path(__file__).resolve().parents[2]
ON = DrivingState(True, 250.0, 0.0, 0.01, 8, 800.0, None)
OFF = DrivingState(False, 0.0, 0.0, 0.0, 8, 0.0, None)
STEP = 12.0


def drain(
    s: RadioScheduler, state: DrivingState = ON, start: float = 1.0, polls: int = 30, step: float = STEP
) -> list[RadioMessage]:
    out: list[RadioMessage] = []
    t = start
    for _ in range(polls):
        m = s.next_message(state, t, speaking=False)
        if m is not None:
            out.append(m)
        t += step
    return out


# ------------------------------------------------------------------ one message of every producer
LAP = {"lap_id": 7, "lap_number": 7, "lap_time_ms": 85_458, "clean": True, "valid": True, "flags": []}
OBS = [
    {
        "id": 1,
        "lap_id": 7,
        "lap_number": 7,
        "corner": "T4",
        "kind": "low_min_speed",
        "value": -8.0,
        "impact_s": 0.08,
        "confidence": 0.9,
        "priority": 0.07,
        "positive": False,
        "text": "T4: minimum speed 8 km/h lower.",
        # a habit: the radio says habits and big one-offs, never a small one-off (habits spec section 3)
        "consistency": "4 of the last 5 laps",
        "consistency_ratio": 0.8,
    }
]


def strategy(topic: str, level: str = "normal", priority: str = "normal", **kw: Any) -> dict[str, Any]:
    return {
        "id": kw.pop("id", f"st-{topic}-8-1"),
        "topic": topic,
        "level": level,
        "priority": priority,
        "text": kw.pop("text", f"A call about {topic}."),
        "text_simple": kw.pop("text_simple", None),
        "lap": 8,
        "ttl_s": 60.0,
        "bypass_quiet": kw.pop("bypass", False),
        "audience": "all",
        "data": {},
        "t_unix": 0.0,
    }


def health(topic: str, level: str = "normal", priority: str = "normal", **kw: Any) -> dict[str, Any]:
    return {**strategy(topic, level, priority, **kw), "id": kw.get("id", f"hc-{topic}-8-1")}


def race(call: str, kind: str = "race", priority: str = "normal", **kw: Any) -> dict[str, Any]:
    return {
        "id": kw.pop("id", f"rc-{call}"),
        "session_id": "s1",
        "group": kw.pop("group", "position"),
        "call": call,
        "kind": kind,
        "priority": priority,
        "text": kw.pop("text", f"Race call {call}."),
        "text_simple": None,
        "speech_source": None,
        "ttl_s": kw.pop("ttl", 120.0),
        "needs_window": True,
        "bypass_quiet": kw.pop("bypass", False),
        "topic": kw.pop("topic", "race:position"),
        "lap": 8,
        "addressable": False,
        "defer_to_strategy_detail": False,
        "audience": None,
        "allowance": kw.pop("allowance", True),
        "data": kw.pop("data", {}),
        "tier": "recorded",
        "synthetic": False,
    }


def every_producer(now: float = 0.0) -> dict[str, RadioMessage]:
    """One message of every producer, built by the producer's own builder."""
    summary, coaching = lap_messages(LAP, OBS, None, None, "normal", now)
    goal = goal_message(
        {
            "kind": "goals_achieved",
            "session_id": "s1",
            "lap_id": 7,
            "lap_number": 7,
            "goals": [{"id": 1, "kind": "clean_streak", "target": 8, "params": {}, "track_name": None}],
        },
        GoalLineGate(),
        "s1",
        simple=False,
        to_speech=to_speech,
        now_mono=now,
    )
    assert goal is not None
    race_call = race_message(race("position_change"), now)
    alert = race_message(race("yellow_ahead", "alert", "high", group="flags", topic="race:yellow"), now)
    detail = race_message(race("rival_fastest_lap", "info", "low", group="rivals", topic=None), now)
    assert race_call is not None and alert is not None and detail is not None
    red = urgent_message({"id": "rc-red", "source": "raceradio", "text": "Red flag, red flag.", "ttl_s": 15.0}, now)
    spot = RadioMessage("sp", MessageKind.SPOTTER, Priority.URGENT, "Car left.", "Car left.", now)
    cue = RadioMessage(
        "cue", MessageKind.CUE, Priority.HIGH, "T1 brake", "turn 1, brake", now, needs_speak_window=False
    )
    answer = RadioMessage("a", MessageKind.ANSWER, Priority.HIGH, "Fuel is fine.", "Fuel is fine.", now)
    validation = RadioMessage("v", MessageKind.VALIDATION, Priority.LOW, "Next test.", "Next test.", now)
    return {
        "lap_summary": summary,
        "coaching": coaching,
        "goal": goal,
        "race": race_call,
        "alert": alert,
        "detail": detail,
        "strategy": strategy_message(strategy("pit_window"), now),
        "health": health_message(health("tyres_cold", priority="high"), now),
        "urgent": red,
        "spotter": spot,
        "cue": cue,
        "answer": answer,
        "validation": validation,
    }


def test_every_producer_maps_onto_one_row_of_the_table() -> None:
    msgs = every_producer()
    assert {family_of(m) for m in msgs.values()} == set(POLICY_BY_KEY)  # every row is used, by its producer
    for fam, m in msgs.items():
        assert family_of(m) == fam, (fam, m.kind, m.meta)
        assert m.kind in POLICY_BY_KEY[fam].kinds
    assert {k for f in POLICY for k in f.kinds} == set(MessageKind)  # every kind belongs to a family
    assert set(KIND_RANK) == set(MessageKind)


def test_the_table_is_what_the_scheduler_does() -> None:
    """Intensity, interrupts and the budget column of each row, checked against the live rules."""
    summary_on_air = every_producer()["lap_summary"]
    for fam, m in every_producer().items():
        row = POLICY_BY_KEY[fam]
        allowed = tuple(i for i in ("quiet", "normal", "detailed") if m.kind in ALLOWED_KINDS[i])  # type: ignore[index]
        if fam != "cue":  # cues: their own switch, muted by the hub at quiet intensity
            assert allowed == row.intensities, fam
        assert may_interrupt(m, summary_on_air) is row.interrupts, fam
        budgeted = m.kind in BUDGETED and m.priority < Priority.URGENT
        assert budgeted is (row.budget == "waits"), fam
        assert (row.budget == "spends") is (m.kind is MessageKind.ALERT and m.priority < Priority.URGENT), fam


def test_docs_print_the_code_table() -> None:
    doc = (ROOT / "docs" / "voice-protocol.md").read_text(encoding="utf-8")
    assert policy_markdown() in doc
    for k, v in TALK_PER_LAP.items():
        assert f"{k} {v}" in doc  # "normal 3"
    assert [r["key"] for r in policy_table()] == [f.key for f in POLICY]


# ------------------------------------------------------------------ race order and the one budget
def test_race_order_of_one_lap_off_track() -> None:
    s = RadioScheduler("detailed")
    m = every_producer()
    for k in ("coaching", "goal", "detail", "strategy", "race", "lap_summary", "alert", "validation"):
        assert s.enqueue(m[k]), k
    said = [family_of(x) for x in drain(s, OFF, step=0.5, polls=200)]
    assert said == ["alert", "lap_summary", "race", "strategy", "goal", "coaching", "detail", "validation"]


@pytest.mark.parametrize(("intensity", "n"), [("quiet", 0), ("normal", 3), ("detailed", 5)])
def test_one_budget_whoever_the_producer(intensity: str, n: int) -> None:
    """Race calls, strategy, car health, lap summary, goal, coaching and detail share ONE allowance per lap."""
    s = RadioScheduler(intensity)
    m = every_producer()
    for k in ("lap_summary", "race", "strategy", "health", "goal", "coaching", "detail"):
        s.enqueue(m[k])
    s.enqueue(strategy_message(strategy("gap", "detailed", "low", id="st-gap-2"), 0.0))
    said = [x for x in drain(s) if family_of(x) not in ("alert", "validation")]
    assert len(said) == n == TALK_PER_LAP[intensity]  # type: ignore[index]


def test_alerts_are_never_held_but_spend_the_lap() -> None:
    s = RadioScheduler("normal")
    for i in range(2):
        s.enqueue(race_message(race("blue_flag", "alert", "high", id=f"b{i}", text=f"Blue flag {i}.", group="flags",
                                    topic=None), 0.0))  # fmt: skip
    for i in range(3):
        s.enqueue(strategy_message(strategy(f"t{i}", id=f"st-t{i}"), 0.0))
    said = drain(s)
    assert [family_of(x) for x in said] == ["alert", "alert", "strategy"]  # 2 alerts + 1 of 3: the lap's three


def test_race_calls_share_of_the_allowance() -> None:
    s = RadioScheduler("normal")
    for i in range(4):
        s.enqueue(race_message(race("gap_report", id=f"r{i}", text=f"Gap {i}.", topic=f"race:t{i}"), 0.0))
    assert len(drain(s)) == RACE_PER_LAP["normal"] == 2


# ------------------------------------------------------------------ who may interrupt
def test_only_spotter_red_flag_puncture_and_braking_calls_interrupt() -> None:
    m = every_producer()
    puncture = urgent_message({"id": "rc-p", "source": "raceradio", "text": "Puncture, rear left. Box this lap."}, 0.0)
    interrupting = {"spotter", "urgent"}
    for on_air in m.values():
        if family_of(on_air) in interrupting:
            continue
        for fam, new in m.items():
            if fam == "cue":  # a braking call cuts routine talk, never an alert, an answer, a cue or a spotter call
                cut = on_air.kind not in (
                    MessageKind.CUE,
                    MessageKind.ANSWER,
                    MessageKind.CONTROL,
                    MessageKind.ALERT,
                    MessageKind.SPOTTER,
                )
                assert may_interrupt(new, on_air) is cut, (fam, family_of(on_air))
                continue
            assert may_interrupt(new, on_air) is (fam in interrupting), (fam, family_of(on_air))
        assert may_interrupt(puncture, on_air)
    clear = replace(m["spotter"], meta={YIELDS_TO_CUE_KEY: True})
    assert not may_interrupt(clear, m["cue"]) and may_interrupt(clear, m["lap_summary"])
    assert not may_interrupt(m["urgent"], m["spotter"]) and not may_interrupt(m["spotter"], m["urgent"])


def test_a_puncture_is_on_the_urgent_path() -> None:
    from tests.unit.test_raceradio_damage import clean_race, damage, frame

    r = clean_race()
    r.drive(4.0, 6.0, damage=damage())
    r.feed(frame(7.0, damage=damage(tyres=(0, 0, 100, 0))))
    (call,) = r.drive(7.1, 9.0, damage=damage(tyres=(0, 0, 100, 0)))
    assert call.urgent and call.priority == "urgent" and not call.needs_window
    msg = urgent_message(call.urgent_payload(0.0), 0.0)
    assert family_of(msg) == "urgent" and may_interrupt(msg, every_producer()["lap_summary"])


# ------------------------------------------------------------------ one message per piece of news
def summary(text: str = "That lap, 1:25.458, personal best.", created: float = 0.0) -> RadioMessage:
    return RadioMessage("sum", MessageKind.LAP_SUMMARY, Priority.NORMAL, text, to_speech(text), created, created + 45.0,
                        lap_number=3, meta={"lap_id": 3})  # fmt: skip


def line_call(call: str, text: str, created: float = 0.0, **kw: Any) -> RadioMessage:
    m = race_message(race(call, id=f"rc-{call}", text=text, data={"at_line": True}, **kw), created)
    assert m is not None
    return m


def test_the_lines_race_news_rides_in_the_lap_summary() -> None:
    s = RadioScheduler("normal")
    s.enqueue(line_call("own_fastest_lap", "Fastest lap of the race.", group="rivals", topic=None))
    s.enqueue(line_call("last_lap", "Last lap.", priority="high", group="start", topic="race:countdown"))
    s.enqueue(summary())
    (said,) = drain(s)
    assert said.text == "That lap, 1:25.458, personal best. Fastest lap of the race. Last lap."
    assert said.kind is MessageKind.LAP_SUMMARY
    assert said.meta["merged_race_calls"] == ["rc-own_fastest_lap", "rc-last_lap"]


def test_line_news_that_does_not_fit_goes_on_its_own_at_once() -> None:
    s = RadioScheduler("normal")
    long = "Gap ahead 12.4s, gap behind 3.9s, closing 0.3 a lap, and the car ahead pits next lap probably."
    s.enqueue(line_call("gap_report", long, group="rivals", topic="strategy:gap"))
    s.enqueue(summary())
    assert spoken_word_count(to_speech("That lap, 1:25.458, personal best. " + long)) > MERGE_MAX_WORDS
    said = drain(s, polls=2)
    assert [x.text for x in said] == ["That lap, 1:25.458, personal best.", long]  # no wait for a summary


def test_line_news_waits_for_its_summary_then_goes_alone() -> None:
    s = RadioScheduler("normal")
    s.enqueue(line_call("finish", "P3, the flag.", group="start", topic="race:countdown", allowance=False))
    assert s.next_message(ON, SUMMARY_MERGE_HOLD_S - 0.1, False) is None
    said = s.next_message(ON, SUMMARY_MERGE_HOLD_S, False)
    assert said is not None and said.text == "P3, the flag."


def test_an_old_summary_does_not_take_the_new_lines_news() -> None:
    s = RadioScheduler("normal")
    s.enqueue(summary(created=0.0))
    s.enqueue(line_call("gap_report", "Gap ahead 2.8s.", created=60.0, group="rivals", topic="strategy:gap"))
    assert [m.text for m in s.pending()] == ["That lap, 1:25.458, personal best.", "Gap ahead 2.8s."]


SC_DEPLOYED = race("sc_deployed", "alert", "high", id="rc-sc", group="flags", topic="race:sc", bypass=True,
                   text="Safety car, safety car. No overtaking.")  # fmt: skip
SC_BOX = strategy("sc_box", "alert", "high", bypass=True, text="Safety car. Pitting this lap is an option.",
                  text_simple="Safety car: a pit stop costs less now.")  # fmt: skip


def test_the_safety_car_is_announced_once_queued_together() -> None:
    s = RadioScheduler("normal")
    deployed = race_message(SC_DEPLOYED, 0.0)
    assert deployed is not None
    assert s.enqueue(deployed) and s.enqueue(strategy_message(SC_BOX, 0.5))
    (said,) = drain(s)
    assert said.text == "Safety car, safety car. No overtaking. Pitting this lap is an option."
    assert said.kind is MessageKind.ALERT and said.bypass_quiet and said.meta["announce_merged"] == "race-rc-sc"


def test_strategy_after_the_announcement_loses_its_head() -> None:
    s = RadioScheduler("normal")
    deployed = race_message(SC_DEPLOYED, 0.0)
    assert deployed is not None
    s.enqueue(deployed)
    assert [m.id for m in drain(s, polls=1)] == ["race-rc-sc"]
    s.enqueue(strategy_message(SC_BOX, 5.0))
    assert [m.text for m in drain(s, start=20.0)] == ["Pitting this lap is an option."]
    simple = RadioScheduler("normal")
    simple.enqueue(deployed)
    drain(simple, polls=1)
    simple.enqueue(strategy_message(SC_BOX, 5.0, simple=True))
    assert [m.text for m in drain(simple, start=20.0)] == ["A pit stop costs less now."]
    later = RadioScheduler("normal")
    later.enqueue(deployed)
    drain(later, polls=1)
    later.enqueue(strategy_message(SC_BOX, ANNOUNCE_WINDOW_S + 10.0))  # a new safety car later: said in full
    assert drain(later, start=ANNOUNCE_WINDOW_S + 11.0)[0].text.startswith("Safety car.")


def test_the_announcement_after_strategy_said_it_is_dropped() -> None:
    s = RadioScheduler("normal")
    s.enqueue(strategy_message(SC_BOX, 0.0))
    assert len(drain(s, polls=1)) == 1
    deployed = race_message(SC_DEPLOYED, 5.0)
    assert deployed is not None
    assert not s.enqueue(deployed)


def test_fuel_is_one_topic_across_producers() -> None:
    s = RadioScheduler("normal")
    s.enqueue(strategy_message(strategy("fuel", text="Fuel is tight: plus 0.2 laps."), 0.0))
    s.enqueue(health_message(health("fuel_low", text="Fuel for about 3 more laps."), 1.0))
    assert [m.text for m in s.pending()] == ["Fuel for about 3 more laps."]
    s.enqueue(health_message(health("fuel_critical", "alert", "high", text="Fuel for about one more lap."), 2.0))
    assert [m.text for m in s.pending()] == ["Fuel for about one more lap."]


def test_an_answer_holds_its_topic() -> None:
    s = RadioScheduler("normal")
    answer = RadioMessage("a1", MessageKind.ANSWER, Priority.HIGH, "Plus 0.4 laps of fuel.", "x", 0.0,
                          meta={"intent": "fuel"})  # fmt: skip
    s.note_spoken(answer, 0.0)
    assert not s.enqueue(strategy_message(strategy("fuel", text="Fuel is tight."), 10.0))
    assert s.enqueue(strategy_message(strategy("fuel", "alert", "high", text="Fuel critical."), 11.0))
    assert s.enqueue(strategy_message(strategy("fuel", text="Fuel is tight again.", id="st-f2"), ANSWER_HOLD_S + 1.0))
    s.reset_session()
    assert s.enqueue(strategy_message(strategy("fuel", text="Fuel is tight.", id="st-f3"), 12.0))


def test_a_new_session_forgets_announcements_and_answers() -> None:
    s = RadioScheduler("normal")
    s.enqueue(strategy_message(SC_BOX, 0.0))
    drain(s, polls=1)
    s.reset_session()
    deployed = race_message(SC_DEPLOYED, 5.0)
    assert deployed is not None and s.enqueue(deployed)


def test_standing_still_on_track_is_outside_the_budget() -> None:
    """The budget is the driver's workload at speed: the grid brief and lights out, said standing on the grid, leave
    lap 1's three messages for the racing."""
    s = RadioScheduler("normal")
    grid = replace(ON, speed_kph=0.0, lap_number=1)
    for call in ("grid_brief", "lights_out"):
        m = race_message(race(call, priority="high", group="start", topic=None, allowance=False, id=f"rc-{call}"), 0.0)
        assert m is not None and s.enqueue(m)
    assert len(drain(s, grid, polls=3)) == 2
    for i in range(4):
        s.enqueue(strategy_message(strategy(f"t{i}", id=f"st-t{i}"), 40.0))
    assert len(drain(s, replace(ON, lap_number=1), start=40.0)) == TALK_PER_LAP["normal"]


def test_a_summary_carrying_a_milestone_is_never_held() -> None:
    s = RadioScheduler("normal")
    for i in range(3):
        s.enqueue(strategy_message(strategy(f"t{i}", id=f"st-t{i}"), 0.0))
    assert len(drain(s)) == 3  # the lap's three are spent
    s.enqueue(line_call("laps_2", "Two laps to go.", created=100.0, group="start", topic="race:countdown",
                        allowance=False))  # fmt: skip
    s.enqueue(summary(created=100.0))
    (said,) = drain(s, start=101.0)
    assert said.text.endswith("Two laps to go.") and said.meta["race_allowance"] is False


def test_no_coaching_point_after_the_chequered_flag() -> None:
    """Measured (Melbourne, GT7): a coaching point said after "Chequered flag. P1." - no next lap can use it."""
    s = RadioScheduler("normal")
    m = every_producer()
    s.enqueue(m["coaching"])
    flag = race_message(race("finish", priority="high", group="start", topic="race:countdown", allowance=False,
                             text="Chequered flag. P1."), 1.0)  # fmt: skip
    assert flag is not None and s.enqueue(flag)
    assert [x.kind for x in s.pending()] == [MessageKind.RACE]  # the queued coaching point went
    assert not s.enqueue(replace(m["coaching"], id="late", created_mono=2.0))
    s.reset_session()
    assert s.enqueue(replace(m["coaching"], id="next", created_mono=3.0))


def test_the_race_radio_marks_its_line_news() -> None:
    """The race's fastest lap and the flag are always line news (EA's FTLP can come a frame before the new lap); a
    position change only within LINE_WINDOW_S of the line (raceradio.engine)."""
    from pitwall.raceradio.engine import LINE_WINDOW_S, RaceRadioEngine
    from pitwall.raceradio.model import CallSpec

    eng = RaceRadioEngine("s1")
    eng.st.mode, eng.st.racing, eng.st.t = "race", True, 100.0

    def emit(call: str) -> dict[str, Any]:
        eng._emit(CallSpec(group="rivals", call=call, kind="race", priority="normal", text=call, text_simple=None,
                           ttl_s=20.0))  # fmt: skip
        (c,) = eng.take_calls()
        return dict(c.data)

    assert emit("own_fastest_lap") == {"at_line": True}  # no crossing seen yet: still the line's news
    assert emit("position_change") == {}
    eng.st.crossing_t = 100.0 - LINE_WINDOW_S + 0.5
    assert emit("position_change") == {"at_line": True}
    assert emit("warning") == {}  # not news about the lap just finished


def test_the_flag_always_rides_in_the_final_laps_summary() -> None:
    """Measured: "Chequered flag. P16." then "Final lap, 1:36.360, personal best, 0.677 faster than before." - two
    messages about the flag, the second over the word cap. The race is over: one longer message."""
    s = RadioScheduler("normal")
    s.enqueue(line_call("finish", "Chequered flag. P16. Up 2 from the grid.", group="start", topic="race:countdown",
                        allowance=False))  # fmt: skip
    final = summary("Final lap, 1:36.360, personal best, 0.677 faster than before.")
    assert spoken_word_count(to_speech(final.text + " Chequered flag. P16. Up 2 from the grid.")) > MERGE_MAX_WORDS
    s.enqueue(final)
    (said,) = drain(s)
    assert said.text.endswith("Chequered flag. P16. Up 2 from the grid.") and said.kind is MessageKind.LAP_SUMMARY


def test_a_corner_reminder_cuts_nothing_and_yields_to_spotter_and_braking_calls() -> None:
    """A corner reminder (a CUE with ``meta["cue"] == "reminder"``) is descriptive coaching, not a braking call: it
    starts only on a free radio, cuts nothing (a spotter clear included), and any spotter call (a clear, "still there")
    or braking call may cut it."""
    m = every_producer()
    reminder = replace(m["cue"], meta={"cue": "reminder"})
    brake = replace(m["cue"], meta={"cue": "brake"})
    clear = replace(m["spotter"], meta={YIELDS_TO_CUE_KEY: True})
    still = replace(m["spotter"], priority=Priority.HIGH, meta={YIELDS_TO_CUE_KEY: True})
    assert interrupt_rank(reminder) == 0 and interrupt_rank(brake) == interrupt_rank(m["cue"]) == 1
    assert may_interrupt(reminder, None)
    for on_air in (m["lap_summary"], m["coaching"], clear, still, brake, m["answer"]):
        assert not may_interrupt(reminder, on_air), family_of(on_air)
    for new in (clear, still, m["spotter"], m["urgent"], brake):
        assert may_interrupt(new, reminder), new.meta
    assert not may_interrupt(clear, brake)  # a clear still never cuts a braking call
