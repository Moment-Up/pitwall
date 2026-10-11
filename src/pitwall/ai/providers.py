"""Inference provider abstraction.

``OpenAICompatibleProvider`` works with llama.cpp ``llama-server``, LM Studio, Ollama (/v1), MLX servers, vLLM
and hosted OpenAI-compatible APIs (OpenAI, OpenRouter, Google Gemini's OpenAI endpoint, Groq, Mistral...).
``AnthropicProvider`` talks to Claude through the official ``anthropic`` SDK (Messages API). Swap providers via
configuration (``ai/provider_registry.py``); nothing else in the app depends on the model vendor.

A circuit breaker stops the app hammering a dead endpoint: after ``failure_threshold`` consecutive failures
calls fail fast for ``cooldown_s``. Callers must always have a deterministic fallback (the AI engineer does).
Every provider maps its own errors to ``LLMUnavailable`` so callers handle one exception type.

Each provider keeps ``last_request``: the body of the most recent request *as sent on the wire*, without HTTP
headers (so never an API key). The settings page shows it so the user can see exactly what left the machine.
"""

from __future__ import annotations

import copy
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

import httpx

if TYPE_CHECKING:
    import httpx2
    from anthropic.types import Message
    from anthropic.types.beta import BetaMessage

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BilledUsage:
    """Tokens a provider billed for a call that still produced no usable answer (a refusal, a cut-off answer)."""

    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


class LLMUnavailable(RuntimeError):
    """The model cannot answer; callers use their deterministic answer instead.

    ``usage`` is set only when the provider billed the failed call anyway (e.g. a Claude refusal or an answer cut
    off by ``max_tokens``), so cost accounting and the daily budget still count it. ``LLMUnavailable("reason")``
    behaves exactly as before.
    """

    def __init__(self, *args: object, usage: BilledUsage | None = None) -> None:
        super().__init__(*args)
        self.usage = usage


@dataclass(slots=True)
class LLMResult:
    text: str
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw_timings: dict[str, Any] | None = None


@dataclass(slots=True)
class ProviderHealth:
    ok: bool
    base_url: str
    model: str | None
    detail: str
    latency_ms: int | None = None
    context_tokens: int | None = None
    breaker_open: bool = False


class LLMProvider(Protocol):
    name: str

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 300,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult: ...

    async def health(self) -> ProviderHealth: ...


class ManagedProvider(LLMProvider, Protocol):
    """What the provider registry needs on top of ``LLMProvider``: model listing, the last wire request and
    an explicit close for the HTTP client."""

    last_request: dict[str, Any] | None

    async def list_models(self) -> list[dict[str, Any]]: ...

    async def aclose(self) -> None: ...


class CircuitBreaker:
    """Consecutive-failure breaker shared by the cloud providers (same semantics as OpenAICompatibleProvider)."""

    def __init__(self, failure_threshold: int = 3, cooldown_s: float = 30.0, label: str = "LLM") -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.label = label
        self._failures = 0
        self._open_until = 0.0

    @property
    def open(self) -> bool:
        return time.monotonic() < self._open_until

    def record(self, ok: bool) -> None:
        if ok:
            self._failures = 0
            self._open_until = 0.0
        else:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._open_until = time.monotonic() + self.cooldown_s
                log.warning("%s circuit breaker open for %.0f s", self.label, self.cooldown_s)


