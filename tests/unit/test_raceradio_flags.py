"""Race radio flags (raceradio.flags): yellow ahead / here, blue, safety car / VSC, red flag. Hand-built items."""

from __future__ import annotations

from typing import Any

from pitwall.model.telemetry import SessionType
from tests.unit.raceradio_helpers import L, Run, event, frame, info, race

GREEN = [(i / 10, "green") for i in range(10)]  # ten 500 m zones: zone index i starts at i * 500 m


def zones(**yellow: int) -> list[tuple[float, str | None]]:
    """The ten zones, the given zone indexes (as keyword values) yellow."""
    idx = set(yellow.values())
    return [(f, "yellow" if i in idx else flag) for i, (f, flag) in enumerate(GREEN)]


def yellow_race(model: Any = None) -> Run:
    r = Run()
    if model is not None:
        r.engine.st.track_model = lambda: model
    r.feed(info(0.0, zones=GREEN))
    r.drive(0.0, 15.0, d=800.0, speed=250.0)  # fast for a while: no "slow" guard
    return r


# ---------------------------------------------------------------------------------------------- yellow ahead
def test_a_yellow_zone_ahead_in_the_window_is_called_once_per_lap() -> None:
    r = yellow_race()
    r.feed(info(15.05, zones=zones(z=3)))  # zone 4 (index 3) starts at 1500 m: 700 m ahead of the car at 800 m
    calls = r.drive(15.1, 16.0, d=800.0, speed=250.0)
    assert [c.call for c in calls] == []  # 700 m is beyond the window at 250 km/h (max(300, 10 s x 69 m/s) = 694 m)
    calls = r.drive(16.1, 17.0, d=900.0, speed=250.0)  # now 600 m ahead
    assert [(c.call, c.text, c.kind, c.priority, c.topic) for c in calls] == [
        ("yellow_ahead", "Yellow in sector 1.", "alert", "high", "race:yellow")
    ]
    c = calls[0]
    assert c.text_simple == "Yellow flag ahead in sector 1: slow down a little, no overtaking."
    assert c.data["zone"] == 4 and c.data["ahead_m"] == 600 and c.needs_window and not c.bypass_quiet
    assert c.ttl_s == min(15.0, 600 / (250 / 3.6) + 2.0)
    assert r.drive(17.1, 40.0, d=1000.0, speed=250.0) == []  # once per zone and lap


def test_the_window_bounds() -> None:
    # zone 4 starts at 1500 m; at 250 km/h the window is 150 m .. max(300, 10 s x 69.4 m/s) = 694 m
    for d, called in ((1360.0, False), (1340.0, True), (300.0, False), (1000.0, True)):  # 140 / 160 / 1200 / 500 m
        r = yellow_race()
        r.feed(info(15.05, zones=zones(z=3)))
        assert bool(r.drive(15.1, 15.5, d=d, speed=250.0)) is called, d


def test_slow_cars_keep_a_300_m_window() -> None:
    r = yellow_race()
    r.feed(info(15.05, zones=zones(z=3)))
    assert r.drive(15.1, 15.5, d=1150.0, speed=70.0) == []  # 350 m ahead, window 300 m
    assert [c.call for c in r.drive(15.6, 16.0, d=1250.0, speed=70.0)] == ["yellow_ahead"]  # 250 m


def test_the_players_own_incident_is_never_called() -> None:
    r = yellow_race()
    r.drive(15.0, 15.5, d=1520.0, speed=250.0)  # inside zone 4 (1500-2000 m) as it turns yellow
    r.feed(info(15.55, zones=zones(z=3)))
    assert r.drive(15.6, 300.0, d=1000.0, speed=250.0, lap=3) == []  # next lap, ahead again: still own
    r.feed(info(300.1, zones=GREEN))  # cleared
    r.feed(info(300.2, zones=zones(z=3)))  # yellow again, the car now well before it
    assert [c.call for c in r.drive(300.3, 301.0, d=1000.0, speed=250.0, lap=4)] == ["yellow_ahead"]


