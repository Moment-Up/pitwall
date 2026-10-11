# ACC Broadcasting API over UDP (`acc-broadcast`): implementation spec

Research date: 2026-10-10. Family: `acc-broadcast`. Games: **Assetto Corsa Competizione (PC)**; Assetto Corsa EVO (PC)
is **unknown** (§12). Consoles have no interface (§11).

**Status: research only, no code.** No pitwall decoder or client exists yet. This file is the reference one will be
written from. **No code is copied here.** Layouts are tables, behaviour is prose.

Read with:
- `docs/research/forza-ac-acc-iracing.md` §3.2, the first summary. This file supersedes it where they differ (§15.2).
- `docs/research/track-knowledge-sources.md`: L0b-ACC, §4.2, §6.1 method I, V9, §7.6 and Phase 6. This feed is what that
  field model consumes.
- `docs/research/game-compatibility.md`: family row 5 and §10 item 7 (AC EVO).

---

## 0. Summary

- **What it is.** Kunos built a two-way UDP interface into the ACC PC client for spectator and broadcast tools. An
  external app registers with the running game. The game then streams session state plus one update per car, for
  **every car**, at an interval the app chooses.
- **How it reaches the Mac.**
  - The user sets a UDP port in `Documents\Assetto Corsa Competizione\Config\broadcasting.json` on the gaming PC.
    The key is spelled `updListenerPort`; 9000 is the usual value.
  - pitwall sends a REGISTER datagram from an ephemeral port to `<pc-ip>:<port>`.
  - ACC answers to that source address. Nothing else is needed: no relay, no shared memory, no Windows software.
- **What it carries**, for all cars:
  - world X/Y (2-D) and yaw;
  - pit-lane location, integer km/h, gear;
  - race position, `splinePosition` (0..1 lap fraction), completed laps and a live delta;
  - best, last and current lap with **sector splits of completed laps**.
- **Per session it also carries:**
  - track name, numeric id and length in metres;
  - session type, phase, elapsed time and time remaining;
  - air and track temperature (integer °C);
  - entry list: car model, team, race number, drivers.
- **What it lacks:**
  - throttle, brake, steering, clutch, RPM;
  - tyres, fuel, damage, setup;
  - live sector index;
  - weather (clouds, rain and wetness were zeroed **by design** in 2021, §10).

  It **cannot drive input coaching.** It can feed lap timing, race context and the all-car field model
  (track-knowledge L0b-ACC).
- **Official spec.** There is no prose spec. The vendor reference is Kunos's C# sample `ksBroadcastingNetwork`, which
  ships inside the game (and since about 2025 with the ACC Dedicated Server tool) [K1][K2-p15].
  - I could not fetch it from Kunos, because it is not on the web.
  - I read it through two third-party mirrors [K1a][K1b] and cross-checked every message against:
    - two independent MIT re-implementations, devology [C1] and ACC Race Control [C2];
    - seven **third-party recorded datagrams**, one of each inbound type, from one ACC connection. Six have receipt
      timestamps of 2026-03-14 [C3].
- **Verification done here.** All seven recorded datagrams decode with a clean-room decoder written from §5. Bytes
  consumed equal the datagram length for each one (84, 101, 57, 671, 48, 21 and 61 bytes) (§14.2).
- **Version caveats that matter.** The stream carries **no game-version field**, and the protocol byte has stayed 4.
  - Before ACC **v1.10.1 (2024-04-04)**, the "world position" floats held orientation angles.
  - Also before v1.10.1, `cupPosition` was wrong and the 24h Nürburgring sent no TRACK_DATA [K3].
- **Licence.** No licence covers the Kunos SDK. pitwall implements the wire protocol clean-room in Python and uses it at
  runtime only. Commercial distribution waits on counsel (§13).

Status vocabulary:
- **Kunos-sample**: what the vendor's sample code reads or writes.
- **Kunos-staff**: forum posts by a "KS Dev Team / Staff Member", or patch notes.
- **Community**: forum users and open-source clients.
- **3P-recorded**: bytes recorded by a third party from a real game.
- **Unverified**: one source, or inference.

---

## 1. Sources

| Key | Source | Licence | Used for |
|---|---|---|---|
| K1 | Kunos SDK sample `ksBroadcastingNetwork` (`BroadcastingNetworkProtocol.cs`, `BroadcastingEnums.cs`, `ACCUdpRemoteClient.cs`) and `ksBroadcastingTestClient`. It ships as `sdk\broadcasting\Sources\...` in the game install [K2-p1][K2-p6]. A 2025 user post says it now comes with the "Assetto Corsa Competizione Dedicated Server" Steam tool [K2-p15] (Unverified) | **none** (readme: the library "can be directly used in your own .Net application") | Message types, field order and types, the protocol version, and the client behaviour. Every layout row cites it |
| K1a | Mirror: framf0rt/ACCBroadcastingTool-Modified at first commit `da960ec` (2020-08-03). Its own additions (`MASTERBROADCASTER_EVENT = 8`, car-class logic, log4net) are **excluded** from this spec | repo labelled MIT (© 2020 Anders Ekendahl). The label does not cover the Kunos-authored files | Reading K1 |
| K1b | Mirror: Crew Chief V4, `CrewChiefV4/ACC/ksBroadcastingNetwork/` | Crew Chief licence. It does not cover the Kunos files | Second reading of K1; its "TrackPosition: THIS IS ALWAYS ZERO" note |
| K2 | Kunos forum, "Let's talk about broadcasting (programmers thread)", 15 pages, 2018-12-12 → 2025-06 | forum | Endianness, string format, bugs and their dates, staff statements. Cited per page as K2-pN |
| K3 | Kunos, "ACC v1.10.1 hotfix update out now", AC Support (KS Dev Team), 2024-04-04 | — | Fixes to world position, cup position and N24 TRACK_DATA |
| K4 | ACC EULA (Steam app 805550) | EULA | §13 |
| C1 | devology-uk/sim-racing-sdk @ `c23c291` (pushed 2026-10-10): `SimRacingSdk.Acc.Udp`, `SimRacingSdk.Ace.Udp` | **MIT** | Cross-check of every reader. Also the AC EVO lead (§12) |
| C2 | LennysLounge/ACC-Race-Control @ `42f87f55`: `AccBroadcastingProtocol.java`, `AccConnection.java`, README | **MIT** © 2021 Leonard Schüngel | Cross-check; UNREGISTER with connection id; receive buffer and timeout; setup steps |
| C3 | prule/acc-client @ `88b8e85`: `acc-client-core/src/main/resources/.../simulator/playback-events.csv`, `docs/Sample Run.md`, ReadMe | **no licence** (facts only) | Seven 3P-recorded datagrams used as decoding cross-checks in §14. Six (types 2–7) come from the CSV, receipt time 2026-03-14. The type-1 reply comes from the Sample Run log and has the same connection id 18. The ACC build is not stated |
| O1 | 505 Games AC EVO changelogs 0.6, 0.8, 0.8.1, 0.9 and 0.9.1 | — | §12 |
| O2 | Kunos "ACE SharedFileOut Documentation v1" (changelog to 2026-04-28), copy in C1's `research/` folder | — | §12 (no mention of UDP) |
| S1 | racesimcentral.net republication of the v1.10.1 notes | — | Secondary copy of K3 only |

**Not read: Race-Element (GPL-3.0) or pyacc (GPL-3.0).** CLAUDE.md forbids copying GPL code, and nothing here
depends on them.

**Search limit.** The web-search budget for this session ran out partway through. Direct fetches still worked.
Items this left unverified are marked as such: the encoding of `broadcasting.json`, and Kunos's official car-model id
list.

---

## 2. Games and per-game differences

