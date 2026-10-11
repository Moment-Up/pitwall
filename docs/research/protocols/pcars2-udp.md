# pcars2-udp: implementation spec (Project CARS 2, Automobilista 2, Project CARS 3)

Research date: 2026-10-10. Status: **not implemented**. Evidence tier: **community-documented**. No pitwall capture exists yet.

This spec builds on `docs/research/game-compatibility.md` §3.3 (platform verdicts, reliability) and does not repeat that
research. It adds:

- byte-exact layouts, each recomputed from field types;
- a reconciliation of the three sources that disagree on struct sizes;
- the bit-field conflicts;
- the mapping to pitwall's model;
- a capture plan that settles every open point.

**How to read the evidence.** Offsets are computed from field types under `#pragma pack(1)`, not taken from header
comments, because those comments are wrong in several places (§4.3). In the tables:

- "**H**" means the SMS header copies state it [C10-T][C10-M];
- "**PC1**" means it is inferred from SMS's PC1 packer pseudocode [C32];
- "**CC**", "**MZ**", "**MM**" and "**TT**" mark community interpretations [C9-*][C6][C30][C33];
- "**?**" means unknown, to be settled by a pitwall capture (§12).

---

## 0. Verdict in brief

- **One parser, three games.** PC2 (PS4/XB1/PC), AMS2 (PC) and PC3 (PC) all offer a "Project CARS 2" UDP protocol
  [V4][V6][V55][C6]. AMS2 is the live title. PC1, PC2 and PC3 are delisted [N3].
- **Transport.** One-way UDP broadcast to `255.255.255.255:5606`. The port is fixed. There is no handshake, subscription
  or keep-alive, so pitwall sends **zero bytes** [V30][C10-T][F4][C6].
- **Packets.** A common 12-byte header carries the packet type at byte 10 and a version at byte 11. Seven packet types
  are sent: telemetry, race definition, participants, timings, game state, time stats, and vehicle/class names [C10-T].
- **Sizes disagree** (telemetry 559 / 556 / 538, timings 1063 / 1059 / 993, participants 1136 / 1040, time stats 1040 /
  784). The disagreement is explained by layout revisions (§4.4). **Dispatch on (packet type, datagram length)**, log
  the version byte, and settle each game's sizes with a capture. The first 373 bytes of telemetry (offsets 0–372) are
  identical in every source, and they hold every CarFrame core field except world position.
- **Track knowledge is good.** The data carries untranslated track location and variation strings, track length in
  metres, and per-car lap distance (u16 metres), sector, lap, lap and sector times, and world position for up to 32 cars
  [C10-T][C31].
- **Bit-fields are not settled.** These bytes pack two values each: game/session state, flag, pit mode and lap-invalid.
  Community parsers decode them three different ways (§6). Decode them provisionally and confirm with the capture
  experiments in §12.3.
- **Console risk.** Console broadcast is reported "slow, unreliable" [V4][V7]. Crew Chief disabled its PC2 network
  mode [C9-G]. PC2 on PS5 is **UNVERIFIED** [V39][GC].
- **Licence.** No source carries a licence that lets pitwall copy the SMS header. Pitwall can implement from the facts
  (offsets, types, enums) in its own code and tables, as it does for other games. It must not vendor the header or its
  comment text (§11).

---

## 1. Sources

| ID | Source | What it is | Licence | Used for |
|---|---|---|---|---|
| [C10-T] | tyretrack/server `docs/SMS_UDP_Definitions.hpp` (single commit 91a0aba, 2018-06-04) | SMS's PC2 UDP header (copy). Telemetry 559, timings 1063 (handler v3) | none in repo or file | primary layout |
| [C10-M] | mplutka/tm-bt-led `lib/pcars2-udp/SMS_UDP_Definitions.hpp` (last commit 2021-12-18) | earlier header revision: telemetry 556, timings 1059 (handler v1) | repo is MIT, but the file is SMS's and has no licence text | revision diff |
| [C10-S] | saildeep/pcars2-udp `SMS_UDP_Definitions.hpp` (2018-03-23) | byte-identical to [C10-M] apart from line endings (diffed 2026-10-10) | none | corroboration |
| [C31] | tyretrack/server `docs/SharedMemory.h` | SMS PC2 shared-memory header, `SHARED_MEMORY_VERSION = 9`, "Copyright (c) MWL. All rights reserved." | proprietary notice | units, ranges, enums, tyre order. [C10-T] says the UDP data "mostly follows" shared memory |
| [C32] | tyretrack/server `Readme.txt` | appears to be a copy of SMS's **PC1** UDP documentation, including SMS's packer pseudocode (float → integer conversions). Provenance not confirmed | none | how SMS quantises fields (PC1). The quantisation is presumed to carry over to PC2; unverified |
| [C33] | tyretrack/server `tyretrack/pcars/v2.py` | community PC2 Python decoder (2018) | none | evidence of divergent bit-field decoding. It also misreads several offsets (§4.3) |
| [C9-S] | Crew Chief V4 `CrewChiefV4/PCars2/PCars2UDPTelemetryDataStruct.cs` (branch `main`) | C# mirror plus packet-size constants 538/308/1040/24/993/784/1164/1452 | **MIT** © 2019-2024 Britton IT Ltd | older-revision sizes |
| [C9-R] | Crew Chief `PCars2/PCars2UDPreader.cs` | dispatches on byte 10, truncates each packet to a constant length | MIT | behaviour |
| [C9-M] | Crew Chief `PCars2/PCars2Struct.cs` | UDP → state merge (scaling, bit masks), and a shared-memory struct with SMS unit comments | MIT | scaling interpretations |
| [C9-E] | Crew Chief `PCars2/enums.cs` | enums: packet type, game, session, race state, flag, pit, car flags, tyre flags, terrain, crash | MIT | enum values |
| [C9-G] | Crew Chief `CrewChiefV4/AllGames/GameDefinition.cs` | `// pCars2Network,   TODO: reinstate this when it actually works` | MIT | reliability signal |
| [C6] | crmne/moza-rev `src/madness.rs`, `src/listeners/madness.rs`, `examples/automobilista_2_log.rs`, README (madness parser added 2026-04-28) | Rust packed mirror. Requires telemetry ≥ 559 bytes. Used with AMS2 | **MIT** © 2026 Francis De Brabandere | AMS2 setup, the Linux loopback note, and AMS2 evidence for the 559 layout |
| [C30] | MacManley/project-cars-2-udp (2024-02 to 2026-06) | ESP32 C++ library. Every struct is `pack(1)`, sizes 559/308/1136/1063/24/1040/1164/1452 | **MIT** © 2024 MacManley | layout corroboration. Its vehicle-info interpretation is noted in §5.8 |
| [C34] | mplutka/tm-bt-led `lib/pcars2-udp/udp-parser.js` | JS parser generated from [C10-M]. Code comment: "there is something wrong with version since patch 4" | MIT | the version byte is unreliable |
| [V4] | SIM Dashboard, Project CARS 2 (console) | setup, "patch 2.0", reliability | vendor page | console setup |
| [V6] | SIM Dashboard, Project CARS 3 | console UDP "NOT(!) unlocked"; protocol options PC1/PC2 | vendor page | PC3 |
| [V7] | SIM Dashboard, "Project Cars 1 and 2 are slow" | broadcast slowness, router settings | vendor page | reliability |
| [V30] | RS Dash, Project CARS 2 | "global network broadcast on UDP port 5606"; PS4/Xbox need patch 2.0+ | vendor page | transport |
| [V32] | RS Dash, Project CARS 3 | telemetry on PC only; broadcast 5606 | vendor page | PC3 |
| [V55] | MOZA support, Automobilista 2 | Options > System: Shared Memory PC2, UDP Frequency 1, UDP Protocol PC2 | vendor page | AMS2 setup |
| [F4] | xsimulator.net thread (2017-10-20 to 2019-02-13) | PS4 + PC on Ethernet, "Project Cars 2" format, used for a motion rig | forum | real console use |
| [F6] | Reiza forum thread (2025-08-29 to 2025-09-02) | AMS2 UDP vs shared memory; user finds speed at offset 0x078 | forum (no Reiza staff posts) | the PC1-format pitfall (§3.6) |
| [N1] | GTPlanet, PC2 patch 2.0 on PS4 (2017-10-12) | "support for external applications" | news | console enablement |
| [N3] | GTPlanet, PC3 final pitstop (2025-07-26), via [GC] | delistings; PC3 servers end 2026-02-24 | news | status (not re-fetched) |
| [V39] | Sim Racing Telemetry App Store listing, via [GC] | generic PS4/PS5 tag | vendor | the PS5 claim (not re-fetched) |
| [GC] | `docs/research/game-compatibility.md` §3.3, §1 | pitwall's prior research | — | context |

**What could not be fetched.**

- **No official spec could be fetched.** SMS's own forum posts and example-code sites are "long since gone" (an AMS2
  Club member, 2025-08-29 [F6]). No Reiza statement on the UDP format was found [F6]. All layouts here come from copies
  of SMS's header, mirrored in third-party repositories.
- **Search budget.** The web-search budget for this run ran out before further sources could be searched. Sources were
  limited to the URLs above and repositories they link to (fetched directly). Gaps are marked **?** rather than filled.

---

## 2. Games and platforms

