"""Every sentence the race radio says, in plain British English: standard words and simple words.

Simple words (``CoachingLimits.simple_wording``: beginners, or a driver who picked "Simple") say one idea with no
jargon in at most 14 words. Display text writes a position as ``P5``; the speech source writes ``P 5`` so the TTS
lexicon spells the number (``speech_source``). Gaps are written ``1.2s`` and spoken "1.2 seconds" by ``to_speech``.

Never said: "brake later"; a penalty threshold ("one more warning and ..." - EA's spec does not give one); a reason of 0
/ "invalid"; a personal name. Penalty and infringement words follow EA's spec (``enums.PENALTY_TYPES``,
``enums.INFRINGEMENTS``); an infringement with no entry here gives the call without a reason, never a guessed one.
"""

from __future__ import annotations

import re

_P = re.compile(r"\bP(\d{1,2})\b")
_NUMBER_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}


def speech_source(text: str) -> str:
    """The text the speech is made from: ``P5`` -> ``P 5`` (the lexicon spells the number, never "p five")."""
    return _P.sub(r"P \1", text)


def ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st, 22nd ..."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def places(n: int) -> str:
    return "1 place" if n == 1 else f"{n} places"


def cap(words: str) -> str:
    return words[:1].upper() + words[1:]


# ---------------------------------------------------------------------------------------------------- flags
RED_FLAG = (
    "Red flag, red flag. Slow down, back to the pits.",
    "Red flag: the race is stopped. Slow down and drive back to the pits.",
)
SC_DEPLOYED = (
    "Safety car, safety car. No overtaking.",
    "Safety car is out: slow down and stay behind the car in front.",
)
VSC_DEPLOYED = (
    "Virtual safety car. Slow down, no overtaking.",
    "Virtual safety car: everyone slows down. Don't overtake.",
)
SC_ENDING = ("Safety car in this lap.", "The safety car comes in this lap. Get ready to race.")
VSC_ENDING = ("VSC ending.", "The virtual safety car is ending. Get ready.")
GREEN = ("Green flag, racing.", "Green flag: you can race again.")
BLUE_RACE = ("Blue flag. Let the car behind through.", "Blue flag: a faster car is coming. Let it pass.")
BLUE_SESSION = ("Blue flag: car behind on a fast lap.", "Blue flag: a faster car is coming. Let it pass.")


_SLOW_A_LITTLE = "slow down a little, no overtaking."


def yellow_ahead(corner: str | None, sector: int | None) -> tuple[str, str]:
    if corner:
        return f"Yellow ahead, {corner}.", f"Yellow flag ahead at {corner}: {_SLOW_A_LITTLE}"
    if sector is not None:
        return f"Yellow in sector {sector}.", f"Yellow flag ahead in sector {sector}: {_SLOW_A_LITTLE}"
    return "Yellow ahead.", f"Yellow flag ahead: {_SLOW_A_LITTLE}"


def yellow_here(corner: str | None) -> tuple[str, str]:
    text = f"Yellow flag, {corner}." if corner else "Yellow flag."
    return text, f"Yellow flag here: {_SLOW_A_LITTLE}"


# ---------------------------------------------------------------------------------------------------- start
def grid_brief(grid: int | None, cars: int | None, laps: int | None, *, rolling: bool) -> tuple[str, str] | None:
    """F1: "P20 of 22, 3 laps."; GT7: "Rolling start. P8 of 14, 10 laps." None when nothing is known."""
    parts: list[str] = []
    if grid is not None:
        parts.append(f"P{grid} of {cars}" if cars else f"P{grid}")
    if laps:
        parts.append(f"{laps} laps")
    if not parts:
        return None
    lead = "Rolling start. " if rolling else ""
    text = lead + ", ".join(parts) + "."
    if grid is not None:
        simple = f"{lead}You start {ordinal(grid)}" + (f" of {cars}." if cars else ".")
        if laps and not rolling:
            simple += f" {laps} laps."
    else:
        simple = text
    return text, simple


LIGHTS_OUT = ("Go, go.", "Go!")


def laps_to_go(n: int) -> tuple[str, str]:
    text = f"{_NUMBER_WORDS.get(n, str(n))} laps to go."
    return text, text


