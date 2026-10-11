# Pitwall on Windows

Status: Windows support is new. It is **CI-tested on Windows (GitHub runners), not yet validated live with a game on
a Windows PC.** The `windows` CI job (GitHub's `windows-latest` runner) runs the test suite and these scripts:
`install.ps1`, `smoke.ps1` (a recorded F1 25 capture and a synthetic one streamed over UDP), the background service
(`service.ps1`: start, restart after the server dies, refusal while telemetry is live, stop) and the firewall rules.
CI runs them from a git checkout; a release folder has the same scripts. Consoles send telemetry over the network
the same way they do to a Mac.

The scripts are written for Windows PowerShell 5.1 (built into Windows 10/11) and PowerShell 7. CI runs `install`,
`service` and `firewall` under 5.1 and `smoke` under both. Each one documents its options in its header
(`Get-Help .\scripts\windows\install.ps1 -Detailed`). Run them from the Pitwall folder (an unzipped release or a
clone):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\<script>.ps1 <arguments>
```

`-ExecutionPolicy Bypass` applies to that one PowerShell process; it does not change your PC's policy. If Windows
still refuses ("not digitally signed"), the files carry the mark of a browser download: unblock them once with
`Get-ChildItem -Recurse scripts\windows | Unblock-File`. "Disabled by Group Policy" is a work or school PC policy:
ask whoever manages the PC.

## Install from a release (recommended)

A release zip has the new dashboard prebuilt, so you need neither Node.js nor a HeroUI Pro licence. You need
[uv](https://docs.astral.sh/uv/) (`winget install --id astral-sh.uv -e`; `install.ps1` offers to install it).

1. Download `pitwall-<version>.zip` and `pitwall-<version>.zip.sha256` from the latest release on
   https://github.com/Moment-Up/pitwall/releases (not the "Source code" downloads).
2. Put both files in a folder you keep, for example `C:\Users\<you>\Pitwall` (not Downloads, Desktop or Documents:
   your data lives in the release folder). In PowerShell, in that folder (the example is v0.1.0; use your version):

   ```powershell
   (Get-FileHash .\pitwall-v0.1.0.zip -Algorithm SHA256).Hash -eq (Get-Content .\pitwall-v0.1.0.zip.sha256).Split(' ')[0]   # must print True
   Unblock-File .\pitwall-v0.1.0.zip
   Expand-Archive .\pitwall-v0.1.0.zip -DestinationPath .
   cd .\pitwall-v0.1.0
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install.ps1
   ```

   In a release folder (it has `RELEASE.txt` and no `.git`) `install.ps1` uses the prebuilt dashboard as it is and
   needs neither Node.js nor git: it installs the Python packages and makes the `data` folder private.
3. Continue with [Run it](#run-it) below.

Full guide, including moving your data to the next release:
[docs/install.md](../../docs/install.md#install-from-a-release).

## Install from source

1. `git clone https://github.com/Moment-Up/pitwall.git`, then `cd pitwall`.
2. `install.ps1` checks for git, uv and Node.js 20.19+ or 22.12+ (LTS recommended) and offers to install missing
   ones with winget (y/N for each; the Git and Node.js installers ask for administrator permission because they
   install for all users). Then it runs `uv sync --all-extras` (uv downloads Python 3.12 itself), checks that the
   server imports, builds the dashboard and creates the `data` folder with private permissions (only you, SYSTEM and
   Administrators: it holds the access token and any API keys).
   - Dashboard: the new one (`web-react`) uses the licensed HeroUI Pro components, which only install fully with a
     HeroUI Pro login (`npx heroui-pro@latest login`) or `HEROUI_AUTH_TOKEN`. Without either, `npm ci` still
     succeeds but the build fails with `Can't resolve '@heroui-pro/react/...'`. `auto` builds it when
     `HEROUI_AUTH_TOKEN` is set; otherwise the classic Svelte dashboard (`web`) is built, and Pitwall serves it
     whenever `web-react\dist` does not exist. Force one with `-Dashboard react|svelte|none`. A
     [release](#install-from-a-release-recommended) has the new dashboard without a licence.
   - `-NonInteractive` never prompts and never installs anything (CI, Claude Code); it fails with a clear message
     when a prerequisite is missing.
   - Run it again after `git pull` to update (it stops a running Pitwall from this folder first, never while live).

## Run it

1. `pitwall.ps1` runs the server in that window (Ctrl+C stops it). Dashboard: http://127.0.0.1:8770/. Phones and
   tablets need the LAN link with the access token: `uv run pitwall token`. The first time, Windows may ask whether
   Python may communicate on networks: tick **Private networks only** and click *Allow access*. Do not tick Public
   (that would open Python on public Wi-Fi) and do not click Cancel (that creates rules that block Pitwall).
2. `firewall.ps1 add` (PowerShell opened with *Run as administrator*) lets the console and your devices in. The
   network must be set to *Private* (Settings > Network & internet > your network > Network profile type).
3. In the game, send UDP telemetry to this PC's IP address (F1: port 20777). The dashboard's Setup > Connect page
   shows the settings for each game.
4. `uv run pitwall doctor` checks the whole setup (ports, firewall rules, network profile, voice, AI) and prints a
   fix for each problem. `smoke.ps1` checks the install end to end without a game.

## Scripts

| Script | What it does | Admin |
|---|---|---|
| `install.ps1 [-NonInteractive] [-Dashboard auto\|react\|svelte\|none]` | prerequisites, Python packages, dashboard (a release folder keeps its prebuilt one), data folder | no (winget installers may ask) |
| `pitwall.ps1 [-Port N] [-NoUdp] [-Verbose]` | run the server in this window | no |
| `firewall.ps1 add\|remove\|status [-Games enabled\|all\|f1,gt7,forza,record] [-UdpPort N] [-HttpPort N]` | inbound rules `Pitwall HTTP <port>` (TCP) and `Pitwall UDP <port>` per game, Private networks and local subnet only; `add` is idempotent | add/remove: yes |
| `service.ps1 install\|uninstall\|start\|stop\|restart\|status\|logs [-Force] [-NoStart] [-NoFollow] [-Lines N]` | Task Scheduler task "Pitwall": starts at logon, hidden window, restarts the server 10 s after it exits; log `%LOCALAPPDATA%\pitwall\logs\server.log` (start at a real logon not yet exercised) | no |
| `smoke.ps1` | end-to-end check without a game: temporary server on spare ports bound to 127.0.0.1 and a temporary data folder, a recorded F1 25 capture and a SYNTHETIC one streamed over UDP, sessions and lap analysis checked | no |

`service.ps1 stop|restart|uninstall` refuse while telemetry is live (someone is driving), exit code 3, unless
`-Force` - the same rule as `scripts/pitwall-service.sh` on macOS. Unlike launchd's SIGTERM, stopping ends the
server at once (no clean shutdown): the open capture loses its last unflushed packets (the reader tolerates a
truncated file), queued database writes are lost and the current session is not closed - so stop it between
sessions. Firewall `status` also warns when the network is set to *Public* (the rules only apply to *Private*
networks; change it in Settings > Network & internet) and when a Windows *block* rule for Python (created when its
"allow access?" prompt is cancelled) would win over the rules.

## Updating

- **Release:** stop Pitwall between sessions (in the old folder: `service.ps1 uninstall` if you use the background
  service), unzip the new release next to the old one, move `data` (and `.env`, if you made one) into it before you
  run anything there (the new folder must not have a `data` folder yet, or yours ends up inside it), run
  `install.ps1` there, then start Pitwall (or `service.ps1 install`) from the new folder. Details:
  [docs/install.md](../../docs/install.md#from-one-release-to-the-next).
- **Clone:** `git pull`, then run `install.ps1` again (and `service.ps1 restart` if you use the service).

## Set it up with Claude Code

Open Claude Code in the Pitwall folder (an unzipped release or a clone) and run `/setup-pitwall`
(`.claude/skills/setup-pitwall`, Windows details in `windows.md` there). It checks the prerequisites, runs
`install.ps1 -NonInteractive` (no dashboard build in a release folder), `pitwall doctor` and a demo, and walks
through the game, firewall and phone settings, asking before it changes anything. It never asks for API keys or
tokens. The firewall and network-profile steps stay with you (administrator / Windows Settings). Claude Code on
Windows needs Git for Windows.

## Differences from macOS

- No launchd: `service.ps1` uses Task Scheduler (current user, at logon). A PowerShell window may flash at logon.
- Voice: the radio speaks with Windows' built-in voices (`PITWALL_TTS_SAPI_VOICE` picks one; `pitwall doctor` lists
  them). Speech recognition (Parakeet) needs macOS, so spoken questions need a whisper.cpp server
  (`PITWALL_STT_ENGINE=whispercpp`, tested against a mock server only); typed questions and the iPad's own voice
  work.
- Tailscale is not set up by these scripts (`tailscale serve` works the same once Tailscale is installed).
- Uninstall: `service.ps1 uninstall`, `firewall.ps1 remove` (admin), then delete the folder (your data is in `data`).
