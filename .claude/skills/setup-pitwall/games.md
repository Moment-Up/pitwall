# Game telemetry steps for /setup-pitwall

Source of truth: `src/pitwall/connect.py` (`game_guides`: the same steps the dashboard's Setup > Connect page shows,
with this computer's IP filled in) and `src/pitwall/capabilities.py` (support status; print it with
`uv run pitwall capabilities`). If this file and the code disagree, the code wins - tell the user what you used.

Fill in: `<IP>` = doctor `lan_ip` (this computer's LAN address; for a PC game running on this same computer,
`127.0.0.1` should also work for F1 and Forza - untested with Pitwall). `<F1 port>` = doctor `server.udp_port`
(default 20777). The console and this computer must be on the same network (not a guest Wi-Fi; wired is most
reliable).

Support vocabulary (from capabilities.py, strongest first): live_validated > recorded_validated > spec_implemented >
community_documented > partial > unverified > unsupported. Quote it; never round it up.

## EA SPORTS F1 25 (incl. 2026 Season Pack) - PS5, Xbox Series X|S, PC

Status: format 2025 on **PS5: live_validated** (F1 25 v1.26, real races, 2026-10-10). PC / Xbox Series:
spec_implemented (same packets per EA's spec; not yet tested on those platforms). Format 2026 (Season Pack):
spec_implemented, synthetic tests only. F1 24 and older (format 2024): unsupported - rejected with a message.

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

Status: **community_documented** - implemented from community protocol docs (Salsa20, variants A/B/~/C); synthetic
tests only, not yet tested on a real PS5.

Nothing to set in the game: Pitwall asks the console for telemetry (heartbeat to UDP 33739, replies to 33740).

1. Setup > Connect > Gran Turismo 7: Enable (Pitwall listens on UDP 33740; Windows: re-run `firewall.ps1 add`).
2. Console IP: PS5 Settings > Network > Connection Status > View Connection Status > IPv4 Address.
3. Packet variant: C (richest; B and ~ also work).

Notes: telemetry flows only while the console receives the heartbeat (starts within ~2 s). Only one app on this
computer can receive GT7 telemetry (UDP 33740): quit SimHub etc. GT7 sends no lap distance or track id: Pitwall
integrates speed (~1 % drift per lap) and recognises the circuit from the start/finish line after the first lap.

## Forza Motorsport (2023) / Forza Horizon 4, 5 - Xbox, PC

Status: **community_documented** - implemented from Turn 10 / Playground's Data Out documentation; synthetic tests
only, not yet tested on a real console. Forza Horizon 5 on PS5: no source confirms Data Out exists there. Forza
Horizon 6 and Forza Motorsport 7 are not in the capability matrix: say they are untested with Pitwall.

1. Setup > Connect > Forza: Enable (Pitwall listens on UDP 5301 by default; Windows: re-run `firewall.ps1 add`).
2. In the game: Settings > Gameplay & HUD > UDP Race Telemetry (Horizon: Settings > HUD and Gameplay):

| Setting | Value |
|---|---|
| Data Out | On |
| Data Out IP Address | `<IP>` |
| Data Out IP Port | 5301 (or the port shown on Setup > Connect; Horizon 6 reserves 5200-5300 for itself) |
| Data Out Packet Format | Dash (Forza Motorsport only; Horizon has one format) |

Horizon free roam has no laps: live data only; lap analysis needs a circuit race.

## Assetto Corsa (original) - PS4 version on PS5, PS4, PC

Status: PS4 version on **PS5: recorded_validated** - the protocol was probed live (2026-10-11) and the decoder is
validated on that recording, but Pitwall's own connection, lap storage and coaching have not yet run end to end on
the console. PS4 hardware and PC: community_documented. Xbox One: unsupported (no telemetry interface).

Nothing to set in the game's menus: Pitwall registers with the game (handshake to its UDP 9996; no local port and
no firewall rule needed for it).

1. Setup > Connect > Assetto Corsa: Enable.
2. Console IP: the PS5's IPv4 address (as for GT7). For AC on a PC, that PC's LAN IP - on this same computer use its
   LAN IP, not 127.0.0.1 (refused). Only private LAN addresses are accepted.
3. Platform: PS5, PS4 or PC (what runs the game).
4. Get on track (Hotlap, Time Trial, Practice or a race): AC's telemetry server exists only while on track.

Connect page status "refused" = the console answered but AC is not on track yet; "handshaking" with no reply = not on
track, wrong IP, or Wi-Fi client isolation. On a new track the first lap is used to learn the track length. Steering,
tyre temperatures, fuel and sectors are not sent by the game. A diagnostic probe command is on Setup > Connect.

## Record another game (raw packets, no analysis) - e.g. Project Motor Racing

Status: capture only - no decoder, no live analysis; the recording lets a decoder be written from real data.

1. Setup > Connect > Record another game: Enable (default UDP 7576; Windows: re-run `firewall.ps1 add`).
2. Project Motor Racing: Settings > Preferences > UDP telemetry (v2.3+ on consoles): On, host `<IP>`, port 7576.

## Not supported (say so plainly)

- **Assetto Corsa Competizione** PS5 / Xbox Series: unsupported - no external telemetry on consoles (PS5 tested
  2026-10-11: nothing). PC: partial, not implemented (shared memory / broadcasting API).
- **iRacing** (PC): partial, not implemented (irsdk).
- **F1 24 and older**: unsupported (UDP format 2024).
- Anything else: not implemented. Offer "Record another game" if the game can send UDP telemetry.
