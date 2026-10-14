"""Live predictive braking cues (phase 6, first slice): deterministic, evidence-based, no LLM.

The radio calls a braking zone so that the key word lands where the driver braked on their own reference lap.
Modes (radio setting, default ``focus``):

* ``off``     - nothing.
* ``focus``   - "<corner> brake" only for the 1-3 corners whose recent *braking* observations (``brake_early``,
  ``brake_late_overdrive``, ``overspeed_apex``) carry the most priority. "brake" lands on the reference braking
  point. Which observations qualify follows the seated driver's coaching profile (``FocusLimits``): a beginner
  gets fewer, surer calls than an advanced driver.
* ``markers`` - the corner name ``MARKER_LEAD_S`` before every reference braking zone (a rhythm aid).
* ``all``     - "brake" at every reference braking zone.

Evidence and safety (CLAUDE.md)
-------------------------------
Targets are the reference lap's *measured* braking onsets (``CornerMetrics.brake_start_m`` from
``analysis.compare``, the lap ``LapProcessor`` compared against). Nothing is modelled or invented: a corner
without a measured, substantial reference braking event (peak pedal >= ``MIN_REF_BRAKE_PEAK``) gets no cue. The
reference is the driver's own fastest compatible clean lap; when the latest comparison is not compatible there
are no cues, and a focus corner needs an observation of at least ``MIN_FOCUS_CONFIDENCE`` that the analysis only
emits when the corner lost time against that reference.

Coaching never recommends braking later on its own, so every uncertainty resolves towards calling *early*:
``MARGIN_M`` before the point, word offsets estimated long, the earlier of two time-to-go estimates, and no cue
when the car approaches faster than the reference did (DRS / tow: the reference point would be too late for that
speed). The hard line is the reference point itself: a cue whose key word is predicted to land after it (a late
frame, a distance jump, a plan that arrived mid-approach) is dropped instead of said late, and the event carries
a ``deadline_mono`` past which the radio must drop it too (a stalled hand-off would push it past the point).

Corner names
------------
Cue plans key corners by the learned name (``T1..Tn``, the join key of comparisons and observations). What the
driver reads and hears is the name the dashboard's track view uses: when a verified track sheet maps the learned
corners (``analysis.track_identity``), ``CueLabel`` carries the official label ("T3", "T1 (2)") for the text and
"Turn 3" for speech. Learned numbers are not official ones (Austria's flat Turns 2, 5 and 8 have no speed minimum,
so a real F1 25 race replay had learned "T2" = Turn 3): a cue must never say a number the track view does not
show. A corner with no speakable label gets a plain "brake" call; an unmapped model keeps the learned names.

Another driver's lap as the reference (coachref)
-----------------------------------------------
When the driver chose another driver's lap (``core.coachref``), the comparison carries ``brake_clamp_m``: the
driver's *own* braking point per corner. Every braking zone is then ``min(their point, your own point)``, and a
corner where the driver has no measured point of their own gets no cue at all (``NO_OWN_POINTS`` when that leaves
nothing; the AI field's heads-ups may stand in, as early markers, never as targets). So a faster driver's later
braking point is never called. During a practice drill (``set_drill_corner``) the plan holds only the drill corner
(in focus mode it is the focus corner, whatever the observation history says) and the field's heads-ups are off.

Cues belong to one driver's reference. Clearing the reference (``on_reference(None, None)``: the session's owner
has no reference lap) or a different driver in the seat (``set_driver``) drops the comparison, the focus history
and the plan, so one driver is never called to another driver's braking points.

Timing
------
A cue fires on the first frame where the estimated time to the target ``ttg`` satisfies::

    ttg <= latency_s + word_offset_s + anticipation_s + MARGIN_M / v + frame_dt / 2

which is the ``cue_distance = target - v * (latency + word_offset) - margin`` rule evaluated in time, so speed
changes during the approach are accounted for. ``ttg`` is the smaller of ``k / v`` (constant speed over the
``k`` metres to go) and the reference lap's own time over the same metres scaled by ``v_ref / v`` (captures the
acceleration still to come on the straight). The half frame centres quantisation error at +-half a frame
spacing instead of 0..1 frame late. ``latency_s`` (fire -> audio audible) and the key word's offset inside the
pre-synthesised audio are pushed by the radio hub as an immutable ``CueTiming``.

Threads
-------
* Planning (``on_lap_result``, ``on_reference``, ``set_mode``...) runs on the lap-analysis thread or the asyncio
  loop under ``_plan_lock`` and swaps an immutable ``CuePlan`` in with one attribute assignment.
* ``on_frame`` runs on the ingest thread for EVERY frame and is O(1): a pointer into the plan's cues (sorted by
  target) per lap, at most ``LOOKAHEAD`` checks of one table lookup each. It never takes the planner lock, never
  blocks and never raises (errors are counted). A fired ``CueEvent`` goes to the sink, which must not block (the
  radio hub marshals it onto its loop with ``call_soon_threadsafe``).

Lap handling
------------
One cue per corner per lap: resolved corners (fired, missed or suppressed) are remembered per lap *token*
(``lap_number``, +1 for cues fired before the line for the next lap's first corners), so flashbacks, a plan swap
mid-lap and lap wrap never repeat a call. Rewinds (session time or distance going backwards) re-seek the
pointer. Distance jumps (real F1 data jumps ~150 m in one frame) and late plans skip a cue rather than call it
late. No cues: in or after a pit visit for the rest of that lap (out laps, in laps), on a race's standing-start
lap 1, under safety car / VSC / formation lap, below ``MIN_CUE_SPEED_KPH``, or while paused / not racing. In a race
of known length the final lap gets no pre-line call for a next lap that is never driven, and nothing is called
after the flag (real F1 25: the lap distance wraps one frame before ``resultStatus`` turns finished).
"""

from __future__ import annotations

import bisect
import itertools
import logging
import math
import re
import threading
import time
from array import array
from collections import deque
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Literal, Protocol

import numpy as np

from pitwall.analysis.distance import DistanceTrace
from pitwall.analysis.track_identity import turn_words
from pitwall.model.telemetry import CarFrame, FrameQuality

__all__ = [
    "CUE_MODES",
    "DEFAULT_CUE_MODE",
    "BrakingZone",
    "CoachingProfile",
    "CueApproach",
    "CueEngine",
    "CueEvent",
    "CueKind",
    "CueLabel",
    "CueMode",
    "CuePlan",
    "CueSpec",
    "CueTiming",
    "FocusLimits",
    "FrameSample",
    "build_cue_plan",
    "cue_labels",
    "cue_timing_error_m",
    "estimate_word_offset",
    "parse_cue_mode",
    "reference_braking_zones",
    "reference_onset_ok",
    "select_focus_corners",
]

log = logging.getLogger(__name__)

CueMode = Literal["off", "focus", "markers", "all"]
CUE_MODES: tuple[CueMode, ...] = ("off", "focus", "markers", "all")
DEFAULT_CUE_MODE: CueMode = "focus"

# ---------------------------------------------------------------------------------------------- planning
MAX_FOCUS_CORNERS = 3
FOCUS_HISTORY_LAPS = 3  # laps of observations (against the same reference) considered for focus corners
FOCUS_DECAY = 0.6  # weight of a lap's observations per lap of age (newest = 1)
MIN_FOCUS_CONFIDENCE = 0.6  # same bar as the radio's coaching points (voice.proactive)
BRAKE_CUE_OBSERVATIONS = frozenset({"brake_early", "brake_late_overdrive", "overspeed_apex"})
MIN_REF_BRAKE_PEAK = 0.3  # a lighter reference application is a dab or a lift, not a braking zone to call
MIN_REF_SPEED_DROP_KPH = 15.0  # entry -> minimum speed of the reference, when both are known
MARKER_LEAD_S = 2.0  # markers mode: corner name this long before the braking point
WINDOW_M = 800  # approach covered by a cue's time-to-go table (>= ~8 s of lead at 95 m/s)
# A reference "braking point" where the reference was already slowing is a re-application inside a longer
# braking zone (the analysis matches a corner to its *latest* braking event): never a point to call "brake".
REAPPLY_WINDOW_M = 150
REAPPLY_SPEED_RATIO = 0.9  # speed at the point below 90% of the approach's peak speed = already slowing
TRACE_CACHE = 4  # reference traces kept by lap id (a cached reference survives session resets)
BEGINNER_FOCUS_CORNERS = 1  # a beginner's profile allows one coaching point a lap (drivers.coaching_limits)
NO_REFERENCE = "no reference lap yet"
NO_DRIVER_REFERENCE = "no reference lap for this driver"
NEW_DRIVER = "new driver: waiting for a lap against their reference"
NO_OWN_POINTS = "no braking points of your own yet"  # --- coachref --- another driver's lap, none of the driver's
# Empty-plan reasons that mean "nothing of the driver's own to call": only then may the AI field's heads-ups
# (core.track_knowledge, layer L0b) stand in. A reference that exists but gives no cue keeps silence.
FALLBACK_REASONS = frozenset({NO_REFERENCE, NO_DRIVER_REFERENCE, NEW_DRIVER, NO_OWN_POINTS})

