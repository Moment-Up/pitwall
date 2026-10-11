"""Physics brake prior (layer L1c): closed-form checks of the QSS pipeline on outline geometry, zone extraction and
the sigma-ensemble gate on a synthetic circuit, envelope validation and caching, regressions on the shipped outlines,
the /api/track endpoints, and recorded-tier checks against the committed real PS5 Austria and Monza excerpts."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.analysis.brake_prior import (
    HEAVY_DROP_KPH,
    MAX_APEX_RADIUS_M,
    ONSET_ERROR_P90_M,
    ONSET_EVIDENCE,
    ONSET_UNCERTAINTY_M,
    TIER_PHYSICS_PREDICTED,
    BrakeEnvelope,
    BrakePrior,
    PriorRefresher,
    brake_prior_from_outline,
    build_brake_prior,
    driver_onset,
    solve_zones,
)
from pitwall.analysis.braking import BrakingEvent
from pitwall.analysis.laps import LapTrace
from pitwall.analysis.track_geometry import OutlineError, TrackOutline, outline_from_knots, resample_arc
from pitwall.model.telemetry import SessionInfo
from pitwall.sim.driver import G, VehicleModel, solve_lap

ROOT = Path(__file__).resolve().parents[2]
EXCERPT = ROOT / "tests" / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
MONZA = ROOT / "tests" / "fixtures" / "recorded" / "f1_25_2025_ps5_monza_race-excerpt.pwcap"
VEH = VehicleModel()


def _walk(segments: list[tuple[str, float, float]], step: float = 0.25) -> tuple[np.ndarray, float]:
    """Dense centreline of ("S", length, 0) straights and ("A", radius, +/-deg) arcs (positive = CCW in x/z)."""
    x = z = h = 0.0  # heading measured from +x, CCW
    pts = []
    total = 0.0
    for kind, a, b in segments:
        length = a if kind == "S" else abs(math.radians(b)) * a
        n = max(1, round(length / step))
        ds = length / n
        dh = 0.0 if kind == "S" else math.radians(b) / n
        for _ in range(n):
            pts.append((x, z))
            if kind == "S":
                x += ds * math.cos(h)
                z += ds * math.sin(h)
            else:
                # exact chord of the arc step
                x += 2 * a * math.sin(abs(dh) / 2) * math.cos(h + dh / 2)
                z += 2 * a * math.sin(abs(dh) / 2) * math.sin(h + dh / 2)
                h += dh
        total += length
    arr = np.asarray(pts)
    assert math.hypot(x, z) < 1e-6, "segments must close"
    return arr, total


def _outline(segments: list[tuple[str, float, float]], n: int = 800) -> TrackOutline:
    """Knots at the lap-distance bin centres (i + 0.5) * L / n, like the Pits n' Giggles outlines."""
    dense, total = _walk(segments)
    s_dense = np.arange(len(dense)) * (total / len(dense))
    s = (np.arange(n) + 0.5) * total / n
    knots = np.c_[np.interp(s, s_dense, dense[:, 0], period=total), np.interp(s, s_dense, dense[:, 1], period=total)]
    return outline_from_knots(knots, total, game="synthetic", track_id="synthetic:prior")


# Rounded quadrilateral, all left turns, closed by construction (see the displacement sums in the comments):
# x: 1000 + 100 - 25 - 1065 - 50 + 40 = 0 ; y: 100 + 700 + 25 - 50 - 735 - 40 = 0
SYNTH = [
    ("S", 1000.0, 0.0),
    ("A", 100.0, 90.0),  # fast corner: ~199 km/h, R 100 m >= 90 -> never a heavy stop
    ("S", 700.0, 0.0),
    ("A", 25.0, 90.0),  # slow: ~77 km/h
    ("S", 1065.0, 0.0),
    ("A", 50.0, 90.0),  # medium: ~117 km/h
    ("S", 735.0, 0.0),
    ("A", 40.0, 90.0),  # ~102 km/h
]
ARC_START = {  # lap distance where each bend begins
    "fast": 1000.0,
    "slow": 1000.0 + 50 * math.pi + 700.0,
    "medium": 1000.0 + 50 * math.pi + 700.0 + 12.5 * math.pi + 1065.0,
    "last": 1000.0 + 50 * math.pi + 700.0 + 12.5 * math.pi + 1065.0 + 25 * math.pi + 735.0,
}


