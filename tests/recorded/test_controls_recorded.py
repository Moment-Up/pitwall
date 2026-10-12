"""Setup › Controls on RECORDED real F1 25 captures (tests/fixtures/recorded): the button probe sees the real BUTN
events, names them as spec appendix 8.9 does, labels them ``replay``, and nothing counts as a live press - not in the
button test, not in the validation kit.

RECORDED tier: real game output from the owner's PS5, replayed. The excerpts hold pad-style bits only (no UDP Action
presses); which wheel control set them is not known. This is not live validation of the button test.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pitwall.adapters.f1.enums import button_names, udp_action_bit
from pitwall.config import Settings
from pitwall.controls.probe import ButtonEvent, TestItem
from pitwall.core.runtime import Runtime
from pitwall.validate import evidence as E
from pitwall.validate.kit import ValidationKit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
# the four F1-car excerpts (the F2 excerpts carry other button presses and are tested by the F2 recorded tests)
F1_EXCERPTS = sorted(p for p in FIXTURES.glob("f1_25_2025_ps5_*.pwcap") if "_f2_" not in p.name)
# Every non-zero buttonStatus in the four committed PS5 excerpts (Cross, Circle and the Right Stick direction bits)
STATUSES = {0x1, 0x4, 0x8000, 0x20000, 0x28000, 0x40000, 0x48000, 0x60000}

pytestmark = pytest.mark.recorded


async def _replay(rt: Runtime, capture: Path) -> list[ButtonEvent]:
    seq = rt.controls.probe.seq
    src = rt.start_replay(capture, speed=None)
    while not src.done.is_set():
        await asyncio.sleep(0.05)
    return rt.controls.probe.since(seq)


async def test_the_probe_sees_real_butn_events_as_replay(tmp_path: Path) -> None:
    if len(F1_EXCERPTS) < 4:
        pytest.skip("recorded F1 25 excerpts not present")
    s = Settings(
        data_dir=tmp_path, llm_enabled=False, voice_enabled=False, tailscale_trust_owner=False, access_token="t"
    )
    rt = Runtime(s)
    kit = ValidationKit(s, rt, None, asyncio.get_running_loop())
    run = kit.start_run(["wheel_buttons"], "controls recorded", False)
    run.controls_layout = {"udp_actions": [1]}
    test = rt.controls.tests.start(
        None, [TestItem("ptt_pitwall.hold", "udp_action", "Press UDP Action 1", {"bit": udp_action_bit(1)})]
    )
    try:
        events: list[ButtonEvent] = []
        for cap in F1_EXCERPTS:
            events += await _replay(rt, cap)
        statuses = {e.status for e in events if e.status}
        assert statuses == STATUSES
        assert {e.origin for e in events} == {"replay"}
        names = {n for e in events for n in button_names(e.pressed)}
        assert names <= {"Cross or A", "Circle or B", "Right Stick Left", "Right Stick Up", "Right Stick Down"}
        assert not any(e.status & 0xFFF00000 for e in events)  # no UDP Action in these excerpts
        st = rt.controls.tests.poll()
        assert st is not None and st["items"][0]["state"] == "waiting"  # replayed presses never count
        assert {p["origin"] for p in st["feed"]} == {"replay"}
        await asyncio.sleep(1.2)  # collector ticks copy the presses into the run
        ev = run.evidence.buttons
        assert ev and {b.tier for b in ev} == {"recorded"} and {b.origin for b in ev} == {"replay"}
        auto = E.compute_auto(
            "wheel_buttons", E.views(run), E.AutoContext(0.0, [], {}, controls_layout=run.controls_layout)
        )
        assert auto.verdict == "not_live"
    finally:
        rt.controls.tests.stop(test["id"])
        await kit.finish(run.id, None)
        await kit.close()
        rt.close()
