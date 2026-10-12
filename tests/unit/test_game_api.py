"""Game selection API (``/api/games``, ``/api/game``): contract shape, selection persistence and the input side
effects. ``start_udp=False``: no socket is bound, no GT7 heartbeat is sent and no AC client contacts a console."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.model.telemetry import Game, Platform, SessionInfo
from pitwall.storage import repo

LEVELS = {
    "live_validated",
    "recorded_validated",
    "spec_implemented",
    "community_documented",
    "partial",
    "unverified",
    "unsupported",
}
PLATFORMS = {"ps5", "ps4", "xbox", "pc", "any"}
STATUSES = {"supported", "partial", "not_sent", "not_implemented", "unknown"}
GROUPS = {"timing", "coaching", "track", "car", "session", "setup_radio"}
INTEGRATIONS = {"f1", "gt7", "forza", "ac", "record"}
KINDS = {"udp_listen", "udp_heartbeat", "udp_client", "none"}
ACTIONS = {
    "enabled",
    "already_enabled",
    "set_platform",
    "set_console_ip",
    "needs_console_ip",
    "skipped_live",
    "error",
    "none",
}
ENTRY_KEYS = {
    "id",
    "game_key",
    "label",
    "short_label",
    "text_name",
    "platform",
    "platform_label",
    "group",
    "adapter_game",
    "variant",
    "implemented",
    "integration",
    "support",
    "transport",
    "guide_id",
    "rig",
    "features",
    "notes",
}
FEATURE_KEYS = {"id", "label", "group", "status", "evidence", "short", "reason", "detail", "note", "fields"}
STATE_KEYS = {
    "selected",
    "entry",
    "effective_id",
    "first_run",
    "detected",
    "mismatch",
    "suggestion",
    "input",
    "other_inputs",
    "driver_defaults",
}
INPUT_KEYS = {
    "key",
    "name",
    "enabled",
    "listening",
    "received",
    "console_ip",
    "console_ip_need",
    "port",
    "platform",
    "error",
    "in_use",
}


def check_entry(e: dict[str, Any], *, full: bool = False) -> None:
    """Hand-written validator of ``GameEntry`` (web-react/src/lib/endpoints/game.ts, design spec section 9.2)."""
    assert set(e) == ENTRY_KEYS | ({"fields", "guide"} if full else set()), set(e) ^ ENTRY_KEYS
    assert e["platform"] in PLATFORMS and e["group"] in ("main", "more")
    assert e["id"] == f"{e['game_key']}:{e['platform']}"
    assert isinstance(e["implemented"], bool) and isinstance(e["notes"], list)
    assert e["integration"] is None or e["integration"] in INTEGRATIONS
    sup = e["support"]
    assert set(sup) == {"level", "words", "summary", "note", "capability_row"}
    assert isinstance(sup["summary"], str) and sup["summary"]
    assert sup["level"] is None or sup["level"] in LEVELS
    assert isinstance(sup["words"], str) and sup["words"]
    t = e["transport"]
    assert set(t) == {"kind", "summary", "port", "console_port", "console_ip", "in_game_setting"}
    assert t["kind"] in KINDS and t["console_ip"] in ("required", "optional", "no")
    assert e["rig"] is None or (set(e["rig"]) == {"game", "platform"} and e["rig"]["game"] in ("f1_25", "gt7"))
    assert len(e["features"]) == 24  # spotter: + "spotter"
    for f in e["features"]:
        assert set(f) == FEATURE_KEYS
        assert f["status"] in STATUSES and f["group"] in GROUPS
        assert f["evidence"] is None or f["evidence"] in LEVELS
        assert f["evidence"] is None or f["status"] in ("supported", "partial")
        assert isinstance(f["fields"], list) and isinstance(f["reason"], str) and len(f["short"]) <= 32
    if full:
        assert isinstance(e["fields"], dict)
        for v in e["fields"].values():
            assert set(v) == {"level", "status", "source"} and v["status"] in ("sent", "partial", "not_sent", "unknown")


def check_state(s: dict[str, Any]) -> None:
    assert set(s) == STATE_KEYS
    assert s["first_run"] is (s["selected"] is None)
    if s["selected"] is not None:
        assert set(s["selected"]) == {"id", "since_unix", "source", "by_driver_id", "by_driver_name"}
        check_entry(s["entry"])
    if s["input"] is not None:
        assert set(s["input"]) == INPUT_KEYS
    for o in s["other_inputs"]:
        assert set(o) == {"key", "name", "enabled", "in_use", "can_disable"}
    assert s["driver_defaults"] is True  # stretch 3.6 shipped: drivers can have a usual game


def actions_by(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    for a in body["actions"]:
        assert set(a) == {"key", "action", "message"} and a["action"] in ACTIONS
    return {a["action"]: a for a in body["actions"]}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    from pitwall.api.app import create_app

    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        voice_enabled=False,
        llm_enabled=False,
        tailscale_trust_owner=False,
        record_raw=False,
    )
    with TestClient(create_app(s, start_udp=False)) as c:
        yield c


def integration(c: TestClient, key: str) -> dict[str, Any]:
    return next(r for r in c.get("/api/integrations").json() if r["key"] == key)


def test_games_catalogue_shape(client: TestClient) -> None:
    body = client.get("/api/games").json()
    assert body["schema"] == 1
    assert len(body["entries"]) == 23
    for e in body["entries"]:
        check_entry(e)
    assert [f["id"] for f in body["features"]][:3] == ["lap_timing", "sectors", "delta"]
    assert all(set(f) == {"id", "label", "group", "noun"} for f in body["features"])
    assert {g["id"] for g in body["groups"]} == GROUPS
    assert set(body["support_words"]) == LEVELS
    one = client.get("/api/games/gt7:ps5").json()
    check_entry(one, full=True)
    assert one["guide"]["id"] == "gt7" and one["fields"]["tyre_wear_pct"]["status"] == "not_sent"
    assert client.get("/api/games/acc:ps5").json()["guide"] is None
    assert client.get("/api/games/nope:ps5").status_code == 404


def test_first_run_and_snapshot_block(client: TestClient) -> None:
    state = client.get("/api/game").json()
    check_state(state)
    assert state["first_run"] is True and state["selected"] is None and state["input"] is None
    assert state["suggestion"] is None  # no session recorded yet
    assert [o["key"] for o in state["other_inputs"]] == ["f1"]  # F1 is always on, never offered for switching off
    assert state["other_inputs"][0]["can_disable"] is False
    snap = client.get("/api/live").json()
    assert snap["game"] == {
        "selected_id": None,
        "effective_id": None,
        "detected": None,
        "mismatch": None,
        "suggestion": None,
    }
    assert client.get("/api/connect").json()["selected_game"] is None


def test_select_gt7_enables_its_input_and_never_touches_others(client: TestClient) -> None:
    before_forza = integration(client, "forza")
    # Without a console IP the GT7 input would search the network (a broadcast heartbeat): never as a side effect of
    # choosing the game. The selection is saved; the input waits for an IP or an explicit "Search the network".
    body = client.put("/api/game", json={"id": "gt7:ps5"}).json()
    acts = actions_by(body)
    assert set(acts) == {"needs_console_ip"}
    assert acts["needs_console_ip"]["message"].startswith("Enter the PS5's IP address to switch the GT7 input on")
    check_state(body["state"])
    assert body["state"]["selected"]["id"] == "gt7:ps5" and body["state"]["selected"]["source"] == "dashboard"
    assert body["state"]["input"]["key"] == "gt7" and body["state"]["input"]["console_ip_need"] == "optional"
    assert body["state"]["input"]["enabled"] is False and integration(client, "gt7")["enabled"] is False
    assert (
        "PS4's IP" in actions_by(client.put("/api/game", json={"id": "gt7:ps4"}).json())["needs_console_ip"]["message"]
    )
    assert integration(client, "f1")["enabled"] is True
    assert integration(client, "forza") == before_forza
    assert client.get("/api/live").json()["game"]["selected_id"] == "gt7:ps4"
    assert client.get("/api/connect").json()["selected_game"] == "gt7:ps4"
    # console IP: the integration's own LAN-only gate
    bad = client.put("/api/game", json={"id": "gt7:ps5", "console_ip": "8.8.8.8"})
    assert bad.status_code == 422 and "private" in bad.json()["detail"]
    ok = client.put("/api/game", json={"id": "gt7:ps5", "console_ip": "192.168.1.100"}).json()
    assert set(actions_by(ok)) == {"enabled", "set_console_ip"}
    assert actions_by(ok)["set_console_ip"]["message"] == "Console IP set to 192.168.1.100."
    assert integration(client, "gt7")["console_ip"] == "192.168.1.100" and integration(client, "gt7")["enabled"]
    assert client.put("/api/game", json={"id": "forza_motorsport:pc", "console_ip": "192.168.1.5"}).status_code == 422


def test_gt7_network_search_is_an_explicit_choice(client: TestClient) -> None:
    """Setup › Game's "Search the network" (after a confirm) and Setup › Connect switch GT7 on without an IP."""
    assert client.put("/api/integrations/gt7", json={"enabled": True}).status_code == 200
    acts = actions_by(client.put("/api/game", json={"id": "gt7:ps5"}).json())
    assert set(acts) == {"already_enabled", "needs_console_ip"}
    assert acts["needs_console_ip"]["message"].startswith("Optional")


