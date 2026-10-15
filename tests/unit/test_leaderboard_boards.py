"""Family boards from the database (``repo.board_bests`` / ``board_record_laps`` + ``leaderboard.board`` /
``service``): each driver's best clean valid lap per exact key, laps that never count, unknown values in their own
bucket, layouts within 3 % merged, best sectors and the theoretical best, the record history, record takes."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.leaderboard import board as B
from pitwall.leaderboard import keys as K
from pitwall.leaderboard import service as S
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from tests.unit.leaderboard_data import AUSTRIA_KEY, DAY, T0, add_driver, add_lap, add_session

AUSTRIA = K.decode(AUSTRIA_KEY)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[Database, DbWriter]]:
    db = Database(tmp_path / "boards.sqlite3")
    writer = DbWriter(db)
    yield db, writer
    writer.close()


@pytest.fixture
def family(store: tuple[Database, DbWriter]) -> dict[str, Any]:
    """Sam and Jo at Austria in the Haas (race, dry, same assists), plus every lap that must never count."""
    _db, writer = store

    def job(c: sqlite3.Connection) -> dict[str, Any]:
        sam, jo, kim = add_driver(c, "Sam"), add_driver(c, "Jo"), add_driver(c, "Kim")
        ids: dict[str, Any] = {"sam": sam, "jo": jo, "kim": kim}
        add_session(c, "s1", sam, started=T0)
        ids["s1_first"] = add_lap(c, "s1", 1, 76_577, created=T0 + 100, sectors=(18_000, 33_000, 25_577))
        ids["s1_best"] = add_lap(c, "s1", 2, 71_745, created=T0 + 200, sectors=(16_900, 31_700, 23_145))
        add_lap(c, "s1", 3, 72_000, created=T0 + 300, sectors=(16_662, 32_000, 23_338))  # Sam's best S1 on its own
        add_session(c, "s2", sam, started=T0 + DAY, weather="overcast")  # still dry: the same board
        ids["sam_best"] = add_lap(c, "s2", 1, 70_549, created=T0 + DAY + 100, sectors=(16_900, 31_149, 22_500))
        add_lap(c, "s2", 2, 70_900, created=T0 + DAY + 200, sectors=(17_000, 31_300, 22_151))
        add_session(c, "j1", jo, started=T0 + 2 * DAY)
        ids["jo_best"] = add_lap(c, "j1", 1, 73_616, created=T0 + 2 * DAY + 100, sectors=(17_247, 31_956, 24_413))
        # never counted: unclean, invalid, untimed, synthetic, a replay, no owner, an unknown track
        add_lap(c, "j1", 2, 60_000, created=T0 + 2 * DAY + 200, clean=False)
        add_lap(c, "j1", 3, 60_000, created=T0 + 2 * DAY + 300, valid=False)
        add_lap(c, "j1", 4, None, created=T0 + 2 * DAY + 400)
        add_session(c, "syn", jo, synthetic=True, started=T0 + 3 * DAY)
        add_lap(c, "syn", 1, 60_000, created=T0 + 3 * DAY)
        add_session(c, "rep", jo, source="replay:x.pwcap", started=T0 + 3 * DAY)
        add_lap(c, "rep", 1, 60_000, created=T0 + 3 * DAY)
        add_session(c, "none", None, started=T0 + 3 * DAY)
        c.execute("UPDATE sessions SET driver_id=NULL WHERE id='none'")
        add_lap(c, "none", 1, 60_000, created=T0 + 3 * DAY)
        add_session(c, "unk", jo, track="unknown_7", started=T0 + 3 * DAY)
        add_lap(c, "unk", 1, 60_000, created=T0 + 3 * DAY)
        add_session(c, "m1", jo, track="f1:-1", started=T0 + 3 * DAY)
        add_lap(c, "m1", 1, 60_000, created=T0 + 3 * DAY)
        return ids

    return writer.call(job)


def board(db: Database, key: K.BoardKey = AUSTRIA) -> dict[str, Any]:
    with db.read() as c:
        return S.board_by_key(c, key)


def test_each_driver_s_best_clean_valid_lap_on_the_exact_key(
    store: tuple[Database, DbWriter], family: dict[str, Any]
) -> None:
    db, _ = store
    b = board(db)
    assert b["key"] == AUSTRIA_KEY
    assert [(r["driver_name"], r["lap_ms"], r["lap_id"]) for r in b["rows"]] == [
        ("Sam", 70_549, family["sam_best"]),
        ("Jo", 73_616, family["jo_best"]),
    ]
    sam, jo = b["rows"]
    assert sam["leader"] and sam["gap_ms"] is None and sam["gap_text"] == "Fastest" and sam["position"] == 1
    assert (jo["gap_ms"], jo["gap_pct"], jo["gap_text"]) == (3067, 4.35, "3.067 s behind")
    assert sam["clean_laps"] == 5 and jo["clean_laps"] == 1  # Sam: both sessions (clear and overcast are dry)
    # each sector best on its own, across the driver's sessions on this board
    assert sam["best_sectors_ms"] == [16_662, 31_149, 22_151]
    assert sam["theoretical_best_ms"] == 69_962 and sam["theoretical_gain_ms"] == 587
    assert sam["session_id"] == "s2" and sam["date_text"] == "Sun 11 Oct" and sam["game_version"] == "1.26"
    assert [c["label"] for c in sam["assists"]][:3] == ["Braking assist medium", "ABS on", "Traction control full"]
    assert b["record"]["driver_name"] == "Sam" and b["record"]["lap_ms"] == 70_549
    assert b["no_time"] == [{"driver_id": family["kim"], "driver_name": "Kim"}]
    assert b["labels"]["title"] == "Austria · Haas · Race · Dry"
    assert b["evidence"]["track_limits_checked"] is True
    assert b["ea_rival"] is None and b["real_f1"] is None and sam["vs"] == {}
    assert b["matched"] == 1 and [x["key"] for x in b["boards_here"]] == [AUSTRIA_KEY]


def test_record_history_in_the_order_driven(store: tuple[Database, DbWriter], family: dict[str, Any]) -> None:
    db, writer = store
    hist = board(db)["history"]
    assert [(h["driver_name"], h["lap_ms"], h["changed_hands"]) for h in hist] == [
        ("Sam", 76_577, False),
        ("Sam", 71_745, False),
        ("Sam", 70_549, False),
    ]
    assert hist[0]["text"] == "Sam set the first record: 1:16.577"
    assert hist[2]["text"] == "Sam improved the record: 1:10.549, 1.196 s faster"
    # Jo takes it, then Sam takes it back
    writer.call(lambda c: add_session(c, "j2", family["jo"], started=T0 + 4 * DAY))
    jo_rec = writer.call(lambda c: add_lap(c, "j2", 1, 70_400, created=T0 + 4 * DAY + 60))
    writer.call(lambda c: add_lap(c, "j2", 2, 70_450, created=T0 + 4 * DAY + 120))  # not faster than the record
    writer.call(lambda c: add_session(c, "s3", family["sam"], started=T0 + 5 * DAY))
    writer.call(lambda c: add_lap(c, "s3", 1, 70_100, created=T0 + 5 * DAY + 60))
    hist = board(db)["history"]
    assert [(h["driver_name"], h["lap_ms"], h["changed_hands"]) for h in hist[3:]] == [
        ("Jo", 70_400, True),
        ("Sam", 70_100, True),
    ]
    assert hist[3]["lap_id"] == jo_rec and hist[3]["previous_driver_name"] == "Sam" and hist[3]["gain_ms"] == 149
    assert hist[3]["text"] == "Jo took the record from Sam: 1:10.400, 0.149 s faster"


def test_unknown_values_are_their_own_boards(store: tuple[Database, DbWriter], family: dict[str, Any]) -> None:
    """ABS not sent, weather not sent, the car unknown: separate boards, never merged into the known one."""
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        add_session(c, "abs?", family["jo"], started=T0 + 4 * DAY)
        add_lap(c, "abs?", 1, 65_000, created=T0 + 4 * DAY, meta={"traction_control": 2})
        add_session(c, "wx?", family["jo"], started=T0 + 4 * DAY, weather=None)
        add_lap(c, "wx?", 1, 65_000, created=T0 + 4 * DAY)
        add_session(c, "car?", family["jo"], started=T0 + 4 * DAY, car=None, car_name=None)
        add_lap(c, "car?", 1, 65_000, created=T0 + 4 * DAY)
        add_session(c, "wet", family["jo"], started=T0 + 4 * DAY, weather="light_rain")
        add_lap(c, "wet", 1, 65_000, created=T0 + 4 * DAY)
        add_session(c, "tt", family["jo"], started=T0 + 4 * DAY, session_type="time_trial")
        add_lap(c, "tt", 1, 65_000, created=T0 + 4 * DAY)

    writer.call(job)
    assert board(db)["rows"][0]["lap_ms"] == 70_549  # none of the 65.000 laps is on the known board
    with db.read() as c:
        idx = S.records_index(c, "f1_25", "f1:17")
    parts = sorted(K.parts(K.decode(b["key"]))["assists"] for b in idx["boards"])
    assert parts.count("b2.a?.t2.g3.l2") == 1
    keys = {b["key"] for b in idx["boards"]}
    assert "f1_25~f1:17~4318~f1:team:7~f1~0~race~unknown~b2.a1.t2.g3.l2" in keys
    assert "f1_25~f1:17~4318~?~f1~0~race~dry~b2.a1.t2.g3.l2" in keys  # the formula still names the class
    assert "f1_25~f1:17~4318~f1:team:7~f1~0~race~wet~b2.a1.t2.g3.l2" in keys
    assert "f1_25~f1:17~4318~f1:team:7~f1~0~time_trial~dry~b2.a1.t2.g3.l2" in keys
    assert idx["count"] == 6
    unknown_car = next(b for b in idx["boards"] if b["fields"]["car_id"] is None)
    assert unknown_car["labels"]["car"] == "Unknown car"


def test_layouts_within_three_percent_are_one_board(store: tuple[Database, DbWriter], family: dict[str, Any]) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        add_session(c, "near", family["kim"], started=T0 + 4 * DAY, length=4323.0)
        add_lap(c, "near", 1, 72_000, created=T0 + 4 * DAY)
        add_session(c, "far", family["kim"], started=T0 + 4 * DAY, length=4480.0)
        add_lap(c, "far", 1, 71_000, created=T0 + 4 * DAY)
        add_session(c, "len?", family["kim"], started=T0 + 4 * DAY, length=None)
        add_lap(c, "len?", 1, 71_000, created=T0 + 4 * DAY)

    writer.call(job)
    b = board(db)
    assert [r["driver_name"] for r in b["rows"]] == ["Sam", "Kim", "Jo"]
    assert b["rows"][1]["lap_ms"] == 72_000 and b["labels"]["layout"] == "4.32 km"
    layouts = sorted((x["fields"]["layout_m"] if x["fields"]["layout_m"] is not None else -1) for x in b["boards_here"])
    assert layouts == [-1, 4318, 4480]


def test_records_index(store: tuple[Database, DbWriter], family: dict[str, Any]) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        add_session(
            c,
            "gt7",
            family["kim"],
            game="gt7",
            track="gt7:sf:380:120:15:3800:530",
            track_name="Unidentified GT7 circuit (3.80 km)",
            length=3799.2,
            car="gt7:car:3353",
            car_name=None,
            session_type="unknown",
            weather=None,
            formula=None,
            started=T0 + 4 * DAY,
        )
        add_lap(c, "gt7", 1, 103_358, created=T0 + 4 * DAY, valid=None)

    writer.call(job)
    with db.read() as c:
        idx = S.records_index(c)
        only_jo = S.records_index(c, driver_id=family["jo"])
        gt7 = S.records_index(c, game="gt7")
    assert idx["count"] == 2
    f1, g = idx["boards"]  # F1 25 before GT7
    assert f1["key"] == AUSTRIA_KEY
    assert f1["record"]["driver_name"] == "Sam" and f1["drivers"] == 2 and f1["clean_laps"] == 6
    assert f1["track_limits_checked"] is True
    assert g["labels"]["car"] == "Car 3353"  # GT7 names cars by number only: never the raw id
    assert g["labels"]["assists_text"] == "Assists not reported by this game"
    assert g["track_limits_checked"] is False and g["fields"]["layout_m"] == 3799
    assert [b["key"] for b in only_jo["boards"]] == [AUSTRIA_KEY]
    assert gt7["count"] == 1
    gb = board(db, K.decode(g["key"]))
    assert gb["evidence"]["note"] == B.TRACK_LIMITS_NOTE and gb["rows"][0]["game_version"] is None


def test_board_by_filter_picks_the_most_recent_matching_board(
    store: tuple[Database, DbWriter], family: dict[str, Any]
) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        add_session(c, "q", family["jo"], session_type="qualifying", started=T0 + 9 * DAY)
        add_lap(c, "q", 1, 71_000, created=T0 + 9 * DAY)

    writer.call(job)
    with db.read() as c:
        newest = S.board_by_filter(c, S.BoardFilter("f1_25", "f1:17"))
        race = S.board_by_filter(c, S.BoardFilter("f1_25", "f1:17", category="race", length_m=4320.0))
        by_assists = S.board_by_filter(c, S.BoardFilter("f1_25", "f1:17", assists="b2.a1.t2.g3.l2", car_id="f1:team:7"))
        none = S.board_by_filter(c, S.BoardFilter("f1_25", "f1:17", conditions="wet"))
        other_layout = S.board_by_filter(c, S.BoardFilter("f1_25", "f1:17", length_m=5000.0))
    assert newest["fields"]["category"] == "qualifying" and newest["matched"] == 2
    assert race["key"] == AUSTRIA_KEY and race["matched"] == 1
    assert by_assists["matched"] == 2
    assert none["key"] is None and none["rows"] == [] and none["matched"] == 0 and len(none["boards_here"]) == 2
    assert {d["driver_name"] for d in none["no_time"]} == {"Sam", "Jo", "Kim"}
    assert other_layout["matched"] == 0


def test_an_older_layout_name_finds_its_board(store: tuple[Database, DbWriter], family: dict[str, Any]) -> None:
    """The layout is named by its shortest stored length: a key made before a shorter length was stored still finds
    the board (within 3 %)."""
    db, _ = store
    older = K.decode(AUSTRIA_KEY.replace("~4318~", "~4323~"))
    b = board(db, older)
    assert b["key"] == AUSTRIA_KEY and b["matched"] == 1
    far = board(db, K.decode(AUSTRIA_KEY.replace("~4318~", "~4600~")))
    assert far["rows"] == [] and far["key"].split("~")[2] == "4600"


def test_a_board_nobody_drove_is_empty_with_its_words(store: tuple[Database, DbWriter], family: dict[str, Any]) -> None:
    db, _ = store
    wet = K.decode(AUSTRIA_KEY.replace("~dry~", "~wet~"))
    b = board(db, wet)
    assert b["rows"] == [] and b["record"] is None and b["history"] == [] and b["matched"] == 0
    assert b["labels"]["title"] == "Austria · Haas · Race · Wet"
    assert len(b["no_time"]) == 3


def test_record_takes(store: tuple[Database, DbWriter], family: dict[str, Any]) -> None:
    """Sam held the record when Jo first drove there (contested): Sam's take. Jo has none until faster."""
    db, writer = store
    with db.read() as c:
        sam = S.record_takes_for(c, family["sam"])
        jo = S.record_takes_for(c, family["jo"])
    assert [(t.key.encode(), t.record.lap_id) for t in sam] == [(AUSTRIA_KEY, family["sam_best"])]
    assert jo == []
    writer.call(lambda c: add_session(c, "j2", family["jo"], started=T0 + 4 * DAY))
    lap = writer.call(lambda c: add_lap(c, "j2", 1, 70_000, created=T0 + 4 * DAY + 60))
    with db.read() as c:
        (take,) = S.record_takes_for(c, family["jo"])
    assert take.record.lap_id == lap and take.record.changed_hands and take.labels["track"] == "Austria"


