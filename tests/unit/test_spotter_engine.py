"""The spotter's state machine on the game clock (spec section 3; SYNTHETIC geometry)."""

from __future__ import annotations

import pytest

from pitwall.model.telemetry import EventKind
from pitwall.spotter.engine import PARAMS, SpotterEngine
from pitwall.spotter.model import REASONS
from pitwall.spotter.settings import SpotterSettings
from tests.unit.spotter_helpers import Car, engine, kinds, motion, passing, race_info, run

ALONGSIDE_L = {1: Car(0.0, -3.2)}
ALONGSIDE_R = {2: Car(0.0, 3.2)}


def _until_first(e: SpotterEngine, cars: dict[int, Car], t0: float, hz: float) -> float | None:
    for i in range(60):
        t = t0 + i / hz
        if e.feed_motion(motion(t, cars), int(t * 1e9)):
            return t
    return None


@pytest.mark.parametrize(("hz", "expected_delay"), [(60.0, 0.05), (20.0, 0.05), (10.0, 0.1)])
def test_onset_after_50_ms_of_game_time_and_not_before(hz: float, expected_delay: float) -> None:
    e = engine()
    run(e, lambda t: {}, 10.0, 11.0, hz)  # moving, nothing alongside
    t0 = 11.0 + 1 / hz
    t = _until_first(e, ALONGSIDE_L, t0, hz)
    assert t is not None and t - t0 == pytest.approx(expected_delay, abs=1e-6)


def test_receive_bunching_does_not_shorten_the_debounce() -> None:
    """Three packets 1 ms apart in receive time but 16.7 ms apart on the game clock: still 50 ms of game time."""
    e = engine()
    run(e, lambda t: {}, 10.0, 11.0)
    calls = []
    for i in range(3):
        t = 11.0 + i / 60
        calls += e.feed_motion(motion(t, ALONGSIDE_L, t_recv_ns=10**12 + i * 1_000_000), 0)
    assert calls == []
    calls += e.feed_motion(motion(11.0 + 3 / 60, ALONGSIDE_L, t_recv_ns=10**12 + 3_000_000), 0)
    assert kinds(calls) == ["car_left"]


def test_clear_after_150_ms_and_the_side_view() -> None:
    e = engine()
    calls = run(e, lambda t: ALONGSIDE_L if t < 12.0 else {}, 10.0, 11.99)
    assert kinds(calls) == ["car_left"]
    assert e.view()["left"]["state"] == "alongside" and e.view()["left"]["cars"] == 1
    assert e.view()["traffic"] is True
    calls = run(e, lambda t: {}, 12.0, 12.13)
    assert calls == []
    assert e.view()["left"]["state"] == "clear"  # the bars are instant; the radio waits
    assert e.view()["traffic"] is True  # cleared less than 1 s ago
    calls = run(e, lambda t: {}, 12.15, 12.2)
    assert kinds(calls)[:1] == ["clear_left"]
    run(e, lambda t: {}, 12.2, 13.2)
    assert e.view()["traffic"] is False


def test_lateral_hysteresis_in_line_enter_at_half_width_stay_at_0_35() -> None:
    e = engine()
    calls = run(e, lambda t: {1: Car(0.0, -0.8)}, 10.0, 11.0)  # 0.4 W: in line, never joins
    assert calls == []
    e = engine()
    calls = run(e, lambda t: {1: Car(0.0, -1.2 if t < 11.0 else -0.8)}, 10.0, 12.0)  # joined, then 0.4 W: stays
    assert kinds(calls) == ["car_left"]
    calls = run(e, lambda t: {1: Car(0.0, -0.6)}, 12.0, 13.0)  # 0.3 W: gone
    assert kinds(calls) == ["clear_left"]


