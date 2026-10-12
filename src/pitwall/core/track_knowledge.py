"""Track knowledge resolver: one ``TrackKnowledge`` snapshot from every layer that knows the current circuit.

Layers (research: ``docs/research/track-knowledge-sources.md`` section 2, precedence for *positions*, highest first):

* **L3  learned** - the ``TrackModel`` from the driver's own clean laps (``analysis.track``). Authoritative.
* **L0b field_observed** - the AI field of this session (``analysis.field_model``), usable from support >= 3
  car-laps. An *AI reference*, never the driver's target.
* **L1c physics_predicted** - severity tags only, never positions (``PhysicsPrior``; ``PhysicsPrior.from_payload``
  reads ``analysis.brake_prior.BrakePrior.to_payload()``, whose own tier label ``physics_prior`` is kept).

Identity (layer L2, official turn numbers / names) attaches to whichever corner set is current, through the existing
track sheets (``analysis.track_identity``). A higher layer supersedes a lower one but never edits it: field braking
zones that a learned corner covers stay in the snapshot, marked ``superseded_by="learned"``.

Heads-up candidates (``TrackKnowledge.heads_up``): field braking zones with support >= ``MIN_SUPPORT`` car-laps,
placed conservatively *early* at ``FieldBrakeZone.heads_up_m`` (field onset minus its lower spread, and at least
``MIN_HEADS_UP_EARLY_M`` = 15 m before the field's onset). The AI field is not always earlier than the driver: on
real PS5 data this driver braked 4-54 m *before* the AI onset at some stops (Austria Reverse T1, Silverstone T15,
Las Vegas T12), and AI difficulty is unknown. So the phrase starts ``HEADS_UP_LEAD_S`` (2.5 s, ~200 m at 300 km/h)
before that point and ends well before the driver's own braking. They are never phrased as a target and never say
"brake": ``heads_up_cue_plan`` turns them into ``MARKER`` cues ("heavy braking ahead") for the cue engine, which
should use them only while it has no plan from the driver's own reference lap, and in its default ``focus`` mode
only for the heaviest ``FocusLimits.max_corners`` stops (``CuePlan.focus`` lists them in priority order; a beginner
gets one). CLAUDE.md: coaching never recommends braking later on its own.

Runtime pieces (the lead wires them; see the component report):

* ``FieldWorker`` - runs a ``FieldModel`` on its own thread. ``submit`` is lock-free and never blocks the ingest
  thread: a bounded deque, newest sample dropped (and counted) when full. Snapshots every ``snapshot_interval_s``.
  A replay (never the UDP thread) uses its own worker with ``block_when_full`` so a max-speed replay is not lossy.
* ``TrackKnowledgeResolver`` - thread-safe; recomputes on every input change and publishes through a callback
  (``LiveState`` snapshot key ``track_knowledge``, the cue engine's heads-up plan).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from array import array
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from pitwall.analysis.field_model import (
    MIN_SUPPORT,
    FieldBrakeZone,
    FieldFilter,
    FieldModel,
    FieldSnapshot,
)
from pitwall.analysis.track import TrackModel
from pitwall.analysis.track_identity import corner_texts, identify
from pitwall.coach.cues import WINDOW_M, CueApproach, CueKind, CueMode, CuePlan, CueSpec, parse_cue_mode
from pitwall.model.telemetry import FieldSample, SessionInfo, SessionType

log = logging.getLogger(__name__)

Tier = Literal["learned", "field_observed", "physics_predicted"]
TIER_LEARNED: Tier = "learned"
TIER_FIELD: Tier = "field_observed"
TIER_PHYSICS: Tier = "physics_predicted"
SOURCE_LEARNED = "driver laps"
SOURCE_FIELD = "AI field"

HEADS_UP_PHRASE = "heavy braking ahead"
HEADS_UP_LEAD_S = 2.5  # the phrase starts this long before the (already early) heads-up point (research: >= 2 s)
HEADS_UP_SEVERITIES = frozenset({"heavy"})
LEARNED_MATCH_M = 40.0  # a field zone whose minimum is this close to a learned apex belongs to that corner
LEARNED_LINE_COVERAGE = 0.9  # the learned centreline replaces the field line once it covers this share of the lap
FIELD_LINE_COVERAGE = 0.9  # the field's line is published only once the field has driven this share of the lap
SNAPSHOT_INTERVAL_S = 5.0
MAX_QUEUE = 8192  # ~40 s of a 20-car field at 10 Hz
POLL_S = 0.05
BLOCK_POLL_S = 0.001  # block_when_full: how often a waiting replay thread re-checks for room


# ============================================================================================== L1c interface
@dataclass(slots=True, frozen=True)
class SeverityTag:
    """A physics-predicted heavy stop (layer L1c): *which* corner is severe, never where to brake."""

    window_start_m: float
    window_end_m: float
    severity: str  # "heavy" | "medium"
    gated: bool  # passed the sigma-ensemble voice gate (research section 2, L1c)
    label: str | None = None


@dataclass(slots=True, frozen=True)
class PhysicsPrior:
    """What the resolver needs from a physics prior (layer L1c): gated severity windows, never positions."""

    game: str
    track_id: str
    tags: tuple[SeverityTag, ...]
    source: str  # e.g. "qss@<model-hash>"
    tier: str = TIER_PHYSICS
    car_family: str | None = None  # the carclass family whose braking curve and measured error it carries
    caveat: str | None = None  # the family's caveat (its measured onset error), shown with the layer

    @classmethod
    def from_payload(cls, d: Mapping[str, Any]) -> PhysicsPrior | None:
        """From ``analysis.brake_prior.BrakePrior.to_payload()`` (its windows are the gated heavy stops). Read
        through the JSON contract, so this module does not depend on the prior's implementation; None when the
        payload is not a prior for one track."""
        game, track_id = d.get("game"), d.get("track_id")
        if not isinstance(game, str) or not isinstance(track_id, str):
            return None
        tags: list[SeverityTag] = []
        for w in d.get("windows") or ():
            win = w.get("window_m") if isinstance(w, Mapping) else None
            if not (isinstance(win, list | tuple) and len(win) == 2):
                continue
            a, b = _num(win[0]), _num(win[1])
            if a is None or b is None:
                continue
            turn = w.get("turn")
            label = turn.get("label") if isinstance(turn, Mapping) else None
            tags.append(SeverityTag(a, b, "heavy", gated=True, label=label if isinstance(label, str) else None))
        tier, source = d.get("tier"), d.get("source")
        fam, caveat = d.get("car_family"), d.get("caveat")
        return cls(
            game=game,
            track_id=track_id,
            tags=tuple(tags),
            source=source if isinstance(source, str) else "physics",
            tier=tier if isinstance(tier, str) else TIER_PHYSICS,
            car_family=fam if isinstance(fam, str) else None,
            caveat=caveat if isinstance(caveat, str) else None,
        )


# ============================================================================================== snapshot
@dataclass(slots=True, frozen=True)
class HeadsUp:
    """A lap-1 heads-up candidate: "heavy braking ahead" timed to ``target_m`` (an AI reference, never a target)."""

    key: str  # corner key in this snapshot ("T3" learned, "F2" field) or "zone@<onset>"
    target_m: float  # conservative early point: field onset minus max(its uncertainty, 15 m)
    onset_m: float  # the AI field's median onset (later than target_m by uncertainty_m)
    uncertainty_m: float
    severity: str
    support: int
    cars: int
    entry_speed_kph: float
    min_speed_kph: float
    label: str | None  # official label ("T3") when identity is certain enough to show
    voice: str | None  # how the radio may name the corner ("Turn 3"), None = do not name it
    tier: str = TIER_FIELD
    source: str = SOURCE_FIELD
    phrase: str = HEADS_UP_PHRASE

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "target_m": _r(self.target_m, 1),
            "onset_m": _r(self.onset_m, 1),
            "uncertainty_m": _r(self.uncertainty_m, 1),
            "severity": self.severity,
            "support": self.support,
            "cars": self.cars,
            "entry_speed_kph": _r(self.entry_speed_kph, 0),
            "min_speed_kph": _r(self.min_speed_kph, 0),
            "label": self.label,
            "voice": self.voice,
            "tier": self.tier,
            "source": self.source,
            "phrase": self.phrase,
        }


@dataclass(slots=True)
class TrackKnowledge:
    """What pitwall knows about the current circuit, by layer and tier. ``to_dict()`` is strict-JSON-safe."""

    game: str | None
    track_id: str | None
    track_name: str | None
    track_length_m: float | None
    session_uid: str | None
    synthetic: bool
    version: int
    positions: Tier | None  # layer that owns corner positions now
    layers: dict[str, dict[str, Any]]
    corners: list[dict[str, Any]]
    braking_zones: list[dict[str, Any]]
    heads_up: tuple[HeadsUp, ...]
    severity_tags: list[dict[str, Any]]
    line: dict[str, Any] | None
    speed_profile: dict[str, Any] | None
    # kept for the cue plan, never serialised as such
    _speed_kph: np.ndarray | None = field(default=None, repr=False)
    _bin_m: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game,
            "track_id": self.track_id,
            "track_name": self.track_name,
            "track_length_m": self.track_length_m,
            "session_uid": self.session_uid,
            "synthetic": self.synthetic,
            "version": self.version,
            "positions": self.positions,
            "layers": self.layers,
            "corners": self.corners,
            "braking_zones": self.braking_zones,
            "heads_up": [h.to_dict() for h in self.heads_up],
            "severity_tags": self.severity_tags,
            "line": self.line,
            "speed_profile": self.speed_profile,
        }


# ============================================================================================== resolver
@dataclass(slots=True, frozen=True)
class _Learned:
    """A learned (L3) corner, normalised from a ``TrackModel`` or its API payload."""

    name: str
    apex_m: float
    entry_m: float
    exit_m: float
    min_speed_kph: float | None
    direction: str | None
    label: str | None
    short: str
    long: str
    voice: str


class TrackKnowledgeResolver:
    """Combines L3 > L0b > L1c into ``TrackKnowledge`` and publishes every change through ``publish``.

    All setters are thread-safe (the analysis thread sets L3; the field worker sets L0b and, through its
    ``on_session`` hook, the session) and cheap when nothing changed. ``publish`` receives every new snapshot in
    order (a resolve overtaken by a newer input never publishes after it); it must not call back into the resolver.
    """

    def __init__(
        self,
        publish: Callable[[TrackKnowledge | None], None] | None = None,
        *,
        min_support: int = MIN_SUPPORT,
    ) -> None:
        self._publish = publish
        self.min_support = max(1, min_support)
        self._lock = threading.Lock()
        self._publish_lock = threading.Lock()  # publishes in version order
        self._info: SessionInfo | None = None
        self._info_key: tuple[Any, ...] | None = None
        self._learned: TrackModel | Mapping[str, Any] | None = None
        self._field: FieldSnapshot | None = None
        self._physics: PhysicsPrior | None = None
        self._version = 0
        self._knowledge: TrackKnowledge | None = None
        self.errors = 0

    @property
    def knowledge(self) -> TrackKnowledge | None:
        return self._knowledge

    # ------------------------------------------------------------------ inputs (any thread)
    def set_session(self, info: SessionInfo | None) -> None:
        """Session context (2 Hz on F1): only a different session, track or skeleton triggers a re-resolve."""
        key = None if info is None else _session_key(info)
        with self._lock:
            if key == self._info_key:
                self._info = info
                return
            changed_track = self._info_key is None or key is None or self._info_key[1:3] != key[1:3]
            self._info, self._info_key = info, key
            if changed_track:
                self._learned = self._learned if _same_track(self._learned, info) else None
                self._field = self._field if _same_track(self._field, info) else None
                self._physics = self._physics if _same_track(self._physics, info) else None
        self._resolve()

    def set_learned(self, model: TrackModel | Mapping[str, Any] | None) -> None:
        """Layer L3: a ``TrackModel`` or its API payload (``LiveState.track_model``); ``None`` clears it.

        Re-installing the object the resolver already holds is O(1) and publishes nothing: the session manager does
        exactly that on the INGEST thread after a driver change (``SessionManager._split_for_driver`` keeps the live
        map), where a resolve (1-25 ms, and a wait on the publish lock) must never run. A new model comes from the
        analysis thread."""
        with self._lock:
            if model is self._learned:
                return
            self._learned = model
        self._resolve()

    def set_field(self, snap: FieldSnapshot | None) -> None:
        """Layer L0b: the field worker's latest snapshot; ``None`` clears it (new session)."""
        with self._lock:
            self._field = snap
        self._resolve()

    def set_physics(self, prior: PhysicsPrior | None) -> None:
        """Layer L1c, e.g. ``PhysicsPrior.from_payload(analysis.brake_prior.build_brake_prior(...).to_payload())``;
        ``None`` clears it. Severity only: it never places a braking point."""
        with self._lock:
            self._physics = prior
        self._resolve()

    # ------------------------------------------------------------------ resolve
    def _resolve(self) -> None:
        with self._lock:
            info, learned, fld, physics = self._info, self._learned, self._field, self._physics
            self._version += 1
            version = self._version
        try:
            k = resolve_track_knowledge(info, learned, fld, physics, version=version, min_support=self.min_support)
        except Exception:
            self.errors += 1
            log.exception("track knowledge resolve failed; keeping the previous snapshot")
            return
        with self._publish_lock:
            with self._lock:
                if version != self._version:
                    return  # a newer input arrived while this one was resolving: its own resolve publishes
                self._knowledge = k
            publish = self._publish
            if publish is not None:
                try:
                    publish(k)
                except Exception:
                    self.errors += 1
                    log.exception("track knowledge publish failed")


