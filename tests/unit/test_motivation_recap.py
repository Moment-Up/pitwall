"""Today's 3 things (pure): each step of each order of choices, verbatim observation text, beginner wording and kinds,
special sessions, history as at the session, habits not one-offs (habits spec 6: a habit still there to work on, a
fixed habit that went well), and never "brake later"."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from pitwall.analysis import coaching
from pitwall.drivers import coaching_limits
from pitwall.motivation import recap as R
from pitwall.motivation import rules
from pitwall.motivation.model import GoalRow, History, LapRow, SessionRow
from tests.unit.motivation_data import AUSTRIA_HAAS, DAY, T0, goal, history, lap, laps, sess

BRAKE_LATER = re.compile(r"brak\w* later|later brak", re.I)


def obs(
    lap_number: int,
    kind: str,
    corner: str,
    *,
    positive: bool = False,
    impact: float = 0.23,
    confidence: float = 0.9,
    priority: float | None = None,
    text: str | None = None,
    simple: str | None = None,
    value: float | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{corner}-{kind}-{lap_number}",
        "kind": kind,
        "corner": corner,
        "corner_label": corner,
        "lap_number": lap_number,
        "impact_s": -impact if positive else impact,
        "confidence": confidence,
        "priority": impact * confidence if priority is None else priority,
        "positive": positive,
        "text": text or f"{corner}: {kind} text",
        "text_simple": simple,
        "value": value,
        "unit": unit,
    }


def inp(
    s: SessionRow,
    session_laps: list[LapRow],
    h: History | None,
    *,
    observations: dict[int, list[dict[str, Any]]] | None = None,
    compared: int = 0,
    skill: str = "intermediate",
    goals: Sequence[GoalRow] = (),
    counts: bool = True,
    why: str | None = None,
    corner_laps: R.CornerLaps | None = None,
) -> R.RecapInput:
    return R.RecapInput(
        session=s,
        laps=session_laps,
        observations=observations or {},
        compared=compared,
        limits=coaching_limits(skill),
        counts=counts,
        history=h.until(s.id) if h is not None else None,
        goals=goals,
        why_progress=why,
        corner_laps=corner_laps,
    )


def build(i: R.RecapInput, lap_numbers: dict[int, int] | None = None) -> R.Recap:
    rec = R.build_recap(i, lap_numbers)
    for t in (rec.went_well, rec.work_on, rec.progress):
        if t is not None and t.source != "observation":
            assert not BRAKE_LATER.search(t.text) and not BRAKE_LATER.search(t.text_simple), t
    return rec


# ---------------------------------------------------------------------------------------------- observations
def test_ranking_ports_the_dashboard() -> None:
    o = {
        10: [obs(2, "low_min_speed", "Turn 6"), obs(2, "brake_early", "Turn 4", impact=0.5)],
        11: [obs(3, "low_min_speed", "Turn 6", text="Turn 6: minimum speed is 9 km/h lower than your reference.")],
        12: [obs(4, "low_min_speed", "Turn 6"), obs(4, "exit_gain", "Turn 7", positive=True)],
    }
    limits = coaching_limits("intermediate")
    top = R.rank_points(o, 3, False, limits)
    # Turn 6 (3 x 0.207 / 3 = 0.207) beats Turn 4's one-off (0.45 / 3 = 0.15): a habit outranks a big one-off
    assert [(p.corner, p.kind, p.seen, p.compared) for p in top] == [
        ("Turn 6", "low_min_speed", 3, 3),
        ("Turn 4", "brake_early", 1, 3),
    ]
    assert top[0].latest_lap_id == 12
    assert [p.corner for p in R.rank_points(o, 3, True, limits)] == ["Turn 7"]
    # the incident kind is never coaching
    assert R.rank_points({1: [obs(1, "incident", "Turn 1", impact=3.0)]}, 1, False, limits) == []


def test_limits_filter_on_the_latest_occurrence() -> None:
    o = {1: [obs(1, "coasting", "Turn 2"), obs(1, "low_min_speed", "Turn 3", confidence=0.7)]}
    beginner = coaching_limits("beginner")  # 0.75 confidence, beginner kinds only (no coasting)
    assert R.rank_points(o, 1, False, beginner) == []
    assert {p.kind for p in R.rank_points(o, 1, False, coaching_limits("advanced"))} == {"coasting", "low_min_speed"}
    small = {1: [obs(1, "low_min_speed", "Turn 3", impact=0.04)]}
    assert R.rank_points(small, 1, False, coaching_limits("intermediate")) == []
    assert R.rank_points(small, 1, False, coaching_limits("advanced"))


def test_observation_text_is_verbatim_and_simple_for_beginners() -> None:
    s = sess("a")
    ls = laps("a", [71_000, 70_900])
    text = (
        "Turn 6: minimum speed is 9 km/h lower than your reference (164 vs 173 km/h), losing 0.33 s through the corner."
    )
    simple = "Turn 6: you were 9 km/h slower at the slowest point of the corner."
    # one lap: a one-off is the one to work on only when it is a big one (the radio's rule, 0.30 s+)
    o = {ls[1].id: [obs(2, "low_min_speed", "Turn 6", impact=0.33, text=text, simple=simple)]}
    rec = build(inp(s, ls, history((s, ls)), observations=o, compared=1))
    assert rec.work_on is not None and rec.work_on.text == text and rec.work_on.text_simple == simple
    assert rec.work_on.evidence == "Seen on 1 of 1 lap compared with your reference"
    assert rec.work_on.observation_key == "Turn 6:low_min_speed" and rec.work_on.lap_id == ls[1].id
    # a verbatim observation may describe braking; it is the coach's own text (which never says "brake later")
    late = {
        ls[1].id: [
            obs(2, "brake_late_overdrive", "Turn 1", impact=0.4, text="Turn 1: braking 9 m later but slower out.")
        ]
    }
    rec2 = R.build_recap(inp(s, ls, history((s, ls)), observations=late, compared=1, skill="advanced"))
    assert rec2.work_on is not None and rec2.work_on.source == "observation"


# ---------------------------------------------------------------------------------------------- went well
def test_went_well_order() -> None:
    a = laps("a", [71_745, 72_000])
    b = laps("b", [71_000, 70_549, 72_000])
    sa, sb = sess("a", T0), sess("b", T0 + 60)
    h = history((sa, a), (sb, b))
    pos = {b[1].id: [obs(2, "exit_gain", "Turn 7", positive=True)]}
    # 1. a personal best (beats an earlier session)
    w = build(inp(sb, b, h, observations=pos, compared=2)).went_well
    assert w is not None and w.source == "pb"
    assert w.text == "New personal best at Austria in the Haas: 1:10.549 on lap 2, 1.196 s faster than before."
    assert w.text_simple == "Your fastest lap ever at Austria in the Haas: 1:10.549."
    # 2. the first clean laps here in this car: a first-ever best counts as a best and comes first too (plan 2.6)
    first = build(inp(sa, a, h, observations={a[0].id: pos[b[1].id]}, compared=1))
    w1 = first.went_well
    assert w1 is not None and w1.source == "first_clean" and w1.fact_key == "first_clean:f1_25:f1:17:f1:team:7"
    assert w1.text == "First clean laps here in the Haas: best 1:11.745 on lap 1."
    assert w1.text_simple == "Your first clean laps here in the Haas: best 1:11.745."
    assert first.progress is not None and first.progress.source == "sessions_week"  # said once, not twice
    one = [lap(1, 84_528, sid="one"), lap(2, 85_000, sid="one", flags=["invalid"])]
    so = sess("one", T0, car_id="f1:team:1", car_name="McLaren")
    w1b = build(inp(so, one, history((so, one)))).went_well
    assert w1b is not None and w1b.text == "First clean lap here in the McLaren: 1:24.528."
    #    ... only for real, owned driving (a replay or someone else's session is nobody's first)
    assert build(inp(so, one, None, counts=False)).went_well is None
    #    the top positive point (a session that is neither a best nor a first)
    c0 = laps("c0", [72_000, 72_400])
    s0 = sess("c0", T0 + 30)
    w2 = build(inp(s0, c0, history((sa, a), (s0, c0)), observations={c0[0].id: pos[b[1].id]}, compared=1)).went_well
    assert w2 is not None and w2.source == "observation"
    # 3. a run of 3 clean laps
    c = laps("c", [72_000, 72_100, 72_200])
    sc = sess("c", T0 + 120)
    w3 = build(inp(sc, c, history((sa, a), (sb, b), (sc, c)))).went_well
    assert w3 is not None and (w3.source, w3.text) == ("clean_streak", "3 clean laps in a row.")
    # 4. faster from the first clean lap to the best (0.1 s or more)
    d = [lap(1, 73_000, sid="d"), lap(2, 72_000, sid="d", flags=["invalid"]), lap(3, 71_800, sid="d")]
    sd = sess("d", T0 + 180, session_type="practice")
    w4 = build(inp(sd, d, history((sa, a), (sb, b), (sd, d)))).went_well
    assert w4 is not None and w4.source == "in_session_gain"
    assert w4.text == "Your laps got 1.20 s faster from your first clean lap to your best."
    #    ... but race lap 1 is from the grid, not a measure of getting faster (not always flagged in F1 25)
    rd = sess("d", T0 + 180, session_type="race")
    w4r = build(inp(rd, d, history((sa, a), (sb, b), (rd, d)))).went_well
    assert w4r is None or w4r.source != "in_session_gain"
    # 5. every lap clean (no gain, no run of 3)
    e = laps("e", [72_000, 72_050])
    se = sess("e", T0 + 240)
    w5 = build(inp(se, e, history((sa, a), (sb, b), (se, e)))).went_well
    assert w5 is not None and (w5.source, w5.text) == ("all_clean", "Both timed laps were clean.")
    # nothing
    f = [lap(1, 72_000, sid="f", flags=["invalid"])]
    sf = sess("f", T0 + 300)
    rec = build(inp(sf, f, history((sf, f))))
    assert rec.went_well is None and rec.why["went_well"] == R.WHY_NOTHING_WELL


# ---------------------------------------------------------------------------------------------- work on
def test_work_on_order() -> None:
    s = sess("a")
    ls = laps("a", [71_000, 70_900])
    neg = {ls[1].id: [obs(2, "low_min_speed", "Turn 6", impact=0.35)]}  # a big one-off
    assert build(inp(s, ls, None, observations=neg, compared=1, counts=False)).work_on.source == "observation"  # type: ignore[union-attr]
    bad = [
        lap(1, 71_000, sid="b"),
        lap(2, 70_000, sid="b", flags=["invalid"]),
        lap(3, 72_000, sid="b", flags=["flashback"]),
        lap(4, 75_000, sid="b", flags=["pit_in"]),  # neutral: not counted either way
        lap(5, 71_000, sid="b"),
    ]
    w = build(inp(sess("b"), bad, None, counts=False)).work_on
    assert w is not None and w.source == "lap_hygiene"
    assert w.text == "2 of 4 laps did not count: 1 invalidated by the game, 1 with a flashback."
    assert w.text_simple == "2 timed laps did not count this time: keep them on the track next time."
    one = [lap(1, 71_000, sid="g"), lap(2, 70_000, sid="g", valid=False), lap(3, 71_000, sid="g")]
    w1 = build(inp(sess("g"), one, None, counts=False)).work_on
    assert w1 is not None and w1.text == "Lap 2 did not count: the game invalidated it."
    assert w1.text_simple == "Lap 2 did not count (the game cancelled it): keep it on the track next time."
    incomplete = [lap(1, None, sid="c", flags=["incomplete"]), lap(2, 78_000, sid="c", flags=["incomplete"])]
    w2 = build(inp(sess("c"), incomplete, None, counts=False)).work_on
    assert w2 is not None and w2.source == "no_clean_lap"
    single = [lap(1, 90_000, sid="d", flags=["standing_start"]), lap(2, 78_000, sid="d")]
    w3 = build(inp(sess("d"), single, None, counts=False)).work_on
    assert w3 is not None and w3.source == "single_clean_lap"
    assert w3.text == "Only one clean lap: drive two or more next time so they can be compared."
    # one-shot qualifying has one timed lap by design: never "drive two or more" (review U11)
    osq = sess("o", session_type="qualifying", session_type_raw="One-Shot Qualifying", formula="F2")
    w4 = build(inp(osq, [lap(1, 116_133, sid="o")], None, counts=False)).work_on
    assert w4 is not None and w4.source == "single_clean_lap" and "two or more" not in w4.text
    assert w4.text.startswith("One-shot qualifying has one timed lap")
    assert "two or more" not in w4.text_simple
    rec = build(inp(sess("e"), laps("e", [71_000, 71_100]), None, counts=False))
    assert rec.work_on is None and rec.why["work_on"] == R.WHY_NOTHING_WORK


# ---------------------------------------------------------------------------------------------- habits (spec 6)
def _times(ls: list[LapRow], corner_times: dict[str, list[float | None]]) -> R.CornerLaps:
    """Corner -> {lap id: time} for laps 2.. (lap 1 is the reference: never compared with itself)."""
    return {c: {lap.id: t for lap, t in zip(ls[1:], times, strict=True)} for c, times in corner_times.items()}


def test_work_on_is_a_habit_still_there_not_a_bigger_one_off() -> None:
    s, ls = sess("h"), laps("h", [71_000] * 7)  # laps 2-7 compared with lap 1
    o: dict[int, list[dict[str, Any]]] = {lap.id: [] for lap in ls[1:]}
    for k in (1, 2, 4, 5):  # laps 2, 3, 5, 6: Turn 6 on 4 of 6 laps, and on lap 6 (one of the last 3)
        o[ls[k].id].append(obs(k + 1, "low_min_speed", "Turn 6", impact=0.15, value=-9.0))
    o[ls[3].id].append(obs(4, "brake_early", "Turn 4", impact=0.9, value=-25.0))  # one big lap
    times = _times(ls, {"Turn 6": [0.15, 0.15, 0.0, 0.15, 0.15, 0.01], "Turn 4": [0.0, 0.0, 0.9, 0.0, 0.0, 0.0]})
    i = inp(s, ls, None, observations=o, compared=6, counts=False, corner_laps=times)
    # the ranking alone would pick the one-off (0.81 / 6 beats 4 x 0.135 / 6)
    assert R.rank_points(o, 6, False, i.limits)[0].corner == "Turn 4"
    w = build(i).work_on
    assert w is not None and w.observation_key == "Turn 6:low_min_speed" and w.lap_id == ls[5].id
    assert w.evidence == "Seen on 4 of 6 laps compared with your reference"


def test_work_on_falls_back_to_the_top_big_one_off_only() -> None:
    s, ls = sess("o"), laps("o", [71_000, 71_100, 71_200])
    small = obs(2, "low_min_speed", "Turn 2", impact=0.29, confidence=1.0)  # ranks first, but under 0.30 s
    big = obs(3, "brake_early", "Turn 3", impact=0.32, confidence=0.8)  # the radio's big one-off
    unsure = obs(3, "coasting", "Turn 5", impact=0.5, confidence=0.7)  # big, but not measured clearly enough
    o = {ls[1].id: [small], ls[2].id: [big, unsure]}
    i = inp(s, ls, None, observations=o, compared=2, counts=False)
    assert [p.corner for p in R.rank_points(o, 2, False, i.limits)][:2] == ["Turn 5", "Turn 2"]
    w = build(i).work_on
    assert w is not None and w.source == "observation" and w.observation_key == "Turn 3:brake_early"
    # no big one-off: no point to work on (the laps say nothing either: two clean laps)
    rec = build(inp(s, ls, None, observations={ls[1].id: [small], ls[2].id: [unsure]}, compared=2, counts=False))
    assert rec.work_on is None and rec.why["work_on"] == R.WHY_NOTHING_WORK
    # ...and the laps' own Work on still applies without one
    bad = [lap(1, 71_000, sid="p"), lap(2, 70_000, sid="p", flags=["invalid"]), lap(3, 71_000, sid="p")]
    w2 = build(inp(sess("p"), bad, None, observations={bad[2].id: [small]}, compared=1, counts=False)).work_on
    assert w2 is not None and w2.source == "lap_hygiene"


def _fixed_case(
    t1: list[float | None] | None = None, extra: dict[int, list[dict[str, Any]]] | None = None
) -> tuple[R.RecapInput, list[LapRow]]:
    """Turn 1: braking early on laps 2 and 3 (0.20 / 0.25 s lost), then laps 4-6 at Turn 1 (times ``t1``)."""
    s, ls = sess("f"), laps("f", [71_000] * 6)
    simple = "Turn 1: you braked about 15 m earlier than on your reference lap."
    o: dict[int, list[dict[str, Any]]] = {lap.id: [] for lap in ls[1:]}
    o[ls[1].id].append(obs(2, "brake_early", "T1", impact=0.20, value=-14.0, unit="m", simple=simple))
    o[ls[2].id].append(obs(3, "brake_early", "T1", impact=0.25, value=-16.2, unit="m", simple=simple))
    for k, v in (extra or {}).items():
        o[ls[k].id].extend(v)
    times = _times(ls, {"T1": [0.20, 0.25, *(t1 or [0.0, -0.05, 0.01])]})
    return inp(s, ls, None, observations=o, compared=5, counts=False, corner_laps=times), ls


def test_a_fixed_habit_went_well_and_is_not_the_one_to_work_on() -> None:
    i, ls = _fixed_case()
    rec = build(i)
    w = rec.went_well
    assert w is not None and w.source == "fixed" and w.kind == "went_well"
    assert w.text == "T1: sorted - clean on your last 3 laps (was braking about 15 m early)."
    assert w.text_simple == "Turn 1: sorted - clean on your last 3 laps."
    assert w.evidence == "Seen on 2 of 5 laps compared with your reference, not on your last 3 at this corner"
    assert (w.observation_key, w.lap_id, w.lap_number) == ("T1:brake_early", ls[5].id, 6)
    assert w.values == {"seen": 2, "compared": 5, "clean_laps": 3, "value": -15.1, "unit": "m"}
    assert not BRAKE_LATER.search(w.text) and not BRAKE_LATER.search(w.text_simple)
    # it ranks first but is sorted: not the one to work on (and no other point: nothing)
    assert rec.work_on is None
    # a fixed habit or the top praise, whichever ranks higher (the same score as Work on's)
    plus = _fixed_case(extra={4: [obs(5, "exit_gain", "T7", positive=True)]})[0]
    assert build(plus).went_well.source == "fixed"  # type: ignore[union-attr]
    strong = {k: [obs(k + 1, "exit_gain", "T7", positive=True, priority=0.5)] for k in (2, 3, 4)}
    praise = build(_fixed_case(extra=strong)[0]).went_well
    assert praise is not None and praise.source == "observation" and praise.observation_key == "T7:exit_gain"
    # ...and after a personal best (a best always comes first)
    a, b = laps("a", [71_745]), laps("b", [71_000] * 6)
    sa, sb = sess("a", T0), sess("b", T0 + 60)
    pb = R.RecapInput(**{**vars_of(i), "session": sb, "laps": b, "counts": True, "history": history((sa, a), (sb, b))})
    assert build(pb).went_well.source == "pb"  # type: ignore[union-attr]


def test_fixed_needs_three_clean_faster_laps_at_the_corner() -> None:
    # still braking early on the latest lap: not fixed, still there
    i, _ = _fixed_case([0.0, -0.05, 0.2], extra={4: [obs(6, "brake_early", "T1", impact=0.2, value=-14.0)]})
    rec = build(i)
    assert rec.went_well is not None and rec.went_well.source == "clean_streak"
    assert rec.work_on is not None and rec.work_on.observation_key == "T1:brake_early"
    # two laps after it are not enough
    s, short = sess("g"), laps("g", [71_000] * 5)
    two = {
        short[1].id: [obs(2, "brake_early", "T1", value=-14.0)],
        short[2].id: [obs(3, "brake_early", "T1", value=-16.0)],
    }
    t = _times(short, {"T1": [0.2, 0.2, 0.0, 0.0]})
    assert R.fixed_habit(inp(s, short, None, observations=two, compared=4, counts=False, corner_laps=t)) is None
    # another fault at the corner on one of the last 3 laps: not clean
    other = _fixed_case(extra={4: [obs(6, "coasting", "T1", impact=0.03)]})[0]
    assert R.fixed_habit(other) is None
    # braking early fixed = braking later: praised only when the corner was faster on each of the 3 laps than on any
    # lap it was seen on (0.20 s lost at best), and every time known
    assert R.fixed_habit(_fixed_case([0.0, 0.19, 0.0])[0]) is not None
    assert R.fixed_habit(_fixed_case([0.0, 0.20, 0.0])[0]) is None
    assert R.fixed_habit(_fixed_case([0.0, None, 0.0])[0]) is None


def test_fixed_without_comparisons_uses_what_the_observations_prove() -> None:
    s, ls = sess("k"), laps("k", [71_000] * 6)
    o = {
        ls[1].id: [obs(2, "low_min_speed", "T6", value=-12.0)],
        ls[2].id: [obs(3, "low_min_speed", "T6", value=-10.0)],
        ls[3].id: [obs(4, "exit_gain", "T6", positive=True)],
        ls[4].id: [obs(5, "exit_gain", "T6", positive=True)],
        ls[5].id: [],
    }
    # the corner shows on laps 4 and 5 only: two laps after it, not three
    assert R.fixed_habit(inp(s, ls, None, observations=o, compared=5, counts=False)) is None
    o[ls[5].id] = [obs(6, "exit_gain", "T6", positive=True)]
    w = R.fixed_habit(inp(s, ls, None, observations=o, compared=5, counts=False))
    assert w is not None and w.text == "T6: sorted - clean on your last 3 laps (was about 11 km/h slower at the apex)."
    # an incident there is no evidence of anything
    o[ls[5].id] = [obs(6, "incident", "T6", impact=3.0)]
    assert R.fixed_habit(inp(s, ls, None, observations=o, compared=5, counts=False)) is None


def test_compared_corner_laps_from_the_comparisons() -> None:
    from pitwall.analysis.compare import Compatibility, CornerDelta, CornerMetrics, LapComparison

    m = CornerMetrics(corner="T1", segment_time_s=10.0, min_speed_kph=100.0)
    crawl = CornerMetrics(corner="T1", segment_time_s=14.0, min_speed_kph=20.0)

    def cd(corner: str, t: float | None, cmp: CornerMetrics = m) -> CornerDelta:
        return CornerDelta(corner, t, None, None, None, None, None, None, None, None, None, None, m, cmp)

    def comp(*corners: CornerDelta, ok: bool = True) -> LapComparison:
        return LapComparison(1, 2, 0.1, [], [], list(corners), Compatibility(ok=ok))

    out = R.compared_corner_laps(
        {
            12: comp(cd("T1", 0.1), cd("T2", None)),
            11: comp(cd("T1", -0.05)),
            13: comp(cd("T1", 0.3), ok=False),  # not usable: no evidence either way
            14: comp(cd("T1", 4.0, crawl), cd("T2", 0.02)),  # an incident at T1
        }
    )
    assert out == {"T1": {11: -0.05, 12: 0.1}, "T2": {12: None, 14: 0.02}}
    assert list(out["T1"]) == [11, 12]
    # observations add the laps they prove, and fill an unknown time with their impact
    both = R.corner_laps({12: [obs(3, "low_min_speed", "T2", impact=0.07)], 15: [obs(4, "incident", "T1")]}, out)
    assert both == {"T1": {11: -0.05, 12: 0.1}, "T2": {12: 0.07, 14: 0.02}}


def test_was_words_describe_and_never_say_brake_later() -> None:
    kinds = ("brake_early", "brake_late_overdrive", "low_min_speed", "overspeed_apex", "late_throttle", "coasting")
    for k in kinds:
        w = R.was_words(k, -12.4)
        assert w and not BRAKE_LATER.search(w), (k, w)
    assert R.was_words("brake_early", -14.6) == "braking about 15 m early"
    assert R.was_words("exit_gain", 5.0) is None and R.was_words("coasting", None) is None


# ---------------------------------------------------------------------------------------------- progress
def test_progress_goal_reached_first() -> None:
    a = laps("a", [70_400, 69_981])
    s = sess("a")
    g = goal(
        "lap_time",
        70_000,
        scope=AUSTRIA_HAAS,
        status="achieved",
        achieved_unix=T0 + 100,
        achieved_session_id="a",
        achieved_lap_id=a[1].id,
        achieved_value=69_981,
    )
    p = build(inp(s, a, history((s, a)), goals=[g]), {a[1].id: 7}).progress
    assert p is not None and p.source == "goal_reached" and p.goal_id == 1
    # the card's heading says "Goal reached": the text does not repeat it
    assert p.text == "A lap under 1:10.000 (1:09.981 on lap 7)."
    assert p.text_simple == "You did it: beat 1:10.000."
    assert p.values["goals"] == 1


def test_progress_celebrates_every_goal_reached() -> None:
    a = laps("a", [70_400, 69_981, 70_100])
    s = sess("a")
    lap_goal = goal(
        "lap_time",
        70_000,
        scope=AUSTRIA_HAAS,
        status="achieved",
        achieved_unix=T0 + 100,
        achieved_session_id="a",
        achieved_lap_id=a[1].id,
        achieved_value=69_981,
    )
    run = goal(
        "clean_streak",
        3,
        gid=2,
        status="achieved",
        achieved_unix=T0 + 200,
        achieved_session_id="a",
        achieved_lap_id=a[2].id,
        achieved_value=3,
    )
    p = build(inp(s, a, history((s, a)), goals=[run, lap_goal]), {a[1].id: 2, a[2].id: 3}).progress
    assert p is not None and p.source == "goal_reached" and p.goal_id == 1  # the first one reached
    assert p.text == "A lap under 1:10.000 (1:09.981 on lap 2). And 1 more: 3 clean laps in a row."
    assert p.text_simple == "You did it: beat 1:10.000 and 3 clean laps in a row."
    assert p.values["goals"] == 2


def test_progress_pb_streak_goal_progress_gap_first_and_week() -> None:
    times = [72_000, 71_500, 71_000]
    pairs = [(sess(f"s{i}", T0 + i * 60), [lap(1, ms, sid=f"s{i}")]) for i, ms in enumerate(times)]
    h = history(*pairs)
    s2, l2 = pairs[2]
    p = build(inp(s2, l2, h)).progress
    assert p is not None and p.source == "pb_streak"
    assert p.text == "New best at Austria in the Haas in 2 sessions in a row."
    assert p.fact_key == "pb_streak:f1_25:f1:17:f1:team:7:2"  # the badge's key; Went well's "pb:<lap>" is another
    # a goal this session moved closer (no PB streak: s1's 71.5 is the first gain)
    s1, l1 = pairs[1]
    g = goal("lap_time", 70_000, scope=AUSTRIA_HAAS, after=pairs[0][1][0].id)
    p1 = build(inp(s1, l1, h, goals=[g])).progress
    assert p1 is not None and p1.source == "goal_progress" and p1.goal_id == 1
    assert p1.text == "A lap under 1:10.000: 1.500 s to go (best since you set it 1:11.500)."
    assert p1.text_simple == "About 1.5 s to go to your goal."
    # the gap to the best here
    slow = [lap(1, 71_540, sid="slow")]
    ss = sess("slow", T0 + 180)
    h2 = history(*pairs, (ss, slow))
    p2 = build(inp(ss, slow, h2)).progress
    assert p2 is not None and p2.source == "gap_to_pb"
    assert p2.text == "Your best in this session was 0.540 s off your best here (1:11.000, Sat 10 Oct)."
    close = [lap(1, 71_050, sid="close")]
    sc = sess("close", T0 + 240)
    p3 = build(inp(sc, close, history(*pairs, (sc, close)))).progress
    assert p3 is not None and "within 0.1 s of your best here" in p3.text
    # first clean laps at a track
    suz = [lap(1, 96_360, sid="z")]
    sz = sess("z", T0 + 300, track_id="f1:13", track_name="Suzuka", car_name="F1 Generic", car_id="f1:team:41")
    hz = history(*pairs, (sz, suz))
    bests = R._scope_bests(hz, sz)
    p4 = R.progress_thing(inp(sz, suz, hz), bests, {})
    assert p4 is not None and p4.source == "first_session" and p4.fact_key == "first_clean:f1_25:f1:13:f1:team:41"
    assert p4.text == "Your first clean laps at Suzuka in the F1 Generic: 1:36.360 is the time to beat next time."
    #    ... unless Went well says it already (the recap never says one fact twice)
    rz = build(inp(sz, suz, hz))
    assert rz.went_well is not None and rz.went_well.fact_key == p4.fact_key
    assert rz.progress is not None and rz.progress.source == "sessions_week"
    # otherwise the sessions this week
    none = [lap(1, 80_000, sid="n", flags=["invalid"])]
    sn = sess("n", T0 + 360)
    p5 = build(inp(sn, none, history(*pairs, (sn, none)))).progress
    assert p5 is not None and p5.source == "sessions_week"
    assert p5.text == "4 sessions with a timed lap this week, 4 laps so far."


def test_progress_is_as_at_the_session() -> None:
    a = [lap(1, 72_000, sid="a")]
    b = [lap(1, 71_500, sid="b")]
    c = [lap(1, 71_000, sid="c")]
    pairs = [(sess("a", T0), a), (sess("b", T0 + 60), b)]
    before = build(inp(pairs[1][0], b, history(*pairs))).progress
    after = build(inp(pairs[1][0], b, history(*pairs, (sess("c", T0 + 120), c)))).progress
    assert before is not None and after is not None and before.text == after.text


@pytest.mark.parametrize(
    ("why", "kw"),
    [
        (R.WHY_SYNTHETIC, {"synthetic": True}),
        (R.WHY_REPLAY, {"source": "replay:x.pwcap"}),
        (R.WHY_NO_OWNER, {"driver_id": None}),
    ],
)
def test_sessions_that_do_not_count(why: str, kw: dict[str, Any]) -> None:
    s = sess("x", **kw)
    ls = laps("x", [71_000, 71_100, 71_200])
    rec = build(inp(s, ls, None, counts=False, why=why))
    assert rec.progress is None and rec.why["progress"] == why
    assert rec.went_well is not None and rec.went_well.source == "clean_streak"  # still computed
    assert rec.work_on is None or rec.work_on.source != "pb"


def test_empty_session() -> None:
    """No timed lap: nothing to say, and not one of the week's sessions (as the digest, badges and streaks count)."""
    rec = build(inp(sess("x"), [], history((sess("x"), [])), counts=True))
    assert (rec.went_well, rec.work_on, rec.progress) == (None, None, None)
    assert rec.why == {"went_well": R.WHY_NO_LAPS, "work_on": R.WHY_NO_LAPS, "progress": R.WHY_NO_LAPS}
    untimed = [lap(1, None, sid="u", flags=["incomplete"])]
    rec2 = build(inp(sess("u"), untimed, history((sess("u"), untimed)), counts=True))
    assert rec2.progress is None and rec2.work_on is None