def test_select_ac_sets_its_platform_and_asks_for_the_ip(client: TestClient) -> None:
    acts = actions_by(client.put("/api/game", json={"id": "ac:ps4"}).json())
    assert acts["enabled"]["key"] == "ac"
    assert acts["set_platform"]["message"] == "Assetto Corsa platform set to PS4."
    assert acts["needs_console_ip"]["message"].startswith("Required")
    ac = integration(client, "ac")
    assert ac["enabled"] is True and ac["platform"] == "ps4" and ac["console_ip"] is None
    acts = actions_by(client.put("/api/game", json={"id": "ac:ps4", "console_ip": "192.168.1.50"}).json())
    assert set(acts) == {"already_enabled", "set_console_ip"}


def test_port_conflict_is_an_action_and_the_selection_is_saved(client: TestClient) -> None:
    assert client.put("/api/integrations/forza", json={"port": 33740}).status_code == 200  # Forza still off
    client.put("/api/game", json={"id": "gt7:ps5", "console_ip": "192.168.1.100"})  # GT7 on, receiving on 33740
    body = client.put("/api/game", json={"id": "forza_motorsport:pc"}).json()
    acts = actions_by(body)
    assert acts["error"]["key"] == "forza" and "share a port" in acts["error"]["message"]
    assert body["state"]["selected"]["id"] == "forza_motorsport:pc"
    assert integration(client, "forza")["enabled"] is False
    # the integrations route keeps its own status codes through the shared helper
    assert client.put("/api/integrations/forza", json={"enabled": True}).status_code == 409
    assert client.put("/api/integrations/gt7", json={"console_ip": "8.8.8.8"}).status_code == 422


