"""RECORDED tier: pace vs AI difficulty on real F1 25 telemetry (PS5, v1.26, UDP format 2025).

Committed fixtures: the Austria race excerpt (four windows of a 3-lap race, F1 World, AI difficulty 35) and the Monza
race excerpt (lap-3 window only). Opt-in acceptance on the owner's full captures (never committed): set
``PW_AIPACE_REAL_CAPTURES`` to a folder holding them (the name must not start with ``PITWALL_``: the test setup strips
those). The expected values are the design's real-data table (docs: pace vs AI); the driver's best is Pitwall's own
stored best clean lap.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.analysis.ai_pace import resolve_difficulty
from pitwall.config import Settings
from pitwall.core.ai_pace import collect_capture
from pitwall.core.runtime import Runtime
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import CarLapHistory, SessionInfo
from pitwall.storage import repo

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "recorded"
AUSTRIA = FIXTURES / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
MONZA = FIXTURES / "f1_25_2025_ps5_monza_race-excerpt.pwcap"
PLAYER = 19  # the player's slot in the Austria race (Participants: 19 AI cars in slots 0-18)

pytestmark = pytest.mark.recorded


def _decode(path: Path) -> tuple[list[SessionInfo], dict[int, CarLapHistory], dict[tuple[int, int], int], F1Adapter]:
    """Session infos, each car's latest lap list and every LapData lap transition (car, lap) -> lastLapTimeInMS."""
    adapter = F1Adapter(field_hz=0)
    infos: list[SessionInfo] = []
    hist: dict[int, CarLapHistory] = {}
    transitions: dict[tuple[int, int], int] = {}
    prev: dict[int, int] = {}
    reader = CaptureReader(path)
    assert not reader.meta.synthetic
    for pkt in reader:
        for e in adapter.decode(pkt.data, pkt.t_recv_ns):
            if isinstance(e, SessionInfo):
                infos.append(e)
            elif isinstance(e, CarLapHistory):
                hist[e.car_index] = e
        if len(pkt.data) == P.LAYOUT_2025.sizes[P.PacketId.LAP_DATA] and pkt.data[6] == P.PacketId.LAP_DATA:
            for i in range(P.MAX_CARS):
                lap = P.LAP_DATA.unpack_from(pkt.data, P.HEADER.size + i * P.LAP_DATA.size)
                n = lap["currentLapNum"]
                if i in prev and n == prev[i] + 1 and lap["lastLapTimeInMS"]:
                    transitions[(i, prev[i])] = lap["lastLapTimeInMS"]
                prev[i] = n
    return infos, hist, transitions, adapter


@pytest.mark.skipif(not AUSTRIA.exists(), reason="real PS5 Austria excerpt absent")
def test_austria_excerpt_difficulty_ai_flags_and_history() -> None:
    infos, hist, transitions, adapter = _decode(AUSTRIA)
    known = [i.ai_difficulty for i in infos if i.ai_difficulty is not None]
    assert known and set(known) == {35}
    counts: dict[int, int] = {}
    for v in known:
        counts[v] = counts.get(v, 0) + 1
    assert resolve_difficulty(counts) == (35, "known")
    assert all(i.ai_difficulty in (None, 35) for i in infos)  # an unfilled tail never reads as level 0
    assert all(i.network_game is False and i.extra["game_mode"] == 4 for i in infos if i.ai_difficulty is not None)
    flags = adapter._ai_flags_raw
    assert sum(1 for f in flags[:PLAYER] if f is True) == 19 and flags[PLAYER] is False
    assert sorted(hist) == list(range(20))  # every car's lap list decodes
    assert hist[PLAYER].is_player and all(hist[c].ai_controlled is True for c in range(PLAYER))
    compared = 0
    for (car, n), ms in transitions.items():
        laps = hist[car].laps
        if n <= len(laps) and laps[n - 1].lap_time_ms is not None:
            assert laps[n - 1].lap_time_ms == ms, (car, n)
            compared += 1
    assert compared >= 19  # the game's own lap list agrees with LapData on every lap seen in both


@pytest.mark.skipif(not MONZA.exists(), reason="real PS5 Monza excerpt absent")
def test_monza_excerpt_has_too_few_representative_ai_laps(tmp_path: Path) -> None:
    rt = Runtime(Settings(_env_file=None, data_dir=tmp_path, llm_enabled=False, voice_enabled=False))  # type: ignore[call-arg]
    try:
        r = rt.start_replay(MONZA, speed=None)
        assert r.done.wait(120)
        rt.worker.join()
        rt.writer.flush()
        with rt.db.read() as c:
            sid = repo.latest_session_id(c)
            assert sid
            a = repo.get_session_ai_pace(c, sid)
            s = repo.get_session(c, sid)
    finally:
        rt.close()
    assert s is not None and s["ai_difficulty"] == 35
    assert a is not None and a["status"] == "too_few_ai_cars" and a["ai_ref_ms"] is None and a["ai_difficulty"] == 35
    assert a["excluded"] == {"race_lap_1": 19, "not_observed": 19}  # the window starts in lap 3


