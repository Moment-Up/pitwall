"""Which LLM answers the engineer: presets, the persisted provider config, privacy gating, cost accounting and the
hot-swappable ``SwitchableProvider`` the rest of the app holds on to.

Design
------
* ``RaceEngineer`` and the radio hub keep one ``LLMProvider`` object for the life of the process. That object is a
  ``SwitchableProvider``: it reads the ``"llm"`` section of the ``SettingsStore``, builds the configured providers
  and rebuilds them whenever the section changes (store subscription) or a key changes (``reload()``). Call sites
  never change and nothing restarts; in-flight requests finish on the old client, which is closed after a grace
  period.
* Purpose routing: callers that care (the radio) hold ``switchable.for_purpose("radio")`` - a thin view with the
  normal ``LLMProvider`` interface - so a fast model can answer over the radio while the dashboard uses a deeper
  one. Plain ``chat()`` is the ``"engineer"`` purpose.
* Primary + optional fallback provider (cloud -> local or local -> cloud). A provider that is blocked (privacy,
  missing key, budget) or fails is skipped and the reason recorded; if every provider is out the call raises
  ``LLMUnavailable`` and the engineer answers deterministically, exactly as when the local model is down. The
  current config is re-read before *each* attempt, so a settings change made while the primary is in flight
  (e.g. cloud switched off) also governs the fallback.
* Privacy: anything leaving the local network is "cloud". Cloud calls require ``cloud_enabled`` *and* an
  acknowledgement of the current ``PRIVACY_NOTICE_VERSION``; both are checked when the config is saved and again
  before every call (a hand-edited settings file cannot bypass them). Driver names are replaced with "the driver"
  in everything sent to a cloud provider unless the user turns that off; if the names cannot be read the cloud
  call is skipped (fail closed). The last wire request (no headers, so no key) is kept for the "what gets sent"
  preview.
* Keys never live in the settings section: the preset and the endpoint's location imply the *name* of the
  SecretStore entry, and ``PITWALL_<NAME>`` environment variables override the file. A key is only ever sent to
  the endpoint it belongs to: a cloud vendor's key (``anthropic_api_key``...) only to that vendor's own host (a
  different base URL is refused for those presets); the local-server key (``llm_api_key``) only to local hosts;
  the custom cloud key (``custom_api_key``) only to internet hosts. Listing models for an arbitrary URL sends a
  local/custom key only when that URL is the one saved in the config.
* Cost: tokens per day/provider/model are kept in a small JSON ledger next to the settings (rewritten after each
  call - calls are seconds apart, so this is cheap). Cloud cost uses verified Anthropic prices or user-entered
  prices, looked up for the model id the provider *served* (dated snapshot ids match their base id by prefix) and
  then the configured one. Calls the provider billed but could not answer (a refusal, a cut-off answer) count
  too. An optional daily budget blocks further cloud calls once reached. Unknown stays unknown: with a budget set,
  a cloud model without a price is blocked before the call, and a call whose cost still cannot be computed (no
  token counts) pauses cloud calls for the day instead of counting as free.
* Building a provider can import a vendor SDK (``anthropic``: ~0.7 s the first time), so instances are built in
  a worker thread, never on the event loop that also serves /ws/live and the radio.

Nothing here is on the time-critical path: deterministic coaching never calls an LLM.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import copy
import ipaddress
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

from pitwall.ai.providers import (
    AnthropicProvider,
    BilledUsage,
    LLMResult,
    LLMUnavailable,
    ManagedProvider,
    OpenAICompatibleProvider,
    ProviderHealth,
)
from pitwall.compat import replace_file, set_private_mode, this_machine

if TYPE_CHECKING:
    from pitwall.config import Settings
    from pitwall.settings_store import SecretStore, SettingsStore

log = logging.getLogger(__name__)

SECTION = "llm"
CONFIG_VERSION = 1
PURPOSES: tuple[str, ...] = ("engineer", "radio")
Purpose = Literal["engineer", "radio"]
Role = Literal["primary", "fallback"]
ROLES: tuple[Role, ...] = ("primary", "fallback")
Location = Literal["local", "cloud"]
EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

# Bump when the notice text changes materially: everyone must re-acknowledge before cloud calls resume.
PRIVACY_NOTICE_VERSION = 1
PRIVACY_NOTICE: tuple[str, ...] = (
    "Cloud AI sends data to a third-party company (the provider you pick) over the internet.",
    "Each question to the engineer - typed, or the transcript of what you said on the radio (never audio) - is "
    "sent with a fact sheet derived from your telemetry: lap and sector times, corner-by-corner deltas, braking "
    "and throttle observations, tyre and fuel figures, track, car, session type and weather, plus your last few "
    "exchanges with the engineer.",
    'Driver names are replaced with "the driver" unless you turn that off below. Raw telemetry, captures and '
    "your other settings are never sent.",
    "The provider may keep requests under its own terms (for example for abuse monitoring), and every call is "
    'billed to your account. Use "What gets sent" to see the exact last request.',
    f"Local models keep everything on {this_machine()}. Deterministic coaching and cues never use any model.",
)


# --------------------------------------------------------------------------------------------- presets
@dataclass(frozen=True, slots=True)
class Preset:
    """A known provider. ``base_url`` values were checked against each vendor's documentation (2026-10)."""

    id: str
    label: str
    kind: Literal["anthropic", "openai"]
    location: Literal["local", "cloud", "auto"]  # auto: decided by the base URL's host
    base_url: str
    # SecretStore entry (env override PITWALL_<NAME>). For a fixed cloud vendor it is that vendor's key and only
    # ever goes to ``base_url``'s host. For the other presets it is the key used while the endpoint is local, and
    # ``cloud_key_name`` the one used once the URL points at the internet - so a key saved for an internet host is
    # never sent (possibly over plain http) to a LAN server, and a LAN server's key never leaves the network.
    key_name: str | None = None
    cloud_key_name: str | None = None
    key_required: bool = False
    docs_url: str = ""
    notes: str = ""
    suggested_engineer: str | None = None
    suggested_radio: str | None = None
    suggested_models: tuple[str, ...] = ()
    # OpenAI-compatible wire options (see OpenAICompatibleProvider)
    cache_prompt: bool = False
    send_temperature: bool = True
    max_tokens_field: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    reasoning_headroom_tokens: int = 0
    probe_health_endpoint: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "location": self.location,
            "base_url": self.base_url,
            "key_name": self.key_name,
            "cloud_key_name": self.cloud_key_name,
            "key_required": self.key_required,
            "docs_url": self.docs_url,
            "notes": self.notes,
            "suggested": {"engineer": self.suggested_engineer, "radio": self.suggested_radio},
            "suggested_models": list(self.suggested_models),
        }


