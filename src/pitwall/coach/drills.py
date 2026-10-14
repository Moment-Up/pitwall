"""Practice drills (coachref): one corner, a few laps, one measurable target. Pure: no I/O, no threads, no LLM.

A drill picks a corner and a skill (``DrillKind``) and measures every following lap at that corner against a target
fixed when the drill starts (``plan_target``). Each lap is one attempt (``evaluate_attempt``): a hit, a miss or not
measured, with a sentence that says what happened relative to the target. At the end ``summarise`` gives the hits,
the best attempt and a trend. The service that runs drills (``core.coachref``) stores them and feeds the attempt
into the lap's coaching block (``with_drill``: one coaching point a lap, ``kind: "drill"``), so the radio says
exactly what the coach card shows (D6).

Evidence and safety (CLAUDE.md):

* Targets are measured values only: the reference lap's braking onset (``CornerMetrics.brake_start_m``), the
  driver's own recent laps (median) or own best lap. Nothing is modelled. Missing data makes a kind unavailable with
  a reason; it is never filled in.
* Coaching never recommends braking later on its own. A brake-point target against another driver's lap is the
  earlier of their point and the driver's own braking point (``clamp_m``, the braking clamp of ``core.coachref``);
  a corner where the driver has no point of their own offers no brake-point drill. Speed targets step up from the
  driver's usual speed and never above the best speed demonstrated at the corner (``cap``); entry-speed drills are
  anchored on the driver's own laps only (arriving at another driver's speed would mean braking later).
* No text contains an instruction ("brake later" or any other): every sentence describes the attempt relative to the
  target ("3 m before the point", "minimum 84 km/h, 2 km/h short").
* A brake-point attempt past the target is a hit only when the corner got faster (``corner_time_delta_s`` < 0
  against the reference): braking later than the point is praised only when it paid off. Within the tolerance before
  the point is a hit; within half a metre either side is "on the point" (below the measurement's resolution).
* Laps that say nothing about the driver's habit at the corner are no attempts (``NON_ATTEMPT_FLAGS``: not driven
  to the line, pit laps, rewound, the grid start, a distance jump, stale data) and neither are safety-car laps (the
  service checks the live session).

Heuristics (named constants below, flagged in docs/features.md): the brake-point tolerance (5 m, at least twice the
reference lap's 90th-percentile sample spacing - the rule of ``analysis.coaching._mag_conf``), the speed step
(3 km/h), the entry tolerance (5 km/h), the exit guard (``analysis.coaching.EXIT_SPEED_KPH``), the trend thresholds
and the 30-minute timeout. They come from the owner's recorded F1 25 laps (design spec section 2.3), not from live
validation.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from pitwall.analysis.coaching import EXIT_SPEED_KPH, SHORT_MAX_CHARS, is_incident
from pitwall.analysis.compare import CornerDelta, CornerMetrics
from pitwall.analysis.laps import LapFlag

__all__ = [
    "DRILL_KINDS",
    "DrillAttempt",
    "DrillInputs",
    "DrillKind",
    "DrillSpec",
    "DrillState",
    "DrillSummary",
    "DrillTarget",
    "Unavailable",
    "drill_point",
    "drill_view",
    "evaluate_attempt",
    "is_attempt_lap",
    "kind_for_observation",
    "plan_target",
    "result_texts",
    "state_fields",
    "state_from_row",
    "status_text",
    "stop_text",
    "summarise",
    "with_drill",
]

DrillKind = Literal["brake_point", "min_speed", "exit_speed", "entry_speed"]
DRILL_KINDS: tuple[DrillKind, ...] = ("brake_point", "min_speed", "exit_speed", "entry_speed")
SKILL_LABELS: dict[str, str] = {
    "brake_point": "Brake point",
    "min_speed": "Minimum speed",
    "exit_speed": "Exit speed",
    "entry_speed": "Entry speed",
}
UNITS: dict[str, str] = {"brake_point": "m", "min_speed": "km/h", "exit_speed": "km/h", "entry_speed": "km/h"}
METRICS: dict[str, str] = {
    "brake_point": "brake_start_m",
    "min_speed": "min_speed_kph",
    "exit_speed": "exit_speed_kph",
    "entry_speed": "entry_speed_kph",
}
# Work on point (observation kind) -> the drill that measures it. exit_gain and incident start no drill.
OBSERVATION_DRILLS: dict[str, DrillKind] = {
    "brake_early": "brake_point",
    "brake_late_overdrive": "brake_point",
    "low_min_speed": "min_speed",
    "overspeed_apex": "exit_speed",
    "late_throttle": "exit_speed",
    "coasting": "exit_speed",
}

# ---------------------------------------------------------------------------------------------- heuristics
DEFAULT_LAPS = 5
LAPS_CHOICES = (3, 5, 8, 10)
MIN_LAPS, MAX_LAPS = 3, 10
BRAKE_TOLERANCE_M = 5.0  # never below 2x the reference lap's p90 sample spacing (BRAKE_SPACING_FACTOR)
BRAKE_SPACING_FACTOR = 2.0
SPEED_STEP_KPH = 3.0
ENTRY_TOLERANCE_KPH = 5.0
EXIT_GUARD_KPH = EXIT_SPEED_KPH  # a minimum-speed hit must not cost more exit speed than the analysis notices
BASELINE_LAPS = 5
MIN_BASELINE_LAPS = 2
TREND_MIN_ATTEMPTS = 4
SPEED_TREND_KPH = 1.0
DRILL_TIMEOUT_S = 1800.0
MOVING_KPH = 30.0  # the reference choice lock (core.coachref): at or above this the car is moving
DRILL_PRIORITY = 1e6  # a drill point outranks every analysis point in the coach block
# allowed ranges (API validation) and the dashboard's choices, per kind
TOLERANCE_RANGES: dict[str, tuple[float, float]] = {
    "brake_point": (3.0, 15.0),
    "min_speed": (1.0, 10.0),
    "exit_speed": (1.0, 10.0),
    "entry_speed": (2.0, 10.0),
}
TOLERANCE_CHOICES: dict[str, tuple[float, ...]] = {
    "brake_point": (3.0, 5.0, 10.0),
    "min_speed": (2.0, 3.0, 5.0),
    "exit_speed": (2.0, 3.0, 5.0),
    "entry_speed": (3.0, 5.0, 8.0),
}
DEFAULT_TOLERANCE: dict[str, float] = {
    "brake_point": BRAKE_TOLERANCE_M,
    "min_speed": SPEED_STEP_KPH,
    "exit_speed": SPEED_STEP_KPH,
    "entry_speed": ENTRY_TOLERANCE_KPH,
}
# laps that are no attempt: not driven to the line, pit laps, rewound, the grid start (race lap 1), a reset to the
# track (distance jump), stale data (track-limit laps do count). core.lap_processor keeps the same laps out of the
# drill baselines.
NON_ATTEMPT_FLAGS = frozenset(
    {
        LapFlag.INCOMPLETE,
        LapFlag.PIT_IN,
        LapFlag.PIT_OUT,
        LapFlag.FLASHBACK,
        LapFlag.STANDING_START,
        LapFlag.RACE_START,
        LapFlag.DISTANCE_JUMP,
        LapFlag.STALE_DATA,
    }
)
ON_POINT_M = 0.5  # |delta| below this is "on the point" (it rounds to 0 m): under the sample spacing
STOP_REASONS = ("driver", "driver_changed", "context_changed", "model_changed", "timed_out", "service_restart")
_TREND_SENTENCES = {
    "closer": "Closer each lap.",
    "steady": "Steady.",
    "further": "Drifting off the point.",
    "rising": "Speed rising.",
    "falling": "Speed dropping.",
}
ASSIST_NOTE = "Braking assist is on, so the game helps with braking: these brake points are partly the assist's."


def kind_for_observation(kind: object) -> DrillKind | None:
    """The drill that measures a Work on point's observation kind (None: no drill for it)."""
    return OBSERVATION_DRILLS.get(kind) if isinstance(kind, str) else None


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def _cut(text: str) -> str:
    """At most ``SHORT_MAX_CHARS``: the first clause of an over-long phrase, then a hard cut."""
    return text if len(text) <= SHORT_MAX_CHARS else text[:SHORT_MAX_CHARS]