LAST_LAP = "Last lap."
LAST_LAP_LAPPED = "Last lap: the leader finishes first."
LAST_LAP_FLAG = "Flag's out. Last lap."
LAST_LAP_SIMPLE = "This is the last lap."


def finish(pos: int | None, grid: int | None) -> tuple[str, str]:
    if pos is None:
        return "Chequered flag.", "That's the finish."
    text = f"Chequered flag. P{pos}."
    if grid is not None and grid != pos:
        text += f" Up {grid - pos} from the grid." if pos < grid else f" Down {pos - grid}."
    return text, f"That's the finish. You came {ordinal(pos)}."


def minutes_left(n: int) -> tuple[str, str]:
    text = "Five minutes left in the session." if n == 5 else "One minute left."
    return text, text


# ---------------------------------------------------------------------------------------------------- position
def lap1_summary(pos: int, grid: int | None) -> tuple[str, str]:
    if grid is None or grid == pos:
        tail = ", held position." if grid is not None else "."
        return f"P{pos} after lap one{tail}", f"After lap one you're {ordinal(pos)}."
    if pos < grid:
        n = grid - pos
        return f"P{pos} after lap one, up {n}.", f"After lap one you're {ordinal(pos)}. That's {places(n)} up."
    n = pos - grid
    return f"P{pos} after lap one, down {n}.", f"After lap one you're {ordinal(pos)}. That's {places(n)} down."


def position_change(pos: int, before: int) -> tuple[str, str]:
    if pos < before:
        n = before - pos
        text = f"Up to P{pos}." if n == 1 else f"Up to P{pos}, gained {n}."
        return text, f"You're up to {ordinal(pos)}."
    n = pos - before
    text = f"Down to P{pos}." if n == 1 else f"Down to P{pos}, lost {n}."
    return text, f"You've dropped to {ordinal(pos)}."


def pit_exit(pos: int) -> tuple[str, str]:
    return f"Out of the pits in P{pos}.", f"You're back on track in {ordinal(pos)}."


def clean_pass(pos: int, name: str | None) -> tuple[str, str]:
    text = f"Good move on {name}. P{pos}." if name else f"Good move. P{pos}."
    return text, f"Nice overtake! You're {ordinal(pos)} now."


# ---------------------------------------------------------------------------------------------------- rivals
def _trend(side: str, slope: float | None) -> str:
    """Trend words for a gap's slope (s/lap) when |slope| >= TREND_MIN."""
    if slope is None:
        return ""
    if side == "ahead":
        return ", closing" if slope < 0 else ", pulling away"
    return ", closing" if slope < 0 else ", dropping back"


def gap_report(
    ahead: float | None, ahead_slope: float | None, behind: float | None, behind_slope: float | None, leading: bool
) -> tuple[str, str] | None:
    """ "Gap ahead 1.2s, closing. Behind 0.8s." / "Leading by 2.4s." (slopes already filtered by the caller)."""
    if leading:
        if behind is None:
            return None
        text = f"Leading by {behind:.1f}s{_trend('behind', behind_slope)}."
        return text, f"You're leading by {behind:.1f}s."
    parts: list[str] = []
    if ahead is not None:
        parts.append(f"Gap ahead {ahead:.1f}s{_trend('ahead', ahead_slope)}.")
    if behind is not None:
        parts.append(f"Behind {behind:.1f}s{_trend('behind', behind_slope)}.")
    if not parts:
        return None
    if ahead is not None:
        simple = f"The car in front is {ahead:.1f}s ahead."
        if ahead_slope is not None and ahead_slope < 0:
            simple += " You're catching it."
    else:
        simple = f"The car behind is {behind:.1f}s back."
    return " ".join(parts), simple


def car_ahead_pitting(label_kind: str, label: str) -> tuple[str, str]:
    text = f"{cap(label)} is pitting." if label_kind in ("driver", "team") else "Car ahead is pitting."
    return text, "The car in front is going into the pits."


OWN_FASTEST_LAP = ("Fastest lap of the race.", "That was the fastest lap of the race!")


def rival_fastest_lap(label_kind: str, label: str, time_text: str) -> str:
    if label_kind in ("driver", "team"):
        return f"Fastest lap for {label}, {time_text}."
    if label_kind == "number":
        return f"Fastest lap: {label}, {time_text}."
    return f"Fastest lap: another car, {time_text}."