# ---------------------------------------------------------------------------------------------- firing
MARGIN_M = 5.0  # the key word aims this far before the reference point; it may use the margin, never pass the point
OVERSPEED_TOLERANCE = 0.03  # approach >3% faster than the reference (DRS, tow): its braking point is too late
MIN_CUE_SPEED_KPH = 60.0
LOOKAHEAD = 3  # cues checked per frame (overlapping approach windows of close braking zones)
REWIND_M = 30.0  # a backward step larger than this within a lap is a flashback / reset to track
STANDING_START_M = 60.0  # race lap 1 first seen this far past the line at ~0 lap time = grid start
DEFAULT_FRAME_DT_S = 1 / 60
MAX_FRAME_DT_S = 0.25
FRAME_DT_SMOOTHING = 0.1
MAX_SAMPLE_AGE_S = 0.25  # timing measurement: last frame must be this fresh to extrapolate the car position

# ---------------------------------------------------------------------------------------------- timing defaults
DEFAULT_LATENCY_S = 0.25  # fire -> audible for pre-synthesised audio until the hub has measured it
MAX_LATENCY_S = 2.0
DEFAULT_WORD_S = 1 / 2.6  # seconds per spoken word (voice.scheduler.WORDS_PER_S: deliberately slow = early)
PART_PAUSE_S = 0.15  # pause between spoken parts ("turn 9, brake")

_NOT_DRIVING = FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING | FrameQuality.NOT_RACING
_CORNER_ID = re.compile(r"T\d+", re.IGNORECASE)  # "T9" is spoken "turn 9": two words
_NO_SAFETY_CAR = frozenset({"none"})


def parse_cue_mode(value: str) -> CueMode:
    """Validate a cue mode from settings / the radio protocol (case-insensitive)."""
    v = value.strip().lower()
    for m in CUE_MODES:
        if v == m:
            return m
    raise ValueError(f"unknown cue mode {value!r}; expected one of {', '.join(CUE_MODES)}")


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


# ============================================================================================== data types
class CueKind(StrEnum):
    BRAKE = "brake"  # the key word lands on the reference braking point
    MARKER = "marker"  # the corner name starts ``anticipation_s`` before it


@dataclass(slots=True, frozen=True)
class CueSpec:
    """One planned call. ``parts`` are display tokens spoken in order (the hub runs ``to_speech`` on each and
    pre-synthesises them separately, so the key part's position in the audio is known exactly)."""

    corner: str
    kind: CueKind
    target_m: float  # reference braking point (lap distance, m)
    text: str  # display text, e.g. "T9 brake"
    parts: tuple[str, ...]  # e.g. ("T9", "brake")
    key_index: int  # part that must start at the aim point
    anticipation_s: float = 0.0
    focus: bool = False
    reason: str = ""  # evidence behind the cue (display / logs)
    ref_speed_kph: float | None = None  # reference speed at its braking point (overspeed guard)

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner": self.corner,
            "kind": self.kind.value,
            "target_m": round(self.target_m, 1),
            "text": self.text,
            "focus": self.focus,
            "reason": self.reason,
        }


@dataclass(slots=True, frozen=True)
class CueLabel:
    """How a cue names a learned corner (``cue_labels``): ``text`` for displays (the track view's short label),
    ``spoken`` for the radio's corner part ("Turn 3"; None = no speakable short name, call just "brake"), ``voice``
    for a markers-mode call that must name the corner ("Corner at 570 metres")."""

    text: str
    spoken: str | None
    voice: str


@dataclass(slots=True, frozen=True)
class CueApproach:
    """Reference lap over the approach: index ``k`` = metres before the target (1 m grid, NaN = unknown)."""

    ttg_s: array[float]  # reference seconds from (target - k) to the target
    v_mps: array[float]  # reference speed at (target - k)


@dataclass(slots=True, frozen=True)
class CuePlan:
    """Immutable cue list for one reference; ``cues`` sorted by target, ``targets`` mirrors them for bisect."""

    mode: CueMode
    cues: tuple[CueSpec, ...] = ()
    approaches: tuple[CueApproach | None, ...] = ()
    targets: tuple[float, ...] = ()
    length_m: float = 0.0
    window_m: float = float(WINDOW_M)
    ref_lap_id: int | None = None
    ref_lap_number: int | None = None
    focus: tuple[str, ...] = ()
    reason: str | None = None  # why there are no cues (display)

    @classmethod
    def empty(
        cls,
        mode: CueMode,
        reason: str | None,
        *,
        ref_lap_id: int | None = None,
        ref_lap_number: int | None = None,
        length_m: float = 0.0,
    ) -> CuePlan:
        return cls(mode=mode, reason=reason, ref_lap_id=ref_lap_id, ref_lap_number=ref_lap_number, length_m=length_m)


@dataclass(slots=True, frozen=True)
class CueTiming:
    """Delivery timing pushed by the radio hub. ``offsets_s``: measured start of the key part inside the audio
    for a phrase (``CueSpec.parts``); phrases without one fall back to ``estimate_word_offset``."""

    latency_s: float = DEFAULT_LATENCY_S  # fire -> first audio in the driver's ear
    path: str = "pcm"  # "pcm" (server audio) | "device" (device speaks the text)
    offsets_s: Mapping[tuple[str, ...], float] = field(default_factory=dict)
    word_s: float = DEFAULT_WORD_S

    def word_offset(self, cue: CueSpec) -> float:
        if cue.key_index <= 0:
            return 0.0
        off = self.offsets_s.get(cue.parts)
        return off if off is not None else estimate_word_offset(cue.parts, cue.key_index, self.word_s)


@dataclass(slots=True, frozen=True)
class CueEvent:
    """A cue the engine decided to call (handed to the sink from the ingest thread)."""

    seq: int
    cue: CueSpec
    lap: int  # lap token the cued corner belongs to
    fired_lap: int  # lap token when it fired (lap - 1 when called before the line)
    fired_mono: float  # host monotonic time of the decision
    session_time_s: float | None  # game clock of the frame that fired it
    d_m: float  # lap distance at the decision
    v_mps: float
    ttg_s: float  # estimated time to the target at the decision
    latency_s: float
    word_offset_s: float
    path: str
    aim_m: float  # where the key word should start, in ``lap``'s distance (negative = before the line)
    ref_lap_id: int | None

    @property
    def deadline_mono(self) -> float:
        """Latest host time the radio may still start delivering this cue.

        At the decision the key word was predicted to land ``ttg_s - lead`` before the reference point (lead =
        latency + key-word offset + anticipation; ``slack`` below). Every second the hand-off to the radio takes
        beyond that moves the word past the point, which coaching must never do, so a later delivery is dropped.
        Conservative: the measured latency already contains a typical hand-off."""
        lead = self.latency_s + self.word_offset_s + self.cue.anticipation_s
        return self.fired_mono + max(0.0, self.ttg_s - lead)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            **self.cue.to_dict(),
            "lap": self.lap,
            "d_m": round(self.d_m, 1),
            "speed_kph": round(self.v_mps * 3.6, 1),
            "aim_m": round(self.aim_m, 1),
            "latency_ms": round(self.latency_s * 1000),
            "word_offset_ms": round(self.word_offset_s * 1000),
            "path": self.path,
        }


@dataclass(slots=True, frozen=True)
class FrameSample:
    """Last frame the engine saw (lap token, position), for measuring where a cue was actually heard."""

    mono: float
    lap: int
    d_m: float
    v_mps: float


@dataclass(slots=True, frozen=True)
class BrakingZone:
    corner: str
    brake_m: float
    peak: float
    entry_speed_kph: float | None
    min_speed_kph: float | None


class CoachingProfile(Protocol):
    """What the focus selection reads from a driver's coaching profile (``drivers.CoachingLimits`` satisfies it;
    a protocol keeps the cue engine free of the driver registry and its storage imports)."""

    @property
    def skill_level(self) -> str: ...

    @property
    def min_confidence(self) -> float: ...

    @property
    def min_impact_s(self) -> float: ...

    @property
    def allowed_kinds(self) -> frozenset[str] | None: ...