BEND_LENGTH = {"fast": 50 * math.pi, "slow": 12.5 * math.pi, "medium": 25 * math.pi, "last": 20 * math.pi}


def _in_bend(d: float, bend: str) -> bool:
    return ARC_START[bend] - 30 <= d <= ARC_START[bend] + BEND_LENGTH[bend] + 10


def _braking_distance(v1: float, v2: float, veh: VehicleModel = VEH) -> float:
    """Closed form of dv^2/ds = -2 (b0 + b1 v^2): s = ln((b0 + b1 v1^2) / (b0 + b1 v2^2)) / (2 b1)."""
    b0, b1 = veh.brake_base, veh.brake_aero
    return math.log((b0 + b1 * v1 * v1) / (b0 + b1 * v2 * v2)) / (2 * b1)


# ============================================================================================ closed form
@pytest.mark.parametrize("radius", [30.0, 60.0, 120.0])
def test_constant_radius_speed_matches_closed_form(radius: float) -> None:
    n = max(64, int(2 * math.pi * radius / 4))
    a = 2 * np.pi * (np.arange(n) + 0.5) / n
    o = outline_from_knots(np.c_[radius * np.cos(a), radius * np.sin(a)], 2 * math.pi * radius)
    prof = solve_lap(resample_arc(o, 10.0).to_sim_track(), VEH)
    expected = math.sqrt(VEH.mu_lat * G / (1 / radius - VEH.aero_lat))  # v^2 = mu g / (k - aero)
    assert expected == pytest.approx(VEH.corner_speed(1 / radius))
    assert np.allclose(prof.v, min(expected, VEH.v_max), rtol=3e-3)


def _full_brake_distance(arc_sigma: float, veh: VehicleModel, v_hi_kph: float, v_lo_kph: float) -> float:
    """Distance the solved lap takes to slow from v_hi to v_lo on the straight before the slow hairpin."""
    arc = resample_arc(_outline(SYNTH), arc_sigma)
    prof = solve_lap(arc.to_sim_track(), veh)
    lap = arc.lap_distance_at(arc.s)
    i_bend = int(np.argmin(np.abs(lap - ARC_START["slow"])))
    v = prof.v * 3.6
    j_lo = i_bend
    while v[j_lo - 1] < v_lo_kph:  # walk back to where the speed was last above v_lo
        j_lo -= 1
    j_hi = j_lo
    while v[j_hi - 1] < v_hi_kph:
        j_hi -= 1
    s_hi = np.interp(v_hi_kph, [v[j_hi], v[j_hi - 1]], [arc.s[j_hi], arc.s[j_hi - 1]])
    s_lo = np.interp(v_lo_kph, [v[j_lo], v[j_lo - 1]], [arc.s[j_lo], arc.s[j_lo - 1]])
    return float(s_lo - s_hi)


@pytest.mark.parametrize("envelope", [None, BrakeEnvelope(23.6, 0.00228, "research section 5.3 Austria AI fit")])
def test_straight_line_braking_distance_matches_closed_form(envelope: BrakeEnvelope | None) -> None:
    veh = envelope.apply(VEH) if envelope else VEH
    expected = _braking_distance(300 / 3.6, 150 / 3.6, veh)
    assert _full_brake_distance(5.0, veh, 300.0, 150.0) == pytest.approx(expected, abs=1.5)


def test_zone_onset_and_minimum_match_closed_form() -> None:
    arc = resample_arc(_outline(SYNTH), 5.0)
    zones = solve_zones(arc)
    for bend, radius in (("slow", 25.0), ("medium", 50.0), ("last", 40.0), ("fast", 100.0)):
        z = next(z for z in zones if _in_bend(z.apex_m, bend) and z.drop_kph > 50)
        assert z.apex_kph / 3.6 == pytest.approx(VEH.corner_speed(1 / radius), rel=0.01)
        assert z.apex_radius_m == pytest.approx(radius, rel=0.02)
        # the stop starts one closed-form braking distance before the bend; the Gaussian-smoothed entry ramp moves
        # the end of full braking by up to ~2 sigma (10 m here)
        expected = _braking_distance(z.entry_kph / 3.6, z.apex_kph / 3.6)
        assert ARC_START[bend] - z.onset_m == pytest.approx(expected, abs=12.0)


