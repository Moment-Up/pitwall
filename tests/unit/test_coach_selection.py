"""D6: one coaching selection for the Drive screen and the radio, and the ``text_simple`` / ``short`` wordings.

docs/ui/design-spec.md P7 and section 13: the coach card shows the point the radio picked, both chosen under the
seated driver's limits; every observation is also written in plain words and in at most 48 characters, from
the same facts, and never tells the driver to brake later.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from pitwall.analysis.coaching import SHORT_MAX_CHARS, Observation, observations_for_comparison
from pitwall.analysis.compare import Compatibility, CornerDelta, CornerMetrics, LapComparison
from pitwall.analysis.track_identity import CornerText
from pitwall.coach.selection import (
    COACH_FIELDS,
    CoachSelection,
    coach_block,
    corner_points,
    pick_points,
    screen_limits,
)
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.drivers import coaching_limits
from pitwall.storage.db import Database, DbWriter
from pitwall.voice.proactive import lap_messages
from pitwall.voice.types import MessageKind
from tests.conftest import DecodedSession

LATER_BRAKING_ADVICE = re.compile(r"\b(brake|braking) (a bit |a little |even )?later\b(?! (than|but|did))", re.I)


# ---------------------------------------------------------------------------------------------- wordings
def _cd(corner: str = "T1", **kw: float | None) -> CornerDelta:
    base: dict[str, float | None] = dict(
        time_delta_s=0.0,
        brake_point_delta_m=0.0,
        brake_release_delta_m=0.0,
        min_speed_delta_kph=0.0,
        min_speed_pos_delta_m=0.0,
        entry_speed_delta_kph=0.0,
        exit_speed_delta_kph=0.0,
        throttle_pickup_delta_m=0.0,
        throttle_full_delta_m=0.0,
        coast_delta_m=0.0,
        release_time_delta_s=0.0,
    )
    base.update(kw)
    m = CornerMetrics(corner=corner, segment_time_s=10.0, min_speed_kph=100.0)
    return CornerDelta(corner=corner, ref=m, cmp=m, **base)  # type: ignore[arg-type]


def _comp(*cds: CornerDelta) -> LapComparison:
    return LapComparison(
        ref_lap_number=1,
        cmp_lap_number=2,
        total_delta_s=0.1,
        delta_d=[],
        delta_s=[],
        corners=list(cds),
        compatibility=Compatibility(ok=True),
    )


EVERY_RULE = [
    ("brake_early", _cd("T1", brake_point_delta_m=-12, time_delta_s=0.11)),
    ("brake_late_overdrive", _cd("T2", brake_point_delta_m=12, exit_speed_delta_kph=-6, time_delta_s=0.1)),
    ("low_min_speed", _cd("T3", min_speed_delta_kph=-8, time_delta_s=0.08)),
    ("overspeed_apex", _cd("T4", min_speed_delta_kph=6, exit_speed_delta_kph=-5, time_delta_s=0.07)),
    ("late_throttle", _cd("T5", throttle_full_delta_m=25, time_delta_s=0.06)),
    ("coasting", _cd("T6", coast_delta_m=30, time_delta_s=0.2)),
    ("exit_gain", _cd("T7", exit_speed_delta_kph=6, time_delta_s=-0.1)),
    ("incident", _cd("T8", time_delta_s=3.4)),
]


def _all_wordings(corner_text: dict[str, CornerText] | None = None) -> dict[str, Observation]:
    obs = observations_for_comparison(_comp(*(cd for _, cd in EVERY_RULE)), corner_text=corner_text)
    by_kind = {o.kind: o for o in obs}
    assert set(by_kind) == {k for k, _ in EVERY_RULE}
    return by_kind


def test_every_rule_has_a_simple_and_a_short_wording() -> None:
    by_kind = _all_wordings()
    assert by_kind["brake_early"].short == "T1: braked 12 m earlier"
    assert by_kind["brake_early"].text_simple == "T1: you braked about 12 m earlier than on your reference lap."
    assert by_kind["low_min_speed"].short == "T3: 8 km/h slower mid-corner"
    assert by_kind["exit_gain"].short == "T7: good exit, 6 km/h faster"
    assert by_kind["incident"].short == "T8: incident, no advice this lap"
    for o in by_kind.values():
        assert o.text_simple and o.short
        assert len(o.short) <= SHORT_MAX_CHARS
        # one idea: no reference lap number, no secondary time loss, no habit statistics
        assert "(lap" not in o.text_simple and "losing" not in o.text_simple and "of the last" not in o.text_simple
        d = o.to_dict()
        assert d["text_simple"] == o.text_simple and d["short"] == o.short


def test_no_wording_ever_tells_the_driver_to_brake_later() -> None:
    for o in _all_wordings().values():
        for text in (o.text, o.text_simple, o.short):
            assert text is not None and not LATER_BRAKING_ADVICE.search(text), text
    # later braking that paid off is only ever praise for the exit, never a corrective point
    paid_off = observations_for_comparison(_comp(_cd(brake_point_delta_m=14, time_delta_s=-0.09)))
    assert all(o.positive for o in paid_off)


def test_official_names_and_the_short_limit() -> None:
    long_name = "Turn 10 (Remus Kurve Hairpin With A Very Long Sponsor Name)"
    texts = {
        "T1": CornerText(short="T15", long="Turn 15 (Stowe)", voice="Turn 15, Stowe"),
        "T2": CornerText(short="Remus Kurve Hairpin With A Very Long Name", long=long_name, voice="Turn 10"),
    }
    by_kind = _all_wordings(texts)
    assert by_kind["brake_early"].short == "T15: braked 12 m earlier"
    assert (
        by_kind["brake_early"].text_simple
        == "Turn 15 (Stowe): you braked about 12 m earlier than on your reference lap."
    )
    overdrive = by_kind["brake_late_overdrive"]
    assert overdrive.short == "braked later, 6 km/h slower out"  # the name would not fit: the screen shows it anyway
    assert overdrive.text_simple is not None and overdrive.text_simple.startswith(long_name)


def test_wordings_on_the_synthetic_demo_fit_and_never_advise_later_braking(
    demo_session: DecodedSession, tmp_path: Path
) -> None:
    """SYNTHETIC: every observation the real pipeline produces on the coaching demo carries all three wordings."""
    from tests.unit.test_drivers import lap_ctx, new_session

    seen = 0
    with _store(tmp_path / "w.sqlite3") as (db, writer):
        proc = LapProcessor(db, writer)
        new_session(writer, None, demo_session.info, "d")
        for lap in demo_session.laps:
            for o in proc.process(LapJob("d", lap, lap_ctx(demo_session.info)))["observations"]:
                seen += 1
                assert o["short"] and len(o["short"]) <= SHORT_MAX_CHARS
                assert o["text_simple"] and o["text_simple"].endswith(".")
                for t in (o["text"], o["text_simple"], o["short"]):
                    assert not LATER_BRAKING_ADVICE.search(t), t
    assert seen >= 3


@contextmanager
def _store(path: Path) -> Iterator[tuple[Database, DbWriter]]:
    db = Database(path)
    writer = DbWriter(db)
    try:
        yield db, writer
    finally:
        writer.close()


# ---------------------------------------------------------------------------------------------- selection
def ob(
    oid: str,
    kind: str,
    corner: str,
    conf: float,
    impact: float,
    prio: float,
    positive: bool = False,
    lap: int = 5,
    habit: bool = True,
) -> dict[str, Any]:
    """A coaching point. Corrective points are habits by default (seen on 4 of the last 5 laps): the radio says
    habits (as tracker events, or as they are without a tracker) and big one-offs, never small one-offs."""
    habitual = habit and not positive and kind != "incident"
    return {
        "id": oid,
        "kind": kind,
        "corner": corner,
        "corner_voice": None,
        "lap_number": lap,
        "ref_lap_number": 2,
        "metric": "m",
        "value": -12.0,
        "unit": "m",
        "confidence": conf,
        "impact_s": impact,
        "priority": prio,
        "positive": positive,
        "text": f"{corner}: {kind} text.",
        "text_simple": f"{corner}: {kind} simple.",
        "short": f"{corner}: {kind}",
        "evidence": {"time_delta_s": impact, "exit_speed_delta_kph": -4.0, "ref": {"x": 1}, "lap": {"x": 2}},
        "consistency": "4 of the last 5 laps" if habitual else None,
        "consistency_ratio": 0.8 if habitual else None,
    }


OBS = [
    ob("a", "brake_early", "T1", 0.9, 0.20, 0.18),
    ob("b", "coasting", "T2", 0.95, 0.30, 0.28),  # beginners: not a fundamentals rule
    ob("c", "low_min_speed", "T3", 0.7, 0.25, 0.30),  # below the beginner confidence floor
    ob("d", "late_throttle", "T4", 0.9, 0.12, 0.10),
    ob("e", "exit_gain", "T5", 0.9, -0.15, 0.07, positive=True),
    ob("f", "incident", "T6", 0.9, 3.0, 2.7),  # never a coaching point
    ob("g", "late_throttle", "T1", 0.9, 0.20, 0.05),  # second point at T1
]
LAP = {"lap_id": 105, "lap_number": 5}


def ids(points: list[Any]) -> list[str]:
    return [str(p["id"]) for p in points]


def lap_of(n: int, obs: list[dict[str, Any]] = OBS) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Lap ``n`` with the same points (the habit tracker needs three compared laps before it announces a habit)."""
    return {"lap_id": 100 + n, "lap_number": n}, [{**o, "lap_number": n} for o in obs]


