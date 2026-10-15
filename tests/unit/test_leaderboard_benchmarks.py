"""The two optional board rows wired into the family boards (``leaderboard.service``): the F1 25 Time Trial rival from
EA's leaderboard (packet 14, ``repo.latest_tt_rival``) and the real-F1 pole (F1DB, ``trackdata.real_f1``), with each
driver's gap and gold / silver / bronze band to them, on ``/api/leaderboard`` and ``/api/records``.

Real-F1 times come from the shipped benchmark file (F1DB v2026.17.0): Austria 2025 pole 1:03.971 (Norris), 2026 pole
1:06.113 (Russell). EA rival rows are built directly as ``TimeTrialInfo`` objects (no game data): spec-decoded only.
Household names are fictional."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.api.routes_leaderboard import router
from pitwall.leaderboard import keys as K
from pitwall.leaderboard import service as S
from pitwall.model.telemetry import Game, TimeTrialDataSet, TimeTrialInfo
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from pitwall.trackdata import real_f1 as R
from tests.unit.leaderboard_data import AUSTRIA_KEY, DAY, T0, add_driver, add_lap, add_session

AUSTRIA = K.decode(AUSTRIA_KEY)
POLE_2025 = 63_971  # Norris, Austrian GP 2025 (F1DB)
POLE_2026 = 66_113  # Russell, Austrian GP 2026 (F1DB)
TT_KEY = "f1_25~f1:17~4318~f1:team:8~f1~0~time_trial~dry~b2.a1.t2.g3.l2"  # Austria, McLaren, Time Trial
RIVAL_MS = 64_500


@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[Database, DbWriter]]:
    db = Database(tmp_path / "bench.sqlite3")
    writer = DbWriter(db)
    yield db, writer
    writer.close()


def rival_set(
    lap_ms: int = RIVAL_MS,
    *,
    team: int = 8,
    equal: bool | None = False,
    valid: bool | None = True,
    tc: bool | None = False,
    abs_on: bool | None = True,
) -> TimeTrialDataSet:
    return TimeTrialDataSet(
        car_index=1,
        team_id=team,
        car_id=f"f1:team:{team}",
        car_name="McLaren" if team == 8 else f"Team {team}",
        lap_time_ms=lap_ms,
        sector_times_ms=(16_000, 28_000, lap_ms - 44_000),
        traction_control=tc,
        gearbox_assist=False,
        anti_lock_brakes=abs_on,
        equal_car_performance=equal,
        custom_setup=False,
        valid=valid,
    )


def store_rival(c: sqlite3.Connection, sid: str, rival: TimeTrialDataSet | None, *, seen: float) -> None:
    info = TimeTrialInfo(
        game=Game.F1_25,
        t_recv_ns=1,
        session_time_s=1.0,
        session_uid="4242",
        packet_format=2025,
        player_session_best=None,
        personal_best=None,
        rival=rival,
        pb_car_index=None,
        rival_car_index=None if rival is None else 1,
    )
    repo.upsert_session_time_trial(c, sid, info)
    c.execute("UPDATE session_time_trial SET updated_unix=? WHERE session_id=?", (seen, sid))


def view(db: Database, key: str | K.BoardKey) -> dict[str, Any]:
    with db.read() as c:
        return S.board_by_key(c, K.decode(key) if isinstance(key, str) else key)


def driver_bands(b: dict[str, Any], kind: str) -> list[tuple[str, str | None]]:
    return [(r["driver_name"], r["vs"][kind]["band"]) for r in b["rows"]]


# ---------------------------------------------------------------------------------------------- real F1
def test_real_f1_row_and_bands_for_a_2025_car(store: tuple[Database, DbWriter]) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        for i, (name, ms) in enumerate((("Ana", 65_890), ("Ben", 67_000), ("Cy", 70_000), ("Dee", 70_549))):
            d = add_driver(c, name)
            add_session(c, f"s{i}", d, started=T0 + i * DAY)
            add_lap(c, f"s{i}", 1, ms, created=T0 + i * DAY + 60)

    writer.call(job)
    b = view(db, AUSTRIA_KEY)
    real = b["real_f1"]
    assert real["kind"] == "real_f1" and real["lap_ms"] == POLE_2025 and real["banded"] is True
    assert real["label"] == "Real F1 pole 2025 · Lando Norris" and real["time_text"] == "1:03.971"
    assert (real["what"], real["year"], real["season"], real["generation"]) == ("pole", 2025, 2025, "f1_2025")
    assert real["grand_prix"] == "Austrian Grand Prix" and real["date"] == "2025-06-28" and real["band_note"] is None
    assert real["caveat"] == R.caveat() and "F1 25 is not the real car" in real["caveat"]
    # the credit CC BY 4.0 asks for travels with the row
    src = real["source"]
    assert (src["name"], src["version"], src["licence"]) == ("F1DB", "v2026.17.0", "CC BY 4.0")
    assert src["licence_url"] == "https://creativecommons.org/licenses/by/4.0/" and "F1DB" in src["attribution"]
    assert real["race_fastest_lap"]["time_text"] == "1:07.924" and real["race_fastest_lap"]["year"] == 2025
    assert real["lap_record"]["time_text"] == "1:05.619" and real["lap_record"]["driver"] == "Carlos Sainz Jr."
    assert real["lap_record"]["label"] == "Fastest race lap on this layout (F1DB)"
    assert real["layout"] == {"f1db_layout_id": "spielberg-3", "layout_length_m": 4326, "game_length_m": 4323}
    assert b["real_f1_note"] is None and b["ea_rival"] is None  # a race board has no EA rival
    # gold within 3 % (or faster), silver within 5 %, bronze within 10 %, else no band
    assert driver_bands(b, "real_f1") == [("Ana", "gold"), ("Ben", "silver"), ("Cy", "bronze"), ("Dee", None)]
    assert b["real_f1_asks_generation"] is False and real["generation_chosen"] is False
    with db.read() as c:  # a choice never overrides the generation the game told: a Haas is a 2025 car
        assert S.board_by_key(c, AUSTRIA, car_generation="f1_2026")["real_f1"]["lap_ms"] == POLE_2025
    dee = b["rows"][3]["vs"]["real_f1"]
    assert dee == {"gap_ms": 6578, "gap_pct": 10.28, "gap_text": "6.578 s slower", "band": None}
    # the record index carries the record's gap and band too, and so do the pickers' rows
    with db.read() as c:
        (row,) = S.records_index(c)["boards"]
    assert row["vs"] == {
        "real_f1": {
            "lap_ms": POLE_2025,
            "label": "Real F1 pole 2025 · Lando Norris",
            "gap_ms": 65_890 - POLE_2025,
            "gap_pct": 3.0,
            "gap_text": "1.919 s slower",
            "band": "gold",
        }
    }
    assert b["boards_here"][0]["vs"] == row["vs"]


def test_a_2026_car_is_measured_against_the_2026_pole(store: tuple[Database, DbWriter]) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        d = add_driver(c, "Sam")
        add_session(c, "s26", d, car="f1:team:483", car_name="Haas '26", formula="F1 26")
        add_lap(c, "s26", 1, 68_000, created=T0 + 60)

    writer.call(job)
    with db.read() as c:
        (row,) = S.records_index(c)["boards"]
    b = view(db, row["key"])
    assert b["real_f1"]["lap_ms"] == POLE_2026 and b["real_f1"]["generation"] == "f1_2026"
    assert b["real_f1"]["label"] == "Real F1 pole 2026 · George Russell"
    assert driver_bands(b, "real_f1") == [("Sam", "gold")]  # +2.85 %


def test_no_real_f1_row_for_an_unknown_or_mixed_generation(store: tuple[Database, DbWriter]) -> None:
    """The generic car (team 41) in UDP format 2025 is a 2025 or a 2026 car: no real season to compare with."""
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        sam = add_driver(c, "Sam")
        add_driver(c, "Jo")
        add_session(c, "g", sam, car="f1:team:41", car_name="F1 Generic", formula="F1 World")
        add_lap(c, "g", 1, 68_000, created=T0 + 60)

    writer.call(job)
    with db.read() as c:
        (row,) = S.records_index(c)["boards"]
    b = view(db, row["key"])
    assert b["real_f1"] is None and b["real_f1_note"] == S.REAL_F1_NO_GENERATION
    assert b["real_f1_asks_generation"] is True  # a screen may ask the driver (``car_generation``)
    assert b["rows"][0]["vs"] == {} and row["vs"] == {}
    # the driver's answer fills it in, flagged as chosen, on the board, its pickers and the index
    with db.read() as c:
        chosen = S.board_by_key(c, K.decode(row["key"]), car_generation="f1_2026")
        (idx_row,) = S.records_index(c, car_generation="f1_2025")["boards"]
    real = chosen["real_f1"]
    assert real["lap_ms"] == POLE_2026 and real["generation"] == "f1_2026" and real["generation_chosen"] is True
    assert chosen["real_f1_asks_generation"] is True and chosen["real_f1_note"] is None
    assert chosen["boards_here"][0]["vs"]["real_f1"]["lap_ms"] == POLE_2026
    assert set(chosen["rows"][0]["vs"]) == {"real_f1"}
    assert idx_row["vs"]["real_f1"]["lap_ms"] == POLE_2025

    # the same generic car reported as a 2026 car by another driver: one board, two generations -> still none
    def mixed(c: sqlite3.Connection) -> None:
        jo = int(c.execute("SELECT id FROM drivers WHERE name='Jo'").fetchone()["id"])
        add_session(c, "g26", jo, car="f1:team:41", car_name="F1 Generic", formula="F1 26", started=T0 + DAY)
        add_lap(c, "g26", 1, 69_000, created=T0 + DAY + 60)

    writer.call(mixed)
    b = view(db, row["key"])
    assert [r["driver_name"] for r in b["rows"]] == ["Sam", "Jo"]
    assert b["real_f1"] is None and b["real_f1_note"] == S.REAL_F1_NO_GENERATION


def test_board_generation_rules() -> None:
    assert S.board_generation(AUSTRIA, {}) == "f1_2025"  # an empty board goes by the car id: Haas is a 2025 team
    generic = K.BoardKey("f1_25", "f1:17", 4318, "f1:team:41", "f1", 0, "race", "dry", AUSTRIA.assists)
    assert S.board_generation(generic, {}) is None
    gt7 = K.BoardKey("gt7", "gt7:x", 3800, "gt7:car:1", None, None, "unknown", "unknown", ())
    assert S.board_generation(gt7, {}) is None


@pytest.mark.parametrize(
    ("car", "formula"),
    [("f1:team:158", "F2"), ("f1:team:7", "F1 Classic"), ("f1:team:7", "Beta")],
)
def test_no_real_f1_row_for_f2_or_classic_cars(store: tuple[Database, DbWriter], car: str, formula: str) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        d = add_driver(c, "Sam")
        add_session(c, "s", d, car=car, formula=formula)
        add_lap(c, "s", 1, 75_000, created=T0 + 60)

    writer.call(job)
    with db.read() as c:
        (row,) = S.records_index(c)["boards"]
    b = view(db, row["key"])
    assert b["real_f1"] is None and b["real_f1_note"] is None and row["vs"] == {}


@pytest.mark.parametrize(
    ("track", "length", "note"),
    [
        ("f1:5", 3067.0, S.REAL_F1_OTHER_LENGTH),  # Monaco: the track sheet's lap and the real layout differ by 8 %
        ("f1:19", 4525.0, S.REAL_F1_OTHER_LENGTH),  # Mexico: 4.9 %
        ("f1:40", 4323.0, S.REAL_F1_NO_LAYOUT),  # Austria reversed: real F1 never raced it
        ("f1:17", 5000.0, S.REAL_F1_OTHER_LENGTH),  # Austria's id, another length: the session's layout vetoes it
        ("f1:42", 5411.0, "Real Formula 1 has no pole time here for 2025."),  # Madrid: 2026 only
    ],
)
def test_no_real_f1_row_where_the_real_layout_does_not_compare(
    store: tuple[Database, DbWriter], track: str, length: float, note: str
) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        d = add_driver(c, "Sam")
        add_session(c, "s", d, track=track, track_name="Track", length=length)
        add_lap(c, "s", 1, 80_000, created=T0 + 60)

    writer.call(job)
    with db.read() as c:
        (row,) = S.records_index(c)["boards"]
    b = view(db, row["key"])
    assert b["real_f1"] is None and b["real_f1_note"] == note and b["rows"][0]["vs"] == {}


def test_a_wet_pole_gives_gaps_but_no_bands(store: tuple[Database, DbWriter]) -> None:
    """Las Vegas 2025: the pole (1:47.934) was slower than the race's fastest lap, probably a wet qualifying."""
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        d = add_driver(c, "Sam")
        add_session(c, "lv", d, track="f1:31", track_name="Las Vegas", length=6200.0)
        add_lap(c, "lv", 1, 100_000, created=T0 + 60)

    writer.call(job)
    with db.read() as c:
        (row,) = S.records_index(c)["boards"]
    b = view(db, row["key"])
    real = b["real_f1"]
    assert real["lap_ms"] == 107_934 and real["banded"] is False and real["band_note"] == S.REAL_F1_WET_POLE_NOTE
    assert b["rows"][0]["vs"]["real_f1"] == {
        "gap_ms": -7934,
        "gap_pct": -7.35,
        "gap_text": "7.934 s faster",
        "band": None,
    }
    assert row["vs"]["real_f1"]["band"] is None