def test_weaker_envelope_brakes_earlier() -> None:
    arc = resample_arc(_outline(SYNTH), 10.0)
    soft = solve_zones(arc, BrakeEnvelope(23.6, 0.00228, "test").apply(VEH))
    default = solve_zones(arc)
    for z in (z for z in default if z.drop_kph >= HEAVY_DROP_KPH):
        w = next(c for c in soft if abs(c.apex_m - z.apex_m) < 40)  # SolvedZone: internal solve positions
        assert w.onset_m < z.onset_m  # ~4 g instead of ~5.5 g at 300 km/h


# ============================================================================================ zones + gate
def test_zone_extraction_and_gate_on_a_synthetic_track() -> None:
    o = _outline(SYNTH)
    prior = brake_prior_from_outline(o)
    assert isinstance(prior, BrakePrior)
    by_bend = {next(b for b in ARC_START if _in_bend(w.est_apex_m, b)): w for w in prior.windows}
    assert sorted(by_bend) == ["last", "medium", "slow"]  # the R 100 m corner never passes the gate
    fast = [r for r in prior.rejected if _in_bend(r["est_apex_m"], "fast")]
    assert fast and any("apex R" in reason for reason in fast[0]["reasons"])
    for name, radius in (("slow", 25.0), ("medium", 50.0), ("last", 40.0)):
        w = by_bend[name]
        assert w.est_drop_kph >= HEAVY_DROP_KPH and w.apex_radius_m < MAX_APEX_RADIUS_M
        sigma5 = next(p for p in w.per_sigma if p["sigma_m"] == 5.0)
        assert sigma5["apex_radius_m"] == pytest.approx(radius, rel=0.02)
        assert radius * 0.98 <= w.apex_radius_m <= radius * 1.6  # the largest across sigmas: smoothing widens
        assert w.direction == "right"  # CCW with +x right, +z up is a right turn in F1 25's mirrored frame
        assert w.turn is None  # identity only from verified sheets
        assert w.est_onset_m < ARC_START[name] < w.est_apex_m + 30
        assert w.uncertainty_m >= ONSET_UNCERTAINTY_M
        assert len(w.per_sigma) == 4
    assert [w.index for w in prior.windows] == [1, 2, 3]
    assert [w.est_onset_m for w in prior.windows] == sorted(w.est_onset_m for w in prior.windows)


def test_payload_is_a_heads_up_never_a_target() -> None:
    p = brake_prior_from_outline(_outline(SYNTH)).to_payload()
    assert p["tier"] == TIER_PHYSICS_PREDICTED == "physics_predicted"  # the research doc's / track_knowledge's name
    assert p["positional"] is False and "never" in p["caveat"] and f"p90 error {ONSET_ERROR_P90_M:.0f} m" in p["caveat"]
    assert p["source"].startswith("qss@") and p["envelope"]["source"] == "default"
    assert p["gate"] == {"min_drop_kph": 100.0, "max_apex_radius_m": 90.0, "every_sigma": True}
    assert p["onset_error"]["p90_abs_m"] == ONSET_ERROR_P90_M and p["onset_error"]["stops"] == ONSET_EVIDENCE["stops"]
    for w in p["windows"]:
        assert w["tier"] == TIER_PHYSICS_PREDICTED and w["positional"] is False
        assert w["uncertainty_m"] >= ONSET_UNCERTAINTY_M and w["onset_error_p90_m"] == ONSET_ERROR_P90_M
        a, b = w["window_m"]
        assert a == pytest.approx((w["est_onset_m"] - w["uncertainty_m"]) % p["length_m"], abs=0.11)
        assert b == pytest.approx(w["est_apex_m"], abs=0.11)
        # every position and speed is named as an estimate; only the window (and its margin) is not
        assert not {"onset_m", "apex_m", "end_m", "braking_distance_m"} & set(w)
        assert not any(k.endswith("_kph") and not k.startswith("est_") for k in w)
        assert all("est_onset_m" in ps and "onset_m" not in ps for ps in w["per_sigma"])
    assert all("est_onset_m" in r and "onset_m" not in r for r in p["rejected"])
    json.dumps(p)


