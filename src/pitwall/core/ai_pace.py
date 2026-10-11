"""Pace vs AI difficulty: the ingest-side collector and the analysis-worker processor.

``AiPaceCollector`` holds the in-memory inputs of one *game* session (the game's session UID): every car's latest lap
list (``CarLapHistory``), the aiDifficulty readings, weather, safety car and red flag periods and flashbacks. It runs on
the ingest thread, so every method is O(1) (a ``job`` copy is bounded by the number of cars) and it never does I/O.
The session manager hands an ``AiPaceJob`` snapshot to the ``AnalysisWorker`` after every lap of the player and once
when the session ends; ``AiPaceProcessor`` (analysis thread) summarises it (``analysis.ai_pace``), stores the
``session_ai_pace`` row through the writer and publishes ``snapshot.ai_pace`` while the session is live.

The collector is reset only when the game session UID changes, not when a pitwall session ends: a driver change splits
one game session into two pitwall sessions, and both see the same AI field.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pitwall.analysis.ai_pace import (
    DIFFICULTY_UNKNOWN,
    AiPaceJob,
    AiPaceSummary,
    ScPeriod,
    resolve_difficulty,
    summarise,
    weather_class,
)
from pitwall.core.live import LiveState
from pitwall.model.telemetry import CarLapHistory, EventKind, GameEvent, SessionInfo, SessionType
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

__all__ = [
    "UNCHANGED",
    "AiPaceCollector",
    "AiPaceJob",
    "AiPaceProcessor",
    "BackfillResult",
    "ScPeriod",
    "backfill",
    "collect_capture",
]

log = logging.getLogger(__name__)

SC_ACTIVE = frozenset({"full", "virtual", "formation_lap"})  # SessionInfo.safety_car_status that opens a period
SC_NONE = "none"


class _Unchanged(Enum):
    UNCHANGED = "unchanged"


UNCHANGED = _Unchanged.UNCHANGED  # ``on_info``: the resolved difficulty did not change


class AiPaceCollector:
    """In-memory AI pace inputs of one game session (ingest thread; O(1) per item, no I/O)."""

    def __init__(self) -> None:
        self.reset(None)

    def reset(self, game_uid: str | None) -> None:
        self.game_uid = game_uid
        self.run_id = uuid.uuid4().hex[:12]
        self.histories: dict[int, CarLapHistory] = {}
        self.diff_counts: Counter[int] = Counter()
        self.diff_unknown = 0  # Session packets without a usable aiDifficulty (unfilled tail, out of range)
        self.weather: set[str] = set()
        self.sc_open: tuple[float | None, int] | None = None  # (session time, receive ns) of an open period
        self.sc_periods: list[ScPeriod] = []
        self.red_open: tuple[float | None, int] | None = None  # a red flag not yet followed by lights out
        self.red_flags: list[ScPeriod] = []
        self.flashbacks: list[tuple[float, float]] = []
        self.session_type: str = SessionType.UNKNOWN.value
        self.car_class: str | None = None
        self.network_game: bool | None = None
        self._resolved: tuple[int | None, str] = (None, DIFFICULTY_UNKNOWN)

    # ------------------------------------------------------------------ inputs
    @property
    def difficulty(self) -> tuple[int | None, str]:
        """``(level, status)`` resolved from the readings so far (``analysis.ai_pace.resolve_difficulty``)."""
        return self._resolved

    @property
    def has_data(self) -> bool:
        """Whether this game session gave anything to summarise (non-F1 games never do)."""
        return bool(self.histories) or bool(self.diff_counts)

    def on_info(self, info: SessionInfo) -> int | Literal[_Unchanged.UNCHANGED] | None:
        """Count the difficulty, note weather / safety car / context. Returns the resolved difficulty when the
        resolution (level or status) changed with this packet, else ``UNCHANGED``."""
        if info.ai_difficulty is not None:
            self.diff_counts[info.ai_difficulty] += 1
        else:
            self.diff_unknown += 1
        if info.weather.condition:
            self.weather.add(info.weather.condition)
        sc = info.safety_car_status
        if sc in SC_ACTIVE and self.sc_open is None:
            self.sc_open = (info.session_time_s, info.t_recv_ns)
        elif sc == SC_NONE and self.sc_open is not None:
            start_s, start_ns = self.sc_open
            self.sc_periods.append(ScPeriod(start_s, start_ns, info.session_time_s, info.t_recv_ns))
            self.sc_open = None
        self.session_type = info.session_type.value
        if info.formula is not None:
            self.car_class = info.formula
        if info.network_game is not None:
            self.network_game = info.network_game
        if info.ai_difficulty is None:
            return UNCHANGED  # the resolution only moves with a known reading
        resolved = resolve_difficulty(self.diff_counts)
        if resolved == self._resolved:
            return UNCHANGED
        self._resolved = resolved
        return resolved[0]

    def on_history(self, h: CarLapHistory) -> None:
        if h.session_uid is not None and h.session_uid == self.game_uid:
            self.histories[h.car_index] = h  # immutable: the latest lap list of that car

    def on_flashback(self, e: GameEvent) -> None:
        target = e.payload.get("flashbackSessionTime")
        if isinstance(target, int | float) and e.session_time_s is not None:
            self.flashbacks.append((float(target), float(e.session_time_s)))

    def on_event(self, e: GameEvent) -> None:
        """Flashbacks, and red flag periods: from the red flag to the next lights out (the restart's standing start);
        a red flag never followed by lights out stays open, so every later lap is left out."""
        if e.kind == EventKind.FLASHBACK:
            self.on_flashback(e)
        elif e.kind == EventKind.RED_FLAG and self.red_open is None:
            self.red_open = (e.session_time_s, e.t_recv_ns)
        elif e.kind == EventKind.LIGHTS_OUT and self.red_open is not None:
            start_s, start_ns = self.red_open
            self.red_flags.append(ScPeriod(start_s, start_ns, e.session_time_s, e.t_recv_ns))
            self.red_open = None

    # ------------------------------------------------------------------ output
    def job(self, session_id: str, *, synthetic: bool, final: bool) -> AiPaceJob:
        periods = list(self.sc_periods)
        if self.sc_open is not None:
            periods.append(ScPeriod(self.sc_open[0], self.sc_open[1]))
        reds = list(self.red_flags)
        if self.red_open is not None:
            reds.append(ScPeriod(self.red_open[0], self.red_open[1]))
        level, status = self._resolved
        return AiPaceJob(
            session_id=session_id,
            histories=tuple(self.histories.values()),
            sc_periods=tuple(periods),
            red_flags=tuple(reds),
            flashbacks=tuple(self.flashbacks),
            ai_difficulty=level,
            difficulty_status=status,
            session_type=self.session_type,
            car_class=self.car_class,
            weather_class=weather_class(self.weather),
            network_game=self.network_game,
            run_id=self.run_id,
            synthetic=synthetic,
            final=final,
        )


class AiPaceProcessor:
    """Analysis thread: ``AiPaceJob`` -> summary -> ``session_ai_pace`` row (writer) and ``snapshot.ai_pace``."""

    def __init__(self, db: Database, writer: DbWriter, live: LiveState | None = None) -> None:
        self.db = db
        self.writer = writer
        self.live = live
        self.processed = 0

    def process(self, job: AiPaceJob) -> AiPaceSummary:
        sid = job.session_id
        with self.db.read() as c:
            laps = repo.session_lap_times(c, sid)
        summary = summarise(job, laps)
        row = summary.row()
        self.writer.submit(lambda c: repo.upsert_session_ai_pace(c, sid, row))
        live = self.live
        if live is not None and live.session_id == sid:
            live.set_ai_pace(sid, summary.live_payload())
        self.processed += 1
        log.debug(
            "AI pace %s: %s (difficulty %s, %d AI cars, gap %s ms)",
            sid,
            summary.status,
            summary.ai_difficulty,
            summary.ai_cars,
            summary.gap_ms,
        )
        return summary


# ---------------------------------------------------------------------------------------------- backfill (P2 CLI)
@dataclass(slots=True)
class BackfillResult:
    capture: str
    game_session_uid: str
    session_id: str
    status: str
    ai_difficulty: int | None
    ai_cars: int
    gap_ms: int | None
    written: bool


def collect_capture(path: Path) -> list[AiPaceJob]:
    """Decode one capture (F1 only, field model off) into one AI pace job per game session it contains (the job's
    ``session_id`` is the game session UID). A game session's collection stops at its ``SEND`` event; Session
    History of another session never starts one. Synthetic captures give nothing (they never feed AI statistics)."""
    from pitwall.adapters.base import PacketRejected
    from pitwall.adapters.f1.adapter import F1Adapter
    from pitwall.ingest.capture import CaptureReader

    reader = CaptureReader(path)
    if reader.meta.synthetic:
        return []
    adapter = F1Adapter(field_hz=0)
    jobs: list[AiPaceJob] = []
    col: AiPaceCollector | None = None
    ended: str | None = None  # UID of a game session that sent SEND: ignored until another session starts

    def finish() -> None:
        nonlocal col
        if col is not None and col.game_uid and col.has_data:
            jobs.append(col.job(col.game_uid, synthetic=False, final=True))
        col = None

    for pkt in reader:
        if not adapter.can_decode(pkt.data):
            continue
        try:
            items = adapter.decode(pkt.data, pkt.t_recv_ns)
        except PacketRejected:
            continue
        for e in items:
            if isinstance(e, SessionInfo) and e.session_uid:
                if e.session_uid == ended:
                    continue
                ended = None
                if col is None or col.game_uid != e.session_uid:
                    finish()
                    col = AiPaceCollector()
                    col.reset(e.session_uid)
                col.on_info(e)
            elif col is None:
                continue
            elif isinstance(e, CarLapHistory):
                col.on_history(e)
            elif isinstance(e, GameEvent) and e.kind == EventKind.SESSION_ENDED:
                ended = col.game_uid
                finish()
            elif isinstance(e, GameEvent):
                col.on_event(e)
    finish()
    return jobs


def backfill(db: Database, writer: DbWriter, captures: list[Path], *, dry_run: bool = False) -> list[BackfillResult]:
    """Fill ``session_ai_pace`` (and a missing ``sessions.ai_difficulty``) of existing real sessions from the raw
    captures they were recorded from, matched by the game session UID. Never creates a session; synthetic sessions
    are never touched. The upsert guard keeps a stored row that is based on more AI laps."""
    out: list[BackfillResult] = []
    for path in captures:
        for job in collect_capture(path):
            uid = job.session_id
            with db.read() as c:
                sessions = repo.sessions_for_game_uid(c, uid)
                laps = {s["id"]: repo.session_lap_times(c, s["id"]) for s in sessions}
            for s in sessions:
                sid = str(s["id"])
                summary = summarise(replace(job, session_id=sid), laps[sid])
                written = False
                if not dry_run:
                    row = summary.row()
                    level = summary.ai_difficulty

                    def store(
                        c: sqlite3.Connection, sid: str = sid, row: dict[str, Any] = row, level: int | None = level
                    ) -> bool:
                        if level is not None:
                            repo.set_session_ai_difficulty_if_unknown(c, sid, level)
                        return repo.upsert_session_ai_pace(c, sid, row)

                    written = writer.call(store)
                out.append(
                    BackfillResult(
                        capture=path.name,
                        game_session_uid=uid,
                        session_id=sid,
                        status=summary.status,
                        ai_difficulty=summary.ai_difficulty,
                        ai_cars=summary.ai_cars,
                        gap_ms=summary.gap_ms,
                        written=written,
                    )
                )
    return out
