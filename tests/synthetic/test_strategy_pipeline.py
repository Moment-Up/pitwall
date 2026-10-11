"""SYNTHETIC: the race strategy engineer end to end on ``race-strategy-demo`` (``sim/strategy_stream.py``).

Packet-level F1 25 stream with known ground truth (pit stops, a VSC, a rain forecast, a fuel deficit with a known
burn model, an undercut threat) -> decode -> engine; and the same capture replayed through the full runtime ->
SQLite -> API. Proves the algorithms and the plumbing against generated data; it is NOT evidence that the real game
behaves like this (safety car, rain and the player's own stop have no real capture yet).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.model.telemetry import RaceTiming
from pitwall.sim.strategy_stream import PLAYER, StrategyTruth, race_strategy_demo, write_strategy_capture
from pitwall.storage import repo
from pitwall.strategy.engine import StrategyEngine
from pitwall.strategy.radio import strategy_message
from pitwall.strategy.timeline import build_timeline
from pitwall.voice.scheduler import RadioScheduler
from pitwall.voice.types import DrivingState, MessageKind

pytestmark = pytest.mark.synthetic

CALM = DrivingState(True, 200.0, 0.0, 0.0, 10, 500.0, None)


class Run:
    def __init__(self) -> None:
        self.packets, self.truth = race_strategy_demo()
        self.engine = StrategyEngine("synthetic")
        self.calls: list[dict[str, Any]] = []
        self.records: dict[int, dict[str, Any]] = {}
        self.stops: dict[tuple[int, int], dict[str, Any]] = {}
        self.view_lap6: dict[str, Any] | None = None
        adapter = F1Adapter(field_hz=0.0)
        for p in self.packets:
            for item in adapter.decode(p.data, p.t_recv_ns):
                self.engine.feed(item)
                self._take()
                if isinstance(item, RaceTiming) and self.view_lap6 is None and self.engine._lap == 6:
                    self.view_lap6 = self.engine.view()
        self.engine.end()
        self._take()
        self.final_view = self.engine.view()

    def _take(self) -> None:
        self.calls += [c.to_dict() for c in self.engine.take_calls()]
        self.records.update(self.engine.take_records())
        for s in self.engine.take_stops():
            self.stops[(s["car_index"], s["entry_lap"])] = s


@pytest.fixture(scope="module")
def run() -> Run:
    return Run()


def _calls(run: Run, topic: str) -> list[dict[str, Any]]:
    return [c for c in run.calls if c["topic"] == topic]


def test_stream_carries_the_synthetic_uid_and_decodes_cleanly(run: Run) -> None:
    a = F1Adapter(field_hz=0.0)
    for p in run.packets:
        a.decode(p.data, p.t_recv_ns)
    assert a.stats.errors == 0 and a.stats.rejected == 0 and run.engine.synthetic is False  # flagged by the manager
    assert run.engine.mode == "race" and run.engine.total_laps == 12


def test_measured_pit_loss_matches_the_truth(run: Run) -> None:
    truth: StrategyTruth = run.truth
    for idx in (2, 6):  # the stops under green
        t = truth.stops[idx]
        s = run.stops[(idx, t.entry_lap)]
        assert s["exit_lap"] == t.exit_lap and s["excluded"] is None and s["neutralised"] is None
        assert abs(s["pit_loss_ms"] / 1000 - t.loss_s) <= 0.3, (idx, s["pit_loss_ms"], t.loss_s)
        assert abs(s["lane_time_ms"] - t.lane_ms) <= 100 and s["stationary_ms"] == t.stationary_ms
    mine = run.stops[(PLAYER, truth.stops[PLAYER].entry_lap)]
    assert mine["is_player"] and mine["compound_before"] == "medium" and mine["compound_after"] == "soft"
    assert mine["neutralised"] == "virtual"  # its in-lap ran under the VSC, its out-lap did not
    # the field's laps hold different shares of VSC running: not a fair reference, so not a measurement
    assert mine["excluded"] == "safety car on only part of the stop"


def test_one_vsc_box_call_one_rain_call_and_the_undercut_threat(run: Run) -> None:
    (box,) = _calls(run, "sc_box")
    assert box["lap"] == 7 and box["level"] == "alert" and box["text"].startswith("Virtual safety car. Box this lap")
    (rain,) = _calls(run, "weather")
    assert rain["lap"] == run.truth.rain_call_lap and rain["text"].startswith("Rain forecast in about 10 minutes")
    (threat,) = _calls(run, "undercut_threat")
    assert threat["lap"] == run.truth.threat_lap and threat["data"]["car_index"] == run.truth.threat_car
    assert all(len(c["text"]) <= 120 and "brake later" not in c["text"] for c in run.calls)
    assert not [c for c in run.calls if c["lap"] in (1, 12) and c["topic"] not in ("sc_box", "fuel")]


def test_lift_and_coast_and_burn_model_against_the_truth(run: Run) -> None:
    v = run.view_lap6
    assert v is not None
    fuel = v["fuel"]
    assert fuel["status"] == "short"
    assert fuel["margin_laps"] == pytest.approx(run.truth.fuel_margin_at_lap6, abs=0.05)
    lnc = fuel["lift_coast"]
    assert lnc is not None and lnc["feasible"]
    assert lnc["seconds_per_lap"] == pytest.approx(run.truth.lnc_s_at_lap6, rel=0.10)
    burn = fuel["burn_model"]
    assert burn is not None and burn["r2"] > 0.9


def test_records_and_tyre_window(run: Run) -> None:
    assert sorted(run.records) == list(range(1, 13))
    r9 = run.records[9]
    assert r9["pit"] == "out" and r9["compound"] == "soft" and r9["stops"] == 1
    assert run.records[8]["pit"] == "in" and run.records[7]["safety_car"] == "virtual"
    assert run.records[10]["window"] is not None and run.records[10]["window"]["close"] == 11


def test_view_contract_at_the_flag(run: Run) -> None:
    v = run.final_view
    assert v["mode"] == "race" and v["lap"] == 12 and v["laps_remaining"] == 0.0 and len(v["calls"]) <= 3
    assert v["pit"]["pit_loss"]["n"] == 2 and v["pit"]["pit_entry_m"] == pytest.approx(2850, abs=5)


def test_radio_normal_hears_the_calls_quiet_only_alerts(run: Run) -> None:
    said: dict[str, list[str]] = {}
    for intensity in ("normal", "quiet"):
        s = RadioScheduler(intensity, min_gap_s=0.0)
        out: list[str] = []
        for k, c in enumerate(run.calls):
            s.enqueue(strategy_message(c, float(10 * k)))
            m = s.next_message(CALM, float(10 * k) + 1.0, speaking=False)
            if m is not None:
                out.append(str(m.meta["topic"]))
                assert m.kind in (MessageKind.ALERT, MessageKind.STRATEGY, MessageKind.INFO)
        said[intensity] = out
    levels = {c["topic"]: c["level"] for c in run.calls}
    assert "strategy:undercut_threat" in said["normal"] and "strategy:sc_box" in said["normal"]
    assert all(levels[t.split(":", 1)[1]] == "alert" for t in said["quiet"]) and "strategy:sc_box" in said["quiet"]


# ---------------------------------------------------------------------------------------------- full pipeline
@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Runtime, str]]:
    tmp = tmp_path_factory.mktemp("strategy")
    cap = tmp / "captures" / "race-strategy-demo.pwcap"
    write_strategy_capture(cap)
    rt = Runtime(Settings(data_dir=tmp, llm_enabled=False))
    r = rt.start_replay(cap, speed=None)
    assert r.done.wait(120)
    strategy = rt._replay_strategy
    assert strategy is not None and strategy._thread is not None
    strategy._thread.join(60)
    rt.worker.join()
    rt.writer.flush()
    with rt.db.read() as c:
        sid = repo.latest_session_id(c)
    assert sid
    yield rt, sid
    rt.close()


def test_pipeline_persists_records_stops_and_the_snapshot(replayed: tuple[Runtime, str]) -> None:
    rt, sid = replayed
    with rt.db.read() as c:
        s = repo.get_session(c, sid)
        laps = repo.list_strategy_laps(c, sid)
        stops = repo.list_pit_stops(c, sid)
        tl = build_timeline(c, sid)
    assert s is not None and s["synthetic"] and s["session_type"] == "race"
    assert [r["lap"] for r in laps] == list(range(1, 13))
    assert {(r["car_index"], r["entry_lap"]) for r in stops} == {(2, 5), (PLAYER, 8), (6, 10)}
    assert tl is not None and tl["available"] and tl["total_laps"] == 12
    assert [st["compound"] for st in tl["stints"]] == ["medium", "soft"]
    assert len(tl["stops"]) == 1 and len(tl["field_stops"]) == 2
    assert tl["safety_car_periods"] and tl["safety_car_periods"][0]["status"] == "virtual"
    assert any(c["topic"] == "sc_box" for c in tl["calls"])
    snap = rt.live.snapshot()["strategy"]
    assert snap is not None and snap["session_id"] == sid and snap["synthetic"] is True and snap["mode"] == "race"
    assert rt._replay_strategy is not None and rt._replay_strategy.errors == 0 and rt._replay_strategy.dropped == 0


def test_timeline_api_on_the_replayed_session(replayed: tuple[Runtime, str]) -> None:
    from pitwall.api.routes_strategy import router

    rt, sid = replayed
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = rt
    with TestClient(app) as client:
        tl = client.get(f"/api/sessions/{sid}/strategy").json()
    assert tl["available"] and len(tl["laps"]) == 12 and tl["pit_loss"]["n"] == 2
