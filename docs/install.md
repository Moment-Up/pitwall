# Installing Pitwall

This guide takes you from a fresh computer to coaching on track. There are three ways to install Pitwall:

1. **[Install with one command](#install-with-one-command)** (recommended, from v0.2.0) or **[from a
   release by hand](#install-from-a-release)**. Both install one zip with the new dashboard already built. You need
   only [uv](https://docs.astral.sh/uv/) (the one-line installer offers to install it): no Node.js and no HeroUI Pro
   licence. macOS, Windows and Linux.
2. **[Set up with Claude Code](#set-up-with-claude-code).** Unzip a release (or clone the repository), open the
   folder in Claude Code and run `/setup-pitwall`. It does the steps below with you. Written for macOS and Windows
   (not yet run end to end on a Windows PC).
3. **[Install from source](#install-from-source)** (developers). Clone the repository and build a dashboard
   yourself. The new dashboard needs your own HeroUI Pro licence to build; without one you get the classic
   dashboard automatically.

Where Pitwall has been tested: a Mac with Apple Silicon, with F1 25 on a PS5 (live). Windows is CI-tested on Windows
(GitHub runners), not yet validated live with a game on a Windows PC. Intel Macs and Linux should work but have not
been run with a game (release zips are checked on a Linux CI runner with synthetic telemetry). The
[platform notes](#platform-notes) and the README's [platform table](../README.md#platforms) have the details.

- [What you need](#what-you-need)
- [Install with one command](#install-with-one-command)
- [Install from a release](#install-from-a-release)
- [Set up with Claude Code](#set-up-with-claude-code)
- [Install from source](#install-from-source)
- [Settings](#settings)
- [Start Pitwall](#start-pitwall)
- [Try the demo (no game needed)](#try-the-demo-no-game-needed)
- [Connect your game](#connect-your-game)
- [Open it on an iPad or phone](#open-it-on-an-ipad-or-phone)
- [The AI engineer (optional)](#the-ai-engineer-optional)
- [The voice radio (optional)](#the-voice-radio-optional)
- [Run it in the background](#run-it-in-the-background)
- [First-run checklist](#first-run-checklist)
- [Platform notes](#platform-notes)
- [Updating](#updating)
- [Your data](#your-data)
- [Troubleshooting](#troubleshooting)
- [For developers](#for-developers)

## What you need

- A computer on the same network as your console or gaming PC. A Mac with Apple Silicon is recommended: it is where
  Pitwall has been run with a game, and it is needed for built-in speech recognition and the natural voice.
- A racing game that sends UDP telemetry. See the [supported games](../README.md#supported-games).
- [uv](https://docs.astral.sh/uv/getting-started/installation/). It also installs Python 3.12 for Pitwall: you do
  not need to install Python yourself.
  - macOS: `brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows: `winget install --id astral-sh.uv -e`, or
    `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- About 0.7 GB of disk for Pitwall's Python environment. Speech recognition downloads about 2.5 GB more the first
  time the radio is used (Apple Silicon only). The optional natural voice needs about 1 GB. Raw captures of real
  F1 25 sessions need about 400 MB per hour of driving (`PITWALL_RECORD_RAW=false` turns them off).
- Optional: an iPad or phone next to the wheel, [Tailscale](https://tailscale.com) for the radio microphone, and a
  local model server or a cloud API key for the engineer's explanations.
- Only to install from source: git and Node.js 22.12 or later (the classic dashboard also builds on 20.19 or
  later), and a HeroUI Pro licence if you want to build the new dashboard.

## Install with one command

<!-- --- lane install --- -->
From v0.2.0 (not released yet: until then, [install from a release](#install-from-a-release)), each release also
has two installers. They download the latest release, check it, install it into a folder of its own and keep your
sessions in one data folder that every later version uses.

macOS and Linux (in Terminal):

```bash
curl -fsSL https://github.com/Moment-Up/pitwall/releases/latest/download/install.sh | sh
```

Windows (in PowerShell, not as administrator):

```powershell
irm https://github.com/Moment-Up/pitwall/releases/latest/download/install.ps1 | iex
```

What it does, in order:

1. Finds the latest release on GitHub (pre-releases only with `--pre`) and checks there is 2 GB free.
2. Stops if a game is streaming to a Pitwall on this computer (someone may be driving); `--wait-idle 120` waits up
   to two hours instead.
3. Finds [uv](https://docs.astral.sh/uv/), or asks whether to install it from astral.sh (with `--yes` it does so
   without asking). It never edits your shell profile or PATH.
4. Downloads `pitwall-<version>.zip` and its `.sha256`, checks the SHA-256 and every path in the zip (nothing
   outside its folder, no links), and unpacks it into `~/Pitwall/pitwall-<version>/` (Windows:
   `%LOCALAPPDATA%\Pitwall\pitwall-<version>\`).
5. Runs `uv sync --locked --all-extras` there and checks that the server's modules import.
6. Hands over to the new version's `pitwall install-finish`, which makes the data folder (`~/Pitwall/data`, private
   to your account), backs up the database if there is one, writes `.env` (or carries yours forward), offers to start
   Pitwall in the background at login (macOS and Windows) and prints the dashboard address, the phone link command
   and the address and port to set in your game.

Running it again is safe: an installed version is not downloaded again, and an interrupted install carries on.

Options (macOS and Linux: after `sh -s --`, for example `curl -fsSL <url> | sh -s -- --yes`; Windows: set
`$env:PITWALL_INSTALL_YES='1'` and the like before `irm`, or run
`& ([scriptblock]::Create((irm <url>))) -Yes`):

| install.sh | install.ps1 / environment | What |
|---|---|---|
| `--yes` | `-Yes` / `PITWALL_INSTALL_YES=1` | Yes to every question (installing uv, moving data, the background service) |
| `--version v0.2.0` | `-Version` / `PITWALL_INSTALL_VERSION` | Install that release |
| `--home DIR` | `-InstallHome` / `PITWALL_INSTALL_HOME` | Another install folder |
| `--service`, `--no-service` | `-Service yes\|no` / `PITWALL_INSTALL_SERVICE` | Start at login, or not (default: ask) |
| `--wait-idle MIN` | `-WaitIdle` / `PITWALL_INSTALL_WAIT_IDLE` | Wait while someone is driving instead of stopping |
| `--pre` | `-Pre` / `PITWALL_INSTALL_PRE=1` | Allow pre-releases |
| `--from-zip PATH` | `-FromZip` / `PITWALL_INSTALL_FROM_ZIP` | Install a zip you downloaded (its `.sha256` must be next to it) |

Exit codes: 0 done (or already installed), 1 error, 2 not supported here (or a release older than v0.2.0, which you
install [by hand](#install-from-a-release)), 3 someone is driving, 4 it needs you (a question without a terminal,
low disk, a data folder it will not guess about), 5 the download failed its check.

If you already run a release you installed by hand in `~/Pitwall` (for example `~/Pitwall/pitwall-v0.1.0` with its
`data` folder inside), the installer offers to move that data folder to `~/Pitwall/data`, so every version uses it;
it leaves a note in the old folder. It never deletes a version folder, a data folder or a `.env`, and it never
touches a background service that runs Pitwall from a folder outside `~/Pitwall`.

**What the check proves.** The SHA-256 comes from the same release, so it proves the download is complete and
unchanged, not who made it. Signed installers are future work ([releasing.md](releasing.md)). If you prefer to
look before you run it, download `install.sh` (or `install.ps1`) from the release page and read it first: everything
is in one file. Status: unit-tested and run end to end on a Mac with Apple Silicon against a local test server;
Windows and Linux are tested in CI only.
<!-- --- end lane install --- -->

## Install from a release

A release is one zip, `pitwall-<version>.zip`, on the
[Releases page](https://github.com/Moment-Up/pitwall/releases). It holds Pitwall's source and the new dashboard,
already built. Download `pitwall-<version>.zip` and `pitwall-<version>.zip.sha256` from the latest release. Do not
use GitHub's "Source code" downloads: they do not contain the built dashboard.

The examples use `v0.1.0`, the first release; put in the version you downloaded. Always start Pitwall from the
release folder: it keeps its data in `data/` there and reads `.env` from there.

Put the release in a folder you keep, for example `~/Pitwall` (Windows: `C:\Users\<you>\Pitwall`), not Downloads,
Desktop or Documents: your data lives inside the release folder, and macOS can stop the background service from
reading those folders. If your browser saved the zip in Downloads, move both files there first.

### macOS and Linux

```bash
mkdir -p ~/Pitwall && cd ~/Pitwall            # a folder you keep
curl -LO https://github.com/Moment-Up/pitwall/releases/download/v0.1.0/pitwall-v0.1.0.zip
curl -LO https://github.com/Moment-Up/pitwall/releases/download/v0.1.0/pitwall-v0.1.0.zip.sha256
shasum -a 256 -c pitwall-v0.1.0.zip.sha256    # must print "pitwall-v0.1.0.zip: OK" (Linux: sha256sum -c ...)
unzip pitwall-v0.1.0.zip
cd pitwall-v0.1.0
uv sync --all-extras                          # Python 3.12 and packages; speech recognition on Apple Silicon only
uv run pitwall serve
```

Open `http://127.0.0.1:8770/` on the same computer: you get the new dashboard. The first time, macOS may ask
whether Python may accept incoming network connections: allow it, or the game's packets will not arrive. Stop
Pitwall with Ctrl+C. Next: [try the demo](#try-the-demo-no-game-needed) and [connect your game](#connect-your-game).

### Windows

In PowerShell:

```powershell
mkdir -Force $HOME\Pitwall | Out-Null; cd $HOME\Pitwall   # a folder you keep
curl.exe -LO https://github.com/Moment-Up/pitwall/releases/download/v0.1.0/pitwall-v0.1.0.zip
curl.exe -LO https://github.com/Moment-Up/pitwall/releases/download/v0.1.0/pitwall-v0.1.0.zip.sha256
(Get-FileHash .\pitwall-v0.1.0.zip -Algorithm SHA256).Hash -eq (Get-Content .\pitwall-v0.1.0.zip.sha256).Split(' ')[0]   # must print True
Unblock-File .\pitwall-v0.1.0.zip             # only needed if you downloaded it with a browser
Expand-Archive .\pitwall-v0.1.0.zip -DestinationPath .
cd .\pitwall-v0.1.0
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\pitwall.ps1
```

- `install.ps1` recognises the release folder: it uses the prebuilt dashboard as it is, so it needs neither
  Node.js nor git. It checks for uv (and offers to install it with winget), runs `uv sync --all-extras`, checks that
  the server's modules import and makes the `data` folder private to your Windows account (it will hold the access
  token and any API keys).
- `pitwall.ps1` runs Pitwall in that window; Ctrl+C stops it. Open `http://127.0.0.1:8770/`.
- The first time, Windows may ask whether Python may communicate on networks: tick **Private networks** only and
  click **Allow access**. Do not tick Public, and do not click Cancel (that creates rules that block Pitwall).
- To let your console, phone and tablet in, run once in PowerShell opened with **Run as administrator**, in the
  release folder: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\firewall.ps1 add`.
- `uv run pitwall doctor` checks the whole setup and prints a fix for each problem.

More about the Windows scripts: [scripts/windows/README.md](../scripts/windows/README.md).

### What is in a release

The folder `pitwall-<version>/` holds Pitwall's source at the release's commit, plus:

| Path | What |
|---|---|
| `web-react/dist/` | The new dashboard, prebuilt. Pitwall serves it at `/` |
| `RELEASE.txt` | The version and commit you have |
| `THIRD_PARTY_NOTICES.txt` | The licences of the dashboard's components and of third-party data |

The dashboard includes HeroUI Pro components, © NextUI Inc., used under licence. They are part of the Pitwall
application only and may not be extracted or reused on their own.

Optional check, in the release folder after `uv sync`: `uv run python scripts/verify_release.py` starts a temporary
Pitwall on spare ports with a temporary data folder, streams a synthetic session to it over loopback UDP and prints
PASS or FAIL. It does not touch your data or a running Pitwall, and it says nothing about a game. Every release is
checked this way on Windows, macOS and Linux runners before it is published ([releasing.md](releasing.md)).

To move to a newer release later, use [`pitwall update`](#with-pitwall-update) (or
[by hand](#from-one-release-to-the-next-by-hand)).

## Set up with Claude Code

[Claude Code](https://claude.com/claude-code) (Anthropic's coding assistant; it needs its own Claude account) can do
the whole setup with you. The skill is written for macOS and Windows. On Windows it drives the CI-tested scripts but
has not yet been run end to end on a Windows PC.

1. Get Pitwall: unzip a [release](#install-from-a-release) (recommended), or clone the repository.
2. Open that folder in Claude Code, for example `cd pitwall-v0.1.0` and then `claude`.
3. Run `/setup-pitwall`. You can name your game: `/setup-pitwall F1 25 on PS5`.

It checks the prerequisites, installs Pitwall, runs a synthetic demo and `pitwall doctor`, gives you your game's
exact telemetry settings, and offers the phone or iPad link, the voice radio, an AI engineer and starting at login.

- It asks before it installs or changes anything, one action at a time.
- It never asks for API keys, tokens or your HeroUI Pro login. You type keys into the dashboard yourself
  (Settings › AI engineer), and you copy the phone link with its access token yourself.
- In an unzipped release it skips the dashboard build. In a clone without a HeroUI Pro licence it offers to
  download the latest release for you, or to build the classic dashboard.
- On Windows the firewall rules and the network profile stay with you: they need administrator rights or Windows
  Settings.
- Claude Code may ask whether to enable this project's MCP server `qwen` (from `.mcp.json`). It is the maintainer's
  optional tool for a local model at 127.0.0.1:8081, and setup does not use it: choose No unless you run such a
  server.

On Windows, Claude Code needs [Git for Windows](https://git-scm.com/download/win). On Linux the skill follows the
macOS steps by hand and says that Linux is untested.

## Install from source

For developers, or to follow the latest changes. Releases are easier: see [Install from a
release](#install-from-a-release).

### Tools

macOS:

```bash
xcode-select --install          # git and make (skip if already installed)
brew install uv node            # or uv from https://docs.astral.sh/uv/ and Node.js from https://nodejs.org
```

You need Node.js 22.12 or later (the classic dashboard also builds on 20.19 or later). uv installs Python 3.12.

### Get the code and the Python environment

```bash
git clone https://github.com/Moment-Up/pitwall.git
cd pitwall
uv sync --all-extras
```

`--all-extras` adds speech recognition (`parakeet-mlx`, installed only on Apple Silicon Macs) and a developer tool.
Plain `uv sync` installs Pitwall without speech recognition.

### Build a dashboard

Pitwall has two dashboards. Pitwall serves the new one at `/` when `web-react/dist` exists, and the classic one
otherwise.

**Classic dashboard** (`web/`, Svelte). No HeroUI Pro licence needed:

```bash
cd web && npm ci && npm run build && cd ..
```

npm may print an audit warning. You can ignore it; do not run `npm audit fix --force`, which can upgrade the build
tools to versions Pitwall has not been tested with.

The classic dashboard has Live, Sessions, Engineer, Radio, Setup (rig walkthrough and rig check), Car setup,
Drivers, Connect, Settings and Status. It lacks the new coach-first Drive screens and Review › Coaching and
Progress, looks different from the screenshots, and receives fixes only.

**New dashboard** (`web-react/`, React). The new dashboard uses HeroUI Pro, a commercial component library, so
building it from source needs your own HeroUI Pro licence. Do not share your HeroUI Pro login, licence key or
`HEROUI_AUTH_TOKEN`, and never publish `web-react/node_modules` or a build with source maps. Sign in once, then
build:

```bash
cd web-react && npx heroui-pro@latest login && cd ..
make web-react                  # npm ci + npm run build:root -> web-react/dist
```

Without a HeroUI Pro sign-in, `npm ci` in `web-react/` appears to succeed (it only prints "Sign in to finish
installing"), but the build fails with `Can't resolve '@heroui-pro/react/css/...'`. Signed in without an active
licence, `npm ci` stops with "Access denied". Use the classic dashboard instead, or a
[release](#install-from-a-release), which has the new dashboard prebuilt.

### From source on Windows

In PowerShell, in the cloned folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install.ps1
```

It checks git, uv and Node.js (offering winget installs, y/N for each), runs `uv sync --all-extras`, builds the
classic dashboard (the new one with `-Dashboard react` if you have a HeroUI Pro login, or automatically when
`HEROUI_AUTH_TOKEN` is set) and makes the `data` folder private. Then start Pitwall with `scripts\windows\pitwall.ps1`
as in [Windows](#windows) above. Details: [scripts/windows/README.md](../scripts/windows/README.md).

## Settings

Pitwall works without any settings file. To change something, copy the example and uncomment the lines you need:

```bash
cp .env.example .env
```

Pitwall reads `.env` from the folder you start it in (the release or repository folder). If you have no language
model server yet, set `PITWALL_LLM_ENABLED=false` (or switch the AI engineer off in the dashboard later).
`pitwall ask` uses the `PITWALL_LLM_*` values from `.env` or the environment, never the dashboard's choice: with
`PITWALL_LLM_ENABLED=false` it answers from the facts, and `--no-llm` does the same for one question. Every setting
is listed in [`.env.example`](../.env.example) and `src/pitwall/config.py`.

## Start Pitwall

```bash
uv run pitwall serve
```

(On Windows you can also use `scripts\windows\pitwall.ps1`, which runs the same server.) It prints three lines
(Windows says "this PC" and Linux "this computer" instead of "this Mac"):

```
Dashboard (this Mac):   http://127.0.0.1:8770/
Dashboard (LAN device): http://<computer-ip>:8770/?token=<token>
Game telemetry:         UDP <computer-ip>:20777  (set this IP/port in the game)
```

Open `http://127.0.0.1:8770/` on the same computer. Useful options: `--port` (HTTP port), `--host` (bind address),
`--no-udp` (no telemetry listener) and `--verbose`. Stop the server with Ctrl+C.

## Try the demo (no game needed)

The demo is a generated session at a made-up circuit, "Pitwall Park", with known mistakes built in. It is labelled
SYNTHETIC on every screen and never mixes with real track data.

- In the new dashboard: **Drive › Coach** shows *Try a demo replay (synthetic)* while no telemetry arrives, and
  **Settings › System** has the same demo and replays of your captures. (The new dashboard's demo button has not
  been tested end to end yet; the commands below have.)
- In the classic dashboard: **Status › Generate synthetic demo**, then **Replay** next to the capture.
- From the terminal, in the release or repository folder:

  ```bash
  uv run pitwall simulate                                                   # writes data/captures/synthetic-coaching-demo-2025.pwcap
  uv run pitwall replay data/captures/synthetic-coaching-demo-2025.pwcap    # processes it into the database
  uv run pitwall report                                                     # prints the coaching report
  uv run pitwall send data/captures/synthetic-coaching-demo-2025.pwcap --speed 8   # streams it to a running server
  ```

  `make demo` runs the first three in one go (macOS and Linux, needs `make`). If you set `PITWALL_DATA_DIR`, use
  the path that `pitwall simulate` printed instead of `data/captures/...`.

`pitwall send` sends the capture over real UDP to `127.0.0.1:20777` (change with `--host` and `--port`), as a
console would. Streamed this way, the demo arrives like a real game: it belongs to the driver in the seat and
appears as "Unknown track" (labelled SYNTHETIC), because the generated stream carries no real track id. The replay
is named "Pitwall Park (synthetic)" and has no driver.

## Connect your game

The **Connect** page (new dashboard: **Setup › Connect**) shows the exact settings for each game with copy buttons,
the computer's address, and every device that is sending packets, with the number decoded and rejected. The
computer and the console or PC must be on the same network.

To find the console's IP address on a PS5: Settings › Network › Connection Status › View Connection Status ›
IPv4 Address.

### Tell Pitwall what you play

Do this first. In the new dashboard: **Setup › Game**, then pick the game and the platform. From the terminal (with
either dashboard): `uv run pitwall game list` shows the games and `uv run pitwall game set <id>` chooses one. With
Pitwall running the change applies at once; otherwise at the next start. Choosing a game:

- switches on its telemetry input (F1 25's is always on), so the game's Enable switch on the Connect page is
  already done;
- asks for the console's IP address where Pitwall needs it: required for Assetto Corsa. Gran Turismo 7's input is
  switched on only with its IP (`--console-ip <console-ip>` on `game set`, or the IP field on Setup › Game): without
  one it would search the whole network for the console, so that is a separate, explicit choice (Setup › Game ›
  *Search the network*, or Enable on the Connect page);
- never switches another game's input off;
- shows what the game sends and what it does not, feature by feature (Setup › Game, or `uv run pitwall game show`),
  so an empty tile for data your game never sends is expected rather than a fault. These lists come from the same
  support matrix as [Supported games](../README.md#supported-games) and are never stronger than it.

| You play | Platform | Id |
|---|---|---|
| F1 25 | PS5 / Xbox Series / PC | `f1_25:ps5`, `f1_25:xbox`, `f1_25:pc` |
| F1 25 with 2026 Season Pack cars (UDP Format 2026) | PS5 / Xbox Series / PC | `f1_25_2026:ps5`, `f1_25_2026:xbox`, `f1_25_2026:pc` |
| Gran Turismo 7 | PS5 / PS4 | `gt7:ps5`, `gt7:ps4` |
| Forza Motorsport (2023) | Xbox Series / PC | `forza_motorsport:xbox`, `forza_motorsport:pc` |
| Forza Horizon 4 / 5 | Xbox / PC / PS5 | `forza_horizon:xbox`, `forza_horizon:pc`, `forza_horizon:ps5` |
| Assetto Corsa | PS5 (PS4 version) / PS4 / PC / Xbox One | `ac:ps5`, `ac:ps4`, `ac:pc`, `ac:xbox` |
| Assetto Corsa Competizione | PC / PS5 / Xbox Series | `acc:pc`, `acc:ps5`, `acc:xbox` |
| iRacing | PC | `iracing:pc` |
| F1 24 or older | any | `f1_24:any` |
| Another game | any | `other:any` |

`uv run pitwall game list --all` prints the current list with each one's support. Some entries exist only so you can
say what you play although Pitwall cannot read it (Assetto Corsa Competizione, iRacing, F1 24, Assetto Corsa on
Xbox One). For another game, Pitwall offers to record its packets (see [Other games](#other-games)).

If a different game than the one you chose is sending, Pitwall says so (an alert outside Drive; on Drive, the status
line while the car is stationary) and offers to switch. It still decodes whatever arrives: the choice never filters
packets. Tested with unit, synthetic and recorded data; not yet with a live GT7, Forza or Assetto Corsa console.

### F1 25 (tested live on PS5)

In the game: **Settings › Telemetry Settings**.

| Setting | Value |
|---|---|
| UDP Telemetry | On |
| UDP Broadcast Mode | Off |
| UDP IP Address | the computer's IP address (printed by `pitwall serve` and shown on Connect) |
| UDP Port | 20777 |
| UDP Send Rate | 60Hz (20Hz works, but braking points are less precise: about 4 m instead of 1.4 m) |
| UDP Format | 2025, or 2026 when driving 2026 Season Pack cars. 2024 is not supported |
| Your Telemetry | Public (Restricted hides some data about other cars; your own car is not affected) |

Packets appear on the Connect page within a second of being on track or in the garage. PC and Xbox use the same
settings but have not been tested yet.

For wheel push-to-talk: **Settings › Controls ›** your wheel, and assign a spare button to **UDP Action 1**.
Pitwall reads the button through the telemetry stream. Use `PITWALL_VOICE_PTT_BUTTON=udp_action_2` (up to 12) for
a different action.

### Gran Turismo 7 (built from community docs, untested on a real console)

There is nothing to set in the game. On the Connect page, enable **Gran Turismo 7**, enter the console's IP address
and keep packet variant **C**. Pitwall sends a heartbeat to the console's UDP port 33739 and listens on 33740.
Telemetry starts within about 2 s. Only one app on the computer can receive GT7 telemetry, so quit SimHub or
similar apps first. GT7 sends no lap distance or track id: Pitwall works out distance from speed (about 1% drift per
lap) and recognises the circuit from the start/finish line after the first full lap.

### Forza Motorsport (2023) and Forza Horizon 4 / 5 (built from community docs, untested on a real console)

On the Connect page, enable **Forza**. In the game (Forza Motorsport: Settings › Gameplay & HUD › UDP Race
Telemetry; Forza Horizon: Settings › HUD and Gameplay):

| Setting | Value |
|---|---|
| Data Out | On |
| Data Out IP Address | the computer's IP address |
| Data Out IP Port | 5301 |
| Data Out Packet Format | Dash (Forza Motorsport only) |

Forza Horizon free roam has no laps: you get live data, but lap analysis needs a circuit race.

### Assetto Corsa (telemetry confirmed from a PS5; laps and coaching not yet confirmed)

There is nothing to set in the game. On the Connect page, enable **Assetto Corsa**, enter the console's (or the
gaming PC's) IP address and choose the platform (PS5, PS4 or PC). Pitwall asks the game for telemetry on its UDP
port 9996. The game only answers while you are on track (Hotlap, Time Trial, Practice or a race), not in the menus.
Pitwall gets no usable steering angle (its unit is undocumented), and the game sends no tyre temperatures, fuel or
sectors.

If nothing arrives, switch the integration off on the Connect page and run the probe once while on track:

```bash
uv run python scripts/probe_ac.py --ip <console-ip> --platform ps5 --seconds 60 --out ~/ac-probe-ps5.pwcap
```

It sends at most 5 handshakes and records what comes back; exit code 0 means the game streams.

### Other games

**Record another game** on the Connect page saves every packet sent to a port (7576 by default, Project Motor
Racing's default) without analysing it, so a decoder can be written later. Assetto Corsa Competizione and iRacing
are not supported yet: on PC their telemetry can only be read on the gaming PC itself (no reader yet), and ACC on
consoles sends no telemetry.

## Open it on an iPad or phone

### On your home network

```bash
uv run pitwall token            # prints http://<computer-ip>:8770/?token=<token>
```

Open that link on the device once (the Connect page shows it too). The token is then remembered in a cookie. If
you add Pitwall to the Home Screen, do it from the link with `?token=`, because a Home Screen web app does not share
Safari's cookies. On Windows the firewall rule from `firewall.ps1 add` must exist.

Over plain `http://` the browser will not give Pitwall the microphone. Everything else works, including typed
questions and the radio's spoken replies.

### With HTTPS through Tailscale (needed for the microphone)

1. Install [Tailscale](https://tailscale.com) on the computer and on the iPad or phone, signed in to the same
   tailnet.
2. Turn on MagicDNS and HTTPS certificates for your tailnet in the Tailscale admin console.
3. On the computer (on a Mac, the app's command is `/Applications/Tailscale.app/Contents/MacOS/Tailscale` if
   `tailscale` is not on your PATH):

   ```bash
   tailscale serve status                                   # ports already served (do not reuse them)
   tailscale serve --bg --https=8443 http://127.0.0.1:8770  # 8443, or any port not listed above
   ```

4. On the device, open `https://<your-computer>.<your-tailnet>.ts.net:8443/` (with your port). The Connect page
   shows this address too: it reads `tailscale serve status` for the serve that forwards to Pitwall's port.

Your own Tailscale login is trusted automatically, with no token. Other people on your tailnet need the token, or
add their logins to `PITWALL_TAILSCALE_ALLOWED_LOGINS`. To stop serving: `tailscale serve --https=8443 off`.

Do not forward port 8770 to the internet, and do not use Tailscale Funnel for Pitwall.

### On the iPad

- In Safari: Share › Add to Home Screen, and open Pitwall from that icon. The new dashboard's Drive pages and live
  radio ask the browser to keep the screen awake; this has not yet been tested on a real iPad.
- Keep the iPad unlocked with Pitwall in front. iPadOS cuts the microphone when Safari goes to the background or
  the screen locks.

[radio-setup.md](radio-setup.md) has the full iPad, AirPod and push-to-talk routine.

## The AI engineer (optional)

The engineer explains your sessions in plain words. Without a model it still answers, from the facts alone.
Choose in the dashboard under **Settings › AI engineer** (classic: **Settings**): Off, Local or Cloud. Changes
apply at once.

**Local model.** Start any OpenAI-compatible server and point Pitwall at it, in the settings page or in `.env`:

| Server | Address |
|---|---|
| llama.cpp `llama-server` | `http://127.0.0.1:8080/v1` (its default port) |
| LM Studio | `http://127.0.0.1:1234/v1` |
| Ollama | `http://127.0.0.1:11434/v1` |
| MLX (`mlx_lm.server`) | `http://127.0.0.1:8080/v1` |

```bash
# .env
PITWALL_LLM_BASE_URL=http://127.0.0.1:1234/v1
```

```bash
uv run pitwall llm-check        # finds the model and sends one test message
```

`llm-check` tests the address in `.env` or the environment, not one chosen in the settings page. Once you save
**Settings › AI engineer**, the saved choice takes over from the `PITWALL_LLM_*` values for the server. Pitwall's
built-in default is `http://127.0.0.1:8081/v1`, which is not a standard port, so set the address for your server.

**Cloud model.** Anthropic Claude, OpenAI, OpenRouter, Google Gemini, Groq, Mistral or another OpenAI-compatible
service. Turn cloud on and accept the privacy notice in the settings page, then enter a key there (stored in
`data/secrets.json`, readable only by you) or export it in the shell that starts Pitwall
(`PITWALL_ANTHROPIC_API_KEY` and so on; these are not read from `.env`). Only the question, your last few exchanges
and a fact sheet are sent, never raw telemetry or audio, and driver names are replaced with "the driver". You can
set a daily budget. Cloud providers have been tested against mock servers only. Details:
[llm-providers.md](llm-providers.md).

## The voice radio (optional)

The radio is on by default. It needs no extra setup to take typed questions and speak its replies.

| | Speech recognition (spoken questions) | The engineer's voice on the computer |
|---|---|---|
| Mac with Apple Silicon | Parakeet, installed by `uv sync --all-extras` | The natural voice (Kokoro, optional), else the macOS voices |
| Intel Mac | a whisper.cpp server | the macOS voices |
| Windows | a whisper.cpp server | Windows' built-in voices (SAPI) |
| Linux | a whisper.cpp server | none (text, or the iPad's own voice) |

On every computer the iPad or phone can speak with its own voice instead (Settings › Radio & voice › Engineer
voice), and typed questions always work.

- **Parakeet** downloads its model, about 2.5 GB, the first time a radio connects.
- **whisper.cpp.** Run a [whisper.cpp](https://github.com/ggml-org/whisper.cpp) server and set
  `PITWALL_STT_ENGINE=whispercpp` and `PITWALL_WHISPERCPP_URL` (default `http://127.0.0.1:8178`) in `.env`. This
  path has only been tested against a mock server. Without speech recognition, push-to-talk questions do not work
  and the radio says so; typed questions do.
- **The natural voice** (Kokoro, Apple Silicon only, about 1 GB, offline afterwards). By default Pitwall tries it
  and falls back to the macOS voice Daniel. To install it:

  ```bash
  scripts/setup-tts.sh
  ```

  It installs into `~/Library/Application Support/pitwall`, outside the Pitwall folder, and checks itself. Restart
  Pitwall afterwards. Voices: `bm_fable` (default), `bm_george`, `bf_emma`, `bf_isabella`, chosen in Radio &
  voice settings or with `PITWALL_TTS_VOICE`. `PITWALL_TTS_ENGINE=say` uses only the macOS voices, and `none`
  makes the server silent.
- **Windows voices.** `uv run pitwall doctor` lists the voices installed on the PC; `PITWALL_TTS_SAPI_VOICE=Hazel`
  in `.env` picks one (part of its name is enough). They are CI-tested but have not been heard on a radio yet.
- **Microphone:** the device you talk into needs HTTPS (see
  [Tailscale](#with-https-through-tailscale-needed-for-the-microphone)) or must be the computer itself.
- **Push-to-talk:** hold the on-screen button, the Space bar on a Mac's Drive pages, or a wheel button mapped to
  UDP Action 1 in F1 25.

Say "radio check" to test it. [radio-setup.md](radio-setup.md) lists what you can ask.

## Run it in the background

### macOS (launchd)

Pitwall can run as a launchd user agent that starts at login and restarts if it crashes. Run these in the release
or repository folder:

```bash
scripts/pitwall-service.sh install      # write ~/Library/LaunchAgents/com.pitwall.server.plist and start it
scripts/pitwall-service.sh status       # launchd state and a health check
scripts/pitwall-service.sh logs         # follow ~/Library/Logs/pitwall/server.log
scripts/pitwall-service.sh restart      # refused while a game is streaming; add --force to override
scripts/pitwall-service.sh restart-when-idle [minutes]   # waits until nobody is driving (default 120 min)
scripts/pitwall-service.sh uninstall    # stop and remove it
```

The service runs `.venv/bin/pitwall serve` from the folder the script is in (your release or repository folder),
so it reads the `.env` there. Data goes to `data/` in that folder unless you set `PITWALL_DATA_DIR` in the shell
when you run `install`
(`PITWALL_DATA_DIR="$HOME/pitwall-data" scripts/pitwall-service.sh install`). The service sets `PITWALL_DATA_DIR`
itself, so a `PITWALL_DATA_DIR` line in `.env` has no effect on it. Notes:

- `install` stops any `pitwall serve` already running, without checking whether someone is driving: run it between
  sessions.
- The script's health checks use port 8770. If you change `PITWALL_HTTP_PORT`, `status` will report the service
  as not responding.
- Restarting while someone drives ends their session and splits the race in two, which is why `restart` refuses.

### Windows (Task Scheduler)

`scripts\windows\service.ps1` registers a Task Scheduler task, "Pitwall", that starts Pitwall at logon in a hidden
window and starts it again if it exits. It needs no administrator rights. In PowerShell, in the release or
repository folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\service.ps1 install   # register the task and start it
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\service.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\service.ps1 logs      # follow the log; -NoFollow just prints it
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\service.ps1 restart
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\service.ps1 uninstall
```

The log is `%LOCALAPPDATA%\pitwall\logs\server.log`. `stop`, `restart` and `uninstall` refuse while telemetry is
live (exit code 3) unless you add `-Force`. Stopping ends the server at once, so do it between sessions. Starting
at a real logon has not been exercised yet (CI starts the task directly).

### Linux

There is no service script for Linux yet.

## First-run checklist

1. Open the dashboard on the computer and check it loads.
2. **Drivers** (new dashboard: Settings › Drivers). Pitwall creates one driver profile on first start, named
   "Driver" (or `PITWALL_DRIVER_NAME` from `.env`), with skill level Advanced: rename it, set your skill level and
   coaching intensity, and add a profile for everyone who uses the rig. Choose who is in the seat before driving:
   sessions, reference laps and personal bests belong to that driver.
3. Run the [demo](#try-the-demo-no-game-needed) to see the screens fill in.
4. Set up the game on the **Connect** page and check packets arrive with 0 rejected.
5. Choose the AI engineer: Off, Local or Cloud.
6. Optional: open Pitwall on the iPad, go live on the radio and say "radio check".
7. Drive at least three clean laps. The track map appears after the first lap, coaching and the live delta to your
   reference from the second, and the corner model is fixed after three clean laps. In F1 25, lap times should
   match the game to the millisecond.

`uv run pitwall doctor` checks the setup at any time (ports, firewall, dashboard, voice, AI, telemetry) and prints a
fix for each problem.

## Platform notes

**Mac with Apple Silicon.** The platform Pitwall is developed on and where F1 25 on PS5 was tested live.
[docs/status.md](status.md) lists what is verified there.

**Intel Mac.** Not run yet; it follows from the code. Follow the Mac steps. Parakeet speech recognition and the
natural voice need Apple Silicon: `uv sync` skips Parakeet automatically, and `scripts/setup-tts.sh` refuses to run.
The macOS voices work; use a whisper.cpp server for speech recognition.

**Linux.** Not yet run with a game or by a user; it follows from the code. CI builds the dashboards on Linux, and each
release zip is installed and run with synthetic telemetry on a Linux runner before it is published. Allow UDP 20777 and
TCP 8770 through the firewall. There is no `say`, so the server is silent: the radio shows text, or the iPad speaks with
its own voice. Use whisper.cpp for speech recognition. The Connect page's list of the computer's addresses needs
`ifconfig` (the `net-tools` package); `pitwall serve` prints the address either way. There is no service script for
Linux.

**Windows 10/11.** CI-tested on Windows (GitHub runners), not yet validated live with a game on a Windows PC. CI runs
the test suite, `install.ps1`, a smoke test that streams a recorded F1 25 session and a synthetic one over UDP, the
background service and the firewall rules; the tests ran from a git checkout, not from a release folder. The
scripts in `scripts\windows` (guide: [scripts/windows/README.md](../scripts/windows/README.md)) do the install
(`install.ps1`), run the server (`pitwall.ps1`), open the firewall for the local subnet on Private networks
(`firewall.ps1 add`, as administrator) and start Pitwall at logon (`service.ps1 install`). The radio speaks with
Windows' built-in voices; spoken questions need a whisper.cpp server. `smoke.ps1` checks an install end to end
without a game. The Connect page lists the address of the default network connection.

## Updating

The database is upgraded automatically when Pitwall starts.

<!-- --- lane install --- -->
### With `pitwall update`

If you installed with the [one-line installer](#install-with-one-command), or from a release zip by hand, update in
the folder you run Pitwall from (between sessions):

```bash
cd ~/Pitwall/pitwall-v0.2.0 && uv run pitwall update        # Windows: cd "$env:LOCALAPPDATA\Pitwall\pitwall-v0.2.0"; uv run pitwall update
```

It lists what changed in each newer release, asks before it does anything, then installs the new version next to
the current one exactly as the installer does: download, SHA-256, `uv sync`, a database backup in
`<data>/backups/`, your `.env` carried forward, and the background service moved to the new version (it waits up to
90 s until the new version itself answers, not the old one, and puts everything back if it does not). Your data
folder stays where it is. It refuses while someone is driving: telemetry live, or a game that sent some less than 2
minutes ago (a paused game sends nothing) (exit code 3; `--wait-idle 120` waits up to 2 hours instead). It checks
again just before the switch, and the service scripts refuse too if a session starts in between.

On macOS, starting or moving the background service stops every `pitwall serve` this account runs (from any folder,
on any port), so the service can use its ports. Without the service, a Pitwall you started by hand is never stopped:
the summary tells you to restart it.

- `uv run pitwall update --check` only looks: it asks GitHub for the latest release and prints it.
- `--version v0.2.1` installs a specific release (an older one asks first, in the installers too); `--pre` includes
  pre-releases (automatic when you run a pre-release).
- The background service stays as you have it: one you use moves to the new version, and none is added.
  `--service` also installs one (start at login); `--no-service` leaves it on the old version.
- `--rollback` goes back to the previous version (its folder is kept). The database may already have columns the
  newer version added; older versions ignore them, and the backup from before the update is in `<data>/backups/`.
- A release folder you installed by hand is adopted on its first update: its `data` folder moves to `~/Pitwall/data`
  (the parent folder's `data`) after you agree.
- **Coming from v0.1.0**, which has no `pitwall update` yet: run the [one-line installer](#install-with-one-command)
  once. With your release in `~/Pitwall/pitwall-v0.1.0` (as these docs suggested) it finds it, offers to move its
  `data` folder to `~/Pitwall/data` and moves its background service; elsewhere, pass `--home` with the folder that
  holds your release folder. From then on, `pitwall update` works.
- Settings › System shows when a new version is out and the command to run; it never updates by itself.

Old version folders are never deleted automatically: the summary lists the ones you can delete.
<!-- --- end lane install --- -->

### From one release to the next (by hand)

1. Stop Pitwall between sessions: Ctrl+C, or the background service (macOS:
   `scripts/pitwall-service.sh uninstall`; Windows: `scripts\windows\service.ps1 uninstall`, run in the old
   folder).
2. Download, check and unzip the new release next to the old one, as in
   [Install from a release](#install-from-a-release), but stop after unzipping. Do not run `uv sync`, `install.ps1`
   or Pitwall in the new folder yet: it must not have a `data` folder when you move yours in.
3. Move your data folder (and `.env`, if you made one) from the old folder into the new one. The first command stops
   if the new folder already has a `data` folder, instead of moving yours inside it:

   ```bash
   if [ -e pitwall-v0.2.0/data ]; then echo "pitwall-v0.2.0/data already exists"; else mv pitwall-v0.1.0/data pitwall-v0.2.0/data; fi
   cp pitwall-v0.1.0/.env pitwall-v0.2.0/.env        # only if you made one
   ```

   ```powershell
   if (Test-Path .\pitwall-v0.2.0\data) { throw 'pitwall-v0.2.0\data already exists' }; Move-Item .\pitwall-v0.1.0\data .\pitwall-v0.2.0\data
   Copy-Item .\pitwall-v0.1.0\.env .\pitwall-v0.2.0\.env   # only if you made one
   ```

   If it says the new folder already has a `data` folder (Pitwall was started there), check that folder holds
   nothing you want, delete it, and run the command again.

4. In the new folder: `uv sync --all-extras` (Windows:
   `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install.ps1`, which also keeps the data
   folder private), then start Pitwall, or install the background service again from the new folder.
5. When everything works, delete the old folder.

To keep your data outside the release folders, set an absolute `PITWALL_DATA_DIR` in `.env` (for example
`PITWALL_DATA_DIR=/Users/<you>/pitwall-data`, or `C:\Users\<you>\pitwall-data` on Windows) and copy `.env` to each new
release. The macOS service ignores that line; give it the folder when you install it:
`PITWALL_DATA_DIR="$HOME/pitwall-data" scripts/pitwall-service.sh install`. The background services have not been
tested from a release folder yet.

### A git clone

```bash
git pull
uv sync --all-extras
cd web && npm ci && npm run build && cd ..      # or: make web-react (HeroUI Pro licence)
scripts/pitwall-service.sh restart              # if you run the service; otherwise restart `pitwall serve`
```

On Windows, run `install.ps1` again after `git pull`: it updates the packages and rebuilds the dashboard (it stops a
running Pitwall from that folder first, never while telemetry is live). `scripts/release.sh` is the maintainer's
deploy script; you do not need it.

## Your data

Your sessions and settings are in the data folder (`data/` in the folder you start Pitwall from, or
`PITWALL_DATA_DIR`). With the [one-line installer](#install-with-one-command) it is `~/Pitwall/data`
(Windows: `%LOCALAPPDATA%\Pitwall\data`), outside the version folders:

```
~/Pitwall/
  install.json          which version is current, the previous one and the data folder (written by the installers)
  data/                 your sessions and settings: never moved or deleted by an update
  pitwall-v0.2.0/       the current version, with its own .env (PITWALL_DATA_DIR points at ../data, as a full path)
  pitwall-v0.1.0/       the previous version, kept for --rollback
```

Before each update the database is copied to `data/backups/pitwall-before-<version>-<date>.sqlite3` and checked;
backups are never deleted automatically.

**Update checks.** With `PITWALL_UPDATE_CHECK=auto` (the default) Settings › System asks GitHub for the latest
release at most once a day, and only while nobody is driving: one HTTPS request to api.github.com, which sees your
IP address and the Pitwall version, and nothing else is sent. `manual` asks only when you press "Check now" or run
`uv run pitwall update --check`; `off` means Pitwall never contacts GitHub on its own. Nothing is checked until
someone opens Settings › System or runs a command, and `pitwall doctor` only reads the last result
(`data/update_check.json`, which `uv run pitwall update` also refreshes).

Downloaded speech models live in `~/.cache/huggingface` (Parakeet) and
`~/Library/Application Support/pitwall` (the natural voice). The background service's logs are in
`~/Library/Logs/pitwall` (macOS) or `%LOCALAPPDATA%\pitwall\logs` (Windows).

The data folder holds:

| File | What |
|---|---|
| `pitwall.sqlite3` | Sessions, laps, analysis, drivers, engineer conversations |
| `captures/*.pwcap` | Raw packets of every session (compressed, about 400 MB per hour of F1 25 at 60 Hz), so sessions can be reprocessed after a fix |
| `access_token` | The token for devices on your network |
| `settings.json` | Choices made in the dashboard (games, AI engineer) |
| `secrets.json` | API keys entered in the dashboard (readable only by you) |
| `llm_usage.json` | Model calls, tokens and estimated cloud cost per day |
| `radio_voice.json` | The engineer voice last picked |

To back up, stop Pitwall and copy the folder. Nothing in it leaves the computer unless you turn on a cloud model,
which then receives fact sheets as described in [The AI engineer](#the-ai-engineer-optional).

## Troubleshooting

Start with `uv run pitwall doctor`: it checks ports, firewall, dashboard, voice, AI and telemetry and prints a fix
for each problem.

**"Address already in use" or the server will not start.** Something else holds port 8770 or UDP 20777, often a
Pitwall already running (a second window, or the background service: `scripts/pitwall-service.sh status`, Windows
`scripts\windows\service.ps1 status`) or another telemetry app such as SimHub.
- macOS and Linux: `lsof -nP -iTCP:8770 -sTCP:LISTEN` and `lsof -nP -iUDP:20777`.
- Windows: `Get-NetTCPConnection -LocalPort 8770 -State Listen` and `Get-NetUDPEndpoint -LocalPort 20777`
  (the `OwningProcess` column is the process id). Hyper-V, WSL or Docker can also reserve port ranges, which then
  cannot be used ("access denied" in doctor): `netsh interface ipv4 show excludedportrange protocol=udp` (and
  `protocol=tcp`).
- Or use other ports: `--port` or `PITWALL_HTTP_PORT`, and `PITWALL_F1_UDP_PORT` (then set the same port in the
  game; on Windows run `firewall.ps1 add` again).

**No packets arrive.**
- Firewall. macOS: allow incoming connections for Python (System Settings › Network › Firewall › Options).
  Windows: run `firewall.ps1 add` as administrator, and check the next two points.
- Windows: the network must be **Private** (Settings › Network & internet › your network › Network profile type).
  The firewall rules only apply on Private networks.
- Windows: if someone clicked Cancel on the "allow access" prompt for Python, Windows created rules that block it,
  and block rules win. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\firewall.ps1 status`
  shows them; delete or disable them in "Windows Defender Firewall with Advanced Security".
- Wrong IP address in the game. The computer's address can change; a DHCP reservation in your router fixes that.
- The console and the computer are on different networks or VLANs, or the Wi-Fi isolates clients (try a cable).
- F1 25: UDP Broadcast Mode must be Off and the port must match.
- Packets arrive but are rejected with "unsupported packetFormat 2024": set UDP Format to 2025 or 2026.
- GT7 and Assetto Corsa: the integration must be enabled on the Connect page with the console's IP address, and
  Assetto Corsa only answers while you are on track.

**Windows: the scripts will not run.** Always start them as
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\<script>.ps1`: `-ExecutionPolicy Bypass`
applies to that one PowerShell process and does not change your PC's policy. If Windows still refuses ("not
digitally signed"), the files carry the mark of a browser download: unblock them once with
`Get-ChildItem -Recurse scripts\windows | Unblock-File`. "Disabled by Group Policy" is a work or school PC policy:
ask whoever manages the PC.

**The browser shows "Pitwall API is running" instead of the dashboard.** No dashboard is built. In a release folder
this means `web-react\dist` is missing: unzip the release again. In a clone, build the classic dashboard
(`cd web && npm ci && npm run build`) or the new one (`make web-react`, HeroUI Pro licence), then reload.

**The `web-react` build fails with `Can't resolve '@heroui-pro/react/...'`.** HeroUI Pro is not installed because
there is no licence sign-in. Use a release, the classic dashboard, or run `npx heroui-pro@latest login` and
`make web-react`.

**The dashboard loads on another device but shows no data** (the API answers "access token required"). Open the
link from `uv run pitwall token` once on that device.

**No microphone on the iPad.** You are on `http://`. Use the Tailscale HTTPS address. If audio comes out of the
iPad speaker, reconnect the AirPod to the iPad and tap Go live again.

**The radio has no speech recognition.** Parakeet needs an Apple Silicon Mac and `uv sync --all-extras`. Elsewhere,
use a whisper.cpp server (`PITWALL_STT_ENGINE=whispercpp`). The log says why the engine is unavailable.

**The engineer sounds robotic.** On a Mac, the natural voice is not installed, still starting (it takes a few
seconds after Pitwall starts) or has restarted, so the macOS voice is speaking. Run `scripts/setup-tts.sh`. Radio &
voice settings show which voice is in use.

**Answers say they fell back to the facts.** The model is off, not reachable or failed the grounding check. This
is expected without a model; the answer is still correct. Check with `uv run pitwall llm-check`, or switch
**Settings › AI engineer** to Off (before that page has been saved, `PITWALL_LLM_ENABLED=false` does the same).
`pitwall ask` tries the model set in `.env` unless `PITWALL_LLM_ENABLED=false` or you add `--no-llm`; it ignores
the choice saved in Settings › AI engineer.

**Lap times are off by a lap or look wrong.** Keep the capture from `data/captures/` and report it: real captures
are how the decoders are checked.

## For developers

```bash
make check                      # ruff, mypy --strict, the classic dashboard's type check, and pytest
uv run pytest -m recorded       # tests against real recorded captures
uv run pytest -m llm            # needs a reachable model server (opt-in)
uv run pytest -m live tests/live -s   # with a real game streaming (stop pitwall serve first)
make web-react-check            # the new dashboard's type check and unit tests (HeroUI Pro licence)
```

Tests that load the real speech models are opt-in: `-m voice` (or `PITWALL_VOICE_TESTS=1`) runs Parakeet on
macOS `say` audio, and `-m tts` runs the natural voice (Kokoro). Tests of the Mac's own `say` voices run in the
normal suite and are skipped where `say` is missing. A few radio tests fail if your `.env` or environment sets
`PITWALL_VOICE_ENABLED=false` or a non-default `PITWALL_TTS_ENGINE`; unset them while testing.
[validation.md](validation.md) describes the evidence tiers and how to test a game live on your setup, and
[releasing.md](releasing.md) how releases are built.
