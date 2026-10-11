# Project Motor Racing UDP telemetry (`pmr-udp`): implementation spec

Research date: 2026-10-10. Family: `pmr-udp`. Games: Project Motor Racing (PMR) on PS5 (v2.3+), Xbox Series X|S (v2.3+) and PC.

**Status: GATED.** Do not ship a decoder until the gates in §14 pass. This document is the reference that pitwall's own decoder will be written from. **No code is copied here.** Layouts are given as tables and procedures in prose.

Read with: `docs/research/game-compatibility.md` §3.4 (platform evidence, ranking), §3.10 (ingest prerequisites), §10 item 1 (open questions); `docs/research/track-knowledge-sources.md` (layers L0a/L0b/L3).

---

## 0. Summary

- **Official spec: none public.** Straight4 has published no byte-level document on its website [O1][O2][O3][O4].
  - The MIT community SDK says the PC game comes with an official header `UDPTelemetryProtocol.h`, a `docs/packet_layout_example.txt` and a `SimpleUDPServer` sample [C1-BRE]. It does not say where they ship.
  - I could not fetch any of them, and their licence is unknown. On one point (the order of the first two fields of packet type 1), C1 reports that the header disagrees with the wire.
- **Transport.** One-way UDP push from the game to a configured host and port (default **7576**).
  - There is no handshake and no subscription.
  - Unicast works. On PC, multicast (group 224.0.0.150) also exists.
  - On a console, set **UDP Host = the Mac's LAN IP**. The Mac receives directly; no relay is needed [V27][C1-CONN][V21].
- **Format.**
  - Little-endian, packed, no magic, no checksum.
  - Header: `u8 packet_type`, `u16 packet_version`.
  - Strings and arrays carry a `u8` length prefix, so every packet type has a variable length.
  - Four types: 0 RaceInfo (v1), 1 ParticipantRaceState (v1, **one participant per datagram**), 2 ParticipantVehicleTelemetry (v2), 3 SessionStopped [C1][C2][C3].
- **Layout confidence.**
  - Types 0 and 1: three independently written decoders agree field-for-field [C1][C2][C3].
  - Type 2: two decoders agree [C1][C3].
  - **Units are mostly the community's naming, not measurements.** C1 explicitly marks some units "best guess" or "not empirically confirmed".
- **Platform verdicts.**
  - PC: **Confirmed** (works).
  - PS5: **Likely**. The setting is official [O1], but there is no first-hand stream report.
  - Xbox Series: **Likely**, on the same official wording. No third-party Xbox evidence exists.
- **Track knowledge is rich.**
  - RaceInfo carries track and layout strings plus `layout_length` (metres).
  - Every participant's `lap_progress_fraction` and sector state arrive on the wire.
  - Lap distance = fraction × layout length.
- **Missing from v1.** Session clock, frame counter, last-lap-time field, lap validity, tyre compound, tyre wear and damage (§10).

## Confidence legend

| Tag | Meaning |
|---|---|
| **Confirmed (3)** | Three independent decoders read it identically [C1][C2][C3] |
| **Corroborated (2)** | Two independent decoders agree [C1][C3] |
| **Single** | One source only |
| **Unconfirmed** | Explicitly flagged as a guess by its source, or a unit implied only by a variable name |
| **Unknown** | No source says. Settle with a pitwall capture (§14) |

"Independent" means separately written code with different authors, licences and languages: C# MIT [C1], JavaScript proprietary [C2], C# CC BY-NC-SA [C3]. They may still share an upstream: the official header and SimHub's reader. C2 says it follows "SimHub GSIReader".

---

## 1. Sources and what each may be used for

| Tag | Source | Date / version | Licence | Use in pitwall |
|---|---|---|---|---|
| O1 | PMR "Version 2.3" notes | 2026-09-23 | official page | Console UDP enabled: CONSOLES section "Enabled UDP telemetry settings on console platforms" (re-fetched 2026-10-10) |
| O2 | PMR FAQ | 2025-11-25 | official page | "PMR does have UDP telemetry. This feature can be enabled via Settings > Preferences." |
| O3 | PMR "Update 2.0.0.2" | 2026-04-09 | official page | "Corrected UDP telemetry data for sector times and best sectors." |
| O4 | PMR "Version 2.3.0.1" hotfix | 2026-10-05 | official page | No UDP mention. Sections: What's new, AUDIO, INPUT, ONLINE |
| C1 | devology-uk/sim-racing-sdk, `SimRacingSdk.Pmr.Udp` / `.Monitor` / `.Core`, commit `c23c291140a5a5e8d0efbd80b733d4ad9bf96092` | PMR code 2026-09-13 to 2026-09-25 | **MIT**, "Copyright (c) 2024 Playology" | **Primary layout reference.** Facts may be used, with attribution in `docs/licences.md`. pitwall still writes its own decoder. |
| C2 | Ricozwar/pmr-results-helper, commit `9dceb25ad9ade4c9b98358767971e0809d498b5f` | created 2026-09-22 | **Proprietary**, "All rights reserved" | **Facts only. Never copy.** Corroborates types 0 and 1, plus behaviour notes. |
| C3 | SeriousOldMan/Simulator-Controller, `Sources/Special/PMR UDP Connector/`, commit `cb88003d999c4c01dfd37d296daf0b493cda82d1` | PMR files 2025-12-08 to 2025-12-15 | **CC BY-NC-SA 4.0** ("Most parts") | **Facts only. Never copy** (NC and SA are incompatible with pitwall). Corroborates types 0, 1 and 2. |
| V27 | SIMRIG, PMR (Console) setup | undated (© 2018–2026) | vendor doc | Console settings and values |
| V28 | SIMRIG, PMR (PC) setup | undated | vendor doc | PC settings; 127.0.0.1 tip |
| V13 | SIM Dashboard, PMR (PC) | undated | vendor doc | Settings, "Direct" vs "Multicast", troubleshooting |
| V21 | SimHub changelog | 9.10.2 (2025-10-13) to 9.12.9 (2026-09-30) | vendor doc | Multicast and unicast history; console instructions updated |
| N15 | Traxion | 2026-01-17 | press | Consoles rolled back 1.5.0.5 → 1.5.0.4 while PC kept 1.5.0.5 |
| N16 | Rankouniverse guide | 2026-09-23 | press | "Version 2.3 expands UDP telemetry support to consoles." No technical detail |

C1 file-level citations used below, all at commit `c23c291` (prefix `https://github.com/devology-uk/sim-racing-sdk/blob/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/src/`):

- **C1-BRE**: `SimRacingSdk.Pmr.Udp/Extensions/BinaryReaderExtensions.cs` (wire order)
- **C1-MH**: `SimRacingSdk.Pmr.Udp/PmrUdpMessageHandler.cs` (dispatch, expected versions)
- **C1-CONN**: `SimRacingSdk.Pmr.Udp/PmrUdpConnection.cs` (port, multicast, timeouts)
- **C1-MSG**: `SimRacingSdk.Pmr.Udp/Messages/*.cs` (unit names and "not confirmed" notes)
- **C1-ENUM**: `SimRacingSdk.Pmr.Udp/Enums/*.cs`
- **C1-CFG**: `SimRacingSdk.Pmr.Core/PmrLocalConfigProvider.cs` (PC `settings.xml` keys, frequency options)
- **C1-MON**: `SimRacingSdk.Pmr.Monitor/PmrMonitor.cs` and `Messages/PmrMonitorLap.cs` (lap logic, rig notes)

C1 commit history for the PMR UDP folder:

| Commit | Date | Message |
|---|---|---|
| `cb74e3d645` | 2026-09-13 | "Added initial support for project motor racing udp monitoring" |
| `d270a0f91f` | 2026-09-14 | "Converted string telemetry fields to numeric for pmr" |
| `db61b6396d` | 2026-09-21 | "Switched reading order of vehicleid and isplayer fields to resolve lack of ability to match player telemetry" |
| `0ba58395ed` | 2026-09-25 | "Fixed incorrect naming of steering angle field" |

**Units were added to C1's field names later.** In commit `d270a0f91f` (2026-09-14), names changed from unitless (`Pressure`, `Brake`, `LayoutLength`) to unit-bearing (`PressureKpa`, `BrakeTemperatureCelsius`, `LayoutLengthMeters`). Treat a C1 unit as a claim, not a measurement, unless C1 says it was cross-checked.

---

## 2. Platforms and per-game differences

| Platform | Evidence | Verdict |
|---|---|---|
| PC (Steam) | Official FAQ [O2]. SimHub support since closed beta 9.10.2, 2025-10-13 [V21]. Vendor setup pages [V13][V28]. Three community decoders [C1][C2][C3]. C1 cites rig captures on 2026-09-13 and 2026-09-16 [C1-MSG][C1-MON]. | **Confirmed (works on PC)** |
| PS5 | Official: v2.3 "Enabled UDP telemetry settings on console platforms" [O1]. SIMRIG publishes a console setup page [V27]. SimHub updated its PMR setup instructions on 2026-09-30 without saying what changed [V21]. **No first-hand report of a stream from a PS5.** | **Likely** |
| Xbox Series X\|S | Same official wording, "console platforms" [O1]. SIMRIG's console page names no console [V27]. No third-party Xbox report. | **Likely** |

