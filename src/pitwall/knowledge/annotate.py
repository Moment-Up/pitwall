"""Applying the technique graph to one driver (spec: technique knowledge graph, section 3): which nodes fit them and
why the others do not, which causes the measured signals name, what to say at their skill and style, and the
``knowledge`` annotation every coaching observation carries.

``DriverKnowledge(graph, context, game)`` is the graph seen for one driver (``knowledge.context.Context``) on one game:

* **Fit** (``fit``): a condition holds or not (unknown never holds); a signal is available unless the game does not
  send one of its channels (``context.channel_status``: only ``not_sent`` counts; an unknown channel is never assumed
  absent); a technique fits when its ``applies_when`` all hold and one of its ``applies_any`` does; a fault applies when
  its conditions fit *and* every one of its signals is available; a cause can be named when its conditions fit (e.g.
  ``ready_earlier`` only with traction control off) and the signals of its ``need = "all"`` discriminators, and of at
  least one ``need = "any"``, are available; advice fits when its fault or
  cause applies, its skill is the driver's (or ``any``) and its style (when it has one) the driver's braking style.
  ``why_not`` says why not in plain words ("Only for: H-pattern gearbox (gearbox not known)", "GT7 does not send
  lateral g").
* **Causes** (``causes``): named from measured values only (``graph.Discriminator.holds``: an unmeasured value holds
  nothing), each with the evidence that named it: the discriminators that held, their plain-words test and the value,
  and ``discriminates``: whether the cause's base-rate check showed it tells its fault apart (``graph.Cause``). Only
  such a cause is said as the reason (the coach card, any radio form, the AI engineer's driver-facing sentence);
  Review shows the others as also measured on that lap, never as why.
* **Advice** (``advice``): per form (radio, screen, review), the first advice for the node that has that form, ranked
  a style match first, then the driver's skill, then ``any`` (file order breaks ties). The live faults' ``any``
  advice is today's wording without the numbers, so the radio and the card read as before; numbers stay in the
  observation's own text. With the game's braking assist on (``braking_assist``, ``knowledge.style``), advice chosen
  for the detected braking style says that some of that braking was the game's (``ASSIST_CAVEAT``), as How corners
  work and the AI engineer do: a habit read partly from the game's braking is never presented as all the driver's.

The annotation (``annotate``, an additive ``knowledge`` key on ``Observation.to_dict()`` shapes; never stored):
``{fault, name, status, tier, applies, why_not, causes: [{id, name, tier, discriminates, evidence: [{signal, test,
value, unit}], advice}], advice: {radio, screen, review, ids}, digest}``, or None when the graph did not load or has no
fault for the observation's kind. ``analysis.coaching.applies`` reads ``applies``: a fault that does not apply is stored
and shown in Review with ``why_not``, never picked for the radio or the coach card, and never a habit
(``coach.selection``, ``coach.habits``). For the eight live kinds this changes nothing on F1: they have no conditions
and every game sends their channels. ``slim`` is the coach block's copy (``coach.selection.slim``) and ``card_slim`` the
snapshot observations' copy: both carry only the causes that tell their fault apart, the only ones the coach card says.

Signal values (``LapSignals``): a compared lap's per-corner values, read where each signal's ``code`` says -
``CornerDelta.*`` from the corner's delta, ``CornerMetrics.*`` from this lap's metrics, and the technique signals that
share a field (``TECHNIQUE_READERS``: the entry / mid / exit phase of ``PhaseBalance``, lock-up or wheelspin
``SlipEvents``) from this lap's inputs and balance at that corner, computed only when a cause needs them
(``technique.session.lap_corner``, as the Technique page computes them); the ``*_vs_ref`` signals (mid-corner
understeer and slide, exit wheelspin, slide and oversteer) also read the reference lap's inputs and balance at that
corner (computed only then), so a symptom the reference lap shared names no cause. Session-wide signals
(``CornerSummary``, ``LapCornerTechnique``) are not per-lap values and read as unmeasured here.

Deterministic, no I/O, no LLM: the AI engineer may explain these annotations, never invent one.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from pitwall.knowledge.context import CHANNEL_WORDS, ChannelStatus, Context, channel_status, game_label
from pitwall.knowledge.graph import (
    Advice,
    Cause,
    Channel,
    Condition,
    Discriminator,
    Fault,
    Node,
    Signal,
    Technique,
    TechniqueGraph,
)
from pitwall.technique.thresholds import OS_DIFF_DEG, US_DIFF_DEG

if TYPE_CHECKING:
    from pitwall.analysis.compare import CornerDelta, LapAnalysis
    from pitwall.analysis.track import Corner
    from pitwall.technique.balance import Phase, PhaseBalance
    from pitwall.technique.inputs import CornerInputs, SlipEvents
    from pitwall.technique.samples import Native

FORMS = ("radio", "screen", "review")
# Said after advice written for the driver's detected braking style when the game's braking assist was on (the same
# words as the AI engineer's context fact and How corners work).
ASSIST_CAVEAT = "The game's braking assist was on, so some of that braking was the game's."
# A Context key and its values in words, for ``why_not``.
KEY_WORDS: Mapping[str, str] = {
    "skill": "skill",
    "braking_style": "braking style",
    "coasting": "coasting",
    "game": "game",
    "car_family": "car",
    "downforce": "downforce",
    "abs": "ABS",
    "traction_control": "traction control",
    "gearbox": "gearbox",
    "fuel_saving": "fuel saving",
    "wet": "wet track",
}
VALUE_WORDS: Mapping[str, str] = {
    "straight_line": "straight-line",
    "paddle_autoblip": "paddles with auto-blip",
    "h_pattern": "H-pattern",
    "auto": "automatic",
    "f1": "F1",
    "f2": "F2",
    "gt7": "GT7",
    "forza": "Forza",
    "ac": "Assetto Corsa",
    "acc": "ACC",
}
SKILL_WORDS: Mapping[str, str] = {
    "beginner": "beginner drivers",
    "intermediate": "intermediate drivers",
    "advanced": "advanced drivers",
}
STYLE_WORDS: Mapping[str, str] = {
    "trail": "trail-braking drivers",
    "straight_line": "drivers who brake in a straight line",
    "mixed": "drivers with a mixed braking style",
}


@dataclass(frozen=True, slots=True)
class Fit:
    """Whether a node fits the driver; ``why_not`` says why not (None when it fits)."""

    applies: bool
    why_not: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"applies": self.applies, "why_not": self.why_not}


FITS = Fit(True)


# ---------------------------------------------------------------------------------------------- signal values
type Balance = Mapping[Phase, PhaseBalance | None]  # a corner's balance per phase (technique.balance.lap_balance)


@dataclass(slots=True)
class CornerTechnique:
    """One lap's inputs and handling balance at one corner (``technique.session.lap_corner``). ``ref_balance`` /
    ``ref_inputs``: the reference lap's balance and inputs at that corner, computed on first use (None = not known)."""

    inputs: CornerInputs | None
    balance: Balance | None
    ref_balance: Callable[[], Balance | None] | None = None
    ref_inputs: Callable[[], CornerInputs | None] | None = None


