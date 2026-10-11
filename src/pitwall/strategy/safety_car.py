"""Safety car / VSC state and the "box this lap" opportunity (synthetic only: no real capture has a safety car).

State comes from the Session packet's ``safetyCarStatus`` (2 Hz) with the ``SCAR`` event (deployed / returning /
returned / resume) for the edges in between; a period starts on none -> full or virtual. A stop under a safety car
costs less than under green: the measured neutralised stops of this race if any, else the green loss x 0.5 (full)
or x 0.6 (VSC), a heuristic (``[H]``, unvalidated in F1 25) that is always labelled as an estimate.

The opportunity holds in a race, under a full safety car or a VSC, with at least two laps to go and the player not
in the pit lane, when a stop is needed and the window opens within five laps or a new set reaches the flag from
now. With no stop needed it is the "stay out" variant. The pit-entry deadline: ``(pit entry - lap distance) /
speed - 3 s``; past it the call says "box next lap".
"""

from __future__ import annotations

from typing import Any

from pitwall.model.telemetry import GameEvent, SessionInfo

NEUTRAL = ("full", "virtual")
SCAR_TYPES = {1: "full", 2: "virtual", 3: "formation_lap"}  # SCAR safetyCarType (spec 8.12)
SCAR_DEPLOYED, SCAR_RETURNED = 0, 2  # SCAR eventType
OPEN_WITHIN_LAPS = 5
MIN_LAPS_REMAINING = 2.0
ENTRY_MARGIN_S = 3.0  # [H] the driver needs this long to react before the pit entry


class SafetyCarState:
    def __init__(self) -> None:
        self.status: str | None = None
        self.period = 0
        self.since_lap: int | None = None

    def _set(self, status: str | None, lap: int | None) -> None:
        if status in NEUTRAL and self.status not in NEUTRAL:
            self.period += 1
            self.since_lap = lap
        elif status not in NEUTRAL:
            self.since_lap = None if status in (None, "none") else self.since_lap
        self.status = status

    def on_session(self, info: SessionInfo, lap: int | None) -> None:
        self._set(info.safety_car_status, lap)

    def on_event(self, e: GameEvent, lap: int | None) -> None:
        if e.code != "SCAR":
            return
        kind = SCAR_TYPES.get(e.payload.get("safetyCarType", -1))
        ev = e.payload.get("eventType")
        if ev == SCAR_DEPLOYED and kind is not None:
            self._set(kind, lap)
        elif ev == SCAR_RETURNED:
            self._set("none", lap)

    @property
    def neutral(self) -> str | None:
        """The neutralisation in force: "full" | "virtual", else None."""
        return self.status if self.status in NEUTRAL else None


def entry_ttl_s(pit_entry_m: float | None, lap_distance_m: float | None, speed_kph: float | None) -> float | None:
    """Seconds left to decide before the pit entry on this lap (negative = past it); None when unknown."""
    if pit_entry_m is None or lap_distance_m is None or not speed_kph or speed_kph < 10:
        return None
    return (pit_entry_m - lap_distance_m) / (speed_kph / 3.6) - ENTRY_MARGIN_S


def box_opportunity(
    sc: SafetyCarState,
    *,
    laps_remaining: float | None,
    player_in_pit: bool,
    stop_needed: bool | None,
    window_open_lap: int | None,
    lap: int | None,
    new_set_reaches_flag: bool,
    loss: dict[str, Any],
    green_loss_s: float | None,
    ttl_s: float | None,
) -> dict[str, Any] | None:
    """``SafetyCarView.box`` or None (no neutralisation, too late in the race, already in the pit lane, unknown)."""
    status = sc.neutral
    if status is None or lap is None or lap < 1 or player_in_pit:
        return None
    if laps_remaining is None or laps_remaining < MIN_LAPS_REMAINING or stop_needed is None:
        return None
    if stop_needed and not (
        (window_open_lap is not None and window_open_lap <= lap + OPEN_WITHIN_LAPS) or new_set_reaches_flag
    ):
        return None
    pit_loss = loss.get("full_s" if status == "full" else "virtual_s")
    return {
        "pit_loss_s": pit_loss,
        "green_pit_loss_s": green_loss_s,
        "stop_needed": stop_needed,
        "this_lap": ttl_s is None or ttl_s > 0,
        "tier": loss.get("tier", "heuristic"),
    }