| Game / platform | Interface | Evidence | Notes |
|---|---|---|---|
| ACC, PC (Steam), v1.10.1 or later | Broadcasting UDP, protocol 4 | K1, K3, C1, C2, 3P-recorded C3 (2026) | Target. World X/Y valid only from v1.10.1 (§10) |
| ACC, PC, before v1.10.1 | same wire format | K2 (2020-2024 reports), C2 | World X/Y/yaw hold orientation angles; `cupPosition` = overall position; no N24 TRACK_DATA |
| ACC, PS4 / PS5 / Xbox | **none** | [P1] §3.3, game-compatibility | No `broadcasting.json` and no UDP setting; no report of real console use (§11) |
| ACC Dedicated Server | **none** | K2-p6 (2020-05-13): "There is no server API (yet)"; K2-p4 (2020-04-26): "you can't connect directly to the server itself" | Broadcast comes only from a game client: a driving client, or a spectator client on a second PC |
| Assetto Corsa EVO, PC | **unknown** | C1 port only. No Kunos source (§12) | Do not implement until the probe in §12.3 succeeds |
| Assetto Corsa (2014) | different protocol | `protocols/ac-remote-udp.md` | Not this family |

---

## 3. Transport

| Item | Value | Status / source |
|---|---|---|
| Socket | UDP, **unicast**. No broadcast or multicast | K1 (`UdpClient.Connect(ip, port)`) |
| ACC side | Listens on `updListenerPort` from `broadcasting.json`. Usually **9000** (Kunos test client default, C2 README, C3 README) | K1 test client; Community |
| Client side | Any local port. The Kunos client uses an unbound `UdpClient` connected to `ip:port`, so the OS picks an ephemeral port | K1 |
| Direction | Client → ACC: REGISTER, then requests and commands. ACC → client: everything inbound, sent to the source address/port of the REGISTER | K1, K2-p1 ("a UPD two way interface") |
| ACC source port | Replies arrive from `updListenerPort`. This is an inference: the Kunos client's connected socket would drop anything else | K1 (inference) |
| LAN use | Works from another PC with the gaming PC's IP; the Windows firewall must allow it | Community: K2-p10 (2020-08-06); K2-p4 (2020-04-25: remote "doesn't always connect the first time") |
| Endianness | **Little-endian** throughout | Kunos-sample (.NET `BinaryReader`); K2-p2 Minolin (2019-01-02): "expected in little endian" |
| One message per datagram | Byte 0 is the message type. The Kunos reader parses one message per datagram and ignores any trailing bytes | K1 |
| Max size seen | 671 B (TRACK_DATA, Red Bull Ring). C2 uses a 2048 B receive buffer. pitwall should use 65535 | C3, C2 |
| Auth | Plain-text `connectionPassword` (required) and `commandPassword` (write access) inside REGISTER | K1, C3 |

### 3.1 `broadcasting.json` (on the gaming PC)

```
{
    "updListenerPort": 9000,
    "connectionPassword": "asd",
    "commandPassword": ""
}
```

Path: `Documents\Assetto Corsa Competizione\Config\broadcasting.json` [C2 README][C3 ReadMe][C1 AccPathProvider].

- **Key spelling.** `updListenerPort` is spelled with "upd". C1's model maps exactly these three JSON names.
- **Enabling the API.** The API is enabled by giving it a port. C1's compatibility check requires a port above 1023.
  - Unverified: whether the shipped default is 0, and whether ACC must restart after an edit.
- **File encoding.** Unverified. [P1] §3.2 relays a community report that the file is UTF-16LE and must stay so. C1
  reads it as UTF-8 and falls back to UTF-16 on a parse error.

  The setup guide should say: "edit in Notepad and keep the existing encoding".
- **pitwall never reads this file.** It is on the PC, and the user types the port and password into the Connect page.

### 3.2 Session procedure

1. Send **REGISTER** (§4.1) to `<pc-ip>:<updListenerPort>`.
2. ACC replies with **REGISTRATION_RESULT** (§5.2): connection id, success flag and writable flag.
   - **Wrong command password.** A recorded reply (C3) shows success with read-only access and the text
     `Wrong command mode password, readonly access granted`.
   - Wrong connection password, or a protocol-version mismatch: the reply is **unverified**.
     - In 2019, an outdated client made the game show "Your broadcasting control app is outdated" [K2-p2].
3. Send **REQUEST_ENTRY_LIST** and **REQUEST_TRACK_DATA**, each carrying the connection id.
   - The Kunos sample does this on every REGISTRATION_RESULT [K1].
4. ACC then streams:
   - one **REALTIME_UPDATE** (session) per interval;
   - one **REALTIME_CAR_UPDATE** per car per interval;
   - **ENTRY_LIST** / **ENTRY_LIST_CAR** on request and "automatically when something changes" [K1 comment];
   - **TRACK_DATA** on request;
   - **BROADCASTING_EVENT** as events occur.

   The structure of each burst is inferred from K1's design and has not been measured (V-3).
5. **Unknown car.** If a REALTIME_CAR_UPDATE names a car index that is not in the entry list, or its driver count
   differs, request the entry list again. Rate-limit this: K1 uses at most 1 per second, K1b 1 per 5 s.
6. **To leave, send UNREGISTER with the connection id** (§4.3).
   - The Kunos sample sends only the type byte.
   - Without the id, users found that "it will become terribly slow to connect after a few attempts" [K2-p6/p7,
     2020-05-17/18; K2-p13, 2022-01-03].
   - C2 sends the id.

**Session lifetime: Community, dated.**
- "the client connection is only valid for a particular race" [K2-p3, 2020-03-01].
- After joining a session, "you can only request a UDP handshake with the client once" [K2-p4, 2020-04-27].
- In single player, the game "wont connect any more clients" after the green light [K2-p4, 2020-04-25].
- Connecting "does take more time ... especially after the green light"; a 5 s timeout and retry helped [K2-p4].

None of these has been re-tested on a current build (V-9). The client design in §16 assumes the worst case: re-register
on every session change, and back off when a registration is not answered.

---

## 4. Wire primitives and outbound messages (client → ACC)

### 4.0 Primitives

| Name | Encoding | Source |
|---|---|---|
| u8, u16, i32 | unsigned 8 / unsigned 16 / signed 32-bit, little-endian | K1 |
| f32 | IEEE-754 binary32, little-endian | K1 (`ReadSingle`) |
| string | `u16` byte length, then that many **UTF-8** bytes (no terminator) | K1; K2-p1 (Minolin 2018-12-12); K2-p2 ("your string size descriptor is 1 byte instead of a short") |
| list count | **u8** for camera sets, cameras, HUD pages, drivers and splits. **u16 for the ENTRY_LIST car count** (the exception) | K1; C3 (ENTRY_LIST count = `19 00`) |
| "no value" | `Int32.MaxValue` (0x7FFFFFFF) in lap times and splits | K1 |

### 4.1 REGISTER_COMMAND_APPLICATION (type 1)

| Rel. offset | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | type | 1 |
| 1 | u8 | protocolVersion | **4** (`BROADCASTING_PROTOCOL_VERSION`) [K1][C1][C2]. A 2019 sample used 2 [K2-p2] |
| 2 | string | displayName | Free text. pitwall uses `pitwall` |
| … | string | connectionPassword | Must match `broadcasting.json` |
| … | i32 | msRealtimeUpdateInterval | ms between realtime bursts (§9) |
| … | string | commandPassword | Empty string allowed. pitwall sends no commands, so read-only is fine |

Example (pitwall-built, 22 B): name `pitwall`, password `asd`, interval 100 ms, empty command password:
`01 04 07 00 70 69 74 77 61 6c 6c 03 00 61 73 64 64 00 00 00 00 00`.

C3's logged REGISTER (name `Test`, `asd`, 1000 ms, `asd`) has the same shape:
`01 04 04 00 54 65 73 74 03 00 61 73 64 e8 03 00 00 03 00 61 73 64`.

### 4.2 Requests (5 B each)

| Type | Name | Layout | Source |
|---|---|---|---|
| 10 | REQUEST_ENTRY_LIST | u8 type, i32 connectionId | K1, C1, C2 |
| 11 | REQUEST_TRACK_DATA | u8 type, i32 connectionId | K1, C1, C2 |

Example for connection id 18: `0a 12 00 00 00` and `0b 12 00 00 00`.

### 4.3 UNREGISTER_COMMAND_APPLICATION (type 9)

| Rel. offset | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | type | 9 |
| 1 | i32 | connectionId | **Send it.** K1 and C1 send only the type byte. C2 and the community fix send the id (§3.2) |

