"""Race radio positions (raceradio.positions): lap-1 summary, settled changes, clean passes, pit exit, other games."""

from __future__ import annotations

from pitwall.model.telemetry import FrameQuality, Game, SessionType
from tests.unit.raceradio_helpers import PLAYER, Run, event, info, participant, participants, race


def started(grid_pos: int = 7, lap1_pos: int = 5) -> Run:
    """An F1 race: on the grid in P``grid_pos``, lights out, lap 1 with churn, the line in P``lap1_pos``."""
    r = race()
    r.drive(0.0, 1.0, lap=1, d=-150.0, speed=0.0, pos=grid_pos)
    r.feed(event(1.0, "LGOT"))
    for i, p in enumerate((6, 8, 4, 9, 3, 6)):  # lap-1 churn: never a single position call
        r.drive(2.0 + 10 * i, 9.0 + 10 * i, lap=1, d=100.0 + 500 * i, pos=p)
    r.drive(70.0, 70.5, lap=1, d=4990.0, pos=lap1_pos)
    return r


def test_lap_one_summary_against_the_grid_and_no_call_on_lap_one() -> None:
    r = started()
    assert r.names == ["lights_out"]  # no position call on lap 1
    calls = r.drive(71.0, 71.2, lap=2, d=5.0, pos=5)
    assert [(c.call, c.text, c.text_simple, c.priority, c.topic, c.addressable) for c in calls] == [
        (
            "lap1_summary",
            "P5 after lap one, up 2.",
            "After lap one you're 5th. That's 2 places up.",
            "high",
            "race:position",
            True,
        )
    ]
    assert calls[0].speech_source == "P 5 after lap one, up 2."
    held = started(lap1_pos=7).drive(71.0, 71.2, lap=2, d=5.0, pos=7)
    assert [c.text for c in held] == ["P7 after lap one, held position."]
    lost = started(lap1_pos=9).drive(71.0, 71.2, lap=2, d=5.0, pos=9)
    assert [(c.text, c.addressable) for c in lost] == [("P9 after lap one, down 2.", False)]


def test_settle_cooldown_and_merging() -> None:
    r = started()
    r.drive(71.0, 72.0, lap=2, d=10.0, pos=5)  # lap-1 summary at 71
    assert r.drive(72.1, 95.0, lap=2, d=500.0, pos=5)[1:] == []
    assert r.drive(95.1, 97.9, lap=2, d=800.0, pos=4) == []  # held under 3 s
    calls = r.drive(98.0, 98.3, lap=2, d=900.0, pos=4)  # held 3 s, 27 s after the last position call
    assert [(c.text, c.text_simple, c.priority, c.addressable) for c in calls] == [
        ("Up to P4.", "You're up to 4th.", "normal", True)
    ]
    r.drive(99.0, 101.0, pos=3)
    r.drive(101.1, 104.0, pos=2)  # two more places within the cooldown ...
    assert r.drive(104.1, 117.0, pos=2) == []
    calls = r.drive(117.1, 118.5, pos=2)  # ... merged into one call when it ends (20 s after 98)
    assert [c.text for c in calls] == ["Up to P2, gained 2."]
    r.drive(140.0, 150.0, pos=6)
    assert [(c.text, c.addressable) for c in r.calls[-1:]] == [("Down to P6, lost 4.", False)]


def test_a_flicker_that_reverts_inside_the_settle_is_never_said() -> None:
    r = started()
    r.drive(71.0, 100.0, lap=2, pos=5)
    r.drive(100.1, 102.0, lap=2, pos=6)
    assert r.drive(102.1, 130.0, lap=2, pos=5)[0:] == []


def test_no_position_call_soon_after_a_flashback() -> None:
    r = started()
    r.drive(71.0, 100.0, lap=2, pos=5)
    r.feed(event(100.0, "FLBK", flashbackSessionTime=80.0))
    r.drive(100.1, 101.0, pos=8)  # the rewind puts the car back
    r.feed(event(101.5, "FLBK", flashbackSessionTime=81.0))  # and again
    assert r.drive(101.6, 106.4, pos=8) == []  # within 5 s of the last flashback
    assert [c.text for c in r.drive(106.5, 107.0, pos=8)] == ["Down to P8, lost 3."]


def test_pit_exit_position_ten_seconds_after_leaving_the_pit_lane() -> None:
    r = started()
    r.drive(71.0, 100.0, lap=2, pos=5)
    assert r.drive(100.1, 125.0, lap=2, pos=11, pit=1) == []  # no position call in the pit lane
    assert r.drive(125.1, 135.0, lap=3, pos=11, pit=0) == []
    calls = r.drive(135.1, 136.0, lap=3, pos=11)
    assert [(c.call, c.text, c.text_simple) for c in calls] == [
        ("pit_exit_position", "Out of the pits in P11.", "You're back on track in 11th.")
    ]
    assert r.drive(136.1, 170.0, lap=3, pos=11) == []  # the exit call set the spoken position