**Known or possible differences:**

- **Unicast and multicast.**
  - On PC, the output was multicast-only at first. SimHub 9.10.13 (2025-11-26) added "telemetry forward option (now that unicast is available)". It also made auto-configuration force multicast off to prevent "network-wide spam" [V21].
  - C3 (December 2025) and C1 define the multicast group 224.0.0.150; C3 joins it by default [C3][C1-CONN].
  - Whether a console offers or defaults to multicast is **unknown**.
- **Build lag.** Consoles have run older builds than PC: 1.5.0.4 vs 1.5.0.5 in January 2026 [N15]. Packet versions on console may differ from PC. Always dispatch on version (§6).
- **Sector times.** These were wrong before 2.0.0.2 (2026-04-09) [O3]. Console UDP arrived only with 2.3 (2026-09-23) [O1], so a current console build should include the fix. Verify with a capture.
- **Same game and data model.** Nothing indicates a different wire format per platform. This is unverified until a PS5 capture is compared field by field with C1's PC-derived layout.

---

## 3. Transport

| Item | Value | Confidence / source |
|---|---|---|
| Direction | Game → receiver only. The receiver never sends to the game. | Confirmed (3): all decoders only bind and receive [C1-CONN][C2][C3] |
| Handshake / subscription | **None.** No message to send; no bytes to specify. The stream is enabled in game settings. | Confirmed (3) [C1-CONN][C2][C3][O2] |
| Settings (UI) | Settings > Preferences: **UDP Enabled** (On), **UDP Frequency** (default 60), **UDP Port** (default 7576), **UDP Host** | [O2][V27][V28][V13] |
| Console values | UDP Enabled On; Frequency 60; Port 7576; **Host = receiving machine's IP** (SIMRIG example "192.168.2.111") | [V27] |
| PC values (vendors) | Host 127.0.0.1. SIMRIG: "otherwise you might experience performance and network issues". SIM Dashboard: "Direct (recommended)" or "Multicast". | [V28][V13] |
| Default port | 7576 | [C1-CONN `DefaultPort = 7576`][V27][V28][V13] |
| Multicast group (PC) | 224.0.0.150. A link-local block, TTL 1, not routed. | [C1-CONN `DefaultMulticastGroup`][C3] |
| UDP Frequency options | 10, 20, 30, 60 Hz. C1 confirmed this on PC by toggling the in-game option and reading the saved index. | Single [C1-CFG] |
| PC `settings.xml` keys | `SettingsPreferencesUDPEnabled` (2 = on), `SettingsPreferencesUDPFrequency` (1-based index into 10/20/30/60), `SettingsPreferencesUDPHost`, `SettingsPreferencesUDPPort`, in `Documents\My Games\ProjectMotorRacing\savegame1\settings.xml` | Single [C1-CFG][C1 `PmrPathProvider.cs`]. PC only, for reference. |
| Per-type rates | **Unknown.** Whether RaceInfo and per-participant race states also follow UDP Frequency is unknown. | Measure (§14.2) |
| Game's source port | Unknown; irrelevant. Route by the Mac's listening port. | — |
| Datagram size | Variable. Type 2 with 4 wheels is about 960–1000 bytes (formula in §7.4), below a 1472-byte UDP payload at a 1500 MTU, so no IP fragmentation is expected. Type 0 could exceed 1472 only if the strings total more than about 1440 bytes. | Computed from the layout |
| Stream stall | SIM Dashboard: if no data, set UDP Enabled Off, save, then On, save (PC) [V13]. C1 warns after 5 s without packets [C1-CONN]. | Community |
| One destination | The game sends to one Host:Port. Other consumers (SimHub, motion) need forwarding: SimHub has a forward option [V21] and SIM Dashboard has "Forward UDP Telemetry" [V13]. Only one process per host can bind a port [V13]. | Community |
| Ports used by other tools | C2 defaults to **7580** and advises "Avoid 7576 (often used by wheel software)" on Windows [C2 README FIRST]. Irrelevant on the Mac; use the in-game value. | Single |
| UI pitfall | "Don't use the backspace key in these fields": in game version 1.5.0.0, backspace resets the screen's settings (PC) [V13]. Console behaviour is unknown. | Single |

**pitwall transport rules:**

1. Bind UDP `0.0.0.0:7576` with a listener dedicated to PMR, following the existing `UdpListener` pattern (`src/pitwall/ingest/sources.py`).
   - Route by port. **Do not auto-detect PMR on a shared port.** The 3-byte header (type 0–3 plus a small u16) is too weak a signature.
   - `PacketRouter._adapter_for` tries `can_decode` on unknown ports, so PMR's `can_decode` must be strict anyway (§6).
2. On console: set Host = the Mac's **LAN** IPv4 address, not its Tailscale (100.x) address, which the console cannot reach.
   - Give the Mac a DHCP reservation so the Host value stays valid.
   - The macOS application firewall must allow inbound UDP for the Python process.
3. Multicast join is optional and PC-only (224.0.0.150, `IP_ADD_MEMBERSHIP`). Not needed for the PS5 plan.
4. No send path is needed. GT7's heartbeat (`ingest/gt7_heartbeat.py`) has no PMR equivalent.

---

## 4. Wire conventions

| Convention | Value | Confidence / source |
|---|---|---|
| Endianness | **Little-endian** for all multi-byte fields. C2 uses explicit `readUInt16LE`/`readInt32LE`/`readFloatLE`; C1 uses .NET `BinaryReader` (always LE); C3 uses `BitConverter` on x86 (LE). | Confirmed (3) on PC. Console unverified (PS5 and Xbox are x86-64, so LE is expected). |
| Packing | No padding or alignment. Fields are read back-to-back. | Confirmed (3) |
| `u8` / `bool` | 1 byte. C1 and C3 treat bool as `!= 0`; C2 as `=== 1`. Use `!= 0`, and log any value other than 0 or 1. | Confirmed (3) |
| `u16`, `i32`, `u32` | 2 / 4 / 4 bytes | Confirmed (3) |
| `f32` | IEEE-754 binary32 | Confirmed (3) |
| `vec3` | 3 × f32 in order x, y, z | Corroborated (2) [C1][C3] |
| `quat` | 4 × f32 in order x, y, z, w | Corroborated (2) [C1][C3]. **The x,y,z,w order is unverified**: a header could use w-first. Check with \|q\| = 1 and yaw tracking heading (§14.2). |
| `lpstr` | `u8 len` then `len` bytes of UTF-8, no terminator. Max 255 bytes. len may be 0. | Confirmed (3) |
| `lpf32[]` | `u8 count` then `count` × f32 | Confirmed (3) |
| Magic / checksum / sequence | **None** | Confirmed (3) |
| Timestamp / frame counter | **None in any packet type** | Confirmed (3) for types 0 and 1; (2) for type 2 |

---

## 5. Packet catalogue

| Type (byte 0) | Name | Version expected | Count per datagram | Sources |
|---|---|---|---|---|
| 0 | RaceInfo | 1 | 1 session description | [C1-MH `ExpectedRaceInfoVersion = 1`][C1-ENUM][C2][C3] |
| 1 | ParticipantRaceState | 1 | **1 participant**. The field is covered by a series of datagrams, one per car. | [C1-MH = 1][C2][C3] |
| 2 | ParticipantVehicleTelemetry | **2** (so a v1 existed or exists) | 1 vehicle | [C1-MH `ExpectedVehicleTelemetryVersion = 2`]. C3 does not check the version. |
| 3 | SessionStopped | not checked by any decoder | 0 (header only) | [C1-MH][C2][C3] |

**Type 1 corrects the shorthand "carries all cars".** No count field exists. Every decoder reads exactly one participant per type-1 datagram [C1-BRE][C2][C3]. RaceInfo's `num_participants` gives the field size.

Whether type-2 telemetry is sent for **every** car or only the player is **unknown** (§14.2). C3 stores telemetry per `vehicle_id` [C3 `PMRUDPReceiver.cs`], which suggests more than one.

---

## 6. Identification and validation

No magic exists. Validate structurally:

1. **Route by port**: 7576, or the user's configured PMR port.
2. **Check the header.**
   - `len >= 3`.
   - `type = data[0]` must be in {0, 1, 2, 3}.
   - `version = u16le(data[1:3])`.
   - Accept only the (type, version) pairs in §5: (0,1), (1,1), (2,2), and (3, any).
   - An unknown pair is counted as **ignored** (not an error) and its version is logged once. A new version is expected sooner or later (§7.7).
3. **Parse fully with bounds checks.** Every read checks remaining length. A truncated datagram raises `PacketRejected`.
4. **Exact consumption.**
   - After parsing, the cursor must equal `len(data)`.
   - None of the three community decoders checks this, so whether the game pads or appends bytes is **unknown**.
   - Until a capture shows exact consumption on PS5, treat trailing bytes as `DECODE_WARNING` (decode, flag and count) rather than rejecting.
   - Once captures confirm exact consumption, make trailing bytes a rejection.
