"""Assetto Corsa Competizione shared-memory page layouts: SPageFilePhysics, SPageFileGraphic, SPageFileStatic.

Source of truth: Kunos Simulazioni, **"ACC Shared Memory v1.8.12"** (25-page PDF, author KUNOS, file created
2022-03-23), attached to the first post of the official forum thread "ACC Shared Memory Documentation" (KS Dev Team,
first posted 2019-08-28): https://www.assettocorsa.net/forum/index.php?threads/acc-shared-memory-documentation.59965/
- the latest version published there (checked 2026-10-16). Field order, C types, array lengths and every field name
below are transcribed from that PDF; ``docs/research/acc-shared-memory-spec.md`` restates them field by field (with
Kunos' meaning in our own words and whether Kunos marks the field as used by ACC), and
``tests/unit/test_acc_protocol.py`` machine-checks these ``StructDef``s against that document: names, types, counts,
offsets and total sizes.

Layout rules (from the PDF and Kunos' C sample header ``SharedFileOut.h``, which wraps the three structs in
``#pragma pack(4)``):

* ``int`` = int32, ``float`` = float32, every ``ACC_*`` enum = int32, ``wchar_t`` = 2 bytes (UTF-16LE: the game is
  Windows-only), little-endian.
* Natural alignment up to 4 bytes: a ``wchar_t[N]`` with odd ``N`` ends on a 2-byte boundary, so 2 padding bytes
  follow it when the next member is 4 bytes wide. ``StructDef`` packs without alignment, so each such gap is an
  explicit ``_pad_<offset>`` field (2 raw bytes, never interpreted).
* Two-dimensional arrays (``float tyreContactPoint[4][3]``, ``float carCoordinates[60][3]``) are flattened row-major
  (``[wheel][axis]`` / ``[car][axis]``): 12 and 180 floats.
* Field names are Kunos' own, spelling and capitalisation included (``TyreCoreTemp``, ``secondaryDisplyIndex``,
  ``TCCUT``, ``Clock``...), so the machine check can compare them one to one. Kunos' C sample header spells a few
  differently (``rpms``, ``wheelsPressure``, ``tyreCoreTemperature``...); the PDF wins (see the research doc).

Sizes: Physics **800** B, Graphics **1588** B, Static **820** B. The PDF prints no array length for
``trackConfiguration`` (a field it marks "Not used in ACC"); Kunos' sample header declares ``wchar_t
trackConfiguration[33]``, which gives 820. Only fields after it depend on that (``ersMaxJ`` .. ``wetTyresName``), and
pitwall reads none of them.

Pitwall-internal framing (not anything ACC sends): the shared-memory reader copies one whole page per snapshot and
prefixes a 4-byte ASCII tag - ``PHYS``, ``GRPH`` or ``STAT`` - so a snapshot can travel through the packet router,
the ``.pwcap`` capture and replay exactly like a UDP datagram. A snapshot is therefore always 4 + 800, 4 + 1588 or
4 + 820 bytes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from pitwall.adapters.structdef import StructDef

# ---------------------------------------------------------------------------------------------- shared memory
# The named file mappings ACC creates on the gaming PC (per-session namespace, hence "Local\"). A reader must OPEN
# these (OpenFileMappingW + MapViewOfFile, read-only); creating them would make an empty page under ACC's name.
PHYSICS_MAPPING = "Local\\acpmf_physics"
GRAPHICS_MAPPING = "Local\\acpmf_graphics"
STATIC_MAPPING = "Local\\acpmf_static"

# Pitwall-internal snapshot tags (4 ASCII bytes in front of one whole page; see the module docstring).
TAG_PHYSICS = b"PHYS"
TAG_GRAPHICS = b"GRPH"
TAG_STATIC = b"STAT"
TAG_SIZE = 4

INT32_MAX = 2_147_483_647  # ACC fills the integer lap times with this before they have a value

# In-band marker for SYNTHETIC streams (pitwall's generators): a Static page whose ``carModel`` is this string makes
# the adapter use ``SYNTHETIC_SESSION_UID``, so generated telemetry is flagged synthetic wherever it travels. Real
# ``carModel`` values are Kunos ids such as ``mclaren_720s_gt3`` (Appendix 2).
SYNTHETIC_CAR_MODEL = "PITWALL-SYNTHETIC"


class AccStatus(IntEnum):
    """``ACC_STATUS`` (Graphics.status)."""

    OFF = 0
    REPLAY = 1
    LIVE = 2
    PAUSE = 3


class AccSessionType(IntEnum):
    """``ACC_SESSION_TYPE`` (Graphics.session)."""

    UNKNOWN = -1
    PRACTICE = 0
    QUALIFY = 1
    RACE = 2
    HOTLAP = 3
    TIMEATTACK = 4
    DRIFT = 5
    DRAG = 6
    HOTSTINT = 7
    HOTSTINTSUPERPOLE = 8


class AccFlagType(IntEnum):
    """``ACC_FLAG_TYPE`` (Graphics.flag)."""

    NO_FLAG = 0
    BLUE_FLAG = 1
    YELLOW_FLAG = 2
    BLACK_FLAG = 3
    WHITE_FLAG = 4
    CHECKERED_FLAG = 5
    PENALTY_FLAG = 6
    GREEN_FLAG = 7
    ORANGE_FLAG = 8


class AccTrackGripStatus(IntEnum):
    """``ACC_TRACK_GRIP_STATUS`` (Graphics.trackGripStatus)."""

    GREEN = 0
    FAST = 1
    OPTIMUM = 2
    GREASY = 3
    DAMP = 4
    WET = 5
    FLOODED = 6


class AccRainIntensity(IntEnum):
    """``ACC_RAIN_INTENSITY`` (Graphics.rainIntensity / rainIntensityIn10min / rainIntensityIn30min)."""

    NO_RAIN = 0
    DRIZZLE = 1
    LIGHT_RAIN = 2
    MEDIUM_RAIN = 3
    HEAVY_RAIN = 4
    THUNDERSTORM = 5


def _w(name: str) -> tuple[str, str]:
    """A ``float[4]`` per-wheel array (FL, FR, RL, RR per Kunos)."""
    return (name, "4f")


def _ws(name: str, chars: int) -> tuple[str, str]:
    """A ``wchar_t[chars]`` string: 2 bytes per UTF-16 code unit."""
    return (name, f"{2 * chars}s")


# ---------------------------------------------------------------------------------------------- SPageFilePhysics
# "Change at each graphic step"; all of it is the player's car. 85 fields, all 4 bytes wide: no padding.
PHYSICS = StructDef(
    "SPageFilePhysics",
    [
        ("packetId", "i"),  # 0
        ("gas", "f"),  # 4
        ("brake", "f"),  # 8
        ("fuel", "f"),  # 12 - Kunos: kg (see the research doc: unit conflict)
        ("gear", "i"),  # 16
        ("rpm", "i"),  # 20
        ("steerAngle", "f"),  # 24 - steering input -1..1
        ("speedKmh", "f"),  # 28
        ("velocity", "3f"),  # 32 - global coordinates
        ("accG", "3f"),  # 44 - Kunos: global coordinates
        _w("wheelSlip"),  # 56
        _w("wheelLoad"),  # 72 - not used by ACC
        _w("wheelPressure"),  # 88
        _w("wheelAngularSpeed"),  # 104 - rad/s
        _w("tyreWear"),  # 120 - not used by ACC
        _w("tyreDirtyLevel"),  # 136 - not used by ACC
        _w("TyreCoreTemp"),  # 152 - double field (also tyreTemp, unused)
        _w("camberRAD"),  # 168 - not used by ACC
        _w("suspensionTravel"),  # 184
        ("drs", "f"),  # 200 - not used by ACC
        ("tc", "f"),  # 204 - TC in action (double field: tcinAction, unused)
        ("heading", "f"),  # 208
        ("pitch", "f"),  # 212
        ("roll", "f"),  # 216
        ("cgHeight", "f"),  # 220 - not used by ACC
        ("carDamage", "5f"),  # 224 - front, rear, left, right, centre
        ("numberOfTyresOut", "i"),  # 244 - not used by ACC
        ("pitLimiterOn", "i"),  # 248
        ("abs", "f"),  # 252 - ABS in action (double field: absInAction, unused)
        ("kersCharge", "f"),  # 256 - not used by ACC
        ("kersInput", "f"),  # 260 - not used by ACC
        ("autoshifterOn", "i"),  # 264
        ("rideHeight", "2f"),  # 268 - not used by ACC
        ("turboBoost", "f"),  # 276
        ("ballast", "f"),  # 280 - not used by ACC
        ("airDensity", "f"),  # 284 - not used by ACC
        ("airTemp", "f"),  # 288
        ("roadTemp", "f"),  # 292
        ("localAngularVel", "3f"),  # 296 - local coordinates
        ("finalFF", "f"),  # 308
        ("performanceMeter", "f"),  # 312 - not used by ACC
        ("engineBrake", "i"),  # 316 - not used by ACC
        ("ersRecoveryLevel", "i"),  # 320 - not used by ACC
        ("ersPowerLevel", "i"),  # 324 - not used by ACC
        ("ersHeatCharging", "i"),  # 328 - not used by ACC
        ("ersIsCharging", "i"),  # 332 - not used by ACC
        ("kersCurrentKJ", "f"),  # 336 - not used by ACC
        ("drsAvailable", "i"),  # 340 - not used by ACC
        ("drsEnabled", "i"),  # 344 - not used by ACC
        _w("brakeTemp"),  # 348
        ("clutch", "f"),  # 364
        _w("tyreTempI"),  # 368 - not shown in ACC
        _w("tyreTempM"),  # 384 - not shown in ACC
        _w("tyreTempO"),  # 400 - not shown in ACC
        ("isAIControlled", "i"),  # 416
        ("tyreContactPoint", "12f"),  # 420 - [4][3]
        ("tyreContactNormal", "12f"),  # 468 - [4][3]
        ("tyreContactHeading", "12f"),  # 516 - [4][3]
        ("brakeBias", "f"),  # 564 - needs Kunos' per-car offset (Appendix 4)
        ("localVelocity", "3f"),  # 568 - local coordinates
        ("P2PActivation", "i"),  # 580 - not used by ACC
        ("P2PStatus", "i"),  # 584 - not used by ACC
        ("currentMaxRpm", "f"),  # 588 - not used by ACC (sample header: int)
        _w("mz"),  # 592 - not shown in ACC
        _w("fx"),  # 608 - not shown in ACC
        _w("fy"),  # 624 - not shown in ACC
        _w("slipRatio"),  # 640
        _w("slipAngle"),  # 656
        ("tcinAction", "i"),  # 672 - not used by ACC (double of tc)
        ("absInAction", "i"),  # 676 - not used by ACC (double of abs)
        _w("suspensionDamage"),  # 680 - not used by ACC
        _w("tyreTemp"),  # 696 - not used by ACC (double of TyreCoreTemp)
        ("waterTemp", "f"),  # 712
        _w("brakePressure"),  # 716
        ("frontBrakeCompound", "i"),  # 732
        ("rearBrakeCompound", "i"),  # 736
        _w("padLife"),  # 740
        _w("discLife"),  # 756
        ("ignitionOn", "i"),  # 772
        ("starterEngineOn", "i"),  # 776
        ("isEngineRunning", "i"),  # 780
        ("kerbVibration", "f"),  # 784
        ("slipVibrations", "f"),  # 788
        ("gVibrations", "f"),  # 792
        ("absVibrations", "f"),  # 796
    ],
)

# ---------------------------------------------------------------------------------------------- SPageFileGraphic
# "Updated at each graphical step"; the player's car, except carCoordinates and carID (the cars on track).
GRAPHICS = StructDef(
    "SPageFileGraphic",
    [
        ("packetId", "i"),  # 0
        ("status", "i"),  # 4 - ACC_STATUS
        ("session", "i"),  # 8 - ACC_SESSION_TYPE
        _ws("currentTime", 15),  # 12
        _ws("lastTime", 15),  # 42
        _ws("bestTime", 15),  # 72
        _ws("split", 15),  # 102
        ("completedLaps", "i"),  # 132 - double field (numberOfLaps)
        ("position", "i"),  # 136
        ("iCurrentTime", "i"),  # 140 - ms
        ("iLastTime", "i"),  # 144 - ms
        ("iBestTime", "i"),  # 148 - ms
        ("sessionTimeLeft", "f"),  # 152
        ("distanceTraveled", "f"),  # 156 - in the current stint
        ("isInPit", "i"),  # 160
        ("currentSectorIndex", "i"),  # 164
        ("lastSectorTime", "i"),  # 168 - ms
        ("numberOfLaps", "i"),  # 172 - double field (completedLaps)
        _ws("tyreCompound", 33),  # 176
        ("_pad_242", "2s"),  # 242 - alignment
        ("replayTimeMultiplier", "f"),  # 244 - not used by ACC
        ("normalizedCarPosition", "f"),  # 248 - 0 start .. 1 finish
        ("activeCars", "i"),  # 252
        ("carCoordinates", "180f"),  # 256 - [60][3]
        ("carID", "60i"),  # 976
        ("playerCarID", "i"),  # 1216
        ("penaltyTime", "f"),  # 1220
        ("flag", "i"),  # 1224 - ACC_FLAG_TYPE
        ("penalty", "i"),  # 1228 - ACC_PENALTY_TYPE
        ("idealLineOn", "i"),  # 1232
        ("isInPitLane", "i"),  # 1236
        ("surfaceGrip", "f"),  # 1240
        ("mandatoryPitDone", "i"),  # 1244
        ("windSpeed", "f"),  # 1248 - m/s
        ("windDirection", "f"),  # 1252 - rad
        ("isSetupMenuVisible", "i"),  # 1256
        ("mainDisplayIndex", "i"),  # 1260
        ("secondaryDisplyIndex", "i"),  # 1264 - Kunos' spelling
        ("TC", "i"),  # 1268 - traction control level
        ("TCCUT", "i"),  # 1272
        ("EngineMap", "i"),  # 1276
        ("ABS", "i"),  # 1280 - ABS level
        ("fuelXLap", "f"),  # 1284 - litres per lap
        ("rainLights", "i"),  # 1288
        ("flashingLights", "i"),  # 1292
        ("lightsStage", "i"),  # 1296
        ("exhaustTemperature", "f"),  # 1300
        ("wiperLV", "i"),  # 1304
        ("driverStintTotalTimeLeft", "i"),  # 1308 - ms
        ("driverStintTimeLeft", "i"),  # 1312 - ms
        ("rainTyres", "i"),  # 1316
        ("sessionIndex", "i"),  # 1320
        ("usedFuel", "f"),  # 1324
        _ws("deltaLapTime", 15),  # 1328
        ("_pad_1358", "2s"),  # 1358 - alignment
        ("iDeltaLapTime", "i"),  # 1360 - ms
        _ws("estimatedLapTime", 15),  # 1364
        ("_pad_1394", "2s"),  # 1394 - alignment
        ("iEstimatedLapTime", "i"),  # 1396 - ms
        ("isDeltaPositive", "i"),  # 1400
        ("iSplit", "i"),  # 1404 - ms
        ("isValidLap", "i"),  # 1408
        ("fuelEstimatedLaps", "f"),  # 1412
        _ws("trackStatus", 33),  # 1416
        ("_pad_1482", "2s"),  # 1482 - alignment
        ("missingMandatoryPits", "i"),  # 1484
        ("Clock", "f"),  # 1488 - time of day, s
        ("directionLightsLeft", "i"),  # 1492
        ("directionLightsRight", "i"),  # 1496
        ("GlobalYellow", "i"),  # 1500
        ("GlobalYellow1", "i"),  # 1504
        ("GlobalYellow2", "i"),  # 1508
        ("GlobalYellow3", "i"),  # 1512
        ("GlobalWhite", "i"),  # 1516
        ("GlobalGreen", "i"),  # 1520
        ("GlobalChequered", "i"),  # 1524
        ("GlobalRed", "i"),  # 1528
        ("mfdTyreSet", "i"),  # 1532
        ("mfdFuelToAdd", "f"),  # 1536
        ("mfdTyrePressureLF", "f"),  # 1540
        ("mfdTyrePressureRF", "f"),  # 1544
        ("mfdTyrePressureLR", "f"),  # 1548
        ("mfdTyrePressureRR", "f"),  # 1552
        ("trackGripStatus", "i"),  # 1556 - ACC_TRACK_GRIP_STATUS
        ("rainIntensity", "i"),  # 1560 - ACC_RAIN_INTENSITY
        ("rainIntensityIn10min", "i"),  # 1564
        ("rainIntensityIn30min", "i"),  # 1568
        ("currentTyreSet", "i"),  # 1572
        ("strategyTyreSet", "i"),  # 1576
        ("gapAhead", "i"),  # 1580 - ms
        ("gapBehind", "i"),  # 1584 - ms
    ],
)

# ---------------------------------------------------------------------------------------------- SPageFileStatic
# "Initialized when the instance starts and never changes until the instance is closed."
STATIC = StructDef(
    "SPageFileStatic",
    [
        _ws("smVersion", 15),  # 0
        _ws("acVersion", 15),  # 30
        ("numberOfSessions", "i"),  # 60
        ("numCars", "i"),  # 64
        _ws("carModel", 33),  # 68 - Kunos id (Appendix 2)
        _ws("track", 33),  # 134
        _ws("playerName", 33),  # 200 - personal: never decoded by pitwall
        _ws("playerSurname", 33),  # 266 - personal: never decoded by pitwall
        _ws("playerNick", 33),  # 332 - personal: never decoded by pitwall
        ("_pad_398", "2s"),  # 398 - alignment
        ("sectorCount", "i"),  # 400
        ("maxTorque", "f"),  # 404 - not shown in ACC
        ("maxPower", "f"),  # 408 - not shown in ACC
        ("maxRpm", "i"),  # 412
        ("maxFuel", "f"),  # 416
        _w("suspensionMaxTravel"),  # 420 - not shown in ACC
        _w("tyreRadius"),  # 436 - not shown in ACC
        ("maxTurboBoost", "f"),  # 452 - not used by ACC
        ("deprecated_1", "f"),  # 456
        ("deprecated_2", "f"),  # 460
        ("penaltiesEnabled", "i"),  # 464
        ("aidFuelRate", "f"),  # 468
        ("aidTireRate", "f"),  # 472
        ("aidMechanicalDamage", "f"),  # 476
        ("AllowTyreBlankets", "f"),  # 480 - PDF: float (sample header: int aidAllowTyreBlankets)
        ("aidStability", "f"),  # 484
        ("aidAutoclutch", "i"),  # 488
        ("aidAutoBlip", "i"),  # 492
        ("hasDRS", "i"),  # 496 - not used by ACC
        ("hasERS", "i"),  # 500 - not used by ACC
        ("hasKERS", "i"),  # 504 - not used by ACC
        ("kersMaxJ", "f"),  # 508 - not used by ACC
        ("engineBrakeSettingsCount", "i"),  # 512 - not used by ACC
        ("ersPowerControllerCount", "i"),  # 516 - not used by ACC
        ("trackSplineLength", "f"),  # 520 - not used by ACC
        _ws("trackConfiguration", 33),  # 524 - not used by ACC; [33] from the sample header (PDF: no length)
        ("_pad_590", "2s"),  # 590 - alignment
        ("ersMaxJ", "f"),  # 592 - not used by ACC
        ("isTimedRace", "i"),  # 596 - not used by ACC
        ("hasExtraLap", "i"),  # 600 - not used by ACC
        _ws("carSkin", 33),  # 604 - not used by ACC
        ("_pad_670", "2s"),  # 670 - alignment
        ("reversedGridPositions", "i"),  # 672 - not used by ACC
        ("PitWindowStart", "i"),  # 676
        ("PitWindowEnd", "i"),  # 680
        ("isOnline", "i"),  # 684
        _ws("dryTyresName", 33),  # 688
        _ws("wetTyresName", 33),  # 754
    ],
)

assert PHYSICS.size == 800
assert GRAPHICS.size == 1588
assert STATIC.size == 820

PAD_PREFIX = "_pad_"


@dataclass(frozen=True, slots=True)
class Page:
    """One shared-memory page: its mapping name, Pitwall's snapshot tag and its layout."""

    kind: str  # "physics" | "graphics" | "static" (DecodeStats keys)
    mapping: str
    tag: bytes
    layout: StructDef

    @property
    def size(self) -> int:
        return self.layout.size

    @property
    def snapshot_size(self) -> int:
        return TAG_SIZE + self.layout.size


