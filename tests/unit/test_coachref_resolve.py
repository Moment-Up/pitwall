"""coachref: reference resolution (``core.coachref.resolve_reference``, ``reference_options``, ``CoachRef.resolve``)
on a temporary database with several drivers. Laps are stored rows (no analysis needed to choose a reference)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.analysis.laps import LapTrace
from pitwall.core import coachref as cr
from pitwall.core.lap_processor import LapProcessor
from pitwall.model.telemetry import SessionInfo
from pitwall.storage import repo
from tests.coachref_support import Env, copy_lap, lap_ctx, make_env, new_session, session_info
from tests.conftest import DecodedSession


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = make_env(tmp_path)
    yield e
    e.close()


def add(
    env: Env,
    driver: int | None,
    sid: str,
    info: SessionInfo,
    base: LapTrace,
    times: list[int],
    *,
    source: str = "udp:20777",
    synthetic: bool = False,
    meta: dict[str, Any] | None = None,
) -> list[int]:
    new_session(env.writer, driver, info, sid, source=source, synthetic=synthetic)
    ids = []
    for n, ms in enumerate(times, start=1):
        lap = copy_lap(base, ms, n)
        lap.meta = {**lap.meta, **(meta or {})}
        ids.append(env.writer.call(lambda c, lap=lap: repo.insert_lap(c, sid, lap, None)))
    return ids


def ctx_of(info: SessionInfo, **extra: Any) -> dict[str, Any]:
    return {**lap_ctx(info), "formula": info.formula, **extra}


def resolve(env: Env, owner: int | None, ctx: dict[str, Any], exclude: int | None = None) -> cr.ResolvedReference:
    with env.db.read() as c:
        return cr.resolve_reference(c, owner, ctx, exclude)


def choose(env: Env, driver: int, kind: str, **kw: Any) -> None:
    def job(c: sqlite3.Connection) -> None:
        repo.set_reference_choice(c, driver, kind, **kw)

    env.writer.call(job)


@pytest.fixture
def family(env: Env, clean_session: DecodedSession) -> dict[str, Any]:
    info, base = clean_session.info, clean_session.laps[0]
    ann = env.drivers.default_id
    sam = env.drivers.create("Sam").id
    jo = env.drivers.create("Jo").id
    a = add(env, ann, "s-ann", info, base, [70_000, 69_000])
    s = add(env, sam, "s-sam", info, base, [66_000, 65_000])
    j = add(env, jo, "s-jo", info, base, [67_000])
    return {"info": info, "base": base, "ann": ann, "sam": sam, "jo": jo, "a": a, "s": s, "j": j}


def test_no_choice_is_the_legacy_rule(env: Env, family: dict[str, Any]) -> None:
    info, ann, a = family["info"], family["ann"], family["a"]
    legacy = LapProcessor(env.db, env.writer)  # no coachref: the pre-coachref body
    game, track, car, length = info.game.value, str(info.track_id), info.car_id, float(info.track_length_m or 0)

    def both(exclude: int | None) -> tuple[int | None, int | None]:
        _, ref_id, desc = legacy._choose_reference("s-ann", game, track, car, exclude, length)
        assert desc is None
        return ref_id, resolve(env, ann, ctx_of(info), exclude).lap_id

    assert both(None) == (a[1], a[1])  # fastest own clean lap (never Sam's faster laps)
    assert both(a[1]) == (a[0], a[0])  # the lap just driven is excluded
    env.writer.call(lambda c: repo.pin_reference(c, a[0]))
    assert both(None) == (a[0], a[0])  # the active pin wins
    assert both(a[0]) == (a[1], a[1])
    res = resolve(env, ann, ctx_of(info))
    assert (res.kind, res.own, res.pinned, res.reason) == ("own_best", True, True, None)
    assert res.to_dict()["label"] == "Your pinned lap" and res.to_dict()["brake_clamped"] is False


def test_household_and_driver_best(env: Env, family: dict[str, Any]) -> None:
    info, ann, sam, jo = family["info"], family["ann"], family["sam"], family["jo"]
    choose(env, ann, "household_best")
    res = resolve(env, ann, ctx_of(info))
    assert (res.lap_id, res.kind, res.own, res.driver_name) == (family["s"][1], "household_best", False, "Sam")
    d = res.to_dict()
    assert (d["label"], d["label_to"], d["ref_name"], d["brake_clamped"]) == (
        "Family record · Sam",
        "the family record",
        "Sam",
        True,
    )
    choose(env, sam, "household_best")
    mine = resolve(env, sam, ctx_of(info))
    assert (mine.lap_id, mine.own) == (family["s"][1], True)
    assert mine.to_dict()["label"] == "Family record (you)" and mine.ref_name is None
    choose(env, ann, "driver_best", target_driver_id=jo)
    res = resolve(env, ann, ctx_of(info))
    assert (res.lap_id, res.kind, res.labels[0]) == (family["j"][0], "driver_best", "Jo's best")


CASES = [
    ("car", {"car_id": "f1:team:99"}, {}, "Sam has no lap here in this car"),
    ("layout", {"track_length_m": 9999.0}, {}, "Sam's laps here were on another layout"),
    ("wet", {"condition": "heavy_rain"}, {}, "Sam's laps here were set in the wet"),
    ("dry", {}, {"weather": "light_rain"}, "Sam's laps here were set in the dry"),
    ("braking", {"assists": {"braking": 2}}, {}, "Sam's laps here used a different braking assist"),
    ("gearbox", {"assists": {"gearbox": 2}}, {}, "Sam's laps here used a different gearbox setting"),
    ("abs", {"assists": {"abs": 1}}, {"assists": {"abs": 0}}, "Sam's laps here used a different ABS setting"),
    ("tc", {"assists": {"tc": 3}}, {"assists": {"tc": 0}}, "Sam's laps here used a different traction control setting"),
    ("formula", {"formula": "F2"}, {"formula": "F1 World"}, "Sam's laps here were in a different car class"),
]


@pytest.mark.parametrize(("case", "sam_info", "ctx_extra", "reason"), CASES, ids=[c[0] for c in CASES])
def test_incompatible_laps_fall_back_with_the_reason(
    env: Env,
    clean_session: DecodedSession,
    case: str,
    sam_info: dict[str, Any],
    ctx_extra: dict[str, Any],
    reason: str,
) -> None:
    info, base = clean_session.info, clean_session.laps[0]
    ann, sam = env.drivers.default_id, env.drivers.create("Sam").id
    if case == "layout":
        sam_info = {"track_length_m": float(info.track_length_m or 0) * 1.04}
    a = add(env, ann, "s-ann", info, base, [70_000])
    add(env, sam, "s-sam", session_info(info, **sam_info), base, [65_000])
    choose(env, ann, "driver_best", target_driver_id=sam)
    ctx = ctx_of(info)
    for k, v in ctx_extra.items():
        ctx[k] = {**ctx[k], **v} if isinstance(v, dict) else v
    res = resolve(env, ann, ctx)
    assert (res.lap_id, res.kind, res.own, res.reason) == (a[0], "own_best", True, reason)


def test_unknown_car_and_empty_family(env: Env, family: dict[str, Any]) -> None:
    info, ann = family["info"], family["ann"]
    choose(env, ann, "driver_best", target_driver_id=family["sam"])
    res = resolve(env, ann, ctx_of(info, car_id=None))
    assert res.reason == "the car is unknown, so other drivers' laps can't be matched" and res.own
    choose(env, ann, "household_best")
    res = resolve(env, ann, ctx_of(info, assists={**info.assists, "braking": 3}))
    assert res.reason == "no family lap here matches your car and settings"


def test_synthetic_and_replay_laps_are_never_candidates(env: Env, clean_session: DecodedSession) -> None:
    info, base = clean_session.info, clean_session.laps[0]
    ann, sam = env.drivers.default_id, env.drivers.create("Sam").id
    a = add(env, ann, "s-ann", info, base, [70_000])
    add(env, sam, "s-syn", info, base, [60_000], synthetic=True)
    add(env, sam, "s-rep", info, base, [61_000], source="replay:x.pwcap")
    choose(env, ann, "household_best")
    res = resolve(env, ann, ctx_of(info))
    assert (res.lap_id, res.own) == (a[0], True)  # the family record is Ann's own real lap
    choose(env, ann, "driver_best", target_driver_id=sam)
    assert resolve(env, ann, ctx_of(info)).reason == "Sam has no clean lap here yet"


def test_unowned_synthetic_and_replay_sessions_use_the_legacy_rule(env: Env, family: dict[str, Any]) -> None:
    info, base, ann, sam = family["info"], family["base"], family["ann"], family["sam"]
    choose(env, ann, "driver_best", target_driver_id=sam)
    new_session(env.writer, ann, info, "live-syn", synthetic=True)
    new_session(env.writer, ann, info, "live-rep", source="replay:y.pwcap")
    new_session(env.writer, None, info, "live-none", source="replay:z.pwcap")
    ctx = ctx_of(info)
    with env.db.read() as c:
        syn = env.svc.resolve(c, "live-syn", ann, ctx, None)
        rep = env.svc.resolve(c, "live-rep", ann, ctx, None)
        none = env.svc.resolve(c, "live-none", None, ctx, None)
        real = env.svc.resolve(c, "s-ann", ann, ctx, None)
    for res in (syn, rep):
        assert (res.lap_id, res.kind, res.own) == (family["a"][1], "own_best", True)
        assert res.reason == "replays and synthetic sessions use their own laps"
    assert (none.lap_id, none.kind, none.reason) == (family["s"][1], "own_best", None)  # pre-profile: any lap
    assert (real.lap_id, real.kind, real.own) == (family["s"][1], "driver_best", False)
    del base


def test_saved_lap_kind(env: Env, family: dict[str, Any]) -> None:
    info, ann = family["info"], family["ann"]
    lap = family["s"][0]
    choose(env, ann, "lap", game=info.game.value, track_id=str(info.track_id), lap_id=lap)
    res = resolve(env, ann, ctx_of(info))
    assert (res.lap_id, res.kind, res.own) == (lap, "lap", False)
    assert res.labels[0].startswith("Sam · lap 1 · ") and res.labels[1] == "Sam's lap"
    blocked = resolve(env, ann, ctx_of(info, assists={**info.assists, "braking": 3}))
    assert blocked.reason == "the saved lap isn't comparable now: it used a different braking assist"
    env.writer.call(lambda c: c.execute("DELETE FROM sessions WHERE id='s-sam'"))  # the lap is gone (FK: NULL)
    gone = resolve(env, ann, ctx_of(info))
    assert (gone.lap_id, gone.reason) == (family["a"][1], "the saved lap is no longer available")
    own_lap = family["a"][0]
    choose(env, ann, "lap", game=info.game.value, track_id=str(info.track_id), lap_id=own_lap)
    mine = resolve(env, ann, ctx_of(info))
    assert (mine.lap_id, mine.own, mine.labels[1]) == (own_lap, True, "your saved lap")
    assert mine.labels[0].startswith("Your lap 1 · ")


def test_deleted_target_driver(env: Env, family: dict[str, Any]) -> None:
    ann, sam, jo = family["ann"], family["sam"], family["jo"]
    choose(env, ann, "driver_best", target_driver_id=sam)
    env.drivers.delete(sam, reassign_to=jo)
    res = resolve(env, ann, ctx_of(family["info"]))
    assert (res.own, res.reason) == (True, "that driver's profile was removed")
    with env.db.read() as c:
        assert repo.reference_choice_rows(c, ann, None, None)["all_tracks"]["target_driver_id"] is None  # type: ignore[index]


def test_track_override_beats_all_tracks(env: Env, family: dict[str, Any]) -> None:
    info, ann = family["info"], family["ann"]
    choose(env, ann, "driver_best", target_driver_id=family["jo"])
    choose(env, ann, "household_best", game=info.game.value, track_id=str(info.track_id))
    with env.db.read() as c:
        assert cr.effective_choice(c, ann, info.game.value, str(info.track_id)).kind == "household_best"
        assert cr.effective_choice(c, ann, info.game.value, "f1:99").kind == "driver_best"
        assert cr.effective_choice(c, family["sam"], info.game.value, str(info.track_id)).kind == "own_best"
    assert resolve(env, ann, ctx_of(info)).lap_id == family["s"][1]


def test_options_order_availability_warnings_selected(env: Env, family: dict[str, Any]) -> None:
    info, base, ann, sam = family["info"], family["base"], family["ann"], family["sam"]
    bea = env.drivers.create("bea").id
    add(env, bea, "s-bea", session_info(info, assists={"braking": 2}), base, [64_000])
    add(env, sam, "s-sam2", info, base, [64_500], meta={"tyre_compound": "medium"})
    choose(env, ann, "driver_best", target_driver_id=sam)
    ctx = ctx_of(info, tyre_compound="soft")
    with env.db.read() as c:
        eff = cr.effective_choice(c, ann, info.game.value, str(info.track_id))
        opts = cr.reference_options(c, ann, ctx, eff)
        none = cr.reference_options(c, ann, None, eff)
    head = [(o["kind"], o["label"], o["available"], o["selected"]) for o in opts[:5]]
    assert head == [
        ("own_best", "Your best", True, False),
        ("household_best", "Family record", True, False),
        ("driver_best", "bea's best", False, False),
        ("driver_best", "Jo's best", True, False),
        ("driver_best", "Sam's best", True, True),
    ]
    assert opts[2]["reason"] == "bea's laps here used a different braking assist"
    assert opts[0]["lap"]["lap_id"] == family["a"][1]
    assert opts[4]["lap"]["lap_time_ms"] == 64_500
    assert any("tyre compound differs" in w for w in opts[4]["warnings"])
    laps = [o for o in opts if o["kind"] == "lap"]
    assert [o["lap"]["lap_time_ms"] for o in laps] == [64_500, 65_000, 66_000, 67_000, 69_000, 70_000]
    assert laps[0]["label"] == "Lap 1 · Sam" and all(o["available"] for o in laps)
    assert [o["kind"] for o in none] == ["own_best", "household_best", "driver_best", "driver_best", "driver_best"]
    assert all(o["available"] is None and o["lap"] is None for o in none)
    assert set(opts[0]) == {
        "kind",
        "target_driver_id",
        "lap_id",
        "label",
        "available",
        "reason",
        "warnings",
        "lap",
        "selected",
    }


def test_frozen_reference(env: Env, family: dict[str, Any]) -> None:
    info, ann = family["info"], family["ann"]
    desc = resolve(env, ann, ctx_of(info)).to_dict()
    choose(env, ann, "driver_best", target_driver_id=family["sam"])
    with env.db.read() as c:
        res = cr.resolve_reference(c, ann, ctx_of(info), None, frozen=cr.FrozenRef(family["a"][1], desc, {"T1": 500.0}))
    assert (res.lap_id, res.frozen, res.own, res.kind) == (family["a"][1], True, True, "own_best")
    assert res.clamp == {"T1": 500.0} and res.to_dict()["frozen"] is True
