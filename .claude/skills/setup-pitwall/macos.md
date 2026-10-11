# macOS details for /setup-pitwall

macOS is Pitwall's primary platform (F1 25 on PS5 was validated live with the server on a Mac). Apple silicon gets
the full voice radio. Intel Macs should run everything except Parakeet speech recognition and the Kokoro voice, but
have not been run yet: say so.

## Prerequisites (ask before each install)

| Tool | Needed for | Check | Install |
|---|---|---|---|
| uv | always | `uv --version` | with Homebrew: `brew install uv`; otherwise the official installer from https://docs.astral.sh/uv/getting-started/installation/ (it downloads and runs a script: say so) |
| Command Line Tools (git, make) | a clone | `xcode-select -p` | `xcode-select --install` (opens Apple's installer dialog; the user clicks Install) |
| Node.js 20.19+ / 22.12+ | a clone (dashboard build) | `node --version` | `brew install node`, or the LTS installer from https://nodejs.org |

A release folder needs only uv. Python: `uv sync` downloads Python 3.12 itself (`.python-version`). Do not install
Python with Homebrew for Pitwall.

## Install and build

Release folder (SKILL.md step 0): the dashboard is prebuilt, so only

```bash
uv sync --all-extras                                                       # Python 3.12 + packages (+ parakeet-mlx on Apple silicon)
```

Git clone:

```bash
uv sync --all-extras                                                       # Python 3.12 + packages (+ parakeet-mlx on Apple silicon)
(cd web && npm ci --no-audit --no-fund && npm run build)                   # free Svelte dashboard -> web/dist
(cd web-react && npm ci --no-audit --no-fund && npm run build:root)        # OR: React + HeroUI Pro (licence holders) -> web-react/dist
```

The subshells keep the working folder at the repo root. `make web-react` runs the same React commands. Use `npm ci`
(never `npm install` or `npm audit fix`) so the lockfiles stay unchanged. A first install can take several
minutes: Bash `timeout: 600000` or `run_in_background`. Both builds are served at `/`; the React one wins when both
exist. Without a HeroUI Pro login or `HEROUI_AUTH_TOKEN`, the React `npm ci` still succeeds and `build:root` then
fails with `Can't resolve '@heroui-pro/react/...'`: build the Svelte one.

## Firewall

doctor's `firewall` check reads the macOS application firewall. When it is on, macOS asks once whether Python may
"accept incoming network connections" the first time the server listens: the user clicks Allow. If they clicked Deny
(or "Block all incoming connections" is set), no telemetry arrives: System Settings > Network > Firewall > Options,
allow the Python of `.venv` (or turn off "Block all incoming connections"). The user changes these settings.

## Voice (optional, Apple silicon)

- Speech recognition (push-to-talk questions): `parakeet-mlx`, installed by `uv sync --all-extras`. The model
  downloads from Hugging Face on first use. doctor `voice_stt` shows whether it is installed.
- Natural engineer voice (Kokoro): `scripts/setup-tts.sh` - creates `~/Library/Application Support/pitwall/tts-venv`,
  downloads the pinned Kokoro-82M model and voices, then proves it speaks offline. Ask first (download + disk space).
  Without it the radio speaks with macOS `say` (voice `PITWALL_TTS_FALLBACK_VOICE`, default Daniel).
- The iPad/iPhone can speak with its own voices instead: Settings > Radio & voice > Engineer voice > This device.

## Start at login (optional)

```bash
scripts/pitwall-service.sh install     # launchd agent com.pitwall.server: starts at login, restarts on crash
scripts/pitwall-service.sh status      # state + health check
scripts/pitwall-service.sh logs        # follow ~/Library/Logs/pitwall/server.log
scripts/pitwall-service.sh uninstall
```

`install` stops any manually started `pitwall serve` first (so the service can take the ports) - without checking
whether telemetry is live, so check doctor's `telemetry` first - and runs the server from the folder the script is
in (the release folder or the clone) with `PITWALL_DATA_DIR` = `<that folder>/data` unless set in the shell
(`PITWALL_DATA_DIR` in `.env` does not reach the service). After moving to a new release folder, run `install` again
from the new folder (SKILL.md "Updating"). `restart` (and `restart-when-idle`) refuse while telemetry is live.
`scripts/release.sh` is a maintainer deploy tool (release worktree); new users do not need it.

## Tailscale (HTTPS for the radio microphone)

The Mac app's CLI is `/Applications/Tailscale.app/Contents/MacOS/Tailscale` (or `tailscale` if the user installed
the CLI). Check what is already served before choosing a port:

```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve status
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg --https=<free port> http://127.0.0.1:<http_port>
```

Under launchd the CLI needs `TAILSCALE_BE_CLI=1` (Pitwall sets it for its own calls).

## Find the LAN IP by hand

doctor's `lan_ip` is the address the Mac uses for its default route. To cross-check: `ipconfig getifaddr en0`
(often Wi-Fi or built-in Ethernet; try `en1` etc.). A Tailscale address (100.x) is never the one for the game.
