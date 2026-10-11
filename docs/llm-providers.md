# AI engineer models: local and cloud providers

Pitwall's AI race engineer can explain your session with a model running on this Mac (the default), with a cloud
model (so people without a local model can use pitwall), or with no model at all. Whatever you pick:

- **Coaching cues, corner analysis and braking advice never use a language model.** They are deterministic.
- The model only rephrases a **fact sheet** pitwall has already computed and checked. Every answer passes the
  grounding check (`ai/grounding.py`: every number must come from a cited fact) or is replaced by a deterministic
  answer built from the facts. If every configured model is down, blocked or over budget, the engineer still
  answers - from the facts alone.

Configure it on the dashboard: **Settings > AI engineer** (Off / Local / Cloud). Changes apply immediately; nothing
restarts and the radio keeps working.

## How it fits together

| Piece | File | Role |
|---|---|---|
| Providers | `src/pitwall/ai/providers.py` | `OpenAICompatibleProvider` (llama.cpp, LM Studio, Ollama, MLX, OpenAI, OpenRouter, Gemini, Groq, Mistral) and `AnthropicProvider` (official `anthropic` SDK). Circuit breaker on both. |
| Registry | `src/pitwall/ai/provider_registry.py` | Presets, the saved config (SettingsStore section `llm`), privacy gating, name redaction, usage/cost ledger, and `SwitchableProvider` - the one `LLMProvider` object the engineer and radio hold, which hot-swaps when settings change. |
| API | `src/pitwall/api/routes_llm.py` | `/api/llm/*` (below). |
| UI | `web/src/views/SettingsView.svelte`, `web/src/lib/llm.ts` | The settings page. |

Purpose routing: dashboard questions use the **engineer** model; spoken radio answers use the **radio** model
(pick a fast one). A primary provider can have a **fallback** (cloud first and local if the cloud fails, or the
other way round).

## Local models (private, free)

| Preset | Default URL | Notes |
|---|---|---|
| llama.cpp `llama-server` | `http://127.0.0.1:8081/v1` | This Mac's install (llama-server's own default port is 8080). Uses llama.cpp's `cache_prompt`. |
| LM Studio | `http://127.0.0.1:1234/v1` | Start the server from LM Studio's Developer tab. |
| Ollama | `http://127.0.0.1:11434/v1` | `ollama serve`; model ids look like `qwen3:8b`. |
| MLX (`mlx_lm.server`) | `http://127.0.0.1:8080/v1` | Structured JSON output is not documented for it (the engineer does not need it). |
| Other OpenAI-compatible | (enter the URL) | vLLM, another Mac on your LAN/tailnet, etc. |

"Local" means the host is this Mac, your LAN (10/8, 172.16/12, 192.168/16), link-local, your tailnet
(100.64.0.0/10, `*.ts.net`), `*.local`, or a single-label hostname. Plain `http://` is allowed only for those.
A "local" preset pointed at an internet host is treated as **cloud** (https and the privacy acknowledgement are
required). Leave the model empty to use the first model the server reports.

