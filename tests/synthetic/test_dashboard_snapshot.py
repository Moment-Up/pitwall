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
    coach = replayed.live.snapshot()["coach"]
    assert coach is not None and coach["lap_number"] == 7 and coach["skill_level"] == "advanced"
    (point,) = coach["picked"]
    assert point["kind"] == "brake_early" and point["corner"] == "T1" and point["picked"]
    assert point["short"] == "T1: braked 20 m earlier"
    assert point["text_simple"] == "T1: you braked about 20 m earlier than on your reference lap."
    assert coach["by_corner"]["T1"]["id"] == point["id"]