@dataclass(slots=True, frozen=True)
class FocusLimits:
    """Which corrective braking observations may become a focus cue: the seated driver's coaching profile.

    The defaults are the engine's own bar (identical to the radio's pre-profile coaching). A profile can only
    *raise* the confidence bar (``MIN_FOCUS_CONFIDENCE`` is the floor for a time-critical call), and with an
    impact floor an observation of unknown impact is not spoken (unknown is not small, as in
    ``drivers.apply_coaching_limits``). ``allowed_kinds`` narrows ``BRAKE_CUE_OBSERVATIONS``; it never widens it.
    """

    min_confidence: float = MIN_FOCUS_CONFIDENCE
    min_impact_s: float = 0.0
    allowed_kinds: frozenset[str] | None = None
    max_corners: int = MAX_FOCUS_CORNERS

    def __post_init__(self) -> None:
        if not (math.isfinite(self.min_confidence) and 0.0 <= self.min_confidence <= 1.0):
            raise ValueError(f"min_confidence must be 0-1, got {self.min_confidence}")
        if not (math.isfinite(self.min_impact_s) and 0.0 <= self.min_impact_s <= 10.0):
            raise ValueError(f"min_impact_s must be 0-10 s, got {self.min_impact_s}")
        if not 1 <= self.max_corners <= MAX_FOCUS_CORNERS:
            raise ValueError(f"max_corners must be 1-{MAX_FOCUS_CORNERS}, got {self.max_corners}")

    @classmethod
    def from_profile(cls, profile: CoachingProfile) -> FocusLimits:
        """Limits for a driver's coaching profile. A beginner's profile allows one point a lap, so one focus
        corner; other levels keep the engine's 1-3 (the cue is the corner's braking point, not extra talk)."""
        kinds = profile.allowed_kinds
        return cls(
            min_confidence=max(MIN_FOCUS_CONFIDENCE, float(profile.min_confidence)),
            min_impact_s=float(profile.min_impact_s),
            allowed_kinds=None if kinds is None else frozenset(kinds),
            max_corners=BEGINNER_FOCUS_CORNERS if profile.skill_level == "beginner" else MAX_FOCUS_CORNERS,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_confidence": self.min_confidence,
            "min_impact_s": self.min_impact_s,
            "allowed_kinds": None if self.allowed_kinds is None else sorted(self.allowed_kinds),
            "max_corners": self.max_corners,
        }


DEFAULT_FOCUS_LIMITS = FocusLimits()


# ============================================================================================== planning (pure)
def estimate_word_offset(parts: Sequence[str], key_index: int, word_s: float = DEFAULT_WORD_S) -> float:
    """Spoken length of the parts before the key part. Errs long (= the cue fires early)."""
    words = 0
    for p in parts[:key_index]:
        for tok in p.split():
            words += 2 if _CORNER_ID.fullmatch(tok) else 1
    return words * word_s + PART_PAUSE_S * max(0, key_index)


def reference_braking_zones(comparison: Mapping[str, Any], length_m: float) -> list[BrakingZone]:
    """Measured reference braking points per corner (``LapComparison.to_dict()['corners'][i]['ref']``).

    With ``comparison['brake_clamp_m']`` (coachref: the reference is another driver's lap) each point is the earlier
    of the reference's and the driver's own, and a corner without a point of the driver's own is left out."""
    zones: dict[str, BrakingZone] = {}
    clamp = comparison.get("brake_clamp_m")  # --- coachref ---
    clamp_map = clamp if isinstance(clamp, Mapping) else None
    for cd in comparison.get("corners") or ():
        if not isinstance(cd, Mapping):
            continue
        corner = cd.get("corner")
        ref = cd.get("ref")
        if not isinstance(corner, str) or not corner or not isinstance(ref, Mapping):
            continue
        b = _num(ref.get("brake_start_m"))
        peak = _num(ref.get("brake_peak"))
        if b is None or peak is None or not 0.0 <= b < length_m or peak < MIN_REF_BRAKE_PEAK:
            continue  # no measured, substantial reference braking: nothing to call
        entry, vmin = _num(ref.get("entry_speed_kph")), _num(ref.get("min_speed_kph"))
        if entry is not None and vmin is not None and entry - vmin < MIN_REF_SPEED_DROP_KPH:
            continue
        if clamp_map is not None:  # --- coachref --- never later than the driver's own braking point
            own = _num(clamp_map.get(corner))
            if own is None:
                continue
            b = min(b, own)
            if b < 0.0:
                continue
        zones.setdefault(corner, BrakingZone(corner, b, peak, entry, vmin))
    return sorted(zones.values(), key=lambda z: z.brake_m)


def select_focus_corners(
    history: Sequence[Sequence[Mapping[str, Any]]],
    zones: Collection[str],
    max_corners: int = MAX_FOCUS_CORNERS,
    limits: FocusLimits = DEFAULT_FOCUS_LIMITS,
) -> list[tuple[str, str]]:
    """``(corner, reason)`` for the corners with the most corrective braking evidence, best first.

    ``history`` holds each recent lap's observations (``Observation.to_dict()``), oldest first, all against the
    current reference. A lap's priorities are weighted ``FOCUS_DECAY ** age``, so a habit outranks a one-off and
    a fixed corner drops out after a few laps. Only corners with a measured reference braking zone qualify, and
    only observations the driver's profile (``limits``) would have the radio say.
    """
    allowed = set(zones)
    kinds = BRAKE_CUE_OBSERVATIONS if limits.allowed_kinds is None else BRAKE_CUE_OBSERVATIONS & limits.allowed_kinds
    min_conf = max(MIN_FOCUS_CONFIDENCE, limits.min_confidence)
    scores: dict[str, float] = {}
    first_kind: dict[str, str] = {}
    laps_with: dict[str, int] = {}
    total = len(history)
    for age, observations in enumerate(reversed(history)):
        weight = FOCUS_DECAY**age
        seen: set[str] = set()
        for o in observations:
            corner, kind = o.get("corner"), o.get("kind")
            if not isinstance(corner, str) or corner not in allowed or o.get("positive"):
                continue
            if kind not in kinds:
                continue
            conf = _num(o.get("confidence")) or 0.0
            if conf < min_conf:
                continue
            if limits.min_impact_s > 0.0:
                impact = _num(o.get("impact_s"))
                if impact is None or abs(impact) < limits.min_impact_s:
                    continue  # unknown impact is not small: not worth a call on this profile
            prio = _num(o.get("priority"))
            if prio is None:
                prio = abs(_num(o.get("impact_s")) or 0.0) * conf
            if prio <= 0.0:
                continue
            scores[corner] = scores.get(corner, 0.0) + weight * prio
            first_kind.setdefault(corner, str(kind))  # newest lap first: the most recent evidence names it
            if corner not in seen:
                seen.add(corner)
                laps_with[corner] = laps_with.get(corner, 0) + 1
    n = max(1, min(MAX_FOCUS_CORNERS, max_corners, limits.max_corners))
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return [(c, f"{first_kind[c]} on {laps_with[c]} of the last {total} lap(s)") for c, _ in ranked]


def _approach_table(trace: DistanceTrace, target: float, length_m: float, lap_s: float | None) -> CueApproach | None:
    speed = trace.ch.get("speed_kph")
    d = trace.d
    if speed is None or len(d) < 2:
        return None
    ks = np.arange(0.0, WINDOW_M + 1.0)
    pos = target - ks
    wrap = pos < 0.0  # the approach starts on the previous lap
    pos_w = np.where(wrap, pos + length_m, pos)
    t_pos = np.interp(pos_w, d, trace.t_s, left=np.nan, right=np.nan)
    t_target = float(np.interp(target, d, trace.t_s, left=np.nan, right=np.nan))
    lap_t = np.nan if lap_s is None else lap_s
    ttg = np.where(wrap, t_target + (lap_t - t_pos), t_target - t_pos)
    v = np.interp(pos_w, d, speed, left=np.nan, right=np.nan) / 3.6
    with np.errstate(invalid="ignore"):
        bad = ~np.isfinite(ttg) | (ttg < 0.0) | ~np.isfinite(v) | (v <= 1.0)
    if bool(bad.all()):
        return None
    ttg[bad] = np.nan
    v[bad] = np.nan
    return CueApproach(array("d", ttg.tolist()), array("d", v.tolist()))


def _already_slowing(app: CueApproach) -> bool:
    """True when the reference was already braking or slowing into this point (or its speed there is unknown)."""
    v0 = app.v_mps[0]
    if v0 != v0:
        return True  # unknown speed at the point: cannot show it is a braking onset
    window = [v for v in app.v_mps[: REAPPLY_WINDOW_M + 1] if v == v]
    return v0 < REAPPLY_SPEED_RATIO * max(window, default=v0)


