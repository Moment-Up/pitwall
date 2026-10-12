"""The spotter on REAL PS5 F1 25 captures (committed, scrubbed excerpts; format 2025). Recorded tier: the game's own
packets, but no driver listening - the ground truth is geometric, from the same positions as the spotter, so it
checks the data, timing and state machine, not what the driver saw (docs/research/f1-spotter-data.md).

* The data assumptions: ``worldRightDir`` is the driver's right (it agrees with the steering sign), every car's
  position is new in every packet, and LapData arrives in the same frame as Motion.
* The engine on the Austria race excerpt (3 overlaps of 0.3 s or more) and the Monza race start (lights out to +30 s,
  the busiest part of a race): every overlap called, no wrong clear, no false onset, the decision within 70 ms of
  game time.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import subset_struct
from pitwall.ingest.capture import CaptureReader
from pitwall.spotter.score import collect, score_trace

pytestmark = pytest.mark.recorded

ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "recorded"
AUSTRIA = ROOT / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
MONZA = ROOT / "f1_25_2025_ps5_monza_race-excerpt.pwcap"
MELBOURNE = ROOT / "f1_25_2025_ps5_melbourne_race-start-excerpt.pwcap"
MONZA_START = ROOT / "f1_25_2025_ps5_monza_race-start-spotter-excerpt.pwcap"

_MOT = (
    "worldVelocityX",
    "worldVelocityY",
    "worldVelocityZ",
    "worldForwardDirX",
    "worldForwardDirY",
    "worldForwardDirZ",
    "worldRightDirX",
    "worldRightDirY",
    "worldRightDirZ",
)


def _need(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path.name} not present")


def _right_vs_steering(path: Path) -> tuple[int, float, float]:
    """How often the player's turn agrees with ``worldRightDir`` and the steering sign (CarTelemetry steer: +1 = full
    right, EA spec), above 80 km/h with more than 30% lock: the velocity turning towards ``right`` over 100 ms
    ((v(t) - v(t - 100 ms)) . right), and the heading turning towards it (forward vector). Returns (samples, velocity
    agreement, heading agreement)."""
    lay = P.LAYOUTS[2025]
    mot = subset_struct(lay.car_motion, _MOT)
    tel = subset_struct(lay.car_telemetry, ("speed", "steer"))
    frames: dict[int, tuple[float, ...]] = {}
    vel: list[bool] = []
    head: list[bool] = []
    for pkt in CaptureReader(path):
        d = pkt.data
        if len(d) < P.HEADER.size or int.from_bytes(d[0:2], "little") != 2025:
            continue
        pid = d[6]
        h = P.HEADER.unpack_from(d)
        p = h["playerCarIndex"]
        if pid == P.PacketId.MOTION and len(d) == lay.sizes[P.PacketId.MOTION]:
            frames[h["frameIdentifier"]] = mot.unpack_from(d, P.HEADER.size + p * lay.car_motion.size)
        elif pid == P.PacketId.CAR_TELEMETRY and len(d) == lay.sizes[P.PacketId.CAR_TELEMETRY]:
            speed, steer = tel.unpack_from(d, P.HEADER.size + p * lay.car_telemetry.size)
            fid = h["frameIdentifier"]
            if fid in frames and fid - 6 in frames and speed > 80 and abs(steer) > 0.3:
                a, b = np.array(frames[fid - 6]), np.array(frames[fid])
                r = a[6:9] / 32767.0
                vel.append(bool(np.sign(steer) == np.sign((b[:3] - a[:3]) @ r)))
                head.append(bool(np.sign(steer) == np.sign((b[3:6] - a[3:6]) @ r)))
    return len(vel), float(np.mean(vel)) if vel else 0.0, float(np.mean(head)) if head else 0.0


def test_world_right_dir_is_the_drivers_right() -> None:
    """Of the committed excerpts only Monza turns enough above 80 km/h to test it (151 samples); the Austria excerpt's
    65 are mostly the slides of a race start (the full captures: docs/research/f1-spotter-data.md)."""
    _need(MONZA)
    n, vel, head = _right_vs_steering(MONZA)
    assert n >= 100 and vel >= 0.95 and head >= 0.95, (n, vel, head)


@pytest.mark.parametrize("path", [AUSTRIA, MONZA, MELBOURNE])
def test_positions_are_fresh_and_lap_data_shares_the_motion_frame(path: Path) -> None:
    _need(path)
    lay = P.LAYOUTS[2025]
    pos = subset_struct(lay.car_motion, ("worldPositionX", "worldPositionY", "worldPositionZ"))
    vel = subset_struct(lay.car_motion, ("worldVelocityX", "worldVelocityY", "worldVelocityZ"))
    prev: list[tuple[float, ...]] | None = None
    lap_frame = -1
    same = moving = skew0 = motions = 0
    for pkt in CaptureReader(path):
        d = pkt.data
        if len(d) < P.HEADER.size:
            continue
        fid = int.from_bytes(d[19:23], "little")  # header frameIdentifier
        if d[6] == P.PacketId.LAP_DATA:
            lap_frame = fid
        elif d[6] == P.PacketId.MOTION and len(d) == lay.sizes[P.PacketId.MOTION]:
            motions += 1
            skew0 += lap_frame == fid
            body = d[P.HEADER.size : P.HEADER.size + lay.max_cars * lay.car_motion.size]
            cur = list(pos.iter_unpack(body))
            speeds = [float(np.linalg.norm(v)) for v in vel.iter_unpack(body)]
            if prev is not None:
                for i, (a, b) in enumerate(zip(prev, cur, strict=True)):
                    if speeds[i] > 5:
                        moving += 1
                        same += a == b
            prev = cur
    assert moving > 10_000 and same / moving < 1e-3, (same, moving)
    assert skew0 / motions > 0.99, (skew0, motions)


def test_austria_race_excerpt_calls_are_pinned() -> None:
    _need(AUSTRIA)
    (tr,) = collect(CaptureReader(AUSTRIA), min_motion=100)
    got = [(c.kind, round(c.session_time_s, 2)) for _i, c in tr.calls]
    assert got == [
        # 83.67-84.0 s the player slides at up to 36 degrees (113 km/h): the spin gate holds the call until 0.3 s
        # after the slide is back under 15 degrees (it was 83.73, mid-slide)
        ("car_right", 84.35),
        ("hold_your_line", 86.42),  # 0.8 m/s for 0.15 s, side by side (was 86.37 at 0.5 m/s for 0.1 s)
        ("clear_right", 87.39),
        ("car_right", 87.89),
        ("clear_right", 88.29),
        ("car_right", 89.17),
        ("clear_right", 93.21),
    ]
    row = score_trace(tr)
    assert row["gt_meaningful"] == 3 and row["hit"] == 3 and row["long_hit"] == row["long_n"] == 3
    assert row["wrong_clears"] == 0 and row["false_onsets"] == 0
    assert max(row["_delays"]) <= 0.070


def test_monza_race_start() -> None:
    _need(MONZA_START)
    (tr,) = collect(CaptureReader(MONZA_START), min_motion=100)
    row = score_trace(tr)
    kinds = [c.kind for _i, c in tr.calls]
    assert row["gt_meaningful"] == 6 and row["hit"] == 6  # every overlap of 0.3 s or more in the first 30 s
    assert row["onset_calls"] >= 4 and kinds.count("three_wide") >= 1
    assert row["wrong_clears"] == 0 and row["false_onsets"] == 0
    assert float(np.percentile(row["_delays"], 95)) <= 0.070
    assert tr.calls[0][1].session_time_s >= 5.0  # silent for the 5 s after lights out
    for dec in (3,):  # the game's default 20 Hz send rate
        (tr20,) = collect(CaptureReader(MONZA_START), min_motion=100, decimate=dec)
        r20 = score_trace(tr20)
        assert r20["hit"] == 6 and r20["wrong_clears"] == 0 and max(r20["_delays"]) <= 0.140