PHYSICS_PAGE = Page("physics", PHYSICS_MAPPING, TAG_PHYSICS, PHYSICS)
GRAPHICS_PAGE = Page("graphics", GRAPHICS_MAPPING, TAG_GRAPHICS, GRAPHICS)
STATIC_PAGE = Page("static", STATIC_MAPPING, TAG_STATIC, STATIC)
PAGES: tuple[Page, ...] = (PHYSICS_PAGE, GRAPHICS_PAGE, STATIC_PAGE)
PAGE_BY_TAG: dict[bytes, Page] = {p.tag: p for p in PAGES}


class PacketError(ValueError):
    """A snapshot does not have a known tag and the exact size of that page."""


def page_of(data: bytes) -> Page | None:
    """The page a snapshot carries, or None when its tag or size is not one of Pitwall's ACC snapshots."""
    page = PAGE_BY_TAG.get(bytes(data[:TAG_SIZE]))
    return page if page is not None and len(data) == page.snapshot_size else None


def snapshot(page: Page, body: bytes) -> bytes:
    """Frame one page copy as a snapshot (what the shared-memory reader hands the router)."""
    if len(body) != page.size:
        raise PacketError(f"{page.layout.name} must be {page.size} bytes, got {len(body)}")
    return page.tag + body


def parse(data: bytes) -> tuple[Page, dict[str, Any]]:
    """Raw field values of one snapshot (Kunos' names; padding included). No interpretation: that is the adapter's."""
    page = page_of(data)
    if page is None:
        raise PacketError(
            f"not an ACC snapshot: tag {bytes(data[:TAG_SIZE])!r}, {len(data)} bytes (expected PHYS+800, GRPH+1588 "
            "or STAT+820)"
        )
    return page, page.layout.unpack_from(data, TAG_SIZE)