def test_gap_hysteresis_enter_2_5_stay_3_0() -> None:
    # W = 2.0: gap = |lat| - 2.0
    e = engine()
    assert run(e, lambda t: {1: Car(0.0, -4.7)}, 10.0, 11.0) == []  # gap 2.7: not alongside
    e = engine()
    calls = run(e, lambda t: {1: Car(0.0, -4.4 if t < 11.0 else -4.9)}, 10.0, 12.0)  # gap 2.4, then 2.9: stays
    assert kinds(calls) == ["car_left"]
    assert kinds(run(e, lambda t: {1: Car(0.0, -5.2)}, 12.0, 13.0)) == ["clear_left"]  # gap 3.2: gone


def test_lengthwise_hysteresis_reach_plus_1_5_m() -> None:
    e = engine()
    # reach = 5.5 m for two aligned F1 cars; a member stays until 7.0 m
    calls = run(e, lambda t: {1: Car(5.0 if t < 11.0 else 6.8, -3.2)}, 10.0, 12.0)
    assert kinds(calls) == ["car_left"]
    assert kinds(run(e, lambda t: {1: Car(7.2, -3.2)}, 12.0, 13.0)) == ["clear_left"]


def test_lengthwise_arrival_hold_keeps_the_side_announced() -> None:
    """Car 1 leaves ahead while car 3 closes from behind on the same side, due within 1 s: no clear."""
    e = engine()

    def cars(t: float) -> dict[int, Car]:
        if t < 11.0:
            return {1: Car(0.0, -3.2)}
        return {1: Car(9.0, -3.2, vlon=4.0), 3: Car(-8.0 + 3.0 * (t - 11.0), -3.2, vlon=3.0)}

    calls = run(e, cars, 10.0, 12.0)
    assert kinds(calls) == ["car_left"]  # car 3 joins at t ~ 11.83: never cleared in between


def test_sideways_arrival_hold() -> None:
    e = engine()

    def cars(t: float) -> dict[int, Car]:
        if t < 11.0:
            return {1: Car(0.0, -3.2)}
        return {1: Car(0.0, -6.0, vlat=-1.5), 3: Car(1.0, -5.9 + 2.0 * (t - 11.0), vlat=2.0)}

    calls = run(e, cars, 10.0, 11.5)
    assert "clear_left" not in kinds(calls)


def test_three_wide_in_one_packet_and_in_sequence() -> None:
    e = engine()
    calls = run(e, lambda t: {**ALONGSIDE_L, **ALONGSIDE_R}, 10.0, 10.5)
    assert kinds(calls) == ["three_wide"]
    assert e.view()["three_wide"] is True
    e = engine()
    calls = run(e, lambda t: {**ALONGSIDE_L, **(ALONGSIDE_R if t >= 10.5 else {})}, 10.0, 11.0)
    assert kinds(calls) == ["car_left", "three_wide"]


def test_clear_all_round_after_three_wide_and_both_clearing_at_once() -> None:
    e = engine()
    run(e, lambda t: {**ALONGSIDE_L, **ALONGSIDE_R}, 10.0, 11.0)
    calls = run(e, lambda t: {}, 11.0, 12.0)
    assert kinds(calls) == ["clear_all_round"]  # one call, not "clear left" + "clear all round"
    e = engine()
    run(e, lambda t: {**ALONGSIDE_L, **ALONGSIDE_R}, 10.0, 11.0)
    calls = run(e, lambda t: ALONGSIDE_L if t < 12.0 else {}, 11.0, 13.0)
    assert kinds(calls) == ["clear_right", "clear_all_round"]


def test_clear_all_round_waits_for_a_car_arriving_on_the_other_side() -> None:
    e = engine()
    run(e, lambda t: {**ALONGSIDE_L, **ALONGSIDE_R}, 10.0, 11.0)
    calls = run(e, lambda t: ALONGSIDE_L if t < 12.0 else {}, 11.0, 12.0)
    assert kinds(calls) == ["clear_right"]
    # the left car goes; another one closes on the right within 1 s: "clear left", not "clear all round"
    calls = run(e, lambda t: {4: Car(-7.0 + 2.0 * (t - 12.0), 3.2, vlon=2.0)}, 12.0, 12.3)
    assert kinds(calls) == ["clear_left"]


