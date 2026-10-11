"""Proactive strategy calls (``strategy.calls``): every trigger, cooldowns, per-lap budgets, silences, priority order,
length, and the rule that no call ever tells the driver to brake later."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

import pytest

from pitwall.strategy.calls import MAX_TEXT, CallContext, CallPlanner, StrategyCall

BRAKE_LATER = re.compile(r"brake\w* later", re.I)
WINDOW = {"open_lap": 18, "close_lap": 22, "ideal_lap": 20}


def ctx(**kw: Any) -> CallContext:
    base: dict[str, Any] = {
        "t": 100.0,
        "lap": 10,
        "total_laps": 30,
        "laps_remaining": 20.5,
        "player_in_pit": False,
        "blocked": None,
    }
    base.update(kw)
    return CallContext(**base)


def topics(calls: list[StrategyCall]) -> list[str]:
    return [c.topic for c in calls]


def test_safety_car_box_and_stay_out() -> None:
    p = CallPlanner(clock=lambda: 1.0)
    box = {"pit_loss_s": 10.2, "green_pit_loss_s": 19.4, "stop_needed": True, "this_lap": True, "tier": "heuristic"}
    (c,) = p.plan(ctx(sc_status="full", sc_period=1, sc_box=box, entry_ttl_s=12.0))
    assert c.topic == "sc_box" and c.level == "alert" and c.priority == "high" and c.bypass_quiet
    assert c.text == "Safety car. Pitting this lap is an option: a stop costs about 10 s now, 19 s under green."
    assert c.text_simple == "Safety car: a pit stop is cheap now, about 10 seconds instead of 19. You can pit this lap."
    assert c.ttl_s == 12.0 and c.audience == "all"
    assert not p.plan(ctx(sc_status="full", sc_period=1, sc_box=box, t=110.0))  # once per period
    (v,) = p.plan(ctx(sc_status="virtual", sc_period=2, sc_box={**box, "this_lap": False, "pit_loss_s": None}))
    assert v.text == "Virtual safety car. Pitting next lap is an option." and v.ttl_s == 60.0
    stay = {**box, "stop_needed": False}
    (s,) = p.plan(ctx(sc_status="full", sc_period=3, sc_box=stay))
    assert s.topic == "sc_stay" and s.level == "normal" and "no stop needed" in s.text
    assert s.text_simple == "Safety car: your tyres last to the finish, so no pit stop."


def test_safety_car_with_the_pit_entry_unknown_names_no_lap() -> None:
    # no stop seen in this race yet: the pit entry (and so "this lap or next") is unknown
    box = {"pit_loss_s": None, "green_pit_loss_s": None, "stop_needed": True, "this_lap": None, "tier": "heuristic"}
    (c,) = CallPlanner().plan(ctx(sc_status="full", sc_period=1, sc_box=box))
    assert c.text == "Safety car. Pitting is an option." and c.data["this_lap"] is None and c.ttl_s == 60.0
    assert c.text_simple == "Safety car: a pit stop costs less now."


def test_lap_one_allows_only_the_safety_car_and_critical_fuel() -> None:
    p = CallPlanner()
    box = {"pit_loss_s": None, "green_pit_loss_s": None, "stop_needed": True, "this_lap": True, "tier": "heuristic"}
    calls = p.plan(
        ctx(
            lap=1,
            new_lap=True,
            sc_status="full",
            sc_period=1,
            sc_box=box,
            fuel_status="short",
            fuel_margin_laps=-0.6,
            window=WINDOW,
            within_behind=4,
        )
    )
    assert topics(calls) == ["sc_box", "fuel"]


@pytest.mark.parametrize(
    ("kw", "why"),
    [
        ({"lap": 30}, "final lap"),
        ({"lap": 28, "laps_remaining": 0.7}, "a lapped player's final lap"),
        ({"player_in_pit": True}, "pit lane"),
        ({"blocked": "formation lap"}, "formation"),
        ({"blocked": "red flag"}, "red flag"),
    ],
)
def test_silences(kw: dict[str, Any], why: str) -> None:
    p = CallPlanner()
    assert p.plan(ctx(new_lap=True, fuel_status="short", fuel_margin_laps=-0.6, within_behind=4, **kw)) == [], why


def test_fuel_critical_cooldown_and_lift_coast_wording() -> None:
    p = CallPlanner()
    lnc = {"seconds_per_lap": 2.1, "corners": ["T3", "T4"]}
    (c,) = p.plan(ctx(new_lap=True, fuel_status="short", fuel_margin_laps=-0.3, lift_coast=lnc))
    assert (
        c.text
        == "Fuel critical: 0.3 laps short. Lift and coast about 2.1 s a lap before T3 and T4, brake at your normal point."
    )
    assert c.level == "alert" and c.bypass_quiet
    assert not p.plan(ctx(lap=11, new_lap=True, fuel_status="short", fuel_margin_laps=-0.4))  # 0.1 worse, 1 lap later
    assert topics(p.plan(ctx(lap=11, new_lap=True, fuel_status="short", fuel_margin_laps=-0.55))) == ["fuel"]
    assert topics(p.plan(ctx(lap=14, new_lap=True, fuel_status="short", fuel_margin_laps=-0.55))) == ["fuel"]
    assert not p.plan(ctx(lap=15, new_lap=False, fuel_status="short", fuel_margin_laps=-1.0))  # only at the line


def test_fuel_tight() -> None:
    p = CallPlanner()
    (c,) = p.plan(ctx(new_lap=True, fuel_status="tight", fuel_margin_laps=0.2))
    assert c.text == "Fuel is tight: plus 0.2 laps to the finish." and c.level == "normal"
    assert not p.plan(ctx(lap=13, new_lap=True, fuel_status="tight", fuel_margin_laps=0.2))
    assert p.plan(ctx(lap=14, new_lap=True, fuel_status="tight", fuel_margin_laps=0.02))[0].text.endswith(
        "right on the limit to the finish."
    )


def test_pit_window_open_and_last_laps() -> None:
    p = CallPlanner()
    (c,) = p.plan(ctx(lap=18, window=WINDOW))
    assert c.text == "Pit window is open: laps 18 to 22, best around 20."
    assert c.text_simple == "Pit stop window open: any lap from 18 to 22, best lap 20."
    assert not p.plan(ctx(lap=19, window={**WINDOW, "open_lap": 19}))  # the open lap just follows the current lap
    assert not p.plan(ctx(lap=19, window={"open_lap": 19, "close_lap": 26, "ideal_lap": None}))  # later: not news
    p = CallPlanner()
    p.plan(ctx(lap=18, window={"open_lap": 18, "close_lap": 26, "ideal_lap": None}))
    (m,) = p.plan(ctx(lap=19, window={"open_lap": 19, "close_lap": 23, "ideal_lap": None}))  # 3 laps earlier: news
    assert m.text == "Pit window is open: laps 19 to 23."
    (last,) = p.plan(ctx(lap=22, window={"open_lap": 19, "close_lap": 23, "ideal_lap": None}))
    assert last.level == "alert" and last.text == "Last laps of the tyre window: box this lap or next."
    assert last.text_simple == "Pit this lap or next: your tyres are nearly worn out."
    assert not p.plan(ctx(lap=22, window={"open_lap": 19, "close_lap": 23, "ideal_lap": None}, t=200.0))
    p2 = CallPlanner()
    p2.plan(ctx(lap=18, window=WINDOW))
    assert topics(p2.plan(ctx(lap=25, stops_done=1, window={"open_lap": 25, "close_lap": 27}))) == ["pit_window"]


def test_a_window_at_the_limit_is_not_announced_again_and_again() -> None:
    # The tyres reach the limit (no tyre-sets data: the heuristic window, 4 %/lap): the window shrinks to "lap N to N"
    # and then stays on the current lap. One "open", one "last laps", then nothing (review exp2: "Pit window is open:
    # laps 19 to 19" every three laps to the flag).
    p = CallPlanner()
    seq = {12: (13, 16, False), 13: (13, 16, False), 14: (14, 16, False), 15: (15, 16, False), 16: (16, 16, False)}
    seq |= {lap: (lap, lap, True) for lap in range(17, 30)}
    said = []
    for lap, (o, c, overdue) in seq.items():
        w = {"open_lap": o, "close_lap": c, "ideal_lap": None, "overdue": overdue, "close_source": "measured"}
        said += [(lap, x.text) for x in p.plan(ctx(lap=lap, t=100.0 + 80 * lap, window=w))]
    assert said == [
        (13, "Pit window is open: laps 13 to 16."),
        (15, "Last laps of the tyre window: box this lap or next."),
    ]


def test_the_game_figure_says_so_and_waits_after_a_stop() -> None:
    # just after a stop the game's laps-left figure for a used set is all there is (synthetic: it said "box" at 45 %
    # wear, 8 %/lap, a set that reached the flag at 61 %): no window call in the stint's first MIN_STINT_LAPS laps
    w = {"open_lap": 9, "close_lap": 11, "ideal_lap": None, "close_source": "game"}
    p = CallPlanner()
    assert not p.plan(ctx(lap=9, stops_done=1, stint_laps=2, window=w))
    assert not p.plan(ctx(lap=10, stops_done=1, stint_laps=3, window=w))
    (o,) = p.plan(ctx(lap=12, stops_done=1, stint_laps=5, window={**w, "open_lap": 12, "close_lap": 16}))
    assert o.text == "Pit window is open: laps 12 to 16, on the game's tyre figure."
    (last,) = p.plan(ctx(lap=15, stops_done=1, stint_laps=8, window={**w, "open_lap": 12, "close_lap": 16}))
    assert last.text == "The game's tyre figure says last laps of the window: box this lap or next."
    # the first stint: the game's figure is called at once, with its source
    (first,) = CallPlanner().plan(ctx(lap=2, stops_done=0, stint_laps=2, window={**w, "open_lap": 2}))
    assert first.text == "Pit window is open: laps 2 to 11, on the game's tyre figure."


def test_undercut_threat_needs_the_window_and_a_real_threat() -> None:
    threat = {"status": "marginal", "gap_s": 1.4}
    p = CallPlanner()
    assert not p.plan(ctx(lap=12, behind_pitting=6, undercut_threat=threat, window=WINDOW))  # window not open yet
    assert not p.plan(ctx(lap=19, behind_pitting=6, undercut_threat={"status": "unlikely"}, window=WINDOW))
    (c,) = p.plan(ctx(lap=19, behind_pitting=6, behind_stops=0, undercut_threat=threat, window=WINDOW, entry_ttl_s=-2))
    assert c.text == "Car behind is pitting. Box next lap to cover the undercut."
    assert c.priority == "high" and c.audience == "experienced" and c.ttl_s == 45.0
    assert not p.plan(ctx(lap=19, behind_pitting=6, behind_stops=0, undercut_threat=threat, window=WINDOW))  # same stop
    p2 = CallPlanner()
    (d,) = p2.plan(ctx(lap=19, behind_pitting=6, undercut_threat=threat, window=WINDOW, entry_ttl_s=30.0))
    assert "Box this lap" in d.text and d.ttl_s == 30.0


def test_undercut_chance_on_the_transition_only() -> None:
    p = CallPlanner()
    cut = {"status": "likely", "gap_s": 1.2}
    (c,) = p.plan(ctx(lap=19, undercut_ahead=cut, gain_s=1.5, window=WINDOW))
    assert c.text == "Undercut on the car ahead looks on: gap 1.2 s, new tyres worth about 1.5 s a lap."
    assert c.level == "detailed" and c.audience == "experienced" and c.text_simple is None
    assert not p.plan(ctx(lap=19, undercut_ahead=cut, gain_s=1.5, window=WINDOW, t=101.0))  # still likely


def test_neighbour_stop_wording() -> None:
    p = CallPlanner()
    ns = {"car": "ahead", "car_index": 2, "rejoin_gap_s": 4.2, "status": "covered", "traffic": False}
    (c,) = p.plan(ctx(ahead_pitting=ns))
    assert c.text == "Car ahead is pitting: it rejoins about 4 s behind you." and c.level == "detailed"
    (d,) = p.plan(ctx(lap=11, ahead_pitting={**ns, "car_index": 3, "status": "close", "traffic": True}))
    assert d.text == "Car ahead is pitting: it rejoins close to you. It rejoins in traffic."


def test_gap_within_and_cooldown_per_car() -> None:
    # detail, not a call to act on (real Austria: four times in ten laps at the normal setting was chatter)
    p = CallPlanner()
    (c,) = p.plan(ctx(lap=5, within_behind=4, drs_behind=True))
    assert c.text == "Car behind is within a second, DRS range." and c.level == "detailed"
    assert c.text_simple == "Car close behind you."
    assert not p.plan(ctx(lap=7, within_behind=4))
    assert not p.plan(ctx(lap=7, within_behind=5))  # another car, but a "within a second" two laps ago
    assert p.plan(ctx(lap=8, within_behind=5))[0].text == "Car behind is within a second."
    assert not p.plan(ctx(lap=14, within_behind=4))
    assert p.plan(ctx(lap=15, within_behind=4))


def test_no_gap_calls_under_a_safety_car_or_vsc() -> None:
    # the field bunches up behind the safety car; a gap call would also take the lap's slot from "stay out"
    trends = [{"side": "behind", "car_index": 2, "gap_s": 0.6, "slope": -0.5, "laps": 4, "laps_to_1s": 0.0}]
    stay = {"pit_loss_s": None, "green_pit_loss_s": None, "stop_needed": False, "this_lap": True, "tier": "heuristic"}
    for status in ("full", "virtual"):
        calls = CallPlanner().plan(
            ctx(sc_status=status, sc_period=1, sc_box=stay, within_behind=2, drs_behind=True, trends=trends)
        )
        assert topics(calls) == ["sc_stay"], status


def test_gap_trends() -> None:
    p = CallPlanner()
    trends = [
        {"side": "ahead", "car_index": 0, "gap_s": 2.4, "slope": -0.4, "laps": 4, "laps_to_1s": 3.5},
        {"side": "behind", "car_index": 2, "gap_s": 1.8, "slope": -0.3, "laps": 4, "laps_to_1s": 2.7},
    ]
    (c,) = p.plan(ctx(trends=trends))
    assert c.text == "Catching the car ahead: 2.4 s, about 0.4 s a lap." and c.level == "detailed"
    (d,) = p.plan(ctx(lap=11, trends=trends))
    assert d.text == "Car behind closing: 1.8 s, 0.3 s a lap."
    slow = [{"side": "ahead", "car_index": 7, "gap_s": 2.4, "slope": -0.1, "laps": 4, "laps_to_1s": 14}]
    assert not p.plan(ctx(lap=12, trends=slow))


def test_weather_and_crossover() -> None:
    p = CallPlanner()
    nc = {"in_min": 10, "weather": "light_rain", "rain_pct": 60, "in_laps": 7}
    (c,) = p.plan(ctx(next_weather=nc, weather_now="clear"))
    assert c.text == "Rain forecast in about 10 minutes, around 7 laps." and c.level == "alert" and not c.bypass_quiet
    assert c.text_simple == "Rain is coming in about 10 minutes."
    assert not p.plan(ctx(lap=11, next_weather=nc, weather_now="clear", t=250.0))  # 5 minute cooldown
    assert p.plan(ctx(lap=14, next_weather=nc, weather_now="clear", t=401.0))
    dry = CallPlanner().plan(
        ctx(next_weather={"in_min": 5, "weather": "overcast", "in_laps": None}, weather_now="light_rain")
    )
    assert dry[0].text == "Forecast says dry in about 5 minutes." and dry[0].level == "normal"
    (x,) = CallPlanner().plan(ctx(crossover={"compound": "inter", "gain_s": 0.8}))
    assert x.text == "Game's tyre model now has inters 0.8 s a lap faster than your slicks." and x.level == "alert"
    assert (
        x.text_simple == "The game says intermediate rain tyres are now 0.8 seconds a lap faster than your dry tyres."
    )


def test_no_rain_call_for_a_change_after_the_flag() -> None:
    # review: "L9 Rain forecast in about 10 minutes, around 10 laps" in a 12-lap race (an alert at every setting)
    nc = {"in_min": 10, "weather": "light_rain", "rain_pct": 60, "in_laps": 10}
    assert not CallPlanner().plan(ctx(lap=9, total_laps=12, laps_remaining=3.9, next_weather=nc, weather_now="clear"))
    assert not CallPlanner().plan(ctx(lap=3, total_laps=12, laps_remaining=10.0, next_weather=nc, weather_now="clear"))
    (c,) = CallPlanner().plan(ctx(lap=2, total_laps=12, laps_remaining=10.5, next_weather=nc, weather_now="clear"))
    assert c.topic == "weather"


def test_budget_one_normal_and_two_detailed_per_lap_and_priority_order() -> None:
    p = CallPlanner()
    nc = {"in_min": 10, "weather": "light_rain", "rain_pct": 60, "in_laps": 7}
    ns = {"car": "ahead", "car_index": 2, "rejoin_gap_s": 4.2, "status": "covered", "traffic": False}
    trends = [{"side": "ahead", "car_index": 0, "gap_s": 2.4, "slope": -0.4, "laps": 4, "laps_to_1s": 3.5}]
    calls = p.plan(
        ctx(
            lap=18,
            window=WINDOW,
            within_behind=4,
            new_lap=True,
            fuel_status="tight",
            fuel_margin_laps=0.2,
            next_weather=nc,
            weather_now="clear",
            ahead_pitting=ns,
            trends=trends,
            undercut_ahead={"status": "likely", "gap_s": 1.0},
            gain_s=1.6,
        )
    )
    # weather (alert) first; the one normal call is fuel tight (before the window and the gap); two detailed calls
    assert [(c.topic, c.level) for c in calls] == [
        ("weather", "alert"),
        ("fuel", "normal"),
        ("undercut_chance", "detailed"),
        ("neighbour_stop", "detailed"),
    ]


def test_texts_are_short_and_never_say_brake_later() -> None:
    p = CallPlanner()
    lnc = {"seconds_per_lap": 12.5, "corners": ["Turn 1 (Niki Lauda)", "Turn 3 (Remus)", "Turn 4 (Schlossgold)"]}
    calls = p.plan(ctx(new_lap=True, fuel_status="short", fuel_margin_laps=-3.25, lift_coast=lnc))
    calls += CallPlanner().plan(
        ctx(
            sc_status="virtual",
            sc_period=1,
            sc_box={"pit_loss_s": 123.4, "green_pit_loss_s": 234.5, "stop_needed": True, "this_lap": False},
        )
    )
    assert calls
    for c in calls:
        assert len(c.text) <= MAX_TEXT and not BRAKE_LATER.search(c.text)
    assert "brake at your normal point" in calls[0].text


def test_to_dict_contract() -> None:
    (c,) = CallPlanner(clock=lambda: 12.5).plan(ctx(within_behind=4))
    d = c.to_dict()
    assert set(d) == {
        "id",
        "topic",
        "level",
        "priority",
        "text",
        "text_simple",
        "lap",
        "ttl_s",
        "bypass_quiet",
        "audience",
        "data",
        "t_unix",
    }
    assert d["t_unix"] == 12.5 and d["lap"] == 10 and d["id"].startswith("st-gap-10-")
    assert replace(c, lap=3).lap == 3
