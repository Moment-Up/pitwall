# Game telemetry steps for /setup-pitwall

Source of truth: the code. Prefer the `guide` from `uv run pitwall game show --json`: if it disagrees with this file,
the code wins - tell the user what you used. `game show` gives the same steps as the dashboard's Setup > Game and
Setup > Connect pages (`src/pitwall/connect.py`, `game_guides`), with this computer's IP and ports filled in, plus the
support level (`entry.support`, from `src/pitwall/capabilities.py`) and what the game sends, feature by feature
(`entry.features`, from the adapters' field declarations). `uv run pitwall capabilities` prints the whole support
matrix. Before Pitwall is installed (the early question), read `src/pitwall/capabilities.py` and the
"Not supported" section below. This file adds what the user needs to know before Pitwall runs and the ids for
`uv run pitwall game set <id>` (`uv run pitwall game list --all` lists every id).

Fill in: `<IP>` = doctor `lan_ip` (this computer's LAN address; for a PC game running on this same computer,
`127.0.0.1` should also work for F1 and Forza - untested with Pitwall). `<F1 port>` = doctor `server.udp_port`
(default 20777). The console and this computer must be on the same network (not a guest Wi-Fi; wired is most
reliable). When `game set` reported `enabled` or `already_enabled`, the guide's "Connect page > ... Enable" step is
already done.

Support vocabulary (from capabilities.py, strongest first): live_validated > recorded_validated > spec_implemented >
community_documented > partial > unverified > unsupported. `entry.support.words` says the same in words ("Tested
live", "Built from community docs", ...). Quote it; never round it up. Per feature (`entry.features[].status`):
`supported`, `partial` (`short` "Estimated" when Pitwall works the value out itself), `not_sent` (the game does not
send it), `not_implemented` (the game sends it, Pitwall does not read it yet), `unknown` (not known either way).

## EA SPORTS F1 25 (incl. 2026 Season Pack) - PS5, Xbox Series X|S, PC

Ids: `f1_25:ps5`, `f1_25:xbox`, `f1_25:pc`. Driving 2026 Season Pack cars (UDP Format 2026): `f1_25_2026:ps5`,
`f1_25_2026:xbox`, `f1_25_2026:pc`. The F1 input is always on; nothing to switch on.

In the game: **Settings > Telemetry Settings**

| Setting | Value |
|---|---|
| UDP Telemetry | On |
| UDP Broadcast Mode | Off |
| UDP IP Address | `<IP>` |
| UDP Port | `<F1 port>` |
| UDP Send Rate | 60Hz (20Hz works; 60Hz gives ~1.4 m braking-point precision) |
| UDP Format | 2025 (2026 when driving 2026 Season Pack cars; 2024 is not supported) |
| Your Telemetry | Public (Restricted hides some data for other cars; your car is unaffected) |

Optional: Controls > (your wheel) > a spare button = **UDP Action 1** - push-to-talk to the race engineer (hold to
talk; the radio needs the Tailscale HTTPS step). Packets show up within a second of being on track or in the garage.

## Gran Turismo 7 - PS5, PS4

Ids: `gt7:ps5`, `gt7:ps4`.

Nothing to set in the game: Pitwall asks the console for telemetry (heartbeat to UDP 33739, replies to 33740).

1. `uv run pitwall game set gt7:ps5 --console-ip <PS5 IP> --json` switches the GT7 input on (Pitwall listens on UDP
   33740; Windows: re-run `firewall.ps1 add`) and stores the IP. The IP is optional: without it Pitwall searches the
   network for the console.
2. Console IP: PS5 Settings > Network > Connection Status > View Connection Status > IPv4 Address.
3. Packet variant: C (richest; B and ~ also work).

Notes: telemetry flows only while the console receives the heartbeat (starts within ~2 s). Only one app on this
computer can receive GT7 telemetry (UDP 33740): quit SimHub etc. GT7 sends no lap distance or track id: Pitwall
integrates speed (~1 % drift per lap) and recognises the circuit from the start/finish line after the first lap.

## Forza Motorsport (2023) / Forza Horizon 4, 5 - Xbox, PC

Status: **community_documented** - implemented from Turn 10 / Playground's Data Out documentation; synthetic tests
only, not yet tested on a real console. Forza Horizon 5 on PS5: no source confirms Data Out exists there. Forza
Horizon 6 and Forza Motorsport 7 are not in the capability matrix: say they are untested with Pitwall.
Ids: `forza_motorsport:xbox`, `forza_motorsport:pc`, `forza_horizon:xbox`, `forza_horizon:pc`, `forza_horizon:ps5`
(unverified: no source confirms Data Out on PS5). FM7 and Forza Horizon 6 are read by the same Forza input but have
no id of their own: pick `forza_motorsport:<platform>` or `forza_horizon:<platform>` and say so.

1. `uv run pitwall game set forza_motorsport:xbox --json` (or the Horizon id) switches the Forza input on (Pitwall
   listens on UDP 5301 by default; Windows: re-run `firewall.ps1 add`).
2. In the game: Settings > Gameplay & HUD > UDP Race Telemetry (Horizon: Settings > HUD and Gameplay):

| Setting | Value |
|---|---|
| Data Out | On |
| Data Out IP Address | `<IP>` |
| Data Out IP Port | 5301 (or the port shown on Setup > Connect; Horizon 6 reserves 5200-5300 for itself) |
| Data Out Packet Format | Dash (Forza Motorsport only; Horizon has one format) |

Horizon free roam has no laps: live data only; lap analysis needs a circuit race.

## Assetto Corsa (original) - PS4 version on PS5, PS4, PC

Ids: `ac:ps5` (the PS4 version on a PS5), `ac:ps4`, `ac:pc`. `ac:xbox`: not supported (no telemetry interface).

Nothing to set in the game's menus: Pitwall registers with the game (handshake to its UDP 9996; no local port and
no firewall rule needed for it).

1. Console IP: the PS5's IPv4 address (as for GT7). For AC on a PC, that PC's LAN IP - on this same computer use its
   LAN IP, not 127.0.0.1 (refused). Only private LAN addresses are accepted. Required: without it Pitwall cannot
   contact the game.
2. `uv run pitwall game set ac:ps5 --console-ip <IP> --json` switches the Assetto Corsa input on, sets its platform
   from the id (PS5, PS4 or PC) and stores the IP.
3. Get on track (Hotlap, Time Trial, Practice or a race): AC's telemetry server exists only while on track.

Connect page status "refused" = the console answered but AC is not on track yet; "handshaking" with no reply = not on
track, wrong IP, or Wi-Fi client isolation. On a new track the first lap is used to learn the track length. Steering,
tyre temperatures, fuel and sectors are not sent by the game. A diagnostic probe command is on Setup > Connect.

## Record another game (raw packets, no analysis) - e.g. Project Motor Racing

Id: `other:any`. Selecting it does not switch recording on (it listens on a port and writes every packet to disk):
offer it, and on a yes the user enables it at Setup > Connect > Record another game.

Status: capture only - no decoder, no live analysis; the recording lets a decoder be written from real data.

1. Setup > Connect > Record another game: Enable (default UDP 7576; Windows: re-run `firewall.ps1 add`).
2. Project Motor Racing: Settings > Preferences > UDP telemetry (v2.3+ on consoles): On, host `<IP>`, port 7576.

## Not supported (say so plainly)

These ids exist so the user can say what they play; Pitwall cannot read them (`game set` answers with action `none`
and the reason).

- **Assetto Corsa Competizione** PS5 / Xbox Series (`acc:ps5`, `acc:xbox`): unsupported - no external telemetry on
  consoles (PS5 tested 2026-10-11: nothing). PC (`acc:pc`): partial, not implemented (shared memory / broadcasting
  API).
- **iRacing** (PC, `iracing:pc`): partial, not implemented (irsdk).
- **F1 24 and older** (`f1_24:any`): unsupported (UDP format 2024).
- **Assetto Corsa on Xbox One** (`ac:xbox`): unsupported (no telemetry interface).
- Anything else: not implemented. Offer "Record another game" (`other:any`) if the game can send UDP telemetry.
