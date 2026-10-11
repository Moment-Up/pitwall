"""Field model (track knowledge layer L0b): all-car decode in the F1 adapter, the field model's filters, binning and
braking zones, the field worker's back-pressure and the track-knowledge resolver's precedence.

Synthetic tier: the AI field comes from ``sim/f1_stream.py`` with *known* injected braking points
(``GroundTruth.ai_brake_onsets_m``); results here are evidence for the algorithms, never for game compatibility.
"""

from __future__ import annotations

import json
import math
import struct
import threading
import time
import warnings
from collections import defaultdict
from dataclasses import dataclass, replace

import numpy as np
import orjson
import pytest

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import FIELD_HZ, F1Adapter, subset_struct
from pitwall.analysis.field_model import (
    BIN_M,
    MIN_HEADS_UP_EARLY_M,
    SOURCE,
    TIER,
    FieldFilter,
    FieldModel,
    FieldSnapshot,
)
from pitwall.analysis.track import Corner, TrackModel
from pitwall.coach.cues import CueEngine, CueEvent, CueKind
from pitwall.core.track_knowledge import (
    HEADS_UP_LEAD_S,
    HEADS_UP_PHRASE,
    FieldWorker,
    PhysicsPrior,
    SeverityTag,
    TrackKnowledgeResolver,
    heads_up_cue_plan,
    resolve_track_knowledge,
)
from pitwall.ingest.capture import CapturedPacket
from pitwall.model.telemetry import CarFrame, FieldSample, Game, SessionInfo, SessionType
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.sim.f1_stream import AiCarSpec, F1Scenario, GroundTruth, generate_f1_session
from tests.conftest import DecodedSession

pytestmark = pytest.mark.synthetic

# The AI field brakes early at two corners (known ground truth); everything else is the optimal profile.
FIELD_DEV = DriverProfile(
    deviations={"T1": CornerDeviation(brake_early_m=30.0), "T3": CornerDeviation(brake_early_m=12.0)}
)
SLOW = DriverProfile(deviations={n: CornerDeviation(brake_early_m=80.0) for n in ("T1", "T3", "T4", "T7", "T8")})
GOOD = tuple(range(1, 9))
OUT_LAP, GARAGE, PIT, HUMAN, TRAFFIC = 9, 10, 11, 12, 13
RACE = 15  # Session.sessionType: the traffic filter (deltaToCarInFront) is validated in races only
HEAVY = ("T1", "T3", "T7", "T8")  # design corners with a clean, separate heavy stop on Pitwall Park


@dataclass
class Field:
    packets: list[CapturedPacket]
    truth: GroundTruth
    info: SessionInfo
    samples: list[FieldSample]
    frames: list[CarFrame]


def _field_scenario(packet_format: int = 2025) -> F1Scenario:
    ai = tuple(AiCarSpec(index=k, driver=FIELD_DEV, start_s=0.4 + 1.37 * k) for k in GOOD)
    ai += (
        AiCarSpec(index=OUT_LAP, driver=FIELD_DEV, out_lap=True, start_s=5.0, slow_driver=SLOW),
        AiCarSpec(index=GARAGE, garage_only=True),
        AiCarSpec(index=PIT, driver=FIELD_DEV, pit_laps=frozenset({2}), start_s=3.3, slow_driver=SLOW),
        AiCarSpec(index=HUMAN, driver=SLOW, ai_controlled=False, start_s=7.1),
        AiCarSpec(index=TRAFFIC, driver=SLOW, gap_ahead_ms=200, start_s=9.9),
    )
    # a race: lap 1 is never learned, so 4 laps leave 3 per car (the pit car: lap 2 in the pit lane, lap 3 rejoined)
    return F1Scenario(laps=4, rate_hz=30, ai_cars=ai, packet_format=packet_format, session_type=RACE)


def _decode(
    packets: list[CapturedPacket], adapter: F1Adapter | None = None
) -> tuple[SessionInfo, list[FieldSample], list[CarFrame]]:
    a = adapter or F1Adapter()
    info: SessionInfo | None = None
    samples: list[FieldSample] = []
    frames: list[CarFrame] = []
    for p in packets:
        for e in a.decode(p.data, p.t_recv_ns):
            if isinstance(e, FieldSample):
                samples.append(e)
            elif isinstance(e, SessionInfo):
                info = e
            elif isinstance(e, CarFrame):
                frames.append(e)
    assert info is not None
    return info, samples, frames


@pytest.fixture(scope="module")
def field() -> Field:
    packets, truth = generate_f1_session(_field_scenario())
    info, samples, frames = _decode(packets)
    return Field(packets, truth, info, samples, frames)


@pytest.fixture(scope="module")
def snap(field: Field) -> FieldSnapshot:
    assert field.info.session_type is SessionType.RACE
    m = FieldModel(
        game="f1_25", track_id=field.info.track_id, track_length_m=field.info.track_length_m or 0.0, is_race=True
    )
    m.feed_many(field.samples)
    s = m.snapshot()
    assert s is not None
    return s


