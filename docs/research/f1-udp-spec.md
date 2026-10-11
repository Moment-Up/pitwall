# EA SPORTS F1 25 UDP Telemetry: Wire Specification (formats 2025 and 2026)

Research date: 2026-10-10. This document is the reference for the pitwall binary parser.
All struct blocks marked **verbatim** were extracted programmatically from EA's official
`.txt` attachments (byte-verified, see Sources). The offset tables, Python `struct` format
strings and size checks were generated from those same files by script, not typed by hand.

---

## 0. TL;DR for the parser

| Item | Value |
|---|---|
| Transport | UDP datagrams, one packet per datagram, default port **20777** |
| Byte order / packing | **Little-endian, fully packed** (no padding anywhere) |
| Header | 29 bytes, identical in formats 2025 and 2026 |
| Dispatch key | `(m_packetFormat, m_packetId)`, where `m_packetFormat` is the uint16 at offset 0: **2025** or **2026** |
| Do NOT dispatch on | `m_gameYear`. It reads **25** even in 2026 format (observed), and **0** in some pre-race packets (confirmed EA bug) |
| Cars per array | **22** in format 2025, **24** in format 2026 |
| Packet IDs | 0-15 exist in format 2025 (F1 25). Format 2026 adds **16 = Car Telemetry 2** |
| Wheel arrays | index 0 = RL, 1 = RR, 2 = FL, 3 = FR |
| Size check | Every packet has a fixed size per format (table in §3). All stated sizes were re-computed from the structs: **no mismatches** |
| Consoles | UDP output is available on PS5 and Xbox (in-game menu); the XML config file and D-BOX are PC-only |

---

## 1. Sources and confidence

### 1.1 Official (source of truth)

EA hosts the spec as a blog post with file attachments. The original F1 25 URL now redirects
to the post that also carries the 2026 Season Pack files:

- Blog post: <https://forums.ea.com/blog/f1-games-game-info-hub-en/ea-sports%E2%84%A2-f1%C2%AE25-2026-season-pack-udp-specification/12187347>
  (old URL `.../f1%c2%ae-25-udp-specification/12187347` redirects here). Title "EA SPORTS™ F1®25: 2026 Season Pack UDP SPECIFICATION",
  author EA_Groguet (Community Manager), shown as "VERSION 11.0", "Updated 1 month ago" on 2026-10-10.
  The post says: "If you have already started a game, you will be on F1® 25 UDP and need to change it manually. If you have never played F1® 25 before, you will get the F1® 25: 2026 Season Pack UDP by default."
- Q&A threads: F1 25: <https://forums.ea.com/discussions/f1-25-general-discussion-en/discussion-f1%c2%ae-25-udp-specification/12187351>,
  2026 Season Pack: <https://forums.ea.com/discussions/f1-25-general-discussion-en/discussion-f1%C2%AE25-2026-season-pack-udp-specification/13424444>
  (replies are not visible without signing in).

Attachments (base URL `https://forums.ea.com/t5/s/tghpe58374/attachments/tghpe58374/f1-games-game-info-hub-en/61/`):

| Attachment (path under base) | Content | HTTP Last-Modified | SHA-256 (as served) |
|---|---|---|---|
| `4/Data%20Output%20from%20F1%2025%20v3.pdf` | F1 25 spec PDF (format 2025), 31 pp | 2025-05-27 | `850199d1ea817b887b150118095c5ca86527a397d578d53fd5c83427636b92d5` |
| `5/F1%2025%20Telemetry%20Output%20Structures.txt` | F1 25 C++ structs (format 2025), 51,656 B | 2025-05-27 | `49cceadc60a1a6403a59620c6fc09da377048ba004b15c199399f775b9b3fc69` |
| `8/2026%20Season%20Pack%20Telemetry%20Output%20Structures%20(1).txt` | 2026 Season Pack C++ structs (format 2026), 55,368 B | 2026-06-03 | `4f97867924f5f13f11b7fde6eb84ccb3aefcaf69062424bc077e387090647c72` |
| `9/Data%20Output%20from%20F1%2025%202026%20Season%20Pack%20(1).pdf` | 2026 spec PDF **v1.1** ("rename Overtake deploy state to Boost") | 2026-06-03 | `74fc3793b123717fd3261d1bbbba3e896dfd9bdba442bb79af7db8500098d2a0` |
| `10/Data%20Output%20from%20F1%2025%202026%20Season%20Pack%20(Season%208).pdf` | 2026 spec PDF **v1.2** ("Added F2 Driver IDs as part of the Season 8 Sports Update") | 2026-09-07 | `3f38858c3ca65b2faa55a90a35277dd2767bb9cea2911e741b61b370a39365ae` |

Other official pages used:
- F1 25: 2026 Season Pack v1.25 patch notes (2026-09-07): <https://forums.ea.com/blog/f1-games-game-info-hub-en/f1%c2%ae-25-2026-season-pack-%e2%80%93-v1-25-%e2%80%93-patch-notes/13694119>.
  It says an "Overtake Enabled" Race Control message "has also been added to the UDP output". This matches PDF v1.2.
- Confirmed bug report "UDP telemetry - Game year is reported as 0 before race start" (status CONFIRMED): <https://forums.ea.com/idea/f1-25-bug-reports-en/udp-telemetry---game-year-is-reported-as-0-before-race-start/12214767>
- F1 23 and F1 24 spec links given in the F1 25 PDF: `https://answers.ea.com/t5/General-Discussion/F1-23-UDP-Specification/m-p/12633159`, `https://answers.ea.com/t5/General-Discussion/F1-24-UDP-Specification/td-p/13745220`.

### 1.2 How the files were obtained and verified

- forums.ea.com returns HTTP 403 to plain `curl`/WebFetch. The pages were read in a real browser session. The two `.txt` files and three PDFs were hashed (SHA-256) inside that session.
- Byte-identical mirrors of the same files were then fetched from GitHub through `gh api`. Matching hashes confirm they are EA's files unmodified:
  - 2025 `.txt`: `VitaliyNig/Telemetry-Logger`, `JanVerstuyft/racing-league`, `KaygusuzBK/f1-telemetry-nextjs` (exact bytes). `rico1792/F125_telemetrie` and `LarsLaskowski/F1-Telemetry` (`... - v3.txt`) match after CRLF→LF.
  - 2026 `.txt`: `rico1792/F125_telemetrie`, `VitaliyNig/Telemetry-Logger`, `JanVerstuyft/racing-league`, `LarsLaskowski/F1-Telemetry` (all match after CRLF→LF).
  - PDFs: `LarsLaskowski/F1-Telemetry/docs/original-specs/F1 2025 Telemetry.pdf` = F1 25 v3 PDF, and `.../F1 2026 Telemetry.pdf` = 2026 v1.1 PDF (exact SHA-256 match). The v1.2 (Season 8) PDF has no mirror. It was text-extracted in the browser with pdf.js and line-diffed against v1.1 (differences listed in §7.4 and §8).
- The struct lists in the PDFs were compared against the `.txt` files with a script. Field order and types are **identical** in both formats. Only these names differ: PDF `m_carSetups` vs txt `m_carSetupData`, PDF `m_vehicleFiaFlags` vs txt `m_vehicleFIAFlags`, and in 2026 PDF `m_ersHarvestedLimitPerLap` vs txt `m_ersHarvestLimitPerLap`.
- The F1 23 and F1 24 `.docx` specs (mirrored in `LarsLaskowski/F1-Telemetry`) were used only for the legacy Track IDs, and the F1 24 `.txt` only for the F1 24 → F1 25 diff.
- GitHub implementations were used only for cross-checking (see `f1-repos.md`).

**Confidence.** High for every struct, size, offset and appendix value. They come straight from EA's files and were machine-checked. Medium for runtime behaviour (send rates, gameYear quirks), which comes from EA's prose plus community or measured observations. Each such item is labelled.

---

## 2. Wire basics (official)

From the PDF: "Please note that all values are encoded using Little Endian format. All data is packed." The FAQ adds: "Yes, all data is packed, there is no padding used."

| Spec type | Bytes | Python `struct` code |
|---|---:|---|
| `uint8` (also `NEuint8`) | 1 | `B` |
| `int8` | 1 | `b` |
| `uint16` | 2 | `H` |
| `int16` | 2 | `h` |
| `uint32` (also bare `uint`, used in `TimeTrialDataSet` and constants) | 4 | `I` |
| `float` | 4 | `f` (IEEE-754 binary32) |
| `double` | 8 | `d` |
| `uint64` | 8 | `Q` |
| `char[N]` | N | `Ns` (UTF-8, null-terminated, truncated with U+2026 if too long) |

- **Car arrays** are indexed by *vehicle index*. The index stays fixed for the whole session. Use `m_numActiveCars` (Participants) for the count, and `LapData.m_resultStatus` per slot: data is valid only when the status is not 0 (invalid) or 1 (inactive).
- **Wheel order** for every 4-element wheel array: `0 = RL, 1 = RR, 2 = FL, 3 = FR`.
- **Co-ordinate system.** The spec shows only a picture with no text. By community convention (and in every reviewed implementation that draws maps), `Y` is vertical and the `X`/`Z` plane is the ground. This is not stated in the spec text.
- **Frame grouping.** All packets sent at "Rate as specified in menus" for one frame go out together and are never split across frames. Packets with fixed rates can arrive on any frame. On frame 1 the game sends Session, Participants, Car Setups, Lap Data, Motion, Car Telemetry, Car Status, Car Damage and Motion Ex, all with `m_sessionTime` 0.000.
- **"Your Telemetry" restriction.** When the player driving a car has Your Telemetry = Restricted (the default), other players' UDP shows zero for these fields of that car:
  - Car Status: `m_fuelInTank`, `m_fuelCapacity`, `m_fuelMix`, `m_fuelRemainingLaps`, `m_frontBrakeBias`, `m_ersDeployMode`, `m_ersStoreEnergy`, `m_ersDeployedThisLap`, `m_ersHarvestedThisLapMGUK`, `m_ersHarvestedThisLapMGUH`, `m_enginePowerICE`, `m_enginePowerMGUK`
  - Car Damage: wing, floor, diffuser, sidepod, engine and gearbox damage; `m_tyresWear`, `m_tyresDamage` and `m_brakesDamage` (all four wheels); `m_drsFault`; all `m_engine*Wear`
  - Tyre Sets: all data for that car

  You always see full data for your own car. Online names appear only if the player enabled "Show online ID / gamertags".
- **Participant names.** On PC multiplayer the name is the Steam ID (or the LAN name). On Xbox it is always the driver name. On PlayStation it is the LAN name in LAN games, otherwise the driver name.
- **Car Setups.** In multiplayer, other players' setups are blank regardless of Your Telemetry. Spectators see no setups.

---

## 3. Packet catalogue and size verification

Sizes are total datagram bytes, header included. "Computed" means summed from the verbatim
structs by script (`packed`, constants resolved). Every stated size matches its computed size.

| ID | Packet | Frequency (official) | 2025 stated | 2025 computed | 2025 layout | 2026 stated | 2026 computed | 2026 layout | Match |
|---:|---|---|---:|---:|---|---:|---:|---|:-:|
| 0 | Motion | Rate as specified in menus | 1349 | 1349 | 29 + 22×60 | 1325 | 1325 | 29 + 24×**54** | yes |
| 1 | Session | 2 per second | 753 | 753 | 29 + 724 | 926 | 926 | 29 + 724 + 173 tail | yes |
| 2 | Lap Data | Rate as specified in menus | 1285 | 1285 | 29 + 22×57 + 2 | 1399 | 1399 | 29 + 24×57 + 2 | yes |
| 3 | Event | When the event occurs | 45 | 45 | 29 + 4 + 12 (union) | 45 | 45 | 29 + 4 + 12 (union) | yes |
| 4 | Participants | Every 5 seconds | 1284 | 1284 | 29 + 1 + 22×57 | 1470 | 1470 | 29 + 1 + 24×**60** | yes |
| 5 | Car Setups | 2 per second | 1133 | 1133 | 29 + 22×50 + 4 | 1233 | 1233 | 29 + 24×50 + 4 | yes |
| 6 | Car Telemetry | Rate as specified in menus | 1352 | 1352 | 29 + 22×60 + 3 | 1448 | 1448 | 29 + 24×**59** + 3 | yes |
| 7 | Car Status | Rate as specified in menus | 1239 | 1239 | 29 + 22×55 | 1445 | 1445 | 29 + 24×**59** | yes |
| 8 | Final Classification | Once at the end of a race | 1042 | 1042 | 29 + 1 + 22×46 | 1134 | 1134 | 29 + 1 + 24×46 | yes |
| 9 | Lobby Info | Two every second when in the lobby | 954 | 954 | 29 + 1 + 22×42 | 1062 | 1062 | 29 + 1 + 24×**43** | yes |
| 10 | Car Damage | 10 per second (see §10, item 4) | 1041 | 1041 | 29 + 22×46 | 1133 | 1133 | 29 + 24×46 | yes |
| 11 | Session History | 20 per second, cycling through cars | 1460 | 1460 | 29 + 7 + 100×14 + 8×3 | 1460 | 1460 | unchanged | yes |
| 12 | Tyre Sets | 20 per second, cycling through cars | 231 | 231 | 29 + 1 + 20×10 + 1 | 231 | 231 | unchanged | yes |
| 13 | Motion Ex | Rate as specified in menus | 273 | 273 | 29 + 244 (player car only) | 273 | 273 | unchanged | yes |
| 14 | Time Trial | 1 per second (Time Trial mode only) | 101 | 101 | 29 + 3×24 | 104 | 104 | 29 + 3×**25** | yes |
| 15 | Lap Positions | 1 per second | 1131 | 1131 | 29 + 2 + 50×22 | 1231 | 1231 | 29 + 2 + 50×24 | yes |
| 16 | Car Telemetry 2 | Rate as specified in menus | n/a | n/a | not in format 2025 | 269 | 269 | 29 + 24×10 | yes |

Per-car / sub-struct sizes (computed):

| Struct | 2025 | 2026 | | Struct | 2025 | 2026 |
|---|---:|---:|---|---|---:|---:|
| PacketHeader | 29 | 29 | | CarDamageData | 46 | 46 |
| CarMotionData | 60 | 54 | | LapHistoryData | 14 | 14 |
| MarshalZone | 5 | 5 | | TyreStintHistoryData | 3 | 3 |
| WeatherForecastSample | 8 | 8 | | TyreSetData | 10 | 10 |
| ActiveAeroZone / DRSZone | n/a | 8 / 8 | | TimeTrialDataSet | 24 | 25 |
| LapData | 57 | 57 | | EventDataDetails (union) | 12 | 12 |
| ParticipantData | 57 | 60 | | LiveryColour | 3 | 3 |
| CarSetupData | 50 | 50 | | CarTelemetry2Data | n/a | 10 |
| CarTelemetryData | 60 | 59 | | FinalClassificationData | 46 | 46 |
| CarStatusData | 55 | 59 | | LobbyInfoData | 42 | 43 |

For comparison, the F1 24 (format 2024) sizes recomputed from EA's F1 24 `.txt` also match their stated values:
Motion 1349, Session 753, Lap 1285, Event 45, Participants **1350**, Car Setups 1133, Car Telemetry 1352,
Car Status 1239, Final Classification **1020**, Lobby Info **1306**, Car Damage **953**, Session History 1460,
Tyre Sets 231, Motion Ex **237**, Time Trial 101. Bold marks values that changed in F1 25.

---

## 4. Constants, packet IDs and header

### 4.1 Constants and PacketId enum: format 2025 (verbatim)

```c
static const uint32     cs_maxNumCarsInUDPData = 22;
static const uint32     cs_maxParticipantNameLen = 32;
static const uint32     cs_maxTyreStints = 8;
static const uint32     cs_maxNumTyreSets = 13 + 7; // 13 slick and 7 wet weather

// Different packet types
enum PacketId
{
    ePacketIdMotion                 = 0,    // Contains all motion data for player’s car – only sent while player is in control
    ePacketIdSession                = 1,    // Data about the session – track, time left
    ePacketIdLapData                = 2,    // Data about all the lap times of cars in the session
    ePacketIdEvent                  = 3,    // Various notable events that happen during a session
    ePacketIdParticipants           = 4,    // List of participants in the session, mostly relevant for multiplayer
    ePacketIdCarSetups              = 5,    // Packet detailing car setups for cars in the race
    ePacketIdCarTelemetry           = 6,    // Telemetry data for all cars
    ePacketIdCarStatus              = 7,    // Status data for all cars
    ePacketIdFinalClassification    = 8,    // Final classification confirmation at the end of a race
    ePacketIdLobbyInfo              = 9,    // Information about players in a multiplayer lobby
    ePacketIdCarDamage              = 10,   // Damage status for all cars
    ePacketIdSessionHistory         = 11,   // Lap and tyre data for session
    ePacketIdTyreSets               = 12,   // Extended tyre set data
    ePacketIdMotionEx               = 13,   // Extended motion data for player car
    ePacketIdTimeTrial              = 14,   // Time Trial specific data
    ePacketIdLapPositions           = 15,   // Lap positions on each lap so a chart can be constructed
    ePacketIdMax
};
```

Format 2026 changes only `cs_maxNumCarsInUDPData = 24` and adds one enum entry (verbatim):

```c
    ePacketIdCarTelemetry2          = 16,   // More telemetry data for all cars
```

### 4.2 PacketHeader (29 bytes, both formats; verbatim from the 2025 file)

```c
struct PacketHeader
{
    uint16      m_packetFormat;             // 2025
    uint8       m_gameYear;                 // Game year - last two digits e.g. 25
    uint8       m_gameMajorVersion;         // Game major version - "X.00"
    uint8       m_gameMinorVersion;         // Game minor version - "1.XX"
    uint8       m_packetVersion;            // Version of this packet type
    uint8       m_packetId;                 // Identifier for the packet type
    uint64      m_sessionUID;               // Unique identifier for the session
    float       m_sessionTime;              // Session timestamp
    uint32      m_frameIdentifier;          // Identifier for the frame the data was retrieved on
    uint32      m_overallFrameIdentifier;   // Overall identifier for the frame the data was retrieved on, doesn't go back after flashbacks
    uint8       m_playerCarIndex;           // Index of player's car in the array
    uint8       m_secondaryPlayerCarIndex;  // Index of secondary player's car in the array (splitscreen) - 255 if no second player
};
```

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 2 | `uint16` | `m_packetFormat` |
| 2 | 1 | `uint8` | `m_gameYear` |
| 3 | 1 | `uint8` | `m_gameMajorVersion` |
| 4 | 1 | `uint8` | `m_gameMinorVersion` |
| 5 | 1 | `uint8` | `m_packetVersion` |
| 6 | 1 | `uint8` | `m_packetId` |
| 7 | 8 | `uint64` | `m_sessionUID` |
| 15 | 4 | `float` | `m_sessionTime` |
| 19 | 4 | `uint32` | `m_frameIdentifier` |
| 23 | 4 | `uint32` | `m_overallFrameIdentifier` |
| 27 | 1 | `uint8` | `m_playerCarIndex` |
| 28 | 1 | `uint8` | `m_secondaryPlayerCarIndex` |
| **29** | | | *total* |

Python: `<HBBBBBQfIIBB` (calcsize = 29)

The 2026 file's header (verbatim) is byte-identical; only the comments on the first two fields differ:

```c
struct PacketHeader
{
    uint16      m_packetFormat;             // 2026
    uint8       m_gameYear;                 // Game year - last two digits e.g. 26
    uint8       m_gameMajorVersion;         // Game major version - "X.00"
    uint8       m_gameMinorVersion;         // Game minor version - "1.XX"
    uint8       m_packetVersion;            // Version of this packet type
    uint8       m_packetId;                 // Identifier for the packet type
    uint64      m_sessionUID;               // Unique identifier for the session
    float       m_sessionTime;              // Session timestamp
    uint32      m_frameIdentifier;          // Identifier for the frame the data was retrieved on
    uint32      m_overallFrameIdentifier;   // Overall identifier for the frame the data was retrieved on, doesn't go back after flashbacks
    uint8       m_playerCarIndex;           // Index of player's car in the array
    uint8       m_secondaryPlayerCarIndex;  // Index of secondary player's car in the array (splitscreen) - 255 if no second player
};
```

Notes:
- `m_packetFormat`: 2025 or 2026. Older formats selected in-game (2024, 2023) carry their own layouts (out of scope).
- `m_gameYear`: the 2025 file says "e.g. 25". The 2026 `.txt` says "e.g. 26", but the 2026 PDF still says "e.g. 25", and live 2026-format captures show **25**. Treat it as informational only.
- `m_gameMajorVersion` / `m_gameMinorVersion`: game patch, e.g. 1 / 24 for v1.24.
- `m_packetVersion`: "Version of this packet type, all start from 1". Every packet in both formats is Version 1.
- `m_sessionUID`: uint64. It is 0 in menus and loading screens (observed). A change of UID means a new session.
- `m_sessionTime`: seconds since the session started (float). It goes backwards on flashback and restart.
- `m_frameIdentifier`: goes back after flashbacks. `m_overallFrameIdentifier` does not.
- `m_playerCarIndex`: index into car arrays. It is often not 0 (e.g. 21 was observed in a 2026-format practice session).
- `m_secondaryPlayerCarIndex`: 255 if there is no second (split-screen) player.

---

## 5. Format 2025 packets (F1 25 base game), structs verbatim

### 5.0 Motion (ID 0), 1349 bytes, rate as set in menus

The spec says: "The motion packet gives physics data for all the cars being driven." For the normalised direction vectors: "to convert to float values divide by 32767.0f".

