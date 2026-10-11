"""Pace vs AI difficulty: storage (upsert guard, per-driver points), the API contract, live state, the processor and
the engineer (intents, grounded deterministic answers, radio phrasing)."""

from __future__ import annotations

import queue
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.ai.engineer import RaceEngineer, detect_intent, deterministic_answer
from pitwall.ai.facts import AI_LEVEL_PREFIX, AI_PACE_PREFIX, build_fact_sheet, ordinal
from pitwall.ai.grounding import check_grounding
from pitwall.ai.radio_phrasing import radio_answer
from pitwall.analysis.ai_pace import summarise
from pitwall.api.routes_drivers import router
from pitwall.core.ai_pace import AiPaceProcessor
from pitwall.core.lap_processor import AnalysisWorker, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.drivers import DriverService
from pitwall.model.telemetry import Game, SessionInfo, SessionType, Weather
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from pitwall.voice.hub import FAST_INTENTS
from tests.unit.test_ai_pace import BESTS, driver_laps, field, job

SESSION_AI_PACE_KEYS = {
    "status",
    "method_version",
    "updated_unix",
    "ai_difficulty",
    "car_class",
    "weather_class",
    "online",
    "ai_cars",
    "ai_laps",
    "ai_ref_ms",
    "ai_best_ms",
    "ai_p25_ms",
    "ai_p75_ms",
    "ai_median_lap_ms",
    "ai_bests_ms",
    "driver_best_ms",
    "driver_best_lap_id",
    "driver_median_ms",
    "driver_clean_laps",
    "gap_ms",
    "gap_pct",
    "gap_to_best_ai_ms",
    "race_pace_gap_pct",
    "field_rank",
    "field_size",
    "excluded",
}
POINT_KEYS = {
    "session_id",
    "started_unix",
    "game",
    "track_id",
    "track_name",
    "car_id",
    "car_name",
    "car_class",
    "session_category",
    "weather_class",
    "online",
    "status",
    "ai_difficulty",
    "ai_ref_ms",
    "ai_best_ms",
    "ai_cars",
    "driver_best_ms",
    "gap_ms",
    "gap_pct",
    "field_rank",
    "field_size",
}
SUGGESTION_KEYS = {
    "key",
    "basis",
    "level",
    "range",
    "bound",
    "confidence",
    "direction",
    "note",
    "latest_level",
    "latest_gap_pct",
    "target_gap_pct",
    "sessions_used",
    "levels_used",
    "slope_pct_per_level",
    "slope_sources",
    "text",
}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[Database, DbWriter]]:
    db = Database(tmp_path / "ai.sqlite3")
    writer = DbWriter(db)
    yield db, writer
    writer.close()


def make_session(
    writer: DbWriter,
    sid: str,
    driver: int | None,
    *,
    track: str = "f1:17",
    name: str = "Austria",
    source: str = "udp:20777",
    synthetic: bool = False,
    started: float = 1000.0,
    session_type: SessionType = SessionType.RACE,
) -> str:
    info = SessionInfo(
        game=Game.F1_25,
        session_uid=f"uid-{sid}",
        track_id=track,
        track_name=name,
        track_length_m=4318.0,
        session_type=session_type,
        session_type_raw="Race",
        car_id="f1:team:8",
        car_name="McLaren",
        weather=Weather(condition="clear"),
        formula="F1 World",
    )

    def go(c: sqlite3.Connection) -> None:
        repo.insert_session(c, sid, "f1_25", source, synthetic, None, None, driver_id=driver)
        repo.update_session_info(c, sid, info)
        c.execute("UPDATE sessions SET started_unix=? WHERE id=?", (started, sid))

    writer.call(go)
    return sid


def store_pace(
    writer: DbWriter,
    sid: str,
    *,
    difficulty: int | None = 35,
    driver_ms: int | None = 78_351,
    bests: list[int] | None = None,
    run_id: str = "run1",
    session_type: SessionType = SessionType.RACE,
    weather: str = "dry",
) -> dict[str, Any]:
    j = replace(
        job(field(bests or BESTS), session_type=session_type, difficulty=difficulty),
        session_id=sid,
        run_id=run_id,
        weather_class=weather,
    )
    laps = driver_laps(driver_ms) if driver_ms else []
    row = summarise(j, laps).row()
    row["driver_best_lap_id"] = None  # the synthetic lap ids are not stored laps
    assert writer.call(lambda c: repo.upsert_session_ai_pace(c, sid, row))
    return row


