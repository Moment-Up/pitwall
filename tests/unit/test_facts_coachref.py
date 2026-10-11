"""coachref in the engineer's facts: the live reference fact appears only for another driver's lap, and the
deterministic answer built from it passes the grounding check."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.ai.engineer import Intent, detect_intent, deterministic_answer
from pitwall.ai.facts import build_fact_sheet
from pitwall.ai.grounding import check_grounding, display_text
from pitwall.core.session_analysis import SessionAnalyzer
from tests.coachref_support import Env, drive, make_env, new_session
from tests.conftest import DecodedSession


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = make_env(tmp_path)
    yield e
    e.close()


def live_ref(own: bool) -> dict[str, Any]:
    return {
        "lap_id": 1,
        "lap_number": 3,
        "lap_time_ms": 96_953,
        "session_id": "s-ben",
        "kind": "driver_best" if not own else "own_best",
        "own": own,
        "pinned": False,
        "driver_id": 2,
        "driver_name": "Ben",
        "set_unix": 1_760_000_000.0,
        "label": "Ben's best" if not own else "Your best",
        "label_to": "Ben's best" if not own else "your best",
        "ref_name": "Ben" if not own else None,
        "brake_clamped": not own,
        "frozen": False,
    }


def test_live_reference_fact_only_for_another_drivers_lap(env: Env, clean_session: DecodedSession) -> None:
    sid = new_session(env.writer, env.drivers.default_id, clean_session.info, "s-ann")
    drive(env.proc, sid, clean_session.info, [(lap, 70_000 + i, i + 1) for i, lap in enumerate(clean_session.laps)])
    sa = SessionAnalyzer(env.db).analyse(sid)
    assert sa is not None
    legacy = build_fact_sheet(sa, {"reference": {"lap_id": 1, "lap_number": 3, "lap_time_ms": 96_953}})
    assert not any(f.text.startswith("Live delta and coaching reference") for f in legacy.facts)  # no coachref
    own = build_fact_sheet(sa, {"reference": live_ref(True)})
    refs = [f for f in own.facts if f.topic == "reference"]
    assert refs[0].text.startswith("Reference lap for comparisons")  # the session's own fact stays first
    assert refs[-1].plain == "You're being compared with your best, a 1:36.953."
    sheet = build_fact_sheet(sa, {"reference": live_ref(False)})
    fact = next(f for f in sheet.facts if f.text.startswith("Live delta and coaching reference"))
    assert fact.topic == "reference"
    assert "Ben's best (Ben), 1:36.953, lap 3" in fact.text
    assert "never go later than Driver's own braking point" in fact.text
    assert fact.plain == "You're being compared with Ben's best, a 1:36.953."
    facts = sheet.select({"session", "compare", "reference", "laps"})
    det = deterministic_answer(Intent("compare"), facts, sheet)
    g = check_grounding(det, facts)
    assert g.ok, g
    assert "You're being compared with Ben's best, a 1:36.953." in display_text(det, facts)


@pytest.mark.parametrize("own", [False, True])
def test_who_am_i_compared_with_names_the_live_reference(env: Env, clean_session: DecodedSession, own: bool) -> None:
    """UX review: "who am I compared with?" answered "Best clean lap this session ..." instead of the reference."""
    sid = new_session(env.writer, env.drivers.default_id, clean_session.info, "s-ann")
    drive(env.proc, sid, clean_session.info, [(lap, 70_000 + i, i + 1) for i, lap in enumerate(clean_session.laps)])
    sa = SessionAnalyzer(env.db).analyse(sid)
    assert sa is not None
    sheet = build_fact_sheet(sa, {"reference": live_ref(own)})
    intent = detect_intent("who am I compared with?")
    assert intent.name == "reference"
    facts = sheet.select({"session", "reference", "laps"})
    det = deterministic_answer(intent, facts, sheet)
    assert check_grounding(det, facts).ok
    said = "your best" if own else "Ben's best"
    assert display_text(det, facts) == f"You're being compared with {said}, a 1:36.953."
