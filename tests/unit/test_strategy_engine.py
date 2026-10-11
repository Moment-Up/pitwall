"""The strategy engine (``strategy.engine``) on constructed item sequences: mode by session type, the lap ledger,
records, flashbacks and the ``StrategyView`` contract (keys and types the dashboard is built against)."""

from __future__ import annotations

from typing import Any

import orjson
import pytest

from pitwall.model.telemetry import EventKind, Game, GameEvent, SessionType
from pitwall.strategy.engine import REASON_NOT_F1, StrategyEngine
from pitwall.strategy.view import off_view
from tests.unit.strategy_helpers import car, completion, frame, session, timing, tyre_set, tyre_sets

LAP_S = 80.0


def drive(
    e: StrategyEngine,
    laps: range,
    *,
    t0: float = 0.0,
    burn: float = 1.4,
    wear: float = 1.5,
    fuel0: float = 30.0,
    pit_lap: int | None = None,
) -> float:
    """Feed frames, timing and lap completions for whole laps (4318 m in LAP_S)."""
    t = t0
    for lap in laps:
        for k in range(0, 20):
            frac = k / 20
            done = (lap - 1) + frac
            w = 10.0 + wear * done
            pit = 1 if pit_lap == lap and frac > 0.9 else 0
            e.feed(
                frame(
                    t,
                    lap,
                    4318 * frac,
                    fuel=fuel0 - burn * done,
                    wear=(w, w, w - 2, w - 2),
                    age=lap - 1,
                    pit=pit,
                    throttle=1.0 if frac < 0.7 else 0.0,
                )
            )
            if k % 4 == 0:
                me = car(
                    1,
                    2,
                    lap=lap,
                    dist=4318 * frac,
                    gap_ms=1500,
                    leader_ms=1500,
                    player=True,
                    pit=pit,
                    last_ms=int(LAP_S * 1000) if lap > 1 else None,
                )
                e.feed(
                    timing(
                        t,
                        [
                            car(0, 1, lap=lap, dist=4318 * frac + 100, gap_ms=None),
                            me,
                            car(2, 3, lap=lap, dist=4318 * frac - 60, gap_ms=900),
                        ],
                    )
                )
            t += LAP_S / 20
        e.feed(completion(lap, int(LAP_S * 1000), t))
    return t


@pytest.mark.parametrize(
    ("stype", "game", "mode", "reason"),
    [
        (SessionType.RACE, Game.F1_25, "race", None),
        (SessionType.PRACTICE, Game.F1_25, "practice", None),
        (SessionType.QUALIFYING, Game.F1_25, "off", "qualifying"),
        (SessionType.TIME_TRIAL, Game.F1_25, "off", "time trial"),
        (SessionType.RACE, Game.GT7, "off", REASON_NOT_F1),
    ],
)
def test_mode_by_session_type(stype: SessionType, game: Game, mode: str, reason: str | None) -> None:
    e = StrategyEngine("s1")
    assert e.view()["mode"] == "off" and e.view()["reason"] == "no session information yet"
    e.feed(session(stype, game=game))
    v = e.view()
    assert v["mode"] == mode and v["reason"] == reason
    if mode == "off":
        assert v == off_view(reason, "s1")


