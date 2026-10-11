"""Track skeleton (L0a) maths: sectors, cyclic positions, wrap-aware zones, lookups and JSON export.

Pure unit tests on hand-built ``TrackZones``. Decoding the zones from Session packets is covered in
``test_f1_adapter.py``; the real-game values in ``tests/recorded/test_f1_25_ps5_austria.py``.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from itertools import pairwise

import pytest

from pitwall.analysis.track_skeleton import (
    TIER_GAME_NATIVE,
    TIER_SYNTHETIC,
    TrackSkeleton,
    ZoneKind,
    build_track_skeleton,
    skeleton_from_session_row,
)
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID
from pitwall.model.telemetry import Game, MarshalZone, SessionInfo, TrackZones

L = 4000.0
S2, S3 = 1200.0, 2900.0


def skel(zones: TrackZones | None = None, length: float | None = L) -> TrackSkeleton:
    return TrackSkeleton.from_zones(length, zones or TrackZones(sector2_start_m=S2, sector3_start_m=S3))


def _flat(segments: tuple[tuple[float, float], ...]) -> list[float]:
    return [v for seg in segments for v in seg]


def marshal(*starts: float, flags: tuple[str | None, ...] | None = None) -> TrackZones:
    fl = flags or ("none",) * len(starts)
    return TrackZones(marshal_zones=tuple(MarshalZone(start_frac=s, flag=f) for s, f in zip(starts, fl, strict=True)))


# ---------------------------------------------------------------- sectors
def test_sector_boundaries_and_sectors() -> None:
    sk = skel()
    assert sk.sector_boundaries_m == (0.0, S2, S3, L)
    assert sk.sectors is not None
    assert [(s.name, s.start_m, s.end_m) for s in sk.sectors] == [("S1", 0, S2), ("S2", S2, S3), ("S3", S3, L)]
    assert sum(s.length_m for s in sk.sectors) == L


# ``sector_of`` is GEOMETRY (which stretch of track a point is on), deliberately not the game's timing sector: the
# cases past/before the line are where the two differ. Real F1 25 still reports sector 3 at lapDistance L + 0.23
# (tests/recorded/test_f1_25_ps5_austria.py); what it reports for negative lapDistance on lap 1 is not observed yet
# (most likely S1 = 0). Timing consumers use CarFrame.sector.
@pytest.mark.parametrize(
    ("distance_m", "sector"),
    [
        (0.0, 0),
        (S2 - 1e-6, 0),
        (S2, 1),  # a boundary belongs to the sector it starts
        (S3 - 1e-6, 1),
        (S3, 2),
        (L - 1e-6, 2),
        (L, 0),  # exactly one lap is the line again
        (L + 10.0, 0),  # just past the line: S1 stretch (the game's timing may still say S3 on the crossing frame)
        (-10.0, 2),  # 10 m before the line: S3 stretch (geometry; NOT a claim about the game's lap-1 timing sector)
        (-L, 0),
        (-1e-18, 0),  # float edge: (-1e-18) % L == L
        (2 * L - 1.0, 2),
    ],
)
def test_sector_of_is_geometric_with_cyclic_edges(distance_m: float, sector: int) -> None:
    assert skel().sector_of(distance_m) == sector


@pytest.mark.parametrize("distance_m", [None, math.nan, math.inf, -math.inf, -L - 0.5, 2 * L, 1e9])
def test_sector_of_unknown_or_far_off_lap_is_none(distance_m: float | None) -> None:
    assert skel().sector_of(distance_m) is None


def test_position_and_fraction_are_cyclic() -> None:
    sk = skel()
    assert sk.position_m(-100.0) == pytest.approx(L - 100.0)
    assert sk.position_m(L + 5.0) == pytest.approx(5.0)
    assert sk.fraction(L / 4) == pytest.approx(0.25)
    assert sk.fraction(None) is None


def test_sector_of_without_track_length_only_classifies_forward_distances() -> None:
    sk = skel(length=None)
    assert sk.sectors is None and sk.sector_boundaries_m is None  # S3 end is unknown
    assert sk.sector_of(1500.0) == 1 and sk.sector_of(1e6) == 2
    assert sk.sector_of(-10.0) is None  # cannot wrap without knowing the lap length


@pytest.mark.parametrize(
    ("s2", "s3", "expect"),
    [
        (S3, S2, (None, None)),  # contradictory order: neither can be trusted
        (S2, S2, (None, None)),
        (0.0, S3, (None, S3)),  # 0 is the zero-filled "not populated" value
        (S2, L, (S2, None)),  # a boundary on/after the line is not inside the lap
        (math.nan, S3, (None, S3)),
        (None, None, (None, None)),
    ],
)
def test_invalid_sector_starts_stay_unknown(
    s2: float | None, s3: float | None, expect: tuple[float | None, ...]
) -> None:
    sk = skel(TrackZones(sector2_start_m=s2, sector3_start_m=s3))
    assert (sk.sector2_start_m, sk.sector3_start_m) == expect
    assert sk.sectors is None and sk.sector_of(100.0) is None


@pytest.mark.parametrize("length", [None, 0.0, -5.0, math.nan])
def test_invalid_track_length_is_unknown(length: float | None) -> None:
    sk = skel(marshal(0.1, 0.5), length=length)
    assert sk.track_length_m is None
    assert sk.marshal_zones is None  # fractions cannot become metres without a length


# ---------------------------------------------------------------- marshal zones (starts only, wrap-aware)
AUSTRIA_LIKE = (0.99, 0.08, 0.13, 0.22, 0.30, 0.34, 0.42, 0.54, 0.59, 0.67, 0.75, 0.80, 0.91)  # game order


def test_marshal_zones_are_sorted_and_the_last_wraps_through_the_line() -> None:
    sk = skel(marshal(*AUSTRIA_LIKE))
    zs = sk.marshal_zones
    assert zs is not None and len(zs) == 13
    assert [z.start_m for z in zs] == sorted(z.start_m for z in zs)
    assert [z.lap_order for z in zs] == list(range(1, 14))
    assert zs[0].index == 1 and zs[0].start_m == pytest.approx(0.08 * L)  # game index preserved
    assert zs[0].game_number == 2 and zs[-1].game_number == 1  # the game's numbering, not the order from the line
    last = zs[-1]
    assert last.index == 0 and last.wraps
    assert last.start_m == pytest.approx(0.99 * L) and last.end_m == pytest.approx(0.08 * L)
    assert _flat(last.segments_m) == pytest.approx([0.99 * L, L, 0.0, 0.08 * L])
    assert last.length_m == pytest.approx(0.09 * L)
    # each zone ends where the next one starts
    for a, b in pairwise(zs):
        assert a.end_m == b.start_m and not a.wraps


def test_marshal_zones_cover_the_lap_exactly_once() -> None:
    sk = skel(marshal(*AUSTRIA_LIKE))
    zs = sk.marshal_zones
    assert zs is not None
    assert sum(z.length_m for z in zs) == pytest.approx(L)
    for d in [0.0, 1.0, 0.08 * L - 1e-6, 0.08 * L, 2000.0, L - 1.0]:
        p = sk.position_m(d)
        assert p is not None
        assert sum(z.contains(p) for z in zs) == 1, d


def test_marshal_zone_lookup_across_the_line_and_flags() -> None:
    sk = skel(marshal(0.99, 0.08, 0.5, flags=("yellow", "none", None)))
    for d in (0.0, L - 1.0, -5.0, L + 5.0, 0.08 * L - 0.1):
        z = sk.marshal_zone_at(d)
        assert z is not None and z.index == 0 and z.flag == "yellow", d
    z = sk.marshal_zone_at(0.08 * L)
    assert z is not None and z.index == 1 and z.flag == "none"
    z = sk.marshal_zone_at(0.6 * L)
    assert z is not None and z.index == 2 and z.flag is None  # -1 / unknown flag stays unknown
    assert sk.marshal_zone_at(None) is None


def test_marshal_zone_starting_on_the_line_does_not_wrap() -> None:
    zs = skel(marshal(0.5, 0.0)).marshal_zones
    assert zs is not None
    assert [(z.start_m, z.end_m, z.wraps) for z in zs] == [(0.0, 0.5 * L, False), (0.5 * L, L, False)]


def test_single_marshal_zone_covers_the_whole_lap() -> None:
    (z,) = skel(marshal(0.25)).marshal_zones or ()
    assert z.length_m == pytest.approx(L) and z.wraps and z.contains(0.0) and z.contains(0.25 * L)
    (z0,) = skel(marshal(0.0)).marshal_zones or ()
    assert z0.segments_m == ((0.0, L),) and not z0.wraps


def test_marshal_zone_tables_unknown_vs_empty_vs_invalid() -> None:
    assert skel(TrackZones()).marshal_zones is None  # not reported
    assert skel(TrackZones(marshal_zones=())).marshal_zones == ()  # reported: none
    zs = skel(marshal(math.nan, 1.5, -0.2, 0.3, 1.0000004)).marshal_zones  # float32 noise above 1 is tolerated
    assert zs is not None and [(z.index, z.start_m) for z in zs] == [(4, 0.0), (3, pytest.approx(0.3 * L))]


# ---------------------------------------------------------------- DRS / active-aero zones (start, end pairs)
def test_drs_zone_through_the_line_wraps() -> None:
    sk = skel(TrackZones(drs_zones_frac=((0.6, 0.7), (0.95, 0.10))))
    zs = sk.drs_zones
    assert zs is not None and [z.index for z in zs] == [0, 1]
    wrap = zs[1]
    assert wrap.wraps and wrap.length_m == pytest.approx(0.15 * L)
    assert _flat(wrap.segments_m) == pytest.approx([0.95 * L, L, 0.0, 0.10 * L])
    assert sk.drs_zone_at(-1.0) is wrap and sk.drs_zone_at(0.0) is wrap and sk.drs_zone_at(0.1 * L) is None
    assert sk.drs_zone_at(0.65 * L) is zs[0] and sk.drs_zone_at(0.5 * L) is None


def test_zone_ending_on_the_line_is_not_a_wrap() -> None:
    for end in (1.0, 0.0):
        (z,) = skel(TrackZones(drs_zones_frac=((0.9, end),))).drs_zones or ()
        assert z.end_m == L and not z.wraps and z.contains(L - 1e-6) and not z.contains(0.0)
    (z,) = skel(TrackZones(drs_zones_frac=((1.0, 0.2),))).drs_zones or ()
    assert z.start_m == 0.0 and z.end_m == pytest.approx(0.2 * L) and not z.wraps  # a start of 1.0 is the line


def test_degenerate_and_invalid_zone_pairs_are_dropped() -> None:
    zs = skel(TrackZones(aero_full_zones_frac=((0.3, 0.3), (math.nan, 0.5), (0.2, 1.7), (0.4, 0.5)))).aero_full_zones
    assert zs is not None and [(z.index, z.lap_order) for z in zs] == [(3, 1)]


@pytest.mark.parametrize(
    "pair",
    [
        (1.0, 1.0),  # zero-length on the line: 1.0 % 1.0 == 0 must not turn it into start 0, end L
        (0.0, 0.0),
        (1.0000003, 0.9999999),  # float32 noise either side of 1.0
        (0.9999999, 1.0000003),
        (1.0, 0.0),  # from the line to the line
        (1.0, 0.0000005),
        (0.9999995, 0.0000003),  # noise either side of the line, as a "wrapping" pair
        (0.5, 0.5000004),
    ],
)
def test_zero_length_pairs_never_become_a_whole_lap_zone(pair: tuple[float, float]) -> None:
    sk = skel(TrackZones(drs_zones_frac=(pair,)))
    assert sk.drs_zones == ()
    assert sk.drs_zone_at(0.0) is None and sk.drs_zone_at(0.5 * L) is None


def test_explicit_whole_lap_zone_is_kept() -> None:
    (z,) = skel(TrackZones(aero_full_zones_frac=((0.0, 1.0),))).aero_full_zones or ()
    assert (z.start_m, z.end_m, z.wraps, z.length_m) == (0.0, L, False, L)


def test_format_2025_zone_tables_stay_none_not_empty() -> None:
    sk = skel(TrackZones(source="f1_session@2025", sector2_start_m=S2, sector3_start_m=S3))
    assert sk.drs_zones is None and sk.aero_full_zones is None and sk.aero_partial_zones is None
    d = sk.to_dict()
    assert d["drs_zones"] is None and d["aero_full_zones"] is None and d["aero_partial_zones"] is None


def test_reported_zero_zones_is_an_empty_list() -> None:
    d = skel(TrackZones(drs_zones_frac=(), aero_full_zones_frac=((0.1, 0.2),), active_aero_track_status="full"))
    assert d.drs_zones == () and d.to_dict()["drs_zones"] == []
    assert d.zone_at(ZoneKind.DRS, 10.0) is None and d.next_zone(ZoneKind.DRS, 10.0) is None
    assert d.active_aero_track_status == "full"


def test_next_zone_is_cyclic() -> None:
    sk = skel(TrackZones(drs_zones_frac=((0.25, 0.3), (0.75, 0.8))))
    nz = sk.next_zone(ZoneKind.DRS, 0.5 * L)
    assert nz is not None and nz[0].index == 1 and nz[1] == pytest.approx(0.25 * L)
    nz = sk.next_zone(ZoneKind.DRS, 0.9 * L)  # past the last zone: the first one, next lap
    assert nz is not None and nz[0].index == 0 and nz[1] == pytest.approx(0.35 * L)
    nz = sk.next_zone(ZoneKind.DRS, 0.25 * L)  # exactly at a start
    assert nz is not None and nz[0].index == 0 and nz[1] == pytest.approx(0.0)
    assert sk.next_zone(ZoneKind.AERO_FULL, 0.0) is None  # table unknown


# ---------------------------------------------------------------- export / builders
def _full_zones() -> TrackZones:
    return TrackZones(
        source="f1_session@2026",
        sector2_start_m=S2,
        sector3_start_m=S3,
        marshal_zones=tuple(MarshalZone(start_frac=f, flag="none") for f in AUSTRIA_LIKE),
        drs_zones_frac=((0.95, 0.1),),
        aero_full_zones_frac=((0.95, 0.1), (0.4, 0.5)),
        aero_partial_zones_frac=((0.96, 0.08),),
        active_aero_track_status="partial",
    )


def test_to_dict_is_strict_json_and_complete() -> None:
    sk = TrackSkeleton.from_zones(L, _full_zones(), pit_speed_limit_kph=80.0, game="f1_25", track_id="f1:17")
    d = sk.to_dict()
    json.dumps(d, allow_nan=False)
    assert d["tier"] == TIER_GAME_NATIVE and d["source"] == "f1_session@2026" and d["track_id"] == "f1:17"
    assert d["sector_boundaries_m"] == [0.0, S2, S3, L] and [s["name"] for s in d["sectors"]] == ["S1", "S2", "S3"]
    assert d["pit_speed_limit_kph"] == 80.0 and d["active_aero_track_status"] == "partial"
    wrap = d["drs_zones"][0]
    assert wrap["wraps"] and wrap["segments_m"] == [[0.95 * L, L], [0.0, 0.1 * L]]
    assert wrap["start_frac"] == 0.95 and wrap["end_frac"] == 0.1 and wrap["kind"] == "drs"
    assert [z["lap_order"] for z in d["aero_full_zones"]] == [1, 2] and d["aero_full_zones"][0]["index"] == 1
    assert [z["game_number"] for z in d["aero_full_zones"]] == [2, 1]
    assert d["synthetic"] is False
    assert len(d["marshal_zones"]) == 13 and d["marshal_zones"][-1]["index"] == 0


def test_to_dict_with_nothing_known_is_all_none() -> None:
    d = TrackSkeleton.from_zones(None, None).to_dict()
    json.dumps(d, allow_nan=False)
    assert d["sectors"] is None and d["marshal_zones"] is None and d["track_length_m"] is None


def test_build_from_session_info() -> None:
    info = SessionInfo(
        game=Game.F1_25, track_id="f1:17", track_length_m=L, pit_speed_limit_kph=80.0, track_zones=_full_zones()
    )
    sk = build_track_skeleton(info)
    assert sk.game == "f1_25" and sk.track_id == "f1:17" and sk.pit_speed_limit_kph == 80.0
    assert sk.sector_of(S3) == 2 and sk.marshal_zones is not None
    # other games / adapters that send no skeleton: everything unknown, nothing fabricated
    bare = build_track_skeleton(SessionInfo(game=Game.GT7, track_length_m=L))
    assert bare.sectors is None and bare.marshal_zones is None and bare.drs_zones is None


def test_track_zones_round_trip_and_geometry_key() -> None:
    z = _full_zones()
    assert TrackZones.from_dict(json.loads(json.dumps(z.to_dict(), allow_nan=False))) == z
    flagged = replace(z, marshal_zones=marshal(*AUSTRIA_LIKE, flags=("yellow",) * 13).marshal_zones)
    assert flagged.geometry_key() == z.geometry_key() and flagged != z  # flags are live state, not geometry
    assert TrackZones(sector2_start_m=1.0).geometry_key() != TrackZones(sector2_start_m=2.0).geometry_key()


def test_track_zones_from_dict_is_tolerant() -> None:
    assert TrackZones.from_dict(None) is None and TrackZones.from_dict([]) is None  # type: ignore[arg-type]
    z = TrackZones.from_dict(
        {
            "sector2_start_m": "1200",
            "sector3_start_m": True,
            "marshal_zones": [{"start_frac": 0.5, "flag": 3}, {"flag": "none"}, "junk", {"start_frac": 0.1}],
            "drs_zones_frac": [[0.1, None], [0.2, 0.3], [1, 2, 3]],
            "aero_full_zones_frac": "nope",
        }
    )
    assert z is not None
    assert z.sector2_start_m is None and z.sector3_start_m is None  # strings/bools are not numbers
    assert z.marshal_zones == (MarshalZone(0.5, None), MarshalZone(0.1, None))
    assert z.drs_zones_frac == ((0.2, 0.3),) and z.aero_full_zones_frac is None and z.aero_partial_zones_frac is None
    assert TrackZones(sector2_start_m=math.nan).to_dict()["sector2_start_m"] is None


def test_synthetic_sessions_are_tiered_synthetic() -> None:
    """Generated zones must never be labelled game data (evidence tiers, CLAUDE.md)."""
    zones = _full_zones()
    infos = [
        SessionInfo(game=Game.F1_25, track_length_m=L, track_zones=zones, extra={"synthetic": True}),  # session mgr
        SessionInfo(game=Game.F1_25, track_length_m=L, track_zones=zones, session_uid=str(SYNTHETIC_SESSION_UID)),
        SessionInfo(game=Game.F1_25, track_length_m=L, track_zones=zones, track_id="synthetic:demo"),
    ]
    for info in infos:
        sk = build_track_skeleton(info)
        assert sk.tier == TIER_SYNTHETIC and sk.synthetic and sk.to_dict()["tier"] == "synthetic", info
        assert sk.source == "f1_session@2026"  # the wire format is still recorded, the tier says it is generated
    real = build_track_skeleton(SessionInfo(game=Game.F1_25, session_uid="123", track_id="f1:17", track_length_m=L))
    assert real.tier == TIER_GAME_NATIVE and not real.synthetic

    stored = {"track_zones": zones.to_dict()}
    rows: list[dict[str, object]] = [
        {"track_length_m": L, "info": stored, "synthetic": True},  # sessions.synthetic column
        {"track_length_m": L, "info": {**stored, "synthetic": True}},  # info.extra flag
        {"track_length_m": L, "info": stored, "track_id": "synthetic:demo"},
        {"track_length_m": L, "info": {"sector2_start_m": S2, "sector3_start_m": S3}, "synthetic": 1},  # legacy row
    ]
    for r in rows:
        sk_row = skeleton_from_session_row(r)
        assert sk_row is not None and sk_row.tier == TIER_SYNTHETIC, r
    sk_real = skeleton_from_session_row({"track_length_m": L, "info": stored, "synthetic": False, "track_id": "f1:17"})
    assert sk_real is not None and sk_real.tier == TIER_GAME_NATIVE


def test_stored_rows_never_replay_marshal_flags() -> None:
    """A stored copy of the zones is one 0.5 s moment: its flags must not reappear as a fact on the session page."""
    flagged = replace(_full_zones(), marshal_zones=marshal(*AUSTRIA_LIKE, flags=("yellow",) * 13).marshal_zones)
    live = TrackSkeleton.from_zones(L, flagged)
    assert {z.flag for z in live.marshal_zones or ()} == {"yellow"}  # live: flags are current game state
    sk = skeleton_from_session_row({"game": "f1_25", "track_length_m": L, "info": {"track_zones": flagged.to_dict()}})
    assert sk is not None and sk.marshal_zones is not None and len(sk.marshal_zones) == 13
    assert {z.flag for z in sk.marshal_zones} == {None}
    assert {z["flag"] for z in sk.to_dict()["marshal_zones"]} == {None}
    assert [z.start_m for z in sk.marshal_zones] == [z.start_m for z in live.marshal_zones or ()]  # geometry kept
    off = TrackSkeleton.from_zones(L, flagged, live_flags=False)
    assert {z.flag for z in off.marshal_zones or ()} == {None}


def test_without_flags_keeps_geometry() -> None:
    flagged = replace(_full_zones(), marshal_zones=marshal(0.1, 0.5, flags=("yellow", "blue")).marshal_zones)
    bare = flagged.without_flags()
    assert bare.geometry_key() == flagged.geometry_key()
    assert [m.flag for m in bare.marshal_zones or ()] == [None, None]
    assert TrackZones.from_dict(bare.to_dict()) == bare
    assert bare.without_flags() is bare and TrackZones().without_flags() == TrackZones()


def test_skeleton_from_stored_session_rows() -> None:
    new_row = {
        "game": "f1_25",
        "track_id": "f1:17",
        "track_length_m": L,
        "info": {"track_zones": _full_zones().to_dict()},
    }
    sk = skeleton_from_session_row(new_row)
    assert sk is not None and sk.marshal_zones is not None and sk.drs_zones is not None and sk.track_id == "f1:17"
    # rows written before the typed zones: the legacy extra keys still give the sectors
    legacy = {"game": "f1_25", "track_length_m": L, "info": {"sector2_start_m": S2, "sector3_start_m": S3}}
    sk = skeleton_from_session_row(legacy)
    assert sk is not None and sk.sector_boundaries_m == (0.0, S2, S3, L) and sk.marshal_zones is None
    assert sk.source == "legacy_session_info"
    assert skeleton_from_session_row({"game": "gt7", "track_length_m": L, "info": {}}) is None
    assert skeleton_from_session_row({"info": None}) is None
