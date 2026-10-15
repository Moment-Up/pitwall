"""Applying the technique graph to one driver (spec: technique knowledge graph, section 3): which nodes fit and why the
others do not, causes named from measured signals only (with their evidence), advice by skill and braking style, and
the ``knowledge`` annotation an observation carries.

Pure: the packaged graph, hand-made corner metrics and technique values; no game, LLM or database.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from pitwall.analysis import coaching
from pitwall.analysis.compare import CornerDelta, CornerMetrics, corner_delta
from pitwall.knowledge.annotate import (
    DELTA_CLASS,
    METRICS_CLASS,
    TECHNIQUE_READERS,
    CornerTechnique,
    DriverKnowledge,
    corner_reader,
    slim,
)
from pitwall.knowledge.context import Context, build_context
from pitwall.knowledge.graph import Fault, Signal, TechniqueGraph, load_graph
from pitwall.technique.balance import PhaseBalance
from pitwall.technique.inputs import CornerInputs, SlipEvents

F1 = Context(game="f1", car_family="f1", downforce="high", gearbox="paddle_autoblip", abs=False)


@pytest.fixture(scope="module")
def g() -> TechniqueGraph:
    return load_graph()


def dk(g: TechniqueGraph, ctx: Context = F1, game: str | None = "f1_25") -> DriverKnowledge:
    return DriverKnowledge(g, ctx, game)


def metrics(**kw: Any) -> CornerMetrics:
    base: dict[str, Any] = {
        "corner": "T3",
        "segment_time_s": 10.0,
        "brake_start_m": 500.0,
        "brake_end_m": 560.0,
        "entry_speed_kph": 200.0,
        "min_speed_kph": 100.0,
        "min_speed_m": 600.0,
        "exit_speed_kph": 150.0,
        "throttle_pickup_m": 610.0,
        "throttle_full_m": 650.0,
        "coast_m": 0.0,
        "trail_brake_m": 20.0,
    }
    return CornerMetrics(**{**base, **kw})


def delta(**lap: Any) -> CornerDelta:
    """This lap minus the reference at T3; ``lap`` overrides this lap's metrics."""
    return corner_delta("T3", metrics(), metrics(**lap))


# ---------------------------------------------------------------------------------------------- fit
def test_live_faults_fit_every_driver_on_every_game(g: TechniqueGraph) -> None:
    """The eight live kinds have no conditions and every game sends their channels: coaching on them is unchanged."""
    games = ("f1_25", "gt7", "forza_motorsport", "forza_horizon", "ac", None, "f1_24")
    for game in games:
        for ctx in (Context(), F1, Context(skill="beginner", gearbox="h_pattern")):
            view = dk(g, ctx, game)
            for kind in coaching.COACHING_KINDS:
                f = g.fault_for_kind(kind)
                assert f is not None and view.fit(f).applies, (game, ctx, kind, view.fit(f))


def test_a_fault_whose_channel_the_game_does_not_send_does_not_apply(g: TechniqueGraph) -> None:
    gt7 = dk(g, Context(game="gt7"), "gt7")
    fit = gt7.fit("low_throttle_acceptance")
    assert not fit.applies and fit.why_not == "GT7 does not send lateral g"
    assert not gt7.fit("throttle_acceptance").applies  # the signal itself
    assert dk(g, F1).fit("low_throttle_acceptance").applies  # F1 25 sends it
    # an unknown channel is never assumed absent (GT7 does not declare tyre slip)
    assert gt7.fit("lockup_events").applies


def test_conditions_say_why_a_node_does_not_fit(g: TechniqueGraph) -> None:
    f1 = dk(g, F1)
    blip = f1.fit("missed_blip")
    assert not blip.applies and blip.why_not == "Only for: H-pattern gearbox (gearbox paddles with auto-blip)"
    unknown = dk(g, Context()).fit("rev_match_downshift")
    assert not unknown.applies and unknown.why_not == "Only for: H-pattern gearbox (gearbox not known)"
    assert dk(g, Context(gearbox="h_pattern")).fit("rev_match_downshift").applies
    sl = f1.fit("straight_line_braking")
    assert not sl.applies and sl.why_not is not None
    assert sl.why_not.startswith("Only for: Beginner, Straight-line braking driver or No ABS, low downforce (")
    assert "skill not known" in sl.why_not and "braking style not known" in sl.why_not
    assert f1.fit("trail_braking").applies  # high downforce
    assert dk(g, Context(skill="beginner")).fit("straight_line_braking").applies
    assert not f1.fit("abs_on").applies and f1.fit("abs_on").why_not == "ABS off"
    assert f1.fit("not_a_node") == f1.fit("not_a_node") and not f1.fit("not_a_node").applies


