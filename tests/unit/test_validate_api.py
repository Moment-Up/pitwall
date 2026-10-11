"""Rig validation kit API (/api/validation) through the real app: statuses, actions, device reports, reports,
and the radio commands through the hub's typed-question path (no STT, no TTS, no LLM)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pitwall.config import Settings
from pitwall.validate.rules import SWITCH_SETTLE_S as R_SETTLE
from pitwall.voice.hub import NO_GAME_REPLY, NO_SESSION_REPLY

V = "/api/validation"


class ScriptedStt:
    name = "scripted"

    def warmup(self) -> None:
        return None

    def transcribe(self, clip: Any, prompt: str | None = None) -> Any:
        raise AssertionError("typed questions never reach the STT")


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, Any]]:
    from pitwall.api.app import create_app

    s = Settings(
        data_dir=tmp_path,
        llm_enabled=False,
        stt_engine="none",
        tts_engine="none",
        tailscale_trust_owner=False,
        access_token="tok",
    )
    app = create_app(s, start_udp=False)
    with TestClient(app) as client:
        yield client, app


def report_body(run_id: str, **kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "run_id": run_id,
        "client_id": "5f1c2a9e-7b3d-4c11-9a2e-0d4b8f6e1a77",
        "seq": 1,
        "reason": "start",
        "t_client_ms": 1000.0,
        "device": "ipad",
        "standalone": True,
        "secure_context": True,
        "origin_kind": "tailscale_https",
        "safari_version": "18.6",
        "viewport": {"w": 1180, "h": 820, "dpr": 2, "orientation": "landscape"},
        "visibility": "visible",
        "route": "drive/coach",
        "wake": {"wanted": True, "state": "on"},
        "radio": {
            "phase": "live",
            "conn": "open",
            "mic": "live",
            "mic_silent": False,
            "wake": "on",
            "audio": "running",
            "audio_session": "play-and-record",
            "tts_mode": "server",
            "rtt_ms": 38,
        },
        "audio_input_kind": "airpods",
        "fps_10s": None,
    }
    body.update(kw)
    return body


def wait_for(fn: Any, timeout: float = 5.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("condition not met")


def test_catalog_and_empty_state(api: tuple[TestClient, Any]) -> None:
    c, _app = api
    cat = c.get(f"{V}/catalog").json()
    by = {i["id"]: i for i in cat["items"]}
    assert (
        by["radio_ptt"]["available"] is False
        and by["radio_ptt"]["unavailable_reason"] == "Speech recognition is off on this Mac."
    )
    assert by["cues_timing"]["available"] is True  # the radio hub runs (null engines)
    assert by["radio_kokoro"]["available"] is False
    assert by["driver_switch"]["unavailable_reason"] == "Add a second driver in Settings › Drivers first."
    assert c.get(f"{V}/active").json() == {"run": None}
    assert c.get(f"{V}/runs").json() == []
    assert c.post(f"{V}/client", json=report_body("20261012-193012-a3f1")).status_code == 409


def test_run_lifecycle_and_statuses(api: tuple[TestClient, Any]) -> None:
    c, app = api
    assert c.post(f"{V}/runs", json={"items": ["nope"]}).status_code == 404
    assert c.post(f"{V}/runs", json={"items": ["radio_ptt"]}).status_code == 409  # unavailable here
    assert c.post(f"{V}/runs", json={"bogus": 1}).status_code == 422
    r = c.post(f"{V}/runs", json={"items": ["gt7_ps5", "ipad_home_screen", "cues_timing"], "label": "Desk run"})
    assert r.status_code == 201
    run = r.json()
    rid = run["id"]
    assert run["selected_items"] == ["ipad_home_screen", "cues_timing", "gt7_ps5"]  # catalogue order
    assert run["current_item"] == "ipad_home_screen" and run["label"] == "Desk run" and run["format"] == 1
    assert run["context"]["telemetry"] == "no_data" and run["items"][0]["status"] == "current"
    assert c.post(f"{V}/runs", json={}).status_code == 409
    assert c.get(f"{V}/active").json()["run"]["id"] == rid
    assert c.get(f"{V}/runs/not-a-run").status_code == 422
    assert c.get(f"{V}/runs/20000101-000000-0000").status_code == 404
    full = c.get(f"{V}/runs/{rid}?detail=full").json()
    assert set(full["evidence"]) >= {"cues", "ptt", "proactive", "laps", "switches", "input_phases", "game"}
    assert "evidence" not in c.get(f"{V}/runs/{rid}").json()

    v1 = c.post(f"{V}/runs/{rid}/current", json={"item_id": "gt7_ps5"}).json()
    assert v1["current_item"] == "gt7_ps5" and v1["items"][0]["status"] == "pending"
    assert c.post(f"{V}/runs/{rid}/current", json={"item_id": "radio_ptt"}).status_code == 404  # not in this run
    v2 = c.post(f"{V}/runs/{rid}/next", json={}).json()
    assert v2["current_item"] is None and v2["version"] > v1["version"]  # gt7_ps5 was the last test
    v2 = c.post(f"{V}/runs/{rid}/next", json={}).json()
    assert v2["current_item"] == "ipad_home_screen"  # with none current, "next" starts from the first pending test
    # verdicts: attestations are filtered to the item's own keys; null clears this driver's mark
    v3 = c.post(
        f"{V}/runs/{rid}/items/ipad_home_screen/verdict",
        json={"verdict": "worked", "notes": "fine", "attestations": {"did_not_touch": True, "bogus": True}},
    ).json()
    hs = next(i for i in v3["items"] if i["id"] == "ipad_home_screen")
    assert hs["marks"][0]["attestations"] == {"did_not_touch": True} and hs["marks"][0]["source"] == "screen"
    assert hs["result"] == "needs_review"  # worked + no evidence
    cleared = c.post(f"{V}/runs/{rid}/items/ipad_home_screen/verdict", json={"verdict": None}).json()
    assert next(i for i in cleared["items"] if i["id"] == "ipad_home_screen")["marks"] == []
    assert c.post(f"{V}/runs/{rid}/items/ipad_home_screen/verdict", json={"verdict": "maybe"}).status_code == 422
    assert (
        c.post(
            f"{V}/runs/{rid}/items/ipad_home_screen/verdict", json={"verdict": "worked", "notes": "x" * 2001}
        ).status_code
        == 422
    )
    # input check: only tests that have one, only their phases
    assert c.post(f"{V}/runs/{rid}/items/gt7_ps5/input-check", json={"phase": "left"}).status_code == 200
    assert c.post(f"{V}/runs/{rid}/items/gt7_ps5/input-check", json={"phase": "reverse"}).status_code == 409
    assert c.post(f"{V}/runs/{rid}/items/ipad_home_screen/input-check", json={"phase": "left"}).status_code == 409
    assert c.post(f"{V}/runs/{rid}/items/gt7_ps5/input-check", json={"phase": "sideways"}).status_code == 422
    stopped = c.post(f"{V}/runs/{rid}/items/gt7_ps5/input-check", json={"phase": "stop"}).json()
    assert c.get(f"{V}/runs/{rid}?detail=full").json()["evidence"]["input_phases"][0]["phase"] == "left"
    assert stopped["id"] == rid
    # skip moves on from the current test
    sk = c.post(f"{V}/runs/{rid}/items/ipad_home_screen/skip", json={"reason": "no iPad today"}).json()
    hs = next(i for i in sk["items"] if i["id"] == "ipad_home_screen")
    assert hs["status"] == "skipped" and hs["result"] == "skipped" and sk["current_item"] == "cues_timing"
    assert c.post(f"{V}/runs/{rid}/records/ptt/m999", json={"heard_right": True}).status_code == 404
    # finish writes the files; the run is no longer active
    fin = c.post(f"{V}/runs/{rid}/finish", json={"notes": "desk check"}).json()
    assert fin["status"] == "finished" and fin["ended_unix"] and fin["notes"] == "desk check"
    folder = Path(app.state.runtime.settings.data_dir) / "validation" / rid
    assert sorted(p.name for p in folder.iterdir()) == ["report.json", "report.md", "run.json"]
    assert c.get(f"{V}/active").json() == {"run": None}
    assert c.post(f"{V}/runs/{rid}/next", json={}).status_code == 409  # run not active
    rep = c.get(f"{V}/runs/{rid}/report").json()
    assert rep["in_progress"] is False and rep["disclaimer"].startswith("This report never changes capability statuses")
    assert [r["id"] for r in c.get(f"{V}/runs").json()] == [rid]


def test_client_reports(api: tuple[TestClient, Any]) -> None:
    c, _app = api
    rid = c.post(f"{V}/runs", json={"items": ["ipad_home_screen"]}).json()["id"]
    assert c.post(f"{V}/client", json=report_body(rid)).status_code == 204
    assert c.post(f"{V}/client", json=report_body(rid, seq=2, reason="interval")).status_code == 204
    assert c.post(f"{V}/client", json=report_body(rid, seq=1, reason="start")).status_code == 204  # a reload
    assert c.post(f"{V}/client", json=report_body("20000101-000000-0000")).status_code == 409
    assert c.post(f"{V}/client", json=report_body(rid, device="toaster")).status_code == 422
    assert c.post(f"{V}/client", json=report_body(rid, route="drive/" + "x" * 64)).status_code == 422
    assert c.post(f"{V}/client", json=report_body(rid, safari_version="1" * 17)).status_code == 422
    assert c.post(f"{V}/client", json={**report_body(rid), "label": "AirPods Pro"}).status_code == 422  # no labels
    run = c.get(f"{V}/runs/{rid}").json()
    (client,) = run["clients"]
    assert client["device"] == "ipad" and client["reloads"] == 1 and client["origin_kind"] == "tailscale_https"
    assert client["audio_input_kind"] == "airpods" and client["radio"]["tts_mode"] == "server"
    assert set(client) == {
        "client_id",
        "device",
        "standalone",
        "secure_context",
        "origin_kind",
        "safari_version",
        "last_seen_s",
        "route",
        "visibility",
        "wake",
        "radio",
        "audio_input_kind",
        "gaps",
        "hidden_transitions",
        "reloads",
        "wake_on_streak_s",
        "fps",
    }
    hs = run["items"][0]
    assert hs["auto"]["verdict"] in ("not_live", "no_evidence")  # no live telemetry: never a pass
    c.post(f"{V}/runs/{rid}/abort", json={})
    assert c.post(f"{V}/client", json=report_body(rid, seq=3)).status_code == 409


def test_radio_commands_and_transcripts(api: tuple[TestClient, Any]) -> None:
    c, app = api
    hub = app.state.hub
    assert hub is not None and hub.command_handler == app.state.validation.voice_command
    hub.stt = ScriptedStt()  # a speech engine makes the push-to-talk test available (typed questions skip it)
    # with no run active only "start validation" is a command: "next test" or "passed" reach the engineer
    for said in ("next test", "passed", "it worked"):
        n = len(hub.history)
        assert c.post("/api/voice/ask", json={"text": said}).json() == {"queued": True}
        wait_for(lambda n=n: len(hub.history) > n and hub.history[0]["role"] == "engineer")
        assert "validation" not in hub.history[0]["text"].lower(), hub.history[0]
    assert c.get(f"{V}/active").json()["run"] is None
    c.post("/api/voice/ask", json={"text": "start validation"})
    run_id = wait_for(lambda: (c.get(f"{V}/active").json()["run"] or {}).get("id"))
    first = c.get(f"{V}/runs/{run_id}").json()["current_item"]
    assert first == "ipad_home_screen"
    wait_for(lambda: hub.history and hub.history[0]["text"].startswith("Validation started. First test: screen test."))
    c.post("/api/voice/ask", json={"text": "it worked"})
    wait_for(lambda: hub.history and hub.history[0]["text"] == "Screen test: noted as worked.")
    run = c.get(f"{V}/runs/{run_id}?detail=full").json()
    mark = run["items"][0]["marks"][0]
    assert mark["verdict"] == "worked" and mark["source"] == "voice"
    c.post("/api/voice/ask", json={"text": "What's the test?"})
    wait_for(lambda: hub.history and hub.history[0]["text"].startswith("Test 1 of"))
    assert "Drive five minutes without touching the iPad" in hub.history[0]["text"]  # the test's instructions
    c.post("/api/voice/ask", json={"text": "how are my tyres"})  # an ordinary question reaches the engineer
    # no session and (game selection) no game chosen: the engineer asks which game, from the hub's own replies
    wait_for(lambda: hub.history and hub.history[0]["text"] in (NO_SESSION_REPLY, NO_GAME_REPLY))
    ptt = c.get(f"{V}/runs/{run_id}?detail=full").json()["evidence"]["ptt"]
    by_text = {p["transcript"]: p for p in ptt}
    assert by_text["it worked"]["answer_source"] == "command" and by_text["it worked"]["source"] == "typed"
    assert by_text["how are my tyres"]["answer_source"] == "deterministic"
    md = c.get(f"{V}/runs/{run_id}/report.md").text
    assert "| how are my tyres |" in md
    red = c.get(f"{V}/runs/{run_id}/report.md?redact_transcripts=true")
    assert red.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "| how are my tyres |" not in red.text and "[transcript removed]" in red.text
    # Download JSON honours "Leave out transcripts" too
    js = c.get(f"{V}/runs/{run_id}/report?redact_transcripts=true").text
    assert "how are my tyres" not in js and "[transcript removed]" in js
    assert "how are my tyres" in c.get(f"{V}/runs/{run_id}/report").text
    c.post("/api/voice/ask", json={"text": "finish validation"})
    wait_for(lambda: c.get(f"{V}/active").json()["run"] is None)
    wait_for(lambda: hub.history and hub.history[0]["text"] == "Finishing validation.")
    assert c.get(f"{V}/runs/{run_id}").json()["status"] == "finished"
    md = c.get(f"{V}/runs/{run_id}/report.md").text
    assert md.startswith(f"# Pitwall validation run {run_id}") and "How are my tyres" not in md.split("\n")[0]
    assert "[transcript removed]" in c.get(f"{V}/runs/{run_id}/report.md?redact_transcripts=true").text
    js = c.get(f"{V}/runs/{run_id}/report?redact_transcripts=true").text  # a finished run: built again, redacted
    assert "how are my tyres" not in js and "[transcript removed]" in js


def test_driver_switch_is_recorded_and_settled(api: tuple[TestClient, Any]) -> None:
    c, app = api
    assert c.post("/api/drivers", json={"name": "Sam"}).status_code == 201
    cat = {i["id"]: i for i in c.get(f"{V}/catalog").json()["items"]}
    assert cat["driver_switch"]["available"] is True  # a second profile now exists
    first = c.get("/api/drivers/active").json()["id"]
    second = next(d["id"] for d in c.get("/api/drivers").json()["drivers"] if d["id"] != first)
    rid = c.post(f"{V}/runs", json={"items": ["driver_switch"]}).json()["id"]
    assert c.put("/api/drivers/active", json={"driver_id": second}).status_code == 200
    assert c.put("/api/drivers/active", json={"driver_id": second}).status_code == 200  # same seat: no switch
    time.sleep(R_SETTLE + 0.4)
    c.portal.call(app.state.validation.collector.refresh_db)  # type: ignore[union-attr]
    full = c.get(f"{V}/runs/{rid}?detail=full").json()
    (sw,) = full["evidence"]["switches"]
    assert sw["from_driver_id"] == first and sw["to_driver_id"] == second and sw["settled"] is True
    assert sw["session_before"] is None and sw["ok"] is None  # no telemetry: nothing to check yet
    item = full["items"][0]
    assert item["auto"]["verdict"] == "not_live" and item["result"] == "not_run"  # no answer, nothing live
