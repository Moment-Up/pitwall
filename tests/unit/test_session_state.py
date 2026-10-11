"""D4: ``snapshot.session_state`` kept server-side from game events (docs/ui/design-spec.md section 13)."""

from __future__ import annotations

import pytest

from pitwall.core.live import (
    RED_FLAG_PIT_EXIT,
    RED_FLAG_TIMEOUT,
    RED_FLAG_TIMEOUT_S,
    SESSION_ENDED,
    SESSION_RED_FLAG,
    SESSION_RUNNING,
    LiveState,
    SessionState,
    next_session_state,
    red_flag_resume,
)
from pitwall.model.telemetry import CarFrame, EventKind, Game, GameEvent, Platform, SessionInfo, SessionType


def ev(kind: EventKind, t_ns: int = 1) -> GameEvent:
    return GameEvent(kind=kind, game=Game.F1_25, t_recv_ns=t_ns)


def states(*kinds: str) -> list[str | None]:
    st: SessionState | None = SessionState(SESSION_RUNNING, None, 0.0)
    out: list[str | None] = []
    for i, k in enumerate(kinds):
        st = next_session_state(st, k, float(i + 1))
        out.append(None if st is None else st.state)
    return out


def test_transitions_follow_the_session_events() -> None:
    assert states("lights_out", "red_flag", "penalty", "lights_out", "session_ended") == [
        SESSION_RUNNING,
        SESSION_RED_FLAG,
        SESSION_RED_FLAG,  # unrelated events leave the state alone
        SESSION_RUNNING,  # the restart clears the red flag
        SESSION_ENDED,
    ]
    assert states("red_flag", "session_started") == [SESSION_RED_FLAG, SESSION_RUNNING]
    assert states("red_flag", "session_ended") == [SESSION_RED_FLAG, SESSION_ENDED]
    assert next_session_state(None, "penalty", 1.0) is None  # no session, nothing known
    started = next_session_state(None, "session_started", 5.0)
    assert started == SessionState(SESSION_RUNNING, "session_started", 5.0)


def test_chequered_flag_is_reported_but_never_ends_the_session() -> None:
    """F1 sends CHQF when the leader takes the flag (3.5 s before the player crossed the line in a real F1 25
    capture), so only ``session_ended`` ends the session."""
    st = next_session_state(SessionState(SESSION_RUNNING, "lights_out", 1.0), "chequered_flag", 2.0)
    assert st == SessionState(SESSION_RUNNING, "lights_out", 1.0, chequered_flag=True)
    ended = next_session_state(st, "session_ended", 3.0)
    assert ended == SessionState(SESSION_ENDED, "session_ended", 3.0, chequered_flag=True)
    restarted = next_session_state(ended, "session_started", 4.0)
    assert restarted is not None and not restarted.chequered_flag and restarted.state == SESSION_RUNNING


def test_live_state_keeps_the_state_beyond_the_event_window() -> None:
    live = LiveState()
    assert live.snapshot()["session_state"] is None and live.snapshot()["session_state_info"] is None
    live.reset_session("s1", "test", False)
    snap = live.snapshot()
    assert snap["session_state"] == SESSION_RUNNING
    assert snap["session_state_info"]["cause"] is None and not snap["session_state_info"]["chequered_flag"]
    live.on_event(ev(EventKind.RED_FLAG))
    for _ in range(15):  # more than the 10 events the snapshot carries
        live.on_event(ev(EventKind.PENALTY))
    snap = live.snapshot()
    assert "red_flag" not in {e["kind"] for e in snap["events"]}
    assert snap["session_state"] == SESSION_RED_FLAG and snap["session_state_info"]["cause"] == "red_flag"
    live.on_event(ev(EventKind.BUTTON))  # wheel buttons are not events at all
    live.on_event(ev(EventKind.LIGHTS_OUT))
    assert live.snapshot()["session_state"] == SESSION_RUNNING
    live.on_event(ev(EventKind.CHEQUERED_FLAG))
    assert live.snapshot()["session_state"] == SESSION_RUNNING
    live.on_event(ev(EventKind.SESSION_ENDED))
    info = live.snapshot()["session_state_info"]
    assert info["state"] == SESSION_ENDED and info["cause"] == "session_ended" and info["chequered_flag"]
    assert info["since_unix"] == pytest.approx(live.events[0]["t"], abs=1e-3)


def test_a_new_session_starts_running_and_no_session_is_unknown() -> None:
    live = LiveState()
    live.reset_session("s1", "test", False)
    live.on_event(ev(EventKind.SESSION_ENDED))
    assert live.snapshot()["session_state"] == SESSION_ENDED
    live.reset_session("s2", "test", False)
    assert live.snapshot()["session_state"] == SESSION_RUNNING
    live.reset_session(None, None, False)
    assert live.snapshot()["session_state"] is None


