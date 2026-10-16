"""RECORDED tier: the field model (track knowledge layer L0b) on real F1 25 AI cars (v1.26, PS5, UDP format 2025).

The committed fixture is the byte-for-byte Austria race excerpt (four windows: grid, lap 1->2, lap 2->3, flag). The
full race capture (``data/captures/20261010-191501_udp20777.pwcap``) is not committed; the checks that need whole
laps of the field skip without it. Only robust facts are asserted: the game's own data (19 AI cars, all-car
lap distance and analog brake), positions inside the track sheet's hand-verified windows, and the safety property
that matters for coaching - a field heads-up is never later than where this driver braked himself.
"""

from __future__ import annotations

import gc
import os
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.analysis.braking import detect_braking
from pitwall.analysis.distance import to_distance_domain
from pitwall.analysis.field_model import MIN_HEADS_UP_EARLY_M
from pitwall.analysis.laps import LapAssembler, LapFlag, LapTrace
from pitwall.analysis.track import build_track_model
from pitwall.analysis.track_identity import identify
from pitwall.core.track_knowledge import FieldWorker, TrackKnowledge, TrackKnowledgeResolver
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.model.telemetry import CarFrame, FieldSample, LapCompletion, SessionInfo

ROOT = Path(__file__).resolve().parents[2]
EXCERPT = ROOT / "tests" / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
FULL_RACE = ROOT / "data" / "captures" / "20261010-191501_udp20777.pwcap"
LONG_RACE = ROOT / "data" / "captures" / "20261010-221749_udp20777.pwcap"  # Austria, 71 laps, 2 AI pit stops
ONLINE_SUZUKA = ROOT / "data" / "captures" / "20261010-225601_udp20777.pwcap"  # online: humans, stale-UID packets
PLAYER = 19  # the player's slot in this race (Participants: 19 AI cars in slots 0-18)

# Austria track sheet (17_austria.toml, hand-verified against this capture): T1 Niki Lauda window and the driver's
# own lap-2 braking point there ("braking 335-425 m").
T1_WINDOW = (320.0, 545.0)
DRIVER_T1_BRAKE_M = 335.0

pytestmark = [pytest.mark.recorded, pytest.mark.skipif(not EXCERPT.exists(), reason="real PS5 Austria excerpt absent")]


def _packets(path: Path) -> list[CapturedPacket]:
    reader = CaptureReader(path)
    assert not reader.meta.synthetic
    return list(reader)


def _run(packets: list[CapturedPacket]) -> tuple[TrackKnowledge | None, list[FieldSample], list[LapTrace], SessionInfo]:
    adapter = F1Adapter()
    resolver = TrackKnowledgeResolver()
    worker = FieldWorker(resolver.set_field, on_session=resolver.set_session, start=False)
    samples: list[FieldSample] = []
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append)
    info: SessionInfo | None = None
    for p in packets:
        for e in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(e, FieldSample):
                samples.append(e)
                worker.submit(e)
            elif isinstance(e, SessionInfo):
                info = e
                asm.set_track_length(e.track_length_m)
                worker.submit(e)
            elif isinstance(e, CarFrame):
                asm.feed(e)
            elif isinstance(e, LapCompletion):
                asm.feed_completion(e)
        if worker.pending >= 4000:
            worker.process_pending(snapshot=False)
    asm.flush()
    worker.process_pending()
    assert info is not None and worker.dropped == 0 and worker.errors == 0
    return resolver.knowledge, samples, laps, info


@pytest.fixture(scope="module")
def excerpt() -> tuple[TrackKnowledge | None, list[FieldSample], list[LapTrace], SessionInfo]:
    return _run(_packets(EXCERPT))


