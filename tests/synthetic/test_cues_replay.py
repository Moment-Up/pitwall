"""Live braking cues on a replayed SYNTHETIC session, through the full pipeline: packets -> F1 adapter -> SessionManager
-> LiveState -> CueEngine, with LapProcessor (SQLite in a tmp dir) running synchronously so each lap's analysis lands
between frames deterministically, exactly where the background worker would publish it.

Audio is simulated: a cue becomes audible LATENCY_S (+- JITTER_S, seeded) after the frame that fired it, and its key
word KEY_OFFSET_S later (the engine is told LATENCY_S and KEY_OFFSET_S, as the radio hub would after measuring
them). Where the car really was at that moment is read back from the replayed frames and compared with an
independently computed intended point: the car's position ``anticipation_s`` before it reached
``target - MARGIN_M`` (anticipation is 0 for brake calls, 2 s for markers).

Errors are checked two ways: a two-sided tolerance (the timing model is accurate) and a one-sided bound, error <=
``MARGIN_M``: with simulated latency jitter the key word may use the margin but never lands past the reference
braking point (coaching never pushes braking later). A sign error that made every cue a few metres late would
pass a symmetric tolerance and fail the bound.

SYNTHETIC: proves the trigger, timing model and pipeline wiring against known geometry. It is NOT evidence of
behaviour with the real game, whose approach-speed variance and audio latency jitter are larger.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from pitwall.coach.cues import MARGIN_M, CueEngine, CueEvent, CueKind, CuePlan, CueTiming, FrameSample
from pitwall.coach.cues import cue_timing_error_m as measured_error_m
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.runtime import default_adapters
from pitwall.core.session import SessionManager
from pitwall.ingest.router import PacketRouter
from pitwall.model.telemetry import CarFrame
from pitwall.sim.f1_stream import generate_f1_session
from pitwall.sim.scenarios import coaching_demo
from pitwall.storage.db import Database, DbWriter

pytestmark = pytest.mark.synthetic

LATENCY_S = 0.45
JITTER_S = 0.03
KEY_OFFSET_S = 0.55
TOLERANCE_M = 15.0


class _SyncWorker:
    """AnalysisWorker stand-in: process each lap immediately on the ingest thread (deterministic for tests)."""

    def __init__(self, processor: LapProcessor) -> None:
        self.processor = processor

    def submit(self, job: LapJob) -> None:
        self.processor.process(job)


@dataclass
class Replay:
    live: LiveState
    frames: list[CarFrame]
    events: list[CueEvent]
    length_m: float
    lap_observations: dict[int, list[dict[str, Any]]] = field(default_factory=dict)


def _replay(root: Path, mode: str, rate_hz: int) -> Replay:
    sc = coaching_demo()
    sc.rate_hz = rate_hz
    packets, truth = generate_f1_session(sc)
    db = Database(root / f"cues-{mode}-{rate_hz}.sqlite3")
    writer = DbWriter(db)
    live = LiveState()
    processor = LapProcessor(db, writer, live)
    sessions = SessionManager(
        writer,
        live,
        _SyncWorker(processor),  # type: ignore[arg-type]
        source="synthetic-cue-test",
        synthetic=True,
        overrides={"scenario": "coaching-demo"},
    )
    router = PacketRouter(default_adapters(), sessions, live)
    out = Replay(live, [], [], float(truth.track.length_m if truth.track else 0.0))

    def on_lap(kind: str, payload: dict[str, Any]) -> None:
        if kind == "lap":
            out.lap_observations[payload["lap"]["lap_number"]] = payload["observations"]

    def timing_for(plan: CuePlan) -> None:  # what the radio hub pushes once it has measured delivery
        offsets = {c.parts: KEY_OFFSET_S for c in plan.cues if c.key_index > 0}
        live.cues.set_timing(CueTiming(latency_s=LATENCY_S, offsets_s=offsets))

    live.subscribe(on_lap)
    live.cues.set_mode(mode)
    live.cues.set_sink(out.events.append)
    live.cues.set_plan_listener(timing_for)
    record = live.on_frame

    def on_frame(f: CarFrame) -> None:
        out.frames.append(f)
        record(f)

    live.on_frame = on_frame  # type: ignore[method-assign]
    for p in packets:
        router.handle(p)
    router.finish()
    writer.flush()
    writer.close()
    assert live.cues.errors == 0
    return out


@pytest.fixture(scope="module")
def replays(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, int], Replay]:
    """Each (mode, rate) replay runs once per module, on first use."""
    root = tmp_path_factory.mktemp("cue-replays")

    class _Replays(dict[tuple[str, int], Replay]):
        def __missing__(self, key: tuple[str, int]) -> Replay:
            rp = self[key] = _replay(root, *key)
            return rp

    return _Replays()


def _path_after(
    frames: list[CarFrame], i: int, lap: int, length: float
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """(time, position) from frame ``i`` on, in the cued lap's distance (negative before its line), until a rewind."""
    ts: list[float] = []
    xs: list[float] = []
    for f in frames[i : i + 900]:
        t, d, n = f.session_time_s, f.lap_distance_m, f.lap_number
        if t is None or d is None or n is None:
            continue
        if ts and t <= ts[-1]:
            break  # flashback: this cue's future was rewound
        if n == lap:
            x = d
        elif n == lap - 1:
            x = d - length
        else:
            break
        ts.append(t)
        xs.append(x)
    return np.array(ts), np.array(xs)


