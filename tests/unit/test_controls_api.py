"""Setup › Controls API (``/api/controls``): every endpoint, its error codes (404 / 409 / 422), the contract keys, the
printable card (escaped, script-free) and the button test against a live-looking F1 stream."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pitwall.adapters.f1.enums import udp_action_bit
from pitwall.config import Settings


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, Any]]:
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
    app = create_app(s, start_udp=False)
    with TestClient(app) as client:
        yield client, app


def save_gt_wheel(c: TestClient) -> dict[str, Any]:
    r = c.post("/api/controls/wheels", json={"name": "James's <b>wheel</b>", "template": "fanatec_gt_dd_pro_wheel"})
    assert r.status_code == 201, r.text
    return dict(r.json())


def save_f1_layout(c: TestClient, wid: str, **kw: Any) -> dict[str, Any]:
    body = {
        "game": "f1_25",
        "platform": "ps5",
        "wheel_id": wid,
        "owner": "household",
        "preset": "advanced",
        "from_recommendation": True,
        **kw,
    }
    r = c.post("/api/controls/layouts", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_catalog_template_and_empty_state(api: tuple[TestClient, Any]) -> None:
    c, _app = api
    cat = c.get("/api/controls/catalog").json()
    assert cat["status"].startswith("Research only") and len(cat["games"]) == 11 and len(cat["templates"]) == 24
    t = c.get("/api/controls/templates/fanatec_gt_dd_pro_wheel").json()
    assert t["rev"] == 0 and t["template"] == "fanatec_gt_dd_pro_wheel" and len(t["controls"]) == 19
    assert c.get("/api/controls/templates/nope").status_code == 404
    st = c.get("/api/controls/state").json()
    assert set(st) == {"schema", "wheels", "layouts", "household", "drivers", "updated_unix", "ptt", "defaults"}
    assert st["wheels"] == [] and st["ptt"] == {
        "udp_actions": [1],
        "from": "default",
        "layout_id": None,
        "label": None,
        "fallback_kept": True,
    }
    d = st["defaults"]
    assert set(d) == {"driver_id", "game", "platform", "wheel_id", "template", "preset"}
    assert d["template"] == "fanatec_gt_dd_pro_wheel" and d["wheel_id"] is None and d["platform"] == "ps5"


def test_recommendation_draft_and_errors(api: tuple[TestClient, Any]) -> None:
    c, _app = api
    r = c.get(
        "/api/controls/recommendation",
        params={"game": "f1_25", "platform": "ps5", "template": "fanatec_gt_dd_pro_wheel", "preset": "advanced"},
    )
    assert r.status_code == 200, r.text
    rec = r.json()
    assert set(rec) == {
        "game",
        "platform",
        "wheel_id",
        "preset",
        "driver_id",
        "catalogue_version",
        "status",
        "assignments",
        "pitwall_ptt",
        "not_on_wheel",
        "not_in_game",
        "unplaced",
        "reserved",
        "notes",
    }
    assert rec["status"] == "research_only" and rec["pitwall_ptt"]["path"] == "udp_action"
    a = rec["assignments"][0]
    assert set(a) == {
        "key",
        "function",
        "action",
        "control_id",
        "slot",
        "udp_action",
        "origin",
        "check",
        "label",
        "native",
        "menu_group",
        "control_label",
        "signal",
        "reason",
        "evidence",
        "evidence_parts",
        "source_ids",
        "conditions",
        "warnings",
        "pitwall_sees",
    }
    assert (
        c.get(
            "/api/controls/recommendation", params={"game": "nope", "platform": "ps5", "template": "custom"}
        ).status_code
        == 404
    )
    assert (
        c.get(
            "/api/controls/recommendation", params={"game": "f1_25", "platform": "ps5", "wheel_id": "w_00000000"}
        ).status_code
        == 404
    )
    assert (
        c.get(
            "/api/controls/recommendation", params={"game": "f1_25", "platform": "ps9", "template": "custom"}
        ).status_code
        == 422
    )
    other = c.get(
        "/api/controls/recommendation",
        params={
            "game": "other",
            "platform": "pc",
            "template": "custom",
            "game_name": "Rally",
            "functions": "brake_bias,lights",
        },
    )
    assert other.status_code == 200 and other.json()["pitwall_ptt"]["path"] == "screen"


def test_wheels_crud_rev_and_import_export(api: tuple[TestClient, Any]) -> None:
    c, _app = api
    w = save_gt_wheel(c)
    assert w["rev"] == 1 and w["id"].startswith("w_") and len(w["controls"]) == 19
    custom = c.post(
        "/api/controls/wheels",
        json={
            "name": "Box",
            "shape": "box",
            "platforms": ["pc"],
            "controls": [{"id": "b1", "kind": "button", "label": "Big red", "zone": "box"}],
        },
    ).json()
    assert custom["controls"][0]["evidence"] == "H" and custom["controls"][0]["reach"] is None
    bad = c.post("/api/controls/wheels", json={"name": "x", "controls": [{"id": "b1", "kind": "laser", "label": "L"}]})
    assert bad.status_code == 422 and "laser" in bad.json()["detail"]
    assert c.post("/api/controls/wheels", json={"name": "x", "extra": 1}).status_code == 422
    put = {**w, "name": "Renamed"}
    ok = c.put(f"/api/controls/wheels/{w['id']}", json=put)
    assert ok.status_code == 200 and ok.json()["rev"] == 2 and ok.json()["name"] == "Renamed"
    stale = c.put(f"/api/controls/wheels/{w['id']}", json=put)  # still rev 1: someone saved in between
    assert stale.status_code == 409
    assert c.put("/api/controls/wheels/w_00000000", json=put).status_code == 404
    exp = c.get(f"/api/controls/wheels/{w['id']}/export").json()
    assert exp["schema"] == "pitwall.controls.wheel/1"
    exp["wheel"]["controls"][0]["signals"]["ps"]["value"] = "circle"  # changed by hand: becomes the driver's entry
    imp = c.post("/api/controls/wheels/import", json=exp).json()
    assert imp["id"] != w["id"] and imp["rev"] == 1
    ctl = {x["id"]: x for x in imp["controls"]}
    assert ctl["face_triangle"]["signals"]["ps"]["evidence"] == "H"
    assert ctl["face_square"]["signals"]["ps"]["evidence"] == "A"  # unchanged template field keeps its letter
    assert c.post("/api/controls/wheels/import", json={"schema": "nope"}).status_code == 422
    sig = c.put(
        f"/api/controls/wheels/{w['id']}/controls/paddle_left/signal",
        json={
            "platform": "ps",
            "signal": {
                "kind": "pad",
                "value": "l1",
                "evidence": "seen",
                "seen": {"t_unix": 1.0, "bits": ["L1 or LB"], "game": "f1_25", "platform": "ps5"},
            },
        },
    )
    assert sig.status_code == 200 and sig.json()["rev"] == 3
    pl = next(x for x in sig.json()["controls"] if x["id"] == "paddle_left")
    assert pl["signals"]["ps"]["evidence"] == "seen" and pl["signals"]["ps"]["seen"]["bits"] == ["L1 or LB"]
    assert (
        c.put(
            f"/api/controls/wheels/{w['id']}/controls/nope/signal",
            json={"platform": "ps", "signal": {"kind": "pad", "value": "l1"}},
        ).status_code
        == 404
    )
    assert c.delete(f"/api/controls/wheels/{custom['id']}").status_code == 200


def test_layouts_guide_card_and_delete_rules(api: tuple[TestClient, Any]) -> None:
    c, _app = api
    w = save_gt_wheel(c)
    kept = [
        {
            "function": "ptt_pitwall",
            "action": "hold",
            "control_id": "face_cross",
            "slot": "press",
            "udp_action": 1,
            "origin": "kept",
        }
    ]
    lay = save_f1_layout(c, w["id"], assignments=kept)
    ptt = next(a for a in lay["assignments"] if a["function"] == "ptt_pitwall")
    assert ptt["control_id"] == "face_cross" and ptt["origin"] == "kept" and lay["rev"] == 1
    st = c.get("/api/controls/state").json()
    assert st["household"]["layouts"] == {"f1_25:ps5": lay["id"]} and st["ptt"]["from"] == "layout"
    assert c.delete(f"/api/controls/wheels/{w['id']}").status_code == 409  # a layout uses it
    g = c.get(f"/api/controls/layouts/{lay['id']}/guide").json()
    assert set(g) == {"where", "where_evidence", "intro", "steps", "outro"}
    assert set(g["steps"][0]) == {"n", "group", "native", "label", "physical", "evidence", "note"}
    html = c.get(f"/api/controls/layouts/{lay['id']}/card.html")
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert "<script" not in html.text.lower() and "&lt;b&gt;wheel&lt;/b&gt;" in html.text
    assert "<b>wheel</b>" not in html.text and "Research only" in html.text
    assert "UDP Action 1" in html.text and "A4 landscape" in html.text
    txt = c.get(f"/api/controls/layouts/{lay['id']}/card.txt").text
    assert "Research only" in txt and "Talk to Pitwall" in txt
    edit = [a for a in lay["assignments"] if a["function"] != "look"]
    edit.append({"function": "look", "action": "press", "control_id": "tab_l2", "slot": "press"})
    r = c.put(f"/api/controls/layouts/{lay['id']}", json={"rev": 1, "assignments": edit})
    assert r.status_code == 200 and r.json()["rev"] == 2
    assert c.put(f"/api/controls/layouts/{lay['id']}", json={"rev": 1}).status_code == 409
    bad = [{"function": "tc", "action": "inc", "control_id": "tab_l2", "slot": "press"}]
    r = c.put(f"/api/controls/layouts/{lay['id']}", json={"rev": 2, "assignments": bad})
    assert r.status_code == 422 and "can't go on a button" in r.json()["detail"]
    r = c.put(
        f"/api/controls/layouts/{lay['id']}",
        json={"rev": 2, "assignments": [{"function": "look", "action": "press", "control_id": "nope"}]},
    )
    assert r.status_code == 422
    gt7 = c.post(
        "/api/controls/layouts",
        json={
            "game": "gt7",
            "platform": "ps5",
            "wheel_id": w["id"],
            "owner": "household",
            "assignments": [{"function": "ptt_pitwall", "action": "hold", "control_id": "face_cross", "slot": "press"}],
        },
    )
    assert gt7.status_code == 422 and "doesn't send button presses" in gt7.json()["detail"]
    assert (
        c.post(
            "/api/controls/layouts",
            json={"game": "f1_25", "platform": "ps5", "wheel_id": "w_00000000", "owner": "household"},
        ).status_code
        == 404
    )
    assert (
        c.post(
            "/api/controls/layouts", json={"game": "f1_25", "platform": "ps5", "wheel_id": w["id"], "owner": 99}
        ).status_code
        == 404
    )
    assert c.get("/api/controls/layouts/l_00000000/guide").status_code == 404
    assert c.delete(f"/api/controls/layouts/{lay['id']}").status_code == 200
    assert c.get("/api/controls/state").json()["household"]["layouts"] == {}
    assert c.delete(f"/api/controls/wheels/{w['id']}").status_code == 200


def test_driver_choices(api: tuple[TestClient, Any]) -> None:
    c, app = api
    w = save_gt_wheel(c)
    did = app.state.runtime.drivers.active_id
    r = c.put(f"/api/controls/drivers/{did}", json={"wheel_id": w["id"], "preset": "beginner"})
    assert r.status_code == 200 and r.json()["preset"] == "beginner"
    st = c.get("/api/controls/state", params={"driver_id": did}).json()
    assert st["defaults"]["wheel_id"] == w["id"] and st["defaults"]["preset"] == "beginner"
    r = c.put(f"/api/controls/drivers/{did}", json={"preset": None})
    assert r.json()["preset"] is None and r.json()["wheel_id"] == w["id"]  # partial: the wheel is kept
    assert c.put("/api/controls/drivers/999", json={"preset": "advanced"}).status_code == 404
    assert c.put("/api/controls/drivers/household", json={"wheel_id": "w_00000000"}).status_code == 404
    lay = save_f1_layout(c, w["id"])
    assert c.put("/api/controls/drivers/household", json={"layouts": {"gt7:ps5": lay["id"]}}).status_code == 422
    ok = c.put(f"/api/controls/drivers/{did}", json={"layouts": {"f1_25:ps5": lay["id"]}})
    assert ok.status_code == 200 and ok.json()["layouts"] == {"f1_25:ps5": lay["id"]}


def test_changing_a_layouts_owner_moves_the_choice(api: tuple[TestClient, Any]) -> None:
    c, app = api
    did = app.state.runtime.drivers.active_id
    w = save_gt_wheel(c)
    lay = save_f1_layout(c, w["id"])
    r = c.put(f"/api/controls/layouts/{lay['id']}", json={"rev": 1, "owner": did})
    assert r.status_code == 200 and r.json()["owner"] == did
    st = c.get("/api/controls/state").json()
    assert st["household"]["layouts"] == {} and st["drivers"][str(did)]["layouts"] == {"f1_25:ps5": lay["id"]}


def test_button_test_and_identify(api: tuple[TestClient, Any]) -> None:
    c, app = api
    rt = app.state.runtime
    w = save_gt_wheel(c)
    lay = save_f1_layout(c, w["id"])
    gt7 = c.post(
        "/api/controls/layouts",
        json={"game": "gt7", "platform": "ps5", "wheel_id": w["id"], "owner": "household", "from_recommendation": True},
    ).json()
    r = c.post("/api/controls/test", json={"layout_id": gt7["id"]})
    assert r.status_code == 422 and "can't test your wheel here" in r.json()["detail"]
    t = c.post("/api/controls/test", json={"layout_id": lay["id"]})
    assert t.status_code == 201, t.text
    test = t.json()
    assert set(test) == {
        "id",
        "layout_id",
        "started_unix",
        "available",
        "why",
        "saves",
        "wheel_ptt_paused",
        "current",
        "items",
        "feed",
    }
    assert test["available"] is False and "No live F1 25 data" in test["why"]  # nothing streaming in this test
    assert c.post("/api/controls/test", json={"layout_id": lay["id"]}).status_code == 409
    rt.live.on_button(udp_action_bit(1))  # what a live F1 BUTN event does
    got = c.get("/api/controls/test").json()
    assert got["items"][0]["state"] == "detected" and got["feed"][-1]["pressed"] == ["UDP Action 1"]
    assert c.post(f"/api/controls/test/{got['id']}/skip").json()["current"] == 2
    stop = c.post(f"/api/controls/test/{got['id']}/stop")
    assert stop.status_code == 200 and c.get("/api/controls/test").json() is None
    assert c.post(f"/api/controls/test/{got['id']}/stop").status_code == 404
    # nothing was stored: the stream was not live
    saved = c.get("/api/controls/state").json()["layouts"]
    assert all(a["check"] is None for x in saved for a in x["assignments"])
    assert stop.json()["test"]["items"][0]["saved"] is False and stop.json()["test"]["saves"] is False
    ident = c.post("/api/controls/test", json={"mode": "identify"}).json()
    rt.live.on_button(0x800)
    assert c.get("/api/controls/test").json()["items"][0]["seen"] == ["L2 or LT"]
    c.post(f"/api/controls/test/{ident['id']}/stop")
    feed = c.get("/api/controls/buttons").json()
    assert feed["seq"] == 2 and feed["presses"][-1]["pressed"] == ["L2 or LT"]
    assert c.get("/api/controls/buttons", params={"since": feed["seq"]}).json()["presses"] == []


def test_ask_which_button_without_a_session(api: tuple[TestClient, Any]) -> None:
    c, _app = api
    r = c.post("/api/engineer/ask", json={"question": "Which button is brake bias?"})
    assert r.status_code == 200 and r.json()["intent"] == "controls_where"
    assert r.json()["text"] in (
        "Tell me which game you're playing: open Setup, then Game.",
        "You haven't saved buttons for F1 25 yet. Open Setup, then Controls.",
    )


def test_a_live_press_is_stored_as_seen_by_pitwall(api: tuple[TestClient, Any]) -> None:
    c, app = api
    rt = app.state.runtime
    w = save_gt_wheel(c)
    lay = save_f1_layout(c, w["id"])
    rt.live.on_packet(True)  # a stream is arriving (what the UDP listener does)
    test = c.post("/api/controls/test", json={"layout_id": lay["id"]}).json()
    assert test["available"] is True and test["why"] is None and test["saves"] is True
    rt.live.on_button(0, "replay")
    rt.live.on_button(udp_action_bit(1), "replay")  # a replayed press: shown, never counted
    assert c.get("/api/controls/test").json()["items"][0]["state"] == "waiting"
    rt.live.on_button(0)
    rt.live.on_button(udp_action_bit(1))
    assert c.get("/api/controls/test").json()["items"][0]["state"] == "detected"
    c.post(f"/api/controls/test/{test['id']}/stop")
    saved = next(x for x in c.get("/api/controls/state").json()["layouts"] if x["id"] == lay["id"])
    ptt = next(a for a in saved["assignments"] if a["function"] == "ptt_pitwall")
    assert ptt["check"]["result"] == "detected" and ptt["check"]["origin"] == "live"
    assert ptt["check"]["detail"] == "UDP Action 1 seen" and saved["rev"] == lay["rev"] + 1


def test_presses_from_this_computer_are_shown_not_stored(api: tuple[TestClient, Any]) -> None:
    """``pitwall send`` or a loopback replay is not the owner's wheel: the test says so and stores nothing."""
    c, app = api
    rt = app.state.runtime
    w = save_gt_wheel(c)
    lay = save_f1_layout(c, w["id"])
    rt.live.on_packet(True)
    rt.controls.senders = lambda: [{"ip": "127.0.0.1", "last_seen_s": 0.2}]
    test = c.post("/api/controls/test", json={"layout_id": lay["id"]}).json()
    assert test["available"] is True and test["saves"] is False and "this computer" in test["why"]
    rt.live.on_button(udp_action_bit(1))
    assert c.get("/api/controls/test").json()["items"][0]["state"] == "detected"  # shown
    c.post(f"/api/controls/test/{test['id']}/stop")
    saved = next(x for x in c.get("/api/controls/state").json()["layouts"] if x["id"] == lay["id"])
    assert all(a["check"] is None for a in saved["assignments"]) and saved["rev"] == lay["rev"]  # not stored
    rt.controls.senders = lambda: [{"ip": "192.168.1.50", "last_seen_s": 0.2}]
    assert rt.controls.availability()[:2] == (True, None)
