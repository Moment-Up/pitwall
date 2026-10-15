"""F1 25 Time Trial (leaderboard): the session manager keeps packet 14 in live state and stores the latest per session
(schema v7 ``session_time_trial``); ``repo.latest_tt_rival`` / ``latest_tt_rivals`` give a board its EA rival row.

Objects are built directly (no game data): this tests storage and routing, not the decoder (test_f1_time_trial.py)."""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from pitwall.core.lap_processor import AnalysisWorker
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.model.telemetry import CarFrame, Game, SessionInfo, SessionType, TimeTrialDataSet, TimeTrialInfo
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

SOURCE = "udp:20777"
UID = "4242"


def ds(
    lap_ms: int, *, car: int | None = 8, abs_on: bool | None = True, valid: bool | None = True, **kw: Any
) -> TimeTrialDataSet:
    base: dict[str, Any] = {
        "car_index": 1,
        "team_id": car,
        "car_id": None if car is None else f"f1:team:{car}",
        "car_name": None if car is None else f"Team {car}",
        "lap_time_ms": lap_ms,
        "sector_times_ms": (lap_ms // 3, lap_ms // 3, lap_ms - 2 * (lap_ms // 3)),
        "traction_control": False,
        "gearbox_assist": False,
        "anti_lock_brakes": abs_on,
        "equal_car_performance": False,
        "custom_setup": False,
        "valid": valid,
    }
    return TimeTrialDataSet(**(base | kw))


def tt(rival: TimeTrialDataSet | None, *, t: int = 1, uid: str | None = UID, best: int | None = None) -> TimeTrialInfo:
    return TimeTrialInfo(
        game=Game.F1_25,
        t_recv_ns=t,
        session_time_s=t / 1e9,
        session_uid=uid,
        packet_format=2025,
        player_session_best=None if best is None else ds(best, car=8, abs_on=False),
        personal_best=None,
        rival=rival,
        pb_car_index=None,
        rival_car_index=None if rival is None else 1,
    )


class _Jobs:
    def submit(self, job: Any) -> None:
        pass

    def submit_ai_pace(self, job: Any) -> None:
        pass


@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[Database, DbWriter]]:
    db = Database(tmp_path / "t.sqlite3")
    writer = DbWriter(db)
    yield db, writer
    writer.close()


def info(uid: str = UID, t: int = 1) -> SessionInfo:
    return SessionInfo(
        game=Game.F1_25,
        t_recv_ns=t,
        session_uid=uid,
        track_id="f1:17",
        track_name="Austria",
        track_length_m=4318.0,
        session_type=SessionType.TIME_TRIAL,
        car_id="f1:team:8",
    )


def manager(writer: DbWriter, live: LiveState, **kw: Any) -> SessionManager:
    return SessionManager(writer, live, cast(AnalysisWorker, _Jobs()), source=SOURCE, **kw)


def rows(db: Database) -> list[dict[str, Any]]:
    with db.read() as c:
        return [dict(r) for r in c.execute("SELECT * FROM session_time_trial ORDER BY rowid")]