PRESETS: dict[str, Preset] = {
    p.id: p
    for p in (
        # ---- local (http allowed on loopback / LAN / tailnet)
        Preset(
            "llamacpp",
            "llama.cpp (llama-server)",
            "openai",
            "local",
            "http://127.0.0.1:8081/v1",
            key_name="llm_api_key",
            cloud_key_name="custom_api_key",
            docs_url="https://github.com/ggml-org/llama.cpp/tree/master/tools/server",
            notes="This Mac's default. llama-server itself defaults to port 8080; pitwall's install uses 8081.",
            cache_prompt=True,
            probe_health_endpoint=True,
        ),
        Preset(
            "lmstudio",
            "LM Studio",
            "openai",
            "local",
            "http://127.0.0.1:1234/v1",
            docs_url="https://lmstudio.ai/docs/developer/openai-compat",
            notes="Start the server from LM Studio's Developer tab (default port 1234).",
            probe_health_endpoint=True,
        ),
        Preset(
            "ollama",
            "Ollama",
            "openai",
            "local",
            "http://127.0.0.1:11434/v1",
            docs_url="https://docs.ollama.com/api/openai-compatibility",
            notes="Ollama's OpenAI-compatible endpoint (default port 11434).",
            probe_health_endpoint=True,
        ),
        Preset(
            "mlx",
            "MLX (mlx_lm.server)",
            "openai",
            "local",
            "http://127.0.0.1:8080/v1",
            docs_url="https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md",
            notes="mlx_lm.server defaults to port 8080. Structured JSON output is not documented for it.",
            probe_health_endpoint=True,
        ),
        # ---- cloud (https only)
        Preset(
            "anthropic",
            "Anthropic Claude",
            "anthropic",
            "cloud",
            "https://api.anthropic.com",
            key_name="anthropic_api_key",
            key_required=True,
            docs_url="https://platform.claude.com/docs/en/about-claude/models/overview",
            notes="Opus 5.5 for depth on the dashboard; Haiku 5.5 for fast radio answers.",
            suggested_engineer="claude-opus-5-5",
            suggested_radio="claude-haiku-5-5",
            suggested_models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
        ),
        Preset(
            "openai",
            "OpenAI",
            "openai",
            "cloud",
            "https://api.openai.com/v1",
            key_name="openai_api_key",
            key_required=True,
            docs_url="https://platform.openai.com/docs/api-reference/chat",
            notes="Uses max_completion_tokens and the default temperature (required by OpenAI reasoning models).",
            send_temperature=False,
            max_tokens_field="max_completion_tokens",
            reasoning_headroom_tokens=1024,
        ),
        Preset(
            "openrouter",
            "OpenRouter",
            "openai",
            "cloud",
            "https://openrouter.ai/api/v1",
            key_name="openrouter_api_key",
            key_required=True,
            docs_url="https://openrouter.ai/docs/quickstart",
            notes="One key for many vendors; model ids look like vendor/model.",
            reasoning_headroom_tokens=1024,
        ),
        Preset(
            "gemini",
            "Google Gemini (OpenAI-compatible)",
            "openai",
            "cloud",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            key_name="gemini_api_key",
            key_required=True,
            docs_url="https://ai.google.dev/gemini-api/docs/openai",
            reasoning_headroom_tokens=1024,
        ),
        Preset(
            "groq",
            "Groq",
            "openai",
            "cloud",
            "https://api.groq.com/openai/v1",
            key_name="groq_api_key",
            key_required=True,
            docs_url="https://console.groq.com/docs/openai",
            reasoning_headroom_tokens=1024,
        ),
        Preset(
            "mistral",
            "Mistral",
            "openai",
            "cloud",
            "https://api.mistral.ai/v1",
            key_name="mistral_api_key",
            key_required=True,
            docs_url="https://docs.mistral.ai/api/",
            reasoning_headroom_tokens=1024,
        ),
        # ---- anything else speaking the OpenAI wire format; local or cloud depending on its host
        Preset(
            "custom",
            "Other OpenAI-compatible server",
            "openai",
            "auto",
            "",
            key_name="llm_api_key",
            cloud_key_name="custom_api_key",
            notes=f"Local if the host is on {this_machine()}, your LAN or tailnet; otherwise treated as cloud "
            "(https only).",
        ),
    )
}

KEY_NAMES: frozenset[str] = frozenset(
    n for p in PRESETS.values() for n in (p.key_name, p.cloud_key_name) if n is not None
)


# --------------------------------------------------------------------------------------------- URLs
_CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale addresses


def is_local_host(host: str) -> bool:
    """True for loopback, private LAN, link-local, Tailscale (100.64/10, *.ts.net), mDNS (*.local) and bare
    single-label hostnames. Everything else is treated as the public internet ("cloud")."""
    h = host.strip("[]").lower().rstrip(".")
    if not h:
        return False
    if h == "localhost" or h.endswith((".localhost", ".local", ".ts.net", ".home.arpa")):
        return True
    if "." not in h and ":" not in h:  # single-label name: resolved by the LAN, not public DNS
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local or (ip.version == 4 and ip in _CGNAT)


class ConfigError(ValueError):
    def __init__(self, field_path: str, message: str) -> None:
        super().__init__(f"{field_path}: {message}")
        self.field = field_path
        self.message = message


def check_base_url(url: str, *, cloud: bool, field_path: str = "base_url") -> str:
    """Validate and normalise a provider base URL. Cloud endpoints must use https; credentials, query strings and
    fragments are refused (keys belong in the SecretStore, never in a URL)."""
    u = url.strip()
    parts = urlsplit(u)
    if parts.scheme not in ("http", "https"):
        raise ConfigError(field_path, "must start with http:// or https://")
    if not parts.hostname:
        raise ConfigError(field_path, "has no host")
    if parts.username or parts.password:
        raise ConfigError(field_path, "must not contain credentials - save the API key separately")
    if parts.query or parts.fragment:
        raise ConfigError(field_path, "must not contain a query string or fragment")
    if cloud and parts.scheme != "https":
        raise ConfigError(field_path, "cloud providers must use https://")
    return u.rstrip("/")


def location_of(preset: Preset, base_url: str) -> Location:
    """``cloud`` for cloud presets and for any URL whose host is not on the local network."""
    if preset.location == "cloud":
        return "cloud"
    host = urlsplit(base_url).hostname or ""
    return "local" if is_local_host(host) else "cloud"


def _origin(url: str) -> tuple[str, str, int | None]:
    """(scheme, host, port) with the scheme's default port filled in; an invalid port never matches anything."""
    parts = urlsplit(url.strip())
    try:
        port = parts.port
    except ValueError:
        port = -1
    if port is None:
        port = {"https": 443, "http": 80}.get(parts.scheme)
    return parts.scheme, (parts.hostname or "").lower().rstrip("."), port


def on_vendor_host(preset: Preset, url: str) -> bool:
    """True unless ``preset`` is a fixed cloud vendor and ``url`` is not on that vendor's own origin."""
    return preset.location != "cloud" or _origin(url) == _origin(preset.base_url)


def check_vendor_host(preset: Preset, url: str, field_path: str = "base_url") -> None:
    """A cloud vendor's saved key must only ever reach that vendor: refuse any other host for its preset (another
    path on the same host is fine). Endpoints elsewhere use the "custom" preset with its own key."""
    if not on_vendor_host(preset, url):
        host = urlsplit(preset.base_url).hostname
        raise ConfigError(
            field_path,
            f"must be on {host} ({preset.label} keys are only sent there); "
            f'use "{PRESETS["custom"].label}" for a different endpoint',
        )


def key_name_for(preset: Preset, url: str) -> str | None:
    """The SecretStore entry used for this preset at this URL (see ``Preset.key_name``)."""
    if preset.location == "cloud":
        return preset.key_name
    return preset.cloud_key_name if location_of(preset, url) == "cloud" else preset.key_name