Example: `09 12 00 00 00`.

### 4.4 Command messages: pitwall must never send these

These need write access (the command password) and change what the user's game shows. They are listed only so that
pitwall can recognise them.

- **CHANGE_HUD_PAGE (49):** i32 connectionId, string page.
- **CHANGE_FOCUS (50):** i32 connectionId; u8 hasCar [+ u16 carIndex]; u8 hasCamera [+ string set + string camera].
- **INSTANT_REPLAY_REQUEST (51):** i32 connectionId, f32 startSessionTime, f32 durationMs, i32 initialFocusedCarIndex,
  string cameraSet, string camera.
- **52 and 60:** "planned" replay-highlight types, with no layout in K1.

[K1][C1][C2]

---

## 5. Inbound messages (ACC → client)

The type byte is at offset 0 of every datagram. Type numbers [K1][C1][C2]:

| Type | Name |
|---|---|
| 1 | REGISTRATION_RESULT |
| 2 | REALTIME_UPDATE |
| 3 | REALTIME_CAR_UPDATE |
| 4 | ENTRY_LIST |
| 5 | TRACK_DATA |
| 6 | ENTRY_LIST_CAR |
| 7 | BROADCASTING_EVENT |

Type 8 appears only in the framf0rt fork (`MASTERBROADCASTER_EVENT`), with no layout. Count it as `ignored`.

### 5.1 LapInfo (embedded structure, 13 + 4·k bytes)

Source: K1 `ReadLap`; C1, C2 identical; C3 decodes.

| Rel. offset | Type | Field | Units / notes |
|---|---|---|---|
| 0 | i32 | laptimeMs | ms. `0x7FFFFFFF` = none. In `currentLap` it is the running time of the lap in progress (C3: 10290 ms at spline 0.119) |
| 4 | u16 | carIndex | |
| 6 | u16 | driverIndex | |
| 8 | u8 | splitCount = k | 3 for a completed lap in all C3 samples, **0 for the current lap**. Splits arrive only when the lap completes [K2-p8, 2020-07-09; K2-p12, 2021-04-02] |
| 9 | i32[k] | splits | ms per **sector** (not cumulative), `0x7FFFFFFF` = none. Sums equal the lap time within 1 ms in 2 of the 3 C3 laps; one best lap is 50 ms off (unexplained). Middle splits are sometimes missing online [K2-p10, 2020] |
| 9+4k | u8 | isInvalid | >0 = invalid |
| 10+4k | u8 | isValidForBest | >0 = true. "Seems sometimes off" for qualifying [K2-p9, 2020] |
| 11+4k | u8 | isOutlap | >0 = out-lap |
| 12+4k | u8 | isInlap | >0 = in-lap. K1 maps (outlap, inlap) to LapType Outlap / Inlap / Regular |

K1 pads the split list to 3 entries with null. pitwall should keep the list as received and use `None` for
`0x7FFFFFFF`.

### 5.2 REGISTRATION_RESULT (type 1): 9 + n bytes

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | type | 1 |
| 1 | i32 | connectionId | Echo it in every request and in UNREGISTER |
| 5 | u8 | success | >0 = registered |
| 6 | u8 | writable | **0 = read-only** (K1: `isReadonly = byte == 0`) |
| 7 | string | errorMessage | Empty on clean success. C3: `Wrong command mode password, readonly access granted` (52 B; whole datagram 61 B) |

C1 reads `errorMessage` with .NET `BinaryReader.ReadString` (7-bit length), which is a bug. Follow K1.

### 5.3 REALTIME_UPDATE (type 2, session state): ≥ 48 bytes

Fixed part:

| Offset | Type | Field | Units / notes |
|---|---|---|---|
| 0 | u8 | type | 2 |
| 1 | u16 | eventIndex | |
| 3 | u16 | sessionIndex | Changes between sessions of one event. Treat any change of `(eventIndex, sessionIndex)` as a new session |
| 5 | u8 | sessionType | enum §6.1. C3: 10 (Race) |
| 6 | u8 | phase | enum §6.2. C3: 5 (Session) |
| 7 | f32 | sessionTime | **ms** elapsed. C3: 1 143 552.5 |
| 11 | f32 | sessionEndTime | **ms remaining**, despite the name. C3: 356 447.5. 1 143 552.5 + 356 447.5 = 1 500 000 = 25:00 exactly. Community: "SessionEndTime already contains the amount of time left" [K2-p5, 2020-04-27] |
| 15 | i32 | focusedCarIndex | The car the game camera follows. Can be −1, for example a spectator in an empty server [K2-p1, Minolin 2018-12-22] |
| 19 | string | activeCameraSet | C3: `Drivable` |

Then, in order:

| Type | Field | Units / notes |
|---|---|---|
| string | activeCamera | C3: `Cockpit` |
| string | currentHudPage | C3: `Basic HUD` |
| u8 | isReplayPlaying | >0 = replay. **Only if set, two extra fields follow:** |
| (f32) | replaySessionTime | present only when isReplayPlaying > 0 |
| (f32) | replayRemainingTime | present only when isReplayPlaying > 0 |
| f32 | timeOfDay | **seconds** since midnight. C3: 55 190.73 = 15:19:50. K1 parses it as ms, which is why users saw "always 00:00" [K2-p3/p5/p7, 2020]. Brado23's working fix treats it as seconds [K2-p9, 2020-07-28] |
| u8 | ambientTemp | °C, integer. C3: 30 |
| u8 | trackTemp | °C, integer. C3: 38 |
| u8 | clouds | ×0.1 in K1. **Always 0 since about v1.7 (2021), by design** (§10) |
| u8 | rainLevel | ×0.1 in K1. Always 0 since then |
| u8 | wetness | ×0.1 in K1. Always 0 since then |
| LapInfo | bestSessionLap | §5.1. C3: 93 145 ms by car 5 |

Size with no replay = 19 + Σ(2 + string bytes) for the three strings + 1 + 4 + 5 + (13 + 4k). C3: 84 B.

### 5.4 REALTIME_CAR_UPDATE (type 3, one car): 77 + 4·(k1+k2+k3) bytes

| Offset | Type | Field | Units / notes |
|---|---|---|---|
| 0 | u8 | type | 3 |
| 1 | u16 | carIndex | Key into the entry list. C3 indexes are 0..24, sent in non-sequential order |
| 3 | u16 | driverIndex | Changes on a driver swap [K1 comment; K2-p12, 2021-06-15] |
| 5 | u8 | driverCount | Compare with the entry list; on mismatch, request it again |
| 6 | u8 | gearRaw | **gear = raw − 2** (R = −1, N = 0, 1st = 1) [K1 comment]. So raw 1 = R, 2 = N, 3 = 1st. Raw 0 has no meaning: map it to `None`. C3: raw 3 at 120 km/h. Unverified on current builds: "always returns 0" in the test client [K2-p14, 2023-04-30] |
| 7 | f32 | worldPosX | **v1.10.1 and later:** world coordinate, metres assumed (C3: −107.14). **Before:** an orientation angle (§10) |
| 11 | f32 | worldPosY | Same caveat. C3: 358.75. Which shared-memory axis this equals (y or z) is unverified (V-4) |
| 15 | f32 | yaw | Radians assumed. C3: 2.537 (within ±π). Zero heading and sign are unverified |
| 19 | u8 | carLocation | enum §6.3. C3: 1 (Track) |
| 20 | u16 | kmh | km/h, **integer** resolution. C3: 120 |
| 22 | u16 | position | "official P/Q/R position (1 based)" [K1]. Not real-time; changes at timing lines [K2-p3, 2020] |
| 24 | u16 | cupPosition | Position in cup. Equal to overall position before v1.10.1 [K2-p13, 2022; K3] |
| 26 | u16 | trackPosition | "position on track (1 based)" per K1, but **always 0** [K1b comment; K2-p4/p7, 2020; C3 2026 = 0] |
| 28 | f32 | splinePosition | Lap fraction 0..1. Jumps from about 1 to 0 at the line [K2-p8, 2020-07-12]. C3: 0.11872 |
| 32 | u16 | laps | **Completed** laps. Inferred from C3: laps = 12, current lap at 10.29 s, session 1 143.6 s ≈ 12 × 94 s + 10.3 s + start. Unverified |
| 34 | i32 | delta | ms, "Realtime delta to best session lap" [K1]. C3: −5 |
| 38 | LapInfo | bestSessionLap | This car's best in the session |
| 38+13+4k1 | LapInfo | lastLap | |
| … | LapInfo | currentLap | running time; k3 = 0 |