def _session_key(info: SessionInfo) -> tuple[Any, ...]:
    z = info.track_zones
    return (
        info.session_uid,
        info.track_id,
        info.track_length_m,
        None if z is None else z.geometry_key(),
        bool(info.extra.get("synthetic")),
    )


type _Layer = TrackModel | Mapping[str, Any] | FieldSnapshot | PhysicsPrior | None


def _track_of(obj: _Layer) -> str | None:
    if obj is None:
        return None
    tid = obj.get("track_id") if isinstance(obj, Mapping) else obj.track_id
    return tid if isinstance(tid, str) else None


def _same_track(obj: _Layer, info: SessionInfo | None) -> bool:
    return obj is not None and info is not None and _track_of(obj) == info.track_id


def resolve_track_knowledge(
    info: SessionInfo | None,
    learned: TrackModel | Mapping[str, Any] | None,
    fld: FieldSnapshot | None,
    physics: PhysicsPrior | None = None,
    *,
    version: int = 0,
    min_support: int = MIN_SUPPORT,
) -> TrackKnowledge | None:
    """Pure resolution of the layers (see the module docstring). Inputs for another track than the session's are
    ignored; without a session nothing is known."""
    if info is None or not info.track_id:
        return None
    track_id = info.track_id
    length = info.track_length_m if info.track_length_m and info.track_length_m > 0 else None
    l3 = _learned_corners(learned) if _track_of(learned) == track_id else []
    fs = fld if fld is not None and fld.track_id == track_id else None
    pp = physics if physics is not None and physics.track_id == track_id else None
    positions: Tier | None = TIER_LEARNED if l3 else TIER_FIELD if fs is not None and fs.corners else None

    field_text: dict[str, tuple[str | None, str, str | None]] = {}
    if fs is not None and fs.corners:
        field_text = _field_identity(fs, info)

    corners: list[dict[str, Any]] = []
    if l3:
        corners = [
            {
                "key": c.name,
                "name": c.name,
                "label": c.label,
                "text": {"short": c.short, "long": c.long, "voice": c.voice},
                "apex_m": _r(c.apex_m, 1),
                "entry_m": _r(c.entry_m, 1),
                "exit_m": _r(c.exit_m, 1),
                "min_speed_kph": _r(c.min_speed_kph, 1),
                "direction": c.direction,
                "tier": TIER_LEARNED,
                "source": SOURCE_LEARNED,
            }
            for c in l3
        ]
    elif fs is not None:
        for c in fs.corners:
            label, short, voice = field_text.get(c.name, (None, c.name, None))
            corners.append(
                {
                    "key": c.name,
                    "name": c.name,
                    "label": label,
                    "text": {"short": short, "long": short, "voice": voice},
                    "apex_m": _r(c.apex_m, 1),
                    "entry_m": _r(c.entry_m, 1),
                    "exit_m": _r(c.exit_m, 1),
                    "min_speed_kph": _r(c.ref_min_speed_kph, 1),
                    "direction": c.direction,
                    "tier": TIER_FIELD,
                    "source": SOURCE_FIELD,
                }
            )

    zones: list[dict[str, Any]] = []
    heads: list[HeadsUp] = []
    if fs is not None:
        flen = fs.track_length_m
        for z in fs.braking_zones:
            owner = _learned_owner(l3, z, flen)
            key, label, voice = _zone_identity(z, owner, field_text)
            zones.append(
                {
                    **z.to_dict(),
                    "key": key,
                    "label": label,
                    "superseded_by": TIER_LEARNED if owner is not None else None,
                }
            )
            if z.support >= min_support:
                heads.append(
                    HeadsUp(
                        key=key,
                        target_m=z.heads_up_m,
                        onset_m=z.onset_m,
                        uncertainty_m=z.uncertainty_m,
                        severity=z.severity,
                        support=z.support,
                        cars=z.cars,
                        entry_speed_kph=z.entry_speed_kph,
                        min_speed_kph=z.min_speed_kph,
                        label=label,
                        voice=voice,
                    )
                )
    heads.sort(key=lambda h: h.target_m)

    tags: list[dict[str, Any]] = []
    if pp is not None:
        for t in pp.tags:
            if not t.gated:
                continue  # an ungated physics zone is never used (research section 2, L1c)
            a, b = t.window_start_m, t.window_end_m
            covered = any(_overlaps(c.entry_m, c.apex_m, a, b, length) for c in l3) or any(
                _overlaps(z.onset_m, z.min_speed_m, a, b, length) for z in (fs.braking_zones if fs is not None else ())
            )
            if not covered:
                tags.append(
                    {
                        "window_start_m": _r(t.window_start_m, 1),
                        "window_end_m": _r(t.window_end_m, 1),
                        "severity": t.severity,
                        "label": t.label,
                        "tier": pp.tier,
                        "source": pp.source,
                    }
                )

    line = _line(learned if l3 else None, fs, length)
    speed_profile = None
    if fs is not None:
        speed_profile = {
            "tier": TIER_FIELD,
            "source": SOURCE_FIELD,
            "step_m": fs.bin_m,
            "speed_kph": [_r(float(v), 1) for v in fs.speed_kph],
            "speed_iqr_kph": [_r(float(v), 1) for v in fs.speed_iqr_kph],
            "brake_frac": [_r(float(v), 2) for v in fs.brake_frac],
            "support": [int(v) for v in fs.support],
        }
    layers: dict[str, dict[str, Any]] = {
        "L3": {
            "tier": TIER_LEARNED,
            "available": bool(l3),
            "version": _learned_attr(learned, "version") if l3 else None,
            "n_laps": _learned_attr(learned, "n_laps") if l3 else None,
            "corners": len(l3),
        },
        "L0b": {
            "tier": TIER_FIELD,
            "source": SOURCE_FIELD,
            "available": fs is not None,
            "version": fs.version if fs is not None else None,
            "car_laps": fs.car_laps if fs is not None else 0,
            "cars": fs.cars if fs is not None else 0,
            "coverage": round(fs.coverage, 3) if fs is not None else 0.0,
            "braking_zones": len(fs.braking_zones) if fs is not None else 0,
            "heads_up": len(heads),
            "min_support": min_support,
            "brake_envelope": fs.brake_envelope.to_dict() if fs is not None and fs.brake_envelope else None,
            "counts": dict(fs.counts) if fs is not None else {},
        },
        "L1c": {
            "tier": pp.tier if pp is not None else TIER_PHYSICS,
            "available": pp is not None,
            "source": pp.source if pp is not None else None,
            "severity_tags": len(tags),
            "car_family": pp.car_family if pp is not None else None,  # F2: its own braking curve and error
            "caveat": pp.caveat if pp is not None else None,
        },
    }
    return TrackKnowledge(
        game=info.game.value,
        track_id=track_id,
        track_name=info.track_name,
        track_length_m=length,
        session_uid=info.session_uid,
        synthetic=bool(info.extra.get("synthetic")),
        version=version,
        positions=positions,
        layers=layers,
        corners=corners,
        braking_zones=zones,
        heads_up=tuple(heads),
        severity_tags=tags,
        line=line,
        speed_profile=speed_profile,
        _speed_kph=None if fs is None else fs.speed_kph.copy(),
        _bin_m=fs.bin_m if fs is not None else 5.0,
    )


