"""Assetto Corsa (original, 2014) "Remote Telemetry" UDP packet layouts: handshaker, handshakerResponse, RTCarInfo, RTLap.

Sources, in order of authority (see ``docs/research/protocols/ac-remote-udp.md`` and
``docs/research/forza-ac-acc-iracing.md`` section 2.2, which ``tests/unit/test_ac.py`` machine-checks these
layouts against):

1. Kunos, "AC Socket Document" (the Remote Telemetry UDP specification, a public Google Doc): field names, field
   order and C types (``int`` = int32 LE, ``float`` = float32, ``bool`` = 8 bit), port 9996, operation ids, the
   handshake -> subscribe -> dismiss procedure. It does *not* specify struct packing, ``char`` vs ``wchar_t``,
   string termination, units of ``steer`` / ``carPositionNormalized``, wheel order, or the update rate.
2. Observed packets (community, 2017-2020, PC and PS4): RTCarInfo is **328 bytes**, the handshake reply is
   **408 bytes** on PC (strings are UTF-16LE ``wchar_t[50]``), RTLap is 212 bytes on PC.
3. Two MIT-licensed clients read for corroboration only (no code copied): rickwest/ac-remote-telemetry-client
   (JavaScript, explicit offsets) and crmne/moza-rev (Rust ``#[repr(C)]`` structs).

Packing - why RTCarInfo is 328 bytes and ``isInPit`` is at 24
    Laying the spec's fields out with *natural (default MSVC) alignment* gives exactly 328 bytes: the leading
    ``identifier`` (``char``, or a 2-byte ``wchar_t``) is followed by padding up to the 4-aligned ``int size`` at 4;
    the six ``bool``s occupy 20..25 and two padding bytes (26, 27) align ``accG_vertical`` to 28. A packed
    (``#pragma pack(1)``) reading of the spec gives 323 bytes, which is where the old "323 computed vs 328
    observed" puzzle came from. Natural alignment therefore explains the observed size with no extra
    assumptions, and both MIT clients agree (``isInPit`` at 24, ``isEngineLimiterOn`` at 25). The one dissenting
    client (Egocentrix, unlicensed, read only in the research doc's summary) places them at 26/27; nothing in the
    observed size supports that. **Certain**: offsets 0..23 and 28..327 (every reading agrees). **Not certain**:
    which of 24/25 vs 26/27 carry ``isInPit`` / ``isEngineLimiterOn``. The decoder reads 24/25, keeps 26/27 raw as
    ``pad_26_27`` so the adapter can count non-zero padding (evidence for the other reading) and the live probe can
    print both, and the adapter only trusts a flag byte that is exactly 0 or 1.

Strings
    The spec declares ``char[50]``; on PC the reply is 408 bytes, which only fits ``wchar_t[50]`` (UTF-16LE,
    100 bytes per string). A spec-literal 8-bit variant would be 208 bytes; it has never been observed but the
    console reply size has never been measured publicly either, so it is accepted (and reported) if it appears.
    Unused string tails are padded with ``'%'`` rather than NUL (moza-rev observation), so a string ends at the first
    NUL *or* ``'%'``.

Validation is by exact datagram size only (the protocol has no magic or header): 408/208 handshake reply, 328
RTCarInfo, 212 RTLap. Anything else is rejected. The ``identifier`` byte (``'a'``) and ``size`` field (328) of
RTCarInfo are checked by the adapter as *warnings*, not as rejection criteria: on consoles they are unverified.

Wheel order of the ``[4]`` arrays is undocumented (AC's shared memory uses FL, FR, RL, RR); none of them is mapped
into ``CarFrame``, so the question does not affect pitwall's output. They are decoded raw for completeness.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any

from pitwall.adapters.structdef import StructDef

AC_PORT = 9996  # the UDP port AC's in-session "ACServer" listens on (spec)
HANDSHAKE_IDENTIFIER = 1  # spec example value; "not used in the current version"
HANDSHAKE_VERSION = 1  # spec example value; "not used in the current version"
HANDSHAKE_STATUS_OK = 4242  # handshakerResponse.identifier: "for now is just 4242" (spec)
RT_CAR_INFO_IDENTIFIER = ord("a")  # RTCarInfo.identifier "is set to char 'a'" (spec)
STRING_CHARS = 50  # every string field is [50] characters (spec)
STRING_TERMINATORS = (0x0000, ord("%"))  # NUL (C convention) or '%' (AC pads unused tails with it)

# In-band marker carried by every SYNTHETIC handshake reply (``pitwall.sim.ac_stream``): the adapter maps a session
# with this car name to ``SYNTHETIC_SESSION_UID`` so generated telemetry is flagged synthetic wherever it travels
# (also when streamed over real UDP). Real AC car names are folder names such as ``ks_ferrari_488_gt3``.
SYNTHETIC_CAR_NAME = "PITWALL-SYNTHETIC"


class Operation(IntEnum):
    """``handshaker.operationId`` (spec)."""

    HANDSHAKE = 0  # ask for a handshakerResponse
    SUBSCRIBE_UPDATE = 1  # stream RTCarInfo "for every physics step"
    SUBSCRIBE_SPOT = 2  # RTLap on spot events (end of a lap), for every car in the session
    DISMISS = 3  # stop sending to this client


class PacketKind(StrEnum):
    HANDSHAKE_RESPONSE = "handshake_response"
    RT_CAR_INFO = "rt_car_info"
    RT_LAP = "rt_lap"


class PacketError(ValueError):
    """A payload does not have the exact size of the structure it was decoded as."""


def _wheels(name: str) -> tuple[str, str]:
    return (name, "4f")


# --- client -> AC (12 bytes) -----------------------------------------------------------------------------------
HANDSHAKER = StructDef(
    "handshaker",
    [
        ("identifier", "i"),  # 0
        ("version", "i"),  # 4
        ("operationId", "i"),  # 8
    ],
)

# --- AC -> client: handshake reply ------------------------------------------------------------------------------
# PC (observed): wchar_t[50] UTF-16LE strings -> 408 bytes.
HANDSHAKE_RESPONSE_WIDE = StructDef(
    "handshakerResponse(wchar_t)",
    [
        ("carName", "100s"),  # 0
        ("driverName", "100s"),  # 100
        ("identifier", "i"),  # 200 - 4242
        ("version", "i"),  # 204 - 1
        ("trackName", "100s"),  # 208
        ("trackConfig", "100s"),  # 308
    ],
)
# Spec-literal char[50] reading -> 208 bytes. Never observed; accepted only so a console that sends it is reported.
HANDSHAKE_RESPONSE_NARROW = StructDef(
    "handshakerResponse(char)",
    [
        ("carName", "50s"),  # 0
        ("driverName", "50s"),  # 50
        ("identifier", "i"),  # 100
        ("version", "i"),  # 104
        ("trackName", "50s"),  # 108
        ("trackConfig", "50s"),  # 158
    ],
)

# --- AC -> client: RTCarInfo (SUBSCRIBE_UPDATE), 328 bytes with natural alignment -------------------------------
RT_CAR_INFO = StructDef(
    "RTCarInfo",
    [
        ("identifier", "B"),  # 0 - 'a' (char; a wchar_t would add a 0x00 high byte at 1)
        ("identifier_pad", "3s"),  # 1..3 - wchar high byte and/or alignment padding before the int
        ("size", "i"),  # 4 - "size of the structured data in bytes" (328 observed)
        ("speed_Kmh", "f"),  # 8
        ("speed_Mph", "f"),  # 12
        ("speed_Ms", "f"),  # 16
        ("isAbsEnabled", "B"),  # 20
        ("isAbsInAction", "B"),  # 21
        ("isTcInAction", "B"),  # 22
        ("isTcEnabled", "B"),  # 23
        ("isInPit", "B"),  # 24 - natural alignment (rickwest, moza-rev); Egocentrix: 26. See module docstring.
        ("isEngineLimiterOn", "B"),  # 25 - natural alignment; Egocentrix: 27
        ("pad_26_27", "2s"),  # 26..27 - alignment padding before accG_vertical (kept raw as evidence)
        ("accG_vertical", "f"),  # 28
        ("accG_horizontal", "f"),  # 32
        ("accG_frontal", "f"),  # 36
        ("lapTime", "i"),  # 40 - current lap (ms)
        ("lastLap", "i"),  # 44 - ms
        ("bestLap", "i"),  # 48 - ms
        ("lapCount", "i"),  # 52
        ("gas", "f"),  # 56
        ("brake", "f"),  # 60
        ("clutch", "f"),  # 64
        ("engineRPM", "f"),  # 68
        ("steer", "f"),  # 72 - units undocumented
        ("gear", "i"),  # 76 - 0 = R, 1 = N, 2 = 1st (community)
        ("cgHeight", "f"),  # 80
        _wheels("wheelAngularSpeed"),  # 84
        _wheels("slipAngle"),  # 100
        _wheels("slipAngle_ContactPatch"),  # 116
        _wheels("slipRatio"),  # 132
        _wheels("tyreSlip"),  # 148
        _wheels("ndSlip"),  # 164
        _wheels("load"),  # 180
        _wheels("Dy"),  # 196
        _wheels("Mz"),  # 212
        _wheels("tyreDirtyLevel"),  # 228
        _wheels("camberRAD"),  # 244
        _wheels("tyreRadius"),  # 260
        _wheels("tyreLoadedRadius"),  # 276
        _wheels("suspensionHeight"),  # 292
        ("carPositionNormalized", "f"),  # 308 - spline position, 0..1 of a lap (name; spec gives no unit)
        ("carSlope", "f"),  # 312
        ("carCoordinates", "3f"),  # 316 - world x, y, z
    ],
)

# --- AC -> client: RTLap (SUBSCRIBE_SPOT), 212 bytes with wchar_t strings (PC; never received from a PS4) ---------
RT_LAP = StructDef(
    "RTLap",
    [
        ("carIdentifierNumber", "i"),  # 0
        ("lap", "i"),  # 4
        ("driverName", "100s"),  # 8
        ("carName", "100s"),  # 108
        ("time", "i"),  # 208 - ms
    ],
)

assert HANDSHAKER.size == 12
assert HANDSHAKE_RESPONSE_WIDE.size == 408
assert HANDSHAKE_RESPONSE_NARROW.size == 208
assert RT_CAR_INFO.size == 328
assert RT_LAP.size == 212

# Exact sizes accepted from the wire -> (kind, wide strings?). Every other size is rejected.
SIZES: dict[int, tuple[PacketKind, bool]] = {
    HANDSHAKE_RESPONSE_WIDE.size: (PacketKind.HANDSHAKE_RESPONSE, True),
    HANDSHAKE_RESPONSE_NARROW.size: (PacketKind.HANDSHAKE_RESPONSE, False),
    RT_CAR_INFO.size: (PacketKind.RT_CAR_INFO, True),
    RT_LAP.size: (PacketKind.RT_LAP, True),
}
HANDSHAKE_RESPONSE_SIZES = frozenset(s for s, (k, _) in SIZES.items() if k is PacketKind.HANDSHAKE_RESPONSE)


def kind_of(size: int) -> PacketKind | None:
    """Packet kind for a datagram of ``size`` bytes, or None if no AC structure has that size."""
    entry = SIZES.get(size)
    return entry[0] if entry else None


def field_offsets(sd: StructDef) -> dict[str, tuple[int, str]]:
    """``{field: (byte offset, struct format)}`` - used by the tests to compare layouts with the documentation."""
    out: dict[str, tuple[int, str]] = {}
    off = 0
    for name, fmt in sd.fields:
        out[name] = (off, fmt)
        off += StructDef("_", [(name, fmt)]).size
    return out


# --------------------------------------------------------------------------------------------------- strings
def decode_string(raw: bytes, wide: bool) -> str | None:
    """Decode one fixed-size string field; it ends at the first NUL or ``'%'``. Empty -> None.

    Wide strings are UTF-16LE code units (``wchar_t`` on Windows); narrow ones are decoded as UTF-8 (AC names are
    ASCII folder names in practice). Undecodable bytes become U+FFFD and control characters are dropped, so a
    corrupt field can never inject newlines or escape codes into logs or the UI.
    """
    if wide:
        units = [int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw) - 1, 2)]
        end = next((i for i, u in enumerate(units) if u in STRING_TERMINATORS), len(units))
        text = raw[: 2 * end].decode("utf-16-le", errors="replace")
    else:
        end = next((i for i, b in enumerate(raw) if b in STRING_TERMINATORS), len(raw))
        text = raw[:end].decode("utf-8", errors="replace")
    text = "".join(ch for ch in text if ch.isprintable()).strip()
    return text or None


def encode_string(text: str, wide: bool, pad: str = "%") -> bytes:
    """Encode ``text`` into a ``[50]`` field, padding the tail with ``pad`` (AC uses ``'%'``; ``'\\0'`` also works)."""
    if len(pad) != 1:
        raise ValueError("pad must be a single character")
    if len(text) > STRING_CHARS:
        raise ValueError(f"string longer than {STRING_CHARS} characters: {text!r}")
    full = text + pad * (STRING_CHARS - len(text))
    if wide:
        return full.encode("utf-16-le")
    raw = full.encode("utf-8")
    if len(raw) != STRING_CHARS:
        raise ValueError(f"narrow string must be single-byte characters: {text!r}")
    return raw


# --------------------------------------------------------------------------------------------------- handshaker
def encode_handshaker(op: Operation, identifier: int = HANDSHAKE_IDENTIFIER, version: int = HANDSHAKE_VERSION) -> bytes:
    return HANDSHAKER.pack({"identifier": identifier, "version": version, "operationId": int(op)})


def decode_handshaker(data: bytes) -> tuple[int, int, int]:
    """``(identifier, version, operationId)`` of a client request (used by the synthetic fake server)."""
    if len(data) != HANDSHAKER.size:
        raise PacketError(f"handshaker must be {HANDSHAKER.size} bytes, got {len(data)}")
    d = HANDSHAKER.unpack_from(data)
    return int(d["identifier"]), int(d["version"]), int(d["operationId"])


# --------------------------------------------------------------------------------------------------- handshake reply
@dataclass(frozen=True, slots=True)
class HandshakeResponse:
    car_name: str | None
    driver_name: str | None
    identifier: int  # status code; 4242 is the only documented value
    version: int
    track_name: str | None
    track_config: str | None
    wide: bool  # True: 408-byte UTF-16LE reply (PC); False: 208-byte 8-bit reply (spec-literal, unobserved)

    @property
    def size(self) -> int:
        return HANDSHAKE_RESPONSE_WIDE.size if self.wide else HANDSHAKE_RESPONSE_NARROW.size

    @property
    def encoding(self) -> str:
        return "utf-16le" if self.wide else "8-bit"


def parse_handshake_response(data: bytes) -> HandshakeResponse:
    if len(data) == HANDSHAKE_RESPONSE_WIDE.size:
        wide, sd = True, HANDSHAKE_RESPONSE_WIDE
    elif len(data) == HANDSHAKE_RESPONSE_NARROW.size:
        wide, sd = False, HANDSHAKE_RESPONSE_NARROW
    else:
        raise PacketError(
            f"handshakerResponse must be {HANDSHAKE_RESPONSE_WIDE.size} (wchar_t) or "
            f"{HANDSHAKE_RESPONSE_NARROW.size} (char) bytes, got {len(data)}"
        )
    d = sd.unpack_from(data)
    return HandshakeResponse(
        car_name=decode_string(d["carName"], wide),
        driver_name=decode_string(d["driverName"], wide),
        identifier=int(d["identifier"]),
        version=int(d["version"]),
        track_name=decode_string(d["trackName"], wide),
        track_config=decode_string(d["trackConfig"], wide),
        wide=wide,
    )


def encode_handshake_response(
    car_name: str,
    driver_name: str,
    track_name: str,
    track_config: str = "",
    *,
    wide: bool = True,
    identifier: int = HANDSHAKE_STATUS_OK,
    version: int = HANDSHAKE_VERSION,
    pad: str = "%",
) -> bytes:
    sd = HANDSHAKE_RESPONSE_WIDE if wide else HANDSHAKE_RESPONSE_NARROW
    return sd.pack(
        {
            "carName": encode_string(car_name, wide, pad),
            "driverName": encode_string(driver_name, wide, pad),
            "identifier": identifier,
            "version": version,
            "trackName": encode_string(track_name, wide, pad),
            "trackConfig": encode_string(track_config, wide, pad),
        }
    )


# --------------------------------------------------------------------------------------------------- RTCarInfo
def parse_rt_car_info(data: bytes) -> dict[str, Any]:
    """Raw field values (spec names). No interpretation: units and validity are the adapter's job."""
    if len(data) != RT_CAR_INFO.size:
        raise PacketError(f"RTCarInfo must be {RT_CAR_INFO.size} bytes, got {len(data)}")
    return RT_CAR_INFO.unpack_from(data)