# --------------------------------------------------------------------------------------------- config
@dataclass(frozen=True, slots=True)
class ProviderSpec:
    provider: str
    base_url: str | None = None  # None: the preset's URL
    model: str | None = None  # default model for every purpose; None = first model a local server reports
    engineer_model: str | None = None
    radio_model: str | None = None
    timeout_s: float = 60.0
    max_tokens: int | None = None  # upper limit on answer tokens per call (cost guard); None = caller decides
    effort: str = "low"  # Anthropic output_config.effort

    @property
    def preset(self) -> Preset:
        return PRESETS[self.provider]

    @property
    def url(self) -> str:
        return (self.base_url or self.preset.base_url).rstrip("/")

    @property
    def location(self) -> Location:
        return location_of(self.preset, self.url)

    def model_for(self, purpose: str) -> str | None:
        specific = self.radio_model if purpose == "radio" else self.engineer_model
        return specific or self.model

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "models": {"engineer": self.engineer_model, "radio": self.radio_model},
            "timeout_s": self.timeout_s,
            "max_tokens": self.max_tokens,
            "effort": self.effort,
        }


@dataclass(frozen=True, slots=True)
class Price:
    """USD per million tokens. Claude Haiku 5.5 has a second rate card for prompts over 100K tokens."""

    input_per_mtok: float
    output_per_mtok: float
    long_context_threshold: int | None = None
    long_input_per_mtok: float | None = None
    long_output_per_mtok: float | None = None

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        i, o = self.input_per_mtok, self.output_per_mtok
        if self.long_context_threshold is not None and prompt_tokens > self.long_context_threshold:
            i = self.long_input_per_mtok if self.long_input_per_mtok is not None else i
            o = self.long_output_per_mtok if self.long_output_per_mtok is not None else o
        return (prompt_tokens * i + completion_tokens * o) / 1_000_000


# Base input/output prices from https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-10-10).
# pitwall does not use prompt caching or batch, so base rates apply. Keys match by prefix (dated ids).
ANTHROPIC_PRICES: dict[str, Price] = {
    "claude-fable-5-1": Price(10.0, 50.0),
    "claude-fable-5": Price(10.0, 50.0),
    "claude-opus-5-5": Price(4.0, 20.0),
    "claude-opus-5": Price(5.0, 25.0),
    "claude-opus-4-8": Price(5.0, 25.0),
    "claude-opus-4-7": Price(5.0, 25.0),
    "claude-opus-4-6": Price(5.0, 25.0),
    "claude-opus-4-5": Price(5.0, 25.0),
    "claude-sonnet-5-5": Price(2.0, 10.0),
    "claude-sonnet-5": Price(2.0, 10.0),
    "claude-sonnet-4-6": Price(3.0, 15.0),
    "claude-haiku-5-5": Price(0.10, 0.50, 100_000, 0.50, 2.50),
    "claude-haiku-4-5": Price(1.0, 5.0),
}


@dataclass(frozen=True, slots=True)
class LLMConfig:
    enabled: bool = True
    primary: ProviderSpec = field(default_factory=lambda: ProviderSpec("llamacpp"))
    fallback: ProviderSpec | None = None
    cloud_enabled: bool = False
    notice_version: int = 0  # version of PRIVACY_NOTICE the user acknowledged (0 = never)
    acknowledged_at: float | None = None
    redact_driver_names: bool = True
    daily_budget_usd: float | None = None
    prices: Mapping[str, Price] = field(default_factory=dict)

    @property
    def cloud_allowed(self) -> bool:
        return self.cloud_enabled and self.notice_version >= PRIVACY_NOTICE_VERSION

    def cloud_block_reason(self) -> str | None:
        if not self.cloud_enabled:
            return "cloud AI is off (turn it on in Settings > AI engineer)"
        if self.notice_version < PRIVACY_NOTICE_VERSION:
            return "the cloud privacy notice has not been acknowledged (Settings > AI engineer)"
        return None

    def specs(self) -> list[tuple[Role, ProviderSpec]]:
        out: list[tuple[Role, ProviderSpec]] = [("primary", self.primary)]
        if self.fallback is not None:
            out.append(("fallback", self.fallback))
        return out

    def price_for(self, spec: ProviderSpec, model: str | None) -> Price | None:
        """Price of ``model`` on ``spec``'s provider, or None if unknown.

        User prices match exactly or as a prefix of a dated snapshot id (``gpt-5`` prices ``gpt-5-2025-08-07``,
        which is what OpenAI reports back for a ``gpt-5`` request); the longest key wins, so ``gpt-5-mini`` is not
        priced as ``gpt-5``. Built-in Anthropic prices match the same way.
        """
        if spec.location == "local":
            return Price(0.0, 0.0)
        if not model:
            return None
        tables: list[Mapping[str, Price]] = [self.prices]
        if spec.provider == "anthropic":
            tables.append(ANTHROPIC_PRICES)
        for table in tables:
            for key in sorted(table, key=len, reverse=True):
                if model == key or model.startswith(key + "-"):
                    return table[key]
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CONFIG_VERSION,
            "enabled": self.enabled,
            "primary": self.primary.to_dict(),
            "fallback": self.fallback.to_dict() if self.fallback else None,
            "privacy": {
                "cloud_enabled": self.cloud_enabled,
                "notice_version": self.notice_version,
                "acknowledged_at": self.acknowledged_at,
                "redact_driver_names": self.redact_driver_names,
            },
            "budget": {"daily_usd": self.daily_budget_usd},
            "prices": {
                m: {"input_per_mtok": p.input_per_mtok, "output_per_mtok": p.output_per_mtok}
                for m, p in sorted(self.prices.items())
            },
        }


def _opt_str(v: Any, path: str, max_len: int = 200) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ConfigError(path, "must be a string")
    s = v.strip()
    if len(s) > max_len:
        raise ConfigError(path, f"longer than {max_len} characters")
    if any(c.isspace() or not c.isprintable() for c in s):
        raise ConfigError(path, "must not contain spaces or control characters")
    return s or None