def test_other_games_get_no_real_f1_row(store: tuple[Database, DbWriter]) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        d = add_driver(c, "Sam")
        add_session(c, "g", d, game="gt7", track="gt7:sf:1", track_name="Track", car="gt7:car:1", formula=None)
        add_lap(c, "g", 1, 90_000, created=T0 + 60)

    writer.call(job)
    with db.read() as c:
        (row,) = S.records_index(c)["boards"]
    b = view(db, row["key"])
    assert b["real_f1"] is None and b["real_f1_note"] is None and b["ea_rival"] is None


def test_an_empty_board_still_shows_its_benchmarks(store: tuple[Database, DbWriter]) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        add_driver(c, "Sam")
        add_session(c, "tt", None, session_type="time_trial", car="f1:team:8")
        c.execute("UPDATE sessions SET driver_id=NULL WHERE id='tt'")
        store_rival(c, "tt", rival_set(), seen=T0)

    writer.call(job)
    b = view(db, TT_KEY)
    assert b["rows"] == [] and b["matched"] == 0
    assert b["real_f1"]["lap_ms"] == POLE_2025 and b["ea_rival"]["lap_ms"] == RIVAL_MS


# ---------------------------------------------------------------------------------------------- EA rival
@pytest.fixture
def time_trial(store: tuple[Database, DbWriter]) -> dict[str, Any]:
    """Sam and Jo in Time Trial at Austria in the McLaren; the rival Sam picked was stored with Sam's session."""
    _db, writer = store

    def job(c: sqlite3.Connection) -> dict[str, Any]:
        sam, jo = add_driver(c, "Sam"), add_driver(c, "Jo")
        add_session(c, "tt1", sam, session_type="time_trial", car="f1:team:8", car_name="McLaren")
        add_lap(c, "tt1", 1, 66_000, created=T0 + 60)
        store_rival(c, "tt1", rival_set(), seen=T0 + 120)
        add_session(c, "tt2", jo, session_type="time_trial", car="f1:team:8", car_name="McLaren", started=T0 + DAY)
        add_lap(c, "tt2", 1, 70_000, created=T0 + DAY + 60)
        add_session(c, "race", sam, session_type="race", car="f1:team:8", car_name="McLaren", started=T0 + DAY)
        add_lap(c, "race", 1, 66_500, created=T0 + DAY + 120)
        return {"sam": sam, "jo": jo}

    return writer.call(job)


