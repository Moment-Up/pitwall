"""Race radio answers (raceradio.answers via ai.radio_phrasing): who is ahead / behind, the position in any game,
penalties, damage and sector deltas, from the live race block and the lap facts; the game's capability otherwise."""

from __future__ import annotations

import copy
from typing import Any

from pitwall.ai.facts import build_fact_sheet
from pitwall.ai.grounding import check_grounding
from pitwall.ai.radio_phrasing import radio_answer
from pitwall.raceradio.model import off_view
from tests.unit.test_ai import _game_analysis


def race_block(**kw: Any) -> dict[str, Any]:
    v = off_view(None, "s1", False, "f1_25")
    v.update(
        mode="race",
        position=5,
        cars=20,
        grid_position=7,
        position_tier="spec_implemented",
        laps_left=3.4,
        penalties={
            "time_s": 5,
            "warnings": 2,
            "track_limits": 1,
            "drive_throughs": 0,
            "stop_gos": 0,
            "serve_at_stop": False,
        },
        damage={
            "grade": "major",
            "parts": [{"part": "front_left_wing", "pct": 41, "grade": "major"}],
            "puncture": ["RL"],
        },
        ahead={"label": "Norris", "label_kind": "driver", "position": 4, "gap_s": 1.2, "settled": True},
        behind={"label": "the Williams", "label_kind": "team", "position": 6, "gap_s": 0.8, "settled": True},
    )
    v.update(kw)
    return v


def sheet(game: str = "f1_25", **kw: Any) -> Any:
    sa = _game_analysis(game, "ps5")
    return build_fact_sheet(sa, {"session_id": "s1", "race": race_block(game=game, **kw)})


def test_who_is_ahead_and_behind() -> None:
    s = sheet()
    assert radio_answer("who_ahead", s, "Who's ahead?") == "Norris is ahead, P4, 1.2 seconds."
    assert radio_answer("who_ahead", s, "who is behind me") == "The Williams is behind, P6, 0.8 seconds."
    anon = sheet(ahead={"label": "the car ahead", "label_kind": "car", "position": 4, "gap_s": None, "settled": False})
    assert radio_answer("who_ahead", anon, "Who's in front?") == "The car ahead is P4."
    leading = sheet(position=1, ahead=None)
    assert radio_answer("who_ahead", leading, "Who's leading?") == "You're leading, 0.8 seconds clear."


def test_penalties_and_damage() -> None:
    s = sheet()
    assert radio_answer("penalties", s, "Do I have a penalty?") == (
        "5 seconds of penalties, 2 warnings, 1 for track limits."
    )
    clean = sheet(penalties={k: 0 for k in race_block()["penalties"]})
    assert radio_answer("penalties", clean, "any penalties?") == "No penalties and no warnings."
    dt = sheet(penalties={**race_block()["penalties"], "drive_throughs": 1, "time_s": 0, "warnings": 0})
    assert radio_answer("penalties", dt, "penalty?") == "A drive-through to serve."
    assert radio_answer("damage", s, "What's my damage?") == "Puncture, rear left. Left front wing damage, major."
    none = sheet(damage={"grade": "none", "parts": [], "puncture": []})
    assert radio_answer("damage", none, "any damage?") == "No damage."


def test_position_in_gt7_with_its_evidence_note() -> None:
    note = "From GT7's race position; not yet checked against the game's screen."
    s = sheet(game="gt7", penalties=None, damage=None, ahead=None, behind=None, position=8, cars=14, laps_left=6.8,
              position_note=note, position_tier="community_documented")  # fmt: skip
    # the note stays on screen (Drive) and in the fact, never in the spoken answer (as with the race calls)
    assert radio_answer("gaps", s, "What position am I?") == "P8 of 14, 7 laps to go."
    assert note in next(f.text for f in s.facts if f.topic == "race")
    assert radio_answer("penalties", s, "Do I have a penalty?") == "GT7 doesn't send penalties."
    assert radio_answer("who_ahead", s, "Who's ahead?") == "GT7 doesn't send data about the other cars."


def test_race_facts_only_for_this_sessions_live_block_and_grounded() -> None:
    sa = _game_analysis("f1_25", "ps5")
    stale = build_fact_sheet(sa, {"race": race_block(session_id="old")})
    assert not [f for f in stale.facts if f.topic == "race"]
    off = build_fact_sheet(sa, {"race": {**race_block(), "mode": "off"}})
    assert not [f for f in off.facts if f.topic == "race"]
    s = sheet()
    race = [f for f in s.facts if f.topic == "race"]
    assert [f.data["kind"] for f in race] == ["position", "ahead", "behind", "penalties", "damage"]
    for f in race:  # every number a deterministic answer says is in its fact
        assert check_grounding(f"{f.text} [{f.id}]", [f]).ok, f.text


def test_sector_deltas_from_the_lap_facts() -> None:
    sa = copy.deepcopy(_game_analysis("f1_25", "ps5"))
    for lap in sa.laps:
        if lap["lap_time_ms"]:
            n = lap["lap_number"]
            lap.update(s1_ms=21_000 + n, s2_ms=24_000 + (71 - n) * 10, s3_ms=lap["lap_time_ms"] - 45_000 - (71 - n) * 9)
    s = build_fact_sheet(sa, None)
    last = next(f for f in s.facts if f.topic == "laps" and f.data.get("lap") == 71 and "sectors_ms" in f.data)
    best = next(f for f in s.facts if f.topic == "laps" and "best_sectors_ms" in f.data)
    k = 1
    want = (last.data["sectors_ms"][k] - best.data["best_sectors_ms"][k]) / 1000
    said = radio_answer("sectors", s, "How was sector 2?")
    assert said == f"Sector 2, {last.data['sectors_ms'][k] / 1000:.2f}: " + (
        "level with your best." if f"{abs(want):.2f}" == "0.00" else f"plus {want:.2f} to your best."
    )
    splits = radio_answer("sectors", s, "What were my splits?")
    assert splits == "Sector 1 plus 0.01, sector 3 plus 0.56 to your best; the rest level."  # only what is off
    no_sectors = build_fact_sheet(_game_analysis("f1_25", "ps5"), None)  # the helper's laps have no sector times
    assert radio_answer("sectors", no_sectors, "How was sector 2?") is None