def _num(v: Any, path: str, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise ConfigError(path, "must be a number")
    if not lo <= float(v) <= hi:
        raise ConfigError(path, f"must be between {lo:g} and {hi:g}")
    return float(v)


def _parse_spec(raw: Any, path: str) -> ProviderSpec:
    if not isinstance(raw, Mapping):
        raise ConfigError(path, "must be an object")
    pid = raw.get("provider")
    if pid not in PRESETS:
        raise ConfigError(f"{path}.provider", f"unknown provider (choose one of {', '.join(PRESETS)})")
    preset = PRESETS[pid]
    base_url = raw.get("base_url")
    if base_url is not None and not isinstance(base_url, str):
        raise ConfigError(f"{path}.base_url", "must be a string")
    url = (base_url or "").strip() or preset.base_url
    if not url:
        raise ConfigError(f"{path}.base_url", "is required for this provider")
    # Validate syntax first, then the scheme against where the host actually is, then the vendor's host.
    url = check_base_url(url, cloud=False, field_path=f"{path}.base_url")
    check_base_url(url, cloud=location_of(preset, url) == "cloud", field_path=f"{path}.base_url")
    check_vendor_host(preset, url, f"{path}.base_url")
    models = raw.get("models") or {}
    if not isinstance(models, Mapping):
        raise ConfigError(f"{path}.models", "must be an object")
    unknown = set(models) - set(PURPOSES)
    if unknown:
        raise ConfigError(f"{path}.models", f"unknown purpose(s): {', '.join(sorted(unknown))}")
    effort = raw.get("effort", "low")
    if effort not in EFFORTS:
        raise ConfigError(f"{path}.effort", f"must be one of {', '.join(EFFORTS)}")
    max_tokens = raw.get("max_tokens")
    spec = ProviderSpec(
        provider=pid,
        base_url=None if url == preset.base_url.rstrip("/") else url,
        model=_opt_str(raw.get("model"), f"{path}.model"),
        engineer_model=_opt_str(models.get("engineer"), f"{path}.models.engineer"),
        radio_model=_opt_str(models.get("radio"), f"{path}.models.radio"),
        timeout_s=_num(raw.get("timeout_s", 60.0), f"{path}.timeout_s", 2, 600),
        max_tokens=None if max_tokens is None else int(_num(max_tokens, f"{path}.max_tokens", 16, 8192)),
        effort=effort,
    )
    if spec.location == "cloud" or preset.kind == "anthropic":
        for purpose in PURPOSES:
            if not spec.model_for(purpose):
                raise ConfigError(f"{path}.models.{purpose}", "choose a model (cloud providers have no default)")
    return spec


def parse_config(raw: Mapping[str, Any]) -> LLMConfig:
    """Validate a stored/submitted ``llm`` section. Raises ``ConfigError`` naming the offending field."""
    if not isinstance(raw, Mapping):
        raise ConfigError("config", "must be an object")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError("enabled", "must be true or false")
    primary = _parse_spec(raw.get("primary"), "primary")
    fallback = None if raw.get("fallback") is None else _parse_spec(raw.get("fallback"), "fallback")
    if fallback is not None and fallback == primary:
        raise ConfigError("fallback", "is the same as the primary provider")
    privacy = raw.get("privacy") or {}
    if not isinstance(privacy, Mapping):
        raise ConfigError("privacy", "must be an object")
    cloud_enabled = privacy.get("cloud_enabled", False)
    redact = privacy.get("redact_driver_names", True)
    if not isinstance(cloud_enabled, bool) or not isinstance(redact, bool):
        raise ConfigError("privacy", "flags must be true or false")
    notice_version = privacy.get("notice_version", 0)
    if isinstance(notice_version, bool) or not isinstance(notice_version, int) or notice_version < 0:
        raise ConfigError("privacy.notice_version", "must be a non-negative integer")
    ack_at = privacy.get("acknowledged_at")
    if ack_at is not None:
        ack_at = _num(ack_at, "privacy.acknowledged_at", 0, 1e11)
    budget = raw.get("budget") or {}
    if not isinstance(budget, Mapping):
        raise ConfigError("budget", "must be an object")
    daily = budget.get("daily_usd")
    daily_usd = None if daily is None else _num(daily, "budget.daily_usd", 0, 10_000)
    prices_raw = raw.get("prices") or {}
    if not isinstance(prices_raw, Mapping):
        raise ConfigError("prices", "must be an object")
    prices: dict[str, Price] = {}
    for model, p in prices_raw.items():
        mid = _opt_str(model, "prices")
        if not mid or not isinstance(p, Mapping):
            raise ConfigError(f"prices.{model}", "must map a model id to input/output prices")
        prices[mid] = Price(
            _num(p.get("input_per_mtok"), f"prices.{model}.input_per_mtok", 0, 1000),
            _num(p.get("output_per_mtok"), f"prices.{model}.output_per_mtok", 0, 1000),
        )
    cfg = LLMConfig(
        enabled=enabled,
        primary=primary,
        fallback=fallback,
        cloud_enabled=cloud_enabled,
        notice_version=notice_version,
        acknowledged_at=ack_at,
        redact_driver_names=redact,
        daily_budget_usd=daily_usd,
        prices=prices,
    )
    for role, spec in cfg.specs():
        if spec.location == "cloud" and (reason := cfg.cloud_block_reason()):
            raise ConfigError(f"{role}.provider", f"{spec.preset.label} is a cloud provider but {reason}")
    return cfg


def config_from_settings(settings: Settings) -> LLMConfig:
    """The initial config while the ``llm`` section is empty: the environment (``PITWALL_LLM_*``) as before."""
    url = settings.llm_base_url.rstrip("/")
    host = urlsplit(url).hostname or ""
    pid = "llamacpp" if is_local_host(host) else "custom"
    preset = PRESETS[pid]
    spec = ProviderSpec(
        provider=pid,
        base_url=None if url == preset.base_url else url,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_s,
        max_tokens=settings.llm_max_tokens,
    )
    return LLMConfig(enabled=settings.llm_enabled, primary=spec)


# --------------------------------------------------------------------------------------------- redaction
_GENERIC_NAMES = frozenset({"driver", "the driver", "me", "you", "player", "guest", "unknown", "default"})


def redact_names(text: str, names: Iterable[str]) -> tuple[str, int]:
    """Replace each driver name (whole words, case-sensitive, possessive kept) with "the driver".

    Case-sensitive on purpose: names appear capitalised in fact sheets and transcripts, and matching
    case-insensitively would mangle ordinary words (a driver called "Max" vs "max speed"). Generic labels such as
    "Driver" are never treated as names. Longer names go first so "Alex Racer" wins over "Alex".
    """
    cleaned = sorted(
        {n.strip() for n in names if n and len(n.strip()) >= 2 and n.strip().lower() not in _GENERIC_NAMES},
        key=len,
        reverse=True,
    )
    if not cleaned or not text:
        return text, 0
    rx = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(n) for n in cleaned) + r")(?!\w)")
    out, n = rx.subn("the driver", text)
    return out, n


def redact_messages(messages: list[dict[str, Any]], names: Iterable[str]) -> tuple[list[dict[str, Any]], int]:
    names = list(names)
    total = 0
    out: list[dict[str, Any]] = []
    for m in messages:
        m2 = dict(m)
        content = m.get("content")
        if isinstance(content, str):
            m2["content"], n = redact_names(content, names)
            total += n
        elif isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict) and isinstance(p.get("text"), str):
                    p = {**p}
                    p["text"], n = redact_names(p["text"], names)
                    total += n
                parts.append(p)
            m2["content"] = parts
        out.append(m2)
    return out, total


def _scrub(obj: Any, secrets: list[str]) -> Any:
    """Defence in depth for the request preview: blank any configured secret value wherever it appears."""
    if not secrets:
        return obj
    if isinstance(obj, str):
        for s in secrets:
            if s and s in obj:
                obj = obj.replace(s, "[redacted secret]")
        return obj
    if isinstance(obj, list):
        return [_scrub(v, secrets) for v in obj]
    if isinstance(obj, dict):
        return {k: _scrub(v, secrets) for k, v in obj.items()}
    return obj


