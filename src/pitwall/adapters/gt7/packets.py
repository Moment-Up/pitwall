"""Gran Turismo 7 "Simulator Interface" packet layouts, variants and Salsa20 framing.

Source of truth: docs/research/gt7-protocol.md (community reverse-engineering; Polyphony publishes no spec).
Every field below is taken from that document's tables - section 4 (base / variant A), 5 (B), 6 (``~``) and
7 (C). ``tests/unit/test_gt7.py`` parses those tables and machine-checks every struct element against them:
offset, type and field label (so swapping two same-typed fields or changing a type fails, not just a shifted
offset). Fields marked unknown/unverified in the doc are kept under neutral names and are not normalised by the
adapter.

Framing (doc section 3): each datagram is Salsa20/20-encrypted as a whole with the key
``b"Simulator Interface Packet GT7 ver 0.0"[:32]`` and an 8-byte nonce ``IV2 || IV1`` (both little-endian
uint32), where ``IV1`` is read from ciphertext bytes 0x40..0x43 and ``IV2 = IV1 XOR <variant constant>``.
The variant is identified by datagram length (296/316/344/368), never by what was requested.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntFlag
from typing import Any

from pitwall.adapters.gt7.salsa20 import Salsa20
from pitwall.adapters.structdef import StructDef

KEY = b"Simulator Interface Packet GT7 ver 0.0"[:32]  # 38-byte string, first 32 bytes used (doc section 3.2)
MAGIC = 0x47375330  # plaintext bytes 30 53 37 47 ("0S7G") read as a little-endian uint32 (doc section 3.7)
IV_OFFSET = 0x40  # nonce seed IV1, read from the *ciphertext* (doc section 3.3)
CONSOLE_PORT = 33739  # where the heartbeat goes (doc section 1)
RECEIVE_PORT = 33740  # where the console sends telemetry (doc section 1)

# Synthetic streams (pitwall.sim.gt7_stream) write this marker into the 32 bytes at 0xD4..0xF3, which the doc
# records as "reserved, server does not set that" (PDTools). The adapter flags any packet carrying it as
# synthetic, so generated telemetry can never pass as real game data, even when streamed over real UDP.
SYNTHETIC_MARKER = b"PITWALL-SYNTHETIC-GT7-STREAM\x00\x00\x00\x00"
assert len(SYNTHETIC_MARKER) == 32

_CIPHER = Salsa20(KEY)


class Flags(IntFlag):
    """Bitfield at 0x8E (doc section 4.1, PDTools names). Bits 12-15 are unknown."""

    CAR_ON_TRACK = 0x0001
    PAUSED = 0x0002
    LOADING_OR_PROCESSING = 0x0004
    IN_GEAR = 0x0008  # "needs more investigation" (PDTools)
    HAS_TURBO = 0x0010
    REV_LIMITER_ALERT = 0x0020
    HAND_BRAKE = 0x0040
    LIGHTS = 0x0080
    HIGH_BEAM = 0x0100
    LOW_BEAM = 0x0200
    ASM_ACTIVE = 0x0400
    TCS_ACTIVE = 0x0800


# --- section 4: base packet (variant A), 0x000-0x127 ------------------------------------------------
BASE_FIELDS: list[tuple[str, str]] = [
    ("magic", "I"),  # 0x000
    ("position", "3f"),  # 0x004 X, 0x008 Y (up), 0x00C Z - metres
    ("velocity", "3f"),  # 0x010..0x01B - world frame m/s
    ("rotation", "4f"),  # 0x01C..0x02B - quaternion x,y,z,w (naming conflicting, doc note R)
    ("angular_velocity", "3f"),  # 0x02C..0x037 - rad/s
    ("body_height", "f"),  # 0x038 - m
    ("engine_rpm", "f"),  # 0x03C
    ("iv", "I"),  # 0x040 - nonce seed in the ciphertext; garbage after decryption
    ("fuel_level", "f"),  # 0x044 - litres per PDTools (GT7Eng treats as %; capacity is 100 for most cars)
    ("fuel_capacity", "f"),  # 0x048 - 100 most cars, 5 karts, 0 EVs
    ("speed", "f"),  # 0x04C - m/s
    ("turbo_boost", "f"),  # 0x050 - +1 offset (1.0 = 0 kPa gauge)
    ("oil_pressure", "f"),  # 0x054 - bar
    ("water_temp", "f"),  # 0x058 - always 85 (not simulated)
    ("oil_temp", "f"),  # 0x05C - always 110 (not simulated)
    ("tyre_surface_temp", "4f"),  # 0x060..0x06F - FL, FR, RL, RR, deg C
    ("packet_id", "i"),  # 0x070
    ("lap_count", "h"),  # 0x074 - 0 before the start / outside a timed session
    ("total_laps", "h"),  # 0x076 - 0 for timed/endurance and free runs
    ("best_lap_ms", "i"),  # 0x078 - -1 when unset
    ("last_lap_ms", "i"),  # 0x07C - -1 when unset
    ("time_of_day_ms", "i"),  # 0x080
    ("pre_race_position", "h"),  # 0x084 - conflicting: grid position, -1 after the start (or live position)
    ("num_cars_pre_race", "h"),  # 0x086 - conflicting
    ("rev_alert_min_rpm", "H"),  # 0x088 - i16 (PDTools) / u16 (Kaitai); identical for real RPM values
    ("rev_alert_max_rpm", "H"),  # 0x08A
    ("calc_max_speed_kph", "h"),  # 0x08C
    ("flags", "h"),  # 0x08E - i16 bitfield, see Flags (bits 12-15 unknown; the adapter masks them off)
    ("gears", "B"),  # 0x090 - low nibble current, high nibble suggested (15 = none)
    ("throttle", "B"),  # 0x091 - 0..255
    ("brake", "B"),  # 0x092 - 0..255
    ("unused_93", "B"),  # 0x093 - padding
    ("road_plane", "3f"),  # 0x094..0x09F
    ("road_plane_distance", "f"),  # 0x0A0
    ("wheel_angular_speed", "4f"),  # 0x0A4..0x0B3 - FL, FR, RL, RR rad/s
    ("tyre_radius", "4f"),  # 0x0B4..0x0C3 - FL, FR, RL, RR m
    ("suspension_height", "4f"),  # 0x0C4..0x0D3 - FL, FR, RL, RR m
    ("reserved", "32s"),  # 0x0D4..0x0F3 - not set by the game (NOT tyre pressures)
    ("clutch_pedal", "f"),  # 0x0F4 - 0..1
    ("clutch_engagement", "f"),  # 0x0F8 - 0..1
    ("rpm_clutch_to_gearbox", "f"),  # 0x0FC
    ("transmission_top_speed", "f"),  # 0x100 - gear-ratio value
    ("gear_ratios", "8f"),  # 0x104..0x123
    ("car_code", "i"),  # 0x124 - corrupted for cars with 9+ gears
]

# --- section 5: variant B extension, 0x128-0x13B ----------------------------------------------------------
B_FIELDS: list[tuple[str, str]] = [
    ("wheel_rotation_rad", "f"),  # 0x128 - steering wheel angle (rad); sign convention unverified
    ("wheel_angular_velocity", "f"),  # 0x12C - rad/s (PDTools: unknown)
    ("sway", "f"),  # 0x130 - units unverified
    ("heave", "f"),  # 0x134
    ("surge", "f"),  # 0x138
]

# --- section 6: variant ~ extension, 0x13C-0x157 ------------------------------------------------------
TILDE_FIELDS: list[tuple[str, str]] = [
    ("throttle_alt", "B"),  # 0x13C - input vs output after TCS: conflicting
    ("brake_alt", "B"),  # 0x13D - conflicting
    ("unknown_13e", "B"),  # 0x13E
    ("unknown_13f", "B"),  # 0x13F
    ("wheel_torque", "4f"),  # 0x140..0x14F - unverified per-wheel value
    ("energy_recovery", "f"),  # 0x150 - units unknown
    ("unknown_154", "f"),  # 0x154
]

# --- section 7: variant C extension, 0x158-0x16F ------------------------------------------------------
C_FIELDS: list[tuple[str, str]] = [
    ("surface_type", "4s"),  # 0x158 - one ASCII letter per wheel FL, FR, RL, RR
    ("current_lap_ms", "i"),  # 0x15C - running lap time, -1 when not set
    ("fl_steer_rad", "f"),  # 0x160 - road-wheel angle, left positive
    ("fr_steer_rad", "f"),  # 0x164
    ("wheelbase_left_m", "f"),  # 0x168
    ("car_category", "4s"),  # 0x16C - NUL-terminated ASCII, e.g. b"GR3\0"
]

PACKET_A = StructDef("GT7PacketA", BASE_FIELDS)
PACKET_B = StructDef("GT7PacketB", BASE_FIELDS + B_FIELDS)
PACKET_TILDE = StructDef("GT7PacketTilde", BASE_FIELDS + B_FIELDS + TILDE_FIELDS)
PACKET_C = StructDef("GT7PacketC", BASE_FIELDS + B_FIELDS + TILDE_FIELDS + C_FIELDS)


@dataclass(frozen=True, slots=True)
class Variant:
    name: str  # "A", "B", "~", "C"
    heartbeat: bytes  # single ASCII byte sent to the console to select this variant
    size: int  # datagram length in bytes
    xor: int  # IV2 = IV1 XOR this constant
    layout: StructDef


VARIANTS: dict[str, Variant] = {
    "A": Variant("A", b"A", 296, 0xDEADBEAF, PACKET_A),  # note BEAF, not BEEF (doc section 2)
    "B": Variant("B", b"B", 316, 0xDEADBEEF, PACKET_B),
    "~": Variant("~", b"~", 344, 0x55FABB4F, PACKET_TILDE),
    "C": Variant("C", b"C", 368, 0xDEADBEEF, PACKET_C),
}
BY_SIZE: dict[int, Variant] = {v.size: v for v in VARIANTS.values()}

for _v in VARIANTS.values():
    if _v.layout.size != _v.size:  # pragma: no cover - import-time guard against layout edits
        raise AssertionError(f"GT7 variant {_v.name}: layout is {_v.layout.size} bytes, expected {_v.size}")


def field_offsets(layout: StructDef) -> dict[str, int]:
    """Byte offset of every field in ``layout`` (packed little-endian, so offsets are cumulative sizes)."""
    out: dict[str, int] = {}
    off = 0
    for name, fmt in layout.fields:
        out[name] = off
        off += struct.calcsize("<" + fmt)
    return out


class PacketError(ValueError):
    """Structural failure: unknown size or wrong magic after decryption."""


def nonce_for(variant: Variant, iv1: int) -> bytes:
    """Doc section 3.4-3.5: nonce = (IV1 XOR constant) as LE u32, followed by IV1 as LE u32."""
    iv1 &= 0xFFFFFFFF
    return ((iv1 ^ variant.xor) & 0xFFFFFFFF).to_bytes(4, "little") + iv1.to_bytes(4, "little")


def variant_for(data: bytes) -> Variant:
    v = BY_SIZE.get(len(data))
    if v is None:
        raise PacketError(f"unexpected GT7 datagram size {len(data)} (expected one of {sorted(BY_SIZE)})")
    return v


def decrypt(data: bytes) -> tuple[Variant, bytes]:
    """Decrypt one datagram and validate size and magic. Raises ``PacketError``."""
    variant = variant_for(data)
    iv1 = int.from_bytes(data[IV_OFFSET : IV_OFFSET + 4], "little")
    plain = _CIPHER.xor(nonce_for(variant, iv1), data)
    if int.from_bytes(plain[0:4], "little") != MAGIC:
        raise PacketError(f"bad magic after decryption (variant {variant.name}): not a GT7 packet or corrupted")
    return variant, plain


def has_valid_magic(data: bytes) -> bool:
    """Cheap auto-detection: size check plus decryption of the first 64-byte block only. Never raises."""
    variant = BY_SIZE.get(len(data))
    if variant is None:
        return False
    iv1 = int.from_bytes(data[IV_OFFSET : IV_OFFSET + 4], "little")
    head = _CIPHER.xor(nonce_for(variant, iv1), data[:4])
    return int.from_bytes(head, "little") == MAGIC


def encrypt(plain: bytes, iv1: int) -> bytes:
    """Inverse of ``decrypt`` for synthetic packets: encrypt, then store IV1 in ciphertext bytes 0x40..0x43.

    The bytes at 0x40..0x43 of the plaintext are therefore overwritten in transit, exactly as the doc
    describes for real packets ("meaningless after decryption").
    """
    variant = variant_for(plain)
    ct = bytearray(_CIPHER.xor(nonce_for(variant, iv1), plain))
    ct[IV_OFFSET : IV_OFFSET + 4] = (iv1 & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(ct)


def unpack(variant: Variant, plain: bytes) -> dict[str, Any]:
    return variant.layout.unpack_from(plain)


def pack(variant: Variant, values: dict[str, Any]) -> bytes:
    """Encode a plaintext packet (missing fields zero-filled); the magic is always set."""
    return variant.layout.pack({**values, "magic": MAGIC})