RETIREMENT_REASONS = {3: "damage", 6: "black flagged", 8: "mechanical failure"}  # RTMT reason (spec 8.12) worth saying


def retirement(label_kind: str, label: str, near_pos: int | None, reason: str | None) -> tuple[str, str]:
    if label_kind in ("driver", "team"):
        text = f"{cap(label)} is out"
    elif label_kind == "number":
        text = f"{cap(label)} has retired"
    else:
        text = "A car has retired"
    text += f": {reason}." if reason else "."
    if near_pos is not None:
        text += f" From P{near_pos}."
    simple = f"The car in {ordinal(near_pos)} place has stopped." if near_pos is not None else "A car has stopped."
    return text, simple


# ---------------------------------------------------------------------------------------------------- penalties
# Infringement words (EA spec section 8.11): short, lower case, no jargon. A code with no entry has no reason said.
INFRINGEMENT_WORDS: dict[int, str | None] = {
    0: "blocking",
    1: "blocking",
    2: "reversing off the grid",
    3: "a collision",
    4: "a collision",
    5: "not giving the place back",
    6: "not giving the place back",
    7: "cutting the track",
    8: "cutting the track",
    9: "cutting the track",
    10: "crossing the pit exit line",
    11: "ignoring blue flags",
    12: "ignoring yellow flags",
    13: "not serving the drive-through",
    14: "too many drive-throughs",
    15: "the drive-through",
    16: "the drive-through",
    17: "speeding in the pit lane",
    18: "parking too long",
    19: "the tyre rules",
    20: "too many penalties",
    21: "too many warnings",
    22: "nearly disqualified",
    23: "the tyre rules",
    24: "the tyre rules",
    25: "track limits",
    26: "track limits",
    27: "track limits",
    28: "track limits",
    29: "track limits",
    30: "riding the wall",
    31: "using a flashback",
    32: "resetting to track",
    33: "blocking the pit lane",
    34: "a jump start",
    35: "hitting the safety car",
    36: "overtaking under the safety car",
    37: "too fast under the safety car",
    38: "too fast under the virtual safety car",
    39: "too slow on the formation lap",
    40: "parking on the formation lap",
    41: "a mechanical failure",
    42: "terminal damage",
    43: "falling too far behind the safety car",
    44: "the black flag timer",
    45: "an unserved stop-go",
    46: "an unserved drive-through",
    47: "an engine part change",
    48: "a gearbox change",
    49: "a parc fermé change",
    50: "a league grid penalty",
    51: "a retry",
    52: "an illegal time gain",
    53: "the mandatory pit stop",
    54: None,  # "Attribute assigned": no reason said
}
TRACK_LIMIT_INFRINGEMENTS = frozenset({7, 8, 9, 25, 26, 27, 28, 29})
CONTACT_INFRINGEMENTS = frozenset({3, 4})


def reason_words(infringement: int | None) -> str | None:
    return None if infringement is None else INFRINGEMENT_WORDS.get(infringement)


def _with(base: str, reason: str | None) -> str:
    return f"{base}: {reason}." if reason else f"{base}."


def penalty(ptype: int, infringement: int | None, time_s: int | None) -> tuple[str, str] | None:
    """The ``penalty`` call of penalty types 0, 1, 2, 4, 6, 7, 8, 9 and 17 (Appendix A); None for any other type."""
    r = reason_words(infringement)
    if ptype == 0:
        return _with("Drive-through penalty", r), _with("You must drive through the pit lane", r)
    if ptype == 1:
        return _with("Stop-go penalty", r), _with("You must stop in your pit box", r)
    if ptype == 2:
        return _with("Grid penalty", r), _with("You'll start further back", r)
    if ptype == 4:
        for_r = f" for {r}." if r else "."
        if time_s is None or time_s == 255 or time_s <= 0:  # 255: not set
            return _with("Time penalty", r), "Time will be added to your race time" + for_r
        return _with(f"{time_s} second penalty", r), f"{time_s} seconds will be added to your race time" + for_r
    if ptype == 6:
        return _with("Disqualified", r), _with("You've been disqualified", r)
    if ptype == 7:
        return "Removed from the formation lap.", "Removed from the formation lap."
    if ptype == 8:
        return "Parked too long.", "You stopped on track too long."
    if ptype == 9:
        return "Tyre regulations penalty.", "Penalty for breaking the tyre rules."
    if ptype == 17:
        text = _with("Black flag warning", r)
        return text, text + " You could be disqualified."
    return None