def _phase(t: CornerTechnique, phase: Phase, attr: str) -> object:
    pb = t.balance.get(phase) if t.balance is not None else None
    return getattr(pb, attr, None) if pb is not None else None


def _ref_phase(t: CornerTechnique, phase: Phase) -> PhaseBalance | None:
    rb = t.ref_balance() if t.ref_balance is not None else None
    return rb.get(phase) if rb is not None else None


# [H] Understeer that cost this lap grip the reference lap had: the front tyres at least US_DIFF_DEG (3 degrees) past
# the rears around the slowest point (understeer, technique.thresholds) and at least that much more than on the
# reference lap at the corner. A corner's mid-corner slip difference moves about 1.8 degrees between clean laps (the
# median per-corner spread; 90 % of clean laps within +2.9 degrees of the corner's median, six real F1 25 sessions,
# pitwall_signal_spread), so 3 degrees more is outside a clean lap's normal spread. Understeer the reference lap shared
# is the car at that corner, not grip this lap lacked.
UNDERSTEER_MORE_DEG = US_DIFF_DEG


def _understeer_vs_ref(t: CornerTechnique) -> bool | None:
    """Mid-corner understeer on this lap and ``UNDERSTEER_MORE_DEG`` more than on the reference lap; False when this
    lap did not understeer, None when either lap's balance was not measured."""
    this = _phase(t, "mid", "slip_diff_deg")
    if not isinstance(this, float | int):
        return None
    if this < US_DIFF_DEG:
        return False
    ref = _ref_phase(t, "mid")
    r = ref.slip_diff_deg if ref is not None else None
    return None if r is None else this - r >= UNDERSTEER_MORE_DEG


