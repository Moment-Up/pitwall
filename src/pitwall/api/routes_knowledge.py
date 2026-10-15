"""Technique knowledge API: ``/api/technique/knowledge`` (mounted by ``api.app`` with ``app.include_router(router)``,
next to the technique router that shares its prefix).

Endpoints
    GET /api/technique/knowledge        the whole technique graph (``pitwall.knowledge.graph``), validated: phases,
                                        conditions, techniques, signals, faults, causes, advice, constraints and
                                        sources (each with its tier, sources and the file it lives in), the typed
                                        edges between them with the tier of the node making each claim, the tier
                                        meanings and the graph's ``digest`` (changes whenever the knowledge does)
    GET /api/technique/knowledge?session=<id>
                                        the same, for that session's driver (``knowledge.session.session_payload``):
                                        plus ``session_id``, ``context`` (the driver's Context: skill, detected braking
                                        style and coasting, game, car, assists, gearbox, fuel saving, wet), ``style``
                                        (what the style was detected from), ``channels`` (what the game sends) and, on
                                        every condition, signal, technique, fault, cause and advice node, ``applies``
                                        and ``why_not``. 404 for an unknown session.

The graph is packaged data, loaded and validated once per process (``load_graph``, cached); nothing here calls an
LLM. The session form reads the session through the shared ``SessionAnalyzer`` (cached) and, while the session is
live, the race strategy's fuel saving. A graph that did not load (a validation problem in a release: logged, and
Pitwall runs without technique knowledge) is 503, ``{"detail": {"message", "errors"}}`` listing its problems.
"""

from __future__ import annotations

import asyncio
from typing import Any

import orjson
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from pitwall.knowledge.graph import TechniqueGraph, load_graph

router = APIRouter(prefix="/api/technique", tags=["technique"])


class _Json(JSONResponse):
    """orjson, as every Pitwall route."""

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY)


def _graph() -> TechniqueGraph:
    graph = load_graph()
    if not graph.valid:
        raise HTTPException(
            503, {"message": "technique knowledge is unavailable: the graph did not load", "errors": list(graph.errors)}
        )
    return graph


def _payload() -> dict[str, Any]:
    return _graph().to_payload()


def _session_payload(request: Request, session_id: str) -> dict[str, Any]:
    from pitwall.knowledge.context import fuel_saving_of
    from pitwall.knowledge.session import session_payload

    graph = _graph()
    sa = request.app.state.analyzer.analyse(session_id)
    if sa is None:
        raise HTTPException(404, "session not found")
    live = getattr(getattr(request.app.state, "runtime", None), "live", None)
    strategy = live.strategy if live is not None and live.session_id == session_id else None
    return session_payload(sa, graph, fuel_saving=fuel_saving_of(strategy))


@router.get("/knowledge")
async def technique_knowledge(request: Request, session: str | None = None) -> _Json:
    if session is None:
        return _Json(await asyncio.to_thread(_payload))  # the first call parses and validates the TOML files
    return _Json(await asyncio.to_thread(_session_payload, request, session))