def test_pick_follows_the_drivers_limits_and_by_corner_shows_every_eligible_corner() -> None:
    beginner = coaching_limits("beginner")
    assert ids(pick_points(OBS, beginner, 5)) == ["a"]
    block = coach_block(LAP, OBS, beginner)
    assert ids(block["picked"]) == ["a"] and block["skill_level"] == "beginner" and block["simple_wording"]
    assert not block["radio_quiet"] and block["lap_number"] == 5 and block["lap_id"] == 105
    assert block["ref_lap_number"] == 2
    # the coach card has a point for every corner that passes the beginner's filters, picked or not
    assert {c: o["id"] for c, o in block["by_corner"].items()} == {"T1": "a", "T4": "d", "T5": "e"}
    assert block["by_corner"]["T1"]["picked"] and not block["by_corner"]["T4"]["picked"]
    advanced = coach_block(LAP, OBS, coaching_limits("advanced", "detailed"))
    assert ids(advanced["picked"]) == ["c", "b", "e"]
    assert {c: o["id"] for c, o in advanced["by_corner"].items()} == {
        "T1": "a",  # corrective, best priority at T1
        "T2": "b",
        "T3": "c",
        "T4": "d",
        "T5": "e",
    }
    assert "T6" not in advanced["by_corner"]  # incidents are not coaching points