def test_payload_feeds_the_track_knowledge_resolver() -> None:
    """The JSON contract ``core.track_knowledge.PhysicsPrior.from_payload`` reads: tier name, windows, labels."""
    from pitwall.core.track_knowledge import TIER_PHYSICS, PhysicsPrior

    prior = build_brake_prior("f1_25", "f1:17", 4323.0)
    pp = PhysicsPrior.from_payload(prior.to_payload())
    assert pp is not None and pp.tier == TIER_PHYSICS == TIER_PHYSICS_PREDICTED
    assert [t.label for t in pp.tags] == ["T1", "T3", "T4", "T6", "T10"]
    for t, w in zip(pp.tags, prior.windows, strict=True):
        assert t.gated and t.severity == "heavy"
        assert (t.window_start_m, t.window_end_m) == w.window_m(prior.track_length_m)


def test_windows_ahead_wraps_across_the_line() -> None:
    prior = brake_prior_from_outline(_outline(SYNTH))
    L = prior.track_length_m
    first = prior.windows[0]
    ahead = prior.windows_ahead(first.window_start_m - 100.0, 150.0)
    assert ahead and ahead[0][1] is first and ahead[0][0] == pytest.approx(100.0)
    last = prior.windows[-1]
    wrap = prior.windows_ahead((last.est_apex_m + 10.0) % L, L)
    assert wrap[0][1] is first  # past the last window, the next one is the first of the next lap
    assert prior.windows_ahead(first.window_start_m + 1.0, 10.0) == []  # already inside


def test_split_braking_is_chained_into_one_stop() -> None:
    from pitwall.analysis.brake_prior import _chain
    from pitwall.analysis.braking import BrakingEvent

    def ev(start: float, v0: float, vmin: float, at: float) -> BrakingEvent:
        return BrakingEvent(start, at, v0, vmin, vmin, at, 1.0, 0.1, 0.1, 1.0, 0.0, None, None, 0.0)

    one = _chain([ev(100, 330, 200, 180), ev(185, 201, 90, 260)])  # no re-acceleration: one stop
    assert len(one) == 1 and one[0].start_m == 100 and one[0].min_speed_kph == 90 and one[0].min_speed_m == 260
    two = _chain([ev(100, 330, 120, 180), ev(300, 200, 90, 360)])  # re-accelerated in between: two stops
    assert len(two) == 2


# ============================================================================================ shipped outlines
def test_austria_prior_regression() -> None:
    prior = build_brake_prior("f1_25", "f1:17", 4323.0)
    labels = [(w.turn or {}).get("label") for w in prior.windows]
    assert labels == ["T1", "T3", "T4", "T6", "T10"]  # research section 5.3: 5 gated stops at Austria
    assert [w.direction for w in prior.windows] == ["right", "right", "right", "left", "right"]
    t1 = prior.windows[0]
    assert t1.turn == {"label": "T1", "name": "Niki Lauda Kurve", "voice_ok": True}
    assert 300 < t1.est_onset_m < 400 and 400 < t1.est_apex_m < 500
    assert build_brake_prior("f1_25", "f1:17", 4323.0) is prior  # cached
    assert build_brake_prior("f1_25", "f1:17", 4323.0000153) is prior  # float32 noise in m_trackLength: same key


@pytest.mark.parametrize(
    ("track_id", "length", "label"),
    [("f1:11", 5798.0, "T1-2"), ("f1:7", 5890.0, "T3"), ("f1:6", 4371.0, "T10"), ("f1:13", 5809.0, "T11")],
)
def test_known_heavy_stops_are_flagged(track_id: str, length: float, label: str) -> None:
    prior = build_brake_prior("f1_25", track_id, length)
    assert label in [(w.turn or {}).get("label") for w in prior.windows]


def test_no_outline_raises() -> None:
    with pytest.raises(OutlineError):
        build_brake_prior("f1_25", "f1:42", 5411.0)  # Madrid
    with pytest.raises(OutlineError):
        build_brake_prior("f1_25", "f1:5")  # Monaco at its truncated seeded length: refused, not guessed


