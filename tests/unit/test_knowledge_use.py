"""The technique graph in use (spec: technique knowledge graph, section 3): every observation carries its ``knowledge``
annotation on the live path and in stored-session analysis; a fault that does not fit the driver is never picked,
never on the coach card and never a habit (and still makes its corner unclean); coaching on the eight live kinds is
unchanged on F1; the AI engineer's knowledge facts are grounded, an answer built from them passes and an invented
technique claim fails; and ``GET /api/technique/knowledge?session=<id>`` adds the session's Context, style and
per-node fit.

The laps are the SYNTHETIC coaching demo (``demo_session``): results prove the wiring against known answers, never
game compatibility.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import orjson
import pytest
from fastapi.testclient import TestClient

from pitwall.ai.engineer import RaceEngineer, detect_intent
from pitwall.ai.facts import Fact, build_fact_sheet
from pitwall.ai.grounding import check_grounding
from pitwall.coach.selection import CoachSelection
from pitwall.config import Settings
from pitwall.core import lap_processor as lp
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.drivers import DriverService
from pitwall.knowledge.annotate import card_slim, slim
from pitwall.knowledge.facts import CONTEXT_PREFIX, FAULT_PREFIX, TOPIC
from pitwall.knowledge.graph import CONTEXT_KEYS, TechniqueGraph, load_graph
from pitwall.storage.db import Database, DbWriter
from tests.coachref_support import copy_lap, lap_ctx, new_session
from tests.conftest import DecodedSession

pytestmark = pytest.mark.synthetic

CORNERS = ["T1", "T2", "T3", "T4", "T5", "T6"]
COMP = {"compatibility": {"ok": True, "blocking": [], "warnings": []}}
NOT_FOR_YOU = {"fault": "x", "applies": False, "why_not": "Only for: H-pattern gearbox (gearbox not known)"}


def pt(corner: str, kind: str, lap: int, *, fits: bool = True, ratio: float | None = 0.8) -> dict[str, Any]:
    """A big corrective observation dict; ``fits`` False: the technique graph says it is not for this driver."""
    o: dict[str, Any] = {
        "id": f"L{lap}:{corner}:{kind}",
        "kind": kind,
        "corner": corner,
        "corner_label": corner,
        "lap_number": lap,
        "ref_lap_number": 1,
        "metric": "min_speed_delta_kph",
        "value": -12.0,
        "unit": "km/h",
        "impact_s": 0.4,
        "confidence": 0.9,
        "priority": 0.36,
        "positive": False,
        "consistency": None if ratio is None else "3 of the last 3 laps",
        "consistency_ratio": ratio,
        "text": f"{corner}: minimum speed is 12 km/h lower than your reference.",
        "text_simple": f"{corner}: you were 12 km/h slower.",
        "short": "12 km/h slower mid-corner",
    }
    if not fits:
        o["knowledge"] = dict(NOT_FOR_YOU)
    return o


def lap_of(n: int, *points: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Lap ``n`` (lap id 100 + n), compared with reference lap id 1 (a lap with none of these points)."""
    return {"lap_id": 100 + n, "lap_number": n}, list(points)


def select(sel: CoachSelection, n: int, *points: dict[str, Any]) -> dict[str, Any]:
    times = {c: 10.3 if any(p["corner"] == c for p in points) else 10.0 for c in CORNERS}
    return sel.select(*lap_of(n, *points), compared=True, corners=CORNERS, ref_lap_id=1, corner_times=times)


# ---------------------------------------------------------------------------------------------- coach selection
def test_a_point_that_does_not_fit_is_not_picked_not_on_the_card_and_no_habit() -> None:
    sel = CoachSelection()
    for n in (1, 2, 3, 4):
        block = select(sel, n, pt("T6", "low_min_speed", n, fits=False, ratio=None if n < 3 else 1.0))
        assert block["picked"] == [] and "T6" not in block["by_corner"], n
        assert block["habits"] == [] and block["focus"] == [], n
    # the same laps with points that fit: the habit is announced and on the card
    sel = CoachSelection()
    blocks = [select(sel, n, pt("T6", "low_min_speed", n, ratio=None if n < 3 else 1.0)) for n in (1, 2, 3)]
    assert blocks[-1]["picked"] and blocks[-1]["by_corner"]["T6"]["knowledge"] is None
    assert [h["status"] for h in blocks[-1]["habits"]] == ["focus"]


