"""Racing line relative to the driver's own reference lap (never an "ideal" line: track edges are unknown).

``lateral_offsets`` measures, for every metre of a lap, how far it ran from the reference lap's line, positive to
the reference's left normal in the game's ground plane. Per corner, ``inside_sign`` turns that into "tighter" (+,
towards the inside of this corner) or "wider" (-), which works whatever the handedness of the game's frame: the
sign of the reference line's own curvature says which side the inside is. On a near-straight (radius above 2 km)
the inside is unknown and offsets are reported without a side.

Matching is two-stage so games whose lap distance is derived (GT7, Forza) and drifts a few metres still match: a
coarse nearest-point search every 50 m within +/-150 m, median-filtered, gives a distance shift; then every sample
is matched to the nearest reference point within +/-30 m of the shifted index. A match that is not roughly square
to the reference line (more than 2 m along it) or further than 25 m from it is dropped (NaN).

Corner points come from the reference lap: the apex is its slowest point, turn-in is where its steering rises above
a quarter of the corner's steering peak, track-out where it falls below that again.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from pitwall.analysis.distance import DistanceTrace
from pitwall.analysis.laps import FloatArray
from pitwall.technique import thresholds as T


@dataclass(slots=True)
class ReferenceLine:
    """The reference lap's line on its 1 m grid: points, unit tangents and signed curvature (1/m)."""

    d: FloatArray
    a: FloatArray
    b: FloatArray
    ta: FloatArray
    tb: FloatArray
    kappa: FloatArray
    step: float

    @property
    def has_positions(self) -> bool:
        return bool(np.isfinite(self.a).sum() >= 10)


def _smooth(x: FloatArray, n: int) -> FloatArray:
    """NaN-aware centred moving average over ``n`` samples (NaN where no sample is finite)."""
    if n <= 1:
        return x.copy()
    ok = np.isfinite(x)
    k = np.ones(n)
    num = np.convolve(np.where(ok, x, 0.0), k, mode="same")
    den = np.convolve(ok.astype(np.float64), k, mode="same")
    out = np.full(len(x), np.nan)
    np.divide(num, den, out=out, where=den > 0)
    return out


def _step(dt: DistanceTrace) -> float:
    return float(dt.d[1] - dt.d[0]) if len(dt.d) > 1 else 1.0


def reference_line(ref: DistanceTrace, plane: tuple[str, str]) -> ReferenceLine:
    step = _step(ref)
    nan = np.full(len(ref.d), np.nan)
    a = ref.ch.get(plane[0], nan)
    b = ref.ch.get(plane[1], nan)
    n = max(1, round(T.LINE_SMOOTH_M / step))
    sa, sb = _smooth(a, n), _smooth(b, n)
    ga, gb = np.full(len(a), np.nan), np.full(len(b), np.nan)
    if len(a) >= 3:
        ga[1:-1] = sa[2:] - sa[:-2]
        gb[1:-1] = sb[2:] - sb[:-2]
    norm = np.hypot(ga, gb)
    with np.errstate(invalid="ignore", divide="ignore"):
        ta = np.where(norm > 1e-9, ga / norm, np.nan)
        tb = np.where(norm > 1e-9, gb / norm, np.nan)
    kappa = np.full(len(a), np.nan)
    if len(a) >= 2:
        kappa[:-1] = (ta[:-1] * tb[1:] - tb[:-1] * ta[1:]) / step
    return ReferenceLine(d=ref.d, a=a, b=b, ta=ta, tb=tb, kappa=kappa, step=step)


def _windows(x: FloatArray, half: int) -> np.ndarray:
    """``out[k]`` = ``x[k-half .. k+half]`` (NaN beyond the ends), via a strided view (no copy of the windows)."""
    pad = np.concatenate([np.full(half, np.nan), x, np.full(half, np.nan)])
    return sliding_window_view(pad, 2 * half + 1)


