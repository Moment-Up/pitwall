---
name: setup-pitwall
description: Guided first-time setup of Pitwall (sim-racing telemetry coach) on this computer, macOS or Windows - from an unzipped release (dashboard prebuilt, no Node.js) or a git clone - prerequisites, install, synthetic demo, the user's game telemetry settings, phone/iPad access, optional voice / AI engineer / start at login, finishing with `uv run pitwall doctor` all OK. Use right after unzipping a release or cloning the repo, or when the user asks to install, set up, update, configure or repair Pitwall, or says no telemetry arrives.
argument-hint: "[optional: your game and platform, e.g. F1 25 on PS5]"
---

# Set up Pitwall

Guide a user from an unzipped release (or a fresh clone) to "my game's telemetry shows up on the dashboard". Work in
the folder Claude Code was opened in (the Pitwall folder). Keep messages short; one step at a time; say what you are
about to run and why. If the user passed arguments (`$ARGUMENTS`), treat them as their answer to "which game and
platform?" in step 6.

Reference files (read the one for this OS now, the others when the step needs them):
[macos.md](macos.md) | [windows.md](windows.md) | [games.md](games.md) | [troubleshooting.md](troubleshooting.md)

**Ask about the game early.** Before the install (step 3), unless `$ARGUMENTS` already answers it, ask: "Which game
and platform will you play?" Look it up in games.md. If Pitwall cannot read that game ("Not supported" there), say so
now, before the user spends time installing, and say what is left (the synthetic demo; recording the game's packets
if it sends UDP telemetry). Pitwall itself is told the game in step 6, once it is installed and running.

If Claude Code asked the user to enable this project's MCP server `qwen` (from `.mcp.json`): that is the maintainer's
optional local-model dev tool (it expects a model server at 127.0.0.1:8081 and creates `.venv` when it starts).
Setup does not need it; recommend "No" unless they run such a server.

## Rules (apply to every step)

- **Game support comes from the code.** Support claims come from `uv run pitwall game show` /
  `uv run pitwall capabilities` (both built from `src/pitwall/capabilities.py` and the adapters' field
  declarations); never round up. Keep two things apart: "the game does not send X" (known in advance for the
  selected game) and "X has not arrived yet" (a runtime state, shown as `-`).
- **Ask before you change the machine.** Every install, download, firewall rule, network setting, start-at-login
  item, `.env` edit, file move or model download needs the user's yes for that action. Read-only checks need no
  permission.
- **Secrets stay out of the chat.** Claude never asks for, reads, prints or pastes `HEROUI_AUTH_TOKEN`, API keys, the
  access token, `~/.npmrc`, `.env` values or `data/secrets.json`. Do not dump the environment (`env`, `printenv`,
  `set`). The user types API keys into the dashboard (Settings > AI engineer) and copies the LAN link with its token
  from Setup > Connect, or runs `uv run pitwall token` in their own terminal. `uv run pitwall serve` prints that
  token: send its output to a log file and never show the `token=` line.
- **Accounts are the user's.** They sign in to Tailscale, HeroUI, GitHub or an AI provider themselves.
- **The licence is not yours to work around.** HeroUI Pro needs the user's own licence to build from source. Never
  copy `web-react/dist` from a release into a clone (or anywhere else), never extract files from it, never look for
  tokens. Without a licence: a release, or the classic dashboard.
- **Be honest about support.** The synthetic demo proves the install works, not that a game works. Quote game
  support from `uv run pitwall capabilities` (source: `src/pitwall/capabilities.py`); never upgrade it. Windows is
  CI-tested on Windows (GitHub runners), not yet validated live with a game on a Windows PC - say so. Linux and
  Intel Macs have not been run.
- **Never take over a busy port** or stop someone else's program: report it and ask. Never use Tailscale serve port
  443 (or any port `tailscale serve status` already lists) without the user confirming it is free.
- Do not edit Pitwall's own files during setup; configuration goes in the dashboard or the folder's `.env`.
- **Long first installs.** `uv sync --all-extras` (hundreds of MB), `npm ci` and the dashboard build can each take
  minutes on a fresh machine, and `install.ps1` does several of them in one call: run them with the Bash tool's
  `timeout: 600000`, or with `run_in_background` and poll. If a run is cut off, run it again: uv and npm resume
  from their caches.
