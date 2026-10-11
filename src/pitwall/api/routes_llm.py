"""AI provider settings API: ``/api/llm/*`` (mounted by ``api.app`` with ``app.include_router(router)``).

Endpoints
    GET    /api/llm/providers?health=false   presets, current config, masked keys, status (+ health when asked)
    PUT    /api/llm/config                   save the provider config (validated; takes effect immediately)
    PUT    /api/llm/keys/{name}              {"value": "..."} store an API key; the response never contains it
    DELETE /api/llm/keys/{name}              remove a stored key
    POST   /api/llm/test                     {"role", "purpose"}: health + one grounded test question through the
                                             real engineer path (canned test facts, never your telemetry)
    POST   /api/llm/models                   {"provider", "base_url"}: models the provider offers (sends no
                                             telemetry; a saved key only to the endpoint it belongs to)
    GET    /api/llm/usage                    tokens / cost today and recent days, budget state
    GET    /api/llm/last-request             the last request sent to a provider (no headers, keys scrubbed)

State: ``app.state.llm`` is the process-wide ``SwitchableProvider`` (``ai/provider_registry.py``); it owns the
SettingsStore section ``"llm"`` and reads keys from the SecretStore it was built with.

Secrets: key values are only ever accepted, never returned. ``PUT /keys`` parses its body by hand so a malformed
request cannot be echoed back in FastAPI's validation error (which would include the submitted key).
``/api/llm/health`` stays in ``api.app`` (it reads ``app.state.provider``).

Cross-site requests: the app trusts loopback and the owner's Tailscale identity without a token, so a page in any
browser on those devices can make requests here. Every state-changing or outbound-calling endpoint is therefore
non-simple in CORS terms: PUT/DELETE always need a preflight (which this app never grants), and the POSTs require
``Content-Type: application/json`` - a cross-site page can only send that after a preflight. (FastAPI would
otherwise parse a JSON body sent with no content type, which a cross-site page *can* send.) The only outbound
requests a GET can trigger are ``/providers?health=true`` checks of the *saved* endpoints, each with its own key
and no tokens spent; nothing that takes a URL or spends tokens is a GET.

Privacy notice: the client sends the notice version it displayed; the server accepts only the current one (409
otherwise), so a tab opened before a notice change can never acknowledge text it did not show.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any, Literal

import orjson
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import FactSheet
from pitwall.ai.provider_registry import (
    EFFORTS,
    KEY_NAMES,
    PRESETS,
    PRIVACY_NOTICE,
    PRIVACY_NOTICE_VERSION,
    PURPOSES,
    ConfigError,
    SwitchableProvider,
    parse_config,
    presets_public,
    price_table,
)
from pitwall.ai.providers import LLMUnavailable, ProviderHealth
from pitwall.settings_store import SecretStore, mask_secret

router = APIRouter(prefix="/api/llm", tags=["llm"])

HEALTH_TIMEOUT_S = 8.0
TEST_QUESTION = "What was my best lap?"


# ---------------------------------------------------------------------------------------------- models
class ModelsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engineer: str | None = Field(default=None, max_length=200)
    radio: str | None = Field(default=None, max_length=200)


class SpecIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(max_length=40)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=200)
    models: ModelsIn = Field(default_factory=ModelsIn)
    timeout_s: float = Field(default=60.0, ge=2, le=600)
    max_tokens: int | None = Field(default=None, ge=16, le=8192)
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"


class PrivacyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cloud_enabled: bool = False
    # Version of the privacy notice the page displayed and the user ticked; None = not acknowledged.
    acknowledged_notice_version: int | None = Field(default=None, ge=0)
    redact_driver_names: bool = True


class BudgetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    daily_usd: float | None = Field(default=None, ge=0, le=10_000)


class PriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_per_mtok: float = Field(ge=0, le=1000)
    output_per_mtok: float = Field(ge=0, le=1000)


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    primary: SpecIn
    fallback: SpecIn | None = None
    privacy: PrivacyIn = Field(default_factory=PrivacyIn)
    budget: BudgetIn = Field(default_factory=BudgetIn)
    prices: dict[str, PriceIn] = Field(default_factory=dict, max_length=50)


class TestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["primary", "fallback"] = "primary"
    purpose: Literal["engineer", "radio"] = "engineer"


class ModelListIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(max_length=40)
    base_url: str | None = Field(default=None, max_length=300)


# ---------------------------------------------------------------------------------------------- helpers
def require_json(request: Request) -> None:
    """Refuse POSTs that a cross-site page could send without a CORS preflight (see the module docstring)."""
    ctype = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if ctype != "application/json":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "send JSON (Content-Type: application/json)")


def llm_manager(request: Request) -> SwitchableProvider:
    llm = getattr(request.app.state, "llm", None)
    if not isinstance(llm, SwitchableProvider):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI provider settings are not available")
    return llm


def _mask(value: str) -> str:
    """Display form of a key. Short values (custom local servers) show no characters at all."""
    return mask_secret(value) if len(value) >= 20 else f"saved ({len(value)} characters)"


def _keys(llm: SwitchableProvider) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in sorted(KEY_NAMES):
        value = llm.key_value(name)
        out[name] = {
            "set": bool(value),
            "masked": _mask(value) if value else None,
            "source": llm.key_source(name),  # "env" | "file" | "settings" (.env) | None
            "env_var": SecretStore.env_name(name),
        }
    return out


def _config_out(llm: SwitchableProvider) -> dict[str, Any]:
    cfg = llm.config
    d = cfg.to_dict()
    d["privacy"]["notice_acknowledged"] = cfg.notice_version >= PRIVACY_NOTICE_VERSION
    return d


def _health_dict(h: ProviderHealth) -> dict[str, Any]:
    return asdict(h)


async def _health(llm: SwitchableProvider, role: Literal["primary", "fallback"]) -> dict[str, Any] | None:
    if not any(r == role for r, _ in llm.config.specs()):
        return None
    try:
        h = await asyncio.wait_for(llm.health("engineer", role), HEALTH_TIMEOUT_S)
    except TimeoutError:
        spec = dict(llm.config.specs())[role]
        h = ProviderHealth(False, spec.url, spec.model_for("engineer"), f"no answer within {HEALTH_TIMEOUT_S:.0f} s")
    return _health_dict(h)


def _overview(llm: SwitchableProvider) -> dict[str, Any]:
    return {
        "presets": presets_public(),
        "config": _config_out(llm),
        "status": llm.status(),
        "keys": _keys(llm),
        "privacy_notice": {"version": PRIVACY_NOTICE_VERSION, "points": list(PRIVACY_NOTICE)},
        "purposes": list(PURPOSES),
        "efforts": list(EFFORTS),
        "prices": price_table(),
    }


def _test_sheet() -> FactSheet:
    """Canned facts for the connection test: clearly labelled, never the driver's real telemetry."""
    fs = FactSheet()
    fs.add("session", "Session: PITWALL CONNECTION TEST (sample data, not your telemetry): Red Bull Ring, Race.")
    fs.add("laps", "Best clean lap this session: lap 4 in 1:05.626.", {"lap": 4, "lap_time_s": 65.626})
    fs.add("laps", "Last lap: lap 6 in 1:06.104 (0.478 s slower than the best).", {"lap": 6, "lap_time_s": 66.104})
    fs.add("reference", "Reference lap for comparisons: lap 4 (this session) in 1:05.626.")
    return fs