def test_every_ai_car_is_decoded_and_the_player_is_not(
    excerpt: tuple[TrackKnowledge | None, list[FieldSample], list[LapTrace], SessionInfo],
) -> None:
    _k, samples, _laps, _info = excerpt
    cars = {s.car_index for s in samples}
    assert cars == set(range(19)) and PLAYER not in cars
    assert all(s.ai_controlled is True for s in samples if s.session_time_s > 6.0)  # Participants every 5 s
    assert {s.driver_status for s in samples} == {"on_track"}  # race: every racing car is "on track", none "flying"
    assert all(s.pit_status == 0 and 0.0 <= s.brake <= 1.0 and 0.0 <= s.throttle <= 1.0 for s in samples)
    assert max(s.lap_distance_m for s in samples) > 4000.0  # all-car lap distance spans the lap
    partial = [s.brake for s in samples if 0.05 < s.brake < 0.95]
    assert len(partial) > 100  # AI cars report an analog brake, not on/off


def test_field_samples_are_decimated_to_10_hz(
    excerpt: tuple[TrackKnowledge | None, list[FieldSample], list[LapTrace], SessionInfo],
) -> None:
    per_car: dict[int, list[float]] = defaultdict(list)
    for s in excerpt[1]:
        per_car[s.car_index].append(s.session_time_s)
    for ts in per_car.values():
        dt = np.diff(ts)
        dt = dt[(dt > 0) & (dt < 1.0)]  # excerpt windows leave gaps
        assert dt.min() >= 0.094 and np.median(dt) == pytest.approx(0.1, abs=0.005)


def _decode_times_ns(packets: list[CapturedPacket], field_hz: float) -> tuple[np.ndarray, np.ndarray]:
    """Per-packet decode time (ns) and whether the packet produced FieldSamples (a field tick)."""
    adapter = F1Adapter(field_hz=field_hz)
    times = np.empty(len(packets))
    ticks = np.zeros(len(packets), dtype=bool)
    for i, p in enumerate(packets):
        t0 = time.perf_counter_ns()
        out = adapter.decode(p.data, p.t_recv_ns)
        times[i] = time.perf_counter_ns() - t0
        ticks[i] = any(isinstance(e, FieldSample) for e in out)
    return times, ticks


def test_field_tick_adds_well_under_100_us_on_the_ingest_thread() -> None:
    """Only the CarTelemetry packets that carry a field tick (~1 in 38 packets) do the all-car decode: their own
    added cost is what the ingest thread pays, so it is what is timed (an average over all packets would hide a 10x
    regression). Per packet, the minimum of 3 runs filters OS scheduling noise; measured ~17 us median, ~25 us p99
    on an M4 Max."""
    packets = _packets(EXCERPT)
    gc.disable()
    try:
        runs = [_decode_times_ns(packets, 10.0) for _ in range(3)]
        base = np.min([_decode_times_ns(packets, 0.0)[0] for _ in range(3)], axis=0)
    finally:
        gc.enable()
    ticks = runs[0][1]
    assert all((r[1] == ticks).all() for r in runs)  # the same packets tick on every run (game clock cadence)
    assert ticks.sum() > 100 and ticks.mean() < 0.05
    added_us = (np.min([r[0] for r in runs], axis=0) - base)[ticks] / 1e3
    # Shared CI runners are noisy (a GitHub macOS runner measured 35 us median, 123 us p99; a Windows runner 60.1 us
    # median): both bounds are relaxed on CI only, so the regression check stays strict on a real machine.
    median_limit = 120.0 if os.environ.get("CI") else 60.0
    assert np.percentile(added_us, 50) < median_limit, np.percentile(added_us, [50, 99])
    p99_limit = 300.0 if os.environ.get("CI") else 100.0
    assert np.percentile(added_us, 99) < p99_limit, np.percentile(added_us, [50, 99])
    assert added_us.max() < 1000.0 * (3 if os.environ.get("CI") else 1)  # the budget for anything on the ingest thread


