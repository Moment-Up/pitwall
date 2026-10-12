"""Race radio names (raceradio.roster): official AI names only, personal names never in a call, a view or a repr."""

from __future__ import annotations

import json

from pitwall.adapters.f1 import enums
from pitwall.raceradio.roster import Roster, team_label
from tests.unit.raceradio_helpers import PLAYER, Run, car, event, frame, participant, participants, race, timing

CANARY = "Zz_Canary_Gamertag"


def test_driver_radio_names() -> None:
    assert enums.DRIVER_RADIO_NAMES[54] == "Norris" and enums.DRIVER_RADIO_NAMES[7] == "Hamilton"
    assert enums.DRIVER_RADIO_NAMES[206] == "van Hoepen"  # 2026 doc v1.2
    assert enums.DRIVER_RADIO_NAMES[165] == "Antonelli" and enums.DRIVER_RADIO_NAMES[80] == "Zhou"
    assert enums.DRIVER_RADIO_NAMES[83] == "Correa" and enums.DRIVER_RADIO_NAMES[10] == "Hülkenberg"
    assert enums.DRIVER_RADIO_NAMES[192] == "Minì"
    assert set(enums.DRIVER_RADIO_NAMES) == set(enums.DRIVERS) and {255, 65535} == enums.DRIVER_ID_NONE


def test_labels_and_personal() -> None:
    r = Roster()
    r.update(
        participants(
            0.0,
            [
                participant(0, ai=True, driver=54, team=8, number=4, name="LANDO NORRIS"),
                participant(1, ai=True, driver=None, team=8, number=81, name=CANARY),  # F1 World AI: a player's ID
                participant(2, ai=False, driver=None, team=188, number=23, name=CANARY),  # a human
                participant(3, ai=True, driver=None, team=41, number=None, name=CANARY),  # F1 Generic, no number
                participant(4, ai=None, driver=7, team=None, number=44, name=CANARY),  # control unknown
            ],
        )
    )
    assert [r.label(i) for i in range(6)] == [
        ("driver", "Norris"),
        ("team", "the McLaren"),
        ("team", "the Williams"),  # "Williams '24": the year suffix dropped
        ("car", "a car"),  # every F1 World car is "F1 Generic": no team label
        ("number", "car 44"),  # an id in the table, but not known to be AI: never a driver name
        ("car", "a car"),  # not in the table at all
    ]
    assert [r.personal(i) for i in range(6)] == [False, True, True, True, True, True]
    assert r.personal_name(0) is None and r.personal_name(1) == CANARY
    assert CANARY not in repr(r) and CANARY not in repr(r._cars[1])
    assert team_label(None) is None and team_label(41) is None and team_label(2) == "the Red Bull Racing"


def test_generic_placeholders_are_never_a_name() -> None:
    r = Roster()
    r.update(participants(0.0, [participant(1, ai=False, driver=None, name="Driver 03"), participant(
        2, ai=False, driver=None, name="Player")]))  # fmt: skip
    assert r.personal_name(1) is None and r.personal_name(2) is None


def test_no_call_or_view_ever_carries_a_packet_name() -> None:
    """Property over every builder that names a car: the canary roster's names never reach a call, the view or the
    urgent payload (only official names from the driver table, a team, a number)."""
    r = race(total_laps=20)
    names = [participant(i, ai=i % 2 == 0, driver=None if i % 3 else 54, team=8, name=f"{CANARY}{i}") for i in range(8)]
    names[PLAYER] = participant(PLAYER, ai=False, driver=None, name=f"{CANARY}me")
    r.feed(participants(0.0, names))
    for lap in range(1, 8):
        for i in range(180):
            t = lap * 100.0 + i * 0.5
            cars = [car(k, k + 1, lap=lap, gap_ms=1200, pit=1 if (lap == 4 and k == 2 and i > 90) else 0) for k in
                    range(8)]  # fmt: skip
            r.feed(frame(t, lap=lap, d=10.0 + i * 25.0, pos=PLAYER + 1), timing(t, cars))
        r.feed(event(lap * 100.0 + 50, "FTLP", vehicleIdx=lap % 8, lapTime=90.0 + lap))
        r.feed(event(lap * 100.0 + 60, "OVTK", overtakingVehicleIdx=PLAYER, beingOvertakenVehicleIdx=lap % 8))
        r.feed(event(lap * 100.0 + 70, "RTMT", vehicleIdx=(lap + 3) % 8, reason=lap % 11))
    r.feed(event(800.0, "RDFL"))
    assert len(r.calls) >= 5
    blob = json.dumps([c.to_dict() for c in r.calls] + [r.engine.view()] + [r.calls[-1].urgent_payload(1.0)])
    assert CANARY not in blob
    assert "Norris" in blob  # the official names do get through


def test_unscrubbed_name_in_an_ai_slot_with_a_driver_id_is_still_not_used() -> None:
    r = Run()
    r.engine.st.roster.update(participants(0.0, [participant(5, ai=True, driver=54, name=CANARY)]))
    assert r.engine.st.roster.label(5) == ("driver", "Norris")  # the table's name, never the packet's
