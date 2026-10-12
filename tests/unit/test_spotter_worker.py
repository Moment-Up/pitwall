"""SpotterWorker: O(1) submit from the ingest thread, its own thread, backlog skipping, publishing, sink errors."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.core.live import LiveState
from pitwall.model.telemetry import FieldMotion, GameEvent, SessionInfo
from pitwall.sim.spotter_scenarios import by_name, generate
from pitwall.spotter.model import SpotterCall
from pitwall.spotter.settings import SpotterSettings
from pitwall.spotter.stats import Ring, percentile
from pitwall.spotter.worker import SpotterWorker

ON = SpotterSettings(enabled=True)


def _items(name: str = "a_pass_left") -> list[FieldMotion | SessionInfo | GameEvent]:
    a = F1Adapter(field_motion=True)
    out: list[Any] = []
    for p in generate(by_name(name)):
        out += [e for e in a.decode(p.data, p.t_recv_ns) if isinstance(e, FieldMotion | SessionInfo | GameEvent)]
    return out


def test_calls_go_to_the_sink_in_order_and_live_is_published_without_a_version_bump() -> None:
    live = LiveState()
    calls: list[SpotterCall] = []
    w = SpotterWorker(live, ON, sink=calls.append, start=False)
    for it in _items():
        w.submit(it)
    w.process_pending()
    assert [c.kind for c in calls] == ["car_left", "clear_left"]
    assert all(c.origin is w for c in calls) and calls[0].seq < calls[1].seq
    assert live.version == 0  # frames bump it; the spotter never does
    assert live.spotter is not None and live.spotter["active"] and live.spotter["v"] == 1
    assert w.counters()["calls"] == {"car_left": 1, "clear_left": 1}
    assert w.status()["motion_hz"] == pytest.approx(60.0, abs=0.5)
    assert [r["kind"] for r in w.recent] == ["clear_left", "car_left"]


def test_reset_clears_the_live_block_and_publish_calls_off_keeps_the_radio_out() -> None:
    live = LiveState()
    calls: list[SpotterCall] = []
    w = SpotterWorker(live, ON, sink=calls.append, publish_calls=False, start=False)
    for it in _items():
        w.submit(it)
    w.reset(None)
    w.process_pending()
    assert calls == [] and w.counters()["calls"] == {"car_left": 1, "clear_left": 1}
    assert live.spotter is None and w.session_id is None


def test_sink_errors_are_counted_and_never_stop_the_worker() -> None:
    def boom(_c: SpotterCall) -> None:
        raise RuntimeError("radio gone")

    w = SpotterWorker(LiveState(), ON, sink=boom, start=False)
    for it in _items():
        w.submit(it)
    w.process_pending()
    assert w.errors == 2 and w.counters()["calls"]["clear_left"] == 1


def test_settings_are_an_attribute_swap_picked_up_at_the_next_item() -> None:
    live = LiveState()
    w = SpotterWorker(live, SpotterSettings(), start=False)
    items = _items()
    for it in items[:200]:
        w.submit(it)
    w.process_pending()
    assert w.engine.reason == "disabled" and live.spotter is not None and live.spotter["enabled"] is False
    w.apply_settings(ON)
    w.set_ear_latency(0.2)
    for it in items[200:]:
        w.submit(it)
    w.process_pending()
    assert w.engine.settings is ON and w.engine.ear_latency_s == 0.2


def test_submit_stays_cheap_with_a_stalled_sink_and_a_backlog_is_skipped() -> None:
    gate = threading.Event()
    entered = threading.Event()

    def stalled(_c: SpotterCall) -> None:
        entered.set()
        gate.wait(10)

    live = LiveState()
    w = SpotterWorker(live, ON, sink=stalled)
    try:
        items = _items()
        it = iter(items)
        for x in it:  # until the first call: the worker is now stuck in the sink
            w.submit(x)
            if entered.wait(0.002):
                break
        assert entered.is_set()
        rest = [x for x in it if isinstance(x, FieldMotion)]
        times = []
        for x in rest[:100]:
            t0 = time.perf_counter_ns()
            w.submit(x)
            times.append(time.perf_counter_ns() - t0)
        assert sorted(times)[len(times) // 2] < 50_000  # median under 50 us, while the worker is stalled
        assert max(times) < 5_000_000
        gate.set()
        deadline = time.monotonic() + 5
        while w.pending and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)
        assert w.skipped >= 60  # only the newest Motion of the backlog was decoded
    finally:
        gate.set()
        w.close()
    assert w._thread is None


def test_stale_after_250_ms_without_motion() -> None:
    live = LiveState()
    w = SpotterWorker(live, ON)
    try:
        for it in _items()[:400]:
            w.submit(it)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (live.spotter and live.spotter["reason"] == "stale"):
            time.sleep(0.05)
        assert live.spotter is not None and live.spotter["reason"] == "stale" and not live.spotter["active"]
    finally:
        w.close()


def test_rings_and_percentiles() -> None:
    assert percentile([], 50) is None
    assert percentile([3.0, 1.0, 2.0, float("nan")], 50) == 2.0
    assert percentile(range(1, 101), 95) == 95
    r = Ring(size=3)
    for v in (1.0, 2.0, 3.0, 40.0):
        r.add(v)
    assert r.summary() == {"p50": 3.0, "p95": 40.0, "max": 40.0, "n": 3}
    assert Ring().summary() == {"p50": None, "p95": None, "max": None, "n": 0}
