"""Motivation API (``api/routes_motivation.py``): every endpoint and status code, replay and synthetic exclusion,
re-assignment and reopening, and goals following a deleted driver."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.api.routes_drivers import router as drivers_router
from pitwall.api.routes_motivation import router
from pitwall.core.live import LiveState
from pitwall.drivers import DriverService
from pitwall.model.telemetry import EventKind
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from tests.unit.motivation_data import SeedLap, SeedSession, game_event, seed, seed_laps

NOW = datetime.now().timestamp()
_LAST_MONDAY = date.today() - timedelta(days=date.today().weekday() + 7)
SAT = (
    datetime.combine(_LAST_MONDAY + timedelta(days=5), datetime.min.time()).timestamp() + 12 * 3600
)  # last Saturday noon


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, SimpleNamespace]]:
    db = Database(tmp_path / "motivation.sqlite3")
    writer = DbWriter(db)
    rt = SimpleNamespace(db=db, writer=writer, live=LiveState(), drivers=DriverService(db, writer, default_name="Sam"))
    app = FastAPI()
    app.include_router(drivers_router)
    app.include_router(router)
    app.state.runtime = rt
    with TestClient(app) as client:
        yield client, rt
    writer.close()


@pytest.fixture
def driving(api: tuple[TestClient, SimpleNamespace]) -> dict[str, Any]:
    """Sam: two Austria sessions in the Haas (1:11.745 then 1:10.549, sectors for an ideal lap), a replay and a
    synthetic session that must never count; Jo: one session."""
    _client, rt = api
    sam = rt.drivers.default_id
    jo = rt.drivers.create("Jo").id
    a = seed(rt.writer, SeedSession("a", sam, SAT, seed_laps([71_745, 72_100])))
    b_laps = [
        SeedLap(1, 71_000, sectors=(18_000, 31_000, 22_000)),
        SeedLap(2, 70_549, sectors=(18_100, 30_200, 22_249)),
        SeedLap(3, 70_900, sectors=(18_500, 30_000, 22_400)),
        SeedLap(4, 70_800, sectors=(18_400, 30_438, 21_962)),
    ]
    b = seed(rt.writer, SeedSession("b", sam, SAT + 600, b_laps))
    seed(rt.writer, SeedSession("rep", sam, SAT + 1200, seed_laps([60_000, 60_000, 60_000]), source="replay:x.pwcap"))
    seed(
        rt.writer,
        SeedSession("syn", sam, SAT + 1800, seed_laps([65_000] * 4), synthetic=True, track_id="synthetic:demo"),
    )
    seed(rt.writer, SeedSession("jo1", jo, SAT + 2400, seed_laps([69_000, 69_100])))
    return {"sam": sam, "jo": jo, "a": a, "b": b}


def post(client: TestClient, driver: int, **body: Any) -> Any:
    return client.post(f"/api/drivers/{driver}/goals", json=body)


# ---------------------------------------------------------------------------------------------- goals
def test_create_list_patch_delete(api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]) -> None:
    client, _rt = api
    sam = driving["sam"]
    assert client.get(f"/api/drivers/{sam}/goals").json() == {
        "driver_id": sam,
        "simple": False,
        "goals": [],
        "limits": {"max_active": 6, "active": 0},
    }
    r = post(client, sam, kind="lap_time", target=70_000, from_session_id="b")
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["title"] == "A lap under 1:10.000" and g["scope_text"] == "Austria · Haas" and g["status"] == "active"
    assert g["scope"]["track_length_m"] == 4318.0 and g["scope"]["car_id"] == "f1:team:7"
    assert g["progress"]["baseline"] == 70_549 and g["progress"]["current"] is None  # laps before it do not count
    # nothing driven since it was set: no bar, and the gap from the best it was set against
    assert g["progress"]["fraction"] is None and g["achieved"] is None
    assert g["progress"]["text"] == "0.549 s to go from your best 1:10.549"
    assert g["progress"]["text_simple"] == "About 0.5 s to go"
    streak = post(client, sam, kind="clean_streak", target=8).json()
    assert streak["scope_text"] is None and streak["progress"]["baseline"] == 4
    body = client.get(f"/api/drivers/{sam}/goals").json()
    assert [x["id"] for x in body["goals"]] == [streak["id"], g["id"]]  # newest first
    assert body["limits"]["active"] == 2
    archived = client.patch(f"/api/drivers/{sam}/goals/{g['id']}", json={"status": "archived"}).json()
    assert archived["status"] == "archived"
    assert [x["id"] for x in client.get(f"/api/drivers/{sam}/goals").json()["goals"]] == [streak["id"]]
    assert len(client.get(f"/api/drivers/{sam}/goals", params={"status": "archived"}).json()["goals"]) == 1
    assert client.patch(f"/api/drivers/{sam}/goals/{g['id']}", json={"status": "active"}).json()["status"] == "active"
    assert client.delete(f"/api/drivers/{sam}/goals/{g['id']}").json() == {"deleted": g["id"]}
    assert client.delete(f"/api/drivers/{sam}/goals/{g['id']}").status_code == 404
    assert client.get("/api/drivers/999/goals").status_code == 404
    assert client.patch(f"/api/drivers/{sam}/goals/{streak['id']}", json={"status": "achieved"}).status_code == 422
    assert client.get(f"/api/drivers/{sam}/goals", params={"status": "done"}).status_code == 422


def test_refusals(api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]) -> None:
    client, _rt = api
    sam, jo = driving["sam"], driving["jo"]
    beaten = post(client, sam, kind="lap_time", target=71_000, from_session_id="b")
    assert beaten.status_code == 409
    assert beaten.json() == {"detail": "Your best here is already 1:10.549.", "code": "already_beaten"}
    assert post(client, sam, kind="lap_time", target=70_000, from_session_id="b").status_code == 201
    assert post(client, sam, kind="lap_time", target=70_000, from_session_id="b").json()["code"] == "duplicate"
    assert post(client, sam, kind="lap_time", target=69_500, from_session_id="b").json()["code"] == "duplicate_scope"
    for n in (3, 4, 5, 6, 7):
        assert post(client, sam, kind="clean_streak", target=n).status_code == 201
    too_many = post(client, sam, kind="clean_streak", target=9)
    assert too_many.status_code == 409 and too_many.json()["code"] == "too_many"
    bad = post(client, jo, kind="lap_time", target=70_050, from_session_id="jo1")
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_target"
    other = post(client, jo, kind="lap_time", target=68_000, from_session_id="b")  # Sam's session
    assert other.status_code == 422 and other.json()["code"] == "unknown_session"
    syn = post(client, sam, kind="lap_time", target=60_000, game="f1_25", track_id="synthetic:demo", car_id="x")
    assert syn.status_code == 422 and syn.json()["code"] == "synthetic_scope"
    gt7 = post(client, jo, kind="race_clean", target=1, params={"rule": "no_contact"}, game="gt7")
    assert gt7.json()["code"] == "unsupported_game"
    assert post(client, jo, kind="clean_streak", target=5, colour="red").status_code == 422  # unknown field
    assert post(client, 999, kind="clean_streak", target=5).status_code == 404


def test_class_scope_and_explicit_scope(api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]) -> None:
    client, _rt = api
    sam = driving["sam"]
    g = post(
        client, sam, kind="lap_time", target=70_000, game="f1_25", track_id="f1:17", car_class="f1_25:formula:F1 World"
    ).json()
    assert g["scope"]["car_id"] is None and g["scope_text"] == "Austria · any F1 World car"
    assert g["scope"]["track_name"] == "Austria"  # labels from the latest session at that track


# ---------------------------------------------------------------------------------------------- reassignment
def test_reassignment_and_reopen(api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]) -> None:
    client, rt = api
    sam, jo = driving["sam"], driving["jo"]
    gid = post(client, sam, kind="clean_streak", target=2).json()["id"]
    lap_id = driving["b"][1]
    rt.writer.call(lambda c: repo.mark_goal_achieved(c, gid, unix=NOW, session_id="b", lap_id=lap_id, value=2))
    (g,) = client.get(f"/api/drivers/{sam}/goals").json()["goals"]
    assert g["status"] == "achieved" and g["achieved"]["session_owned"] and g["achieved"]["lap_number"] == 2
    assert g["progress"]["met"] and g["progress"]["text"] == "Reached: 2 clean laps in a row"
    rt.drivers.assign_session("b", jo)  # forgot to switch: it was Jo's session
    (g2,) = client.get(f"/api/drivers/{sam}/goals").json()["goals"]
    assert g2["achieved"]["session_owned"] is False
    reopened = client.patch(f"/api/drivers/{sam}/goals/{gid}", json={"status": "active"}).json()
    assert reopened["status"] == "active" and reopened["achieved"] is None


def test_reopen_refused_while_own_driving_still_reaches_it(
    api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]
) -> None:
    """Reopened, a goal the driver's own laps still reach would be reached (and celebrated) again by the same lap."""
    client, rt = api
    sam = driving["sam"]
    gid = post(client, sam, kind="clean_streak", target=2).json()["id"]
    ids = seed(rt.writer, SeedSession("c", sam, NOW - 60, seed_laps([70_700, 70_650, 70_600])))
    rt.writer.call(lambda c: repo.mark_goal_achieved(c, gid, unix=NOW, session_id="c", lap_id=ids[1], value=2))
    r = client.patch(f"/api/drivers/{sam}/goals/{gid}", json={"status": "active"})
    assert r.status_code == 409 and r.json()["code"] == "still_reached"
    assert r.json()["detail"] == "Your own driving still reaches this goal. To go for it again, add it as a new goal."
    (g,) = client.get(f"/api/drivers/{sam}/goals").json()["goals"]
    assert g["status"] == "achieved" and g["achieved"]["lap_id"] == ids[1]
    # archived and back: the same refusal (its achievement is kept while archived)
    assert client.patch(f"/api/drivers/{sam}/goals/{gid}", json={"status": "archived"}).status_code == 200
    assert client.patch(f"/api/drivers/{sam}/goals/{gid}", json={"status": "active"}).json()["code"] == "still_reached"


