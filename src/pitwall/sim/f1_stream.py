"""Generate a synthetic EA F1 25 UDP packet stream (SYNTHETIC - not real game output).

Every packet is encoded with the same ``StructDef`` layouts the decoder uses, so the stream exercises the
full replay -> decode -> analysis path. Synthetic captures validate our algorithms against known ground
truth; they are never evidence of compatibility with the real game.

Optional AI field (``F1Scenario.ai_cars``, layer L0b tests): synthetic AI cars drive their own laps of the same
track with known injected braking points (``GroundTruth.ai_brake_onsets_m``), and can be parked in the garage, do an
out lap or drive through the pit lane. Without AI cars the stream is byte-for-byte what it was before.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.structdef import StructDef
from pitwall.ingest.capture import CapturedPacket
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID
from pitwall.model.telemetry import FracZone, MarshalZone, TrackZones
from pitwall.sim.driver import CornerDeviation, DriverProfile, LapProfile, VehicleModel, solve_lap
from pitwall.sim.track import TrackGeometry, pitwall_park

PLAYER = 0
GARAGE_LAP_DISTANCE_M = -500.0  # synthetic garage cars sit far before the line (cf. third-party F1 clips)
GARAGE_POS = (0.0, 0.0, -60.0)  # synthetic pit box (x, y, z)
GROUND_TRUTH_BRAKE_ON = 0.10  # same pedal threshold as analysis.braking / analysis.field_model
GROUND_TRUTH_THROTTLE = 0.6


@dataclass(slots=True)
class AiCarSpec:
    """One synthetic AI car of the field (SYNTHETIC). It drives its own laps of the scenario's track.

    Before ``start_s`` (session time at which it crosses the line to begin lap 1) and after its ``laps`` it sits in
    the garage (driverStatus 0, pit area, large negative lap distance). ``out_lap`` makes lap 1 an out lap
    (driverStatus 3); out laps and ``pit_laps`` (driven through the pit lane: pitStatus 1) use ``slow_driver``, so a
    field model that failed to filter them would visibly move its braking points. ``garage_only`` never leaves.
    """

    index: int  # car slot, never the player's (0)
    driver: DriverProfile = field(default_factory=DriverProfile)
    start_s: float = 0.0
    laps: int | None = None  # None: keep lapping until the session ends
    out_lap: bool = False
    pit_laps: frozenset[int] = frozenset()
    slow_driver: DriverProfile | None = None  # out laps / pit laps; default brakes 80 m early everywhere
    garage_only: bool = False
    ai_controlled: bool = True
    gap_ahead_ms: int = 0  # LapData deltaToCarInFront (0 = not reported)
    lap_index_seed: int = 0  # varies solve_lap's per-lap noise between cars


@dataclass(slots=True)
class FlashbackSpec:
    lap: int  # lap number (1-based) during which the flashback happens
    at_fraction: float  # fraction of that lap at which the driver rewinds
    rewind_s: float = 4.0


@dataclass(slots=True)
class F1Scenario:
    laps: int = 5
    rate_hz: int = 60
    driver_by_lap: dict[int, DriverProfile] = field(default_factory=dict)  # lap number -> profile
    default_driver: DriverProfile = field(default_factory=DriverProfile)
    invalid_laps: frozenset[int] = frozenset()
    flashback: FlashbackSpec | None = None
    session_uid: int = SYNTHETIC_SESSION_UID
    team_id: int = 8
    track_id: int = -1  # -1 = unknown in the EA spec; synthetic geometry must not masquerade as a real track
    session_type: int = 1  # Practice 1
    fuel_start_kg: float = 40.0
    fuel_per_lap_kg: float = 1.6
    wear_per_lap_pct: tuple[float, float, float, float] = (1.9, 2.1, 1.4, 1.5)  # FL, FR, RL, RR
    start_ns: int = 1_000_000_000_000
    seed: int = 7
    packet_format: int = 2025  # 2025 (F1 25) or 2026 (2026 Season Pack layout)
    ai_cars: tuple[AiCarSpec, ...] = ()  # synthetic AI field (layer L0b tests); empty = player only
    # --- feat/technique: optional MotionEx (ID 13) with real-game signs, and the ABS assist flag (both off by
    # default, so existing scenarios stream exactly what they did before) ---
    motion_ex: bool = False
    abs_on: bool = False

    @property
    def layout(self) -> P.F1Layout:
        return P.LAYOUTS[self.packet_format]


@dataclass(slots=True)
class GroundTruth:
    """What the generator actually did, for test assertions."""

    lap_times_ms: dict[int, int] = field(default_factory=dict)
    profiles: dict[int, LapProfile] = field(default_factory=dict)
    track: TrackGeometry | None = None
    track_zones: TrackZones | None = None  # the skeleton written into every Session packet (SYNTHETIC)
    # AI field: car index -> lap -> design corner -> braking onset (lap distance, m) actually driven
    ai_brake_onsets_m: dict[int, dict[int, dict[str, float]]] = field(default_factory=dict)
    ai_lap_kinds: dict[int, dict[int, str]] = field(default_factory=dict)  # car -> lap -> "flying" | "out" | "pit"


def _hdr(pid: P.PacketId, sc: F1Scenario, session_time: float, frame: int, overall: int) -> bytes:
    return P.HEADER.pack(
        {
            "packetFormat": sc.packet_format,
            "gameYear": 25,
            "gameMajorVersion": 1,
            "gameMinorVersion": 0,
            "packetVersion": 1,
            "packetId": int(pid),
            "sessionUID": sc.session_uid,
            "sessionTime": session_time,
            "frameIdentifier": frame,
            "overallFrameIdentifier": overall,
            "playerCarIndex": PLAYER,
            "secondaryPlayerCarIndex": 255,
        }
    )


def _cars(
    struct_def: StructDef,
    player_values: Mapping[str, object],
    n_cars: int,
    others: Mapping[int, Mapping[str, object]] | None = None,
) -> bytes:
    empty = struct_def.pack({})
    if not others:
        return struct_def.pack(player_values) + empty * (n_cars - 1)
    out = [struct_def.pack(player_values)] + [empty] * (n_cars - 1)
    for i, values in others.items():
        out[i] = struct_def.pack(values)
    return b"".join(out)


def brake_onsets(prof: LapProfile, track: TrackGeometry) -> dict[str, float]:
    """Ground truth: where ``prof`` starts braking for each design corner - the ``GROUND_TRUTH_BRAKE_ON`` rising
    crossing after a throttle phase, interpolated on the 1 m profile grid, between the end of the previous corner's
    arc and the middle of this one (cyclic: a zone may start before the line). Corners taken without braking (fast
    sweepers) are left out."""
    out: dict[str, float] = {}
    length = track.length_m
    s2 = np.concatenate([prof.s - length, prof.s])  # previous lap, then this lap: windows may run through the line
    b2 = np.concatenate([prof.brake, prof.brake])
    t2 = np.concatenate([prof.throttle, prof.throttle])
    corners = sorted(track.corners, key=lambda c: c[1])
    for k, (name, start, end) in enumerate(corners):
        prev_end = corners[k - 1][2] - (length if k == 0 else 0.0)
        lo = int(np.searchsorted(s2, prev_end))
        hi = int(np.searchsorted(s2, (start + end) / 2))
        armed = False
        found: float | None = None
        for i in range(max(1, lo), hi):
            if t2[i] >= GROUND_TRUTH_THROTTLE and b2[i] < 0.05:
                armed = True
            elif armed and b2[i] >= GROUND_TRUTH_BRAKE_ON > b2[i - 1]:
                w = (GROUND_TRUTH_BRAKE_ON - b2[i - 1]) / (b2[i] - b2[i - 1])
                found = float(s2[i - 1] + w * (s2[i] - s2[i - 1]))
                armed = False
        if found is not None:
            out[name] = found % length
    return out


@dataclass(slots=True)
class _AiCar:
    spec: AiCarSpec
    lap_starts: list[float]  # session time each lap starts
    profiles: list[LapProfile]
    kinds: list[str]  # "flying" | "out" | "pit"

    @property
    def end_s(self) -> float:
        return self.lap_starts[-1] + self.profiles[-1].lap_time_s if self.profiles else self.spec.start_s


def _plan_ai(sc: F1Scenario, track: TrackGeometry, vehicle: VehicleModel, session_end: float) -> list[_AiCar]:
    cars: list[_AiCar] = []
    for spec in sc.ai_cars:
        if spec.index == PLAYER or not 0 <= spec.index < sc.layout.max_cars:
            raise ValueError(f"AI car index {spec.index} must be another slot than the player's")
        slow = spec.slow_driver or DriverProfile(
            deviations={name: CornerDeviation(brake_early_m=80.0) for name, _, _ in track.corners}
        )
        starts: list[float] = []
        profiles: list[LapProfile] = []
        kinds: list[str] = []
        t = spec.start_s
        lap = 1
        while not spec.garage_only and t < session_end and (spec.laps is None or lap <= spec.laps):
            kind = "out" if spec.out_lap and lap == 1 else "pit" if lap in spec.pit_laps else "flying"
            driver = spec.driver if kind == "flying" else slow
            prof = solve_lap(track, vehicle, driver, lap_index=1000 * spec.index + spec.lap_index_seed + lap)
            starts.append(t)
            profiles.append(prof)
            kinds.append(kind)
            t += prof.lap_time_s
            lap += 1
        cars.append(_AiCar(spec, starts, profiles, kinds))
    return cars


def _ai_values(
    car: _AiCar, t: float, track: TrackGeometry, layout: P.F1Layout
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """(motion, lap data, telemetry) values of one AI car at session time ``t``."""
    spec = car.spec
    gap = {
        "deltaToCarInFrontMSPart": spec.gap_ahead_ms % 60000,
        "deltaToCarInFrontMinutesPart": spec.gap_ahead_ms // 60000,
    }
    if not car.profiles or t < car.lap_starts[0] or t >= car.end_s:
        x, y, z = GARAGE_POS
        lap_num = 1 if not car.profiles or t < car.lap_starts[0] else len(car.profiles) + 1
        motion: dict[str, object] = {"worldPositionX": x, "worldPositionY": y, "worldPositionZ": z}
        lapdata: dict[str, object] = {
            "lapDistance": GARAGE_LAP_DISTANCE_M,
            "currentLapNum": lap_num,
            "carPosition": spec.index + 1,
            "pitStatus": 2,
            "driverStatus": 0,
            "resultStatus": 2,
            **gap,
        }
        idle: dict[str, object] = {"speed": 0, "gear": 0, "engineRPM": 4000}
        return motion, lapdata, idle
    k = int(np.searchsorted(car.lap_starts, t, side="right")) - 1
    prof = car.profiles[k]
    lap_t = t - car.lap_starts[k]
    i = max(0, min(int(np.searchsorted(prof.t, lap_t, side="right")) - 1, len(prof.t) - 1))
    j = min(i + 1, len(prof.t) - 1)
    seg = prof.t[j] - prof.t[i]
    w = (lap_t - prof.t[i]) / seg if j != i and seg > 0 else 0.0

    def lerp(arr: npt.NDArray[np.float64]) -> float:
        return float(arr[i] * (1 - w) + arr[j] * w)

    s = lerp(prof.s)
    v = lerp(prof.v)
    heading = float(np.interp(s, track.s, track.heading))
    g_lon = lerp(prof.g_lon)
    g_lat = lerp(prof.g_lat)
    quantise = layout.gforce_scale != 1.0
    kind = car.kinds[k]
    motion = {
        "worldPositionX": float(np.interp(s, track.s, track.x)),
        "worldPositionY": 0.0,
        "worldPositionZ": float(np.interp(s, track.s, track.z)),
        "worldVelocityX": v * math.sin(heading),
        "worldVelocityZ": v * math.cos(heading),
        "worldForwardDirX": int(32767 * math.sin(heading)),
        "worldForwardDirZ": int(32767 * math.cos(heading)),
        "gForceLateral": round(g_lat * 1000) if quantise else g_lat,
        "gForceLongitudinal": round(g_lon * 1000) if quantise else g_lon,
        "yaw": heading,
    }
    lapdata = {
        "currentLapTimeInMS": int(lap_t * 1000),
        "lapDistance": s,
        "totalDistance": k * track.length_m + s,
        "carPosition": spec.index + 1,
        "currentLapNum": k + 1,
        "sector": 0 if s < track.length_m / 3 else (1 if s < 2 * track.length_m / 3 else 2),
        "pitStatus": 1 if kind == "pit" else 0,
        "driverStatus": 3 if kind == "out" else 1,
        "resultStatus": 2,
        **gap,
    }
    telem: dict[str, object] = {
        "speed": round(v * 3.6),
        "throttle": lerp(prof.throttle),
        "steer": lerp(prof.steering),
        "brake": lerp(prof.brake),
        "gear": int(prof.gear[i]),
        "engineRPM": int(lerp(prof.rpm)),
    }
    return motion, lapdata, telem


def _rl_rr_fl_fr(fl: float, fr: float, rl: float, rr: float) -> tuple[float, float, float, float]:
    return (rl, rr, fl, fr)


SYNTHETIC_MARSHAL_ZONES = 12
DRS_ACTIVATION_AFTER_EXIT_M = 60.0  # synthetic rule: zones open this far after a corner exit ...
DRS_END_BEFORE_ENTRY_M = 120.0  # ... and close this far before the next corner
AERO_MIN_STRAIGHT_M = 300.0  # synthetic rule: every straight at least this long gets a "full" aero zone


def synthetic_track_zones(track: TrackGeometry, packet_format: int = P.PACKET_FORMAT_2025) -> TrackZones:
    """A plausible, clearly SYNTHETIC skeleton for a generated track (never a real circuit's data).

    * Sectors at L/3 and 2L/3, matching the ``sector`` field the LapData generator writes.
    * 12 evenly spaced marshal zones in game order with zone 0 starting just before the line, so it wraps through
      the line exactly like real F1 25 Austria (zone 0 at 0.9908).
    * Format 2026 only: DRS zones on the two longest straights, "full" active-aero zones on every straight of at
      least 300 m, "partial" ones on the two longest. Straights are the gaps between the track's arcs (cyclic), so on
      Pitwall Park the main straight's zones run through the line and exercise wrap handling.
    """
    length = track.length_m
    n = SYNTHETIC_MARSHAL_ZONES
    marshal = tuple(MarshalZone(start_frac=((k - 0.25) / n) % 1.0, flag="none") for k in range(n))
    drs: tuple[FracZone, ...] | None = None
    full: tuple[FracZone, ...] | None = None
    partial: tuple[FracZone, ...] | None = None
    if packet_format >= P.PACKET_FORMAT_2026:
        corners = sorted(track.corners, key=lambda c: c[1])
        straights = [  # (length, exit of corner k, entry of corner k+1), cyclic
            ((corners[(k + 1) % len(corners)][1] - c[2]) % length, c[2], corners[(k + 1) % len(corners)][1])
            for k, c in enumerate(corners)
        ]

        def zone(exit_m: float, entry_m: float, open_after_m: float = DRS_ACTIVATION_AFTER_EXIT_M) -> FracZone:
            a = ((exit_m + open_after_m) % length) / length
            b = ((entry_m - DRS_END_BEFORE_ENTRY_M) % length) / length
            return (round(a, 6), round(b, 6))

        longest = sorted(sorted(straights, reverse=True)[:2], key=lambda s: s[1])
        drs = tuple(zone(x, e) for _, x, e in longest)
        full = tuple(zone(x, e) for ln, x, e in straights if ln >= AERO_MIN_STRAIGHT_M)
        partial = tuple(zone(x, e, open_after_m=2 * DRS_ACTIVATION_AFTER_EXIT_M) for _, x, e in longest)
    return TrackZones(
        source=f"f1_session@{packet_format}",
        sector2_start_m=length / 3,
        sector3_start_m=2 * length / 3,
        marshal_zones=marshal,
        drs_zones_frac=drs,
        aero_full_zones_frac=full,
        aero_partial_zones_frac=partial,
        active_aero_track_status="full" if packet_format >= P.PACKET_FORMAT_2026 else None,
    )


_MARSHAL_FLAG_CODES = {"none": 0, "green": 1, "blue": 2, "yellow": 3}


def _flat_pairs(zones: tuple[FracZone, ...] | None, max_count: int) -> list[float]:
    flat = [v for pair in (zones or ())[:max_count] for v in pair]
    return flat + [0.0] * (2 * max_count - len(flat))


def _session_packet(
    sc: F1Scenario, track: TrackGeometry, st: float, frame: int, overall: int, zones: TrackZones | None = None
) -> bytes:
    zones = zones or synthetic_track_zones(track, sc.packet_format)
    marshal = (zones.marshal_zones or ())[: P.NUM_MARSHAL_ZONES]
    head = P.SESSION_HEAD.pack(
        {
            "weather": 0,
            "trackTemperature": 32,
            "airTemperature": 24,
            "totalLaps": sc.laps,
            "trackLength": round(track.length_m),
            "sessionType": sc.session_type,
            "trackId": sc.track_id,
            "formula": 0,
            "sessionTimeLeft": 3600,
            "sessionDuration": 3600,
            "pitSpeedLimit": 80,
            "numMarshalZones": len(marshal),
        }
    )
    marshal_bytes = b"".join(
        P.MARSHAL_ZONE.pack({"zoneStart": z.start_frac, "zoneFlag": _MARSHAL_FLAG_CODES.get(z.flag or "", -1)})
        for z in marshal
    ) + P.MARSHAL_ZONE.pack({}) * (P.NUM_MARSHAL_ZONES - len(marshal))
    mid = P.SESSION_MID.pack({"numWeatherForecastSamples": 1})
    fc = P.WEATHER_FORECAST_SAMPLE.pack(
        {"sessionType": sc.session_type, "weather": 0, "trackTemperature": 32, "airTemperature": 24}
    ) + P.WEATHER_FORECAST_SAMPLE.pack({}) * (P.NUM_WEATHER_SAMPLES - 1)
    tail_values: dict[str, object] = {
        "sector2LapDistanceStart": zones.sector2_start_m or 0.0,
        "sector3LapDistanceStart": zones.sector3_start_m or 0.0,
        "brakingAssist": 0,
        "dynamicRacingLine": 0,
    }
    if "numDRSZones" in dict(sc.layout.session_tail.fields):  # format 2026 tail
        full, partial, drs = zones.aero_full_zones_frac, zones.aero_partial_zones_frac, zones.drs_zones_frac
        tail_values |= {
            "activeAeroTrackStatus": 1 if zones.active_aero_track_status == "partial" else 0,
            "numActiveAeroZonesFull": min(len(full or ()), P.NUM_ACTIVE_AERO_ZONES),
            "activeAeroZonesFull": _flat_pairs(full, P.NUM_ACTIVE_AERO_ZONES),
            "numActiveAeroZonesPartial": min(len(partial or ()), P.NUM_ACTIVE_AERO_ZONES),
            "activeAeroZonesPartial": _flat_pairs(partial, P.NUM_ACTIVE_AERO_ZONES),
            "numDRSZones": min(len(drs or ()), P.NUM_DRS_ZONES),
            "drsZones": _flat_pairs(drs, P.NUM_DRS_ZONES),
        }
    tail = sc.layout.session_tail.pack(tail_values)
    return _hdr(P.PacketId.SESSION, sc, st, frame, overall) + head + marshal_bytes + mid + fc + tail


def _participants_packet(sc: F1Scenario, st: float, frame: int, overall: int) -> bytes:
    others: dict[int, Mapping[str, object]] = {
        a.index: {
            "aiControlled": int(a.ai_controlled),
            "name": b"SYNTHETIC AI",
            "platform": 255,
            "teamId": a.index % 10,
        }
        for a in sc.ai_cars
    }
    n_active = 1 + (max(others) if others else 0)
    body = P.PARTICIPANTS_HEAD.pack({"numActiveCars": n_active}) + _cars(
        sc.layout.participant,
        {"teamId": sc.team_id, "name": b"SYNTHETIC", "platform": 255, "aiControlled": 0, "raceNumber": 4},
        sc.layout.max_cars,
        others,
    )
    return _hdr(P.PacketId.PARTICIPANTS, sc, st, frame, overall) + body


def _setups_packet(sc: F1Scenario, st: float, frame: int, overall: int) -> bytes:
    setup = {
        "frontWing": 25,
        "rearWing": 22,
        "onThrottle": 60,
        "offThrottle": 50,
        "frontCamber": -3.0,
        "rearCamber": -1.5,
        "frontToe": 0.05,
        "rearToe": 0.2,
        "frontSuspension": 20,
        "rearSuspension": 10,
        "frontAntiRollBar": 10,
        "rearAntiRollBar": 8,
        "frontSuspensionHeight": 30,
        "rearSuspensionHeight": 60,
        "brakePressure": 100,
        "brakeBias": 56,
        "engineBraking": 50,
        "rearLeftTyrePressure": 21.5,
        "rearRightTyrePressure": 21.5,
        "frontLeftTyrePressure": 23.0,
        "frontRightTyrePressure": 23.0,
        "ballast": 6,
        "fuelLoad": sc.fuel_start_kg,
    }
    body = _cars(P.CAR_SETUP, setup, sc.layout.max_cars) + P.CAR_SETUPS_TAIL.pack({"nextFrontWingValue": 25.0})
    return _hdr(P.PacketId.CAR_SETUPS, sc, st, frame, overall) + body


def _event_packet(sc: F1Scenario, code: str, details: bytes, st: float, frame: int, overall: int) -> bytes:
    details = details.ljust(P.EVENT_DETAILS_SIZE, b"\x00")
    return _hdr(P.PacketId.EVENT, sc, st, frame, overall) + code.encode() + details


# --- feat/technique: MotionEx with injected technique deviations (SYNTHETIC) ------------------------------------
TECH_LINE_FULL_M = 40.0  # line offset is full within apex +/- 40 m ...
TECH_LINE_FADE_M = 120.0  # ... and fades out (raised cosine) by apex +/- 120 m
TECH_PHASE_SPAN_M = 200.0
TECH_PHASE_MARGIN_M = 3.0  # understeer regions stay this far inside the analysis' phase boundaries
TECH_LOCK_SLIP = -0.35
TECH_SPIN_SLIP = 0.30


@dataclass(slots=True)
class _CornerInjection:
    """Where one design corner's technique deviations apply on one lap (distance along the lap / lap time)."""

    mid_s: float
    kappa_sign: float
    line_offset_m: float
    understeer: tuple[tuple[float, float, float], ...]  # (from s, to s, extra front slip angle in degrees)
    lock: tuple[float, float] | None  # lap-time window of the front-left lock
    spin: tuple[float, float, float, bool] | None  # exit window (lap time): from, to, body slip (deg), wheelspin


def _technique_plan(prof: LapProfile, track: TrackGeometry, driver: DriverProfile) -> list[_CornerInjection]:
    out: list[_CornerInjection] = []
    for name, start, end in track.corners:
        dev = driver.deviations.get(name)
        if dev is None or not (
            dev.line_offset_m or any(dev.understeer_deg) or dev.lockup_s or dev.wheelspin_s or dev.body_slip_exit_deg
        ):
            continue
        mid = (start + end) / 2
        ksign = 1.0 if float(np.interp(mid, track.s, track.curvature)) >= 0 else -1.0
        half = max(10.0, 0.5 * float(np.interp(mid, prof.s, prof.v)))
        m = TECH_PHASE_MARGIN_M
        en, mi, ex = dev.understeer_deg
        regions = tuple(
            r
            for r in (
                (mid - TECH_PHASE_SPAN_M, mid - half - m, en),
                (mid - half + m, mid + half - m, mi),
                (mid + half + m, mid + TECH_PHASE_SPAN_M, ex),
            )
            if r[2]
        )
        lock = None
        if dev.lockup_s:
            idx = np.flatnonzero((prof.s >= start - 400) & (prof.s <= mid) & (prof.brake >= 0.10))
            if len(idx):
                t_on = float(prof.t[idx[0]])
                lock = (t_on + 0.2, t_on + 0.2 + dev.lockup_s)
        spin = None
        if dev.wheelspin_s or dev.body_slip_exit_deg:
            idx = np.flatnonzero((prof.s >= mid + half + 5) & (prof.throttle >= 0.2))
            if len(idx):
                t0 = float(prof.t[idx[0]])
                spin = (t0, t0 + (dev.wheelspin_s or 0.3), dev.body_slip_exit_deg, dev.wheelspin_s > 0)
        out.append(_CornerInjection(mid, ksign, dev.line_offset_m, regions, lock, spin))
    return out


def _line_weight(ds: float) -> float:
    a = abs(ds)
    if a <= TECH_LINE_FULL_M:
        return 1.0
    if a >= TECH_LINE_FADE_M:
        return 0.0
    return 0.5 * (1 + math.cos(math.pi * (a - TECH_LINE_FULL_M) / (TECH_LINE_FADE_M - TECH_LINE_FULL_M)))


def _motion_ex_values(
    plan: list[_CornerInjection],
    s: float,
    lap_t: float,
    v: float,
    kappa: float,
    g_lat: float,
    brake: float,
    throttle: float,
) -> dict[str, object]:
    """MotionEx of the player car (real-game signs: angularVelocityY = -v * curvature, i.e. negative turning right;
    RL, RR, FL, FR wheel order). Base model: rear slip angle 0.5 deg per g, fronts 1 deg more (neutral)."""
    us = 0.0
    lock = False
    spin = False
    beta_deg = 0.0
    for inj in plan:
        for lo, hi, deg in inj.understeer:
            if lo <= s <= hi:
                us += deg
        if inj.lock is not None and inj.lock[0] <= lap_t <= inj.lock[1] and brake >= 0.05:
            lock = True
        if inj.spin is not None and inj.spin[0] <= lap_t <= inj.spin[1]:
            spin = spin or inj.spin[3]
            beta_deg = inj.spin[2]
    sign = 1.0 if kappa >= 0 else -1.0
    alpha_r = math.radians(0.5 * abs(g_lat))
    alpha_f = alpha_r + math.radians(1.0 + us)
    sr_f = -0.05 * brake
    sr_r = 0.04 * throttle
    fl = TECH_LOCK_SLIP if lock else sr_f
    rl = rr = TECH_SPIN_SLIP if spin else sr_r
    sr = (fl, sr_f, rl, rr)  # FL, FR, RL, RR
    beta = sign * math.radians(beta_deg)  # tail out: same sign as the rotation (as recorded on real F1 25 slides)
    return {
        "wheelSlipRatio": list(_rl_rr_fl_fr(*sr)),
        "wheelSlipAngle": list(_rl_rr_fl_fr(sign * alpha_f, sign * alpha_f, sign * alpha_r, sign * alpha_r)),
        "wheelSpeed": list(_rl_rr_fl_fr(*(v * (1 + x) for x in sr))),
        "localVelocityX": v * math.tan(beta),
        "localVelocityZ": v,
        "angularVelocityY": -v * kappa,
        "chassisYaw": beta,
    }


# --- end feat/technique ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Timeline:
    """Continuous driving timeline across laps, sampled by session time."""

    lap_starts: list[float]
    profiles: list[LapProfile]
    track: TrackGeometry
    plans: list[list[_CornerInjection]] = field(default_factory=list)  # feat/technique: per lap (motion_ex only)

    def at(self, t: float) -> tuple[int, float, int]:
        """Return (lap_number 1-based, lap time s, index into the profile grid) at session time t."""
        k = int(np.searchsorted(self.lap_starts, t, side="right")) - 1
        k = max(0, min(k, len(self.profiles) - 1))
        lap_t = t - self.lap_starts[k]
        prof = self.profiles[k]
        i = int(np.searchsorted(prof.t, lap_t, side="right")) - 1
        return k + 1, lap_t, max(0, min(i, len(prof.t) - 1))


def generate_f1_session(
    sc: F1Scenario | None = None,
    track: TrackGeometry | None = None,
    vehicle: VehicleModel | None = None,
) -> tuple[list[CapturedPacket], GroundTruth]:
    sc = sc or F1Scenario()
    track = track or pitwall_park()
    vehicle = vehicle or VehicleModel()
    truth = GroundTruth(track=track, track_zones=synthetic_track_zones(track, sc.packet_format))
    profiles: list[LapProfile] = []
    for lap in range(1, sc.laps + 1):
        prof = solve_lap(track, vehicle, sc.driver_by_lap.get(lap, sc.default_driver), lap_index=lap)
        profiles.append(prof)
        truth.profiles[lap] = prof
        truth.lap_times_ms[lap] = round(prof.lap_time_s * 1000)
    starts = np.concatenate([[0.0], np.cumsum([p.lap_time_s for p in profiles])])
    tl = _Timeline(lap_starts=list(starts[:-1]), profiles=profiles, track=track)
    if sc.motion_ex:  # feat/technique
        tl.plans = [
            _technique_plan(prof, track, sc.driver_by_lap.get(lap, sc.default_driver))
            for lap, prof in enumerate(profiles, start=1)
        ]
    ai = _plan_ai(sc, track, vehicle, float(starts[-1]))
    for car in ai:
        truth.ai_brake_onsets_m[car.spec.index] = {
            lap: brake_onsets(prof, track) for lap, prof in enumerate(car.profiles, start=1)
        }
        truth.ai_lap_kinds[car.spec.index] = dict(enumerate(car.kinds, start=1))
    return list(_stream(sc, tl, truth, starts, ai)), truth


def _stream(
    sc: F1Scenario, tl: _Timeline, truth: GroundTruth, starts: np.ndarray, ai: list[_AiCar] | None = None
) -> Iterator[CapturedPacket]:
    ai = ai or []
    track = tl.track
    rng = np.random.default_rng(sc.seed)
    dt = 1.0 / sc.rate_hz
    session_end = float(starts[-1])
    frame = 0
    overall = 0
    wall = float(sc.start_ns)
    t = 0.0
    fb = sc.flashback
    fb_time = (starts[fb.lap - 1] + fb.at_fraction * tl.profiles[fb.lap - 1].lap_time_s) if fb else None
    fb_done = False
    frame_at_time: dict[int, int] = {}
    last_slow = -1.0
    last_damage = -1.0
    last_part = -10.0

    def pkt(data: bytes, offset_us: float = 0.0) -> CapturedPacket:
        return CapturedPacket(int(wall + offset_us * 1000), 20777, data)

    yield pkt(_participants_packet(sc, 0.0, 0, 0))
    yield pkt(_session_packet(sc, track, 0.0, 0, 0, truth.track_zones), 50)
    yield pkt(_event_packet(sc, "SSTA", b"", 0.0, 0, 0), 100)

    while t < session_end - 1e-9:
        if fb_time is not None and not fb_done and t >= fb_time:
            # Driver rewinds: game emits FLBK, then the stream resumes from an earlier frame/session time.
            fb_done = True
            target_t = t - (fb.rewind_s if fb else 0.0)
            target_frame = frame_at_time.get(round(target_t * sc.rate_hz), max(0, frame - 240))
            details = P.EVENT_DETAILS["FLBK"].pack(
                {"flashbackFrameIdentifier": target_frame, "flashbackSessionTime": target_t}
            )
            yield pkt(_event_packet(sc, "FLBK", details, t, frame, overall))
            wall += 2.5e9  # time spent in the flashback menu
            t = target_t
            frame = target_frame
            continue

        lap, lap_t, i = tl.at(t)
        prof = tl.profiles[lap - 1]
        # interpolate within the 1 m grid for smooth values
        if i + 1 < len(prof.t):
            seg = prof.t[i + 1] - prof.t[i]
            w = (lap_t - prof.t[i]) / seg if seg > 0 else 0.0
        else:
            w = 0.0
        j = min(i + 1, len(prof.t) - 1)

        def lerp(arr: npt.NDArray[np.float64], i: int = i, j: int = j, w: float = w) -> float:
            return float(arr[i] * (1 - w) + arr[j] * w)

        s = lerp(prof.s) if j != i else float(prof.s[i])
        v = lerp(prof.v)
        x = float(np.interp(s, track.s, track.x))
        z = float(np.interp(s, track.s, track.z))
        heading = float(np.interp(s, track.s, track.heading))
        plan = tl.plans[lap - 1] if tl.plans else []  # feat/technique: line offset towards the outside
        for inj in plan:
            if inj.line_offset_m:
                off = inj.line_offset_m * _line_weight(s - inj.mid_s)
                # right normal of heading h (0 = +z, clockwise) is (cos h, -sin h); the outside is opposite the turn
                x -= inj.kappa_sign * off * math.cos(heading)
                z += inj.kappa_sign * off * math.sin(heading)
        throttle = lerp(prof.throttle)
        brake = lerp(prof.brake)
        steer = lerp(prof.steering)
        gear = int(prof.gear[i])
        rpm = lerp(prof.rpm)
        g_lat = lerp(prof.g_lat)
        g_lon = lerp(prof.g_lon)

        laps_done = lap - 1 + s / track.length_m
        fuel = sc.fuel_start_kg - sc.fuel_per_lap_kg * laps_done
        wear = [w_ * laps_done for w_ in sc.wear_per_lap_pct]
        load = abs(g_lat) + abs(g_lon)
        tyre_surf = [88 + 6 * load + rng.normal(0, 0.4) for _ in range(4)]
        tyre_inner = [96 + 2 * load for _ in range(4)]
        brake_temp = [350 + 550 * brake for _ in range(4)]
        sector = 0 if s < track.length_m / 3 else (1 if s < 2 * track.length_m / 3 else 2)
        prev_ms = truth.lap_times_ms.get(lap - 1, 0)
        s1_ms = round(float(np.interp(track.length_m / 3, prof.s, prof.t)) * 1000) if sector >= 1 else 0
        s2_ms = round(float(np.interp(2 * track.length_m / 3, prof.s, prof.t)) * 1000) - s1_ms if sector >= 2 else 0
        frame_at_time[round(t * sc.rate_hz)] = frame

        L = sc.layout
        quantise = L.gforce_scale != 1.0
        ai_motion: dict[int, Mapping[str, object]] = {}
        ai_lap: dict[int, Mapping[str, object]] = {}
        ai_tel: dict[int, Mapping[str, object]] = {}
        for car in ai:
            ai_motion[car.spec.index], ai_lap[car.spec.index], ai_tel[car.spec.index] = _ai_values(car, t, track, L)

        def gq(g: float, quantise: bool = quantise) -> float | int:
            return round(g * 1000) if quantise else g  # format 2026 sends int16 thousandths of g

        motion = _cars(
            L.car_motion,
            {
                "worldPositionX": x,
                "worldPositionY": 0.0,
                "worldPositionZ": z,
                "worldVelocityX": v * math.sin(heading),
                "worldVelocityZ": v * math.cos(heading),
                "worldForwardDirX": int(32767 * math.sin(heading)),
                "worldForwardDirZ": int(32767 * math.cos(heading)),
                "gForceLateral": gq(g_lat),
                "gForceLongitudinal": gq(g_lon),
                "gForceVertical": gq(1.0),
                "yaw": heading,
            },
            L.max_cars,
            ai_motion,
        )
        lapdata = _cars(
            P.LAP_DATA,
            {
                "lastLapTimeInMS": prev_ms,
                "currentLapTimeInMS": int(lap_t * 1000),
                "sector1TimeMSPart": s1_ms % 60000,
                "sector1TimeMinutesPart": s1_ms // 60000,
                "sector2TimeMSPart": s2_ms % 60000,
                "sector2TimeMinutesPart": s2_ms // 60000,
                "lapDistance": s,
                "totalDistance": (lap - 1) * track.length_m + s,
                "carPosition": 1,
                "currentLapNum": lap,
                "sector": sector,
                "currentLapInvalid": 1 if lap in sc.invalid_laps else 0,
                "driverStatus": 1,
                "resultStatus": 2,
            },
            L.max_cars,
            ai_lap,
        ) + P.LAP_DATA_TAIL.pack({"timeTrialPBCarIdx": 255, "timeTrialRivalCarIdx": 255})
        telem = _cars(
            L.car_telemetry,
            {
                "speed": round(v * 3.6),
                "throttle": throttle,
                "steer": steer,
                "brake": brake,
                "clutch": 0,
                "gear": gear,
                "engineRPM": int(rpm),
                "drs": 0,
                "revLightsPercent": int(100 * (rpm - 4000) / 8500),
                "brakesTemperature": [int(b) for b in _rl_rr_fl_fr(*brake_temp)],
                "tyresSurfaceTemperature": [int(v_) for v_ in _rl_rr_fl_fr(*tyre_surf)],
                "tyresInnerTemperature": [int(v_) for v_ in _rl_rr_fl_fr(*tyre_inner)],
                "engineTemperature": 105,
                "tyresPressure": list(_rl_rr_fl_fr(23.6, 23.6, 22.1, 22.1)),
                "surfaceType": [0, 0, 0, 0],
            },
            L.max_cars,
            ai_tel,
        ) + P.CAR_TELEMETRY_TAIL.pack({"mfdPanelIndex": 255, "mfdPanelIndexSecondaryPlayer": 255, "suggestedGear": 0})
        status = _cars(
            L.car_status,
            {
                "tractionControl": 0,
                "antiLockBrakes": 1 if sc.abs_on else 0,
                "fuelMix": 1,
                "frontBrakeBias": 56,
                "fuelInTank": fuel,
                "fuelCapacity": 110.0,
                "fuelRemainingLaps": fuel / sc.fuel_per_lap_kg,
                "maxRPM": 12500,
                "idleRPM": 4000,
                "maxGears": 8,
                "actualTyreCompound": 18,
                "visualTyreCompound": 16,
                "tyresAgeLaps": lap - 1,
                "ersStoreEnergy": 3.0e6,
                "ersDeployMode": 1,
            },
            L.max_cars,
        )
        yield pkt(_hdr(P.PacketId.MOTION, sc, t, frame, overall) + motion)
        if sc.motion_ex:  # feat/technique
            ex = _motion_ex_values(
                plan, s, lap_t, v, float(np.interp(s, track.s, track.curvature)), g_lat, brake, throttle
            )
            yield pkt(_hdr(P.PacketId.MOTION_EX, sc, t, frame, overall) + P.MOTION_EX.pack(ex), 20)
        yield pkt(_hdr(P.PacketId.LAP_DATA, sc, t, frame, overall) + lapdata, 40)
        yield pkt(_hdr(P.PacketId.CAR_TELEMETRY, sc, t, frame, overall) + telem, 80)
        yield pkt(_hdr(P.PacketId.CAR_STATUS, sc, t, frame, overall) + status, 120)
        if t - last_damage >= 0.1 or t < last_damage:
            last_damage = t
            dmg = _cars(P.CAR_DAMAGE, {"tyresWear": list(_rl_rr_fl_fr(*wear))}, L.max_cars)
            yield pkt(_hdr(P.PacketId.CAR_DAMAGE, sc, t, frame, overall) + dmg, 160)
        if t - last_slow >= 0.5 or t < last_slow:
            last_slow = t
            yield pkt(_session_packet(sc, track, t, frame, overall, truth.track_zones), 200)
            yield pkt(_setups_packet(sc, t, frame, overall), 240)
        if t - last_part >= 5.0 or t < last_part:
            last_part = t
            yield pkt(_participants_packet(sc, t, frame, overall), 280)

        frame += 1
        overall += 1
        t += dt
        wall += dt * 1e9

    # final crossing of the line: one LapData frame on lap N+1 so the last lap completes
    final_lap = len(tl.profiles) + 1
    lapdata = _cars(
        P.LAP_DATA,
        {
            "lastLapTimeInMS": truth.lap_times_ms[final_lap - 1],
            "currentLapTimeInMS": 0,
            "lapDistance": 0.0,
            "currentLapNum": final_lap,
            "carPosition": 1,
            "driverStatus": 1,
            "resultStatus": 2,
        },
        sc.layout.max_cars,
    ) + P.LAP_DATA_TAIL.pack({"timeTrialPBCarIdx": 255, "timeTrialRivalCarIdx": 255})
    yield pkt(_hdr(P.PacketId.LAP_DATA, sc, t, frame, overall) + lapdata)
    yield pkt(_event_packet(sc, "SEND", b"", t, frame, overall), 100)
