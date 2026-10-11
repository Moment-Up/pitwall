"""Update status API: ``/api/update`` (mounted by ``api.app`` with ``app.include_router(router)``).

Endpoints
    GET  /api/update        ``UpdateStatus`` (install/check.py, web-react/src/lib/endpoints/update.ts). With
                            ``PITWALL_UPDATE_CHECK=auto`` it may start a background check: last success over 24 h
                            ago, last attempt over 10 min ago, telemetry not live.
    POST /api/update/check  body ``{}``: start a check now. 409 when checks are off; the current status (no new
                            check) while one runs or one finished less than 60 s ago.
    GET  /api/update/version  ``{"current": "v0.2.0", "install_kind": "managed"}``: which version is running. Never
                            contacts GitHub; ``pitwall install-finish`` polls it after a switch to tell the new
                            version from the old one still answering.

There is no endpoint that installs anything: updating replaces the server's own files and restarts it, so it is
done from a terminal on the computer (``uv run pitwall update``), never by a device on the network.

Handlers only read memory and one small file (well within 50 ms); the GitHub request runs in a worker thread
(``asyncio.to_thread``), one at a time. Nothing here touches ingest or the language model. The POST requires
``Content-Type: application/json`` so a cross-site page cannot start checks without a CORS preflight.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from pitwall.install.check import UpdateChecker
from pitwall.install.versions import code_root

router = APIRouter(prefix="/api/update", tags=["update"])


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


def require_json(request: Request) -> None:
    ctype = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if ctype != "application/json":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "send JSON (Content-Type: application/json)")


def checker(request: Request) -> UpdateChecker:
    st = request.app.state
    c = getattr(st, "update_checker", None)
    if isinstance(c, UpdateChecker):
        return c
    settings = st.runtime.settings
    c = UpdateChecker(settings.data_dir, settings.update_check, code_root())
    st.update_checker = c
    return c


def _live(request: Request) -> bool:
    try:
        return bool(request.app.state.runtime.live.connection().get("status") == "live")
    except AttributeError:
        return False


def _start(request: Request, c: UpdateChecker) -> bool:
    if not c.try_begin():
        return False
    task = asyncio.get_running_loop().create_task(asyncio.to_thread(c.run_claimed))
    tasks: set[asyncio.Task[None]] = getattr(request.app.state, "update_tasks", set())
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    request.app.state.update_tasks = tasks
    return True


@router.get("")
async def update_status(request: Request) -> dict[str, Any]:
    c = checker(request)
    if c.wants_auto_refresh(_live(request)):
        _start(request, c)
    return c.status()


@router.get("/version")
async def running_version(request: Request) -> dict[str, Any]:
    c = checker(request)
    return {"current": c.current, "install_kind": c.kind}


@router.post("/check", dependencies=[Depends(require_json)])
async def update_check(request: Request, body: CheckIn) -> dict[str, Any]:
    c = checker(request)
    if c.mode == "off":
        raise HTTPException(status.HTTP_409_CONFLICT, "Update checks are off (PITWALL_UPDATE_CHECK=off).")
    if not c.checking and not c.recently_finished():
        _start(request, c)
    return c.status()
