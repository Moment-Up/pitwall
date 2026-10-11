"""Undercut, overcut and rejoin assessment (deterministic, heuristic bands).

* **Gain G** of a new set, per lap: the game's tyre model (``d0 + g``: the gain now plus one lap of degradation,
  tier ``game``), else the median fresh-tyre gain the field's stops measured this session (pre-stop pace minus
  post-stop pace, at least two stops, tier ``measured``), else unknown.
* **Undercut on the car ahead** (assumed to respond next lap), on the settled gap: ``likely`` below ``0.7 G``,
  ``marginal`` up to ``G``, else ``unlikely`` [H]. Unknown without G or a settled gap, while that car is in the pit
  lane, when no stop is needed or when it has already made more stops than the player. A ``likely`` undercut
  that rejoins in traffic is only ``marginal``.
* **Threat from the car behind**: the same bands on the gap behind, assuming similar tyres.
* **Rejoin if the player boxes now**: race time after the stop = gap to the leader + pit loss; the rejoin position
  is one more than the cars (not in the pit lane) with a smaller gap to the leader, ``traffic`` = rejoining less than
  ``TRAFFIC_S`` [H] behind a car. The game's own ``pitStopRejoinPosition`` is shown next to it (tier ``game``).
* **A neighbour pitting**: where it rejoins relative to the player (its gap to the leader at pit entry + pit loss).
  The overcut is never given a number: lap data cannot separate out-lap warm-up from lane loss.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Any

from pitwall.model.telemetry import CarTiming

BAND_LOW = 0.7  # [H] undercut likely below 0.7 G ...
TRAFFIC_S = 1.0  # [H] rejoining closer than this behind a car is traffic
CLOSE_S = 1.0  # a neighbour rejoining within this of the player is "close"
MIN_MEASURED_GAINS = 2


def tyre_gain(game: tuple[str, float, float | None] | None, measured: Sequence[float]) -> tuple[float, str] | None:
    """(G s/lap, tier) or None. ``game`` = ``GameTyres.gain`` (compound, d0, g)."""
    if game is not None and game[1] > 0:
        return round(game[1] + (game[2] or 0.0), 3), "game"
    good = [m for m in measured if m > 0]
    if len(good) >= MIN_MEASURED_GAINS:
        return round(statistics.median(good), 3), "measured"
    return None


def leader_s(c: CarTiming) -> float | None:
    """Race-time gap to the leader: 0 for the leader (the game's 0 means "the leader" there), else the game's delta."""
    if c.position == 1:
        return 0.0
    return None if c.gap_leader_ms is None else c.gap_leader_ms / 1000.0


def cut_view(
    kind: str,
    gap_s: float | None,
    settled: bool,
    gain: tuple[float, str] | None,
    *,
    car: CarTiming | None,
    player_stops: int,
    stop_needed: bool | None,
    rejoin_traffic: bool | None = None,
) -> dict[str, Any] | None:
    """``CutView`` for ``kind`` "undercut" (the car ahead) or "threat" (the car behind)."""
    if car is None:
        return None
    who = "car ahead" if kind == "undercut" else "car behind"
    rng = None if gain is None else {"low": round(BAND_LOW * gain[0], 2), "high": round(gain[0], 2)}
    tier = "heuristic" if gain is None else gain[1]

    def out(status: str, reason: str) -> dict[str, Any]:
        return {
            "status": status,
            "gap_s": None if gap_s is None else round(gap_s, 2),
            "gain": rng,
            "reason": reason,
            "tier": tier,
        }

    if stop_needed is False:
        return out("unknown", "no stop needed")
    if car.pit_status:
        return out("unknown", f"the {who} is in the pit lane")
    if car.num_pit_stops > player_stops:
        return out("unknown", f"the {who} has already stopped")
    if gain is None:
        return out("unknown", "new-tyre gain not known yet")
    if gap_s is None or not settled:
        return out("unknown", "gap not settled")
    g = gain[0]
    if gap_s < BAND_LOW * g:
        status = "likely"
    elif gap_s <= g:
        status = "marginal"
    else:
        status = "unlikely"
    reason = f"gap {gap_s:.1f} s, new tyres {BAND_LOW * g:.1f}-{g:.1f} s a lap"
    if kind == "threat":
        reason += ", similar tyres assumed"
    if status == "likely" and kind == "undercut" and rejoin_traffic:
        status = "marginal"
        reason += ", rejoins in traffic"
    return out(status, reason)


def rejoin(
    player: CarTiming, cars: Sequence[CarTiming], loss_s: float | None, game_position: int | None
) -> dict[str, Any] | None:
    """Where the player rejoins if they box now (``PitView.rejoin``); None without a pit loss or a leader gap."""
    game = game_position if game_position else None
    me = leader_s(player)
    if loss_s is None or me is None:
        if game is None:
            return None
        return {"position": None, "gap_ahead_s": None, "gap_behind_s": None, "traffic": None, "game_position": game}
    t = me + loss_s
    others = [
        g
        for c in cars
        if not c.is_player and c.result_status == "active" and not c.pit_status and (g := leader_s(c)) is not None
    ]
    ahead = [g for g in others if g < t]
    behind = [g for g in others if g >= t]
    gap_ahead = None if not ahead else t - max(ahead)
    gap_behind = None if not behind else min(behind) - t
    return {
        "position": 1 + len(ahead),
        "gap_ahead_s": None if gap_ahead is None else round(gap_ahead, 1),
        "gap_behind_s": None if gap_behind is None else round(gap_behind, 1),
        "traffic": None if gap_ahead is None else gap_ahead < TRAFFIC_S,
        "game_position": game,
    }


def neighbour_stop(
    side: str,
    car: CarTiming,
    entry_leader_ms: int | None,
    player: CarTiming,
    cars: Sequence[CarTiming],
    loss_s: float | None,
) -> dict[str, Any]:
    """``NeighbourStopView``: where a pitting neighbour rejoins relative to the player (+ = behind the player)."""
    me = leader_s(player)
    base = 0.0 if car.position == 1 and entry_leader_ms is None else None
    its = base if entry_leader_ms is None else entry_leader_ms / 1000.0
    if loss_s is None or me is None or its is None:
        return {"car": side, "car_index": car.car_index, "rejoin_gap_s": None, "status": "unknown", "traffic": None}
    t = its + loss_s
    gap = t - me
    status = "covered" if gap > CLOSE_S else ("ahead" if gap < -CLOSE_S else "close")
    others = [
        g
        for c in cars
        if c.car_index != car.car_index and c.result_status == "active" and (g := leader_s(c)) is not None
    ]
    near = [t - g for g in others if g < t]
    traffic = bool(near) and min(near) < TRAFFIC_S
    return {
        "car": side,
        "car_index": car.car_index,
        "rejoin_gap_s": round(gap, 1),
        "status": status,
        "traffic": traffic,
    }
