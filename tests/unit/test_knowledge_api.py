"""``GET /api/technique/knowledge``: the whole technique graph, validated, as JSON; 503 with the problems listed when
the graph did not load (the app itself starts and runs without it). The app runs without UDP, LLM or voice."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pitwall.config import Settings
from pitwall.knowledge import graph as kg
from pitwall.knowledge.graph import PHASE_IDS, TIERS, load_graph

NODE_LISTS = ("phases", "conditions", "techniques", "signals", "faults", "causes", "advice", "constraints", "sources")


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
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
        yield c


def test_knowledge_returns_the_validated_graph(client: TestClient) -> None:
    r = client.get("/api/technique/knowledge")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"valid", "errors", "digest", "files", "tiers", "counts", "edges", *NODE_LISTS}
    assert body["valid"] is True and body["errors"] == [] and body["digest"]
    assert set(body["tiers"]) == set(TIERS)
    assert body["counts"] == {k: len(body[k]) for k in NODE_LISTS}
    assert [p["id"] for p in body["phases"]] == list(PHASE_IDS)
    for k in NODE_LISTS:
        for n in body[k]:
            assert {"type", "id", "name", "summary", "tier", "sources", "notes", "file"} <= set(n), (k, n)
            assert n["tier"] in TIERS and n["file"].endswith(".toml")
    lms = next(f for f in body["faults"] if f["id"] == "low_min_speed")
    assert lms["kind"] == "low_min_speed" and lms["status"] == "live" and lms["relative"] == "reference"
    assert lms["signals"] == ["min_speed_delta_kph"] and lms["causes"] == ["over_braking", "early_turn_in", "low_grip"]
    assert {"name": "pitwall.analysis.coaching.MIN_SPEED_KPH", "value": 4.0} in lms["thresholds"]
    advice = {a["id"]: a for a in body["advice"]}
    assert advice["low_min_speed_describe"]["for"] == "low_min_speed"
    assert advice["over_braking_explain"]["radio"] is None  # review-only
    signal = next(s for s in body["signals"] if s["id"] == "min_speed_delta_kph")
    assert signal["code"] == "CornerDelta.min_speed_delta_kph" and signal["channels"] == ["speed", "lap_distance"]
    edge = next(
        e for e in body["edges"] if (e["from"], e["to"], e["rel"]) == ("low_min_speed", "over_braking", "caused_by")
    )
    assert edge["tier"] == "brief" and edge["sources"] == ["ed_corner_brief"]  # Ed's brief makes that claim
    assert body == load_graph().to_payload()


@pytest.fixture
def broken_graph(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """A graph with a broken reference, loaded as the app loads it (not strict)."""
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    (graph_dir / "faults.toml").write_text(
        '[[fault]]\nid = "x"\nname = "X"\nsummary = "X."\nphase = "nowhere"\nstatus = "planned"\n'
        'relative = "reference"\ntier = "brief"\nsources = ["ed_corner_brief"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(kg, "GRAPH_DIR", graph_dir)
    kg.set_strict(False)
    try:
        yield
    finally:
        monkeypatch.undo()
        kg.set_strict(True)


@pytest.mark.usefixtures("broken_graph")
def test_a_graph_that_did_not_load_is_503_and_the_app_still_runs(client: TestClient) -> None:
    r = client.get("/api/technique/knowledge")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "did not load" in detail["message"]
    assert any("unknown id 'nowhere'" in e for e in detail["errors"])
    assert client.get("/api/health").status_code == 200
