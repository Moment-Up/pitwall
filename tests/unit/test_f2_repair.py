"""F2 support in storage and the lap pipeline: the one-off repair of the one-shot laps, track models per car class
family (borrowed until a family's own clean lap), driver bests per family, and references that never cross classes.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall.analysis.laps import CHANNELS, LapFlag, LapTrace
from pitwall.analysis.track import TrackModel
from pitwall.analysis.track_identity import track_model_payload
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

LENGTH = 1000.0
TRACK = "f1:3"


def _trace(n: int, ms: int | None, samples: int, *, final: bool | None = None, speed: float = 200.0) -> LapTrace:
    d = np.linspace(0.0, LENGTH - 1.0, samples) if samples > 1 else np.array([1.0])
    channels = {name: np.zeros(len(d)) for name in CHANNELS}
    channels["distance_m"] = d
    channels["session_time_s"] = np.linspace(0.0, (ms or 60_000) / 1000.0, len(d))
    channels["lap_time_ms"] = channels["session_time_s"] * 1000.0
    # one slow corner in the middle (a speed minimum the track model learns)
    channels["speed_kph"] = speed - 120.0 * np.exp(-(((d - 500.0) / 60.0) ** 2))
    channels["throttle"] = np.where(np.abs(d - 500.0) < 150.0, 0.0, 1.0)
    channels["brake"] = np.where((d > 380.0) & (d < 470.0), 1.0, 0.0)
    channels["pos_x_m"] = np.cos(d / LENGTH * 2 * np.pi) * 150.0
    channels["pos_z_m"] = np.sin(d / LENGTH * 2 * np.pi) * 150.0
    flags = set() if samples > 1 else {LapFlag.INCOMPLETE}
    return LapTrace(lap_number=n, channels=channels, lap_time_ms=ms, valid=True, flags=flags, meta={"final": final})


def _session(c: sqlite3.Connection, sid: str, formula: str | None, car: str, started: float, driver: int) -> None:
    repo.insert_session(c, sid, "f1_25", "udp:20777", False, None, None, driver_id=driver)
    info: dict[str, Any] = {"packet_format": 2025}
    if formula is not None:
        info["formula"] = formula
    c.execute(
        "UPDATE sessions SET track_id=?, track_name='Sakhir', track_length_m=?, car_id=?, car_name=?, info=?, "
        "started_unix=?, session_type='qualifying', session_type_raw='One-Shot Qualifying' WHERE id=?",
        (TRACK, LENGTH, car, "Art GP '24", json.dumps(info), started, sid),
    )


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    yield Database(tmp_path / "pitwall.sqlite3")


def _model(c: sqlite3.Connection, lap_ids: list[int], family: str | None = None) -> None:
    m = TrackModel(game="f1_25", track_id=TRACK, track_name="Sakhir", length_m=LENGTH, source_lap_ids=lap_ids)
    m.n_laps = len(lap_ids)
    m.car_family = family
    repo.save_track_model(c, m)


def test_repair_deletes_the_one_shot_duplicates_tags_models_and_rebuilds(db: Database) -> None:
    w = DbWriter(db)
    try:
        with closing(db.connect()) as c:
            d = repo.insert_driver(c, "Driver", {})
            _session(c, "osq", "F2", "f1:team:158", 100.0, d)  # one-shot qualifying: the real lap had a flashback
            real = repo.insert_lap(c, "osq", _trace(1, 116_133, 600), None)
            c.execute("UPDATE laps SET clean=0, flags='[\"flashback\"]' WHERE id=?", (real,))
            fake = repo.insert_lap(c, "osq", _trace(2, 116_133, 1, final=True), None)
            c.execute("UPDATE laps SET clean=1, flags='[]' WHERE id=?", (fake,))  # stored clean before the fix
            _session(c, "race", "F2", "f1:team:158", 200.0, d)
            race = [repo.insert_lap(c, "race", _trace(n, 108_000 + n, 600), None) for n in (1, 2, 3)]
            _session(c, "synth", "F1 Modern", "f1:team:8", 300.0, d)  # equal times, thousands of samples: kept
            synth = [repo.insert_lap(c, "synth", _trace(n, 90_000, 600, final=n == 2), None) for n in (1, 2)]
            _model(c, [fake])  # v1-v3 built from the fake lap (as on the owner's copy)
            _model(c, [fake, race[0]])
            _model(c, [race[1], fake, race[0]])
            c.commit()
            assert [r["id"] for r in repo.find_fake_final_laps(c)] == [fake]
        lp = LapProcessor(db, w)
        rec = lp.run_repairs()
        assert rec is not None and rec["status"] == "done"
        assert [(x["id"], x["lap_number"], x["lap_time_ms"], x["family"]) for x in rec["deleted"]] == [
            (fake, 2, 116_133, "f2")
        ]
        assert [s["version"] for s in rec["superseded"]] == [1, 2, 3]
        assert [(r["family"], r["version"]) for r in rec["rebuilt"]] == [("f2", 4)]
        assert lp.run_repairs() is None  # once
        with closing(db.connect()) as c:
            c.row_factory = sqlite3.Row
            assert repo.get_lap(c, fake, with_trace=False) is None
            assert all(repo.get_lap(c, i, with_trace=False) is not None for i in [real, *race, *synth])
            rows = {
                r["version"]: json.loads(r["model"])
                for r in c.execute("SELECT version, model FROM track_models WHERE track_id=?", (TRACK,))
            }
            assert [rows[v]["superseded"] for v in (1, 2, 3)] == [True, True, True]
            assert {rows[v]["car_family"] for v in (1, 2, 3, 4)} == {"f2"}
            assert not rows[4].get("superseded") and fake not in rows[4]["source_lap_ids"]
            assert set(rows[4]["source_lap_ids"]) == set(race)
            loaded = repo.load_track_model(c, "f1_25", TRACK, "f2")
            assert loaded is not None and loaded.version == 4
            # the one-shot session is left with no clean lap: correct, its only real lap had a flashback
            assert not any(lap["clean"] for lap in repo.list_laps(c, "osq"))
            meta = json.loads(repo.get_meta(c, repo.REPAIR_F2_V1_KEY) or "{}")
            assert meta["status"] == "done" and meta["deleted"][0]["id"] == fake
    finally:
        w.close()


def test_mixed_family_models_are_superseded_and_each_family_rebuilt(db: Database) -> None:
    w = DbWriter(db)
    try:
        with closing(db.connect()) as c:
            d = repo.insert_driver(c, "Driver", {})
            _session(c, "f2", "F2", "f1:team:158", 100.0, d)
            f2 = repo.insert_lap(c, "f2", _trace(1, 108_000, 600, speed=180.0), None)
            _session(c, "f1", "F1 Modern", "f1:team:8", 200.0, d)
            f1 = repo.insert_lap(c, "f1", _trace(1, 92_000, 600, speed=260.0), None)
            _model(c, [f2, f1])
            c.commit()
        rec = LapProcessor(db, w).run_repairs()
        assert rec is not None and rec["superseded"][0]["why"].startswith("built from laps of more than one")
        assert sorted(r["family"] for r in rec["rebuilt"]) == ["f1", "f2"]
        with closing(db.connect()) as c:
            m1, m2 = repo.load_track_model(c, "f1_25", TRACK, "f1"), repo.load_track_model(c, "f1_25", TRACK, "f2")
            assert m1 is not None and m2 is not None
            assert (m1.car_family, m1.source_lap_ids) == ("f1", [f1]) and (m2.car_family, m2.source_lap_ids) == (
                "f2",
                [f2],
            )
    finally:
        w.close()


def test_track_model_family_choice_and_borrowed_flag(db: Database) -> None:
    with closing(db.connect()) as c:
        _model(c, [1], "f2")  # v1: F2
        c.commit()
        m = repo.load_track_model(c, "f1_25", TRACK, "f1")
        assert m is not None and m.car_family == "f2" and repo.track_model_borrowed(m, "f1")
        p = track_model_payload(m, "f1")
        assert p["car_family"] == "f2" and p["car_family_match"] is False
        assert p["car_family_note"] == "Corners from F2 laps until your first clean F1 lap here."
        _model(c, [2], None)  # v2: a legacy model of unknown family beats another family's
        c.commit()
        m = repo.load_track_model(c, "f1_25", TRACK, "f1")
        assert m is not None and m.version == 2 and not repo.track_model_borrowed(m, "f1")
        assert track_model_payload(m, "f1")["car_family_match"] is None
        _model(c, [3], "f1")  # v3: the family's own
        _model(c, [4], "f2")  # v4: newer, but another family's
        c.commit()
        own = repo.load_track_model(c, "f1_25", TRACK, "f1")
        assert own is not None and own.version == 3 and track_model_payload(own, "f1")["car_family_match"] is True
        newest = repo.load_track_model(c, "f1_25", TRACK)  # no family: as before, the newest of any
        assert newest is not None and newest.version == 4
        assert track_model_payload(newest)["car_family_match"] is None  # non-F1 games / unknown: null
        c.execute("UPDATE track_models SET model=json_set(model, '$.superseded', json('true')) WHERE version=4")
        c.commit()
        assert repo.load_track_model(c, "f1_25", TRACK).version == 3  # type: ignore[union-attr]  # never superseded
        assert repo.load_track_model(c, "f1_25", TRACK, "f2").version == 1  # type: ignore[union-attr]


def test_clean_laps_and_driver_bests_per_family(db: Database) -> None:
    with closing(db.connect()) as c:
        d = repo.insert_driver(c, "Driver", {})
        _session(c, "f2", "F2", "f1:team:214", 100.0, d)
        f2 = repo.insert_lap(c, "f2", _trace(1, 108_000, 600), None)
        _session(c, "f1", "F1 Modern", "f1:team:8", 200.0, d)
        c.execute("UPDATE sessions SET car_name='McLaren' WHERE id='f1'")
        f1 = repo.insert_lap(c, "f1", _trace(1, 92_000, 600), None)
        c.commit()
        assert [r["id"] for r in repo.clean_laps_for(c, "f1_25", TRACK, None, family="f2")] == [f2]
        assert [r["id"] for r in repo.clean_laps_for(c, "f1_25", TRACK, None, family="f1")] == [f1]
        assert [r["id"] for r in repo.clean_laps_for(c, "f1_25", TRACK, None)] == [f1, f2]
        bests = repo.driver_stats(c)[d]["best_laps"]
        assert sorted((b["car_family"], b["lap_id"], b["car_label"]) for b in bests) == [
            ("f1", f1, "McLaren"),
            ("f2", f2, "F2 · Hitech '25"),
        ]


def test_f1_and_f2_laps_never_reference_each_other(db: Database) -> None:
    """References need the same car: an F2 lap is never an F1 lap's reference (and the reverse)."""
    w = DbWriter(db)
    try:
        with closing(db.connect()) as c:
            d = repo.insert_driver(c, "Driver", {})
            _session(c, "f1", "F1 Modern", "f1:team:8", 100.0, d)
            repo.insert_lap(c, "f1", _trace(1, 80_000, 600), None)  # a faster F1 lap at the same track
            _session(c, "f2", "F2", "f1:team:158", 200.0, d)
            first = repo.insert_lap(c, "f2", _trace(1, 108_000, 600), None)
            c.commit()
        lp = LapProcessor(db, w)
        ctx = {
            "game": "f1_25",
            "track_id": TRACK,
            "track_name": "Sakhir",
            "track_length_m": LENGTH,
            "car_id": "f1:team:158",
            "formula": "F2",
            "packet_format": 2025,
        }
        out = lp.process(LapJob("f2", _trace(2, 107_500, 600), ctx))
        comp = out["comparison"]
        assert comp is not None and comp["ref_lap_id"] == first  # its own F2 lap, never the faster F1 lap
        with closing(db.connect()) as c:
            m = repo.load_track_model(c, "f1_25", TRACK, "f2")
            assert m is not None and m.car_family == "f2"
            assert repo.load_track_model(c, "f1_25", TRACK, "f1") is not None  # borrowed until an F1 model exists
    finally:
        w.close()