def _learned_attr(model: TrackModel | Mapping[str, Any] | None, name: str) -> Any:
    if model is None:
        return None
    return model.get(name) if isinstance(model, Mapping) else getattr(model, name, None)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _learned_corners(model: TrackModel | Mapping[str, Any] | None) -> list[_Learned]:
    if model is None:
        return []
    out: list[_Learned] = []
    if isinstance(model, TrackModel):
        texts = corner_texts(model)
        for c in model.corners:
            t = texts.get(c.name)
            out.append(
                _Learned(
                    name=c.name,
                    apex_m=c.apex_m,
                    entry_m=c.entry_m,
                    exit_m=c.exit_m,
                    min_speed_kph=c.ref_min_speed_kph,
                    direction=c.direction,
                    label=c.label,
                    short=t.short if t else c.name,
                    long=t.long if t else c.name,
                    voice=t.voice if t else c.name,
                )
            )
        return out
    raw_text = model.get("corner_text")
    text = raw_text if isinstance(raw_text, Mapping) else {}
    for c in model.get("corners") or ():
        if not isinstance(c, Mapping):
            continue
        name, apex, entry, exit_m = c.get("name"), _num(c.get("apex_m")), _num(c.get("entry_m")), _num(c.get("exit_m"))
        if not isinstance(name, str) or apex is None or entry is None or exit_m is None:
            continue
        raw = text.get(name)
        tx: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
        label, direction = c.get("label"), c.get("direction")
        out.append(
            _Learned(
                name=name,
                apex_m=apex,
                entry_m=entry,
                exit_m=exit_m,
                min_speed_kph=_num(c.get("ref_min_speed_kph")),
                direction=direction if isinstance(direction, str) else None,
                label=label if isinstance(label, str) else None,
                short=str(tx.get("short") or name),
                long=str(tx.get("long") or name),
                voice=str(tx.get("voice") or name),
            )
        )
    return out


