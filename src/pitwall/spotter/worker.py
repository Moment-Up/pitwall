"""Runs the spotter off the ingest thread (spec section 4).

* ``submit(item)`` (ingest thread): ``queue.SimpleQueue.put`` only - a C call that never blocks and never decodes.
  The UDP thread's whole spotter cost is the ``FieldMotion`` object the adapter built and this one put.
  ``reset(session_id)`` queues a session change behind the items already submitted.
* The worker thread wakes on every item (``SimpleQueue.get``; the strategy worker's 20 ms polling would be too slow),
  decodes every car (``spotter.geometry``), runs the pure ``SpotterEngine`` on the game clock and publishes the live
  snapshot's ``spotter`` block (``LiveState.spotter``: one attribute swap per Motion item; it does NOT bump
  ``LiveState.version``: frames already bump it at the same rate, and two threads incrementing it would race).
* Its calls go to ``sink`` (the radio hub's ``_on_spotter_threadsafe``: ``loop.call_soon_threadsafe``), unless
  ``publish_calls`` is off (max-speed replays: nobody is driving). Sink errors are counted and never stop the worker.
* No Motion for ``STALE_S`` (receive time; Motion is sent only while the player is in control): the engine forgets
  the traffic and says nothing ("stale").
* Backlog: when more than ``BACKLOG`` items wait (0.5 s at 60 Hz: the thread was starved), only the newest Motion is
  kept (session info and events stay, in order), the debounce timers restart (a call is never made on stale data)
  and the skipped items are counted.
* ``apply_settings`` and ``set_ear_latency`` are attribute swaps; the thread picks them up at its next item.
* ``start=False`` (tests, ``scripts/spotter_check.py``): ``process_pending`` runs the same steps on the caller's
  thread.
"""

from __future__ import annotations

import dataclasses
import logging
import queue
import threading
import time
from collections import Counter, deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pitwall.compat import recv_clock_ns
from pitwall.model.telemetry import FieldMotion, GameEvent, SessionInfo
from pitwall.spotter.engine import PARAMS, SpotterEngine, SpotterParams
from pitwall.spotter.geometry import decode
from pitwall.spotter.model import SpotterCall, SpotterState
from pitwall.spotter.settings import DEFAULTS, SpotterSettings
from pitwall.spotter.stats import Ring

if TYPE_CHECKING:
    from pitwall.core.live import LiveState

log = logging.getLogger(__name__)

STALE_S = 0.25
BACKLOG = 30
WARN_EVERY_S = 60.0
CHATTER_WINDOW_S = 60.0
CHATTER_CALLS = 30  # more calls than this in a minute: one INFO line for diagnosis (never auto-muted)
MAX_PLAUSIBLE_DECIDE_NS = 5_000_000_000  # a replay's capture clock is not this process's: such stamps are ignored
RECENT = 20

SpotterSink = Callable[[SpotterCall], None]


@dataclasses.dataclass(slots=True, frozen=True)
class _Reset:
    session_id: str | None


_STOP = object()


