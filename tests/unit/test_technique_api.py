"""``/api/technique``: errors, the JSON contract's keys, blocked lap pairs and non-F1 sessions.

SYNTHETIC sessions (F1 technique-demo, an F1 session without a clean lap, and the GT7 coaching demo) replayed into
a scratch data folder; the app runs without UDP, LLM or voice.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pitwall.api.app import create_app
from pitwall.config import Settings
from pitwall.sim.f1_stream import F1Scenario
from pitwall.sim.gt7_stream import write_gt7_capture
from pitwall.sim.scenarios import technique_demo
from pitwall.storage import repo
from pitwall.storage.db import Database
from tests.technique_fixtures import f1_writer, replay_into

pytestmark = pytest.mark.synthetic

SESSION_KEYS = {
    "session_id",
    "game",
    "synthetic",
    "source",
    "ref_lap_id",
    "ref_lap_number",
    "ref_session_id",
    "available",
    "pedals",
    "assists",
    "laps",
    "corners",
    "symptoms",
    "setup",
    "thresholds",
}
CORNER_KEYS = {
    "corner",
    "label",
    "name",
    "direction",
    "apex_m",
    "speed_class",
    "ref_min_speed_kph",
    "points",
    "ref",
    "laps",
    "line",
    "balance",
    "habits",
}
LAP_CORNER_KEYS = {"lap_id", "lap_number", "clean", "incident", "time_delta_s", "line", "inputs", "notes", "balance"}
INPUT_KEYS = {
    "braked",
    "brake_start_m",
    "brake_peak",
    "time_to_peak_s",
    "peak_hold_s",
    "release_s",
    "release_shape",
    "brake_at_turn_in",
    "brake_at_apex",
    "trail_overlap_s",
    "coast_s",
    "coast_m",
    "pickup_m",
    "pickup_vs_apex_m",
    "full_throttle_m",
    "throttle_ramp_s",
    "throttle_lifts",
    "lockup",
    "wheelspin",
}
COMPARE_KEYS = {
    "ref_lap_id",
    "lap_id",
    "ref_lap_number",
    "lap_number",
    "synthetic",
    "compatible",
    "blocking",
    "warnings",
    "lines",
    "markers",
    "corners",
    "available",
    "pedals",
    "assists",
}


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    root = tmp_path_factory.mktemp("technique_api")
    no_clean = F1Scenario(laps=1, invalid_laps=frozenset({1}))
    sids = replay_into(
        root,
        [
            ("technique-demo", f1_writer(technique_demo(), "technique-demo")),
            ("no-model", f1_writer(no_clean, "no-model")),
            ("gt7-demo", lambda p: write_gt7_capture(p)),
        ],
    )
    return root, sids


@pytest.fixture(scope="module")
def client(data: tuple[Path, dict[str, str]]) -> Iterator[TestClient]:
    root, _ = data
    app = create_app(Settings(data_dir=root, llm_enabled=False, voice_enabled=False), start_udp=False)
    with TestClient(app, client=("127.0.0.1", 40000)) as c:
        yield c


def _laps(root: Path, sid: str) -> list[dict[str, Any]]:
    with Database(root / "pitwall.sqlite3").read() as c:
        return repo.list_laps(c, sid)


def _no_nan(x: Any) -> None:
    if isinstance(x, float):
        assert math.isfinite(x)
    elif isinstance(x, dict):
        for v in x.values():
            _no_nan(v)
    elif isinstance(x, list):
        for v in x:
            _no_nan(v)


def test_errors(client: TestClient, data: tuple[Path, dict[str, str]]) -> None:
    _root, sids = data
    assert client.get("/api/technique/sessions/nope").status_code == 404
    assert client.get("/api/technique/sessions/nope/balance").status_code == 404
    r = client.get(f"/api/technique/sessions/{sids['no-model']}")
    assert r.status_code == 409 and "no track model" in r.json()["detail"]
    assert client.get("/api/technique/compare?ref=999999&lap=999998").status_code == 404
    bad = client.get(f"/api/technique/sessions/{sids['technique-demo']}?car_format=f1_1999")
    assert bad.status_code == 422


def test_session_payload_follows_the_contract(client: TestClient, data: tuple[Path, dict[str, str]]) -> None:
    _, sids = data
    body = client.get(f"/api/technique/sessions/{sids['technique-demo']}").json()
    assert set(body) >= SESSION_KEYS and body["synthetic"] is True and body["game"] == "f1_25"
    assert set(body["available"]) == {"line", "inputs", "slip", "balance", "setup"}
    assert all(set(v) == {"ok", "reason", "note"} for v in body["available"].values())
    assert set(body["pedals"]) == {
        "pedals",
        "label",
        "brake_sensor",
        "peak_tol",
        "time_tol_s",
        "changed_since_reference",
        "note",
    }
    assert body["pedals"]["pedals"] == "csl"  # the default rig profile (never saved): stock CSL pedals
    assert set(body["assists"]) == {"abs", "traction_control", "braking_assist", "notes"}
    c = body["corners"][0]
    assert set(c) >= CORNER_KEYS and set(c["points"]) == {"turn_in", "apex", "track_out"}
    assert set(c["ref"]) == {"inputs", "balance"} and set(c["ref"]["inputs"]) >= INPUT_KEYS
    assert set(c["balance"]) == {"entry", "mid", "exit"}
    lc = c["laps"][1]
    assert set(lc) >= LAP_CORNER_KEYS and set(lc["line"]) == {"turn_in", "apex", "track_out"}
    assert set(c["line"]) == {"inside_known", "points", "view"} and set(c["line"]["view"]) == {
        "lap_id",
        "lap_number",
        "ref_xz",
        "lap_xz",
    }
    sym = body["symptoms"][0]
    assert sym["id"] == "mid-understeer-car" and sym["verdict"] == "car"
    setup = body["setup"]
    assert set(setup) == {"car_format", "setup_known", "suggestions", "caveat", "note"}
    assert setup["suggestions"][0]["parameter"] == "front_arb"
    assert {t["key"] for t in body["thresholds"]} >= {"US_DIFF_DEG", "LINE_NOTABLE_M", "LOCKUP_SLIP"}
    _no_nan(body)
    balance = client.get(f"/api/technique/sessions/{sids['technique-demo']}/balance").json()
    assert set(balance) >= {"session_id", "symptoms", "setup", "available", "assists"}


def test_compare_payload_and_markers(client: TestClient, data: tuple[Path, dict[str, str]]) -> None:
    root, sids = data
    laps = _laps(root, sids["technique-demo"])
    ref, lap3 = laps[0]["id"], laps[2]["id"]
    body = client.get(f"/api/technique/compare?ref={ref}&lap={lap3}").json()
    assert set(body) >= COMPARE_KEYS and body["compatible"] is True and body["synthetic"] is True
    assert body["lines"]["step_m"] == 5 and len(body["lines"]["ref_xz"]) == len(body["lines"]["lap_xz"])
    assert body["markers"] and all(m["offset_m"] == pytest.approx(-2.0, abs=0.2) for m in body["markers"])
    assert "wider than your reference" in body["markers"][0]["text"]
    corner = next(c for c in body["corners"] if c["corner"] == body["markers"][0]["corner"])
    assert (
        corner["inside_known"]
        and corner["window"]
        and len(corner["window"]["d_m"]) == len(corner["window"]["offset_m"])
    )
    assert set(corner["offsets"]) == {"turn_in", "apex", "track_out"}
    _no_nan(body)


def test_a_blocked_pair_is_not_compared(client: TestClient, data: tuple[Path, dict[str, str]]) -> None:
    root, sids = data
    ref = _laps(root, sids["technique-demo"])[0]["id"]
    other = _laps(root, sids["no-model"])[0]["id"]  # another (synthetic) track: not comparable
    body = client.get(f"/api/technique/compare?ref={ref}&lap={other}").json()
    assert body["compatible"] is False and body["blocking"]
    assert body["lines"] is None and body["markers"] == [] and body["corners"] == []
    assert body["available"]["line"]["ok"] is False


def test_non_f1_sessions_have_no_setup_and_no_slip(client: TestClient, data: tuple[Path, dict[str, str]]) -> None:
    _, sids = data
    body = client.get(f"/api/technique/sessions/{sids['gt7-demo']}").json()
    assert body["game"] == "gt7" and body["setup"] is None
    assert body["available"]["slip"]["ok"] is False
    assert body["available"]["slip"]["reason"].startswith("This game does not send tyre slip to Pitwall yet")
    assert body["available"]["setup"]["reason"] == "Setup suggestions are for F1 25 only."
    assert body["symptoms"] == []
    for c in body["corners"]:
        for lc in c["laps"]:
            if lc["inputs"] is not None:
                assert lc["inputs"]["wheelspin"]["status"] == "no_data"
    assert any("GT7" in n for n in body["assists"]["notes"])
