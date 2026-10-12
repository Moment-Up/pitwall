"""Tyre temperatures against the driver's own warm laps (``carhealth.tyres``): baselines, the temperature model,
the cold-tyre rule after a stop and a safety car, bands, flashbacks. Values are made up; the real-data checks are
``tests/recorded/test_carhealth_recorded.py`` and ``scripts/carhealth_check.py``."""

from __future__ import annotations

from pitwall.carhealth import thresholds as T
from pitwall.carhealth.engine import CarHealthEngine
from pitwall.carhealth.tyres import TyreTempMonitor
from pitwall.model.telemetry import Game, SessionType
from tests.unit.carhealth_helpers import drive, flashback, frame, info


def _engine(model: str | None = "surface_and_carcass", game: Game = Game.F1_25) -> CarHealthEngine:
    eng = CarHealthEngine("s1")
    eng.feed(info(game=game, model=model))
    return eng


def test_stint_baseline_skips_the_first_minute_and_needs_fifteen_seconds() -> None:
    eng = _engine()
    drive(eng, 0.0, T.STINT_SKIP_S, inner=40.0, lap_s=1000.0)  # the first minute: left out
    drive(eng, T.STINT_SKIP_S, T.STINT_SKIP_S + 10.0, inner=90.0, lap_s=1000.0)
    assert eng.tyres.baseline_index() is None  # 10 s of racing after the skip: not enough
    drive(eng, T.STINT_SKIP_S + 10.0, T.STINT_SKIP_S + T.BASE_MIN_S + 2.0, inner=90.0, lap_s=1000.0)
    assert eng.tyres.baseline_index() == 90.0 and eng.tyres.state == "ok"
    assert eng.tyres.baseline_source() == "this_stint"


def test_model_follows_the_f1_setting_and_the_game() -> None:
    assert _engine("surface_and_carcass").tyre_model() == "carcass"
    assert _engine("surface").tyre_model() == "surface"
    assert _engine(None).tyre_model() == "surface"  # the tail is unfilled for the first ~1.5 s: surface
    assert _engine(None, Game.GT7).tyre_model() == "surface"
    assert _engine(None, Game.FORZA_MOTORSPORT).tyre_model() == "surface"
    assert _engine(None, Game.AC).tyre_model() is None


def test_surface_mode_never_uses_the_inner_temperature() -> None:
    """Surface only: the game fabricates a constant inner temperature (80 / 85 C on real PS5), never used."""
    eng = _engine("surface")
    drive(eng, 0.0, 90.0, surf=70.0, inner=80.0, lap_s=1000.0)
    t = eng.tyres
    assert t.model == "surface" and t.baseline_index() == 70.0
    view = eng.view()["tyres"]
    assert view["model"] == "surface" and {w["window_c"] for w in view["wheels"]} == {70.0}
    assert view["pressures_fixed"] is True and "surface only" in view["note"]


def _stint_then_stop(eng: CarHealthEngine, base: float = 90.0) -> float:
    """Stint 1 (lap 2-3) at ``base``, a pit visit on lap 3, the exit at the returned time."""
    t = drive(eng, 0.0, 100.0, inner=base, surf=base - 10, lap0=2, lap_s=200.0)
    t = drive(eng, t, t + 25.0, inner=base, surf=base - 10, pit=1, speed=70.0, lap0=2, lap_s=1000.0)
    return t


def test_cold_after_a_pit_stop_then_warm_again() -> None:
    eng = _engine()
    t = _stint_then_stop(eng)
    t = drive(eng, t, t + 6.0, inner=30.0, lap0=2, lap_s=1000.0)  # out of the pits on new tyres
    assert eng.tyres.state == "cold" and eng.tyres.since == {"lap": 2, "reason": "pit_exit"}
    calls = eng.take_calls()
    assert [c.topic for c in calls] == ["tyres_cold"]
    assert calls[0].data["baseline_c"] == 90.0 and calls[0].data["index_c"] <= 31.0
    assert eng.view()["tyres"]["baseline_source"] == "previous_stint"
    assert {w["band"] for w in eng.view()["tyres"]["wheels"]} == {"cold"}
    t = drive(eng, t, t + 30.0, inner=60.0, lap0=3, lap_s=1000.0)  # warming, still cold (lap 3: line crossed)
    assert eng.tyres.state == "cold"
    t = drive(eng, t, t + 15.0, inner=85.0, lap0=3, lap_s=1000.0)  # within WARM_DROP (8 C) of 90
    assert eng.tyres.state == "ok" and eng.tyres.since == {"lap": 3, "reason": "warm"}
    assert [c.topic for c in eng.take_calls()] == ["tyres_warm"]
    drive(eng, t, t + 200.0, inner=88.0, lap0=3, lap_s=1000.0)
    # the new stint's baseline starts after the warm-up: warm tyres never read "hot" against a cold baseline
    assert eng.tyres.baseline_index() == 88.0 and {w["band"] for w in eng.view()["tyres"]["wheels"]} == {"ok"}


