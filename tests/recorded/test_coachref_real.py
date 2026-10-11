"""coachref on real recorded laps: ``scripts/coachref_check.py``'s invariants (braking calls never later than the
driver's own point, wording, drills, the assist fallback) on every committed F1 capture with at least three clean
laps. None of today's committed excerpts has a complete lap, so this module skips; a future full-lap fixture is
picked up automatically. The owner's full local captures are checked with the script itself (docs/status.md)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from pitwall.ingest.capture import CaptureReader

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "recorded"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("coachref_check", ROOT / "scripts" / "coachref_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("coachref_check", mod)
    spec.loader.exec_module(mod)
    return mod


CHECK = _script()


def _full_lap_captures() -> list[Path]:
    out = []
    for p in sorted(FIXTURES.glob("**/*.pwcap")):
        if CaptureReader(p).meta.game_hint == "ac-remote":
            continue
        decoded = CHECK.decode_f1(p)
        if decoded is not None and sum(1 for lap in decoded[0] if lap.clean and lap.lap_time_ms) >= 3:
            out.append(p)
    return out


CAPTURES = _full_lap_captures()

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not CAPTURES, reason="no committed capture with three clean laps (see tests/fixtures/recorded)"),
]


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_coachref_invariants_on_real_laps(path: Path) -> None:
    rep = CHECK.check_capture(path)
    assert rep.skipped is None, rep.skipped
    assert rep.failures == [], "\n".join(rep.lines)
