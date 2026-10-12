"""Game selection API: "What are you playing?" (mounted by ``api.app`` with ``app.include_router(router)``).

Endpoints
    GET    /api/games          every catalogue entry with its feature profile (no ``fields`` / ``guide``)
    GET    /api/games/{id}     one entry with ``fields`` (AdapterInfo, capped by the entry level) and its Connect
                               ``guide`` filled in with this machine's LAN IP, ports and the AC/GT7 console IP
    GET    /api/game           ``GameState``: the selection, its input, live detection, mismatch, suggestion (live,
                               else the most recent real session: one ``repo.list_sessions`` read)
    PUT    /api/game           ``{id, console_ip?, ensure_input? = true, source? = "dashboard"}``
                               -> ``{state, actions}``
    DELETE /api/game           clears the selection (inputs untouched) -> ``GameState``

Storage: ``SettingsStore`` section ``"game"`` (``games.SECTION``), owned by this module and ``pitwall game``; the
runtime pushes it into ``LiveState`` (snapshot ``game``). Selecting a game never disables an input: it switches the
game's own input on (and sets AC's platform / a console IP) unless that input is streaming right now
(``skipped_live``), and a port conflict is reported as an action, not an HTTP error - the selection is a fact about
what the household plays, so it is saved either way. Errors: 422 for an unknown id or an invalid / unneeded console
IP. Handlers are plain ``def`` (FastAPI's thread pool): applying an input binds sockets and reads the database.
"""

from __future__ import annotations

import threading
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from pitwall import games
from pitwall.core.runtime import Runtime
from pitwall.drivers import NotFoundError
from pitwall.storage import repo

router = APIRouter(tags=["game"])
HISTORY_SESSIONS = 20
_write_lock = threading.Lock()  # selection + input side effects as one step (two devices choosing at once)


class GamePut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    console_ip: str | None = None
    ensure_input: bool = True
    source: Literal["dashboard", "cli"] = "dashboard"  # who chose (``pitwall game set`` sends "cli")


def _rt(request: Request) -> Runtime:
    return request.app.state.runtime  # type: ignore[no-any-return]


def game_state(rt: Runtime) -> dict[str, Any]:
    """``GameState`` for the running server (history suggestion only while nothing is selected or detected). A
    driver's usual game also names that driver (``selected.by_driver_name``; None when the profile is gone)."""
    sel = rt.live.game_selection
    block = rt.live.game_block()
    history = None
    if sel is None and block.get("suggestion") is None:
        with rt.db.read() as c:
            history = games.history_suggestion(repo.list_sessions(c, HISTORY_SESSIONS))
    out = games.game_state(sel, block, rt.input_status(), rt.integration_configs(), history)
    if sel is not None and out["selected"] is not None:
        name = None
        if sel.by_driver_id is not None:
            try:
                name = rt.drivers.get(sel.by_driver_id).name
            except NotFoundError:
                name = None
        out["selected"]["by_driver_name"] = name
    return out


def entry_guide(rt: Runtime, entry: games.GameEntry) -> dict[str, Any] | None:
    """The Connect guide of ``entry`` with this machine's LAN IP, ports and the AC console IP / platform filled in."""
    from pitwall.compat import this_machine
    from pitwall.connect import game_guides, primary_lan_ip

    if entry.guide_id is None:
        return None
    ac = next((r for r in rt.input_status() if r.get("key") == "ac"), {})
    ac_ip = ac.get("console_ip") if isinstance(ac.get("console_ip"), str) else None
    ac_platform = ac.get("platform") if isinstance(ac.get("platform"), str) else None
    ip = primary_lan_ip() or f"<{this_machine()}'s IP>"
    controls = getattr(rt, "controls", None)  # Setup › Controls: the effective push-to-talk action
    ptt = controls.ptt_now() if controls is not None else None
    guide = next((g for g in game_guides(ip, rt.settings, ac_ip, ac_platform, ptt) if g.id == entry.guide_id), None)
    return None if guide is None else asdict(guide)


@router.get("/api/games")
def list_games(request: Request) -> dict[str, Any]:
    return games.games_response(_rt(request).integration_configs())


@router.get("/api/games/{entry_id}")
def get_game(request: Request, entry_id: str) -> dict[str, Any]:
    rt = _rt(request)
    entry = games.entry(entry_id)
    if entry is None:
        raise HTTPException(404, f"unknown game {entry_id!r}")
    return entry.to_dict(rt.integration_configs(), with_fields=True, guide=entry_guide(rt, entry))


@router.get("/api/game")
def get_state(request: Request) -> dict[str, Any]:
    return game_state(_rt(request))


@router.put("/api/game")
def put_game(request: Request, body: GamePut) -> dict[str, Any]:
    rt = _rt(request)
    entry = games.entry(body.id)
    if entry is None:
        raise HTTPException(422, f"unknown game {body.id!r}: see GET /api/games")
    try:
        console_ip = games.validate_console_ip(entry, body.console_ip)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    with _write_lock:
        sel = games.new_selection(entry.id, body.source)
        rt.store.replace(games.SECTION, sel.section())  # the runtime listener updates the live snapshot
        actions: list[dict[str, Any]] = []
        if body.ensure_input:  # False: only the selection (a console IP is validated, not stored)
            actions = games.ensure_input(entry, rt.settings, rt.store, rt.input_status(), console_ip)
    return {"state": game_state(rt), "actions": actions}


@router.delete("/api/game")
def clear_game(request: Request) -> dict[str, Any]:
    rt = _rt(request)
    with _write_lock:
        rt.store.replace(games.SECTION, {})
    return game_state(rt)