def test_deleting_a_driver_deletes_their_goals(
    api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]
) -> None:
    client, _rt = api
    sam, jo = driving["sam"], driving["jo"]
    gid = post(client, jo, kind="clean_streak", target=4).json()["id"]
    assert client.delete(f"/api/drivers/{jo}", params={"reassign_to": sam}).status_code == 200
    assert client.get(f"/api/drivers/{sam}/goals", params={"status": "active,achieved,archived"}).json()["goals"] == []
    assert client.delete(f"/api/drivers/{sam}/goals/{gid}").status_code == 404


# ---------------------------------------------------------------------------------------------- suggestions
def test_suggestions(api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]) -> None:
    client, _rt = api
    sam = driving["sam"]
    body = client.get(f"/api/drivers/{sam}/goals/suggestions").json()
    assert body["scope"]["track_name"] == "Austria" and body["scope"]["car_class"] == "f1_25:formula:F1 World"
    kinds = [s["kind"] for s in body["suggestions"]]
    assert kinds[0] == "lap_time" and body["suggestions"][0]["target"] == 70_000
    assert body["none_reason"] is None
    create = body["suggestions"][0]["create"]
    assert client.post(f"/api/drivers/{sam}/goals", json=create).status_code == 201
    again = client.get(f"/api/drivers/{sam}/goals/suggestions", params={"game": "f1_25", "track_id": "f1:17"}).json()
    assert "lap_time" not in [s["kind"] for s in again["suggestions"]]
    nowhere = client.get(f"/api/drivers/{sam}/goals/suggestions", params={"game": "f1_25", "track_id": "f1:99"}).json()
    assert nowhere["none_reason"] is not None
    assert client.get(f"/api/drivers/{sam}/goals/suggestions", params={"from_session_id": "jo1"}).status_code == 422


