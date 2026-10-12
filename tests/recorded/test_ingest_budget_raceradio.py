"""The ingest thread's budget with the race radio merged: the same run as ``test_ingest_budget_combined`` (adapter
decode + ``SessionManager.handle`` + the O(1) hooks, over the committed PS5 F1 25 Austria race excerpt) with the race
radio's sink attached as well (one deque append per item) and the adapter's race radio mappings (the player's FIA flag,
the CarDamage and penalty objects rebuilt only on change, the Participants table compared every 5 s). Same limits."""

from __future__ import annotations

import gc
import os
import time
from pathlib import Path
from typing import cast

import numpy as np
import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.core.lap_processor import AnalysisWorker
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.ingest.router import PacketRouter
from pitwall.model.telemetry import CarFrame, Participants, RaceTiming
from pitwall.storage.db import DbWriter
from tests.recorded.test_ingest_budget_combined import EXCERPT, _Appends

pytestmark = pytest.mark.recorded
CI = bool(os.environ.get("CI"))


def _packets() -> list[CapturedPacket]:
    reader = CaptureReader(Path(EXCERPT))
    assert not reader.meta.synthetic
    return list(reader)


def _run(packets: list[CapturedPacket]) -> tuple[np.ndarray, _Appends]:
    live = LiveState()
    race = _Appends()
    sessions = SessionManager(
        cast(DbWriter, _Appends()),
        live,
        cast(AnalysisWorker, _Appends()),
        source="udp:20777",
        field=_Appends(),
        strategy=_Appends(),
        race=race,
    )
    router = PacketRouter([F1Adapter()], sessions, live)
    times = np.empty(len(packets))
    for i, p in enumerate(packets):
        t0 = time.perf_counter_ns()
        router.handle(p)
        times[i] = time.perf_counter_ns() - t0
    return times, race


def test_with_the_race_radio_ingest_stays_inside_the_budget() -> None:
    packets = _packets()
    gc.disable()
    try:
        runs = [_run(packets) for _ in range(3)]
    finally:
        gc.enable()
    race = runs[0][1]
    kinds = {type(e).__name__ for (_sid, e) in race.items}
    assert {"CarFrame", "RaceTiming", "SessionInfo", "GameEvent", "LapCompletion", "Participants"} <= kinds
    frames = [e for (_sid, e) in race.items if isinstance(e, CarFrame)]
    assert all(f.fia_flag in ("none", "green", "blue", "yellow", None) for f in frames)
    assert sum(isinstance(e, Participants) for (_sid, e) in race.items) <= 3  # on change only (and at a new session)
    assert sum(isinstance(e, RaceTiming) for (_sid, e) in race.items) > 30
    us = np.min([r[0] for r in runs], axis=0) / 1e3
    median, p99, worst = np.percentile(us, 50), np.percentile(us, 99), us.max()
    numbers = f"median {median:.1f} us, p99 {p99:.1f} us, max {worst:.0f} us over {len(us)} packets"
    print(numbers)
    scale = 3.0 if CI else 1.0
    assert median < 60.0, numbers
    assert p99 < 150.0 * scale, numbers
    assert worst < 1000.0 * scale, numbers
