"""Technique analysis of a stored session or a lap pair: the orchestrator behind ``/api/technique`` and the facts.

* ``analyse_session(sa)`` is pure (no I/O): it works from a ``SessionAnalysis`` (the reference, the per-lap
  ``LapAnalysis`` and comparisons) and returns a ``SessionTechnique``. Results are cached in a small module-level LRU
  keyed by (session, lap count, reference, track model version, latest setup, pedals), so the fact builder and the
  radio can call it on every question.
* ``TechniqueAnalyzer`` adds what needs the database: the rig profile's pedals at the session's start, the laps'
  traces when the session has no reference yet (balance still works then; line and inputs need a reference), the
  session's current setup and running experiments for the setup engineer (never cached: a garage change or a new
  experiment shows at once), and lap-pair comparisons (``compare``).

Nothing is stored and nothing touches the live path.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from pitwall import carclass
from pitwall.analysis.braking import BrakingEvent
from pitwall.analysis.coaching import is_incident
from pitwall.analysis.compare import (
    CornerDelta,
    CornerMetrics,
    LapAnalysis,
    analyse_lap,
    check_compatibility,
    compare,
    compat_meta,
    lengths_compatible,
)
from pitwall.analysis.laps import LapFlag
from pitwall.analysis.track import Corner, TrackModel
from pitwall.analysis.track_identity import CornerText, corner_texts, identify
from pitwall.carsetup.catalog import FORMAT_FAMILY, CarFormat, CatalogError, load_catalog
from pitwall.carsetup.compare import stored_values
from pitwall.carsetup.context import session_context
from pitwall.core.session_analysis import SessionAnalysis, SessionAnalyzer, session_ctx
from pitwall.model.telemetry import TrackZones
from pitwall.storage import repo
from pitwall.storage.db import Database
from pitwall.technique import thresholds as T
from pitwall.technique.balance import (
    PHASE_SIMPLE,
    PHASES,
    BalanceSymptom,
    CornerPhaseInput,
    LapPhase,
    Phase,
    PhaseBalance,
    PhaseSummary,
    SpeedClass,
    build_symptoms,
    lap_balance,
    speed_class,
    summarise,
)
from pitwall.technique.inputs import CornerInputs, TechniqueNote, compare_inputs, corner_inputs, habits, top_notes
from pitwall.technique.line import (
    ReferenceLine,
    inside_sign,
    lateral_offsets,
    point_offset,
    polyline,
    reference_line,
    steer_points,
)
from pitwall.technique.rig import NOTE_ABS, AssistInfo, PedalInfo, assist_info, pedal_info
from pitwall.technique.samples import Native, m2, native, rnd, runs, xz_list
from pitwall.technique.setup_map import FORMAT_UNKNOWN, LockupSymptom, SetupEngineer, suggest
from pitwall.technique.thresholds import threshold_infos

if TYPE_CHECKING:
    from pitwall.rig.recommend import RigProfile

POINT_KEYS = ("turn_in", "apex", "track_out")
EXCLUDED_FLAGS = (LapFlag.INCOMPLETE, LapFlag.DISTANCE_JUMP, LapFlag.PIT_IN, LapFlag.PIT_OUT, LapFlag.FLASHBACK)
FLAG_REASONS = {
    LapFlag.INCOMPLETE: "incomplete lap",
    LapFlag.DISTANCE_JUMP: "lap distance jumped (reset to track?)",
    LapFlag.PIT_IN: "pit lap",
    LapFlag.PIT_OUT: "out lap from the pits",
    LapFlag.FLASHBACK: "flashback during the lap",
}
F1_GAMES = frozenset({"f1_25"})
NO_REFERENCE = "No reference lap yet: drive a clean lap at this track first."
NO_SLIP = "No tyre slip data in this session (recorded before Pitwall stored it, or the game does not send it)."
NO_SLIP_GAME = "Pitwall does not read tyre slip from this game yet, so wheelspin, lock-ups and balance are unknown."


def no_slip_reason(game: object) -> str:
    """Why there is no slip data: the game's adapter maps none (only F1 25 sends MotionEx), or an F1 session recorded
    before Pitwall stored the channels."""
    return NO_SLIP if game in F1_GAMES else NO_SLIP_GAME


NO_LAPS = "No analysed laps in this session yet."
CACHE_ENTRIES = 16


class TechniqueNotFound(LookupError):
    """Unknown session or lap (HTTP 404)."""


class NoTrackModel(RuntimeError):
    """No track model for the track yet (HTTP 409)."""

    def __init__(self) -> None:
        super().__init__("no track model yet for this track (complete a clean lap first)")


class TechniqueBadReference(ValueError):
    """A reference lap that cannot be the session's reference: another game, track or layout (HTTP 422)."""


def check_reference(sess: Mapping[str, Any], ref_sess: Mapping[str, Any] | None) -> None:
    """Raise unless a chosen reference lap's session is on the session's game, track and layout. A reference from
    elsewhere would be "analysed" against the wrong track model: corner speeds, speed classes and setup gating would
    all come from another circuit."""
    if ref_sess is None:
        raise TechniqueNotFound("reference lap not found")
    if ref_sess.get("game") != sess.get("game") or ref_sess.get("track_id") != sess.get("track_id"):
        raise TechniqueBadReference("the reference lap is from another game or track")
    if not lengths_compatible(ref_sess.get("track_length_m"), sess.get("track_length_m")):
        raise TechniqueBadReference("the reference lap is from another layout of this track")


@dataclass(slots=True)
class Availability:
    ok: bool
    reason: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "note": self.note}


@dataclass(slots=True)
class LapEntry:
    lap_id: int
    lap_number: int
    clean: bool
    usable: bool
    reason: str | None
    # why a usable lap is left out of the handling balance and the habits (standing start, well off the pace)
    balance_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_id": self.lap_id,
            "lap_number": self.lap_number,
            "clean": self.clean,
            "usable": self.usable,
            "reason": self.reason,
            "balance_reason": self.balance_reason,
        }


def _balance_dict(b: Mapping[Phase, PhaseBalance | None] | None) -> dict[str, Any] | None:
    if b is None:
        return None
    return {p: (pb.to_dict() if pb is not None else None) for p, pb in b.items()}


@dataclass(slots=True)
class LapCornerTechnique:
    lap_id: int
    lap_number: int
    clean: bool
    incident: bool
    time_delta_s: float | None
    line: dict[str, float | None] | None
    inputs: CornerInputs | None
    notes: list[TechniqueNote]
    balance: dict[Phase, PhaseBalance | None] | None
    all_notes: list[TechniqueNote] = field(default_factory=list)  # every note with both values (habits, facts)
    lap_time_ms: int | None = None
    representative: bool = True  # at racing pace (not a standing start, not well off the pace): balance, habits

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_id": self.lap_id,
            "lap_number": self.lap_number,
            "clean": self.clean,
            "incident": self.incident,
            "time_delta_s": rnd(self.time_delta_s, 3),
            "line": None if self.line is None else {k: m2(v) for k, v in self.line.items()},
            "inputs": self.inputs.to_dict() if self.inputs is not None else None,
            "notes": [n.to_dict() for n in self.notes],
            "balance": _balance_dict(self.balance),
        }