def test_takes_need_a_contested_board() -> None:
    def entry(driver: int, first: float) -> B.Entry:
        return B.Entry(driver, f"d{driver}", 1, 1, "s", 70_000, first, first, 1, [None] * 3, first, first, {})

    def rec(lap: int, driver: int, ms: int, t: float, prev: tuple[int, int] | None = None) -> B.RecordEntry:
        return B.RecordEntry(lap, 1, f"s{lap}", driver, f"d{driver}", ms, t, t, *(prev if prev else (None, None)), None)

    hist = [rec(1, 1, 75_000, 1.0), rec(2, 1, 72_000, 2.0, (75_000, 1)), rec(3, 2, 71_000, 9.0, (72_000, 1))]
    # alone on the board: no take
    assert B.record_takes(AUSTRIA, hist[:2], {1: entry(1, 1.0)}, {}) == []
    # driver 2 first drove at t=5: driver 1 held the record (lap 2) then; driver 2 took it at t=9
    takes = B.record_takes(AUSTRIA, hist, {1: entry(1, 1.0), 2: entry(2, 5.0)}, {})
    assert [(t.driver_id, t.record.lap_id) for t in takes] == [(1, 2), (2, 3)]
    # driver 2's first lap was itself the record: only driver 2
    takes = B.record_takes(AUSTRIA, hist, {1: entry(1, 1.0), 2: entry(2, 9.0)}, {})
    assert [(t.driver_id, t.record.lap_id) for t in takes] == [(2, 3)]


