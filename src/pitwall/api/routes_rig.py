"""Rig setup API: ``/api/rig`` (mounted by ``api.app`` with ``app.include_router(router)``).

Endpoints
    GET  /api/rig/catalog                         games, platforms, hardware, styles, presets (filterable on
                                                  applies_to platforms/torque), owner BRF reports, rules, issues
    GET  /api/rig/profile                         the rig profile (defaults when never saved)
    PUT  /api/rig/profile                         partial update: platform, wheel_base, torque_nm, pedals, rim
    POST /api/rig/upgrades                        {change, fitted?, date?, note?} -> record + apply an upgrade (409
                                                  when a Boost Kit / Load Cell Kit change would not change the rig)
    GET  /api/rig/drivers/{driver_id}/prefs       a driver's style + strength scale
    PUT  /api/rig/drivers/{driver_id}/prefs       {style?, strength_scale?} partial: omitted fields keep their value,
                                                  strength_scale null returns to the skill default
    GET  /api/rig/recommendations?game=&platform=&driver_id=&style=&skill_level=&strength_scale=
                                                  ordered settings with provenance + what the next upgrades change
    GET  /api/rig/check?session_id=&driver_id=&game=&laps=clean|usable&rotation_deg=&baseline=none|upgrade
                                                  telemetry rig check of one session (default: the latest real
                                                  session with laps of a game the check covers, or of ``game``; a
                                                  synthetic one only when no real one exists).
                                                  The pedals fitted at the session start come from the upgrade
                                                  history (load-cell-only checks)

Storage: the profile and per-driver preferences live in the ``SettingsStore`` section ``"rig"``
(``app.state.runtime.store``); this module owns and validates that section. Driver names and skill levels are
read from the drivers table with the existing ``repo.get_driver`` (read-only). Recommendations and rig checks are
deterministic (``pitwall.rig``); nothing here calls an LLM.

Handlers are plain ``def``: FastAPI runs them in its thread pool, so loading lap traces for a rig check never
blocks the event loop that serves the live WebSocket. Validation errors map to 422, unknown drivers/sessions to
404, and combinations the catalogue does not cover (e.g. GT7 on PC) to 422 with the reason.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Collection
from dataclasses import replace
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from pitwall.rig.catalog import Catalog, StyleId, load_catalog
from pitwall.rig.recommend import (
    SKILL_LEVELS,
    UPGRADE_CHANGES,
    DriverRigPrefs,
    RecommendationUnavailable,
    RigProfile,
    RigValidationError,
    SkillLevel,
    UpgradeChange,
    UpgradeEvent,
    effective_strength_scale,
    parse_pedals,
    parse_platform,
    parse_rim,
    parse_skill,
    parse_strength_scale,
    parse_torque,
    parse_wheel_base,
    recommend,
    upcoming_upgrades,
)
from pitwall.rig.rig_check import MIN_LAP_SAMPLES, check_session, compare_reports
from pitwall.settings_store import SettingsStore
from pitwall.storage import repo

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rig", tags=["rig"])
SECTION = "rig"
_write_lock = threading.Lock()  # read-modify-write of the section (two iPads saving at once)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: str | None = None
    wheel_base: str | None = None
    torque_nm: int | None = None
    pedals: str | None = None
    rim: str | None = None


class PrefsUpdate(BaseModel):
    """Partial update: a field that is not sent keeps its saved value (``model_fields_set``), so a style tap can
    never overwrite the force scale with a stale value from the UI, or the other way round."""

    model_config = ConfigDict(extra="forbid")
    style: StyleId | None = None
    strength_scale: float | None = Field(default=None, ge=0.2, le=1.0)


class UpgradeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change: UpgradeChange
    fitted: bool = True
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: str | None = Field(default=None, max_length=200)


# ---------------------------------------------------------------------------------------------- helpers
def _store(request: Request) -> SettingsStore:
    store = getattr(request.app.state.runtime, "store", None)
    if not isinstance(store, SettingsStore):
        raise HTTPException(503, "settings store unavailable")
    return store


def load_profile(store: SettingsStore, catalog: Catalog | None = None) -> RigProfile:
    return RigProfile.from_stored(store.get(SECTION), catalog)


def save_profile(store: SettingsStore, profile: RigProfile) -> RigProfile:
    store.replace(SECTION, {"schema": 1, **profile.to_dict(), "updated_unix": time.time()})
    return profile


def _profile_body(profile: RigProfile, cat: Catalog) -> dict[str, Any]:
    wb = cat.wheel_bases.get(profile.wheel_base)
    last = profile.last_hardware_upgrade()
    return {
        **profile.to_dict(),
        "labels": {
            "platform": cat.platforms[profile.platform].name,
            "wheel_base": wb.name if wb else profile.wheel_base,
            "torque": cat.torque_labels.get(profile.torque_nm, f"{profile.torque_nm} Nm"),
            "pedals": cat.pedal_models[cat.pedals[profile.pedals]].name,
            "rim": cat.rims[profile.rim].name if profile.rim in cat.rims else profile.rim,
        },
        "boost_kit_fitted": profile.torque_nm == 8,
        "load_cell_fitted": profile.pedals == "csl_load_cell",
        "last_hardware_upgrade": last.to_dict() if last else None,
    }


def _http(e: Exception) -> HTTPException:
    return HTTPException(422, str(e))


def _driver(request: Request, driver_id: int | None) -> dict[str, Any] | None:
    """The driver row (name, skill) via the read-only repository; None when no driver was named. 404 if unknown.

    Tolerates a database without a drivers table (older schema) by treating the driver as unknown-but-allowed."""
    if driver_id is None:
        return None
    try:
        with request.app.state.runtime.db.read() as c:
            row = repo.get_driver(c, driver_id)
    except sqlite3.OperationalError:
        log.warning("drivers table unavailable; driver %s not verified", driver_id)
        return {"id": driver_id, "name": None, "preferences": {}}
    if row is None:
        raise HTTPException(404, f"unknown driver {driver_id}")
    return row


def _skill_of(row: dict[str, Any] | None) -> SkillLevel | None:
    prefs = (row or {}).get("preferences") or {}
    try:
        return parse_skill(prefs.get("skill_level"))
    except RigValidationError:
        return None


# ---------------------------------------------------------------------------------------------- catalogue
@router.get("/catalog")
def get_catalog(
    game: str | None = None,
    platform: str | None = None,
    torque_nm: int | None = None,
    pedals: str | None = None,
    style: str | None = None,
    include_stale: bool = True,
) -> dict[str, Any]:
    cat = load_catalog()
    presets = cat.presets_for(
        game=game,
        platform=platform,
        torque_nm=torque_nm,
        pedals=pedals,
        preference=style,
        include_stale=include_stale,
    )
    return {
        **cat.summary(),
        "skill_levels": list(SKILL_LEVELS),
        "upgrade_changes": list(UPGRADE_CHANGES),
        "supported": [{"game": g, "platform": p} for g, p in sorted(cat.supported)],
        "presets": [p.summary() for p in presets],
        "pedal_reports": [r.to_dict() for r in cat.pedal_reports.values()],
        "known_issues": [i.to_dict() for i in cat.known_issues],
        "open_questions": [q.to_dict() for q in cat.open_questions],
    }


# ---------------------------------------------------------------------------------------------- profile
@router.get("/profile")
def get_profile(request: Request) -> dict[str, Any]:
    cat = load_catalog()
    return _profile_body(load_profile(_store(request), cat), cat)


@router.put("/profile")
def put_profile(request: Request, body: ProfileUpdate) -> dict[str, Any]:
    cat = load_catalog()
    store = _store(request)
    with _write_lock:
        p = load_profile(store, cat)
        try:
            platform = parse_platform(body.platform, cat) if body.platform is not None else p.platform
            wheel_base = parse_wheel_base(body.wheel_base, cat) if body.wheel_base is not None else p.wheel_base
            torque = body.torque_nm if body.torque_nm is not None else p.torque_nm
            torque = parse_torque(torque, cat, wheel_base)
            pedals = parse_pedals(body.pedals) if body.pedals is not None else p.pedals
            rim = parse_rim(body.rim, cat) if body.rim is not None else p.rim
        except RigValidationError as e:
            raise _http(e) from e
        p = RigProfile(platform, wheel_base, torque, pedals, rim, p.upgrades, p.drivers)
        save_profile(store, p)
    return _profile_body(p, cat)


@router.post("/upgrades", status_code=201)
def post_upgrade(request: Request, body: UpgradeIn) -> dict[str, Any]:
    """Record a hardware change (Boost Kit fitted, Load Cell Kit fitted, firmware...) and apply its effect. The
    history lets the rig check compare sessions before and after (``/check?baseline=upgrade``).

    A Boost Kit or Load Cell Kit event that would not change the rig (fitting a kit that is already fitted,
    removing one that is not) is refused with 409: ``hardware_at`` replays the history backwards, so a no-op event
    would make every earlier session look as if it had the other hardware."""
    cat = load_catalog()
    store = _store(request)
    event = UpgradeEvent(
        date=body.date or time.strftime("%Y-%m-%d"),
        change=body.change,
        fitted=body.fitted,
        note=body.note,
        recorded_unix=time.time(),
    )
    with _write_lock:
        current = load_profile(store, cat)
        fitted_now = {"boost_kit_180": current.torque_nm == 8, "load_cell_kit": current.pedals == "csl_load_cell"}
        if body.change in fitted_now and fitted_now[body.change] == body.fitted:
            state = "fitted" if body.fitted else "not fitted"
            raise HTTPException(409, f"{body.change} is already {state}: nothing to record")
        p = current.with_upgrade(event)
        save_profile(store, p)
    return _profile_body(p, cat)


# ---------------------------------------------------------------------------------------------- driver prefs
@router.get("/drivers/{driver_id}/prefs")
def get_prefs(request: Request, driver_id: int) -> dict[str, Any]:
    """The saved prefs and the effective scale on the reference (5 Nm) base. On a stronger base a skill default is
    lower and depends on the game's table (``weight_factor``): ``strength_scale`` in ``/recommendations`` is the
    value actually applied."""
    cat = load_catalog()
    row = _driver(request, driver_id)
    prefs = load_profile(_store(request), cat).prefs_for(driver_id)
    skill = _skill_of(row) or "intermediate"
    scale, source = effective_strength_scale(skill, prefs.strength_scale, cat)
    return {
        "driver_id": driver_id,
        "prefs": prefs.to_dict(),
        "skill_level": skill,
        "effective_strength_scale": scale,
        "strength_scale_source": source,
    }


@router.put("/drivers/{driver_id}/prefs")
def put_prefs(request: Request, driver_id: int, body: PrefsUpdate) -> dict[str, Any]:
    """Merge the sent fields into the driver's saved preferences (see ``PrefsUpdate``)."""
    cat = load_catalog()
    _driver(request, driver_id)
    sent = body.model_fields_set
    if "style" in sent and body.style is None:
        raise HTTPException(422, "style cannot be null")
    try:
        scale = parse_strength_scale(body.strength_scale, cat) if "strength_scale" in sent else None
    except RigValidationError as e:
        raise _http(e) from e
    store = _store(request)
    with _write_lock:
        profile = load_profile(store, cat)
        current = profile.prefs_for(driver_id)
        prefs = DriverRigPrefs(
            style=body.style if body.style is not None else current.style,
            strength_scale=scale if "strength_scale" in sent else current.strength_scale,
        )
        save_profile(store, profile.with_prefs(driver_id, prefs))
    return get_prefs(request, driver_id)


