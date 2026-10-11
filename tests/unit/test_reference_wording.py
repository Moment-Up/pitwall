"""coachref: coaching wording against another driver's lap (``coach.reference_wording``).

Observations are built the way ``analysis.coaching.observations_for_comparison`` builds them (same fields, same
evidence shape); the reworded texts must keep every number of the original, name the other driver, never mention
"your reference" or the reference lap number, stay within the glance length, and never tell the driver to brake
later.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest

from pitwall.analysis.coaching import SHORT_MAX_CHARS, Observation
from pitwall.analysis.track_identity import CornerText
from pitwall.coach.reference_wording import descriptor_labels, lap_date, reword_observations

TEXTS = {
    "T3": CornerText(short="T3", long="Turn 3 (Remus)", voice="Turn 3, Remus"),
    "T9": CornerText(short="T10 (2)", long="Turn 10, part 2 (Red Bull Mobile Grandstand)", voice="Turn 10"),
}
FORBIDDEN = (re.compile(r"\bbrake later\b", re.I), re.compile(r"\blater braking point\b", re.I))


def ob(
    kind: str, value: float, *, corner: str = "T3", impact: float | None = 0.21, positive: bool = False
) -> Observation:
    ev: dict[str, Any] = {
        "time_delta_s": impact,
        "exit_speed_delta_kph": -6.4,
        "ref": {"min_speed_kph": 91.2, "brake_start_m": 1140.9},
        "lap": {"min_speed_kph": 85.0, "brake_start_m": 1128.0},
    }
    return Observation(
        id=f"L4:{corner}:{kind}",
        kind=kind,
        corner=corner,
        lap_number=4,
        ref_lap_number=7,
        metric="m",
        value=value,
        unit="m",
        impact_s=impact,
        confidence=0.83,
        text=f"{corner}: original text against your reference (lap 7).",
        evidence=ev,
        consistency="3 of the last 4 laps",
        consistency_ratio=0.75,
        positive=positive,
        corner_label="T3",
        corner_voice="Turn 3, Remus",
        text_simple="Turn 3 (Remus): original simple text.",
        short="T3: original",
    )


ALL = [
    ob("brake_early", -12.4),
    ob("brake_late_overdrive", 9.6),
    ob("low_min_speed", -6.2),
    ob("overspeed_apex", 5.1),
    ob("late_throttle", 21.0),
    ob("coasting", 18.4),
    ob("exit_gain", 4.6, impact=-0.08, positive=True),
]


def test_each_kind_is_worded_against_the_other_driver() -> None:
    out = {o.kind: o for o in reword_observations(ALL, "Sam", TEXTS)}
    assert (
        out["brake_early"].text
        == "Turn 3 (Remus): you're braking about 12 m earlier than Sam, losing 0.21 s through the corner."
    )
    assert out["brake_early"].text_simple == "Turn 3 (Remus): you braked about 12 m earlier than Sam."
    assert out["brake_early"].short == "T3: braked 12 m earlier than Sam"
    assert out["low_min_speed"].text == (
        "Turn 3 (Remus): Sam carries 6 km/h more through the slowest point (91 vs 85 km/h), losing 0.21 s through "
        "the corner."
    )
    assert out["low_min_speed"].short == "T3: Sam carries 6 km/h more"
    assert out["brake_late_overdrive"].text.startswith(
        "Turn 3 (Remus): you're braking 10 m later than Sam but exiting 6 km/h slower"
    )
    assert (
        out["overspeed_apex"].text_simple
        == "Turn 3 (Remus): the extra speed in cost you on the way out: 6 km/h slower than Sam."
    )
    assert (
        out["late_throttle"].text
        == "Turn 3 (Remus): Sam is back on full throttle 21 m sooner, losing 0.21 s through the corner."
    )
    assert out["coasting"].short == "T3: 18 m more coasting than Sam"
    assert (
        out["exit_gain"].text
        == "Turn 3 (Remus): good - your exit is 5 km/h faster than Sam's and you gained 0.08 s there."
    )
    for o in out.values():
        assert o.ref_name == "Sam"
        assert "Sam" in o.text and "Sam" in (o.text_simple or "")


@pytest.mark.parametrize("name", ["Sam", "Alexandra-Marie", "A" * 40])
@pytest.mark.parametrize("corner", ["T3", "T9"])
def test_numbers_identity_and_lengths_survive(name: str, corner: str) -> None:
    obs = [dataclasses.replace(o, corner=corner, id=f"L4:{corner}:{o.kind}") for o in ALL]
    for before, after in zip(obs, reword_observations(obs, name, TEXTS), strict=True):
        for f in ("id", "kind", "corner", "value", "impact_s", "confidence", "evidence", "positive", "lap_number"):
            assert getattr(after, f) == getattr(before, f)
        assert after.priority == before.priority
        assert f"{round(abs(before.value))}" in after.text  # the observation's own number
        assert after.short is not None and len(after.short) <= SHORT_MAX_CHARS
        for t in (after.text, after.text_simple or "", after.short):
            assert "your reference" not in t
            assert "lap 7" not in t and "(lap" not in t  # never the other driver's lap number
            assert not any(rx.search(t) for rx in FORBIDDEN)
            assert not re.match(r"^\W*brake\b", t.split(": ", 1)[-1], re.I)  # no instruction


def test_incident_and_unknown_kinds_keep_their_text() -> None:
    inc = ob("incident", 2.7)
    odd = ob("something_new", 1.0)
    out = reword_observations([inc, odd], "Sam", TEXTS)
    assert [o.text for o in out] == [inc.text, odd.text]
    assert all(o.ref_name == "Sam" for o in out)


def test_own_reference_is_not_reworded() -> None:
    out = reword_observations(ALL, None, TEXTS)
    assert out == ALL
    assert all(o.ref_name is None for o in out)
    assert reword_observations(ALL, "", TEXTS) == ALL


def test_without_corner_texts_the_learned_name_is_used() -> None:
    (o,) = reword_observations([ob("brake_early", -12.0, corner="T7")], "Sam")
    assert o.text.startswith("T7: you're braking about 12 m earlier than Sam")
    assert o.short == "T7: braked 12 m earlier than Sam"


def test_long_bodies_fall_back_to_the_short_own_wording() -> None:
    (o,) = reword_observations([ob("late_throttle", 21.0)], "B" * 40, TEXTS)
    assert o.short == "T3: full throttle 21 m later"


def test_descriptor_labels() -> None:
    t = 1_759_500_000.0  # 3 Oct 2025 (local dates differ by at most a day)
    date = lap_date(t)
    assert date is not None and date.endswith("Oct")
    assert descriptor_labels("own_best", True, False, "Ann", 3, t) == ("Your best", "your reference", None)
    assert descriptor_labels("own_best", True, True, "Ann", 3, t) == ("Your pinned lap", "your reference", None)
    assert descriptor_labels("household_best", True, False, "Ann", 3, t) == (
        "Family record (you)",
        "your reference",
        None,
    )
    assert descriptor_labels("household_best", False, False, "Sam", 3, t) == (
        "Family record · Sam",
        "the family record",
        "Sam",
    )
    assert descriptor_labels("driver_best", False, False, "Sam", 3, t) == ("Sam's best", "Sam's best", "Sam")
    assert descriptor_labels("lap", False, False, "Sam", 7, t) == (f"Sam · lap 7 · {date}", "Sam's lap", "Sam")
    assert descriptor_labels("lap", True, False, "Ann", 7, t) == (f"Your lap 7 · {date}", "your saved lap", None)
    assert lap_date(None) is None
