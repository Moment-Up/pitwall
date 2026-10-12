"""F2 support: the F2 car format of the setup catalogue (ranges from F2 evidence only, cited setups with credits), the
session setup page for F2 cars, and the physics heavy-stop warning per car class family."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.analysis.brake_prior import (
    CAVEAT,
    CAVEAT_F2,
    F2_ENVELOPE,
    ONSET_EVIDENCE,
    ONSET_EVIDENCE_F2,
    BrakeEnvelope,
    PriorRefresher,
    build_brake_prior,
    default_envelope,
    family_prior,
)
from pitwall.api.routes_carsetup import router
from pitwall.carsetup.catalog import FORMAT_FAMILY, load_catalog
from pitwall.carsetup.context import guess_car_format, session_context
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


# ---------------------------------------------------------------------------------------------- catalogue
def test_f2_format_ranges_come_from_f2_evidence() -> None:
    cat = load_catalog()
    f2, f1 = cat.formats["f2"], cat.formats["f1_2025"]
    assert f2.label == "F2 cars (2024 and 2025 seasons)" and f2.latest_handling_patch is None
    assert f2.tracks == (0, 3, 5, 11, 29)  # Melbourne, Sakhir, Monaco, Monza, Jeddah: tracks with cited setups
    assert set(f2.ranges) == set(f1.ranges)  # the same items as the F1 car...
    assert (f2.ranges["brake_bias"].max, f1.ranges["brake_bias"].max) == (69, 60)  # ...but its own ranges
    assert (f2.ranges["rear_suspension"].max, f1.ranges["rear_suspension"].max) == (26, 41)
    assert f2.ranges["rear_suspension"].max_confirmed and not f2.ranges["brake_bias"].max_confirmed
    steps = {"front_wing": 1, "diff_on_throttle": 5, "front_camber": 0.1, "front_toe": 0.01, "tyre_pressure_fl": 0.1}
    for k, step in steps.items():
        assert f2.ranges[k].step == step, k
    for k, r in f2.ranges.items():
        assert r.note, k  # every F2 range says where its ends come from
        if not (r.min_confirmed and r.max_confirmed):
            assert "f2_ps5" in r.note, k


def test_every_f2_setup_is_credited_and_none_is_a_preset_copy_or_an_email() -> None:
    cat = load_catalog()
    f2 = [s for s in cat.source_setups.values() if s.car_format == "f2"]
    assert len(f2) == 30
    for s in f2:
        assert s.source == "f1laps" and s.url.startswith("https://www.f1laps.com/f1-25/setups/") and s.author
        assert s.published and s.conditions == "dry" and not EMAIL.match(s.author), s.id
        assert s.notes and "F2" in s.notes and s.style is None, s.id
    per = Counter((s.track_id, s.session) for s in f2)
    assert set(per.values()) == {3} and len(per) == 10  # 3 per track and session
    for (track, session), _n in per.items():
        authors = [s.author for s in f2 if (s.track_id, s.session) == (track, session)]
        assert len(set(authors)) == 3  # one per author
    values = Counter((s.track_id, json.dumps(dict(s.values), sort_keys=True)) for s in f2)
    assert max(values.values()) < 5  # an exact copy of a preset (the same values from 5 or more authors) is left out


def test_f2_recommendations_are_built_from_f2_setups_only() -> None:
    cat = load_catalog()
    recs = [r for r in cat.recommendations.values() if r.car_format == "f2"]
    assert len(recs) == 10 and {r.style for r in recs} == {"balanced"}  # the stable rule cites F1 guides only
    for r in recs:
        assert all(cat.source_setups[c].car_format == "f2" for c in r.candidates)
        assert not any("handling patch" in n for n in r.notes)


# ---------------------------------------------------------------------------------------------- context
@pytest.mark.parametrize(
    ("formula", "car", "fmt", "expected", "reason"),
    [
        ("F2", "f1:team:158", 2025, "f2", "2024 season car"),
        (None, "f1:team:160", 2025, "f2", "2024 season car"),
        ("F2", "f1:team:214", 2025, "f2", "2025 season car"),
        ("F2", "f1:team:470", 2026, "f2", "2025 season car"),
        (None, "f1:team:214", 2025, None, "Pitwall can't tell which F2 car this is, so it shows no setups."),
        ("F2", "f1:team:494", 2026, None, "No setups for the 2026 F2 cars in Pitwall yet."),
        ("F2", None, 2025, None, "Pitwall can't tell which F2 car this is, so it shows no setups."),
        ("F1 Modern", "f1:team:8", 2025, "f1_2025", "2025 team id 8"),
        ("F1 26", "f1:team:480", 2026, "f1_2026", "formula F1 26"),
    ],
)
def test_f2_car_formats(formula: str | None, car: str | None, fmt: int, expected: str | None, reason: str) -> None:
    g = guess_car_format(fmt, formula, car)
    assert g.car_format == expected and reason in g.reason


def _row(**kw: Any) -> dict[str, Any]:
    row = {
        "game": "f1_25",
        "track_id": "f1:3",
        "track_name": "Sakhir (Bahrain)",
        "session_type": "race",
        "car_id": "f1:team:158",
        "weather": {"condition": "clear"},
        "info": {"formula": "F2", "packet_format": 2025},
    }
    return {**row, **kw}


def test_session_context_never_asks_an_f2_car_for_a_format() -> None:
    ctx = session_context(_row())
    assert ctx.car_format == "f2" and ctx.family == "f2" and not ctx.asks_car_format
    assert ctx.to_dict()["car_class"]["id"] == "f2"
    unknown = session_context(_row(car_id="f1:team:214", info={"packet_format": 2025}))
    assert unknown.car_format is None and not unknown.asks_car_format
    generic = session_context(_row(car_id="f1:team:41", info={"formula": "F1 World", "packet_format": 2025}))
    assert generic.car_format is None and generic.asks_car_format


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, DbWriter]]:
    db = Database(tmp_path / "x.sqlite3")
    writer = DbWriter(db)
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(db=db, writer=writer)
    with TestClient(app) as c:
        yield c, writer
    writer.close()


def _add(writer: DbWriter, sid: str, row: dict[str, Any]) -> None:
    def write(c: Any) -> None:
        repo.insert_session(c, sid, row["game"], "udp:20777", False, None, None)
        c.execute(
            "UPDATE sessions SET track_id=?, track_name=?, session_type=?, session_type_raw='Race 2', car_id=?, "
            "weather=?, info=? WHERE id=?",
            (
                row["track_id"],
                row["track_name"],
                row["session_type"],
                row["car_id"],
                json.dumps(row["weather"]),
                json.dumps(row["info"]),
                sid,
            ),
        )

    writer.call(write)


def test_catalog_serves_the_f2_format(client: tuple[TestClient, DbWriter]) -> None:
    c, _w = client
    f2 = next(f for f in c.get("/api/carsetup/catalog").json()["formats"] if f["id"] == "f2")
    assert f2["latest_handling_patch"] is None and [t["id"] for t in f2["tracks"]] == [0, 3, 5, 11, 29]
    assert f2["ranges"]["brake_bias"]["max"] == 69 and f2["ranges"]["brake_bias"]["max_confirmed"] is False


def test_session_setup_page_for_f2(client: tuple[TestClient, DbWriter]) -> None:
    c, w = client
    _add(w, "sakhir", _row())
    body = c.get("/api/carsetup/sessions/sakhir").json()
    assert body["needs"] == [] and body["context"]["car_format"] == "f2" and body["chosen"]["car_format"] == "f2"
    assert body["recommendation"]["car_format"] == "f2" and body["session"]["car_label"] == "F2 · Art GP '24"
    assert body["session"]["session_label"] == "Feature race"
    for ref in body["recommendation"]["setups"].values():  # credits on every cited setup
        assert ref["author"] and ref["url"] and ref["source"] == "f1laps" and ref["published"]
    # an F1 format for an F2 car is refused (422), and the reverse
    assert c.get("/api/carsetup/sessions/sakhir", params={"car_format": "f1_2025"}).status_code == 422
    _add(w, "mclaren", _row(car_id="f1:team:8", info={"formula": "F1 Modern", "packet_format": 2025}))
    assert c.get("/api/carsetup/sessions/mclaren", params={"car_format": "f2"}).status_code == 422
    # no F2 setups at the track: said plainly, the driver's own setup cards still show
    _add(w, "silverstone", _row(track_id="f1:7", track_name="Silverstone"))
    s = c.get("/api/carsetup/sessions/silverstone").json()
    assert s["unavailable"] == {"reason": "No F2 setups for this track in Pitwall yet.", "alternatives": []}
    assert s["needs"] == [] and s["context"]["car_format"] == "f2"
    # an F2 car Pitwall cannot place: never asked to choose an F1 format
    _add(w, "unknown", _row(car_id="f1:team:214", info={"packet_format": 2025}))
    u = c.get("/api/carsetup/sessions/unknown").json()
    assert u["needs"] == [] and u["unavailable"]["reason"].startswith("Pitwall can't tell which F2 car")
    assert u["unavailable"]["alternatives"] == []
    # a generic F1 car is asked, and offered F1 formats only
    _add(w, "generic", _row(car_id="f1:team:41", info={"formula": "F1 World", "packet_format": 2025}))
    g = c.get("/api/carsetup/sessions/generic").json()
    assert g["needs"] == ["car_format"]
    assert {FORMAT_FAMILY[a["car_format"]] for a in g["unavailable"]["alternatives"]} == {"f1"}


def test_f2_experiment_uses_f2_ranges(tmp_path: Path) -> None:
    from pitwall.carsetup import experiments as exps

    db = Database(tmp_path / "x.sqlite3")
    w = DbWriter(db)
    try:
        _add(w, "s", _row())
        cat = load_catalog()
        e = exps.propose(db, w, cat, before_session_id="s", parameter="brake_bias", to_value=65)  # beyond F1's 60
        assert e["parameter"] == "brake_bias" and e["to_value"] == 65 and e["status"] == "proposed"
        with pytest.raises(exps.ExperimentError):
            exps.propose(db, w, cat, before_session_id="s", parameter="rear_suspension", to_value=30)  # F2 max 26
        with pytest.raises(exps.ExperimentError):
            exps.propose(db, w, cat, before_session_id="s", parameter="brake_bias", to_value=55, car_format="f1_2025")
    finally:
        w.close()


# ---------------------------------------------------------------------------------------------- physics prior
def test_f2_braking_curve_is_plausible_and_measured() -> None:
    assert default_envelope("f2") is F2_ENVELOPE and default_envelope("f1") is None and default_envelope(None) is None
    BrakeEnvelope(F2_ENVELOPE.brake_base, F2_ENVELOPE.brake_aero, "check")  # passes the plausibility limits
    assert 2.0 < F2_ENVELOPE.decel_g(100.0) < F2_ENVELOPE.decel_g(300.0) < 3.5  # brakes less than the F1 model
    assert ONSET_EVIDENCE_F2["in_sample"] is True and ONSET_EVIDENCE_F2["outside_window"] == 0
    assert family_prior("f1").evidence is ONSET_EVIDENCE and not family_prior("other").enabled


def test_prior_per_family() -> None:
    f1 = build_brake_prior("f1_25", "f1:3", 5408.0, family="f1")
    f2 = build_brake_prior("f1_25", "f1:3", 5408.0, family="f2")
    assert f1.envelope_source == "default" and f2.envelope_source == "F2 default"
    p1, p2 = f1.to_payload(), f2.to_payload()
    assert (p1["car_family"], p2["car_family"]) == ("f1", "f2")
    assert p1["caveat"] == CAVEAT and p2["caveat"] == CAVEAT_F2 and "38 m" in CAVEAT_F2
    assert all(w["onset_error_p90_m"] == 38.0 for w in p2["windows"]) and p2["windows"]
    with pytest.raises(ValueError):
        build_brake_prior("f1_25", "f1:3", 5408.0, family="other")


def test_refresher_rebuilds_on_a_family_change_and_never_carries_a_fit_over() -> None:
    r = PriorRefresher()
    changed, f1 = r.refresh("f1_25", "f1:3", 5408.0, None, "f1")
    assert changed and f1 is not None and f1.envelope_source == "default"
    field = BrakeEnvelope(23.6, 0.00228, "AI field")
    changed, fit = r.refresh("f1_25", "f1:3", 5408.0, field, "f1")
    assert changed and fit is not None and fit.envelope_source == "AI field"
    changed, f2 = r.refresh("f1_25", "f1:3", 5408.0, None, "f2")  # an F2 session next: the F1 fit does not carry
    assert changed and f2 is not None and f2.envelope_source == "F2 default" and f2.car_family == "f2"
    assert r.refresh("f1_25", "f1:3", 5408.0, None, "f2") == (False, f2)
    changed, own = r.refresh("f1_25", "f1:3", 5408.0, field, "f2")  # the session's own AI fit replaces the default
    assert changed and own is not None and own.envelope_source == "AI field"
    assert r.refresh("f1_25", "f1:3", 5408.0, None, "other") == (True, None)  # classic / Beta: no warning
    assert r.refresh("f1_25", "f1:3", 5408.0, field, "other") == (False, None)


def test_knowledge_carries_the_family_caveat() -> None:
    from pitwall.core.runtime import knowledge_feeds
    from pitwall.core.track_knowledge import TrackKnowledgeResolver
    from pitwall.model.telemetry import Game, SessionInfo

    got: list[Any] = []
    resolver = TrackKnowledgeResolver(got.append)
    _on_snapshot, on_session = knowledge_feeds(resolver)
    on_session(
        SessionInfo(
            game=Game.F1_25,
            track_id="f1:3",
            track_length_m=5408.0,
            formula="F2",
            car_id="f1:team:158",
            extra={"packet_format": 2025},
        )
    )
    k = got[-1]
    assert k is not None and k.layers["L1c"]["car_family"] == "f2" and k.layers["L1c"]["caveat"] == CAVEAT_F2


def test_live_snapshot_names_the_class(tmp_path: Path) -> None:
    from pitwall.core.live import LiveState
    from pitwall.model.telemetry import Game, SessionInfo, SessionType

    live = LiveState()
    live.reset_session("s", "udp:20777", False, "f1_25")
    live.on_session(
        SessionInfo(
            game=Game.F1_25,
            track_id="f1:0",
            car_id="f1:team:214",
            car_name="Unknown team (id 214)",
            formula="F2",
            session_type=SessionType.RACE,
            session_type_raw="Race",
            extra={"packet_format": 2025},
        )
    )
    s = live.snapshot()["session"]
    assert s["car_label"] == "F2 · Hitech '25" and s["session_label"] == "Sprint race"
    assert s["car_class"]["id"] == "f2" and s["car_class"]["has_ers"] is False
    assert s["car_name"] == "Unknown team (id 214)"  # unchanged: the spec's neutral fallback


def test_sessions_api_rows_carry_the_class(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.sqlite3")
    with closing(db.connect()) as c:
        repo.insert_session(c, "s", "f1_25", "udp:20777", False, None, None)
        c.execute(
            "UPDATE sessions SET car_id='f1:team:158', car_name='Art GP ''24', session_type_raw='Race 2', "
            'info=\'{"formula": "F2", "packet_format": 2025}\' WHERE id=\'s\''
        )
        c.commit()
        from pitwall import carclass

        row = repo.get_session(c, "s")
        assert row is not None
        f = carclass.session_fields(row)
        assert f["car_label"] == "F2 · Art GP '24" and f["session_label"] == "Feature race"