def serve_reminder(infringement: int | None) -> tuple[str, str]:
    if infringement == 16:
        return "Serve the drive-through this lap.", "Drive through the pit lane this lap to serve your penalty."
    if infringement == 15:
        return "Drive-through still to serve.", "You still have a penalty to serve."
    return "Penalty still to serve.", "You still have a penalty to serve."


def warning(infringement: int | None, track_limit_count: int | None) -> tuple[str, str]:
    if infringement in TRACK_LIMIT_INFRINGEMENTS:
        text = f"Track limits warning, {track_limit_count}." if track_limit_count else "Track limits warning."
        return text, "Warning for cutting the track. Keep inside the white lines."
    if infringement in CONTACT_INFRINGEMENTS:
        return "Warning for contact.", "Warning for contact. Give the other cars more room."
    r = reason_words(infringement)
    text = _with("Warning", r)
    return text, text


def served(code: str) -> tuple[str, str]:
    return ("Drive-through served." if code == "DTSV" else "Stop-go served."), "Penalty served."


NEXT_LAP_INVALID = "Next lap won't count either."
PREVIOUS_LAP_INVALID = "Your previous lap was deleted too."

# ---------------------------------------------------------------------------------------------------- damage
GRADES = ("none", "minor", "major", "severe")
PART_WORDS: dict[str, str] = {
    "front_left_wing": "front wing, left",
    "front_right_wing": "front wing, right",
    "front_wing": "front wing",
    "rear_wing": "rear wing",
    "floor": "floor",
    "diffuser": "diffuser",
    "sidepod": "sidepod",
    "gearbox": "gearbox",
    "engine": "engine",
}
SIMPLE_PART_WORDS: dict[str, str] = {**PART_WORDS, "front_left_wing": "front wing", "front_right_wing": "front wing"}
WHEEL_WORDS: dict[str, str] = {"FL": "front left", "FR": "front right", "RL": "rear left", "RR": "rear right"}


def part_words(part: str, *, simple: bool = False) -> str:
    """ "front wing, left"; brakes: "brakes, rear left" (``brakes_RL``)."""
    if part.startswith("brakes_"):
        return "brakes" if simple else f"brakes, {WHEEL_WORDS[part[7:]]}"
    return (SIMPLE_PART_WORDS if simple else PART_WORDS)[part]


def damage(
    parts: list[tuple[str, str]], punctures: list[str], advice: str | None, advice_simple: str | None
) -> tuple[str, str]:
    """``parts``: [(part, grade)] at most two, highest grade first; ``punctures``: wheel codes."""
    out: list[str] = []
    simple: list[str] = []
    if punctures:
        wheels = " and ".join(WHEEL_WORDS[w] for w in punctures)
        out.append(f"Puncture, {wheels}.")
        simple.append(f"Puncture on the {wheels} tyre.")
    if len(parts) == 1:
        part, grade = parts[0]
        out.append(f"{cap(part_words(part))} damage, {grade}.")
    elif parts:
        out.append("Damage: " + ", ".join(f"{part_words(p)} {g}" for p, g in parts) + ".")
    if parts and not punctures:
        simple.append(f"The {part_words(parts[0][0], simple=True)} is damaged.")
    if advice:
        out.append(advice)
    if advice_simple:
        simple.append(advice_simple)
    return " ".join(out), " ".join(simple)


BOX_PUNCTURE = ("Box this lap.", "Come into the pits.")
BOX_FRONT_WING = ("Box for a new front wing.", "Come into the pits for a new front wing.")
FAULTS: dict[str, tuple[str, str]] = {
    "drs_fault": ("DRS fault.", "The DRS is broken."),
    "ers_fault": ("ERS fault.", "The battery has a fault."),
    "engine_failure": ("Engine failure.", "The engine has failed."),
}
