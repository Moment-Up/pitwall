"""Track outline prior (layer L1a): the F1 25 circuit shape before the driver's first lap.

Source: Pits n' Giggles ``assets/track-maps/f1_2025`` (MIT), vendored byte-identical under
``trackdata/third_party/pits_n_giggles/track-maps/`` (see ``PROVENANCE.md`` there). Each SVG holds one polyline
of 800 knots plus a closing duplicate: the mean world X/Z of the on-track field per lap-distance bin, i.e. the
de-facto racing line, drawn into SVG pixels by a per-track affine stored in ``svg_transforms.json``
(``docs/research/track-knowledge-sources.md`` section 2 "L1a", section 6.1 method B, section 8 phase 4).

Design decisions:

* **Data only, no upstream code.** The SVG is parsed with the stdlib XML parser; the affine is inverted here.
  Upstream's documented convention is ``svgX = a*worldX + b*worldZ + c`` and ``svgY = d*worldX + e*worldZ + f``
  with F1's ``m_worldPositionX/Z``, which pitwall stores unchanged as ``pos_x_m`` / ``pos_z_m``. Verified on the
  real PS5 Austria race (``20261010-191501``): the inverted line sits a median 1.2 m (RMS 2.5 m) from the driver's
  clean lap, while the three other axis/sign candidates sit 67-86 m away.
* **Lap distance by index fraction, never by arc length.** Knot ``i`` (0-based, closing duplicate dropped) is the
  lap-distance bin centre ``(i + 0.5) * L / n`` with ``L`` the game's ``m_trackLength``. On the same capture the
  driver's own lap distance agrees to a median +1.1 m (p95 +1.5 m, max 3.9 m). The polyline is ~1 % shorter than
  ``L`` (a racing line cuts corners), so arc length as lap distance would drift by tens of metres.
* **Length gate.** The outline is refused (``OutlineError``) when ``n * median knot spacing`` differs from ``L`` by
  ``MAX_LENGTH_MISMATCH`` (2 %) or more, or the closed path length by ``MAX_PATH_MISMATCH`` (3 %) or more: a wrong
  ``L`` (Monaco's 3067 m in the seeded sheet is truncated; the outline is 1.06 x it) or another layout must not
  produce a lap-distance map. The knots are uniform in lap distance, so the median spacing measures ``L``; the path is
  a racing line that cuts corners and runs 0.6-2.1 % short of ``L`` on all 27 layouts (Monaco at its probable game
  length 3323 m: -2.1 %), so a 2 % path gate would wrongly refuse Monaco (research section 2 "L1a"). The game's own
  ``m_trackLength`` (the live session) is preferred over the track sheet's ``lap_length_m``.
* **Physics geometry is separate from the drawn outline.** ``ArcTrack`` re-samples a periodic chord-length cubic
  spline at (about) 1 m of true arc length and takes curvature from the heading derivative, then smooths it with a
  periodic (wrap-mode) Gaussian, which preserves closure and the total turning angle. Sigma below 7.5 m lets the
  outline's 0.06-0.22 m lateral noise create phantom corners on straights (research section 5.2); 10 m is the default.
* **Curvature sign: F1's X/Z plane is mirrored.** Heading is ``atan2(dx, dz)`` (``sim.track`` convention), so
  positive curvature turns from +Z towards +X. In F1 25 that is a *left* turn: at every hand-verified turn of the
  Austria, Austria Reverse, Monza and Silverstone sheets the sign is opposite to the sheet's direction, and on the
  real Austria lap pitwall's steering (positive = right) has the opposite sign to the curvature at T1/T3/T4/T6.
  ``direction_of`` therefore maps negative curvature to ``"right"``. (A plot with +X right and +Z up, as
  ``web/src/lib/TrackMap.svelte`` draws, shows F1 circuits mirrored; Pits n' Giggles' own SVGs are not.)
* **Unknown stays unknown.** Only ``f1_25`` with a vendored outline is supported (Madrid and the legacy ids have
  none); anything else raises ``OutlineError`` instead of guessing. Synthetic track ids never match.
* **Pure and cached.** Parsing is cheap and cached per outline key; nothing here runs on the ingest path.
"""