def test_less_than_150_m_past_the_start_or_slow_is_own_too() -> None:
    r = yellow_race()
    r.feed(info(15.05, zones=zones(z=2)))  # zone 3 starts at 1000 m; the car is at 800 m, fast: not own
    assert [c.call for c in r.drive(15.1, 15.5, d=800.0, speed=250.0)] == ["yellow_ahead"]
    r2 = yellow_race()
    r2.drive(15.0, 15.2, d=1100.0, speed=250.0)  # 100 m past zone 3's start as it turns yellow
    r2.feed(info(15.25, zones=zones(z=2)))
    assert r2.drive(16.0, 200.0, d=700.0, speed=250.0, lap=3) == []
    r3 = yellow_race()
    r3.drive(15.0, 15.2, d=200.0, speed=50.0)  # slow (a spin) somewhere else as it turns yellow
    r3.feed(info(15.25, zones=zones(z=2)))
    assert r3.drive(16.0, 30.0, d=700.0, speed=250.0) == []


def test_cooldown_and_suppression() -> None:
    r = yellow_race()
    r.feed(info(15.05, zones=zones(a=3, b=6)))  # zones 4 (1500 m) and 7 (3000 m)
    assert len(r.drive(15.1, 15.3, d=1000.0)) == 1
    assert r.drive(20.0, 20.5, d=2500.0) == []  # zone 7 in the window, but within 15 s of the last yellow call
    for kw, setup in (
        ({"pit": 1}, None),
        ({"speed": 55.0}, None),
        ({}, "sc"),
    ):
        r = yellow_race()
        if setup == "sc":
            r.feed(info(15.0, zones=GREEN, sc="full"))
        r.feed(info(15.05 if setup is None else 18.5, zones=zones(z=3), sc="full" if setup else "none"))
        assert [c.call for c in r.drive(19.0, 19.5, d=1000.0, **kw) if c.call == "yellow_ahead"] == [], (kw, setup)


def test_corner_name_from_the_learned_track_model() -> None:
    model = {"length_m": L, "corners": [{"name": "T5", "entry_m": 1700.0, "exit_m": 1800.0}]}
    r = yellow_race(model)
    r.feed(info(15.05, zones=zones(z=3)))
    calls = r.drive(15.1, 15.3, d=1000.0)
    assert [(c.text, c.data["corner"]) for c in calls] == [("Yellow ahead, T5.", "T5")]
    assert calls[0].speech_source is None  # no position in it


def test_view_shows_the_nearest_yellow_ahead() -> None:
    r = yellow_race()
    r.feed(info(15.05, zones=zones(z=3)))
    r.drive(15.1, 15.2, d=500.0, speed=250.0)
    assert r.engine.view()["flags"]["yellow_ahead"] == {"zone": 4, "ahead_m": 1000, "corner": None}


# ---------------------------------------------------------------------------------------------- yellow here
def test_own_fia_yellow_confirmed_a_second_later_with_its_guards() -> None:
    r = race()
    r.drive(0.0, 15.0)
    assert r.drive(15.1, 16.0, fia="yellow") == []  # not yet: confirmed a second after the flag turned yellow
    calls = r.drive(16.1, 16.3, fia="yellow")
    assert [(c.call, c.text) for c in calls] == [("yellow_here", "Yellow flag.")]
    r.drive(16.4, 17.0, fia="green")
    r.drive(17.1, 18.0, fia="none")
    assert r.drive(30.0, 32.0, fia="yellow") == []  # within 30 s of the last yellow call
    r.drive(32.1, 33.0, fia="none")
    assert [c.call for c in r.drive(50.0, 51.5, fia="yellow")] == ["yellow_here"]
    r.drive(51.6, 52.0, fia="none")
    r.drive(70.0, 75.0, speed=60.0)  # slow: the player's own spin
    assert r.drive(80.0, 82.0, fia="yellow") == []  # slow within the 10 s before the flag
    r.drive(82.1, 90.0, fia="none")
    r.feed(event(91.0, "FLBK", flashbackSessionTime=50.0))
    assert r.drive(95.0, 97.0, fia="yellow") == []  # within 10 s of a flashback
    r.drive(97.1, 98.0, fia="none")
    assert r.drive(110.0, 112.0, fia="yellow", pit=1) == []  # in the pits


