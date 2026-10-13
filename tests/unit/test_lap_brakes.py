"""v0.3.0 speak windows on a new track: the car's own braking zones of its last lap (voice.lap_brakes), merged with the
track knowledge in the hub's driving state, so a sentence does not run into a corner the knowledge does not cover."""

from __future__ import annotations

from dataclasses import dataclass

from pitwall.voice.hub import time_to_next_braking
from pitwall.voice.lap_brakes import LAPS_KEPT, LapBrakeZones, merged


@dataclass
class F:
    lap_number: int | None
    lap_distance_m: float | None
    brake: float | None
    pit_status: int | None = None


def drive(
    z: LapBrakeZones, lap: int, brakes: dict[tuple[float, float], float], length: float = 5000.0, pit_from: float = 1e9
) -> None:
    """A lap at 5 m steps: brake ``v`` inside each (start, end) of ``brakes``; in the pit lane from ``pit_from``."""
    for d in range(0, int(length), 5):
        b = next((v for (s, e), v in brakes.items() if s <= d < e), 0.0)
        z.observe(F(lap, float(d), b, 1 if d >= pit_from else 0), length)


def test_the_last_full_laps_give_the_zones() -> None:
    z = LapBrakeZones()
    drive(z, 1, {(900.0, 1100.0): 0.9, (3000.0, 3004.0): 0.8, (4000.0, 4200.0): 0.2})
    assert z.model() is None  # lap 1 is not complete yet
    drive(z, 2, {(950.0, 1150.0): 0.9})
    m = z.model()
    assert m is not None and m["length_m"] == 5000.0
    # a dab of the pedal is a zone too; a 0.2 trail of the pedal is not braking
    assert [(c["entry_m"], c["exit_m"]) for c in m["corners"]] == [(900.0, 1100.0), (3000.0, 3005.0)]
    assert time_to_next_braking(m, 500.0, 180.0) < 10.0  # 300 m (less the lead) at 50 m/s
    drive(z, 3, {})
    m = z.model()
    assert m is not None and (950.0, 1150.0) in [(c["entry_m"], c["exit_m"]) for c in m["corners"]]
    assert (900.0, 1100.0) in [(c["entry_m"], c["exit_m"]) for c in m["corners"]]  # braked there two laps ago
    for lap in range(4, 5 + LAPS_KEPT):  # LAPS_KEPT laps completed since (a lap without braking is not kept)
        drive(z, lap, {(2000.0, 2100.0): 0.9})
    m = z.model()
    assert m is not None and {(c["entry_m"], c["exit_m"]) for c in m["corners"]} == {(2000.0, 2100.0)}


def test_the_same_frame_twice_counts_once_and_a_flashback_forgets() -> None:
    z = LapBrakeZones()
    drive(z, 1, {(900.0, 1100.0): 0.9})
    drive(z, 2, {})
    assert z.model() is not None
    f = F(2, 1200.0, 0.9)
    z.observe(f, None)
    z.observe(f, None)
    z.observe(F(1, 4000.0, 0.0), None)  # back to lap 1: a flashback over the line
    assert z.model() is None
    z.reset()
    assert z.model() is None


def test_braking_across_the_line_is_closed_at_the_line() -> None:
    z = LapBrakeZones()
    drive(z, 1, {(4950.0, 5000.0): 0.9})
    drive(z, 2, {})
    m = z.model()
    assert m is not None and [(c["entry_m"], c["exit_m"]) for c in m["corners"]] == [(4950.0, 5000.0)]


def test_merged_keeps_every_zone() -> None:
    a = {"length_m": 5000.0, "corners": [{"entry_m": 100.0, "exit_m": 200.0}]}
    b = {"length_m": None, "corners": [{"entry_m": 900.0, "exit_m": 1000.0}]}
    m = merged(a, None, b)
    assert m == {"length_m": 5000.0, "corners": [*a["corners"], *b["corners"]]}
    assert merged(None, b) is b and merged(None, None) is None


def test_a_lap_in_the_pit_lane_is_not_the_tracks() -> None:
    """Measured (Jeddah): the in-lap's braking for the pit entry closed the speak window at the end of the next laps."""
    z = LapBrakeZones()
    drive(z, 1, {(900.0, 1100.0): 0.9})
    drive(z, 2, {(900.0, 1100.0): 0.9, (4800.0, 4900.0): 0.9}, pit_from=4850.0)  # the in-lap
    drive(z, 3, {(300.0, 320.0): 0.9}, pit_from=0.0)  # the out-lap starts in the pit lane
    drive(z, 4, {})
    m = z.model()
    assert m is not None and [(c["entry_m"], c["exit_m"]) for c in m["corners"]] == [(900.0, 1100.0)]
