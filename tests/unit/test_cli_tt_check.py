"""``pitwall tt-check <capture>`` (leaderboard): packet 14, the rival's times and whether the rival car's slot carries
moving telemetry ("does the game send the ghost's inputs?").

Every capture here is SYNTHETIC (``pitwall.sim.scenarios.time_trial_demo``): it exercises the check and the decoder,
and the report says so. Packet 14 is spec-decoded until a recorded Time Trial capture has been checked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pitwall import cli
from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.tt_check import (
    ANSWER_TEXT,
    CHANGE_MIN,
    INPUT_CHANNELS,
    MIN_SAMPLES,
    ChannelStats,
    TtCheckReport,
    check_time_trial,
    report_lines,
)
from pitwall.ingest.capture import CaptureMeta, write_capture
from pitwall.sim.f1_stream import F1Scenario, generate_f1_session
from pitwall.sim.scenarios import TT_DEMO_RIVAL_INDEX, time_trial_demo

runner = CliRunner()


def _write(path: Path, sc: F1Scenario) -> Path:
    packets, _truth = generate_f1_session(sc)
    meta = CaptureMeta(source="synthetic", game_hint="f1_25", synthetic=True, description="SYNTHETIC test capture")
    write_capture(path, packets, meta)
    return path


@pytest.fixture(scope="module")
def captures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("tt")
    with_inputs, without = time_trial_demo(), time_trial_demo(rival_inputs=False)
    with_inputs.laps = without.laps = 1
    return {
        "inputs": _write(d / "tt.pwcap", with_inputs),
        "ghost": _write(d / "tt-ghost.pwcap", without),
        "practice": _write(d / "practice.pwcap", F1Scenario(laps=1)),
    }


def test_rival_with_inputs(captures: dict[str, Path]) -> None:
    r = runner.invoke(cli.app, ["tt-check", str(captures["inputs"])])
    assert r.exit_code == 0, r.output
    out = r.output
    assert "SYNTHETIC capture (generated)" in out and "says nothing about what F1 25 sends" in out
    assert "session types: Time Trial (18)" in out
    assert "Rival          1:04.870  (S1 21.412  S2 22.105  S3 21.353)  McLaren, car index 1;" in out
    assert "ABS on" in out and "Personal best  1:05.904" in out
    assert f"rival (m_timeTrialRivalCarIdx): {TT_DEMO_RIVAL_INDEX} in" in out
    assert "PB ghost (m_timeTrialPBCarIdx): none (255)" in out
    for ch in INPUT_CHANNELS:
        assert any(line.split()[:2] == [ch, "changes"] for line in out.splitlines()), ch
    assert "lap distance covers 100% of the 3964 m lap" in out
    assert out.rstrip().endswith("Answer: " + ANSWER_TEXT["yes"])


def test_ghost_without_inputs(captures: dict[str, Path]) -> None:
    r = runner.invoke(cli.app, ["tt-check", str(captures["ghost"])])
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    for ch in ("speed_kph", *INPUT_CHANNELS):
        assert any(line.split()[:2] == [ch, "constant"] for line in lines), ch
    assert any(line.split()[:2] == ["lap_distance_m", "changes"] for line in lines)
    assert "Answer: " + ANSWER_TEXT["position_only"] in r.output


def test_not_a_time_trial(captures: dict[str, Path]) -> None:
    r = runner.invoke(cli.app, ["tt-check", str(captures["practice"])])
    assert r.exit_code == 0, r.output
    assert "Time Trial packets (ID 14): 0" in r.output and "rival (m_timeTrialRivalCarIdx): none (255)" in r.output
    assert "Answer: " + ANSWER_TEXT["no_time_trial"] in r.output


def test_json(captures: dict[str, Path]) -> None:
    r = runner.invoke(cli.app, ["tt-check", "--json", str(captures["inputs"])])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert (d["answer"], d["evidence"], d["synthetic"], d["truncated"]) == ("yes", "synthetic", True, False)
    assert d["time_trial_packets"] >= 60 and d["packet_formats"] == [2025] and d["session_types"] == {"18": 129}
    assert d["latest"]["rival"]["lap_time_ms"] == 64_870 and d["latest"]["rival"]["anti_lock_brakes"] is True
    assert d["latest"]["personal_best"]["lap_time_ms"] == 65_904
    assert d["rival_laps_ms"] == [64_870]
    rival = d["cars"]["rival"]
    assert rival["index"] == TT_DEMO_RIVAL_INDEX and rival["channels"]["throttle"]["verdict"] == "changes"
    assert d["cars"]["pb"]["index"] is None and d["car_indexes"]["pb"] == {"None": d["lap_data_packets"]}


def test_unreadable_capture(tmp_path: Path) -> None:
    bad = tmp_path / "x.pwcap"
    bad.write_bytes(b"not a capture")
    r = runner.invoke(cli.app, ["tt-check", str(bad)])
    assert r.exit_code == 1 and "cannot read" in r.output
    r = runner.invoke(cli.app, ["tt-check", str(tmp_path / "missing.pwcap")])
    assert r.exit_code == 1 and "cannot read" in r.output


# ---------------------------------------------------------------- the check itself
def test_garbage_is_counted_and_skipped() -> None:
    hdr = P.HEADER.pack({"packetFormat": 2025, "packetId": 14})
    rep = check_time_trial([b"", b"\x01\x02", hdr + b"\0" * 10, P.HEADER.pack({"packetFormat": 2024}) + b"\0" * 72])
    assert (rep.packets, rep.f1_packets, rep.tt_packets, rep.answer) == (4, 0, 0, "no_time_trial")
    zero = hdr + b"\0" * (101 - 29)  # a packet 14 of the right size whose sets are all zero
    rep = check_time_trial([zero])
    assert rep.tt_packets == 1 and rep.latest == (None, None, None) and rep.answer == "no_rival_car"


def _stats(values: list[float]) -> ChannelStats:
    st = ChannelStats()
    for v in values:
        st.add(v)
    return st


MOVING = [float(i % 2) for i in range(MIN_SAMPLES * 2)]  # 0, 1, 0, 1, ...: changes every sample
STILL = [0.5] * (MIN_SAMPLES * 2)


@pytest.mark.parametrize(
    ("channels", "answer"),
    [
        ({c: MOVING for c in CHANGE_MIN}, "yes"),
        ({"throttle": MOVING, "brake": STILL, "steering": STILL}, "partly"),
        ({"lap_distance_m": [100.0 * i for i in range(MIN_SAMPLES * 2)], "throttle": STILL}, "position_only"),
        ({c: STILL for c in CHANGE_MIN}, "no"),
        ({"throttle": MOVING[: MIN_SAMPLES - 1]}, "no_data"),
    ],
)
def test_answers(channels: dict[str, list[float]], answer: str) -> None:
    rep = TtCheckReport(tt_packets=1)
    rep.indexes["rival"][1] = 10
    for ch, values in channels.items():
        rep.cars["rival"][ch] = _stats(values)
    assert rep.answer == answer
    assert ANSWER_TEXT[answer] in report_lines(rep)[-1]


def test_small_or_non_finite_changes_do_not_count() -> None:
    jitter = _stats([0.001 * (i % 2) for i in range(MIN_SAMPLES * 2)])  # changes, but under 0.05 of a pedal
    assert jitter.verdict("throttle") == "constant" and jitter.changes == MIN_SAMPLES * 2 - 1
    assert _stats([float("nan")] * 50).samples == 0


def test_a_real_capture_is_labelled_spec_decoded_not_synthetic() -> None:
    lines = report_lines(TtCheckReport(synthetic=False), "x.pwcap")
    assert lines[0] == "Capture: x.pwcap" and "spec-decoded" in lines[1] and "SYNTHETIC" not in "\n".join(lines)
    assert TtCheckReport(synthetic=False).to_dict()["evidence"] == "spec_decoded"
