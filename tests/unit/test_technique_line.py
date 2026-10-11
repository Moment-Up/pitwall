"""Racing line against the reference lap: lateral offsets, inside side, robustness, turn-in / track-out points."""

from __future__ import annotations

import numpy as np
import pytest

from pitwall.analysis.distance import DistanceTrace
from pitwall.technique.line import (
    inside_sign,
    lateral_offsets,
    point_offset,
    reference_line,
    steer_points,
)

PLANE = ("pos_x_m", "pos_z_m")
N = 1400


def _kappa(corners: list[tuple[float, float, float]]) -> np.ndarray:
    """Curvature on a 1 m grid: (start, length, curvature) arcs, straight elsewhere."""
    k = np.zeros(N)
    for start, length, kap in corners:
        k[int(start) : int(start + length)] = kap
    return k


def _path(k: np.ndarray, mirror: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Points of a path with curvature ``k`` and, at each point, the unit vector towards the inside of the turn
    (zero on straights), worked out from the geometry alone (not from the module under test)."""
    h = np.cumsum(k)
    x, z = np.cumsum(np.sin(h)), np.cumsum(np.cos(h))
    # heading h rotates the direction (sin h, cos h) towards (cos h, -sin h) as h grows: that side is the inside
    ix, iz = np.sign(k) * np.cos(h), -np.sign(k) * np.sin(h)
    if mirror:
        x, ix = -x, -ix
    return np.stack([x, z]), np.stack([ix, iz])


def _trace(x: np.ndarray, z: np.ndarray, d: np.ndarray | None = None, steer: np.ndarray | None = None) -> DistanceTrace:
    grid = np.arange(N, dtype=np.float64)
    ch = {
        "pos_x_m": x if d is None else np.interp(grid, d, x),
        "pos_z_m": z if d is None else np.interp(grid, d, z),
        "steering": np.zeros(N) if steer is None else steer,
        "speed_kph": np.full(N, 100.0),
    }
    return DistanceTrace(d=grid, t_s=grid / 30.0, ch=ch, lap_number=1)


def _offset_lap(
    corners: list[tuple[float, float, float]], offset_out: float, mirror: bool = False, window: float = 120.0
) -> tuple[DistanceTrace, DistanceTrace, list[float]]:
    """Reference on the centre line, lap ``offset_out`` metres towards the outside around each apex."""
    pts, inside = _path(_kappa(corners), mirror)
    s = np.arange(N)
    w = np.zeros(N, dtype=bool)
    apexes = []
    for start, length, _ in corners:
        apex = start + length / 2
        apexes.append(apex)
        w |= np.abs(s - apex) <= window
    out_pts = pts - offset_out * inside * w
    return _trace(pts[0], pts[1]), _trace(out_pts[0], out_pts[1]), apexes


ARC = [(500.0, 157.0, 1 / 50)]  # 180 deg right-hand (sign per the path's frame) hairpin, radius 50 m
CHICANE = [(500.0, 60.0, 1 / 40), (560.0, 60.0, -1 / 40)]


@pytest.mark.parametrize("corners", [ARC, CHICANE])
@pytest.mark.parametrize("mirror", [False, True])
def test_a_lap_run_wide_reads_minus_two_metres_at_every_apex(
    corners: list[tuple[float, float, float]], mirror: bool
) -> None:
    ref, lap, apexes = _offset_lap(corners, 2.0, mirror, window=25.0)
    geo = reference_line(ref, PLANE)
    off = lateral_offsets(geo, lap, PLANE)
    for apex in apexes:
        sign = inside_sign(geo, apex)
        assert sign != 0
        v = point_offset(ref.d, off, apex)
        assert v is not None and v * sign == pytest.approx(-2.0, abs=0.05)  # wider = negative, mirrored or not
    far = point_offset(ref.d, off, 200.0)
    assert far is not None and abs(far) < 0.05  # nothing changed on the straight


def test_mirrored_frames_give_the_same_inside_side() -> None:
    ref, _, apexes = _offset_lap(ARC, 0.0)
    mref, _, _ = _offset_lap(ARC, 0.0, mirror=True)
    a, b = reference_line(ref, PLANE), reference_line(mref, PLANE)
    # the left normal flips with the handedness, and so does the curvature: inside * normal is the same direction
    assert inside_sign(a, apexes[0]) == -inside_sign(b, apexes[0])


def test_distance_drift_of_one_percent_is_still_matched() -> None:
    pts, inside = _path(_kappa(ARC))
    ref = _trace(pts[0], pts[1])
    geo = reference_line(ref, PLANE)
    apex = ARC[0][0] + ARC[0][1] / 2
    out = pts - 2.0 * inside
    # the lap's own lap distance runs 1 % long (derived distance, e.g. GT7): position s is reported at 1.01 * s
    lap = _trace(out[0], out[1], d=np.arange(N) * 1.01)
    off = lateral_offsets(geo, lap, PLANE)
    v = point_offset(ref.d, off, apex * 1.01)
    sign = inside_sign(geo, apex)
    assert v is not None and v * sign == pytest.approx(-2.0, abs=0.1)


def test_far_from_the_reference_is_unknown() -> None:
    ref, lap, apexes = _offset_lap(ARC, 30.0, window=60.0)
    geo = reference_line(ref, PLANE)
    off = lateral_offsets(geo, lap, PLANE)
    assert point_offset(ref.d, off, apexes[0]) is None  # > 25 m: off track or the pit lane


def test_a_straight_has_no_inside() -> None:
    ref, _, _ = _offset_lap([], 0.0)
    assert inside_sign(reference_line(ref, PLANE), 700.0) == 0


def test_one_bad_sample_does_not_move_the_point() -> None:
    ref, lap, apexes = _offset_lap(ARC, 2.0, window=30.0)
    geo = reference_line(ref, PLANE)
    off = lateral_offsets(geo, lap, PLANE)
    i = int(apexes[0])
    off[i] = 12.0  # one glitch
    v = point_offset(ref.d, off, apexes[0])
    assert v is not None and abs(v) == pytest.approx(2.0, abs=0.05)
    sparse = np.full(N, np.nan)
    sparse[i : i + 3] = 1.0
    assert point_offset(ref.d, sparse, apexes[0]) is None  # fewer than 6 samples: unknown


def test_turn_in_and_track_out_come_from_the_steering() -> None:
    d = np.arange(N, dtype=np.float64)
    steer = np.zeros(N)
    steer[480:500] = np.linspace(0, 0.4, 20)  # turn in from 480 m
    steer[500:640] = 0.4
    steer[640:660] = np.linspace(0.4, 0, 20)  # unwind to 660 m
    ti, to = steer_points(d, steer, 570.0)
    assert ti is not None and 480 <= ti <= 490
    assert to is not None and 650 <= to <= 660
    assert steer_points(d, np.zeros(N), 570.0) == (None, None)  # no steering: no points