def _slide_vs_ref(t: CornerTechnique, phase: Phase = "mid") -> bool | None:
    """A slide in ``phase`` (around the slowest point; ``exit``: on the way out) on this lap and none on the reference
    lap; False when this lap did not slide, None when either lap's balance was not measured."""
    pb = t.balance.get(phase) if t.balance is not None else None
    if pb is None:
        return None
    if not pb.slide:
        return False
    ref = _ref_phase(t, phase)
    return None if ref is None else not ref.slide


def _events(slip: SlipEvents | None) -> int | None:
    """Events counted only when measured (``abs_on``, ``no_data`` and ``not_applicable`` are unknown, not zero)."""
    return slip.events if slip is not None and slip.status == "measured" else None


def _spin_vs_ref(t: CornerTechnique) -> bool | None:
    """Wheelspin on the way out on this lap and none on the reference lap at that corner; False when this lap had
    none, None when either lap's wheelspin was not measured. Spin the reference lap shared is the car at that corner
    (or its traction control), not what held this lap's throttle back."""
    this = _events(t.inputs.wheelspin if t.inputs is not None else None)
    if this is None:
        return None
    if this < 1:
        return False
    ref = t.ref_inputs() if t.ref_inputs is not None else None
    r = _events(ref.wheelspin if ref is not None else None)
    return None if r is None else r == 0


def _oversteer_vs_ref(t: CornerTechnique) -> bool | None:
    """Oversteer on the way out on this lap (front-minus-rear slip at or below ``OS_DIFF_DEG``, as
    ``technique.balance`` classes it) and not on the reference lap at that corner; False when this lap did not
    oversteer, None when either lap's exit balance was not measured."""
    this = _phase(t, "exit", "slip_diff_deg")
    if not isinstance(this, float | int):
        return None
    if this > OS_DIFF_DEG:
        return False
    ref = _ref_phase(t, "exit")
    r = ref.slip_diff_deg if ref is not None else None
    return None if r is None else r > OS_DIFF_DEG


def _inputs(t: CornerTechnique, attr: str) -> object:
    return getattr(t.inputs, attr, None) if t.inputs is not None else None


# Signals whose code names a field another signal shares (which phase, which slip events), or a CornerInputs field:
# signal id -> (the code it reads, the reader). A test keeps the code equal to the graph signal's.
TECHNIQUE_READERS: Mapping[str, tuple[str, Callable[[CornerTechnique], object]]] = {
    "entry_balance_deg": ("PhaseBalance.slip_diff_deg", lambda t: _phase(t, "entry", "slip_diff_deg")),
    "mid_balance_deg": ("PhaseBalance.slip_diff_deg", lambda t: _phase(t, "mid", "slip_diff_deg")),
    "exit_balance_deg": ("PhaseBalance.slip_diff_deg", lambda t: _phase(t, "exit", "slip_diff_deg")),
    "mid_slide": ("PhaseBalance.slide", lambda t: _phase(t, "mid", "slide")),
    "exit_slide": ("PhaseBalance.slide", lambda t: _phase(t, "exit", "slide")),
    "mid_understeer_vs_ref": ("PhaseBalance.slip_diff_deg", _understeer_vs_ref),
    "mid_slide_vs_ref": ("PhaseBalance.slide", _slide_vs_ref),
    "exit_wheelspin_vs_ref": ("SlipEvents.events", _spin_vs_ref),
    "exit_slide_vs_ref": ("PhaseBalance.slide", lambda t: _slide_vs_ref(t, "exit")),
    "exit_oversteer_vs_ref": ("PhaseBalance.slip_diff_deg", _oversteer_vs_ref),
    "entry_brake_share": ("PhaseBalance.brake_share", lambda t: _phase(t, "entry", "brake_share")),
    "lockup_events": ("SlipEvents.events", lambda t: _events(t.inputs.lockup if t.inputs is not None else None)),
    "exit_wheelspin_events": (
        "SlipEvents.events",
        lambda t: _events(t.inputs.wheelspin if t.inputs is not None else None),
    ),
    "brake_at_turn_in": ("CornerInputs.brake_at_turn_in", lambda t: _inputs(t, "brake_at_turn_in")),
    "trail_overlap_s": ("CornerInputs.trail_overlap_s", lambda t: _inputs(t, "trail_overlap_s")),
    "pickup_vs_apex_m": ("CornerInputs.pickup_vs_apex_m", lambda t: _inputs(t, "pickup_vs_apex_m")),
    "throttle_ramp_s": ("CornerInputs.throttle_ramp_s", lambda t: _inputs(t, "throttle_ramp_s")),
    "throttle_lifts": ("CornerInputs.throttle_lifts", lambda t: _inputs(t, "throttle_lifts")),
}
# Classes whose fields are per-lap values of a corner read from its delta or this lap's metrics.
DELTA_CLASS, METRICS_CLASS = "CornerDelta", "CornerMetrics"

