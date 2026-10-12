"""Brakes and engine against the session's own laps (``carhealth.temps``): lap peaks and medians, the words, and
"not available" for the games that do not send them."""

from __future__ import annotations

from pitwall.carhealth import thresholds as T
from pitwall.carhealth.engine import CarHealthEngine
from pitwall.carhealth.temps import BrakeEngineMonitor
from pitwall.model.telemetry import Game
from tests.unit.carhealth_helpers import drive, frame, info


def _laps(m: BrakeEngineMonitor, peaks: list[float], engines: list[float]) -> None:
    t = 0.0
    for lap, (peak, eng) in enumerate(zip(peaks, engines, strict=True), start=2):
        for k in range(300):  # 30 s of racing frames
            b = peak if k == 150 else 400.0
            m.on_frame(frame(t, lap=lap, brakes_c=(b, b - 3, b - 20, b - 21), engine_c=eng + (k % 3) - 1))
            t += 0.1
        m.on_line(lap)


def test_brake_peaks_and_engine_medians_per_lap() -> None:
    m = BrakeEngineMonitor()
    _laps(m, [980.0, 975.0, 990.0], [123.0, 124.0, 124.0])
    assert m.last_brake == (4, (990.0, 987.0, 970.0, 969.0))
    assert m.brake_baseline() == (980.0, 977.0, 960.0, 959.0)
    b = m.brakes_view()
    assert b["word"] == "normal" and b["last_lap_max_c"] == [990, 987, 970, 969] and b["laps"] == 3
    e = m.engine_view()
    assert e["word"] == "steady" and e["lap_median_c"] == 124.0 and e["baseline_c"] == 124.0 and e["max_c"] == 125.0


def test_words_hotter_and_cooler() -> None:
    m = BrakeEngineMonitor()
    _laps(m, [900.0, 900.0, 900.0 + T.BRAKE_NORMAL_C + 50], [120.0, 120.0, 120.0 + T.ENGINE_STEADY_C + 6])
    assert m.brakes_view()["word"] == "hotter"
    # the engine median baseline is 120 over three laps (120, 120, 130): 130 is hotter than earlier
    assert m.engine_view()["word"] == "hotter"
    m2 = BrakeEngineMonitor()
    _laps(m2, [900.0, 900.0, 700.0], [120.0, 120.0, 110.0])
    assert m2.brakes_view()["word"] == "cooler" and m2.engine_view()["word"] == "cooler"


def test_two_laps_before_a_word_and_pit_laps_never_count() -> None:
    m = BrakeEngineMonitor()
    _laps(m, [980.0], [123.0])
    assert m.brakes_view()["word"] is None and m.brakes_view()["reason"] == "needs two full laps"
    for k in range(300):
        m.on_frame(frame(100 + k / 10, lap=3, pit=1 if k > 250 else 0, brakes_c=1200.0))
    m.on_line(3)
    assert len(m.brake_laps) == 1 and m.last_brake is not None and m.last_brake[1][0] == 1200.0


def test_a_flashback_lap_never_counts() -> None:
    m = BrakeEngineMonitor()
    _laps(m, [980.0, 975.0], [123.0, 124.0])
    for k in range(300):
        m.on_frame(frame(200 + k / 10, lap=4, brakes_c=1500.0))
    m.rewind()
    for k in range(300):
        m.on_frame(frame(200 + k / 10, lap=4, brakes_c=990.0))
    m.on_line(4)
    assert len(m.brake_laps) == 2  # the re-driven lap is not a clean lap


def test_not_available_for_the_games_that_do_not_send_them() -> None:
    for game, brakes_reason, engine_reason in (
        (Game.GT7, "GT7 doesn't send brake temperatures.", "GT7 doesn't send engine temperature."),
        (Game.FORZA_MOTORSPORT, "doesn't send brake temperatures", "doesn't send engine temperature"),
        (Game.AC, "doesn't send brake temperatures", "doesn't send engine temperature"),
    ):
        eng = CarHealthEngine("x")
        eng.feed(info(game=game, model=None))
        drive(eng, 0.0, 5.0, game=game, brakes_c=None, engine_c=None, inner=None)
        v = eng.view()
        assert v["brakes"]["available"] is False and brakes_reason in v["brakes"]["reason"], game
        assert v["engine"]["available"] is False and engine_reason in v["engine"]["reason"], game


def test_f1_view_has_both() -> None:
    eng = CarHealthEngine("f")
    eng.feed(info())
    drive(eng, 0.0, 200.0, lap_s=60.0)
    v = eng.view()
    assert v["brakes"]["available"] and v["brakes"]["word"] == "normal"
    assert v["engine"]["available"] and v["engine"]["now_c"] == 120 and v["engine"]["word"] == "steady"