# ============================================================================================== targets
@dataclass(frozen=True, slots=True)
class Unavailable:
    """Why a drill kind cannot run at a corner (a plain sentence for the screen and the radio)."""

    reason: str


@dataclass(frozen=True, slots=True)
class DrillTarget:
    kind: DrillKind
    target: float
    tolerance: float  # m (brake point) or km/h (entry); the speed step for speed drills
    unit: str
    baseline: float | None
    target_text: str
    note: str | None
    target_source: str  # own_reference | other_reference | own_point | own_laps | own_best
    cap: float | None = None
    exit_guard: float | None = None


@dataclass(frozen=True, slots=True)
class DrillInputs:
    """What ``plan_target`` needs about one corner (all measured; None = unknown)."""

    corner_label: str  # official short label ("T3"), else the learned name
    ref: CornerMetrics | None = None  # the live reference lap at the corner
    ref_zone: bool = False  # the reference has a braking zone there by the cue engine's criteria
    ref_other: bool = False  # the reference is another driver's lap
    ref_name: str | None = None
    clamp_m: float | None = None  # the driver's own braking point there (only used with another driver's lap)
    spacing_p90_m: float | None = None  # the reference lap's 90th-percentile sample spacing
    own_best: CornerMetrics | None = None  # the driver's own best (reference) lap at the corner
    recent: tuple[CornerMetrics, ...] = ()  # this session's recent laps there, oldest first, incidents excluded
    tolerance: float | None = None  # requested; None = the kind's default
    braking_assist: int | None = None  # F1 braking assist level of the live session
    shares_with: str | None = None  # another corner's label with the same reference braking onset
    own_whose: str = "your best lap's"  # the driver's own reference in a sentence ("your pinned lap's")


