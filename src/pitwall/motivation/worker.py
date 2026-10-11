"""MotivationWorker: marks goals reached after each live lap and at session end, off every hot path.

It listens to ``LiveState`` notes. ``_on_note`` may run on any thread, including the INGEST thread (the
``event`` note), so it does O(1) work only: no I/O, no locks beyond the queue's, and a full queue drops the item
(the next lap re-evaluates, and every read derives the truth from the laps anyway). The evaluation itself runs on
this worker's own thread (``motivation``) through ``MotivationService``; a goal reached there is flipped exactly
once (``repo.mark_goal_achieved``) and only that flip publishes ``live.notify("motivation", note)``: the
``/ws/live`` stream forwards it to dashboards and the radio hub says one short line.

Race goals are judged when the session ends (``session_ended``). The race's last lap may still be in the analysis
queue at that moment, so an ended session is remembered and judged again on any later lap note of it.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections import OrderedDict
from typing import Any

from pitwall.core.live import LiveState
from pitwall.motivation.service import MotivationService
from pitwall.storage.db import Database, DbWriter

log = logging.getLogger(__name__)

QUEUE_SIZE = 256
ENDED_KEPT = 16
MOTIVATION_NOTE = "motivation"

_Item = tuple[str, str | None, int | None]


class MotivationWorker:
    """Evaluates goals after each live lap / at session end, off every hot path."""

    def __init__(
        self,
        db: Database,
        writer: DbWriter,
        live: LiveState,
        *,
        include_synthetic: bool = False,
        service: MotivationService | None = None,
    ) -> None:
        self.live = live
        self.service = service or MotivationService(db, writer, live=live, include_synthetic=include_synthetic)
        self._q: queue.Queue[_Item | None] = queue.Queue(maxsize=QUEUE_SIZE)
        self.dropped = 0
        self.errors = 0
        self.notes = 0
        self._ended: OrderedDict[str, None] = OrderedDict()  # worker thread only
        self._thread = threading.Thread(target=self._run, name="motivation", daemon=True)
        self._thread.start()
        live.subscribe(self._on_note)

    def _on_note(self, kind: str, payload: dict[str, Any]) -> None:
        """ANY thread, including INGEST: O(1), no I/O."""
        if kind == "lap":
            lap = payload.get("lap")
            lap_id = lap.get("lap_id") if isinstance(lap, dict) else None
            item: _Item = ("lap", self.live.session_id, lap_id if isinstance(lap_id, int) else None)
        elif kind == "event" and payload.get("kind") == "session_ended":
            item = ("end", self.live.session_id, None)
        else:
            return  # including this worker's own "motivation" notes
        if item[1] is None:
            return
        try:
            self._q.put_nowait(item)
        except queue.Full:
            self.dropped += 1  # the next lap re-evaluates; reads always show the derived truth

    def _run(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is None:
                    return
                self._handle(item)
            except Exception:
                self.errors += 1
                log.exception("goal evaluation failed")
            finally:
                self._q.task_done()

    def _handle(self, item: _Item) -> None:
        kind, sid, lap_id = item
        if sid is None:
            return
        notes: list[dict[str, Any]] = []
        if kind == "end":
            self._ended[sid] = None
            while len(self._ended) > ENDED_KEPT:
                self._ended.popitem(last=False)
            note = self.service.on_session_end(sid)
            if note is not None:
                notes.append(note)
        else:
            note = self.service.on_lap(sid, lap_id)
            if note is not None:
                notes.append(note)
            if sid in self._ended:  # the race's last lap arrived after the end
                end_note = self.service.on_session_end(sid)
                if end_note is not None:
                    notes.append(end_note)
        for n in notes:
            self.notes += 1
            log.info("goals reached in session %s: %s", sid, ", ".join(g["title"] for g in n["goals"]))
            self.live.notify(MOTIVATION_NOTE, n)

    def join(self) -> None:
        """Wait until every queued item was evaluated (tests, replays)."""
        self._q.join()

    def close(self) -> None:
        self.live.unsubscribe(self._on_note)
        try:
            self._q.put(None, timeout=5)
        except queue.Full:
            log.warning("motivation queue full at shutdown")
        self._thread.join(10)
