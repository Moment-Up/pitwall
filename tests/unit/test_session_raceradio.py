"""SessionManager routing for the race radio: Participants only ever to the race radio (never a session, the database,
live state or strategy), race timing to both sinks, the player's items to the race sink, button events never."""

from __future__ import annotations

from typing import Any, cast

from pitwall.core.lap_processor import AnalysisWorker
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.model.telemetry import EventKind, Game, GameEvent
from pitwall.storage.db import DbWriter
from tests.unit.raceradio_helpers import car, frame, info, lap_done, participant, participants, timing


class Sink:
    def __init__(self) -> None:
        self.items: list[tuple[str, Any]] = []
        self.ended: list[str] = []

    def submit(self, session_id: str, item: Any) -> bool:
        self.items.append((session_id, item))
        return True

    def end_session(self, session_id: str) -> None:
        self.ended.append(session_id)


class Writer:
    def __init__(self) -> None:
        self.jobs: list[Any] = []

    def submit(self, fn: Any) -> None:
        self.jobs.append(fn)


def manager() -> tuple[SessionManager, Sink, Sink, Writer, LiveState]:
    race, strategy, writer, live = Sink(), Sink(), Writer(), LiveState()
    sm = SessionManager(
        cast(DbWriter, writer),
        live,
        cast(AnalysisWorker, Writer()),
        source="test",
        strategy=strategy,
        race=race,
    )
    return sm, race, strategy, writer, live


def test_participants_never_start_a_session_and_go_to_the_race_radio_only() -> None:
    sm, race, strategy, writer, live = manager()
    table = participants(0.0, [participant(0, name="Zz_Canary")])
    sm.handle(table)
    assert sm.session_id is None and race.items == [] and writer.jobs == []  # no session: nowhere
    sm.handle(info(1.0))
    sid = sm.session_id
    assert sid is not None
    jobs = len(writer.jobs)
    sm.handle(table)
    assert race.items[-1] == (sid, table)
    assert len(writer.jobs) == jobs and all(item is not table for _s, item in strategy.items)
    assert "Zz_Canary" not in repr(live.snapshot(include_static=True))


def test_timing_to_both_sinks_and_the_players_items_to_the_race_radio() -> None:
    sm, race, strategy, _w, _live = manager()
    sm.handle(info(0.0))
    rt = timing(1.0, [car(3, 5)])
    f, lc = frame(1.1), lap_done(1.2, 1)
    flbk = GameEvent(kind=EventKind.FLASHBACK, game=Game.F1_25, t_recv_ns=2, code="FLBK")
    button = GameEvent(kind=EventKind.BUTTON, game=Game.F1_25, t_recv_ns=3, code="BUTN", payload={"buttonStatus": 0})
    for item in (rt, f, lc, flbk, button):
        sm.handle(item)
    got = [item for _s, item in race.items]
    assert rt in got and f in got and lc in got and flbk in got and button not in got
    assert rt in [item for _s, item in strategy.items]
    sid = sm.session_id
    sm.end()
    assert race.ended == [sid]


def test_a_participants_table_before_the_session_reaches_it_when_it_starts() -> None:
    """F1 sends Participants every 5 s, but the adapter emits it only when it changed: a table that came before the
    session's first item must still reach that session (and a split session for a new driver)."""
    sm, race, _strategy, writer, _live = manager()
    table = participants(0.0, [participant(0, name="Zz_Canary")])
    sm.handle(table)  # before any session: kept, not sent, not persisted
    assert race.items == [] and writer.jobs == []
    sm.handle(info(1.0))
    sid = sm.session_id
    assert (sid, table) in race.items
    sm.end()
    sm.handle(info(2.0, uid="43"))  # the next session (a new game session UID)
    assert (sm.session_id, table) in race.items and sm.session_id != sid
