"""RECORDED tier: the telemetry rig check on real F1 25 output (v1.26, PS5, UDP format 2025, Austria race).

The fixture is a byte-for-byte excerpt of four windows of a real race (see test_f1_25_ps5_austria.py), driven on
the user's rig: Fanatec GT DD Pro (5 Nm) with stock CSL Pedals (Hall-sensor brake). Assertions are limited to
facts that hold for any healthy rig and do not depend on where the excerpt windows were cut:

* no brake input at rest on full-throttle straights, the throttle returns to 0 and reaches 100%;
* the brake reaches 100% (the CSL Hall brake is travel-based, so a full press reads 1.0);
* the wheel is centred on straights and never at full lock at speed;
* on the grid (the excerpt starts with the race start, the session clock standing still while the driver revs) the
  wheel is calm: no false "session-start oscillation";
* metrics needing data pitwall does not record stay unknown (wheel slip, DRS, wheel angle, BRF history), and the
  excerpt's windows hold no complete braking event, so the braking metrics are unknown rather than guessed;
* nothing bridges the gaps between the excerpt's windows (a braking event can never span missing data).

The full race and later real sessions (data/captures, not committed) give the numbers quoted in docs/rig-setup.md.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall.analysis.laps import LapTrace
from pitwall.ingest.capture import CaptureReader
from pitwall.rig.rig_check import (
    MetricResult,
    RigCheckReport,
    brake_events,
    build_report,
    continuous_chunks,
    session_start_lap,
)
from tests.conftest import decode_session

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not FIXTURE.exists(), reason="real PS5 Austria excerpt not present"),
]


@pytest.fixture(scope="module")
def laps() -> list[LapTrace]:
    reader = CaptureReader(FIXTURE)
    assert not reader.meta.synthetic
    decoded, _frames, info, _ = decode_session(list(reader))
    assert info.track_name == "Austria"
    return decoded


@pytest.fixture(scope="module")
def report(laps: list[LapTrace]) -> RigCheckReport:
    # Every excerpt lap is flagged incomplete (gaps between windows), so the check runs on all of them: pedal and
    # steering inputs inside each window are genuine. The rig had the stock Hall-sensor CSL Pedals.
    return build_report(
        laps,
        session={"id": "excerpt", "game": "f1_25", "track_name": "Austria"},
        lap_policy="usable",
        pedals="csl",
    )


def known(m: MetricResult) -> float:
    assert m.value is not None, m.reason_unknown
    return m.value


def test_real_pedals_read_zero_at_rest_and_reach_full_range(laps: list[LapTrace], report: RigCheckReport) -> None:
    at_rest = report.metric("brake_at_rest_max")
    assert known(at_rest) < 0.5 and at_rest.samples > 300  # % of full brake
    assert known(report.metric("throttle_at_rest_min")) < 0.5
    assert known(report.metric("throttle_peak_straights")) >= 99.0
    assert max(float(np.nanmax(lap.channels["brake"])) for lap in laps) >= 0.99
    assert report.sample_rate_hz == pytest.approx(60.0, rel=0.02)
    assert len(report.metrics) == 19 and report.pedals == "csl"


def test_real_wheel_is_centred_and_not_at_lock(report: RigCheckReport) -> None:
    assert known(report.metric("steer_centre_offset")) < 1.0
    assert known(report.metric("steer_full_lock_share")) == 0.0


def test_real_grid_is_not_a_session_start_oscillation(laps: list[LapTrace], report: RigCheckReport) -> None:
    start = session_start_lap(laps)
    assert start is not None and start.lap_number == 1
    t = start.channels["session_time_s"]
    assert np.count_nonzero(t == t[0]) > 300  # the session clock stands still on the grid: time counted in samples
    m = report.metric("session_start_oscillation")
    assert m.status == "pass" and known(m) == 0.0 and m.samples > 120  # more than 2 s of grid checked


def test_unrecorded_data_stays_unknown(report: RigCheckReport) -> None:
    for name in ("lockup_at_full_brake_share", "drs_drop_light_brake", "steer_roadwheel_linearity"):
        m = report.metric(name)
        assert m.status == "unknown" and m.value is None and m.reason_unknown
    history = report.metric("brake_peak_vs_history")
    assert history.status == "unknown" and "Hall" in (history.reason_unknown or "")
    # the windows are cut around the start/finish line, so no braking zone is complete: unknown, not guessed
    for name in ("brake_peak_heavy_zones", "brake_peak_drift_session", "brake_reapply_count", "brake_hold_noise"):
        assert report.metric(name).status == "unknown"


def test_excerpt_gaps_are_never_bridged(laps: list[LapTrace], report: RigCheckReport) -> None:
    assert all(len(continuous_chunks(lap.channels["session_time_s"])) >= 2 for lap in laps[1:])
    for lap in laps:
        assert all(e.duration_s < 10.0 for e in brake_events(lap))
    for name in ("trail_brake_duration_s", "brake_time_to_peak_s"):
        v = report.metric(name).value
        assert v is None or v < 5.0