def _recent_values(inputs: DrillInputs, attr: str) -> list[float]:
    vals = [v for m in inputs.recent if (v := _num(getattr(m, attr))) is not None]
    return vals[-BASELINE_LAPS:]


def _baseline(inputs: DrillInputs, attr: str) -> tuple[float | None, str]:
    """Median over the recent laps (>= ``MIN_BASELINE_LAPS``), else the own best lap's value."""
    vals = _recent_values(inputs, attr)
    if len(vals) >= MIN_BASELINE_LAPS:
        return float(statistics.median(vals)), "own_laps"
    own = _num(getattr(inputs.own_best, attr)) if inputs.own_best is not None else None
    return own, "own_best"


def plan_target(kind: DrillKind, inputs: DrillInputs) -> DrillTarget | Unavailable:
    """The target of a ``kind`` drill at one corner, fixed for the whole drill (spec 3.4.2a)."""
    label = inputs.corner_label
    if kind == "brake_point":
        ref = inputs.ref
        ref_m = _num(ref.brake_start_m) if ref is not None else None
        if ref_m is None or not inputs.ref_zone:
            return Unavailable(f"The reference has no braking point at {label}.")
        if inputs.ref_other:
            own = _num(inputs.clamp_m)
            if own is None:
                return Unavailable(f"No braking point of your own at {label} yet.")
            target = min(ref_m, own)
            source = "other_reference" if ref_m <= own else "own_point"
        else:
            target, source = ref_m, "own_reference"
        tol = inputs.tolerance if inputs.tolerance is not None else BRAKE_TOLERANCE_M
        spacing = _num(inputs.spacing_p90_m)
        if spacing is not None and spacing > 0:
            tol = max(tol, float(math.ceil(BRAKE_SPACING_FACTOR * spacing)))
        whose = {"own_reference": inputs.own_whose, "own_point": "your own"}.get(
            source, f"{inputs.ref_name}'s" if inputs.ref_name else "the reference's"
        )
        notes = []
        if inputs.braking_assist is not None and inputs.braking_assist >= 1:
            notes.append(ASSIST_NOTE)
        if inputs.shares_with:
            notes.append(f"{label} shares its braking point with {inputs.shares_with}.")
        return DrillTarget(
            kind,
            target,
            tol,
            "m",
            None,
            f"Brake within {tol:.0f} m of {whose} braking point",
            " ".join(notes) or None,
            source,
        )
    if kind in ("min_speed", "exit_speed"):
        attr = METRICS[kind]
        baseline, source = _baseline(inputs, attr)
        if baseline is None:
            return Unavailable("Drive a clean lap first.")
        known = [
            v for v in (_num(getattr(m, attr)) for m in (inputs.ref, inputs.own_best) if m is not None) if v is not None
        ]
        cap = max(known) if known else max(_recent_values(inputs, attr), default=baseline)
        word = "minimum speed" if kind == "min_speed" else "exit speed"
        if baseline >= cap:
            return Unavailable(f"You already reach the best {word} driven here ({cap:.0f} km/h): pick another skill.")
        step = inputs.tolerance if inputs.tolerance is not None else SPEED_STEP_KPH
        target = min(baseline + step, cap)
        guard = None
        if kind == "min_speed":
            exit_base = _baseline(inputs, "exit_speed_kph")[0] if source == "own_laps" else None
            if exit_base is None and inputs.own_best is not None:
                exit_base = _num(inputs.own_best.exit_speed_kph)
            guard = None if exit_base is None else exit_base - EXIT_GUARD_KPH
        head = "Minimum speed" if kind == "min_speed" else "Exit speed"
        return DrillTarget(
            kind,
            target,
            step,
            "km/h",
            baseline,
            f"{head} {target:.0f} km/h or more (usually {baseline:.0f})",
            None,
            source,
            cap=cap,
            exit_guard=guard,
        )
    # entry_speed: anchored on the driver's own laps only (never another driver's arrival speed)
    anchor, source = _baseline(inputs, "entry_speed_kph")
    if anchor is None:
        return Unavailable("Drive a clean lap first.")
    tol = inputs.tolerance if inputs.tolerance is not None else ENTRY_TOLERANCE_KPH
    return DrillTarget(
        "entry_speed", anchor, tol, "km/h", anchor, f"Arrive at {anchor:.0f} km/h, within {tol:.0f} km/h", None, source
    )