def test_race_view_contract_and_records() -> None:
    e = StrategyEngine("s1")
    e.feed(session(total_laps=20))
    e.feed(
        tyre_sets(
            0.0,
            [
                tyre_set(0, "medium", life=25, usable=30, fitted=True),
                tyre_set(1, "hard", life=35, delta_ms=-400),
                tyre_set(2, "inter", delta_ms=3000),
            ],
        )
    )
    drive(e, range(1, 8))
    v = e.view()
    assert set(v) == {
        "version",
        "mode",
        "reason",
        "session_id",
        "synthetic",
        "lap",
        "total_laps",
        "laps_remaining",
        "position",
        "cars",
        "gaps",
        "tyres",
        "fuel",
        "pit",
        "safety_car",
        "weather",
        "calls",
    }
    assert v["version"] == 1 and v["mode"] == "race" and v["lap"] == 7 and v["position"] == 2 and v["cars"] == 3
    assert set(v["gaps"]) == {"ahead", "behind", "leader_s", "note"}
    assert set(v["gaps"]["ahead"]) == {
        "car_index",
        "gap_s",
        "settled",
        "trend_s_per_lap",
        "trend_laps",
        "laps_to_1s",
        "within_1s",
        "drs_range",
        "stops",
        "in_pit",
        "tyre",
    }
    assert set(v["tyres"]) == {
        "compound",
        "age_laps",
        "stint_laps",
        "wear_pct",
        "limiting_wheel",
        "rate_pct_per_lap",
        "rate_range",
        "limit_pct",
        "laps_to_limit",
        "enough_laps",
        "note",
        "game_laps_left",
        "game_usable_life",
        "new_set",
    }
    assert set(v["fuel"]) == {
        "fuel_kg",
        "per_lap_kg",
        "laps_used",
        "margin_laps",
        "margin_kg",
        "game_margin_laps",
        "status",
        "lift_coast",
        "burn_model",
    }
    assert set(v["pit"]) == {
        "stops_done",
        "stop_needed",
        "two_stops",
        "window",
        "game_window",
        "pit_loss",
        "pit_loss_sc",
        "pit_entry_m",
        "rejoin",
        "undercut_ahead",
        "undercut_threat",
        "neighbour_stop",
        "note",
    }
    assert set(v["safety_car"]) == {"status", "since_lap", "box"}
    assert set(v["weather"]) == {"now", "rain_pct", "track_temp_c", "accuracy", "forecast", "next_change", "crossover"}
    t = v["tyres"]
    assert (
        t["enough_laps"]
        and t["limiting_wheel"] in ("FL", "FR")
        and t["rate_pct_per_lap"] == pytest.approx(1.5, abs=0.2)
    )
    assert t["game_laps_left"] == 25 and t["new_set"]["compound"] == "hard" and t["new_set"]["gain_s"] == 0.4
    # first to last frame of each lap (19 of the 20 steps here)
    assert v["fuel"]["per_lap_kg"] == pytest.approx(1.4 * 0.95, abs=0.01) and v["fuel"]["status"] == "ok"
    assert v["gaps"]["ahead"]["gap_s"] == 1.5 and v["gaps"]["behind"]["within_1s"] is True
    raw = orjson.dumps(v)
    assert len(raw) < 2500  # rides every snapshot
    records = dict(e.take_records())
    assert sorted(records) == list(range(1, 7))  # lap 7's line window has not run yet
    r = records[5]
    assert {
        "v",
        "lap",
        "position",
        "cars",
        "lap_time_ms",
        "gap_ahead_ms",
        "ahead_car",
        "gap_behind_ms",
        "behind_car",
        "pit",
        "stops",
        "compound",
        "tyre_age_laps",
        "wear_pct",
        "fuel_kg",
        "fuel_per_lap_kg",
        "fuel_margin_laps",
        "game_fuel_margin_laps",
        "safety_car",
        "weather",
        "rain_pct",
        "next_weather",
        "window",
        "undercut_ahead",
        "undercut_threat",
        "tyre_gain_s",
        "calls",
        "total_laps",
    } <= set(r)
    assert r["lap"] == 5 and r["lap_time_ms"] == 80000 and r["ahead_car"] == 0 and r["gap_ahead_ms"] == 1500
    e.end()
    assert [lap for lap, _ in e.take_records()] == [7]


def test_practice_has_no_gaps_pit_or_calls() -> None:
    e = StrategyEngine("p1")
    e.feed(session(SessionType.PRACTICE, total_laps=0))
    drive(e, range(1, 6))
    v = e.view()
    assert v["mode"] == "practice" and v["gaps"] is None and v["pit"] is None and v["safety_car"] is None
    assert v["tyres"] is not None and v["fuel"]["per_lap_kg"] is not None and v["calls"] == []
    assert e.take_calls() == [] and e.take_records() == []


def test_flashback_rebuilds_the_ledger() -> None:
    e = StrategyEngine("s1")
    e.feed(session(total_laps=20))
    t = drive(e, range(1, 6))
    assert 5 in e.ledger and e.ledger[5].complete
    assert [lap for lap, _ in e.take_records()] == [1, 2, 3, 4]
    rewind_to = t - LAP_S * 1.5  # back into lap 4
    e.feed(
        GameEvent(
            kind=EventKind.FLASHBACK,
            game=Game.F1_25,
            t_recv_ns=0,
            code="FLBK",
            session_time_s=t,
            payload={"flashbackSessionTime": rewind_to},
        )
    )
    assert 5 not in e.ledger and e.ledger[4].flashback and not e.ledger[4].complete
    drive(e, range(4, 7), t0=rewind_to)
    assert e.ledger[4].complete and e.ledger[4].flashback and not e.ledger[4].green
    assert e.ledger[5].green
    assert [lap for lap, _ in e.take_records()] == [4, 5]  # lap 4 written again (an upsert in the database)