def test_unreadable_games_unknown_ids_and_clearing(client: TestClient) -> None:
    body = client.put("/api/game", json={"id": "acc:ps5"}).json()
    assert body["actions"][0]["action"] == "none" and body["actions"][0]["key"] is None
    assert "no telemetry output" in body["actions"][0]["message"]
    assert body["state"]["input"] is None
    other = client.put("/api/game", json={"id": "other:any"}).json()
    assert other["actions"][0] == {
        "key": "record",
        "action": "none",
        "message": "Turn on 'Record another game' on Setup › Connect to save its packets for a future decoder.",
    }
    assert integration(client, "record")["enabled"] is False  # never automatic: it binds a port and writes captures
    assert client.put("/api/game", json={"id": "fm7:xbox"}).status_code == 422
    assert client.put("/api/game", json={"id": "gt7:ps5", "colour": "red"}).status_code == 422
    cleared = client.delete("/api/game").json()
    check_state(cleared)
    assert cleared["first_run"] is True
    assert client.get("/api/live").json()["game"]["selected_id"] is None


def test_no_input_changes_with_ensure_input_false(client: TestClient) -> None:
    body = client.put("/api/game", json={"id": "gt7:ps5", "ensure_input": False}).json()
    assert body["actions"] == [] and integration(client, "gt7")["enabled"] is False
    assert body["state"]["input"]["enabled"] is False