```c
struct CarMotionData
{
    float       m_worldPositionX;           // World space X position - metres
    float       m_worldPositionY;           // World space Y position
    float       m_worldPositionZ;           // World space Z position
    float       m_worldVelocityX;           // Velocity in world space X - metres/s
    float       m_worldVelocityY;           // Velocity in world space Y
    float       m_worldVelocityZ;           // Velocity in world space Z
    int16       m_worldForwardDirX;         // World space forward X direction (normalised)
    int16       m_worldForwardDirY;         // World space forward Y direction (normalised)
    int16       m_worldForwardDirZ;         // World space forward Z direction (normalised)
    int16       m_worldRightDirX;           // World space right X direction (normalised)
    int16       m_worldRightDirY;           // World space right Y direction (normalised)
    int16       m_worldRightDirZ;           // World space right Z direction (normalised)
    float       m_gForceLateral;            // Lateral G-Force component
    float       m_gForceLongitudinal;       // Longitudinal G-Force component
    float       m_gForceVertical;           // Vertical G-Force component
    float       m_yaw;                      // Yaw angle in radians
    float       m_pitch;                    // Pitch angle in radians
    float       m_roll;                     // Roll angle in radians
};
```

```c
struct PacketMotionData
{
    PacketHeader    m_header;               // Header

    // Packet specific data
    CarMotionData   m_carMotionData[cs_maxNumCarsInUDPData];  // Data for all cars on track
};
```

`CarMotionData` offsets (stride 60; car *i* starts at `29 + 60*i`):

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 4 | `float` | `m_worldPositionX` |
| 4 | 4 | `float` | `m_worldPositionY` |
| 8 | 4 | `float` | `m_worldPositionZ` |
| 12 | 4 | `float` | `m_worldVelocityX` |
| 16 | 4 | `float` | `m_worldVelocityY` |
| 20 | 4 | `float` | `m_worldVelocityZ` |
| 24 | 2 | `int16` | `m_worldForwardDirX` |
| 26 | 2 | `int16` | `m_worldForwardDirY` |
| 28 | 2 | `int16` | `m_worldForwardDirZ` |
| 30 | 2 | `int16` | `m_worldRightDirX` |
| 32 | 2 | `int16` | `m_worldRightDirY` |
| 34 | 2 | `int16` | `m_worldRightDirZ` |
| 36 | 4 | `float` | `m_gForceLateral` |
| 40 | 4 | `float` | `m_gForceLongitudinal` |
| 44 | 4 | `float` | `m_gForceVertical` |
| 48 | 4 | `float` | `m_yaw` |
| 52 | 4 | `float` | `m_pitch` |
| 56 | 4 | `float` | `m_roll` |
| **60** | | | *total* |

Python per-car: `<ffffffhhhhhhffffff` (calcsize = 60)

Units: position in m, velocity in m/s, direction int16 ÷ 32767 (unit vectors), yaw/pitch/roll in rad.
In format 2025 the g-force components are `float`. The spec gives no unit; implementations treat them as multiples of g (lateral, longitudinal, vertical).
The packet is sent "only while player is in control" (PacketId comment).

### 5.1 Session (ID 1), 753 bytes, 2 per second

```c
static const uint32     cs_maxMarshalsZonePerLap = 21;
static const uint32     cs_maxWeatherForecastSamples = 64;
static const uint32     cs_maxSessionsInWeekend = 12;
```

```c
struct MarshalZone
{
    float       m_zoneStart;       // Fraction (0..1) of way through the lap the marshal zone starts
    int8        m_zoneFlag;        // -1 = invalid/unknown, 0 = none, 1 = green, 2 = blue, 3 = yellow
};
```

```c
struct WeatherForecastSample
{
    uint8       m_sessionType;              // 0 = unknown, see appendix
    uint8       m_timeOffset;               // Time in minutes the forecast is for
    uint8       m_weather;                  // Weather - 0 = clear, 1 = light cloud, 2 = overcast, 3 = light rain, 4 = heavy rain, 5 = storm
    int8        m_trackTemperature;         // Track temp. in degrees celsius
    int8        m_trackTemperatureChange;   // Track temp. change - 0 = up, 1 = down, 2 = no change
    int8        m_airTemperature;           // Air temp. in degrees celsius
    int8        m_airTemperatureChange;     // Air temp. change - 0 = up, 1 = down, 2 = no change
    uint8       m_rainPercentage;           // Rain percentage (0-100)
};
```

```c
struct PacketSessionData
{
    PacketHeader    m_header;               // Header

    // Packet specific data
    uint8       m_weather;                          // Weather - 0 = clear, 1 = light cloud, 2 = overcast, 3 = light rain, 4 = heavy rain, 5 = storm
    int8        m_trackTemperature;                 // Track temp. in degrees celsius
    int8        m_airTemperature;                   // Air temp. in degrees celsius
    uint8       m_totalLaps;                        // Total number of laps in this race
    uint16      m_trackLength;                      // Track length in metres
    uint8       m_sessionType;                      // 0 = unknown, see appendix
    int8        m_trackId;                          // -1 for unknown, see appendix
    uint8       m_formula;                          // Formula, 0 = F1 Modern, 1 = F1 Classic, 2 = F2, 3 = F1 Generic, 4 = Beta, 6 = Esports, 8 = F1 World, 9 = F1 Elimination
    uint16      m_sessionTimeLeft;		            // Time left in session in seconds
    uint16      m_sessionDuration;		            // Session duration in seconds
    uint8       m_pitSpeedLimit;                    // Pit speed limit in kilometres per hour
    uint8       m_gamePaused;                       // Whether the game is paused - network game only
    uint8       m_isSpectating;                     // Whether the player is spectating
    uint8       m_spectatorCarIndex;                // Index of the car being spectated
    uint8       m_sliProNativeSupport;              // SLI Pro support, 0 = inactive, 1 = active
    uint8       m_numMarshalZones;                  // Number of marshal zones to follow
    MarshalZone m_marshalZones[cs_maxMarshalsZonePerLap];  // List of marshal zones - max 21
    uint8       m_safetyCarStatus;                  // 0 = no safety car, 1 = full, 2 = virtual, 3 = formation lap
    uint8       m_networkGame;                      // 0 = offline, 1 = online
    uint8       m_numWeatherForecastSamples;        // Number of weather samples to follow
    WeatherForecastSample m_weatherForecastSamples[cs_maxWeatherForecastSamples];   // Array of weather forecast samples
    uint8       m_forecastAccuracy;                 // 0 = Perfect, 1 = Approximate
    uint8       m_aiDifficulty;                     // AI difficulty - 0-110
    uint32      m_seasonLinkIdentifier;             // Identifier for season - persists across saves
    uint32      m_weekendLinkIdentifier;            // Identifier for weekend - persists across saves
    uint32      m_sessionLinkIdentifier;            // Identifier for session - persists across saves
    uint8       m_pitStopWindowIdealLap;            // Ideal lap to pit on for current strategy (player)
    uint8       m_pitStopWindowLatestLap;           // Latest lap to pit on for current strategy (player)
    uint8       m_pitStopRejoinPosition;            // Predicted position to rejoin at (player)
    uint8       m_steeringAssist;                   // 0 = off, 1 = on
    uint8       m_brakingAssist;                    // 0 = off, 1 = low, 2 = medium, 3 = high
    uint8       m_gearboxAssist;                    // 1 = manual, 2 = manual & suggested gear, 3 = auto
    uint8       m_pitAssist;                        // 0 = off, 1 = on
    uint8       m_pitReleaseAssist;                 // 0 = off, 1 = on
    uint8       m_ERSAssist;                        // 0 = off, 1 = on
    uint8       m_DRSAssist;                        // 0 = off, 1 = on
    uint8       m_dynamicRacingLine;                // 0 = off, 1 = corners only, 2 = full
    uint8       m_dynamicRacingLineType;            // 0 = 2D, 1 = 3D
    uint8       m_gameMode;                         // Game mode id - see appendix
    uint8       m_ruleSet;                          // Ruleset - see appendix
    uint32      m_timeOfDay;                        // Local time of day - minutes since midnight
    uint8       m_sessionLength;                    // 0 = None, 2 = Very Short, 3 = Short, 4 = Medium, 5 = Medium Long, 6 = Long, 7 = Full
    uint8       m_speedUnitsLeadPlayer;             // 0 = MPH, 1 = KPH
    uint8       m_temperatureUnitsLeadPlayer;       // 0 = Celsius, 1 = Fahrenheit
    uint8       m_speedUnitsSecondaryPlayer;        // 0 = MPH, 1 = KPH
    uint8       m_temperatureUnitsSecondaryPlayer;  // 0 = Celsius, 1 = Fahrenheit
    uint8       m_numSafetyCarPeriods;              // Number of safety cars called during session
    uint8       m_numVirtualSafetyCarPeriods;       // Number of virtual safety cars called during session
    uint8       m_numRedFlagPeriods;                // Number of red flags called during session
    uint8       m_equalCarPerformance;              // 0 = Off, 1 = On
    uint8       m_recoveryMode;                     // 0 = None, 1 = Flashbacks, 2 = Auto-recovery
    uint8       m_flashbackLimit;                   // 0 = Low, 1 = Medium, 2 = High, 3 = Unlimited
    uint8       m_surfaceType;                      // 0 = Simplified, 1 = Realistic
    uint8       m_lowFuelMode;                      // 0 = Easy, 1 = Hard
    uint8       m_raceStarts;                       // 0 = Manual, 1 = Assisted
    uint8       m_tyreTemperature;                  // 0 = Surface only, 1 = Surface & Carcass
    uint8       m_pitLaneTyreSim;                   // 0 = On, 1 = Off
    uint8       m_carDamage;                        // 0 = Off, 1 = Reduced, 2 = Standard, 3 = Simulation
    uint8       m_carDamageRate;                    // 0 = Reduced, 1 = Standard, 2 = Simulation
    uint8       m_collisions;                       // 0 = Off, 1 = Player-to-Player Off, 2 = On
    uint8       m_collisionsOffForFirstLapOnly;     // 0 = Disabled, 1 = Enabled
    uint8       m_mpUnsafePitRelease;               // 0 = On, 1 = Off (Multiplayer)
    uint8       m_mpOffForGriefing;                 // 0 = Disabled, 1 = Enabled (Multiplayer)
    uint8       m_cornerCuttingStringency;          // 0 = Regular, 1 = Strict
    uint8       m_parcFermeRules;                   // 0 = Off, 1 = On
    uint8       m_pitStopExperience;                // 0 = Automatic, 1 = Broadcast, 2 = Immersive
    uint8       m_safetyCar;                        // 0 = Off, 1 = Reduced, 2 = Standard, 3 = Increased
    uint8       m_safetyCarExperience;              // 0 = Broadcast, 1 = Immersive
    uint8       m_formationLap;                     // 0 = Off, 1 = On
    uint8       m_formationLapExperience;           // 0 = Broadcast, 1 = Immersive
    uint8       m_redFlags;                         // 0 = Off, 1 = Reduced, 2 = Standard, 3 = Increased
    uint8       m_affectsLicenceLevelSolo;          // 0 = Off, 1 = On
    uint8       m_affectsLicenceLevelMP;            // 0 = Off, 1 = On
    uint8       m_numSessionsInWeekend;             // Number of session in following array
    uint8       m_weekendStructure[cs_maxSessionsInWeekend];    // List of session types to show weekend structure - see appendix for types
    float       m_sector2LapDistanceStart;          // Distance in m around track where sector 2 starts
    float       m_sector3LapDistanceStart;          // Distance in m around track where sector 3 starts
};
```

`PacketSessionData` offsets (absolute, header included):

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 29 | `PacketHeader` | `m_header` |
| 29 | 1 | `uint8` | `m_weather` |
| 30 | 1 | `int8` | `m_trackTemperature` |
| 31 | 1 | `int8` | `m_airTemperature` |
| 32 | 1 | `uint8` | `m_totalLaps` |
| 33 | 2 | `uint16` | `m_trackLength` |
| 35 | 1 | `uint8` | `m_sessionType` |
| 36 | 1 | `int8` | `m_trackId` |
| 37 | 1 | `uint8` | `m_formula` |
| 38 | 2 | `uint16` | `m_sessionTimeLeft` |
| 40 | 2 | `uint16` | `m_sessionDuration` |
| 42 | 1 | `uint8` | `m_pitSpeedLimit` |
| 43 | 1 | `uint8` | `m_gamePaused` |
| 44 | 1 | `uint8` | `m_isSpectating` |
| 45 | 1 | `uint8` | `m_spectatorCarIndex` |
| 46 | 1 | `uint8` | `m_sliProNativeSupport` |
| 47 | 1 | `uint8` | `m_numMarshalZones` |
| 48 | 105 | `MarshalZone[21]` | `m_marshalZones` |
| 153 | 1 | `uint8` | `m_safetyCarStatus` |
| 154 | 1 | `uint8` | `m_networkGame` |
| 155 | 1 | `uint8` | `m_numWeatherForecastSamples` |
| 156 | 512 | `WeatherForecastSample[64]` | `m_weatherForecastSamples` |
| 668 | 1 | `uint8` | `m_forecastAccuracy` |
| 669 | 1 | `uint8` | `m_aiDifficulty` |
| 670 | 4 | `uint32` | `m_seasonLinkIdentifier` |
| 674 | 4 | `uint32` | `m_weekendLinkIdentifier` |
| 678 | 4 | `uint32` | `m_sessionLinkIdentifier` |
| 682 | 1 | `uint8` | `m_pitStopWindowIdealLap` |
| 683 | 1 | `uint8` | `m_pitStopWindowLatestLap` |
| 684 | 1 | `uint8` | `m_pitStopRejoinPosition` |
| 685 | 1 | `uint8` | `m_steeringAssist` |
| 686 | 1 | `uint8` | `m_brakingAssist` |
| 687 | 1 | `uint8` | `m_gearboxAssist` |
| 688 | 1 | `uint8` | `m_pitAssist` |
| 689 | 1 | `uint8` | `m_pitReleaseAssist` |
| 690 | 1 | `uint8` | `m_ERSAssist` |
| 691 | 1 | `uint8` | `m_DRSAssist` |
| 692 | 1 | `uint8` | `m_dynamicRacingLine` |
| 693 | 1 | `uint8` | `m_dynamicRacingLineType` |
| 694 | 1 | `uint8` | `m_gameMode` |
| 695 | 1 | `uint8` | `m_ruleSet` |
| 696 | 4 | `uint32` | `m_timeOfDay` |
| 700 | 1 | `uint8` | `m_sessionLength` |
| 701 | 1 | `uint8` | `m_speedUnitsLeadPlayer` |
| 702 | 1 | `uint8` | `m_temperatureUnitsLeadPlayer` |
| 703 | 1 | `uint8` | `m_speedUnitsSecondaryPlayer` |
| 704 | 1 | `uint8` | `m_temperatureUnitsSecondaryPlayer` |
| 705 | 1 | `uint8` | `m_numSafetyCarPeriods` |
| 706 | 1 | `uint8` | `m_numVirtualSafetyCarPeriods` |
| 707 | 1 | `uint8` | `m_numRedFlagPeriods` |
| 708 | 1 | `uint8` | `m_equalCarPerformance` |
| 709 | 1 | `uint8` | `m_recoveryMode` |
| 710 | 1 | `uint8` | `m_flashbackLimit` |
| 711 | 1 | `uint8` | `m_surfaceType` |
| 712 | 1 | `uint8` | `m_lowFuelMode` |
| 713 | 1 | `uint8` | `m_raceStarts` |
| 714 | 1 | `uint8` | `m_tyreTemperature` |
| 715 | 1 | `uint8` | `m_pitLaneTyreSim` |
| 716 | 1 | `uint8` | `m_carDamage` |
| 717 | 1 | `uint8` | `m_carDamageRate` |
| 718 | 1 | `uint8` | `m_collisions` |
| 719 | 1 | `uint8` | `m_collisionsOffForFirstLapOnly` |
| 720 | 1 | `uint8` | `m_mpUnsafePitRelease` |
| 721 | 1 | `uint8` | `m_mpOffForGriefing` |
| 722 | 1 | `uint8` | `m_cornerCuttingStringency` |
| 723 | 1 | `uint8` | `m_parcFermeRules` |
| 724 | 1 | `uint8` | `m_pitStopExperience` |
| 725 | 1 | `uint8` | `m_safetyCar` |
| 726 | 1 | `uint8` | `m_safetyCarExperience` |
| 727 | 1 | `uint8` | `m_formationLap` |
| 728 | 1 | `uint8` | `m_formationLapExperience` |
| 729 | 1 | `uint8` | `m_redFlags` |
| 730 | 1 | `uint8` | `m_affectsLicenceLevelSolo` |
| 731 | 1 | `uint8` | `m_affectsLicenceLevelMP` |
| 732 | 1 | `uint8` | `m_numSessionsInWeekend` |
| 733 | 12 | `uint8[12]` | `m_weekendStructure` |
| 745 | 4 | `float` | `m_sector2LapDistanceStart` |
| 749 | 4 | `float` | `m_sector3LapDistanceStart` |
| **753** | | | *total* |

Sub-struct Python: MarshalZone `<fb` (calcsize = 5), WeatherForecastSample `<BBBbbbbB` (calcsize = 8).

Units and meanings: `m_trackLength` in m. `m_sessionTimeLeft` and `m_sessionDuration` in s. `m_pitSpeedLimit` in km/h. Zone starts are a lap fraction 0..1. Forecast `m_timeOffset` is in minutes. Temperatures in °C (int8). `m_timeOfDay` is minutes since midnight. `m_sector2LapDistanceStart` and `m_sector3LapDistanceStart` are in m. `m_weekendStructure` holds session-type IDs (Appendix §8.5). Only the first `m_numMarshalZones`, `m_numWeatherForecastSamples` and `m_numSessionsInWeekend` entries of their arrays are meaningful.

### 5.2 Lap Data (ID 2), 1285 bytes, rate as set in menus

```c
struct LapData
{
    uint32      m_lastLapTimeInMS;              // Last lap time in milliseconds
    uint32      m_currentLapTimeInMS;           // Current time around the lap in milliseconds
    uint16      m_sector1TimeMSPart;            // Sector 1 time milliseconds part
    uint8       m_sector1TimeMinutesPart;       // Sector 1 whole minute part
    uint16      m_sector2TimeMSPart;            // Sector 2 time milliseconds part
    uint8       m_sector2TimeMinutesPart;       // Sector 2 whole minute part
    uint16      m_deltaToCarInFrontMSPart;      // Time delta to car in front milliseconds part
    uint8       m_deltaToCarInFrontMinutesPart; // Time delta to car in front whole minute part
    uint16      m_deltaToRaceLeaderMSPart;      // Time delta to race leader milliseconds part
    uint8       m_deltaToRaceLeaderMinutesPart; // Time delta to race leader whole minute part
    float       m_lapDistance;                  // Distance vehicle is around current lap in metres – could be negative if line hasn’t been crossed yet
    float       m_totalDistance;                // Total distance travelled in session in metres – could be negative if line hasn’t been crossed yet
    float       m_safetyCarDelta;               // Delta in seconds for safety car
    uint8       m_carPosition;                  // Car race position
    uint8       m_currentLapNum;                // Current lap number
    uint8       m_pitStatus;                    // 0 = none, 1 = pitting, 2 = in pit area
    uint8       m_numPitStops;                  // Number of pit stops taken in this race
    uint8       m_sector;                       // 0 = sector1, 1 = sector2, 2 = sector3
    uint8       m_currentLapInvalid;            // Current lap invalid - 0 = valid, 1 = invalid
    uint8       m_penalties;                    // Accumulated time penalties in seconds to be added
    uint8       m_totalWarnings;                // Accumulated number of warnings issued
    uint8       m_cornerCuttingWarnings;        // Accumulated number of corner cutting warnings issued
    uint8       m_numUnservedDriveThroughPens;  // Num drive through pens left to serve
    uint8       m_numUnservedStopGoPens;        // Num stop go pens left to serve
    uint8       m_gridPosition;                 // Grid position the vehicle started the race in
    uint8       m_driverStatus;                 // Status of driver - 0 = in garage, 1 = flying lap, 2 = in lap, 3 = out lap, 4 = on track
    uint8       m_resultStatus;                 // Result status - 0 = invalid, 1 = inactive, 2 = active, 3 = finished, 4 = didnotfinish, 5 = disqualified, 6 = not classified, 7 = retired
    uint8       m_pitLaneTimerActive;           // Pit lane timing, 0 = inactive, 1 = active
    uint16      m_pitLaneTimeInLaneInMS;        // If active, the current time spent in the pit lane in ms
    uint16      m_pitStopTimerInMS;             // Time of the actual pit stop in ms
    uint8       m_pitStopShouldServePen;        // Whether the car should serve a penalty at this stop
    float       m_speedTrapFastestSpeed;        // Fastest speed through speed trap for this car in kmph
    uint8       m_speedTrapFastestLap;          // Lap no the fastest speed was achieved, 255 = not set
};
```

```c
struct PacketLapData
{
    PacketHeader    m_header;               // Header

    // Packet specific data
    LapData     m_lapData[cs_maxNumCarsInUDPData];      // Lap data for all cars on track

    uint8       m_timeTrialPBCarIdx;                    // Index of Personal Best car in time trial (255 if invalid)
    uint8       m_timeTrialRivalCarIdx;                 // Index of Rival car in time trial (255 if invalid)
};
```