| Game | Platform | UDP "Project CARS 2" protocol | Evidence | Status for pitwall |
|---|---|---|---|---|
| Project CARS 2 | PS4 / Xbox One | yes (patch 2.0+) | [V4][V30][N1]; real PS4 use over Ethernet [F4] | COMMUNITY_DOCUMENTED (works on console, PS4) |
| Project CARS 2 | PS5 / Xbox Series (back-compat) | unknown | one generic vendor tag only [V39][GC]; SIM Dashboard does not name PS5 [V4] | **UNVERIFIED**: test on James's PS5 (§12.4) |
| Project CARS 2 | PC | yes; Shared Memory also offered | [V30][V4] | COMMUNITY_DOCUMENTED |
| Automobilista 2 | PC (Steam) | yes: Options > System > UDP Protocol Version "Project CARS 2" | [V55][C6] | COMMUNITY_DOCUMENTED; no relay needed |
| Project CARS 3 | PC | yes: PC1 or PC2 protocol | [V6][V32] | COMMUNITY_DOCUMENTED (likely), layout revision unknown |
| Project CARS 3 | PS4 / Xbox One | **no**: "NOT(!) unlocked on Consoles" | [V6][V32] | UNSUPPORTED |

---

## 3. Transport

### 3.1 Direction, address, port

- **Game → network only.** The game sends UDP/IPv4 datagrams to the limited broadcast address
  `255.255.255.255`, destination port **5606**.
  - The header defines `SMS_UDP_PORT 5606` and `SMS_UDP_MAX_PACKETSIZE 1500` [C10-T].
  - RS Dash: PC2 "only supports outputting its UDP telemetry as a global network broadcast on UDP port 5606" [V30].
  - The AMS2 destination `255.255.255.255:5606` was seen with tcpdump [C6].
- **The port cannot be changed in game.** A motion-rig user (2018-03-31) said it was "impossible to change port in
  PCARs" [F4]. RS Dash and SIM Dashboard give no port setting [V30][V4].
- **No handshake, subscription or keep-alive.** No source describes any message to the game. Crew Chief only binds and
  receives [C9-R]; moza-rev only binds and receives [C6]. **Pitwall sends nothing.** The exact handshake bytes are
  therefore "none".
- **Source port:** not documented (**?**). Do not filter on it.

### 3.2 In-game settings

**PC2 console (PS4/XB1).**

- From the main menu: Options > System ("Configurate External Apps").
- **UDP Frequency:** 1–9, where 1 is the fastest. SIM Dashboard suggests 4; RS Dash suggests 1, or 4 if laggy
  [V4][V30].
- **UDP Protocol Version:** "Project CARS 2". The other choice is "Project CARS 1" [V4].
- Patch 2.0 or later is required [V4][V30].

**PC2 PC.** The same panel adds a **Shared Memory** option [V30].

**AMS2.**

- Options > System: Shared Memory "Project CARS 2", UDP Frequency 1, UDP Protocol Version "Project CARS 2" [V55].
- moza-rev adds two notes:
  - restart the game so the setting applies;
  - "5 ≈ 120 Hz is plenty" [C6].

**PC3.** Options > System, reached from the main screen and not the pause menu. Protocol "Project CARS 2" or "Project
CARS 1" [V6].

### 3.3 Receiving on the Mac

- **Socket.** Bind UDP `0.0.0.0:5606`. pitwall's `UdpListener` already binds `0.0.0.0` by default
  (`src/pitwall/ingest/sources.py`). A socket bound to the wildcard address receives limited-broadcast datagrams for its
  port. `SO_BROADCAST` is only needed for sending. Confirm with `tcpdump -n -i en0 udp port 5606` during the first
  capture.
- **Same L2 segment.** A limited broadcast is not routed, so the Mac must be on the same L2 segment as the
  console or PC [GC].
- **Interfaces.** The console sometimes sends on the wrong interface (LAN vs Wi-Fi) [V4].
- **Dedicated listener.** Give port 5606 its own listener and pin the adapter to it. Do not rely on `PacketRouter`
  auto-detection alone. No pcars2 size collides with any F1 25 size (pitwall's `PACKET_SIZES`), Forza, GT7 or AC size,
  but the type byte alone is a weak signature.
- **Same-host capture only (Linux).** Linux does not loop limited broadcast back to local sockets. moza-rev's
  workaround is an iptables DNAT to 127.0.0.1 [C6]. This does not affect pitwall, because the game always runs on
  another host.

### 3.4 Reliability (main risk)

- **Vendor warnings.**
  - SIM Dashboard calls the console interface "slow, unreliable" and warns it can affect "the whole local network"
    [V4].
  - Broadcasts are "much slower than normal data packets" [V7].
  - Advice: use 5 GHz Wi-Fi; disable router UDP-flood, DoS and multicast-flood protection; use a medium UDP Frequency
    [V7].
  - RS Dash gives the same router advice [V30].
- **Crew Chief.**
  - Crew Chief's PC2 network mode is disabled pending "when it actually works" [C9-G].
  - Its reader's out-of-sequence check is a stub that always returns false [C9-R].
  - Its merge code has unresolved TODOs (§6). Treat Crew Chief as a mirror of struct text, **not** as a validated
    decoder.
- **Positive evidence.** PS4 + PC wired over Ethernet ran a motion rig with the PC2 format (2019-02-13) [F4]. AMS2 on
  PC feeds a 2026 LED controller [C6].
- **Pitwall must measure:**
  - per-type packet rate;
  - loss, using `mCategoryPacketNumber` gaps (§4.1);
  - jitter, on wired and Wi-Fi console links;
  - the rate per UDP Frequency setting.

### 3.5 Update rates

These are from the header comments [C10-T]. No source gives a Hz table for the UDP Frequency setting.

| Packet | When sent |
|---|---|
| 0 Telemetry | every tick of the UDP streamer (the UDP Frequency option), in race |
| 3 Timings | every tick, in race |
| 1 Race definition | "logarithmic decrease"; counter resets on entering InRace and whenever a value changes |
| 2 Participants | logarithmic decrease; resets on entering InRace and when participants change |
| 8 Vehicle / class names | logarithmic decrease. At least 2 packets: 1..n-1 carry vehicle names, the last carries class names |
| 4 Game state | every 5 s in menus, every 10 s in race (up to every 5 s with fast weather), and several times on menu ↔ race changes. Always sent |
| 7 Time stats | on entering race and on any change, so roughly at every sector crossing by any car |
| 5 Weather, 6 Vehicle names | "not sent at the moment" |

The only rate figure in any source is "UDP Frequency 5 ≈ 120 Hz" for AMS2 [C6]. Console figures are unknown. Start
the listener **before** entering a session, so the front-loaded definition and participant packets are caught.

### 3.6 Wrong-protocol pitfall: "Project CARS 1" format

- **All three games also offer a "Project CARS 1" UDP format** [V4][V6]. RS Dash even tells users to pick it [V30][V32].
- **The PC1 format is a different protocol.** It has a 3-byte header (u16 build version, u8 type | sequence << 2) and
  a 1367-byte telemetry packet with `sSpeed` at offset 120 [C32].
- **AMS2 can emit it.** The Reiza forum user who found "speed (m/s) at offset 0x078" (= 120) in AMS2 was almost
  certainly receiving PC1-format packets [F6][C32]. The post does not say which protocol was selected.
- **Pitwall must detect and explain this, not decode it.** Datagrams of 1367 / 1347 / 1028 bytes with `byte[2] & 3` in
  {0, 1, 2} [C32] should raise a Connect-tab hint: *"set UDP Protocol Version to Project CARS 2"*.

---

## 4. Framing, validation and dispatch

### 4.1 Common header (all packet types) [C10-T][C10-M][C9-S][C6][C30]

Endianness is **little-endian**. Every community decoder reads little-endian: tyretrack `<`, moza-rev `repr(C, packed)`
on x86, Crew Chief `BitConverter` on x86, the tm-bt-led `le` parsers [C33][C6][C9-R][C34]. The sending platforms (x86
PC, PS4/XB1 x86-64) are little-endian. Confirm on the first console capture.

<!-- layout:pcars2_header size=12 -->
| Off | Size | Type | Field | Meaning |
|---|---|---|---|---|
| 0 | 4 | u32 | mPacketNumber | counter over **all** packets sent during the game run |
| 4 | 4 | u32 | mCategoryPacketNumber | counter per category (packet type): use it for per-type loss and reorder detection |
| 8 | 1 | u8 | mPartialPacketIndex | index when one logical packet is split over several datagrams (participants, vehicle names). Crew Chief treats it as 1-based (`(index - 1) * 16`) [C9-M] (**?**) |
| 9 | 1 | u8 | mPartialPacketNumber | total datagrams in the split |
| 10 | 1 | u8 | mPacketType | `EUDPStreamerPacketHandlerType` (§4.2) |
| 11 | 1 | u8 | mPacketVersion | handler version, "to be bumped with data structure change" [C10-T]. Unreliable in practice [C34] |

### 4.2 Packet types [C10-T][C9-E]

| Value | Name | Sent? |
|---|---|---|
| 0 | eCarPhysics (telemetry) | yes |
| 1 | eRaceDefinition | yes |
| 2 | eParticipants | yes |
| 3 | eTimings | yes |
| 4 | eGameState | yes |
| 5 | eWeatherState | "not sent at the moment"; the data is in game state |
| 6 | eVehicleNames | "not sent at the moment" (MacManley labels 6 as class names [C30]; this contradicts the header) |
| 7 | eTimeStats | yes |
| 8 | eParticipantVehicleNames | yes; the final datagram of the series carries the class-name table |

### 4.3 Packing and why comments cannot be trusted

- **Packing.** `sTelemetryData` and `sTimingsData` (with `sParticipantInfo`) are declared under `#pragma pack(1)`.
  The other structs use default packing [C10-T].
  - For race data, participants, game state, time stats and class names, natural alignment gives the **same field
    offsets** as packed, apart from trailing padding (computed; §5).
  - The one exception is `sVehicleInfo` (§5.8).
- **Comments are wrong in places** (computed with Python `struct`, `<` = packed):
  - `sJoyPad0` is commented 376 but is at **373**.
  - `mGameState` is commented 15 but is at **14**. Every game-state comment from there on is off by one.
  - `sTimeStatsData::sPacketSize = 1024`, but the struct sums to **1040**.
- **Copied comment offsets cause real decode bugs.** tyretrack's v2 decoder reads:
  - `sTyreCarcassTemp` at 240 instead of 232;
  - `sEngineTorque` at 264 instead of 364;
  - `sJoyPad0` at 376;
  - game state at 15 [C33].
- **Pitwall rule.** Derive offsets from the type list with `StructDef`. Never transcribe comment offsets.

### 4.4 Size matrix and the revision story

| Type | [C10-T] (handler ver) | [C10-M]/[C10-S] (handler ver) | Crew Chief constants [C9-S] | moza-rev [C6] | MacManley [C30] |
|---|---|---|---|---|---|
| 0 Telemetry | **559** (v2) | 556 constant; fields sum to 555 (v2) | **538** | ≥ 559 required | 559 |
| 1 Race definition | 308 (v1) | 308 (v1) | 308 | — | 308 |
| 2 Participants | 1136 (v2) | 1136 (v2) | **1040** | — | 1136 |
| 3 Timings | **1063** (v3) | **1059** (v1) | **993** | — | 1063 |
| 4 Game state | 24 (v2) | 24 (v2) | 24 | — | 24 |
| 7 Time stats | constant 1024, fields 1040 (v2) | same | **784** | — | 1040 |
| 8 Vehicle names / class names | 1164 / 1452 (v2) | same | 1164 / 1452 | — | 1164 / 1452 |

**Reconciliation.** Arithmetic on each source's own fields explains every size.

- **Telemetry.**
  - 559 = 555 + `sTickCount` (u32).
  - 555 is the [C10-M] field list. Its 556 constant is one byte larger than its fields; the cause is unknown.
  - 538 = the shared prefix ending after `sTyreCompound` (378 + 160). That revision has no turbo, full-position,
    brake-bias or tick fields.
- **Timings.**
  - 1063 = 1059 + `sTickCount`.
  - 993 = 33 + 32 × **30**: participant records without `sMPParticipantIndex`, and no `sLocalParticipantIndex`.
- **Participants.** 1040 = 12 + 4 + 16 × 64: names only, with no nationality or index arrays.
- **Time stats.** 784 = 16 + 32 × **24**: six floats per car, with no online-rep or MP index.

**Interpretation (inference, not documented).** Crew Chief's constants describe the earliest layout. [C10-M] (dated
≤ 2018-03) is a middle revision. [C10-T] (2018-06) is the latest. Fields were appended over PC2 patches; the tm-bt-led
comment about "patch 4" fits this [C34].