C3: 101 B = 38 + 25 + 25 + 13.

C2 decodes offsets 7/11/15 as yaw/pitch/roll, with the comment "falsely documented as posX/posY/yaw". It added that
comment on 2021-09-02, which is pre-v1.10.1 behaviour. C1 and K1 decode them as position. The 2026 recording holds
values that cannot be angles (−107, 359). That supports the K3 fix.

### 5.5 ENTRY_LIST (type 4): 7 + 2·n bytes

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | type | 4 |
| 1 | i32 | connectionId | |
| 5 | u16 | carCount = n | **u16**, unlike other lists |
| 7 | u16[n] | carIndex | Replaces the whole entry list. C3: n = 25 (57 B) |

Cars that leave a server are not removed from clients' lists unless the client prunes against the new list
[K2-p5/p6/p7, 2020].

### 5.6 ENTRY_LIST_CAR (type 6, one car): 15 + |team| + Σ(9 + |first| + |last| + |short|)

| Rel. offset | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | type | 6 (no connectionId) |
| 1 | u16 | carIndex | Ignore unless it is in the last ENTRY_LIST [K1] |
| 3 | u8 | carModelType | ACC car model id. C3: 1. Kunos publishes the list with the dedicated server (not fetched here; C2 `CarModel.java` is an MIT cross-check) |
| 4 | string | teamName | Empty online, populated offline [K2-p7, 2020; K2-p13, 2022] |
| … | i32 | raceNumber | C3: 4 |
| … | u8 | cupCategory | K1 comment: 0 Overall/Pro, 1 ProAm, 2 Am, 3 Silver, 4 National. C1's enum orders these alphabetically; that is wrong, follow K1 |
| … | u8 | currentDriverIndex | Reported as not updated on a swap; use `driverIndex` from §5.4 [K2-p12, 2021] |
| … | u16 | carNationality | enum §6.5 |
| … | u8 | driverCount = d | |
| per driver | string, string, string | firstName, lastName, shortName | **Personal data** (§13) |
| per driver | u8 | driverCategory | 0 Bronze, 1 Silver, 2 Gold, 3 Platinum, 255 Error |
| per driver | u16 | driverNationality | Added in ACC 1.3.11/1.3.12 (2020) [K2-p4/p6]. K1's comment reads "new in 1.13.11" |

C3: 48 B. Crew Chief reads both nationality fields as i16; the bytes are the same.

### 5.7 TRACK_DATA (type 5): variable (C3: 671 B)

| Rel. offset | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | type | 5 |
| 1 | i32 | connectionId | |
| 5 | string | trackName | Display name. C3: `Red Bull Ring` |
| … | i32 | trackId | C3: 26. Whether ids stay stable across ACC versions is unverified |
| … | i32 | trackMeters | Integer metres. C3: 4318. K1 stores it as float and sets ≤ 0 to −1 |
| … | u8 | cameraSetCount | then per set: string name, u8 count, string[count] cameras |
| … | u8 | hudPageCount | then string[count]. C3: Blank, Basic HUD, Help, TimeTable, Broadcasting, TrackMap |

The 24h Nürburgring sent no TRACK_DATA before v1.10.1 [K2-p14, 2024-04-01; K3].

Correction: `track-knowledge-sources.md` L0b-ACC calls the C3 Red Bull Ring check a "101-byte sample". The 101-byte
datagram is REALTIME_CAR_UPDATE. TRACK_DATA is 671 B. The decoded values (id 26, 4318 m) are right.

### 5.8 BROADCASTING_EVENT (type 7): 12 + n bytes

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | type | 7 |
| 1 | u8 | eventType | enum §6.4 |
| 2 | string | msg | C3 (LapCompleted): `01:36.745`. Accident messages carry garbage car ids such as `#vs. #-1271002704` [K2-p3/p5/p10, 2019-2020] |
| … | i32 | timeMs | Semantics unverified. C3: 1 204 467, which is 60.9 s ahead of the sessionTime received 6.8 s earlier |
| … | i32 | carId | car index (C3: 6) |

C3: 21 B.

---

## 6. Enumerations

Source: K1 `BroadcastingEnums.cs`. C1 and C2 agree except where noted.

### 6.1 RaceSessionType (u8)

| Value | Name | pitwall `SessionType` |
|---|---|---|
| 0 | Practice | practice |
| 4 | Qualifying | qualifying |
| 9 | Superpole | qualifying (`session_type_raw` = "superpole") |
| 10 | Race | race |
| 11 | Hotlap | time_trial |
| 12 | Hotstint | time_trial (`raw` = "hotstint") |
| 13 | HotlapSuperpole | time_trial |
| 14 | Replay | unknown, and flag the session as replay |
| other | — | unknown. C1 adds −1/NONE; C2 uses 255 |

### 6.2 SessionPhase (u8)

0 NONE, 1 Starting, 2 PreFormation, 3 FormationLap, 4 PreSession, 5 Session, 6 SessionOver, 7 PostSession,
8 ResultUI.

### 6.3 CarLocation (u8)

| Value | Name | pitwall `pit_status` |
|---|---|---|
| 0 | NONE | `None` |
| 1 | Track | 0 |
| 2 | Pitlane | 1 |
| 3 | PitEntry | 1 |
| 4 | PitExit | 1 |

There is no "in pit box" state, so `pit_status` = 2 is never produced.

### 6.4 BroadcastingCarEventType (u8)

0 None, 1 GreenFlag, 2 SessionOver, 3 PenaltyCommMsg, 4 Accident, 5 LapCompleted, 6 BestSessionLap,
7 BestPersonalLap.

Community reports, all from 2020:
- Only 5, 6 and 7 arrived in some sessions [K2-p5].
- GreenFlag did not fire [K2-p8].
- Penalties are reported only when cleared [K2-p5, K2-p12].
- Accidents appear only online [K2-p10].

### 6.5 Nationality (u16)

- K1 lists 0 Any … 77 Wales.
- Kunos added 78 (Iran) to 84 (Madagascar) in 2021 [K2-p11, Minolin 2021-03-17].
- Chile = 82 [K2-p10].

pitwall does not need nationality (§13).

### 6.6 LapType (derived, not on the wire)

0 ERROR, 1 Outlap, 2 Regular, 3 Inlap. This comes from the two flag bytes in LapInfo.

---

## 7. Identifying and validating packets

There is **no magic, no length field, no checksum, and no version field in any inbound message.** The protocol
version is sent only by the client in REGISTER. Validation therefore rests on the socket and on structure:

1. **Source.** Accept datagrams only on the client's connected socket, from the registered `<pc-ip>:<port>` (the OS
   drops others).
   - Replays from `.pwcap` skip this check, so the adapter's `can_decode` must be structural only.
2. **Type byte** must be in {1..7}. Type 8 counts as `ignored`; anything else is `rejected`.
3. **Bounds-checked parse.**
   - Every field must fit in the datagram.
   - Every string length must be ≤ the remaining bytes, and its bytes must be valid UTF-8 (decode with
     `errors="replace"`).
   - On any overrun, raise `PacketRejected`.
4. **Trailing bytes.** K1 ignores them. pitwall should accept them, count them (`DecodeStats.by_type["trailing"]`)
   and still decode. All C3 vectors consume the datagram exactly.
5. **Plausibility.** These bounds are pitwall's own choices; reject or blank any field that fails them:

   | Field | Bound |
   |---|---|
   | splitCount | ≤ 16 |
   | ENTRY_LIST n | ≤ 128 |
   | cameraSet/HUD counts | free |
   | gearRaw | 1..12, else `None` |
   | carLocation | 0..4, else `None` |
   | kmh | ≤ 450 |
   | splinePosition | finite and in [−0.01, 1.01], else `None` |
   | sessionType, phase | in their enums, else unknown |
   | floats | `math.isfinite` |