def test_progression_merges_partitions() -> None:
    """Two raw partitions of one key (clear and overcast): the record runs again over both, in the order driven."""
    rows = [
        {"lap_id": 1, "lap_time_ms": 72_000, "set_unix": 1.0, "driver_id": 1, "driver_name": "Sam", "session_id": "a"},
        {"lap_id": 2, "lap_time_ms": 73_000, "set_unix": 2.0, "driver_id": 2, "driver_name": "Jo", "session_id": "b"},
        {"lap_id": 3, "lap_time_ms": 71_000, "set_unix": 3.0, "driver_id": 2, "driver_name": "Jo", "session_id": "b"},
    ]
    hist = B.progression(reversed(rows))
    assert [(h.lap_id, h.previous_driver_name, h.changed_hands) for h in hist] == [(1, None, False), (3, "Sam", True)]


def test_bands_and_benchmarks() -> None:
    assert B.band(64_000, 64_000) == "gold"
    assert B.band(63_000, 64_000) == "gold"  # faster than the benchmark
    assert B.band(65_920, 64_000) == "gold"  # +3.0 %
    assert B.band(65_921, 64_000) == "silver"
    assert B.band(67_200, 64_000) == "silver"  # +5.0 %
    assert B.band(70_400, 64_000) == "bronze"  # +10.0 %
    assert B.band(70_401, 64_000) is None
    assert B.band(70_000, 0) is None
    view = {"rows": [{"lap_ms": 70_549}, {"lap_ms": 73_616}]}
    pole = B.Benchmark("real_f1", 63_971, "Real F1 pole 2025", "Real car: F1 25 is not the real car.", {"year": 2025})
    out = B.with_benchmarks(view, real_f1=pole)
    assert out["real_f1"] == {
        "year": 2025,
        "kind": "real_f1",
        "lap_ms": 63_971,
        "label": "Real F1 pole 2025",
        "caveat": "Real car: F1 25 is not the real car.",
    }
    assert out["ea_rival"] is None
    assert out["rows"][0]["vs"] == {"real_f1": {"gap_ms": 6578, "gap_pct": 10.28, "band": None}}
    rival = B.Benchmark("ea_rival", 70_000, "EA rival")
    out = B.with_benchmarks(view, ea_rival=rival, real_f1=pole)
    assert out["rows"][0]["vs"]["ea_rival"] == {"gap_ms": 549, "gap_pct": 0.78, "band": "gold"}
    assert set(out["rows"][1]["vs"]) == {"ea_rival", "real_f1"}


