"""Telemetry rig check: is the hardware reporting what the driver does? (rig-setup-sources.md section 8)

Deterministic metrics over pitwall ``LapTrace`` channels (``throttle``/``brake`` 0..1, ``steering`` -1..+1,
``speed_kph``, ``g_lat``, ``session_time_s``). They answer setup questions, not driving ones: is there brake input
at rest, can 100% throttle and brake be reached, does the brake sit at 100% for long stretches, does the brake peak
drift through a session, is the wheel centred, does it oscillate on straights or after a session change.

What telemetry cannot show (and so this module never claims): pedal force, BRF, SEN, or FFB torque. Neither F1 25
nor GT7 sends FFB torque, so clipping cannot be measured. Values are the game's *processed* inputs, very likely
after in-game deadzone/linearity/saturation (unverified, open question 6).

Design decisions:

* **Unknown stays unknown.** A metric whose data is not recorded (wheel slip, DRS state, front wheel angle, BRF
  history, the car's GT7 steering lock) returns ``status="unknown"`` with the reason, never a guess. The functions
  use those channels automatically if a later version of ``LapTrace`` stores them.
* **Labelled heuristics.** Every pass/warn threshold comes from the catalogue's ``rig_check`` entries with its
  evidence label; the constants below that shape the measurement itself (what counts as a straight, a braking
  event, a steady hold) are pitwall heuristics ``[H]``, calibrated against the real PS5 Austria race
  (docs/rig-setup.md).
* **Braking events follow Joyce et al. 2025** (Sensors 25(13):3872): a run of non-zero brake whose peak exceeds 10%,
  separated from the next by at least 2 s of zero brake (their 100 frames at 50 Hz), so the definition does not
  depend on the sample rate. Runs closer than 2 s are merged into one event; events cut by the trace edge are
  dropped because their onset or release is unknown.
* **Straights without yaw rate.** Lap traces have no yaw rate, so a straight is speed >= 120 km/h, |steering| <= 0.10
  and |lateral g| <= 0.5 g (0.5 s moving average; raw lateral g carries kerb spikes). At speed, low lateral g means
  low yaw rate.
* **Ghost braking vs. left-foot overlap.** On the real data the brake starts rising a few frames before the throttle
  leaves 100%, and a driver may brush the brake at full throttle in the second before a stop (a real Austria race:
  5% for 0.1 s, 0.9 s before the stop). ``brake_at_rest_max`` therefore skips samples within 0.5 s of *real*
  braking and in the 1.5 s before it starts; real braking needs the throttle low (<= 20%; real F1 25 stops often read
  a steady 10% throttle) as well as the brake at 10% or more. A ghost reading of any size (load-cell preload, a
  sticking pedal) with the throttle pressed, fully or partly, therefore never opens a guard window that would hide
  the full-throttle samples next to it. Only samples at 95% throttle or more are measured.
* **Re-applications happen within one stop.** Joyce's 2 s clearance can merge two separate stops (a feather, then the
  real stop; two corners close together) into one event. A re-application must happen before the stop ends, so a
  fall to zero brake *or* a throttle application resets the detector, and an event's entry speed is taken where the
  brake first reaches 10%.
* **Steering scale per game.** F1 25 normalises ``steering`` to the in-game lock (Maximum Wheel Rotation), so +-1 is
  full lock. pitwall's GT7 adapter normalises the wheel angle to a fixed nominal 900 deg (magnitude approximate),
  while GT7 runs SEN AUTO with a per-car lock that is not in telemetry. For GT7, time at full lock and centre offset
  (both "% of lock") are unknown unless the caller knows the lock (``rotation_deg``), the oscillation and reversal
  rates are informational, and the straight-line thresholds are converted so they mean the same wheel angle as on a
  360 deg F1 wheel (``SteeringScale``).
* **Session-start oscillation** (the F1 25 v1.25 bug) looks at the first 30 s of the session's first lap, in
  stretches where the car stands still or no pedal is pressed (drivers rev the engine on the grid), and counts bursts
  of three or more steering reversals larger than 10% of lock. Paused and garage frames are never in lap traces, so a
  bug that shows only there stays unseen.
* **Brake noise is the research statistic.** The standard deviation of the brake in each steady hold, after removing
  the driver's slow change through the hold with a quadratic fit (not a sample-to-sample estimate, which read a
  2-8 Hz oscillation 2-7x too low). Oscillations of 1 Hz or faster count at full size; slower ones cannot be told
  apart from the driver's own modulation.
* **Pedal-specific metrics.** Brake noise in steady holds and the heavy-stop peak against history are load-cell
  checks: with the stock Hall brake the noise is shown for comparison only (status info), and the history check
  needs earlier sessions at the same BRF, which pitwall does not record (unknown unless the caller passes them).
"""

from __future__ import annotations

import math
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from typing import Any, Literal

import numpy as np
from scipy.signal import butter, filtfilt

from pitwall.adapters.gt7.adapter import STEER_HALF_LOCK_RAD as GT7_STEER_HALF_LOCK_RAD
from pitwall.analysis.laps import FloatArray, LapFlag, LapTrace
from pitwall.rig.catalog import Catalog, RigCheckSpec, load_catalog

Status = Literal["pass", "warn", "fail", "info", "unknown"]
LapPolicy = Literal["clean", "usable"]
BoolArray = np.ndarray[Any, np.dtype[np.bool_]]

# ---- measurement heuristics [H] (thresholds for pass/warn/fail live in the catalogue) ------------------------------
BRAKE_ZERO = 0.01  # below this the brake counts as released (Hall pedals read ~1e-5 at rest on PS5)
EVENT_MIN_PEAK = 0.10  # Joyce: an event's peak must exceed 10%
CLEARANCE_S = 2.0  # Joyce: >= 100 zero-brake frames at 50 Hz either side
AT_PEAK_TOL = 0.005  # "at peak" = within half a percentage point of the event maximum
FULL = 0.99  # brake/throttle at 100%
FLAT_TOP_S = 0.3  # a plateau at 100% longer than this is a flat top
LOW_SPEED_ZONE_KPH = 120.0  # flat tops are counted in braking zones whose minimum speed is below this
HEAVY_ENTRY_KPH = 250.0  # "heavy" braking zones start above this speed
REAPPLY_DROP = 0.10  # peak-release-reapply: fall >= 10 points, then rise >= 10 points before release
STRAIGHT_MIN_KPH = 120.0
STRAIGHT_MAX_STEER = 0.10
STRAIGHT_MAX_GLAT = 0.5  # g, after a 0.5 s moving average
GLAT_SMOOTH_S = 0.5
FULL_THROTTLE = 0.95
BRAKE_GUARD_S = 0.5  # exclude samples this close to real braking from "brake at rest"
BRAKE_APPROACH_S = 1.5  # and samples this long before real braking starts (a foot covering the brake at full throttle)
BRAKE_GUARD_MAX_THROTTLE = 0.20  # real braking needs the throttle low (F1 25 often reads 10% throttle in real stops)
REAPPLY_RESET_THROTTLE = 0.20  # throttle at or above this ends the stop (real stops start with up to ~10% overlap)
HAIRPIN_KPH = 80.0  # full lock below this speed is legitimate (slow hairpins)
FULL_LOCK = 0.99
OSC_STEER_BAND = 0.05  # oscillation is measured where |steering| < 5% of lock
OSC_MIN_SEGMENT_S = 1.0
OSC_LOWPASS_HZ = 10.0
OSC_GAP = 0.01  # normalised steering (1.8 deg at 360 deg rotation)
OSC_MIN_TOTAL_S = 3.0
SWRR_LOWPASS_HZ = 2.0  # Markkula & Engstrom use 0.6 Hz for road driving; racing steers faster
SWRR_GAP_DEG = 2.0
LOCK_SLIP = 0.2  # |front wheel slip ratio| at which a lock-up starts (sign unverified; fronts are undriven)
DRS_LIGHT_BRAKE = 0.05
DRIFT_MIN_STOPS = 6  # first three against last three firm stops
HOLD_MIN_S = 0.3  # research: near-constant holds of at least 0.3 s
HOLD_LOWPASS_HZ = 3.0  # the driver's intended brake level (finds the holds)
HOLD_MAX_SLOPE = 0.5  # fraction of full brake per second: slower than this counts as held
HOLD_EDGE_S = 0.1  # trimmed from both ends of a hold
HOLD_TREND_DEGREE = 2  # the driver's slow change through a hold (a ramp or a gentle dip) is removed before the std
HOLD_MIN_LEVEL, HOLD_MAX_LEVEL = 0.05, 0.97  # away from released and from the 100% plateau
SSO_WINDOW_S = 30.0  # session-start oscillation: the first seconds of the session's first lap
SSO_NO_PEDAL = 0.05  # throttle and brake both below this: no pedal input
SSO_STATIONARY_KPH = 5.0  # or the car standing still (the grid, where drivers rev the engine)
SSO_GAP = 0.10  # reversal size, fraction of lock (36 deg at 360 deg)
SSO_MIN_REVERSALS = 3  # within one pedal-free run
SSO_MIN_RUN_S = 1.0
SSO_MIN_CHECKED_S = 2.0  # pedal-free time needed before "none" means anything
MAX_SAMPLE_GAP_S = 0.5  # a larger session-time gap is lost data (or an excerpt boundary): never bridged
MIN_LAP_SAMPLES = 600  # 10 s at 60 Hz: shorter traces cannot hold a braking event with clearance
START_LINE_TOL_M = 60.0  # a first lap that starts this close to the line started with the session
DEFAULT_ROTATION_DEG = 360.0  # F1 25: the recommended Maximum Wheel Rotation (steering is normalised to it)
GT7_ROTATION_DEG = math.degrees(2.0 * GT7_STEER_HALF_LOCK_RAD)  # GT7 adapter: fixed nominal scale (900 deg)