def test_a_point_that_does_not_fit_still_makes_its_corner_unclean() -> None:
    """A habit is sorted only on laps clean at its corner: a point there that does not fit the driver is no habit,
    but the corner lost time on that lap."""

    def run(*later: dict[str, Any] | None) -> list[str]:
        sel = CoachSelection()
        for n in (1, 2, 3):
            select(sel, n, pt("T6", "low_min_speed", n, ratio=None if n < 3 else 1.0))
        events: list[str] = []
        for i, p in enumerate(later):
            block = select(sel, 4 + i, *(() if p is None else (p,)))
            events += [str(x.get("habit_event")) for x in block["picked"]]
        return events

    assert run(None, None) == ["fixed"]
    unclean = [pt("T6", "coasting", n, fits=False, ratio=None) for n in (4, 5)]
    assert run(*unclean) == []


def test_the_session_recap_does_not_rank_a_point_that_does_not_fit() -> None:
    from pitwall.drivers import coaching_limits
    from pitwall.motivation.recap import rank_points

    observations = {101: [pt("T6", "low_min_speed", 1, fits=False), pt("T2", "low_min_speed", 1)]}
    assert [p.corner for p in rank_points(observations, 1, False, coaching_limits("advanced"))] == ["T2"]


def test_habit_lines_carry_this_laps_knowledge() -> None:
    sel = CoachSelection()
    k = {"fault": "low_min_speed", "applies": True, "why_not": None, "causes": [], "advice": None}
    for n in (1, 2):
        select(sel, n, pt("T6", "low_min_speed", n, ratio=None))
    third = {**pt("T6", "low_min_speed", 3, ratio=1.0), "knowledge": k}
    block = select(sel, 3, third)
    (line,) = block["picked"]
    assert line["habit_event"] == "announce" and line["knowledge"]["fault"] == "low_min_speed"


def test_live_snapshots_carry_the_slim_annotation() -> None:
    """Twenty snapshots a second carry the coach card's slim copy; the radio and the lap notification keep the full
    annotation (causes with their signals, advice ids)."""
    full = {
        "fault": "low_min_speed",
        "name": "Low minimum speed",
        "status": "live",
        "tier": "live",
        "applies": True,
        "why_not": None,
        "causes": [
            {
                "id": "over_braking",
                "name": "Over-braking",
                "tier": "brief",
                "evidence": [{"signal": "brake_point_delta_m", "test": "braked earlier", "value": -12.0, "unit": "m"}],
                "advice": {"radio": None, "screen": "Slowed more on the way in", "review": "...", "ids": {}},
            }
        ],
        "advice": {"radio": "r", "screen": "s", "review": "v", "ids": {}, "tailored": {}},
        "digest": "abc",
    }
    live = LiveState()
    live.reset_session("s", "test", False)
    notes: list[dict[str, Any]] = []
    live.subscribe(lambda kind, p: notes.append(p) if kind == "lap" else None)
    o = {**pt("T6", "low_min_speed", 2), "knowledge": full}
    live.on_lap_result({"lap_id": 102, "lap_number": 2}, [o, pt("T2", "low_min_speed", 2)], None)
    snap = live.snapshot()["observations"]
    # the snapshot's observations: only what the card reads from one (fits, the first cause's screen line)
    assert (
        snap[0]["knowledge"]
        == card_slim(full)
        == {
            "fault": "low_min_speed",
            "applies": True,
            "causes": [{"id": "over_braking", "name": "Over-braking", "screen": "Slowed more on the way in"}],
        }
    )
    assert "knowledge" not in snap[1]  # an observation without an annotation is sent as it is
    assert live.observations[0]["knowledge"] is full and notes[0]["observations"][0]["knowledge"] is full
    # the coach block's copy keeps the annotation's shape, the evidence as measured values without their sentences
    s = slim(full)
    assert s is not None and set(s) == {"fault", "applies", "why_not", "causes", "advice"}
    assert s["causes"][0]["evidence"] == [{"signal": "brake_point_delta_m", "value": -12.0, "unit": "m"}]
    assert len(orjson.dumps(snap[0]["knowledge"])) < len(orjson.dumps(s)) < len(orjson.dumps(full))