Reader = Callable[[Signal], object]


def corner_reader(cd: CornerDelta | None, technique: Callable[[], CornerTechnique | None] | None = None) -> Reader:
    """A function reading a signal's value at one corner of one compared lap (None = not measured)."""

    def read(s: Signal) -> object:
        if s.code is None:
            return None
        cls, _, attr = s.code.partition(".")
        if cls == DELTA_CLASS:
            return getattr(cd, attr, None) if cd is not None else None
        if cls == METRICS_CLASS:
            return getattr(cd.cmp, attr, None) if cd is not None else None
        rd = TECHNIQUE_READERS.get(s.id)
        if rd is None or technique is None:
            return None
        t = technique()
        return None if t is None else rd[1](t)

    return read


class LapSignals:
    """Signal values of one compared lap, per corner. A corner's inputs and balance (``CornerTechnique``) are computed
    once, the first time a cause needs one of them; this lap's native samples likewise."""

    def __init__(
        self,
        deltas: Mapping[str, CornerDelta],
        lap: LapAnalysis | None = None,
        ref: LapAnalysis | None = None,
        corners: Mapping[str, Corner] | None = None,
    ) -> None:
        self.deltas = deltas
        self.lap = lap
        self.ref = ref
        self.corners = corners or {}
        self._native: Native | None = None
        self._ref_native: Native | None = None
        self._technique: dict[str, CornerTechnique | None] = {}
        self._ref_corner: dict[str, tuple[CornerInputs, Balance | None] | None] = {}

    def technique(self, corner: str) -> CornerTechnique | None:
        if corner in self._technique:
            return self._technique[corner]
        out: CornerTechnique | None = None
        c = self.corners.get(corner)
        if self.lap is not None and c is not None:
            # lazy: technique.session imports core.session_analysis, which annotates with this module
            from pitwall.technique.samples import native
            from pitwall.technique.session import corner_anchors, lap_corner

            if self._native is None:
                self._native = native(self.lap.lap)
            inputs, balance = lap_corner(self.lap, self._native, c, corner_anchors(self.ref, c))
            out = CornerTechnique(inputs, balance, lambda: self.ref_balance(corner), lambda: self.ref_inputs(corner))
        self._technique[corner] = out
        return out

    def _ref_at(self, corner: str) -> tuple[CornerInputs, Balance | None] | None:
        """The reference lap's inputs and handling balance at ``corner`` (computed once, when a cause compares with
        it)."""
        if corner in self._ref_corner:
            return self._ref_corner[corner]
        out: tuple[CornerInputs, Balance | None] | None = None
        c = self.corners.get(corner)
        if self.ref is not None and c is not None:
            from pitwall.technique.samples import native
            from pitwall.technique.session import corner_anchors, lap_corner

            if self._ref_native is None:
                self._ref_native = native(self.ref.lap)
            out = lap_corner(self.ref, self._ref_native, c, corner_anchors(self.ref, c))
        self._ref_corner[corner] = out
        return out

    def ref_balance(self, corner: str) -> Balance | None:
        """The reference lap's handling balance at ``corner``."""
        at = self._ref_at(corner)
        return at[1] if at is not None else None

    def ref_inputs(self, corner: str) -> CornerInputs | None:
        """The reference lap's inputs at ``corner`` (its wheelspin and lock-ups)."""
        at = self._ref_at(corner)
        return at[0] if at is not None else None

    def reader(self, corner: object) -> Reader:
        name = str(corner)
        return corner_reader(self.deltas.get(name), lambda: self.technique(name))


