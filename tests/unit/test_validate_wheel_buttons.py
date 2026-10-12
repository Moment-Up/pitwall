"""Validation kit, ``wheel_buttons`` (Setup › Controls): the rule, live-only evidence, the additive run.json keys, and
an old run.json (written before the item existed) still loading."""

from __future__ import annotations

import json
from pathlib import Path

from pitwall.validate import evidence as E
from pitwall.validate import rules as R
from pitwall.validate.model import ButtonRecord, Evidence, run_from_dict

NOW = 1_800_000_000.0
LAYOUT = {"layout_id": "l_0000abcd", "udp_actions": [1, 3], "wheel": "GT DD Pro wheel", "platform": "ps5"}
EXAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "validation" / "example-run.json"


def press(names: list[str], tier: str = "live", origin: str = "live", seq: int = 1) -> ButtonRecord:
    return ButtonRecord(NOW - 10, tier, "s1", 1, seq, 0, names, origin)  # type: ignore[arg-type]


def test_passes_when_every_layout_action_was_seen() -> None:
    got = R.wheel_buttons_verdict([press(["UDP Action 1"]), press(["UDP Action 3", "Cross or A"])], LAYOUT, NOW)
    assert got.verdict == "pass" and got.metrics["seen"] == 2
    assert [c.status for c in got.checks] == ["met", "met"]


def test_some_seen_is_inconclusive_never_fail() -> None:
    got = R.wheel_buttons_verdict([press(["UDP Action 1"])], LAYOUT, NOW)
    assert got.verdict == "inconclusive" and "not yet: UDP Action 3" in got.reasons[0]
    other = R.wheel_buttons_verdict([press(["Circle or B"])], LAYOUT, NOW)
    assert other.verdict == "inconclusive" and "none of your layout's" in other.reasons[0]


def test_no_layout_or_no_presses_is_no_evidence() -> None:
    assert R.wheel_buttons_verdict([], None, NOW).verdict == "no_evidence"
    assert R.wheel_buttons_verdict([], {"udp_actions": []}, NOW).verdict == "no_evidence"
    assert R.wheel_buttons_verdict([], LAYOUT, NOW).verdict == "no_evidence"


def test_only_live_presses_can_pass() -> None:
    """A replayed press (the recorded F1 captures have 78 UDP Action 1 presses) shows, but never passes."""
    ev = Evidence(buttons=[press(["UDP Action 1", "UDP Action 3"], tier="recorded", origin="replay")])
    run = run_from_dict(json.loads(EXAMPLE.read_text(encoding="utf-8"))["run"])
    run.evidence = ev
    run.controls_layout = LAYOUT
    ctx = E.AutoContext(NOW, [], {}, controls_layout=LAYOUT)
    got = E.compute_auto("wheel_buttons", E.views(run), ctx)
    assert got.verdict == "not_live" and got.tier == "recorded"
    run.evidence = Evidence(buttons=[press(["UDP Action 1", "UDP Action 3"])])
    live = E.compute_auto("wheel_buttons", E.views(run), ctx)
    assert live.verdict == "pass" and live.tier == "live"


def test_run_json_round_trip_and_old_files() -> None:
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))["run"]
    old = run_from_dict(raw)  # written before buttons / controls_layout existed
    assert old.evidence.buttons == [] and old.controls_layout is None
    old.evidence.buttons.append(press(["UDP Action 1"]))
    old.controls_layout = LAYOUT
    again = run_from_dict(json.loads(json.dumps(old.to_dict())))
    assert again.controls_layout == LAYOUT and again.evidence.buttons[0].pressed == ["UDP Action 1"]
    assert again.evidence.tier_counts()["live"] >= 1
