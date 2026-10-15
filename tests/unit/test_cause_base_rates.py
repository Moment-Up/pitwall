"""scripts/cause_base_rates.py, the base-rate check behind each cause's ``[[cause.measured]]`` and ``discriminates``
(docs/knowledge.md): what counts as measurable, how corner-laps are split between a fault's and the others, and that
the TOML it prints loads as the graph's own base-rate checks.

The laps are the SYNTHETIC coaching demo (``demo_session``): this proves the counting against the analysis Review
reads, never a base rate (the script refuses a synthetic capture; the recorded checks are in causes.toml).
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.knowledge.graph import Cause, Discriminator, Signal, TechniqueGraph, load_graph
from pitwall.storage.db import Database, DbWriter
from tests.coachref_support import copy_lap, lap_ctx, new_session
from tests.conftest import DecodedSession

pytestmark = pytest.mark.synthetic

ROOT = Path(__file__).resolve().parents[2]


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("cause_base_rates", ROOT / "scripts" / "cause_base_rates.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cause_base_rates"] = mod  # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


def _cause(*discs: Discriminator) -> Cause:
    return Cause(
        id="c", name="C", summary="s", tier="expert", sources=(), explains=("low_min_speed",), discriminators=discs
    )


def test_evidence_is_measurable_only_when_its_signals_were_measured() -> None:
    """Every need = "all" signal measured and, with need = "any" ones, one of those: otherwise the corner-lap is
    neither for nor against the cause."""
    mod = _script()
    g = load_graph()
    brake = Discriminator(signal="brake_point_delta_m", test="earlier", op="le", value=-8.0, need="any")
    entry = Discriminator(signal="entry_speed_delta_kph", test="slower", op="le", value=-4.0)
    c = _cause(brake, entry)

    def reader(values: dict[str, object]) -> Any:
        return lambda s: values.get(s.id) if isinstance(s, Signal) else None

    assert mod.evaluate(g, c, reader({"brake_point_delta_m": -12.0, "entry_speed_delta_kph": -6.0})) == (True, True)
    assert mod.evaluate(g, c, reader({"brake_point_delta_m": -2.0, "entry_speed_delta_kph": -6.0})) == (True, False)
    assert mod.evaluate(g, c, reader({"brake_point_delta_m": -12.0})) == (False, False)  # the entry: unmeasured
    assert mod.evaluate(g, c, reader({"entry_speed_delta_kph": -6.0})) == (False, False)  # no braking: no any-signal


@pytest.fixture(scope="module")
def tally(tmp_path_factory: pytest.TempPathFactory, demo_session: DecodedSession) -> tuple[Any, TechniqueGraph]:
    mod = _script()
    db = Database(tmp_path_factory.mktemp("base-rate") / "p.sqlite3")
    writer = DbWriter(db)
    proc = LapProcessor(db, writer, LiveState())
    sid = new_session(writer, None, demo_session.info, "s-base-rate")
    try:
        for lap in demo_session.laps:
            proc.process(LapJob(sid, copy_lap(lap), lap_ctx(demo_session.info)))
    finally:
        writer.close()
    sa = SessionAnalyzer(db).analyse(sid)
    assert sa is not None
    g = load_graph()
    t = mod.Tally()
    mod.count_session(sa, g, t)
    return t, g


def test_every_live_pair_is_counted_and_the_counts_add_up(tally: tuple[Any, TechniqueGraph]) -> None:
    t, g = tally
    mod = _script()
    pairs = {(c.id, f.id) for c, f in mod.live_pairs(g)}
    assert set(t.pairs) == pairs
    assert ("released_too_early_for_apex", "stepped_throttle") not in pairs  # a planned fault never fires
    assert t.sessions == 1 and t.laps > 0 and t.corner_laps > 0
    for pc in t.pairs.values():
        assert pc.fault_laps + pc.other_laps + pc.unmeasured == t.corner_laps, pc
        assert 0 <= pc.fault_held <= pc.fault_laps and 0 <= pc.other_held <= pc.other_laps
        assert pc.named <= pc.fault_held  # named = its conditions held too, on the fault's own points
    # the demo has low minimum speed points, and the entry speed is measured at every corner
    ob = t.pairs[("over_braking", "low_min_speed")]
    assert ob.fault_laps > 0


def test_the_printed_checks_load_as_the_graphs_own(tally: tuple[Any, TechniqueGraph]) -> None:
    t, _ = tally
    mod = _script()
    text = mod.toml_blocks(t, "2026-10-15", "pitwall_cause_base_rate")
    rows = tomllib.loads(text.replace("[[cause.measured]]", "[[measured]]"))["measured"]
    assert len(rows) == len(t.pairs)
    for row, pc in zip(rows, t.pairs.values(), strict=True):
        assert row == {
            "fault": pc.fault,
            "fault_laps": pc.fault_laps,
            "fault_held": pc.fault_held,
            "other_laps": pc.other_laps,
            "other_held": pc.other_held,
            "date": "2026-10-15",
            "source": "pitwall_cause_base_rate",
        }
    table = mod.table(t)
    assert table.splitlines()[0].split()[:2] == ["cause", "fault"] and len(table.splitlines()) == len(t.pairs) + 1


def test_a_synthetic_capture_is_refused(tmp_path: Path) -> None:
    from pitwall.ingest.capture import CaptureMeta, CaptureWriter

    mod = _script()
    cap = tmp_path / "synthetic.pwcap"
    with CaptureWriter(cap, CaptureMeta(synthetic=True)) as w:
        w.write(0, 20777, b"\x00" * 4)
    with pytest.raises(SystemExit, match="SYNTHETIC"):
        mod.replay(cap, tmp_path)
