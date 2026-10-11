"""Cloud/local LLM providers, the switchable provider registry and the /api/llm routes. No network: Anthropic and
OpenAI wire formats are exercised through mock transports, the registry through scripted fake providers."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import secrets as pysecrets
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import FactSheet
from pitwall.ai.provider_registry import (
    PRESETS,
    PRIVACY_NOTICE_VERSION,
    SECTION,
    ConfigError,
    LLMConfig,
    ProviderBuild,
    ProviderSpec,
    SwitchableProvider,
    check_base_url,
    config_from_settings,
    default_factory,
    is_local_host,
    key_name_for,
    parse_config,
    redact_messages,
    redact_names,
)
from pitwall.ai.providers import (
    ANTHROPIC_FALLBACK_BETA,
    AnthropicProvider,
    BilledUsage,
    LLMResult,
    LLMUnavailable,
    OpenAICompatibleProvider,
    ProviderHealth,
)
from pitwall.api.routes_llm import router
from pitwall.config import Settings
from pitwall.settings_store import SecretStore, SettingsStore

ANTHROPIC_KEY = "sk-ant-api03-" + pysecrets.token_hex(32) + "Zq9Z"
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "LLM_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(f"PITWALL_{name}", raising=False)


# =============================================================================================== Anthropic wire
def _message(
    text: str | None = "Best lap was 1:05.626 [F2].",
    *,
    model: str = "claude-haiku-5-5",
    stop_reason: str = "end_turn",
    stop_details: dict[str, Any] | None = None,
    usage: tuple[int, int] = (120, 30),
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "thinking", "thinking": "", "signature": "sig"}]
    if text is not None:
        content.append({"type": "text", "text": text})
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }


def _anthropic(
    handler: Callable[[httpx2.Request], httpx2.Response], model: str = "claude-haiku-5-5", **kw: Any
) -> AnthropicProvider:
    kw.setdefault("max_retries", 0)
    return AnthropicProvider(ANTHROPIC_KEY, model, transport=httpx2.MockTransport(handler), **kw)


def _engineer_messages() -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "You are a race engineer."},
        {"role": "assistant", "content": "earlier engineer reply (history starting mid-conversation)"},
        {"role": "user", "content": "FACTS:\n[F2] Best clean lap: lap 4 in 1:05.626.\n\nDRIVER: best lap?"},
    ]


async def test_anthropic_request_shape_and_response_parsing() -> None:
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(200, json=_message())

    p = _anthropic(handler)
    res = await p.chat(_engineer_messages(), max_tokens=350, temperature=0.2)
    req = seen[0]
    body = json.loads(req.content)
    assert req.url.host == "api.anthropic.com" and req.url.path == "/v1/messages"
    assert req.headers["x-api-key"] == ANTHROPIC_KEY and req.headers["anthropic-version"]
    assert "anthropic-beta" not in req.headers  # Haiku 5.5 has no server-side fallback
    assert body["model"] == "claude-haiku-5-5"
    assert body["system"] == "You are a race engineer."
    assert [m["role"] for m in body["messages"]] == ["user"]  # leading assistant turn dropped, system lifted
    assert "temperature" not in body and "thinking" not in body and "fallbacks" not in body
    assert body["output_config"] == {"effort": "low"}
    assert body["max_tokens"] == 350 + 1024  # thinking headroom on top of the answer budget
    assert res.text == "Best lap was 1:05.626 [F2]."  # thinking block ignored
    assert (res.model, res.prompt_tokens, res.completion_tokens) == ("claude-haiku-5-5", 120, 30)
    assert p.last_request is not None and ANTHROPIC_KEY not in json.dumps(p.last_request)
    await p.aclose()


async def test_anthropic_opus_opts_into_refusal_fallback_and_structured_output() -> None:
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(200, json=_message('{"answer": "lap 4"}', model="claude-opus-5-5"))

    p = _anthropic(handler, model="claude-opus-5-5", effort="medium")
    res = await p.chat([{"role": "user", "content": "best lap?"}], max_tokens=200, json_schema=SCHEMA)
    req = seen[0]
    body = json.loads(req.content)
    assert req.url.path == "/v1/messages" and req.url.params.get("beta") == "true"
    assert ANTHROPIC_FALLBACK_BETA in req.headers["anthropic-beta"]
    assert body["fallbacks"] == "default"
    assert body["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert json.loads(res.text) == {"answer": "lap 4"}
    await p.aclose()


async def test_anthropic_rejected_optional_fields_are_dropped_once_and_remembered() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        body = json.loads(req.content)
        bodies.append(body)
        if "fallbacks" in body:
            err = {"type": "invalid_request_error", "message": "fallbacks: not available for this organization"}
            return httpx2.Response(400, json={"type": "error", "error": err})
        return httpx2.Response(200, json=_message(model="claude-opus-5-5"))

    p = _anthropic(handler, model="claude-opus-5-5")
    assert (await p.chat([{"role": "user", "content": "q"}])).text
    assert (await p.chat([{"role": "user", "content": "q"}])).text
    assert ["fallbacks" in b for b in bodies] == [True, False, False]
    assert not p.breaker_open
    await p.aclose()


async def test_anthropic_refusal_and_truncation_do_not_trip_the_breaker() -> None:
    replies = [
        _message(
            None, stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": None}
        ),
        _message(None, stop_reason="max_tokens"),
    ] * 3

    def handler(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=replies.pop(0))

    p = _anthropic(handler, failure_threshold=2)
    for _ in range(3):
        with pytest.raises(LLMUnavailable, match=r"safety classifier.*cyber"):
            await p.chat([{"role": "user", "content": "q"}])
        with pytest.raises(LLMUnavailable, match="max_tokens"):
            await p.chat([{"role": "user", "content": "q"}])
    assert not p.breaker_open  # the endpoint is healthy; the engineer just answers deterministically
    await p.aclose()


@pytest.mark.parametrize(
    ("status", "match"),
    [(401, "rejected the API key"), (404, "not found"), (429, "rate limit"), (500, "API error 500"), (529, "529")],
)
async def test_anthropic_http_errors_map_to_unavailable_and_open_breaker(status: int, match: str) -> None:
    def handler(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"type": "error", "error": {"type": "api_error", "message": "nope"}})

    p = _anthropic(handler, failure_threshold=2)
    for _ in range(2):
        with pytest.raises(LLMUnavailable, match=match):
            await p.chat([{"role": "user", "content": "q"}])
    assert p.breaker_open
    with pytest.raises(LLMUnavailable, match="circuit breaker"):
        await p.chat([{"role": "user", "content": "q"}])
    await p.aclose()


async def test_anthropic_connection_error_and_timeout_map_to_unavailable() -> None:
    def refuse(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=req)

    def slow(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=req)

    p = _anthropic(refuse)
    with pytest.raises(LLMUnavailable, match="cannot reach Anthropic"):
        await p.chat([{"role": "user", "content": "q"}])
    q = _anthropic(slow, timeout_s=3)
    with pytest.raises(LLMUnavailable, match="timed out"):
        await q.chat([{"role": "user", "content": "q"}])
    await p.aclose()
    await q.aclose()


async def test_anthropic_ignores_environment_credentials_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-should-not-be-used")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example.com")
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(200, json=_message())

    p = _anthropic(handler)
    await p.chat([{"role": "user", "content": "q"}])
    assert seen[0].url.host == "api.anthropic.com" and seen[0].headers["x-api-key"] == ANTHROPIC_KEY
    await p.aclose()


async def test_anthropic_health_and_model_listing() -> None:
    info = {
        "id": "claude-haiku-5-5",
        "type": "model",
        "display_name": "Claude Haiku 5.5",
        "created_at": "2026-09-01T00:00:00Z",
        "lifecycle": "active",
        "max_input_tokens": 1_000_000,
        "max_tokens": 128_000,
    }

    def handler(req: httpx2.Request) -> httpx2.Response:
        if req.url.path == "/v1/models/claude-haiku-5-5":
            return httpx2.Response(200, json=info)
        if req.url.path == "/v1/models":
            return httpx2.Response(200, json={"data": [info], "has_more": False, "first_id": "a", "last_id": "a"})
        return httpx2.Response(404)

    p = _anthropic(handler)
    h = await p.health()
    assert h.ok and h.model == "claude-haiku-5-5" and h.context_tokens == 1_000_000
    models = await p.list_models()
    assert models[0]["id"] == "claude-haiku-5-5" and models[0]["display_name"] == "Claude Haiku 5.5"
    await p.aclose()


# =============================================================================================== OpenAI presets
def _openai_transport(seen: list[httpx.Request], status: int = 200) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path.endswith("/models"):
            return httpx.Response(status, json={"data": [{"id": "b-model"}, {"id": "a-model"}]})
        body = json.loads(req.content)
        return httpx.Response(
            status,
            json={
                "model": body["model"],
                "choices": [{"message": {"content": "ok [F1]"}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},
            },
        )

    return httpx.MockTransport(handler)


def _built(preset_id: str, model: str | None, key: str | None, base_url: str | None = None) -> OpenAICompatibleProvider:
    preset = PRESETS[preset_id]
    p = default_factory(ProviderBuild(preset, base_url or preset.base_url, model, key, 30.0, "low", preset_id))
    assert isinstance(p, OpenAICompatibleProvider)
    return p


async def test_openai_cloud_preset_wire_format() -> None:
    seen: list[httpx.Request] = []
    p = _built("openai", "gpt-test", "sk-openai-test-key-000000")
    p._client = httpx.AsyncClient(headers=p._client.headers, transport=_openai_transport(seen))
    await p.chat([{"role": "user", "content": "q"}], max_tokens=350, temperature=0.2, json_schema=SCHEMA)
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.openai.com/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer sk-openai-test-key-000000"
    assert body["max_completion_tokens"] == 350 + 1024 and "max_tokens" not in body
    assert "temperature" not in body and "cache_prompt" not in body  # OpenAI rejects both for reasoning models
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    await p.aclose()


async def test_llamacpp_preset_keeps_the_original_request_body() -> None:
    seen: list[httpx.Request] = []
    p = _built("llamacpp", "qwen", None)
    p._client = httpx.AsyncClient(transport=_openai_transport(seen))
    await p.chat([{"role": "user", "content": "q"}], max_tokens=350, temperature=0.2)
    body = json.loads(seen[0].content)
    assert list(body) == ["model", "messages", "max_tokens", "temperature", "stream", "cache_prompt"]
    assert body["max_tokens"] == 350 and body["temperature"] == 0.2 and body["cache_prompt"] is True
    assert p.probe_health_endpoint and p.last_request is not None
    await p.aclose()


async def test_hosted_openai_health_uses_models_listing_and_reports_bad_keys() -> None:
    seen: list[httpx.Request] = []
    p = _built("groq", "llama-test", "gsk_bad_key_0000000000")
    p._client = httpx.AsyncClient(headers=p._client.headers, transport=_openai_transport(seen, status=401))
    h = await p.health()
    assert not h.ok and "API key rejected" in h.detail and seen[0].url.path == "/openai/v1/models"
    p._client = httpx.AsyncClient(transport=_openai_transport(seen))
    assert [m["id"] for m in await p.list_models()] == ["a-model", "b-model"]
    await p.aclose()


# =============================================================================================== registry
class FakeProvider:
    """Scripted ManagedProvider: replies are strings, exceptions, or callables of the received messages."""

    def __init__(self, build: ProviderBuild, script: list[Any]) -> None:
        self.build = build
        self.name = build.name
        self.script = script
        self.calls: list[dict[str, Any]] = []
        self.last_request: dict[str, Any] | None = None
        self.closed = False

    async def chat(self, messages: list[dict[str, Any]], **kw: Any) -> LLMResult:
        self.calls.append({"messages": copy.deepcopy(messages), **kw})
        self.last_request = {"body": {"model": self.build.model, "messages": copy.deepcopy(messages)}}
        r = self.script.pop(0) if self.script else "Best lap 1:05.626 on lap 4 [F2]."
        if isinstance(r, Exception):
            raise r
        if callable(r):
            r = r(messages)
            if inspect.isawaitable(r):
                r = await r
        if isinstance(r, LLMResult):
            return r
        return LLMResult(
            text=r, model=self.build.model or "auto", latency_ms=3, prompt_tokens=1000, completion_tokens=500
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(True, self.build.base_url, self.build.model, "ok")

    async def list_models(self) -> list[dict[str, Any]]:
        return [{"id": "m1"}, {"id": "m2"}]

    async def aclose(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(self, scripts: dict[str, list[Any]] | None = None) -> None:
        self.scripts = scripts or {}
        self.built: list[FakeProvider] = []

    def __call__(self, b: ProviderBuild) -> FakeProvider:
        p = FakeProvider(b, self.scripts.get(b.preset.id, []))
        self.built.append(p)
        return p

    def calls(self, preset_id: str, model: str | None = None) -> list[dict[str, Any]]:
        return [
            c
            for p in self.built
            if p.build.preset.id == preset_id and (model is None or p.build.model == model)
            for c in p.calls
        ]


def _stores(tmp: Path) -> tuple[SettingsStore, SecretStore]:
    return SettingsStore(tmp / "settings.json"), SecretStore(tmp / "secrets.json")


def _cloud_cfg(**over: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "enabled": True,
        "primary": {
            "provider": "anthropic",
            "models": {"engineer": "claude-opus-5-5", "radio": "claude-haiku-5-5"},
            "timeout_s": 30,
        },
        "fallback": {"provider": "llamacpp"},
        "privacy": {"cloud_enabled": True, "notice_version": PRIVACY_NOTICE_VERSION, "redact_driver_names": True},
        "budget": {"daily_usd": None},
    }
    cfg.update(over)
    return cfg


def _sheet() -> FactSheet:
    fs = FactSheet()
    fs.add("session", "Session: f1_25 at Austria, Race. Driver: Sam (beginner level).")
    fs.add("laps", "Best clean lap this session: lap 4 in 1:05.626.", {"lap": 4, "lap_time_s": 65.626})
    fs.add("reference", "Reference lap for comparisons: lap 4 (this session) in 1:05.626.")
    return fs


async def test_switchable_hot_swaps_on_settings_change_without_new_objects(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    factory = FakeFactory()
    sw = SwitchableProvider(store, sec, factory=factory, retire_grace_s=0)
    engineer = RaceEngineer(sw)
    a1 = await engineer.answer("best lap?", _sheet())
    assert not a1.fallback and factory.calls("llamacpp")  # env defaults: local llama.cpp
    store.replace(SECTION, {"enabled": True, "primary": {"provider": "ollama", "model": "qwen3:8b"}})
    a2 = await engineer.answer("best lap?", _sheet())
    assert not a2.fallback and a2.model == "qwen3:8b" and engineer.provider is sw
    assert len(factory.calls("ollama")) == 1
    store.replace(SECTION, {"enabled": False, "primary": {"provider": "ollama", "model": "qwen3:8b"}})
    a3 = await engineer.answer("best lap?", _sheet())
    assert a3.fallback and "turned off" in a3.grounding_issues[0]
    await sw.aclose()


async def test_purpose_routing_picks_the_radio_model(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    store.replace(SECTION, _cloud_cfg())
    factory = FakeFactory()
    sw = SwitchableProvider(store, sec, factory=factory)
    radio = sw.for_purpose("radio")
    r1 = await sw.chat([{"role": "user", "content": "q"}])
    r2 = await radio.chat([{"role": "user", "content": "q"}])
    assert (r1.model, r2.model) == ("claude-opus-5-5", "claude-haiku-5-5")
    assert factory.built[0].build.api_key == ANTHROPIC_KEY
    usage = sw.usage()["today"]["by_model"]
    assert {r["model"]: r["by_purpose"] for r in usage} == {
        "claude-opus-5-5": {"engineer": 1},
        "claude-haiku-5-5": {"radio": 1},
    }
    await sw.aclose()


async def test_fallback_provider_answers_when_primary_fails(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    store.replace(SECTION, _cloud_cfg())
    factory = FakeFactory({"anthropic": [LLMUnavailable("Anthropic API error 529: overloaded")]})
    sw = SwitchableProvider(store, sec, factory=factory)
    res = await sw.chat([{"role": "user", "content": "q"}])
    assert factory.calls("llamacpp") and res.model == "auto"
    rows = {r["provider"]: r for r in sw.usage()["today"]["by_model"]}
    assert rows["anthropic"]["errors"] == 1 and rows["llamacpp"]["calls"] == 1
    await sw.aclose()


async def test_cloud_needs_enable_and_acknowledgement(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cloud AI is off"):
        parse_config(_cloud_cfg(privacy={"cloud_enabled": False}))
    with pytest.raises(ConfigError, match="not been acknowledged"):
        parse_config(_cloud_cfg(privacy={"cloud_enabled": True, "notice_version": 0}))
    # A hand-edited settings file cannot bypass it: invalid -> defaults (local) with a visible error.
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    store.replace(SECTION, _cloud_cfg(privacy={"cloud_enabled": True, "notice_version": 0}))
    factory = FakeFactory()
    sw = SwitchableProvider(store, sec, factory=factory)
    assert sw.status()["error"] and sw.config.primary.provider == "llamacpp"
    # And the runtime check holds even for a config object that skipped validation.
    unvalidated = LLMConfig(primary=ProviderSpec("anthropic", model="claude-haiku-5-5"), cloud_enabled=False)
    sw2 = SwitchableProvider(SettingsStore(tmp_path / "other.json"), sec, defaults=unvalidated, factory=factory)
    with pytest.raises(LLMUnavailable, match="cloud AI is off"):
        await sw2.chat([{"role": "user", "content": "q"}])
    assert not factory.calls("anthropic")
    await sw.aclose()
    await sw2.aclose()


async def test_missing_key_blocks_cloud_with_a_clear_reason(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    store.replace(SECTION, _cloud_cfg(fallback=None))
    sw = SwitchableProvider(store, sec, factory=FakeFactory())
    with pytest.raises(LLMUnavailable, match="no API key saved \\(anthropic_api_key\\)"):
        await sw.chat([{"role": "user", "content": "q"}])
    await sw.aclose()


async def test_daily_budget_blocks_cloud_and_survives_restart(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    store.replace(SECTION, _cloud_cfg(budget={"daily_usd": 0.01}))
    factory = FakeFactory()
    usage_path = tmp_path / "llm_usage.json"
    sw = SwitchableProvider(store, sec, factory=factory, usage_path=usage_path)
    first = await sw.chat([{"role": "user", "content": "q"}])  # 1000 in / 500 out on Opus 5.5 = $0.014
    assert first.model == "claude-opus-5-5"
    second = await sw.chat([{"role": "user", "content": "q"}])
    assert second.model == "auto"  # cloud blocked -> local fallback answered
    u = sw.usage()
    assert u["budget"]["reached"] and u["budget"]["spent_today_usd"] == pytest.approx(0.014)
    assert "daily cloud budget reached" in u["last_block"]["reason"]
    await sw.aclose()
    # restart: the ledger is on disk, so the cap still holds
    sw2 = SwitchableProvider(store, sec, factory=FakeFactory(), usage_path=usage_path)
    store.replace(SECTION, _cloud_cfg(budget={"daily_usd": 0.01}, fallback=None))
    with pytest.raises(LLMUnavailable, match=r"daily cloud budget reached \(\$0\.01 of \$0\.01 today\)"):
        await sw2.chat([{"role": "user", "content": "q"}])
    await sw2.aclose()


async def test_budget_with_unknown_price_blocks_instead_of_running_unmetered(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("openai_api_key", "sk-openai-test-key-000000")
    cfg = _cloud_cfg(primary={"provider": "openai", "model": "gpt-test"}, fallback=None, budget={"daily_usd": 5.0})
    store.replace(SECTION, cfg)
    sw = SwitchableProvider(store, sec, factory=FakeFactory())
    with pytest.raises(LLMUnavailable, match="no price is known for gpt-test"):
        await sw.chat([{"role": "user", "content": "q"}])
    store.replace(SECTION, {**cfg, "prices": {"gpt-test": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}})
    await sw.chat([{"role": "user", "content": "q"}])
    assert sw.usage()["today"]["cloud_cost_usd"] == pytest.approx((1000 * 1.0 + 500 * 2.0) / 1e6)
    await sw.aclose()


def test_name_redaction_rules() -> None:
    names = ["Sam", "Alex Racer", "Alex", "Driver", "Max"]
    text, n = redact_names("Driver: Alex Racer. Sam's T3 is slow; Alex pits. max speed 312. DRIVER: hi", names)
    assert text == "Driver: the driver. the driver's T3 is slow; the driver pits. max speed 312. DRIVER: hi"
    assert n == 3
    assert redact_names("Samantha and Sam", ["Sam"]) == ("Samantha and the driver", 1)


async def test_driver_names_redacted_for_cloud_only_and_toggleable(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    store.replace(SECTION, _cloud_cfg())
    factory = FakeFactory()
    sw = SwitchableProvider(store, sec, factory=factory, names=lambda: ["Sam", "Driver"])
    ans = await RaceEngineer(sw).answer("How was Sam's best lap?", _sheet())
    sent = json.dumps(factory.calls("anthropic")[0]["messages"])
    assert "Sam" not in sent and "the driver (beginner level)" in sent and "DRIVER:" in sent
    assert ans.model == "claude-opus-5-5"
    preview = sw.last_request()
    assert preview is not None and preview["driver_names_redacted"] == 2 and "Sam" not in json.dumps(preview)
    # local providers see the real names; redaction can be turned off for cloud
    local = SwitchableProvider(SettingsStore(tmp_path / "l.json"), sec, factory=factory, names=lambda: ["Sam"])
    await RaceEngineer(local).answer("How was Sam's best lap?", _sheet())
    assert "Sam" in json.dumps(factory.calls("llamacpp")[-1]["messages"])
    privacy = {"cloud_enabled": True, "notice_version": PRIVACY_NOTICE_VERSION, "redact_driver_names": False}
    store.replace(SECTION, _cloud_cfg(privacy=privacy))
    await RaceEngineer(sw).answer("How was Sam's best lap?", _sheet())
    assert "Sam" in json.dumps(factory.calls("anthropic")[-1]["messages"])
    msgs, n = redact_messages([{"role": "user", "content": [{"type": "text", "text": "Sam"}]}], ["Sam"])
    assert msgs[0]["content"][0]["text"] == "the driver" and n == 1
    await sw.aclose()
    await local.aclose()


def test_https_enforced_for_cloud_and_local_rules() -> None:
    with pytest.raises(ConfigError, match="must use https"):
        parse_config(_cloud_cfg(primary={"provider": "openai", "model": "m", "base_url": "http://api.openai.com/v1"}))
    with pytest.raises(ConfigError, match="must use https"):  # custom host on the internet = cloud
        parse_config(_cloud_cfg(primary={"provider": "custom", "model": "m", "base_url": "http://llm.example.com/v1"}))
    with pytest.raises(ConfigError, match="credentials"):
        check_base_url("https://user:secret@api.example.com/v1", cloud=True)
    with pytest.raises(ConfigError, match="query string"):
        check_base_url("https://api.example.com/v1?key=abc", cloud=True)
    with pytest.raises(ConfigError, match="http:// or https://"):
        check_base_url("ftp://127.0.0.1/v1", cloud=False)
    ok = parse_config({"primary": {"provider": "custom", "base_url": "http://192.168.1.20:11434/v1"}, "privacy": {}})
    assert ok.primary.location == "local" and ok.primary.model is None  # local servers may auto-pick a model
    # a "local" preset pointed at a public host becomes cloud: https + cloud consent required
    with pytest.raises(ConfigError, match="https"):
        parse_config({"primary": {"provider": "ollama", "base_url": "http://ollama.example.com/v1"}})
    with pytest.raises(ConfigError, match="cloud AI is off"):
        parse_config({"primary": {"provider": "ollama", "base_url": "https://ollama.example.com/v1", "model": "m"}})


@pytest.mark.parametrize(
    ("host", "local"),
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("192.168.1.20", True),
        ("10.0.0.5", True),
        ("100.101.102.103", True),  # tailnet
        ("studio.tail1234.ts.net", True),
        ("mac-studio.local", True),
        ("studio", True),
        ("::1", True),
        ("api.anthropic.com", False),
        ("8.8.8.8", False),
        ("ollama.example.com", False),
    ],
)
def test_is_local_host(host: str, local: bool) -> None:
    assert is_local_host(host) is local


@pytest.mark.usefixtures("no_pitwall_env")
def test_env_defaults_become_the_initial_config(tmp_path: Path) -> None:
    s = Settings(_env_file=None, data_dir=tmp_path, llm_model="qwen", llm_max_tokens=300, llm_timeout_s=45)
    cfg = config_from_settings(s)
    assert cfg.primary.provider == "llamacpp" and cfg.primary.url == "http://127.0.0.1:8081/v1"
    assert (cfg.primary.model, cfg.primary.max_tokens, cfg.primary.timeout_s) == ("qwen", 300, 45)
    assert not cfg.cloud_enabled


async def test_engineer_still_answers_deterministically_when_every_provider_fails(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    store.replace(SECTION, _cloud_cfg())
    down = LLMUnavailable("connection refused")
    factory = FakeFactory({"anthropic": [down, down], "llamacpp": [down, down]})
    sw = SwitchableProvider(store, sec, factory=factory)
    ans = await RaceEngineer(sw).answer("What was my best lap?", _sheet())
    assert (
        ans.fallback and ans.grounded and "1:05.626" in ans.text and "[F2]" in ans.cited_text and "[F" not in ans.text
    )
    assert "primary (Anthropic Claude)" in ans.grounding_issues[0] and "fallback" in ans.grounding_issues[0]
    await sw.aclose()


async def test_old_clients_are_closed_after_a_swap(tmp_path: Path) -> None:
    import asyncio

    store, sec = _stores(tmp_path)
    factory = FakeFactory()
    sw = SwitchableProvider(store, sec, factory=factory, retire_grace_s=0)
    await sw.chat([{"role": "user", "content": "q"}])
    old = factory.built[0]
    store.replace(SECTION, {"primary": {"provider": "lmstudio"}})
    for _ in range(20):
        if old.closed:
            break
        await asyncio.sleep(0.01)
    assert old.closed
    await sw.aclose()


# =============================================================================================== API
def _client(tmp_path: Path, factory: FakeFactory | None = None) -> tuple[TestClient, SwitchableProvider]:
    store, sec = _stores(tmp_path)
    sw = SwitchableProvider(store, sec, factory=factory or FakeFactory(), usage_path=tmp_path / "usage.json")
    app = FastAPI()
    app.include_router(router)
    app.state.llm = sw
    return TestClient(app), sw


def _api_cfg(**privacy: Any) -> dict[str, Any]:
    return {
        "enabled": True,
        "primary": {"provider": "anthropic", "models": {"engineer": "claude-opus-5-5", "radio": "claude-haiku-5-5"}},
        "fallback": {"provider": "llamacpp"},
        "privacy": {"cloud_enabled": True, "acknowledged_notice_version": PRIVACY_NOTICE_VERSION, **privacy},
        "budget": {"daily_usd": 2.5},
    }


def test_api_never_returns_api_keys(tmp_path: Path) -> None:
    leaky = FakeFactory()
    original = leaky.__call__

    def build(b: ProviderBuild) -> FakeProvider:  # a provider that (wrongly) puts its key in the body
        p = original(b)
        if b.api_key:
            p.script.append(lambda _m: "Best lap 1:05.626 on lap 4 [F2].")
            p.build = ProviderBuild(b.preset, b.base_url, b.model, b.api_key, b.timeout_s, b.effort, b.name)
            orig_chat = p.chat

            async def chat(messages: list[dict[str, Any]], **kw: Any) -> LLMResult:
                res = await orig_chat(messages, **kw)
                p.last_request = {"body": {"debug_key": b.api_key, "messages": messages}}
                return res

            p.chat = chat  # type: ignore[method-assign]
        return p

    client, sw = _client(tmp_path, leaky)
    client.app.state.llm._factory = build  # type: ignore[attr-defined]
    middle = ANTHROPIC_KEY[15:40]
    responses: list[httpx2.Response] = [
        client.put("/api/llm/keys/anthropic_api_key", json={"value": ANTHROPIC_KEY}),
        client.put("/api/llm/keys/anthropic_api_key", json={"valu": ANTHROPIC_KEY}),  # malformed: no echo
        client.put("/api/llm/keys/anthropic_api_key", content=b'{"value": "' + ANTHROPIC_KEY.encode() + b' x"}'),
        client.put("/api/llm/keys/anthropic_api_key", content=ANTHROPIC_KEY.encode()),  # not JSON
        client.put("/api/llm/keys/not_a_key", json={"value": ANTHROPIC_KEY}),
        client.put("/api/llm/config", json=_api_cfg()),
        client.get("/api/llm/providers", params={"health": "true"}),
        client.post("/api/llm/test", json={"role": "primary", "purpose": "radio"}),
        client.post("/api/llm/models", json={"provider": "anthropic"}),
        client.get("/api/llm/usage"),
        client.get("/api/llm/last-request"),
        client.delete("/api/llm/keys/anthropic_api_key"),
    ]
    assert [r.status_code for r in responses] == [200, 422, 422, 422, 404, 200, 200, 200, 200, 200, 200, 200]
    for r in responses:
        assert ANTHROPIC_KEY not in r.text and middle not in r.text, r.request.url
    saved = responses[0].json()
    assert saved["saved"] and saved["masked"].startswith("sk-ant-") and saved["masked"].endswith("Zq9Z")
    last = responses[10].json()["last"]
    assert last["request"]["body"]["debug_key"] == "[redacted secret]" and last["model"] == "claude-haiku-5-5"
    assert sw.secrets.get("anthropic_api_key") is None


def test_api_config_validation_and_round_trip(tmp_path: Path) -> None:
    client, sw = _client(tmp_path)
    r = client.put("/api/llm/config", json=_api_cfg(acknowledged_notice_version=None))
    assert r.status_code == 422 and "acknowledge" in r.json()["detail"]
    bad_url = _api_cfg()
    bad_url["primary"] = {"provider": "openai", "base_url": "http://api.openai.com/v1", "model": "m"}
    r = client.put("/api/llm/config", json=bad_url)
    assert r.status_code == 422 and "https" in r.json()["detail"]
    r = client.put("/api/llm/config", json={**_api_cfg(), "primary": {"provider": "nope"}})
    assert r.status_code == 422 and "unknown provider" in r.json()["detail"]
    r = client.put("/api/llm/config", json={**_api_cfg(), "primary": {"provider": "anthropic"}})
    assert r.status_code == 422 and "choose a model" in r.json()["detail"]
    r = client.put("/api/llm/config", json=_api_cfg())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["config"]["primary"]["models"] == {"engineer": "claude-opus-5-5", "radio": "claude-haiku-5-5"}
    assert body["config"]["privacy"]["notice_acknowledged"] and body["config"]["privacy"]["acknowledged_at"]
    assert body["status"]["mode"] == "cloud" and body["status"]["providers"][0]["blocked"].startswith("no API key")
    assert sw.store.get(SECTION)["budget"] == {"daily_usd": 2.5}
    first_ack = body["config"]["privacy"]["acknowledged_at"]
    time.sleep(0.01)
    again = client.put("/api/llm/config", json=_api_cfg()).json()
    assert again["config"]["privacy"]["acknowledged_at"] == first_ack  # re-saving keeps the original timestamp


def test_api_test_endpoint_runs_the_real_engineer_path(tmp_path: Path) -> None:
    factory = FakeFactory({"llamacpp": ["Your best lap was 1:05.626 on lap 4 [F2]."]})
    client, _ = _client(tmp_path, factory)
    r = client.post("/api/llm/test", json={"role": "primary", "purpose": "engineer"})
    out = r.json()
    assert r.status_code == 200 and out["ok"] and out["grounded"] and not out["fallback"]
    assert out["health"]["ok"] and isinstance(out["answer_latency_ms"], int)
    assert "1:05.626" in out["answer"] and "sample" in out["note"]
    sent = json.dumps(factory.calls("llamacpp")[0]["messages"])
    assert "PITWALL CONNECTION TEST" in sent  # canned facts, never the driver's telemetry
    missing = client.post("/api/llm/test", json={"role": "fallback"})
    assert missing.status_code == 404


# =============================================================================================== review fixes
class RecordingFactory:
    """Builds the *real* providers (default_factory / AnthropicProvider) on mock transports and records every
    request that would have gone on the wire, so tests can prove what was (not) sent and with which key."""

    def __init__(self, openai_reply: Callable[[httpx.Request], httpx.Response] | None = None) -> None:
        self.builds: list[ProviderBuild] = []
        self.openai: list[httpx.Request] = []
        self.anthropic: list[httpx2.Request] = []
        self.openai_reply = openai_reply

    def __call__(self, b: ProviderBuild) -> Any:
        self.builds.append(b)
        if b.preset.kind == "anthropic":

            def ah(req: httpx2.Request) -> httpx2.Response:
                self.anthropic.append(req)
                if req.url.path == "/v1/models":
                    return httpx2.Response(200, json={"data": [], "has_more": False, "first_id": None, "last_id": None})
                return httpx2.Response(200, json=_message())

            assert b.api_key and b.model
            return AnthropicProvider(
                b.api_key, b.model, base_url=b.base_url, transport=httpx2.MockTransport(ah), max_retries=0
            )
        p = default_factory(b)
        assert isinstance(p, OpenAICompatibleProvider)

        def oh(req: httpx.Request) -> httpx.Response:
            self.openai.append(req)
            if self.openai_reply is not None and not req.url.path.endswith("/models"):
                return self.openai_reply(req)
            if req.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "m1"}]})
            body = json.loads(req.content)
            usage = {"prompt_tokens": 50, "completion_tokens": 5}
            return httpx.Response(
                200, json={"model": body["model"], "choices": [{"message": {"content": "ok"}}], "usage": usage}
            )

        p._client = httpx.AsyncClient(headers=p._client.headers, transport=httpx.MockTransport(oh))
        return p


async def test_cloud_vendor_keys_only_go_to_the_vendor_host(tmp_path: Path) -> None:
    for pid, url in (("anthropic", "https://attacker.example"), ("openai", "https://evil.example/v1")):
        with pytest.raises(ConfigError, match="keys are only sent there"):
            parse_config(_cloud_cfg(primary={"provider": pid, "model": "m", "base_url": url}))
    same_host = parse_config(
        _cloud_cfg(primary={"provider": "openai", "model": "m", "base_url": "https://api.openai.com/v1/"})
    )
    assert same_host.primary.url == "https://api.openai.com/v1"
    # The reviewer's exploit: cloud off, nothing acknowledged, a saved key, and a foreign base_url.
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    rec = RecordingFactory()
    sw = SwitchableProvider(store, sec, factory=rec)
    with pytest.raises(LLMUnavailable, match=r"api\.anthropic\.com"):
        await sw.list_models("anthropic", "https://attacker.example")
    assert rec.builds == [] and rec.anthropic == []  # nothing built, nothing sent
    await sw.list_models("anthropic")
    assert rec.anthropic[0].url.host == "api.anthropic.com" and rec.anthropic[0].headers["x-api-key"] == ANTHROPIC_KEY
    # Defence in depth: a config that skipped validation still cannot carry the key elsewhere.
    unvalidated = LLMConfig(
        primary=ProviderSpec("anthropic", base_url="https://attacker.example", model="claude-haiku-5-5"),
        cloud_enabled=True,
        notice_version=PRIVACY_NOTICE_VERSION,
    )
    sw2 = SwitchableProvider(SettingsStore(tmp_path / "o.json"), sec, defaults=unvalidated, factory=rec)
    with pytest.raises(LLMUnavailable, match="key is withheld"):
        await sw2.chat([{"role": "user", "content": "q"}])
    assert len(rec.anthropic) == 1
    await sw.aclose()
    await sw2.aclose()


def test_models_endpoint_cannot_be_driven_cross_site(tmp_path: Path) -> None:
    rec = RecordingFactory()
    client, sw = _client(tmp_path, rec)  # type: ignore[arg-type]
    sw.secrets.set("anthropic_api_key", ANTHROPIC_KEY)
    body = {"provider": "anthropic", "base_url": "https://attacker.example"}
    assert client.get("/api/llm/models", params=body).status_code == 405  # an <img src> cannot trigger it
    raw = json.dumps(body).encode()
    assert client.post("/api/llm/models", content=raw).status_code == 415  # no content type (simple request)
    plain = {"content-type": "text/plain"}
    assert client.post("/api/llm/models", content=raw, headers=plain).status_code == 415
    r = client.post("/api/llm/models", json=body)
    assert r.status_code == 200 and "api.anthropic.com" in r.json()["error"]
    assert rec.builds == [] and rec.anthropic == []
    assert client.post("/api/llm/test", content=b'{"role": "primary"}').status_code == 415


async def test_local_and_custom_keys_stay_with_their_own_endpoints(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("llm_api_key", "local-key-0123456789")
    sec.set("custom_api_key", "cloud-key-0123456789")
    custom, lan = "https://llm.example.com/v1", "http://192.168.1.20:8081/v1"
    store.replace(
        SECTION,
        _cloud_cfg(
            primary={"provider": "custom", "base_url": custom, "model": "big"},
            fallback={"provider": "llamacpp", "base_url": lan, "model": "qwen"},
        ),
    )
    rec = RecordingFactory()
    sw = SwitchableProvider(store, sec, factory=rec)
    assert key_name_for(PRESETS["custom"], custom) == "custom_api_key"
    assert key_name_for(PRESETS["custom"], lan) == key_name_for(PRESETS["llamacpp"], lan) == "llm_api_key"
    assert [s["key_name"] for s in sw.status()["providers"]] == ["custom_api_key", "llm_api_key"]

    def auth_of_listing(provider: str, url: str) -> str | None:
        sent = next(r for r in reversed(rec.openai) if str(r.url).startswith(url))
        auth: str | None = sent.headers.get("authorization")
        return auth

    for provider, url, expected in [
        ("custom", custom, "Bearer cloud-key-0123456789"),
        ("custom", "https://attacker.example/v1", None),  # not the saved URL: listed without any key
        ("custom", lan, None),  # custom at a LAN URL is not a saved custom URL
        ("llamacpp", lan, "Bearer local-key-0123456789"),
        ("llamacpp", "http://192.168.1.66:8000/v1", None),
        ("llamacpp", "http://127.0.0.1:8081/v1", "Bearer local-key-0123456789"),  # the preset's own default
    ]:
        await sw.list_models(provider, url)
        assert auth_of_listing(provider, url) == expected, (provider, url)
    await sw.chat([{"role": "user", "content": "q"}])
    sent = rec.openai[-1]
    assert str(sent.url) == f"{custom}/chat/completions" and sent.headers["authorization"].endswith(
        "cloud-key-0123456789"
    )
    await sw.aclose()


def _openai_reply(model: str, usage: dict[str, int] | None) -> Callable[[httpx.Request], httpx.Response]:
    def reply(req: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = {"model": model, "choices": [{"message": {"content": "Best lap 1:05.626 [F2]."}}]}
        if usage is not None:
            body["usage"] = usage
        return httpx.Response(200, json=body)

    return reply


async def test_budget_prices_the_served_snapshot_id(tmp_path: Path) -> None:
    """The reviewer's scenario on the real OpenAI-compatible provider: gpt-5 requested, gpt-5-2025-08-07 served."""
    store, sec = _stores(tmp_path)
    sec.set("openai_api_key", "sk-openai-test-key-000000")
    prices = {"gpt-5": {"input_per_mtok": 1.25, "output_per_mtok": 10.0}}
    store.replace(
        SECTION,
        _cloud_cfg(
            primary={"provider": "openai", "model": "gpt-5"}, fallback=None, budget={"daily_usd": 0.01}, prices=prices
        ),
    )
    big = {"prompt_tokens": 100_000, "completion_tokens": 100_000}
    rec = RecordingFactory(_openai_reply("gpt-5-2025-08-07", big))
    sw = SwitchableProvider(store, sec, factory=rec)
    first = await sw.chat([{"role": "user", "content": "q"}])
    assert first.model == "gpt-5-2025-08-07"
    for _ in range(4):
        with pytest.raises(LLMUnavailable, match="daily cloud budget reached"):
            await sw.chat([{"role": "user", "content": "q"}])
    assert len([r for r in rec.openai if r.url.path.endswith("/chat/completions")]) == 1
    u = sw.usage()
    assert u["budget"]["spent_today_usd"] == pytest.approx(0.125 + 1.0) and u["budget"]["reached"]
    assert u["today"]["unpriced_calls"] == 0
    cfg = sw.config
    priced = LLMConfig(prices={"gpt-5": cfg.prices["gpt-5"], "gpt-5-mini": type(cfg.prices["gpt-5"])(0.25, 2.0)})
    assert priced.price_for(cfg.primary, "gpt-5-mini-2025-08-07") == priced.prices["gpt-5-mini"]  # longest wins
    assert priced.price_for(cfg.primary, "gpt-50") is None  # prefix match needs the "-" boundary
    await sw.aclose()


