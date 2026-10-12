"""Race radio start and countdown (raceradio.countdown): grid brief, lights out, laps to go, finish, minutes left."""

from __future__ import annotations

from pitwall.model.telemetry import FrameQuality, Game, SessionType
from pitwall.raceradio.engine import RaceRadioEngine
from tests.unit.raceradio_helpers import PLAYER, Run, car, event, frame, info, lap_done, race, timing


def grid(r: Run, t0: float, t1: float, pos: int = 7) -> None:
    r.drive(t0, t1, lap=1, d=-150.0, speed=0.0, pos=pos)


def test_grid_brief_at_ssta_on_the_grid_no_speak_window_short_ttl() -> None:
    r = race(total_laps=3)
    r.feed(timing(0.0, [car(i, i + 1, lap=1) for i in range(20)]))
    grid(r, 0.0, 0.5)
    calls = r.feed(event(0.6, "SSTA"), frame(0.65, lap=1, d=-150.0, speed=0.0, pos=7))
    assert [(c.call, c.text, c.text_simple, c.kind, c.priority, c.needs_window) for c in calls] == [
        ("grid_brief", "P7 of 20, 3 laps.", "You start 7th of 20. 3 laps.", "race", "high", False)
    ]
    assert 1.9 <= calls[0].ttl_s <= 2.0 and calls[0].speech_source == "P 7 of 20, 3 laps."
    calls = r.feed(event(6.0, "LGOT"))
    assert [(c.call, c.text, c.ttl_s, c.needs_window) for c in calls] == [("lights_out", "Go, go.", 1.5, False)]
    assert r.engine.st.grid == 7
    assert [c.allowance for c in r.calls] == [False, False]  # said standing still: never lap 1's race allowance


def test_no_brief_when_moving_or_late_and_stlg_arms_it_when_ssta_was_missed() -> None:
    r = race()
    r.drive(0.0, 1.0, lap=1, speed=40.0)  # rolling: not on the grid
    assert r.feed(event(1.0, "SSTA")) == [] and r.drive(1.1, 4.0, lap=1, speed=40.0) == []
    r = race()
    calls = r.feed(event(0.0, "STLG", numLights=1), frame(0.1, lap=1, speed=0.0, pos=3))
    assert [c.text for c in calls] == ["P3, 10 laps."]  # no field size known yet: no "of N"
    assert r.feed(event(0.8, "STLG", numLights=2)) == []  # said once


def test_formation_lap_session_brief_and_the_memo_skips_the_race_brief() -> None:
    memo: dict[tuple[str | None, int | None], float] = {}
    formation = Run(RaceRadioEngine("formation", memo=memo))
    formation.feed(info(0.0, sc="formation_lap", uid="1"))
    calls = formation.feed(frame(0.1, lap=1, speed=80.0, pos=4))
    assert [(c.call, c.needs_window, c.ttl_s, c.text) for c in calls] == [("grid_brief", True, 30.0, "P4, 10 laps.")]
    assert calls[0].tier == "recorded"  # Imola 2026-10-11 made it in the formation-lap session
    race_session = Run(RaceRadioEngine("race", memo=memo))
    race_session.feed(info(120.0, uid="2"))
    grid(race_session, 120.0, 121.0, pos=4)
    assert race_session.feed(event(121.0, "SSTA"), frame(121.1, lap=1, speed=0.0, pos=4)) == []
    later = Run(RaceRadioEngine("later", memo=memo))
    later.feed(info(900.0, uid="3"))
    grid(later, 900.0, 900.5)
    assert [c.call for c in later.feed(event(901.0, "SSTA"), frame(901.1, lap=1, speed=0.0))] == ["grid_brief"]


def test_gt7_rolling_start_brief_before_lap_1() -> None:
    r = Run()
    r.feed(info(0.0, game=Game.GT7, stype=SessionType.UNKNOWN, total_laps=10, extra={"num_cars_pre_race": 14}))
    calls = r.feed(frame(0.1, game=Game.GT7, lap=None, speed=79.0, pos=8, quality=FrameQuality.NOT_RACING))
    assert [(c.call, c.text, c.text_simple, c.needs_window, c.ttl_s) for c in calls] == [
        ("grid_brief", "Rolling start. P8 of 14, 10 laps.", "Rolling start. You start 8th of 14. 10 laps.", True, 20.0)
    ]
    assert r.engine.st.grid == 8


def test_laps_to_go() -> None:
    r = race(total_laps=10)
    said = []
    for lap in range(2, 11):
        said += [(lap, c.call, c.text) for c in r.drive(lap * 100.0, lap * 100.0 + 0.2, lap=lap, d=5.0)]
    assert said == [(6, "laps_5", "Five laps to go."), (9, "laps_2", "Two laps to go."), (10, "last_lap", "Last lap.")]
    assert [c.priority for c in r.calls] == ["normal", "high", "high"] and r.named("last_lap")[0].addressable
    short = race(total_laps=8)
    for lap in range(2, 9):
        short.drive(lap * 100.0, lap * 100.0 + 0.2, lap=lap, d=5.0)
    assert short.names == ["laps_2", "last_lap"]  # five to go only in races of 10 laps or more
    three = race(total_laps=3)
    for lap in range(2, 4):
        three.drive(lap * 100.0, lap * 100.0 + 0.2, lap=lap, d=5.0)
    assert three.names == ["last_lap"]  # two to go only in races of 5 laps or more (the brief said "3 laps")
    assert all(not c.allowance and c.data["at_line"] for c in r.calls)  # outside the race allowance, at the line
    assert all(c.tier == "recorded" for c in r.calls)


