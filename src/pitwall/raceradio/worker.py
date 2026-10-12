"""Runs the race radio engine off the ingest thread (the ``strategy.worker.StrategyWorker`` pattern, no DB writes).

* ``submit(session_id, item)`` (ingest thread): one lock-free deque append, never blocks, never raises. When
  ``max_queue`` items wait, the newest is dropped and counted (``dropped``): back-pressure lands on the race radio,
  never on ingest. ``block_when_full`` (replays only, never the UDP thread) waits for room instead.
* The worker thread keeps one ``RaceRadioEngine`` per session (a new session id starts a fresh engine) and after each
  item hands out what it produced:

  - each call to ``LiveState.notify("race_call", RaceCall.to_dict())`` (the radio hub filters it by the seated
    driver's groups and wording and queues it for the scheduler); an urgent call (the red flag) to
    ``LiveState.notify(voice.urgent.URGENT_NOTE, ...)`` instead; after a flashback
    ``LiveState.notify("race_retract", {"session_id", "groups"})`` (the hub drops those groups' unsaid calls); none of
    them when ``publish_calls`` is off (max-speed replays: nobody is driving);
  - the view to ``LiveState.set_race`` (snapshot ``race``) at most every ``view_interval_s``, and at once after a call.

* The formation-lap memo (``countdown.Memo``) outlives the engines: a formation-lap session is a separate game session
  [M], and the race session that follows must not say the grid brief again.
* Engines are kept per session id (the last ``ENGINES_KEPT``): two sources feeding at once (UDP and Assetto Corsa)
  each keep their engine's state instead of rebuilding it on every switch. The view published is the live
  session's engine.
* ``start=False`` (tests, headless tools): ``process_pending`` runs the same steps on the caller's thread.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pitwall.raceradio.countdown import Memo
from pitwall.raceradio.engine import RaceRadioEngine
from pitwall.raceradio.names import NeighbourNames
from pitwall.voice.urgent import URGENT_NOTE

if TYPE_CHECKING:
    from pitwall.core.live import LiveState

log = logging.getLogger(__name__)

MAX_QUEUE = 16384  # ~4 min of 60 Hz frames: the engine never falls that far behind in practice
VIEW_INTERVAL_S = 0.5
POLL_S = 0.02
BLOCK_POLL_S = 0.001
RACE_CALL_NOTE = "race_call"
RACE_RETRACT_NOTE = "race_retract"
ENGINES_KEPT = 2


class RaceRadioWorker:
    def __init__(
        self,
        live: LiveState | None = None,
        *,
        publish_calls: bool = True,
        start: bool = True,
        block_when_full: bool = False,
        max_queue: int = MAX_QUEUE,
        view_interval_s: float = VIEW_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.live = live
        self.publish_calls = publish_calls
        self.block_when_full = block_when_full
        self.max_queue = max(1, max_queue)
        self.view_interval_s = max(0.0, view_interval_s)
        self._clock = clock
        self._q: deque[tuple[str, object | None]] = deque()
        self.engine: RaceRadioEngine | None = None  # the engine of the latest item
        self._engines: OrderedDict[str, RaceRadioEngine] = OrderedDict()  # per session id, the newest last
        self.memo: Memo = {}
        self._last_view = -1e9
        self._stop = threading.Event()
        self._drain = threading.Event()
        self.submitted = 0
        self.dropped = 0
        self.processed = 0
        self.errors = 0
        self.calls = 0
        self.urgent = 0
        self._thread: threading.Thread | None = None
        if start:
            self._thread = threading.Thread(target=self._run, name="raceradio", daemon=True)
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
        """The session ended (queued behind its items)."""
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
            "urgent": self.urgent,
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
            if item is None:
                ended = self._engines.pop(session_id, None)
                if ended is not None:
                    ended.end()
                    self.engine = ended
                    self._publish_view(force=True)
                return
            eng = self._engines.get(session_id)
            if eng is None:
                eng = RaceRadioEngine(session_id, track_model=self._track_model, memo=self.memo)
                self._engines[session_id] = eng
                while len(self._engines) > ENGINES_KEPT:
                    _sid, old = self._engines.popitem(last=False)
                    old.end()
                self._last_view = -1e9
            else:
                self._engines.move_to_end(session_id)
            if eng is not self.engine:
                self.engine = eng
                live = self.live
                if live is not None and self.publish_calls and live.session_id == session_id:
                    live.race_roster = NeighbourNames(eng)  # opt-in answers only (raceradio.names); never stored
            eng.feed(item)
            self.processed += 1
            if self._drain_engine(eng):
                self._publish_view(force=True)
        except Exception:
            self.errors += 1
            if self.errors <= 3 or self.errors % 1000 == 0:
                log.exception("race radio worker error (%d)", self.errors)

    def _track_model(self) -> Any:
        live = self.live
        return None if live is None else live.track_model

    def _drain_engine(self, eng: RaceRadioEngine) -> bool:
        """Hand out the engine's calls (and a flashback's retraction). True when there was a call (the view shows it
        at once)."""
        calls = eng.take_calls()
        live = self.live
        stale = eng.take_retractions()
        if stale and self.publish_calls and live is not None:
            live.notify(RACE_RETRACT_NOTE, {"session_id": eng.session_id, "groups": list(stale)})
        for call in calls:
            self.calls += 1
            if not self.publish_calls or live is None:
                continue
            if call.urgent:
                self.urgent += 1
                live.notify(URGENT_NOTE, call.urgent_payload(time.monotonic()))
            else:
                live.notify(RACE_CALL_NOTE, call.to_dict())
        return bool(calls)

    def _publish_view(self, force: bool = False) -> None:
        live = self.live
        if live is None:
            return
        eng = self._engines.get(live.session_id or "") or self.engine  # the live session's engine first
        if eng is None:
            return
        now = self._clock()
        if not force and now - self._last_view < self.view_interval_s:
            return
        self._last_view = now
        try:
            live.set_race(eng.session_id, eng.view())
        except Exception:
            self.errors += 1
            log.exception("race radio view failed")