# ---------------------------------------------------------------------------------------------- routes
@router.get("/providers")
async def providers(request: Request, health: bool = False) -> dict[str, Any]:
    llm = llm_manager(request)
    out = _overview(llm)
    if health:
        primary, fallback = await asyncio.gather(_health(llm, "primary"), _health(llm, "fallback"))
        out["health"] = {"primary": primary, "fallback": fallback}
    return out


@router.put("/config")
def put_config(request: Request, body: ConfigIn) -> dict[str, Any]:
    """Validate and save. Cloud providers need ``privacy.cloud_enabled`` and the current notice acknowledged."""
    llm = llm_manager(request)
    prev = llm.config
    shown = body.privacy.acknowledged_notice_version
    if shown is not None and shown != PRIVACY_NOTICE_VERSION:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "privacy: the privacy notice has changed since this page was loaded - read it and acknowledge it again",
        )
    ack = shown is not None
    already = prev.notice_version >= PRIVACY_NOTICE_VERSION
    raw: dict[str, Any] = {
        "enabled": body.enabled,
        "primary": body.primary.model_dump(),
        "fallback": body.fallback.model_dump() if body.fallback else None,
        "privacy": {
            "cloud_enabled": body.privacy.cloud_enabled,
            "notice_version": PRIVACY_NOTICE_VERSION if ack else 0,
            "acknowledged_at": (prev.acknowledged_at if already else time.time()) if ack else None,
            "redact_driver_names": body.privacy.redact_driver_names,
        },
        "budget": {"daily_usd": body.budget.daily_usd},
        "prices": {m: p.model_dump() for m, p in body.prices.items()},
    }
    if body.privacy.cloud_enabled and not ack:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "privacy: acknowledge the privacy notice to enable cloud AI"
        )
    try:
        cfg = parse_config(raw)
    except ConfigError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    llm.save_config(cfg)
    return _overview(llm)


