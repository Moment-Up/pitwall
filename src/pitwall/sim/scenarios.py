"""Named synthetic scenarios with documented ground truth. Output captures are flagged ``synthetic=True``."""

from __future__ import annotations

from pathlib import Path

from pitwall.ingest.capture import CaptureMeta, write_capture
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.sim.f1_stream import F1Scenario, FlashbackSpec, GroundTruth, generate_f1_session


def coaching_demo() -> F1Scenario:
    """Seven laps at 'Pitwall Park' with known mistakes (names are the synthetic design names, not
    pitwall's learned corner numbers):

    lap 1-2: clean, near-optimal (lap 1 is the reference)
    lap 3:   brakes 15 m early into design-T3
    lap 4:   8 km/h low apex speed at design-T7
    lap 5:   40 m late to full throttle out of design-T8
    lap 6:   flashback mid-lap (lap must be excluded from references)
    lap 7:   invalidated by the game (track limits) + braking early at design-T1
    """
    return F1Scenario(
        laps=7,
        driver_by_lap={
            3: DriverProfile(deviations={"T3": CornerDeviation(brake_early_m=15)}),
            4: DriverProfile(deviations={"T7": CornerDeviation(apex_speed_loss_kph=8)}),
            5: DriverProfile(deviations={"T8": CornerDeviation(throttle_delay_m=40)}),
            7: DriverProfile(deviations={"T1": CornerDeviation(brake_early_m=20)}),
        },
        invalid_laps=frozenset({7}),
        flashback=FlashbackSpec(lap=6, at_fraction=0.45),
    )


def technique_demo() -> F1Scenario:
    """feat/technique: six laps at 'Pitwall Park' with MotionEx (real-game signs) and known technique deviations
    (design corner names; on this track design-T8 is learned as T5):

    every lap: 5 deg extra front slip angle mid-corner at design-T8 (a car symptom: it shows on the best lap too)
    lap 1-2, 6: otherwise clean (lap 1 or the fastest clean lap is the reference)
    lap 3:   runs 2.0 m wider (towards the outside) around the apex of design-T3
    lap 4:   front-left wheel locked for 0.3 s braking into design-T1 (ABS off)
    lap 5:   0.5 s of wheelspin with 6 deg of body slip on the exit of design-T8 (one lap only: not recurring)
    """
    us = (0.0, 5.0, 0.0)

    def lap(**extra: CornerDeviation) -> DriverProfile:
        return DriverProfile(deviations={"T8": CornerDeviation(understeer_deg=us), **extra})

    return F1Scenario(
        laps=6,
        default_driver=lap(),
        driver_by_lap={
            3: lap(T3=CornerDeviation(line_offset_m=2.0)),
            4: lap(T1=CornerDeviation(lockup_s=0.3)),
            5: DriverProfile(
                deviations={"T8": CornerDeviation(understeer_deg=us, wheelspin_s=0.5, body_slip_exit_deg=6.0)}
            ),
        },
        motion_ex=True,
        abs_on=False,
    )


SCENARIOS = {"coaching-demo": coaching_demo, "technique-demo": technique_demo}


def write_synthetic_capture(path: Path, scenario: F1Scenario | None = None, name: str = "coaching-demo") -> GroundTruth:
    sc = scenario or SCENARIOS[name]()
    packets, truth = generate_f1_session(sc)
    meta = CaptureMeta(
        source="synthetic",
        game_hint="f1_25",
        synthetic=True,
        description=f"SYNTHETIC F1 25 packet stream, scenario '{name}' - not real game output",
        extra={
            "track_name": truth.track.name if truth.track else "synthetic",
            "scenario": name,
            "lap_times_ms": truth.lap_times_ms,
        },
    )
    write_capture(path, packets, meta)
    return truth