def encode(page: Page, values: Mapping[str, Any] | None = None) -> bytes:
    """A whole snapshot from field values (missing fields are zero); for synthetic streams and tests."""
    return snapshot(page, page.layout.pack(values))


def field_offsets(sd: StructDef) -> dict[str, tuple[int, str]]:
    """``{field: (byte offset, struct format)}`` - what the tests compare with the documentation."""
    out: dict[str, tuple[int, str]] = {}
    off = 0
    for name, fmt in sd.fields:
        out[name] = (off, fmt)
        off += StructDef("_", [(name, fmt)]).size
    return out


# ---------------------------------------------------------------------------------------------- strings
def decode_wstring(raw: bytes) -> str | None:
    """A fixed ``wchar_t[N]`` field (UTF-16LE): up to the first NUL, control characters dropped, empty -> None.

    Undecodable code units become U+FFFD and non-printable characters are removed, so a corrupt page can never inject
    newlines or escape codes into logs or the UI.
    """
    end = len(raw) - (len(raw) % 2)
    for i in range(0, end, 2):
        if raw[i] == 0 and raw[i + 1] == 0:
            end = i
            break
    text = bytes(raw[:end]).decode("utf-16-le", errors="replace")
    text = "".join(ch for ch in text if ch.isprintable()).strip()
    return text or None