# ---------------------------------------------------------------------------------------------- words
def _value_words(key: str, value: object) -> str:
    k = KEY_WORDS.get(key, key)
    if value is None:
        return f"{k} not known"
    if isinstance(value, bool):
        if key == "wet":
            return "wet track" if value else "dry track"
        if key == "fuel_saving":
            return "saving fuel" if value else "not saving fuel"
        return f"{k} {'on' if value else 'off'}"
    v = str(value)
    return f"{k} {VALUE_WORDS.get(v, v.replace('_', ' '))}"


def _py(v: object) -> object:
    """A numpy scalar as the Python value it holds (``graph.Discriminator.holds`` tests Python types)."""
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def _round(v: object) -> object:
    """A measured value for JSON: plain bool / int, a float to 2 decimals (numpy scalars converted)."""
    if v is None or isinstance(v, bool | np.bool_):
        return None if v is None else bool(v)
    if isinstance(v, int | np.integer):
        return int(v)
    if isinstance(v, float | np.floating):
        f = float(v)
        return round(f, 2) + 0.0 if math.isfinite(f) else None
    return None


def _context_value(context: object, key: str) -> object:
    return context.get(key) if isinstance(context, Mapping) else getattr(context, key, None)


# ---------------------------------------------------------------------------------------------- the driver's view
@dataclass(slots=True)
class DriverKnowledge:
    """The technique graph seen for one driver (``context``) on one game (``game``: a ``model.telemetry.Game`` value;
    None = unknown, no channel known absent). ``braking_assist``: the F1 braking assist level the style was detected
    with (``knowledge.style.Style.braking_assist``; 1 and above: style advice carries ``ASSIST_CAVEAT``). Fits are
    cached per node."""

    graph: TechniqueGraph
    context: Context
    game: str | None = None
    braking_assist: int | None = None
    channels: Mapping[Channel, ChannelStatus] = field(init=False)
    _fits: dict[str, Fit] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.channels = channel_status(self.game)

    # ------------------------------------------------------------------ fit
    def holds(self, cid: str) -> bool:
        return self.graph.holds(cid, self.context)

    def _state(self, cid: str) -> str:
        """What the Context says for a condition ("gearbox not known", "skill intermediate")."""
        c = self.graph.get(cid, Condition)
        if c is None:
            return f"{cid} not known"
        if c.key is not None:
            return _value_words(c.key, _context_value(self.context, c.key))
        parts = [self._state(x) for x in (c.all_of or c.any_of)]
        return ", ".join(dict.fromkeys(parts))

    def _name(self, cid: str) -> str:
        c = self.graph.get(cid, Condition)
        return c.name if c is not None else cid

    def _conditions(self, when: Sequence[str], any_: Sequence[str]) -> list[str]:
        """Reasons the conditions fail (empty = they fit)."""
        out = [f"Only for: {self._name(c)} ({self._state(c)})" for c in when if not self.holds(c)]
        if any_ and not any(self.holds(c) for c in any_):
            names = [self._name(c) for c in any_]
            either = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]
            states = ", ".join(dict.fromkeys(self._state(c) for c in any_))
            out.append(f"Only for: {either} ({states})")
        return out

    def _missing(self, signals: Sequence[str]) -> list[str]:
        """Channels the game does not send among ``signals``' (in words, once each)."""
        out: dict[str, None] = {}
        for sid in signals:
            s = self.graph.get(sid, Signal)
            for ch in s.channels if s is not None else ():
                if self.channels.get(ch) == "not_sent":
                    out[CHANNEL_WORDS.get(ch, ch)] = None
        return list(out)

    def _not_sent(self, words: Sequence[str]) -> str:
        what = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " or " + words[-1]
        return f"{game_label(self.game)} does not send {what}"

    def fit(self, node: Node | str) -> Fit:
        """Whether a condition, signal, technique, fault, cause or advice node fits this driver (module docstring);
        any other node (phase, constraint, source) always does."""
        n = self.graph.node(node) if isinstance(node, str) else node
        if n is None:
            return Fit(False, "not in the technique graph")
        hit = self._fits.get(n.id)
        if hit is None:
            hit = self._fit(n)
            self._fits[n.id] = hit
        return hit

    def _fit(self, n: Node) -> Fit:
        reasons: list[str] = []
        if isinstance(n, Condition):
            if not self.holds(n.id):
                reasons.append(self._state(n.id))
        elif isinstance(n, Signal):
            missing = self._missing([n.id])
            if missing:
                reasons.append(self._not_sent(missing))
        elif isinstance(n, Technique):
            reasons += self._conditions(n.applies_when, n.applies_any)
        elif isinstance(n, Fault):
            reasons += self._conditions(n.applies_when, n.applies_any)
            missing = self._missing(n.signals)
            if missing:
                reasons.append(self._not_sent(missing))
        elif isinstance(n, Cause):
            reasons += self._conditions(n.applies_when, n.applies_any)
            reasons += self._cause_reasons(n)
        elif isinstance(n, Advice):
            owner = self.fit(n.for_id)
            if not owner.applies:
                reasons.append(f"{n.for_id} does not apply ({owner.why_not})")
            if n.skill != "any" and n.skill != self.context.skill:
                reasons.append(f"For {SKILL_WORDS[n.skill]} ({_value_words('skill', self.context.skill)})")
            if n.style is not None and n.style != self.context.braking_style:
                reasons.append(
                    f"For {STYLE_WORDS[n.style]} ({_value_words('braking_style', self.context.braking_style)})"
                )
        return Fit(False, "; ".join(reasons)) if reasons else FITS

    def _cause_reasons(self, c: Cause) -> list[str]:
        alls = [d.signal for d in c.discriminators if d.need == "all"]
        anys = [d.signal for d in c.discriminators if d.need == "any"]
        missing = self._missing(alls)
        if anys and all(self._missing([s]) for s in anys):
            missing += [w for w in self._missing(anys) if w not in missing]
        return [self._not_sent(missing)] if missing else []

    # ------------------------------------------------------------------ advice
    def _advice_for(self, node_id: str) -> list[Advice]:
        """The node's advice that fits this driver's skill and style, best first: a style match, then the driver's
        skill, then ``any`` (file order breaks ties)."""
        ctx = self.context
        fitting = [
            a
            for a in self.graph.advice_for(node_id)
            if (a.skill == "any" or a.skill == ctx.skill) and (a.style is None or a.style == ctx.braking_style)
        ]
        return sorted(fitting, key=lambda a: (a.style is None, a.skill == "any"))

    def advice(self, node_id: str) -> dict[str, Any] | None:
        """``{radio, screen, review, ids: {form: advice id}, tailored: {form: bool}}`` for a fault or cause, each form
        from the best advice that has it; None when no advice fits. ``tailored``: the form's advice is written for the
        driver's skill or braking style (not the ``any`` wording), which Review shows as an explanation under the
        coach's own text."""
        ranked = self._advice_for(node_id)
        if not ranked:
            return None
        out: dict[str, Any] = {}
        ids: dict[str, str | None] = {}
        tailored: dict[str, bool] = {}
        assisted = self.braking_assist is not None and self.braking_assist >= 1
        for form in FORMS:
            a = next((x for x in ranked if getattr(x, form) is not None), None)
            text = getattr(a, form) if a is not None else None
            if form == "review" and a is not None and a.style is not None and assisted and text:
                text = f"{text} {ASSIST_CAVEAT}"  # the style was read partly from the game's braking
            out[form] = text
            ids[form] = a.id if a is not None else None
            tailored[form] = a is not None and (a.skill != "any" or a.style is not None)
        out["ids"] = ids
        out["tailored"] = tailored
        return out

    # ------------------------------------------------------------------ causes
    def causes(self, fault: Fault, read: Reader | None) -> list[dict[str, Any]]:
        """The fault's causes its measured values name (``graph.Discriminator.holds``; module docstring), in graph
        order, each with its evidence and advice. ``read`` None = nothing measured: no cause."""
        if read is None:
            return []
        out: list[dict[str, Any]] = []
        for cid in fault.causes:
            c = self.graph.get(cid, Cause)
            if c is None or not self.fit(c).applies:
                continue
            held: list[tuple[Discriminator, object]] = []
            named = True
            any_hit = False
            for d in c.discriminators:
                s = self.graph.get(d.signal, Signal)
                v = _py(read(s)) if s is not None else None
                if d.holds(v):
                    held.append((d, v))
                    any_hit = any_hit or d.need == "any"
                elif d.need == "all":
                    named = False
                    break
            if not named or (any(d.need == "any" for d in c.discriminators) and not any_hit):
                continue
            out.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "tier": c.tier,
                    "discriminates": c.discriminates,
                    "evidence": [
                        {
                            "signal": d.signal,
                            "test": d.test,
                            "value": _round(v),
                            "unit": s.unit if (s := self.graph.get(d.signal, Signal)) is not None else None,
                        }
                        for d, v in held
                    ],
                    "advice": self.advice(c.id),
                }
            )
        return out

    # ------------------------------------------------------------------ observations
    def annotate(self, obs: Mapping[str, Any], read: Reader | None = None) -> dict[str, Any] | None:
        """The ``knowledge`` annotation of one observation (module docstring); None without a graph fault for its
        kind. ``read``: the corner's signal values on that lap (``LapSignals.reader``), for its causes."""
        if not self.graph.valid:
            return None
        kind = obs.get("kind")
        fault = self.graph.fault_for_kind(kind) if isinstance(kind, str) else None
        if fault is None:
            return None
        fit = self.fit(fault)
        return {
            "fault": fault.id,
            "name": fault.name,
            "status": fault.status,
            "tier": fault.tier,
            "applies": fit.applies,
            "why_not": fit.why_not,
            "causes": self.causes(fault, read),
            "advice": self.advice(fault.id),
            "digest": self.graph.digest,
        }

    def annotate_all(self, observations: Sequence[dict[str, Any]], signals: LapSignals | None) -> None:
        """Annotate a lap's observation dicts in place (``knowledge`` key)."""
        for o in observations:
            o["knowledge"] = self.annotate(o, signals.reader(o.get("corner")) if signals is not None else None)

    def node_fits(self) -> dict[str, Fit]:
        """Every condition, signal, technique, fault, cause and advice node's fit (the session API)."""
        g = self.graph
        nodes: list[Node] = [*g.conditions, *g.signals, *g.techniques, *g.faults, *g.causes, *g.advice]
        return {n.id: self.fit(n) for n in nodes}


