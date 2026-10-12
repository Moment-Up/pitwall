# Gran Turismo 7 "Simulator Interface" UDP protocol

Research date: 2026-10-10. Scope: everything needed to write a byte-exact Python receiver/parser for GT7 telemetry on a Mac on the same LAN as a PlayStation.

The interface is undocumented by Polyphony Digital. Everything below comes from reverse-engineering by the community. No code is copied here. Field layouts are described in tables and the procedure in prose.

## Confidence legend

| Tag | Meaning |
|---|---|
| **Confirmed** | At least three independent implementations agree, and live use is reported (for example PDTools, gt7-udp, gt7dashboard, zetetos/gt-telemetry, or GT7Eng's live validation). |
| **Community** | Documented by one or two reverse-engineering sources and plausible, but not cross-checked by several implementations. |
| **Conflicting** | Sources disagree. Both readings are given. Verify with our own captures before relying on it. |
| **Unverified** | A single claim with no corroboration, or my own inference. |

---

## 1. Transport and session

| Item | Value | Confidence |
|---|---|---|
| Console listen port (where we send the heartbeat) | UDP **33739** on the PlayStation's IP | Confirmed |
| Our receive port (where the console sends telemetry) | UDP **33740** on the host that sent the heartbeat | Confirmed |
| Direction | The console unicasts encrypted datagrams to the source IP of the most recent heartbeat. Nothing is sent until a heartbeat arrives. | Confirmed |
| Rate | About 60 Hz, one packet per simulation tick. GT7Eng measured "roughly 60 Hz" live on a PS5 in May 2026. | Confirmed |
| Heartbeat payload | A single ASCII byte that selects the packet variant: `A` (0x41), `B` (0x42), `~` (0x7E) or `C` (0x43). See §2. | Confirmed |
| Stream lifetime without a heartbeat | gt7-udp says the console expects a heartbeat about every 1000 packets (~16.7 s at 60 Hz), or it stops sending. | Community |
| Heartbeat cadence used in the wild | PDTools and zetetos/gt-telemetry send one every **10 s**. gt7dashboard and Bornhall send one every **100 received packets** (~1.7 s) and also after any 10 s receive timeout. sim-race-engineer sends one every 100 ms, which is excessive but harmless. | Confirmed (as implementations) |
| Recommended for pitwall | Send a heartbeat on start, then every 1–5 s. Send one immediately after any receive gap longer than about 1 s. The cost is negligible and it recovers quickly after console sleep or a mode change. | Recommendation |
| Reply port vs heartbeat source port | PDTools, gt7dashboard and Bornhall send the heartbeat from the same socket that is bound to 33740. sim-race-engineer sends from a separate ephemeral socket and still receives on 33740. This implies the console always targets port 33740 regardless of the heartbeat's source port. | Community (inferred from a working implementation) |
| Discovery | (a) gt7dashboard and zetetos send the heartbeat to `255.255.255.255:33739` (broadcast) when no IP is configured; the first reply reveals the console IP. (b) gt-telem (GPL) uses the PlayStation device-discovery protocol: a `SRCH * HTTP/1.1` query broadcast to UDP **9302** (PS5). PS4 is commonly said to use UDP 987 for the same protocol (not verified here). | Community |
| In-game setting | No in-game toggle is known; the interface is always available. sim-race-engineer's README tells users to enable "Options → Machine Settings → Send Vehicle Data"; I found no corroboration of such a setting. | Community / Unverified (the toggle claim) |
| Network | The console and the receiver must be on the same LAN (unicast UDP; no NAT traversal). macOS's application firewall must allow inbound UDP 33740 (GT7Eng's README notes this). Docker containers cannot broadcast by default (gt7dashboard README). | Confirmed |
| Platforms | PS5: Confirmed (all 2026 live reports). PS4: gt7-udp README and gt-telem describe PS4/PS5 support. No recent PS4-specific live report found. | PS5 Confirmed / PS4 Community |
| Multiple consumers | Only one process per host can bind 33740 (GTPlanet users report that SimHub and a motion tool conflict). Run a single receiver that fans out internally or re-broadcasts. | Community |
| Replays | Packets also flow during replays and menu "background" driving. gt7dashboard needs an "always record" toggle to log replays, and filters by flags otherwise. gt7-udp says variant `~` is "not available in Replays", and the Kaitai spec says the `~` brake-output byte is "live sessions only". | Community / Unverified (the `~` replay caveat) |

