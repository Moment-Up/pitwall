# Assetto Corsa (2014) Remote Telemetry over UDP (`ac-remote-udp`)

Status: implemented in pitwall from the Kunos spec, observed packet sizes and two MIT clients, and wired in as the
`ac` integration (Connect page: enable, console IP, platform). **PS5 running the PS4 build: protocol confirmed
live by the probe script, decoder and lap logic recorded-validated** (live probe `scripts/probe_ac.py` on
2026-10-11, results in §6; replayed through the adapter, recorded fixture
`tests/fixtures/recorded/ac_ps5_ks_silverstone_probe-excerpt.pwcap`: one real lap crossing). pitwall's own client
and service have not yet run against the console, so lap storage, timing end to end and coaching are still to be
confirmed on a full AC session. PS4 is community-confirmed (2017-2020); PC uses the same structures but has not
been tested by pitwall. Xbox One has no telemetry.
The struct field lists, C types, ops and procedure below were re-checked against the published Kunos document on
2026-10-10 (unchanged).

Code: `src/pitwall/adapters/ac/` (pure decoder), `src/pitwall/ingest/ac_client.py` (handshake client and packet
source), `src/pitwall/sim/ac_stream.py` (synthetic stream and loopback fake server), `tests/unit/test_ac.py`,
`tests/recorded/test_ac_ps5_real.py` (real PS5 data).
`tests/unit/test_ac.py` checks the layout tables in this file and in `forza-ac-acc-iracing.md` §2.2 against
`packets.py`.

## 1. Sources

| Source | Licence | Used for |
|---|---|---|
| Kunos, "AC Socket Document" (Remote Telemetry UDP spec, public Google Doc): https://docs.google.com/document/d/1KfkZiIluXZ6mMhLWfDX1qAGbvhGRC3ZUzjVIt5FQpp4/pub | none stated | Field names, order and C types; port; ops; procedure. Implemented from it, nothing copied |
| rickwest/ac-remote-telemetry-client (JavaScript) | MIT | Read for corroboration: explicit offsets, size dispatch 408/328/212, UTF-16LE strings |
| crmne/moza-rev, `src/assetto_corsa.rs` (Rust) | MIT | Read for corroboration: `#[repr(C)]` natural alignment (328 B), `'%'`-padded strings, gear 0=R 1=N, ~333 Hz on PC |
| assettocorsamods.net "UDP format update" thread (2017); vthinsel captures | forum / CC0 capture | PS4: handshake reply plus 328-byte RTCarInfo |
| rusty-telemetry (AGPL), ch3p4ll3/ACUDP (GPL), Egocentrix/AC-UDP-Connection and MrDoor1234 (no licence) | — | **Not read for code, nothing copied.** Egocentrix's 26/27 bool offsets are known only from the research summary |

## 2. Session procedure (spec)

All integers are int32 little-endian, floats are float32, `bool` is 8 bits.

1. Client sends `handshaker` = `(identifier=1, version=1, operationId=0 HANDSHAKE)` to the AC host, UDP **9996**.
   The spec says `identifier` and `version` are "not used in the current version".
2. AC replies with `handshakerResponse` (car, driver, track, track config). The reply `identifier` is "for now
   just 4242" and is meant to carry status codes such as "not available".
3. Client sends the same struct with `operationId` **1 SUBSCRIBE_UPDATE** (RTCarInfo "for every physics step") or
   **2 SUBSCRIBE_SPOT** (RTLap on spot events, such as the end of a lap, "for all the cars in the session").
4. **3 DISMISS** stops the stream. To reconnect, start again at step 1.

AC replies to the sender's address. A client can therefore bind an ephemeral port and `connect()` to `host:9996`.
The server exists only while a session is loaded. The client must re-register for every session (PS4 report,
2017). Nothing needs enabling in the game.

The update rate is not in the spec. On PC it is about 333 Hz per moza-rev, and other claims range from 20 to 60
Hz. **PS5 (PS4 build): 59.8 Hz** (median inter-arrival 16.4 ms, p95 21.0 ms), also while the simulation is frozen
(identical packets). Over Wi-Fi some packets arrive bunched (~0.1 s gaps whose next packet's `lapTime` advanced only
one step); the longest gap in 240 s was 428 ms, just before a pause/menu.

