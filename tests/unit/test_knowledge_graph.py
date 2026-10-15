"""Technique knowledge graph (spec: technique knowledge graph, section 1): the packaged graph loads and validates; the
validator catches broken references, mirrored edges that disagree, unknown fields, bad condition keys and values,
signal code paths that name no dataclass field, live faults without a real coaching kind, missing threshold constants,
advice over its length limits and tiers no source backs; every user-facing text passes the forbidden-advice
constraints (no "brake later", "brake less", "release the brake earlier" or "carry more speed" outside praise); and
the runtime loader logs a broken graph and runs without it.

Pure: the packaged TOML files and small graphs written to a temporary folder; no game, LLM or database.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import logging
import math
import textwrap
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from pathlib import Path
from types import SimpleNamespace

import orjson
import pytest

from pitwall import carclass, drivers
from pitwall.analysis import coaching
from pitwall.knowledge import graph as kg
from pitwall.knowledge.graph import (
    CANONICAL_CAUSES,
    CANONICAL_LIVE_FAULTS,
    CANONICAL_PLANNED_FAULTS,
    CANONICAL_TECHNIQUES,
    CHANNEL_FIELDS,
    CONTEXT_VALUES,
    PHASE_IDS,
    RADIO_MAX_WORDS,
    SCREEN_MAX_CHARS,
    SIGNAL_CLASSES,
    Advice,
    Cause,
    Condition,
    Discriminator,
    Fault,
    GraphError,
    Signal,
    Technique,
    TechniqueGraph,
    load_graph,
    load_graph_dir,
    missing_canonical,
)
from pitwall.model.telemetry import CarFrame

# ---------------------------------------------------------------------------------------------- a small valid graph
_PHASES = "".join(
    f'\n[[phase]]\nid = "{p}"\norder = {i + 1}\nname = "{p}"\nsummary = "Phase {p}."\ntier = "expert"\n'
    'sources = ["book"]\n'
    for i, p in enumerate(PHASE_IDS)
)

BASE = (
    _PHASES
    + r"""
[[source]]
id = "book"
title = "A coaching book"
author = "Someone"
date = "2001"
tier = "expert"
note = "What we took, in our words."

[[source]]
id = "rules"
title = "Pitwall's rules"
author = "Pitwall project"
tier = "design"
note = "The rules."

[[source]]
id = "code"
title = "Pitwall's coaching code"
author = "Pitwall project"
tier = "live"
note = "The live rules."

[[condition]]
id = "trail"
name = "Trail-braking driver"
summary = "Brakes while turning in."
key = "braking_style"
op = "eq"
value = "trail"
tier = "design"

[[signal]]
id = "min_speed"
name = "Minimum speed vs reference"
summary = "Slowest speed minus the reference's."
code = "CornerDelta.min_speed_delta_kph"
unit = "km/h"
channels = ["speed", "lap_distance"]
tier = "live"
sources = ["code"]

[[technique]]
id = "tb"
name = "Trail braking"
summary = "Keep some brake on into the turn."
detail = "The release is blended with the steering."
phase = "turn_in"
applies_any = ["trail"]
measured_by = ["min_speed"]
tier = "expert"
sources = ["book"]

[[fault]]
id = "low_min_speed"
kind = "low_min_speed"
status = "live"
name = "Low minimum speed"
summary = "Slower at the slowest point."
phase = "apex"
relative = "reference"
signals = ["min_speed"]
thresholds = ["pitwall.analysis.coaching.MIN_SPEED_KPH"]
violates = ["tb"]
causes = ["ob"]
advice = ["say"]
tier = "live"
sources = ["code"]

[[cause]]
id = "ob"
name = "Over-braking"
summary = "More braking on the way in."
explains = ["low_min_speed"]
tier = "expert"
sources = ["book"]

[[cause.discriminators]]
signal = "min_speed"
test = "slower at the slowest point"
op = "lt"
value = -4.0

[[advice]]
id = "say"
for = "low_min_speed"
skill = "any"
kind = "describe"
radio = "Minimum speed down on your reference"
screen = "Slower at the slowest point"
review = "The slowest point was lower than on your reference lap."
tier = "live"
sources = ["code"]