@dataclass(slots=True)
class LinePointSummary:
    median_offset_m: float | None
    laps: int
    laps_wider: int
    laps_tighter: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "median_offset_m": m2(self.median_offset_m),
            "laps": self.laps,
            "laps_wider": self.laps_wider,
            "laps_tighter": self.laps_tighter,
        }


@dataclass(slots=True)
class CornerLineSummary:
    inside_known: bool
    points: dict[str, LinePointSummary | None]
    view: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "inside_known": self.inside_known,
            "points": {k: (v.to_dict() if v is not None else None) for k, v in self.points.items()},
            "view": self.view,
        }


@dataclass(slots=True)
class TechniqueCorner:
    corner: str
    label: str | None
    name: str | None
    direction: str | None
    apex_m: float
    speed_class: SpeedClass | None
    ref_min_speed_kph: float | None
    points: dict[str, float | None]
    ref_inputs: CornerInputs | None
    ref_balance: dict[Phase, PhaseBalance | None] | None
    laps: list[LapCornerTechnique]
    line: CornerLineSummary | None
    balance: dict[Phase, PhaseSummary] | None
    habits: list[TechniqueNote]
    long_name: str = ""  # sentence form ("Turn 3 (Remus)"), for facts
    inside: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner": self.corner,
            "label": self.label,
            "name": self.name,
            "direction": self.direction,
            "apex_m": round(self.apex_m, 2),
            "speed_class": self.speed_class,
            "ref_min_speed_kph": rnd(self.ref_min_speed_kph, 1),
            "points": {k: m2(v) for k, v in self.points.items()},
            "ref": {
                "inputs": self.ref_inputs.to_dict() if self.ref_inputs is not None else None,
                "balance": _balance_dict(self.ref_balance),
            },
            "laps": [lc.to_dict() for lc in self.laps],
            "line": self.line.to_dict() if self.line is not None else None,
            "balance": None if self.balance is None else {p: s.to_dict() for p, s in self.balance.items()},
            "habits": [h.to_dict() for h in self.habits],
        }


@dataclass(slots=True)
class SessionTechnique:
    session: dict[str, Any]
    ref_lap_id: int | None
    ref_lap_number: int | None
    ref_session_id: str | None
    available: dict[str, Availability]
    pedals: PedalInfo
    assists: AssistInfo
    laps: list[LapEntry]
    corners: list[TechniqueCorner]
    symptoms: list[BalanceSymptom]
    lockups: list[LockupSymptom]
    model: TrackModel | None

    @property
    def session_id(self) -> str:
        return str(self.session.get("id"))

    @property
    def is_f1(self) -> bool:
        return self.session.get("game") in F1_GAMES

    def to_dict(self, setup: SetupEngineer | None) -> dict[str, Any]:
        s = self.session
        return {
            "session_id": self.session_id,
            "game": s.get("game"),
            "synthetic": bool(s.get("synthetic")),
            "source": s.get("source"),
            "ref_lap_id": self.ref_lap_id,
            "ref_lap_number": self.ref_lap_number,
            "ref_session_id": self.ref_session_id,
            "available": {k: v.to_dict() for k, v in self.available.items()},
            "pedals": self.pedals.to_dict(),
            "assists": self.assists.to_dict(),
            "laps": [lap.to_dict() for lap in self.laps],
            "corners": [c.to_dict() for c in self.corners],
            "symptoms": [x.to_dict() for x in self.symptoms],
            "lockups": [x.to_dict() for x in self.lockups],
            "setup": setup.to_dict() if setup is not None else None,
            "thresholds": threshold_infos(),
        }

    def balance_dict(self, setup: SetupEngineer | None) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "symptoms": [x.to_dict() for x in self.symptoms],
            "lockups": [x.to_dict() for x in self.lockups],
            "setup": setup.to_dict() if setup is not None else None,
            "available": {k: v.to_dict() for k, v in self.available.items()},
            "assists": self.assists.to_dict(),
        }


# ---------------------------------------------------------------------------------------------- helpers
def _event_for(an: LapAnalysis, cm: CornerMetrics | None) -> BrakingEvent | None:
    if cm is None or cm.brake_start_m is None:
        return None
    return next((e for e in an.braking if abs(e.start_m - cm.brake_start_m) < 1e-6), None)


def _next_brake(an: LapAnalysis, after_m: float) -> float | None:
    return next((e.start_m for e in an.braking if e.start_m > after_m), None)


APEX_PLATEAU_KPH = 0.5  # speed within this of the minimum counts as the same slowest point
APEX_SEARCH_M = 80.0  # analysis.compare.BRAKE_MATCH_APEX_TOL_M


def _apex(an: LapAnalysis | None, c: Corner, fallback: float) -> float:
    """The lap's slowest point in corner ``c``: the middle of the minimum-speed plateau within +/-80 m of the model's
    apex, clipped to the corner's segment (so the two corners of a chicane keep their own slowest points).

    Games report speed in whole km/h (F1: uint16), so a constant-radius corner holds its minimum for several metres
    and the first minimum sample (``CornerMetrics.min_speed_m``) sits early in the corner; the plateau's middle is the
    slowest *point*."""
    if an is None:
        return fallback
    d, v = an.dtrace.d, an.dtrace.ch.get("speed_kph")
    if v is None or len(d) < 2:
        return fallback
    lo_m = max(c.seg_start_m, c.apex_m - APEX_SEARCH_M)
    hi_m = min(c.seg_end_m, c.apex_m + APEX_SEARCH_M)
    idx = np.flatnonzero((d >= lo_m) & (d <= hi_m) & np.isfinite(v))
    if len(idx) == 0:
        return fallback
    w = v[idx]
    k = int(np.argmin(w))
    flat = w <= w[k] + APEX_PLATEAU_KPH
    contiguous = np.diff(idx) == 1
    for a, b in runs(flat):
        if a <= k <= b and bool(np.all(contiguous[a:b])):
            return float((d[idx[a]] + d[idx[b]]) / 2)
    return float(d[idx[k]])


