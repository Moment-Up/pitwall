"""Live braking cues and corner reminders on a replayed SYNTHETIC session, through the full pipeline: packets -> F1
adapter -> SessionManager -> LiveState (coach selection and its habit tracker) -> CueEngine, with LapProcessor (SQLite
in a tmp dir) running synchronously so each lap's analysis lands between frames deterministically, exactly where the
background worker would publish it.

Audio is simulated: a cue becomes audible LATENCY_S (+- JITTER_S, seeded) after the frame that fired it, and its key
word KEY_OFFSET_S later (the engine is told LATENCY_S and KEY_OFFSET_S, as the radio hub would after measuring
them). Where the car really was at that moment is read back from the replayed frames and compared with an
independently computed intended point: the car's position ``anticipation_s`` before it reached
``target - MARGIN_M`` (anticipation is 0 for brake calls, 2 s for markers, a reminder's length plus 1 s).

Two sessions: the coaching demo (one-off mistakes: focus mode calls none of them) and ``habit_session`` (the same two
mistakes on every lap from lap 3: a braking habit and a minimum-speed habit, worked on at Detailed intensity), where a
corner reminder's phrase - spoken by a simulated voice slower than the planner's estimate, whose length the "hub"
reports - must END at least ``REMINDER_END_MARGIN_S`` before the braking point.

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

from pitwall.coach.cues import (
    MARGIN_M,
    NO_HABITS,
    REMINDER_END_MARGIN_S,
    CueEngine,
    CueEvent,
    CueKind,
    CuePlan,
    CueTiming,
    FrameSample,
    estimate_phrase_s,
)
from pitwall.coach.cues import cue_timing_error_m as measured_error_m
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.runtime import default_adapters
from pitwall.core.session import SessionManager
from pitwall.ingest.router import PacketRouter
from pitwall.model.telemetry import CarFrame
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.sim.f1_stream import F1Scenario, generate_f1_session
from pitwall.sim.scenarios import coaching_demo
from pitwall.storage.db import Database, DbWriter

pytestmark = pytest.mark.synthetic

LATENCY_S = 0.45
JITTER_S = 0.03
KEY_OFFSET_S = 0.55
TOLERANCE_M = 15.0
SLOWER_VOICE_S = 0.4  # the simulated voice says a reminder this much slower than the planner's word estimate


def habit_session() -> F1Scenario:
    """Nine laps at 'Pitwall Park' (design corner names): laps 1-2 clean (the reference), laps 3-9 brake 15 m early
    into design-T3 and take design-T7 12 km/h slow at the apex: two habits from lap 4's analysis on."""
    every = DriverProfile(
        deviations={"T3": CornerDeviation(brake_early_m=15), "T7": CornerDeviation(apex_speed_loss_kph=12)}
    )
    return F1Scenario(laps=9, driver_by_lap={lap: every for lap in range(3, 10)})


def spoken_s(parts: tuple[str, ...]) -> float:
    """How long the simulated voice takes over a reminder (longer than the estimate: the hub's measured length)."""
    return estimate_phrase_s(parts) + SLOWER_VOICE_S


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


def _replay(root: Path, mode: str, rate_hz: int, session: str = "demo") -> Replay:
    sc = habit_session() if session == "habits" else coaching_demo()
    sc.rate_hz = rate_hz
    packets, truth = generate_f1_session(sc)
    db = Database(root / f"cues-{session}-{mode}-{rate_hz}.sqlite3")
    writer = DbWriter(db)
    live = LiveState()
    processor = LapProcessor(db, writer, live)
    sessions = SessionManager(
        writer,
        live,
        _SyncWorker(processor),  # type: ignore[arg-type]
        source="synthetic-cue-test",
        synthetic=True,
        overrides={"scenario": "coaching-demo" if session == "demo" else "habit-session"},
    )
    if session == "habits":
        live.coach.set_radio_intensity("detailed")  # two habits worked on: a braking call and a corner reminder
    router = PacketRouter(default_adapters(), sessions, live)
    out = Replay(live, [], [], float(truth.track.length_m if truth.track else 0.0))

    def on_lap(kind: str, payload: dict[str, Any]) -> None:
        if kind == "lap":
            out.lap_observations[payload["lap"]["lap_number"]] = payload["observations"]

    def timing_for(plan: CuePlan) -> None:  # what the radio hub pushes once it has measured delivery
        offsets = {c.parts: KEY_OFFSET_S for c in plan.cues if c.key_index > 0}
        durations = {c.parts: spoken_s(c.parts) for c in plan.cues if c.kind is CueKind.REMINDER}
        live.cues.set_timing(CueTiming(latency_s=LATENCY_S, offsets_s=offsets, durations_s=durations))

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
    """Each (mode, rate) replay of the coaching demo runs once per module, on first use."""
    root = tmp_path_factory.mktemp("cue-replays")

    class _Replays(dict[tuple[str, int], Replay]):
        def __missing__(self, key: tuple[str, int]) -> Replay:
            rp = self[key] = _replay(root, *key)
            return rp

    return _Replays()