`LapData` offsets (stride 57; car *i* at `29 + 57*i`; `m_timeTrialPBCarIdx` at 1283, `m_timeTrialRivalCarIdx` at 1284):

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 4 | `uint32` | `m_lastLapTimeInMS` |
| 4 | 4 | `uint32` | `m_currentLapTimeInMS` |
| 8 | 2 | `uint16` | `m_sector1TimeMSPart` |
| 10 | 1 | `uint8` | `m_sector1TimeMinutesPart` |
| 11 | 2 | `uint16` | `m_sector2TimeMSPart` |
| 13 | 1 | `uint8` | `m_sector2TimeMinutesPart` |
| 14 | 2 | `uint16` | `m_deltaToCarInFrontMSPart` |
| 16 | 1 | `uint8` | `m_deltaToCarInFrontMinutesPart` |
| 17 | 2 | `uint16` | `m_deltaToRaceLeaderMSPart` |
| 19 | 1 | `uint8` | `m_deltaToRaceLeaderMinutesPart` |
| 20 | 4 | `float` | `m_lapDistance` |
| 24 | 4 | `float` | `m_totalDistance` |
| 28 | 4 | `float` | `m_safetyCarDelta` |
| 32 | 1 | `uint8` | `m_carPosition` |
| 33 | 1 | `uint8` | `m_currentLapNum` |
| 34 | 1 | `uint8` | `m_pitStatus` |
| 35 | 1 | `uint8` | `m_numPitStops` |
| 36 | 1 | `uint8` | `m_sector` |
| 37 | 1 | `uint8` | `m_currentLapInvalid` |
| 38 | 1 | `uint8` | `m_penalties` |
| 39 | 1 | `uint8` | `m_totalWarnings` |
| 40 | 1 | `uint8` | `m_cornerCuttingWarnings` |
| 41 | 1 | `uint8` | `m_numUnservedDriveThroughPens` |
| 42 | 1 | `uint8` | `m_numUnservedStopGoPens` |
| 43 | 1 | `uint8` | `m_gridPosition` |
| 44 | 1 | `uint8` | `m_driverStatus` |
| 45 | 1 | `uint8` | `m_resultStatus` |
| 46 | 1 | `uint8` | `m_pitLaneTimerActive` |
| 47 | 2 | `uint16` | `m_pitLaneTimeInLaneInMS` |
| 49 | 2 | `uint16` | `m_pitStopTimerInMS` |
| 51 | 1 | `uint8` | `m_pitStopShouldServePen` |
| 52 | 4 | `float` | `m_speedTrapFastestSpeed` |
| 56 | 1 | `uint8` | `m_speedTrapFastestLap` |
| **57** | | | *total* |

Python per-car: `<IIHBHBHBHBfffBBBBBBBBBBBBBBBHHBfB` (calcsize = 57)

Units and meanings:
- Sector times and deltas are split into `ms part` (uint16) plus `minutes part` (uint8). Full value = `minutes*60000 + msPart` in ms.
- `m_lapDistance` and `m_totalDistance` are in m and "could be negative if line hasn't been crossed yet".
- `m_safetyCarDelta` is in s. `m_penalties` is accumulated time penalties in s. `m_speedTrapFastestSpeed` is in km/h. `m_speedTrapFastestLap` is 255 if not set.
- `m_pitStatus`: 0 none, 1 pitting, 2 in pit area. `m_sector`: 0/1/2 = S1/S2/S3. `m_currentLapInvalid`: 0 valid, 1 invalid.
- `m_driverStatus`: 0 in garage, 1 flying lap, 2 in lap, 3 out lap, 4 on track.
- `m_resultStatus`: 0 invalid, 1 inactive, 2 active, 3 finished, 4 didnotfinish, 5 disqualified, 6 not classified, 7 retired.
- `m_pitLaneTimeInLaneInMS` and `m_pitStopTimerInMS` are in ms. `m_timeTrialPBCarIdx` and `m_timeTrialRivalCarIdx` are 255 if invalid.

### 5.3 Event (ID 3), 45 bytes, when the event occurs

The union is always transmitted as 12 bytes (its largest member, `SpeedTrap`), so the packet is always 45 bytes.
Interpret the payload only according to `m_eventStringCode`.

```c
static const uint cs_eventStringCodeLen = 4;
```

```c
union EventDataDetails
{
    struct
    {
        uint8 vehicleIdx; // Vehicle index of car achieving fastest lap
        float lapTime;    // Lap time is in seconds
    } FastestLap;

    struct
    {
        uint8 vehicleIdx; // Vehicle index of car retiring
        uint8 reason;     // Result reason - 0 = invalid, 1 = retired, 2 = finished, 3 = terminal damage, 4 = inactive, 5 = not enough laps completed, 6 = black flagged
                          // 7 = red flagged, 8 = mechanical failure, 9 = session skipped, 10 = session simulated
    } Retirement;

    struct
    {
        NEuint8 reason;     // 0 = Wet track, 1 = Safety car deployed, 2 = Red flag, 3 = Min lap not reached
    } DRSDisabled;

    struct
    {
        uint8 vehicleIdx; // Vehicle index of team mate
    } TeamMateInPits;

    struct
    {
        uint8 vehicleIdx; // Vehicle index of the race winner
    } RaceWinner;

    struct
    {
        uint8 penaltyType;        // Penalty type – see Appendices
        uint8 infringementType;   // Infringement type – see Appendices
        uint8 vehicleIdx;         // Vehicle index of the car the penalty is applied to
        uint8 otherVehicleIdx;    // Vehicle index of the other car involved
        uint8 time;               // Time gained, or time spent doing action in seconds
        uint8 lapNum;             // Lap the penalty occurred on
        uint8 placesGained;       // Number of places gained by this
    } Penalty;

    struct
    {
        uint8 vehicleIdx;                 // Vehicle index of the vehicle triggering speed trap
        float speed;                      // Top speed achieved in kilometres per hour
        uint8 isOverallFastestInSession;  // Overall fastest speed in session = 1, otherwise 0
        uint8 isDriverFastestInSession;   // Fastest speed for driver in session = 1, otherwise 0
        uint8 fastestVehicleIdxInSession; // Vehicle index of the vehicle that is the fastest in this session
        float fastestSpeedInSession;      // Speed of the vehicle that is the fastest in this session
    } SpeedTrap;

    struct
    {
        uint8 numLights;                  // Number of lights showing
    } StartLights;

    struct
    {
        uint8 vehicleIdx;                 // Vehicle index of the vehicle serving drive through
    } DriveThroughPenaltyServed;

    struct
    {
        uint8 vehicleIdx;                 // Vehicle index of the vehicle serving stop go
        float stopTime;                   // Time spent serving stop go in seconds
    } StopGoPenaltyServed;

    struct
    {
        uint32 flashbackFrameIdentifier;  // Frame identifier flashed back to
        float flashbackSessionTime;       // Session time flashed back to
    } Flashback;

    struct
    {
        uint32 buttonStatus;              // Bit flags specifying which buttons are being pressed currently - see appendices
    } Buttons;

    struct
    {
        uint8 overtakingVehicleIdx;       // Vehicle index of the vehicle overtaking
        uint8 beingOvertakenVehicleIdx;   // Vehicle index of the vehicle being overtaken
    } Overtake;

    struct
    {
        uint8 safetyCarType;              // 0 = No Safety Car, 1 = Full Safety Car, 2 = Virtual Safety Car, 3 = Formation Lap Safety Car
        uint8 eventType;                  // 0 = Deployed, 1 = Returning, 2 = Returned, 3 = Resume Race
    } SafetyCar;

    struct
    {
        uint8 vehicle1Idx;                // Vehicle index of the first vehicle involved in the collision
        uint8 vehicle2Idx;                // Vehicle index of the second vehicle involved in the collision
    } Collision;
};
```

```c
struct PacketEventData
{
    // Valid event strings
    static const NEchar*    cs_sessionStartedEventCode;         // "SSTA"
    static const NEchar*    cs_sessionEndedEventCode;           // "SEND"
    static const NEchar*    cs_fastestLapEventCode;             // "FTLP"
    static const NEchar*    cs_retirementEventCode;             // "RTMT"
    static const NEchar*    cs_drsEnabledEventCode;             // "DRSE"
    static const NEchar*    cs_drsDisabledEventCode;            // "DRSD"
    static const NEchar*    cs_teamMateInPitsEventCode;         // "TMPT"
    static const NEchar*    cs_chequeredFlagEventCode;          // "CHQF"
    static const NEchar*    cs_raceWinnerEventCode;             // "RCWN"
    static const NEchar*    cs_penaltyEventCode;                // "PENA"
    static const NEchar*    cs_speedTrapEventCode;              // "SPTP"
    static const NEchar*    cs_startLightsEventCode;            // "STLG"
    static const NEchar*    cs_lightsOutEventCode;              // "LGOT"
    static const NEchar*    cs_driveThroughServedEventCode;     // "DTSV"
    static const NEchar*    cs_stopGoServedEventCode;           // "SGSV"
    static const NEchar*    cs_flashbackEventCode;              // "FLBK"
    static const NEchar*    cs_buttonStatusEventCode;           // "BUTN"
    static const NEchar*    cs_redFlagEventCode;                // "RDFL"
    static const NEchar*    cs_overtakeEventCode;               // "OVTK"
    static const NEchar*    cs_safetyCarEventCode;              // "SCAR"
    static const NEchar*    cs_collisionEventCode;              // "COLL"

    PacketHeader        m_header;               // Header

    // Packet specific data
    uint8               m_eventStringCode[cs_eventStringCodeLen];       // Event string code
    EventDataDetails    m_eventDetails;                                 // Event details - should be interpreted differently for each type
};
```

Offsets: header 0-28, `m_eventStringCode` 29-32 (4 ASCII bytes, not null-terminated), `m_eventDetails` 33-44.
Union member sizes (2025): FastestLap 5, Retirement 2, DRSDisabled 1, TeamMateInPits 1, RaceWinner 1, Penalty 7, SpeedTrap 12,
StartLights 1, DriveThroughPenaltyServed 1, StopGoPenaltyServed 5, Flashback 8, Buttons 4, Overtake 2, SafetyCar 2, Collision 2.

Event codes and payloads (2025):

| Code | Event (PDF description) | Payload member | Python fmt (at offset 33) |
|---|---|---|---|
| `SSTA` | Session Started: sent when the session starts | none | |
| `SEND` | Session Ended: sent when the session ends | none | |
| `FTLP` | Fastest Lap: when a driver achieves the fastest lap | FastestLap {vehicleIdx, lapTime s} | `<Bf` |
| `RTMT` | Retirement: when a driver retires | Retirement {vehicleIdx, reason} | `<BB` |
| `DRSE` | DRS enabled by race control | none | |
| `DRSD` | DRS disabled by race control | DRSDisabled {reason} | `<B` |
| `TMPT` | Team mate in pits: your team mate has entered the pits | TeamMateInPits {vehicleIdx} | `<B` |
| `CHQF` | Chequered flag has been waved | none | |
| `RCWN` | Race Winner announced | RaceWinner {vehicleIdx} | `<B` |
| `PENA` | Penalty Issued (details in event) | Penalty {penaltyType, infringementType, vehicleIdx, otherVehicleIdx, time, lapNum, placesGained} | `<7B` |
| `SPTP` | Speed Trap triggered by fastest speed | SpeedTrap {vehicleIdx, speed km/h, isOverallFastestInSession, isDriverFastestInSession, fastestVehicleIdxInSession, fastestSpeedInSession} | `<BfBBBf` |
| `STLG` | Start lights: number shown | StartLights {numLights} | `<B` |
| `LGOT` | Lights out | none | |
| `DTSV` | Drive through penalty served | DriveThroughPenaltyServed {vehicleIdx} | `<B` |
| `SGSV` | Stop go penalty served | StopGoPenaltyServed {vehicleIdx, stopTime s} | `<Bf` |
| `FLBK` | Flashback activated | Flashback {flashbackFrameIdentifier, flashbackSessionTime} | `<If` |
| `BUTN` | Button status changed | Buttons {buttonStatus bit flags, Appendix §8.9} | `<I` |
| `RDFL` | Red Flag shown | none | |
| `OVTK` | Overtake occurred | Overtake {overtakingVehicleIdx, beingOvertakenVehicleIdx} | `<BB` |
| `SCAR` | Safety car event (details in event) | SafetyCar {safetyCarType, eventType} | `<BB` |
| `COLL` | Collision between two vehicles | Collision {vehicle1Idx, vehicle2Idx} | `<BB` (2026: `<BBB`) |

Payload enums: Retirement `reason` and DRSD `reason` are in §8.12. `safetyCarType`: 0 none, 1 full, 2 virtual, 3 formation-lap SC. `eventType`: 0 deployed, 1 returning, 2 returned, 3 resume race.
Penalty and infringement types are in §8.10 and §8.11. Penalty `time` is "time gained, or time spent doing action in seconds".
Observed (community, not in the spec): optional u8 fields are 255 when not applicable (e.g. `time` on a warning).

### 5.4 Participants (ID 4), 1284 bytes, every 5 seconds

```c
struct LiveryColour
{
    uint8       red;
    uint8       green;
    uint8       blue;
};
```

```c
struct ParticipantData
{
    uint8           m_aiControlled;                     // Whether the vehicle is AI (1) or Human (0) controlled
    uint8           m_driverId;                         // Driver id - see appendix, 255 if network human
    uint8           m_networkId;                        // Network id - unique identifier for network players
    uint8           m_teamId;                           // Team id - see appendix
    uint8           m_myTeam;                           // My team flag - 1 = My Team, 0 = otherwise
    uint8           m_raceNumber;                       // Race number of the car
    uint8           m_nationality;                      // Nationality of the driver
    char            m_name[cs_maxParticipantNameLen];   // Name of participant in UTF-8 format – null terminated
                                                        // Will be truncated with ... (U+2026) if too long
    uint8           m_yourTelemetry;                    // The player's UDP setting, 0 = restricted, 1 = public
    uint8           m_showOnlineNames;                  // The player's show online names setting, 0 = off, 1 = on
    uint16          m_techLevel;                        // F1 World tech level
    uint8           m_platform;                         // 1 = Steam, 3 = PlayStation, 4 = Xbox, 6 = Origin, 255 = unknown
    uint8           m_numColours;                       // Number of colours valid for this car
    LiveryColour    m_liveryColours[4];                 // Colours for the car
};
```

```c
struct PacketParticipantsData
{
    PacketHeader    m_header;                       // Header

    // Packet specific data
    uint8               m_numActiveCars;            // Number of active cars in the data - should match number of cars on HUD
    ParticipantData     m_participants[cs_maxNumCarsInUDPData];
};
```

`ParticipantData` offsets (stride 57; car *i* at `30 + 57*i`; `m_numActiveCars` at 29):

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 1 | `uint8` | `m_aiControlled` |
| 1 | 1 | `uint8` | `m_driverId` |
| 2 | 1 | `uint8` | `m_networkId` |
| 3 | 1 | `uint8` | `m_teamId` |
| 4 | 1 | `uint8` | `m_myTeam` |
| 5 | 1 | `uint8` | `m_raceNumber` |
| 6 | 1 | `uint8` | `m_nationality` |
| 7 | 32 | `char[32]` | `m_name` |
| 39 | 1 | `uint8` | `m_yourTelemetry` |
| 40 | 1 | `uint8` | `m_showOnlineNames` |
| 41 | 2 | `uint16` | `m_techLevel` |
| 43 | 1 | `uint8` | `m_platform` |
| 44 | 1 | `uint8` | `m_numColours` |
| 45 | 12 | `LiveryColour[4]` | `m_liveryColours` |
| **57** | | | *total* |

Python per-car: `<BBBBBBB32sBBHBBBBBBBBBBBBBB` (calcsize = 57)

Meanings: `m_aiControlled` 1 = AI, 0 = human. `m_driverId` is 255 for a network human. `m_myTeam` 1 = My Team. `m_yourTelemetry` 0 restricted, 1 public. `m_showOnlineNames` 0 off, 1 on.
`m_platform`: 1 Steam, 3 PlayStation, 4 Xbox, 6 Origin, 255 unknown. `m_techLevel` is the F1 World tech level. `m_numColours` is the number of valid `m_liveryColours` entries (RGB).
Decode `m_name` as UTF-8 up to the first NUL.

### 5.5 Car Setups (ID 5), 1133 bytes, 2 per second

```c
struct CarSetupData
{
    uint8       m_frontWing;                // Front wing aero
    uint8       m_rearWing;                 // Rear wing aero
    uint8       m_onThrottle;               // Differential adjustment on throttle (percentage)
    uint8       m_offThrottle;              // Differential adjustment off throttle (percentage)
    float       m_frontCamber;              // Front camber angle (suspension geometry)
    float       m_rearCamber;               // Rear camber angle (suspension geometry)
    float       m_frontToe;                 // Front toe angle (suspension geometry)
    float       m_rearToe;                  // Rear toe angle (suspension geometry)
    uint8       m_frontSuspension;          // Front suspension
    uint8       m_rearSuspension;           // Rear suspension
    uint8       m_frontAntiRollBar;         // Front anti-roll bar
    uint8       m_rearAntiRollBar;          // Front anti-roll bar
    uint8       m_frontSuspensionHeight;    // Front ride height
    uint8       m_rearSuspensionHeight;     // Rear ride height
    uint8       m_brakePressure;            // Brake pressure (percentage)
    uint8       m_brakeBias;                // Brake bias (percentage)
    uint8       m_engineBraking;            // Engine braking (percentage)
    float       m_rearLeftTyrePressure;     // Rear left tyre pressure (PSI)
    float       m_rearRightTyrePressure;    // Rear right tyre pressure (PSI)
    float       m_frontLeftTyrePressure;    // Front left tyre pressure (PSI)
    float       m_frontRightTyrePressure;   // Front right tyre pressure (PSI)
    uint8       m_ballast;                  // Ballast
    float       m_fuelLoad;                 // Fuel load
};
```

```c
struct PacketCarSetupData
{
    PacketHeader    m_header;               // Header

    // Packet specific data
    CarSetupData    m_carSetupData[cs_maxNumCarsInUDPData];

    float           m_nextFrontWingValue;   // Value of front wing after next pit stop - player only
};
```

`CarSetupData` offsets (stride 50; car *i* at `29 + 50*i`; `m_nextFrontWingValue` float at 1129):

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 1 | `uint8` | `m_frontWing` |
| 1 | 1 | `uint8` | `m_rearWing` |
| 2 | 1 | `uint8` | `m_onThrottle` |
| 3 | 1 | `uint8` | `m_offThrottle` |
| 4 | 4 | `float` | `m_frontCamber` |
| 8 | 4 | `float` | `m_rearCamber` |
| 12 | 4 | `float` | `m_frontToe` |
| 16 | 4 | `float` | `m_rearToe` |
| 20 | 1 | `uint8` | `m_frontSuspension` |
| 21 | 1 | `uint8` | `m_rearSuspension` |
| 22 | 1 | `uint8` | `m_frontAntiRollBar` |
| 23 | 1 | `uint8` | `m_rearAntiRollBar` |
| 24 | 1 | `uint8` | `m_frontSuspensionHeight` |
| 25 | 1 | `uint8` | `m_rearSuspensionHeight` |
| 26 | 1 | `uint8` | `m_brakePressure` |
| 27 | 1 | `uint8` | `m_brakeBias` |
| 28 | 1 | `uint8` | `m_engineBraking` |
| 29 | 4 | `float` | `m_rearLeftTyrePressure` |
| 33 | 4 | `float` | `m_rearRightTyrePressure` |
| 37 | 4 | `float` | `m_frontLeftTyrePressure` |
| 41 | 4 | `float` | `m_frontRightTyrePressure` |
| 45 | 1 | `uint8` | `m_ballast` |
| 46 | 4 | `float` | `m_fuelLoad` |
| **50** | | | *total* |

Python per-car: `<BBBBffffBBBBBBBBBffffBf` (calcsize = 50)

Units: tyre pressures in PSI. Differential, brake pressure, brake bias and engine braking in %. Camber and toe are angles (unit not stated). Fuel load unit not stated (kg in practice).
EA's comment on `m_rearAntiRollBar` says "Front anti-roll bar". This is a copy-paste typo in the spec; the field is the rear ARB.

### 5.6 Car Telemetry (ID 6), 1352 bytes, rate as set in menus

```c
struct CarTelemetryData
{
    uint16      m_speed;                        // Speed of car in kilometres per hour
    float       m_throttle;                     // Amount of throttle applied (0.0 to 1.0)
    float       m_steer;                        // Steering (-1.0 (full lock left) to 1.0 (full lock right))
    float       m_brake;                        // Amount of brake applied (0.0 to 1.0)
    uint8       m_clutch;                       // Amount of clutch applied (0 to 100)
    int8        m_gear;                         // Gear selected (1-8, N=0, R=-1)
    uint16      m_engineRPM;                    // Engine RPM
    uint8       m_drs;                          // 0 = off, 1 = on
    uint8       m_revLightsPercent;             // Rev lights indicator (percentage)
    uint16      m_revLightsBitValue;            // Rev lights (bit 0 = leftmost LED, bit 14 = rightmost LED)
    uint16      m_brakesTemperature[4];         // Brakes temperature (celsius)
    uint8       m_tyresSurfaceTemperature[4];   // Tyres surface temperature (celsius)
    uint8       m_tyresInnerTemperature[4];     // Tyres inner temperature (celsius)
    uint16      m_engineTemperature;            // Engine temperature (celsius)
    float       m_tyresPressure[4];             // Tyre pressure (PSI)
    uint8       m_surfaceType[4];               // Driving surface, see appendices
};
```

```c
struct PacketCarTelemetryData
{
    PacketHeader        m_header;               // Header

    // Packet specific data
    CarTelemetryData    m_carTelemetryData[cs_maxNumCarsInUDPData];   // data for all cars on track

    uint8               m_mfdPanelIndex;                // Index of MFD panel open - 255 = MFD closed
                                                        // Single player, race – 0 = Car setup, 1 = Pits
                                                        // 2 = Damage, 3 =  Engine, 4 = Temperatures
                                                        // May vary depending on game mode
    uint8               m_mfdPanelIndexSecondaryPlayer; // See above
    int8                m_suggestedGear;                // Suggested gear for the player (1-8), 0 if no gear suggested
};
```