def _truth_onsets(truth: GroundTruth) -> dict[str, float]:
    """Injected braking onset per design corner on the good AI cars' flying laps (identical for all of them)."""
    out: dict[str, set[float]] = defaultdict(set)
    for car in GOOD:
        for lap, onsets in truth.ai_brake_onsets_m[car].items():
            assert truth.ai_lap_kinds[car][lap] == "flying"
            for corner, d in onsets.items():
                out[corner].add(round(d, 3))
    assert all(len(v) == 1 for v in out.values()), out
    return {k: next(iter(v)) for k, v in out.items()}


def _sample(**kw: object) -> FieldSample:
    base: dict[str, object] = {
        "game": Game.F1_25,
        "t_recv_ns": 0,
        "session_time_s": 0.0,
        "frame_id": 0,
        "car_index": 1,
        "ai_controlled": True,
        "lap_number": 2,
        "lap_distance_m": 100.0,
        "pos_x_m": 0.0,
        "pos_y_m": 0.0,
        "pos_z_m": 0.0,
        "speed_kph": 250.0,
        "throttle": 1.0,
        "brake": 0.0,
        "steering": 0.0,
        "gear": 7,
        "sector": 0,
        "lap_invalid": False,
        "pit_status": 0,
        "driver_status": "flying_lap",
        "result_status": "active",
    }
    base.update(kw)
    return FieldSample(**base)  # type: ignore[arg-type]


# ================================================================================================ adapter
def test_subset_struct_matches_the_full_decoder() -> None:
    rng = np.random.default_rng(3)
    for layout in P.LAYOUTS.values():
        for sd, keep in (
            (layout.car_motion, ("worldPositionX", "worldPositionZ", "gForceLongitudinal")),
            (P.LAP_DATA, ("lapDistance", "currentLapNum", "pitStatus", "driverStatus", "resultStatus")),
            (layout.car_telemetry, ("speed", "throttle", "brake", "gear", "steer")),
            (layout.participant, ("aiControlled",)),
        ):
            raw = bytes(rng.integers(0, 256, sd.size, dtype=np.uint8))
            full = sd.unpack_from(raw)
            sub = subset_struct(sd, keep).unpack_from(raw)
            want = [full[n] for n, _ in sd.fields if n in keep]
            assert list(sub) == pytest.approx(want, nan_ok=True)
    with pytest.raises(ValueError):
        subset_struct(P.LAP_DATA, ("noSuchField",))
    with pytest.raises(ValueError):
        subset_struct(P.CAR_TELEMETRY, ("tyresPressure",))  # arrays are never kept


def test_adapter_emits_racing_ai_cars_only(field: Field) -> None:
    cars = {s.car_index for s in field.samples}
    assert 0 not in cars  # the player streams CarFrames and is learned from its own laps
    assert GARAGE not in cars  # never left the garage
    assert set(GOOD) | {OUT_LAP, PIT, HUMAN, TRAFFIC} == cars
    assert all(s.driver_status != "garage" and s.result_status == "active" for s in field.samples)
    # pit lane samples go out (the field model must see the visit to drop the lap that led into it)
    in_pit = {(s.car_index, s.lap_number) for s in field.samples if s.pit_status != 0}
    assert in_pit == {(PIT, 2)}
    assert {s.driver_status for s in field.samples if s.car_index == OUT_LAP and s.lap_number == 1} == {"out_lap"}
    by_car = {s.car_index: s.ai_controlled for s in field.samples if s.ai_controlled is not None}
    assert by_car[HUMAN] is False and all(by_car[k] is True for k in GOOD)
    assert {s.gap_ahead_ms for s in field.samples if s.car_index == TRAFFIC} == {200}
    assert all(s.gap_ahead_ms is None for s in field.samples if s.car_index in GOOD)  # 0 on the wire = unknown


def test_field_samples_are_decimated_to_10_hz_per_car(field: Field) -> None:
    per_car: dict[int, list[float]] = defaultdict(list)
    for s in field.samples:
        per_car[s.car_index].append(s.session_time_s)
    for car, ts in per_car.items():
        dt = np.diff(ts)
        dt = dt[dt > 0]
        assert dt.min() >= 1 / FIELD_HZ - 0.006, car  # never faster than 10 Hz (clock jitter tolerance)
        assert np.median(dt) == pytest.approx(0.1, abs=0.01)
    # the player's frames are untouched: one CarFrame per CarTelemetry packet at the stream's own rate
    assert len(field.frames) == sum(1 for p in field.packets if p.data[6] == P.PacketId.CAR_TELEMETRY)


def test_field_samples_follow_the_frames_and_can_be_disabled(field: Field, clean_session: DecodedSession) -> None:
    a = F1Adapter()
    for p in field.packets[:2000]:
        out = a.decode(p.data, p.t_recv_ns)
        kinds = [type(e).__name__ for e in out]
        if "FieldSample" in kinds:
            assert kinds[0] == "CarFrame"  # the player's frame comes first in the same packet
    assert a.field_ticks > 0 and a.field_samples > 0
    _, off, frames_off = _decode(field.packets, F1Adapter(field_hz=0))
    assert off == [] and len(frames_off) == len(field.frames)
    # player-only streams (every existing synthetic scenario) emit no field samples at all
    assert clean_session.adapter.field_samples == 0
    with pytest.raises(ValueError):
        F1Adapter(field_hz=120)


