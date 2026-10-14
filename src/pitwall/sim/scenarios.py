"""Named synthetic scenarios with documented ground truth. Output captures are flagged ``synthetic=True``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pitwall.ingest.capture import CaptureMeta, write_capture
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.sim.f1_stream import F1Scenario, FlashbackSpec, GroundTruth, generate_f1_session

# The coaching demo's injected mistakes (design corner names; ``coaching_demo``). Pitwall learns its own corner
# numbers from the speed minima: design-T1 is learned as T1, design-T3 as T2, the design-T4/T5 chicane as T3,
# design-T7 as T4 and design-T8 as T5 (design-T2 and T6 are taken flat out: no corner). Sizes measured at 20, 30 and
# 60 Hz: the braking habit stays under a big one-off on its first lap (about 0.24 s) and clear of the braking call's
# confidence floor (0.7-0.9), the big one-off well over BIG_ONE_OFF_S.
DEMO_BRAKE_EARLY = CornerDeviation(brake_early_m=15)  # design-T8 (learned T5): a braking habit, about 0.24 s a lap
DEMO_APEX_SLOW = CornerDeviation(apex_speed_loss_kph=9)  # design-T7 (learned T4): a habit, about 0.09 s a lap
DEMO_SMALL_ONE_OFF = CornerDeviation(apex_speed_loss_kph=7)  # design-T1 (learned T1): about 0.1 s, screen only
DEMO_BIG_ONE_OFF = CornerDeviation(throttle_delay_m=30)  # design-T3 (learned T2): about 0.67 s, said once


def coaching_demo() -> F1Scenario:
    """Ten laps at 'Pitwall Park' that tell the habits story (``COACHING_DEMO_STORY`` says what the radio and the Drive
    screen show, in the corner names Pitwall learns). Design corner names here:

    lap 1:     clean (the reference)
    laps 2-10: 9 km/h low apex speed at design-T7 (a habit that waits while another one is worked on)
    laps 3-5:  brake 15 m early into design-T8 (a braking habit: announced after lap 4, called on laps 5-7)
    laps 6-10: brake on the reference point at design-T8 (the corner gets faster: sorted after lap 7)
    lap 5:     flashback mid-lap (shown, never a habit lap nor a reference)
    lap 6:     7 km/h low apex speed at design-T1 (a small one-off: on the screen only)
    lap 9:     30 m late to full throttle out of design-T3 (a big one-off: said once)
    lap 10:    invalidated by the game (track limits: shown, never a habit lap nor a reference)
    """
    plan: dict[int, dict[str, CornerDeviation]] = {lap: {"T7": DEMO_APEX_SLOW} for lap in range(2, 11)}
    for lap in (3, 4, 5):
        plan[lap]["T8"] = DEMO_BRAKE_EARLY
    plan[6]["T1"] = DEMO_SMALL_ONE_OFF
    plan[9]["T3"] = DEMO_BIG_ONE_OFF
    return F1Scenario(
        laps=10,
        driver_by_lap={lap: DriverProfile(deviations=devs) for lap, devs in plan.items()},
        invalid_laps=frozenset({10}),
        flashback=FlashbackSpec(lap=5, at_fraction=0.45),
    )


@dataclass(frozen=True, slots=True)
class StoryBeat:
    """One thing to look for in a SYNTHETIC scenario's replay: on which laps, when (``AFTER_THE_LINE``, before a
    corner such as "before T5", ``ON_THE_SCREEN`` or ``WITH_THE_LAP_TIME``), the exact radio line said on its own
    (None: not one) or else what the Drive screen or the lap time shows, and what it shows about the coaching."""

    laps: tuple[int, ...]
    when: str
    radio: str | None
    screen: str | None
    shows: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "laps": list(self.laps),
            "when": self.when,
            "radio": self.radio,
            "screen": self.screen,
            "shows": self.shows,
        }


@dataclass(frozen=True, slots=True)
class Story:
    """What a scenario's replay shows: ``intro`` (the settings it assumes) and its beats in the order they happen."""

    intro: str
    beats: tuple[StoryBeat, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"intro": self.intro, "beats": [b.to_dict() for b in self.beats]}


