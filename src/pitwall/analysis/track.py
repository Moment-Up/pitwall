"""Track intelligence: learn a circuit model (centreline + corners) from recorded clean laps.

Corner detection is speed-based (significant speed minima) on the median of the supplied clean laps, so a
single noisy lap cannot invent a corner. Corners are numbered T1..Tn by distance from the line. These are
*pitwall* numbers and may differ from official turn numbering (flat-out kinks are not detected as corners).
``Corner.name`` stays the stable join key; the optional identity fields at the end of ``Corner`` (official
label, numbers, curated name) are attached by ``pitwall.analysis.track_identity`` and never change positions.

Identity is *derived* data: it is re-attached from the shipped track sheets whenever a model is used, so it is never
persisted. ``TrackModel.to_dict()`` (what ``storage.repo.save_track_model`` stores) is the learned model only -
exactly the JSON shape written before the identity fields existed, so older code can still read new rows - and
``TrackModel.from_dict`` ignores identity and unknown keys, so rows written by any version (including the
2026-10-10 rows that carried null identity keys) load, and a stored label from an older sheet can never resurface.

Models are versioned and keyed by (game, track_id); braking references are NOT stored here because they
depend on the car - they come from reference laps.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

import numpy as np
from scipy.signal import find_peaks

from pitwall.analysis.distance import DistanceTrace

MIN_PROMINENCE_KPH = 8.0
MIN_CORNER_SPACING_M = 60.0
CENTRELINE_STEP_M = 5.0


@dataclass(slots=True)
class Corner:
    name: str
    apex_m: float  # distance of the reference minimum speed
    entry_m: float  # where the reference starts slowing (braking or lift)
    exit_m: float  # where the reference is back to full throttle (or apex + 100 m)
    seg_start_m: float  # analysis segment start (midpoint from previous apex, or 0)
    seg_end_m: float  # analysis segment end (midpoint to next apex, or lap length)
    direction: str | None  # "left" | "right" | None (from steering sign at apex)
    ref_min_speed_kph: float
    # Identity (layer L2), filled by ``analysis.track_identity.apply_identity``. Labels only - never positions.
    # All defaulted, so code that builds corners positionally is unaffected; never persisted (``IDENTITY_FIELDS``).
    label: str | None = None  # official short label, e.g. "T3" or "T2-4" (complex); None = no official number
    official_numbers: list[int] = field(default_factory=list)  # e.g. [2, 3, 4] for "T2-4"
    display_name: str | None = None  # curated corner name from the track sheet, e.g. "Remus"
    voice_ok: bool = False  # display_name may be spoken on the radio
    identity_tier: str | None = None  # "sheet_verified" | "sheet_seeded" | None (no identity attached)
    label_part: int | None = None  # 1-based, when several learned corners share one official label
    identity_match: str | None = None  # "inside" | "edge" (apex just outside the window) | "merged"; None = none


# Corner fields that carry identity (layer L2). Derived on use, never persisted (see the module docstring).
IDENTITY_FIELDS = (
    "label",
    "official_numbers",
    "display_name",
    "voice_ok",
    "identity_tier",
    "label_part",
    "identity_match",
)


@dataclass(slots=True)
class TrackModel:
    game: str
    track_id: str
    track_name: str | None
    length_m: float
    version: int = 1
    n_laps: int = 0
    corners: list[Corner] = field(default_factory=list)
    centreline: list[tuple[float, float]] = field(default_factory=list)  # ground-plane (a, b) every 5 m
    ground_plane: tuple[str, str] = ("pos_x_m", "pos_z_m")
    source_lap_ids: list[int] = field(default_factory=list)

    def corner(self, name: str) -> Corner | None:
        return next((c for c in self.corners if c.name.lower() == name.lower()), None)

    def corner_at(self, d: float) -> Corner | None:
        for c in self.corners:
            if c.seg_start_m <= d < c.seg_end_m:
                return c
        return None

    def to_dict(self, *, identity: bool = False) -> dict[str, Any]:
        """JSON-ready dict. By default the learned model only (the persisted shape, without ``IDENTITY_FIELDS``);
        ``identity=True`` keeps the identity fields, for API payloads (``track_identity.track_model_payload``)."""
        d = asdict(self)
        if not identity:
            for c in d["corners"]:
                for k in IDENTITY_FIELDS:
                    c.pop(k, None)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrackModel:
        """Inverse of ``to_dict()`` for stored rows of any version: identity and unknown keys are ignored."""
        model_keys = {f.name for f in fields(cls)}
        corner_keys = {f.name for f in fields(Corner)} - set(IDENTITY_FIELDS)
        d = {k: v for k, v in d.items() if k in model_keys}
        d["corners"] = [Corner(**{k: v for k, v in c.items() if k in corner_keys}) for c in d.get("corners", [])]
        d["centreline"] = [tuple(p) for p in d.get("centreline", [])]
        d["ground_plane"] = tuple(d.get("ground_plane", ("pos_x_m", "pos_z_m")))
        return cls(**d)


def _nanmedian_stack(traces: list[DistanceTrace], key: str) -> np.ndarray:
    """Per-bin median across laps, NaN where no lap has data. Computed only over bins with data instead of
    silencing numpy's "All-NaN slice" warning: warnings.catch_warnings swaps process-global filters and is not
    thread-safe (the analysis thread and the field-model worker both build track models)."""
    stack = np.vstack([t.t_s if key == "t_s" else t.ch[key] for t in traces])
    out = np.full(stack.shape[1], np.nan)
    cols = np.isfinite(stack).any(axis=0)
    if cols.any():
        out[cols] = np.nanmedian(stack[:, cols], axis=0)
    return out


def build_track_model(
    game: str,
    track_id: str,
    track_name: str | None,
    length_m: float,
    clean_traces: list[DistanceTrace],
    ground_plane: tuple[str, str] = ("pos_x_m", "pos_z_m"),
    source_lap_ids: list[int] | None = None,
    version: int = 1,
) -> TrackModel:
    if not clean_traces:
        raise ValueError("need at least one clean lap to build a track model")
    d = clean_traces[0].d
    speed = _nanmedian_stack(clean_traces, "speed_kph")
    throttle = _nanmedian_stack(clean_traces, "throttle")
    brake = _nanmedian_stack(clean_traces, "brake")
    steer = _nanmedian_stack(clean_traces, "steering")
    step = float(d[1] - d[0])
    filled = np.where(np.isfinite(speed), speed, np.nanmax(speed))
    peaks, _ = find_peaks(-filled, prominence=MIN_PROMINENCE_KPH, distance=max(1, int(MIN_CORNER_SPACING_M / step)))
    apexes = [float(d[p]) for p in peaks]

    corners: list[Corner] = []
    for k, p in enumerate(peaks):
        apex = float(d[p])
        # entry: last braking onset within 400 m before the apex, else the speed peak (lift) within 300 m
        lo = max(0, p - int(400 / step))
        on = np.nan_to_num(brake[lo : p + 1], nan=0.0) >= 0.05
        onsets = np.nonzero(on[1:] & ~on[:-1])[0]
        if len(onsets):
            entry = float(d[lo + onsets[-1] + 1])
        else:
            lo = max(0, p - int(300 / step))
            entry = float(d[lo + int(np.argmax(filled[lo : p + 1]))])
        # exit: first full-throttle point after the apex
        j = p
        n = len(d)
        while j < n - 1 and not (throttle[j] >= 0.95):
            j += 1
        exit_m = float(d[j]) if j < n - 1 else min(apex + 100.0, length_m)
        seg_start = 0.0 if k == 0 else (apexes[k - 1] + apex) / 2
        seg_end = length_m if k == len(peaks) - 1 else (apex + apexes[k + 1]) / 2
        win = slice(max(0, p - 10), min(n, p + 10))
        s_mean = float(np.nanmean(steer[win])) if np.isfinite(steer[win]).any() else 0.0
        direction = "right" if s_mean > 0.02 else "left" if s_mean < -0.02 else None
        corners.append(
            Corner(
                name=f"T{k + 1}",
                apex_m=apex,
                entry_m=entry,
                exit_m=exit_m,
                seg_start_m=seg_start,
                seg_end_m=seg_end,
                direction=direction,
                ref_min_speed_kph=float(filled[p]),
            )
        )

    # centreline from median ground-plane position
    a = _nanmedian_stack(clean_traces, ground_plane[0])
    b = _nanmedian_stack(clean_traces, ground_plane[1])
    stride = max(1, int(CENTRELINE_STEP_M / step))
    centre = [
        (round(float(x), 2), round(float(z), 2))
        for x, z in zip(a[::stride], b[::stride], strict=True)
        if np.isfinite(x) and np.isfinite(z)
    ]
    return TrackModel(
        game=game,
        track_id=track_id,
        track_name=track_name,
        length_m=length_m,
        version=version,
        n_laps=len(clean_traces),
        corners=corners,
        centreline=centre,
        ground_plane=ground_plane,
        source_lap_ids=source_lap_ids or [],
    )