def _field_identity(fs: FieldSnapshot, info: SessionInfo) -> dict[str, tuple[str | None, str, str | None]]:
    """{field corner: (official label, short text, voice text or None)} through the track sheets (layer L2)."""
    fmt = info.extra.get("packet_format")
    model, _mapping = identify(
        fs.as_track_model(), zones=info.track_zones, packet_format=fmt if isinstance(fmt, int) else None
    )
    mapped = any(c.identity_tier is not None for c in model.corners)
    texts = corner_texts(model)
    out: dict[str, tuple[str | None, str, str | None]] = {}
    for c in model.corners:
        t = texts[c.name]
        # an unlabelled corner of an unmapped model is only "F3": never spoken
        voice = t.voice if c.label or (mapped and c.display_name and c.voice_ok) else None
        out[c.name] = (c.label, t.short, voice)
    return out


def _signed(delta: float, length: float) -> float:
    return (delta + 0.5 * length) % length - 0.5 * length


def _learned_owner(l3: Sequence[_Learned], z: FieldBrakeZone, length: float) -> _Learned | None:
    near = [c for c in l3 if abs(_signed(c.apex_m - z.min_speed_m, length)) <= LEARNED_MATCH_M]
    return min(near, key=lambda c: abs(_signed(c.apex_m - z.min_speed_m, length))) if near else None


