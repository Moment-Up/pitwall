"""Spotter API: ``/api/spotter`` (mounted by ``api.app`` with ``app.include_router(router)``; same auth as every
``/api/`` route). Contract: spec section 8, docs/features.md "Spotter (F1 25)".

Endpoints
    GET  /api/spotter            settings, availability, status (rate, car size, audio, the wording in effect),
                                 latency, counters, recent
    PUT  /api/spotter/settings   partial body: validated (422 on an unknown key or a bad value), persisted in the
                                 ``SettingsStore`` section "spotter", applied at once; returns the GET payload
    POST /api/spotter/test       "Car left", then "Clear left" 1.2 s later (in the wording in use: ``says``), through
                                 the real spotter radio path (``meta.test``); 409 when the radio is off (voice
                                 disabled, or no radio connected)

Everything here is deterministic; nothing calls an LLM.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from pitwall import games
from pitwall.spotter.phrases import phrase_text
from pitwall.spotter.settings import SECTION, merge, parse_stored

router = APIRouter(prefix="/api/spotter", tags=["spotter"])
_write_lock = threading.Lock()  # read-modify-write of the section (two iPads saving at once)
SPOTTER_GAME = "f1_25"


def _availability(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    e = games.entry(rt.live.effective_game_id())
    game = e.adapter_game if e is not None else None
    if game is not None and game != SPOTTER_GAME:
        reason: str | None = "game_not_supported"
    elif not rt.spotter.motion_seen and not (rt._replay_spotter is not None and rt._replay_spotter.motion_seen):
        reason = "no_motion"
    else:
        reason = None
    return {"available": reason != "game_not_supported", "game": game, "reason": reason}


def payload(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    hub = request.app.state.hub
    worker = rt._replay_spotter if rt._replay_spotter is not None and rt._replay_spotter.motion_seen else rt.spotter
    status = worker.status()
    radio = hub.spotter if hub is not None else None
    status["audio"] = radio.status() if radio is not None else {"ready": False, "engine": None, "reason": "voice off"}
    # what the driver hears now: "auto" follows the seated driver's profile (Settings shows it beside Auto)
    wording = rt.spotter_settings.wording
    status["wording"] = (
        ("simple" if radio.simple(wording) else "standard")
        if radio is not None
        else (wording if wording != "auto" else None)
    )
    counters = worker.counters()
    latency: dict[str, Any]
    if radio is not None:
        latency = radio.latency()
        counters["dropped"] = dict(radio.dropped)
        counters["spoken"] = dict(radio.spoken)
        recent = list(radio.recent)
    else:
        latency = {"n": 0, **worker.latency()}
        counters["dropped"] = {}
        counters["spoken"] = {}
        recent = list(worker.recent)
    return {
        "v": 1,
        "settings": rt.spotter_settings.to_dict(),
        "availability": _availability(request),
        "status": status,
        "latency": latency,
        "counters": counters,
        "recent": recent,
    }


@router.get("")
async def get_spotter(request: Request) -> dict[str, Any]:
    return payload(request)


@router.put("/settings")
async def put_settings(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    rt = request.app.state.runtime

    def save() -> None:
        with _write_lock:
            current = parse_stored(rt.store.get(SECTION))
            new = merge(current, body)  # ValueError -> 422
            rt.store.replace(SECTION, new.to_dict())  # subscribers apply it (runtime: the workers; hub: next tick)

    try:
        await asyncio.to_thread(save)  # the settings file is written with fsync: off the event loop
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return payload(request)


@router.post("/test")
async def test_spotter(request: Request) -> dict[str, Any]:
    hub = request.app.state.hub
    if hub is None or not hub.voice_enabled:
        raise HTTPException(409, "the radio is off")
    if not hub.clients:
        raise HTTPException(409, "no radio connected")
    hub.spotter.test()
    simple = hub.spotter.simple()  # the test speaks the wording in use ("Car on your left." for a beginner)
    return {"ok": True, "says": [phrase_text(p, simple) for p in ("car_left", "clear_left")], "gap_s": 1.2}