[[constraint]]
id = "no_later"
name = "No later braking"
summary = "Never ask for later braking."
text = "never tell a driver to brake later"
scope = ["technique", "fault", "cause", "advice"]
except_praise = true
forbidden = ['\bbrak(?:e|ing)\s+later\b']
tier = "design"
sources = ["rules"]
"""
)

PRAISE = """
[[fault]]
id = "exit_gain"
kind = "exit_gain"
status = "live"
positive = true
name = "Good exit"
summary = "Faster out of the corner."
phase = "exit"
relative = "reference"
signals = ["min_speed"]
advice = ["praise"]
tier = "live"
sources = ["code"]

[[advice]]
id = "praise"
for = "exit_gain"
skill = "any"
kind = "describe"
review = "Braking later paid off here: the corner got faster."
tier = "live"
sources = ["code"]
"""


def build(tmp_path: Path, text: str) -> TechniqueGraph:
    (tmp_path / "graph.toml").write_text(text, encoding="utf-8")
    return load_graph_dir(tmp_path)


def problems(tmp_path: Path, text: str) -> list[str]:
    with pytest.raises(GraphError) as e:
        build(tmp_path, text)
    return list(e.value.errors)


def swap(old: str, new: str, text: str = BASE) -> str:
    assert old in text, old
    return text.replace(old, new, 1)


def assert_problem(tmp_path: Path, text: str, *needles: str) -> None:
    found = problems(tmp_path, text)
    assert any(all(n in p for n in needles) for p in found), found


# ---------------------------------------------------------------------------------------------- the packaged graph
def test_the_packaged_graph_loads_and_validates() -> None:
    g = load_graph_dir()
    assert g.valid and g.errors == ()
    assert [p.id for p in g.phases] == list(PHASE_IDS)
    assert {"phases.toml", "techniques.toml", "faults.toml", "constraints.toml", "sources.toml"} <= set(g.files)
    # the seed: one node of every type, end to end
    lms = g.fault_for_kind("low_min_speed")
    assert lms is not None and lms.status == "live" and lms.signals == ("min_speed_delta_kph",)
    assert [t.name for t in lms.thresholds] == [
        "pitwall.analysis.coaching.MIN_SPEED_KPH",
        "pitwall.analysis.coaching.MIN_TIME_LOSS_S",
    ]
    assert lms.thresholds[0].value == coaching.MIN_SPEED_KPH
    ob = g.get("over_braking", Cause)
    assert ob is not None and ob.explains == ("low_min_speed",) and lms.causes == ("over_braking",)
    assert [d.signal for d in ob.discriminators] == ["brake_point_delta_m", "entry_speed_delta_kph"]
    assert [a.id for a in g.advice_for("low_min_speed")] == ["low_min_speed_describe"]
    tb = g.get("trail_braking", Technique)
    assert tb is not None and tb.phase == "turn_in" and g.techniques_for("turn_in") == (tb,)
    assert {c.id for c in g.constraints} >= {"never_brake_later", "never_brake_less", "never_release_earlier"}
    ed = [s for s in g.sources if s.author == "Ed (Pitwall tester)"]
    assert {s.id for s in ed} == {"ed_corner_brief", "ed_fault_checklist", "ed_patches"}
    assert all(s.tier == "brief" for s in ed)
    assert g.digest is not None and len(g.digest) == 16


def test_load_graph_is_cached_and_raises_in_tests(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert load_graph() is load_graph() and load_graph().valid
    (tmp_path / "broken.toml").write_text('[[technique]]\nid = "x"\n', encoding="utf-8")
    monkeypatch.setattr(kg, "GRAPH_DIR", tmp_path)
    load_graph.cache_clear()
    try:
        with pytest.raises(GraphError):
            load_graph()  # tests run strict (tests/conftest.py)
    finally:
        monkeypatch.undo()
        load_graph.cache_clear()
    assert load_graph().valid


@pytest.fixture
def runtime_loader(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``load_graph()`` as the app runs it (not strict), restored to the tests' strict mode afterwards."""
    kg.set_strict(False)
    try:
        yield
    finally:
        monkeypatch.undo()
        kg.set_strict(True)