def corner_anchors(ref_an: LapAnalysis | None, c: Corner) -> tuple[float, float | None, float | None]:
    """(slowest point, turn-in, track-out) of corner ``c`` from the reference lap (the model's entry and exit without
    one): what every lap's inputs and balance at that corner are anchored to."""
    apex = _apex(ref_an, c, c.apex_m)
    turn_in: float | None = c.entry_m
    track_out: float | None = c.exit_m
    if ref_an is not None:
        turn_in, track_out = _lap_points(ref_an, apex, (c.entry_m, c.exit_m))
    return apex, turn_in, track_out


def lap_corner(
    an: LapAnalysis,
    nat: Native,
    c: Corner,
    anchors: tuple[float, float | None, float | None],
) -> tuple[CornerInputs, dict[Phase, PhaseBalance | None] | None]:
    """One lap's inputs and handling balance at corner ``c`` (``nat`` = ``native(an.lap)``), on this lap's own slowest
    point, turn-in and track-out near the reference's ``anchors`` (``corner_anchors``)."""
    apex, turn_in, track_out = anchors
    apex_lap = _apex(an, c, apex)
    ti_lap, to_lap = _lap_points(an, apex_lap, (turn_in, track_out))
    meta = an.lap.meta
    inputs = corner_inputs(
        nat,
        _event_for(an, an.corners.get(c.name)),
        apex_lap,
        ti_lap,
        to_lap,
        _next_brake(an, apex_lap),
        abs_on=meta.get("abs_active"),
        tc_level=meta.get("traction_control"),
    )
    return inputs, lap_balance(nat, apex_lap, c.seg_start_m, c.seg_end_m)


def _resolution_m(nat: Native, apex_m: float) -> float:
    w = np.abs(nat.d - apex_m) <= 50.0
    dd = np.diff(nat.d[w])
    return float(np.median(dd)) if len(dd) else 1.5


def _lap_points(
    an: LapAnalysis, apex_m: float, fallback: tuple[float | None, float | None]
) -> tuple[float | None, float | None]:
    dt = an.dtrace
    steer = dt.ch.get("steering")
    if steer is None:
        return fallback
    ti, to = steer_points(dt.d, steer, apex_m)
    return (ti if ti is not None else fallback[0], to if to is not None else fallback[1])


def _corner_label(c: Corner) -> tuple[str | None, str | None]:
    return c.label, c.display_name


def _has(an: LapAnalysis, names: tuple[str, ...]) -> bool:
    ch = an.lap.channels
    return all(k in ch and bool(np.isfinite(ch[k]).any()) for k in names)


SLIP_CHANNELS = ("wheel_slip_fl", "wheel_slip_fr", "wheel_slip_rl", "wheel_slip_rr")
BALANCE_CHANNELS = ("slip_angle_front_abs_rad", "slip_angle_rear_abs_rad", "g_lat")


def lap_entries(sa: SessionAnalysis, analyses: Mapping[int, LapAnalysis]) -> list[LapEntry]:
    out: list[LapEntry] = []
    for lap in sa.laps:
        lid = int(lap["id"])
        flags = set(lap.get("flags") or ())
        bad = next((f for f in EXCLUDED_FLAGS if f in flags), None)
        reason: str | None = FLAG_REASONS[bad] if bad else None
        usable = bad is None and lid in analyses
        if bad is None and lid not in analyses:
            reason = "no lap trace"
        comp = sa.comparisons.get(lid)
        if usable and comp is not None and not comp.compatibility.ok:
            reason = "not compared with the reference: " + "; ".join(comp.compatibility.blocking)
        out.append(LapEntry(lid, int(lap["lap_number"]), bool(lap.get("clean")), usable, reason))
    return out


def _pace_exclusions(sa: SessionAnalysis, entries: list[LapEntry]) -> tuple[dict[int, str], int | None]:
    """Usable laps left out of the handling balance and the habits, with why, and the session's best clean lap (the
    fastest clean timed lap that is not left out). A standing start is not driven at the limit like a flying lap, and
    a lap well off the pace (a safety car, a cool-down) is not at the limit at all: neither says how the car handles.
    """
    rows = {int(lap["id"]): lap for lap in sa.laps}
    timed = [e for e in entries if e.usable and e.clean and rows[e.lap_id].get("lap_time_ms")]
    times = [int(rows[e.lap_id]["lap_time_ms"]) for e in timed]
    best_ms = min(times) if times else None
    out: dict[int, str] = {}
    for e in entries:
        if not e.usable:
            continue
        lap = rows[e.lap_id]
        ms = lap.get("lap_time_ms")
        flags = lap.get("flags") or ()
        if LapFlag.STANDING_START in flags:
            out[e.lap_id] = "standing start"
        elif LapFlag.RACE_START in flags:
            out[e.lap_id] = "race start"
        elif best_ms and ms and int(ms) > T.BALANCE_PACE_FRAC * best_ms:
            out[e.lap_id] = f"more than {(T.BALANCE_PACE_FRAC - 1) * 100:.0f} % off your best clean lap"
    best = [
        (int(rows[e.lap_id]["lap_time_ms"]), e.lap_id)
        for e in entries
        if e.usable and e.clean and e.lap_id not in out and rows[e.lap_id].get("lap_time_ms")
    ]
    return out, (min(best)[1] if best else None)


# ---------------------------------------------------------------------------------------------- session analysis
_CACHE: OrderedDict[tuple[Any, ...], SessionTechnique] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _cache_key(sa: SessionAnalysis, pedals: PedalInfo | None) -> tuple[Any, ...]:
    return (
        sa.session.get("id"),
        len(sa.laps),
        sa.ref_lap_id,
        sa.model.version if sa.model is not None else None,
        sa.model.n_laps if sa.model is not None else None,
        sa.setup["id"] if sa.setup else None,
        None if pedals is None else (pedals.pedals, pedals.changed_since_reference),
        tuple(sorted(sa.analyses)),
    )


