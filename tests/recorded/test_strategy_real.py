"""RECORDED tier: the race strategy engineer on real F1 25 races (v1.26, PS5, UDP format 2025).

Committed fixtures only (byte-for-byte excerpts, names scrubbed): the Austria race excerpt (grid, lap 1->2, lap 2->3,
flag) and the Monza race excerpt (lap 3, 560-2250 m). What is asserted is the game's own data and the engine's honest
answers on it: decoding of every car's timing and the player's tyre sets, the forecast, the gap settle rule against
the real glitches, and "not enough laps yet" where a 3-lap race cannot say more. The full 71-lap Austria race is not
committed (other players' names); ``test_full_austria_race`` runs only where the owner's capture is present (it is
checked manually with ``scripts/strategy_check.py``). Nothing here is live validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import RaceTiming, SessionInfo, TyreSetsInfo
from pitwall.strategy.engine import StrategyEngine
from pitwall.strategy.gaps import GapTracker

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "recorded"
AUSTRIA = FIXTURES / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
MONZA = FIXTURES / "f1_25_2025_ps5_monza_race-excerpt.pwcap"
LONG_RACE = ROOT / "data" / "captures" / "20261010-221749_udp20777.pwcap"  # Austria, laps 62-71 (two UIDs)

pytestmark = pytest.mark.recorded


class Decoded:
    def __init__(self, path: Path) -> None:
        reader = CaptureReader(path)
        assert not reader.meta.synthetic
        adapter = F1Adapter(field_hz=0.0)
        self.engine = StrategyEngine("recorded")
        self.timings: list[RaceTiming] = []
        self.tyre_sets: list[TyreSetsInfo] = []
        self.info: SessionInfo | None = None
        self.calls: list[dict[str, Any]] = []
        self.records: dict[int, dict[str, Any]] = {}
        for p in reader:
            try:
                items = adapter.decode(p.data, p.t_recv_ns)
            except Exception:
                continue
            for it in items:
                if isinstance(it, RaceTiming):
                    self.timings.append(it)
                elif isinstance(it, TyreSetsInfo):
                    self.tyre_sets.append(it)
                elif isinstance(it, SessionInfo):
                    self.info = it
                self.engine.feed(it)
            self.calls += [c.to_dict() for c in self.engine.take_calls()]
            self.records.update(self.engine.take_records())
        self.engine.end()
        self.records.update(self.engine.take_records())
        self.view = self.engine.view()


@pytest.fixture(scope="module")
def austria() -> Decoded:
    if not AUSTRIA.exists():
        pytest.skip("real PS5 Austria excerpt absent")
    return Decoded(AUSTRIA)


def test_austria_timing_of_every_car_at_two_hz(austria: Decoded) -> None:
    assert austria.timings and austria.timings[-1].player_index == 19
    assert len(austria.timings[-1].cars) == 20 and sum(c.is_player for c in austria.timings[-1].cars) == 1
    dt = np.diff([t.session_time_s for t in austria.timings])
    dt = dt[(dt > 0) & (dt < 1.0)]  # excerpt windows leave gaps
    assert dt.min() >= 0.495  # <= 2 Hz (no pit-status change in the excerpt)
    me = next(c for c in austria.timings[-1].cars if c.is_player)
    assert me.tyre_visual == "soft" and me.last_lap_ms == 78351 and me.ai_controlled is False


def test_austria_tyre_sets_are_the_games_model(austria: Decoded) -> None:
    ts = austria.tyre_sets[-1]
    fitted = ts.sets[ts.fitted_index or 0]
    assert ts.car_index == 19 and ts.fitted_index == 8
    assert (fitted.visual, fitted.wear_pct, fitted.life_span_laps, fitted.usable_life_laps) == ("soft", 11, 22, 27)
    deltas = {s.visual: s.lap_delta_ms for s in ts.sets if s.available and not s.fitted and s.wear_pct == 0}
    assert deltas == {"medium": -158, "hard": 291, "inter": 3325, "wet": 4977, "soft": -608}


def test_austria_forecast_and_session(austria: Decoded) -> None:
    info = austria.info
    assert info is not None and info.total_laps == 3 and info.extra["session_type_id"] == 15
    race = [s for s in info.extra["forecast"] if s["session_type"] == 15]
    assert [s["time_offset_min"] for s in race] == [0, 5, 10] and {s["rain_pct"] for s in race} == {7}
    w = austria.view["weather"]
    assert w["now"] == "light_cloud" and w["rain_pct"] == 7 and w["next_change"] is None


def test_austria_honest_answers_on_a_three_lap_race(austria: Decoded) -> None:
    v = austria.view
    assert v["mode"] == "race" and v["total_laps"] == 3 and v["synthetic"] is False
    assert v["tyres"]["enough_laps"] is False and "not enough laps" in v["tyres"]["note"]
    assert v["tyres"]["game_laps_left"] == 22 and v["tyres"]["game_usable_life"] == 27
    assert v["pit"]["window"] is None and v["pit"]["pit_loss"] is None
    assert v["pit"]["stop_needed"] is False  # the game gives the softs 22 more laps of a 3-lap race
    assert not [c for c in austria.calls if c["topic"] in ("pit_window", "fuel", "weather", "sc_box", "sc_stay")]
    assert sorted(austria.records) == [1, 2, 3]


def test_monza_gap_settle_rule_on_the_real_glitches() -> None:
    if not MONZA.exists():
        pytest.skip("real PS5 Monza excerpt absent")
    adapter = F1Adapter(field_hz=0.0)
    g = GapTracker()
    published: list[tuple[float, float]] = []
    for p in CaptureReader(MONZA):
        for it in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(it, RaceTiming):
                g.update(it)
                if g.ahead.settled and g.ahead.value_s is not None:
                    published.append((it.session_time_s, g.ahead.value_s))
    assert all(v < 60.0 for _, v in published)  # 65403 (a negative delta wrapped into the uint16) never published
    after = [(t, v) for t, v in published if t > 192.741]
    assert after and after[0][0] >= 192.741 + 4.0 - 1e-3  # nothing within 4 s of the position change
    assert round(after[0][1] * 1000) == 1235  # the real gap, not the 2453 ms of the car that was ahead before


@pytest.mark.skipif(not LONG_RACE.exists(), reason="owner's full Austria race capture absent (never committed)")
def test_full_austria_race() -> None:
    res = {}
    adapter = F1Adapter(field_hz=0.0)
    engine: StrategyEngine | None = None
    uid = None
    stops: dict[tuple[int, int], dict[str, Any]] = {}
    calls: list[dict[str, Any]] = []
    for p in CaptureReader(LONG_RACE):
        try:
            items = adapter.decode(p.data, p.t_recv_ns)
        except Exception:
            continue
        for it in items:
            if isinstance(it, SessionInfo) and it.session_uid != uid:
                if engine is not None:
                    engine.end()
                    res[uid] = (engine, dict(stops), list(calls))
                uid, engine, stops, calls = it.session_uid, StrategyEngine(str(it.session_uid)), {}, []
            if engine is None:
                continue
            engine.feed(it)
            for s in engine.take_stops():
                stops[(s["car_index"], s["entry_lap"])] = s
            calls += [c.to_dict() for c in engine.take_calls()]
            engine.take_records()
    assert engine is not None
    engine.end()
    stops.update({(s["car_index"], s["entry_lap"]): s for s in engine.take_stops()})
    res[uid] = (engine, stops, calls)
    first = res["10888533858520381703"]
    eng, st, cl = first
    car14 = st[(14, 65)]
    assert car14["pit_loss_ms"] == 18911 and car14["exit_lap"] == 66 and car14["stationary_ms"] == 3353
    assert car14["excluded"] is None and car14["entry_lap_distance_m"] == pytest.approx(4264, abs=5)
    assert st[(7, 62)]["excluded"] == "long stop (repair?)"
    assert eng.pits.pit_entry_m() == pytest.approx(4264, abs=5)
    assert {c["topic"] for c in cl} == {"gap"}  # only "car behind within a second"
    d = eng.d
    assert d.burn is not None and d.burn.b1 == pytest.approx(0.024, abs=0.002) and d.burn.r2 >= 0.8
    assert d.stop_needed is False and d.fuel is not None and 1.37 <= (d.fuel.per_lap_kg or 0) <= 1.46