def encode_rt_car_info(values: Mapping[str, Any] | None = None) -> bytes:
    """Encode RTCarInfo; ``identifier`` defaults to ``'a'`` and ``size`` to 328, other fields to zero."""
    v: dict[str, Any] = {"identifier": RT_CAR_INFO_IDENTIFIER, "size": RT_CAR_INFO.size}
    v.update(values or {})
    return RT_CAR_INFO.pack(v)


# --------------------------------------------------------------------------------------------------- RTLap
@dataclass(frozen=True, slots=True)
class RtLap:
    car_identifier: int
    lap: int
    driver_name: str | None
    car_name: str | None
    time_ms: int


def parse_rt_lap(data: bytes) -> RtLap:
    if len(data) != RT_LAP.size:
        raise PacketError(f"RTLap must be {RT_LAP.size} bytes, got {len(data)}")
    d = RT_LAP.unpack_from(data)
    return RtLap(
        car_identifier=int(d["carIdentifierNumber"]),
        lap=int(d["lap"]),
        driver_name=decode_string(d["driverName"], True),
        car_name=decode_string(d["carName"], True),
        time_ms=int(d["time"]),
    )


def encode_rt_lap(car_identifier: int, lap: int, driver_name: str, car_name: str, time_ms: int) -> bytes:
    return RT_LAP.pack(
        {
            "carIdentifierNumber": car_identifier,
            "lap": lap,
            "driverName": encode_string(driver_name, True),
            "carName": encode_string(car_name, True),
            "time": time_ms,
        }
    )