@pytest.mark.usefixtures("runtime_loader")
def test_at_runtime_a_broken_graph_is_logged_and_pitwall_runs_without_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "broken.toml").write_text(swap('causes = ["ob"]', 'causes = ["nope"]'), encoding="utf-8")
    monkeypatch.setattr(kg, "GRAPH_DIR", tmp_path)
    load_graph.cache_clear()
    with caplog.at_level(logging.ERROR, logger="pitwall.knowledge.graph"):
        g = load_graph()
    assert not g.valid and g.faults == () and g.phases == () and g.by_id == {}
    assert any("unknown id 'nope'" in e for e in g.errors)
    assert "unknown id 'nope'" in caplog.text and "running without technique knowledge" in caplog.text
    assert g.fault_for_kind("low_min_speed") is None and g.advice_for("low_min_speed") == ()
    assert g.to_payload()["valid"] is False


@pytest.mark.usefixtures("runtime_loader")
def test_at_runtime_a_missing_graph_folder_is_logged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(kg, "GRAPH_DIR", tmp_path / "nowhere")
    load_graph.cache_clear()
    g = load_graph()
    assert not g.valid and "no *.toml files" in g.errors[0]


# ---------------------------------------------------------------------------------------------- the spec's checks
def _constraint_hits(g: TechniqueGraph, owner: kg.Node, text: str) -> list[str]:
    hits = []
    for c in g.constraints:
        if c.except_praise and kg._is_praise(owner, g.by_id):
            continue
        hits += [f"{c.id}: {p}" for p in c.violations(text)]
    return hits


def test_every_advice_string_passes_every_constraint() -> None:
    g = load_graph_dir()
    assert g.advice and len(g.constraints) >= 4
    for a in g.advice:
        for text in (a.radio, a.screen, a.review):
            if text is not None:
                assert _constraint_hits(g, a, text) == [], (a.id, text)


# The packaged constraints catch instructions and let descriptions through. Add an example here when you change a
# pattern in graph/constraints.toml.
CAUGHT = [
    ("never_brake_later", "Brake later into Turn 3"),
    ("never_brake_later", "try braking a bit later"),
    ("never_brake_later", "Later braking would help here"),
    ("never_brake_later", "later on the brakes next time"),
    ("never_brake_later", "move your braking point back"),
    ("never_brake_later", "your brake point later by 10 m"),
    ("never_brake_later", "Don't brake so early"),
    ("never_brake_later", "don’t brake too soon"),
    ("never_brake_later", "brake deeper into the corner"),
    ("never_brake_later", "stay flat a little longer"),
    ("never_brake_later", "wait longer before braking"),
    ("never_brake_less", "brake less into the hairpin"),
    ("never_brake_less", "Use less brake pressure"),
    ("never_brake_less", "less braking on the way in"),
    ("never_brake_less", "be lighter on the brakes"),
    ("never_brake_less", "softer braking here"),
    ("never_brake_less", "don't brake so hard"),
    ("never_brake_less", "avoid over-braking"),
    ("never_release_earlier", "release the brake earlier"),
    ("never_release_earlier", "Next lap, release the brake earlier and carry more speed to turn-in"),
    ("never_release_earlier", "come off the brakes a bit sooner"),
    ("never_release_earlier", "an earlier brake release"),
    ("never_release_earlier", "release it sooner"),
    ("never_release_earlier", "be off the brake earlier"),
    ("never_carry_more_speed", "Next lap, release the brake earlier and carry more speed to turn-in"),
    ("never_carry_more_speed", "carry more speed into the apex"),
    ("never_carry_more_speed", "carry a bit more through the corner"),
    ("never_carry_more_speed", "carry the speed to the apex"),
    ("never_carry_more_speed", "take more speed into the corner"),
    ("never_carry_more_speed", "turn in faster"),
    ("never_carry_more_speed", "you need more entry speed"),
]
ALLOWED = [
    "You braked about 12 m earlier than on your reference lap.",
    "braked later, 5 km/h slower out",
    "going in 9 m too deep",
    "Minimum speed down on your reference",
    "apex speed, 12 down",
    "carrying 6 km/h more into the apex, slower out",
    "faster in, 4 km/h slower out",
    "full throttle 20 m later than your reference",
    "the brake release was 0.2 s quicker than on your reference",
    "Over-braking",
    "Keep some brake on as you start to turn, and ease it off as the steering goes in.",
    "Hit the brake hard and fast, then bleed the pressure off as the car slows.",
    "Stay flat out right up to your braking point; don't lift before it.",
    "Come off the brake with a little speed to spare and let the cornering load slow the car to the apex.",
    "Release the brake while the car is still faster than the apex needs.",
]


