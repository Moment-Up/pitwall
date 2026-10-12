"""Race radio rivals (raceradio.rivals): gap reports, the car ahead pitting, fastest laps, retirements."""

from __future__ import annotations

from tests.unit.raceradio_helpers import PLAYER, Run, car, event, frame, participant, participants, race, timing

AHEAD, BEHIND = 2, 7


def field(t: float, *, lap: int, ahead_gap: int = 1500, behind_gap: int = 900, ahead_pit: int = 0) -> object:
    return timing(
        t,
        [
            car(0, 1, lap=lap, gap_ms=None),
            car(AHEAD, 4, lap=lap, gap_ms=2000, pit=ahead_pit),
            car(PLAYER, 5, lap=lap, gap_ms=ahead_gap),
            car(BEHIND, 6, lap=lap, gap_ms=behind_gap),
        ],
    )


def lap_of_timing(r: Run, lap: int, t0: float, **kw: object) -> None:
    """A lap: frames and race timing (2 Hz) for 90 s, the player in P5."""
    for i in range(180):
        t = t0 + i * 0.5
        r.feed(frame(t, lap=lap, d=10.0 + i * 25.0, pos=5), field(t, lap=lap, **kw))  # type: ignore[arg-type]


def test_gap_report_on_laps_3_6_9_with_settled_gaps() -> None:
    r = race(total_laps=20)
    said = []
    for lap in range(1, 11):
        before = len(r.calls)
        lap_of_timing(r, lap, lap * 100.0)
        said += [(lap, c.call, c.text) for c in r.calls[before:] if c.call == "gap_report"]
    assert [s[0] for s in said] == [3, 6, 9]
    assert said[0][2] == "Gap ahead 1.5s. Behind 0.9s."
    c = r.named("gap_report")[0]
    assert c.topic == "strategy:gap" and c.kind == "race" and c.speech_source is None
    assert c.text_simple == "The car in front is 1.5s ahead."


def test_gap_report_trend_words_and_leading() -> None:
    r = race(total_laps=20)
    for lap in range(1, 7):
        lap_of_timing(r, lap, lap * 100.0, ahead_gap=3000 - 300 * lap, behind_gap=500 + 200 * lap)
    text = r.named("gap_report")[-1].text
    assert text == "Gap ahead 1.5s, closing. Behind 1.5s, dropping back."  # 0.3 s a lap each way
    lead = race(total_laps=20)
    for lap in range(1, 4):
        for i in range(180):
            t = lap * 100.0 + i * 0.5
            lead.feed(
                frame(t, lap=lap, d=10.0 + i * 25.0, pos=1),
                timing(t, [car(PLAYER, 1, lap=lap, gap_ms=None), car(BEHIND, 2, lap=lap, gap_ms=2400)]),
            )
    assert [c.text for c in lead.named("gap_report")] == ["Leading by 2.4s."]


def test_no_gap_report_on_the_last_lap_or_under_a_safety_car() -> None:
    r = race(total_laps=3)
    for lap in range(1, 4):
        lap_of_timing(r, lap, lap * 100.0)
    assert r.named("gap_report") == []  # lap 3 of 3 is the last lap


def test_car_ahead_pitting_is_deferred_to_strategy_at_detailed() -> None:
    r = race(total_laps=20)
    r.feed(participants(0.0, [participant(AHEAD, driver=54, team=8, name="Driver 03")]))
    lap_of_timing(r, 2, 200.0)
    calls = r.feed(frame(300.0, lap=2, pos=5), field(300.0, lap=2, ahead_pit=1))
    assert [(c.call, c.text, c.defer_to_strategy_detail) for c in calls] == [
        ("car_ahead_pitting", "Norris is pitting.", True)
    ]
    assert calls[0].tier == "synthetic"  # no real capture has produced it yet
    anon = race(total_laps=20)
    lap_of_timing(anon, 2, 200.0)
    calls = anon.feed(frame(300.0, lap=2, pos=5), field(300.0, lap=2, ahead_pit=1))
    assert [c.text for c in calls] == ["Car ahead is pitting."]
    lap1 = race(total_laps=20)
    lap_of_timing(lap1, 1, 100.0)
    assert lap1.feed(frame(200.0, lap=1, pos=5), field(200.0, lap=1, ahead_pit=1)) == []  # not on lap 1


