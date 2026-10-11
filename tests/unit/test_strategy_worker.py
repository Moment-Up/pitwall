"""The strategy worker (``strategy.worker``): O(1) submit from the ingest thread, drop counting, engines per session,
the live view and notifications, database writes, and no calls from max-speed replays."""

from __future__ import annotations

import time
from typing import Any

from pitwall.core.live import LiveState
from pitwall.strategy.worker import StrategyWorker
from tests.unit.strategy_helpers import car, completion, frame, session, timing


class FakeWriter:
    def __init__(self) -> None:
        self.jobs: list[Any] = []

    def submit(self, fn: Any) -> None:
        self.jobs.append(fn)


class FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> None:
        self.calls.append((sql, args))


def _items(laps: int = 4) -> list[Any]:
    out: list[Any] = [session(total_laps=20)]
    t = 0.0
    for lap in range(1, laps + 1):
        for k in range(10):
            frac = k / 10
            out.append(frame(t, lap, 4318 * frac, fuel=30 - 1.4 * (lap - 1 + frac)))
            out.append(
                timing(
                    t,
                    [
                        car(0, 1, lap=lap, dist=4318 * frac + 50, gap_ms=None),
                        car(1, 2, lap=lap, dist=4318 * frac, gap_ms=1500, player=True),
                        car(2, 3, lap=lap, dist=4318 * frac - 40, gap_ms=600 if lap > 1 else 1500),
                    ],
                )
            )
            t += 8.0
        out.append(completion(lap, 80000, t))
    return out


def test_submit_is_a_bounded_append_and_counts_drops() -> None:
    w = StrategyWorker(start=False, max_queue=3)
    assert all(w.submit("s1", i) for i in range(3))
    assert not w.submit("s1", 4) and w.dropped == 1 and w.pending == 3
    t0 = time.perf_counter()
    for i in range(10_000):
        w.submit("s1", i)
    assert (time.perf_counter() - t0) / 10_000 < 20e-6  # O(1), never blocks


def test_process_pending_publishes_view_calls_records() -> None:
    live = LiveState()
    live.reset_session("s1", "udp:20777", False)
    notes: list[tuple[str, dict[str, Any]]] = []
    live.subscribe(lambda k, p: notes.append((k, p)))
    writer = FakeWriter()
    w = StrategyWorker(live, writer, start=False)  # type: ignore[arg-type]
    for it in _items():
        w.submit("s1", it)
    w.process_pending()
    snap = live.snapshot()
    assert snap["strategy"]["mode"] == "race" and snap["strategy"]["session_id"] == "s1"
    assert w.records == 3 and len(writer.jobs) == 3  # laps 1-3 (lap 4's line window has not run)
    conn = FakeConn()
    writer.jobs[0](conn)
    assert "INSERT INTO strategy_laps" in conn.calls[0][0] and conn.calls[0][1][:2] == ("s1", 1)
    calls = [p for k, p in notes if k == "strategy_call"]
    assert calls and calls[0]["text"] == "Car behind is within a second." and calls[0]["session_id"] == "s1"
    w.end_session("s1")
    w.process_pending()
    assert w.records == 4 and w.engine is not None and w.engine.ended


def test_another_sessions_view_is_dropped_and_a_new_session_starts_a_new_engine() -> None:
    live = LiveState()
    live.reset_session("s2", "udp:20777", False)
    w = StrategyWorker(live, None, start=False)
    for it in _items(1):
        w.submit("s1", it)
    w.process_pending()
    assert live.strategy is None  # the live session is s2
    first = w.engine
    w.submit("s2", session(total_laps=5))
    w.process_pending()
    assert w.engine is not first and first is not None and first.ended
    assert live.strategy is not None and live.strategy["session_id"] == "s2"


def test_no_calls_published_for_max_speed_replays() -> None:
    live = LiveState()
    live.reset_session("s1", "replay:x", False)
    notes: list[str] = []
    live.subscribe(lambda k, p: notes.append(k))
    w = StrategyWorker(live, None, start=False, publish_calls=False)
    for it in _items():
        w.submit("s1", it)
    w.process_pending()
    assert w.calls > 0 and "strategy_call" not in notes


def test_thread_drains_on_close() -> None:
    live = LiveState()
    live.reset_session("s1", "udp:20777", False)
    w = StrategyWorker(live, FakeWriter(), block_when_full=True, max_queue=50)  # type: ignore[arg-type]
    for it in _items():
        assert w.submit("s1", it)  # waits for room instead of dropping
    w.end_session("s1")
    w.close(drain=True)
    assert w.dropped == 0 and w.errors == 0 and w.records == 4
    assert live.strategy is not None and live.strategy["lap"] == 4


def test_reset_session_clears_the_view() -> None:
    live = LiveState()
    live.reset_session("s1", "udp:20777", False)
    live.set_strategy("s1", {"mode": "race"})
    assert live.snapshot()["strategy"] == {"mode": "race"}
    live.reset_session("s2", "udp:20777", False)
    assert live.snapshot()["strategy"] is None
