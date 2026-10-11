# Troubleshooting for /setup-pitwall

Always start with `uv run pitwall doctor --json`: every non-ok check has a one-line `fix`. Then use the matching
section. Read-only diagnostics need no permission; anything that changes the machine does.

## No telemetry arrives

Check in this order (doctor `telemetry`, `udp_*`, `firewall`, `network_profile`, `lan_ip`; Setup > Connect shows
"Live connections" and per-game errors):

1. **Server running and listening?** doctor `server.running` true and the game's `udp_*` check says "Pitwall is
   listening on UDP <port>". If a `udp_*` check fails, see "Port in use". The right game selected with its input
   on: doctor `game` ok (otherwise see "doctor `game` warns").
2. **Right IP and port in the game?** The game's IP must be doctor `lan_ip` (this computer), not the console's, not
   a Tailscale 100.x address. The port must match exactly. The IP can change after a router restart (DHCP): suggest
   a DHCP reservation in the router if it keeps changing.
3. **Same network?** Console and computer on the same router/subnet; not a guest Wi-Fi; no "client/AP isolation";
   VPN on the computer off (doctor `lan_ip` warns when traffic leaves through a non-LAN address).
4. **Firewall.** Windows: the inbound rules from `firewall_rules` (user runs `scripts\windows\firewall.ps1 add` as
   Administrator), network profile Private, no inbound *block* rule for python.exe (windows.md). macOS: firewall
   allows Python / "Block all incoming connections" off (macos.md).
5. **In the game.** F1 25: on track or in the garage (menus send little), UDP Telemetry On, Broadcast Off, Format
   2025/2026. GT7: console IP right and GT7 enabled on Setup > Connect. AC: on track (not in menus).
6. **Packets arrive but are not understood:** doctor `telemetry` warn "packet(s) arrived but were not understood"
   -> wrong UDP Format (F1 24 / 2024 is unsupported) or another device/game sends to that port.
7. **Prove the path without the game:** `uv run pitwall send <data_dir>/captures/synthetic-coaching-demo-2025.pwcap
   --port <port>` (from this computer, to 127.0.0.1; `<data_dir>` from doctor) must make `telemetry` report the
   SYNTHETIC packets (it stays `info`: only a game makes it `ok`). If that works and the console does not, the
   problem is between the console and this computer (2-4).

## doctor `game` warns

The `game` check compares the selected game (`uv run pitwall game show`) with the inputs and, while a server runs,
with what is actually arriving. Its `fix` line is the command to run; selecting a game never turns another input off.

- **"... is selected but its telemetry input is off":** run the `fix` (`uv run pitwall game set <id>`), which
  switches the input on. GT7 needs `--console-ip <IP>` for that (without it the input would search the network: ask
  the user first, then they switch it on at Setup > Connect). If the result says the input is busy (`skipped_live`),
  change it after the session.
- **"Assetto Corsa needs the console's IP":** ask the user for it (games.md), then
  `uv run pitwall game set <id> --console-ip <IP>`. GT7 without an IP is only `info`: Pitwall searches the network
  for the console; set the IP if no telemetry arrives.