# ---------------------------------------------------------------------------------------------- badges, digest
def test_badges_exclude_replays_and_synthetic(api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]) -> None:
    client, _rt = api
    sam = driving["sam"]
    body = client.get(f"/api/drivers/{sam}/badges").json()
    assert body["include_synthetic"] is False and body["simple"] is False
    keys = {b["key"] for b in body["badges"]}
    assert "first_clean_lap:f1_25:f1:17" in keys and "under_time:f1_25:f1:17:f1:team:7:71000" in keys
    assert not any("synthetic" in k for k in keys) and not any(b["synthetic"] for b in body["badges"])
    assert body["streaks"]["clean_laps"]["best"] == 4  # never the replay's or the synthetic session's laps
    with_syn = client.get(f"/api/drivers/{sam}/badges", params={"synthetic": "true"}).json()
    assert with_syn["include_synthetic"] and any(b["synthetic"] for b in with_syn["badges"])
    assert client.get("/api/drivers/999/badges").status_code == 404


def test_digest(api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]) -> None:
    client, _rt = api
    sam = driving["sam"]
    week = date.fromtimestamp(SAT).isoformat()
    d = client.get(f"/api/drivers/{sam}/digest", params={"week": week}).json()
    assert d["driver"] == {"id": sam, "name": "Sam", "skill_level": "advanced"}
    assert d["totals"]["sessions"] == 2 and d["totals"]["laps"] == 6
    assert d["markdown"].startswith("# Sam's week: ")
    future = (date.today() + timedelta(days=8)).isoformat()
    assert client.get(f"/api/drivers/{sam}/digest", params={"week": future}).json()["code"] == "future_week"
    assert client.get(f"/api/drivers/{sam}/digest", params={"week": "soon"}).status_code == 422
    page = client.get(f"/api/drivers/{sam}/digest.html", params={"week": week})
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "<title>Sam&#x27;s week:" in page.text
    assert client.get("/api/drivers/999/digest").status_code == 404