def test_t1_heavy_stop_from_the_excerpt_alone(
    excerpt: tuple[TrackKnowledge | None, list[FieldSample], list[LapTrace], SessionInfo],
) -> None:
    k = excerpt[0]
    assert k is not None and k.layers["L0b"]["available"] and k.synthetic is False
    t1 = [z for z in k.braking_zones if T1_WINDOW[0] <= z["min_speed_m"] <= T1_WINDOW[1]]
    assert len(t1) == 1
    z = t1[0]
    assert z["severity"] == "heavy" and z["support"] >= 3 and z["tier"] == "field_observed"
    assert 250.0 <= z["onset_m"] <= DRIVER_T1_BRAKE_M  # the AI field brakes before this driver did
    heads = [h for h in k.heads_up if h.onset_m == pytest.approx(z["onset_m"], abs=0.05)]
    assert heads and heads[0].target_m <= DRIVER_T1_BRAKE_M - 20.0


# ------------------------------------------------------------------------------------- full race (not committed)
full_race = pytest.mark.skipif(not FULL_RACE.exists(), reason="full Austria race capture not on this machine")


@pytest.fixture(scope="module")
def race() -> tuple[TrackKnowledge | None, list[FieldSample], list[LapTrace], SessionInfo]:
    if not FULL_RACE.exists():
        pytest.skip("full Austria race capture not on this machine")
    return _run(_packets(FULL_RACE))


@full_race
def test_full_race_field_covers_the_lap_with_official_heavy_stops(
    race: tuple[TrackKnowledge | None, list[FieldSample], list[LapTrace], SessionInfo],
) -> None:
    k = race[0]
    assert k is not None
    l0b = k.layers["L0b"]
    assert l0b["cars"] == 19 and l0b["car_laps"] >= 30 and l0b["coverage"] >= 0.99
    assert l0b["counts"]["race_lap_1"] > 0  # race lap 1 is never learned
    by_label = {z["label"]: z for z in k.braking_zones if z["label"]}
    for label in ("T1", "T3", "T4", "T6", "T9"):  # Austria's heavy stops (official numbers via the track sheet)
        assert by_label[label]["severity"] == "heavy" and by_label[label]["support"] >= 10, label
    # every heads-up sits at least 15 m before its field onset, never later
    assert all(h.target_m <= h.onset_m - MIN_HEADS_UP_EARLY_M + 0.05 for h in k.heads_up)


@full_race
def test_full_race_t3_t4_field_onsets_match_the_drivers_learned_corners(
    race: tuple[TrackKnowledge | None, list[FieldSample], list[LapTrace], SessionInfo],
) -> None:
    k, _samples, laps, info = race
    assert k is not None and info.track_length_m is not None
    clean = [lap for lap in laps if not ({LapFlag.INCOMPLETE, LapFlag.STANDING_START} & lap.flags)]
    assert len(clean) >= 2
    learned = build_track_model(
        "f1_25",
        info.track_id or "",
        info.track_name,
        info.track_length_m,
        [to_distance_domain(lap, info.track_length_m) for lap in clean],
    )
    learned, _ = identify(learned, zones=info.track_zones, packet_format=2025)
    zones = {z["label"]: z for z in k.braking_zones if z["label"]}
    for label in ("T3", "T4"):
        corner = next(c for c in learned.corners if c.label == label and c.label_part in (None, 1))
        z = zones[label]
        # the AI's minimum is the driver's corner, and the AI starts braking up to ~80 m before his learned entry
        assert abs(z["min_speed_m"] - corner.apex_m) <= 30.0, label
        assert corner.entry_m - 80.0 <= z["onset_m"] <= corner.entry_m + 15.0, label
        # the heads-up point is never later than where the driver braked on any of his laps
        driver_onsets = [
            e.start_m
            for lap in clean
            for e in detect_braking(lap)
            if e.peak_brake >= 0.3 and abs(e.start_m - z["onset_m"]) <= 100.0
        ]
        assert driver_onsets, label
        heads = next(h for h in k.heads_up if h.label == label)
        assert heads.target_m <= min(driver_onsets), (label, heads.target_m, driver_onsets)


@full_race
def test_full_race_ai_brake_envelope_is_about_4_g_at_300_kph(
    race: tuple[TrackKnowledge | None, list[FieldSample], list[LapTrace], SessionInfo],
) -> None:
    """The AI field's full-brake deceleration (the physics prior's calibration): research measured 4.0 g at
    300 km/h on this race from 60 Hz samples; the 10 Hz field samples must agree, and stay well below the default
    vehicle model's 5.5 g."""
    k = race[0]
    assert k is not None
    env = k.layers["L0b"]["brake_envelope"]
    assert env is not None and env["samples"] >= 60
    assert 3.6 <= env["decel_g_at_300_kph"] <= 4.4


