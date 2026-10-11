"""Technique API: ``/api/technique`` (mounted by ``api.app`` with ``app.include_router(router)``).

Endpoints
    GET /api/technique/sessions/{sid}?ref_lap_id=&car_format=
                                                    racing line, brake/throttle technique and handling balance per
                                                    corner and lap, handling symptoms, setup suggestions (F1 25)
                                                    and the thresholds used (``TechniqueSession``)
    GET /api/technique/sessions/{sid}/balance?car_format=
                                                    symptoms, setup suggestions, availability and assists only
    (``car_format`` = f1_2025 | f1_2026: the driver's choice when a generic car cannot be told apart, as in
    ``/api/carsetup/sessions``; an invalid value is 422)
    GET /api/technique/compare?ref=&lap=            one lap against a reference lap: both lines, the biggest line
                                                    differences, and per-corner inputs, notes and balance

Everything is deterministic (``pitwall.technique``); nothing here calls an LLM, nothing is stored. The analyzer is
created on first use from the app's database, ``SessionAnalyzer`` and the rig profile in the settings store, so the
app's lifespan is untouched. Work runs in a thread. Errors: unknown session, lap or reference lap 404; no track model
for the track yet 409; a ``ref_lap_id`` from another game, track or layout 422. Numbers are rounded (m 0.01,
deg 0.1, s 0.01, fractions 0.01) and non-finite values are ``null``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import orjson
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from pitwall.carsetup.catalog import CarFormat
from pitwall.carsetup.recommend import SetupRequestError, parse_car_format
from pitwall.technique.session import NoTrackModel, TechniqueAnalyzer, TechniqueBadReference, TechniqueNotFound

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/technique", tags=["technique"])


class _Json(JSONResponse):
    """orjson with NaN -> null (the payloads are rounded already; this is the safety net)."""

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS)


def _rig_profile(state: Any) -> Any:
    """The stored rig profile (read on every analysis: an upgrade recorded in Setup › Rig applies at once), or None
    when there is no settings store."""
    store = getattr(getattr(state, "runtime", None), "store", None)
    if store is None:
        return None
    try:
        from pitwall.rig.recommend import RigProfile

        return RigProfile.from_stored(store.get("rig"))
    except Exception:  # a broken rig catalogue must not take technique down: pedals become unknown
        log.exception("rig profile unavailable for technique analysis")
        return None


def analyzer(request: Request) -> TechniqueAnalyzer:
    state = request.app.state
    ta = getattr(state, "technique", None)
    if ta is None:
        runtime = getattr(state, "runtime", None)
        sessions = getattr(state, "analyzer", None)
        if runtime is None or sessions is None:
            raise HTTPException(503, "analysis is not available")
        ta = TechniqueAnalyzer(runtime.db, sessions, lambda: _rig_profile(state))
        state.technique = ta
    return ta


async def _run(fn: Any, *args: Any) -> _Json:
    try:
        return _Json(await asyncio.to_thread(fn, *args))
    except TechniqueNotFound as e:
        raise HTTPException(404, str(e)) from e
    except NoTrackModel as e:
        raise HTTPException(409, str(e)) from e
    except TechniqueBadReference as e:
        raise HTTPException(422, str(e)) from e


def _car_format(raw: str | None) -> CarFormat | None:
    if raw is None or raw == "":
        return None
    try:
        return parse_car_format(raw)
    except SetupRequestError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/sessions/{sid}")
async def technique_session(
    request: Request, sid: str, ref_lap_id: int | None = None, car_format: str | None = None
) -> _Json:
    return await _run(analyzer(request).session_payload, sid, ref_lap_id, _car_format(car_format))


@router.get("/sessions/{sid}/balance")
async def technique_balance(request: Request, sid: str, car_format: str | None = None) -> _Json:
    return await _run(analyzer(request).balance_payload, sid, _car_format(car_format))


@router.get("/compare")
async def technique_compare(request: Request, ref: int, lap: int) -> _Json:
    return await _run(analyzer(request).compare, ref, lap)