@dataclass
class Heard:
    event: CueEvent
    error_m: float  # key word position - intended position (+ = late)
    onset_t: float
    onset_x: float
    onset_v: float


def _heard(rp: Replay, seed: int = 7) -> tuple[list[Heard], int]:
    """Simulated delivery of every fired cue; returns the measurable ones and how many were not measurable."""
    rng = random.Random(seed)
    index = {(f.session_time_s, f.lap_distance_m, f.lap_number): k for k, f in enumerate(rp.frames)}
    heard: list[Heard] = []
    unmeasurable = 0
    for ev in rp.events:
        i = index[(ev.session_time_s, ev.d_m, ev.fired_lap)]
        ts, xs = _path_after(rp.frames, i, ev.lap, rp.length_m)
        assert ev.session_time_s is not None
        onset_t = ev.session_time_s + LATENCY_S + rng.uniform(-JITTER_S, JITTER_S)
        key_t = onset_t + ev.word_offset_s
        reach_x = ev.cue.target_m - MARGIN_M
        if len(ts) < 2 or not (xs[0] <= reach_x <= xs[-1]) or not (ts[0] <= key_t <= ts[-1]):
            unmeasurable += 1
            continue
        reach_t = float(np.interp(reach_x, xs, ts))
        intended_t = reach_t - ev.cue.anticipation_s
        intended_x = float(np.interp(intended_t, ts, xs))
        key_x = float(np.interp(key_t, ts, xs))
        onset_x = float(np.interp(onset_t, ts, xs))
        onset_v = float(np.interp(onset_t, ts[1:], np.diff(xs) / np.diff(ts)))
        heard.append(Heard(ev, key_x - intended_x, onset_t, onset_x, onset_v))
    return heard, unmeasurable


def test_focus_cue_lands_on_the_reference_braking_point_at_60hz(replays: dict[tuple[str, int], Replay]) -> None:
    rp = replays["focus", 60]
    # lap 3 is the injected "brakes 15 m early" lap: its brake_early observation names the focus corner
    focus = {o["corner"] for o in rp.lap_observations[3] if o["kind"] == "brake_early"}
    assert len(focus) == 1
    fired = [(ev.lap, ev.cue.corner) for ev in rp.events]
    # the plan exists from lap 3's analysis on, so laps 4-6 get the call; lap 7's evidence comes after the last lap
    assert fired == [(4, c) for c in focus] + [(5, c) for c in focus] + [(6, c) for c in focus]
    assert all(ev.cue.parts == (ev.cue.corner, "brake") and ev.cue.focus for ev in rp.events)
    heard, unmeasurable = _heard(rp)
    assert unmeasurable == 0
    errors = [h.error_m for h in heard]
    assert max(map(abs, errors)) <= TOLERANCE_M, errors
    assert max(errors) <= MARGIN_M, errors  # never past the reference point
    # in this clean synthetic replay the model is far tighter than the tolerance
    assert max(map(abs, errors)) <= 4.0, errors