# ------------------------------------------------------------------------ other real captures (not committed)
@pytest.mark.skipif(not LONG_RACE.exists(), reason="long Austria race capture not on this machine")
def test_ai_in_laps_are_dropped_not_learned() -> None:
    """71-lap Austria race, two AI pit stops (cars 7 and 14). F1 25 flags a pitting car "in_lap" only ~240 m before
    the pit lane, yet car 14 was already 11-33 km/h slower through T9 and T10 before that: each in-lap is
    dropped (never finished), the pit lane is seen (pit_status 1 at the 80 km/h line, ~4264 m), and the lap the car
    rejoins on is not learned (F1 25 flags it "out_lap")."""
    adapter = F1Adapter()
    samples: list[FieldSample] = []
    info: SessionInfo | None = None
    for p in CaptureReader(LONG_RACE):
        for e in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(e, FieldSample):
                samples.append(e)
            elif isinstance(e, SessionInfo) and info is None:
                info = e
    assert info is not None and info.track_length_m is not None
    pit = [s for s in samples if s.pit_status != 0]
    assert {s.car_index for s in pit} == {7, 14}
    entries = [s.lap_distance_m for s in pit if s.lap_distance_m > 4000.0]
    assert entries and min(entries) >= 4200.0  # pit_status turns 1 at the pit lane line, after the slow-down
    from pitwall.analysis.field_model import FieldModel

    first: list[FieldSample] = []  # the first session in the capture (it holds two)
    for s in samples:
        if first and s.session_time_s < first[-1].session_time_s - 100.0:
            break
        first.append(s)
    m = FieldModel(game="f1_25", track_id=info.track_id, track_length_m=info.track_length_m, is_race=True)
    m.feed_many(first)
    assert m.counts["in_lap_drops"] == 2 and m.counts["pit"] > 0
    learned = {(r.car, r.lap) for r in m._rows}
    assert not {(7, 62), (14, 65)} & learned  # the in-laps


@pytest.mark.skipif(not ONLINE_SUZUKA.exists(), reason="online Suzuka capture not on this machine")
def test_stale_session_uid_lap_positions_never_reset_the_adapter() -> None:
    """Online Suzuka (PS5): LapPositions (and a few SessionHistory / FinalClassification packets, all ignored by
    pitwall) carry the PREVIOUS session's UID. Before the fix they reset the adapter ~1,300 times, wiping the AI
    flags every ~2 s: all ~105k field samples had ai_controlled=None. Now only the real session change resets."""
    adapter = F1Adapter()
    resets = 0
    reset = adapter.reset

    def counting_reset() -> None:
        nonlocal resets
        resets += 1
        reset()

    adapter.reset = counting_reset  # type: ignore[method-assign]
    stale = 0
    handled_uids: set[int] = set()
    known = 0
    total = 0
    for p in CaptureReader(ONLINE_SUZUKA):
        h = P.HEADER.unpack_from(p.data)
        if h["packetId"] == P.PacketId.LAP_POSITIONS and handled_uids and h["sessionUID"] not in handled_uids:
            stale += 1
        out = adapter.decode(p.data, p.t_recv_ns)
        if h["packetId"] in (P.PacketId.MOTION, P.PacketId.LAP_DATA) and h["sessionUID"]:
            handled_uids.add(h["sessionUID"])
        for e in out:
            if isinstance(e, FieldSample):
                total += 1
                known += e.ai_controlled is not None
    assert stale > 500  # the game really does this
    assert resets == len(handled_uids) - 1 == 1  # qualifying -> race, nothing else
    # the AI flags survive: unknown only until each session's first Participants packet (these opponents are
    # humans, so the rest say False)
    assert total > 50_000 and known / total > 0.9
