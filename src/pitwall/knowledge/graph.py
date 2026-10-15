"""Technique knowledge graph: good technique in each phase of a corner, the faults Pitwall can see in telemetry, their
causes and what to say about them - every piece with WHEN it applies and WHERE it comes from.

Why a graph (spec: technique knowledge graph, section 1): a tester's brief (Ed, 2026-10-14) describes the textbook
corner - straight-line braking, coasting to the apex - while the owner's fastest F1 25 laps trail-brake into 40 of 41
braking corners. Neither is wrong; each fits some drivers and cars. So every technique, fault, cause and piece of
advice is a node that says when it applies (``applies_when``: all of these conditions, ``applies_any``: at least one;
conditions are predicates over the driver's Context - skill, braking style, car, gearbox ...), and Pitwall can coach
any driver within what fits them.

Data, not code: the nodes live in TOML files in ``graph/`` next to this module (read with the standard library's
``tomllib``), one file per node type by convention (``phases.toml``, ``techniques.toml`` ...); any file may hold any
node tables (``[[technique]]``, ``[[fault]]`` ...) and every ``*.toml`` there is loaded. docs/knowledge.md is the
contributor guide (the exact schema, the canonical ids, how to add a source); people extend knowledge there without
touching this module.

Node types (``NODE_TYPES``; the TOML table is the type's name):

* ``phase``      the six phases of a corner (``PHASE_IDS``, in driving order).
* ``condition``  a predicate over the Context (``key`` / ``op`` / ``value``), or ``all_of`` / ``any_of`` others.
* ``technique``  how to drive a phase, when it applies, its alternatives and the signals that measure it.
* ``signal``     a measured value: the dataclass field that holds it (``code``) and the channels it needs.
* ``fault``      something that goes wrong. ``status`` live = a coaching rule says it today (``kind``, the
                 ``Observation.kind``, equal to the id); experimental / planned / context_only otherwise.
* ``cause``      why a fault happens and the evidence that tells it apart (``discriminators``).
* ``advice``     what to say about a fault or cause: radio, screen and review texts, by skill and braking style.
* ``constraint`` a rule every text obeys: forbidden phrasings, e.g. no "brake later" outside praise.
* ``source``     where knowledge came from: a book, a web page, Ed's brief, a Pitwall measurement.

Evidence tiers (``TIERS``, ``TIER_MEANING``): ``expert`` (published coaching knowledge), ``brief`` (Ed's brief and
checklist), ``synthetic``, ``recorded`` (measured by Pitwall on recorded laps), ``live`` (running in Pitwall and seen
working with a real game) and ``design`` (Pitwall's own rules and definitions: conditions, constraints). A node's
tier must be one of its sources' tiers, so expert or brief content is never presented as validated by Pitwall. An
edge carries the tier and sources of the node that makes its claim (``Edge``).

Validation (``parse_graph``), all problems reported at once: snake_case ids unique across the graph; known fields
only, with the right types; every reference resolves to a node of the right type and mirrored edges agree (a fault's
``causes`` and the causes' ``explains``; ``advice`` and the advice's ``for``; ``alternatives`` both ways); the six
phases; condition keys and values from ``CONTEXT_VALUES``, no condition cycles; every signal's ``code`` names a real
dataclass field (``SIGNAL_CLASSES``) and its channels are known (``CHANNEL_FIELDS``); a live fault's ``kind`` is a
coaching kind (``analysis.coaching.COACHING_KINDS``) and its signals are computed; thresholds name numeric constants;
advice length limits; every user-facing text passes every constraint; canonical ids have their type.

A broken graph raises ``GraphError`` (listing every problem) from ``load_graph_dir``. The app's ``load_graph()``
(cached) logs the problems instead and returns an empty graph (``valid`` False): Pitwall starts and coaches as before
without it. Tests make ``load_graph()`` raise (``set_strict``, tests/conftest.py).

Deterministic data, no LLM: the AI engineer may explain these nodes, never invent one.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import math
import re
import tomllib
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Literal, TypeVar, cast, get_args

log = logging.getLogger(__name__)

Tier = Literal["expert", "brief", "synthetic", "recorded", "live", "design"]
NodeType = Literal["phase", "condition", "technique", "signal", "fault", "cause", "advice", "constraint", "source"]
FaultStatus = Literal["live", "experimental", "planned", "context_only"]
Relative = Literal["reference", "absolute"]
AdviceSkill = Literal["beginner", "intermediate", "advanced", "any"]
AdviceKind = Literal["describe", "explain", "drill"]
BrakingStyle = Literal["trail", "straight_line", "mixed"]
ConditionOp = Literal["eq", "ne", "in", "true", "false"]
TestOp = Literal["lt", "le", "gt", "ge", "true", "false"]
Need = Literal["all", "any"]
Channel = Literal[
    "brake",
    "throttle",
    "steering",
    "clutch",
    "gear",
    "rpm",
    "speed",
    "g_lat",
    "g_lon",
    "wheel_slip",
    "yaw_rate",
    "body_slip",
    "position",
    "lap_distance",
]
EdgeRel = Literal[
    "in_phase",
    "applies_when",
    "applies_any",
    "alternative",
    "measured_by",
    "violates",
    "caused_by",
    "advice",
    "discriminated_by",
    "all_of",
    "any_of",
]

TIERS: tuple[Tier, ...] = get_args(Tier)
NODE_TYPES: tuple[NodeType, ...] = get_args(NodeType)
FAULT_STATUSES: tuple[FaultStatus, ...] = get_args(FaultStatus)
RELATIVES: tuple[Relative, ...] = get_args(Relative)
ADVICE_SKILLS: tuple[AdviceSkill, ...] = get_args(AdviceSkill)
ADVICE_KINDS: tuple[AdviceKind, ...] = get_args(AdviceKind)
BRAKING_STYLES: tuple[BrakingStyle, ...] = get_args(BrakingStyle)
CONDITION_OPS: tuple[ConditionOp, ...] = get_args(ConditionOp)
TEST_OPS: tuple[TestOp, ...] = get_args(TestOp)
NEEDS: tuple[Need, ...] = get_args(Need)
CHANNELS: tuple[Channel, ...] = get_args(Channel)

TIER_MEANING: Mapping[Tier, str] = {
    "expert": "published coaching knowledge, cited; not validated by Pitwall",
    "brief": "from Ed's brief, checklist or patches (Pitwall tester); not validated by Pitwall",
    "synthetic": "checked on generated telemetry only; never proof on a real game",
    "recorded": "measured by Pitwall on recorded real laps; the measurement is cited",
    "live": "running in Pitwall and seen working live with a real game",
    "design": "Pitwall's own rule or definition, not evidence",
}
# Only rules and definitions may be ``design``: knowledge about driving needs evidence.
DESIGN_TYPES: frozenset[NodeType] = frozenset({"condition", "constraint", "source"})

PHASE_IDS: tuple[str, ...] = ("approach", "braking", "turn_in", "mid_corner", "apex", "exit")

# The Context a condition may test (``pitwall.knowledge.context``, spec section 2): key -> its values, or None for a
# true/false key. None in a driver's Context = unknown, and unknown satisfies no condition (``Condition.holds``).
# skill = ``drivers.SKILL_LEVELS``, car_family = ``carclass.FAMILIES`` (a test keeps them equal).
CONTEXT_VALUES: Mapping[str, tuple[str, ...] | None] = {
    "skill": ("beginner", "intermediate", "advanced"),
    "braking_style": BRAKING_STYLES,
    "coasting": ("rare", "often"),
    "game": ("f1", "gt7", "forza", "ac", "acc"),
    "car_family": ("f1", "f2", "other"),
    "downforce": ("high", "medium", "low"),
    "abs": None,
    "traction_control": None,
    "gearbox": ("paddle_autoblip", "h_pattern", "auto"),
    "fuel_saving": None,
    "wet": None,
}
CONTEXT_KEYS: tuple[str, ...] = tuple(CONTEXT_VALUES)

# Channel -> the CarFrame fields it reads (``model.telemetry.CarFrame``). A signal lists the channels it needs; a
# channel a game does not send (its adapter's ``AdapterInfo.fields``) makes the signal unavailable for that game.
# ``position`` is the adapter's ground plane (two of the three, ``AdapterInfo.ground_plane``).
CHANNEL_FIELDS: Mapping[Channel, tuple[str, ...]] = {
    "brake": ("brake",),
    "throttle": ("throttle",),
    "steering": ("steering",),
    "clutch": ("clutch",),
    "gear": ("gear",),
    "rpm": ("rpm",),
    "speed": ("speed_kph",),
    "g_lat": ("g_lat",),
    "g_lon": ("g_lon",),
    "wheel_slip": ("wheel_slip_ratio",),
    "yaw_rate": ("yaw_rate_rps",),
    "body_slip": ("body_slip_rad",),
    "position": ("pos_x_m", "pos_y_m", "pos_z_m"),
    "lap_distance": ("lap_distance_m",),
}

# Classes a signal's ``code`` may name ("CornerMetrics.trail_brake_m"): class name -> module. Add a class here when a
# signal is computed somewhere new; the field must exist on it (``resolve_code``).
SIGNAL_CLASSES: Mapping[str, str] = {
    "CornerMetrics": "pitwall.analysis.compare",
    "CornerDelta": "pitwall.analysis.compare",
    "BrakingEvent": "pitwall.analysis.braking",
    "CornerSummary": "pitwall.core.session_analysis",
    "CornerInputs": "pitwall.technique.inputs",
    "SlipEvents": "pitwall.technique.inputs",
    "PhaseBalance": "pitwall.technique.balance",
    "CarFrame": "pitwall.model.telemetry",
}
SIGNAL_UNITS: tuple[str, ...] = ("m", "s", "km/h", "m/s", "g", "deg", "rpm", "fraction", "ratio", "count", "bool")

RADIO_MAX_WORDS = 8  # an advice's radio form: a few descriptive words, inside the radio's line budget
SCREEN_MAX_CHARS = 48  # = analysis.coaching.SHORT_MAX_CHARS: a glance on the Drive screen (a test keeps them equal)
REVIEW_MAX_CHARS = 320  # one or two plain sentences

# User-facing texts per node type: what constraints scan (``Constraint.scope`` picks the types). ``notes`` are for
# contributors and are not scanned; a cause's discriminator ``test`` and ``note`` are.
TEXT_FIELDS: Mapping[NodeType, tuple[str, ...]] = {
    "phase": ("name", "summary"),
    "condition": ("name", "summary"),
    "technique": ("name", "summary", "detail"),
    "signal": ("name", "summary"),
    "fault": ("name", "summary"),
    "cause": ("name", "summary"),
    "advice": ("name", "summary", "radio", "screen", "review"),
}
SCANNABLE_TYPES: tuple[NodeType, ...] = tuple(TEXT_FIELDS)

GRAPH_DIR = Path(str(resources.files("pitwall.knowledge") / "graph"))

# --- canonical ids: the graph's content is written against these (docs/knowledge.md says what each means). A node
# with one of them must have that type (a live fault must be live, a planned one must not); ``missing_canonical``
# lists the ones not written yet.
CANONICAL_TECHNIQUES: tuple[str, ...] = (
    "flat_to_brake_marker",
    "fast_brake_attack",
    "progressive_brake_release",
    "rev_match_downshift",
    "straight_line_braking",
    "trail_braking",
    "release_with_speed_to_spare",
    "single_smooth_turn_in",
    "coast_to_apex",
    "throttle_at_rotation",
    "commit_throttle_no_lift",
    "unwind_with_throttle",
    "use_track_width_exit",
    "consistent_brake_marker",
    "left_foot_braking",
    "fuel_save_lift_and_coast",
)
# The eight coaching kinds (``analysis.coaching.COACHING_KINDS``); exit_gain is praise (``positive``).
CANONICAL_LIVE_FAULTS: tuple[str, ...] = (
    "brake_early",
    "brake_late_overdrive",
    "overspeed_apex",
    "low_min_speed",
    "late_throttle",
    "coasting",
    "exit_gain",
    "incident",
)
# Ed's checklist and patch detectors, and the brief's faults: planned or experimental (not coached).
CANONICAL_PLANNED_FAULTS: tuple[str, ...] = (
    "double_hump",
    "slow_brake_attack",
    "abrupt_brake_release",
    "pedal_overlap",
    "lift_before_braking",
    "steering_sawing",
    "snatched_turn_in",
    "early_apex",
    "throttle_sawtooth",
    "stepped_throttle",
    "low_throttle_acceptance",
    "throttle_before_unwind",
    "unused_grip_exit",
    "missed_blip",
    "gear_change_while_cornering",
    "lap_scatter",
    "entry_understeer_from_release",
    "aero_crossover",
)
CANONICAL_CAUSES: tuple[str, ...] = (
    "over_braking",
    "early_turn_in",
    "low_grip",
    "traction_limited",
    "ready_earlier",
    "early_brake_release",
    "waiting_for_rotation",
    "carried_too_much_speed",
    "released_too_early_for_apex",
)

_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_SOURCE_DATE = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")
_MEASURED_DATE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
_URL = re.compile(r"^https?://\S+$")
_CODE = re.compile(r"^([A-Z][A-Za-z0-9]*)\.([a-z_][a-z0-9_]*)$")
_CONSTANT = re.compile(r"^(pitwall(?:\.[a-z_][a-z0-9_]*)+)\.([A-Z][A-Z0-9_]*)$")


class GraphError(ValueError):
    """The technique graph does not load: ``errors`` lists every problem (file, node and field)."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors: tuple[str, ...] = tuple(errors)
        listing = "\n".join(f"- {e}" for e in self.errors)
        super().__init__(f"{len(self.errors)} problem(s) in the technique graph:\n{listing}")