# ---------------------------------------------------------------------------------------------- red flag, no event
# F1 practice and qualifying resume after a red flag without a lights-out, and no "red flag cleared" event is
# decoded. Until a real red-flag capture confirms the game's behaviour (spec section 16, question 6), the flag
# also ends when the player's car leaves the pits under green, or after a backstop timeout.


def test_red_flag_resume_rule() -> None:
    # in the pits after the flag: still red, remembered
    assert red_flag_resume(False, 1, "none", 10.0) == (True, None)
    assert red_flag_resume(True, 2, "none", 900.0) == (True, None)  # parked in the pits: never times out
    # back on track after the pits under green: the session resumed
    assert red_flag_resume(True, 0, "none", 60.0) == (True, RED_FLAG_PIT_EXIT)
    assert red_flag_resume(True, 0, None, 60.0) == (True, RED_FLAG_PIT_EXIT)  # unknown = no safety car (cues)
    # a restart behind the safety car waits for it to come in (or for the lights-out)
    for sc in ("full", "virtual", "formation_lap"):
        assert red_flag_resume(True, 0, sc, 60.0) == (True, None)
    assert red_flag_resume(True, None, "none", 60.0) == (True, None)  # pit status lost: not a pit exit
    # never in the pits since the flag: the backstop only
    assert red_flag_resume(False, 0, "none", RED_FLAG_TIMEOUT_S - 1) == (False, None)
    assert red_flag_resume(False, 0, "none", RED_FLAG_TIMEOUT_S) == (False, RED_FLAG_TIMEOUT)
    assert red_flag_resume(False, None, None, RED_FLAG_TIMEOUT_S) == (False, RED_FLAG_TIMEOUT)  # no pit status


def frame(pit_status: int | None) -> CarFrame:
    return CarFrame(game=Game.F1_25, t_recv_ns=1, pit_status=pit_status, speed_kph=80.0)


def info(safety_car: str | None = "none") -> SessionInfo:
    return SessionInfo(
        game=Game.F1_25,
        platform=Platform.PS5,
        session_type=SessionType.PRACTICE,
        track_id="f1:17",
        safety_car_status=safety_car,
    )


def test_a_practice_red_flag_ends_when_the_car_leaves_the_pits_under_green() -> None:
    live = LiveState()
    live.reset_session("s1", "test", False)
    live.on_session(info())
    live.on_frame(frame(0))
    live.on_event(ev(EventKind.RED_FLAG))
    live.on_frame(frame(0))  # driving back to the pits under the flag
    assert live.snapshot()["session_state"] == SESSION_RED_FLAG
    for pit in (1, 2, 2, 1):  # pit lane, garage, out through the pit lane
        live.on_frame(frame(pit))
        assert live.snapshot()["session_state"] == SESSION_RED_FLAG
    live.on_frame(frame(0))  # back on track, no safety car: the session resumed
    info_ = live.snapshot()["session_state_info"]
    assert info_["state"] == SESSION_RUNNING and info_["cause"] == RED_FLAG_PIT_EXIT
    # a second flag must see the car in the pits again: being on track is not enough
    live.on_event(ev(EventKind.RED_FLAG))
    live.on_frame(frame(0))
    assert live.snapshot()["session_state"] == SESSION_RED_FLAG


def test_a_restart_behind_the_safety_car_waits_for_it() -> None:
    live = LiveState()
    live.reset_session("s1", "test", False)
    live.on_session(info())
    live.on_event(ev(EventKind.RED_FLAG))
    live.on_frame(frame(1))
    live.on_session(info("full"))
    live.on_frame(frame(0))  # out of the pit lane behind the safety car
    assert live.snapshot()["session_state"] == SESSION_RED_FLAG
    live.on_session(info("none"))
    live.on_frame(frame(0))
    assert live.snapshot()["session_state_info"]["cause"] == RED_FLAG_PIT_EXIT


def test_the_backstop_ends_a_red_flag_the_car_never_pitted_for() -> None:
    live = LiveState()
    live.reset_session("s1", "test", False)
    live.on_session(info())
    live.on_event(ev(EventKind.RED_FLAG))
    live.on_frame(frame(0))
    assert live.snapshot()["session_state"] == SESSION_RED_FLAG
    st = live.session_state
    assert st is not None
    live.session_state = SessionState(st.state, st.cause, st.since_unix - RED_FLAG_TIMEOUT_S)  # the flag is old
    live.on_frame(frame(0))
    assert live.snapshot()["session_state_info"]["cause"] == RED_FLAG_TIMEOUT
    # a new session forgets that the car was in the pits
    live.on_event(ev(EventKind.RED_FLAG))
    live.on_frame(frame(2))
    live.reset_session("s2", "test", False)
    live.on_event(ev(EventKind.RED_FLAG))
    live.on_frame(frame(0))
    assert live.snapshot()["session_state"] == SESSION_RED_FLAG