class OpenAICompatibleProvider:
    """OpenAI chat-completions wire format.

    The keyword-only options after ``transport`` adapt the request to stricter hosted APIs; their defaults keep
    the original llama.cpp-oriented behaviour exactly:

    - ``cache_prompt``: llama.cpp's KV-cache reuse flag. Hosted APIs (OpenAI, Groq, Gemini) reject unknown body
      fields with a 400, so cloud presets turn it off.
    - ``send_temperature``: OpenAI's reasoning models (o-series, GPT-5) accept only the default temperature.
    - ``max_tokens_field``: OpenAI deprecated ``max_tokens`` for ``max_completion_tokens`` (reasoning models
      reject the old name).
    - ``reasoning_headroom_tokens``: added to the wire token limit for models whose hidden reasoning counts
      against it, so a short answer is not cut off after the reasoning.
    - ``probe_health_endpoint``: llama.cpp exposes ``/health`` next to ``/v1``; hosted APIs don't, so their
      health check lists ``/models`` instead (which also verifies the API key).
    """

    def __init__(
        self,
        base_url: str,
        model: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 90.0,
        failure_threshold: int = 3,
        cooldown_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        name: str = "openai-compatible",
        extra_headers: Mapping[str, str] | None = None,
        cache_prompt: bool = True,
        send_temperature: bool = True,
        max_tokens_field: Literal["max_tokens", "max_completion_tokens"] = "max_tokens",
        reasoning_headroom_tokens: int = 0,
        probe_health_endpoint: bool = True,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.timeout_s = timeout_s
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        headers.update(extra_headers or {})
        self._client = httpx.AsyncClient(headers=headers, timeout=timeout_s, transport=transport)
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._failures = 0
        self._open_until = 0.0
        self._context_tokens: int | None = None
        self.cache_prompt = cache_prompt
        self.send_temperature = send_temperature
        self.max_tokens_field = max_tokens_field
        self.reasoning_headroom_tokens = max(0, reasoning_headroom_tokens)
        self.probe_health_endpoint = probe_health_endpoint
        self.last_request: dict[str, Any] | None = None

    @property
    def breaker_open(self) -> bool:
        return time.monotonic() < self._open_until

    def _record(self, ok: bool) -> None:
        if ok:
            self._failures = 0
            self._open_until = 0.0
        else:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._open_until = time.monotonic() + self.cooldown_s
                log.warning("LLM circuit breaker open for %.0f s", self.cooldown_s)

    async def model_id(self) -> str:
        if self._model:
            return self._model
        r = await self._client.get(f"{self.base_url}/models", timeout=10)
        r.raise_for_status()
        data = r.json().get("data") or []
        if not data:
            raise LLMUnavailable("endpoint reports no models")
        self._model = str(data[0]["id"])
        meta = data[0].get("meta") or {}
        if isinstance(meta, dict) and meta.get("n_ctx"):
            self._context_tokens = int(meta["n_ctx"])
        return self._model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 300,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult:
        if self.breaker_open:
            raise LLMUnavailable("circuit breaker open (recent failures)")
        t0 = time.perf_counter()
        try:
            model = await self.model_id()
            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                self.max_tokens_field: max_tokens + self.reasoning_headroom_tokens,
            }
            if self.send_temperature:
                body["temperature"] = temperature
            body["stream"] = False
            if self.cache_prompt:
                body["cache_prompt"] = True  # llama.cpp: reuse KV cache for the shared prefix (ignored elsewhere)
            if json_schema is not None:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": json_schema},
                }
            self.last_request = {"endpoint": f"POST {self.base_url}/chat/completions", "body": copy.deepcopy(body)}
            r = await self._client.post(
                f"{self.base_url}/chat/completions", json=body, timeout=timeout_s or self.timeout_s
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError, KeyError) as e:
            self._record(False)
            raise LLMUnavailable(f"{type(e).__name__}: {e}") from e
        self._record(True)
        msg = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        return LLMResult(
            text=(msg.get("content") or "").strip(),
            model=str(data.get("model") or model),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            tool_calls=msg.get("tool_calls") or [],
            raw_timings=data.get("timings"),
        )

    async def health(self) -> ProviderHealth:
        t0 = time.perf_counter()
        if not self.probe_health_endpoint:
            return await self._health_via_models(t0)
        try:
            model = await self.model_id()
            r = await self._client.get(f"{self.base_url.removesuffix('/v1')}/health", timeout=5)
            detail = "ok" if r.status_code == 200 else f"health endpoint returned {r.status_code}"
            ok = r.status_code == 200 or r.status_code == 404  # not every server has /health
            if r.status_code == 404:
                detail = "ok (no /health endpoint; /models responded)"
        except Exception as e:
            return ProviderHealth(
                False, self.base_url, self._model, f"{type(e).__name__}: {e}", breaker_open=self.breaker_open
            )
        return ProviderHealth(
            ok,
            self.base_url,
            model,
            detail,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            context_tokens=self._context_tokens,
            breaker_open=self.breaker_open,
        )

    async def _health_via_models(self, t0: float) -> ProviderHealth:
        """Hosted APIs: an authenticated ``GET /models`` proves reachability and (mostly) the key. No tokens used."""
        try:
            r = await self._client.get(f"{self.base_url}/models", timeout=10)
        except httpx.HTTPError as e:
            return ProviderHealth(
                False, self.base_url, self._model, f"{type(e).__name__}: {e}", breaker_open=self.breaker_open
            )
        latency = int((time.perf_counter() - t0) * 1000)
        if r.status_code in (401, 403):
            detail = f"API key rejected ({r.status_code})"
        elif r.status_code == 200:
            detail = "ok"
        else:
            detail = f"/models returned {r.status_code}"
        return ProviderHealth(
            r.status_code == 200, self.base_url, self._model, detail, latency_ms=latency, breaker_open=self.breaker_open
        )

    async def list_models(self) -> list[dict[str, Any]]:
        """Models the endpoint reports (``GET /models``), as ``[{"id": ...}, ...]`` sorted by id."""
        try:
            r = await self._client.get(f"{self.base_url}/models", timeout=15)
            r.raise_for_status()
            data = r.json().get("data") or []
        except (httpx.HTTPError, ValueError, AttributeError) as e:
            raise LLMUnavailable(f"{type(e).__name__}: {e}") from e
        out = [{"id": str(m["id"])} for m in data if isinstance(m, dict) and m.get("id")]
        return sorted(out, key=lambda m: m["id"])

    async def aclose(self) -> None:
        await self._client.aclose()