def _with_norris(r: Run) -> Run:
    r.feed(participants(0.0, [participant(4, driver=54, team=8, name="Driver 05")]))
    return r


def test_clean_pass_names_the_overtaken_ai_driver() -> None:
    r = _with_norris(started())
    r.drive(71.0, 100.0, lap=2, pos=5)
    r.feed(event(100.0, "OVTK", overtakingVehicleIdx=PLAYER, beingOvertakenVehicleIdx=4))
    assert r.drive(100.0, 104.9, lap=2, pos=4) == []  # a penalty for the move may still come (5 s)
    calls = r.drive(105.0, 105.5, lap=2, pos=4)
    assert [(c.call, c.text, c.text_simple, c.addressable) for c in calls] == [
        ("clean_pass", "Good move on Norris. P4.", "Nice overtake! You're 4th now.", True)
    ]
    assert calls[0].data["passed_name"] == "Norris"


def test_contact_or_a_penalty_turns_the_praise_into_a_plain_change() -> None:
    for extra in (
        event(99.5, "COLL", vehicle1Idx=PLAYER, vehicle2Idx=4),
        event(103.0, "PENA", vehicleIdx=PLAYER, penaltyType=4, infringementType=7, time=3),
    ):
        r = _with_norris(started())
        r.drive(71.0, 99.0, lap=2, pos=5)
        r.feed(event(100.0, "OVTK", overtakingVehicleIdx=PLAYER, beingOvertakenVehicleIdx=4))
        r.feed(extra)
        r.drive(100.0, 106.0, lap=2, pos=4)
        assert "clean_pass" not in r.names and "Up to P4." in [c.text for c in r.calls], extra.code


def test_one_praise_a_minute() -> None:
    r = _with_norris(started())
    r.drive(71.0, 100.0, lap=2, pos=5)
    r.feed(event(100.0, "OVTK", overtakingVehicleIdx=PLAYER, beingOvertakenVehicleIdx=4))
    r.drive(100.0, 130.0, lap=2, pos=4)
    r.feed(event(130.0, "OVTK", overtakingVehicleIdx=PLAYER, beingOvertakenVehicleIdx=2))
    r.drive(130.0, 140.0, lap=2, pos=3)
    assert [c.call for c in r.calls if c.group == "position"][-2:] == ["clean_pass", "position_change"]


def test_gt7_and_forza_race_mode_and_positions() -> None:
    gt7 = Run()
    gt7.feed(info(0.0, game=Game.GT7, stype=SessionType.UNKNOWN, total_laps=10, extra={"num_cars_pre_race": 14}))
    assert gt7.engine.st.mode == "off"  # no race position seen yet
    gt7.drive(0.0, 5.0, game=Game.GT7, lap=None, pos=8, quality=FrameQuality.NOT_RACING)
    assert gt7.engine.st.mode == "race" and gt7.engine.st.grid == 8
    gt7.drive(5.1, 30.0, game=Game.GT7, lap=1, pos=11)
    assert [c.text for c in gt7.drive(30.1, 31.0, game=Game.GT7, lap=2, pos=11)] == ["P11 after lap one, down 3."]
    v = gt7.engine.view()
    assert v["position"] == 11 and v["position_tier"] == "community_documented"
    assert v["position_note"] == "From GT7's race position; not yet checked against the game's screen."
    free_run = Run()
    free_run.feed(info(0.0, game=Game.GT7, stype=SessionType.UNKNOWN, total_laps=None))
    free_run.drive(0.0, 2.0, game=Game.GT7, lap=1, pos=None)
    assert free_run.engine.view()["reason"] == "GT7 sends a race position only in races"
    forza = Run()
    forza.feed(info(0.0, game=Game.FORZA_MOTORSPORT, stype=SessionType.UNKNOWN, total_laps=None))
    forza.drive(0.0, 1.0, game=Game.FORZA_MOTORSPORT, lap=1, pos=6)
    assert forza.engine.st.mode == "race" and forza.engine.st.grid == 6
    forza.drive(1.1, 60.0, game=Game.FORZA_MOTORSPORT, lap=1, pos=4)
    calls = forza.drive(60.1, 61.0, game=Game.FORZA_MOTORSPORT, lap=2, pos=4)
    assert [(c.text, c.tier) for c in calls] == [("P4 after lap one, up 2.", "community")]