# ---------------------------------------------------------------------------------------------- nodes
@dataclass(frozen=True, slots=True, kw_only=True)
class Measurement:
    """A number Pitwall measured (a firing rate, a spread), when and from which source."""

    metric: str
    value: float
    unit: str
    date: str  # YYYY-MM-DD or YYYY-MM
    source: str  # source id
    note: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Discriminator:
    """Evidence that tells a cause apart: ``signal`` compared by ``op`` with ``value`` (lt/le/gt/ge), or tested true /
    false. A cause is named only when every ``need = "all"`` discriminator holds and, if it has ``need = "any"`` ones,
    at least one of those holds; an unmeasured signal holds nothing (unknown stays unknown). ``test`` says it in plain
    words."""

    signal: str
    test: str
    op: TestOp
    value: float | None = None
    need: Need = "all"
    note: str | None = None

    def holds(self, measured: object) -> bool:
        """Whether a measured value passes this test; None (not measured) never does."""
        if measured is None or isinstance(measured, str):
            return False
        if self.op == "true":
            return measured is True
        if self.op == "false":
            return measured is False
        if isinstance(measured, bool) or not isinstance(measured, int | float) or self.value is None:
            return False
        x = float(measured)
        if not math.isfinite(x):
            return False
        return {"lt": x < self.value, "le": x <= self.value, "gt": x > self.value, "ge": x >= self.value}[self.op]