@pytest.fixture(scope="module")
def habit_replays(tmp_path_factory: pytest.TempPathFactory) -> dict[int, Replay]:
    """``habit_session`` in focus mode, once per frame rate."""
    root = tmp_path_factory.mktemp("cue-habit-replays")

    class _Replays(dict[int, Replay]):
        def __missing__(self, hz: int) -> Replay:
            rp = self[hz] = _replay(root, "focus", hz, "habits")
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
    reach_target_t: float | None = None  # when the car reached the reference braking point itself


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
        intended_t = reach_t - ev.lead_anticipation_s  # what the trigger used (a reminder: its spoken length + 1 s)
        intended_x = float(np.interp(intended_t, ts, xs))
        key_x = float(np.interp(key_t, ts, xs))
        onset_x = float(np.interp(onset_t, ts, xs))
        onset_v = float(np.interp(onset_t, ts[1:], np.diff(xs) / np.diff(ts)))
        target_t = float(np.interp(ev.cue.target_m, xs, ts)) if xs[0] <= ev.cue.target_m <= xs[-1] else None
        heard.append(Heard(ev, key_x - intended_x, onset_t, onset_x, onset_v, target_t))
    return heard, unmeasurable


def test_focus_mode_calls_habits_not_one_offs(replays: dict[tuple[str, int], Replay]) -> None:
    """Focus mode calls the session's habits (coach.habits): the coaching demo's mistakes happen on one lap each, so
    they stay on the screen and no braking call follows them. (Before habits, lap 3's single early braking was called
    on laps 4-6: one lap of evidence made a focus corner.)"""
    rp = replays["focus", 60]
    assert [o["corner"] for o in rp.lap_observations[3] if o["kind"] == "brake_early"]  # the one-off is measured
    assert rp.events == []
    assert rp.live.cues.plan.cues == () and rp.live.cues.plan.reason == NO_HABITS


@pytest.mark.parametrize("hz", [60, 20])
def test_braking_habit_call_lands_on_the_reference_braking_point(habit_replays: dict[int, Replay], hz: int) -> None:
    rp = habit_replays[hz]
    # the braking habit (design-T3, 15 m early) is measured from lap 3 and a habit from lap 4's analysis on
    early = {o["corner"] for o in rp.lap_observations[4] if o["kind"] == "brake_early"}
    assert len(early) == 1
    brakes = [ev for ev in rp.events if ev.cue.kind is CueKind.BRAKE]
    assert [(ev.lap, ev.cue.corner) for ev in brakes] == [(lap, c) for lap in range(5, 10) for c in early]
    assert all(ev.cue.parts == (ev.cue.corner, "brake") and ev.cue.focus for ev in brakes)
    heard, unmeasurable = _heard(Replay(rp.live, rp.frames, brakes, rp.length_m))
    assert unmeasurable == 0
    errors = [h.error_m for h in heard]
    assert max(map(abs, errors)) <= TOLERANCE_M, errors
    assert max(errors) <= MARGIN_M, errors  # never past the reference point