def test_own_crash_turning_the_flag_yellow_is_not_a_yellow_call() -> None:
    """Real F1 25 (the Austria 71-lap run): the player's FIA flag turns yellow in the packet of the player's own crash."""
    from tests.unit.raceradio_helpers import damage

    r = race()
    r.drive(0.0, 15.0, damage=damage())
    r.feed(frame(15.0, fia="yellow", damage=damage(fl=100, fr=100)))  # the crash: still at speed in this frame
    assert [c.call for c in r.drive(15.1, 17.0, fia="yellow", damage=damage(fl=100, fr=100))] == ["damage"]
    r2 = race()
    r2.drive(0.0, 15.0)
    r2.feed(frame(15.0, fia="yellow"))
    assert r2.drive(15.1, 17.0, fia="yellow", speed=40.0) == []  # it slowed right after: a spin


# ---------------------------------------------------------------------------------------------- blue
def test_blue_needs_half_a_second_one_call_per_episode_and_30_s() -> None:
    r = race()
    r.drive(0.0, 5.0)
    assert r.feed(frame(5.0, fia="blue"), frame(5.3, fia="blue")) == []  # 0.3 s: not yet
    calls = r.feed(frame(5.6, fia="blue"))
    assert [(c.call, c.text, c.topic) for c in calls] == [
        ("blue_flag", "Blue flag. Let the car behind through.", "race:blue")
    ]
    assert r.drive(5.7, 9.0, fia="blue") == []  # the same episode
    r.feed(frame(9.1, fia="yellow"))  # real blue episodes flicker 2 <-> 3 / 1 / 0
    assert r.drive(9.2, 20.0, fia="blue") == []  # a new episode, but within 30 s
    r.feed(frame(36.0, fia="none"))
    assert [c.call for c in r.drive(36.1, 37.0, fia="blue")] == ["blue_flag"]


def test_blue_in_practice_and_never_from_marshal_zones() -> None:
    r = race(stype=SessionType.PRACTICE)
    r.drive(0.0, 2.0)
    assert [c.text for c in r.drive(2.0, 3.0, fia="blue")] == ["Blue flag: car behind on a fast lap."]
    r = Run()
    r.feed(info(0.0, zones=[(i / 10, "blue") for i in range(10)]))  # every zone blue: a car is being lapped somewhere
    assert r.drive(0.0, 60.0, d=800.0, fia="none") == []


# ---------------------------------------------------------------------------------------------- SC / VSC
def test_safety_car_from_the_session_packet_and_scar_one_call_per_period() -> None:
    r = race()
    r.drive(0.0, 2.0)
    calls = r.feed(info(2.5, sc="full"))
    assert [(c.call, c.text, c.bypass_quiet, c.topic) for c in calls] == [
        ("sc_deployed", "Safety car, safety car. No overtaking.", True, "race:sc")
    ]
    assert r.feed(event(3.0, "SCAR", safetyCarType=1, eventType=0)) == []  # the same period
    calls = r.feed(event(60.0, "SCAR", safetyCarType=1, eventType=1))
    assert [(c.call, c.text) for c in calls] == [("sc_ending", "Safety car in this lap.")]
    assert r.feed(event(90.0, "SCAR", safetyCarType=1, eventType=2)) == []  # returned: in the pit lane, no green yet
    calls = r.feed(event(96.0, "SCAR", safetyCarType=1, eventType=3))
    assert [(c.call, c.text, c.bypass_quiet) for c in calls] == [("green", "Green flag, racing.", False)]
    assert r.feed(info(96.5, sc="full")) == []  # the 2 Hz packet lagging the SCAR edge: not a new period
    assert r.feed(info(100.0, sc="full")) == []  # still lagging, past SCAR_LAG_S: no second period before "none"
    assert r.feed(info(100.5, sc="none")) == []
    assert r.engine.flags.period == 1


