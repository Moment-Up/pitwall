"""SYNTHETIC: the built-in coaching demo (``pitwall simulate``, Drive's "Try a demo replay", Settings › System) tells the
habits story its capture promises (``sim.scenarios.COACHING_DEMO_STORY``, the capture's ``meta.extra["story"]``), line
for line and in order: a braking habit announced once with its count, braking calls at its corner, "sorted" once the
corner got faster, the habit that waited becoming the focus with a corner reminder before its corner, a big one-off said
once, and a small one-off left on the screen.

Replayed through the real pipeline: packets -> F1 adapter -> SessionManager -> LapProcessor (run synchronously, as in
test_cues_replay.py, so each lap's analysis lands where the background worker would publish it) -> LiveState (coach
selection, habit tracker) -> cue engine in Focus mode, with the radio's lap messages at Normal intensity and nobody in
the seat. The radio commits habit lines two ways, and both must tell the same story: at the pick (no radio hub:
``pitwall replay``) and on air (the radio hub: ``CoachSelection.commit_on_delivery``, each habit line confirmed through
``LiveState.habit_line_said`` as the hub does when it says it, here right after its lap).

SYNTHETIC: proves the demo's script against the pipeline. It is NOT evidence of behaviour with a real game.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from pitwall.coach.cues import CueTiming
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.runtime import default_adapters
from pitwall.core.session import SessionManager
from pitwall.ingest.capture import CaptureReader
from pitwall.ingest.router import PacketRouter
from pitwall.sim.f1_stream import generate_f1_session
from pitwall.sim.scenarios import (
    AFTER_THE_LINE,
    COACHING_DEMO_STORY,
    ON_THE_SCREEN,
    WITH_THE_LAP_TIME,
    coaching_demo,
    write_synthetic_capture,
)
from pitwall.storage.db import Database, DbWriter
from pitwall.voice.proactive import lap_messages
from pitwall.voice.types import MessageKind

pytestmark = pytest.mark.synthetic

CUE = "in the lap"
AFTER = AFTER_THE_LINE

# The demo's radio at Normal intensity with nobody in the seat (lap summaries aside), in the order it is said:
# (lap, when, what it is, the line). In-lap calls belong to the lap they are called on; "after the line" lines to the
# lap just finished.
EXPECTED = [
    (4, AFTER, "announce", "T5, losing 0.23 s: braking 14 m earlier. 2 of the last 3 laps."),
    (5, CUE, "brake", "T5 brake"),
    (6, CUE, "brake", "T5 brake"),
    (7, CUE, "brake", "T5 brake"),
    (7, AFTER, "fixed", "T5 sorted: clean on 2 of the last 3 laps."),
    (8, AFTER, "announce", "T4, losing 0.09 s: minimum speed 9 km/h down. 5 of the last 5 laps."),
    (9, CUE, "reminder", "T4: apex speed, 9 down"),
    (9, AFTER, "one-off", "T2, losing 0.67 s: full throttle 31 m later than your reference."),
    (10, CUE, "reminder", "T4: apex speed, 9 down"),
]


class _SyncWorker:
    """AnalysisWorker stand-in: each lap is processed on the ingest thread, before the next frame."""

    def __init__(self, processor: LapProcessor) -> None:
        self.processor = processor

    def submit(self, job: LapJob) -> None:
        self.processor.process(job)


@dataclass
class Replay:
    live: LiveState
    radio: list[tuple[int, str, str, str]] = field(default_factory=list)  # (lap, when, what, line)
    summaries: dict[int, str] = field(default_factory=dict)
    coach: dict[int, dict[str, Any]] = field(default_factory=dict)  # lap -> its coach block
    evidence: dict[int, bool] = field(default_factory=dict)  # lap -> habit evidence
    ref_lap: dict[int, int | None] = field(default_factory=dict)  # lap -> reference lap number


def _replay(root: Path, packet_format: int, on_air: bool, intensity: str) -> Replay:
    sc = coaching_demo()
    sc.packet_format = packet_format
    packets, _truth = generate_f1_session(sc)
    db = Database(root / f"story-{packet_format}-{on_air}-{intensity}.sqlite3")
    writer = DbWriter(db)
    live = LiveState()
    live.coach.set_radio_intensity(intensity)
    if on_air:
        live.coach.commit_on_delivery(True)
    sessions = SessionManager(
        writer,
        live,
        _SyncWorker(LapProcessor(db, writer, live)),  # type: ignore[arg-type]
        source="synthetic-demo-story",
        synthetic=True,
        overrides={"scenario": "coaching-demo"},
    )
    router = PacketRouter(default_adapters(), sessions, live)
    out = Replay(live)

    def on_lap(kind: str, payload: dict[str, Any]) -> None:
        if kind != "lap":
            return
        lap, coach = payload["lap"], payload["coach"]
        n = int(lap["lap_number"])
        out.coach[n] = coach
        comparison = live.last_comparison or {}
        out.evidence[n] = comparison.get("habit_evidence") is not False
        out.ref_lap[n] = (live.reference or {}).get("lap_number")
        for m in lap_messages(lap, payload["observations"], None, live.reference, intensity, 0.0, coach=coach):
            if m.kind is MessageKind.LAP_SUMMARY:
                out.summaries[n] = m.text
                continue
            event = m.meta.get("habit_event")
            out.radio.append((n, AFTER, str(event or "one-off"), m.text))
            if on_air and event:
                assert live.habit_line_said(m.meta.get("observation_id"))  # the hub says it at once

    live.subscribe(on_lap)
    live.cues.set_mode("focus")
    live.cues.set_plan_listener(lambda _plan: live.cues.set_timing(CueTiming(latency_s=0.45)))
    live.cues.set_sink(lambda ev: out.radio.append((ev.lap, CUE, ev.cue.kind.value, ev.cue.text)))
    for p in packets:
        router.handle(p)
    router.finish()
    writer.flush()
    writer.close()
    assert live.cues.errors == 0 and live.cues.missed == 0
    return out


@pytest.fixture(scope="module")
def replays(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[int, bool, str], Replay]:
    """Each (packet format, on air, intensity) replay of the demo runs once per module, on first use."""
    root = tmp_path_factory.mktemp("demo-story")

    class _Replays(dict[tuple[int, bool, str], Replay]):
        def __missing__(self, key: tuple[int, bool, str]) -> Replay:
            rp = self[key] = _replay(root, *key)
            return rp

    return _Replays()


def _story_radio() -> list[tuple[int, str, str]]:
    """The radio lines ``COACHING_DEMO_STORY`` promises, in the order they are said: per lap, the calls before its
    corners, then the lines after its line."""
    out: list[tuple[int, int, str, str]] = []
    for b in COACHING_DEMO_STORY.beats:
        if b.radio is None:
            continue
        for lap in b.laps:
            out.append((lap, 1 if b.when == AFTER_THE_LINE else 0, b.when, b.radio))
    out.sort(key=lambda x: (x[0], x[1]))
    return [(lap, when, line) for lap, _, when, line in out]


@pytest.mark.parametrize(("packet_format", "on_air"), [(2025, False), (2025, True), (2026, False)])
def test_the_demo_radio_tells_the_habits_story_in_order(
    replays: dict[tuple[int, bool, str], Replay], packet_format: int, on_air: bool
) -> None:
    """Announce (once, with its count), braking calls, sorted, the next habit, its reminder, the big one-off."""
    rp = replays[packet_format, on_air, "normal"]
    assert rp.radio == EXPECTED
    # the story in the capture (and on Settings › System) is what the radio says, in the corners the demo shows
    story = _story_radio()
    assert [(lap, line) for lap, _when, line in story] == [(lap, line) for lap, _when, _what, line in EXPECTED]
    assert [when == AFTER_THE_LINE for _lap, when, _line in story] == [when == AFTER for _l, when, _w, _x in EXPECTED]
    befores = {b.when: b.radio for b in COACHING_DEMO_STORY.beats if b.when.startswith("before ")}
    assert befores == {"before T5": "T5 brake", "before T4": "T4: apex speed, 9 down"}  # the corner it is said at


def test_the_screen_shows_what_the_radio_leaves_out(replays: dict[tuple[int, bool, str], Replay]) -> None:
    """The small one-off (lap 6) and the braking habit's first lap (lap 3) are on the coach card as one-offs and never
    picked; flashback (lap 5) and invalid (lap 10) laps are named with the lap time, never habit laps, and the
    reference stays lap 1."""
    rp = replays[2025, False, "normal"]
    screen = {b.screen for b in COACHING_DEMO_STORY.beats if b.when == ON_THE_SCREEN}
    (small,) = screen
    point = rp.coach[6]["by_corner"]["T1"]
    assert point["short"] == small and point["one_off"] and not point["picked"] and rp.coach[6]["picked"] == []
    first = rp.coach[3]["by_corner"]["T5"]
    assert first["kind"] == "brake_early" and first["one_off"] and rp.coach[3]["picked"] == []
    assert rp.summaries[5].endswith("Flashback used.") and rp.summaries[10].endswith("That lap was invalidated.")
    (laps_note,) = [b for b in COACHING_DEMO_STORY.beats if b.when == WITH_THE_LAP_TIME]
    assert laps_note.laps == (5, 10)
    assert [n for n, ok in sorted(rp.evidence.items()) if not ok] == [5, 10]
    assert rp.ref_lap[1] is None and {rp.ref_lap[n] for n in range(2, 11)} == {1}  # lap 1 is the reference
    # where the session ends: the reminder's habit worked on, the braking habit sorted
    habits = {(h["corner"], h["kind"]): h["status"] for h in rp.coach[10]["habits"]}
    assert habits == {("T4", "low_min_speed"): "focus", ("T5", "brake_early"): "fixed"}


def test_detailed_works_on_both_habits_from_lap_four(replays: dict[tuple[int, bool, str], Replay]) -> None:
    """The story's note: at Detailed both habits are announced after lap 4, so the reminder starts on lap 5."""
    rp = replays[2025, False, "detailed"]
    announced = [(lap, line) for lap, _when, what, line in rp.radio if what == "announce"]
    assert [lap for lap, _ in announced] == [4, 4]
    assert announced[0][1] == EXPECTED[0][3] and announced[1][1].startswith("T4, losing 0.09 s: minimum speed 9")
    reminders = [lap for lap, when, what, _ in rp.radio if what == "reminder"]
    assert reminders == [5, 6, 7, 8, 9, 10]
    assert [lap for lap, _when, what, _ in rp.radio if what == "brake"] == [5, 6, 7]


def test_the_capture_carries_the_story(tmp_path: Path) -> None:
    cap = tmp_path / "demo.pwcap"
    write_synthetic_capture(cap)
    meta = CaptureReader(cap).meta
    assert meta.synthetic and meta.extra["scenario"] == "coaching-demo"
    assert meta.extra["story"] == COACHING_DEMO_STORY.to_dict()
    assert meta.extra["story"]["intro"].startswith("SYNTHETIC")
    other = tmp_path / "technique.pwcap"
    write_synthetic_capture(other, name="technique-demo")
    assert "story" not in CaptureReader(other).meta.extra  # no story promised for it
