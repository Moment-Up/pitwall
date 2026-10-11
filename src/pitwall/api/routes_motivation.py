"""Goals, badges, streaks, the weekly digest and session recaps (lane motivation; contract in
docs/ui/design-spec.md section 13, rows M1-M5).

Endpoints
    GET    /api/drivers/{id}/goals?status=active,achieved&achieved_days=30   GoalsResponse
    POST   /api/drivers/{id}/goals                       GoalCreate -> 201 Goal; 409 {detail, code}; 422 {detail, code}
    PATCH  /api/drivers/{id}/goals/{goal_id}             {"status": "active"|"archived"} -> Goal (active from
                                                         achieved = reopen: the stored achievement is cleared)
    DELETE /api/drivers/{id}/goals/{goal_id}             {"deleted": goal_id}
    GET    /api/drivers/{id}/goals/suggestions?game&track_id&car&from_session_id   SuggestionsResponse
    GET    /api/drivers/{id}/badges?synthetic=false      BadgesResponse
    GET    /api/drivers/{id}/digest?week=YYYY-MM-DD&synthetic=false              WeeklyDigest
    GET    /api/drivers/{id}/digest.html?week&synthetic   the printable page (text/html)
    GET    /api/sessions/{sid}/recap                     SessionRecap (404 unknown)
    WS     /ws/live                                      {"type": "motivation", "data": MotivationNote} (forwarded
                                                         by app.py from ``LiveState.notify``; nothing here)

Handlers are plain ``def`` (FastAPI's thread pool), like ``routes_drivers``: writes are ``DbWriter.call`` round trips.
Reads never write. Refusals: 404 unknown driver / goal / session, 409 ``{detail, code}`` (``too_many``,
``duplicate``, ``duplicate_scope``, ``already_beaten``), 422 ``{detail, code}`` for bad values.
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from pitwall.api.routes_drivers import _analyzer
from pitwall.motivation.goals import GoalError
from pitwall.motivation.html import digest_html
from pitwall.motivation.service import MotivationNotFound, MotivationService

router = APIRouter(tags=["motivation"])
_lock = threading.Lock()


class GoalCreateBody(BaseModel):
    """Types only; values are checked by the service so every refusal says what was wrong in plain words."""

    model_config = ConfigDict(extra="forbid")
    kind: str
    target: float
    params: dict[str, Any] | None = None
    game: str | None = None
    track_id: str | None = None
    car_id: str | None = None
    car_class: str | None = None
    from_session_id: str | None = None
    source: str = "manual"
    basis: dict[str, Any] | None = None


class GoalPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


def motivation_service(request: Request) -> MotivationService:
    """One service per app, sharing the runtime's database, writer, live state and session analyzer."""
    svc = getattr(request.app.state, "motivation", None)
    if isinstance(svc, MotivationService):
        return svc
    with _lock:
        svc = getattr(request.app.state, "motivation", None)
        if not isinstance(svc, MotivationService):
            rt = request.app.state.runtime
            svc = MotivationService(
                rt.db, getattr(rt, "writer", None), analyzer=_analyzer(request), live=getattr(rt, "live", None)
            )
            request.app.state.motivation = svc
        return svc


def _refused(e: GoalError) -> JSONResponse:
    return JSONResponse({"detail": e.detail, "code": e.code}, status_code=e.status)


def _not_found(e: MotivationNotFound) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(e.args[0]) if e.args else "not found")


def _week(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise GoalError(422, "invalid_week", "week must be a date: YYYY-MM-DD") from e


# ---------------------------------------------------------------------------------------------- goals
# /goals/suggestions is declared before the /goals/{goal_id} routes.
@router.get("/api/drivers/{driver_id}/goals/suggestions", response_model=None)
def goal_suggestions(
    request: Request,
    driver_id: int,
    game: str | None = None,
    track_id: str | None = None,
    car: str | None = None,
    from_session_id: str | None = None,
) -> dict[str, Any] | JSONResponse:
    try:
        return motivation_service(request).suggestions_response(
            driver_id, game=game, track_id=track_id, car=car, from_session_id=from_session_id
        )
    except MotivationNotFound as e:
        raise _not_found(e) from e
    except GoalError as e:
        return _refused(e)


@router.get("/api/drivers/{driver_id}/goals", response_model=None)
def list_goals(
    request: Request,
    driver_id: int,
    status_: Annotated[str, Query(alias="status")] = "active,achieved",
    achieved_days: Annotated[int, Query(ge=0, le=3650)] = 30,
) -> dict[str, Any] | JSONResponse:
    statuses = tuple(s.strip() for s in status_.split(",") if s.strip())
    try:
        return motivation_service(request).goals_response(driver_id, statuses, achieved_days)
    except MotivationNotFound as e:
        raise _not_found(e) from e
    except GoalError as e:
        return _refused(e)


@router.post("/api/drivers/{driver_id}/goals", status_code=status.HTTP_201_CREATED, response_model=None)
def create_goal(request: Request, driver_id: int, body: GoalCreateBody) -> dict[str, Any] | JSONResponse:
    try:
        return motivation_service(request).create_goal(driver_id, body.model_dump())
    except MotivationNotFound as e:
        raise _not_found(e) from e
    except GoalError as e:
        return _refused(e)


@router.patch("/api/drivers/{driver_id}/goals/{goal_id}", response_model=None)
def patch_goal(request: Request, driver_id: int, goal_id: int, body: GoalPatchBody) -> dict[str, Any] | JSONResponse:
    try:
        return motivation_service(request).patch_goal(driver_id, goal_id, body.status)
    except MotivationNotFound as e:
        raise _not_found(e) from e
    except GoalError as e:
        return _refused(e)


@router.delete("/api/drivers/{driver_id}/goals/{goal_id}")
def delete_goal(request: Request, driver_id: int, goal_id: int) -> dict[str, Any]:
    try:
        return {"deleted": motivation_service(request).delete_goal(driver_id, goal_id)}
    except MotivationNotFound as e:
        raise _not_found(e) from e


# ---------------------------------------------------------------------------------------------- badges, digest
@router.get("/api/drivers/{driver_id}/badges")
def driver_badges(request: Request, driver_id: int, synthetic: bool = False) -> dict[str, Any]:
    try:
        return motivation_service(request).badges_response(driver_id, include_synthetic=synthetic)
    except MotivationNotFound as e:
        raise _not_found(e) from e


@router.get("/api/drivers/{driver_id}/digest", response_model=None)
def driver_digest(
    request: Request, driver_id: int, week: str | None = None, synthetic: bool = False
) -> dict[str, Any] | JSONResponse:
    try:
        return motivation_service(request).digest(driver_id, _week(week), include_synthetic=synthetic)
    except MotivationNotFound as e:
        raise _not_found(e) from e
    except GoalError as e:
        return _refused(e)


@router.get("/api/drivers/{driver_id}/digest.html", response_class=HTMLResponse, response_model=None)
def driver_digest_html(
    request: Request, driver_id: int, week: str | None = None, synthetic: bool = False
) -> HTMLResponse | JSONResponse:
    try:
        d = motivation_service(request).digest(driver_id, _week(week), include_synthetic=synthetic)
    except MotivationNotFound as e:
        raise _not_found(e) from e
    except GoalError as e:
        return _refused(e)
    return HTMLResponse(digest_html(d), headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------------------------- recap
@router.get("/api/sessions/{session_id}/recap")
def session_recap(request: Request, session_id: str) -> dict[str, Any]:
    out = motivation_service(request).recap(session_id)
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return out