def test_tyre_blankets_arm_but_never_call() -> None:
    eng = _engine("surface")
    t = _stint_then_stop(eng, base=70.0)
    drive(eng, t, t + 60.0, surf=66.0, lap0=2, lap_s=1000.0)  # warm already: within 12 C, back within 5 after...
    assert not eng.tyres.armed and eng.tyres.state == "ok"
    assert eng.take_calls() == []


def test_no_arm_without_a_warm_baseline() -> None:
    """A stop in the first minute (or a session joined mid-race): no warm laps to compare with, never armed."""
    eng = _engine()
    t = drive(eng, 0.0, 40.0, inner=90.0, lap_s=1000.0)
    t = drive(eng, t, t + 20.0, inner=90.0, pit=1, speed=70.0, lap_s=1000.0)
    drive(eng, t, t + 20.0, inner=30.0, lap_s=1000.0)
    assert not eng.tyres.armed and eng.tyres.state != "cold" and eng.take_calls() == []


def test_the_arm_ends_after_three_laps() -> None:
    eng = _engine()
    t = _stint_then_stop(eng)
    t = drive(eng, t, t + 5.0, inner=75.0, lap0=2, lap_s=1000.0)  # under 90 - 8 but not 20 under: still armed
    assert eng.tyres.armed and eng.tyres.state == "ok"
    for lap in range(3, 3 + T.ARM_MAX_LAPS):
        t = drive(eng, t, t + 20.0, inner=75.0, lap0=lap, lap_s=1000.0)
        assert eng.tyres.armed, lap
    drive(eng, t, t + 5.0, inner=75.0, lap0=2 + T.ARM_MAX_LAPS + 1, lap_s=1000.0)
    assert not eng.tyres.armed and eng.take_calls() == []


def test_safety_car_end_judges_the_laps_behind_it_at_once() -> None:
    eng = _engine()
    t = drive(eng, 0.0, 100.0, inner=90.0, lap_s=1000.0)
    eng.feed(info(sc="full", t=t))
    t = drive(eng, t, t + 120.0, inner=65.0, speed=120.0, lap_s=1000.0)  # cooled behind the safety car
    assert eng.tyres.baseline_index() == 90.0  # the neutralised laps never enter the stint baseline
    eng.feed(info(sc="none", t=t))
    assert eng.tyres.armed
    drive(eng, t, t + 0.5, inner=66.0, lap0=3, lap_s=1000.0)  # the first racing frame of the restart
    assert eng.tyres.state == "cold" and eng.tyres.since is not None and eng.tyres.since["reason"] == "sc_end"
    (call,) = eng.take_calls()
    assert call.topic == "tyres_cold" and "safety car" in call.text and call.data["reason"] == "sc_end"


def test_a_safety_car_that_did_not_cool_the_tyres_says_nothing() -> None:
    eng = _engine()
    t = drive(eng, 0.0, 100.0, inner=90.0, lap_s=1000.0)
    eng.feed(info(sc="virtual", t=t))
    t = drive(eng, t, t + 60.0, inner=86.0, speed=150.0, lap_s=1000.0)
    eng.feed(info(sc="none", t=t))
    drive(eng, t, t + 10.0, inner=88.0, lap0=3, lap_s=1000.0)
    assert not eng.tyres.armed and eng.tyres.state == "ok" and eng.take_calls() == []


def _stop_with_a_change(eng: CarHealthEngine, new: float, *, base: float = 90.0, surface: bool = False) -> float:
    """A stint at ``base``, the pit lane, the box (tyre age 3 -> 0 at the change) at ``new``; returns the exit time."""
    kw = (lambda v: {"surf": v, "inner": 80.0}) if surface else (lambda v: {"inner": v, "surf": v - 10})
    t = drive(eng, 0.0, 100.0, lap0=2, lap_s=200.0, **kw(base))
    t = drive(eng, t, t + 10.0, pit=1, speed=70.0, lap0=2, lap_s=1000.0, **kw(base))
    t = drive(eng, t, t + 3.0, pit=2, speed=0.0, lap0=2, lap_s=1000.0, **kw(base - 2))  # in the box, old tyres
    t = drive(eng, t, t + 4.0, pit=2, speed=0.0, lap0=2, lap_s=1000.0, age=0, **kw(new))  # the change
    return drive(eng, t, t + 10.0, pit=1, speed=70.0, lap0=2, lap_s=1000.0, age=0, **kw(new))


def test_new_cold_tyres_are_called_in_the_box() -> None:
    eng = _engine()
    _stop_with_a_change(eng, 30.0)
    calls = eng.take_calls()  # still in the pit lane
    assert [c.topic for c in calls] == ["tyres_cold"] and calls[0].data["in_pit"] is True
    assert calls[0].data["baseline_c"] == 90.0 and calls[0].data["index_c"] == 30.0
    assert eng.tyres.state == "cold" and eng.view()["tyres"]["armed"]