# ---------------------------------------------------------------------------------------------- the live path
def _process(
    tmp_path: Path, demo: DecodedSession, *, graph: bool, skill: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Database, str]:
    db = Database(tmp_path / f"k-{graph}-{skill}.sqlite3")
    writer = DbWriter(db)
    live = LiveState()
    proc = LapProcessor(db, writer, live)
    driver_id = DriverService(db, writer).create("Sam", skill_level=skill).id if skill else None
    sid = new_session(writer, driver_id, demo.info, f"s-{graph}-{skill}")
    live.reset_session(sid, "test", False)
    blocks: list[dict[str, Any]] = []
    live.subscribe(lambda kind, p: blocks.append(p["coach"]) if kind == "lap" else None)
    try:
        results = [proc.process(LapJob(sid, copy_lap(lap), lap_ctx(demo.info))) for lap in demo.laps]
    finally:
        writer.close()
    return results, blocks, db, sid


def _without_knowledge(block: dict[str, Any]) -> dict[str, Any]:
    def strip(p: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in p.items() if k != "knowledge"}

    return {
        **block,
        "picked": [strip(p) for p in block["picked"]],
        "by_corner": {c: strip(p) for c, p in block["by_corner"].items()},
    }


@pytest.fixture(scope="module")
def processed(
    tmp_path_factory: pytest.TempPathFactory, demo_session: DecodedSession
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Database, str]:
    return _process(tmp_path_factory.mktemp("knowledge_use"), demo_session, graph=True, skill="beginner")


def test_the_lap_processor_annotates_every_observation(
    processed: tuple[list[dict[str, Any]], list[dict[str, Any]], Database, str],
) -> None:
    results, blocks, _, _ = processed
    observations = [o for r in results for o in r["observations"]]
    assert observations, "the coaching demo has coaching points"
    for o in observations:
        k = o["knowledge"]
        assert k["fault"] == o["kind"] and k["applies"] is True and k["why_not"] is None, o["id"]
        assert k["advice"]["ids"]["review"].endswith("_beginner"), o["id"]  # the seated driver is a beginner
    compared = [r["comparison"] for r in results if r["comparison"] is not None]
    k = compared[-1]["knowledge"]
    assert set(k["context"]) == set(CONTEXT_KEYS) and k["digest"] == load_graph().digest
    assert k["context"]["skill"] == "beginner" and k["context"]["game"] == "f1" and k["context"]["car_family"] == "f1"
    assert k["style"]["laps"] >= 2 and k["context"]["braking_style"] == k["style"]["braking_style"] is not None
    points = [p for b in blocks for p in [*b["picked"], *b["by_corner"].values()]]
    lines = [p for p in points if p.get("habit_event") != "fixed"]
    assert lines and all(p["knowledge"] is not None and p["knowledge"]["applies"] for p in lines)
    # a "sorted" line is about the habit, not a point of this lap: no lap's causes on it
    assert all(p["knowledge"] is None for p in points if p.get("habit_event") == "fixed")


def test_coaching_on_the_live_kinds_is_unchanged_on_f1(
    tmp_path: Path,
    demo_session: DecodedSession,
    monkeypatch: pytest.MonkeyPatch,
    processed: tuple[list[dict[str, Any]], list[dict[str, Any]], Database, str],
) -> None:
    """The same laps without the graph pick the same points, cards, habits and focus: the eight live kinds have no
    conditions and F1 25 sends every channel they need."""
    _, with_graph, _, _ = processed
    monkeypatch.setattr(lp, "load_graph", lambda: TechniqueGraph.empty(["switched off for the test"]))
    results, without, _, _ = _process(tmp_path, demo_session, graph=False, skill="beginner")
    assert all("knowledge" not in o for r in results for o in r["observations"])
    assert all(p["knowledge"] is None for b in without for p in b["picked"])
    assert [_without_knowledge(b) for b in with_graph] == [_without_knowledge(b) for b in without]