5. **Plausibility (cheap).**
   - All strings decode as UTF-8.
   - RaceInfo: `state ∈ {0,1,2}`; `0 < layout_length < 30000`. The longest C1 layout is 25 378 m (the Nordschleife 24h layout); see `data/pmr/tracks` in C1.
   - Type 1: `0 ≤ lap_progress_fraction ≤ 1` is not guaranteed. C3 clamps it, which suggests values outside the range occur. Record raw values; do not clamp in the adapter.
   - Type 2: `wheel_count == constant.number_of_wheels`, an internal cross-check available in every packet. Every f32 is finite.
6. **`can_decode`** (auto-detection on an unrouted port) must run steps 2 to 4 completely and return True only on exact consumption. Otherwise return False. Never raise.

Size formulas, with Σlen = the sum of the string byte lengths in the packet:

| Type | Size (bytes) |
|---|---|
| 0 RaceInfo v1 | `32 + Σlen(6 strings)` |
| 1 ParticipantRaceState v1 | `45 + Σlen(4 strings) + 4·(n_cur_sectors + n_best_sectors)` |
| 2 ParticipantVehicleTelemetry v2 | `408 + 124·W + 8·G + 4·N` (W wheels, G gear entries, N suspension loads) |
| 3 SessionStopped | 3, assuming no payload. Unverified: no decoder reads past the version. |

---

## 7. Packet layouts

Offsets are bytes from the start of the UDP payload. After the first `lpstr` all offsets are cursor-relative; base names (S, P, Q, R, C, D, E, I, T, Gn, K) are defined in each table. Field names below are pitwall's own (snake_case). C1/C3 names are given where they carry a unit claim.

### 7.1 Common header (all types)

| Offset | Type | Field | Notes | Confidence |
|---|---|---|---|---|
| 0 | u8 | `packet_type` | 0–3 (§5) | Confirmed (3) |
| 1 | u16 | `packet_version` | per type (§5) | Confirmed (3) |

### 7.2 Type 0: RaceInfo (version 1)

Sources: [C1-BRE `ReadPmrRaceInfo`][C1-MSG `PmrRaceInfo.cs`][C2 `src/udp-parser.js`][C3 `PMRUDPProtocol.cs` `UDPRaceInfo`]. Order: Confirmed (3).

| Offset | Type | Field | Unit / meaning | Unit confidence |
|---|---|---|---|---|
| 0 | u8 | `packet_type` = 0 | | |
| 1 | u16 | `packet_version` = 1 | | |
| 3 | lpstr | `track` | track name. Format (display name vs internal id such as `ID_spielberg`) **unknown** | — |
| + | lpstr | `layout` | layout name. Format unknown | — |
| + | lpstr | `season` | | — |
| + | lpstr | `weather` | vocabulary unknown | — |
| + | lpstr | `session` | session label. Vocabulary unknown; possibly localised (§11) | — |
| + | lpstr | `game_mode` | vocabulary unknown | — |
| S+0 | f32 | `layout_length` | **metres** (C1 `LayoutLengthMeters`) | Unconfirmed (name only). Cross-check against layout lengths in C1's game-data table (e.g. Spielberg GP 4318 m). |
| S+4 | f32 | `duration` | C1: "Seconds is a best guess, not empirically confirmed … a 2026-09-13 rig capture showed 300 for a race weekend's race session". May be laps when `is_laps` = 1. | **Unconfirmed** (flagged by C1) |
| S+8 | f32 | `overtime` | seconds? (C1 `OvertimeSeconds`) | Unconfirmed |
| S+12 | f32 | `ambient_temperature` | °C? (C1 `AmbientTemperatureCelsius`) | Unconfirmed |
| S+16 | f32 | `track_temperature` | °C? | Unconfirmed |
| S+20 | u8 | `is_laps` | bool: race length in laps? | Semantics unconfirmed |
| S+21 | u8 | `state` | enum RaceSessionState (§7.6) | Confirmed (3) |
| S+22 | u8 | `num_participants` | count | Confirmed (3) |
| S+23 | — | end | size = S + 23, where S = 3 + Σ(1 + len_i) over the 6 strings = 9 + Σlen; size = 32 + Σlen | |

### 7.3 Type 1: ParticipantRaceState (version 1), one participant per datagram

Sources: [C1-BRE `ReadPmrParticipantRaceState`][C1-MSG `PmrParticipantRaceState.cs`][C2][C3 `UDPParticipantRaceState`]. Order: Confirmed (3).

**Field-order note (bytes 3–7).** C1 reports that "The header (UDPTelemetryProtocol.h) and docs/packet_layout_example.txt say isPlayer comes first, but the wire order is vehicleId then isPlayer, as the bundled SimpleUDPServer sample reads it" [C1-BRE, commit `db61b6396d`, 2026-09-21].

- C2 and C3 both read `vehicle_id` first.
- So the wire order is Confirmed (3), and **the official header is wrong on this point**, if C1's account is right. This is one reason a header alone would not replace captures.

| Offset | Type | Field | Unit / meaning | Unit confidence |
|---|---|---|---|---|
| 0 | u8 | `packet_type` = 1 | | |
| 1 | u16 | `packet_version` = 1 | | |
| 3 | i32 | `vehicle_id` | joins with type-2 `vehicle_id` | Confirmed (3) |
| 7 | u8 | `is_player` | bool | Confirmed (3) as a layout. Semantics: see §11 (stale C1 comments) |
| 8 | lpstr | `vehicle_name` | | |
| + | lpstr | `driver_name` | may be another real person's name online (§12) | |
| + | lpstr | `livery_id` | | |
| + | lpstr | `vehicle_class` | | |
| P+0 | i32 | `race_position` | 1-based? | Base unknown |
| P+4 | i32 | `current_lap` | 0- or 1-based? | Base unknown |
| P+8 | f32 | `current_lap_time` | seconds (C1 `CurrentLapTimeSeconds`) | Unconfirmed; plausible |
| P+12 | f32 | `best_lap_time` | seconds | Unconfirmed; the value when no lap is set (0, negative, large) is unknown |
| P+16 | f32 | `lap_progress_fraction` | 0..1 of the lap (C1 `LapProgressFraction`) | Range not guaranteed (§6 step 5) |
| P+20 | i32 | `current_sector` | 0- or 1-based? | Base unknown |
| P+24 | u8 | `n_cur` | count of current-lap sector times | Confirmed (3) |
| P+25 | f32 × n_cur | `current_sector_times` | seconds | Unconfirmed. Fixed in 2.0.0.2 [O3] |
| Q = P+25+4·n_cur | u8 | `n_best` | count | Confirmed (3) |
| Q+1 | f32 × n_best | `best_sector_times` | seconds | Unconfirmed. Fixed in 2.0.0.2 [O3] |
| R = Q+1+4·n_best | u8 | `in_pits` | bool. Pit lane or pit box? | Semantics unknown |
| R+1 | u8 | `session_finished` | bool | |
| R+2 | u8 | `disqualified` | bool | |
| R+3 | u32 | `flags` | bitfield RaceFlags (§7.6) | Layout Confirmed (3); bit meanings Single [C1-ENUM] |
| R+7 | — | end | P = 12 + Σlen(4 strings); size = 45 + Σlen + 4·(n_cur + n_best) | |

### 7.4 Type 2: ParticipantVehicleTelemetry (version 2)

Sources: [C1-BRE `ReadPmrVehicleTelemetry` and sub-readers][C1-MSG][C3 `UDPVehicleTelemetry.Decode`]. Order: Corroborated (2). C2 does not decode type 2.

**Top-level sequence** (W = wheel count, G = gear-entry count, N = suspension-load count):

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | `packet_type` = 2 | |
| 1 | u16 | `packet_version` = 2 | |
| 3 | i32 | `vehicle_id` | joins with type 1 |
| 7 | u8 | `wheel_count` = W | expect W = `constant.number_of_wheels` |
| 8 | Wheel × W | `wheels[]` | 124 bytes each (table A). **Wheel order unknown** (§9.4) |
| C = 8+124·W | Chassis | `chassis` | 112 bytes (table B) |
| D = C+112 | Drivetrain (fixed) | `drivetrain` | 120 bytes, ending with `gear_count` = G at D+119 (table C) |
| D+120 | Gear × G | `gears[]` | 8 bytes each: f32 `upshift_rpm`, f32 `downshift_rpm` |
| E = D+120+8·G | u8 | `n_loads` = N | |
| E+1 | f32 × N | `suspension_average_loads` | newtons? (C1 `AverageLoadsNewtons`); order unknown |
| E+1+4·N | f32 | `suspension_load_bias` | fraction? |
| I = E+5+4·N | Input | `input` | 24 bytes (table D) |
| T = I+24 | Setup | `setup` | 22 bytes (table E) |
| Gn = T+22 | General | `general` | 41 bytes (table F) |
| K = Gn+41 | Constant | `constant` | 76 bytes (table G) |
| K+76 | — | end | size = 408 + 124·W + 8·G + 4·N |

With W = 4: chassis at 504, drivetrain at 616, `gear_count` at 735, gears from 736. Examples: W=4, G=6, N=4 → **968**; W=4, G=7, N=4 → 976; W=4, G=6, N=2 → 960. G and N on the wire are **unknown**. G might equal `constant.number_of_forward_gears` (hypothesis).