def analyse_session(
    sa: SessionAnalysis, pedals: PedalInfo | None = None, analyses: Mapping[int, LapAnalysis] | None = None
) -> SessionTechnique:
    """Technique of a session (pure, cached). ``analyses``: the session's ``LapAnalysis`` when ``sa`` has none (no
    reference yet); only balance is available then."""
    key = (*_cache_key(sa, pedals), tuple(sorted(analyses)) if analyses else ())
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit
    out = _analyse(sa, pedals or pedal_info(None), analyses)
    with _CACHE_LOCK:
        _CACHE[key] = out
        while len(_CACHE) > CACHE_ENTRIES:
            _CACHE.popitem(last=False)
    return out


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _analyse(sa: SessionAnalysis, pedals: PedalInfo, extra: Mapping[int, LapAnalysis] | None) -> SessionTechnique:
    s = sa.session
    model = sa.model
    analyses: dict[int, LapAnalysis] = dict(sa.analyses)
    if extra:
        for k, v in extra.items():
            analyses.setdefault(k, v)
    entries = lap_entries(sa, analyses)
    usable = {e.lap_id: e for e in entries if e.usable}
    off_pace, best_lap_id = _pace_exclusions(sa, entries)
    for e in entries:
        e.balance_reason = off_pace.get(e.lap_id)
    rows = {int(lap["id"]): lap for lap in sa.laps}
    ref_id = sa.ref_lap_id if sa.ref_lap_id in sa.analyses else None
    ref_an = analyses.get(ref_id) if ref_id is not None else None
    session_lap_ans = [analyses[i] for i in usable]
    assists = assist_info(s.get("game"), s.get("assists"), (an.lap.meta for an in session_lap_ans))
    muted = assists.brake_notes_muted
    tol = pedals.tolerances
    plane = model.ground_plane if model is not None else ("pos_x_m", "pos_z_m")

    no_data = no_slip_reason(s.get("game")) if session_lap_ans else NO_LAPS
    has_slip = any(_has(an, SLIP_CHANNELS) for an in session_lap_ans)
    has_balance = any(_has(an, BALANCE_CHANNELS) for an in session_lap_ans)
    ref_line: ReferenceLine | None = reference_line(ref_an.dtrace, plane) if ref_an is not None else None
    line_ok = ref_line is not None and ref_line.has_positions
    available = {
        "line": Availability(
            line_ok,
            None if line_ok else (NO_REFERENCE if ref_an is None else "The reference lap has no position data."),
            "Compared with your own reference lap; Pitwall does not know the track edges." if line_ok else None,
        ),
        "inputs": Availability(
            ref_an is not None, None if ref_an is not None else NO_REFERENCE, assists.notes[0] if muted else None
        ),
        "slip": Availability(has_slip, None if has_slip else no_data),
        "balance": Availability(
            has_balance,
            None if has_balance else no_data,
            "Measured from tyre slip at the limit; the thresholds are Pitwall's heuristics."
            + (
                f" Standing starts and laps more than {(T.BALANCE_PACE_FRAC - 1) * 100:.0f} % off your best clean lap "
                "are left out."
                if off_pace
                else ""
            )
            if has_balance
            else None,
        ),
        "setup": Availability(False, None),
    }
    # line and inputs need at least one lap compared with the reference (a reference alone compares nothing)
    others = [lid for lid in usable if lid != ref_id]
    if ref_an is not None and not any(_compared_ok(sa, lid) for lid in others):
        blocked = next((sa.comparisons[lid] for lid in others if lid in sa.comparisons), None)
        ref_no = sa.ref_lap.get("lap_number") if sa.ref_lap else None
        why = (
            f"Not compared with your reference lap (lap {ref_no}): " + "; ".join(blocked.compatibility.blocking) + "."
            if blocked is not None and blocked.compatibility.blocking
            else f"No other lap compared with your reference lap (lap {ref_no}) yet."
        )
        available["line"] = Availability(False, why)
        available["inputs"] = Availability(False, why)
    if s.get("game") not in F1_GAMES:
        available["setup"] = Availability(False, "Setup suggestions are for F1 25 only.")
    elif not has_balance:
        available["setup"] = Availability(False, no_data)
    else:
        available["setup"] = Availability(True, None, "One change at a time, then compare a session.")
    if has_slip and assists.abs:
        available["slip"].note = NOTE_ABS  # the assists' own sentence: one wording wherever it shows

    corners: list[TechniqueCorner] = []
    lockup_rows: dict[str, dict[str, set[int]]] = {"front": {}, "rear": {}}  # axle -> corner -> lap ids
    lockup_events: dict[str, int] = {"front": 0, "rear": 0}
    phase_items: list[CornerPhaseInput] = []
    if model is None or not model.corners:
        return SessionTechnique(
            session=s,
            ref_lap_id=ref_id,
            ref_lap_number=sa.ref_lap.get("lap_number") if sa.ref_lap and ref_id is not None else None,
            ref_session_id=sa.ref_lap.get("session_id") if sa.ref_lap and ref_id is not None else None,
            available=available,
            pedals=pedals,
            assists=assists,
            laps=entries,
            corners=[],
            symptoms=[],
            lockups=[],
            model=model,
        )
    texts = corner_texts(model)
    natives: dict[int, Native] = {lid: native(analyses[lid].lap) for lid in usable}
    ref_nat = native(ref_an.lap) if ref_an is not None else None
    offsets: dict[int, np.ndarray] = {}
    if ref_line is not None and line_ok:
        for lid in usable:
            if lid == ref_id or not _compared_ok(sa, lid):
                continue
            offsets[lid] = lateral_offsets(ref_line, analyses[lid].dtrace, plane)
    ref_abs = ref_an.lap.meta.get("abs_active") if ref_an is not None else None
    ref_tc = ref_an.lap.meta.get("traction_control") if ref_an is not None else None

    for c in model.corners:
        ct: CornerText | None = texts.get(c.name)
        ref_cm = ref_an.corners.get(c.name) if ref_an is not None else None
        apex, turn_in, track_out = corner_anchors(ref_an, c)
        inside = inside_sign(ref_line, apex) if ref_line is not None and line_ok else 0
        ref_min = (
            ref_cm.min_speed_kph if ref_cm is not None and ref_cm.min_speed_kph is not None else c.ref_min_speed_kph
        )
        # the corner's speed class from the track model, never from the chosen reference lap: it gates setup changes
        sc = speed_class(c.ref_min_speed_kph)
        ref_inputs: CornerInputs | None = None
        ref_bal: dict[Phase, PhaseBalance | None] | None = None
        if ref_an is not None and ref_nat is not None:
            ref_inputs = corner_inputs(
                ref_nat,
                _event_for(ref_an, ref_cm),
                apex,
                turn_in,
                track_out,
                _next_brake(ref_an, apex),
                abs_on=ref_abs,
                tc_level=ref_tc,
            )
            ref_bal = lap_balance(ref_nat, apex, c.seg_start_m, c.seg_end_m)
        lap_rows: list[LapCornerTechnique] = []
        for lid in usable:
            an = analyses[lid]
            nat = natives[lid]
            row = rows.get(lid, {})
            inputs, bal = lap_corner(an, nat, c, (apex, turn_in, track_out))
            cd = _corner_delta(sa, lid, c.name)
            incident = cd is not None and is_incident(cd)
            line_pts: dict[str, float | None] | None = None
            notes: list[TechniqueNote] = []
            all_notes: list[TechniqueNote] = []
            if lid != ref_id and ref_inputs is not None and _compared_ok(sa, lid) and not incident:
                off = offsets.get(lid)
                if off is not None:
                    d = an.dtrace.d
                    line_pts = {}
                    for pkey, pos in zip(POINT_KEYS, (turn_in, apex, track_out), strict=True):
                        pv = point_offset(d, off, pos)
                        line_pts[pkey] = None if pv is None else (pv * inside if inside else abs(pv))
                res = _resolution_m(nat, _apex(an, c, apex))  # this lap's slowest point, as lap_corner placed it
                all_notes = compare_inputs(inputs, ref_inputs, tol, res, muted=muted)
                notes = top_notes(all_notes)
            lap_rows.append(
                LapCornerTechnique(
                    lap_id=lid,
                    lap_number=int(row.get("lap_number", an.lap.lap_number)),
                    clean=bool(row.get("clean")),
                    incident=incident,
                    time_delta_s=cd.time_delta_s if cd is not None else None,
                    line=line_pts,
                    inputs=inputs,
                    notes=notes,
                    balance=bal,
                    all_notes=all_notes,
                    lap_time_ms=row.get("lap_time_ms"),
                    representative=lid not in off_pace,
                )
            )
            lk = inputs.lockup
            if lk.status == "measured" and lk.events and not incident:
                for axle, wheels in (("front", ("fl", "fr")), ("rear", ("rl", "rr"))):
                    if any(w in lk.wheels for w in wheels):
                        lockup_rows[axle].setdefault(c.name, set()).add(lid)
                        lockup_events[axle] += lk.events
        line_summary = _line_summary(
            lap_rows, inside, ref_an, analyses, plane, turn_in, track_out, line_ok and ref_an is not None
        )
        bal_summary: dict[Phase, PhaseSummary] | None = None
        if has_balance:
            bal_summary = {}
            for p in PHASES:
                prow = [
                    LapPhase(
                        lap_id=lc.lap_id,
                        lap_number=lc.lap_number,
                        lap_time_ms=lc.lap_time_ms,
                        clean=lc.clean,
                        pb=pb,
                        wheelspin=bool(lc.inputs and lc.inputs.wheelspin.events),
                    )
                    for lc in lap_rows
                    if lc.representative
                    and not lc.incident
                    and lc.balance is not None
                    and (pb := lc.balance.get(p)) is not None
                ]
                summ = summarise(prow, best_lap_id)
                bal_summary[p] = summ
                phase_items.append(
                    CornerPhaseInput(
                        corner=c.name,
                        corner_label=ct.long if ct else c.name,
                        speed_class=sc,
                        phase=p,
                        summary=summ,
                        rows=prow,
                    )
                )
        compared = [lc.all_notes for lc in lap_rows if lc.all_notes and lc.representative]
        label, name = _corner_label(c)
        corners.append(
            TechniqueCorner(
                corner=c.name,
                label=label,
                name=name,
                direction=c.direction,
                apex_m=float(apex),
                speed_class=sc,
                ref_min_speed_kph=ref_min,
                points={"turn_in": turn_in, "apex": float(apex), "track_out": track_out},
                ref_inputs=ref_inputs,
                ref_balance=ref_bal,
                laps=lap_rows,
                line=line_summary,
                balance=bal_summary,
                habits=habits(compared),
                long_name=ct.long if ct else c.name,
                inside=inside,
            )
        )
    lockups = _lockup_symptoms(lockup_rows, lockup_events, texts, assists.abs_words)
    return SessionTechnique(
        session=s,
        ref_lap_id=ref_id,
        ref_lap_number=sa.ref_lap.get("lap_number") if sa.ref_lap and ref_id is not None else None,
        ref_session_id=sa.ref_lap.get("session_id") if sa.ref_lap and ref_id is not None else None,
        available=available,
        pedals=pedals,
        assists=assists,
        laps=entries,
        corners=corners,
        symptoms=build_symptoms(phase_items) if has_balance else [],
        lockups=lockups,
        model=model,
    )