def test_a_knowledge_failure_never_breaks_a_lap(
    tmp_path: Path, demo_session: DecodedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(lp, "detect_style", broken)
    results, blocks, _, _ = _process(tmp_path, demo_session, graph=True)
    assert any(r["observations"] for r in results) and blocks
    assert all("knowledge" not in o for r in results for o in r["observations"])


def _strip_knowledge(snap: dict[str, Any]) -> dict[str, Any]:
    """A snapshot as it was before the technique graph: no ``knowledge`` on observations or coach points."""

    def strip(p: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in p.items() if k != "knowledge"}

    out = {**snap, "observations": [strip(o) for o in snap.get("observations") or []]}
    coach = snap.get("coach")
    if isinstance(coach, dict):
        out["coach"] = {
            **coach,
            "picked": [strip(p) for p in coach.get("picked") or []],
            "by_corner": {c: strip(p) for c, p in (coach.get("by_corner") or {}).items()},
        }
    return out


def test_live_snapshots_stay_within_the_size_budget(tmp_path: Path, demo_session: DecodedSession) -> None:
    """/ws/live sends a snapshot up to twenty times a second (P2): the technique knowledge in it is the coach block's
    slim copy and the card's few bytes per observation, never the evidence sentences (on the owner's real Imola and
    Melbourne sessions the median snapshot grew 2.5-3.2 kB over integration, down from 5-6 kB)."""
    db = Database(tmp_path / "size.sqlite3")
    writer = DbWriter(db)
    live = LiveState()
    proc = LapProcessor(db, writer, live)
    sid = new_session(writer, None, demo_session.info, "s-size")
    live.reset_session(sid, "test", False)
    with_k: list[int] = []
    without: list[int] = []
    per_obs: list[int] = []
    try:
        for lap in demo_session.laps:
            proc.process(LapJob(sid, copy_lap(lap), lap_ctx(demo_session.info)))
            snap = live.snapshot(include_strategy=False)
            with_k.append(len(orjson.dumps(snap)))
            without.append(len(orjson.dumps(_strip_knowledge(snap))))
            per_obs += [len(orjson.dumps(o["knowledge"])) for o in snap["observations"] if o.get("knowledge")]
            coach = snap.get("coach") or {}
            for pnt in [*(coach.get("picked") or []), *(coach.get("by_corner") or {}).values()]:
                for c in (pnt.get("knowledge") or {}).get("causes") or []:
                    assert all("test" not in e for e in c["evidence"]), c  # no evidence sentences at 20 Hz
    finally:
        writer.close()
    assert per_obs and max(per_obs) <= 200, per_obs  # fits + the first cause's screen line
    grew = sorted(a - b for a, b in zip(with_k, without, strict=True))
    p95 = grew[int(0.95 * (len(grew) - 1))]
    assert p95 <= 2500, grew  # bytes per snapshot over the same snapshot without the graph


# ---------------------------------------------------------------------------------------------- stored sessions
def test_session_analysis_annotates_observations_for_review(
    processed: tuple[list[dict[str, Any]], list[dict[str, Any]], Database, str],
) -> None:
    _, _, db, sid = processed
    sa = SessionAnalyzer(db).analyse(sid)
    assert sa is not None and sa.knowledge is not None
    assert sa.knowledge.context.skill == "beginner" and sa.knowledge.game == "f1_25"
    assert sa.knowledge.style.enough and sa.knowledge.context.braking_style is not None
    observations = [o for obs in sa.observations.values() for o in obs]
    assert observations and all(o["knowledge"]["fault"] == o["kind"] for o in observations)


# ---------------------------------------------------------------------------------------------- AI engineer
@pytest.fixture(scope="module")
def sheet(processed: tuple[list[dict[str, Any]], list[dict[str, Any]], Database, str]) -> list[Fact]:
    _, _, db, sid = processed
    sa = SessionAnalyzer(db).analyse(sid)
    assert sa is not None
    return build_fact_sheet(sa).facts


def test_knowledge_facts_are_grounded_and_name_their_nodes(sheet: list[Fact]) -> None:
    know = [f for f in sheet if f.topic == TOPIC]
    assert know[0].text.startswith(CONTEXT_PREFIX) and all(f.text.startswith(FAULT_PREFIX) for f in know[1:])
    assert sheet[-len(know) :] == know  # last on the sheet: never pushes another fact out of a selection
    seen = {f.data["fault"] for f in know[1:]}
    assert {"low_min_speed", "brake_early"} <= seen
    for f in know:
        assert check_grounding(f"{f.plain} [{f.id}]", sheet).ok, f.plain
        assert isinstance(f.data["nodes"], list)
        low = f.text.lower()
        assert "brake later" not in low and "carry more speed" not in low and "brake less" not in low
    ctx = know[0]
    assert "skill beginner" in ctx.text and "Not known: fuel saving" in ctx.text
    lms = next(f for f in know if f.data.get("fault") == "low_min_speed")
    assert "Pitwall coaches it" in lms.text and "low_min_speed" in lms.data["nodes"]
    assert "throttle_at_rotation" in lms.data["nodes"]  # the apex's technique
    assert "not validated by Pitwall" in lms.text  # expert knowledge is never presented as Pitwall's evidence


def test_an_answer_from_graph_facts_passes_and_an_invented_technique_fails(sheet: list[Fact]) -> None:
    ctx = next(f for f in sheet if f.topic == TOPIC)
    assert "trail_braking" in ctx.data["nodes"]  # an F1 car (high downforce): trail braking fits this driver
    assert check_grounding(f"Trail braking fits a car like yours [{ctx.id}].", sheet).ok
    invented = check_grounding(f"Try heel-and-toe downshifts into Turn 3 [{ctx.id}].", sheet)
    assert not invented.ok and invented.ungrounded_techniques == ["heel-and-toe"]
    uncited = check_grounding("Use threshold braking everywhere.", sheet)
    assert not uncited.ok and uncited.ungrounded_techniques == ["threshold braking"]
    # a technique fact that says it in its own words grounds it too (no graph node list needed)
    own = Fact("F1", "technique", "T3: trail braking 0.4 s longer than your reference lap.")
    assert check_grounding("You trail-braked longer into T3 [F1].", [own]).ok
    assert not check_grounding("You coasted to the apex at T3 [F1].", [own]).ok


def test_a_technique_the_facts_say_is_not_for_this_driver_is_never_grounded(sheet: list[Fact]) -> None:
    """The braking-phase fault facts of an F1 car (paddles: the game blips) list rev-matching as not for this driver;
    an uncited answer (every fact considered) that suggests it fails, though a fact names its phase's techniques."""
    braking = next(f for f in sheet if f.topic == TOPIC and f.data.get("fault") == "brake_early")
    assert "rev_match_downshift" in braking.data["not_for_driver"]
    assert "rev_match_downshift" not in braking.data["nodes"] and "Rev-matched" not in braking.text
    for answer, words in (
        ("Try heel-and-toe downshifts into T2 to settle the car.", ["heel-and-toe"]),
        ("Blip the throttle on each downshift.", ["Blip the throttle"]),
    ):
        g = check_grounding(answer, sheet)
        assert not g.ok and g.ungrounded_techniques == words, answer
    # a fact that declares its nodes grounds only those, not whatever its words name
    lms = next(f for f in sheet if f.topic == TOPIC and f.data.get("fault") == "low_min_speed")
    assert not check_grounding(f"Commit to the throttle at T1 [{lms.id}].", sheet).ok


def test_answers_that_break_the_coaching_rules_are_not_grounded() -> None:
    """The graph's constraints run over every answer: an instruction to brake later (or less, or to carry more speed)
    falls back to the deterministic answer; Pitwall's own descriptions of what happened stay allowed."""
    obs = Fact(
        "F1",
        "observations",
        "T3: you're braking 9 m later than your reference but exiting 4 km/h slower - the later braking isn't paying "
        "off.",
    )
    for answer in (
        "You're braking 9 m later than your reference at T3, and the later braking isn't paying off [F1].",
        "At T3 you braked 9 m later and exited 4 km/h slower [F1].",
    ):
        g = check_grounding(answer, [obs])
        assert g.ok and g.constraint_breaches == [], answer
    own = Fact("F2", "technique", "T3: trail braking 0.4 s longer than your reference lap.")
    described = check_grounding("At T3 you were trail braking longer than on your reference lap [F2].", [own])
    assert described.ok and described.constraint_breaches == []
    for answer, breach in (
        ("Brake later into T3 [F1].", "never_brake_later: Brake later"),
        ("Try braking a bit later at T3 [F1].", "never_brake_later: braking a bit later"),
        ("Later braking would help at T3 [F1].", "never_brake_later: Later braking"),
        ("Carry more speed into T3 [F1].", "never_carry_more_speed: Carry more"),
        ("Be lighter on the brakes at T3 [F1].", "never_brake_less: lighter on the brakes"),
        ("Brake 9 m later at T3 [F1].", "never_brake_later: Brake 9 m later"),
        ("Trail brake more into T3 [F1].", "never_trail_brake_more: Trail brake more"),
        (
            "At T3, come off the brake with a little more speed to spare [F1].",
            "never_carry_more_speed: more speed to spare",
        ),
    ):
        g = check_grounding(answer, [obs])
        assert not g.ok and g.constraint_breaches == [breach], answer


def test_the_technique_terms_follow_the_graph() -> None:
    """Every technique of the graph has the words answers name it by; every term names a technique or cause."""
    from pitwall.knowledge.graph import Cause, Technique
    from pitwall.knowledge.terms import TERMS

    g = load_graph()
    assert {t.id for t in g.techniques} <= set(TERMS)
    assert all(isinstance(g.node(k), Technique | Cause) for k in TERMS)
    # narrow on purpose: ordinary sentences about the pedals, the steering or the car are no technique claim
    for plain in (
        "You braked 12 m earlier.",
        "Full throttle 20 m later.",
        "The car has paddles with auto-blip.",
        "There was a blip of oversteer at T3.",
        "The car understeers on the exit while you unwind the steering.",
    ):
        assert check_grounding(plain, []).ungrounded_techniques == [], plain
    for claim, words in (
        ("Blip the throttle on each downshift.", "Blip the throttle"),
        ("Unwind the steering as you add throttle.", "Unwind the steering as you add throttle"),
    ):
        assert check_grounding(claim, []).ungrounded_techniques == [words], claim


def test_technique_questions_see_the_knowledge_facts(sheet: list[Fact]) -> None:
    from pitwall.ai.facts import FactSheet

    fs = FactSheet(facts=sheet)
    for q in ("should I trail brake?", "what should I work on?", "how is my braking?"):
        sel = RaceEngineer._select(detect_intent(q), fs)
        assert any(f.topic == TOPIC for f in sel), q


# ---------------------------------------------------------------------------------------------- API
@pytest.fixture
def client(tmp_path: Path, demo_session: DecodedSession) -> Iterator[tuple[TestClient, str, list[int]]]:
    from pitwall.api.app import create_app

    s = Settings(
        data_dir=tmp_path,
        llm_enabled=False,
        voice_enabled=False,
        stt_engine="none",
        tts_engine="none",
        tailscale_trust_owner=False,
        access_token="tok",
    )
    with TestClient(create_app(s, start_udp=False)) as c:
        rt = c.app.state.runtime  # type: ignore[attr-defined]
        sid = new_session(rt.writer, None, demo_session.info, "s-api")
        proc = LapProcessor(rt.db, rt.writer)
        results = [proc.process(LapJob(sid, copy_lap(lap), lap_ctx(demo_session.info))) for lap in demo_session.laps]
        yield c, sid, [int(r["lap_id"]) for r in results]


def test_the_session_knowledge_api(client: tuple[TestClient, str, list[int]]) -> None:
    c, sid, _ = client
    r = c.get(f"/api/technique/knowledge?session={sid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == sid and set(body["context"]) == set(CONTEXT_KEYS)
    sa = c.app.state.analyzer.analyse(sid)  # type: ignore[attr-defined]
    assert body["context"] == sa.knowledge.context.to_dict() and body["context"]["game"] == "f1"
    assert body["style"]["laps"] >= 1 and set(body["channels"]["g_lat"]) == {"status", "words", "caveat"}
    tech = {t["id"]: t for t in body["techniques"]}
    assert tech["trail_braking"]["applies"] is True and tech["trail_braking"]["why_not"] is None
    rev = tech["rev_match_downshift"]
    assert rev["applies"] is False and rev["why_not"] == "Only for: H-pattern gearbox (gearbox paddles with auto-blip)"
    faults = {f["id"]: f for f in body["faults"]}
    assert all(faults[k]["applies"] for k in ("low_min_speed", "late_throttle", "coasting", "incident"))
    assert all("applies" in n for k in ("conditions", "signals", "causes", "advice") for n in body[k])
    assert all("applies" not in n for k in ("phases", "constraints", "sources") for n in body[k])
    assert c.get("/api/technique/knowledge?session=nope").status_code == 404
    plain = c.get("/api/technique/knowledge").json()
    assert "context" not in plain and "applies" not in plain["techniques"][0]


def test_a_lap_pair_comparison_is_annotated(client: tuple[TestClient, str, list[int]]) -> None:
    c, _, lap_ids = client
    r = c.get(f"/api/compare?ref={lap_ids[0]}&lap={lap_ids[3]}")
    assert r.status_code == 200, r.text
    observations = r.json()["observations"]
    assert observations and all(o["knowledge"]["fault"] == o["kind"] for o in observations)
    assert all(o["knowledge"]["applies"] for o in observations)


def test_knowledge_facts_stay_small(sheet: list[Fact]) -> None:
    """The prompt goes to a shared local LLM server: the techniques of a fault are named, with their summaries only on
    the most-seen fault, and techniques for other drivers are left out of the words (on the owner's real Imola
    session the knowledge facts went from about 9 kB to 3.9 kB: the braking prompt from 2.9 to 1.8 times its size
    without them)."""
    from pitwall.knowledge.facts import DETAILED_FAULTS

    know = [f for f in sheet if f.topic == TOPIC]
    context, faults = know[0], know[1:]
    assert len(context.text) <= 750, context.text
    for i, f in enumerate(faults):
        assert len(f.text) <= (900 if i < DETAILED_FAULTS else 500), f.text
        assert "For other drivers" not in f.text and "Only for:" not in f.text, f.text
    summaries = {t.summary for t in load_graph().techniques}
    with_summaries = [f for f in faults if any(x in f.text for x in summaries)]
    assert with_summaries in ([], faults[:DETAILED_FAULTS])


def test_the_review_compare_route_is_annotated_too(client: tuple[TestClient, str, list[int]]) -> None:
    """Review > Session > Compare loads the pair through /api/coachref/compare (the reference-aware route), not
    /api/compare: its observations carry the same annotation, so the explainer's causes and "not coached for you"
    show."""
    c, _, lap_ids = client
    r = c.get(f"/api/coachref/compare?ref={lap_ids[0]}&lap={lap_ids[3]}")
    assert r.status_code == 200, r.text
    observations = r.json()["observations"]
    assert observations and all(o["knowledge"]["fault"] == o["kind"] for o in observations)
    plain = c.get(f"/api/compare?ref={lap_ids[0]}&lap={lap_ids[3]}").json()["observations"]
    assert [o["knowledge"] for o in observations] == [o["knowledge"] for o in plain]