def test_block_copies_are_slim() -> None:
    block = coach_block(LAP, OBS, coaching_limits("advanced"))
    (p,) = block["picked"]
    # habits (spec section 3): every point also says whether it is a habit and whether it is a one-off
    assert set(p) == {*COACH_FIELDS, "evidence", "picked", "habit", "one_off"}
    assert p["evidence"] == {"time_delta_s": 0.25, "exit_speed_delta_kph": -4.0}  # per-lap metric dicts dropped
    assert p["habit"] is None and p["one_off"] is False  # no tracker here; a habit is never a one-off
    assert block["habits"] == [] and block["focus"] == []


def test_quiet_drivers_still_see_their_points_but_the_radio_says_none() -> None:
    quiet = coaching_limits("beginner", "quiet")
    block = coach_block(LAP, OBS, quiet)
    assert block["radio_quiet"] and ids(block["picked"]) == ["a"]
    assert screen_limits(quiet).max_per_lap == 1
    msgs = lap_messages(LAP | {"lap_time_ms": 65_000}, OBS, None, None, "normal", 0.0, limits=quiet, coach=block)
    assert [m.kind for m in msgs] == [MessageKind.LAP_SUMMARY]


def test_repeat_grace_limits_the_radio_not_the_screen() -> None:
    # big one-offs: the radio says them as they are (a habit would be a tracker event)
    big_a = ob("a", "brake_early", "T1", 0.9, 0.40, 0.36, habit=False)
    big_d = ob("d", "late_throttle", "T4", 0.9, 0.32, 0.29, habit=False)
    sel = CoachSelection()
    sel.set_limits(2, coaching_limits("beginner"))
    first = sel.select({"lap_id": 104, "lap_number": 4}, [{**big_a, "lap_number": 4}], compared=True)
    assert ids(first["picked"]) == ["a"]
    second = sel.select(LAP, [big_a, big_d], compared=True)
    assert ids(second["picked"]) == ["d"]  # T1 was coached last lap: a lap's grace on the radio
    assert second["by_corner"]["T1"]["id"] == "a" and not second["by_corner"]["T1"]["picked"]
    assert second["by_corner"]["T1"]["one_off"] and second["by_corner"]["T1"]["habit"] is None


