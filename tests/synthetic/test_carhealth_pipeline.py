"""SYNTHETIC: car health end to end on generated streams (``sim/``): Forza's tank-level fuel (community-documented
``Dash.Fuel``, 0.36 start, 0.04 a lap), GT7's fuel staying off, and an F1 stream replayed through the runtime (the
blocks reach the snapshot, flagged synthetic; the engine temperature reaches the frame). This proves the algorithms
and the plumbing on generated data; it is NOT evidence that Forza or GT7 behave like this."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.adapters.base import PacketRejected
from pitwall.adapters.forza.adapter import ForzaAdapter
from pitwall.adapters.gt7.adapter import GT7Adapter
from pitwall.ai.facts import FactSheet
from pitwall.carhealth.engine import CarHealthEngine
from pitwall.carhealth.facts import add_car_health_facts
from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.model.telemetry import CarFrame, EventKind, GameEvent, LapCompletion, SessionInfo
from pitwall.sim.forza_stream import ForzaScenario, generate_forza_session
from pitwall.sim.gt7_stream import GT7Scenario, generate_gt7_session
from pitwall.sim.scenarios import write_synthetic_capture

pytestmark = pytest.mark.synthetic

START, PER_LAP = 0.36, 0.04


def _feed(engine: CarHealthEngine, adapter: Any, packets: list[Any]) -> list[tuple[int | None, float | None, Any]]:
    """Route like the session manager (player items only); returns (lap, laps of fuel, call) per call made."""
    calls = []
    last_lap = None
    for p in packets:
        try:
            items = adapter.decode(p.data, p.t_recv_ns)
        except PacketRejected:
            continue
        for it in items:
            if isinstance(it, GameEvent) and it.kind == EventKind.BUTTON:
                continue
            if isinstance(it, CarFrame | LapCompletion | SessionInfo | GameEvent):
                engine.feed(it)
                if isinstance(it, CarFrame):
                    last_lap = it.lap_number
            for c in engine.take_calls():
                fuel = engine.fuel
                calls.append((last_lap, None if fuel is None else fuel.laps_of_fuel(), c))
    return calls


@pytest.fixture(scope="module")
def forza() -> tuple[CarHealthEngine, list[Any], list[tuple[int, float]]]:
    packets, _truth = generate_forza_session(
        ForzaScenario(flying_laps=9, fuel_start_fraction=START, fuel_per_lap_fraction=PER_LAP)
    )
    eng = CarHealthEngine("forza")
    seen: list[tuple[int, float]] = []
    adapter = ForzaAdapter()
    calls = []
    lap = None
    for p in packets:
        try:
            items = adapter.decode(p.data, p.t_recv_ns)
        except PacketRejected:
            continue
        for it in items:
            if isinstance(it, CarFrame | LapCompletion | SessionInfo | GameEvent):
                lines = eng.lines
                eng.feed(it)
                if eng.lines != lines and eng.fuel is not None and eng.fuel.laps_of_fuel() is not None:
                    seen.append((eng._lap or 0, float(eng.fuel.laps_of_fuel() or 0.0)))
                if isinstance(it, CarFrame):
                    lap = it.lap_number
            calls += [(lap, c) for c in eng.take_calls()]
    return eng, calls, seen


def test_forza_laps_of_fuel_follow_the_truth(forza: tuple[CarHealthEngine, list[Any], list[tuple[int, float]]]) -> None:
    eng, _calls, seen = forza
    assert seen, "no fuel estimate"
    fuel = eng.fuel
    assert fuel is not None and fuel.per_lap() == pytest.approx(PER_LAP, rel=0.05)
    # the line into lap k (pitwall laps: 1 = the out-lap, 0.35 of a lap): START - PER_LAP * (k - 2 + 0.35) left
    for lap, laps in seen:
        truth = max(0.0, START - PER_LAP * (lap - 2 + 0.35)) / PER_LAP  # the generator stops at an empty tank
        assert abs(laps - truth) <= 0.3, (lap, laps, truth)
    view = eng.view()["fuel"]
    assert view["source"] == "tank_fraction" and view["tier"] == "community" and view["laps_used"] >= 2


def test_forza_calls_low_then_critical(forza: tuple[CarHealthEngine, list[Any], list[tuple[int, float]]]) -> None:
    _eng, calls, _seen = forza
    topics = [(lap, c.topic) for lap, c in calls if c.topic.startswith("fuel")]
    # 2.65 laps left at the line into lap 8 (low), 1.65 into lap 9: critical - only this lap to reach the pit entry
    # (the alert bypasses quiet mode); 0.65 into lap 10: under a lap now, so the alert again at once
    assert topics == [(8, "fuel_low"), (9, "fuel_critical"), (10, "fuel_critical")], topics
    low, crit, crit2 = (c for _, c in calls if c.topic.startswith("fuel"))
    assert low.level == "normal" and crit.level == "alert" and crit.bypass_quiet
    assert low.text == "Fuel for about 2 more laps, at 4 percent a lap."  # rounded down, as the answer and the tile
    assert crit.text == "Fuel for about one more lap." and crit2.text == "Fuel is almost gone: less than a lap left."


def test_gt7_fuel_stays_off_with_no_numbers() -> None:
    packets, _ = generate_gt7_session(GT7Scenario(laps=5))  # the generator burns 2.2 l a lap
    eng = CarHealthEngine("gt7")
    calls = _feed(eng, GT7Adapter(), packets)
    view = eng.view()
    fuel = view["fuel"]
    assert fuel["status"] == "unverified" and fuel["fraction"] is None and fuel["laps_of_fuel"] is None
    assert not [c for *_, c in calls if c.topic.startswith("fuel")]
    fs = FactSheet()
    add_car_health_facts(fs, {"session_id": "gt7", "car_health": view, "racecraft": eng.racecraft_view()})
    assert not [f for f in fs.facts if f.topic == "fuel"]  # no fuel numbers anywhere
    assert view["tyres"]["available"] and view["tyres"]["model"] == "surface"


@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Runtime]:
    tmp = tmp_path_factory.mktemp("carhealth")
    cap = tmp / "captures" / "coaching-demo.pwcap"
    cap.parent.mkdir(parents=True, exist_ok=True)
    write_synthetic_capture(cap)
    rt = Runtime(Settings(data_dir=tmp, llm_enabled=False))
    r = rt.start_replay(cap, speed=None)
    assert r.done.wait(120)
    h = rt._replay_health
    assert h is not None
    if h._thread is not None:
        h._thread.join(60)
    yield rt
    rt.close()


def test_the_runtime_publishes_the_blocks_flagged_synthetic(replayed: Runtime) -> None:
    snap = replayed.live.snapshot()
    ch, rc = snap["car_health"], snap["racecraft"]
    assert ch is not None and ch["session_id"] == snap["session_id"] and ch["synthetic"] is True
    assert ch["tyres"]["available"] and ch["engine"]["available"]
    assert rc is not None and rc["mode"] == "off"  # a practice session: attack / defend need a race
    assert snap["frame"]["engine_temp_c"] == 105  # the generator's engine temperature, through the adapter
    h = replayed._replay_health
    assert h is not None and h.errors == 0 and h.dropped == 0 and h.calls == 0  # max speed: nobody driving, no calls


def test_synthetic_streams_never_name_a_real_track(tmp_path: Path) -> None:
    eng = CarHealthEngine("x")
    _feed(eng, ForzaAdapter(), generate_forza_session(ForzaScenario(flying_laps=1))[0])
    assert eng.view()["game"] in ("forza_motorsport", "forza_horizon")