def test_still_there_at_4_then_10_and_at_most_two_per_episode() -> None:
    e = engine()
    calls = run(e, lambda t: ALONGSIDE_L, 10.0, 30.0)
    got = [(c.kind, round(c.session_time_s - calls[0].session_time_s, 2)) for c in calls]
    assert got == [("car_left", 0.0), ("still_there", 4.0), ("still_there", 10.0)]
    assert calls[1].side == "left" and not calls[1].urgent and calls[0].urgent


def test_still_there_can_be_switched_off() -> None:
    e = engine(SpotterSettings(enabled=True, still_there=False))
    assert kinds(run(e, lambda t: ALONGSIDE_L, 10.0, 20.0)) == ["car_left"]


def _squeeze(closing: float, gap_end: float, start: float = 11.2) -> object:
    lat_end = -(2.0 + gap_end)

    def cars(t: float) -> dict[int, Car]:
        if t < start:
            return {1: Car(0.0, -3.2)}
        lat = min(lat_end, -3.2 + closing * (t - start))  # lat < 0: moving right closes the gap
        return {1: Car(0.0, lat, vlat=closing)}

    return cars


def test_hold_your_line_needs_close_closing_sustained_and_after_one_second() -> None:
    e = engine()
    calls = run(e, _squeeze(0.6, 0.2), 10.0, 14.0)  # type: ignore[arg-type]
    assert kinds(calls) == ["car_left", "hold_your_line"]
    hold = calls[1]
    assert hold.side == "left" and hold.session_time_s - calls[0].session_time_s >= PARAMS.hold_after_onset_s
    # once per episode
    assert "hold_your_line" not in kinds(run(e, _squeeze(0.6, 0.2, start=14.0), 14.0, 15.0))  # type: ignore[arg-type]
    # too slow a squeeze, or not close enough: nothing
    assert kinds(run(engine(), _squeeze(0.3, 0.2), 10.0, 14.0)) == ["car_left"]  # type: ignore[arg-type]
    assert kinds(run(engine(), _squeeze(0.6, 0.6), 10.0, 14.0)) == ["car_left"]  # type: ignore[arg-type]
    # too early after the onset (the car closes in at once)
    e = engine()
    calls = run(e, lambda t: {1: Car(0.0, -2.3, vlat=0.6)}, 10.0, 10.9)
    assert kinds(calls) == ["car_left"]


def test_short_overlap_is_not_spoken_but_shown() -> None:
    e = engine()
    run(e, lambda t: {}, 9.0, 9.9)
    # 30 m/s relative: 11 m of overlap last 0.37 s, less than the 0.30 s ear latency + 0.15 s
    calls = run(e, passing(-3.2, 30.0, -8.0, 10.0), 10.0, 10.6)
    assert calls == [] and e.suppressed_short == 1
    e = engine()
    e.set_ear_latency(0.1)  # a fast radio: 0.25 s is enough
    run(e, lambda t: {}, 9.0, 9.9)
    assert kinds(run(e, passing(-3.2, 30.0, -8.0, 10.0), 10.0, 10.6))[:1] == ["car_left"]


def test_ear_latency_is_clamped() -> None:
    e = engine()
    e.set_ear_latency(5.0)
    assert e.ear_latency_s == 1.0
    e.set_ear_latency(0.0)
    assert e.ear_latency_s == 0.1


def _first_reason(**kw: object) -> str | None:
    e = engine()
    kw2 = dict(kw)
    info = {k: kw2.pop(k) for k in list(kw2) if k in ("session_type", "safety_car", "paused")}
    if info:
        e.feed_session(race_info(**info))  # type: ignore[arg-type]
    e.feed_motion(motion(10.0, ALONGSIDE_L, **kw2), 0)  # type: ignore[arg-type]
    return e.reason


