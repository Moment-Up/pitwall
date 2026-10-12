"""Race radio worker (raceradio.worker): off the ingest thread, notes to the radio, the live view."""

from __future__ import annotations

import time
from typing import Any

from pitwall.core.live import LiveState
from pitwall.raceradio.worker import RACE_CALL_NOTE, RaceRadioWorker
from pitwall.voice.urgent import URGENT_NOTE
from tests.unit.raceradio_helpers import event, frame, info


class Notes:
    def __init__(self, live: LiveState) -> None:
        self.got: list[tuple[str, dict[str, Any]]] = []
        live.subscribe(lambda kind, payload: self.got.append((kind, payload)))

    def kinds(self) -> list[str]:
        return [k for k, _p in self.got if k in (RACE_CALL_NOTE, URGENT_NOTE)]


def live_for(sid: str) -> LiveState:
    live = LiveState()
    live.reset_session(sid, "test", False, "f1_25")
    return live


def test_submit_is_a_deque_append_and_drops_when_full() -> None:
    w = RaceRadioWorker(None, start=False, max_queue=3)
    assert all(w.submit("s1", frame(i)) for i in range(3))
    assert not w.submit("s1", frame(4.0)) and w.dropped == 1 and w.pending == 3
    t0 = time.perf_counter()
    for i in range(10_000):
        w.submit("s1", i)
    assert time.perf_counter() - t0 < 0.5  # O(1): no work on the caller's thread


def test_calls_become_notes_and_the_view_is_published() -> None:
    live = live_for("s1")
    notes = Notes(live)
    w = RaceRadioWorker(live, start=False)
    for item in (info(0.0), *[frame(i / 10) for i in range(20)], *[frame(2 + i / 10, fia="blue") for i in range(10)]):
        w.submit("s1", item)
    w.process_pending()
    assert notes.kinds() == [RACE_CALL_NOTE]
    payload = notes.got[-1][1]
    assert payload["call"] == "blue_flag" and payload["session_id"] == "s1"
    assert live.race is not None and live.race["calls"][0]["call"] == "blue_flag"
    w.submit("s1", event(5.0, "RDFL"))
    w.process_pending()
    assert notes.kinds() == [RACE_CALL_NOTE, URGENT_NOTE]
    urgent = notes.got[-1][1]
    assert urgent["source"] == "raceradio" and isinstance(urgent["t_mono"], float) and urgent["ttl_s"] == 15.0
    assert w.stats()["urgent"] == 1 and w.stats()["calls"] == 2


def test_a_new_session_starts_a_fresh_engine_and_stale_views_are_dropped() -> None:
    live = live_for("s2")
    w = RaceRadioWorker(live, start=False)
    w.submit("s1", info(0.0))
    w.submit("s1", frame(0.1))
    w.process_pending()
    assert live.race is None  # s1 is not the live session any more
    w.submit("s2", info(1.0))
    w.process_pending()
    assert w.engine is not None and w.engine.session_id == "s2" and live.race is not None
    w.end_session("s2")
    w.process_pending()
    assert w.engine.ended


def test_no_notes_from_a_max_speed_replay() -> None:
    live = live_for("s1")
    notes = Notes(live)
    w = RaceRadioWorker(live, start=False, publish_calls=False)
    for item in (info(0.0), *[frame(i / 10, fia="blue") for i in range(20)], event(3.0, "RDFL")):
        w.submit("s1", item)
    w.process_pending()
    assert notes.kinds() == [] and w.calls == 2 and live.race is not None


def test_view_rate_and_errors_never_escape() -> None:
    live = live_for("s1")
    clock = [0.0]
    w = RaceRadioWorker(live, start=False, view_interval_s=0.5, clock=lambda: clock[0])
    sets: list[float] = []
    original = live.set_race

    def counted(sid: str, view: dict[str, Any] | None) -> None:
        sets.append(clock[0])
        original(sid, view)

    live.set_race = counted  # type: ignore[method-assign]
    w.submit("s1", info(0.0))
    for i in range(50):
        clock[0] = i * 0.05
        w._handle("s1", frame(i * 0.05))
        w._publish_view()
    assert 4 <= len(sets) <= 7  # every 0.5 s over 2.5 s (plus the first)
    w._handle("s1", object())  # not an item: ignored, never raises
    assert w.errors == 0


def test_thread_mode_drains_on_close() -> None:
    live = live_for("s1")
    notes = Notes(live)
    w = RaceRadioWorker(live)
    for item in (info(0.0), *[frame(i / 10, fia="blue") for i in range(20)]):
        w.submit("s1", item)
    w.close(drain=True)
    assert notes.kinds() == [RACE_CALL_NOTE] and w.processed == 21