def _zone_identity(
    z: FieldBrakeZone, owner: _Learned | None, field_text: Mapping[str, tuple[str | None, str, str | None]]
) -> tuple[str, str | None, str | None]:
    """(key, label, voice) of a field zone: the learned corner it belongs to, else its provisional corner."""
    if owner is not None:
        return owner.name, owner.label, owner.voice if owner.label else None
    if z.corner is not None:
        label, _short, voice = field_text.get(z.corner, (None, z.corner, None))
        return z.corner, label, voice
    return f"zone@{z.onset_m:.0f}", None, None


def _in_window(d: float, lo: float, hi: float, length: float | None) -> bool:
    if length is None:
        return lo <= d <= hi
    return (d - lo) % length <= (hi - lo) % length


def _overlaps(a1: float, b1: float, a2: float, b2: float, length: float | None) -> bool:
    """Whether the lap-distance spans [a1, b1] and [a2, b2] (cyclic when the length is known) overlap."""
    return _in_window(a2, a1, b1, length) or _in_window(a1, a2, b2, length)


def _line(
    learned: TrackModel | Mapping[str, Any] | None, fs: FieldSnapshot | None, length: float | None
) -> dict[str, Any] | None:
    """The map line: the learned centreline once it covers the lap, else the field's median line once the field
    covers ``FIELD_LINE_COVERAGE`` of the lap (a partial line would make a map draw chords across track nobody has
    driven yet: unknown stays unknown), else None. Unknown bins of the field line are ``[None, None]``."""
    centre = _learned_attr(learned, "centreline")
    if isinstance(centre, Sequence) and length and len(centre) * 5.0 >= LEARNED_LINE_COVERAGE * length:
        pts = [[_r(_num(p[0]), 1), _r(_num(p[1]), 1)] for p in centre if isinstance(p, Sequence) and len(p) == 2]
        return {"tier": TIER_LEARNED, "source": SOURCE_LEARNED, "step_m": 5.0, "points": pts}
    if fs is not None and fs.coverage >= FIELD_LINE_COVERAGE:
        pts = [[_r(float(x), 1), _r(float(z), 1)] for x, z in zip(fs.x_m, fs.z_m, strict=True)]
        return {"tier": TIER_FIELD, "source": SOURCE_FIELD, "step_m": fs.bin_m, "points": pts}
    return None


