"""Reference choice and practice drills API: ``/api/coachref`` (mounted by ``api.app``; rules in
``core.coachref`` and ``coach.drills``; JSON contract in the coachref design spec section 6).

Endpoints
    GET    /api/coachref/options?driver_id                 RefOptionsResponse (the Drive picker; live context)
    GET    /api/coachref/choice?driver_id&game&track_id    {all_tracks, track, effective}
    PUT    /api/coachref/choice                            ChoiceRequest -> {choice, applies}
    DELETE /api/coachref/choice?driver_id&game&track_id    204 (track row removed) / 404
    GET    /api/coachref/candidates?lap_id                 Review › Compare picker A for lap B
    GET    /api/coachref/compare?ref&lap                   /api/compare + reference descriptor, reworded texts
    GET    /api/coachref/drills/options?corner|corner_ref  DrillOptionsResponse (live context)
    POST   /api/coachref/drills                            DrillStartRequest -> 201 DrillView; 409 {detail}
    GET    /api/coachref/drills/active?driver_id           DrillView | null
    POST   /api/coachref/drills/active/stop                DrillView / 404
    GET    /api/coachref/drills?driver_id&game&track_id&car_id&limit&include_empty   DrillView[] newest first
    GET    /api/coachref/drills/{id}                       DrillView / 404

Handlers are plain ``def`` (FastAPI's thread pool): changes wait for the lap-analysis thread (at most 5 s, then
503). Errors: 404 unknown driver / lap / drill, 409 a business refusal (a plain sentence in ``detail``), 422
validation, 503 the analysis did not answer in time or the service is not running. Pydantic models live only here.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pitwall.core.coachref import ChoiceRequest, CoachRef, CoachRefError, DrillRequest

router = APIRouter(prefix="/api/coachref", tags=["coachref"])

RefKindField = Literal["own_best", "household_best", "driver_best", "lap"]
DrillKindField = Literal["brake_point", "min_speed", "exit_speed", "entry_speed"]


class ChoiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    driver_id: int | None = None
    kind: RefKindField
    target_driver_id: int | None = None
    lap_id: int | None = None
    scope: Literal["all_tracks", "track"] = "all_tracks"
    game: str | None = Field(default=None, min_length=1, max_length=64)
    track_id: str | None = Field(default=None, min_length=1, max_length=128)


class DrillBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corner: str | None = Field(default=None, min_length=1, max_length=64)
    corner_ref: str | None = Field(default=None, min_length=1, max_length=64)
    kind: DrillKindField | None = None
    laps: int | None = Field(default=None, ge=3, le=10)
    tolerance: float | None = Field(default=None, ge=1.0, le=15.0)
    source: Literal["work_on", "manual"] = "manual"
    observation_kind: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _one_corner(self) -> DrillBody:
        if self.corner is None and self.corner_ref is None:
            raise ValueError("give corner (learned key) or corner_ref")
        return self


def _svc(request: Request) -> CoachRef:
    svc = getattr(request.app.state.runtime, "coachref", None)
    if not isinstance(svc, CoachRef):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "reference choice and drills are not running")
    return svc


def _http(e: CoachRefError) -> HTTPException:
    return HTTPException(e.status, str(e))


# ---------------------------------------------------------------------------------------------- reference choice
@router.get("/options")
def options(request: Request, driver_id: int | None = None) -> dict[str, Any]:
    try:
        return _svc(request).options(driver_id)
    except CoachRefError as e:
        raise _http(e) from e


@router.get("/choice")
def get_choice(
    request: Request, driver_id: int, game: str | None = None, track_id: str | None = None
) -> dict[str, Any]:
    try:
        return _svc(request).get_choice(driver_id, game, track_id)
    except CoachRefError as e:
        raise _http(e) from e


@router.put("/choice")
def put_choice(request: Request, body: ChoiceBody) -> dict[str, Any]:
    req = ChoiceRequest(
        kind=body.kind,
        driver_id=body.driver_id,
        target_driver_id=body.target_driver_id,
        lap_id=body.lap_id,
        scope=body.scope,
        game=body.game,
        track_id=body.track_id,
    )
    try:
        choice, applies = _svc(request).set_choice(req)
    except CoachRefError as e:
        raise _http(e) from e
    return {"choice": choice, "applies": applies}


@router.delete("/choice", status_code=status.HTTP_204_NO_CONTENT)
def delete_choice(
    request: Request,
    game: str = Query(min_length=1),
    track_id: str = Query(min_length=1),
    driver_id: int | None = None,
) -> Response:
    svc = _svc(request)
    try:
        did = driver_id if driver_id is not None else svc.drivers.active_id
        if did is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No driver in the seat.")
        gone = svc.delete_choice(did, game, track_id)
    except CoachRefError as e:
        raise _http(e) from e
    if not gone:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no choice for that track")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------------------------- Review › Compare
@router.get("/candidates")
def candidates(request: Request, lap_id: int) -> dict[str, Any]:
    try:
        return _svc(request).candidates(lap_id)
    except CoachRefError as e:
        raise _http(e) from e


@router.get("/compare")
def compare(request: Request, ref: int, lap: int) -> dict[str, Any]:
    try:
        return _svc(request).compare(ref, lap)
    except CoachRefError as e:
        raise _http(e) from e


# ---------------------------------------------------------------------------------------------- drills
@router.get("/drills/options")
def drill_options(request: Request, corner: str | None = None, corner_ref: str | None = None) -> dict[str, Any]:
    if corner is None and corner_ref is None:
        raise HTTPException(422, "give corner (learned key) or corner_ref")
    try:
        return _svc(request).drill_options(corner, corner_ref)
    except CoachRefError as e:
        raise _http(e) from e


@router.post("/drills", status_code=status.HTTP_201_CREATED)
def start_drill(request: Request, body: DrillBody) -> dict[str, Any]:
    req = DrillRequest(
        corner=body.corner,
        corner_ref=body.corner_ref,
        kind=body.kind,
        laps=body.laps,
        tolerance=body.tolerance,
        source=body.source,
        observation_kind=body.observation_kind,
    )
    try:
        return _svc(request).start_drill(req)
    except CoachRefError as e:
        raise _http(e) from e


@router.get("/drills/active")
def active_drill(request: Request, driver_id: int | None = None) -> dict[str, Any] | None:
    try:
        return _svc(request).active_drill(driver_id)
    except CoachRefError as e:
        raise _http(e) from e


@router.post("/drills/active/stop")
def stop_drill(request: Request) -> dict[str, Any]:
    try:
        view = _svc(request).stop_drill()
    except CoachRefError as e:
        raise _http(e) from e
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No drill running.")
    return view


@router.get("/drills")
def list_drills(
    request: Request,
    driver_id: int | None = None,
    game: str | None = None,
    track_id: str | None = None,
    car_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    include_empty: bool = False,
) -> list[dict[str, Any]]:
    return _svc(request).drills(driver_id, game, track_id, car_id, include_empty=include_empty, limit=limit)


@router.get("/drills/{drill_id}")
def get_drill(request: Request, drill_id: int) -> dict[str, Any]:
    try:
        return _svc(request).drill(drill_id)
    except CoachRefError as e:
        raise _http(e) from e
