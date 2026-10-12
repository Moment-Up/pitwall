"""Race radio damage (raceradio.damage): settle, grades, punctures, wear-like parts, faults, re-baselining."""

from __future__ import annotations

from pitwall.raceradio.damage import aero_grade, brake_grade
from tests.unit.raceradio_helpers import Run, damage, event, frame, race


def clean_race(total_laps: int = 10) -> Run:
    r = race(total_laps=total_laps)
    r.drive(0.0, 3.0, damage=damage())  # the session's first values: the silent baseline
    return r


def test_grades() -> None:
    assert [aero_grade(v) for v in (0, 9, 10, 29, 30, 59, 60, 100)] == [0, 0, 1, 1, 2, 2, 3, 3]
    assert [brake_grade(v) for v in (0, 29, 30, 59, 60)] == [0, 0, 2, 2, 3]


def test_one_call_after_the_real_jeddah_step_pattern_settles() -> None:
    r = clean_race()
    # the floor going 3 -> 16 -> 28 -> 31 -> 33 within 0.45 s, the front wing broken in the same contact [M]
    steps = [(3.10, 3, 0), (3.20, 16, 40), (3.35, 28, 71), (3.45, 31, 100), (3.55, 33, 100)]
    for t, floor, wing in steps:
        assert r.feed(frame(t, damage=damage(floor=floor, fl=wing))) == []
    assert r.drive(3.6, 5.0, damage=damage(floor=33, fl=100)) == []  # under 1.5 s since the last step
    calls = r.drive(5.1, 5.3, damage=damage(floor=33, fl=100))
    assert [(c.call, c.text, c.kind, c.priority, c.bypass_quiet) for c in calls] == [
        ("damage", "Damage: left front wing severe, floor major. Box for a new front wing.", "alert", "high", True)
    ]
    assert calls[0].data["advise_box"] is True and calls[0].text_simple.startswith("The front wing is damaged.")
    assert calls[0].tier == "recorded"  # wings and floor: said on real captures


def test_minor_is_a_race_call_and_major_an_alert_without_bypass() -> None:
    r = clean_race()
    r.drive(4.0, 6.0, damage=damage(sidepod=15))
    assert [(c.text, c.kind, c.priority, c.tier) for c in r.calls] == [
        ("Sidepod damage, minor.", "race", "normal", "synthetic")  # no real capture said a sidepod
    ]
    r.drive(30.0, 32.0, damage=damage(sidepod=15, rw=40))
    assert [(c.text, c.kind, c.bypass_quiet) for c in r.calls[1:]] == [("Rear wing damage, major.", "alert", False)]


def test_non_severe_waits_for_the_cooldown_severe_always_goes() -> None:
    r = clean_race()
    r.drive(4.0, 6.0, damage=damage(sidepod=15))
    r.drive(7.0, 9.0, damage=damage(sidepod=15, diffuser=12))  # minor again, within 20 s
    assert r.names == ["damage"]
    r.drive(9.1, 27.0, damage=damage(sidepod=15, diffuser=12))  # retried when the cooldown ends (20 s after 5.5)
    assert [c.text for c in r.calls[1:]] == ["Diffuser damage, minor."]
    r.drive(28.0, 35.0, damage=damage(sidepod=15, diffuser=12, rw=100))
    assert r.names == ["damage", "damage"]  # severe within 10 s of the last call: waits for what else breaks
    r.drive(35.1, 36.0, damage=damage(sidepod=15, diffuser=12, rw=100, floor=70))
    r.drive(36.1, 38.0, damage=damage(sidepod=15, diffuser=12, rw=100, floor=70))
    assert [c.text for c in r.calls[2:]] == ["Damage: rear wing severe, floor severe."]  # one call for the incident


def test_a_puncture_never_waits_for_the_severe_merge() -> None:
    r = clean_race()
    r.drive(4.0, 6.0, damage=damage(fl=80))
    r.feed(frame(7.0, damage=damage(fl=80, tyres=(0, 0, 100, 0))))
    calls = r.drive(7.1, 9.0, damage=damage(fl=80, tyres=(0, 0, 100, 0)))
    assert [c.text for c in calls] == ["Puncture, rear left. Box this lap."]


def test_both_front_wings_read_front_wing() -> None:
    r = clean_race()
    r.drive(4.0, 6.0, damage=damage(fl=45, fr=35))
    assert [c.text for c in r.calls] == ["Front wing damage, major."]