**Table A: Wheel (124 bytes), offsets relative to the wheel start**

| Rel. offset | Type | Field | Unit claim (C1 name) | Unit confidence |
|---|---|---|---|---|
| 0 | i32 | `contact_material_hash` | hash of surface material | — |
| 4 | f32 | `angular_velocity` | rad/s | Unconfirmed |
| 8 | f32 | `linear_speed` | m/s | Unconfirmed |
| 12 | vec3 | `slide_ls` | m/s, local space | Unconfirmed |
| 24 | vec3 | `force_ls` | N, local space | Unconfirmed |
| 36 | vec3 | `moment_ls` | N·m, local space | Unconfirmed |
| 48 | f32 | `contact_radius` | m | Unconfirmed |
| 52 | f32 | `pressure` | kPa. C1: "Not empirically confirmed - no captured session has shown a value to sanity-check magnitude against" | **Unconfirmed (flagged)** |
| 56 | f32 | `inclination` | rad (camber?) | Unconfirmed |
| 60 | f32 | `slip_ratio` | ratio | Unconfirmed |
| 64 | f32 | `slip_angle` | rad | Unconfirmed |
| 68 | vec3 | `tread_temperature` | °C? Three zones; **which zone is x, y, z (inner/middle/outer) is unknown** | Unconfirmed |
| 80 | f32 | `carcass_temperature` | °C? | Unconfirmed |
| 84 | f32 | `internal_air_temperature` | °C? | Unconfirmed |
| 88 | f32 | `well_air_temperature` | °C? | Unconfirmed |
| 92 | f32 | `rim_temperature` | °C? | Unconfirmed |
| 96 | f32 | `brake_temperature` | °C? | Unconfirmed |
| 100 | f32 | `spring_strain` | fraction? | Unconfirmed |
| 104 | f32 | `damper_velocity` | m/s | Unconfirmed |
| 108 | f32 | `hub_torque` | N·m | C1: torque cross-checked against "real MX-5 specs" (2026-09-13) |
| 112 | f32 | `hub_power` | kW | as above (power) |
| 116 | f32 | `wheel_torque` | N·m | as above |
| 120 | f32 | `wheel_power` | kW | as above |

**Table B: Chassis (112 bytes)**

| Rel. offset | Type | Field | Unit claim | Unit confidence |
|---|---|---|---|---|
| 0 | vec3 | `position_ws` | m, world space. **Axes and handedness unknown** | Unconfirmed |
| 12 | quat | `orientation` | unit quaternion (x, y, z, w per C1/C3) | Component order unverified |
| 28 | vec3 | `angular_velocity_ws` | rad/s | Unconfirmed |
| 40 | vec3 | `angular_velocity_ls` | rad/s | Unconfirmed |
| 52 | vec3 | `velocity_ws` | m/s | Unconfirmed |
| 64 | vec3 | `velocity_ls` | m/s; local axes unknown | Unconfirmed |
| 76 | vec3 | `acceleration_ws` | m/s². Gravity included or not: unknown | Unconfirmed |
| 88 | vec3 | `acceleration_ls` | m/s² | Unconfirmed |
| 100 | f32 | `overall_speed` | m/s (magnitude) | Unconfirmed; plausible |
| 104 | f32 | `forward_speed` | m/s (signed?) | Unconfirmed |
| 108 | f32 | `sideslip` | rad | Unconfirmed |

**Table C: Drivetrain, fixed part (120 bytes)**

| Rel. offset | Type | Field | Unit claim | Unit confidence |
|---|---|---|---|---|
| 0 | f32 | `engine_rpm` | rpm | plausible |
| 4 | f32 | `engine_rev_ratio` | fraction of max? | Unknown |
| 8 | f32 | `engine_torque` | N·m | cross-checked (C1, MX-5) |
| 12 | f32 | `engine_power` | kW | cross-checked (C1, MX-5) |
| 16 | f32 | `engine_load` | fraction | Unconfirmed |
| 20 | f32 | `turbo_rpm` | rpm | Unconfirmed |
| 24 | f32 | `turbo_boost_pressure` | kPa (flagged by C1 as not confirmed) | **Unconfirmed (flagged)** |
| 28 | f32 | `fuel_remaining` | litres | Unconfirmed |
| 32 | f32 | `fuel_use_rate` | L/s | Unconfirmed |
| 36 | f32 | `oil_pressure` | kPa (flagged) | **Unconfirmed (flagged)** |
| 40 | f32 | `oil_temperature` | °C? | Unconfirmed |
| 44 | f32 | `coolant_temperature` | °C? | Unconfirmed |
| 48 | f32 | `exhaust_gas_temperature` | °C? | Unconfirmed |
| 52 | f32 | `motor_rpm` | rpm (hybrid/EV motor) | Unconfirmed |
| 56 | f32 | `battery_remaining` | J. C1: "Joules is a best guess … no hybrid/EV car has been captured yet" | **Unconfirmed (flagged)** |
| 60 | f32 | `battery_use_rate` | J/s | Unconfirmed |
| 64 | f32 | `transmission_rpm` | rpm | Unconfirmed |
| 68 | f32 | `gearbox_input_rpm` | rpm | Unconfirmed |
| 72 | f32 | `gearbox_output_rpm` | rpm | Unconfirmed |
| 76 | f32 | `gearbox_torque` | N·m | Unconfirmed |
| 80 | f32 | `gearbox_power` | kW | Unconfirmed |
| 84 | f32 | `gearbox_load_in` | fraction | Unconfirmed |
| 88 | f32 | `gearbox_load_out` | fraction | Unconfirmed |
| 92 | f32 | `time_since_shift` | s | Unconfirmed |
| 96 | f32 | `estimated_driven_speed` | m/s | Unconfirmed |
| 100 | f32 | `output_torque` | N·m | Unconfirmed |
| 104 | f32 | `output_power` | kW | Unconfirmed |
| 108 | f32 | `output_efficiency` | fraction | Unconfirmed |
| 112 | u8 | `starter_active` | bool | |
| 113 | u8 | `engine_running` | bool | |
| 114 | u8 | `engine_fan_running` | bool | |
| 115 | u8 | `rev_limiter_active` | bool | |
| 116 | u8 | `traction_control_active` | bool | |
| 117 | u8 | `speed_limiter_enabled` | bool (pit limiter switch?) | |
| 118 | u8 | `speed_limiter_active` | bool | |
| 119 | u8 | `gear_count` = G | count of following Gear entries | Corroborated (2) |

**Table D: Input (24 bytes)**

| Rel. offset | Type | Field | Meaning | Confidence |
|---|---|---|---|---|
| 0 | f32 | `steering` | C1 `SteeringFraction`. **Range and sign unknown** (−1..1? left negative?) | Unknown |
| 4 | f32 | `accelerator` | 0..1? Raw pedal or after assists: unknown | Unconfirmed |
| 8 | f32 | `brake` | 0..1? | Unconfirmed |
| 12 | f32 | `clutch` | 0..1? Direction (1 = pressed?) unknown | Unknown |
| 16 | f32 | `handbrake` | 0..1? | Unconfirmed |
| 20 | i32 | `gear` | **Encoding of reverse and neutral unknown** | Unknown |

**Table E: Setup (22 bytes)**

| Rel. offset | Type | Field | Meaning | Confidence |
|---|---|---|---|---|
| 0 | f32 | `brake_bias` | fraction (front share?) | Unconfirmed |
| 4 | f32 | `front_anti_roll_stiffness` | N·m/rad. C1: "Not empirically confirmed" | **Unconfirmed (flagged)** |
| 8 | f32 | `rear_anti_roll_stiffness` | N·m/rad | Unconfirmed |
| 12 | f32 | `regen_limit` | fraction | Unconfirmed |
| 16 | f32 | `deploy_limit` | fraction | Unconfirmed |
| 20 | u8 | `abs_level` | level index | — |
| 21 | u8 | `tcs_level` | level index | — |

**Table F: General (41 bytes)**

| Rel. offset | Type | Field | Meaning | Confidence |
|---|---|---|---|---|
| 0 | vec3 | `center_of_gravity` | m | cross-checked ("Meters", C1) |
| 12 | f32 | `steering_wheel_angle` | **degrees**: renamed from radians in C1 commit `0ba58395ed` (2026-09-25), "Fixed incorrect naming of steering angle field". Sign unknown. | Single; observed by C1 |
| 16 | f32 | `total_mass` | kg | cross-checked (C1, MX-5) |
| 20 | f32 | `driven_wheel_angular_velocity` | rad/s | Unconfirmed |
| 24 | f32 | `non_driven_wheel_angular_velocity` | rad/s | Unconfirmed |
| 28 | f32 | `estimated_rolling_speed` | m/s | Unconfirmed |
| 32 | f32 | `estimated_linear_speed` | m/s | Unconfirmed |
| 36 | f32 | `total_brake_force` | N | Unconfirmed |
| 40 | u8 | `abs_active` | bool | |

**Table G: Constant (76 bytes)**