def test_a_borrowed_model_is_replaced_by_the_familys_own_on_its_first_clean_lap(db: Database) -> None:
    w = DbWriter(db)
    try:
        with closing(db.connect()) as c:
            d = repo.insert_driver(c, "Driver", {})
            _session(c, "f2", "F2", "f1:team:158", 100.0, d)
            f2 = repo.insert_lap(c, "f2", _trace(1, 108_000, 600, speed=180.0), None)
            _model(c, [f2], "f2")
            m = repo.load_track_model(c, "f1_25", TRACK, "f2")
            assert m is not None
            c.execute("DELETE FROM track_models")
            repo.save_track_model(c, _built(m, f2))
            _session(c, "f1", "F1 Modern", "f1:team:8", 200.0, d)
            c.commit()
        lp = LapProcessor(db, w)
        ctx = {"game": "f1_25", "track_id": TRACK, "track_length_m": LENGTH, "car_id": "f1:team:8"}
        ctx |= {"formula": "F1 Modern", "packet_format": 2025, "track_name": "Sakhir"}
        lp.process(LapJob("f1", _trace(1, 92_000, 600, speed=260.0), ctx))
        with closing(db.connect()) as c:
            own = repo.load_track_model(c, "f1_25", TRACK, "f1")
            assert own is not None and own.car_family == "f1" and f2 not in own.source_lap_ids
    finally:
        w.close()