def _compared_ok(sa: SessionAnalysis, lid: int) -> bool:
    comp = sa.comparisons.get(lid)
    return comp is not None and comp.compatibility.ok


def _corner_delta(sa: SessionAnalysis, lid: int, corner: str) -> CornerDelta | None:
    comp = sa.comparisons.get(lid)
    if comp is None:
        return None
    return next((cd for cd in comp.corners if cd.corner == corner), None)


def _line_summary(
    lap_rows: list[LapCornerTechnique],
    inside: int,
    ref_an: LapAnalysis | None,
    analyses: Mapping[int, LapAnalysis],
    plane: tuple[str, str],
    turn_in: float | None,
    track_out: float | None,
    ok: bool,
) -> CornerLineSummary | None:
    if not ok or ref_an is None:
        return None
    pts: dict[str, LinePointSummary | None] = {}
    for k in POINT_KEYS:
        vals = [lc.line[k] for lc in lap_rows if lc.line is not None and lc.line.get(k) is not None]
        fv = [float(v) for v in vals if v is not None]
        if not fv:
            pts[k] = None
            continue
        pts[k] = LinePointSummary(
            median_offset_m=float(np.median(fv)),
            laps=len(fv),
            laps_wider=sum(1 for v in fv if v <= -T.LINE_NOTABLE_M) if inside else 0,
            laps_tighter=sum(1 for v in fv if v >= T.LINE_NOTABLE_M) if inside else 0,
        )
    latest = next((lc for lc in reversed(lap_rows) if lc.line is not None), None)
    view: dict[str, Any] | None = None
    if latest is not None and turn_in is not None and track_out is not None:
        lo, hi = turn_in - T.LINE_WINDOW_MARGIN_M, track_out + T.LINE_WINDOW_MARGIN_M
        _, ra, rb = polyline(ref_an.dtrace, plane, T.LINE_WINDOW_STEP_M, lo, hi)
        _, la, lb = polyline(analyses[latest.lap_id].dtrace, plane, T.LINE_WINDOW_STEP_M, lo, hi)
        view = {
            "lap_id": latest.lap_id,
            "lap_number": latest.lap_number,
            "ref_xz": xz_list(ra, rb),
            "lap_xz": xz_list(la, lb),
        }
    return CornerLineSummary(inside_known=inside != 0, points=pts, view=view)


def _lockup_symptoms(
    rows: dict[str, dict[str, set[int]]], events: dict[str, int], texts: Mapping[str, CornerText], abs_words: str
) -> list[LockupSymptom]:
    out: list[LockupSymptom] = []
    axles: tuple[Literal["front", "rear"], ...] = ("front", "rear")
    for axle in axles:
        per = rows[axle]
        if not per:
            continue
        corners = list(per)
        labels = [texts[c].long if c in texts else c for c in corners]
        laps = len(set().union(*per.values()))
        where = ", ".join(labels)
        out.append(
            LockupSymptom(
                id=f"lockups-{axle}",
                axle=axle,
                corners=corners,
                corner_labels=labels,
                laps=laps,
                events=events[axle],
                text=f"{axle.capitalize()} lock-ups under braking at {where}: {events[axle]} in total over {laps} "
                f"lap{'s' if laps != 1 else ''} ({abs_words}).",
                text_simple=f"The {axle} wheels locked under braking at {where}.",
            )
        )
    return out