# ============================================================================================== cue plan
def heads_up_cue_plan(
    knowledge: TrackKnowledge | None,
    mode: str = "markers",
    *,
    severities: frozenset[str] = HEADS_UP_SEVERITIES,
    lead_s: float = HEADS_UP_LEAD_S,
) -> CuePlan | None:
    """A ``CuePlan`` of "heavy braking ahead" heads-ups from the field (``MARKER`` cues: the phrase starts
    ``lead_s`` before the conservative early heads-up point; never a "brake" call, never later than 15 m before the
    field's onset). ``None`` when there is nothing to call (mode off, no heads-ups, unknown length).

    ``CuePlan.focus`` lists the heads-ups' keys by priority (largest speed drop first): in ``focus`` mode the cue
    engine keeps only the first ``FocusLimits.max_corners`` of them, so the driver's coaching profile caps the
    calls (a beginner gets one per lap). For the cue engine's fallback slot: the engine fires it exactly like its
    own plans (same timing rules, one call per corner per lap, no calls in pit / out laps, standing starts or under
    safety car), and only while it has no plan from the driver's own reference lap.
    """
    m: CueMode = parse_cue_mode(mode)
    if m == "off" or knowledge is None:
        return None
    length = knowledge.track_length_m
    if length is None or length <= 0:
        return None
    heads = [h for h in knowledge.heads_up if h.severity in severities]
    if not heads:
        return None
    speed = knowledge._speed_kph
    specs: list[CueSpec] = []
    approaches: list[CueApproach | None] = []
    seen: set[str] = set()
    kept: list[HeadsUp] = []
    for h in sorted(heads, key=lambda h: h.target_m):
        if h.key in seen:
            continue  # the engine resolves one call per corner key per lap
        seen.add(h.key)
        kept.append(h)
        specs.append(
            CueSpec(
                corner=h.key,
                kind=CueKind.MARKER,
                target_m=h.target_m,
                text=HEADS_UP_PHRASE,
                parts=(HEADS_UP_PHRASE,),
                key_index=0,
                anticipation_s=lead_s,
                focus=False,
                reason=f"AI field: {h.support} car-laps brake from {h.onset_m:.0f} m ({h.severity})",
                ref_speed_kph=h.entry_speed_kph,
            )
        )
        approaches.append(_approach(speed, knowledge._bin_m, length, h.target_m))
    priority = sorted(kept, key=lambda h: (-(h.entry_speed_kph - h.min_speed_kph), -h.support, h.target_m))
    return CuePlan(
        mode=m,
        cues=tuple(specs),
        approaches=tuple(approaches),
        targets=tuple(sp.target_m for sp in specs),
        length_m=length,
        focus=tuple(h.key for h in priority),
        reason=None,
    )