def test_selection_keeps_the_last_compared_lap_and_resets() -> None:
    sel = CoachSelection()
    sel.set_limits(1, coaching_limits("advanced"))
    block = sel.select(LAP, OBS, compared=True)
    assert sel.current is block
    out_lap = sel.select({"lap_id": 106, "lap_number": 6}, [], compared=False)
    assert out_lap["picked"] == [] and sel.current is block  # the card keeps lap 5's point, with its lap number
    sel.set_limits(1, coaching_limits("intermediate"))  # a profile edit keeps the card
    assert sel.current is block
    sel.set_limits(3, coaching_limits("beginner"))  # someone else in the seat: not their coaching
    assert sel.current is None
    sel.select(LAP, OBS, compared=True)
    sel.reset()
    assert sel.current is None


def test_corner_points_prefer_the_picked_point() -> None:
    picked = [OBS[6]]  # the radio chose T1's throttle point over its braking point
    assert corner_points(OBS, coaching_limits("advanced"), 5, picked)["T1"]["id"] == "g"


# ---------------------------------------------------------------------------------------------- one message, two channels
def test_live_state_sends_the_pick_with_the_lap_and_shows_it() -> None:
    live = LiveState()
    notes: list[tuple[str, dict[str, Any]]] = []
    live.subscribe(lambda k, p: notes.append((k, p)))
    live.on_driver(7, coaching_limits("beginner"))
    live.reset_session("s1", "test", False)
    assert live.snapshot()["coach"] is None
    comp = {"compatibility": {"ok": True, "blocking": [], "warnings": []}}
    for n in (3, 4):  # the same habits on the two laps before
        lap, obs = lap_of(n)
        live.on_lap_result(lap | {"lap_time_ms": 65_000}, obs, comp)
    live.on_lap_result({"lap_id": 105, "lap_number": 5, "lap_time_ms": 65_000}, OBS, comp)
    assert [k for k, _ in notes] == ["lap"] * 3
    payload = notes[-1][1]
    assert payload["coach"] == live.snapshot()["coach"]
    # the beginner's one eligible habit is announced as their focus (spec section 3: tracker events on the radio)
    (point,) = payload["coach"]["picked"]
    assert (point["corner"], point["kind"], point["habit_event"]) == ("T1", "brake_early", "announce")
    assert point["habit"] == {"status": "focus", "laps_seen": 3, "laps": 3}
    assert [(f["corner"], f["kind"]) for f in payload["coach"]["focus"]] == [("T1", "brake_early")]
    # an uncompared lap (no reference, flashback) sends an empty pick and leaves the card alone
    live.on_lap_result({"lap_id": 106, "lap_number": 6, "lap_time_ms": 66_000}, [], None)
    assert notes[-1][1]["coach"]["picked"] == [] and live.snapshot()["coach"]["lap_number"] == 5
    live.reset_session("s2", "test", False)
    assert live.snapshot()["coach"] is None


@pytest.mark.parametrize("skill", ["beginner", "intermediate", "advanced"])
@pytest.mark.parametrize("intensity", ["normal", "detailed"])
def test_the_radio_says_exactly_the_shared_pick(skill: str, intensity: str) -> None:
    limits = coaching_limits(skill, intensity)
    block = coach_block(LAP, OBS, limits)
    lap = LAP | {"lap_time_ms": 65_000}
    msgs = lap_messages(lap, OBS, None, None, intensity, 0.0, limits=limits, last_coached={}, coach=block)
    spoken = [m.meta["observation_id"] for m in msgs if m.kind is MessageKind.COACHING]
    assert spoken == ids(block["picked"])
    for m in msgs:
        if m.kind is MessageKind.COACHING:
            assert block["by_corner"][str(m.corner)]["id"] == m.meta["observation_id"]  # the card for that corner
    # without the block the radio picks the same points with the same shared function
    alone = lap_messages(lap, OBS, None, None, intensity, 0.0, limits=limits, last_coached={})
    assert [m.meta["observation_id"] for m in alone if m.kind is MessageKind.COACHING] == spoken


