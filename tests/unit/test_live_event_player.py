"""Live events say whether an every-car event concerns the player (Drive's penalty/contact/fastest-lap chips)."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.core.live import LiveState
from pitwall.model.telemetry import EventKind, Game, GameEvent


def _event(kind: EventKind, payload: dict[str, Any]) -> dict[str, Any]:
    live = LiveState()
    live.on_event(GameEvent(kind=kind, game=Game.F1_25, t_recv_ns=1, code="X", payload=payload))
    return dict(live.events[0])


@pytest.mark.parametrize(
    ("kind", "payload", "expected"),
    [
        (EventKind.PENALTY, {"vehicleIdx": 3, "player_idx": 3}, True),
        (EventKind.PENALTY, {"vehicleIdx": 4, "player_idx": 3}, False),
        (EventKind.FASTEST_LAP, {"vehicleIdx": 0, "lapTime": 80.1, "player_idx": 0}, True),
        (EventKind.FASTEST_LAP, {"vehicleIdx": 7, "lapTime": 80.1, "player_idx": 0}, False),
        (EventKind.COLLISION, {"vehicle1Idx": 5, "vehicle2Idx": 2, "player_idx": 2}, True),
        (EventKind.COLLISION, {"vehicle1Idx": 2, "vehicle2Idx": 9, "player_idx": 2}, True),
        (EventKind.COLLISION, {"vehicle1Idx": 5, "vehicle2Idx": 9, "player_idx": 2}, False),
    ],
)
def test_every_car_events_carry_player(kind: EventKind, payload: dict[str, Any], expected: bool) -> None:
    assert _event(kind, payload)["player"] is expected


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        (EventKind.PENALTY, {"vehicleIdx": 3}),  # no player index: unknown stays unknown
        (EventKind.PENALTY, {"player_idx": 3}),  # no car index
        (EventKind.COLLISION, {"player_idx": 3}),
        (EventKind.FLASHBACK, {"player_idx": 3}),  # player-only by nature: no field
        (EventKind.SAFETY_CAR, {"player_idx": 3}),
    ],
)
def test_player_is_absent_when_unknown_or_not_an_every_car_event(kind: EventKind, payload: dict[str, Any]) -> None:
    assert "player" not in _event(kind, payload)