# --------------------------------------------------------------------------------------------- Anthropic
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
# Server-side refusal fallback ("default" form): on a safety-classifier decline the API re-runs the request on
# the model Anthropic recommends for that category, inside the same call. Only these models accept it; Claude
# Haiku 5.5 has no server-side fallback. Claude API only (not Bedrock/Vertex/Foundry).
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"
ANTHROPIC_SERVER_FALLBACK_MODELS = frozenset(
    {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
)
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class AnthropicProvider:
    """Claude via the Messages API, using the official ``anthropic`` SDK (async client).

    Request shaping, and why (verified against platform.claude.com docs, 2026-10):

    - ``system`` messages are lifted into the top-level ``system`` field; the Messages API takes the system prompt
      there, not as a message. Leading assistant turns are dropped (the first message must be from the user).
    - No ``temperature``: Claude Opus 5.5, Sonnet 5.5 and Haiku 5.5 reject non-default sampling values with a
      400. The engineer does not rely on low temperature for correctness - every answer passes the grounding
      check or is replaced by the deterministic answer.
    - No ``thinking`` field: on the current models omitting it means adaptive thinking (and Opus 5.5 cannot
      disable thinking at all). ``output_config.effort`` is the latency/cost control; ``low`` suits "rephrase
      these facts" and keeps radio answers fast.
    - Thinking tokens count toward ``max_tokens``, so ``reasoning_headroom_tokens`` is added to the caller's
      answer budget; otherwise a 350-token radio answer can be consumed by thinking before any text appears.
    - Structured output: ``output_config.format = {"type": "json_schema", "schema": ...}`` (the deprecated
      top-level ``output_format`` is not used). The JSON arrives as the text block.
    - Refusals (``stop_reason == "refusal"``) and any answer stopped by ``max_tokens`` raise ``LLMUnavailable``
      without tripping the breaker - the endpoint is healthy, the caller should just use its deterministic answer.
      A cut-off answer is never returned, even with some text: the radio would speak half a sentence (which could
      still pass grounding). Both cases were billed, so the exception carries the usage (``BilledUsage``).
    - The SDK is given the API key and base URL explicitly so it never picks up ``ANTHROPIC_API_KEY``,
      ``ANTHROPIC_BASE_URL`` or an ``ant`` CLI profile from the environment: keys live only in pitwall's
      SecretStore.
    - If the API rejects the server-side fallback opt-in or ``effort`` for a model (400 naming the field), the
      request is retried once without it and the field stays off for that model.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        timeout_s: float = 60.0,
        effort: Effort | None = "low",
        reasoning_headroom_tokens: int = 1024,
        refusal_fallback: bool = True,
        max_retries: int = 1,
        failure_threshold: int = 3,
        cooldown_s: float = 30.0,
        transport: httpx2.AsyncBaseTransport | None = None,
        name: str = "anthropic",
    ) -> None:
        # Deferred: keeps start-up light for local-only setups. The first import takes ~0.7 s, so construct this
        # class off the event loop (the provider registry builds providers with asyncio.to_thread).
        import anthropic

        if not api_key:
            raise ValueError("an Anthropic API key is required")
        if not model:
            raise ValueError("an Anthropic model id is required")
        self.name = name
        self.base_url = (base_url or ANTHROPIC_DEFAULT_BASE_URL).rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.effort: Effort | None = effort
        self.reasoning_headroom_tokens = max(0, reasoning_headroom_tokens)
        self.refusal_fallback = refusal_fallback
        self._breaker = CircuitBreaker(failure_threshold, cooldown_s, label="Anthropic")
        http_client = anthropic.DefaultAsyncHttpxClient(transport=transport) if transport is not None else None
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=self.base_url,
            timeout=timeout_s,
            max_retries=max_retries,
            http_client=http_client,
        )
        self._no_fallback: set[str] = set()  # models whose 400 said the fallback opt-in is not accepted
        self._no_effort: set[str] = set()
        self._context_tokens: int | None = None
        self.last_request: dict[str, Any] | None = None

    @property
    def breaker_open(self) -> bool:
        return self._breaker.open

    @staticmethod
    def split_messages(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        """OpenAI-style messages -> (system prompt, Messages API turns).

        System messages are joined into the system prompt. Turns keep their order; consecutive same-role turns
        are merged (the API would combine them anyway) and leading assistant turns are dropped because a
        conversation must start with the user.
        """
        system: list[str] = []
        turns: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            text = _content_text(m.get("content"))
            if role == "system":
                if text:
                    system.append(text)
                continue
            if role not in ("user", "assistant") or not text:
                continue
            if not turns and role == "assistant":
                continue
            if turns and turns[-1]["role"] == role:
                turns[-1]["content"] += "\n\n" + text
            else:
                turns.append({"role": role, "content": text})
        return ("\n\n".join(system) or None), turns

    def _request(
        self, messages: list[dict[str, Any]], max_tokens: int, json_schema: dict[str, Any] | None
    ) -> tuple[dict[str, Any], bool]:
        system, turns = self.split_messages(messages)
        if not turns or turns[-1]["role"] != "user":
            raise LLMUnavailable("conversation must end with a user turn (assistant prefill is not supported)")
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens + self.reasoning_headroom_tokens,
            "messages": turns,
        }
        if system:
            params["system"] = system
        output_config: dict[str, Any] = {}
        if self.effort and self.model not in self._no_effort:
            output_config["effort"] = self.effort
        if json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        if output_config:
            params["output_config"] = output_config
        use_fallback = (
            self.refusal_fallback
            and self.model in ANTHROPIC_SERVER_FALLBACK_MODELS
            and self.model not in self._no_fallback
            and self.base_url == ANTHROPIC_DEFAULT_BASE_URL
        )
        return params, use_fallback

    async def _send(self, params: dict[str, Any], use_fallback: bool, timeout_s: float) -> Message | BetaMessage:
        wire = copy.deepcopy(params)
        if use_fallback:
            wire["fallbacks"] = "default"
        self.last_request = {
            "endpoint": f"POST {self.base_url}/v1/messages",
            "anthropic_beta": [ANTHROPIC_FALLBACK_BETA] if use_fallback else [],
            "body": wire,
        }
        from anthropic import omit

        system = params.get("system")
        output_config = params.get("output_config")
        if use_fallback:
            return await self._client.beta.messages.create(
                model=params["model"],
                max_tokens=params["max_tokens"],
                messages=params["messages"],
                system=system if system is not None else omit,
                output_config=output_config if output_config is not None else omit,
                betas=[ANTHROPIC_FALLBACK_BETA],
                fallbacks="default",
                timeout=timeout_s,
            )
        return await self._client.messages.create(
            model=params["model"],
            max_tokens=params["max_tokens"],
            messages=params["messages"],
            system=system if system is not None else omit,
            output_config=output_config if output_config is not None else omit,
            timeout=timeout_s,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 300,
        temperature: float = 0.2,  # accepted for interface compatibility; never sent (see class docstring)
        json_schema: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult:
        import anthropic

        if self._breaker.open:
            raise LLMUnavailable("circuit breaker open (recent failures)")
        t0 = time.perf_counter()
        params, use_fallback = self._request(messages, max_tokens, json_schema)
        timeout = timeout_s or self.timeout_s
        try:
            try:
                resp = await self._send(params, use_fallback, timeout)
            except anthropic.BadRequestError as e:
                # One adaptive retry when the API rejects an optional field we chose to send.
                msg = str(e.message).lower()
                if use_fallback and "fallback" in msg:
                    log.warning("Anthropic rejected the refusal-fallback opt-in for %s; continuing without", self.model)
                    self._no_fallback.add(self.model)
                    resp = await self._send(params, False, timeout)
                elif "effort" in msg and "output_config" in params and "effort" in params["output_config"]:
                    log.warning("Anthropic rejected effort for %s; continuing without", self.model)
                    self._no_effort.add(self.model)
                    params["output_config"].pop("effort")
                    if not params["output_config"]:
                        params.pop("output_config")
                    resp = await self._send(params, use_fallback, timeout)
                else:
                    raise
        except anthropic.AuthenticationError as e:
            self._breaker.record(False)
            raise LLMUnavailable("Anthropic rejected the API key (401)") from e
        except anthropic.PermissionDeniedError as e:
            self._breaker.record(False)
            raise LLMUnavailable(f"Anthropic permission denied (403): {e.message}") from e
        except anthropic.NotFoundError as e:
            self._breaker.record(False)
            raise LLMUnavailable(f"model {self.model!r} not found (404)") from e
        except anthropic.RateLimitError as e:
            self._breaker.record(False)
            raise LLMUnavailable("Anthropic rate limit (429)") from e
        except anthropic.APIStatusError as e:
            self._breaker.record(False)
            raise LLMUnavailable(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APITimeoutError as e:
            self._breaker.record(False)
            raise LLMUnavailable(f"Anthropic request timed out after {timeout:.0f} s") from e
        except anthropic.APIConnectionError as e:
            self._breaker.record(False)
            raise LLMUnavailable(f"cannot reach Anthropic: {e}") from e
        except anthropic.AnthropicError as e:
            self._breaker.record(False)
            raise LLMUnavailable(f"{type(e).__name__}: {e}") from e
        self._breaker.record(True)
        return self._result(resp, t0)

    def _result(self, resp: Message | BetaMessage, t0: float) -> LLMResult:
        u = resp.usage
        prompt = u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
        billed = BilledUsage(str(resp.model), prompt, u.output_tokens)
        if resp.stop_reason == "refusal":
            details = resp.stop_details
            category = getattr(details, "category", None) if details is not None else None
            raise LLMUnavailable(
                f"declined by the model's safety classifier (category: {category or 'unspecified'})", usage=billed
            )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if resp.stop_reason == "max_tokens":
            where = "mid-answer" if text else "before any text"
            raise LLMUnavailable(
                f"answer cut off by max_tokens {where} (lower thinking effort or raise Max answer tokens)", usage=billed
            )
        return LLMResult(
            text=text,
            model=str(resp.model),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            prompt_tokens=prompt,
            completion_tokens=u.output_tokens,
        )

    async def health(self) -> ProviderHealth:
        """``GET /v1/models/{model}``: verifies the key and the model id without spending tokens."""
        import anthropic

        t0 = time.perf_counter()
        try:
            info = await self._client.models.retrieve(self.model, timeout=10)
        except anthropic.AuthenticationError:
            return ProviderHealth(
                False, self.base_url, self.model, "API key rejected (401)", breaker_open=self.breaker_open
            )
        except anthropic.NotFoundError:
            return ProviderHealth(
                False, self.base_url, self.model, f"model {self.model!r} not found", breaker_open=self.breaker_open
            )
        except anthropic.AnthropicError as e:
            return ProviderHealth(
                False, self.base_url, self.model, f"{type(e).__name__}: {e}", breaker_open=self.breaker_open
            )
        self._context_tokens = getattr(info, "max_input_tokens", None)
        return ProviderHealth(
            True,
            self.base_url,
            info.id,
            "ok",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            context_tokens=self._context_tokens,
            breaker_open=self.breaker_open,
        )

    async def list_models(self) -> list[dict[str, Any]]:
        """The models this key can use, from ``GET /v1/models`` (newest first, as the API orders them)."""
        import anthropic

        out: list[dict[str, Any]] = []
        try:
            async for m in self._client.models.list(limit=100):
                out.append(
                    {
                        "id": m.id,
                        "display_name": m.display_name,
                        "max_input_tokens": getattr(m, "max_input_tokens", None),
                        "max_tokens": getattr(m, "max_tokens", None),
                    }
                )
        except anthropic.AnthropicError as e:
            raise LLMUnavailable(f"{type(e).__name__}: {e}") from e
        return out

    async def aclose(self) -> None:
        await self._client.close()


def _content_text(content: Any) -> str:
    """Text of an OpenAI-style message content (a string, or a list of ``{"type": "text", "text": ...}`` parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""
