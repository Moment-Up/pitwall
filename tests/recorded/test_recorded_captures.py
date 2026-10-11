"""Recorded validation: real-game captures in tests/fixtures/recorded (skipped when none exist).

These checks are weaker than synthetic ground truth (we don't know the true values) but they are the only
evidence that the decoder copes with real game output: exact sizes, field ranges, lap structure.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall.analysis.distance import monotonic_mask
from pitwall.ingest.capture import CaptureReader
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID
from tests.conftest import decode_session

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
# AC remote-telemetry captures (game_hint 'ac-remote') have their own module: tests/recorded/test_ac_ps5_real.py
CAPTURES = sorted(p for p in FIXTURES.glob("**/*.pwcap") if CaptureReader(p).meta.game_hint != "ac-remote")

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not CAPTURES, reason="no real-game captures in tests/fixtures/recorded (see README there)"),
]


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_recorded_capture_decodes_cleanly(path: Path) -> None:
    reader = CaptureReader(path)
    assert not reader.meta.synthetic, "synthetic captures do not belong in the recorded tier"
    packets = list(reader)
    laps, frames, info, adapter = decode_session(packets)
    assert info.session_uid != str(SYNTHETIC_SESSION_UID), "this capture is a synthetic stream"
    st = adapter.stats
    assert st.errors == 0, st.last_error
    assert st.rejected <= 0.001 * st.packets, f"{st.rejected} rejected: {st.last_error}"
    for f in frames:
        assert f.speed_kph is None or 0 <= f.speed_kph <= 400
        assert f.throttle is None or 0 <= f.throttle <= 1
        assert f.brake is None or 0 <= f.brake <= 1
        assert f.steering is None or -1 <= f.steering <= 1
        assert f.gear is None or -1 <= f.gear <= 8
    for lap in laps:
        if lap.lap_time_ms is not None:
            assert 20_000 < lap.lap_time_ms < 400_000
        # Stationary samples (grid, pit box) are legitimate; going *backwards* is not, apart from a flashback
        # or the single wrap sample real F1 25 sends on the final lap before resultStatus turns 'finished'.
        d = lap.channels["distance_m"]
        backwards = (np.maximum.accumulate(np.where(np.isfinite(d), d, -np.inf)) - d) > 1.0
        assert backwards.sum() <= max(1, 0.01 * len(d)) or "flashback" in lap.flags
        assert monotonic_mask(d).sum() > 100
        assert np.nanmax(lap.channels["speed_kph"]) > 50
