"""The ingest thread's budget with every lane merged (v0.2.0 plan 6.2): adapter decode + ``SessionManager.handle`` +
the O(1) hooks (live state, lap assembly, the field model's and race strategy's queue appends, pace vs AI's
history store), per packet, over the committed PS5 F1 25 Austria race excerpt.

The run goes through the real ``PacketRouter`` exactly as the UDP thread does; only what happens off the ingest thread
is replaced by appends (the database writer, the analysis worker, the field and strategy workers' consumers), so the
timing is the ingest thread's own. Absolute limits, because a pytest run cannot load an older build to compare: the
median, p99 and worst packet of the minimum of 3 runs (OS scheduling noise filtered as in
``test_field_model_real.py``), garbage collector off. Measured on an M4 Max at the v0.2.0 strategy merge
(2026-10-11, 13 208 packets): median 2.8 us, p99 35 us, max 0.54 ms. The limits are the plan's.

Spotter (lane spotter, 2026-10-12): the F1 adapter runs with ``field_motion=True`` and the session manager hands every
``FieldMotion`` to the real ``SpotterWorker.submit`` (one ``SimpleQueue.put``; the worker is not started, so nothing
off-thread competes for the GIL). Measured on the M4 Max (2026-10-12, minimum of 5 runs): median 2.83 us, p99 33.4 us,
max 0.46 ms, against 2.71 / 33.3 / 0.45 with the spotter off in the same session - one object and one put per Motion
packet (2224 of the 13 208 packets).
"""

from __future__ import annotations

import gc
import os
import time
from collections import deque
from pathlib import Path
from typing import Any, cast

import numpy as np

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.core.lap_processor import AnalysisWorker
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.ingest.router import PacketRouter
from pitwall.model.telemetry import CarLapHistory, FieldMotion, FieldSample, RaceTiming
from pitwall.spotter.worker import SpotterWorker
from pitwall.storage.db import DbWriter

ROOT = Path(__file__).resolve().parents[2]
EXCERPT = ROOT / "tests" / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
CI = bool(os.environ.get("CI"))


class _Appends:
    """Stands in for everything off the ingest thread: each call is one deque append, as the real queues are."""

    def __init__(self) -> None:
        self.items: deque[Any] = deque()
        self.ended = 0

    def submit(self, *args: Any) -> bool:
        self.items.append(args)
        return True

    def submit_ai_pace(self, job: Any) -> None:
        self.items.append((job,))

    def end_session(self, *_args: Any) -> None:
        self.ended += 1


def _packets() -> list[CapturedPacket]:
    reader = CaptureReader(EXCERPT)
    assert not reader.meta.synthetic
    return list(reader)


def _run(packets: list[CapturedPacket]) -> tuple[np.ndarray, dict[str, int]]:
    live = LiveState()
    writer, worker, field, strategy = _Appends(), _Appends(), _Appends(), _Appends()
    spotter = SpotterWorker(live, start=False)  # spotter: the real submit (a queue put); nothing drains it here
    sessions = SessionManager(
        cast(DbWriter, writer),
        live,
        cast(AnalysisWorker, worker),
        source="udp:20777",
        field=field,
        strategy=strategy,
        spotter=spotter,
    )
    router = PacketRouter([F1Adapter(field_motion=True)], sessions, live)
    times = np.empty(len(packets))
    for i, p in enumerate(packets):
        t0 = time.perf_counter_ns()
        router.handle(p)
        times[i] = time.perf_counter_ns() - t0
    kinds = {
        "field": sum(1 for (e,) in field.items if isinstance(e, FieldSample)),
        "timing": sum(1 for (_sid, e) in strategy.items if isinstance(e, RaceTiming)),
        "laps": sum(1 for (e,) in worker.items if type(e).__name__ == "LapJob"),
        "motion": sum(isinstance(e, FieldMotion) for e in _drain(spotter)),
    }
    return times, kinds


def _drain(spotter: SpotterWorker) -> list[object]:
    out: list[object] = []
    while spotter.pending:
        out.append(spotter._q.get_nowait())
    return out


def test_every_lane_together_stays_inside_the_ingest_budget() -> None:
    packets = _packets()
    gc.disable()
    try:
        runs = [_run(packets) for _ in range(3)]
    finally:
        gc.enable()
    kinds = runs[0][1]
    assert kinds["field"] > 1000 and kinds["timing"] > 30  # the field model and race strategy were both fed
    assert kinds["laps"] >= 1  # the player's laps reached the analysis worker
    assert kinds["motion"] > 1000  # spotter: every Motion packet reached its queue
    us = np.min([r[0] for r in runs], axis=0) / 1e3
    median, p99, worst = np.percentile(us, 50), np.percentile(us, 99), us.max()
    numbers = f"median {median:.1f} us, p99 {p99:.1f} us, max {worst:.0f} us over {len(us)} packets"
    scale = 3.0 if CI else 1.0  # shared CI runners are noisy (as test_field_model_real.py)
    assert median < 60.0, numbers
    assert p99 < 150.0 * scale, numbers
    assert worst < 1000.0 * scale, numbers  # the budget for anything on the ingest thread


def test_the_lanes_outputs_reach_their_queues() -> None:
    """The merged adapter feeds every lane from one stream: pace vs AI's lap lists stay in the session manager (never a
    queue), race timing and tyre sets go to the strategy queue, field samples to the field queue."""
    packets = _packets()
    live = LiveState()
    field, strategy = _Appends(), _Appends()
    sessions = SessionManager(
        cast(DbWriter, _Appends()),
        live,
        cast(AnalysisWorker, _Appends()),
        source="udp:20777",
        field=field,
        strategy=strategy,
    )
    adapter = F1Adapter()
    router = PacketRouter([adapter], sessions, live)
    for p in packets:
        router.handle(p)
    solo = F1Adapter()  # the same stream decoded alone: pace vs AI's lap lists come out of it too
    histories = sum(isinstance(e, CarLapHistory) for p in packets for e in solo.decode(p.data, p.t_recv_ns))
    assert histories > 0
    assert sessions.sessions_started >= 1
    assert {type(e).__name__ for (_sid, e) in strategy.items} >= {
        "RaceTiming",
        "TyreSetsInfo",
        "CarFrame",
        "LapCompletion",
    }
    assert all(isinstance(e, FieldSample) or type(e).__name__ == "SessionInfo" for (e,) in field.items)
    assert adapter.timing_ticks > 30 and adapter.stats.rejected == 0
