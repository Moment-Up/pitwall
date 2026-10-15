"""Family leaderboard API (``api/routes_leaderboard.py``): the board by key and by fields, the record index, the
lap card, and every refusal (404, 409, 422). Local only: nothing is sent anywhere."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall import __version__
from pitwall.api.routes_leaderboard import router
from pitwall.storage.db import Database, DbWriter
from tests.unit.leaderboard_data import AUSTRIA_KEY, DAY, T0, add_driver, add_lap, add_session


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, dict[str, Any]]]:
    db = Database(tmp_path / "lb.sqlite3")
    writer = DbWriter(db)
    capture = tmp_path / "austria.pwcap"
    capture.write_bytes(b"pwcap test bytes")

    def job(c: sqlite3.Connection) -> dict[str, Any]:
        sam, jo = add_driver(c, "Sam"), add_driver(c, "Jo")
        add_session(c, "s1", sam, capture_path=str(capture))
        best = add_lap(c, "s1", 1, 70_549, created=T0 + 100, sectors=(16_900, 31_149, 22_500))
        add_session(c, "j1", jo, started=T0 + DAY)
        add_lap(c, "j1", 1, 73_616, created=T0 + DAY + 100)
        untimed = add_lap(c, "j1", 2, None, created=T0 + DAY + 200)
        add_session(c, "syn", jo, synthetic=True, track="synthetic:demo", started=T0 + 2 * DAY)
        syn = add_lap(c, "syn", 1, 60_000, created=T0 + 2 * DAY)
        add_session(c, "rep", jo, source="replay:x.pwcap", started=T0 + 2 * DAY)
        rep = add_lap(c, "rep", 1, 60_000, created=T0 + 2 * DAY)
        return {"best": best, "untimed": untimed, "syn": syn, "rep": rep, "capture": capture}

    ids = writer.call(job)
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(db=db, writer=writer)
    with TestClient(app) as client:
        yield client, ids
    writer.close()


def test_board_by_key_and_by_fields(api: tuple[TestClient, dict[str, Any]]) -> None:
    client, _ids = api
    by_key = client.get("/api/leaderboard", params={"key": AUSTRIA_KEY, "token": "x"})  # the auth token is ignored
    assert by_key.status_code == 200
    b = by_key.json()
    assert b["key"] == AUSTRIA_KEY and [r["driver_name"] for r in b["rows"]] == ["Sam", "Jo"]
    assert b["rows"][1]["gap_text"] == "3.067 s behind" and b["ea_rival"] is None
    assert b["real_f1"]["label"] == "Real F1 pole 2025 · Lando Norris" and b["real_f1_note"] is None
    by_fields = client.get(
        "/api/leaderboard",
        params={
            "game": "f1_25",
            "track_id": "f1:17",
            "length_m": 4318,
            "car_id": "f1:team:7",
            "car_class": "f1",
            "equal_performance": "0",
            "category": "race",
            "conditions": "dry",
            "assists": "b2.a1.t2.g3.l2",
        },
    ).json()
    assert by_fields["key"] == AUSTRIA_KEY and by_fields["matched"] == 1
    track_only = client.get("/api/leaderboard", params={"game": "f1_25", "track_id": "f1:17"}).json()
    assert track_only["key"] == AUSTRIA_KEY
    nothing = client.get("/api/leaderboard", params={"game": "f1_25", "track_id": "f1:17", "conditions": "wet"}).json()
    assert nothing["key"] is None and nothing["rows"] == [] and nothing["matched"] == 0
    unknown_bucket = client.get("/api/leaderboard", params={"game": "f1_25", "track_id": "f1:17", "car_id": "?"})
    assert unknown_bucket.json()["matched"] == 0  # "?" asks for the unknown-car board, never "any car"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"game": "f1_25"},
        {"key": AUSTRIA_KEY, "game": "f1_25"},
        {"key": "f1_25~f1:17"},
        {"key": AUSTRIA_KEY.replace("race", "sprint")},
        {"game": "f1_25", "track_id": "f1:17", "category": "sprint"},
        {"game": "f1_25", "track_id": "f1:17", "assists": "a1.t0"},
        {"game": "gt7", "track_id": "x", "assists": "b2"},
        {"game": "f1_25", "track_id": "f1:17", "length_m": -5},
    ],
)
def test_bad_queries_are_422(api: tuple[TestClient, dict[str, Any]], params: dict[str, Any]) -> None:
    client, _ids = api
    assert client.get("/api/leaderboard", params=params).status_code == 422


def test_records_index(api: tuple[TestClient, dict[str, Any]]) -> None:
    client, _ids = api
    idx = client.get("/api/records").json()
    assert idx["count"] == 1
    (row,) = idx["boards"]
    assert row["key"] == AUSTRIA_KEY and row["record"]["driver_name"] == "Sam" and row["record"]["lap_ms"] == 70_549
    assert row["drivers"] == 2 and row["labels"]["title"] == "Austria · Haas · Race · Dry"
    assert row["vs"]["real_f1"]["band"] is None and row["vs"]["real_f1"]["gap_pct"] == 10.28  # +10.28 % off the pole
    assert client.get("/api/records", params={"game": "gt7"}).json() == {"boards": [], "count": 0}
    assert client.get("/api/records", params={"driver_id": 99}).json()["count"] == 0


def test_lap_card(api: tuple[TestClient, dict[str, Any]]) -> None:
    client, ids = api
    card = client.get(f"/api/leaderboard/lapcard/{ids['best']}").json()
    assert card["format"] == "pitwall.lapcard" and card["version"] == 1
    assert card["board"]["key"] == AUSTRIA_KEY and card["board"]["category"] == "race"
    assert card["lap_ms"] == 70_549 and card["sectors_ms"] == [16_900, 31_149, 22_500]
    assert card["date"] == "2026-10-10"  # the day only, never the time of day
    assert card["game"] == {"id": "f1_25", "version": "1.26", "platform": "ps5", "packet_format": 2025}
    assert card["pitwall_version"] == __version__
    assert card["assists"] == {"braking": 2, "abs": 1, "tc": 2, "gearbox": 3, "racing_line": 2}
    assert card["evidence"]["counts"] is True and card["evidence"]["reasons"] == []
    assert card["evidence"]["track_limits_checked"] is True and card["evidence"]["valid"] is True
    assert card["capture_sha256"] is None  # only when asked for
    assert card["online_name"] == ""  # never the household name or a PSN id
    assert "Sam" not in str(card) and "driver" not in str(card).lower()
    hashed = client.get(f"/api/leaderboard/lapcard/{ids['best']}", params={"capture_hash": True}).json()
    assert hashed["capture_sha256"] == hashlib.sha256(b"pwcap test bytes").hexdigest()


def test_lap_cards_of_laps_that_never_count(api: tuple[TestClient, dict[str, Any]]) -> None:
    client, ids = api
    syn = client.get(f"/api/leaderboard/lapcard/{ids['syn']}").json()
    assert syn["evidence"]["counts"] is False and syn["evidence"]["synthetic"] is True
    assert "synthetic data, not a game" in syn["evidence"]["reasons"]
    assert "the track is not known" in syn["evidence"]["reasons"]
    assert syn["board"] is None  # a synthetic track has no board
    rep = client.get(f"/api/leaderboard/lapcard/{ids['rep']}").json()
    assert rep["evidence"]["replay"] is True and rep["evidence"]["counts"] is False
    assert client.get(f"/api/leaderboard/lapcard/{ids['untimed']}").status_code == 409
    assert client.get("/api/leaderboard/lapcard/999999").status_code == 404
