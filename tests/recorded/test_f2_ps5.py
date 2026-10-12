"""RECORDED tier: F2 cars in F1 25 on the owner's PS5 (F1 25 v1.26, UDP format 2025, 2026-10-11).

Fixtures (byte-for-byte excerpts, ``scripts/excerpt_capture.py``; names scrubbed with ``scripts/scrub_capture.py``):

* ``f1_25_2025_ps5_f2_one-shot-quali-line-excerpt.pwcap`` (20261011-224147, 571.6-579.0 s and 737.0-745.0 s): Sakhir
  one-shot qualifying in the Art GP '24 (team 158): the session start, then the line crossing (lap 1 -> 2, the lap's
  time 1:56.133) and the result turning "finished" 17 ms later with the last-lap time unchanged. Pitwall stored that
  as a second, one-sample "lap 2" until the fix: exactly one lap now.
* ``f1_25_2025_ps5_f2_jeddah_race-excerpt.pwcap`` (20261011-224147, 3228.1-3236.0 s, 3356.5-3359.0 s,
  3427.5-3429.5 s): Jeddah feature race ("Race 2"): the start, the DRS enabled event, DRS allowed for a moment. Every
  ERS and hybrid field of every car is 0; the tyre sets are F2 compounds (actual 11 / 13 / 15, visual 19 / 21 / 15);
  the pit speed limit is 60 km/h.
* ``f1_25_2025_ps5_f2_melbourne_gp-excerpt.pwcap`` (20261011-011513, 100.0-101.0 s and 136.5-146.0 s): a Grand Prix
  race in a 2025 F2 car: the player's team id 214 and the 22-car field on ids 209-219 (two cars each), which EA's
  F1 25 document does not list (docs/research/f1-udp-spec.md section 10, item 19).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from pitwall import carclass
from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.analysis.laps import LapAssembler, LapTrace
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.model.telemetry import CarFrame, Emitted, GameEvent, LapCompletion, SessionInfo, TyreSetsInfo
from pitwall.strategy.engine import StrategyEngine

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
ONE_SHOT = FIXTURES / "f1_25_2025_ps5_f2_one-shot-quali-line-excerpt.pwcap"
JEDDAH = FIXTURES / "f1_25_2025_ps5_f2_jeddah_race-excerpt.pwcap"
MELBOURNE = FIXTURES / "f1_25_2025_ps5_f2_melbourne_gp-excerpt.pwcap"

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(
        not (ONE_SHOT.exists() and JEDDAH.exists() and MELBOURNE.exists()), reason="real PS5 F2 excerpts absent"
    ),
]


def _packets(path: Path) -> list[CapturedPacket]:
    reader = CaptureReader(path)
    assert not reader.meta.synthetic
    return list(reader)


def _decode(path: Path, **kw: Any) -> tuple[F1Adapter, list[Emitted]]:
    a = F1Adapter(**kw)
    out: list[Emitted] = []
    for p in _packets(path):
        out += a.decode(p.data, p.t_recv_ns)
    return a, out


def _last_info(items: list[Emitted]) -> SessionInfo:
    infos = [e for e in items if isinstance(e, SessionInfo)]
    assert infos
    return infos[-1]


def test_one_shot_qualifying_stores_one_lap() -> None:
    a, items = _decode(ONE_SHOT, field_hz=0, timing_hz=0)
    info = _last_info(items)
    assert (info.formula, info.car_id, info.session_type_raw, info.pit_speed_limit_kph) == (
        "F2",
        "f1:team:158",
        "One-Shot Qualifying",
        60.0,
    )
    done = [e for e in items if isinstance(e, LapCompletion)]
    assert [(c.lap_number, c.lap_time_ms) for c in done] == [(1, 116_133)]  # never a second "lap 2"
    assert a.stats.by_type.get("LAP_FINAL_WITHOUT_NEW_TIME") == 1 and a.stats.rejected == 0
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=info.track_length_m)
    for e in items:
        if isinstance(e, CarFrame):
            asm.feed(e)
        elif isinstance(e, LapCompletion):
            asm.feed_completion(e)
    asm.flush()
    assert [(lap.lap_number, lap.lap_time_ms) for lap in laps if lap.lap_time_ms] == [(1, 116_133)]
    # known gap (docs/status.md): the result turns "finished" after the completion, so the lap is not tagged final
    assert done[0].final is False
    cls = carclass.classify_info(info)
    assert cls is not None and cls.id == "f2" and carclass.info_fields(info)["car_label"] == "F2 · Art GP '24"


def test_jeddah_feature_race_has_no_ers_and_sends_drs_and_f2_compounds() -> None:
    raw_ers = 0
    for p in _packets(JEDDAH):
        d = p.data
        if len(d) == P.LAYOUTS[2025].sizes[P.PacketId.CAR_STATUS] and d[6] == P.PacketId.CAR_STATUS:
            L = P.LAYOUTS[2025]
            for i in range(L.max_cars):
                st = L.car_status.unpack_from(d, P.HEADER.size + i * L.car_status.size)
                for k in ("ersStoreEnergy", "ersDeployMode", "enginePowerMGUK", "ersDeployedThisLap"):
                    raw_ers += st[k] != 0
                raw_ers += st["ersHarvestedThisLapMGUK"] != 0 or st["ersHarvestedThisLapMGUH"] != 0
    assert raw_ers == 0  # the game sends 0 in every ERS / hybrid field of every F2 car
    _a, items = _decode(JEDDAH)
    info = _last_info(items)
    assert info.formula == "F2" and info.pit_speed_limit_kph == 60.0 and info.session_type_raw == "Race 2"
    assert carclass.info_fields(info)["session_label"] == "Feature race"
    frames = [e for e in items if isinstance(e, CarFrame)]
    after = [f for f in frames if f.t_recv_ns > info.t_recv_ns]
    assert after and all(f.ers_store_j is None and f.ers_deploy_mode is None for f in after)
    # allowed for a moment, recorded (None: telemetry before the first CarStatus packet of the excerpt)
    assert {f.drs_allowed for f in frames} - {None} == {True, False}
    events = [e.code for e in items if isinstance(e, GameEvent)]
    assert "DRSE" in events and "LGOT" in events
    sets = [e for e in items if isinstance(e, TyreSetsInfo)]
    assert sets
    seen = Counter((s.actual, s.visual) for t in sets for s in t.sets if s.actual is not None)
    assert set(seen) == {("super_soft", "super_soft"), ("medium", "medium"), ("wet", "wet")}
    tyres = {f.tyre_compound for f in frames if f.tyre_compound}
    assert tyres == {"super_soft"}
    # the strategy view: DRS enabled after the event, and the race's stop rules (never known) with the F2 note
    eng = StrategyEngine("jeddah")
    for e in items:
        eng.feed(e)
    v = eng.view()
    assert v["mode"] == "race" and v["drs_enabled"] is True
    assert v["pit"]["rules"]["race"] == "feature" and v["pit"]["rules"]["known"] is False
    assert v["pit"]["rules"]["class_note"].startswith("In real F2 the feature race needs one pit stop")


def test_melbourne_grand_prix_f2_field_is_on_ids_209_to_219() -> None:
    teams: Counter[int] = Counter()
    player_team = None
    for p in _packets(MELBOURNE):
        d = p.data
        L = P.LAYOUTS[2025]
        if len(d) == L.sizes[P.PacketId.PARTICIPANTS] and d[6] == P.PacketId.PARTICIPANTS:
            h = P.HEADER.unpack_from(d)
            n = P.PARTICIPANTS_HEAD.unpack_from(d, P.HEADER.size)["numActiveCars"]
            rows = [
                L.participant.unpack_from(d, P.HEADER.size + P.PARTICIPANTS_HEAD.size + i * L.participant.size)
                for i in range(n)
            ]
            teams = Counter(r["teamId"] for r in rows)
            player_team = rows[h["playerCarIndex"]]["teamId"]
    assert player_team == 214 and set(teams) == set(range(209, 220)) and set(teams.values()) == {2}
    _a, items = _decode(MELBOURNE, field_hz=0, timing_hz=0)
    info = _last_info(items)
    assert (info.car_id, info.car_name, info.formula, info.session_type_raw) == (
        "f1:team:214",
        "Unknown team (id 214)",  # the adapter keeps the spec's neutral fallback
        "F2",
        "Race",
    )
    labels = carclass.info_fields(info)
    assert labels["car_label"] == "F2 · Hitech '25" and labels["session_label"] == "Sprint race"
    assert labels["car_class"]["id"] == "f2" and labels["car_class"]["has_ers"] is False


def test_the_owners_f2_setups_fit_the_f2_ranges() -> None:
    """The F2 ranges come from F2 setups only; the owner's own F2 setups (CarSetups packet) all fit inside them."""
    from pitwall.carsetup.catalog import load_catalog
    from pitwall.model.telemetry import CarSetup

    cat = load_catalog()
    seen = 0
    for path in (ONE_SHOT, JEDDAH, MELBOURNE):
        _a, items = _decode(path, field_hz=0, timing_hz=0)
        for s in (e for e in items if isinstance(e, CarSetup)):
            for key, param in s.parameters.items():
                p = cat.param(key)
                rng = cat.range("f2", key)
                if p is None or rng is None:
                    continue  # engine braking, ballast, fuel load: not setup-sheet items
                v = p.menu_value(param.value)
                assert rng.contains(v) and rng.on_step(v), (path.name, key, v)
                seen += 1
    assert seen >= 20
