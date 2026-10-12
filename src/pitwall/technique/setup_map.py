"""Setup engineer (F1 25 only): one-parameter changes to try for handling symptoms that are the car's.

Rules:

* Only ``verdict == "car"`` symptoms qualify (they recur *and* show on the session's best lap), and only when they
  cover at least two corners, or one corner on at least three laps, or one corner strongly (at least 6 degrees of
  understeer, or a slide on every lap). A symptom the best lap did not have points at the driving: no setup.
* Lock-ups qualify only with ABS off, and only when they recur at two or more corners or on three or more laps.
* With the game's braking assist on, the brake figures are not all the driver's (``technique.rig``): brake bias and
  brake pressure are never suggested then, nor anything that needs the symptom to happen under braking.
* Each suggestion changes **one** parameter by a trial step in menu units (wings 2 clicks, differentials 10 %,
  anti-roll bars 2, suspension 3, brake bias 1 %, brake pressure 3 %), from the session's latest stored setup,
  snapped to the car format's range (an F2 car: the F2 ranges, never the F1 car's). It feeds the existing
  experiments flow (``carsetup.experiments.propose``).
* Never suggested: tyre pressures (they change as a pair, which breaks the one-parameter rule), camber, toe and
  ride heights. If two symptoms want one parameter moved in opposite directions, it is dropped from both.
* Every result carries ``carsetup.recommend.CAVEAT``: a setup is never a guaranteed fix.

The candidate lists are Pitwall's heuristics; the ``why`` texts are in our own words and the expected effects come
from the cited setup catalogue (``carsetup.catalog``, ``Parameter.higher`` / ``lower``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pitwall.carsetup.catalog import CarFormat, Catalog
from pitwall.carsetup.recommend import CAVEAT
from pitwall.technique import thresholds as T
from pitwall.technique.balance import BalanceSymptom
from pitwall.technique.samples import rnd

Direction = Literal["higher", "lower"]
NEVER_SUGGESTED: frozenset[str] = frozenset(
    {
        "tyre_pressure_fl",
        "tyre_pressure_fr",
        "tyre_pressure_rl",
        "tyre_pressure_rr",
        "front_camber",
        "rear_camber",
        "front_toe",
        "rear_toe",
        "front_ride_height",
        "rear_ride_height",
    }
)
# trial step in the menu's own units (heuristic)
TRIAL_STEP: dict[str, float] = {
    "front_wing": 2,
    "rear_wing": 2,
    "diff_on_throttle": 10,
    "diff_off_throttle": 10,
    "front_arb": 2,
    "rear_arb": 2,
    "front_suspension": 3,
    "rear_suspension": 3,
    "brake_bias": 1,
    "brake_pressure": 3,
}
BRAKE_KEYS: frozenset[str] = frozenset({"brake_bias", "brake_pressure"})
NOTE_BRAKING_ASSIST = (
    "Brake bias and pressure are not suggested while the game's braking assist is on (it adds its own braking)."
)
FORMAT_UNKNOWN = "Choose the car format at the top of this page to size this change."
ALL: frozenset[str] = frozenset({"slow", "medium", "fast"})
SLOW_MED: frozenset[str] = frozenset({"slow", "medium"})
MED_FAST: frozenset[str] = frozenset({"medium", "fast"})
FAST: frozenset[str] = frozenset({"fast"})


@dataclass(frozen=True, slots=True)
class Candidate:
    key: str
    direction: Direction
    speeds: frozenset[str] = ALL
    needs_braking: bool = False
    why: str = ""


# (phase, class) -> candidates in rank order
CANDIDATES: dict[tuple[str, str], tuple[Candidate, ...]] = {
    ("entry", "understeer"): (
        Candidate(
            "diff_off_throttle",
            "lower",
            why="A more open off-throttle differential lets the rear wheels turn "
            "at different speeds off the throttle, so the car rotates more into the corner.",
        ),
        Candidate(
            "brake_bias",
            "lower",
            needs_braking=True,
            why="Moving the brake bias rearwards takes braking "
            "load off the fronts, leaving them more grip for turning while you are still braking.",
        ),
        Candidate(
            "front_arb",
            "lower",
            SLOW_MED,
            why="A softer front anti-roll bar gives the front tyres more grip in slow and medium corners.",
        ),
        Candidate(
            "front_wing",
            "higher",
            MED_FAST,
            why="More front wing adds front downforce, which helps the fronts grip in medium and fast corners.",
        ),
    ),
    ("mid", "understeer"): (
        Candidate(
            "front_arb",
            "lower",
            SLOW_MED,
            why="A softer front anti-roll bar gives the front tyres more grip in slow and medium corners.",
        ),
        Candidate(
            "front_wing",
            "higher",
            MED_FAST,
            why="More front wing adds front downforce, which helps the fronts grip in medium and fast corners.",
        ),
        Candidate(
            "rear_arb",
            "higher",
            SLOW_MED,
            why="A stiffer rear anti-roll bar moves the balance towards the "
            "front, so the car turns more readily mid-corner.",
        ),
    ),
    ("exit", "understeer"): (
        Candidate(
            "diff_on_throttle",
            "lower",
            why="A more open on-throttle differential lets the car turn more while you are on the power.",
        ),
        Candidate(
            "rear_arb",
            "higher",
            SLOW_MED,
            why="A stiffer rear anti-roll bar moves the balance towards the "
            "front, so the car turns more readily on the exit.",
        ),
    ),
    ("entry", "oversteer"): (
        Candidate(
            "brake_bias",
            "higher",
            needs_braking=True,
            why="Moving the brake bias forwards puts less "
            "braking on the rears, so they keep more grip for stability while you brake into the corner.",
        ),
        Candidate(
            "diff_off_throttle",
            "higher",
            why="A more locked off-throttle differential keeps the rear wheels "
            "together off the throttle, which steadies the car on entry.",
        ),
        Candidate("rear_arb", "lower", why="A softer rear anti-roll bar gives the rear tyres more grip."),
        Candidate(
            "rear_wing",
            "higher",
            FAST,
            why="More rear wing adds rear downforce, which steadies the car in fast corners.",
        ),
    ),
    ("mid", "oversteer"): (
        Candidate("rear_arb", "lower", why="A softer rear anti-roll bar gives the rear tyres more grip."),
        Candidate(
            "rear_wing",
            "higher",
            MED_FAST,
            why="More rear wing adds rear downforce, which helps the rears grip in medium and fast corners.",
        ),
    ),
    ("exit", "oversteer"): (
        Candidate(
            "diff_on_throttle",
            "lower",
            why="A more open on-throttle differential makes the rear less likely "
            "to step out when you get on the power.",
        ),
        Candidate("rear_arb", "lower", why="A softer rear anti-roll bar gives the rear tyres more grip."),
        Candidate(
            "rear_suspension",
            "lower",
            why="Softer rear suspension helps the rear tyres follow the track and put the power down.",
        ),
        Candidate(
            "rear_wing",
            "higher",
            MED_FAST,
            why="More rear wing adds rear downforce, which helps the rears grip in medium and fast corners.",
        ),
    ),
}
LOCKUP_CANDIDATES: dict[str, tuple[Candidate, ...]] = {
    "front": (
        Candidate("brake_pressure", "lower", why="Lower brake pressure makes the wheels harder to lock at full pedal."),
        Candidate(
            "brake_bias",
            "lower",
            why="Moving the brake bias rearwards puts less braking on the fronts, so they lock less easily.",
        ),
    ),
    "rear": (
        Candidate(
            "brake_bias",
            "higher",
            why="Moving the brake bias forwards puts less braking on the rears, so they lock less easily.",
        ),
    ),
}


@dataclass(slots=True)
class LockupSymptom:
    """Lock-ups that recur with ABS off (``axle`` front or rear); not a handling-balance symptom."""

    id: str
    axle: Literal["front", "rear"]
    corners: list[str]
    corner_labels: list[str]
    laps: int
    events: int
    text: str
    text_simple: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "axle": self.axle,
            "corners": list(self.corners),
            "corner_labels": list(self.corner_labels),
            "laps": self.laps,
            "events": self.events,
            "text": self.text,
            "text_simple": self.text_simple,
        }


@dataclass(slots=True)
class SetupSuggestion:
    symptom_id: str
    rank: int
    parameter: str
    label: str
    unit: str | None
    direction: Direction
    from_value: float | None
    to_value: float | None
    steps: float
    effect: str
    why: str
    hypothesis: str
    blocked: str | None
    symptom_text: str = ""  # for facts (not serialised)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symptom_id": self.symptom_id,
            "rank": self.rank,
            "parameter": self.parameter,
            "label": self.label,
            "unit": self.unit,
            "direction": self.direction,
            "from_value": self.from_value,
            "to_value": self.to_value,
            "steps": rnd(self.steps, 2),
            "effect": self.effect,
            "why": self.why,
            "hypothesis": self.hypothesis,
            "blocked": self.blocked,
        }


@dataclass(slots=True)
class SetupEngineer:
    car_format: CarFormat | None
    setup_known: bool
    suggestions: list[SetupSuggestion] = field(default_factory=list)
    caveat: str = CAVEAT
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "car_format": self.car_format,
            "setup_known": self.setup_known,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "caveat": self.caveat,
            "note": self.note,
        }


def qualifies(s: BalanceSymptom) -> bool:
    if s.verdict != "car":
        return False
    if len(s.corners) >= 2:
        return True
    laps = max(s.per_corner_laps.values(), default=s.laps)
    if laps >= T.SETUP_SINGLE_CORNER_MIN_LAPS:
        return True
    if s.cls == "understeer" and s.median_slip_diff_deg >= T.STRONG_US_DIFF_DEG:
        return True
    return s.cls == "oversteer" and s.slide_every_lap


def lockup_qualifies(s: LockupSymptom) -> bool:
    return len(s.corners) >= T.LOCKUP_RECUR_CORNERS or s.laps >= T.LOCKUP_RECUR_LAPS


def _applicable(c: Candidate, s: BalanceSymptom, braking_assist: bool = False) -> bool:
    if c.key in NEVER_SUGGESTED:
        return False
    if braking_assist and (c.needs_braking or c.key in BRAKE_KEYS):
        return False
    if c.needs_braking and not s.with_braking:
        return False
    speeds = s.corner_speed_classes or set(ALL)
    return bool(speeds & c.speeds)


def suggest(
    symptoms: Sequence[BalanceSymptom],
    lockups: Sequence[LockupSymptom],
    *,
    cat: Catalog,
    car_format: CarFormat | None,
    stored: Mapping[str, float] | None,
    testing: frozenset[str] = frozenset(),
    braking_assist: bool = False,
    format_unknown: str = FORMAT_UNKNOWN,
) -> SetupEngineer:
    """Suggestions for the qualifying symptoms. ``stored``: menu values of the session's latest setup (None =
    unknown). ``testing``: parameters with an experiment already proposed or running from this session.
    ``braking_assist``: the game's braking assist was on (no brake bias or pressure changes). ``format_unknown``:
    why a change cannot be sized without a car format (an F2 car with no setups is never asked to choose one)."""
    wanted: list[tuple[str, str, list[Candidate]]] = []  # (symptom id, simple text, candidates)
    brake_dropped = False
    for s in symptoms:
        if not qualifies(s):
            continue
        all_c = CANDIDATES.get((s.phase, s.cls), ())
        cands = [c for c in all_c if _applicable(c, s, braking_assist)]
        brake_dropped |= braking_assist and any(c.key in BRAKE_KEYS for c in all_c if _applicable(c, s))
        wanted.append((s.id, s.text_simple, cands[: T.MAX_SUGGESTIONS_PER_SYMPTOM]))
    for lk in lockups:
        if lockup_qualifies(lk):
            if braking_assist:
                brake_dropped = True  # every lock-up candidate is a brake setting
                continue
            wanted.append((lk.id, lk.text_simple, list(LOCKUP_CANDIDATES[lk.axle])))
    # a parameter two symptoms want moved in opposite directions is dropped from both
    dirs: dict[str, set[str]] = {}
    for _, _, cands in wanted:
        for c in cands:
            dirs.setdefault(c.key, set()).add(c.direction)
    conflicts = sorted(k for k, d in dirs.items() if len(d) > 1)
    notes: list[str] = []
    if brake_dropped:
        notes.append(NOTE_BRAKING_ASSIST)
    if conflicts:
        labels = [(p.label if (p := cat.param(k)) else k) for k in conflicts]
        notes.append(
            "Not suggested because two symptoms want it moved in opposite directions: " + ", ".join(labels) + "."
        )
    out: list[SetupSuggestion] = []
    for sid, simple, cands in wanted:
        rank = 0
        for c in cands:
            if c.key in conflicts:
                continue
            p = cat.param(c.key)
            if p is None:
                continue
            rank += 1
            out.append(_suggestion(sid, simple, rank, c, cat, car_format, stored, testing, format_unknown))
    if not wanted:
        notes.append(
            "No handling symptom qualifies for a setup change: a symptom must recur and also show on your best lap "
            "this session (otherwise it points at the driving)."
        )
    elif stored is None:
        notes.append("No setup has been received from the game in this session, so the starting values are unknown.")
    return SetupEngineer(
        car_format=car_format,
        setup_known=stored is not None,
        suggestions=out,
        note=" ".join(notes) or None,
    )


def _suggestion(
    sid: str,
    simple: str,
    rank: int,
    c: Candidate,
    cat: Catalog,
    car_format: CarFormat | None,
    stored: Mapping[str, float] | None,
    testing: frozenset[str],
    format_unknown: str = FORMAT_UNKNOWN,
) -> SetupSuggestion:
    p = cat.param(c.key)
    assert p is not None
    effect = p.higher if c.direction == "higher" else p.lower
    step = TRIAL_STEP.get(c.key, 1.0)
    rng = cat.range(car_format, c.key) if car_format is not None else None
    from_v = stored.get(c.key) if stored is not None else None
    to_v: float | None = None
    blocked: str | None = None
    steps = step / rng.step if rng is not None and rng.step > 0 else step
    if car_format is None:
        blocked = format_unknown
    elif rng is None:
        blocked = f"{p.label} has no known range for this car format."
    elif from_v is None:
        blocked = "Your setup for this session is unknown (the game has not sent it)."
    else:
        target = from_v + step if c.direction == "higher" else from_v - step
        to_v = round(rng.snap(target), p.decimals)
        steps = abs(to_v - from_v) / rng.step if rng.step > 0 else abs(to_v - from_v)
        if abs(to_v - from_v) < rng.step / 4:
            end = "maximum" if c.direction == "higher" else "minimum"
            blocked = f"{p.label} is already at its {end} ({p.fmt(from_v)})."
            to_v = None
    if blocked is None and c.key in testing:
        blocked = f"An experiment with {p.label} is already proposed or running from this session."
    hypothesis = f"{p.label} {p.fmt(from_v)} → {p.fmt(to_v)}: {simple} Expected: {effect}"
    if len(hypothesis) > 500:
        hypothesis = hypothesis[:497].rstrip() + "..."
    return SetupSuggestion(
        symptom_id=sid,
        rank=rank,
        parameter=c.key,
        label=p.label,
        unit=p.unit,
        direction=c.direction,
        from_value=from_v,
        to_value=to_v,
        steps=steps,
        effect=effect,
        why=c.why,
        hypothesis=hypothesis,
        blocked=blocked,
        symptom_text=simple,
    )