6. **World-position sanity (pre-v1.10.1 builds).** There is no game version on the wire. Mark the session's world
   position as orientation-like and emit `None` for `pos_*` and `yaw_rad` in this case:
   - over the first 10 s of car updates in a session, every |worldPosX| and |worldPosY| across all cars is ≤ 3.2
     (π + margin);
   - and the cars' `splinePosition` values span more than 0.1.

   Record the decision in `SessionInfo.extra["acc_world_pos"]` = `"ok" | "orientation_like" | "unknown"`.

---

## 8. Session, car and player identity

- **Session boundary:**
  - a change of `(eventIndex, sessionIndex)`;
  - a `sessionType` change;
  - a TRACK_DATA with another `trackName`;
  - or re-registration after a timeout.

  The protocol has no session UID. Leave `SessionInfo.session_uid` `None` and put `eventIndex` and `sessionIndex` in
  `SessionInfo.extra`, so `core/session.py` segments on them. The adapter must not invent a UID.
- **Track identity:**
  - `trackName` is the display string ("Red Bull Ring");
  - `trackId` is an int (26).

  Proposed `SessionInfo.track_id = "acc:" + trackName`, with `trackId` in `extra`. Use the pitwall-authored 25-track
  crosswalk in track-knowledge Phase 6 to map names to seeds. Whether `trackId` is stable across ACC versions is
  unverified.
- **Player car.** No field says which car is the user's.
  - Heuristic: player = `focusedCarIndex` while:
    - `isReplayPlaying` = 0;
    - `activeCameraSet` ≠ a TV/broadcast set ("Drivable" in C3, unverified list);
    - the user has not changed focus (pitwall never sends CHANGE_FOCUS).
  - Confidence: Unverified (V9 in track-knowledge; V-5 here).
  - The Connect page should let the user confirm their race number. Keep the matching car index from ENTRY_LIST_CAR
    after that.
- **Other cars.** Key them by `carIndex`. Car class comes from `carModelType`, which feeds the class-aware decel
  thresholds of L0b-ACC.

---

## 9. Update rates and timing

| Item | Value | Status |
|---|---|---|
| Interval | Chosen by the client in REGISTER (`msRealtimeUpdateInterval`, ms). Kunos test client default **250** [K1a]; 100 "everything works fine" [K2-p6, 2020-05-11]; C3 logs 1000 | Kunos-sample / Community |
| Per interval | 1 × REALTIME_UPDATE + 1 × REALTIME_CAR_UPDATE per car (inferred from K1) | Unverified (V-3) |
| Minimum interval | Unknown. Plan to test 50, 100 and 250 ms (track-knowledge V9) | Unverified |
| Timestamps | **REALTIME_CAR_UPDATE has no time field.** Use the host receive time (`t_recv_ns`). `session_time_s` comes from the latest REALTIME_UPDATE, so it can be up to one interval stale | K1 |
| Ordering | Car updates arrive out of spline order at 100, 250 and 2000 ms [K2-p9, 2020-07-15]. Spline values occasionally step backwards at small intervals [K2-p8, 2020-07-12]. Online positions lag [K2-p10, 2020-12-14] | Community |
| Latency vs shared memory | Values match shared memory; "Only the sampling rate differs" [K2-p14, 2024-03-24] | Community |

At 100 ms with 25 cars the stream is about 260 datagrams/s of 77–113 B, which is trivial for `UdpListener`-style
ingest.

---

## 10. Version history of known behaviour

| When | Change | Source |
|---|---|---|
| 0.5 → 0.6 (2019-03) | Broadcasting UDP interface disabled for a while | K2-p2 (quoting Minolin) |
| 1.0 (2019-05) | Old clients rejected: "Your broadcasting control app is outdated" | K2-p2 |
| 1.3.11 / 1.3.12 (2020) | Car and driver nationality added to ENTRY_LIST_CAR | K2-p4, K2-p6 |
| 2020 builds | TimeOfDay "always 00:00" in K1 (a units bug in K1); WorldPosX/Y and TrackPosition "always 0"; accident ids garbage | K2-p3, K2-p4, K2-p5, K2-p7 |
| about 1.7.x (2021-03) | **Clouds, RainLevel and Wetness zeroed by design**: "It's removed by design … weather is no longer quantified" | K2-p11 (pankykapus, KS Dev Team, 2021-03-20); K2-p12, K2-p13 |
| 2021-09 → 2024-03 | World X/Y/yaw carry orientation angles in radians; the exact order is disputed: C2 says yaw/pitch/roll, K2-p13 2021-11-10 says the fields are yaw/roll/pitch | C2 commit `8d834d37`, K2-p13, K2-p14 |
| **v1.10.1 (2024-04-04)** | "Broadcasting API: fixed world position data." "Broadcasting API: fixed position in cup." "Fixed broadcasting API not sending N24 track_info." | **K3 (Kunos-staff)**; S1 secondary |
| 2026-03-14 | Recorded stream: world X/Y in metre range, `trackPosition` 0, weather bytes 0, temperatures present | C3 (3P-recorded) |

Correction: `track-knowledge-sources.md` says the v1.10.1 primary post "was not located". It is K3.

---

## 11. Consoles

- **ACC on PS4, PS5, Xbox One and Xbox Series:** **no interface.**
  - There is no `broadcasting.json` to edit, no UDP setting, and no SDK folder.
  - The Kunos API attaches to the "local ACC client" on the PC [K2-p1, Minolin 2018-12-14].
  - No report of console use exists in any source read for this file. [P1] §3.3 and `game-compatibility.md` hold
    the console evidence: NLR's console motion list, and GTPlanet / SimHub user reports.
  - Status: **Unsupported**.
- **Consequence for this user (PS5 rig).** This family helps only if ACC runs on a Windows PC on the same LAN. Two
  cases:
  - The user drives on that PC: L0b-ACC field model, lap timing and race context.
  - The PC is a spectator client watching an online session that includes the user, with the Mac registering to that
    PC. The user's own console would still produce nothing.
- **Exists on PC only.** Evidence of real PC use: the C3 recording (2026-03); C2 is used "almost daily" by league
  stewards (C2 README); 15 forum pages of PC client authors [K2].

---

## 12. Assetto Corsa EVO: unverified lead

### 12.1 What the lead is

devology's MIT SDK [C1] added `SimRacingSdk.Ace.Udp` in commit `4531315fa2` (2026-07-27), titled "Added port of ACC UDP
protocol to ACE UDP".

- `AcePathProvider` points at `broadcasting.json` under `Config` in `Documents\ACE`. When that folder has fewer
  entries, it uses `%USERPROFILE%\Saved Games\ACE` instead.
- The game process name is `AssettoCorsaEVO`.

### 12.2 What the evidence actually shows

- **A mechanical copy.**
  - A diff of every file in `Ace.Udp` against `Acc.Udp` (with the namespace renamed) shows only renames and BOM
    changes.
  - The message handler, reader, enums and protocol version 4 are byte-for-byte the same logic.
  - There is no AC EVO-specific field, no captured packet and no test.
- **The author's own words.**
  - Commit `1f8b9ef708` (2026-07-29): "Whether Evo keeps broadcasting.json under Config in the same shape as Acc is
    still unverified."
  - The `BroadcastingSettings` model said "Shape assumed identical to Acc's broadcasting.json - unverified against a
    real Ace Evo install."
  - Commit `da5cac0798` (2026-09-07, "Cleaned up non-critical comments") deleted both comments. It changed no code
    and recorded no verification.
- **What the same repo did verify for AC EVO.** Only file locations, from commits `4a07166291`, `1f8b9ef708` and
  `93cebb58e8`:
  - the `Documents\ACE` and `Saved Games\ACE` data folders;
  - `local.driverdescriptor.json`;
  - the `Car Setups` folder.
