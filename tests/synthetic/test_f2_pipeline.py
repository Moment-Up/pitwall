"""SYNTHETIC: an F2 session (``F1Scenario(formula=2)``) replayed end to end through the runtime -> SQLite.

The stream sends what F1 25 sent for F2 cars on the owner's PS5 (formula 2, F2 tyre compounds, 0 in every ERS field,
a 60 km/h pit limit), but it is generated data: it proves the plumbing (class, no ERS, labels, the strategy view's
stop rules, the per-family track model), never that the game behaves like this. It is flagged synthetic everywhere.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pitwall import carclass
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.model.telemetry import CarFrame, SessionInfo
from pitwall.sim.f1_stream import F1Scenario, generate_f1_session
from pitwall.sim.scenarios import write_synthetic_capture
from pitwall.storage import repo
from pitwall.strategy.engine import StrategyEngine

pytestmark = pytest.mark.synthetic


def _scenario() -> F1Scenario:
    return F1Scenario(laps=3, formula=2, team_id=158, session_type=16)  # an F2 feature race ("Race 2")


def test_f2_stream_decodes_as_an_f2_car_without_ers() -> None:
    packets, _truth = generate_f1_session(_scenario())
    a = F1Adapter(field_hz=0)
    eng = StrategyEngine("synthetic-f2")
    info: SessionInfo | None = None
    frames: list[CarFrame] = []
    for p in packets:
        for e in a.decode(p.data, p.t_recv_ns):
            eng.feed(e)
            if isinstance(e, SessionInfo):
                info = e
            elif isinstance(e, CarFrame):
                frames.append(e)
    assert a.stats.errors == 0 and a.stats.rejected == 0 and info is not None
    assert info.formula == "F2" and info.pit_speed_limit_kph == 60.0 and info.session_uid is not None
    cls = carclass.classify_info(info)
    assert cls is not None and cls.id == "f2" and cls.has_ers is False
    assert all(f.ers_store_j is None and f.ers_deploy_mode is None for f in frames)
    assert {f.tyre_compound for f in frames if f.tyre_compound} == {"soft"}
    v = eng.view()
    assert v["mode"] == "race" and v["pit"]["rules"]["race"] == "feature" and v["pit"]["rules"]["known"] is False


@pytest.fixture
def replayed(tmp_path: Path) -> Iterator[tuple[Runtime, str]]:
    cap = tmp_path / "captures" / "f2.pwcap"
    write_synthetic_capture(cap, _scenario(), name="f2-demo")
    rt = Runtime(Settings(data_dir=tmp_path, llm_enabled=False))
    r = rt.start_replay(cap, speed=None)
    assert r.done.wait(60)
    rt.worker.join()
    rt.writer.flush()
    with rt.db.read() as c:
        sid = repo.latest_session_id(c)
    assert sid
    yield rt, sid
    rt.close()


def test_replayed_f2_session_is_classified_and_flagged_synthetic(replayed: tuple[Runtime, str]) -> None:
    rt, sid = replayed
    with rt.db.read() as c:
        s = repo.get_session(c, sid)
        laps = repo.list_laps(c, sid)
        model = repo.load_track_model(c, "f1_25", "synthetic:f2-demo", "f2")
    assert s is not None and s["synthetic"] and s["track_id"] == "synthetic:f2-demo"
    fields = carclass.session_fields(s)
    assert fields["car_class"]["id"] == "f2" and fields["car_label"] == "F2 · Art GP '24"
    assert fields["session_label"] == "Feature race"
    assert [lap["lap_number"] for lap in laps] == [1, 2, 3] and all(lap["lap_time_ms"] for lap in laps)
    assert model is not None and model.car_family == "f2"  # the synthetic track model is F2's own
    assert rt.worker.errors == 0 and rt.writer.errors == 0