def test_lapped_last_lap_and_the_flag_out_variant() -> None:
    r = race(total_laps=10)
    r.drive(800.0, 800.2, lap=8, d=10.0, pos=15)
    # the leader is on its last lap, 4.5 km round: when it finishes the player (one lap down) is on its last lap too
    r.feed(timing(899.0, [car(0, 1, lap=10, d=4500.0), car(PLAYER, 15, lap=8, d=4990.0)]))
    calls = r.drive(900.0, 900.2, lap=9, d=5.0, pos=15)
    assert [c.text for c in calls] == ["Last lap: the leader finishes first."]
    assert calls[0].data == {"source": "leader", "at_line": True}
    assert calls[0].tier == "synthetic"  # no real capture had the leader finish first
    r = race(total_laps=10)
    r.drive(800.0, 801.0, lap=8, d=1000.0, pos=15)
    calls = r.feed(event(810.0, "CHQF"))
    assert [c.text for c in calls] == ["Flag's out. Last lap."]
    assert calls[0].tier == "synthetic" and "at_line" not in calls[0].data  # mid-lap: never folded into a summary
    leader = race(total_laps=10)
    leader.drive(800.0, 801.0, lap=10, d=1000.0, pos=1)
    assert leader.feed(event(810.0, "CHQF")) == []  # the player is the leader: the finish call comes instead


def test_finish_with_the_grid_delta_then_only_urgent_calls() -> None:
    r = race(total_laps=3)
    grid(r, 0.0, 0.5, pos=7)
    r.feed(event(1.0, "LGOT"))
    r.drive(300.0, 300.2, lap=3, d=100.0, pos=3)
    calls = r.feed(lap_done(310.0, 3, final=True))
    assert [(c.call, c.text, c.text_simple, c.ttl_s) for c in calls] == [
        ("finish", "Chequered flag. P3. Up 4 from the grid.", "That's the finish. You came 3rd.", 60.0)
    ]
    assert r.engine.st.finished
    assert r.drive(311.0, 340.0, lap=3, d=100.0, pos=9, fia="blue") == []  # nothing but urgent after the flag
    assert [c.call for c in r.feed(event(350.0, "RDFL"))] == ["red_flag"]


def test_finish_with_time_penalties_still_to_add_is_the_position_on_the_road() -> None:
    from tests.unit.raceradio_helpers import pens

    r = race(total_laps=3)
    grid(r, 0.0, 0.5, pos=7)
    r.feed(event(1.0, "LGOT"))
    r.drive(300.0, 300.2, lap=3, d=100.0, pos=3, penalties=pens(time_s=5))
    calls = r.feed(lap_done(310.0, 3, final=True))
    assert [(c.text, c.text_simple, c.data["time_penalties_s"]) for c in calls] == [
        (
            "Chequered flag. P3 on the road, 5 seconds to add.",
            "That's the finish. You crossed the line 3rd; 5 seconds will be added.",
            5,
        )
    ]


def test_finish_never_counts_places_lost() -> None:
    r = race(total_laps=3)
    grid(r, 0.0, 0.5, pos=2)
    r.feed(event(1.0, "LGOT"))
    r.drive(300.0, 300.2, lap=3, d=100.0, pos=20)
    assert [c.text for c in r.feed(lap_done(310.0, 3, final=True))] == ["Chequered flag. P20."]


def test_gt7_finish_on_the_last_lap_completion() -> None:
    r = Run()
    r.feed(info(0.0, game=Game.GT7, stype=SessionType.UNKNOWN, total_laps=4, extra={"num_cars_pre_race": 12}))
    r.drive(0.0, 1.0, game=Game.GT7, lap=4, pos=4)
    assert r.feed(lap_done(2.0, 3, game=Game.GT7)) == []
    assert [c.text for c in r.feed(lap_done(100.0, 4, game=Game.GT7))] == ["Chequered flag. P4."]


def test_minutes_left_only_in_practice_and_qualifying_and_never_for_zero() -> None:
    r = race(stype=SessionType.PRACTICE, time_left=320.0)
    r.drive(0.0, 1.0)
    calls = r.feed(info(5.0, stype=SessionType.PRACTICE, time_left=299.0))
    assert [(c.call, c.text) for c in calls] == [("minutes_5", "Five minutes left in the session.")]
    assert r.feed(info(5.5, stype=SessionType.PRACTICE, time_left=200.0)) == []
    assert [c.text for c in r.feed(info(6.0, stype=SessionType.PRACTICE, time_left=59.0))] == ["One minute left."]
    q = race(stype=SessionType.QUALIFYING, time_left=0.0)  # one-shot qualifying sends 0
    q.drive(0.0, 1.0)
    assert q.feed(info(2.0, stype=SessionType.QUALIFYING, time_left=0.0)) == []
    rc = race(time_left=7200.0)
    rc.drive(0.0, 1.0)
    assert rc.feed(info(2.0, time_left=59.0)) == []  # races: never