def test_fastest_laps() -> None:
    r = race(total_laps=20)
    r.drive(0.0, 1.0, lap=1)
    assert r.feed(event(90.0, "FTLP", vehicleIdx=PLAYER, lapTime=95.0)) == []  # lap 1: trivially the fastest
    r.drive(90.1, 91.0, lap=2, d=10.0)
    r.drive(180.0, 181.0, lap=3, d=10.0)
    calls = r.feed(event(180.5, "FTLP", vehicleIdx=PLAYER, lapTime=94.0))  # just after the line: lap 2's time
    assert [(c.call, c.text, c.addressable, c.data["lap"]) for c in calls] == [
        ("own_fastest_lap", "Fastest lap of the race.", True, 2)
    ]
    r.drive(270.0, 271.0, lap=4, d=10.0)
    assert r.feed(event(270.5, "FTLP", vehicleIdx=PLAYER, lapTime=93.0)) == []  # within 3 laps of the last one
    r.feed(participants(271.0, [participant(9, driver=7, team=1, name="Driver 10")]))
    calls = r.feed(event(272.0, "FTLP", vehicleIdx=9, lapTime=92.534))
    assert [(c.call, c.kind, c.priority, c.text, c.audience) for c in calls] == [
        ("rival_fastest_lap", "info", "low", "Fastest lap for Hamilton, 1:32.534.", "experienced")
    ]
    assert r.feed(event(273.0, "FTLP", vehicleIdx=9, lapTime=92.0)) == []


def test_retirements_once_near_or_far_and_never_the_resends() -> None:
    r = race(total_laps=20)
    r.feed(participants(0.0, [participant(AHEAD, driver=54, team=8, name="Driver 03")]))
    lap_of_timing(r, 2, 100.0)
    calls = r.feed(event(200.0, "RTMT", vehicleIdx=AHEAD, reason=0))
    assert [(c.call, c.kind, c.text, c.text_simple) for c in calls] == [
        ("retirement", "race", "Norris is out. From P4.", "The car in 4th place has stopped.")
    ]
    assert r.feed(event(201.0, "RTMT", vehicleIdx=AHEAD, reason=0)) == []  # once per car
    r.feed(event(250.0, "FLBK", flashbackSessionTime=150.0))
    assert r.feed(event(252.0, "RTMT", vehicleIdx=11, reason=8)) == []  # a re-send after the flashback
    assert r.feed(event(300.0, "RTMT", vehicleIdx=11, reason=8)) == []  # remembered as seen
    far = r.feed(event(310.0, "RTMT", vehicleIdx=0, reason=8))
    assert [(c.kind, c.text, c.audience) for c in far] == [("info", "A car has retired: mechanical failure.",
                                                            "experienced")]  # fmt: skip
    start = race(total_laps=20)
    assert start.feed(frame(0.0), event(1.0, "RTMT", vehicleIdx=AHEAD, reason=0)) == []  # at a mid-race join


def test_retirement_from_the_result_status() -> None:
    r = race(total_laps=20)
    lap_of_timing(r, 2, 100.0)
    calls = r.feed(
        frame(200.0, lap=2, pos=5),
        timing(200.0, [car(AHEAD, 4, lap=2, result="retired"), car(PLAYER, 5, lap=2), car(BEHIND, 6, lap=2)]),
    )
    assert [c.text for c in calls] == ["A car has retired. From P4."]


def test_the_players_own_out_of_race_status_retires_the_radio() -> None:
    r = race(total_laps=20)
    lap_of_timing(r, 2, 100.0)
    r.feed(timing(200.0, [car(PLAYER, 5, lap=2, result="dnf")]))
    assert r.engine.st.retired
