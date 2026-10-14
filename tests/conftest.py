from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.analysis.laps import LapAssembler, LapTrace
from pitwall.ingest.capture import CapturedPacket
from pitwall.model.telemetry import CarFrame, LapCompletion, SessionInfo
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.sim.f1_stream import F1Scenario, FlashbackSpec, GroundTruth, generate_f1_session
from pitwall.sim.scenarios import coaching_demo


@dataclass
class DecodedSession:
    packets: list[CapturedPacket]
    truth: GroundTruth
    laps: list[LapTrace]
    frames: list[CarFrame]
    info: SessionInfo
    adapter: F1Adapter


def decode_session(packets: list[CapturedPacket]) -> tuple[list[LapTrace], list[CarFrame], SessionInfo, F1Adapter]:
    adapter = F1Adapter()
    laps: list[LapTrace] = []
    frames: list[CarFrame] = []
    info: SessionInfo | None = None
    asm = LapAssembler(laps.append)
    for p in packets:
        for e in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(e, SessionInfo):
                info = e
                asm.set_track_length(e.track_length_m)
            elif isinstance(e, CarFrame):
                frames.append(e)
                asm.feed(e)
            elif isinstance(e, LapCompletion):
                asm.feed_completion(e)
    assert info is not None
    return laps, frames, info, adapter


def one_offs_scenario() -> F1Scenario:
    """Seven laps at 'Pitwall Park' with four one-off mistakes: the coaching demo before habits (v0.3.0), kept as the
    known-answer session of the tests written against it (``one_offs_session``). Design corner names, the learned
    ones in brackets:

    lap 1-2: clean, near-optimal (lap 1 is the reference)
    lap 3:   brakes 15 m early into design-T3 (T2)
    lap 4:   8 km/h low apex speed at design-T7 (T4)
    lap 5:   40 m late to full throttle out of design-T8 (T5)
    lap 6:   flashback mid-lap (lap must be excluded from references)
    lap 7:   invalidated by the game (track limits) + braking 20 m early at design-T1 (T1)

    The product demo (``pitwall.sim.scenarios.coaching_demo``, the ``demo_session`` fixture) tells the habits story
    instead. SYNTHETIC, like every generated stream."""
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


@pytest.fixture(scope="session")
def one_offs_session() -> DecodedSession:
    """``one_offs_scenario`` decoded: one-off mistakes with known answers, a flashback lap 6 and an invalid lap 7."""
    packets, truth = generate_f1_session(one_offs_scenario())
    laps, frames, info, adapter = decode_session(packets)
    return DecodedSession(packets, truth, laps, frames, info, adapter)


@pytest.fixture(scope="session")
def demo_session() -> DecodedSession:
    """The product's coaching demo (``pitwall simulate``) decoded: the habits story of ``COACHING_DEMO_STORY``."""
    packets, truth = generate_f1_session(coaching_demo())
    laps, frames, info, adapter = decode_session(packets)
    return DecodedSession(packets, truth, laps, frames, info, adapter)


@pytest.fixture(scope="session")
def clean_session() -> DecodedSession:
    packets, truth = generate_f1_session(F1Scenario(laps=3))
    laps, frames, info, adapter = decode_session(packets)
    return DecodedSession(packets, truth, laps, frames, info, adapter)


@pytest.fixture(scope="session")
def demo_session_2026() -> DecodedSession:
    sc = coaching_demo()
    sc.packet_format = 2026
    packets, truth = generate_f1_session(sc)
    laps, frames, info, adapter = decode_session(packets)
    return DecodedSession(packets, truth, laps, frames, info, adapter)


@pytest.fixture
def spec_doc() -> str:
    from pitwall.adapters.f1.spec_check import default_spec_path

    p: Path = default_spec_path()
    if not p.exists():
        pytest.skip("docs/research/f1-udp-spec.md not present")
    return p.read_text(encoding="utf-8")  # UTF-8 on every OS (Windows' locale default would garble it)


# Opt-in tiers that talk to a real game, LLM or audio device: they may need the shell's PITWALL_* settings.
_REAL_WORLD_MARKERS = ("live", "llm", "voice")


@pytest.fixture(autouse=True)
def _shell_pitwall_env_hidden(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests see the built-in defaults, not the developer's shell: a shell that moved ``PITWALL_HTTP_PORT`` off 8770
    or switched voice off (the integration rules do both) must not change what a unit test asserts, and
    ``scripts/release.sh`` runs the suite from whatever shell starts it. ``PITWALL_DATA_DIR`` is kept: it only ever
    points a stray default at a scratch folder. The opt-in live, LLM and voice tiers keep the whole environment."""
    if any(request.node.get_closest_marker(m) is not None for m in _REAL_WORLD_MARKERS):
        return
    for name in list(os.environ):
        if name.upper().startswith("PITWALL_") and name.upper() != "PITWALL_DATA_DIR":
            monkeypatch.delenv(name)


@pytest.fixture
def no_pitwall_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide ``PITWALL_*`` variables of the shell running the tests (a CI job or a developer may set some, e.g. to
    keep the LLM off), for tests that assert the built-in defaults."""
    for name in list(os.environ):
        if name.upper().startswith("PITWALL_"):
            monkeypatch.delenv(name)