def test_clock_going_back_is_a_rewind_too() -> None:
    e = StrategyEngine("s1")
    e.feed(session(total_laps=20))
    t = drive(e, range(1, 4))
    e.feed(frame(t - 100.0, 2, 3000.0))
    assert 3 not in e.ledger and e.ledger[2].flashback


def test_pit_laps_and_safety_car_laps_are_not_green() -> None:
    e = StrategyEngine("s1")
    e.feed(session(total_laps=20))
    t = drive(e, range(1, 4), pit_lap=3)
    e.feed(frame(t, 4, 0.0))
    e.feed(session(total_laps=20, sc="full"))
    drive(e, range(4, 5), t0=t)
    assert e.ledger[3].pit_in and not e.ledger[3].green
    assert e.ledger[4].sc == "full" and not e.ledger[4].green
    assert e.excluded_laps() == frozenset({1, 4})


def test_view_is_strict_json_without_nan() -> None:
    e = StrategyEngine("s1")
    e.feed(session(total_laps=20))
    e.feed(frame(1.0, 1, float("nan"), fuel=float("nan")))
    raw = orjson.dumps(e.view())
    assert b"NaN" not in raw


def _calls(e: StrategyEngine) -> list[dict[str, Any]]:
    return [c.to_dict() for c in e.take_calls()]


def test_finished_race_has_nothing_left_to_run() -> None:
    e = StrategyEngine("s1")
    e.feed(session(total_laps=3))
    drive(e, range(1, 4))
    assert e.laps_remaining() == 0.0
    assert [lap for lap, _ in e.take_records()][-1] == 3  # the final lap is recorded at the flag


def test_lap_seen_only_from_mid_lap_never_counts_for_fuel_or_wear() -> None:
    """A split or resumed session that starts mid-lap sees only part of its first lap: its fuel and wear are partial
    (a live run recorded 0.13 kg a lap and +39 laps of fuel from such a lap), so it is not a green lap for them."""
    e = StrategyEngine("s2")
    e.feed(session(total_laps=20))
    t = 0.0
    for k in range(12, 20):  # lap 2 from 60 % of the way round
        frac = k / 20
        e.feed(frame(t, 2, 4318 * frac, fuel=30.0 - 1.4 * (1 + frac), wear=(12.0, 12.0, 10.0, 10.0)))
        t += LAP_S / 20
    e.feed(completion(2, int(LAP_S * 1000), t))
    assert not e.ledger[2].from_start and "incomplete" in e.ledger[2].as_lap()["flags"]
    assert e.view()["fuel"]["per_lap_kg"] is None  # nothing measured from a partial lap
    drive(e, range(3, 6), t0=t, burn=1.4, fuel0=30.0)
    assert e.ledger[3].from_start and e.ledger[4].from_start
    v = e.view()
    assert v["fuel"]["per_lap_kg"] == pytest.approx(1.4 * 19 / 20, abs=0.01)  # drive() samples 0..95 % of a lap
    assert v["fuel"]["laps_used"] == 3  # laps 3-5, not the partial lap 2
    for _lap, rec in e.take_records():
        assert rec["fuel_per_lap_kg"] is None or rec["fuel_per_lap_kg"] > 1.0


def test_lap_first_seen_at_the_line_counts() -> None:
    e = StrategyEngine("s3")
    e.feed(session(total_laps=20))
    drive(e, range(4, 7))  # starts at lap 4, 0 m: seen from the line
    assert e.ledger[4].from_start and e.ledger[4].green