def test_a_cause_needs_its_signals_on_the_game(g: TechniqueGraph) -> None:
    gt7 = dk(g, Context(game="gt7"), "gt7")
    fit = gt7.fit("ready_earlier")  # every discriminator is needed; the exit slide needs lateral g
    assert not fit.applies and fit.why_not == "GT7 does not send lateral g"
    assert gt7.fit("traction_limited").applies  # one of its any-of signals (wheelspin) may be measured
    assert gt7.fit("over_braking").applies and dk(g, F1).fit("ready_earlier").applies


def test_advice_fits_by_skill_and_style(g: TechniqueGraph) -> None:
    beginner = dk(g, Context(skill="beginner"))
    assert beginner.fit("low_min_speed_describe_beginner").applies
    adv = dk(g, Context(skill="advanced"))
    fit = adv.fit("low_min_speed_describe_beginner")
    assert not fit.applies and fit.why_not == "For beginner drivers (skill advanced)"
    trail = adv.fit("coasting_explain_straight_line")
    assert not trail.applies and trail.why_not == "For drivers who brake in a straight line (braking style not known)"


# ---------------------------------------------------------------------------------------------- advice
def test_advice_by_skill_and_style(g: TechniqueGraph) -> None:
    any_ = dk(g, Context()).advice("low_min_speed")
    assert any_ is not None
    assert any_["radio"] == "Minimum speed down on your reference" and any_["ids"]["review"] == "low_min_speed_describe"
    beginner = dk(g, Context(skill="beginner")).advice("low_min_speed")
    assert beginner is not None and beginner["ids"] == dict.fromkeys(
        ("radio", "screen", "review"), "low_min_speed_describe_beginner"
    )
    # a trail-braking driver: the style's explanation for the review, the radio and screen keep the describe line
    trail = dk(g, Context(braking_style="trail")).advice("coasting")
    assert trail is not None
    assert trail["ids"] == {
        "radio": "coasting_describe",
        "screen": "coasting_describe",
        "review": "coasting_explain_trail",
    }
    # a straight-line beginner: style first, then the skill
    sl = dk(g, Context(skill="beginner", braking_style="straight_line")).advice("coasting")
    assert sl is not None and sl["ids"]["review"] == "coasting_explain_straight_line"
    assert sl["ids"]["radio"] == sl["ids"]["screen"] == "coasting_describe_beginner"
    # incidents never go on the radio; a review-only explanation has no radio or screen
    inc = dk(g, Context()).advice("incident")
    assert inc is not None and inc["radio"] is None and inc["screen"] == "Incident, no advice this lap"
    rel = dk(g, Context()).advice("released_too_early_for_apex")
    assert rel is not None and rel["radio"] is None and rel["screen"] is None and rel["review"]
    assert dk(g, Context()).advice("not_a_node") is None


# ---------------------------------------------------------------------------------------------- causes
def causes(g: TechniqueGraph, kind: str, cd: CornerDelta, tech: CornerTechnique | None = None) -> list[str]:
    f = g.get(kind, Fault)
    assert f is not None
    return [c["id"] for c in dk(g).causes(f, corner_reader(cd, (lambda: tech) if tech is not None else None))]