def test_format_2026_field_samples_scale_g_forces() -> None:
    sc = _field_scenario(2026)
    sc.ai_cars = sc.ai_cars[:2]
    sc.laps = 1
    packets, _ = generate_f1_session(sc)
    _, samples, _ = _decode(packets)
    assert samples and {s.car_index for s in samples} == {1, 2}
    assert max(abs(s.g_lon or 0.0) for s in samples) < 8.0  # thousandths of g on the wire, g after decoding
    assert min(s.g_lon or 0.0 for s in samples) < -2.0  # braking


# ================================================================================================ field model
def test_recovers_injected_brake_onsets_within_one_bin(field: Field, snap: FieldSnapshot) -> None:
    truth = _truth_onsets(field.truth)
    assert snap.tier == TIER == "field_observed" and snap.source == SOURCE == "AI field"
    assert snap.cars == len(GOOD) + 2  # the out-lap and pit cars contribute their flying laps
    for corner in HEAVY:
        gt = truth[corner]
        zone = min(snap.braking_zones, key=lambda z: abs(z.onset_m - gt))
        assert abs(zone.onset_m - gt) <= BIN_M, (corner, zone.onset_m, gt)
        assert zone.onset_m <= gt + 0.5  # 10 Hz sampling errs early, never late
        assert zone.heads_up_m <= zone.onset_m - MIN_HEADS_UP_EARLY_M + 1e-9  # heads-up placed earlier still
        assert zone.severity == "heavy" and zone.support >= 3 and zone.cars >= 3
        assert zone.corner is not None and zone.corner.startswith("F")  # provisional names, never T1..Tn


def test_injected_deviation_moves_the_field_onset_by_its_size(field: Field, snap: FieldSnapshot) -> None:
    """T1 is braked 30 m early by the field: the recovered onset sits ~30 m before the optimal profile's."""
    from pitwall.sim.driver import VehicleModel, solve_lap
    from pitwall.sim.f1_stream import brake_onsets

    assert field.truth.track is not None
    optimal = brake_onsets(solve_lap(field.truth.track, VehicleModel()), field.truth.track)
    t1 = min(snap.braking_zones, key=lambda z: abs(z.onset_m - (optimal["T1"] - 30.0)))
    assert optimal["T1"] - t1.onset_m == pytest.approx(30.0, abs=BIN_M)


def test_filters_ignore_pit_out_lap_garage_human_and_traffic(field: Field, snap: FieldSnapshot) -> None:
    c = snap.counts
    assert c["driver_status"] > 0  # the out lap
    assert c["not_ai"] > 0 and c["traffic"] > 0 and c["race_lap_1"] > 0
    assert c["pit"] > 0 and c["out_lap"] > 0  # the pit visit and the lap the car rejoined on
    m = FieldModel(game="f1_25", track_id="t", track_length_m=field.info.track_length_m or 0.0, is_race=True)
    m.feed_many(s for s in field.samples if s.car_index == PIT)
    pit_snap = m.snapshot()
    # lap 1 race start, lap 2 pit lane, lap 3 rejoined: only lap 4 (in progress at the flag) is learned
    assert pit_snap is not None and pit_snap.car_laps == 1 and not m._rows and m._traces[PIT].lap == 4
    bad = [
        s for s in field.samples if s.car_index in (HUMAN, TRAFFIC) or (s.car_index == OUT_LAP and s.lap_number == 1)
    ]
    m = FieldModel(game="f1_25", track_id="t", track_length_m=field.info.track_length_m or 0.0, is_race=True)
    m.feed_many(bad)
    assert m.snapshot() is None  # nothing of theirs is learned
    # ...and it matters: learned without the filters, those laps brake ~80 m early
    loose = FieldModel(
        game="f1_25",
        track_id="t",
        track_length_m=field.info.track_length_m or 0.0,
        filters=FieldFilter(ai_only=False, min_gap_m=None),
    )
    loose.feed_many(s for s in bad if s.driver_status != "out_lap")
    loose_snap = loose.snapshot()
    assert loose_snap is not None
    gt = _truth_onsets(field.truth)["T3"]
    assert min(abs(z.onset_m - (gt - 68.0)) for z in loose_snap.braking_zones) <= 2 * BIN_M


def test_snapshot_arrays_line_and_corners(field: Field, snap: FieldSnapshot) -> None:
    assert snap.coverage == pytest.approx(1.0)
    assert snap.n_bins == math.ceil((field.info.track_length_m or 0.0) / BIN_M)
    track = field.truth.track
    assert track is not None
    # the median line is the synthetic centreline (AI cars drive it exactly): within a metre everywhere
    d = snap.d_m
    x = np.interp(d, track.s, track.x)
    z = np.interp(d, track.s, track.z)
    assert np.nanmax(np.hypot(snap.x_m - x, snap.z_m - z)) < 1.0
    assert int(snap.support.min()) >= 3
    apexes = {name: (a + b) / 2 for name, a, b in track.corners}
    for corner in HEAVY:
        assert min(abs(c.apex_m - apexes[corner]) for c in snap.corners) < 40.0
    d_json = snap.to_dict()
    json.dumps(d_json, allow_nan=False)
    assert len(d_json["line"]) == snap.n_bins and d_json["tier"] == "field_observed"


