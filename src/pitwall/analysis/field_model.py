"""Field model (track knowledge layer L0b): learn the circuit from the OTHER cars of the same session.

In any F1 session with AI cars, Motion / LapData / CarTelemetry describe every car, so within the first minutes
pitwall can know the racing line, the speed profile and where the field brakes - before the driver has completed
a single clean lap (research: ``docs/research/track-knowledge-sources.md`` section 2 "L0b" and section 8 "Phase 3").

Everything here is ``tier="field_observed"``, ``source="AI field"``: an *AI reference*, never the driver's target.
The learned model from the driver's own laps (layer L3, ``analysis.track``) stays authoritative for positions and
braking targets; ``core.track_knowledge`` applies that precedence.

Method (clean room; the binning idea matches the published description of Pits n' Giggles' generator):

1. **Filter** every ``FieldSample`` (``FieldFilter``; the section 2 filters): AI cars only (human opponents'
   data is a privacy question), result active, flying lap / on track (F1 25 reports every racing car as "on
   track" in a race: real PS5 Austria capture), pit status 0, no safety car, not race lap 1, no negative lap
   distance, and in races more than ``min_gap_m`` behind the car in front when the game reports the gap (what
   that gap means outside races - on-track or classification gap - is unverified, so it is not used there). A
   flashback (game clock going back) drops every lap in progress; a car going backwards drops its own. An in-lap
   is dropped, never finished: in the real PS5 Austria race F1 25 flagged a pitting car "in_lap" only ~240 m
   before the pit lane, yet the car with comparable laps was already 11-33 km/h slower through T9-T10 before that
   and braked 12 m *later* for T10. So the lap in progress is dropped when the car turns "in_lap" mid-lap
   or reaches the pit lane (``pit_status`` != 0, the backstop for a visit the status does not flag), and the rest
   of the lap it rejoins on is skipped (pit exit merge; F1 25 also flags it "out_lap").
2. **Trace** each eligible car's samples per lap. A finished car-lap (or a lap cut short by another filter;
   traffic is not a cut) is resampled onto the 5 m grid (bin centres ``(i + 0.5) * bin_m``) by linear interpolation
   between samples at most ``MAX_SAMPLE_GAP_M`` apart; elsewhere the row is NaN (unknown, never invented). At most
   ``max_car_laps`` rows are kept (newest win), plus every lap still in progress at snapshot time.
3. **Medians** across car-laps per bin: line (x/y/z), speed, brake, throttle, steering; ``brake_frac`` (share of
   car-laps braking) and ``support`` (car-laps with data in the bin).
4. **Braking zones** are found on the median profile: the first bin whose median brake exceeds ``BRAKE_ON``
   (0.10, never ``brake > 0``: real pedals have a noise floor) after a throttle phase starts a zone, which runs to
   the next throttle phase. Each car-lap also records its own onsets while it is fed (the ``BRAKE_ON`` rising
   crossing after a throttle phase, interpolated between its raw samples, carried across the line), and per zone
   these give ``onset_m`` (their median: sample-exact, no bin quantisation), ``support`` (car-laps that braked
   there), the spread (IQR) and a conservative *early* heads-up point:
   ``heads_up_m = onset_m - max(uncertainty_m, MIN_HEADS_UP_EARLY_M)`` with
   ``uncertainty_m = max(bin_m, onset_m - q25)``. Never later than 15 m before the field's median onset: on real
   PS5 data this driver braked up to ~50 m *before* the AI field in places (Austria Reverse T1, Silverstone T15),
   and a harder AI brakes later still (AI difficulty is not reported).
5. **Provisional corners**: the median profile goes through the existing speed-minimum detector
   (``analysis.track.build_track_model``); corners are renamed ``F1..Fn`` so they can never be mistaken for the
   learned ``T1..Tn`` numbering or official turn numbers (identity, layer L2, is attached by the resolver).
6. **Brake envelope**: full-brake samples (brake >= 0.95, ``-g_lon * g``) fit ``decel = b0 + b1 v^2``, the per-game
   calibration the physics prior needs (real PS5 races: 3.9-4.0 g at 300 km/h against the default model's 5.5 g).

Sampling bias (documented, safe direction): with 10 Hz samples a car covers up to ~9 m between samples. Linear
interpolation across the brake step puts each car-lap's crossing early by ~0.4 sample spacing on average, so
onsets err *early* by a few metres - the direction CLAUDE.md allows (synthetic ground truth: 2.5-3.7 m early).

Threading: ``FieldModel`` is not thread-safe and does no I/O. ``feed`` is O(1) amortised (~1 us; finishing a
car-lap resamples it with numpy, ~0.1 ms, once per car per lap); ``snapshot`` costs ~35 ms for 100 car-laps at
Austria. Both run on the field worker thread (``core.track_knowledge.FieldWorker``), never on the ingest thread.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import numpy.typing as npt

from pitwall.analysis.distance import DistanceTrace
from pitwall.analysis.track import Corner, TrackModel, build_track_model
from pitwall.model.telemetry import FieldSample

FloatArray = npt.NDArray[np.float64]

TIER = "field_observed"
SOURCE = "AI field"

BIN_M = 5.0
BRAKE_ON = 0.10  # median pedal above this = braking (research section 2, pedal-noise note)
BRAKE_OFF = 0.05
THROTTLE_PHASE = 0.6  # median throttle at or above this, with brake below BRAKE_OFF, is a throttle phase ...
MIN_THROTTLE_BINS = 2  # ... once it lasts this many bins (10 m)
MIN_ZONE_PEAK_BRAKE = 0.3  # a lighter median application is a dab, not a braking zone (cf. coach.cues)
MIN_ZONE_DROP_KPH = 15.0
HEAVY_DROP_KPH = 100.0  # same speed-drop bar as the physics prior's voice gate (research section 2, L1c)
MEDIUM_DROP_KPH = 40.0
ZONE_LOOKBACK_M = 150.0  # per-car-lap onsets are searched this far before the field onset
ZONE_CORNER_SLACK_M = 40.0  # a zone's corner: apex inside the zone, else this close to its minimum
MIN_SUPPORT = 3  # car-laps behind a braking zone before it may drive a heads-up (research section 2)
MIN_HEADS_UP_EARLY_M = 15.0  # the heads-up point sits at least this far before the field's median onset
MIN_GAP_M = 40.0
MAX_SAMPLE_GAP_M = 25.0  # interpolate across at most this much distance (10 Hz at 330 km/h is ~9 m)
MIN_TRACE_M = 100.0
MAX_CAR_LAPS = 96
MAX_TRACE_SAMPLES = 4000  # per car and lap (10 Hz for 6+ minutes): a stuck car cannot grow memory
REWIND_M = 20.0  # a car going back this far within a lap: flashback or reset to track
MAX_TRACE_IDLE_S = 60.0  # a lap whose car sent nothing eligible for this long is finished (stalled stream)
CLOCK_REWIND_S = 0.5  # the game clock going back this far: flashback
CORNER_MIN_COVERAGE = 0.9  # run the corner detector only when the median profile covers this share of the lap
DRIVING_STATUSES = frozenset({"flying_lap", "on_track"})
CHANNELS = ("x", "y", "z", "speed", "brake", "throttle", "steer")
G = 9.81
ENVELOPE_BRAKE = 0.95  # full-brake samples fit the braking envelope (research section 2, L1c / phase 3)
ENVELOPE_MIN_KPH = 80.0  # below this the car is at the end of the stop, where the deceleration falls away
ENVELOPE_MIN_SAMPLES = 60
MAX_ENVELOPE_SAMPLES = 20_000


@dataclass(slots=True, frozen=True)
class FieldFilter:
    """Which samples the field model learns from (research section 2, L0b filters). All on by default."""

    ai_only: bool = True  # unknown (no Participants packet yet) is not AI
    skip_race_lap_1: bool = True
    min_gap_m: float | None = MIN_GAP_M  # races only (the gap is unverified elsewhere); None = keep cars in traffic
    exclude_safety_car: bool = True


@dataclass(slots=True, frozen=True)
class FieldBrakeZone:
    """A braking zone of the AI field (lap distances in metres; ``tier="field_observed"``, an AI reference)."""

    onset_m: float  # median of the car-laps' own onsets (the profile onset when no car-lap has one)
    profile_onset_m: float  # where the field's median brake first exceeds BRAKE_ON (bin-interpolated)
    heads_up_m: float  # conservative early point: onset_m - max(uncertainty_m, MIN_HEADS_UP_EARLY_M)
    uncertainty_m: float
    end_m: float  # where the next throttle phase starts
    entry_speed_kph: float
    min_speed_kph: float
    min_speed_m: float
    peak_brake: float  # peak of the median brake over the zone
    severity: str  # "heavy" | "medium" | "light" (speed drop)
    support: int  # car-laps with their own onset in this zone
    cars: int  # distinct cars among them
    onset_q25_m: float | None  # quartiles of the car-laps' onsets
    onset_q75_m: float | None
    corner: str | None = None  # provisional corner (F1..Fn) whose minimum ends this zone
    complete: bool = True  # False while part of the zone has no data (minimum and severity may still change)
    tier: str = TIER
    source: str = SOURCE

    @property
    def spread_m(self) -> float | None:
        if self.onset_q25_m is None or self.onset_q75_m is None:
            return None
        return self.onset_q75_m - self.onset_q25_m

    def to_dict(self) -> dict[str, Any]:
        return {
            "onset_m": _r(self.onset_m, 1),
            "profile_onset_m": _r(self.profile_onset_m, 1),
            "heads_up_m": _r(self.heads_up_m, 1),
            "uncertainty_m": _r(self.uncertainty_m, 1),
            "end_m": _r(self.end_m, 1),
            "entry_speed_kph": _r(self.entry_speed_kph, 1),
            "min_speed_kph": _r(self.min_speed_kph, 1),
            "min_speed_m": _r(self.min_speed_m, 1),
            "peak_brake": _r(self.peak_brake, 2),
            "severity": self.severity,
            "support": self.support,
            "cars": self.cars,
            "onset_q25_m": _r(self.onset_q25_m, 1),
            "onset_q75_m": _r(self.onset_q75_m, 1),
            "spread_m": _r(self.spread_m, 1),
            "corner": self.corner,
            "complete": self.complete,
            "tier": self.tier,
            "source": self.source,
        }


@dataclass(slots=True, frozen=True)
class FieldBrakeEnvelope:
    """Full-brake deceleration of the AI field, ``decel = brake_base + brake_aero * v^2`` (m/s^2, v in m/s), fitted
    from samples with brake >= 0.95 and ``-g_lon * g``: the per-game calibration the physics prior (layer L1c) needs
    (research section 2 "L1c": the default model brakes too hard for F1 25). Same shape as
    ``analysis.brake_prior.BrakeEnvelope``."""

    brake_base: float
    brake_aero: float
    samples: int
    rmse_mps2: float
    source: str = "AI field"

    def decel_g(self, speed_kph: float) -> float:
        v = speed_kph / 3.6
        return (self.brake_base + self.brake_aero * v * v) / G

    def to_dict(self) -> dict[str, Any]:
        return {
            "brake_base": round(self.brake_base, 3),
            "brake_aero": round(self.brake_aero, 6),
            "samples": self.samples,
            "rmse_mps2": round(self.rmse_mps2, 2),
            "decel_g_at_300_kph": round(self.decel_g(300.0), 2),
            "source": self.source,
            "tier": TIER,
        }


def fit_brake_envelope(speed_mps: FloatArray, decel_mps2: FloatArray) -> FieldBrakeEnvelope | None:
    """Least-squares ``decel = b0 + b1 v^2``; None with too few samples or a non-physical fit."""
    ok = np.isfinite(speed_mps) & np.isfinite(decel_mps2) & (decel_mps2 > 0.0)
    v, a = speed_mps[ok], decel_mps2[ok]
    if len(v) < ENVELOPE_MIN_SAMPLES:
        return None
    design = np.column_stack([np.ones_like(v), v * v])
    coef, *_ = np.linalg.lstsq(design, a, rcond=None)
    b0, b1 = float(coef[0]), float(coef[1])
    if not (math.isfinite(b0) and math.isfinite(b1)) or b1 < 0.0:
        return None
    rmse = float(np.sqrt(np.mean((design @ coef - a) ** 2)))
    return FieldBrakeEnvelope(brake_base=b0, brake_aero=b1, samples=len(v), rmse_mps2=rmse)


@dataclass(slots=True)
class FieldSnapshot:
    """What the field has taught pitwall so far. Per-bin arrays are NaN where no eligible car-lap has data."""

    game: str
    track_id: str | None
    track_length_m: float
    bin_m: float
    version: int  # increases with every snapshot of the same model
    session_time_s: float | None  # game clock of the newest sample in it
    car_laps: int  # rows behind the medians (finished car-laps + laps in progress)
    cars: int  # distinct cars among them
    x_m: FloatArray
    y_m: FloatArray
    z_m: FloatArray
    speed_kph: FloatArray
    brake: FloatArray  # median pedal
    brake_frac: FloatArray  # share of car-laps with brake >= BRAKE_ON
    throttle: FloatArray
    steering: FloatArray
    speed_iqr_kph: FloatArray  # across-car spread of speed
    support: npt.NDArray[np.int32]  # car-laps with data per bin
    braking_zones: tuple[FieldBrakeZone, ...] = ()
    corners: tuple[Corner, ...] = ()  # provisional (F1..Fn), positions only; identity is attached elsewhere
    brake_envelope: FieldBrakeEnvelope | None = None
    counts: dict[str, int] = field(default_factory=dict)  # samples accepted / rejected by reason
    tier: str = TIER
    source: str = SOURCE

    @property
    def n_bins(self) -> int:
        return len(self.speed_kph)

    @property
    def d_m(self) -> FloatArray:
        """Bin centres (m)."""
        return (np.arange(self.n_bins, dtype=np.float64) + 0.5) * self.bin_m

    @property
    def coverage(self) -> float:
        """Share of the lap with at least one eligible car-lap."""
        return float(np.mean(self.support > 0)) if self.n_bins else 0.0

    def heads_up_zones(self, min_support: int = MIN_SUPPORT) -> tuple[FieldBrakeZone, ...]:
        return tuple(z for z in self.braking_zones if z.support >= min_support)

    def distance_trace(self) -> DistanceTrace:
        """Median profile as a ``DistanceTrace`` on the bin centres (``t_s`` integrated from the median speed)."""
        return DistanceTrace(
            d=self.d_m,
            t_s=_lap_time_s(self.speed_kph, self.bin_m),
            ch={
                "speed_kph": self.speed_kph.copy(),
                "brake": self.brake.copy(),
                "throttle": self.throttle.copy(),
                "steering": self.steering.copy(),
                "pos_x_m": self.x_m.copy(),
                "pos_y_m": self.y_m.copy(),
                "pos_z_m": self.z_m.copy(),
            },
            lap_number=0,
        )

    def as_track_model(self) -> TrackModel:
        """The provisional corners as a ``TrackModel`` (version = snapshot version), e.g. for identity mapping. Its
        centreline (one point per bin) is filled only when the field covers the whole lap: a gap would shift every
        later point's lap distance."""
        full = bool(np.isfinite(self.x_m).all() and np.isfinite(self.z_m).all())
        centre = (
            [(round(float(x), 2), round(float(z), 2)) for x, z in zip(self.x_m, self.z_m, strict=True)] if full else []
        )
        return TrackModel(
            game=self.game,
            track_id=self.track_id or "unknown",
            track_name=None,
            length_m=self.track_length_m,
            version=self.version,
            n_laps=self.car_laps,
            corners=[replace(c) for c in self.corners],
            centreline=centre,
        )

    def to_dict(self, *, arrays: bool = True) -> dict[str, Any]:
        """Strict-JSON-safe dict (NaN -> None). ``arrays=False`` leaves out the per-bin arrays."""
        out: dict[str, Any] = {
            "tier": self.tier,
            "source": self.source,
            "game": self.game,
            "track_id": self.track_id,
            "track_length_m": self.track_length_m,
            "bin_m": self.bin_m,
            "version": self.version,
            "session_time_s": _r(self.session_time_s, 2),
            "car_laps": self.car_laps,
            "cars": self.cars,
            "coverage": round(self.coverage, 3),
            "braking_zones": [z.to_dict() for z in self.braking_zones],
            "corners": [
                {
                    "name": c.name,
                    "apex_m": _r(c.apex_m, 1),
                    "entry_m": _r(c.entry_m, 1),
                    "exit_m": _r(c.exit_m, 1),
                    "direction": c.direction,
                    "min_speed_kph": _r(c.ref_min_speed_kph, 1),
                }
                for c in self.corners
            ],
            "brake_envelope": None if self.brake_envelope is None else self.brake_envelope.to_dict(),
            "counts": dict(self.counts),
        }
        if arrays:
            out["line"] = [
                [_r(float(x), 1), _r(float(z), 1)] for x, z in zip(self.x_m, self.z_m, strict=True)
            ]  # [x, z] per bin: the ground plane of F1's Y-up world
            out["elevation_m"] = _list(self.y_m, 1)
            out["speed_kph"] = _list(self.speed_kph, 1)
            out["speed_iqr_kph"] = _list(self.speed_iqr_kph, 1)
            out["brake"] = _list(self.brake, 2)
            out["brake_frac"] = _list(self.brake_frac, 2)
            out["throttle"] = _list(self.throttle, 2)
            out["support"] = [int(v) for v in self.support]
        return out