- **Kunos and 505 Games sources.**
  - The AC EVO changelogs 0.6 (2026-04-15), 0.8, 0.8.1, 0.9 and 0.9.1 (2026-09-01) mention shared memory, MoTeC
    telemetry and TrackIR. They say **nothing** about UDP, a broadcasting API or `broadcasting.json` [O1].
  - 0.9's only "broadcast" is "Fixed TV camera jitter during replays/broadcast footage".
  - Kunos's AC EVO shared-memory document (changelog to 2026-04-28) does not mention UDP [O2].
  - 0.5 and 0.7 were not re-checked here.
  - Steam users were still asking for "UDP telemetry data out" in 2025-01 (`game-compatibility.md` [F12]).
- **Verdict: Unknown, and probably not present.** Do not implement an AC EVO path or claim a capability.

### 12.3 Probe to settle it (owner's own PC only)

1. On a PC with AC EVO installed, look for `Config\broadcasting.json` under `Documents\ACE` and under
   `Saved Games\ACE`.
2. If the file exists, set a port, start a session, and check whether `AssettoCorsaEVO.exe` listens on it:
   `Get-NetUDPEndpoint -OwningProcess (Get-Process AssettoCorsaEVO).Id`.
3. From the Mac, send the §4.1 REGISTER with the file's password. A REGISTRATION_RESULT (type 1, 9+ B) is the first
   evidence the feature exists. Record it with `pitwall` capture, as tier "recorded".
4. If it answers, diff every message against §5 before reusing the ACC decoder. Expect different track and car ids.

Correction for `track-knowledge-sources.md` §6.1 row G: AC EVO shared memory has `npos` and `track_length_m`
[O2 field table], as `game-compatibility.md` already notes. Lap distance for AC EVO comes from the shared-memory relay,
not from this family.

---

## 13. Licence and legal position

- **Kunos SDK sample (K1).**
  - No licence file. The readme says the library "can be directly used in your own .Net application".
  - That permits using Kunos's .NET assembly as-is. It is not a licence to copy the code into another language.
- **ACC EULA [K4].**
  - The licensed "Software Product" includes "Any and all contents, components, attachments, software, media, and
    code with which this Agreement is provided" (§4). The SDK folder ships with the game, so it is covered.
  - §5A grants a "personal, revocable End-User license".
  - §5C(4) forbids "derivative works based on the Software Product or any accompanying materials".
  - §6C forbids "extract information, reverse engineer, disassemble, decompile".
  - It says nothing about UDP, APIs or broadcasting. If the SDK now ships with the Dedicated Server tool, that
    tool's terms were not checked.
- **What pitwall may do (engineering position, not legal advice).**
  - Implement the wire protocol **clean-room in Python** from this spec (facts: byte order, field order, types).
  - Talk to the user's own game at runtime.
  - Never copy Kunos C#, nor C1, C2 or K1b code.
  - The MIT licences of C1 and C2 would allow copying with notice, but C1 is visibly derived from K1. pitwall
    therefore writes its own code and cites C1 and C2 as cross-checks only.
  - C3 has no licence: its recorded bytes are used as **facts for verification only** and are not vendored into
    `tests/fixtures/`.
- **Counsel first** (track-knowledge §7.6 item 5): commercial runtime use of the broadcasting interface, and shipping
  ACC-derived tables. Until then, "personal use, clean-room" is the boundary.
- **Personal data.** ENTRY_LIST_CAR carries real names, short names, nationality and category of other players in
  online sessions.
  - The adapter should **not emit names** by default. Keep `carIndex`, `raceNumber`, `carModelType` and
    `cupCategory`.
  - `.pwcap` files of online sessions contain the names in the raw payloads, and must never be redistributed.
- **Credentials.** REGISTER carries `connectionPassword` in plain text on the LAN.
  - pitwall stores it like other connection settings: local only, not logged, and not written into `.pwcap`, which
    records inbound datagrams only.
  - Tell the user to scope the Windows firewall rule to the Mac's IP.

---

## 14. Test vectors and sample-packet guidance

### 14.1 Evidence tiers (CLAUDE.md)

- **synthetic:**
  - bytes built by a pitwall encoder from §4–§5;
  - flagged `SYNTHETIC_SESSION_UID`;
  - track ids prefixed `synthetic:`;
  - `pytest -m synthetic`.
- **recorded:**
  - pitwall's own `.pwcap` from ACC on a Windows PC (V-1);
  - goes in `tests/fixtures/recorded/acc_pc_<track>_<session>.pwcap`;
  - online sessions only with names scrubbed, or offline AI sessions only.
- **third-party recorded (C3):** cross-check only. Not a pitwall evidence tier, and never shipped as a fixture.

### 14.2 Third-party recorded cross-check (C3, ACC build not stated)

Six datagrams come from the CSV, with receipt timestamps of 2026-03-14. REGISTRATION_RESULT comes from the repo's
Sample Run log and has the same connection id 18. A clean-room decoder written from §5 (scratchpad, not repo code)
consumed exactly the datagram length for all seven:

| Type | Bytes | Decoded highlights |
|---|---|---|
| 1 REGISTRATION_RESULT | 61 | id 18, success 1, writable 0, "Wrong command mode password, readonly access granted" |
| 2 REALTIME_UPDATE | 84 | Race, Session phase, t = 1 143 552.5 ms, remaining 356 447.5 ms, focused 13, Drivable/Cockpit/Basic HUD, ToD 55 190.7 s, 30/38 °C, weather 0/0/0, best 93 145 ms (car 5; splits 23 505 / 40 892 / 28 747) |
| 3 REALTIME_CAR_UPDATE | 101 | car 0, gearRaw 3, X −107.14, Y 358.75, yaw 2.537, Track, 120 km/h, P1, cup P1, trackPos 0, spline 0.118721, laps 12, delta −5 ms; best 93 695, last 94 272 (23 647 / 41 300 / 29 325), current 10 290 (0 splits) |
| 4 ENTRY_LIST | 57 | id 18, 25 cars |
| 5 TRACK_DATA | 671 | id 18, "Red Bull Ring", trackId 26, 4318 m, 7 camera sets, 6 HUD pages |
| 6 ENTRY_LIST_CAR | 48 | car 0, model 1, team "Black Falcon", #4, cup 0, 1 driver (category 1) |
| 7 BROADCASTING_EVENT | 21 | LapCompleted, "01:36.745", timeMs 1 204 467, car 6 |

For decoder cross-checking, the two shortest are reproduced here as game-output facts.
- REALTIME_CAR_UPDATE (101 B):
  `030000000001031948d6c2675fb34317642240017800010001000000f623f33d0c00fbffffffff6d01000000000003fe5b0000c8a0000007710000000100004070010000000000035f5c000054a100008d7200000001000032280000000000000000010000`
- BROADCASTING_EVENT (21 B): `0705090030313a33362e373435f360120006000000`

### 14.3 Synthetic vectors pitwall should build (encoder round-trip and edge cases)

Each is built by pitwall's own encoder and decoded back. Assert every field and that bytes consumed equal the length.

1. REGISTER: the §4.1 example bytes exactly. UNREGISTER, REQUEST_ENTRY_LIST and REQUEST_TRACK_DATA: the §4.2–§4.3
   examples.
2. REALTIME_UPDATE with `isReplayPlaying` = 1: the 8 extra bytes. Without it: no extra bytes.
3. LapInfo with k = 0, 1, 3 and 0x7FFFFFFF in the lap time and splits (→ `None`). Invalid, out-lap and in-lap flags.
4. REALTIME_CAR_UPDATE with:
   - gearRaw 0 (→ `None`), 1 (R), 2 (N), 3 (1st);
   - every carLocation value;
   - spline 0.9995 → 0.0004 wrap with `laps` +1, both in the same burst and one burst apart;
   - negative delta.
5. ENTRY_LIST with n = 0 and n = 60. ENTRY_LIST_CAR with 3 drivers, non-ASCII UTF-8 names (`Schüngel`), an empty team.
6. TRACK_DATA with 0 camera sets and with many sets.
7. **Truncation:** every proper prefix of each vector must raise `PacketRejected`. Trailing junk must decode and be
   counted.
