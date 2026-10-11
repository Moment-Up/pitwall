"""Rig validation kit API: ``/api/validation`` (mounted by ``api.app`` with ``app.include_router(router)``).

Endpoints (contract: the dashboard's ``lib/endpoints/validation.ts``)
    GET  /catalog                                   tests with live availability, radio commands
    GET  /active                                    {run: RunSummary | null} (polled by the device reporter)
    GET  /runs                                      RunSummary[], newest first
    POST /runs                                      {items?, label?, radio_prompts?} -> Run (201; 409: one active)
    GET  /runs/{id}?detail=compact|full             Run (full adds the raw evidence)
    POST /runs/{id}/current                         {item_id} -> Run
    POST /runs/{id}/next                            {} -> Run
    POST /runs/{id}/items/{item}/verdict            {verdict, notes?, attestations?, extra?} -> Run
    POST /runs/{id}/items/{item}/skip               {reason?} -> Run
    POST /runs/{id}/items/{item}/input-check        {phase, rotation_deg?} -> Run
    POST /runs/{id}/records/ptt/{record_id}         {heard_right} -> Run
    POST /runs/{id}/finish                          {notes?} -> Run
    POST /runs/{id}/abort                           {} -> Run
    GET  /runs/{id}/report                          ValidationReport
    GET  /runs/{id}/report.md?redact_transcripts=   text/markdown
    POST /client                                    ClientReport -> 204 | 409 {detail: "no active run"}

Handlers are ``async``: the kit's state lives on the event loop; files and database reads go to worker threads.
Errors: 404 unknown run / test / record, 409 state conflict, 422 invalid body (pydantic, ``extra="forbid"``, strings
length-limited). Auth is the app's ``/api/*`` middleware.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from pitwall.validate.kit import KitError, ValidationKit
from pitwall.validate.store import RUN_ID_PATTERN

router = APIRouter(prefix="/api/validation", tags=["validation"])

RunId = Annotated[str, Path(pattern=RUN_ID_PATTERN)]
ItemId = Annotated[str, Path(max_length=40, pattern=r"^[a-z0-9_]+$")]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartRunBody(_Body):
    items: list[Annotated[str, Field(max_length=40)]] | None = Field(default=None, max_length=30)
    label: str | None = Field(default=None, max_length=80)
    radio_prompts: bool | None = None


class CurrentBody(_Body):
    item_id: str = Field(max_length=40)


class EmptyBody(_Body):
    pass


class VerdictBody(_Body):
    verdict: Literal["worked", "didnt"] | None
    notes: str = Field(default="", max_length=2000)
    attestations: dict[Annotated[str, Field(max_length=40)], bool] = Field(default_factory=dict, max_length=20)
    extra: dict[Annotated[str, Field(max_length=32)], Annotated[str, Field(max_length=64)]] = Field(
        default_factory=dict, max_length=10
    )


class SkipBody(_Body):
    reason: str | None = Field(default=None, max_length=200)


class InputCheckBody(_Body):
    phase: Literal["centre", "left", "right", "pedals", "reverse", "stop"]
    rotation_deg: float | None = Field(default=None, gt=0, le=3600)


class PttMarkBody(_Body):
    heard_right: bool | None


class FinishBody(_Body):
    notes: str | None = Field(default=None, max_length=2000)


class Viewport(_Body):
    w: int = Field(ge=0, le=20000)
    h: int = Field(ge=0, le=20000)
    dpr: float = Field(ge=0, le=10)
    orientation: Literal["landscape", "portrait"]


class Wake(_Body):
    wanted: bool
    state: Literal["off", "pending", "on", "refused", "unsupported"]


class ClientRadio(_Body):
    phase: str = Field(max_length=32)
    conn: str = Field(max_length=32)
    mic: str = Field(max_length=32)
    mic_silent: bool
    wake: str = Field(max_length=32)
    audio: str = Field(max_length=32)
    audio_session: str = Field(max_length=32)
    tts_mode: Literal["device", "server"]
    rtt_ms: float | None = Field(default=None, ge=0, le=600000)


class ClientReportBody(_Body):
    run_id: str = Field(max_length=20)
    client_id: str = Field(min_length=1, max_length=64)
    seq: int = Field(ge=0, le=10**9)
    reason: Literal["start", "interval", "change", "hidden", "visible"]
    t_client_ms: float = Field(ge=0)
    device: Literal["ipad", "iphone", "android", "browser"]
    standalone: bool
    secure_context: bool
    origin_kind: Literal["tailscale_https", "https", "localhost", "lan_http", "other"]
    safari_version: str | None = Field(default=None, max_length=16)
    viewport: Viewport
    visibility: Literal["visible", "hidden"]
    route: str = Field(max_length=64)
    wake: Wake
    radio: ClientRadio | None = None
    audio_input_kind: Literal["airpods", "bluetooth", "built_in", "wired", "unknown"] | None = None
    fps_10s: float | None = Field(default=None, ge=0, le=1000)


def kit(request: Request) -> ValidationKit:
    """The app's kit; created lazily for apps whose lifespan does not create one (tests)."""
    k = getattr(request.app.state, "validation", None)
    if k is None:
        rt = request.app.state.runtime
        k = ValidationKit(rt.settings, rt, getattr(request.app.state, "hub", None), asyncio.get_running_loop())
        request.app.state.validation = k
    return k


