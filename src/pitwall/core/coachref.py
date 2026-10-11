"""Reference choice and practice drills (coachref): the rules and the live service.

Reference choice
----------------
Each driver chooses what the live delta, braking calls, live corner comparison and lap coaching measure against
(``RefKind``): ``own_best`` (the default: exactly the pre-coachref rule, their pinned lap else their fastest
compatible clean lap), ``household_best`` (the family record), ``driver_best`` (another driver's best) or ``lap``
(a saved lap). A choice is stored per driver for every track and optionally per track (``repo.reference_choices``);
the track row wins. Only compatible laps qualify: same game, track, layout length and car (the car must be known on
both sides), wet/dry, assists (``analysis.compare.check_compatibility``) and, for other drivers' laps only, AC's
ABS/TC and F1's formula (``extra_blocking``); real driving only (never synthetic sessions or replays). When the
choice yields nothing the own rule applies and ``reason`` says why in plain words. Unowned, synthetic and replayed
sessions always use the own rule. Review (summaries, Work on, Progress) is never re-based on another driver.

Safety (CLAUDE.md "coaching never recommends braking later on its own"): against another driver's lap the lap
processor sends ``brake_clamp_m`` (the driver's own braking point per corner) with the comparison, and the cue
planner calls ``min(their point, your point)``; a corner with no point of the driver's own gets no call. Drill
targets use the same clamp.

Practice drills
---------------
``coach.drills`` holds the pure rules; this service runs them: one active drill per driver, only in a live session
of the seated driver at a track whose model is frozen, evaluated after every stored lap (``after_lap``), stored in
``repo.drills``. While a drill runs the reference and its clamp are frozen (``frozen_for``), the cue plan holds the
drill corner only and the lap's coaching is the drill point. A lap in other conditions than the drill's start (another
car or layout, wet/dry, a different assist: ``DrillSpec.context``) stops the drill (``context_changed``), and the
frozen reference is never used for such a lap. Safety-car laps are no attempts. The last drill a driver finished (or
that stopped with attempts) stays published for them until they put it away (``dismiss_result``).

Threads (D8): every change of choice or drill state runs on the lap-analysis thread (``run_task``, i.e.
``AnalysisWorker.submit_task``), so nothing here needs a lock with the lap pipeline; API threads wait at most
``TASK_TIMEOUT_S`` for a task to start (``Busy`` -> HTTP 503, and the task is withdrawn); one already running is
waited for, so a refused request never takes effect later. The ingest thread is never involved. ``live.coachref`` is
published with one attribute swap after every change.

Early reference: when the seated driver's live session has a complete context (game, track, layout, car) and no lap
of it is in yet, the chosen reference is resolved and published at once (``on_context``), so the delta runs from the
first lap; braking calls still wait for a lap's comparison.

Evidence tier: unit + synthetic + recorded-tested (``scripts/coachref_check.py`` on the owner's F1 25 captures); not
live-validated.
"""

from __future__ import annotations

import logging
import math
import queue
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar, cast

import numpy as np

from pitwall.analysis.coaching import observations_for_comparison
from pitwall.analysis.compare import (
    CornerMetrics,
    LapAnalysis,
    LapComparison,
    analyse_lap,
    check_compatibility,
    compare,
    compat_meta,
    lengths_compatible,
)
from pitwall.analysis.laps import LapTrace
from pitwall.analysis.track import Corner, TrackModel
from pitwall.analysis.track_identity import CornerText, corner_texts, identify, resolve_corner_ref, track_model_payload
from pitwall.coach import drills as dr
from pitwall.coach.cues import MIN_REF_BRAKE_PEAK, MIN_REF_SPEED_DROP_KPH, reference_onset_ok
from pitwall.coach.reference_wording import descriptor_labels, reword_observations
from pitwall.core.lap_processor import TRACK_MODEL_TARGET_LAPS, CoachrefContext
from pitwall.model.telemetry import FrameQuality, SessionInfo, TrackZones
from pitwall.storage import repo

if TYPE_CHECKING:
    import sqlite3

    from pitwall.core.lap_processor import LapJob, LapProcessor
    from pitwall.core.live import LiveState
    from pitwall.drivers import Driver, DriverService
    from pitwall.storage.db import Database, DbWriter

log = logging.getLogger(__name__)
T = TypeVar("T")

RefKind = Literal["own_best", "household_best", "driver_best", "lap"]
REF_KINDS: tuple[RefKind, ...] = ("own_best", "household_best", "driver_best", "lap")
Applies = Literal["now", "next_lap", "after_drill", "next_session"]
TASK_TIMEOUT_S = 5.0
LAST_RESOLVED_KEPT = 16  # sessions whose latest resolution is remembered (used_kind / reason)
_WET = frozenset({"light_rain", "heavy_rain", "storm"})  # analysis.compare.check_compatibility's wet set
_NOT_DRIVING = FrameQuality.PAUSED | FrameQuality.NOT_RACING | FrameQuality.REPLAY_OR_SPECTATING
_IN_PITS = (1, 2)
_NO_SAFETY_CAR = frozenset({"none"})  # coach.cues: a safety_car_status meaning no safety car

# ---------------------------------------------------------------------------------------------- sentences
LEGACY_REASON = "replays and synthetic sessions use their own laps"
UNKNOWN_CAR = "the car is unknown, so other drivers' laps can't be matched"
DRIVER_REMOVED = "that driver's profile was removed"
LAP_GONE = "the saved lap is no longer available"
NO_FAMILY = "no family lap here matches your car and settings"
LIVE_ONLY = "Drills run on your own live driving."
LEARNING = f"Pitwall is still learning this track: drive {TRACK_MODEL_TARGET_LAPS} clean laps first."
NO_CORNER = "Which corner? Say, for example, drill turn 3."
NO_DRILL = "No drill running."
NO_DRILL_HINT = "No drill running. Say 'start a drill on turn 3'."
_DRIVER_REASONS = {
    "none": "{name} has no clean lap here yet",
    "car": "{name} has no lap here in this car",
    "track": "{name} has no clean lap here yet",
    "layout": "{name}'s laps here were on another layout",
    "wet": "{name}'s laps here were set in the wet",
    "dry": "{name}'s laps here were set in the dry",
    "braking": "{name}'s laps here used a different braking assist",
    "gearbox": "{name}'s laps here used a different gearbox setting",
    "abs": "{name}'s laps here used a different ABS setting",
    "tc": "{name}'s laps here used a different traction control setting",
    "formula": "{name}'s laps here were in a different car class",
    "other": "{name}'s laps here can't be compared with this session",
}
_LAP_REASONS = {
    "track": "it was set at another track",
    "car": "it was set in another car",
    "layout": "it was set on another layout",
    "wet": "it was set in the wet",
    "dry": "it was set in the dry",
    "braking": "it used a different braking assist",
    "gearbox": "it used a different gearbox setting",
    "abs": "it used a different ABS setting",
    "tc": "it used a different traction control setting",
    "formula": "it was in a different car class",
    "other": "its conditions differ from this session",
}


# ---------------------------------------------------------------------------------------------- errors
class CoachRefError(Exception):
    """A refusal with a plain sentence for the screen or the radio (``status`` = HTTP status)."""

    status = 400

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else self.__class__.__name__


class NotFound(CoachRefError):
    status = 404


class Conflict(CoachRefError):
    status = 409


class Invalid(CoachRefError):
    status = 422


