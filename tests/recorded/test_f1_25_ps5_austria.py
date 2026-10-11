"""RECORDED tier: real F1 25 (v1.26, PS5, UDP format 2025) output from a 3-lap Austria race.

The fixture is a byte-for-byte excerpt (``scripts/excerpt_capture.py``) of four windows: standing start,
lap 1->2, lap 2->3 and the chequered flag. Expected values are the game's own timing, cross-checked
(sector splits sum to the lap time), not values produced by Pitwall. Gaps between windows are excerpt
artefacts, so every lap is legitimately flagged ``incomplete`` here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.adapters.f1.packets import HEADER, PACKET_SIZES, PacketId
from pitwall.analysis.laps import LapFlag
from pitwall.analysis.track_skeleton import TIER_GAME_NATIVE, build_track_skeleton, skeleton_from_session_row
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.model.telemetry import CarFrame, FrameQuality, Game, LapCompletion, SessionInfo, SessionType
from tests.conftest import decode_session

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not FIXTURE.exists(), reason="real PS5 Austria excerpt not present"),
]

# (lap, lap time, sector 1, sector 2, sector 3) as reported by the game.
GAME_TIMING = [
    (1, 88_524, 24_742, 38_485, 25_297),
    (2, 78_351, 18_494, 35_484, 24_373),
    (3, 88_352, 21_734, 42_582, 24_036),
]


@pytest.fixture(scope="module")
def packets() -> list[CapturedPacket]:
    reader = CaptureReader(FIXTURE)
    assert not reader.meta.synthetic
    return list(reader)


def test_every_packet_matches_the_published_size(packets: list[CapturedPacket]) -> None:
    seen: set[int] = set()
    for p in packets:
        h = HEADER.unpack_from(p.data, 0)
        assert h["packetFormat"] == 2025
        pid = PacketId(h["packetId"])
        seen.add(pid)
        assert len(p.data) == PACKET_SIZES[pid], pid.name
    assert {PacketId.MOTION, PacketId.LAP_DATA, PacketId.CAR_TELEMETRY, PacketId.CAR_STATUS} <= seen


def test_session_identity(packets: list[CapturedPacket]) -> None:
    _laps, _frames, info, adapter = decode_session(packets)
    assert info.game is Game.F1_25 and info.track_name == "Austria" and info.track_length_m == 4323.0
    assert info.session_type is SessionType.RACE
    assert adapter.stats.rejected == 0 and adapter.stats.errors == 0


def test_lap_completions_match_game_timing(packets: list[CapturedPacket]) -> None:
    adapter = F1Adapter()
    done = [e for p in packets for e in adapter.decode(p.data, p.t_recv_ns) if isinstance(e, LapCompletion)]
    got = [(c.lap_number, c.lap_time_ms, *c.sector_times_ms) for c in done]
    assert got == GAME_TIMING
    for _lap, total, s1, s2, s3 in GAME_TIMING:
        assert s1 + s2 + s3 == total


def test_standing_start_begins_past_the_line_and_waits_on_the_grid(packets: list[CapturedPacket]) -> None:
    laps, _frames, _info, _ = decode_session(packets)
    lap1 = next(lap for lap in laps if lap.lap_number == 1)
    assert LapFlag.STANDING_START in lap1.flags
    d, v = lap1.channels["distance_m"], lap1.channels["speed_kph"]
    assert 120 < d[0] < 145  # Austria's grid slot is ~132 m beyond the timing line
    stationary = (np.abs(d - d[0]) < 0.01) & (v < 1)
    assert stationary.sum() > 60  # > 1 s at 60 Hz waiting for the lights


def test_final_lap_finishes_on_result_status_and_cool_down_is_not_racing(packets: list[CapturedPacket]) -> None:
    adapter = F1Adapter()
    frames = [e for p in packets for e in adapter.decode(p.data, p.t_recv_ns) if isinstance(e, CarFrame)]
    finish = next(i for i, f in enumerate(frames) if f.quality & FrameQuality.NOT_RACING)
    assert all(f.lap_number == 3 for f in frames[finish - 5 : finish])
    assert all(f.quality & FrameQuality.NOT_RACING for f in frames[finish:])
    # Real quirk: lap distance wraps to ~0 one frame *before* resultStatus changes; analysis drops it.
    wrapped = frames[finish - 1].lap_distance_m
    assert wrapped is not None and wrapped < 5


# ---------------------------------------------------------------- track skeleton (L0a), as the game reported it
# Observed in every populated Session packet of this capture (F1 25 v1.26, PS5, format 2025, Red Bull Ring id 17).
# These are the game's own values, recorded here as evidence - not pitwall estimates and not official FIA data.
AUSTRIA_LENGTH_M = 4323.0
AUSTRIA_S2_M = 1203.962
AUSTRIA_S3_M = 2934.932
AUSTRIA_MARSHAL_STARTS = (  # game array order: zone 0 starts before the line and wraps through it
    0.99083,
    0.07919,
    0.12787,
    0.21679,
    0.29541,
    0.34436,
    0.42118,
    0.54229,
    0.59218,
    0.67170,
    0.74759,
    0.80075,
    0.90689,
)


def _session_infos(packets: list[CapturedPacket]) -> list[SessionInfo]:
    adapter = F1Adapter()
    return [e for p in packets for e in adapter.decode(p.data, p.t_recv_ns) if isinstance(e, SessionInfo)]


def test_session_skeleton_as_observed(packets: list[CapturedPacket]) -> None:
    infos = _session_infos(packets)
    unpopulated = [i for i in infos if i.track_zones is not None and i.track_zones.marshal_zones is None]
    populated = [i for i in infos if i.track_zones is not None and i.track_zones.marshal_zones is not None]
    # Real quirk: the first Session packets (before the session clock runs) carry numMarshalZones = 0. The adapter
    # keeps that unknown (None) instead of claiming the circuit has no marshal zones.
    assert len(unpopulated) == 2 and infos[: len(unpopulated)] == unpopulated
    assert len(populated) == len(infos) - 2
    assert len({i.track_zones.geometry_key() for i in populated if i.track_zones}) == 1  # static all race
    info = populated[-1]
    z = info.track_zones
    assert z is not None and z.source == "f1_session@2025"
    assert info.track_length_m == AUSTRIA_LENGTH_M and info.pit_speed_limit_kph == 80
    assert z.sector2_start_m == pytest.approx(AUSTRIA_S2_M, abs=1e-3)
    assert z.sector3_start_m == pytest.approx(AUSTRIA_S3_M, abs=1e-3)
    assert z.marshal_zones is not None
    assert [m.start_frac for m in z.marshal_zones] == pytest.approx(AUSTRIA_MARSHAL_STARTS, abs=1e-5)
    assert {m.flag for m in z.marshal_zones} == {"none"}  # no flags shown during this race
    # format 2025 carries no DRS / active-aero tables: unknown, not "none"
    assert z.drs_zones_frac is None and z.aero_full_zones_frac is None and z.aero_partial_zones_frac is None
    # the sector starts were already sent before the marshal zones were populated
    first = infos[0].track_zones
    assert first is not None and first.sector2_start_m == z.sector2_start_m


def test_skeleton_metres_and_wrapping_zone(packets: list[CapturedPacket]) -> None:
    sk = build_track_skeleton(_session_infos(packets)[-1])
    assert sk.track_id == "f1:17" and sk.track_length_m == AUSTRIA_LENGTH_M
    assert sk.sectors is not None
    assert [round(s.length_m, 2) for s in sk.sectors] == [1203.96, 1730.97, 1388.07]
    zs = sk.marshal_zones
    assert zs is not None and len(zs) == 13
    assert sum(z.length_m for z in zs) == pytest.approx(AUSTRIA_LENGTH_M)
    line = sk.marshal_zone_at(0.0)
    assert line is zs[-1] and line.index == 0 and line.wraps
    assert line.start_m == pytest.approx(0.99083 * AUSTRIA_LENGTH_M, abs=0.1)  # ~40 m before the line
    assert line.end_m == pytest.approx(0.07919 * AUSTRIA_LENGTH_M, abs=0.1)  # ~342 m after it
    assert sk.drs_zones is None
    assert sk.tier == TIER_GAME_NATIVE  # real game output
    # Shown and spoken by the game's own numbering: the zone through the line is the game's zone 1 (index 0),
    # although it is the 13th to start after the line.
    assert (line.game_number, line.lap_order) == (1, 13)


def test_stored_skeleton_matches_the_live_one_without_flags(packets: list[CapturedPacket]) -> None:
    """The stored-row path (session page) rebuilds the same geometry from the persisted zones, minus live flags."""
    info = _session_infos(packets)[-1]
    assert info.track_zones is not None
    live = build_track_skeleton(info)
    row = {
        "game": info.game.value,
        "track_id": info.track_id,
        "track_length_m": info.track_length_m,
        "synthetic": False,
        "info": {"track_zones": info.track_zones.without_flags().to_dict()},
    }
    stored = skeleton_from_session_row(row)
    assert stored is not None and stored.tier == TIER_GAME_NATIVE
    assert stored.sector_boundaries_m == live.sector_boundaries_m
    geometry = [(z.index, z.start_m, z.end_m) for z in live.marshal_zones or ()]
    assert len(geometry) == 13 and [(z.index, z.start_m, z.end_m) for z in stored.marshal_zones or ()] == geometry
    assert {z.flag for z in live.marshal_zones or ()} == {"none"}  # live: the game's current flags
    assert {z.flag for z in stored.marshal_zones or ()} == {None}  # stored: flags unknown, never replayed


def test_skeleton_sectors_agree_with_the_games_own_sector_field(packets: list[CapturedPacket]) -> None:
    """The game's sector starts are right: geometric ``sector_of(lapDistance)`` matches LapData.sector on the lap.

    ``sector_of`` is geometry, not timing; the only place they differ in this capture is the line-crossing frame.
    This excerpt has no negative lapDistance (the grid is ~132 m past the line), so the game's sector for frames
    before the first crossing is unobserved; timing consumers use ``CarFrame.sector``.
    """
    adapter = F1Adapter()
    sk = None
    agree = 0
    disagree: list[tuple[int | None, float, int]] = []
    for p in packets:
        for e in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(e, SessionInfo):
                sk = build_track_skeleton(e)
            elif isinstance(e, CarFrame) and sk is not None and e.sector is not None and e.lap_distance_m is not None:
                if e.quality & FrameQuality.NOT_RACING:
                    continue
                if sk.sector_of(e.lap_distance_m) == e.sector:
                    agree += 1
                else:
                    disagree.append((e.lap_number, e.lap_distance_m, e.sector))
    assert agree > 2000
    # Real quirk: on the line-crossing frame lapDistance is already past the line (4323.23 m > 4323 m) while the
    # game still says sector 3; the skeleton treats positions cyclically (that point is S1 of the next lap).
    assert len(disagree) == 1
    lap, d, sector = disagree[0]
    assert lap == 1 and AUSTRIA_LENGTH_M < d < AUSTRIA_LENGTH_M + 1 and sector == 2