`CarTelemetryData` offsets (stride 60; car *i* at `29 + 60*i`; trailer at 1349 = `m_mfdPanelIndex`, 1350 = `m_mfdPanelIndexSecondaryPlayer`, 1351 = `m_suggestedGear` int8):

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 2 | `uint16` | `m_speed` |
| 2 | 4 | `float` | `m_throttle` |
| 6 | 4 | `float` | `m_steer` |
| 10 | 4 | `float` | `m_brake` |
| 14 | 1 | `uint8` | `m_clutch` |
| 15 | 1 | `int8` | `m_gear` |
| 16 | 2 | `uint16` | `m_engineRPM` |
| 18 | 1 | `uint8` | `m_drs` |
| 19 | 1 | `uint8` | `m_revLightsPercent` |
| 20 | 2 | `uint16` | `m_revLightsBitValue` |
| 22 | 8 | `uint16[4]` | `m_brakesTemperature` |
| 30 | 4 | `uint8[4]` | `m_tyresSurfaceTemperature` |
| 34 | 4 | `uint8[4]` | `m_tyresInnerTemperature` |
| 38 | 2 | `uint16` | `m_engineTemperature` |
| 40 | 16 | `float[4]` | `m_tyresPressure` |
| 56 | 4 | `uint8[4]` | `m_surfaceType` |
| **60** | | | *total* |

Python per-car: `<HfffBbHBBH4H4B4BH4f4B` (calcsize = 60), trailer `<BBb`

Units and meanings:
- `m_speed` in **km/h** (uint16). `m_throttle` 0.0..1.0. `m_steer` −1.0 (full lock left) .. +1.0 (full lock right). `m_brake` 0.0..1.0. `m_clutch` 0..100.
- `m_gear`: 1-8, N = 0, R = −1. `m_engineRPM` in rpm. `m_drs`: 0 off, 1 on.
- `m_revLightsPercent` in %. `m_revLightsBitValue`: bit 0 = leftmost LED, bit 14 = rightmost.
- Temperatures in °C: brakes as uint16[4], tyre surface and inner as uint8[4], engine as uint16 (uint8 in 2026).
- `m_tyresPressure` in PSI. `m_surfaceType[4]` per wheel, see §8.8.
- `m_mfdPanelIndex`: 255 = MFD closed. In single-player race: 0 car setup, 1 pits, 2 damage, 3 engine, 4 temperatures ("may vary depending on game mode").
- `m_suggestedGear`: 1-8, 0 if no suggestion.

### 5.7 Car Status (ID 7), 1239 bytes, rate as set in menus

```c
struct CarStatusData
{
    uint8       m_tractionControl;                  // Traction control - 0 = off, 1 = medium, 2 = full
    uint8       m_antiLockBrakes;                   // 0 (off) - 1 (on)
    uint8       m_fuelMix;                          // Fuel mix - 0 = lean, 1 = standard, 2 = rich, 3 = max
    uint8       m_frontBrakeBias;                   // Front brake bias (percentage)
    uint8       m_pitLimiterStatus;                 // Pit limiter status - 0 = off, 1 = on
    float       m_fuelInTank;                       // Current fuel mass
    float       m_fuelCapacity;                     // Fuel capacity
    float       m_fuelRemainingLaps;                // Fuel remaining in terms of laps (value on MFD)
    uint16      m_maxRPM;                           // Cars max RPM, point of rev limiter
    uint16      m_idleRPM;                          // Cars idle RPM
    uint8       m_maxGears;                         // Maximum number of gears
    uint8       m_drsAllowed;                       // 0 = not allowed, 1 = allowed
    uint16      m_drsActivationDistance;            // 0 = DRS not available, non-zero - DRS will be available in [X] metres
    uint8       m_actualTyreCompound;               // F1 Modern - 16 = C5, 17 = C4, 18 = C3, 19 = C2, 20 = C1, 21 = C0, 22 = C6, 7 = inter, 8 = wet
                                                    // F1 Classic - 9 = dry, 10 = wet
                                                    // F2 – 11 = super soft, 12 = soft, 13 = medium, 14 = hard, 15 = wet
    uint8       m_visualTyreCompound;               // F1 visual (can be different from actual compound)
                                                    // 16 = soft, 17 = medium, 18 = hard, 7 = inter, 8 = wet
                                                    // F1 Classic – same as above
                                                    // F2 ‘20, 15 = wet, 19 – super soft, 20 = soft, 21 = medium, 22 = hard
    uint8       m_tyresAgeLaps;                     // Age in laps of the current set of tyres
    int8        m_vehicleFIAFlags;                  // -1 = invalid/unknown, 0 = none, 1 = green, 2 = blue, 3 = yellow
    float       m_enginePowerICE;                   // Engine power output of ICE (W)
    float       m_enginePowerMGUK;                  // Engine power output of MGU-K (W)
    float       m_ersStoreEnergy;                   // ERS energy store in Joules
    uint8       m_ersDeployMode;                    // ERS deployment mode, 0 = none, 1 = medium, 2 = hotlap, 3 = overtake
    float       m_ersHarvestedThisLapMGUK;          // ERS energy harvested this lap by MGU-K
    float       m_ersHarvestedThisLapMGUH;          // ERS energy harvested this lap by MGU-H
    float       m_ersDeployedThisLap;               // ERS energy deployed this lap
    uint8       m_networkPaused;                    // Whether the car is paused in a network game
};
```

```c
struct PacketCarStatusData
{
    PacketHeader    m_header;               // Header

    // Packet specific data
    CarStatusData       m_carStatusData[cs_maxNumCarsInUDPData];      // data for all cars on track
};
```

`CarStatusData` offsets (stride 55; car *i* at `29 + 55*i`):

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 1 | `uint8` | `m_tractionControl` |
| 1 | 1 | `uint8` | `m_antiLockBrakes` |
| 2 | 1 | `uint8` | `m_fuelMix` |
| 3 | 1 | `uint8` | `m_frontBrakeBias` |
| 4 | 1 | `uint8` | `m_pitLimiterStatus` |
| 5 | 4 | `float` | `m_fuelInTank` |
| 9 | 4 | `float` | `m_fuelCapacity` |
| 13 | 4 | `float` | `m_fuelRemainingLaps` |
| 17 | 2 | `uint16` | `m_maxRPM` |
| 19 | 2 | `uint16` | `m_idleRPM` |
| 21 | 1 | `uint8` | `m_maxGears` |
| 22 | 1 | `uint8` | `m_drsAllowed` |
| 23 | 2 | `uint16` | `m_drsActivationDistance` |
| 25 | 1 | `uint8` | `m_actualTyreCompound` |
| 26 | 1 | `uint8` | `m_visualTyreCompound` |
| 27 | 1 | `uint8` | `m_tyresAgeLaps` |
| 28 | 1 | `int8` | `m_vehicleFIAFlags` |
| 29 | 4 | `float` | `m_enginePowerICE` |
| 33 | 4 | `float` | `m_enginePowerMGUK` |
| 37 | 4 | `float` | `m_ersStoreEnergy` |
| 41 | 1 | `uint8` | `m_ersDeployMode` |
| 42 | 4 | `float` | `m_ersHarvestedThisLapMGUK` |
| 46 | 4 | `float` | `m_ersHarvestedThisLapMGUH` |
| 50 | 4 | `float` | `m_ersDeployedThisLap` |
| 54 | 1 | `uint8` | `m_networkPaused` |
| **55** | | | *total* |

Python per-car: `<BBBBBfffHHBBHBBBbfffBfffB` (calcsize = 55)

Meanings:
- `m_tractionControl`: 0 off, 1 medium, 2 full. `m_antiLockBrakes`: 0 off, 1 on. `m_fuelMix`: 0 lean, 1 standard, 2 rich, 3 max. `m_frontBrakeBias` in %. `m_pitLimiterStatus`: 0/1.
- `m_fuelInTank` is "current fuel mass" and `m_fuelCapacity` is the capacity (kg in practice; no unit stated). `m_fuelRemainingLaps` is the value shown on the MFD.
- `m_maxRPM` (rev limiter) and `m_idleRPM` in rpm. `m_drsAllowed`: 0/1. `m_drsActivationDistance`: 0 = not available, else metres until available.
- Tyre compounds (actual vs visual): see §8.13. `m_tyresAgeLaps` is laps on the current set.
- `m_vehicleFIAFlags`: −1 invalid/unknown, 0 none, 1 green, 2 blue, 3 yellow.
- `m_enginePowerICE` and `m_enginePowerMGUK` in **W**. `m_ersStoreEnergy` in **J**. `m_ersDeployMode`: 0 none, 1 medium, 2 hotlap, 3 overtake (renamed "boost" in 2026). Harvested and deployed this lap: J (by context).
- `m_networkPaused`: car paused in a network game.

### 5.8 Final Classification (ID 8), 1042 bytes, once at the end of a race

```c
struct FinalClassificationData
{
    uint8       m_position;                             // Finishing position
    uint8       m_numLaps;                              // Number of laps completed
    uint8       m_gridPosition;                         // Grid position of the car
    uint8       m_points;                               // Number of points scored
    uint8       m_numPitStops;                          // Number of pit stops made
    uint8       m_resultStatus;                         // Result status - 0 = invalid, 1 = inactive, 2 = active, 3 = finished, 4 = didnotfinish, 5 = disqualified, 6 = not classified, 7 = retired
    uint8       m_resultReason;                         // Result reason - 0 = invalid, 1 = retired, 2 = finished, 3 = terminal damage, 4 = inactive, 5 = not enough laps completed, 6 = black flagged
                                                        // 7 = red flagged, 8 = mechanical failure, 9 = session skipped, 10 = session simulated
    uint32      m_bestLapTimeInMS;                      // Best lap time of the session in milliseconds
    double      m_totalRaceTime;                        // Total race time in seconds without penalties
    uint8       m_penaltiesTime;                        // Total penalties accumulated in seconds
    uint8       m_numPenalties;                         // Number of penalties applied to this driver
    uint8       m_numTyreStints;                        // Number of tyres stints up to maximum
    uint8       m_tyreStintsActual[cs_maxTyreStints];   // Actual tyres used by this driver
    uint8       m_tyreStintsVisual[cs_maxTyreStints];   // Visual tyres used by this driver
    uint8       m_tyreStintsEndLaps[cs_maxTyreStints];  // The lap number stints end on
};
```

```c
struct PacketFinalClassificationData
{
    PacketHeader    m_header;               // Header

    // Packet specific data
    uint8                       m_numCars;          // Number of cars in the final classification
    FinalClassificationData     m_classificationData[cs_maxNumCarsInUDPData];
};
```

`FinalClassificationData` offsets (stride 46; car *i* at `30 + 46*i`; `m_numCars` at 29):

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 1 | `uint8` | `m_position` |
| 1 | 1 | `uint8` | `m_numLaps` |
| 2 | 1 | `uint8` | `m_gridPosition` |
| 3 | 1 | `uint8` | `m_points` |
| 4 | 1 | `uint8` | `m_numPitStops` |
| 5 | 1 | `uint8` | `m_resultStatus` |
| 6 | 1 | `uint8` | `m_resultReason` |
| 7 | 4 | `uint32` | `m_bestLapTimeInMS` |
| 11 | 8 | `double` | `m_totalRaceTime` |
| 19 | 1 | `uint8` | `m_penaltiesTime` |
| 20 | 1 | `uint8` | `m_numPenalties` |
| 21 | 1 | `uint8` | `m_numTyreStints` |
| 22 | 8 | `uint8[8]` | `m_tyreStintsActual` |
| 30 | 8 | `uint8[8]` | `m_tyreStintsVisual` |
| 38 | 8 | `uint8[8]` | `m_tyreStintsEndLaps` |
| **46** | | | *total* |

Python per-car: `<BBBBBBBIdBBB8B8B8B` (calcsize = 46)

Meanings: `m_bestLapTimeInMS` in ms. `m_totalRaceTime` in s (double) **without** penalties. `m_penaltiesTime` in s. Tyre stint arrays hold compound IDs (§8.13) and the lap each stint ended on.
The spec says this data "will match with the post race results screen".
Observed (community): the packet is also emitted after qualifying, with values that are not meaningful (stale points, lap time in `m_totalRaceTime`). Gate on the session type.

### 5.9 Lobby Info (ID 9), 954 bytes, two per second while in a lobby

```c
struct LobbyInfoData
{
    uint8       m_aiControlled;                     // Whether the vehicle is AI (1) or Human (0) controlled
    uint8       m_teamId;                           // Team id - see appendix (255 if no team currently selected)
    uint8       m_nationality;                      // Nationality of the driver
    uint8       m_platform;                         // 1 = Steam, 3 = PlayStation, 4 = Xbox, 6 = Origin, 255 = unknown
    char        m_name[cs_maxParticipantNameLen];   // Name of participant in UTF-8 format – null terminated
                                                    // Will be truncated with ... (U+2026) if too long
    uint8       m_carNumber;                        // Car number of the player
    uint8       m_yourTelemetry;                    // The player's UDP setting, 0 = restricted, 1 = public
    uint8       m_showOnlineNames;                  // The player's show online names setting, 0 = off, 1 = on
    uint16      m_techLevel;                        // F1 World tech level
    uint8       m_readyStatus;                      // 0 = not ready, 1 = ready, 2 = spectating
};
```

```c
struct PacketLobbyInfoData
{
    PacketHeader    m_header;                       // Header

    // Packet specific data
    uint8               m_numPlayers;               // Number of players in the lobby data
    LobbyInfoData       m_lobbyPlayers[cs_maxNumCarsInUDPData];
};
```

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 1 | `uint8` | `m_aiControlled` |
| 1 | 1 | `uint8` | `m_teamId` |
| 2 | 1 | `uint8` | `m_nationality` |
| 3 | 1 | `uint8` | `m_platform` |
| 4 | 32 | `char[32]` | `m_name` |
| 36 | 1 | `uint8` | `m_carNumber` |
| 37 | 1 | `uint8` | `m_yourTelemetry` |
| 38 | 1 | `uint8` | `m_showOnlineNames` |
| 39 | 2 | `uint16` | `m_techLevel` |
| 41 | 1 | `uint8` | `m_readyStatus` |
| **42** | | | *total* |

Python per-player: `<BBBB32sBBBHB` (calcsize = 42). Field meanings: `m_teamId` is 255 if no team is selected; `m_readyStatus` 0 not ready, 1 ready, 2 spectating.

### 5.10 Car Damage (ID 10), 1041 bytes, 10 per second

```c
struct CarDamageData
{
    float       m_tyresWear[4];                     // Tyre wear (percentage)
    uint8       m_tyresDamage[4];                   // Tyre damage (percentage)
    uint8       m_brakesDamage[4];                  // Brakes damage (percentage)
    uint8       m_tyreBlisters[4];                  // Tyre blisters value (percentage)
    uint8       m_frontLeftWingDamage;              // Front left wing damage (percentage)
    uint8       m_frontRightWingDamage;             // Front right wing damage (percentage)
    uint8       m_rearWingDamage;                   // Rear wing damage (percentage)
    uint8       m_floorDamage;                      // Floor damage (percentage)
    uint8       m_diffuserDamage;                   // Diffuser damage (percentage)
    uint8       m_sidepodDamage;                    // Sidepod damage (percentage)
    uint8       m_drsFault;                         // Indicator for DRS fault, 0 = OK, 1 = fault
    uint8       m_ersFault;                         // Indicator for ERS fault, 0 = OK, 1 = fault
    uint8       m_gearBoxDamage;                    // Gear box damage (percentage)
    uint8       m_engineDamage;                     // Engine damage (percentage)
    uint8       m_engineMGUHWear;                   // Engine wear MGU-H (percentage)
    uint8       m_engineESWear;                     // Engine wear ES (percentage)
    uint8       m_engineCEWear;                     // Engine wear CE (percentage)
    uint8       m_engineICEWear;                    // Engine wear ICE (percentage)
    uint8       m_engineMGUKWear;                   // Engine wear MGU-K (percentage)
    uint8       m_engineTCWear;                     // Engine wear TC (percentage)
    uint8       m_engineBlown;                      // Engine blown, 0 = OK, 1 = fault
    uint8       m_engineSeized;                     // Engine seized, 0 = OK, 1 = fault
};
```

```c
struct PacketCarDamageData
{
    PacketHeader    m_header;               // Header

    // Packet specific data
    CarDamageData   m_carDamageData[cs_maxNumCarsInUDPData];      // data for all cars on track
};
```

`CarDamageData` offsets (stride 46; car *i* at `29 + 46*i`):

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 16 | `float[4]` | `m_tyresWear` |
| 16 | 4 | `uint8[4]` | `m_tyresDamage` |
| 20 | 4 | `uint8[4]` | `m_brakesDamage` |
| 24 | 4 | `uint8[4]` | `m_tyreBlisters` |
| 28 | 1 | `uint8` | `m_frontLeftWingDamage` |
| 29 | 1 | `uint8` | `m_frontRightWingDamage` |
| 30 | 1 | `uint8` | `m_rearWingDamage` |
| 31 | 1 | `uint8` | `m_floorDamage` |
| 32 | 1 | `uint8` | `m_diffuserDamage` |
| 33 | 1 | `uint8` | `m_sidepodDamage` |
| 34 | 1 | `uint8` | `m_drsFault` |
| 35 | 1 | `uint8` | `m_ersFault` |
| 36 | 1 | `uint8` | `m_gearBoxDamage` |
| 37 | 1 | `uint8` | `m_engineDamage` |
| 38 | 1 | `uint8` | `m_engineMGUHWear` |
| 39 | 1 | `uint8` | `m_engineESWear` |
| 40 | 1 | `uint8` | `m_engineCEWear` |
| 41 | 1 | `uint8` | `m_engineICEWear` |
| 42 | 1 | `uint8` | `m_engineMGUKWear` |
| 43 | 1 | `uint8` | `m_engineTCWear` |
| 44 | 1 | `uint8` | `m_engineBlown` |
| 45 | 1 | `uint8` | `m_engineSeized` |
| **46** | | | *total* |

Python per-car: `<4f4B4B4BBBBBBBBBBBBBBBBBBB` (calcsize = 46)

All damage and wear values are percentages. `m_tyresWear` is float % (the in-game display is reported by users to read roughly double the telemetry value; this is not in the spec). `m_drsFault`, `m_ersFault`, `m_engineBlown` and `m_engineSeized` are 0 OK / 1 fault.

### 5.11 Session History (ID 11), 1460 bytes, 20 per second cycling through cars

The spec says: "each packet relates to a specific vehicle and is sent every 1/20 s, and the vehicle being sent is cycled through. Therefore in a 20 car race you should receive an update for each vehicle at least once per second." After the Final Classification packet, the game sends a final bulk update of all session histories.

```c
static const uint     cs_maxNumLapsInHistory = 100;
```

```c
struct LapHistoryData
{
    uint32      m_lapTimeInMS;              // Lap time in milliseconds
    uint16      m_sector1TimeMSPart;        // Sector 1 milliseconds part
    uint8       m_sector1TimeMinutesPart;   // Sector 1 whole minute part
    uint16      m_sector2TimeMSPart;        // Sector 2 time milliseconds part
    uint8       m_sector2TimeMinutesPart;   // Sector 2 whole minute part
    uint16      m_sector3TimeMSPart;        // Sector 3 time milliseconds part
    uint8       m_sector3TimeMinutesPart;   // Sector 3 whole minute part
    uint8       m_lapValidBitFlags;         // 0x01 bit set-lap valid,      0x02 bit set-sector 1 valid
                                            // 0x04 bit set-sector 2 valid, 0x08 bit set-sector 3 valid
};
```

```c
struct TyreStintHistoryData
{
    uint8       m_endLap;               // Lap the tyre usage ends on (255 if current tyre)
    uint8       m_tyreActualCompound;   // Actual tyres used by this driver
    uint8       m_tyreVisualCompound;   // Visual tyres used by this driver
};
```

```c
struct PacketSessionHistoryData
{
    PacketHeader    m_header;               // Header

    // Packet specific data
    uint8           m_carIdx;                   // Index of the car this lap data relates to
    uint8           m_numLaps;                  // Num laps in the data (including current partial lap)
    uint8           m_numTyreStints;            // Number of tyre stints in the data
    
    uint8           m_bestLapTimeLapNum;        // Lap the best lap time was achieved on
    uint8           m_bestSector1LapNum;        // Lap the best Sector 1 time was achieved on
    uint8           m_bestSector2LapNum;        // Lap the best Sector 2 time was achieved on
    uint8           m_bestSector3LapNum;        // Lap the best Sector 3 time was achieved on

    LapHistoryData          m_lapHistoryData[cs_maxNumLapsInHistory];   // 100 laps of data max
    TyreStintHistoryData    m_tyreStintsHistoryData[cs_maxTyreStints];
};
```

Layout: header 0-28. `m_carIdx` 29, `m_numLaps` 30, `m_numTyreStints` 31, `m_bestLapTimeLapNum` 32, `m_bestSector1LapNum` 33, `m_bestSector2LapNum` 34, `m_bestSector3LapNum` 35.
`m_lapHistoryData[100]` at 36 (stride 14, lap *n* (1-based) at `36 + 14*(n-1)`). `m_tyreStintsHistoryData[8]` at 1436 (stride 3).

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 4 | `uint32` | `m_lapTimeInMS` |
| 4 | 2 | `uint16` | `m_sector1TimeMSPart` |
| 6 | 1 | `uint8` | `m_sector1TimeMinutesPart` |
| 7 | 2 | `uint16` | `m_sector2TimeMSPart` |
| 9 | 1 | `uint8` | `m_sector2TimeMinutesPart` |
| 10 | 2 | `uint16` | `m_sector3TimeMSPart` |
| 12 | 1 | `uint8` | `m_sector3TimeMinutesPart` |
| 13 | 1 | `uint8` | `m_lapValidBitFlags` |
| **14** | | | *total* |

Python: LapHistoryData `<IHBHBHBB` (calcsize = 14), TyreStintHistoryData `<BBB` (calcsize = 3).
`m_lapValidBitFlags`: 0x01 lap valid, 0x02 S1 valid, 0x04 S2 valid, 0x08 S3 valid. Stint `m_endLap` is 255 for the current tyre. `m_numLaps` includes the current partial lap.

### 5.12 Tyre Sets (ID 12), 231 bytes, 20 per second cycling through cars