@pytest.mark.parametrize(("constraint", "text"), CAUGHT)
def test_the_constraints_catch_instructions(constraint: str, text: str) -> None:
    g = load_graph_dir()
    c = next(c for c in g.constraints if c.id == constraint)
    assert c.violations(text), text


@pytest.mark.parametrize("text", ALLOWED)
def test_the_constraints_let_descriptions_through(text: str) -> None:
    g = load_graph_dir()
    assert [c.violations(text) for c in g.constraints] == [[] for _ in g.constraints], text


def test_signal_code_paths_name_real_dataclass_fields() -> None:
    g = load_graph_dir()
    computed = [s for s in g.signals if s.code is not None]
    assert computed
    for s in computed:
        assert s.code is not None
        cls_name, attr = s.code.split(".")
        cls = getattr(importlib.import_module(SIGNAL_CLASSES[cls_name]), cls_name)
        assert is_dataclass(cls), s.code
        assert attr in {f.name for f in fields(cls)}, s.code
        getattr(cls, attr)  # slotted dataclass: the field's descriptor


def test_signal_classes_and_channels_are_real() -> None:
    for name, module in SIGNAL_CLASSES.items():
        cls = getattr(importlib.import_module(module), name)
        assert is_dataclass(cls) and hasattr(cls, "__slots__"), name
    frame_fields = {f.name for f in fields(CarFrame)}
    for channel, names in CHANNEL_FIELDS.items():
        assert set(names) <= frame_fields, channel


def test_vocabularies_follow_the_code() -> None:
    assert CONTEXT_VALUES["skill"] == drivers.SKILL_LEVELS
    assert CONTEXT_VALUES["car_family"] == carclass.FAMILIES
    assert SCREEN_MAX_CHARS == coaching.SHORT_MAX_CHARS
    assert set(CANONICAL_LIVE_FAULTS) == set(coaching.COACHING_KINDS)


def test_coaching_kinds_are_the_kinds_the_rules_produce() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(coaching.observations_for_comparison)))
    kinds: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "add" and node.args:
            arg = node.args[0]
            kinds.add(arg.value if isinstance(arg, ast.Constant) else getattr(coaching, getattr(arg, "id", "")))
    assert kinds == set(coaching.COACHING_KINDS)
    assert kinds >= coaching.POSITIVE_KINDS


def test_canonical_ids_present_have_their_type() -> None:
    g = load_graph_dir()
    for ids, cls in ((CANONICAL_TECHNIQUES, Technique), (CANONICAL_CAUSES, Cause)):
        assert all(isinstance(g.by_id[i], cls) for i in ids if i in g.by_id)
    for i in CANONICAL_LIVE_FAULTS:
        f = g.get(i, Fault)
        assert i not in g.by_id or (f is not None and f.status == "live" and f.kind == i)
    for i in CANONICAL_PLANNED_FAULTS:
        f = g.get(i, Fault)
        assert i not in g.by_id or (f is not None and f.status != "live" and f.kind is None)


@pytest.mark.xfail(
    strict=True, reason="the content slices write these nodes: remove this marker once missing_canonical() is empty"
)
def test_every_canonical_id_has_a_node() -> None:
    assert missing_canonical(load_graph_dir()) == {}