- **AMS2:** moza-rev's ≥ 559 check suggests AMS2 sends 559-byte telemetry [C6]. This is consistent but not proof.
- **PC2 final console patch:** unknown.
- **PC3:** unknown.

### 4.5 Dispatch table (implement exactly this; extend only from captures)

| type | len | Layout | Confidence |
|---|---|---|---|
| 0 | 559 | `TELEMETRY_559` (§5.1, full) | primary [C10-T][C30]; AMS2-consistent [C6] |
| 0 | 556 or 555 | `TELEMETRY_559` fields up to and including `sBrakeBias` (offsets 0–554); ignore trailing bytes | [C10-M] (**?** whether ever sent) |
| 0 | 538 | **safe core only**: offsets 0–372. `sJoyPad`/`sDPad`/`sTyreCompound` offsets are ambiguous: Crew Chief's struct uses 2 one-byte joypad fields, which puts the compound at 376, against 378 in [C10-T] | [C9-S] (**?**) |
| 1 | 308 (accept 307) | `RACE_308` | all sources |
| 2 | 1136 | `PARTICIPANTS_1136` | [C10-T][C10-M][C30] |
| 2 | 1040 | `PARTICIPANTS_1040` (header + timestamp + 16 names) | inferred from [C9-S] (**?**) |
| 3 | 1063 | `TIMINGS_1063` (32-byte records) | [C10-T][C30] |
| 3 | 1059 | `TIMINGS_1059` (no tick count) | [C10-M] |
| 3 | 993 | `TIMINGS_993` (30-byte records, no local index) | inferred from [C9-S] (**?**) |
| 4 | 24 (accept 22) | `GAME_STATE_24` | all sources |
| 7 | 1040 | `TIME_STATS_1040` (32-byte records) | [C10-T][C30] |
| 7 | 784 | `TIME_STATS_784` (24-byte records) | inferred from [C9-S] (**?**) |
| 8 | 1164 | `VEHICLE_NAMES_1164` | all sources |
| 8 | 1452 | `CLASS_NAMES_1452` | all sources |
| 5, 6 | any | count as `ignored`, keep in capture | header says not sent |
| other | — | `PacketRejected("pcars2: type T len L not in layout table")`, counted by `"T:L"` key, kept in capture | — |

**Validation per datagram.**

1. `len ≥ 12`.
2. Apply the (type, len) table above.
3. Record `mPacketVersion` per type in `DecodeStats.by_type`, for example `"0:559:v2"`. **Do not reject on version**
   [C34].
   - Versions expected from [C10-T]: telemetry 2, race 1, participants 2, timings 3, game state 2, time stats 2,
     names 2.
   - [C10-M] gives timings version 1.
4. Telemetry plausibility (flag `DECODE_WARNING`, do not reject):
   - `sSpeed` finite and in 0–200 m/s;
   - `sMaxRpm` = 0 or `sRpm` ≤ 1.3 × `sMaxRpm`;
   - gear nibble ∈ {0..num_gears, 15};
   - `sViewedParticipantIndex` ∈ [-1, 31].
5. `can_decode()`: true only for an exact (type, len) match on types 0–4, 7 and 8.
6. PC1-format datagrams: §3.6.

---

## 5. Packet layouts

Field names follow the SMS identifiers so they can be cross-referenced. Types: `u8 i8 u16 i16 u32 f32 char[N]`;
`T[n]` is an array. Offsets are absolute (from datagram byte 0). Every table was recomputed with Python `struct` under
`<` (packed, little-endian) on 2026-10-10. Units and scaling are detailed in §7.

### 5.1 Telemetry, type 0: `sTelemetryData`, viewed car only

Source: [C10-T] (field order and types). The common prefix (0–372) is identical in [C10-M], [C9-S], [C6] and [C30].
The fields after it are listed in the layout column.

<!-- layout:pcars2_telemetry_559 size=559 -->
| Off | Size | Type | Field | Layout |
|---|---|---|---|---|
| 0 | 12 | header | sBase | all |
| 12 | 1 | i8 | sViewedParticipantIndex | all |
| 13 | 1 | u8 | sUnfilteredThrottle | all |
| 14 | 1 | u8 | sUnfilteredBrake | all |
| 15 | 1 | i8 | sUnfilteredSteering | all |
| 16 | 1 | u8 | sUnfilteredClutch | all |
| 17 | 1 | u8 | sCarFlags | all |
| 18 | 2 | i16 | sOilTempCelsius | all |
| 20 | 2 | u16 | sOilPressureKPa | all |
| 22 | 2 | i16 | sWaterTempCelsius | all |
| 24 | 2 | u16 | sWaterPressureKpa | all (MZ/MM use i16) |
| 26 | 2 | u16 | sFuelPressureKpa | all |
| 28 | 1 | u8 | sFuelCapacity | all |
| 29 | 1 | u8 | sBrake | all |
| 30 | 1 | u8 | sThrottle | all |
| 31 | 1 | u8 | sClutch | all |
| 32 | 4 | f32 | sFuelLevel | all |
| 36 | 4 | f32 | sSpeed | all |
| 40 | 2 | u16 | sRpm | all |
| 42 | 2 | u16 | sMaxRpm | all |
| 44 | 1 | i8 | sSteering | all |
| 45 | 1 | u8 | sGearNumGears | all |
| 46 | 1 | u8 | sBoostAmount | all |
| 47 | 1 | u8 | sCrashState | all |
| 48 | 4 | f32 | sOdometerKM | all |
| 52 | 12 | f32[3] | sOrientation | all |
| 64 | 12 | f32[3] | sLocalVelocity | all |
| 76 | 12 | f32[3] | sWorldVelocity | all |
| 88 | 12 | f32[3] | sAngularVelocity | all |
| 100 | 12 | f32[3] | sLocalAcceleration | all |
| 112 | 12 | f32[3] | sWorldAcceleration | all |
| 124 | 12 | f32[3] | sExtentsCentre | all |
| 136 | 4 | u8[4] | sTyreFlags | all |
| 140 | 4 | u8[4] | sTerrain | all |
| 144 | 16 | f32[4] | sTyreY | all |
| 160 | 16 | f32[4] | sTyreRPS | all |
| 176 | 4 | u8[4] | sTyreTemp | all |
| 180 | 16 | f32[4] | sTyreHeightAboveGround | all |
| 196 | 4 | u8[4] | sTyreWear | all |
| 200 | 4 | u8[4] | sBrakeDamage | all |
| 204 | 4 | u8[4] | sSuspensionDamage | all |
| 208 | 8 | i16[4] | sBrakeTempCelsius | all |
| 216 | 8 | u16[4] | sTyreTreadTemp | all |
| 224 | 8 | u16[4] | sTyreLayerTemp | all |
| 232 | 8 | u16[4] | sTyreCarcassTemp | all |
| 240 | 8 | u16[4] | sTyreRimTemp | all |
| 248 | 8 | u16[4] | sTyreInternalAirTemp | all |
| 256 | 8 | u16[4] | sTyreTempLeft | all |
| 264 | 8 | u16[4] | sTyreTempCenter | all |
| 272 | 8 | u16[4] | sTyreTempRight | all |
| 280 | 16 | f32[4] | sWheelLocalPositionY | all |
| 296 | 16 | f32[4] | sRideHeight | all |
| 312 | 16 | f32[4] | sSuspensionTravel | all |
| 328 | 16 | f32[4] | sSuspensionVelocity | all |
| 344 | 8 | u16[4] | sSuspensionRideHeight | all |
| 352 | 8 | u16[4] | sAirPressure | all |
| 360 | 4 | f32 | sEngineSpeed | all |
| 364 | 4 | f32 | sEngineTorque | all |
| 368 | 2 | u8[2] | sWings | all |
| 370 | 1 | u8 | sHandBrake | all |
| 371 | 1 | u8 | sAeroDamage | all |
| 372 | 1 | u8 | sEngineDamage | all (**end of safe core**) |
| 373 | 4 | u32 | sJoyPad0 | 555/559 (Crew Chief 538: two u8 at 373, 374) |
| 377 | 1 | u8 | sDPad | 555/559 (Crew Chief 538: 375) |
| 378 | 160 | char[4][40] | sTyreCompound | 555/559 (Crew Chief 538: 376) |
| 538 | 4 | f32 | sTurboBoostPressure | 555/559 |
| 542 | 12 | f32[3] | sFullPosition | 555/559 |
| 554 | 1 | u8 | sBrakeBias | 555/559 |
| 555 | 4 | u32 | sTickCount | 559 only |