@pytest.mark.skipif(not AUSTRIA.exists(), reason="real PS5 Austria excerpt absent")
def test_backfill_collects_the_same_inputs() -> None:
    (job,) = collect_capture(AUSTRIA)
    assert job.ai_difficulty == 35 and job.final and len(job.histories) == 20 and job.car_class == "F1 World"


# ---------------------------------------------------------------------------------------------- opt-in: full captures
REAL_DIR = os.environ.get("PW_AIPACE_REAL_CAPTURES")
# game session UID -> expected (design table): status, difficulty, ai_ref, ai_best, p25, p75, ai_cars, ai_laps, excluded
EXPECTED: dict[str, tuple[Any, ...]] = {
    "10376571985058302815": ("ok", 35, 74_579, 72_730, 73_802, 75_516, 19, 38, {"race_lap_1": 19}),  # Austria
    # Silverstone: p25 is 95_626.5 (printed "1:35.626" in the design table), stored half up
    "10484264066372284569": ("ok", 35, 96_422, 94_249, 95_627, 96_847, 19, 38, {"race_lap_1": 19}),
    "14715103996819411055": (  # Monza, the capture starts in lap 2
        "too_few_ai_cars",
        35,
        None,
        None,
        None,
        None,
        3,
        3,
        {"race_lap_1": 19, "not_observed": 19, "timing_inconsistent": 16},
    ),
    "1042067171392571216": (  # Melbourne, F2: the results fill-in caught by timing
        "ok",
        35,
        98_807,
        97_396,
        98_651,
        98_915,
        21,
        22,
        {"race_lap_1": 21, "timing_inconsistent": 20},
    ),
    "10888533858520381703": (  # Austria 71-lap scenario from lap 62
        "ok",
        31,
        75_489,
        73_159,
        75_060,
        75_917,
        17,
        119,
        {"not_observed": 94, "pit_in_out": 2, "flashback": 19, "timing_inconsistent": 15},
    ),
    "5898558813253896417": (  # the same scenario, restarted
        "ok",
        31,
        75_459,
        73_228,
        75_011,
        75_903,
        17,
        117,
        {"not_observed": 94, "pit_in_out": 2, "flashback": 19, "timing_inconsistent": 16},
    ),
    "15101521888722876682": ("too_few_ai_cars", 41, None, None, None, None, 0, 0, {}),  # online one-shot quali
    "7834815583073984766": ("too_few_ai_cars", 41, None, None, None, None, 1, 4, {"race_lap_1": 1}),  # online race
}
CAPTURES = (
    "20261010-191501_udp20777.pwcap",
    "20261010-203637_udp20777.pwcap",
    "20261010-205007_udp20777.pwcap",
    "20261011-011513_udp20777.pwcap",
    "20261010-221749_udp20777.pwcap",
    "20261010-225601_udp20777.pwcap",
)


@pytest.fixture(scope="module")
def real_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Runtime]:
    if not REAL_DIR:
        pytest.skip("set PW_AIPACE_REAL_CAPTURES to a folder of the owner's full captures (opt-in)")
    folder = Path(REAL_DIR)
    missing = [n for n in CAPTURES if not (folder / n).exists()]
    if missing:
        pytest.skip(f"captures missing: {missing}")
    rt = Runtime(
        Settings(_env_file=None, data_dir=tmp_path_factory.mktemp("real"), llm_enabled=False, voice_enabled=False)  # type: ignore[call-arg]
    )
    try:
        for name in CAPTURES:
            r = rt.start_replay(folder / name, speed=None)
            assert r.done.wait(600)
            rt.worker.join()
            rt.writer.flush()
        yield rt
    finally:
        rt.close()


def test_real_captures_match_the_design_table(real_db: Runtime) -> None:
    with real_db.db.read() as c:
        sessions = repo.list_sessions(c, 100)
        rows = {s["game_session_uid"]: (s, repo.get_session_ai_pace(c, s["id"])) for s in sessions}
    assert set(EXPECTED) <= set(rows)
    for uid, (status, diff, ref, best, p25, p75, cars, laps, excluded) in EXPECTED.items():
        s, a = rows[uid]
        assert a is not None, uid
        got = (a["status"], a["ai_difficulty"], a["ai_ref_ms"], a["ai_best_ms"], a["ai_p25_ms"], a["ai_p75_ms"])
        assert got == (status, diff, ref, best, p25, p75), uid
        assert (a["ai_cars"], a["ai_laps"], a["excluded"]) == (cars, laps, excluded), uid
        assert s["ai_difficulty"] == diff, uid
        assert a["driver_best_ms"] == s["best_clean_ms"], uid  # Pitwall's own stored best clean lap
    gaps = {uid: (rows[uid][1] or {}).get("gap_ms") for uid in EXPECTED}
    assert gaps["10376571985058302815"] == 3772 and gaps["10484264066372284569"] == 7397
    assert gaps["1042067171392571216"] == -3219
    assert gaps["10888533858520381703"] == -3744 and gaps["5898558813253896417"] == -4910