def test_board_reads_never_touch_the_trace(store: tuple[Database, DbWriter], family: dict[str, Any]) -> None:
    db, _ = store
    with db.read() as c:
        rows = repo.board_bests(c)
        recs = repo.board_record_laps(c)
        lap = repo.board_lap(c, family["sam_best"])
    assert all("trace" not in r and "meta" not in r for r in (*rows, *recs))
    assert lap is not None and "trace" not in lap and lap["owned"] and lap["clean"] and lap["valid"] is True


def test_driver_scoped_loads_keep_everyone_s_laps_at_the_driver_s_tracks(
    store: tuple[Database, DbWriter], family: dict[str, Any]
) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        add_session(c, "kim", family["kim"], track="f1:11", track_name="Monza", length=5793.0, started=T0 + 4 * DAY)
        add_lap(c, "kim", 1, 81_000, created=T0 + 4 * DAY)
        add_session(c, "sam_monza", family["sam"], track="f1:11", track_name="Monza", length=5793.0, started=T0)
        add_lap(c, "sam_monza", 1, 80_000, created=T0 + 60)

    writer.call(job)
    with db.read() as c:
        kim_rows = repo.board_bests(c, driver_id=family["kim"])
        kim_recs = repo.board_record_laps(c, driver_id=family["kim"])
        sam_takes = S.record_takes_for(c, family["sam"])
    assert {r["track_id"] for r in kim_rows} == {"f1:11"} and {r["driver_id"] for r in kim_rows} == {
        family["kim"],
        family["sam"],
    }
    assert {r["track_id"] for r in kim_recs} == {"f1:11"}
    # oldest first: Sam held Monza (set at T0) when Kim first drove there, and Austria when Jo did
    assert [t.key.track_id for t in sam_takes] == ["f1:11", "f1:17"]
