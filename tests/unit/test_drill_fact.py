"""The ``drill`` fact (plan 4.4, coachref): the practice drill running in the live session, or the result of one
driven in it, from the snapshot's ``coachref.drill``; never for another session."""

from __future__ import annotations

from typing import Any

from pitwall.ai.engineer import _TOPICS
from pitwall.ai.facts import DRILL_PREFIX, FactSheet, build_fact_sheet
from pitwall.ai.grounding import check_grounding
from tests.unit.test_ai import _game_analysis


def _drill(status: str = "active", attempts: int = 2, hits: int = 1, session_id: str | None = None) -> dict[str, Any]:
    return {
        "id": 12,
        "session_id": session_id,
        "corner": "T3",
        "corner_label": "T3",
        "corner_voice": "Turn 3",
        "kind": "brake_point",
        "skill_label": "Brake point",
        "laps_target": 5,
        "target_text": "Brake within 5 m of your braking point.",
        "status": status,
        "attempts": [{"attempt": i + 1} for i in range(attempts)],
        "hits": hits,
        "summary_text": "Turn 3 brake point drill: 3 of 5 on the point" if status != "active" else None,
    }


def _sheet(drill: dict[str, Any] | None, *, live_session: str | None = "same") -> tuple[FactSheet, str]:
    sa = _game_analysis("f1_25", "ps5")
    sid = str(sa.session["id"])
    live = {
        "session_id": sid if live_session == "same" else live_session,
        "connection": {"status": "live"},
        "session": {"safety_car_status": "none"},
        "marshal_flags": [],
        "frame": {},
        "coachref": {"driver_id": 1, "drill": drill},
    }
    return build_fact_sheet(sa, live), sid


def _drill_facts(sheet: FactSheet) -> list[str]:
    return [f.text for f in sheet.facts if f.topic == "drill"]


def test_a_running_drill_is_a_fact_with_its_progress_and_target() -> None:
    sheet, _ = _sheet(_drill())
    assert _drill_facts(sheet) == [
        f"{DRILL_PREFIX} T3 brake point, 2 of 5 laps done, 1 hit. Target: Brake within 5 m of your braking point."
    ]
    fact = next(f for f in sheet.facts if f.topic == "drill")
    assert fact.say == "T3 brake point drill: 2 of 5 done, 1 hit."
    assert fact.corner == "T3"
    assert check_grounding(f"{fact.text} [{fact.id}]", sheet.facts).ok
    # early in the sheet, so a long sheet's selection never drops it
    assert sheet.facts.index(fact) < 5


def test_an_ended_drill_of_this_session_gives_its_result() -> None:
    sa_sheet, sid = _sheet(None)
    sheet, _ = _sheet(_drill("completed", attempts=5, hits=3, session_id=sid), live_session="another")
    assert _drill_facts(sheet) == ["Drill result: Turn 3 brake point drill: 3 of 5 on the point."]
    assert not _drill_facts(sa_sheet)


def test_no_drill_fact_for_another_session_or_without_coachref() -> None:
    sheet, _ = _sheet(_drill(session_id="older"), live_session="another")
    assert not _drill_facts(sheet)
    sheet, _ = _sheet(_drill("stopped", attempts=0))
    assert not _drill_facts(sheet)  # stopped before the first attempt: nothing to say
    sa = _game_analysis("f1_25", "ps5")
    assert not _drill_facts(build_fact_sheet(sa, None))


def test_focus_and_summary_questions_see_the_drill() -> None:
    assert "drill" in _TOPICS["focus"]
    assert "drill" in _TOPICS["summary"]
