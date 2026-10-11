"""Safety car / VSC (``strategy.safety_car``): state from the Session status and SCAR events, the box opportunity
and its pit-entry deadline. Synthetic/unit only: no real capture has a safety car yet."""

from __future__ import annotations

from pitwall.model.telemetry import EventKind, Game, GameEvent
from pitwall.strategy.safety_car import SafetyCarState, box_opportunity, entry_ttl_s
from tests.unit.strategy_helpers import session

LOSS = {"full_s": 9.5, "virtual_s": 11.3, "tier": "heuristic"}


def _scar(kind: int, event: int) -> GameEvent:
    return GameEvent(
        kind=EventKind.SAFETY_CAR,
        game=Game.F1_25,
        t_recv_ns=0,
        code="SCAR",
        payload={"safetyCarType": kind, "eventType": event},
    )


def test_state_from_status_and_scar() -> None:
    sc = SafetyCarState()
    sc.on_session(session(sc="none"), 3)
    assert sc.neutral is None and sc.period == 0
    sc.on_event(_scar(2, 0), 4)  # VSC deployed: the edge before the next Session packet
    assert sc.neutral == "virtual" and sc.period == 1 and sc.since_lap == 4
    sc.on_session(session(sc="virtual"), 4)
    assert sc.period == 1  # the same period
    sc.on_event(_scar(2, 2), 5)  # returned
    assert sc.neutral is None
    sc.on_session(session(sc="full"), 7)
    assert sc.neutral == "full" and sc.period == 2 and sc.since_lap == 7
    sc.on_session(session(sc="formation_lap"), 7)
    assert sc.neutral is None and sc.status == "formation_lap"


def _box(sc: SafetyCarState, **kw: object) -> dict[str, object] | None:
    args: dict[str, object] = {
        "laps_remaining": 10.0,
        "player_in_pit": False,
        "stop_needed": True,
        "window_open_lap": 12,
        "lap": 8,
        "new_set_reaches_flag": False,
        "loss": LOSS,
        "green_loss_s": 19.0,
        "ttl_s": 20.0,
    }
    args.update(kw)
    return box_opportunity(sc, **args)  # type: ignore[arg-type]


def test_box_vs_stay_out_and_conditions() -> None:
    sc = SafetyCarState()
    assert _box(sc) is None  # no safety car
    sc.on_session(session(sc="full"), 8)
    box = _box(sc)
    assert box == {
        "pit_loss_s": 9.5,
        "green_pit_loss_s": 19.0,
        "stop_needed": True,
        "this_lap": True,
        "tier": "heuristic",
    }
    assert _box(sc, window_open_lap=20) is None  # window too far away and a new set does not reach the flag
    assert _box(sc, window_open_lap=20, new_set_reaches_flag=True) is not None
    assert _box(sc, laps_remaining=1.5) is None and _box(sc, player_in_pit=True) is None
    assert _box(sc, stop_needed=None) is None
    stay = _box(sc, stop_needed=False)
    assert stay is not None and stay["stop_needed"] is False
    assert _box(sc, ttl_s=-1.0)["this_lap"] is False  # type: ignore[index]  # past the pit entry: next lap
    # no stop seen in this race yet: the pit entry is unknown, and "this lap" would be a guess (review: "Box this lap"
    # with the driver already past Austria's entry)
    assert _box(sc, ttl_s=None)["this_lap"] is None  # type: ignore[index]
    sc.on_session(session(sc="virtual"), 8)
    assert _box(sc)["pit_loss_s"] == 11.3  # type: ignore[index]


def test_entry_deadline() -> None:
    assert entry_ttl_s(4264.0, 4000.0, 180.0) == (264.0 / 50.0) - 3.0
    assert entry_ttl_s(None, 4000.0, 180.0) is None and entry_ttl_s(4264.0, 4000.0, 0.0) is None
