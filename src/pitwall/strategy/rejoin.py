"""Where the player comes out if they box now (``PitView.rejoin``, F1 races), rebuilt on real F1 25 data.

Real F1 25 (PS5, the Imola 32-lap race): LapData zeroes both ``deltaToRaceLeader`` and ``deltaToCarInFront`` 1-2 s
*before* a car turns into the pit lane (driver status in-lap) and keeps them zero through the lane, and about 20 % of
the other cars' leader gaps read zero at any one tick. The first rule (gap to the leader + pit loss, cars without a gap
dropped: ``cuts.rejoin``) could therefore predict 2 of the 32 stops. This one:

1. **Leader gap per car** (``resolve_leader_gaps``): the game's (0 for P1); else chained from the car in front (its
   gap + this car's ``deltaToCarInFront``) when both are known; else the last known value at most
   ``LAST_KNOWN_MAX_AGE_S`` old (``PitTracker.last_known_leader``); else unknown, counted in ``unknown_cars``.
2. **The player on the in-lap or in the pit lane**: the last prediction made on track, ``frozen``, for up to
   ``FROZEN_MAX_S`` (its own gap is zero by then).
3. ``t_out`` = the player's gap + the pit loss (median); ``t_lo`` / ``t_hi`` with the measured range when at least two
   stops were measured, else +-``LOSS_RANGE_FRAC``.
4. **The others**: active cars on track with a known gap, and cars already in the pit lane at their entry gap + the
   loss (``PitVisit.entry_leader_ms``, itself last-known when the game had zeroed it).
5. ``position`` = 1 + the cars with g < t_out; ``position_low`` / ``position_high`` the same at t_lo / t_hi.
6. **Neighbours**: the car with the largest g < t_out (ahead, ``ahead_position`` = position - 1) and the smallest
   g >= t_out (behind).
7. **Road traffic** [H]: every other car's race-time difference modulo one lap (L = the median green lap):
   Δ = ((g - t_out + L/2) mod L) - L/2. A car less than ``TRAFFIC_S`` ahead on the road (``road_ahead_s``) is
   traffic, a lapped car included, which a position count cannot see.
8. **No measured loss** (or the player's own gap unknown this moment): no position, ``basis: "game_only"`` with the
   game's own ``pitStopRejoinPosition`` and the ``reason`` (``no_loss`` / ``no_gap``).

On 28 real Imola stops (the loss measured leave-one-out): |predicted - position 10 s after the exit| <= 1 for 75 %
and <= 2 for 100 %; [low, high] +- 1 covered 89 %; both player stops exact. The game's own value said P4 where the
car came out P2, and reads 0 once on the in-lap: it is shown next to the estimate, never instead of it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pitwall.model.telemetry import CarTiming
from pitwall.strategy.cuts import TRAFFIC_S, leader_s

LAST_KNOWN_MAX_AGE_S = 15.0  # [R] F1 25 zeroes both timing deltas 1-2 s before pit entry and through the lane
FROZEN_MAX_S = 120.0  # [H] the prediction made on track is kept this long while the player is in the lane
LOSS_RANGE_FRAC = 0.10  # [H] the loss range when fewer than two stops were measured

SOURCE_GAME = "game"
SOURCE_CHAINED = "chained"
SOURCE_LAST_KNOWN = "last_known"
BASIS_MEASURED = "measured_loss"
BASIS_ESTIMATED = "estimated_loss"  # the safety-car / VSC loss when none was measured under one (heuristic)
BASIS_GAME_ONLY = "game_only"
REASON_NO_LOSS = "no_loss"  # game_only: no pit stop timed in this race yet (none under this safety car either)
REASON_NO_GAP = "no_gap"  # game_only: the player's own gap to the leader is not known this moment

type LastKnown = Mapping[int, tuple[float, float]]  # car index -> (session time s, gap to the leader s)


@dataclass(slots=True, frozen=True)
class Loss:
    """The pit loss to use now: median and range (s), the stops behind it and its tier ("measured" / "heuristic")."""

    median_s: float
    low_s: float
    high_s: float
    n: int
    tier: str

    @classmethod
    def of(cls, median_s: float, low_s: float | None, high_s: float | None, n: int, tier: str) -> Loss:
        if n >= 2 and low_s is not None and high_s is not None:
            return cls(median_s, min(low_s, median_s), max(high_s, median_s), n, tier)
        return cls(median_s, median_s * (1 - LOSS_RANGE_FRAC), median_s * (1 + LOSS_RANGE_FRAC), n, tier)


def resolve_leader_gaps(
    cars: Sequence[CarTiming], now: float, last_known: LastKnown | None = None
) -> dict[int, tuple[float | None, str | None]]:
    """Car index -> (gap to the leader in s, source): the game's, else chained, else last known, else (None, None)."""
    out: dict[int, tuple[float | None, str | None]] = {}
    prev: float | None = None
    have_prev = False
    for c in sorted((c for c in cars if c.position > 0), key=lambda x: x.position):
        g = leader_s(c)
        src: str | None = SOURCE_GAME if g is not None else None
        if g is None and have_prev and prev is not None and c.gap_ahead_ms is not None:
            g, src = prev + c.gap_ahead_ms / 1000.0, SOURCE_CHAINED
        if g is None and last_known is not None:
            lk = last_known.get(c.car_index)
            if lk is not None and 0.0 <= now - lk[0] <= LAST_KNOWN_MAX_AGE_S:
                g, src = lk[1], SOURCE_LAST_KNOWN
        out[c.car_index] = (g, src)
        prev, have_prev = g, True
    return out