A secured local server (llama.cpp `--api-key`, vLLM...) uses the **local server key** `llm_api_key`
(`PITWALL_LLM_API_KEY`, also read from pitwall's `.env`). It is only ever sent to local hosts.

## Cloud models

Cloud is **off until you turn it on and acknowledge the privacy notice** (see Privacy). Keys are entered on the
settings page and stored only in `data/secrets.json` (mode 0600); an environment variable always wins.

| Provider | Base URL (from the vendor docs) | Key name / env override | Docs |
|---|---|---|---|
| Anthropic Claude | `https://api.anthropic.com` | `anthropic_api_key` / `PITWALL_ANTHROPIC_API_KEY` | https://platform.claude.com/docs |
| OpenAI | `https://api.openai.com/v1` | `openai_api_key` / `PITWALL_OPENAI_API_KEY` | https://platform.openai.com/docs |
| OpenRouter | `https://openrouter.ai/api/v1` | `openrouter_api_key` / `PITWALL_OPENROUTER_API_KEY` | https://openrouter.ai/docs/quickstart |
| Google Gemini (OpenAI-compatible) | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini_api_key` / `PITWALL_GEMINI_API_KEY` | https://ai.google.dev/gemini-api/docs/openai |
| Groq | `https://api.groq.com/openai/v1` | `groq_api_key` / `PITWALL_GROQ_API_KEY` | https://console.groq.com/docs/openai |
| Mistral | `https://api.mistral.ai/v1` | `mistral_api_key` / `PITWALL_MISTRAL_API_KEY` | https://docs.mistral.ai/api/ |
| Other OpenAI-compatible (internet host) | your https URL | `custom_api_key` / `PITWALL_CUSTOM_API_KEY` | - |

**A key only ever goes to the endpoint it belongs to.** The vendor presets are pinned to the vendor's host: a
different host is refused when saving (another path on the same host is fine); use "Other OpenAI-compatible server"
for proxies or other endpoints - it has its own key. The custom cloud key is never sent to a local server and the
local server key never leaves your network.

Pick models per purpose; **Load available models** lists what your key can use (it sends only the key, never
telemetry). For a vendor preset it always asks the vendor's own host. For a custom or local server it sends the
saved key only if the URL is the one saved in the settings - so list models for a new custom URL after saving it.
Cloud providers have no default model: both purposes must resolve to a model.

### Recommended: Anthropic Claude

| Use | Model | Why |
|---|---|---|
| Engineer (dashboard) | `claude-opus-5-5` | Most capable; depth for debriefs and "why" questions. |
| Radio (spoken) | `claude-haiku-5-5` | Fastest and cheapest; radio answers are 1-3 sentences. |
| Middle ground | `claude-sonnet-5-5` | Near-Opus quality at half the price. |

Prices (USD per million tokens, base input / output, from https://platform.claude.com/docs/en/about-claude/pricing,
checked 2026-10-10): Opus 5.5 $4 / $20, Sonnet 5.5 $2 / $10, Haiku 5.5 $0.10 / $0.50 (prompts up to 100K tokens;
$0.50 / $2.50 above). Pitwall uses no prompt caching or batch, so base rates apply.

Rough cost per question (estimate, not a measurement of Claude's tokenizer): the real Austria race fact sheet
produced a 1,698-character request (522 prompt tokens on the local Qwen tokenizer). Assuming ~700 input tokens and
up to ~350 output tokens including brief thinking: **Haiku 5.5 ≈ $0.0003, Sonnet 5.5 ≈ $0.005, Opus 5.5 ≈ $0.01**
per question; an answer that fails the grounding check is retried once (double). The usage panel shows real
token counts from the API responses.

How pitwall calls Claude (verified against the platform docs):

- Messages API through the official `anthropic` Python SDK (`AsyncAnthropic`), given the key and base URL
  explicitly so it never picks up `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` or an `ant` CLI profile.
- The system prompt goes in `system`; no `temperature` (current models reject non-default sampling values); no
  `thinking` field (adaptive by default; Opus 5.5 cannot disable it). **Thinking effort** (`output_config.effort`,
  default `low`) is the speed/cost control. Thinking counts toward `max_tokens`, so 1,024 tokens of headroom are
  added to the answer budget.
- Structured output (when a caller asks for JSON) uses `output_config.format = {"type": "json_schema", ...}`.
- Opus 5.5 / Sonnet 5.5 requests opt into Anthropic's **server-side refusal fallback** (`fallbacks: "default"`,
  beta `server-side-fallback-2026-07-01`): if a safety classifier declines, the API retries on the model Anthropic
  recommends, inside the same call. Haiku 5.5 has no server-side fallback, so it is not sent. If your account
  rejects the opt-in, pitwall drops it automatically. A refusal that still happens is treated like "model
  unavailable": the engineer answers from the facts.

### Other cloud providers

They use the OpenAI chat-completions format. Differences pitwall handles:

- No llama.cpp `cache_prompt` field (hosted APIs reject unknown fields).
- OpenAI: `max_completion_tokens` instead of `max_tokens`, and the default temperature (reasoning models such as
  the o-series and GPT-5 reject anything else).
- 1,024 tokens of headroom for hidden reasoning tokens.
- Health checks list `/models` (proves reachability and, except on OpenRouter, the key).

Prices for these are not built in. If you set a daily budget, enter the model's input/output price (from the
provider's pricing page) on the settings page - a model without a known price is blocked while a budget is set,
rather than running unmetered. A price entered for `gpt-5` also covers the dated snapshot ids the provider reports
back (`gpt-5-2025-08-07`); the longest matching id wins, so `gpt-5-mini` needs its own price.

## Privacy

Before the first cloud call you must tick **"I understand what is sent"**. The notice says:

- Data goes to a third-party company over the internet.
- Sent: the question (typed, or the transcript of what you said - never audio), a fact sheet derived from your
  telemetry (lap and sector times, corner deltas, braking/throttle observations, tyre and fuel figures, track, car,
  session type, weather) and your last few exchanges with the engineer.
- Not sent: raw telemetry, captures, other settings, keys of other providers (each key only goes to its own
  endpoint, see Cloud models).
- The provider may retain requests under its own terms, and calls are billed to your account.

Safeguards:

- **Consent is enforced twice**: saving a cloud provider requires cloud enabled + the current notice acknowledged
  (`PRIVACY_NOTICE_VERSION`; bumping it requires everyone to re-acknowledge), and every call re-checks it - a
  hand-edited `data/settings.json` cannot bypass it (an invalid saved config falls back to the local defaults and
  the settings page shows why). The page sends the notice version it displayed; if the notice changed since the
  page loaded the server answers 409 and the page shows the new notice, so an old tab cannot acknowledge text it
  never showed. The config in force is re-read before every attempt, so turning cloud off while a local answer
  is still running also stops the cloud fallback for that question.
- **Driver names are replaced with "the driver"** in everything sent to a cloud provider (on by default; toggle on
  the settings page). Names come from driver profiles; matching is whole-word and case-sensitive, so "Max" the
  driver is redacted but "max speed" is not. Local models see real names. Redaction **fails closed**: if the
  names cannot be read (and there is no earlier read, or a driver was added/renamed since), the cloud call is
  skipped and the fallback or the fact answer is used instead.
- **What gets sent**: the settings page shows the exact body of the last request (HTTP headers, which carry the
  key, are omitted; any configured key value found in the body is replaced with `[redacted secret]`).
- **Keys** are write-only through the API: responses only ever contain a masked form such as `sk-ant-…1234`.
  The key endpoint parses its body by hand so even a malformed request is never echoed back. Keys and prompts are
  never logged (config changes are logged at INFO with provider and model names only).
- Cloud base URLs must be `https://` and may not contain credentials or query strings.
- Cross-site pages cannot drive these endpoints: changes are PUT/DELETE (always CORS-preflighted, never granted)
  and the POSTs require `Content-Type: application/json` (415 otherwise). The only GET that reaches out is the
  health check of the saved providers (each with its own key, no tokens spent); nothing that takes a URL or spends
  tokens is a GET.
- The connection **Test** uses canned sample facts ("PITWALL CONNECTION TEST"), never your telemetry.

## Costs, usage and the daily budget

- Every call is recorded per local day and provider/model in `data/llm_usage.json` (tokens, calls, errors, blocked
  calls, estimated cloud cost; 90 days kept). It is rewritten after each call, so the budget survives restarts.
- **Daily budget (USD)**: once today's estimated cloud cost reaches it, cloud calls are blocked with the reason
  "daily cloud budget reached (...)" until local midnight or until you raise it; a configured fallback (e.g. the
  local model) answers instead. The check runs before each call, so the last call can overshoot by one call's cost.
- A call is priced by the model id the provider reports it **served** (e.g. a dated snapshot), falling back to
  the configured id. Calls the provider billed without a usable answer - a Claude refusal, or an answer cut off by
  the token limit - are counted with their tokens and cost.
- Unknown stays unknown: if a cloud call made while a budget is set reports no token counts, today's spend can no
  longer be checked, so cloud calls pause for the rest of the day ("... spend is unknown") unless you remove the
  budget.
- Costs are estimates from published prices and the token counts the provider returns; your provider's bill is
  authoritative. Declined attempts inside a server-side fallback (beyond what the final response reports) and failed
  calls that return no usage (network errors, 5xx) are not counted.

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/llm/providers?health=false` | Presets, saved config, status per provider, masked keys, privacy notice. `health=true` adds a reachability check (no tokens used; cloud only when allowed). |
| PUT | `/api/llm/config` | Body: `{enabled, primary, fallback, privacy: {cloud_enabled, acknowledged_notice_version, redact_driver_names}, budget: {daily_usd}, prices}`. 422 with the offending field on validation errors; 409 if `acknowledged_notice_version` is not the current notice. |
| PUT | `/api/llm/keys/{name}` | `{"value": "..."}`. Names: `anthropic_api_key`, `openai_api_key`, `openrouter_api_key`, `gemini_api_key`, `groq_api_key`, `mistral_api_key`, `llm_api_key` (local servers), `custom_api_key` (custom internet host). |
| DELETE | `/api/llm/keys/{name}` | Removes the stored key (an environment variable or `.env` value still applies). |
| POST | `/api/llm/test` | JSON `{role: primary|fallback, purpose: engineer|radio}`: health + one grounded question through `RaceEngineer`; reports latency, model, grounding. Billed like any call. |
| POST | `/api/llm/models` | JSON `{provider, base_url}`: models the provider offers (keys only to their own endpoint, see above). |
| GET | `/api/llm/usage` | Today, recent days, budget state, last blocked call. |
| GET | `/api/llm/last-request` | The last request preview. |
| GET | `/api/llm/health` | (in `api/app.py`) health of the primary provider. |

## Defaults and environment

While the `llm` settings section is empty, the old environment settings apply: `PITWALL_LLM_ENABLED`,
`PITWALL_LLM_BASE_URL` (llama.cpp preset if the host is local, otherwise "other OpenAI-compatible" - which counts as
cloud and needs the acknowledgement), `PITWALL_LLM_MODEL`, `PITWALL_LLM_TIMEOUT_S`, `PITWALL_LLM_MAX_TOKENS`.
Saving from the settings page takes over from then on.

Keys: a key saved on the settings page (`data/secrets.json`) or exported as `PITWALL_<NAME>` is used first; the
`PITWALL_LLM_API_KEY` value in pitwall's `.env` still applies to local servers when neither is set (the app
passes it as a default key; the settings page shows it as "from pitwall's .env").

## Troubleshooting

| Symptom | Fix |
|---|---|
| "no API key saved (anthropic_api_key)" | Save the key on the settings page or set `PITWALL_ANTHROPIC_API_KEY`. |
| "Anthropic rejected the API key (401)" | Wrong or revoked key. |
| "model ... not found (404)" | The key's organisation cannot use that model; use **Load available models**. |
| "daily cloud budget reached" | Raise the budget, wait for midnight, or add a local fallback. |
| "circuit breaker open" | Three failures in a row; calls resume after 30 s. |
| "answer cut off by max_tokens" | Lower thinking effort or raise "Max answer tokens" (Advanced). A cut-off answer is never spoken or shown; the fact answer is used. |
| "... spend is unknown; cloud calls resume tomorrow" | A cloud call under a budget reported no token counts. Remove the budget or wait until tomorrow. |
| "driver names could not be read" | Driver profiles could not be read, so names could not be redacted; the cloud was skipped. Usually transient. |
| "the privacy notice has changed" when saving | The notice text was updated: read it on the page and tick the box again. |
| "must be on api.anthropic.com" (or another vendor host) | Vendor keys only go to the vendor; use "Other OpenAI-compatible server" for other endpoints. |
| Test says "fell back to facts" with unsupported numbers | The model invented numbers; the grounding check caught it. Try a stronger model. |

## Limitations

- Cut-off detection is Claude-only: OpenAI-compatible servers (including local llama.cpp) return an answer stopped
  by the token limit (`finish_reason: "length"`) as-is; that provider's behaviour is deliberately unchanged.
- No streaming: answers arrive whole (they are short).
- Claude on Amazon Bedrock / Google Vertex AI / Microsoft Foundry is not wired up (different clients and auth).
- Prices for non-Anthropic models must be entered by hand to enforce a budget.