def test_tyre_blankets_in_the_box_say_nothing_even_when_the_pit_lane_cools_them() -> None:
    """F1 Imola (surface model, blankets): 69 C in the box against 66-68 C warm laps, then 53 C at the 80 km/h exit."""
    eng = _engine("surface")
    t = _stop_with_a_change(eng, 69.0, base=67.0, surface=True)
    assert not eng.tyres.armed and eng.take_calls() == []
    drive(eng, t, t + 5.0, pit=1, speed=80.0, surf=53.0, inner=80.0, age=0, lap0=2, lap_s=1000.0)
    drive(eng, t + 5.0, t + 60.0, surf=60.0, inner=80.0, age=0, lap0=2, lap_s=1000.0)
    assert eng.take_calls() == [] and eng.tyres.state != "cold"


def test_undecided_in_the_box_is_judged_on_track() -> None:
    eng = _engine()
    t = _stop_with_a_change(eng, 78.0)  # 12 C under: neither cold (20) nor warm (8)
    assert eng.tyres.armed and eng.take_calls() == []
    drive(eng, t, t + 6.0, inner=60.0, age=0, lap0=2, lap_s=1000.0)  # out on track, cooling: cold
    assert [c.topic for c in eng.take_calls()] == ["tyres_cold"]


def test_wheels_stay_cold_while_the_tyres_are_called_cold() -> None:
    """The cold state clears within WARM_DROP (8 C): a wheel 10 C under is still "cold", never "ok" under the chip."""
    eng = _engine()
    t = _stop_with_a_change(eng, 30.0)
    drive(eng, t, t + 12.0, inner=80.0, age=0, lap0=2, lap_s=1000.0)  # 10 C under the 90 C warm laps
    assert eng.tyres.state == "cold"
    assert {w["band"] for w in eng.view()["tyres"]["wheels"]} == {"cold"}


def test_a_short_dip_on_a_straight_is_not_cold_in_surface_mode() -> None:
    """Surface temperatures drop on every long straight: the 45 s window rides through a 7 s dip."""
    eng = _engine("surface")
    t = drive(eng, 0.0, 100.0, surf=70.0, lap_s=1000.0)
    eng.feed(info(model="surface", sc="virtual", t=t))
    t = drive(eng, t, t + 20.0, surf=70.0, lap_s=1000.0)
    eng.feed(info(model="surface", sc="none", t=t))
    t = drive(eng, t, t + 10.0, surf=70.0, lap_s=1000.0)
    t = drive(eng, t, t + 7.0, surf=40.0, lap_s=1000.0)
    drive(eng, t, t + 40.0, surf=70.0, lap_s=1000.0)
    assert eng.tyres.state == "ok" and eng.take_calls() == []


def test_bands_per_wheel_against_their_own_baseline() -> None:
    eng = _engine()
    t = drive(eng, 0.0, 100.0, inner=90.0, lap_s=1000.0)
    drive(eng, t, t + 15.0, inner=(90.0, 104.0, 65.0, 92.0), lap_s=1000.0)
    bands = {w["wheel"]: w["band"] for w in eng.view()["tyres"]["wheels"]}
    assert bands == {"FL": "ok", "FR": "hot", "RL": "cold", "RR": "ok"}


def test_without_a_baseline_every_band_is_unknown() -> None:
    eng = _engine()
    drive(eng, 0.0, 20.0, inner=90.0, lap_s=1000.0)
    tyres = eng.view()["tyres"]
    assert tyres["state"] == "unknown" and {w["band"] for w in tyres["wheels"]} == {"unknown"}
    assert tyres["baseline_c"] is None


def test_a_flashback_clears_the_lap_and_the_windows() -> None:
    eng = _engine()
    t = drive(eng, 0.0, 100.0, inner=90.0, lap_s=1000.0)
    eng.feed(flashback(t, t - 30.0))
    m = eng.tyres
    assert all(h.n == 0 for h in m._lap_hist) and m._index_win.median() is None
    assert m.baseline_index() == 90.0  # the stint baseline is kept


def test_lap_medians_at_the_line() -> None:
    m = TyreTempMonitor()
    for k in range(50):
        m.on_frame(frame(float(k) / 10, lap=2, inner=80.0 + (k % 5)), "carcass")
    m.on_line(3)
    assert m.last_lap_median == (82.0, 82.0, 82.0, 82.0)


def test_gt7_and_forza_have_bands_but_no_cold_call() -> None:
    """GT7 and Forza send no pit state: bands against the warm laps, never a cold-tyre call."""
    eng = CarHealthEngine("g")
    eng.feed(info(game=Game.GT7, model=None, session_type=SessionType.RACE))
    t = drive(eng, 0.0, 100.0, surf=60.0, inner=None, game=Game.GT7, lap_s=1000.0)
    drive(eng, t, t + 35.0, surf=30.0, inner=None, game=Game.GT7, lap_s=1000.0)  # most of the 45 s window
    assert {w["band"] for w in eng.view()["tyres"]["wheels"]} == {"cold"}
    assert not eng.tyres.armed and eng.take_calls() == []
