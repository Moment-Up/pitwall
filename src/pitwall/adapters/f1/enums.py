"""Enumerations from the EA F1 25 UDP specification appendices.

Unknown codes are passed through as ``"unknown_<n>"`` rather than guessed.
"""

from __future__ import annotations

from pitwall.model.telemetry import Platform, SessionType

TRACKS: dict[int, str] = {
    0: "Melbourne",
    1: "Paul Ricard",
    2: "Shanghai",
    3: "Sakhir (Bahrain)",
    4: "Catalunya",
    5: "Monaco",
    6: "Montreal",
    7: "Silverstone",
    8: "Hockenheim",
    9: "Hungaroring",
    10: "Spa",
    11: "Monza",
    12: "Singapore",
    13: "Suzuka",
    14: "Abu Dhabi",
    15: "Texas",
    16: "Brazil",
    17: "Austria",
    18: "Sochi",
    19: "Mexico",
    20: "Baku (Azerbaijan)",
    21: "Sakhir Short",
    22: "Silverstone Short",
    23: "Texas Short",
    24: "Suzuka Short",
    25: "Hanoi",
    26: "Zandvoort",
    27: "Imola",
    28: "Portimão",
    29: "Jeddah",
    30: "Miami",
    31: "Las Vegas",
    32: "Losail",
    39: "Silverstone (Reverse)",
    40: "Austria (Reverse)",
    41: "Zandvoort (Reverse)",
    42: "Madrid",  # 2026 Season Pack
}

SESSION_TYPES: dict[int, tuple[str, SessionType]] = {
    0: ("Unknown", SessionType.UNKNOWN),
    1: ("Practice 1", SessionType.PRACTICE),
    2: ("Practice 2", SessionType.PRACTICE),
    3: ("Practice 3", SessionType.PRACTICE),
    4: ("Short Practice", SessionType.PRACTICE),
    5: ("Qualifying 1", SessionType.QUALIFYING),
    6: ("Qualifying 2", SessionType.QUALIFYING),
    7: ("Qualifying 3", SessionType.QUALIFYING),
    8: ("Short Qualifying", SessionType.QUALIFYING),
    9: ("One-Shot Qualifying", SessionType.QUALIFYING),
    10: ("Sprint Shootout 1", SessionType.QUALIFYING),
    11: ("Sprint Shootout 2", SessionType.QUALIFYING),
    12: ("Sprint Shootout 3", SessionType.QUALIFYING),
    13: ("Short Sprint Shootout", SessionType.QUALIFYING),
    14: ("One-Shot Sprint Shootout", SessionType.QUALIFYING),
    15: ("Race", SessionType.RACE),
    16: ("Race 2", SessionType.RACE),
    17: ("Race 3", SessionType.RACE),
    18: ("Time Trial", SessionType.TIME_TRIAL),
}

WEATHER: dict[int, str] = {
    0: "clear",
    1: "light_cloud",
    2: "overcast",
    3: "light_rain",
    4: "heavy_rain",
    5: "storm",
}

# Visual compounds are what the driver sees (soft/medium/hard), actual compounds are C0..C6.
VISUAL_COMPOUNDS: dict[int, str] = {
    16: "soft",
    17: "medium",
    18: "hard",
    7: "inter",
    8: "wet",
    15: "wet",  # F2 '19
    19: "super_soft",  # F2 '19
    20: "soft",  # F2 '19
    21: "medium",  # F2 '19
    22: "hard",  # F2 '19
}
ACTUAL_COMPOUNDS: dict[int, str] = {
    16: "C5",
    17: "C4",
    18: "C3",
    19: "C2",
    20: "C1",
    21: "C0",
    22: "C6",
    7: "inter",
    8: "wet",
    9: "dry",  # classic
    10: "wet",  # classic
    11: "super_soft",  # F2
    12: "soft",  # F2
    13: "medium",  # F2
    14: "hard",  # F2
    15: "wet",  # F2
}

FORMULA: dict[int, str] = {
    0: "F1 Modern",
    1: "F1 Classic",
    2: "F2",
    3: "F1 Generic",
    4: "Beta",
    6: "Esports",
    8: "F1 World",
    9: "F1 Elimination",
    13: "F1 26",
}

SAFETY_CAR_STATUS: dict[int, str] = {0: "none", 1: "full", 2: "virtual", 3: "formation_lap"}

