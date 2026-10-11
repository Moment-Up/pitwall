"""coachref through the whole live pipeline on SYNTHETIC laps (``LapProcessor`` + ``LiveState`` + ``CueEngine`` +
``CoachRef`` + ``voice.proactive.lap_messages``).

Sam drives the synthetic clean session, Ann the coaching demo with its injected mistakes (lap 3 brakes 15 m early
into design-T3, learned "T2"). Both are stored as ordinary non-synthetic sessions *on purpose*: the test exercises
cross-driver resolution, the wording, the braking clamp and drills against known ground truth. It is never a
compatibility claim: synthetic != recorded != live.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.core.coachref import LEGACY_REASON, ChoiceRequest, DrillRequest
from pitwall.sim.scenarios import coaching_demo
from pitwall.voice.proactive import lap_messages
from pitwall.voice.types import MessageKind
from tests.coachref_support import Env, drive, make_env, new_session
from tests.conftest import DecodedSession

pytestmark = pytest.mark.synthetic


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = make_env(tmp_path)
    yield e
    e.close()


def test_ann_against_sams_lap_and_a_drill(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    sam = env.drivers.create("Sam").id
    ann = env.drivers.default_id
    ss = new_session(env.writer, sam, clean_session.info, "s-sam")
    drive(env.proc, ss, clean_session.info, [(clean_session.laps[i], 60_000 + i, i + 1) for i in range(3)])
    sa = new_session(env.writer, ann, demo_session.info, "s-ann")
    env.live.reset_session(sa, "udp:20777", False)
    env.live.on_session(demo_session.info)
    env.live.cues.set_mode("all")
    env.svc.set_choice(ChoiceRequest(kind="driver_best", target_driver_id=sam))
    notes: list[dict[str, Any]] = []
    env.live.subscribe(lambda kind, payload: notes.append(payload) if kind == "lap" else None)
    laps, info = demo_session.laps, demo_session.info
    res = drive(env.proc, sa, info, [(laps[0], 69_000, 1), (laps[1], 69_500, 2), (laps[2], 70_500, 3)])
    # Ann's observations name Sam; the injected early braking is seen against Sam's lap
    early = [o for o in res[2]["observations"] if o["kind"] == "brake_early"]
    injected = coaching_demo().driver_by_lap[3].deviations["T3"].brake_early_m
    assert early and early[0]["corner"] == "T2" and "than Sam" in early[0]["text"]
    assert abs(abs(early[0]["value"]) - injected) <= 3.0
    # every braking call is at or before Ann's own point
    clamp = res[2]["comparison"]["brake_clamp_m"]
    assert env.live.cues.plan.cues
    assert all(c.target_m <= clamp[c.corner] for c in env.live.cues.plan.cues)
    # a brake-point drill on the injected corner: lap 3 again (15 m early: miss), then two clean laps (hits)
    view = env.svc.start_drill(DrillRequest(corner="T2", kind="brake_point", laps=3))
    assert view["target"] <= clamp["T2"]
    notes.clear()
    drive(env.proc, sa, info, [(laps[2], 70_500, 4), (laps[0], 69_000, 5), (laps[1], 69_300, 6)])
    drill = env.live.coachref["drill"] if env.live.coachref else None
    assert drill is not None and drill["status"] == "completed"
    outcomes = [a["outcome"] for a in drill["attempts"]]
    assert outcomes == ["miss", "hit", "hit"]
    assert abs(drill["attempts"][0]["delta"] + injected) <= 3.0  # the ground truth: 15 m before the point
    # the radio says exactly one drill point a lap and no lap summary
    for payload in notes:
        msgs = lap_messages(
            payload["lap"], payload["observations"], None, env.live.reference, "normal", 0.0, coach=payload["coach"]
        )
        assert len(msgs) == 1 and msgs[0].kind is MessageKind.COACHING
        assert msgs[0].meta["observation_kind"] == "drill" and "drill" in msgs[0].text
    assert notes[-1]["coach"]["picked"][0]["text"].startswith("T2 drill done: 2 of 3 on the point.")


def test_a_synthetic_live_session_ignores_the_choice(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    sam = env.drivers.create("Sam").id
    ann = env.drivers.default_id
    ss = new_session(env.writer, sam, clean_session.info, "s-sam")
    drive(env.proc, ss, clean_session.info, [(clean_session.laps[i], 60_000 + i, i + 1) for i in range(3)])
    env.svc.set_choice(ChoiceRequest(kind="driver_best", target_driver_id=sam))
    syn = new_session(env.writer, ann, demo_session.info, "s-syn", synthetic=True)
    env.live.reset_session(syn, "udp:20777", True)
    env.live.on_session(demo_session.info)
    res = drive(
        env.proc, syn, demo_session.info, [(demo_session.laps[0], 69_000, 1), (demo_session.laps[2], 70_500, 2)]
    )
    ref = env.live.reference
    assert ref is not None and ref["own"] is True and ref["session_id"] == syn  # never Sam's lap
    assert env.live.coachref is not None and env.live.coachref["reason"] == LEGACY_REASON
    assert all("Sam" not in o["text"] for o in res[1]["observations"])
    assert "brake_clamp_m" not in res[1]["comparison"]