# ---------------------------------------------------------------------------------------------- recommendations
@router.get("/recommendations")
def get_recommendations(
    request: Request,
    game: Annotated[str, Query()] = "f1_25",
    platform: str | None = None,
    driver_id: int | None = None,
    style: str | None = None,
    skill_level: str | None = None,
    strength_scale: Annotated[float | None, Query(ge=0.2, le=1.0)] = None,
) -> dict[str, Any]:
    """Settings for the saved rig (``platform`` may override it). The driver's saved style, strength scale and
    skill level apply unless given explicitly."""
    cat = load_catalog()
    profile = load_profile(_store(request), cat)
    row = _driver(request, driver_id)
    prefs = profile.prefs_for(driver_id)
    try:
        hw = profile.hardware
        if platform is not None:
            hw = replace(hw, platform=parse_platform(platform, cat))
        skill: SkillLevel
        if skill_level is not None:
            skill, skill_source = parse_skill(skill_level), "request"
        elif (stored := _skill_of(row)) is not None:
            skill, skill_source = stored, "driver"
        else:
            skill, skill_source = "intermediate", "default"
        chosen_style = style or prefs.style
        scale = strength_scale if strength_scale is not None else prefs.strength_scale
        name = (row or {}).get("name")
        rec = recommend(game, hw, chosen_style, skill, scale, name, cat)
        upcoming = upcoming_upgrades(game, hw, chosen_style, skill, scale, name, cat)
    except (RigValidationError, RecommendationUnavailable) as e:
        raise _http(e) from e
    return {
        **rec.to_dict(),
        "driver": None
        if row is None
        else {"id": driver_id, "name": name, "skill_level": skill, "skill_source": skill_source},
        "upcoming": [u.to_dict() for u in upcoming],
    }


