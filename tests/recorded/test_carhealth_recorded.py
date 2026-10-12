"""RECORDED tier: car health on real F1 25 captures (v1.26, PS5, UDP format 2025).

Committed fixtures (byte-for-byte excerpts of the owner's sessions, names scrubbed; the F2 ones keep only the packet
types car health reads: ``excerpt_capture.py --f1-packet-id``):

* ``f1_25_2025_ps5_jeddah-f2_race-pitstop-coldtyres-excerpt.pwcap`` (F2 Jeddah race, carcass tyre model): the lap-1
  stop on new tyres -> ``tyres_cold`` in the box, a second after the tyre change and 13 s before the pit exit
  (carcass 28 C against an 88 C baseline), warm again on lap 3 at 353 s.
* ``f1_25_2025_ps5_bahrain-f2_race-lockups-abs-off-excerpt.pwcap`` (F2 Bahrain race, ABS off): five lock-ups in lap 2,
  the wheels fully locked (slip -1.0).
* ``f1_25_2025_ps5_imola_race-pitstop-excerpt.pwcap`` (F1 Imola, tyre blankets, surface model): no cold-tyre call;
  the player's pit entry gap is known and the rejoin estimate is frozen through the lane.

The owner-only checks (``scripts/carhealth_check.py`` on the owner's full captures) run only when
``PITWALL_OWNER_CAPTURES`` names a folder of scratch copies of them, never the live data folder (a capture the service
is still writing could break or flake ``make check``); they are skipped otherwise, and for a capture that is absent.
Nothing here is live validation.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from pitwall.adapters.base import PacketRejected
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.carhealth.engine import CarHealthEngine
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import CarFrame, EventKind, GameEvent, LapCompletion, RaceTiming, SessionInfo
from pitwall.strategy import rejoin as rj
from pitwall.strategy.pitloss import PitTracker

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "recorded"
JEDDAH = FIXTURES / "f1_25_2025_ps5_jeddah-f2_race-pitstop-coldtyres-excerpt.pwcap"
BAHRAIN = FIXTURES / "f1_25_2025_ps5_bahrain-f2_race-lockups-abs-off-excerpt.pwcap"
IMOLA = FIXTURES / "f1_25_2025_ps5_imola_race-pitstop-excerpt.pwcap"
# the owner's full captures: only scratch copies PITWALL_OWNER_CAPTURES points at (never the live data folder)
_OWNER_DIR = os.environ.get("PITWALL_OWNER_CAPTURES")
CAPTURES = Path(_OWNER_DIR) if _OWNER_DIR else None

pytestmark = pytest.mark.recorded


class Run:
    def __init__(self, path: Path) -> None:
        if not path.exists():
            pytest.skip(f"{path.name} absent")
        reader = CaptureReader(path)
        assert not reader.meta.synthetic
        self.engine = CarHealthEngine("recorded")
        self.calls: list[tuple[float | None, Any]] = []
        self.pit_exits: list[float] = []
        self.min_slip = 0.0
        self.engine_temps: list[float] = []
        adapter = F1Adapter(field_hz=0.0, timing_hz=0.0)
        prev_pit: int | None = None
        for p in reader:
            try:
                items = adapter.decode(p.data, p.t_recv_ns)
            except PacketRejected:
                continue
            for it in items:
                if isinstance(it, GameEvent) and it.kind == EventKind.BUTTON:
                    continue
                if not isinstance(it, CarFrame | LapCompletion | SessionInfo | GameEvent):
                    continue
                self.engine.feed(it)
                if isinstance(it, CarFrame):
                    if prev_pit and not it.pit_status and it.session_time_s is not None:
                        self.pit_exits.append(it.session_time_s)
                    prev_pit = it.pit_status
                    if it.wheel_slip_ratio is not None:
                        self.min_slip = min(self.min_slip, *it.wheel_slip_ratio.as_tuple())
                    if it.engine_temp_c and (it.speed_kph or 0) > 60:
                        self.engine_temps.append(it.engine_temp_c)
                for c in self.engine.take_calls():
                    self.calls.append((self.engine._t, c))


@pytest.fixture(scope="module")
def jeddah() -> Run:
    return Run(JEDDAH)


def test_jeddah_cold_tyres_after_the_stop_then_warm(jeddah: Run) -> None:
    e = jeddah.engine
    assert e.info is not None and e.info.extra["tyre_temperature_model"] == "surface_and_carcass"
    assert e.tyre_model() == "carcass" and e.info.formula == "F2"
    (exit_t,) = jeddah.pit_exits
    assert exit_t == pytest.approx(146.3, abs=0.2)
    cold = [(t, c) for t, c in jeddah.calls if c.topic == "tyres_cold"]
    warm = [(t, c) for t, c in jeddah.calls if c.topic == "tyres_warm"]
    assert len(cold) == 1 and len(warm) == 1
    t_cold, c = cold[0]
    # in the box, a second after the change at 132.5 s: said in the pit lane, never into the first braking zone
    assert t_cold is not None and 133.0 <= t_cold <= 134.0 and exit_t - t_cold > 10.0
    assert c.data["baseline_c"] == 88.0 and c.data["index_c"] <= 30.0 and c.data["in_pit"] is True
    assert c.data["reason"] == "pit_exit" and c.lap == 2
    assert c.text == "New tyres are cold: give them a lap or two before you push."
    t_warm, w = warm[0]
    assert t_warm is not None and 350.0 <= t_warm <= 356.0 and w.lap == 3 and w.level == "normal"
    assert e.tyres.state == "ok" and not e.tyres.armed


def test_jeddah_engine_temperature_is_real_and_unwarned(jeddah: Run) -> None:
    assert jeddah.engine_temps and min(jeddah.engine_temps) >= 103.0 and max(jeddah.engine_temps) <= 132.0
    assert {c.topic for _, c in jeddah.calls} <= {"tyres_cold", "tyres_warm"}  # no temperature warnings


def test_bahrain_lockups_with_abs_off() -> None:
    run = Run(BAHRAIN)
    s = run.engine.slip
    assert s.abs_on is False and run.engine.view()["slip"]["lockups_applicable"] is True
    assert s.current()["lockups"] >= 5 and run.min_slip == -1.0  # fully locked wheels
    assert all(e.kind != "lockup" or e.duration_s >= 0.1 for e in s._events)


def test_imola_blankets_no_cold_call_and_the_frozen_rejoin() -> None:
    run = Run(IMOLA)
    assert not [c for _, c in run.calls if c.topic == "tyres_cold"]
    adapter = F1Adapter(field_hz=0.0)
    pits = PitTracker()
    pred = rj.RejoinPredictor()
    loss = rj.Loss.of(25.1, 20.9, 28.3, 32, "measured")  # the full race's measured stops (owner capture)
    states: list[tuple[str | None, int, dict[str, Any] | None]] = []
    for p in CaptureReader(IMOLA):
        try:
            items = adapter.decode(p.data, p.t_recv_ns)
        except PacketRejected:
            continue
        for it in items:
            if not isinstance(it, RaceTiming):
                continue
            pits.update(it, None)
            me = next(c for c in it.cars if c.is_player)
            out = pred.update(
                me,
                it.cars,
                it.session_time_s,
                resolved=pits.resolved,
                loss=loss,
                game_position=None,
                in_lane=pits.in_lane_entries(),
            )
            states.append((me.driver_status, me.pit_status, out))
    visit = next(v for v in pits.visits if v.is_player)
    assert visit.entry_lap == 14 and visit.entry_leader_ms == 0  # the leader: its gap is known (0), never None
    lane = [o for ds, ps, o in states if ps or ds == "in_lap"]
    assert lane and all(o is not None and o["frozen"] and o["position"] == 2 for o in lane)  # P2: where it came out


# ------------------------------------------------------------------------------------- owner-only acceptance
def _check_module() -> Any:
    spec = importlib.util.spec_from_file_location("carhealth_check", ROOT / "scripts" / "carhealth_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["carhealth_check"] = mod
    spec.loader.exec_module(mod)
    return mod


def _owner(name: str) -> Path:
    if CAPTURES is None:
        pytest.skip("PITWALL_OWNER_CAPTURES not set (scratch copies of the owner's captures)")
    path = CAPTURES / name
    if not path.exists():
        pytest.skip(f"owner capture {name} absent")
    return path


def test_owner_imola_rejoin_and_neighbour_stops() -> None:
    res = _check_module().run_capture(_owner("20261011-195612_udp20777.pwcap"), "846837")
    (s,) = res["sessions"].values()
    rr = s["rejoin"]
    assert rr["n"] >= 28 and rr["within1"] >= 0.70 and rr["within2"] >= 0.95 and rr["range_pm1"] >= 0.85
    assert [p["pred"] == p["actual"] for p in rr["player"]] == [True, True]
    assert rr["neighbour"].get("covered", 0) + rr["neighbour"].get("ahead", 0) + rr["neighbour"].get("close", 0) > 0
    assert not [c for c in s["calls"] if c["topic"] in ("tyres_cold", "slip_lockups", "slip_wheelspin")]
    assert all(lap["abs"] for lap in s["slip_laps"])  # ABS on: lock-ups never applicable
    defend = [r["behind"]["verdict"] for r in s["racecraft"] if r["behind"] and r["behind"]["verdict"] != "unknown"]
    assert sum(v in ("spread", "none") for v in defend) / len(defend) >= 0.5
    assert all(abs(a - b) <= 0.05 for _, a, b in s["seg_checks"])


def test_owner_austria_attack_corner() -> None:
    mod = _check_module()
    picks = []
    for name in ("20261010-221749_udp20777.pwcap", "20261011-183245_udp20777.pwcap"):
        res = mod.run_capture(_owner(name))
        for s in res["sessions"].values():
            if not s["racecraft"] or not s["model_corners"]:
                continue
            apex = {c: m for c, m in s["model_corners"]}
            nearest = min(apex, key=lambda c: abs(apex[c] - 1420))
            for r in s["racecraft"]:
                a = r["ahead"]
                if a and a["verdict"] in ("clear", "spread", "none"):
                    picks.append(a["verdict"] == "clear" and a["corner"]["name"] == nearest)
            assert not [c for c in s["calls"] if c["topic"] == "tyres_cold"]
    assert picks and sum(picks) / len(picks) >= 0.8


def test_owner_f2_cold_tyres_and_lockups() -> None:
    res = _check_module().run_capture(_owner("20261011-224147_udp20777.pwcap"))
    by = {uid[-6:]: s for uid, s in res["sessions"].items()}
    for uid, exit_t in (("314818", 146.3), ("244822", 161.6)):
        cold = [c for c in by[uid]["calls"] if c["topic"] == "tyres_cold"]
        assert len(cold) == 1 and 10.0 < exit_t - cold[0]["t"] <= 20.0 and cold[0]["in_pit"], uid  # the box
        assert [c["topic"] for c in by[uid]["calls"]].count("tyres_warm") == 1, uid  # the all-clear is never dropped
    assert next(s for s in by["244822"]["lap_states"] if s["lap"] == 5)["state"] == "ok"  # warm by the end of lap 4
    raw = by["752346"]["raw_slip_laps"]
    assert raw["1"][0] == 10 and (raw.get("2") or raw.get("2*"))[0] == 8  # the survey's per-lap lock-ups


def test_owner_gt7_fuel_stays_off() -> None:
    """Why ``GT7_FUEL_ENABLED`` is off: no GT7 recording shows the level falling. A capture that does fails this test,
    which is the cue to verify the estimate (thresholds.GT7_FUEL_ENABLED) - not to loosen it."""
    if CAPTURES is None:
        pytest.skip("PITWALL_OWNER_CAPTURES not set (scratch copies of the owner's captures)")
    mod = _check_module()
    names = sorted(p.name for p in CAPTURES.glob("*_udp33740.pwcap"))
    if not names:
        pytest.skip("owner GT7 captures absent")
    for name in names:
        for s in mod.run_capture(CAPTURES / name)["sessions"].values():
            levels = s["fuel_levels"]
            assert not levels or levels[0] == levels[1] == 1.0, (name, levels)  # 100 / 100 throughout
            fuel = s["final_view"]["fuel"]
            assert fuel["status"] == "unverified" and fuel["fraction"] is None and fuel["laps_of_fuel"] is None
            assert not [f for f in s["facts"] if "Fuel" in f]
