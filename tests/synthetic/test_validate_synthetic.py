"""Rig validation kit on SYNTHETIC sessions: the evidence pipeline end to end, with known answers.

F1: the coaching demo replays through the real pipeline (adapter -> SessionManager -> LiveState -> cue engine), the
lap processor running synchronously (as in test_cues_replay.py). A fake radio hub turns each fired call into the
hub's observer events (delivered at a seeded latency) and plays proactive messages at chosen points: one on a
straight and one just after a braking point on several laps. The kit then reads the stored laps: the calls on the
laps with injected early braking match onsets about 15 m and 20 m before the point, the messages played inside a
braking zone are the only overlaps, and nothing passes: every record is tier ``synthetic``.

GT7 and AC: synthetic captures replayed by a real Runtime feed the game rules (lap counts, variant, tier).

SYNTHETIC: proves the kit's wiring and arithmetic, never game compatibility.
"""

from __future__ import annotations

import asyncio
import itertools
import random
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pitwall.analysis.braking import detect_braking
from pitwall.coach.cues import CueEvent, CuePlan, CueTiming
from pitwall.config import Settings
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.runtime import Runtime, default_adapters
from pitwall.core.session import SessionManager
from pitwall.ingest.router import PacketRouter
from pitwall.model.telemetry import CarFrame
from pitwall.sim.ac_stream import write_ac_capture
from pitwall.sim.f1_stream import generate_f1_session
from pitwall.sim.gt7_stream import write_gt7_capture
from pitwall.sim.scenarios import coaching_demo
from pitwall.storage.db import Database, DbWriter
from pitwall.validate.kit import ValidationKit
from tests.conftest import decode_session

pytestmark = pytest.mark.synthetic

LATENCY_S = 0.45
KEY_OFFSET_S = 0.3
JITTER_S = 0.03
PLAY_S = 1.5


class _SyncWorker:
    def __init__(self, processor: LapProcessor) -> None:
        self.processor = processor

    def submit(self, job: LapJob) -> None:
        self.processor.process(job)


class _Drivers:
    active_id = 1

    def list_drivers(self) -> list[Any]:
        return [object()]

    def subscribe(self, fn: Any) -> None:
        pass

    def unsubscribe(self, fn: Any) -> None:
        pass


class FakeHub:
    """Enough of RadioHub for the kit: engines' names, an observer list, no clients (no prompts)."""

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

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        payload = {**payload, "t_mono": time.monotonic(), "t_unix": time.time()}
        for fn in list(self.observers):
            fn(kind, payload)