def test_a_block_for_another_lap_is_ignored() -> None:
    stale = coach_block({"lap_id": 99, "lap_number": 4}, [], coaching_limits("advanced"))
    msgs = lap_messages(LAP | {"lap_time_ms": 65_000}, OBS, None, None, "normal", 0.0, coach=stale)
    assert [m.meta.get("observation_id") for m in msgs if m.kind is MessageKind.COACHING] == ["c"]


def test_radio_and_screen_agree_on_the_synthetic_demo(demo_session: DecodedSession, tmp_path: Path) -> None:
    """SYNTHETIC end to end: lap processor -> live state -> radio. Every point the radio says on a lap equals the
    coach card for that corner (design spec 14.5, acceptance 4), for a beginner and an advanced driver."""
    from tests.unit.test_drivers import lap_ctx, new_session

    for skill in ("beginner", "advanced"):
        limits = coaching_limits(skill, "detailed")
        live = LiveState()
        notes: list[dict[str, Any]] = []
        live.subscribe(lambda k, p, notes=notes: notes.append(p) if k == "lap" else None)
        live.on_driver(1, limits)
        spoken_total = 0
        with _store(tmp_path / f"{skill}.sqlite3") as (db, writer):
            proc = LapProcessor(db, writer, live)
            new_session(writer, None, demo_session.info, "d")
            live.reset_session("d", "t", True)
            last_coached: dict[str, int] = {}
            for lap in demo_session.laps:
                proc.process(LapJob("d", lap, lap_ctx(demo_session.info)))
                payload = notes[-1]
                msgs = lap_messages(
                    payload["lap"],
                    payload["observations"],
                    None,
                    live.reference,
                    "detailed",
                    0.0,
                    limits=limits,
                    last_coached=last_coached,
                    coach=payload["coach"],
                )
                card = live.snapshot()["coach"]
                for m in msgs:
                    if m.kind is MessageKind.COACHING:
                        spoken_total += 1
                        assert card is not None and card["by_corner"][str(m.corner)]["id"] == m.meta["observation_id"]
        assert spoken_total >= 2, skill


# ---------------------------------------------------------------------------------------------- the radio's intensity
def events(block: dict[str, Any]) -> list[tuple[str, str | None]]:
    return [(str(p["corner"]), p.get("habit_event")) for p in block["picked"]]


def test_with_nobody_seated_the_radio_intensity_sets_the_budget() -> None:
    """The radio speaks ``coaching_limits("advanced", intensity)`` when nobody is in the seat, so the shared pick
    must use the radio's intensity too: Detailed is two corrective points and a positive one, on screen as on air.
    With habits (spec section 3) the intensity also sets the focus slots: one at normal, two at detailed, none at
    quiet (the screen still shows the habits)."""
    sel = CoachSelection()
    sel.set_limits(None, None)
    assert sel.radio_intensity == "normal"
    assert [events(sel.select(*lap_of(n), compared=True)) for n in (3, 4)] == [[], []]  # small one-offs so far
    assert events(sel.select(*lap_of(5), compared=True)) == [("T2", "announce")]  # the biggest habit, one slot
    sel.set_radio_intensity("detailed")
    block = sel.select(*lap_of(6), compared=True)
    assert events(block) == [("T3", "announce"), ("T5", None)] and not block["radio_quiet"]  # a 2nd slot + praise
    assert [f["corner"] for f in block["focus"]] == ["T2", "T3"]
    assert sel.current is block  # the card and the radio change together
    sel.set_radio_intensity("quiet")
    block = sel.select(*lap_of(7), compared=True)
    assert block["radio_quiet"] and events(block) == []  # no new focus while quiet
    assert [f["corner"] for f in block["focus"]] == ["T2", "T3"]  # the screen still shows what is worked on
    sel.set_radio_intensity("loud")  # not an intensity: ignored
    assert sel.radio_intensity == "quiet"
    # a seated driver's profile sets the budget (as on the radio); a quiet radio still says none of it
    sel.set_limits(2, coaching_limits("beginner", "normal"))  # another driver: their own habits, from scratch
    sel.set_radio_intensity("detailed")
    assert sel.select(*lap_of(8), compared=True)["focus"] == []
    sel.select(*lap_of(9), compared=True)
    block = sel.select(*lap_of(10), compared=True)
    assert events(block) == [("T1", "announce")] and [f["corner"] for f in block["focus"]] == ["T1"]
    sel.set_radio_intensity("quiet")
    block = sel.select(*lap_of(11), compared=True)
    assert block["radio_quiet"] and events(block) == [("T5", None)]  # the screen still shows the praise


