# Windows details for /setup-pitwall

Status to tell the user: Windows support is new. It is CI-tested on Windows (GitHub runners: the `windows` job in
`.github/workflows/ci.yml` runs the tests and these scripts on windows-latest, and the release workflow installs and
runs each release zip there) but **not yet validated live with a game on a Windows PC**. Consoles (PS5/Xbox) send
telemetry over the network exactly as they do to a Mac, so the same in-game settings apply. `scripts/windows/README.md`
is the user-facing guide to the scripts.

Claude Code's Bash tool on Windows is Git Bash: forward slashes work, `$` inside double quotes is expanded by bash
(use single quotes around PowerShell code). Every script below lives in `scripts/windows/`; read its header comment
(`.SYNOPSIS` / `.PARAMETER`) before running it - that is the source of truth for its options.

## Prerequisites (ask before each install)

| Tool | Check | Install (winget, from Git Bash or PowerShell) |
|---|---|---|
| Git | `git --version` | `winget install --id Git.Git -e --source winget` (Claude Code itself needs Git Bash, so it is usually present) |
| uv | `uv --version` | `winget install --id astral-sh.uv -e --source winget` |
| Node.js LTS (a clone only) | `node --version` (20.19+ / 22.12+) | `winget install --id OpenJS.NodeJS.LTS -e --source winget` (installs for all users: Windows shows a UAC prompt) |

A release folder needs only uv (git is there anyway for Claude Code). After winget installs something, this Claude Code
session may not see the new PATH: ask the user to restart Claude Code, then continue. No winget? Use the installers from
https://docs.astral.sh/uv/ and https://nodejs.org. Python: `uv sync` installs Python 3.12 itself.

## Install

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install.ps1 -NonInteractive                    # release folder
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install.ps1 -NonInteractive -Dashboard svelte  # clone without a HeroUI Pro licence
```

- `-NonInteractive`: never prompts and never installs prerequisites (you did that above); fails with a clear
  message if something is missing. Without it the script asks y/N questions this session cannot answer.
- Release folder (`RELEASE.txt`, no `.git`): the default `-Dashboard auto` keeps the prebuilt `web-react/dist` as it
  is - no Node.js, npm or git needed. Do not pass `-Dashboard none` there (it would report the dashboard as not
  built) or `svelte` (it would build the classic one with Node.js for nothing).
- Clone, `-Dashboard`: `svelte` (free), `react` (HeroUI Pro licence holders: needs their own `HEROUI_AUTH_TOKEN` or
  Pro login), `auto` (react only when `HEROUI_AUTH_TOKEN` is set), `none`.
- It runs `uv sync --all-extras`, checks the server imports, builds the dashboard (a clone only) and creates the
  data folder with private permissions (this account, SYSTEM, Administrators). Running it again updates (it stops a
  running Pitwall from this folder first, never while live). A first run can take several minutes: Bash
  `timeout: 600000` or `run_in_background`; if it is cut off, run it again.

## Start / stop

```bash
PYTHONIOENCODING=utf-8:replace uv run pitwall serve > <data_dir>/serve.log 2>&1   # what the skill uses (Bash run_in_background)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/pitwall.ps1   # what the user runs: Ctrl+C stops
```

`PYTHONIOENCODING` makes the redirected log UTF-8, as `pitwall.ps1` does for the service log (without it Python
writes the ANSI code page). `<data_dir>` is doctor's `data_dir`.

Before the first start, warn the user: Windows may ask whether Python may communicate on networks. Tick **Private
networks** only and click *Allow access*. Cancel creates block rules (see Firewall below); Public would open Python
on public Wi-Fi.

If a background server outlives its task, `powershell -NoProfile -ExecutionPolicy Bypass -File
scripts/windows/service.ps1 stop` stops Pitwall processes started from this folder. It refuses (exit code 3) while
telemetry is live - the SYNTHETIC demo too: stop the demo sender first and wait about 3 s. Stopping ends the
server at once (no clean shutdown), so do it between sessions.
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/smoke.ps1` checks an install end to end without
a game: its own temporary server on 127.0.0.1 (HTTP 8779 / UDP 20779, a temporary data folder, LLM off) receives a
recorded F1 25 excerpt and a SYNTHETIC stream. It touches neither your data nor a running Pitwall. Passing proves the
pipeline runs on this PC, not that a game works.

## Firewall (needs Administrator - the user runs it)