def test_over_braking_and_early_turn_in_are_told_apart(g: TechniqueGraph) -> None:
    """Over-braking: braked 8 m earlier (any) and entered 4 km/h slower; early turn-in: the slowest point 20 m sooner
    with an entry no more than 4 km/h slower."""
    early_brake = delta(brake_start_m=488.0, entry_speed_kph=194.0, min_speed_kph=92.0)
    assert causes(g, "low_min_speed", early_brake) == ["over_braking"]
    early_apex = delta(min_speed_m=575.0, min_speed_kph=92.0)
    assert causes(g, "low_min_speed", early_apex) == ["early_turn_in"]
    assert causes(g, "low_min_speed", delta(min_speed_kph=92.0)) == []  # nothing tells it apart: no cause
    f = g.get("low_min_speed", Fault)
    assert f is not None
    (named,) = dk(g).causes(f, corner_reader(early_brake))
    assert named["name"] == "Over-braking" and named["tier"] == "brief"
    assert named["evidence"] == [
        {
            "signal": "brake_point_delta_m",
            "test": "braked at least 8 m earlier than on the reference lap",
            "value": -12.0,
            "unit": "m",
        },
        {
            "signal": "entry_speed_delta_kph",
            "test": "at least 4 km/h slower at the corner entry than on the reference lap",
            "value": -6.0,
            "unit": "km/h",
        },
    ]
    assert named["advice"]["radio"] is None and named["advice"]["review"]  # causes stay off the radio


def test_an_unmeasured_signal_names_no_cause(g: TechniqueGraph) -> None:
    unmeasured_entry = corner_delta("T3", metrics(entry_speed_kph=None), metrics(brake_start_m=480.0))
    assert causes(g, "low_min_speed", unmeasured_entry) == []
    assert dk(g).causes(g.get("low_min_speed", Fault), None) == []  # type: ignore[arg-type]


def _pb(slip: float | None = 1.0, slide: bool = False) -> PhaseBalance:
    return PhaseBalance(cls=None, slip_diff_deg=slip, body_slip_max_deg=None, slide=slide, samples=30)


def _tech(
    mid: PhaseBalance | None = None,
    exit_: PhaseBalance | None = None,
    lockup: SlipEvents | None = None,
    spin: SlipEvents | None = None,
) -> CornerTechnique:
    inputs = CornerInputs(
        braked=True, lockup=lockup or SlipEvents("measured", 0), wheelspin=spin or SlipEvents("measured", 0)
    )
    return CornerTechnique(inputs, {"entry": _pb(), "mid": mid or _pb(), "exit": exit_ or _pb()})


def test_slip_and_balance_causes_read_this_laps_technique(g: TechniqueGraph) -> None:
    slow = delta(min_speed_kph=92.0)
    assert causes(g, "low_min_speed", slow, _tech(mid=_pb(slide=True))) == ["low_grip"]
    assert causes(g, "low_min_speed", slow, _tech(mid=_pb(3.5))) == ["low_grip"]  # mid-corner understeer
    assert causes(g, "low_min_speed", slow, _tech(lockup=SlipEvents("measured", 1))) == ["low_grip"]
    assert causes(g, "low_min_speed", slow, _tech()) == []
    late = delta(throttle_full_m=680.0)
    assert causes(g, "late_throttle", late, _tech(spin=SlipEvents("measured", 2))) == ["traction_limited"]
    assert causes(g, "late_throttle", late, _tech(exit_=_pb(slide=True))) == ["traction_limited"]
    assert causes(g, "late_throttle", late, _tech()) == ["ready_earlier"]  # grip was there: no spin, slide, push
    assert causes(g, "late_throttle", late, _tech(exit_=_pb(3.0))) == []  # exit understeer: neither


def test_unknown_slip_is_not_zero(g: TechniqueGraph) -> None:
    """Lock-ups with ABS on, or no slip data, are unknown: "no wheelspin" never holds then."""
    late = delta(throttle_full_m=680.0)
    for status in ("abs_on", "no_data", "not_applicable"):
        spin = SlipEvents(status)  # type: ignore[arg-type]
        assert causes(g, "late_throttle", late, _tech(spin=spin)) == [], status
    assert causes(g, "late_throttle", late, _tech(exit_=_pb(None))) == []  # exit balance unmeasured
    no_balance = CornerTechnique(CornerInputs(braked=True, wheelspin=SlipEvents("measured", 0)), None)
    assert causes(g, "late_throttle", late, no_balance) == []