def remember(
    last_known: dict[int, tuple[float, float]], resolved: Mapping[int, tuple[float | None, str | None]], now: float
) -> None:
    """Keep the gaps the game gave (directly or chained) as the cars' last known values; never refresh a stale one."""
    for idx, (g, src) in resolved.items():
        if g is not None and src in (SOURCE_GAME, SOURCE_CHAINED):
            last_known[idx] = (now, g)


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def game_only(game_position: int | None, unknown_cars: int = 0, reason: str | None = None) -> dict[str, Any] | None:
    """The game's own value alone; ``reason`` why Pitwall has none: ``REASON_NO_LOSS`` (no stop timed yet) or
    ``REASON_NO_GAP`` (the player's own gap is not known this moment, e.g. right after a stop)."""
    game = game_position if game_position else None
    if game is None:
        return None
    return {
        "position": None,
        "gap_ahead_s": None,
        "gap_behind_s": None,
        "traffic": None,
        "game_position": game,
        "position_low": None,
        "position_high": None,
        "ahead_position": None,
        "behind_position": None,
        "road_ahead_s": None,
        "road_behind_s": None,
        "unknown_cars": unknown_cars,
        "frozen": False,
        "loss_s": None,
        "loss_tier": None,
        "loss_n": 0,
        "basis": BASIS_GAME_ONLY,
        "reason": reason,
    }


def predict(
    player: CarTiming,
    cars: Sequence[CarTiming],
    *,
    resolved: Mapping[int, tuple[float | None, str | None]],
    loss: Loss | None,
    game_position: int | None,
    in_lane: Mapping[int, float] | None = None,
    lap_s: float | None = None,
) -> dict[str, Any] | None:
    """One prediction (rules 1 and 3-8; the freeze is ``RejoinPredictor``'s). None without a loss and a game value."""
    in_lane = in_lane or {}
    me = resolved.get(player.car_index, (None, None))[0]
    if me is None and player.position == 1:
        me = 0.0
    others: list[float] = []
    unknown = 0
    for c in cars:
        if c.car_index == player.car_index or c.result_status != "active":
            continue
        if c.pit_status:
            entry = in_lane.get(c.car_index)
            if entry is None or loss is None:
                unknown += 1
            else:
                others.append(entry + loss.median_s)
            continue
        g = resolved.get(c.car_index, (None, None))[0]
        if g is None:
            unknown += 1
        else:
            others.append(g)
    if loss is None or me is None:
        return game_only(game_position, unknown, REASON_NO_LOSS if loss is None else REASON_NO_GAP)
    t_out = me + loss.median_s
    t_lo, t_hi = me + loss.low_s, me + loss.high_s
    ahead = [g for g in others if g < t_out]
    behind = [g for g in others if g >= t_out]
    position = 1 + len(ahead)
    gap_ahead = None if not ahead else t_out - max(ahead)
    gap_behind = None if not behind else min(behind) - t_out
    road_ahead = road_behind = None
    if lap_s is not None and lap_s > 2 * TRAFFIC_S:
        half = lap_s / 2
        for g in others:
            delta = ((g - t_out + half) % lap_s) - half
            if -TRAFFIC_S < delta < 0:
                road_ahead = -delta if road_ahead is None else min(road_ahead, -delta)
            elif 0 <= delta < TRAFFIC_S:
                road_behind = delta if road_behind is None else min(road_behind, delta)
        traffic: bool | None = road_ahead is not None
    else:
        traffic = None if gap_ahead is None else gap_ahead < TRAFFIC_S
    return {
        "position": position,
        "gap_ahead_s": _r(gap_ahead),
        "gap_behind_s": _r(gap_behind),
        "traffic": traffic,
        "game_position": game_position if game_position else None,
        "position_low": 1 + sum(1 for g in others if g < t_lo),
        "position_high": 1 + sum(1 for g in others if g < t_hi),
        "ahead_position": position - 1 if ahead else None,
        "behind_position": position + 1 if behind else None,
        "road_ahead_s": _r(road_ahead),
        "road_behind_s": _r(road_behind),
        "unknown_cars": unknown,
        "frozen": False,
        "loss_s": round(loss.median_s, 1),
        "loss_tier": loss.tier,
        "loss_n": loss.n,
        "basis": BASIS_MEASURED if loss.tier == "measured" else BASIS_ESTIMATED,
    }


def player_in_lane(player: CarTiming) -> bool:
    """On the in-lap (the game has zeroed the gaps) or in the pit lane."""
    return bool(player.pit_status) or player.driver_status == "in_lap"


class RejoinPredictor:
    """Rule 2: keeps the last prediction made on track and hands it out ``frozen`` while the player is in the lane."""

    def __init__(self) -> None:
        self._last: tuple[float, dict[str, Any]] | None = None

    def update(
        self,
        player: CarTiming,
        cars: Sequence[CarTiming],
        now: float,
        *,
        resolved: Mapping[int, tuple[float | None, str | None]],
        loss: Loss | None,
        game_position: int | None,
        in_lane: Mapping[int, float] | None = None,
        lap_s: float | None = None,
    ) -> dict[str, Any] | None:
        last = self._last
        if player_in_lane(player) and last is not None and 0.0 <= now - last[0] <= FROZEN_MAX_S:
            return {**last[1], "frozen": True}
        out = predict(
            player, cars, resolved=resolved, loss=loss, game_position=game_position, in_lane=in_lane, lap_s=lap_s
        )
        if not player_in_lane(player) and out is not None and out.get("position") is not None:
            self._last = (now, out)
        return out

    def rewind(self, t: float) -> None:
        if self._last is not None and self._last[0] > t:
            self._last = None
