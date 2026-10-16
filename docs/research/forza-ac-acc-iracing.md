# Forza, Assetto Corsa, ACC and iRacing telemetry: protocols and availability

Research date: 2026-10-10. Target host: a Python app on macOS on the same LAN as the game machine or console. Offsets are byte-exact where a parser needs them. Shared-memory APIs that cannot be read from a Mac are summarised at field level only.

Status vocabulary used throughout: **Official** (vendor doc), **Community** (documented by community implementations), **Unverified** (single or unconfirmed claim), **Unsupported** (no interface exists, as far as I can find).

---

## 1. Forza "Data Out" (FM7, FH4, FH5, FH6, Forza Motorsport 2023)

### 1.1 Transport and settings

| Item | Detail | Status |
|---|---|---|
| Transport | One-way UDP push to a user-configured IP:port. No handshake and no heartbeat. Little-endian. | Official |
| Rate | FM2023 and FM7: **60 packets/s**. FH6: "a rate equal to the game's frame rate". | Official |
| Localhost | FM2023 and FH6 support 127.0.0.1 (FM2023's doc calls this "new"). FM7, FH4 and FH5 on PC (Store/UWP builds) historically could not send to localhost without a loopback exemption, so a second machine was used. | Official (FM2023/FH6) / Community (older titles) |
| Settings, FM2023 | SETTINGS > GAMEPLAY & HUD > "UDP RACE TELEMETRY": Data Out (On/Off), Data Out IP Address, Data Out IP Port, Data Out Packet Format (Sled/Dash) | Official |
| Settings, FH6 | SETTINGS > HUD AND GAMEPLAY: Data Out, IP Address, IP Port. **Avoid ports 5200–5300**, because the game binds its own outgoing socket in that range. Single fixed format. | Official |
| Settings, FH4/FH5 | Settings > HUD and Gameplay (bottom of list): DATA OUT, DATA OUT IP ADDRESS, DATA OUT IP PORT (Dash-style format is forced) | Community (xsimulator FAQ, Moza guide) |
| When sent | FM: continuous while on track. `IsRaceOn` = 0 in menus or when the race is stopped. FH6: **only while actively driving**; nothing in menus, pauses, replays or rewinds, or after finishing. | Official |
| Multiple consumers | A single destination only. Fan out on the Mac. | Official (implied) |

### 1.2 Packet sizes and how to tell formats apart (by datagram length)

| Length | Format | Games | Status |
|---|---|---|---|
| **232** | Sled | FM7, FM2023 (when "Sled" is selected) | Official |
| **311** | Dash v1 = Sled + Dash block | FM7 | Official (field list) / Community (size) |
| **324** | Horizon Dash = Sled + **12-byte block at offset 232** + Dash block (shifted +12) + **1 trailing pad byte** at 323 | FH4, FH5, FH6 | FH6 Official ("Total packet size: 324 bytes"); FH4/5 Community |
| **331** | Dash v3 = FM7 Dash + TireWear ×4 + TrackOrdinal | Forza Motorsport (2023) | Official (field list) / Community (size) |

FH4, FH5 and FH6 all produce 324 bytes and cannot be told apart by length. Treat them as one layout. For FH6 the 12-byte block is officially `CarGroup` (U32), `SmashableVelDiff` (F32) and `SmashableMass` (F32). For FH4/5 the community decodes only the first int, as "CarCategory" (forza-data-web), which is consistent with FH6's `CarGroup`. FH6 also redefines the four `WheelInPuddle*` fields as S32 booleans (FM: F32 depth 0..1). The offsets are the same.

### 1.3 Sled block (offsets 0–231, all games)

| Offset (dec / hex) | Type | Field | Units / notes |
|---|---|---|---|
| 0 / 0x000 | S32 | IsRaceOn | 1 = race on; 0 = menus / race stopped |
| 4 / 0x004 | U32 | TimestampMS | ms; wraps to 0 eventually |
| 8 / 0x008 | F32 | EngineMaxRpm | rpm |
| 12 / 0x00C | F32 | EngineIdleRpm | rpm |
| 16 / 0x010 | F32 | CurrentEngineRpm | rpm |
| 20–28 / 0x014–0x01C | F32×3 | AccelerationX, Y, Z | Car-local (X right, Y up, Z forward). m/s² per community; unit not stated officially. |
| 32–40 / 0x020–0x028 | F32×3 | VelocityX, Y, Z | Car-local, m/s |
| 44–52 / 0x02C–0x034 | F32×3 | AngularVelocityX, Y, Z | Car-local pitch / yaw / roll rate, rad/s |
| 56 / 0x038 | F32 | Yaw | rad |
| 60 / 0x03C | F32 | Pitch | rad |
| 64 / 0x040 | F32 | Roll | rad |
| 68–80 / 0x044–0x050 | F32×4 | NormalizedSuspensionTravel FL, FR, RL, RR | 0 = max stretch, 1 = max compression |
| 84–96 / 0x054–0x060 | F32×4 | TireSlipRatio FL..RR | 0 = full grip; absolute value > 1 = loss of grip |
| 100–112 / 0x064–0x070 | F32×4 | WheelRotationSpeed FL..RR | rad/s |
| 116–128 / 0x074–0x080 | S32×4 | WheelOnRumbleStrip FL..RR | 1 = on rumble strip |
| 132–144 / 0x084–0x090 | F32×4 (FH6: S32×4) | WheelInPuddleDepth FL..RR | 0..1 depth (FH6: 1 = in puddle) |
| 148–160 / 0x094–0x0A0 | F32×4 | SurfaceRumble FL..RR | Non-dimensional FFB value |
| 164–176 / 0x0A4–0x0B0 | F32×4 | TireSlipAngle FL..RR | Normalised; absolute value > 1 = loss of grip |
| 180–192 / 0x0B4–0x0C0 | F32×4 | TireCombinedSlip FL..RR | Normalised; absolute value > 1 = loss of grip |
| 196–208 / 0x0C4–0x0D0 | F32×4 | SuspensionTravelMeters FL..RR | m |
| 212 / 0x0D4 | S32 | CarOrdinal | Car make/model ID |
| 216 / 0x0D8 | S32 | CarClass | 0 (D) .. 7 (X) |
| 220 / 0x0DC | S32 | CarPerformanceIndex | 100..999 |
| 224 / 0x0E0 | S32 | DrivetrainType | 0 FWD, 1 RWD, 2 AWD |
| 228 / 0x0E4 | S32 | NumCylinders | count |

The official FM doc contains a typo, `heelOnRumbleStripRearRight`; the field is WheelOnRumbleStripRearRight.

### 1.4 Horizon-only block (FH4/FH5/FH6, offsets 232–243)

| Offset | Type | Field (FH6 official name) | Notes |
|---|---|---|---|
| 232 / 0x0E8 | U32 | CarGroup | FH4/5 community: "CarCategory" |
| 236 / 0x0EC | F32 | SmashableVelDiff | m/s velocity lost hitting a smashable object |
| 240 / 0x0F0 | F32 | SmashableMass | kg of the recently hit smashable |

### 1.5 Dash block (FM7/FM2023 offset | Horizon offset = FM offset + 12)

| FM7/FM2023 | FH4/5/6 | Type | Field | Units / notes (units from the FH6 doc unless stated) |
|---|---|---|---|---|
| 232 (0x0E8) | 244 (0x0F4) | F32 | PositionX | World space, m |
| 236 (0x0EC) | 248 (0x0F8) | F32 | PositionY | m (vertical) |
| 240 (0x0F0) | 252 (0x0FC) | F32 | PositionZ | m |
| 244 (0x0F4) | 256 (0x100) | F32 | Speed | m/s |
| 248 (0x0F8) | 260 (0x104) | F32 | Power | W |
| 252 (0x0FC) | 264 (0x108) | F32 | Torque | N·m |
| 256 (0x100) | 268 (0x10C) | F32 | TireTempFrontLeft | Unit not stated officially; community: °F |
| 260 (0x104) | 272 (0x110) | F32 | TireTempFrontRight | " |
| 264 (0x108) | 276 (0x114) | F32 | TireTempRearLeft | " |
| 268 (0x10C) | 280 (0x118) | F32 | TireTempRearRight | " |
| 272 (0x110) | 284 (0x11C) | F32 | Boost | psi above atmospheric |
| 276 (0x114) | 288 (0x120) | F32 | Fuel | 0.0 empty .. 1.0 full |
| 280 (0x118) | 292 (0x124) | F32 | DistanceTraveled | m, cumulative since driving started (not per lap) |
| 284 (0x11C) | 296 (0x128) | F32 | BestLap | s (0.0 if n/a) |
| 288 (0x120) | 300 (0x12C) | F32 | LastLap | s |
| 292 (0x124) | 304 (0x130) | F32 | CurrentLap | s |
| 296 (0x128) | 308 (0x134) | F32 | CurrentRaceTime | s |
| 300 (0x12C) | 312 (0x138) | U16 | LapNumber | Laps completed |
| 302 (0x12E) | 314 (0x13A) | U8 | RacePosition | |
| 303 (0x12F) | 315 (0x13B) | U8 | Accel | Throttle 0..255 |
| 304 (0x130) | 316 (0x13C) | U8 | Brake | 0..255 |
| 305 (0x131) | 317 (0x13D) | U8 | Clutch | 0..255 |
| 306 (0x132) | 318 (0x13E) | U8 | HandBrake | 0..255 |
| 307 (0x133) | 319 (0x13F) | U8 | Gear | Current gear. Reverse/neutral encoding not documented: verify with a capture. |
| 308 (0x134) | 320 (0x140) | S8 | Steer | −127 full left .. 127 full right |
| 309 (0x135) | 321 (0x141) | S8 | NormalizedDrivingLine | −127..127 |
| 310 (0x136) | 322 (0x142) | S8 | NormalizedAIBrakeDifference | −127..127 |
| — | 323 (0x143) | — | padding | 1 byte, unused (forza-data-web reads Dash from 244..323) |

### 1.6 Forza Motorsport (2023) extras (offsets 311–330; total 331)

| Offset | Type | Field | Notes |
|---|---|---|---|
| 311 (0x137) | F32 | TireWearFrontLeft | Officially undocumented range; community treats it as 0..1 wear fraction. **Unaligned**: parse with an unaligned little-endian unpack. |
| 315 (0x13B) | F32 | TireWearFrontRight | |
| 319 (0x13F) | F32 | TireWearRearLeft | |
| 323 (0x143) | F32 | TireWearRearRight | |
| 327 (0x147) | S32 | TrackOrdinal | Track ID (a mapping table must be built by the community or by us) |

### 1.7 Console availability (Forza)

| Game / platform | Data Out to a LAN IP from the console? | Status |
|---|---|---|
| FM7 – Xbox One | Yes. The same settings send UDP to a PC or Mac on the LAN. | Community |
| FH4 – Xbox One | Yes. The xsimulator FAQ documents DATA OUT on Xbox One X sending to a PC IP/port. | Community |
| FH5 – Xbox One / Series X\|S | Yes (same settings as FH4) | Community |
| FH5 – PS5 (released 2025) | Not found. No source confirms Data Out exists or works on PS5. | **Unverified** |
| FM2023 – Xbox Series X\|S | Yes. The official doc describes sending "to a remote IP address". | Official (feature) / Community (console use) |
| FH6 | The official doc (2026-05) describes the feature but does not list platforms | Official (feature) / Unverified (per-platform) |

Xbox caveat: Next Level Racing's console-motion page (2026-05) says its platforms support no Xbox titles. That is a statement about their product, not about Forza Data Out.

---

## 2. Assetto Corsa (original, 2014)

### 2.1 Shared memory (Windows only)
- Three named file mappings: `Local\acpmf_physics`, `Local\acpmf_graphics`, `Local\acpmf_static`. They are documented by Kunos in the "Shared Memory Reference" forum post, and community ports such as mdjarv/assettocorsasharedmemory (MIT) mirror the structs.
- **physics** (per physics step): packetId, gas, brake, clutch, fuel, gear, rpms, steerAngle, speedKmh, velocity[3], accG[3], wheelSlip[4], wheelLoad[4], wheelsPressure[4], wheelAngularSpeed[4], **tyreWear[4]**, tyreDirtyLevel[4], tyreCoreTemperature[4], **tyreTempI/M/O[4]**, camberRAD[4], suspensionTravel[4], rideHeight[2], brakeTemp[4], brakeBias, drs, tc, abs, heading/pitch/roll, cgHeight, carDamage[5], numberOfTyresOut, pitLimiterOn, turboBoost, ballast, airDensity, **airTemp, roadTemp**, localAngularVelocity, localVelocity, finalFF, ERS/KERS fields.
- **graphics** (per frame): status, session type, completedLaps, position, iCurrentTime/iLastTime/iBestTime (ms), sessionTimeLeft, distanceTraveled, isInPit, isInPitLane, **currentSectorIndex, lastSectorTime**, numberOfLaps, **normalizedCarPosition** (0..1 lap fraction), **carCoordinates[3]**, penaltyTime, flag, surfaceGrip, mandatoryPitDone.
- **static** (per session): smVersion, acVersion, carModel, **track, trackConfiguration**, playerName, sectorCount, maxRpm, maxFuel, maxTorque, maxPower, tyreRadius[4], suspensionMaxTravel[4], trackSPlineLength, aid settings, pit window.
- Setups are **not** exposed. They live on disk as `.ini` files under `Documents\Assetto Corsa\setups\<car>\<track>\`. Weather beyond air/road temperature is not exposed in vanilla AC.
- **Not readable from a Mac.** A Windows-side relay process (one that reads the mappings and streams over UDP/WebSocket) is required.

### 2.2 UDP "Remote Telemetry" (port 9996)

Official spec: Kunos "Assetto Corsa Remote Telemetry: UDP Specification" (Google Doc linked from AC client libraries). The byte layout below combines that spec with observed packets.

**Session**
1. Client to AC host UDP **9996**: `handshaker` = 3 × int32 LE: `identifier` (1; reserved for device type), `version` (1; reserved), `operationId`.
2. operationId values: **0 HANDSHAKE**, **1 SUBSCRIBE_UPDATE** (stream RTCarInfo), **2 SUBSCRIBE_SPOT** (lap events as RTLap), **3 DISMISS**.
3. Send HANDSHAKE and receive `handshakerResponse`. Then send the same 12-byte struct with operationId 1 or 2. The server sends to the sender's address. Send DISMISS on exit; to reconnect, repeat from step 1.
4. AC sends RTCarInfo "on every physics step" (spec). One community client reports about 20 Hz. **Measure the rate yourself.**

**handshakerResponse.** The spec says `char[50]`. In practice the strings are UTF-16LE `wchar[50]`, and the response is **408 bytes** (rusty-telemetry, Egocentrix C# marshalling with CharSet.Unicode).

| Offset | Type | Field |
|---|---|---|
| 0 | wchar[50] (100 B) | carName |
| 100 | wchar[50] | driverName |
| 200 | int32 | identifier (4242 = OK) |
| 204 | int32 | version (1) |
| 208 | wchar[50] | trackName |
| 308 | wchar[50] | trackConfig |

**RTCarInfo** (observed size **328 bytes**; an early community calculation from the spec gave 323. Strings and bools are padded.)

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | wchar (2 B) + 2 pad | identifier | `'a'` |
| 4 | int32 | size | struct size (328) |
| 8 | f32 | speed_Kmh | |
| 12 | f32 | speed_Mph | |
| 16 | f32 | speed_Ms | |
| 20 | u8 | isAbsEnabled | |
| 21 | u8 | isAbsInAction | |
| 22 | u8 | isTcInAction | |
| 23 | u8 | isTcEnabled | |
| 24 or 26 | u8 | isInPit | Natural C layout gives 24/25. The Egocentrix C# client (built from observed packets) uses 26/27. **Verify.** |
| 25 or 27 | u8 | isEngineLimiterOn | as above |
| 28 | f32 | accG_vertical | g |
| 32 | f32 | accG_horizontal | g |
| 36 | f32 | accG_frontal | g |
| 40 | int32 | lapTime | ms (current lap) |
| 44 | int32 | lastLap | ms |
| 48 | int32 | bestLap | ms |
| 52 | int32 | lapCount | |
| 56 | f32 | gas | 0..1 |
| 60 | f32 | brake | 0..1 |
| 64 | f32 | clutch | 0..1 |
| 68 | f32 | engineRPM | |
| 72 | f32 | steer | Steering angle (units undocumented) |
| 76 | int32 | gear | AC convention: 0 = R, 1 = N, 2 = 1st (community; verify) |
| 80 | f32 | cgHeight | m |
| 84 | f32×4 | wheelAngularSpeed | |
| 100 | f32×4 | slipAngle | |
| 116 | f32×4 | slipAngle_ContactPatch | |
| 132 | f32×4 | slipRatio | |
| 148 | f32×4 | tyreSlip | |
| 164 | f32×4 | ndSlip | |
| 180 | f32×4 | load | N |
| 196 | f32×4 | Dy | |
| 212 | f32×4 | Mz | |
| 228 | f32×4 | tyreDirtyLevel | |
| 244 | f32×4 | camberRAD | |
| 260 | f32×4 | tyreRadius | |
| 276 | f32×4 | tyreLoadedRadius | |
| 292 | f32×4 | suspensionHeight | |
| 308 | f32 | carPositionNormalized | **Lap fraction 0..1** |
| 312 | f32 | carSlope | |
| 316 | f32×3 | carCoordinates | World x, y, z |

**RTLap** (SUBSCRIBE_SPOT; fires for every car in the session on lap completion): int32 carIdentifierNumber @0, int32 lap @4, wchar[50] driverName @8, wchar[50] carName @108, int32 time (ms) @208. That is 212 bytes assuming wchar strings. **Unverified**: capture to confirm.

**Not in RTCarInfo:** fuel, tyre temperatures, tyre wear, sector times, weather, setup. The track is identified via handshake strings.

**Usable from a Mac on the LAN while AC runs on a Windows PC? Yes.** The protocol is plain UDP to the PC's IP. Libraries such as Egocentrix/AC-UDP-Connection target remote hosts. Windows Firewall must allow inbound UDP 9996 for `acs.exe`. Status: Community. The spec talks about connecting to "the PC running AC".

**Console AC (PS4 / Xbox One, 2016 console edition):**
- **PS4**: community reports that the UDP 9996 handshake works. vthinsel (assettocorsamods.net, 2017) received 328-byte RTCarInfo packets "running on PS4", and iimetra/assetto-corsa-telemetry-4j's README example connects to a PS4 LAN IP. One member's 2017 observation: the console build follows the older v1 protocol. Status: **Community (2017-era; not re-verified on current firmware or PS5 back-compat)**.
- **Xbox One**: no report found. Status: **Unverified**.
- Shared memory does not exist on consoles.
- Note: Assetto Corsa EVO (PC, early access 2025) uses differently named mappings (`Local\acevo_pmf_physics`/`graphics`/`static`). It is out of scope here, but a relay could support it later.

---

## 3. Assetto Corsa Competizione

### 3.1 Shared memory (Windows only)
- Same mapping names as AC (`Local\acpmf_physics`/`graphics`/`static`) with ACC-specific layouts. Official reference: Kunos "ACC Shared Memory Documentation" v1.8.12 PDF (forum thread 59965, login required), plus `SharedMemoryACCS.zip` sample.
- Field-by-field layouts, offsets and what pitwall maps: `docs/research/acc-shared-memory-spec.md` (machine-checked against `adapters/acc/packets.py`).
- **Player car only**, except `carCoordinates[60][3]` and `carID[60]` (graphics), which cover every car.
- Highlights:
  - physics: gas, brake, clutch, steerAngle, gear, rpms, speedKmh, velocities, accG, wheel slip, wheelPressure, wheelAngularSpeed, **tyreCoreTemperature**, brakeTemp, padLife/discLife, suspension travel, TC/ABS levels.
  - graphics: iCurrentTime/iLastTime/iBestTime, **currentSectorIndex/lastSectorTime/iSplit**, **normalizedCarPosition**, completedLaps, position, isInPit/isInPitLane, fuelXLap, fuelEstimatedLaps, usedFuel, tyreCompound, **rainIntensity, rainIntensityIn10min/30min, trackGripStatus, windSpeed/windDirection**, flags, gapAhead/gapBehind, MFD settings (TC, ABS, engine map, brake bias, tyre pressures to add).
  - static: **track**, carModel, maxFuel, sectorCount, pitWindowStart/End, dryTyresName/wetTyresName, aids.
  - physics also carries airTemp and roadTemp.
- `tyreWear` exists in the struct but is **not used in ACC** (marked obsolete by community ports such as Race-Element). There is **no live tyre-wear value**.
- Setups are **not** exposed. They are JSON files on disk at `Documents\Assetto Corsa Competizione\Setups\<car>\<track>\`.
- Not readable from a Mac without a Windows relay.

### 3.2 Broadcasting API (UDP)
- Purpose: spectator/broadcast tools. It covers all cars' positions and timing, not the driver's inputs.
- Configuration: `Documents\Assetto Corsa Competizione\Config\broadcasting.json` with `updListenerPort` (commonly **9000**), `connectionPassword` and `commandPassword`. The community reports the file is UTF-16LE encoded and must be saved that way.
- Reference implementation: the C# sample `ksBroadcastingNetwork` that Kunos ships with the game's SDK folder. It is mirrored in Race-Element (GPL-3.0) and SeriousOldMan/Simulator-Controller. No public Kunos spec page was found, so this section is **Community**.
- Wire format: every message starts with a 1-byte type. Integers and floats are little-endian. Strings are a UInt16 length followed by that many UTF-8 bytes.
- **Register** (client → ACC): byte 1 (REGISTER_COMMAND_APPLICATION), byte **4** (protocol version), string displayName, string connectionPassword, int32 msRealtimeUpdateInterval, string commandPassword.
- Other outbound types: 9 UNREGISTER, 10 REQUEST_ENTRY_LIST, 11 REQUEST_TRACK_DATA, 49 CHANGE_HUD_PAGE, 50 CHANGE_FOCUS, 51 INSTANT_REPLAY_REQUEST (52/60 replay highlights planned). Each carries int32 connectionId after the type byte.
- Inbound types:
  - 1 **REGISTRATION_RESULT**: int32 connectionId, u8 success (>0 = ok), u8 writeable flag (0 = read-only, i.e. the command password was not accepted), string error.
  - 2 **REALTIME_UPDATE** (session): u16 eventIndex, u16 sessionIndex, u8 sessionType, u8 phase, f32 sessionTime ms, f32 sessionEndTime ms, i32 focusedCarIndex, strings activeCameraSet/activeCamera/currentHudPage, u8 isReplayPlaying (+ 2 × f32 if set), f32 timeOfDay ms, **u8 ambientTemp, u8 trackTemp, u8 clouds/10, u8 rainLevel/10, u8 wetness/10**, then a best-session-lap structure.
  - 3 **REALTIME_CAR_UPDATE** (per car): u16 carIndex, u16 driverIndex, u8 driverCount, u8 gear (subtract 2: R = −1, N = 0), f32 worldPosX, f32 worldPosY (2-D map plane), f32 heading/yaw, u8 carLocation (track/pitlane/pit entry/pit exit), **u16 kmh**, u16 position, u16 cupPosition, u16 trackPosition, **f32 splinePosition (0..1)**, u16 laps, i32 delta (ms), then three LapInfo structures (best session, last, current).
  - 4 ENTRY_LIST: i32 connectionId, u16 count, u16[count] carIds.
  - 5 **TRACK_DATA**: i32 connectionId, string trackName, **i32 trackId, i32 trackMeters**, camera sets, HUD pages.
  - 6 ENTRY_LIST_CAR: car model, team, race number, cup category, drivers with names, category and nationality.
  - 7 BROADCASTING_EVENT: u8 type, string msg, i32 timeMs, i32 carId.
  - **LapInfo**: i32 laptimeMs, u16 carIndex, u16 driverIndex, u8 splitCount, i32[splitCount] splits, then u8 flags isInvalid, isValidForBest, isOutlap, isInlap.
- **Provides:** positions and laps for all cars, lap distance (splinePosition × trackMeters), sector splits, gear, speed (1 km/h resolution), weather summary, track identity.
- **Does not provide:** throttle, brake, steering, RPM, tyres, fuel, damage, setup.
- From a Mac: plain UDP to the PC's IP and `updListenerPort`. The community uses it across the LAN; allow it in the Windows firewall. Status: Community.

### 3.3 Console ACC (PS4/Xbox One 2020; PS5/Xbox Series X|S 2022)
**No external telemetry interface is known.** The console builds have no shared memory, no user-editable broadcasting.json, and no UDP output setting. No Kunos/505 document mentions one. Next Level Racing's console motion support page (updated 2026-05) lists only **Gran Turismo 7 and F1 25** on PlayStation and **no Xbox titles**. GTPlanet users report that SimHub cannot connect to ACC on PS5. Status: **Unsupported** (community consensus, no official statement). For console ACC the only fallback is video capture (§7).

---

## 4. iRacing (Windows PC only)

### 4.1 Live SDK (irsdk)
- A memory-mapped file `Local\IRSDKMemMapFileName` (pyirsdk maps 1164 KiB), with a data-valid event `Local\IRSDKDataValidEvent` signalled on each update and a broadcast window message `IRSDK_BROADCASTMSG` for camera, replay, chat, pit and telemetry commands.
- Header (int32 fields): version, status, **tickRate** (60), sessionInfoUpdate (incremented when the YAML changes), sessionInfoLen, sessionInfoOffset, numVars, varHeaderOffset, numBuf (rotating buffers, up to 4; 3 in practice), bufLen. It is followed by per-buffer {tickCount, bufOffset}. Readers use the buffer with the highest tickCount.
- Each variable header: type (char/bool/int/bitfield/float/double), offset, count, countAsTime, name[32], desc[64], unit[32]. Variables are discovered by name at runtime, so there are no hard-coded offsets.
- Session info is a **YAML** string: WeekendInfo (TrackName, **TrackID**, TrackLength, weather settings), SessionInfo, DriverInfo, **SplitTimeInfo** (sector start positions as lap fractions), **CarSetup** (when the setup is visible to the driver).
- Useful live variables (from pyirsdk `vars.txt`): Speed (m/s), RPM, Gear, Throttle, Brake, Clutch, **SteeringWheelAngle** (rad), **LapDist** (m), **LapDistPct**, Lap, LapCurrentLapTime, LapLastLapTime, LapBestLapTime, LapDeltaToBestLap, FuelLevel (L), FuelLevelPct, LFtempCL/CM/CR (carcass), LFwearL/M/R, LFcoldPressure, LFshockDefl, PlayerCarPosition, CarIdxLapDistPct / CarIdxPosition / CarIdxF2Time (all cars), AirTemp, TrackTempCrew, TrackWetness, Precipitation, Skies, WindVel, VelocityX/Y/Z, Yaw/Pitch/Roll, LatAccel/LongAccel, OnPitRoad, SessionFlags.
- Variables with the `_ST` suffix carry 360 Hz sub-samples (for example LatAccel_ST, LFshockDefl_ST).
- Caveats:
  - Live tyre carcass temperatures and wear update only when the car is in the pit stall (Community; verify).
  - There is no world X/Y/Z in live data. Lat/Lon/Alt are disk-only (.ibt) variables (Community; verify).

### 4.2 .ibt files
- Written to `Documents\iRacing\telemetry\` when disk logging is on (Alt+L in the sim, or the TelemCommand broadcast message).
- Layout: the same irsdk header, then a disk sub-header (session start date, start time, end time, lap count, record count), variable headers, session YAML, and fixed-size 60 Hz records.
- Parseable on any OS. pyirsdk has an `IBT` reader that maps the file; its live mode needs Windows APIs (`ctypes.windll`).

### 4.3 From another machine
The memory map is local to the Windows box and **iRacing has no network telemetry API**. A Mac host needs either:
- (a) a **Windows-side relay** (a small Python/C# service that reads irsdk at 60 Hz and streams over UDP/WebSocket), or
- (b) post-session copying of `.ibt` files (an SMB share).

There is no console version.

### 4.4 Licences
- **pyirsdk** (kutu/pyirsdk): **MIT**, © 2014 Mihail Latyshov. It is suitable for a Windows relay.
- iRacing's own C++ SDK sample headers carry iRacing's copyright notice. Check their terms before vendoring (Unverified).

---

## 5. Capability matrix

Legend: **Y** = provided directly; **D** = derivable from provided fields; **P** = partial (see note); **N** = not available. Status = source quality for that row.

| Game / platform | Transport | Speed | Inputs T/B/Steer | Gear/RPM | World position | Lap distance | Lap / sector times | Tyre temps | Tyre wear | Fuel | Setup data | Weather | Track ID | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GT7, PS5 (variant A, all versions) | UDP 33739/33740, heartbeat, Salsa20 | Y | Y / Y / **N** | Y / Y | Y (XYZ) | D (integrate speed or project on centreline) | Lap: Y (best/last) / Sector: N | P (surface only) | N (radius heuristic only) | Y | P (gear ratios only) | N (time of day only) | D (geometry match) | Community (well cross-checked) |
| GT7, PS5 (B/~ ≥1.42; C ≥~1.68) | same, heartbeat `B`/`~`/`C` | Y | Y / Y / **Y** (wheel angle; C adds road-wheel angles) | Y / Y | Y | D | C adds current-lap ms; sectors N | P | N | Y | P | N (C: surface type per wheel) | D | Community |
| GT7, PS4 | same | Y | as above | Y | Y | D | as above | P | N | Y | P | N | D | Community (no recent live report) |
| FM7, Xbox One / PC (Dash 311) | UDP push, user IP:port | Y | Y / Y / Y | Y / Y | Y | D (DistanceTraveled delta per lap) | Lap: Y / Sector: N | Y (1 per tyre) | N | Y | N | N (puddle/rumble only) | N | Official |
| Forza Motorsport 2023, Xbox Series / PC (Dash 331) | UDP push | Y | Y / Y / Y | Y / Y | Y | D | Lap: Y / Sector: N | Y | **Y** | Y | N | N | **Y** (TrackOrdinal) | Official |
| FH4 / FH5, Xbox / PC (324) | UDP push | Y | Y / Y / Y | Y / Y | Y | D (open world; laps only in races) | Lap: Y / Sector: N | Y | N | Y | N | N | N | Community (FH4/5 layout) |
| FH5, PS5 | ? | — | — | — | — | — | — | — | — | — | — | — | — | **Unverified** |
| FH6 (324) | UDP push, frame-rate rate | Y | Y / Y / Y | Y / Y | Y | D | Lap: Y / Sector: N | Y | N | Y | N | N | N | Official (platforms unverified) |
| AC, PC, shared memory | Windows mmap, needs relay | Y | Y / Y / Y | Y / Y | Y | Y (normalizedCarPosition × spline length) | Y / Y (last sector, index) | Y (core + I/M/O) | Y | Y | N (.ini on disk) | P (air/road temp) | Y (track + config strings) | Official |
| AC, PC, UDP 9996 | UDP handshake + subscribe | Y | Y / Y / Y | Y / Y | Y | Y (carPositionNormalized) | Lap: Y / Sector: N | N | N | N | N | N | Y (handshake strings) | Official spec + Community layout |
| AC, PS4 (Xbox One: ?) | UDP 9996 handshake | Y | Y / Y / Y | Y / Y | Y | Y | Lap: Y / Sector: N | N | N | N | N | N | Y | PS4: Community (2017) / XB1: Unverified |
| ACC, PC, shared memory | Windows mmap, needs relay | Y | Y / Y / Y | Y / Y | Y (all cars) | Y | Y / Y | Y (core) | **N** (field unused) | Y | N (JSON on disk) | **Y** (rain now/+10/+30 min, grip, wind, temps) | Y (string) | Official |
| ACC, PC, Broadcasting | UDP register (port in broadcasting.json, often 9000) | Y (int km/h) | **N / N / N** | Y / N | P (2-D) | Y (spline × trackMeters) | Y / Y (splits) | N | N | N | N | Y (temps, clouds, rain, wetness) | Y (name, id, metres) | Community (Kunos SDK sample) |
| ACC, PS5 / Xbox Series (and PS4/XB1) | none | N | N | N | N | N | N | N | N | N | N | N | N | **Unsupported** |
| iRacing, PC, live SDK | Windows mmap, needs relay | Y | Y / Y / Y | Y / Y | **N** live | Y (LapDist, LapDistPct) | Y / D (SplitTimeInfo + LapDistPct) | P (carcass, pit-only updates) | P (pit-only updates) | Y | Y (CarSetup YAML when visible) | Y | Y (TrackID) | Official (SDK) + Community caveats |
| iRacing, PC, .ibt | File copy | Y | Y / Y / Y | Y / Y | P (Lat/Lon/Alt, disk-only) | Y | Y / D | P | P | Y | Y | Y | Y | Official + Community |
| F1 25, PC | UDP push (EA spec) | Y | Y / Y / Y | Y / Y | Y | Y | Y / Y | Y | Y | Y | Y | Y | Y | Official EA spec (see F1 doc) |
| F1 25, PS5 | UDP push to LAN IP | Y | Y / Y / Y | Y / Y | Y | Y | Y / Y | Y | Y | Y | Y | Y | Y | Official EA spec |
| F1 25, Xbox Series X\|S | UDP push to LAN IP | Y | Y / Y / Y | Y / Y | Y | Y | Y / Y | Y | Y | Y | Y | Y | Y | Official EA spec |

Notes:
- "Lap distance D" for Forza: subtract `DistanceTraveled` at the lap-start transition (LapNumber increments). This drifts in Horizon free-roam. For Forza Motorsport, `NormalizedDrivingLine` is lateral position relative to the driving line, not a longitudinal value.
- For a Mac-hosted coach the directly reachable sources are GT7, Forza, AC UDP, ACC Broadcasting and F1. AC/ACC shared memory and iRacing need a Windows relay.

---

## 6. Practical recommendations for pitwall
1. Implement transports in this order: **GT7** (encrypted, heartbeat), **Forza** (length-dispatched passive listener), **F1 25**, then **AC UDP** (handshake/subscribe).
2. Put AC/ACC shared memory and iRacing behind a single **Windows relay** protocol that pitwall defines (for example JSON or CBOR over UDP). Do not try to support them natively on macOS.
3. Use ACC Broadcasting only for race context (positions, gaps, splits, weather). It cannot drive input coaching.
4. Always record the raw datagrams with monotonic receive timestamps. They make test fixtures and are the only way to settle the Unverified items above.

---

## 7. Video capture / computer-vision fallback (for ACC console, FH5 PS5 and anything else without telemetry)

- **Setup:** console HDMI → passthrough capture card (UVC devices appear as a camera on macOS) → frame grabber at 30–60 fps → region crops → OCR/CNN.
- **HDCP:** PS4/PS5 output HDCP by default. Both expose a system setting to disable HDCP for game output (community-known; verify on current firmware). Xbox game output is generally capturable.
- **Extractable:**
  - Speed and gear from fixed HUD digits. A small digit classifier trained per game/HUD layout is more robust than generic OCR. Apple Vision/Tesseract are a fallback.
  - Lap timer / delta text.
  - Position "P3/20".
  - Fuel or tyre widgets where the HUD shows them.
  - **Track position** by locating the player marker on the minimap. Its pixel position maps to lap fraction after calibrating a centreline per track. Accuracy is limited by minimap scale, rotation and zoom.
- **Key limitations:**
  - End-to-end latency of about 50–150 ms (capture, decode, inference). That is acceptable for coaching cues and poor for anything reactive.
  - No pedal or steering inputs unless the HUD draws input bars. Some games can show them; detect bar fill.
  - HUD layouts vary by game, settings, resolution, language, camera view and car. Calibration is needed for each game and each HUD preset.
  - Occlusion by pop-ups, replays and menus. A UI-state classifier is needed.
  - OCR misreads need temporal filtering, for example rejecting physically impossible speed jumps.
  - Minimap-based lap distance is coarse, roughly ±5–20 m.
  - There is no tyre, fuel or setup data unless it is visible.
  - Extra hardware cost (capture card) and setup complexity.
  - Check platform/game terms before distributing any capture-based product.

---

## Sources
- Forza Motorsport (2023) Data Out documentation (Turn 10, updated 2023-10-18): https://support.forza.net/hc/en-us/articles/21742934024211-Forza-Motorsport-Data-Out-Documentation
- Forza Horizon 6 Data Out documentation (Playground, 2026-05-15): https://support.forza.net/hc/en-us/articles/51744149102611-Forza-Horizon-6-Data-Out-Documentation
- geeooff/forza-data-web (Apache-2.0), packet-length dispatch and Horizon extras: https://github.com/geeooff/forza-data-web
- xsimulator.net console FAQ (FH4 on Xbox One X Data Out): https://xsimulator.net/community/faq/consoles.27/category
- Moza FH4/5 telemetry configuration: https://support.mozaracing.com/en/support/solutions/articles/70000625637-forza-horizon-4-5-telemetry-configuration
- Kunos, Assetto Corsa Remote Telemetry UDP specification: https://docs.google.com/document/d/1KfkZiIluXZ6mMhLWfDX1qAGbvhGRC3ZUzjVIt5FQpp4/pub
- Egocentrix/AC-UDP-Connection (no licence; read for layout only): https://github.com/Egocentrix/AC-UDP-Connection
- iimetra/assetto-corsa-telemetry-4j (PS4 example): https://github.com/iimetra/assetto-corsa-telemetry-4j
- rusty-telemetry (408-byte handshake, UTF-16LE): https://codeberg.org/jhunnius/rusty-telemetry
- assettocorsamods.net "UDP format update" thread (PS4, 328 bytes): https://assettocorsamods.net/threads/udp-format-update.896/
- mdjarv/assettocorsasharedmemory (MIT; AC shared-memory structs): https://github.com/mdjarv/assettocorsasharedmemory
- Kunos, ACC Shared Memory Documentation thread (PDF v1.8.12 attached): https://www.assettocorsa.net/forum/index.php?threads/acc-shared-memory-documentation.59965/
- RiddleTime/Race-Element (GPL-3.0; ACC broadcasting protocol and shared-memory mirrors): https://github.com/RiddleTime/Race-Element
- gotzl/pyacc (GPL-3.0): https://github.com/gotzl/pyacc
- Next Level Racing, Motion Compatibility on Console (2026-05-27): https://support.nextlevelracing.com/hc/en-us/articles/16164543318799-Motion-Compatibility-on-Console
- GTPlanet thread (ACC on PS5 has no telemetry, user report): https://www.gtplanet.net/forum/threads/bass-shaker-on-acc-awesome.394724/latest
- kutu/pyirsdk (MIT), `irsdk.py` and `vars.txt`: https://github.com/kutu/pyirsdk
