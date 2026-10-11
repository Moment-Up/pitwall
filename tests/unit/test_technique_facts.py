"""Technique facts for the AI engineer: grounded plain sentences, the new intents, deterministic answers.

Uses the SYNTHETIC technique-demo session (known injected deviations), replayed into a scratch database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pitwall.ai.engineer import Intent, RaceEngineer, detect_intent, deterministic_answer
from pitwall.ai.facts import FactSheet, build_fact_sheet
from pitwall.ai.grounding import check_grounding
from pitwall.core.session_analysis import SessionAnalysis, SessionAnalyzer
from pitwall.sim.scenarios import technique_demo
from pitwall.storage.db import Database
from pitwall.voice.hub import FAST_INTENTS
from tests.technique_fixtures import design_to_learned, f1_writer, replay_into

pytestmark = pytest.mark.synthetic


@pytest.fixture(scope="module")
def sa(tmp_path_factory: pytest.TempPathFactory) -> SessionAnalysis:
    root: Path = tmp_path_factory.mktemp("technique_facts")
    sid = replay_into(root, [("technique-demo", f1_writer(technique_demo(), "technique-demo"))])["technique-demo"]
    out = SessionAnalyzer(Database(root / "pitwall.sqlite3")).analyse(sid)
    assert out is not None and out.model is not None
    return out


@pytest.fixture(scope="module")
def sheet(sa: SessionAnalysis) -> FactSheet:
    return build_fact_sheet(sa)


@pytest.fixture(scope="module")
def names(sa: SessionAnalysis) -> dict[str, str]:
    from pitwall.sim.track import pitwall_park

    design = {n: (a, b) for n, a, b in pitwall_park().corners}
    assert sa.model is not None
    return design_to_learned(sa.model.corners, design)


def test_every_plain_sentence_is_grounded(sheet: FactSheet) -> None:
    tech = [f for f in sheet.facts if f.topic in ("line", "technique", "balance")]
    assert {f.topic for f in tech} == {"line", "technique", "balance"}
    for f in tech:
        g = check_grounding(f"{f.plain} [{f.id}]", sheet.facts)
        assert g.ok, (f.plain, g.ungrounded_numbers)
        assert "brake later" not in f.plain.lower() and "brake earlier" not in f.plain.lower()


def test_facts_carry_the_injected_deviations(sheet: FactSheet, names: dict[str, str]) -> None:
    line = [f for f in sheet.facts if f.topic == "line" and f.corner == names["T3"]]
    assert line and "2.0 m wider than your reference lap" in line[0].text and line[0].data["lap"] == 3
    assert any(f.text.startswith("Biggest line differences vs reference") for f in sheet.facts)
    lock = next(f for f in sheet.facts if f.topic == "technique" and f.text.startswith("Lock-ups"))
    assert "on lap 4" in lock.text and "ABS off" in lock.text
    spin = next(f for f in sheet.facts if f.topic == "technique" and f.text.startswith("Wheelspin"))
    assert "on lap 5" in spin.text
    summary = next(f for f in sheet.facts if f.topic == "balance" and f.text.startswith("Handling summary"))
    assert "heuristic thresholds" in summary.text and "mid-corner understeer" in summary.text
    setup = next(f for f in sheet.facts if f.topic == "balance" and f.text.startswith("Setup to try"))
    assert "Front Anti-Roll Bar 10 -> 8" in setup.text and "One change, then compare a session" in setup.text
    assert setup.corner == names["T8"]


def test_generic_car_setup_fact_only_when_both_car_formats_agree(sa: SessionAnalysis) -> None:
    """The generic car (team 41) hides the car format and the fact builder cannot see the driver's choice on the Setup
    page: a change is stated only when it is the same on the 2025 and the 2026 car, and says so."""
    from dataclasses import replace

    from pitwall.technique.session import clear_cache

    generic = replace(sa, session={**sa.session, "car_id": 41})
    clear_cache()
    try:
        sheet = build_fact_sheet(generic)
    finally:
        clear_cache()
    setup = [f for f in sheet.facts if f.topic == "balance" and f.text.startswith("Setup to try")]
    assert setup, [f.text for f in sheet.facts if f.topic == "balance"]
    assert "Front Anti-Roll Bar 10 -> 8 (the same change on the 2025 and the 2026 car)" in setup[0].text
    for f in setup:
        assert check_grounding(f"{f.plain} [{f.id}]", sheet.facts).ok


def test_line_summary_names_the_lap_when_the_median_is_close(sheet: FactSheet) -> None:
    """Only lap 3 ran wide at design-T3: the summary names that lap instead of a near-zero session median."""
    summary = next(f for f in sheet.facts if f.text.startswith("Biggest line differences vs reference"))
    assert "2.0 m wider on lap 3" in summary.text and " 0.0 m" not in summary.text, summary.text
    assert "of 1 laps" not in summary.text


@pytest.mark.parametrize(
    ("q", "intent", "corner"),
    [
        ("how's my line through turn 3", "line", "T3"),
        ("am I locking up", "technique", None),
        ("trail braking at T5", "technique", "T5"),
        ("I've got understeer in turn 3", "balance", "T3"),
        ("brake balance", "setup", None),
        ("the rear end steps out on exit", "balance", None),
        ("am I smooth on the throttle", "technique", None),
        ("am I running wide at the apex", "line", None),
        ("what is my apex speed at turn 3", "corner", "T3"),  # apex speed is not the line
        # unchanged
        ("Where should I be braking for Turn 1?", "braking", "T1"),
        ("Should I change my front wing?", "setup", None),
        ("Engineer, why am I losing time through Turn 7?", "losing_time", "T7"),
        ("Compare that lap to my best.", "compare", None),
    ],
)
def test_intents(q: str, intent: str, corner: str | None) -> None:
    i = detect_intent(q)
    assert (i.name, i.corner) == (intent, corner)


async def test_deterministic_answers_are_grounded_and_corner_aware(sheet: FactSheet, names: dict[str, str]) -> None:
    eng = RaceEngineer(None)
    t3 = names["T3"]  # learned name of design-T3 (lap 3 ran 2 m wide there)
    cases = {
        f"how's my line through {t3}": "2.0 m wider",
        "am I locking up": "Lock-ups under braking",
        f"I've got understeer at {names['T8']}": "pushed wide",
        "how is the balance": "Something to try",
        "how much wheelspin": "Wheelspin",
    }
    for q, needle in cases.items():
        ans = await eng.answer(q, sheet, use_llm=False)
        assert ans.grounded and ans.fallback, q
        assert "don't have enough data" not in ans.text and needle in ans.text, (q, ans.text)
        assert "[F" not in ans.text


def test_setup_answers_add_the_handling_facts_only_when_present(sheet: FactSheet) -> None:
    facts = sheet.select({"session", "corners", "observations", "compare", "setup", "balance"})
    with_balance = deterministic_answer(Intent("setup"), facts, sheet)
    assert "Handling summary" in with_balance and "Something to try" in with_balance
    without = deterministic_answer(Intent("setup"), [f for f in facts if f.topic != "balance"], sheet)
    assert "Something to try" not in without and "Handling summary" not in without
    assert without.startswith("Before changing the setup")


def test_radio_answers_the_new_intents_without_the_llm() -> None:
    assert {"line", "technique", "balance"} <= FAST_INTENTS


def test_technique_answer_without_a_corner_uses_the_session_facts() -> None:
    """A corner's technique fact that mentions wheelspin is not the session's wheelspin fact (Miami race)."""
    sheet = FactSheet()
    sheet.add(
        "technique",
        "Brake and throttle technique at T9 on lap 2 vs reference lap 3: Wheelspin on the exit 0.40s vs 0.10s.",
        {"lap": 2},
        corner="T9",
        say="T9. On lap 2: the rear wheels spun more on the exit than on your reference.",
    )
    sheet.add("technique", "Lock-ups: ABS is on, so the game prevents them and lock-ups are not analysed.", {})
    sheet.add("technique", "Wheelspin on corner exits this session (traction control full): T8 1.82s on laps 1, 2.", {})
    text = deterministic_answer(Intent("technique"), sheet.facts, sheet)
    assert "Lock-ups: ABS is on" in text and "T8 1.82s" in text and "T9" not in text, text