# ---------------------------------------------------------------------------------------------- setup engineer
def setup_engineer(
    st: SessionTechnique,
    setup_row: Mapping[str, Any] | None,
    testing: frozenset[str] = frozenset(),
    car_format: CarFormat | None = None,
) -> SetupEngineer | None:
    """Setup suggestions for an F1 session (None for other games): never cached, from the current setup.
    ``car_format`` overrides the session's (the driver's choice when a generic car cannot be told apart)."""
    if not st.is_f1:
        return None
    try:
        cat = load_catalog()
    except CatalogError:
        return SetupEngineer(car_format=None, setup_known=False, note="The setup catalogue is unavailable.")
    ctx = session_context(st.session)
    stored: dict[str, float] | None = None
    if setup_row is not None:
        stored = {}
        for k, v in stored_values(setup_row.get("params") or {}).items():
            p = cat.param(k)
            if p is not None:
                stored[k] = p.menu_value(v)
    if car_format is not None and ctx.family is not None and FORMAT_FAMILY[car_format] != ctx.family:
        car_format = None  # never another car class's ranges (an F1 format for an F2 car, or the reverse)
    fmt = car_format or ctx.car_format
    eng = suggest(
        st.symptoms,
        st.lockups,
        cat=cat,
        car_format=fmt,
        stored=stored,
        testing=testing,
        braking_assist=bool(st.assists.braking_assist),
        # an F2 (or classic) car is never asked for a car format: say why its changes cannot be sized
        format_unknown=FORMAT_UNKNOWN if ctx.asks_car_format else ctx.reasons.get("car_format", FORMAT_UNKNOWN),
    )
    if not st.available["balance"].ok:
        eng.note = st.available["balance"].reason
    return eng


# ---------------------------------------------------------------------------------------------- analyzer (DB)
class TechniqueAnalyzer:
    """Technique for the API: pedals from the rig profile, traces loaded when the session has no reference yet, the
    setup engineer from the current setup, and lap-pair comparisons."""

    def __init__(
        self, db: Database, sessions: SessionAnalyzer, rig_profile: Callable[[], RigProfile | None] | None = None
    ) -> None:
        self.db = db
        self.sessions = sessions
        self.rig_profile = rig_profile or (lambda: None)
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[Any, ...], SessionTechnique] = OrderedDict()

    def _pedals_at(self, unix: float | None) -> str | None:
        profile = self.rig_profile()
        if profile is None:
            return None
        return str(profile.hardware_at(unix).pedals)

    def _pedals(self, sess: Mapping[str, Any], ref_sess: Mapping[str, Any] | None) -> PedalInfo:
        pedals = self._pedals_at(sess.get("started_unix"))
        if ref_sess is None:
            return pedal_info(pedals)
        return pedal_info(pedals, self._pedals_at(ref_sess.get("started_unix")), ref_known=pedals is not None)

    def analyse(self, session_id: str, ref_lap_id: int | None = None) -> SessionTechnique:
        """``ref_lap_id``: a reference lap chosen instead of the session's own; unknown is ``TechniqueNotFound``, one
        from another game, track or layout ``TechniqueBadReference``."""
        sa = self.sessions.analyse(session_id, ref_lap_id)
        if sa is None:
            raise TechniqueNotFound(f"session {session_id} not found")
        if ref_lap_id is not None and sa.ref_lap is None:
            raise TechniqueNotFound("reference lap not found")
        ref_sess = None
        if sa.ref_lap is not None:
            with self.db.read() as c:
                ref_sess = repo.get_session(c, sa.ref_lap["session_id"])
        if ref_lap_id is not None:
            check_reference(sa.session, ref_sess)
        if sa.model is None:
            raise NoTrackModel()
        pedals = self._pedals(sa.session, ref_sess)
        key = (*_cache_key(sa, pedals), "db")
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        extra: dict[int, LapAnalysis] | None = None
        if not sa.analyses:
            extra = {}
            with self.db.read() as c:
                for lap in sa.laps:
                    if LapFlag.INCOMPLETE in (lap.get("flags") or ()):
                        continue
                    trace = repo.load_lap_trace(c, int(lap["id"]))
                    if trace is not None:
                        trace.meta.update(session_ctx(sa.session))
                        extra[int(lap["id"])] = analyse_lap(trace, sa.model)
        out = _analyse(sa, pedals, extra)
        with self._lock:
            self._cache[key] = out
            while len(self._cache) > CACHE_ENTRIES:
                self._cache.popitem(last=False)
        return out

    def setup(self, st: SessionTechnique, car_format: CarFormat | None = None) -> SetupEngineer | None:
        if not st.is_f1:
            return None
        with self.db.read() as c:
            row = repo.latest_setup(c, st.session_id)
            exps = repo.list_setup_experiments(c, session_id=st.session_id)
        testing = frozenset(
            str(e["parameter"])
            for e in exps
            if e.get("status") in ("proposed", "running") and e.get("before_session_id") == st.session_id
        )
        return setup_engineer(st, row, testing, car_format)

    def session_payload(
        self, session_id: str, ref_lap_id: int | None = None, car_format: CarFormat | None = None
    ) -> dict[str, Any]:
        st = self.analyse(session_id, ref_lap_id)
        return st.to_dict(self.setup(st, car_format))

    def balance_payload(self, session_id: str, car_format: CarFormat | None = None) -> dict[str, Any]:
        st = self.analyse(session_id)
        return st.balance_dict(self.setup(st, car_format))

    # ------------------------------------------------------------------ setup experiments
    def balance_change(self, before_sid: str, after_sid: str) -> dict[str, Any]:
        """``ExperimentBalance``: how the handling balance moved between a setup experiment's two sessions."""
        note = "Balance uses Pitwall's heuristic thresholds; one session each: an indication, not proof."
        try:
            before, after = self.analyse(before_sid), self.analyse(after_sid)
        except (TechniqueNotFound, NoTrackModel) as e:
            return {"available": False, "reason": str(e), "changes": [], "note": note}
        if not (before.available["balance"].ok and after.available["balance"].ok):
            return {
                "available": False,
                "reason": no_slip_reason(before.session.get("game")),
                "changes": [],
                "note": note,
            }
        return {"available": True, "reason": None, "changes": balance_changes(before, after), "note": note}

    # ------------------------------------------------------------------ lap pair
    def compare(self, ref_lap_id: int, lap_id: int) -> dict[str, Any]:
        with self.db.read() as c:
            a, b = repo.load_lap_trace(c, ref_lap_id), repo.load_lap_trace(c, lap_id)
            if a is None or b is None:
                raise TechniqueNotFound("lap not found")
            sa_ = repo.get_session(c, a.meta["session_id"])
            sb = repo.get_session(c, b.meta["session_id"])
            if sa_ is None or sb is None:
                raise TechniqueNotFound("lap not found")
            fam = carclass.family_of_row(sb)  # the compared lap's car class family
            model = repo.load_track_model(c, sa_["game"], sa_["track_id"], fam) if sa_.get("track_id") else None
        if model is not None and not lengths_compatible(model.length_m, sa_.get("track_length_m")):
            model = None  # the stored model is of another layout under the same track id (AC consoles)
        if model is None:
            raise NoTrackModel()
        pedals = pedal_info(
            self._pedals_at(sb.get("started_unix")),
            self._pedals_at(sa_.get("started_unix")),
            ref_known=self.rig_profile() is not None,
        )
        return compare_pair(a, b, sa_, sb, model, pedals, ref_lap_id, lap_id)