def test_race_lap_1_flashback_rewind_and_wrap() -> None:
    m = FieldModel(game="f1_25", track_id="t", track_length_m=1000.0, is_race=True)
    assert not m.feed(_sample(lap_number=1))
    assert m.counts["race_lap_1"] == 1
    # lap 2: distance wraps one sample before the lap number moves (seen on real F1 25): one lap, then the next
    t = 0.0
    for d in range(20, 1000, 8):
        t += 0.1
        assert m.feed(_sample(session_time_s=t, lap_distance_m=float(d)))
    t += 0.1
    assert m.feed(_sample(session_time_s=t, lap_number=2, lap_distance_m=4.0))  # wrapped, lap number still 2
    assert m.counts["car_laps"] == 1 and m._traces[1].lap == 3
    t += 0.1
    assert m.feed(_sample(session_time_s=t, lap_number=3, lap_distance_m=12.0))
    assert m._traces[1].lap == 3 and len(m._traces[1].rows) == 2
    # a car going backwards within its lap (reset to track) loses that lap in progress
    t += 0.1
    assert m.feed(_sample(session_time_s=t, lap_number=3, lap_distance_m=80.0))
    t += 0.1
    assert not m.feed(_sample(session_time_s=t, lap_number=3, lap_distance_m=75.0))  # jitter: ignored
    assert m.counts["stationary"] == 1 and len(m._traces[1].rows) == 3
    t += 0.1
    m.feed(_sample(session_time_s=t, lap_number=3, lap_distance_m=40.0))
    assert m.counts["rewind_drops"] == 1 and len(m._traces[1].rows) == 1  # restarted from the new position
    # flashback: the game clock goes back -> every lap in progress is dropped
    m.feed(_sample(session_time_s=t + 0.1, lap_number=3, lap_distance_m=50.0, car_index=2))
    m.feed(_sample(session_time_s=t - 5.0, lap_number=3, lap_distance_m=60.0, car_index=3))
    assert m.counts["flashback_drops"] >= 1 and 2 not in m._traces
    # negative lap distance (before the first line crossing) is never binned
    assert not m.feed(_sample(session_time_s=t, lap_distance_m=-120.0, car_index=4))
    assert m.counts["lap_distance"] == 1


def test_brake_threshold_ignores_pedal_noise() -> None:
    """A resting pedal (real CSL pedals: brake < 0.005 with full throttle) is never a braking onset."""
    m = FieldModel(game="f1_25", track_id="t", track_length_m=1000.0)
    for k, d in enumerate(range(5, 995, 7)):
        for car in range(1, 5):
            dd = float(d) + car
            brake = 0.004 if dd < 600 else 0.9 if dd < 700 else 0.0  # resting-pedal noise until the real stop
            thr = 1.0 if dd < 600 or dd >= 700 else 0.0
            v = 250.0 if dd < 600 else 250.0 - 1.5 * (dd - 600) if dd < 700 else 100.0 + 0.5 * (dd - 700)
            m.feed(
                _sample(
                    car_index=car, session_time_s=k * 0.1, lap_distance_m=dd, brake=brake, throttle=thr, speed_kph=v
                )
            )
    s = m.snapshot()
    assert s is not None and len(s.braking_zones) == 1
    assert 595.0 <= s.braking_zones[0].onset_m <= 610.0


# ================================================================================================ worker
def test_worker_back_pressure_drops_newest_and_never_blocks() -> None:
    w = FieldWorker(start=False, max_queue=100)
    s = _sample()
    t0 = time.perf_counter()
    results = [w.submit(s) for _ in range(10_000)]
    elapsed = time.perf_counter() - t0
    assert results.count(True) == 100 and w.dropped == 9_900
    assert elapsed < 0.1  # ~1 us per submit; an overflowing queue never waits
    w.process_pending()
    assert w.stats()["queued"] == 0


def test_threaded_worker_with_a_stalled_consumer_never_blocks_ingest() -> None:
    gate = threading.Event()
    seen: list[FieldSnapshot | None] = []

    def stalled(snap: FieldSnapshot | None) -> None:
        seen.append(snap)
        gate.wait(5.0)  # a consumer that hangs

    info = SessionInfo(game=Game.F1_25, session_uid="1", track_id="f1:x", track_length_m=1000.0)
    w = FieldWorker(stalled, snapshot_interval_s=0.0, max_queue=500)
    try:
        assert w.submit(info)
        for k in range(30):
            w.submit(_sample(session_time_s=k * 0.1, lap_distance_m=10.0 + 8 * k))
        deadline = time.monotonic() + 5.0
        while not seen and time.monotonic() < deadline:
            time.sleep(0.01)
        assert seen and seen[0] is not None  # the worker is now stuck in the callback
        t0 = time.perf_counter()
        accepted = sum(w.submit(_sample(session_time_s=10.0, lap_distance_m=500.0)) for _ in range(5_000))
        assert time.perf_counter() - t0 < 0.1
        assert accepted <= 500 and w.dropped >= 4_500
    finally:
        gate.set()
        w.close()