Windows Defender Firewall blocks the console's UDP packets and phone/tablet access until inbound rules exist.
doctor's `firewall_rules` lists the rule names it expects (`Pitwall HTTP <http port>`, `Pitwall UDP <port>` per
enabled game). The user opens PowerShell with "Run as administrator", goes to the repo folder and runs:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\firewall.ps1 add
```

The rules (group "Pitwall") apply only on Private networks and only accept devices on the local subnet. `add`
covers the HTTP port and the enabled games (`-Games all` or `-Games f1,gt7` to choose). Re-run it after enabling
another game on Setup > Connect or changing a port. `firewall.ps1 status` (no admin needed, read-only) shows the
rules, the network profile and anything that would block Pitwall - you may run that one yourself. Never add rules
yourself with `netsh`/`New-NetFirewallRule`.

**Network profile.** doctor `network_profile` warns when the connection is *Public* (Windows treats it as untrusted).
If it is the user's home network, they set it to Private: Settings > Network & internet > Wi-Fi (or Ethernet) >
the network > Network profile type > Private. They make this change, not you.

**Block rules for Python.** If someone clicked Cancel on Windows' "allow access" prompt for `python.exe`, Windows
created inbound *block* rules, and block rules beat allow rules. The right answer to that prompt is: tick **Private
networks** only, then *Allow access* (Windows then also adds a block rule for the *Public* profile: that one is
harmless and should stay). Check (read-only; `firewall.ps1 status` reports the same):

```bash
powershell -NoProfile -Command 'Get-NetFirewallApplicationFilter | Where-Object { $_.Program -like "*python*" } | Get-NetFirewallRule | Where-Object { $_.Direction -eq "Inbound" -and $_.Action -eq "Block" -and $_.Enabled -eq "True" -and [string]$_.Profile -match "Private|Any" } | Select-Object DisplayName, Profile, Enabled'
```

If any show up, the user deletes or disables them in "Windows Defender Firewall with Advanced Security".

## Execution policy

`-ExecutionPolicy Bypass` on the command line applies to that one PowerShell process only; it does not change the
machine's policy. If scripts still refuse to run:

- "cannot be loaded ... not digitally signed" after downloading a ZIP: the files carry the Mark of the Web. With
  the user's consent: `powershell -NoProfile -Command 'Get-ChildItem -Recurse scripts\windows | Unblock-File'`.
- "disabled by Group Policy": a work/school PC policy; the user (or their IT) must allow it. Do not try to bypass it.
- Changing the user's policy permanently (`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`) is a setting
  change: only if the user asks for it.

## Voice

- Engineer voice: Windows' built-in SAPI voices (for example Microsoft David / Zira, Hazel for British English).
  doctor `voice_tts` lists them. `PITWALL_TTS_SAPI_VOICE=Hazel` in `.env` picks one (a unique part of the name is
  enough). Windows' newer "natural" voices are not visible to this API.
- Spoken questions (speech recognition) need macOS (Parakeet). Typed questions work. Advanced: a whisper.cpp server
  with `PITWALL_STT_ENGINE=whispercpp` and `PITWALL_WHISPERCPP_URL`.
- The iPad/phone can always speak with its own voice: Settings > Radio & voice > Engineer voice > This device.

## Start at login (optional, no admin)

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/service.ps1 install   # Task Scheduler task "Pitwall", starts now
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/service.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/service.ps1 logs -NoFollow
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/service.ps1 uninstall
```

Log: `%LOCALAPPDATA%\pitwall\logs\server.log`. Stop the demo sender and the server you started by hand first. The
task runs Pitwall from this folder; after moving to a new release folder, run `uninstall` in the old folder and
`install` in the new one (SKILL.md "Updating").
`install`, `stop`, `restart` and `uninstall` refuse while telemetry is live (exit code 3) unless `-Force` - do not
add `-Force` yourself. Not yet exercised: the task starting at a real logon.

## Other Windows notes

- **Same-PC games:** a PC game running on this computer can send F1/Forza telemetry to `127.0.0.1` and the port.
  Assetto Corsa needs this PC's LAN IP instead (Pitwall refuses loopback for the console IP). Untested on Windows.
- **Reserved ports:** Hyper-V / WSL / Docker can reserve port ranges; a port inside one cannot be bound ("access
  denied" in doctor). Check with `netsh interface ipv4 show excludedportrange protocol=udp` (and `protocol=tcp`),
  then pick a port outside them (Setup > Connect, or `PITWALL_HTTP_PORT` in `.env`).
- **Who uses a port:**
  `powershell -NoProfile -Command 'Get-NetUDPEndpoint -LocalPort 20777 | ForEach-Object { Get-Process -Id $_.OwningProcess }'`
  (TCP: `Get-NetTCPConnection -LocalPort 8770 -State Listen`).
- **Sleep:** the PC must stay awake while driving (Settings > System > Power).
- **LAN IP by hand:** `ipconfig` -> the IPv4 Address of the adapter that has a Default Gateway.
- **Tailscale:** after installing it, `tailscale` is on PATH: `tailscale serve status`, then
  `tailscale serve --bg --https=<free port> http://127.0.0.1:<http_port>`.
