"""Race radio API (``pitwall.raceradio``), mounted by ``api.app`` with ``app.include_router(router)``.

Endpoints
    GET /api/race/live          the live ``RaceView`` (also ``race`` in ``/ws/live`` snapshots, sent when it changed);
                                ``off_view`` with the reason ("no live session", "waiting for the race radio") otherwise
    GET /api/race/settings      the household's race radio settings: ``{"online_names": false}`` (the default)
    PUT /api/race/settings      the same body; answers what is stored (SettingsStore section ``race_radio``).
                                ``online_names``: say online players' names in "who's ahead?" answers only
                                (``raceradio.names``); proactive calls never do

Handlers are plain ``def`` (thread pool). Everything is deterministic; nothing here calls an LLM or touches ingest.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from pitwall.raceradio.model import off_view
from pitwall.raceradio.names import SECTION, online_names_enabled

router = APIRouter(tags=["race"])

REASON_NO_LIVE = "no live session"
REASON_WAITING = "waiting for the race radio"


@router.get("/api/race/live")
def race_live(request: Request) -> dict[str, Any]:
    live = request.app.state.runtime.live
    sid = live.session_id
    if sid is None:
        return off_view(REASON_NO_LIVE)
    view = live.race
    if view is not None:
        return view  # type: ignore[no-any-return]
    s = live.session
    return off_view(REASON_WAITING, sid, bool(live.synthetic), None if s is None else s.game.value)


class RaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    online_names: StrictBool  # true / false only: "yes" is refused, never read as on


@router.get("/api/race/settings")
def race_settings(request: Request) -> dict[str, Any]:
    return {"online_names": online_names_enabled(request.app.state.runtime.store.get(SECTION))}


@router.put("/api/race/settings")
def put_race_settings(request: Request, body: RaceSettings) -> dict[str, Any]:
    stored = request.app.state.runtime.store.replace(SECTION, {"online_names": body.online_names})
    return {"online_names": online_names_enabled(stored)}