def compare_pair(
    a: Any,
    b: Any,
    sess_a: Mapping[str, Any],
    sess_b: Mapping[str, Any],
    model: TrackModel,
    pedals: PedalInfo,
    ref_lap_id: int,
    lap_id: int,
) -> dict[str, Any]:
    """TechniqueCompare for reference trace ``a`` and lap trace ``b`` (``LapTrace``)."""
    a.meta.update(session_ctx(dict(sess_a)))
    b.meta.update(session_ctx(dict(sess_b)))
    compat = check_compatibility(compat_meta(a.meta), compat_meta(b.meta), a.clean)
    model = identify(model, zones=TrackZones.from_dict((sess_b.get("info") or {}).get("track_zones")))[0]
    assists = assist_info(sess_b.get("game"), sess_b.get("assists"), [b.meta])
    synthetic = bool(sess_a.get("synthetic")) or bool(sess_b.get("synthetic"))
    base: dict[str, Any] = {
        "ref_lap_id": ref_lap_id,
        "lap_id": lap_id,
        "ref_lap_number": a.lap_number,
        "lap_number": b.lap_number,
        "synthetic": synthetic,
        "compatible": compat.ok,
        "blocking": list(compat.blocking),
        "warnings": list(compat.warnings),
        "lines": None,
        "markers": [],
        "corners": [],
        "pedals": pedals.to_dict(),
        "assists": assists.to_dict(),
    }
    has_slip = all(k in b.channels and bool(np.isfinite(b.channels[k]).any()) for k in SLIP_CHANNELS)
    has_bal = all(k in b.channels and bool(np.isfinite(b.channels[k]).any()) for k in BALANCE_CHANNELS)
    if not compat.ok:
        why = "These laps cannot be compared: " + "; ".join(compat.blocking)
        base["available"] = {
            k: Availability(False, why).to_dict() for k in ("line", "inputs", "slip", "balance", "setup")
        }
        return base
    ra, rb = analyse_lap(a, model), analyse_lap(b, model)
    comp = compare(ra, rb, compat)
    plane = model.ground_plane
    ref_line = reference_line(ra.dtrace, plane)
    line_ok = ref_line.has_positions
    off = lateral_offsets(ref_line, rb.dtrace, plane) if line_ok else np.full(len(rb.dtrace.d), np.nan)
    texts = corner_texts(model)
    na, nb = native(a), native(b)
    tol = pedals.tolerances
    muted = assists.brake_notes_muted
    corners: list[dict[str, Any]] = []
    candidates: list[tuple[float, float, dict[str, Any]]] = []  # (|offset|, time loss, marker)
    for c in model.corners:
        ct = texts.get(c.name)
        rcm, lcm = ra.corners.get(c.name), rb.corners.get(c.name)
        apex = _apex(ra, c, c.apex_m)
        turn_in, track_out = _lap_points(ra, apex, (c.entry_m, c.exit_m))
        apex_lap = _apex(rb, c, apex)
        ti_lap, to_lap = _lap_points(rb, apex_lap, (turn_in, track_out))
        r_in = corner_inputs(
            na,
            _event_for(ra, rcm),
            apex,
            turn_in,
            track_out,
            _next_brake(ra, apex),
            abs_on=a.meta.get("abs_active"),
            tc_level=a.meta.get("traction_control"),
        )
        l_in = corner_inputs(
            nb,
            _event_for(rb, lcm),
            apex_lap,
            ti_lap,
            to_lap,
            _next_brake(rb, apex_lap),
            abs_on=b.meta.get("abs_active"),
            tc_level=b.meta.get("traction_control"),
        )
        cd = next((x for x in comp.corners if x.corner == c.name), None)
        incident = cd is not None and is_incident(cd)
        inside = inside_sign(ref_line, apex) if line_ok else 0
        offsets: dict[str, float | None] = dict.fromkeys(POINT_KEYS)
        window: dict[str, Any] | None = None
        if line_ok:
            if not incident:
                for k, at in zip(POINT_KEYS, (turn_in, apex, track_out), strict=True):
                    v = point_offset(rb.dtrace.d, off, at)
                    offsets[k] = None if v is None else (v * inside if inside else abs(v))
            if turn_in is not None and track_out is not None:
                d = rb.dtrace.d
                wd = np.arange(
                    max(0.0, turn_in - T.LINE_WINDOW_MARGIN_M),
                    min(float(d[-1]), track_out + T.LINE_WINDOW_MARGIN_M) + 1e-9,
                    T.LINE_WINDOW_STEP_M,
                )
                wv = np.interp(wd, d, off, left=np.nan, right=np.nan)
                wv = wv * inside if inside else np.abs(wv)
                window = {"d_m": [round(float(x), 2) for x in wd], "offset_m": [m2(float(x)) for x in wv]}
        notes = [] if incident else compare_inputs(l_in, r_in, tol, _resolution_m(nb, apex_lap), muted=muted)
        label, name = _corner_label(c)
        cname = ct.long if ct else c.name
        cshort = ct.short if ct else c.name
        loss = cd.time_delta_s if cd is not None else None
        corners.append(
            {
                "corner": c.name,
                "label": label,
                "name": name,
                "direction": c.direction,
                "time_delta_s": rnd(loss, 3),
                "incident": incident,
                "inside_known": inside != 0,
                "points": {"turn_in": m2(turn_in), "apex": m2(apex), "track_out": m2(track_out)},
                "offsets": {k: m2(v) for k, v in offsets.items()},
                "window": window,
                "ref_inputs": r_in.to_dict(),
                "lap_inputs": l_in.to_dict(),
                "notes": [n.to_dict() for n in notes],
                "ref_balance": _balance_dict(lap_balance(na, apex, c.seg_start_m, c.seg_end_m)),
                "lap_balance": _balance_dict(lap_balance(nb, apex_lap, c.seg_start_m, c.seg_end_m)),
            }
        )
        for k, at in zip(POINT_KEYS, (turn_in, apex, track_out), strict=True):
            v = offsets[k]
            if v is None or at is None or abs(v) < T.LINE_NOTABLE_M:
                continue
            pa = float(np.interp(at, rb.dtrace.d, rb.dtrace.ch.get(plane[0], np.full(len(rb.dtrace.d), np.nan))))
            pb = float(np.interp(at, rb.dtrace.d, rb.dtrace.ch.get(plane[1], np.full(len(rb.dtrace.d), np.nan))))
            if not (np.isfinite(pa) and np.isfinite(pb)):
                continue
            candidates.append(
                (abs(v), loss or 0.0, _marker(c.name, label, k, at, v, inside != 0, pa, pb, cname, cshort))
            )
    candidates.sort(key=lambda x: (-round(x[0], 2), -x[1]))
    seen: set[str] = set()
    per_corner: list[dict[str, Any]] = []  # the biggest difference of each corner (markers never repeat a corner)
    for _, _, m in candidates:
        if m["corner"] not in seen:
            seen.add(m["corner"])
            per_corner.append(m)
    lines = None
    if line_ok:
        _, ra_a, ra_b = polyline(ra.dtrace, plane, T.LINE_POLYLINE_STEP_M)
        _, rb_a, rb_b = polyline(rb.dtrace, plane, T.LINE_POLYLINE_STEP_M)
        lines = {"step_m": T.LINE_POLYLINE_STEP_M, "ref_xz": xz_list(ra_a, ra_b), "lap_xz": xz_list(rb_a, rb_b)}
    base.update(
        lines=lines,
        markers=per_corner[: T.LINE_MAX_MARKERS],
        corners=corners,
        available={
            "line": Availability(
                line_ok,
                None if line_ok else "The reference lap has no position data.",
                "Pitwall does not know the track edges: the lines show where each lap went." if line_ok else None,
            ).to_dict(),
            "inputs": Availability(True).to_dict(),
            "slip": Availability(has_slip, None if has_slip else no_slip_reason(sess_b.get("game"))).to_dict(),
            "balance": Availability(has_bal, None if has_bal else no_slip_reason(sess_b.get("game"))).to_dict(),
            "setup": Availability(False, "Setup suggestions come from a whole session (Setup › Car setup).").to_dict(),
        },
    )
    return base


