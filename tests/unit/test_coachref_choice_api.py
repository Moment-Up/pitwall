"""coachref API: reference choice, Review › Compare candidates and compare (``/api/coachref``), on a real runtime
(temp data dir, LLM and voice off, no UDP) whose analysis worker thread runs every change. JSON keys are pinned
by ``tests.coachref_support.CONTRACT`` (design spec 6.2)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.api.routes_coachref import router
from pitwall.config import Settings
from pitwall.core.lap_processor import LapJob
from pitwall.core.runtime import Runtime
from pitwall.model.telemetry import CarFrame, Game, SessionInfo
from tests.coachref_support import copy_lap, keys, lap_ctx, new_session, session_info
from tests.conftest import DecodedSession


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, Runtime]]:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", llm_enabled=False, voice_enabled=False)  # type: ignore[call-arg]
    rt = Runtime(settings)
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = rt
    try:
        with TestClient(app) as client:
            yield client, rt
    finally:
        rt.close()


def feed(rt: Runtime, sid: str, info: SessionInfo, laps: list[tuple[Any, int, int]]) -> None:
    for lap, ms, n in laps:
        rt.worker.submit(LapJob(sid, copy_lap(lap, ms, n), lap_ctx(info)))
    rt.worker.join()


def go_live(rt: Runtime, sid: str, info: SessionInfo) -> None:
    rt.live.reset_session(sid, "udp:20777", False)
    rt.live.on_session(info)
    rt.worker.join()


def moving(rt: Runtime, speed: float | None) -> None:
    rt.live.frame = CarFrame(game=Game.F1_25, t_recv_ns=0, speed_kph=speed, pit_status=0, lap_number=2)
    rt.live.last_packet_mono = time.monotonic()


@pytest.fixture
def family(
    api: tuple[TestClient, Runtime], clean_session: DecodedSession, one_offs_session: DecodedSession
) -> dict[str, Any]:
    _, rt = api
    ann = rt.drivers.default_id
    sam = rt.drivers.create("Sam").id
    jo = rt.drivers.create("Jo").id
    feed(
        rt,
        new_session(rt.writer, sam, clean_session.info, "s-sam"),
        clean_session.info,
        [(clean_session.laps[i], 60_000 + i, i + 1) for i in range(3)],
    )
    jo_info = session_info(clean_session.info, assists={"braking": 2})
    feed(rt, new_session(rt.writer, jo, jo_info, "s-jo"), jo_info, [(clean_session.laps[0], 59_000, 1)])
    sa = new_session(rt.writer, ann, one_offs_session.info, "s-ann")
    go_live(rt, sa, one_offs_session.info)
    feed(rt, sa, one_offs_session.info, [(one_offs_session.laps[0], 69_000, 1), (one_offs_session.laps[2], 70_500, 2)])
    return {"ann": ann, "sam": sam, "jo": jo, "sid": sa, "info": one_offs_session.info}


def test_options_without_a_live_session(api: tuple[TestClient, Runtime]) -> None:
    client, rt = api
    body = client.get("/api/coachref/options").json()
    keys("RefOptionsResponse", body)
    keys("ReferenceChoice", body["choice"])
    assert body["driver_id"] == rt.drivers.default_id and body["context"] is None
    assert body["choice"]["kind"] == "own_best" and body["choice"]["updated_unix"] is None
    assert body["applies"] == "next_session" and body["has_track_override"] is False
    assert [o["kind"] for o in body["options"]] == ["own_best", "household_best"]
    for o in body["options"]:
        keys("RefOption", o)
        assert o["available"] is None
    assert client.get("/api/coachref/options", params={"driver_id": 999}).status_code == 404


def test_options_with_a_live_session(api: tuple[TestClient, Runtime], family: dict[str, Any]) -> None:
    client, _ = api
    body = client.get("/api/coachref/options").json()
    keys("RefOptionsResponse", body)
    keys("RefContext", body["context"])
    assert body["applies"] == "now"  # no frames: the car is not moving
    by_label = {o["label"]: o for o in body["options"]}
    assert by_label["Your best"]["selected"] is True and by_label["Your best"]["lap"]["lap_time_ms"] == 69_000
    keys("RefOptionLap", by_label["Your best"]["lap"])
    # Jo is faster but used another assist: Jo holds the record, Sam's lap is the best in these conditions (plan 5.2)
    assert by_label["Best in these conditions"]["lap"]["driver_name"] == "Sam"
    assert by_label["Jo's best"]["available"] is False
    assert by_label["Jo's best"]["reason"] == "Jo's laps here used a different braking assist"
    assert by_label["Sam's best"]["available"] is True and by_label["Sam's best"]["lap"]["lap_time_ms"] == 60_000
    assert [o["label"] for o in body["options"] if o["kind"] == "lap"][:2] == ["Lap 1 · Sam", "Lap 2 · Sam"]


def test_put_choice_applies_and_validation(api: tuple[TestClient, Runtime], family: dict[str, Any]) -> None:
    client, rt = api
    sam = family["sam"]
    r = client.put("/api/coachref/choice", json={"kind": "driver_best", "target_driver_id": sam})
    assert r.status_code == 200, r.text
    body = r.json()
    keys("ChoiceResponse", body)
    keys("ReferenceChoice", body["choice"])
    assert (
        body["applies"] == "now" and body["choice"]["label"] == "Sam's best" and body["choice"]["scope"] == "all_tracks"
    )
    ref = rt.live.reference
    assert ref is not None and ref["label"] == "Sam's best" and ref["own"] is False  # applied at once
    keys("ReferenceDescriptor", ref)
    snap = rt.live.snapshot()
    keys("SnapshotCoachref", snap["coachref"])
    assert snap["coachref"]["choice"]["kind"] == "driver_best" and snap["cues"]["drill_corner"] is None
    moving(rt, 220.0)
    r = client.put("/api/coachref/choice", json={"kind": "household_best", "scope": "track"})
    assert r.json()["applies"] == "next_lap"
    assert r.json()["choice"]["scope"] == "track" and r.json()["choice"]["game"] == "f1_25"
    assert rt.live.snapshot()["coachref"]["pending"] is True
    rows = client.get(
        "/api/coachref/choice",
        params={"driver_id": family["ann"], "game": "f1_25", "track_id": family["info"].track_id},
    ).json()
    keys("ChoiceRows", rows)
    assert rows["all_tracks"]["kind"] == "driver_best" and rows["track"]["kind"] == "household_best"
    assert rows["effective"]["kind"] == "household_best"
    # validation and unknowns
    assert client.put("/api/coachref/choice", json={"kind": "driver_best"}).status_code == 422
    assert client.put("/api/coachref/choice", json={"kind": "driver_best", "target_driver_id": 999}).status_code == 404
    assert client.put("/api/coachref/choice", json={"kind": "lap", "lap_id": 99_999}).status_code == 404
    assert client.put("/api/coachref/choice", json={"kind": "nonsense"}).status_code == 422
    assert client.put("/api/coachref/choice", json={"kind": "own_best", "extra": 1}).status_code == 422
    # driver_best of yourself is stored as own_best
    me = client.put("/api/coachref/choice", json={"kind": "driver_best", "target_driver_id": family["ann"]}).json()
    assert me["choice"]["kind"] == "own_best"
    # delete the track row: 204, then 404
    params = {"game": "f1_25", "track_id": family["info"].track_id}
    assert client.delete("/api/coachref/choice", params=params).status_code == 204
    assert client.delete("/api/coachref/choice", params=params).status_code == 404
    assert client.delete("/api/coachref/choice", params={"game": "f1_25"}).status_code == 422


def test_saved_lap_choice_is_scoped_to_its_track(api: tuple[TestClient, Runtime], family: dict[str, Any]) -> None:
    client, rt = api
    sam_lap = 1  # Sam's first lap (the first lap stored)
    body = client.put("/api/coachref/choice", json={"kind": "lap", "lap_id": sam_lap}).json()
    assert body["choice"]["scope"] == "track" and body["choice"]["lap_id"] == sam_lap
    assert body["choice"]["label"].startswith("Sam · lap 1 · ")
    assert rt.live.reference is not None and rt.live.reference["lap_id"] == sam_lap
    assert rt.live.reference["label_to"] == "Sam's lap"


def test_candidates_and_compare(api: tuple[TestClient, Runtime], family: dict[str, Any]) -> None:
    client, rt = api
    with rt.db.read() as c:
        lap_b = int(c.execute("SELECT id FROM laps WHERE session_id='s-ann' AND lap_number=2").fetchone()[0])
    body = client.get("/api/coachref/candidates", params={"lap_id": lap_b}).json()
    keys("CandidatesResponse", body)
    assert body["driver_id"] == family["ann"]
    assert [g["id"] for g in body["groups"]] == ["own", "family"]
    for g in body["groups"]:
        keys("CandidatesGroup", g)
        for o in g["options"]:
            keys("RefOption", o)
    own = body["groups"][0]["options"][0]
    assert own["label"] == "Your best" and own["lap"]["lap_time_ms"] == 69_000
    fam = {o["label"]: o for o in body["groups"][1]["options"]}
    assert fam["Jo's best"]["available"] is False and fam["Sam's best"]["available"] is True
    assert client.get("/api/coachref/candidates", params={"lap_id": 99_999}).status_code == 404
    sam_best = fam["Sam's best"]["lap"]["lap_id"]
    cmp = client.get("/api/coachref/compare", params={"ref": sam_best, "lap": lap_b}).json()
    keys("CompareResponse", cmp)
    keys("ReferenceDescriptor", cmp["reference"])
    assert (cmp["reference"]["label"], cmp["reference"]["own"], cmp["reference"]["kind"]) == (
        "Sam's best",
        False,
        "driver_best",
    )
    assert cmp["comparison"]["compatibility"]["ok"] is True
    texts = [o["text"] for o in cmp["observations"]]
    assert texts and all("your reference" not in t for t in texts) and any("Sam" in t for t in texts)
    own_cmp = client.get("/api/coachref/compare", params={"ref": own["lap"]["lap_id"], "lap": lap_b}).json()
    assert own_cmp["reference"]["own"] is True and own_cmp["reference"]["label"] == "Your best"
    assert client.get("/api/coachref/compare", params={"ref": 99_999, "lap": lap_b}).status_code == 404