def test_gate_reasons_in_order() -> None:
    assert REASONS[0] == "disabled" and REASONS[-1] == "slow"
    e = SpotterEngine()  # off by default
    e.feed_motion(motion(10.0, ALONGSIDE_L), 0)
    assert e.reason == "disabled"
    assert _first_reason(lap=False) == "not_available"
    assert _first_reason(session_type=18) == "session_type"  # time trial: never
    assert _first_reason(session_type=0) == "session_type"
    assert _first_reason(session_type=5) == "session_type"  # qualifying only when switched on
    assert _first_reason(session_type=1, safety_car="full") == "session_type"  # first closed gate wins
    assert _first_reason(safety_car="virtual") == "safety_car"
    assert _first_reason(safety_car="formation_lap") == "safety_car"
    assert _first_reason(safety_car=None) == "safety_car"  # unknown stays unknown
    assert _first_reason(paused=True) == "paused"
    assert _first_reason(player_status=(1, 4, 2)) == "pit"
    assert _first_reason(player_status=(0, 4, 3)) == "finished"
    assert _first_reason(speed=5.0) == "slow"
    assert _first_reason() is None
    e = engine()
    e.feed_motion(motion(10.0, ALONGSIDE_L), 0, red_flag=True)
    assert e.reason == "red_flag"


def test_qualifying_and_practice_only_when_switched_on() -> None:
    for st, setting in ((5, "qualifying"), (14, "qualifying"), (1, "practice"), (4, "practice")):
        e = engine(SpotterSettings(enabled=True, **{setting: True}), session_type=st)
        e.feed_motion(motion(10.0, {}), 0)
        assert e.reason is None, (st, setting)


def test_a_closed_gate_forgets_the_traffic_and_never_says_clear() -> None:
    e = engine()
    assert kinds(run(e, lambda t: ALONGSIDE_L, 10.0, 11.0)) == ["car_left"]
    epoch = e.state().epoch
    e.feed_session(race_info(safety_car="full"))
    assert run(e, lambda t: {}, 11.0, 13.0) == []
    assert e.reason == "safety_car" and e.view()["left"]["state"] == "clear" and e.state().epoch > epoch
    e.feed_session(race_info())
    assert kinds(run(e, lambda t: ALONGSIDE_L, 13.0, 14.0)) == ["car_left"]  # a new episode


def test_speed_hysteresis_30_on_20_off() -> None:
    e = engine()
    e.feed_motion(motion(10.0, {}, speed=25 / 3.6), 0)
    assert e.reason == "slow"
    e.feed_motion(motion(10.1, {}, speed=31 / 3.6), 0)
    assert e.reason is None
    e.feed_motion(motion(10.2, {}, speed=25 / 3.6), 0)
    assert e.reason is None  # stays armed down to 20 km/h
    e.feed_motion(motion(10.3, {}, speed=19 / 3.6), 0)
    assert e.reason == "slow"


def test_lights_out_delay_and_armed_without_lights_out() -> None:
    e = engine()
    e.feed_event(EventKind.LIGHTS_OUT, 0.0)
    calls = run(e, lambda t: ALONGSIDE_L, 0.0, 4.9)
    assert calls == [] and e.reason == "start"
    calls = run(e, lambda t: ALONGSIDE_L, 5.0, 5.2)
    assert kinds(calls) == ["car_left"]
    e = engine(SpotterSettings(enabled=True, start_delay_s=0.0))
    e.feed_event(EventKind.LIGHTS_OUT, 0.0)
    assert kinds(run(e, lambda t: ALONGSIDE_L, 0.0, 0.2)) == ["car_left"]
    e = engine()  # joined late (no LGOT seen): armed at once
    assert kinds(run(e, lambda t: ALONGSIDE_L, 1.0, 1.2)) == ["car_left"]