def test_worker_builds_a_model_per_session(field: Field) -> None:
    got: list[FieldSnapshot | None] = []
    w = FieldWorker(got.append, start=False)
    for s in field.samples[:50]:
        w.submit(s)  # before any session context: no model, nothing learned
    w.process_pending()
    assert got == [] and w.model is None
    w.submit(field.info)
    for s in field.samples:
        w.submit(s)
    snap = w.process_pending()
    assert snap is not None and got[-1] is snap and snap.track_id == field.info.track_id
    other = replace(field.info, session_uid="another")
    w.submit(other)
    w.process_pending()
    assert got[-1] is None and w.model is not None and w.model.car_laps == 0  # new session: forget the old field
    w.end_session()  # the session ended: nothing more is learned, but the last view stays published
    for s in field.samples[:500]:
        w.submit(s)
    w.process_pending()
    assert w.model is not None and w.model.counts["accepted"] == 0 and got[-1] is None
    w.submit(other)  # the same session again (an idle end, then the game resumes): learning resumes
    w.submit(next(s for s in field.samples if s.car_index in GOOD and s.lap_number == 2))
    w.process_pending(snapshot=False)
    assert w.model.counts["accepted"] == 1


# ================================================================================================ resolver
def _learned_model(snap: FieldSnapshot, track_id: str) -> TrackModel:
    corners = [
        Corner(
            name=f"T{k + 1}",
            apex_m=c.apex_m + 3.0,
            entry_m=c.entry_m,
            exit_m=c.exit_m,
            seg_start_m=c.seg_start_m,
            seg_end_m=c.seg_end_m,
            direction=c.direction,
            ref_min_speed_kph=c.ref_min_speed_kph,
        )
        for k, c in enumerate(snap.corners)
    ]
    return TrackModel(
        game="f1_25", track_id=track_id, track_name=None, length_m=snap.track_length_m, n_laps=3, corners=corners
    )


def test_resolver_precedence_field_then_learned(field: Field, snap: FieldSnapshot) -> None:
    published: list[object] = []
    r = TrackKnowledgeResolver(published.append)
    r.set_session(field.info)
    r.set_field(snap)
    k = r.knowledge
    assert k is not None and k.positions == "field_observed"
    assert k.layers["L0b"]["available"] and not k.layers["L3"]["available"]
    assert k.heads_up and all(h.tier == "field_observed" and h.source == "AI field" for h in k.heads_up)
    assert all(h.target_m <= h.onset_m - MIN_HEADS_UP_EARLY_M + 1e-9 for h in k.heads_up)  # early, always
    assert all(z["superseded_by"] is None for z in k.braking_zones)
    assert {c["tier"] for c in k.corners} == {"field_observed"}
    assert k.line is not None and k.line["tier"] == "field_observed"
    # L3 arrives: it owns positions; field zones stay, marked superseded, keyed by the learned corner
    r.set_learned(_learned_model(snap, field.info.track_id or ""))
    k2 = r.knowledge
    assert k2 is not None and k2.positions == "learned" and k2.version > k.version
    assert {c["tier"] for c in k2.corners} == {"learned"}
    owned = [z for z in k2.braking_zones if z["superseded_by"] == "learned"]
    assert owned and all(z["key"].startswith("T") and z["tier"] == "field_observed" for z in owned)
    # a learned model of another track is never mixed in
    r.set_learned(_learned_model(snap, "f1:999"))
    assert r.knowledge is not None and r.knowledge.positions == "field_observed"
    assert len(published) >= 3
    # a new track drops the old layers
    r.set_session(replace(field.info, track_id="f1:other", session_uid="2"))
    assert r.knowledge is not None and r.knowledge.layers["L0b"]["available"] is False


def test_heads_up_needs_support_of_three_car_laps(field: Field, snap: FieldSnapshot) -> None:
    weak = replace(snap, braking_zones=tuple(replace(z, support=2) for z in snap.braking_zones))
    k = resolve_track_knowledge(field.info, None, weak)
    assert k is not None and k.braking_zones and k.heads_up == ()
    k3 = resolve_track_knowledge(field.info, None, snap, min_support=3)
    assert k3 is not None and len(k3.heads_up) == len([z for z in snap.braking_zones if z.support >= 3])


def test_physics_prior_gives_severity_only_where_nothing_better_exists(field: Field, snap: FieldSnapshot) -> None:
    tid = field.info.track_id or ""
    z0 = snap.braking_zones[0]
    prior = PhysicsPrior(
        game="f1_25",
        track_id=tid,
        source="qss@test",
        tags=(
            SeverityTag(z0.onset_m, z0.min_speed_m + 10.0, "heavy", gated=True),  # covered by the field
            SeverityTag(10.0, 30.0, "heavy", gated=True),  # nothing else knows this window
            SeverityTag(40.0, 60.0, "heavy", gated=False),  # failed the voice gate: never used
        ),
    )
    k = resolve_track_knowledge(field.info, None, snap, prior)
    assert k is not None
    assert [t["window_start_m"] for t in k.severity_tags] == [10.0]
    assert k.severity_tags[0]["tier"] == "physics_predicted" and "onset_m" not in k.severity_tags[0]