CORE_CHANNELS: frozenset[str] = frozenset({"brake", "throttle", "steering", "speed_kph", "session_time_s"})
INPUT_SAFE_FLAGS: frozenset[str] = frozenset({LapFlag.STANDING_START, LapFlag.DISTANCE_JUMP, LapFlag.INVALID})


# ---------------------------------------------------------------------------------------------- results
@dataclass(frozen=True, slots=True)
class MetricResult:
    metric: str
    label: str
    value: float | None  # in ``unit``; None = unknown
    unit: str
    status: Status
    heuristic: bool  # the pass/warn threshold is a pitwall heuristic [H]
    good_range: str  # the research wording (section 8), in the source's units
    target: str  # the pass/fail thresholds in this metric's display unit, e.g. "<= 0.5% (fail above 5%)"
    detail: str
    action: str | None  # what to do when the value is outside the good range
    reason_unknown: str | None = None
    samples: int = 0
    per_lap: Mapping[int, float | None] = field(default_factory=dict)
    reference: str | None = None
    threshold_note: str | None = None
    sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["value"] = _r(self.value)
        d["per_lap"] = {str(k): _r(v) for k, v in self.per_lap.items()}
        return d


@dataclass(frozen=True, slots=True)
class BrakeEvent:
    lap_number: int
    onset_s: float
    entry_speed_kph: float
    min_speed_kph: float
    peak: float
    time_to_peak_s: float  # TPB: onset -> first sample at peak
    trail_release_s: float  # TBD: last sample at peak -> brake released
    duration_s: float
    time_at_full_s: float
    low_speed_flat_tops: int
    reapplied: bool
    distance_m: float = math.nan  # lap distance where the brake first reaches 10% (identifies the corner)


@dataclass(frozen=True, slots=True)
class RigCheckReport:
    session_id: str | None
    game: str | None
    track: str | None
    session_type: str | None
    synthetic: bool
    started_unix: float | None
    lap_policy: str  # "clean" | "usable" | "usable (no clean laps)"
    laps: tuple[int, ...]
    lap_ids: tuple[int, ...]
    sample_rate_hz: float | None
    rotation_deg: float  # what steering +-1 spans (F1: the in-game lock; GT7: the adapter's nominal 900 deg)
    metrics: tuple[MetricResult, ...]
    notes: tuple[str, ...]
    generated_unix: float = 0.0
    steering_lock_deg: float | None = None  # the car's full lock-to-lock rotation, when known
    pedals: str | None = None  # the pedals fitted when the session was driven (app id), when known

    def metric(self, name: str) -> MetricResult:
        for m in self.metrics:
            if m.metric == name:
                return m
        raise KeyError(name)

    @property
    def counts(self) -> dict[str, int]:
        out = {"pass": 0, "warn": 0, "fail": 0, "info": 0, "unknown": 0}
        for m in self.metrics:
            out[m.status] += 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "game": self.game,
            "track": self.track,
            "session_type": self.session_type,
            "synthetic": self.synthetic,
            "started_unix": self.started_unix,
            "lap_policy": self.lap_policy,
            "laps": list(self.laps),
            "lap_ids": list(self.lap_ids),
            "sample_rate_hz": _r(self.sample_rate_hz),
            "rotation_deg": self.rotation_deg,
            "steering_lock_deg": self.steering_lock_deg,
            "pedals": self.pedals,
            "counts": self.counts,
            "metrics": [m.to_dict() for m in self.metrics],
            "notes": list(self.notes),
            "generated_unix": self.generated_unix,
        }


def _r(v: float | None, nd: int = 4) -> float | None:
    return None if v is None or not math.isfinite(v) else round(v, nd)


@dataclass(frozen=True, slots=True)
class SteeringScale:
    """How the normalised ``steering`` channel (-1..+1) maps to the steering wheel for one game.

    ``rotation_deg`` is the lock-to-lock rotation that -1..+1 spans (converts to degrees for the reversal rate).
    ``lock_deg`` is the car's real lock-to-lock rotation when known; "% of lock" metrics need it.
    ``threshold_scale`` multiplies the lock-fraction constants (straight-line band, oscillation band and gap), which
    were set for F1 at its default 360 deg, so they mean the same wheel angle in every game.
    ``approximate``: the scale itself is not verified (GT7's wheel-angle magnitude is community-documented).
    """

    rotation_deg: float
    lock_deg: float | None
    threshold_scale: float
    approximate: bool = False

    @property
    def lock_known(self) -> bool:
        return self.lock_deg is not None

    @property
    def half_lock_deg(self) -> float:
        return self.rotation_deg / 2.0

    def lock_fraction(self, steering: FloatArray) -> FloatArray:
        """``steering`` as a fraction of the car's full lock (only when the lock is known)."""
        if self.lock_deg is None:
            raise ValueError("steering lock unknown")
        return np.asarray(steering * (self.rotation_deg / self.lock_deg), dtype=np.float64)


def steering_scale(game: str | None, rotation_deg: float | None = None) -> SteeringScale:
    """F1 25 (and unknown games): steering is normalised to the in-game lock; ``rotation_deg`` (default 360) only
    converts it to degrees. GT7: the adapter's fixed nominal 900 deg span; the car's lock is known only when the
    caller passes it as ``rotation_deg`` (SEN AUTO picks it per car and it is not in telemetry)."""
    if game == "gt7":
        return SteeringScale(GT7_ROTATION_DEG, rotation_deg, DEFAULT_ROTATION_DEG / GT7_ROTATION_DEG, approximate=True)
    rot = rotation_deg or DEFAULT_ROTATION_DEG
    return SteeringScale(rot, rot, threshold_scale=1.0)


F1_STEERING = steering_scale(None)


# ---------------------------------------------------------------------------------------------- signal helpers
def _ch(lap: LapTrace, name: str) -> FloatArray | None:
    arr = lap.channels.get(name)
    if arr is None or len(arr) == 0 or not np.isfinite(arr).any():
        return None
    return arr


def sample_rate_hz(lap: LapTrace) -> float | None:
    t = _ch(lap, "session_time_s")
    if t is None:
        return None
    dt = np.diff(t[np.isfinite(t)])
    dt = dt[dt > 0]
    return None if len(dt) == 0 else float(1.0 / np.median(dt))