# ---------------------------------------------------------------------------------------------- repo
def test_upsert_guard(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    sid = make_session(writer, "s1", None)
    row = store_pace(writer, sid)
    fewer = {**row, "ai_laps": row["ai_laps"] - 1, "gap_ms": 1}
    assert writer.call(lambda c: repo.upsert_session_ai_pace(c, sid, {**fewer, "run_id": "run1"}))  # same run
    with db.read() as c:
        assert repo.get_session_ai_pace(c, sid)["gap_ms"] == 1  # type: ignore[index]
    worse = {**row, "ai_laps": row["ai_laps"] - 2, "gap_ms": 2, "run_id": "restart"}
    assert not writer.call(lambda c: repo.upsert_session_ai_pace(c, sid, worse))  # another run, less data
    with db.read() as c:
        assert repo.get_session_ai_pace(c, sid)["gap_ms"] == 1  # type: ignore[index]
    better = {**row, "gap_ms": 3, "run_id": "backfill"}
    assert writer.call(lambda c: repo.upsert_session_ai_pace(c, sid, better))  # another run, as many laps
    with db.read() as c:
        stored = repo.get_session_ai_pace(c, sid)
    assert stored is not None and stored["gap_ms"] == 3
    assert set(stored) == SESSION_AI_PACE_KEYS  # exactly the SessionAiPace contract
    assert stored["online"] is False and stored["excluded"] == {"race_lap_1": 7}
    assert stored["ai_bests_ms"] == sorted(BESTS)


def test_driver_points_scope_and_order(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    svc = DriverService(db, writer)
    james, jo = svc.default_id, svc.create("Jo").id
    make_session(writer, "new", james, started=3000.0)
    make_session(writer, "old", james, started=1000.0)
    make_session(writer, "mel", james, track="f1:0", name="Melbourne", started=2000.0)
    make_session(writer, "nolap", james, started=2500.0)
    make_session(writer, "syn", james, synthetic=True, started=4000.0)
    make_session(writer, "rep", james, source="replay:x.pwcap", started=4100.0)
    make_session(writer, "jo", jo, started=4200.0)
    make_session(writer, "few", james, started=4300.0)
    make_session(writer, "unk", james, started=4400.0)
    for sid in ("new", "old", "mel", "syn", "rep", "jo"):
        store_pace(writer, sid)
    store_pace(writer, "nolap", driver_ms=None)
    store_pace(writer, "few", bests=BESTS[:3])
    store_pace(writer, "unk", difficulty=None)
    with db.read() as c:
        pts = repo.driver_ai_pace_points(c, james)
        austria = repo.driver_ai_pace_points(c, james, track_id="f1:17")
        newest = repo.driver_ai_pace_points(c, james, limit=2)
        f2 = repo.driver_ai_pace_points(c, james, car_class="F2")
        quali = repo.driver_ai_pace_points(c, james, category="qualifying")
    assert [p["session_id"] for p in pts] == ["old", "mel", "nolap", "new"]  # oldest first; no syn/rep/jo/few/unk
    assert set(pts[0]) == POINT_KEYS
    assert pts[2]["status"] == "no_driver_lap" and pts[2]["gap_pct"] is None and pts[2]["ai_ref_ms"] == 74_579
    assert pts[0]["session_category"] == "race" and pts[0]["online"] is False and pts[0]["car_class"] == "F1 World"
    assert [p["session_id"] for p in austria] == ["old", "nolap", "new"]
    assert [p["session_id"] for p in newest] == ["nolap", "new"]
    assert f2 == [] and quali == []


# ---------------------------------------------------------------------------------------------- API
@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, SimpleNamespace]]:
    db = Database(tmp_path / "api.sqlite3")
    writer = DbWriter(db)
    rt = SimpleNamespace(db=db, writer=writer, live=LiveState(), drivers=DriverService(db, writer))
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = rt
    with TestClient(app) as client:
        yield client, rt
    writer.close()


