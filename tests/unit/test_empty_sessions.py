"""Empty sessions and laps without a trace (storage.repo).

An ended session with nothing to show (menus, loading screens: GT7 left 23 such rows for 4 races on the owner's PS5
before its session rule was fixed) is hidden from the session lists, the latest-session lookups and the per-driver
counts, and never deleted. A lap the game timed but the adapter could not place on the track is stored with its time
and no samples; every trace reader sees it as having no trace.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import numpy as np
import pytest

from pitwall.analysis.laps import CHANNELS, LapAssembler, LapFlag, LapTrace
from pitwall.model.telemetry import CarFrame, EventKind, Game, GameEvent, LapCompletion
from pitwall.storage import repo
from pitwall.storage.db import Database


@pytest.fixture
def c(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db = Database(tmp_path / "pitwall.sqlite3")
    with closing(db.connect()) as c:
        yield c


def _lap(n: int, ms: int | None, samples: int) -> LapTrace:
    d = np.linspace(0.0, 10.0 * samples, samples)
    channels = {name: np.zeros(samples) for name in CHANNELS}
    channels["distance_m"] = d
    return LapTrace(lap_number=n, channels=channels, lap_time_ms=ms, flags=set() if ms else {LapFlag.INCOMPLETE})


def _session(c: sqlite3.Connection, sid: str, started: float, driver: int, *, ended: bool = True) -> None:
    repo.insert_session(c, sid, "gt7", "udp:33740", False, None, None, driver_id=driver)
    c.execute("UPDATE sessions SET started_unix=? WHERE id=?", (started, sid))
    if ended:
        repo.end_session(c, sid, None)


def test_empty_sessions_are_hidden_from_lists_latest_and_counts_never_deleted(c: sqlite3.Connection) -> None:
    d = repo.insert_driver(c, "Driver", {})
    now = time.time()
    _session(c, "driven", now - 100, d)
    repo.insert_lap(c, "driven", _lap(2, 23_222, 1393), None)
    _session(c, "stub", now - 90, d)  # a 2-sample untimed lap: the GT7 menus
    repo.insert_lap(c, "stub", _lap(1, None, 2), None)
    _session(c, "untimed", now - 85, d)  # driving without a completed lap is something to show
    repo.insert_lap(c, "untimed", _lap(1, None, 4473), None)
    _session(c, "chat", now - 80, d)
    repo.insert_message(c, "chat", "user", "How was that?")
    _session(c, "penalty", now - 70, d)
    repo.insert_event(c, "penalty", GameEvent(kind=EventKind.PENALTY, game=Game.GT7, t_recv_ns=1))
    _session(c, "ended_only", now - 60, d)  # GT7 now ends every session with a session_ended event
    repo.insert_event(c, "ended_only", GameEvent(kind=EventKind.SESSION_ENDED, game=Game.GT7, t_recv_ns=1))
    _session(c, "live", now - 50, d, ended=False)  # open (live) sessions are always listed
    _session(c, "menu", now - 40, d)  # the latest session: nothing in it
    c.commit()

    listed = [r["id"] for r in repo.list_sessions(c, 50)]
    assert listed == ["live", "penalty", "chat", "untimed", "driven"]
    assert [r["id"] for r in repo.list_sessions(c, 50, driver_id=d)] == listed
    assert len(repo.list_sessions(c, 50, include_empty=True)) == 8  # nothing deleted
    assert repo.latest_session_id(c) == repo.latest_session_id(c, driver_id=d) == "live"
    assert repo.driver_stats(c)[d]["sessions"] == repo.count_driver_sessions(c, d) == 5
    assert repo.get_session(c, "menu") is not None  # still there, by id


def test_a_driver_with_only_empty_sessions_can_be_deleted_and_they_are_kept(c: sqlite3.Connection) -> None:
    keep = repo.insert_driver(c, "Keep", {})
    gone = repo.insert_driver(c, "Gone", {})
    owner = repo.insert_driver(c, "Owner", {})
    _session(c, "menu", 1.0, gone)
    _session(c, "driven", 2.0, owner)
    repo.insert_lap(c, "driven", _lap(2, 23_222, 1393), None)
    c.commit()
    assert repo.count_driver_sessions(c, gone) == 0 and repo.driver_stats(c)[gone]["sessions"] == 0
    assert repo.delete_driver(c, gone) == 0
    assert repo.get_session(c, "menu")["driver_id"] is None  # type: ignore[index]  # kept, nobody's driving
    with pytest.raises(ValueError, match="still owns 1 session"):
        repo.delete_driver(c, owner)
    assert repo.get_driver(c, keep) is not None


def test_a_lap_without_a_trace_keeps_its_time_and_has_no_trace(c: sqlite3.Connection) -> None:
    d = repo.insert_driver(c, "Driver", {})
    _session(c, "s", 1.0, d)
    timed: list[LapTrace] = []
    asm = LapAssembler(timed.append)
    for k in range(5):  # driven, never placed on the track (no lap distance)
        asm.feed(CarFrame(game=Game.GT7, t_recv_ns=k, session_time_s=k / 60, lap_number=1, speed_kph=100.0))
    asm.feed_completion(
        LapCompletion(game=Game.GT7, t_recv_ns=9, lap_number=1, lap_time_ms=125_838, untraced=True, race_start=True)
    )
    (lap,) = timed
    assert lap.n == 0 and not lap.clean and lap.flags == {LapFlag.INCOMPLETE, LapFlag.NO_TRACE, LapFlag.RACE_START}
    lap_id = repo.insert_lap(c, "s", lap, None)
    repo.end_session(c, "s", None)
    c.commit()
    (row,) = repo.list_laps(c, "s")
    assert (row["lap_time_ms"], row["n_samples"], row["clean"]) == (125_838, 0, False)
    assert repo.load_lap_trace(c, lap_id) is None  # every trace reader treats it as missing
    assert [r["id"] for r in repo.list_sessions(c)] == ["s"]  # a timed lap: not an empty session


def test_a_completion_never_replaces_a_lap_with_a_trace() -> None:
    """Only a lap the adapter says it never placed, that this assembler saw driven and never built, is stored without a
    trace: a late or repeated completion of a lap with a trace stays a pending completion, as before."""
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append)
    for k in range(10):
        asm.feed(CarFrame(game=Game.GT7, t_recv_ns=k, session_time_s=k / 60, lap_number=2, lap_distance_m=10.0 * k))
    asm.feed_completion(LapCompletion(game=Game.GT7, t_recv_ns=10, lap_number=2, lap_time_ms=23_222))
    asm.feed_completion(LapCompletion(game=Game.GT7, t_recv_ns=11, lap_number=2, lap_time_ms=23_222, untraced=True))
    assert [lap.n for lap in laps] == [10]
    # untraced=None (every other game): no trace-less lap, whatever the frames
    other: list[LapTrace] = []
    asm = LapAssembler(other.append)
    asm.feed(CarFrame(game=Game.FORZA_MOTORSPORT, t_recv_ns=0, session_time_s=0.0, lap_number=1))
    asm.feed_completion(LapCompletion(game=Game.FORZA_MOTORSPORT, t_recv_ns=1, lap_number=1, lap_time_ms=90_000))
    assert other == []
