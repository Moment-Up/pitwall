"""Rig validation kit on RECORDED real-game captures (tests/fixtures/recorded): replays never pass.

Each committed excerpt is replayed into a scratch Runtime with a validation run active. The kit must label every
record ``recorded``, record the game's context (platform, packet format, game version), show what the replay
contains (laps, AC handshake facts) and never let anything pass. The Monza excerpt checks the onset matcher on a
real stored lap trace.

RECORDED tier: real game output, replayed. Not live validation of the kit on the rig.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from pitwall.coach.cues import CueEvent
from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.storage import repo
from pitwall.validate import evidence as E
from pitwall.validate.kit import ValidationKit
from pitwall.validate.model import CueRecord, Run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
AUSTRIA = FIXTURES / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
MONZA = FIXTURES / "f1_25_2025_ps5_monza_race-excerpt.pwcap"
AC = FIXTURES / "ac_ps5_ks_silverstone_probe-excerpt.pwcap"

pytestmark = pytest.mark.recorded


class FakeHub:
    def __init__(self) -> None:
        self.stt = SimpleNamespace(name="scripted")
        self.tts = SimpleNamespace(name="kokoro")
        self.clients: list[Any] = []
        self.observers: list[Any] = []
        self.command_handler = None

    def state(self) -> dict[str, Any]:
        return {"stt_reason": None}

    def add_observer(self, fn: Any) -> None:
        self.observers.append(fn)

    def remove_observer(self, fn: Any) -> None:
        self.observers.remove(fn)


class Replayed(SimpleNamespace):
    rt: Runtime
    kit: ValidationKit
    run: Run


async def replay(tmp_path: Path, capture: Path) -> AsyncIterator[Replayed]:
    if not capture.exists():
        pytest.skip(f"{capture.name} not present")
    s = Settings(
        data_dir=tmp_path, llm_enabled=False, voice_enabled=False, tailscale_trust_owner=False, access_token="t"
    )
    rt = Runtime(s)
    hub = FakeHub()
    loop = asyncio.get_running_loop()
    kit = ValidationKit(s, rt, hub, loop)
    run = kit.start_run(None, capture.name, False)

    def sink(ev: CueEvent) -> None:  # the hub: every fired call delivered (replay thread -> loop)
        payload = {
            "seq": ev.seq,
            "status": "sent",
            "reason": None,
            "msg_id": f"c{ev.seq}",
            "corner": ev.cue.corner,
            "text": ev.cue.text,
            "kind": ev.cue.kind.value,
            "focus": ev.cue.focus,
            "lap": ev.lap,
            "fired_lap": ev.fired_lap,
            "target_m": ev.cue.target_m,
            "aim_m": ev.aim_m,
            "d_m": ev.d_m,
            "speed_kph": ev.v_mps * 3.6,
            "ttg_s": ev.ttg_s,
            "latency_s": ev.latency_s,
            "word_offset_s": ev.word_offset_s,
            "path": "pcm",
            "ref_lap_id": ev.ref_lap_id,
            "engine": None,
            "t_mono": time.monotonic(),
            "t_unix": time.time(),
        }
        for fn in list(hub.observers):
            loop.call_soon_threadsafe(fn, "cue", payload)

    rt.live.cues.set_mode("all")
    rt.live.cues.set_sink(sink)
    try:
        src = rt.start_replay(capture, speed=None)
        while not src.done.is_set():
            await asyncio.sleep(0.1)
        await asyncio.to_thread(rt.worker.join)
        rt.writer.flush()
        await asyncio.sleep(1.2)  # a few sampler ticks and the lap jobs
        assert kit.collector is not None
        await kit.collector.refresh_db()
        kit.recompute()
        yield Replayed(rt=rt, kit=kit, run=run)
    finally:
        if kit.run is not None:
            await kit.finish(kit.run.id, None)
        await kit.close()
        rt.close()


@pytest.fixture
async def austria(tmp_path: Path) -> AsyncIterator[Replayed]:
    async for r in replay(tmp_path, AUSTRIA):
        yield r


@pytest.fixture
async def ac(tmp_path: Path) -> AsyncIterator[Replayed]:
    async for r in replay(tmp_path, AC):
        yield r


@pytest.fixture
async def monza(tmp_path: Path) -> AsyncIterator[Replayed]:
    async for r in replay(tmp_path, MONZA):
        yield r


def _never_passes(run: Run) -> None:
    for it in run.items:
        assert it.auto.verdict in ("no_evidence", "not_live", "unavailable", "inconclusive", "driver_only"), it.id
        assert it.result != "pass", it.id


async def test_f1_austria_excerpt_is_recorded_and_never_passes(austria: Replayed) -> None:
    run = austria.run
    ctx = run.context
    assert ctx["tier"] == "recorded" and ctx["game"] == "f1_25" and ctx["platform"] == "ps5"
    assert ctx["packet_format"] == 2025 and ctx["game_version"] == "1.26" and ctx["track"] == "Austria"
    laps = run.evidence.laps
    assert (
        len(laps) == 3 and all("incomplete" in lap.flags for lap in laps) and {lap.tier for lap in laps} == {"recorded"}
    )
    assert all(c.heads_up and c.tier == "recorded" for c in run.evidence.cues)  # no reference lap: heads-ups only
    decode = E.decode_totals(run.evidence.decode, "f1", lambda t: t == "recorded")
    assert decode is not None and decode["packets"] > 0 and decode["rejected"] == 0
    assert any(e.kind == "telemetry" and "(recorded)" in e.text for e in run.timeline)
    _never_passes(run)


async def test_ac_excerpt_shows_the_handshake_facts(ac: Replayed) -> None:
    run = ac.run
    sessions = [s for s in run.evidence.sessions if s.game == "ac"]
    assert sessions and {s.tier for s in sessions} == {"recorded"}
    item = run.item("ac_ps5")
    assert item is not None
    auto = item.auto
    assert auto.verdict == "not_live" and auto.tier == "recorded"
    assert auto.reasons[:2] == ["This data is from a replay: it is shown but does not count", "No timed lap yet"]
    m = auto.metrics
    assert m["handshake_encoding"] == "utf-16le" and m["handshake_status"] == 4242 and m["rtcarinfo_size"] == 328
    assert m["track_length_quality"] == "estimate" and m["timed_laps"] == 0 and m["platform"] == "ps5"
    assert m["steer_raw_range"] == "-144.9 .. 211.9"
    checks = {c.id: c for c in auto.checks}
    assert checks["handshake"].status == "met" and checks["decode"].status == "met"
    assert checks["rate"].status == "unknown"  # a replay has no live packet rate
    _never_passes(run)


async def test_monza_onset_matcher_on_a_real_stored_trace(monza: Replayed) -> None:
    """A call placed at T1's braking point (found here independently on the raw brake channel) is matched to the
    stored onset within 2 m; calls 30 m early or 60 m late match the same onset; one with nothing within 100 m
    stays unmatched; and the corner name plays no part."""
    run = monza.run
    (lap,) = run.evidence.laps
    with monza.rt.db.read() as c:
        trace = repo.load_lap_trace(c, lap.lap_id)
    assert trace is not None
    d, b = trace.channels["distance_m"], np.nan_to_num(trace.channels["brake"])
    i = int(np.flatnonzero((d > 600.0) & (d < 800.0) & (b >= 0.10))[0])
    t1 = float(d[i - 1] + (0.10 - b[i - 1]) / (b[i] - b[i - 1]) * (d[i] - d[i - 1]))
    onsets = run.evidence.lap_onsets[str(lap.lap_id)]
    assert onsets[0] == pytest.approx(t1, abs=2.0)

    def call(target: float, corner: str) -> CueRecord:
        rec = CueRecord(
            time.time(),
            "recorded",
            lap.session_id,
            1,
            1,
            "m",
            lap.lap_number,
            corner,
            "brake",
            False,
            False,
            target,
            target - 5.0,
            target - 300.0,
            320.0,
            3.0,
            "pcm",
            "sent",
            error_m=0.0,
        )
        E.enrich_cue(rec, onsets)
        return rec

    assert call(t1, "T1").onset_vs_point_m == pytest.approx(0.0, abs=2.0)
    assert call(t1 + 30.0, "T4").onset_vs_point_m == pytest.approx(-30.0, abs=2.0)  # name ignored
    assert call(t1 - 60.0, "T1").onset_vs_point_m == pytest.approx(60.0, abs=2.0)
    assert call(1500.0, "T2").onset_m is None
    _never_passes(run)