# ---------------------------------------------------------------------------------------------- rig check
def _latest_session_with_laps(
    conn: Any,
    driver_id: int | None,
    game: str | Collection[str] | None = None,
    before_unix: float | None = None,
    synthetic: bool | None = None,
) -> dict[str, Any] | None:
    """The most recent session with at least one lap long enough for the check, of ``game`` (one id or a set).
    ``synthetic`` (when not None) must match: a generated session says nothing about the rig and is never compared
    with a real one. ``driver_id`` None means any driver."""
    games = {game} if isinstance(game, str) else (set(game) if game is not None else None)
    for s in repo.list_sessions(conn, 200, driver_id=driver_id):
        if not s.get("lap_count"):
            continue
        if games is not None and s.get("game") not in games:
            continue
        if synthetic is not None and bool(s.get("synthetic")) != synthetic:
            continue
        if before_unix is not None and float(s.get("started_unix") or 0.0) >= before_unix:
            continue
        laps = repo.list_laps(conn, s["id"])
        if any(int(lap.get("n_samples") or 0) >= MIN_LAP_SAMPLES for lap in laps):
            return s
    return None


@router.get("/check")
def get_check(
    request: Request,
    session_id: str | None = None,
    driver_id: int | None = None,
    game: str | None = None,
    laps: Literal["clean", "usable"] = "clean",
    rotation_deg: Annotated[float | None, Query(ge=90, le=2520)] = None,
    baseline: Literal["none", "upgrade"] = "none",
) -> dict[str, Any]:
    """Rig check of ``session_id``, or of the latest real session with laps (of ``driver_id`` and ``game`` when
    given; otherwise of any game the rig check covers, so an Assetto Corsa session never hides the latest F1 25 or
    GT7 one; a synthetic session only when no real one exists, and the report says it is synthetic).

    ``rotation_deg`` is F1's Maximum Wheel Rotation (default 360), or for GT7 the car's lock-to-lock rotation (GT7's
    steering is on a nominal 900 deg scale and its AUTO lock is not in telemetry, so lock-based metrics stay unknown
    without it). The pedals fitted when the session started are taken from the recorded upgrade history.

    ``baseline=upgrade`` also checks the latest session of the same game, driver and evidence tier (real vs
    synthetic) recorded before the most recent hardware upgrade (Boost Kit / Load Cell Kit) and returns the
    per-metric change. When the checked session itself predates the upgrade there is nothing "after" yet, and a
    session with no driver has no baseline (another driver's session must never be the "before"): ``baseline_note``
    says so instead."""
    cat = load_catalog()
    if driver_id is not None:
        _driver(request, driver_id)
    checkable = sorted({g for spec in cat.rig_check.values() for g in spec.games})
    if game is not None and game not in checkable:
        raise HTTPException(422, f"the rig check covers {checkable}, not {game!r}")
    games: str | list[str] = game if game is not None else checkable
    db = request.app.state.runtime.db
    profile = load_profile(_store(request), cat)

    def pedals_at(session: dict[str, Any] | None) -> str | None:
        return profile.hardware_at((session or {}).get("started_unix")).pedals if session else None

    with db.read() as c:
        if session_id is None:
            s = _latest_session_with_laps(c, driver_id, games, synthetic=False) or _latest_session_with_laps(
                c, driver_id, games, synthetic=True
            )
            if s is None:
                raise HTTPException(404, "no session with laps recorded yet")
            session_id = str(s["id"])
        else:
            s = repo.get_session(c, session_id)
        report = check_session(c, session_id, laps, rotation_deg, cat, pedals=pedals_at(s))
        if report is None:
            raise HTTPException(404, "session not found")
        body: dict[str, Any] = {
            **report.to_dict(),
            "baseline": None,
            "comparison": None,
            "upgrade": None,
            "baseline_note": None,
        }
        if baseline == "upgrade":
            ev = profile.last_hardware_upgrade()
            body["upgrade"] = ev.to_dict() if ev else None
            if ev is not None:
                cutoff = ev.recorded_unix or time.mktime(time.strptime(ev.date, "%Y-%m-%d"))
                if report.started_unix is None or report.started_unix < cutoff:
                    body["baseline_note"] = (
                        "No session recorded since this upgrade yet: drive a few laps, then compare."
                    )
                    return body
                owner = driver_id if driver_id is not None else (repo.get_session(c, session_id) or {}).get("driver_id")
                if owner is None:
                    body["baseline_note"] = (
                        "This session has no driver, so there is no baseline: pick the driver to compare with their "
                        "sessions from before the upgrade."
                    )
                    return body
                prior = _latest_session_with_laps(c, owner, report.game, before_unix=cutoff, synthetic=report.synthetic)
                if prior is not None and str(prior["id"]) == session_id:
                    prior = None  # never compare a session with itself
                before = (
                    check_session(c, str(prior["id"]), laps, rotation_deg, cat, pedals=pedals_at(prior))
                    if prior is not None
                    else None
                )
                if before is None:
                    body["baseline_note"] = "No session of this game recorded before the upgrade to compare with."
                else:
                    body["baseline"] = before.to_dict()
                    body["comparison"] = [d.to_dict() for d in compare_reports(before, report)]
    return body