# ============================================================================================== state
@dataclass(frozen=True, slots=True)
class DrillAttempt:
    attempt: int  # 1..laps_target
    lap_id: int | None
    lap_number: int | None
    value: float | None  # m or km/h; None = not measured
    target: float
    delta: float | None  # value - target
    outcome: str  # hit | miss | unmeasured
    reason: str | None
    corner_time_s: float | None
    corner_time_delta_s: float | None
    text: str
    short: str
    text_simple: str = ""  # not stored (the drill point carries it when the attempt is made)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "lap_id": self.lap_id,
            "lap_number": self.lap_number,
            "value": None if self.value is None else round(self.value, 2),
            "target": self.target,  # exact: a rounded brake target could land after the clamp
            "delta": None if self.delta is None else round(self.delta, 2),
            "outcome": self.outcome,
            "reason": self.reason,
            "corner_time_s": None if self.corner_time_s is None else round(self.corner_time_s, 3),
            "corner_time_delta_s": None if self.corner_time_delta_s is None else round(self.corner_time_delta_s, 3),
            "text": self.text,
            "short": self.short,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> DrillAttempt:
        def i(v: object) -> int | None:
            return v if isinstance(v, int) and not isinstance(v, bool) else None

        return cls(
            attempt=int(d.get("attempt") or 0),
            lap_id=i(d.get("lap_id")),
            lap_number=i(d.get("lap_number")),
            value=_num(d.get("value")),
            target=_num(d.get("target")) or 0.0,
            delta=_num(d.get("delta")),
            outcome=str(d.get("outcome") or "unmeasured"),
            reason=d.get("reason") if isinstance(d.get("reason"), str) else None,
            corner_time_s=_num(d.get("corner_time_s")),
            corner_time_delta_s=_num(d.get("corner_time_delta_s")),
            text=str(d.get("text") or ""),
            short=str(d.get("short") or ""),
        )


@dataclass(frozen=True, slots=True)
class DrillSpec:
    """Everything fixed when a drill starts (stored in the ``drills`` row and its ``detail`` JSON)."""

    id: int
    driver_id: int | None
    session_id: str | None
    game: str
    track_id: str
    track_length_m: float | None
    car_id: str | None
    track_model_version: int | None
    corner: str  # learned corner key (the join key)
    corner_label: str  # official short label at start ("T3"), display only
    corner_voice: str  # radio form at start ("Turn 3")
    apex_m: float | None
    kind: DrillKind
    source: str  # work_on | manual | radio
    observation_kind: str | None
    laps_target: int
    target: float
    tolerance: float
    unit: str
    baseline: float | None
    started_unix: float
    start_lap_number: int = 0  # frame lap number at start (0 = garage / pits / no frame)
    target_text: str = ""
    note: str | None = None
    target_source: str = ""
    cap: float | None = None
    exit_guard: float | None = None
    ref_lap_id: int | None = None
    ref_kind: str | None = None
    ref_driver_id: int | None = None
    ref_driver_name: str | None = None
    ref_label: str | None = None
    ref_name: str | None = None  # the other driver's name (None = the driver's own lap)
    ref_desc: Mapping[str, Any] | None = None  # the reference descriptor frozen for the drill
    clamp: Mapping[str, float] | None = None  # the braking clamp frozen for the drill (another driver's lap)
    # the conditions at the start (game, track, layout, car, weather, assists, formula): a lap in other conditions
    # (wet/dry, another assist) stops the drill, and the frozen reference is not used for it (core.coachref)
    context: Mapping[str, Any] | None = None

    @property
    def skill_label(self) -> str:
        return SKILL_LABELS[self.kind]


@dataclass(frozen=True, slots=True)
class DrillSummary:
    hits: int
    scored: int
    best: float | None  # the best attempt's value
    best_delta: float | None
    trend: str | None  # closer | steady | further | rising | falling | None (< TREND_MIN_ATTEMPTS)


@dataclass(frozen=True, slots=True)
class DrillState:
    """A drill and its attempts. Immutable: replaced on every attempt and when it ends."""

    spec: DrillSpec
    status: str = "active"  # active | completed | stopped | abandoned
    stop_reason: str | None = None
    ended_unix: float | None = None
    attempts: tuple[DrillAttempt, ...] = ()
    last_activity_unix: float = 0.0

    @property
    def active(self) -> bool:
        return self.status == "active"

    @property
    def summary(self) -> DrillSummary:
        return summarise(self.spec, self.attempts)

    def with_attempt(self, attempt: DrillAttempt, now: float) -> DrillState:
        attempts = (*self.attempts, attempt)
        done = len(attempts) >= self.spec.laps_target
        return replace(
            self,
            attempts=attempts,
            last_activity_unix=now,
            status="completed" if done else self.status,
            ended_unix=now if done else self.ended_unix,
        )

    def stopped(self, reason: str, now: float) -> DrillState:
        return replace(self, status="stopped" if self.attempts else "abandoned", stop_reason=reason, ended_unix=now)


# ============================================================================================== evaluation
def is_attempt_lap(spec: DrillSpec, session_id: str, lap_number: int, flags: Sequence[str] | set[str]) -> bool:
    """Whether a completed lap of the drill's driver (same context, processed after the start) is an attempt."""
    if NON_ATTEMPT_FLAGS & set(flags):
        return False
    return session_id != spec.session_id or lap_number > spec.start_lap_number