def test_coasting_causes(g: TechniqueGraph) -> None:
    released = delta(brake_end_m=548.0, coast_m=20.0)
    assert causes(g, "coasting", released) == ["early_brake_release"]
    waiting = delta(throttle_pickup_m=625.0, coast_m=20.0)
    assert causes(g, "coasting", waiting) == ["waiting_for_rotation"]
    hot = delta(entry_speed_kph=206.0, min_speed_kph=106.0, exit_speed_kph=145.0)
    assert causes(g, "overspeed_apex", hot) == ["carried_too_much_speed"]


def test_every_cause_signal_has_a_reader_with_the_graphs_code(g: TechniqueGraph) -> None:
    for sid, (code, _) in TECHNIQUE_READERS.items():
        s = g.get(sid, Signal)
        assert s is not None and s.code == code, sid
    for c in g.causes:
        for d in c.discriminators:
            s = g.get(d.signal, Signal)
            assert s is not None and s.code is not None
            cls = s.code.split(".")[0]
            assert cls in (DELTA_CLASS, METRICS_CLASS) or s.id in TECHNIQUE_READERS, (c.id, s.id, s.code)


# ---------------------------------------------------------------------------------------------- annotation
def obs(kind: str, corner: str = "T3") -> dict[str, Any]:
    return {"kind": kind, "corner": corner, "positive": kind == "exit_gain"}


def test_the_annotation_of_an_observation(g: TechniqueGraph) -> None:
    view = dk(g, build_context(game="f1_25", skill="beginner"))
    k = view.annotate(obs("low_min_speed"), corner_reader(delta(brake_start_m=488.0, entry_speed_kph=194.0)))
    assert k is not None
    assert {"fault", "applies", "why_not", "causes", "advice"} <= set(k)
    assert (k["fault"], k["status"], k["tier"], k["applies"], k["why_not"]) == (
        "low_min_speed",
        "live",
        "live",
        True,
        None,
    )
    assert [c["id"] for c in k["causes"]] == ["over_braking"] and k["digest"] == g.digest
    assert k["advice"]["screen"] == "Slower in the middle of the corner"  # the beginner's words
    s = slim(k)
    assert s is not None and set(s) == {"fault", "applies", "why_not", "causes", "advice"}
    assert s["causes"][0]["screen"] == "Slowed more than your reference on the way in"
    assert set(s["causes"][0]["evidence"][0]) == {"test", "value", "unit"}
    assert view.annotate(obs("not_a_kind")) is None and slim(None) is None
    assert view.annotate(obs("exit_gain"))["advice"]["radio"]  # type: ignore[index]
    assert coaching.applies({**obs("low_min_speed"), "knowledge": k})


def test_a_point_that_does_not_fit_is_marked(g: TechniqueGraph) -> None:
    """No live fault has conditions today: a fault given one stands in for a future conditional rule."""
    lms = g.get("low_min_speed", Fault)
    assert lms is not None
    gated = TechniqueGraph(
        faults=tuple(replace(f, applies_when=("gearbox_h_pattern",)) if f.id == lms.id else f for f in g.faults),
        conditions=g.conditions,
        signals=g.signals,
        causes=g.causes,
        advice=g.advice,
        by_id={**g.by_id, lms.id: replace(lms, applies_when=("gearbox_h_pattern",))},
    )
    k = dk(gated).annotate(obs("low_min_speed"))
    assert k is not None and k["applies"] is False
    assert k["why_not"] == "Only for: H-pattern gearbox (gearbox paddles with auto-blip)"
    assert not coaching.applies({**obs("low_min_speed"), "knowledge": k})
    assert coaching.applies(obs("low_min_speed"))  # no annotation: as before the graph


def test_without_a_graph_nothing_is_annotated() -> None:
    empty = TechniqueGraph.empty(["broken"])
    assert DriverKnowledge(empty, Context()).annotate(obs("low_min_speed")) is None


def test_node_fits_cover_the_driver_facing_nodes(g: TechniqueGraph) -> None:
    fits = dk(g).node_fits()
    want = {n.id for n in (*g.conditions, *g.signals, *g.techniques, *g.faults, *g.causes, *g.advice)}
    assert set(fits) == want