def test_track_knowledge_is_strict_json(field: Field, snap: FieldSnapshot) -> None:
    k = resolve_track_knowledge(field.info, _learned_model(snap, field.info.track_id or ""), snap)
    assert k is not None
    d = k.to_dict()
    json.dumps(d, allow_nan=False)
    assert orjson.loads(orjson.dumps(d))["positions"] == "learned"
    assert resolve_track_knowledge(None, None, snap) is None


# ================================================================================================ cue plan
def test_heads_up_cue_plan_is_markers_before_the_field_onset(field: Field, snap: FieldSnapshot) -> None:
    k = resolve_track_knowledge(field.info, None, snap)
    plan = heads_up_cue_plan(k)
    assert plan is not None and plan.cues
    assert heads_up_cue_plan(k, "off") is None and heads_up_cue_plan(None) is None
    heavy = [h for h in k.heads_up if h.severity == "heavy"] if k else []
    assert [c.target_m for c in plan.cues] == sorted(h.target_m for h in heavy)
    for c, app in zip(plan.cues, plan.approaches, strict=True):
        assert c.kind is CueKind.MARKER and c.text == HEADS_UP_PHRASE and c.parts == (HEADS_UP_PHRASE,)
        assert "brake" not in c.parts[0].split()  # a heads-up never says "brake"
        assert c.anticipation_s == HEADS_UP_LEAD_S
        assert app is not None and app.ttg_s[0] == 0.0 and app.ttg_s[200] > app.ttg_s[100] > 0.0


def test_cue_engine_calls_the_heads_up_ahead_of_the_field_onset(field: Field, snap: FieldSnapshot) -> None:
    """The plan runs through the unmodified cue engine: each call lands before the heads-up point."""
    k = resolve_track_knowledge(field.info, None, snap)
    plan = heads_up_cue_plan(k)
    assert plan is not None
    fired: list[CueEvent] = []
    eng = CueEngine("markers")
    eng.set_sink(fired.append)
    eng.set_plan(plan)
    for f in field.frames:
        if f.lap_number == 2:
            eng.on_frame(f, now_mono=f.session_time_s or 0.0)
    assert {e.cue.corner for e in fired} == {c.corner for c in plan.cues}
    for e in fired:
        assert e.aim_m <= e.cue.target_m  # the phrase starts before the (already early) heads-up point
        assert e.cue.target_m - e.d_m > 0.0


# ================================================================================================ L1c calibration
def test_brake_envelope_recovers_the_synthetic_vehicle(snap: FieldSnapshot) -> None:
    """Full-brake AI samples (brake >= 0.95) refit the generator's braking model: decel = 14 + 0.0058 v^2."""
    from pitwall.sim.driver import VehicleModel

    env = snap.brake_envelope
    veh = VehicleModel()
    assert env is not None and env.source == "AI field" and env.samples >= 60
    assert env.decel_g(300.0) == pytest.approx((veh.brake_base + veh.brake_aero * (300 / 3.6) ** 2) / 9.81, rel=0.05)
    assert snap.to_dict(arrays=False)["brake_envelope"]["tier"] == "field_observed"


def test_physics_prior_payload_is_read_through_its_json_contract(field: Field, snap: FieldSnapshot) -> None:
    payload = {
        "game": "f1_25",
        "track_id": field.info.track_id,
        "tier": "physics_prior",
        "source": "qss@abc",
        "windows": [
            {"window_m": [10.0, 30.0], "turn": {"label": "T9", "name": None, "voice_ok": False}},
            {"window_m": "broken"},
        ],
    }
    prior = PhysicsPrior.from_payload(payload)
    assert prior is not None and [t.label for t in prior.tags] == ["T9"] and prior.tier == "physics_prior"
    k = resolve_track_knowledge(field.info, None, snap, prior)
    assert k is not None and k.severity_tags[0]["tier"] == "physics_prior" and k.layers["L1c"]["available"]
    assert PhysicsPrior.from_payload({"windows": []}) is None


def test_partial_coverage_zone_is_flagged_incomplete() -> None:
    """Early in a session the field has driven only part of the lap: a zone at the edge of the data is kept (its
    onset is measured) but marked incomplete, and its severity can only be understated."""
    m = FieldModel(game="f1_25", track_id="t", track_length_m=1000.0)
    for k, d in enumerate(range(5, 640, 7)):
        for car in range(1, 5):
            dd = float(d) + car
            braking = dd >= 600
            m.feed(
                _sample(
                    car_index=car,
                    session_time_s=k * 0.1,
                    lap_distance_m=dd,
                    brake=0.9 if braking else 0.0,
                    throttle=0.0 if braking else 1.0,
                    speed_kph=300.0 - 2.0 * max(0.0, dd - 600),
                )
            )
    s = m.snapshot()
    assert s is not None and s.coverage < 0.7 and s.corners == ()  # too little of the lap for corners
    (z,) = s.braking_zones
    assert not z.complete and 595.0 <= z.onset_m <= 606.0 and z.severity != "heavy"


