"""Car health and racecraft API (``pitwall.carhealth``), mounted by ``api.app`` with ``app.include_router(router)``.

``/api/health`` is the service's own health check, so these live under ``/api/car-health/`` and ``/api/racecraft/``.

Endpoints
    GET /api/car-health/live        the live ``CarHealthView`` with the thresholds table (also ``car_health`` in
                                    ``/ws/live`` snapshots, without the table, when it changed); every section
                                    ``available: false`` with the reason without a live session
    GET /api/racecraft/live         the live ``RacecraftView`` (``mode: "off"`` with the reason outside F1 races)
    GET /api/car-health/settings    the household's car health call settings (``carhealth.settings``)
    PUT /api/car-health/settings    a partial update; 400 on an unknown key or a bad value
    GET /api/car-health/stats       the live worker's counters (submitted, dropped, processed, busy time): the ingest
                                    budget check

Handlers are plain ``def`` (thread pool). Deterministic; nothing here calls an LLM, touches ingest or the database.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from pitwall.carhealth.racecraft import REASON_NOT_RACE
from pitwall.carhealth.settings import SECTION, from_stored, validate
from pitwall.carhealth.view import off_car_health, off_racecraft, with_thresholds

router = APIRouter(tags=["car-health"])

REASON_NO_LIVE = "no live session"
REASON_WAITING = "waiting for car data"


@router.get("/api/car-health/live")
def car_health_live(request: Request) -> dict[str, Any]:
    live = request.app.state.runtime.live
    sid = live.session_id
    if sid is None:
        return off_car_health(None, REASON_NO_LIVE)
    view = live.car_health
    if isinstance(view, dict) and view.get("session_id") == sid:
        return with_thresholds(view)
    return off_car_health(sid, REASON_WAITING)


@router.get("/api/racecraft/live")
def racecraft_live(request: Request) -> dict[str, Any]:
    live = request.app.state.runtime.live
    sid = live.session_id
    if sid is None:
        return off_racecraft(None, REASON_NO_LIVE)
    view = live.racecraft
    if isinstance(view, dict) and view.get("session_id") == sid:
        return view
    s = live.session
    reason = REASON_NOT_RACE if s is not None and s.game.value != "f1_25" else REASON_WAITING
    return off_racecraft(sid, reason)


@router.get("/api/car-health/settings")
def car_health_settings(request: Request) -> dict[str, Any]:
    return from_stored(request.app.state.runtime.store.get(SECTION)).to_dict()


@router.put("/api/car-health/settings")
def put_car_health_settings(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    store = request.app.state.runtime.store
    try:
        s = validate(body, from_stored(store.get(SECTION)))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    store.replace(SECTION, s.to_dict())  # the runtime's listener hands it to the worker
    return s.to_dict()


@router.get("/api/car-health/stats")
def car_health_stats(request: Request) -> dict[str, Any]:
    worker = getattr(request.app.state.runtime, "health", None)
    return {} if worker is None else dict(worker.stats())
