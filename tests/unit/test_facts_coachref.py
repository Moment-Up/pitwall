"""coachref in the engineer's facts: the live reference fact appears only for another driver's lap, and the
deterministic answer built from it passes the grounding check."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.ai.engineer import Intent, deterministic_answer
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
        "label_to": "Ben's best",
        "ref_name": "Ben" if not own else None,
        "brake_clamped": not own,
        "frozen": False,
    }


def test_live_reference_fact_only_for_another_drivers_lap(env: Env, clean_session: DecodedSession) -> None:
    sid = new_session(env.writer, env.drivers.default_id, clean_session.info, "s-ann")
    drive(env.proc, sid, clean_session.info, [(lap, 70_000 + i, i + 1) for i, lap in enumerate(clean_session.laps)])
    sa = SessionAnalyzer(env.db).analyse(sid)
    assert sa is not None
    own = build_fact_sheet(sa, {"reference": live_ref(True)})
    assert not any(f.text.startswith("Live delta and coaching reference") for f in own.facts)
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
