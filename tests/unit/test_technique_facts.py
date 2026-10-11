"""Technique facts for the AI engineer: grounded plain sentences, the new intents, deterministic answers.

Uses the SYNTHETIC technique-demo session (known injected deviations), replayed into a scratch database.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from pitwall.ai.engineer import Intent, RaceEngineer, detect_intent, deterministic_answer, named_corner
from pitwall.ai.facts import FactSheet, build_fact_sheet
from pitwall.ai.grounding import check_grounding
from pitwall.analysis.laps import LapFlag
from pitwall.core.session_analysis import SessionAnalysis, SessionAnalyzer
from pitwall.sim.scenarios import technique_demo
from pitwall.storage.db import Database
from pitwall.technique.facts import _line_facts, _slip_facts, technique_facts
from pitwall.technique.rig import ABS_OFF_OR_UNKNOWN
from pitwall.technique.session import NO_SLIP_GAME, Availability, analyse_session, clear_cache
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
    clear_cache()
    return build_fact_sheet(sa)


@pytest.fixture(scope="module")
def real(sa: SessionAnalysis) -> SessionAnalysis:
    """The same laps as if they were not synthetic (setup facts are never made for a synthetic session)."""
    return replace(sa, session={**sa.session, "synthetic": False})


@pytest.fixture(scope="module")
def real_sheet(real: SessionAnalysis) -> Iterator[FactSheet]:
    clear_cache()
    yield build_fact_sheet(real)
    clear_cache()


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


def test_facts_carry_the_injected_deviations(sheet: FactSheet, real_sheet: FactSheet, names: dict[str, str]) -> None:
    line = [f for f in sheet.facts if f.topic == "line" and f.corner == names["T3"]]
    assert line and "2.0 m wider than your reference lap" in line[0].text and line[0].data["lap"] == 3
    assert any(f.text.startswith("Biggest line differences vs reference") for f in sheet.facts)
    lock = next(f for f in sheet.facts if f.topic == "technique" and f.text.startswith("Lock-ups"))
    assert "on lap 4" in lock.text and "ABS off" in lock.text
    spin = next(f for f in sheet.facts if f.topic == "technique" and f.text.startswith("Wheelspin"))
    assert "on lap 5" in spin.text
    summary = next(f for f in sheet.facts if f.topic == "balance" and f.text.startswith("Handling summary"))
    assert "heuristic thresholds" in summary.text and "understeer mid-corner" in summary.text
    # a synthetic session says so, in the text and in the spoken sentence, and gets no setup change to try
    assert "SYNTHETIC data, not your car" in summary.text and summary.plain.startswith("Synthetic data, not your car")
    assert not any(f.text.startswith("Setup to try") for f in sheet.facts)
    setup = next(f for f in real_sheet.facts if f.topic == "balance" and f.text.startswith("Setup to try"))
    assert "Front Anti-Roll Bar 10 → 8" in setup.text and "One change, then compare a session" in setup.text
    assert setup.plain == "Something to try after the session: Front Anti-Roll Bar from 10 to 8."
    assert setup.corner == names["T8"]
    real_summary = next(f for f in real_sheet.facts if f.text.startswith("Handling summary"))
    assert "SYNTHETIC" not in real_summary.text and real_summary.plain.startswith("The car pushes wide mid-corner")


def test_spoken_sentences_are_short(sheet: FactSheet, real_sheet: FactSheet) -> None:
    """The radio reads ``say`` out: about 2.6 words a second, so no technique fact may take more than ~12 s."""
    for f in [*sheet.facts, *real_sheet.facts]:
        if f.topic in ("line", "technique", "balance") and f.say is not None:
            assert len(f.say.split()) <= 32, f.say
    for prefix in ("Biggest line differences", "Lock-ups", "Wheelspin", "Handling summary", "Setup to try"):
        f = next(x for x in real_sheet.facts if x.text.startswith(prefix))
        assert f.say is not None and len(f.say) < len(f.text), prefix


def test_generic_car_setup_fact_only_when_both_car_formats_agree(real: SessionAnalysis) -> None:
    """The generic car (team 41) hides the car format and the fact builder cannot see the driver's choice on the Setup
    page: a change is stated only when it is the same on the 2025 and the 2026 car, and says so."""
    generic = replace(real, session={**real.session, "car_id": 41})
    clear_cache()
    try:
        sheet = build_fact_sheet(generic)
    finally:
        clear_cache()
    setup = [f for f in sheet.facts if f.topic == "balance" and f.text.startswith("Setup to try")]
    assert setup, [f.text for f in sheet.facts if f.topic == "balance"]
    assert "Front Anti-Roll Bar 10 → 8 (the same change on the 2025 and the 2026 car)" in setup[0].text
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
        # review: a braking question stays braking, "smooth" alone and "the line" alone are not technique / line
        ("am I braking too late into the apex at turn 1", "braking", "T1"),
        ("was my last lap smooth", "last_lap", None),
        ("how far to the line", "general", None),
        ("the rear is stepping out", "balance", None),
        ("the rear end's kicking out at turn 4", "balance", "T4"),
        ("is my line through turn 2 any good", "line", "T2"),
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


@pytest.mark.parametrize(
    ("q", "topic"),
    [
        ("am I locking up", "lock"),
        ("how much wheelspin on the exit", "spin"),
        ("trail braking at T5", "trail"),
        ("am I smooth on the throttle", "throttle"),
        ("am I coasting too much", "coast"),
        ("the rear end is loose in turn 8", "oversteer"),
        ("the car won't turn in", "understeer"),
        ("how's the balance", None),
    ],
)
def test_technique_and_balance_questions_carry_their_topic(q: str, topic: str | None) -> None:
    assert detect_intent(q).topic == topic


async def test_deterministic_answers_are_grounded_and_corner_aware(
    real_sheet: FactSheet, names: dict[str, str]
) -> None:
    eng = RaceEngineer(None)
    sheet = real_sheet
    t3 = names["T3"]  # learned name of design-T3 (lap 3 ran 2 m wide there)
    cases = {
        f"how's my line through {t3}": "2.0 m wider",
        "am I locking up": "1 lock-up, at",
        f"I've got understeer at {names['T8']}": "pushed wide",
        "how is the balance": "Something to try after the session",
        "how much wheelspin": "Most wheelspin at",
        "am I trail braking": "trail braking was close to your reference",
        f"the rear end is loose at {names['T8']}": "I don't see oversteer at",
    }
    for q, needle in cases.items():
        ans = await eng.answer(q, sheet, use_llm=False)
        assert ans.grounded and ans.fallback, q
        assert "don't have enough data" not in ans.text and needle in ans.text, (q, ans.text)
        assert "[F" not in ans.text


def test_setup_answers_add_the_handling_facts_only_when_present(real_sheet: FactSheet) -> None:
    """Only the short "Setup to try" line joins a setup answer (the radio read the whole handling summary there)."""
    sheet = real_sheet
    facts = sheet.select({"session", "corners", "observations", "compare", "setup", "balance"})
    with_balance = deterministic_answer(Intent("setup"), facts, sheet)
    assert "Handling summary" not in with_balance and "pushes wide" not in with_balance
    assert "Something to try after the session" in with_balance
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


def test_a_named_corner_is_the_question_s_corner(real_sheet: FactSheet, names: dict[str, str]) -> None:
    """A question such as "why does the car push wide at Stowe" names the corner by the track model's curated name,
    not only "turn N" / "TN"."""
    assert real_sheet.model is not None
    t8 = names["T8"]
    model = replace(
        real_sheet.model,
        corners=[replace(c, display_name="Stowe" if c.name == t8 else None) for c in real_sheet.model.corners],
    )
    sheet = FactSheet(facts=real_sheet.facts, model=model)
    i = named_corner(detect_intent("why does the car push wide at Stowe"), "why does the car push wide at Stowe", sheet)
    assert (i.name, i.corner, i.topic) == ("balance", "Stowe", "understeer")
    assert named_corner(Intent("fuel"), "fuel at Stowe", sheet).corner is None  # other intents are untouched
    assert named_corner(Intent("line"), "how's my line through the chicane", sheet).corner is None
    text = deterministic_answer(i, sheet.facts, sheet)
    assert f"The car pushed wide mid-corner at {t8}" in text, text


def test_missing_data_is_said_as_missing(real: SessionAnalysis) -> None:
    """A session with only its reference lap: no "within 1 m everywhere over 0 compared laps", no "nothing recurs"
    from one lap."""
    ref = real.ref_lap_id
    assert ref is not None
    one = replace(
        real,
        laps=[lap for lap in real.laps if lap["id"] == ref],
        comparisons={},
        analyses={ref: real.analyses[ref]},
    )
    clear_cache()
    try:
        facts = technique_facts(one)
    finally:
        clear_cache()
    texts = [t for _, t, *_ in facts]
    line = next(t for t in texts if t.startswith("Racing line vs reference"))
    assert "not available" in line and "No other lap compared with your reference lap" in line, line
    assert not any("over 0 compared" in t or "every corner" in t for t in texts)
    summary = next(t for t in texts if t.startswith("Handling summary"))
    assert "over 1 lap with slip data; needs at least 2 laps to judge" in summary, summary
    assert not any("1 laps" in t for t in texts)


def test_abs_off_is_claimed_only_when_every_lap_had_it_off(sa: SessionAnalysis) -> None:
    st = analyse_session(sa)
    assert st.assists.abs is False and st.assists.abs_unknown_laps == 0
    lock = next(t for _, t, *_ in _slip_facts(st) if t.startswith("Lock-ups"))
    assert "in total, ABS off)" in lock and "unknown" not in lock
    unknown = replace(st, assists=replace(st.assists, abs_unknown_laps=1))
    lock = next(t for _, t, *_ in _slip_facts(unknown) if t.startswith("Lock-ups"))
    assert ABS_OFF_OR_UNKNOWN in lock and "ABS off)" not in lock


def test_no_slip_from_the_game_is_said_on_the_radio(sa: SessionAnalysis) -> None:
    st = analyse_session(sa)
    gt7 = replace(
        st,
        session={**st.session, "game": "gt7"},
        available={**st.available, "slip": Availability(False, NO_SLIP_GAME)},
    )
    facts = _slip_facts(gt7)
    none = next(f for f in facts if f[1].startswith("Lock-ups and wheelspin: not available"))
    assert none[4] == "I can't see tyre slip in this game yet, so I can't judge lock-ups or wheelspin."
    sheet = FactSheet()
    for t in facts:
        sheet.add(*t[:3], corner=t[3], say=t[4])
    for q in ("am I locking up", "how much wheelspin"):
        assert "can't see tyre slip" in deterministic_answer(detect_intent(q), sheet.facts, sheet), q


def test_topic_answers_say_only_what_was_asked() -> None:
    """For "am I smooth on the throttle", the throttle sentence of the corner's fact, not its wheelspin and lifts too; a
    measure never taken (GT7 sends no steering, so no trail braking) is said as not measured."""
    sheet = FactSheet()
    sheet.add(
        "technique",
        "Brake and throttle technique at T9 on lap 2 vs reference lap 3: ramp 1.20 s vs 0.80 s. Wheelspin 0.40s.",
        {
            "lap": 2,
            "kinds": ["throttle_ramp", "wheelspin"],
            "corner_name": "T9",
            "simple": {
                "throttle_ramp": "You took longer to reach full throttle than on your reference.",
                "wheelspin": "The rear wheels spun more on the exit than on your reference.",
            },
            "habit_simple": {},
        },
        corner="T9",
        say="At T9, on lap 2, you took longer to reach full throttle than on your reference.",
    )
    sheet.add(
        "technique",
        "Brake and throttle vs reference lap 3 (latest compared lap at each corner): throttle ramp differs at T9.",
        {"differs_keys": {"throttle_ramp": ["T9"]}, "measured_keys": ["T9"], "close": ["coast"]},
    )
    text = deterministic_answer(detect_intent("am I smooth on the throttle"), sheet.facts, sheet)
    assert text.startswith("At T9, on lap 2, you took longer to reach full throttle") and "spun" not in text, text
    text = deterministic_answer(detect_intent("am I trail braking"), sheet.facts, sheet)
    assert text.startswith("I couldn't measure your trail braking against your reference."), text
    text = deterministic_answer(detect_intent("am I coasting"), sheet.facts, sheet)
    assert text.startswith("On your latest laps, your coasting was close to your reference"), text


def test_braking_assist_answers_brake_questions_honestly() -> None:
    sheet = FactSheet()
    sheet.add("technique", "Braking assist is on (medium): the game adds its own braking.", {"braking_assist": 2})
    sheet.add("technique", "Lock-ups: ABS is on, so the game prevents them and lock-ups are not analysed.", {})
    text = deterministic_answer(detect_intent("am I trail braking"), sheet.facts, sheet)
    assert text.startswith("The braking assist is on, so I can't judge your trail braking."), text


def test_standing_starts_are_left_out_of_the_balance(real: SessionAnalysis) -> None:
    """Lap 1 from the grid is not driven at the limit like a flying lap: it never counts towards a symptom."""
    first = min(real.laps, key=lambda lap: lap["lap_number"])
    laps = [
        {**lap, "flags": [*lap.get("flags", []), LapFlag.STANDING_START]} if lap["id"] == first["id"] else lap
        for lap in real.laps
    ]
    clear_cache()
    try:
        st = analyse_session(replace(real, laps=laps))
    finally:
        clear_cache()
    entry = next(e for e in st.laps if e.lap_id == first["id"])
    assert entry.usable and entry.balance_reason == "standing start"
    for c in st.corners:
        assert all(lc.representative == (lc.lap_id != first["id"]) for lc in c.laps)
        if c.balance:
            assert all(s.laps <= len(real.laps) - 1 for s in c.balance.values())
    assert "Standing starts" in (st.available["balance"].note or "")
    assert _line_facts(st)  # the line still uses that lap