class SpotterWorker:
    def __init__(
        self,
        live: LiveState | None = None,
        settings: SpotterSettings = DEFAULTS,
        *,
        sink: SpotterSink | None = None,
        publish_calls: bool = True,
        start: bool = True,
        params: SpotterParams = PARAMS,
        clock_ns: Callable[[], int] = recv_clock_ns,
        name: str = "spotter",
    ) -> None:
        self.live = live
        self.settings = settings
        self.sink = sink
        self.publish_calls = publish_calls
        self.engine = SpotterEngine(settings, params)
        self._clock = clock_ns
        self._ear_latency_s: float | None = None
        self._q: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self.session_id: str | None = None
        self.motion_seen = False
        # counters (worker thread writes, readers copy)
        self.items = 0
        self.skipped = 0
        self.invalid = 0
        self.errors = 0
        self.calls: Counter[str] = Counter()
        self.decide_ms = Ring()
        self.onset_game_ms = Ring()
        self.data_age_ms = Ring()
        self.recent: deque[dict[str, Any]] = deque(maxlen=RECENT)
        self._call_times: deque[float] = deque()
        self._last_backlog_warn = -1e9
        self._last_chatter_log = -1e9
        self._thread: threading.Thread | None = None
        if start:
            self._thread = threading.Thread(target=self._run, name=name, daemon=True)
            self._thread.start()

    # ------------------------------------------------------------------ any thread
    def submit(self, item: FieldMotion | SessionInfo | GameEvent) -> bool:
        """Ingest thread: one C-level queue put. Never blocks, never raises."""
        self._q.put(item)
        return True

    def reset(self, session_id: str | None) -> None:
        """A new pitwall session (``session_id``) or none: queued behind what was submitted."""
        self._q.put(_Reset(session_id))

    def apply_settings(self, settings: SpotterSettings) -> None:
        self.settings = settings

    def set_ear_latency(self, seconds: float) -> None:
        """The radio hub's measured fire -> heard latency (short-overlap suppression)."""
        self._ear_latency_s = seconds

    def state(self) -> SpotterState:
        """The engine's latest state (immutable; the radio hub's validity checks)."""
        return self.engine.state_obj

    @property
    def pending(self) -> int:
        return self._q.qsize()

    def status(self) -> dict[str, Any]:
        e = self.engine
        if not self.settings.enabled:
            reason: str | None = "disabled"  # the switch is read at once, before the next Motion item
        elif not self.motion_seen:
            reason = "not_available"
        else:
            reason = e.reason
        return {
            "active": e.active and self.settings.enabled,
            "reason": reason,
            "motion_hz": None if e.motion_hz is None else round(e.motion_hz, 1),
            "send_rate_low": e.send_rate_low,
            "dims": e.dims.to_dict(),
            "ear_latency_s": round(e.ear_latency_s, 3),
        }

    def counters(self) -> dict[str, Any]:
        return {
            "calls": dict(self.calls),
            "suppressed_short": self.engine.suppressed_short,
            "items": self.items,
            "skipped": self.skipped,
            "invalid": self.invalid + self.engine.invalid,
            "errors": self.errors,
        }

    def latency(self) -> dict[str, Any]:
        return {
            "decide_ms": self.decide_ms.summary(2),
            "onset_game_ms": self.onset_game_ms.summary(0),
            "data_age_ms": self.data_age_ms.summary(0),
        }

    def close(self, timeout: float = 5.0) -> None:
        """Stop the thread (a sentinel, then join). Idempotent."""
        th = self._thread
        if th is None:
            return
        self._q.put(_STOP)
        th.join(timeout)
        self._thread = None

    def process_pending(self) -> None:
        """Drain the queue on the calling thread (``start=False`` workers)."""
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                return
            if item is not _STOP:
                self._handle(item)

    # ------------------------------------------------------------------ worker thread
    def _run(self) -> None:
        while True:
            try:
                item = self._q.get(timeout=STALE_S)
            except queue.Empty:
                self._stale()
                continue
            if item is _STOP:
                return
            if self._q.qsize() > BACKLOG:
                for it in self._drain(item):
                    if it is _STOP:
                        return
                    self._handle(it)
                continue
            self._handle(item)

    def _drain(self, first: Any) -> list[Any]:
        """Everything queued, with every Motion but the newest dropped (order otherwise kept)."""
        items = [first]
        while True:
            try:
                items.append(self._q.get_nowait())
            except queue.Empty:
                break
        last_motion = max((i for i, it in enumerate(items) if isinstance(it, FieldMotion)), default=-1)
        kept = [it for i, it in enumerate(items) if not isinstance(it, FieldMotion) or i == last_motion]
        dropped = len(items) - len(kept)
        self.skipped += dropped
        self.engine.mark_stale()  # restart the debounce timers: never call on stale data
        now = time.monotonic()
        if now - self._last_backlog_warn >= WARN_EVERY_S:
            self._last_backlog_warn = now
            log.warning("spotter: %d motion packets skipped (worker behind; %d skipped so far)", dropped, self.skipped)
        return kept

    def _handle(self, item: Any) -> None:
        try:
            if isinstance(item, FieldMotion):
                self._motion(item)
            elif isinstance(item, SessionInfo):
                self.engine.feed_session(item)
            elif isinstance(item, GameEvent):
                self.engine.feed_event(item.kind, item.session_time_s)
                self._publish()
            elif isinstance(item, _Reset):
                self.session_id = item.session_id
                self.motion_seen = False
                self.engine.reset()
                if self.live is not None:
                    self.live.spotter = None  # no F1 Motion in this session yet
        except Exception:
            self.errors += 1
            log.exception("spotter item failed")

    def _sync(self) -> None:
        e = self.engine
        if self.settings is not e.settings:
            e.apply_settings(self.settings)
        ear = self._ear_latency_s
        if ear is not None:
            self._ear_latency_s = None
            e.set_ear_latency(ear)

    def _motion(self, fm: FieldMotion) -> None:
        self.items += 1
        self._sync()
        m = decode(fm)
        if m is None:
            self.invalid += 1
            return
        self.motion_seen = True
        live = self.live
        red = False
        if live is not None:
            st = live.session_state
            red = st is not None and st.state == "red_flag"
        calls = self.engine.feed_motion(m, self._clock(), red_flag=red)
        age = self.engine.data_age_ms
        if age is not None and self.engine.active:
            self.data_age_ms.add(age)
        self._publish()
        if calls:
            self._hand_out(calls)

    def _hand_out(self, calls: list[SpotterCall]) -> None:
        t1 = self._clock()
        wall = time.time()
        for c in calls:
            call = dataclasses.replace(c, t_decided_ns=t1, origin=self)
            self.calls[call.kind] += 1
            dt = t1 - call.t_recv_ns
            if 0 <= dt <= MAX_PLAUSIBLE_DECIDE_NS:
                self.decide_ms.add(dt / 1e6)
            if call.onset_game_ms is not None:
                self.onset_game_ms.add(call.onset_game_ms)
            self.recent.appendleft({"t_unix": wall, "kind": call.kind, "side": call.side, "seq": call.seq})
            self._chatter(wall)
            sink = self.sink
            if self.publish_calls and sink is not None:
                try:
                    sink(call)
                except Exception:
                    self.errors += 1
                    log.exception("spotter sink failed")

    def _chatter(self, now: float) -> None:
        times = self._call_times
        times.append(now)
        while times and now - times[0] > CHATTER_WINDOW_S:
            times.popleft()
        if len(times) > CHATTER_CALLS and now - self._last_chatter_log >= CHATTER_WINDOW_S:
            self._last_chatter_log = now
            log.info("spotter: %d calls in the last minute (busy traffic; not muted)", len(times))

    def _publish(self) -> None:
        live = self.live
        if live is not None and self.motion_seen:
            live.spotter = self.engine.view_dict  # one attribute swap of an immutable-by-convention dict

    def _stale(self) -> None:
        e = self.engine
        if not self.motion_seen or (e.reason == "stale" and not e.active):
            return
        try:
            e.mark_stale()
            self._publish()
        except Exception:
            self.errors += 1
            log.exception("spotter stale check failed")