@pytest.mark.parametrize("via_event", [True, False])
def test_flashback_or_rewind_resets_and_mutes_for_one_second(via_event: bool) -> None:
    e = engine()
    assert kinds(run(e, lambda t: ALONGSIDE_L, 10.0, 11.0)) == ["car_left"]
    if via_event:
        e.feed_event(EventKind.FLASHBACK, 11.0)
    calls = run(e, lambda t: ALONGSIDE_L, 6.0, 6.95)  # the clock went back 5 s
    assert calls == [] and e.reason == "flashback"
    calls = run(e, lambda t: ALONGSIDE_L, 7.0, 7.2)
    assert kinds(calls) == ["car_left"]


def test_stale_and_session_reset() -> None:
    e = engine()
    run(e, lambda t: ALONGSIDE_L, 10.0, 11.0)
    e.mark_stale()
    assert e.reason == "stale" and not e.active and e.state().announced == (False, False)
    assert kinds(run(e, lambda t: ALONGSIDE_L, 11.5, 12.0)) == ["car_left"]
    e.reset()
    assert e.reason == "not_available" and e.dims.formula is None
    e.feed_motion(motion(12.1, ALONGSIDE_L), 0)
    assert e.reason == "session_type"  # no Session packet of the new session yet


def test_invalid_player_vectors_skip_the_packet() -> None:
    e = engine()
    run(e, lambda t: ALONGSIDE_L, 10.0, 10.5)
    m = motion(10.6, ALONGSIDE_L)
    bad = (*m.cars[0][:6], 0.0, 0.0, 0.0, -32767.0, 0.0, 0.0)
    m2 = type(m)(m.t_recv_ns, m.session_time_s, m.frame_id, 0, 2025, (bad, *m.cars[1:]), m.status)
    assert e.feed_motion(m2, 0) == [] and e.invalid == 1 and e.state().announced == (True, False)


def test_view_contract() -> None:
    e = engine()
    run(e, lambda t: {1: Car(-1.84, -2.3)}, 10.0, 11.0)
    v = e.view()
    keys = {"v", "enabled", "active", "reason", "left", "right", "three_wide", "traffic", "rate_hz", "seq", "length_m"}
    assert set(v) == keys
    assert v["length_m"] == 5.5  # the F1 box by default (the iPad bars' scale)
    assert v["v"] == 1 and v["enabled"] and v["active"] and v["reason"] is None
    assert v["left"] == {"state": "close", "lon_m": -1.8, "gap_m": 0.3, "cars": 1}
    assert v["right"] == {"state": "clear", "lon_m": None, "gap_m": None, "cars": 0}
    assert v["rate_hz"] == pytest.approx(60.0, abs=0.5)
    off = SpotterEngine(SpotterSettings(enabled=True, visual=False))
    assert off.view()["enabled"] is False


def test_send_rate_low_below_30_hz() -> None:
    e = engine()
    run(e, lambda t: {}, 10.0, 12.0, hz=20.0)
    assert e.motion_hz == pytest.approx(20.0, abs=0.5) and e.send_rate_low
    e = engine()
    run(e, lambda t: {}, 10.0, 11.0, hz=60.0)
    assert not e.send_rate_low


def test_calls_carry_the_decision_stamps() -> None:
    e = engine()
    run(e, lambda t: {}, 9.0, 10.0)
    calls = []
    for i in range(10):
        t = 10.0 + i / 60
        calls += e.feed_motion(motion(t, ALONGSIDE_L, t_recv_ns=5_000 + i), 77)
    c = calls[0]
    assert c.kind == "car_left" and c.side == "left" and c.t_decided_ns == 77
    assert c.t_recv_ns == 5_003 and c.onset_game_ms == pytest.approx(50.0, abs=0.01)
    assert e.state().last_seq == (c.seq, 0) and e.state().occupied == (True, False)