def test_a_streaming_input_is_never_modified(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    real = Runtime.input_status

    def busy_ac(self: Runtime) -> list[dict[str, Any]]:
        rows = real(self)
        for r in rows:
            if r["key"] == "ac":
                r.update(enabled=True, console_ip="192.168.1.50", client={"last_rx_s_ago": 0.4}, decoded_s_ago=0.4)
        return rows

    monkeypatch.setattr(Runtime, "input_status", busy_ac)
    body = client.put("/api/game", json={"id": "ac:pc"}).json()
    acts = actions_by(body)
    assert acts["skipped_live"]["message"] == (
        "Assetto Corsa is streaming: change its platform on Setup › Connect after the session."
    )
    assert "set_platform" not in acts
    assert integration(client, "ac")["platform"] == "ps5"  # untouched
    assert body["state"]["input"]["in_use"] is True


def test_sessions_carry_their_entry_and_feed_the_history_suggestion(client: TestClient) -> None:
    rt: Runtime = client.app.state.runtime  # type: ignore[attr-defined]

    def add(sid: str, synthetic: bool, platform: Platform, fmt: int) -> None:
        def write(c: Any) -> None:
            repo.insert_session(c, sid, "f1_25", "udp:20796", synthetic, None, None)
            info = SessionInfo(game=Game.F1_25, platform=platform, extra={"packet_format": fmt})
            repo.update_session_info(c, sid, info)

        rt.writer.call(write)

    add("real", False, Platform.PS5, 2025)
    add("demo", True, Platform.PC, 2026)
    rows = {r["id"]: r for r in client.get("/api/sessions").json()}
    assert rows["real"]["game_entry_id"] == "f1_25:ps5"
    assert rows["demo"]["game_entry_id"] == "f1_25_2026:pc"
    assert client.get("/api/sessions/real").json()["game_entry_id"] == "f1_25:ps5"
    state = client.get("/api/game").json()
    assert state["suggestion"] == {"id": "f1_25:ps5", "source": "history", "text": "You last drove F1 25 on PS5."}
    client.put("/api/game", json={"id": "gt7:ps5"})
    assert client.get("/api/game").json()["suggestion"] is None  # only while nothing is selected


def test_selection_survives_a_restart(tmp_path: Path) -> None:
    from pitwall.api.app import create_app

    s = Settings(_env_file=None, data_dir=tmp_path, voice_enabled=False, llm_enabled=False)  # type: ignore[call-arg]
    with TestClient(create_app(s, start_udp=False)) as c:
        c.put("/api/game", json={"id": "forza_horizon:pc"})
    with TestClient(create_app(s, start_udp=False)) as c:
        assert c.get("/api/game").json()["selected"]["id"] == "forza_horizon:pc"
        assert c.get("/api/live").json()["game"]["selected_id"] == "forza_horizon:pc"


def test_a_drivers_usual_game_is_selected_on_a_seat_change(client: TestClient) -> None:
    rt: Runtime = client.app.state.runtime  # type: ignore[attr-defined]
    bad = client.post("/api/drivers", json={"name": "Sam", "default_game": "fm7:xbox"})
    assert bad.status_code == 422 and "unknown game" in bad.json()["detail"]
    sam = client.post("/api/drivers", json={"name": "Sam", "default_game": "gt7:ps5"}).json()
    assert sam["preferences"]["default_game"] == "gt7:ps5"
    first = rt.drivers.active_id
    assert client.get("/api/game").json()["selected"] is None  # creating a profile is not a seat change
    client.put("/api/drivers/active", json={"driver_id": sam["id"]})
    sel = client.get("/api/game").json()["selected"]
    assert sel["id"] == "gt7:ps5" and sel["source"] == "driver_default"
    # who it was for, so Setup › Game can say "Selected because Sam usually plays GT7" (plan 1.3)
    assert sel["by_driver_id"] == sam["id"] and sel["by_driver_name"] == "Sam"
    assert integration(client, "gt7")["enabled"] is False  # selection only: inputs are untouched
    # editing the seated driver's profile is not a seat change
    client.put("/api/game", json={"id": "ac:ps5", "ensure_input": False})
    client.patch(f"/api/drivers/{sam['id']}", json={"skill_level": "beginner"})
    chosen = client.get("/api/game").json()["selected"]
    assert chosen["id"] == "ac:ps5" and chosen["by_driver_id"] is None and chosen["by_driver_name"] is None
    # an explicit null clears the usual game; omitting it keeps it
    client.patch(f"/api/drivers/{sam['id']}", json={"coaching_intensity": "quiet"})
    assert client.get(f"/api/drivers/{sam['id']}").json()["preferences"]["default_game"] == "gt7:ps5"
    client.patch(f"/api/drivers/{sam['id']}", json={"default_game": None})
    assert client.get(f"/api/drivers/{sam['id']}").json()["preferences"]["default_game"] is None
    # while telemetry is live, whatever is being driven wins
    client.patch(f"/api/drivers/{sam['id']}", json={"default_game": "forza_horizon:pc"})
    client.put("/api/drivers/active", json={"driver_id": first})
    rt.live.on_packet(True)  # telemetry live
    client.put("/api/drivers/active", json={"driver_id": sam["id"]})
    assert client.get("/api/game").json()["selected"]["id"] == "ac:ps5"


def test_engineer_answers_capability_questions_before_any_session(client: TestClient) -> None:
    """D8: with no session recorded, a question only about data the selected game never sends is answered from the
    game's capabilities (deterministic, grounded, no LLM); any other question gets a plain "no session yet" answer
    (plan 6.5: never a raw 409)."""
    nothing = client.post("/api/engineer/ask", json={"question": "any damage?"})  # nothing selected
    assert nothing.status_code == 200 and nothing.json()["session_id"] is None
    assert (
        nothing.json()["text"] == "No session yet: choose your game in Setup › Game, or drive a lap and ask me again."
    )
    client.put("/api/game", json={"id": "ac:ps5", "ensure_input": False})
    r = client.post("/api/engineer/ask", json={"question": "how are my tyres?"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] is None and body["model"] is None and body["grounded"] is True
    assert (
        body["text"] == "Assetto Corsa doesn't send tyre temperatures, tyre wear, tyre pressures or brake temperatures."
    )
    client.put("/api/game", json={"id": "gt7:ps5", "ensure_input": False})
    # GT7 sends tyre temperatures: the tyres question is about data, so it waits for a session
    tyres = client.post("/api/engineer/ask", json={"question": "how are my tyres?"})
    assert tyres.status_code == 200 and tyres.json()["model"] is None
    want = "No session yet: ask about the game (what Gran Turismo 7 sends), or drive a lap and ask again."
    assert tyres.json()["text"] == want
    fuel = client.post("/api/engineer/ask", json={"question": "how much fuel do I have?"}).json()
    assert fuel["model"] is None and fuel["text"].startswith("GT7 sends a fuel level, but sources disagree")
    assert client.get("/api/engineer/history").json() == []  # nothing stored without a session


def test_a_selection_reaches_live_dashboards_without_waiting_for_a_frame(client: TestClient) -> None:
    """/ws/live pushes a snapshot when frames arrive or every 5 s; a changed game block (a selection from another
    device or the CLI, no telemetry flowing) is pushed on the next tick instead."""
    import time

    import orjson

    with client.websocket_connect("/ws/live") as ws:
        first = orjson.loads(ws.receive_bytes())
        assert first["type"] == "snapshot" and first["data"]["game"]["selected_id"] is None
        t0 = time.monotonic()
        client.put("/api/game", json={"id": "forza_horizon:pc", "ensure_input": False})
        while True:
            msg = orjson.loads(ws.receive_bytes())
            if msg["type"] == "snapshot":
                break
        assert msg["data"]["game"]["selected_id"] == "forza_horizon:pc"
        assert time.monotonic() - t0 < 4.0  # not the 5 s static push


def test_stray_packets_are_not_receiving(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Packets arriving that no decoder accepts keep an input "in use" for safety (never modified under the driver),
    but the input card never calls that "Receiving"."""
    real = Runtime.input_status

    def stray_ac(self: Runtime) -> list[dict[str, Any]]:
        rows = real(self)
        for r in rows:
            if r["key"] == "ac":
                r.update(enabled=True, console_ip="192.168.1.50", client={"last_rx_s_ago": 0.4}, decoded_s_ago=None)
        return rows

    monkeypatch.setattr(Runtime, "input_status", stray_ac)
    body = client.put("/api/game", json={"id": "ac:pc"}).json()
    assert "skipped_live" in actions_by(body)  # packets arrive: still never modified
    assert body["state"]["input"]["in_use"] is False


class _StubListener:
    received = 7
    capture = None

    def source_snapshot(self) -> list[dict[str, Any]]:
        return []

    def stop(self) -> None:
        return None


class _StubRouter:
    unrecognised = 3
    last_accepted_mono = None

    def finish(self) -> None:
        return None


def test_connect_hint_names_the_port_that_saw_the_packets(client: TestClient) -> None:
    """Unrecognised packets on the F1 port are not "GT7 telemetry" just because GT7 is selected: the hint names the
    port's own decoder, and where the selected game sends instead."""
    from pitwall.core.runtime import _Input

    rt: Runtime = client.app.state.runtime  # type: ignore[attr-defined]
    port = rt.integration_configs()["f1"].port
    rt.inputs[port] = _Input(port, ("f1",), _StubListener(), _StubRouter())  # type: ignore[arg-type]
    try:
        rt.live.unrecognised = 3
        client.put("/api/game", json={"id": "ac:ps5", "ensure_input": False})
        hint = client.get("/api/connect").json()["telemetry"]["hint"]
        assert hint.startswith(f"Packets arrived on UDP {port} that aren't F1 25 telemetry")
        assert "Assetto Corsa doesn't send to this port: Pitwall registers with the game (UDP 9996)" in hint
        client.put("/api/game", json={"id": "f1_25:ps5", "ensure_input": False})
        hint = client.get("/api/connect").json()["telemetry"]["hint"]
        assert "aren't F1 25 telemetry" in hint and "doesn't send to this port" not in hint
    finally:
        del rt.inputs[port]
