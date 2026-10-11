"""Motivation rules (pure): lap classes, clean runs, steady-lap windows, scopes, race outcomes, personal bests, weeks."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, datetime
from typing import Any

import pytest

from pitwall.motivation import rules
from pitwall.motivation.model import (
    Scope,
    car_class_label,
    display_car,
    lap_time,
    lap_time_radio,
    seconds,
    short_date,
)
from tests.unit.motivation_data import AUSTRIA_HAAS, T0, collision, lap, laps, penalty, sess


# ---------------------------------------------------------------------------------------------- lap classes and runs
def test_lap_classes() -> None:
    assert rules.lap_class(lap(2, 70_000)) == rules.CLEAN
    for f in ("invalid", "flashback", "distance_jump"):
        assert rules.lap_class(lap(2, 70_000, flags=[f])) == rules.BREAKER
    assert rules.lap_class(lap(2, 70_000, valid=False)) == rules.BREAKER
    for f in ("pit_in", "pit_out", "standing_start", "incomplete"):
        assert rules.lap_class(lap(2, 70_000, flags=[f])) == rules.NEUTRAL
    assert rules.lap_class(lap(2, None)) == rules.NEUTRAL
    # a breaker wins over a neutral flag (a flashback on an incomplete lap still ends a run)
    assert rules.lap_class(lap(2, None, flags=["flashback", "incomplete"])) == rules.BREAKER
    # not clean for another reason: neutral (defensive)
    assert rules.lap_class(lap(2, 70_000, clean=False)) == rules.NEUTRAL


def test_runs_breakers_neutral_and_gaps() -> None:
    ls = [
        lap(1, 80_000, flags=["standing_start"]),  # neutral: skipped
        lap(2, 71_000),
        lap(3, 71_100),
        lap(4, 72_000, flags=["pit_in"]),  # neutral: does not break
        lap(5, 71_200),
        lap(6, 71_300, flags=["invalid"]),  # breaker
        lap(7, 71_000),
        lap(8, 71_100),
        lap(10, 71_000),  # lap 9 missing: nobody knows what happened -> new run
        lap(11, 71_000),
    ]
    rs = rules.runs(ls)
    assert [[x.lap_number for x in r] for r in rs] == [[2, 3, 5], [7, 8], [10, 11]]
    assert [x.lap_number for x in rules.best_run(ls)] == [2, 3, 5]
    assert rules.best_run([]) == []


def test_runs_after_lap_id_cuts() -> None:
    ls = laps("s1", [71_000, 71_100, 71_200, 71_300])
    cut = ls[1].id
    assert [[x.lap_number for x in r] for r in rules.runs(ls, after_lap_id=cut)] == [[3, 4]]
    assert [x.lap_number for x in rules.run_ending_at(ls, ls[2].id)] == [1, 2, 3]
    assert rules.run_ending_at(ls, 999_999_999) == []


def test_windows_skip_race_lap_one() -> None:
    ls = laps("s1", [90_000, 71_000, 71_400, 71_200, 71_900])  # lap 1 clean (not flagged standing_start)
    ws = rules.windows(ls, 3, "race")
    assert [tuple(x.lap_number for x in w.laps) for w in ws] == [(2, 3, 4), (3, 4, 5)]
    assert [w.spread_ms for w in ws] == [400, 700]
    best = rules.best_window(ls, 3, "race")
    assert best is not None and best.spread_ms == 400 and best.last.lap_number == 4
    # outside a race lap 1 counts
    assert rules.best_window(ls, 3, "practice") is not None
    assert len(rules.windows(ls, 3, "practice")) == 3
    assert rules.best_window(ls, 5, "race") is None
    # a window never spans a breaker
    broken = [lap(1, 71_000), lap(2, 71_000), lap(3, 71_000, flags=["flashback"]), lap(4, 71_000)]
    assert rules.windows(broken, 3, "practice") == []


def test_incomplete_laps_end_a_run_mid_session_only() -> None:
    """Lost packets in the middle of a session: nobody knows what happened on that lap, so the run ends there (like
    a gap in lap numbers). Joined mid-lap (first), ended mid-lap (last) or a pit lap: still neutral."""
    ls = [
        lap(1, None, flags=["incomplete"]),  # joined mid-lap: neutral
        lap(2, 71_000),
        lap(3, 71_100),
        lap(4, 71_050, flags=["incomplete"]),  # packets lost mid-session: ends the run
        lap(5, 71_000),
        lap(6, 71_000),
        lap(7, 90_000, flags=["pit_in", "incomplete"]),  # into the garage: a pit lap, neutral
        lap(8, 71_200),
        lap(9, None, flags=["incomplete"]),  # the session ended mid-lap: neutral
    ]
    assert [[x.lap_number for x in r] for r in rules.runs(ls)] == [[2, 3], [5, 6, 8]]
    assert rules.windows(ls, 3, "practice")[0].laps[0].lap_number == 5


def test_safety_car_laps_end_a_steady_window() -> None:
    """Laps behind the safety car are naturally even: they never make a steady-lap window (they stay clean laps)."""
    ls = laps("s1", [71_000, 71_100, 71_050, 71_000, 71_100, 71_050])
    ls[2] = replace(ls[2], safety_car=True)
    ws = rules.windows(ls, 3, "practice")
    assert [tuple(x.lap_number for x in w.laps) for w in ws] == [(4, 5, 6)]
    assert [x.lap_number for x in rules.best_run(ls)] == [1, 2, 3, 4, 5, 6]  # still 6 clean laps in a row


def test_safety_car_spans_and_laps() -> None:
    def scar(t: int, what: int, kind: int = 1) -> dict[str, Any]:
        return {"kind": "safety_car", "t_recv_ns": t, "payload": {"safetyCarType": kind, "eventType": what}}

    events = [scar(5, 0, kind=3), scar(6, 2, kind=3), scar(100, 0), scar(150, 1), scar(200, 3), scar(500, 0, kind=2)]
    spans = rules.safety_car_spans(events)
    assert spans == [(100, 200), (500, None)]  # the formation lap is ignored; still out at the end = open-ended

    def at(n: int, a: int | None, b: int | None) -> Any:
        return replace(lap(n, 71_000), t_start_ns=a, t_end_ns=b)

    assert not rules.behind_safety_car(at(1, 0, 90), spans)
    assert rules.behind_safety_car(at(2, 90, 180), spans)  # deployed during the lap
    assert rules.behind_safety_car(at(3, 180, 270), spans)  # the restart lap
    assert not rules.behind_safety_car(at(4, 270, 360), spans)
    assert rules.behind_safety_car(at(5, 600, 700), spans)  # the VSC never came in: unknown counts as out
    assert not rules.behind_safety_car(at(6, None, None), spans)  # no receive times: never guessed


# ---------------------------------------------------------------------------------------------- scopes
def test_scope_matching_car_class_and_layout_tolerance() -> None:
    s = sess("s1")
    assert rules.scope_matches(AUSTRIA_HAAS, s)
    assert rules.scope_matches(Scope(), s)  # anywhere
    assert not rules.scope_matches(Scope(game="f1_25", track_id="f1:13"), s)
    assert not rules.scope_matches(Scope(game="f1_25", track_id="f1:17", car_id="f1:team:1"), s)
    cls = Scope(game="f1_25", track_id="f1:17", car_class="f1_25:formula:F1 World")
    assert rules.scope_matches(cls, s)
    assert not rules.scope_matches(cls, sess("s2", formula="F2"))
    # 3 % layout tolerance; an unknown length matches
    assert rules.scope_matches(AUSTRIA_HAAS, sess("s3", track_length_m=4318.0 * 1.029))
    assert not rules.scope_matches(AUSTRIA_HAAS, sess("s4", track_length_m=4318.0 * 1.05))
    assert rules.scope_matches(AUSTRIA_HAAS, sess("s5", track_length_m=None))


def test_car_class_keys_and_labels() -> None:
    assert rules.session_car_class(sess("s", formula="F1 World")) == "f1_25:formula:F1 World"
    assert rules.session_car_class(sess("s", formula=None)) is None
    forza = sess("f", game="forza_motorsport", formula=None, car_class=5, car_name="Mazda")
    assert rules.session_car_class(forza) == "forza_motorsport:class:5"
    assert rules.session_car_class(sess("g", game="gt7", formula=None, car_class=5)) is None  # never guessed
    assert car_class_label("f1_25:formula:F1 World") == "any F1 World car"
    assert car_class_label("forza_motorsport:class:5", "Mazda") == "any car of the same class as the Mazda"
    assert car_class_label("forza_motorsport:class:5") == "any car of the same class"
    assert Scope(game="f1_25", track_id="f1:17", track_name="Austria", car_class="f1_25:formula:F1 World").text() == (
        "Austria · any F1 World car"
    )
    assert AUSTRIA_HAAS.text() == "Austria · Haas"
    assert Scope().text() is None


# ---------------------------------------------------------------------------------------------- races
def race(sid: str = "r1", total: int | None = 3, **kw: Any) -> Any:
    return sess(sid, session_type="race", total_laps=total, formula="F1 Generic", **kw)


def test_race_outcome_counts_only_the_players_incidents() -> None:
    s = race()
    ls = laps("r1", [88_524, 78_351, 78_400])
    events = [
        penalty(5, infringement=4),  # warning: shown, never counted
        penalty(3, infringement=7),  # penalty reminder: shown, never counted
        penalty(4, vehicle=7),  # another car's time penalty
        collision(19, 4),
        collision(4, 19),
        collision(4, 7),  # not the player (only stored when it is; counted defensively anyway)
        {"kind": "flashback", "payload": {"flashbackFrameIdentifier": 1}},
    ]
    o = rules.race_outcome(s, ls, events[:-1])
    assert (o.finished, o.from_start, o.evaluable) == (True, True, True)
    assert (o.contacts, o.penalties, o.warnings, o.flashbacks, o.resets) == (2, 0, 2, 0, 0)
    assert o.no_penalties and not o.no_contact
    # a counted penalty type and a flashback
    o2 = rules.race_outcome(s, ls, [penalty(4, infringement=3)])
    assert o2.penalties == 1 and not o2.no_penalties
    o3 = rules.race_outcome(s, ls, events)
    assert o3.flashbacks == 1 and not o3.no_penalties
    # nothing at all: no penalties and no contact
    assert rules.race_outcome(s, ls, []).no_contact


def test_race_outcome_unknown_player_is_not_evaluable() -> None:
    s = race()
    ls = laps("r1", [88_524, 78_351, 78_400])
    o = rules.race_outcome(s, ls, [collision(19, 4, player=None)])
    assert not o.incidents_known and not o.evaluable and not o.no_penalties and not o.no_contact


def test_finished_from_start_and_resets() -> None:
    ls = laps("r1", [88_524, 78_351, 78_400])
    assert not rules.race_outcome(race(total=None), ls, []).evaluable  # length unknown (recorded before v3)
    assert not rules.race_outcome(race(total=5), ls, []).finished  # last lap not stored
    incomplete = [*ls[:2], lap(3, None, sid="r1", flags=["incomplete"])]
    assert not rules.race_outcome(race(), incomplete, []).finished
    joined = laps("r1", [71_000, 70_900], first=70)  # joined at lap 70 of 71
    o = rules.race_outcome(race(total=71), joined, [])
    assert o.finished and not o.from_start and not o.evaluable
    reset = [ls[0], lap(2, 79_000, sid="r1", flags=["distance_jump"]), ls[2]]
    o2 = rules.race_outcome(race(), reset, [])
    assert o2.resets == 1 and o2.evaluable and not o2.no_penalties
    assert not rules.race_outcome(sess("q", session_type="qualifying", total_laps=3), ls, []).race
    assert not rules.race_outcome(race(game="gt7"), ls, []).race  # GT7 / AC / Forza: no session type, never judged


def test_a_lapped_finisher_takes_the_flag() -> None:
    """A lapped car (or a race shortened by a red flag) never drives lap ``total_laps``: F1's chequered flag and a
    complete last lap that ended after it say the race was finished."""

    def timed(n: int, ms: int | None, a: int, b: int, flags: tuple[str, ...] = ()) -> Any:
        return replace(lap(n, ms, sid="r1", flags=flags), t_start_ns=a, t_end_ns=b)

    flag = [{"kind": "chequered_flag", "t_recv_ns": 250, "payload": {}}]
    lapped = [timed(1, 88_524, 0, 100), timed(2, 78_351, 100, 200), timed(3, 78_400, 200, 300)]
    o = rules.race_outcome(race(total=4), lapped, flag)
    assert o.finished and o.evaluable and (o.final_lap_id, o.final_lap_number) == (lapped[2].id, 3)
    assert not rules.race_outcome(race(total=4), lapped, []).finished  # no flag recorded: unknown
    retired = lapped[:2]  # stopped before the flag
    assert not rules.race_outcome(race(total=4), retired, flag).finished
    cut = [*lapped[:2], timed(3, None, 200, 260, ("incomplete",))]  # quit after the flag, mid-lap
    assert not rules.race_outcome(race(total=4), cut, flag).finished
    full = rules.race_outcome(race(total=3), lapped, [])
    assert full.finished and full.final_lap_number == 3


# ---------------------------------------------------------------------------------------------- bests
def test_ideal_lap_and_session_bests() -> None:
    a = [
        lap(1, 71_745, sid="a", sectors=(18_300, 30_900, 22_545)),
        lap(2, 72_000, sid="a", sectors=(18_200, 31_000, 22_800)),
    ]
    b = [lap(1, 70_549, sid="b", sectors=(18_250, 30_000, 22_299)), lap(2, 69_000, sid="b", flags=["invalid"])]
    assert rules.ideal_lap(a + b) == 18_200 + 30_000 + 22_299
    assert rules.ideal_lap([lap(1, 70_000)]) is None  # no sectors (GT7, AC, Forza)
    bests = rules.session_bests([sess("a", T0), sess("b", T0 + 60)], {"a": a, "b": b})
    assert [(x.session.id, x.best_ms, x.previous_ms, x.is_pb, x.gain_ms) for x in bests] == [
        ("a", 71_745, None, False, None),
        ("b", 70_549, 71_745, True, 1196),
    ]
    assert rules.recent_gain_ms(bests, T0 + 120) == 1196
    assert rules.recent_gain_ms(bests, T0 + 61 * 86_400) is None  # older than 60 days


def test_recent_gain_is_the_median_of_the_last_three() -> None:
    times = [80_000, 79_000, 78_500, 78_400, 77_000]  # gains 1000, 500, 100, 1400
    sessions = [sess(f"s{i}", T0 + i) for i in range(len(times))]
    ls = {f"s{i}": [lap(1, ms, sid=f"s{i}")] for i, ms in enumerate(times)}
    bests = rules.session_bests(sessions, ls)
    assert rules.recent_gain_ms(bests, T0 + 10) == 500  # median of 500, 100, 1400


def test_pb_streak() -> None:
    times = [72_000, 71_500, 71_000, 71_200, 70_900]
    sessions = [sess(f"s{i}", T0 + i) for i in range(len(times))]
    ls = {f"s{i}": [lap(1, ms, sid=f"s{i}")] for i, ms in enumerate(times)}
    st = rules.pb_streak(rules.session_bests(sessions, ls))
    assert st.per_session == (0, 1, 2, 0, 1)  # the first session is never a gain
    assert (st.current, st.best) == (1, 2)


# ---------------------------------------------------------------------------------------------- weeks and wording
@pytest.fixture
def london() -> Iterator[None]:
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available on this platform")
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/London"
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_week_math_across_the_clock_change(london: None) -> None:
    # BST ends at 02:00 on Sunday 25 Oct 2026: that Sunday has 25 hours, so "+ 7 * 86400" would drift.
    sunday_late = datetime(2026, 10, 25, 23, 30).timestamp()
    monday = datetime(2026, 10, 26, 0, 10).timestamp()
    assert rules.week_of(sunday_late) == date(2026, 10, 19)
    assert rules.week_of(monday) == date(2026, 10, 26)
    assert rules.week_of(datetime(2026, 10, 19, 0, 0).timestamp()) == date(2026, 10, 19)
    from pitwall.motivation.digest import week_bounds

    start, end = week_bounds(date(2026, 10, 19))
    assert end - start == 7 * 86_400 + 3600  # one hour longer: the week still ends at local midnight
    assert datetime.fromtimestamp(end).hour == 0


def test_wording_helpers() -> None:
    assert lap_time(70_549) == "1:10.549" and lap_time(23_055) == "0:23.055"
    assert lap_time_radio(70_000) == "1:10" and lap_time_radio(70_300) == "1:10.3"
    assert lap_time_radio(23_000) == "23 seconds" and lap_time_radio(23_500) == "23.5 seconds"  # never "0:23"
    assert display_car("Haas") == "Haas" and display_car("Unknown team (id 214)") is None and display_car(None) is None
    assert seconds(1100) == "1.1" and seconds(1230) == "1.230" and seconds(1100, tenths_when_whole=False) == "1.100"
    assert short_date(datetime(2026, 10, 10, 12).timestamp()) == "Sat 10 Oct"
