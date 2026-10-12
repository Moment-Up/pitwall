"""RECORDED tier: the race radio on the owner's real PS5 captures (F1 25 v1.26 format 2025, GT7 variant C).

Committed fixtures only (byte-for-byte excerpts, names scrubbed to ``Driver NN`` with the driver ids intact), run with
``scripts/race_radio_check.run`` (the engine per game session plus the radio policy's scheduler on the frames; no radio,
no network). What is pinned is what the game sent and the calls the rules make from it. The gaps between an excerpt's
windows are excerpt artefacts: only what lies inside a window is asserted. Nothing here is live validation.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from pitwall.ingest.capture import CaptureReader

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "recorded"

pytestmark = pytest.mark.recorded

_spec = importlib.util.spec_from_file_location("race_radio_check", ROOT / "scripts" / "race_radio_check.py")
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
sys.modules["race_radio_check"] = check  # its dataclasses look their module up
_spec.loader.exec_module(check)

_CACHE: dict[str, list[dict[str, Any]]] = {}


def run(name: str) -> dict[str, Any]:
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    if name not in _CACHE:
        _CACHE[name] = check.run(CaptureReader(path))
    sessions = [s for s in _CACHE[name] if s["frames"] > 0]
    assert len(sessions) == 1, [s["mode"] for s in sessions]
    s = sessions[0]
    assert s["ok"], {k: v for k, v in s["checks"].items() if not v["ok"]}
    return s


def calls(s: dict[str, Any], call: str | None = None) -> list[dict[str, Any]]:
    return [c for c in s["calls"] if call is None or c["call"] == call]


def at(c: dict[str, Any]) -> float:
    return float(c["t"])


# ---------------------------------------------------------------------------------------------- existing fixtures
def test_melbourne_start_grid_brief_lights_out_and_lap_one() -> None:
    s = run("f1_25_2025_ps5_melbourne_race-start-excerpt.pwcap")
    brief, go, lap1 = calls(s, "grid_brief"), calls(s, "lights_out"), calls(s, "lap1_summary")
    assert [c["text"] for c in brief] == ["P21 of 22, 3 laps."]  # the grid slot before the start (gridPosition 20)
    assert brief[0]["needs_window"] is False and brief[0]["ttl_s"] <= 2.0 and at(brief[0]) < 1.0
    assert [(c["text"], c["needs_window"], c["ttl_s"]) for c in go] == [("Go, go.", False, 1.5)]
    assert 7.0 < at(go[0]) < 7.5  # LGOT 7.23 s into the excerpt
    assert [(c["text"], c["lap"]) for c in lap1] == [("P8 after lap one, up 13.", 2)]
    assert not [c for c in calls(s, "position_change") if c["lap"] == 1]  # lap-1 churn: no single calls
    dispatched = {d["call"]: d for d in s["dispatched"]}
    assert dispatched["grid_brief"]["speed"] < 5.0  # said standing on the grid


def test_austria_countdown_and_no_names() -> None:
    s = run("f1_25_2025_ps5_austria_race-excerpt.pwcap")
    said = [(c["call"], c["text"], c["lap"]) for c in s["calls"] if c["group"] == "start"]
    assert ("laps_2", "Two laps to go.", 2) in said and ("last_lap", "Last lap.", 3) in said
    assert "Driver " not in json.dumps(s) and s["checks"]["7_names"]["leaks"] == 0


def test_monza_position_change_after_the_settle() -> None:
    s = run("f1_25_2025_ps5_monza_race-excerpt.pwcap")
    changes = calls(s, "position_change")
    assert [c["text"] for c in changes] == ["Down to P3."]
    assert 12.5 < at(changes[0]) < 13.5  # the change at 9.88 s (192.74 in the source), held 3 s


def test_imola_pit_exit_and_driver_names_from_the_table() -> None:
    s = run("f1_25_2025_ps5_imola_race-pitstop-excerpt.pwcap")
    assert [c["call"] for c in s["calls"] if c["group"] == "position"] == ["pit_exit_position"]  # none in the lane
    assert [c["text"] for c in calls(s, "pit_exit_position")] == ["Out of the pits in P1."]
    behind = s["view"]["behind"]
    assert behind["label"] == "Hamilton" and behind["label_kind"] == "driver"  # "Driver 01", driver id 7


def test_gt7_rolling_start_and_settled_positions() -> None:
    s = run("gt7_c_ps5_oval_race-start-3laps-excerpt.pwcap")
    assert s["mode"] == "race" and s["game"] == "gt7"
    assert [c["text"] for c in calls(s, "grid_brief")] == ["Rolling start. P8 of 14, 10 laps."]
    group = [c["text"] for c in s["calls"] if c["group"] == "position"]
    assert group == ["P11 after lap one, down 3.", "Up to P9, gained 2.", "Up to P8."]  # 8 -> 11 -> 8: three calls
    v = s["view"]
    assert v["position"] == 8 and v["position_tier"] == "community_documented"
    assert v["position_note"] == "From GT7's race position; not yet checked against the game's screen."


# ---------------------------------------------------------------------------------------------- the radio's fixtures
def test_austria_reverse_contact_warning_and_lap_one_without_single_position_calls() -> None:
    s = run("f1_25_2025_ps5_austria-reverse_race-yellow-warnings-excerpt.pwcap")
    assert [(c["call"], c["text"], c["data"]["infringement"]) for c in s["calls"]] == [
        ("warning", "Warning for contact.", 4)  # PENA 5/4 at 91.15 s in the source
    ]
    # the player's own FIA flag goes yellow at 105.31 s while cars stream past after its own contact: never a call


def test_monza_a_pass_then_a_penalty_is_never_praised() -> None:
    s = run("f1_25_2025_ps5_monza_race-pass-then-penalty-excerpt.pwcap")
    assert not calls(s, "clean_pass")  # the pass to P1 at 129.16 s, PENA 4/7 0.9 s later
    [pen] = calls(s, "penalty")
    assert (pen["text"], pen["data"]["time_s"], pen["data"]["infringement"]) == (
        "3 second penalty: cutting the track.",
        3,
        7,
    )
    assert pen["tier"] == "recorded" and pen["kind"] == "alert"
    assert [c["text"] for c in calls(s, "position_change")] == ["Up to P1."]  # held 5 s: a plain change
    assert [c["text"] for c in calls(s, "yellow_here")] == ["Yellow flag."]  # FIA yellow at 137.69 s, confirmed


def test_austria_lapped_blue_once_crash_retired_flashback_resends_ignored() -> None:
    s = run("f1_25_2025_ps5_austria_race-blue-damage-excerpt.pwcap")
    assert [c["call"] for c in s["calls"]] == ["blue_flag"]  # the second blue episode is within 30 s
    [blue] = calls(s, "blue_flag")
    assert blue["text"] == "Blue flag. Let the car behind through." and 3.4 < at(blue) < 3.7  # FIA blue 0.5 s
    # the crash at 111.57 s (both front wings gone, a puncture) is followed by PENA 16/42 before the damage settles:
    # retired, so no damage call and no yellow for its own crash; the flashback at 126.24 s restores the car silently
    # and the RTMT re-sends 0.74 s after it are not retirements
    assert not calls(s, "damage") and not calls(s, "yellow_here") and not calls(s, "retirement")


def test_jeddah_contact_damage_is_one_call_after_the_steps_settle() -> None:
    s = run("f1_25_2025_ps5_jeddah_race-damage-steps-excerpt.pwcap")
    [dmg] = calls(s, "damage")
    assert dmg["text"] == "Damage: front wing severe, floor severe. Box for a new front wing."
    assert dmg["kind"] == "alert" and dmg["data"]["advise_box"] is True
    assert 7.9 < at(dmg) < 8.4  # the last step at 5.71 s (wing 71 -> 100, floor 10 -> 99 within 0.8 s) + 1.5 s
    assert [c["text"] for c in calls(s, "warning")] == ["Warning for contact."]


def test_gt7_last_lap_and_the_finish() -> None:
    s = run("gt7_c_ps5_3800m_race-last-lap-finish-excerpt.pwcap")
    [last] = calls(s, "last_lap")
    assert last["text"] == "Last lap." and 5.0 < at(last) < 5.5  # the lap 3 -> 4 line at 1203.24 s
    [fin] = calls(s, "finish")
    assert fin["text"].startswith("Chequered flag. P4.") and 108.5 < at(fin) < 109.0  # lap 4 done at 1306.71 s
    # (the grid delta in this excerpt is an artefact: it starts mid-race)