def test_driver_ai_pace_endpoint(api: tuple[TestClient, SimpleNamespace]) -> None:
    client, rt = api
    james = rt.drivers.default_id
    make_session(rt.writer, "a", james, started=1000.0)
    make_session(rt.writer, "m", james, track="f1:0", name="Melbourne", started=2000.0)
    store_pace(rt.writer, "a")
    store_pace(rt.writer, "m", driver_ms=72_000)
    body = client.get(f"/api/drivers/{james}/ai-pace").json()
    assert set(body) == {"driver_id", "method_version", "target_gap_pct", "scope", "points", "suggestions"}
    assert body["scope"] == {"game": None, "track_id": None, "car_class": None, "category": None}
    assert body["method_version"] == 1 and body["target_gap_pct"] == 0
    assert [p["session_id"] for p in body["points"]] == ["a", "m"]
    assert [s["key"]["track_name"] for s in body["suggestions"]] == ["Melbourne", "Austria"]  # newest first
    assert all(set(s) == SUGGESTION_KEYS for s in body["suggestions"])
    austria = body["suggestions"][1]
    assert austria["basis"] == "direction_only" and austria["direction"] == "lower" and austria["latest_level"] == 35
    scoped = client.get(f"/api/drivers/{james}/ai-pace", params={"track_id": "f1:17", "target_gap_pct": 5}).json()
    assert [p["session_id"] for p in scoped["points"]] == ["a"] and len(scoped["suggestions"]) == 1
    assert scoped["suggestions"][0]["target_gap_pct"] == 5.0
    assert client.get("/api/drivers/999/ai-pace").status_code == 404
    assert client.get(f"/api/drivers/{james}/ai-pace", params={"target_gap_pct": 5.5}).status_code == 422
    assert client.get(f"/api/drivers/{james}/ai-pace", params={"target_gap_pct": -6}).status_code == 422
    assert client.get(f"/api/drivers/{james}/ai-pace", params={"category": "sprint"}).status_code == 422


def test_session_detail_and_list_carry_ai_pace(tmp_path: Path) -> None:
    from pitwall.api.app import create_app
    from pitwall.config import Settings

    s = Settings(_env_file=None, data_dir=tmp_path, llm_enabled=False, voice_enabled=False)  # type: ignore[call-arg]
    with TestClient(create_app(s, start_udp=False), client=("127.0.0.1", 40000)) as client:
        rt = client.app.state.runtime  # type: ignore[attr-defined]
        make_session(rt.writer, "x", None)
        make_session(rt.writer, "y", None)
        store_pace(rt.writer, "x")
        rt.writer.call(lambda c: repo.set_session_ai_difficulty(c, "x", 35))
        detail = client.get("/api/sessions/x").json()
        assert detail["ai_difficulty"] == 35 and set(detail["ai_pace"]) == SESSION_AI_PACE_KEYS
        assert detail["ai_pace"]["ai_ref_ms"] == 74_579 and detail["ai_pace"]["gap_ms"] == 3772
        assert client.get("/api/sessions/y").json()["ai_pace"] is None  # not recorded: null
        rows = {r["id"]: r for r in client.get("/api/sessions").json()}
        assert rows["x"]["ai_difficulty"] == 35 and rows["y"]["ai_difficulty"] is None


# ---------------------------------------------------------------------------------------------- live / processor
def test_live_state_publishes_only_for_the_live_session() -> None:
    live = LiveState()
    live.reset_session("s1", "udp:20777", False)
    assert live.snapshot()["ai_pace"] is None
    live.set_ai_pace("other", {"status": "ok"})
    assert live.ai_pace is None
    live.set_ai_pace("s1", {"status": "ok"})
    assert live.snapshot()["ai_pace"] == {"status": "ok"}
    live.reset_session("s2", "udp:20777", False)
    assert live.snapshot()["ai_pace"] is None