def test_ea_rival_row_and_bands_on_a_time_trial_board(
    store: tuple[Database, DbWriter], time_trial: dict[str, Any]
) -> None:
    db, _ = store
    b = view(db, TT_KEY)
    assert b["key"] == TT_KEY
    rival = b["ea_rival"]
    assert rival["kind"] == "ea_rival" and rival["lap_ms"] == RIVAL_MS and rival["label"] == "EA rival"
    assert rival["banded"] is True and rival["valid"] is True and rival["session_id"] == "tt1"
    assert rival["sectors_ms"] == [16_000, 28_000, RIVAL_MS - 44_000]
    assert rival["assists"] == {"traction_control": False, "anti_lock_brakes": True, "gearbox_assist": False}
    assert rival["assists_text"] == "Traction control off, ABS on, Gearbox assist off"
    assert rival["equal_performance"] is False and rival["custom_setup"] is False and rival["car_name"] == "McLaren"
    assert rival["seen_unix"] == T0 + 120 and rival["date_text"] == "Sat 10 Oct"
    # spec-decoded until a recording shows packet 14: the tier and the caveat say so
    assert (rival["evidence"], rival["evidence_level"]) == ("spec-decoded", "spec_implemented")
    assert "EA's Time Trial leaderboard" in rival["caveat"] and "not yet seen in a recording" in rival["caveat"]
    # Sam 66.000 is +2.33 % (gold), Jo 70.000 +8.53 % (bronze); both rows also carry the real 2025 pole
    assert driver_bands(b, "ea_rival") == [("Sam", "gold"), ("Jo", "bronze")]
    assert b["rows"][0]["vs"]["ea_rival"]["gap_text"] == "1.500 s slower"
    assert set(b["rows"][0]["vs"]) == {"ea_rival", "real_f1"}
    # the race board at the same track and car has no EA rival
    with db.read() as c:
        idx = {r["fields"]["category"]: r for r in S.records_index(c)["boards"]}
    assert set(idx["time_trial"]["vs"]) == {"ea_rival", "real_f1"} and set(idx["race"]["vs"]) == {"real_f1"}
    race = view(db, idx["race"]["key"])
    assert race["ea_rival"] is None and set(race["rows"][0]["vs"]) == {"real_f1"}