8. Unknown type 0, type 8 (counted as `ignored`) and type 255 (rejected).
9. Pre-v1.10.1 orientation-like positions (all |x|, |y| ≤ π over 10 s): world position suppressed (§7).
10. **Protocol-table test:** parse the tables in §4–§5 of this file and compare them with the decoder's layout
    constants, as `tests/unit/test_f1_protocol.py` and `test_ac.py` do.

### 14.4 Capture guidance (V-1, on the user's or a friend's Windows PC)

1. Set `updListenerPort` 9000 and a connection password in `broadcasting.json`. Allow inbound UDP 9000 in the
   Windows firewall from the Mac's IP only.
2. Run offline sessions:
   - a practice session with AI, then a race with AI, at Monza, Spa and Donington (track-knowledge V9);
   - one Hotlap session;
   - pit in and out at least once;
   - leave a replay running for 30 s.
3. Capture at intervals of 250, 100 and 50 ms (separate files). In each capture's description, record the ACC version
   from the main menu, since the stream has none.
4. Do not record online sessions with other people unless names are scrubbed before the file leaves the machine.

---

## 15. Mapping to pitwall's unified model

### 15.1 CarFrame (player car only; one per REALTIME_CAR_UPDATE for the player index)

`game` = `Game.ACC`, platform PC.

| CarFrame field | Source | Transform | Status |
|---|---|---|---|
| `t_recv_ns` | host | receipt time (no game timestamp) | — |
| `session_time_s` | REALTIME_UPDATE.sessionTime | ÷1000, from the latest session update (stale ≤ 1 interval) | Kunos-sample |
| `speed_kph` | kmh | as-is (integer resolution) | Kunos-sample, 3P-recorded |
| `throttle`, `brake`, `steering`, `clutch` | — | `None` | **not provided** |
| `gear` | gearRaw | raw − 2; raw 0 → `None` | Kunos-sample; current-build mapping unverified (V-6) |
| `rpm`, `max_rpm`, DRS/ERS fields | — | `None` | not provided |
| `pos_x_m`, `pos_y_m` | worldPosX, worldPosY | as-is; `None` when §7 step 6 says orientation-like | v1.10.1+ (K3); axes vs shared memory unverified (V-4). `AdapterInfo.ground_plane = ("pos_x_m", "pos_y_m")` until V-4 says otherwise |
| `pos_z_m`, velocities, g-forces, pitch, roll | — | `None` | not provided |
| `yaw_rad` | yaw | as-is; same suppression rule | radians assumed (V-4) |
| `lap_number` | laps | **laps + 1** (1-based current lap) | inferred from C3 (V-7) |
| `lap_distance_m` | splinePosition × trackMeters | derived from two game values | scale and offset caveats: `trackMeters` is an integer official length, not the measured spline length; the offset of spline 0 from the timing line is unverified (track-knowledge §6.1 I, V9) |
| `total_distance_m` | — | `None` (or laps × trackMeters + lap distance in analysis, not in the adapter) | — |
| `current_lap_time_ms` | currentLap.laptimeMs | 0x7FFFFFFF → `None` | 3P-recorded |
| `last_lap_time_ms` | lastLap.laptimeMs | same | 3P-recorded |
| `sector` | — | `None`. No live sector index; splits arrive only at lap end | not provided |
| `lap_invalid` | currentLap.isInvalid | >0 | Kunos-sample |
| `pit_status` | carLocation | §6.3 | Kunos-sample |
| `race_position` | position | as-is (not real-time; updates at timing lines) | Kunos-sample |
| tyre, brake-temperature, wear, compound, fuel, brake bias, TC/ABS fields | — | `None` | not provided (shared-memory relay only) |

### 15.2 SessionInfo

| Field | Source |
|---|---|
| `track_name`, `track_length_m` | TRACK_DATA trackName, trackMeters |
| `track_id` | `"acc:" + trackName`; `extra["acc_track_id"]` = trackId |
| `session_type` / `session_type_raw` | §6.1 |
| `session_time_left_s` | sessionEndTime ÷ 1000 (remaining; §5.3) |
| `weather.air_temp_c`, `weather.track_temp_c` | ambientTemp, trackTemp (integer °C) |
| `weather.condition`, `weather.rain_percentage` | **`None` always.** The bytes are 0 by design, so 0 must not become "clear / 0 %" |
| `car_id` | `"acc:model:" + carModelType` of the player's ENTRY_LIST_CAR |
| `extra` | `eventIndex`, `sessionIndex`, `phase`, `focusedCarIndex`, `isReplayPlaying`, `acc_world_pos`, `registration_writable` |

`total_laps`, `pit_speed_limit_kph`, `safety_car_status` and `track_zones` are `None`. Sector lines come from L0a-like
derivation or from seeds in the track-knowledge layer, not from the adapter.

### 15.3 GameEvent and LapCompletion

- **Player lap end.** A `LapCompletion` when the player's `laps` increments, using the *new* `lastLap`:
  - `lap_number` = laps (the lap just completed);
  - `lap_time_ms` = lastLap.laptimeMs;
  - `sector_times_ms` = lastLap.splits;
  - `valid` = not isInvalid.

  The LapCompleted event (type 5) for the player's car index is a cross-check only.
- **Event mapping:**

  | BROADCASTING_EVENT | `EventKind` |
  |---|---|
  | BestSessionLap | FASTEST_LAP |
  | SessionOver | SESSION_ENDED |
  | PenaltyCommMsg | PENALTY (fires on clearance only) |
  | Accident | COLLISION (online only; message ids unreliable) |
  | GreenFlag | LIGHTS_OUT (reported not to fire) |
  | BestPersonalLap | OTHER |

  `code` = the raw type number; `payload` = {carId, msg, timeMs}.
- **Other cars.** Their REALTIME_CAR_UPDATEs are **not** CarFrames. They feed the L0b-ACC field model as per-car
  samples:
  - `carIndex`, `t_recv_ns`, spline × trackMeters, kmh, world X/Y, carLocation, laps, LapInfo validity;
  - car class from `carModelType`.

  `model/telemetry.py` has no field-sample type yet. Define it once for the F1 L0b (track-knowledge Phase 3) and
  reuse it here.

### 15.4 Corrections to `forza-ac-acc-iracing.md` §3.2

- UNREGISTER: K1 sends no connection id; send one anyway (§4.3).
- `timeOfDay` is in **seconds**, not ms.
- Clouds, rain and wetness are always 0 since 2021.
- `sessionEndTime` is time remaining.
- World X/Y were orientation angles before v1.10.1.
- `trackPosition` is always 0.
- ENTRY_LIST's count is u16.
- ENTRY_LIST_CAR also carries `currentDriverIndex` and two u16 nationality fields.

---

## 16. Implementation notes for pitwall

Model it on `src/pitwall/ingest/ac_client.py`, the same pattern as the AC handshake client.

- **Modules:**
  - `src/pitwall/adapters/acc/packets.py`: pure readers, layout constants and the §7 validation;
  - `src/pitwall/adapters/acc/adapter.py`: `GameAdapter` that emits CarFrame, SessionInfo, GameEvent, LapCompletion
    and field samples;
  - `src/pitwall/ingest/acc_client.py`: the client;
  - `src/pitwall/sim/acc_stream.py`: a synthetic stream plus a loopback fake ACC for tests.
- **Socket.** One UDP socket on an ephemeral local port, `connect()`-ed to `(pc_ip, port)`.
  - `ConnectionRefusedError` (ICMP port unreachable) → state `refused`. Likely causes: ACC is not running, the port
    is wrong, or the firewall blocks it.
  - Set the receive buffer the same way `RCVBUF_BYTES` is set for the other listeners.
- **States:** `idle` → `registering` → `registered` → `streaming`.
  - `idle`: no PC IP.
  - `registering`: REGISTER every 2 s, never more than 1 per s.
  - `registered`: the result has success > 0. Send REQUEST_ENTRY_LIST and REQUEST_TRACK_DATA. If TRACK_DATA does not
    arrive within 2 s, re-request it up to 3 times.
  - `streaming`: REALTIME_UPDATE is arriving.
  - Success = 0 → state `rejected`, showing `errorMessage` (for example a wrong password). Back off 10 s.
  - If nothing arrives for 3 s (stream timeout):
    1. send UNREGISTER(connectionId);
    2. close the socket;
    3. register again from a fresh ephemeral port.
  - Session idle timeout: the same 60 s `on_idle` semantics as `UdpListener` and `AcClient`.
