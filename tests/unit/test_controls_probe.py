"""Setup › Controls button probe and test runner: the bounded lock-free ring, rising edges, origin labelling (replay and
synthetic presses never count), every item state, effects up and down, and presses from the menus (no session)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from pitwall.adapters.f1.enums import udp_action_bit
from pitwall.controls import model as M
from pitwall.controls.probe import ITEM_TIMEOUT_S, ButtonProbe, TestRunner, build_items
from pitwall.core.live import LiveState
from tests.unit.controls_support import CAT, tmpl

U1, U3 = udp_action_bit(1), udp_action_bit(3)


def layout(**kw: Any) -> M.Layout:
    asg = [
        M.Assignment("ptt_pitwall.hold", "ptt_pitwall", "hold", "face_cross", "press", 3, "recommended"),
        M.Assignment("brake_bias.inc", "brake_bias", "inc", "tab_r2", "press"),
        M.Assignment("ers_mode.dec", "ers_mode", "dec", "tab_l2", "press"),
    ]
    return M.Layout(
        "l_00000001", 1, "f1_25", None, "ps5", "w_00000001", "household", "advanced", None, tuple(asg), **kw
    )


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class World:
    """Availability and frame values the runner asks for on each poll."""

    def __init__(self) -> None:
        self.ok = True
        self.not_saved: str | None = None  # available, but shown only (a stream sent from this computer)
        self.values: dict[str, float | None] = {"brake_bias_front_pct": 56.0, "ers_deploy_mode": 1.0}

    def __call__(self) -> tuple[bool, str | None, dict[str, float | None]]:
        return self.ok, self.not_saved if self.ok else "no live F1 25 data", dict(self.values)


def make() -> tuple[ButtonProbe, TestRunner, World, list[Any], list[bool], Clock]:
    origin = {"v": "live"}
    probe = ButtonProbe(origin_of=lambda: origin["v"])
    probe.origin = origin  # type: ignore[attr-defined]
    world, results, pauses, clock = World(), [], [], Clock()
    runner = TestRunner(
        probe,
        world,
        on_result=lambda lid, key, chk: results.append((lid, key, chk)),
        on_pause=pauses.append,
        clock=clock,
    )
    return probe, runner, world, results, pauses, clock


def test_ring_is_bounded_and_keeps_order() -> None:
    probe = ButtonProbe(size=8)
    for i in range(20):
        probe.on_button(i)
    got = probe.since(0)
    assert [e.seq for e in got] == list(range(13, 21)) and probe.seq == 20
    assert [e.status for e in probe.since(18)] == [18, 19]
    e = got[-1]
    assert e.prev == 18 and e.pressed == (19 & ~18) and e.released == (18 & ~19)
    assert probe.feed(3)[-1]["seq"] == 20


def test_rising_edges_and_names() -> None:
    probe = ButtonProbe()
    probe.on_button(U1)
    probe.on_button(U1 | 0x4)
    probe.on_button(0x4)
    a, b, c = probe.since(0)
    assert a.to_dict()["pressed"] == ["UDP Action 1"] and b.to_dict()["pressed"] == ["Circle or B"]
    assert c.to_dict()["released"] == ["UDP Action 1"] and c.to_dict()["pressed"] == []


def test_origin_comes_from_live_state_and_session_manager() -> None:
    """Replays share LiveState: a replayed BUTN must be labelled before the fan-out."""
    from pitwall.core.session import SessionManager

    live = LiveState()
    probe = ButtonProbe(origin_of=lambda: live.button_origin)
    live.subscribe_buttons(probe.on_button)
    live.on_button(U1)
    live.on_button(0, "replay")
    live.on_button(U1, "synthetic")
    assert [e.origin for e in probe.since(0)] == ["live", "replay", "synthetic"]

    class _W:
        def submit(self, fn: Any) -> None:  # pragma: no cover - not reached
            pass

    sm = SessionManager(_W(), live, None, source="replay:x.pwcap")  # type: ignore[arg-type]
    assert sm.button_origin == "replay"
    sm2 = SessionManager(_W(), live, None, source="udp:20777", synthetic=True)  # type: ignore[arg-type]
    assert sm2.button_origin == "synthetic"
    assert SessionManager(_W(), live, None, source="udp:20777").button_origin == "live"  # type: ignore[arg-type]


def test_items_from_a_layout() -> None:
    items = build_items(layout(), tmpl("fanatec_gt_dd_pro_wheel"), CAT.label)
    assert [(i.kind, i.key) for i in items] == [
        ("udp_action", "ptt_pitwall.hold"),
        ("effect", "brake_bias.inc"),
        ("effect", "ers_mode.dec"),
    ]
    assert items[0].expect == {"bit": U3} and "(UDP Action 3) (Cross)" in items[0].prompt
    assert items[1].expect == {"field": "brake_bias_front_pct", "direction": "change"}


def test_detected_effect_seen_and_results() -> None:
    probe, runner, world, results, pauses, _clock = make()
    st = runner.start(layout(), build_items(layout(), None, CAT.label))
    assert st["available"] and st["current"] == 0 and pauses == [True] and st["wheel_ptt_paused"]
    probe.on_button(0x1)  # Cross first: another bit
    st = runner.poll()
    assert st is not None and st["items"][0]["state"] == "other_bits"
    assert "We saw Cross or A, not UDP Action 3" in st["items"][0]["detail"]
    probe.on_button(0)
    probe.on_button(U3)
    st = runner.poll()
    assert st is not None and st["items"][0]["state"] == "detected" and st["current"] == 1
    assert st["items"][0]["saved"] is True and st["saves"] is True
    assert results[0][1] == "ptt_pitwall.hold" and results[0][2].result == "detected"
    assert results[0][2].detail == "UDP Action 3 seen" and results[0][2].origin == "live"
    world.values["brake_bias_front_pct"] = 57.0
    st = runner.poll()
    assert st is not None and st["items"][1]["state"] == "effect_seen" and st["items"][1]["detail"] == "56 → 57 (up)"
    assert st["items"][1]["expect"]["direction"] == "up"
    world.values["ers_deploy_mode"] = 0.0
    st = runner.poll()
    assert (
        st is not None
        and st["items"][2]["state"] == "effect_seen"
        and "medium → none (down)" in st["items"][2]["detail"]
    )
    assert [r[2].result for r in results] == ["detected", "effect_seen", "effect_seen"]
    runner.stop(st["id"])
    assert pauses[-1] is False and runner.poll() is None


def test_replay_presses_show_but_never_count() -> None:
    probe, runner, _world, results, _p, _c = make()
    runner.start(layout(), build_items(layout(), None, CAT.label))
    probe.origin["v"] = "replay"  # type: ignore[attr-defined]
    probe.on_button(U3)
    st = runner.poll()
    assert st is not None and st["items"][0]["state"] == "waiting" and not results
    assert st["feed"][-1]["origin"] == "replay" and st["feed"][-1]["pressed"] == ["UDP Action 3"]


def test_a_stream_from_this_computer_runs_but_saves_nothing() -> None:
    probe, runner, world, results, _p, _c = make()
    world.not_saved = "The data comes from this computer"
    runner.start(layout(), build_items(layout(), None, CAT.label))
    probe.on_button(U3)
    st = runner.poll()
    assert st is not None and st["items"][0]["state"] == "detected" and st["available"] is True
    assert st["saves"] is False and st["why"] == "The data comes from this computer"
    assert st["items"][0]["saved"] is False
    world.values["brake_bias_front_pct"] = 57.0
    st = runner.poll()
    assert st is not None and st["items"][1]["state"] == "effect_seen"
    assert results == []  # shown, never saved


def test_noisy_right_stick_bits_are_not_other_bits() -> None:
    probe, runner, _w, _r, _p, _c = make()
    runner.start(layout(), build_items(layout(), None, CAT.label))
    probe.on_button(0x20000)  # Right Stick Up: changes all the time while driving in the recorded captures
    st = runner.poll()
    assert st is not None and st["items"][0]["state"] == "waiting"


def test_timeout_skip_and_one_test_at_a_time() -> None:
    _probe, runner, world, results, _p, _clock = make()
    st = runner.start(layout(), build_items(layout(), None, CAT.label))
    with pytest.raises(RuntimeError):
        runner.start(layout(), build_items(layout(), None, CAT.label))
    runner.test.items[0].started_unix = time.time() - ITEM_TIMEOUT_S - 1  # type: ignore[union-attr]
    st = runner.poll()
    assert st is not None and st["items"][0]["state"] == "timeout" and results[-1][2].result == "not_seen"
    st = runner.skip(st["id"])
    assert st["items"][1]["state"] == "skipped" and st["current"] == 2
    world.ok = False  # not live: nothing counts, and the item's 60 s wait until F1 25 is live
    runner.test.items[2].started_unix = time.time() - ITEM_TIMEOUT_S - 1  # type: ignore[union-attr]
    n = len(results)
    st = runner.poll()
    assert st is not None and st["items"][2]["state"] == "waiting" and len(results) == n
    assert st["available"] is False and st["why"] and st["saves"] is False
    assert time.time() - runner.test.items[2].started_unix < 5  # type: ignore[union-attr]
    world.ok = True
    st = runner.poll()
    assert st is not None and st["items"][2]["state"] == "waiting" and st["saves"] is True
    with pytest.raises(KeyError):
        runner.skip("t_00000000")


def test_an_abandoned_test_ends_and_wheel_ptt_comes_back() -> None:
    _probe, runner, _w, _r, pauses, clock = make()
    runner.start(layout(), build_items(layout(), None, CAT.label))
    clock.t += 61
    assert runner.poll() is None and pauses[-1] is False and not runner.running


def test_identify_collects_what_it_sees() -> None:
    from pitwall.controls.probe import TestItem

    probe, runner, _w, results, _p, _c = make()
    st = runner.start(None, [TestItem("identify", "identify", "Press a control", {})])
    probe.on_button(0x800)
    probe.on_button(0)
    probe.on_button(U1)
    st = runner.poll()
    assert st is not None and st["items"][0]["seen"] == ["L2 or LT", "UDP Action 1"] and not results


def test_menus_without_a_session_still_reach_the_probe() -> None:
    """F1 sends BUTN from its menus with no session: the session manager hands them to LiveState anyway."""
    from pitwall.core.session import SessionManager
    from pitwall.model.telemetry import EventKind, Game, GameEvent

    live = LiveState()
    probe = ButtonProbe(origin_of=lambda: live.button_origin)
    live.subscribe_buttons(probe.on_button)

    class _W:
        def submit(self, fn: Any) -> None:
            pass

    sm = SessionManager(_W(), live, None, source="udp:20777")  # type: ignore[arg-type]
    sm.handle(GameEvent(t_recv_ns=1, game=Game.F1_25, kind=EventKind.BUTTON, code="BUTN", payload={"buttonStatus": U1}))
    assert sm.session_id is None and [e.status for e in probe.since(0)] == [U1]