def encode_wstring(text: str, chars: int) -> bytes:
    """``text`` as a NUL-padded ``wchar_t[chars]`` field (at most ``chars - 1`` code units, so it stays terminated)."""
    raw = text.encode("utf-16-le")
    if len(raw) > 2 * (chars - 1):
        raise ValueError(f"string longer than {chars - 1} UTF-16 code units: {text!r}")
    return raw.ljust(2 * chars, b"\0")


# ---------------------------------------------------------------------------------------------- Appendix 2
# Kunos' Appendix 2 ("carModel"): the Static.carModel id -> the car's name, as listed in v1.8.12 (cars up to the 2022
# Challengers Pack; later DLC cars are not in the PDF and keep their raw id as the name). Grouped as in the PDF.
CAR_MODELS: dict[str, str] = {
    # GT3 - 2018
    "amr_v12_vantage_gt3": "Aston Martin Vantage V12 GT3 2013",
    "audi_r8_lms": "Audi R8 LMS 2015",
    "bentley_continental_gt3_2016": "Bentley Continental GT3 2015",
    "bentley_continental_gt3_2018": "Bentley Continental GT3 2018",
    "bmw_m6_gt3": "BMW M6 GT3 2017",
    "jaguar_g3": "Emil Frey Jaguar G3 2012",
    "ferrari_488_gt3": "Ferrari 488 GT3 2018",
    "honda_nsx_gt3": "Honda NSX GT3 2017",
    "lamborghini_gallardo_rex": "Lamborghini Gallardo G3 Reiter 2017",
    "lamborghini_huracan_gt3": "Lamborghini Huracan GT3 2015",
    "lamborghini_huracan_st": "Lamborghini Huracan ST 2015",
    "lexus_rc_f_gt3": "Lexus RCF GT3 2016",
    "mclaren_650s_gt3": "McLaren 650S GT3 2015",
    "mercedes_amg_gt3": "Mercedes AMG GT3 2015",
    "nissan_gt_r_gt3_2017": "Nissan GTR Nismo GT3 2015",
    "nissan_gt_r_gt3_2018": "Nissan GTR Nismo GT3 2018",
    "porsche_991_gt3_r": "Porsche 991 GT3 R 2018",
    "porsche_991ii_gt3_cup": "Porsche 991 II GT3 Cup 2017",
    # GT3 - 2019
    "amr_v8_vantage_gt3": "Aston Martin V8 Vantage GT3 2019",
    "audi_r8_lms_evo": "Audi R8 LMS Evo 2019",
    "honda_nsx_gt3_evo": "Honda NSX GT3 Evo 2019",
    "lamborghini_huracan_gt3_evo": "Lamborghini Huracan GT3 EVO 2019",
    "mclaren_720s_gt3": "McLaren 720S GT3 2019",
    "porsche_991ii_gt3_r": "Porsche 911 II GT3 R 2019",
    # GT4
    "alpine_a110_gt4": "Alpine A110 GT4 2018",
    "amr_v8_vantage_gt4": "Aston Martin Vantage AMR GT4 2018",
    "audi_r8_gt4": "Audi R8 LMS GT4 2016",
    "bmw_m4_gt4": "BMW M4 GT4 2018",
    "chevrolet_camaro_gt4r": "Chevrolet Camaro GT4 R 2017",
    "ginetta_g55_gt4": "Ginetta G55 GT4 2012",
    "ktm_xbow_gt4": "KTM X-Bow GT4 2016",
    "maserati_mc_gt4": "Maserati Gran Turismo MC GT4 2016",
    "mclaren_570s_gt4": "McLaren 570S GT4 2016",
    "mercedes_amg_gt4": "Mercedes AMG GT4 2016",
    "porsche_718_cayman_gt4_mr": "Porsche 718 Cayman GT4 MR 2019",
    # GT3 - 2020
    "ferrari_488_gt3_evo": "Ferrari 488 GT3 Evo 2020",
    "mercedes_amg_gt3_evo": "Mercedes AMG GT3 Evo 2020",
    # GT3 - 2021
    "bmw_m4_gt3": "BMW M4 GT3 2021",
    # Challengers Pack - 2022
    "audi_r8_lms_evo_ii": "Audi R8 LMS Evo II 2022",
    "bmw_m2_cs_racing": "BMW M2 Cup 2020",
    "ferrari_488_challenge_evo": "Ferrari 488 Challenge Evo 2020",
    "lamborghini_huracan_st_evo2": "Lamborghini Huracan ST Evo2 2021",
    "porsche_992_gt3_cup": "Porsche 992 GT3 Cup 2021",
}

