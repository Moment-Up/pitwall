"""Value types shared by the spotter's engine, worker, scorer and the radio hub."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Side = Literal["left", "right"]
SIDES: tuple[Side, Side] = ("left", "right")
LEFT, RIGHT = 0, 1

# Call kinds (``SpotterCall.kind``). Onsets announce traffic, clears release it.
CAR_LEFT = "car_left"
CAR_RIGHT = "car_right"
THREE_WIDE = "three_wide"
CLEAR_LEFT = "clear_left"
CLEAR_RIGHT = "clear_right"
CLEAR_ALL_ROUND = "clear_all_round"
STILL_THERE = "still_there"
HOLD_YOUR_LINE = "hold_your_line"
CALL_KINDS: tuple[str, ...] = (
    CAR_LEFT,
    CAR_RIGHT,
    THREE_WIDE,
    CLEAR_LEFT,
    CLEAR_RIGHT,
    CLEAR_ALL_ROUND,
    STILL_THERE,
    HOLD_YOUR_LINE,
)
ONSET_KINDS = frozenset({CAR_LEFT, CAR_RIGHT, THREE_WIDE, HOLD_YOUR_LINE})
CLEAR_KINDS = frozenset({CLEAR_LEFT, CLEAR_RIGHT, CLEAR_ALL_ROUND})

# Why the spotter is not active (``reason``), in gate order (spec section 3.6). The first closed gate wins.
REASONS: tuple[str, ...] = (
    "disabled",
    "not_available",
    "session_type",
    "red_flag",
    "safety_car",
    "start",
    "paused",
    "stale",
    "flashback",
    "pit",
    "finished",
    "spin",
    "slow",
)


@dataclass(slots=True, frozen=True)
class DecodedMotion:
    """One Motion packet decoded for every car (worker thread), plus the latest LapData statuses.

    ``cars[i]`` = (posX, posY, posZ, velX, velY, velZ, fwdX, fwdY, fwdZ, rightX, rightY, rightZ): positions in m,
    velocities in m/s, direction vectors as the raw int16 the game sends (divide by 32767, EA spec).
    ``status[i]`` = (pitStatus, driverStatus, resultStatus) of LapData; ``None`` = no LapData yet (unknown).
    """

    t_recv_ns: int
    session_time_s: float
    frame_id: int
    player_index: int
    packet_format: int
    cars: tuple[tuple[float, ...], ...]
    status: tuple[tuple[int, int, int], ...] | None


@dataclass(slots=True, frozen=True)
class SpotterCall:
    """A decision of the engine, handed to the radio. ``side`` is None for three wide / clear all round."""

    kind: str
    side: Side | None
    seq: int
    epoch: int  # engine reset counter: a call of an older epoch belongs to traffic the engine has forgotten
    session_time_s: float
    t_recv_ns: int  # t0: receive time of the packet that completed the decision (recv clock)
    t_decided_ns: int  # t1: when the engine decided (recv clock, worker thread)
    onset_game_ms: float | None = None  # game clock from the overlap's start to the decision (onsets)
    test: bool = False  # POST /api/spotter/test: no real car, validity checks skipped
    # a clear decided as a gate closed (slow, pit, finished: positions still valid): the engine has already forgotten
    # the episode (new epoch), so the radio checks only that the side is still clear
    final: bool = False
    origin: Any = field(default=None, compare=False, repr=False)  # the worker that made it (validity checks)

    @property
    def urgent(self) -> bool:
        """``still_there`` never cuts anything (HIGH); every other call is URGENT (spec section 5.2)."""
        return self.kind != STILL_THERE


@dataclass(slots=True, frozen=True)
class SpotterState:
    """What the hub re-checks before playing a call held in its mailbox (one immutable object, swapped)."""

    active: bool = False
    occupied: tuple[bool, bool] = (False, False)  # left, right: a car alongside now (no debounce)
    announced: tuple[bool, bool] = (False, False)
    last_seq: tuple[int, int] = (0, 0)  # seq of the newest call that concerned each side
    epoch: int = 0
    traffic: bool = False  # a side occupied, or cleared less than ``traffic_hold_s`` ago (game clock)


@dataclass(slots=True)
class PacketTrace:
    """Per-packet internals for the offline scorer (``spotter.score``); never published."""

    gate_open: bool = False
    gt: tuple[bool, bool] = (False, False)  # the geometric ground truth: an obstacle overlapping on that side
    announced: tuple[bool, bool] = (False, False)
    speed_kph: float | None = None
