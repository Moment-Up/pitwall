"""Runs the race strategy engine off the ingest thread (the same pattern as ``core.track_knowledge.FieldWorker``).

* ``submit(session_id, item)`` (ingest thread): one lock-free deque append, never blocks, never raises. When
  ``max_queue`` items wait, the newest is dropped and counted (``dropped``): back-pressure lands on strategy,
  never on ingest. ``block_when_full`` (replays only, never the UDP thread) waits for room instead.
* The worker thread keeps one ``StrategyEngine`` for the current session (a new session id starts a fresh engine;
  ``end_session`` finishes it), and after each item hands out what the engine produced:

  - the view to ``LiveState.set_strategy`` (snapshot ``strategy``) at most every ``view_interval_s``, and at
    once when a lap record was finished;
  - each proactive call to ``LiveState.notify("strategy_call", ...)`` (the radio hub turns it into a radio message
    for the scheduler's speak windows), unless ``publish_calls`` is off (max-speed replays: nobody is driving);
  - lap records and pit stops to the database writer (``repo.upsert_strategy_lap`` / ``upsert_pit_stop``).

* ``start=False`` (tests, headless tools): ``process_pending`` runs the same steps on the caller's thread.
"""

from __future__ import annotations

import functools
import logging
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pitwall.storage import repo
from pitwall.strategy.engine import StrategyEngine

if TYPE_CHECKING:
    from pitwall.core.live import LiveState
    from pitwall.storage.db import DbWriter

log = logging.getLogger(__name__)

MAX_QUEUE = 16384  # ~4 min of 60 Hz frames plus timing: the engine never falls that far behind in practice
VIEW_INTERVAL_S = 0.5
POLL_S = 0.02
BLOCK_POLL_S = 0.001
STRATEGY_CALL_NOTE = "strategy_call"


def _write_lap(c: sqlite3.Connection, *, session_id: str, lap: int, record: dict[str, Any]) -> None:
    repo.upsert_strategy_lap(c, session_id, lap, record)


def _write_stop(c: sqlite3.Connection, *, session_id: str, stop: dict[str, Any]) -> None:
    repo.upsert_pit_stop(c, session_id, stop)


class StrategyWorker:
    def __init__(
        self,
        live: LiveState | None = None,
        writer: DbWriter | None = None,
        *,
        publish_calls: bool = True,
        start: bool = True,
        block_when_full: bool = False,
        max_queue: int = MAX_QUEUE,
        view_interval_s: float = VIEW_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.live = live
        self.writer = writer
        self.publish_calls = publish_calls
        self.block_when_full = block_when_full
        self.max_queue = max(1, max_queue)
        self.view_interval_s = max(0.0, view_interval_s)
        self._clock = clock
        self._q: deque[tuple[str, object | None]] = deque()
        self.engine: StrategyEngine | None = None
        self._last_view = -1e9
        self._stop = threading.Event()
        self._drain = threading.Event()
        self.submitted = 0
        self.dropped = 0
        self.processed = 0
        self.errors = 0
        self.calls = 0
        self.records = 0
        self.stops = 0
        self._thread: threading.Thread | None = None
        if start:
            self._thread = threading.Thread(target=self._run, name="strategy", daemon=True)
            self._thread.start()

    # ------------------------------------------------------------------ ingest thread
    def submit(self, session_id: str, item: object) -> bool:
        """Queue one item of ``session_id``; False when it was dropped because the worker is behind. O(1)."""
        if len(self._q) >= self.max_queue:
            th = self._thread
            if self.block_when_full and th is not None:
                while len(self._q) >= self.max_queue and th.is_alive() and not self._stop.is_set():
                    time.sleep(BLOCK_POLL_S)
            if len(self._q) >= self.max_queue:
                self.dropped += 1
                return False
        self._q.append((session_id, item))
        self.submitted += 1
        return True

    def end_session(self, session_id: str) -> None:
        """The session ended (queued behind its items): its engine finishes its records and pit stops."""
        self._q.append((session_id, None))

    # ------------------------------------------------------------------ worker
    @property
    def pending(self) -> int:
        return len(self._q)

    def stats(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted,
            "dropped": self.dropped,
            "processed": self.processed,
            "queued": self.pending,
            "errors": self.errors,
            "calls": self.calls,
            "records": self.records,
            "stops": self.stops,
        }

    def process_pending(self) -> None:
        """Drain the queue on the calling thread (``start=False`` workers), then publish the view."""
        while self._q:
            self._handle(*self._q.popleft())
        self._publish_view(force=True)

    def close(self, timeout: float = 5.0, *, drain: bool = False) -> None:
        """Stop the worker. ``drain``: process what is still queued and publish a final view first."""
        if drain:
            self._drain.set()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        elif drain:
            self.process_pending()

    def _run(self) -> None:
        while True:
            stopping = self._stop.is_set()
            if stopping and not self._drain.is_set():
                return
            busy = False
            for _ in range(1024):
                if not self._q:
                    break
                self._handle(*self._q.popleft())
                busy = True
            self._publish_view()
            if stopping and not self._q:
                self._publish_view(force=True)
                return
            if not busy:
                self._stop.wait(POLL_S)

    def _handle(self, session_id: str, item: object | None) -> None:
        try:
            eng = self.engine
            if item is None:
                if eng is not None and eng.session_id == session_id:
                    eng.end()
                    self._drain_engine(eng)
                    self._publish_view(force=True)
                return
            if eng is None or eng.session_id != session_id:
                if eng is not None and not eng.ended:
                    eng.end()
                    self._drain_engine(eng)
                eng = self.engine = StrategyEngine(session_id, track_model=self._track_model)
                self._last_view = -1e9
            eng.feed(item)
            self.processed += 1
            if self._drain_engine(eng):
                self._publish_view(force=True)
        except Exception:
            self.errors += 1
            if self.errors <= 3 or self.errors % 1000 == 0:
                log.exception("strategy worker error (%d)", self.errors)

    def _track_model(self) -> Any:
        live = self.live
        return None if live is None else live.track_model

    def _drain_engine(self, eng: StrategyEngine) -> bool:
        """Hand out the engine's calls, records and stops. True when a lap record was finished."""
        sid = eng.session_id
        live, writer = self.live, self.writer
        for call in eng.take_calls():
            self.calls += 1
            if self.publish_calls and live is not None:
                live.notify(STRATEGY_CALL_NOTE, {**call.to_dict(), "session_id": sid})
        records = eng.take_records()
        for lap, rec in records:
            self.records += 1
            if writer is not None:
                writer.submit(functools.partial(_write_lap, session_id=sid, lap=lap, record=rec))
        for stop in eng.take_stops():
            self.stops += 1
            if writer is not None:
                writer.submit(functools.partial(_write_stop, session_id=sid, stop=stop))
        return bool(records)

    def _publish_view(self, force: bool = False) -> None:
        eng, live = self.engine, self.live
        if eng is None or live is None:
            return
        now = self._clock()
        if not force and now - self._last_view < self.view_interval_s:
            return
        self._last_view = now
        try:
            live.set_strategy(eng.session_id, eng.view())
        except Exception:
            self.errors += 1
            log.exception("strategy view failed")