### Older titles (for reference only)
- GT Sport: key `Simulator Interface Packet ver 0.0`, ports 33339 (console) and 33340 (receiver), XOR `0xDEADBEAF`, 296-byte packet with the same magic as GT7. Sources: PDTools, grandturismo-srs-proxy.
- GT6 (PS3): magic `G6S0`, big-endian. Source: PDTools.

---

## 2. Packet variants

| Heartbeat byte | Datagram size | XOR constant for IV2 | Adds | Introduced | Confidence |
|---|---|---|---|---|---|
| `A` | **296 bytes (0x128)** | **0xDEADBEAF** (note: BEAF) | Base packet (§4) | Launch (2022) | Confirmed |
| `B` | **316 bytes (0x13C)** | **0xDEADBEEF** | A + steering wheel angle, steering angular velocity, sway, heave, surge (§5) | GT7 **1.42** (PDTools source comment; gt7-udp README) | Confirmed |
| `~` | **344 bytes (0x158)** | **0x55FABB4F** | B + second throttle/brake bytes, 2 unknown bytes, 4 floats believed to be per-wheel torque vectoring, energy recovery, 1 unknown float (§6) | GT7 **1.42** | Confirmed (layout) / Community (meaning of several fields) |
| `C` | **368 bytes (0x170)** | **0xDEADBEEF** (same as B) | `~` + per-wheel surface type, current lap time, front-wheel steer angles, left wheelbase, car category string (§7) | "Around 1.68" (gt7-udp README). Reported in PDTools issue #18 on 2026-03-17. | Confirmed (size/XOR in gt7-udp and zetetos) / Community (field meanings) |

- In PDTools issue #18 (2026-03-31), Nenkai says there are **no other packet modes as of 1.68**. Treat A/B/~/C as the complete set until a later game update shows otherwise.
- Each variant is a strict superset of the previous one. Even though gt7-udp's README prose says "C : public PacketB", its source header and the arithmetic (344 + 24 = 368) show C extends `~`. Offsets 0x000–0x157 are identical across `~` and `C`.
- **Identify the variant by datagram length** (296/316/344/368). Do not rely on what you requested. Pick the XOR from the length.
- PDTools carries a TODO saying the game "might send a packet of 0x94 if not using 'A'". This is an unconfirmed note. Log and drop any length you don't recognise.
- gt7-udp says variant B is "not available in Sport Mode" (presumably the online Sport mode). This is a single unverified claim. Fall back to `A` if `B`/`~`/`C` stop arriving.

**pitwall recommendation:** request `C` by default. It is a superset and adds steering, current-lap time and surface type. If no `C`-sized packets arrive within a few seconds, fall back to `~`, then `A`, to cover older firmware.

---

## 3. Decryption procedure (Salsa20)

