# Assetto Corsa Competizione shared memory (PC): Kunos' layouts, field by field

Research date: 2026-10-16. This document restates Kunos' official **"ACC Shared Memory v1.8.12"** for pitwall's ACC
reader. Every field name, C type and array length in §4 was extracted from that PDF by script (its text layer), the
"Kunos" column was read off the rendered pages (Kunos colours each row), and the offsets were computed from the
PDF's own types with the packing rule in §2 - none of it was typed from memory or copied from a port. The meanings are
in our own words.

Code: `src/pitwall/adapters/acc/packets.py` (the `StructDef`s), `src/pitwall/adapters/acc/adapter.py` (what pitwall
makes of the fields), `src/pitwall/adapters/acc/tracks.py` (track lengths). `tests/unit/test_acc_protocol.py`
machine-checks `packets.py` against §4 and §5 of this file: field names, types, array lengths, order, offsets and
total sizes, the enum values, and that the adapter reads only fields listed here as used by ACC (with one stated
exception) - the same job `test_f1_protocol.py` does for EA's F1 spec.

Evidence tier: **official document, synthetic tests**. Nothing here has been checked against a pitwall recording of
ACC yet. Ed (Pitwall tester) drove ACC with his own build of the adapter (Spa 2026-10-09, Brands Hatch 2026-10-13/14);
what he saw is quoted as a tester's report where it matters (§6), not as recorded evidence.

---

## 0. Summary

