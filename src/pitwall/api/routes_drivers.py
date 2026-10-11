"""Driver profile API: ``/api/drivers`` (mounted by ``api.app`` with ``app.include_router(router)``).

Endpoints
    GET    /api/drivers                            {"active_id", "radio_follows_driver", "drivers": [driver + "active"
                                                    + "stats"]}
    POST   /api/drivers                            create -> 201 driver
    GET    /api/drivers/active                     the driver in the seat (null if none)
    PUT    /api/drivers/active                     {"driver_id"} -> put that driver in the seat
    POST   /api/drivers/sessions/{sid}/assign      {"driver_id"} -> re-assign a session (forgot to switch)
    GET    /api/drivers/{id}                       driver + stats
    PATCH  /api/drivers/{id}                       partial update (name and/or preferences)
    DELETE /api/drivers/{id}?reassign_to=<id>      delete; refused (409) while they own sessions unless reassigned
    GET    /api/drivers/{id}/sessions?limit=50     that driver's sessions (same rows as /api/sessions)
    GET    /api/drivers/{id}/progress?game&track_id&car&synthetic&limit&corners
                                                   per-session progress + PB history (dashboard D5, see
                                                   ``driver_progress``)
    GET    /api/drivers/{id}/ai-pace?game&track_id&car_class&category&limit&target_gap_pct
                                                   pace vs AI difficulty over time + suggested AI level per
                                                   track / car class / category / weather (``driver_ai_pace``)

Handlers are plain ``def``: FastAPI runs them in its thread pool, so the blocking ``DbWriter.call`` round trips
never stall the event loop that also serves the live WebSocket. Service errors map to 404 (unknown driver or
session), 409 (conflicts: duplicate name, sessions still owned, last driver) and 422 (invalid values).

``radio_follows_driver`` says whether the radio applies the seated driver's coaching intensity, voice setting and
skill-level coaching limits (``DriverService.attach_radio``). The dashboard only offers those settings when it
does: a control that changes nothing would be a promise the rig does not keep.

State: ``app.state.runtime`` provides ``db``, ``writer`` and ``live``; the shared ``DriverService`` is
``runtime.drivers`` when the runtime has one (the session manager must use the same instance), otherwise one is
created on first use and kept on ``app.state.drivers``. ``app.state.analyzer`` (optional) is invalidated after
any change of session ownership or of a profile (the analysis carries the owner's name and skill level).
"""

from __future__ import annotations

import statistics
import threading
from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from pitwall.analysis import ai_level
from pitwall.analysis.ai_pace import AI_PACE_METHOD_VERSION
from pitwall.analysis.track_identity import corner_texts
from pitwall.core.session_analysis import SessionAnalysis, SessionAnalyzer
from pitwall.drivers import (
    MAX_NAME_LEN,
    DriverConflictError,
    DriverError,
    DriverService,
    DriverValidationError,
    NotFoundError,
    SkillLevel,
)
from pitwall.storage import repo

router = APIRouter(prefix="/api/drivers", tags=["drivers"])
_service_lock = threading.Lock()

PROGRESS_CORNER_SESSIONS = 30  # newest sessions given corner trends per request (a session analysis ~3 ms/lap)
AI_PACE_SUGGESTION_POINTS = 500  # a driver's newest AI pace points used for suggestions (all tracks: other slopes)
_CATEGORY = r"^(race|qualifying|practice|time_trial|unknown)$"
_COLOUR = r"^#[0-9a-fA-F]{6}$"
_INITIALS = r"^[A-Za-z0-9]{1,3}$"
Intensity = Annotated[str, Field(pattern="^(quiet|normal|detailed)$")]


class DriverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=MAX_NAME_LEN)
    colour: str | None = Field(default=None, pattern=_COLOUR)
    initials: str | None = Field(default=None, pattern=_INITIALS)
    skill_level: SkillLevel = "intermediate"
    coaching_intensity: Intensity = "normal"
    voice_enabled: bool = True
    default_game: str | None = None  # games catalogue id ("Usually plays")


class DriverUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LEN)
    colour: str | None = Field(default=None, pattern=_COLOUR)
    initials: str | None = Field(default=None, pattern=_INITIALS)
    skill_level: SkillLevel | None = None
    coaching_intensity: Intensity | None = None
    voice_enabled: bool | None = None
    default_game: str | None = None  # null clears it (only when sent: omitted leaves it unchanged)


class DriverRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    driver_id: int


# ---------------------------------------------------------------------------------------------- helpers
def driver_service(request: Request) -> DriverService:
    """The process-wide ``DriverService`` (see module docstring)."""
    rt = request.app.state.runtime
    svc = getattr(rt, "drivers", None)
    if isinstance(svc, DriverService):
        return svc
    with _service_lock:
        svc = getattr(request.app.state, "drivers", None)
        if not isinstance(svc, DriverService):
            settings = getattr(rt, "settings", None)
            svc = DriverService(rt.db, rt.writer, default_name=getattr(settings, "driver_name", None))
            request.app.state.drivers = svc
        return svc


def _invalidate_analyses(request: Request) -> None:
    analyzer = getattr(request.app.state, "analyzer", None)
    if analyzer is not None and hasattr(analyzer, "invalidate"):
        analyzer.invalidate()


def _http(e: DriverError) -> HTTPException:
    if isinstance(e, NotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    if isinstance(e, DriverConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, str(e))
    if isinstance(e, DriverValidationError):
        return HTTPException(422, str(e))  # numeric: the constant was renamed across Starlette versions
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


def _session_is_live(request: Request, session_id: str) -> bool:
    """The session is being driven now: live state shows it and it has not ended. ``LiveState`` keeps showing the
    last session after it ends, and seating its owner then would hand the rig to someone who is not driving (e.g.
    fixing the previous driver's session while the next driver is already seated)."""
    rt = request.app.state.runtime
    if getattr(getattr(rt, "live", None), "session_id", None) != session_id:
        return False
    with rt.db.read() as c:
        sess = repo.get_session(c, session_id)
    return sess is not None and sess.get("ended_unix") is None


# ---------------------------------------------------------------------------------------------- collection
@router.get("")
def list_drivers(request: Request) -> dict[str, Any]:
    svc = driver_service(request)
    return {
        "active_id": svc.active_id,
        "radio_follows_driver": svc.radio_follows_driver,
        "drivers": svc.describe_all(),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_driver(request: Request, body: DriverCreate) -> dict[str, Any]:
    svc = driver_service(request)
    try:
        driver = svc.create(
            body.name,
            colour=body.colour,
            initials=body.initials,
            skill_level=body.skill_level,
            coaching_intensity=body.coaching_intensity,
            voice_enabled=body.voice_enabled,
            default_game=body.default_game,
        )
    except DriverError as e:
        raise _http(e) from e
    return svc.describe(driver)


# ---------------------------------------------------------------------------------------------- active driver
@router.get("/active")
def get_active(request: Request) -> dict[str, Any] | None:
    svc = driver_service(request)
    active = svc.active
    return None if active is None else svc.describe(active)


@router.put("/active")
def set_active(request: Request, body: DriverRef) -> dict[str, Any]:
    svc = driver_service(request)
    try:
        driver = svc.set_active(body.driver_id)
    except DriverError as e:
        raise _http(e) from e
    return svc.describe(driver)


# ---------------------------------------------------------------------------------------------- session ownership
@router.post("/sessions/{session_id}/assign")
def assign_session(request: Request, session_id: str, body: DriverRef) -> dict[str, Any]:
    """Re-assign a session. Re-assigning the *live* session also puts that driver in the seat: whoever owns the
    session being driven is, by definition, the one driving (otherwise the session manager would split it). Both
    happen in one atomic service call: two separate calls would let the ingest thread, which handles a packet
    every few milliseconds, see the new owner with the old driver seated and hand the session straight back."""
    svc = driver_service(request)
    live = _session_is_live(request, session_id)
    try:
        result = svc.assign_session(session_id, body.driver_id, activate=live)
    except DriverError as e:
        raise _http(e) from e
    if result.changed:
        _invalidate_analyses(request)
    return {
        "session_id": session_id,
        "driver_id": body.driver_id,
        "previous_driver_id": result.previous_driver_id,
        "live": live,
        "active_changed": result.active_changed,
    }


# ---------------------------------------------------------------------------------------------- one driver
@router.get("/{driver_id}")
def get_driver(request: Request, driver_id: int) -> dict[str, Any]:
    svc = driver_service(request)
    try:
        return svc.describe(svc.get(driver_id))
    except DriverError as e:
        raise _http(e) from e


@router.patch("/{driver_id}")
def update_driver(request: Request, driver_id: int, body: DriverUpdate) -> dict[str, Any]:
    svc = driver_service(request)
    fields: dict[str, Any] = body.model_dump(exclude_none=True)
    if "default_game" in body.model_fields_set:  # an explicit null clears the usual game
        fields["default_game"] = body.default_game
    try:
        driver = svc.update(driver_id, **fields)
    except DriverError as e:
        raise _http(e) from e
    _invalidate_analyses(request)  # cached analyses carry the owner's name and skill level
    return svc.describe(driver)


@router.delete("/{driver_id}")
def delete_driver(
    request: Request, driver_id: int, reassign_to: Annotated[int | None, Query()] = None
) -> dict[str, Any]:
    svc = driver_service(request)
    try:
        moved = svc.delete(driver_id, reassign_to)
    except DriverError as e:
        raise _http(e) from e
    if moved:
        _invalidate_analyses(request)
    return {"deleted": driver_id, "reassigned_to": reassign_to, "sessions_moved": moved, "active_id": svc.active_id}


@router.get("/{driver_id}/sessions")
def driver_sessions(
    request: Request, driver_id: int, limit: Annotated[int, Query(ge=1, le=500)] = 50
) -> list[dict[str, Any]]:
    svc = driver_service(request)
    try:
        svc.get(driver_id)
    except DriverError as e:
        raise _http(e) from e
    with request.app.state.runtime.db.read() as c:
        return repo.list_sessions(c, limit, driver_id=driver_id)


# ---------------------------------------------------------------------------------------------- progress (D5)
def _analyzer(request: Request) -> SessionAnalyzer:
    """The app's shared ``SessionAnalyzer`` (cached analyses, invalidated on ownership changes); one is created
    on first use when the app has none."""
    analyzer = getattr(request.app.state, "analyzer", None)
    if isinstance(analyzer, SessionAnalyzer):
        return analyzer
    with _service_lock:
        analyzer = getattr(request.app.state, "analyzer", None)
        if not isinstance(analyzer, SessionAnalyzer):
            analyzer = SessionAnalyzer(request.app.state.runtime.db)
            request.app.state.analyzer = analyzer
        return analyzer


def lap_stats(clean_ms: list[int]) -> dict[str, int | None]:
    """Best, median (rounded to the ms) and spread (slowest - fastest) of a session's clean laps; the spread
    needs two clean laps. Unknown is None, never 0."""
    if not clean_ms:
        return {"best_clean_ms": None, "median_clean_ms": None, "spread_ms": None}
    return {
        "best_clean_ms": min(clean_ms),
        "median_clean_ms": round(statistics.median(clean_ms)),
        "spread_ms": max(clean_ms) - min(clean_ms) if len(clean_ms) >= 2 else None,
    }


def corner_trends(sa: SessionAnalysis | None) -> tuple[dict[str, float] | None, dict[str, int] | None]:
    """``(corners, habits)`` of a session analysis: mean time lost per corner against the driver's reference
    (``corner_summary``, incidents excluded) and how often each corrective rule fired over the session's laps.
    ``(None, None)`` when the session could not be compared (no track model or no reference lap)."""
    if sa is None or sa.ref_lap_id is None or not sa.comparisons:
        return None, None
    corners = {c.corner: c.mean_time_delta_s for c in sa.corner_summary if c.mean_time_delta_s is not None}
    habits = Counter(
        str(o.get("kind"))
        for obs in sa.observations.values()
        for o in obs
        if not o.get("positive") and o.get("kind") != "incident"
    )
    return corners, dict(sorted(habits.items()))


@router.get("/{driver_id}/progress")
def driver_progress(
    request: Request,
    driver_id: int,
    game: str | None = None,
    track_id: str | None = None,
    car: str | None = None,
    synthetic: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    corners: bool = True,
) -> dict[str, Any]:
    """Is this driver getting better? (design spec 6.8 / 6.9, D5). The driver's own driving only (never replays;
    synthetic sessions only with ``synthetic=true``, each row flagged), optionally one ``game`` / ``track_id`` /
    ``car`` (car id).

    ``sessions``: the newest ``limit``, oldest first: ``{session_id, started_unix, game, track_id, track_name,
    car_id, car_name, session_type, synthetic, laps, clean_laps, best_clean_ms, median_clean_ms, spread_ms,
    ref_lap_id, corners: {corner: mean_time_delta_s}, habits: {kind: count}}``. ``corners`` / ``habits`` come
    from the session analysis against the driver's current reference at that track (their pinned lap, else their
    fastest clean lap in that car), so sessions are compared with the same lap; they are null when the session
    could not be compared, with ``corners=false``, and for sessions older than the newest
    ``PROGRESS_CORNER_SESSIONS``. Corner keys are learned names; ``corner_text["<game>/<track_id>"]`` gives their
    official labels. ``pb_history``: each lap that beat the driver's previous best for its game + track + car.
    """
    svc = driver_service(request)
    try:
        svc.get(driver_id)
    except DriverError as e:
        raise _http(e) from e
    with request.app.state.runtime.db.read() as c:
        rows = repo.driver_progress_sessions(
            c, driver_id, game, track_id, car, include_synthetic=synthetic, limit=limit
        )
        history = repo.pb_history(c, driver_id, game, track_id, car, include_synthetic=synthetic)
    analyse = set() if not corners else {r["session_id"] for r in rows[-PROGRESS_CORNER_SESSIONS:]}
    analyzer = _analyzer(request) if analyse else None
    texts: dict[str, dict[str, dict[str, str]]] = {}
    sessions: list[dict[str, Any]] = []
    for r in rows:
        clean_ms = r.pop("clean_lap_ms")
        sa = analyzer.analyse(r["session_id"]) if analyzer is not None and r["session_id"] in analyse else None
        corner_map, habits = corner_trends(sa)
        if sa is not None and sa.model is not None and corner_map is not None:
            texts[f"{r['game']}/{r['track_id']}"] = {
                k: {"short": t.short, "long": t.long} for k, t in corner_texts(sa.model).items()
            }
        sessions.append(
            {
                **r,
                "clean_laps": len(clean_ms),
                **lap_stats(clean_ms),
                "ref_lap_id": None if sa is None else sa.ref_lap_id,
                "corners": corner_map,
                "habits": habits,
            }
        )
    return {
        "driver_id": driver_id,
        "scope": {"game": game, "track_id": track_id, "car_id": car},
        "include_synthetic": synthetic,
        "sessions": sessions,
        "corner_text": texts,
        "pb_history": history,
    }


# ---------------------------------------------------------------------------------------------- pace vs AI
@router.get("/{driver_id}/ai-pace")
def driver_ai_pace(
    request: Request,
    driver_id: int,
    game: str | None = None,
    track_id: str | None = None,
    car_class: str | None = None,
    category: Annotated[str | None, Query(pattern=_CATEGORY)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    target_gap_pct: Annotated[float, Query(ge=ai_level.TARGET_GAP_MIN, le=ai_level.TARGET_GAP_MAX)] = 0.0,
) -> dict[str, Any]:
    """Pace vs AI difficulty over time (``DriverAiPace``). ``points``: one per session of the driver's own real
    driving (never synthetic, never replays) whose AI metrics are known, oldest first, within the optional scope.
    ``suggestions``: the suggested AI level per (game, track, car class, category, weather) present in ``points``,
    newest first, computed from all of the driver's points (so slopes measured at other tracks are available);
    ``target_gap_pct`` (-5..5) is the wanted gap to the typical AI car (positive: the AI slightly faster)."""
    svc = driver_service(request)
    try:
        svc.get(driver_id)
    except DriverError as e:
        raise _http(e) from e
    with request.app.state.runtime.db.read() as c:
        points = repo.driver_ai_pace_points(
            c, driver_id, game=game, track_id=track_id, car_class=car_class, category=category, limit=limit
        )
        every = repo.driver_ai_pace_points(c, driver_id, limit=AI_PACE_SUGGESTION_POINTS)
    return {
        "driver_id": driver_id,
        "method_version": AI_PACE_METHOD_VERSION,
        "target_gap_pct": target_gap_pct,
        "scope": {"game": game, "track_id": track_id, "car_class": car_class, "category": category},
        "points": points,
        "suggestions": ai_level.suggestions(every, points, target_gap_pct=target_gap_pct),
    }