from __future__ import annotations

import functools
import json
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.interpolate import CubicSpline
from scipy.ndimage import gaussian_filter1d

from pitwall import trackdata
from pitwall.analysis.track import CENTRELINE_STEP_M
from pitwall.sim.track import TrackGeometry

FloatArray = npt.NDArray[np.float64]

TIER_SHIPPED_SEED = "shipped_seed"  # provenance tier (track-knowledge-sources.md "Representing confidence")
OUTLINE_SOURCE = f"pits_n_giggles@{trackdata.PITS_N_GIGGLES_COMMIT[:7]}"
OUTLINE_LICENCE = "MIT"
OUTLINE_LABEL = "game outline (Pits n' Giggles)"
OUTLINE_ATTRIBUTION = (
    "Track outline derived from Pits n' Giggles (https://github.com/ashwin-nat/pits-n-giggles), "
    "Copyright (c) [2024] [Ashwin Natarajan], MIT License."
)
MAPS_DIR = ("track-maps", "f1_2025")
TRANSFORMS_FILE = "svg_transforms.json"
OUTLINE_GAMES = frozenset({"f1_25"})  # the f1_2025 maps; the 2026 Season Pack shares Game.F1_25 (Bahrain checked)

MAX_LENGTH_MISMATCH = 0.02  # n * median knot spacing must be within 2 % of the game's lap length
MAX_PATH_MISMATCH = 0.03  # and the closed path length within 3 % (a racing line runs up to 2.1 % short)
DEFAULT_SIGMA_M = 10.0
ARC_STEP_M = 1.0
_DENSE_STEP_M = 0.25  # spline sampling used to measure arc length
_CLOSE_PX = 1e-6

# Measured on pitwall's real PS5 F1 25 laps (8 layouts, 2026-10-10; tests/unit/test_track_geometry.py has the recorded
# check): the driver's clean laps sit a median 0.6-1.2 m from the outline (p95 2-6 m, up to 11 m on laps with offs),
# and the index-mapped lap distance agrees with the game's to a median +1.1-1.3 m, p99.9 |error| <= 4.8 m.
LATERAL_UNCERTAINTY_M = 3.0
ALONG_TRACK_UNCERTAINTY_M = 5.0

# F1 25 track id -> outline file stem (the same circuit names as the vendored track-segments' ``circuit_name``;
# tests cross-check this table against them). Madrid (42) has no outline at the pinned commit.
F1_25_OUTLINE_KEYS: Mapping[int, str] = {
    0: "Melbourne",
    2: "Shanghai",
    3: "Sakhir_Bahrain",
    4: "Catalunya",
    5: "Monaco",
    6: "Montreal",
    7: "Silverstone",
    9: "Hungaroring",
    10: "Spa",
    11: "Monza",
    12: "Singapore",
    13: "Suzuka",
    14: "Abu_Dhabi",
    15: "Texas",
    16: "Brazil",
    17: "Austria",
    19: "Mexico",
    20: "Baku_Azerbaijan",
    26: "Zandvoort",
    27: "Imola",
    29: "Jeddah",
    30: "Miami",
    31: "Las_Vegas",
    32: "Losail",
    39: "Silverstone_Reverse",
    40: "Austria_Reverse",
    41: "Zandvoort_Reverse",
}

__all__ = [
    "ALONG_TRACK_UNCERTAINTY_M",
    "DEFAULT_SIGMA_M",
    "F1_25_OUTLINE_KEYS",
    "LATERAL_UNCERTAINTY_M",
    "MAX_LENGTH_MISMATCH",
    "MAX_PATH_MISMATCH",
    "OUTLINE_LABEL",
    "OUTLINE_SOURCE",
    "TIER_SHIPPED_SEED",
    "ArcTrack",
    "LengthGate",
    "OutlineError",
    "SvgAffine",
    "TrackOutline",
    "build_outline",
    "direction_of",
    "knot_lap_distances",
    "length_gate",
    "load_outline_svg",
    "outline_from_knots",
    "outline_key",
    "parse_svg_polyline",
    "resample_arc",
]


