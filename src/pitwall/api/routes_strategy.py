"""Race strategy API (``pitwall.strategy``), mounted by ``api.app`` with ``app.include_router(router)``.

Endpoints
    GET /api/strategy/live          the live ``StrategyView`` (also in every ``/ws/live`` snapshot as ``strategy``);
                                    ``{"mode": "off", "reason": "no live session", ...}`` without a live session
    GET /api/sessions/{sid}/strategy
                                    ``StrategyTimeline`` of a stored session (Review > Strategy); 404 when the
                                    session does not exist, ``available: false`` with the reason otherwise

Handlers are plain ``def`` (thread pool). Everything is deterministic; nothing here calls an LLM or touches ingest.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from pitwall.strategy.engine import REASON_NOT_F1
from pitwall.strategy.timeline import build_timeline
from pitwall.strategy.view import off_view

router = APIRouter(tags=["strategy"])

REASON_NO_LIVE = "no live session"
REASON_WAITING = "waiting for race timing"


@router.get("/api/strategy/live")
def strategy_live(request: Request) -> dict[str, Any]:
    live = request.app.state.runtime.live
    sid = live.session_id
    if sid is None:
        return off_view(REASON_NO_LIVE)
    view = live.strategy
    if view is not None:
        return view  # type: ignore[no-any-return]
    s = live.session
    reason = REASON_NOT_F1 if s is not None and s.game.value != "f1_25" else REASON_WAITING
    return off_view(reason, sid, bool(live.synthetic))


@router.get("/api/sessions/{sid}/strategy")
def session_strategy(request: Request, sid: str) -> dict[str, Any]:
    with request.app.state.runtime.db.read() as c:
        timeline = build_timeline(c, sid)
    if timeline is None:
        raise HTTPException(404, "session not found")
    return timeline