POINT_WORDS = {"turn_in": "turn-in", "apex": "apex", "track_out": "track-out"}


def _marker(
    corner: str,
    label: str | None,
    point: str,
    d_m: float,
    offset: float,
    inside_known: bool,
    pa: float,
    pb: float,
    cname: str,
    cshort: str,
) -> dict[str, Any]:
    pw = POINT_WORDS[point]
    if inside_known:
        side = "wider" if offset < 0 else "tighter"
        text = f"{cshort} {pw}: {abs(offset):.1f} m {side} than your reference"
        simple = f"You ran {side} at the {pw} of {cname}"
    else:
        text = f"{cshort} {pw}: {abs(offset):.1f} m off your reference line"
        simple = f"You were off your reference line at the {pw} of {cname}"
    return {
        "corner": corner,
        "label": label,
        "point": point,
        "d_m": round(d_m, 2),
        "offset_m": round(offset, 2),
        "xz": [round(pa, 2), round(pb, 2)],
        "text": text,
        "text_simple": simple,
    }


# ---------------------------------------------------------------------------------------------- experiments
BALANCE_CHANGE_MIN_DEG = 1.5
MAX_BALANCE_CHANGES = 6


def _summary_class(s: PhaseSummary) -> str:
    return s.recurring or ("neutral" if s.neutral * 2 >= s.laps else "mixed")


def _summary_words(s: PhaseSummary) -> str:
    if s.laps == 0:
        return "no data"
    cls = _summary_class(s)
    count = {"understeer": s.understeer, "oversteer": s.oversteer, "neutral": s.neutral}.get(cls)
    word = "balanced" if cls == "neutral" else cls
    return f"{word} on {count} of {s.laps} laps" if count is not None else f"mixed over {s.laps} laps"


def _deg(v: float) -> str:
    """Signed degrees with a real minus sign (U+2212)."""
    return f"{v:+.1f}°".replace("-", "\u2212")


def balance_changes(before: SessionTechnique, after: SessionTechnique) -> list[dict[str, Any]]:
    """Corner phases where a symptom recurred in either session, or the median slip difference moved by at least
    1.5 degrees; biggest moves first."""
    after_by = {c.corner: c for c in after.corners}
    rows: list[tuple[float, dict[str, Any]]] = []
    for cb in before.corners:
        ca = after_by.get(cb.corner)
        if ca is None or cb.balance is None or ca.balance is None:
            continue
        for p in PHASES:
            sb, sa_ = cb.balance.get(p), ca.balance.get(p)
            if sb is None or sa_ is None or sb.laps == 0 or sa_.laps == 0:
                continue
            delta = (
                sa_.median_slip_diff_deg - sb.median_slip_diff_deg
                if sa_.median_slip_diff_deg is not None and sb.median_slip_diff_deg is not None
                else None
            )
            if not (sb.recurring or sa_.recurring or (delta is not None and abs(delta) >= BALANCE_CHANGE_MIN_DEG)):
                continue
            wb, wa = _summary_words(sb), _summary_words(sa_)
            unchanged = _summary_class(sb) == _summary_class(sa_) and (
                delta is None or abs(delta) < BALANCE_CHANGE_MIN_DEG
            )
            if unchanged:
                how = f"no change ({wb} both times)" if wb == wa else f"little change ({wb} before, {wa} after)"
                words = f"{cb.long_name} {PHASE_SIMPLE[p]}: {how}"
            else:
                words = f"{cb.long_name} {PHASE_SIMPLE[p]}: {wb} before, {wa} after"
                if delta is not None and sb.median_slip_diff_deg is not None and sa_.median_slip_diff_deg is not None:
                    b_deg, a_deg = sb.median_slip_diff_deg, sa_.median_slip_diff_deg
                    words += f" (front minus rear slip angle {_deg(b_deg)} → {_deg(a_deg)})"
            rows.append(
                (
                    abs(delta) if delta is not None else 0.0,
                    {
                        "corner": cb.corner,
                        "label": cb.long_name,
                        "phase": p,
                        "before": sb.to_dict(),
                        "after": sa_.to_dict(),
                        "delta_deg": rnd(delta, 1),
                        "changed": not unchanged,
                        "words": words + ".",
                    },
                )
            )
    rows.sort(key=lambda r: (not r[1]["changed"], -r[0]))  # real changes first, then the biggest moves
    return [r for _, r in rows[:MAX_BALANCE_CHANGES]]