@pytest.mark.parametrize(("mode", "hz"), [("all", 60), ("markers", 60), ("all", 20), ("markers", 20)])
def test_every_braking_zone_cue_lands_within_tolerance(
    replays: dict[tuple[str, int], Replay], mode: str, hz: int
) -> None:
    rp = replays[mode, hz]
    plan = rp.live.cues.plan
    assert len(plan.cues) >= 3 and all(
        c.kind is (CueKind.MARKER if mode == "markers" else CueKind.BRAKE) for c in plan.cues
    )
    per_lap: dict[tuple[int, str], int] = {}
    for ev in rp.events:
        per_lap[(ev.lap, ev.cue.corner)] = per_lap.get((ev.lap, ev.cue.corner), 0) + 1
    assert set(per_lap.values()) == {1}  # one call per corner per lap, flashback lap 6 included
    assert {lap for lap, _ in per_lap} == {3, 4, 5, 6, 7}  # plan from lap 2's analysis on
    heard, unmeasurable = _heard(rp)
    assert unmeasurable <= 1  # at most a cue whose word fell after lap 6's flashback
    errors = [round(h.error_m, 2) for h in heard]
    assert len(errors) >= 4 * len(plan.cues)
    assert max(map(abs, errors)) <= TOLERANCE_M, errors
    assert max(errors) <= MARGIN_M, errors  # never past the reference point (markers: never inside their lead)
    assert rp.live.cues.missed == 0  # on-time approaches at 20-60 Hz: the late-drop rule costs no call


def test_planned_brake_points_are_braking_onsets_on_the_reference(replays: dict[tuple[str, int], Replay]) -> None:
    """No call at a re-application inside a braking zone: the reference was off the brakes just before each point."""
    rp = replays["all", 60]
    trace = rp.live._ref_trace
    assert trace is not None
    brake = trace.ch["brake"]
    for c in rp.live.cues.plan.cues:
        before = brake[(trace.d >= c.target_m - 40.0) & (trace.d < c.target_m - 3.0)]
        after = brake[(trace.d > c.target_m + 3.0) & (trace.d <= c.target_m + 40.0)]
        assert np.nanmax(before) < 0.1 <= np.nanmax(after), c.corner


def test_measured_error_matches_the_simulated_truth(replays: dict[tuple[str, int], Replay]) -> None:
    """What the hub logs from a playback 'started' report agrees with where the word really landed."""
    rp = replays["all", 60]
    heard, _ = _heard(rp)
    for h in heard:
        sample = FrameSample(h.onset_t, h.event.lap, h.onset_x, h.onset_v)
        m = measured_error_m(h.event, sample, h.onset_t, rp.length_m)
        assert m is not None and abs(m - h.error_m) <= 1.5, (h.event.cue.corner, m, h.error_m)


def test_distance_jump_skips_the_call_instead_of_calling_late(replays: dict[tuple[str, int], Replay]) -> None:
    """Real F1 lap distance can jump ~150 m in one frame (reset to track): the affected cue must be dropped."""
    rp = replays["all", 60]
    plan = rp.live.cues.plan
    first = plan.cues[0]
    fire_d = next(ev.d_m for ev in rp.events if ev.lap == 4 and ev.cue.corner == first.corner)
    frames: list[CarFrame] = []
    for f in rp.frames:
        if f.lap_number == 4 and f.lap_distance_m is not None and f.lap_distance_m >= fire_d - 60.0:
            f = CarFrame(**{**{k: getattr(f, k) for k in f.__slots__}, "lap_distance_m": f.lap_distance_m + 150.0})
        frames.append(f)
    engine = CueEngine("all")
    engine.set_plan(plan)
    engine.set_timing(CueTiming(latency_s=LATENCY_S))
    fired: list[CueEvent] = []
    engine.set_sink(fired.append)
    for f in frames:
        if f.lap_number is not None and 3 <= f.lap_number <= 5:
            engine.on_frame(f, f.session_time_s)
    calls = [(ev.lap, ev.cue.corner) for ev in fired]
    assert (4, first.corner) not in calls
    assert (3, first.corner) in calls and (5, first.corner) in calls
    assert engine.missed >= 1 and engine.errors == 0