class OutlineError(ValueError):
    """No usable outline: unsupported game/track, missing data, or the length gate refused it."""


# ============================================================================================ SVG + affine
@dataclass(frozen=True, slots=True)
class SvgAffine:
    """World (X, Z) metres -> SVG pixels: ``x = a*X + b*Z + c``, ``y = d*X + e*Z + f``."""

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    @classmethod
    def from_mapping(cls, m: Mapping[str, Any]) -> SvgAffine:
        try:
            vals = {k: float(m[k]) for k in ("a", "b", "c", "d", "e", "f")}
        except (KeyError, TypeError, ValueError) as e:
            raise OutlineError(f"svg transform: missing or non-numeric coefficient ({e})") from e
        if not all(math.isfinite(v) for v in vals.values()):
            raise OutlineError("svg transform: non-finite coefficient")
        aff = cls(**vals)
        if abs(aff.det) < 1e-12:
            raise OutlineError("svg transform: singular matrix")
        return aff

    @property
    def det(self) -> float:
        return self.a * self.e - self.b * self.d

    def to_svg(self, world_xz: FloatArray) -> FloatArray:
        w = np.asarray(world_xz, dtype=np.float64)
        x = self.a * w[..., 0] + self.b * w[..., 1] + self.c
        y = self.d * w[..., 0] + self.e * w[..., 1] + self.f
        return np.stack([x, y], axis=-1)

    def to_world(self, svg_xy: FloatArray) -> FloatArray:
        """Inverse of ``to_svg``: SVG pixels -> world (X, Z) metres (``pos_x_m``, ``pos_z_m``)."""
        p = np.asarray(svg_xy, dtype=np.float64)
        u = p[..., 0] - self.c
        v = p[..., 1] - self.f
        det = self.det
        x = (self.e * u - self.b * v) / det
        z = (-self.d * u + self.a * v) / det
        return np.stack([x, z], axis=-1)


_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_svg_polyline(text: str) -> FloatArray:
    """Points of the first ``<polyline>`` in an SVG document, as an ``(n, 2)`` array of pixels (stdlib XML only)."""
    if "<!DOCTYPE" in text or "<!ENTITY" in text:  # vendored data never needs them; refuse entity expansion
        raise OutlineError("svg: DOCTYPE/ENTITY declarations are not accepted")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise OutlineError(f"svg: not well-formed XML ({e})") from e
    poly = next((el for el in root.iter() if _local(el.tag) == "polyline"), None)
    if poly is None:
        raise OutlineError("svg: no <polyline> element")
    nums = [float(v) for v in _NUM_RE.findall(poly.get("points", ""))]
    if len(nums) % 2 or len(nums) < 8:
        raise OutlineError(f"svg: polyline needs an even number of coordinates (>= 4 points), got {len(nums)}")
    pts = np.asarray(nums, dtype=np.float64).reshape(-1, 2)
    if not np.isfinite(pts).all():
        raise OutlineError("svg: non-finite coordinate")
    return pts


def _maps_dir() -> Any:
    return trackdata.pits_n_giggles_dir().joinpath(*MAPS_DIR)


