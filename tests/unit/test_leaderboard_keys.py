"""Board keys (``leaderboard.keys``): every part exact, an unknown value its own bucket, the string form round trips,
layouts group lengths within 3 %, and the words never show a raw id."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.leaderboard import keys as K
from tests.unit.leaderboard_data import AUSTRIA_KEY, F1_ASSISTS, UNFILLED_TAIL


def raw(**kw: Any) -> dict[str, Any]:
    """A board row of the owner's Austria race: Haas, dry, braking medium, ABS on, TC full, auto gears, full line."""
    d: dict[str, Any] = {
        "game": "f1_25",
        "track_id": "f1:17",
        "car_id": "f1:team:7",
        "family": "f1",
        "session_type": "race",
        "weather_condition": "overcast",
        "a_braking": F1_ASSISTS["braking"],
        "a_gearbox": F1_ASSISTS["gearbox"],
        "a_line": F1_ASSISTS["dynamic_racing_line"],
        "a_ecp": F1_ASSISTS["equal_car_performance"],
        "lap_abs": 1,
        "lap_tc": 2,
    }
    d.update(kw)
    return d


def test_the_owner_s_austria_race_key() -> None:
    k = K.key_of(raw(), 4318)
    assert k.encode() == AUSTRIA_KEY
    assert K.decode(AUSTRIA_KEY) == k
    assert k.fields() == {
        "game": "f1_25",
        "track_id": "f1:17",
        "layout_m": 4318,
        "car_id": "f1:team:7",
        "car_class": "f1",
        "equal_performance": 0,
        "category": "race",
        "conditions": "dry",
        "assists": {"braking": 2, "abs": 1, "tc": 2, "gearbox": 3, "racing_line": 2},
        "assists_code": "b2.a1.t2.g3.l2",
    }


@pytest.mark.parametrize(
    ("change", "part", "value"),
    [
        ({"session_type": "time_trial"}, "category", "time_trial"),
        ({"session_type": "unknown"}, "category", "unknown"),
        ({"session_type": None}, "category", "unknown"),
        ({"weather_condition": "light_rain"}, "conditions", "wet"),
        ({"weather_condition": "storm"}, "conditions", "wet"),
        ({"weather_condition": "clear"}, "conditions", "dry"),
        ({"weather_condition": None}, "conditions", "unknown"),
        ({"weather_condition": ""}, "conditions", "unknown"),
        ({"car_id": None}, "car_id", "?"),
        ({"family": None}, "car_class", "?"),
        ({"family": "f2"}, "car_class", "f2"),
        ({"a_ecp": 1}, "equal_performance", "1"),
        ({"lap_abs": None}, "assists", "b2.a?.t2.g3.l2"),
        ({"lap_abs": False, "lap_tc": 0}, "assists", "b2.a0.t0.g3.l2"),
        ({"lap_tc": 7}, "assists", "b2.a1.t?.g3.l2"),  # out of the spec's range: unknown, never guessed
        ({"a_braking": 3}, "assists", "b3.a1.t2.g3.l2"),
    ],
)
def test_each_part_is_exact_and_unknown_is_its_own_bucket(change: dict[str, Any], part: str, value: str) -> None:
    k = K.key_of(raw(**change), 4318)
    assert K.parts(k)[part] == value
    assert k != K.key_of(raw(), 4318) or part == "conditions"  # "clear" and "overcast" are both dry
    assert K.decode(k.encode()) == k


def test_an_unfilled_session_tail_leaves_the_session_assists_unknown() -> None:
    """F1 25 sends gearboxAssist 0 (not in the spec's 1-3) for the first ~1.5 s: no Session assist is trusted then;
    ABS and TC come from the lap and stay known."""
    tail = {f"a_{k}": v for k, v in (("braking", 0), ("gearbox", 0), ("line", 0), ("ecp", 0))}
    assert UNFILLED_TAIL["gearbox"] == 0
    k = K.key_of(raw(**tail), 4318)
    assert K.parts(k)["assists"] == "b?.a1.t2.g?.l?"
    assert k.equal_performance is None


def test_ac_reports_abs_and_tc_and_gt7_reports_none() -> None:
    ac = K.key_of({"game": "ac", "track_id": "ac:monza", "car_id": "ac:ks_ferrari", "a_abs": True, "a_tc": 0}, 5793)
    assert ac.encode() == "ac~ac:monza~5793~ac:ks_ferrari~-~-~unknown~unknown~a1.t0"
    assert [c["label"] for c in K.assist_chips(ac)] == ["ABS on", "Traction control off"]
    gt7 = K.key_of({"game": "gt7", "track_id": "gt7:sf:380:120:15:3800:530", "car_id": "gt7:car:3353"}, 3799)
    assert gt7.encode() == "gt7~gt7:sf:380:120:15:3800:530~3799~gt7:car:3353~-~-~unknown~unknown~-"
    assert K.assist_chips(gt7) == [
        {"key": "assists", "value": None, "known": False, "label": "Assists not reported by this game"}
    ]
    assert not gt7.assists_reported and gt7.car_class is None and gt7.equal_performance is None
    # the session-level F1 fields mean nothing outside F1
    assert K.key_of({"game": "gt7", "track_id": "x", "a_braking": 2, "a_gearbox": 3, "family": "f1"}, 1).assists == ()