@pytest.mark.parametrize("hz", [60, 20])
def test_corner_reminder_ends_before_the_braking_point(habit_replays: dict[int, Replay], hz: int) -> None:
    """The minimum-speed habit (design-T7, 12 km/h) is worked on: its corner gets "<corner>, apex speed, 12 down"
    every lap, said by a voice slower than the planner's estimate (the hub reports its length). The phrase must end
    at least REMINDER_END_MARGIN_S before the car reaches the reference braking point, at 300+ km/h."""
    rp = habit_replays[hz]
    low = {o["corner"] for o in rp.lap_observations[4] if o["kind"] == "low_min_speed"}
    assert len(low) == 1
    (corner,) = low
    reminders = [ev for ev in rp.events if ev.cue.kind is CueKind.REMINDER]
    assert [(ev.lap, ev.cue.corner) for ev in reminders] == [(lap, corner) for lap in range(5, 10)]
    # the median of the laps it was measured on, rounded to 1 km/h: the injected 12 km/h reads 11-12 at 20-60 Hz
    phrases = {ev.cue.parts[1] for ev in reminders}
    assert phrases <= {"apex speed, 11 down", "apex speed, 12 down"}, phrases
    for ev in reminders:
        assert ev.cue.parts == (corner, ev.cue.parts[1]) and ev.cue.text == f"{corner}: {ev.cue.parts[1]}"
        assert ev.cue.key_index == 0 and ev.cue.focus
    assert corner not in {ev.cue.corner for ev in rp.events if ev.cue.kind is CueKind.BRAKE}  # one call per corner
    assert all(
        ev.lead_anticipation_s == pytest.approx(spoken_s(ev.cue.parts) + REMINDER_END_MARGIN_S) for ev in reminders
    )
    heard, unmeasurable = _heard(Replay(rp.live, rp.frames, reminders, rp.length_m))
    assert unmeasurable == 0 and len(heard) == 5
    for h in heard:
        assert h.onset_v * 3.6 > 280.0  # a fast approach: about 90 m of track a second
        assert h.reach_target_t is not None
        ends_t = h.onset_t + spoken_s(h.event.cue.parts)
        spare = h.reach_target_t - ends_t
        assert spare >= REMINDER_END_MARGIN_S, (h.event.lap, spare)  # ends at least 1 s before the braking point
        assert spare <= REMINDER_END_MARGIN_S + 0.2, (h.event.lap, spare)  # and not needlessly early
    assert rp.live.cues.missed == 0 and rp.live.cues.errors == 0


def test_reminder_after_a_distance_jump_is_dropped_not_late(habit_replays: dict[int, Replay]) -> None:
    """A distance jump just before a reminder's start (real F1 data jumps ~150 m: reset to track) leaves too little
    time to end the phrase a second before the braking point: that lap's reminder is dropped, never said late."""
    rp = habit_replays[60]
    plan = rp.live.cues.plan
    (spec,) = [c for c in plan.cues if c.kind is CueKind.REMINDER]
    fire_d = next(ev.d_m for ev in rp.events if ev.lap == 6 and ev.cue.kind is CueKind.REMINDER)
    frames: list[CarFrame] = []
    for f in rp.frames:
        if f.lap_number == 6 and f.lap_distance_m is not None and fire_d - 60.0 <= f.lap_distance_m < spec.target_m:
            f = CarFrame(**{**{k: getattr(f, k) for k in f.__slots__}, "lap_distance_m": f.lap_distance_m + 150.0})
        frames.append(f)
    engine = CueEngine("focus")
    engine.set_plan(plan)
    engine.set_timing(CueTiming(latency_s=LATENCY_S, durations_s={spec.parts: spoken_s(spec.parts)}))
    fired: list[CueEvent] = []
    engine.set_sink(fired.append)
    for f in frames:
        if f.lap_number is not None and 5 <= f.lap_number <= 7:
            engine.on_frame(f, f.session_time_s)
    calls = [(ev.lap, ev.cue.corner) for ev in fired if ev.cue.kind is CueKind.REMINDER]
    assert calls == [(5, spec.corner), (7, spec.corner)]
    assert engine.missed >= 1 and engine.errors == 0


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