def test_processor_stores_and_publishes(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    live = LiveState()
    sid = make_session(writer, "s1", None)
    live.reset_session(sid, "udp:20777", False)
    proc = AiPaceProcessor(db, writer, live)
    j = job(field(BESTS))
    summary = proc.process(replace(j, session_id=sid))
    writer.flush()
    with db.read() as c:
        stored = repo.get_session_ai_pace(c, sid)
    assert stored is not None and stored["status"] == "no_driver_lap" and stored["ai_ref_ms"] == 74_579
    assert live.ai_pace == summary.live_payload() and live.ai_pace["synthetic"] is False
    other = make_session(writer, "s2", None)
    proc.process(replace(j, session_id=other))
    assert live.ai_pace["session_id"] == sid  # type: ignore[index]  # not the live session: stored, not shown


def test_worker_drops_ai_jobs_when_full_never_blocking(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    worker = AnalysisWorker(LapProcessor(db, writer))
    try:
        full: queue.Queue[Any] = queue.Queue(maxsize=1)
        full.put(None)
        real, worker._q = worker._q, full
        worker.submit_ai_pace(job(field(BESTS)))
        assert worker.ai_dropped == 1
        worker._q = real
    finally:
        worker.close()


# ---------------------------------------------------------------------------------------------- engineer / radio
@pytest.mark.parametrize(
    ("phrase", "intent"),
    [
        ("how am I doing against the AI?", "ai_pace"),
        ("am I faster than the AI", "ai_pace"),
        ("how's my pace vs the AI", "ai_pace"),
        ("what AI level should I use?", "ai_level"),
        ("what difficulty should I race at", "ai_level"),
        ("turn the AI up?", "ai_level"),
        ("how's my pace", "lap_times"),
        ("compare to my best", "compare"),
    ],
)
def test_intents(phrase: str, intent: str) -> None:
    assert detect_intent(phrase).name == intent


def test_fast_intents() -> None:
    assert {"ai_pace", "ai_level"} <= FAST_INTENTS


def test_ordinal() -> None:
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 20, 21, 22, 23, 101, 111)] == [
        "1st",
        "2nd",
        "3rd",
        "4th",
        "11th",
        "12th",
        "13th",
        "20th",
        "21st",
        "22nd",
        "23rd",
        "101st",
        "111th",
    ]


def _analysis(
    db: Database, writer: DbWriter, sid: str, *, driver: int | None, synthetic: bool = False, source: str = "udp:20777"
) -> Any:
    make_session(writer, sid, driver, synthetic=synthetic, source=source)
    if driver is None:  # a live session always gets the seated driver: make this one unowned (pre-profile rows)
        writer.call(lambda c: c.execute("UPDATE sessions SET driver_id=NULL WHERE id=?", (sid,)))
    store_pace(writer, sid)
    return SessionAnalyzer(db).analyse(sid)


