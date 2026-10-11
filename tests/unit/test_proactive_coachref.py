"""coachref on the radio (``voice.proactive``): the reference's name in the lap summary and coaching points, and a
practice drill's one message a lap (no summary, the drill point verbatim)."""

from __future__ import annotations

from typing import Any

from pitwall.coach import drills as dr
from pitwall.voice.proactive import coaching_text, lap_messages, lap_summary_text
from pitwall.voice.types import MessageKind, Priority

LAP = {"lap_id": 41, "lap_number": 4, "lap_time_ms": 91_204, "clean": True, "valid": True, "flags": []}
SAM_REF = {"lap_id": 12, "lap_time_ms": 90_412, "label_to": "Sam's best", "own": False}


def obs(kind: str, value: float, ref_name: str | None = "Sam", **kw: Any) -> dict[str, Any]:
    return {
        "id": f"L4:T3:{kind}",
        "kind": kind,
        "corner": "T3",
        "corner_voice": "Turn 3",
        "value": value,
        "impact_s": 0.12,
        "confidence": 0.9,
        "priority": 0.1,
        "positive": False,
        "evidence": {"exit_speed_delta_kph": -4.0},
        "text": "fallback text",
        "ref_name": ref_name,
        **kw,
    }


def test_lap_summary_names_the_reference() -> None:
    assert lap_summary_text(LAP, None, SAM_REF) == "Lap 4, 1:31.204, plus 0.792 to Sam's best."
    assert lap_summary_text(LAP, None, {**SAM_REF, "lap_time_ms": 91_204}) == "Lap 4, 1:31.204, level with Sam's best."
    legacy = {"lap_id": 12, "lap_time_ms": 90_412}  # a reference without a descriptor (no coachref)
    assert lap_summary_text(LAP, None, legacy) == "Lap 4, 1:31.204, plus 0.792 to your reference."
    own = {**legacy, "label_to": "your best", "own": True}
    assert lap_summary_text(LAP, None, own) == "Lap 4, 1:31.204, plus 0.792 to your best."


def test_coaching_points_name_the_other_driver() -> None:
    assert coaching_text(obs("brake_early", -12.0)) == "Turn 3, losing 0.12 s: braking 12 m earlier than Sam."
    assert coaching_text(obs("low_min_speed", -6.0)) == (
        "Turn 3, losing 0.12 s: Sam was 6 km/h faster in the middle of the corner."
    )
    assert coaching_text(obs("late_throttle", 21.0)) == "Turn 3, losing 0.12 s: full throttle 21 m later than Sam."
    assert coaching_text(obs("coasting", 18.0)) == "Turn 3, losing 0.12 s: 18 m more coasting than Sam."
    assert coaching_text(obs("brake_early", -12.0, None)) == (
        "Turn 3, losing 0.12 s: braking 12 m earlier than your reference."
    )
    assert coaching_text(obs("low_min_speed", -6.0, None)) == "Turn 3, losing 0.12 s: minimum speed 6 km/h down."


def drill_block() -> tuple[dict[str, Any], dict[str, Any]]:
    spec = dr.DrillSpec(
        id=3,
        driver_id=1,
        session_id="s",
        game="f1_25",
        track_id="f1:17",
        track_length_m=4318.0,
        car_id=None,
        track_model_version=1,
        corner="T3",
        corner_label="T3",
        corner_voice="Turn 3",
        apex_m=1180.0,
        kind="brake_point",
        source="radio",
        observation_kind=None,
        laps_target=5,
        target=1100.0,
        tolerance=5.0,
        unit="m",
        baseline=None,
        started_unix=0.0,
    )
    st = dr.DrillState(spec)
    a = dr.evaluate_attempt(st, _m(1099.0), None, lap_id=41, lap_number=4)
    st = st.with_attempt(a, 1.0)
    point = dr.drill_point(st, a)
    block = {"lap_id": 41, "lap_number": 4, "radio_quiet": False, "picked": [], "by_corner": {}}
    return dr.with_drill(block, point, "T3"), point


def _m(v: float) -> Any:
    from pitwall.analysis.compare import CornerMetrics

    return CornerMetrics(corner="T3", segment_time_s=6.0, brake_start_m=v)


def test_drill_lap_is_one_message_the_drill_point_verbatim() -> None:
    coach, point = drill_block()
    msgs = lap_messages(LAP, [obs("brake_early", -12.0)], None, SAM_REF, "normal", 0.0, coach=coach)
    assert len(msgs) == 1
    (m,) = msgs
    assert m.text == point["text"] == "Turn 3 drill, 1 of 5: on the point, 1 m early. 1 hit."
    assert m.kind is MessageKind.COACHING and m.priority is Priority.NORMAL and m.needs_speak_window
    assert m.meta["observation_kind"] == "drill"
    assert m.meta["drill_id"] == 3  # the validation kit and acceptance R9 tell a drill point by it
    detailed = lap_messages(LAP, [], None, SAM_REF, "detailed", 0.0, coach=coach)
    assert [x.text for x in detailed] == [point["text"]]


def test_drill_laps_without_an_attempt_and_quiet_radio_say_nothing() -> None:
    coach, _ = drill_block()
    none = dr.with_drill(
        {"lap_id": 41, "lap_number": 4, "radio_quiet": False, "picked": [], "by_corner": {}}, None, "T3"
    )
    assert lap_messages(LAP, [obs("brake_early", -12.0)], None, SAM_REF, "normal", 0.0, coach=none) == []
    assert lap_messages(LAP, [], None, SAM_REF, "quiet", 0.0, coach=coach) == []
    quiet_block = dr.with_drill({**coach, "radio_quiet": True}, coach["picked"][0], "T3")
    assert lap_messages(LAP, [], None, SAM_REF, "normal", 0.0, coach=quiet_block) == []
