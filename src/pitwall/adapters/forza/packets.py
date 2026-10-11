"""Forza "Data Out" UDP packet layouts: FM7, Forza Motorsport (2023), Forza Horizon 4/5/6.

Source of truth: ``docs/research/forza-ac-acc-iracing.md`` section 1, which collates Turn 10's official
"Forza Motorsport Data Out Documentation" (FM7/FM2023 field list), Playground's official FH6 documentation
(324-byte layout) and community decoders (FH4/FH5 layout, packet sizes). ``tests/unit/test_forza.py``
machine-checks every offset and type below against the tables in that document, so a typo here or there
cannot slip through. Nothing in this file is guessed: fields whose *meaning* is undocumented (gear 0, tyre
temperature unit, tyre wear range) are decoded raw here and interpreted conservatively in ``adapter.py``.

The protocol is a one-way little-endian UDP push with no header, magic or version. The format is identified
purely by datagram length:

========  ==========================================================  ==================================
Length    Layout                                                      Titles
========  ==========================================================  ==================================
232       Sled                                                        FM7, FM2023 ("Sled" selected)
311       Sled + Dash                                                 FM7 ("Dash")
324       Sled + 12-byte Horizon block @232 + Dash @244 + 1 pad byte  FH4, FH5, FH6 (indistinguishable)
331       Sled + Dash + TireWear x4 + TrackOrdinal (unaligned @311)   Forza Motorsport (2023) ("Dash")
========  ==========================================================  ==================================

Field names are the official names (wheel arrays spelled out as ``...FrontLeft`` .. ``...RearRight``, which
is also the FL, FR, RL, RR order pitwall uses) so they can be compared against the documentation by eye.
``struct`` is used with ``<`` (no alignment), which reads FM2023's unaligned floats at offset 311 correctly.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pitwall.adapters.structdef import StructDef
from pitwall.model.telemetry import Game

WHEEL_SUFFIXES = ("FrontLeft", "FrontRight", "RearLeft", "RearRight")  # FL, FR, RL, RR (Forza's own order)

# In-band marker carried by every SYNTHETIC Forza stream (``pitwall.sim.forza_stream``). Forza has no session id
# on the wire, so the generator writes this impossible car ordinal (real ordinals are positive model ids) and
# the adapter maps it to ``SYNTHETIC_SESSION_UID``, which makes the session manager flag the session as synthetic
# even when the stream arrives over live UDP (e.g. ``pitwall send``).
SYNTHETIC_CAR_ORDINAL = -0x5EED


class ForzaFormat(StrEnum):
    SLED = "sled"  # 232 B: FM7 / FM2023 with "Sled" selected
    FM7_DASH = "fm7_dash"  # 311 B
    HORIZON_DASH = "horizon_dash"  # 324 B: FH4 / FH5 / FH6
    FM2023_DASH = "fm2023_dash"  # 331 B: Forza Motorsport (2023)


def _wheels(prefix: str, fmt: str) -> list[tuple[str, str]]:
    return [(f"{prefix}{w}", fmt) for w in WHEEL_SUFFIXES]


# Offsets 0-231, every title and format (doc section 1.3).
SLED = StructDef(
    "ForzaSled",
    [
        ("IsRaceOn", "i"),  # S32: 1 = race on, 0 = menus / race stopped
        ("TimestampMS", "I"),  # U32 ms, wraps
        ("EngineMaxRpm", "f"),
        ("EngineIdleRpm", "f"),
        ("CurrentEngineRpm", "f"),
        ("AccelerationX", "f"),  # car-local: X right, Y up, Z forward (m/s^2 per community docs)
        ("AccelerationY", "f"),
        ("AccelerationZ", "f"),
        ("VelocityX", "f"),  # car-local m/s
        ("VelocityY", "f"),
        ("VelocityZ", "f"),
        ("AngularVelocityX", "f"),  # car-local rad/s
        ("AngularVelocityY", "f"),
        ("AngularVelocityZ", "f"),
        ("Yaw", "f"),  # rad
        ("Pitch", "f"),
        ("Roll", "f"),
        *_wheels("NormalizedSuspensionTravel", "f"),  # 0 = max stretch, 1 = max compression
        *_wheels("TireSlipRatio", "f"),
        *_wheels("WheelRotationSpeed", "f"),  # rad/s
        *_wheels("WheelOnRumbleStrip", "i"),
        *_wheels("WheelInPuddleDepth", "f"),  # FM: F32 depth 0..1; FH6 redefines as S32 bool (unused here)
        *_wheels("SurfaceRumble", "f"),
        *_wheels("TireSlipAngle", "f"),
        *_wheels("TireCombinedSlip", "f"),
        *_wheels("SuspensionTravelMeters", "f"),
        ("CarOrdinal", "i"),
        ("CarClass", "i"),  # 0 (D) .. 7 (X)
        ("CarPerformanceIndex", "i"),  # 100..999
        ("DrivetrainType", "i"),  # 0 FWD, 1 RWD, 2 AWD
        ("NumCylinders", "i"),
    ],
)

# Offsets 232-243, Horizon only (doc section 1.4). FH6 official names; FH4/5 community decode only the first U32.
HORIZON_EXTRA = StructDef(
    "ForzaHorizonExtra",
    [
        ("CarGroup", "I"),
        ("SmashableVelDiff", "f"),  # m/s lost hitting a smashable object
        ("SmashableMass", "f"),  # kg
    ],
)

# FM7/FM2023 offset 232, Horizon offset 244 (doc section 1.5).
DASH = StructDef(
    "ForzaDash",
    [
        ("PositionX", "f"),  # world m
        ("PositionY", "f"),  # world m, vertical
        ("PositionZ", "f"),  # world m
        ("Speed", "f"),  # m/s
        ("Power", "f"),  # W
        ("Torque", "f"),  # N.m
        ("TireTempFrontLeft", "f"),  # unit not stated officially; community: degF
        ("TireTempFrontRight", "f"),
        ("TireTempRearLeft", "f"),
        ("TireTempRearRight", "f"),
        ("Boost", "f"),  # psi above atmospheric
        ("Fuel", "f"),  # 0.0 empty .. 1.0 full
        ("DistanceTraveled", "f"),  # m, cumulative since driving started (not per lap)
        ("BestLap", "f"),  # s (0.0 if n/a)
        ("LastLap", "f"),  # s
        ("CurrentLap", "f"),  # s
        ("CurrentRaceTime", "f"),  # s
        ("LapNumber", "H"),  # laps completed
        ("RacePosition", "B"),
        ("Accel", "B"),  # throttle 0..255
        ("Brake", "B"),  # 0..255
        ("Clutch", "B"),  # 0..255
        ("HandBrake", "B"),  # 0..255
        ("Gear", "B"),  # reverse/neutral encoding undocumented
        ("Steer", "b"),  # -127 full left .. 127 full right
        ("NormalizedDrivingLine", "b"),  # -127..127, lateral offset from the driving line
        ("NormalizedAIBrakeDifference", "b"),  # -127..127
    ],
)

# Offsets 311-330, Forza Motorsport (2023) only (doc section 1.6). Unaligned: ``<`` packing handles it.
FM2023_EXTRA = StructDef(
    "ForzaMotorsport2023Extra",
    [
        *_wheels("TireWear", "f"),  # range officially undocumented; community: 0..1 wear fraction
        ("TrackOrdinal", "i"),
    ],
)

HORIZON_PAD_OFFSET = 323  # 1 trailing byte, unused


@dataclass(frozen=True, slots=True)
class FormatLayout:
    """One datagram format: which blocks sit at which offset, and which game family sends it."""

    fmt: ForzaFormat
    size: int
    game: Game
    blocks: tuple[tuple[int, StructDef], ...]  # (byte offset, block)
    family: str  # namespace for game-scoped ids (car ordinals and fingerprints differ per title)

    @property
    def has_dash(self) -> bool:
        return any(sd is DASH for _, sd in self.blocks)

    def unpack(self, data: bytes | memoryview) -> dict[str, Any]:
        """Decode every block into one flat ``{official field name: value}`` dict."""
        out: dict[str, Any] = {}
        for offset, sd in self.blocks:
            out.update(sd.unpack_from(data, offset))
        return out

    def pack(self, values: dict[str, Any]) -> bytes:
        """Encode (used by the synthetic generator). Missing fields and padding bytes are zero."""
        buf = bytearray(self.size)
        for offset, sd in self.blocks:
            buf[offset : offset + sd.size] = sd.pack(values)
        return bytes(buf)


SLED_LAYOUT = FormatLayout(ForzaFormat.SLED, 232, Game.FORZA_MOTORSPORT, ((0, SLED),), "fm")
FM7_DASH_LAYOUT = FormatLayout(ForzaFormat.FM7_DASH, 311, Game.FORZA_MOTORSPORT, ((0, SLED), (232, DASH)), "fm7")
HORIZON_DASH_LAYOUT = FormatLayout(
    ForzaFormat.HORIZON_DASH, 324, Game.FORZA_HORIZON, ((0, SLED), (232, HORIZON_EXTRA), (244, DASH)), "fh"
)
FM2023_DASH_LAYOUT = FormatLayout(
    ForzaFormat.FM2023_DASH, 331, Game.FORZA_MOTORSPORT, ((0, SLED), (232, DASH), (311, FM2023_EXTRA)), "fm2023"
)

LAYOUTS: dict[int, FormatLayout] = {
    lay.size: lay for lay in (SLED_LAYOUT, FM7_DASH_LAYOUT, HORIZON_DASH_LAYOUT, FM2023_DASH_LAYOUT)
}
LAYOUT_BY_FORMAT: dict[ForzaFormat, FormatLayout] = {lay.fmt: lay for lay in LAYOUTS.values()}


def field_offsets(layout: FormatLayout) -> dict[str, tuple[int, str]]:
    """``{field name: (absolute byte offset, struct format code)}`` - for spec checks and documentation."""
    out: dict[str, tuple[int, str]] = {}
    for base, sd in layout.blocks:
        off = base
        for name, fmt in sd.fields:
            out[name] = (off, fmt)
            off += struct.calcsize("<" + fmt)
    return out


def _check_layouts() -> None:
    """Import-time guard: blocks must tile each datagram exactly (only Horizon's documented pad byte is spare)."""
    for lay in LAYOUTS.values():
        end = 0
        for offset, sd in lay.blocks:
            if offset != end:
                raise AssertionError(f"{lay.fmt}: block {sd.name} at {offset}, expected {end}")
            end = offset + sd.size
        spare = 1 if lay.fmt is ForzaFormat.HORIZON_DASH else 0
        if end + spare != lay.size:
            raise AssertionError(f"{lay.fmt}: blocks end at {end} (+{spare} pad), datagram is {lay.size}")


_check_layouts()