- **Entry list.** Re-request at most once per second on an unknown car or a driver-count mismatch. Prune cars that are
  absent from the latest ENTRY_LIST.
- **Never send commands** (types 49–52, 60). Read-only access is fine, so `commandPassword` stays empty unless the user
  supplies one.
- **Never block ingest.** Decode on the client thread with O(1) state updates. Field-model accumulation goes to the
  analysis worker, as for F1.
- **Capture.**
  - `.pwcap` with `source` = "acc_broadcast" and `game_hint` = "acc";
  - `extra` = {pc_ip, port, interval_ms, acc_version (user-entered)}.
  - Outbound datagrams are not recorded, so replays need no handshake.
- **Connect page guide:**
  1. edit `broadcasting.json` (port 9000, a password);
  2. restart ACC (unverified whether this is needed, but harmless);
  3. allow UDP 9000 inbound from the Mac in Windows Defender Firewall;
  4. enter the PC's IP, port and password in pitwall;
  5. start a session.
- **`capabilities.py`.**
  - The ACC PC row stays **PARTIAL**, and its note should say "Broadcasting: all-car timing/position, no inputs".
  - Field support levels are `COMMUNITY_DOCUMENTED` until a pitwall recorded capture exists, then `RECORDED_VALIDATED`.
  - Never upgrade the console row.
  - Add no AC EVO row from this family.

---

## 17. Open questions (to settle with a Windows-PC capture)

| ID | Question | How |
|---|---|---|
| V-1 | First pitwall recorded capture (all message types) on a current build | §14.4 |
| V-2 | REGISTRATION_RESULT for a wrong *connection* password and for protocol version ≠ 4 | Register deliberately wrong; record the replies |
| V-3 | Burst structure per interval; minimum usable interval; datagram rate at 50 ms | Timestamps in the capture |
| V-4 | Which shared-memory axes worldPosX/Y equal; yaw zero and sign; units | Run the shared-memory relay alongside; or compare with Race Control track maps |
| V-5 | Does `focusedCarIndex` equal the player while driving? Does it change when a TV camera is selected? | Offline race; switch cameras |
| V-6 | gearRaw mapping on the current build (raw 3 = 1st?) | Drive through the gears in a known car |
| V-7 | `laps` = completed laps, and the order of the `laps` increment vs the spline wrap | Line crossings in the capture |
| V-8 | `timeMs` in BROADCASTING_EVENT: session time or something else | Compare with REALTIME_UPDATE.sessionTime |
| V-9 | Can a client register mid-session and after the green light? Does a registration survive a session change? Can several clients connect at once (pitwall plus SimHub)? | Scripted re-registration tests |
| V-10 | Hotlap / Hotstint / Superpole: is only the player's car sent? | One session each |
| V-11 | `broadcasting.json` default contents and encoding; is a restart needed after an edit? | Inspect a fresh install |
| V-12 | AC EVO: does any broadcasting listener exist? | §12.3 |

Already tracked in track-knowledge V9 (offsets, scale and latency for the field model): spline-0 offset, `trackMeters`
vs integrated lap length, km/h-vs-spline latency.

---

## 18. Source URLs

**Kunos / 505 (vendor)**
- [K1] Kunos SDK (in the game install, `sdk\broadcasting\Sources\`; not on the web). Located by K2-p1 (2018-12-12) and
  K2-p6 (2020-05-14). K2-p15 (2025-04-09) points to the Dedicated Server tool.
- [K1a] https://github.com/framf0rt/ACCBroadcastingTool-Modified/blob/da960ec6551399b69f1e56542e18977a6bca06bd/ksBroadcastingNetwork/BroadcastingNetworkProtocol.cs
- https://github.com/framf0rt/ACCBroadcastingTool-Modified/blob/da960ec6551399b69f1e56542e18977a6bca06bd/ksBroadcastingTestClient/ClientConnections/ClientPanelViewModel.cs
  (defaults 127.0.0.1 / 9000 / "asd" / 250 ms)
- https://github.com/framf0rt/ACCBroadcastingTool-Modified/blob/master/KunosReadme/readme.txt (Kunos readme)
- [K1b] https://gitlab.com/mr_belowski/CrewChiefV4/-/tree/master/CrewChiefV4/ACC/ksBroadcastingNetwork
- [K2] https://www.assettocorsa.net/forum/index.php?threads/lets-talk-about-broadcasting-programmers-thread.53826/
  (pages cited as `/page-N`, for example
  https://www.assettocorsa.net/forum/index.php?threads/lets-talk-about-broadcasting-programmers-thread.53826/page-11)
- [K3] https://www.assettocorsa.net/forum/index.php?threads/assetto-corsa-competizione-v1-10-1-hotfix-update-out-now.73634/
  (2024-04-04)
- [K4] https://store.steampowered.com/eula/805550_eula_0
- [O1] https://support.505games.com/support/solutions/articles/150000225211-assetto-corsa-evo-0-6-changelog-15-apr-2026 ;
  https://support.505games.com/support/solutions/articles/150000229709-assetto-corsa-evo-0-8-patch-notes ;
  https://support.505games.com/support/solutions/articles/150000230407-assetto-corsa-evo-patch-notes-0-8-1 ;
  https://support.505games.com/support/solutions/articles/150000232714-assetto-corsa-evo-0-9-patch-notes ;
  https://support.505games.com/support/solutions/articles/150000233185-assetto-corsa-evo-0-9-1-hotfix-1st-sept-2026-
- [O2] https://github.com/devology-uk/sim-racing-sdk/blob/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/research/ACE_SharedFileOut_Documentation_v1.pdf

**Open source (cross-checks)**
- [C1] https://github.com/devology-uk/sim-racing-sdk/tree/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/src/SimRacingSdk.Acc.Udp ;
  https://github.com/devology-uk/sim-racing-sdk/tree/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/src/SimRacingSdk.Ace.Udp ;
  commits https://github.com/devology-uk/sim-racing-sdk/commit/4531315fa2 ,
  https://github.com/devology-uk/sim-racing-sdk/commit/1f8b9ef708 ,
  https://github.com/devology-uk/sim-racing-sdk/commit/da5cac0798
- [C2] https://github.com/LennysLounge/ACC-Race-Control/blob/42f87f55ffa8cc7332c686ab7c15bb98df1c090d/base/src/main/java/racecontrol/client/protocol/AccBroadcastingProtocol.java ;
  https://github.com/LennysLounge/ACC-Race-Control/blob/42f87f55ffa8cc7332c686ab7c15bb98df1c090d/base/src/main/java/racecontrol/client/AccConnection.java ;
  README https://github.com/LennysLounge/ACC-Race-Control/blob/42f87f55ffa8cc7332c686ab7c15bb98df1c090d/README.md ;
  the "falsely documented" commit https://github.com/LennysLounge/ACC-Race-Control/commit/8d834d37fc2276221419e18407e252dc482580ba (2021-09-02)
- [C3] https://github.com/prule/acc-client/blob/88b8e854971177ec59c5f65ba527415eba2e914b/acc-client-core/src/main/resources/com/github/prule/acc/client/simulator/playback-events.csv ;
  https://github.com/prule/acc-client/blob/88b8e854971177ec59c5f65ba527415eba2e914b/docs/Sample%20Run.md

**Secondary**
- [S1] https://racesimcentral.net/assetto-corsa-competizione-v1-10-1-fixes-api-sector-times-for-nurburgring-24h/

**pitwall**
- [P1] `docs/research/forza-ac-acc-iracing.md` §3
- `docs/research/track-knowledge-sources.md` (L0b-ACC, §4.2, §6.1, V9, §7.6, Phase 6)
- `docs/research/game-compatibility.md` (family 5; §10 item 7; [F12])
- `docs/research/protocols/ac-remote-udp.md` (sibling client pattern)