def test_ea_rival_matching(store: tuple[Database, DbWriter], time_trial: dict[str, Any]) -> None:
    db, writer = store
    tt = K.decode(TT_KEY)

    def rival(key: K.BoardKey = tt) -> int | None:
        with db.read() as c:
            r = S.ea_rival_for(c, key)
        return None if r is None else r.lap_ms

    assert rival() == RIVAL_MS

    def newer(c: sqlite3.Connection) -> None:
        store_rival(c, "tt2", rival_set(64_000), seen=T0 + DAY + 300)

    writer.call(newer)
    assert rival() == 64_000  # the latest stored rival wins

    def other_car(c: sqlite3.Connection) -> None:  # a newer rival in another team: not this board's
        add_session(c, "tt3", time_trial["sam"], session_type="time_trial", car="f1:team:8", started=T0 + 2 * DAY)
        store_rival(c, "tt3", rival_set(60_000, team=7), seen=T0 + 2 * DAY)

    writer.call(other_car)
    assert rival() == 64_000

    def equal(c: sqlite3.Connection) -> None:  # set with equal car performance: not on a realistic-performance board
        store_rival(c, "tt3", rival_set(61_000, equal=True), seen=T0 + 2 * DAY)

    writer.call(equal)
    assert rival() == 64_000
    assert rival(K.decode(TT_KEY.replace("~f1~0~", "~f1~1~"))) == 61_000  # the equal-performance board's rival

    def invalid(c: sqlite3.Connection) -> None:
        store_rival(c, "tt3", rival_set(59_000, valid=False), seen=T0 + 3 * DAY)

    writer.call(invalid)
    assert rival() == 64_000  # an invalid rival lap never shows

    def assists_differ(c: sqlite3.Connection) -> None:  # TC on: shown as the game sent it, never matched
        store_rival(c, "tt3", rival_set(63_000, tc=True, abs_on=None), seen=T0 + 4 * DAY)

    writer.call(assists_differ)
    assert rival() == 63_000
    with db.read() as c:
        r = S.ea_rival_for(c, tt)
    assert r is not None and r.detail["assists_text"] == "Traction control on, ABS unknown, Gearbox assist off"
    # other layouts, session types, games and an unknown car never get one
    assert rival(K.decode(TT_KEY.replace("~4318~", "~5000~"))) is None
    assert rival(K.decode(TT_KEY.replace("~time_trial~", "~qualifying~"))) is None
    assert rival(K.decode(TT_KEY.replace("~f1:team:8~", "~?~"))) is None
    assert rival(K.decode(TT_KEY.replace("~f1~0~", "~f1~?~"))) is None  # unknown equal performance: only unknown