def _fail(e: KitError) -> HTTPException:
    return HTTPException(e.status, e.detail)


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    k = kit(request)
    await k.refresh_drivers()
    return k.catalog()


@router.get("/active")
async def active(request: Request) -> dict[str, Any]:
    k = kit(request)
    return {"run": None if k.run is None else _summary(k)}


def _summary(k: ValidationKit) -> dict[str, Any]:
    from pitwall.validate.report import run_summary

    assert k.run is not None
    return run_summary(k.run)


@router.get("/runs")
async def runs(request: Request) -> list[dict[str, Any]]:
    k = kit(request)
    out = await asyncio.to_thread(k.store.list_runs)
    if k.run is not None:  # the active run's summary from memory (the file may lag by up to 2 s)
        out = [_summary(k) if r.get("id") == k.run.id else r for r in out]
        if not any(r.get("id") == k.run.id for r in out):
            out.insert(0, _summary(k))
    return out


@router.post("/runs", status_code=201)
async def start_run(request: Request, body: StartRunBody | None = None) -> dict[str, Any]:
    k = kit(request)
    b = body or StartRunBody()
    await k.refresh_drivers()
    try:
        run = k.start_run(b.items, b.label, b.radio_prompts)
    except KitError as e:
        raise _fail(e) from e
    await k.save_now()
    return k.run_api(run)


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: RunId, detail: Literal["compact", "full"] = "compact") -> dict[str, Any]:
    try:
        return await kit(request).get_run(run_id, detail)
    except KitError as e:
        raise _fail(e) from e


async def _act(request: Request, fn: Any, *args: Any) -> dict[str, Any]:
    k = kit(request)
    try:
        run = fn(*args)
    except KitError as e:
        raise _fail(e) from e
    await k.save_now()
    return k.run_api(run)


@router.post("/runs/{run_id}/current")
async def set_current(request: Request, run_id: RunId, body: CurrentBody) -> dict[str, Any]:
    return await _act(request, kit(request).set_current, run_id, body.item_id)


@router.post("/runs/{run_id}/next")
async def next_item(request: Request, run_id: RunId, body: EmptyBody | None = None) -> dict[str, Any]:
    return await _act(request, kit(request).next_item, run_id)


@router.post("/runs/{run_id}/items/{item_id}/verdict")
async def verdict(request: Request, run_id: RunId, item_id: ItemId, body: VerdictBody) -> dict[str, Any]:
    k = kit(request)
    return await _act(request, k.verdict, run_id, item_id, body.verdict, body.notes, body.attestations, body.extra)


@router.post("/runs/{run_id}/items/{item_id}/skip")
async def skip(request: Request, run_id: RunId, item_id: ItemId, body: SkipBody | None = None) -> dict[str, Any]:
    return await _act(request, kit(request).skip, run_id, item_id, (body or SkipBody()).reason)


@router.post("/runs/{run_id}/items/{item_id}/input-check")
async def input_check(request: Request, run_id: RunId, item_id: ItemId, body: InputCheckBody) -> dict[str, Any]:
    return await _act(request, kit(request).input_check, run_id, item_id, body.phase, body.rotation_deg)


@router.post("/runs/{run_id}/records/ptt/{record_id}")
async def mark_ptt(
    request: Request, run_id: RunId, record_id: Annotated[str, Path(max_length=40)], body: PttMarkBody
) -> dict[str, Any]:
    return await _act(request, kit(request).mark_ptt, run_id, record_id, body.heard_right)


@router.post("/runs/{run_id}/finish")
async def finish(request: Request, run_id: RunId, body: FinishBody | None = None) -> dict[str, Any]:
    k = kit(request)
    try:
        run = await k.finish(run_id, (body or FinishBody()).notes)
    except KitError as e:
        raise _fail(e) from e
    return k.run_api(run)


@router.post("/runs/{run_id}/abort")
async def abort(request: Request, run_id: RunId, body: EmptyBody | None = None) -> dict[str, Any]:
    k = kit(request)
    try:
        run = await k.finish(run_id, None, status="aborted")
    except KitError as e:
        raise _fail(e) from e
    return k.run_api(run)


@router.get("/runs/{run_id}/report")
async def report(request: Request, run_id: RunId) -> dict[str, Any]:
    try:
        rep, _run = await kit(request).report(run_id)
    except KitError as e:
        raise _fail(e) from e
    return rep


@router.get("/runs/{run_id}/report.md")
async def report_md(request: Request, run_id: RunId, redact_transcripts: Annotated[bool, Query()] = False) -> Response:
    try:
        md = await kit(request).report_md(run_id, redact_transcripts)
    except KitError as e:
        raise _fail(e) from e
    return Response(md, media_type="text/markdown; charset=utf-8")


@router.post("/client", status_code=204)
async def client_report(request: Request, body: ClientReportBody) -> Response:
    try:
        kit(request).client_report(body.model_dump())
    except KitError as e:
        raise _fail(e) from e
    return Response(status_code=204)