| Rel. offset | Type | Field | Meaning | Confidence |
|---|---|---|---|---|
| 0 | vec3 | `chassis_bbox_min` | m | cross-checked ("Meters") |
| 12 | vec3 | `chassis_bbox_max` | m | cross-checked ("Meters") |
| 24 | f32 | `starter_idle_rpm` | rpm | plausible |
| 28 | f32 | `engine_torque_peak_rpm` | rpm | plausible |
| 32 | f32 | `engine_power_peak_rpm` | rpm | plausible |
| 36 | f32 | `engine_max_rpm` | rpm | plausible |
| 40 | f32 | `engine_max_torque` | N·m | cross-checked (C1) |
| 44 | f32 | `engine_max_power` | kW | cross-checked (C1) |
| 48 | f32 | `engine_max_boost` | kPa (flagged) | **Unconfirmed (flagged)** |
| 52 | f32 | `fuel_capacity` | litres | Unconfirmed |
| 56 | f32 | `battery_capacity` | J (flagged) | **Unconfirmed (flagged)** |
| 60 | f32 | `track_width_front` | m | cross-checked ("Meters") |
| 64 | f32 | `track_width_rear` | m | cross-checked ("Meters") |
| 68 | f32 | `wheelbase` | m | cross-checked ("Meters") |
| 72 | u8 | `number_of_wheels` | count | |
| 73 | u8 | `number_of_forward_gears` | count | |
| 74 | u8 | `number_of_reverse_gears` | count | |
| 75 | u8 | `is_hybrid` | bool | |

"Cross-checked" means C1's note: "unlike Torque/Power/Mass/Meters below, all cross-checked against real MX-5 specs from the 2026-09-13 rig log" [C1-MSG `PmrVehicleTelemetryWheel.cs`]. Even these unit names are one PC capture of one car, so pitwall re-checks them (§14.2).

### 7.5 Type 3: SessionStopped

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | `packet_type` = 3 | |
| 1 | u16 | `packet_version` | no decoder checks it [C1-MH][C2][C3]; value unknown |
| 3 | — | end? | Any payload after byte 3 is unknown. Log the size the first time. |

### 7.6 Enumerations

RaceSessionState (RaceInfo `state`), Confirmed (3) [C1-ENUM][C2][C3]:

| Value | Meaning |
|---|---|
| 0 | Inactive |
| 1 | Active |
| 2 | Complete |

RaceFlags (type 1 `flags`, u32 bitfield). Single source [C1-ENUM `PmrRaceFlags.cs`], probably from the header:

| Bit | Mask | Meaning |
|---|---|---|
| 0 | 0x1 | Chequered |
| 1 | 0x2 | Yellow |
| 2 | 0x4 | White |
| 3 | 0x8 | Blue |

Other bits: unknown. Log them when seen.

### 7.7 Possible future versions (do not implement yet)

C3 contains an **inactive** branch guarded by `Version > 1` (its constant is 1). It adds fields to RaceInfo and ParticipantRaceState [C3 `PMRUDPProtocol.cs`; commit "Introduced protocol version switch for PMR UDP", 2025-12-13]:

- **RaceInfo:** `session_time_elapsed` and `track_grip` (both f32, after `track_temperature`); `session_is_laps` (u8, after `is_laps`).
- **ParticipantRaceState:**
  - `last_lap_time` (f32, after `best_lap_time`);
  - `last_sector_times` (an lpf32 array, after `best_sector_times`);
  - `tyre_compound_front` and `tyre_compound_rear` (lpstr);
  - `in_pit_lane` and `lap_valid` (u8, around `in_pits`);
  - `aero_damage`, `suspension_damage` and `engine_damage` (f32, after `flags`).

C3 states no source for these. Treat them as a hint that Straight4 may extend types 0 and 1, and that the version field is the switch. **Implement only after observing a type-0 or type-1 datagram with version ≥ 2**, and then only from a capture or an official layout.

---

## 8. Units policy for pitwall

pitwall's rule is "unknown stays unknown". For PMR:

| Class | Fields | pitwall behaviour until §14 gates pass |
|---|---|---|
| Layout-confirmed and semantically obvious | `engine_rpm`, `engine_max_rpm`, bools, counts, enums, strings | decode and emit |
| Unit plausible, verifiable against the HUD | `overall_speed` (m/s), `current_lap_time` (s), `layout_length` (m), `fuel_remaining` (L) | emit **only after** a recorded capture matches the in-game HUD and track length (§14.2); until then `None` |
| Flagged unconfirmed by C1 | tyre/oil/boost pressures (kPa), battery (J), anti-roll stiffness, `duration` | `None` until verified. Keep the raw value in debug output only. |
| Unknown sign, range or encoding | `steering`, `gear`, `clutch`, axes, quaternion order, wheel order, tread-zone order, lap/sector/position base | `None` until settled by a scripted capture |

PMR has per-quantity unit preferences (distance, fluid, pressure, weight) on PC [C1-CFG]. **Whether UDP values follow those preferences is unknown.** Test it: toggle pressure and fluid units between two captures and compare raw values (§14.2 step 9).

---

## 9. Mapping to pitwall's unified model

New identifiers: `Game.PMR = "pmr"` in `src/pitwall/model/telemetry.py`. The adapter goes in `src/pitwall/adapters/pmr/`: pure, no I/O (ADR-002), `AdapterInfo(name="pmr-udp", transport="udp", default_port=7576, ground_plane=<from capture>)`.

**Platform** is not on the wire. Take it from the user's Connect setting, never from packets. Record it in `.pwcap` `CaptureMeta.extra` (§14.1).

### 9.1 Player selection and merging

- **Player id.** The player is the `vehicle_id` of the type-1 datagram with `is_player = 1`. Corroborated by C3, which does exactly this [C3 `PMRUDPReceiver.cs`], and by C1's commit `db61b6396d`, which notes that player telemetry is matched by `vehicle_id`.
- **Before the player id is known**, type-2 datagrams are counted as ignored. No CarFrame is fabricated.
- **CarFrame.** Each type-2 datagram whose `vehicle_id` equals the player id yields one CarFrame. The frame is merged with the latest player type-1 state.
  - If that state is older than about 2 frame intervals, set `FrameQuality.STALE_LAP_DATA`.
  - Do not extrapolate lap distance in the adapter. The core may do so.
- **Other cars.** Type-2 datagrams for other vehicles, if the game sends them, are ignored for CarFrame. Type-1 states of other cars go to the field model (§13), not to CarFrame.

### 9.2 CarFrame

| CarFrame field | PMR source | Transform | Gate |
|---|---|---|---|
| `t_recv_ns` | host | — | — |
| `session_time_s`, `frame_id` | **none** | `None` | — |
| `throttle` | input.`accelerator` | as-is if 0..1 | verify range |
| `brake` | input.`brake` | as-is if 0..1 | verify range |
| `clutch` | input.`clutch` | as-is if 0..1 and 1 = pressed | verify direction |
| `steering` | input.`steering` | map to −1 left … +1 right | verify sign and range (steering sweep) |
| `speed_kph` | chassis.`overall_speed` | × 3.6 | verify against the HUD |
| `gear` | input.`gear` | map to −1/0/1..n | verify R and N encoding |
| `rpm` | drivetrain.`engine_rpm` | — | — |
| `max_rpm` | constant.`engine_max_rpm` | — | — |
| `drs_open` | none | `None` | — |
| `ers_store_j` | drivetrain.`battery_remaining` | — | `None` until a hybrid capture confirms J |
| `pos_x_m`, `pos_y_m`, `pos_z_m` | chassis.`position_ws` | identity | axes unknown; set `ground_plane` from capture |
| `vel_*_mps` | chassis.`velocity_ws` | identity | as above |
| `g_lat`, `g_lon`, `g_vert` | chassis.`acceleration_ls` | ÷ 9.80665, axes and signs mapped | verify local axes; gravity included? |
| `yaw_rad`, `pitch_rad`, `roll_rad` | chassis.`orientation` | quaternion → Euler | verify component order and axes |
| `lap_number` | type 1 `current_lap` | +1 if 0-based | verify base |
| `lap_distance_m` | type 1 `lap_progress_fraction` × RaceInfo `layout_length` | product; keep raw (may be <0 or >1) | verify that ∫speed dt over a lap ≈ `layout_length` |
| `total_distance_m` | none | `None` (do not derive until the lap base is settled) | — |
| `current_lap_time_ms` | type 1 `current_lap_time` | × 1000, round | verify against the HUD |
| `last_lap_time_ms` | **no v1 field** | `None` (see LapCompletion) | — |
| `sector` | type 1 `current_sector` | −1 if 1-based | verify base |
| `lap_invalid` | none in v1 | `None` | — |
| `pit_status` | type 1 `in_pits` | 1 or 2 per semantics | `None` until pit lane vs box is known |
| `race_position` | type 1 `race_position` | — | verify base |
| `tyre_surface_temp_c` | wheel `tread_temperature` (3 zones) | mean of the 3 zones, wheel-ordered | `None` until °C vs K and wheel order are settled |
| `tyre_inner_temp_c` | wheel `carcass_temperature` | wheel-ordered | as above |
| `tyre_pressure_psi` | wheel `pressure` | kPa × 0.1450377 | `None` until the unit is confirmed |
| `brake_temp_c` | wheel `brake_temperature` | wheel-ordered | unit and wheel order |
| `tyre_wear_pct`, `tyre_compound`, `tyre_age_laps` | **none** | `None` | — |
| `fuel_litres` | drivetrain.`fuel_remaining` | — | verify against the HUD |
| `fuel_capacity_litres` | constant.`fuel_capacity` | — | as above |
| `fuel_kg`, `fuel_remaining_laps_game` | none | `None` | — |
| `brake_bias_front_pct` | setup.`brake_bias` | × 100 if front fraction | verify against the setup screen |
| `traction_control` | setup.`tcs_level` | — | — |
| `abs_active` | general.`abs_active` | — | — |

