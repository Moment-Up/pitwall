"""The car health worker (``carhealth.worker``): O(1) submits that never raise and drop when full, one engine per
session, the publish cadence, ``wants_field`` only in F1 races, calls to the live notifications, settings swaps, the
session manager's routing hooks."""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Any, cast

from pitwall.carhealth.settings import HealthSettings
from pitwall.carhealth.worker import HEALTH_CALL_NOTE, CarHealthWorker
from pitwall.core.lap_processor import AnalysisWorker
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.model.telemetry import EventKind, Game, GameEvent, SessionType
from pitwall.storage.db import DbWriter
from tests.unit.carhealth_helpers import drive, field_sample, frame, info
from tests.unit.strategy_helpers import car, timing


class FakeWriter:
    def submit(self, *a: Any, **k: Any) -> None:
        pass


def test_submit_is_constant_time_and_drops_when_full() -> None:
    w = CarHealthWorker(start=False, max_queue=3)
    assert all(w.submit("s", frame(float(k))) for k in range(3))
    assert w.submit("s", frame(4.0)) is False and w.dropped == 1 and w.submitted == 3
    w.process_pending()
    assert w.pending == 0 and w.processed == 3 and w.errors == 0


def test_a_bad_item_never_raises() -> None:
    w = CarHealthWorker(start=False)
    w.submit("s", object())
    w.submit("s", None)  # type: ignore[arg-type]
    w.process_pending()
    assert w.errors == 0


def test_one_engine_per_session_and_views_for_the_live_one() -> None:
    live = LiveState()
    live.reset_session("s1", "test", False, "f1_25")
    w = CarHealthWorker(live, start=False)
    w.submit("s1", info())
    w.submit("s2", info())
    for k in range(20):
        w.submit("s1", frame(float(k)))
    w.process_pending()
    assert set(w.engines) == {"s1", "s2"}
    snap = live.snapshot()
    assert snap["car_health"]["session_id"] == "s1" and snap["racecraft"]["session_id"] == "s1"
    live.reset_session("s3", "test", False, "f1_25")
    assert live.snapshot()["car_health"] is None  # a new session starts without the old blocks


def test_publish_cadence_and_at_once_after_a_line() -> None:
    live = LiveState()
    live.reset_session("s", "test", False, "f1_25")
    clock = [0.0]
    w = CarHealthWorker(live, start=False, clock=lambda: clock[0])
    w.submit("s", info())
    w.process_pending()
    views = w.views
    for k in range(10):
        w._handle("s", frame(1.0 + k / 10))
    w._publish()
    assert w.views == views  # within the second: nothing new
    clock[0] = 5.0
    w._publish()
    assert w.views == views + 1
    w._handle("s", frame(3.0, lap=3, d=5.0))  # the line: published at once
    assert w.views == views + 2


def test_wants_field_only_in_f1_races() -> None:
    live = LiveState()
    live.reset_session("s", "test", False, "f1_25")
    w = CarHealthWorker(live, start=False)
    w.submit("s", info(session_type=SessionType.QUALIFYING))
    w.process_pending()
    assert w.wants_field is False
    w.submit("s", info())
    w.process_pending()
    assert w.wants_field is True
    w.end_session("s")
    w.process_pending()
    assert w.wants_field is False


