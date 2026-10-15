"""Technique knowledge API: ``/api/technique/knowledge`` (mounted by ``api.app`` with ``app.include_router(router)``,
next to the technique router that shares its prefix).

Endpoints
    GET /api/technique/knowledge        the whole technique graph (``pitwall.knowledge.graph``), validated: phases,
                                        conditions, techniques, signals, faults, causes, advice, constraints and
                                        sources (each with its tier, sources and the file it lives in), the typed
                                        edges between them with the tier of the node making each claim, the tier
                                        meanings and the graph's ``digest`` (changes whenever the knowledge does)

The graph is packaged data, loaded and validated once per process (``load_graph``, cached); nothing here calls an
LLM or touches the database. A graph that did not load (a validation problem in a release: logged, and Pitwall runs
without technique knowledge) is 503, ``{"detail": {"message", "errors"}}`` listing its problems. Spec section 3 adds
``?session=<id>`` (the session's Context, detected style and per-node ``applies`` / ``why_not``).
"""

from __future__ import annotations

import asyncio
from typing import Any

import orjson
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from pitwall.knowledge.graph import load_graph

router = APIRouter(prefix="/api/technique", tags=["technique"])


class _Json(JSONResponse):
    """orjson, as every Pitwall route."""

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_NON_STR_KEYS)


def _payload() -> dict[str, Any]:
    graph = load_graph()
    if not graph.valid:
        raise HTTPException(
            503, {"message": "technique knowledge is unavailable: the graph did not load", "errors": list(graph.errors)}
        )
    return graph.to_payload()


@router.get("/knowledge")
async def technique_knowledge() -> _Json:
    return _Json(await asyncio.to_thread(_payload))  # the first call parses and validates the TOML files
