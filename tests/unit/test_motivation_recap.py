"""Today's 3 things (pure): each step of each order of choices, verbatim observation text, beginner wording and kinds,
special sessions, history as at the session, and never "brake later"."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import pytest

from pitwall.drivers import coaching_limits
from pitwall.motivation import recap as R
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
        "Turn 6: minimum speed is 9 km/h lower than your reference (164 vs 173 km/h), losing 0.23 s through the corner."
    )
    simple = "Turn 6: you were 9 km/h slower at the slowest point of the corner."
    o = {ls[1].id: [obs(2, "low_min_speed", "Turn 6", text=text, simple=simple)]}
    rec = build(inp(s, ls, history((s, ls)), observations=o, compared=1))
    assert rec.work_on is not None and rec.work_on.text == text and rec.work_on.text_simple == simple
    assert rec.work_on.evidence == "Seen on 1 of 1 lap compared with your reference"
    assert rec.work_on.observation_key == "Turn 6:low_min_speed" and rec.work_on.lap_id == ls[1].id
    # a verbatim observation may describe braking; it is the coach's own text (which never says "brake later")
    late = {ls[1].id: [obs(2, "brake_late_overdrive", "Turn 1", text="Turn 1: braking 9 m later but slower out.")]}
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
    neg = {ls[1].id: [obs(2, "low_min_speed", "Turn 6")]}
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
    assert w.text_simple == "2 timed laps did not count this time."
    one = [lap(1, 71_000, sid="g"), lap(2, 70_000, sid="g", valid=False), lap(3, 71_000, sid="g")]
    w1 = build(inp(sess("g"), one, None, counts=False)).work_on
    assert w1 is not None and w1.text == "Lap 2 did not count: the game invalidated it."
    assert w1.text_simple == "1 timed lap did not count this time."
    incomplete = [lap(1, None, sid="c", flags=["incomplete"]), lap(2, 78_000, sid="c", flags=["incomplete"])]
    w2 = build(inp(sess("c"), incomplete, None, counts=False)).work_on
    assert w2 is not None and w2.source == "no_clean_lap"
    single = [lap(1, 90_000, sid="d", flags=["standing_start"]), lap(2, 78_000, sid="d")]
    w3 = build(inp(sess("d"), single, None, counts=False)).work_on
    assert w3 is not None and w3.source == "single_clean_lap"
    rec = build(inp(sess("e"), laps("e", [71_000, 71_100]), None, counts=False))
    assert rec.work_on is None and rec.why["work_on"] == R.WHY_NOTHING_WORK


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