@router.put("/keys/{name}")
async def put_key(request: Request, name: str) -> dict[str, Any]:
    llm = llm_manager(request)
    if name not in KEY_NAMES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown key name")
    try:
        payload = orjson.loads(await request.body())
    except orjson.JSONDecodeError:
        payload = None
    value = payload.get("value") if isinstance(payload, dict) else None
    # Never include the submitted value in an error: these messages are generic on purpose.
    if not isinstance(value, str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, 'body must be JSON {"value": "<key>"}')
    value = value.strip()
    if not 8 <= len(value) <= 512:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "key must be 8-512 characters")
    if any(c.isspace() or not c.isprintable() or not c.isascii() for c in value):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "key contains spaces or invalid characters")
    await asyncio.to_thread(llm.secrets.set, name, value)
    llm.reload()
    src = llm.key_source(name)
    return {
        "name": name,
        "saved": True,
        "masked": _mask(llm.key_value(name) or ""),
        "source": src,
        "note": f"{SecretStore.env_name(name)} is set and takes precedence over the saved key"
        if src == "env"
        else None,
    }


@router.delete("/keys/{name}")
async def delete_key(request: Request, name: str) -> dict[str, Any]:
    llm = llm_manager(request)
    if name not in KEY_NAMES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown key name")
    await asyncio.to_thread(llm.secrets.set, name, None)
    llm.reload()
    src = llm.key_source(name)
    notes = {
        "env": f"{SecretStore.env_name(name)} is still set in the environment",
        "settings": f"{SecretStore.env_name(name)} is still set in pitwall's .env file",
    }
    return {"name": name, "deleted": True, "set": src is not None, "note": notes.get(src or "")}


@router.post("/test", dependencies=[Depends(require_json)])
async def test_provider(request: Request, body: TestIn) -> dict[str, Any]:
    """Health, then one question through ``RaceEngineer`` with this provider only. Real call: it is billed and
    counted in usage like any other."""
    llm = llm_manager(request)
    specs = dict(llm.config.specs())
    spec = specs.get(body.role)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no {body.role} provider configured")
    t0 = time.perf_counter()
    try:
        h = await asyncio.wait_for(llm.health(body.purpose, body.role), HEALTH_TIMEOUT_S)
    except TimeoutError:
        h = ProviderHealth(False, spec.url, spec.model_for(body.purpose), "health check timed out")
    base = getattr(request.app.state, "engineer", None)
    engineer = RaceEngineer(
        llm.for_purpose(body.purpose, body.role),
        max_tokens=getattr(base, "max_tokens", 350),
        temperature=getattr(base, "temperature", 0.2),
    )
    ans = await engineer.answer(TEST_QUESTION, _test_sheet())
    llm_ok = not ans.fallback and bool(ans.grounded) and ans.model is not None
    return {
        "ok": llm_ok,
        "role": body.role,
        "purpose": body.purpose,
        "provider": spec.provider,
        "location": spec.location,
        "model": ans.model or spec.model_for(body.purpose),
        "health": _health_dict(h),
        "question": TEST_QUESTION,
        "answer": ans.text,
        "grounded": ans.grounded,
        "fallback": ans.fallback,
        "llm_attempts": ans.llm_attempts,
        "issues": ans.grounding_issues,
        "answer_latency_ms": ans.latency_ms,
        "total_ms": int((time.perf_counter() - t0) * 1000),
        "note": "Answered from sample test facts, not your telemetry.",
    }


@router.post("/models", dependencies=[Depends(require_json)])
async def models(request: Request, body: ModelListIn) -> dict[str, Any]:
    """Models a provider offers. A POST (JSON only) because it makes an outbound request; the registry sends a
    saved key only to that key's own endpoint (vendor host, or the server URL saved in the config)."""
    llm = llm_manager(request)
    provider = body.provider
    preset = PRESETS.get(provider)
    if preset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown provider")
    try:
        listed = await llm.list_models(provider, body.base_url)
        error = None
    except LLMUnavailable as e:
        listed, error = [], str(e)
    return {
        "provider": provider,
        "models": listed,
        "suggested": {"engineer": preset.suggested_engineer, "radio": preset.suggested_radio},
        "suggested_models": list(preset.suggested_models),
        "error": error,
    }


@router.get("/usage")
async def usage(request: Request) -> dict[str, Any]:
    return llm_manager(request).usage()


@router.get("/last-request")
async def last_request(request: Request) -> dict[str, Any]:
    return {"last": llm_manager(request).last_request()}