# --------------------------------------------------------------------------------------------- usage ledger
class UsageLedger:
    """Token and cost totals per local day and provider/model, persisted as a small JSON file (mode 0600).

    The file is rewritten after each recorded call (atomic temp + rename; a few hundred bytes per active day).
    Losing it only resets the counters, so no fsync. Days older than ``keep_days`` are pruned.
    """

    def __init__(self, path: Path | None, clock: Callable[[], float] = time.time, keep_days: int = 90) -> None:
        self.path = path
        self.clock = clock
        self.keep_days = keep_days
        self._lock = threading.Lock()
        self._days: dict[str, dict[str, dict[str, Any]]] = {}
        self.last_block: dict[str, Any] | None = None
        if path is not None and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                days = data.get("days") if isinstance(data, dict) else None
                if isinstance(days, dict):
                    self._days = {d: v for d, v in days.items() if isinstance(v, dict)}
            except (OSError, ValueError):
                log.warning("unreadable LLM usage ledger %s; starting from zero", path)

    def today(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(self.clock()))

    def record(
        self,
        *,
        provider: str,
        model: str | None,
        location: str,
        purpose: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        cost_usd: float | None = None,
        ok: bool = True,
        blocked: str | None = None,
        billed: bool | None = None,
        unmetered: bool = False,
    ) -> None:
        """Count one call. ``billed`` (default: ``ok``) is True when the provider charged for it - a failed call
        can be billed (a refusal). ``unmetered`` marks a billed cloud call whose cost could not be computed while a
        daily budget was set; any such call pauses cloud calls for the day (see ``unmetered_cloud_today``)."""
        billed = ok if billed is None else billed
        day = self.today()
        key = f"{provider}|{model or '(auto)'}"
        with self._lock:
            row = self._days.setdefault(day, {}).setdefault(
                key,
                {
                    "provider": provider,
                    "model": model,
                    "location": location,
                    "calls": 0,
                    "errors": 0,
                    "blocked": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": 0.0,
                    "unpriced_calls": 0,
                    "unmetered_calls": 0,
                    "by_purpose": {},
                },
            )
            if blocked:
                row["blocked"] += 1
                self.last_block = {"at": self.clock(), "provider": provider, "model": model, "reason": blocked}
                return
            row["calls"] += 1
            row["by_purpose"][purpose] = row["by_purpose"].get(purpose, 0) + 1
            if not ok:
                row["errors"] += 1
            row["prompt_tokens"] += prompt_tokens or 0
            row["completion_tokens"] += completion_tokens or 0
            if billed and cost_usd is None and location == "cloud":
                row["unpriced_calls"] += 1
            if unmetered:
                row["unmetered_calls"] = row.get("unmetered_calls", 0) + 1  # rows from older ledgers lack it
            row["cost_usd"] = round(row["cost_usd"] + (cost_usd or 0.0), 6)

    def cloud_cost_today(self) -> float:
        with self._lock:
            rows = self._days.get(self.today(), {})
            return float(sum(r["cost_usd"] for r in rows.values() if r.get("location") == "cloud"))

    def unmetered_cloud_today(self) -> int:
        """Billed cloud calls today whose cost is unknown although a budget was set (today's spend is unknown)."""
        with self._lock:
            rows = self._days.get(self.today(), {})
            return int(sum(r.get("unmetered_calls", 0) for r in rows.values() if r.get("location") == "cloud"))

    def summary(self, days: int = 14) -> dict[str, Any]:
        with self._lock:
            keys = sorted(self._days, reverse=True)[:days]
            snap = {d: copy.deepcopy(self._days[d]) for d in keys}
        today = self.today()

        def totals(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
            vals = list(rows.values())
            return {
                "calls": sum(r["calls"] for r in vals),
                "errors": sum(r["errors"] for r in vals),
                "blocked": sum(r["blocked"] for r in vals),
                "prompt_tokens": sum(r["prompt_tokens"] for r in vals),
                "completion_tokens": sum(r["completion_tokens"] for r in vals),
                "cloud_cost_usd": round(sum(r["cost_usd"] for r in vals if r.get("location") == "cloud"), 6),
                "unpriced_calls": sum(r["unpriced_calls"] for r in vals),
                "unmetered_calls": sum(r.get("unmetered_calls", 0) for r in vals),
            }

        return {
            "today": {"date": today, **totals(snap.get(today, {})), "by_model": list(snap.get(today, {}).values())},
            "days": [{"date": d, **totals(snap[d])} for d in keys],
            "last_block": self.last_block,
        }

    def save(self) -> None:
        if self.path is None:
            return
        with self._lock:
            cutoff = time.strftime("%Y-%m-%d", time.localtime(self.clock() - self.keep_days * 86400))
            self._days = {d: v for d, v in self._days.items() if d >= cutoff}
            data = json.dumps({"version": 1, "days": self._days}, indent=1, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            set_private_mode(fd, 0o600)  # os.fchmod; no-op on Windows (folder ACL)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(data)
            replace_file(Path(tmp), self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


# --------------------------------------------------------------------------------------------- building
@dataclass(frozen=True, slots=True)
class ProviderBuild:
    """Everything needed to construct one provider instance (one endpoint + one model)."""

    preset: Preset
    base_url: str
    model: str | None
    api_key: str | None
    timeout_s: float
    effort: str
    name: str


ProviderFactory = Callable[[ProviderBuild], ManagedProvider]


def default_factory(b: ProviderBuild) -> ManagedProvider:
    if b.preset.kind == "anthropic":
        if not b.api_key:
            raise LLMUnavailable(f"no API key saved ({b.preset.key_name})")
        if not b.model:
            raise LLMUnavailable("no model chosen")
        effort: Any = b.effort if b.effort in EFFORTS else "low"
        return AnthropicProvider(
            b.api_key, b.model, base_url=b.base_url, timeout_s=b.timeout_s, effort=effort, name=b.name
        )
    p = b.preset
    return OpenAICompatibleProvider(
        b.base_url,
        b.model,
        b.api_key,
        timeout_s=b.timeout_s,
        name=b.name,
        cache_prompt=p.cache_prompt,
        send_temperature=p.send_temperature,
        max_tokens_field=p.max_tokens_field,
        reasoning_headroom_tokens=p.reasoning_headroom_tokens,
        probe_health_endpoint=p.probe_health_endpoint if location_of(p, b.base_url) == "local" else False,
    )


@dataclass(slots=True)
class _Slot:
    role: Role
    spec: ProviderSpec
    instances: dict[str, ManagedProvider] = field(default_factory=dict)  # model ("" = auto) -> provider

    @property
    def label(self) -> str:
        return f"{self.role} ({self.spec.preset.label})"


@dataclass(slots=True)
class _State:
    config: LLMConfig
    source: Literal["settings", "defaults"]
    error: str | None
    slots: dict[Role, _Slot]
    version: int


class _Stale(Exception):
    """The slot being used was replaced by a settings change: re-read the state and try again."""


class _NamesUnavailable(Exception):
    """Driver names could not be read, so nothing may go to a cloud provider (redaction fails closed)."""


NAMES_TTL_S = 30.0
_MAX_RESTARTS = 5  # settings changes tolerated during one call before giving up on a role


class SwitchableProvider:
    """The app's single ``LLMProvider``: delegates to the configured provider(s) and hot-swaps on change."""

    def __init__(
        self,
        store: SettingsStore,
        secrets: SecretStore,
        *,
        defaults: LLMConfig | None = None,
        usage_path: Path | None = None,
        names: Callable[[], Iterable[str]] | None = None,
        factory: ProviderFactory | None = None,
        clock: Callable[[], float] = time.time,
        retire_grace_s: float | None = None,
        default_keys: Mapping[str, str | None] | None = None,
    ) -> None:
        """``default_keys``: key values from the deploy-time ``Settings`` (``.env``), used when neither the
        SecretStore file nor the process environment has the key - e.g. ``{"llm_api_key": settings.llm_api_key}``
        so ``PITWALL_LLM_API_KEY`` in ``.env`` keeps working (pydantic-settings reads ``.env`` without exporting it
        to ``os.environ``, which is all ``SecretStore`` looks at)."""
        self.store = store
        self.secrets = secrets
        self.defaults = defaults or LLMConfig()
        self.ledger = UsageLedger(usage_path, clock)
        self.clock = clock
        self._names_fn = names
        self._names: tuple[str, ...] | None = None  # last successful read (None: never read)
        self._names_at = -1e9
        self._names_stale = False  # a driver was added/renamed since the last read
        self._factory = factory or default_factory
        self._retire_grace_s = retire_grace_s
        self._default_keys = {k: v for k, v in (default_keys or {}).items() if v}
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing: set[concurrent.futures.Future[None]] = set()
        self._last_request: dict[str, Any] | None = None
        self._version = 0
        self.name = "switchable"
        self._state = self._build_state()
        self._unsubscribe = store.subscribe(SECTION, self._on_change)

    # ------------------------------------------------------------------ config
    @property
    def config(self) -> LLMConfig:
        return self._state.config

    def _build_state(self) -> _State:
        raw = self.store.get(SECTION)
        cfg = self.defaults
        source: Literal["settings", "defaults"] = "defaults"
        error: str | None = None
        if raw:
            try:
                cfg, source = parse_config(raw), "settings"
            except ConfigError as e:
                error = f"saved AI settings are invalid ({e}); using the defaults"
                log.error("llm settings: %s", error)
        with self._lock:
            self._version += 1
            version = self._version
        slots = {role: _Slot(role, spec) for role, spec in cfg.specs()}
        st = _State(cfg, source, error, slots, version)
        self.name = f"switchable:{cfg.primary.provider}" if cfg.enabled else "switchable:off"
        return st

    def _on_change(self, _section: str, _values: dict[str, Any]) -> None:
        self.reload()

    def reload(self) -> None:
        """Rebuild providers from the store and secrets (after a settings or key change). Thread-safe."""
        with self._lock:
            old = self._state
            self._state = new = self._build_state()
            # Collected under the lock: an instance is only ever added to a slot that is current (see _instance),
            # so nothing built for the old state can escape being closed.
            retired = [p for s in old.slots.values() for p in s.instances.values()]
        c = new.config
        log.info(
            "AI provider config v%d: %s primary=%s (%s) engineer=%s radio=%s fallback=%s",
            new.version,
            "enabled" if c.enabled else "disabled",
            c.primary.provider,
            c.primary.location,
            c.primary.model_for("engineer") or "(auto)",
            c.primary.model_for("radio") or "(auto)",
            c.fallback.provider if c.fallback else "none",
        )
        self._retire(retired, old.config)

    def save_config(self, cfg: LLMConfig) -> LLMConfig:
        """Persist a validated config (the store notifies us, which swaps the providers)."""
        self.store.replace(SECTION, cfg.to_dict())
        return self._state.config

    # ------------------------------------------------------------------ lifecycle
    def _retire(self, providers: list[ManagedProvider], cfg: LLMConfig) -> None:
        if not providers:
            return
        grace = self._retire_grace_s
        if grace is None:
            grace = max([s.timeout_s for _, s in cfg.specs()] + [5.0]) + 5.0
        loop = self._loop
        if loop is None or loop.is_closed():
            return  # never used from an event loop: nothing in flight, clients hold no connections yet

        async def close_later() -> None:
            await asyncio.sleep(grace)
            for p in providers:
                try:
                    await p.aclose()
                except Exception:
                    log.debug("closing retired provider failed", exc_info=True)

        fut = asyncio.run_coroutine_threadsafe(close_later(), loop)
        self._closing.add(fut)
        fut.add_done_callback(self._closing.discard)

    async def aclose(self) -> None:
        self._unsubscribe()
        for fut in list(self._closing):
            fut.cancel()
        for slot in self._state.slots.values():
            for p in list(slot.instances.values()):
                try:
                    await p.aclose()
                except Exception:
                    log.debug("closing provider failed", exc_info=True)
            slot.instances.clear()

    def _remember_loop(self) -> None:
        with contextlib.suppress(RuntimeError):  # called outside a loop (sync tests): nothing to remember
            self._loop = asyncio.get_running_loop()

    # ------------------------------------------------------------------ keys
    def key_value(self, name: str) -> str | None:
        """A key by SecretStore name: environment, then the secrets file, then the deploy-time default."""
        return self.secrets.get(name) or self._default_keys.get(name)

    def key_source(self, name: str) -> str | None:
        """``"env"``, ``"file"``, ``"settings"`` (deploy-time default, e.g. ``.env``) or None."""
        return self.secrets.source(name) or ("settings" if self._default_keys.get(name) else None)

    def _key(self, spec: ProviderSpec) -> str | None:
        """The key for a configured endpoint. A fixed cloud vendor's key is withheld from any other host - checked
        here as well as in ``parse_config`` so a config that skipped validation cannot redirect it."""
        name = key_name_for(spec.preset, spec.url)
        if name is None or not on_vendor_host(spec.preset, spec.url):
            return None
        return self.key_value(name)

    def _key_for_listing(self, preset: Preset, url: str) -> str | None:
        """The key to send with a model listing for an arbitrary (validated) URL.

        Fixed cloud vendors: their own key (the URL was already checked to be on the vendor's host). Any other
        preset: its key only if ``url`` is a URL the current config uses for that preset, or the preset's own
        default local URL - so ``/api/llm/models`` naming some other server can never carry a saved key there.
        """
        name = key_name_for(preset, url)
        if name is None:
            return None
        if preset.location == "cloud":
            return self.key_value(name) if on_vendor_host(preset, url) else None
        bound = {s.url for _, s in self._state.config.specs() if s.provider == preset.id}
        if preset.location == "local" and preset.base_url:
            bound.add(preset.base_url.rstrip("/"))
        return self.key_value(name) if url.rstrip("/") in bound else None

    def _secret_values(self) -> list[str]:
        return [v for n in KEY_NAMES if (v := self.key_value(n))]

    # ------------------------------------------------------------------ provider instances
    def _instance(self, slot: _Slot, model: str | None) -> ManagedProvider:
        """Get or build the provider for (slot, model). Runs in a worker thread: building may import a vendor SDK.

        The factory runs outside the lock (the import must not hold up the event loop's own lock use). The result
        is only stored in a slot that is still current; if a settings change retired the slot meanwhile, the new
        instance is closed and ``_Stale`` tells the caller to re-read the state.
        """
        k = model or ""
        with self._lock:
            if self._state.slots.get(slot.role) is not slot:
                raise _Stale
            existing = slot.instances.get(k)
            if existing is not None:
                return existing
            spec = slot.spec
            key = self._key(spec)
            if spec.preset.key_required and not key:
                raise LLMUnavailable(
                    f"no API key saved for {spec.preset.label} ({key_name_for(spec.preset, spec.url)})"
                )
            build = ProviderBuild(
                preset=spec.preset,
                base_url=spec.url,
                model=model,
                api_key=key,
                timeout_s=spec.timeout_s,
                effort=spec.effort,
                name=f"{spec.provider}:{model or 'auto'}",
            )
        p = self._factory(build)
        with self._lock:
            current = self._state.slots.get(slot.role) is slot
            existing = slot.instances.get(k)
            if current and existing is None:
                slot.instances[k] = p
                return p
            config = self._state.config
        self._retire([p], config)  # unused: holds no connections, but close it anyway
        if not current:
            raise _Stale
        assert existing is not None  # built concurrently by another call: use that one
        return existing

    async def _get_instance(self, slot: _Slot, model: str | None) -> ManagedProvider:
        with self._lock:
            if self._state.slots.get(slot.role) is not slot:
                raise _Stale
            p = slot.instances.get(model or "")
        if p is not None:
            return p
        return await asyncio.to_thread(self._instance, slot, model)

    def _block_reason(self, cfg: LLMConfig, spec: ProviderSpec, model: str | None) -> str | None:
        if spec.location != "cloud":
            return None
        if reason := cfg.cloud_block_reason():
            return reason
        if not on_vendor_host(spec.preset, spec.url):
            return f"the server URL is not on {urlsplit(spec.preset.base_url).hostname}, so the saved key is withheld"
        if spec.preset.key_required and not self._key(spec):
            return f"no API key saved ({key_name_for(spec.preset, spec.url)})"
        if cfg.daily_budget_usd is not None:
            if cfg.price_for(spec, model) is None:
                return f"a daily budget is set but no price is known for {model}; add its price in Settings"
            if unmetered := self.ledger.unmetered_cloud_today():
                return (
                    f"a daily budget is set but {unmetered} cloud call(s) today reported no token counts, so today's "
                    "spend is unknown; cloud calls resume tomorrow or when the budget is removed"
                )
            spent = self.ledger.cloud_cost_today()
            if spent >= cfg.daily_budget_usd:
                return (
                    f"daily cloud budget reached (${spent:.2f} of ${cfg.daily_budget_usd:.2f} today); "
                    "cloud calls resume tomorrow or when the budget is raised"
                )
        return None

    # ------------------------------------------------------------------ redaction
    async def _driver_names(self) -> tuple[str, ...]:
        """Names to redact, cached for ``NAMES_TTL_S``. Fails closed: raises ``_NamesUnavailable`` when they cannot
        be read and there is no trustworthy earlier read (none at all, or a driver was added/renamed since). A
        failed read is never cached, so the next call tries again."""
        if self._names_fn is None:
            return ()
        cached = self._names
        now = time.monotonic()
        if cached is not None and not self._names_stale and now - self._names_at < NAMES_TTL_S:
            return cached
        fn = self._names_fn
        try:
            names = tuple(await asyncio.to_thread(lambda: [str(n) for n in fn() if n]))
        except Exception as e:
            if cached is not None and not self._names_stale:
                log.warning("could not re-read driver names; redacting with the last list read", exc_info=True)
                return cached
            log.warning("could not read driver names for redaction; cloud calls skipped", exc_info=True)
            raise _NamesUnavailable(f"{type(e).__name__}: {e}") from e
        self._names, self._names_at, self._names_stale = names, now, False
        return names

    def invalidate_names(self) -> None:
        """Re-read driver names before the next cloud call (call after a driver is added or renamed). Until a read
        succeeds, cloud calls that need redaction are skipped rather than sent with an outdated list."""
        self._names_stale = True

    # ------------------------------------------------------------------ LLMProvider
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 300,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        purpose: str = "engineer",
        role: Role | None = None,
    ) -> LLMResult:
        """Answer with the primary provider, else the fallback. ``role`` restricts to one of them.

        The state is re-read before every attempt (and after every await that precedes the request), so privacy,
        key and budget checks always use the config that is current when the request is sent, and instances are
        only ever built for current slots. A provider that was already tried in this call is not tried again
        even if a settings change moved it to the other role.
        """
        self._remember_loop()
        purpose = purpose if purpose in PURPOSES else "engineer"
        order = [r for r in ROLES if role is None or r == role]
        reasons: list[str] = []
        tried: set[ProviderSpec] = set()
        i = restarts = 0
        while i < len(order):
            st = self._state
            cfg = st.config
            if not cfg.enabled:
                reasons.append("the AI engineer is turned off in Settings")
                break
            slot = st.slots.get(order[i])
            if slot is None or slot.spec in tried:
                i += 1
                continue
            spec = slot.spec
            model = spec.model_for(purpose)
            redact = spec.location == "cloud" and cfg.redact_driver_names
            blocked = self._block_reason(cfg, spec, model)
            names: tuple[str, ...] = ()
            if blocked is None and redact:
                try:
                    names = await self._driver_names()
                except _NamesUnavailable:
                    blocked = "driver names could not be read, so they cannot be redacted"
            if blocked:
                reasons.append(f"{slot.label}: {blocked}")
                self.ledger.record(
                    provider=spec.provider, model=model, location=spec.location, purpose=purpose, blocked=blocked
                )
                i += 1
                continue
            try:
                if self._state is not st:
                    raise _Stale
                provider = await self._get_instance(slot, model)
                if self._state is not st:
                    raise _Stale
            except _Stale:
                restarts += 1
                if restarts > _MAX_RESTARTS:
                    reasons.append(f"{slot.label}: settings kept changing during the call")
                    i += 1
                continue
            except (LLMUnavailable, ValueError) as e:
                reasons.append(f"{slot.label}: {e}")
                i += 1
                continue
            tried.add(spec)
            i += 1
            send, redactions = redact_messages(messages, names) if redact else (messages, 0)
            cap = min(max_tokens, spec.max_tokens) if spec.max_tokens else max_tokens
            res: LLMResult | None = None
            err: LLMUnavailable | None = None
            sent_before = getattr(provider, "last_request", None)
            try:
                res = await provider.chat(
                    send,
                    max_tokens=cap,
                    temperature=temperature,
                    json_schema=json_schema,
                    timeout_s=timeout_s or spec.timeout_s,
                )
            except LLMUnavailable as e:
                err = e
                reasons.append(f"{slot.label}: {e}")
            finally:
                sent = getattr(provider, "last_request", None) is not sent_before  # a request went on the wire
                if sent:
                    self._remember_request(slot, cfg, provider, model, purpose, redactions, res is not None)
            if not sent and res is None:
                continue  # failed before sending (breaker open, model lookup): not a call, nothing billed
            self._account(cfg, spec, model, purpose, res, err)
            await asyncio.to_thread(self._save_ledger)
            if res is not None:
                log.debug(
                    "llm %s/%s purpose=%s tokens=%s/%s %d ms",
                    spec.provider,
                    res.model,
                    purpose,
                    res.prompt_tokens,
                    res.completion_tokens,
                    res.latency_ms,
                )
                return res
        raise LLMUnavailable("; ".join(reasons) or "no AI provider configured")

    @staticmethod
    def _cost(
        cfg: LLMConfig,
        spec: ProviderSpec,
        served: str | None,
        requested: str | None,
        prompt: int | None,
        completion: int | None,
    ) -> float | None:
        """Cost of one billed call. Priced by the served model id first (what the provider actually billed),
        then by the configured id; None when the price or the token counts are unknown (never guessed as 0)."""
        if spec.location == "local":
            return 0.0
        if prompt is None or completion is None:
            return None
        price = cfg.price_for(spec, served)
        if price is None:
            price = cfg.price_for(spec, requested)
        return None if price is None else price.cost(prompt, completion)

    def _account(
        self,
        cfg: LLMConfig,
        spec: ProviderSpec,
        requested: str | None,
        purpose: str,
        res: LLMResult | None,
        err: LLMUnavailable | None,
    ) -> None:
        usage: LLMResult | BilledUsage | None = res if res is not None else (err.usage if err is not None else None)
        billed = usage is not None
        prompt = usage.prompt_tokens if usage is not None else None
        completion = usage.completion_tokens if usage is not None else None
        served = (usage.model if usage is not None else None) or requested
        cost = self._cost(cfg, spec, served, requested, prompt, completion) if billed else None
        self.ledger.record(
            provider=spec.provider,
            model=served,
            location=spec.location,
            purpose=purpose,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cost_usd=cost,
            ok=res is not None,
            billed=billed,
            unmetered=billed and cost is None and spec.location == "cloud" and cfg.daily_budget_usd is not None,
        )

    def _save_ledger(self) -> None:
        try:
            self.ledger.save()
        except OSError:
            log.warning("could not save LLM usage ledger", exc_info=True)

    def _remember_request(
        self,
        slot: _Slot,
        cfg: LLMConfig,
        provider: ManagedProvider,
        model: str | None,
        purpose: str,
        redactions: int,
        ok: bool,
    ) -> None:
        wire = getattr(provider, "last_request", None)
        if wire is None:
            return
        spec = slot.spec
        self._last_request = {
            "at": self.clock(),
            "role": slot.role,
            "provider": spec.provider,
            "provider_label": spec.preset.label,
            "location": spec.location,
            "base_url": spec.url,
            "model": model,
            "purpose": purpose,
            "ok": ok,
            "driver_names_redacted": redactions,
            "redaction_enabled": spec.location == "cloud" and cfg.redact_driver_names,
            "headers": "omitted (they carry the API key)",
            "request": _scrub(copy.deepcopy(wire), self._secret_values()),
        }

    async def health(self, purpose: str = "engineer", role: Role = "primary") -> ProviderHealth:
        self._remember_loop()
        for _ in range(_MAX_RESTARTS):
            st = self._state
            cfg = st.config
            slot = st.slots.get(role)
            if slot is None:
                return ProviderHealth(False, "", None, f"no {role} provider configured")
            spec = slot.spec
            model = spec.model_for(purpose)
            if not cfg.enabled:
                return ProviderHealth(False, spec.url, model, "AI engineer is off")
            if blocked := self._block_reason(cfg, spec, model):
                return ProviderHealth(False, spec.url, model, blocked)
            try:
                provider = await self._get_instance(slot, model)
            except _Stale:
                continue
            except (LLMUnavailable, ValueError) as e:
                return ProviderHealth(False, spec.url, model, str(e))
            return await provider.health()
        return ProviderHealth(False, "", None, "settings changed during the check; try again")

    def for_purpose(self, purpose: str, role: Role | None = None) -> PurposeProvider:
        """An ``LLMProvider`` view that routes every call to ``purpose`` (and optionally one role)."""
        return PurposeProvider(self, purpose, role)

    # ------------------------------------------------------------------ settings page support
    def status(self) -> dict[str, Any]:
        state = self._state
        cfg = state.config
        slots = []
        for role, spec in cfg.specs():
            slot = state.slots.get(role)
            slots.append(
                {
                    "role": role,
                    "provider": spec.provider,
                    "label": spec.preset.label,
                    "kind": spec.preset.kind,
                    "location": spec.location,
                    "base_url": spec.url,
                    "models": {p: spec.model_for(p) for p in PURPOSES},
                    "key_name": key_name_for(spec.preset, spec.url),
                    "key_set": bool(self._key(spec)),
                    "blocked": self._block_reason(cfg, spec, spec.model_for("engineer")) if cfg.enabled else None,
                    "breaker_open": any(
                        getattr(p, "breaker_open", False) for p in (slot.instances.values() if slot else [])
                    ),
                }
            )
        return {
            "version": state.version,
            "source": state.source,
            "error": state.error,
            "enabled": cfg.enabled,
            "mode": "off" if not cfg.enabled else cfg.primary.location,
            "providers": slots,
        }

    def last_request(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._last_request)

    def usage(self) -> dict[str, Any]:
        cfg = self._state.config
        summary = self.ledger.summary()
        spent = self.ledger.cloud_cost_today()
        budget = cfg.daily_budget_usd
        unmetered = self.ledger.unmetered_cloud_today()
        summary["budget"] = {
            "daily_usd": budget,
            "spent_today_usd": round(spent, 6),
            "remaining_usd": None if budget is None else round(max(0.0, budget - spent), 6),
            "reached": budget is not None and (spent >= budget or unmetered > 0),
            "unmetered_calls": unmetered,
        }
        return summary

    async def list_models(self, provider_id: str, base_url: str | None = None) -> list[dict[str, Any]]:
        """Models a provider offers. Sends no telemetry, and a saved key only where it belongs (see
        ``_key_for_listing``): a fixed cloud vendor is only ever asked on its own host."""
        if provider_id not in PRESETS:
            raise LLMUnavailable("unknown provider")
        preset = PRESETS[provider_id]
        url = (base_url or "").strip() or preset.base_url
        if not url:
            raise LLMUnavailable("enter the server URL first")
        try:
            url = check_base_url(url, cloud=False)
            check_base_url(url, cloud=location_of(preset, url) == "cloud")
            check_vendor_host(preset, url)
        except ConfigError as e:
            raise LLMUnavailable(f"server URL {e.message}") from e
        key = self._key_for_listing(preset, url)
        name = key_name_for(preset, url)
        if preset.key_required and not key:
            raise LLMUnavailable(f"save the {preset.label} API key first")
        probe_model = preset.suggested_engineer if preset.kind == "anthropic" else None
        build = ProviderBuild(preset, url, probe_model, key, 15.0, "low", f"{provider_id}:list")
        p = await asyncio.to_thread(self._factory, build)  # may import a vendor SDK: off the event loop
        try:
            return await p.list_models()
        except LLMUnavailable as e:
            if key is None and name is not None and self.key_value(name):
                raise LLMUnavailable(
                    f"{e} - the saved key is only sent to the server URL saved in these settings; save first"
                ) from e
            raise
        finally:
            await p.aclose()


class PurposeProvider:
    """``LLMProvider`` view of a ``SwitchableProvider`` bound to one purpose (e.g. the radio)."""

    def __init__(self, parent: SwitchableProvider, purpose: str, role: Role | None = None) -> None:
        self.parent = parent
        self.purpose = purpose
        self.role = role
        self.name = f"{parent.name}:{purpose}"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 300,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult:
        return await self.parent.chat(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            json_schema=json_schema,
            timeout_s=timeout_s,
            purpose=self.purpose,
            role=self.role,
        )

    async def health(self) -> ProviderHealth:
        return await self.parent.health(self.purpose, self.role or "primary")


def presets_public() -> list[dict[str, Any]]:
    return [p.public() for p in PRESETS.values()]


def price_table() -> dict[str, dict[str, Any]]:
    return {m: asdict(p) for m, p in ANTHROPIC_PRICES.items()}


__all__ = [
    "KEY_NAMES",
    "PRESETS",
    "PRIVACY_NOTICE",
    "PRIVACY_NOTICE_VERSION",
    "ROLES",
    "ConfigError",
    "LLMConfig",
    "Preset",
    "Price",
    "ProviderSpec",
    "PurposeProvider",
    "SwitchableProvider",
    "UsageLedger",
    "check_base_url",
    "check_vendor_host",
    "config_from_settings",
    "is_local_host",
    "key_name_for",
    "on_vendor_host",
    "parse_config",
    "presets_public",
    "redact_messages",
    "redact_names",
]