@dataclass(slots=True)
class _Row:
    car: int
    lap: int
    ch: dict[str, npt.NDArray[np.float32]]
    onsets: tuple[float, ...]  # this car-lap's braking onsets (lap distance, m), from the raw samples


@dataclass(slots=True)
class _Trace:
    car: int
    lap: int
    rows: list[tuple[float, ...]] = field(default_factory=list)  # (d, x, y, z, speed, brake, throttle, steer)
    last_t: float = 0.0
    last_d: float = 0.0
    onsets: list[float] = field(default_factory=list)
    armed: bool = False  # a throttle phase since the last braking onset (and no unknown stretch since)
    prev: tuple[float, float] | None = None  # (d, brake) of the previous sample (d < 0: end of the previous lap)


class FieldModel:
    """Incremental field model for one session on one track (see the module docstring).

    ``feed`` the adapter's ``FieldSample``s (in arrival order), call ``snapshot`` whenever a fresh view is wanted
    (the worker does it every few seconds when ``dirty``). ``counts`` says how many samples each filter rejected.
    """

    def __init__(
        self,
        *,
        game: str,
        track_id: str | None,
        track_length_m: float,
        is_race: bool = False,
        filters: FieldFilter | None = None,
        bin_m: float = BIN_M,
        max_car_laps: int = MAX_CAR_LAPS,
    ) -> None:
        if not (math.isfinite(track_length_m) and track_length_m > 10 * bin_m):
            raise ValueError(f"track_length_m must be a real lap length, got {track_length_m}")
        if not (math.isfinite(bin_m) and 1.0 <= bin_m <= 50.0):
            raise ValueError(f"bin_m must be 1-50 m, got {bin_m}")
        self.game = game
        self.track_id = track_id
        self.length_m = float(track_length_m)
        self.is_race = is_race
        self.filters = filters or FieldFilter()
        self.bin_m = float(bin_m)
        self.n_bins = math.ceil(self.length_m / self.bin_m)
        self._centres = (np.arange(self.n_bins, dtype=np.float64) + 0.5) * self.bin_m
        self._rows: deque[_Row] = deque(maxlen=max(1, max_car_laps))
        self._traces: dict[int, _Trace] = {}
        # car -> lap it rejoined on after a pit visit (None until its first sample outside the pit lane): skipped
        self._rejoin: dict[int, int | None] = {}
        self._last_t: float | None = None
        self._envelope: deque[tuple[float, float]] = deque(maxlen=MAX_ENVELOPE_SAMPLES)
        self._version = 0
        self.counts: Counter[str] = Counter()
        self.dirty = False

    # ------------------------------------------------------------------ input
    def feed_many(self, samples: Iterable[FieldSample]) -> None:
        for s in samples:
            self.feed(s)

    def feed(self, s: FieldSample) -> bool:
        """Take one sample; True when it was used. O(1) except when it completes a car-lap."""
        t = s.session_time_s
        last_t = self._last_t
        if last_t is not None and t < last_t - CLOCK_REWIND_S:
            # flashback: every lap in progress now holds driving the game has rewound
            self.counts["flashback_drops"] += len(self._traces)
            self._traces.clear()
        self._last_t = t if last_t is None or t > last_t or t < last_t - CLOCK_REWIND_S else last_t
        car = s.car_index
        reason = self._reject_reason(s)
        if s.pit_status == 0 and car in self._rejoin:
            lap = self._rejoin[car]
            if lap is None:  # the car's first sample out of the pit lane, whatever else filters it (an out-lap)
                self._rejoin[car] = lap = s.lap_number
            if s.lap_number != lap:
                del self._rejoin[car]  # a new lap since it rejoined: clean again
            elif reason is None:
                reason = "out_lap"
        if reason in (None, "traffic"):  # full braking in traffic is still the car's braking capability
            self._envelope_sample(s)
        if reason is not None:
            self.counts[reason] += 1
            if reason == "pit" or (reason == "driver_status" and s.driver_status == "in_lap" and self._mid_lap(s)):
                # an in-lap (heading for the pits, already off the racing pace): dropped, never finished
                if self._traces.pop(car, None) is not None:
                    self.counts["in_lap_drops"] += 1
                if reason == "pit":
                    self._rejoin[car] = None  # and the lap it rejoins on is skipped (pit exit merge)
            elif reason != "traffic":  # traffic thins a lap; anything else ends the car's clean run
                self._finish(car)
            return False
        d, lap = s.lap_distance_m, s.lap_number
        tr = self._traces.get(car)
        half = 0.5 * self.length_m
        carry: tuple[bool, tuple[float, float]] | None = None
        if tr is not None:
            if lap == tr.lap + 1 and d > half and tr.last_d > half:
                lap = tr.lap  # the lap number moved a sample before the distance wrapped: still the old lap
            elif lap == tr.lap and d < tr.last_d - half:
                lap = tr.lap + 1  # the distance wrapped a sample before the lap number moved
            if lap != tr.lap or t - tr.last_t > MAX_TRACE_IDLE_S:
                if lap == tr.lap + 1 and t - tr.last_t <= 1.0 and tr.prev is not None:
                    # straight on into the next lap: a braking zone just after the line keeps its throttle phase
                    carry = (tr.armed, (tr.prev[0] - self.length_m, tr.prev[1]))
                self._finish(car)
                tr = None
            elif d < tr.last_d - REWIND_M:
                self.counts["rewind_drops"] += 1
                del self._traces[car]
                tr = None
            elif d <= tr.last_d:
                self.counts["stationary"] += 1
                return False
        if tr is None:
            tr = self._traces[car] = _Trace(car=car, lap=lap)
            if carry is not None:
                tr.armed, tr.prev = carry
        if len(tr.rows) >= MAX_TRACE_SAMPLES:
            self.counts["trace_full"] += 1
            return False
        brake, throttle = s.brake, s.throttle
        prev = tr.prev
        if prev is None or d - prev[0] > MAX_SAMPLE_GAP_M:
            tr.armed = throttle >= THROTTLE_PHASE and brake < BRAKE_OFF  # nothing known in between
        elif throttle >= THROTTLE_PHASE and brake < BRAKE_OFF:
            tr.armed = True
        elif tr.armed and brake >= BRAKE_ON > prev[1]:
            w = (BRAKE_ON - prev[1]) / (brake - prev[1])
            tr.onsets.append((prev[0] + w * (d - prev[0])) % self.length_m)
            tr.armed = False
        tr.prev = (d, brake)
        tr.rows.append((d, s.pos_x_m, s.pos_y_m, s.pos_z_m, s.speed_kph, brake, throttle, s.steering))
        tr.last_t, tr.last_d = t, d
        self.counts["accepted"] += 1
        self.dirty = True
        return True

    def _mid_lap(self, s: FieldSample) -> bool:
        """Whether ``s`` is on the same lap as its car's lap in progress (not the next lap's first sample: at the
        line an ended flying lap turns "in_lap" and is finished as usual)."""
        tr = self._traces.get(s.car_index)
        return tr is not None and s.lap_number == tr.lap and s.lap_distance_m >= tr.last_d - 0.5 * self.length_m

    def _envelope_sample(self, s: FieldSample) -> None:
        glon = s.g_lon
        if glon is not None and s.brake >= ENVELOPE_BRAKE and s.speed_kph >= ENVELOPE_MIN_KPH:
            self._envelope.append((s.speed_kph / 3.6, -glon * G))

    def _reject_reason(self, s: FieldSample) -> str | None:
        f = self.filters
        if f.ai_only and s.ai_controlled is not True:
            return "not_ai"
        if s.result_status != "active":
            return "result_status"
        if s.pit_status != 0:
            return "pit"  # before the driver status: any pit visit drops the lap in progress and the rejoin lap
        if s.driver_status not in DRIVING_STATUSES:
            return "driver_status"  # garage, out lap, in lap
        if f.exclude_safety_car and s.safety_car:
            return "safety_car"
        if f.skip_race_lap_1 and self.is_race and s.lap_number <= 1:
            return "race_lap_1"
        d = s.lap_distance_m
        if not (math.isfinite(d) and 0.0 <= d <= self.length_m + MAX_SAMPLE_GAP_M):
            return "lap_distance"
        if not all(
            math.isfinite(v) for v in (s.pos_x_m, s.pos_y_m, s.pos_z_m, s.speed_kph, s.brake, s.throttle, s.steering)
        ):
            return "non_finite"
        if f.min_gap_m is not None and self.is_race and s.gap_ahead_ms is not None:
            gap_m = s.gap_ahead_ms / 1000.0 * s.speed_kph / 3.6
            if gap_m < f.min_gap_m:
                return "traffic"
        return None

    def _finish(self, car: int) -> None:
        tr = self._traces.pop(car, None)
        if tr is None:
            return
        row = self._resample(tr)
        if row is None:
            self.counts["short_traces"] += 1
            return
        self._rows.append(row)
        self.counts["car_laps"] += 1
        self.dirty = True

    def _resample(self, tr: _Trace) -> _Row | None:
        if len(tr.rows) < 3:
            return None
        a = np.asarray(tr.rows, dtype=np.float64)
        d = a[:, 0]
        if d[-1] - d[0] < MIN_TRACE_M:
            return None
        c = self._centres
        j = np.searchsorted(d, c, side="right")  # d[j-1] <= c < d[j]
        inside = (j > 0) & (j < len(d))
        jj = np.clip(j, 1, len(d) - 1)
        step = d[jj] - d[jj - 1]
        ok = inside & (step <= MAX_SAMPLE_GAP_M)
        ok |= c == d[-1]
        ch: dict[str, npt.NDArray[np.float32]] = {}
        for k, name in enumerate(CHANNELS, start=1):
            y = np.interp(c, d, a[:, k])
            y[~ok] = np.nan
            ch[name] = y.astype(np.float32)
        return _Row(car=tr.car, lap=tr.lap, ch=ch, onsets=tuple(tr.onsets))

    # ------------------------------------------------------------------ output
    @property
    def car_laps(self) -> int:
        return len(self._rows)

    def snapshot(self) -> FieldSnapshot | None:
        """The current view: medians over the kept car-laps and the laps in progress. None before any data."""
        if self._last_t is not None:
            for car in [c for c, tr in self._traces.items() if self._last_t - tr.last_t > MAX_TRACE_IDLE_S]:
                self._finish(car)  # its car stopped sending (retired, finished, left): the lap is as long as it got
        rows = list(self._rows)
        for tr in self._traces.values():
            r = self._resample(tr)
            if r is not None:
                rows.append(r)
        self.dirty = False
        if not rows:
            return None
        self._version += 1
        stack = {k: np.vstack([r.ch[k] for r in rows]).astype(np.float64) for k in CHANNELS}
        # Medians only over bins with data: an all-NaN bin would warn, and silencing that with
        # warnings.catch_warnings is not thread-safe (it swaps process-global filters; this runs on the worker).
        med = {k: _nanmedian_cols(v) for k, v in stack.items()}
        q75, q25 = _nanpercentile_cols(stack["speed"], (75.0, 25.0))
        valid = np.isfinite(stack["brake"])
        support = valid.sum(axis=0).astype(np.int32)
        with np.errstate(invalid="ignore", divide="ignore"):
            brake_frac = np.where(support > 0, (stack["brake"] >= BRAKE_ON).sum(axis=0) / support, np.nan)
        snap = FieldSnapshot(
            game=self.game,
            track_id=self.track_id,
            track_length_m=self.length_m,
            bin_m=self.bin_m,
            version=self._version,
            session_time_s=self._last_t,
            car_laps=len(rows),
            cars=len({r.car for r in rows}),
            x_m=med["x"],
            y_m=med["y"],
            z_m=med["z"],
            speed_kph=med["speed"],
            brake=med["brake"],
            brake_frac=brake_frac.astype(np.float64),
            throttle=med["throttle"],
            steering=med["steer"],
            speed_iqr_kph=q75 - q25,
            support=support,
            counts=dict(self.counts),
        )
        if self._envelope:
            env = np.asarray(self._envelope, dtype=np.float64)
            snap.brake_envelope = fit_brake_envelope(env[:, 0], env[:, 1])
        corners = _provisional_corners(snap)
        snap.corners = corners
        snap.braking_zones = _braking_zones(snap, [(r.car, r.onsets) for r in rows], corners)
        return snap


