"""``ipad_one_message`` with coachref drills (plan 3.7, F9): on a drill lap (its coach block says ``drill_only``) the
one coaching message spoken is the drill point; another point on that lap, or a second message, fails."""

from __future__ import annotations

from pitwall.validate.evidence import AutoContext, View, _one_message
from pitwall.validate.model import LapRecord, ProactiveRecord

NOW = 1_791_700_000.0


def _lap(lap_id: int, picked: list[str], drill_only: bool) -> LapRecord:
    return LapRecord(
        t_unix=NOW,
        tier="live",
        session_id="s",
        driver_id=1,
        lap_id=lap_id,
        lap_number=lap_id,
        lap_time_ms=80_000,
        clean=True,
        flags=[],
        game="f1_25",
        track_id="f1:17",
        track_name="Austria",
        cue_mode="focus",
        n_observations=3,
        picked_ids=picked,
        drill_only=drill_only,
    )


def _said(lap_id: int, obs_id: str, drill_id: int | None) -> ProactiveRecord:
    return ProactiveRecord(
        t_unix=NOW,
        tier="live",
        session_id="s",
        driver_id=1,
        id=f"m{lap_id}{obs_id}",
        kind="coaching",
        text="x",
        lap=lap_id,
        lap_id=lap_id,
        observation_id=obs_id,
        held_s=0.0,
        state_at_send={},
        started=True,
        drill_id=drill_id,
    )


def _ctx() -> AutoContext:
    return AutoContext(now=NOW, windows=[], attest={})


def test_drill_laps_pass_when_the_drill_point_is_the_one_message() -> None:
    v = View(
        laps=[_lap(1, ["drill3:a1"], True), _lap(2, ["drill3:a2"], True), _lap(3, ["T5:brake_early"], False)],
        proactive=[_said(1, "drill3:a1", 3), _said(2, "drill3:a2", 3), _said(3, "T5:brake_early", None)],
    )
    st = _one_message(v, _ctx())
    assert st.verdict == "pass"
    assert st.metrics["drill_breaches"] == 0


def test_another_point_on_a_drill_lap_fails() -> None:
    v = View(
        laps=[_lap(1, ["drill3:a1"], True), _lap(2, ["drill3:a2"], True), _lap(3, ["T5:brake_early"], False)],
        proactive=[
            _said(1, "drill3:a1", 3),
            _said(1, "T9:late_throttle", None),  # a second, non-drill point on the drill lap
            _said(2, "drill3:a2", 3),
            _said(3, "T5:brake_early", None),
        ],
    )
    st = _one_message(v, _ctx())
    assert st.verdict == "fail"
    assert st.metrics["drill_breaches"] == 1