def _durations(t: FloatArray) -> FloatArray:
    """Time each sample represents (forward difference; the last sample repeats the median step)."""
    if len(t) < 2:
        return np.zeros(len(t))
    d = np.diff(t)
    med = float(np.nanmedian(d[d > 0])) if np.any(d > 0) else 0.0
    d = np.where(np.isfinite(d) & (d > 0) & (d < 1.0), d, med)
    return np.append(d, med)


def _moving_average(x: FloatArray, n: int) -> FloatArray:
    """NaN-aware centred moving average."""
    if n <= 1:
        return x
    ok = np.isfinite(x)
    k = np.ones(n)
    num = np.convolve(np.where(ok, x, 0.0), k, mode="same")
    den = np.convolve(ok.astype(float), k, mode="same")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def _runs(mask: BoolArray) -> list[tuple[int, int]]:
    """``[start, end)`` index pairs of consecutive True values."""
    if len(mask) == 0:
        return []
    m = np.concatenate(([False], mask.astype(bool), [False]))
    edges = np.flatnonzero(np.diff(m.astype(np.int8)))
    return [(int(edges[i]), int(edges[i + 1])) for i in range(0, len(edges), 2)]


def continuous_chunks(t: FloatArray) -> list[tuple[int, int]]:
    """``[start, end)`` ranges with no session-time gap above ``MAX_SAMPLE_GAP_S`` (and no time going backwards).

    Events, filters and reversal counts are computed per chunk, so lost packets (or the gaps between the windows
    of an excerpt capture) can never stretch a braking event or feed a filter a discontinuity."""
    n = len(t)
    if n == 0:
        return []
    dt = np.diff(t)
    with np.errstate(invalid="ignore"):
        brk = np.flatnonzero(~((dt >= 0) & (dt <= MAX_SAMPLE_GAP_S))) + 1
    edges = [0, *(int(i) for i in brk), n]
    return [(a, b) for a, b in pairwise(edges) if b > a]