def _built(m: TrackModel, lap: int) -> TrackModel:
    """A real built model of the F2 lap (corners and all), standing in for what the live path would have stored."""
    from pitwall.analysis.distance import to_distance_domain
    from pitwall.analysis.track import build_track_model

    t = _trace(1, 108_000, 600, speed=180.0)
    return build_track_model(
        "f1_25", TRACK, "Sakhir", LENGTH, [to_distance_domain(t, LENGTH)], source_lap_ids=[lap], car_family="f2"
    )


def test_an_interrupted_repair_resumes_its_rebuild(db: Database) -> None:
    """Steps 1-2 committed, the service stopped before the rebuild: the next start rebuilds and finishes."""
    w = DbWriter(db)
    try:
        with closing(db.connect()) as c:
            d = repo.insert_driver(c, "Driver", {})
            _session(c, "osq", "F2", "f1:team:158", 100.0, d)
            fake = repo.insert_lap(c, "osq", _trace(2, 116_133, 1, final=True), None)
            repo.insert_lap(c, "osq", _trace(1, 116_133, 600), None)
            _session(c, "race", "F2", "f1:team:158", 200.0, d)
            race = repo.insert_lap(c, "race", _trace(1, 108_000, 600), None)
            _model(c, [fake, race])
            c.commit()
        w.call(repo.repair_f2_v1)  # the first start got this far
        with closing(db.connect()) as c:
            c.row_factory = sqlite3.Row
            rec = repo.repair_record(c)
            assert rec is not None and rec["status"] == "rebuilding" and len(rec["superseded"]) == 1
        done = LapProcessor(db, w).run_repairs()
        assert done is not None and done["status"] == "done" and [r["family"] for r in done["rebuilt"]] == ["f2"]
        assert [x["id"] for x in done["deleted"]] == [fake]  # the record keeps what the first run deleted
    finally:
        w.close()