def _approach(speed_kph: np.ndarray | None, bin_m: float, length: float, target: float) -> CueApproach | None:
    """Time-to-go table over the approach from the field's median speed (1 m steps, cyclic; NaN = unknown)."""
    if speed_kph is None or not np.isfinite(speed_kph).any():
        return None
    centres = (np.arange(len(speed_kph), dtype=np.float64) + 0.5) * bin_m
    known = np.isfinite(speed_kph)
    ks = np.arange(0.0, WINDOW_M + 1.0)
    pos = (target - ks) % length
    v = np.interp(pos, centres[known], speed_kph[known] / 3.6, period=length)
    # cells around unknown bins stay unknown
    idx = np.minimum((pos / bin_m).astype(int), len(speed_kph) - 1)
    v[~known[idx]] = np.nan
    with np.errstate(invalid="ignore", divide="ignore"):
        step = np.where(v > 1.0, 1.0 / v, np.nan)
    ttg = np.concatenate([[0.0], np.cumsum(step[1:])])
    if not np.isfinite(ttg[1:]).any():
        return None
    return CueApproach(array("d", ttg.tolist()), array("d", v.tolist()))


# ============================================================================================== worker
class FieldWorker:
    """Runs a ``FieldModel`` off the ingest thread and hands each new ``FieldSnapshot`` to ``on_snapshot``.

    * ``submit`` (ingest thread): an atomic deque append, never blocks, never raises. When ``max_queue`` items are
      waiting the newest is dropped and counted (``dropped``): back-pressure lands on the field model, never on
      ingest. ``SessionInfo`` items share the queue so context and samples stay in order.
    * The worker thread builds a new model whenever the session, track or length changes (publishing ``None``
      first), feeds samples and snapshots at most every ``snapshot_interval_s`` when something changed. It also
      hands every ``SessionInfo`` to ``on_session`` (e.g. ``TrackKnowledgeResolver.set_session``), so resolving
      (identity mapping, a few ms on a track change) never runs on the ingest thread.
    * ``start=False`` (tests, headless replay): call ``process_pending`` to run the same steps on the caller's thread.
    * ``block_when_full`` (replays only, NEVER the UDP ingest thread): ``submit`` waits for the worker instead of
      dropping, so a max-speed replay learns from every sample. ``close(drain=True)`` processes what is still queued
      and publishes a final snapshot before the thread stops.
    """

    def __init__(
        self,
        on_snapshot: Callable[[FieldSnapshot | None], None] | None = None,
        *,
        on_session: Callable[[SessionInfo], None] | None = None,
        snapshot_interval_s: float = SNAPSHOT_INTERVAL_S,
        max_queue: int = MAX_QUEUE,
        filters: FieldFilter | None = None,
        start: bool = True,
        block_when_full: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.on_snapshot = on_snapshot
        self.on_session = on_session
        self.snapshot_interval_s = max(0.0, snapshot_interval_s)
        self.max_queue = max(1, max_queue)
        self.block_when_full = block_when_full
        self.filters = filters
        self._clock = clock
        self._q: deque[FieldSample | SessionInfo | None] = deque()
        self._model: FieldModel | None = None
        self._key: tuple[Any, ...] | None = None
        self._ended = False
        self._next_snapshot = 0.0
        self._stop = threading.Event()
        self._drain = threading.Event()
        self.submitted = 0
        self.dropped = 0
        self.processed = 0
        self.snapshots = 0
        self.errors = 0
        self.last: FieldSnapshot | None = None
        self._thread: threading.Thread | None = None
        if start:
            self._thread = threading.Thread(target=self._run, name="field-model", daemon=True)
            self._thread.start()

    # ------------------------------------------------------------------ ingest thread
    def submit(self, item: FieldSample | SessionInfo) -> bool:
        """Queue one item; False when it was dropped because the worker is behind. O(1), lock-free; with
        ``block_when_full`` (replays) it waits for room while the worker runs instead."""
        if len(self._q) >= self.max_queue:
            th = self._thread
            if self.block_when_full and th is not None:
                while len(self._q) >= self.max_queue and th.is_alive() and not self._stop.is_set():
                    time.sleep(BLOCK_POLL_S)
            if len(self._q) >= self.max_queue:
                self.dropped += 1
                return False
        self._q.append(item)
        self.submitted += 1
        return True

    def end_session(self) -> None:
        """The session ended (queued behind any samples still waiting): samples are ignored until the next
        ``SessionInfo``. The last snapshot stays published - like the learned map, the field's view of the track is
        still true in the menus - and is replaced only when another session starts."""
        self._q.append(None)

    # ------------------------------------------------------------------ worker
    @property
    def model(self) -> FieldModel | None:
        return self._model

    @property
    def pending(self) -> int:
        """Items waiting in the queue."""
        return len(self._q)

    def stats(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted,
            "dropped": self.dropped,
            "processed": self.processed,
            "queued": self.pending,
            "snapshots": self.snapshots,
            "errors": self.errors,
            "car_laps": self._model.car_laps if self._model is not None else 0,
        }

    def process_pending(self, *, snapshot: bool = True) -> FieldSnapshot | None:
        """Drain the queue on the calling thread, then (``snapshot``) take and publish a snapshot if anything
        changed. For ``start=False`` workers; returns the latest snapshot."""
        while self._q:
            self._handle(self._q.popleft())
        if snapshot and self._model is not None and self._model.dirty:
            self._snapshot()
        return self.last

    def close(self, timeout: float = 5.0, *, drain: bool = False) -> None:
        """Stop the worker. ``drain``: first process everything still queued and publish a final snapshot (end of a
        replay); otherwise queued items are dropped."""
        if drain:
            self._drain.set()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        elif drain:
            self.process_pending()

    def _run(self) -> None:
        while True:
            stopping = self._stop.is_set()
            if stopping and not self._drain.is_set():
                return
            try:
                busy = False
                for _ in range(512):
                    if not self._q:
                        break
                    self._handle(self._q.popleft())
                    busy = True
                now = self._clock()
                final = stopping and not self._q
                if self._model is not None and self._model.dirty and (now >= self._next_snapshot or final):
                    self._next_snapshot = now + self.snapshot_interval_s
                    self._snapshot()
                if final:
                    return
                if not busy:
                    self._stop.wait(POLL_S)
            except Exception:
                self.errors += 1
                if self.errors <= 3 or self.errors % 1000 == 0:
                    log.exception("field model worker error (%d)", self.errors)
                if stopping:
                    return

    def _handle(self, item: FieldSample | SessionInfo | None) -> None:
        try:
            if item is None:
                self._ended = True
            elif isinstance(item, SessionInfo):
                self._ended = False  # a new session, or the same one again after an idle end: learn again
                self._on_session(item)
                if self.on_session is not None:
                    self.on_session(item)
            elif self._model is not None and not self._ended:
                self._model.feed(item)
                self.processed += 1
        except Exception:
            self.errors += 1
            if self.errors <= 3 or self.errors % 1000 == 0:
                log.exception("field model error (%d)", self.errors)

    def _on_session(self, info: SessionInfo) -> None:
        length = info.track_length_m
        if not info.track_id or length is None or not math.isfinite(length) or length <= 100.0:
            return  # no lap length yet: samples wait for a model (and are dropped meanwhile)
        key = (info.session_uid, info.track_id, length)
        if key == self._key:
            return
        model = FieldModel(
            game=info.game.value,
            track_id=info.track_id,
            track_length_m=length,
            is_race=info.session_type is SessionType.RACE,
            filters=self.filters,
        )
        self._set_model(model, key)

    def _set_model(self, model: FieldModel | None, key: tuple[Any, ...] | None) -> None:
        had = self._model is not None
        self._model, self._key = model, key
        self.last = None
        self._next_snapshot = self._clock() + self.snapshot_interval_s
        if had:
            self._emit(None)

    def _snapshot(self) -> None:
        model = self._model
        if model is None:
            return
        snap = model.snapshot()
        if snap is None:
            return
        self.snapshots += 1
        self.last = snap
        self._emit(snap)

    def _emit(self, snap: FieldSnapshot | None) -> None:
        cb = self.on_snapshot
        if cb is None:
            return
        try:
            cb(snap)
        except Exception:
            self.errors += 1
            log.exception("field snapshot callback failed")


def _r(v: float | None, nd: int) -> float | None:
    return None if v is None or not math.isfinite(v) else round(float(v), nd)