# ================================================================================================ review fixes
def _drive(
    m: FieldModel, car: int, lap: int, d0: float, d1: float, t: float, *, pit: int = 0, status: str = "on_track"
) -> float:
    """Feed one car from ``d0`` to ``d1`` (8 m steps, 10 Hz) on ``lap``; returns the session time reached."""
    d = d0
    while d < d1:
        t += 0.1
        m.feed(
            _sample(
                car_index=car, session_time_s=t, lap_number=lap, lap_distance_m=d, pit_status=pit, driver_status=status
            )
        )
        d += 8.0
    return t


def test_unknown_ai_flag_is_not_ai() -> None:
    """Before the first Participants packet (every 5 s) nobody is known to be AI: nothing is learned."""
    m = FieldModel(game="f1_25", track_id="t", track_length_m=1000.0)
    assert not m.feed(_sample(ai_controlled=None))
    assert m.counts["not_ai"] == 1 and m.snapshot() is None


def test_traffic_filter_applies_in_races_only() -> None:
    """deltaToCarInFront is validated as an on-track gap in races only (practice / qualifying: unverified)."""
    for is_race, used in ((True, False), (False, True)):
        m = FieldModel(game="f1_25", track_id="t", track_length_m=1000.0, is_race=is_race)
        assert m.feed(_sample(gap_ahead_ms=200)) is used  # 200 ms at 250 km/h: 14 m behind the car in front
        assert m.counts["traffic"] == (0 if used else 1)


def test_pit_visit_drops_the_in_lap_and_the_rejoin_lap() -> None:
    """A pit visit the driver status does not flag: the pit-lane samples alone mark the in-lap. The lap that led
    into the pit (with the slow-down for pit entry) is dropped, never finished, and so is the lap the car rejoins
    on (pit exit merge)."""
    m = FieldModel(game="f1_25", track_id="t", track_length_m=1000.0, is_race=True)
    t = _drive(m, 1, 2, 10.0, 999.0, 0.0)  # a clean lap 2
    t = _drive(m, 1, 3, 4.0, 900.0, t)  # lap 3 up to pit entry ...
    assert m.counts["car_laps"] == 1
    t = _drive(m, 1, 3, 900.0, 1000.0, t, pit=1)  # ... down the pit lane and across the line ...
    t = _drive(m, 1, 4, 0.0, 120.0, t, pit=1)
    assert m.counts["in_lap_drops"] == 1 and 1 not in m._traces and m.counts["car_laps"] == 1
    t = _drive(m, 1, 4, 120.0, 999.0, t)  # ... rejoined: the rest of lap 4 is not learned
    assert m.counts["out_lap"] > 0 and 1 not in m._traces
    t = _drive(m, 1, 5, 4.0, 999.0, t)  # the next lap is clean again
    _drive(m, 1, 6, 4.0, 20.0, t)
    assert m.counts["car_laps"] == 2 and [r.lap for r in m._rows] == [2, 5]


def test_in_lap_flagged_mid_lap_is_dropped_but_a_lap_ending_at_the_line_is_kept() -> None:
    """Real PS5 Austria race: a pitting car turns "in_lap" ~240 m before the pit lane, already slower through the
    corners before. That lap is dropped; a flying lap that ends at the line and turns "in_lap" there is finished."""
    race = FieldModel(game="f1_25", track_id="t", track_length_m=1000.0, is_race=True)
    t = _drive(race, 1, 2, 10.0, 800.0, 0.0)
    t = _drive(race, 1, 2, 800.0, 999.0, t, status="in_lap")
    assert race.counts["in_lap_drops"] == 1 and race.counts["car_laps"] == 0 and 1 not in race._traces
    quali = FieldModel(game="f1_25", track_id="t", track_length_m=1000.0)
    t = _drive(quali, 1, 2, 10.0, 999.0, 0.0, status="flying_lap")
    _drive(quali, 1, 3, 4.0, 400.0, t, status="in_lap")
    assert quali.counts["in_lap_drops"] == 0 and [r.lap for r in quali._rows] == [2]


def test_qualifying_pit_exit_does_not_taint_the_flying_lap() -> None:
    m = FieldModel(game="f1_25", track_id="t", track_length_m=1000.0)
    t = _drive(m, 1, 1, 850.0, 950.0, 0.0, pit=1, status="out_lap")  # out of the garage, down the pit lane
    t = _drive(m, 1, 1, 950.0, 999.0, t, status="out_lap")  # rejoined on the out-lap
    t = _drive(m, 1, 2, 4.0, 999.0, t, status="flying_lap")
    _drive(m, 1, 3, 4.0, 20.0, t, status="flying_lap")
    assert m.counts["out_lap"] == 0 and [r.lap for r in m._rows] == [2]


def test_snapshot_with_unknown_bins_raises_no_runtime_warning() -> None:
    """Medians are taken over bins with data only: no "All-NaN slice" warning, and no warnings.catch_warnings on
    the worker thread (it swaps process-global filters, which is not thread-safe)."""
    m = FieldModel(game="f1_25", track_id="t", track_length_m=1000.0)
    _drive(m, 1, 2, 10.0, 400.0, 0.0)
    _drive(m, 2, 2, 14.0, 400.0, 0.05)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        s = m.snapshot()
    assert s is not None and 0.3 < s.coverage < 0.5
    assert np.isfinite(s.speed_kph[10]) and np.isnan(s.speed_kph[-1]) and np.isnan(s.speed_iqr_kph[-1])