def _runs_in_chunks(mask: BoolArray, chunks: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    return [(a + s, a + e) for a, b in chunks for s, e in _runs(mask[a:b])]


def _before(mask: BoolArray, n: int) -> BoolArray:
    """True where ``mask`` turns True within the next ``n`` samples (the approach to each run)."""
    if n <= 0 or not mask.any():
        return np.zeros(len(mask), dtype=bool)
    c = np.concatenate(([0], np.cumsum(mask.astype(np.int64))))
    i = np.arange(len(mask))
    return np.asarray(c[np.minimum(len(mask), i + 1 + n)] - c[i + 1] > 0, dtype=bool)


def _dilate(mask: BoolArray, n: int) -> BoolArray:
    if n <= 0 or not mask.any():
        return mask
    k = np.ones(2 * n + 1)
    return np.convolve(mask.astype(float), k, mode="same") > 0


def straight_mask(lap: LapTrace, steer: SteeringScale = F1_STEERING) -> BoolArray | None:
    """Straight-line, at-speed samples (see module docstring). None if speed or steering is missing."""
    v, st = _ch(lap, "speed_kph"), _ch(lap, "steering")
    if v is None or st is None:
        return None
    with np.errstate(invalid="ignore"):
        m = (v >= STRAIGHT_MIN_KPH) & (np.abs(st) <= STRAIGHT_MAX_STEER * steer.threshold_scale)
        gl = _ch(lap, "g_lat")
        if gl is not None:
            hz = sample_rate_hz(lap) or 60.0
            m &= np.abs(_moving_average(gl, max(1, round(hz * GLAT_SMOOTH_S)))) <= STRAIGHT_MAX_GLAT
    return np.asarray(m & np.isfinite(v) & np.isfinite(st), dtype=bool)


def count_reversals(theta: FloatArray, gap: float) -> int:
    """Steering reversals larger than ``gap`` (Markkula & Engstrom 2006, implemented from the paper's description).

    Stationary points of the (already filtered) signal are found; walking through them, an upward reversal is
    counted when a point exceeds the lowest point since the last counted reversal by ``gap`` (then the reference
    moves there), and a lower point moves the reference down. Downward reversals are the same on ``-theta``.
    """
    if len(theta) < 3:
        return 0
    d = np.diff(theta)
    sign = np.sign(d)
    # carry the previous sign through flat steps so a plateau is not a stationary point
    for i in range(1, len(sign)):
        if sign[i] == 0:
            sign[i] = sign[i - 1]
    idx = [0, *(int(i) + 1 for i in np.flatnonzero(sign[1:] * sign[:-1] < 0)), len(theta) - 1]
    pts = theta[idx]

    def up(values: FloatArray) -> int:
        n, k = 0, 0
        for j in range(1, len(values)):
            if values[j] - values[k] >= gap:
                n += 1
                k = j
            elif values[j] < values[k]:
                k = j
        return n

    return up(pts) + up(-pts)


def _lowpass(x: FloatArray, hz: float, cutoff: float) -> FloatArray | None:
    cutoff = min(cutoff, 0.45 * hz)
    b, a = butter(2, cutoff / (hz / 2.0))
    if len(x) <= 3 * max(len(a), len(b)):
        return None
    return np.asarray(filtfilt(b, a, x), dtype=np.float64)


def brake_events(lap: LapTrace) -> list[BrakeEvent]:
    """Braking events of one lap (Joyce et al. 2025 definition, adapted as described in the module docstring)."""
    b, t = _ch(lap, "brake"), _ch(lap, "session_time_s")
    if b is None or t is None:
        return []
    v, th, d = _ch(lap, "speed_kph"), _ch(lap, "throttle"), _ch(lap, "distance_m")
    out: list[BrakeEvent] = []
    for a, z in continuous_chunks(t):
        out.extend(
            _chunk_events(
                lap.lap_number,
                b[a:z],
                t[a:z],
                None if v is None else v[a:z],
                None if th is None else th[a:z],
                None if d is None else d[a:z],
            )
        )
    return out


def _chunk_events(
    lap_number: int,
    b: FloatArray,
    t: FloatArray,
    v: FloatArray | None,
    th: FloatArray | None = None,
    d: FloatArray | None = None,
) -> list[BrakeEvent]:
    n = len(b)
    with np.errstate(invalid="ignore"):
        nz = np.nan_to_num(b, nan=0.0) > BRAKE_ZERO
    merged: list[list[int]] = []
    for s, e in _runs(nz):
        if merged and t[s] - t[merged[-1][1] - 1] < CLEARANCE_S:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    out = []
    dur = _durations(t)
    for s, e in merged:
        if s == 0 or e >= n or t[s] - t[0] < CLEARANCE_S or t[-1] - t[e - 1] < CLEARANCE_S:
            continue  # truncated or too close to the trace edge: onset/release clearance unknown
        seg = np.nan_to_num(b[s:e], nan=0.0)
        peak = float(seg.max())
        if peak <= EVENT_MIN_PEAK:
            continue
        # Entry speed where the brake first reaches 10%, not at a light feather that Joyce's clearance merged in.
        first_app = s + int(np.argmax(seg >= EVENT_MIN_PEAK))
        at_peak = np.flatnonzero(seg >= peak - AT_PEAK_TOL)
        first_pk, last_pk = s + int(at_peak[0]), s + int(at_peak[-1])
        full = seg >= FULL
        speed = v[s:e] if v is not None else None
        min_speed = float(np.nanmin(speed)) if speed is not None and np.isfinite(speed).any() else math.nan
        flat = 0
        if min_speed < LOW_SPEED_ZONE_KPH:
            flat = sum(1 for a, z in _runs(full) if t[s + z - 1] - t[s + a] + dur[s + z - 1] > FLAT_TOP_S)
        out.append(
            BrakeEvent(
                lap_number=lap_number,
                onset_s=float(t[s]),
                entry_speed_kph=float(v[first_app]) if v is not None and np.isfinite(v[first_app]) else math.nan,
                min_speed_kph=min_speed,
                peak=peak,
                time_to_peak_s=float(t[first_pk] - t[s]),
                trail_release_s=float(t[e] - t[last_pk]),
                duration_s=float(t[e] - t[s]),
                time_at_full_s=float(dur[s:e][full].sum()),
                low_speed_flat_tops=flat,
                reapplied=_reapplied(seg, None if th is None else np.nan_to_num(th[s:e], nan=0.0)),
                distance_m=float(d[first_app]) if d is not None and np.isfinite(d[first_app]) else math.nan,
            )
        )
    return out


def _reapplied(seg: FloatArray, throttle: FloatArray | None = None) -> bool:
    """Peak, release by >= 10 points, then re-apply by >= 10 points within the same stop.

    The stop ends at a full release (brake <= ``BRAKE_ZERO``) or when the throttle is applied (>= 20%): the next press
    is a new stop (a feather before the real stop, or two corners braked less than 2 s apart), not a re-application,
    even when the clearance rule merged both into one event. A load cell that does not read exactly zero between two
    stops is caught by the throttle condition."""
    peak = 0.0
    trough: float | None = None
    for i, x in enumerate(seg):
        xf = float(x)
        thr = float(throttle[i]) if throttle is not None else 0.0
        if xf <= BRAKE_ZERO or thr >= REAPPLY_RESET_THROTTLE:
            peak, trough = 0.0, None
        elif trough is None:
            if xf > peak:
                peak = xf
            elif xf <= peak - REAPPLY_DROP:
                trough = xf
        elif xf >= trough + REAPPLY_DROP:
            return True
        else:
            trough = min(trough, xf)
    return False


# ---------------------------------------------------------------------------------------------- metrics
def _status(spec: RigCheckSpec, value: float | None) -> Status:
    if value is None:
        return "unknown"
    th = spec.thresholds
    if spec.direction in ("lower_better", "abs_lower_better"):
        v = abs(value) if spec.direction == "abs_lower_better" else value
        if v <= th.get("pass_max", math.inf):
            return "pass"
        return "fail" if "fail_above" in th and v > th["fail_above"] else "warn"
    if spec.direction == "higher_better":
        if value >= th.get("pass_min", -math.inf):
            return "pass"
        return "fail" if "fail_below" in th and value < th["fail_below"] else "warn"
    return "info"


def target_text(spec: RigCheckSpec) -> str:
    """Thresholds in the display unit, so the UI never shows a fraction next to a percentage."""
    th, u = spec.thresholds, spec.unit
    unit = u if u in ("%",) else f" {u}" if u else ""
    if spec.direction == "lower_better" and "pass_max" in th:
        out = f"<= {th['pass_max']:g}{unit}"
        return out + (f" (fail above {th['fail_above']:g}{unit})" if "fail_above" in th else "")
    if spec.direction == "abs_lower_better" and "pass_max" in th:
        out = f"within +-{th['pass_max']:g}{unit}"
        return out + (f" (fail beyond +-{th['fail_above']:g}{unit})" if "fail_above" in th else "")
    if spec.direction == "higher_better" and "pass_min" in th:
        out = f">= {th['pass_min']:g}{unit}"
        return out + (f" (fail below {th['fail_below']:g}{unit})" if "fail_below" in th else "")
    return "Compare with your own sessions" + (f" ({spec.reference})" if spec.reference else "")


def _action(spec: RigCheckSpec, value: float) -> str | None:
    if spec.direction == "lower_better":
        text = spec.action_if_high
    elif spec.direction == "higher_better":
        text = spec.action_if_low
    elif spec.direction == "abs_lower_better":
        text = spec.action_if_high if value > 0 else spec.action_if_low
    else:
        return None
    return None if text.strip().lower() in ("n/a", "-", "") else text


def _result(
    spec: RigCheckSpec,
    value: float | None,
    detail: str,
    *,
    samples: int = 0,
    per_lap: Mapping[int, float | None] | None = None,
    reason_unknown: str | None = None,
    info_only: str | None = None,
) -> MetricResult:
    """``info_only``: the value is measured but the pass/warn thresholds do not apply (the text says why)."""
    status = _status(spec, value)
    if info_only and value is not None:
        status = "info"
        detail = f"{detail} {info_only}"
    action = _action(spec, value) if status in ("warn", "fail") and value is not None else None
    return MetricResult(
        metric=spec.metric,
        label=spec.label,
        value=value,
        unit=spec.unit,
        status=status,
        heuristic=spec.threshold_evidence == "H",
        good_range=spec.good_range,
        target=target_text(spec),
        detail=detail if value is not None else (reason_unknown or detail),
        action=action,
        reason_unknown=reason_unknown if value is None else None,
        samples=samples,
        per_lap=dict(per_lap or {}),
        reference=spec.reference,
        threshold_note=spec.threshold_note,
        sources=spec.sources,
    )


def _missing(laps: Sequence[LapTrace], channels: Sequence[str]) -> list[str]:
    return [c for c in channels if not any(_ch(lap, c) is not None for lap in laps)]


def _m_brake_at_rest(laps: Sequence[LapTrace], spec: RigCheckSpec, steer: SteeringScale) -> MetricResult:
    per_lap: dict[int, float | None] = {}
    worst, n, above_s, total_s = None, 0, 0.0, 0.0
    for lap in laps:
        b, th, t = _ch(lap, "brake"), _ch(lap, "throttle"), _ch(lap, "session_time_s")
        sm = straight_mask(lap, steer)
        if b is None or th is None or t is None or sm is None:
            per_lap[lap.lap_number] = None
            continue
        hz = sample_rate_hz(lap) or 60.0
        with np.errstate(invalid="ignore"):
            # Guard only real braking: brake >= 10% with the throttle released. A ghost reading with the throttle
            # pressed (fully or partly) is exactly what this metric must report, however large, so it never opens a
            # guard window. Left-foot overlap frames at a braking onset are still excluded because throttle-off
            # braking follows within the guard.
            braking = (np.nan_to_num(b) >= EVENT_MIN_PEAK) & (np.nan_to_num(th, nan=1.0) <= BRAKE_GUARD_MAX_THROTTLE)
            near = _dilate(braking, round(BRAKE_GUARD_S * hz)) | _before(braking, round(BRAKE_APPROACH_S * hz))
            m = sm & (th >= FULL_THROTTLE) & np.isfinite(b) & ~near
        if not m.any():
            per_lap[lap.lap_number] = None
            continue
        dur = _durations(t)
        v = float(np.max(b[m])) * 100.0
        per_lap[lap.lap_number] = v
        worst = v if worst is None else max(worst, v)
        n += int(m.sum())
        total_s += float(dur[m].sum())
        above_s += float(dur[m & (b * 100.0 > spec.thresholds.get("pass_max", 0.5))].sum())
    detail = (
        f"Highest brake reading during {total_s:.0f} s of full throttle on straights; above "
        f"{spec.thresholds.get('pass_max', 0.5):g}% for {above_s:.1f} s."
    )
    return _result(
        spec, worst, detail, samples=n, per_lap=per_lap, reason_unknown="No full-throttle straight-line samples."
    )


def _m_throttle_at_rest(laps: Sequence[LapTrace], spec: RigCheckSpec) -> MetricResult:
    per_lap: dict[int, float | None] = {}
    for lap in laps:
        th = _ch(lap, "throttle")
        per_lap[lap.lap_number] = None if th is None else float(np.nanmin(th)) * 100.0
    vals = [v for v in per_lap.values() if v is not None]
    worst = max(vals) if vals else None
    return _result(
        spec,
        worst,
        "Lowest throttle reading of each lap (worst lap shown): the pedal should return to 0.",
        samples=len(vals),
        per_lap=per_lap,
        reason_unknown="No throttle channel.",
    )


def _m_throttle_peak(
    laps: Sequence[LapTrace], spec: RigCheckSpec, game: str | None, steer: SteeringScale
) -> MetricResult:
    per_lap: dict[int, float | None] = {}
    n = 0
    for lap in laps:
        th, v = _ch(lap, "throttle"), _ch(lap, "speed_kph")
        if th is None or v is None:
            per_lap[lap.lap_number] = None
            continue
        with np.errstate(invalid="ignore"):
            m = (v >= STRAIGHT_MIN_KPH) & np.isfinite(th)
        sm = straight_mask(lap, steer)
        if sm is not None and (m & sm).sum() > 30:
            m &= sm
        if not m.any():
            per_lap[lap.lap_number] = None
            continue
        per_lap[lap.lap_number] = float(np.percentile(th[m], 99)) * 100.0
        n += int(m.sum())
    vals = [v for v in per_lap.values() if v is not None]
    value = min(vals) if vals else None
    detail = "99th percentile of throttle on straights, lowest lap shown."
    if game == "f1_25":
        detail += " Since F1 25 v1.25, S Mode/DRS stays open only while throttle is above 90%."
    elif game == "gt7":
        detail += " GT7 may report throttle after traction control (unverified): a low peak may not be the pedal."
    return _result(
        spec, value, detail, samples=n, per_lap=per_lap, reason_unknown="No throttle or speed samples at speed."
    )


def _m_brake_peak_heavy(events: Sequence[BrakeEvent], spec: RigCheckSpec) -> MetricResult:
    heavy = [e for e in events if e.entry_speed_kph > HEAVY_ENTRY_KPH]
    value = float(statistics.median(e.peak for e in heavy)) * 100.0 if heavy else None
    return _result(
        spec,
        value,
        f"Median peak brake of {len(heavy)} braking zones entered above {HEAVY_ENTRY_KPH:.0f} km/h.",
        samples=len(heavy),
        reason_unknown=f"No braking zone started above {HEAVY_ENTRY_KPH:.0f} km/h.",
    )


def _m_brake_full_pct(events: Sequence[BrakeEvent], spec: RigCheckSpec) -> MetricResult:
    total = sum(e.duration_s for e in events)
    value = 100.0 * sum(e.time_at_full_s for e in events) / total if total > 0 else None
    flat = sum(e.low_speed_flat_tops for e in events)
    return _result(
        spec,
        value,
        f"Share of {total:.1f} s of braking spent at 100% over {len(events)} braking events; "
        f"{flat} plateaus at 100% longer than {FLAT_TOP_S:g} s in slow corners (below {LOW_SPEED_ZONE_KPH:.0f} km/h).",
        samples=len(events),
        reason_unknown="No braking events.",
    )


def _m_event_median(events: Sequence[BrakeEvent], spec: RigCheckSpec, attr: str, what: str) -> MetricResult:
    vals = [float(getattr(e, attr)) for e in events]
    value = float(statistics.median(vals)) if vals else None
    detail = f"Median {what} over {len(vals)} braking events"
    if len(vals) >= 4:
        q1, _, q3 = statistics.quantiles(vals, n=4)
        detail += f" (middle half {q1:.2f}-{q3:.2f} s)"
    return _result(spec, value, detail + ".", samples=len(vals), reason_unknown="No braking events.")


def _m_reapply(events: Sequence[BrakeEvent], laps: Sequence[LapTrace], spec: RigCheckSpec) -> MetricResult:
    """Re-applications per lap, over the laps where at least one braking event was measured. A lap whose stops were
    all cut by lost data or the trace edge is unknown (None), never a lap with 0 re-applications."""
    if not events:
        return _result(spec, None, "", reason_unknown="No braking events.")
    with_events = {e.lap_number for e in events}
    per_lap: dict[int, float | None] = {
        lap.lap_number: (
            float(sum(e.reapplied for e in events if e.lap_number == lap.lap_number))
            if lap.lap_number in with_events
            else None
        )
        for lap in laps
    }
    measured = [v for v in per_lap.values() if v is not None]
    value = sum(measured) / max(1, len(measured))
    return _result(
        spec,
        value,
        f"Braking events per lap where the brake fell by at least {REAPPLY_DROP * 100:.0f} points and was pressed "
        f"{REAPPLY_DROP * 100:.0f}+ points again before being released (a full release starts a new press), over "
        f"{len(measured)} lap{'s' if len(measured) != 1 else ''} with measured stops.",
        samples=len(events),
        per_lap=per_lap,
    )


def _m_lockup(laps: Sequence[LapTrace], spec: RigCheckSpec) -> MetricResult:
    missing = _missing(laps, ("wheel_slip_fl", "wheel_slip_fr"))
    if missing:
        return _result(
            spec,
            None,
            "",
            reason_unknown="Wheel slip is not recorded in pitwall lap traces, and the sign and scale of F1's wheel "
            "slip ratio are unconfirmed (open question 13).",
        )
    onsets = at_full = 0
    for lap in laps:
        b, fl, fr = _ch(lap, "brake"), _ch(lap, "wheel_slip_fl"), _ch(lap, "wheel_slip_fr")
        if b is None or fl is None or fr is None:
            continue
        # Front wheels are undriven in both games, so large front slip under braking can only be locking: |slip|
        # is used because the sign convention is unverified.
        with np.errstate(invalid="ignore"):
            locked = (np.maximum(np.abs(fl), np.abs(fr)) >= LOCK_SLIP) & (np.nan_to_num(b) > BRAKE_ZERO)
        for s, _e in _runs(locked):
            onsets += 1
            at_full += int(b[s] >= FULL)
    value = 100.0 * at_full / onsets if onsets else None
    # feat/technique: with ABS on for every lap the game prevents lock-ups, so none detected says nothing
    abs_on = bool(laps) and all(lap.meta.get("abs_active") is True for lap in laps)
    return _result(
        spec,
        value,
        f"{at_full} of {onsets} front lock-ups started with the brake at 100%.",
        samples=onsets,
        reason_unknown="ABS on: the game prevents lock-ups." if abs_on else "No front lock-ups detected.",
    )


def _m_drs(laps: Sequence[LapTrace], spec: RigCheckSpec, game: str | None) -> MetricResult:
    if game not in (None, "f1_25"):
        return _result(spec, None, "", reason_unknown="DRS / S Mode exists only in F1.")
    if _missing(laps, ("drs_open", "brake")):
        return _result(spec, None, "", reason_unknown="DRS state is not recorded in pitwall lap traces.")
    count = 0
    for lap in laps:
        drs, b = _ch(lap, "drs_open"), _ch(lap, "brake")
        if drs is None or b is None:
            continue
        d = np.nan_to_num(drs) > 0.5
        closes = np.flatnonzero(d[:-1] & ~d[1:]) + 1
        count += sum(1 for i in closes if 0.0 < b[i] < DRS_LIGHT_BRAKE)
    return _result(spec, float(count), "DRS/S Mode closures while the brake read between 0 and 5%.", samples=len(laps))


def _m_full_lock(laps: Sequence[LapTrace], spec: RigCheckSpec, steer: SteeringScale) -> MetricResult:
    lock_s = total_s = 0.0
    per_lap: dict[int, float | None] = {}
    for lap in laps:
        st, v, t = _ch(lap, "steering"), _ch(lap, "speed_kph"), _ch(lap, "session_time_s")
        if st is None or v is None or t is None:
            per_lap[lap.lap_number] = None
            continue
        dur = _durations(t)
        with np.errstate(invalid="ignore"):
            m = (np.abs(steer.lock_fraction(st)) >= FULL_LOCK) & (v >= HAIRPIN_KPH)
        lap_total = float(dur.sum())
        per_lap[lap.lap_number] = 100.0 * float(dur[m].sum()) / lap_total if lap_total else None
        lock_s += float(dur[m].sum())
        total_s += lap_total
    value = 100.0 * lock_s / total_s if total_s else None
    return _result(
        spec,
        value,
        f"{lock_s:.1f} s at full steering lock above {HAIRPIN_KPH:.0f} km/h in {total_s / 60:.1f} min of driving"
        + (f" ({steer.lock_deg:g} deg lock)." if steer.approximate else "."),
        per_lap=per_lap,
        reason_unknown="No steering or speed channel.",
        info_only=_GT7_APPROX if steer.approximate else None,
    )


def _m_centre(laps: Sequence[LapTrace], spec: RigCheckSpec, steer: SteeringScale) -> MetricResult:
    vals: list[FloatArray] = []
    per_lap: dict[int, float | None] = {}
    for lap in laps:
        st, sm = _ch(lap, "steering"), straight_mask(lap, steer)
        if st is None or sm is None or not sm.any():
            per_lap[lap.lap_number] = None
            continue
        frac = steer.lock_fraction(st[sm])
        vals.append(frac)
        per_lap[lap.lap_number] = abs(float(np.median(frac))) * 100.0
    if not vals:
        return _result(spec, None, "", reason_unknown="No straight-line samples.")
    pooled = np.concatenate(vals)
    value = abs(float(np.median(pooled))) * 100.0
    return _result(
        spec,
        value,
        f"Median steering on straights over {len(pooled)} samples, as % of full lock (0 = centred).",
        samples=len(pooled),
        per_lap=per_lap,
        info_only=_GT7_APPROX if steer.approximate else None,
    )


def _m_oscillation(laps: Sequence[LapTrace], spec: RigCheckSpec, steer: SteeringScale) -> MetricResult:
    reversals, seconds = 0, 0.0
    band, gap = OSC_STEER_BAND * steer.threshold_scale, OSC_GAP * steer.threshold_scale
    for lap in laps:
        st, sm, hz = _ch(lap, "steering"), straight_mask(lap, steer), sample_rate_hz(lap)
        if st is None or sm is None or hz is None:
            continue
        t = _ch(lap, "session_time_s")
        with np.errstate(invalid="ignore"):
            m = sm & (np.abs(st) < band)
        chunks = continuous_chunks(t) if t is not None else [(0, len(st))]
        for s, e in _runs_in_chunks(m, chunks):
            if (e - s) / hz < OSC_MIN_SEGMENT_S:
                continue
            y = _lowpass(st[s:e], hz, OSC_LOWPASS_HZ)
            if y is None:
                continue
            reversals += count_reversals(y, gap)
            seconds += (e - s) / hz
    value = reversals / seconds if seconds >= OSC_MIN_TOTAL_S else None
    size = (
        f"{gap * steer.half_lock_deg:.1f} deg (GT7 nominal {steer.rotation_deg:g} deg scale)"
        if steer.approximate
        else f"{OSC_GAP * 100:g}% of lock"
    )
    return _result(
        spec,
        value,
        f"{reversals} steering reversals larger than {size} in {seconds:.1f} s of near-centre "
        "straight-line driving (low-pass 10 Hz). Hands-on corrections count too: compare before and after a change.",
        samples=reversals,
        reason_unknown=f"Less than {OSC_MIN_TOTAL_S:g} s of steady straight-line driving.",
    )


def _m_swrr(laps: Sequence[LapTrace], spec: RigCheckSpec, steer: SteeringScale) -> MetricResult:
    reversals, minutes = 0, 0.0
    per_lap: dict[int, float | None] = {}
    for lap in laps:
        st, hz = _ch(lap, "steering"), sample_rate_hz(lap)
        if st is None or hz is None:
            per_lap[lap.lap_number] = None
            continue
        ok = np.isfinite(st)
        if ok.mean() < 0.95:
            per_lap[lap.lap_number] = None
            continue
        x = np.interp(np.arange(len(st)), np.flatnonzero(ok), st[ok]) * steer.half_lock_deg
        t = _ch(lap, "session_time_s")
        r, mins = 0, 0.0
        for a, z in continuous_chunks(t) if t is not None else [(0, len(x))]:
            y = _lowpass(x[a:z], hz, SWRR_LOWPASS_HZ)
            if y is not None:
                r += count_reversals(y, SWRR_GAP_DEG)
                mins += (z - a) / hz / 60.0
        if mins == 0:
            per_lap[lap.lap_number] = None
            continue
        per_lap[lap.lap_number] = r / mins if mins else None
        reversals += r
        minutes += mins
    value = reversals / minutes if minutes else None
    return _result(
        spec,
        value,
        f"{reversals} steering reversals of at least {SWRR_GAP_DEG:g} deg (low-pass {SWRR_LOWPASS_HZ:g} Hz, "
        + (
            f"GT7 steering on its nominal {steer.rotation_deg:g} deg scale"
            if steer.approximate
            else f"{steer.rotation_deg:g} deg rotation assumed"
        )
        + f") in {minutes:.1f} min.",
        samples=reversals,
        per_lap=per_lap,
        reason_unknown="No steering channel.",
    )


def _m_peak_drift(events: Sequence[BrakeEvent], spec: RigCheckSpec) -> MetricResult:
    """Brake-peak drift through the session (research: stops 8-10 against stops 1-3 at a similar entry speed). A
    skipped press-fully routine after power-on shows as the peak of a firm stop changing once the pedal recalibrates.

    Compared stops: heavy (entered above 250 km/h, where a firm press is expected, so entry speeds are similar) and
    single-press (a stop eased off and pressed again peaks where the driver chose: traffic, a lift). The value is the
    median peak of the last three such stops minus the median of the first three; it needs six."""
    firm = sorted(
        (e for e in events if not e.reapplied and e.entry_speed_kph > HEAVY_ENTRY_KPH), key=lambda e: e.onset_s
    )
    if len(firm) < DRIFT_MIN_STOPS:
        return _result(
            spec,
            None,
            "",
            samples=len(firm),
            reason_unknown=f"Needs at least {DRIFT_MIN_STOPS} single-press stops entered above "
            f"{HEAVY_ENTRY_KPH:.0f} km/h; found {len(firm)}.",
        )
    early, late = firm[:3], firm[-3:]
    value = 100.0 * (float(np.median([e.peak for e in late])) - float(np.median([e.peak for e in early])))
    return _result(
        spec,
        value,
        f"Median peak of the last 3 firm stops minus the first 3 ({len(firm)} single-press stops entered above "
        f"{HEAVY_ENTRY_KPH:.0f} km/h; positive: later stops peak higher).",
        samples=len(firm),
    )


def _m_hold_noise(laps: Sequence[LapTrace], spec: RigCheckSpec, pedals: str | None) -> MetricResult:
    """The research metric: standard deviation of the brake signal in near-constant holds of at least 0.3 s (after
    trimming 0.1 s at each end). A hold is where the 3 Hz low-pass of the brake changes by less than 0.5 per second
    and both it and the raw brake stay between 5% and 97% (so a series of quick taps is not a hold). The driver's
    slow change through the hold is removed with a quadratic fit (on the real Hall-brake races of 2026-10-10 a line
    left the driver's dip-and-recover inside a hold in the value, up to 1.8% per session); an oscillation of 1 Hz
    or faster under constant pressure (a fault signature) still counts at full size. Median over holds."""
    stds: list[float] = []
    for lap in laps:
        b, t, hz = _ch(lap, "brake"), _ch(lap, "session_time_s"), sample_rate_hz(lap)
        if b is None or t is None or hz is None:
            continue
        for a, z in continuous_chunks(t):
            x = np.nan_to_num(b[a:z], nan=0.0)
            lp = _lowpass(x, hz, HOLD_LOWPASS_HZ)
            if lp is None:
                continue
            slope = np.abs(np.gradient(lp)) * hz
            # the trend is steady AND the raw brake never leaves the band (rapid taps smooth into a fake "hold")
            held = (lp >= HOLD_MIN_LEVEL) & (lp <= HOLD_MAX_LEVEL) & (slope <= HOLD_MAX_SLOPE)
            held &= (x >= HOLD_MIN_LEVEL) & (x <= HOLD_MAX_LEVEL)
            edge = round(HOLD_EDGE_S * hz)  # the ends of a hold are where the press starts or stops changing
            for s, e in _runs(held):
                s, e = s + edge, e - edge
                if (e - s) / hz >= HOLD_MIN_S:
                    seg = x[s:e]
                    k = np.arange(len(seg), dtype=np.float64)
                    trend = np.polyval(np.polyfit(k, seg, HOLD_TREND_DEGREE), k)
                    stds.append(float(np.std(seg - trend)))
    if not stds:
        return _result(
            spec,
            None,
            "",
            reason_unknown=f"No steady brake holds of {HOLD_MIN_S:g} s or more between "
            f"{HOLD_MIN_LEVEL * 100:.0f}% and {HOLD_MAX_LEVEL * 100:.0f}%.",
        )
    value = 100.0 * float(np.median(stds))
    info = None
    if pedals is not None and spec.pedals and pedals not in spec.pedals:
        info = "Shown for comparison: the threshold is for the load-cell brake, and this session used the Hall brake."
    return _result(
        spec,
        value,
        f"Median standard deviation of the brake (the driver's slow change removed) over {len(stds)} steady holds "
        f"of {HOLD_MIN_S:g} s or more.",
        samples=len(stds),
        info_only=info,
    )


def heavy_peak(events: Sequence[BrakeEvent]) -> float | None:
    """Median peak (0-1) of braking events entered above 250 km/h (the value ``brake_peak_heavy_zones`` shows)."""
    heavy = [e.peak for e in events if e.entry_speed_kph > HEAVY_ENTRY_KPH]
    return float(statistics.median(heavy)) if heavy else None


def _m_peak_vs_history(
    events: Sequence[BrakeEvent], spec: RigCheckSpec, pedals: str | None, history: Sequence[float] | None
) -> MetricResult:
    if pedals is not None and spec.pedals and pedals not in spec.pedals:
        return _result(spec, None, "", reason_unknown="Load Cell Kit only: this session used the Hall brake.")
    if not history:
        return _result(
            spec,
            None,
            "",
            reason_unknown="Needs earlier sessions at the same BRF. BRF is not in telemetry and pitwall does not "
            "record BRF changes, so they cannot be picked: compare 'Full brake in heavy stops' with an earlier "
            "session instead.",
        )
    now = heavy_peak(events)
    if now is None:
        return _result(spec, None, "", reason_unknown=f"No braking zone started above {HEAVY_ENTRY_KPH:.0f} km/h.")
    ref = float(statistics.median(history))
    return _result(
        spec,
        100.0 * (now - ref),
        f"Heavy-stop peak {now * 100:.0f}% against {ref * 100:.0f}% (median of {len(history)} earlier sessions at the "
        "same BRF).",
        samples=len(history),
    )


def session_start_lap(laps: Sequence[LapTrace]) -> LapTrace | None:
    """The session's first lap, when its trace starts at the session start (grid or pit exit, not joined mid-lap)."""
    for lap in laps:
        if lap.lap_number != 1:
            continue
        d = _ch(lap, "distance_m")
        started = bool(lap.flags & {LapFlag.STANDING_START, LapFlag.PIT_OUT}) or (
            d is not None and np.isfinite(d[0]) and d[0] <= START_LINE_TOL_M
        )
        return lap if started else None
    return None


def _m_session_start(lap: LapTrace | None, spec: RigCheckSpec) -> MetricResult:
    """F1 25 v1.25 session-change oscillation: large rapid steering reversals with no pedal input in the first
    seconds of the session's first lap. Time is counted in samples (the session clock stands still on the grid)."""
    if lap is None:
        return _result(
            spec,
            None,
            "",
            reason_unknown="The session's first lap (from the grid or the pit exit) is not among the checked laps.",
        )
    st, th, b = _ch(lap, "steering"), _ch(lap, "throttle"), _ch(lap, "brake")
    if st is None or th is None or b is None:
        return _result(spec, None, "", reason_unknown="Needs steering, throttle and brake.")
    hz = sample_rate_hz(lap) or 60.0
    n = min(len(st), round(SSO_WINDOW_S * hz))
    t = _ch(lap, "session_time_s")
    chunks = continuous_chunks(t[:n]) if t is not None else [(0, n)]
    v = _ch(lap, "speed_kph")
    with np.errstate(invalid="ignore"):
        quiet = (np.nan_to_num(th[:n], nan=1.0) < SSO_NO_PEDAL) & (np.nan_to_num(b[:n], nan=1.0) < SSO_NO_PEDAL)
        if v is not None:  # waiting on the grid while revving: stationary counts as "not driving" too
            quiet |= np.nan_to_num(v[:n], nan=99.0) < SSO_STATIONARY_KPH
        quiet &= np.isfinite(st[:n])
    events, checked_s = 0, 0.0
    for s, e in _runs_in_chunks(quiet, chunks):
        if (e - s) / hz < SSO_MIN_RUN_S:
            continue
        y = _lowpass(st[s:e], hz, OSC_LOWPASS_HZ)
        if y is None:
            continue
        checked_s += (e - s) / hz
        if count_reversals(y, SSO_GAP) >= SSO_MIN_REVERSALS:
            events += 1
    if checked_s < SSO_MIN_CHECKED_S:
        return _result(
            spec,
            None,
            "",
            reason_unknown=f"Less than {SSO_MIN_CHECKED_S:g} s standing still or without pedal input in the first "
            f"{SSO_WINDOW_S:g} s of the session.",
        )
    return _result(
        spec,
        float(events),
        f"{events} bursts of {SSO_MIN_REVERSALS}+ steering reversals larger than {SSO_GAP * 100:g}% of lock in "
        f"{checked_s:.1f} s standing still or without pedal input at the start of the session. Paused and garage "
        "frames are not recorded.",
        samples=round(checked_s * hz),
    )


_LOCK_UNKNOWN = (
    "GT7 steering is normalised to a nominal 900 deg and the car's AUTO lock is not in telemetry, so full lock and "
    "% of lock are unknown. Pass the car's lock-to-lock rotation to measure it."
)
_GT7_APPROX = "Informational: GT7's wheel-angle magnitude is community-documented, so the thresholds are not applied."


def run_rig_check(
    laps: Sequence[LapTrace],
    *,
    game: str | None = None,
    rotation_deg: float | None = None,
    pedals: str | None = None,
    start_lap: LapTrace | None = None,
    brake_history: Sequence[float] | None = None,
    catalog: Catalog | None = None,
) -> list[MetricResult]:
    """Every catalogue metric over ``laps`` (pure: no I/O). Order follows the catalogue.

    ``rotation_deg``: F1's Maximum Wheel Rotation (default 360), or the car's lock-to-lock rotation in GT7 (unknown
    by default). ``pedals``: the app pedals id fitted when the laps were driven (load-cell checks). ``start_lap``:
    the session's first lap when it is not among ``laps`` (session-start oscillation). ``brake_history``: heavy-stop
    peaks (0-1) of earlier sessions at the same BRF."""
    cat = catalog or load_catalog()
    specs = cat.rig_check
    steer = steering_scale(game, rotation_deg)
    events = [e for lap in laps for e in brake_events(lap)]
    first = start_lap if start_lap is not None else session_start_lap(laps)
    # A skipped press-fully routine shows in the session's first stops, which sit on the start lap. That lap is
    # often not clean (standing start) or not usable (pit out), so its stops are added for the drift check only.
    checked = {lap.lap_number for lap in laps}
    drift_events = events if first is None or first.lap_number in checked else [*brake_events(first), *events]

    def lock_metric(build: Callable[[RigCheckSpec], MetricResult]) -> Callable[[RigCheckSpec], MetricResult]:
        return build if steer.lock_known else (lambda s: _result(s, None, "", reason_unknown=_LOCK_UNKNOWN))

    builders: dict[str, Callable[[RigCheckSpec], MetricResult]] = {
        "brake_at_rest_max": lambda s: _m_brake_at_rest(laps, s, steer),
        "throttle_at_rest_min": lambda s: _m_throttle_at_rest(laps, s),
        "throttle_peak_straights": lambda s: _m_throttle_peak(laps, s, game, steer),
        "brake_peak_heavy_zones": lambda s: _m_brake_peak_heavy(events, s),
        "brake_time_at_full_pct": lambda s: _m_brake_full_pct(events, s),
        "brake_time_to_peak_s": lambda s: _m_event_median(events, s, "time_to_peak_s", "time from brake onset to peak"),
        "trail_brake_duration_s": lambda s: _m_event_median(
            events, s, "trail_release_s", "time from the last moment at peak brake to release"
        ),
        "brake_reapply_count": lambda s: _m_reapply(events, laps, s),
        "lockup_at_full_brake_share": lambda s: _m_lockup(laps, s),
        "drs_drop_light_brake": lambda s: _m_drs(laps, s, game),
        "brake_peak_drift_session": lambda s: _m_peak_drift(drift_events, s),
        "brake_hold_noise": lambda s: _m_hold_noise(laps, s, pedals),
        "brake_peak_vs_history": lambda s: _m_peak_vs_history(events, s, pedals, brake_history),
        "steer_full_lock_share": lock_metric(lambda s: _m_full_lock(laps, s, steer)),
        "steer_centre_offset": lock_metric(lambda s: _m_centre(laps, s, steer)),
        "steer_roadwheel_linearity": lambda s: _result(
            s, None, "", reason_unknown="Front wheel angle is not recorded in pitwall lap traces."
        ),
        "straight_oscillation_rate": lambda s: _m_oscillation(laps, s, steer),
        "session_start_oscillation": lambda s: _m_session_start(first, s),
        "steering_reversal_rate": lambda s: _m_swrr(laps, s, steer),
    }
    out = []
    for name, spec in specs.items():
        if not laps:
            out.append(_result(spec, None, "", reason_unknown="No laps to check."))
            continue
        if game is not None and game not in spec.games:
            names = ", ".join(cat.games[g].name if g in cat.games else g for g in spec.games)
            out.append(
                _result(spec, None, "", reason_unknown=f"Not applicable to this game: measured for {names} only.")
            )
            continue
        # Core channels are checked here; optional ones (wheel slip, DRS, wheel angle) by the metric itself.
        missing = _missing(laps, [c for c in spec.requires if c in CORE_CHANNELS])
        builder = builders.get(name)
        if builder is None or missing:
            reason = f"Needs {', '.join(missing)}, which these laps do not record." if missing else "Not implemented."
            out.append(_result(spec, None, "", reason_unknown=reason))
            continue
        out.append(builder(spec))
    return out


_NOTES = (
    "Telemetry carries the game's processed inputs (probably after in-game deadzone, linearity and saturation; "
    "unverified). It cannot show pedal force, BRF or SEN.",
    "Neither F1 25 nor GT7 sends force-feedback torque, so clipping and FFB strength cannot be measured here.",
    "Thresholds marked H are pitwall heuristics, not published values. Use them to compare sessions, before and "
    "after a change.",
)
_GT7_NOTES = (
    "GT7: steering is on a nominal 900 deg scale and the car's AUTO lock is not in telemetry, so time at full lock "
    "and centre offset are unknown (informational when a lock is given); oscillation and reversal rates are "
    "informational, with thresholds converted to wheel degrees on that nominal scale.",
    "GT7: the throttle and brake values may be the output after TCS/ABS rather than the pedal (open question 13), "
    "so a low throttle or brake peak may not be the pedal.",
)


def build_report(
    laps: Sequence[LapTrace],
    *,
    session: Mapping[str, Any] | None = None,
    lap_policy: str = "clean",
    lap_ids: Sequence[int] = (),
    rotation_deg: float | None = None,
    pedals: str | None = None,
    start_lap: LapTrace | None = None,
    brake_history: Sequence[float] | None = None,
    catalog: Catalog | None = None,
) -> RigCheckReport:
    s = session or {}
    game = s.get("game")
    metrics = run_rig_check(
        laps,
        game=game,
        rotation_deg=rotation_deg,
        pedals=pedals,
        start_lap=start_lap,
        brake_history=brake_history,
        catalog=catalog,
    )
    rates = [r for r in (sample_rate_hz(lap) for lap in laps) if r is not None]
    notes = list(_NOTES)
    if game == "gt7":
        notes.extend(_GT7_NOTES)
    synthetic = bool(s.get("synthetic"))
    if synthetic:
        notes.insert(0, "SYNTHETIC session (generated data): this says nothing about your rig.")
    if lap_policy.startswith("usable"):
        notes.append(
            "Includes laps that are not clean (standing start, track-limit or distance-jump laps): their pedal and "
            "steering inputs are still valid for a rig check."
        )
    steer = steering_scale(game, rotation_deg)
    return RigCheckReport(
        session_id=s.get("id"),
        game=game,
        track=s.get("track_name"),
        session_type=s.get("session_type"),
        synthetic=synthetic,
        started_unix=s.get("started_unix"),
        lap_policy=lap_policy,
        laps=tuple(lap.lap_number for lap in laps),
        lap_ids=tuple(lap_ids),
        sample_rate_hz=float(np.median(rates)) if rates else None,
        rotation_deg=steer.rotation_deg,
        metrics=tuple(metrics),
        notes=tuple(notes),
        generated_unix=time.time(),
        steering_lock_deg=steer.lock_deg,
        pedals=pedals,
    )


# ---------------------------------------------------------------------------------------------- sessions
def select_laps(rows: Sequence[Mapping[str, Any]], policy: LapPolicy = "clean") -> tuple[list[Mapping[str, Any]], str]:
    """Pick lap rows (``repo.list_laps`` dicts) for the check and say which policy was effectively used.

    ``clean`` laps are the default. ``usable`` adds laps whose only flags are ones that leave the driver's inputs
    intact (standing start, track-limits invalid, distance jump). ``clean`` falls back to ``usable`` when a
    session has no clean lap (a short race often has one or none), and the report says so.
    """

    def long_enough(r: Mapping[str, Any]) -> bool:
        return int(r.get("n_samples") or 0) >= MIN_LAP_SAMPLES

    clean = [r for r in rows if r.get("clean") and long_enough(r)]
    usable = [
        r
        for r in rows
        if long_enough(r)
        and (r.get("clean") or (bool(r.get("flags")) and set(r.get("flags") or ()) <= INPUT_SAFE_FLAGS))
    ]
    if policy == "clean":
        return (clean, "clean") if clean else (usable, "usable (no clean laps)")
    return usable, "usable"


def check_session(
    conn: Any,
    session_id: str,
    policy: LapPolicy = "clean",
    rotation_deg: float | None = None,
    catalog: Catalog | None = None,
    *,
    pedals: str | None = None,
) -> RigCheckReport | None:
    """Load a session's laps with the existing read-only repository functions and run the check. None if the
    session does not exist. The session's first lap is loaded for the session-start check even when the lap policy
    leaves it out (a standing-start lap is not clean, but its first seconds are what that check needs)."""
    from pitwall.storage import repo

    session = repo.get_session(conn, session_id)
    if session is None:
        return None
    all_rows = repo.list_laps(conn, session_id)
    rows, effective = select_laps(all_rows, policy)
    laps = [lap for lap in (repo.load_lap_trace(conn, int(r["id"])) for r in rows) if lap is not None]
    start = session_start_lap(laps)
    if start is None:
        first = next((r for r in all_rows if int(r.get("lap_number") or 0) == 1), None)
        if first is not None and int(first["id"]) not in {int(r["id"]) for r in rows}:
            start = session_start_lap(
                [lap for lap in (repo.load_lap_trace(conn, int(first["id"])),) if lap is not None]
            )
    return build_report(
        laps,
        session=session,
        lap_policy=effective,
        lap_ids=[int(r["id"]) for r in rows],
        rotation_deg=rotation_deg,
        pedals=pedals,
        start_lap=start,
        catalog=catalog,
    )


@dataclass(frozen=True, slots=True)
class MetricDelta:
    metric: str
    label: str
    unit: str
    before: float | None
    after: float | None
    delta: float | None
    before_status: Status
    after_status: Status

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("before", "after", "delta"):
            d[k] = _r(d[k])
        return d


def compare_reports(before: RigCheckReport, after: RigCheckReport) -> list[MetricDelta]:
    """Per-metric change between two checks (e.g. the last session before an upgrade and the latest one)."""
    b = {m.metric: m for m in before.metrics}
    out = []
    for m in after.metrics:
        old = b.get(m.metric)
        bv = old.value if old else None
        delta = m.value - bv if m.value is not None and bv is not None else None
        out.append(
            MetricDelta(m.metric, m.label, m.unit, bv, m.value, delta, old.status if old else "unknown", m.status)
        )
    return out
