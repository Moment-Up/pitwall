"""Track knowledge wired into the runtime: field samples -> field worker -> resolver -> live state and cue engine.

Synthetic tier (generated AI field): evidence for the wiring and its thread rules, never for game compatibility.
"""

from __future__ import annotations

from pathlib import Path

import orjson
import pytest

from pitwall.coach.cues import CueEngine, CueKind, CuePlan, CueSpec, FocusLimits
from pitwall.config import Settings
from pitwall.core.live import LiveState
from pitwall.core.runtime import Runtime
from pitwall.core.track_knowledge import TrackKnowledgeResolver
from pitwall.ingest.capture import CaptureMeta, write_capture
from pitwall.model.telemetry import Game, SessionInfo
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.sim.f1_stream import AiCarSpec, F1Scenario, generate_f1_session

pytestmark = pytest.mark.synthetic


def _heads_up_plan() -> CuePlan:
    """Three heads-ups at 100 / 500 / 900 m; priority (largest speed drop first): B, C, A."""
    specs = tuple(
        CueSpec(
            corner=c,
            kind=CueKind.MARKER,
            target_m=d,
            text="heavy braking ahead",
            parts=("heavy braking ahead",),
            key_index=0,
            anticipation_s=2.5,
        )
        for c, d in (("A", 100.0), ("B", 500.0), ("C", 900.0))
    )
    return CuePlan(
        mode="markers",
        cues=specs,
        approaches=(None, None, None),
        targets=tuple(s.target_m for s in specs),
        length_m=1000.0,
        focus=("B", "C", "A"),
    )


def test_cue_engine_uses_field_heads_ups_only_without_own_cues_and_caps_them_in_focus_mode() -> None:
    eng = CueEngine()  # default mode "focus", no reference yet
    eng.set_fallback_plan(_heads_up_plan())
    plan = eng.plan
    assert [c.corner for c in plan.cues] == ["A", "B", "C"] and plan.focus == ("B", "C", "A")  # 3 focus corners
    assert plan.reason is not None and plan.reason.startswith("AI field heads-ups")
    eng.set_focus_limits(FocusLimits(max_corners=1))  # a beginner: one call per lap, the heaviest stop
    plan = eng.plan
    assert [c.corner for c in plan.cues] == ["B"] and plan.focus == ("B",)
    eng.set_mode("markers")  # every heads-up, in lap order; markers mode has no focus corners
    plan = eng.plan
    assert [c.corner for c in plan.cues] == ["A", "B", "C"] and not plan.focus
    assert list(plan.targets) == sorted(plan.targets)
    eng.set_mode("off")
    assert eng.plan.cues == ()
    eng.set_mode("markers")
    eng.reset_session()  # a new session: the old field's heads-ups go until the resolver republishes
    assert eng.plan.cues == ()


def test_reinstalling_the_live_map_on_the_ingest_thread_does_not_resolve() -> None:
    """``SessionManager._split_for_driver`` resets live state and re-installs the same track model payload on the
    INGEST thread: the resolver must not re-resolve (or wait for a publish in flight) for it."""
    live = LiveState()
    resolver = TrackKnowledgeResolver(live.set_track_knowledge)
    live.knowledge = resolver
    resolver.set_session(SessionInfo(game=Game.F1_25, session_uid="1", track_id="f1:x", track_length_m=1000.0))
    payload = {"track_id": "f1:x", "length_m": 1000.0, "corners": [], "version": 1, "n_laps": 1}
    live.set_track_model(payload)
    assert resolver.knowledge is not None
    v = resolver.knowledge.version
    live.reset_session("s2", "udp:20777", False)
    live.set_track_model(payload)  # what _split_for_driver does
    assert resolver.knowledge.version == v and live.track_model is payload
    live.set_track_model(dict(payload))  # a new payload (analysis thread) resolves again
    assert resolver.knowledge.version == v + 1


def test_replay_learns_the_field_in_its_own_worker(tmp_path: Path) -> None:
    dev = DriverProfile(deviations={"T1": CornerDeviation(brake_early_m=20.0)})
    sc = F1Scenario(
        laps=3,
        rate_hz=30,
        session_type=15,
        ai_cars=tuple(AiCarSpec(index=k, driver=dev, start_s=0.4 + 1.37 * k) for k in range(1, 7)),
    )
    packets, _truth = generate_f1_session(sc)
    cap = tmp_path / "captures" / "field.pwcap"
    write_capture(
        cap, packets, CaptureMeta(source="synthetic", game_hint="f1_25", synthetic=True, extra={"scenario": "field"})
    )
    rt = Runtime(Settings(data_dir=tmp_path, llm_enabled=False))
    try:
        r = rt.start_replay(cap, speed=None)  # max speed: the replay's worker blocks instead of dropping
        assert r.done.wait(60)
        rt.stop_replay()  # joins the replay thread: its worker has drained and published its final view
        k = rt.live.snapshot(include_static=True)["track_knowledge"]
        assert k is not None and k["synthetic"] is True and k["track_id"] == "synthetic:field"
        assert k["layers"]["L0b"]["available"] and k["layers"]["L0b"]["cars"] == 6 and k["heads_up"]
        orjson.dumps(k)  # strict JSON
        assert rt.field.model is None and rt.field.submitted == 0  # the live stream's worker never saw the replay
        assert rt.live.knowledge is rt.knowledge  # learned models feed the live resolver again
    finally:
        rt.close()
