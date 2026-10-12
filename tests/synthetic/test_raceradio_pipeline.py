"""SYNTHETIC tier: the race radio end to end on the scripted ``race-radio-demo`` stream (sim.raceradio_stream).

Packets -> F1Adapter -> SessionManager -> RaceRadioWorker -> the ``race_call`` / ``radio_urgent`` notes -> the radio's
own message builders (``raceradio.radio.race_message``, ``voice.urgent.urgent_message``) -> a ``RadioScheduler`` polled
on every frame with the frame's driving state, so the radio policy decides what is said when. This is the only
evidence for the safety car, the red flag, drive-throughs and stop-gos served: synthetic only, never game
compatibility (docs/status.md). The real hub with a TTS engine is covered by tests/unit/test_hub_race_calls.py.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.core.lap_processor import AnalysisWorker
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.model.telemetry import CarFrame
from pitwall.raceradio.radio import race_message
from pitwall.raceradio.worker import RACE_CALL_NOTE, RaceRadioWorker
from pitwall.sim.raceradio_stream import BRAKE_FROM_M, BRAKE_TO_M, race_radio_demo
from pitwall.storage.db import DbWriter
from pitwall.voice.scheduler import CALM_BRAKE, CALM_STEERING, RadioScheduler
from pitwall.voice.types import DrivingState, Priority
from pitwall.voice.urgent import URGENT_NOTE, urgent_message

pytestmark = pytest.mark.synthetic


class Fake:
    def __init__(self) -> None:
        self.jobs: list[Any] = []

    def submit(self, job: Any) -> None:
        self.jobs.append(job)

    def submit_ai_pace(self, job: Any) -> None:
        self.jobs.append(job)


def replay(intensity: str = "normal", quiet: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(notes, dispatched): every race radio note in stream order, and what the scheduler said when."""
    live = LiveState()
    notes: list[tuple[str, dict[str, Any]]] = []
    live.subscribe(lambda kind, payload: notes.append((kind, payload)))
    worker = RaceRadioWorker(live, start=False)
    sm = SessionManager(cast(DbWriter, Fake()), live, cast(AnalysisWorker, Fake()), source="replay:synthetic",
                        synthetic=True, race=worker)  # fmt: skip
    adapter = F1Adapter(field_hz=0.0)
    sched = RadioScheduler(intensity)
    if quiet:
        sched.set_quiet(indefinite=True)
    packets, _truth = race_radio_demo()
    seen: list[dict[str, Any]] = []
    dispatched: list[dict[str, Any]] = []
    busy_until = -1.0
    for p in packets:
        t = p.t_recv_ns / 1e9
        for item in adapter.decode(p.data, p.t_recv_ns):
            sm.handle(item)
            worker.process_pending()
            while notes:
                kind, payload = notes.pop(0)
                if kind == RACE_CALL_NOTE:
                    seen.append(payload)
                    msg = race_message(payload, t)
                elif kind == URGENT_NOTE:
                    seen.append({**payload, "call": payload["meta"]["call"], "kind": "urgent"})
                    msg = urgent_message(payload, t)
                else:
                    continue
                if msg is not None:
                    sched.enqueue(msg)
            if isinstance(item, CarFrame):
                state = DrivingState(True, item.speed_kph, item.brake, item.steering, item.lap_number,
                                     item.lap_distance_m, None)  # fmt: skip
                m = sched.next_message(state, t, t < busy_until)
                if m is not None:
                    busy_until = t + 3.0
                    dispatched.append(
                        {
                            "t": t,
                            "call": m.meta.get("call"),
                            "urgent": m.priority >= Priority.URGENT,
                            "brake": item.brake,
                            "steer": item.steering,
                            "d": item.lap_distance_m,
                            "kind": m.kind.value,
                        }
                    )
    return seen, dispatched


def test_every_scripted_call_is_made_once_tagged_synthetic() -> None:
    seen, _dispatched = replay()
    assert [c["call"] for c in seen] == [
        "grid_brief",
        "lights_out",
        "yellow_ahead",
        "lap1_summary",
        "yellow_here",
        "clean_pass",
        "penalty",
        "gap_report",
        "own_fastest_lap",
        "warning",
        "penalty",
        "position_change",
        "damage",
        "damage",
        "blue_flag",
        "penalty_served",
        "retirement",
        "laps_2",
        "sc_deployed",
        "sc_ending",
        "green",
        "last_lap",
        "red_flag",
        "finish",
    ]
    by = {c["call"]: c for c in seen}
    assert by["clean_pass"]["text"] == "Good move on Hamilton. P2."  # a clean pass, the AI driver's official name
    assert by["position_change"]["text"] == "Up to P1."  # the pass with contact: no praise
    assert [c["text"] for c in seen if c["call"] == "penalty"] == [
        "5 second penalty: cutting the track.",
        "Drive-through penalty: speeding in the pit lane.",
    ]
    assert by["damage"]["text"] == "Puncture, rear right. Box this lap."
    assert by["retirement"]["text"] == "Russell is out."  # once: the re-send after the flashback is ignored
    # the scripted 5 s penalty is still to add at the flag: the position on the road, never "P1" alone
    assert by["finish"]["text"] == "Chequered flag. P1 on the road, 5 seconds to add."
    assert all(c.get("synthetic") is True or c.get("meta", {}).get("synthetic") is True for c in seen)
    assert all(c.get("tier", c.get("meta", {}).get("tier")) == "synthetic" for c in seen)


def test_nothing_but_the_red_flag_in_a_braking_zone_and_the_policy_holds() -> None:
    _seen, dispatched = replay()
    for d in dispatched:
        in_zone = d["d"] is not None and BRAKE_FROM_M <= d["d"] <= BRAKE_TO_M
        calm = (d["brake"] or 0) < CALM_BRAKE and abs(d["steer"] or 0) < CALM_STEERING
        if not d["urgent"] and d["call"] not in ("grid_brief", "lights_out"):
            assert calm and not in_zone, d
    calls = [d["call"] for d in dispatched]
    assert "red_flag" in calls and "sc_deployed" in calls and "finish" in calls


def test_quiet_intensity_and_quiet_mode() -> None:
    _seen, quiet_intensity = replay("quiet")
    assert {d["kind"] for d in quiet_intensity} <= {"alert"}  # alerts only: no race calls at quiet intensity
    _seen, quiet_mode = replay("normal", quiet=True)
    said = {d["call"] for d in quiet_mode}
    assert {"red_flag", "sc_deployed", "penalty"} <= said  # urgent, and the bypass-quiet alerts (a drive-through)
    assert not said & {"lap1_summary", "position_change", "blue_flag", "yellow_ahead", "green", "warning"}
