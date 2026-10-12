"""Runs the car health engines off the ingest thread (the same mechanics as ``strategy.worker.StrategyWorker``).

* ``submit(session_id, item)`` (ingest thread): one lock-free deque append, never blocks, never raises. When
  ``max_queue`` items wait, the newest is dropped and counted (``dropped``). ``block_when_full`` (replays only, never
  the UDP thread) waits for room instead.
* ``wants_field``: a plain bool the ingest thread reads before handing a field sample over (one attribute load); True
  only while the live session is an F1 race, so other sessions never queue the field's 200 samples a second.
* The worker thread keeps one ``CarHealthEngine`` per session id (a few at most: one per live input, LRU), and after
  each item hands out what it produced:

  - the views to ``LiveState.set_car_health`` / ``set_racecraft`` at most every ``view_interval_s``, and at once after
    a lap line or a call;
  - each proactive call to ``LiveState.notify("health_call", ...)`` (the radio hub queues it for the scheduler's speak
    windows), unless ``publish_calls`` is off (max-speed replays: nobody is driving).

* ``end_session``: the engine ends and drops every per-car buffer (privacy). Nothing is written to the database.
* ``start=False`` (tests, headless tools): ``process_pending`` runs the same steps on the caller's thread.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pitwall.carhealth.engine import CarHealthEngine
from pitwall.carhealth.settings import DEFAULTS, HealthSettings

if TYPE_CHECKING:
    from pitwall.core.live import LiveState

log = logging.getLogger(__name__)

MAX_QUEUE = 16384  # ~1 min of 60 Hz frames plus a race's field samples: the engine never falls that far behind
VIEW_INTERVAL_S = 1.0
POLL_S = 0.02
BLOCK_POLL_S = 0.001
MAX_ENGINES = 4
HEALTH_CALL_NOTE = "health_call"


class CarHealthWorker:
    def __init__(
        self,
        live: LiveState | None = None,
        *,
        settings: HealthSettings = DEFAULTS,
        publish_calls: bool = True,
        start: bool = True,
        block_when_full: bool = False,
        max_queue: int = MAX_QUEUE,
        view_interval_s: float = VIEW_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.live = live
        self._settings = settings
        self.publish_calls = publish_calls
        self.block_when_full = block_when_full
        self.max_queue = max(1, max_queue)
        self.view_interval_s = max(0.0, view_interval_s)
        self._clock = clock
        self._q: deque[tuple[str, object | None]] = deque()
        self.engines: OrderedDict[str, CarHealthEngine] = OrderedDict()
        self.wants_field = False
        self._last_view: dict[str, float] = {}
        self._dirty: set[str] = set()
        self._stop = threading.Event()
        self._drain = threading.Event()
        self.submitted = 0
        self.dropped = 0
        self.processed = 0
        self.errors = 0
        self.calls = 0
        self.views = 0
        self.busy_s = 0.0  # time spent handling items (the CPU budget check)
        self._thread: threading.Thread | None = None
        if start:
            self._thread = threading.Thread(target=self._run, name="carhealth", daemon=True)
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
        """The session ended (queued behind its items): its per-car buffers go."""
        self._q.append((session_id, None))

    # ------------------------------------------------------------------ settings (any thread)
    @property
    def settings(self) -> HealthSettings:
        return self._settings

    def set_settings(self, s: HealthSettings) -> None:
        """One reference swap; the engines pick it up on their next item (worker thread)."""
        self._settings = s

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
            "views": self.views,
            "engines": len(self.engines),
            "busy_s": round(self.busy_s, 3),
            "wants_field": self.wants_field,
        }

    def process_pending(self) -> None:
        """Drain the queue on the calling thread (``start=False`` workers), then publish the views."""
        while self._q:
            self._handle(*self._q.popleft())
        self._publish(force=True)

    def close(self, timeout: float = 5.0, *, drain: bool = False) -> None:
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
            self._publish()
            if stopping and not self._q:
                self._publish(force=True)
                return
            if not busy:
                self._stop.wait(POLL_S)

    def _engine(self, sid: str) -> CarHealthEngine:
        eng = self.engines.get(sid)
        if eng is None:
            eng = CarHealthEngine(sid, track_model=self._track_model, settings=self._settings)
            self.engines[sid] = eng
            while len(self.engines) > MAX_ENGINES:
                old_sid, old = self.engines.popitem(last=False)
                old.end()
                self._last_view.pop(old_sid, None)
        else:
            self.engines.move_to_end(sid)
        return eng

    def _handle(self, session_id: str, item: object | None) -> None:
        t0 = time.perf_counter()
        try:
            if item is None:
                eng = self.engines.get(session_id)
                if eng is not None:
                    eng.end()
                    self._dirty.add(session_id)
                    self._publish_one(eng, force=True)
                self._update_wants_field()
                return
            eng = self._engine(session_id)
            if eng.settings is not self._settings:
                eng.settings = self._settings
            lines = eng.lines
            eng.feed(item)
            self.processed += 1
            self._dirty.add(session_id)
            calls = eng.take_calls()
            for call in calls:
                self.calls += 1
                live = self.live
                if self.publish_calls and live is not None:
                    live.notify(HEALTH_CALL_NOTE, {**call.to_dict(), "session_id": session_id})
            if calls or eng.lines != lines:
                self._publish_one(eng, force=True)
            self._update_wants_field()
        except Exception:
            self.errors += 1
            if self.errors <= 3 or self.errors % 1000 == 0:
                log.exception("car health worker error (%d)", self.errors)
        finally:
            self.busy_s += time.perf_counter() - t0

    def _update_wants_field(self) -> None:
        live = self.live
        sid = None if live is None else live.session_id
        eng = self.engines.get(sid) if sid is not None else None
        if eng is None and self.engines:
            eng = next(reversed(self.engines.values()))
        self.wants_field = bool(eng is not None and eng.wants_field)

    def _track_model(self) -> Any:
        live = self.live
        return None if live is None else live.track_model

    def _publish(self, force: bool = False) -> None:
        for sid in list(self._dirty):
            eng = self.engines.get(sid)
            if eng is None:
                self._dirty.discard(sid)
                continue
            self._publish_one(eng, force=force)

    def _publish_one(self, eng: CarHealthEngine, force: bool = False) -> None:
        live = self.live
        if live is None:
            self._dirty.discard(eng.session_id)
            return
        now = self._clock()
        sid = eng.session_id
        if not force and now - self._last_view.get(sid, -1e9) < self.view_interval_s:
            return
        self._last_view[sid] = now
        self._dirty.discard(sid)
        if live.session_id != sid:
            return  # not the live session: nothing to show (set_* would drop it anyway)
        try:
            live.set_car_health(sid, eng.view())
            live.set_racecraft(sid, eng.racecraft_view())
            self.views += 1
        except Exception:
            self.errors += 1
            log.exception("car health view failed")