def _brake_phrase(outcome: str, delta: float) -> tuple[str, str]:
    a = abs(delta)
    if outcome == "hit":
        if a < ON_POINT_M:
            return "on the point", "on the point"
        if delta > 0:  # past the point and the corner was faster
            return f"on the point, {max(a, 1.0):.0f} m late but faster", "on the point"
        return f"on the point, {max(a, 1.0):.0f} m early", "on the point"
    txt = f"{a:.0f} m before the point" if delta < 0 else f"{max(a, 1.0):.0f} m past the point"
    return txt, txt


def _attempt_phrase(spec: DrillSpec, a: DrillAttempt, exit_kph: float | None = None) -> tuple[str, str]:
    """(phrase, simple phrase) for one attempt (spec 3.4.6)."""
    if a.reason == "incident":
        return "incident there", "incident there"
    if a.outcome == "unmeasured" or a.value is None or a.delta is None:
        txt = "no braking measured" if spec.kind == "brake_point" else "not measured"
        return txt, txt
    v, d = a.value, a.delta
    if spec.kind == "brake_point":
        return _brake_phrase(a.outcome, d)
    if spec.kind == "entry_speed":
        if a.outcome == "hit":
            return f"arrived at {v:.0f} km/h, on target", "on target"
        txt = f"arrived {abs(d):.0f} km/h {'faster' if d > 0 else 'slower'} than usual"
        return txt, txt
    word = "minimum" if spec.kind == "min_speed" else "exit"
    if a.reason is not None and a.reason.startswith("exit "):
        down = a.reason.removeprefix("exit ").removesuffix(" km/h down")
        return f"minimum {v:.0f} km/h but exit {down} km/h down", "exit speed down"
    if a.outcome == "hit":
        return f"{word} {v:.0f} km/h, on target", "on target"
    short_by = spec.target - v
    gap = f"{short_by:.0f} km/h short" if round(short_by) > 0 else "just short"
    return f"{word} {v:.0f} km/h, {gap}", gap


def evaluate_attempt(
    state: DrillState,
    m: CornerMetrics | None,
    cd: CornerDelta | None,
    *,
    lap_id: int | None,
    lap_number: int | None,
) -> DrillAttempt:
    """One lap at the drill corner (spec 3.4.4). ``m``: the lap's metrics there; ``cd``: its delta against the
    reference when a usable comparison exists (incident detection, corner time delta)."""
    spec = state.spec
    k = len(state.attempts) + 1
    attr = METRICS[spec.kind]
    value = _num(getattr(m, attr)) if m is not None else None
    delta = None if value is None else value - spec.target
    corner_t = _num(m.segment_time_s) if m is not None else None
    corner_dt = _num(cd.time_delta_s) if cd is not None else None
    outcome, reason = "miss", None
    if cd is not None and is_incident(cd):
        outcome, reason = "miss", "incident"
    elif value is None or delta is None:
        outcome, reason = "unmeasured", ("no braking measured" if spec.kind == "brake_point" else "not measured")
    elif spec.kind == "brake_point":
        # before the point within the tolerance; past it only when the corner got faster (later braking is praised
        # only when it paid off)
        faster = corner_dt is not None and corner_dt < 0
        if -spec.tolerance <= delta < ON_POINT_M or (ON_POINT_M <= delta <= spec.tolerance and faster):
            outcome = "hit"
    elif spec.kind == "entry_speed":
        outcome = "hit" if abs(delta) <= spec.tolerance else "miss"
    elif spec.kind == "min_speed":
        exit_v = _num(m.exit_speed_kph) if m is not None else None
        guard = spec.exit_guard
        if value >= spec.target and (guard is None or exit_v is None or exit_v >= guard):
            outcome = "hit"
        elif value >= spec.target and guard is not None and exit_v is not None:
            outcome, reason = "miss", f"exit {guard + EXIT_GUARD_KPH - exit_v:.0f} km/h down"
    else:  # exit_speed
        outcome = "hit" if value >= spec.target else "miss"
    draft = DrillAttempt(k, lap_id, lap_number, value, spec.target, delta, outcome, reason, corner_t, corner_dt, "", "")
    hits = sum(1 for a in state.attempts if a.outcome == "hit") + (outcome == "hit")
    if k >= spec.laps_target:
        text, simple, short = result_texts(replace(state, attempts=(*state.attempts, draft)), ended="done")
    else:
        # "2 of 5", never "lap 2 of 5": the drill's laps are not the race's
        phrase, simple_phrase = _attempt_phrase(spec, draft)
        text = f"{spec.corner_voice} drill, {k} of {spec.laps_target}: {phrase}. {_hits_text(hits).capitalize()}."
        simple = f"{spec.corner_voice} drill, {k} of {spec.laps_target}: {simple_phrase}."
        short = f"Drill {k}/{spec.laps_target}: {phrase} · {_hits_text(hits)}"
        if len(short) > SHORT_MAX_CHARS:
            short = _cut(f"Drill {k}/{spec.laps_target}: {phrase.split(',')[0]} · {_hits_text(hits)}")
    return replace(draft, text=text, short=short, text_simple=simple)


