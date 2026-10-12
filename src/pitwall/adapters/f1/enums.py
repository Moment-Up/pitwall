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


# OBSERVED, not in EA's F1 25 document (docs/research/f1-udp-spec.md section 10, item 19): in UDP format 2025 the
# 2025 F2 cars (added in v1.12) report team ids 209-219, which the spec does not list. The owner's PS5 recording
# (F1 25 v1.26, 2026-10-11, Melbourne F2 race, 20261011-011513) has all 22 cars, two per id 209-219, with the 2025 F2
# driver pairings; EA's own format-2026 list names the same eleven teams, in the same order, as ids 465-475. So id
# 209 + k is the team EA names at 465 + k. Used only for display (``carclass.car_label``), never for ``car_id`` or
# ``SessionInfo.car_name``, which keep the spec's neutral fallback ("Unknown team (id 214)").
OBSERVED_F2_TEAMS_FMT2025: dict[int, str] = {209 + k: TEAMS[465 + k] for k in range(11)}


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


# --- race radio (pitwall.raceradio) -------------------------------------------------------------------------------
# Driver ids exactly as docs/research/f1-udp-spec.md section 8.2 spells them (F1 25 PDF v3, plus the 2026 docs' rows
# 186-207); tests/unit/test_f1_protocol.py machine-checks this table against that appendix. 255 (format 2025) and
# 65535 (2026) mean "network human": the adapter maps them to None. In F1 World races the AI cars carry real players'
# online IDs with driver id 255 [measured], so a car's *name* is never a driver's name: only this table is.
DRIVERS: dict[int, str] = {
    0: "Carlos Sainz",
    2: "Daniel Ricciardo",
    3: "Fernando Alonso",
    4: "Felipe Massa",
    7: "Lewis Hamilton",
    9: "Max Verstappen",
    10: "Nico Hülkenberg",
    11: "Kevin Magnussen",
    14: "Sergio Pérez",
    15: "Valtteri Bottas",
    17: "Esteban Ocon",
    19: "Lance Stroll",
    20: "Arron Barnes",
    21: "Martin Giles",
    22: "Alex Murray",
    23: "Lucas Roth",
    24: "Igor Correia",
    25: "Sophie Levasseur",
    26: "Jonas Schiffer",
    27: "Alain Forest",
    28: "Jay Letourneau",
    29: "Esto Saari",
    30: "Yasar Atiyeh",
    31: "Callisto Calabresi",
    32: "Naota Izumi",
    33: "Howard Clarke",
    34: "Lars Kaufmann",
    35: "Marie Laursen",
    36: "Flavio Nieves",
    38: "Klimek Michalski",
    39: "Santiago Moreno",
    40: "Benjamin Coppens",
    41: "Noah Visser",
    50: "George Russell",
    54: "Lando Norris",
    58: "Charles Leclerc",
    59: "Pierre Gasly",
    62: "Alexander Albon",
    70: "Rashid Nair",
    71: "Jack Tremblay",
    77: "Ayrton Senna",
    80: "Guanyu Zhou",
    83: "Juan Manuel Correa",
    90: "Michael Schumacher",
    94: "Yuki Tsunoda",
    102: "Aidan Jackson",
    109: "Jenson Button",
    110: "David Coulthard",
    112: "Oscar Piastri",
    113: "Liam Lawson",
    116: "Richard Verschoor",
    123: "Enzo Fittipaldi",
    125: "Mark Webber",
    126: "Jacques Villeneuve",
    127: "Callie Mayer",
    132: "Logan Sargeant",
    136: "Jack Doohan",
    137: "Amaury Cordeel",
    138: "Dennis Hauger",
    145: "Zane Maloney",
    146: "Victor Martins",
    147: "Oliver Bearman",
    148: "Jak Crawford",
    149: "Isack Hadjar",
    152: "Roman Stanek",
    153: "Kush Maini",
    156: "Brendon Leigh",
    157: "David Tonizza",
    158: "Jarno Opmeer",
    159: "Lucas Blakeley",
    160: "Paul Aron",
    161: "Gabriel Bortoleto",
    162: "Franco Colapinto",
    163: "Taylor Barnard",
    164: "Joshua Dürksen",
    165: "Andrea-Kimi Antonelli",
    166: "Ritomo Miyata",
    167: "Rafael Villagómez",
    168: "Zak O'Sullivan",
    169: "Pepe Marti",
    170: "Sonny Hayes",
    171: "Joshua Pearce",
    172: "Callum Voisin",
    173: "Matias Zagazeta",
    174: "Nikola Tsolov",
    175: "Tim Tramnitz",
    185: "Luca Cortez",
    186: "Luke Browning",
    187: "Cian Shields",
    188: "Arvid Lindblad",
    189: "Dino Beganovic",
    190: "Leonardo Fornaroli",
    191: "Oliver Goethe",
    192: "Gabriele Minì",
    193: "Sebastián Montoya",
    194: "Alexander Dunne",
    195: "Max Esterson",
    196: "Sami Meguetounif",
    197: "John Bennett",
    198: "Emerson Fittipaldi",
    199: "Tasanopol Inthraphuvasak",
    200: "Noel León",
    201: "Roman Bilinski",
    202: "Colton Herta",
    203: "Rafael Câmara",
    204: "Mari Boya",
    205: "Martinius Stenshorne",
    206: "Laurens van Hoepen",
    207: "Nico Varrone",
}
DRIVER_ID_NONE = frozenset({255, 65535})  # network human (or a player's ID on an AI car): not in the table
# The spoken surname of a driver id: the last word of the spec's name, except where that is not the surname.
_RADIO_NAME_OVERRIDES: dict[str, str] = {
    "Laurens van Hoepen": "van Hoepen",
    "Juan Manuel Correa": "Correa",
    "Guanyu Zhou": "Zhou",
    "Andrea-Kimi Antonelli": "Antonelli",
    "Nico Hülkenberg": "Hülkenberg",
}
DRIVER_RADIO_NAMES: dict[int, str] = {
    i: _RADIO_NAME_OVERRIDES.get(name, name.split()[-1]) for i, name in DRIVERS.items()
}