def test_envelope_source_and_hash() -> None:
    o = _outline(SYNTH)
    a = brake_prior_from_outline(o)
    b = brake_prior_from_outline(o, envelope=BrakeEnvelope(23.6, 0.00228, "field fit"))
    assert a.source != b.source and b.to_payload()["envelope"]["source"] == "field fit"
    with pytest.raises(ValueError, match="primary"):
        brake_prior_from_outline(o, sigmas_m=(5.0, 15.0))


@pytest.mark.parametrize(
    ("b0", "b1", "match"),
    [
        (-5.0, 0.003, "brake_base > 0"),  # a sparse early AI fit with a negative intercept
        (0.0, 0.006, "brake_base > 0"),
        (20.0, -0.001, "brake_aero >= 0"),
        (math.nan, 0.002, "finite"),
        (20.0, math.inf, "finite"),
        (60.0, 0.008, "at 300 km/h"),  # ~11.8 g: not a car
        (3.0, 0.0001, "at 100 km/h"),  # ~0.4 g at 100 km/h
    ],
)
def test_envelope_rejects_non_physical_fits(b0: float, b1: float, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        BrakeEnvelope(b0, b1, "AI field")


def test_envelope_plausible_fits_and_refit_threshold() -> None:
    default = BrakeEnvelope(VEH.brake_base, VEH.brake_aero, "default")
    field = BrakeEnvelope(23.6, 0.00228, "AI field")
    assert default.decel_g(300.0) == pytest.approx(5.5, abs=0.1) and field.decel_g(300.0) == pytest.approx(4.0, abs=0.1)
    assert field.differs_from(None) and field.differs_from(default)
    assert not field.differs_from(BrakeEnvelope(23.7, 0.002285, "AI field"))  # < 3 % everywhere
    assert BrakeEnvelope(23.64, 0.0022801, "AI field").rounded() == BrakeEnvelope(23.6, 0.00228, "AI field")


def test_build_brake_prior_cache_key_is_the_rounded_envelope() -> None:
    a = build_brake_prior("f1_25", "f1:17", 4323.0, BrakeEnvelope(23.61, 0.0022801, "AI field"))
    assert build_brake_prior("f1_25", "f1:17", 4323.0, BrakeEnvelope(23.64, 0.0022799, "AI field")) is a
    assert a.to_payload()["envelope"] == {"brake_base": 23.6, "brake_aero": 0.00228, "source": "AI field"}
    other = build_brake_prior("f1_25", "f1:17", 4323.0, BrakeEnvelope(23.61, 0.0022801, "AI field (812 samples)"))
    assert other is not a  # the source is part of the key: refitting callers keep it constant


def test_prior_refresher_rebuilds_only_when_something_changed() -> None:
    r = PriorRefresher()
    changed, prior = r.refresh("f1_25", "f1:17", 4323.0)
    assert changed and prior is not None and prior.envelope_source == "default"
    assert r.refresh("f1_25", "f1:17", 4323.00002) == (False, prior)  # 2 Hz session hook, float32 noise: O(1)
    assert r.refresh("f1_25", "f1:17", 4323.0, None) == (False, prior)  # no envelope yet: keep
    field = BrakeEnvelope(23.6, 0.00228, "AI field")
    changed, cal = r.refresh("f1_25", "f1:17", 4323.0, field)
    assert changed and cal is not None and cal is not prior and cal.envelope_source == "AI field"
    assert r.refresh("f1_25", "f1:17", 4323.0, BrakeEnvelope(23.7, 0.002283, "AI field")) == (False, cal)  # < 3 %
    assert r.refresh("f1_25", "f1:17", 4323.0, None) == (False, cal)  # a lost snapshot does not un-calibrate
    changed, new_track = r.refresh("f1_25", "f1:11", 5798.0, None)
    assert (
        changed and new_track is not None and new_track.track_id == "f1:11" and new_track.envelope_source == "default"
    )
    assert r.refresh("f1_25", "f1:42", 5411.0) == (True, None)  # Madrid: no outline -> clear the layer
    assert r.refresh("f1_25", "f1:42", 5411.0, field) == (False, None)  # an envelope cannot create an outline
    assert r.refresh("f1_25", "f1:17", None) == (True, None) and r.prior is None  # no lap length: unknown
    assert r.refresh("f1_25", None, None) == (False, None)


# ============================================================================================ driver onset rule
def _ev(start: float, v0: float, vmin: float, at: float, end: float | None = None) -> BrakingEvent:
    return BrakingEvent(
        start, end if end is not None else at, v0, vmin, vmin, at, 1.0, 0.1, 0.1, 1.0, 0.0, None, None, 0.0
    )


def test_driver_onset_is_the_first_application_of_the_stop() -> None:
    """Monza T1-2 on the real lap 3 (see the recorded test): the driver brakes from 337 km/h at 718 m, re-accelerates
    between the chicane's parts and slows to 28 km/h after it. The stop is the 337 km/h application, never the
    later, nearer or slower minimum."""
    prior = build_brake_prior("f1_25", "f1:11", 5798.0)
    t12 = next(w for w in prior.windows if (w.turn or {}).get("label") == "T1-2")
    evs = [_ev(718, 337, 152, 828, 833), _ev(844, 159, 159, 845), _ev(866, 171, 80, 913), _ev(956, 93, 28, 984)]
    e = driver_onset(evs, t12, prior.track_length_m)
    assert e is not None and e.start_m == 718
    # chained (no re-acceleration in between): the first event of the chain, whichever event holds the minimum
    e = driver_onset([_ev(600, 320, 250, 640), _ev(700, 251, 120, 780)], t12, prior.track_length_m)
    assert e is not None and e.start_m == 600
    assert driver_onset([_ev(2400, 250, 160, 2450)], t12, prior.track_length_m) is None  # no braking there


# ============================================================================================ API
@pytest.fixture(scope="module")
def client() -> TestClient:
    from pitwall.api.app import OrjsonResponse
    from pitwall.api.routes_track import router

    app = FastAPI(default_response_class=OrjsonResponse)
    app.include_router(router)
    return TestClient(app)


def test_api_outline(client: TestClient) -> None:
    r = client.get("/api/track/outline", params={"game": "f1_25", "track_id": "f1:17", "track_length_m": 4323})
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "game outline (Pits n' Giggles)" and body["tier"] == "shipped_seed"
    assert body["track_length_source"] == "session" and len(body["centreline"]) == 865
    sheet = client.get("/api/track/outline", params={"game": "f1_25", "track_id": "f1:17"}).json()
    assert sheet["track_length_source"] == "track_sheet"
    assert client.get("/api/track/outline", params={"game": "f1_25", "track_id": "f1:42"}).status_code == 404
    assert client.get("/api/track/outline", params={"game": "gt7", "track_id": "f1:17"}).status_code == 404
    monaco = client.get("/api/track/outline", params={"game": "f1_25", "track_id": "f1:5"})
    assert monaco.status_code == 422 and "lap length" in monaco.json()["detail"]
    bad = client.get("/api/track/outline", params={"game": "f1_25", "track_id": "f1:17", "track_length_m": -4})
    assert bad.status_code == 422


def test_api_prior(client: TestClient) -> None:
    r = client.get("/api/track/prior", params={"game": "f1_25", "track_id": "f1:17", "track_length_m": 4323.0})
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "physics_predicted" and body["positional"] is False
    assert [w["turn"]["label"] for w in body["windows"]] == ["T1", "T3", "T4", "T6", "T10"]
    assert client.get("/api/track/prior", params={"game": "f1_25", "track_id": "synthetic:1"}).status_code == 404


# ============================================================================================ recorded tier
def _player_lap(path: Path, lap_number: int) -> tuple[LapTrace, SessionInfo]:
    """The player's samples on ``lap_number`` of a real capture excerpt, as a LapTrace (excerpts start mid-lap)."""
    from pitwall.adapters.f1.adapter import F1Adapter
    from pitwall.ingest.capture import CaptureReader
    from pitwall.model.telemetry import CarFrame

    adapter = F1Adapter()
    info: SessionInfo | None = None
    frames: list[CarFrame] = []
    for p in CaptureReader(path):
        for e in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(e, SessionInfo):
                info = e
            elif isinstance(e, CarFrame) and e.lap_number == lap_number and e.lap_distance_m is not None:
                frames.append(e)
    assert info is not None and frames

    def ch(attr: str) -> np.ndarray:
        return np.array([math.nan if getattr(f, attr) is None else getattr(f, attr) for f in frames], dtype=float)

    channels = {
        "distance_m": ch("lap_distance_m"),
        "session_time_s": ch("session_time_s"),
        "speed_kph": ch("speed_kph"),
        "brake": ch("brake"),
        "throttle": ch("throttle"),
        "steering": ch("steering"),
    }
    return LapTrace(lap_number=lap_number, channels=channels, lap_time_ms=None), info


@pytest.mark.recorded
@pytest.mark.skipif(not EXCERPT.exists(), reason="real PS5 Austria excerpt not present")
def test_driver_t1_onsets_fall_inside_the_heads_up_window() -> None:
    """On the real race the prediction is later than the driver (default envelope); the window, which starts one
    margin before the estimated onset, must contain the driver's real T1 brake application on both flying laps of
    the excerpt (laps 2 and 3: 334 m and 340 m against an estimated 354 m)."""
    from pitwall.analysis.braking import detect_braking
    from pitwall.ingest.capture import CaptureReader
    from tests.conftest import decode_session

    laps, _frames, info, _ = decode_session(list(CaptureReader(EXCERPT)))
    assert info.track_length_m == 4323.0
    prior = build_brake_prior("f1_25", "f1:17", info.track_length_m)
    t1 = prior.windows[0]
    a, _ = t1.window_m(prior.track_length_m)
    onsets = []
    for lap in laps:
        if lap.lap_number < 2:
            continue
        # the excerpt keeps ~10 s after each line crossing (to ~400 m, mid-braking for T1) and the lap's last seconds:
        # use the first piece only, so no event spans the excerpt's gap
        keep = lap.channels["distance_m"] <= t1.est_apex_m + 150.0
        assert lap.channels["distance_m"][keep].max() > t1.est_onset_m
        head = LapTrace(lap.lap_number, {k: v[keep] for k, v in lap.channels.items()}, None)
        e = driver_onset(detect_braking(head), t1, prior.track_length_m)
        assert e is not None and e.start_speed_kph > 250, lap.lap_number
        onsets.append(e.start_m)
    assert len(onsets) == 2
    for d in onsets:
        assert a <= d <= t1.est_onset_m  # inside the band, and before the (late) estimate


@pytest.mark.recorded
@pytest.mark.skipif(not MONZA.exists(), reason="real PS5 Monza excerpt not present")
def test_monza_heavy_stops_start_inside_the_heads_up_window() -> None:
    """Real PS5 Monza race, lap 3 (a clean flying lap; capture 20261010-205007, 560-2250 m): the driver's first brake
    application at T1-2 (718 m from 337 km/h) and T4-5 (1985 m from 325 km/h) must fall inside the heads-up window.
    The estimate is 88 m and 49 m late there, so the old 45 m margin missed T1-2 (its window began 43 m after the
    driver was already braking): the margin is a measured quantity, not a guess."""
    from pitwall.analysis.braking import detect_braking

    lap, info = _player_lap(MONZA, 3)
    assert info.track_id == "f1:11" and info.track_length_m == 5798.0
    prior = build_brake_prior("f1_25", info.track_id, info.track_length_m)
    L = prior.track_length_m
    evs = detect_braking(lap)
    by_label = {(w.turn or {}).get("label"): w for w in prior.windows}
    late = {}
    for label, (first_m, entry_kph) in {"T1-2": (718.0, 337.0), "T4-5": (1985.0, 325.0)}.items():
        w = by_label[label]
        e = driver_onset(evs, w, L)
        assert e is not None
        assert e.start_m == pytest.approx(first_m, abs=5.0) and e.start_speed_kph == pytest.approx(entry_kph, abs=3.0)
        a, b = w.window_m(L)
        assert a <= e.start_m <= b, (label, a, e.start_m, b)
        late[label] = w.est_onset_m - e.start_m
    assert late["T1-2"] > 45.0  # the estimate is late: a 45 m margin would not have covered the real stop
    assert max(late.values()) <= ONSET_UNCERTAINTY_M