### 9.3 SessionInfo, GameEvent, LapCompletion, CarSetup

| Model | Field | PMR source / rule |
|---|---|---|
| SessionInfo | `session_uid` | **Not on the wire.** pitwall generates one on RaceInfo `state` → Active, or when the `session` string changes while Active (C1-MON uses the same heuristic). |
| | `track_id` | `"pmr:" + slug(track) + ":" + slug(layout)`, but only after captures show the strings are stable ids rather than localised display text. Until then also key on the rounded `layout_length`. |
| | `track_name`, `track_length_m` | `track` (+ `layout`); `layout_length` (after the gate) |
| | `session_type` / `session_type_raw` | map the `session` string. Vocabulary unknown, so `UNKNOWN` plus the raw value until observed. |
| | `total_laps` | `duration` when `is_laps` = 1, **only if** captures show `duration` is then a lap count; else `None` |
| | `weather` | `condition` from the `weather` string (raw until the vocabulary is known); `air_temp_c` / `track_temp_c` from the temperatures after a plausibility check |
| | `car_name` / `car_id` | player type-1 `vehicle_name` (+ `vehicle_class`) |
| | `extra` | `season`, `game_mode`, `overtime`, `num_participants`, `state`, packet versions seen |
| | `pit_speed_limit_kph`, `track_zones` | **not on the wire**: `None`. Sector boundaries are learned, not reported (§13). |
| GameEvent | SESSION_STARTED / SESSION_ENDED | `state` transitions; type 3 → SESSION_ENDED |
| | CHEQUERED_FLAG, OTHER | edges of player `flags` bits; `disqualified` edge |
| | PIT_ENTRY / PIT_EXIT | edges of player `in_pits` (after semantics are known) |
| LapCompletion | trigger | player `current_lap` increases (C1-MON does the same for all cars) |
| | `lap_time_ms` | **Exact only in one case.** If `best_lap_time` decreased at the tick, the new best is the lap just completed. Otherwise `None`. C1 notes "The UDP protocol has no explicit 'last lap time' field"; the last pre-tick `current_lap_time` "can be up to one UDP interval short" [C1-MON `PmrMonitorLap.cs`]. C2 reports that finish packets "often zero currentLapTime" [C2 `race-session.js`]. Put the estimate in a GameEvent(OTHER, code=`pmr_lap_time_estimate`) with its ±1/f bound. |
| | `sector_times_ms` | last pre-tick `current_sector_times`. Whether the final sector is present at the tick is unknown, so missing sectors stay `None`. |
| | `valid` | `None` (no field in v1) |
| CarSetup | parameters | `brake_bias`, `abs_level`, `tcs_level`, `regen_limit`, `deploy_limit`. Omit the anti-roll values (flagged unconfirmed). Gate the fingerprint on verified units. |

### 9.4 Wheel order and axes (blocking unknowns)

- **Wheel order.** No source states the wheel order of `wheels[]` or of `suspension_average_loads`. pitwall needs FL, FR, RL, RR (`Wheels`).
  - Do **not** assume `from_fl_fr_rl_rr`. Add a constructor only after a capture decides the order.
  - Steady right-hand corner: the left wheels show higher vertical load (`force_ls` vertical component).
  - Hard braking: the front wheels' load rises.
- **Axes.** Unknown: world axes (which is vertical), the local-space axes behind `velocity_ls`/`acceleration_ls`, quaternion component order, and handedness.
  - Settle the vertical axis from the axis with the smallest range over a flat lap.
  - Then set `AdapterInfo.ground_plane`.

---

## 10. What is missing (v1 types 0 and 1, v2 type 2)

- No session clock, frame counter or packet timestamp. Timing is host-receive time only.
- No last-lap-time field; lap validity; tyre compound; tyre wear; damage; penalties (only a DQ flag); total distance; pit speed limit; or sector boundary positions. The C3 v>1 branch hints at future compound, validity, last-lap and damage fields (§7.7).
- No explicit pause state. SimHub 9.10.13 "Detect game pause" [V21] shows it can be inferred somehow; the method is unknown.
- No platform or game-version field.
- No ERS/DRS. Hybrid battery fields exist, with unconfirmed units.
- Other cars: position and speed only if type 2 is sent for them (unknown). Otherwise only lap fraction, sector, times and status.

---

## 11. Community-reported behaviour and quirks (dated)

| Date | Report | Source | Status |
|---|---|---|---|
| 2025-11-26 | PC auto-config forces multicast off ("prevents network-wide spam"); forwarding added "now that unicast is available" | [V21] | vendor changelog |
| 2026-04-09 | Sector-time and best-sector UDP data corrected in 2.0.0.2 | [O3] | official |
| undated | Stream can stop until UDP is toggled off and on (PC) | [V13] | vendor FAQ |
| undated | Backspace in the settings fields resets the screen (1.5.0.0, PC) | [V13] | vendor doc |
| 2026-09-13 | A race-weekend race session showed `duration` = 300 | [C1-MSG `PmrRaceInfo.cs`] | single capture |
| 2026-09-16 | "PMR sends VehicleId=0 for every AI car" and "IsPlayer flag is inverted". **Both are likely artifacts** of reading `is_player` before `vehicle_id`: in that order the u8 lands in the low byte of the i32. C1 fixed the order on 2026-09-21 and removed the inversion. The VehicleId=0 comment and a "true for every car" note in `PmrMonitorLap.cs` remain but predate the fix. Treat both as **unverified**. | [C1-MON][C1-BRE, commit `db61b6396d`] | stale comments |
| 2026-09-22 → | Race results: standings "locked just before the leader finishes (PMR often corrupts results after the line)"; finish packets "often zero currentLapTime"; finish flags "often arrive with corrupt order" | [C2 README, `race-session.js`] | single tool |
| 2026-09-22 → | Session labels normalised with English and Polish keywords (`trening`, `kwalifik`, `wyscig`). This suggests the `session` string may follow the UI language. My inference, unverified. | [C2 `session-kind.js`] | inference |

---

## 12. Console caveats (PS5 / Xbox)

1. **No stream has been seen from a console yet.** The first PS5 capture is the gate (§14).
2. **Settings on console.** Settings > Preferences: UDP Enabled On, UDP Frequency 60, UDP Port 7576, UDP Host = the Mac's LAN IP [V27].
   - Read and record the **default Host value** on the PS5 before changing it. If it is a multicast address, the Mac could join 224.0.0.150 instead; that is untested, and Wi-Fi multicast is unreliable.
3. **Network.**
   - The PS5 and the Mac must be on the same LAN segment. The game sends unicast, so no NAT traversal is involved.
   - The macOS firewall must allow inbound UDP 7576.
   - Prefer Ethernet. Measure the Wi-Fi loss rate in the capture.
4. **Builds lag.** Consoles have lagged PC [N15]. PS5 packet versions may differ from C1's PC observations (1/1/2), so the version gate in §6 must log rather than crash.
5. **Hotfix 2.3.0.1 (2026-10-05)** lists no UDP change [O4]. Record the exact game version shown in the PS5 menu with every capture.
6. **One destination.** If James also runs a motion or haptic app that needs PMR data, pitwall must forward. The game cannot send to two hosts.
7. **Other people's data.** Online sessions put other drivers' names in `driver_name`. Treat them as personal data: do not send them to the LLM, and keep them out of logs beyond the session.

---

## 13. Track knowledge from PMR

