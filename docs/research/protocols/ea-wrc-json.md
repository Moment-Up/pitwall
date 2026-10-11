# Protocol family `ea-wrc-json`: EA SPORTS WRC UDP telemetry (PC only)

Research date: 2026-10-10. This is an implementation spec for a pitwall adapter. It changes no code.

**Scope.** EA SPORTS WRC (Codemasters, 2023) on PC, game version 1.3 and later. This is the only game in the family.

**Why this family.**
- A current rally title whose UDP output is described by files that the game itself generates. The files are self-describing and official.
- The Mac can be the target directly. No Windows relay is needed.
- The data includes stage distance, stage length and location/route ids, which gives natural track identity.
- Consoles have no interface.

**What pitwall needs.**
- A **schema-driven decoder**. Channel types come from the game's `channels.json`; channel order comes from a packet-structure JSON.
- A **point-to-point stage model**, where one stage run is one lap.

**Not redone here.**
- The compatibility verdicts and port plan in `docs/research/game-compatibility.md` §3.7 and §3.10 [P1].
- Track-knowledge licensing rules in `docs/research/track-knowledge-sources.md` §7 [P2].

**Labels.** Every claim carries a bracketed source ID that resolves to a URL or path in §14.

| Prefix | Source kind |
|---|---|
| **W** | Game-generated official files (EA/Codemasters), read from a third-party copy |
| **O** | Official EA statement or patch notes |
| **N** | News article reprinting official notes |
| **V** | Ecosystem vendor (dashboard or wheel software) setup docs |
| **C** | Open-source code (licence stated) |
| **F** | Forum report (dated) |
| **P** | pitwall's own docs and code |

**Confidence tags:**

| Tag | Meaning |
|---|---|
| **Official** | Stated in the game-generated documentation or EA notes |
| **Corroborated** | Not stated officially, but a shipped third-party implementation depends on it |
| **Gate Gn** | Unknown. Settle it with a pitwall capture before relying on it (§11) |
| **Design** | pitwall's own choice, not a protocol fact |

---

## 0. Research limits (read first)

- **Primary sources were read from a third-party copy.** The authoritative spec is the set of files the game writes to the user's PC under `Documents/My Games/WRC/telemetry/` [W1]. No such PC was available for this session.
- **The copy and its licence.** The copy read is in vAzhureRacingHub, which is GPL-3.0 [C1]:
  - commit `1881af7be8dbdfe8f97873ddac7e4fb01191a98a`;
  - files uploaded 2024-04-24 (commit `554f5ee14b`).
- **What the copy contains.**
  - Its `ids.json` reports game version **1.7.0** [W9].
  - Its `channels.json` is data version **2**, with **66 channels** [W3].
  - It also has EA's PDF *"EA SPORTS WRC - UDP Telemetry Guide (v1.3)"* [W2]. Its text matches the game-generated `readme.txt` [W1], except that the PDF lacks the "Converting UIDs to Strings" section.
- **Use of the copy.** It was used only to read the format. Nothing from that repository is vendored (§12).
- **Game versions after 1.7.0 added channels that this copy does not describe.**
  - The game added channels in 1.8.0 [F11].
  - Their **types, units and positions are not known here**, and are deliberately **not guessed**.
  - The decoder takes them from the user's own `channels.json` (§4.3).
- **Web search was unavailable.** The shared WebSearch budget for this run was used up before this task began. So:
  - no wider search for a post-1.8 `channels.json`;
  - no wider search for a permissively licensed EA WRC implementation.

  Sources were reached by direct URL instead:
  - GitHub and GitLab APIs;
  - a real browser for overtake.gg and forums.ea.com, which return 403 to scripted fetchers.
- **No first-hand capture exists.** Every behavioural detail that the documentation does not state is listed as a gate in §11.

---

## 1. Summary