# Penalty types (section 8.10) and infringement types (section 8.11), named exactly as the spec names them (machine-
# checked); the radio's own words for them are in ``raceradio.wording`` (never guessed for an unknown code).
PENALTY_TYPES: dict[int, str] = {
    0: "Drive through",
    1: "Stop Go",
    2: "Grid penalty",
    3: "Penalty reminder",
    4: "Time penalty",
    5: "Warning",
    6: "Disqualified",
    7: "Removed from formation lap",
    8: "Parked too long timer",
    9: "Tyre regulations",
    10: "This lap invalidated",
    11: "This and next lap invalidated",
    12: "This lap invalidated without reason",
    13: "This and next lap invalidated without reason",
    14: "This and previous lap invalidated",
    15: "This and previous lap invalidated without reason",
    16: "Retired",
    17: "Black flag timer",
}
INFRINGEMENTS: dict[int, str] = {
    0: "Blocking by slow driving",
    1: "Blocking by wrong way driving",
    2: "Reversing off the start line",
    3: "Big Collision",
    4: "Small Collision",
    5: "Collision failed to hand back position single",
    6: "Collision failed to hand back position multiple",
    7: "Corner cutting gained time",
    8: "Corner cutting overtake single",
    9: "Corner cutting overtake multiple",
    10: "Crossed pit exit lane",
    11: "Ignoring blue flags",
    12: "Ignoring yellow flags",
    13: "Ignoring drive through",
    14: "Too many drive throughs",
    15: "Drive through reminder serve within n laps",
    16: "Drive through reminder serve this lap",
    17: "Pit lane speeding",
    18: "Parked for too long",
    19: "Ignoring tyre regulations",
    20: "Too many penalties",
    21: "Multiple warnings",
    22: "Approaching disqualification",
    23: "Tyre regulations select single",
    24: "Tyre regulations select multiple",
    25: "Lap invalidated corner cutting",
    26: "Lap invalidated running wide",
    27: "Corner cutting ran wide gained time minor",
    28: "Corner cutting ran wide gained time significant",
    29: "Corner cutting ran wide gained time extreme",
    30: "Lap invalidated wall riding",
    31: "Lap invalidated flashback used",
    32: "Lap invalidated reset to track",
    33: "Blocking the pitlane",
    34: "Jump start",
    35: "Safety car to car collision",
    36: "Safety car illegal overtake",
    37: "Safety car exceeding allowed pace",
    38: "Virtual safety car exceeding allowed pace",
    39: "Formation lap below allowed speed",
    40: "Formation lap parking",
    41: "Retired mechanical failure",
    42: "Retired terminally damaged",
    43: "Safety car falling too far back",
    44: "Black flag timer",
    45: "Unserved stop go penalty",
    46: "Unserved drive through penalty",
    47: "Engine component change",
    48: "Gearbox change",
    49: "Parc Fermé change",
    50: "League grid penalty",
    51: "Retry penalty",
    52: "Illegal time gain",
    53: "Mandatory pitstop",
    54: "Attribute assigned",
}
# CarStatus.vehicleFIAFlags (section 8.12): -1 = invalid/unknown -> None, like any value the spec does not define
# (a 4 = "red" seen in community code is not in EA's spec: unknown, never a red flag).
FIA_FLAGS: dict[int, str] = {0: "none", 1: "green", 2: "blue", 3: "yellow"}