async def test_facts_are_grounded_and_radio_phrasing(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    svc = DriverService(db, writer)
    sa = _analysis(db, writer, "s1", driver=svc.default_id)
    assert sa.ai_pace is not None and sa.ai_suggestion is not None
    sheet = build_fact_sheet(sa)
    ai = [f for f in sheet.facts if f.topic == "ai"]
    assert [f.text.split(":")[0] for f in ai] == [AI_PACE_PREFIX, f"{AI_LEVEL_PREFIX} suggestion at Austria"]
    pace, level = ai
    assert pace.text == (
        "Pace vs AI this session: AI difficulty 35; your best clean lap 1:18.351 vs the typical AI car's best lap "
        "1:14.579 (median of 7 AI cars; fastest AI 1:12.730): 3.772s slower (+5.06%), 8 of 8 on best laps."
    )
    assert pace.say == (
        "Against the AI at difficulty 35, your best lap is 3.8 seconds slower than the typical AI car: "
        "8th of 8 on best laps."
    )
    assert level.text == (
        "AI level suggestion at Austria: none yet; only difficulty 35 raced here, gap to the typical AI car +5.06%."
    )
    assert level.say is not None and level.say.startswith("At AI 35 your best lap here was 5.1% slower")
    for f in ai:
        assert check_grounding(f"{f.plain} [{f.id}]", [f]).ok, f.plain
    engineer = RaceEngineer(None)
    ans = await engineer.answer("how am I doing against the AI?", sheet, use_llm=False)
    assert ans.intent == "ai_pace" and ans.grounded and ans.text == pace.say
    ans = await engineer.answer("what AI level should I use?", sheet, use_llm=False)
    assert ans.intent == "ai_level" and ans.text == level.say
    assert (
        radio_answer("ai_pace", sheet)
        == "Against the AI at 35: 3.8 off the typical AI car, position 8 of 8 on best laps."
    )
    assert radio_answer("ai_level", sheet) == (
        "Not enough levels yet. At 35 you're 5.1 percent slower than the AI here. "
        "Try a lower level, then I can suggest one."
    )
    det = deterministic_answer(detect_intent("am I faster than the AI"), [pace], sheet)
    assert check_grounding(det, [pace]).ok


def test_no_suggestion_for_synthetic_replay_or_unowned(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    james = DriverService(db, writer).default_id
    syn = _analysis(db, writer, "syn", driver=james, synthetic=True)
    rep = _analysis(db, writer, "rep", driver=james, source="replay:x.pwcap")
    nobody = _analysis(db, writer, "nobody", driver=None)
    for sa in (syn, rep, nobody):
        assert sa.ai_pace is not None and sa.ai_suggestion is None
    syn_facts = [f for f in build_fact_sheet(syn).facts if f.topic == "ai"]
    assert len(syn_facts) == 1 and syn_facts[0].text.endswith("NOTE: SYNTHETIC data.")


def test_analysis_cache_follows_new_ai_pace(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    sid = make_session(writer, "s1", None)
    an = SessionAnalyzer(db)
    assert an.analyse(sid).ai_pace is None  # type: ignore[union-attr]
    store_pace(writer, sid)
    first = an.analyse(sid)
    assert first is not None and first.ai_pace is not None and first.ai_pace["gap_ms"] == 3772
    store_pace(writer, sid, driver_ms=74_000)
    again = an.analyse(sid)
    assert again is not None and again.ai_pace is not None and again.ai_pace["gap_ms"] == -579


def test_other_statuses_say_why(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    sid = make_session(writer, "s1", None)
    store_pace(writer, sid, bests=BESTS[:2])
    sa = SessionAnalyzer(db).analyse(sid)
    assert sa is not None
    sheet = build_fact_sheet(sa)
    (f,) = [f for f in sheet.facts if f.topic == "ai"]
    assert f.text == (
        "Pace vs AI this session: not available (too few AI laps were seen: Pitwall needs clean laps from at least "
        "5 AI cars)."
    )
    assert radio_answer("ai_pace", sheet) == f.text and check_grounding(f"{f.plain} [{f.id}]", [f]).ok
    store_pace(writer, sid, driver_ms=None, run_id="run1")
    sheet = build_fact_sheet(SessionAnalyzer(db).analyse(sid))  # type: ignore[arg-type]
    (f,) = [f for f in sheet.facts if f.topic == "ai"]
    assert f.say == "At AI 35 the typical AI car's best lap is a 1:14.579. Set a clean lap and I can compare."
    assert radio_answer("ai_pace", sheet) == "Typical AI best at 35 is a 1:14.579. No clean lap yet to compare."
    assert check_grounding(f"{f.plain} [{f.id}]", [f]).ok


def test_level_with_the_typical_ai_car_wording(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    sid = make_session(writer, "s1", None)
    store_pace(writer, sid, driver_ms=74_600)  # 21 ms off the typical AI car
    sheet = build_fact_sheet(SessionAnalyzer(db).analyse(sid))  # type: ignore[arg-type]
    (f,) = [f for f in sheet.facts if f.topic == "ai"]
    assert (
        f.say
        == "Against the AI at difficulty 35, your best lap is level with the typical AI car: 5th of 8 on best laps."
    )
    assert radio_answer("ai_pace", sheet) == (
        "Against the AI at 35: level with the typical AI car, position 5 of 8 on best laps."
    )
    assert check_grounding(f"{f.plain} [{f.id}]", [f]).ok