```c
struct TyreSetData
{
    uint8       m_actualTyreCompound;               // Actual tyre compound used
    uint8       m_visualTyreCompound;               // Visual tyre compound used
    uint8       m_wear;                             // Tyre wear (percentage)
    uint8       m_available;                        // Whether this set is currently available
    uint8       m_recommendedSession;               // Recommended session for tyre set, see appendix
    uint8       m_lifeSpan;                         // Laps left in this tyre set
    uint8       m_usableLife;                       // Max number of laps recommended for this compound
    int16       m_lapDeltaTime;                     // Lap delta time in milliseconds compared to fitted set
    uint8       m_fitted;                           // Whether the set is fitted or not
};
```

```c
struct PacketTyreSetsData
{
    PacketHeader    m_header;                           // Header

    uint8           m_carIdx;                           // Index of the car this data relates to

    // Packet specific data
    TyreSetData     m_tyreSetData[cs_maxNumTyreSets];   // 13 (dry) + 7 (wet)

    uint8           m_fittedIdx;                        // Index into array of fitted tyre
};
```

Layout: `m_carIdx` 29, `m_tyreSetData[20]` at 30 (stride 10; 13 dry + 7 wet), `m_fittedIdx` at 230.

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 1 | `uint8` | `m_actualTyreCompound` |
| 1 | 1 | `uint8` | `m_visualTyreCompound` |
| 2 | 1 | `uint8` | `m_wear` |
| 3 | 1 | `uint8` | `m_available` |
| 4 | 1 | `uint8` | `m_recommendedSession` |
| 5 | 1 | `uint8` | `m_lifeSpan` |
| 6 | 1 | `uint8` | `m_usableLife` |
| 7 | 2 | `int16` | `m_lapDeltaTime` |
| 9 | 1 | `uint8` | `m_fitted` |
| **10** | | | *total* |

Python: `<BBBBBBBhB` (calcsize = 10). `m_wear` in %. `m_recommendedSession` is a session type (§8.5). `m_lifeSpan` is laps left; `m_usableLife` is the recommended maximum laps. `m_lapDeltaTime` is int16 ms versus the fitted set.

### 5.13 Motion Ex (ID 13), 273 bytes, rate as set in menus (player car only)

The spec says: "extended data for the car being driven with the goal of being able to drive a motion platform setup."

```c
struct PacketMotionExData
{
    PacketHeader    m_header;               // Header

    // Extra player car ONLY data
    float           m_suspensionPosition[4];        // Note: All wheel arrays have the following order:
    float           m_suspensionVelocity[4];        // RL, RR, FL, FR
    float           m_suspensionAcceleration[4];    // RL, RR, FL, FR
    float           m_wheelSpeed[4];                // Speed of each wheel
    float           m_wheelSlipRatio[4];            // Slip ratio for each wheel
    float           m_wheelSlipAngle[4];            // Slip angles for each wheel
    float           m_wheelLatForce[4];             // Lateral forces for each wheel
    float           m_wheelLongForce[4];            // Longitudinal forces for each wheel
    float           m_heightOfCOGAboveGround;       // Height of centre of gravity above ground
    float           m_localVelocityX;               // Velocity in local space X - metres/s
    float           m_localVelocityY;               // Velocity in local space Y
    float           m_localVelocityZ;               // Velocity in local space Z
    float           m_angularVelocityX;             // Angular velocity x-component - radians/s
    float           m_angularVelocityY;             // Angular velocity y-component
    float           m_angularVelocityZ;             // Angular velocity z-component
    float           m_angularAccelerationX;         // Angular acceleration x-component - radians/s/s
    float           m_angularAccelerationY;         // Angular acceleration y-component
    float           m_angularAccelerationZ;         // Angular acceleration z-component
    float           m_frontWheelsAngle;             // Current front wheels angle in radians
    float           m_wheelVertForce[4];            // Vertical forces for each wheel
    float           m_frontAeroHeight;              // Front plank edge height above road surface
    float           m_rearAeroHeight;               // Rear plank edge height above road surface
    float           m_frontRollAngle;               // Roll angle of the front suspension
    float           m_rearRollAngle;                // Roll angle of the rear suspension
    float           m_chassisYaw;                   // Yaw angle of the chassis relative to the direction of motion - radians
    float           m_chassisPitch;                 // Pitch angle of the chassis relative to the direction of motion - radians
    float           m_wheelCamber[4];               // Camber of each wheel in radians
    float           m_wheelCamberGain[4];           // Camber gain for each wheel in radians, difference between active camber and dynamic camber
};
```

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 29 | `PacketHeader` | `m_header` |
| 29 | 16 | `float[4]` | `m_suspensionPosition` |
| 45 | 16 | `float[4]` | `m_suspensionVelocity` |
| 61 | 16 | `float[4]` | `m_suspensionAcceleration` |
| 77 | 16 | `float[4]` | `m_wheelSpeed` |
| 93 | 16 | `float[4]` | `m_wheelSlipRatio` |
| 109 | 16 | `float[4]` | `m_wheelSlipAngle` |
| 125 | 16 | `float[4]` | `m_wheelLatForce` |
| 141 | 16 | `float[4]` | `m_wheelLongForce` |
| 157 | 4 | `float` | `m_heightOfCOGAboveGround` |
| 161 | 4 | `float` | `m_localVelocityX` |
| 165 | 4 | `float` | `m_localVelocityY` |
| 169 | 4 | `float` | `m_localVelocityZ` |
| 173 | 4 | `float` | `m_angularVelocityX` |
| 177 | 4 | `float` | `m_angularVelocityY` |
| 181 | 4 | `float` | `m_angularVelocityZ` |
| 185 | 4 | `float` | `m_angularAccelerationX` |
| 189 | 4 | `float` | `m_angularAccelerationY` |
| 193 | 4 | `float` | `m_angularAccelerationZ` |
| 197 | 4 | `float` | `m_frontWheelsAngle` |
| 201 | 16 | `float[4]` | `m_wheelVertForce` |
| 217 | 4 | `float` | `m_frontAeroHeight` |
| 221 | 4 | `float` | `m_rearAeroHeight` |
| 225 | 4 | `float` | `m_frontRollAngle` |
| 229 | 4 | `float` | `m_rearRollAngle` |
| 233 | 4 | `float` | `m_chassisYaw` |
| 237 | 4 | `float` | `m_chassisPitch` |
| 241 | 16 | `float[4]` | `m_wheelCamber` |
| 257 | 16 | `float[4]` | `m_wheelCamberGain` |
| **273** | | | *total* |

Python (whole packet including header): `<HBBBBBQfIIBB4f4f4f4f4f4f4f4ffffffffffff4fffffff4f4f` (calcsize = 273)

Units where stated: local velocity in m/s, angular velocity in rad/s, angular acceleration in rad/s², front wheels angle in rad, chassis yaw and pitch in rad, camber and camber gain in rad.
**Not stated:** suspension position, velocity and acceleration; wheel speed; slip ratio and slip angle; lateral, longitudinal and vertical forces; COG height; aero heights; roll angles. Verify the units empirically before using them for coaching.

### 5.14 Time Trial (ID 14), 101 bytes, 1 per second, Time Trial mode only

```c
struct TimeTrialDataSet
{
    uint8       m_carIdx;                   // Index of the car this data relates to
    uint8       m_teamId;                   // Team id - see appendix
    uint        m_lapTimeInMS;              // Lap time in milliseconds
    uint        m_sector1TimeInMS;          // Sector 1 time in milliseconds
    uint        m_sector2TimeInMS;          // Sector 2 time in milliseconds
    uint        m_sector3TimeInMS;          // Sector 3 time in milliseconds
    uint8       m_tractionControl;          // 0 = assist off, 1 = assist on
    uint8       m_gearboxAssist;            // 0 = assist off, 1 = assist on
    uint8       m_antiLockBrakes;           // 0 = assist off, 1 = assist on
    uint8       m_equalCarPerformance;      // 0 = Realistic, 1 = Equal
    uint8       m_customSetup;              // 0 = No, 1 = Yes
    uint8       m_valid;                    // 0 = invalid, 1 = valid
};
```

```c
struct PacketTimeTrialData
{
    PacketHeader        m_header;                       // Header

    TimeTrialDataSet    m_playerSessionBestDataSet;     // Player session best data set
    TimeTrialDataSet    m_personalBestDataSet;          // Personal best data set
    TimeTrialDataSet    m_rivalDataSet;                 // Rival data set
};
```

Layout: player session best at 29, personal best at 53, rival at 77 (each 24 bytes).

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 1 | `uint8` | `m_carIdx` |
| 1 | 1 | `uint8` | `m_teamId` |
| 2 | 4 | `uint` | `m_lapTimeInMS` |
| 6 | 4 | `uint` | `m_sector1TimeInMS` |
| 10 | 4 | `uint` | `m_sector2TimeInMS` |
| 14 | 4 | `uint` | `m_sector3TimeInMS` |
| 18 | 1 | `uint8` | `m_tractionControl` |
| 19 | 1 | `uint8` | `m_gearboxAssist` |
| 20 | 1 | `uint8` | `m_antiLockBrakes` |
| 21 | 1 | `uint8` | `m_equalCarPerformance` |
| 22 | 1 | `uint8` | `m_customSetup` |
| 23 | 1 | `uint8` | `m_valid` |
| **24** | | | *total* |

Python: `<BBIIIIBBBBBB` (calcsize = 24). `uint` here is 4 bytes. Times are in ms. Assist flags: 0 off, 1 on. `m_equalCarPerformance` 0 realistic, 1 equal. `m_customSetup` and `m_valid` are 0/1.

### 5.15 Lap Positions (ID 15, new in F1 25), 1131 bytes, 1 per second

The spec says: "indicates which position each car was on at the start of each lap... only a maximum of 50 laps will be transmitted in a packet. If more than 50 laps have occurred then two packets will be transmitted, with different m_lapStart parameters."

```c
static const NEuint     cs_maxNumLapsInLapPositionsHistoryPacket = 50;
```

```c
struct PacketLapPositionsData
{
    PacketHeader    m_header;                   // Header

    // Packet specific data
    uint8           m_numLaps;                  // Number of laps in the data
    uint8           m_lapStart;                 // Index of the lap where the data starts, 0 indexed

    // Array holding the position of the car in a given lap, 0 if no record
    uint8           m_positionForVehicleIdx[cs_maxNumLapsInLapPositionsHistoryPacket][cs_maxNumCarsInUDPData];
};
```

Layout: `m_numLaps` 29, `m_lapStart` 30 (0-indexed), positions at 31. The array is row-major `[lap][vehicle]`: the byte for lap *l* (0-based within packet) and car *v* is at `31 + l*22 + v` (2026: `31 + l*24 + v`). A value of 0 means no record.

---

## 6. F1 24 (2024) to F1 25 (2025) differences

Official list from the F1 25 PDF FAQ ("What has changed since last year?"), confirmed by diffing EA's F1 24 and F1 25 `.txt` files:

| Change | Struct / packet | Wire effect |
|---|---|---|
| New Lap Positions packet | ID 15 | new 1131-byte packet |
| Participant name 48 → 32 chars; added `m_numColours` + `m_liveryColours[4]` (RGB) | ParticipantData | 60 → 57 B/car; packet 1350 → 1284 |
| Lobby name 48 → 32 chars | LobbyInfoData | 58 → 42 B; packet 1306 → 954 |
| Added `m_resultReason` | FinalClassificationData | 45 → 46 B; packet 1020 → 1042 |
| Added `m_tyreBlisters[4]` (after `m_brakesDamage`) | CarDamageData | 42 → 46 B; packet 953 → 1041 |
| Added `m_chassisPitch`, `m_wheelCamber[4]`, `m_wheelCamberGain[4]` (at the end) | MotionEx | 237 → 273 |
| Retirement event gained `reason` | Event RTMT | union payload only (packet stays 45) |
| DRS disabled event gained `reason` | Event DRSD | payload only |
| Stop-go served event gained `stopTime` (float) | Event SGSV | payload only |
| C6 compound documented (actual = 22) | CarStatus comment | none |
| `cs_maxParticipantNameLen` moved to top-level constants (32) | n/a | n/a |

Unchanged between 2024 and 2025: Header, Motion, Session, LapData, CarSetups, CarTelemetry, CarStatus, SessionHistory, TyreSets, TimeTrial.
F1 25 itself accepts UDP formats 2025, 2024 and 2023 ("F1 25 will only support the previous 2 UDP formats").

---

## 7. Format 2026: "F1 25: 2026 Season Pack" (DLC, June 2026)

### 7.1 What is confirmed