def test_puncture_is_a_jump_not_wear() -> None:
    r = clean_race()
    r.drive(4.0, 6.0, damage=damage(tyres=(40, 41, 30, 30)))  # wear-like values: nothing
    r.feed(frame(7.0, damage=damage(tyres=(40, 41, 30, 100))))  # RR jumps to 100
    calls = r.drive(7.1, 9.0, damage=damage(tyres=(40, 41, 30, 100)))
    assert [(c.text, c.text_simple, c.bypass_quiet) for c in calls] == [
        ("Puncture, rear right. Box this lap.", "Puncture on the rear right tyre. Come into the pits.", True)
    ]
    assert calls[0].data["puncture"] == ["RR"]
    assert calls[0].tier == "synthetic"  # every real 100 % came with a retirement or a flashback first
    slow = clean_race()
    for i, v in enumerate(range(60, 100, 4)):  # 60 -> 96 over 10 s: wear, never a puncture
        slow.feed(frame(4.0 + i, damage=damage(tyres=(v, 0, 0, 0))))
    slow.drive(15.0, 20.0, damage=damage(tyres=(96, 0, 0, 0)))
    assert slow.calls == []


def test_no_box_advice_on_the_last_lap() -> None:
    r = race(total_laps=3)
    r.drive(0.0, 3.0, lap=3, damage=damage())
    r.feed(frame(4.0, lap=3, damage=damage(tyres=(0, 0, 100, 0))))
    calls = r.drive(4.1, 6.0, lap=3, damage=damage(tyres=(0, 0, 100, 0)))
    assert [c.text for c in calls] == ["Puncture, rear left."]


def test_gearbox_and_engine_wear_never_called_a_sudden_step_is() -> None:
    r = clean_race()
    for i in range(1, 6):  # +1 every few laps [M]
        r.drive(10.0 * i, 10.0 * i + 2, damage=damage(gearbox=i, engine=i))
    assert r.calls == []
    r.feed(frame(70.0, damage=damage(gearbox=5, engine=17)))
    r.drive(70.1, 72.0, damage=damage(gearbox=5, engine=17))
    assert [c.text for c in r.calls] == ["Engine damage, major."]
    r.drive(80.0, 82.0, damage=damage(gearbox=5, engine=17, blown=True))
    assert r.calls[-1].text.startswith("Engine failure.") and r.calls[-1].tier == "synthetic"


def test_faults_once_each() -> None:
    r = clean_race()
    r.drive(4.0, 6.0, damage=damage(drs=True))
    r.drive(7.0, 9.0, damage=damage(drs=True, ers=True))
    r.drive(10.0, 12.0, damage=damage(drs=False, ers=True))
    r.drive(13.0, 15.0, damage=damage(drs=True, ers=True))
    assert [(c.call, c.text, c.kind) for c in r.calls] == [
        ("fault", "DRS fault.", "race"),
        ("fault", "ERS fault.", "race"),
    ]


def test_flashback_and_repair_re_baseline_silently() -> None:
    r = clean_race()
    r.drive(4.0, 6.0, damage=damage(fl=80))
    assert r.names == ["damage"]
    r.feed(event(7.0, "FLBK", flashbackSessionTime=50.0))
    r.drive(7.1, 10.0, damage=damage(fl=0))  # the flashback restores the pre-crash wing [M]
    r.drive(10.1, 13.0, damage=damage(fl=80))  # the same crash again after the rewind: news again
    assert r.names == ["damage", "damage"]
    r.drive(40.0, 42.0, damage=damage(fl=0))  # a new wing in the pits: silent
    assert len(r.calls) == 2
    joined = race()
    joined.drive(0.0, 3.0, damage=damage(fl=60, floor=40))  # joined with damage on the car: the baseline
    assert joined.calls == []
    assert joined.engine.view()["damage"]["grade"] == "severe"


def test_view() -> None:
    r = clean_race()
    r.drive(4.0, 6.0, damage=damage(fl=58, brakes=(0, 0, 35, 0), tyres=(0, 0, 0, 100)))
    v = r.engine.view()["damage"]
    assert v == {
        "grade": "severe",
        "parts": [{"part": "front_left_wing", "pct": 58, "grade": "major"}, {"part": "brakes_RL", "pct": 35,
                                                                               "grade": "major"}],
        "puncture": ["RR"],
    }  # fmt: skip
    r.drive(7.0, 9.0, damage=damage(fl=58, fr=12, rw=100, floor=33, brakes=(0, 0, 35, 0)))
    assert [p["part"] for p in r.engine.view()["damage"]["parts"]] == ["rear_wing", "front_left_wing", "brakes_RL"]
