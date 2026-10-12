"""Race radio engine (raceradio.engine): modes per game, common suppression, synthetic tagging, the view contract."""

from __future__ import annotations

import json
import math

import pytest

from pitwall.model.synthetic import SYNTHETIC_SESSION_UID
from pitwall.model.telemetry import FrameQuality, Game, SessionType
from pitwall.raceradio.engine import RaceRadioEngine
from pitwall.raceradio.model import RECORDED_CALLS, off_view
from tests.unit.raceradio_helpers import (
    PLAYER,
    Run,
    car,
    damage,
    event,
    frame,
    info,
    participant,
    participants,
    pens,
    race,
    timing,
)

VIEW_KEYS = set(off_view(None))


@pytest.mark.parametrize(
    ("game", "stype", "extra", "mode", "reason"),
    [
        (Game.F1_25, SessionType.RACE, {}, "race", None),
        (Game.F1_25, SessionType.PRACTICE, {}, "session", None),
        (Game.F1_25, SessionType.QUALIFYING, {}, "session", None),
        (Game.F1_25, SessionType.TIME_TRIAL, {}, "off", "time trial"),
        (Game.F1_25, SessionType.UNKNOWN, {}, "off", "not a race, practice or qualifying session"),
        (Game.AC, SessionType.UNKNOWN, {}, "off", "the race radio needs F1, GT7 or Forza race data"),
        (Game.GT7, SessionType.UNKNOWN, {"num_cars_pre_race": 1}, "off", "GT7 sends a race position only in races"),
    ],
)
def test_mode(game: Game, stype: SessionType, extra: dict[str, object], mode: str, reason: str | None) -> None:
    r = Run()
    r.feed(info(0.0, game=game, stype=stype, extra=extra), frame(0.1, game=game, pos=3))
    assert (r.engine.st.mode, r.engine.view()["reason"]) == (mode, reason)


def test_spectating_is_off() -> None:
    r = race()
    r.feed(frame(1.0, quality=FrameQuality.REPLAY_OR_SPECTATING))
    assert r.engine.st.mode == "off" and r.engine.view()["reason"] == "spectating or a replay"


@pytest.mark.parametrize("quality", [FrameQuality.PAUSED, FrameQuality.REPLAY_OR_SPECTATING, FrameQuality.NOT_RACING])
def test_not_driving_suppresses_all_but_urgent(quality: FrameQuality) -> None:
    r = race()
    r.drive(0.0, 2.0)
    assert r.drive(2.0, 3.0, fia="blue", quality=quality) == []
    assert [c.call for c in r.feed(event(4.0, "RDFL"))] == ["red_flag"] or quality is FrameQuality.REPLAY_OR_SPECTATING
    assert r.engine.dropped >= 1 or quality is FrameQuality.REPLAY_OR_SPECTATING  # spectating: the mode is off


def test_synthetic_sessions_make_every_call_tagged_synthetic() -> None:
    r = Run()
    r.feed(info(0.0, uid=str(SYNTHETIC_SESSION_UID)))
    r.drive(0.0, 2.0)
    calls = r.drive(2.0, 3.0, fia="blue")
    assert [(c.call, c.synthetic, c.tier) for c in calls] == [("blue_flag", True, "synthetic")]
    assert r.engine.view()["synthetic"] is True


def test_real_sessions_tier_by_the_rules_evidence() -> None:
    r = race()
    r.drive(0.0, 2.0)
    blue = r.drive(2.0, 3.0, fia="blue")
    sc = r.feed(info(5.0, sc="full"))
    assert [(c.call, c.tier, c.synthetic) for c in blue + sc] == [
        ("blue_flag", "recorded", False),
        ("sc_deployed", "synthetic", False),  # no real capture has a safety car
    ]
    assert "sc_deployed" not in RECORDED_CALLS and "red_flag" not in RECORDED_CALLS


def test_call_ids_and_the_live_note_contract() -> None:
    r = race()
    r.drive(0.0, 2.0, lap=4)
    c = r.drive(2.0, 3.0, lap=4, fia="blue")[0]
    d = c.to_dict()
    assert c.id == "rc-1-4"
    assert set(d) == {
        "id",
        "session_id",
        "group",
        "call",
        "kind",
        "priority",
        "text",
        "text_simple",
        "speech_source",
        "ttl_s",
        "needs_window",
        "bypass_quiet",
        "topic",
        "lap",
        "addressable",
        "defer_to_strategy_detail",
        "audience",
        "allowance",
        "data",
        "tier",
        "synthetic",
        "t_unix",
    }
    assert json.loads(json.dumps(d)) == d


def test_view_contract_on_a_busy_state() -> None:
    r = Run(RaceRadioEngine("8d7c2f3a9b1e4d6f8a0c2e4b6d8f0a1c", clock=lambda: 1_760_000_000.123))  # a real-length id
    r.feed(info(0.0, total_laps=50, sc="none"))
    r.feed(participants(0.0, [participant(i, driver=54, name="Driver 01") for i in range(20)]))
    for i in range(400):
        t = i * 0.5
        r.feed(
            frame(t, lap=12, d=100.0 + i * 10, pos=5, fia="yellow", damage=damage(fl=58, rw=35, floor=70, sidepod=40,
                  tyres=(0, 0, 100, 100), brakes=(0, 35, 0, 70)), penalties=pens(time_s=15, warnings=3, cc=2, dt=1)),
            timing(t, [car(k, k + 1, lap=12) for k in range(20)]),
        )  # fmt: skip
    r.feed(event(201.0, "PENA", penaltyType=4, infringementType=7, vehicleIdx=PLAYER, time=5))
    r.feed(event(202.0, "PENA", penaltyType=0, infringementType=17, vehicleIdx=PLAYER, time=0))
    r.feed(event(203.0, "PENA", penaltyType=2, infringementType=50, vehicleIdx=PLAYER, time=0))
    v = r.engine.view()
    assert set(v) == VIEW_KEYS and v["version"] == 1 and len(v["calls"]) == 3
    blob = json.dumps(v, allow_nan=False, separators=(",", ":"))  # compact, as the API's orjson sends it
    assert len(blob.encode()) <= 1300, len(blob.encode())
    assert v["penalties"] == {
        "time_s": 15,
        "warnings": 3,
        "track_limits": 2,
        "drive_throughs": 1,
        "stop_gos": 0,
        "serve_at_stop": False,
    }
    assert v["flags"]["you"] == "yellow" and v["position"] == 5 and v["cars"] == 20 and v["total_laps"] == 50


def test_unknown_stays_null_and_nan_never_reaches_the_view() -> None:
    r = race(total_laps=None, length=None)
    r.feed(frame(0.0, speed=math.nan, d=None, pos=None))
    v = r.engine.view()
    assert set(v) == VIEW_KEYS
    assert v["position"] is None and v["laps_left"] is None and v["total_laps"] is None
    json.dumps(v, allow_nan=False)
    assert Run().engine.view() == {**off_view("no session information yet", "s1"), "game": None}