AFTER_THE_LINE = "after the line"
ON_THE_SCREEN = "on the screen"
WITH_THE_LAP_TIME = "with the lap time"

# The coaching demo's story, pinned line for line by tests/synthetic/test_demo_story.py (60 Hz, both packet formats).
# Corner names are the LEARNED ones the demo shows (``coaching_demo`` lists the design names).
COACHING_DEMO_STORY = Story(
    intro=(
        "SYNTHETIC: 10 generated laps at Pitwall Park, about 11 minutes at real time. With the defaults (Normal "
        "coaching, nobody in the seat, braking calls in Focus) and the radio on (Drive › Radio, Go live) you should "
        "hear and see these, in the corner names the demo learns (T1-T5). A habit is worked on only once the radio "
        "has said it: without the radio the Drive screen still shows every lap's notes."
    ),
    beats=(
        StoryBeat(
            (4,),
            AFTER_THE_LINE,
            "T5, losing 0.23 s: braking 14 m earlier. 2 of the last 3 laps.",
            None,
            "A braking habit, announced once with how often it happened. Lap 3's early braking alone was a small "
            "one-off: on the screen only.",
        ),
        StoryBeat(
            (5, 6, 7),
            "before T5",
            "T5 brake",
            None,
            "Braking calls: the word lands where you braked on your reference lap (lap 1). Lap 5 still brakes early; "
            "laps 6 and 7 brake on the point.",
        ),
        StoryBeat(
            (6,),
            ON_THE_SCREEN,
            None,
            "T1: 7 km/h slower mid-corner",
            "A small one-off (under 0.3 s): on the Drive screen only, never on the radio.",
        ),
        StoryBeat(
            (7,),
            AFTER_THE_LINE,
            "T5 sorted: clean on 2 of the last 3 laps.",
            None,
            "Sorted: two laps on the point since the announcement, with T5 faster than on the laps that braked early.",
        ),
        StoryBeat(
            (8,),
            AFTER_THE_LINE,
            "T4, losing 0.09 s: minimum speed 9 km/h down. 5 of the last 5 laps.",
            None,
            "The habit that waited becomes the focus once T5 is sorted: one at a time at Normal (Detailed announces "
            "both after lap 4).",
        ),
        StoryBeat(
            (9, 10),
            "before T4",
            "T4: apex speed, 9 down",
            None,
            "A corner reminder for a habit that is not about braking: it ends a second before the braking point.",
        ),
        StoryBeat(
            (9,),
            AFTER_THE_LINE,
            "T2, losing 0.67 s: full throttle 31 m later than your reference.",
            None,
            "A big one-off (0.3 s or more): said once.",
        ),
        StoryBeat(
            (5, 10),
            WITH_THE_LAP_TIME,
            None,
            "Flashback used. (lap 5) / That lap was invalidated. (lap 10)",
            "A flashback lap and a lap the game invalidated (track limits): shown, never counted as a habit lap or "
            "used as the reference.",
        ),
    ),
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
# What each named scenario's replay shows (meta.extra["story"] of its capture, the simulate API's "story").
STORIES: dict[str, Story] = {"coaching-demo": COACHING_DEMO_STORY}


def write_synthetic_capture(path: Path, scenario: F1Scenario | None = None, name: str = "coaching-demo") -> GroundTruth:
    """Write the SYNTHETIC capture of ``scenario`` (default: the named one). Its ``meta.extra`` carries the named
    scenario's story (``STORIES``) when it has one: pass a scenario of another shape under another name."""
    sc = scenario or SCENARIOS[name]()
    packets, truth = generate_f1_session(sc)
    extra: dict[str, Any] = {
        "track_name": truth.track.name if truth.track else "synthetic",
        "scenario": name,
        "lap_times_ms": truth.lap_times_ms,
    }
    story = STORIES.get(name)
    if story is not None:
        extra["story"] = story.to_dict()
    meta = CaptureMeta(
        source="synthetic",
        game_hint="f1_25",
        synthetic=True,
        description=f"SYNTHETIC F1 25 packet stream, scenario '{name}' - not real game output",
        extra=extra,
    )
    write_capture(path, packets, meta)
    return truth