# ---------------------------------------------------------------------------------------------- semantics
@pytest.mark.parametrize(
    ("cid", "ctx", "expected"),
    [
        ("skill_beginner", {"skill": "beginner"}, True),
        ("skill_beginner", {"skill": "advanced"}, False),
        ("skill_beginner", {"skill": None}, False),
        ("skill_beginner", {}, False),
        ("skill_not_beginner", {"skill": "advanced"}, True),
        ("skill_not_beginner", {"skill": None}, False),
        ("abs_off", {"abs": False}, True),
        ("abs_off", {"abs": None}, False),
        ("abs_on", {"abs": None}, False),
        ("dry", {"wet": False}, True),
        ("dry", {}, False),
        ("no_abs_low_downforce", {"abs": False, "downforce": "low"}, True),
        ("no_abs_low_downforce", {"abs": False, "downforce": None}, False),
        ("no_abs_low_downforce", {"abs": False, "downforce": "high"}, False),
        ("not_a_condition", {"skill": "beginner"}, False),
    ],
)
def test_unknown_never_satisfies_a_condition(cid: str, ctx: dict[str, object], expected: bool) -> None:
    g = load_graph_dir()
    assert g.holds(cid, ctx) is expected
    assert g.holds(cid, SimpleNamespace(**ctx)) is expected  # a Context object works the same


def test_ne_does_not_hold_for_unknown() -> None:
    c = Condition(id="not_h", name="n", summary="s", tier="design", sources=(), key="gearbox", op="ne", value="auto")
    assert c.holds("h_pattern") and not c.holds("auto") and not c.holds(None)


def test_discriminators_hold_only_on_measured_values() -> None:
    d = Discriminator(signal="brake_point_delta_m", test="earlier", op="le", value=-8.0)
    assert d.holds(-12.0) and d.holds(-8) and not d.holds(-3.0)
    assert not d.holds(None) and not d.holds(math.nan) and not d.holds(True) and not d.holds("-12")
    flag = Discriminator(signal="slide", test="slid", op="true")
    assert flag.holds(True) and not flag.holds(False) and not flag.holds(None)


def test_payload_is_json_with_toml_names_and_claimed_edge_tiers(tmp_path: Path) -> None:
    g = build(tmp_path, BASE)
    p = orjson.loads(orjson.dumps(g.to_payload()))
    assert p["valid"] and p["counts"]["faults"] == 1 and p["counts"]["phases"] == 6
    say = p["advice"][0]
    assert say["for"] == "low_min_speed" and "for_id" not in say and say["type"] == "advice"
    assert p["faults"][0]["thresholds"] == [{"name": "pitwall.analysis.coaching.MIN_SPEED_KPH", "value": 4.0}]
    assert "patterns" not in p["constraints"][0] and p["constraints"][0]["forbidden"]
    edges = {(e["from"], e["to"], e["rel"]): e for e in p["edges"]}
    # the cause makes the "caused by" claim: its tier (expert), not the live fault's
    assert edges[("low_min_speed", "ob", "caused_by")]["tier"] == "expert"
    assert edges[("low_min_speed", "say", "advice")]["tier"] == "live"
    assert edges[("tb", "trail", "applies_any")]["sources"] == ["book"]
    assert ("ob", "min_speed", "discriminated_by") in edges


def test_minimal_graph_with_praise_is_valid(tmp_path: Path) -> None:
    g = build(tmp_path, BASE + PRAISE)
    assert g.valid and g.fault_for_kind("exit_gain") is not None
    assert isinstance(g.node("praise"), Advice)


# ---------------------------------------------------------------------------------------------- the validator
@pytest.mark.parametrize(
    ("old", "new", "needles"),
    [
        ('causes = ["ob"]', 'causes = ["nope"]', ("fault 'low_min_speed'", "causes", "unknown id 'nope'")),
        ('phase = "turn_in"', 'phase = "nowhere"', ("technique 'tb'", "phase", "unknown id 'nowhere'")),
        ('measured_by = ["min_speed"]', 'measured_by = ["x"]', ("measured_by", "unknown id 'x'")),
        ('for = "low_min_speed"', 'for = "ghost"', ("advice 'say'", "for", "unknown id 'ghost'")),
        ('applies_any = ["trail"]', 'applies_any = ["late"]', ("applies_any", "unknown id 'late'")),
        ('sources = ["book"]\n\n[[fault]]', 'sources = ["nobook"]\n\n[[fault]]', ("sources", "unknown id 'nobook'")),
        ('signal = "min_speed"', 'signal = "speed"', ("discriminators[0].signal", "unknown id 'speed'")),
    ],
)
def test_broken_references_are_found(tmp_path: Path, old: str, new: str, needles: tuple[str, ...]) -> None:
    assert_problem(tmp_path, swap(old, new), *needles)