async def test_cloud_call_without_token_counts_pauses_cloud_under_a_budget(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("openai_api_key", "sk-openai-test-key-000000")
    prices = {"gpt-test": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}
    store.replace(
        SECTION,
        _cloud_cfg(primary={"provider": "openai", "model": "gpt-test"}, budget={"daily_usd": 5.0}, prices=prices),
    )
    rec = RecordingFactory(_openai_reply("gpt-test", None))  # the provider reports no usage at all
    sw = SwitchableProvider(store, sec, factory=rec)
    assert (await sw.chat([{"role": "user", "content": "q"}])).model == "gpt-test"
    await sw.chat([{"role": "user", "content": "q"}])
    chats = [r.url.host for r in rec.openai if r.url.path.endswith("/chat/completions")]
    assert chats == ["api.openai.com", "127.0.0.1"]  # cloud paused -> the local fallback answered
    u = sw.usage()
    assert u["budget"]["unmetered_calls"] == 1 and u["budget"]["reached"]
    assert "spend is unknown" in u["last_block"]["reason"]
    await sw.aclose()


async def test_settings_change_during_a_call_governs_the_fallback(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    privacy = {"cloud_enabled": True, "notice_version": PRIVACY_NOTICE_VERSION}
    store.replace(
        SECTION,
        {
            "primary": {"provider": "llamacpp"},
            "fallback": {
                "provider": "anthropic",
                "models": {"engineer": "claude-haiku-5-5", "radio": "claude-haiku-5-5"},
            },
            "privacy": privacy,
        },
    )
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_then_fail(_m: list[dict[str, Any]]) -> str:
        started.set()
        await release.wait()
        raise LLMUnavailable("ReadTimeout: timed out")

    factory = FakeFactory({"llamacpp": [slow_then_fail]})
    sw = SwitchableProvider(store, sec, factory=factory, retire_grace_s=0)
    task = asyncio.create_task(sw.chat([{"role": "user", "content": "Driver: James. best lap?"}]))
    await started.wait()
    store.replace(SECTION, {"primary": {"provider": "llamacpp"}, "privacy": {"cloud_enabled": False}})
    assert not sw.config.cloud_enabled
    release.set()
    with pytest.raises(LLMUnavailable, match="timed out"):
        await task
    assert not [p for p in factory.built if p.build.preset.id == "anthropic"]  # never built, never called
    await sw.aclose()


async def test_redaction_fails_closed_when_driver_names_cannot_be_read(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    store.replace(SECTION, _cloud_cfg())
    reads: list[Any] = [RuntimeError("database is locked"), ["James"], RuntimeError("database is locked")]

    def names() -> list[str]:
        r = reads.pop(0) if reads else RuntimeError("database is locked")
        if isinstance(r, Exception):
            raise r
        return list(r)

    factory = FakeFactory()
    sw = SwitchableProvider(store, sec, factory=factory, names=names)
    msg = [{"role": "user", "content": "Driver: James. best lap?"}]
    await sw.chat(msg)  # never read successfully: the cloud is skipped, the local fallback answers
    assert not factory.calls("anthropic") and factory.calls("llamacpp")
    assert "driver names could not be read" in sw.usage()["last_block"]["reason"]
    await sw.chat(msg)  # names read: redacted cloud call
    assert "James" not in json.dumps(factory.calls("anthropic")[-1]["messages"])
    sw._names_at = -1e9  # cache expired and the re-read fails: the last good list is still used
    await sw.chat(msg)
    assert len(factory.calls("anthropic")) == 2 and "James" not in json.dumps(
        factory.calls("anthropic")[-1]["messages"]
    )
    sw.invalidate_names()  # a driver changed: the old list is no longer trusted
    await sw.chat(msg)
    assert len(factory.calls("anthropic")) == 2
    await sw.aclose()


async def test_providers_are_built_off_the_event_loop(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    store.replace(SECTION, _cloud_cfg())
    threads: list[bool] = []
    inner = FakeFactory()

    def factory(b: ProviderBuild) -> FakeProvider:
        threads.append(threading.current_thread() is threading.main_thread())
        return inner(b)

    sw = SwitchableProvider(store, sec, factory=factory)
    await sw.chat([{"role": "user", "content": "q"}])
    await sw.health("radio")
    await sw.list_models("anthropic")
    assert len(threads) == 3 and not any(threads)  # e.g. the ~0.7 s first `import anthropic` never blocks the loop
    await sw.aclose()


async def test_billed_failures_are_counted_and_cut_off_answers_never_returned(tmp_path: Path) -> None:
    def cut(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json=_message("Your best lap was 1:05.626 [F2], which is", stop_reason="max_tokens", usage=(700, 1374))
        )

    p = _anthropic(cut)
    with pytest.raises(LLMUnavailable, match="cut off by max_tokens mid-answer") as ei:
        await p.chat([{"role": "user", "content": "q"}])
    assert ei.value.usage == BilledUsage("claude-haiku-5-5", 700, 1374) and not p.breaker_open
    await p.aclose()
    store, sec = _stores(tmp_path)
    sec.set("anthropic_api_key", ANTHROPIC_KEY)
    store.replace(SECTION, _cloud_cfg())
    refused = LLMUnavailable("declined", usage=BilledUsage("claude-opus-5-5", 1000, 1374))
    sw = SwitchableProvider(store, sec, factory=FakeFactory({"anthropic": [refused]}))
    await sw.chat([{"role": "user", "content": "q"}])  # refused (billed) -> local fallback
    row = next(r for r in sw.usage()["today"]["by_model"] if r["provider"] == "anthropic")
    assert row["errors"] == 1 and (row["prompt_tokens"], row["completion_tokens"]) == (1000, 1374)
    assert row["cost_usd"] == pytest.approx((1000 * 4.0 + 1374 * 20.0) / 1e6)
    assert sw.ledger.cloud_cost_today() == pytest.approx(row["cost_usd"])
    await sw.aclose()


async def test_deploy_time_key_from_env_file_is_used(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    factory = FakeFactory()
    sw = SwitchableProvider(store, sec, factory=factory, default_keys={"llm_api_key": "dotenv-key-0123456789"})
    await sw.chat([{"role": "user", "content": "q"}])
    assert factory.built[-1].build.api_key == "dotenv-key-0123456789"
    assert sw.key_source("llm_api_key") == "settings" and sw.status()["providers"][0]["key_set"]
    sec.set("llm_api_key", "saved-key-0123456789")  # a key saved on the settings page wins
    sw.reload()
    await sw.chat([{"role": "user", "content": "q"}])
    assert factory.built[-1].build.api_key == "saved-key-0123456789" and sw.key_source("llm_api_key") == "file"
    await sw.aclose()


def test_notice_acknowledgement_must_be_for_the_version_shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pitwall.ai.provider_registry as registry
    import pitwall.api.routes_llm as routes

    client, sw = _client(tmp_path)
    assert client.put("/api/llm/config", json=_api_cfg()).status_code == 200
    shown = PRIVACY_NOTICE_VERSION
    monkeypatch.setattr(registry, "PRIVACY_NOTICE_VERSION", shown + 1)  # the notice text changes...
    monkeypatch.setattr(routes, "PRIVACY_NOTICE_VERSION", shown + 1)
    stale = client.put("/api/llm/config", json={**_api_cfg(), "budget": {"daily_usd": 3.0}})  # ...an old tab saves
    assert stale.status_code == 409 and "changed" in stale.json()["detail"]
    assert sw.store.get(SECTION)["privacy"]["notice_version"] == shown  # not re-acknowledged
    fresh = client.put("/api/llm/config", json=_api_cfg(acknowledged_notice_version=shown + 1))
    assert fresh.status_code == 200 and fresh.json()["config"]["privacy"]["notice_acknowledged"]


async def test_served_id_without_a_price_falls_back_to_the_configured_models_price(tmp_path: Path) -> None:
    store, sec = _stores(tmp_path)
    sec.set("gemini_api_key", "gemini-test-key-0000000")
    prices = {"gemini-x": {"input_per_mtok": 2.0, "output_per_mtok": 4.0}}
    cfg = _cloud_cfg(primary={"provider": "gemini", "model": "gemini-x"}, budget={"daily_usd": 1.0}, prices=prices)
    store.replace(SECTION, cfg)
    served = LLMResult("ok [F2]", "models/gemini-x", 3, prompt_tokens=1000, completion_tokens=500)
    sw = SwitchableProvider(store, sec, factory=FakeFactory({"gemini": [served]}))
    await sw.chat([{"role": "user", "content": "q"}])
    assert sw.ledger.cloud_cost_today() == pytest.approx((1000 * 2.0 + 500 * 4.0) / 1e6)
    assert sw.usage()["today"]["unpriced_calls"] == 0
    await sw.aclose()
