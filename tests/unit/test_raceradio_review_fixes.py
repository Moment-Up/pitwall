"""Race radio review fixes (correctness and UX reviews of feat/radio): one regression test per finding, on hand-made
items (test data, not game output). The real-capture checks stay in tests/recorded and scripts/race_radio_check.py."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from pitwall.ai.engineer import NO_RACE_LAPS, NO_RACE_LENGTH, RaceEngineer, detect_intent
from pitwall.ai.facts import FactSheet, _add_race
from pitwall.ai.radio_phrasing import radio_answer
from pitwall.core.live import LiveState
from pitwall.drivers import Driver, DriverPreferences
from pitwall.model.telemetry import Game, SessionType
from pitwall.raceradio.names import NeighbourNames, personal_who
from pitwall.raceradio.radio import race_message
from pitwall.raceradio.worker import RACE_RETRACT_NOTE, RaceRadioWorker
from pitwall.voice import field_zones
from pitwall.voice.hub import RadioHub
from pitwall.voice.scheduler import (
    REPEAT_OK_KEY,
    SUMMARY_MERGE_HOLD_S,
    SUMMARY_MERGE_KEY,
    RadioScheduler,
)
from pitwall.voice.speech import to_speech
from pitwall.voice.types import AudioClip, DrivingState, MessageKind, Priority, RadioMessage
from tests.unit.raceradio_helpers import (
    PLAYER,
    Run,
    car,
    damage,
    event,
    frame,
    info,
    lap_done,
    participant,
    participants,
    race,
    timing,
)
from tests.unit.test_voice_hub import FakeStt, FakeTts

CALM = DrivingState(True, 250.0, 0.0, 0.0, 10, 500.0, None)


def said(sch: RadioScheduler, t: float, state: DrivingState = CALM) -> list[RadioMessage]:
    out = []
    while (m := sch.next_message(state, t, False)) is not None:
        out.append(m)
        t += 10.0  # past the gap and the estimated speech
    return out


def as_message(c: Any, now: float, **kw: Any) -> RadioMessage | None:
    return race_message(c.to_dict(), now, **kw)


# ============================================================================================ correctness 1: repeats
def test_a_second_and_third_blue_flag_are_said_not_filtered_as_repeats() -> None:
    """The probe: blue flags at 5, 40 and 80 s; the 60 s identical-text window used to swallow the one at 40 s."""
    sch = RadioScheduler("normal")
    r = race(0.0, total_laps=20)
    heard: list[float] = []
    t = 0.0
    for blue_at in (5.0, 40.0, 80.0):
        while t < blue_at:
            t += 0.1
            r.feed(frame(t, lap=10, pos=8, fia="none"))
        for _ in range(10):
            t += 0.1
            for c in r.feed(frame(t, lap=10, pos=8, fia="blue")):
                m = as_message(c, t)
                assert m is not None and m.meta[REPEAT_OK_KEY] is True
                sch.enqueue(m)
            if (m := sch.next_message(CALM, t, False)) is not None:
                heard.append(round(t))
    assert [c.call for c in r.calls] == ["blue_flag"] * 3
    assert heard == [6, 41, 81]


def test_only_rules_with_their_own_cooldown_skip_the_repeat_window() -> None:
    for group, exempt in (("flags", True), ("penalties", True), ("damage", True), ("position", False),
                          ("start", False), ("rivals", False)):  # fmt: skip
        m = race_message({"id": "x", "group": group, "call": "c", "kind": "race", "text": "Same words."}, 0.0)
        assert m is not None and (m.meta.get(REPEAT_OK_KEY) is True) is exempt, group


# ============================================================================================ correctness 2: SC
# (tests/unit/test_raceradio_flags.py: returned is not green, a lagging Session packet never re-deploys)


# ============================================================================================ correctness 3: allowance
def test_the_start_and_the_countdown_never_use_the_race_allowance_and_the_lead_always_gets_through() -> None:
    sch = RadioScheduler("normal")
    lap2 = DrivingState(True, 250.0, 0.0, 0.0, 2, 500.0, None)
    for i, text in enumerate(("Down to P9.", "Up to P8.")):  # the lap's allowance (2 at normal) used up
        sch.enqueue(race_message({"id": f"p{i}", "group": "position", "call": "position_change", "kind": "race",
                                  "text": text, "data": {"position": 8, "before": 9}}, 0.0))  # fmt: skip
    assert len(said(sch, 0.0, lap2)) == 2
    sch.enqueue(race_message({"id": "c", "group": "position", "call": "position_change", "kind": "race",
                              "text": "Up to P7.", "data": {"position": 7, "before": 8}}, 100.0))  # fmt: skip
    assert said(sch, 100.0, lap2) == []  # a third ordinary position call waits for the next lap
    lead = {"id": "lead", "group": "position", "call": "clean_pass", "kind": "race", "text": "Good move. P1.",
            "allowance": False, "data": {"position": 1, "before": 2}}  # fmt: skip
    sch.enqueue(race_message(lead, 101.0))
    assert [m.text for m in said(sch, 101.0, lap2)] == ["Good move. P1."]


def test_engine_marks_a_move_into_p1_outside_the_allowance() -> None:
    r = race(0.0, total_laps=10)
    r.drive(0.0, 2.0, lap=3, pos=3)
    r.feed(lap_done(2.0, 3))
    r.drive(2.1, 10.0, lap=4, pos=3)
    r.drive(10.1, 40.0, lap=4, pos=2)
    r.drive(40.1, 70.0, lap=4, pos=1)
    changes = r.named("position_change")
    assert [(c.text, c.allowance) for c in changes] == [("Up to P2.", True), ("Up to P1.", False)]


# ============================================================================================ correctness 4: laps to go
def gt7_view(lap: int, frac: float) -> dict[str, Any]:
    r = Run()
    r.feed(info(0.0, game=Game.GT7, stype=SessionType.UNKNOWN, total_laps=5, sc=None,
                extra={"num_cars_pre_race": 12}, length=3800.0))  # fmt: skip
    r.feed(frame(0.1, game=Game.GT7, lap=None, pos=8, fia=None, d=0.0))
    r.feed(frame(1.0, game=Game.GT7, lap=lap, pos=5, fia=None, d=frac * 3800.0))
    return r.engine.view()


@pytest.mark.parametrize(
    ("lap", "frac", "fact", "position", "laps"),
    [
        (4, 0.4, "2 laps to go", "P5 of 12, 2 laps to go.", "Lap 4 of 5, 2 laps to go."),
        (4, 0.6, "2 laps to go", "P5 of 12, 2 laps to go.", "Lap 4 of 5, 2 laps to go."),  # was "last lap"
        (5, 0.3, "last lap", "P5 of 12, last lap.", "Lap 5 of 5, last lap."),
        (5, 0.7, "last lap", "P5 of 12, last lap.", "Lap 5 of 5, last lap."),  # 0.3 left: was no "last lap" at all
    ],
)
def test_laps_to_go_count_the_current_lap(lap: int, frac: float, fact: str, position: str, laps: str) -> None:
    v = gt7_view(lap, frac)
    fs = FactSheet()
    _add_race(fs, {"race": v}, "s1")
    text = fs.facts[0].text
    assert fact in text and "1 laps" not in text
    assert v["final_lap"] is (lap == 5)
    assert radio_answer("gaps", fs, "what position am I") == position
    assert radio_answer("laps_left", fs, "how many laps left?") == laps


def test_laps_left_questions_are_understood_and_answered_outside_a_race() -> None:
    for q in ("how many laps left?", "How many laps to go", "is this the last lap?", "what lap are we on?",
              "how many more laps", "laps remaining?"):  # fmt: skip
        assert detect_intent(q).name == "laps_left", q
    for q, intent in (("how many laps of fuel left?", "fuel"), ("how many laps left on these tyres?", "tyres"),
                      ("how many laps this week?", "week"), ("how was my last lap?", "last_lap")):  # fmt: skip
        assert detect_intent(q).name == intent, q
    practice = FactSheet()
    practice.add("session", "Session: F1 25 on PS5 at Silverstone, practice.", {})
    ans = asyncio.run(RaceEngineer(None).answer("how many laps left?", practice, use_llm=False, short=True))
    assert ans.text == NO_RACE_LAPS and radio_answer("laps_left", practice, "how many laps left?") is None
    timed = FactSheet()  # a race the game sends no length for, nor a lap number
    timed.add("race", "Race: position P5 of 12.", {"kind": "position", "position": 5, "cars": 12, "laps_to_go": None})
    ans = asyncio.run(RaceEngineer(None).answer("how many laps to go?", timed, use_llm=False, short=True))
    assert ans.text == NO_RACE_LENGTH and radio_answer("laps_left", timed, "how many laps to go?") is None


# ============================================================================================ correctness 5: the leader
def field_engine(player_pos: int = 5) -> Run:
    r = race(0.0)
    r.feed(participants(0.0, [participant(0, driver=9, name="Driver 01"), participant(2, driver=54, name="Driver 03"),
                              participant(4, driver=0, name="Driver 05")]))  # fmt: skip
    for i in range(10):
        t = i * 0.5
        r.feed(frame(t, lap=3, pos=player_pos))
        r.feed(
            timing(
                t,
                [
                    car(0, 1, lap=3, gap_ms=None),
                    car(2, player_pos - 1, lap=3),
                    car(PLAYER, player_pos, lap=3, gap_ms=1200),
                    car(4, player_pos + 1, lap=3, gap_ms=900),
                ],
            )
        )
    return r


def sheet_of(r: Run) -> FactSheet:
    fs = FactSheet()
    _add_race(fs, {"race": r.engine.view()}, "s1")
    return fs


def test_whos_leading_names_the_leader_never_the_car_ahead() -> None:
    r = field_engine()
    v = r.engine.view()
    assert v["leader"] == {"label": "Verstappen", "label_kind": "driver", "gap_s": 5.0}
    assert v["ahead"]["car_index"] == 2 and v["behind"]["car_index"] == 4
    fs = sheet_of(r)
    assert radio_answer("who_ahead", fs, "Who's leading?") == "Verstappen is leading, 5.0 seconds ahead."
    assert radio_answer("who_ahead", fs, "who's ahead?") == "Norris is ahead, P4, 1.2 seconds."
    no_leader = FactSheet(facts=[f for f in fs.facts if f.data.get("kind") != "leader"])
    assert radio_answer("who_ahead", no_leader, "who is in the lead?") == "You're P5."
    leading = field_engine(player_pos=1)
    assert leading.engine.view()["leader"] is None


def test_online_names_never_answer_the_leader_question_nor_name_another_car() -> None:
    r = field_engine()
    names = NeighbourNames(r.engine)
    fs = sheet_of(r)
    assert personal_who(fs, "who's leading?", names) is None
    ahead = next(f for f in fs.facts if f.data.get("kind") == "ahead")
    ahead.data["car_index"] = 7  # the snapshot's car ahead is another car than the engine's now
    assert personal_who(fs, "who's ahead?", names) is None
    assert names.name("ahead", None) is None and names.name("ahead", 7) is None


def test_whos_behind_when_last() -> None:
    fs = FactSheet()
    fs.add("race", "Race: position P20 of 20.", {"kind": "position", "position": 20, "cars": 20})
    assert radio_answer("who_ahead", fs, "who's behind me?") == "Nobody behind you: P20 of 20."


# ============================================================================================ correctness 6, 7: the grid
def test_gt7_joined_mid_race_has_no_grid() -> None:
    r = Run()
    r.feed(info(0.0, game=Game.GT7, stype=SessionType.UNKNOWN, total_laps=5, sc=None,
                extra={"num_cars_pre_race": 12}, length=3800.0))  # fmt: skip
    for i in range(50):
        r.feed(frame(0.1 + i * 0.1, game=Game.GT7, lap=3, pos=9, fia=None, d=100.0 + i))
    for i in range(50):
        r.feed(frame(10 + i * 0.1, game=Game.GT7, lap=5, pos=4, fia=None, d=100.0 + i))
    r.feed(lap_done(20.0, 5, game=Game.GT7))
    assert r.engine.view()["grid_position"] is None
    assert [c.text for c in r.named("finish")] == ["Chequered flag. P4."]  # never "Up 5 from the grid"


def test_f1_grid_is_frozen_once_the_car_moved_even_without_lights_out() -> None:
    r = race(0.0, total_laps=5)
    r.drive(0.0, 1.0, lap=1, pos=7, speed=0.0)  # on the grid
    r.drive(1.1, 3.0, lap=1, pos=7, speed=150.0)  # lights out missed (a lost packet)
    r.drive(3.1, 6.0, lap=1, pos=14, speed=2.0)  # spun and stopped
    r.drive(6.1, 20.0, lap=1, pos=14, speed=150.0)
    r.feed(lap_done(20.0, 1))
    r.drive(20.1, 25.0, lap=2, pos=14, speed=200.0)
    assert r.engine.st.grid == 7
    assert [c.text for c in r.named("lap1_summary")] == ["P14 after lap one, down 7."]


# ============================================================================================ correctness 8: DSQ
def test_a_disqualification_is_said_after_the_lap_datas_dsq_status() -> None:
    r = race(0.0)
    r.drive(0.1, 5.0, lap=3, pos=5)
    cars = [car(i, i + 1) for i in range(6)]
    cars[PLAYER] = car(PLAYER, 4, result="dsq")
    r.feed(timing(5.0, cars))
    calls = r.feed(event(5.05, "PENA", penaltyType=6, infringementType=20, vehicleIdx=PLAYER, time=255))
    assert [c.text for c in calls] == ["Disqualified: too many penalties."]
    assert r.engine.st.retired
    assert r.drive(5.1, 8.0, lap=3, pos=5, fia="blue") == []  # nothing else once out


# ============================================================================================ correctness 9: flashback
def test_a_flashback_retracts_unsaid_position_and_damage_calls() -> None:
    live = LiveState()
    live.reset_session("s1", "test", False, "f1_25")
    notes: list[tuple[str, dict[str, Any]]] = []
    live.subscribe(lambda kind, payload: notes.append((kind, payload)))
    w = RaceRadioWorker(live, start=False)
    w.submit("s1", info(0.0))
    w.submit("s1", frame(0.1, damage=damage()))
    w.submit("s1", event(5.0, "FLBK", flashbackSessionTime=1.0))
    w.process_pending()
    assert [p for k, p in notes if k == RACE_RETRACT_NOTE] == [{"session_id": "s1", "groups": ["position", "damage"]}]
    assert w.engine is not None and w.engine.take_retractions() == ()


async def test_the_hub_drops_retracted_calls_queued_or_held() -> None:
    live = LiveState()
    live.reset_session("s1", "test", False, "f1_25")
    hub = RadioHub(live, RaceEngineer(None), FakeStt(), FakeTts(), RadioScheduler("normal"),
                   fact_sheet=FactSheet, to_speech=to_speech, lap_messages=None)  # fmt: skip
    hub.start()
    now = time.monotonic()
    for i, group in enumerate(("damage", "position", "flags")):
        m = race_message({"id": f"rc-{i}", "group": group, "call": "x", "kind": "race", "text": f"Call {i}."}, now)
        assert m is not None
        hub.scheduler.enqueue(m)
    held = race_message({"id": "rc-h", "group": "position", "call": "x", "kind": "race", "text": "Held."}, now)
    assert held is not None
    hub._held = (held, AudioClip(b"", 22_050), None)
    live.notify(RACE_RETRACT_NOTE, {"session_id": "other", "groups": ["position"]})  # another session: ignored
    live.notify(RACE_RETRACT_NOTE, {"session_id": "s1", "groups": ["position", "damage"]})
    end = time.monotonic() + 2.0
    while hub._held is not None and time.monotonic() < end:
        await asyncio.sleep(0.01)
    assert hub._held is None and [m.text for m in hub.scheduler.pending()] == ["Call 2."]
    await hub.stop()


# ============================================================================================ correctness 10: the name
class G2pTts(FakeTts):
    def __init__(self, dropped: list[str]) -> None:
        self.dropped = dropped
        self.asked: list[str] = []

    def g2p_dropped(self, text: str) -> list[str]:
        self.asked.append(text)
        return [w for w in self.dropped if w in text]


async def test_a_name_the_voice_cannot_say_switches_addressing_off() -> None:
    tts = G2pTts(["Zoë"])
    hub = RadioHub(LiveState(), RaceEngineer(None), FakeStt(), tts, RadioScheduler("normal"),
                   fact_sheet=FactSheet, to_speech=to_speech, lap_messages=None)  # fmt: skip
    hub.start()
    hub.apply_driver(Driver(1, "Sam Reid", 0.0, DriverPreferences()))
    hub.apply_driver(Driver(2, "Zoë Reid", 0.0, DriverPreferences()))
    end = time.monotonic() + 2.0
    while hub.addresser.name is not None and time.monotonic() < end:
        await asyncio.sleep(0.01)
    assert tts.asked == ["Sam", "Zoë"] and hub.addresser.name is None
    await hub.stop()


# ============================================================================================ correctness 11, 12
def test_leading_gap_wording() -> None:
    from pitwall.raceradio.wording import gap_report

    assert gap_report(None, None, 12.9, 0.3, True) == ("Leading by 12.9s, gap growing.", "You're leading by 12.9s.")
    assert gap_report(None, None, 2.1, -0.4, True)[0] == "Leading by 2.1s, gap shrinking."  # type: ignore[index]


# ============================================================================================ correctness 16: engines
def test_two_sources_keep_their_own_engines() -> None:
    live = LiveState()
    live.reset_session("udp", "test", False, "f1_25")
    w = RaceRadioWorker(live, start=False)
    w.submit("udp", info(0.0))
    w.submit("udp", frame(0.1, lap=3, pos=6))
    w.submit("ac", info(0.2, game=Game.AC, stype=SessionType.UNKNOWN))
    w.submit("udp", frame(0.3, lap=3, pos=6))
    w.process_pending()
    udp = w._engines["udp"]
    assert udp.st.info is not None and udp.st.position == 6 and set(w._engines) == {"udp", "ac"}
    assert live.race is not None and live.race["session_id"] == "udp"


# ============================================================================================ UX 1: speak windows
def test_field_zones_close_the_speak_window_before_a_learned_model() -> None:
    kn = {
        "track_id": "f1:17",
        "track_length_m": 5000.0,
        "corners": [{"entry_m": 3000.0, "exit_m": 3200.0}],
        "braking_zones": [
            {"onset_m": 1200.0, "onset_q25_m": 1180.0, "end_m": 1400.0, "min_speed_m": 1350.0},
            {"onset_m": 4900.0, "end_m": 80.0},  # over the line
        ],
        "severity_tags": [{"window_start_m": 2000.0, "window_end_m": 2100.0}],
    }
    model = field_zones.knowledge_model(kn, "f1:17")
    assert model is not None and model["length_m"] == 5000.0
    assert [(z["entry_m"], z["exit_m"]) for z in model["corners"]] == [
        (3000.0, 3200.0), (1180.0, 1400.0), (4900.0, 5000.0), (0.0, 80.0), (2000.0, 2100.0)
    ]  # fmt: skip
    assert field_zones.knowledge_model(kn, "f1:17") is model  # cached per knowledge object
    assert field_zones.knowledge_model(kn, "f1:3") is None  # another track's knowledge
    assert field_zones.build({"track_id": "x", "corners": [], "braking_zones": []}) is None
    live = LiveState()
    live.session = info(0.0)
    live.frame = frame(0.0, d=1000.0, speed=250.0)
    live.track_knowledge = kn
    hub = RadioHub(live, RaceEngineer(None), FakeStt(), FakeTts(), RadioScheduler("normal"),
                   fact_sheet=FactSheet, to_speech=to_speech, lap_messages=None)  # fmt: skip
    ttb = hub.driving_state().time_to_next_braking_s
    assert ttb is not None and ttb == pytest.approx((1180.0 - 15.0 - 1000.0) / (250.0 / 3.6))
    live.frame = frame(0.0, d=1300.0, speed=150.0)
    assert hub.driving_state().time_to_next_braking_s == 0.0  # inside the zone the heads-up cue already announced


# ============================================================================================ UX 3: the line
def lap_summary(now: float, lap: int = 8) -> RadioMessage:
    return RadioMessage(f"lap{lap}-summary", MessageKind.LAP_SUMMARY, Priority.NORMAL, f"Lap {lap}, 1:29.4.",
                        f"Lap {lap}, 1:29.4.", now, now + 45.0, lap_number=lap, meta={"lap_id": lap})  # fmt: skip


def countdown(now: float, text: str = "Two laps to go.") -> RadioMessage:
    m = race_message({"id": "rc-c", "group": "start", "call": "laps_2", "kind": "race", "priority": "high",
                      "text": text, "ttl_s": 30.0, "topic": "race:countdown", "allowance": False,
                      "data": {"laps_left": 2, "at_line": True}}, now)  # fmt: skip
    assert m is not None and m.meta[SUMMARY_MERGE_KEY] is True
    return m


def test_a_countdown_call_at_the_line_goes_out_inside_the_lap_summary() -> None:
    sch = RadioScheduler("normal")
    sch.enqueue(countdown(100.0))
    assert said(sch, 100.5) == []  # held for the summary
    sch.enqueue(lap_summary(101.2))
    [m] = said(sch, 101.5)
    assert (m.kind, m.text) == (MessageKind.LAP_SUMMARY, "Lap 8, 1:29.4. Two laps to go.")
    other = RadioScheduler("normal")
    other.enqueue(lap_summary(100.0))
    assert other.enqueue(countdown(100.2))
    assert [m.text for m in other.pending()] == ["Lap 8, 1:29.4. Two laps to go."]
    alone = RadioScheduler("normal")
    alone.enqueue(countdown(100.0))
    assert said(alone, 100.0 + SUMMARY_MERGE_HOLD_S - 0.1) == []
    assert [m.text for m in said(alone, 100.0 + SUMMARY_MERGE_HOLD_S)] == ["Two laps to go."]  # no summary came


# ============================================================================================ UX 6, 7: wording
def test_simple_words_never_count_places_lost() -> None:
    lost = {"id": "p", "group": "position", "call": "position_change", "kind": "race", "text": "Down to P9.",
            "text_simple": "You've dropped to 9th.", "data": {"position": 9, "before": 8}}  # fmt: skip
    assert race_message(lost, 0.0, simple=True) is None
    m = race_message(lost, 0.0)
    assert m is not None and m.text == "Down to P9."
    gained = {**lost, "text_simple": "You're up to 7th.", "data": {"position": 7, "before": 8}}
    m = race_message(gained, 0.0, simple=True)
    assert m is not None and m.text == "You're up to 7th."
    from pitwall.raceradio import wording as W

    assert W.lap1_summary(16, 1) == ("P16 after lap one, down 15.", "After lap one you're 16th.")
    assert W.warning(25, 1)[0] == "Track limits: first warning." and W.warning(25, 7)[0] == "Track limits: 7th warning."
    assert W.damage([("front_left_wing", "severe")], [], None, None)[0] == "Left front wing damage, severe."
    assert W.part_words("brakes_RL") == "rear left brakes"