class Busy(CoachRefError):
    status = 503


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _int(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


# ============================================================================================== choices
@dataclass(frozen=True, slots=True)
class ReferenceChoice:
    """A driver's choice for every track (``game == track_id == ''``) or for one track. ``updated_unix`` None =
    the default (no stored row)."""

    driver_id: int
    kind: RefKind = "own_best"
    target_driver_id: int | None = None
    lap_id: int | None = None
    game: str = ""
    track_id: str = ""
    updated_unix: float | None = None

    @property
    def scope(self) -> str:
        return "track" if self.game and self.track_id else "all_tracks"

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> ReferenceChoice:
        kind = row.get("kind")
        return cls(
            driver_id=int(row["driver_id"]),
            kind=cast(RefKind, kind if kind in REF_KINDS else "own_best"),
            target_driver_id=_int(row.get("target_driver_id")),
            lap_id=_int(row.get("lap_id")),
            game=str(row.get("game") or ""),
            track_id=str(row.get("track_id") or ""),
            updated_unix=_num(row.get("updated_unix")),
        )

    def to_dict(self, label: str) -> dict[str, Any]:
        """``ReferenceChoice`` JSON (spec 6.2)."""
        return {
            "driver_id": self.driver_id,
            "kind": self.kind,
            "target_driver_id": self.target_driver_id,
            "lap_id": self.lap_id,
            "scope": self.scope,
            "game": self.game or None,
            "track_id": self.track_id or None,
            "label": label,
            "updated_unix": self.updated_unix,
        }


def effective_choice(
    conn: sqlite3.Connection, driver_id: int, game: str | None, track_id: str | None
) -> ReferenceChoice:
    """The track row, else the all-tracks row, else ``own_best``."""
    rows = repo.reference_choice_rows(conn, driver_id, game, track_id)
    row = rows["track"] or rows["all_tracks"]
    return ReferenceChoice.from_row(row) if row is not None else ReferenceChoice(driver_id)


def choice_label(conn: sqlite3.Connection, choice: ReferenceChoice) -> str:
    """ "Your best", "Family record", "Sam's best", "Sam · lap 7 · 3 Oct" / "Your lap 7 · 3 Oct"."""
    if choice.kind == "household_best":
        return "Family record"
    if choice.kind == "driver_best":
        d = repo.get_driver(conn, choice.target_driver_id) if choice.target_driver_id is not None else None
        return f"{d['name']}'s best" if d is not None else "Another driver's best"
    if choice.kind == "lap":
        info = repo.lap_with_context(conn, choice.lap_id) if choice.lap_id is not None else None
        if info is None:
            return "A saved lap"
        own = info.get("driver_id") == choice.driver_id
        name, number, when = info.get("driver_name"), info.get("lap_number"), info.get("created_unix")
        return descriptor_labels("lap", own, False, name, number, when)[0]
    return "Your best"


# ============================================================================================== compatibility
def ctx_from_session_info(info: SessionInfo) -> dict[str, Any]:
    """A lap context (``LapJob.context`` keys plus ``formula``) from a live ``SessionInfo``."""
    return {
        "game": info.game.value,
        "track_id": info.track_id,
        "track_name": info.track_name,
        "track_length_m": info.track_length_m,
        "car_id": info.car_id,
        "car_name": info.car_name,
        "weather": info.weather.condition,
        "track_temp_c": info.weather.track_temp_c,
        "assists": dict(info.assists),
        "formula": info.formula,
        "setup_fp": None,
    }


def ctx_from_lap(info: Mapping[str, Any]) -> dict[str, Any]:
    """A lap context from a ``repo.lap_with_context`` / ``reference_candidates`` row (its session's conditions)."""
    weather = info.get("weather")
    w: Mapping[str, Any] = weather if isinstance(weather, Mapping) else {}
    meta_raw = info.get("meta")
    meta: Mapping[str, Any] = meta_raw if isinstance(meta_raw, Mapping) else {}
    assists = info.get("assists")
    return {
        "game": info.get("game"),
        "track_id": info.get("track_id"),
        "track_name": info.get("track_name"),
        "track_length_m": info.get("track_length_m"),
        "car_id": info.get("car_id"),
        "car_name": info.get("car_name"),
        "weather": w.get("condition"),
        "track_temp_c": w.get("track_temp_c"),
        "assists": dict(assists) if isinstance(assists, Mapping) else {},
        "formula": info.get("formula"),
        "setup_fp": info.get("setup_fp"),
        "tyre_compound": meta.get("tyre_compound"),
        "fuel_start_kg": meta.get("fuel_start_kg"),
    }


def _assists(m: Mapping[str, Any]) -> Mapping[str, Any]:
    a = m.get("assists")
    return a if isinstance(a, Mapping) else {}


def extra_blocking(cand: Mapping[str, Any], ctx: Mapping[str, Any]) -> list[str]:
    """Blocking differences checked for other drivers' laps only (on top of ``check_compatibility``): AC's ABS and
    traction control (``assists.abs`` / ``assists.tc``) and F1's formula, when both sides know them."""
    out: list[str] = []
    ca, cb = _assists(cand), _assists(ctx)
    for key, label in (("abs", "ABS"), ("tc", "traction control")):
        a, b = ca.get(key), cb.get(key)
        if a is not None and b is not None and a != b:
            out.append(f"different {label} setting ({a} vs {b})")
    fa, fb = cand.get("formula"), ctx.get("formula")
    if fa is not None and fb is not None and fa != fb:
        out.append(f"different car class ({fa} vs {fb})")
    return out


def _block_code(cand: Mapping[str, Any], ctx: Mapping[str, Any]) -> str | None:
    """The first blocking difference of a candidate lap against the context, in ``check_compatibility``'s order."""
    a, b = compat_meta(dict(cand)), compat_meta(dict(ctx))
    for key in ("game", "track_id"):
        if a.get(key) is not None and b.get(key) is not None and a[key] != b[key]:
            return "track"
    if a.get("car_id") is not None and b.get("car_id") is not None and a["car_id"] != b["car_id"]:
        return "car"
    if (
        a.get("track_length_m") is not None
        and b.get("track_length_m") is not None
        and not lengths_compatible(a["track_length_m"], b["track_length_m"])
    ):
        return "layout"
    wa, wb = a.get("weather"), b.get("weather")
    if wa and wb and ((wa in _WET) != (wb in _WET)):
        return "wet" if wa in _WET else "dry"
    ba, bb = a.get("braking_assist"), b.get("braking_assist")
    if ba is not None and bb is not None and ba != bb:
        return "braking"
    ca, cb = _assists(cand), _assists(ctx)
    for key in ("abs", "tc"):
        if ca.get(key) is not None and cb.get(key) is not None and ca[key] != cb[key]:
            return key
    ga, gb = a.get("gearbox_assist"), b.get("gearbox_assist")
    if ga is not None and gb is not None and ga != gb:
        return "gearbox"
    fa, fb = cand.get("formula"), ctx.get("formula")
    if fa is not None and fb is not None and fa != fb:
        return "formula"
    return None


def comparable(cand: Mapping[str, Any], ctx: Mapping[str, Any]) -> tuple[bool, list[str], str | None]:
    """``(usable, warnings, first blocking code)`` of a candidate lap (``ctx_from_lap`` shape or a candidate row)
    for the live context. Warnings (compound, setup, fuel, temperature) never exclude a lap."""
    c = ctx_from_lap(cand) if "lap_id" in cand else dict(cand)
    compat = check_compatibility(compat_meta(c), compat_meta(dict(ctx)), True)
    extra = extra_blocking(c, ctx)
    ok = compat.ok and not extra
    return ok, list(compat.warnings), None if ok else (_block_code(c, ctx) or "other")


def _driver_reason(code: str | None, name: str) -> str:
    return _DRIVER_REASONS.get(code or "other", _DRIVER_REASONS["other"]).format(name=name)


# ============================================================================================== resolution
@dataclass(frozen=True, slots=True)
class FrozenRef:
    """The reference held for a drill: its lap, the descriptor at the start and the braking clamp."""

    lap_id: int
    desc: Mapping[str, Any]
    clamp: Mapping[str, float] | None


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    """What the live pipeline compares against, and why (``to_dict`` = ``ReferenceDescriptor``, spec 6.2)."""

    lap_id: int | None
    kind: RefKind = "own_best"  # what picked it, after any fallback
    own: bool = True  # the lap belongs to the session's driver
    pinned: bool = False
    driver_id: int | None = None  # the lap's holder
    driver_name: str | None = None
    lap_number: int | None = None
    lap_time_ms: int | None = None
    session_id: str | None = None
    set_unix: float | None = None
    reason: str | None = None  # why the choice could not be honoured (plain words)
    frozen: bool = False  # held for an active drill
    clamp: Mapping[str, float] | None = None  # the frozen braking clamp (drill)
    owner: int | None = None  # the session's driver it was resolved for

    @property
    def labels(self) -> tuple[str, str, str | None]:
        return descriptor_labels(self.kind, self.own, self.pinned, self.driver_name, self.lap_number, self.set_unix)

    @property
    def ref_name(self) -> str | None:
        return None if self.own else self.labels[2]

    def to_dict(self) -> dict[str, Any]:
        label, label_to, ref_name = self.labels
        return {
            "lap_id": self.lap_id,
            "lap_number": self.lap_number,
            "lap_time_ms": self.lap_time_ms,
            "session_id": self.session_id,
            "kind": self.kind,
            "own": self.own,
            "pinned": self.pinned,
            "driver_id": self.driver_id,
            "driver_name": self.driver_name,
            "set_unix": self.set_unix,
            "label": label,
            "label_to": label_to,
            "ref_name": None if self.own else ref_name,
            "brake_clamped": not self.own and self.lap_id is not None,
            "frozen": self.frozen,
        }


def own_reference(
    conn: sqlite3.Connection,
    game: str,
    track_id: str,
    car_id: str | None,
    driver_id: int | None,
    exclude: int | None,
    track_length_m: float | None,
) -> tuple[int | None, bool]:
    """The pre-coachref rule, unchanged (``LapProcessor._choose_reference``): the driver's active pin, else their
    fastest clean lap of a compatible length, never the lap just driven. ``(lap id, pinned)``."""
    pinned = repo.pinned_reference(conn, game, track_id, car_id, driver_id=driver_id)
    if pinned is not None and pinned != exclude:
        return pinned, True
    for r in repo.clean_laps_for(
        conn, game, track_id, car_id, limit=5, driver_id=driver_id, track_length_m=track_length_m
    ):
        if r["id"] != exclude:
            return int(r["id"]), False
    return None, False


def _resolved_lap(
    info: Mapping[str, Any] | None,
    kind: RefKind,
    owner: int | None,
    *,
    lap_id: int | None = None,
    pinned: bool = False,
    reason: str | None = None,
) -> ResolvedReference:
    if info is None:
        return ResolvedReference(lap_id=lap_id, kind=kind, own=True, pinned=pinned, reason=reason, owner=owner)
    holder = _int(info.get("driver_id"))
    return ResolvedReference(
        lap_id=int(info["lap_id"]),
        kind=kind,
        own=owner is None or holder == owner,
        pinned=pinned,
        driver_id=holder,
        driver_name=info.get("driver_name"),
        lap_number=_int(info.get("lap_number")),
        lap_time_ms=_int(info.get("lap_time_ms")),
        session_id=info.get("session_id"),
        set_unix=_num(info.get("created_unix")),
        reason=reason,
        owner=owner,
    )


def _ctx_keys(ctx: Mapping[str, Any]) -> tuple[str, str, str | None, float | None]:
    length = _num(ctx.get("track_length_m"))
    car = ctx.get("car_id")
    return (
        str(ctx.get("game") or ""),
        str(ctx.get("track_id") or ""),
        car if isinstance(car, str) else None,
        length if length is not None and length > 0 else None,
    )


def household_best(
    conn: sqlite3.Connection, ctx: Mapping[str, Any], exclude: int | None
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    """The family record usable here: ``(candidate row, reason when none, warnings)``."""
    game, track, car, length = _ctx_keys(ctx)
    if car is None:
        return None, UNKNOWN_CAR, []
    for r in repo.reference_candidates(conn, game, track, car, length, exclude_lap_id=exclude, match=dict(ctx)):
        ok, warns, _ = comparable(r, ctx)
        if ok:
            return r, None, warns
    return None, NO_FAMILY, []


def driver_best(
    conn: sqlite3.Connection, ctx: Mapping[str, Any], driver_id: int, name: str, exclude: int | None
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    """``driver_id``'s best lap usable here: ``(candidate row, reason when none, warnings)``. The reason is the
    first blocking difference of their best lap in this car (spec 3.1.1)."""
    game, track, car, length = _ctx_keys(ctx)
    if car is None:
        return None, UNKNOWN_CAR, []
    usable = repo.reference_candidates(
        conn, game, track, car, length, exclude_lap_id=exclude, driver_id=driver_id, match=dict(ctx)
    )
    for r in usable:
        ok, warns, _ = comparable(r, ctx)
        if ok:
            return r, None, warns
    # none usable: the reason is the first blocking difference of their best lap in this car and layout
    rows = repo.reference_candidates(conn, game, track, car, length, exclude_lap_id=exclude, driver_id=driver_id)
    if rows:
        return None, _driver_reason(comparable(rows[0], ctx)[2], name), []
    anywhere = repo.reference_candidates(conn, game, track, None, None, exclude_lap_id=exclude, driver_id=driver_id)
    if not anywhere:
        return None, _driver_reason("none", name), []
    in_car = [r for r in anywhere if r.get("car_id") == car]
    if not in_car:
        return None, _driver_reason("car", name), []
    return None, _driver_reason(comparable(in_car[0], ctx)[2] or "layout", name), []


def resolve_reference(
    conn: sqlite3.Connection,
    owner: int | None,
    ctx: Mapping[str, Any],
    exclude_lap_id: int | None,
    *,
    frozen: FrozenRef | None = None,
    legacy: bool = False,
    choice: ReferenceChoice | None = None,
) -> ResolvedReference:
    """The reference for the session's driver ``owner`` (spec 3.1). ``legacy``: ignore any choice (unowned,
    synthetic or replayed session). ``frozen``: a drill holds the reference."""
    if frozen is not None:
        d = frozen.desc
        kind = d.get("kind")
        return ResolvedReference(
            lap_id=frozen.lap_id,
            kind=cast(RefKind, kind if kind in REF_KINDS else "own_best"),
            own=bool(d.get("own", True)),
            pinned=bool(d.get("pinned", False)),
            driver_id=_int(d.get("driver_id")),
            driver_name=d.get("driver_name") if isinstance(d.get("driver_name"), str) else None,
            lap_number=_int(d.get("lap_number")),
            lap_time_ms=_int(d.get("lap_time_ms")),
            session_id=d.get("session_id") if isinstance(d.get("session_id"), str) else None,
            set_unix=_num(d.get("set_unix")),
            frozen=True,
            clamp=frozen.clamp,
            owner=owner,
        )
    game, track, car, length = _ctx_keys(ctx)
    own_id, pinned = own_reference(conn, game, track, car, owner, exclude_lap_id, length)
    own_info = repo.lap_with_context(conn, own_id) if own_id is not None else None
    own = _resolved_lap(own_info, "own_best", owner, lap_id=own_id, pinned=pinned)
    if legacy or owner is None:
        return own
    choice = choice or effective_choice(conn, owner, game, track)
    if choice.kind == "own_best":
        return own
    if choice.kind == "household_best":
        cand, reason, _ = household_best(conn, ctx, exclude_lap_id)
        return _resolved_lap(cand, "household_best", owner) if cand else replace(own, reason=reason)
    if choice.kind == "driver_best":
        target = repo.get_driver(conn, choice.target_driver_id) if choice.target_driver_id is not None else None
        if target is None:
            return replace(own, reason=DRIVER_REMOVED)
        cand, reason, _ = driver_best(conn, ctx, int(target["id"]), str(target["name"]), exclude_lap_id)
        return _resolved_lap(cand, "driver_best", owner) if cand else replace(own, reason=reason)
    # lap
    info = repo.lap_with_context(conn, choice.lap_id) if choice.lap_id is not None else None
    if (
        info is None
        or not info.get("clean")
        or info.get("synthetic")
        or repo.is_replay_source(str(info.get("source") or ""))
        or not info.get("lap_time_ms")
        or info.get("lap_id") == exclude_lap_id
    ):
        return replace(own, reason=LAP_GONE)
    mine = info.get("driver_id") == owner
    if not mine and (car is None or info.get("car_id") is None):
        return replace(own, reason=f"the saved lap isn't comparable now: {UNKNOWN_CAR}")
    ok, _, code = comparable(info, ctx)
    if not ok:
        return replace(own, reason=f"the saved lap isn't comparable now: {_LAP_REASONS.get(code or 'other')}")
    return _resolved_lap(info, "lap", owner)


# ============================================================================================== options
def _lap_view(info: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """``RefOptionLap`` (spec 6.2)."""
    if info is None:
        return None
    return {
        "lap_id": int(info["lap_id"]),
        "lap_number": _int(info.get("lap_number")),
        "lap_time_ms": _int(info.get("lap_time_ms")),
        "set_unix": _num(info.get("created_unix")),
        "driver_id": _int(info.get("driver_id")),
        "driver_name": info.get("driver_name"),
        "session_id": info.get("session_id"),
        "car_name": info.get("car_name"),
    }


def _option(
    kind: RefKind,
    label: str,
    *,
    target_driver_id: int | None = None,
    lap_id: int | None = None,
    available: bool | None,
    reason: str | None = None,
    warnings: Sequence[str] = (),
    lap: Mapping[str, Any] | None = None,
    selected: bool = False,
) -> dict[str, Any]:
    """``RefOption`` (spec 6.2)."""
    return {
        "kind": kind,
        "target_driver_id": target_driver_id,
        "lap_id": lap_id,
        "label": label,
        "available": available,
        "reason": reason,
        "warnings": list(warnings),
        "lap": _lap_view(lap),
        "selected": selected,
    }


def reference_options(
    conn: sqlite3.Connection,
    driver_id: int,
    ctx: Mapping[str, Any] | None,
    effective: ReferenceChoice | None = None,
    *,
    exclude_lap_id: int | None = None,
    saved_laps: int = 10,
) -> list[dict[str, Any]]:
    """The picker rows: own best, family record, each other driver's best (name order), then up to ``saved_laps``
    compatible laps (kind ``lap``). ``ctx`` None: no live context, so availability is unknown (``None``)."""
    eff = effective or ReferenceChoice(driver_id)

    def selected(kind: RefKind, target: int | None = None, lap: int | None = None) -> bool:
        if eff.kind != kind:
            return False
        if kind == "driver_best":
            return eff.target_driver_id == target
        if kind == "lap":
            return eff.lap_id == lap
        return True

    others = sorted(
        (d for d in repo.list_drivers(conn) if int(d["id"]) != driver_id),
        key=lambda d: (str(d["name"]).lower(), int(d["id"])),
    )
    usable = ctx is not None and bool(ctx.get("game")) and bool(ctx.get("track_id"))
    if not usable or ctx is None:
        out = [
            _option("own_best", "Your best", available=None, selected=selected("own_best")),
            _option("household_best", "Family record", available=None, selected=selected("household_best")),
        ]
        for d in others:
            out.append(
                _option(
                    "driver_best",
                    f"{d['name']}'s best",
                    target_driver_id=int(d["id"]),
                    available=None,
                    selected=selected("driver_best", int(d["id"])),
                )
            )
        return out
    game, track, car, length = _ctx_keys(ctx)
    own_id, _ = own_reference(conn, game, track, car, driver_id, exclude_lap_id, length)
    own_info = repo.lap_with_context(conn, own_id) if own_id is not None else None
    out = [_option("own_best", "Your best", available=True, lap=own_info, selected=selected("own_best"))]
    hh, reason, warns = household_best(conn, ctx, exclude_lap_id)
    out.append(
        _option(
            "household_best",
            "Family record",
            available=hh is not None,
            reason=reason,
            warnings=warns,
            lap=hh,
            selected=selected("household_best"),
        )
    )
    for d in others:
        did, name = int(d["id"]), str(d["name"])
        cand, reason, warns = driver_best(conn, ctx, did, name, exclude_lap_id)
        out.append(
            _option(
                "driver_best",
                f"{name}'s best",
                target_driver_id=did,
                available=cand is not None,
                reason=reason,
                warnings=warns,
                lap=cand,
                selected=selected("driver_best", did),
            )
        )
    if car is not None:
        n = 0
        for r in repo.reference_candidates(
            conn, game, track, car, length, exclude_lap_id=exclude_lap_id, match=dict(ctx)
        ):
            ok, warns, _ = comparable(r, ctx)
            if not ok:
                continue
            lap_id = int(r["lap_id"])
            out.append(
                _option(
                    "lap",
                    f"Lap {r['lap_number']} · {r['driver_name']}",
                    lap_id=lap_id,
                    available=True,
                    warnings=warns,
                    lap=r,
                    selected=selected("lap", lap=lap_id),
                )
            )
            n += 1
            if n >= saved_laps:
                break
    return out


# ============================================================================================== small helpers
def _spacing_p90(lap: LapTrace) -> float | None:
    d = lap.channels.get("distance_m")
    if d is None or len(d) < 3:
        return None
    steps = np.diff(np.asarray(d, dtype=float))
    steps = steps[np.isfinite(steps) & (steps > 0)]
    return float(np.percentile(steps, 90)) if len(steps) else None


def _corner_voice(c: Corner, text: CornerText | None) -> str:
    """The radio form of a corner without its curated name: "Turn 3", "Turn 1, first part", else the voice form."""
    voice = text.voice if text is not None else c.name
    if c.label and c.display_name:
        voice = voice.replace(f", {c.display_name}", "")
    return voice


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s else s


class _IntentLike(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def corner(self) -> str | None: ...


_LAP_WORDS = {"three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_LAPS_RE = re.compile(r"\b(\d{1,2}|" + "|".join(_LAP_WORDS) + r")\s+laps?\b", re.I)
_CORNER_WORDS_RE = re.compile(
    r"\bdrill\s+(?:on|at|for)\s+(.+?)(?=\s+(?:for|with|over|in)\s+\w+\s+laps?\b|\s+please\b|[.?!,]|$)", re.I
)
_KIND_WORDS: tuple[tuple[dr.DrillKind, re.Pattern[str]], ...] = (
    ("brake_point", re.compile(r"\bbrak(?:e|es|ing)\b", re.I)),
    ("min_speed", re.compile(r"\b(?:minimum|apex|min speed|mid-?corner)\b", re.I)),
    ("exit_speed", re.compile(r"\bexit\b", re.I)),
    ("entry_speed", re.compile(r"\b(?:entry|arrival)\b", re.I)),
)


@dataclass(frozen=True, slots=True)
class DrillRequest:
    corner: str | None = None  # learned key
    corner_ref: str | None = None  # "T3", "Turn 3", "Copse"
    kind: str | None = None
    laps: int | None = None
    tolerance: float | None = None
    source: str = "manual"  # work_on | manual | radio
    observation_kind: str | None = None


@dataclass(frozen=True, slots=True)
class ChoiceRequest:
    kind: str
    driver_id: int | None = None
    target_driver_id: int | None = None
    lap_id: int | None = None
    scope: str = "all_tracks"
    game: str | None = None
    track_id: str | None = None


@dataclass(slots=True)
class _DrillEnv:
    session_id: str
    driver_id: int
    ctx: dict[str, Any]
    cx: CoachrefContext
    model: TrackModel
    texts: dict[str, CornerText]


# ============================================================================================== the service
class CoachRef:
    """The live coachref service (see the module docstring for the thread model)."""

    def __init__(
        self,
        db: Database,
        writer: DbWriter,
        live: LiveState,
        drivers: DriverService,
        run_task: Callable[[Callable[[], Any]], Future[Any]],
        *,
        processor: LapProcessor | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db = db
        self.writer = writer
        self.live = live
        self.drivers = drivers
        self.processor = processor
        self._run_task = run_task
        self._clock = clock
        # analysis-thread state (tasks and lap hooks only)
        self._drills: dict[int, dr.DrillState] = {}  # active drill per driver
        self._ended: dict[int, dr.DrillState] = {}  # per driver: the last drill that ended with attempts (until Done)
        self._pending: set[int] = set()  # drivers whose new choice waits for the next lap / the drill's end
        self._last: dict[str, ResolvedReference] = {}  # session -> latest resolution (used_kind, reason)
        self._publish_lock = threading.Lock()
        try:
            n = writer.call(lambda c: repo.stop_active_drills(c, "service_restart", clock()))
            if n:
                log.info("coachref: %d drill(s) left active by the last run were stopped", n)
        except Exception:
            log.exception("coachref: could not stop drills left active by the last run")
        drivers.subscribe(self.on_driver)
        self._publish()

    def close(self) -> None:
        self.drivers.unsubscribe(self.on_driver)

    # ------------------------------------------------------------------ plumbing
    def _task(self, fn: Callable[[], T]) -> T:
        """Run ``fn`` on the analysis thread and wait for it (``Busy`` after ``TASK_TIMEOUT_S``)."""
        try:
            fut = self._run_task(fn)
        except queue.Full as e:
            raise Busy("The analysis is busy: try again in a moment.") from e
        try:
            return cast(T, fut.result(TASK_TIMEOUT_S))
        except TimeoutError as e:
            if fut.cancel():  # still queued: withdrawn, so it never takes effect after the refusal
                raise Busy("The analysis is busy: try again in a moment.") from e
        return cast(T, fut.result())  # already running: its change happens, so answer with it

    def _driver(self, driver_id: int | None) -> int:
        did = driver_id if driver_id is not None else self.drivers.active_id
        if did is None:
            raise NotFound("No driver in the seat.")
        with self.db.read() as c:
            if repo.get_driver(c, did) is None:
                raise NotFound(f"driver {did} not found")
        return did

    def _live_ctx(self) -> dict[str, Any] | None:
        info = self.live.session
        if info is None or not info.track_id:
            return None
        return ctx_from_session_info(info)

    def _moving(self) -> bool:
        """The car is on track and moving (spec 3.1.2): live connection, not in the pits, not paused / not racing,
        and the speed at or above ``MOVING_KPH`` or unknown (unknown is never assumed stopped)."""
        if self.live.connection().get("status") != "live":
            return False
        f = self.live.frame
        if f is None or f.pit_status in _IN_PITS or int(f.quality) & int(_NOT_DRIVING):
            return False
        return f.speed_kph is None or f.speed_kph >= dr.MOVING_KPH

    def _live_session_of(self, driver_id: int) -> dict[str, Any] | None:
        """The live session when it is ``driver_id``'s own real driving and still running."""
        sid = self.live.session_id
        if sid is None:
            return None
        with self.db.read() as c:
            sess = repo.get_session(c, sid)
        if (
            sess is None
            or sess.get("driver_id") != driver_id
            or sess.get("synthetic")
            or repo.is_replay_source(str(sess.get("source") or ""))
            or sess.get("ended_unix") is not None
        ):
            return None
        return sess

    def _applies(self, driver_id: int, game: str = "", track_id: str = "") -> Applies:
        if driver_id in self._drills:
            return "after_drill"
        sess = self._live_session_of(driver_id)
        if sess is None:
            return "next_session"
        if game and (game, track_id) != (sess.get("game"), sess.get("track_id")):
            return "next_session"
        return "next_lap" if self._moving() else "now"

    def _choice_dict(self, conn: sqlite3.Connection, choice: ReferenceChoice) -> dict[str, Any]:
        return choice.to_dict(choice_label(conn, choice))

    def _publish(self) -> None:
        """``live.coachref`` for the seated driver (one attribute swap)."""
        try:
            with self._publish_lock:
                live = self.live
                driver = self.drivers.active_id
                info = live.session
                game = info.game.value if info is not None else None
                track = info.track_id if info is not None else None
                choice = eff = None
                if driver is not None:
                    with self.db.read() as c:
                        eff = effective_choice(c, driver, game, track)
                        choice = self._choice_dict(c, eff)
                res = self._last.get(live.session_id or "")
                if res is not None and res.owner != driver:
                    res = None
                st = self._drills.get(driver) if driver is not None else None
                ended = self._ended.get(driver) if driver is not None else None
                drill = dr.drill_view(st) if st is not None else (dr.drill_view(ended) if ended else None)
                live.coachref = {
                    "driver_id": driver,
                    "choice": choice,
                    "used_kind": res.kind if res is not None else (eff.kind if eff is not None else "own_best"),
                    "reason": res.reason if res is not None else None,
                    "pending": driver in self._pending,
                    "drill": drill,
                }
        except Exception:
            log.exception("coachref publish failed")

    # ------------------------------------------------------------------ choices (API threads)
    def options(self, driver_id: int | None = None) -> dict[str, Any]:
        did = self._driver(driver_id)
        return self._task(lambda: self._options(did))

    def _options(self, driver_id: int) -> dict[str, Any]:
        ctx = self._live_ctx()
        game = str(ctx["game"]) if ctx else None
        track = str(ctx["track_id"]) if ctx else None
        with self.db.read() as c:
            rows = repo.reference_choice_rows(c, driver_id, game, track)
            eff = effective_choice(c, driver_id, game, track)
            opts = reference_options(c, driver_id, ctx, eff)
            choice = self._choice_dict(c, eff)
        context = None
        if ctx is not None:
            keys = ("game", "track_id", "track_name", "car_id", "car_name", "track_length_m")
            context = {k: ctx.get(k) for k in keys}
        return {
            "driver_id": driver_id,
            "context": context,
            "choice": choice,
            "has_track_override": rows["track"] is not None,
            "options": opts,
            "applies": self._applies(driver_id),
        }

    def get_choice(self, driver_id: int, game: str | None = None, track_id: str | None = None) -> dict[str, Any]:
        did = self._driver(driver_id)
        with self.db.read() as c:
            rows = repo.reference_choice_rows(c, did, game, track_id)
            out: dict[str, Any] = {}
            for key in ("all_tracks", "track"):
                row = rows[key]
                out[key] = None if row is None else self._choice_dict(c, ReferenceChoice.from_row(row))
            out["effective"] = self._choice_dict(c, effective_choice(c, did, game, track_id))
        return out

    def set_choice(self, req: ChoiceRequest) -> tuple[dict[str, Any], Applies]:
        did = self._driver(req.driver_id)
        return self._task(lambda: self._set_choice(did, req))

    def _set_choice(self, driver_id: int, req: ChoiceRequest) -> tuple[dict[str, Any], Applies]:
        if req.kind not in REF_KINDS:
            raise Invalid(f"unknown reference kind {req.kind!r}")
        kind: RefKind = req.kind
        target, lap_id = req.target_driver_id, req.lap_id
        game, track = "", ""
        with self.db.read() as c:
            if kind == "driver_best":
                if target is None:
                    raise Invalid("target_driver_id is required for driver_best")
                if repo.get_driver(c, target) is None:
                    raise NotFound(f"driver {target} not found")
                if target == driver_id:
                    kind, target = "own_best", None
            if kind == "lap":
                if lap_id is None:
                    raise Invalid("lap_id is required for a saved lap")
                info = repo.lap_with_context(c, lap_id)
                if info is None:
                    raise NotFound(f"lap {lap_id} not found")
                if not info.get("clean") or info.get("synthetic") or repo.is_replay_source(str(info.get("source"))):
                    raise Conflict("That lap can't be a reference: only clean laps of real driving can.")
                game, track = str(info.get("game") or ""), str(info.get("track_id") or "")
            elif req.scope == "track":
                live_ctx = self._live_ctx() or {}
                game = req.game or str(live_ctx.get("game") or "")
                track = req.track_id or str(live_ctx.get("track_id") or "")
                if not game or not track:
                    raise Invalid("Choose a track: there is no live session to take it from.")
            elif req.scope != "all_tracks":
                raise Invalid(f"unknown scope {req.scope!r}")
        if kind != "driver_best":
            target = None
        if kind != "lap":
            lap_id = None
        k, t, lp, g, tr = kind, target, lap_id, game, track
        row = self.writer.call(
            lambda c: repo.set_reference_choice(c, driver_id, k, game=g, track_id=tr, target_driver_id=t, lap_id=lp)
        )
        applies = self._applies(driver_id, game, track)
        if applies in ("next_lap", "after_drill"):
            self._pending.add(driver_id)
        elif applies == "now":
            self._pending.discard(driver_id)
            self._refresh_live()
        with self.db.read() as c:
            choice = self._choice_dict(c, ReferenceChoice.from_row(row))
        self._publish()
        return choice, applies

    def _refresh_live(self) -> None:
        sid = self.live.session_id
        if self.processor is not None and sid is not None:
            self.processor.refresh_reference(sid)

    def delete_choice(self, driver_id: int, game: str, track_id: str) -> bool:
        did = self._driver(driver_id)
        return self._task(lambda: self._delete_choice(did, game, track_id))

    def _delete_choice(self, driver_id: int, game: str, track_id: str) -> bool:
        gone = self.writer.call(lambda c: repo.delete_reference_choice(c, driver_id, game, track_id))
        if gone and self._applies(driver_id, game, track_id) == "now":
            self._refresh_live()
        self._publish()
        return gone

    # ------------------------------------------------------------------ Review (API threads, read-only)
    def candidates(self, lap_id: int) -> dict[str, Any]:
        """Review › Compare picker A for lap B (``lap_id``): B's driver's own best and the family's laps."""
        with self.db.read() as c:
            info = repo.lap_with_context(c, lap_id)
            if info is None:
                raise NotFound(f"lap {lap_id} not found")
            owner = _int(info.get("driver_id"))
            ctx = ctx_from_lap(info)
            game, track, car, length = _ctx_keys(ctx)
            own_opts = []
            if owner is not None:
                own_id, _ = own_reference(c, game, track, car, owner, lap_id, length)
                own_info = repo.lap_with_context(c, own_id) if own_id is not None else None
                own_opts.append(
                    _option(
                        "own_best",
                        "Your best",
                        available=own_info is not None,
                        reason=None if own_info is not None else "You have no other clean lap here yet",
                        lap=own_info,
                    )
                )
            hh, reason, warns = household_best(c, ctx, lap_id)
            family = [
                _option(
                    "household_best", "Family record", available=hh is not None, reason=reason, warnings=warns, lap=hh
                )
            ]
            others = sorted(
                (d for d in repo.list_drivers(c) if int(d["id"]) != owner),
                key=lambda d: (str(d["name"]).lower(), int(d["id"])),
            )
            for d in others:
                did, name = int(d["id"]), str(d["name"])
                cand, reason, warns = driver_best(c, ctx, did, name, lap_id)
                family.append(
                    _option(
                        "driver_best",
                        f"{name}'s best",
                        target_driver_id=did,
                        available=cand is not None,
                        reason=reason,
                        warnings=warns,
                        lap=cand,
                    )
                )
        return {
            "lap_id": lap_id,
            "driver_id": owner,
            "groups": [
                {"id": "own", "title": "Your best here", "options": own_opts},
                {"id": "family", "title": "Family", "options": family},
            ],
        }

    def compare(self, ref: int, lap: int) -> dict[str, Any]:
        """``/api/compare`` plus ``reference`` (a descriptor of lap ``ref`` relative to lap ``lap``'s driver); the
        observations name the other driver when ``ref`` is theirs."""
        from pitwall.core.session_analysis import session_ctx

        with self.db.read() as c:
            a, b = repo.load_lap_trace(c, ref), repo.load_lap_trace(c, lap)
            if a is None or b is None:
                raise NotFound("lap not found")
            sa = repo.get_session(c, a.meta["session_id"])
            sb = repo.get_session(c, b.meta["session_id"])
            if sa is None or sb is None:
                raise NotFound("lap not found")
            model = repo.load_track_model(c, sa["game"], sa["track_id"]) if sa.get("track_id") else None
            info_a = repo.lap_with_context(c, ref)
            info_b = repo.lap_with_context(c, lap)
            assert info_a is not None and info_b is not None
            owner = _int(info_b.get("driver_id"))
            # what picked lap A, for the label: the holder's best here ("Sam's best", "Your best"), else a saved lap
            kind: RefKind = "lap"
            ctx_b = ctx_from_lap(info_b)
            game, track, car, length = _ctx_keys(ctx_b)
            holder = _int(info_a.get("driver_id"))
            if holder is not None and owner is not None:
                if holder == owner:
                    if own_reference(c, game, track, car, owner, lap, length)[0] == ref:
                        kind = "own_best"
                else:
                    best, _, _ = driver_best(c, ctx_b, holder, str(info_a.get("driver_name") or ""), lap)
                    if best is not None and int(best["lap_id"]) == ref:
                        kind = "driver_best"
        if model is None:
            raise Conflict("no track model yet for this track (complete a clean lap first)")
        a.meta.update(session_ctx(sa))
        b.meta.update(session_ctx(sb))
        compat = check_compatibility(compat_meta(a.meta), compat_meta(b.meta), a.clean)
        desc = _resolved_lap(info_a, kind, owner)
        if not desc.own:  # another driver's lap: the stricter rules for other drivers' laps
            extra = extra_blocking(ctx_from_lap(info_a), ctx_b)
            if extra:
                compat = replace(compat, ok=False, blocking=[*compat.blocking, *extra])
        model = identify(model, zones=TrackZones.from_dict((sb.get("info") or {}).get("track_zones")))[0]
        ra, rb = analyse_lap(a, model), analyse_lap(b, model)
        comp = compare(ra, rb, compat)
        texts = corner_texts(model)
        obs = observations_for_comparison(comp, corner_text=texts)
        if not desc.own:
            obs = reword_observations(obs, desc.ref_name, texts)
        out = desc.to_dict()
        out["brake_clamped"] = False  # Review compares; it calls no braking points
        return {
            "comparison": comp.to_dict(),
            "observations": [o.to_dict() for o in obs],
            "track_model": track_model_payload(model),
            "reference": out,
        }

    # ------------------------------------------------------------------ drills (API threads)
    def drill_options(self, corner: str | None = None, corner_ref: str | None = None) -> dict[str, Any]:
        return self._task(lambda: self._drill_options(corner, corner_ref))

    def start_drill(self, req: DrillRequest) -> dict[str, Any]:
        return self._task(lambda: self._start_drill(req))

    def stop_drill(self, driver_id: int | None = None) -> dict[str, Any] | None:
        did = driver_id if driver_id is not None else self.drivers.active_id
        if did is None:
            return None
        st = self._task(lambda: self._stop(did, "driver"))
        return None if st is None else dr.drill_view(st)

    def active_drill(self, driver_id: int | None = None) -> dict[str, Any] | None:
        did = driver_id if driver_id is not None else self.drivers.active_id
        if did is None:
            return None
        st = self._task(lambda: self._active(did))
        return None if st is None else dr.drill_view(st)

    def dismiss_result(self, drill_id: int, driver_id: int | None = None) -> bool:
        """Put away a finished drill's result (the Ready card's Done): it is no longer published. False when it is
        not the driver's last result."""
        did = driver_id if driver_id is not None else self.drivers.active_id
        if did is None:
            return False
        return self._task(lambda: self._dismiss(did, drill_id))

    def _dismiss(self, driver_id: int, drill_id: int) -> bool:
        st = self._ended.get(driver_id)
        if st is None or st.spec.id != drill_id:
            return False
        del self._ended[driver_id]
        self._publish()
        return True

    def drills(
        self,
        driver_id: int | None = None,
        game: str | None = None,
        track_id: str | None = None,
        car_id: str | None = None,
        *,
        include_empty: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self.db.read() as c:
            rows = repo.list_drills(c, driver_id, game, track_id, car_id, include_empty=include_empty, limit=limit)
        return [dr.drill_view(dr.state_from_row(r)) for r in rows]

    def drill(self, drill_id: int) -> dict[str, Any]:
        with self.db.read() as c:
            row = repo.get_drill(c, drill_id)
        if row is None:
            raise NotFound(f"drill {drill_id} not found")
        return dr.drill_view(dr.state_from_row(row))

    # ------------------------------------------------------------------ radio (a worker thread)
    def radio_command(self, intent: _IntentLike, question: str) -> tuple[str, dict[str, Any]]:
        """Answer a drill intent at once (``ai.engineer`` control answer, no LLM): ``(text, control)``."""
        action = intent.name
        try:
            if action == "drill_start":
                ref = intent.corner or self._corner_words(question)
                if not ref:
                    return NO_CORNER, {"action": action, "drill_id": None}
                laps = None
                m = _LAPS_RE.search(question)
                if m:
                    raw = m.group(1).lower()
                    laps = _LAP_WORDS.get(raw) or int(raw)
                kind = next((k for k, rx in _KIND_WORDS if rx.search(question)), None)
                view = self.start_drill(DrillRequest(corner_ref=ref, kind=kind, laps=laps, source="radio"))
                text = (
                    f"Copy. {view['corner_voice']} {str(view['skill_label']).lower()} drill, {view['laps_target']} "
                    f"laps: {_lower_first(str(view['target_text']))}. It starts on your next lap."
                )
                return text, {"action": action, "drill_id": view["id"]}
            if action == "drill_status":
                text, drill_id = self._task(self._status_text)
                return text, {"action": action, "drill_id": drill_id}
            if action == "drill_stop":
                did = self.drivers.active_id
                st = self._task(lambda: self._stop(did, "driver")) if did is not None else None
                if st is None:
                    return NO_DRILL, {"action": action, "drill_id": None}
                return dr.stop_text(st), {"action": action, "drill_id": st.spec.id}
        except CoachRefError as e:
            return str(e), {"action": action, "drill_id": None}
        return "Drills aren't available right now.", {"action": action, "drill_id": None}

    @staticmethod
    def _corner_words(question: str) -> str | None:
        m = _CORNER_WORDS_RE.search(question.strip())
        if m is None:
            return None
        words = re.sub(r"^(?:the)\s+", "", m.group(1).strip(), flags=re.I)
        return words or None

    def _status_text(self) -> tuple[str, int | None]:
        did = self.drivers.active_id
        st = self._active(did) if did is not None else None
        if st is not None:
            return dr.status_text(st), st.spec.id
        ended = self._ended.get(did) if did is not None else None
        if ended is not None and ended.attempts:
            text = dr.drill_view(ended)["summary_text"]
            return str(text), ended.spec.id
        return NO_DRILL_HINT, None

    # ------------------------------------------------------------------ analysis-thread hooks
    def own_reference(
        self,
        conn: sqlite3.Connection,
        game: str,
        track_id: str,
        car_id: str | None,
        driver_id: int | None,
        exclude: int | None,
        track_length_m: float | None,
    ) -> int | None:
        return own_reference(conn, game, track_id, car_id, driver_id, exclude, track_length_m)[0]

    def resolve(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        owner: int | None,
        ctx: Mapping[str, Any],
        exclude: int | None,
        *,
        record: bool = True,
    ) -> ResolvedReference:
        """``LapProcessor._choose_reference`` with a service: the chosen reference for the session's driver.
        ``record`` False only looks (drill options before the session's first lap): the result is not published and
        a pending choice stays pending."""
        sess = repo.get_session(conn, session_id)
        info = sess.get("info") if sess is not None else None
        full = dict(ctx)
        if isinstance(info, Mapping) and full.get("formula") is None:
            full["formula"] = info.get("formula")
        legacy = (
            owner is None
            or sess is None
            or bool(sess.get("synthetic"))
            or repo.is_replay_source(str(sess.get("source") or ""))
        )
        frozen = None if legacy or owner is None else self.frozen_for(owner, full)
        res = resolve_reference(conn, owner, full, exclude, frozen=frozen, legacy=legacy)
        if legacy and owner is not None:
            game, track, _, _ = _ctx_keys(full)
            if effective_choice(conn, owner, game, track).kind != "own_best":
                res = replace(res, reason=LEGACY_REASON)
        if not record:
            return res
        if owner is not None and not res.frozen:
            self._pending.discard(owner)
        self._last[session_id] = res
        while len(self._last) > LAST_RESOLVED_KEPT:
            del self._last[next(iter(self._last))]
        if self.live.session_id == session_id:
            self._publish()
        return res

    def frozen_for(self, owner: int, ctx: Mapping[str, Any]) -> FrozenRef | None:
        """The reference a running drill holds for ``owner`` at this track (None: no drill, or none to hold)."""
        st = self._drills.get(owner)
        if st is None or st.spec.ref_lap_id is None:
            return None
        if (str(ctx.get("game") or ""), str(ctx.get("track_id") or "")) != (st.spec.game, st.spec.track_id):
            return None
        start = st.spec.context
        if start is not None and not comparable(start, ctx)[0]:
            return None  # other conditions (car, wet/dry, assists): the lap pipeline's own choice; after_lap stops it
        return FrozenRef(st.spec.ref_lap_id, dict(st.spec.ref_desc or {}), st.spec.clamp)

    def on_context(self, session_id: str) -> None:
        """The live session's context or the seat changed (``LapProcessor.refresh_bests``, analysis thread): resolve
        and publish the chosen reference before the session's first lap (see the module docstring), then the
        choice."""
        try:
            self._early_reference(session_id)
        except Exception:
            log.exception("coachref: early reference failed")
        self._publish()

    def _early_reference(self, session_id: str) -> None:
        """The seated driver's own live driving with a complete context (game, track, layout, car) and no lap of the
        session in yet: publish the chosen reference now (the lap pipeline owns it from the first lap)."""
        proc, driver, info = self.processor, self.drivers.active_id, self.live.session
        if proc is None or driver is None or info is None or self.live.session_id != session_id:
            return
        if not info.track_id or not info.car_id or not info.track_length_m or info.track_length_m <= 0:
            return
        if proc.has_lap(session_id) or self._live_session_of(driver) is None:
            return
        proc.refresh_reference(session_id, load_model=True)

    def on_driver(self, driver: Driver | None) -> None:
        """The seated driver changed or edited their profile (``DriverService`` listener, API thread): a different
        driver stops the active drill (``driver_changed``); the change runs on the analysis thread."""
        new = None if driver is None else driver.id

        def task() -> None:
            for owner in [o for o in self._drills if o != new]:
                self._stop(owner, "driver_changed")  # its result waits for that driver (``_ended``)
            self._publish()

        try:
            self._run_task(task)
        except Exception:
            log.exception("coachref: driver change not applied")

    def after_lap(
        self,
        job: LapJob,
        lap_id: int,
        model: TrackModel | None,
        cur: LapAnalysis | None,
        comp: LapComparison | None,
    ) -> dict[str, Any] | None:
        """Evaluate an active drill with a stored lap (every lap, whatever the pipeline did with it). Returns
        ``{"active": True, "corner", "point"}`` while the lap belongs to a drill (``point`` None when the lap is no
        attempt), else None."""
        if not self._drills:
            return None
        with self.db.read() as c:
            owner = repo.session_driver_id(c, job.session_id)
        st = self._drills.get(owner) if owner is not None else None
        if st is None or owner is None:
            return None
        spec = st.spec
        now = self._clock()
        if now - st.last_activity_unix > dr.DRILL_TIMEOUT_S:
            self._stop(owner, "timed_out")
            return None
        ctx = job.context
        car = ctx.get("car_id")
        if (
            (ctx.get("game"), ctx.get("track_id")) != (spec.game, spec.track_id)
            or (car is not None and spec.car_id is not None and car != spec.car_id)
            or not lengths_compatible(ctx.get("track_length_m"), spec.track_length_m)
            or (spec.context is not None and _block_code(spec.context, ctx) is not None)  # wet/dry, assists
        ):
            self._stop(owner, "context_changed")
            return None
        if model is not None and (
            (spec.track_model_version is not None and model.version != spec.track_model_version)
            or model.corner(spec.corner) is None
        ):
            self._stop(owner, "model_changed")
            return None
        lap = job.lap
        busy = {"active": True, "corner": spec.corner, "point": None}
        if (
            model is None
            or not dr.is_attempt_lap(spec, job.session_id, lap.lap_number, lap.flags)
            or self._safety_car(job.session_id)
        ):
            return busy
        an = cur if cur is not None else analyse_lap(lap, model)
        m: CornerMetrics | None = an.corners.get(spec.corner)
        cd = None
        if comp is not None and comp.compatibility.ok:
            cd = next((x for x in comp.corners if x.corner == spec.corner), None)
        attempt = dr.evaluate_attempt(st, m, cd, lap_id=lap_id, lap_number=lap.lap_number)
        st = st.with_attempt(attempt, now)
        done = st.status != "active"
        fields = dr.state_fields(st)
        self.writer.submit(lambda c: repo.update_drill(c, spec.id, **fields))
        if done:
            self._drills.pop(owner, None)
            self._ended[owner] = st
            if not self._drills:
                self.live.cues.set_drill_corner(None)
        else:
            self._drills[owner] = st
        self._publish()
        return {"active": True, "corner": spec.corner, "point": dr.drill_point(st, attempt)}

    # ------------------------------------------------------------------ drill internals (analysis thread)
    def _active(self, driver_id: int) -> dr.DrillState | None:
        st = self._drills.get(driver_id)
        if st is not None and self._clock() - st.last_activity_unix > dr.DRILL_TIMEOUT_S:
            self._stop(driver_id, "timed_out")
            return None
        return st

    def _stop(self, driver_id: int, reason: str) -> dr.DrillState | None:
        st = self._drills.pop(driver_id, None)
        if st is None:
            return None
        st = st.stopped(reason, self._clock())
        fields = dr.state_fields(st)
        drill_id = st.spec.id
        self.writer.submit(lambda c: repo.update_drill(c, drill_id, **fields))
        if st.attempts:
            self._ended[driver_id] = st
        else:
            self._ended.pop(driver_id, None)
        if not self._drills:
            self.live.cues.set_drill_corner(None)
        self._publish()
        return st

    def _safety_car(self, session_id: str) -> bool:
        """A safety car (or VSC, formation lap) is out in the live session ``session_id`` at the lap's end: the lap
        says nothing about the driver's braking or speed there."""
        info = self.live.session if self.live.session_id == session_id else None
        sc = info.safety_car_status if info is not None else None
        return sc is not None and sc not in _NO_SAFETY_CAR

    def _drill_env(self) -> _DrillEnv | str:
        """The live driving a drill needs (spec 3.4.2 #1-2), or the refusal sentence."""
        driver = self.drivers.active_id
        if driver is None or self.live.synthetic or repo.is_replay_source(self.live.source or ""):
            return LIVE_ONLY
        sess = self._live_session_of(driver)
        sid = self.live.session_id
        if sess is None or sid is None or self.processor is None:
            return LIVE_ONLY
        cx = self.processor.coachref_context(sid)
        ctx = cx.ctx
        model = cx.model
        if ctx is None or not ctx.get("game") or not ctx.get("track_id"):
            return LEARNING
        if (
            model is None
            or not model.corners
            or model.n_laps < TRACK_MODEL_TARGET_LAPS
            or not lengths_compatible(model.length_m, ctx.get("track_length_m"))
        ):
            return LEARNING
        return _DrillEnv(sid, driver, ctx, cx, model, corner_texts(model))

    def _corners(self, env: _DrillEnv, corner: str | None, corner_ref: str | None) -> list[str]:
        names = [c.name for c in env.model.corners]
        if corner is not None:
            return [corner] if corner in names else []
        if corner_ref is None or not corner_ref.strip():
            return []
        return resolve_corner_ref(env.model, corner_ref.strip())

    def _ref_zone(self, env: _DrillEnv, m: CornerMetrics | None) -> bool:
        """The reference has a braking zone at the corner by the cue planner's criteria."""
        ref = env.cx.ref
        if ref is None or m is None:
            return False
        b, peak = _num(m.brake_start_m), _num(m.brake_peak)
        if b is None or peak is None or peak < MIN_REF_BRAKE_PEAK:
            return False
        entry, vmin = _num(m.entry_speed_kph), _num(m.min_speed_kph)
        if entry is not None and vmin is not None and entry - vmin < MIN_REF_SPEED_DROP_KPH:
            return False
        ms = ref.lap.lap_time_ms
        lap_s = ms / 1000.0 if ms else None
        return reference_onset_ok(ref.dtrace, b, env.model.length_m, lap_s)

    def _inputs(self, env: _DrillEnv, corner: str, tolerance: float | None) -> dr.DrillInputs:
        cx = env.cx
        label = env.texts[corner].short if corner in env.texts else corner
        ref = cx.ref
        ref_m = ref.corners.get(corner) if ref is not None else None
        desc = cx.desc
        other = desc is not None and not desc.own and desc.lap_id is not None
        shares = None
        b = _num(ref_m.brake_start_m) if ref_m is not None else None
        if ref is not None and b is not None:
            for name, m in ref.corners.items():
                ob = _num(m.brake_start_m)
                if name != corner and ob is not None and abs(ob - b) < 0.05:
                    shares = env.texts[name].short if name in env.texts else name
                    break
        assist = _assists(env.ctx).get("braking")
        own_whose = "your best lap's"
        if desc is not None and not other:
            if desc.pinned:
                own_whose = "your pinned lap's"
            elif desc.kind == "lap":
                own_whose = "your saved lap's"
        return dr.DrillInputs(
            corner_label=label,
            ref=ref_m,
            ref_zone=self._ref_zone(env, ref_m),
            ref_other=other,
            ref_name=desc.ref_name if desc is not None and other else None,
            clamp_m=(cx.clamp or {}).get(corner) if other else None,
            spacing_p90_m=_spacing_p90(ref.lap) if ref is not None else None,
            own_best=cx.own.corners.get(corner) if cx.own is not None else None,
            recent=tuple(cx.recent.get(corner, ())),
            tolerance=tolerance,
            braking_assist=assist if isinstance(assist, int) and not isinstance(assist, bool) else None,
            shares_with=shares,
            own_whose=own_whose,
        )

    def _suggested(self, corner: str) -> dr.DrillKind | None:
        cur = self.live.coach.current
        by_corner = cur.get("by_corner") if isinstance(cur, Mapping) else None
        point = by_corner.get(corner) if isinstance(by_corner, Mapping) else None
        return dr.kind_for_observation(point.get("kind")) if isinstance(point, Mapping) else None

    def _running_reason(self, st: dr.DrillState, *, radio: bool = False) -> str:
        """Why another drill cannot start: "A Turn 3 drill is running: 1 of 3 done. Stop it first." (the radio says
        what to say instead)."""
        spec = st.spec
        head = f"A {spec.corner_voice} drill is running: {len(st.attempts)} of {spec.laps_target} done."
        return f"{head} Say 'stop the drill' first." if radio else f"{head} Stop it first."

    def _drill_options(self, corner: str | None, corner_ref: str | None) -> dict[str, Any]:
        ref = corner if corner is not None else (corner_ref or "")
        base: dict[str, Any] = {
            "corner": ref,
            "corner_label": ref,
            "corner_voice": ref,
            "available": False,
            "reason": None,
            "laps_choices": list(dr.LAPS_CHOICES),
            "default_laps": dr.DEFAULT_LAPS,
            "kinds": [],
        }
        env = self._drill_env()
        if isinstance(env, str):
            return {**base, "reason": env}
        corners = self._corners(env, corner, corner_ref)
        if not corners:
            return {**base, "reason": f"I can't find {ref} on this track."}
        chosen, rows = corners[0], []
        for name in corners:  # several learned parts: the first with something available
            rows = self._kind_rows(env, name)
            chosen = name
            if any(r["available"] for r in rows):
                break
        c = env.model.corner(chosen)
        assert c is not None
        reason = None
        st = self._active(env.driver_id)
        if st is not None:
            reason = self._running_reason(st)
        return {
            **base,
            "corner": chosen,
            "corner_label": env.texts[chosen].short if chosen in env.texts else chosen,
            "corner_voice": _corner_voice(c, env.texts.get(chosen)),
            "available": reason is None and any(r["available"] for r in rows),
            "reason": reason,
            "kinds": rows,
        }

    def _kind_rows(self, env: _DrillEnv, corner: str) -> list[dict[str, Any]]:
        suggested = self._suggested(corner)
        rows = []
        for kind in dr.DRILL_KINDS:
            t = dr.plan_target(kind, self._inputs(env, corner, None))
            ok = isinstance(t, dr.DrillTarget)
            rows.append(
                {
                    "kind": kind,
                    "skill_label": dr.SKILL_LABELS[kind],
                    "available": ok,
                    "reason": None if isinstance(t, dr.DrillTarget) else t.reason,
                    "target": t.target if isinstance(t, dr.DrillTarget) else None,
                    "unit": dr.UNITS[kind],
                    "tolerance": t.tolerance if isinstance(t, dr.DrillTarget) else dr.DEFAULT_TOLERANCE[kind],
                    "baseline": (
                        round(t.baseline, 2) if isinstance(t, dr.DrillTarget) and t.baseline is not None else None
                    ),
                    "target_text": t.target_text if isinstance(t, dr.DrillTarget) else None,
                    "note": t.note if isinstance(t, dr.DrillTarget) else None,
                    "tolerance_choices": list(dr.TOLERANCE_CHOICES[kind]),
                    "suggested": kind == suggested,
                }
            )
        return rows

    def _start_context(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        """The conditions a drill starts in (``DrillSpec.context``): the session's lap context plus F1's formula."""
        keys = ("game", "track_id", "track_length_m", "car_id", "weather", "assists", "formula")
        out = {k: ctx.get(k) for k in keys}
        out["assists"] = dict(_assists(ctx))
        info = self.live.session
        if out["formula"] is None and info is not None:
            out["formula"] = info.formula
        return out

    def _start_drill(self, req: DrillRequest) -> dict[str, Any]:
        env = self._drill_env()
        if isinstance(env, str):
            raise Conflict(env)
        if req.kind is not None and req.kind not in dr.DRILL_KINDS:
            raise Invalid(f"unknown drill kind {req.kind!r}")
        laps = req.laps if req.laps is not None else dr.DEFAULT_LAPS
        if not dr.MIN_LAPS <= laps <= dr.MAX_LAPS:
            raise Invalid(f"A drill runs {dr.MIN_LAPS} to {dr.MAX_LAPS} laps.")
        ref = req.corner if req.corner is not None else (req.corner_ref or "")
        corners = self._corners(env, req.corner, req.corner_ref)
        if not corners:
            raise Conflict(f"I can't find {ref} on this track.")
        running = self._active(env.driver_id)
        if running is not None:
            raise Conflict(self._running_reason(running, radio=req.source == "radio"))
        first_reason: str | None = None
        picked: tuple[str, dr.DrillTarget] | None = None
        for corner in corners:
            kinds: list[dr.DrillKind]
            if req.kind is not None:
                kinds = [req.kind]
            else:
                sug = self._suggested(corner)
                kinds = [*([sug] if sug else []), *(k for k in dr.DRILL_KINDS if k != sug)]
            for kind in kinds:
                tol = req.tolerance
                if tol is not None:
                    lo, hi = dr.TOLERANCE_RANGES[kind]
                    if not lo <= tol <= hi:
                        raise Invalid(f"tolerance for {dr.SKILL_LABELS[kind].lower()} must be {lo:g}-{hi:g}")
                t = dr.plan_target(kind, self._inputs(env, corner, tol))
                if isinstance(t, dr.DrillTarget):
                    picked = (corner, t)
                    break
                first_reason = first_reason or t.reason
            if picked is not None:
                break
        if picked is None:
            raise Conflict(first_reason or f"No drill is possible at {ref} yet.")
        corner, t = picked
        c = env.model.corner(corner)
        assert c is not None
        desc = env.cx.desc
        other = desc is not None and not desc.own and desc.lap_id is not None
        frame = self.live.frame
        start_lap = 0 if frame is None or frame.pit_status in _IN_PITS or frame.lap_number is None else frame.lap_number
        now = self._clock()
        length = _num(env.ctx.get("track_length_m"))
        car = env.ctx.get("car_id")
        spec = dr.DrillSpec(
            id=0,
            driver_id=env.driver_id,
            session_id=env.session_id,
            game=str(env.ctx["game"]),
            track_id=str(env.ctx["track_id"]),
            track_length_m=length,
            car_id=car if isinstance(car, str) else None,
            track_model_version=env.model.version,
            corner=corner,
            corner_label=env.texts[corner].short if corner in env.texts else corner,
            corner_voice=_corner_voice(c, env.texts.get(corner)),
            apex_m=c.apex_m,
            kind=t.kind,
            source=req.source if req.source in ("work_on", "manual", "radio") else "manual",
            observation_kind=req.observation_kind,
            laps_target=laps,
            target=t.target,
            tolerance=t.tolerance,
            unit=t.unit,
            baseline=t.baseline,
            started_unix=now,
            start_lap_number=start_lap,
            target_text=t.target_text,
            note=t.note,
            target_source=t.target_source,
            cap=t.cap,
            exit_guard=t.exit_guard,
            ref_lap_id=desc.lap_id if desc is not None else None,
            ref_kind=desc.kind if desc is not None and desc.lap_id is not None else None,
            ref_driver_id=desc.driver_id if desc is not None else None,
            ref_driver_name=desc.driver_name if desc is not None else None,
            ref_label=desc.labels[0] if desc is not None and desc.lap_id is not None else None,
            ref_name=desc.ref_name if other and desc is not None else None,
            ref_desc=desc.to_dict() if desc is not None and desc.lap_id is not None else None,
            clamp=dict(env.cx.clamp or {}) if other else None,
            context=self._start_context(env.ctx),
        )
        state = dr.DrillState(spec=spec, last_activity_unix=now)
        row = dr.spec_row(spec, state)
        drill_id = self.writer.call(lambda conn: repo.insert_drill(conn, row))
        spec = replace(spec, id=drill_id)
        state = replace(state, spec=spec)
        self._drills[env.driver_id] = state
        self._ended.pop(env.driver_id, None)
        self.live.cues.set_drill_corner(corner)
        self._publish()
        return dr.drill_view(state)