# --- coachref ---
def reference_onset_ok(trace: DistanceTrace, target_m: float, length_m: float, lap_s: float | None) -> bool:
    """Whether ``target_m`` is a braking *onset* on the reference trace by the cue planner's own test (an approach
    table exists and the reference was not already slowing there): the drill planner uses the same rule."""
    app = _approach_table(trace, target_m, length_m, lap_s)
    return app is not None and not _already_slowing(app)


# --- coachref ---


def cue_labels(track_model: Mapping[str, Any] | None) -> dict[str, CueLabel]:
    """``{learned corner name: CueLabel}`` from the live track model payload (``track_model_payload``: corners with
    their identity fields plus ``corner_text``). Empty when the model carries no identity (no sheet, unverified
    turns, synthetic tracks): cues then use the learned names, as the dashboard does. Never raises."""
    try:
        if not isinstance(track_model, Mapping):
            return {}
        corners = track_model.get("corners")
        texts = track_model.get("corner_text")
        if not isinstance(corners, list) or not isinstance(texts, Mapping):
            return {}
        if not any(isinstance(c, Mapping) and c.get("identity_tier") for c in corners):
            return {}
        out: dict[str, CueLabel] = {}
        for c in corners:
            if not isinstance(c, Mapping):
                continue
            name, ct = c.get("name"), texts.get(c.get("name"))
            if not isinstance(name, str) or not isinstance(ct, Mapping):
                continue
            short, voice = ct.get("short"), ct.get("voice")
            if not isinstance(short, str) or not short or not isinstance(voice, str) or not voice:
                continue
            label, display = c.get("label"), c.get("display_name")
            spoken: str | None = None
            if isinstance(label, str) and label:
                spoken = turn_words(label, voice=True)  # the turn, without "second part" or the name: a cue is short
            elif isinstance(display, str) and display and c.get("voice_ok") is True:
                spoken = display
            out[name] = CueLabel(short, spoken, voice)
        return out
    except Exception:  # a malformed payload must never stop planning: learned names are always correct keys
        log.exception("cue labels from the track model failed; using learned corner names")
        return {}


def build_cue_plan(
    mode: str,
    comparison: Mapping[str, Any] | None,
    *,
    length_m: float | None,
    history: Sequence[Sequence[Mapping[str, Any]]] = (),
    reference: Mapping[str, Any] | None = None,
    trace: DistanceTrace | None = None,
    max_focus: int = MAX_FOCUS_CORNERS,
    focus_limits: FocusLimits = DEFAULT_FOCUS_LIMITS,
    labels: Mapping[str, CueLabel] | None = None,
    only_corner: str | None = None,
) -> CuePlan:
    """Plan the cues for the current reference.

    ``comparison`` is the latest lap's ``LapComparison.to_dict()`` plus ``ref_lap_id`` (as ``LapProcessor``
    publishes it): it carries the compatibility verdict and the reference's measured braking points.
    ``reference``/``trace`` are the reference lap's summary and distance trace (``LiveState.set_reference``); the
    trace is required. It times the approach (time-to-go tables) and proves each point is a braking *onset*: a
    point the reference reached while already slowing is a re-application and gets no cue. ``history`` is the
    recent laps' observations for focus mode, filtered by the driver's ``focus_limits``. ``labels``
    (``cue_labels``) name the corners as the track view does; without one a corner keeps its learned name. Never
    raises on malformed input: an empty plan's ``reason`` says why there are no cues. ``only_corner`` (a practice
    drill, coachref) keeps that corner alone: in focus mode it is the focus corner whatever the history says.
    """
    m = parse_cue_mode(mode)
    if m == "off":
        return CuePlan.empty(m, "cues off")
    if comparison is None:
        return CuePlan.empty(m, NO_REFERENCE)
    compat = comparison.get("compatibility")
    if not isinstance(compat, Mapping) or compat.get("ok") is not True:
        blocking = compat.get("blocking") if isinstance(compat, Mapping) else None
        first = blocking[0] if isinstance(blocking, list) and blocking else "compatibility unknown"
        return CuePlan.empty(m, f"reference not usable: {first}")
    length = _num(length_m)
    if length is None or length <= 0:
        return CuePlan.empty(m, "track length unknown")
    ref_id = comparison.get("ref_lap_id")
    ref_lap_id = ref_id if isinstance(ref_id, int) and not isinstance(ref_id, bool) else None
    ref_no = comparison.get("ref_lap_number")
    ref_lap_number = ref_no if isinstance(ref_no, int) and not isinstance(ref_no, bool) else None

    def empty(reason: str) -> CuePlan:
        return CuePlan.empty(m, reason, ref_lap_id=ref_lap_id, ref_lap_number=ref_lap_number, length_m=length)

    if trace is None or (reference is not None and reference.get("lap_id") not in (None, ref_lap_id)):
        return empty("reference lap trace not available")
    lap_s = None
    if reference is not None:
        ms = _num(reference.get("lap_time_ms"))
        lap_s = None if ms is None or ms <= 0 else ms / 1000.0
    tables: dict[str, CueApproach] = {}
    zones: list[BrakingZone] = []
    for z in reference_braking_zones(comparison, length):
        app = _approach_table(trace, z.brake_m, length, lap_s)
        if app is not None and not _already_slowing(app):
            tables[z.corner] = app
            zones.append(z)
    # --- coachref ---
    if only_corner is not None:
        zones = [z for z in zones if z.corner == only_corner]
        if not zones:
            lab = (labels or {}).get(only_corner)
            return empty(f"drill: no braking call at {lab.text if lab else only_corner}")
    clamp = comparison.get("brake_clamp_m")
    if not zones and isinstance(clamp, Mapping):
        unclamped = reference_braking_zones({**comparison, "brake_clamp_m": None}, length)
        if unclamped and all(_num(clamp.get(z.corner)) is None for z in unclamped):
            return empty(NO_OWN_POINTS)  # another driver's lap and no braking point of the driver's own
    # --- coachref ---
    if not zones:
        return empty("no measured braking zones on the reference lap")

    by_corner = {z.corner: z for z in zones}
    names = labels or {}

    def label(corner: str) -> CueLabel:
        return names.get(corner) or CueLabel(corner, corner, corner)

    def spoken_names(corners: Sequence[str], fallback_voice: bool) -> dict[str, str | None]:
        """The radio's corner part for each cue, in lap order. Two parts of one turn ("T1" and "T1 (2)") share the
        short spoken name ("Turn 1"): the later one says its full voice form ("Turn 1, second part"), so two
        different braking points never sound the same."""
        out: dict[str, str | None] = {}
        used: set[str] = set()
        for corner in sorted(corners, key=lambda c: by_corner[c].brake_m):
            lab = label(corner)
            said = lab.spoken or (lab.voice if fallback_voice else None)
            if said is not None and said in used and lab.voice not in used:
                said = lab.voice
            out[corner] = said
            if said is not None:
                used.add(said)
        return out

    specs: list[CueSpec] = []
    focus: tuple[str, ...] = ()
    if m == "focus":
        if only_corner is not None:  # --- coachref --- a drill: its corner is the focus, evidence or not
            picked = [(only_corner, "drill")]
        else:
            picked = select_focus_corners(history, by_corner, max_focus, focus_limits)
        focus = tuple(c for c, _ in picked)
        said = spoken_names(focus, fallback_voice=False)
        for corner, why in picked:
            z, lab, name = by_corner[corner], label(corner), said[corner]
            parts, key = ((name, "brake"), 1) if name else (("brake",), 0)
            specs.append(_spec(z, CueKind.BRAKE, f"{lab.text} brake", parts, key, 0.0, True, why))
        if not specs:
            return empty("no braking corrections to focus on")
    elif m == "markers":
        said = spoken_names([z.corner for z in zones], fallback_voice=True)
        for z in zones:
            lab = label(z.corner)
            parts = (said[z.corner] or lab.voice,)
            specs.append(_spec(z, CueKind.MARKER, lab.text, parts, 0, MARKER_LEAD_S, False, "braking zone"))
    else:  # "all"
        for z in zones:
            text = f"{label(z.corner).text} brake"
            specs.append(_spec(z, CueKind.BRAKE, text, ("brake",), 0, 0.0, False, "braking zone"))
    specs.sort(key=lambda sp: sp.target_m)
    return CuePlan(
        mode=m,
        cues=tuple(specs),
        approaches=tuple(tables[sp.corner] for sp in specs),
        targets=tuple(sp.target_m for sp in specs),
        length_m=length,
        ref_lap_id=ref_lap_id,
        ref_lap_number=ref_lap_number,
        focus=focus,
    )