def test_calls_go_to_the_live_notifications_unless_switched_off() -> None:
    live = LiveState()
    live.reset_session("s", "test", False, "f1_25")
    notes: list[tuple[str, dict[str, Any]]] = []
    live.subscribe(lambda k, p: notes.append((k, p)))
    w = CarHealthWorker(live, start=False)
    w.submit("s", info())
    t = 0.0
    eng_items = []
    # a stint, a stop and new cold tyres: one tyres_cold call
    for k in range(1000):
        eng_items.append(frame(t, inner=90.0, lap=2, d=k))
        t += 0.1
    for k in range(250):
        eng_items.append(frame(t, inner=90.0, pit=1, speed=70.0, lap=2, d=k))
        t += 0.1
    for k in range(60):
        eng_items.append(frame(t, inner=30.0, lap=2, d=k))
        t += 0.1
    for it in eng_items:
        w.submit("s", it)
    w.process_pending()
    calls = [p for k, p in notes if k == HEALTH_CALL_NOTE]
    assert [c["topic"] for c in calls] == ["tyres_cold"] and calls[0]["session_id"] == "s"
    assert live.snapshot()["car_health"]["calls"][0]["topic"] == "tyres_cold"
    quiet = CarHealthWorker(live, start=False, publish_calls=False)
    quiet.submit("s", info())
    for it in eng_items:
        quiet.submit("s", it)
    quiet.process_pending()
    assert quiet.calls == 1 and len([1 for k, _ in notes if k == HEALTH_CALL_NOTE]) == 1


def test_settings_swap_reaches_the_engines() -> None:
    w = CarHealthWorker(start=False)
    w.submit("s", info())
    w.process_pending()
    w.set_settings(HealthSettings(slip_calls="off"))
    w.submit("s", frame(1.0))
    w.process_pending()
    assert w.engines["s"].settings.slip_calls == "off"


def test_a_running_worker_drains_and_stops() -> None:
    live = LiveState()
    live.reset_session("s", "test", False, "f1_25")
    w = CarHealthWorker(live, block_when_full=True, max_queue=50)
    w.submit("s", info())
    for k in range(400):
        w.submit("s", frame(k / 10))
    deadline = time.monotonic() + 5
    while w.pending and time.monotonic() < deadline:
        time.sleep(0.01)
    w.close(drain=True)
    assert w.dropped == 0 and w.processed == 401 and live.snapshot()["car_health"] is not None


class Sink:
    def __init__(self, wants_field: bool) -> None:
        self.wants_field = wants_field
        self.items: list[tuple[str, object]] = []
        self.ended: list[str] = []

    def submit(self, sid: str, item: object) -> bool:
        self.items.append((sid, item))
        return True

    def end_session(self, sid: str) -> None:
        self.ended.append(sid)


def _manager(sink: Sink) -> SessionManager:
    return SessionManager(
        cast(DbWriter, FakeWriter()),
        LiveState(),
        cast(AnalysisWorker, FakeWriter()),
        source="test",
        health=sink,
    )


def test_session_manager_routes_player_items_timing_and_field_only_when_wanted() -> None:
    sink = Sink(wants_field=False)
    m = _manager(sink)
    m.handle(info())
    m.handle(frame(1.0))
    m.handle(GameEvent(kind=EventKind.BUTTON, game=Game.F1_25, t_recv_ns=0, payload={"buttonStatus": 1}))
    m.handle(timing(1.0, [car(1, 1, player=True)]))
    m.handle(field_sample(3, 1.0, 2, 100.0))
    kinds = [type(i).__name__ for _, i in sink.items]
    assert kinds == ["SessionInfo", "CarFrame", "RaceTiming"]  # no button, no field sample
    sink.wants_field = True
    m.handle(field_sample(3, 1.1, 2, 110.0))
    assert type(sink.items[-1][1]).__name__ == "FieldSample"
    m.end()
    assert sink.ended == [sink.items[0][0]]


def test_the_ingest_side_is_one_append() -> None:
    """``submit`` holds no lock and does no work beyond the deque append (the ingest-thread contract)."""
    src = Path(__file__).resolve().parents[2] / "src" / "pitwall" / "carhealth" / "worker.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "submit")
    calls = {n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert calls <= {"append", "is_alive", "sleep", "is_set"}  # sleep: replays only (block_when_full)
    assert not any(isinstance(n, ast.With) for n in ast.walk(fn))


def test_drive_helper_produces_lines() -> None:
    from pitwall.carhealth.engine import CarHealthEngine

    eng = CarHealthEngine("x")
    eng.feed(info())
    drive(eng, 0.0, 130.0, lap_s=60.0)
    assert eng.lines == 2