def test_the_week_counts_timed_sessions_only() -> None:
    a = laps("a", [71_000, 71_100])
    empty = sess("e", T0 + 60)
    b = [lap(1, 80_000, sid="b", flags=["invalid"])]
    sb = sess("b", T0 + 120)
    p = build(inp(sb, b, history((sess("a"), a), (empty, []), (sb, b)))).progress
    assert p is not None and p.source == "sessions_week"
    assert p.text == "2 sessions with a timed lap this week, 3 laps so far."  # the count says its rule (5.7)
    assert DAY > 0


def test_a_beginner_hears_what_they_did_rather_than_nothing() -> None:
    f = [lap(1, 72_000, sid="f", flags=["invalid"]), lap(2, 73_000, sid="f", flags=["invalid"])]
    sf = sess("f", T0, track_name="Suzuka")
    rec = build(inp(sf, f, history((sf, f)), skill="beginner"))
    assert rec.went_well is not None and rec.went_well.source == "drove"
    assert rec.went_well.text_simple == "You drove 2 laps at Suzuka."
    assert build(inp(sf, f, history((sf, f)), skill="advanced")).went_well is None


def test_an_older_session_names_its_own_week_not_this_week() -> None:
    """UX review: a 10 Oct session read on 12 Oct said "4 sessions with a timed lap this week". Read in a later week
    it names the week it was driven in, counted up to it; the simple wording keeps the counting rule too."""
    a = laps("a", [71_000, 71_100])
    sa = sess("a", T0)
    hist = history((sa, a))
    same = R.progress_thing(R.RecapInput(**{**vars_of(inp(sa, a, hist)), "now_unix": T0 + 3600}), [], {})
    assert same is not None and same.text == "1 session with a timed lap this week, 2 laps so far."
    assert same.text_simple == "You set lap times in 1 session this week."
    later = R.progress_thing(R.RecapInput(**{**vars_of(inp(sa, a, hist)), "now_unix": T0 + 9 * DAY}), [], {})
    week = rules.week_of(T0)
    when = f"the week of {week:%a} {week.day} {week:%b}"
    assert later is not None and later.text == f"1 session with a timed lap in {when}, 2 laps by then."
    assert later.text_simple == f"You set lap times in 1 session in {when}."
    assert later.values["this_week"] is False