1. **Cipher:** Salsa20/20 stream cipher with an 8-byte nonce and a 32-byte key. Use any standard implementation (for example pycryptodome's `Crypto.Cipher.Salsa20`, as used by gt7dashboard and sim-race-engineer).
2. **Key:** the ASCII string `Simulator Interface Packet GT7 ver 0.0` (38 bytes; gt7-udp's README says 39, which is wrong). Use only the **first 32 bytes**: `Simulator Interface Packet GT7 v`.
3. **Nonce seed:** read 4 bytes at offset **0x40–0x43 of the received ciphertext**, before decrypting, as a little-endian 32-bit integer `IV1`.
4. **IV2** = `IV1 XOR C`, where `C` is the per-variant constant from §2: A `0xDEADBEAF`, B `0xDEADBEEF`, `~` `0x55FABB4F`, C `0xDEADBEEF`. Do the XOR on unsigned 32-bit values.
5. **Nonce (8 bytes)** = `IV2` as 4 little-endian bytes, followed by `IV1` as 4 little-endian bytes.
6. Decrypt the **whole datagram** from offset 0, with the stream counter starting at 0. Bytes 0x40–0x43 of the plaintext are meaningless after decryption; treat them as reserved.
7. **Magic check:** plaintext bytes 0..3 must be `30 53 37 47` (ASCII `"0S7G"`). Read as a little-endian uint32 this is **0x47375330**, the value gt7dashboard and PDTools compare against. PDTools' comment calls it "G7S0" because that is how it reads as a big-endian value. If the magic does not match, drop the packet. As a defensive measure, if the length is unexpected you can retry the other XOR constants.
8. All multi-byte fields are **little-endian** (PS4/PS5).
9. Use **packet id** (0x70) to drop duplicate and out-of-order packets and to count losses. gt7dashboard ignores packets whose id is not greater than the last one, and resets its tracker after a timeout or reconnect because the id restarts.

Pitfalls seen in the reviewed repos:
- grandturismo-srs-proxy (2022) unpacks an early layout. It treats 0x40–0x47 as 8 "IV" chars, which swallows fuel level, mislabels angular velocity as acceleration, and reads lap count as int32. Do not use it as a layout reference.
- sim-race-engineer reads tyre pressure from 0xD4–0xE0, and "inner/middle/outer tyre temps" and handbrake from offsets that are reserved or that overlap clutch and gear-ratio fields. PDTools states that 0xD4–0xF3 is not set by the game. **Do not reproduce those fields.**
- The Kaitai spec in zetetos/gt-telemetry (CC0) has `header_is_gt6` and `header_is_gt7` swapped relative to its own doc comment and PDTools. The doc comment (bytes `30 53 37 47` = GT7/GTS) is correct.

---

## 4. Base packet (variant A), offsets 0x000–0x127, 296 bytes

Types: `f32` = IEEE-754 float32 LE, `i32/u32/i16/u16/u8` = integers LE. Offsets are in the decrypted buffer.

| Hex | Dec | Size | Type | Field | Units / semantics | Confidence |
|---|---|---|---|---|---|---|
| 0x000 | 0 | 4 | u8[4] / u32 | magic | Bytes `30 53 37 47`; LE u32 0x47375330 | Confirmed |
| 0x004 | 4 | 4 | f32 | position X | World coordinates, metres. Y is up (track maps plot X vs Z). | Confirmed |
| 0x008 | 8 | 4 | f32 | position Y | metres (vertical) | Confirmed |
| 0x00C | 12 | 4 | f32 | position Z | metres | Confirmed |
| 0x010 | 16 | 4 | f32 | velocity X | World-frame m/s | Confirmed |
| 0x014 | 20 | 4 | f32 | velocity Y | m/s | Confirmed |
| 0x018 | 24 | 4 | f32 | velocity Z | m/s | Confirmed |
| 0x01C | 28 | 4 | f32 | rotation[0] | PDTools: quaternion X. Community (gt7-udp, gt7dashboard, Kaitai): "pitch", range −1..1 | Conflicting naming, see note R |
| 0x020 | 32 | 4 | f32 | rotation[1] | Quaternion Y / "yaw" (−1..1) | Conflicting naming |
| 0x024 | 36 | 4 | f32 | rotation[2] | Quaternion Z / "roll" (−1..1) | Conflicting naming |
| 0x028 | 40 | 4 | f32 | rotation[3] | Quaternion W. Community: "orientation relative to north", 1.0 = north, 0.0 = south | Conflicting naming |
| 0x02C | 44 | 4 | f32 | angular velocity X | rad/s (gt7-udp's "range −1..1" comment is doubtful) | Confirmed (offset) |
| 0x030 | 48 | 4 | f32 | angular velocity Y | rad/s (yaw rate if Y is up) | Confirmed (offset) |
| 0x034 | 52 | 4 | f32 | angular velocity Z | rad/s | Confirmed (offset) |
| 0x038 | 56 | 4 | f32 | body height | metres (ride height; gt7dashboard multiplies by 1000 for mm) | Confirmed |
| 0x03C | 60 | 4 | f32 | engine RPM | rev/min | Confirmed |
| 0x040 | 64 | 4 | — | nonce seed (IV1) | Read from the **ciphertext** only. Garbage after decryption. | Confirmed |
| 0x044 | 68 | 4 | f32 | fuel level | PDTools: litres, 0..capacity, and "may change from 0 when regenerative braking" for EVs. GT7Eng treats it as **percent** because capacity is 100 for most cars. Use `level / capacity` as the fraction. | Confirmed (offset) / Conflicting (unit) |
| 0x048 | 72 | 4 | f32 | fuel capacity | 100 for most cars, 5 for karts, 0 for EVs (PDTools, gt7-udp) | Community |
| 0x04C | 76 | 4 | f32 | speed | m/s (×3.6 for km/h). sim-race-engineer applies `abs()`, so it may be negative in reverse. | Confirmed |
| 0x050 | 80 | 4 | f32 | turbo boost / manifold pressure | Offset by +1: 1.0 = 0 kPa gauge, 2.0 = +100 kPa. Subtract 1 and multiply by 100 for kPa gauge. Kaitai: populated only when a turbo is fitted. | Confirmed |
| 0x054 | 84 | 4 | f32 | oil pressure | bar | Community |
| 0x058 | 88 | 4 | f32 | water temperature | °C. **Always 85** (not simulated) per PDTools and gt7-udp | Confirmed |
| 0x05C | 92 | 4 | f32 | oil temperature | °C. **Always 110** (not simulated) | Confirmed |
| 0x060 | 96 | 4 | f32 | tyre surface temp FL | °C | Confirmed |
| 0x064 | 100 | 4 | f32 | tyre surface temp FR | °C | Confirmed |
| 0x068 | 104 | 4 | f32 | tyre surface temp RL | °C | Confirmed |
| 0x06C | 108 | 4 | f32 | tyre surface temp RR | °C | Confirmed |
| 0x070 | 112 | 4 | i32 (Kaitai: u32) | packet id | Increments once per packet. Restarts on reconnect. | Confirmed |
| 0x074 | 116 | 2 | i16 | lap count | Current lap number. 0 before the start / outside a timed session. | Confirmed |
| 0x076 | 118 | 2 | i16 | total laps | Laps in race. **0 for timed/endurance and free runs** (GT7Eng) | Confirmed |
| 0x078 | 120 | 4 | i32 | best lap time | ms, **−1 when unset**. GT7Eng found the raw packet best lap "unstable" and recomputes it from its own completed-lap history. | Confirmed (offset) |
| 0x07C | 124 | 4 | i32 | last lap time | ms, −1 when unset | Confirmed |
| 0x080 | 128 | 4 | i32 | time of day | ms since in-game midnight. GT7Eng uses a rewind of 10 s or more to detect a session retry. | Confirmed |
| 0x084 | 132 | 2 | i16 | pre-race start position / quali position | PDTools, gt7-udp and Kaitai: **−1 once the race starts**. GT7Eng (live 2026), gt7dashboard and sim-race-engineer all use it as the **live race position**, and GT7Eng reports working position-change alerts. | **Conflicting**: verify with captures |
| 0x086 | 134 | 2 | i16 | number of cars (pre-race) | −1 once the race starts (PDTools). Used as "total cars" by GT7Eng. | Conflicting |
| 0x088 | 136 | 2 | i16 (Kaitai/gt7dashboard: u16) | rev-limiter alert min RPM | RPM where the shift/rev indicator starts | Confirmed |
| 0x08A | 138 | 2 | i16 / u16 | rev-limiter alert max RPM | RPM where the rev alert maxes | Confirmed |
| 0x08C | 140 | 2 | i16 | calculated max speed | km/h, top speed achievable with the current gearing | Confirmed |
| 0x08E | 142 | 2 | i16 bitfield | flags | See §4.1 | Confirmed |
| 0x090 | 144 | 1 | u8 | gears | Low nibble = current gear. High nibble = suggested gear (15 = no suggestion). See §4.2. | Confirmed |
| 0x091 | 145 | 1 | u8 | throttle | 0..255. Kaitai: "throttle **output** after TCS". The `~` variant adds a separate throttle byte (§6). | Confirmed (offset) / Conflicting (input vs output) |
| 0x092 | 146 | 1 | u8 | brake | 0..255. Kaitai: brake **input** from the controller. | Confirmed (offset) |
| 0x093 | 147 | 1 | u8 | unused | Padding (always ignored) | Confirmed |
| 0x094 | 148 | 4 | f32 | road plane X | Road surface plane normal (banking) | Community |
| 0x098 | 152 | 4 | f32 | road plane Y | | Community |
| 0x09C | 156 | 4 | f32 | road plane Z | | Community |
| 0x0A0 | 160 | 4 | f32 (Kaitai: u4) | road plane distance | Distance above/below the plane (gt7-udp: dip negative, hill positive). Float per PDTools. | Community |
| 0x0A4 | 164 | 4 | f32 | wheel angular speed FL | rad/s, signed (PDTools: "revolutions per second (in radians)"). Wheel surface speed = ω × tyre radius. | Confirmed |
| 0x0A8 | 168 | 4 | f32 | wheel angular speed FR | rad/s | Confirmed |
| 0x0AC | 172 | 4 | f32 | wheel angular speed RL | rad/s | Confirmed |
| 0x0B0 | 176 | 4 | f32 | wheel angular speed RR | rad/s | Confirmed |
| 0x0B4 | 180 | 4 | f32 | tyre radius FL | metres. gt7dashboard calls it "diameter" but uses it as a radius. | Confirmed |
| 0x0B8 | 184 | 4 | f32 | tyre radius FR | m | Confirmed |
| 0x0BC | 188 | 4 | f32 | tyre radius RL | m | Confirmed |
| 0x0C0 | 192 | 4 | f32 | tyre radius RR | m | Confirmed |
| 0x0C4 | 196 | 4 | f32 | suspension height FL | metres | Confirmed |
| 0x0C8 | 200 | 4 | f32 | suspension height FR | m | Confirmed |
| 0x0CC | 204 | 4 | f32 | suspension height RL | m | Confirmed |
| 0x0D0 | 208 | 4 | f32 | suspension height RR | m | Confirmed |
| 0x0D4–0x0F3 | 212–243 | 32 | 8 × f32 | reserved | "Seems to be reserved, server does not set that" (PDTools). **Not** tyre pressure or inner temps. | Community (PDTools, Kaitai "reserved") |
| 0x0F4 | 244 | 4 | f32 | clutch pedal | 0.0..1.0 | Confirmed |
| 0x0F8 | 248 | 4 | f32 | clutch engagement | 0.0..1.0 | Confirmed |
| 0x0FC | 252 | 4 | f32 | RPM from clutch to gearbox | ≈ engine RPM when in gear with the clutch released | Confirmed |
| 0x100 | 256 | 4 | f32 | transmission top speed | Expressed as a gear-ratio value (Kaitai: ratio of top speed to wheel speed; lets you derive the final drive) | Community |
| 0x104 | 260 | 4 | f32 | gear ratio 1 | | Confirmed |
| 0x108 | 264 | 4 | f32 | gear ratio 2 | | Confirmed |
| 0x10C | 268 | 4 | f32 | gear ratio 3 | | Confirmed |
| 0x110 | 272 | 4 | f32 | gear ratio 4 | (sim-race-engineer wrongly reads "handbrake" here) | Confirmed |
| 0x114 | 276 | 4 | f32 | gear ratio 5 | | Confirmed |
| 0x118 | 280 | 4 | f32 | gear ratio 6 | | Confirmed |
| 0x11C | 284 | 4 | f32 | gear ratio 7 | | Confirmed |
| 0x120 | 288 | 4 | f32 | gear ratio 8 / unused | Usually 0. The game copies gear ratios without bounds checking. | Confirmed |
| 0x124 | 292 | 4 | i32 | car code | Internal car ID. **Corrupted for cars with 9+ gears**: the extra ratios overwrite it (the Lexus LC500 with 10 gears is the known case). Map IDs to names with ddm999/gt7info `cars.csv` (MIT-0). | Confirmed |

**Note R (rotation).** PDTools reads 0x1C–0x2B as a `Quaternion(x, y, z, w)`. The community "pitch/yaw/roll in −1..1" plus "orientation to north 1→0" are consistent with the x/y/z/w components of a unit quaternion: w = cos(θ/2) runs from 1 (heading north) to 0 (heading south). Treat the four floats as a quaternion and derive Euler angles yourself. gt7dashboard's "yaw rate" (difference of the 0x20 value over 60 ticks) is therefore not a true angle rate. Use angular velocity (0x2C–0x37) instead.

### 4.1 Flags (i16 at 0x8E)

| Bit | Mask | Name (PDTools) | Meaning / caveats | Confidence |
|---|---|---|---|---|
| 0 | 0x0001 | CarOnTrack | Car is on track or paddock with data available. gt7dashboard calls it `in_race`. | Confirmed |
| 1 | 0x0002 | Paused | Simulation paused. **Not set in online modes' pause menu**, because the sim keeps running. | Confirmed |
| 2 | 0x0004 | LoadingOrProcessing | Track or car loading | Confirmed |
| 3 | 0x0008 | InGear | "Needs more investigation" (PDTools) | Community |
| 4 | 0x0010 | HasTurbo | Current car has a turbo | Confirmed |
| 5 | 0x0020 | RevLimiterBlinkAlertActive | Rev-limit alert flashing | Confirmed |
| 6 | 0x0040 | HandBrakeActive | Handbrake engaged (boolean only; no analog value) | Confirmed |
| 7 | 0x0080 | LightsActive | Headlights on | Confirmed |
| 8 | 0x0100 | HighBeamActive | High beams. sim-race-engineer's comment swaps 8 and 9; follow PDTools. | Community |
| 9 | 0x0200 | LowBeamActive | Low beams | Community |
| 10 | 0x0400 | ASMActive | Stability control (ASM) intervening | Confirmed |
| 11 | 0x0800 | TCSActive | Traction control intervening | Confirmed |
| 12–15 | 0xF000 | — | Unknown/unused | — |

There is **no ABS-active flag**. Lockups have to be inferred from wheel speed compared with vehicle speed under braking (as GT7Eng and sim-race-engineer do).

### 4.2 Gear byte (u8 at 0x90)
- `current = byte & 0x0F`, `suggested = byte >> 4`.
- Suggested gear 15 means "no suggestion" (PDTools, gt7-udp).
- Reverse/neutral encoding of the current gear: Kaitai says "0 = reverse, 15 = neutral", and zetetos' library treats 15 as neutral. **Unverified**: confirm with a capture by selecting N and R.

---

## 5. Variant B extension, 0x128–0x13B (packet 316 bytes)

| Hex | Dec | Type | Field | Units / semantics | Confidence |
|---|---|---|---|---|---|
| 0x128 | 296 | f32 | steering wheel rotation | **radians**. PDTools "WheelRotation", Kaitai "steering wheel angular position". Sign convention unverified. | Confirmed (offset) / Community (sign) |
| 0x12C | 300 | f32 | steering wheel angular velocity | rad/s (gt7-udp, Kaitai). PDTools labels it "FillerFloatFB" (unknown). | Community |
| 0x130 | 304 | f32 | sway | Lateral (X) acceleration / body force. Kaitai: "body forces along axes (−1 to 1)". Units unverified. | Community |
| 0x134 | 308 | f32 | heave | Vertical (Y) | Community |
| 0x138 | 312 | f32 | surge | Longitudinal (Z) | Community |

Steering input is **only** available from variant B onwards (game ≥ 1.42).

## 6. Variant `~` extension, 0x13C–0x157 (packet 344 bytes)

| Hex | Dec | Type | Field | Units / semantics | Confidence |
|---|---|---|---|---|---|
| 0x13C | 316 | u8 | throttle (alt) | 0..255. gt7-udp and PDTools debug label: "throttle filtered". Kaitai: "throttle **input** from controller" (so 0x91 would be output after TCS). | Conflicting semantics |
| 0x13D | 317 | u8 | brake (alt) | 0..255. gt7-udp: "brake filtered". Kaitai: "brake **output** after ABS (live sessions only)". | Conflicting semantics |
| 0x13E | 318 | u8 | unknown | PDTools: "CarType(?)", with 4 = electric. Kaitai: possibly an EV-related bitfield. | Unverified |
| 0x13F | 319 | u8 | unknown | PDTools field name "NoGasConsumption". Kaitai: possibly a bitfield. | Unverified |
| 0x140 | 320 | f32 | per-wheel value FL | gt7-udp: torque vectoring (positive = drive, negative = braking/regen). PDTools: unknown Vector4. | Unverified |
| 0x144 | 324 | f32 | per-wheel value FR | as above | Unverified |
| 0x148 | 328 | f32 | per-wheel value RL | as above | Unverified |
| 0x14C | 332 | f32 | per-wheel value RR | as above | Unverified |
| 0x150 | 336 | f32 | energy recovery | Energy being recovered to the battery. Units unknown. | Community |
| 0x154 | 340 | f32 | unknown | Kaitai: "possibly engine load" | Unverified |

Practical use: comparing 0x91/0x13C and 0x92/0x13D shows whether TCS or ABS is modifying the driver's pedal. That is coaching-relevant ("TCS cut 30 % of your throttle on exit"), but only once we have confirmed which byte is input and which is output.

## 7. Variant C extension, 0x158–0x16F (packet 368 bytes)

| Hex | Dec | Type | Field | Units / semantics | Confidence |
|---|---|---|---|---|---|
| 0x158 | 344 | char[4] | surface type FL, FR, RL, RR | One ASCII letter per wheel: `T` tarmac, `C` curb/kerb, `D` dirt, `G` grass, `S` sand, `s` snow (lower-case). Nenkai: the game's 23 surface types all map to these letters. | Community (multiple researchers agree) |
| 0x15C | 348 | i32 | current lap time | ms, running time of the lap in progress. Kaitai: −1 when not set. | Community |
| 0x160 | 352 | f32 | front-left wheel steer angle | radians. Right-hand rule about the vertical axis, so **turning left is positive**. | Community |
| 0x164 | 356 | f32 | front-right wheel steer angle | radians | Community |
| 0x168 | 360 | f32 | left-side wheelbase (dynamic) | metres. Equals the static wheelbase at zero steer and changes with FL steer angle. Karts ~1.06 m. | Community |
| 0x16C | 364 | char[4] | car category | NUL-terminated ASCII: `GR1`, `GR2`, `GR3`, `GR4`, `GRB`, `GRN`, `GRX` (N = road cars). Nenkai confirmed the list is complete. | Community |

Surface type, together with position, is the cheapest off-track and kerb-use detector GT7 offers.

---

## 8. What GT7 does NOT provide (in any variant)

- **Lap distance / track position**: there is no spline or normalised lap position. It must be derived (§9).
- **Track ID / track name**: must be inferred from geometry (§9).
- **Sector/split times**: none. The only lap times are best, last, and the current-lap timer (C only).
- **Live race position and gaps**: 0x84 is officially "pre-race position" (conflicting live evidence, see above). There are no gaps, deltas or data about other cars; telemetry covers the player's car only.
- **Steering in variant A**. Steering exists only in B/~/C.
- **Tyre wear, tyre pressure, inner/core tyre temperatures, brake temperatures, damage**. Tyre radius shrinks with wear and is used as a heuristic by sim-race-engineer and GT7Eng, but this is unvalidated.
- **Real water/oil temperatures**: these are constants (85 / 110 °C).
- **Weather, rain, track temperature, grip**. Only time of day is provided.
- **Setup data** beyond gear ratios and transmission top speed: no camber, toe, springs, brake balance, fuel map or TCS level settings.
- **ABS-active flag, pit-lane/pit-stop state, race flags (yellow/blue), penalties, session type**.
- **Analog handbrake** (flag only).

## 9. Derivations used by the community (approaches, described)

- **Distance along lap:** gt7dashboard integrates speed × 16.668 ms per tick and resets at each lap change. It drifts with packet loss. A better approach is to project the XZ position onto a reference centreline. zetetos/gt-telemetry (MIT) ships per-circuit centreline polylines at about 1 m spacing with `lengthMetres`.
- **Live lap timer (A/B/~):** count ticks × (1/60 s). gt7dashboard keeps a running correction equal to the reported last-lap ms minus the tick-derived time of the previous lap, so the estimate stays aligned with the game clock. Use 0x15C directly when variant C is available.
- **Lap completion:** lap count increments (with the previous value > 0). Use last-lap ms as the authoritative time. GT7Eng adds duplicate suppression and a "retry" detector (lap resets to 1 with a time-of-day rewind ≥ 10 s, a packet-id restart, or leaving the loading/menu state).
- **Track identification:** Bornhall's `gt7trackdetect` and gt-telem (both GPL) store, per track ID, a start/finish line segment (two XZ points), a crossing direction and an XZ bounding box, and match on crossing the line. zetetos (MIT) matches positions against circuit centrelines. Track IDs and names are listed in ddm999/gt7info `course.csv` (MIT-0).
- **Wheel slip:** wheel surface speed = |ω| × radius. Slip ratio ≈ wheel speed / vehicle speed. gt7dashboard flags spin when the ratio is above 1.1. Lockup is a ratio well below 1 while braking.
- **Tyre change / pit stop inference:** a refuel shows as fuel rising by ≥ 1 point. A new tyre set shows as ≥ 2 tyre radii jumping up ≥ 1.5 % (GT7Eng) or ≥ 3 mm (sim-race-engineer).
- **Powertrain type:** fuel capacity 0 → EV, 5 → kart, otherwise ICE (gt7-udp). Variant `~` byte 0x13E may encode this directly (unverified).
- **Race start (lights out):** gt7-udp's `startlightsexploit` example relies on the time-of-day field (0x80) staying frozen on the grid / rolling start and beginning to advance at lights-out. Use the first change as the race-start timestamp, for reaction-time and launch coaching. Community, single source.

## 10. Captures available for test fixtures

| Source | What | Licence |
|---|---|---|
| zetetos/gt-telemetry `data/replays/demo.gtz` (~1.3 MB) | gzip of **decrypted** packets concatenated without timestamps. The reader splits on the magic bytes `30 53 37 47`. | MIT (repo) |
| snipem/gt7dashboard `test_data/broad_bean_raceway_time_trial_4laps.json` (~1.36 MB) | Processed per-tick lap arrays (throttle, brake, speed, position, …), not raw packets | GPL-3.0 (repo) |
| neW1-/GT7Eng `tests/fixtures/simple_race.jsonl` | 3 synthetic normalised frames | GPL-3.0-or-later |

pitwall should record its own raw **encrypted** datagrams with receive timestamps. That exercises decryption and gives fixtures we fully own.

## 11. Open questions to settle with our own captures

Answers from the owner's PS5 captures of 2026-10-11 (4 captures, 277,467 packets, all variant C; 4 races, 3 cars, 2
circuits; `tests/recorded/test_gt7_ps5_real.py` pins excerpts of them) are given after each question.

1. Is 0x84 a live race position in races (GT7 ≥ 1.6x), or −1 after the start? **Partly answered:** during races it
   stays within 1..N, N being 0x86 (the field size, constant during the race), and moves one place at a time; −1
   outside races. That supports the live-position reading; it has not been compared with the game's HUD.
2. Is throttle at 0x91 the input or the post-TCS output? (Compare with 0x13C while TCS is active.) **Answered:** 0x91
   was below 0x13C on all 6,297 packets with the TCS flag set (61-92 units lower on average) and above it only while
   the clutch was in (downshift blips): 0x91 is the throttle after TCS, 0x13C the driver's pedal (the Kaitai
   reading). 0x13D equalled 0x92 on 7,068 of 7,070 braking packets, so brake input vs after-ABS output stays open.
3. Reverse/neutral encoding in the gear nibble. **Reverse answered:** every gear-0 packet that moved, moved backwards
   (171 packets; none forwards), so 0 = reverse (Kaitai). 15 (neutral) never appeared.
4. Sign convention of the steering wheel rotation at 0x128, and units of sway/heave/surge. **Sign answered:** radians,
   left positive - it agreed with the variant C road-wheel angles on 22,643 of 22,643 packets (road wheel = 0.068 x
   0x128 on 3 cars, a 1:14.7 ratio) - but 0x128 is clamped at exactly ±π while the road wheels keep turning. The
   sway/heave/surge units are still unknown.
5. Fuel units for EVs and for cars whose capacity is not 100. **Open:** 100 / 100 in every packet (no fuel used).
6. The actual heartbeat timeout: stop the heartbeat and count packets until the stream stops. **Open.**

Other facts of the same captures: the speed at 0x4C equals the velocity magnitude to 0.1 % (median) while the tyres
grip, is never above it, and drops to 22-47 % of it in slides; the rotation at 0x1C..0x2B has unit norm in every
packet (a quaternion); the lap count and total are −1/−1 in menus (not 0); the last-lap field updates in the packet of
the counter increment; the variant C lap timer at 0x15C reads within one tick of the last-lap value just before the
line and, on race lap 1, starts 150-383 ms before the line; the reserved bytes 0xD4..0xF3 are all zero; a car reset
shows as a single packet with the loading flag (and CarOnTrack) set; after the player leaves a race the console
repeats one packet, CarOnTrack set and paused clear, with only the packet id changing, for minutes (20 min in one
capture). Menus, replays and the menus' background laps stream at 60 Hz too, background laps and replays with
CarOnTrack clear.

## Sources
- Nenkai, PDTools, `PDTools.SimulatorInterface` and `PDTools.Crypto/SimulationInterface` (MIT): https://github.com/Nenkai/PDTools/tree/master/PDTools.SimulatorInterface
- PDTools issue #18, "C telemetry format discovered" (2026-03): https://github.com/Nenkai/PDTools/issues/18
- MacManley, gt7-udp README and `src/GT7UDPParser.{h,cpp}` (MIT, v2.1.3): https://github.com/MacManley/gt7-udp
- zetetos/gt-telemetry, Kaitai struct `internal/kaitai/gran_turismo_telemetry.ksy` (spec CC0-1.0; repo MIT): https://github.com/zetetos/gt-telemetry
- snipem/gt7dashboard `gt7dashboard/gt7communication.py`, `gt7helper.py` (GPL-3.0): https://github.com/snipem/gt7dashboard
- Bornhall/gt7telemetry (GPL-3.0): https://github.com/Bornhall/gt7telemetry
- RaceCrewAI/gt-telem (GPL-3.0; device discovery, track detection): https://github.com/RaceCrewAI/gt-telem
- ddm999/gt7info car and course databases (MIT-0): https://github.com/ddm999/gt7info
- GTPlanet thread "GT7 is compatible with motion rig?": https://www.gtplanet.net/forum/threads/gt7-is-compatible-with-motion-rig.410728/
- GTPlanet thread on running GT7 motion + SimHub simultaneously (single-listener conflict): https://www.gtplanet.net/forum/threads/help-needed-gt7-ps5-motion-rig-simhub-at-the-same-time-%E2%80%93-how-to-split-udp-telemetry.432620/
- GTPlanet article on the discovery: https://www.gtplanet.net/gran-turismo-7-telemetry-data-now-available-via-open-source-software/
- neW1-/GT7Eng README (live PS5 validation notes, 2026-05): https://github.com/neW1-/GT7Eng