def test_a_lapped_player_finishes_a_lap_early_and_is_not_told_fuel_is_short() -> None:
    """Review exp4: a 10-lap race, 1.5 kg a lap from 14 kg, the leader 1.1 laps ahead. The player's race ends at the
    first line crossing after the leader takes the flag (lap 9 for the player): the true margin is +0.33 laps, and
    the engine used to say "Fuel critical: 0.4 laps short. Lift and coast..." on laps 4 and 7."""
    e = StrategyEngine("lapped", clock=lambda: 0.0)
    e.feed(session(total_laps=10))
    t, fuel = 0.0, 14.0
    calls = []
    for lap in range(1, 10):
        for k in range(20):
            t += 4.0
            d = k * 215.9
            fuel -= 1.5 / 20
            e.feed(frame(t, lap, d, fuel=fuel, game_margin=0.3))
            leader = car(3, 1, lap=lap + 1, dist=min(4300.0, d + 430.0), gap_ms=None)  # 1.1 laps ahead
            me = car(1, 18, player=True, lap=lap, dist=d, gap_ms=5000, leader_ms=88000)
            e.feed(timing(t, [leader, me, car(2, 19, lap=lap, dist=d - 300, gap_ms=5000)]))
        e.feed(completion(lap, 80000, t + 0.5))
        calls += [c.text for c in e.take_calls()]
        if lap == 7:
            assert e.d.laps_remaining == pytest.approx(2.05, abs=0.05)  # laps 8 and 9, not 8, 9 and 10
            assert e.view()["fuel"]["status"] == "ok" and e.view()["fuel"]["margin_laps"] > 0
    assert not [c for c in calls if "Fuel" in c]


def test_once_the_leader_has_finished_the_race_ends_at_the_next_line() -> None:
    e = StrategyEngine("flag")
    e.feed(session(total_laps=10))
    e.feed(frame(100.0, 9, 1000.0, fuel=5.0))
    e.feed(
        timing(100.0, [car(0, 1, lap=10, result="finished", gap_ms=None), car(1, 2, lap=9, dist=1000.0, player=True)])
    )
    assert e.laps_remaining() == pytest.approx(1 - 1000 / 4318, abs=0.01)


def test_the_fuel_verdict_is_judged_at_the_line_not_per_tick() -> None:
    """Review M4: the tile's margin swung -0.4 -> -0.7 -> -0.5 within a lap (flat out, then lifting); the radio judges
    at the line, and now so does the view. The tank itself stays live."""
    e = StrategyEngine("fuel")
    e.feed(session(total_laps=20))
    t = drive(e, range(1, 5), burn=1.4)
    tank = e.view()["fuel"]["fuel_kg"]
    seen, per_tick = set(), set()
    for k in range(1, 15):  # lap 5: burn hard early in the lap
        e.feed(frame(t + k * 4.0, 5, 4318 * k / 20, fuel=tank - 0.2 * k))
        v = e.view()["fuel"]
        seen.add((v["margin_laps"], v["status"]))
        per_tick.add(e.d.fuel.margin_laps if e.d.fuel is not None else None)
        assert v["fuel_kg"] == pytest.approx(tank - 0.2 * k, abs=0.01)  # the tank is live
    assert len(seen) == 1 and len(per_tick) > 5  # one verdict for the lap; per tick it would have moved


def test_window_calls_at_the_wear_limit_are_said_once() -> None:
    """Review exp2 through the engine: no tyre-sets data, 4 %/lap. The window used to become "laps N to N" every lap
    past the limit, and "Pit window is open: laps 19 to 19" came every three laps to the flag."""
    e = StrategyEngine("s4", clock=lambda: 0.0)
    e.feed(session(total_laps=30))
    t = 1000.0
    said: list[tuple[int | None, str]] = []
    for lap in range(1, 31):
        for k in range(10):
            t += 8.0
            d = k * 430.0
            w = 5.0 + (lap - 1) * 4.0 + k * 0.4
            e.feed(frame(t, lap, d, wear=(w, w, w, w), fuel=60 - lap * 1.5 - k * 0.15, game_margin=2.0))
            e.feed(
                timing(
                    t,
                    [
                        car(1, 5, player=True, lap=lap, dist=d, gap_ms=3000),
                        car(2, 6, lap=lap, gap_ms=3000),
                        car(3, 4, lap=lap, gap_ms=3000),
                    ],
                )
            )
        e.feed(completion(lap, 80000, t + 1))
        said += [(c.lap, c.text) for c in e.take_calls() if c.topic == "pit_window"]
        if lap == 20:
            assert e.view()["pit"]["window"]["overdue"] is True
    assert [text for _lap, text in said] == [
        "Pit window is open: laps 13 to 16.",
        "Last laps of the tyre window: box this lap or next.",
    ]


def test_stops_done_is_unknown_before_the_first_timing_tick() -> None:
    e = StrategyEngine("s5")
    e.feed(session(total_laps=20))
    e.feed(frame(1.0, 1, 10.0, fuel=30.0))
    assert e.view()["pit"]["stops_done"] is None
    e.feed(timing(1.5, [car(1, 1, player=True, lap=1, dist=20.0, stops=0)]))
    assert e.view()["pit"]["stops_done"] == 0