| Item | Answer | Source |
|---|---|---|
| Platforms | **PC only**, since v1.3 ("Added support for User Datagram Protocol (UDP) on PC", notes last edited 2023-11-08) | [N8] |
| PS5 / Xbox | **No interface**: SIM Dashboard states that the console version ships without a telemetry interface, and that PC has one | [V1]; also [P1] §2 ([V20][V57]) |
| James's PS5 rig | **Gains nothing.** This family helps only PC users, or James if he plays EA WRC on a Windows PC. | [P1] §1.1 |
| Transport | UDP, unicast from the game to a configured **IPv4 or IPv6** endpoint. One entry per packet assignment in `config.json`. | [W1][W8] |
| Handshake / subscription | **None**. Output is configured by editing `config.json` on the PC; pitwall sends nothing. | [W1] |
| Default ports | `session_update` → 127.0.0.1:**20777**; start/end/pause/resume → 127.0.0.1:**20778**. Every packet is disabled (`bEnabled: false`) by default. | [W8] |
| Port clash | 20777 is pitwall's F1 port [P8]. Use **20790** (updates) and **20791** (events) for EA WRC. | Design (§3.3) |
| Encoding | Little-endian, packed in channel order, no padding. Types per `channels.json`. | [W1][W3] |
| Magic / version on the wire | **No version field.** An optional 4-byte `packet_4cc` channel (`SESS`/`SESU`/`SESE`/`SESP`/`SESR`) exists only if the packet structure includes it. The built-in `wrc` structure does **not**. | [W3][W4][W5] |
| Default packet | `wrc` / `session_update`: **237 bytes**, 59 channels, no 4CC and no track or car ids | computed from [W3][W5] (§5.1) |
| Recommended packet | pitwall structure (`udp/pitwall.json`): 4CC + the 237-byte `wrc` body + 11 bytes of identity = **252 bytes**, for all five packets | Design (§6) |
| Rate | Every rendered frame when `frequencyHz` = −1; otherwise capped at N Hz. pitwall recommends **60**. | [W1] |
| Per-game differences | One game only. Differences are by game version (§2: uid channels after 1.3, new channels in 1.8.0) and by packet structure (§5: `wrc`, `wrc_experimental`, user structures). | [W1][W2][F11] |
| Track identity | `location_id` + `route_id` (uint16 uids; names in the user's `readme/ids.json`, UTF-16LE). Length = `stage_length` (float64 m). | [W3][W9] |
| Lap distance | `stage_current_distance` (float64 m). Point-to-point: one stage run = one lap. | [W3] |
| Missing | Sectors/splits, tyre temperatures, pressures and wear, fuel, weather, surface, damage, position in the event, lap validity (in data version 2) | [W3] |
| Spec licence | © 2023 Electronic Arts. Written for third-party tools, but with no redistribution grant. **Implement from the user's own files; ship none of EA's files.** | [W1] §12 |
| Effort | **L**: new schema-driven adapter, two ports, stage model in the lap pipeline | [P1] §2.5 |

---

## 2. Version history relevant to pitwall

| Game version | Telemetry facts | Source |
|---|---|---|
| 1.3 (Nov 2023) | UDP added on PC. Guide v1.3 documents channels, packets, structures, `config.json` and types. It has **no** `ids.json` section. | [N8][W2] |
| ≤ 1.7.0 (by Apr 2024) | `readme.txt` gains "Converting UIDs to Strings". `channels.json` data version 2 has 66 channels, including `vehicle_id`, `vehicle_class_id`, `vehicle_manufacturer_id`, `location_id` and `route_id`. `ids.json` reports game version 1.7.0. | [W1][W3][W9] |
| 1.8.0 (by 2024-04-30) | New channels exist, named in the report: `stage_progress`, `stage_result_time`, `stage_result_time_penalty`, `stage_result_status` and `vehicle_tyre_state_{fl,fr,bl,br}`, plus further new fields that the report does not name. A user reported that adding some of them stopped all output. EA staff (EA_Groguet, 2024-05-16) could not reproduce this with `stage_progress` and advised regenerating the telemetry folder. Types and units: **not known here**. | [F11] |
| Final | EA ended development on 2025-04-30: the 2024 season content was the last expansion, and the game stays available. **The format is therefore effectively frozen.** | [O1] |

**Upgrade policy.** EA's FAQ says new data will arrive as new structure files (for example `wrc_<version>.json`), and older structures keep working unless stated otherwise [W1]. The `wrc` structure in the copy is data version 3 [W5].

---

## 3. Transport

### 3.1 Files on the PC

| Path (under `Documents/My Games/WRC/telemetry/`) | Role | Writable | Encoding seen in the copy | Source |
|---|---|---|---|---|
| `config.json` | Packet → structure → endpoint assignments | yes | UTF-8 (no BOM) | [W1][W8] |
| `udp/custom1.json` | User-editable structure (default contents = `wrc`) | yes | UTF-8 | [W1][W7] |
| `udp/<any>.json` | Third-party or user structures; any number can be added | yes | — | [W1] |
| `readme/channels.json` | Every channel: id, type, units, description | **read-only**; regenerated at each launch | UTF-8 | [W1][W3] |
| `readme/packets.json` | Packet ids and their fourCCs | read-only | UTF-8 | [W1][W4] |
| `readme/udp/wrc.json`, `readme/udp/wrc_experimental.json` | Built-in structures, for reference. The game does **not** read files in `readme/udp/`. | read-only | UTF-8 | [W1][W5][W6] |
| `readme/ids.json` | uid → name for vehicles, classes, manufacturers, locations and routes | read-only | **UTF-16LE with BOM** (`FF FE`) | [W1][W9] |
| `log.txt` | Load status and errors, e.g. `Loaded upd packet structure 'custom1'` (sic) | game-written | ASCII | [W1][W10] |

**Notes on the files:**
- The game creates the folder on first launch; the user must reach the first interactive screen, then quit, before editing [W1].
- After any change, the game must be relaunched to reload `config.json` [W1].
- A patch may regenerate `config.json`; the old file is kept as a backup [W1]. Re-check pitwall's entries after any game update.

### 3.2 `config.json` (schema 2)

The generated file [W8] has a top-level `"schema": 2`, then `udp.packets[]`, `lcd.bDisplayGears` and `dBox.bEnabled` (D-BOX output is on by default).

Each `udp.packets[]` entry has these keys:

| Key | Meaning | Source |
|---|---|---|
| `structure` | Structure id: built-in (`wrc`, `wrc_experimental`) or a file in `udp/` | [W1][W8] |
| `packet` | One of `session_start`, `session_update`, `session_end`, `session_pause`, `session_resume` | [W4][W8] |
| `ip` | Target IPv4 or IPv6 address | [W1] |
| `port` | Target UDP port | [W1] |
| `frequencyHz` | −1 = no limit (every frame); 0 = disabled; N ≥ 1 = at most N packets per second | [W1] |
| `bEnabled` | Enable this entry | [W8] |

**Generated default entries** [W8]. All are `bEnabled: false`:

| Structure | Packet | Endpoint | `frequencyHz` |
|---|---|---|---|
| `wrc` | `session_update` | 127.0.0.1:20777 | −1 |
| `wrc_experimental` | `session_start` | 127.0.0.1:20778 | 0 |
| `wrc_experimental` | `session_update` | 127.0.0.1:20777 | −1 |
| `wrc_experimental` | `session_end` | 127.0.0.1:20778 | 0 |
| `wrc_experimental` | `session_pause` | 127.0.0.1:20778 | 0 |
| `wrc_experimental` | `session_resume` | 127.0.0.1:20778 | 0 |
| `custom1` | `session_update` | 127.0.0.1:20777 | −1 |

**Discrepancies between EA's own texts.** Follow the generated files and verify against a capture.
1. The readme calls the enable key `udp:packets:enabled`, but the generated file uses `bEnabled` [W1][W8].
2. The readme describes `config.json` `versions:schema`, but the generated file has a top-level `schema` [W1][W8].
3. The default event entries use `frequencyHz: 0`, which the readme defines as disabled (no packets sent). Whether single-shot event packets are sent at 0 is **Gate G9**. pitwall's instructions use −1 for event packets to avoid the question.
4. The readme says the fourCC travels in the `packet_uid` channel [W1]. `channels.json` instead defines a separate `packet_4cc` channel (type `fourcc`) and makes `packet_uid` a uint64 rolling counter [W3]. **Trust `channels.json`.**
5. The readme names the `ids.json` lists `vehicles_classes` and `vehicles_manufacturers` [W1]. The generated `ids.json` and the `channels.json` descriptions use `vehicle_classes` and `vehicle_manufacturers` [W3][W9]. **Read the keys present in the user's file.**

### 3.3 Endpoints, direction, coexistence

**Direction and addressing:**
- **Direction.** PC → target only. No handshake, heartbeat or registration exists [W1].
- **Addressing.** Unicast to the configured IP [W1]. Broadcast and multicast are not documented: do not rely on them.
  - Use the Mac's **numeric LAN IPv4**. Give the Mac a DHCP reservation, because `config.json` is static.
  - The docs describe the field only as an IPv4 or IPv6 address and never mention hostnames, so do not use `.local` names.
  - A Tailscale `100.x` address would only work if the PC is on the tailnet. This is unverified.
- **Remote (non-loopback) target.** Allowed by the documented `ip` field [W1]. No first-hand report of a LAN target was found in this session: **Gate G10**.

**Several consumers at once.** Several entries may name the same packet with different structures and endpoints. The generated default already has three `session_update` entries [W8]. Vendors use this to coexist:
- SIM Dashboard adds its own structure file plus a `session_update` entry on port 20432 at 20 Hz [V2];
- Simucube Tuner patches `config.json` to add its own custom packet type, on port 27878 by default [V3].

pitwall should do the same: add its own entries and leave the user's other tools untouched.

**Ports.** EA recommends a different port for the infrequent start/end/pause/resume packets than for `session_update`, so that socket buffer limits do not cause lost packets [W1].

| Use | pitwall default (Design) | Notes |
|---|---|---|
| `session_update` | **20790** | Avoids 20777 (F1 [P8]; EA default), 20778 (EA default), 20432 (SIM Dashboard [V2]), 27878 (Simucube [V3]) and the ports in [P1] §3.10 |
| start / end / pause / resume | **20791** | One adapter serves both ports. The 4CC tells packets apart. |

---

## 4. Encoding and the schema

### 4.1 Wire rules

| Rule | Detail | Confidence | Source |
|---|---|---|---|
| Byte order | Little-endian for all values | Official | [W1] |
| Packing | Values are packed in the order of the channel ids listed in the structure. "Packed" implies no alignment padding; the 237-byte corroboration below supports this. | Official (order); Corroborated (no padding) | [W1][C2] |
| Header channels | `header.channels` is prefixed to **every** packet of that structure, before the packet's own `channels` | Official | [W1] |
| Integer types | uint8/int8/uint16/int16/uint32/int32/uint64/int64 | Official | [W1][W2] |
| Floats | float32, float64 (32/64-bit floating point; IEEE 754 is implied on x86 PCs) | Official | [W1][W2] |
| `fourcc` | 4 characters, **not** NUL-terminated | Official | [W1] |
| `fourcc` byte order | Characters in reading order (`S`,`E`,`S`,`U`) or reversed as a little-endian integer? **Not stated.** | **Gate G2** | — |
| `boolean` | The type list calls it a "single bit". On the wire it **occupies 1 byte** when isolated between other channels. Evidence: vAzhure Racing Hub, a released GPL app, decodes EA WRC only when the datagram length equals its `Pack = 1` struct of the 59 `wrc` channels with a 1-byte `shiftlights_rpm_valid`. That struct is 237 bytes [C2]. Whether **adjacent** booleans are bit-packed is unknown. pitwall's structure never puts two booleans next to each other. | Corroborated; **Gate G1** | [W1][C2] |
| Datagram | One packet per UDP datagram (implied by the docs; [C2] relies on it). Sizes are small (≤ 252 B for pitwall's structure). | Corroborated | [W1][C2] |

### 4.2 Version fields

- **None on the wire.**
- Versions live only in the JSON files. Each file has `versions.schema` (structural) and `versions.data` (content) [W1]. Values in the copy [W3][W4][W5][W6][W7][W8]:

  | File | `schema` | `data` |
  |---|---|---|
  | `channels.json` | 1 | 2 |
  | `packets.json` | 1 | 1 |
  | `wrc.json`, `wrc_experimental.json`, `custom1.json` | 1 | 3 |
  | `config.json` (top-level `schema`) | 2 | — |

- `ids.json` has `schema: 1` and instead carries `data: {major: 7, minor: 0, build: 1}`, meaning game 1.7.0 in the copy [W9].
- EA says tools should check `versions.schema` before parsing [W1].

**pitwall rule (Design):**
- Accept `schema == 1` for `channels.json`, `packets.json` and structure files.
- Accept `schema == 2` for `config.json`.
- Refuse anything else with an actionable message.
- Record every file's versions and SHA-256 in the session's `SessionInfo.extra` and in `.pwcap` metadata, for provenance.

### 4.3 How the decoder obtains the schema

A packet carries no field names. The receiver needs two things:
- the **structure** (ordered channel ids per packet);
- the **types** (from `channels.json`).

| Profile | Structure | Types | When | Validation |
|---|---|---|---|---|
| `pitwall` (default) | pitwall's own `udp/pitwall.json`, shipped as a pitwall-authored id list (§6) | pitwall's pinned type table for the 66 data-v2 channels (§5.0) | always available | exact size 252 B + known 4CC |
| `wrc` | built-in `wrc` | pinned table | user enables the built-in `wrc` entry and points it at pitwall instead of installing `pitwall.json` | exact size 237 B + plausibility (§7.2). **No track or car identity.** |
| `user` | any structure JSON the user uploads | the user's own `readme/channels.json`, uploaded on the Connect page | the user wants 1.8+ channels (e.g. `stage_result_time`) | size computed from their files; 4CC if present |

**Rules:**
- **The pinned type table is verified, not trusted.**
  - When the user uploads `channels.json`, pitwall compares the type of every pinned channel with it.
  - It refuses the `pitwall` profile on any mismatch.
  - Uploads are stored under `data/ea_wrc/` (user-side, never committed or shipped).
- **`wrc_experimental` is not supported.** EA labels it experimental and prone to loss. Its per-packet channel sets differ, so a lost `session_start` loses `stage_length` and the rpm limits [W1][W6].

---

## 5. Packet catalogue

### 5.0 Channel table (`channels.json`, schema 1, data 2, 66 channels) [W3]

**How to read this table:**
- Order = `channels.json` order. Only the **structure** order matters on the wire.
- Byte sizes assume boolean = 1 byte (Gate G1).
- Units are EA's unit strings, abbreviated.
- Descriptions are paraphrased.
- **Axis conventions copied from the channel descriptions:** X positive **left**, Y positive **up**, Z positive **forward**. Taken with the right-hand rule, left × up = forward, so the frame is **right-handed**. The descriptions use the same left/up/forward wording for world position and world velocity, which reads like a template; treat the world-axis semantics as **Gate G6**.

| # | Channel | Type | Bytes | Units | Meaning (paraphrased) |
|---:|---|---|---:|---|---|
| 0 | `packet_4cc` | fourcc | 4 | - | Automatic channel: the packet's 4CC, so one socket can receive all packets |
| 1 | `packet_uid` | uint64 | 8 | count | Rolling per-packet id, for ordering and drop detection |
| 2 | `shiftlights_fraction` | float32 | 4 | - | 0 at `shiftlights_rpm_start` → 1 at `shiftlights_rpm_end` |
| 3 | `shiftlights_rpm_start` | float32 | 4 | rpm | Shift lights start |
| 4 | `shiftlights_rpm_end` | float32 | 4 | rpm | Shift lights end (optimal shift) |
| 5 | `shiftlights_rpm_valid` | boolean | 1 | - | Shift-light rpm values valid |
| 6 | `vehicle_gear_index` | uint8 | 1 | - | Gear, or the neutral/reverse sentinel |
| 7 | `vehicle_gear_index_neutral` | uint8 | 1 | - | Value of `vehicle_gear_index` in neutral |
| 8 | `vehicle_gear_index_reverse` | uint8 | 1 | - | Value of `vehicle_gear_index` in reverse |
| 9 | `vehicle_gear_maximum` | uint8 | 1 | - | Number of forward gears |
| 10 | `vehicle_speed` | float32 | 4 | m/s | Car body speed |
| 11 | `vehicle_transmission_speed` | float32 | 4 | m/s | Speed at the wheel from the transmission (speedo); may differ from body speed |
| 12 | `vehicle_position_x` | float32 | 4 | m | Position X (+left) |
| 13 | `vehicle_position_y` | float32 | 4 | m | Position Y (+up) |
| 14 | `vehicle_position_z` | float32 | 4 | m | Position Z (+forward) |
| 15 | `vehicle_velocity_x` | float32 | 4 | m/s | Velocity X (+left) |
| 16 | `vehicle_velocity_y` | float32 | 4 | m/s | Velocity Y (+up) |
| 17 | `vehicle_velocity_z` | float32 | 4 | m/s | Velocity Z (+forward) |
| 18 | `vehicle_acceleration_x` | float32 | 4 | m/s² | Acceleration X (+left) |
| 19 | `vehicle_acceleration_y` | float32 | 4 | m/s² | Acceleration Y (+up) |
| 20 | `vehicle_acceleration_z` | float32 | 4 | m/s² | Acceleration Z (+forward) |
| 21 | `vehicle_left_direction_x` | float32 | 4 | - | Car's left unit vector, X component |
| 22 | `vehicle_left_direction_y` | float32 | 4 | - | Car's left unit vector, Y component |
| 23 | `vehicle_left_direction_z` | float32 | 4 | - | Car's left unit vector, Z component |
| 24 | `vehicle_forward_direction_x` | float32 | 4 | - | Car's forward unit vector, X component |
| 25 | `vehicle_forward_direction_y` | float32 | 4 | - | Car's forward unit vector, Y component |
| 26 | `vehicle_forward_direction_z` | float32 | 4 | - | Car's forward unit vector, Z component |
| 27 | `vehicle_up_direction_x` | float32 | 4 | - | Car's up unit vector, X component |
| 28 | `vehicle_up_direction_y` | float32 | 4 | - | Car's up unit vector, Y component |
| 29 | `vehicle_up_direction_z` | float32 | 4 | - | Car's up unit vector, Z component |
| 30 | `vehicle_hub_position_bl` | float32 | 4 | m | Wheel-hub vertical displacement (+up), back left |
| 31 | `vehicle_hub_position_br` | float32 | 4 | m | Wheel-hub vertical displacement (+up), back right |
| 32 | `vehicle_hub_position_fl` | float32 | 4 | m | Wheel-hub vertical displacement (+up), front left |
| 33 | `vehicle_hub_position_fr` | float32 | 4 | m | Wheel-hub vertical displacement (+up), front right |
| 34 | `vehicle_hub_velocity_bl` | float32 | 4 | m/s | Wheel-hub vertical velocity (+up), back left |
| 35 | `vehicle_hub_velocity_br` | float32 | 4 | m/s | Wheel-hub vertical velocity (+up), back right |
| 36 | `vehicle_hub_velocity_fl` | float32 | 4 | m/s | Wheel-hub vertical velocity (+up), front left |
| 37 | `vehicle_hub_velocity_fr` | float32 | 4 | m/s | Wheel-hub vertical velocity (+up), front right |
| 38 | `vehicle_cp_forward_speed_bl` | float32 | 4 | m/s | Tyre contact-patch forward speed, back left |
| 39 | `vehicle_cp_forward_speed_br` | float32 | 4 | m/s | Tyre contact-patch forward speed, back right |
| 40 | `vehicle_cp_forward_speed_fl` | float32 | 4 | m/s | Tyre contact-patch forward speed, front left |
| 41 | `vehicle_cp_forward_speed_fr` | float32 | 4 | m/s | Tyre contact-patch forward speed, front right |
| 42 | `vehicle_brake_temperature_bl` | float32 | 4 | °C | Brake temperature, back left |
| 43 | `vehicle_brake_temperature_br` | float32 | 4 | °C | Brake temperature, back right |
| 44 | `vehicle_brake_temperature_fl` | float32 | 4 | °C | Brake temperature, front left |
| 45 | `vehicle_brake_temperature_fr` | float32 | 4 | °C | Brake temperature, front right |
| 46 | `vehicle_engine_rpm_max` | float32 | 4 | rpm | Engine maximum |
| 47 | `vehicle_engine_rpm_idle` | float32 | 4 | rpm | Engine idle |
| 48 | `vehicle_engine_rpm_current` | float32 | 4 | rpm | Engine current |
| 49 | `vehicle_throttle` | float32 | 4 | - | 0..1, **after assists and overrides** |
| 50 | `vehicle_brake` | float32 | 4 | - | 0..1, after assists and overrides |
| 51 | `vehicle_clutch` | float32 | 4 | - | 0..1, after assists and overrides |
| 52 | `vehicle_steering` | float32 | 4 | - | −1 full left .. +1 full right, after assists and overrides |
| 53 | `vehicle_handbrake` | float32 | 4 | - | 0..1, after assists and overrides |
| 54 | `game_total_time` | float32 | 4 | s | Time in game since boot |
| 55 | `game_delta_time` | float32 | 4 | s | Time since the last frame |
| 56 | `game_frame_count` | uint64 | 8 | count | Frames since boot |
| 57 | `stage_current_time` | float32 | 4 | s | Time spent on the current stage |
| 58 | `stage_current_distance` | float64 | 8 | m | Distance reached on the current stage |
| 59 | `stage_length` | float64 | 8 | m | Total length of the current stage |
| 60 | `stage_shakedown` | boolean | 1 | - | In a shakedown event |
| 61 | `vehicle_id` | uint16 | 2 | uid | → `ids.json` `vehicles` |
| 62 | `vehicle_class_id` | uint16 | 2 | uid | → `ids.json` `vehicle_classes` |
| 63 | `vehicle_manufacturer_id` | uint16 | 2 | uid | → `ids.json` `vehicle_manufacturers` |
| 64 | `location_id` | uint16 | 2 | uid | → `ids.json` `locations` |
| 65 | `route_id` | uint16 | 2 | uid | → `ids.json` `routes` |

**Wheel order on the wire.** Per-wheel channels list `bl, br, fl, fr`, which is the same order as F1's RL, RR, FL, FR. Build them with `Wheels.from_rl_rr_fl_fr((bl, br, fl, fr))` [P3].

### 5.1 `wrc` / `session_update` (default, 237 bytes)

Sources: structure [W5] (identical to the copy's `custom1.json` [W7]), header channels empty, types [W3]. This is the only packet of the `wrc` structure.

| Offset | Channel | Type | Size |
|---:|---|---|---:|
| 0 | `packet_uid` | uint64 | 8 |
| 8 | `game_total_time` | float32 | 4 |
| 12 | `game_delta_time` | float32 | 4 |
| 16 | `game_frame_count` | uint64 | 8 |
| 24 | `shiftlights_fraction` | float32 | 4 |
| 28 | `shiftlights_rpm_start` | float32 | 4 |
| 32 | `shiftlights_rpm_end` | float32 | 4 |
| 36 | `shiftlights_rpm_valid` | boolean | 1 |
| 37 | `vehicle_gear_index` | uint8 | 1 |
| 38 | `vehicle_gear_index_neutral` | uint8 | 1 |
| 39 | `vehicle_gear_index_reverse` | uint8 | 1 |
| 40 | `vehicle_gear_maximum` | uint8 | 1 |
| 41 | `vehicle_speed` | float32 | 4 |
| 45 | `vehicle_transmission_speed` | float32 | 4 |
| 49 | `vehicle_position_x` / `_y` / `_z` | float32 ×3 | 12 |
| 61 | `vehicle_velocity_x` / `_y` / `_z` | float32 ×3 | 12 |
| 73 | `vehicle_acceleration_x` / `_y` / `_z` | float32 ×3 | 12 |
| 85 | `vehicle_left_direction_x` / `_y` / `_z` | float32 ×3 | 12 |
| 97 | `vehicle_forward_direction_x` / `_y` / `_z` | float32 ×3 | 12 |
| 109 | `vehicle_up_direction_x` / `_y` / `_z` | float32 ×3 | 12 |
| 121 | `vehicle_hub_position_bl` / `br` / `fl` / `fr` | float32 ×4 | 16 |
| 137 | `vehicle_hub_velocity_bl` / `br` / `fl` / `fr` | float32 ×4 | 16 |
| 153 | `vehicle_cp_forward_speed_bl` / `br` / `fl` / `fr` | float32 ×4 | 16 |
| 169 | `vehicle_brake_temperature_bl` / `br` / `fl` / `fr` | float32 ×4 | 16 |
| 185 | `vehicle_engine_rpm_max` | float32 | 4 |
| 189 | `vehicle_engine_rpm_idle` | float32 | 4 |
| 193 | `vehicle_engine_rpm_current` | float32 | 4 |
| 197 | `vehicle_throttle` | float32 | 4 |
| 201 | `vehicle_brake` | float32 | 4 |
| 205 | `vehicle_clutch` | float32 | 4 |
| 209 | `vehicle_steering` | float32 | 4 |
| 213 | `vehicle_handbrake` | float32 | 4 |
| 217 | `stage_current_time` | float32 | 4 |
| 221 | `stage_current_distance` | float64 | 8 |
| 229 | `stage_length` | float64 | 8 |
| **237** | end | | |

`struct` format: `<QffQfffBBBBB` + `f`×44 + `fdd` (`f`×44 covers offsets 41–216).

**This packet carries none of the following:**
- `packet_4cc`, so packet types cannot be told apart and there is no magic;
- `location_id` / `route_id` / `vehicle_*_id`, so there is no track or car identity;
- `stage_shakedown`.

### 5.2 `wrc_experimental` (not supported by pitwall; for recognition only)

Sources: [W6] and [W3].
- Header (every packet) = `packet_4cc`, `packet_uid`, `game_total_time`, `game_frame_count` (24 bytes).

| Packet | Body channels (in order) | Total |
|---|---|---:|
| `session_start` | `shiftlights_rpm_start`, `shiftlights_rpm_end`, `vehicle_gear_index_neutral`, `vehicle_gear_index_reverse`, `vehicle_gear_maximum`, `vehicle_engine_rpm_max`, `vehicle_engine_rpm_idle`, `stage_length` (body at offsets 24–50) | **51 B** |
| `session_update` | `game_delta_time` @24, `shiftlights_fraction` @28, `shiftlights_rpm_valid` @32, `vehicle_gear_index` @33, `vehicle_speed` @34 … `vehicle_handbrake` @198 (same order as `wrc` without rpm max/idle), `stage_current_time` @202, `stage_current_distance` @206 | **214 B** |
| `session_pause` / `session_resume` / `session_end` | `stage_current_time` @24, `stage_current_distance` @28 | **36 B** each |

**Why pitwall does not use it.**
- EA describes it as the same data as `wrc`, but sends only what changes, and warns that it is prone to packet loss [W1].
- Despite the name, it is not delta-encoded: each packet has a fixed channel list.
- pitwall needs full state in every update.

### 5.3 Packet identities (`packets.json`, schema 1, data 1) [W4]

| Packet id | fourCC | When sent [W1] |
|---|---|---|
| `session_start` | `SESS` | Once, at the start of the scope |
| `session_update` | `SESU` | Repeatedly, whenever the scope updates (every frame at −1) |
| `session_end` | `SESE` | Once, at the end of the scope |
| `session_pause` | `SESP` | Once, when the scope is paused |
| `session_resume` | `SESR` | Once, when the scope is unpaused |

**Scope.** The only scope is Session, which covers driving through one rally stage [W1]. What counts as start and end around restarts, quits, finishes and replays is **Gate G8 / G11**.

---

## 6. The pitwall structure (recommended configuration)

### 6.1 Design

Design goals:
- Every packet is self-contained (full state), so one lost datagram costs one frame and never the identity.
- Packets are identified by 4CC.
- The `wrc` body is reused byte for byte, so that `wrc` offsets = pitwall offsets − 4.
- No two booleans are adjacent (Gate G1).
- Only data-v2 channels are used, to avoid the 1.8.0 reports [F11].

**Structure file `udp/pitwall.json`** (pitwall-authored; the Connect page shows it for copy-paste):
- `versions`: `{schema: 1, data: 1}`.
- `id`: `"pitwall"`.
- `header.channels`: `["packet_4cc"]`.
- `packets`: the five ids `session_start`, `session_update`, `session_end`, `session_pause` and `session_resume`. **Each** has the same `channels` list:
  - the 59 channels of `wrc` / `session_update` in §5.1 order (`packet_uid` … `stage_length`),
  - then `stage_shakedown`, `vehicle_id`, `vehicle_class_id`, `vehicle_manufacturer_id`, `location_id`, `route_id`.

| Offset | Channel(s) | Type | Size |
|---:|---|---|---:|
| 0 | `packet_4cc` | fourcc | 4 |
| 4–240 | the 59 `wrc` channels, each at its §5.1 offset **+ 4** (e.g. `packet_uid` @4, `vehicle_gear_index` @41, `vehicle_speed` @45, `stage_current_time` @221, `stage_current_distance` @225, `stage_length` @233) | as §5.1 | 237 |
| 241 | `stage_shakedown` | boolean | 1 |
| 242 | `vehicle_id` | uint16 | 2 |
| 244 | `vehicle_class_id` | uint16 | 2 |
| 246 | `vehicle_manufacturer_id` | uint16 | 2 |
| 248 | `location_id` | uint16 | 2 |
| 250 | `route_id` | uint16 | 2 |
| **252** | end | | |

`struct` format: `<4sQffQfffBBBBB` + `f`×44 + `fddBHHHHH`.

### 6.2 `config.json` entries to add

Add these to `udp.packets` and leave the existing entries alone. `<MAC_IP>` is the Mac's LAN IPv4.

| `structure` | `packet` | `ip` | `port` | `frequencyHz` | `bEnabled` |
|---|---|---|---:|---:|---|
| `pitwall` | `session_update` | `<MAC_IP>` | 20790 | 60 | true |
| `pitwall` | `session_start` | `<MAC_IP>` | 20791 | −1 | true |
| `pitwall` | `session_end` | `<MAC_IP>` | 20791 | −1 | true |
| `pitwall` | `session_pause` | `<MAC_IP>` | 20791 | −1 | true |
| `pitwall` | `session_resume` | `<MAC_IP>` | 20791 | −1 | true |

**Why these values:**
- 60 Hz matches pitwall's other 60 Hz sources. EA notes that slower rates are more reliable [W1].
- −1 for event packets sidesteps the ambiguity of 0 meaning disabled (§3.2, G9).

**User steps** (the same pattern SIM Dashboard documents for manual setup [V2]):
1. Launch the game once to the first interactive screen, then quit.
2. Save `pitwall.json` into `udp/`.
3. Add the five entries to `config.json`.
4. Relaunch the game.
5. Check that `log.txt` reports that structure `pitwall` loaded [W10].

---

## 7. Identification and validation

### 7.1 `pitwall` profile (ports 20790/20791)

`can_decode(data)` is cheap and never raises:
- `len(data) == 252`, and
- `data[0:4]` is in {`SESS`,`SESU`,`SESE`,`SESP`,`SESR`}, in the byte order pinned by G2.

`decode` then works through these steps:
1. **Unpack** with the 252-byte `StructDef` (`adapters/structdef.py`, `<`) [P4].
2. **Reject** (`PacketRejected`) on a wrong size or an unknown 4CC.
3. **Check plausibility.** A failure marks `DECODE_WARNING`: the field becomes `None`, but the packet is not dropped.

   | Value | Plausible range |
   |---|---|
   | `stage_length` | finite and in (0, 100 000) m |
   | `stage_current_distance` | finite |
   | throttle, brake, clutch, handbrake | in [−0.01, 1.01] |
   | steering | in [−1.01, 1.01] |
   | `vehicle_gear_maximum` | in 1..12 |
   | `vehicle_gear_index` | ≤ max(gear max, neutral sentinel, reverse sentinel) |
   | rpm | 0 ≤ `rpm_current` ≤ 2 × `rpm_max` |

4. **Use `packet_uid`** to detect drops (gap > 1) and reordering (decrease), counting them in `DecodeStats`.
   - Whether the counter is shared across endpoints is Gate G3.
   - Until G3 is settled, track it per listening port.

### 7.2 `wrc` profile (237 B, no magic)

- `can_decode` accepts `len(data) == 237` **only on a port explicitly assigned to EA WRC**.
- Never auto-detect this profile on an unassigned port. With no magic, a size check alone is too weak for `PacketRouter` auto-detection [P7].
- The same plausibility checks apply.

### 7.3 Rejecting other games on the same port

Users may wrongly reuse 20777:
- None of pitwall's F1 packet sizes (formats 2025 and 2026) is 237 or 252 bytes, and every F1 datagram starts with the 29-byte F1 header [P9].
- Even so, keep EA WRC on its own ports, and keep F1 on 20777.

---

## 8. Mapping to pitwall's model

### 8.1 `CarFrame`

| Field | Source channel(s) | Transform | Status |
|---|---|---|---|
| `game` | — | new enum member `Game.EA_WRC = "ea_wrc"` | Design |
| `t_recv_ns` | — | ingest clock | — |
| `session_time_s` | `stage_current_time` | as is (s) | Design. Freezes in pause? **G8**. `game_total_time` is the alternative. |
| `frame_id` | `game_frame_count` | int | Official |
| `quality` | 4CC state | `PAUSED` between `SESP` and `SESR`; `NOT_RACING` after `SESE` until the next `SESS`/new run | Design; **G8/G11** |
| `throttle`, `brake`, `clutch` | `vehicle_throttle`, `vehicle_brake`, `vehicle_clutch` | as is (0..1). These are **post-assist** values, not raw pedal input. | Official |
| `steering` | `vehicle_steering` | as is. −1 = full left matches pitwall's convention [P3]. Post-assist. | Official |
| handbrake | `vehicle_handbrake` | **No `CarFrame` field.** Add `handbrake: float \| None` (0..1); rally coaching needs it. | Model change |
| `speed_kph` | `vehicle_speed` | × 3.6 (`vehicle_transmission_speed` is the speedo value; keep it as an extra) | Official |
| `gear` | `vehicle_gear_index`, `_neutral`, `_reverse` | if idx == reverse sentinel → −1; if == neutral sentinel → 0; else idx | Sentinels official; forward gears = 1..`vehicle_gear_maximum`? **G4** |
| `rpm`, `max_rpm` | `vehicle_engine_rpm_current`, `vehicle_engine_rpm_max` | as is | Official |
| `drs_open`, `ers_*` | — | `None` | Not provided |
| `pos_x_m`, `pos_y_m`, `pos_z_m` | `vehicle_position_x/y/z` | as is; `AdapterInfo.ground_plane = ("pos_x_m", "pos_z_m")` (Y up) | **G6**. +X is "left", so maps plot mirrored unless x is negated for display. |
| `vel_*_mps` | `vehicle_velocity_x/y/z` | as is | Official (frame: G6) |
| `g_lon`, `g_lat`, `g_vert` | `vehicle_acceleration_*`, the three direction vectors | `g_lon = (a·fwd)/9.80665` (+ accelerating); `g_lat = (a·left)/9.80665` (+ = toward the car's left); `g_vert = (a·up)/9.80665` | **G5**: is `a` world-frame (then project) or already body-frame? Check d(speed)/dt against `a·fwd`. |
| `yaw_rad`, `pitch_rad`, `roll_rad` | direction vectors | `yaw = atan2(fwd_x, fwd_z)`; `pitch = asin(fwd_y)` (nose up +); `roll = atan2(left_y, up_y)` (+ = left side up) | Design (pitwall-defined signs); G6 |
| `lap_number` | — | stage-run counter within the pitwall session (§9) | Design |
| `lap_distance_m` | `stage_current_distance` | as is (float64 m) | Official. Start value, behaviour when reversing, value at the finish: **G7**. |
| `total_distance_m` | — | `None` | — |
| `current_lap_time_ms` | `stage_current_time` | round(× 1000) | Official. Includes penalties or false-start time? **G8** |
| `last_lap_time_ms` | adapter state | time of the last *finished* run (§9.3) | Design; **G8/G12** |
| `sector` | — | `None`: no split channel in data v2 | Not provided |
| `lap_invalid`, `pit_status`, `race_position` | — | `None` | Not provided |
| `brake_temp_c` | `vehicle_brake_temperature_{bl,br,fl,fr}` | `Wheels.from_rl_rr_fl_fr((bl, br, fl, fr))`, °C | Official |
| tyre temperatures, pressures, wear, compound, age | — | `None`. `vehicle_tyre_state_*` (1.8+) has unknown type and meaning (G12). | Not provided |
| `fuel_*` | — | `None` | Not provided |
| `brake_bias_front_pct`, `traction_control`, `abs_active` | — | `None` | Not provided |

**Extras worth keeping** (live state, not persisted per frame):
- `vehicle_transmission_speed`;
- `shiftlights_fraction` / `_rpm_start` / `_rpm_end` / `_rpm_valid` (deterministic shift-point coaching);
- hub positions and velocities (suspension travel and landing detection);
- `vehicle_cp_forward_speed_*`. Contact-patch speed well below body speed under braking indicates lock-up; well above under power indicates wheelspin. This is a deterministic `analysis/` derivation, not an adapter value.

### 8.2 `SessionInfo`

Emit on `SESS`, on any identity change, and otherwise at about 2 Hz.

| Field | Value | Status |
|---|---|---|
| `platform` | `Platform.PC` | Official (PC only) |
| `session_uid` | `f"eawrc:{route_id}:{int(stage_shakedown)}:{game_frame_count of the first SESS on this route}"`. Falls back to the first `SESU` if `SESS` was lost. Deterministic, so replays reproduce it. | Design |
| `track_id` | `f"eawrc:{location_id}:{route_id}"` | Official ids; Design format |
| `track_name` | `"<location name> – <route name>"` from the **user's** `ids.json`, if uploaded; else `None` | [W9]; user-side only (§12) |
| `track_length_m` | `stage_length` | Official |
| `session_type` / `session_type_raw` | `PRACTICE` / `"shakedown"` if `stage_shakedown`, else `UNKNOWN` / `"stage"`. The game's mode (career, championship, time trial, clubs, regularity) is **not** in telemetry. | Official flag; Design mapping |
| `car_id` / `car_name` | `f"eawrc:{vehicle_id}"` / name from the user's `ids.json` | Official ids |
| `total_laps` | `None` (do not fabricate 1) | — |
| `weather` | all `None`: no weather, surface or time-of-day channel | Not provided |
| `track_zones` | `None`: no split or zone table | Not provided |
| `extra` | `vehicle_class_id` (+ name), `vehicle_manufacturer_id` (+ name), `location_id`, `route_id`, `shakedown`, `rpm_idle`, `gear_maximum`, file versions and SHA-256s (§4.2) | Design |

### 8.3 `GameEvent` and `LapCompletion`

| 4CC | Emit | Notes |
|---|---|---|
| `SESS` | `GameEvent(SESSION_STARTED, code="SESS")` + `SessionInfo` | Starts a new stage run (`lap_number += 1` if the route is unchanged; new session if the route changed) |
| `SESU` | `CarFrame` | — |
| `SESP` / `SESR` | `GameEvent(OTHER, code="SESP"/"SESR")` | Toggles `PAUSED` quality |
| `SESE` | `GameEvent(OTHER, code="SESE", payload={"finished": bool})`, plus `LapCompletion` if finished (§9.3) | **Do not** emit `SESSION_ENDED`: one pitwall session holds repeated runs of one route (§9.1), and `SESSION_ENDED` ends the pitwall session [P6] |

---

## 9. Stage model (stage = lap)

### 9.1 Sessions and runs (Design)

- **One pitwall session per route.**
  - A change of `route_id`, `location_id` or `stage_shakedown` ends the session. It also changes `session_uid`, which `SessionManager` treats as a new session [P6].
  - The idle timeout (`session_idle_timeout_s`, 60 s [P8]) also ends it.
- **One lap per stage run.** `lap_number` starts at 1 and increments on each `SESS` for the same route (a restart, or another attempt in time trial).
- **Fallback when `SESS` was lost.** If `stage_current_time` drops by more than 1 s **and** `stage_current_distance` drops back to the start, treat it as a new run and set `DECODE_WARNING` on the first frame.
- **Why runs are laps.** `LapAssembler` already finalises a lap when `lap_number` increments, or immediately when a matching `LapCompletion` arrives [P5]. No new lap-boundary logic is needed beyond emitting these correctly.

### 9.2 Distance and completeness

- **Lap distance and length.** `lap_distance_m = stage_current_distance` and `track_length_m = stage_length`.
- **Completeness.** `LapAssembler` marks a lap `INCOMPLETE` when:
  - it starts more than 60 m in, or
  - it ends short of `track_length_m` minus a tolerance [P5].

  (A lap 1 that starts with under 1 s on the clock is flagged `STANDING_START` instead of incomplete.) Both rules suit stages unchanged, provided G7 confirms that distance starts near 0 and reaches about `stage_length` at the finish.
- **Gaps.** `LapAssembler` flags `INCOMPLETE` on session-time gaps of more than 3 s [P5].
  - With `session_time_s = stage_current_time`, a pause only breaks this if the stage clock keeps running during the pause (G8).
  - If it does keep running, use `game_total_time`, or drop `PAUSED` spans before assembly.
- **Rewinds.** A rewind would show as stage time going backwards. In the stage model that means a new run (§9.1), not a flashback.

### 9.3 Finish and stage time

- **Finished** = `SESE` received with `stage_current_distance ≥ stage_length − tolerance`. The tolerance is set from G7 captures; start with 25 m.
- **Lap time.** `LapCompletion(lap_number, lap_time_ms=round(stage_current_time × 1000) from the SESE packet, valid=None, sector_times_ms=[])`.
- **Caveats** (G8):
  - Whether the stage clock includes penalties, and whether it matches the result screen, is unknown.
  - On 1.8+ installs, `stage_result_time`, `stage_result_time_penalty` and `stage_result_status` may give the official result. They are used only through the `user` profile, after a capture shows their types and meaning (G12).
- **Abandoned runs.** A quit, restart or retirement (`SESE` without reaching the end, or a new `SESS`) gives no `LapCompletion`. The lap is finalised incomplete.

### 9.4 Track model and references

- **The geometry is an open polyline.** A start and a finish, no wrap-around.
  - Anything in `analysis/` that assumes a closed lap (wrap at the line, `end < start` zones) must be gated off for `Game.EA_WRC`. Examples are the circuit track model and `TrackZones` fractions.
- **Reference runs.** Key them on `track_id` (route) **and** `vehicle_class_id`. Rally classes differ hugely (Rally1 against historic cars), so a cross-class reference is misleading.
- **Conditions are unknown.** Weather, surface and time of day are not in telemetry. A reference from different conditions cannot be detected, so state this in coaching facts.
- **No field model.** Telemetry has only the player's car; there is no L0b-style field model [P2].

---

## 10. Track knowledge for EA WRC

| Layer [P2] | EA WRC | Source |
|---|---|---|
| L0a skeleton | `track_id` (location + route), `track_length_m` = `stage_length`. **No** splits, zones or pit data. | [W3] |
| L1 geometry priors | None shipped. Build the stage polyline from the driver's own runs (L3): position against `stage_current_distance`. | Design |
| L2 identity / names | Location and route names come only from the **user's** `ids.json`, read at runtime. In the 1.7.0 copy it lists 18 locations and 216 routes (with distinct route names), plus 84 vehicles, 18 classes and 35 manufacturers. Location names include sponsor trademarks (e.g. the Portugal event name carries a telecoms sponsor). | [W9] |
| L3 learned | Best finished run per route and class is the reference. Speed and brake profiles are distance-indexed, as for circuits. | [P5] |
| Virtual splits | If wanted, pitwall-authored splits (e.g. thirds of `stage_length`), labelled as derived rather than the game's splits. | Design |

**Route identity across versions.** The id space is sparse: the 1.7.0 copy has 18 location ids between 5 and 29, and 216 route ids between 24 and 379 [W9]. Ids are therefore not dense indices. Store the numeric ids, and never hard-code names.

---

## 11. Gates: settle with a pitwall capture before relying on these

**Phase-0 capture plan** (needs a Windows PC with EA WRC):
- Use `pitwall capture --port 20790` and `--port 20791`. This is the capture-only command that [P1] §3.10 lists as a prerequisite.
- Record:
  - a full stage with a pause and a resume;
  - a finish;
  - a restart mid-stage;
  - a quit mid-stage;
  - a short reverse;
  - a shakedown;
  - a replay and some menu time.
- Copy the user's `readme/channels.json`, `packets.json`, `ids.json` and `log.txt` to the Mac (local only).

| Gate | Question | Pass criterion |
|---|---|---|
| G1 | Booleans are 1 byte; no padding | Every datagram is exactly 252 B (pitwall) or 237 B (`wrc`) |
| G2 | 4CC byte order on the wire | First 4 bytes read `SESU` in text order (or reversed); pin it |
| G3 | `packet_uid` semantics | Monotonic per endpoint or shared across endpoints; wrap behaviour |
| G4 | Gear numbering | Forward gears occupy 1..`vehicle_gear_maximum`; sentinel values observed |
| G5 | Acceleration frame | `a·fwd` (world projection) or `a_z` (body) tracks d(`vehicle_speed`)/dt |
| G6 | World axes | Y is vertical (small Δy on flat ground); x/z trace matches the stage map; mirror handling for display |
| G7 | `stage_current_distance` | Value at the start box, monotonicity when reversing or off-route, value at the finish against `stage_length` |
| G8 | Stage clock and events | Clock frozen in pause? Starts at the go signal? Includes penalties? `SESE` on finish / quit / restart? `SESS` on restart? |
| G9 | `frequencyHz` 0 for events | Are event packets sent at 0? (pitwall uses −1 regardless) |
| G10 | LAN target | Packets arrive on the Mac's LAN IPv4 from the gaming PC |
| G11 | Non-driving output | Is telemetry sent during replays, menus, the post-finish cool-down or the countdown? How to tell (e.g. `game_delta_time`, constant `stage_current_time`)? |
| G12 | 1.8+ channels | Names, types and units from the user's `channels.json`. Does adding them stop output [F11]? Meaning of `stage_result_status` and `vehicle_tyre_state_*`. |

**Capability levels:**
- Until the gates pass, `capabilities.py` may claim **SPEC_IMPLEMENTED** for PC (built from the official game-generated spec, synthetic tests only).
- After a recorded capture passes G1–G8, it may claim **RECORDED_VALIDATED**.
- PS5 and Xbox stay **UNSUPPORTED** [V1].

---

## 12. Licences: can pitwall implement from this spec?

| Source | Licence / status | Use in pitwall |
|---|---|---|
| Game-generated `readme.txt`, `channels.json`, `packets.json`, `readme/udp/*.json`, `ids.json` [W1–W9]; EA PDF guide v1.3 [W2] | © 2023 Electronic Arts Inc. legal notice. Written for third-party tools: the readme names structure files from third parties as an intended use [W1]. **No redistribution licence found.** | **Implement from the facts**: channel ids, types, order, sizes. **Do not ship** EA's files or route/location/vehicle name tables. Read the user's own files at runtime; store uploads under `data/ea_wrc/`; never commit them. Same posture as EA's F1 spec in `docs/licences.md`. |
| pitwall `udp/pitwall.json` (§6) and the pinned type table (§5.0) | pitwall-authored: a list of channel identifiers and their types | OK to ship |
| vAzhureRacingHub [C1][C2] | **GPL-3.0** (GitHub licence API) | Read for orientation only (format facts, sizes). **No code copied.** Its copy of EA's files is EA content, not GPL-licensable by vAzhure: do not vendor it. |
| CrewChiefV4 [C4] | MIT | Checked 2026-10-10: has RBR and DiRT modules, **no EA WRC** |
| dr2_logger [C5] | MIT | DiRT Rally 1/2.0 only |
| `timonboehm/wrc_telemetry` (Bitbucket) [C3] | Unknown; repository no longer accessible (API, 2026-10-10) | Not used |
| SIM Dashboard [V2], Simucube [V3] | vendor docs | Facts about configuration only |

**Verdict.**
- **Yes.** pitwall can implement a clean-room, schema-driven decoder from the game's official self-describing files.
- No permissively licensed third-party EA WRC implementation was found to borrow from, and none is needed.
- Review before any commercial release, along with the other EA questions in `docs/research/track-knowledge-sources.md` §7.6 [P2]:
  - how names from `ids.json` are displayed;
  - whether stored telemetry may contain EA game data.

---

## 13. Implementation plan and test vectors

### 13.1 Code shape (ADR-002: adapters are pure functions of bytes, with no I/O) [P4][P7][P10]

- **`src/pitwall/adapters/ea_wrc/schema.py`**
  - Parses `channels.json`, `packets.json` and structure JSON from **text passed in** (UTF-8 or UTF-16 with BOM detection; `ids.json` is UTF-16LE).
  - Checks `versions.schema`.
  - Builds one `StructDef` per packet. The type → format map is: boolean→`B`, uint8→`B`, int8→`b`, uint16→`H`, int16→`h`, uint32→`I`, int32→`i`, uint64→`Q`, int64→`q`, float32→`f`, float64→`d`, fourcc→`4s`.
  - Rejects unknown types and unknown channel ids.
- **`src/pitwall/adapters/ea_wrc/adapter.py`**
  - `EaWrcAdapter(profile)` decodes to a dict of channels, then normalises per §8.
  - Holds the stage-run state machine (§9).
  - Emits `CarFrame`, `SessionInfo`, `GameEvent` and `LapCompletion`.
- **Model**
  - `Game.EA_WRC`.
  - `CarFrame.handbrake` (bump the storage `SCHEMA_VERSION` only if lap channels persist it).
- **Config**
  - `ea_wrc_enabled=False`, `ea_wrc_udp_port=20790`, `ea_wrc_event_port=20791`.
  - Router binds **both** ports to the adapter explicitly. No auto-detect for the `wrc` profile (§7.2).
- **Connect page.** Generates `pitwall.json` and the five `config.json` entries with the Mac's IP filled in. It accepts uploads of `channels.json` (type cross-check, `user` profile) and `ids.json` (names).
- **Analysis.** Gate closed-lap assumptions off for open stages (§9.4). Reference key = route + class.
- **Docs.** Update `capabilities.py`, `docs/status.md`, `docs/architecture.md` and `docs/licences.md` ("Specifications used": EA WRC game-generated telemetry files, read from the user's install).

### 13.2 Tests

All tests below are **synthetic** unless stated (CLAUDE.md evidence tiers).

1. **Doc conformance**, in the style of `tests/unit/test_f1_protocol.py`:
   - parse the §5.0 table of this file (`| # | Channel | Type | Bytes |`);
   - assert that pitwall's pinned type table matches it channel for channel.
2. **Size table.** From the pinned types and the structure lists:

   | Structure / packet | Size |
   |---|---:|
   | `wrc` / `session_update` | 237 B |
   | `wrc_experimental` / `session_start` | 51 B |
   | `wrc_experimental` / `session_update` | 214 B |
   | `wrc_experimental` / pause, resume, end | 36 B each |
   | `pitwall` / every packet | 252 B |

   Plus: every `wrc` offset = pitwall offset − 4.
3. **Round trip.** Pack known values with `StructDef.pack`, decode, and compare every `CarFrame` field per §8.1.
4. **Synthetic vector (pin it).** `pitwall` / `SESU`, 252 bytes, with **4CC written in text order pending G2**:
   - SHA-256 `403ecb2159e97f12bcae3f5eac90661f7f14077d73ac476a86082ab2b2a41ad7`.
   - All values are arbitrary test values, **not** claims about the game (e.g. sentinel neutral = 0, reverse = 10).
   - Input values: `packet_uid` 1000, `game_total_time` 512.25, `game_delta_time` 1/60, `game_frame_count` 30735, shift-lights fraction 0.5 (6000 → 7500 rpm, valid 1), gear index 3 (neutral 0, reverse 10, maximum 6), `vehicle_speed` 25.0 m/s, transmission speed 25.5, position (100.0, 12.5, −250.0), velocity (0, 0, 25), acceleration (0, 0, −9.80665), left (1,0,0), forward (0,0,1), up (0,1,0), brake temps bl 150 / br 151 / fl 300 / fr 301, rpm max 8000 / idle 1000 / current 6750, brake 0.75, steering −0.25, `stage_current_time` 61.5, `stage_current_distance` 1234.5, `stage_length` 10000.0, shakedown 0, `vehicle_id` 4, class 1, manufacturer 1, `location_id` 5, `route_id` 24. All other channels are 0.
   - Expected outputs:

     | Field | Expected |
     |---|---|
     | `speed_kph` | 90.0 |
     | `gear` | 3 |
     | `brake` | 0.75 |
     | `steering` | −0.25 |
     | `rpm` | 6750 |
     | `max_rpm` | 8000 |
     | `lap_distance_m` | 1234.5 |
     | `current_lap_time_ms` | 61500 |
     | `brake_temp_c` (FL, FR, RL, RR) | (300, 301, 150, 151) |
     | `g_lon` | −1.0 (float32: compare with tolerance 1e-6) |
     | `g_lat` | 0.0 |
     | `yaw_rad` | 0.0 |
     | `pitch_rad` | 0.0 |
     | `frame_id` | 30735 |
     | `track_id` | `"eawrc:5:24"` |
     | `track_length_m` | 10000.0 |

   ```
   0000: 53 45 53 55 e8 03 00 00 00 00 00 00 00 10 00 44
   0010: 89 88 88 3c 0f 78 00 00 00 00 00 00 00 00 00 3f
   0020: 00 80 bb 45 00 60 ea 45 01 03 00 0a 06 00 00 c8
   0030: 41 00 00 cc 41 00 00 c8 42 00 00 48 41 00 00 7a
   0040: c3 00 00 00 00 00 00 00 00 00 00 c8 41 00 00 00
   0050: 00 00 00 00 00 0a e8 1c c1 00 00 80 3f 00 00 00
   0060: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 80
   0070: 3f 00 00 00 00 00 00 80 3f 00 00 00 00 00 00 00
   0080: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
   0090: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
   00a0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 16
   00b0: 43 00 00 17 43 00 00 96 43 00 80 96 43 00 00 fa
   00c0: 45 00 00 7a 44 00 f0 d2 45 00 00 00 00 00 00 40
   00d0: 3f 00 00 00 00 00 00 80 be 00 00 00 00 00 00 76
   00e0: 42 00 00 00 00 00 4a 93 40 00 00 00 00 00 88 c3
   00f0: 40 00 04 00 01 00 01 00 05 00 18 00
   ```

   **Derived `wrc` vector:** bytes `[4:241]` of this vector form a valid 237-byte `wrc` packet with the same values, minus the 4CC and identity.
5. **Negative vectors.**
   - 251 / 253 / 236 / 238 bytes → `PacketRejected`.
   - 4CC `XXXX` → rejected.
   - NaN `stage_length` → `track_length_m` is `None` with `DECODE_WARNING`.
   - gear = reverse sentinel → −1; = neutral sentinel → 0.
   - Steering 1.5 → `None` with a warning.
   - A `packet_uid` gap → drop counter increments.
6. **Stage state machine**, on synthetic streams:
   - `SESS`, `SESU`…, `SESE` at full distance → one complete lap with a time;
   - restart (`SESS` mid-stage) → the first lap is incomplete and the second starts;
   - route change → new `session_uid`;
   - `SESP`/`SESR` → frames flagged `PAUSED`;
   - lost `SESS` → fallback run detection.

   Synthetic streams must carry `SYNTHETIC_SESSION_UID` handling, or a `synthetic:` track namespace, as for other games.
7. **Recorded tier** (after Phase 0): the user's `.pwcap` files under `tests/fixtures/recorded/ea_wrc/`.
   - Record the SHA-256 and `versions` of the user's `channels.json` beside them, not the file itself.
   - Tests that need the real `channels.json` look for a local, git-ignored copy and **skip** if it is absent.

---

## 14. Sources

Accessed 2026-10-10 unless stated. The **user's own** files under `Documents/My Games/WRC/telemetry/` are authoritative. The URLs below are the third-party copy that was read.

**Game-generated official files** (copy in vAzhureRacingHub @ `1881af7be8dbdfe8f97873ddac7e4fb01191a98a`, uploaded 2024-04-24; EA content, © 2023 Electronic Arts)
- [W1] `readme/readme.txt`: https://raw.githubusercontent.com/vazhure/vAzhureRacingHub/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/WRC2023/telemetry/readme/readme.txt
- [W2] EA SPORTS WRC - UDP Telemetry Guide (v1.3), PDF, 6 pages, Google Docs export, SHA-256 `1ce5eadb4da02a1a86a4d77cc5f3cfc9a5635849f2911a668c0388c364ba0a50`: https://github.com/vazhure/vAzhureRacingHub/blob/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/WRC2023/doc/EA%20SPORTS%20WRC%20-%20UDP%20Telemetry%20Guide%20(v1.3).pdf
- [W3] `readme/channels.json` (schema 1, data 2, 66 channels; SHA-256 `614d60dc8be6d0603b2f52c8a3edbe1fccdf85637bef0b304cc125143ff7cc1b`): https://raw.githubusercontent.com/vazhure/vAzhureRacingHub/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/WRC2023/telemetry/readme/channels.json
- [W4] `readme/packets.json`: https://raw.githubusercontent.com/vazhure/vAzhureRacingHub/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/WRC2023/telemetry/readme/packets.json
- [W5] `readme/udp/wrc.json` (SHA-256 `624193b1b4257f02e5285c6568849a67391d2c449074f864e1815fcd01128f2e`): https://raw.githubusercontent.com/vazhure/vAzhureRacingHub/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/WRC2023/telemetry/readme/udp/wrc.json
- [W6] `readme/udp/wrc_experimental.json` (SHA-256 `49255e1fef98bd5daa2f12975cd6cbe679e2b746d8a28ea30edc402f2ca5d237`): https://raw.githubusercontent.com/vazhure/vAzhureRacingHub/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/WRC2023/telemetry/readme/udp/wrc_experimental.json
- [W7] `udp/custom1.json`: https://raw.githubusercontent.com/vazhure/vAzhureRacingHub/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/WRC2023/telemetry/udp/custom1.json
- [W8] `config.json` (schema 2): https://raw.githubusercontent.com/vazhure/vAzhureRacingHub/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/WRC2023/telemetry/config.json
- [W9] `readme/ids.json` (UTF-16LE with BOM; game version 1.7.0): https://raw.githubusercontent.com/vazhure/vAzhureRacingHub/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/WRC2023/telemetry/readme/ids.json
- [W10] `log.txt`: https://raw.githubusercontent.com/vazhure/vAzhureRacingHub/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/WRC2023/telemetry/log.txt

**Official statements and news**
- [O1] EA Forums, "EA SPORTS™ WRC - Development Update" (EA_Groguet, Community Manager, 2025-04-30): https://forums.ea.com/blog/wrc-game-info-hub-en/ea-sports%E2%84%A2-wrc---development-update/12142087
- [N8] OverTake, EA SPORTS WRC Update 1.3 patch notes (last edited 2023-11-08; read in a browser, 403 to scripted fetch): https://www.overtake.gg/news/ea-sports-wrc-update-1-3-brings-performance-fixes.1481/page/ea-sports-wrc-update-1-3-patch-notes.271/

**Forum**
- [F11] EA Forums, "Broken UDP telemetry fields in version 1.8.0" (report 2024-04-30; EA_Groguet reply 2024-05-16, marked as solution; read in a browser): https://forums.ea.com/discussions/wrc-technical-issues-en/broken-udp-telemetry-fields-in-version-1-8-0/8405061

**Vendors**
- [V1] SIM Dashboard, Unsupported Games (EA SPORTS WRC: no telemetry interface on console; supported on PC): http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Unsupported_Games
- [V2] SIM Dashboard, EA SPORTS WRC (PC) manual setup (own structure file + `session_update` entry, port 20432, 20 Hz): http://www.stryder-it.de/simdashboard/help/en/For_PC_Gamers/Game_Configuration/EA_SPORTS_WRC
- [V3] Simucube, EA Sports WRC (Tuner patches `config.json`, own packet type, port 27878): https://docs.simucube.com/TunerSoftware/games/EA%20Sports%20WRC.html
- [V20], [V57]: SimHub supported games and oesimracing console guide, as cited in [P1] §12 (not re-fetched)

**Code**
- [C1] vazhure/vAzhureRacingHub (GPL-3.0 per https://api.github.com/repos/vazhure/vAzhureRacingHub; telemetry files commit `554f5ee14b`, 2024-04-24): https://github.com/vazhure/vAzhureRacingHub
- [C2] vAzhureRacingHub `Codemasters/UDPClient.cs` (decodes EA WRC only when the length equals the struct size) and `Codemasters/Dirt4UDPPacket.cs` (`Pack = 1` struct `WRC_DATA`: 59 fields, 237 bytes, 1-byte `shiftlights_rpm_valid`). The app is released (latest v1.0.098, 2026-07-03, per the GitHub releases API). GPL-3.0, orientation only, no code copied: https://github.com/vazhure/vAzhureRacingHub/blob/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/UDPClient.cs , https://github.com/vazhure/vAzhureRacingHub/blob/1881af7be8dbdfe8f97873ddac7e4fb01191a98a/Codemasters/Dirt4UDPPacket.cs
- [C3] timonboehm/wrc_telemetry `support1.8.0` (cited in [F11]; inaccessible via the Bitbucket API on 2026-10-10): https://bitbucket.org/timonboehm/wrc_telemetry/src/support1.8.0/
- [C4] CrewChiefV4 (MIT, "Copyright (c) 2019-2024 Britton IT Ltd"; no EA WRC module on `main`): https://gitlab.com/mr_belowski/CrewChiefV4
- [C5] ErlerPhilipp/dr2_logger (MIT; DiRT Rally only): https://github.com/ErlerPhilipp/dr2_logger

**pitwall**
- [P1] `docs/research/game-compatibility.md` (§1.1, §2, §3.7, §3.10, §12)
- [P2] `docs/research/track-knowledge-sources.md` (§2 layers, §7 licensing, §7.6 counsel questions)
- [P3] `src/pitwall/model/telemetry.py` (`CarFrame`, `Wheels.from_rl_rr_fl_fr`, `SessionInfo`, `Game`)
- [P4] `src/pitwall/adapters/structdef.py`, `src/pitwall/adapters/base.py`
- [P5] `src/pitwall/analysis/laps.py` (`LapAssembler`: `EDGE_TOLERANCE_M` 60 m, 3 s gap rule, `feed_completion`)
- [P6] `src/pitwall/core/session.py` (session-uid change and `SESSION_ENDED` end the session)
- [P7] `src/pitwall/ingest/router.py` (per-port adapter auto-detection via `can_decode`)
- [P8] `src/pitwall/config.py` (`f1_udp_port` 20777, `session_idle_timeout_s` 60)
- [P10] `docs/decisions/README.md` (ADR-002: adapters are pure functions of bytes)
- [P9] `src/pitwall/adapters/f1/packets.py` (`PACKET_SIZES`, `SPEC_PUBLISHED_SIZES`, `LAYOUT_2025`/`LAYOUT_2026`: 28 distinct sizes, none 237 or 252, checked 2026-10-10) and `tests/unit/test_f1_protocol.py` (29-byte header)