## 3. Layouts

### 3.1 handshaker (client to AC, 12 B)

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | int32 | identifier | 1 |
| 4 | int32 | version | 1 |
| 8 | int32 | operationId | 0 HANDSHAKE, 1 SUBSCRIBE_UPDATE, 2 SUBSCRIBE_SPOT, 3 DISMISS |

### 3.2 handshakerResponse: 408 B on PC (UTF-16LE `wchar_t[50]`)

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | wchar[50] | carName | |
| 100 | wchar[50] | driverName | |
| 200 | int32 | identifier | 4242 |
| 204 | int32 | version | 1 |
| 208 | wchar[50] | trackName | |
| 308 | wchar[50] | trackConfig | |

The spec says `char[50]`. Read literally, that gives a **208-byte** reply: carName@0, driverName@50,
identifier@100, version@104, trackName@108, trackConfig@158. Nobody has seen one, but the console reply size has
never been measured publicly either. pitwall accepts 208 B and reports it as the `8-bit` encoding. **The PS5 (PS4
build) sends the 408-byte UTF-16LE reply**, status 4242, version 1.

### 3.3 RTCarInfo (SUBSCRIBE_UPDATE): 328 B

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | identifier | `'a'` (0x61). Byte 1 is 0x00 if the field is `wchar_t`; bytes 1-3 are padding otherwise |
| 4 | int32 | size | 328 |
| 8 | f32 | speed_Kmh | |
| 12 | f32 | speed_Mph | |
| 16 | f32 | speed_Ms | |
| 20 | u8 | isAbsEnabled | |
| 21 | u8 | isAbsInAction | |
| 22 | u8 | isTcInAction | |
| 23 | u8 | isTcEnabled | |
| 24 | u8 | isInPit | natural alignment (rickwest, moza-rev); **PS5 confirmed**. Egocentrix reads 26 |
| 25 | u8 | isEngineLimiterOn | natural alignment. Egocentrix reads 27 |
| 26 | u8×2 | pad_26_27 | alignment padding before the next float |
| 28 | f32 | accG_vertical | g |
| 32 | f32 | accG_horizontal | g |
| 36 | f32 | accG_frontal | g |
| 40 | int32 | lapTime | ms, current lap |
| 44 | int32 | lastLap | ms |
| 48 | int32 | bestLap | ms |
| 52 | int32 | lapCount | completed laps (community; PS5: 0 on the out-lap, 1 after the first line) |
| 56 | f32 | gas | 0..1 |
| 60 | f32 | brake | 0..1 |
| 64 | f32 | clutch | 0..1; PS5 rests at 1.0 (1 = engaged?) |
| 68 | f32 | engineRPM | |
| 72 | f32 | steer | unit undocumented; PS5 raw -228..227 |
| 76 | int32 | gear | 0 = R, 1 = N, 2 = 1st (community; PS5 1..6 seen, no R) |
| 80 | f32 | cgHeight | m |
| 84 | f32×4 | wheelAngularSpeed | wheel order undocumented |
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
| 308 | f32 | carPositionNormalized | spline position, 0..1 of a lap; PS5: wraps at the timing line |
| 312 | f32 | carSlope | |
| 316 | f32×3 | carCoordinates | world x, y (up), z in metres |

### 3.4 RTLap (SUBSCRIBE_SPOT): 212 B on PC

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | int32 | carIdentifierNumber | |
| 4 | int32 | lap | |
| 8 | wchar[50] | driverName | |
| 108 | wchar[50] | carName | |
| 208 | int32 | time | ms |