def _hits_text(hits: int) -> str:
    """ "no hits yet", "1 hit", "3 hits" (a running drill)."""
    return "no hits yet" if hits == 0 else f"{hits} hit{_plural(hits)}"


def summarise(spec: DrillSpec, attempts: Sequence[DrillAttempt]) -> DrillSummary:
    """Hits, the best attempt and the trend (spec 3.4.5)."""
    hits = sum(1 for a in attempts if a.outcome == "hit")
    scored = [a for a in attempts if a.outcome != "unmeasured"]
    measured = [a for a in scored if a.value is not None and a.delta is not None]
    best: DrillAttempt | None = None
    closeness = spec.kind in ("brake_point", "entry_speed")
    if measured:
        if closeness:
            best = min(measured, key=lambda a: (abs(a.delta or 0.0), a.attempt))
        else:
            best = max(measured, key=lambda a: (a.value or 0.0, -a.attempt))
    trend: str | None = None
    if len(measured) >= TREND_MIN_ATTEMPTS:
        half = len(measured) // 2
        first, second = measured[:half], measured[len(measured) - half :]
        if closeness:
            diff = statistics.fmean(abs(a.delta or 0.0) for a in second) - statistics.fmean(
                abs(a.delta or 0.0) for a in first
            )
            trend = "closer" if diff <= -spec.tolerance / 2 else "further" if diff >= spec.tolerance / 2 else "steady"
        else:
            diff = statistics.fmean(a.value or 0.0 for a in second) - statistics.fmean(a.value or 0.0 for a in first)
            trend = "rising" if diff >= SPEED_TREND_KPH else "falling" if diff <= -SPEED_TREND_KPH else "steady"
    return DrillSummary(
        hits=hits,
        scored=len(scored),
        best=None if best is None else best.value,
        best_delta=None if best is None else best.delta,
        trend=trend,
    )


def _best_text(spec: DrillSpec, s: DrillSummary) -> str | None:
    """The best attempt in words: "right on the point", "3 m from the point", "on target", "4 km/h from the target",
    "88 km/h"."""
    if s.best is None or s.best_delta is None:
        return None
    d = abs(s.best_delta)
    if spec.kind == "brake_point":
        return "right on the point" if d < ON_POINT_M else f"{max(d, 1.0):.0f} m from the point"
    if spec.kind == "entry_speed":
        return "on target" if round(d) == 0 else f"{d:.0f} km/h from the target"
    return f"{s.best:.0f} km/h"


def result_texts(state: DrillState, *, ended: str = "done") -> tuple[str, str, str]:
    """(text, text_simple, short) of a finished drill: ``ended`` "done" (all laps) or "stopped"."""
    spec, s = state.spec, state.summary
    word = "on the point" if spec.kind == "brake_point" else "on target"
    if ended == "done":
        head = f"{spec.corner_voice} drill done: {s.hits} of {s.scored} {word}."
        short_head = f"Drill done: {s.hits}/{s.scored}"
    else:
        k = len(state.attempts)
        head = f"{spec.corner_voice} drill stopped after {k} of {spec.laps_target} laps: {s.hits} of {s.scored} {word}."
        short_head = f"Drill stopped: {s.hits}/{s.scored}"
    best = _best_text(spec, s)
    trend = _TREND_SENTENCES.get(s.trend or "")
    if trend is not None and spec.kind == "entry_speed" and s.trend == "further":
        trend = "Drifting off the target."
    text = " ".join([head, *([f"Best: {best}."] if best else []), *([trend] if trend else [])])
    simple = " ".join([head, *([trend] if trend else [])])
    short = _cut(f"{short_head} · best {best}" if best else short_head)
    return text, simple, short


def status_text(state: DrillState) -> str:
    """The radio's answer to "how's my drill going" for an active drill."""
    spec, s = state.spec, state.summary
    done = len(state.attempts)
    line = f"{spec.corner_voice} {spec.skill_label.lower()} drill: {done} of {spec.laps_target} done, "
    line += f"{_hits_text(s.hits)}."
    if state.attempts:
        phrase, _ = _attempt_phrase(spec, state.attempts[-1])
        line += f" Last one {phrase}."
    return line


def stop_text(state: DrillState) -> str:
    """The radio's acknowledgement of "stop the drill"."""
    s = state.summary
    word = "on the point" if state.spec.kind == "brake_point" else "on target"
    return f"Copy, {state.spec.corner_voice} drill stopped: {s.hits} of {s.scored} {word}."


