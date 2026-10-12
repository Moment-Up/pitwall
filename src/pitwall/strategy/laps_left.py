"""Laps left in a race, as a pure function (the lapped-car rule), shared by race strategy and the race radio.

``StrategyEngine.laps_remaining`` is a thin wrapper around this (behaviour unchanged); ``pitwall.raceradio`` calls it
for "laps to go" and "last lap". The race ends for every car at its first line crossing after the leader takes the
flag, so a lapped car runs fewer laps than ``total_laps``: when the leader's laps left (in its own laps, at about the
player's pace) are fewer than the player's, the player's count is the distance to the line plus the leader's whole laps
still to run after that. ``cars=()`` (no field timing: GT7, Forza) gives the plain ``total - lap + 1 - frac``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from pitwall.model.telemetry import CarTiming

SOURCE_LAPS = "laps"  # total laps minus laps done
SOURCE_FLAG = "flag"  # the leader took the flag: the race ends at the next line
SOURCE_LEADER = "leader"  # lapped: the leader finishes first
SOURCE_DONE = "done"  # the player took the flag or is out of the race


def laps_remaining_detail(
    *,
    total_laps: int | None,
    lap: int | None,
    lap_frac: float,
    cars: Sequence[CarTiming],
    track_length_m: float | None,
    took_flag: bool,
    player_result: str | None,
) -> tuple[float | None, str | None]:
    """(laps left, where the number comes from: ``SOURCE_*``); (None, None) when the race length or lap is unknown.

    ``lap_frac`` is the player's fraction of the current lap (0..1); ``took_flag`` the player's last lap is complete;
    ``player_result`` the player's ``CarTiming.result_status`` (None = unknown)."""
    if total_laps is None or lap is None:
        return None, None
    if took_flag or player_result not in (None, "active"):
        return 0.0, SOURCE_DONE  # took the flag (or out of the race): nothing left to run
    base = total_laps - lap + 1 - lap_frac
    to_line = 1.0 - lap_frac
    if any(c.result_status == "finished" for c in cars):
        return max(0.0, min(base, to_line)), SOURCE_FLAG  # the flag is out: the race ends at the next line
    # Lapped: the race ends at the first line crossing after the leader takes the flag (the leader's laps left, in its
    # own laps, at about the player's pace).
    lead = next((c for c in cars if c.position == 1 and c.result_status == "active"), None)
    source = SOURCE_LAPS
    if lead is not None and not lead.is_player and track_length_m:
        lead_frac = min(1.0, max(0.0, lead.lap_distance_m) / track_length_m)
        lead_left = total_laps - lead.lap_number + 1 - lead_frac
        if lead_left < base:
            lapped = to_line + max(0, math.ceil(lead_left - to_line - 1e-9))
            if lapped < base - 1e-9:
                source = SOURCE_LEADER  # the leader's flag really ends the race early (not just a leader ahead)
            base = lapped
    return max(0.0, base), source


def laps_remaining(
    *,
    total_laps: int | None,
    lap: int | None,
    lap_frac: float,
    cars: Sequence[CarTiming],
    track_length_m: float | None,
    took_flag: bool,
    player_result: str | None,
) -> float | None:
    """Laps left for the player (see ``laps_remaining_detail``)."""
    return laps_remaining_detail(
        total_laps=total_laps,
        lap=lap,
        lap_frac=lap_frac,
        cars=cars,
        track_length_m=track_length_m,
        took_flag=took_flag,
        player_result=player_result,
    )[0]


def lap_fraction(lap_distance_m: float | None, track_length_m: float | None) -> float:
    """The player's fraction of the lap for ``laps_remaining``: 0 when unknown or before the line (as strategy)."""
    if lap_distance_m is None or not track_length_m or lap_distance_m <= 0:
        return 0.0
    return min(1.0, lap_distance_m / track_length_m)