def _spec(
    z: BrakingZone,
    kind: CueKind,
    text: str,
    parts: tuple[str, ...],
    key_index: int,
    anticipation_s: float,
    focus: bool,
    reason: str,
) -> CueSpec:
    return CueSpec(
        corner=z.corner,
        kind=kind,
        target_m=z.brake_m,
        text=text,
        parts=parts,
        key_index=key_index,
        anticipation_s=anticipation_s,
        focus=focus,
        reason=reason,
        ref_speed_kph=z.entry_speed_kph,
    )


def _wrap_hide_m(plan: CuePlan) -> float:
    """How far past a cue's point the dashboard waits before it shows the same cue for the next lap: the approach
    window (at most half a lap, for short tracks)."""
    return min(plan.window_m, 0.5 * plan.length_m)


def _time_to_go(app: CueApproach | None, k: float, v: float) -> tuple[float, float | None]:
    """(seconds to cover the ``k`` metres to the target at speed ``v``, reference speed there or None).

    The earlier of constant speed and the reference lap's own time scaled by ``v_ref / v``: on a straight the car
    is still accelerating, which the reference captures; when the shapes disagree the smaller estimate fires
    earlier, the safe side. O(1): one table lookup."""
    ttg = k / v
    if app is not None:
        idx = int(k + 0.5)
        if 0 <= idx < len(app.ttg_s):
            t_ref, v_ref = app.ttg_s[idx], app.v_mps[idx]
            if t_ref == t_ref and v_ref == v_ref:  # not NaN
                return min(ttg, t_ref * v_ref / v), v_ref
    return ttg, None


def _aim_m(app: CueApproach | None, cue: CueSpec, v: float, margin_m: float, k_now: float) -> float:
    """Where the key word should start (lap distance): ``margin_m`` before the target, plus ``anticipation_s`` of
    *time* for markers. The car keeps accelerating over a 2 s anticipation, so ``anticipation_s * v`` metres would
    misplace it by tens of metres: the point is found on the reference lap's remaining time, scaled by the
    driver's pace relative to the reference where the car is now (``k_now`` metres to go). Binary search over the
    approach table: called once per fired cue, never per frame."""
    if cue.anticipation_s <= 0.0 or app is None:
        return cue.target_m - margin_m - cue.anticipation_s * v
    ttg, v_ref_now = app.ttg_s, app.v_mps
    i_now = int(k_now + 0.5)
    ratio = 1.0
    if 0 <= i_now < len(v_ref_now) and v_ref_now[i_now] == v_ref_now[i_now]:
        ratio = v_ref_now[i_now] / v
    want = cue.anticipation_s + margin_m / v
    lo, hi = 0, min(len(ttg) - 1, max(0, i_now))
    if not (ttg[hi] == ttg[hi] and ttg[hi] * ratio >= want):
        return cue.target_m - margin_m - cue.anticipation_s * v
    while lo < hi:  # remaining time grows with distance to go (NaN entries count as "not far enough")
        mid = (lo + hi) // 2
        t = ttg[mid]
        if t == t and t * ratio >= want:
            hi = mid
        else:
            lo = mid + 1
    return cue.target_m - lo


def cue_timing_error_m(
    event: CueEvent, sample: FrameSample | None, now_mono: float, length_m: float, output_s: float = 0.0
) -> float | None:
    """Where the key word was actually heard relative to where it should have been (m, + = late), measured when
    the device reports playback started at ``now_mono``. ``output_s`` is the audio path after that report (e.g.
    Bluetooth output to an earbud): the device reports when *it* starts playing, the driver hears it later. The
    car's position is the last frame extrapolated at its speed; ``None`` when that frame is stale or from an
    unrelated lap. The report's uplink delay makes this read slightly late (and the measured latency slightly
    long, so cues drift early: safe). An error above ``MARGIN_M`` means the word landed past the reference point.
    """
    if sample is None:
        return None
    age = now_mono - sample.mono
    if not 0.0 <= age <= MAX_SAMPLE_AGE_S:
        return None
    x = sample.d_m + sample.v_mps * age
    if sample.lap == event.lap - 1 and length_m > 0:
        x -= length_m  # audio started before the line, for the next lap's corner
    elif sample.lap != event.lap:
        return None
    return x + sample.v_mps * (max(0.0, output_s) + event.word_offset_s) - event.aim_m