# ============================================================================================== coaching block
def drill_point(state: DrillState, attempt: DrillAttempt) -> dict[str, Any]:
    """The lap's D6 coaching point for a drill attempt: every ``coach.selection.COACH_FIELDS`` key (plus the slim
    copy's ``evidence`` / ``picked`` and the block point's ``habit`` / ``one_off``) and ``drill`` (id, attempt, of,
    hits, outcome, done)."""
    spec = state.spec
    s = state.summary
    ref_no = spec.ref_desc.get("lap_number") if spec.ref_desc else None
    evidence = {
        k: v
        for k, v in (
            ("target", spec.target),
            ("tolerance", round(spec.tolerance, 2)),
            ("delta", None if attempt.delta is None else round(attempt.delta, 2)),
            ("corner_time_delta_s", attempt.corner_time_delta_s),
        )
        if v is not None
    }
    return {
        "id": f"drill{spec.id}:a{attempt.attempt}",
        "kind": "drill",
        "corner": spec.corner,
        "corner_label": spec.corner_label,
        "lap_number": attempt.lap_number,
        "ref_lap_number": ref_no if isinstance(ref_no, int) and not isinstance(ref_no, bool) else None,
        "metric": METRICS[spec.kind],
        "value": None if attempt.value is None else round(attempt.value, 2),
        "unit": spec.unit,
        "impact_s": attempt.corner_time_delta_s,
        "confidence": 1.0,
        "priority": DRILL_PRIORITY,
        "positive": False,
        "consistency": None,
        "consistency_ratio": None,
        "text": attempt.text,
        "text_simple": attempt.text_simple or attempt.text,
        "short": attempt.short,
        "corner_voice": spec.corner_voice,
        "ref_name": spec.ref_name,
        "habit_event": None,  # habits (coach.habits): a drill attempt is no habit event and no one-off
        "was_value": None,
        "clean_laps": None,
        "clean_of": None,
        "habit": None,
        "one_off": False,
        "evidence": evidence,
        "picked": True,
        "drill": {
            "id": spec.id,
            "attempt": attempt.attempt,
            "of": spec.laps_target,
            "hits": s.hits,
            "outcome": attempt.outcome,
            "done": not state.active,
        },
    }


def with_drill(block: Mapping[str, Any], point: Mapping[str, Any] | None, corner: str) -> dict[str, Any]:
    """The lap's coach block while a drill runs: the drill point is the only point (``picked`` unless the radio is
    quiet; ``by_corner`` for the drill corner only), and ``drill_only`` tells the radio to say nothing else (no lap
    summary, no other corner)."""
    out = dict(block)
    out["picked"] = [] if point is None or block.get("radio_quiet") else [dict(point)]
    out["by_corner"] = {corner: dict(point)} if point is not None else {}
    out["drill_only"] = True
    return out


def drill_view(state: DrillState) -> dict[str, Any]:
    """``DrillView`` (spec 6.2): the API's and the snapshot's JSON for a drill."""
    spec, s = state.spec, state.summary
    summary_text = None
    if state.attempts and state.status in ("completed", "stopped"):
        summary_text = result_texts(state, ended="done" if state.status == "completed" else "stopped")[0]
    return {
        "id": spec.id,
        "driver_id": spec.driver_id,
        "session_id": spec.session_id,
        "game": spec.game,
        "track_id": spec.track_id,
        "car_id": spec.car_id,
        "corner": spec.corner,
        "corner_label": spec.corner_label,
        "corner_voice": spec.corner_voice,
        "kind": spec.kind,
        "skill_label": spec.skill_label,
        "source": spec.source,
        "laps_target": spec.laps_target,
        "target": spec.target,  # exact (never rounded past the braking clamp)
        "tolerance": spec.tolerance,
        "unit": spec.unit,
        "baseline": None if spec.baseline is None else round(spec.baseline, 2),
        "target_text": spec.target_text,
        "note": spec.note,
        "reference": {
            "lap_id": spec.ref_lap_id,
            "kind": spec.ref_kind,
            "driver_name": spec.ref_driver_name,
            "label": spec.ref_label,
        },
        "status": state.status,
        "stop_reason": state.stop_reason,
        "started_unix": spec.started_unix,
        "ended_unix": state.ended_unix,
        "attempts": [a.to_dict() for a in state.attempts],
        "hits": s.hits,
        "scored": s.scored,
        "best": None if s.best is None else round(s.best, 2),
        "best_delta": None if s.best_delta is None else round(s.best_delta, 2),
        "trend": s.trend,
        "summary_text": summary_text,
        "synthetic": False,
    }


# ============================================================================================== storage rows
def spec_row(spec: DrillSpec, state: DrillState) -> dict[str, Any]:
    """The ``drills`` row for a new drill (``repo.insert_drill``; the id is assigned by the database)."""
    row: dict[str, Any] = {
        "driver_id": spec.driver_id,
        "session_id": spec.session_id,
        "game": spec.game,
        "track_id": spec.track_id,
        "track_length_m": spec.track_length_m,
        "car_id": spec.car_id,
        "track_model_version": spec.track_model_version,
        "corner": spec.corner,
        "corner_label": spec.corner_label,
        "corner_voice": spec.corner_voice,
        "apex_m": spec.apex_m,
        "kind": spec.kind,
        "source": spec.source,
        "observation_kind": spec.observation_kind,
        "laps_target": spec.laps_target,
        "target": spec.target,
        "tolerance": spec.tolerance,
        "unit": spec.unit,
        "baseline": spec.baseline,
        "ref_lap_id": spec.ref_lap_id,
        "ref_kind": spec.ref_kind,
        "ref_driver_id": spec.ref_driver_id,
        "started_unix": spec.started_unix,
    }
    row.update(state_fields(state))
    return row