@functools.cache
def _transforms() -> dict[str, Any]:
    raw = json.loads(_maps_dir().joinpath(TRANSFORMS_FILE).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise OutlineError(f"{TRANSFORMS_FILE}: expected an object")
    return raw


@functools.cache
def load_outline_svg(key: str) -> tuple[FloatArray, SvgAffine]:
    """Vendored outline ``key`` (e.g. ``"Austria"``): SVG pixel points (closing duplicate kept) and its affine."""
    if key not in F1_25_OUTLINE_KEYS.values():
        raise OutlineError(f"no vendored outline named {key!r}")
    entry = _transforms().get(key)
    if not isinstance(entry, Mapping):
        raise OutlineError(f"{TRANSFORMS_FILE}: no transform for {key!r}")
    pts = parse_svg_polyline(_maps_dir().joinpath(f"{key}.svg").read_text(encoding="utf-8"))
    pts.setflags(write=False)
    return pts, SvgAffine.from_mapping(entry)


def outline_key(game: str | None, track_id: str | None) -> str | None:
    """The vendored outline for ``(game, track_id)`` such as ``("f1_25", "f1:17")`` -> ``"Austria"``; else None."""
    if game not in OUTLINE_GAMES or not isinstance(track_id, str):
        return None
    family, sep, raw = track_id.partition(":")
    if family != "f1" or not sep or not raw.isascii() or not raw.isdigit():
        return None
    return F1_25_OUTLINE_KEYS.get(int(raw))


# ============================================================================================ lap-distance map
def knot_lap_distances(n: int, track_length_m: float) -> FloatArray:
    """Lap distance of each of ``n`` outline knots: the bin centres ``(i + 0.5) * L / n`` (method B)."""
    return (np.arange(n, dtype=np.float64) + 0.5) * (track_length_m / n)


@dataclass(frozen=True, slots=True)
class LengthGate:
    track_length_m: float
    path_length_m: float  # closed polyline length
    spacing_length_m: float  # n * median knot spacing (robust to a few long or short segments)
    max_mismatch: float  # for the spacing length
    max_path_mismatch: float = MAX_PATH_MISMATCH

    @property
    def path_ratio(self) -> float:
        return self.path_length_m / self.track_length_m

    @property
    def spacing_ratio(self) -> float:
        return self.spacing_length_m / self.track_length_m

    @property
    def ok(self) -> bool:
        return abs(self.spacing_ratio - 1.0) < self.max_mismatch and abs(self.path_ratio - 1.0) < self.max_path_mismatch

    @property
    def reason(self) -> str | None:
        if self.ok:
            return None
        return (
            f"outline length {self.spacing_length_m:.0f} m (n x median spacing, limit {self.max_mismatch:.0%}) / "
            f"{self.path_length_m:.0f} m (path, limit {self.max_path_mismatch:.0%}) vs lap length "
            f"{self.track_length_m:.0f} m"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "track_length_m": self.track_length_m,
            "path_length_m": round(self.path_length_m, 1),
            "spacing_length_m": round(self.spacing_length_m, 1),
            "path_ratio": round(self.path_ratio, 4),
            "spacing_ratio": round(self.spacing_ratio, 4),
            "max_mismatch": self.max_mismatch,
            "max_path_mismatch": self.max_path_mismatch,
            "reason": self.reason,
        }


def _closed_segments(knots: FloatArray) -> FloatArray:
    return np.asarray(np.hypot(*(np.roll(knots, -1, axis=0) - knots).T), dtype=np.float64)


def length_gate(knots_xz: FloatArray, track_length_m: float, max_mismatch: float = MAX_LENGTH_MISMATCH) -> LengthGate:
    """|n * median spacing / L - 1| < ``max_mismatch`` and |L_path / L - 1| < ``MAX_PATH_MISMATCH``."""
    seg = _closed_segments(np.asarray(knots_xz, dtype=np.float64))
    return LengthGate(
        track_length_m=float(track_length_m),
        path_length_m=float(seg.sum()),
        spacing_length_m=float(len(seg) * np.median(seg)),
        max_mismatch=max_mismatch,
    )


def _wrap(d: FloatArray | float, length: float) -> FloatArray:
    return np.mod(np.asarray(d, dtype=np.float64), length)


def direction_of(curvature: float, flat: float = 1e-4) -> str | None:
    """F1 25 world frame: ``"right"`` for negative curvature, ``"left"`` for positive (module docstring); None if
    about straight."""
    if not math.isfinite(curvature) or abs(curvature) < flat:
        return None
    return "right" if curvature < 0 else "left"


# ============================================================================================ outline
@dataclass(slots=True)
class TrackOutline:
    """Game-frame outline knots with their lap distance. Positions are a prior (``shipped_seed``), never targets."""

    game: str
    track_id: str
    key: str
    track_length_m: float  # the lap length the index map uses (game m_trackLength when known)
    track_length_source: str  # "session" (the game's value) | "track_sheet" | "caller"
    knots_xz: FloatArray  # (n, 2) world X/Z metres, closing duplicate removed
    lap_distance_m: FloatArray  # (n,) knot lap distance, (i + 0.5) * L / n
    gate: LengthGate

    @property
    def n(self) -> int:
        return len(self.knots_xz)

    def position_at(self, d: FloatArray | float) -> FloatArray:
        """World (X, Z) at lap distance(s) ``d``, linear between knots, periodic across the line."""
        L = self.track_length_m
        dd = _wrap(d, L)
        xp = np.concatenate([[self.lap_distance_m[-1] - L], self.lap_distance_m, [self.lap_distance_m[0] + L]])
        kx = np.concatenate([[self.knots_xz[-1, 0]], self.knots_xz[:, 0], [self.knots_xz[0, 0]]])
        kz = np.concatenate([[self.knots_xz[-1, 1]], self.knots_xz[:, 1], [self.knots_xz[0, 1]]])
        return np.stack([np.interp(dd, xp, kx), np.interp(dd, xp, kz)], axis=-1)

    def centreline(self, step_m: float = CENTRELINE_STEP_M) -> list[tuple[float, float]]:
        """Points at lap distance 0, step, 2*step, ... (< L): the ``TrackModel.centreline`` shape TrackMap draws."""
        d = np.arange(0.0, self.track_length_m, step_m)
        pts = self.position_at(d)
        return [(round(float(x), 2), round(float(z), 2)) for x, z in pts]

    def project(self, xz: FloatArray) -> tuple[FloatArray, FloatArray]:
        """Lap distance and lateral offset (m) of world points projected onto the outline polyline.

        For validation and tests (O(points x knots) memory in chunks); not for the ingest path.
        """
        P = np.atleast_2d(np.asarray(xz, dtype=np.float64))
        K = self.knots_xz
        n = len(K)
        A = K
        AB = np.roll(K, -1, axis=0) - K
        ab2 = np.maximum((AB**2).sum(axis=1), 1e-12)
        out_d = np.empty(len(P))
        out_lat = np.empty(len(P))
        L = self.track_length_m
        for lo in range(0, len(P), 512):
            p = P[lo : lo + 512]
            ap = p[:, None, :] - A[None, :, :]
            u = np.clip((ap * AB[None, :, :]).sum(axis=2) / ab2[None, :], 0.0, 1.0)
            q = A[None, :, :] + u[:, :, None] * AB[None, :, :]
            dist = np.hypot(*(p[:, None, :] - q).transpose(2, 0, 1))
            j = dist.argmin(axis=1)
            rows = np.arange(len(p))
            idx = j + u[rows, j]
            out_d[lo : lo + len(p)] = np.mod((idx + 0.5) * L / n, L)
            out_lat[lo : lo + len(p)] = dist[rows, j]
        return out_d, out_lat

    def to_payload(self, *, include_knots: bool = True) -> dict[str, Any]:
        """JSON-ready outline for the dashboard. ``centreline`` is TrackModel-compatible (5 m of lap distance)."""
        out: dict[str, Any] = {
            "game": self.game,
            "track_id": self.track_id,
            "layout_key": self.key,
            "tier": TIER_SHIPPED_SEED,
            "source": OUTLINE_SOURCE,
            "licence": OUTLINE_LICENCE,
            "attribution": OUTLINE_ATTRIBUTION,
            "label": OUTLINE_LABEL,
            "ground_plane": ["pos_x_m", "pos_z_m"],
            "length_m": self.track_length_m,
            "track_length_source": self.track_length_source,
            "length_gate": self.gate.to_dict(),
            "uncertainty": {"lateral_m": LATERAL_UNCERTAINTY_M, "along_track_m": ALONG_TRACK_UNCERTAINTY_M},
            "centreline_step_m": CENTRELINE_STEP_M,
            "centreline": self.centreline(),
            "note": "Prior from recorded game data (the field's mean line), shown until pitwall learns the track "
            "from your laps. Not your line and not a target.",
        }
        if include_knots:
            out["points"] = [(round(float(x), 2), round(float(z), 2)) for x, z in self.knots_xz]
            out["lap_distance_m"] = [round(float(d), 2) for d in self.lap_distance_m]
        return out


def _drop_closing_duplicate(pts: FloatArray) -> FloatArray:
    if len(pts) > 3 and float(np.hypot(*(pts[0] - pts[-1]))) <= _CLOSE_PX:
        return pts[:-1]
    return pts


def outline_from_knots(
    knots_xz: FloatArray,
    track_length_m: float,
    *,
    game: str = "f1_25",
    track_id: str = "",
    key: str = "",
    track_length_source: str = "caller",
    max_mismatch: float = MAX_LENGTH_MISMATCH,
) -> TrackOutline:
    """Outline from world knots (closing duplicate optional). Raises ``OutlineError`` if the length gate refuses."""
    if not (isinstance(track_length_m, int | float) and math.isfinite(track_length_m) and track_length_m > 0):
        raise OutlineError(f"lap length must be a positive number of metres, got {track_length_m!r}")
    K = _drop_closing_duplicate(np.asarray(knots_xz, dtype=np.float64))
    if K.ndim != 2 or K.shape[1] != 2 or len(K) < 4 or not np.isfinite(K).all():
        raise OutlineError("outline needs >= 4 finite (x, z) knots")
    if (_closed_segments(K) <= 1e-9).any():
        raise OutlineError("outline has repeated consecutive knots")
    gate = length_gate(K, float(track_length_m), max_mismatch)
    if not gate.ok:
        raise OutlineError(gate.reason or "length gate")
    return TrackOutline(
        game=game,
        track_id=track_id,
        key=key,
        track_length_m=float(track_length_m),
        track_length_source=track_length_source,
        knots_xz=K,
        lap_distance_m=knot_lap_distances(len(K), float(track_length_m)),
        gate=gate,
    )


def _sheet_length(game: str, track_id: str) -> float | None:
    from pitwall.analysis.track_identity import SheetError, find_sheet

    try:
        sheet = find_sheet(game, track_id)
    except SheetError:
        return None
    return sheet.lap_length_m if sheet else None


def build_outline(game: str, track_id: str, track_length_m: float | None = None) -> TrackOutline:
    """The vendored outline for ``(game, track_id)`` in world metres with its lap-distance map.

    ``track_length_m`` should be the session's ``m_trackLength``; without it the track sheet's ``lap_length_m`` is
    used (seeded, possibly wrong: Monaco), and the length gate decides. Raises ``OutlineError``.
    """
    key = outline_key(game, track_id)
    if key is None:
        raise OutlineError(f"no outline for game={game!r} track_id={track_id!r}")
    source = "session"
    if track_length_m is None:
        track_length_m = _sheet_length(game, track_id)
        source = "track_sheet"
        if track_length_m is None:
            raise OutlineError(f"lap length unknown for {track_id!r}: pass the session's track length")
    svg, affine = load_outline_svg(key)
    knots = affine.to_world(svg)
    return outline_from_knots(
        knots, float(track_length_m), game=game, track_id=track_id, key=key, track_length_source=source
    )


# ============================================================================================ physics geometry
@dataclass(slots=True)
class ArcTrack:
    """The outline re-sampled at ~1 m of arc length with smoothed curvature, and the lap distance of every sample."""

    s: FloatArray  # arc length from knot 0 (m), uniform step
    x: FloatArray
    z: FloatArray
    heading: FloatArray  # rad, atan2(dx, dz)
    curvature: FloatArray  # 1/m, smoothed; positive turns from +Z towards +X (an F1 25 left turn)
    lap_distance_m: FloatArray  # game lap distance of each sample, through the knot table
    arc_length_m: float  # loop length along the spline
    track_length_m: float
    sigma_m: float

    @property
    def step_m(self) -> float:
        return self.arc_length_m / len(self.s)

    def lap_distance_at(self, s: FloatArray | float) -> FloatArray:
        """Game lap distance at arc length(s) ``s`` (periodic)."""
        ss = _wrap(s, self.arc_length_m)
        L = self.track_length_m
        unwrapped = np.unwrap(self.lap_distance_m, period=L)
        xp = np.concatenate([self.s, [self.arc_length_m]])
        fp = np.concatenate([unwrapped, [unwrapped[0] + L]])
        return np.asarray(np.mod(np.interp(ss, xp, fp), L), dtype=np.float64)

    def to_sim_track(self, name: str = "outline", roll: int = 0) -> TrackGeometry:
        """``sim.track.TrackGeometry`` for ``sim.driver.solve_lap``, optionally rotated to start at sample ``roll``."""
        k = np.roll(self.curvature, -roll)
        return TrackGeometry(
            name=name,
            s=self.s.copy(),
            x=np.roll(self.x, -roll),
            z=np.roll(self.z, -roll),
            heading=np.roll(self.heading, -roll),
            curvature=k,
            length_m=self.arc_length_m,
            corners=[],
        )


def resample_arc(outline: TrackOutline, sigma_m: float = DEFAULT_SIGMA_M, step_m: float = ARC_STEP_M) -> ArcTrack:
    """Periodic chord-length spline -> ~``step_m`` arc-length samples -> heading-derivative curvature, smoothed by a
    wrap-mode Gaussian of ``sigma_m`` (0 = none). Lap distance follows the knot table, never arc length."""
    if sigma_m < 0 or step_m <= 0:
        raise ValueError("sigma_m must be >= 0 and step_m > 0")
    K = outline.knots_xz
    closed = np.vstack([K, K[:1]])
    chord = np.hypot(*np.diff(closed, axis=0).T)  # > 0: outline_from_knots refuses repeated knots
    t = np.concatenate([[0.0], np.cumsum(chord)])
    spline = CubicSpline(t, closed, bc_type="periodic", axis=0)
    total_t = float(t[-1])
    n_dense = max(64, math.ceil(total_t / _DENSE_STEP_M))
    td = np.linspace(0.0, total_t, n_dense + 1)
    dense = spline(td)
    arc = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(dense, axis=0).T))])
    A = float(arc[-1])
    N = max(16, round(A / step_m))
    s = np.arange(N, dtype=np.float64) * (A / N)
    ts = np.interp(s, arc, td)
    xy = spline(ts)
    d1 = spline(ts, 1)
    heading = np.arctan2(d1[:, 0], d1[:, 1])
    ds = A / N
    dh = np.angle(np.exp(1j * (np.roll(heading, -1) - np.roll(heading, 1))))
    kappa = dh / (2.0 * ds)
    if sigma_m > 0:
        kappa = gaussian_filter1d(kappa, sigma=sigma_m / ds, mode="wrap")
    # knot table: knot i sits at spline parameter t[i] (arc length s_knot[i]) and lap distance (i + 0.5) * L / n
    s_knot = np.interp(t[:-1], td, arc)
    L = outline.track_length_m
    xp = np.concatenate([s_knot, [A]])
    fp = np.concatenate([outline.lap_distance_m, [outline.lap_distance_m[0] + L]])
    lap_d = np.mod(np.interp(s, xp, fp), L)
    return ArcTrack(
        s=s,
        x=xy[:, 0].astype(np.float64),
        z=xy[:, 1].astype(np.float64),
        heading=heading.astype(np.float64),
        curvature=np.asarray(kappa, dtype=np.float64),
        lap_distance_m=lap_d,
        arc_length_m=A,
        track_length_m=L,
        sigma_m=float(sigma_m),
    )