# ================================================================================================== zones
def _throttle_phase(brake: FloatArray, throttle: FloatArray) -> npt.NDArray[np.bool_]:
    with np.errstate(invalid="ignore"):
        return (throttle >= THROTTLE_PHASE) & (brake < BRAKE_OFF)


def _scan_start(phase: npt.NDArray[np.bool_]) -> int | None:
    """Middle of the longest cyclic throttle-phase run (usually the main straight): a scan from there meets every
    braking zone exactly once."""
    n = len(phase)
    if not phase.any():
        return None
    if phase.all():
        return 0
    first_off = int(np.argmin(phase))  # a bin outside any run
    best_len, best_mid, run, start = 0, 0, 0, 0
    for k in range(1, n + 1):
        i = (first_off + k) % n
        if phase[i]:
            if run == 0:
                start = k
            run += 1
            if run > best_len:
                best_len, best_mid = run, (first_off + start + run // 2) % n
        else:
            run = 0
    return best_mid


def _cross(lo_val: float, hi_val: float, lo_d: float, thr: float, bin_m: float) -> float:
    """Distance where a value rising from ``lo_val`` (at ``lo_d``) to ``hi_val`` (one bin later) crosses ``thr``."""
    if not (math.isfinite(lo_val) and math.isfinite(hi_val)) or hi_val <= lo_val:
        return lo_d + bin_m
    w = min(1.0, max(0.0, (thr - lo_val) / (hi_val - lo_val)))
    return lo_d + w * bin_m


def _braking_zones(
    snap: FieldSnapshot, row_onsets: list[tuple[int, tuple[float, ...]]], corners: tuple[Corner, ...]
) -> tuple[FieldBrakeZone, ...]:
    brake, throttle, speed = snap.brake, snap.throttle, snap.speed_kph
    n, bin_m, length = snap.n_bins, snap.bin_m, snap.track_length_m
    centres = snap.d_m
    phase = _throttle_phase(brake, throttle)
    start = _scan_start(phase)
    if start is None:
        return ()
    zones: list[FieldBrakeZone] = []
    armed = False
    run = 0
    k = 0
    while k < n:
        i = (start + k) % n
        b = brake[i]
        if not math.isfinite(b) or not math.isfinite(throttle[i]):
            armed, run = False, 0  # unknown cannot prove a throttle phase
            k += 1
            continue
        if phase[i]:
            run += 1
            if run >= MIN_THROTTLE_BINS:
                armed = True
            k += 1
            continue
        run = 0
        if not (armed and b > BRAKE_ON):
            k += 1
            continue
        # profile onset between bin i-1 (below the threshold) and bin i
        prev = (i - 1) % n
        profile_onset = _cross(float(brake[prev]), float(b), float(centres[prev]), BRAKE_ON, bin_m) % length
        # the zone runs until a throttle phase is re-established
        j, run_j, peak, vmin, vmin_i = k, 0, 0.0, math.inf, i
        complete = True
        while j < k + n:
            ii = (start + j) % n
            if not (math.isfinite(brake[ii]) and math.isfinite(speed[ii])):
                complete = False  # the field has not driven all of it yet: the minimum may still come
            if phase[ii]:
                run_j += 1
                if run_j >= MIN_THROTTLE_BINS:
                    break
            else:
                run_j = 0
            if math.isfinite(brake[ii]):
                peak = max(peak, float(brake[ii]))
            if math.isfinite(speed[ii]) and speed[ii] < vmin:
                vmin, vmin_i = float(speed[ii]), ii
            j += 1
        end_i = (start + j - run_j + 1) % n
        entry = float(speed[prev]) if math.isfinite(speed[prev]) else float("nan")
        armed, run = run_j >= MIN_THROTTLE_BINS, run_j
        k = j + 1
        if not (math.isfinite(entry) and math.isfinite(vmin)):
            continue
        drop = entry - vmin
        if peak < MIN_ZONE_PEAK_BRAKE or drop < MIN_ZONE_DROP_KPH:
            continue  # a dab or a lift
        severity = "heavy" if drop >= HEAVY_DROP_KPH else "medium" if drop >= MEDIUM_DROP_KPH else "light"
        min_m = float(centres[vmin_i])
        onsets, cars = _zone_onsets(row_onsets, profile_onset - ZONE_LOOKBACK_M, min_m, length)
        q25 = q50 = q75 = None
        onset = profile_onset
        if onsets:
            rel = np.array([_signed(o - profile_onset, length) for o in onsets])
            q25, q50, q75 = (float(profile_onset + v) for v in np.percentile(rel, [25, 50, 75]))
            onset = q50  # the car-laps' own onsets: sample-exact, no bin quantisation
        unc = bin_m if q25 is None else max(bin_m, onset - q25)
        corner = _zone_corner(corners, profile_onset, float(centres[end_i]), min_m, length, bin_m)
        zones.append(
            FieldBrakeZone(
                onset_m=onset % length,
                profile_onset_m=profile_onset,
                heads_up_m=(onset - max(unc, MIN_HEADS_UP_EARLY_M)) % length,
                uncertainty_m=unc,
                end_m=float(centres[end_i]) - 0.5 * bin_m,
                entry_speed_kph=entry,
                min_speed_kph=vmin,
                min_speed_m=min_m,
                peak_brake=peak,
                severity=severity,
                support=len(onsets),
                cars=len(cars),
                onset_q25_m=None if q25 is None else q25 % length,
                onset_q75_m=None if q75 is None else q75 % length,
                corner=corner,
                complete=complete,
            )
        )
    zones.sort(key=lambda z: z.onset_m)
    return tuple(zones)


def _zone_corner(
    corners: tuple[Corner, ...], onset: float, end: float, min_m: float, length: float, bin_m: float
) -> str | None:
    """The provisional corner whose apex lies in the zone (onset .. a little past its end), nearest its minimum
    (constant-radius corners have a speed plateau, so the apex and the first minimum bin can differ)."""
    span = (end - onset) % length + 2 * bin_m
    inside = [c for c in corners if (c.apex_m - onset) % length <= span]
    if not inside:  # a plateau through a chicane can end the zone before the detector's apex: allow a short way on
        inside = [c for c in corners if abs(_signed(c.apex_m - min_m, length)) <= ZONE_CORNER_SLACK_M]
    if not inside:
        return None
    return min(inside, key=lambda c: abs(_signed(c.apex_m - min_m, length))).name


def _signed(delta: float, length: float) -> float:
    """``delta`` wrapped into [-length/2, length/2)."""
    return (delta + 0.5 * length) % length - 0.5 * length


def _zone_onsets(
    row_onsets: list[tuple[int, tuple[float, ...]]], lo_m: float, hi_m: float, length: float
) -> tuple[list[float], set[int]]:
    """Each car-lap's first own onset inside the cyclic window ``[lo_m, hi_m]`` (zone lookback .. minimum)."""
    span = (hi_m - lo_m) % length
    out: list[float] = []
    cars: set[int] = set()
    for car, onsets in row_onsets:
        best: float | None = None
        for o in onsets:
            k = (o - lo_m) % length
            if k <= span and (best is None or k < best):
                best = k
        if best is not None:
            out.append((lo_m + best) % length)
            cars.add(car)
    return out, cars


# ================================================================================================== corners
def _provisional_corners(snap: FieldSnapshot) -> tuple[Corner, ...]:
    """Speed minima of the median profile via the existing detector, renamed F1..Fn (layer L0b, positions only)."""
    if snap.coverage < CORNER_MIN_COVERAGE or not np.isfinite(snap.speed_kph).any():
        return ()
    try:
        model = build_track_model(
            snap.game,
            snap.track_id or "unknown",
            None,
            snap.track_length_m,
            [snap.distance_trace()],
        )
    except ValueError:
        return ()
    known = np.isfinite(snap.speed_kph)
    out: list[Corner] = []
    for c in model.corners:
        i = min(snap.n_bins - 1, max(0, int(c.apex_m / snap.bin_m)))
        near = [(i + k) % snap.n_bins for k in range(-2, 3)]
        if not known[near].all():
            continue  # a minimum at the edge of unknown data may be an artefact of the gap
        out.append(c)
    return tuple(replace(c, name=f"F{k + 1}") for k, c in enumerate(out))


# ================================================================================================== helpers
def _lap_time_s(speed_kph: FloatArray, bin_m: float) -> FloatArray:
    """Elapsed time at each bin centre from the median speed (NaN after the first unknown bin)."""
    v = speed_kph / 3.6
    with np.errstate(invalid="ignore", divide="ignore"):
        dt = np.where(np.isfinite(v) & (v > 1.0), bin_m / v, np.nan)
    t = np.concatenate([[0.0], np.cumsum(dt[:-1])])
    return t.astype(np.float64)


def _nanmedian_cols(stack: FloatArray) -> FloatArray:
    """Per-column median ignoring NaN; NaN (without a RuntimeWarning) where a column has no finite value."""
    out = np.full(stack.shape[1], np.nan)
    cols = np.isfinite(stack).any(axis=0)
    if cols.any():
        out[cols] = np.nanmedian(stack[:, cols], axis=0)
    return out


def _nanpercentile_cols(stack: FloatArray, qs: tuple[float, ...]) -> tuple[FloatArray, ...]:
    """``np.nanpercentile`` per column for each of ``qs``; NaN (without a warning) where a column has no data."""
    outs = [np.full(stack.shape[1], np.nan) for _ in qs]
    cols = np.isfinite(stack).any(axis=0)
    if cols.any():
        vals = np.nanpercentile(stack[:, cols], list(qs), axis=0)
        for o, v in zip(outs, vals, strict=True):
            o[cols] = v
    return tuple(outs)


def _r(v: float | None, nd: int) -> float | None:
    return None if v is None or not math.isfinite(v) else round(float(v), nd)


def _list(a: FloatArray, nd: int) -> list[float | None]:
    return [_r(float(v), nd) for v in a]