def vars_of(i: R.RecapInput) -> dict[str, Any]:
    return {f: getattr(i, f) for f in R.RecapInput.__dataclass_fields__}


def test_the_dashboard_mirror_keeps_the_same_constants() -> None:
    """web-react/src/lib/review/coaching.ts repeats the report's and the radio's habit rules for the dashboard: its
    copies of the constants must be these (a change here without the mirror would make screen and report disagree)."""
    ts = (Path(__file__).resolve().parents[2] / "web-react" / "src" / "lib" / "review" / "coaching.ts").read_text()

    def const(name: str) -> float:
        m = re.search(rf"export const {name} = ([0-9.]+);", ts)
        assert m is not None, name
        return float(m.group(1))

    assert (const("MIN_REPEAT"), const("RECENT_LAPS")) == (R.MIN_REPEAT, R.RECENT_LAPS)
    assert const("BIG_ONE_OFF_S") == coaching.BIG_ONE_OFF_S
    assert const("BIG_ONE_OFF_CONFIDENCE") == coaching.BIG_ONE_OFF_CONFIDENCE
    assert const("HABIT_RATIO") == coaching.HABIT_RATIO
    later = re.search(r"LATER_BRAKING_FIXES[^=]*= new Set\(\[([^\]]*)\]\)", ts)
    assert later is not None and set(re.findall(r'"(\w+)"', later.group(1))) == set(coaching.LATER_BRAKING_FIXES)
    assert R.LATER_BRAKING_FIXES is coaching.LATER_BRAKING_FIXES  # one definition