| Need | Source | Layer (track-knowledge-sources.md) |
|---|---|---|
| Identity | RaceInfo `track` + `layout` (+ `layout_length` as a tiebreak) | L0a |
| Lap length | RaceInfo `layout_length` | L0a |
| Lap distance (player and every car) | `lap_progress_fraction` × `layout_length`. Float32 resolution is about 1.5 mm at 25 km. | L0a |
| Sector boundaries | Learned: the median fraction at which `current_sector` changes, across the player and all cars | L0b (learned; **not** `TrackZones`, which holds game-reported values only) |
| Field speed profile | d(fraction × L)/dt per car from type-1 host timestamps. Resolution depends on the per-participant rate (unknown). | L0b |
| Map outline | player `position_ws` (and other cars', if type 2 covers them) | L0b / L3 |
| Turn names, pit lane | not on the wire | L2 (curated) |

C1 ships a track table generated from the PC game's data files: `data/pmr/tracks/*.json`, `"Author": "Straight 4 Studios"`, 21 tracks, layout lengths in metres.

- Use it only as a **test oracle**, for example to check `layout_length` from a capture.
- Do not vendor it. The data derive from Straight4's game files whatever the repository's MIT licence says.

---

## 14. Gates and implementation plan

### 14.1 Gate 0: decoder-less capture (prerequisite)

- `UdpListener` already writes every datagram to `.pwcap` **before** calling the handler (`src/pitwall/ingest/sources.py` `_run`). A listener on 7576 with a no-op handler is therefore a complete raw recorder.
- Missing: a CLI command (`pitwall capture --port 7576 --game-hint pmr --platform ps5`) or a Connect-page toggle. See game-compatibility.md §3.10.
- Fill `CaptureMeta`:
  - `game_hint = "pmr"`, `synthetic = False`;
  - `extra = {platform, game_version, udp_frequency_hz, sender_ip, network: "ethernet"|"wifi", units_prefs}`.
- `.pwcap` stores the listener port, not the sender IP. Record the sender IP (from `SourceStats`) in `extra` as evidence that the packets came from the PS5.

### 14.2 Gate 1: the scripted PS5 capture session

Do one capture per step, or one long capture with a written timeline. Each step settles specific unknowns.

| Step | Action | Settles |
|---|---|---|
| 1 | UDP Enabled, sit in menus for 30 s | Is anything sent outside sessions? |
| 2 | Practice at a known layout (e.g. Spielberg GP, 4318 m in C1's table); sit in the pit box for 20 s | RaceInfo strings (id vs display, localisation); `layout_length`; stationary values; tyre temperature vs ambient (°C vs K); pressure magnitude; fuel vs HUD; gear encoding for N; `in_pits` |
| 3 | Stationary steering sweep: full left, then full right | `steering` sign and range; `steering_wheel_angle` (degrees) |
| 4 | Select reverse briefly | `gear` encoding for R |
| 5 | Drive out of the pits | `in_pits` semantics (pit lane vs box); `speed_limiter_*` |
| 6 | Steady constant-radius right-hander, then a hard straight-line stop | Wheel order (left/right and front/rear loads); local-axis signs; gravity in `acceleration_*` |
| 7 | Three or more flying laps | `current_lap` base; fraction behaviour at the line (wrap, negatives); `current_sector` base and count; sector arrays at the tick; best-lap update; `current_lap_time` at the tick vs HUD; ∫speed dt vs `layout_length`; vertical axis |
| 8 | Pause for 20 s, then resume | Pause signature |
| 9 | Change Pressure and Fluid units in Preferences, drive 1 lap | Do UDP values follow the unit preferences? |
| 10 | Set UDP Frequency to 10, 20, 30, 60 Hz (1 min each) | Per-type rates; whether type 1 and type 0 follow the setting |
| 11 | Short race against AI (about 8 cars), to the flag | Per-participant datagrams; `is_player` uniqueness; distinct `vehicle_id`s; type 2 for AI or not; `flags` bits; finish behaviour; SessionStopped size and version |
| 12 | Exit to menu | type 3; RaceInfo `state` transitions |

Write down HUD readings at fixed moments (speed, gear, lap time, fuel, tyre temperatures and pressures with their units) so that values can be compared.

**Gate 1 passes when** every datagram in the capture:

- parses with **exact consumption**;
- has (type, version) pairs in §5 (or new ones are documented);
- shows `wheel_count == number_of_wheels` everywhere;
- and speed, lap time, fuel and layout length match the HUD and the track table within stated tolerances.

### 14.3 Gate 2: ask Straight4 (in parallel)

**Channels.** The official site links:

- Discord: https://discord.gg/pmr
- the Straight4 forum hub: https://hub.straight4.com/index.php#english-forums.1
- a support page (`/support.php` on projectmotorracing.com)

Neither the Discord nor the hub was opened in this session. SimHub's support was built "with Straight4's help" (game-compatibility.md §3.4).

**Ask for:**

1. `UDPTelemetryProtocol.h`, `docs/packet_layout_example.txt` and `SimpleUDPServer`, and the terms for implementing a decoder from them in a personal or open-source tool.
2. Whether console builds emit the same versions as PC.
3. Units for every field, wheel order, axis conventions and the quaternion layout.
4. Per-type send rates, and whether AI telemetry is sent.
5. The `is_player` / `vehicle_id` order discrepancy between the header and the wire.
6. Planned versions: last lap, validity, compounds, damage.

If the header arrives, add it as an "official" source tier and re-check every table here against it. **The wire order wins where they differ** (§7.3).

### 14.4 Implementation (after Gate 1)

1. `src/pitwall/adapters/pmr/`:
   - a pitwall-authored struct table (§7) and a cursor reader with bounds checks;
   - per-type decoders and the session state machine of §9.
   - Unknown or unconfirmed fields stay `None`.
2. `Game.PMR` added. Listener on 7576 wired in `serve`. Connect page row (port 7576; "set Host to <Mac LAN IP>").
3. `tests/unit/test_pmr_protocol.py`: machine-check pitwall's struct tables against §7 of this document, like `tests/unit/test_f1_protocol.py`. Keep §7's table columns stable for this.
4. `tests/unit/test_pmr_adapter.py`: synthetic vectors (§15.1, marked synthetic) plus the recorded fixture (§15.2).
5. `docs/licences.md`: add rows. C1 (MIT): protocol reference, no code copied. C2 (proprietary): facts only. C3 (CC BY-NC-SA 4.0): facts only.
6. `src/pitwall/capabilities.py`, which has no PMR row yet:
   - PC: `COMMUNITY_DOCUMENTED` once implemented (layout from community decoders; pitwall has no PC capture).
   - PS5: `UNVERIFIED` → `RECORDED_VALIDATED` after a Gate-1 capture is in `tests/fixtures/recorded/` → `LIVE_VALIDATED` after a live session.
   - Xbox: `UNVERIFIED` until an Xbox capture exists.
   - Per-field `FieldSupport` reflects §8. Fields still unconfirmed stay `UNVERIFIED`.

---

## 15. Test vectors and sample-packet guidance

**No public PMR sample captures were found.** C1 has no test fixtures. C2's `selftest.js` builds JavaScript objects, not wire bytes. Do not copy it.

### 15.1 Synthetic vectors (pitwall-made from §7; synthetic tier only)

These were built from §7 with an independent script. They prove only that pitwall's decoder matches this document, not the game. The strings are deliberately fake.

**RaceInfo v1**, 36 bytes = 32 + Σlen(3+1+0+0+0+0). Contents:

- track "SYN", layout "A", four empty strings;
- `layout_length` 4000.0, `duration` 600.0, `overtime` 0.0, ambient 20.0, track 30.0;
- `is_laps` 0, `state` 1 (Active), 2 participants.

```
00 01 00 03 53 59 4e 01 41 00 00 00 00 00 00 7a
45 00 00 16 44 00 00 00 00 00 00 a0 41 00 00 f0
41 00 01 02
```

**ParticipantRaceState v1**, 67 bytes = 45 + Σlen(3+3+0+0) + 4·(1+3). Contents:

- `vehicle_id` 7, `is_player` 1, vehicle "CAR", driver "DRV", empty livery and class;
- position 3, lap 2, current lap time 45.5, best 90.25, fraction 0.5, sector 1;
- current sector times [30.0], best [29.5, 31.0, 28.75];
- `in_pits` 0, finished 0, DQ 0, `flags` 0x2 (Yellow).

```
01 01 00 07 00 00 00 01 03 43 41 52 03 44 52 56
00 00 03 00 00 00 02 00 00 00 00 00 36 42 00 80
b4 42 00 00 00 3f 01 00 00 00 01 00 00 f0 41 03
00 00 ec 41 00 00 f8 41 00 00 e6 41 00 00 00 02
00 00 00
```

**ParticipantVehicleTelemetry v2.** Generate in the test, not as a literal: W=4, G=6, N=4 gives 968 bytes. Assert:

- the offsets of `chassis` (504), `drivetrain` (616), `gear_count` (735) and `constant` (968 − 76 = 892);
- that a deliberate 1-byte truncation is rejected;
- that one extra trailing byte is flagged (§6 step 4).

**Negative vectors:**

- `len < 3`;
- type 4;
- RaceInfo whose string length runs past the end;
- invalid UTF-8;
- `state` = 3;
- `wheel_count` ≠ `number_of_wheels`;
- NaN floats.

### 15.2 Recorded fixtures (the evidence that unlocks status upgrades)

- Store `tests/fixtures/recorded/pmr_ps5_<gameversion>_<track>_<yyyymmdd>.pwcap` with its `CaptureMeta.extra` (§14.1). Trim it to about 2 minutes for the unit tests, and keep the full capture outside git.
- Recorded assertions, written down before looking at the decoded values:
  - every datagram parses with exact consumption;
  - stationary in the box: speed < 0.1 m/s, gear = the N encoding, rpm ≈ `starter_idle_rpm` ± 20 %;
  - fuel matches the HUD;
  - the layout length matches C1's table for that layout within 1 m;
  - ∫`overall_speed` dt over a clean lap lies within ±3 % of `layout_length`;
  - `lap_progress_fraction` rises monotonically within a lap;
  - at most one participant has `is_player = 1`.

---

## 16. Licence position: can pitwall implement this?

- **Yes, from facts.** pitwall writes its own decoder from the tables in §7. These are a description of field order and types, corroborated across three decoders, and they will be validated by pitwall's own captures.
- **C1 (MIT).** Reading it and using its facts is permitted; even copying code would be permitted with the notice, but pitwall's policy is to implement from specs. Attribute C1 in `docs/licences.md` as the protocol reference.
- **C2 (proprietary) and C3 (CC BY-NC-SA 4.0).** Used here for corroborating facts only. No code, comments or structure text is reproduced. Do not open them while writing the decoder; this document is the interface.
- **Official header (`UDPTelemetryProtocol.h`, sample, layout example).** Not obtained; licence unknown; it presumably sits under the PMR EULA. If Straight4 supplies it, record the terms before using it. Do not commit the header to the repository without written permission.
- **Game data tables** (C1 `data/pmr/`, derived from game files): test oracle only, never shipped.

---

## 17. Open questions (each settled by the step shown)

1. Does a PS5 stream arrive, with which versions and sizes, and does it consume exactly? → §14.2 (all steps)
2. The console default Host value; multicast on console? → §12 item 2
3. Per-type send rates, and the effect of UDP Frequency on types 0 and 1 → §14.2 step 10
4. Is type 2 sent for AI cars? → step 11
5. Wheel order; tread-zone order; suspension-load order → step 6
6. World and local axes, gravity in acceleration, quaternion component order → steps 6 and 7
7. Range and sign of steering, throttle, brake and clutch; gear encoding → steps 2–4
8. Bases (0 or 1) of lap, sector and position; fraction behaviour at the line → step 7
9. Units: temperatures (°C vs K), pressures, fuel, duration (s vs laps), battery → steps 2, 9 and 11, plus a hybrid car later
10. Do UDP values follow the in-game unit preferences? → step 9
11. Format and localisation of the track, layout, session and weather strings → step 2, repeated in a second UI language if possible
12. Pause signature; SessionStopped payload → steps 8 and 12
13. Is `is_player` unique and correct, and are `vehicle_id`s distinct? (C1's stale comments, §11) → step 11
14. The official header's content and licence → §14.3
15. Xbox parity → needs an Xbox capture (no owner known)

---

## 18. Verification performed while writing (2026-10-10)

| Check | Result |
|---|---|
| O1 v2.3 notes (WebFetch) | "Project Motor Racing — Version 2.3", "September 23, 2026"; CONSOLES: "Enabled UDP telemetry settings on console platforms"; also "Fixed an issue on PlayStation 5 causing crashes when returning to the pits during Join in Progress in Custom Lobbies sessions" |
| O2 FAQ | "November 25, 2025"; "PMR does have UDP telemetry. This feature can be enabled via Settings > Preferences."; platforms "PC, PlayStation 5, and Xbox Series X\|S" |
| O3 2.0.0.2 | "April 09, 2026"; "Corrected UDP telemetry data for sector times and best sectors." |
| O4 2.3.0.1 | "October 05, 2026"; no UDP, telemetry or console lines |
| C1 via GitHub API and raw files at `c23c291` | licence MIT; pushed 2026-10-10; full read of `Pmr.Udp` and `Pmr.Monitor`, plus `PmrLocalConfigProvider.cs` and `PmrPathProvider.cs`; four PMR UDP commits (§1); the only references to `UDPTelemetryProtocol.h`, `packet_layout_example.txt` and `SimpleUDPServer` are the comment in `BinaryReaderExtensions.cs` (whole-repo grep) |
| C2 at `9dceb25` | LICENSE "All rights reserved"; README and README FIRST (default port 7580); `udp-parser.js` layout read for facts; `packet-forensics.js` samples type/version at byte offsets 10/11, inconsistent with its own parser. Treated as a diagnostic leftover, not evidence. |
| C3 at `cb88003` | `License`: "Most parts … licensed under CC BY-NC-SA 4.0"; `PMRUDPProtocol.cs` (Version = 1, inactive v>1 branch) and `PMRUDPReceiver.cs` (multicast default true, group 224.0.0.150, port 7576) read for facts; commit dates 2025-12-08 to 2025-12-15 |
| V27, V28, V13, V21 (WebFetch) | as quoted in §3 and §11; none shows a page date except V21's version dates |
| N15, N16 (WebFetch) | as quoted in §1 |
| projectmotorracing.com home | community links in §14.3; GIANTS GDN PMR tutorials page has no telemetry material (the `documentation.php` page was not checked) |
| Size arithmetic | wheel 124, chassis 112, drivetrain fixed 120, input 24, setup 22, general 41, constant 76, base 408. Computed by script from §7; the synthetic vectors in §15.1 were generated the same way. |
| Web search | **Not available.** The session's web-search budget was exhausted, so searches for `UDPTelemetryProtocol.h` and for console stream reports could not run. A follow-up can retry them, along with searches for forum or Discord reports of PS5/Xbox streams since 2026-09-23. |

---

## 19. Sources

Retrieved 2026-10-10 unless stated otherwise.

**Official (Straight4 / PMR)**
- [O1] Project Motor Racing — Version 2.3 (2026-09-23): https://projectmotorracing.com/newsArticle.php?articleCode=NjU1Y2M3ODc4
- [O2] Project Motor Racing FAQ (2025-11-25): https://projectmotorracing.com/newsArticle.php?articleCode=NmNjNmE0MjQy&lang=en
- [O3] Project Motor Racing — Update 2.0.0.2 (2026-04-09): https://projectmotorracing.com/newsArticle.php?articleCode=NGI1YmMyZDI5
- [O4] Project Motor Racing — Version 2.3.0.1 (2026-10-05): https://projectmotorracing.com/newsArticle.php?articleCode=ZDk3NTVhYTFl
- Community channels linked from https://projectmotorracing.com/: https://discord.gg/pmr , https://hub.straight4.com/index.php#english-forums.1

**Community code**
- [C1] devology-uk/sim-racing-sdk (MIT) @ `c23c291140a5a5e8d0efbd80b733d4ad9bf96092`: https://github.com/devology-uk/sim-racing-sdk/tree/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/src/SimRacingSdk.Pmr.Udp
  - wire order: https://github.com/devology-uk/sim-racing-sdk/blob/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/src/SimRacingSdk.Pmr.Udp/Extensions/BinaryReaderExtensions.cs
  - versions: https://github.com/devology-uk/sim-racing-sdk/blob/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/src/SimRacingSdk.Pmr.Udp/PmrUdpMessageHandler.cs
  - transport: https://github.com/devology-uk/sim-racing-sdk/blob/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/src/SimRacingSdk.Pmr.Udp/PmrUdpConnection.cs
  - settings keys and frequencies: https://github.com/devology-uk/sim-racing-sdk/blob/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/src/SimRacingSdk.Pmr.Core/PmrLocalConfigProvider.cs
  - lap logic and rig notes: https://github.com/devology-uk/sim-racing-sdk/blob/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/src/SimRacingSdk.Pmr.Monitor/PmrMonitor.cs
  - order-fix commit: https://github.com/devology-uk/sim-racing-sdk/commit/db61b6396d
  - steering-angle commit: https://github.com/devology-uk/sim-racing-sdk/commit/0ba58395ed
  - unit-naming commit: https://github.com/devology-uk/sim-racing-sdk/commit/d270a0f91f
- [C2] Ricozwar/pmr-results-helper (proprietary, facts only) @ `9dceb25ad9ade4c9b98358767971e0809d498b5f`: https://github.com/Ricozwar/pmr-results-helper
- [C3] SeriousOldMan/Simulator-Controller (CC BY-NC-SA 4.0, facts only) @ `cb88003d999c4c01dfd37d296daf0b493cda82d1`: https://github.com/SeriousOldMan/Simulator-Controller/tree/cb88003d999c4c01dfd37d296daf0b493cda82d1/Sources/Special/PMR%20UDP%20Connector

**Vendors**
- [V13] SIM Dashboard, Project Motor Racing (PC): http://www.stryder-it.de/simdashboard/help/en/For_PC_Gamers/Game_Configuration/Project_Motor_Racing
- [V21] SimHub download page and changelog: https://www.simhubdash.com/download-2/
- [V27] SIMRIG, Project Motor Racing (Console): https://www.simrig.se/documentation/control-center/game-setup/project-motor-racing-console.html
- [V28] SIMRIG, Project Motor Racing (PC): https://www.simrig.se/documentation/control-center/game-setup/project-motor-racing.html

**Press**
- [N15] Traxion (2026-01-17): https://traxion.gg/project-motor-racings-latest-update-promises-change-but-console-players-miss-out/
- [N16] Rankouniverse, PMR telemetry guide (2026-09-23): https://www.rankouniverse.com/guide-ai-giochi/project-motor-racing/project-motor-racing-telemetry-en?lang=en

**pitwall**
- `docs/research/game-compatibility.md` (§3.4, §3.10, §9, §10), `docs/research/track-knowledge-sources.md`, `src/pitwall/model/telemetry.py`, `src/pitwall/adapters/base.py`, `src/pitwall/ingest/sources.py`, `src/pitwall/ingest/capture.py`, `src/pitwall/ingest/router.py`