def test_a_reference_to_the_wrong_node_type_is_found(tmp_path: Path) -> None:
    assert_problem(tmp_path, swap('violates = ["tb"]', 'violates = ["min_speed"]'), "is a signal, not a technique")
    assert_problem(tmp_path, swap('for = "low_min_speed"', 'for = "tb"'), "is a technique, not a fault or cause")


def test_mirrored_edges_must_agree(tmp_path: Path) -> None:
    assert_problem(tmp_path, swap('causes = ["ob"]\n', ""), "cause 'ob'", "does not list it in causes")
    assert_problem(tmp_path, swap('advice = ["say"]\n', ""), "advice 'say'", "does not list it in advice")
    one_way = swap('measured_by = ["min_speed"]', 'measured_by = ["min_speed"]\nalternatives = ["tb2"]') + (
        '\n[[technique]]\nid = "tb2"\nname = "Straight-line braking"\nsummary = "Brake with the wheel straight."\n'
        'detail = "Then turn."\nphase = "braking"\ntier = "expert"\nsources = ["book"]\n'
    )
    assert_problem(tmp_path, one_way, "technique 'tb'", "does not list it as an alternative")
    both = one_way.replace('phase = "braking"\n', 'phase = "braking"\nalternatives = ["tb"]\n')
    assert build(tmp_path, both).valid


def test_ids_fields_and_tables_are_checked(tmp_path: Path) -> None:
    assert_problem(
        tmp_path,
        BASE + '\n[[source]]\nid = "book"\ntitle = "t"\nauthor = "a"\ntier = "expert"\nnote = "n"\n',
        "duplicate id",
    )
    assert_problem(
        tmp_path,
        swap('detail = "The release', 'colour = "red"\ndetail = "The release'),
        "technique 'tb'",
        "colour",
        "unknown field",
    )
    assert_problem(tmp_path, BASE + '\n[[tecnique]]\nid = "x"\n', "unknown table [[tecnique]]")
    assert_problem(tmp_path, swap('id = "tb"', 'id = "Trail-Braking"'), "is not snake_case")
    assert_problem(tmp_path, swap('summary = "Keep some brake on into the turn."\n', ""), "summary", "missing")
    assert_problem(tmp_path, BASE + "\n[[phase]\n", "cannot read")  # TOML syntax


def test_the_six_phases_are_required_in_driving_order(tmp_path: Path) -> None:
    no_exit = BASE.replace('\n[[phase]]\nid = "exit"', '\n[[phasex]]\nid = "exit"', 1)
    assert_problem(tmp_path, no_exit, "phases: expected exactly")
    assert_problem(tmp_path, swap('id = "apex"\norder = 5', 'id = "apex"\norder = 2'), "order must be 5")


@pytest.mark.parametrize(
    ("old", "new", "needles"),
    [
        ('key = "braking_style"', 'key = "mood"', ("key", "'mood' is not one of")),
        ('value = "trail"', 'value = "late"', ("value", "'late' is not one of trail")),
        ('op = "eq"', 'op = "true"', ("op", "use eq, ne or in")),
        ('op = "eq"\nvalue = "trail"', 'op = "in"\nvalue = "trail"', ("op 'in' takes a list",)),
        (
            'key = "braking_style"\nop = "eq"\nvalue = "trail"',
            'key = "abs"\nop = "eq"\nvalue = "trail"',
            ('abs is true/false: use op = "true" or "false"',),
        ),
        ('value = "trail"', 'value = "trail"\nall_of = ["trail"]', ("exactly one of",)),
    ],
)
def test_condition_keys_and_values_are_checked(tmp_path: Path, old: str, new: str, needles: tuple[str, ...]) -> None:
    assert_problem(tmp_path, swap(old, new), *needles)