# ============================================================================================== engine
class CueEngine:
    """Plans cues off the hot path and fires them from the ingest thread (see module docstring)."""

    def __init__(
        self,
        mode: str = DEFAULT_CUE_MODE,
        *,
        margin_m: float = MARGIN_M,
        max_focus: int = MAX_FOCUS_CORNERS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not (math.isfinite(margin_m) and 0.0 <= margin_m <= 50.0):
            raise ValueError(f"margin_m must be 0-50 m, got {margin_m}")
        self.margin_m = margin_m
        self.max_focus = max(1, min(MAX_FOCUS_CORNERS, max_focus))
        self._clock = clock
        # planner state (analysis thread / asyncio loop, under _plan_lock; never touched by on_frame)
        self._plan_lock = threading.Lock()
        self._mode: CueMode = parse_cue_mode(mode)
        self._comparison: Mapping[str, Any] | None = None
        self._history: deque[list[Mapping[str, Any]]] = deque(maxlen=FOCUS_HISTORY_LAPS)
        self._history_ref: int | None = None
        # the coach block's habits (coach.habits, via on_lap_result): None = a caller that predates them
        self._focus: tuple[Mapping[str, Any], ...] | None = None
        self._habits: tuple[Mapping[str, Any], ...] | None = None
        self._reference: Mapping[str, Any] | None = None
        self._trace: DistanceTrace | None = None
        # reference lap id -> (summary, trace): LapProcessor caches reference analyses across sessions and only
        # publishes a reference when it first loads it, so a reset session can be compared against a reference
        # whose trace this engine saw in an earlier session. Same lap id = same recorded lap, so reuse is exact.
        self._traces: dict[int, tuple[Mapping[str, Any] | None, DistanceTrace]] = {}
        self._length_m: float | None = None
        self._labels: dict[str, CueLabel] = {}  # learned corner -> track-view name (set_corner_labels)
        self._focus_limits = DEFAULT_FOCUS_LIMITS
        self._driver_known = False  # set_driver seen at least once (the first call only records the driver)
        self._driver_id: int | None = None
        self._empty_reason = NO_REFERENCE  # why there is no comparison (shown while there is none)
        self._generation = 0
        self._plan: CuePlan = CuePlan.empty(self._mode, "cues off" if self._mode == "off" else NO_REFERENCE)
        self._fallback: CuePlan | None = None  # AI-field heads-ups (set_fallback_plan), used only without own cues
        self._drill_corner: str | None = None  # --- coachref --- a practice drill's corner (set_drill_corner)
        # pushed by the radio hub (atomic swaps)
        self._timing = CueTiming()
        self._sink: Callable[[CueEvent], None] | None = None
        self._plan_listener: Callable[[CuePlan], None] | None = None
        self._muted: str | None = None
        # session conditions (ingest thread, from SessionInfo)
        self._safety_car = False
        self._race_laps: int | None = None  # total laps of a race; None = not a race or length unknown
        # ingest-thread state
        self._active: CuePlan | None = None
        self._timing_used: CueTiming | None = None
        self._leads: list[float] = []
        self._offsets: list[float] = []
        self._ptr = 0
        self._lap: int | None = None
        self._lap_shift = 0  # -1 / +1 while lap number and lap distance disagree about the line
        self._done: dict[int, set[str]] = {}
        self._blocked: set[int] = set()
        self._prev_d: float | None = None
        self._prev_t: float | None = None
        self._frame_dt = DEFAULT_FRAME_DT_S
        self._sample: FrameSample | None = None
        self._seq = itertools.count(1)
        self._last_lock = threading.Lock()  # fire (rare) vs outcome updates; never taken per frame
        self._last: dict[str, Any] | None = None
        self.fired = 0
        self.missed = 0
        self.suppressed = 0
        self.dropped = 0
        self.errors = 0

    # ------------------------------------------------------------------ configuration (any thread)
    @property
    def mode(self) -> CueMode:
        return self._mode

    @property
    def plan(self) -> CuePlan:
        return self._plan

    @property
    def timing(self) -> CueTiming:
        return self._timing

    def set_mode(self, mode: str) -> CueMode:
        """Change the cue mode and replan from the last inputs. Raises ``ValueError`` for an unknown mode."""
        m = parse_cue_mode(mode)
        with self._plan_lock:
            self._mode = m
        self._replan()
        return m

    def set_sink(self, sink: Callable[[CueEvent], None] | None) -> None:
        """Where fired cues go (called on the ingest thread; must not block). ``None`` disarms firing."""
        self._sink = sink

    def set_plan_listener(self, listener: Callable[[CuePlan], None] | None) -> None:
        """Called with every newly installed plan (from the installing thread), e.g. to pre-synthesise audio."""
        self._plan_listener = listener

    def set_timing(self, timing: CueTiming) -> None:
        if not (math.isfinite(timing.latency_s) and 0.0 <= timing.latency_s <= MAX_LATENCY_S):
            raise ValueError(f"latency_s must be 0-{MAX_LATENCY_S} s, got {timing.latency_s}")
        self._timing = timing

    def set_muted(self, reason: str | None) -> None:
        """Hold every cue (quiet mode, no radio...): due cues are resolved as suppressed, never said late."""
        self._muted = reason or None

    @property
    def focus_limits(self) -> FocusLimits:
        return self._focus_limits

    def on_session_info(
        self, safety_car_status: str | None, total_laps: int | None = None, session_type: str | None = None
    ) -> None:
        """SessionInfo hook (ingest thread): SC, VSC and formation laps have no racing braking points, and a race
        of ``total_laps`` ends at its flag. Unknown is not assumed: an unknown session type or race length keeps
        every lap open."""
        self._safety_car = safety_car_status is not None and safety_car_status not in _NO_SAFETY_CAR
        race = session_type == "race" and isinstance(total_laps, int) and not isinstance(total_laps, bool)
        self._race_laps = total_laps if race and total_laps is not None and total_laps > 0 else None

    def set_focus_limits(self, limits: FocusLimits | None) -> None:
        """Focus-corner filter of the seated driver's coaching profile (``None`` = the engine's defaults); replans."""
        with self._plan_lock:
            self._focus_limits = limits if limits is not None else DEFAULT_FOCUS_LIMITS
        self._replan()

    def set_driver(self, driver_id: int | None, profile: CoachingProfile | None = None) -> None:
        """The driver in the seat (driver-registry listener, any thread) and their coaching profile.

        A *different* driver than the last call drops the comparison, focus history and plan: they describe the
        previous driver's reference, and until the analysis publishes this driver's first lap there is nothing of
        theirs to call. The first call only records the driver (the engine cannot know who drove before it).
        Reference traces stay cached by lap id: a later comparison names its reference lap exactly, whoever
        owns it. Profile edits of the same driver only update the focus limits."""
        limits = FocusLimits.from_profile(profile) if profile is not None else DEFAULT_FOCUS_LIMITS
        cleared: CuePlan | None = None
        with self._plan_lock:
            changed = self._driver_known and driver_id != self._driver_id
            self._driver_known = True
            self._driver_id = driver_id
            self._focus_limits = limits
            if changed:
                self._clear_reference_locked(NEW_DRIVER)
                cleared = self._plan
        if cleared is not None:
            self._announce(cleared)
        else:
            self._replan()

    # ------------------------------------------------------------------ planning inputs (analysis thread)
    def on_reference(self, summary: Mapping[str, Any] | None, trace: DistanceTrace | None) -> None:
        """The reference lap the analysis compares against (``LiveState.set_reference``).

        ``None`` is an explicit clear (``LapProcessor``: the session's owner has no reference lap, e.g. after the
        session was re-assigned to another driver): the comparison and focus history go with it, so the previous
        reference's plan cannot be rebuilt, and a later lap without a comparison keeps the empty plan. A
        reference for a different lap than the stored comparison's makes that comparison stale too; the
        analysis publishes the comparison against the new reference right after."""
        if summary is None or trace is None:
            with self._plan_lock:
                self._clear_reference_locked(NO_DRIVER_REFERENCE)
                installed = self._plan
            self._announce(installed)
            return
        with self._plan_lock:
            self._reference = summary
            self._trace = trace
            lap_id = summary.get("lap_id")
            if isinstance(lap_id, int) and not isinstance(lap_id, bool):
                self._traces[lap_id] = (summary, trace)
                while len(self._traces) > TRACE_CACHE:
                    del self._traces[next(iter(self._traces))]
                comp = self._comparison
                if comp is not None and comp.get("ref_lap_id") != lap_id:
                    self._comparison = None  # measured against another lap: its braking points are not this one's
                    self._empty_reason = NO_REFERENCE
        self._replan()

    def _clear_reference_locked(self, reason: str) -> None:
        """Drop everything that belongs to the current reference and install an empty plan (``_plan_lock`` held).
        The generation bump stops a replan already in flight from installing the old reference's plan."""
        self._generation += 1
        self._reference = None
        self._trace = None
        self._comparison = None
        self._history.clear()
        self._history_ref = None
        self._focus = None
        self._habits = None
        self._empty_reason = reason
        self._plan = self._with_fallback(CuePlan.empty(self._mode, "cues off" if self._mode == "off" else reason))

    def set_track_length(self, length_m: float | None) -> None:
        with self._plan_lock:
            self._length_m = _num(length_m)

    def set_corner_labels(self, labels: Mapping[str, CueLabel] | None) -> None:
        """How the track view names the learned corners (``cue_labels`` of the live track model). Replans only
        when the names changed (the analysis republishes the model every lap). Cheap when there is no comparison
        yet, which is the case when the session manager re-installs the model on the ingest thread."""
        new = dict(labels or {})
        with self._plan_lock:
            if new == self._labels:
                return
            self._labels = new
        self._replan()

    def on_lap_result(
        self,
        observations: Sequence[Mapping[str, Any]],
        comparison: Mapping[str, Any] | None,
        length_m: float | None = None,
        *,
        focus: Sequence[Mapping[str, Any]] | None = None,
        habits: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """A processed lap (``LiveState.on_lap_result``). A lap without a comparison (incomplete, no reference)
        keeps the current plan, which after a cleared reference is the empty one. Never raises into the analysis
        thread. ``focus`` / ``habits``: the lap's coach block lists (``coach.selection`` contract: the habits being
        worked on with their corner reminder, and every habit of the session), kept for the planner with the
        comparison; None = a caller that predates habits."""
        with self._plan_lock:
            if length_m is not None:
                self._length_m = _num(length_m)
            if comparison is None:
                return
            self._focus = None if focus is None else tuple(focus)
            self._habits = None if habits is None else tuple(habits)
            ref_id = comparison.get("ref_lap_id")
            ref_key = ref_id if isinstance(ref_id, int) and not isinstance(ref_id, bool) else None
            if ref_key != self._history_ref:
                self._history.clear()  # observations against another reference are not comparable
                self._history_ref = ref_key
            self._history.append(list(observations))
            self._comparison = comparison
        self._replan()

    def set_fallback_plan(self, plan: CuePlan | None) -> None:
        """Heads-ups from the AI field (``core.track_knowledge.heads_up_cue_plan``: "heavy braking ahead" MARKER
        cues placed early before the field's onsets). They stand in only while the engine has nothing of the
        driver's own to call (``FALLBACK_REASONS``: no reference lap yet, none for this driver, a new driver) and
        never in mode "off": a plan from the driver's reference always wins (track knowledge layer L3 > L0b). In
        "focus" mode only the heaviest ``FocusLimits.max_corners`` of them are kept, so the coaching profile caps
        them like focus corners (a beginner gets one per lap). Fired by the same rules as every cue (one per corner
        per lap, no pit / out laps, standing starts or safety car)."""
        with self._plan_lock:
            self._fallback = plan
        self._replan()

    # --- coachref ---
    @property
    def drill_corner(self) -> str | None:
        return self._drill_corner

    def set_drill_corner(self, corner: str | None) -> None:
        """A practice drill (``core.coachref``): plan only ``corner`` (``None`` ends it) and replan. Kept across
        ``reset_session`` (a drill may continue in the next session); the field's heads-ups stay off meanwhile."""
        with self._plan_lock:
            if corner == self._drill_corner:
                return
            self._drill_corner = corner
        self._replan()

    # --- coachref ---

    def _with_fallback(self, plan: CuePlan) -> CuePlan:
        """``plan``, or the field heads-ups when ``plan`` is empty for lack of the driver's own reference
        (``_plan_lock`` held). ``CuePlan.focus`` of a heads-up plan is its priority order (largest speed drop)."""
        fb = self._fallback
        if self._drill_corner is not None:  # --- coachref --- a drill: only its corner, never the field's
            return plan
        if fb is None or plan.cues or plan.mode == "off" or plan.reason not in FALLBACK_REASONS:
            return plan
        reason = f"AI field heads-ups ({plan.reason})"
        if plan.mode != "focus":
            return replace(fb, mode=plan.mode, focus=(), reason=reason)
        keep = set(fb.focus[: self._focus_limits.max_corners])
        idx = [i for i, c in enumerate(fb.cues) if c.corner in keep]
        return replace(
            fb,
            mode=plan.mode,
            cues=tuple(fb.cues[i] for i in idx),
            approaches=tuple(fb.approaches[i] for i in idx),
            targets=tuple(fb.targets[i] for i in idx),
            focus=tuple(k for k in fb.focus if k in keep),
            reason=reason,
        )

    def set_plan(self, plan: CuePlan | None) -> None:
        """Install a plan built elsewhere (``None`` = no cues). It stands until the next replan trigger (a lap
        result, a new reference or a mode change rebuilds from the engine's own inputs)."""
        with self._plan_lock:
            self._generation += 1  # a replan already in flight must not overwrite this plan
            self._plan = plan if plan is not None else CuePlan.empty(self._mode, NO_REFERENCE)
            installed = self._plan
        self._announce(installed)

    def reset_session(self) -> None:
        """New session: the reference, history, plan and per-lap state belong to the old one. Mode, timing,
        sink, mute, the seated driver and their focus limits stay (radio and profile settings). Called on the
        ingest thread (``LiveState.reset_session`` from the session manager), which owns the per-lap state it
        clears; the planner lock is only held for the swap."""
        with self._plan_lock:
            self._fallback = None  # the old session's field: the track knowledge resolver republishes for the new one
            self._clear_reference_locked(NO_REFERENCE)  # also stops a replan of the old session still in flight
            self._length_m = None
            self._labels = {}  # the next session may be another track: its model brings its own names
            installed = self._plan
        self._safety_car = False
        self._race_laps = None
        # the ingest thread re-seeks on the plan swap; laps restart at 1, so old tokens must not block them
        self._done = {}
        self._blocked = set()
        self._lap = None
        self._prev_d = None
        self._prev_t = None
        with self._last_lock:
            self._last = None
        self._announce(installed)

    def _replan(self) -> None:
        """Rebuild from the stored inputs and install the result.

        The lock only guards the input snapshot and the swap; the build (approach tables, ~1 ms) runs outside it,
        so ``reset_session`` (called on the ingest thread) never waits behind a build. A newer replan or reset
        supersedes an older build still in flight (generation check). Planning errors are logged and keep the
        previous plan: they must never reach the analysis thread or the radio.

        The comparison names its reference lap (``ref_lap_id``); when the published reference is another lap (a
        reset session compared against a reference the analysis had cached), that lap's trace comes from the
        by-id cache. It is exact - the same recorded lap - and only ever used with a comparison received after
        the last clear, because every clear drops the comparison it would otherwise be paired with.
        """
        with self._plan_lock:
            self._generation += 1
            gen = self._generation
            mode, comparison, length = self._mode, self._comparison, self._length_m
            history, reference, trace = list(self._history), self._reference, self._trace
            limits, empty_reason, labels = self._focus_limits, self._empty_reason, self._labels
            drill_corner = self._drill_corner  # --- coachref ---
            ref_id = comparison.get("ref_lap_id") if comparison is not None else None
            if isinstance(ref_id, int) and (reference is None or reference.get("lap_id") != ref_id):
                reference, trace = self._traces.get(ref_id, (None, None))
        try:
            if comparison is None and mode != "off":
                plan = CuePlan.empty(mode, empty_reason)
            else:
                plan = build_cue_plan(
                    mode,
                    comparison,
                    length_m=length,
                    history=history,
                    reference=reference,
                    trace=trace,
                    max_focus=self.max_focus,
                    focus_limits=limits,
                    labels=labels,
                    only_corner=drill_corner,  # --- coachref ---
                )
        except Exception:
            self.errors += 1
            log.exception("cue planning failed; keeping the previous plan")
            return
        with self._plan_lock:
            if gen != self._generation:
                return
            plan = self._with_fallback(plan)
            self._plan = plan
        self._announce(plan)

    def _announce(self, plan: CuePlan) -> None:
        listener = self._plan_listener
        if listener is not None:
            try:
                listener(plan)
            except Exception:
                log.exception("cue plan listener failed")

    # ------------------------------------------------------------------ ingest thread
    def on_frame(self, f: CarFrame, now_mono: float | None = None) -> CueEvent | None:
        """Per-frame trigger (ingest thread). Returns the cue fired on this frame, if any. Never raises."""
        try:
            return self._on_frame(f, self._clock() if now_mono is None else now_mono)
        except Exception:
            self.errors += 1
            if self.errors <= 3 or self.errors % 1000 == 0:
                log.exception("cue engine frame hook failed (%d errors)", self.errors)
            return None

    def _on_frame(self, f: CarFrame, now: float) -> CueEvent | None:
        lap, d, kph = f.lap_number, f.lap_distance_m, f.speed_kph
        if lap is None or d is None or kph is None or not (math.isfinite(d) and math.isfinite(kph)):
            return None
        v = kph / 3.6
        plan = self._plan
        if plan is not self._active:
            self._activate(plan, d)
        elif self._timing is not self._timing_used:
            self._apply_timing()

        rewound = False
        t = f.session_time_s
        if t is not None:
            if self._prev_t is not None:
                dt = t - self._prev_t
                if 0.0 < dt <= MAX_FRAME_DT_S:
                    self._frame_dt += FRAME_DT_SMOOTHING * (dt - self._frame_dt)
                elif dt < 0.0:
                    rewound = True  # flashback: the game clock went backwards
            self._prev_t = t
        prev_d = self._prev_d
        self._prev_d = d
        length = plan.length_m
        if lap != self._lap:
            self._enter_lap(lap, d, length, f)
        elif prev_d is not None:
            if length > 0.0 and prev_d - d > 0.5 * length:
                self._lap_shift = min(1, self._lap_shift + 1)  # crossed the line before the lap number moved
                self._seek(d)
            elif rewound or d < prev_d - REWIND_M:
                self._seek(d)
        token = lap + self._lap_shift
        self._sample = FrameSample(now, token, d, v)

        if f.quality & _NOT_DRIVING:
            return None
        if f.pit_status:
            self._blocked.add(token)  # in/out lap: no racing braking points for the rest of this lap
            return None
        race_laps = self._race_laps
        if race_laps is not None and token > race_laps:
            return None  # past the flag (the distance wraps a frame before the game marks the car finished)
        if not plan.cues or kph < MIN_CUE_SPEED_KPH:
            return None
        # a blocked lap (standing start, out lap) still ends in a flying approach to the next lap's first corner
        return self._evaluate(plan, token, d, v, now, t, token not in self._blocked)

    def _activate(self, plan: CuePlan, d: float) -> None:
        self._active = plan
        self._apply_timing()
        self._seek(d)

    def _apply_timing(self) -> None:
        timing = self._timing
        plan = self._active
        cues = plan.cues if plan is not None else ()
        self._offsets = [timing.word_offset(c) for c in cues]
        self._leads = [timing.latency_s + off + c.anticipation_s for c, off in zip(cues, self._offsets, strict=True)]
        self._timing_used = timing

    def _seek(self, d: float) -> None:
        plan = self._active
        self._ptr = bisect.bisect_left(plan.targets, d) if plan is not None else 0

    def _enter_lap(self, lap: int, d: float, length: float, f: CarFrame) -> None:
        prev_lap = self._lap
        self._lap = lap
        # lap number moved before the distance reset: still before the line until the distance wraps
        late_wrap = prev_lap is not None and lap == prev_lap + 1 and length > 0.0 and d > 0.5 * length
        self._lap_shift = -1 if late_wrap else 0
        for k in [k for k in self._done if k < lap - 2 or k > lap + 2]:
            del self._done[k]
        self._blocked = {k for k in self._blocked if lap - 2 <= k <= lap + 2}
        if lap == 1 and d > STANDING_START_M and (f.current_lap_time_ms or 0) < 1000:
            self._blocked.add(1)  # race start from the grid: cold tyres, traffic, not a flying lap
        self._seek(d)

    def _evaluate(
        self, plan: CuePlan, token: int, d: float, v: float, now: float, t: float | None, this_lap: bool
    ) -> CueEvent | None:
        """Fire at most one due cue: this lap's (unless ``this_lap`` is False: a blocked lap), else a call for the
        next lap's first corners that is due before the line."""
        cues = plan.cues
        n = len(cues)
        if this_lap:
            done = self._done.get(token)
            if done is None:
                done = self._done[token] = set()
            i = self._ptr
            while i < n and (cues[i].corner in done or d > cues[i].target_m):
                if cues[i].corner not in done:
                    done.add(cues[i].corner)
                    self.missed += 1  # passed without a call (distance jump, too slow, joined late...)
                i += 1
            self._ptr = i
            for j in range(i, min(n, i + LOOKAHEAD)):
                c = cues[j]
                k = c.target_m - d
                if k > plan.window_m:
                    break
                if c.corner in done:
                    continue
                ev = self._check(plan, j, k, v, token, token, d, now, t, done)
                if ev is not None:
                    return ev
        # the next lap's first braking zones can need their call before the line - unless this is a race's
        # final lap: the next lap is never driven
        rem = plan.length_m - d
        race_laps = self._race_laps
        nxt = token + 1
        if rem < plan.window_m and (race_laps is None or token < race_laps) and nxt not in self._blocked:
            done_next = self._done.get(nxt)
            if done_next is None:
                done_next = self._done[nxt] = set()
            for j in range(min(n, LOOKAHEAD)):
                c = cues[j]
                k = c.target_m + rem
                if k > plan.window_m:
                    break
                if k < 0.0 or c.corner in done_next:
                    continue
                ev = self._check(plan, j, k, v, nxt, token, d, now, t, done_next)
                if ev is not None:
                    return ev
        return None

    def _check(
        self,
        plan: CuePlan,
        j: int,
        k: float,
        v: float,
        lap: int,
        fired_lap: int,
        d: float,
        now: float,
        t: float | None,
        done: set[str],
    ) -> CueEvent | None:
        c = plan.cues[j]
        app = plan.approaches[j]
        ttg, v_ref = _time_to_go(app, k, v)
        lead = self._leads[j]
        slack = lead + self.margin_m / v + 0.5 * self._frame_dt
        if ttg > slack:
            return None  # not yet
        done.add(c.corner)  # decided: one call per corner per lap, whatever happens next
        if ttg < lead:
            # The key word would land after the reference point (markers: less than their anticipation before
            # it): a distance jump, lost frames or a plan that arrived mid-approach. The margin may absorb a late
            # frame, the point itself never is: silence beats late. A regular approach keeps
            # ttg >= lead + margin/v - frame/2, so only frame spacings above 2 * margin / v (< 10 Hz at
            # 300 km/h) drop on-time calls.
            self.missed += 1
            return None
        if c.kind is CueKind.BRAKE:
            if v_ref is None and c.ref_speed_kph is not None:
                v_ref = c.ref_speed_kph / 3.6
            if v_ref is not None and v > v_ref * (1.0 + OVERSPEED_TOLERANCE):
                self.suppressed += 1  # faster than the reference here: its braking point would be too late
                return None
        sink = self._sink
        if sink is None or self._muted is not None or self._safety_car:
            self.suppressed += 1
            return None
        off = self._offsets[j]
        ev = CueEvent(
            seq=next(self._seq),
            cue=c,
            lap=lap,
            fired_lap=fired_lap,
            fired_mono=now,
            session_time_s=t,
            d_m=d,
            v_mps=v,
            ttg_s=ttg,
            latency_s=self._timing_used.latency_s if self._timing_used is not None else DEFAULT_LATENCY_S,
            word_offset_s=off,
            path=self._timing_used.path if self._timing_used is not None else "pcm",
            aim_m=_aim_m(app, c, v, self.margin_m, k),
            ref_lap_id=plan.ref_lap_id,
        )
        self.fired += 1
        last = {**ev.to_dict(), "status": "pending", "reason": None, "error_m": None, "latency_measured_ms": None}
        with self._last_lock:
            self._last = {**last, "mono": now}
        try:
            sink(ev)
        except Exception:
            self.errors += 1
            log.exception("cue sink failed")
        return ev

    # ------------------------------------------------------------------ outcomes (radio hub, asyncio loop)
    def record_outcome(self, seq: int, status: str, reason: str | None = None) -> None:
        """What the radio did with cue ``seq``: ``sent`` (``reason`` = a note, e.g. text only) or ``dropped``."""
        with self._last_lock:
            if status == "dropped":
                self.dropped += 1
            last = self._last
            if last is not None and last.get("seq") == seq:
                self._last = {**last, "status": status, "reason": reason}

    def record_timing(self, seq: int, *, error_m: float | None, latency_s: float | None) -> None:
        """Measured delivery of cue ``seq``: where its key word was heard vs intended (m, + = late) and the
        fire -> audible latency."""
        with self._last_lock:
            last = self._last
            if last is None or last.get("seq") != seq:
                return
            self._last = {
                **last,
                "error_m": None if error_m is None else round(error_m, 1),
                "latency_measured_ms": None if latency_s is None else round(latency_s * 1000),
            }

    # ------------------------------------------------------------------ readers (any thread)
    def sample(self) -> FrameSample | None:
        return self._sample

    def _next_cue(self, *, for_display: bool = False) -> tuple[CueSpec, float, int] | None:
        """(cue, metres to its target, plan index) for the next unresolved cue ahead of the car (mirrors
        ``_evaluate``: a blocked lap has none of its own, the final race lap no next lap).

        ``for_display`` (the dashboard's "next call"): a next-lap cue whose target the car has only just passed on
        this lap - or not even reached yet, once its call is done - is left out. Its distance would wrap to almost
        a lap length ("T3 brake in 4311 m" while the car is in T3), which reads as the corner the car is in. It
        shows again once the car is ``_wrap_hide_m`` past that point. The speak window
        (``seconds_to_next_cue``) keeps the full lookahead: it times audio, it is not read by the driver."""
        plan, s, race_laps = self._active, self._sample, self._race_laps
        if plan is None or s is None or not plan.cues:
            return None
        if race_laps is not None and s.lap > race_laps:
            return None
        cues = plan.cues
        if s.lap not in self._blocked:
            done = self._done.get(s.lap, set())
            for j in range(min(self._ptr, len(cues)), len(cues)):
                if cues[j].corner not in done and cues[j].target_m >= s.d_m:
                    return cues[j], cues[j].target_m - s.d_m, j
        if (race_laps is not None and s.lap >= race_laps) or s.lap + 1 in self._blocked:
            return None  # final lap: no next lap
        done_next = self._done.get(s.lap + 1, set())
        for j, c in enumerate(cues):
            if c.corner not in done_next:
                if for_display and s.d_m - c.target_m < _wrap_hide_m(plan):
                    return None  # the nearest next-lap cue is this lap's point just behind the car (or done ahead)
                return c, c.target_m + plan.length_m - s.d_m, j
        return None

    def seconds_to_next_cue(self) -> float | None:
        """Seconds until the next cue is due to fire at the current speed (0 = due now), for the radio's speak
        window: a proactive message must not be cut off by (or talk over) a cue. ``None`` = no cue coming."""
        if self._mode == "off" or self._muted is not None or self._safety_car or self._sink is None:
            return None
        nxt, s = self._next_cue(), self._sample
        if nxt is None or s is None or s.v_mps <= 1.0:
            return None
        _cue, k, j = nxt
        lead = self._leads[j] if j < len(self._leads) else DEFAULT_LATENCY_S
        return max(0.0, k / s.v_mps - lead - self.margin_m / s.v_mps)

    def snapshot(self) -> dict[str, Any]:
        """Small JSON-able state for the dashboard (next cue, last cue, timing)."""
        plan = self._plan
        nxt = self._next_cue(for_display=True) if plan is self._active else None
        with self._last_lock:
            last = dict(self._last) if self._last is not None else None
        if last is not None:
            mono = last.pop("mono", None)
            last["age_s"] = None if mono is None else round(max(0.0, self._clock() - mono), 1)
        timing = self._timing
        muted = self._muted or ("safety car" if self._safety_car else None)
        if self._sink is None:
            muted = muted or "radio off"
        return {
            "mode": self._mode,
            "armed": self._sink is not None,
            "muted": muted,
            "reason": plan.reason,
            "ref_lap_number": plan.ref_lap_number,
            "focus": list(plan.focus),
            "focus_limits": self._focus_limits.to_dict(),
            "drill_corner": self._drill_corner,  # --- coachref ---
            "cues": [c.to_dict() for c in plan.cues],
            "next": None
            if nxt is None
            else {"corner": nxt[0].corner, "text": nxt[0].text, "kind": nxt[0].kind.value, "in_m": round(nxt[1])},
            "last": last,
            "timing": {"latency_ms": round(timing.latency_s * 1000), "path": timing.path, "margin_m": self.margin_m},
            "stats": {
                "fired": self.fired,
                "missed": self.missed,
                "suppressed": self.suppressed,
                "dropped": self.dropped,
                "errors": self.errors,
            },
        }