- **There is no standalone "F1 26" game.** The 2026 season is paid DLC on F1 25 ("2026 Season Pack", launched 2026-06-03, also sold bundled as the "2026 Season Edition"; EA news: <https://www.ea.com/games/f1/news/f1-25-2026-season-pack-launch>). EA's spec files and community guides nonetheless call the format and mode "F1 26".
- **A new wire format exists, `m_packetFormat = 2026`, with a published official spec** (the `.txt` plus PDFs v1.1 and v1.2 listed in §1).
- The game with the pack supports UDP formats **2026, 2025 and 2024** ("set 'UDP Format' to either '2025' or '2024'").
  New players default to 2026. Existing F1 25 players stay on 2025 until they change the setting.
- `m_gameYear` stays **25** in 2026 format. Seen in a live PS5 capture (header `packetFormat=2026, gameYear=25, major=1, minor=24`) and reported in the EA 2026 spec discussion thread (13424444, as surfaced by search; replies need sign-in). The 2026 PDF comment also says "e.g. 25" (the `.txt` says "e.g. 26").
- Per the F1Laps setup guide (third-party, <https://www.f1laps.com/faqs/f1-26-udp-telemetry-settings/>): when the game sends format 2025 for 2026 content, 2026 cars can appear as "F1 Generic" and Boost/ERS data is missing. Use format 2026 for 2026 cars.

### 7.2 Official change list (2026 PDF FAQ), with wire effect

| Change (official wording, paraphrased) | Wire effect |
|---|---|
| [IMPORTANT] Max vehicles 22 → **24** ("so most packet sizes have changed") | every car array |
| Engine temperature uint16 → **uint8** | CarTelemetryData 60 → 59 B |
| G-force values **quantised** (int16) "to reduce space in the motion packet" | CarMotionData 60 → 54 B. **Divide by 1000.0f** (spec) |
| New tracks, teams, drivers, cars | appendices (Madrid track 42; team IDs up to 499) |
| Driver, Network and Team IDs widened | ParticipantData `m_driverId`, `m_networkId`, `m_teamId` → **uint16** (57 → 60 B); LobbyInfoData `m_teamId` → uint16 (42 → 43 B); TimeTrialDataSet `m_teamId` → uint16 (24 → 25 B). Sentinel 255 → **65535** |
| New **Car Telemetry 2** packet (2026 regulations, wrong-way flag) | ID 16, 269 B |
| Activation zones and active-aero status added to Session | +173-byte tail |
| ERS harvest limit per lap added to Car Status | `m_ersHarvestLimitPerLap` float inserted before `m_ersDeployedThisLap` (55 → 59 B) |
| Driver reaction time for race starts | Session `m_startReactionTime` |
| Collision severity | Event COLL payload +1 byte |
| ABS, TC, hi-vis and colour-blind assists, rewind prompt | Session tail bytes |
| PDF v1.1: ERS deploy mode 3 renamed "overtake" → **"boost"** | none (comment only) |
| PDF v1.2 (Season 8, v1.25 patch): Race Control partial-mode / overtake-mode events | new event codes `PMEN`, `PMDI`, `OVEN`, `OVDI` + union member `PartialModeEnabled` |
| PDF v1.2: F2 2026 teams/drivers | Team IDs 489-499, Driver IDs 198-207 |
| Formula enum gains **13 = F1 26** | Session `m_formula` |

Byte-identical between 2025 and 2026: Header, LapData (57), CarSetupData (50), FinalClassificationData (46), CarDamageData (46), SessionHistory, TyreSets, MotionEx, MarshalZone, WeatherForecastSample, and the Session body up to `m_sector3LapDistanceStart`.

### 7.3 Changed and new structs (verbatim from the 2026 `.txt`)

**Constants and Session sub-structs:**

```c
static const uint32     cs_maxMarshalZonesPerLap = 21;
static const uint32     cs_maxActiveAeroZonesPerLap = 8;
static const uint32     cs_maxDRSZonesPerLap = 4;
static const uint32     cs_maxWeatherForecastSamples = 64;
static const uint32     cs_maxSessionsInWeekend = 12;
```

```c
struct ActiveAeroZone
{
    float       m_zoneStart;        // Fraction (0..1) of way through the lap the Active Aero zone starts
    float       m_zoneEnd;          // Fraction (0..1) of way through the lap the Active Aero zone ends
};
```

```c
struct DRSZone
{
    float       m_zoneStart;        // Fraction (0..1) of way through the lap the DRS zone starts
    float       m_zoneEnd;          // Fraction (0..1) of way through the lap the DRS zone ends
};
```

**CarMotionData (54 B):**

```c
struct CarMotionData
{
    float       m_worldPositionX;           // World space X position - metres
    float       m_worldPositionY;           // World space Y position
    float       m_worldPositionZ;           // World space Z position
    float       m_worldVelocityX;           // Velocity in world space X - metres/s
    float       m_worldVelocityY;           // Velocity in world space Y
    float       m_worldVelocityZ;           // Velocity in world space Z
    int16       m_worldForwardDirX;         // World space forward X direction (normalised)
    int16       m_worldForwardDirY;         // World space forward Y direction (normalised)
    int16       m_worldForwardDirZ;         // World space forward Z direction (normalised)
    int16       m_worldRightDirX;           // World space right X direction (normalised)
    int16       m_worldRightDirY;           // World space right Y direction (normalised)
    int16       m_worldRightDirZ;           // World space right Z direction (normalised)
    int16       m_gForceLateral;            // Lateral G-Force component (quantised)
    int16       m_gForceLongitudinal;       // Longitudinal G-Force component (quantised)
    int16       m_gForceVertical;           // Vertical G-Force component (quantised)
    float       m_yaw;                      // Yaw angle in radians
    float       m_pitch;                    // Pitch angle in radians
    float       m_roll;                     // Roll angle in radians
};
```

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 4 | `float` | `m_worldPositionX` |
| 4 | 4 | `float` | `m_worldPositionY` |
| 8 | 4 | `float` | `m_worldPositionZ` |
| 12 | 4 | `float` | `m_worldVelocityX` |
| 16 | 4 | `float` | `m_worldVelocityY` |
| 20 | 4 | `float` | `m_worldVelocityZ` |
| 24 | 2 | `int16` | `m_worldForwardDirX` |
| 26 | 2 | `int16` | `m_worldForwardDirY` |
| 28 | 2 | `int16` | `m_worldForwardDirZ` |
| 30 | 2 | `int16` | `m_worldRightDirX` |
| 32 | 2 | `int16` | `m_worldRightDirY` |
| 34 | 2 | `int16` | `m_worldRightDirZ` |
| 36 | 2 | `int16` | `m_gForceLateral` |
| 38 | 2 | `int16` | `m_gForceLongitudinal` |
| 40 | 2 | `int16` | `m_gForceVertical` |
| 42 | 4 | `float` | `m_yaw` |
| 46 | 4 | `float` | `m_pitch` |
| 50 | 4 | `float` | `m_roll` |
| **54** | | | *total* |

Python: `<ffffffhhhhhhhhhfff` (calcsize = 54). The PDF says: "for the g-Force components, these are int16 and need to be converted by dividing by 1000.0f."

**PacketSessionData (926 B).** Identical to 2025 through `m_sector3LapDistanceStart` (offset 749-752). Full verbatim struct:

```c
struct PacketSessionData
{
    PacketHeader    m_header;               // Header

    // Packet specific data
    uint8       m_weather;                          // Weather - 0 = clear, 1 = light cloud, 2 = overcast, 3 = light rain, 4 = heavy rain, 5 = storm
    int8        m_trackTemperature;                 // Track temp. in degrees celsius
    int8        m_airTemperature;                   // Air temp. in degrees celsius
    uint8       m_totalLaps;                        // Total number of laps in this race
    uint16      m_trackLength;                      // Track length in metres
    uint8       m_sessionType;                      // 0 = unknown, see appendix
    int8        m_trackId;                          // -1 for unknown, see appendix
    uint8       m_formula;                          // Formula, 0 = F1 Modern, 1 = F1 Classic, 2 = F2, 3 = F1 Generic, 4 = Beta, 6 = Esports, 8 = F1 World, 9 = F1 Elimination, 13 = F1 26
    uint16      m_sessionTimeLeft;		            // Time left in session in seconds
    uint16      m_sessionDuration;		            // Session duration in seconds
    uint8       m_pitSpeedLimit;                    // Pit speed limit in kilometres per hour
    uint8       m_gamePaused;                       // Whether the game is paused - network game only
    uint8       m_isSpectating;                     // Whether the player is spectating
    uint8       m_spectatorCarIndex;                // Index of the car being spectated
    uint8       m_sliProNativeSupport;              // SLI Pro support, 0 = inactive, 1 = active
    uint8       m_numMarshalZones;                  // Number of marshal zones to follow
    MarshalZone m_marshalZones[cs_maxMarshalZonesPerLap];  // List of marshal zones - max 21
    uint8       m_safetyCarStatus;                  // 0 = no safety car, 1 = full, 2 = virtual, 3 = formation lap
    uint8       m_networkGame;                      // 0 = offline, 1 = online
    uint8       m_numWeatherForecastSamples;        // Number of weather samples to follow
    WeatherForecastSample m_weatherForecastSamples[cs_maxWeatherForecastSamples];   // Array of weather forecast samples
    uint8       m_forecastAccuracy;                 // 0 = Perfect, 1 = Approximate
    uint8       m_aiDifficulty;                     // AI difficulty - 0-110
    uint32      m_seasonLinkIdentifier;             // Identifier for season - persists across saves
    uint32      m_weekendLinkIdentifier;            // Identifier for weekend - persists across saves
    uint32      m_sessionLinkIdentifier;            // Identifier for session - persists across saves
    uint8       m_pitStopWindowIdealLap;            // Ideal lap to pit on for current strategy (player)
    uint8       m_pitStopWindowLatestLap;           // Latest lap to pit on for current strategy (player)
    uint8       m_pitStopRejoinPosition;            // Predicted position to rejoin at (player)
    uint8       m_steeringAssist;                   // 0 = off, 1 = on
    uint8       m_brakingAssist;                    // 0 = off, 1 = low, 2 = medium, 3 = high
    uint8       m_gearboxAssist;                    // 1 = manual, 2 = manual & suggested gear, 3 = auto
    uint8       m_pitAssist;                        // 0 = off, 1 = on
    uint8       m_pitReleaseAssist;                 // 0 = off, 1 = on
    uint8       m_ERSAssist;                        // 0 = off, 1 = on
    uint8       m_DRSAssist;                        // 0 = off, 1 = on
    uint8       m_dynamicRacingLine;                // 0 = off, 1 = corners only, 2 = full
    uint8       m_dynamicRacingLineType;            // 0 = 2D, 1 = 3D
    uint8       m_gameMode;                         // Game mode id - see appendix
    uint8       m_ruleSet;                          // Ruleset - see appendix
    uint32      m_timeOfDay;                        // Local time of day - minutes since midnight
    uint8       m_sessionLength;                    // 0 = None, 2 = Very Short, 3 = Short, 4 = Medium, 5 = Medium Long, 6 = Long, 7 = Full
    uint8       m_speedUnitsLeadPlayer;             // 0 = MPH, 1 = KPH
    uint8       m_temperatureUnitsLeadPlayer;       // 0 = Celsius, 1 = Fahrenheit
    uint8       m_speedUnitsSecondaryPlayer;        // 0 = MPH, 1 = KPH
    uint8       m_temperatureUnitsSecondaryPlayer;  // 0 = Celsius, 1 = Fahrenheit
    uint8       m_numSafetyCarPeriods;              // Number of safety cars called during session
    uint8       m_numVirtualSafetyCarPeriods;       // Number of virtual safety cars called during session
    uint8       m_numRedFlagPeriods;                // Number of red flags called during session
    uint8       m_equalCarPerformance;              // 0 = Off, 1 = On
    uint8       m_recoveryMode;                     // 0 = None, 1 = Flashbacks, 2 = Auto-recovery
    uint8       m_flashbackLimit;                   // 0 = Low, 1 = Medium, 2 = High, 3 = Unlimited
    uint8       m_surfaceType;                      // 0 = Simplified, 1 = Realistic
    uint8       m_lowFuelMode;                      // 0 = Easy, 1 = Hard
    uint8       m_raceStarts;                       // 0 = Manual, 1 = Assisted
    uint8       m_tyreTemperature;                  // 0 = Surface only, 1 = Surface & Carcass
    uint8       m_pitLaneTyreSim;                   // 0 = On, 1 = Off
    uint8       m_carDamage;                        // 0 = Off, 1 = Reduced, 2 = Standard, 3 = Simulation
    uint8       m_carDamageRate;                    // 0 = Reduced, 1 = Standard, 2 = Simulation
    uint8       m_collisions;                       // 0 = Off, 1 = Player-to-Player Off, 2 = On
    uint8       m_collisionsOffForFirstLapOnly;     // 0 = Disabled, 1 = Enabled
    uint8       m_mpUnsafePitRelease;               // 0 = On, 1 = Off (Multiplayer)
    uint8       m_mpOffForGriefing;                 // 0 = Disabled, 1 = Enabled (Multiplayer)
    uint8       m_cornerCuttingStringency;          // 0 = Regular, 1 = Strict
    uint8       m_parcFermeRules;                   // 0 = Off, 1 = On
    uint8       m_pitStopExperience;                // 0 = Automatic, 1 = Broadcast, 2 = Immersive
    uint8       m_safetyCar;                        // 0 = Off, 1 = Reduced, 2 = Standard, 3 = Increased
    uint8       m_safetyCarExperience;              // 0 = Broadcast, 1 = Immersive
    uint8       m_formationLap;                     // 0 = Off, 1 = On
    uint8       m_formationLapExperience;           // 0 = Broadcast, 1 = Immersive
    uint8       m_redFlags;                         // 0 = Off, 1 = Reduced, 2 = Standard, 3 = Increased
    uint8       m_affectsLicenceLevelSolo;          // 0 = Off, 1 = On
    uint8       m_affectsLicenceLevelMP;            // 0 = Off, 1 = On
    uint8       m_numSessionsInWeekend;             // Number of session in following array
    uint8       m_weekendStructure[cs_maxSessionsInWeekend];    // List of session types to show weekend structure - see appendix for types
    float       m_sector2LapDistanceStart;          // Distance in m around track where sector 2 starts
    float       m_sector3LapDistanceStart;          // Distance in m around track where sector 3 starts

    // Aero and DRS zones
    uint8       m_activeAeroTrackStatus;            // 0 = Full, 1 = Partial
    uint8       m_numActiveAeroZonesFull;           // Number of Active Aero zones to follow
    ActiveAeroZone  m_activeAeroZonesFull[cs_maxActiveAeroZonesPerLap];  // List of Active Aero zones - max 8
    uint8       m_numActiveAeroZonesPartial;        // Number of Active Aero zones to follow
    ActiveAeroZone  m_activeAeroZonesPartial[cs_maxActiveAeroZonesPerLap];  // List of Active Aero zones - max 8
    uint8       m_numDRSZones;                      // Number of DRS zones to follow
    DRSZone     m_drsZones[cs_maxDRSZonesPerLap];   // List of DRS zones - max 4
    float       m_startReactionTime;                // Driver start reaction time in seconds, 0.0f if assisted starts
    uint8       m_antiLockBrakesAssist;             // 0 = Off, 1 = On
    uint8       m_tractionControlAssist;            // 0 = Off, 1 = Medium, 2 = Full
    uint8       m_dynamicRacingLineHiVis;           // 0 = Off, 1 = On
    uint8       m_dynamicRacingLineColourBlind;     // 0 = Off, 1 = Protanopia, 2 = Deuteranopia, 3 = Tritanopia
    uint8       m_recurringRewindPrompt;            // 0 = Off, 1 = On
};
```

Full offsets (format 2026):

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 29 | `PacketHeader` | `m_header` |
| 29 | 1 | `uint8` | `m_weather` |
| 30 | 1 | `int8` | `m_trackTemperature` |
| 31 | 1 | `int8` | `m_airTemperature` |
| 32 | 1 | `uint8` | `m_totalLaps` |
| 33 | 2 | `uint16` | `m_trackLength` |
| 35 | 1 | `uint8` | `m_sessionType` |
| 36 | 1 | `int8` | `m_trackId` |
| 37 | 1 | `uint8` | `m_formula` |
| 38 | 2 | `uint16` | `m_sessionTimeLeft` |
| 40 | 2 | `uint16` | `m_sessionDuration` |
| 42 | 1 | `uint8` | `m_pitSpeedLimit` |
| 43 | 1 | `uint8` | `m_gamePaused` |
| 44 | 1 | `uint8` | `m_isSpectating` |
| 45 | 1 | `uint8` | `m_spectatorCarIndex` |
| 46 | 1 | `uint8` | `m_sliProNativeSupport` |
| 47 | 1 | `uint8` | `m_numMarshalZones` |
| 48 | 105 | `MarshalZone[21]` | `m_marshalZones` |
| 153 | 1 | `uint8` | `m_safetyCarStatus` |
| 154 | 1 | `uint8` | `m_networkGame` |
| 155 | 1 | `uint8` | `m_numWeatherForecastSamples` |
| 156 | 512 | `WeatherForecastSample[64]` | `m_weatherForecastSamples` |
| 668 | 1 | `uint8` | `m_forecastAccuracy` |
| 669 | 1 | `uint8` | `m_aiDifficulty` |
| 670 | 4 | `uint32` | `m_seasonLinkIdentifier` |
| 674 | 4 | `uint32` | `m_weekendLinkIdentifier` |
| 678 | 4 | `uint32` | `m_sessionLinkIdentifier` |
| 682 | 1 | `uint8` | `m_pitStopWindowIdealLap` |
| 683 | 1 | `uint8` | `m_pitStopWindowLatestLap` |
| 684 | 1 | `uint8` | `m_pitStopRejoinPosition` |
| 685 | 1 | `uint8` | `m_steeringAssist` |
| 686 | 1 | `uint8` | `m_brakingAssist` |
| 687 | 1 | `uint8` | `m_gearboxAssist` |
| 688 | 1 | `uint8` | `m_pitAssist` |
| 689 | 1 | `uint8` | `m_pitReleaseAssist` |
| 690 | 1 | `uint8` | `m_ERSAssist` |
| 691 | 1 | `uint8` | `m_DRSAssist` |
| 692 | 1 | `uint8` | `m_dynamicRacingLine` |
| 693 | 1 | `uint8` | `m_dynamicRacingLineType` |
| 694 | 1 | `uint8` | `m_gameMode` |
| 695 | 1 | `uint8` | `m_ruleSet` |
| 696 | 4 | `uint32` | `m_timeOfDay` |
| 700 | 1 | `uint8` | `m_sessionLength` |
| 701 | 1 | `uint8` | `m_speedUnitsLeadPlayer` |
| 702 | 1 | `uint8` | `m_temperatureUnitsLeadPlayer` |
| 703 | 1 | `uint8` | `m_speedUnitsSecondaryPlayer` |
| 704 | 1 | `uint8` | `m_temperatureUnitsSecondaryPlayer` |
| 705 | 1 | `uint8` | `m_numSafetyCarPeriods` |
| 706 | 1 | `uint8` | `m_numVirtualSafetyCarPeriods` |
| 707 | 1 | `uint8` | `m_numRedFlagPeriods` |
| 708 | 1 | `uint8` | `m_equalCarPerformance` |
| 709 | 1 | `uint8` | `m_recoveryMode` |
| 710 | 1 | `uint8` | `m_flashbackLimit` |
| 711 | 1 | `uint8` | `m_surfaceType` |
| 712 | 1 | `uint8` | `m_lowFuelMode` |
| 713 | 1 | `uint8` | `m_raceStarts` |
| 714 | 1 | `uint8` | `m_tyreTemperature` |
| 715 | 1 | `uint8` | `m_pitLaneTyreSim` |
| 716 | 1 | `uint8` | `m_carDamage` |
| 717 | 1 | `uint8` | `m_carDamageRate` |
| 718 | 1 | `uint8` | `m_collisions` |
| 719 | 1 | `uint8` | `m_collisionsOffForFirstLapOnly` |
| 720 | 1 | `uint8` | `m_mpUnsafePitRelease` |
| 721 | 1 | `uint8` | `m_mpOffForGriefing` |
| 722 | 1 | `uint8` | `m_cornerCuttingStringency` |
| 723 | 1 | `uint8` | `m_parcFermeRules` |
| 724 | 1 | `uint8` | `m_pitStopExperience` |
| 725 | 1 | `uint8` | `m_safetyCar` |
| 726 | 1 | `uint8` | `m_safetyCarExperience` |
| 727 | 1 | `uint8` | `m_formationLap` |
| 728 | 1 | `uint8` | `m_formationLapExperience` |
| 729 | 1 | `uint8` | `m_redFlags` |
| 730 | 1 | `uint8` | `m_affectsLicenceLevelSolo` |
| 731 | 1 | `uint8` | `m_affectsLicenceLevelMP` |
| 732 | 1 | `uint8` | `m_numSessionsInWeekend` |
| 733 | 12 | `uint8[12]` | `m_weekendStructure` |
| 745 | 4 | `float` | `m_sector2LapDistanceStart` |
| 749 | 4 | `float` | `m_sector3LapDistanceStart` |
| 753 | 1 | `uint8` | `m_activeAeroTrackStatus` |
| 754 | 1 | `uint8` | `m_numActiveAeroZonesFull` |
| 755 | 64 | `ActiveAeroZone[8]` | `m_activeAeroZonesFull` |
| 819 | 1 | `uint8` | `m_numActiveAeroZonesPartial` |
| 820 | 64 | `ActiveAeroZone[8]` | `m_activeAeroZonesPartial` |
| 884 | 1 | `uint8` | `m_numDRSZones` |
| 885 | 32 | `DRSZone[4]` | `m_drsZones` |
| 917 | 4 | `float` | `m_startReactionTime` |
| 921 | 1 | `uint8` | `m_antiLockBrakesAssist` |
| 922 | 1 | `uint8` | `m_tractionControlAssist` |
| 923 | 1 | `uint8` | `m_dynamicRacingLineHiVis` |
| 924 | 1 | `uint8` | `m_dynamicRacingLineColourBlind` |
| 925 | 1 | `uint8` | `m_recurringRewindPrompt` |
| **926** | | | *total* |

Python: ActiveAeroZone / DRSZone `<ff` (calcsize = 8). Session-tail enums: `m_activeAeroTrackStatus` 0 full, 1 partial. `m_startReactionTime` is in s, 0.0 if assisted starts. `m_antiLockBrakesAssist` 0/1. `m_tractionControlAssist` 0 off, 1 medium, 2 full. `m_dynamicRacingLineHiVis` 0/1. `m_dynamicRacingLineColourBlind` 0 off, 1 protanopia, 2 deuteranopia, 3 tritanopia. `m_recurringRewindPrompt` 0/1.

**ParticipantData (60 B):**

```c
struct ParticipantData
{
    uint8           m_aiControlled;                     // Whether the vehicle is AI (1) or Human (0) controlled
    uint16          m_driverId;                         // Driver id - see appendix, 65535 if network human
    uint16          m_networkId;                        // Network id - unique identifier for network players
    uint16          m_teamId;                           // Team id - see appendix
    uint8           m_myTeam;                           // My team flag - 1 = My Team, 0 = otherwise
    uint8           m_raceNumber;                       // Race number of the car
    uint8           m_nationality;                      // Nationality of the driver
    char            m_name[cs_maxParticipantNameLen];   // Name of participant in UTF-8 format – null terminated
                                                        // Will be truncated with ... (U+2026) if too long
    uint8           m_yourTelemetry;                    // The player's UDP setting, 0 = restricted, 1 = public
    uint8           m_showOnlineNames;                  // The player's show online names setting, 0 = off, 1 = on
    uint16          m_techLevel;                        // F1 World tech level
    uint8           m_platform;                         // 1 = Steam, 3 = PlayStation, 4 = Xbox, 6 = Origin, 255 = unknown
    uint8           m_numColours;                       // Number of colours valid for this car
    LiveryColour    m_liveryColours[4];                 // Colours for the car
};
```

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 1 | `uint8` | `m_aiControlled` |
| 1 | 2 | `uint16` | `m_driverId` |
| 3 | 2 | `uint16` | `m_networkId` |
| 5 | 2 | `uint16` | `m_teamId` |
| 7 | 1 | `uint8` | `m_myTeam` |
| 8 | 1 | `uint8` | `m_raceNumber` |
| 9 | 1 | `uint8` | `m_nationality` |
| 10 | 32 | `char[32]` | `m_name` |
| 42 | 1 | `uint8` | `m_yourTelemetry` |
| 43 | 1 | `uint8` | `m_showOnlineNames` |
| 44 | 2 | `uint16` | `m_techLevel` |
| 46 | 1 | `uint8` | `m_platform` |
| 47 | 1 | `uint8` | `m_numColours` |
| 48 | 12 | `LiveryColour[4]` | `m_liveryColours` |
| **60** | | | *total* |

Python: `<BHHHBBB32sBBHBBBBBBBBBBBBBB` (calcsize = 60)

**CarTelemetryData (59 B):**

```c
struct CarTelemetryData
{
    uint16      m_speed;                        // Speed of car in kilometres per hour
    float       m_throttle;                     // Amount of throttle applied (0.0 to 1.0)
    float       m_steer;                        // Steering (-1.0 (full lock left) to 1.0 (full lock right))
    float       m_brake;                        // Amount of brake applied (0.0 to 1.0)
    uint8       m_clutch;                       // Amount of clutch applied (0 to 100)
    int8        m_gear;                         // Gear selected (1-8, N=0, R=-1)
    uint16      m_engineRPM;                    // Engine RPM
    uint8       m_drs;                          // 0 = off, 1 = on
    uint8       m_revLightsPercent;             // Rev lights indicator (percentage)
    uint16      m_revLightsBitValue;            // Rev lights (bit 0 = leftmost LED, bit 14 = rightmost LED)
    uint16      m_brakesTemperature[4];         // Brakes temperature (celsius)
    uint8       m_tyresSurfaceTemperature[4];   // Tyres surface temperature (celsius)
    uint8       m_tyresInnerTemperature[4];     // Tyres inner temperature (celsius)
    uint8       m_engineTemperature;            // Engine temperature (celsius)
    float       m_tyresPressure[4];             // Tyre pressure (PSI)
    uint8       m_surfaceType[4];               // Driving surface, see appendices
};
```

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 2 | `uint16` | `m_speed` |
| 2 | 4 | `float` | `m_throttle` |
| 6 | 4 | `float` | `m_steer` |
| 10 | 4 | `float` | `m_brake` |
| 14 | 1 | `uint8` | `m_clutch` |
| 15 | 1 | `int8` | `m_gear` |
| 16 | 2 | `uint16` | `m_engineRPM` |
| 18 | 1 | `uint8` | `m_drs` |
| 19 | 1 | `uint8` | `m_revLightsPercent` |
| 20 | 2 | `uint16` | `m_revLightsBitValue` |
| 22 | 8 | `uint16[4]` | `m_brakesTemperature` |
| 30 | 4 | `uint8[4]` | `m_tyresSurfaceTemperature` |
| 34 | 4 | `uint8[4]` | `m_tyresInnerTemperature` |
| 38 | 1 | `uint8` | `m_engineTemperature` |
| 39 | 16 | `float[4]` | `m_tyresPressure` |
| 55 | 4 | `uint8[4]` | `m_surfaceType` |
| **59** | | | *total* |

Python: `<HfffBbHBBH4H4B4BB4f4B` (calcsize = 59). Trailer bytes are at 1445, 1446 and 1447.

**CarStatusData (59 B):**

```c
struct CarStatusData
{
    uint8       m_tractionControl;                  // Traction control - 0 = off, 1 = medium, 2 = full
    uint8       m_antiLockBrakes;                   // 0 (off) - 1 (on)
    uint8       m_fuelMix;                          // Fuel mix - 0 = lean, 1 = standard, 2 = rich, 3 = max
    uint8       m_frontBrakeBias;                   // Front brake bias (percentage)
    uint8       m_pitLimiterStatus;                 // Pit limiter status - 0 = off, 1 = on
    float       m_fuelInTank;                       // Current fuel mass
    float       m_fuelCapacity;                     // Fuel capacity
    float       m_fuelRemainingLaps;                // Fuel remaining in terms of laps (value on MFD)
    uint16      m_maxRPM;                           // Cars max RPM, point of rev limiter
    uint16      m_idleRPM;                          // Cars idle RPM
    uint8       m_maxGears;                         // Maximum number of gears
    uint8       m_drsAllowed;                       // 0 = not allowed, 1 = allowed
    uint16      m_drsActivationDistance;            // 0 = DRS not available, non-zero - DRS will be available in [X] metres
    uint8       m_actualTyreCompound;               // F1 Modern - 16 = C5, 17 = C4, 18 = C3, 19 = C2, 20 = C1, 21 = C0, 22 = C6, 7 = inter, 8 = wet
                                                    // F1 Classic - 9 = dry, 10 = wet
                                                    // F2 – 11 = super soft, 12 = soft, 13 = medium, 14 = hard, 15 = wet
    uint8       m_visualTyreCompound;               // F1 visual (can be different from actual compound)
                                                    // 16 = soft, 17 = medium, 18 = hard, 7 = inter, 8 = wet
                                                    // F1 Classic – same as above
                                                    // F2 ‘20, 15 = wet, 19 – super soft, 20 = soft, 21 = medium, 22 = hard
    uint8       m_tyresAgeLaps;                     // Age in laps of the current set of tyres
    int8        m_vehicleFIAFlags;                  // -1 = invalid/unknown, 0 = none, 1 = green, 2 = blue, 3 = yellow
    float       m_enginePowerICE;                   // Engine power output of ICE (W)
    float       m_enginePowerMGUK;                  // Engine power output of MGU-K (W)
    float       m_ersStoreEnergy;                   // ERS energy store in Joules
    uint8       m_ersDeployMode;                    // ERS deployment mode, 0 = none, 1 = medium, 2 = hotlap, 3 = boost
    float       m_ersHarvestedThisLapMGUK;          // ERS energy harvested this lap by MGU-K
    float       m_ersHarvestedThisLapMGUH;          // ERS energy harvested this lap by MGU-H
    float       m_ersHarvestLimitPerLap;            // ERS energy harvest limit for this lap
    float       m_ersDeployedThisLap;               // ERS energy deployed this lap
    uint8       m_networkPaused;                    // Whether the car is paused in a network game
};
```

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 1 | `uint8` | `m_tractionControl` |
| 1 | 1 | `uint8` | `m_antiLockBrakes` |
| 2 | 1 | `uint8` | `m_fuelMix` |
| 3 | 1 | `uint8` | `m_frontBrakeBias` |
| 4 | 1 | `uint8` | `m_pitLimiterStatus` |
| 5 | 4 | `float` | `m_fuelInTank` |
| 9 | 4 | `float` | `m_fuelCapacity` |
| 13 | 4 | `float` | `m_fuelRemainingLaps` |
| 17 | 2 | `uint16` | `m_maxRPM` |
| 19 | 2 | `uint16` | `m_idleRPM` |
| 21 | 1 | `uint8` | `m_maxGears` |
| 22 | 1 | `uint8` | `m_drsAllowed` |
| 23 | 2 | `uint16` | `m_drsActivationDistance` |
| 25 | 1 | `uint8` | `m_actualTyreCompound` |
| 26 | 1 | `uint8` | `m_visualTyreCompound` |
| 27 | 1 | `uint8` | `m_tyresAgeLaps` |
| 28 | 1 | `int8` | `m_vehicleFIAFlags` |
| 29 | 4 | `float` | `m_enginePowerICE` |
| 33 | 4 | `float` | `m_enginePowerMGUK` |
| 37 | 4 | `float` | `m_ersStoreEnergy` |
| 41 | 1 | `uint8` | `m_ersDeployMode` |
| 42 | 4 | `float` | `m_ersHarvestedThisLapMGUK` |
| 46 | 4 | `float` | `m_ersHarvestedThisLapMGUH` |
| 50 | 4 | `float` | `m_ersHarvestLimitPerLap` |
| 54 | 4 | `float` | `m_ersDeployedThisLap` |
| 58 | 1 | `uint8` | `m_networkPaused` |
| **59** | | | *total* |

Python: `<BBBBBfffHHBBHBBBbfffBffffB` (calcsize = 59)

**LobbyInfoData (43 B) and TimeTrialDataSet (25 B):**

```c
struct LobbyInfoData
{
    uint8       m_aiControlled;                     // Whether the vehicle is AI (1) or Human (0) controlled
    uint16      m_teamId;                           // Team id - see appendix (65535 if no team currently selected)
    uint8       m_nationality;                      // Nationality of the driver
    uint8       m_platform;                         // 1 = Steam, 3 = PlayStation, 4 = Xbox, 6 = Origin, 255 = unknown
    char        m_name[cs_maxParticipantNameLen];   // Name of participant in UTF-8 format – null terminated
                                                    // Will be truncated with ... (U+2026) if too long
    uint8       m_carNumber;                        // Car number of the player
    uint8       m_yourTelemetry;                    // The player's UDP setting, 0 = restricted, 1 = public
    uint8       m_showOnlineNames;                  // The player's show online names setting, 0 = off, 1 = on
    uint16      m_techLevel;                        // F1 World tech level
    uint8       m_readyStatus;                      // 0 = not ready, 1 = ready, 2 = spectating
};
```

```c
struct TimeTrialDataSet
{
    uint8       m_carIdx;                   // Index of the car this data relates to
    uint16      m_teamId;                   // Team id - see appendix
    uint        m_lapTimeInMS;              // Lap time in milliseconds
    uint        m_sector1TimeInMS;          // Sector 1 time in milliseconds
    uint        m_sector2TimeInMS;          // Sector 2 time in milliseconds
    uint        m_sector3TimeInMS;          // Sector 3 time in milliseconds
    uint8       m_tractionControl;          // 0 = assist off, 1 = assist on
    uint8       m_gearboxAssist;            // 0 = assist off, 1 = assist on
    uint8       m_antiLockBrakes;           // 0 = assist off, 1 = assist on
    uint8       m_equalCarPerformance;      // 0 = Realistic, 1 = Equal
    uint8       m_customSetup;              // 0 = No, 1 = Yes
    uint8       m_valid;                    // 0 = invalid, 1 = valid
};
```

Python: LobbyInfoData `<BHBB32sBBBHB` (calcsize = 43), TimeTrialDataSet `<BHIIIIBBBBBB` (calcsize = 25).

**Car Telemetry 2 (ID 16, new): 269 B, rate as set in menus.** The PDF says this packet "details additional telemetry for all the cars in the race, as the initial car telemetry was getting too large."

```c
struct CarTelemetry2Data
{
    uint8     m_activeAeroMode;                   // 0 = Corner mode, 1 = Straight mode
    uint8     m_activeAeroAvailable;              // 0 = not available, 1 = available
    uint16    m_activeAeroActivationDistance;     // 0 = Active aero not available, non-zero - Active aero will be available in [X] metres
    uint8     m_overtakeAvailable;                // 0 = not available, 1 = available
    uint8     m_overtakeActive;                   // 0 = not active, 1 = active
    uint16    m_overtakeActivationDistance;       // 0 = Overtake Mode not available, non-zero - Overtake Mode will be available in [X] metres
    uint8     m_2026Regulations;                  // 0 = vehicle conforms to pre-2026, 1 = 2026 regulations applicable
    uint8     m_drivingWrongWay;                  // Whether the car is driving the wrong way
};
```

```c
struct PacketCarTelemetry2Data
{
    PacketHeader        m_header;               // Header

    // Packet specific data
    CarTelemetry2Data   m_carTelemetry2Data[cs_maxNumCarsInUDPData];   // data for all cars on track
};
```

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 1 | `uint8` | `m_activeAeroMode` |
| 1 | 1 | `uint8` | `m_activeAeroAvailable` |
| 2 | 2 | `uint16` | `m_activeAeroActivationDistance` |
| 4 | 1 | `uint8` | `m_overtakeAvailable` |
| 5 | 1 | `uint8` | `m_overtakeActive` |
| 6 | 2 | `uint16` | `m_overtakeActivationDistance` |
| 8 | 1 | `uint8` | `m_2026Regulations` |
| 9 | 1 | `uint8` | `m_drivingWrongWay` |
| **10** | | | *total* |

Python per-car: `<BBHBBHBB` (calcsize = 10). Car *i* is at `29 + 10*i`.

### 7.4 Event packet in format 2026 (still 45 bytes)

The verbatim 2026 `.txt` union (June 2026) adds only `severity` to `Collision`:

```c
union EventDataDetails
{
    struct
    {
        uint8 vehicleIdx; // Vehicle index of car achieving fastest lap
        float lapTime;    // Lap time is in seconds
    } FastestLap;

    struct
    {
        uint8 vehicleIdx; // Vehicle index of car retiring
        uint8 reason;     // Result reason - 0 = invalid, 1 = retired, 2 = finished, 3 = terminal damage, 4 = inactive, 5 = not enough laps completed, 6 = black flagged
                          // 7 = red flagged, 8 = mechanical failure, 9 = session skipped, 10 = session simulated
    } Retirement;

    struct
    {
        NEuint8 reason;     // 0 = Wet track, 1 = Safety car deployed, 2 = Red flag, 3 = Min lap not reached
    } DRSDisabled;

    struct
    {
        uint8 vehicleIdx; // Vehicle index of team mate
    } TeamMateInPits;

    struct
    {
        uint8 vehicleIdx; // Vehicle index of the race winner
    } RaceWinner;

    struct
    {
        uint8 penaltyType;        // Penalty type – see Appendices
        uint8 infringementType;   // Infringement type – see Appendices
        uint8 vehicleIdx;         // Vehicle index of the car the penalty is applied to
        uint8 otherVehicleIdx;    // Vehicle index of the other car involved
        uint8 time;               // Time gained, or time spent doing action in seconds
        uint8 lapNum;             // Lap the penalty occurred on
        uint8 placesGained;       // Number of places gained by this
    } Penalty;

    struct
    {
        uint8 vehicleIdx;                 // Vehicle index of the vehicle triggering speed trap
        float speed;                      // Top speed achieved in kilometres per hour
        uint8 isOverallFastestInSession;  // Overall fastest speed in session = 1, otherwise 0
        uint8 isDriverFastestInSession;   // Fastest speed for driver in session = 1, otherwise 0
        uint8 fastestVehicleIdxInSession; // Vehicle index of the vehicle that is the fastest in this session
        float fastestSpeedInSession;      // Speed of the vehicle that is the fastest in this session
    } SpeedTrap;

    struct
    {
        uint8 numLights;                  // Number of lights showing
    } StartLights;

    struct
    {
        uint8 vehicleIdx;                 // Vehicle index of the vehicle serving drive through
    } DriveThroughPenaltyServed;

    struct
    {
        uint8 vehicleIdx;                 // Vehicle index of the vehicle serving stop go
        float stopTime;                   // Time spent serving stop go in seconds
    } StopGoPenaltyServed;

    struct
    {
        uint32 flashbackFrameIdentifier;  // Frame identifier flashed back to
        float flashbackSessionTime;       // Session time flashed back to
    } Flashback;

    struct
    {
        uint32 buttonStatus;              // Bit flags specifying which buttons are being pressed currently - see appendices
    } Buttons;

    struct
    {
        uint8 overtakingVehicleIdx;       // Vehicle index of the vehicle overtaking
        uint8 beingOvertakenVehicleIdx;   // Vehicle index of the vehicle being overtaken
    } Overtake;

    struct
    {
        uint8 safetyCarType;              // 0 = No Safety Car, 1 = Full Safety Car, 2 = Virtual Safety Car, 3 = Formation Lap Safety Car
        uint8 eventType;                  // 0 = Deployed, 1 = Returning, 2 = Returned, 3 = Resume Race
    } SafetyCar;

    struct
    {
        uint8 vehicle1Idx;                // Vehicle index of the first vehicle involved in the collision
        uint8 vehicle2Idx;                // Vehicle index of the second vehicle involved in the collision
        uint8 severity;                   // Severity of the collision - 0 = low, 1 = medium, 2 = high
    } Collision;
};
```

**PDF v1.2 (Season 8, 2026-09-07) additions.** These are not in any `.txt` attachment. Reproduced from the PDF:

```c
    struct
    {
        uint8 reason;   // 0 = Wet track, 1 = Safety car deployed, 2 = Red flag
    } PartialModeEnabled;
```

| Code | Description (PDF v1.2) | Payload |
|---|---|---|
| `PMEN` | Partial Mode enabled: race control have enabled Partial mode | `PartialModeEnabled { uint8 reason }`, `<B` at offset 33 |
| `PMDI` | Partial Mode disabled | none documented |
| `OVEN` | Overtake enabled: race control have enabled Overtake mode | none documented |
| `OVDI` | Overtake disabled | none documented |

The union stays 12 bytes and the Event packet stays 45 bytes. A parser must ignore unknown 4-character codes rather than fail.
The full 2026 event code list is the 2025 list (§5.3) plus these four codes.

### 7.5 What is NOT known / not found

- No separate retail "F1 26" game or `packetFormat` beyond 2026 was found as of 2026-10-10.
- No official statement explains whether `m_gameYear` should read 26. The two official 2026 documents disagree and live data shows 25.
- Season 8 event payloads for `PMDI`, `OVEN` and `OVDI` are undocumented (presumably none).
- Undocumented `m_gameMode` values have been reported by the community (e.g. 78 in a 2026 driver career). This is unverified.
- The 2026 appendix Game Mode table is unchanged from F1 25 (still lists "Career '25" modes).

---

## 8. Appendices (enumerations)

Values are from the official PDFs: F1 25 v3 for format 2025 and 2026 v1.2 (Season 8) for format 2026. Where only 2026 adds values, this is marked.

### 8.1 Team IDs

| ID | Team | ID | Team | ID | Team |
|---:|---|---:|---|---:|---|
| 0 | Mercedes | 158 | Art GP '24 | 465 | Art GP '25 *(2026 doc)* |
| 1 | Ferrari | 159 | Campos '24 | 466 | Campos '25 *(2026)* |
| 2 | Red Bull Racing | 160 | Rodin Motorsport '24 | 467 | Rodin Motorsport '25 *(2026)* |
| 3 | Williams | 161 | AIX Racing '24 | 468 | AIX Racing '25 *(2026)* |
| 4 | Aston Martin | 162 | DAMS '24 | 469 | DAMS '25 *(2026)* |
| 5 | Alpine | 163 | Hitech '24 | 470 | Hitech '25 *(2026)* |
| 6 | RB | 164 | MP Motorsport '24 | 471 | MP Motorsport '25 *(2026)* |
| 7 | Haas | 165 | Prema '24 | 472 | Prema '25 *(2026)* |
| 8 | McLaren | 166 | Trident '24 | 473 | Trident '25 *(2026)* |
| 9 | Sauber | 167 | Van Amersfoort Racing '24 | 474 | Van Amersfoort Racing '25 *(2026)* |
| 41 | F1 Generic | 168 | Invicta '24 | 475 | Invicta '25 *(2026)* |
| 104 | F1 Custom Team | 185 | Mercedes '24 | 476 | Mercedes '26 *(2026)* |
| 129 | Konnersport | 186 | Ferrari '24 | 477 | Ferrari '26 *(2026)* |
| 142 | APXGP '24 | 187 | Red Bull Racing '24 | 478 | Red Bull Racing '26 *(2026)* |
| 154 | APXGP '25 | 188 | Williams '24 | 479 | Williams '26 *(2026)* |
| 155 | Konnersport '24 | 189 | Aston Martin '24 | 480 | Aston Martin '26 *(2026)* |
| | | 190 | Alpine '24 | 481 | Alpine '26 *(2026)* |
| | | 191 | RB '24 | 482 | RB '26 *(2026)* |
| | | 192 | Haas '24 | 483 | Haas '26 *(2026)* |
| | | 193 | McLaren '24 | 484 | McLaren '26 *(2026)* |
| | | 194 | Sauber '24 | 485 | Audi '26 *(2026)* |
| | | | | 486 | Cadillac '26 *(2026)* |

2026 doc v1.2 only (F2 2026, Season 8): 489 Art GP '26, 490 Campos '26, 491 Rodin Motorsport '26, 492 AIX Racing '26, 493 DAMS '26, 494 Hitech '26, 495 MP Motorsport '26, 496 Prema '26, 497 Trident '26, 498 Van Amersfoort Racing '26, 499 Invicta '26.
IDs ≥ 256 fit only in format 2026, where team IDs are uint16. The F1 25 table lists only 0-194. Note there is no 487 or 488.

### 8.2 Driver IDs

From the F1 25 PDF v3. Rows 186-207 appear only in the 2026 docs (186-197 in v1.1, 198-207 added in v1.2). The F1 25 doc spells "Nico Hülkenburg"; the 2026 doc spells "Hülkenberg".

| ID | Driver | ID | Driver | ID | Driver |
|---:|---|---:|---|---:|---|
| 0 | Carlos Sainz | 62 | Alexander Albon | 164 | Joshua Dürksen |
| 2 | Daniel Ricciardo | 70 | Rashid Nair | 165 | Andrea-Kimi Antonelli |
| 3 | Fernando Alonso | 71 | Jack Tremblay | 166 | Ritomo Miyata |
| 4 | Felipe Massa | 77 | Ayrton Senna | 167 | Rafael Villagómez |
| 7 | Lewis Hamilton | 80 | Guanyu Zhou | 168 | Zak O'Sullivan |
| 9 | Max Verstappen | 83 | Juan Manuel Correa | 169 | Pepe Marti |
| 10 | Nico Hülkenberg | 90 | Michael Schumacher | 170 | Sonny Hayes |
| 11 | Kevin Magnussen | 94 | Yuki Tsunoda | 171 | Joshua Pearce |
| 14 | Sergio Pérez | 102 | Aidan Jackson | 172 | Callum Voisin |
| 15 | Valtteri Bottas | 109 | Jenson Button | 173 | Matias Zagazeta |
| 17 | Esteban Ocon | 110 | David Coulthard | 174 | Nikola Tsolov |
| 19 | Lance Stroll | 112 | Oscar Piastri | 175 | Tim Tramnitz |
| 20 | Arron Barnes | 113 | Liam Lawson | 185 | Luca Cortez |
| 21 | Martin Giles | 116 | Richard Verschoor | 186 | Luke Browning *(2026)* |
| 22 | Alex Murray | 123 | Enzo Fittipaldi | 187 | Cian Shields *(2026)* |
| 23 | Lucas Roth | 125 | Mark Webber | 188 | Arvid Lindblad *(2026)* |
| 24 | Igor Correia | 126 | Jacques Villeneuve | 189 | Dino Beganovic *(2026)* |
| 25 | Sophie Levasseur | 127 | Callie Mayer | 190 | Leonardo Fornaroli *(2026)* |
| 26 | Jonas Schiffer | 132 | Logan Sargeant | 191 | Oliver Goethe *(2026)* |
| 27 | Alain Forest | 136 | Jack Doohan | 192 | Gabriele Minì *(2026)* |
| 28 | Jay Letourneau | 137 | Amaury Cordeel | 193 | Sebastián Montoya *(2026)* |
| 29 | Esto Saari | 138 | Dennis Hauger | 194 | Alexander Dunne *(2026)* |
| 30 | Yasar Atiyeh | 145 | Zane Maloney | 195 | Max Esterson *(2026)* |
| 31 | Callisto Calabresi | 146 | Victor Martins | 196 | Sami Meguetounif *(2026)* |
| 32 | Naota Izumi | 147 | Oliver Bearman | 197 | John Bennett *(2026)* |
| 33 | Howard Clarke | 148 | Jak Crawford | 198 | Emerson Fittipaldi *(2026 v1.2)* |
| 34 | Lars Kaufmann | 149 | Isack Hadjar | 199 | Tasanopol Inthraphuvasak *(v1.2)* |
| 35 | Marie Laursen | 152 | Roman Stanek | 200 | Noel León *(v1.2)* |
| 36 | Flavio Nieves | 153 | Kush Maini | 201 | Roman Bilinski *(v1.2)* |
| 38 | Klimek Michalski | 156 | Brendon Leigh | 202 | Colton Herta *(v1.2)* |
| 39 | Santiago Moreno | 157 | David Tonizza | 203 | Rafael Câmara *(v1.2)* |
| 40 | Benjamin Coppens | 158 | Jarno Opmeer | 204 | Mari Boya *(v1.2)* |
| 41 | Noah Visser | 159 | Lucas Blakeley | 205 | Martinius Stenshorne *(v1.2)* |
| 50 | George Russell | 160 | Paul Aron | 206 | Laurens van Hoepen *(v1.2)* |
| 54 | Lando Norris | 161 | Gabriel Bortoleto | 207 | Nico Varrone *(v1.2)* |
| 58 | Charles Leclerc | 162 | Franco Colapinto | | |
| 59 | Pierre Gasly | 163 | Taylor Barnard | | |

The driver ID is 255 (2025) or 65535 (2026) for a network human.

### 8.3 Track IDs (full list)

`m_trackId` is **int8**; −1 means unknown.

| ID | Track | In F1 25 doc | In 2026 doc | Notes |
|---:|---|:-:|:-:|---|
| −1 | Unknown | yes | yes | |
| 0 | Melbourne | yes | yes | |
| 1 | Paul Ricard | | | legacy (F1 23/24 docs only) |
| 2 | Shanghai | yes | yes | |
| 3 | Sakhir (Bahrain) | yes | yes | |
| 4 | Catalunya | yes | yes | |
| 5 | Monaco | yes | yes | |
| 6 | Montreal | yes | yes | |
| 7 | Silverstone | yes | yes | |
| 8 | Hockenheim | | | legacy |
| 9 | Hungaroring | yes | yes | |
| 10 | Spa | yes | yes | |
| 11 | Monza | yes | yes | |
| 12 | Singapore | yes | yes | |
| 13 | Suzuka | yes | yes | |
| 14 | Abu Dhabi | yes | yes | |
| 15 | Texas | yes | yes | (COTA) |
| 16 | Brazil | yes | yes | (Interlagos) |
| 17 | Austria | yes | yes | (Red Bull Ring) |
| 18 | Sochi | | | legacy |
| 19 | Mexico | yes | yes | |
| 20 | Baku (Azerbaijan) | yes | yes | |
| 21 | Sakhir Short | | | legacy |
| 22 | Silverstone Short | | | legacy |
| 23 | Texas Short | | | legacy |
| 24 | Suzuka Short | | | legacy |
| 25 | Hanoi | | | legacy |
| 26 | Zandvoort | yes | yes | |
| 27 | Imola | yes | yes | |
| 28 | Portimão | | | legacy |
| 29 | Jeddah | yes | yes | |
| 30 | Miami | yes | yes | |
| 31 | Las Vegas | yes | yes | |
| 32 | Losail | yes | yes | (Qatar) |
| 39 | Silverstone (Reverse) | yes | yes | new in F1 25 |
| 40 | Austria (Reverse) | yes | yes | new in F1 25 |
| 41 | Zandvoort (Reverse) | yes | yes | new in F1 25 |
| 42 | Madrid | | yes | new with the 2026 Season Pack ("Madring") |

The F1 25 and 2026 docs omit the legacy IDs. They come from EA's F1 23/F1 24 docs and are kept so a parser does not crash on old captures.

### 8.4 Nationality IDs (identical in F1 25 and 2026 docs)

1 American, 2 Argentinean, 3 Australian, 4 Austrian, 5 Azerbaijani, 6 Bahraini, 7 Belgian, 8 Bolivian, 9 Brazilian, 10 British,
11 Bulgarian, 12 Cameroonian, 13 Canadian, 14 Chilean, 15 Chinese, 16 Colombian, 17 Costa Rican, 18 Croatian, 19 Cypriot, 20 Czech,
21 Danish, 22 Dutch, 23 Ecuadorian, 24 English, 25 Emirian, 26 Estonian, 27 Finnish, 28 French, 29 German, 30 Ghanaian,
31 Greek, 32 Guatemalan, 33 Honduran, 34 Hong Konger, 35 Hungarian, 36 Icelander, 37 Indian, 38 Indonesian, 39 Irish, 40 Israeli,
41 Italian, 42 Jamaican, 43 Japanese, 44 Jordanian, 45 Kuwaiti, 46 Latvian, 47 Lebanese, 48 Lithuanian, 49 Luxembourger, 50 Malaysian,
51 Maltese, 52 Mexican, 53 Monegasque, 54 New Zealander, 55 Nicaraguan, 56 Northern Irish, 57 Norwegian, 58 Omani, 59 Pakistani, 60 Panamanian,
61 Paraguayan, 62 Peruvian, 63 Polish, 64 Portuguese, 65 Qatari, 66 Romanian, 68 Salvadoran, 69 Saudi, 70 Scottish,
71 Serbian, 72 Singaporean, 73 Slovakian, 74 Slovenian, 75 South Korean, 76 South African, 77 Spanish, 78 Swedish, 79 Swiss, 80 Thai,
81 Turkish, 82 Uruguayan, 83 Ukrainian, 84 Venezuelan, 85 Barbadian, 86 Welsh, 87 Vietnamese, 88 Algerian, 89 Bosnian, 90 Filipino.
(There is no 0 and no 67.)

### 8.5 Session types (`m_sessionType`, `m_weekendStructure[]`, `m_recommendedSession`, forecast `m_sessionType`)

| ID | Session | ID | Session |
|---:|---|---:|---|
| 0 | Unknown | 10 | Sprint Shootout 1 |
| 1 | Practice 1 | 11 | Sprint Shootout 2 |
| 2 | Practice 2 | 12 | Sprint Shootout 3 |
| 3 | Practice 3 | 13 | Short Sprint Shootout |
| 4 | Short Practice | 14 | One-Shot Sprint Shootout |
| 5 | Qualifying 1 | 15 | Race |
| 6 | Qualifying 2 | 16 | Race 2 |
| 7 | Qualifying 3 | 17 | Race 3 |
| 8 | Short Qualifying | 18 | Time Trial |
| 9 | One-Shot Qualifying | | |

Observed (community): a sprint race arrives as type 15 or 16 ("Race"/"Race 2"). Order within the weekend is the only discriminator.

### 8.6 Game Mode IDs (`m_gameMode`), identical in the F1 25 and 2026 docs

4 Grand Prix '23 · 5 Time Trial · 6 Splitscreen · 7 Online Custom · 15 Online Weekly Event · 17 Story Mode (Braking Point) ·
27 My Team Career '25 · 28 Driver Career '25 · 29 Career '25 Online · 30 Challenge Career '25 · 75 Story Mode (APXGP) · 127 Benchmark.
Earlier games listed more (e.g. F1 24: 0 Event Mode, 3 Grand Prix, 8 Online League, 11-14 Invitationals/Championships, 19-26 older careers). Treat unknown values as "other".

### 8.7 Ruleset IDs (`m_ruleSet`)

0 Practice & Qualifying · 1 Race · 2 Time Trial · 12 Elimination. F1 23 additionally listed 4 Time Attack, 6 Checkpoint Challenge, 8 Autocross, 9 Drift, 10 Average Speed Zone, 11 Rival Duel.

### 8.8 Surface types (`CarTelemetryData.m_surfaceType[4]`)

"These types are from physics data and show what type of contact each wheel is experiencing."
0 Tarmac · 1 Rumble strip · 2 Concrete · 3 Rock · 4 Gravel · 5 Mud · 6 Sand · 7 Grass · 8 Water · 9 Cobblestone · 10 Metal · 11 Ridged.

### 8.9 Button flags (`BUTN` event, `buttonStatus` uint32)

| Bit | Button | Bit | Button |
|---|---|---|---|
| 0x00000001 | Cross or A | 0x00010000 | Right Stick Right |
| 0x00000002 | Triangle or Y | 0x00020000 | Right Stick Up |
| 0x00000004 | Circle or B | 0x00040000 | Right Stick Down |
| 0x00000008 | Square or X | 0x00080000 | Special |
| 0x00000010 | D-pad Left | 0x00100000 | UDP Action 1 |
| 0x00000020 | D-pad Right | 0x00200000 | UDP Action 2 |
| 0x00000040 | D-pad Up | 0x00400000 | UDP Action 3 |
| 0x00000080 | D-pad Down | 0x00800000 | UDP Action 4 |
| 0x00000100 | Options or Menu | 0x01000000 | UDP Action 5 |
| 0x00000200 | L1 or LB | 0x02000000 | UDP Action 6 |
| 0x00000400 | R1 or RB | 0x04000000 | UDP Action 7 |
| 0x00000800 | L2 or LT | 0x08000000 | UDP Action 8 |
| 0x00001000 | R2 or RT | 0x10000000 | UDP Action 9 |
| 0x00002000 | Left Stick Click | 0x20000000 | UDP Action 10 |
| 0x00004000 | Right Stick Click | 0x40000000 | UDP Action 11 |
| 0x00008000 | Right Stick Left | 0x80000000 | UDP Action 12 |

"UDP Action 1-12" are bindable in the game's controls. They are useful for coach hotkeys such as "mark this lap".

### 8.10 Penalty types (`PENA.penaltyType`)

0 Drive through · 1 Stop Go · 2 Grid penalty · 3 Penalty reminder · 4 Time penalty · 5 Warning · 6 Disqualified · 7 Removed from formation lap ·
8 Parked too long timer · 9 Tyre regulations · 10 This lap invalidated · 11 This and next lap invalidated · 12 This lap invalidated without reason ·
13 This and next lap invalidated without reason · 14 This and previous lap invalidated · 15 This and previous lap invalidated without reason · 16 Retired · 17 Black flag timer.

### 8.11 Infringement types (`PENA.infringementType`)

0 Blocking by slow driving · 1 Blocking by wrong way driving · 2 Reversing off the start line · 3 Big Collision · 4 Small Collision ·
5 Collision failed to hand back position single · 6 Collision failed to hand back position multiple · 7 Corner cutting gained time ·
8 Corner cutting overtake single · 9 Corner cutting overtake multiple · 10 Crossed pit exit lane · 11 Ignoring blue flags · 12 Ignoring yellow flags ·
13 Ignoring drive through · 14 Too many drive throughs · 15 Drive through reminder serve within n laps · 16 Drive through reminder serve this lap ·
17 Pit lane speeding · 18 Parked for too long · 19 Ignoring tyre regulations · 20 Too many penalties · 21 Multiple warnings ·
22 Approaching disqualification · 23 Tyre regulations select single · 24 Tyre regulations select multiple · 25 Lap invalidated corner cutting ·
26 Lap invalidated running wide · 27 Corner cutting ran wide gained time minor · 28 Corner cutting ran wide gained time significant ·
29 Corner cutting ran wide gained time extreme · 30 Lap invalidated wall riding · 31 Lap invalidated flashback used · 32 Lap invalidated reset to track ·
33 Blocking the pitlane · 34 Jump start · 35 Safety car to car collision · 36 Safety car illegal overtake · 37 Safety car exceeding allowed pace ·
38 Virtual safety car exceeding allowed pace · 39 Formation lap below allowed speed · 40 Formation lap parking · 41 Retired mechanical failure ·
42 Retired terminally damaged · 43 Safety car falling too far back · 44 Black flag timer · 45 Unserved stop go penalty · 46 Unserved drive through penalty ·
47 Engine component change · 48 Gearbox change · 49 Parc Fermé change · 50 League grid penalty · 51 Retry penalty · 52 Illegal time gain ·
53 Mandatory pitstop · 54 Attribute assigned.

### 8.12 Inline enums (from struct comments)

| Field(s) | Values |
|---|---|
| Weather (`m_weather`, forecast) | 0 clear, 1 light cloud, 2 overcast, 3 light rain, 4 heavy rain, 5 storm |
| Temperature change (forecast) | 0 up, 1 down, 2 no change |
| `m_formula` | 0 F1 Modern, 1 F1 Classic, 2 F2, 3 F1 Generic, 4 Beta, 6 Esports, 8 F1 World, 9 F1 Elimination, **13 F1 26** (2026 only) |
| `m_safetyCarStatus` | 0 no safety car, 1 full, 2 virtual, 3 formation lap |
| Marshal `m_zoneFlag`, `m_vehicleFIAFlags` | −1 invalid/unknown, 0 none, 1 green, 2 blue, 3 yellow |
| `m_networkGame` | 0 offline, 1 online |
| `m_forecastAccuracy` | 0 perfect, 1 approximate |
| `m_aiDifficulty` | 0-110 |
| `m_steeringAssist`, `m_pitAssist`, `m_pitReleaseAssist`, `m_ERSAssist`, `m_DRSAssist` | 0 off, 1 on |
| `m_brakingAssist` | 0 off, 1 low, 2 medium, 3 high |
| `m_gearboxAssist` | 1 manual, 2 manual & suggested gear, 3 auto |
| `m_dynamicRacingLine` / `...Type` | 0 off, 1 corners only, 2 full / 0 2D, 1 3D |
| `m_sessionLength` | 0 None, 2 Very Short, 3 Short, 4 Medium, 5 Medium Long, 6 Long, 7 Full |
| Speed / temperature units | 0 MPH, 1 KPH / 0 Celsius, 1 Fahrenheit |
| `m_recoveryMode` | 0 none, 1 flashbacks, 2 auto-recovery |
| `m_flashbackLimit` | 0 low, 1 medium, 2 high, 3 unlimited |
| `m_surfaceType` (session setting) | 0 simplified, 1 realistic |
| `m_lowFuelMode` / `m_raceStarts` | 0 easy, 1 hard / 0 manual, 1 assisted |
| `m_tyreTemperature` | 0 surface only, 1 surface & carcass |
| `m_pitLaneTyreSim` | 0 on, 1 off |
| `m_carDamage` / `m_carDamageRate` | 0 off, 1 reduced, 2 standard, 3 simulation / 0 reduced, 1 standard, 2 simulation |
| `m_collisions` | 0 off, 1 player-to-player off, 2 on |
| `m_collisionsOffForFirstLapOnly`, `m_mpOffForGriefing` | 0 disabled, 1 enabled |
| `m_mpUnsafePitRelease` | 0 on, 1 off |
| `m_cornerCuttingStringency` | 0 regular, 1 strict |
| `m_pitStopExperience` | 0 automatic, 1 broadcast, 2 immersive |
| `m_safetyCar`, `m_redFlags` | 0 off, 1 reduced, 2 standard, 3 increased |
| `m_safetyCarExperience`, `m_formationLapExperience` | 0 broadcast, 1 immersive |
| `m_parcFermeRules`, `m_formationLap`, `m_equalCarPerformance`, `m_affectsLicenceLevel*` | 0 off, 1 on |
| LapData `m_pitStatus` | 0 none, 1 pitting, 2 in pit area |
| LapData `m_driverStatus` | 0 in garage, 1 flying lap, 2 in lap, 3 out lap, 4 on track |
| `m_resultStatus` (LapData, FinalClassification) | 0 invalid, 1 inactive, 2 active, 3 finished, 4 didnotfinish, 5 disqualified, 6 not classified, 7 retired |
| `m_resultReason` / RTMT `reason` | 0 invalid, 1 retired, 2 finished, 3 terminal damage, 4 inactive, 5 not enough laps completed, 6 black flagged, 7 red flagged, 8 mechanical failure, 9 session skipped, 10 session simulated |
| DRSD `reason` | 0 wet track, 1 safety car deployed, 2 red flag, 3 min lap not reached |
| PMEN `reason` (2026 v1.2) | 0 wet track, 1 safety car deployed, 2 red flag |
| SCAR `safetyCarType` / `eventType` | 0 none, 1 full, 2 virtual, 3 formation lap / 0 deployed, 1 returning, 2 returned, 3 resume race |
| COLL `severity` (2026) | 0 low, 1 medium, 2 high |
| `m_tractionControl` (status) | 0 off, 1 medium, 2 full |
| `m_fuelMix` | 0 lean, 1 standard, 2 rich, 3 max |
| `m_ersDeployMode` | 0 none, 1 medium, 2 hotlap, 3 overtake (2025) / **boost** (2026) |
| `m_platform` | 1 Steam, 3 PlayStation, 4 Xbox, 6 Origin, 255 unknown |
| Lobby `m_readyStatus` | 0 not ready, 1 ready, 2 spectating |
| CarTelemetry2 `m_activeAeroMode` | 0 corner mode, 1 straight mode |
| CarTelemetry2 availability / active flags | 0 not available / not active, 1 available / active. Distances: 0 = not available, else metres until available |
| CarTelemetry2 `m_2026Regulations` | 0 pre-2026 car, 1 2026 regulations |

### 8.13 Tyre compounds

| Field | F1 Modern | F1 Classic | F2 |
|---|---|---|---|
| `m_actualTyreCompound` (and `m_tyreStintsActual`, `m_tyreActualCompound`) | 16 C5, 17 C4, 18 C3, 19 C2, 20 C1, 21 C0, **22 C6** (documented from F1 25 v3), 7 inter, 8 wet | 9 dry, 10 wet | 11 super soft, 12 soft, 13 medium, 14 hard, 15 wet |
| `m_visualTyreCompound` (and visual stint fields) | 16 soft, 17 medium, 18 hard, 7 inter, 8 wet | same as F1 Modern | F2 '20: 15 wet, 19 super soft, 20 soft, 21 medium, 22 hard |

Note that the value **22 is ambiguous across fields**: it means actual C6 but visual F2 hard. Always interpret it together with the field and `m_formula`.

---

## 9. In-game settings, send rates, console availability

### 9.1 Settings (official FAQ)

Main menu → Options (Triangle / Y) → Settings → **UDP Telemetry Settings** (at the bottom of the list). From there you can set:
- **UDP Telemetry**: On/Off (default Off in the XML)
- **UDP Broadcast Mode**: On/Off. Broadcast sends to the whole subnet, so several devices can listen; no target IP is needed, only the port.
- **UDP IP Address**: target IP when not broadcasting (default 127.0.0.1 in the XML)
- **UDP Port**: default **20777**
- **UDP Send Rate**: default **20 Hz** (XML `sendRate="20"`)
- **UDP Format**: 2025 (F1 25), or 2026 with the Season Pack
- **Your Telemetry**: Restricted (default) / Public
- **Show online ID / gamertags**: off by default; needs a confirmation box
- D-BOX (PC only) and LED device options (Fanatec / SLI Pro native support, SLI Pro brightness 0-255)

PC only: `...\Documents\My Games\<game_folder>\hardwaresettings\hardware_settings_config.xml` contains

```xml
<udp enabled="false" broadcast="false" ip="127.0.0.1" port="20777" sendRate="20" format="2025" yourTelemetry="restricted" onlineNames="off" />
```

The 2026 PDF shows `format="2026"`. Changes made in-game overwrite manual edits. "All options can be changed during a game session and will take immediate effect."

### 9.2 Send-rate options

The F1 25 spec does not list the menu values. EA's own accessibility documentation for F1 2021 lists **10, 20, 30, 60 Hz (default 20)**: <https://www.ea.com/able/resources/f1-2021/ps5/telemetry>.
The menu values for F1 25 itself were not confirmed from an EA source. 10 Hz and 60 Hz are confirmed to work on F1 25 + 2026 pack (PS5) by measured captures in `skrx7392/f126-race-engineer`.

Measured cadence at the 60 Hz setting (f126, 2026 format, PS5, 60 s window) agrees with the spec:
IDs 0, 2, 6, 7, 13 and 16 ran at about 59.9 Hz (they follow the menu rate). IDs 11 and 12 ran at about 20 Hz, 10 (Car Damage) at about 10 Hz, 1 and 5 at about 2 Hz, 15 at 1 Hz, 4 at 0.2 Hz, and 3 is event-driven.
Total load at 60 Hz is about 417 packets/s and about 414 KB/s. At 10 Hz the menu-rate packets ran at about 9.7 Hz.

### 9.3 Console availability

UDP telemetry is available on **PS5 and Xbox Series X|S** as well as PC. Evidence:
- the official FAQ describes the menu path with "triangle / Y" and only marks the XML file and D-BOX as PC-only;
- the participant-name rules cover Xbox and PlayStation, and `m_platform` includes 3 (PlayStation) and 4 (Xbox);
- all four reviewed repos and the F1Laps / GO Fast guides use PS5 or Xbox as the source.

Practical requirements: the console and the receiver must be on the same LAN/subnet (directed UDP, no NAT traversal), and the receiver's firewall must allow inbound UDP on the port. With broadcast off, set the console's UDP IP to the receiver's LAN IP.

---

## 10. Known issues, errata and parser gotchas

1. **`m_gameYear == 0` (and `m_sessionUID`, `m_sessionTime`, `m_frameIdentifier`, `m_overallFrameIdentifier` == 0)** in `BUTN` events sent in the pre-race strategy menu. This is EA bug 12214767, status *CONFIRMED*, seen on v1.02 with format 2025. A community reply also reports zeroed `gameYear` and `overallFrameIdentifier` when the game sends format 2023.
2. **`m_sessionUID == 0`** in menu and loading-screen packets (observed in f126 captures). Do not treat 0 as a new session.
3. **`m_gameYear == 25` in format 2026.** Never use it to choose a decoder.
4. **Car Damage frequency.** The packet section says 10/s, but the FAQ frame example says "Car Damage (since 2 updates per second)". It measures about 10 Hz. Do not assume either rate; key on header time.
5. **Spec comment typo**: `CarSetupData.m_rearAntiRollBar` is commented "Front anti-roll bar".
6. **Name mismatches between the PDF and `.txt`** (`m_carSetups` vs `m_carSetupData`, `m_vehicleFiaFlags` vs `m_vehicleFIAFlags`, `m_ersHarvestedLimitPerLap` vs `m_ersHarvestLimitPerLap`, `StartLIghts` vs `StartLights`). Layouts are identical, so only naming differs.
7. **The 2026 `.txt` is behind the PDF.** It lacks the v1.2 `PMEN`/`PMDI`/`OVEN`/`OVDI` codes and the `PartialModeEnabled` union member.
8. **2026 g-force scale conflict.** The official PDF says divide by **1000.0f**. `skrx7392/f126-race-engineer` instead found empirically that **1024** fits best. It compared against 256, 512, 2048 and 4096, but *not* 1000. The two differ by 2.4%. Use 1000 per spec, and add a regression test that compares against acceleration derived from the float world-velocity vector before trusting either.
9. **Sentinels.** 255 marks "not set/invalid" for u8 indices (`m_secondaryPlayerCarIndex`, `m_speedTrapFastestLap`, TT car indices, `m_mfdPanelIndex` "closed", stint `m_endLap` "current"). Format 2026 widens IDs, so the sentinel becomes 65535. Observed (not in the spec): event u8 fields use 255 for "n/a", and `m_gridPosition` 0 means no grid slot.
10. **Unverified community report**: `m_driverStatus` and `m_gridPosition` in LapData "seem to be in the wrong order" (F1 25 discussion thread). Both official documents give `m_gridPosition` then `m_driverStatus`. Validate against a real capture (driver status should only take values 0-4 and change on out-lap and in-lap transitions).
11. **2025 format with 2026 content.** Team IDs above 255 cannot be encoded in uint8 and 2026 data such as ERS limits is missing. Third-party guides report "F1 Generic" teams. Require format 2026 for 2026 cars.
12. **`m_vehicleFIAFlags`**: the official values are −1..3. Some libraries add 4 = red; it is not in EA's spec.
13. **LapData distances may be negative** before the car first crosses the line (formation, out-laps). Values can also jump backwards on flashback (`FLBK` event, `m_sessionTime` goes back).
14. **Packet sizes are fixed.** A strict `len(datagram) == expected[(format, id)]` check is safe for every ID in both formats. Event is always 45 bytes even when the payload is shorter.
15. **Observed (PS5, F1 25 v1.26, Monza race excerpt): a negative `m_deltaToCarInFront` wraps into the uint16 ms part.** For about 1.4 s after a position change (194.81-196.16 s) the player's `m_deltaToCarInFrontMSPart` reads **65403** (= −133 ms) with minutes part 0. A ms part ≥ 60000 is therefore not a gap; pitwall reads it as unknown. Around a position change the *old* car's gap is also reported for about 2 s, and values are wrong while an adjacent car is in the pit lane (Austria: 19.1 s); pitwall's race strategy publishes a gap only after 4 s without such a change (`pitwall/strategy/gaps.py`).
16. **Observed (PS5, F1 25 v1.26): `m_tyresWear` is whole percent.** 59 248 CarDamage samples across the 2026-10-10 races were all integral, so per-lap wear increments are quantised to 1 %; a stint's wear rate is best taken from the sum of per-lap increments (it telescopes, so the error stays one step over the stint).
17. **Observed (PS5, full Austria race): the pit-lane timer resets at the pit exit, and `m_numPitStops` / `m_driverStatus` change at the box.** Car 14: `m_pitStatus` 0 → 1 at 4264 m on lap 65, 2 in the box 7.2 s later (stop 3353 ms), exit at 257 m on lap 66; `m_pitLaneTimeInLaneInMS` reached 20019 ms and read 0 again at the exit; `m_numPitStops` incremented and `m_driverStatus` went 2 (in lap) → 3 (out lap) when the car left the box. `m_pitStopTimerInMS` keeps the stop time until the exit. This is consistent with item 10: `m_driverStatus` takes only 0-4 and changes on in-lap / out-lap transitions in the spec's field order.
18. **Observed (PS5, F1 25 v1.26): TyreSets `m_lapDeltaTime` tracks the fitted set's degradation.** It is the lap delta *versus the fitted set*: over laps 62-70 of the full Austria race the gain of new mediums over the fitted (37-45 laps old) mediums grew from 0.274 to 1.003 s, about 0.091 s a lap per lap, while the fitted set's `m_lifeSpan` ("laps left") fell one per lap (33 → 26) with `m_usableLife` 37. The player's TyreSets packet arrives about once a second (the game cycles through the cars).

---

## 11. Parser implementation checklist (pitwall)

- Read `fmt = uint16 @0`, `pid = uint8 @6`. Look up `(fmt, pid)` in a size table (§3) and check the length exactly. Count and drop mismatches; never raise.
- Use the per-format struct table. Formats 2025 and 2026 differ only in the structs listed in §7.2, plus `N_CARS` (22 vs 24).
- For CarTelemetry/CarStatus/LapData/Motion, decode only the player car (`m_playerCarIndex`) on the hot path. Decode all cars for timing or tower features.
- Event: decode `code = bytes[29:33].decode('ascii')`. Map the code to a payload fmt at offset 33. Unknown codes produce a generic event.
- Session history and tyre sets arrive one car per packet in rotation. Cache them per `m_carIdx`.
- Track session identity by `m_sessionUID` (ignore 0). Treat a decreasing `m_sessionTime` within the same UID as flashback or restart. `FLBK` gives the target frame and time.
- Use distance-aligned (`m_lapDistance`) resampling for lap comparison; see `f1-repos.md` for approaches.
