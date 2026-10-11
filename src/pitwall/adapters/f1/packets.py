"""EA SPORTS F1 25 UDP packet layouts: packetFormat 2025 (base game) and 2026 (2026 Season Pack DLC).

Source of truth: EA's official "F1 25 UDP Specification" (see docs/research/f1-udp-spec.md for URLs and
cross-checks). All structs are little-endian and packed. Each packet = 29-byte header + body.

Field names keep the spec's names (minus the ``m_`` prefix) so they can be checked against the spec
line-by-line. Normalisation into the unified model happens in ``normalise.py``, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from pitwall.adapters.structdef import StructDef

PACKET_FORMAT_2025 = 2025
MAX_CARS = 22


class PacketId(IntEnum):
    MOTION = 0
    SESSION = 1
    LAP_DATA = 2
    EVENT = 3
    PARTICIPANTS = 4
    CAR_SETUPS = 5
    CAR_TELEMETRY = 6
    CAR_STATUS = 7
    FINAL_CLASSIFICATION = 8
    LOBBY_INFO = 9
    CAR_DAMAGE = 10
    SESSION_HISTORY = 11
    TYRE_SETS = 12
    MOTION_EX = 13
    TIME_TRIAL = 14
    LAP_POSITIONS = 15
    CAR_TELEMETRY_2 = 16  # format 2026 only


HEADER = StructDef(
    "PacketHeader",
    [
        ("packetFormat", "H"),
        ("gameYear", "B"),
        ("gameMajorVersion", "B"),
        ("gameMinorVersion", "B"),
        ("packetVersion", "B"),
        ("packetId", "B"),
        ("sessionUID", "Q"),
        ("sessionTime", "f"),
        ("frameIdentifier", "I"),
        ("overallFrameIdentifier", "I"),
        ("playerCarIndex", "B"),
        ("secondaryPlayerCarIndex", "B"),
    ],
)

# --- Motion (0) ---------------------------------------------------------------------------------
CAR_MOTION = StructDef(
    "CarMotionData",
    [
        ("worldPositionX", "f"),
        ("worldPositionY", "f"),
        ("worldPositionZ", "f"),
        ("worldVelocityX", "f"),
        ("worldVelocityY", "f"),
        ("worldVelocityZ", "f"),
        ("worldForwardDirX", "h"),
        ("worldForwardDirY", "h"),
        ("worldForwardDirZ", "h"),
        ("worldRightDirX", "h"),
        ("worldRightDirY", "h"),
        ("worldRightDirZ", "h"),
        ("gForceLateral", "f"),
        ("gForceLongitudinal", "f"),
        ("gForceVertical", "f"),
        ("yaw", "f"),
        ("pitch", "f"),
        ("roll", "f"),
    ],
)

# --- Session (1) -----------------------------------------------------------------------------------
MARSHAL_ZONE = StructDef("MarshalZone", [("zoneStart", "f"), ("zoneFlag", "b")])
WEATHER_FORECAST_SAMPLE = StructDef(
    "WeatherForecastSample",
    [
        ("sessionType", "B"),
        ("timeOffset", "B"),
        ("weather", "B"),
        ("trackTemperature", "b"),
        ("trackTemperatureChange", "b"),
        ("airTemperature", "b"),
        ("airTemperatureChange", "b"),
        ("rainPercentage", "B"),
    ],
)
SESSION_HEAD = StructDef(
    "SessionHead",
    [
        ("weather", "B"),
        ("trackTemperature", "b"),
        ("airTemperature", "b"),
        ("totalLaps", "B"),
        ("trackLength", "H"),
        ("sessionType", "B"),
        ("trackId", "b"),
        ("formula", "B"),
        ("sessionTimeLeft", "H"),
        ("sessionDuration", "H"),
        ("pitSpeedLimit", "B"),
        ("gamePaused", "B"),
        ("isSpectating", "B"),
        ("spectatorCarIndex", "B"),
        ("sliProNativeSupport", "B"),
        ("numMarshalZones", "B"),
    ],
)
NUM_MARSHAL_ZONES = 21
SESSION_MID = StructDef(
    "SessionMid",
    [("safetyCarStatus", "B"), ("networkGame", "B"), ("numWeatherForecastSamples", "B")],
)
NUM_WEATHER_SAMPLES = 64
SESSION_TAIL = StructDef(
    "SessionTail",
    [
        ("forecastAccuracy", "B"),
        ("aiDifficulty", "B"),
        ("seasonLinkIdentifier", "I"),
        ("weekendLinkIdentifier", "I"),
        ("sessionLinkIdentifier", "I"),
        ("pitStopWindowIdealLap", "B"),
        ("pitStopWindowLatestLap", "B"),
        ("pitStopRejoinPosition", "B"),
        ("steeringAssist", "B"),
        ("brakingAssist", "B"),
        ("gearboxAssist", "B"),
        ("pitAssist", "B"),
        ("pitReleaseAssist", "B"),
        ("ERSAssist", "B"),
        ("DRSAssist", "B"),
        ("dynamicRacingLine", "B"),
        ("dynamicRacingLineType", "B"),
        ("gameMode", "B"),
        ("ruleSet", "B"),
        ("timeOfDay", "I"),
        ("sessionLength", "B"),
        ("speedUnitsLeadPlayer", "B"),
        ("temperatureUnitsLeadPlayer", "B"),
        ("speedUnitsSecondaryPlayer", "B"),
        ("temperatureUnitsSecondaryPlayer", "B"),
        ("numSafetyCarPeriods", "B"),
        ("numVirtualSafetyCarPeriods", "B"),
        ("numRedFlagPeriods", "B"),
        ("equalCarPerformance", "B"),
        ("recoveryMode", "B"),
        ("flashbackLimit", "B"),
        ("surfaceType", "B"),
        ("lowFuelMode", "B"),
        ("raceStarts", "B"),
        ("tyreTemperature", "B"),
        ("pitLaneTyreSim", "B"),
        ("carDamage", "B"),
        ("carDamageRate", "B"),
        ("collisions", "B"),
        ("collisionsOffForFirstLapOnly", "B"),
        ("mpUnsafePitRelease", "B"),
        ("mpOffForGriefing", "B"),
        ("cornerCuttingStringency", "B"),
        ("parcFermeRules", "B"),
        ("pitStopExperience", "B"),
        ("safetyCar", "B"),
        ("safetyCarExperience", "B"),
        ("formationLap", "B"),
        ("formationLapExperience", "B"),
        ("redFlags", "B"),
        ("affectsLicenceLevelSolo", "B"),
        ("affectsLicenceLevelMP", "B"),
        ("numSessionsInWeekend", "B"),
        ("weekendStructure", "12B"),
        ("sector2LapDistanceStart", "f"),
        ("sector3LapDistanceStart", "f"),
    ],
)
SESSION_BODY_SIZE = (
    SESSION_HEAD.size
    + NUM_MARSHAL_ZONES * MARSHAL_ZONE.size
    + SESSION_MID.size
    + NUM_WEATHER_SAMPLES * WEATHER_FORECAST_SAMPLE.size
    + SESSION_TAIL.size
)
# Absolute byte offsets inside the Session packet (header included). Identical in formats 2025 and 2026 (the 2026
# packet only appends to the tail); tests check them against the spec's offset tables.
SESSION_HEAD_OFFSET = HEADER.size  # 29: m_weather
SESSION_MARSHAL_ZONES_OFFSET = SESSION_HEAD_OFFSET + SESSION_HEAD.size  # 48: m_marshalZones[21]
SESSION_MID_OFFSET = SESSION_MARSHAL_ZONES_OFFSET + NUM_MARSHAL_ZONES * MARSHAL_ZONE.size  # 153: m_safetyCarStatus
SESSION_FORECAST_OFFSET = SESSION_MID_OFFSET + SESSION_MID.size  # 156: m_weatherForecastSamples[64]
SESSION_TAIL_OFFSET = SESSION_FORECAST_OFFSET + NUM_WEATHER_SAMPLES * WEATHER_FORECAST_SAMPLE.size  # 668

# --- Lap data (2) ------------------------------------------------------------------------------------
LAP_DATA = StructDef(
    "LapData",
    [
        ("lastLapTimeInMS", "I"),
        ("currentLapTimeInMS", "I"),
        ("sector1TimeMSPart", "H"),
        ("sector1TimeMinutesPart", "B"),
        ("sector2TimeMSPart", "H"),
        ("sector2TimeMinutesPart", "B"),
        ("deltaToCarInFrontMSPart", "H"),
        ("deltaToCarInFrontMinutesPart", "B"),
        ("deltaToRaceLeaderMSPart", "H"),
        ("deltaToRaceLeaderMinutesPart", "B"),
        ("lapDistance", "f"),
        ("totalDistance", "f"),
        ("safetyCarDelta", "f"),
        ("carPosition", "B"),
        ("currentLapNum", "B"),
        ("pitStatus", "B"),
        ("numPitStops", "B"),
        ("sector", "B"),
        ("currentLapInvalid", "B"),
        ("penalties", "B"),
        ("totalWarnings", "B"),
        ("cornerCuttingWarnings", "B"),
        ("numUnservedDriveThroughPens", "B"),
        ("numUnservedStopGoPens", "B"),
        ("gridPosition", "B"),
        ("driverStatus", "B"),
        ("resultStatus", "B"),
        ("pitLaneTimerActive", "B"),
        ("pitLaneTimeInLaneInMS", "H"),
        ("pitStopTimerInMS", "H"),
        ("pitStopShouldServePen", "B"),
        ("speedTrapFastestSpeed", "f"),
        ("speedTrapFastestLap", "B"),
    ],
)
LAP_DATA_TAIL = StructDef("LapDataTail", [("timeTrialPBCarIdx", "B"), ("timeTrialRivalCarIdx", "B")])

# --- Event (3) ---------------------------------------------------------------------------------------
EVENT_CODE_SIZE = 4
EVENT_DETAILS_SIZE = 12  # sizeof(EventDataDetails) union == its largest member (SpeedTrap, 12 bytes)
EVENT_DETAILS: dict[str, StructDef] = {
    "FTLP": StructDef("FastestLap", [("vehicleIdx", "B"), ("lapTime", "f")]),
    "RTMT": StructDef("Retirement", [("vehicleIdx", "B"), ("reason", "B")]),
    "DRSD": StructDef("DRSDisabled", [("reason", "B")]),
    "TMPT": StructDef("TeamMateInPits", [("vehicleIdx", "B")]),
    "RCWN": StructDef("RaceWinner", [("vehicleIdx", "B")]),
    "PENA": StructDef(
        "Penalty",
        [
            ("penaltyType", "B"),
            ("infringementType", "B"),
            ("vehicleIdx", "B"),
            ("otherVehicleIdx", "B"),
            ("time", "B"),
            ("lapNum", "B"),
            ("placesGained", "B"),
        ],
    ),
    "SPTP": StructDef(
        "SpeedTrap",
        [
            ("vehicleIdx", "B"),
            ("speed", "f"),
            ("isOverallFastestInSession", "B"),
            ("isDriverFastestInSession", "B"),
            ("fastestVehicleIdxInSession", "B"),
            ("fastestSpeedInSession", "f"),
        ],
    ),
    "STLG": StructDef("StartLights", [("numLights", "B")]),
    "DTSV": StructDef("DriveThroughPenaltyServed", [("vehicleIdx", "B")]),
    "SGSV": StructDef("StopGoPenaltyServed", [("vehicleIdx", "B"), ("stopTime", "f")]),
    "FLBK": StructDef("Flashback", [("flashbackFrameIdentifier", "I"), ("flashbackSessionTime", "f")]),
    "BUTN": StructDef("Buttons", [("buttonStatus", "I")]),
    "OVTK": StructDef("Overtake", [("overtakingVehicleIdx", "B"), ("beingOvertakenVehicleIdx", "B")]),
    "SCAR": StructDef("SafetyCar", [("safetyCarType", "B"), ("eventType", "B")]),
    "COLL": StructDef("Collision", [("vehicle1Idx", "B"), ("vehicle2Idx", "B")]),
}
EVENT_CODES_NO_DETAILS = frozenset({"SSTA", "SEND", "DRSE", "CHQF", "LGOT", "RDFL"})

# --- Participants (4) ------------------------------------------------------------------------------
PARTICIPANT = StructDef(
    "ParticipantData",
    [
        ("aiControlled", "B"),
        ("driverId", "B"),
        ("networkId", "B"),
        ("teamId", "B"),
        ("myTeam", "B"),
        ("raceNumber", "B"),
        ("nationality", "B"),
        ("name", "32s"),
        ("yourTelemetry", "B"),
        ("showOnlineNames", "B"),
        ("techLevel", "H"),
        ("platform", "B"),
        ("numColours", "B"),
        ("liveryColours", "12B"),  # 4 x (red, green, blue)
    ],
)
PARTICIPANTS_HEAD = StructDef("ParticipantsHead", [("numActiveCars", "B")])

# --- Car setups (5) ----------------------------------------------------------------------------------
CAR_SETUP = StructDef(
    "CarSetupData",
    [
        ("frontWing", "B"),
        ("rearWing", "B"),
        ("onThrottle", "B"),
        ("offThrottle", "B"),
        ("frontCamber", "f"),
        ("rearCamber", "f"),
        ("frontToe", "f"),
        ("rearToe", "f"),
        ("frontSuspension", "B"),
        ("rearSuspension", "B"),
        ("frontAntiRollBar", "B"),
        ("rearAntiRollBar", "B"),
        ("frontSuspensionHeight", "B"),
        ("rearSuspensionHeight", "B"),
        ("brakePressure", "B"),
        ("brakeBias", "B"),
        ("engineBraking", "B"),
        ("rearLeftTyrePressure", "f"),
        ("rearRightTyrePressure", "f"),
        ("frontLeftTyrePressure", "f"),
        ("frontRightTyrePressure", "f"),
        ("ballast", "B"),
        ("fuelLoad", "f"),
    ],
)
CAR_SETUPS_TAIL = StructDef("CarSetupsTail", [("nextFrontWingValue", "f")])

# --- Car telemetry (6) -------------------------------------------------------------------------------
CAR_TELEMETRY = StructDef(
    "CarTelemetryData",
    [
        ("speed", "H"),
        ("throttle", "f"),
        ("steer", "f"),
        ("brake", "f"),
        ("clutch", "B"),
        ("gear", "b"),
        ("engineRPM", "H"),
        ("drs", "B"),
        ("revLightsPercent", "B"),
        ("revLightsBitValue", "H"),
        ("brakesTemperature", "4H"),
        ("tyresSurfaceTemperature", "4B"),
        ("tyresInnerTemperature", "4B"),
        ("engineTemperature", "H"),
        ("tyresPressure", "4f"),
        ("surfaceType", "4B"),
    ],
)
CAR_TELEMETRY_TAIL = StructDef(
    "CarTelemetryTail",
    [("mfdPanelIndex", "B"), ("mfdPanelIndexSecondaryPlayer", "B"), ("suggestedGear", "b")],
)

# --- Car status (7) ----------------------------------------------------------------------------------
CAR_STATUS = StructDef(
    "CarStatusData",
    [
        ("tractionControl", "B"),
        ("antiLockBrakes", "B"),
        ("fuelMix", "B"),
        ("frontBrakeBias", "B"),
        ("pitLimiterStatus", "B"),
        ("fuelInTank", "f"),
        ("fuelCapacity", "f"),
        ("fuelRemainingLaps", "f"),
        ("maxRPM", "H"),
        ("idleRPM", "H"),
        ("maxGears", "B"),
        ("drsAllowed", "B"),
        ("drsActivationDistance", "H"),
        ("actualTyreCompound", "B"),
        ("visualTyreCompound", "B"),
        ("tyresAgeLaps", "B"),
        ("vehicleFIAFlags", "b"),
        ("enginePowerICE", "f"),
        ("enginePowerMGUK", "f"),
        ("ersStoreEnergy", "f"),
        ("ersDeployMode", "B"),
        ("ersHarvestedThisLapMGUK", "f"),
        ("ersHarvestedThisLapMGUH", "f"),
        ("ersDeployedThisLap", "f"),
        ("networkPaused", "B"),
    ],
)

# --- Final classification (8) ------------------------------------------------------------------------
FINAL_CLASSIFICATION = StructDef(
    "FinalClassificationData",
    [
        ("position", "B"),
        ("numLaps", "B"),
        ("gridPosition", "B"),
        ("points", "B"),
        ("numPitStops", "B"),
        ("resultStatus", "B"),
        ("resultReason", "B"),
        ("bestLapTimeInMS", "I"),
        ("totalRaceTime", "d"),
        ("penaltiesTime", "B"),
        ("numPenalties", "B"),
        ("numTyreStints", "B"),
        ("tyreStintsActual", "8B"),
        ("tyreStintsVisual", "8B"),
        ("tyreStintsEndLaps", "8B"),
    ],
)
FINAL_CLASSIFICATION_HEAD = StructDef("FinalClassificationHead", [("numCars", "B")])

# --- Lobby info (9) ----------------------------------------------------------------------------------
LOBBY_INFO = StructDef(
    "LobbyInfoData",
    [
        ("aiControlled", "B"),
        ("teamId", "B"),
        ("nationality", "B"),
        ("platform", "B"),
        ("name", "32s"),
        ("carNumber", "B"),
        ("yourTelemetry", "B"),
        ("showOnlineNames", "B"),
        ("techLevel", "H"),
        ("readyStatus", "B"),
    ],
)
LOBBY_INFO_HEAD = StructDef("LobbyInfoHead", [("numPlayers", "B")])

# --- Car damage (10) ---------------------------------------------------------------------------------
CAR_DAMAGE = StructDef(
    "CarDamageData",
    [
        ("tyresWear", "4f"),
        ("tyresDamage", "4B"),
        ("brakesDamage", "4B"),
        ("tyreBlisters", "4B"),
        ("frontLeftWingDamage", "B"),
        ("frontRightWingDamage", "B"),
        ("rearWingDamage", "B"),
        ("floorDamage", "B"),
        ("diffuserDamage", "B"),
        ("sidepodDamage", "B"),
        ("drsFault", "B"),
        ("ersFault", "B"),
        ("gearBoxDamage", "B"),
        ("engineDamage", "B"),
        ("engineMGUHWear", "B"),
        ("engineESWear", "B"),
        ("engineCEWear", "B"),
        ("engineICEWear", "B"),
        ("engineMGUKWear", "B"),
        ("engineTCWear", "B"),
        ("engineBlown", "B"),
        ("engineSeized", "B"),
    ],
)

# --- Session history (11) ----------------------------------------------------------------------------
SESSION_HISTORY_HEAD = StructDef(
    "SessionHistoryHead",
    [
        ("carIdx", "B"),
        ("numLaps", "B"),
        ("numTyreStints", "B"),
        ("bestLapTimeLapNum", "B"),
        ("bestSector1LapNum", "B"),
        ("bestSector2LapNum", "B"),
        ("bestSector3LapNum", "B"),
    ],
)
LAP_HISTORY = StructDef(
    "LapHistoryData",
    [
        ("lapTimeInMS", "I"),
        ("sector1TimeMSPart", "H"),
        ("sector1TimeMinutesPart", "B"),
        ("sector2TimeMSPart", "H"),
        ("sector2TimeMinutesPart", "B"),
        ("sector3TimeMSPart", "H"),
        ("sector3TimeMinutesPart", "B"),
        ("lapValidBitFlags", "B"),
    ],
)
NUM_LAP_HISTORY = 100
TYRE_STINT_HISTORY = StructDef(
    "TyreStintHistoryData",
    [("endLap", "B"), ("tyreActualCompound", "B"), ("tyreVisualCompound", "B")],
)
NUM_TYRE_STINTS = 8

# --- Tyre sets (12) -----------------------------------------------------------------------------------
TYRE_SET = StructDef(
    "TyreSetData",
    [
        ("actualTyreCompound", "B"),
        ("visualTyreCompound", "B"),
        ("wear", "B"),
        ("available", "B"),
        ("recommendedSession", "B"),
        ("lifeSpan", "B"),
        ("usableLife", "B"),
        ("lapDeltaTime", "h"),
        ("fitted", "B"),
    ],
)
NUM_TYRE_SETS = 20
TYRE_SETS_HEAD = StructDef("TyreSetsHead", [("carIdx", "B")])
TYRE_SETS_TAIL = StructDef("TyreSetsTail", [("fittedIdx", "B")])

# --- Motion ex (13), player car only -------------------------------------------------------------------
MOTION_EX = StructDef(
    "PacketMotionExData",
    [
        ("suspensionPosition", "4f"),
        ("suspensionVelocity", "4f"),
        ("suspensionAcceleration", "4f"),
        ("wheelSpeed", "4f"),
        ("wheelSlipRatio", "4f"),
        ("wheelSlipAngle", "4f"),
        ("wheelLatForce", "4f"),
        ("wheelLongForce", "4f"),
        ("heightOfCOGAboveGround", "f"),
        ("localVelocityX", "f"),
        ("localVelocityY", "f"),
        ("localVelocityZ", "f"),
        ("angularVelocityX", "f"),
        ("angularVelocityY", "f"),
        ("angularVelocityZ", "f"),
        ("angularAccelerationX", "f"),
        ("angularAccelerationY", "f"),
        ("angularAccelerationZ", "f"),
        ("frontWheelsAngle", "f"),
        ("wheelVertForce", "4f"),
        ("frontAeroHeight", "f"),
        ("rearAeroHeight", "f"),
        ("frontRollAngle", "f"),
        ("rearRollAngle", "f"),
        ("chassisYaw", "f"),
        ("chassisPitch", "f"),
        ("wheelCamber", "4f"),
        ("wheelCamberGain", "4f"),
    ],
)

# --- Time trial (14) -------------------------------------------------------------------------------------
TIME_TRIAL_DATASET = StructDef(
    "TimeTrialDataSet",
    [
        ("carIdx", "B"),
        ("teamId", "B"),
        ("lapTimeInMS", "I"),
        ("sector1TimeInMS", "I"),
        ("sector2TimeInMS", "I"),
        ("sector3TimeInMS", "I"),
        ("tractionControl", "B"),
        ("gearboxAssist", "B"),
        ("antiLockBrakes", "B"),
        ("equalCarPerformance", "B"),
        ("customSetup", "B"),
        ("valid", "B"),
    ],
)

# --- Lap positions (15) ---------------------------------------------------------------------------------
LAP_POSITIONS_HEAD = StructDef("LapPositionsHead", [("numLaps", "B"), ("lapStart", "B")])
LAP_POSITIONS_MAX_LAPS = 50


@dataclass(frozen=True, slots=True)
class PacketLayout:
    packet_id: PacketId
    size: int  # total size including header


def _size(body: int) -> int:
    return HEADER.size + body


PACKET_SIZES: dict[PacketId, int] = {
    PacketId.MOTION: _size(MAX_CARS * CAR_MOTION.size),
    PacketId.SESSION: _size(SESSION_BODY_SIZE),
    PacketId.LAP_DATA: _size(MAX_CARS * LAP_DATA.size + LAP_DATA_TAIL.size),
    PacketId.EVENT: _size(EVENT_CODE_SIZE + EVENT_DETAILS_SIZE),
    PacketId.PARTICIPANTS: _size(PARTICIPANTS_HEAD.size + MAX_CARS * PARTICIPANT.size),
    PacketId.CAR_SETUPS: _size(MAX_CARS * CAR_SETUP.size + CAR_SETUPS_TAIL.size),
    PacketId.CAR_TELEMETRY: _size(MAX_CARS * CAR_TELEMETRY.size + CAR_TELEMETRY_TAIL.size),
    PacketId.CAR_STATUS: _size(MAX_CARS * CAR_STATUS.size),
    PacketId.FINAL_CLASSIFICATION: _size(FINAL_CLASSIFICATION_HEAD.size + MAX_CARS * FINAL_CLASSIFICATION.size),
    PacketId.LOBBY_INFO: _size(LOBBY_INFO_HEAD.size + MAX_CARS * LOBBY_INFO.size),
    PacketId.CAR_DAMAGE: _size(MAX_CARS * CAR_DAMAGE.size),
    PacketId.SESSION_HISTORY: _size(
        SESSION_HISTORY_HEAD.size + NUM_LAP_HISTORY * LAP_HISTORY.size + NUM_TYRE_STINTS * TYRE_STINT_HISTORY.size
    ),
    PacketId.TYRE_SETS: _size(TYRE_SETS_HEAD.size + NUM_TYRE_SETS * TYRE_SET.size + TYRE_SETS_TAIL.size),
    PacketId.MOTION_EX: _size(MOTION_EX.size),
    PacketId.TIME_TRIAL: _size(3 * TIME_TRIAL_DATASET.size),
    PacketId.LAP_POSITIONS: _size(LAP_POSITIONS_HEAD.size + LAP_POSITIONS_MAX_LAPS * MAX_CARS),
}

# Sizes published in the EA F1 25 specification ("Size: N bytes" lines). Asserted in tests so that a
# typo in any struct above fails loudly instead of silently mis-parsing.
SPEC_PUBLISHED_SIZES: dict[PacketId, int] = {
    PacketId.MOTION: 1349,
    PacketId.SESSION: 753,
    PacketId.LAP_DATA: 1285,
    PacketId.EVENT: 45,
    PacketId.PARTICIPANTS: 1284,
    PacketId.CAR_SETUPS: 1133,
    PacketId.CAR_TELEMETRY: 1352,
    PacketId.CAR_STATUS: 1239,
    PacketId.FINAL_CLASSIFICATION: 1042,
    PacketId.LOBBY_INFO: 954,
    PacketId.CAR_DAMAGE: 1041,
    PacketId.SESSION_HISTORY: 1460,
    PacketId.TYRE_SETS: 231,
    PacketId.MOTION_EX: 273,
    PacketId.TIME_TRIAL: 101,
    PacketId.LAP_POSITIONS: 1131,
}


# =====================================================================================================
# Format 2026 ("F1 25: 2026 Season Pack"). 24 cars per array; changed structs below, everything else is
# byte-identical to 2025 (header, LapData, CarSetupData, CarDamageData, FinalClassificationData, history,
# tyre sets, MotionEx, marshal zones, forecast samples). See docs/research/f1-udp-spec.md section 7.
# =====================================================================================================
PACKET_FORMAT_2026 = 2026
MAX_CARS_2026 = 24
GFORCE_SCALE_2026 = 1.0 / 1000.0  # int16 quantised g-forces; divide by 1000 (EA spec)

CAR_MOTION_2026 = StructDef(
    "CarMotionData",
    [
        *CAR_MOTION.fields[:12],
        ("gForceLateral", "h"),
        ("gForceLongitudinal", "h"),
        ("gForceVertical", "h"),
        ("yaw", "f"),
        ("pitch", "f"),
        ("roll", "f"),
    ],
)
PARTICIPANT_2026 = StructDef(
    "ParticipantData",
    [
        ("aiControlled", "B"),
        ("driverId", "H"),
        ("networkId", "H"),
        ("teamId", "H"),
        ("myTeam", "B"),
        ("raceNumber", "B"),
        ("nationality", "B"),
        ("name", "32s"),
        ("yourTelemetry", "B"),
        ("showOnlineNames", "B"),
        ("techLevel", "H"),
        ("platform", "B"),
        ("numColours", "B"),
        ("liveryColours", "12B"),
    ],
)
CAR_TELEMETRY_2026 = StructDef(
    "CarTelemetryData",
    [(n, "B" if n == "engineTemperature" else f) for n, f in CAR_TELEMETRY.fields],
)
CAR_STATUS_2026 = StructDef(
    "CarStatusData",
    [
        *[(n, f) for n, f in CAR_STATUS.fields if n not in ("ersDeployedThisLap", "networkPaused")],
        ("ersHarvestLimitPerLap", "f"),
        ("ersDeployedThisLap", "f"),
        ("networkPaused", "B"),
    ],
)
LOBBY_INFO_2026 = StructDef(
    "LobbyInfoData",
    [(n, "H" if n == "teamId" else f) for n, f in LOBBY_INFO.fields],
)
TIME_TRIAL_DATASET_2026 = StructDef(
    "TimeTrialDataSet",
    [(n, "H" if n == "teamId" else f) for n, f in TIME_TRIAL_DATASET.fields],
)
# Session sub-structs new in 2026. SESSION_TAIL_2026 flattens ActiveAeroZone[8] / DRSZone[4] into "16f" / "8f"
# (zoneStart, zoneEnd, zoneStart, zoneEnd, ...); these defs document and machine-check that element layout.
ACTIVE_AERO_ZONE = StructDef("ActiveAeroZone", [("zoneStart", "f"), ("zoneEnd", "f")])  # lap fractions 0..1
DRS_ZONE = StructDef("DRSZone", [("zoneStart", "f"), ("zoneEnd", "f")])  # lap fractions 0..1
NUM_ACTIVE_AERO_ZONES = 8  # cs_maxActiveAeroZonesPerLap
NUM_DRS_ZONES = 4  # cs_maxDRSZonesPerLap
SESSION_TAIL_2026 = StructDef(
    "SessionTail2026",
    [
        *SESSION_TAIL.fields,
        ("activeAeroTrackStatus", "B"),
        ("numActiveAeroZonesFull", "B"),
        ("activeAeroZonesFull", "16f"),  # 8 x (zoneStart, zoneEnd) lap fractions
        ("numActiveAeroZonesPartial", "B"),
        ("activeAeroZonesPartial", "16f"),
        ("numDRSZones", "B"),
        ("drsZones", "8f"),  # 4 x (zoneStart, zoneEnd)
        ("startReactionTime", "f"),
        ("antiLockBrakesAssist", "B"),
        ("tractionControlAssist", "B"),
        ("dynamicRacingLineHiVis", "B"),
        ("dynamicRacingLineColourBlind", "B"),
        ("recurringRewindPrompt", "B"),
    ],
)
CAR_TELEMETRY_2 = StructDef(
    "CarTelemetry2Data",
    [
        ("activeAeroMode", "B"),
        ("activeAeroAvailable", "B"),
        ("activeAeroActivationDistance", "H"),
        ("overtakeAvailable", "B"),
        ("overtakeActive", "B"),
        ("overtakeActivationDistance", "H"),
        ("2026Regulations", "B"),
        ("drivingWrongWay", "B"),
    ],
)
EVENT_DETAILS_2026: dict[str, StructDef] = {
    **EVENT_DETAILS,
    "COLL": StructDef("Collision", [("vehicle1Idx", "B"), ("vehicle2Idx", "B"), ("severity", "B")]),
    "PMEN": StructDef("PartialModeEnabled", [("reason", "B")]),
}
EVENT_CODES_NO_DETAILS_2026 = EVENT_CODES_NO_DETAILS | {"PMDI", "OVEN", "OVDI"}


@dataclass(frozen=True, slots=True)
class F1Layout:
    """Everything that differs between wire formats, so decoders/encoders are format-agnostic."""

    packet_format: int
    max_cars: int
    car_motion: StructDef
    participant: StructDef
    car_telemetry: StructDef
    car_status: StructDef
    lobby_info: StructDef
    time_trial: StructDef
    session_tail: StructDef
    event_details: dict[str, StructDef]
    event_codes_no_details: frozenset[str]
    gforce_scale: float
    sizes: dict[PacketId, int]
    published_sizes: dict[PacketId, int]


def _sizes(
    cars: int,
    motion: StructDef,
    part: StructDef,
    tel: StructDef,
    status: StructDef,
    lobby: StructDef,
    tt: StructDef,
    session_tail: StructDef,
    extra: dict[PacketId, int] | None = None,
) -> dict[PacketId, int]:
    session_body = (
        SESSION_HEAD.size
        + NUM_MARSHAL_ZONES * MARSHAL_ZONE.size
        + SESSION_MID.size
        + NUM_WEATHER_SAMPLES * WEATHER_FORECAST_SAMPLE.size
        + session_tail.size
    )
    out = {
        PacketId.MOTION: _size(cars * motion.size),
        PacketId.SESSION: _size(session_body),
        PacketId.LAP_DATA: _size(cars * LAP_DATA.size + LAP_DATA_TAIL.size),
        PacketId.EVENT: _size(EVENT_CODE_SIZE + EVENT_DETAILS_SIZE),
        PacketId.PARTICIPANTS: _size(PARTICIPANTS_HEAD.size + cars * part.size),
        PacketId.CAR_SETUPS: _size(cars * CAR_SETUP.size + CAR_SETUPS_TAIL.size),
        PacketId.CAR_TELEMETRY: _size(cars * tel.size + CAR_TELEMETRY_TAIL.size),
        PacketId.CAR_STATUS: _size(cars * status.size),
        PacketId.FINAL_CLASSIFICATION: _size(FINAL_CLASSIFICATION_HEAD.size + cars * FINAL_CLASSIFICATION.size),
        PacketId.LOBBY_INFO: _size(LOBBY_INFO_HEAD.size + cars * lobby.size),
        PacketId.CAR_DAMAGE: _size(cars * CAR_DAMAGE.size),
        PacketId.SESSION_HISTORY: PACKET_SIZES[PacketId.SESSION_HISTORY],
        PacketId.TYRE_SETS: PACKET_SIZES[PacketId.TYRE_SETS],
        PacketId.MOTION_EX: PACKET_SIZES[PacketId.MOTION_EX],
        PacketId.TIME_TRIAL: _size(3 * tt.size),
        PacketId.LAP_POSITIONS: _size(LAP_POSITIONS_HEAD.size + LAP_POSITIONS_MAX_LAPS * cars),
    }
    out.update(extra or {})
    return out


LAYOUT_2025 = F1Layout(
    packet_format=PACKET_FORMAT_2025,
    max_cars=MAX_CARS,
    car_motion=CAR_MOTION,
    participant=PARTICIPANT,
    car_telemetry=CAR_TELEMETRY,
    car_status=CAR_STATUS,
    lobby_info=LOBBY_INFO,
    time_trial=TIME_TRIAL_DATASET,
    session_tail=SESSION_TAIL,
    event_details=EVENT_DETAILS,
    event_codes_no_details=EVENT_CODES_NO_DETAILS,
    gforce_scale=1.0,
    sizes=PACKET_SIZES,
    published_sizes=SPEC_PUBLISHED_SIZES,
)

LAYOUT_2026 = F1Layout(
    packet_format=PACKET_FORMAT_2026,
    max_cars=MAX_CARS_2026,
    car_motion=CAR_MOTION_2026,
    participant=PARTICIPANT_2026,
    car_telemetry=CAR_TELEMETRY_2026,
    car_status=CAR_STATUS_2026,
    lobby_info=LOBBY_INFO_2026,
    time_trial=TIME_TRIAL_DATASET_2026,
    session_tail=SESSION_TAIL_2026,
    event_details=EVENT_DETAILS_2026,
    event_codes_no_details=EVENT_CODES_NO_DETAILS_2026,
    gforce_scale=GFORCE_SCALE_2026,
    sizes=_sizes(
        MAX_CARS_2026,
        CAR_MOTION_2026,
        PARTICIPANT_2026,
        CAR_TELEMETRY_2026,
        CAR_STATUS_2026,
        LOBBY_INFO_2026,
        TIME_TRIAL_DATASET_2026,
        SESSION_TAIL_2026,
        extra={PacketId.CAR_TELEMETRY_2: _size(MAX_CARS_2026 * CAR_TELEMETRY_2.size)},
    ),
    published_sizes={
        PacketId.MOTION: 1325,
        PacketId.SESSION: 926,
        PacketId.LAP_DATA: 1399,
        PacketId.EVENT: 45,
        PacketId.PARTICIPANTS: 1470,
        PacketId.CAR_SETUPS: 1233,
        PacketId.CAR_TELEMETRY: 1448,
        PacketId.CAR_STATUS: 1445,
        PacketId.FINAL_CLASSIFICATION: 1134,
        PacketId.LOBBY_INFO: 1062,
        PacketId.CAR_DAMAGE: 1133,
        PacketId.SESSION_HISTORY: 1460,
        PacketId.TYRE_SETS: 231,
        PacketId.MOTION_EX: 273,
        PacketId.TIME_TRIAL: 104,
        PacketId.LAP_POSITIONS: 1231,
        PacketId.CAR_TELEMETRY_2: 269,
    },
)

LAYOUTS: dict[int, F1Layout] = {PACKET_FORMAT_2025: LAYOUT_2025, PACKET_FORMAT_2026: LAYOUT_2026}