def test_safety_car_returned_is_not_green_and_a_lagging_session_packet_never_redeploys() -> None:
    """The Session packet still reads "full" for seconds after SCAR "returned" (the car in the pit lane) and even
    after "resume": one deployed, one ending and one green call, the green only at "resume" [synthetic probe]."""
    r = race()
    r.drive(0.0, 5.0, lap=3)
    calls = list(r.feed(event(5.0, "SCAR", safetyCarType=1, eventType=0)))
    t = 5.0
    while t < 60.0:
        t += 0.5
        calls += r.feed(info(t, sc="full"), frame(t, lap=3))
    calls += r.feed(event(60.0, "SCAR", safetyCarType=1, eventType=1))
    while t < 90.0:
        t += 0.5
        calls += r.feed(info(t, sc="full"), frame(t, lap=4))
    calls += r.feed(event(90.0, "SCAR", safetyCarType=1, eventType=2))
    while t < 100.0:
        t += 0.5
        calls += r.feed(info(t, sc="full"), frame(t, lap=4))
    assert [c.call for c in calls] == ["sc_deployed", "sc_ending"]  # no green while the car is still on its way in
    calls += r.feed(event(100.0, "SCAR", safetyCarType=1, eventType=3))
    while t < 110.0:
        t += 0.5
        calls += r.feed(info(t, sc="full" if t < 106.0 else "none"), frame(t, lap=4))
    assert [c.call for c in calls] == ["sc_deployed", "sc_ending", "green"]
    assert r.engine.flags.period == 1
    # a new safety car after the Session packet read none again
    assert [c.call for c in r.feed(info(140.0, sc="full"))] == ["sc_deployed"]


def test_vsc_from_scar_then_green_from_the_session_packet() -> None:
    r = race()
    r.drive(0.0, 2.0)
    assert [c.text for c in r.feed(event(5.0, "SCAR", safetyCarType=2, eventType=0))] == [
        "Virtual safety car. Slow down, no overtaking."
    ]
    assert r.feed(info(5.5, sc="virtual")) == []
    assert [c.text for c in r.feed(event(50.0, "SCAR", safetyCarType=2, eventType=1))] == ["VSC ending."]
    assert [c.call for c in r.feed(info(60.0, sc="none"))] == ["green"]
    assert r.engine.view()["flags"]["track"] == "green"


def test_scar_formation_lap_and_type_zero_are_ignored() -> None:
    r = race()
    r.drive(0.0, 2.0)
    for ev in (0, 1, 2, 3):
        assert r.feed(event(3.0 + ev, "SCAR", safetyCarType=3, eventType=ev)) == []
        assert r.feed(event(10.0 + ev, "SCAR", safetyCarType=0, eventType=ev)) == []
    assert r.engine.flags.period == 0


def test_no_safety_car_calls_outside_races() -> None:
    r = race(stype=SessionType.QUALIFYING)
    r.drive(0.0, 2.0)
    assert r.feed(info(3.0, stype=SessionType.QUALIFYING, sc="full")) == []


# ---------------------------------------------------------------------------------------------- red flag
def test_red_flag_is_urgent_once_per_flag() -> None:
    r = race()
    r.drive(0.0, 2.0)
    calls = r.feed(event(10.0, "RDFL"))
    assert [(c.call, c.kind, c.priority, c.needs_window, c.bypass_quiet, c.ttl_s) for c in calls] == [
        ("red_flag", "alert", "urgent", False, True, 15.0)
    ]
    assert calls[0].text == "Red flag, red flag. Slow down, back to the pits."
    assert r.feed(event(40.0, "RDFL")) == []  # the same flag
    assert r.engine.view()["flags"]["track"] == "red"
    assert [c.call for c in r.feed(event(75.0, "RDFL"))] == ["red_flag"]
    payload = calls[0].urgent_payload(123.0)
    assert payload["source"] == "raceradio" and payload["t_mono"] == 123.0 and payload["ttl_s"] == 15.0


def test_red_flag_goes_out_even_when_retired_or_finished_but_not_with_the_mode_off() -> None:
    r = race()
    r.drive(0.0, 2.0)
    r.engine.st.retired = r.engine.st.finished = True
    assert [c.call for c in r.feed(event(10.0, "RDFL"))] == ["red_flag"]
    off = Run()
    off.feed(info(0.0, stype=SessionType.TIME_TRIAL))
    assert off.feed(event(1.0, "RDFL")) == []