def test_condition_cycles_are_found(tmp_path: Path) -> None:
    loop = (
        '\n[[condition]]\nid = "a"\nname = "A"\nsummary = "A."\nall_of = ["b"]\ntier = "design"\n'
        '\n[[condition]]\nid = "b"\nname = "B"\nsummary = "B."\nany_of = ["a", "trail"]\ntier = "design"\n'
    )
    assert_problem(tmp_path, BASE + loop, "conditions: cycle a -> b -> a")


@pytest.mark.parametrize(
    ("code", "needle"),
    [
        ("CornerDelta.min_speed_delta", "CornerDelta (pitwall.analysis.compare) has no field 'min_speed_delta'"),
        ("LapDelta.min_speed_delta_kph", "unknown class 'LapDelta'"),
        ("min_speed_delta_kph", "must look like ClassName.field"),
    ],
)
def test_signal_code_must_name_a_real_dataclass_field(tmp_path: Path, code: str, needle: str) -> None:
    assert_problem(tmp_path, swap('code = "CornerDelta.min_speed_delta_kph"', f'code = "{code}"'), "code", needle)


def test_signal_channels_and_units_are_checked(tmp_path: Path) -> None:
    assert_problem(tmp_path, swap('channels = ["speed", "lap_distance"]', 'channels = ["sped"]'), "'sped' not one of")
    assert_problem(tmp_path, swap('unit = "km/h"', 'unit = "mph"'), "unit", "'mph' is not one of")


@pytest.mark.parametrize(
    ("old", "new", "needles"),
    [
        ('kind = "low_min_speed"\n', "", ("a live fault names its coaching kind",)),
        ('kind = "low_min_speed"', 'kind = "slow_apex"', ("'slow_apex' is not a coaching kind",)),
        ('status = "live"', 'status = "planned"', ("a fault with a coaching kind is live",)),
        ('kind = "low_min_speed"', 'kind = "low_min_speed"\npositive = true', ("positive must be False",)),
        ("MIN_SPEED_KPH", "MIN_SPEED", ("thresholds", "no numeric constant 'MIN_SPEED'")),
        ("pitwall.analysis.coaching.MIN_SPEED_KPH", "coaching.MIN_SPEED_KPH", ("thresholds", "dotted path")),
        ('status = "live"', 'status = "maybe"', ("status", "'maybe' is not one of")),
        ('relative = "reference"', 'relative = "best"', ("relative", "'best' is not one of")),
    ],
)
def test_faults_are_checked(tmp_path: Path, old: str, new: str, needles: tuple[str, ...]) -> None:
    assert_problem(tmp_path, swap(old, new), *needles)


def test_a_live_fault_needs_computed_signals(tmp_path: Path) -> None:
    text = swap('code = "CornerDelta.min_speed_delta_kph"\n', "")
    assert_problem(tmp_path, text, "fault 'low_min_speed'", "signal 'min_speed' is not computed")


def test_advice_limits_are_checked(tmp_path: Path) -> None:
    long_radio = 'radio = "' + " ".join(["word"] * (RADIO_MAX_WORDS + 1)) + '"'
    assert_problem(tmp_path, swap('radio = "Minimum speed down on your reference"', long_radio), "radio", "9 words")
    long_screen = 'screen = "' + "x" * (SCREEN_MAX_CHARS + 1) + '"'
    assert_problem(tmp_path, swap('screen = "Slower at the slowest point"', long_screen), "screen", "49 characters")
    long_review = 'review = "' + "y" * 321 + '"'
    assert_problem(
        tmp_path,
        swap('review = "The slowest point was lower than on your reference lap."', long_review),
        "review",
        "321 characters",
    )
    assert_problem(tmp_path, swap('skill = "any"', 'skill = "expert"'), "skill", "'expert' is not one of")
    review_only = swap('radio = "Minimum speed down on your reference"\nscreen = "Slower at the slowest point"\n', "")
    a = build(tmp_path, review_only).get("say", Advice)
    assert a is not None and a.radio is None and a.screen is None and a.summary == a.review


