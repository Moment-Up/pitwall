"""Synthetic closed circuits built from straights and constant-radius arcs.

Used only to generate synthetic validation telemetry. Two designated straights are solved so that the
loop closes exactly, which keeps the geometry realistic (no smeared closure error).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Straight:
    length_m: float | None  # None = solved automatically to close the loop
    name: str = ""


@dataclass(frozen=True, slots=True)
class Arc:
    radius_m: float
    angle_deg: float  # positive = right-hand turn, negative = left-hand turn
    name: str = ""


Segment = Straight | Arc


@dataclass(slots=True)
class TrackGeometry:
    name: str
    s: FloatArray  # arc length (m), uniform step
    x: FloatArray
    z: FloatArray
    heading: FloatArray  # rad, 0 = +z, increasing clockwise (right turn)
    curvature: FloatArray  # 1/m, positive = right turn
    length_m: float
    corners: list[tuple[str, float, float]]  # (name, start_s, end_s) of each arc

    def corner_apex_s(self) -> dict[str, float]:
        return {name: (a + b) / 2 for name, a, b in self.corners}


def _walk(segments: list[Segment], free: dict[int, float]) -> tuple[float, float, float]:
    x = z = h = 0.0
    for i, seg in enumerate(segments):
        if isinstance(seg, Straight):
            length = seg.length_m if seg.length_m is not None else free[i]
            x += length * math.sin(h)
            z += length * math.cos(h)
        else:
            ang = math.radians(seg.angle_deg)
            r = seg.radius_m
            sign = 1.0 if ang > 0 else -1.0
            # centre of rotation is to the right (+) or left (-) of the heading
            cx = x + sign * r * math.cos(h)
            cz = z - sign * r * math.sin(h)
            h2 = h + ang
            x = cx - sign * r * math.cos(h2)
            z = cz + sign * r * math.sin(h2)
            h = h2
    return x, z, h


def solve_closure(segments: list[Segment]) -> list[Segment]:
    free_idx = [i for i, s in enumerate(segments) if isinstance(s, Straight) and s.length_m is None]
    if len(free_idx) != 2:
        raise ValueError("exactly two straights must have length_m=None")
    total_turn = sum(s.angle_deg for s in segments if isinstance(s, Arc))
    if abs(abs(total_turn) - 360.0) > 1e-6:
        raise ValueError(f"arcs must sum to +/-360 degrees, got {total_turn}")
    x0, z0, _ = _walk(segments, {free_idx[0]: 0.0, free_idx[1]: 0.0})
    # headings at the free straights
    dirs = []
    h = 0.0
    for i, seg in enumerate(segments):
        if i in free_idx:
            dirs.append((math.sin(h), math.cos(h)))
        if isinstance(seg, Arc):
            h += math.radians(seg.angle_deg)
    a = np.array([[dirs[0][0], dirs[1][0]], [dirs[0][1], dirs[1][1]]])
    sol = np.linalg.solve(a, np.array([-x0, -z0]))
    if (sol < 50).any():
        raise ValueError(f"closure needs straights of {sol} m; adjust the design")
    out = list(segments)
    for k, i in enumerate(free_idx):
        seg = segments[i]
        assert isinstance(seg, Straight)
        out[i] = Straight(float(sol[k]), seg.name)
    return out


def build_track(name: str, segments: list[Segment], step_m: float = 1.0) -> TrackGeometry:
    segs = solve_closure(segments)
    xs: list[float] = []
    zs: list[float] = []
    hs: list[float] = []
    ks: list[float] = []
    corners: list[tuple[str, float, float]] = []
    x = z = h = 0.0
    s_acc = 0.0
    for seg in segs:
        if isinstance(seg, Straight):
            assert seg.length_m is not None
            n = max(1, round(seg.length_m / step_m))
            ds = seg.length_m / n
            for _ in range(n):
                xs.append(x)
                zs.append(z)
                hs.append(h)
                ks.append(0.0)
                x += ds * math.sin(h)
                z += ds * math.cos(h)
            s_acc += seg.length_m
        else:
            ang = math.radians(seg.angle_deg)
            length = abs(ang) * seg.radius_m
            n = max(1, round(length / step_m))
            dh = ang / n
            sign = 1.0 if ang > 0 else -1.0
            cx = x + sign * seg.radius_m * math.cos(h)
            cz = z - sign * seg.radius_m * math.sin(h)
            corners.append((seg.name, s_acc, s_acc + length))
            for _ in range(n):
                xs.append(x)
                zs.append(z)
                hs.append(h)
                ks.append(sign / seg.radius_m)
                h += dh
                x = cx - sign * seg.radius_m * math.cos(h)
                z = cz + sign * seg.radius_m * math.sin(h)
            s_acc += length
    # resample to an exactly uniform grid
    raw_s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xs), np.diff(zs)))])
    total = float(raw_s[-1] + math.hypot(xs[0] - xs[-1], zs[0] - zs[-1]))
    s = np.arange(0.0, total, step_m)
    k_arr = np.interp(s, raw_s, ks)
    # smooth curvature slightly (real tracks have transitions, not curvature steps)
    win = max(1, round(15 / step_m))
    kernel = np.ones(win) / win
    k_pad = np.concatenate([k_arr[-win:], k_arr, k_arr[:win]])
    k_smooth = np.convolve(k_pad, kernel, mode="same")[win:-win]
    return TrackGeometry(
        name=name,
        s=s,
        x=np.interp(s, raw_s, xs),
        z=np.interp(s, raw_s, zs),
        heading=np.interp(s, raw_s, np.unwrap(hs)),
        curvature=k_smooth,
        length_m=total,
        corners=corners,
    )


def pitwall_park() -> TrackGeometry:
    """A ~5 km synthetic circuit with hairpins, a chicane, fast sweepers and long straights."""
    return build_track(
        "Pitwall Park (synthetic)",
        [
            Straight(820, "main straight"),
            Arc(22, 115, "T1"),
            Straight(None, "back straight 1"),
            Arc(90, -55, "T2"),
            Straight(260),
            Arc(38, 95, "T3"),
            Straight(480),
            Arc(28, 50, "T4"),
            Arc(28, -50, "T5"),
            Straight(None, "back straight 2"),
            Arc(210, 75, "T6"),
            Straight(330),
            Arc(48, 65, "T7"),
            Straight(560),
            Arc(60, 65, "T8"),
            Straight(240),
        ],
    )