def state_fields(state: DrillState) -> dict[str, Any]:
    """The columns that change during a drill (``repo.update_drill``)."""
    spec, s = state.spec, state.summary
    return {
        "status": state.status,
        "stop_reason": state.stop_reason,
        "ended_unix": state.ended_unix,
        "attempts": len(state.attempts),
        "scored": s.scored,
        "hits": s.hits,
        "best_value": s.best,
        "best_delta": s.best_delta,
        "trend": s.trend,
        "laps": [a.to_dict() for a in state.attempts],
        "detail": {
            "start_lap_number": spec.start_lap_number,
            "target_text": spec.target_text,
            "note": spec.note,
            "target_source": spec.target_source,
            "cap": spec.cap,
            "exit_guard": spec.exit_guard,
            "ref_driver_name": spec.ref_driver_name,
            "ref_label": spec.ref_label,
            "ref_name": spec.ref_name,
            "ref_desc": dict(spec.ref_desc) if spec.ref_desc is not None else None,
            "clamp": dict(spec.clamp) if spec.clamp is not None else None,
            "context": dict(spec.context) if spec.context is not None else None,
            "last_activity_unix": state.last_activity_unix,
        },
    }


def state_from_row(row: Mapping[str, Any]) -> DrillState:
    """A stored drill (``repo.get_drill`` / ``list_drills`` row, JSON already decoded) as a ``DrillState``."""
    detail_raw = row.get("detail")
    detail: Mapping[str, Any] = detail_raw if isinstance(detail_raw, Mapping) else {}
    laps_raw = row.get("laps")
    laps = laps_raw if isinstance(laps_raw, list) else []
    clamp_raw = detail.get("clamp")
    clamp = (
        {str(k): float(v) for k, v in clamp_raw.items() if _num(v) is not None}
        if isinstance(clamp_raw, Mapping)
        else None
    )
    ref_desc = detail.get("ref_desc")
    context = detail.get("context")
    kind = str(row.get("kind") or "brake_point")

    def opt_int(v: object) -> int | None:
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def opt_str(v: object) -> str | None:
        return v if isinstance(v, str) else None

    spec = DrillSpec(
        id=int(row["id"]),
        driver_id=opt_int(row.get("driver_id")),
        session_id=opt_str(row.get("session_id")),
        game=str(row.get("game") or ""),
        track_id=str(row.get("track_id") or ""),
        track_length_m=_num(row.get("track_length_m")),
        car_id=opt_str(row.get("car_id")),
        track_model_version=opt_int(row.get("track_model_version")),
        corner=str(row.get("corner") or ""),
        corner_label=str(row.get("corner_label") or row.get("corner") or ""),
        corner_voice=str(row.get("corner_voice") or row.get("corner_label") or row.get("corner") or ""),
        apex_m=_num(row.get("apex_m")),
        kind=kind if kind in DRILL_KINDS else "brake_point",
        source=str(row.get("source") or "manual"),
        observation_kind=opt_str(row.get("observation_kind")),
        laps_target=int(row.get("laps_target") or DEFAULT_LAPS),
        target=_num(row.get("target")) or 0.0,
        tolerance=_num(row.get("tolerance")) or 0.0,
        unit=str(row.get("unit") or UNITS.get(kind, "m")),
        baseline=_num(row.get("baseline")),
        started_unix=_num(row.get("started_unix")) or 0.0,
        start_lap_number=opt_int(detail.get("start_lap_number")) or 0,
        target_text=str(detail.get("target_text") or ""),
        note=opt_str(detail.get("note")),
        target_source=str(detail.get("target_source") or ""),
        cap=_num(detail.get("cap")),
        exit_guard=_num(detail.get("exit_guard")),
        ref_lap_id=opt_int(row.get("ref_lap_id")),
        ref_kind=opt_str(row.get("ref_kind")),
        ref_driver_id=opt_int(row.get("ref_driver_id")),
        ref_driver_name=opt_str(detail.get("ref_driver_name")),
        ref_label=opt_str(detail.get("ref_label")),
        ref_name=opt_str(detail.get("ref_name")),
        ref_desc=dict(ref_desc) if isinstance(ref_desc, Mapping) else None,
        clamp=clamp,
        context=dict(context) if isinstance(context, Mapping) else None,
    )
    return DrillState(
        spec=spec,
        status=str(row.get("status") or "active"),
        stop_reason=opt_str(row.get("stop_reason")),
        ended_unix=_num(row.get("ended_unix")),
        attempts=tuple(DrillAttempt.from_dict(a) for a in laps if isinstance(a, Mapping)),
        last_activity_unix=_num(detail.get("last_activity_unix")) or spec.started_unix,
    )