| Item | Value |
|---|---|
| Interface | Three Windows named file mappings created by ACC on the gaming PC: `Local\acpmf_physics`, `Local\acpmf_graphics`, `Local\acpmf_static` |
| Platforms | **PC only.** Console ACC (PS4/PS5/Xbox) has no shared memory and no telemetry output (`forza-ac-acc-iracing.md` §3.3) |
| Sizes | Physics **800** B, Graphics **1588** B, Static **820** B |
| Packing | `#pragma pack(4)` (Kunos' sample header): natural alignment up to 4 bytes; `int` / `float` / enums 4 B; `wchar_t` 2 B (UTF-16LE); little-endian |
| Change detection | `packetId` (offset 0) of Physics and of Graphics: "current step index", new value = new data. Static has none: it is set when a session instance starts |
| Wheel order | FL, FR, RL, RR in every `[4]` array (the PDF's order table and `ACC_WHEELS_TYPE` 0-3) |
| Whose data | The player's car, except Graphics `carCoordinates` / `carID` (every car on track) |
| Fields marked "not used by ACC" | 34 of 85 in Physics, 1 of 87 in Graphics, 20 of 45 in Static (§4, column "Kunos") |
| Track length | **Not available**: `trackSplineLength` is "not used in ACC". Pitwall uses a table (§6.9) |
| Pitwall framing | One whole page per snapshot, prefixed by a 4-byte tag `PHYS` / `GRPH` / `STAT` (§7) |

---

## 1. Sources

| Source | What it is | Used for |
|---|---|---|
| **[K]** Kunos Simulazioni, *ACC Shared Memory v1.8.12* | The official document: a 25-page PDF, `ACCSharedMemoryDocumentationV1.8.12.pdf`, 479.4 KB (490,941 bytes), PDF metadata author "KUNOS", created 2022-03-23 11:22:32 GMT. Attached to the first post of the official forum thread **"ACC Shared Memory Documentation"** (ACC Blog section, KS Dev Team, first post 2019-08-28, the post shows "Last edited: Feb 5, 2020"): https://www.assettocorsa.net/forum/index.php?threads/acc-shared-memory-documentation.59965/ . On 2026-10-16 that post carries this PDF (the only documentation version attached) and `SharedMemoryACCS.zip` (Kunos' C++ sample, 1.1 MB): v1.8.12 is the latest published. The PDF is newer than the post's last edit (it lists the 2022 Challengers Pack cars), so the attachment was evidently updated after that edit | **Everything in §4-§5**: field order, C types, array lengths, names, descriptions, which fields ACC uses, enums, appendices |
| [K-copy] The same PDF as hosted in `rrennoir/PyAccSharedMemory` (MIT repository; the PDF in it is Kunos') | The bytes we read: https://github.com/rrennoir/PyAccSharedMemory/blob/main/ACCSharedMemoryDocumentationV1.8.12.pdf - same file name and size as the forum attachment; SHA-256 `a0c279753f154e9145f6854313472a0e1270027057ce27e2db1547a63f56cabf`. The forum attachment itself was not downloaded | The text layer (pdftotext) and the rendered pages (colours) |
| [H] Kunos' sample header `SharedFileOut.h` (in `SharedMemoryACCS.zip`), as reproduced in public repositories (e.g. `IkoRein/ACC_ShmemUDP_Relay`, no licence: read for facts only, nothing copied) | Kunos' C declaration of the three structs | `#pragma pack(4)`; the array length of `trackConfiguration` ([33]), which the PDF does not print. The reproduced copies predate v1.8.12 in places (no `gapAhead`/`gapBehind`, a trailing `reserved` block): the PDF wins wherever they differ |
| [P] `rrennoir/PyAccSharedMemory` `src/pyaccsharedmemory.py` (MIT) | A community reader | Cross-check only: it reads `trackConfiguration` as 33 wide chars + 2 padding bytes and agrees with every size here |
| [R] `docs/research/protocols/windows-shm-relay.md` §4.3 (2026-10-10) | Pitwall's earlier relay research: offsets laid out from `devology-uk/sim-racing-sdk` (MIT, C#) with `Pack = 4` | Cross-check only: its offsets equal §4's for every field it lists |
| [E] Ed's patches (`acc-adapter-for-james.patch`, `body-slip-and-cadence-for-james.patch`, 2026-10-14) | Ed's adapter, built from two community ports (alexanderzobnin/grafana-simracing-telemetry and Dekadee/accshm, both MIT) and his live sessions | The starting point of `adapter.py`; his live observations (§6). His layouts are superseded by [K] (§6.12) |

No GPL code was read. Kunos' document states no licence; the field declarations are the interface's facts and the
descriptions here are paraphrased.

---

## 2. The interface

- **Mappings.** ACC creates `Local\acpmf_physics`, `Local\acpmf_graphics` and `Local\acpmf_static` (the `Local\`
  prefix is the per-session namespace: a reader must run in the same Windows logon session as the game, not as a
  service). The names are the same as the original Assetto Corsa's, with ACC's own layouts.
- **Open, never create.** A reader must *open* existing mappings (`OpenFileMappingW(FILE_MAP_READ, FALSE, name)` +
  `MapViewOfFile`) and fail when they are absent. Creating them (`CreateFileMapping`, or Python's
  `mmap.mmap(-1, size, tagname=...)`, which calls it) makes a zero-filled page under ACC's name when the game is not
  running - a reader would then decode blank pages forever - and, if pitwall starts before the game, the game (and
  every other tool) would find a mapping it did not size.
- **Sizes and packing.** Kunos' header wraps the structs in `#pragma pack(4)`. Every member is 4 bytes wide except the
  `wchar_t` strings (2 bytes per code unit), so the only padding is 2 bytes after each odd-length string that is
  followed by a 4-byte member. Totals: Physics 800, Graphics 1588, Static 820 (all multiples of 4: no trailing
  padding). A reader maps and copies exactly these sizes; a later build that appends fields leaves this prefix as it
  is. (An older reproduced copy of [H] ends Graphics at `strategyTyreSet` followed by a reserved block: builds
  before v1.8.12 may differ after that field.)
- **Updates.** Physics "change at each graphic step" and Graphics are "updated at each graphical step": both
  get a new `packetId` when they are rewritten. Static is "initialized when the instance starts and never changes
  until the instance is closed". Whether a paused game keeps rewriting Physics is not documented. A reader that
  forwards a page only when its `packetId` (Static: its bytes) changed forwards nothing from a closed game and
  nothing new from a game that stopped writing.
- **Strings.** `wchar_t[N]` is UTF-16LE, NUL-terminated inside the fixed buffer.
- **Colour legend.** The PDF prints each row green ("field is working as intended") or red ("field is not used by
  ACC"); a cyan highlight marks entries new since the previous build - no row in v1.8.12's tables carries it.
  Fields marked `*`, `**`, `***` are "double fields": the same quantity twice (`TyreCoreTemp`/`tyreTemp`,
  `tc`/`tcinAction`, `abs`/`absInAction`, `completedLaps`/`numberOfLaps`); in each pair the PDF marks one green and
  (except for the lap counters) the other red.

---

## 3. How to read the tables

| Column | Meaning |
|---|---|
| # | Position in Kunos' list (1-based) |
| Offset | Byte offset from the start of the page, computed with the rules in §2 |
| Type | Kunos' C type, normalised to lower case (`ACC_*` are 4-byte enums, §5) |
| Field | Kunos' name exactly, spelling included (`secondaryDisplyIndex`, `TCCUT`, `Clock`...) |
| Array | Array dimensions; † = not printed in the PDF (§6.10) |
| Kunos | `used` (green in the PDF) or `unused` (red: "not used" / "not shown" in ACC) |
| Meaning | Kunos' description in our own words; "unit not stated" where Kunos gives none |
| Pitwall | What `adapters/acc/adapter.py` does with it (`-` = not read). `CarFrame.` is implied for bare field names |

---

## 4. Layouts

### 4.1 SPageFilePhysics (800 bytes)

| # | Offset | Type | Field | Array | Kunos | Meaning (our words) | Pitwall |
|---|---|---|---|---|---|---|---|
| 1 | 0 | int | packetId |  | used | Step counter of this page; a new value means new data | `CarFrame.frame_id` |
| 2 | 4 | float | gas |  | used | Throttle pedal, 0 (released) to 1 (full) | `throttle` |
| 3 | 8 | float | brake |  | used | Brake pedal, 0 to 1 | `brake` |
| 4 | 12 | float | fuel |  | used | Fuel left; Kunos gives the unit as kilograms | - |
| 5 | 16 | int | gear |  | used | Selected gear (encoding not stated; see §6) | `gear` (value - 1) |
| 6 | 20 | int | rpm |  | used | Engine speed, rev/min | `rpm` |
| 7 | 24 | float | steerAngle |  | used | Steering input, normalised -1 to +1 (sign not stated; see §6) | `steering` (negated) |
| 8 | 28 | float | speedKmh |  | used | Car speed, km/h | `speed_kph` |
| 9 | 32 | float | velocity | [3] | used | Velocity vector, world (global) axes; unit not stated | - |
| 10 | 44 | float | accG | [3] | used | Acceleration vector; Kunos says world (global) axes; unit not stated | `g_lat`/`g_vert`/`g_lon` once checked (§6) |
| 11 | 56 | float | wheelSlip | [4] | used | Per-tyre slip (quantity not defined further) | - |
| 12 | 72 | float | wheelLoad | [4] | unused | Per-wheel load | - |
| 13 | 88 | float | wheelPressure | [4] | used | Per-tyre pressure; unit not stated | `tyre_pressure_psi` (range-checked) |
| 14 | 104 | float | wheelAngularSpeed | [4] | used | Per-wheel rotation speed, rad/s | - |
| 15 | 120 | float | tyreWear | [4] | unused | Per-tyre wear | - |
| 16 | 136 | float | tyreDirtyLevel | [4] | unused | Dirt on each tyre's surface | - |
| 17 | 152 | float | TyreCoreTemp | [4] | used | Per-tyre rubber core temperature; unit not stated (double field with `tyreTemp`) | `tyre_core_temp_c` |
| 18 | 168 | float | camberRAD | [4] | unused | Per-wheel camber, radians | - |
| 19 | 184 | float | suspensionTravel | [4] | used | Per-wheel suspension travel; unit not stated | - |
| 20 | 200 | float | drs |  | unused | DRS state | - |
| 21 | 204 | float | tc |  | used | Traction control intervening (double field with `tcinAction`) | - |
| 22 | 208 | float | heading |  | used | Car yaw orientation; unit and zero not stated | - |
| 23 | 212 | float | pitch |  | used | Car pitch orientation; unit not stated | - |
| 24 | 216 | float | roll |  | used | Car roll orientation; unit not stated | - |
| 25 | 220 | float | cgHeight |  | unused | Height of the centre of gravity | - |
| 26 | 224 | float | carDamage | [5] | used | Damage by zone: front, rear, left, right, centre | - |
| 27 | 244 | int | numberOfTyresOut |  | unused | How many tyres are off the track | - |
| 28 | 248 | int | pitLimiterOn |  | used | Pit speed limiter engaged | - |
| 29 | 252 | float | abs |  | used | ABS intervening (double field with `absInAction`) | - |
| 30 | 256 | float | kersCharge |  | unused | (AC heritage, unused) | - |
| 31 | 260 | float | kersInput |  | unused | (AC heritage, unused) | - |
| 32 | 264 | int | autoshifterOn |  | used | Automatic gearbox engaged | - |
| 33 | 268 | float | rideHeight | [2] | unused | Ride height, front and rear | - |
| 34 | 276 | float | turboBoost |  | used | Turbo boost level | - |
| 35 | 280 | float | ballast |  | unused | Ballast (kg); not implemented | - |
| 36 | 284 | float | airDensity |  | unused | Air density | - |
| 37 | 288 | float | airTemp |  | used | Air temperature; unit not stated | `SessionInfo.weather.air_temp_c` |
| 38 | 292 | float | roadTemp |  | used | Track surface temperature; unit not stated | `SessionInfo.weather.track_temp_c` |
| 39 | 296 | float | localAngularVel | [3] | used | Angular velocity vector in the car's own axes; unit and axis order not stated | `yaw_rate_rps` once checked (§6) |
| 40 | 308 | float | finalFF |  | used | Force-feedback output signal | - |
| 41 | 312 | float | performanceMeter |  | unused | (AC heritage, unused) | - |
| 42 | 316 | int | engineBrake |  | unused | (AC heritage, unused) | - |
| 43 | 320 | int | ersRecoveryLevel |  | unused | (AC heritage, unused) | - |
| 44 | 324 | int | ersPowerLevel |  | unused | (AC heritage, unused) | - |
| 45 | 328 | int | ersHeatCharging |  | unused | (AC heritage, unused) | - |
| 46 | 332 | int | ersIsCharging |  | unused | (AC heritage, unused) | - |
| 47 | 336 | float | kersCurrentKJ |  | unused | (AC heritage, unused) | - |
| 48 | 340 | int | drsAvailable |  | unused | (AC heritage, unused) | - |
| 49 | 344 | int | drsEnabled |  | unused | (AC heritage, unused) | - |
| 50 | 348 | float | brakeTemp | [4] | used | Per-wheel brake disc temperature; unit not stated | `brake_temp_c` |
| 51 | 364 | float | clutch |  | used | Clutch pedal input, 0 to 1 | `clutch` |
| 52 | 368 | float | tyreTempI | [4] | unused | Inner tread temperature (not provided by ACC) | - |
| 53 | 384 | float | tyreTempM | [4] | unused | Middle tread temperature (not provided by ACC) | - |
| 54 | 400 | float | tyreTempO | [4] | unused | Outer tread temperature (not provided by ACC) | - |
| 55 | 416 | int | isAIControlled |  | used | The AI is driving the player's car | - |
| 56 | 420 | float | tyreContactPoint | [4][3] | used | Per-tyre contact point, world axes, [wheel][x,y,z] | - |
| 57 | 468 | float | tyreContactNormal | [4][3] | used | Per-tyre contact-patch normal, [wheel][x,y,z] | - |
| 58 | 516 | float | tyreContactHeading | [4][3] | used | Per-tyre contact-patch heading, [wheel][x,y,z] | - |
| 59 | 564 | float | brakeBias |  | used | Front brake bias; the dash value needs a per-car offset (Appendix 4) | - |
| 60 | 568 | float | localVelocity | [3] | used | Velocity vector in the car's own axes; unit and axis order not stated | `body_slip_rad` once checked (§6) |
| 61 | 580 | int | P2PActivation |  | unused | (push-to-pass, unused) | - |
| 62 | 584 | int | P2PStatus |  | unused | (push-to-pass, unused) | - |
| 63 | 588 | float | currentMaxRpm |  | unused | Maximum engine speed | - |
| 64 | 592 | float | mz | [4] | unused | Per-tyre self-aligning torque (not provided by ACC) | - |
| 65 | 608 | float | fx | [4] | unused | Per-tyre longitudinal force (not provided by ACC) | - |
| 66 | 624 | float | fy | [4] | unused | Per-tyre lateral force (not provided by ACC) | - |
| 67 | 640 | float | slipRatio | [4] | used | Per-tyre slip ratio (Kunos adds 'in radians'; sign and scale not stated) | `wheel_slip_ratio` once checked (§6) |
| 68 | 656 | float | slipAngle | [4] | used | Per-tyre slip angle; unit not stated | `wheel_slip_angle_rad` once checked (§6) |
| 69 | 672 | int | tcinAction |  | unused | Traction control intervening (integer twin of tc) (double field with `tc`) | - |
| 70 | 676 | int | absInAction |  | unused | ABS intervening (integer twin of abs) (double field with `abs`) | - |
| 71 | 680 | float | suspensionDamage | [4] | unused | Per-wheel suspension damage | - |
| 72 | 696 | float | tyreTemp | [4] | unused | Per-tyre core temperature (twin of TyreCoreTemp) (double field with `TyreCoreTemp`) | - |
| 73 | 712 | float | waterTemp |  | used | Coolant temperature; unit not stated | - |
| 74 | 716 | float | brakePressure | [4] | used | Per-wheel brake pressure (scale per car: Appendix 3) | - |
| 75 | 732 | int | frontBrakeCompound |  | used | Front brake pad compound | - |
| 76 | 736 | int | rearBrakeCompound |  | used | Rear brake pad compound | - |
| 77 | 740 | float | padLife | [4] | used | Per-wheel brake pad wear | - |
| 78 | 756 | float | discLife | [4] | used | Per-wheel brake disc wear | - |
| 79 | 772 | int | ignitionOn |  | used | Ignition switched on | - |
| 80 | 776 | int | starterEngineOn |  | used | Starter switch on | - |
| 81 | 780 | int | isEngineRunning |  | used | Engine running | - |
| 82 | 784 | float | kerbVibration |  | used | Kerb vibration sent to force feedback | - |
| 83 | 788 | float | slipVibrations |  | used | Slip vibration sent to force feedback | - |
| 84 | 792 | float | gVibrations |  | used | g-force vibration sent to force feedback | - |
| 85 | 796 | float | absVibrations |  | used | ABS vibration sent to force feedback | - |

### 4.2 SPageFileGraphic (1588 bytes)

| # | Offset | Type | Field | Array | Kunos | Meaning (our words) | Pitwall |
|---|---|---|---|---|---|---|---|
| 1 | 0 | int | packetId |  | used | Step counter of this page; a new value means new data | - |
| 2 | 4 | ACC_STATUS | status |  | used | Game state (ACC_STATUS: off, replay, live, pause) | sessions, `PAUSED` / `REPLAY_OR_SPECTATING` |
| 3 | 8 | ACC_SESSION_TYPE | session |  | used | Session kind (ACC_SESSION_TYPE) | `SessionInfo.session_type` |
| 4 | 12 | wchar_t | currentTime | [15] | used | Current lap time as display text | - |
| 5 | 42 | wchar_t | lastTime | [15] | used | Last lap time as display text | - |
| 6 | 72 | wchar_t | bestTime | [15] | used | Best lap time as display text | - |
| 7 | 102 | wchar_t | split | [15] | used | Last split as display text | - |
| 8 | 132 | int | completedLaps |  | used | Laps completed (double field with `numberOfLaps`) | `lap_number` (+ 1), lap completions |
| 9 | 136 | int | position |  | used | Player's position in the classification | `race_position` |
| 10 | 140 | int | iCurrentTime |  | used | Current lap time, ms | `current_lap_time_ms` |
| 11 | 144 | int | iLastTime |  | used | Last lap time, ms | `last_lap_time_ms`, lap time |
| 12 | 148 | int | iBestTime |  | used | Best lap time, ms | `SessionInfo.extra['best_lap_ms']` |
| 13 | 152 | float | sessionTimeLeft |  | used | Time left in the session; unit not stated | - |
| 14 | 156 | float | distanceTraveled |  | used | Distance covered in the current stint; unit not stated | - |
| 15 | 160 | int | isInPit |  | used | Car is in the pit (stopped / pitting) | `pit_status` 2 |
| 16 | 164 | int | currentSectorIndex |  | used | Current sector (base not stated) | `sector` (checked against sectorCount) |
| 17 | 168 | int | lastSectorTime |  | used | Last sector time, ms | - |
| 18 | 172 | int | numberOfLaps |  | used | Laps completed (twin of completedLaps) (double field with `completedLaps`) | - |
| 19 | 176 | wchar_t | tyreCompound | [33] | used | Tyre compound in use, as text | - |
| 20 | 244 | float | replayTimeMultiplier |  | unused | Replay speed | - |
| 21 | 248 | float | normalizedCarPosition |  | used | Position along the track spline, 0.0 at the start to 1.0 at the finish | `lap_distance_m` (x track length) |
| 22 | 252 | int | activeCars |  | used | How many cars are on track | bounds the carID search |
| 23 | 256 | float | carCoordinates | [60][3] | used | World position of each car on track, [car][x,y,z]; unit not stated | `pos_x_m`/`pos_y_m`/`pos_z_m` (player's row) |
| 24 | 976 | int | carID | [60] | used | Id of each car on track (same order as carCoordinates) | finds the player's row |
| 25 | 1216 | int | playerCarID |  | used | Id of the player's car | finds the player's row |
| 26 | 1220 | float | penaltyTime |  | used | Penalty time still to serve | - |
| 27 | 1224 | ACC_FLAG_TYPE | flag |  | used | Flag shown to the player (ACC_FLAG_TYPE) | - |
| 28 | 1228 | ACC_PENALTY_TYPE | penalty |  | used | Penalty given to the player (ACC_PENALTY_TYPE) | - |
| 29 | 1232 | int | idealLineOn |  | used | Racing-line aid shown | - |
| 30 | 1236 | int | isInPitLane |  | used | Car is in the pit lane | `pit_status` 1 |
| 31 | 1240 | float | surfaceGrip |  | used | Friction coefficient of the racing line | - |
| 32 | 1244 | int | mandatoryPitDone |  | used | The mandatory stop is done | - |
| 33 | 1248 | float | windSpeed |  | used | Wind speed, m/s | - |
| 34 | 1252 | float | windDirection |  | used | Wind direction, radians | - |
| 35 | 1256 | int | isSetupMenuVisible |  | used | The setup screen is open | - |
| 36 | 1260 | int | mainDisplayIndex |  | used | Page shown on the car's main display (per car: Appendix 1) | - |
| 37 | 1264 | int | secondaryDisplyIndex |  | used | Page shown on the car's secondary display | - |
| 38 | 1268 | int | TC |  | used | Traction control level (setting) | `traction_control` |
| 39 | 1272 | int | TCCUT |  | used | Traction control cut level (setting) | - |
| 40 | 1276 | int | EngineMap |  | used | Engine map (setting) | - |
| 41 | 1280 | int | ABS |  | used | ABS level (setting) | - |
| 42 | 1284 | float | fuelXLap |  | used | Average fuel used per lap, litres | - |
| 43 | 1288 | int | rainLights |  | used | Rain light on | - |
| 44 | 1292 | int | flashingLights |  | used | Headlight flash on | - |
| 45 | 1296 | int | lightsStage |  | used | Headlight stage | - |
| 46 | 1300 | float | exhaustTemperature |  | used | Exhaust temperature | - |
| 47 | 1304 | int | wiperLV |  | used | Wiper stage | - |
| 48 | 1308 | int | driverStintTotalTimeLeft |  | used | Driving time the driver has left in the race, ms | - |
| 49 | 1312 | int | driverStintTimeLeft |  | used | Driving time the driver has left in this stint, ms | - |
| 50 | 1316 | int | rainTyres |  | used | Wet tyres fitted | `tyre_compound` (wet / dry) |
| 51 | 1320 | int | sessionIndex |  | used | Index of the session (no description in the PDF) | session boundaries |
| 52 | 1324 | float | usedFuel |  | used | Fuel used since the last refuelling; unit not stated | - |
| 53 | 1328 | wchar_t | deltaLapTime | [15] | used | Live delta as display text | - |
| 54 | 1360 | int | iDeltaLapTime |  | used | Live delta, ms | - |
| 55 | 1364 | wchar_t | estimatedLapTime | [15] | used | Estimated lap time (the PDF swaps this description with the next one) | - |
| 56 | 1396 | int | iEstimatedLapTime |  | used | Estimated lap time, ms (description swapped in the PDF) | - |
| 57 | 1400 | int | isDeltaPositive |  | used | Delta is positive (1) or negative (0) | - |
| 58 | 1404 | int | iSplit |  | used | Last split, ms | - |
| 59 | 1408 | int | isValidLap |  | used | The current lap still counts for timing | `lap_invalid`, completion validity |
| 60 | 1412 | float | fuelEstimatedLaps |  | used | Laps the fuel on board lasts | - |
| 61 | 1416 | wchar_t | trackStatus | [33] | used | Track state as text | - |
| 62 | 1484 | int | missingMandatoryPits |  | used | Mandatory stops still to make | - |
| 63 | 1488 | float | Clock |  | used | Time of day, seconds | - |
| 64 | 1492 | int | directionLightsLeft |  | used | Left indicator on | - |
| 65 | 1496 | int | directionLightsRight |  | used | Right indicator on | - |
| 66 | 1500 | int | GlobalYellow |  | used | Yellow flag out (anywhere) | - |
| 67 | 1504 | int | GlobalYellow1 |  | used | Yellow flag in sector 1 | - |
| 68 | 1508 | int | GlobalYellow2 |  | used | Yellow flag in sector 2 | - |
| 69 | 1512 | int | GlobalYellow3 |  | used | Yellow flag in sector 3 | - |
| 70 | 1516 | int | GlobalWhite |  | used | White flag out | - |
| 71 | 1520 | int | GlobalGreen |  | used | Green flag out | - |
| 72 | 1524 | int | GlobalChequered |  | used | Chequered flag out | - |
| 73 | 1528 | int | GlobalRed |  | used | Red flag out | - |
| 74 | 1532 | int | mfdTyreSet |  | used | Tyre set chosen on the pit screen (MFD) | - |
| 75 | 1536 | float | mfdFuelToAdd |  | used | Fuel to add, chosen on the MFD | - |
| 76 | 1540 | float | mfdTyrePressureLF |  | used | Front-left pressure chosen on the MFD | - |
| 77 | 1544 | float | mfdTyrePressureRF |  | used | Front-right pressure chosen on the MFD | - |
| 78 | 1548 | float | mfdTyrePressureLR |  | used | Rear-left pressure chosen on the MFD | - |
| 79 | 1552 | float | mfdTyrePressureRR |  | used | Rear-right pressure chosen on the MFD | - |
| 80 | 1556 | ACC_TRACK_GRIP_STATUS | trackGripStatus |  | used | Track grip (ACC_TRACK_GRIP_STATUS) | - |
| 81 | 1560 | ACC_RAIN_INTENSITY | rainIntensity |  | used | Rain now (ACC_RAIN_INTENSITY) | `SessionInfo.weather.condition` |
| 82 | 1564 | ACC_RAIN_INTENSITY | rainIntensityIn10min |  | used | Rain forecast in 10 minutes | - |
| 83 | 1568 | ACC_RAIN_INTENSITY | rainIntensityIn30min |  | used | Rain forecast in 30 minutes | - |
| 84 | 1572 | int | currentTyreSet |  | used | Tyre set fitted | - |
| 85 | 1576 | int | strategyTyreSet |  | used | Next tyre set in the strategy | - |
| 86 | 1580 | int | gapAhead |  | used | Gap to the car ahead, ms | - |
| 87 | 1584 | int | gapBehind |  | used | Gap to the car behind, ms | - |

### 4.3 SPageFileStatic (820 bytes)

| # | Offset | Type | Field | Array | Kunos | Meaning (our words) | Pitwall |
|---|---|---|---|---|---|---|---|
| 1 | 0 | wchar_t | smVersion | [15] | used | Version of the shared-memory layout, as text | `SessionInfo.extra` |
| 2 | 30 | wchar_t | acVersion | [15] | used | Game version, as text | `SessionInfo.extra` |
| 3 | 60 | int | numberOfSessions |  | used | Sessions in this event | - |
| 4 | 64 | int | numCars |  | used | Cars in this event | - |
| 5 | 68 | wchar_t | carModel | [33] | used | Player's car, as Kunos' id (Appendix 2) | `car_id`, `car_name` |
| 6 | 134 | wchar_t | track | [33] | used | Track, as text | `track_id`, `track_name` |
| 7 | 200 | wchar_t | playerName | [33] | used | Player's first name (personal data) | - |
| 8 | 266 | wchar_t | playerSurname | [33] | used | Player's surname (personal data) | - |
| 9 | 332 | wchar_t | playerNick | [33] | used | Player's nickname (personal data) | - |
| 10 | 400 | int | sectorCount |  | used | Number of sectors | checks `sector` |
| 11 | 404 | float | maxTorque |  | unused | Peak engine torque | - |
| 12 | 408 | float | maxPower |  | unused | Peak engine power | - |
| 13 | 412 | int | maxRpm |  | used | Engine speed limit, rev/min | `max_rpm` |
| 14 | 416 | float | maxFuel |  | used | Fuel tank capacity; unit not stated | - |
| 15 | 420 | float | suspensionMaxTravel | [4] | unused | Per-wheel maximum suspension travel | - |
| 16 | 436 | float | tyreRadius | [4] | unused | Per-wheel tyre radius | - |
| 17 | 452 | float | maxTurboBoost |  | unused | Maximum turbo boost | - |
| 18 | 456 | float | deprecated_1 |  | unused | (deprecated, no description) | - |
| 19 | 460 | float | deprecated_2 |  | unused | (deprecated, no description) | - |
| 20 | 464 | int | penaltiesEnabled |  | used | Penalties switched on | - |
| 21 | 468 | float | aidFuelRate |  | used | Fuel consumption multiplier | - |
| 22 | 472 | float | aidTireRate |  | used | Tyre wear multiplier | - |
| 23 | 476 | float | aidMechanicalDamage |  | used | Mechanical damage multiplier | - |
| 24 | 480 | float | AllowTyreBlankets |  | used | Tyre blankets allowed (not in the endurance series) | - |
| 25 | 484 | float | aidStability |  | used | Stability aid level | - |
| 26 | 488 | int | aidAutoclutch |  | used | Automatic clutch aid on | - |
| 27 | 492 | int | aidAutoBlip |  | used | Automatic throttle blip (always on in ACC) | - |
| 28 | 496 | int | hasDRS |  | unused | (AC heritage, unused) | - |
| 29 | 500 | int | hasERS |  | unused | (AC heritage, unused) | - |
| 30 | 504 | int | hasKERS |  | unused | (AC heritage, unused) | - |
| 31 | 508 | float | kersMaxJ |  | unused | (AC heritage, unused) | - |
| 32 | 512 | int | engineBrakeSettingsCount |  | unused | (AC heritage, unused) | - |
| 33 | 516 | int | ersPowerControllerCount |  | unused | (AC heritage, unused) | - |
| 34 | 520 | float | trackSplineLength |  | unused | Length of the track spline | track length only if plausible (§6) |
| 35 | 524 | wchar_t | trackConfiguration | [33] † | unused | Track layout name | - |
| 36 | 592 | float | ersMaxJ |  | unused | (AC heritage, unused) | - |
| 37 | 596 | int | isTimedRace |  | unused | Race is timed rather than lap-limited | - |
| 38 | 600 | int | hasExtraLap |  | unused | Race has an extra lap | - |
| 39 | 604 | wchar_t | carSkin | [33] | unused | Car livery | - |
| 40 | 672 | int | reversedGridPositions |  | unused | Reversed-grid positions | - |
| 41 | 676 | int | PitWindowStart |  | used | Pit window opens | - |
| 42 | 680 | int | PitWindowEnd |  | used | Pit window closes | - |
| 43 | 684 | int | isOnline |  | used | Multiplayer session | `SessionInfo.network_game` |
| 44 | 688 | wchar_t | dryTyresName | [33] | used | Name of the dry tyres | - |
| 45 | 754 | wchar_t | wetTyresName | [33] | used | Name of the wet tyres | - |

---

## 5. Enums

| Enum | Value | Name |
|---|---|---|
| ACC_STATUS | 0 | ACC_OFF |
| ACC_STATUS | 1 | ACC_REPLAY |
| ACC_STATUS | 2 | ACC_LIVE |
| ACC_STATUS | 3 | ACC_PAUSE |
| ACC_SESSION_TYPE | -1 | ACC_UNKNOWN |
| ACC_SESSION_TYPE | 0 | ACC_PRACTICE |
| ACC_SESSION_TYPE | 1 | ACC_QUALIFY |
| ACC_SESSION_TYPE | 2 | ACC_RACE |
| ACC_SESSION_TYPE | 3 | ACC_HOTLAP |
| ACC_SESSION_TYPE | 4 | ACC_TIMEATTACK |
| ACC_SESSION_TYPE | 5 | ACC_DRIFT |
| ACC_SESSION_TYPE | 6 | ACC_DRAG |
| ACC_SESSION_TYPE | 7 | ACC_HOTSTINT |
| ACC_SESSION_TYPE | 8 | ACC_HOTSTINTSUPERPOLE |
| ACC_FLAG_TYPE | 0 | ACC_NO_FLAG |
| ACC_FLAG_TYPE | 1 | ACC_BLUE_FLAG |
| ACC_FLAG_TYPE | 2 | ACC_YELLOW_FLAG |
| ACC_FLAG_TYPE | 3 | ACC_BLACK_FLAG |
| ACC_FLAG_TYPE | 4 | ACC_WHITE_FLAG |
| ACC_FLAG_TYPE | 5 | ACC_CHECKERED_FLAG |
| ACC_FLAG_TYPE | 6 | ACC_PENALTY_FLAG |
| ACC_FLAG_TYPE | 7 | ACC_GREEN_FLAG |
| ACC_FLAG_TYPE | 8 | ACC_ORANGE_FLAG |
| ACC_TRACK_GRIP_STATUS | 0 | ACC_GREEN |
| ACC_TRACK_GRIP_STATUS | 1 | ACC_FAST |
| ACC_TRACK_GRIP_STATUS | 2 | ACC_OPTIMUM |
| ACC_TRACK_GRIP_STATUS | 3 | ACC_GREASY |
| ACC_TRACK_GRIP_STATUS | 4 | ACC_DAMP |
| ACC_TRACK_GRIP_STATUS | 5 | ACC_WET |
| ACC_TRACK_GRIP_STATUS | 6 | ACC_FLOODED |
| ACC_RAIN_INTENSITY | 0 | ACC_NO_RAIN |
| ACC_RAIN_INTENSITY | 1 | ACC_DRIZZLE |
| ACC_RAIN_INTENSITY | 2 | ACC_LIGHT_RAIN |
| ACC_RAIN_INTENSITY | 3 | ACC_MEDIUM_RAIN |
| ACC_RAIN_INTENSITY | 4 | ACC_HEAVY_RAIN |
| ACC_RAIN_INTENSITY | 5 | ACC_THUNDERSTORM |
| ACC_WHEELS_TYPE | 0 | ACC_FrontLeft |
| ACC_WHEELS_TYPE | 1 | ACC_FrontRight |
| ACC_WHEELS_TYPE | 2 | ACC_RearLeft |
| ACC_WHEELS_TYPE | 3 | ACC_RearRight |

`ACC_PENALTY_TYPE` (Graphics `penalty`) runs from 0 (none) to 21: drive-through / stop-and-go 10, 20 or 30 s /
disqualification / best lap removed, each for cutting (1-6) and pit speeding (7-12); then ignored mandatory pit (13),
post-race time (14), disqualification for trolling, pit entry, pit exit or wrong way (15-18), and three driver-stint
penalties (19-21). Pitwall does not decode it (§6.11). Kunos' sample header also defines a status value -1 ("not
running") that the PDF does not list; pitwall treats any value other than replay / live / pause as off.

The appendices list, per car of the game up to the 2022 Challengers Pack: the dash pages (`mainDisplayIndex`, App. 1),
the `carModel` id and the car's name (App. 2: pitwall's `packets.CAR_MODELS`, used for `car_name`), a per-car
coefficient for `brakePressure` (App. 3), the dash offset of `brakeBias` (App. 4), the maximum steering angle in
degrees (App. 5), the broadcasting `CarModelId` (App. 6) and the rev limit (App. 7). Cars released after the PDF are
not listed.

---

## 6. Where the document is silent or inconsistent - and what pitwall does

Pitwall's rule: a field Kunos does not define clearly, or that cannot be mapped honestly, stays `None`. Where a
reading can be *checked* while the car is driven, the adapter checks it and maps the field only once the evidence is
unambiguous (60 observations, one answer winning 9 to 1); those fields are `UNVERIFIED` in `ACC_INFO.fields` until a
recording confirms them, and `SessionInfo.extra['acc_evidence']` shows the counts.

1. **Gear encoding.** The PDF says "current gear" only. Pitwall uses 0 = reverse, 1 = neutral, 2 = first (the
   original Assetto Corsa's convention, also stated in Kunos' AC EVO document: `windows-shm-relay.md` §4.3.2); Ed's
   tester report (Brands Hatch, 2026-10-13): the raw value shown as a gear read one too high. `gear = raw - 1`.
2. **Steering sign.** The PDF documents `steerAngle` as the steering *input* from -1 to +1 but not its sign. Ed's
   tester report (Brands Hatch, 2026-10-14): unnegated, Brands Hatch's first corner (a right-hander) was drawn as a
   left on the track map. Pitwall's convention is -1 = full left .. +1 = full right, so `steering = -steerAngle`.
   (Ed's range at Spa, -0.58 .. +0.77, fits a normalised input.)
3. **Fuel unit.** The PDF gives `fuel` in kilograms, but its own `fuelXLap` is in litres, `maxFuel` / `usedFuel` /
   `mfdFuelToAdd` have no unit, and the game shows litres. Not mapped (`fuel_kg` / `fuel_litres` = `None`) until one
   recording compares `fuel` with the HUD. `fuelEstimatedLaps` (laps the fuel on board lasts) is not mapped either:
   Pitwall's `fuel_remaining_laps_game` is F1's MFD figure, the fuel margin at the finish in laps, and the race
   strategy reads it so; ACC's figure is another quantity, so mapping it there would show a wrong margin.
4. **`accG` axes.** The PDF says "acceleration vector in global coordinates" with no unit or axis order; Ed's
   adapter (after a community port) read it as the car's own axes in g (x lateral, y vertical, z longitudinal),
   and Kunos' AC EVO document lists `[lateral, longitudinal, vertical]` for that game (`windows-shm-relay.md`
   §4.3.2). Pitwall maps `g_lon` only after `accG[2]` has
   matched the measured change of speed in sign and size (g), and `g_lat` / `g_vert` only after `|accG[0]|` g has also
   matched speed x yaw rate (centripetal acceleration). A world-axis reading would fail both checks.
5. **`localAngularVel`, `localVelocity`.** "Local coordinates" with no unit or axis order. The yaw rate is
   `localAngularVel[1]` with the sign that agrees with the steering in normal cornering (pitwall: + = turning right)
   and its unit (rad/s) confirmed by the centripetal check. Body slip is `atan2(lateral, forward)` of
   `localVelocity`, with `localVelocity[2]` checked to be the forward speed (it matches `speedKmh`) and the lateral
   direction taken from the yaw sign (a raw yaw that is + for right turns means left-handed axes: x points right). Its
   sign follows F1's: the same as the yaw rate when the tail steps out. `velocity` (world axes) and
   `heading` / `pitch` / `roll` (no unit, no zero direction) are not mapped. Ed's report that `velocity` behaves like
   local axes is noted; pitwall follows Kunos and uses `localVelocity`.
6. **`slipAngle` and `slipRatio`.** No unit for the slip angle; the slip ratio is described "in radians" (a ratio has
   no angle unit) with no sign convention. The slip angle is mapped once front slip angles in loaded corners look
   like radians (0.005-0.35) or like degrees (0.5-20; converted); the slip ratio once the front tyres under braking
   and the rear tyres under power both show one sign convention (pitwall: < 0 braking, > 0 wheelspin).
7. **Temperatures and pressures.** No units are printed. Temperatures are taken as degrees C (AC/ACC convention;
   `TyreCoreTemp` -> `tyre_core_temp_c`, `brakeTemp` -> `brake_temp_c`, `airTemp` / `roadTemp` -> weather), with
   plausibility ranges. `wheelPressure` is taken as psi only when all four values lie in 5-60 (bar values sit below
   5, kPa above 100). The tread temperatures `tyreTempI/M/O` are "not shown in ACC", so `tyre_surface_temp_c` and
   `tyre_inner_temp_c` stay `None`; `tyre_core_temp_c` is a field of its own.
8. **TC and ABS.** `tc` / `abs` (green) report TC / ABS *intervening*; their integer twins `tcinAction` /
   `absInAction` are red. Graphics `TC` / `ABS` are the *level* settings. Pitwall's `traction_control` is the TC
   level (`TC`, ACC's own scale); `abs_active` means "the ABS assist is on" in pitwall (lock-up and technique logic
   rely on that), and neither ACC field says that (the level's "off" value is not documented): not mapped.
9. **Track length / lap distance.** `trackSplineLength` is "not used in ACC" (Ed's report: no float in a real Static
   page held a plausible length). Lap distance = `normalizedCarPosition` (0.0 at the start, 1.0 at the finish) x a
   length from `tracks.py` (Ed's table of 25 circuits, three checked), or `trackSplineLength` should the game ever
   fill it with a value within 3 % of the table (or 1-30 km for an unlisted track). Unlisted tracks: no distance.
10. **`trackConfiguration` length.** The PDF prints `wchar_t trackConfiguration` with no array length; Kunos' header
    declares `[33]` ([P] reads 33 too). That fixes the Static size at 820 and the offsets of `ersMaxJ` ..
    `wetTyresName`; pitwall reads none of those, so a different length would not change anything pitwall decodes.
11. **Flags and penalties.** `flag` and `penalty` are green in the PDF, but a comment in Kunos' sample header says
    "flag and penalty currently not working". Not mapped until a recording shows them changing.
12. **Ed's layouts** (superseded): his Static had no padding after `playerNick` and one `tyreRadius` float where
    Kunos has four, so his `sectorCount` / `maxRpm` sat at 398 / 410 (Kunos: 400 / 412) and every field after
    `tyreRadius` 14 bytes early; his Physics stopped after `tyreTemp` (712 of 800 bytes) and his Graphics after
    `strategyTyreSet` (1580 of 1588). The fields he read before those points sit at Kunos' offsets, which is why his
    live checks of the leading Physics scalars and of `track` / `carModel` hold. His note that a live scan found
    `sectorCount` 3 and `maxRpm` 7700 "on this layout's predicted offsets" cannot hold for both layouts (a 2-byte
    shift reads 3 as 196,608); pitwall follows Kunos' header (`pack(4)`, as `[P]` and `[R]` also do) and checks it at
    runtime: Static `maxRpm` must equal Appendix 7's value for the car (7700 for the McLaren 720S GT3),
    `SessionInfo.extra['static_layout_check']`.
13. **Smaller inconsistencies.** The descriptions of `estimatedLapTime` and `iEstimatedLapTime` are swapped (one says
    "in milliseconds" on the string); `sessionIndex` has no description; `brakePressure` points to "Appendix 2" but
    the coefficients are in Appendix 3; `Float` / `Int` are capitalised in two rows. The sample header ([H]) spells
    several names differently (`rpms`, `wheelsPressure`, `tyreCoreTemperature`, `autoShifterOn`, `P2PActivations`,
    `diskLife`, `secondaryDisplayIndex`, `TCCut`, `mfdTyrePressureFL`..., `rainIntensity10min`,
    `aidAllowTyreBlankets`, `trackSPlineLength`) and types two differently (`int currentMaxRpm`,
    `int aidAllowTyreBlankets`); both are 4 bytes, so offsets do not change. Pitwall follows the PDF.

---

## 7. Pitwall's framing (not part of ACC)

The reader (`pitwall.ingest.acc_shm_reader`) copies one whole page per snapshot and prefixes a 4-byte ASCII tag, so
a snapshot travels through the router, `.pwcap` capture and replay like a UDP datagram:

| Tag | Page | Mapping | Snapshot size |
|---|---|---|---|
| `PHYS` | SPageFilePhysics | `Local\acpmf_physics` | 4 + 800 = 804 |
| `GRPH` | SPageFileGraphic | `Local\acpmf_graphics` | 4 + 1588 = 1592 |
| `STAT` | SPageFileStatic | `Local\acpmf_static` | 4 + 820 = 824 |

The adapter accepts exactly these sizes and tags and rejects anything else. It ignores Physics pages outside a
session and opens a session only on a Graphics page with status LIVE or PAUSE, so pages from a game sitting in its
menus produce no frames; the reader is still expected to forward a page only when its `packetId` (Static: its
bytes) changed.

---

## 8. Checking it with a recording

One recorded session on a PC settles every open item above. Useful moments: a few laps with a known lap time; a
pit stop; a stretch of straight-line full throttle and hard braking; fast left and right corners; one corner taken
with a slide and opposite lock. Then compare:

- `SessionInfo.extra['static_layout_check']` = `max_rpm_matches_appendix_7` (the Static layout, §6.12);
- `fuel` against the HUD (kg or litres, §6.3);
- `SessionInfo.extra['acc_evidence']`: every check settled (`verdict` +1/-1), with few `bad` counts (§6.4-6.6);
- the track map's corner directions and the lap distance at the line against the circuit's length (§6.2, §6.9);
- `iLastTime` changing in the same page as `completedLaps` (otherwise the adapter holds the completion, §6 / adapter
  docstring), `isValidLap` after a track-limits warning, `currentSectorIndex` running 0..`sectorCount`-1;
- `flag` during a yellow (§6.11).
