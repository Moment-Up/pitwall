"""Track outline prior (layer L1a): SVG parsing, affine inversion, the lap-distance index map, the length gate,
arc-length resampling and curvature, the vendored data's licence/provenance, and a recorded-tier check of the
axis convention against the committed real PS5 Austria excerpt."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from pitwall import trackdata
from pitwall.analysis.track_geometry import (
    F1_25_OUTLINE_KEYS,
    MAX_LENGTH_MISMATCH,
    OUTLINE_LABEL,
    OUTLINE_SOURCE,
    TIER_SHIPPED_SEED,
    OutlineError,
    SvgAffine,
    build_outline,
    direction_of,
    knot_lap_distances,
    length_gate,
    load_outline_svg,
    outline_from_knots,
    outline_key,
    parse_svg_polyline,
    resample_arc,
)
from pitwall.analysis.track_identity import find_sheet

ROOT = Path(__file__).resolve().parents[2]
EXCERPT = ROOT / "tests" / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
K_FLAT = 0.0065  # 1/m: R 154 m, the research's "straight" threshold (section 5.2)


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _circle(radius: float, n: int = 800, x0: float = 120.0, z0: float = -40.0) -> np.ndarray:
    a = 2 * np.pi * np.arange(n) / n
    return np.asarray(np.c_[x0 + radius * np.cos(a), z0 + radius * np.sin(a)], dtype=np.float64)


def _stadium(straight: float, radius: float, n: int = 800) -> np.ndarray:
    """Closed stadium (two straights, two semicircles) sampled uniformly by arc length."""
    perim = 2 * straight + 2 * np.pi * radius
    s = np.arange(n) * perim / n
    pts = np.empty((n, 2))
    for i, si in enumerate(s):
        if si < straight:
            pts[i] = (si, 0.0)
        elif si < straight + np.pi * radius:
            a = (si - straight) / radius
            pts[i] = (straight + radius * np.sin(a), radius - radius * np.cos(a))
        elif si < 2 * straight + np.pi * radius:
            pts[i] = (straight - (si - straight - np.pi * radius), 2 * radius)
        else:
            a = (si - 2 * straight - np.pi * radius) / radius
            pts[i] = (-radius * np.sin(a), radius + radius * np.cos(a))
    return pts


# ============================================================================================ SVG + affine
def test_affine_round_trip_generic_and_png_shaped() -> None:
    rng = np.random.default_rng(7)
    world = rng.uniform(-900, 900, size=(500, 2))
    for aff in (
        SvgAffine(a=0.3, b=-0.2, c=500.0, d=0.15, e=0.41, f=280.0),  # generic, det != 0
        SvgAffine(a=0.0, b=0.412686, c=537.481, d=-0.412686, e=0.0, f=341.457),  # PnG Austria shape
    ):
        back = aff.to_world(aff.to_svg(world))
        assert np.allclose(back, world, atol=1e-9)
        assert np.allclose(aff.to_svg(aff.to_world(world)), world, atol=1e-9)


def test_affine_inversion_of_every_vendored_outline_reproduces_its_svg_points() -> None:
    for key in F1_25_OUTLINE_KEYS.values():
        svg, aff = load_outline_svg(key)
        assert aff.a == 0.0 and aff.e == 0.0 and aff.b == pytest.approx(-aff.d, rel=1e-5)  # rotation + scale
        world = aff.to_world(svg)
        assert np.abs(aff.to_svg(world) - svg).max() < 1e-9, key


def test_affine_rejects_bad_coefficients() -> None:
    with pytest.raises(OutlineError, match="singular"):
        SvgAffine.from_mapping({"a": 1, "b": 2, "c": 0, "d": 2, "e": 4, "f": 0})
    with pytest.raises(OutlineError, match="missing"):
        SvgAffine.from_mapping({"a": 1, "b": 0, "c": 0, "d": 0, "e": 1})
    with pytest.raises(OutlineError, match="non-finite"):
        SvgAffine.from_mapping({"a": math.nan, "b": 0, "c": 0, "d": 0, "e": 1, "f": 0})


def test_parse_svg_polyline() -> None:
    text = (
        '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><polyline points="1,2 3.5,-4 5e1,6 7,8 1,2"/>'
        '<line x1="0" y1="0" x2="1" y2="1"/></svg>'
    )
    pts = parse_svg_polyline(text)
    assert pts.shape == (5, 2) and pts[2].tolist() == [50.0, 6.0]
    for bad, msg in (
        ("<svg><line/></svg>", "no <polyline>"),
        ('<svg><polyline points="1,2 3"/></svg>', "even number"),
        ("<svg><polyline", "well-formed"),
        ('<!DOCTYPE svg [<!ENTITY x "1,2 ">]><svg><polyline points="&x;&x;&x;&x;"/></svg>', "DOCTYPE"),
    ):
        with pytest.raises(OutlineError, match=msg):
            parse_svg_polyline(bad)


def test_vendored_outlines_have_800_knots_and_a_closing_duplicate() -> None:
    for key in F1_25_OUTLINE_KEYS.values():
        svg, _ = load_outline_svg(key)
        assert svg.shape == (801, 2), key
        assert np.allclose(svg[0], svg[-1]), key


# ============================================================================================ track ids
def test_outline_key_mapping() -> None:
    assert outline_key("f1_25", "f1:17") == "Austria"
    assert outline_key("f1_25", "f1:40") == "Austria_Reverse"
    assert outline_key("f1_25", "f1:32") == "Losail"
    for game, tid in (
        ("f1_25", "f1:42"),  # Madrid: no outline at the pin
        ("f1_25", "f1:8"),  # legacy Hockenheim
        ("f1_25", "f1:-1"),
        ("f1_25", "synthetic:f1:17"),
        ("f1_24", "f1:17"),  # the f1_2025 maps only
        ("gt7", "f1:17"),
        (None, "f1:17"),
        ("f1_25", None),
        ("f1_25", "f1:١٧"),  # non-ASCII digits
    ):
        assert outline_key(game, tid) is None, (game, tid)
    with pytest.raises(OutlineError, match="no outline"):
        build_outline("f1_25", "f1:42", 5411.0)


def test_track_id_table_matches_the_vendored_track_segments() -> None:
    names = {d["circuit_number"]: d["circuit_name"] for _, d in trackdata.pits_n_giggles_segment_documents()}
    for tid, key in F1_25_OUTLINE_KEYS.items():
        assert names[tid] == key, tid
    assert set(names) - set(F1_25_OUTLINE_KEYS) == {42}  # Madrid has segments but no outline
    transforms = json.loads(
        trackdata.pits_n_giggles_dir().joinpath("track-maps", "f1_2025", "svg_transforms.json").read_text("utf-8")
    )
    assert sorted(transforms) == sorted(F1_25_OUTLINE_KEYS.values())


# ============================================================================================ lap distance + gate
def test_knot_lap_distances_are_bin_centres() -> None:
    d = knot_lap_distances(800, 4323.0)
    assert d[0] == pytest.approx(4323.0 / 1600) and d[-1] == pytest.approx(4323.0 - 4323.0 / 1600)
    assert np.allclose(np.diff(d), 4323.0 / 800)


def test_length_gate_on_a_circle() -> None:
    r = 600.0
    circ = 2 * np.pi * r
    knots = _circle(r)
    ok = length_gate(knots, circ)
    assert ok.ok and ok.path_ratio == pytest.approx(1.0, abs=1e-4) and ok.spacing_ratio == pytest.approx(1.0, abs=1e-4)
    assert length_gate(knots, circ * (1 + 0.95 * MAX_LENGTH_MISMATCH)).ok
    bad = length_gate(knots, circ * (1 + 1.05 * MAX_LENGTH_MISMATCH))
    assert not bad.ok and bad.reason and "lap length" in bad.reason
    assert not length_gate(knots, circ / 1.06).ok
    with pytest.raises(OutlineError, match="median spacing"):
        outline_from_knots(knots, circ * 1.08)


def test_length_gate_on_the_real_outlines() -> None:
    # every layout passes at its track sheet's lap length except Monaco, whose seeded 3067 m is truncated
    for tid, key in F1_25_OUTLINE_KEYS.items():
        if key == "Monaco":
            with pytest.raises(OutlineError):
                build_outline("f1_25", f"f1:{tid}")
            continue
        o = build_outline("f1_25", f"f1:{tid}")
        assert o.track_length_source == "track_sheet" and o.gate.ok, key
        assert 0.975 < o.gate.path_ratio < 1.0, key  # a racing line is shorter than the lap reference
    # at its probable game length (unverified) Monaco passes: the spacing measure is robust where the path is not
    monaco = build_outline("f1_25", "f1:5", 3323.0)
    assert monaco.track_length_source == "session" and monaco.gate.path_ratio < 0.98


def test_outline_rejects_bad_input() -> None:
    with pytest.raises(OutlineError, match="positive"):
        outline_from_knots(_circle(100), 0.0)
    with pytest.raises(OutlineError, match=">= 4"):
        outline_from_knots(_circle(100)[:3], 600.0)
    k = _circle(100)
    k[5] = k[4]
    with pytest.raises(OutlineError, match="repeated"):
        outline_from_knots(k, 2 * np.pi * 100)


def test_position_at_and_centreline_follow_the_index_map() -> None:
    o = build_outline("f1_25", "f1:17", 4323.0)
    assert o.n == 800
    assert np.allclose(o.position_at(o.lap_distance_m), o.knots_xz)
    mid = o.position_at((o.lap_distance_m[10] + o.lap_distance_m[11]) / 2)
    assert np.allclose(mid, (o.knots_xz[10] + o.knots_xz[11]) / 2)
    # across the line: halfway between the last knot and the first
    assert np.allclose(o.position_at(0.0), (o.knots_xz[-1] + o.knots_xz[0]) / 2)
    cl = o.centreline()
    assert len(cl) == math.ceil(4323.0 / 5.0)
    assert np.allclose(cl[0], o.position_at(0.0), atol=0.01)


def test_project_round_trip() -> None:
    o = build_outline("f1_25", "f1:11", 5798.0)
    d, lat = o.project(o.knots_xz[::7])
    assert np.allclose(d, o.lap_distance_m[::7], atol=1e-6)
    assert lat.max() < 1e-6


def test_payload_shape_and_labels() -> None:
    p = build_outline("f1_25", "f1:17", 4323.0).to_payload()
    assert p["tier"] == TIER_SHIPPED_SEED and p["label"] == OUTLINE_LABEL and p["licence"] == "MIT"
    assert p["source"] == OUTLINE_SOURCE and OUTLINE_SOURCE == "pits_n_giggles@72f78aa"
    assert "Ashwin Natarajan" in p["attribution"]
    assert p["ground_plane"] == ["pos_x_m", "pos_z_m"] and p["length_m"] == 4323.0
    assert len(p["points"]) == len(p["lap_distance_m"]) == 800
    assert p["length_gate"]["ok"] is True and p["centreline_step_m"] == 5.0
    json.dumps(p)  # JSON-ready, finite


# ============================================================================================ arc + curvature
@pytest.mark.parametrize("radius", [40.0, 150.0, 600.0])
def test_constant_radius_curvature(radius: float) -> None:
    circ = 2 * np.pi * radius
    o = outline_from_knots(_circle(radius, n=max(64, int(circ / 5))), circ)
    for sigma in (0.0, 10.0):
        arc = resample_arc(o, sigma)
        assert arc.arc_length_m == pytest.approx(circ, rel=1e-4)
        assert np.allclose(np.abs(arc.curvature), 1.0 / radius, rtol=2e-3)
        # counter-clockwise in (x, z) = turning from +Z towards -X: negative curvature, total turn -2 pi
        assert (arc.curvature < 0).all()
        assert arc.curvature.sum() * arc.step_m == pytest.approx(-2 * np.pi, rel=1e-3)
        # lap distance follows the knot table and is periodic
        lap = np.unwrap(arc.lap_distance_m, period=circ)
        assert (np.diff(lap) > 0).all() and lap[-1] - lap[0] == pytest.approx(circ - arc.step_m, abs=0.5)


def test_smoothing_suppresses_phantom_curvature_on_noisy_straights() -> None:
    straight, radius = 900.0, 120.0
    perim = 2 * straight + 2 * np.pi * radius
    rng = np.random.default_rng(3)
    knots = _stadium(straight, radius)
    on_straight = np.abs(knots[:, 1]) < 1e-9
    knots[on_straight, 1] += rng.normal(0.0, 0.2, on_straight.sum())  # PnG straights: 0.06-0.22 m RMS
    o = outline_from_knots(knots, perim)
    raw = resample_arc(o, 0.0)
    smooth = resample_arc(o, 10.0)

    def mid(a: np.ndarray) -> np.ndarray:
        return (a > 150) & (a < straight - 150)

    assert np.abs(raw.curvature[mid(raw.lap_distance_m)]).max() > K_FLAT  # unsmoothed: phantom corners
    assert np.abs(smooth.curvature[mid(smooth.lap_distance_m)]).max() < K_FLAT  # sigma 10 m: flat
    # the bends keep their radius and the loop keeps its total turn (closure-preserving smoothing)
    bend = (smooth.lap_distance_m > straight + 60) & (smooth.lap_distance_m < straight + np.pi * radius - 60)
    assert np.median(np.abs(smooth.curvature[bend])) == pytest.approx(1 / radius, rel=0.05)
    assert abs(smooth.curvature.sum() * smooth.step_m) == pytest.approx(2 * np.pi, rel=1e-3)


def test_arc_lap_distance_differs_from_arc_length_on_a_real_outline() -> None:
    o = build_outline("f1_25", "f1:17", 4323.0)
    arc = resample_arc(o)
    assert arc.arc_length_m < 4323.0 - 20  # the racing line is ~36 m shorter than the lap reference
    lap = np.unwrap(arc.lap_distance_m, period=4323.0)
    assert (np.diff(lap) > 0).all()
    # arc length 0 is knot 0, the first lap-distance bin centre; the loop's end wraps back to it
    assert float(arc.lap_distance_at(0.0)) == pytest.approx(4323.0 / 1600, abs=1e-6)
    assert float(arc.lap_distance_at(arc.arc_length_m)) == pytest.approx(4323.0 / 1600, abs=1e-6)
    # using arc length as lap distance would be tens of metres off by the end of the lap (research section 6.1 B)
    assert float(np.max(lap - (arc.s + lap[0]))) > 20.0


def test_direction_matches_every_verified_sheet_turn() -> None:
    assert direction_of(-0.02) == "right" and direction_of(0.02) == "left" and direction_of(0.0) is None
    checked = 0
    for tid in ("f1:17", "f1:40", "f1:11", "f1:7"):
        sheet = find_sheet("f1_25", tid)
        assert sheet is not None
        arc = resample_arc(build_outline("f1_25", tid))
        scale = arc.track_length_m / sheet.lap_length_m
        for t in sheet.turns:
            if not (t.verified and t.direction):
                continue
            a, b = t.segment_m[0] * scale, t.segment_m[1] * scale
            k = arc.curvature[(arc.lap_distance_m >= a) & (arc.lap_distance_m < b)]
            assert direction_of(float(k[np.argmax(np.abs(k))])) == t.direction, (tid, t.ref)
            checked += 1
    assert checked >= 25


# ============================================================================================ licence files
def test_vendored_track_maps_ship_with_licence_and_provenance() -> None:
    root = trackdata.pits_n_giggles_dir()
    licence = root.joinpath("LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("MIT License") and "Copyright (c) [2024] [Ashwin Natarajan]" in licence
    assert _git_blob_sha1(licence.encode("utf-8")) == "8d23eef7c81cc358ae7e6d4b33186cc6704fa5b8"
    provenance = root.joinpath("PROVENANCE.md").read_text(encoding="utf-8")
    section = provenance[provenance.index("assets/track-maps/f1_2025` (outline prior") :]
    assert trackdata.PITS_N_GIGGLES_COMMIT in section and "13c30d7dbfc33e413316c0fe3b5ed747e6b2cbc1" in section
    assert "review before any commercial release" in section.lower()
    recorded = dict(re.findall(r"\| `f1_2025/([A-Za-z_]+\.(?:svg|json))` \| `([0-9a-f]{40})` \|", section))
    maps = root.joinpath("track-maps", "f1_2025")
    files = sorted(p.name for p in maps.iterdir() if p.is_file())
    assert len(files) == 28 and sorted(recorded) == files
    for name in files:
        assert _git_blob_sha1(maps.joinpath(name).read_bytes()) == recorded[name], name


# ============================================================================================ recorded tier
@pytest.mark.recorded
@pytest.mark.skipif(not EXCERPT.exists(), reason="real PS5 Austria excerpt not present")
def test_outline_frame_and_index_map_against_the_real_austria_excerpt() -> None:
    """V2 (research section 6.2): pitwall's pos_x_m/pos_z_m are the outline's world frame, and the index map gives
    the game's lap distance. The full race (data/captures/20261010-191501) measured lateral median 1.2 m and along-
    track median +1.1 m; the excerpt must agree."""
    from pitwall.adapters.f1.adapter import F1Adapter
    from pitwall.ingest.capture import CaptureReader
    from pitwall.model.telemetry import CarFrame

    adapter = F1Adapter()
    pts, dist = [], []
    for p in CaptureReader(EXCERPT):
        for e in adapter.decode(p.data, p.t_recv_ns):
            if (
                isinstance(e, CarFrame)
                and e.pos_x_m is not None
                and e.pos_z_m is not None
                and e.lap_distance_m is not None
                and 0.0 <= e.lap_distance_m < 4323.0
                and (e.speed_kph or 0.0) > 80.0
            ):
                pts.append((e.pos_x_m, e.pos_z_m))
                dist.append(e.lap_distance_m)
    assert len(pts) > 1000
    o = build_outline("f1_25", "f1:17", 4323.0)
    d, lat = o.project(np.asarray(pts))
    err = (d - np.asarray(dist) + 4323.0 / 2) % 4323.0 - 4323.0 / 2
    assert 0.0 < float(np.median(err)) < 2.0
    assert float(np.percentile(np.abs(err), 95)) < 3.0
    assert float(np.median(lat)) < 3.0

    # the other axis/sign conventions neither follow the line nor give the game's lap distance
    def swap_axes(q: np.ndarray) -> np.ndarray:
        return q[:, ::-1]

    def flip_x(q: np.ndarray) -> np.ndarray:
        return np.asarray(q * np.array([-1.0, 1.0]), dtype=np.float64)

    def flip_z(q: np.ndarray) -> np.ndarray:
        return np.asarray(q * np.array([1.0, -1.0]), dtype=np.float64)

    for swap in (swap_axes, flip_x, flip_z):
        d_bad, lat_bad = o.project(swap(np.asarray(pts)))
        err_bad = (d_bad - np.asarray(dist) + 4323.0 / 2) % 4323.0 - 4323.0 / 2
        assert float(np.median(lat_bad)) > 10.0 and float(np.median(np.abs(err_bad))) > 100.0