# Team ids exactly as docs/research/f1-udp-spec.md section 8.1 names them (EA's F1 25 v3 and 2026 v1.2 PDFs);
# tests/unit/test_f1_protocol.py machine-checks this table against that appendix. An id the spec does not list
# (e.g. 214, seen on an F2 car in F1 25) has no name here: ``team_name`` gives the neutral fallback, never a guess.
TEAMS: dict[int, str] = {
    0: "Mercedes",
    1: "Ferrari",
    2: "Red Bull Racing",
    3: "Williams",
    4: "Aston Martin",
    5: "Alpine",
    6: "RB",
    7: "Haas",
    8: "McLaren",
    9: "Sauber",
    41: "F1 Generic",
    104: "F1 Custom Team",
    129: "Konnersport",
    142: "APXGP '24",
    154: "APXGP '25",
    155: "Konnersport '24",
    158: "Art GP '24",
    159: "Campos '24",
    160: "Rodin Motorsport '24",
    161: "AIX Racing '24",
    162: "DAMS '24",
    163: "Hitech '24",
    164: "MP Motorsport '24",
    165: "Prema '24",
    166: "Trident '24",
    167: "Van Amersfoort Racing '24",
    168: "Invicta '24",
    185: "Mercedes '24",
    186: "Ferrari '24",
    187: "Red Bull Racing '24",
    188: "Williams '24",
    189: "Aston Martin '24",
    190: "Alpine '24",
    191: "RB '24",
    192: "Haas '24",
    193: "McLaren '24",
    194: "Sauber '24",
    # format 2026 only (uint16 team ids)
    465: "Art GP '25",
    466: "Campos '25",
    467: "Rodin Motorsport '25",
    468: "AIX Racing '25",
    469: "DAMS '25",
    470: "Hitech '25",
    471: "MP Motorsport '25",
    472: "Prema '25",
    473: "Trident '25",
    474: "Van Amersfoort Racing '25",
    475: "Invicta '25",
    476: "Mercedes '26",
    477: "Ferrari '26",
    478: "Red Bull Racing '26",
    479: "Williams '26",
    480: "Aston Martin '26",
    481: "Alpine '26",
    482: "RB '26",
    483: "Haas '26",
    484: "McLaren '26",
    485: "Audi '26",
    486: "Cadillac '26",
    # 2026 doc v1.2 only (F2 2026, Season 8)
    489: "Art GP '26",
    490: "Campos '26",
    491: "Rodin Motorsport '26",
    492: "AIX Racing '26",
    493: "DAMS '26",
    494: "Hitech '26",
    495: "MP Motorsport '26",
    496: "Prema '26",
    497: "Trident '26",
    498: "Van Amersfoort Racing '26",
    499: "Invicta '26",
}


def team_name(team_id: int) -> str:
    """The spec's name for ``team_id``, else a neutral label that names no team ("Unknown team (id 214)")."""
    return TEAMS.get(team_id, f"Unknown team (id {team_id})")


# ParticipantData.platform
PLATFORMS: dict[int, Platform] = {
    1: Platform.PC,  # Steam
    3: Platform.PS5,  # PlayStation (F1 25 ships on PS5 only, not PS4)
    4: Platform.XBOX,
    6: Platform.PC,  # Origin / EA app
}

PIT_STATUS: dict[int, str] = {0: "none", 1: "pitting", 2: "in_pit_area"}
DRIVER_STATUS: dict[int, str] = {0: "in_garage", 1: "flying_lap", 2: "in_lap", 3: "out_lap", 4: "on_track"}
ERS_DEPLOY_MODE: dict[int, str] = {0: "none", 1: "medium", 2: "hotlap", 3: "overtake"}

# Appendix 8.9: Event BUTN ``buttonStatus`` bit flags, named exactly as the spec names them (machine-checked by
# tests/unit/test_f1_protocol.py). UDP Action n = 0x00100000 << (n - 1). Which wheel control sets which bit is not in
# the spec: Pitwall's button test reports only what it sees.
BUTTON_FLAGS: dict[int, str] = {
    0x00000001: "Cross or A",
    0x00000002: "Triangle or Y",
    0x00000004: "Circle or B",
    0x00000008: "Square or X",
    0x00000010: "D-pad Left",
    0x00000020: "D-pad Right",
    0x00000040: "D-pad Up",
    0x00000080: "D-pad Down",
    0x00000100: "Options or Menu",
    0x00000200: "L1 or LB",
    0x00000400: "R1 or RB",
    0x00000800: "L2 or LT",
    0x00001000: "R2 or RT",
    0x00002000: "Left Stick Click",
    0x00004000: "Right Stick Click",
    0x00008000: "Right Stick Left",
    0x00010000: "Right Stick Right",
    0x00020000: "Right Stick Up",
    0x00040000: "Right Stick Down",
    0x00080000: "Special",
    **{0x00100000 << (n - 1): f"UDP Action {n}" for n in range(1, 13)},
}
UDP_ACTION_BASE = 0x00100000


def udp_action_bit(n: int) -> int:
    """BUTN bit of UDP Action ``n`` (1..12)."""
    if not 1 <= n <= 12:
        raise ValueError("UDP Action must be 1..12")
    return UDP_ACTION_BASE << (n - 1)


def button_names(mask: int) -> list[str]:
    """Spec names of the bits set in ``mask`` (lowest bit first)."""
    return [BUTTON_FLAGS[1 << i] for i in range(32) if mask & (1 << i)]


EVENT_NAMES: dict[str, str] = {
    "SSTA": "session_started",
    "SEND": "session_ended",
    "FTLP": "fastest_lap",
    "RTMT": "retirement",
    "DRSE": "drs_enabled",
    "DRSD": "drs_disabled",
    "TMPT": "team_mate_in_pits",
    "CHQF": "chequered_flag",
    "RCWN": "race_winner",
    "PENA": "penalty",
    "SPTP": "speed_trap",
    "STLG": "start_lights",
    "LGOT": "lights_out",
    "DTSV": "drive_through_served",
    "SGSV": "stop_go_served",
    "FLBK": "flashback",
    "BUTN": "button",
    "RDFL": "red_flag",
    "OVTK": "overtake",
    "SCAR": "safety_car",
    "COLL": "collision",
    "PMEN": "partial_mode_enabled",
    "PMDI": "partial_mode_disabled",
    "OVEN": "overtake_mode_enabled",
    "OVDI": "overtake_mode_disabled",
}


def track_name(track_id: int) -> str:
    if track_id == -1:
        return "Unknown track"
    return TRACKS.get(track_id, f"Unknown track (id {track_id})")