def test_field_line_is_published_only_once_the_field_covers_the_lap(field: Field, snap: FieldSnapshot) -> None:
    length = field.info.track_length_m or 0.0
    m = FieldModel(game="f1_25", track_id=field.info.track_id, track_length_m=length, is_race=True)
    m.feed_many(s for s in field.samples if s.lap_distance_m < 0.5 * length)
    part = m.snapshot()
    assert part is not None and part.coverage < 0.9
    k = resolve_track_knowledge(field.info, None, part)
    assert k is not None and k.line is None  # no chords across track nobody has driven yet
    assert k.braking_zones  # the zones are still published (drawn on whichever line the map shows)
    full = resolve_track_knowledge(field.info, None, snap)
    assert full is not None and full.line is not None and full.line["tier"] == "field_observed"


def test_resolver_reinstalling_the_same_learned_model_is_o1(field: Field, snap: FieldSnapshot) -> None:
    """``SessionManager._split_for_driver`` re-installs the live map on the INGEST thread: that must not resolve,
    publish or wait for a publish in flight on another thread."""
    published: list[object] = []
    r = TrackKnowledgeResolver(published.append)
    r.set_session(field.info)
    model = _learned_model(snap, field.info.track_id or "")
    r.set_learned(model)
    n = len(published)
    done = threading.Event()

    def reinstall() -> None:
        r.set_learned(model)
        done.set()

    with r._publish_lock:  # another thread is publishing
        th = threading.Thread(target=reinstall)
        th.start()
        assert done.wait(2.0)
    th.join()
    assert len(published) == n
    r.set_learned(_learned_model(snap, field.info.track_id or ""))  # a new model (analysis thread) resolves
    assert len(published) == n + 1


def test_heads_up_plan_lists_its_calls_by_priority_for_focus_mode(field: Field, snap: FieldSnapshot) -> None:
    """In the default "focus" mode the cue engine keeps only the first ``FocusLimits.max_corners`` heads-ups of
    ``CuePlan.focus``: the heaviest stops first."""
    k = resolve_track_knowledge(field.info, None, snap)
    plan = heads_up_cue_plan(k)
    assert k is not None and plan is not None
    heads = {h.key: h for h in k.heads_up}
    assert sorted(plan.focus) == sorted(c.corner for c in plan.cues)
    drops = [heads[key].entry_speed_kph - heads[key].min_speed_kph for key in plan.focus]
    assert drops == sorted(drops, reverse=True)
    assert all(c.anticipation_s == HEADS_UP_LEAD_S == 2.5 for c in plan.cues)


def test_replay_worker_blocks_instead_of_dropping_and_drains_on_close() -> None:
    got: list[FieldSnapshot | None] = []
    info = SessionInfo(game=Game.F1_25, session_uid="1", track_id="f1:x", track_length_m=1000.0)
    w = FieldWorker(got.append, snapshot_interval_s=60.0, max_queue=50, block_when_full=True)
    n = 0
    try:
        assert w.submit(info)
        for lap in (2, 3):
            for k, d in enumerate(range(10, 999, 8)):
                assert w.submit(_sample(session_time_s=lap * 200 + k * 0.1, lap_number=lap, lap_distance_m=float(d)))
                n += 1
    finally:
        w.close(drain=True)
    assert w.dropped == 0 and w.processed == n and w.pending == 0
    assert got and got[-1] is not None and got[-1].car_laps == 2  # the final snapshot after the drain


def test_ignored_packet_with_a_stale_session_uid_does_not_reset_the_adapter(field: Field) -> None:
    """Real F1 25 (PS5, online Suzuka) sends LapPositions with the PREVIOUS session's UID. A packet pitwall ignores
    must not wipe the per-session state (AI flags, safety car, the player's lap state); a handled one still does."""
    a = F1Adapter()
    for p in field.packets[:3000]:
        a.decode(p.data, p.t_recv_ns)
    assert a._ai_controlled and a._lap is not None

    def restamp(data: bytes, packet_id: int, size: int | None = None) -> bytes:
        """``data`` as packet ``packet_id`` of another session (sessionUID at byte 7), resized to ``size``."""
        b = bytearray(data if size is None else data[: P.HEADER.size].ljust(size, b"\0"))
        b[6] = packet_id
        struct.pack_into("<Q", b, 7, 0x1234_5678_9ABC)
        return bytes(b)

    layout = P.LAYOUTS[2025]
    ignored = a.stats.ignored
    stale = restamp(field.packets[0].data, P.PacketId.LAP_POSITIONS, layout.sizes[P.PacketId.LAP_POSITIONS])
    assert a.decode(stale, 0) == []
    assert a.stats.ignored == ignored + 1 and a._ai_controlled and a._lap is not None
    motion = next(p.data for p in field.packets if p.data[6] == P.PacketId.MOTION)
    a.decode(restamp(motion, P.PacketId.MOTION), 0)
    assert a._ai_controlled == () and a._lap is None  # a handled packet of another session starts afresh
