"""SYNTHETIC end to end: the dashboard snapshot additions D2, D4 and D6 after replaying the coaching demo.

These prove the pipeline against generated packets with known injected mistakes. They are NOT evidence that a
real game is compatible (see tests/recorded and tests/live).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.sim.scenarios import write_synthetic_capture

pytestmark = pytest.mark.synthetic


@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Runtime]:
    tmp: Path = tmp_path_factory.mktemp("dash")
    cap = tmp / "captures" / "demo.pwcap"
    write_synthetic_capture(cap)
    rt = Runtime(Settings(data_dir=tmp, llm_enabled=False))
    assert rt.start_replay(cap, speed=None).done.wait(60)
    rt.worker.join()
    rt.writer.flush()
    yield rt
    rt.close()


def test_session_state_ends_with_the_streams_session_ended_event(replayed: Runtime) -> None:
    snap = replayed.live.snapshot()
    assert snap["session_state"] == "ended"
    assert snap["session_state_info"]["cause"] == "session_ended"


def test_bests_of_a_replayed_synthetic_session_hold_no_records(replayed: Runtime) -> None:
    snap = replayed.live.snapshot(include_static=True)
    b = snap["bests"]
    clean = [lap for lap in snap["laps"] if lap["clean"]]
    assert b["session"]["lap_ms"] == min(lap["lap_time_ms"] for lap in clean)
    assert b["scope"]["track_id"].startswith("synthetic:") and not b["scope"]["records"]
    assert b["driver"] is None and b["household"] is None  # never a personal best or a family record
    assert replayed.live.snapshot()["bests"] == b  # every snapshot, not only the 5 s static payload


def test_coach_block_is_the_latest_compared_lap_with_all_wordings(replayed: Runtime) -> None:
    """The habits demo ends on lap 10 (invalid: compared and shown, never a habit lap). Nothing is said after it (its
    T4 reminder was said before the corner); the card shows the T4 habit being worked on, with every wording and
    its reminder, and the T5 braking habit sorted."""
    coach = replayed.live.snapshot()["coach"]
    assert coach is not None and coach["lap_number"] == 10 and coach["skill_level"] == "advanced"
    assert coach["picked"] == []
    point = coach["by_corner"]["T4"]
    assert point["kind"] == "low_min_speed" and not point["picked"] and point["habit"]["status"] == "focus"
    assert point["short"] == "T4: 9 km/h slower mid-corner"
    assert point["text_simple"] == "T4: you were 9 km/h slower at the slowest point of the corner."
    (focus,) = coach["focus"]
    assert focus["corner"] == "T4" and focus["reminder"]["text"] == "T4: apex speed, 9 down"
    assert {(h["corner"], h["kind"], h["status"]) for h in coach["habits"]} == {
        ("T4", "low_min_speed", "focus"),
        ("T5", "brake_early", "fixed"),
    }


def test_game_block_follows_the_replayed_data_and_never_reports_a_mismatch(replayed: Runtime) -> None:
    """GT7 selected while the SYNTHETIC F1 demo replays: the screens follow the F1 data (effective game), but a
    replay of generated packets is never real data, so there is no mismatch and no suggestion."""
    from pitwall import games

    replayed.store.replace(games.SECTION, games.new_selection("gt7:ps5", "dashboard").section())
    try:
        g = replayed.live.snapshot()["game"]
        assert g["selected_id"] == "gt7:ps5"
        assert g["effective_id"] is not None and g["effective_id"].startswith("f1_25")
        assert g["detected"]["real"] is False and g["detected"]["adapter_game"] == "f1_25"
        assert g["mismatch"] is None and g["suggestion"] is None
    finally:
        replayed.store.replace(games.SECTION, {})
    assert replayed.live.snapshot()["game"]["suggestion"] is None  # nothing selected: still no suggestion