@dataclass(frozen=True, slots=True, kw_only=True)
class Threshold:
    """A code constant a fault's rule uses (``pitwall.analysis.coaching.MIN_SPEED_KPH``) and its value at load."""

    name: str
    value: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Node:
    """Fields every node has. ``file`` is the graph file it came from (where to edit it)."""

    node_type: ClassVar[NodeType]
    id: str
    name: str
    summary: str
    tier: Tier
    sources: tuple[str, ...]
    notes: str | None = None
    file: str = ""

    @property
    def where(self) -> str:
        return f"{self.file}: {self.node_type} {self.id!r}"

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready, with the TOML field names (``for``) and the node ``type``."""
        out: dict[str, Any] = {"type": self.node_type}
        for f in fields(self):
            if f.metadata.get("payload", True):
                out[f.metadata.get("toml", f.name)] = _plain(getattr(self, f.name))
        return out


@dataclass(frozen=True, slots=True, kw_only=True)
class Phase(Node):
    node_type: ClassVar[NodeType] = "phase"
    order: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Condition(Node):
    """Atomic (``key`` ``op`` ``value``) or compound (``all_of`` / ``any_of`` other conditions)."""

    node_type: ClassVar[NodeType] = "condition"
    key: str | None = None
    op: ConditionOp | None = None
    value: str | tuple[str, ...] | None = None
    all_of: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()

    def holds(self, value: object) -> bool:
        """Whether this atomic condition holds for its key's ``value`` in a driver's Context. Unknown (None) never
        holds - not for ``ne`` or ``false`` either: an unknown trait or style satisfies nothing. A compound condition
        is evaluated by ``TechniqueGraph.holds``."""
        if value is None or self.key is None:
            return False
        if self.op == "true":
            return value is True
        if self.op == "false":
            return value is False
        if self.op == "eq":
            return value == self.value
        if self.op == "ne":
            return value != self.value
        if self.op == "in":
            return isinstance(self.value, tuple) and value in self.value
        return False


@dataclass(frozen=True, slots=True, kw_only=True)
class Technique(Node):
    node_type: ClassVar[NodeType] = "technique"
    phase: str
    detail: str
    applies_when: tuple[str, ...] = ()
    applies_any: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    measured_by: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Signal(Node):
    """``code`` None = not computed by Pitwall yet (only planned faults may rely on it)."""

    node_type: ClassVar[NodeType] = "signal"
    code: str | None
    unit: str
    channels: tuple[Channel, ...]
    noise: tuple[Measurement, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Fault(Node):
    node_type: ClassVar[NodeType] = "fault"
    phase: str
    status: FaultStatus
    relative: Relative
    kind: str | None = None
    positive: bool = False
    violates: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    thresholds: tuple[Threshold, ...] = ()
    applies_when: tuple[str, ...] = ()
    applies_any: tuple[str, ...] = ()
    causes: tuple[str, ...] = ()
    advice: tuple[str, ...] = ()
    measured: tuple[Measurement, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Cause(Node):
    node_type: ClassVar[NodeType] = "cause"
    explains: tuple[str, ...]
    discriminators: tuple[Discriminator, ...] = ()
    advice: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Advice(Node):
    """``radio`` / ``screen`` None = no such form (a review-only explanation). Texts describe what happened and what
    the driver's own faster laps did; numbers stay in the observation's own text (no placeholders)."""

    node_type: ClassVar[NodeType] = "advice"
    for_id: str = field(metadata={"toml": "for"})
    skill: AdviceSkill
    kind: AdviceKind
    review: str
    style: BrakingStyle | None = None
    radio: str | None = None
    screen: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Constraint(Node):
    """``forbidden`` regexes (case-insensitive) no user-facing text of the ``scope`` node types may match;
    ``except_praise``: praise (advice for a positive fault, the positive fault itself) is exempt."""

    node_type: ClassVar[NodeType] = "constraint"
    text: str
    forbidden: tuple[str, ...]
    scope: tuple[NodeType, ...] = ("advice",)
    except_praise: bool = False
    patterns: tuple[re.Pattern[str], ...] = field(default=(), repr=False, compare=False, metadata={"payload": False})

    def violations(self, text: str) -> list[str]:
        """The forbidden patterns ``text`` matches (empty = it passes)."""
        return [p.pattern for p in self.patterns if p.search(text)]


@dataclass(frozen=True, slots=True, kw_only=True)
class Source(Node):
    """``name`` defaults to the title, ``summary`` to the note; a source cites nothing (``sources`` empty)."""

    node_type: ClassVar[NodeType] = "source"
    title: str
    author: str
    note: str
    url: str | None = None
    date: str | None = None  # YYYY, YYYY-MM or YYYY-MM-DD; None = unknown


N = TypeVar("N", bound=Node)


@dataclass(frozen=True, slots=True)
class Edge:
    """A typed link between two nodes, with the tier and sources of the node that makes the claim: the cause for
    ``caused_by`` (it ``explains`` the fault), the advice for ``advice``, else the node that lists it."""

    src: str
    dst: str
    rel: EdgeRel
    tier: Tier
    sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"from": self.src, "to": self.dst, "rel": self.rel, "tier": self.tier, "sources": list(self.sources)}


def _plain(v: object) -> Any:
    if isinstance(v, tuple | list):
        return [_plain(x) for x in v]
    if is_dataclass(v) and not isinstance(v, type):
        return {k: _plain(x) for k, x in asdict(v).items()}
    return v


@dataclass(frozen=True, slots=True, eq=False)
class TechniqueGraph:
    """The loaded graph (phases in driving order; other nodes in file order). ``errors`` non-empty = it did not load
    and every tuple is empty (``valid`` False)."""

    phases: tuple[Phase, ...] = ()
    conditions: tuple[Condition, ...] = ()
    techniques: tuple[Technique, ...] = ()
    signals: tuple[Signal, ...] = ()
    faults: tuple[Fault, ...] = ()
    causes: tuple[Cause, ...] = ()
    advice: tuple[Advice, ...] = ()
    constraints: tuple[Constraint, ...] = ()
    sources: tuple[Source, ...] = ()
    files: tuple[str, ...] = ()
    digest: str | None = None  # of the files' bytes: changes whenever the knowledge does
    errors: tuple[str, ...] = ()
    by_id: Mapping[str, Node] = field(default_factory=lambda: MappingProxyType({}), repr=False)

    @property
    def valid(self) -> bool:
        return not self.errors

    @classmethod
    def empty(cls, errors: Sequence[str]) -> TechniqueGraph:
        """No knowledge: what the app runs with when the graph does not load."""
        return cls(errors=tuple(errors))

    def nodes(self) -> Iterator[Node]:
        yield from self.phases
        yield from self.conditions
        yield from self.techniques
        yield from self.signals
        yield from self.faults
        yield from self.causes
        yield from self.advice
        yield from self.constraints
        yield from self.sources

    def node(self, node_id: str) -> Node | None:
        return self.by_id.get(node_id)

    def get(self, node_id: str, cls: type[N]) -> N | None:
        """The node with this id when it is a ``cls``, else None."""
        n = self.by_id.get(node_id)
        return n if isinstance(n, cls) else None

    def fault_for_kind(self, kind: str) -> Fault | None:
        """The live fault of a coaching kind (``Observation.kind``), or None."""
        f = self.get(kind, Fault)
        return f if f is not None and f.kind == kind else None

    def advice_for(self, node_id: str) -> tuple[Advice, ...]:
        """The advice of a fault or cause (in its ``advice`` order)."""
        owner = self.by_id.get(node_id)
        ids = owner.advice if isinstance(owner, Fault | Cause) else ()
        return tuple(a for a in (self.get(i, Advice) for i in ids) if a is not None)

    def techniques_for(self, phase: str) -> tuple[Technique, ...]:
        return tuple(t for t in self.techniques if t.phase == phase)

    def holds(self, condition_id: str, context: object) -> bool:
        """Whether a condition holds in a driver's Context (a mapping or an object with the ``CONTEXT_KEYS`` as
        attributes; a missing key is unknown). Unknown never holds; an unknown condition id does not hold."""
        c = self.get(condition_id, Condition)
        if c is None:
            return False
        if c.all_of:
            return all(self.holds(x, context) for x in c.all_of)
        if c.any_of:
            return any(self.holds(x, context) for x in c.any_of)
        if c.key is None:
            return False
        value = context.get(c.key) if isinstance(context, Mapping) else getattr(context, c.key, None)
        return c.holds(value)

    def edges(self) -> tuple[Edge, ...]:
        out: list[Edge] = []

        def link(owner: Node, rel: EdgeRel, targets: Iterable[str]) -> None:
            out.extend(Edge(owner.id, t, rel, owner.tier, owner.sources) for t in targets)

        def claimed(src: str, rel: EdgeRel, claims: Iterable[str]) -> None:
            for t in claims:
                claimer = self.by_id.get(t)
                if claimer is not None:
                    out.append(Edge(src, t, rel, claimer.tier, claimer.sources))

        for c in self.conditions:
            link(c, "all_of", c.all_of)
            link(c, "any_of", c.any_of)
        for t in self.techniques:
            link(t, "in_phase", [t.phase])
            link(t, "applies_when", t.applies_when)
            link(t, "applies_any", t.applies_any)
            link(t, "alternative", t.alternatives)
            link(t, "measured_by", t.measured_by)
        for f in self.faults:
            link(f, "in_phase", [f.phase])
            link(f, "violates", f.violates)
            link(f, "measured_by", f.signals)
            link(f, "applies_when", f.applies_when)
            link(f, "applies_any", f.applies_any)
            claimed(f.id, "caused_by", f.causes)
            claimed(f.id, "advice", f.advice)
        for cause in self.causes:
            link(cause, "discriminated_by", dict.fromkeys(d.signal for d in cause.discriminators))
            claimed(cause.id, "advice", cause.advice)
        return tuple(out)

    def to_payload(self) -> dict[str, Any]:
        """The whole graph, JSON-ready: ``GET /api/technique/knowledge``."""
        groups: dict[str, Sequence[Node]] = {
            "phases": self.phases,
            "conditions": self.conditions,
            "techniques": self.techniques,
            "signals": self.signals,
            "faults": self.faults,
            "causes": self.causes,
            "advice": self.advice,
            "constraints": self.constraints,
            "sources": self.sources,
        }
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "digest": self.digest,
            "files": list(self.files),
            "tiers": dict(TIER_MEANING),
            "counts": {k: len(v) for k, v in groups.items()},
            **{k: [n.to_dict() for n in v] for k, v in groups.items()},
            "edges": [e.to_dict() for e in self.edges()],
        }


def missing_canonical(graph: TechniqueGraph) -> dict[str, tuple[str, ...]]:
    """Canonical ids with no node yet, by list (empty lists left out)."""
    lists = {
        "techniques": CANONICAL_TECHNIQUES,
        "live_faults": CANONICAL_LIVE_FAULTS,
        "planned_faults": CANONICAL_PLANNED_FAULTS,
        "causes": CANONICAL_CAUSES,
    }
    out = {k: tuple(i for i in ids if i not in graph.by_id) for k, ids in lists.items()}
    return {k: v for k, v in out.items() if v}


# ---------------------------------------------------------------------------------------------- code links
def resolve_code(code: str) -> str | None:
    """None when ``code`` ("CornerMetrics.trail_brake_m") names a field or property of a ``SIGNAL_CLASSES`` dataclass,
    else what is wrong."""
    m = _CODE.match(code)
    if m is None:
        return "must look like ClassName.field (e.g. CornerMetrics.trail_brake_m)"
    cls_name, attr = m.groups()
    module = SIGNAL_CLASSES.get(cls_name)
    if module is None:
        return f"unknown class {cls_name!r} (known: {', '.join(sorted(SIGNAL_CLASSES))}; add it to SIGNAL_CLASSES)"
    cls = getattr(importlib.import_module(module), cls_name, None)
    if not isinstance(cls, type) or not is_dataclass(cls):
        return f"{module}.{cls_name} is not a dataclass"
    if attr in {f.name for f in fields(cls)} or isinstance(getattr(cls, attr, None), property):
        return None
    return f"{cls_name} ({module}) has no field {attr!r}"


def resolve_constant(path: str) -> tuple[float | None, str | None]:
    """(value, None) for a numeric module constant named by its dotted path ("pitwall.analysis.coaching.
    MIN_SPEED_KPH"), else (None, what is wrong)."""
    m = _CONSTANT.match(path)
    if m is None:
        return None, "must be a dotted path to an UPPER_CASE constant (e.g. pitwall.analysis.coaching.MIN_SPEED_KPH)"
    module, name = m.groups()
    try:
        mod = importlib.import_module(module)
    except ImportError:
        return None, f"no module {module!r}"
    v = getattr(mod, name, None)
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None, f"{module} has no numeric constant {name!r}"
    return float(v), None


# ---------------------------------------------------------------------------------------------- parsing
class _Table:
    """One TOML table read with typed accessors. A problem is appended to ``errors`` (with ``where``) and marks the
    table not ``ok`` instead of raising, so one load reports every problem. Texts are whitespace-normalised (TOML
    multi-line strings read as one paragraph)."""

    def __init__(self, data: object, where: str, errors: list[str]) -> None:
        self.where = where
        self.errors = errors
        self.ok = isinstance(data, dict)
        self.data: Mapping[str, Any] = data if isinstance(data, dict) else {}
        self.used: set[str] = set()
        if not self.ok:
            errors.append(f"{where}: expected a table")

    def fail(self, key: str, msg: str) -> None:
        self.errors.append(f"{self.where}: {key}: {msg}")
        self.ok = False

    def raw(self, key: str) -> Any:
        self.used.add(key)
        return self.data.get(key)

    def has(self, key: str) -> bool:
        return key in self.data

    def text(self, key: str, *, required: bool = True) -> str | None:
        v = self.raw(key)
        if v is None:
            if required:
                self.fail(key, "missing (required)")
            return None
        if not isinstance(v, str) or not v.strip():
            self.fail(key, "must be a non-empty string")
            return None
        return " ".join(v.split())

    def strings(self, key: str, *, required: bool = False) -> tuple[str, ...]:
        """A list of strings, as written (ids, regexes, constant paths)."""
        v = self.raw(key)
        if v is None:
            if required:
                self.fail(key, "missing (required: a list)")
            return ()
        if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
            self.fail(key, "must be a list of non-empty strings")
            return ()
        if required and not v:
            self.fail(key, "must not be empty")
        if len(set(v)) != len(v):
            self.fail(key, "lists the same entry twice")
        return tuple(v)

    def choice(self, key: str, choices: Sequence[str], *, required: bool = True) -> str | None:
        v = self.raw(key)
        if v is None:
            if required:
                self.fail(key, f"missing (required: one of {', '.join(choices)})")
            return None
        if not isinstance(v, str) or v not in choices:
            self.fail(key, f"{v!r} is not one of {', '.join(choices)}")
            return None
        return v

    def choices(self, key: str, choices: Sequence[str], default: tuple[str, ...]) -> tuple[str, ...]:
        if not self.has(key):
            self.used.add(key)
            return default
        vals = self.strings(key, required=True)
        bad = [x for x in vals if x not in choices]
        if bad:
            self.fail(key, f"{', '.join(map(repr, bad))} not one of {', '.join(choices)}")
        return vals

    def flag(self, key: str, default: bool = False) -> bool:
        v = self.raw(key)
        if v is None:
            return default
        if not isinstance(v, bool):
            self.fail(key, "must be true or false")
            return default
        return v

    def integer(self, key: str) -> int:
        v = self.raw(key)
        if isinstance(v, bool) or not isinstance(v, int):
            self.fail(key, "missing (required: an integer)" if v is None else "must be an integer")
            return 0
        return v

    def number(self, key: str, *, required: bool = True) -> float | None:
        v = self.raw(key)
        if v is None:
            if required:
                self.fail(key, "missing (required: a number)")
            return None
        if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
            self.fail(key, "must be a finite number")
            return None
        return float(v)

    def tables(self, key: str) -> list[_Table]:
        v = self.raw(key)
        if v is None:
            return []
        if not isinstance(v, list):
            self.fail(key, "must be a list of tables")
            return []
        return [_Table(item, f"{self.where}: {key}[{i}]", self.errors) for i, item in enumerate(v)]

    def finish(self, subtables: Iterable[_Table] = ()) -> bool:
        """Report unknown fields; True when this table and its sub-tables read cleanly."""
        extra = sorted(set(self.data) - self.used)
        if extra:
            self.fail(", ".join(extra), "unknown field(s)")
        subs_ok = all([s.finish() for s in subtables])
        self.ok = self.ok and subs_ok
        return self.ok


def _measurements(t: _Table, key: str) -> tuple[tuple[Measurement, ...], list[_Table]]:
    subs = t.tables(key)
    out: list[Measurement] = []
    for s in subs:
        metric, value, unit = s.text("metric"), s.number("value"), s.text("unit")
        date, source, note = s.text("date"), s.text("source"), s.text("note", required=False)
        if date is not None and not _MEASURED_DATE.match(date):
            s.fail("date", f"{date!r} is not YYYY-MM-DD or YYYY-MM")
        if metric and value is not None and unit and date and source:
            out.append(Measurement(metric=metric, value=value, unit=unit, date=date, source=source, note=note))
    return tuple(out), subs


def _base(t: _Table, *, name: bool = True, summary: bool = True, sources: bool = True) -> dict[str, Any]:
    """The fields every node has (``name`` / ``summary`` / ``sources`` False: optional for this type)."""
    node_id = t.text("id") or ""
    if node_id and not _ID.match(node_id):
        t.fail("id", f"{node_id!r} is not snake_case (a-z, 0-9 and single underscores, starting with a letter)")
    return {
        "id": node_id,
        "name": t.text("name", required=name) or "",
        "summary": t.text("summary", required=summary) or "",
        "tier": t.choice("tier", TIERS),
        "sources": t.strings("sources", required=sources),
        "notes": t.text("notes", required=False),
    }


def _phase(t: _Table) -> Phase | None:
    kw = _base(t)
    order = t.integer("order")
    return Phase(**kw, order=order) if t.finish() else None


def _condition(t: _Table) -> Condition | None:
    kw = _base(t, sources=False)
    atomic = any(t.has(k) for k in ("key", "op", "value"))
    all_of, any_of = t.strings("all_of"), t.strings("any_of")
    if atomic + bool(all_of) + bool(any_of) != 1:
        t.fail("key", "a condition is exactly one of: key + op (+ value), all_of = [...], any_of = [...]")
    key: str | None = None
    op: str | None = None
    value: str | tuple[str, ...] | None = None
    if atomic:
        key = t.choice("key", CONTEXT_KEYS)
        op = t.choice("op", CONDITION_OPS)
        raw = t.raw("value")
        domain = CONTEXT_VALUES.get(key) if key is not None else None
        if key is not None and op is not None:
            if domain is None:
                if op not in ("true", "false"):
                    t.fail("op", f'{key} is true/false: use op = "true" or "false"')
                elif raw is not None:
                    t.fail("value", f"op {op!r} takes no value")
            elif op in ("true", "false"):
                t.fail("op", f"{key} is one of {', '.join(domain)}: use eq, ne or in")
            elif op == "in":
                if not isinstance(raw, list) or not raw or not all(isinstance(x, str) and x in domain for x in raw):
                    t.fail("value", f"op 'in' takes a list of {', '.join(domain)}")
                else:
                    value = tuple(raw)
            elif not isinstance(raw, str) or raw not in domain:
                t.fail("value", f"{raw!r} is not one of {', '.join(domain)}")
            else:
                value = raw
    if not t.finish():
        return None
    return Condition(**kw, key=key, op=cast(ConditionOp | None, op), value=value, all_of=all_of, any_of=any_of)


def _technique(t: _Table) -> Technique | None:
    kw = _base(t)
    tech: dict[str, Any] = {
        "phase": t.text("phase") or "",
        "detail": t.text("detail") or "",
        "applies_when": t.strings("applies_when"),
        "applies_any": t.strings("applies_any"),
        "alternatives": t.strings("alternatives"),
        "measured_by": t.strings("measured_by"),
    }
    return Technique(**kw, **tech) if t.finish() else None


def _signal(t: _Table) -> Signal | None:
    kw = _base(t)
    code = t.text("code", required=False)
    if code is not None and (problem := resolve_code(code)) is not None:
        t.fail("code", f"{code!r}: {problem}")
    unit = t.choice("unit", SIGNAL_UNITS)
    channels = t.choices("channels", CHANNELS, ())
    if not channels:
        t.fail("channels", "missing (required: the CarFrame channels it needs)")
    noise, subs = _measurements(t, "noise")
    if not t.finish(subs):
        return None
    return Signal(**kw, code=code, unit=unit or "", channels=cast(tuple[Channel, ...], channels), noise=noise)


def _fault(t: _Table) -> Fault | None:
    kw = _base(t)
    thresholds: list[Threshold] = []
    for path in t.strings("thresholds"):
        value, problem = resolve_constant(path)
        if value is None:
            t.fail("thresholds", f"{path!r}: {problem}")
        else:
            thresholds.append(Threshold(name=path, value=value))
    status = t.choice("status", FAULT_STATUSES)
    relative = t.choice("relative", RELATIVES)
    rest: dict[str, Any] = {
        "phase": t.text("phase") or "",
        "kind": t.text("kind", required=False),
        "positive": t.flag("positive"),
        "violates": t.strings("violates"),
        "signals": t.strings("signals"),
        "applies_when": t.strings("applies_when"),
        "applies_any": t.strings("applies_any"),
        "causes": t.strings("causes"),
        "advice": t.strings("advice"),
    }
    measured, subs = _measurements(t, "measured")
    if not t.finish(subs):
        return None
    return Fault(
        **kw,
        **rest,
        status=cast(FaultStatus, status),
        relative=cast(Relative, relative),
        thresholds=tuple(thresholds),
        measured=measured,
    )


def _cause(t: _Table) -> Cause | None:
    kw = _base(t)
    explains = t.strings("explains", required=True)
    advice = t.strings("advice")
    subs = t.tables("discriminators")
    discs: list[Discriminator] = []
    for s in subs:
        signal, test = s.text("signal"), s.text("test")
        op = s.choice("op", TEST_OPS)
        value = s.number("value", required=op in ("lt", "le", "gt", "ge"))
        if op in ("true", "false") and value is not None:
            s.fail("value", f"op {op!r} takes no value")
        need = s.choice("need", NEEDS, required=False) or "all"
        note = s.text("note", required=False)
        if signal and test and op:
            discs.append(
                Discriminator(
                    signal=signal, test=test, op=cast(TestOp, op), value=value, need=cast(Need, need), note=note
                )
            )
    if not t.finish(subs):
        return None
    return Cause(**kw, explains=explains, discriminators=tuple(discs), advice=advice)


def _advice(t: _Table) -> Advice | None:
    kw = _base(t, name=False, summary=False)
    for_id = t.text("for") or ""
    skill = t.choice("skill", ADVICE_SKILLS)
    kind = t.choice("kind", ADVICE_KINDS)
    style = t.choice("style", BRAKING_STYLES, required=False)
    radio, screen = t.text("radio", required=False), t.text("screen", required=False)
    review = t.text("review") or ""
    if radio is not None and len(radio.split()) > RADIO_MAX_WORDS:
        t.fail("radio", f"{len(radio.split())} words (at most {RADIO_MAX_WORDS})")
    if screen is not None and len(screen) > SCREEN_MAX_CHARS:
        t.fail("screen", f"{len(screen)} characters (at most {SCREEN_MAX_CHARS})")
    if len(review) > REVIEW_MAX_CHARS:
        t.fail("review", f"{len(review)} characters (at most {REVIEW_MAX_CHARS}: one or two plain sentences)")
    if not t.finish():
        return None
    kw["name"] = kw["name"] or f"{for_id}: {kind} ({skill})"
    kw["summary"] = kw["summary"] or review
    return Advice(
        **kw,
        for_id=for_id,
        skill=cast(AdviceSkill, skill),
        kind=cast(AdviceKind, kind),
        style=cast(BrakingStyle | None, style),
        radio=radio,
        screen=screen,
        review=review,
    )


def _constraint(t: _Table) -> Constraint | None:
    kw = _base(t)
    text = t.text("text") or ""
    forbidden = t.strings("forbidden", required=True)
    patterns: list[re.Pattern[str]] = []
    for p in forbidden:
        try:
            patterns.append(re.compile(p, re.IGNORECASE))
        except re.error as e:
            t.fail("forbidden", f"{p!r} is not a valid regular expression ({e})")
    scope = t.choices("scope", SCANNABLE_TYPES, ("advice",))
    except_praise = t.flag("except_praise")
    if not t.finish():
        return None
    return Constraint(
        **kw,
        text=text,
        forbidden=forbidden,
        scope=cast(tuple[NodeType, ...], scope),
        except_praise=except_praise,
        patterns=tuple(patterns),
    )


def _source(t: _Table) -> Source | None:
    kw = _base(t, name=False, summary=False, sources=False)
    if kw["sources"]:
        t.fail("sources", "a source cites nothing")
    title, author, note = t.text("title") or "", t.text("author") or "", t.text("note") or ""
    url, date = t.text("url", required=False), t.text("date", required=False)
    if url is not None and not _URL.match(url):
        t.fail("url", f"{url!r} is not an http(s) URL")
    if date is not None and not _SOURCE_DATE.match(date):
        t.fail("date", f"{date!r} is not YYYY, YYYY-MM or YYYY-MM-DD")
    if not t.finish():
        return None
    kw["name"] = kw["name"] or title
    kw["summary"] = kw["summary"] or note
    return Source(**kw, title=title, author=author, note=note, url=url, date=date)


_PARSERS: Mapping[str, Callable[[_Table], Node | None]] = {
    "phase": _phase,
    "condition": _condition,
    "technique": _technique,
    "signal": _signal,
    "fault": _fault,
    "cause": _cause,
    "advice": _advice,
    "constraint": _constraint,
    "source": _source,
}


# ---------------------------------------------------------------------------------------------- validation
def _is_praise(n: Node, by_id: Mapping[str, Node]) -> bool:
    """Praise: a positive fault, a cause that only explains positive faults, advice for either."""
    if isinstance(n, Fault):
        return n.positive
    if isinstance(n, Cause):
        explained = [by_id.get(f) for f in n.explains]
        return bool(explained) and all(isinstance(f, Fault) and f.positive for f in explained)
    if isinstance(n, Advice):
        target = by_id.get(n.for_id)
        return target is not None and not isinstance(target, Advice) and _is_praise(target, by_id)
    return False


def _texts(n: Node) -> Iterator[tuple[str, str]]:
    seen: set[str] = set()
    for name in TEXT_FIELDS.get(n.node_type, ()):
        v = getattr(n, name)
        if isinstance(v, str) and v not in seen:  # an advice's summary defaults to its review: scan it once
            seen.add(v)
            yield name, v
    if isinstance(n, Cause):
        for i, d in enumerate(n.discriminators):
            yield f"discriminators[{i}].test", d.test
            if d.note:
                yield f"discriminators[{i}].note", d.note


def _validate(nodes: Sequence[Node]) -> list[str]:
    from pitwall.analysis.coaching import COACHING_KINDS, POSITIVE_KINDS  # lazy: the graph loads before coaching

    errors: list[str] = []
    by_id: dict[str, Node] = {}
    for n in nodes:
        if n.id in by_id:
            errors.append(f"{n.where}: duplicate id (also {by_id[n.id].where})")
        else:
            by_id[n.id] = n

    def ref(owner: Node, label: str, ids: Iterable[str], *want: type[Node]) -> None:
        for x in ids:
            target = by_id.get(x)
            if target is None:
                errors.append(f"{owner.where}: {label}: unknown id {x!r}")
            elif not isinstance(target, want):
                names = " or ".join(w.node_type for w in want)
                errors.append(f"{owner.where}: {label}: {x!r} is a {target.node_type}, not a {names}")

    def mirrored(owner: Node, label: str, ids: Iterable[str], cls: type[N], back: str, back_label: str) -> None:
        """Each listed node of ``cls`` must list ``owner`` back in its ``back`` field."""
        for x in ids:
            target = by_id.get(x)
            if not isinstance(target, cls):
                continue  # reported by ref()
            values = getattr(target, back)
            if owner.id not in (values if isinstance(values, tuple) else (values,)):
                errors.append(f"{owner.where}: {label} lists {x!r}, but {target.where} {back_label}")

    phase_ids = [n.id for n in nodes if isinstance(n, Phase)]
    if sorted(phase_ids) != sorted(PHASE_IDS):
        errors.append(f"phases: expected exactly {', '.join(PHASE_IDS)}; found {', '.join(phase_ids) or 'none'}")

    for n in nodes:
        ref(n, "sources", n.sources, Source)
        if n.tier == "design" and n.node_type not in DESIGN_TYPES:
            errors.append(f"{n.where}: tier 'design' is only for conditions, constraints and sources")
        cited = {s.tier for s in (by_id.get(x) for x in n.sources) if isinstance(s, Source)}
        if not isinstance(n, Source) and n.tier != "design" and n.tier not in cited:
            errors.append(
                f"{n.where}: tier {n.tier!r} needs a source of that tier (its sources are "
                f"{', '.join(sorted(cited)) or 'none'})"
            )
        if isinstance(n, Phase) and n.id in PHASE_IDS and n.order != PHASE_IDS.index(n.id) + 1:
            errors.append(f"{n.where}: order must be {PHASE_IDS.index(n.id) + 1} (driving order: {PHASE_IDS})")
        elif isinstance(n, Condition):
            ref(n, "all_of", n.all_of, Condition)
            ref(n, "any_of", n.any_of, Condition)
        elif isinstance(n, Technique):
            ref(n, "phase", [n.phase], Phase)
            ref(n, "applies_when", n.applies_when, Condition)
            ref(n, "applies_any", n.applies_any, Condition)
            ref(n, "alternatives", n.alternatives, Technique)
            ref(n, "measured_by", n.measured_by, Signal)
            if n.id in n.alternatives:
                errors.append(f"{n.where}: alternatives: a technique is not its own alternative")
            mirrored(n, "alternatives", n.alternatives, Technique, "alternatives", "does not list it as an alternative")
        elif isinstance(n, Signal):
            for m in n.noise:
                ref(n, "noise source", [m.source], Source)
        elif isinstance(n, Fault):
            ref(n, "phase", [n.phase], Phase)
            ref(n, "violates", n.violates, Technique)
            ref(n, "signals", n.signals, Signal)
            ref(n, "applies_when", n.applies_when, Condition)
            ref(n, "applies_any", n.applies_any, Condition)
            ref(n, "causes", n.causes, Cause)
            ref(n, "advice", n.advice, Advice)
            mirrored(n, "causes", n.causes, Cause, "explains", "does not list it in explains")
            mirrored(n, "advice", n.advice, Advice, "for_id", "is not for it")
            for m in n.measured:
                ref(n, "measured source", [m.source], Source)
            if n.kind is not None:
                if n.kind not in COACHING_KINDS:
                    errors.append(f"{n.where}: kind {n.kind!r} is not a coaching kind ({', '.join(COACHING_KINDS)})")
                if n.kind != n.id:
                    errors.append(f"{n.where}: a coaching fault's id is its kind ({n.kind!r})")
                if n.status != "live":
                    errors.append(f"{n.where}: a fault with a coaching kind is live")
                if n.positive != (n.kind in POSITIVE_KINDS):
                    errors.append(f"{n.where}: positive must be {n.kind in POSITIVE_KINDS} for kind {n.kind!r}")
            elif n.status == "live":
                errors.append(f"{n.where}: a live fault names its coaching kind (kind = one of {COACHING_KINDS})")
            if n.status == "live":
                for s in n.signals:
                    sig = by_id.get(s)
                    if isinstance(sig, Signal) and sig.code is None:
                        errors.append(f"{n.where}: live, but signal {s!r} is not computed (no code)")
        elif isinstance(n, Cause):
            ref(n, "explains", n.explains, Fault)
            ref(n, "advice", n.advice, Advice)
            mirrored(n, "explains", n.explains, Fault, "causes", "does not list it in causes")
            mirrored(n, "advice", n.advice, Advice, "for_id", "is not for it")
            for i, d in enumerate(n.discriminators):
                ref(n, f"discriminators[{i}].signal", [d.signal], Signal)
        elif isinstance(n, Advice):
            ref(n, "for", [n.for_id], Fault, Cause)
            owner = by_id.get(n.for_id)
            if isinstance(owner, Fault | Cause) and n.id not in owner.advice:
                errors.append(f"{n.where}: for {n.for_id!r}, but {owner.where} does not list it in advice")

    errors += _condition_cycles([n for n in nodes if isinstance(n, Condition)])

    for c in (n for n in nodes if isinstance(n, Constraint)):
        for n in nodes:
            if n.node_type not in c.scope or (c.except_praise and _is_praise(n, by_id)):
                continue
            for label, text in _texts(n):
                hits = c.violations(text)
                if hits:
                    errors.append(f"{n.where}: {label}: {text!r} breaks constraint {c.id!r} ({c.text}): {hits[0]}")

    for ids, cls in ((CANONICAL_TECHNIQUES, Technique), (CANONICAL_CAUSES, Cause)):
        for x in ids:
            if x in by_id and not isinstance(by_id[x], cls):
                errors.append(f"{by_id[x].where}: {x!r} is a canonical {cls.node_type} id")
    for ids, live in ((CANONICAL_LIVE_FAULTS, True), (CANONICAL_PLANNED_FAULTS, False)):
        for x in ids:
            found = by_id.get(x)
            if found is not None and (not isinstance(found, Fault) or (found.status == "live") != live):
                want = "a live fault" if live else "a fault that is not live (planned, experimental or context_only)"
                errors.append(f"{found.where}: {x!r} is canonically {want}")
    return errors


def _condition_cycles(conditions: Sequence[Condition]) -> list[str]:
    deps = {c.id: c.all_of + c.any_of for c in conditions}
    errors: list[str] = []
    done: set[str] = set()

    def visit(cid: str, path: tuple[str, ...]) -> None:
        if cid in path:
            errors.append(f"conditions: cycle {' -> '.join((*path[path.index(cid) :], cid))}")
            return
        if cid in done:
            return
        for d in deps.get(cid, ()):
            visit(d, (*path, cid))
        done.add(cid)

    for cid in deps:
        visit(cid, ())
    return errors


def parse_graph(
    docs: Mapping[str, Mapping[str, Any]], *, digest: str | None = None, errors: Sequence[str] = ()
) -> TechniqueGraph:
    """Build and validate a graph from parsed TOML documents (file name -> document). Raises ``GraphError`` with every
    problem, ``errors`` (earlier ones, e.g. unreadable files) included."""
    problems = list(errors)
    nodes: list[Node] = []
    for fname, doc in docs.items():
        for table, items in doc.items():
            if table not in _PARSERS:
                problems.append(f"{fname}: unknown table [[{table}]] (one of {', '.join(NODE_TYPES)})")
                continue
            if not isinstance(items, list):
                problems.append(f"{fname}: {table} must be an array of tables ([[{table}]])")
                continue
            for i, item in enumerate(items):
                raw_id = item.get("id") if isinstance(item, dict) else None
                where = f"{fname}: {table} {raw_id!r}" if isinstance(raw_id, str) else f"{fname}: {table} #{i + 1}"
                node = _PARSERS[table](_Table(item, where, problems))
                if node is not None:
                    nodes.append(replace(node, file=fname))
    problems += _validate(nodes)
    if problems:
        raise GraphError(problems)

    def of(cls: type[N]) -> tuple[N, ...]:
        return tuple(n for n in nodes if isinstance(n, cls))

    return TechniqueGraph(
        phases=tuple(sorted(of(Phase), key=lambda p: p.order)),
        conditions=of(Condition),
        techniques=of(Technique),
        signals=of(Signal),
        faults=of(Fault),
        causes=of(Cause),
        advice=of(Advice),
        constraints=of(Constraint),
        sources=of(Source),
        files=tuple(docs),
        digest=digest,
        by_id=MappingProxyType({n.id: n for n in nodes}),
    )


def load_graph_dir(directory: Path | None = None) -> TechniqueGraph:
    """Load and validate every ``*.toml`` in ``directory`` (default ``GRAPH_DIR``), in file-name order. Raises
    ``GraphError``."""
    root = GRAPH_DIR if directory is None else directory
    paths = sorted(root.glob("*.toml"))
    if not paths:
        raise GraphError([f"no *.toml files in {root}"])
    docs: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    digest = hashlib.sha256()
    for p in paths:
        try:
            raw = p.read_bytes()
            docs[p.name] = tomllib.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
            errors.append(f"{p.name}: cannot read: {e}")
            continue
        digest.update(p.name.encode() + b"\0" + raw + b"\0")
    return parse_graph(docs, digest=digest.hexdigest()[:16], errors=errors)


_strict = False


def set_strict(strict: bool) -> None:
    """Strict: ``load_graph()`` raises on a broken graph instead of logging it (tests/conftest.py turns it on)."""
    global _strict
    _strict = strict
    load_graph.cache_clear()


@lru_cache(maxsize=1)
def load_graph() -> TechniqueGraph:
    """The packaged graph, loaded once per process. When it does not load, every problem is logged and an empty graph
    (``valid`` False) is returned: Pitwall runs without technique knowledge, as before it existed."""
    try:
        return load_graph_dir()
    except GraphError as e:
        if _strict:
            raise
        for msg in e.errors:
            log.error("technique graph: %s", msg)
        log.error("technique graph: %d problem(s); running without technique knowledge", len(e.errors))
        return TechniqueGraph.empty(e.errors)
    except Exception as e:  # a bug in the loader must not stop the app either
        if _strict:
            raise
        log.exception("technique graph failed to load; running without technique knowledge")
        return TechniqueGraph.empty([f"loader error: {e!r}"])
