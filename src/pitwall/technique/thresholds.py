"""Every threshold the technique analysis uses, with its unit, whether it is a heuristic, and why.

The API returns ``THRESHOLDS`` with each result (``thresholds[]``) so the dashboard can show "how this is measured".
A *heuristic* threshold is Pitwall's judgement, tested on recorded data (F1 25 on PS5) but not validated live;
the others are numerical choices (smoothing, search windows) or shared with ``analysis.braking``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Threshold:
    key: str
    value: float
    unit: str
    heuristic: bool
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "unit": self.unit,
            "heuristic": self.heuristic,
            "text": self.text,
            "group": GROUP_OF.get(self.key, "other"),
        }


# ---------------------------------------------------------------------------------------------- racing line
LINE_SMOOTH_M = 9.0
LINE_SEARCH_M = 30
LINE_COARSE_EVERY_M = 50
LINE_COARSE_SEARCH_M = 150
LINE_MAX_ALONG_M = 2.0
LINE_MAX_LATERAL_M = 25.0
LINE_POINT_HALF_WINDOW_M = 5.0
LINE_POINT_MIN_SAMPLES = 6
LINE_NOTABLE_M = 1.0
LINE_BIG_M = 2.0
TURN_IN_STEER_FRAC = 0.25
TRACK_OUT_STEER_FRAC = 0.25
STEER_PEAK_WINDOW_M = 150.0
STEER_SCAN_MAX_M = 300.0
STRAIGHT_CURVATURE = 1.0 / 2000.0
INSIDE_CURVATURE_HALF_M = 15
LINE_POLYLINE_STEP_M = 5
LINE_WINDOW_MARGIN_M = 40.0
LINE_WINDOW_STEP_M = 2
LINE_MAX_MARKERS = 5

# ---------------------------------------------------------------------------------------------- brake / throttle
BRAKE_ONSET = 0.10  # analysis.braking.BRAKE_ON
PEAK_FRAC = 0.90
RELEASE_END_FRAC = 0.10
STEP_RELEASE_S = 0.15
SHAPE_DROP_TRAIL_MAX = 0.40
SHAPE_LATE_DROP_MIN = 0.60
TRAIL_STEER_FRAC = 0.25
TRAIL_BRAKE_MIN = 0.05
COAST_PEDAL = 0.05
THROTTLE_PICKUP = 0.20
THROTTLE_FULL = 0.95
RAMP_MAX_S = 6.0
LIFT_DROP = 0.15
TRAIL_OVERLAP_NOTE_S = 0.15
COAST_NOTE_S = 0.15
PICKUP_NOTE_M = 5.0
RAMP_NOTE_S = 0.2
RAMP_NOTE_FRAC = 0.30
RELEASE_NOTE_FRAC = 0.25
WHEELSPIN_NOTE_S = 0.2
FULL_BRAKE = 0.95
MAX_NOTES_PER_CORNER = 3
HABIT_MIN_LAPS = 2
HABIT_MIN_FRAC = 0.5

# ---------------------------------------------------------------------------------------------- tyre slip
LOCKUP_SLIP = -0.20  # rig.rig_check.LOCK_SLIP (sign now known: negative under braking)
LOCKUP_MIN_S = 0.10
SPIN_SLIP = 0.15
SPIN_MIN_S = 0.20
SPIN_THROTTLE = 0.20
SPIN_AFTER_TRACK_OUT_M = 150.0

# ---------------------------------------------------------------------------------------------- balance
AT_LIMIT_FRAC = 0.60
AT_LIMIT_MIN_KPH = 40.0
MID_HALF_MIN_M = 10.0
MID_HALF_S = 0.5
PHASE_SPAN_M = 200.0
MIN_PHASE_SAMPLES = 6
US_DIFF_DEG = 3.0
STRONG_US_DIFF_DEG = 6.0
OS_DIFF_DEG = -1.0
SLIDE_BODY_SLIP_DEG = 5.0
SLIDE_MIN_S = 0.10
SLIDE_YAW_MIN_RPS = 0.05  # below this rotation the body slip's direction cannot be compared with the turn
COUNTERSTEER_STEER = 0.05
COUNTERSTEER_YAW_RPS = 0.10
COUNTERSTEER_MIN_S = 0.15
RECURRING_MIN_LAPS = 2
RECURRING_MIN_FRAC = 0.5
BALANCE_PACE_FRAC = 1.07  # a lap slower than this times the best clean lap is not at the limit (107 % rule)
WITH_BRAKING_PEDAL = 0.2
WITH_BRAKING_FRAC = 0.5
SPEED_SLOW_KPH = 120.0
SPEED_FAST_KPH = 200.0

# ---------------------------------------------------------------------------------------------- setup
SETUP_SINGLE_CORNER_MIN_LAPS = 3
LOCKUP_RECUR_CORNERS = 2
LOCKUP_RECUR_LAPS = 3
MAX_SUGGESTIONS_PER_SYMPTOM = 3

# ---------------------------------------------------------------------------------------------- pedals
PEAK_TOL_HALL = 0.08
TIME_TOL_HALL_S = 0.10
PEAK_TOL_LOAD_CELL = 0.05
TIME_TOL_LOAD_CELL_S = 0.07


THRESHOLDS: tuple[Threshold, ...] = (
    Threshold(
        "LINE_SMOOTH_M", LINE_SMOOTH_M, "m", False, "Moving average of the reference line, for its direction only."
    ),
    Threshold(
        "LINE_SEARCH_M",
        LINE_SEARCH_M,
        "m",
        False,
        "Each point of your lap is matched to the nearest reference point within this distance of the coarse match.",
    ),
    Threshold(
        "LINE_COARSE_EVERY_M",
        LINE_COARSE_EVERY_M,
        "m",
        False,
        "Spacing of the coarse lap-distance match (a safety net for games whose lap distance drifts).",
    ),
    Threshold("LINE_COARSE_SEARCH_M", LINE_COARSE_SEARCH_M, "m", False, "Search range of the coarse match."),
    Threshold(
        "LINE_MAX_ALONG_M",
        LINE_MAX_ALONG_M,
        "m",
        False,
        "A match must be roughly square to the reference line; otherwise the point is left out.",
    ),
    Threshold(
        "LINE_MAX_LATERAL_M",
        LINE_MAX_LATERAL_M,
        "m",
        True,
        "Further than this from the reference line is off the track or the pit lane, so the point is left out.",
    ),
    Threshold(
        "LINE_POINT_HALF_WINDOW_M",
        LINE_POINT_HALF_WINDOW_M,
        "m",
        False,
        "Turn-in, apex and track-out offsets are the median over this distance either side (at least 6 samples).",
    ),
    Threshold(
        "LINE_NOTABLE_M",
        LINE_NOTABLE_M,
        "m",
        True,
        "A line difference is called out from this size. The same driver's laps typically differ by 0.7 to 2.8 m.",
    ),
    Threshold("LINE_BIG_M", LINE_BIG_M, "m", True, "A big line difference."),
    Threshold(
        "TURN_IN_STEER_FRAC",
        TURN_IN_STEER_FRAC,
        "fraction",
        True,
        "Turn-in is where steering rises above "
        "this share of the corner's steering peak; track-out is where it falls below it again.",
    ),
    Threshold(
        "STRAIGHT_CURVATURE",
        STRAIGHT_CURVATURE,
        "1/m",
        True,
        "Below this curvature (radius above 2 km) "
        "which side is the inside is unknown, so offsets are given without a side.",
    ),
    Threshold(
        "PEAK_FRAC",
        PEAK_FRAC,
        "fraction",
        True,
        "Brake at or above this share of its peak counts as the peak (as in braking detection).",
    ),
    Threshold(
        "RELEASE_END_FRAC",
        RELEASE_END_FRAC,
        "fraction",
        True,
        "The release ends when the brake falls below this share of its peak (or at the slowest point of the corner).",
    ),
    Threshold(
        "STEP_RELEASE_S", STEP_RELEASE_S, "s", True, "A release shorter than this is a step (let off in one go)."
    ),
    Threshold(
        "SHAPE_DROP_TRAIL_MAX",
        SHAPE_DROP_TRAIL_MAX,
        "fraction",
        True,
        "Release area below this: dropped most of the brake, then trailed the rest.",
    ),
    Threshold(
        "SHAPE_LATE_DROP_MIN",
        SHAPE_LATE_DROP_MIN,
        "fraction",
        True,
        "Release area above this: held the brake, then let go late.",
    ),
    Threshold(
        "TRAIL_STEER_FRAC",
        TRAIL_STEER_FRAC,
        "fraction",
        True,
        "Braking counts as trail braking while steering is above this share of the corner's steering peak.",
    ),
    Threshold("COAST_PEDAL", COAST_PEDAL, "fraction", False, "Coasting: brake and throttle both below this."),
    Threshold(
        "THROTTLE_PICKUP", THROTTLE_PICKUP, "fraction", False, "Throttle pick-up level (as in braking detection)."
    ),
    Threshold("THROTTLE_FULL", THROTTLE_FULL, "fraction", False, "Full throttle level."),
    Threshold("RAMP_MAX_S", RAMP_MAX_S, "s", True, "The throttle ramp is measured for at most this long."),
    Threshold(
        "LIFT_DROP",
        LIFT_DROP,
        "fraction",
        True,
        "A throttle lift is a drop of at least this much below the highest throttle so far on the exit.",
    ),
    Threshold(
        "LOCKUP_SLIP",
        LOCKUP_SLIP,
        "slip ratio",
        True,
        "A wheel locking: slip ratio at or below this under "
        "braking. With ABS on the real minimum seen was -0.18, so lock-ups are not analysed then.",
    ),
    Threshold("LOCKUP_MIN_S", LOCKUP_MIN_S, "s", True, "A lock-up lasts at least this long."),
    Threshold(
        "SPIN_SLIP",
        SPIN_SLIP,
        "slip ratio",
        True,
        "Wheelspin: a rear wheel's slip ratio at or above this on "
        "the throttle (real plateaus with traction control on were 0.15 to 0.24).",
    ),
    Threshold("SPIN_MIN_S", SPIN_MIN_S, "s", True, "Wheelspin lasts at least this long."),
    Threshold(
        "AT_LIMIT_FRAC",
        AT_LIMIT_FRAC,
        "fraction",
        True,
        "Balance is read only where lateral g is at least "
        "this share of the corner's 95th percentile (and above 40 km/h).",
    ),
    Threshold(
        "MID_HALF_MIN_M",
        MID_HALF_MIN_M,
        "m",
        True,
        "Mid-corner is the slowest point plus or minus the larger of this and half a second of travel.",
    ),
    Threshold(
        "PHASE_SPAN_M", PHASE_SPAN_M, "m", True, "Entry and exit are read up to this far from the slowest point."
    ),
    Threshold(
        "US_DIFF_DEG",
        US_DIFF_DEG,
        "deg",
        True,
        "Understeer: the front tyres run at least this much more "
        "slip angle than the rears at the limit (real neutral corners read +0.4 to +2.9 deg).",
    ),
    Threshold("STRONG_US_DIFF_DEG", STRONG_US_DIFF_DEG, "deg", True, "Strong understeer."),
    Threshold(
        "OS_DIFF_DEG",
        OS_DIFF_DEG,
        "deg",
        True,
        "Oversteer: the rears run more slip angle than the fronts by at least this much (negative difference).",
    ),
    Threshold(
        "SLIDE_BODY_SLIP_DEG",
        SLIDE_BODY_SLIP_DEG,
        "deg",
        True,
        "A slide: the car points at least this far away from where it is travelling, tail out, for at least 0.1 s "
        "(recorded slides were 5.4 to 6.7 deg). The opposite direction is the normal body slip of a slow, tight "
        "turn and does not count.",
    ),
    Threshold(
        "COUNTERSTEER_MIN_S",
        COUNTERSTEER_MIN_S,
        "s",
        True,
        "Counter-steer: steering against the rotation "
        "(steer at least 5 %, rotation at least 0.1 rad/s) for at least this long.",
    ),
    Threshold(
        "RECURRING_MIN_LAPS",
        RECURRING_MIN_LAPS,
        "laps",
        True,
        "A handling symptom recurs when it shows on at least this many laps and on at least half the laps with data.",
    ),
    Threshold(
        "BALANCE_PACE_FRAC",
        BALANCE_PACE_FRAC,
        "ratio",
        True,
        "Laps slower than this times your best clean lap (a safety car, a cool-down) and standing starts are left out "
        "of the handling balance and the habits: they are not driven at the limit.",
    ),
    Threshold(
        "SPEED_SLOW_KPH",
        SPEED_SLOW_KPH,
        "km/h",
        True,
        "Corners slower than this are slow; 200 km/h and above are fast (the track model's minimum speed).",
    ),
    Threshold(
        "PEAK_TOL_HALL",
        PEAK_TOL_HALL,
        "fraction",
        True,
        "Brake pressure difference called out with a travel-sensing brake (stock CSL) or unknown pedals.",
    ),
    Threshold(
        "TIME_TOL_HALL_S",
        TIME_TOL_HALL_S,
        "s",
        True,
        "Brake timing difference called out with a travel-sensing brake (stock CSL) or unknown pedals.",
    ),
    Threshold(
        "PEAK_TOL_LOAD_CELL",
        PEAK_TOL_LOAD_CELL,
        "fraction",
        True,
        "Brake pressure difference called out with a load cell brake.",
    ),
    Threshold(
        "TIME_TOL_LOAD_CELL_S",
        TIME_TOL_LOAD_CELL_S,
        "s",
        True,
        "Brake timing difference called out with a load cell brake.",
    ),
)


# The "How this is measured" sheet's headings: where each section of ``THRESHOLDS`` starts (they are in this order).
GROUP_STARTS: dict[str, str] = {
    "LINE_SMOOTH_M": "line",
    "PEAK_FRAC": "inputs",
    "LOCKUP_SLIP": "slip",
    "AT_LIMIT_FRAC": "balance",
    "PEAK_TOL_HALL": "pedals",
}


def _groups() -> dict[str, str]:
    out: dict[str, str] = {}
    group = "other"
    for t in THRESHOLDS:
        group = GROUP_STARTS.get(t.key, group)
        out[t.key] = group
    return out


GROUP_OF: dict[str, str] = _groups()


def threshold_infos() -> list[dict[str, Any]]:
    return [t.to_dict() for t in THRESHOLDS]
