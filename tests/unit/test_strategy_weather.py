"""Weather and forecast (``strategy.weather``): this session's samples only, a change counts after two Session
packets, minutes to laps, and the crossover (game estimate) after two TyreSets samples. Synthetic/unit only: no real
capture has rain yet."""

from __future__ import annotations

from pitwall.strategy.weather import WeatherTracker, category
from tests.unit.strategy_helpers import session, tyre_set, tyre_sets


def _fc(rain_at: int | None = None, stype: int = 15) -> list[dict[str, object]]:
    out = []
    for off in (0, 5, 10, 15, 30):
        w = "light_rain" if rain_at is not None and off >= rain_at else "clear"
        out.append({"time_offset_min": off, "weather": w, "rain_pct": 60 if w != "clear" else 5, "session_type": stype})
    return out


def test_categories() -> None:
    assert category("overcast") == "dry" and category("light_rain") == "light_rain"
    assert category("storm") == "heavy_rain" and category(None) is None and category("fog") is None


def test_next_change_needs_two_packets_and_uses_this_sessions_samples() -> None:
    w = WeatherTracker()
    other = [dict(s, session_type=1) for s in _fc(rain_at=5)]  # practice samples riding along: ignored
    w.on_session(session(forecast=_fc() + other))
    assert w.next_change is None and len(w.samples) == 5
    w.on_session(session(forecast=_fc(rain_at=10)))
    assert w.next_change is None  # one packet only
    w.on_session(session(forecast=_fc(rain_at=10)))
    assert w.next_change == {"in_min": 10, "weather": "light_rain", "rain_pct": 60}
    v = w.view(60.0)
    assert v["next_change"]["in_laps"] == 10 and v["accuracy"] == "perfect" and v["rain_pct"] == 5  # type: ignore[index]
    assert [f["in_min"] for f in v["forecast"]] == [5, 10, 15, 30]
    w.on_session(session(forecast=_fc()))
    assert w.next_change is None


def test_change_beyond_the_horizon_is_not_announced() -> None:
    w = WeatherTracker()
    for _ in range(2):
        w.on_session(session(forecast=_fc(rain_at=30)))
    assert w.next_change is None


def test_rain_percentage_is_the_games_number() -> None:
    w = WeatherTracker()
    w.on_session(session(forecast=[{"time_offset_min": 0, "weather": "clear", "rain_pct": 13, "session_type": 15}]))
    assert w.view(None)["rain_pct"] == 13


def test_crossover_needs_two_samples() -> None:
    w = WeatherTracker()
    sets = [tyre_set(0, "medium", fitted=True), tyre_set(1, "inter", delta_ms=-800), tyre_set(2, "wet", delta_ms=600)]
    w.on_tyre_sets(tyre_sets(0.0, sets))
    assert w.crossover is None
    w.on_tyre_sets(tyre_sets(1.0, sets))
    assert w.crossover is not None and (w.crossover.compound, w.crossover.gain_s) == ("inter", 0.8)
    assert w.view(None)["crossover"] == {"compound": "inter", "gain_s": 0.8, "tier": "game"}
    dry = [tyre_set(0, "medium", fitted=True), tyre_set(1, "inter", delta_ms=2500)]
    w.on_tyre_sets(tyre_sets(2.0, dry))
    assert w.crossover is None
    back = [tyre_set(0, "inter", fitted=True), tyre_set(1, "soft", delta_ms=-1200)]
    w.on_tyre_sets(tyre_sets(3.0, back))
    w.on_tyre_sets(tyre_sets(4.0, back))
    assert w.crossover is not None and w.crossover.compound == "slick"