- **"Receiving <game>, but <other game> is selected":** a real game is sending, but not the selected one. Ask the
  user which game they are playing now. If the detected one is right, run the `fix`; if the selection is right,
  something else is sending to that port (another console, a second game, a replay tool): find it on Setup >
  Connect > Live connections. The synthetic demo and replays (`pitwall replay`, the dashboard's Replay) never cause
  this warning; `pitwall send` of a recording of a real game does, because it arrives like that game.
- **"Pitwall can't read <game> telemetry":** that game or platform is not supported (games.md "Not supported").
  If the user also plays something Pitwall reads, select that; otherwise only the demo and recording are left.
- **`game` info "no game selected":** expected until SKILL.md step 6. `uv run pitwall game list`, then
  `uv run pitwall game set <id>` (or Setup > Game).

## Port in use

doctor `http_port` / `udp_*` fail with "is in use by another program" (or "blocked (access denied)" on Windows).

- Find the owner: macOS `lsof -nP -iUDP:20777` / `lsof -nP -iTCP:8770 -sTCP:LISTEN`; Windows see windows.md
  ("Who uses a port", "Reserved ports").
- Often it is Pitwall itself: a second copy, the start-at-login service (`scripts/pitwall-service.sh status`,
  Windows `scripts/windows/service.ps1 status`), or SimHub / another telemetry app on 20777 or 33740.
- Never stop someone else's program yourself: tell the user what holds the port and let them choose: quit it, or move
  Pitwall - HTTP with `PITWALL_HTTP_PORT=<port>` in `.env`; game ports on Setup > Connect (and the same port in the
  game). Then re-run doctor (Windows: re-run `firewall.ps1 add` for the new port).

## Dashboard not built / blank page

- doctor `dashboard` fail ("no dashboard built"; the browser shows "Pitwall API is running"). In a release folder:
  `web-react/dist` is missing, so the zip was not unzipped completely - unzip it again into an empty folder (never
  copy a `dist` from elsewhere). In a clone: build one (SKILL.md steps 2-3), or offer the release download. Node.js
  too old -> doctor `node` (a release does not need Node.js: its `node` check is only info).
- React dashboard and HeroUI Pro: with no HeroUI Pro login or token on this computer, `npm ci` in `web-react/` looks
  fine (the package's installer prints "Sign in to finish installing", which npm hides), then `npm run build:root`
  fails with `Can't resolve '@heroui-pro/react/...'`. An expired or invalid login fails at `npm ci` instead
  ("Access denied ... HeroUI Pro"). Either way: offer the release download (SKILL.md "Download the latest
  release") or build the Svelte dashboard; do not look for, ask for or work around tokens.
- doctor says the React build is for `/next/` or older than its source: rebuild (`npm run build:root` in web-react/).
- Both built: the React one is served. To use the Svelte one, the user deletes `web-react/dist` (ask first).
- After `git pull`, rebuild the dashboard (doctor warns when it is older than its source); Windows: re-run
  `install.ps1`, which also updates the Python packages. A release is never rebuilt: update to a newer release
  instead (SKILL.md "Updating").

## Windows: scripts will not run

"running scripts is disabled on this system", "not digitally signed", or nothing happens: see windows.md
"Execution policy". Always call scripts as `powershell -NoProfile -ExecutionPolicy Bypass -File <script> <args>`.
A script that waits for "[y/N]" input hangs in this session: stop it and re-run with `-NonInteractive` (install.ps1),
or ask the user to run it in their own PowerShell window.

## AI engineer does not answer

doctor `llm` warn "does not answer": the configured provider is down or unreachable. Pitwall still works (answers are
deterministic). Fix on Settings > AI engineer (start the local server, choose another provider, or turn it off);
its Test button checks the provider and key. `uv run pitwall llm-check` is not the check here: it only probes
`PITWALL_LLM_BASE_URL` (default 127.0.0.1:8081) and ignores the dashboard's provider and "off". Keys are entered on
that page by the user, never in chat.

## Phone/iPad cannot open the dashboard

- Same network, the link includes `?token=` (copy it from Setup > Connect), `PITWALL_HTTP_HOST` is not 127.0.0.1
  (doctor `http_port` warns), Windows HTTP firewall rule present.
- Radio microphone silent or no permission prompt: the page is on plain http. Use the Tailscale HTTPS address
  (SKILL.md step 7). On iPad, Safari must be allowed to use the microphone for that site.

## Settings look wrong

- doctor `settings` shows whether a `.env` was found in the current folder and which dashboard sections are saved.
  Pitwall reads `.env` and the `data` folder relative to the folder it is started from: always start it from the
  Pitwall folder (the release folder or the clone; doctor `data_dir` warns otherwise), or set an absolute
  `PITWALL_DATA_DIR`.
- Variable names are `PITWALL_<SETTING>` for each field in `src/pitwall/config.py` (for example `PITWALL_HTTP_PORT`,
  `PITWALL_F1_UDP_PORT`, `PITWALL_LLM_ENABLED`, `PITWALL_DATA_DIR`).