def test_ids_with_separators_round_trip() -> None:
    k = K.key_of(raw(track_id="odd~track%1", car_id="car?"), None)
    text = k.encode()
    assert text.split("~")[1:4] == ["odd%7Etrack%251", "?", "car%3F"]
    assert K.decode(text) == k
    assert K.parts(k)["layout_m"] == "?" and k.layout_m is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "f1_25~f1:17",
        "~f1:17~4318~?~f1~0~race~dry~b2.a1.t2.g3.l2",
        "f1_25~f1:17~43a~?~f1~0~race~dry~b2.a1.t2.g3.l2",
        "f1_25~f1:17~4318~?~f9~0~race~dry~b2.a1.t2.g3.l2",
        "f1_25~f1:17~4318~?~f1~2~race~dry~b2.a1.t2.g3.l2",
        "f1_25~f1:17~4318~?~f1~0~sprint~dry~b2.a1.t2.g3.l2",
        "f1_25~f1:17~4318~?~f1~0~race~damp~b2.a1.t2.g3.l2",
        "f1_25~f1:17~4318~?~f1~0~race~dry~b2.a1.t2.g3",
        "f1_25~f1:17~4318~?~f1~0~race~dry~b9.a1.t2.g3.l2",
        "f1_25~f1:17~4318~?~f1~0~race~dry~b2.a1.t2.g0.l2",
        "f1_25~f1:17~4318~?~f1~0~race~dry~b2.b1.t2.g3.l2",
        "f1_25~f1:17~4318~?~f1~0~race~dry~-",
        "gt7~x~1~?~f1~-~unknown~unknown~-",
        "gt7~x~1~?~-~-~unknown~unknown~a1.t0",
        "ac~x~1~?~-~-~unknown~unknown~a1",
    ],
)
def test_keys_that_do_not_parse_are_refused(text: str) -> None:
    with pytest.raises(K.BadKey):
        K.decode(text)


def test_layouts_group_lengths_within_three_percent() -> None:
    # 4318 and 4323 (+0.1 %) are one layout; 4400 is +1.9 % of 4318: the same; 4480 is +3.75 %: another
    clusters = K.layout_clusters([4323.0, 4318.0, None, 4400.0, 4480.0, -1.0, 4318.0])
    assert clusters == {4318.0: 4318, 4323.0: 4318, 4400.0: 4318, 4480.0: 4480}
    assert K.layout_for(4323.0, clusters) == 4318
    assert K.layout_for(4330.0, clusters) == 4318  # a new length near a layout joins it
    assert K.layout_for(9000.0, clusters) == 9000  # far from every layout: its own
    assert K.layout_for(None, clusters) is None
    assert K.layout_for(0, clusters) is None


def test_words() -> None:
    k = K.key_of(raw(lap_abs=None, lap_tc=None), 4318)
    assert K.assists_text(k) == (
        "Braking assist medium, ABS unknown, Traction control unknown, Automatic gears, Racing line full"
    )
    assert K.car_class_label(k) == "F1 car"
    assert K.equal_performance_label(k) == "Realistic car performance"
    unknown = K.key_of(raw(family=None, a_gearbox=0), 4318)
    assert K.car_class_label(unknown) == "Car class unknown"
    assert K.equal_performance_label(unknown) == "Car performance setting unknown"
    assert K.CATEGORY_LABELS[k.category] == "Race" and K.CONDITION_LABELS["unknown"] == "Weather unknown"


def test_raw_of_session_reads_a_stored_session_and_lap() -> None:
    session = {
        "game": "f1_25",
        "track_id": "f1:17",
        "car_id": "f1:team:7",
        "session_type": "race",
        "weather": {"condition": "clear"},
        "assists": F1_ASSISTS,
        "info": {"formula": "F1 World", "packet_format": 2025},
    }
    r = K.raw_of_session(session, {"abs_active": True, "traction_control": 2})
    assert K.key_of(r, 4318).encode() == AUSTRIA_KEY
    assert K.parts(K.key_of(K.raw_of_session(session), 4318))["assists"] == "b2.a?.t?.g3.l2"
