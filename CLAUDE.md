# Pitwall - AI sim racing coach & race engineer

Python 3.12 (uv) backend + React/HeroUI dashboard (`web-react/`, served at `/`; the Svelte dashboard in `web/` is
the frozen fallback, served only while `web-react/dist` is not built). Multi-game telemetry -> unified model ->
deterministic analysis/coaching -> LLM race engineer (local or cloud) that only explains validated facts.
Runs on macOS (primary) and Windows (new: not yet validated live with a game on a Windows PC).

**First-time setup on a new machine: run `/setup-pitwall`** (`.claude/skills/setup-pitwall/`), and
`uv run pitwall doctor` (`--json` for scripts) to check an install - it reports OK/INFO/WARN/FAIL with a fix each.
Machine-specific notes for the owner's computer live in `CLAUDE.local.md` (gitignored) when present; it is per
checkout, so each checkout or worktree needs its own copy. The safety rules below apply everywhere regardless.

## Commands
```bash
uv sync --all-extras                 # install (Python deps incl. voice + MCP dev tool extras)
uv run pitwall doctor [--json]       # check this machine's setup (read-only; exit 1 on FAIL)
make web-react                       # React dashboard (web-react/dist, npm ci + build:root); needs a HeroUI Pro licence
make web                             # Svelte fallback dashboard (web/dist); run `cd web && npm ci` first; needs node
uv run pitwall serve                 # dashboard http://127.0.0.1:8770 + UDP 20777 listener
uv run pitwall simulate              # write SYNTHETIC F1 capture with known injected mistakes
uv run pitwall replay <capture>      # headless: capture -> DB -> analysis
uv run pitwall send <capture>        # stream a capture over real UDP (emulates a console)
uv run pitwall report | ask "..." | sessions | capabilities | llm-check | token
make check                           # ruff + mypy --strict + pytest (+ svelte-check) - must pass before commit
make web-react-check                 # React dashboard: tsc (strict) + vitest
scripts/pitwall-service.sh install|status|logs|restart-when-idle  # macOS launchd agent com.pitwall.server (refuses to restart while a game is live)
scripts/release.sh [ref]             # macOS deploy: tests + builds a COMMITTED ref in a release worktree (PITWALL_RELEASE_DIR), waits until nobody drives, repoints launchd
uv run python scripts/package_release.py --version vX.Y.Z --out <dir>   # release zip with the prebuilt dashboard (docs/releasing.md; CI does this on v* tags)
uv run pytest -m llm                 # real local-LLM test (slow, opt-in)
uv run pytest -m live tests/live -s  # with a real game streaming (manual)
```