- **Paths come from doctor.** The data folder is doctor's `data_dir` (`data` in the Pitwall folder unless
  `PITWALL_DATA_DIR` says otherwise): use it, or the path a command printed, instead of assuming `data/`.

## 0. What kind of folder is this?

Run (read-only) in the Pitwall folder:

```bash
test -f RELEASE.txt && test -f web-react/dist/index.html && grep -q 'src="/assets/' web-react/dist/index.html && ! grep -q '"/next/' web-react/dist/index.html && echo release
git rev-parse --is-inside-work-tree 2>/dev/null
```

- **Release** (prints `release`): an unzipped `pitwall-<version>.zip`. The new dashboard is prebuilt for `/`. Tell
  the user the version (first line of `RELEASE.txt`). **Skip every dashboard build, every Node.js/npm step and the
  HeroUI Pro question (step 2).** Node.js and git are not needed.
- **Git clone** (`true`, no `RELEASE.txt`): go through every step. Step 2 decides the dashboard.
- **Neither** (for example GitHub's "Source code" zip, which has no built dashboard and no `.git`): explain that
  this download lacks the dashboard, and offer [the release download](#download-the-latest-release) (recommended)
  or the classic dashboard build as in a clone.
- `RELEASE.txt` but no usable `web-react/dist/index.html`: the zip was not unzipped completely. Ask the user to
  unzip it again into an empty folder (or offer the release download).

## 1. Platform and prerequisites

1. The platform is in your environment info (darwin = macOS, win32 = Windows). On Windows your Bash tool is Git
   Bash: use forward slashes and run PowerShell scripts as
   `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/<script>.ps1 <args>`.
   Linux has no installer or service scripts yet: follow the macOS steps manually and say it is untested.
2. Check: `uv --version` always; in a clone also `git --version` and `node --version`. Needed: uv (it installs
   Python 3.12 itself - never install Python separately). In a clone only: Node.js 20.19+ or 22.12+ to build a
   dashboard (22.12+ for the new one). A release needs neither Node.js nor git.
3. Missing tools: propose the install command from macos.md / windows.md, ask, run it. A fresh install may not be on
   this session's PATH: if `uv`/`node` still is not found, ask the user to restart Claude Code (or the terminal).

## 2. Dashboard choice (clone only) - ask before installing

Skip this step in a release: its dashboard is already built.

The new dashboard (`web-react/`, React + HeroUI) uses **HeroUI Pro**, a commercial component library. Building it
from source needs the user's own HeroUI Pro licence: its npm package only installs fully with a HeroUI Pro login
(`npx heroui-pro@latest login`) or `HEROUI_AUTH_TOKEN`. Without either, `npm ci` still looks successful, and the
build then fails with `Can't resolve '@heroui-pro/react/...'`. If `web-react/dist/index.html` already exists and
doctor's `dashboard` check is ok, it is built: skip the build. Otherwise explain this, then ask: "Do you have a
HeroUI Pro licence, and is this computer already logged in (`npx heroui-pro@latest login`) or is
`HEROUI_AUTH_TOKEN` set in your environment?"

- **Yes** -> the new dashboard. The user sets the token or login up themselves; you never see it.
- **No / not sure** -> offer two choices:
  1. **Download the latest release** (recommended): the new dashboard prebuilt, no Node.js. See
     [Download the latest release](#download-the-latest-release). Pitwall then runs from the release folder, not
     from this clone.
  2. **The classic dashboard** (`web/`, Svelte), built in this clone. Pitwall serves it automatically whenever
     `web-react/dist` is not built. It is the earlier dashboard (fixes only) with the same core tabs (Live,
     Sessions, Engineer, Radio, Connect, Settings); newer pages such as Drive > Coach exist only in the new one.

Where things are (new dashboard / classic dashboard): the live car = Drive / Live tab; game setup and the LAN link
= Setup > Connect / Connect tab (not the classic Setup tab, which is the rig walkthrough); AI provider and keys =
Settings > AI engineer / Settings tab; radio voice = Settings > Radio & voice / Radio tab. The steps below name the
new dashboard's locations; translate them for a classic user.

### Download the latest release

Ask first (it downloads about 15 MB from GitHub), and ask where to put it: a new folder **outside** this clone that
the user keeps, for example next to it or `~/Pitwall` (not Downloads, Desktop or Documents: the data lives in the
release folder, and macOS can stop the launchd service from reading those folders). Then, in that folder:

1. Find the latest version: `gh release view --repo Moment-Up/pitwall --json tagName --jq .tagName` (needs a
   signed-in `gh`), or without gh:
   `curl -fsSLI -o /dev/null -w '%{url_effective}\n' https://github.com/Moment-Up/pitwall/releases/latest`
   (the version is the last part of the printed URL, e.g. `v0.1.0`).
2. Download the zip and its checksum:
   `gh release download <version> --repo Moment-Up/pitwall --pattern 'pitwall-*'`, or
   `curl -fLO https://github.com/Moment-Up/pitwall/releases/download/<version>/pitwall-<version>.zip` and the same
   URL with `.zip.sha256`.
3. Verify before anything else: macOS `shasum -a 256 -c pitwall-<version>.zip.sha256`, Windows (Git Bash)
   `sha256sum -c pitwall-<version>.zip.sha256`. It must print `pitwall-<version>.zip: OK`. Anything else: stop,
   delete both files, tell the user, and do not unzip.
4. Unzip: macOS `unzip -q pitwall-<version>.zip`; Windows
   `powershell -NoProfile -Command 'Expand-Archive -LiteralPath pitwall-<version>.zip -DestinationPath .'`
   (fill in the version).
5. Tell the user: run Pitwall from `pitwall-<version>/`, not from the clone. Ask them to open Claude Code in that
   folder and run `/setup-pitwall` there; setup continues there and skips the dashboard build. Do not copy
   `web-react/dist` into the clone. If this clone already has a data folder with sessions (doctor `data_dir`), offer
   to move it into the release folder later (with Pitwall stopped; see "Updating" below).

## 3. Install

- **Release, macOS (and Linux):** `uv sync --all-extras`. Nothing else: no npm.
- **Release, Windows:** read the header of `scripts/windows/install.ps1`, then run
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install.ps1 -NonInteractive` (no
  `-Dashboard` option: the default `auto` keeps the release's prebuilt dashboard). It says "release folder", skips
  git and Node.js, runs `uv sync --all-extras`, checks the server imports and makes the data folder private; doctor's
  `dashboard` check then confirms the prebuilt dashboard. If it says the release has no prebuilt dashboard, the zip
  was not unzipped completely (step 0).
- **Clone, macOS:** `uv sync --all-extras`, then the dashboard: new
  `(cd web-react && npm ci --no-audit --no-fund && npm run build:root)`, or classic
  `(cd web && npm ci --no-audit --no-fund && npm run build)`. Details: macos.md. Use `npm ci`, never `npm install`
  or `npm audit fix` (they rewrite the lockfiles).
- **Clone, Windows:** read the header of `scripts/windows/install.ps1`, then run it non-interactively (its own y/N
  prompts cannot be answered from here - you install missing prerequisites in step 1 instead):
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install.ps1 -NonInteractive -Dashboard svelte`
  (`-Dashboard react` for licence holders). It runs `uv sync --all-extras`, builds the dashboard and creates `data`.
- If the new dashboard's install or build fails on HeroUI Pro (`npm ci`: "Access denied ... HeroUI Pro" for an
  expired or invalid login; or `npm ci` looked fine and the build says `Can't resolve '@heroui-pro/react/...'`: no
  licence on this computer): stop, tell the user, and offer the release download or the classic dashboard.

## 4. Doctor

Until step 6, doctor's `game` check is info ("no game selected"): expected. Do not select a game here.

Run `uv run pitwall doctor --json` and read `summary` and `checks` (each has `status` ok|info|warn|fail, `detail`,
`fix`). Fix every `fail` using its `fix` line (asking first when it changes the machine). Expected at this point and
fine: `telemetry` info (server not running), `access_token` warn (created on first start), `llm` warn when no AI
model runs (step 8 settles it), and in a release `node` info (only needed to rebuild the dashboard). Keep
`data_dir`, `lan_ip`, `http_port` and `urls` for later steps, and on Windows `firewall_rules` (always `[]`
elsewhere). Windows: `data_private` warn means other accounts on the PC can read the data folder (token, API keys);
its `fix` is an `icacls` command - offer it, run it only with a yes.

## 5. Synthetic demo and first start

1. Demo data (headless, a few seconds; every session it creates is flagged SYNTHETIC and uses `synthetic:` track
   ids, so it never mixes with real laps): `uv run pitwall simulate` - it prints the capture it wrote
   (`<data_dir>/captures/synthetic-coaching-demo-2025.pwcap`) - then `uv run pitwall replay <that path>`, then
   `uv run pitwall report` (show the user two or three coaching lines from it).
2. Windows, before the first start: tell the user that Windows may ask whether Python may communicate on networks:
   tick **Private networks** only and click *Allow access*. Cancel creates block rules that stop telemetry
   (windows.md); ticking Public opens Python on public Wi-Fi.
3. Start the server in the background with its output in a log:
   `PYTHONIOENCODING=utf-8:replace uv run pitwall serve > <data_dir>/serve.log 2>&1` (Bash `run_in_background`;
   the variable makes Windows write the log in UTF-8, like the Windows service does, and changes nothing on macOS).
   Wait until `uv run pitwall doctor --json` shows `server.running: true` (or
   `curl -s http://127.0.0.1:<http_port>/api/health` answers). Read the log only through `grep -v "token="`.
4. Live demo: run `uv run pitwall send <data_dir>/captures/synthetic-coaching-demo-2025.pwcap --port
   <server.udp_port>` in the background (about 8 minutes in real time; add `--speed 4` to hurry) and ask the user to
   open `urls.local` (http://127.0.0.1:8770/ by default): Drive (classic: the Live tab) shows the SYNTHETIC car
   live. Stop the sender when they have seen it (or let it finish). doctor's `telemetry` stays `info` for the demo:
   only a game makes it `ok`.
5. Windows: if `firewall` is warn, explain it now (step 6 needs it). The user runs, in PowerShell opened with
   "Run as administrator" in the Pitwall folder:
   `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\firewall.ps1 add`. If `network_profile` is
   warn (Public network), the user switches the network to Private in Windows Settings themselves. See windows.md.

## 6. The user's game

Tell Pitwall which game the user plays: that switches on the game's telemetry input and gives the honest list of what
the game sends. Keep the server from step 5 running: the commands below then go through it.
Every value is also on Setup > Connect (`http://127.0.0.1:<port>/#/setup/connect`; classic dashboard: the Connect tab),
with copy buttons and the live connections.

1. **Ask** "Which game and platform do you drive?" unless the early question or `$ARGUMENTS` already answered it. On
   PC, also ask whether the game runs on this same computer. F1 25: ask whether they drive the 2026 Season Pack cars
   (the game's UDP Format 2026).
2. **Find the id:** `uv run pitwall game list --all --json`. Match the answer to one `entries[].id` (by `label` and
   `platform_label`), e.g. `f1_25:ps5`, `f1_25_2026:pc`, `gt7:ps5`, `ac:ps5` (Assetto Corsa's PS4 version on a
   PS5). A game that is not listed is `other:any`. Confirm in one line, saying what selecting changes (from
   `integration` and `transport.summary`), e.g. "Gran Turismo 7 on PS5? Selecting it switches on Pitwall's GT7
   input." That yes covers sub-step 4. If `game` is not a `pitwall` command (an older Pitwall), use games.md and
   `uv run pitwall capabilities` instead, and the user switches the game on at Setup > Connect.
3. **Console IP**, only when the entry's `transport.console_ip` is `required` (Assetto Corsa) or `optional` (GT7):
   ask for it (where to find it: games.md). AC cannot connect without it. GT7: with the IP, selecting switches the
   input on; without it, selecting only records the choice, because the input would then search the whole network
   for the console (a broadcast every 1.6 s). If the user has no IP, ask whether Pitwall may search the network;
   only on a yes, they switch GT7 on at Setup > Game > Search the network (or Setup > Connect). Only private LAN
   addresses are accepted.
4. **Select:** `uv run pitwall game set <id> [--console-ip <ip>] --json`. Tell the user each `actions[].message` in
   plain words: `enabled`, `already_enabled`, `set_platform`, `set_console_ip` = done; `needs_console_ip` = AC still
   needs it (back to 3); GT7 with the input off: no IP was given (back to 3), with the input on: optional (it
   searches the network); `skipped_live` = that input is receiving packets right now, change it on
   Setup > Connect after the session; `error` = usually a port conflict (troubleshooting.md "Port in use");
   `none` = Pitwall cannot read this game (the message says why), or for `other:any`: offer Setup > Connect >
   Record another game (ask first: it listens on a UDP port and saves every packet to disk).
   `via: "file"` = no Pitwall was running: the choice applies at its next start. Exit code 1 "predates game
   selection" = the running Pitwall is older than this folder: restart it from here (step 5), then retry. Exit
   code 1 "something listens on ... retry" = a server answers slowly (or not like Pitwall): nothing was changed;
   wait a moment and run it again (never edit settings.json by hand while a server may be running). Selecting
   never turns another game's input off. Windows: a newly enabled input listens on a new UDP port, so if doctor's
   `firewall` then warns, the user re-runs `firewall.ps1 add` as administrator (step 5.5).
5. **Steps and honest support:** `uv run pitwall game show --json`. Give the user `guide.menu_path` and
   `guide.steps` (label, value, note) with the values already filled in (this computer's IP and ports; the IP should
   equal doctor `lan_ip`), and `guide.extras` when useful. Quote `entry.support.words`, plus the gist of
   `entry.support.note`, without rounding up. `guide` is null for a game Pitwall cannot read: say so plainly
   (games.md "Not supported") and skip 6-7.
6. **Say what will stay empty**, in one sentence, from `entry.features`: the `label`s with `status` `not_sent`
   ("GT7 doesn't send ...") and `not_implemented` ("Pitwall doesn't read ... yet"), so those empty tiles are
   expected, not a fault. Leave `unknown` features out (they show `-`); if `entry.support.level` is `unverified`
   (e.g. Forza Horizon on PS5), say nobody has confirmed that version sends telemetry.
7. "Go on track (or into the garage) now." Re-run `uv run pitwall doctor --json` until `game` and `telemetry` are
   both ok and `server.synthetic` is false (a game, not the demo); Setup > Connect > Live connections shows the
   sending console's address. `game` warns "Receiving X, but Y is selected": ask the user which game they are
   playing and run doctor's `fix` (`uv run pitwall game set <id>`) only for their answer. Nothing after a minute ->
   troubleshooting.md "No telemetry arrives".

The new dashboard's Setup > Game page shows the same (picker, input, "What <game> sends") and changes the game
later. The classic dashboard has no Game page: there the game is changed with `uv run pitwall game set <id>`.

## 7. Phone or iPad

- **Dashboard on the LAN:** the user opens Setup > Connect on this computer and copies "Any browser on your network"
  (a link with the access token) to the device, or runs `uv run pitwall token` in their own terminal. The device
  must be on the same network. Windows needs the HTTP firewall rule (step 5.5).
- **Radio (push-to-talk microphone) needs HTTPS:** Tailscale on this computer and on the device, same account.
  The user installs and signs in to Tailscale. Then read doctor's `tailscale` check: its `fix` suggests a port that
  `tailscale serve status` does not use yet. Ask, then run
  `tailscale serve --bg --https=<port> http://127.0.0.1:<http_port>` (macOS CLI path: macos.md). The device opens
  `https://<this computer's tailnet name>:<port>/`. The tailnet owner's login is trusted automatically; anyone else
  needs `PITWALL_TAILSCALE_ALLOWED_LOGINS` (JSON list) in `.env`. Setup > Connect then shows this link (it reads
  `tailscale serve status` for the serve that forwards to this Pitwall's port). Remove later with
  `tailscale serve --https=<port> off`.

## 8. Optional extras - offer each, skip on "no"

- **Voice radio.** macOS on Apple silicon: speech recognition (Parakeet) came with `uv sync --all-extras`; the
  natural engineer voice is `scripts/setup-tts.sh` (downloads the Kokoro model; ask first). Otherwise the radio
  speaks with macOS `say`. Windows: the radio speaks with Windows' built-in voices (`PITWALL_TTS_SAPI_VOICE`
  picks one); spoken questions need macOS (Parakeet) or a whisper.cpp server (`PITWALL_STT_ENGINE=whispercpp`,
  tested against a mock server only); typed questions work everywhere. On any OS the iPad/phone can speak with its
  own voice: Settings > Radio & voice > Engineer voice.
- **AI engineer.** Deterministic coaching never needs a model. For explanations in plain language the user picks a
  provider at Settings > AI engineer: a local OpenAI-compatible server (LM Studio, Ollama, llama.cpp, MLX) or a cloud
  provider (Anthropic, OpenAI, OpenRouter, Gemini) - they paste any API key into that page themselves and accept its
  privacy notice for cloud use. Ask before installing any model server or downloading models (gigabytes). No AI
  wanted: turn it off on that page (or, with permission, `PITWALL_LLM_ENABLED=false` in `.env`); doctor then says
  "off (deterministic answers only)". Check the choice with doctor's `llm` check and the Test button on Settings >
  AI engineer. (`uv run pitwall llm-check` only probes `PITWALL_LLM_BASE_URL`, default 127.0.0.1:8081: it ignores
  the provider picked on the dashboard and "off".)
- **Start at login.** Stop the demo sender and the server you started in step 5 first, and check doctor's
  `telemetry` is not live. macOS: `scripts/pitwall-service.sh install` (launchd; `install` stops any running
  `pitwall serve` without checking telemetry, `restart` refuses while live). Windows:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/service.ps1 install` (Task Scheduler, no
  admin; `install`, `stop`, `restart` and `uninstall` refuse while telemetry is live). Both run Pitwall from this
  folder, so in a release it must stay where it is (see "Updating" for moving to a new release).

## 9. Finish

Run `uv run pitwall doctor` (text). Goal: `Result: OK` - info lines are fine; for any warn left, either fix it or
tell the user why it is acceptable for them. Summarise in a few lines: dashboard URL(s), the game settings they
entered, what is on/off (voice, AI, start at login), how to start Pitwall (`uv run pitwall serve` in this folder,
`scripts\windows\pitwall.ps1` on Windows, or the service), where data lives (doctor `data_dir`), and that
`uv run pitwall doctor` re-checks everything later. Stop any background process you started that the user does not
want left running: the demo sender always, first. Then wait about 3 s (the server counts as live while a packet
arrived in the last 2 s; Windows `service.ps1 stop` refuses while live, demo included) before stopping a server.

## Updating

- **Release -> newer release** (ask before each action; nobody driving): download, verify and unzip the new release
  next to the current one ([Download the latest release](#download-the-latest-release)). Stop Pitwall (Windows: in
  the old folder `service.ps1 uninstall` if the service is installed; macOS: `scripts/pitwall-service.sh uninstall`).
  Do not run `uv sync`, `install.ps1` or Pitwall in the new folder before the move. If the new folder already has a
  `data` folder, stop and ask the user (moving onto it would nest the old data inside it). Move the data folder
  (doctor `data_dir`, if it is inside the old folder) and `.env` (if any; do not read it) into the new folder, then
  run step 3 there and start Pitwall (or install the service) from the new folder. Do not
  delete the old folder: the user does that once the new one works. Full steps: `docs/install.md`, "From one release
  to the next".
- **Clone:** `git pull`, `uv sync --all-extras`, rebuild the dashboard (step 3; Windows: re-run `install.ps1`).

## Troubleshooting

Common fixes (no packets, port in use, dashboard not built, Windows execution policy, firewall, Public network,
excluded ports, macOS firewall prompt) are in [troubleshooting.md](troubleshooting.md). Start every diagnosis with
`uv run pitwall doctor --json`; its `fix` lines are the first thing to try.