# ---------------------------------------------------------------- session manager + live state
def test_changes_go_to_live_state_and_the_session_row(
    store: tuple[Database, DbWriter], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, writer = store
    writes: list[str] = []
    real = repo.upsert_session_time_trial

    def counting(c: sqlite3.Connection, sid: str, e: TimeTrialInfo) -> None:
        writes.append(sid)
        real(c, sid, e)

    monkeypatch.setattr(repo, "upsert_session_time_trial", counting)
    live = LiveState()
    sm = manager(writer, live)
    sm.handle(tt(ds(64_000)))
    assert sm.session_id is None  # never starts a session
    sm.handle(info())
    sid = sm.session_id
    assert sid is not None
    for k in range(5):  # packet 14 every second, nothing new: stored once
        sm.handle(tt(ds(64_000), t=10 + k))
    writer.flush()
    assert writes == [sid]
    assert live.snapshot()["time_trial"]["rival"]["lap_time_ms"] == 64_000
    sm.handle(tt(ds(63_500), t=20))  # the player picked another rival
    sm.handle(tt(ds(63_500), t=21, best=66_000))  # and set a session best
    writer.flush()
    assert len(writes) == 3
    (row,) = rows(db)
    assert (row["session_id"], row["rival_lap_ms"], row["rival_car_id"], row["rival_abs"]) == (
        sid,
        63_500,
        "f1:team:8",
        1,
    )
    with db.read() as c:
        stored = repo.get_session_time_trial(c, sid)
    assert stored is not None and stored["session_best"]["lap_time_ms"] == 66_000
    assert live.time_trial is not None and live.time_trial["session_best"]["lap_time_ms"] == 66_000


def test_another_game_sessions_packet_is_dropped(store: tuple[Database, DbWriter]) -> None:
    """The adapter changes session on the new session's first packet; until its Session packet arrives here, a Time
    Trial packet of the new game session must not land on the old pitwall session."""
    db, writer = store
    live = LiveState()
    sm = manager(writer, live)
    sm.handle(info())
    sm.handle(tt(ds(64_000), uid="9999"))
    writer.flush()
    assert rows(db) == [] and live.time_trial is None
    sm.handle(info(uid="9999", t=5))  # the new game session: a new pitwall session, stored again at once
    sm.handle(tt(ds(64_000), uid="9999", t=6))
    writer.flush()
    assert [r["session_id"] for r in rows(db)] == [sm.session_id]


def test_a_new_session_stores_the_same_data_again(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    live = LiveState()
    sm = manager(writer, live)
    sm.handle(info())
    sm.handle(tt(ds(64_000)))
    first = sm.session_id
    sm.end()
    assert live.time_trial is not None  # end() keeps live state until the next session starts
    sm.handle(info(t=50))
    assert sm.session_id != first and live.time_trial is None  # reset_session cleared it
    sm.handle(tt(ds(64_000), t=51))
    writer.flush()
    assert [r["session_id"] for r in rows(db)] == [first, sm.session_id]
    assert live.time_trial is not None


def test_resumed_session_gets_its_row_back(store: tuple[Database, DbWriter]) -> None:
    """A service restart mid-session: the just-started row is folded into the old one (its Time Trial row goes with
    it) and the next packet is stored on the resumed session."""
    db, writer = store
    sm = manager(writer, LiveState())
    sm.handle(info())
    sm.handle(CarFrame(game=Game.F1_25, t_recv_ns=2, lap_number=1, lap_distance_m=10.0))
    old = sm.session_id
    sm.end()
    writer.flush()
    with db.read() as c:
        cand = repo.last_live_session(c, SOURCE)
    sm2 = manager(writer, LiveState(), resume_candidate=cand)
    sm2.handle(CarFrame(game=Game.F1_25, t_recv_ns=100, lap_number=1, lap_distance_m=20.0))
    sm2.handle(tt(ds(64_000), t=101))  # stored on the new row...
    sm2.handle(info(t=102))  # ...which the game's same UID folds back into the old session
    sm2.handle(tt(ds(64_000), t=103))
    writer.flush()
    assert sm2.session_id == old and sm2.sessions_resumed == 1
    assert [r["session_id"] for r in rows(db)] == [old]


def test_live_state_drops_another_sessions_block() -> None:
    live = LiveState()
    live.reset_session("s1", SOURCE, False)
    live.set_time_trial("s0", {"rival": None})
    assert live.snapshot()["time_trial"] is None
    live.set_time_trial("s1", {"rival": None})
    assert live.snapshot()["time_trial"] == {"rival": None}


# ---------------------------------------------------------------- repo: the board's EA rival
def _session(
    c: sqlite3.Connection,
    sid: str,
    rival: TimeTrialDataSet | None,
    *,
    updated: float,
    track: str = "f1:17",
    length: float = 4318.0,
    synthetic: bool = False,
    source: str = SOURCE,
) -> None:
    repo.insert_session(c, sid, "f1_25", source, synthetic, None, 0)
    c.execute(
        "UPDATE sessions SET track_id=?, track_name='Austria', track_length_m=?, session_type='time_trial', "
        "started_unix=? WHERE id=?",
        (track, length, updated - 100, sid),
    )
    repo.upsert_session_time_trial(c, sid, tt(rival))
    c.execute("UPDATE session_time_trial SET updated_unix=? WHERE session_id=?", (updated, sid))


@pytest.fixture
def boards(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db = Database(tmp_path / "b.sqlite3")
    with db.read() as c:
        _session(c, "a_abs_on", ds(64_000, abs_on=True), updated=1000.0)
        _session(c, "b_abs_off", ds(63_900, abs_on=False), updated=2000.0)
        _session(c, "c_synthetic", ds(60_000), updated=3000.0, synthetic=True)
        _session(c, "d_replay", ds(61_000), updated=3000.0, source="replay:x.pwcap")
        _session(c, "e_williams", ds(64_500, car=3), updated=1500.0)
        _session(c, "f_invalid", ds(59_000, valid=False), updated=3500.0)
        _session(c, "g_no_rival", None, updated=3600.0)
        _session(c, "h_unknown_valid", ds(59_500, valid=None), updated=3700.0)
        _session(c, "i_other_track", ds(80_000), updated=3800.0, track="f1:7", length=5891.0)
        c.commit()
        yield c


def test_latest_rival_is_the_newest_real_valid_lap_in_that_car(boards: sqlite3.Connection) -> None:
    c = boards
    r = repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:8")
    assert r is not None and r["session_id"] == "b_abs_off"  # newer than a; synthetic, replay, invalid never count
    assert r["lap_time_ms"] == 63_900 and r["sector_times_ms"] == [21_300, 21_300, 21_300]
    assert r["car_id"] == "f1:team:8" and r["car_name"] == "Team 8" and r["valid"] is True
    assert r["assists"] == {
        "traction_control": False,
        "gearbox_assist": False,
        "anti_lock_brakes": False,
        "equal_car_performance": False,
        "custom_setup": False,
    }
    assert (r["track_name"], r["track_length_m"], r["seen_unix"], r["packet_format"]) == (
        "Austria",
        4318.0,
        2000.0,
        2025,
    )
    assert repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:3")["session_id"] == "e_williams"  # type: ignore[index]
    assert repo.latest_tt_rival(c, "f1_25", "f1:17", None) is None  # an unknown car has no rival
    assert repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:1") is None
    assert repo.latest_tt_rival(c, "f1_25", "f1:99", "f1:team:8") is None
    assert repo.latest_tt_rival(c, "gt7", "f1:17", "f1:team:8") is None


def test_assists_and_layout_are_exact(boards: sqlite3.Connection) -> None:
    c = boards
    on = repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:8", assists={"anti_lock_brakes": True})
    assert on is not None and on["session_id"] == "a_abs_on"
    both = {"anti_lock_brakes": False, "traction_control": False, "equal_car_performance": False}
    assert repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:8", assists=both)["session_id"] == "b_abs_off"  # type: ignore[index]
    # unknown is its own bucket, never a wildcard
    assert repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:8", assists={"anti_lock_brakes": None}) is None
    assert repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:8", track_length_m=4400.0) is not None  # within 3 %
    assert repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:8", track_length_m=5000.0) is None
    with pytest.raises(ValueError, match="unknown time trial flag"):
        repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:8", assists={"braking": 1})  # type: ignore[dict-item]


def test_an_unknown_flag_matches_only_unknown(tmp_path: Path) -> None:
    db = Database(tmp_path / "u.sqlite3")
    with db.read() as c:
        _session(c, "x", ds(64_000, traction_control=None), updated=10.0)
        c.commit()
        assert repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:8", assists={"traction_control": False}) is None
        r = repo.latest_tt_rival(c, "f1_25", "f1:17", "f1:team:8", assists={"traction_control": None})
        assert r is not None and r["assists"]["traction_control"] is None


def test_latest_rivals_index_one_per_track_car_and_assist_bucket(boards: sqlite3.Connection) -> None:
    out = repo.latest_tt_rivals(boards)
    assert [(r["track_id"], r["car_id"], r["session_id"]) for r in out] == [
        ("f1:17", "f1:team:3", "e_williams"),
        ("f1:17", "f1:team:8", "b_abs_off"),
        ("f1:17", "f1:team:8", "a_abs_on"),
        ("f1:7", "f1:team:8", "i_other_track"),
    ]
    assert repo.latest_tt_rivals(boards, game="gt7") == []


def test_row_roundtrip_and_cascade(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.sqlite3")
    with db.read() as c:
        _session(c, "s", None, updated=5.0)
        c.commit()
        stored = repo.get_session_time_trial(c, "s")
        assert stored == {**tt(None).to_dict(), "updated_unix": 5.0}
        (row,) = (dict(r) for r in c.execute("SELECT * FROM session_time_trial"))
        assert row["rival_lap_ms"] is None and row["rival_car_id"] is None and row["rival_valid"] is None
        repo.upsert_session_time_trial(c, "s", dataclasses.replace(tt(ds(64_000)), pb_car_index=2))
        assert tuple(c.execute("SELECT COUNT(*), MAX(pb_car_index) FROM session_time_trial").fetchone()) == (1, 2)
        c.execute("DELETE FROM sessions WHERE id='s'")
        c.commit()
        assert repo.get_session_time_trial(c, "s") is None
        assert repo.get_session_time_trial(c, "missing") is None


def test_synthetic_time_trial_stream_is_stored_but_never_a_board_rival(store: tuple[Database, DbWriter]) -> None:
    """SYNTHETIC end to end: the generated Time Trial stream through the adapter and the session manager on a live
    source. The stream carries the synthetic session UID, so its session is flagged synthetic: the row is stored (and
    shown live) but never a board's rival."""
    from pitwall.adapters.f1.adapter import F1Adapter
    from pitwall.sim.f1_stream import generate_f1_session
    from pitwall.sim.scenarios import TT_DEMO_RIVAL, time_trial_demo

    db, writer = store
    sc = time_trial_demo()
    sc.laps = 1
    packets, _truth = generate_f1_session(sc)
    adapter, live = F1Adapter(), LiveState()
    sm = manager(writer, live)
    for p in packets:
        for e in adapter.decode(p.data, p.t_recv_ns):
            sm.handle(e)
    writer.flush()
    (row,) = rows(db)
    assert row["rival_lap_ms"] == TT_DEMO_RIVAL.lap_ms and row["rival_car_id"] == "f1:team:8"
    assert live.time_trial is not None and live.time_trial["rival"]["lap_time_ms"] == TT_DEMO_RIVAL.lap_ms
    with db.read() as c:
        s = repo.get_session(c, row["session_id"])
        assert s is not None and s["synthetic"] and s["session_type"] == "time_trial"
        assert s["track_id"].startswith("synthetic:")
        assert repo.latest_tt_rival(c, "f1_25", s["track_id"], "f1:team:8") is None
        assert repo.latest_tt_rivals(c) == []