Windows (PowerShell; from Claude Code's Git Bash use forward slashes). `uv run pitwall ...` is identical; there is
no `make`, so run the npm steps directly (`cd web; npm ci; npm run build` or in `web-react`: `npm run build:root`):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 [-NonInteractive] [-Dashboard auto|react|svelte|none]
powershell -ExecutionPolicy Bypass -File scripts\windows\pitwall.ps1        # run the server (Ctrl+C stops)
powershell -ExecutionPolicy Bypass -File scripts\windows\firewall.ps1 add   # inbound rules (as Administrator)
powershell -ExecutionPolicy Bypass -File scripts\windows\service.ps1 install|status|logs|stop|uninstall  # start at logon
uv run ruff check src tests; uv run ruff format --check src tests; uv run mypy; uv run pytest -q   # = make check (Python)
```

## Architecture (see docs/architecture.md)
`ingest/` (UDP thread, .pwcap capture, replay) -> `adapters/<game>/` (pure decode, no I/O) ->
`model/telemetry.py` (CarFrame / SessionInfo / GameEvent / CarSetup / LapCompletion) ->
`core/session.py` (sessions, LapAssembler) -> `core/lap_processor.py` (background thread: persist, learn
track model, pick reference, compare, observations) -> `storage/` (SQLite WAL, single writer thread) ->
`api/app.py` (REST + /ws/live) -> `web-react/` (`web/` fallback). AI: `ai/facts.py` -> `ai/engineer.py` ->
`ai/grounding.py`; providers in `ai/provider_registry.py` (Settings > AI engineer). Setup check: `doctor.py`.

## Non-negotiable rules
- **No LLM in the time-critical path.** Braking cues/coaching are deterministic (`analysis/`, `coach/`).
  The LLM only explains facts from `ai/facts.py`; answers pass `check_grounding` or fall back to a
  deterministic answer. The app must work fully with the LLM down.
- **Unknown stays unknown.** Adapters never fabricate values; missing = `None`. Units live in field names.
  Wheel order is always FL, FR, RL, RR (F1 sends RL, RR, FL, FR - use `Wheels.from_rl_rr_fl_fr`).
- **Never block ingest.** UDP thread: timestamp -> capture queue -> decode -> O(1) state updates only.
  DB writes go through `DbWriter`; lap analysis through `AnalysisWorker`.
- **Protocol accuracy.** F1 structs must match EA's spec; `tests/unit/test_f1_protocol.py` machine-checks
  them against `docs/research/f1-udp-spec.md`. Add new games from official/community docs only - never guess
  packet layouts.
- **Evidence tiers.** synthetic (generated, `pytest -m synthetic`) != recorded (real captures in
  `tests/fixtures/recorded`) != live (`-m live`). Never present synthetic results as game compatibility.
  Synthetic streams carry `SYNTHETIC_SESSION_UID` and are flagged synthetic everywhere; synthetic replays
  use `synthetic:` track ids so they cannot pollute real track models. Platforms too: passing CI on Windows is
  "CI-tested", not "live-validated with a game on a Windows PC".
- **Capability claims** live in `src/pitwall/capabilities.py`; only upgrade a status with evidence.
- **Licences.** Do not copy code from GPL/unlicensed repos (see docs/licences.md). Implement from specs. HeroUI Pro
  is licensed: never copy its source into the repo; never ask for, read or print `HEROUI_AUTH_TOKEN`.
- **Platform guards.** macOS behaviour is the reference; Windows support is additive and guarded by `sys.platform`
  (`compat.py`). macOS-only: Parakeet STT, Kokoro/`say` TTS, launchd scripts.
- Coaching never recommends braking later on its own; later braking is praised only if the corner got faster.
- **Shared machines.** Pitwall usually runs next to other services and agents. Never change or remove a
  `tailscale serve` mapping you did not create, and never reuse a serve port that `tailscale serve status` lists
  (443 is often another service's). Never bind, take over or kill a port another program holds (`pitwall doctor`
  reports busy ports): pick a free one. Never stop or restart a running Pitwall (service or by hand) while
  `/api/health` reports telemetry `live` - someone is driving. A local LLM server may be shared with other agents
  and short of memory: keep requests small and turn the LLM off in anything you run for testing.

## Network / voice
- Phones/tablets: LAN link with the access token (`uv run pitwall token`, Setup > Connect), or Tailscale serve for
  HTTPS (`tailscale serve --bg --https=<port> http://127.0.0.1:8770` on a port not already served - the radio's
  microphone needs HTTPS). Auth: `api/auth.py` (local / Tailscale identity / token). Uvicorn MUST run
  with `proxy_headers=False` or Tailscale requests are misattributed. The Tailscale CLI needs `TAILSCALE_BE_CLI=1`
  under launchd.
- Radio: `voice/hub.py` (asyncio) + `/ws/radio` (protocol: docs/voice-protocol.md). STT Parakeet-MLX (Apple
  silicon), TTS Kokoro / macOS `say` / Windows SAPI, or device-side Web Speech voices (iPad Premium voices).
  Proactive messages only in speak windows (`voice/scheduler.py`), re-checked after synthesis. Setup guide:
  docs/radio-setup.md.
- Connect page (`connect.py`, `/api/connect`): game telemetry settings + live UDP senders.

## Local LLM as a dev tool (Claude Code, optional)
`.mcp.json` registers `pitwall.devtools.qwen_mcp` (read-only tools: `qwen_status`, `qwen_ask`,
`qwen_review_code`, `qwen_generate_tests`) against an OpenAI-compatible server at `QWEN_BASE_URL` (default
`http://127.0.0.1:8081/v1`). Its output is ADVISORY: Claude owns architecture and final validation; never apply
its suggested changes without review + passing tests. It refuses while a real race session is live.

## Conventions
- Dataclasses (slots) on hot paths; pydantic only at the API edge. orjson responses (NaN -> null).
- All SQL in `storage/repo.py`. Schema in `storage/db.py` (bump SCHEMA_VERSION + migrate when changing).
- Settings: deploy-time in `config.py` (`PITWALL_<NAME>` env / `.env`, read from the working directory);
  dashboard-editable in `data/settings.json` (`settings_store.py`), API keys in `data/secrets.json`.
- Docs to keep current: `docs/status.md` (what works / what's unverified), `docs/architecture.md`,
  `docs/licences.md`, capability matrix in code, `/setup-pitwall` skill + `doctor.py` when setup changes.