# A beginner's only eligible point is the lap's sixth observation: the lap notification's ``observations`` are the
# top five (for the dashboard), so a radio picking from them would say nothing while the card shows the sixth.
SIXTH = [ob(f"x{i}", "coasting", f"T{i}", 0.95, 0.30, 0.50 - i / 100) for i in range(1, 6)] + [
    ob("y", "brake_early", "T9", 0.9, 0.35, 0.10, habit=False)  # a big one-off
]


async def _radio(live: LiveState) -> tuple[Any, Any, list[Any]]:
    from pitwall.ai.engineer import RaceEngineer
    from pitwall.voice.hub import RadioClient, RadioHub
    from tests.unit.test_voice_hub import FakeScheduler, FakeStt, FakeTts, sheet

    sched = FakeScheduler()
    hub = RadioHub(live, RaceEngineer(None), FakeStt(), FakeTts(), sched, sheet, lambda s: s, lap_messages=lap_messages)
    hub.start()

    async def send(item: Any) -> None:
        return None

    client = RadioClient(send=send)
    await hub.connect(client)
    return hub, client, sched.queue


def _coaching(queue: list[Any]) -> list[str]:
    return [str(m.meta["observation_id"]) for m in queue if m.kind is MessageKind.COACHING]


async def test_the_hub_says_the_shared_pick_from_all_of_the_laps_observations() -> None:
    from pitwall.drivers import Driver, DriverPreferences

    live = LiveState()
    notes: list[dict[str, Any]] = []
    live.subscribe(lambda k, p: notes.append(p) if k == "lap" else None)
    hub, _client, queue = await _radio(live)
    beginner = Driver(1, "Sam", 0.0, DriverPreferences(skill_level="beginner"))
    live.on_driver(1, beginner.coaching)
    hub.apply_driver(beginner)
    live.reset_session("s1", "test", False)
    comp = {"compatibility": {"ok": True, "blocking": [], "warnings": []}}
    live.on_lap_result(LAP | {"lap_time_ms": 65_000}, SIXTH, comp)
    payload = notes[-1]
    assert [o["id"] for o in payload["observations"]] == ["x1", "x2", "x3", "x4", "x5"]  # no eligible point
    hub._enqueue_lap(payload)
    assert _coaching(queue) == ["y"] == ids(live.snapshot()["coach"]["picked"])  # the card's point, on air
    await hub.stop()


async def test_the_hubs_intensity_reaches_the_shared_pick() -> None:
    live = LiveState()
    notes: list[dict[str, Any]] = []
    live.subscribe(lambda k, p: notes.append(p) if k == "lap" else None)
    hub, client, queue = await _radio(live)
    await hub.on_text(client, {"type": "settings", "intensity": "detailed"})  # a radio device, nobody seated
    assert hub.intensity == "detailed" == live.coach.radio_intensity
    live.reset_session("s1", "test", False)
    comp = {"compatibility": {"ok": True, "blocking": [], "warnings": []}}
    for n in (3, 4):  # the same habits on the two laps before
        lap, obs = lap_of(n)
        live.on_lap_result(lap | {"lap_time_ms": 65_000}, obs, comp)
    live.on_lap_result(LAP | {"lap_time_ms": 65_000}, OBS, comp)
    hub._enqueue_lap(notes[-1])
    # detailed: two focus slots, so the two biggest habits are announced, then the praise
    announced = ["L5:T2:coasting:announce", "L5:T3:low_min_speed:announce", "e"]
    assert _coaching(queue) == announced == ids(live.snapshot()["coach"]["picked"])
    # a seated driver's own intensity reaches the selection too
    from pitwall.drivers import Driver, DriverPreferences

    hub.apply_driver(Driver(1, "Sam", 0.0, DriverPreferences(skill_level="advanced", coaching_intensity="quiet")))
    assert live.coach.radio_intensity == "quiet"
    await hub.stop()