Wheel order in every `[4]` array is presumed to be FL, FR, RL, RR, for two reasons:

- the shared-memory enum is `TYRE_FRONT_LEFT = 0, TYRE_FRONT_RIGHT, TYRE_REAR_LEFT, TYRE_REAR_RIGHT` [C31];
- Crew Chief names the four compound slots lf, rf, lr, rr [C9-S].

The UDP header itself does not say (**?**; §12.3). Use `Wheels.from_fl_fr_rl_rr`.

### 5.2 Race definition, type 1: `sRaceData` [C10-T][C9-S][C30]

<!-- layout:pcars2_race_308 size=308 -->
| Off | Size | Type | Field |
|---|---|---|---|
| 0 | 12 | header | sBase |
| 12 | 4 | f32 | sWorldFastestLapTime |
| 16 | 4 | f32 | sPersonalFastestLapTime |
| 20 | 4 | f32 | sPersonalFastestSector1Time |
| 24 | 4 | f32 | sPersonalFastestSector2Time |
| 28 | 4 | f32 | sPersonalFastestSector3Time |
| 32 | 4 | f32 | sWorldFastestSector1Time |
| 36 | 4 | f32 | sWorldFastestSector2Time |
| 40 | 4 | f32 | sWorldFastestSector3Time |
| 44 | 4 | f32 | sTrackLength |
| 48 | 64 | char[64] | sTrackLocation |
| 112 | 64 | char[64] | sTrackVariation |
| 176 | 64 | char[64] | sTranslatedTrackLocation |
| 240 | 64 | char[64] | sTranslatedTrackVariation |
| 304 | 2 | u16 | sLapsTimeInEvent |
| 306 | 1 | i8 | sEnforcedPitStopLap |
| 307 | 1 | pad | (struct alignment; MacManley names it `paddingA` [C30]) |

### 5.3 Participants, type 2: `sParticipantsData` (16 per datagram, split over 2 partials for 32 cars) [C10-T][C30]

<!-- layout:pcars2_participants_1136 size=1136 -->
| Off | Size | Type | Field |
|---|---|---|---|
| 0 | 12 | header | sBase |
| 12 | 4 | u32 | sParticipantsChangedTimestamp |
| 16 | 1024 | char[16][64] | sName |
| 1040 | 64 | u32[16] | sNationality |
| 1104 | 32 | u16[16] | sIndex (session-unique index for MP) |

The 1040-byte variant (inferred from [C9-S]) ends after `sName`.

### 5.4 Timings, type 3: `sTimingsData` (pack 1) [C10-T][C30]

<!-- layout:pcars2_timings_1063 size=1063 -->
| Off | Size | Type | Field |
|---|---|---|---|
| 0 | 12 | header | sBase |
| 12 | 1 | i8 | sNumParticipants |
| 13 | 4 | u32 | sParticipantsChangedTimestamp |
| 17 | 4 | f32 | sEventTimeRemaining |
| 21 | 4 | f32 | sSplitTimeAhead |
| 25 | 4 | f32 | sSplitTimeBehind |
| 29 | 4 | f32 | sSplitTime |
| 33 | 1024 | sParticipantInfo[32] | sPartcipants (sic in header); record stride 32 |
| 1057 | 2 | u16 | sLocalParticipantIndex |
| 1059 | 4 | u32 | sTickCount (absent in the 1059 variant) |

`sParticipantInfo` record (offsets relative to the record start; record i is at `33 + 32*i`):

<!-- layout:pcars2_participant_info size=32 -->
| Off | Size | Type | Field |
|---|---|---|---|
| 0 | 6 | i16[3] | sWorldPosition |
| 6 | 6 | i16[3] | sOrientation (quantised heading −π..π, pitch −π/2..π/2, bank −π..π [C10-T]; scale factor **?**) |
| 12 | 2 | u16 | sCurrentLapDistance |
| 14 | 1 | u8 | sRacePosition (bit 7 = active) |
| 15 | 1 | u8 | sSector (sector + extra x/z precision bits) |
| 16 | 1 | u8 | sHighestFlag (colour + reason) |
| 17 | 1 | u8 | sPitModeSchedule (pit mode + schedule) |
| 18 | 2 | u16 | sCarIndex ("top bit" = human) |
| 20 | 1 | u8 | sRaceState (race state + lap-invalidated) |
| 21 | 1 | u8 | sCurrentLap |
| 22 | 4 | f32 | sCurrentTime |
| 26 | 4 | f32 | sCurrentSectorTime |
| 30 | 2 | u16 | sMPParticipantIndex (matches participants `sIndex`) |

The 993-byte variant is inferred to use the same first 30 bytes per record, stride 30, with no
`sLocalParticipantIndex` (**?**).

### 5.5 Game state, type 4: `sGameStateData` [C10-T][C30]

<!-- layout:pcars2_game_state_24 size=24 -->
| Off | Size | Type | Field |
|---|---|---|---|
| 0 | 12 | header | sBase |
| 12 | 2 | u16 | mBuildVersionNumber |
| 14 | 1 | u8 | mGameState (game state + session state; §6) |
| 15 | 1 | i8 | sAmbientTemperature |
| 16 | 1 | i8 | sTrackTemperature |
| 17 | 1 | u8 | sRainDensity |
| 18 | 1 | u8 | sSnowDensity (non-zero only in snow season) |
| 19 | 1 | i8 | sWindSpeed |
| 20 | 1 | i8 | sWindDirectionX |
| 21 | 1 | i8 | sWindDirectionY |
| 22 | 2 | pad | (struct alignment; `paddingD` [C30]) |

### 5.6 Types 5 and 6

These are declared but "not sent at the moment" [C10-T]. No layout is published. Crew Chief logs them as "undocumented"
if seen [C9-R].

### 5.7 Time stats, type 7: `sTimeStatsData` [C10-T][C30]

<!-- layout:pcars2_time_stats_1040 size=1040 -->
| Off | Size | Type | Field |
|---|---|---|---|
| 0 | 12 | header | sBase |
| 12 | 4 | u32 | sParticipantsChangedTimestamp |
| 16 | 1024 | sParticipantStatsInfo[32] | sStats; record stride 32 |

<!-- layout:pcars2_participant_stats size=32 -->
| Off | Size | Type | Field |
|---|---|---|---|
| 0 | 4 | f32 | sFastestLapTime |
| 4 | 4 | f32 | sLastLapTime |
| 8 | 4 | f32 | sLastSectorTime |
| 12 | 4 | f32 | sFastestSector1Time |
| 16 | 4 | f32 | sFastestSector2Time |
| 20 | 4 | f32 | sFastestSector3Time |
| 24 | 4 | u32 | sParticipantOnlineRep (u16 rank type + u16 strength; 0 in SP) |
| 28 | 2 | u16 | sMPParticipantIndex |
| 30 | 2 | pad | (`paddingB` [C30]) |

The 784-byte variant is inferred to have only the six floats per record (stride 24) (**?**).

### 5.8 Vehicle names and class names, type 8 [C10-T][C9-S][C30]

**Vehicle names.**

<!-- layout:pcars2_vehicle_names_1164 size=1164 -->
| Off | Size | Type | Field |
|---|---|---|---|
| 0 | 12 | header | sBase |
| 12 | 1152 | sVehicleInfo[16] | sVehicles; record stride 72 |

The `sVehicleInfo` record is **ambiguous**, because the struct is outside `pack(1)` and the header comments read as
if it were packed:

| Interpretation | sIndex | sClass (u32) | sName (char[64]) | Pad |
|---|---|---|---|---|
| A. natural alignment (C default, matches the struct's declared packing) | 0 (u16) | **4** | **8** | none |
| B. packed + 2 trailing pad bytes (header comment offsets; MacManley [C30]) | 0 (u16) | **2** | **6** | 70–71 |

Settle it on the first capture: for a populated slot, the first name byte is printable ASCII at record+8 (A) or at
record+6 (B). Implement both behind a layout flag until then.

**Class names.**

<!-- layout:pcars2_class_names_1452 size=1452 -->
| Off | Size | Type | Field |
|---|---|---|---|
| 0 | 12 | header | sBase |
| 12 | 1440 | sClassInfo[60] | sClasses; record stride 24: `u32 sClassIndex` @0, `char[20] sName` @4 |

`sVehicleInfo.sClass` presumably indexes `sClasses[].sClassIndex` (**?**). Crew Chief leaves class names unmapped:
"TODO: understand this data and map it" [C9-M].

---

## 6. Bit-fields: sources disagree, so decode provisionally

| Byte | SMS PC2 header comment [C10-T] | SMS PC1 packer pseudocode [C32] | Crew Chief [C9-M] | tyretrack v2 [C33] | **Pitwall provisional** |
|---|---|---|---|---|---|
| game state `mGameState` (@14) | "first 3 bits" game state, "second 3 bits" session state | `game \| session << 4` | game `& 7`, session `>> 4` | game `& 7`, session `>> 3` (and reads @15) | game = `b & 7`, session = `(b >> 4) & 7`; mark UNVERIFIED |
| `sHighestFlag` | "(enum 3 bits/enum 2 bits)" colour, reason | `colour \| reason << 4` | colour `& 28`, reason `& 3` (no shift) | colour `& 0x0F`, reason `>> 4` | colour = `b & 0x0F`, reason = `(b >> 4) & 3` |
| `sPitModeSchedule` | "(enum 3 bits/enum 2 bits)" mode, schedule | `mode \| schedule << 4` | mode `& 28`, schedule `& 3` | mode `& 0x0F`, schedule `>> 4` | mode = `b & 0x0F`, schedule = `b >> 4` |
| `sRaceState` | "race state flags + invalidated lap indication" | PC1 `sRaceStateFlags = state \| lapInvalid·8 \| ABS·16 \| boost·32` | state `& 127`, invalid = bit 7 | state `& 7`, invalid = bit 3 | state = `b & 7`; lap-invalid **unknown bit** (3 or 7), decide by capture |
| `sSector` | "sector + extra precision bits for x/z" | PC1: `sector \| x_q << 6 \| z_q << 4`, `q = floor(pos·4) & 3` | sector `& 7`, x `>> 6 & 3`, z `>> 4 & 3` | sector `& 3`, same x/z | sector = `b & 7`; x_frac = `((b >> 6) & 3) / 4`, z_frac = `((b >> 4) & 3) / 4` |
| `sRacePosition` | position + top bit active | `pos \| active·128` | `& 127`, bit 7 | `& 0x7F` | position = `b & 0x7F`; active = `b >> 7` |
| `sCarIndex` (u16) | "top bit" human | — | `>> 7`, `& 127` (byte semantics) | `& 0x7FFF`, `0x8000` | human = `v >> 15`; index = `v & 0x7FFF` |
| `sLapsTimeInEvent` (u16) | top bit 1 = timed; else laps; timed value = number of 5-minute blocks | — | `/2`, and the meaning appears inverted (code comment: "is it valid to just halve it?") | `& 0x8000` → `5 × (v & 0x7FFF)` minutes, else laps | timed = `v >> 15`; n = `v & 0x7FFF`; laps = n, or duration = 300·n s |
| `sGearNumGears` | — | `gear \| numGears << 4`; reverse = `0x0F` | `& 15`, `>> 4` | — | gear = low nibble (15 → −1 R, 0 → N); gears = high nibble [C6] |

**Rationale.**

- **The PC1 packer pseudocode is the only SMS-authored code** showing how these bytes are built [C32]. The PC2 header
  comments agree with it on which fields share a byte, though not on widths. For example, the colour enum has 12
  values and cannot fit in "3 bits" [C9-E][C31].
- **The x/z extra-precision bits for negative coordinates are lossy.** PC1 casts the integer part with `(s16)`, which
  truncates toward zero, but builds the fraction from `floor(pos·4)` [C32]. So `int16 + frac/4` is exact only for
  positive coordinates. For negative non-integer coordinates the error can reach about 1 m.
  - Use `sFullPosition` for the player.
  - Accept about 1 m error for other cars.
  - (This is pitwall's derivation from the pseudocode; confirm with a capture.)

**Enums** (values from the SMS shared-memory header [C31], mirrored under MIT in [C9-E]):

- **Game state:**
  - 0 EXITED;
  - 1 FRONT_END;
  - 2 INGAME_PLAYING;
  - 3 INGAME_PAUSED;
  - 4 INGAME_INMENU_TIME_TICKING;
  - 5 INGAME_RESTARTING;
  - 6 INGAME_REPLAY;
  - 7 FRONT_END_REPLAY.
- **Session state:** 0 INVALID, 1 PRACTICE, 2 TEST, 3 QUALIFY, 4 FORMATION_LAP, 5 RACE, 6 TIME_ATTACK.
- **Race state:** 0 INVALID, 1 NOT_STARTED, 2 RACING, 3 FINISHED, 4 DISQUALIFIED, 5 RETIRED, 6 DNF.
- **Flag colour:**
  - 0 NONE;
  - 1 GREEN;
  - 2 BLUE;
  - 3 WHITE_SLOW_CAR;
  - 4 WHITE_FINAL_LAP;
  - 5 RED;
  - 6 YELLOW;
  - 7 DOUBLE_YELLOW;
  - 8 BLACK_AND_WHITE;
  - 9 BLACK_ORANGE_CIRCLE;
  - 10 BLACK;
  - 11 CHEQUERED.
- **Flag reason:** 0 NONE, 1 SOLO_CRASH, 2 VEHICLE_CRASH, 3 VEHICLE_OBSTRUCTION.
- **Pit mode:**
  - 0 NONE;
  - 1 DRIVING_INTO_PITS;
  - 2 IN_PIT;
  - 3 DRIVING_OUT_OF_PITS;
  - 4 IN_GARAGE;
  - 5 DRIVING_OUT_OF_GARAGE.
- **Pit schedule:**
  - 0 NONE;
  - 1 PLAYER_REQUESTED;
  - 2 ENGINEER_REQUESTED;
  - 3 DAMAGE_REQUESTED;
  - 4 MANDATORY;
  - 5 DRIVE_THROUGH;
  - 6 STOP_GO;
  - 7 PITSPOT_OCCUPIED.
- **Car flags (bits):** 0 headlight, 1 engine active, 2 engine warning, 3 speed limiter, 4 ABS, 5 handbrake.
- **Tyre flags (bits):** 0 attached, 1 inflated, 2 on ground.
- **Crash state:** 0 NONE, 1 OFFTRACK, 2 LARGE_PROP, 3 SPINNING, 4 ROLLING.
- **Terrain:** 0 ROAD … see [C9-E] (AMS2/PC2 lists may differ; display only).

---

## 7. Units and scaling

**Base units** come from the SMS shared-memory header for the matching `m`-field [C31]. **Wire scaling** comes from
the SMS PC1 packer [C32] where it exists, and from community decoders otherwise.

| Field (wire type) | Model value | Unit / range | Evidence | Confidence |
|---|---|---|---|---|
| sUnfilteredThrottle / Brake / Clutch (u8) | `v / 255` | 0..1 | PC1 `clamp(0,1) × 255` [C32]; Crew Chief `/255` [C9-M] | high |
| sUnfilteredSteering, sSteering (i8) | `v / 127` | −1..+1; sign **?** | PC1 `× 127` [C32] | high (scale), **?** (direction) |
| sThrottle / sBrake / sClutch (u8) | `v / 255` | 0..1, after assists | [C32][C9-M] | high |
| sSpeed (f32) | `× 3.6` → kph | m/s | [C31][C6] | high |
| sRpm, sMaxRpm (u16) | as is | rpm | [C31] | high |
| sGearNumGears (u8) | §6 | — | [C32][C6] | high |
| sFuelLevel (f32) | fraction of capacity | 0..1 | [C31]; moza-rev displays `× 100 %` [C6] | high |
| sFuelCapacity (u8) | litres | L (integer) | [C31] "Liters"; PC1 `(u8)` cast [C32] | medium |
| sOilTempCelsius, sWaterTempCelsius (i16) | °C | °C | [C31][C32] | high |
| sOil/Water/FuelPressure (u16) | kPa | kPa | [C31][C32] | high |
| sBoostAmount (u8) | as is | 0..100 | [C31][C32] | medium |
| sOdometerKM (f32) | km | km | field name, [C31] | high |
| sOrientation (f32[3]) | radians, Euler | rotation order not documented. Crew Chief's note: data "appears" pitch-yaw-roll [C9-M] | [C31][C9-M] | **?** order and signs |
| sLocalVelocity, sWorldVelocity (f32[3]) | m/s | m/s | [C31] | high |
| sAngularVelocity (f32[3]) | rad/s | rad/s | [C31] | high |
| sLocalAcceleration, sWorldAcceleration (f32[3]) | `/ 9.80665` → g | header says "Metres per-second"; values must be m/s² (**?** confirm magnitude) | [C31] | medium; axis signs **?** |
| sTyreTemp (u8) | °C | °C, clamped 0..255 | [C31][C32] | medium |
| sTyreWear, sBrakeDamage, sSuspensionDamage, sAeroDamage, sEngineDamage (u8) | `v / 255` | 0..1 | PC1 `× 255` [C32]; [C9-M] | high |
| sBrakeTempCelsius (i16) | °C | °C | [C31][C32] | high |
| sTyreTreadTemp / Layer / Carcass / Rim / InternalAir (u16) | `v − 273.15` → °C | **Kelvin** (SHM float), integer-cast in PC1 | [C31][C32] | medium; confirm range ≈ 290–400 |
| sTyreTempLeft / Center / Right (u16) | **?** | not in shared memory v9; likely same unit as tread temperature | [C10-T] | **?** |
| sAirPressure (u16) | **?** | SHM is PSI float [C31]; PC1 casts float → u16, which would be whole PSI [C32]. The PC2 quantisation is unknown | — | **?**: compare with the in-game pressure display |
| sSuspensionTravel (f32[4]) | m | m | [C31] | high |
| sRideHeight (f32), sSuspensionRideHeight (u16) | **?** | not in SHM v9 | — | **?** |
| sEngineSpeed (f32) / sEngineTorque (f32) | rad/s / N·m | | [C31] | high |
| sWings (u8[2]), sHandBrake (u8) | **?** (`/255`?) | SHM 0..1 | [C31]; PC1 casts float → u8 for wings [C32] | **?** |
| sTyreCompound (char[4][40]) | string, NUL-terminated | car-specific names | [C10-T][C31] | high |
| sTurboBoostPressure (f32) | **?** | SHM range 0..1 | [C31] | **?** |
| sFullPosition (f32[3]) | m, world | "full precision" position of the viewed car | [C10-T][C31] | high (metres presumed: world space) |
| sBrakeBias (u8) | **?** (`/255` front fraction?) | "quantized"; SHM 0..1 | [C10-T][C31] | **?**: compare with the in-game bias |
| sTickCount (u32) | monotonic id only | unit undocumented | [C10-T] | **?** |
| sCurrentLapDistance (u16) | m | metres, truncated, capped at 65535 | [C31]; PC1 `(u16)min(d, 65535)` [C32] | high |
| sWorldPosition (i16[3]) + sSector bits | m | §6 | [C32] | medium |
| sCurrentTime, sCurrentSectorTime, all lap and sector times (f32) | `× 1000` → ms | seconds; −1 or 0 when unset per SHM | [C31] | high |
| sEventTimeRemaining (f32) | **?** | "−1 invalid; −1 − laps remaining in lap-based races" [C10-T]; the SHM equivalent is milliseconds [C31] | — | **?** units in timed sessions |
| sTrackLength (f32) | m | m | [C31] | high |
| sAmbientTemperature, sTrackTemperature (i8) | °C | °C | [C31][C32] | high |
| sRainDensity, sSnowDensity (u8) | `/ 255` | 0..1 | PC1 `× 255` [C32] | medium |
| sWindSpeed (i8) | **?** | PC1 packs `speed × 0.5` [C32] | — | low |

---

## 8. Mapping to pitwall's model

**Adapter shape.**

- Module: `src/pitwall/adapters/pcars2/` (`packets.py` StructDefs built from §5; `adapter.py`).
- The adapter is pure (no I/O).
- It keeps per-session state:
  - the latest timings, race definition, game state, time stats, and the participant / vehicle-name tables;
  - all keyed by `sParticipantsChangedTimestamp`, so tables from different participant sets are never mixed.
- `AdapterInfo.ground_plane = ("pos_x_m", "pos_z_m")`. Y is "up": shared memory describes wheel and tyre heights in
  "Local Space Y" [C31], and the extra-precision bits exist only for x and z [C10-T][C32]. Confirm with a capture
  (y should stay nearly constant on a flat track).

**Game identity.** No packet names the title. `mBuildVersionNumber` exists, but its ranges per title are unknown
[C10-T].

- Add `Game.PCARS2`, `Game.AMS2` and `Game.PCARS3`.
- Take the title, and the platform, from a Connect-tab setting for the 5606 listener.
- Store `build_version` in `SessionInfo.extra`.
- Do not guess the title from track names.

### 8.1 CarFrame, emitted per telemetry datagram

Each telemetry packet is merged with the latest timings record of the viewed car. "Viewed car" means record index
`sViewedParticipantIndex`, the index Crew Chief uses [C9-M] (**?** that it indexes the timings array; §12.3).

| CarFrame field | Source | Notes |
|---|---|---|
| game, t_recv_ns | listener setting, ingest | |
| session_time_s | **None** | no session clock in the protocol |
| frame_id | telemetry `mCategoryPacketNumber` | monotonic per type. `sTickCount` exists only at 559 bytes, unit unknown |
| throttle / brake / clutch | `sUnfiltered*` / 255 | the driver's pedal input. Filtered values (after assists) go in a debug extra only |
| steering | `sUnfilteredSteering` / 127 | sign **?** until §12.3 |
| speed_kph | `sSpeed × 3.6` | |
| gear | low nibble; 15 → −1 | |
| rpm, max_rpm | `sRpm`, `sMaxRpm` | |
| drs_open, ers_* | None | not in the protocol |
| pos_x/y/z_m | `sFullPosition` (555/559); else timings `sWorldPosition` + x/z fraction bits | flag the lower precision via the FieldSupport source |
| vel_x/y/z_mps | `sWorldVelocity` | |
| g_lat / g_lon / g_vert | `sLocalAcceleration / 9.80665` | axis mapping and signs **?** (capture: hard braking, steady left turn) |
| yaw / pitch / roll_rad | `sOrientation` | order **?** |
| lap_number | timings `sCurrentLap` of the viewed car | 0- or 1-based **?** (SHM range "0->..." [C31]) |
| lap_distance_m | timings `sCurrentLapDistance` + **derived** interpolation (§8.4) | the raw value is integer metres at the timings rate |
| total_distance_m | None | |
| current_lap_time_ms | timings `sCurrentTime × 1000` | stale between timings packets: set `STALE_LAP_DATA` past 2 × the observed timings period |
| last_lap_time_ms | time stats `sLastLapTime` (viewed car) × 1000 | |
| sector | timings `sSector & 7` minus the observed base | sector numbering base **?** (Crew Chief treats 1..3 as S1..S3 [C9-M]; SHM unset is −1 [C31]) |
| lap_invalid | race-state lap-invalid bit | bit **?** (§6) |
| pit_status | pit mode: 0 → 0; 1, 3, 5 → 1; 2, 4 → 2 | pitwall's mapping decision. IN_GARAGE also sets `NOT_RACING` |
| race_position | `sRacePosition & 0x7F` | |
| tyre_surface_temp_c | `sTyreTemp` (°C) | or the tread temperature in K − 273.15. Choose after the capture |
| tyre_inner_temp_c | `sTyreCarcassTemp − 273.15` | units **?** |
| tyre_pressure_psi | **None until quantisation is confirmed** | §7 |
| brake_temp_c | `sBrakeTempCelsius` | |
| tyre_wear_pct | `sTyreWear / 255 × 100` | 0 = new [C31] |
| tyre_compound | `sTyreCompound[FL]` raw string | do not normalise to soft/medium/hard: names are car-specific |
| fuel_litres | **derived** `sFuelLevel × sFuelCapacity` | mark derived. Capacity is an integer number of litres |
| fuel_capacity_litres | `sFuelCapacity` | |
| fuel_kg, fuel_remaining_laps_game | None | |
| brake_bias_front_pct | None until scale confirmed | |
| abs_active | `sCarFlags` bit 4 | the SHM flag means "ABS" [C31]; whether it means active or fitted is **?** |
| quality | `PAUSED` if game state ∈ {3, 4}; `REPLAY_OR_SPECTATING` if game state ∈ {6, 7}; `NOT_RACING` if pit mode is IN_GARAGE or race state ∈ {3..6}; `STALE_LAP_DATA` as above | game-state decode **?** (§6) |

### 8.2 SessionInfo

Emitted on a race-definition change, a game-state session change, or a participants-timestamp change.

| Field | Source |
|---|---|
| track_id | `"<game>:" + sTrackLocation + "/" + sTrackVariation`, raw bytes up to NUL, decoded UTF-8 with replacement. These are the **untranslated** names [C31], so they are stable across UI languages. Crew Chief makes the text encoding user-configurable [C9-M], so keep the raw bytes in `extra` |
| track_name | `sTranslatedTrackLocation` + `sTranslatedTrackVariation` (display) |
| track_length_m | `sTrackLength` |
| session_type | session-state enum: PRACTICE, TEST → practice; QUALIFY → qualifying; FORMATION_LAP, RACE → race; TIME_ATTACK → time_trial; else unknown. Keep the raw value in `session_type_raw` |
| total_laps | `sLapsTimeInEvent` when not timed (§6) |
| session_time_left_s | `sEventTimeRemaining` only in timed sessions, after the units are confirmed |
| car_name | vehicle-names table for the viewed car (§5.8 ambiguity) |
| weather | `track_temp_c`, `air_temp_c`, `rain_percentage = sRainDensity / 255 × 100`. `condition` stays None: the protocol has no condition label |
| platform | Connect-tab setting |
| extra | `build_version`, the enforced pit-stop lap, world and personal fastest laps and sectors (s), snow density, wind |

### 8.3 LapCompletion and events

- **LapCompletion.** Emit it when the viewed car's `sCurrentLap` increments.
  - **lap_time_ms:** that car's `sLastLapTime` from the **next** time-stats packet, which is sent on every sector
    crossing [C10-T]. Wait up to about 3 s; otherwise `None`.
  - **sector_times_ms:**
    - S1 and S2 come from `sLastSectorTime` captured after each of the viewed car's sector changes.
    - S3 is the last sector time at the lap change, or `lap − S1 − S2`, labelled derived.
  - **valid:** NOT (lap-invalid bit seen during the lap).
  - Cross-check `lap_time_ms` against the timings `sCurrentTime` just before the wrap.
- **GameEvents.** The protocol has no event stream. Derive these from state edges:
  - PIT_ENTRY / PIT_EXIT from pit-mode transitions;
  - SESSION_STARTED / SESSION_ENDED from game and session state;
  - CHEQUERED_FLAG from flag colour 11.
- **Lap times.** Never fabricate a lap time from local timing when the game value is missing.

### 8.4 Lap distance: raw and derived

- **Raw value.** `sCurrentLapDistance` is integer metres, truncated, sent only with timings packets. It is shared by all
  32 cars [C10-T][C32].
- **Derived value.** Between timings packets, add `sSpeed × Δt` from the telemetry frames, re-anchored on every
  timings packet and clamped to `sTrackLength`. Expose it with
  `FieldSupport(source="derived: timings sCurrentLapDistance + ∫sSpeed dt")`.
- **Track model.** Once pitwall's track model has learnt a reference line from `sFullPosition`, prefer projecting the
  position onto that line. Use the raw value to anchor the start/finish line.
- **Behaviour before the first line crossing** (pit exit or out-lap) is **?**. Capture an out-lap.

### 8.5 Track knowledge (feeds L0a / L0b in `track-knowledge-sources.md`)

- **L0a, before the first lap:**
  - track location and variation strings (stable id);
  - track length;
  - world and personal best laps and sectors.
- **L0b, during the first minutes, learnt from up to 32 cars:**
  - centreline and map in the game frame, from `sWorldPosition` (≈ 0.25 m precision for x/z);
  - per-car `sCurrentLapDistance`, giving distance ↔ position;
  - **S2/S3 start distances**, learnt from `sSector` transitions against lap distance.
- **Not provided:** sector boundary distances, corner names, pit-lane geometry and pit speed limit. Crew Chief's MIT
  `trackLandmarksData.json` has AMS2 corner names (see `track-knowledge-sources.md`).

---

## 9. What is missing

- **No setup or car-tuning packet.** `CarSetup` is not available.
- **No session clock and no event stream.** Events must be derived (§8.3).
- **No DRS/ERS.** An AMS2 user notes that AMS2's shared memory has DRS state, "new to AMS2 and not in PCARS2"
  [F6]. UDP is expected to lack it (**?**).
- **No damage per panel beyond aero/engine/brake/suspension. No pit speed limit, sector distances or track map.**
- **Lap distance resolution.** 1 m resolution, at the timings rate, with no sub-metre data.
- **Units not yet confirmed:** tyre pressure quantisation, brake bias, wings and handbrake scale, turbo pressure, ride
  heights, left/centre/right tyre temperatures (§7).
- **No title or platform identifier** (§8).
- **Weather.** No precipitation type beyond rain/snow density, and no forecast.

---

## 10. Per-game differences

| Aspect | PC2 (console) | PC2 (PC) | AMS2 (PC) | PC3 (PC) |
|---|---|---|---|---|
| Layout revision | unknown; depends on the final patch (§4.4) | unknown | ≥ 559-byte telemetry implied [C6] | unknown |
| Alternative interface | none | shared memory | shared memory `$pcars2$` (`windows-shm-relay` in [GC]) | shared memory (PC2 format) [V32] |
| PC1-format option | yes [V4] | yes | yes (inferred from [F6]+[C32]) | yes [V6] |
| Reliability notes | broadcast is slow and fragile [V4][V7] | — | — | — |
| Store status | delisted [N3] | delisted [N3] | live | delisted; servers off 2026-02-24 [N3] |
| Extra data | — | — | DRS in shared memory only [F6] | — |
| Track ids | `pcars2:` namespace | `pcars2:` | `ams2:` | `pcars3:` |

Track and car names overlap between titles but are not guaranteed identical, so namespace per title.

---

## 11. Licence and implementation rights

- **No SMS licence.** Neither the SMS UDP header copies [C10-T][C10-M][C10-S] nor the shared-memory header [C31] grant
  a licence. The shared-memory header says "All rights reserved" [C31]. The tm-bt-led repository's MIT licence
  [C10-M] cannot relicense SMS's file. **Do not vendor these files or reproduce their comment text.**
- **Implementing from facts is in line with pitwall's existing rule** ("implemented from published specifications or
  community protocol documentation", `docs/licences.md`). Field order, types and enum values are interoperability
  facts. This document restates them in pitwall's own tables. This is a project-policy assessment, not legal advice.
- **MIT sources** (Crew Chief [C9-*], moza-rev [C6], MacManley [C30], tm-bt-led's own JS [C34]) may be read and cited.
  Pitwall copies no code from them, consistent with `docs/licences.md`. If any MIT text or code is ever reused, ship
  the MIT notice.
- **Unlicensed sources** (tyretrack `v2.py` [C33], `Readme.txt` [C32], saildeep [C10-S]): facts only.
- **Add to the `docs/licences.md` reviewed-repositories table when implementing:**
  - tyretrack/server (U);
  - saildeep/pcars2-udp (U);
  - mplutka/tm-bt-led (P: MIT, but the bundled SMS header is U);
  - Crew Chief (P);
  - crmne/moza-rev (P);
  - MacManley/project-cars-2-udp (P).

---

## 12. Test vectors and capture plan

### 12.1 Synthetic vectors (synthetic tier only; generate with pitwall's own `StructDef.pack`)

- **Header** for telemetry, packet #1000, category #500, partial 1/1, version 2:
  `e8 03 00 00 f4 01 00 00 01 01 00 02`. Partial-index base **?**.
- **Speed:** 50.0 m/s at offset 36 is `00 00 48 42`, expected 180.0 kph.
- **RPM:** 7500 at offset 40 is `4c 1d`, expected 7500.
- **Gear:** 3rd of 6 is `0x63` at offset 45, expected gear 3 / 6 gears. Reverse of 6 is `0x6f`, expected gear −1.
- **Unfiltered inputs:** bytes 13–16 = `ff 00 c0 00`, expected throttle 1.0, brake 0.0, steering −64/127 = −0.504,
  clutch 0.0.
- **Full position:** (−123.25, 4.5, 987.75) at offset 542 is `00 80 f6 c2 00 00 90 40 00 f0 76 44`.
- **Timings record 0 at offset 33** (32 bytes):

  ```text
  d2 04 05 00 c9 fd 00 00 00 00 00 00 d2 04 83 92 00 00 07 80 02 03 00 00 76 42 00 00 a2 41 00 00
  ```

  It encodes:
  - world (1234, 5, −567);
  - lap distance 1234 m;
  - position 3, active;
  - sector byte `0x92`, which decodes to sector 2, x_frac 0.5, z_frac 0.25, so x = 1234.5. z = −567 + 0.25 is
    exactly the negative-coordinate ambiguity of §6;
  - car index 7, human;
  - race state 2;
  - lap 3;
  - current time 61.5 s;
  - sector time 20.25 s.
- **Game state byte for "playing, race session":** `0x52` under the `<< 4` hypothesis, `0x2a` under `<< 3`. The
  capture decides (§12.3).
- **Negative tests:**
  - an 11-byte datagram;
  - type 0 with length 560;
  - type 9;
  - a PC1-format 1367-byte datagram (must produce the §3.6 hint, not a decode);
  - NaN `sSpeed` (`DECODE_WARNING`).
- **Machine check.** As for F1 (`tests/unit/test_f1_protocol.py`), add `tests/unit/test_pcars2_protocol.py`. It parses
  the `<!-- layout:… -->` tables in this file and asserts that `StructDef` field order, types, offsets and sizes match.
  Mark these tests `synthetic`.

### 12.2 Real captures (recorded tier)

No public pcars2 capture with a clear licence was found in this research. Pitwall must record its own.

- **Tool.** Add the decoder-less capture mode proposed in [GC] §7 (`pitwall capture --port 5606`). Write `.pwcap` with
  per-datagram timestamps, because many fields can only be settled offline.
- **AMS2 on PC, wired:**
  1. Run 1 practice out-lap plus 3 timed laps on one track.
  2. Run one 3-lap race against at least 15 AI cars.
  3. Repeat at UDP Frequency 1 and 5.
- **PC2 on PS4 or PS5:** the same script. Run it wired, then on 5 GHz Wi-Fi.
- **Store as fixtures:** `tests/fixtures/recorded/pcars2/<game>_<platform>_<date>.pwcap` plus a notes file. Record the
  in-game settings, game version and build number (from game state), and on-screen reference values (lap times, tyre
  pressures, brake bias, fuel).

### 12.3 Experiments that settle each open point

| Open point | Experiment | Pass criterion |
|---|---|---|
| sizes, versions per game | count `(type, len, version)` over the whole capture | every datagram hits §4.5. Update the table with what is seen |
| loss and rate | `mCategoryPacketNumber` gaps per type; inter-arrival times | report Hz per UDP Frequency setting; loss < 1 % wired |
| game/session bits | in the race session: drive, pause, open the in-game menu, watch a replay | `b & 7` = 2/3/4/6 and the high bits = 5. Pick `<< 4` vs `<< 3` |
| lap-invalid bit | cut a chicane to invalidate a lap | the bit that flips in `sRaceState` (3 or 7) |
| sector base | log `sSector & 7` across a lap | the values seen (0–2 vs 1–3); the transition distances become S2/S3 starts |
| lap base | `sCurrentLap` on the out-lap vs the first timed lap | the base that matches the HUD |
| pit mode/schedule bits | drive into the pits, stop, exit | the nibble cycling 1 → 2 → 3 |
| steering sign, g axes | steady left turn; hard straight-line braking | left = negative/positive; g_lon < 0 under braking after mapping |
| wheel order | left-side kerb strike or a single-wheel lock-up (brake temp, `sTyreRPS`) | the left-front index is 0 |
| tyre temperature units | compare `sTyreTreadTemp` with `sTyreTemp` (°C) | tread ≈ °C + 273 means Kelvin |
| tyre pressure, brake bias, wings | compare with the in-game/garage displays | derive the scale; else keep None |
| viewed vs local index | single player; then spectate another car / replay | `sViewedParticipantIndex` indexes timings; relation to `sLocalParticipantIndex` |
| vehicle-info layout | first type-8 1164 datagram | name at record+6 or record+8 (§5.8) |
| lap-time source | compare time-stats `sLastLapTime` with the HUD for 3 laps | exact to 1 ms |
| full vs coarse position | compare `sFullPosition` with the viewed car's timings `sWorldPosition` | agree within 1 m |

### 12.4 PS5 back-compat probe for PC2

1. Install PC2 (PS4 disc or library) on the PS5 and update it (patch ≥ 2.0 [V4]).
2. Set Options > System as in §3.2.
3. Run `tcpdump -n -i en0 udp port 5606` on the Mac, wired first.
4. **Pass:** any datagram with `byte[10]` ∈ {0..8}.
5. Only then upgrade `capabilities.py` "PC2 / PS5" from UNVERIFIED.

### 12.5 Capability claims (`src/pitwall/capabilities.py`)

| Integration | Initial | Upgrade path |
|---|---|---|
| AMS2 (PC) | COMMUNITY_DOCUMENTED once implemented | RECORDED_VALIDATED after the §12.2 fixtures pass §12.3; LIVE_VALIDATED after a live session |
| PC2 PS4 / Xbox One | COMMUNITY_DOCUMENTED | same |
| PC2 PS5 | UNVERIFIED | §12.4 |
| PC3 PC | COMMUNITY_DOCUMENTED (layout revision unknown) | capture |
| PC3 consoles | UNSUPPORTED [V6][V32] | — |
| PC1-format stream | UNSUPPORTED (detected, with a hint) | needs its own spec ([C32] is a candidate; unlicensed) |

---

## 13. Console caveats (PC2 on PS4/PS5)

- **Patch.** Patch 2.0 or later is needed [V4][V30][N1].
- **Network.**
  - The broadcast is slow and fragile, and can burden the LAN [V4][V7].
  - Prefer a wired console and a medium UDP Frequency (4–5) [V4][V7][C6].
  - The console may choose the wrong interface [V4].
- **Port and target.** The port is fixed and there is no target-IP field, so the Mac must be on the same broadcast
  domain (§3.3).
- **PS5.** Back-compat telemetry is unverified (§12.4). If it works, it is the PS4 build's protocol.
- **Wheel.** The Fanatec GT DD Pro may need PURPLE (PS4 compatibility) mode in PS4-era titles. Which titles need it is
  unverified [GC] §1 (Fanatec article [O26] in [GC]).
- **Availability.** PC2 is delisted; only existing owners or disc buyers can play [N3].

---

## 14. Open questions (carry to `docs/status.md` when implementing)

1. Which (type, len, version) set does each game and platform actually emit (§4.4)?
2. Game/session, flag, pit and lap-invalid bit layouts (§6).
3. Units: tyre pressure, brake bias, wings, handbrake, turbo pressure, left/centre/right tyre temperatures,
   `sEventTimeRemaining`, `sTickCount` (§7).
4. The `sVehicleInfo` layout (§5.8) and the meaning of `sClass`.
5. Partial-packet index base (§4.1).
6. Whether `sViewedParticipantIndex` indexes the timings array in single player, multiplayer and spectating.
7. PC2 on PS5 (§12.4).
8. Real console rates per UDP Frequency setting; Wi-Fi loss.

---

## 15. References

- [C10-T] tyretrack/server, `docs/SMS_UDP_Definitions.hpp` (commit 91a0aba, 2018-06-04; no licence):
  https://github.com/tyretrack/server/blob/master/docs/SMS_UDP_Definitions.hpp
- [C10-M] mplutka/tm-bt-led, `lib/pcars2-udp/SMS_UDP_Definitions.hpp` (repo MIT; file unlicensed SMS header):
  https://github.com/mplutka/tm-bt-led/blob/master/lib/pcars2-udp/SMS_UDP_Definitions.hpp
- [C10-S] saildeep/pcars2-udp, `SMS_UDP_Definitions.hpp` (no licence; 2018-03-23):
  https://github.com/saildeep/pcars2-udp/blob/master/SMS_UDP_Definitions.hpp
- [C31] tyretrack/server, `docs/SharedMemory.h` (SMS shared memory v9; "Copyright (c) MWL. All rights reserved."):
  https://github.com/tyretrack/server/blob/master/docs/SharedMemory.h
- [C32] tyretrack/server, `Readme.txt` (PC1 UDP layout and SMS packer pseudocode; no licence):
  https://github.com/tyretrack/server/blob/master/Readme.txt
- [C33] tyretrack/server, `tyretrack/pcars/v2.py` (no licence):
  https://github.com/tyretrack/server/blob/master/tyretrack/pcars/v2.py
- [C9-S] Crew Chief V4, `PCars2UDPTelemetryDataStruct.cs` (MIT, © 2019-2024 Britton IT Ltd):
  https://gitlab.com/mr_belowski/CrewChiefV4/-/blob/master/CrewChiefV4/PCars2/PCars2UDPTelemetryDataStruct.cs
  (identical on `main`)
- [C9-R] Crew Chief V4, `PCars2UDPreader.cs`:
  https://gitlab.com/mr_belowski/CrewChiefV4/-/blob/main/CrewChiefV4/PCars2/PCars2UDPreader.cs
- [C9-M] Crew Chief V4, `PCars2Struct.cs`:
  https://gitlab.com/mr_belowski/CrewChiefV4/-/blob/main/CrewChiefV4/PCars2/PCars2Struct.cs
- [C9-E] Crew Chief V4, `enums.cs`: https://gitlab.com/mr_belowski/CrewChiefV4/-/blob/main/CrewChiefV4/PCars2/enums.cs
- [C9-G] Crew Chief V4, `GameDefinition.cs` (the `pCars2Network` entry is commented out):
  https://gitlab.com/mr_belowski/CrewChiefV4/-/blob/main/CrewChiefV4/AllGames/GameDefinition.cs
  On the older `master` branch (last commit 2024-06-12), the path cited in [GC] still resolves, at
  `CrewChiefV4/GameDefinition.cs`. There `definitions.Add(pCars2Network)` is commented out (line 189).
- Crew Chief licence: https://gitlab.com/mr_belowski/CrewChiefV4/-/blob/main/LICENSE
- [C6] crmne/moza-rev (MIT, © 2026 Francis De Brabandere; madness parser added 2026-04-28):
  https://github.com/crmne/moza-rev (`src/madness.rs`, `src/listeners/madness.rs`, `examples/automobilista_2_log.rs`,
  README "Automobilista 2 / Project CARS 2")
- [C30] MacManley/project-cars-2-udp (MIT, © 2024 MacManley): https://github.com/MacManley/project-cars-2-udp
- [C34] mplutka/tm-bt-led, `lib/pcars2-udp/udp-parser.js` (MIT):
  https://github.com/mplutka/tm-bt-led/blob/master/lib/pcars2-udp/udp-parser.js
- [V4] SIM Dashboard, Project Cars 2 (console):
  http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Project_Cars_2
- [V6] SIM Dashboard, Project Cars 3:
  http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Project_Cars_3
- [V7] SIM Dashboard, "Project Cars 1 and 2 are slow":
  http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Issues/Project_Cars_1_and_2_are_slow
- [V30] RS Dash, Project CARS 2: https://www.rsdash.com/rs-dash-pcars2
- [V32] RS Dash, Project CARS 3: https://www.rsdash.com/rs-dash-pcars3
- [V55] MOZA support, Automobilista 2 (page "Modified on Fri, 29 May"; year not shown):
  https://support.mozaracing.com/en/support/solutions/articles/70000628772-automobilista-2-ams2-
- [V39] Sim Racing Telemetry, App Store listing (via [GC], not re-fetched):
  https://apps.apple.com/us/app/sim-racing-telemetry/id1288695792
- [F4] xsimulator.net, PC2 console UDP thread (posts 2017-10-20 to 2019-02-13):
  https://xsimulator.net/community/goto/post?id=166501
- [F6] Reiza Studios forum, AMS2 shared memory vs UDP (2025-08-29 to 2025-09-02):
  https://forum.reizastudios.com/posts/335128
- [N1] GTPlanet, "Project CARS 2 patch 2.0 launches on PS4" (2017-10-12):
  https://www.gtplanet.net/project-cars-2-patch-2-0-launches-ps4/
- [N3] GTPlanet, Project CARS 3 final pitstop (2025-07-26; via [GC], not re-fetched):
  https://www.gtplanet.net/project-cars-3-makes-final-pitstop-20250726
- [GC] pitwall, `docs/research/game-compatibility.md` (§1, §3.3, §7; licence table §6).