async def _drain(kit: ValidationKit, lap_ids: int, timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        await asyncio.sleep(0.05)
        run = kit.run
        assert run is not None
        if len(run.evidence.lap_onsets) >= lap_ids and kit.collector is not None and kit.collector._lap_q.empty():
            await asyncio.sleep(0.2)
            return
    raise AssertionError("lap jobs did not finish")


async def test_f1_cues_and_speak_windows_known_answers(tmp_path: Path) -> None:
    sc = coaching_demo()
    packets, _truth = generate_f1_session(sc)
    laps, _frames, _info, _adapter = decode_session(packets)
    zones = [e for e in detect_braking(laps[0]) if e.peak_brake >= 0.5]
    assert len(zones) >= 4
    gaps = [(b.start_m - a.end_m, a.end_m, b.start_m) for a, b in itertools.pairwise(zones)]
    _, calm_from, calm_to = max(gaps)
    calm_at = calm_from + 0.15 * (calm_to - calm_from)  # early on the longest straight: 1.5 s fits easily
    braking_at = zones[1].start_m + 5.0  # just after a braking point: the brake is already on

    db = Database(tmp_path / "v.sqlite3")
    writer = DbWriter(db)
    live = LiveState()
    processor = LapProcessor(db, writer, live)
    sessions = SessionManager(
        writer,
        live,
        _SyncWorker(processor),
        source="synthetic-validate-test",
        synthetic=True,  # type: ignore[arg-type]
        overrides={"scenario": "coaching-demo"},
    )
    router = PacketRouter(default_adapters(), sessions, live)
    rt = SimpleNamespace(
        live=live,
        drivers=_Drivers(),
        db=db,
        input_status=lambda: [],
        settings=SimpleNamespace(data_dir=tmp_path, llm_enabled=False),
    )
    hub = FakeHub()
    kit = ValidationKit(rt.settings, rt, hub, asyncio.get_running_loop())
    run = kit.start_run(["cues_timing", "radio_speak_windows", "ipad_one_message", "radio_kokoro"], "synthetic", False)
    rng = random.Random(7)

    def timing_for(plan: CuePlan) -> None:  # what the hub pushes once it has measured delivery
        live.cues.set_timing(CueTiming(latency_s=LATENCY_S, offsets_s={c.parts: KEY_OFFSET_S for c in plan.cues}))

    def sink(ev: CueEvent) -> None:  # the hub delivering every call at a seeded latency
        mid = f"c{ev.seq}"
        hub.emit(
            "cue",
            {
                "seq": ev.seq,
                "status": "sent",
                "reason": None,
                "msg_id": mid,
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
                "engine": "kokoro",
            },
        )
        err = ev.v_mps * rng.uniform(-JITTER_S, JITTER_S)  # the latency was predicted exactly, plus jitter
        hub.emit(
            "cue_timing",
            {
                "seq": ev.seq,
                "error_m": err,
                "latency_ms": round(LATENCY_S * 1000),
                "output_ms": 50,
                "output_reported": False,
                "predicted_latency_ms": 450,
            },
        )

    live.cues.set_mode("off")
    live.cues.set_sink(sink)
    live.cues.set_plan_listener(timing_for)
    record = live.on_frame
    started: dict[str, float] = {}
    planned = {
        (lap, at, kind): f"p{lap}{kind}" for lap in (3, 4, 5) for at, kind in ((calm_at, "calm"), (braking_at, "brake"))
    }

    def brief(f: CarFrame) -> dict[str, Any]:
        return {
            "lap": f.lap_number,
            "lap_distance_m": f.lap_distance_m,
            "session_time_s": f.session_time_s,
            "speed_kph": f.speed_kph,
            "brake": f.brake,
            "steering": f.steering,
        }

    def on_frame(f: CarFrame) -> None:
        record(f)
        lap, d, t = f.lap_number, f.lap_distance_m, f.session_time_s
        if lap is None or d is None or t is None:
            return
        if lap == 3 and d > 50.0 and live.cues.mode == "off":
            live.cues.set_mode("all")
        for (plap, at, kind), mid in planned.items():
            if lap == plap and d >= at and mid not in started:
                started[mid] = t
                hub.emit(
                    "proactive",
                    {
                        "msg_id": mid,
                        "kind": "coaching",
                        "priority": 50,
                        "text": f"{kind} test",
                        "lap_number": lap - 1,
                        "meta": {"lap_id": None, "observation_id": None},
                        "needs_speak_window": True,
                        "held_s": 0.2,
                        "state": {
                            "on_track": True,
                            "speed_kph": f.speed_kph,
                            "brake": f.brake,
                            "steering": f.steering,
                            "lap_number": lap,
                            "lap_distance_m": d,
                            "time_to_next_braking_s": None,
                        },
                    },
                )
                hub.emit(
                    "synth",
                    {
                        "msg_id": mid,
                        "kind": "coaching",
                        "engine": "kokoro",
                        "neural": True,
                        "synth_ms": 180.0,
                        "fallback_reason": None,
                    },
                )
                hub.emit(
                    "deliver",
                    {
                        "msg_id": mid,
                        "kind": "coaching",
                        "n_bytes": 48000,
                        "audio_clients": 1,
                        "device_clients": 0,
                        "cancelled_id": None,
                    },
                )
                hub.emit(
                    "playback",
                    {
                        "msg_id": mid,
                        "state": "started",
                        "client": "ipad",
                        "device_tts": False,
                        "output_s": None,
                        "frame": brief(f),
                        "latency": None,
                    },
                )
        for mid, t0 in list(started.items()):
            if t0 >= 0 and t - t0 >= PLAY_S:
                started[mid] = -1.0
                hub.emit(
                    "playback",
                    {
                        "msg_id": mid,
                        "state": "ended",
                        "client": "ipad",
                        "device_tts": False,
                        "output_s": None,
                        "frame": brief(f),
                        "latency": None,
                    },
                )

    live.on_frame = on_frame  # type: ignore[method-assign]
    for i, p in enumerate(packets):
        router.handle(p)
        if i % 400 == 0:
            await asyncio.sleep(0)  # the kit's lap notifications and lap jobs run on this loop
    router.finish()
    writer.flush()
    await _drain(kit, len(run.evidence.laps) or 7)
    kit.recompute()
    ev = run.evidence
    assert ev.cues and all(c.tier == "synthetic" for c in ev.cues)
    assert {lap.cue_mode for lap in ev.laps if lap.lap_number <= 2} == {"off"}
    by_lap: dict[int, list[float]] = {}
    for c in ev.cues:
        if c.onset_vs_point_m is not None:
            by_lap.setdefault(c.lap, []).append(c.onset_vs_point_m)
    assert min(by_lap[3]) == pytest.approx(-15.0, abs=3.0)  # lap 3: brakes 15 m early into design-T3
    assert min(by_lap[7]) == pytest.approx(-20.0, abs=3.0)  # lap 7: brakes 20 m early into design-T1
    clean = [x for lap in (4, 5) for x in by_lap.get(lap, [])]
    assert clean and max(map(abs, clean)) <= 5.0  # elsewhere on the reference point (lap 4 T7 apex loss: -3.4 m)
    assert all(c.cls == "on_time" for c in ev.cues if c.error_m is not None)
    pro = {p.id: p for p in ev.proactive}
    assert {pid for pid, p in pro.items() if p.cls == "overlap"} == {f"p{lap}brake" for lap in (3, 4, 5)}
    assert all(pro[f"p{lap}calm"].cls == "clean" for lap in (3, 4, 5))
    assert all(p.tier == "synthetic" and p.engine == "kokoro" for p in pro.values())
    items = {it.id: it for it in run.items}
    assert items["cues_timing"].auto.verdict == "not_live" and items["cues_timing"].auto.tier == "synthetic"
    assert int(items["cues_timing"].auto.metrics["measured"] or 0) >= 8
    assert items["cues_timing"].auto.metrics["baseline_median_onset_vs_point_m"] is not None
    assert items["radio_speak_windows"].auto.verdict == "not_live"
    assert items["radio_speak_windows"].auto.metrics["overlap"] == 3
    assert all(it.result != "pass" for it in run.items)
    done = await kit.finish(run.id, None)
    assert all(it.auto.verdict in ("not_live", "no_evidence", "driver_only") for it in done.items)
    await kit.close()
    writer.close()


@pytest.mark.parametrize("game", ["gt7", "ac"])
async def test_gt7_and_ac_synthetic_streams_feed_the_game_rules(tmp_path: Path, game: str) -> None:
    s = Settings(
        data_dir=tmp_path, llm_enabled=False, voice_enabled=False, tailscale_trust_owner=False, access_token="t"
    )
    cap = tmp_path / f"{game}.pwcap"
    truth = write_gt7_capture(cap) if game == "gt7" else write_ac_capture(cap)
    rt = Runtime(s)
    kit = ValidationKit(s, rt, None, asyncio.get_running_loop())
    try:
        item = "gt7_ps5" if game == "gt7" else "ac_ps5"
        run = kit.start_run([item], None, False)
        src = rt.start_replay(cap, speed=None)
        await asyncio.to_thread(src.done.wait, 60)
        await asyncio.to_thread(rt.worker.join)
        rt.writer.flush()
        assert kit.collector is not None
        await kit.collector.refresh_db()
        sessions = [x for x in run.evidence.sessions if x.game == game]
        assert sessions and all(x.tier == "synthetic" for x in sessions)
        auto = run.item(item).auto  # type: ignore[union-attr]
        assert auto.verdict == "not_live" and auto.tier == "synthetic"
        timed = sum(1 for x in sessions for lap in x.laps if lap.get("lap_time_ms") is not None)
        assert int(auto.metrics["timed_laps"] or 0) == timed >= len(truth.lap_times_ms) - 1
        if game == "gt7":
            assert auto.metrics["variants"] == "C"
        else:
            assert auto.metrics["handshake_encoding"] == "utf-16le"
        await kit.finish(run.id, None)
    finally:
        await kit.close()
        rt.close()
