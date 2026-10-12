"""Car setups per track (``pitwall.carsetup``): catalogue validation, recommendation building and selection, the
driver's setup vs recommended, setup experiments and the ``/api/carsetup`` API.

Logic tests use a small in-test catalogue (``_mini``) whose values are made up for the test and say so; tests of
the packaged catalogue check the real, sourced data (``data/f1_25_setups.json``), and one test diffs the setup
decoded from the real PS5 Austria capture (recorded tier).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.analysis.distance import to_distance_domain
from pitwall.analysis.track import build_track_model
from pitwall.api.routes_carsetup import router
from pitwall.carsetup import experiments as exps
from pitwall.carsetup.build import STABLE_ADJUST, build_recommendations, is_current, medoid, summary
from pitwall.carsetup.catalog import (
    DEFAULT_PATH,
    Catalog,
    CatalogError,
    load_catalog,
    parse_catalog,
)
from pitwall.carsetup.compare import diff_setup, stored_values
from pitwall.carsetup.context import conditions_for, guess_car_format, session_context, session_kind
from pitwall.carsetup.facts import setup_facts
from pitwall.carsetup.recommend import (
    CAVEAT,
    RecommendationUnavailable,
    SetupRequest,
    SetupRequestError,
    default_style,
    parse_track_id,
    recommend,
)
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.model.telemetry import CarSetup, Game, SetupParameter
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from tests.conftest import DecodedSession

# ---------------------------------------------------------------------------------------------- mini catalogue
# Made-up ranges and setups for logic tests only (NOT game data).
_RANGES = {
    "front_wing": {"min": 0, "max": 50, "step": 1},
    "rear_wing": {"min": 0, "max": 50, "step": 1},
    "diff_on_throttle": {"min": 10, "max": 100, "step": 5},
    "diff_off_throttle": {"min": 10, "max": 100, "step": 5},
    "front_camber": {"min": -3.5, "max": -2.5, "step": 0.1},
    "tyre_pressure_fl": {"min": 22.5, "max": 29.5, "step": 0.1},
}
_PARAMS = [
    ("front_wing", "Front Wing Aero", "Aerodynamics", 1, None, 0),
    ("rear_wing", "Rear Wing Aero", "Aerodynamics", 2, None, 0),
    ("diff_on_throttle", "Differential Adjustment On Throttle", "Transmission", 3, "%", 0),
    ("diff_off_throttle", "Differential Adjustment Off Throttle", "Transmission", 4, "%", 0),
    ("front_camber", "Front Camber", "Suspension Geometry", 5, "deg", 2),
    ("tyre_pressure_fl", "Front Left Tyre Pressure", "Tyres", 6, "psi", 1),
]


def _setup(sid: str, values: dict[str, float], **kw: Any) -> dict[str, Any]:
    return {
        "id": sid,
        "source": kw.pop("source", "site-a"),
        "url": f"https://example.test/{sid}",
        "author": "tester",
        "published": kw.pop("published", "2026-08-01"),
        "patch": kw.pop("patch", "1.25"),
        "car_format": kw.pop("car_format", "f1_2025"),
        "track_id": kw.pop("track_id", 17),
        "session": kw.pop("session", "race"),
        "conditions": kw.pop("conditions", "dry"),
        "style": kw.pop("style", None),
        "input": None,
        "values": values,
        "verified": "2026-10-10",
        "notes": None,
        **kw,
    }


def _mini(setups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fmt = {
        "label": "Test cars",
        "description": "made-up format for tests",
        "latest_handling_patch": {"version": "1.20", "date": "2026-06-03", "source": "test", "note": "test"},
        "tracks": [17, 7],
        "ranges": {
            k: {**v, "confidence": "high", "sources": ["test"], "min_confirmed": True, "max_confirmed": True}
            for k, v in _RANGES.items()
        },
        "notes": [],
    }
    return {
        "schema_version": 1,
        "game": "f1_25",
        "updated": "2026-10-10",
        "research_doc": "docs/research/f1-car-setups.md",
        "formats": {"f1_2025": fmt, "f1_2026": {**copy.deepcopy(fmt), "label": "Test 2026 cars"}},
        "parameters": [
            {
                "key": k,
                "label": label,
                "group": group,
                "order": order,
                "unit": unit,
                "decimals": dec,
                "udp_to_menu": "identity",
                "higher": f"raising {k} does X.",
                "lower": f"lowering {k} does Y.",
                "sources": ["test"],
            }
            for k, label, group, order, unit, dec in _PARAMS
        ],
        "sources": [
            {
                "id": sid,
                "name": sid.upper(),
                "url": f"https://{sid}.test",
                "kind": "setup_site",
                "terms_url": None,
                "terms": "test",
                "use_policy": policy,
                "accessed": "2026-10-10",
            }
            for sid, policy in (("site-a", "use"), ("site-b", "use_limited"), ("site-x", "do_not_use"))
        ],
        "source_setups": setups if setups is not None else _BASE_SETUPS,
        "rules": [{"id": "stable_v1", "description": "test rule", "sources": ["test"]}],
        "recommendations": [],
    }


_V1 = {"front_wing": 10, "rear_wing": 12, "diff_on_throttle": 50, "diff_off_throttle": 50, "front_camber": -3.5}
_BASE_SETUPS = [
    _setup("a-1", {**_V1, "tyre_pressure_fl": 24.3}),
    _setup("a-2", {**_V1, "front_wing": 12, "tyre_pressure_fl": 24.5}, source="site-b"),
    _setup("a-3", {**_V1, "front_wing": 30, "rear_wing": 30, "tyre_pressure_fl": 22.5}),
    _setup("q-1", {**_V1, "front_wing": 14}, session="qualifying"),
    _setup("w-1", {**_V1, "front_wing": 25, "rear_wing": 25}, conditions="wet", session="both"),
    _setup("s-1", {**_V1, "diff_on_throttle": 30}, style="stable", track_id=7),
    _setup("b-7", _V1, track_id=7),
    _setup("old-1", {**_V1, "front_wing": 40}, patch="1.10", published="2025-07-01", track_id=7),
    _setup("n26-1", {**_V1, "front_wing": 20}, car_format="f1_2026"),
]


def _built(setups: list[dict[str, Any]] | None = None) -> Catalog:
    data = _mini(setups)
    data["recommendations"] = build_recommendations(parse_catalog(data))
    return parse_catalog(data)


@pytest.fixture(scope="module")
def mini() -> Catalog:
    return _built()


# ---------------------------------------------------------------------------------------------- validation
def test_mini_catalogue_parses_and_builds(mini: Catalog) -> None:
    assert mini.param("front_wing") is not None
    assert mini.find("f1_2025", 17, "race", "dry", "balanced") is not None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["source_setups"][0]["values"].update(front_wing=51), "outside"),
        (lambda d: d["source_setups"][0]["values"].update(front_camber=-3.45), "step"),
        (lambda d: d["source_setups"][0].update(source="site-x"), "do_not_use"),
        (lambda d: d["source_setups"][0].update(track_id=42), "not drivable"),
        (lambda d: d["source_setups"][0].update(conditions="damp"), "conditions"),
        (lambda d: d["source_setups"][0]["values"].update(ballast=6), "no range"),
        (lambda d: d["formats"]["f1_2025"]["ranges"]["front_wing"].update(sources=[]), "at least one source"),
        (lambda d: d["formats"]["f1_2025"]["ranges"]["front_wing"].update(step=0.7), "not reachable"),
        (lambda d: d["parameters"].reverse(), "menu order"),
        (lambda d: d["formats"]["f1_2025"]["ranges"]["front_wing"].update(max_confirmed=False), "unconfirmed"),
        (lambda d: d["source_setups"].append(copy.deepcopy(d["source_setups"][0])), "duplicate setup"),
    ],
)
def test_catalogue_validation_rejects_bad_evidence(mutate: Any, message: str) -> None:
    data = _mini(copy.deepcopy(_BASE_SETUPS))
    mutate(data)
    with pytest.raises(CatalogError, match=message):
        parse_catalog(data)


def test_recommendation_values_must_be_sourced_or_flagged_derived() -> None:
    data = _mini(copy.deepcopy(_BASE_SETUPS))
    data["recommendations"] = build_recommendations(parse_catalog(data))
    rec = next(r for r in data["recommendations"] if r["style"] == "balanced")
    bad = copy.deepcopy(data)
    next(r for r in bad["recommendations"] if r["id"] == rec["id"])["values"]["front_wing"]["value"] = 33
    with pytest.raises(CatalogError, match="is not what"):
        parse_catalog(bad)
    bad = copy.deepcopy(data)
    next(r for r in bad["recommendations"] if r["id"] == rec["id"])["values"]["front_wing"]["derived"] = True
    with pytest.raises(CatalogError, match="derived values need a rule"):
        parse_catalog(bad)


# ---------------------------------------------------------------------------------------------- building
def test_single_source_is_used_as_published(mini: Catalog) -> None:
    rec = mini.find("f1_2025", 17, "qualifying", "dry", "balanced")
    assert rec is not None and rec.selection == "single_source" and rec.from_setup == "q-1"
    assert rec.values["front_wing"].value == 14 and not rec.values["front_wing"].derived
    assert rec.values["front_wing"].confidence == "low"  # one source


def test_medoid_picks_the_most_representative_whole_setup(mini: Catalog) -> None:
    rec = mini.find("f1_2025", 17, "race", "dry", "balanced")
    assert rec is not None and rec.selection == "medoid"
    assert rec.from_setup in ("a-1", "a-2")  # a-3 is the outlier (wings 30)
    fw = rec.values["front_wing"]
    assert fw.value == mini.source_setups[rec.from_setup].values["front_wing"]
    assert set(fw.sources) == {"a-1", "a-2"} and fw.spread == (10, 30) and fw.confidence == "high"
    assert any("Front Wing Aero" in d for d in rec.disagreements)  # 10..30 is > 25 % of 0..50
    assert set(rec.candidates) == {"a-1", "a-2", "a-3"}


def test_medoid_ties_prefer_newest_patch() -> None:
    cat = parse_catalog(
        _mini([_setup("x-old", _V1, patch="1.20"), _setup("x-new", _V1, patch="1.25", published="2026-09-01")])
    )
    assert medoid(list(cat.source_setups.values()), cat.formats["f1_2025"]).id == "x-new"


def test_outdated_setups_are_dropped_when_current_ones_exist(mini: Catalog) -> None:
    rec = mini.find("f1_2025", 7, "race", "dry", "balanced")
    assert rec is not None and "old-1" not in rec.candidates and rec.from_setup == "b-7"


def test_only_outdated_setups_cap_confidence_and_say_so() -> None:
    cat = _built([_setup(f"o-{i}", _V1, patch="1.10", published="2025-07-01") for i in range(3)])
    rec = cat.find("f1_2025", 17, "race", "dry", "balanced")
    assert rec is not None and all(v.confidence == "low" for v in rec.values.values())
    assert any("1.20" in n for n in rec.notes)


def test_is_current_uses_the_patch_or_a_full_publication_date() -> None:
    cat = parse_catalog(_mini())
    s = cat.source_setups["a-1"]
    assert is_current(replace(s, patch="1.20"), "1.20", "2026-06-03")
    assert not is_current(replace(s, patch="1.9"), "1.20", "2026-06-03")
    assert is_current(replace(s, patch=None, published="2026-06-03"), "1.20", "2026-06-03")
    assert not is_current(replace(s, patch=None, published="2026-06"), "1.20", "2026-06-03")
    assert not is_current(replace(s, patch=None, published=None), "1.20", "2026-06-03")


def test_stable_variant_is_derived_with_the_rule_when_no_source_labels_one(mini: Catalog) -> None:
    bal = mini.find("f1_2025", 17, "race", "dry", "balanced")
    st = mini.find("f1_2025", 17, "race", "dry", "stable")
    assert bal is not None and st is not None and st.selection == "derived" and st.base == bal.id
    adjusted = [k for k in STABLE_ADJUST if k in bal.values]
    assert adjusted == ["rear_wing", "diff_on_throttle", "diff_off_throttle"]  # the mini catalogue has no ARB range
    for key in adjusted:
        v = st.values[key]
        assert v.derived and v.rule == "stable_v1" and v.confidence == "low" and not v.sources
        assert v.value == (bal.values[key].value or 0) + STABLE_ADJUST[key]
    assert not st.values["front_wing"].derived and st.values["front_wing"] == bal.values["front_wing"]


def test_stable_derivation_clamps_to_the_range() -> None:
    cat = _built([_setup("c-1", {**_V1, "rear_wing": 50, "diff_on_throttle": 10, "diff_off_throttle": 100})])
    st = cat.find("f1_2025", 17, "race", "dry", "stable")
    assert st is not None and not st.values["diff_on_throttle"].derived  # already at the stable end
    assert st.values["diff_on_throttle"].value == 10 and st.values["diff_off_throttle"].value == 100
    assert "no change was needed" in st.notes[0]


def test_a_labelled_stable_setup_beats_derivation(mini: Catalog) -> None:
    st = mini.find("f1_2025", 7, "race", "dry", "stable")
    assert st is not None and st.from_setup == "s-1" and st.selection == "single_source"


def test_wet_is_never_derived_and_both_session_setups_serve_race_and_qualifying(mini: Catalog) -> None:
    assert mini.find("f1_2025", 7, "race", "wet", "balanced") is None
    for session in ("race", "qualifying"):
        rec = mini.find("f1_2025", 17, session, "wet", "balanced")  # type: ignore[arg-type]
        assert rec is not None and rec.from_setup == "w-1"
    assert mini.find("f1_2025", 17, "qualifying", "dry", "aggressive") is None  # never derived


def test_car_formats_are_never_mixed(mini: Catalog) -> None:
    r25 = mini.find("f1_2025", 17, "race", "dry", "balanced")
    r26 = mini.find("f1_2026", 17, "race", "dry", "balanced")
    assert r25 is not None and r26 is not None
    assert "n26-1" not in r25.candidates and r26.candidates == ("n26-1",)
    assert mini.find("f1_2026", 7, "race", "dry", "balanced") is None


# ---------------------------------------------------------------------------------------------- selection
def test_style_follows_skill() -> None:
    assert default_style("beginner")[0] == "stable"
    assert default_style("intermediate")[0] == "balanced"
    assert default_style(None)[0] == "balanced"


def test_recommend_beginner_gets_stable_first(mini: Catalog) -> None:
    res = recommend(mini, SetupRequest("f1_2025", 17, "race", "dry", skill_level="beginner"))
    assert res.style == "stable" and res.requested_style == "stable" and "beginner" in res.style_reason
    assert res.caveat == CAVEAT and [r.order for r in res.rows] == sorted(r.order for r in res.rows)
    assert res.groups == ("Aerodynamics", "Transmission", "Suspension Geometry", "Tyres")
    assert set(res.setups) >= {"a-1", "a-2", "a-3"}


def test_recommend_fallbacks_are_labelled(mini: Catalog) -> None:
    res = recommend(mini, SetupRequest("f1_2025", 17, "race", "dry", style="aggressive"))
    assert res.style == "balanced" and "No aggressive setup" in res.notes[0]
    res = recommend(mini, SetupRequest("f1_2025", 7, "qualifying", "dry", style="balanced"))
    assert res.session == "race" and res.requested_session == "qualifying" and "showing the race setup" in res.notes[0]


def test_recommend_never_serves_dry_for_wet_or_another_car_format(mini: Catalog) -> None:
    with pytest.raises(RecommendationUnavailable) as e:
        recommend(mini, SetupRequest("f1_2025", 7, "race", "wet"))
    assert "does not turn a dry setup into a wet one" in e.value.reason
    assert any(a["conditions"] == "dry" for a in e.value.alternatives)
    with pytest.raises(RecommendationUnavailable):
        recommend(mini, SetupRequest("f1_2026", 7, "race", "dry"))
    with pytest.raises(RecommendationUnavailable, match="not drivable"):
        recommend(mini, SetupRequest("f1_2025", 42, "race", "dry"))


def test_parse_track_id() -> None:
    assert parse_track_id("f1:17") == 17 and parse_track_id("17") == 17 and parse_track_id(17) == 17
    with pytest.raises(SetupRequestError):
        parse_track_id("synthetic:17")


# ---------------------------------------------------------------------------------------------- compare
def _stored(**values: float) -> dict[str, Any]:
    return {k: {"key": k, "value": v, "unit": None} for k, v in values.items()}


def test_diff_explains_each_difference_and_suggests_one_experiment(mini: Catalog) -> None:
    res = recommend(mini, SetupRequest("f1_2025", 17, "race", "dry", style="balanced"))
    rec_fw = res.row("front_wing")
    assert rec_fw is not None and rec_fw.value is not None
    yours = _stored(
        front_wing=rec_fw.value - 8,
        rear_wing=12,
        diff_on_throttle=50,
        diff_off_throttle=50,
        front_camber=-3.5,
        tyre_pressure_fl=24.3,
        fuel_load=10,
        ballast=6,
    )
    d = diff_setup(mini, res, yours)
    fw = next(r for r in d.rows if r.key == "front_wing")
    assert fw.direction == "higher" and fw.delta == 8 and fw.steps == 8 and fw.magnitude == "moderate"
    assert "raising front_wing does X." in fw.explanation and "higher than yours" in fw.explanation
    assert next(r for r in d.rows if r.key == "diff_on_throttle").direction == "same"
    assert d.not_compared == ("ballast", "fuel_load") and not d.out_of_range
    assert d.experiment is not None and d.experiment.key == "front_wing" and "not a fix" in d.experiment.text
    assert d.caveat == CAVEAT and "differ" in d.summary


def test_diff_flags_values_outside_the_car_format_range(mini: Catalog) -> None:
    res = recommend(mini, SetupRequest("f1_2025", 17, "race", "dry", style="balanced"))
    d = diff_setup(mini, res, _stored(front_wing=10, front_camber=-1.0))
    assert d.out_of_range == ("front_camber",) and d.experiment is None
    assert "probably for other cars" in d.summary


def test_diff_only_calls_values_impossible_beyond_confirmed_menu_limits() -> None:
    data = _mini(copy.deepcopy(_BASE_SETUPS))
    data["formats"]["f1_2025"]["ranges"]["front_camber"].update(
        min_confirmed=False, note="observed bound of published setups"
    )
    cat = parse_catalog(data)
    data["recommendations"] = build_recommendations(cat)
    cat = parse_catalog(data)
    res = recommend(cat, SetupRequest("f1_2025", 17, "race", "dry", style="balanced"))
    d = diff_setup(cat, res, _stored(front_wing=10, front_camber=-3.9))
    row = next(r for r in d.rows if r.key == "front_camber")
    assert row.in_range is None and not d.out_of_range and row.direction == "higher"
    assert diff_setup(cat, res, _stored(front_camber=-2.0)).out_of_range == ("front_camber",)


def test_diff_accepts_a_car_setup_and_unknowns(mini: Catalog) -> None:
    res = recommend(mini, SetupRequest("f1_2025", 17, "race", "dry", style="balanced"))
    cs = CarSetup(
        game=Game.F1_25,
        t_recv_ns=0,
        car_id=None,
        track_id="f1:17",
        parameters={"front_wing": SetupParameter(key="front_wing", value=10.0)},
    )
    assert stored_values(cs) == {"front_wing": 10.0}
    d = diff_setup(mini, res, cs)
    rw = next(r for r in d.rows if r.key == "rear_wing")
    assert rw.yours is None and rw.direction == "unknown" and "unknown" in rw.explanation
    empty = diff_setup(mini, res, {})
    assert "not been received" in empty.summary and empty.experiment is None


def test_setup_facts_carry_values_provenance_and_the_caveat(mini: Catalog) -> None:
    res = recommend(mini, SetupRequest("f1_2025", 17, "race", "dry", skill_level="beginner"))
    d = diff_setup(mini, res, _stored(front_wing=20, rear_wing=12, diff_on_throttle=50))
    facts = setup_facts(res, d)
    texts = [t for _, t, _ in facts]
    assert all(topic == "setup" for topic, _, _ in facts)
    assert "Recommended stable dry race setup for Austria" in texts[0] and "SITE-A" in texts[0]
    assert any("pitwall derived" in t for t in texts) and texts[-1] == CAVEAT
    assert setup_facts(None, None, "no wet setup")[0][1] == "Setup recommendation: none (no wet setup)."


# ---------------------------------------------------------------------------------------------- context
@pytest.mark.parametrize(
    ("packet_format", "formula", "car_id", "expected", "certain"),
    [
        (2025, "F1 Modern", "f1:team:0", "f1_2025", True),
        (2025, None, "f1:team:8", "f1_2025", True),
        (2025, "F1 World", "f1:team:41", None, False),  # the real PS5 capture: generic car is ambiguous
        (2025, None, None, None, False),
        (2026, "F1 26", "f1:team:476", "f1_2026", True),
        (2025, None, "f1:team:486", "f1_2026", True),
        (2026, "F1 Modern", "f1:team:3", "f1_2025", True),
        (2026, "F1 World", "f1:team:41", "f1_2025", True),
        (2026, None, "f1:team:41", None, False),
        (2025, "F2", "f1:team:12", None, True),
        (2026, None, "f1:team:490", None, True),
    ],
)
def test_guess_car_format(
    packet_format: int, formula: str | None, car_id: str | None, expected: str | None, certain: bool
) -> None:
    g = guess_car_format(packet_format, formula, car_id)
    assert (g.car_format, g.certain) == (expected, certain) and g.reason


def test_session_kind_and_conditions() -> None:
    assert session_kind("race") == ("race", None)
    assert session_kind("time_trial")[0] == "qualifying" and session_kind("practice")[0] == "race"
    assert session_kind("unknown") == (None, None)
    assert conditions_for({"condition": "light_rain"}) == "wet" and conditions_for({"condition": "overcast"}) == "dry"
    assert conditions_for({}) is None


def test_session_context_explains_unknowns() -> None:
    ctx = session_context(
        {
            "game": "f1_25",
            "track_id": "f1:17",
            "track_name": "Austria",
            "session_type": "race",
            "car_id": "f1:team:41",
            "weather": {"condition": "clear"},
            "info": {"packet_format": 2025},
            "synthetic": True,
        }
    )
    assert (ctx.track_id, ctx.car_format, ctx.session, ctx.conditions) == (17, None, "race", "dry")
    assert "cannot be told apart" in ctx.reasons["car_format"] and any("synthetic" in n for n in ctx.notes)
    other = session_context({"game": "gt7", "track_id": "gt7:1", "info": {}})
    assert "game" in other.reasons and other.track_id is None


# ---------------------------------------------------------------------------------------------- experiments
@pytest.fixture
def store(tmp_path: Path) -> Iterator[SimpleNamespace]:
    db = Database(tmp_path / "carsetup.sqlite3")
    writer = DbWriter(db)
    yield SimpleNamespace(db=db, writer=writer, analyzer=SessionAnalyzer(db))
    writer.close()


def _car_setup(**values: float) -> CarSetup:
    return CarSetup(
        game=Game.F1_25,
        t_recv_ns=1,
        car_id="f1:team:0",
        track_id="f1:17",
        parameters={k: SetupParameter(key=k, value=v) for k, v in values.items()},
    )


def _add_session(
    st: SimpleNamespace, sid: str, decoded: DecodedSession, lap_times: list[int], setup: CarSetup | None
) -> None:
    base = next(lap for lap in decoded.laps if lap.clean)
    info = replace(decoded.info, car_id="f1:team:0", formula="F1 Modern")

    def job(c: Any) -> None:
        repo.insert_session(c, sid, "f1_25", "test", True, None, None)
        repo.update_session_info(c, sid, info)
        for i, t in enumerate(lap_times, start=2):
            repo.insert_lap(c, sid, replace(base, lap_number=i, lap_time_ms=t, flags=set()), None)
        if setup is not None:
            repo.insert_setup(c, sid, setup)

    st.writer.call(job)


def _add_model(st: SimpleNamespace, decoded: DecodedSession) -> None:
    lap = next(lap for lap in decoded.laps if lap.clean)
    info = decoded.info
    assert info.track_id is not None and info.track_length_m is not None
    model = build_track_model(
        "f1_25", info.track_id, info.track_name, info.track_length_m, [to_distance_domain(lap, info.track_length_m)]
    )
    st.writer.call(lambda c: repo.save_track_model(c, model))


def test_experiment_lifecycle(store: SimpleNamespace, mini: Catalog, clean_session: DecodedSession) -> None:
    before_setup = _car_setup(front_wing=10, rear_wing=12, diff_on_throttle=50)
    _add_session(store, "before", clean_session, [80_000, 80_200, 80_100, 80_300], before_setup)
    _add_session(
        store,
        "after",
        clean_session,
        [79_500, 79_600, 79_550, 79_700],
        _car_setup(front_wing=12, rear_wing=12, diff_on_throttle=50),
    )
    _add_model(store, clean_session)

    with pytest.raises(exps.ExperimentError, match="between 0 and 50"):
        exps.propose(store.db, store.writer, mini, before_session_id="before", parameter="front_wing", to_value=55)
    with pytest.raises(exps.ExperimentError, match="already"):
        exps.propose(store.db, store.writer, mini, before_session_id="before", parameter="front_wing", to_value=10)
    with pytest.raises(exps.ExperimentError, match="not a setup-sheet parameter"):
        exps.propose(store.db, store.writer, mini, before_session_id="before", parameter="fuel_load", to_value=5)
    with pytest.raises(exps.ExperimentNotFound):
        exps.propose(store.db, store.writer, mini, before_session_id="nope", parameter="front_wing", to_value=12)

    e = exps.propose(store.db, store.writer, mini, before_session_id="before", parameter="front_wing", to_value=12)
    assert e["status"] == "proposed" and e["from_value"] == 10 and e["to_value"] == 12
    assert e["track_id"] == clean_session.info.track_id and "nothing else changed" in e["hypothesis"]
    with pytest.raises(exps.ExperimentError, match="start") as conflict:
        exps.conclude(store.db, store.writer, store.analyzer, mini, e["id"])
    assert conflict.value.conflict
    with pytest.raises(exps.ExperimentError, match="new session"):
        exps.start(store.db, store.writer, e["id"], "before")

    e = exps.start(store.db, store.writer, e["id"], "after")
    assert e["status"] == "running" and e["after_session_id"] == "after"
    e = exps.conclude(store.db, store.writer, store.analyzer, mini, e["id"])
    assert e["status"] == "concluded"
    cmp = e["after_metrics"]["comparison"]
    assert cmp["verdict"] == "faster" and cmp["median_delta_s"] == pytest.approx(-0.575)
    assert cmp["setup_check"] == {"applied": True, "other_changes": [], "note": None}
    assert cmp["reference_lap_id"] is not None and isinstance(cmp["corners"], list) and cmp["corners"]
    assert e["before_metrics"]["clean_laps"] == 4 and e["before_metrics"]["setup"]["front_wing"] == 10
    assert "Front Wing Aero 10 -> 12." in e["conclusion"] and "indication, not proof" in e["conclusion"]
    assert [x["id"] for x in exps.list_experiments(store.db, session_id="after")] == [e["id"]]
    with pytest.raises(exps.ExperimentError) as done:
        exps.abandon(store.db, store.writer, e["id"])
    assert done.value.conflict


def test_experiment_verdicts_stay_inconclusive_without_evidence(
    store: SimpleNamespace, mini: Catalog, clean_session: DecodedSession
) -> None:
    _add_session(store, "b", clean_session, [80_000, 80_100, 80_200], _car_setup(front_wing=10, rear_wing=12))
    _add_session(store, "a", clean_session, [79_000, 79_100, 79_200], _car_setup(front_wing=12, rear_wing=20))
    _add_session(store, "short", clean_session, [79_000], _car_setup(front_wing=12, rear_wing=12))
    e = exps.propose(store.db, store.writer, mini, before_session_id="b", parameter="front_wing", to_value=12)
    exps.start(store.db, store.writer, e["id"], "a")
    e = exps.conclude(store.db, store.writer, store.analyzer, mini, e["id"])
    cmp = e["after_metrics"]["comparison"]
    assert cmp["verdict"] == "inconclusive" and "other setup parameters changed" in cmp["reason"]
    assert cmp["setup_check"]["other_changes"][0]["key"] == "rear_wing"
    assert "Also changed: Rear Wing Aero." in e["conclusion"]

    e2 = exps.propose(store.db, store.writer, mini, before_session_id="b", parameter="front_wing", to_value=12)
    exps.start(store.db, store.writer, e2["id"], "short")
    e2 = exps.conclude(store.db, store.writer, store.analyzer, mini, e2["id"])
    assert e2["after_metrics"]["comparison"]["verdict"] == "inconclusive"
    assert "at least 3 clean laps" in e2["after_metrics"]["comparison"]["reason"]

    e3 = exps.propose(store.db, store.writer, mini, before_session_id="b", parameter="front_wing", to_value=13)
    e3 = exps.abandon(store.db, store.writer, e3["id"], "rain came")
    assert e3["status"] == "abandoned" and e3["conclusion"] == "Abandoned: rain came"


# ---------------------------------------------------------------------------------------------- API
@pytest.fixture
def api(
    store: SimpleNamespace, mini: Catalog, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, SimpleNamespace]]:
    import pitwall.api.routes_carsetup as routes

    monkeypatch.setattr(routes, "load_catalog", lambda: mini)
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(db=store.db, writer=store.writer)
    with TestClient(app) as client:
        yield client, store


def test_api_catalog_and_recommendation(api: tuple[TestClient, SimpleNamespace]) -> None:
    client, store = api
    body = client.get("/api/carsetup/catalog").json()
    assert [f["id"] for f in body["formats"]] == ["f1_2025", "f1_2026"]
    assert body["formats"][0]["tracks"][0] == {"id": 17, "name": "Austria"}
    assert body["parameters"][0]["ranges"]["f1_2025"]["max"] == 50 and body["caveat"] == CAVEAT
    assert {
        "car_format": "f1_2025",
        "track_id": 17,
        "session": "race",
        "conditions": "dry",
        "style": "stable",
        "derived": True,
    } in body["available"]

    r = client.get("/api/carsetup/recommendation", params={"car_format": "f1_2025", "track_id": "f1:17"})
    assert r.status_code == 200 and r.json()["style"] == "balanced" and r.json()["rows"][0]["key"] == "front_wing"
    did = store.writer.call(lambda c: repo.insert_driver(c, "Rookie", {"skill_level": "beginner"}))
    r = client.get("/api/carsetup/recommendation", params={"car_format": "f1_2025", "track_id": 17, "driver_id": did})
    assert r.json()["style"] == "stable" and r.json()["skill_source"] == "driver"
    r = client.get("/api/carsetup/recommendation", params={"car_format": "f1_2025", "track_id": 7, "conditions": "wet"})
    assert r.status_code == 404 and "dry" in r.json()["detail"]["reason"] and r.json()["detail"]["alternatives"]
    r = client.get("/api/carsetup/recommendation", params={"car_format": "f1_2099", "track_id": 17})
    assert r.status_code == 422
    assert (
        client.get(
            "/api/carsetup/recommendation", params={"car_format": "f1_2025", "track_id": 17, "driver_id": 999}
        ).status_code
        == 404
    )


def test_api_session_setup_needs_and_diff(
    api: tuple[TestClient, SimpleNamespace], clean_session: DecodedSession
) -> None:
    client, store = api
    assert client.get("/api/carsetup/sessions/nope").status_code == 404
    _add_session(store, "s1", clean_session, [80_000, 80_100, 80_200], _car_setup(front_wing=20, rear_wing=12))
    store.writer.call(lambda c: c.execute("UPDATE sessions SET car_id='f1:team:41', track_id='f1:17' WHERE id='s1'"))
    store.writer.call(lambda c: c.execute("UPDATE sessions SET info=json_remove(info, '$.formula') WHERE id='s1'"))
    body = client.get("/api/carsetup/sessions/s1").json()
    assert body["needs"] == ["car_format"] and body["recommendation"] is None and body["diff"] is None
    assert "choose car format" in body["unavailable"]["reason"] and body["setup"]["params"]["front_wing"]["value"] == 20

    body = client.get("/api/carsetup/sessions/s1", params={"car_format": "f1_2025", "style": "balanced"}).json()
    assert body["needs"] == [] and body["recommendation"]["track_id"] == 17
    fw = next(r for r in body["diff"]["rows"] if r["key"] == "front_wing")
    assert fw["yours"] == 20 and fw["direction"] in ("higher", "lower") and body["diff"]["caveat"] == CAVEAT
    assert client.get("/api/carsetup/sessions/s1", params={"conditions": "damp"}).status_code == 422


def test_api_experiment_lifecycle(api: tuple[TestClient, SimpleNamespace], clean_session: DecodedSession) -> None:
    client, store = api
    _add_session(store, "b", clean_session, [80_000, 80_200, 80_100], _car_setup(front_wing=10))
    _add_session(store, "a", clean_session, [79_000, 79_200, 79_100], _car_setup(front_wing=12))
    r = client.post(
        "/api/carsetup/experiments", json={"before_session_id": "b", "parameter": "front_wing", "to_value": 99}
    )
    assert r.status_code == 422
    r = client.post(
        "/api/carsetup/experiments", json={"before_session_id": "zz", "parameter": "front_wing", "to_value": 12}
    )
    assert r.status_code == 404
    r = client.post(
        "/api/carsetup/experiments",
        json={"before_session_id": "b", "parameter": "front_wing", "to_value": 12, "extra": 1},
    )
    assert r.status_code == 422
    r = client.post(
        "/api/carsetup/experiments", json={"before_session_id": "b", "parameter": "front_wing", "to_value": 12}
    )
    assert r.status_code == 201
    eid = r.json()["id"]
    assert client.post(f"/api/carsetup/experiments/{eid}/conclude").status_code == 409
    assert client.post(f"/api/carsetup/experiments/{eid}/start", json={"after_session_id": "a"}).json()["status"] == (
        "running"
    )
    done = client.post(f"/api/carsetup/experiments/{eid}/conclude").json()
    assert done["status"] == "concluded" and done["after_metrics"]["comparison"]["verdict"] == "faster"
    assert client.get(f"/api/carsetup/experiments/{eid}").json()["conclusion"] == done["conclusion"]
    listed = client.get("/api/carsetup/experiments", params={"track_id": clean_session.info.track_id}).json()
    assert [x["id"] for x in listed] == [eid]
    assert client.get("/api/carsetup/experiments", params={"status": "bogus"}).status_code == 422
    assert client.post(f"/api/carsetup/experiments/{eid}/abandon", json={}).status_code == 409
    assert client.get("/api/carsetup/experiments/9999").status_code == 404


# ---------------------------------------------------------------------------------------------- engineer wiring
def _f1_session(**over: Any) -> dict[str, Any]:
    return {
        "id": "s",
        "game": "f1_25",
        "track_id": "f1:17",
        "track_name": "Austria",
        "session_type": "race",
        "car_id": "f1:team:0",
        "weather": {"condition": "clear"},
        "info": {"packet_format": 2025, "formula": "F1 Modern"},
        **over,
    }


def test_session_setup_facts_feed_the_engineer(mini: Catalog, monkeypatch: pytest.MonkeyPatch) -> None:
    from pitwall.ai.engineer import Intent, deterministic_answer
    from pitwall.ai.facts import FactSheet
    from pitwall.carsetup import facts as setup_facts_mod

    monkeypatch.setattr(setup_facts_mod, "load_catalog", lambda: mini)
    stored = {"params": _stored(front_wing=20, rear_wing=12, diff_on_throttle=50, diff_off_throttle=50)}
    entries = setup_facts_mod.session_setup_facts(_f1_session(), stored, "beginner")
    texts = [t for _, t, _ in entries]
    assert texts[0].startswith("Recommended stable dry race setup for Austria")
    assert any(t.startswith("Driver's setup vs recommended") for t in texts) and texts[-1] == CAVEAT

    sheet = FactSheet()
    for topic, text, data in entries:
        sheet.add(topic, text, data)
    answer = deterministic_answer(Intent("setup"), sheet.select({"setup"}), sheet)
    assert answer.startswith("Before changing the setup, let's rule out technique.")
    assert "Driver's setup vs recommended" in answer and "[F" in answer

    ambiguous = setup_facts_mod.session_setup_facts(
        _f1_session(car_id="f1:team:41", info={"packet_format": 2025}), None
    )
    assert len(ambiguous) == 1 and "cannot be told apart" in ambiguous[0][1]
    wet = setup_facts_mod.session_setup_facts(_f1_session(track_id="f1:7", weather={"condition": "heavy_rain"}), None)
    assert "does not turn a dry setup into a wet one" in wet[0][1]
    assert setup_facts_mod.session_setup_facts(_f1_session(game="gt7"), None) == []


def test_router_is_mounted_in_the_app(tmp_path: Path) -> None:
    from pitwall.api.app import create_app
    from pitwall.config import Settings

    app = create_app(Settings(data_dir=tmp_path, llm_enabled=False), start_udp=False)
    with TestClient(app, client=("127.0.0.1", 40000)) as client:
        assert client.get("/api/carsetup/experiments").json() == []
        assert client.get("/api/carsetup/sessions/nope").status_code == 404


# ---------------------------------------------------------------------------------------------- packaged catalogue
@pytest.fixture(scope="module")
def cat() -> Catalog:
    return load_catalog()


def test_packaged_catalogue_stores_evidence_and_builds_recommendations_at_load(cat: Catalog) -> None:
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    assert "recommendations" not in data  # derived data is never stored, so it cannot drift from the evidence
    evidence = parse_catalog(data)
    assert not evidence.recommendations and cat.recommendations
    rebuilt = parse_catalog({**data, "recommendations": build_recommendations(evidence)})
    assert rebuilt.recommendations == cat.recommendations
    assert "cited setups ->" in summary(cat)


def test_packaged_values_are_in_range_on_step_and_sourced(cat: Catalog) -> None:
    assert set(cat.formats) == {"f1_2025", "f1_2026", "f2"}
    assert cat.source_setups and cat.recommendations
    for s in cat.source_setups.values():
        assert cat.sources[s.source].use_policy != "do_not_use"
        for k, v in s.values.items():
            rng = cat.range(s.car_format, k)
            assert rng is not None and rng.contains(v) and rng.on_step(v), (s.id, k, v)
    for rec in cat.recommendations.values():
        for k, v in rec.values.items():
            if v.value is None:
                continue
            rng = cat.range(rec.car_format, k)
            assert rng is not None and rng.contains(v.value) and rng.on_step(v.value), (rec.id, k)
            assert v.derived or (v.from_setup is not None and cat.source_setups[v.from_setup].values[k] == v.value)
            assert not v.derived or (v.rule is not None and v.rule in cat.rules)
            if not v.derived:  # its setup is for the same car format, track and conditions
                src = cat.source_setups[v.from_setup or ""]
                assert (src.car_format, src.track_id, src.conditions) == (rec.car_format, rec.track_id, rec.conditions)


def test_packaged_parameters_cover_the_udp_setup(cat: Catalog) -> None:
    udp_keys = {  # the keys the F1 adapter emits from the CarSetups packet
        "front_wing",
        "rear_wing",
        "diff_on_throttle",
        "diff_off_throttle",
        "front_camber",
        "rear_camber",
        "front_toe",
        "rear_toe",
        "front_suspension",
        "rear_suspension",
        "front_arb",
        "rear_arb",
        "front_ride_height",
        "rear_ride_height",
        "brake_pressure",
        "brake_bias",
        "engine_braking",
        "tyre_pressure_rl",
        "tyre_pressure_rr",
        "tyre_pressure_fl",
        "tyre_pressure_fr",
        "ballast",
        "fuel_load",
    }
    keys = {p.key for p in cat.parameters}
    assert keys <= udp_keys
    assert {"front_wing", "rear_wing", "brake_bias", "front_camber"} <= keys
    for p in cat.parameters:
        assert p.higher.strip() and p.lower.strip() and p.sources
    assert [p.order for p in cat.parameters] == sorted(p.order for p in cat.parameters)
    for fmt in cat.formats.values():  # every parameter is a menu item of both car formats
        assert set(fmt.ranges) == keys


def test_packaged_catalogue_covers_every_track_and_never_mixes_formats(cat: Catalog) -> None:
    for fid, fmt in cat.formats.items():
        # F2: no handling patch is known, and the stable rule (F1 guides) is not applied to F2 cars
        assert fmt.tracks and (fmt.latest_handling_patch is None) is (fid == "f2")
        if fmt.latest_handling_patch is not None:
            assert fmt.latest_handling_patch.version
        for track in fmt.tracks:
            assert cat.find(fid, track, "race", "dry", "balanced") is not None, (fid, track)
            assert (cat.find(fid, track, "race", "dry", "stable") is not None) is (fid != "f2"), (fid, track)
    for rec in cat.recommendations.values():
        for sid in rec.candidates:
            s = cat.source_setups[sid]
            assert (s.car_format, s.track_id, s.conditions) == (rec.car_format, rec.track_id, rec.conditions)
            assert s.covers(rec.session)


def test_api_serves_the_packaged_catalogue(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.sqlite3")
    writer = DbWriter(db)
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(db=db, writer=writer)
    try:
        with TestClient(app) as client:
            body = client.get("/api/carsetup/catalog").json()
        assert {f["id"] for f in body["formats"]} == {"f1_2025", "f1_2026", "f2"} and body["sources"]
        f2 = next(f for f in body["formats"] if f["id"] == "f2")
        assert f2["label"] == "F2 cars (2024 and 2025 seasons)" and f2["latest_handling_patch"] is None
    finally:
        writer.close()
