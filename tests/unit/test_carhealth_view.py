"""The live JSON contracts (``carhealth.view``: ``CarHealthView`` v1, ``RacecraftView`` v1): keys and types, null for
unknown, NaN never leaves, the size budget, and the off shapes the API returns."""

from __future__ import annotations

import math

import orjson

from pitwall.carhealth.engine import CarHealthEngine
from pitwall.carhealth.view import off_car_health, off_racecraft, with_thresholds
from pitwall.model.telemetry import Game, SessionType
from tests.unit.carhealth_helpers import drive, frame, info, model

TOP = {"version", "session_id", "game", "synthetic", "tyres", "brakes", "engine", "slip", "fuel", "calls"}
TYRES = {
    "available",
    "model",
    "compound",
    "age_laps",
    "state",
    "armed",
    "since",
    "index_c",
    "baseline_c",
    "baseline_source",
    "wheels",
    "pressures_fixed",
    "note",
    "tier",
}
WHEEL = {"wheel", "band", "window_c", "lap_median_c", "baseline_c", "pressure_psi", "wear_pct"}
RC = {"version", "session_id", "mode", "reason", "corners_source", "ahead", "behind"}


def _f1_view() -> tuple[CarHealthEngine, dict]:  # type: ignore[type-arg]
    eng = CarHealthEngine("s1", track_model=lambda: model([0.0, 1000.0, 2500.0]))
    eng.feed(info())
    drive(eng, 0.0, 200.0, slip=(0.0, 0.0, 0.0, 0.0), lap_s=60.0)
    return eng, eng.view()


def test_car_health_view_contract() -> None:
    _, v = _f1_view()
    assert set(v) == TOP and v["version"] == 1 and v["game"] == "f1_25" and v["synthetic"] is False
    assert set(v["tyres"]) == TYRES and all(set(w) == WHEEL for w in v["tyres"]["wheels"])
    assert [w["wheel"] for w in v["tyres"]["wheels"]] == ["FL", "FR", "RL", "RR"]
    assert v["tyres"]["model"] == "carcass" and v["tyres"]["tier"] == "heuristic"
    assert set(v["brakes"]) >= {"available", "last_lap_max_c", "baseline_max_c", "word", "reason"}
    assert set(v["engine"]) >= {"available", "lap_median_c", "baseline_c", "max_c", "word", "reason"}
    assert set(v["slip"]) == {
        "available",
        "abs",
        "tc",
        "lockups_applicable",
        "last_lap",
        "current",
        "session",
        "reason",
    }
    assert v["fuel"] is None  # F1: race strategy owns fuel
    assert "thresholds" not in v  # the API adds the table; the snapshot never carries it
    full = with_thresholds(v)
    assert full["thresholds"] and {"name", "value", "unit", "heuristic", "meaning", "evidence"} == set(
        full["thresholds"][0]
    )


def test_unknown_is_null_and_nan_never_leaves() -> None:
    eng = CarHealthEngine("s2")
    eng.feed(info())
    eng.feed(frame(1.0, surf=(math.nan, 80.0, 80.0, 80.0), inner=(math.nan, 90.0, 90.0, 90.0)))
    v = eng.view()
    raw = orjson.dumps(v)
    assert b"NaN" not in raw and b"nan" not in raw.lower().replace(b"unknown", b"")
    assert v["tyres"]["baseline_c"] is None and v["brakes"]["word"] is None and v["engine"]["baseline_c"] is None
    assert v["slip"]["available"] is False  # no slip ratio yet: unknown, never zero


def test_size_budget() -> None:
    from pitwall.carhealth.calls import sample_calls

    eng, v = _f1_view()
    assert len(orjson.dumps(v)) <= 1500
    assert len(orjson.dumps(eng.racecraft_view())) <= 650
    # the worst case: the two longest calls and a lap of lock-ups in three corners
    for c in sorted(sample_calls(), key=lambda c: len(c.text) + len(c.text_simple or ""))[-2:]:
        eng.recent_calls.appendleft(c)
    assert eng.slip.last_lap is not None
    eng.slip.last_lap["corners"] = [
        {"corner": f"T{k}", "text": f"Turn {k}", "lockups": 3, "wheelspin": 2} for k in range(1, 6)
    ]
    assert len(orjson.dumps(eng.view())) <= 2200  # real F2 Bahrain worst case: 2018 bytes


def test_racecraft_view_contract_and_off_shapes() -> None:
    eng, _ = _f1_view()
    rc = eng.racecraft_view()
    assert set(rc) == RC and rc["mode"] == "race" and rc["corners_source"] == "learned"
    gt7 = CarHealthEngine("g")
    gt7.feed(info(game=Game.GT7, model=None))
    off = gt7.racecraft_view()
    assert set(off) == RC and off["mode"] == "off" and off["ahead"] is None and "only F1 25" in off["reason"]
    q = CarHealthEngine("q")
    q.feed(info(session_type=SessionType.QUALIFYING))
    assert q.racecraft_view()["reason"] == "attack and defend work in races only"
    assert set(off_racecraft(None, "no live session")) == RC
    na = off_car_health(None, "no live session")
    assert set(na) - {"thresholds"} == TOP and na["tyres"] == {"available": False, "reason": "no live session"}


def test_ac_sections_say_what_is_not_sent() -> None:
    eng = CarHealthEngine("ac")
    eng.feed(info(game=Game.AC, model=None))
    eng.feed(frame(1.0, game=Game.AC, surf=None, inner=None, brakes_c=None, engine_c=None, pressure=None, wear=None))
    v = eng.view()
    assert v["tyres"] == {"available": False, "reason": "Assetto Corsa doesn't send tyre temperatures."}
    assert v["fuel"]["status"] == "not_sent" and "fuel" in v["fuel"]["reason"]