# Kunos' Appendix 7 ("Max RPM") by Appendix 2 id. Static.maxRpm of a listed car must equal it: a cheap check, on the
# first real page, that Static is laid out as documented (maxRpm sits at offset 412, after the alignment padding).
CAR_MAX_RPM: dict[str, int] = {
    "amr_v12_vantage_gt3": 7750,
    "audi_r8_lms": 8650,
    "bentley_continental_gt3_2016": 7500,
    "bentley_continental_gt3_2018": 7400,
    "bmw_m6_gt3": 7100,
    "jaguar_g3": 8750,
    "ferrari_488_gt3": 7300,
    "honda_nsx_gt3": 7500,
    "lamborghini_gallardo_rex": 8650,
    "lamborghini_huracan_gt3": 8650,
    "lamborghini_huracan_st": 8650,
    "lexus_rc_f_gt3": 7750,
    "mclaren_650s_gt3": 7500,
    "mercedes_amg_gt3": 7900,
    "nissan_gt_r_gt3_2017": 7500,
    "nissan_gt_r_gt3_2018": 7500,
    "porsche_991_gt3_r": 9250,
    "porsche_991ii_gt3_cup": 8500,
    "amr_v8_vantage_gt3": 7250,
    "audi_r8_lms_evo": 8650,
    "honda_nsx_gt3_evo": 7650,
    "lamborghini_huracan_gt3_evo": 8650,
    "mclaren_720s_gt3": 7700,
    "porsche_991ii_gt3_r": 9250,
    "alpine_a110_gt4": 6450,
    "amr_v8_vantage_gt4": 7000,
    "audi_r8_gt4": 8650,
    "bmw_m4_gt4": 7600,
    "chevrolet_camaro_gt4r": 7500,
    "ginetta_g55_gt4": 7200,
    "ktm_xbow_gt4": 6500,
    "maserati_mc_gt4": 7000,
    "mclaren_570s_gt4": 7600,
    "mercedes_amg_gt4": 7000,
    "porsche_718_cayman_gt4_mr": 7800,
    "ferrari_488_gt3_evo": 7600,
    "mercedes_amg_gt3_evo": 7600,
    "bmw_m4_gt3": 7000,
    "audi_r8_lms_evo_ii": 8650,
    "bmw_m2_cs_racing": 7520,
    "ferrari_488_challenge_evo": 8000,
    "lamborghini_huracan_st_evo2": 8650,
    "porsche_992_gt3_cup": 8750,
}
