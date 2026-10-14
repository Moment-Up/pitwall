"""coachref API: practice drills (``/api/coachref/drills``) on a real runtime (temp data dir, LLM and voice off, no
UDP): preconditions, the lifecycle start -> attempts -> completed / stopped, history and its filters, the radio
handler. JSON keys are pinned by ``tests.coachref_support.CONTRACT`` (design spec 6.2)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.ai.engineer import detect_intent
from pitwall.api.routes_coachref import router
from pitwall.config import Settings
from pitwall.core.coachref import CoachRef
from pitwall.core.runtime import Runtime
from pitwall.storage import repo
from tests.coachref_support import keys, new_session, run_now
from tests.conftest import DecodedSession
from tests.unit.test_coachref_choice_api import feed, go_live


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


def view_keys(v: dict[str, Any]) -> None:
    keys("DrillView", v)
    keys("DrillReference", v["reference"])
    for a in v["attempts"]:
        keys("DrillAttempt", a)


def test_preconditions(api: tuple[TestClient, Runtime], one_offs_session: DecodedSession) -> None:
    client, rt = api
    body = {"corner_ref": "T2", "kind": "brake_point"}
    r = client.post("/api/coachref/drills", json=body)
    assert (r.status_code, r.json()["detail"]) == (409, "Drills run on your own live driving.")
    opts = client.get("/api/coachref/drills/options", params={"corner_ref": "T2"}).json()
    keys("DrillOptionsResponse", opts)
    assert (
        opts["available"] is False and opts["reason"] == "Drills run on your own live driving." and opts["kinds"] == []
    )
    sid = new_session(rt.writer, rt.drivers.default_id, one_offs_session.info, "s-ann")
    go_live(rt, sid, one_offs_session.info)
    r = client.post("/api/coachref/drills", json=body)
    assert (r.status_code, r.json()["detail"]) == (
        409,
        "Pitwall is still learning this track: drive 3 clean laps first.",
    )
    syn = new_session(rt.writer, rt.drivers.default_id, one_offs_session.info, "s-syn", synthetic=True)
    rt.live.reset_session(syn, "udp:20777", True)
    assert client.post("/api/coachref/drills", json=body).json()["detail"] == "Drills run on your own live driving."
    # validation
    assert client.post("/api/coachref/drills", json={"kind": "brake_point"}).status_code == 422
    assert client.post("/api/coachref/drills", json={"corner": "T2", "laps": 2}).status_code == 422
    assert client.post("/api/coachref/drills", json={"corner": "T2", "tolerance": 20}).status_code == 422
    assert client.post("/api/coachref/drills", json={"corner": "T2", "kind": "trail_braking"}).status_code == 422
    assert client.get("/api/coachref/drills/options").status_code == 422
    assert client.get("/api/coachref/drills/999").status_code == 404
    assert client.post("/api/coachref/drills/active/stop").status_code == 404
    assert client.get("/api/coachref/drills/active").json() is None


@pytest.fixture
def live_ann(api: tuple[TestClient, Runtime], one_offs_session: DecodedSession) -> dict[str, Any]:
    _, rt = api
    ann = rt.drivers.default_id
    sid = new_session(rt.writer, ann, one_offs_session.info, "s-ann")
    go_live(rt, sid, one_offs_session.info)
    laps = one_offs_session.laps
    feed(rt, sid, one_offs_session.info, [(laps[0], 69_000, 1), (laps[1], 69_500, 2), (laps[0], 69_200, 3)])
    return {"ann": ann, "sid": sid, "info": one_offs_session.info, "laps": laps}


def test_lifecycle_start_attempts_completed(api: tuple[TestClient, Runtime], live_ann: dict[str, Any]) -> None:
    client, rt = api
    opts = client.get("/api/coachref/drills/options", params={"corner_ref": "T2"}).json()
    keys("DrillOptionsResponse", opts)
    assert opts["available"] is True and opts["corner"] == "T2" and opts["laps_choices"] == [3, 5, 8, 10]
    by_kind = {k["kind"]: k for k in opts["kinds"]}
    for k in opts["kinds"]:
        keys("DrillOption", k)
    assert by_kind["brake_point"]["available"] is True
    assert by_kind["brake_point"]["target_text"] == "Brake within 5 m of your best lap's braking point"
    assert by_kind["brake_point"]["tolerance_choices"] == [3.0, 5.0, 10.0]
    r = client.post("/api/coachref/drills", json={"corner_ref": "T2", "kind": "brake_point", "laps": 3})
    assert r.status_code == 201, r.text
    v = r.json()
    view_keys(v)
    assert (v["status"], v["kind"], v["skill_label"], v["source"], v["laps_target"]) == (
        "active",
        "brake_point",
        "Brake point",
        "manual",
        3,
    )
    assert v["reference"]["label"] == "Your best" and v["synthetic"] is False
    again = client.post("/api/coachref/drills", json={"corner_ref": "T4"})
    assert (again.status_code, again.json()["detail"]) == (409, "A T2 drill is running: 0 of 3 done. Stop it first.")
    snap = rt.live.snapshot()
    keys("SnapshotCoachref", snap["coachref"])
    assert snap["coachref"]["drill"]["id"] == v["id"] and snap["cues"]["drill_corner"] == "T2"
    laps, info = live_ann["laps"], live_ann["info"]
    feed(rt, live_ann["sid"], info, [(laps[2], 70_500, 4)])  # design-T3 = learned T2: braked 15 m early
    active = client.get("/api/coachref/drills/active").json()
    view_keys(active)
    assert len(active["attempts"]) == 1 and active["attempts"][0]["outcome"] == "miss"
    assert active["attempts"][0]["text"].startswith("T2 drill, 1 of 3: ")
    feed(rt, live_ann["sid"], info, [(laps[0], 69_000, 5), (laps[1], 69_300, 6)])
    done = client.get(f"/api/coachref/drills/{v['id']}").json()
    view_keys(done)
    assert done["status"] == "completed" and done["hits"] == 2 and done["scored"] == 3
    assert done["summary_text"].startswith("T2 drill done: 2 of 3 on the point.")
    assert client.get("/api/coachref/drills/active").json() is None
    assert rt.live.snapshot()["coachref"]["drill"]["status"] == "completed"  # the result stays for the Ready card
    assert rt.live.snapshot()["cues"]["drill_corner"] is None
    history = client.get("/api/coachref/drills", params={"driver_id": live_ann["ann"]}).json()
    assert [d["id"] for d in history] == [v["id"]]
    for params, n in (
        ({"game": "f1_25"}, 1),
        ({"track_id": "f1:none"}, 0),
        ({"car_id": info.car_id}, 1),
        ({"driver_id": 999}, 0),
        ({"limit": 1}, 1),
    ):
        assert len(client.get("/api/coachref/drills", params=params).json()) == n, params
    assert client.get("/api/coachref/drills", params={"limit": 0}).status_code == 422


def test_stop_abandon_and_restart(api: tuple[TestClient, Runtime], live_ann: dict[str, Any]) -> None:
    client, rt = api
    first = client.post("/api/coachref/drills", json={"corner": "T2", "laps": 3}).json()
    stopped = client.post("/api/coachref/drills/active/stop").json()
    view_keys(stopped)
    assert (stopped["id"], stopped["status"], stopped["stop_reason"]) == (first["id"], "abandoned", "driver")
    assert client.get("/api/coachref/drills").json() == []  # nothing driven: hidden from history
    assert len(client.get("/api/coachref/drills", params={"include_empty": True}).json()) == 1
    second = client.post("/api/coachref/drills", json={"corner": "T2", "laps": 3}).json()
    feed(rt, live_ann["sid"], live_ann["info"], [(live_ann["laps"][0], 69_000, 4)])
    st = client.post("/api/coachref/drills/active/stop").json()
    assert st["status"] == "stopped" and st["summary_text"].startswith("T2 drill stopped after 1 of 3 laps")
    third = client.post("/api/coachref/drills", json={"corner": "T2", "laps": 3}).json()
    rt.writer.flush()
    # a restart: drills left active by the last run are stopped
    restarted = CoachRef(rt.db, rt.writer, rt.live, rt.drivers, run_task=run_now)
    try:
        with rt.db.read() as c:
            row = repo.get_drill(c, third["id"])
        assert row is not None and (row["status"], row["stop_reason"]) == ("abandoned", "service_restart")
    finally:
        restarted.close()
    assert second["id"] != third["id"]
    missing = client.post("/api/coachref/drills", json={"corner_ref": "T99"})
    assert missing.status_code == 409


def test_driver_change_stops_the_drill(api: tuple[TestClient, Runtime], live_ann: dict[str, Any]) -> None:
    client, rt = api
    d = client.post("/api/coachref/drills", json={"corner": "T2", "laps": 3}).json()
    sam = rt.drivers.create("Sam").id
    rt.drivers.set_active(sam)
    rt.worker.join()
    with rt.db.read() as c:
        row = repo.get_drill(c, d["id"])
    assert row is not None and row["status"] == "abandoned" and row["stop_reason"] == "driver_changed"


def test_done_puts_the_result_away(api: tuple[TestClient, Runtime], live_ann: dict[str, Any]) -> None:
    client, rt = api
    d = client.post("/api/coachref/drills", json={"corner": "T2", "laps": 3}).json()
    feed(rt, live_ann["sid"], live_ann["info"], [(live_ann["laps"][0], 69_000, 4)])
    assert client.post("/api/coachref/drills/active/stop").json()["status"] == "stopped"
    assert rt.live.snapshot()["coachref"]["drill"]["id"] == d["id"]  # the result shows until Done
    assert client.post(f"/api/coachref/drills/{d['id'] + 1}/dismiss").status_code == 404
    r = client.post(f"/api/coachref/drills/{d['id']}/dismiss")
    assert r.status_code == 204
    assert rt.live.snapshot()["coachref"]["drill"] is None
    assert client.post(f"/api/coachref/drills/{d['id']}/dismiss").status_code == 404
    assert client.get(f"/api/coachref/drills/{d['id']}").json()["status"] == "stopped"  # history keeps it


def test_radio_commands(api: tuple[TestClient, Runtime], live_ann: dict[str, Any]) -> None:
    _, rt = api
    svc = rt.coachref

    def say(q: str) -> tuple[str, dict[str, Any]]:
        return svc.radio_command(detect_intent(q), q)

    assert say("how's my drill going") == (
        "No drill running. Say 'start a drill on turn 3'.",
        {"action": "drill_status", "drill_id": None},
    )
    assert say("stop the drill")[0] == "No drill running."
    assert say("start a drill please")[0] == "Which corner? Say, for example, drill turn 3."
    text, control = say("give me a braking drill at turn 2 for three laps")
    assert (
        text
        == "Copy. T2 brake point drill, 3 laps: brake within 5 m of your best lap's braking point. It starts on your next lap."
    )
    assert control["action"] == "drill_start" and isinstance(control["drill_id"], int)
    assert say("start a drill on turn 4")[0] == "A T2 drill is running: 0 of 3 done. Say 'stop the drill' first."
    feed(rt, live_ann["sid"], live_ann["info"], [(live_ann["laps"][0], 69_000, 4)])
    status, _ = say("how am I doing on the drill")
    assert status.startswith("T2 brake point drill: 1 of 3 done, 1 hit. Last one on the point")
    assert say("cancel my drill")[0] == "Copy, T2 drill stopped: 1 of 1 on the point."
    assert say("how's the drill going")[0].startswith("T2 drill stopped after 1 of 3 laps: 1 of 1 on the point.")
    assert say("drill at Nowhere")[0] == "I can't find Nowhere on this track."