RTLap was **not delivered on PS4** (2017). moza-rev says SPOT instead sends one RTCarInfo per second, which
contradicts the spec. **On the PS5 (PS4 build) RTLap arrives** on a second socket subscribed with SUBSCRIBE_SPOT
(212 B, UTF-16 names equal to the handshake's), and that socket received no RTCarInfo at all. Two arrived in 120 s:
`lap -1, time 0` when the lap counter reset into the pit box, and `lap 0, time 138817` when the game restored the
earlier lap state 2.6 s later - i.e. the PS5 re-sends a lap's RTLap when a state is restored, so RTLap is not a
line-crossing signal by itself. `lap` is the 0-based index of the completed lap (`lap 0` = the lap that `lapCount`
0 -> 1 completed; its `time` equals that crossing packet's `lastLap`) - inferred from that re-send: the SPOT socket
opened after the only crossing, so no RTLap was seen at a crossing and its timing there is unverified.

### 3.5 Packing: why 328 bytes, and the isInPit dispute

The spec's field list, laid out with **natural (default MSVC) alignment**, gives exactly the observed 328 bytes:

- `identifier` (1 or 2 bytes) is padded to the 4-aligned `size` at offset 4;
- the six bools occupy bytes 20-25;
- 2 padding bytes align `accG_vertical` to offset 28.

A packed (`#pragma pack(1)`) reading of the same field list gives 323 bytes. That explains the old "323
computed vs 328 observed" note.

Natural alignment explains the observed size with no extra assumptions, and both MIT clients use it. So pitwall
reads `isInPit` at 24 and `isEngineLimiterOn` at 25.

- **Certain:** offsets 0-23 and 28-327, where every reading agrees.
- **Not certain:** whether bytes 24/25 or 26/27 carry `isInPit` and `isEngineLimiterOn`. To guard against a
  misread:
  - the decoder trusts a flag byte only if it is exactly 0 or 1;
  - it counts non-zero padding in `DecodeStats.by_type['pad_26_27_nonzero']`;
  - the probe prints the value sets of bytes 20-27.
- **Settled on PS5 (2026-10-11):** byte 24 was 1 in 4,117 of 14,356 packets (always with the car stationary in the
  pit box), while bytes 26 and 27 were 0 in every packet: natural alignment is right. Byte 25 (limiter) stayed 0
  (the limiter was not hit). `isInPit` means *in the pit box*: it was 0 while driving out of the pit lane.

### 3.6 Strings

Strings are UTF-16LE (`wchar_t[50]`) in the 408-byte reply and in RTLap. AC pads unused tails with **`'%'`**
rather than NUL (moza-rev), so a string ends at the first NUL **or** `'%'`. pitwall also drops non-printable
characters.

A forum snippet says console versions "don't send out proper track data" (game-compatibility.md [F13]). **PS5:**
the strings decode cleanly (`ks_audi_r8_plus`, the PSN name, `ks_silverstone`), but `trackConfig` repeats the
track name (`ks_silverstone`) instead of naming the layout. The driven layout was ~2.97 km per spline lap (§6), not
the 5.891 km GP, so console track ids cannot tell layouts apart. The adapter's first-full-lap length check rejects
a stored geometry of another layout (only its own geometry); references, comparisons and track models are kept
apart by track length downstream (§5, "Layouts share a track id"). Until a full lap is measured, nothing tells two
layouts with the same spline origin apart.

## 4. What the stream does and does not carry

| Need | RTCarInfo | Evidence |
|---|---|---|
| Speed, throttle, brake, RPM, gear | yes | spec names plus community units |
| Clutch | yes, direction unverified | PS5: rests at 1.0 |
| Steering | `steer`, unit **undocumented** (radians, wheel degrees and normalised input have all been claimed) | PS5 raw -228..227; wheel rotation during the probe not recorded |
| World position | `carCoordinates` (metres, y up) | PS5: path = integral of `speed_Ms` within 0.02 % (metres) |
| Lap fraction | `carPositionNormalized` (absolute spline position) | PS5: one wrap per lap, at the timing line |
| Lap count and times | `lapCount`, `lapTime`, `lastLap`, `bestLap` (ms) | spec; PS5 confirmed (§6) |
| Accelerations | `accG_*` in g, signs undocumented | PS5: `accG_frontal` sign agrees with d(speed)/dt (4637 : 0) |
| Velocity vector, orientation | no (speed magnitudes only) | |
| Tyre temperatures, pressures, wear, fuel, sectors, lap validity, weather, setup, max RPM | **no** | |
| Track / car identity | only in the handshake reply | |

## 5. Implementation notes (pitwall)

**Validation.** Packets are validated by exact size: 408 or 208 (handshake reply), 328 (RTCarInfo), 212 (RTLap).
Every other size is rejected. No other pitwall protocol uses these sizes; F1 25/26, GT7 and Forza sizes are
disjoint. RTCarInfo's `'a'` identifier and its `size` field are checked as warnings (`DECODE_WARNING`), not as
rejection criteria, because both are unverified on consoles.

**Identity.** Track id is `ac:<track>[:<config>]`, lower-cased with whitespace and `:` replaced. Car id is
`ac:car:<car>`. Frames that arrive without a preceding handshake reply have no ids.

**Platform.** The wire cannot distinguish PS4 from PC, so `platform` is a constructor argument; it is UNKNOWN
otherwise.

**Sessions.**
- A session starts at the first RTCarInfo, with uid `ac:<t_recv_ns>`.
- It ends on a handshake reply with a different car, driver, track or config, or when `lapCount` goes backwards: a
  session restart, or a return to the pits that resets the counter (PS5: `lapCount` 1 -> 0, `lapTime`, `lastLap`
  and `bestLap` reset, car in the pit box). Lap numbers are unique per stored session, so this is a new session;
  the lap in progress ends incomplete.
- A reply with the same identity is a re-subscription and continues the session (PS5: the SPOT socket's reply).
- A car name of `PITWALL-SYNTHETIC` maps to the synthetic session uid.

**Clock.** The adapter uses the host receive clock. The clock does not advance while the simulation is *frozen*
(position and `lapTime` unchanged); those frames are flagged `PAUSED`.

**Laps.**
- pitwall's lap number is `lapCount + 1`.
- An increment **with `lapTime` restarting** (at most the receive gap + 0.5 s) completes the previous lap. An
  increment with the lap clock **jumping** (neither restarting nor running on from the lap before) or with a
  **teleport** is not a line crossing: on the PS5 the game restored the pre-reset state 2.6 s after a counter reset
  (`lapCount` 0 -> 1, `lapTime` 1.2 s -> 73 s, the exact earlier position 534 m from the pit box), and completing a
  lap there was the duplicate the first replay showed. Nothing is completed (`increment_without_lap_start`) and the
  lap that starts there is unanchored and void.
- An increment with `lapTime` still **running on** from the lap before (no teleport) is treated as a crossing whose
  clock lags the counter (one PS5 crossing showed no lag; PC is untested): the completion is held until `lapTime`
  restarts within 0.5 s (`lap_clock_restarted_late`; that restart is not a lap reset), else released untimed and
  `valid=False`, and the lap that began there is void too (`lap_clock_not_restarted`).
- Lap time: `lastLap` when it changed in the crossing packet (PS5: it did); else an RTLap for that lap received at
  most 1 s before the increment; else an unchanged `lastLap` that matches the lap's own clock (equal lap times);
  else the completion and the following frames are held for up to 0.5 s until `lastLap` changes or an RTLap arrives.
- RTLap (only when a SPOT subscription delivers it; the service subscribes to updates only, and no RTLap was ever
  seen at a crossing): after the completion it is compared (`rt_lap_confirmed` / `rt_lap_time_mismatch`); an early
  one is dropped after 1 s, on a lap reset or a teleport (the PS5 re-sends RTLaps after state changes); for a lap
  the session did not complete it is ignored (`rt_lap_unmatched`). A lap number is never completed twice.
- `isInPit` = 1 -> `pit_status` 2 (pit box); 0 -> `None`: the PS5 sent 0 while the car drove the pit-exit lane.
- If `lapTime` drops without an increment (lap reset) or the car teleports (PS5: sent to the pit box with the lap
  clock running), the lap is marked `valid=False` and its distance trace stops.

**Lap distance.** Distance is `(carPositionNormalized - line_norm) mod 1 × track_length`. The spline position is
absolute, so with one fixed length the same corner sits at the same distance on every lap. Two values have to be
derived:
- `line_norm`. **Spline zero**: if a `lapCount` increment on a continuous stream lies within 0.002 of spline
  position 0, the spline origin is the timing line for the session (`ac_line_source='spline_zero'`) and distances
  start once the length is known. PS5 Silverstone: the spline wrapped 0.99999 -> 0.00018 and the increment followed
  two packets (35.5 ms, ~2 m) later at 0.00077, with `lapTime` restarting. Every later crossing is checked against
  it like any trusted line. **Fallback** for a track whose spline origin is elsewhere: the midpoint of the spline
  positions either side of an increment is a *candidate* (a console might increment on a race start or at pit
  exit), trusted once a second increment agrees within the two crossings' packet spacing; a disagreeing increment
  replaces the candidate (`line_candidate_moved`).
- A trusted line (spline zero, confirmed, or stored from an earlier session) that a crossing contradicts is counted
  (`line_mismatch`), and the lap that ended at that crossing is completed `valid=False`. One such crossing changes
  nothing else; if the next crossing agrees with it instead of the trusted line, the line is rejected
  (`line_rejected`): it moves to where the two crossings agree, the length is forgotten and re-estimated, and the
  stored entry is dropped.
- The track length (provenance `derived`, `SessionInfo.extra['track_length_source']`): an **early estimate**,
  driven path (3-D `carCoordinates` steps) / spline progress, accumulated **only on laps that began with an observed
  crossing** - the out-lap can start in the pit lane, which runs off the spline without `isInPit` saying so (PS5:
  ~29 m off, path/spline 4 % short) - over clean steps (receive gap <= 0.5 s, no teleport, not frozen, spline
  moving forward by less than 5 % of a lap, not in the pit box). It is published
  (`derived:path_over_spline_estimate`, `track_length_quality='estimate'`, `track_length_estimate_fraction`) once
  it covers at least 15 % of a lap and has stayed inside a 0.5 % band over the last 10 % of a lap. The band shows
  that the running ratio has settled, **not that it is accurate**: see §6 for the measured accuracy (a few %).
- The **first** anchored full lap from line to line (no gap, teleport, reset, pit box or missing position) measures
  the length over exactly one spline lap, **once per session**; from then on the length is fixed. A measurement
  within 0.5 % of an estimate keeps the estimate's value (`length_estimate_confirmed`,
  `derived:estimate_confirmed_by_full_lap`), so the lap it scaled and the later laps share one scale; otherwise the
  measurement replaces it (`length_estimate_replaced`, or `length_estimate_off` beyond 3 %;
  `derived:full_lap_path`). Any lap with a distance scaled by an estimate that its own full lap did not confirm is
  completed `valid=False` (`estimate_scaled_lap_void`), so it can never be a reference or track-model lap next to
  laps of another scale. `track_length_full_lap_m` reports the session's measurement. This is the driven line,
  about 1 % off the centreline.
- A stored full-lap length is checked on the first anchored full lap: within 3 % (the same layout, another line)
  it is kept unchanged (`known_length_confirmed`, identical scaling across sessions); further off it is replaced
  (`length_rejected`, that lap `valid=False`). A stored estimate is checked like a new one, and counts as rejected
  when more than 3 % off.
- After either rejection `SessionInfo.extra['ac_geometry_rejected']` is true for the rest of the session, and the
  runtime ignores every older stored session of that track when it seeds the next one: the stale track name ([F13]),
  an unnamed layout change (PS5 `trackConfig`) or a track update that moved the spline origin cannot keep a bad
  entry alive.

On a new track where spline 0 is the line, distances start when the estimate converges, 15-25 % of a lap after
the first crossing (PS5: 2945.3 m after 15.0 % of lap 2, 10.2 s after the line), so that lap's trace starts
mid-lap and is not a reference; the first clean, fully scaled lap is the one after the first full lap. Elsewhere
distances start at the second crossing. Until both are known,
`lap_distance_m` is `None`, so the out-lap is not assembled. `SessionInfo.extra` carries `ac_line_norm` (trusted
lines only), `ac_line_source`, `track_length_quality` and `lap_distance_status`. Pass `AcAdapter(known_tracks=...)`
with geometry from earlier sessions to get distances from the first frame and identical scaling across sessions;
the runtime builds it from the most recent stored real AC sessions (`sessions.track_length_m` +
`info.ac_line_norm` + `info.track_length_quality`).

**Longitudinal g.** `g_lon` stays `None` until the sign of `accG_frontal` has been learned online against the
measured change in `speed_Ms`. Steering is not mapped.

**Client** (`AcRemoteClient`):
- One socket on an ephemeral port, `connect()`ed to the game. A socket that fails to bind/connect is closed.
- Targets: RFC 1918 or link-local IPv4 unicast only (loopback for tests); public, CGNAT/Tailscale, documentation,
  multicast, `.0` and `.255` addresses raise `ValueError` in the constructor and in `set_console_ip`. The integration
  settings and the probe use the same gate.
- States: idle → handshaking (every 2 s) → subscribed → streaming. Refusals (ICMP) are reported as the `refused`
  state. Never more than one HANDSHAKE per second to a non-loopback target, whatever the caller configures; after
  2 min without a stream the interval stretches to 6 s. That covers silence, refusals, send errors (a PS5 in rest
  mode makes macOS report `EHOSTDOWN`; the error path keeps the back-off schedule) and a game that answers
  handshakes but never streams (re-registration cycles back off too). Only RTCarInfo resets it.
- If there is no stream for 3 s, it sends DISMISS and re-registers on a fresh port.
- It subscribes to updates only. `subscribe_spot=True` would send SUBSCRIBE_SPOT on the same socket: unvalidated
  (the probe used a second socket with its own handshake, and that socket received no RTCarInfo, so a SPOT
  subscription might replace the update stream); it logs a warning and must stay off.
- `idle_timeout_s` (60 s) ends the session, as `UdpListener` does.
- It sends DISMISS on stop and on retarget (`set_console_ip`).
- Every datagram goes to capture and to the handler, with `src_port` = the game's port. Captures are
  `<time>_ac9996.pwcap`, `game_hint='ac-remote'`, `extra.platform` = the configured platform (replay uses it).
- Replays decode a capture as AC only when its `game_hint` is `ac-remote` (client, probe, synthetic writer): AC is
  detected by datagram size alone, so a raw "record another game" capture is never decoded as AC.
- When the stream ends (idle timeout, integration switched off, replay done) a lap completion still waiting for
  `lastLap` is released without a time before the session ends (`AcAdapter.flush`).

**Layouts share a track id on consoles.** The PS5 sends `trackConfig` = track name, so International and GP are both
`ac:ks_silverstone:ks_silverstone`. The adapter's checks protect only its own geometry (the first full lap rejects a
stored length of another layout). Downstream, `analysis.compare.check_compatibility` blocks comparisons between
sessions whose track lengths differ by more than 3 %, and the lap processor and session analysis choose references
and build track models only from sessions within 3 % of the session's length (`repo.clean_laps_for(...,
track_length_m=...)`). The stored track model is still one per track id: switching layouts rebuilds it from that
layout's laps, and a model of the other layout is never used meanwhile.

**Integration** (`integrations.py` key `ac`, `core/runtime.py`): no listening port (`IntegrationSpec.listens=False`,
so it never conflicts with another integration's port). Enabled with a console IP, the runtime starts one client
with its own `SessionManager` (source `ac-remote`) and `PacketRouter` holding one `AcAdapter` (platform from the
settings: ps5 | ps4 | pc, default ps5; known track geometry from stored sessions). An IP change retargets the same
client; a platform change rebuilds it; disabling or clearing the IP stops it. `input_status()` reports the client
snapshot (state, sent/received, rate, last error, last handshake) for the Connect page.

**Probe** (`scripts/probe_ac.py`): at most 5 HANDSHAKEs per run in total (the SPOT socket only gets what the update
socket left), at least 1 s apart for a LAN target, target checked inside `run_probe` as well as on the command
line. Switch the AC integration off while it runs: the service's client would register with the same console, and
whether AC streams to two clients is undocumented (a stream that keeps stopping could then be pitwall's own doing).
The PS5 outcome was A (it streams, §6), so a `refused` there means AC is not on track yet.

**Synthetic data.** `pitwall.sim.ac_stream` generates a handshake plus an RTCarInfo stream with ground truth.
`FakeAcServer` is a loopback-only stand-in for the game, used by the client tests and by `probe_ac.py --dry-run`.

## 6. PS5 live probe (2026-10-11): results and what is still open

`scripts/probe_ac.py --platform ps5 --seconds 120 --spot-seconds 120` against AC (PS4 build) on James's PS5,
`ks_audi_r8_plus` at `ks_silverstone`, GT DD Pro. Capture `data/captures/ac-probe-ps5-20261011-002351.pwcap`
(+ `.json` summary); recorded-tier excerpt and checks in `tests/recorded/test_ac_ps5_real.py`.

1. **PS5 answers: outcome A (stream).** One handshake, answered at once.
2. **Handshake reply:** 408 B UTF-16LE, status 4242, version 1; strings decode cleanly; `trackConfig` = track name
   (no layout).
3. **RTCarInfo identity:** byte 0 `'a'`, byte 1 0, `size` 328 in all 14,356 packets; 0 rejected, 0 non-finite.
4. **isInPit at 24** (see §3.5); 26/27 always 0. Limiter not hit.
5. **Rate:** 59.8 Hz, median 16.4 ms, p95 21.0 ms, max 428 ms; frozen (paused) simulation keeps streaming.
6. **`steer`:** raw -228..227. Open: the wheel rotation setting was not recorded, so the unit is still not settled.
7. **Gear:** raw 1 at standstill, 2..6 rising with speed (1st..5th); reverse not selected. R = 0 still unverified.
8. **`lapCount`:** 0 on the out-lap, +1 at the line two packets (35.5 ms) after the spline wraps, `lapTime`
   restarting and `lastLap` = `bestLap` = 138,817 ms in that same packet - the only crossing in the capture. After
   a counter reset the game later *restored* the earlier state (an increment without a lap start, see §5). Race
   start / pit exit behaviour: not observed.
9. **Clutch:** rests at 1.0 (dips during shifts), so 1 = engaged is likely; not mapped differently.
10. **`accG_frontal` sign:** agrees with d(speed_Ms)/dt (4637 windows : 0); the adapter learns it online anyway.
11. **SUBSCRIBE_SPOT:** RTLap (212 B) on a second socket, no RTCarInfo on that socket (§3.4). The socket opened at
    ~120 s, after the only crossing (88.65 s): the two RTLaps were the reset marker (-1, 0) and a re-send of lap 0
    (138,817 ms) after the restored state. No RTLap was seen at a crossing, so its timing semantics are unverified.
12. **Re-registration:** one registration lasted the whole run, through a pause, a counter reset and a teleport to
    the pit box; after a session change in the menus: not observed.
13. **Pit lane:** after the pause at the start, the car pulled away down the pit-exit lane (t = 6-14 s, up to ~29 m
    off lap 2's line at the same spline position, merging by t = 14 s) with `isInPit` = 0 throughout; `isInPit` was
    1 only with the car stationary in the pit box. Path/spline over t = 6-14.3 s: 2851.9 m, 4.1 % below the
    all-laps value.

Units: `speed_Kmh` = 3.6 × `speed_Ms` exactly; the `carCoordinates` path equals the integral of `speed_Ms` within
0.02 % (metres).

**Track length on the capture** (one crossing only, so no full lap was measured):

| Value | Metres | How |
|---|---|---|
| Early estimate published by the adapter (current rules) | **2945.3** | 15.0 % of lap 2 from the crossing, t = 98.9 s (10.2 s after the line); identical on the excerpt fixture |
| Earlier estimate rules (out-lap included) | 2966.0 / 2914.1 | full capture / excerpt: both passed the 0.5 % band, 1.8 % apart - the out-lap's pit lane and section mix |
| Driven path / spline over all clean driving (1.760 laps) | 2974.5 | offline, same clean-step rules (5235.1 m / 1.760); the `speed_Ms` integral over the game's `lapTime` gives 2974.4 |
| Spline scale on the straights (driven line parallel to the spline) | ~2945 | path/spline at spline 0.40-0.65 (2942-2945 per 5 %) |
| Silverstone GP (real world; also AC's GP layout per third-party listings) | 5891 | not this layout |

**Accuracy of a partial-lap estimate.** Path/spline varies section by section: per 5 % of the spline it ranges from
2834 m to 3247 m (-4.7 % / +9.2 % against 2974.5 m), because the driven line leaves the AI spline in corners. An
estimate over 15-30 % of a lap is therefore good to a few percent, whatever the 0.5 % stability band says: the
current estimate is 1.0 % below the 1.76-lap value, and the two estimates of the earlier rules disagreed by 1.8 %.
That is why a lap scaled by an estimate is void unless its own full lap confirms the estimate within 0.5 %.

The GP figure cannot be right for this run: lap 2 covered 85.7 % of the spline in 73.0 s of the game's `lapTime`
(the wall clock to the counter reset, 77.3 s, includes a ~4 s pause) with a top speed of 229 km/h, which would need
a 249 km/h average on a 5.9 km lap, and the driven area spans only ~0.93 × 1.0 km. The layout driven was ~2.97 km
per lap - probably the International layout; AC's own `ui_track.json` length was not available to confirm it
(third-party listings give 3.62 km for AC's International and 2.64 km for its National, neither of which matches).

**Full runtime replay** (`pitwall replay` into a scratch data dir, current rules): two sessions, 3 laps stored,
none clean, no track model, 0 observations, no duplicate completion. Session 1: lap 1 completed once at 138,817 ms
but not stored (no frame had a distance before the first crossing, so the lap time never reached the database);
lap 2 stored incomplete, distance 443.7 -> 2524.0 m (from the estimate at 15 % of the lap until the counter reset
cut it at spline 0.857). Session 2 (starting from session 1's stored estimate): lap 1 = the pit box at 235.3 m
(flagged pit/incomplete, its distance lost at the lap-time reset), lap 2 = the restored state, unanchored at
2524.0 -> 2540.6 m until the teleport to the pit box, then no distance. Both RTLaps stored as events.

Still open: pitwall's own client/service path against the console (laps stored and timed end to end), R gear
value, `steer` unit, limiter byte, RTLap at a line crossing, lap coaching on a full AC session (several laps), what
the game sends at a race start, a full-lap length measurement on PS5, and a layout name (track ids cannot tell
layouts apart).

## 7. Recorded-fixture options

- **The probe's own `.pwcap`** (`--platform ps5`): done.
  `tests/fixtures/recorded/ac_ps5_ks_silverstone_probe-excerpt.pwcap` (0.75 MB, 4,351 packets, byte-for-byte via
  `scripts/excerpt_capture.py`, windows 0-12 s, 55-100 s, 119-122 s, 163-176 s), checked by
  `tests/recorded/test_ac_ps5_real.py`. The player's PSN name (handshake reply and RTLap `driverName`) was then
  replaced with `Player` by `scripts/scrub_capture.py`, and the console's LAN address in the metadata with
  127.0.0.1; every other byte is unchanged.
- **vthinsel/Python_UDP_Receiver** (commit 21d6b5f): `AssettoCorsa_monza_A8LMS.raw`, 8641 × 328-byte PS4 RTCarInfo
  records. **CC0-1.0.**
  - It may be downloaded only with James's permission, into a fresh scratch directory.
  - The extensionless sibling is a Python pickle stream: **never unpickle it**.
  - The capture has no handshake reply and no receive timestamps. It can validate the RTCarInfo layout (PS4, not
    PS5) as a third-party fixture, separate from pitwall's own recorded tier.