def reasons(k: object) -> list[Mapping[str, Any]]:
    """The annotation's causes that tell their fault apart (``discriminates`` true), in order: the only ones said as
    the reason. A cause without the flag (an older annotation) is not one."""
    causes = k.get("causes") if isinstance(k, Mapping) else None
    return [
        c for c in (causes if isinstance(causes, list) else ()) if isinstance(c, Mapping) and c.get("discriminates")
    ]


def slim(k: object) -> dict[str, Any] | None:
    """The coach block's copy of an annotation (``coach.selection.slim``; every ``/ws/live`` snapshot carries the coach
    block): the annotation's shape with only the causes that tell their fault apart (``reasons``: the coach card says
    no other), each cause's evidence as its measured values (``{signal, value, unit}``) without the plain-words test,
    which the full annotation in the lap notification and Review's analysis carry with every measured cause."""
    if not isinstance(k, Mapping):
        return None
    adv = k.get("advice")
    return {
        "fault": k.get("fault"),
        "applies": k.get("applies"),
        "why_not": k.get("why_not"),
        "causes": [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "discriminates": True,
                "evidence": [
                    {"signal": e.get("signal"), "value": e.get("value"), "unit": e.get("unit")}
                    for e in c.get("evidence") or ()
                    if isinstance(e, Mapping)
                ],
                "screen": _cause_screen(c),
            }
            for c in reasons(k)
        ],
        "advice": {f: adv.get(f) for f in FORMS} if isinstance(adv, Mapping) else None,
    }


def card_slim(k: object) -> dict[str, Any] | None:
    """The snapshot observations' copy of an annotation (``core.live``; twenty snapshots a second): only what the
    coach card reads when it falls back to an observation - whether the point fits the driver and the screen line of
    the first measured cause that tells its fault apart (``reasons``). The coach block carries ``slim``; the lap
    notification and Review the full annotation."""
    if not isinstance(k, Mapping):
        return None
    first = next(iter(reasons(k)), None)
    return {
        "fault": k.get("fault"),
        "applies": k.get("applies"),
        "causes": []
        if first is None
        else [
            {"id": first.get("id"), "name": first.get("name"), "discriminates": True, "screen": _cause_screen(first)}
        ],
    }


def _cause_screen(c: Mapping[str, Any]) -> object:
    adv = c.get("advice")
    return adv.get("screen") if isinstance(adv, Mapping) else c.get("screen")