def test_tiers_must_be_backed_by_a_source(tmp_path: Path) -> None:
    text = swap(
        'tier = "expert"\nsources = ["book"]\n\n[[fault]]', 'tier = "recorded"\nsources = ["book"]\n\n[[fault]]'
    )
    assert_problem(tmp_path, text, "technique 'tb'", "tier 'recorded' needs a source of that tier", "expert")
    design = swap(
        'tier = "expert"\nsources = ["book"]\n\n[[fault]]', 'tier = "design"\nsources = ["book"]\n\n[[fault]]'
    )
    assert_problem(tmp_path, design, "technique 'tb'", "tier 'design' is only for")
    assert_problem(
        tmp_path, swap('tier = "design"\n\n[[signal]]', 'tier = "guess"\n\n[[signal]]'), "'guess' is not one of"
    )


def test_text_that_breaks_a_constraint_is_found(tmp_path: Path) -> None:
    text = swap('summary = "Keep some brake on into the turn."', 'summary = "Brake later and keep some brake on."')
    assert_problem(tmp_path, text, "technique 'tb'", "summary", "breaks constraint 'no_later'")
    radio = swap('radio = "Minimum speed down on your reference"', 'radio = "Try braking later here"')
    assert_problem(tmp_path, radio, "advice 'say'", "radio", "breaks constraint 'no_later'")
    test = swap('test = "slower at the slowest point"', 'test = "braking later than the reference"')
    assert_problem(tmp_path, test, "cause 'ob'", "discriminators[0].test", "no_later")
    # praise may say it (the constraint's except_praise); the same words on a corrective point may not
    assert build(tmp_path, BASE + PRAISE).valid
    corrective = BASE + PRAISE.replace("positive = true\n", "").replace('kind = "exit_gain"\n', "").replace(
        'status = "live"\n', 'status = "planned"\n'
    )
    assert_problem(tmp_path, corrective, "advice 'praise'", "breaks constraint 'no_later'")
    bad_regex = swap(r"forbidden = ['\bbrak(?:e|ing)\s+later\b']", "forbidden = ['brake (later']")
    assert_problem(tmp_path, bad_regex, "forbidden", "not a valid regular expression")


def test_discriminators_measurements_and_sources_are_checked(tmp_path: Path) -> None:
    assert_problem(tmp_path, swap("value = -4.0\n", ""), "discriminators[0]", "value", "missing")
    assert_problem(tmp_path, swap('op = "lt"', 'op = "below"'), "discriminators[0]", "'below' is not one of")
    measured = swap(
        'sources = ["code"]\n\n[[cause]]',
        'sources = ["code"]\n\n[[fault.measured]]\nmetric = "firing rate"\n'
        'value = 5.1\nunit = "%"\ndate = "15 Oct"\nsource = "ghost"\n\n[[cause]]',
    )
    assert_problem(tmp_path, measured, "measured[0]", "date", "'15 Oct'")
    measured_ok_date = measured.replace('"15 Oct"', '"2026-10-15"')
    assert_problem(tmp_path, measured_ok_date, "measured source", "unknown id 'ghost'")
    assert_problem(tmp_path, swap('date = "2001"', 'date = "2001"\nurl = "ftp://x"'), "url", "not an http(s) URL")
    assert_problem(tmp_path, swap('date = "2001"', 'date = "May 2001"'), "date", "'May 2001'")
    assert_problem(
        tmp_path, swap('note = "The rules."', 'note = "The rules."\nsources = ["book"]'), "a source cites nothing"
    )


def test_canonical_ids_keep_their_type(tmp_path: Path) -> None:
    assert_problem(tmp_path, BASE.replace('"tb"', '"over_braking"'), "'over_braking' is a canonical cause id")
    planned = BASE + (
        '\n[[technique]]\nid = "pedal_overlap"\nname = "Overlap"\nsummary = "Both pedals."\ndetail = "Both."\n'
        'phase = "braking"\ntier = "expert"\nsources = ["book"]\n'
    )
    assert_problem(tmp_path, planned, "'pedal_overlap' is canonically a fault that is not live")


def test_signal_type_is_frozen_and_hashable() -> None:
    g = load_graph_dir()
    s = g.get("min_speed_delta_kph", Signal)
    assert s is not None and hash(s) == hash(s)
    with pytest.raises(AttributeError):
        s.code = "x"  # type: ignore[misc]