# ---------------------------------------------------------------------------------------------- recap
def test_recap(api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]) -> None:
    client, _rt = api
    r = client.get("/api/sessions/b/recap").json()
    assert set(r) == {
        "session_id", "driver_id", "driver_name", "simple", "synthetic", "replay", "ended", "laps", "clean_laps",
        "things", "why_empty", "goals_achieved", "goals_progress", "badges_earned",
    }  # fmt: skip
    assert r["driver_name"] == "Sam" and r["ended"] and (r["laps"], r["clean_laps"]) == (4, 4)
    assert r["things"]["went_well"]["source"] == "pb"
    assert (
        r["things"]["went_well"]["text"]
        == "New personal best at Austria in the Haas: 1:10.549 on lap 2, 1.196 s faster than before."
    )
    assert r["things"]["progress"]["source"] == "sessions_week"
    assert [b["key"] for b in r["badges_earned"]] == ["clean_streak:3", "under_time:f1_25:f1:17:f1:team:7:71000"]
    rep = client.get("/api/sessions/rep/recap").json()
    assert rep["replay"] and rep["things"]["progress"] is None
    assert rep["why_empty"]["progress"] == "Replays are not anyone's driving"
    syn = client.get("/api/sessions/syn/recap").json()
    assert syn["synthetic"] and syn["why_empty"]["progress"] == "Synthetic sessions do not count towards progress"
    assert client.get("/api/sessions/nope/recap").status_code == 404


def test_recap_lists_goals_in_scope(api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]) -> None:
    client, rt = api
    sam = driving["sam"]
    lap_goal = post(client, sam, kind="lap_time", target=70_000, from_session_id="b").json()
    post(client, sam, kind="clean_streak", target=8)
    seed(rt.writer, SeedSession("c", sam, NOW - 60, seed_laps([70_700, 70_650])))  # not a new best
    r = client.get("/api/sessions/c/recap").json()
    assert [g["kind"] for g in r["goals_progress"]] == ["lap_time", "clean_streak"]
    assert r["things"]["progress"]["source"] == "goal_progress" and r["things"]["progress"]["goal_id"] == lap_goal["id"]
    assert r["things"]["progress"]["text"] == "A lap under 1:10.000: 0.650 s to go (best since you set it 1:10.650)."


def test_race_recap_and_events(api: tuple[TestClient, SimpleNamespace], driving: dict[str, Any]) -> None:
    client, rt = api
    sam = driving["sam"]
    events = [game_event(EventKind.COLLISION, {"vehicle1Idx": 19, "vehicle2Idx": 4, "player_idx": 19})]
    seed(
        rt.writer, SeedSession("race", sam, NOW - 30, seed_laps([88_000, 78_000, 78_100]), total_laps=3, events=events)
    )
    gid = post(client, sam, kind="race_clean", target=1, params={"rule": "no_contact"}).json()["id"]
    (g,) = [x for x in client.get(f"/api/drivers/{sam}/goals").json()["goals"] if x["id"] == gid]
    # the race was stored before the goal; a race is reached or not: no part-way bar
    assert g["progress"]["text"] == "No race recorded from lap 1 to the flag since you set it"
    assert g["progress"]["fraction"] is None
    badges = {b["key"] for b in client.get(f"/api/drivers/{sam}/badges").json()["badges"]}
    assert "clean_race:no_penalties" in badges and "clean_race:no_contact" not in badges