def test_synthetic_and_replayed_rivals_never_show(store: tuple[Database, DbWriter]) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        d = add_driver(c, "Sam")
        add_session(c, "syn", d, session_type="time_trial", car="f1:team:8", synthetic=True)
        store_rival(c, "syn", rival_set(50_000), seen=T0)
        add_session(c, "rep", d, session_type="time_trial", car="f1:team:8", source="replay:x.pwcap")
        store_rival(c, "rep", rival_set(51_000), seen=T0)

    writer.call(job)
    assert view(db, TT_KEY)["ea_rival"] is None


# ---------------------------------------------------------------------------------------------- API
def test_api_board_and_index_carry_the_rows(store: tuple[Database, DbWriter], time_trial: dict[str, Any]) -> None:
    db, writer = store
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(db=db, writer=writer)
    with TestClient(app) as client:
        b = client.get("/api/leaderboard", params={"key": TT_KEY}).json()
        by_fields = client.get(
            "/api/leaderboard", params={"game": "f1_25", "track_id": "f1:17", "category": "time_trial"}
        ).json()
        idx = client.get("/api/records").json()
    assert b["ea_rival"]["lap_ms"] == RIVAL_MS and b["real_f1"]["lap_ms"] == POLE_2025 and b["real_f1_note"] is None
    assert b["rows"][0]["vs"]["ea_rival"]["band"] == "gold" and b["rows"][0]["vs"]["real_f1"]["band"] == "silver"
    assert by_fields["key"] == TT_KEY and by_fields["ea_rival"] == b["ea_rival"]
    tt_row = next(r for r in idx["boards"] if r["key"] == TT_KEY)
    assert tt_row["vs"]["ea_rival"]["band"] == "gold" and tt_row["vs"]["real_f1"]["lap_ms"] == POLE_2025
    with TestClient(app) as client:
        chosen = client.get("/api/leaderboard", params={"key": TT_KEY, "car_generation": "f1_2026"})
        assert chosen.status_code == 200 and chosen.json()["real_f1"]["lap_ms"] == POLE_2025  # McLaren: 2025 car
        assert client.get("/api/records", params={"car_generation": "f1_2026"}).status_code == 200
        bad = {"key": TT_KEY, "car_generation": "f1_2024"}
        assert client.get("/api/leaderboard", params=bad).status_code == 422
        assert client.get("/api/records", params={"car_generation": "2025"}).status_code == 422