def _nearest(
    ref: ReferenceLine, ba: FloatArray, bb: FloatArray, centres: np.ndarray, half: int
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest reference index for each (ba, bb) within ``centres +/- half`` (``valid`` False: none is finite)."""
    wa = _windows(ref.a, half)[centres]
    wb = _windows(ref.b, half)[centres]
    d2 = (ba[:, None] - wa) ** 2 + (bb[:, None] - wb) ** 2
    d2 = np.where(np.isfinite(d2), d2, np.inf)
    k = np.argmin(d2, axis=1)
    valid = np.isfinite(d2[np.arange(len(k)), k]) if len(k) else np.zeros(0, dtype=bool)
    return centres - half + k, valid


def _coarse_shift(ref: ReferenceLine, ba: FloatArray, bb: FloatArray) -> FloatArray:
    """Index shift (reference index - lap index) at every sample, from a coarse search every 50 m."""
    n = len(ba)
    every = max(1, round(T.LINE_COARSE_EVERY_M / ref.step))
    half = max(1, round(T.LINE_COARSE_SEARCH_M / ref.step))
    ks = np.arange(0, n, every)
    ks = ks[np.isfinite(ba[ks]) & np.isfinite(bb[ks])]
    if len(ks) == 0:
        return np.zeros(n)
    j, valid = _nearest(ref, ba[ks], bb[ks], ks, half)
    shift = np.where(valid, (j - ks).astype(np.float64), np.nan)
    # 3-point median filter (NaN-aware) over the coarse points: one bad match cannot move the window
    filt = np.full(len(shift), np.nan)
    for i in range(len(shift)):  # coarse points only (one per 50 m), not samples
        w = shift[max(0, i - 1) : i + 2]
        w = w[np.isfinite(w)]
        if len(w):
            filt[i] = float(np.median(w))
    ok = np.isfinite(filt)
    if not ok.any():
        return np.zeros(n)
    out: FloatArray = np.interp(np.arange(n, dtype=np.float64), ks[ok].astype(np.float64), filt[ok])
    return out


def lateral_offsets(ref: ReferenceLine, lap: DistanceTrace, plane: tuple[str, str]) -> FloatArray:
    """Signed distance (m) of ``lap`` from the reference line at every grid point, + = the reference's left normal.

    NaN where the lap has no position, no reference point matches squarely within the search window, or the lap is
    more than ``LINE_MAX_LATERAL_M`` away (off track, pit lane)."""
    n = len(lap.d)
    out = np.full(n, np.nan)
    nan = np.full(n, np.nan)
    ba = lap.ch.get(plane[0], nan)
    bb = lap.ch.get(plane[1], nan)
    if len(ref.a) != n or not ref.has_positions:
        return out
    shift = _coarse_shift(ref, ba, bb)
    idx = np.flatnonzero(np.isfinite(ba) & np.isfinite(bb))
    if len(idx) == 0:
        return out
    half = max(1, round(T.LINE_SEARCH_M / ref.step))
    centres = np.clip(np.rint(idx + shift[idx]).astype(np.int64), 0, n - 1)
    j, valid = _nearest(ref, ba[idx], bb[idx], centres, half)
    j = np.clip(j, 0, n - 1)
    da, db = ba[idx] - ref.a[j], bb[idx] - ref.b[j]
    ta, tb = ref.ta[j], ref.tb[j]
    lateral = da * (-tb) + db * ta  # left normal N = (-tb, ta)
    along = da * ta + db * tb
    with np.errstate(invalid="ignore"):
        ok = valid & (np.abs(along) <= T.LINE_MAX_ALONG_M) & (np.abs(lateral) <= T.LINE_MAX_LATERAL_M)
    out[idx[ok]] = lateral[ok]
    return out


def inside_sign(ref: ReferenceLine, apex_m: float) -> int:
    """+1 / -1: which normal side is the inside of the corner at ``apex_m``; 0 when the line is too straight to say."""
    i = round(apex_m / ref.step)
    half = max(1, round(T.INSIDE_CURVATURE_HALF_M / ref.step))
    w = ref.kappa[max(0, i - half) : i + half + 1]
    w = w[np.isfinite(w)]
    if len(w) == 0:
        return 0
    k = float(np.mean(w))
    if abs(k) < T.STRAIGHT_CURVATURE:
        return 0
    return 1 if k > 0 else -1


def steer_points(d: FloatArray, steer: FloatArray, apex_m: float) -> tuple[float | None, float | None]:
    """(turn-in, track-out) on a 1 m grid: where |steering| crosses a quarter of the corner's steering peak (95th
    percentile within +/-150 m of the apex), scanning at most 300 m either side. None when not found."""
    n = len(d)
    if n < 3 or not np.isfinite(apex_m):
        return None, None
    step = float(d[1] - d[0])
    ia = int(min(n - 1, max(0, round((apex_m - d[0]) / step))))
    s = np.abs(steer)
    w = np.abs(d - apex_m) <= T.STEER_PEAK_WINDOW_M
    vals = s[w & np.isfinite(s)]
    if len(vals) < 5:
        return None, None
    peak = float(np.percentile(vals, 95))
    if peak < 0.02:
        return None, None
    thr = T.TURN_IN_STEER_FRAC * peak
    scan = round(T.STEER_SCAN_MAX_M / step)
    lo = max(0, ia - scan)
    with np.errstate(invalid="ignore"):
        below = np.flatnonzero(s[lo : ia + 1] < thr)
    turn_in: float | None = None
    if len(below):
        k = lo + int(below[-1]) + 1
        if k < ia:
            turn_in = float(d[k])
    hi = min(n - 1, ia + scan)
    with np.errstate(invalid="ignore"):
        below2 = np.flatnonzero(s[ia : hi + 1] < T.TRACK_OUT_STEER_FRAC * peak)
    track_out: float | None = None
    if len(below2) and below2[0] > 0:
        track_out = float(d[ia + int(below2[0])])
    return turn_in, track_out


def point_offset(d: FloatArray, offset: FloatArray, at_m: float | None) -> float | None:
    """Median offset within +/-5 m of ``at_m`` (at least 6 finite samples), else None."""
    if at_m is None or not np.isfinite(at_m):
        return None
    w = np.abs(d - at_m) <= T.LINE_POINT_HALF_WINDOW_M
    vals = offset[w]
    vals = vals[np.isfinite(vals)]
    if len(vals) < T.LINE_POINT_MIN_SAMPLES:
        return None
    return float(np.median(vals))


def polyline(
    dt: DistanceTrace, plane: tuple[str, str], step_m: float, lo: float = 0.0, hi: float | None = None
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """(d, a, b) of a lap every ``step_m`` metres within [lo, hi] (NaN where the lap has no position)."""
    top = float(dt.d[-1]) if hi is None else min(hi, float(dt.d[-1]))
    d = np.arange(max(0.0, lo), top + 1e-9, step_m)
    nan = np.full(len(dt.d), np.nan)
    a = np.interp(d, dt.d, dt.ch.get(plane[0], nan), left=np.nan, right=np.nan)
    b = np.interp(d, dt.d, dt.ch.get(plane[1], nan), left=np.nan, right=np.nan)
    return d, a, b
