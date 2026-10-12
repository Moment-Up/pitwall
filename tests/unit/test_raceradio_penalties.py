"""Race radio penalties (raceradio.penalties): every penalty type per Appendix A, warnings, served, retired."""

from __future__ import annotations

import pytest

from pitwall.adapters.f1 import enums
from pitwall.raceradio import wording as W
from tests.unit.raceradio_helpers import PLAYER, event, frame, pens, race

# type -> (call, kind, priority, bypass quiet); None = not said
TABLE: dict[int, tuple[str, str, str, bool] | None] = {
    0: ("penalty", "alert", "high", True),
    1: ("penalty", "alert", "high", True),
    2: ("penalty", "race", "normal", False),
    3: ("serve_reminder", "alert", "high", True),
    4: ("penalty", "alert", "high", False),
    5: ("warning", "race", "normal", False),
    6: ("penalty", "alert", "high", True),
    7: ("penalty", "race", "normal", False),
    8: ("penalty", "alert", "high", False),
    9: ("penalty", "alert", "high", False),
    10: None,
    11: ("next_lap_invalid", "race", "normal", False),
    12: None,
    13: ("next_lap_invalid", "race", "normal", False),
    14: ("previous_lap_invalid", "race", "normal", False),
    15: ("previous_lap_invalid", "race", "normal", False),
    16: None,
    17: ("penalty", "alert", "high", True),
}


def pena(t: float, ptype: int, inf: int = 4, time: int = 5, car: int = PLAYER) -> object:
    return event(t, "PENA", penaltyType=ptype, infringementType=inf, vehicleIdx=car, time=time, lapNum=2)


def test_the_table_covers_every_penalty_type_of_the_spec() -> None:
    assert set(TABLE) == set(enums.PENALTY_TYPES)


@pytest.mark.parametrize("ptype", sorted(TABLE))
def test_each_penalty_type(ptype: int) -> None:
    r = race()
    r.drive(0.0, 1.0)
    calls = r.feed(pena(1.0, ptype, inf=7, time=3))
    calls += r.drive(1.1, 2.0, penalties=pens(cc=1))
    want = TABLE[ptype]
    if want is None:
        assert calls == []
        return
    assert [(c.call, c.kind, c.priority, c.bypass_quiet, c.group) for c in calls] == [(*want, "penalties")]
    assert calls[0].topic == ("race:warning" if ptype == 5 else None)  # two different penalties are both said
    if want[0] in ("next_lap_invalid", "previous_lap_invalid"):
        assert calls[0].tier == "synthetic"  # PENA 11/13/14/15 never came in a real capture


def test_wording_of_time_penalties_and_drive_throughs() -> None:
    r = race()
    r.drive(0.0, 1.0)
    calls = r.feed(pena(1.0, 4, inf=7, time=3), pena(2.0, 4, inf=29, time=10), pena(3.0, 4, inf=3, time=255))
    assert [c.text for c in calls] == [
        "3 second penalty: cutting the track.",
        "10 second penalty: track limits.",
        "Time penalty: a collision.",
    ]
    assert calls[0].text_simple == "3 seconds will be added to your race time for cutting the track."
    assert calls[0].tier == "recorded" and calls[0].data["time_s"] == 3
    calls = r.feed(pena(4.0, 0, inf=17), pena(5.0, 1, inf=99))
    assert [(c.text, c.text_simple, c.tier) for c in calls] == [
        ("Drive-through penalty: speeding in the pit lane.", "You must drive through the pit lane: speeding in the "
         "pit lane.", "recorded"),  # a real drive-through: 0/34 (a jump start) in the Sakhir sprint
        ("Stop-go penalty.", "You must stop in your pit box.", "synthetic"),  # an unknown code: no reason, no guess
    ]  # fmt: skip


def test_track_limit_warnings_say_the_count_read_after_the_pena() -> None:
    r = race()
    r.drive(0.0, 1.0, penalties=pens(cc=1))
    assert r.feed(pena(1.0, 5, inf=27)) == []  # waits 0.3 s for the counters
    r.feed(frame(1.1, penalties=pens(cc=1)))
    calls = r.feed(frame(1.31, penalties=pens(cc=2, warnings=2)))
    assert [(c.text, c.text_simple, c.data["track_limits"]) for c in calls] == [
        ("Track limits warning, 2.", "Warning for cutting the track. Keep inside the white lines.", 2)
    ]
    assert r.feed(pena(10.0, 5, inf=4)) == []  # at most one warning call every 20 s
    calls = r.feed(pena(25.0, 5, inf=4))
    assert [(c.text, c.text_simple) for c in calls] == [
        ("Warning for contact.", "Warning for contact. Give the other cars more room.")
    ]
    assert [c.text for c in r.feed(pena(50.0, 5, inf=12))] == ["Warning: ignoring yellow flags."]


def test_served_and_other_cars_penalties() -> None:
    r = race()
    r.drive(0.0, 1.0)
    assert r.feed(pena(1.0, 4, car=7)) == []  # another car's penalty
    dt = r.feed(event(2.0, "DTSV", vehicleIdx=PLAYER))
    assert [(c.text, c.tier) for c in dt] == [("Drive-through served.", "recorded")]  # the Sakhir sprint
    sg = r.feed(event(3.0, "SGSV", vehicleIdx=PLAYER, stopTime=5.0))
    assert [(c.text, c.tier) for c in sg] == [("Stop-go served.", "synthetic")]  # never in a real capture
    assert r.feed(event(4.0, "DTSV", vehicleIdx=1)) == []


def test_reminder_words() -> None:
    assert W.serve_reminder(16)[0] == "Serve the drive-through this lap."
    assert W.serve_reminder(15)[0] == "Drive-through still to serve."
    assert W.serve_reminder(46)[0] == "Penalty still to serve."


def test_retired_mutes_everything_but_urgent_until_a_flashback() -> None:
    r = race()
    r.drive(0.0, 1.0)
    assert r.feed(pena(1.0, 16, inf=42)) == [] and r.engine.st.retired
    assert r.drive(1.1, 40.0, fia="blue") == [] and r.feed(pena(41.0, 4)) == []
    assert [c.call for c in r.feed(event(42.0, "RDFL"))] == ["red_flag"]
    r.feed(event(45.0, "FLBK", flashbackSessionTime=20.0))
    assert not r.engine.st.retired
    assert [c.call for c in r.feed(pena(50.0, 4))] == ["penalty"]


def test_every_infringement_has_words_or_says_no_reason() -> None:
    assert set(W.INFRINGEMENT_WORDS) == set(enums.INFRINGEMENTS)
    for words in W.INFRINGEMENT_WORDS.values():
        assert words is None or (words == words.lower().replace("fermé", "fermé") and "invalid" not in words)
    assert W.reason_words(None) is None and W.reason_words(54) is None and W.reason_words(200) is None
