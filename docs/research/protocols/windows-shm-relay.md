# Windows shared-memory relay (`windows-shm-relay`): implementation spec

Research date: 2026-10-10. Family: `windows-shm-relay`. Games, in implementation order: **RaceRoom (first target)**,
Le Mans Ultimate, Assetto Corsa Competizione (shared memory), iRacing, Assetto Corsa (shared memory), Automobilista 2
(shared memory), rFactor 2, Assetto Corsa EVO.

**Status: research only, no code.** No relay, decoder or plugin exists yet. **No third-party code is copied here.**
Layouts are tables and behaviour is prose. Every offset in this file was computed (§1.2), not typed from memory.

**What this family is.** It is one pitwall-defined protocol, not a game protocol. A small agent on the gaming PC opens
each game's memory-mapped telemetry read-only. It copies chosen byte ranges verbatim and streams them over UDP to the
Mac. The Mac records them as `.pwcap` like any other source, and pure decoders turn them into `CarFrame` /
`SessionInfo` / `LapCompletion`. All of these interfaces are Windows-PC only, so this family has **no PS5 value**. Its
value is sharing pitwall with PC sim racers ([P2] §1.3 row 4).

Read with:
- `docs/research/forza-ac-acc-iracing.md` §2.1, §3.1, §4 [P1]. This file supersedes their field-level summaries with
  byte offsets.
- `docs/research/game-compatibility.md` §2.6, §4, §6 and §9 row 4 [P2].
- `docs/research/track-knowledge-sources.md` §2 (L0b-ACC), §4.2, §7.6 and Phase 6 [P3].
- Sibling Mac-direct families: `acc-broadcast.md`, `ac-remote-udp.md` and `pcars2-udp.md` [P5]. For ACC, AC and AMS2
  those need no relay and should usually ship first.

---

## 0. Summary

- **Transport (pitwall-defined, §2).** The protocol is called `PWRL` v1, and every integer in it is little-endian.
  - The agent listens on **UDP 28771** on the PC. The Mac sends `SUBSCRIBE` there every 1 s; the lease lasts 5 s.
  - The agent unicasts data to the subscriber's source IP, on the `data_port` the Mac names (**28770** by default).
  - Datagrams are ≤ 1472 B by default, so they are never IP-fragmented on a 1500-byte Ethernet MTU.
  - The datagrams are the `.pwcap` payloads, byte for byte.
- **Payload (§2.4).** A `SLICE` message carries `(game, mapping, stream, snapshot_seq, offset, bytes)`.
  - One coherent read of a mapping is a *snapshot*. A snapshot is split into parts.
  - The Mac keeps a sparse mirror of each mapping and decodes once a snapshot is complete.
  - The agent understands only version fields, change counters and the byte ranges to copy. All semantics live in
    the Mac decoders. Raw bytes are kept, so a decoder fixed later can reprocess old sessions (same rule as
    `ingest/capture.py` [P4]).
- **Agent placement (§3.1).** The agent must run **in the user's logon session** (a tray app or logon task), not as a
  Windows service. Every mapping here lives in the per-session namespace (`Local\…` or unprefixed). Microsoft's
  documentation says services use the global namespace by default [O10].
- **RaceRoom first (§4.1).** It has the cleanest source.
  - The official `r3e.h` v3.5 is **Unlicense** [O1][O2], so pitwall may even vendor it.
  - It needs no plugin.
  - It carries track and layout ids, layout length, lap distance and fraction, raw inputs, tyres and fuel.
  - **Caveat:** minor versions can move offsets. 3.4 inserted a field [O3]. Decode only exact `(major, minor)` pairs.
- **Other games:**

| Game | Mapping | Layout source | Can pitwall implement from it? | Rate (source) |
|---|---|---|---|---|
| LMU | `LMU_Data` (Enable Plugins ON) | Game-shipped `SharedMemoryInterface.hpp` (**not readable here**). Two MIT mirrors [C2][C3] agree, and their records match S397's rF2 header [O9] | Yes, from facts. The header's own licence is **unchecked** | Telemetry 100 Hz, scoring 5 Hz (measured by [C2]) |
| ACC | `Local\acpmf_*` | Kunos PDF v1.8.12 [O6] plus MIT mirror [C1] | Yes (official doc). Commercial use is a counsel question [P3] §7.6 | Per graphics step [O6] |
| iRacing | `Local\IRSDKMemMapFileName` | pyirsdk (MIT) [C4] | Yes. Track-data use is on **legal hold** (ToU) [P3] | `tickRate` (60) [C4] |
| AC | `Local\acpmf_*` | MIT mirror [C5]. Kunos reference not fetched | Yes, facts only | Unmeasured |
| AMS2 | `$pcars2$` (v14) | MIT mirror only [C1]. Game header unread | Facts only, after a header check | Unmeasured |
| rF2 | none native; pitwall writes its own plugin | S397 InternalsPlugin sample [O9]. Marked "PROPRIETARY AND CONFIDENTIAL", and the download has no licence | Plugin yes. Do not commit the header | Scoring ≈ 5 Hz [O9]. Telemetry unmeasured |
| AC EVO | `Local\acevo_pmf_*` | Kunos PDF v1 [O7], physics only. MIT transcription for graphics/static [C1]. Steam guide **unread** (HTTP 429) [O8] | Physics yes. Graphics/static are **gated** | Physics ≈ 333 Hz [C7] |

- **Biggest gaps:**
  - **ACC** exposes no track length in shared memory (`trackSplineLength` is "Not used in ACC" [O6]). Lap metres
    need the broadcast `trackMeters` or a table.
  - **LMU and rF2** give lap distance only in 5 Hz scoring, so it must be interpolated.
  - **iRacing** has no live world position [P1].
  - **AC EVO** tyre wear reads zero [C7], and its graphics layout is unverified.

---

## 1. Sources and how offsets were derived

### 1.1 Sources

| Key | Source | Licence | Used for |
|---|---|---|---|
| O1 | Sector3 `r3e-api` `sample-c/src/r3e.h` @ `29a3e95` (2026-03-20, "3.5 with LRT specific changes") | **Unlicense** [O2] | Every RaceRoom offset (§4.1) |
| O2 | Same repo: `LICENSE`, `README.md`, `sample-c/src/sample.c` (opens `"$R3E"` with `OpenFileMapping(FILE_MAP_READ, …)`) | Unlicense | Licence; how to open the mapping |
| O3 | `r3e.h` commit history: 3.1 "Breaks backward compatibility!" (`ad2b1f3`, 2025-09-11); 3.4 (`faff6d6`, 2025-09-17) adds `user_id` at the start of `r3e_playerdata`; 3.5 (`eeb9304`, 2026-03-18) only renames reserved fields | Unlicense | Version gating (§4.1.2) |
| O4 | Sector3 `r3e-spectator-overlay` `r3e-data.json` (76 tracks with layout ids and names) | **Unlicense** | Track and layout names |
| N1 | bsimracing reprint of the LMU v1.2 notes (2025-12-08): "Added the SharedMemory Header file to the support folder for the new shared memory implementation" | — | Existence and location of LMU's header |
| O6 | Kunos, *ACC Shared Memory v1.8.12* (25-page PDF). Official thread 59965 needs a login; read from the copy in [C6] | Kunos document, no licence stated | ACC field order, types, units, enums, and which fields are "not used in ACC" |
| O7 | Kunos, *ACE SharedFileOut Documentation v1* (8 pages; change log 2026-03-31 … 2026-04-28). Read from the copy in [C1] `research/` | Kunos document | AC EVO mapping names, enums, the physics struct and sub-struct sizes |
| O8 | Kunos Steam guide 3707421508 (AC EVO shared memory) | — | **Not read.** It returned HTTP 429 again on 2026-10-10 |
| O9 | Studio 397 modding resources: "Example Plugin v8" (`rF2_Example_Plugin.7z`) and `rFactorInternalsPlugin.pdf`. The page attaches no licence. Header text read from the copy in [C8]: `InternalsPlugin.hpp` ("PROPRIETARY AND CONFIDENTIAL / Copyright (c) 2017 Studio 397 B.V.") and `PluginObjects.hpp` (© 1996-2013 Image Space Inc.) | Proprietary; terms not stated | rF2 records, plugin interface, coordinate system |
| O10 | Microsoft Learn, *Kernel object namespaces* (updated 2025-04-15) | — | Session vs global namespace (§3.1) |
| C1 | devology-uk/sim-racing-sdk @ `c23c291`: `Acc.SharedMemory/Messages/*Page.cs`, `Ace.SharedMemory/Messages/*.cs`, `Ams2.SharedMemory/Messages/SharedMemoryPage.cs`, `Lmu.SharedMemory/LmuSharedMemoryLock.cs`, `…Reader.cs` | **MIT** (© 2024 Playology) | ACC/AC EVO/AMS2 layouts; the LMU lock objects |
| C2 | Swizzjack/lmu-pitwall @ `a171b80`: `bridge/src/shared_memory/lmu_data.rs`, `reader.rs`, `README.md`, `tools/lmu-probe/README.md` | **MIT** | LMU container sizes (compile-time asserts), rates, setting, witness read, probe findings |
| C3 | TinyPedal/pyLMUSharedMemory @ `6cef58e`: `lmu_data.py`, `lmu_mmap.py` | **MIT** (© 2021 Tony Whitley, © 2025 Xiang). The TinyPedal app itself is GPL [P2]; this library repo is MIT | LMU field list (second, independent mirror) |
| C4 | kutu/pyirsdk @ `1abbd64` (v1.3.7): `irsdk.py`, `vars.txt`. Commit `9880eea` (2026-06-09) added `cur_buf_tick_count`, `cur_buf` and `tick_count_begin` | **MIT** (© 2014 Mihail Latyshov) | iRacing header, buffers, variable headers, variable semantics |
| C5 | mdjarv/assettocorsasharedmemory @ `dc39bfa`: `Physics.cs`, `Graphics.cs`, `StaticInfo.cs` | **MIT** (© 2016 Mathias Djärv) | AC (2014) layout |
| C6 | rrennoir/PyAccSharedMemory | MIT (the repo). The PDF it hosts is Kunos's | Host of [O6] only |
| C7 | albertowd/live-telemetry-evo `docs/SHARED_MEMORY.md` (2026-08-02) | **no licence**: facts only | AC EVO rates, packing, `sm_version`, observed behaviour |
| C8 | ianv1/BSTSharedMemoryMapPlugin | **GPL-3.0** | Only its README (points to S397 sample #8) and the S397/ISI headers it carries. **None of its code was read or used** |
| C9 | TheIronWolfModding/rF2SharedMemoryMapPlugin | **GPL-3.0** | **Not used** (pitwall rule) |
| P1–P5 | pitwall docs and code (§14) | — | Context, pwcap format, model |

**Research limits.**
- The session's shared web-search budget was used up before this file was started, so no new web searches were run.
  Every source above was fetched directly (GitHub API, raw files, known URLs).
- **Not readable from a Mac:**
  - the LMU header shipped with the game;
  - the AMS2 `SharedMemory.h` shipped with the game ([P2] cites the Reiza forum [F6] for its existence);
  - the Kunos AC "Shared Memory Reference" forum post;
  - the AC EVO Steam guide [O8].

  Rows that depend on these are marked, and the gaps are **not** filled by guessing.

### 1.2 How the offsets were computed (reproducible)

| Game | Method | Cross-check |
|---|---|---|
| R3E | Compiled `r3e.h` with clang and printed `offsetof`/`sizeof` for every field. The header has `#pragma pack(push, 1)`; enums are 4 bytes | `sizeof(r3e_shared)` = **43 996**, `r3e_driver_data` = 328, `r3e_playerdata` = 560 |
| LMU | Parsed [C3]'s declarative ctypes classes as text (**not executed**), rebuilt them with `_pack_ = 4`, printed offsets | Matches [C2]'s compile-time asserts: ScoringInfo 548, VehicleScoring 584, VehicleTelemetry 1888, Wheel 260, total **324 820**. Also matches [O9]'s records compiled with Windows' 32-bit `long`: same sizes, identical offsets up to each record's expansion area (§4.2.5) |
| ACC | Laid out [C1]'s C# classes with `Pack = 4`, `CharSet.Unicode` (wchar = 2 B), `UnmanagedType.Bool` = 4 B | Field order checked row by row against [O6] |
| AC | Same method on [C5] | Physics identical to ACC for 0–579. Graphics identical for 0–251. Static identical for 0–523 |
| AC EVO | Physics: every field is 4-byte, field list from [O7]. Graphics and static: [C1] with `Pack = 4`, `CharSet.Ansi` | Physics offsets equal ACC's with renamed fields. Sub-struct sizes equal [O7]'s stated sizes (256/128/64) |
| AMS2 | [C1] C# with default packing | **Single source**: verify against the game's header |
| iRacing | Read directly from [C4] (`Header`, `VarBuffer`, `VarHeader`) | Self-describing at runtime |

The scratch tools (a clang `offsetof` program, an AST-only ctypes rebuilder, a C# layout calculator) stayed in the
session scratchpad. They are not part of the repo. §12 recommends a machine check in `tests/unit`, mirroring
`test_f1_protocol.py`.

---

## 2. Transport: the pitwall relay protocol `PWRL` v1

This protocol is **defined by pitwall**. Nothing here is a game protocol, so these layouts are normative.

### 2.1 Ports, direction, addressing

| Item | Value | Notes |
|---|---|---|
| Control port (agent, PC) | **UDP 28771**, inbound | Receives `SUBSCRIBE`/`UNSUBSCRIBE`. Windows Firewall needs an inbound allow rule for the agent on the Private profile only |
| Data port (Mac) | **UDP 28770** by default. Configurable; it is carried inside `SUBSCRIBE` | The Mac's existing `UdpListener` binds it [P4]. It is distinct from every port in [P2] §3.10 and from 8770, 1234, 5432, 8081, 8091, 8092, 8888 and 6397 (LMU REST, [C2]). **The IANA registry was not checked** |
| Data direction | agent → Mac, **unicast** to the source IP of the last valid `SUBSCRIBE` | The Mac never needs to know its own address |
| Discovery | Optional `BEACON`, broadcast to `255.255.255.255:28770` every 2 s while the agent has no subscriber | The Mac can also `SUBSCRIBE` to a configured PC IP, or broadcast `SUBSCRIBE` to `255.255.255.255:28771` (the GT7 heartbeat pattern, `ingest/gt7_heartbeat.py` [P4]) |
| Push mode | The agent can be configured with a static Mac `ip:port` and no subscriptions | For networks where the PC cannot receive inbound UDP |
| Max datagram | **1472 B** by default (IPv4/UDP payload on a 1500 B MTU). The subscriber can lower it (e.g. 1200 over a VPN) | Avoids IP fragmentation, where losing one fragment loses the whole datagram |
| Byte order | little-endian everywhere. All game data is little-endian too (Windows x86-64) | — |
| Subscribers | up to 4. The agent sends each snapshot to each live subscriber | — |

### 2.2 Common header (24 bytes, every message)

| Off | Type | Field | Value / meaning |
|---|---|---|---|
| 0 | char[4] | `magic` | `50 57 52 4C` ("PWRL") |
| 4 | u8 | `proto_version` | `1` |
| 5 | u8 | `msg_type` | §2.3 |
| 6 | u16 | `flags` | 0 (reserved; receivers ignore unknown bits) |
| 8 | u32 | `instance` | Sender identity. The agent picks a random u32 at start-up and **must reset the Mac's mirror state when it changes**. The Mac sends its own random subscriber nonce here |
| 12 | u32 | `seq` | Per-sender datagram counter, +1 per datagram, wraps. Lets the Mac count UDP loss |
| 16 | u64 | `t_send_ns` | Sender's monotonic clock in ns. On Windows: `QueryPerformanceCounter` scaled to ns. Not wall time, and never compared across hosts |

### 2.3 Message types

| `msg_type` | Name | Direction | Body (offsets relative to the end of the header, i.e. absolute offset = 24 + off) |
|---|---|---|---|
| `0x01` | BEACON | agent → broadcast :28770 | `0 u16 control_port`, `2 u16 agent_build`, `4 u32 games_available_mask` (bit *n* = game id *n* currently attached), `8 u8 hostname_len`, `9 hostname` (UTF-8, ≤ 63 B) |
| `0x02` | SUBSCRIBE | Mac → agent :28771 | `0 u16 data_port`, `2 u16 max_datagram` (≤ 1472), `4 u32 games_mask` (bit *n* = stream game *n*; `0xFFFFFFFF` = all), `8 u32 options` (§2.6), `12 u32 lease_ms` (requested; the agent caps it at 10 000) |
| `0x03` | SUBSCRIBE_ACK | agent → `SUBSCRIBE` source addr:port | `0 u8 status` (0 ok, 1 too many subscribers, 2 unsupported `proto_version`, 3 source not allowed), `1 u8 reserved`, `2 u16 granted_max_datagram`, `4 u32 granted_lease_ms`, `8 u32 games_available_mask`, `12 u32 subscriber_nonce` (echo of the Mac's `instance`) |
| `0x04` | UNSUBSCRIBE | Mac → agent | empty |
| `0x10` | SOURCE_INFO | agent → subscribers, on attach and then every 1 s | `0 u8 game_id`, `1 u8 mapping_id`, `2 u16 name_len`, `4 u32 region_size` (`VirtualQuery` RegionSize of the view), `8 u32 decode_size` (bytes the Mac mirror must hold, §3.4), `12 u32 version_a`, `16 u32 version_b` (per game, §3.4), `20 u32 process_id`, `24 name` (UTF-8 mapping name) |
| `0x11` | SLICE | agent → subscribers | §2.4 |
| `0x12` | SOURCE_LOST | agent → subscribers | `0 u8 game_id`, `1 u8 mapping_id`, `2 u16 reason` (0 mapping closed or game exited, 1 version not supported for decode (raw still sent if option bit 2), 2 read error) |
| `0x13` | AGENT_STATS | agent → subscribers, every 5 s | `0 u32 polls`, `4 u32 snapshots_sent`, `8 u32 torn_retries`, `12 u32 torn_dropped`, `16 u32 send_errors`, `20 u32 dropped_backpressure` |

### 2.4 SLICE (`0x11`)

| Off (abs) | Type | Field | Meaning |
|---|---|---|---|
| 24 | u8 | `game_id` | §3.3 |
| 25 | u8 | `mapping_id` | §3.3 |
| 26 | u8 | `stream_id` | 0 = player/fast, 1 = field/slow, 2 = static/layout, 3 = session text (iRacing YAML) |
| 27 | u8 | reserved | 0 |
| 28 | u32 | `snapshot_seq` | +1 per coherent read for this `(game, mapping, stream)`. Wraps |
| 32 | u32 | `offset` | Byte offset of `data` inside the game mapping (or plugin record, §4.7) |
| 36 | u16 | `part_index` | 0 … `part_count` − 1 |
| 38 | u16 | `part_count` | Total datagrams in this snapshot, across **all** regions copied in it |
| 40 | u16 | `data_len` | Bytes that follow. Must satisfy 44 + `data_len` = datagram length |
| 42 | u16 | `snapshot_flags` | bit0 coherent (the game's guard passed, §3.5); bit1 torn retries exhausted (sent anyway, decoders set `FrameQuality.DECODE_WARNING`); bit2 names scrubbed (§3.7); bit3 decimated (the agent skipped game updates to respect its rate cap) |
| 44 | u8[`data_len`] | `data` | Verbatim copy of the mapping's bytes `[offset, offset + data_len)` |

At the default 1472 B datagram, `data_len` ≤ **1428**. A region longer than that is split into consecutive parts. A
snapshot can hold several non-adjacent regions (for example, LMU's header bytes plus the player's record).

### 2.5 Mac-side validation and reassembly (decoder contract)

1. **Accept** a datagram only if it is ≥ 24 B, `magic` = `PWRL` and `proto_version` = 1. Unknown `msg_type` → count it
   and ignore it.
2. **SLICE checks.** Reject with `PacketRejected` if any of these fail:
   - length = 44 + `data_len`;
   - `part_index` < `part_count`;
   - `offset` + `data_len` ≤ the `decode_size` from the latest SOURCE_INFO for `(game, mapping)`.

   If no SOURCE_INFO has been seen yet, buffer at most 1 s of slices and then drop them, with a counter.
3. **Key** each snapshot as `(instance, game, mapping, stream, snapshot_seq)`. Keep **one** pending snapshot per
   `(game, mapping, stream)`:
   - a part with a newer `snapshot_seq` discards the incomplete older one (count `incomplete_snapshots`);
   - a part with an older `snapshot_seq` is dropped as late.
4. **On completion** (all `part_count` parts present):
   - copy every part into the sparse mirror (`bytearray(decode_size)` per `(game, mapping)`);
   - then call the game decoder for that stream. The decoder reads only the regions the stream's plan (§4) defines.
5. **A new `instance`** (agent restart) clears all mirrors and pending snapshots. The adapter emits a session reset.
6. **Purity.** The adapter stays pure (`adapters/base.py` [P4]): it holds no sockets and reads no clocks. `t_send_ns`
   comes from the data and may be used for spacing; `t_recv_ns` stays the pwcap receive time.

### 2.6 `SUBSCRIBE.options` bits

| Bit | Name | Default (Mac sends) | Effect |
|---|---|---|---|
| 0 | `field` | off | Also stream all-car data (stream 1) where the game has it. Bandwidth: §3.6. Privacy: §3.7 |
| 1 | `static_1hz` | on | Re-send static/layout streams at 1 Hz as well as on change, so a late subscriber or a lost datagram recovers within 1 s |
| 2 | `raw_unknown` | on | If the game's version is not on the agent's list, still mirror `decode_size` = min(region_size, 64 KiB) as raw slices at 1 Hz. This is for building fixtures; decoders reject it (§3.4) |
| 3 | `no_scrub` | off | Turn off name scrubbing (§3.7). Use only for the owner's own offline sessions |

### 2.7 Recording (`.pwcap`)

- The Mac's `UdpListener` on 28770 writes every datagram unchanged into `.pwcap` with `src_port = 28770` [P4]. That
  includes BEACON, SOURCE_INFO and STATS.
- Replay therefore reproduces the mirror exactly.
- `CaptureMeta.game_hint` should be `"pwrl"`, with `extra = {"agent_instance": …, "games": […]}` taken from the first
  SOURCE_INFO.
- **Router binding.** `PacketRouter` auto-detects an adapter per port [P4]. Bind port 28770 to the relay adapter
  statically, or put it first in the adapter list, so another adapter's length-only `can_decode` can never claim a
  relay datagram. The F1 adapter checks `packetFormat`, Forza checks `IsRaceOn ∈ {0,1}` and AC checks exact sizes;
  none of them matches `PWRL` today, but a static binding removes the risk. Relay `can_decode` = `len ≥ 24 and
  data[0:4] == b"PWRL" and data[4] == 1`.

---

## 3. Agent behaviour (Windows side)

### 3.1 Process model and attach

- **Run in the interactive user session**, for example as a Task Scheduler logon task or a tray app.
  - Each session has its own namespace for file-mapping objects.
  - "Service applications use the global namespace by default" [O10].
  - All mappings here are `Local\…` or unprefixed, which resolves to the session namespace [O10].
  - So a session-0 service cannot open them.
- **Open only, never create.** Use `OpenFileMappingW(FILE_MAP_READ, FALSE, name)` and
  `MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)`, as Sector3's sample does with `"$R3E"` [O2].
  - [C7] warns that Python's `mmap.mmap(-1, size, tagname=…)` *creates* the mapping when it is missing. The reader
    then attaches to an empty mapping and reads zeros.
  - [C3]'s `lmu_mmap.py` uses exactly that call. **pitwall's agent must not.**
- **Size.** After mapping, call `VirtualQuery` on the view and report `RegionSize` in SOURCE_INFO. Never read beyond
  it.
- **Read-only, always.** The agent never writes to a game mapping, never sends iRacing broadcast messages [C4], never
  takes LMU's lock in v1 (§4.2.3) and never injects into a process. rF2 is the exception: there pitwall's own code
  runs *as a plugin*, through the game's plugin interface (§4.7).
- **Detach.** On `SOURCE_LOST`, or when the change counter has not moved for 5 s while the process is gone, unmap,
  close the handle and retry `OpenFileMappingW` every 1 s.
- **Language.** The agent can be stdlib Python (ctypes) packaged with uv, or a small Rust binary. Either way it must
  not copy GPL code (CLAUDE.md). Sector3's `r3e.h` may be vendored (Unlicense). pyirsdk may be vendored with its MIT
  notice.

### 3.2 Loop

For each attached mapping and stream:
1. Poll at the stream's cap (§3.6).
2. Read the game's change counter (§3.5). If it has not changed since the last snapshot, send nothing.
3. Copy the stream's regions under the coherence guard, then send them as one snapshot.
4. Never block on the network:
   - sends use a non-blocking socket with a bounded queue (≤ 64 datagrams per subscriber);
   - on overflow, drop the **oldest** snapshot and count it in `dropped_backpressure`.

### 3.3 Ids

| `game_id` | Game | `mapping_id` → mapping name |
|---|---|---|
| 1 | RaceRoom | 0 → `$R3E` [O1] |
| 2 | Le Mans Ultimate | 0 → `LMU_Data` [C2][C3] |
| 3 | ACC | 0 → `Local\acpmf_physics`, 1 → `Local\acpmf_graphics`, 2 → `Local\acpmf_static` [P1][C1] |
| 4 | iRacing | 0 → `Local\IRSDKMemMapFileName` [C4] |
| 5 | AC (2014) | 0/1/2 → the same three `Local\acpmf_*` names as ACC [P1][C5]. **Tell AC and ACC apart by process**, because the names are identical |
| 6 | AMS2 | 0 → `$pcars2$` [C1] |
| 7 | rFactor 2 (pitwall plugin) | 0 → TelemInfoV01 image, 1 → ScoringInfoV01 image, 2 → VehicleScoringInfoV01 array image (§4.7; no shared memory) |
| 8 | AC EVO | 0 → `Local\acevo_pmf_physics`, 1 → `…_graphics`, 2 → `…_static` [O7] |

### 3.4 Version fields carried in SOURCE_INFO and the decode gate

| Game | `version_a` / `version_b` | Mac decoder accepts | `decode_size` |
|---|---|---|---|
| R3E | `version_major` @0 / `version_minor` @4 [O1] | (3, 4) and (3, 5) only. 3.5 has the same offsets as 3.4 ([O3]: 3.5 only renamed reserved fields) | 43 996 |
| LMU | `generic.gameVersion` @64 (e.g. 14000 = 1.4 per [C2]) / 0 | any build ≥ the first one recorded, **and** `region_size` ≥ 324 820. After a game update, re-check with the plausibility windows (§11.3) before trusting it | 324 820 |
| ACC | 0 / 0. The version is the `smVersion` wchar string in static @0 [O6] | `smVersion` values on an accept-list built from recordings. **The value is unknown today** | 800 / 1588 / 820 (§4.3.3 caveat) |
| iRacing | `header.ver` @0 / `header.tickRate` @8 [C4] | `ver ≥ 1` (pyirsdk's own check [C4]) | min(region_size, 1164 KiB) |
| AC | 0 / 0. `smVersion` in static @0 | accept-list (unknown today) | 800 / 1588 / 820 (the AC decoder reads only its prefix, §4.5) |
| AMS2 | `mVersion` @0 / `mBuildVersionNumber` @4 [C1] | `mVersion` = 14 ([C1] constant). **Unverified** | 23 100 |
| rF2 | the plugin's own version / rF2 `Startup(version)` value [O9] | the plugin's own version | 1888 / 548 / 584 × 128 |
| AC EVO | 0 / 0. `sm_version` char[15] in static @0 [C7][C1] | `sm_version` accept-list. **Physics only until [O8] is read** | 800 / min(region, 8192) / min(region, 2048) |

### 3.5 Coherence guards (torn reads)

| Game | Guard | Basis |
|---|---|---|
| R3E | Read `player.game_simulation_ticks` (abs @44), copy, read it again. If it changed, retry (≤ 3). For the field stream, also re-read `num_cars` @2008 | `r3e.h` documents no lock or sequence field [O1]. **This guard is pitwall's choice**, not a Sector3 recommendation |
| LMU | Witness read: before and after the copy, compare scoring `mCurrentET` (abs 1700), the player's `mElapsedTime`, `mNumVehicles` (abs 1736) and `activeVehicles` (abs 128464). Retry ≤ 5 | [C2] `reader.rs`. That tool saw car counts disagree in 0.04–0.08 % of samples, but only while cars were joining |
| ACC / AC / AC EVO | `packetId` @0 of physics and graphics: equal before and after the copy | [O6] "Current step index"; [O7] "Incrementing counter — detect new data packets by comparing to previous value"; [C7] |
| iRacing | Pick the buffer with the highest `tick_count`. Copy it only if its `tick_count_begin` (+8) equals `tick_count` (+0) before and after the copy. If `tick_count_begin` reads 0 (older builds), use pyirsdk's legacy rule: the **second**-newest buffer | [C4] (`tick_count_begin` "updated BEFORE write starts (for torn read detection)", added 2026-06-09) |
| AMS2 | `mSequenceNumber` (abs 7320) must be **even** and unchanged before and after the copy | [C1] skips odd sequence numbers. **Unverified** against the game header |
| rF2 | none needed: the plugin copies inside the game's callback | [O9] |

### 3.6 Streams, rates and bandwidth

These are defaults; every cap is configurable. Bandwidth adds 44 B of header per datagram.

| Game | Stream 0 (player) | Stream 1 (field) | Stream 2 (static) | ≈ KB/s at the caps |
|---|---|---|---|---|
| R3E | `[0, 2012)` on tick change, ≤ 100 Hz (2 parts) | `[2008, 2012 + 328·n)`, n = `num_cars` ≤ 128, at 10 Hz | — (static data is inside stream 0) | 210 player; +112 field (34 cars) |
| LMU | regions `[0,72)` + `[128464,128467)` + player record `[128468+1888·i, +1888)`, ≤ 100 Hz (2 parts) | `[1632,2180)` + `[2192, 2192+584·n)` (or only the player's row), 5 Hz | — | 205; +102 field (34 cars) |
| ACC | physics `[0,800)` ≤ 100 Hz; graphics `[0,1588)` ≤ 60 Hz (separate snapshots) | (all-car coordinates are inside graphics) | static `[0,820)` 1 Hz + on change | ≈ 190 |
| iRacing | header `[0, 48+16·numBuf)` + the coherent line `[buf_offset, +bufLen)` on each new tick | — | layout: header + var headers `[varHeaderOffset, +144·numVars)` on change and 1 Hz. Stream 3: header + YAML `[sessionInfoOffset, +sessionInfoLen)` when `sessionInfoUpdate` changes | `bufLen` × 60. **`bufLen` is only known at runtime** |
| AC | same as ACC | — | same as ACC | ≈ 190 |
| AMS2 | `[0,28)` + participant `[28+100·i, +100)` (i = `mViewedParticipantIndex`, abs 20) + `[6428, 7408)`, ≤ 100 Hz | full page `[0, 23100)` at 2 Hz | — | ≈ 115 + 47 |
| rF2 | TelemInfoV01 per `UpdateTelemetry` (player only) | ScoringInfoV01 + VehicleScoringInfoV01 × n per `UpdateScoring` (~5 Hz [O9]) | — | ≈ 200 |
| AC EVO | physics `[0,800)` decimated from ≈ 333 Hz [C7] to ≤ 100 Hz | graphics (raw) ≤ 30 Hz | static 1 Hz | ≈ 85 + 250 |

All of these fit easily on 100 Mb/s+ Ethernet or decent Wi-Fi. Lowering the caps is the only knob needed.

### 3.7 Privacy and safety

These mappings carry personal data:

| Game | Personal fields |
|---|---|
| R3E | `player_name` @1324; per-driver `driver_info.name`, `user_id` |
| LMU | `mPlayerName`, `mPlrFileName`; per-car `mDriverName`, **`mSteamID`** (u64, VSI +536); server name and public IP; and a **paths block** (abs 332–1631) with Windows user paths. The plans in §3.6 never send the paths block |
| ACC | player first/last/nick names (static 200/266/332) |
| iRacing | the session YAML (driver names, user ids) [P1] |
| AMS2 | participant names |
| AC EVO | driver name and surname (graphics, candidate offsets 3020/3053) |

Rules:
- By default the agent **zeroes name, id and path bytes of non-player cars** and of server fields in field streams,
  and sets `snapshot_flags` bit2.
- Player-name fields are zeroed too unless option bit3 is set.
- iRacing YAML (stream 3) is sent only when option bit3 is set. Otherwise the agent extracts nothing from it, and the
  Mac falls back to `TrackID`-less operation (§4.4.4).
- Captures of other people's online sessions must never be committed or redistributed (the same rule as [P3] L0b-ACC).
- **Network policy:**
  - accept `SUBSCRIBE` only from RFC 1918 or link-local source addresses, or from a configured allow-list;
  - bind the control socket to the LAN interface, not to `0.0.0.0` on a machine with a public interface;
  - the agent sends nothing until it has a subscriber, apart from optional beacons.

---

## 4. Per-game specifications

All offsets are bytes from the start of the mapping (or record) in decimal. Types: `i32`/`u32`/`f32`/`f64` and so on;
`i32` booleans are 0/1. Byte order is little-endian. "Use" says where a field maps in pitwall's model
(`model/telemetry.py` [P4]).

### 4.1 RaceRoom (`$R3E`, game 1): first target

#### 4.1.1 Facts

- **Mapping.** `$R3E` (`R3E_SHARED_MEMORY_NAME`). It is opened with `OpenFileMapping(FILE_MAP_READ, …)` and needs
  no plugin or setting [O1][O2].
- **Layout.** `#pragma pack(push, 1)`. The struct `r3e_shared` is **43 996 bytes** at v3.5 [O1].
- **Coverage.**
  - Player data: offsets 0–2011.
  - `num_cars` @2008.
  - Then `all_drivers_data_1[128]` × 328 B @2012, "in place order" [O1].
- **Version.** `version_major` @0 = 3 and `version_minor` @4 = 5 in the current header [O1].
  - 3.1 broke backward compatibility (2025-09-11).
  - 3.4 inserted `r3e_int32 user_id` at the start of `r3e_playerdata`. That shifted every later field by 4 B.
  - 3.5 replaced reserved fields with same-size fields [O3].
  - **So decode only (3,4) and (3,5).** Anything else is raw-capture only (option bit 2).
- **Self-description.**
  - `all_drivers_offset` @8 is commented "Offset to num_cars", and the compiled `num_cars` is @2008.
  - `driver_data_size` @12 should be 328.
  - Check both at attach. A mismatch means "unknown layout".
- **Conventions [O1].**
  - "-1 = N/A" sentinels throughout: −1, −1.0, −2 for `gear`, and −1000.0 for `time_delta_best_self`. Map every
    sentinel to `None`.
  - Strings are `r3e_u8char` "UTF-8 code unit" arrays, NUL-padded.
  - World `car_cg_location` has Y up. Local acceleration "+X=left, +Y=up, +Z=back".
  - Wheel order FL, FR, RL, RR (`r3e_tire_index_enum`).
- **Rate.** **Not documented.** Physics time is in ticks of 1/400 s (`game_simulation_ticks`) [O1]. That is the
  simulation resolution, not the mapping write rate. Measure the rate from tick deltas in the first recording.
- **Licence.** Unlicense: "Anyone is free to copy, modify, publish, use, compile, sell, or distribute" [O2]. pitwall
  may vendor `r3e.h` or write its own decoder; either way it should record provenance in `docs/licences.md`.

#### 4.1.2 Top-level layout (`r3e_shared`, 43 996 B). Fields pitwall uses are marked ●

| Off | Size | Type | Field | Units / notes [O1] |
|---|---|---|---|---|
| 0 | 4 | i32 | `version_major` ● | 3 |
| 4 | 4 | i32 | `version_minor` ● | 5 (3.4 has the same layout) |
| 8 | 4 | i32 | `all_drivers_offset` ● | "Offset to num_cars" (validate) |
| 12 | 4 | i32 | `driver_data_size` ● | 328 |
| 16 | 4 | i32 | `game_mode` | enum −1…7 (track test, leaderboard, competition, single race, championship, MP, MP ranked, try-before-buy) |
| 20 | 4 | i32 | `game_paused` ● | → `FrameQuality.PAUSED` |
| 24 | 4 | i32 | `game_in_menus` ● | → `NOT_RACING` |
| 28 | 4 | i32 | `game_in_replay` ● | → `REPLAY_OR_SPECTATING` |
| 32 | 4 | i32 | `game_using_vr` | |
| 36 | 4 | i32 | `game_player_in_garage` ● | → `NOT_RACING` (3.5 name; 3.4 `game_unused1`) |
| 40 | 560 | struct | `player` (`r3e_playerdata`, §4.1.3) | high-precision player data |
| 600 | 64 | u8[64] | `track_name` ● | UTF-8 |
| 664 | 64 | u8[64] | `layout_name` ● | UTF-8 |
| 728 | 4 | i32 | `track_id` ● | names via [O4] |
| 732 | 4 | i32 | `layout_id` ● | names via [O4] |
| 736 | 4 | f32 | `layout_length` ● | m (unit not stated in the header; "length" plus metre-valued `lap_distance` → verify) |
| 740 | 12 | f32×3 | `sector_start_factors` ● | sector1..3 starts. Presumed lap fractions (name only): **verify** |
| 752 | 12 | i32×3 | `race_session_laps` | −1 = N/A |
| 764 | 12 | i32×3 | `race_session_minutes` | |
| 776 | 4 | i32 | `event_index` | |
| 780 | 4 | i32 | `session_type` ● | −1 N/A, 0 practice, 1 qualify, 2 race, 3 warmup |
| 784 | 4 | i32 | `session_iteration` | 1-based |
| 788 | 4 | i32 | `session_length_format` | 0 time, 1 laps, 2 time + extra lap |
| 792 | 4 | f32 | `session_pit_speed_limit` ● | m/s |
| 796 | 4 | i32 | `session_phase` ● | 1 garage, 2 gridwalk, 3 formation, 4 countdown, 5 green, 6 checkered |
| 800 | 4 | i32 | `start_lights` | 0 off, 1–5 red, 6 green |
| 804 | 4 | i32 | `tire_wear_active` | −1, 0 off, 1–4 multiplier |
| 808 | 4 | i32 | `fuel_use_active` | same |
| 812 | 4 | i32 | `number_of_laps` ● | −1 if not a race |
| 816 | 4 | f32 | `session_time_duration` | s, −1 N/A |
| 820 | 4 | f32 | `session_time_remaining` ● | s |
| 824 | 4 | i32 | `max_incident_points` | |
| 828, 832 | 4+4 | f32 | `event_unused1/2` | reserved |
| 836 | 4 | i32 | `pit_window_status` | −1…4 |
| 840, 844 | 4+4 | i32 | `pit_window_start/end` | minutes or laps |
| 848 | 4 | i32 | `in_pitlane` ● | −1/0/1 |
| 852 | 4 | i32 | `pit_menu_selection` | |
| 856 | 48 | i32×12 | `pit_menu_state` | |
| 904 | 4 | i32 | `pit_state` ● | 0 none, 1 requested, 2 entered pit lane, 3 stopped at pit spot, 4 exiting |
| 908, 912 | 4+4 | f32 | `pit_total_duration`, `pit_elapsed_time` | s |
| 916 | 4 | i32 | `pit_action` | bitmask |
| 920 | 4 | i32 | `num_pitstops` | |
| 924, 928 | 4+4 | f32 | `pit_min_duration_total/left` | s |
| 932 | 56 | struct | `flags` (yellow @+0, sector_yellow[3] @+16, closest_yellow_distance_into_track @+28 (m), blue @+32, black @+36, green @+40, checkered @+44, white @+48, black_and_white @+52) | −1/0/1 |
| 988 | 4 | i32 | `position` ● | 1 = first |
| 992 | 4 | i32 | `position_class` | |
| 996 | 4 | i32 | `finish_status` | −1…5 |
| 1000 | 4 | i32 | `cut_track_warnings` | |
| 1004 | 20 | f32×5 | `penalties` (drive_through, stop_and_go, pit_stop, time_deduction, slow_down) | −1 none pending |
| 1024 | 4 | i32 | `num_penalties` | |
| 1028 | 4 | i32 | `completed_laps` ● | "If this value is 6, the car is on it's 7th lap. -1 = n/a" |
| 1032 | 4 | i32 | `current_lap_valid` | (no comment in header) |
| 1036 | 4 | i32 | `track_sector` ● | **base (0 or 1) undocumented: verify** |
| 1040 | 4 | f32 | `lap_distance` ● | m (header gives no unit for the player field; the driver_data one is the same name). Verify against `layout_length` |
| 1044 | 4 | f32 | `lap_distance_fraction` ● | 0.0–1.0, −1.0 = N/A |
| 1048, 1052 | 4+4 | f32 | `lap_time_best_leader`, `…_class` | s |
| 1056 | 12 | f32×3 | `session_best_lap_sector_times` | s |
| 1068 | 4 | f32 | `lap_time_best_self` ● | s, −1.0 = N/A |
| 1072 | 12 | f32×3 | `sector_time_best_self` | s. **Cumulative or per-sector is undocumented: verify** |
| 1084 | 4 | f32 | `lap_time_previous_self` ● | s |
| 1088 | 12 | f32×3 | `sector_time_previous_self` ● | s (same caveat) |
| 1100 | 4 | f32 | `lap_time_current_self` ● | s |
| 1104 | 12 | f32×3 | `sector_time_current_self` | s |
| 1116–1132 | 5×4 | f32 | `lap_time_delta_leader`, `…_leader_class`, `time_delta_front`, `time_delta_behind`, `time_delta_best_self` | s (−1000.0 = N/A for the last) |
| 1136 | 36 | f32×9 | `best_individual_sector_time_self/leader/leader_class` | s |
| 1172 | 4 | i32 | `incident_points` | |
| 1176 | 4 | i32 | `lap_valid_state` ● | −1 N/A, 0 this and next valid, 1 this invalid, 2 this and next invalid |
| 1180 | 4 | i32 | `prev_lap_valid` ● | −1, 0 invalid, 1 valid |
| 1184, 1188 | 4+4 | f32 | `discharge_rate`, `brake_regen` | 0–1 (3.5) |
| 1192 | 4 | f32 | `unused1` | |
| 1196 | 128 | struct | `vehicle_info` ● (`r3e_driver_info`, §4.1.4): `class_id` @1264, `model_id` @1268 | car identity |
| 1324 | 64 | u8[64] | `player_name` | **personal**, scrubbed |
| 1388 | 4 | i32 | `control_type` ● | 0 player, 1 AI, 2 remote, 3 replay |
| 1392 | 4 | f32 | `car_speed` ● | m/s |
| 1396 | 4 | f32 | `engine_rps` ● | rad/s |
| 1400 | 4 | f32 | `max_engine_rps` ● | rad/s |
| 1404 | 4 | f32 | `upshift_rps` | rad/s |
| 1408 | 4 | i32 | `gear` ● | −2 N/A, −1 R, 0 N, 1… (EVs report 2 when regen braking is on) |
| 1412 | 4 | i32 | `num_gears` | |
| 1416 | 12 | f32×3 | `car_cg_location` | world, Y up |
| 1428 | 12 | f32×3 | `car_orientation` ● | pitch, yaw, roll (rad) |
| 1440 | 12 | f32×3 | `local_acceleration` ● | m/s², +X left, +Y up, +Z back |
| 1452 | 4 | f32 | `total_mass` | kg |
| 1456 | 4 | f32 | `fuel_left` ● | l |
| 1460 | 4 | f32 | `fuel_capacity` ● | l |
| 1464 | 4 | f32 | `fuel_per_lap` ● | l (estimate) |
| 1468–1476 | 3×4 | f32 | `virtual_energy_left/capacity/per_lap` | MJ |
| 1480, 1484 | 4+4 | f32 | `engine_temp`, `engine_oil_temp` | °C |
| 1488, 1492 | 4+4 | f32 | `fuel_pressure`, `engine_oil_pressure` | kPa |
| 1496 | 4 | f32 | `turbo_pressure` | bar |
| 1500 | 4 | f32 | `throttle` | 0–1, −1 N/A ("Not valid for AI or remote players") |
| 1504 | 4 | f32 | `throttle_raw` ● | 0–1 |
| 1508 | 4 | f32 | `brake` | 0–1 |
| 1512 | 4 | f32 | `brake_raw` ● | 0–1 |
| 1516 | 4 | f32 | `clutch` | 0–1 |
| 1520 | 4 | f32 | `clutch_raw` ● | 0–1 |
| 1524 | 4 | f32 | `steer_input_raw` ● | −1.0 – 1.0 |
| 1528 | 4 | i32 | `steer_lock_degrees` | centre to full lock |
| 1532 | 4 | i32 | `steer_wheel_range_degrees` | |
| 1536 | 20 | i32×5 | `aid_settings` (abs @1536, tc @1540, esp, countersteer, cornering) ● | −1 N/A, 0 off, 1 on, **5 = currently active** |
| 1556 | 16 | i32×4 | `drs` (equipped, available, numActivationsLeft, engaged) | |
| 1572 | 4 | i32 | `pit_limiter` | |
| 1576 | 20 | | `push_to_pass` | |
| 1596 | 4 | f32 | `brake_bias` ● | "biased towards the **back** wheels (0.3 = 30%)" |
| 1600–1612 | 4×4 | | `drs_numActivationsTotal`, `ptp_numActivationsTotal`, `battery_soc` (0–100), `water_left` (l) | |
| 1616 | 4 | i32 | `abs_setting` | |
| 1620 | 4 | i32 | `headlights` | |
| 1624 | 4 | i32 | `steer_wheel_max_rotation` | 3.5 |
| 1628 | 4 | i32 | `tire_type` | deprecated |
| 1632 | 16 | f32×4 | `tire_rps` | rad/s |
| 1648 | 16 | f32×4 | `tire_speed` | m/s |
| 1664 | 16 | f32×4 | `tire_grip` | 0–1 |
| 1680 | 16 | f32×4 | `tire_wear` ● | 0–1, −1 N/A. **Direction (1 = new or worn) undocumented: verify** |
| 1696 | 16 | i32×4 | `tire_flatspot` | |
| 1712 | 16 | f32×4 | `tire_pressure` ● | kPa |
| 1728 | 16 | f32×4 | `tire_dirt` | 0–1 |
| 1744 | 96 | 4 × `r3e_tire_temp` (24 B: `current_temp[3]` L/C/R @+0, optimal @+12, cold @+16, hot @+20) ● | | °C, "three points across the tread". Whether "left" means the car's left side is **unverified** |
| 1840–1852 | 4×4 | i32 | `tire_type_front/rear`, `tire_subtype_front/rear` ● | subtype: 0 primary, 1 alternate, 2 soft, 3 medium, 4 hard |
| 1856 | 64 | 4 × `r3e_brake_temp` (16 B: current @+0, optimal, cold, hot) ● | | °C |
| 1920 | 16 | f32×4 | `brake_pressure` | kN |
| 1936 | 4 | i32 | `traction_control_setting` ● | |
| 1940, 1944 | 4+4 | i32 | `engine_map_setting`, `engine_brake_setting` | |
| 1948 | 4 | f32 | `traction_control_percent` | 0–100 |
| 1952 | 16 | i32×4 | `tire_on_mtrl` | material enum (tarmac, grass, dirt, gravel, rumble, concrete) |
| 1968 | 16 | f32×4 | `tire_load` | N |
| 1984 | 24 | f32×6 | `car_damage` (engine, transmission, aerodynamics, suspension, 2 unused) | 0–1, −1 N/A |
| 2008 | 4 | i32 | `num_cars` ● | |
| 2012 | 41 984 | 128 × `r3e_driver_data` | `all_drivers_data_1` | field stream only |

#### 4.1.3 `r3e_playerdata` (560 B at abs 40). Absolute offset = 40 + rel

| Rel | Abs | Type | Field ([O1] units) |
|---|---|---|---|
| 0 | 40 | i32 | `user_id` (3.4+; **personal**) |
| 4 | 44 | i32 | `game_simulation_ticks` ● (1 tick = 1/400 s): change counter and `frame_id` |
| 8 | 48 | f64 | `game_simulation_time` ● (s) → `session_time_s` |
| 16 | 56 | f64×3 | `position` ● (world; Y up per `car_cg_location` note) |
| 40 | 80 | f64×3 | `velocity` ● (world m/s) |
| 64 | 104 | f64×3 | `local_velocity` (m/s) |
| 88 | 128 | f64×3 | `acceleration` (world m/s²) |
| 112 | 152 | f64×3 | `local_acceleration` (m/s²) |
| 136 | 176 | f64×3 | `orientation` ("Euler angles") |
| 160 | 200 | f64×3 | `rotation` |
| 184 | 224 | f64×3 | `angular_acceleration` |
| 208 | 248 | f64×3 | `angular_velocity` (rad/s) |
| 232 | 272 | f64×3 | `local_angular_velocity` (rad/s) |
| 256 | 296 | f64×3 | `local_g_force` ● ("Driver g-force local to car"; axis signs: verify) |
| 280–344 | 320–384 | f64×9 | steering_force, steering_force_percentage, engine_torque, current_downforce (N), voltage, ers_level, power_mgu_h, power_mgu_k, torque_mgu_k ("currently unused" for the last five) |
| 352 | 392 | f64×4 | `suspension_deflection` |
| 384 | 424 | f64×4 | `suspension_velocity` |
| 416 | 456 | f64×4 | `camber` |
| 448 | 488 | f64×4 | `ride_height` |
| 480–528 | 520–568 | f64×7 | front_wing_height, front/rear_roll_angle, third-spring deflection/velocity front/rear |
| 536–552 | 576–592 | f64×3 | unused |

#### 4.1.4 `r3e_driver_info` (128 B) and `r3e_driver_data` (328 B; entry *k* at 2012 + 328·k)

`r3e_driver_info`:

| Rel | Type | Field |
|---|---|---|
| 0 | u8[64] | `name` (**personal**, scrubbed) |
| 64 | i32 | `car_number` |
| 68 | i32 | `class_id` |
| 72 | i32 | `model_id` |
| 76 | i32 | `team_id` |
| 80 | i32 | `livery_id` |
| 84 | i32 | `manufacturer_id` |
| 88 | i32 | `user_id` (**personal**) |
| 92 | i32 | `slot_id` |
| 96 | i32 | `class_performance_index` |
| 100 | i32 | `engine_type` |
| 104 | f32 | `car_width` |
| 108 | f32 | `car_length` |
| 112 | f32 | `rating` |
| 116 | f32 | `reputation` |
| 120 | f32×2 | unused |

`r3e_driver_data`:

| Rel | Type | Field |
|---|---|---|
| 0 | 128 | `driver_info` |
| 128 | i32 | `finish_status` |
| 132 | i32 | `place` |
| 136 | i32 | `place_class` |
| 140 | f32 | `lap_distance` |
| 144 | f32 | `lap_distance_fraction` |
| 148 | f32×3 | `position` |
| 160 | i32 | `track_sector` |
| 164 | i32 | `completed_laps` |
| 168 | i32 | `current_lap_valid` |
| 172 | f32 | `lap_time_current_self` |
| 176 | f32×3 | `sector_time_current_self` |
| 188 | f32×3 | `sector_time_previous_self` |
| 200 | f32×3 | `sector_time_best_self` |
| 212 | f32 | `time_delta_front` |
| 216 | f32 | `time_delta_behind` |
| 220 | i32 | `pitstop_status` |
| 224 | i32 | `in_pitlane` |
| 228 | i32 | `num_pitstops` |
| 232 | f32×5 | `penalties` |
| 252 | f32 | `car_speed` (m/s) |
| 256–268 | i32×4 | `tire_type_front/rear`, `tire_subtype_front/rear` |
| 272 | f32 | `base_penalty_weight` |
| 276 | f32 | `aid_penalty_weight` |
| 280 | i32 | `drs_state` |
| 284 | i32 | `ptp_state` |
| 288 | f32 | `virtual_energy` |
| 292 | i32 | `penaltyType` |
| 296 | i32 | `penaltyReason` |
| 300 | i32 | `engineState` |
| 304 | f32×3 | `orientation` |
| 316 | f32×3 | unused |

The driver array gives an all-car **lap-distance and speed** field, the same shape as the F1 and ACC field models [P3].

#### 4.1.5 Mapping to pitwall

| pitwall field | Source (abs offset) | Conversion |
|---|---|---|
| `speed_kph` | `car_speed` @1392 | ×3.6 |
| `throttle` / `brake` / `clutch` | `throttle_raw` @1504 / `brake_raw` @1512 / `clutch_raw` @1520 | none. Raw is the pedal; the header does not say how `throttle` @1500 differs, so record both and compare in fixtures |
| `steering` | `steer_input_raw` @1524 | none (−1..1). The **sign** (left = −1?) must be verified, because the header gives only the range |
| `gear` | `gear` @1408 | −2 → `None`; otherwise as-is (matches pitwall: −1 R, 0 N) |
| `rpm` / `max_rpm` | `engine_rps` @1396 / `max_engine_rps` @1400 | ×60/(2π) |
| `pos_x/y/z_m` | `player.position` @56 | none. Ground plane (`pos_x_m`, `pos_z_m`): Y is up |
| `vel_*` | `player.velocity` @80 | none |
| `g_lon` / `g_lat` / `g_vert` | `local_acceleration` @1440 | g_lon = −z/9.80665 (+Z is back); g_lat = x/9.80665 (+X is left; pitwall sign per adapter docs); g_vert = y/9.80665 |
| `yaw/pitch/roll_rad` | `car_orientation` @1428 (pitch, yaw, roll) | none |
| `session_time_s` / `frame_id` | @48 / @44 | none |
| `lap_number` | `completed_laps` @1028 | +1; −1 → `None` |
| `lap_distance_m` | `lap_distance` @1040 | none (verify the unit) |
| `current_lap_time_ms` / `last_lap_time_ms` | @1100 / @1084 | s ×1000; −1.0 → `None` |
| `sector` | `track_sector` @1036 | **base unverified** |
| `lap_invalid` | `lap_valid_state` @1176 | 0 → False; 1/2 → True; −1 → `None` |
| `pit_status` | `in_pitlane` @848, `pit_state` @904 | pit_state 3 → 2; in_pitlane 1 → 1; else 0 |
| `race_position` | @988 | none |
| `tyre_surface_temp_c` | `tire_temp[i].current_temp[1]` (centre) at 1744 + 24·i + 4 | none. Keep L/C/R in `extra` |
| `tyre_pressure_psi` | `tire_pressure` @1712 | kPa × 0.1450377 |
| `brake_temp_c` | 1856 + 16·i | none |
| `tyre_wear_pct` | `tire_wear` @1680 | **withhold until the direction is verified** |
| `tyre_compound` | `tire_subtype_front` @1848 | soft/medium/hard (2/3/4); primary/alternate are game-specific |
| `fuel_litres` / `fuel_capacity_litres` | @1456 / @1460 | none |
| `brake_bias_front_pct` | `brake_bias` @1596 | (1 − x) × 100 |
| `traction_control` / `abs_active` | @1936 / `aid_settings.abs` @1536 | abs_active = (value == 5) |
| `SessionInfo.track_id` | @728, @732 | `"r3e:{track_id}:{layout_id}"`; names from @600/@664 or [O4] |
| `SessionInfo.track_length_m` | `layout_length` @736 | none |
| `SessionInfo.car_id` | `vehicle_info.model_id` @1268 | `"r3e:{model_id}"`; class @1264 |
| `SessionInfo.session_type` | @780 | enum |
| `SessionInfo.pit_speed_limit_kph` | @792 | ×3.6 |
| `LapCompletion` | `completed_laps` increments | `lap_time_previous_self`, `sector_time_previous_self`, `prev_lap_valid` |

**Missing in R3E:**
- weather: no air or track temperature, rain or wind;
- tyre carcass and inner temperatures;
- the setup;
- the documented write rate;
- sector-time semantics.

**Unverified:**
- the `track_sector` base;
- the `sector_start_factors` meaning;
- the `tire_wear` direction;
- the steering sign;
- `layout_length` and `lap_distance` units (presumed metres).

### 4.2 Le Mans Ultimate (`LMU_Data`, game 2)

#### 4.2.1 Facts

- **Mapping.** `LMU_Data`, created by the game itself with no plugin installed [C2][C3]. The game ships its header,
  `SharedMemoryInterface.hpp`, in `Support\SharedMemoryInterface` [C2][C3]. The v1.2 notes say "Added the
  SharedMemory Header file to the support folder for the new shared memory implementation" [N1].
- **Setting.** "Settings → Gameplay → Enable Plugins → **ON**, then restart LMU". The switch also governs the built-in
  shared memory and needs a full restart [C2] README.
- **Size and packing.** `SharedMemoryObjectOut` is **324 820 B**, `pack(4)`. Vehicle slots: **104** (not rF2's 128)
  [C2][C3].
- **Rates.** Telemetry **100 Hz**, scoring **5 Hz** [C2] (measured by its `lmu-probe` at 200 Hz sampling on LMU 1.4).
- **No version block.** The rF2 plugin had `mVersionUpdateBegin/End`; LMU_Data does not [C2]. Use `gameVersion` @64,
  where 14000 = 1.4 [C2].
- **Lock objects.** [C1] states the game's header defines a `SharedMemoryLock` built on a mapping named
  `LMU_SharedMemoryLockData` (8 B: `{waiters, busy}`) and an event `LMU_SharedMemoryLockEvent`.
  - [C1] takes the lock with an interlocked compare-exchange on `busy`.
  - [C2] does not use it and uses witness reads.
  - **Conflicting practice; the header itself was not read.** v1 of the agent uses the witness read only (§3.5),
    because taking the lock could stall the game's own writer.
- **Anti-cheat.** [C2] reports its reads work "in online sessions (EAC-protected)".
- **Licence.**
  - The game-shipped header's notice is **unchecked**; it is not readable from the Mac.
  - pitwall implements from facts in two MIT mirrors [C2][C3], cross-checked against S397's rF2 records [O9].
  - Before shipping, read the header notice on a Windows install and record it in `docs/licences.md`.
  - Do not use TinyPedal (GPL) or the GPL rF2 plugin [C9].

#### 4.2.2 Container layout (absolute offsets)

| Abs | Size | Field | Notes |
|---|---|---|---|
| 0 | 64 | `generic.events` = 16 × u32 `SME_ENTER, SME_EXIT, SME_STARTUP, SME_SHUTDOWN, SME_LOAD, SME_UNLOAD, SME_START_SESSION, SME_END_SESSION, SME_ENTER_REALTIME, SME_EXIT_REALTIME, SME_UPDATE_SCORING, SME_UPDATE_TELEMETRY, SME_INIT_APPLICATION, SME_UNINIT_APPLICATION, SME_SET_ENVIRONMENT, SME_FFB` | [C2] reads them as per-event counters "bumped by the game as callbacks fire"; [C3] treats them as flags. **Semantics unverified**: record and compare |
| 64 | 4 | `generic.gameVersion` (i32) ● | e.g. 14000 |
| 68 | 4 | `generic.FFBTorque` (f32) | |
| 72 | 260 | `generic.appInfo` (`mAppWindow` u64 @72, `mWidth`, `mHeight`, `mRefreshRate`, `mWindowed` u32, `mOptionsLocation` u8 @96 (0 main UI, 1 track loading, 2 monitor, 3 on track), `mOptionsPage` char[31], expansion[204]) | |
| 332 | 1300 | `paths` (userData, customVariables, stewardResults, playerProfile, pluginsFolder; 5 × char[260]) | **Never sent** (Windows user paths) |
| 1632 | 548 | `scoring.scoringInfo` (§4.2.4) ● | 5 Hz |
| 2180 | 12 | `scoring.scoringStreamSize` | |
| 2192 | 60 736 | `scoring.vehScoringInfo[104]` × 584 (§4.2.5) ● | row *i* at 2192 + 584·i |
| 62 928 | 65 536 | `scoring.scoringStream` | not sent |
| 128 464 | 1 | `telemetry.activeVehicles` (u8) ● | |
| 128 465 | 1 | `telemetry.playerVehicleIdx` (u8) ● | index into `telemInfo` |
| 128 466 | 1 | `telemetry.playerHasVehicle` (bool) ● | |
| 128 468 | 196 352 | `telemetry.telemInfo[104]` × 1888 (§4.2.3) ● | record *i* at 128 468 + 1888·i. Ends at 324 820 |

#### 4.2.3 Telemetry record (`TelemInfoV01` as embedded by LMU, 1888 B). Offsets relative to the record

rF2's own `TelemInfoV01` [O9] has identical offsets and sizes for 0–744. At 745 rF2 has `mExpansion[103]`, which LMU
reuses (rows marked *LMU*).

| Rel | Type | Field | Units / notes [C3][O9] |
|---|---|---|---|
| 0 | i32 | `mID` | slot id |
| 4 | f64 | `mDeltaTime` | s since last update |
| 12 | f64 | `mElapsedTime` ● | game session time (s): change counter and witness |
| 20 | i32 | `mLapNumber` ● | "current lap number" (base: verify) |
| 24 | f64 | `mLapStartET` ● | s (−1 until the first line crossing [C2]) |
| 32 | char[64] | `mVehicleName` | |
| 96 | char[64] | `mTrackName` | |
| 160 | f64×3 | `mPos` ● | world m. "left-handed, with +y pointing up" [O9] |
| 184 | f64×3 | `mLocalVel` ● | m/s, local: +x left, +y roof, +z **back** [O9] |
| 208 | f64×3 | `mLocalAccel` ● | m/s², local |
| 232 | f64×9 | `mOri[3]` ● | orientation matrix rows |
| 304 | f64×3 | `mLocalRot` | rad/s |
| 328 | f64×3 | `mLocalRotAccel` | rad/s² |
| 352 | i32 | `mGear` ● | −1 R, 0 N, 1+ |
| 356 | f64 | `mEngineRPM` ● | rpm |
| 364, 372 | f64 | `mEngineWaterTemp`, `mEngineOilTemp` | °C |
| 380 | f64 | `mClutchRPM` | |
| 388 | f64 | `mUnfilteredThrottle` ● | 0–1 |
| 396 | f64 | `mUnfilteredBrake` ● | 0–1 |
| 404 | f64 | `mUnfilteredSteering` ● | −1 (left) … +1 (right) |
| 412 | f64 | `mUnfilteredClutch` ● | 0–1 |
| 420–444 | f64×4 | `mFilteredThrottle/Brake/Steering/Clutch` | after aids |
| 452 | f64 | `mSteeringShaftTorque` | |
| 460, 468 | f64 | `mFront3rdDeflection`, `mRear3rdDeflection` | |
| 476–492 | f64×3 | `mFrontWingHeight`, `mFrontRideHeight`, `mRearRideHeight` | m |
| 500–516 | f64×3 | `mDrag`, `mFrontDownforce`, `mRearDownforce` | |
| 524 | f64 | `mFuel` ● | litres |
| 532 | f64 | `mEngineMaxRPM` ● | rev limit |
| 540 | u8 | `mScheduledStops` | |
| 541–543 | bool×3 | `mOverheating`, `mDetached`, `mHeadlights` | |
| 544 | u8×8 | `mDentSeverity` | |
| 552, 560 | f64 | `mLastImpactET`, `mLastImpactMagnitude` | |
| 568 | f64×3 | `mLastImpactPos` | |
| 592 | f64 | `mEngineTorque` | |
| 600 | i32 | `mCurrentSector` ● | zero-based; **pit-lane flag in the sign bit** (0x80000002 = entering pits from sector 3) |
| 604–607 | u8×4 | `mSpeedLimiter`, `mMaxGears`, `mFront/RearTireCompoundIndex` | |
| 608 | f64 | `mFuelCapacity` ● | l |
| 616–619 | u8×4 | `mFront/RearFlapActivated`, `mRearFlapLegalStatus`, `mIgnitionStarter` | |
| 620, 638 | char[18]×2 | `mFrontTireCompoundName`, `mRearTireCompoundName` ● | |
| 656–659 | u8×4 | `mSpeedLimiterAvailable`, `mAntiStallActivated`, `mUnused[2]` | |
| 660 | f32 | `mVisualSteeringWheelRange` | deg |
| 664 | f64 | `mRearBrakeBias` ● | fraction on rear |
| 672 | f64 | `mTurboBoostPressure` | |
| 680 | f32×3 | `mPhysicsToGraphicsOffset` | |
| 692 | f32 | `mPhysicalSteeringWheelRange` | deg |
| 696 | f64 | `mDeltaBest` | s |
| 704 | f64 | `mBatteryChargeFraction` | 0–1 |
| 712–736 | f64×4 | `mElectricBoostMotorTorque/RPM/Temperature/WaterTemperature` | |
| 744 | u8 | `mElectricBoostMotorState` | 0 n/a, 1 inactive, 2 propulsion, 3 regen |
| 745 | bool | `mLapInvalidated` ● *LMU* | |
| 746–748 | bool×3 | `mABSActive` ●, `mTCActive`, `mSpeedLimiterActive` *LMU* | |
| 749 | u8 | `mWiperState` *LMU* | |
| 750–765 | u8×16 | `mTC`, `mTCMax`, `mTCSlip`, `mTCSlipMax`, `mTCCut`, `mTCCutMax`, `mABS`, `mABSMax`, `mMotorMap`, `mMotorMapMax`, `mMigration`, `mMigrationMax`, `mFrontAntiSway`, `mFrontAntiSwayMax`, `mRearAntiSway`, `mRearAntiSwayMax` *LMU* | `mTC` @750 ● |
| 766, 767 | u8 | `mLiftAndCoastProgress`, `mTrackLimitsSteps` *LMU* | |
| 768–792 | f32×7 | `mRegen` (kW), `mStateOfCharge` (%), `mVirtualEnergy` (fraction), `mTimeGapCarAhead/Behind`, `mTimeGapPlaceAhead/Behind` *LMU* | |
| 796 | char[30] | `mVehicleModel` *LMU* | |
| 826, 827 | u8 | `mVehicleClass`, `mVehicleChampionship` *LMU* | |
| 828 | u8×20 | `mExpansion` | |
| 848 | 4 × 260 | `mWheels[4]` (FL, FR, RL, RR) ● | wheel *w* at 848 + 260·w |

**Wheel record (260 B).** rF2 is identical for 0–235; at 236 rF2 has `mExpansion[24]` [O9].

| Rel | Type | Field | Units / notes |
|---|---|---|---|
| 0 | f64 | `mSuspensionDeflection` | m |
| 8 | f64 | `mRideHeight` | m |
| 16 | f64 | `mSuspForce` | N |
| 24 | f64 | `mBrakeTemp` ● | rF2 header: °C [O9]. [C2] lists "whether mBrakeTemp is still Kelvin" in LMU 1.4 as an **open question** |
| 32 | f64 | `mBrakePressure` | 0–1 |
| 40 | f64 | `mRotation` | rad/s |
| 48–72 | f64×4 | `mLateralPatchVel`, `mLongitudinalPatchVel`, `mLateralGroundVel`, `mLongitudinalGroundVel` | |
| 80 | f64 | `mCamber` | rad |
| 88–104 | f64×3 | `mLateralForce`, `mLongitudinalForce`, `mTireLoad` | N |
| 112 | f64 | `mGripFract` | |
| 120 | f64 | `mPressure` ● | kPa |
| 128 | f64×3 | `mTemperature` ● | **Kelvin**, left/centre/right ("not to be confused with inside/center/outside") [O9] |
| 152 | f64 | `mWear` ● | "0.0-1.0, fraction of maximum". **Direction to verify** |
| 160 | char[16] | `mTerrainName` | |
| 176 | u8 | `mSurfaceType` | 0 dry, 1 wet, 2 grass, 3 dirt, 4 gravel, 5 rumble, 6 special |
| 177, 178 | bool | `mFlat`, `mDetached` | |
| 179 | u8 | `mStaticUndeflectedRadius` | cm |
| 180–196 | f64×3 | `mVerticalTireDeflection`, `mWheelYLocation`, `mToe` | |
| 204 | f64 | `mTireCarcassTemperature` ● | K |
| 212 | f64×3 | `mTireInnerLayerTemperature` ● | K |
| 236 | f32 | `mOptimalTemp` *LMU* | °C |
| 240, 241 | u8 | `mCompoundIndex`, `mCompoundType` (0 soft, 1 medium, 2 hard, 3 wet) *LMU* | |
| 242 | u8×18 | `mExpansion` | |

#### 4.2.4 Scoring info (`ScoringInfoV01`, 548 B at abs 1632). rF2 is identical for 0–339; at 340 it has `mExpansion[200]` [O9]

| Rel | Type | Field | Notes |
|---|---|---|---|
| 0 | char[64] | `mTrackName` ● | track identity (no numeric id) |
| 64 | i32 | `mSession` ● | 0 testday, 1–4 practice, 5–8 qual, 9 warmup, 10–13 race |
| 68 | f64 | `mCurrentET` ● | s; witness |
| 76 | f64 | `mEndET` | |
| 84 | i32 | `mMaxLaps` | `i32::MAX` in timed races [C2] |
| 88 | f64 | `mLapDist` ● | **track length**, m |
| 96 | 8 B | `mResultsStreamPointer` | pointer, meaningless off-process |
| 104 | i32 | `mNumVehicles` ● | |
| 108 | u8 | `mGamePhase` ● | 0 before, 1 recon, 2 gridwalk, 3 formation, 4 countdown, 5 green, 6 FCY/SC, 7 stopped, 8 over, 9 paused |
| 109 | i8 | `mYellowFlagState` | −1…7 |
| 110 | u8×3 | `mSectorFlag` | LMU: 1 = yellow, **11 = clear** [C2] |
| 113–115 | u8, u8, bool | `mStartLight`, `mNumRedLights`, `mInRealtime` | |
| 116 | char[32] | `mPlayerName` | personal |
| 148 | char[64] | `mPlrFileName` | personal |
| 212–236 | f64×4 | `mDarkCloud`, `mRaining` ● (0–1), `mAmbientTemp` ● (°C), `mTrackTemp` ● (°C) | |
| 244 | f64×3 | `mWind` | |
| 268, 276 | f64 | `mMinPathWetness`, `mMaxPathWetness` | 0–1 |
| 284–295 | | `mGameMode` u8, `mIsPasswordProtected` bool, `mServerPort` u16, `mServerPublicIP` u32 (personal), `mMaxPlayers` i32 | |
| 296 | char[32] | `mServerName` | |
| 328 | f32 | `mStartET` | |
| 332 | f64 | `mAvgPathWetness` | |
| 340 | f32 | `mSessionTimeRemaining` *LMU* | s |
| 344 | f32 | `mTimeOfDay` *LMU* | s |
| 348–352 | bool, u8×4 | `mIsFixedSetup`, `mTrackGripLevel` (0 green … 4 saturated), `mCloudCoverage` (0 clear … 10 storm), `mTrackLimitsStepsPerPenalty/PerPoint` *LMU* | |
| 353 | u8×187 | `mExpansion` | |
| 540 | 8 B | `mVehiclePointer` | pointer |

#### 4.2.5 Vehicle scoring (`VehicleScoringInfoV01`, 584 B; row *i* at abs 2192 + 584·i). rF2 is identical for 0–535; at 536 it has `mExpansion[48]` [O9]

| Rel | Type | Field | Notes |
|---|---|---|---|
| 0 | i32 | `mID` | matches telemetry `mID` |
| 4 | char[32] | `mDriverName` | personal |
| 36 | char[64] | `mVehicleName` | |
| 100 | i16 | `mTotalLaps` ● | laps completed |
| 102 | i8 | `mSector` | **0 = sector 3**, 1 = sector 1, 2 = sector 2 [O9] |
| 103 | i8 | `mFinishStatus` | |
| 104 | f64 | `mLapDist` ● | m around the track: the **only** lap-distance source (5 Hz) |
| 112, 120 | f64 | `mPathLateral`, `mTrackEdge` | |
| 128–184 | f64×8 | `mBestSector1`, `mBestSector2` (incl. S1), `mBestLapTime` ●, `mLastSector1`, `mLastSector2` (incl. S1), `mLastLapTime` ●, `mCurSector1`, `mCurSector2` | s, **cumulative** |
| 192, 194 | i16 | `mNumPitstops`, `mNumPenalties` | |
| 196 | bool | `mIsPlayer` ● | |
| 197 | i8 | `mControl` | −1 nobody, 0 local player, 1 local AI, 2 remote, 3 replay |
| 198 | bool | `mInPits` ● | |
| 199 | u8 | `mPlace` ● | |
| 200 | char[32] | `mVehicleClass` | |
| 232–252 | | `mTimeBehindNext` f64, `mLapsBehindNext` i32, `mTimeBehindLeader` f64, `mLapsBehindLeader` i32 | |
| 256 | f64 | `mLapStartET` | |
| 264 | f64×3 | `mPos` | world |
| 288–432 | | `mLocalVel`, `mLocalAccel`, `mOri[3]`, `mLocalRot`, `mLocalRotAccel` (f64) | |
| 456–459 | u8×4 | `mHeadlights`, `mPitState` ● (0 none, 1 request, 2 entering, 3 stopped, 4 exiting), `mServerScored`, `mIndividualPhase` | |
| 460 | i32 | `mQualification` | |
| 464, 472 | f64 | `mTimeIntoLap`, `mEstimatedLapTime` | |
| 480 | char[24] | `mPitGroup` | |
| 504–507 | u8, bool, u8, bool | `mFlag`, `mUnderYellow`, `mCountLapFlag`, `mInGarageStall` | |
| 508 | u8×16 | `mUpgradePack` | |
| 524–532 | f32×3 | `mPitLapDist`, `mBestLapSector1`, `mBestLapSector2` | |
| 536 | u64 | `mSteamID` *LMU* | **personal**, always scrubbed |
| 544 | char[32] | `mVehFilename` *LMU* | |
| 576 | i16 | `mAttackMode` *LMU* | |
| 578 | u8 | `mFuelFraction` *LMU* | 0x00 = 0 %, 0xFF = 100 % |
| 579 | bool | `mDRSState` *LMU* | |
| 580 | u8×4 | `mExpansion` | |

#### 4.2.6 Mapping to pitwall

The player's telemetry record index is `playerVehicleIdx` @128465 (only when `playerHasVehicle` = 1). The player's
scoring row is the one with `mIsPlayer` ≠ 0 [C2].

| pitwall field | Source | Conversion |
|---|---|---|
| `speed_kph` | `mLocalVel` | ‖v‖ × 3.6 (rF2 has no scalar speed; this is a derivation) |
| `throttle` / `brake` / `steering` / `clutch` | `mUnfiltered*` @388/396/404/412 | none |
| `gear`, `rpm`, `max_rpm` | @352, @356, @532 | none |
| `pos_*` | `mPos` @160 | none. Ground plane (x, z): +y is up [O9] |
| `g_lon` / `g_lat` | `mLocalAccel` @208 | g_lon = −z/9.80665; g_lat = x/9.80665 (+x is left) |
| `yaw_rad` etc. | `mOri` | derive from the rows (S397's `TelemQuat` helpers [O9]); verify the sign |
| `session_time_s` | `mElapsedTime` @12 | none |
| `lap_number` | VSI `mTotalLaps` | +1 |
| `lap_distance_m` | VSI `mLapDist` | **5 Hz only.** Between scoring updates, integrate ‖v‖ from the 100 Hz telemetry and re-anchor on each scoring update. Mark frames between anchors as derived (`extra`); never present them as game values |
| `current_lap_time_ms` | `mElapsedTime − mLapStartET` | ×1000. `mLapStartET` = −1 → `None` [C2] |
| `last_lap_time_ms` | VSI `mLastLapTime` | ×1000; ≤ 0 → `None` |
| `sector` | `mCurrentSector` @600 | mask `0x7FFFFFFF`; the pit bit → `pit_status` |
| `lap_invalid` | `mLapInvalidated` @745 | none |
| `pit_status` | VSI `mInPits`, `mPitState`, `mInGarageStall` | |
| `race_position` | VSI `mPlace` | |
| `tyre_surface_temp_c` | wheel `mTemperature[1]` | K − 273.15 (centre) |
| `tyre_inner_temp_c` | `mTireInnerLayerTemperature[1]` or `mTireCarcassTemperature` | K − 273.15 |
| `tyre_pressure_psi` | `mPressure` | kPa × 0.1450377 |
| `brake_temp_c` | `mBrakeTemp` | **withhold until Kelvin vs °C is settled** |
| `tyre_wear_pct` | `mWear` | **withhold until the direction is verified** |
| `fuel_litres`, `fuel_capacity_litres` | @524, @608 | none |
| `brake_bias_front_pct` | `mRearBrakeBias` @664 | (1 − x) × 100 |
| `traction_control`, `abs_active` | `mTC` @750, `mABSActive` @746 | |
| `SessionInfo.track_name` / `track_length_m` | `mTrackName`, `mLapDist` (scoring) | `track_id = "lmu:" + normalised name + ":" + round(len)`. LMU has no numeric id |
| `SessionInfo.weather` | `mAmbientTemp`, `mTrackTemp`, `mRaining` | none |
| `LapCompletion` | `mTotalLaps` increments | `mLastLapTime`, sectors from cumulative `mLastSector1/2` |

**Missing in LMU:**
- high-rate lap distance;
- a numeric track id;
- the setup;
- safety-car existence: the plugin's Rules buffer had it, and `LMU_Data` has only `mGamePhase` = 6 plus
  `mYellowFlagState` [C2].

The REST API on :6397 [C2] is out of scope; [P2] says it may be localhost-only.

### 4.3 Assetto Corsa Competizione (shared memory, game 3)

#### 4.3.1 Facts

- **Mappings.** `Local\acpmf_physics`, `Local\acpmf_graphics`, `Local\acpmf_static` [P1][C1].
- **Encoding.** `pack(4)`. Strings are `wchar_t` (UTF-16LE). Booleans are `int` [O6][C1].
- **Rates [O6].** Physics members "change at each graphic step". Graphics are "updated at each graphical step".
  Static is "initialized when the instance starts and never changes until the instance is closed".
- **"Not used in ACC".** [O6] colours fields red when "not used by ACC". Those fields are listed as such below and
  **must decode to `None`**.
- **Player only.** All data is the player's car, except graphics `carCoordinates[60]` and `carID[60]`, which cover the
  cars on track [O6].
- **Licence.** Kunos document [O6] with no licence text. The ACC EULA questions on commercial use are in [P3] §7.6
  item 5.

#### 4.3.2 `SPageFilePhysics` (800 B)

| Off | Type | Field [O6] | Notes |
|---|---|---|---|
| 0 | i32 | `packetId` | change counter |
| 4 | f32 | `gas` ● | 0–1 |
| 8 | f32 | `brake` ● | 0–1 |
| 12 | f32 | `fuel` | [O6]: "**kg**". But `fuelXLap` says litres and the static `maxFuel` has no unit. **Unit conflict: verify against the HUD** |
| 16 | i32 | `gear` ● | Kunos convention 0 = R, 1 = N, 2 = 1st ([O7] for AC EVO; [P1] for AC) → pitwall gear = value − 1. **Verify for ACC** |
| 20 | i32 | `rpm` ● | |
| 24 | f32 | `steerAngle` ● | "Steering input value (from -1.0 to 1.0)" |
| 28 | f32 | `speedKmh` ● | |
| 32 | f32×3 | `velocity` | global |
| 44 | f32×3 | `accG` ● | "in global coordinates" per [O6]. [O7] for AC EVO says [lateral, longitudinal, vertical] in g. **Verify** |
| 56 | f32×4 | `wheelSlip` | |
| 72 | f32×4 | `wheelLoad` | not used in ACC |
| 88 | f32×4 | `wheelPressure` ● | psi (unit per [O7]; [O6] states none) |
| 104 | f32×4 | `wheelAngularSpeed` | rad/s |
| 120 | f32×4 | `tyreWear` | **not used in ACC** |
| 136 | f32×4 | `tyreDirtyLevel` | not used |
| 152 | f32×4 | `tyreCoreTemp` ● | °C |
| 168 | f32×4 | `camberRAD` | not used |
| 184 | f32×4 | `suspensionTravel` | |
| 200 | f32 | `drs` | not used |
| 204 | f32 | `tc` | "TC in action" |
| 208, 212, 216 | f32 | `heading`, `pitch`, `roll` ● | rad |
| 220 | f32 | `cgHeight` | not used |
| 224 | f32×5 | `carDamage` | front, rear, left, right, centre |
| 244 | i32 | `numberOfTyresOut` | not used |
| 248 | i32 | `pitLimiterOn` | |
| 252 | f32 | `abs` ● | "ABS in action" |
| 256, 260 | f32 | `kersCharge`, `kersInput` | not used |
| 264 | i32 | `autoshifterOn` | |
| 268 | f32×2 | `rideHeight` | not used |
| 276 | f32 | `turboBoost` | |
| 280, 284 | f32 | `ballast`, `airDensity` | not used |
| 288 | f32 | `airTemp` ● | °C |
| 292 | f32 | `roadTemp` ● | °C |
| 296 | f32×3 | `localAngularVel` | |
| 308 | f32 | `finalFF` | |
| 312–344 | 9 × 4 B | `performanceMeter`, `engineBrake`, `ersRecoveryLevel`, `ersPowerLevel`, `ersHeatCharging`, `ersIsCharging`, `kersCurrentKJ`, `drsAvailable`, `drsEnabled` | not used |
| 348 | f32×4 | `brakeTemp` ● | °C |
| 364 | f32 | `clutch` ● | 0–1 |
| 368, 384, 400 | f32×4 ×3 | `tyreTempI/M/O` | **not shown in ACC** |
| 416 | i32 | `isAIControlled` | |
| 420, 468, 516 | f32[4][3] ×3 | `tyreContactPoint/Normal/Heading` | |
| 564 | f32 | `brakeBias` ● | needs a per-car offset ([O6] Appendix 4) |
| 568 | f32×3 | `localVelocity` | |
| 580, 584 | i32 | `P2PActivation`, `P2PStatus` | not used |
| 588 | f32 ([O6]) / i32 ([C1]) | `currentMaxRpm` | not used. **Type conflict** |
| 592, 608, 624 | f32×4 ×3 | `mz`, `fx`, `fy` | not shown |
| 640 | f32×4 | `slipRatio` | |
| 656 | f32×4 | `slipAngle` | |
| 672, 676 | i32 | `tcinAction`, `absInAction` | not used |
| 680 | f32×4 | `suspensionDamage` | not used |
| 696 | f32×4 | `tyreTemp` | not used |
| 712 | f32 | `waterTemp` | |
| 716 | f32×4 | `brakePressure` | |
| 732, 736 | i32 | `frontBrakeCompound`, `rearBrakeCompound` | |
| 740 | f32×4 | `padLife` | |
| 756 | f32×4 | `discLife` | |
| 772–780 | i32×3 | `ignitionOn`, `starterEngineOn`, `isEngineRunning` | |
| 784–796 | f32×4 | `kerbVibration`, `slipVibrations`, `gVibrations`, `absVibrations` | |

#### 4.3.3 `SPageFileGraphic` (1588 B)

| Off | Type | Field [O6] | Notes |
|---|---|---|---|
| 0 | i32 | `packetId` | change counter |
| 4 | i32 | `status` ● | 0 off, 1 replay, 2 live, 3 pause |
| 8 | i32 | `session` ● | −1 unknown, 0 practice, 1 qualify, 2 race, 3 hotlap, 4 time attack, 5 drift, 6 drag, 7 hotstint, 8 hotstint superpole |
| 12, 42, 72, 102 | wchar[15] ×4 | `currentTime`, `lastTime`, `bestTime`, `split` | display strings |
| 132 | i32 | `completedLaps` ● | |
| 136 | i32 | `position` ● | |
| 140 | i32 | `iCurrentTime` ● | ms |
| 144 | i32 | `iLastTime` ● | ms |
| 148 | i32 | `iBestTime` ● | ms |
| 152 | f32 | `sessionTimeLeft` | |
| 156 | f32 | `distanceTraveled` | "in the current stint" |
| 160 | i32 | `isInPit` ● | |
| 164 | i32 | `currentSectorIndex` ● | base unverified |
| 168 | i32 | `lastSectorTime` ● | ms |
| 172 | i32 | `numberOfLaps` | |
| 176 | wchar[33] | `tyreCompound` ● | |
| 244 | f32 | `replayTimeMultiplier` | not used |
| 248 | f32 | `normalizedCarPosition` ● | 0.0 start – 1.0 finish |
| 252 | i32 | `activeCars` | |
| 256 | f32[60][3] | `carCoordinates` ● | cars on track |
| 976 | i32[60] | `carID` | |
| 1216 | i32 | `playerCarID` ● | player position = `carCoordinates[k]` where `carID[k] == playerCarID` |
| 1220 | f32 | `penaltyTime` | |
| 1224 | i32 | `flag` | 0 none, 1 blue, 2 yellow, 3 black, 4 white, 5 chequered, 6 penalty, 7 green, 8 orange |
| 1228 | i32 | `penalty` | enum 0–21 |
| 1232 | i32 | `idealLineOn` | |
| 1236 | i32 | `isInPitLane` ● | |
| 1240 | f32 | `surfaceGrip` | |
| 1244 | i32 | `mandatoryPitDone` | |
| 1248 | f32 | `windSpeed` ● | m/s |
| 1252 | f32 | `windDirection` | rad |
| 1256–1280 | i32×7 | `isSetupMenuVisible`, `mainDisplayIndex`, `secondaryDisplyIndex`, `TC` ●, `TCCUT`, `EngineMap`, `ABS` | |
| 1284 | f32 | `fuelXLap` ● | litres per lap |
| 1288–1304 | i32, i32, i32, f32, i32 | `rainLights`, `flashingLights`, `lightsStage`, `exhaustTemperature`, `wiperLV` | |
| 1308, 1312 | i32 | `driverStintTotalTimeLeft`, `driverStintTimeLeft` | ms |
| 1316 | i32 | `rainTyres` | |
| 1320 | i32 | `sessionIndex` | |
| 1324 | f32 | `usedFuel` | since refuel |
| 1328 | wchar[15] | `deltaLapTime` | |
| 1360 | i32 | `iDeltaLapTime` | ms |
| 1364 | wchar[15] | `estimatedLapTime` | |
| 1396 | i32 | `iEstimatedLapTime` | ms. [O6] swaps the two descriptions |
| 1400 | i32 | `isDeltaPositive` | |
| 1404 | i32 | `iSplit` ● | ms |
| 1408 | i32 | `isValidLap` ● | |
| 1412 | f32 | `fuelEstimatedLaps` ● | |
| 1416 | wchar[33] | `trackStatus` | |
| 1484 | i32 | `missingMandatoryPits` | |
| 1488 | f32 | `Clock` | time of day, s |
| 1492–1528 | i32×10 | `directionLightsLeft/Right`, `GlobalYellow`, `GlobalYellow1/2/3`, `GlobalWhite`, `GlobalGreen`, `GlobalChequered`, `GlobalRed` | |
| 1532 | i32 | `mfdTyreSet` | |
| 1536 | f32 | `mfdFuelToAdd` | |
| 1540–1552 | f32×4 | `mfdTyrePressureLF/RF/LR/RR` | |
| 1556 | i32 | `trackGripStatus` ● | 0 green … 6 flooded |
| 1560, 1564, 1568 | i32 | `rainIntensity` ●, `rainIntensityIn10min` ●, `rainIntensityIn30min` ● | 0 none … 5 thunderstorm |
| 1572, 1576 | i32 | `currentTyreSet`, `strategyTyreSet` | |
| 1580, 1584 | i32 | `gapAhead`, `gapBehind` | ms |

#### 4.3.4 `SPageFileStatic` (820 B if `trackConfiguration` is wchar[33])

| Off | Type | Field [O6] | Notes |
|---|---|---|---|
| 0 | wchar[15] | `smVersion` ● | the version gate (value unknown) |
| 30 | wchar[15] | `acVersion` | |
| 60 | i32 | `numberOfSessions` | |
| 64 | i32 | `numCars` | |
| 68 | wchar[33] | `carModel` ● | Kunos id (e.g. `ferrari_488_gt3`, [O6] App. 2) |
| 134 | wchar[33] | `track` ● | track id string |
| 200, 266, 332 | wchar[33] ×3 | `playerName`, `playerSurname`, `playerNick` | personal |
| 400 | i32 | `sectorCount` ● | |
| 404, 408 | f32 | `maxTorque`, `maxPower` | not shown |
| 412 | i32 | `maxRpm` ● | |
| 416 | f32 | `maxFuel` ● | unit not stated |
| 420, 436 | f32×4 ×2 | `suspensionMaxTravel`, `tyreRadius` | not shown |
| 452 | f32 | `maxTurboBoost` | not used |
| 456, 460 | f32 | `deprecated_1/2` | [C1] names them air/road temperature |
| 464–504 | | `penaltiesEnabled`, `aidFuelRate`, `aidTireRate`, `aidMechanicalDamage`, `AllowTyreBlankets`, `aidStability`, `aidAutoclutch`, `aidAutoBlip`, `hasDRS`, `hasERS`, `hasKERS` | |
| 508–516 | | `kersMaxJ`, `engineBrakeSettingsCount`, `ersPowerControllerCount` | not used |
| 520 | f32 | `trackSplineLength` | **"Not used in ACC"** |
| 524 | wchar[?] | `trackConfiguration` | not used. **Array length conflict:** [O6] prints no length; [C1] uses [33]; the AC mirror [C5] uses [15] |
| 592 / 556 | | `ersMaxJ` … then `isTimedRace`, `hasExtraLap`, `carSkin[33]`, `reversedGridPositions`, `PitWindowStart`, `PitWindowEnd`, `isOnline`, `dryTyresName[33]`, `wetTyresName[33]` | **Offsets depend on that conflict**: [33] gives `isOnline` @684 and `dryTyresName` @688; [15] gives 36 bytes less. Settle with one recording (`dryTyresName` must decode as readable text) |

#### 4.3.5 Mapping and gaps

Inputs, speed, gear, rpm, core tyre temperature, pressures, brake temperatures, laps and lap times (ms), sector index,
last sector time, validity, pit state, compound and weather (air, road, wind, rain now/+10/+30, grip) all map
directly from the tables above. Gaps and caveats:
- **Lap distance in metres.** `normalizedCarPosition` × track length. ACC's shared memory has **no** track length
  (`trackSplineLength` is not used [O6]). Take the length from the broadcast `TRACK_DATA.trackMeters` (Mac-direct
  sibling family [P5]) or from the pitwall ACC crosswalk ([P3] §4.2 lists `trackMeters` per track).
- **Player world position.** Taken through `carID`/`playerCarID`. Y is up (community [P1]).
- **Session time.** None in physics. Use the agent's `t_send_ns` for spacing; `session_time_s` = `None`.
- **Tyre surface temperatures and live tyre wear:** not available in ACC (both marked unused [O6]).
- **Setup:** not exposed (JSON files on disk [P1]).
- **Pairing.** Physics and graphics are separate snapshots. Merge the latest graphics into each physics frame and set
  `FrameQuality.STALE_LAP_DATA` when graphics are > 100 ms older.

### 4.4 iRacing (irsdk, game 4)

#### 4.4.1 Facts

- **Mapping.** `Local\IRSDKMemMapFileName`. pyirsdk maps **1164 × 1024** bytes.
- **Event.** `Local\IRSDKDataValidEvent` is signalled on update.
- **Before opening.** pyirsdk checks the sim is running at `http://127.0.0.1:32034/get_sim_status?object=simStatus`
  [C4].
- **Self-describing.** Variables are found by name; there are no fixed offsets [C4][P1].
- **Licence.** pyirsdk is MIT [C4] and may be vendored into the agent with its notice.
- **Legal hold.** iRacing's Terms of Use (August 2026) §§4.1, 6.1(d)(e)(f), 6.2, 6.3 and 6.5 put **track-data use on
  legal hold** [P3] §7.6 item 6. Ask counsel whether §6.1(e) ("data-collecting software") reaches the agent itself
  before releasing iRacing support.

#### 4.4.2 Header (offset 0) and buffers [C4]

| Off | Type | Field | Notes |
|---|---|---|---|
| 0 | i32 | `ver` | ≥ 1 |
| 4 | i32 | `status` | bit 1 = connected |
| 8 | i32 | `tickRate` | ticks/s ("60 or 360 etc.") |
| 12 | i32 | `sessionInfoUpdate` | increments when the YAML changes |
| 16 | i32 | `sessionInfoLen` | bytes |
| 20 | i32 | `sessionInfoOffset` | |
| 24 | i32 | `numVars` | |
| 28 | i32 | `varHeaderOffset` | |
| 32 | i32 | `numBuf` | "≤ IRSDK_MAX_BUFS (3 for now)" |
| 36 | i32 | `bufLen` | bytes per line |
| 40 | i32 | `cur_buf_tick_count` | 2026 addition: stashed tick count |
| 44 | u8 | `cur_buf` | 2026 addition: index of the newest buffer |
| 48 + 16·k | 16 B | `varBuf[k]`: `tick_count` i32 @+0 (updated **after** the write), `buf_offset` i32 @+4, `tick_count_begin` i32 @+8 (updated **before** the write; 2026 addition), pad @+12 | k < `numBuf` |

**`VarHeader`** (144 B; entry *j* at `varHeaderOffset` + 144·j):

| Rel | Type | Field |
|---|---|---|
| 0 | i32 | `type`: 0 char, 1 bool, 2 int, 3 bitfield (u32), 4 float, 5 double |
| 4 | i32 | `offset` (within a line) |
| 8 | i32 | `count` |
| 12 | bool | `countAsTime` (+3 pad) |
| 16 | char[32] | `name` |
| 48 | char[64] | `desc` |
| 112 | char[32] | `unit` |

**Session YAML.** It sits at `sessionInfoOffset`, `sessionInfoLen` bytes long. pyirsdk 1.3.7 decodes it as UTF-8 and
falls back to cp1252 (`1abbd64`, 2026-10-03) [C4]. It contains `WeekendInfo` (`TrackID`, `TrackName`, `TrackLength`),
`SplitTimeInfo` (sector starts as lap fractions), `DriverInfo` (personal) and `CarSetup` when visible [P1].

#### 4.4.3 Agent slice plan

- **Stream 2 (layout).** Header `[0, 48+16·numBuf)` plus the variable headers. Sent at attach, whenever
  `numVars`/`varHeaderOffset`/`bufLen` change, and at 1 Hz.
- **Stream 0 (line).** The header plus the coherent line, on each new `tick_count`. The header slice tells the decoder
  which `buf_offset` is current.
- **Stream 3 (YAML).** The header plus the YAML when `sessionInfoUpdate` changes. Off by default (§3.7).
- **Mac decoder.** It looks variables up by name in its mirror's header table, the way pyirsdk does on a file
  (`startup(test_file=…)` [C4]). It is pure Python, so it also runs on macOS.

#### 4.4.4 Mapping (variable names and descriptions from `vars.txt` [C4])

| pitwall field | Variable | Conversion |
|---|---|---|
| `speed_kph` | `Speed` ("GPS vehicle speed, m/s") | ×3.6 |
| `throttle` / `brake` | `ThrottleRaw` / `BrakeRaw` (0–1) | none. `Throttle`/`Brake` are the processed values |
| `clutch` | `ClutchRaw` ("0=disengaged to 1=fully engaged") | **1 − value** to get pedal travel (the scale is inverted against the other games) |
| `steering` | `SteeringWheelAngle` / `SteeringWheelAngleMax` (rad) | ratio. **The sign convention is unverified** |
| `gear` / `rpm` | `Gear` (−1/0/1..n) / `RPM` | none |
| `g_lat`/`g_lon`/`g_vert` | `LatAccel`/`LongAccel`/`VertAccel` (m/s², "including gravity") | ÷9.80665. Signs unverified |
| `yaw/pitch/roll_rad` | `Yaw`, `Pitch`, `Roll` | none |
| `vel_*` | `VelocityX/Y/Z` (m/s) | none (frame unverified) |
| `pos_*` | — | **no live world position** [P1] |
| `session_time_s` / `frame_id` | `SessionTime` / `SessionTick` | none |
| `lap_number` | `Lap` ("Laps started count") | none |
| `lap_distance_m` | `LapDist` ("Meters traveled from S/F this lap") | none |
| `current_lap_time_ms` / `last_lap_time_ms` | `LapCurrentLapTime` ("Estimate … as shown in F3 box") / `LapLastLapTime` (s) | ×1000 |
| `sector` | derived from YAML `SplitTimeInfo` and `LapDistPct` | needs stream 3 |
| `race_position` | `PlayerCarPosition` | none |
| `pit_status` | `OnPitRoad`, `IsInGarage` | |
| `tyre_inner_temp_c` | `LFtempCM` etc. (carcass, °C) | community: updates only in the pit stall [P1] |
| `tyre_wear_pct` | `LFwearM` etc. ("percent tread remaining") | 100 − value; pit-stall updates only [P1] |
| `tyre_pressure_psi` | — | only `LFcoldPressure` ("as set in the garage", kPa) is listed: no live pressure |
| `fuel_litres` | `FuelLevel` (l) | none |
| `SessionInfo.track_id` / `track_length_m` | YAML `WeekendInfo.TrackID` / `TrackLength` | `"iracing:{TrackID}"`. **Legal hold** on any derived track data [P3] |
| `SessionInfo.weather` | `AirTemp`, `TrackTempCrew`, `TrackWetness`, `Precipitation` | none |

### 4.5 Assetto Corsa 2014 (shared memory, game 5)

- **Mapping names** are the same as ACC [P1]. Identify AC by its process (`acs.exe`, per [P1] §2.2). Its layouts are
  shorter versions of ACC's [C5]:

| Page | AC size [C5] | Same as ACC | Difference |
|---|---|---|---|
| physics | 580 | offsets 0–579 identical (ends at `localVelocity`) | no fields after 580 in [C5]. [C5] comments mark "since 1.5/1.6/1.7" additions, so the size depends on `smVersion` |
| graphics | 288 | 0–251 identical (through `normalizedCarPosition` @248) | @252 `carCoordinates` f32×3 (**player only**), @264 `penaltyTime`, @268 `flag`, @272 `idealLineOn`, @276 `isInPitLane`, @280 `surfaceGrip`, @284 `mandatoryPitDone` |
| static | 648 | 0–523 identical | @520 `trackSPlineLength` **is used in AC** ([P1]: lap metres = `normalizedCarPosition` × it); @524 `trackConfiguration` **wchar[15]**; @556 `ersMaxJ`; @560 `isTimedRace`; @564 `hasExtraLap`; @568 `carSkin[33]`; @636 `reversedGridPositions`; @640/644 `pitWindowStart/End` |

- **Mapping.** As for ACC, plus:
  - lap distance from `trackSPlineLength`;
  - the track from `track` @134 plus `trackConfiguration` @524;
  - tyre wear `tyreWear` @120 and tyre I/M/O temperatures exist ([P1] §2.1 lists them as live in AC).
- **Gear.** 0 = R, 1 = N, 2 = 1st [P1].
- **Rate.** Unmeasured.
- **Prefer** the Mac-direct `ac-remote-udp` family [P5] for basic coaching. The relay adds fuel, tyres, sector index
  and lap metres [P1] §2.2.
- **Licence.** The Kunos "Shared Memory Reference" was not fetched; [C5] is MIT and used for facts only.

### 4.6 Automobilista 2 (`$pcars2$`, game 6)

- **Source.** [C1] only: `SharedMemoryVersion = 14`, 64 participants, 64-byte strings, total **23 100 B**. The
  game-shipped `SharedMemory.h` (Support folder, per Reiza forum [F6] via [P2]) was **not readable**: verify every
  row against it on Windows before implementing.
- **Prefer** the Mac-direct `pcars2-udp` family [P5]. That family covers AMS2 without a relay ([P2] §4 row 6).

Key offsets (from [C1]; **unverified**):

| Off | Type | Field | Notes |
|---|---|---|---|
| 0 | u32 | `mVersion` | 14 |
| 4 | u32 | `mBuildVersionNumber` | |
| 8, 12, 16 | u32 | `mGameState`, `mSessionState`, `mRaceState` | |
| 20 | i32 | `mViewedParticipantIndex` | [C1] name: `FocusedParticipantIndex` |
| 24 | i32 | `mNumParticipants` | |
| 28 + 100·i | 100 B | participant *i*: `mIsActive` bool @+0, `mName` char[64] @+1 (personal), `mWorldPosition` f32×3 @+68, `mCurrentLapDistance` f32 @+80 ●, `mRacePosition` u32 @+84, `mLapsCompleted` u32 @+88, `mCurrentLap` u32 @+92, `mCurrentSector` i32 @+96 | |
| 6428–6440 | f32×4 | unfiltered throttle, brake, steering, clutch ● | |
| 6444, 6508 | char[64] | car name, class | |
| 6576, 6640 | char[64] | track location ●, track variation ● | |
| 6704 | f32 | track length ● | |
| 6712 | bool | lap invalidated | |
| 6716–6724 | f32 | best, last ●, current ● lap time | s |
| 6840, 6844 | f32 | fuel level, capacity | |
| 6848 | f32 | speed ● | m/s |
| 6852, 6856 | f32 | rpm ●, max rpm | |
| 6860–6872 | f32 | brake, throttle, clutch, steering (filtered) | |
| 6876 | i32 | gear ● | |
| 7072 | f32×4 | tyre temperature °C | |
| 7136 | f32×4 | tyre wear | |
| 7184 | f32×4 | brake temperature °C | |
| 7200–7264 | f32×4 ×5 | tyre tread/layer/carcass/rim/internal-air temperature (K) | |
| 7292, 7296, 7300 | f32 | ambient temp, track temp, rain density | |
| 7320 | u32 | `mSequenceNumber` ● | odd = write in progress [C1] |

- **Rate:** unmeasured.
- **Licence:** game header unchecked; [C1] is MIT and used for facts only.

### 4.7 rFactor 2 (pitwall plugin, game 7)

- **No native output.** rF2 has no native mapping. Telemetry needs a plugin DLL in `Plugins\`, built against S397's
  Internals Plugin interface [O9].
  - The common shared-memory plugin [C9] and BST's fork [C8] are **GPL-3.0**: do not use them.
  - pitwall writes its own.
- **Interface [O9].** The DLL exports these `__cdecl` functions (types in `PluginObjects.hpp`):
  - `GetPluginName`;
  - `GetPluginType` → `PO_INTERNALS` (= 3);
  - `GetPluginVersion` → 7 for `InternalsPluginV07`;
  - `CreatePluginObject` and `DestroyPluginObject`.

  The class overrides:
  - `WantsTelemetryUpdates()`, which returns 1 = player only (0 no, 2 all vehicles);
  - `UpdateTelemetry(const TelemInfoV01&)`;
  - `WantsScoringUpdates()` and `UpdateScoring(const ScoringInfoV01&)`, called "approximately five times per second";
  - `Startup(long version)` ("version * 1000").
- **Design: the plugin is its own relay.**
  - In each callback it copies the record verbatim into a lock-free ring and returns.
  - A background thread sends `PWRL` SLICEs (game 7) with the record as `data` and `offset` 0:
    - mapping 0: TelemInfoV01, 1888 B;
    - mapping 1: ScoringInfoV01, 548 B, with both pointers (@96, @540) **zeroed**;
    - mapping 2: VehicleScoringInfoV01 × `mNumVehicles` at offset 584·i.
  - It **never blocks the sim thread**.
  - The control port behaviour is the same as the agent's (§2).
- **Layouts.** rF2 records have the same sizes as LMU's (TelemInfoV01 **1888**, TelemWheelV01 260,
  VehicleScoringInfoV01 **584**, ScoringInfoV01 **548**). They are compiled from [O9] with Windows' 32-bit `long`.
  Offsets are identical to §4.2.3–§4.2.5 up to the expansion areas (telemetry < 745, wheel < 236, VSI < 536,
  scoring < 340). In rF2 those tails are `mExpansion` and must not be decoded with LMU's meanings.
- **Rates.** Scoring ≈ 5 Hz [O9]. The telemetry callback rate is not stated in the header: measure it.
- **Licence.**
  - `InternalsPlugin.hpp` reads "PROPRIETARY AND CONFIDENTIAL / Copyright (c) 2017 Studio 397 B.V.", and
    `PluginObjects.hpp` reads "Copyright (c) 1996-2013 Image Space Incorporated".
  - S397's download page attaches no licence to "Example Plugin v8" [O9].
  - **Do not commit these headers.** Build the plugin against a developer-downloaded copy.
  - Ask S397 for terms before distributing a binary.
  - The Mac decoder implements the layout from this spec, which states facts and contains no header text.

### 4.8 Assetto Corsa EVO (game 8): last target, gated

- **Mappings.** `Local\acevo_pmf_physics`, `Local\acevo_pmf_graphics`, `Local\acevo_pmf_static` [O7].
- **[O7] change log:**
  - 2026-03-31: inner structures have fixed sizes; `display_current_page_index` is now 16 items, not 9.
  - 2026-04-28: `car_ids` added to the graphics struct.
- **Layout churn.** The layout was reworked in 0.5 and 0.6 ([P2] cites [N14][O20]).
- **Version.** Key on `sm_version` (char[15] at static @0; "Bump when offsets change" [C7]).
- **Physics (800 B).** [O7] lists the fields, all 4-byte types, so the offsets are fixed. They equal ACC's §4.3.2 with
  these renames:
  - @716 `brakeTorque` (Nm), not `brakePressure`;
  - @792 `roadVibrations`, not `gVibrations`.

  [C1] agrees. Rate: "every simulation step" [O7], typically 333 Hz [C7]. Units per [O7]:
  - `fuel` litres;
  - `gear` 0 = R, 1 = N, 2+ forward;
  - `wheelsPressure` psi;
  - tyre temperatures °C;
  - `tyreWear` "0.0 = new, 1.0 = fully worn". [C7] says it **reads 0 in current builds**.
- **Conflicts:**
  - `steerAngle` is "Normalised (−1 … +1)" per [O7] but "radians, signed" per [C7]. Verify.
  - `accG` per [O7] is [lateral, longitudinal, vertical] in g.
- **Static (208 B, [C1] transcription; candidate).**

| Off | Type | Field |
|---|---|---|
| 0 | char[15] | `sm_version` |
| 15 | char[15] | `ac_evo_version` |
| 32 | i32 | `session` (−1 unknown, 0 time attack, 1 race, 2 hot stint, 3 cruise [O7]) |
| 36 | char[33] | `session_name` |
| 69 | u8 | `event_id` |
| 70 | u8 | `session_id` |
| 72 | i32 | `starting_grip` |
| 76 | f32 | `starting_ambient_temperature_c` |
| 80 | f32 | `starting_ground_temperature_c` |
| 84–86 | bool×3 | `is_static_weather`, `is_timed_race`, `is_online` |
| 88 | i32 | `number_of_sessions` |
| 92 | char[33] | `nation` |
| 128 | f32 | `longitude` |
| 132 | f32 | `latitude` |
| 136 | char[33] | `track` ● |
| 169 | char[33] | `track_configuration` ● |
| 204 | f32 | `track_length_m` ● |

- **Graphics ([C1] transcription, 4 900 B; candidate).** [C7] describes it as "~6–8 kB", which **conflicts** with
  this. The agent sends it raw; nothing is decoded until [O8] is read and a dump confirms. Candidate offsets:
  - `packetId` 0, `status` 4;
  - `rpm` u16 40, `gear_int` i16 68;
  - `gas/brake/clutch/steering_percent` f32 76/80/88/92;
  - `current_lap_time_ms` i32 188;
  - four 256 B tyre states at 220/476/732/988;
  - `npos` f32 1244, `car_location` 1388;
  - `total_lap_count` 2384, `current_position` 2388;
  - `last_lap_time_ms` 2396, `best_lap_time_ms` 2400;
  - session state 2476, timing state 2732 (`is_invalid` inside it);
  - driver name/surname 3020/3053 (personal);
  - `is_in_pit_box`/`is_in_pit_lane`/`is_valid_lap` 3119/3120/3121;
  - `car_coordinates[60]` 3124;
  - `car_ids[60]` (16 B each) 3940.
- **Lap distance.** `npos` × `track_length_m`. This corrects the "AC EVO (no lap distance)" row in [P3] §6.1, as [P2]
  already noted, but stays **unverified** until a recording confirms it.
- **Licence.** [O7] is a Kunos document. Its copy sits in an MIT repo, but the MIT licence does not cover Kunos's
  text. [C7] has no licence: facts only.

---

## 5. Unified mapping matrix

Y = direct; D = derived (method in §4); P = partial; N = not available; ? = present but unverified (gated).

| Game | Speed | Thr/Brk/Steer | Gear/RPM | World pos | Lap no. | Lap distance | Lap times | Sector | Tyres | Fuel | Track id |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R3E | Y | Y/Y/Y (steer sign ?) | Y/Y (rad/s→rpm) | Y | Y | **Y** (m + fraction) | Y (s) | Y (base ?) | temp L/C/R, pressure Y; wear ? | Y (l) | **Y** (track_id + layout_id + length) |
| LMU | D (‖v‖) | Y/Y/Y | Y/Y | Y | Y | D (5 Hz anchor + integration) | Y | Y | temp K→°C, pressure, carcass Y; wear ?; brake temp ? | Y | P (name + length) |
| ACC | Y | Y/Y/Y | Y (−1)/Y | Y (via carID) | Y | D (npos × external length) | Y (ms) | Y | core temp, pressure Y; surface N; wear N | ? (kg vs l) | P (string; no length) |
| iRacing | Y | Y/Y/D | Y/Y | **N** | Y | Y | Y | D (YAML) | carcass, wear: pit-only P; pressure N | Y | Y (YAML TrackID; **legal hold**) |
| AC | Y | Y/Y/Y | Y (−1)/Y | Y (player) | Y | D (npos × spline length) | Y (ms) | Y | I/M/O, core, wear Y | Y | Y (track + config + length) |
| AMS2 | ? | ? | ? | ? | ? | ? (direct field) | ? | ? | ? | ? | ? (location + variation + length) |
| rF2 | D | Y/Y/Y | Y/Y | Y | Y | D (as LMU) | Y | Y | Y (K) | Y | P (name + length) |
| AC EVO | Y (physics) | Y/Y/? | Y (−1)/Y | ? | ? | ? (npos × length) | ? | N | temps, pressure Y; wear N (zero) | Y (l) | ? (track + config + length) |

---

## 6. What is missing (consolidated)

- **Setup data** is in none of these mappings. iRacing YAML `CarSetup` is the exception, when visible [P1]. ACC and AC
  keep setups on disk [P1].
- **Weather:**
  - R3E has none;
  - LMU and rF2 have temperatures, rain and wetness;
  - ACC has the richest (rain now/+10/+30 minutes, grip);
  - iRacing has temperature, wetness and precipitation.
- **High-rate lap distance:** missing in LMU and rF2 (5 Hz). ACC needs an external track length.
- **World position:** iRacing has none live. ACC gives it only through the car table.
- **Live tyre wear:** none in ACC or AC EVO; pit-stall-only in iRacing; direction unverified in R3E and LMU.
- **Documented write rates:** missing for R3E, AC, AMS2 and rF2 telemetry.

---

## 7. Console caveats

- Every interface in this family is a Windows named file mapping, or an rF2 DLL plugin. **None exists on any
  console**, so the user's PS5 rig gets nothing from it.
- Console builds of games that also appear here:
  - **ACC on PS4/PS5/Xbox:** no external telemetry ([P1] §3.3; [P2] §5.2).
  - **AC on PS4:** only the UDP 9996 interface is reported (2017, Community; [P1] §2.2). That is the
    `ac-remote-udp` family, not this one.
- No source read for this file shows a console build of R3E, LMU, iRacing, rF2, AMS2 or AC EVO. That is "unknown",
  not "no".

---

## 8. Licences (summary)

| Spec source | Licence | Can pitwall implement from it? | Can pitwall vendor it? |
|---|---|---|---|
| `r3e.h` [O1] | Unlicense | Yes | Yes (record in `docs/licences.md`) |
| `r3e-data.json` [O4] | Unlicense | Yes (names) | Yes |
| LMU `SharedMemoryInterface.hpp` | **unchecked** (unreadable here) | Facts via MIT mirrors [C2][C3] | No, until its notice is read |
| lmu-pitwall [C2], pyLMUSharedMemory [C3], sim-racing-sdk [C1], mdjarv [C5] | MIT | Facts | Not needed (no code copied) |
| Kunos ACC PDF [O6], AC EVO PDF [O7] | Kunos documents, no licence stated | Yes (published integration docs); commercial use is a counsel question [P3] §7.6 item 5 | No |
| pyirsdk [C4] | MIT | Yes | Yes, in the agent, with notice |
| iRacing ToU | — | **Legal hold** for track data; ask counsel about §6.1(e) | — |
| S397 InternalsPlugin sample [O9] | "PROPRIETARY AND CONFIDENTIAL"; no licence on the download | Plugin code yes; layout facts yes | **No**: do not commit headers; ask S397 |
| AMS2 `SharedMemory.h` | unchecked | After reading it on Windows | No |
| live-telemetry-evo [C7] | none | Facts only | No |
| rF2SharedMemoryMapPlugin [C9], BST fork [C8], TinyPedal app | GPL-3.0 | **No** | **No** |

---

## 9. Identification and validation summary

1. **Datagram.** `PWRL` magic, `proto_version` 1, the length rules in §2.5.
2. **Source.** SOURCE_INFO `region_size` ≥ `decode_size`, plus the version gate (§3.4).
3. **Per-game self-checks at attach:**
   - R3E: `driver_data_size` = 328 and `all_drivers_offset` as recorded;
   - LMU: `region_size` ≥ 324 820 and `playerVehicleIdx` < 104;
   - ACC/AC: the `smVersion` accept-list and process name;
   - iRacing: `ver` ≥ 1, `numBuf` ≤ 4, and every offset + length inside the region;
   - AMS2: `mVersion` = 14;
   - AC EVO: the `sm_version` accept-list.
4. **Plausibility windows** on decoded values (§11.3). They catch a layout shift that still "decodes": [C2]'s point
   that a shifted float looks like `3.7e-42`.

---

## 10. pitwall integration checklist (when implementing)

- `model/telemetry.py` `Game`: add `RACEROOM`, `LMU`, `RFACTOR2`, `AMS2`, `AC_EVO`. `ACC`, `AC` and `IRACING` exist.
- `adapters/relay/`:
  - one `GameAdapter` (`can_decode` per §2.7);
  - per-game pure decoders;
  - the sparse mirror and reassembler (§2.5).
  - `AdapterInfo.ground_plane = ("pos_x_m", "pos_z_m")` for R3E, LMU, rF2, ACC, AC and AC EVO (all Y-up). AMS2: to
    verify.
  - The router uses one `ground_plane` per adapter [P4]. Either make it per-game for the relay adapter, or have the
    relay adapter report the active game's plane.
- `ingest/`: a `RelaySubscriber` thread modelled on `gt7_heartbeat.py`. It sends `SUBSCRIBE` every 1 s and never
  blocks ingest.
- `config.py`: add `relay_enabled`, `relay_data_port = 28770`, `relay_agent_ip: str | None` (None = broadcast
  `SUBSCRIBE`).
- Connect page: show agent BEACONs and SOURCE_INFO (game, version, rate).
- `capabilities.py`: new rows stay **UNVERIFIED/planned** until recorded evidence exists (CLAUDE.md).
- `docs/licences.md`: add the rows from §8 that are actually used.
- `docs/status.md`: add the rows once code exists.
- A new top-level `relay/windows/` for the agent: no GPL, no S397 headers committed.

---

## 11. Test vectors and sample-packet guidance

### 11.1 Protocol vectors (normative; generated with Python `struct`, little-endian)

**SUBSCRIBE** (40 B):
- subscriber nonce `0x1234ABCD`, seq 7, t = 5 000 000 000 ns;
- data_port 28770, max_datagram 1472, games_mask `0x00000002` (RaceRoom), options `0x00000001` (field),
  lease 5000 ms.

```
50 57 52 4c 01 02 00 00 cd ab 34 12 07 00 00 00 00 f2 05 2a 01 00 00 00
62 70 c0 05 02 00 00 00 01 00 00 00 88 13 00 00
```

**SUBSCRIBE_ACK** (40 B):
- agent instance `0xCAFEF00D`, seq 1;
- status 0, granted 1472 B and 5000 ms, games available `0x2`, echo `0x1234ABCD`.

```
50 57 52 4c 01 03 00 00 0d f0 fe ca 01 00 00 00 08 1a 99 be 1c 00 00 00
00 00 c0 05 88 13 00 00 02 00 00 00 cd ab 34 12
```

**BEACON** (38 B): control 28771, build 1, games `0x2`, host "SIMPC".

```
50 57 52 4c 01 01 00 00 0d f0 fe ca 00 00 00 00 00 ca 9a 3b 00 00 00 00
63 70 01 00 02 00 00 00 05 53 49 4d 50 43
```

**SOURCE_INFO** (52 B; region size illustrative):
- game 1, mapping 0;
- region 45 056, decode 43 996, version 3.5, pid 4321, name `$R3E`.

```
50 57 52 4c 01 10 00 00 0d f0 fe ca 02 00 00 00 00 ab 90 41 00 00 00 00
01 00 04 00 00 b0 00 00 dc ab 00 00 03 00 00 00 05 00 00 00 e1 10 00 00 24 52 33 45
```

**SLICE, part 0 of 2** (1472 B total; first 64 B shown):
- R3E stream 0, snapshot 42, offset 0, `data_len` 1428, flags coherent;
- data starts with `version_major` = 3 and `version_minor` = 5.

```
50 57 52 4c 01 11 00 00 0d f0 fe ca 03 00 00 00 00 8c 86 47 00 00 00 00
01 00 00 00 2a 00 00 00 00 00 00 00 00 00 02 00 94 05 01 00 03 00 00 00
05 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

**SLICE, part 1 of 2** (628 B total; header shown): offset 1428, `data_len` 584 (1428 + 584 = 2012).

```
50 57 52 4c 01 11 00 00 0d f0 fe ca 04 00 00 00 00 8c 86 47 00 00 00 00
01 00 00 00 2a 00 00 00 94 05 00 00 01 00 02 00 48 02 01 00
```

**SOURCE_LOST** (28 B):

```
50 57 52 4c 01 12 00 00 0d f0 fe ca 09 00 00 00 00 94 35 77 00 00 00 00 01 00 00 00
```

**UNSUBSCRIBE** (24 B):

```
50 57 52 4c 01 04 00 00 cd ab 34 12 08 00 00 00 00 bc a0 65 01 00 00 00
```

**Unit tests to write (synthetic tier, `pytest -m synthetic`):**
- round-trip every message;
- reject: a bad magic, version 2, a length mismatch, `part_index` ≥ `part_count`, and `offset + len > decode_size`;
- reassemble out of order (part 1 before part 0);
- a newer snapshot discards an older incomplete one;
- an `instance` change resets the mirror;
- seq wrap at 2³²;
- a 324-byte PWRL datagram must not be claimed by the Forza adapter, and 208/212/328/408-byte ones not by AC (§2.7).

### 11.2 Synthetic decoder vectors (label them synthetic everywhere; `SYNTHETIC_SESSION_UID` rules apply)

- Build each game's buffer with `struct.pack_into` at the offsets in §4, using recognisable values. For R3E:
  - `car_speed` @1392 = 50.0 m/s (expect 180.0 km/h);
  - `gear` @1408 = 3;
  - `engine_rps` @1396 = 628.3185 (expect 6000 rpm);
  - `completed_laps` @1028 = 6 (expect `lap_number` 7);
  - `lap_distance` @1040 = 1234.5;
  - `lap_time_previous_self` @1084 = 92.345 (expect 92 345 ms);
  - `brake_bias` @1596 = 0.42 (expect a 58 % front bias);
  - `gear` = −2 (expect `None`).
- Slice the buffer into PWRL SLICEs (§3.6 plans) and feed them through the adapter.
- Machine-check the offset tables: give `tests/unit/test_relay_layouts.py` a ctypes model per game, and assert
  `sizeof` and key offsets against this file (R3E 43 996; LMU 324 820/1888/584/548/260; ACC 800/1588; AC EVO physics
  800). This mirrors how `test_f1_protocol.py` checks F1.

### 11.3 Recorded fixtures (the only evidence that upgrades a capability)

1. **On the gaming PC, record two things at once:**
   - the Mac `.pwcap` on port 28770;
   - an agent-side **full-mapping dump** each minute (`decode_size` bytes, plus SOURCE_INFO) to `.bin`, for offline
     layout checks.
2. **Note HUD truth during the run:** speed on a straight, gear, lap time, fuel, and pit-lane entry. These anchor the
   unit and sign checks: R3E `layout_length`, `tire_wear` direction and steer sign; LMU `mBrakeTemp` unit; ACC fuel
   unit and gear offset; AC EVO steer unit.
3. **Plausibility windows** (an LMU example from [C2]; extend to every game):
   - tyre temperature 240–500 K;
   - pedals 0–1;
   - |steer| ≤ 1;
   - fuel 0 to capacity;
   - known sentinels allowed: `mMaxLaps` = `i32::MAX` in timed races, `mSectorFlag` = 11 for clear, and
     `mLapStartET` = −1 before the first lap [C2].
4. **Version accept-lists.** Record `smVersion`/`sm_version`/`gameVersion`/R3E `(major, minor)` values from each
   recording.
5. **Scrub before committing.** Run the agent in default scrub mode, then zero any remaining name/id/path/SteamID
   bytes in the dump. Never commit other drivers' data (§3.7). Put fixtures under `tests/fixtures/recorded/<game>/`
   with a README stating the game build, `sm_version`, date and conditions.
6. **Rates.** Measure the real rate per mapping from change counters and `t_send_ns`:
   - R3E ticks, ACC/AC/AC EVO `packetId`, iRacing `tickRate`, AMS2 `mSequenceNumber`, rF2 callbacks;
   - LMU's 100/5 Hz [C2] is the only measured rate in hand.

---

## 12. Open questions

1. **LMU:**
   - the game header's licence notice;
   - the lock vs witness choice (§4.2.1);
   - the `events` semantics;
   - the `mBrakeTemp` unit;
   - the `mWear` direction.
2. **R3E:**
   - the mapping write rate;
   - the `track_sector` base;
   - the `sector_start_factors` meaning;
   - the `tire_wear` direction;
   - the steer sign;
   - the units of `layout_length`/`lap_distance`;
   - the observed `all_drivers_offset` value.
3. **ACC:**
   - the `smVersion` value;
   - the fuel unit (kg per [O6] vs litres);
   - the gear offset;
   - the static `trackConfiguration` length ([33] vs [15]), which moves `isOnline` and the tyre names.
4. **AC EVO:**
   - read the Steam guide [O8] in a real browser;
   - the graphics size (4 900 vs "~6–8 kB");
   - `steerAngle` units;
   - `sm_version` values;
   - `npos` × `track_length_m` vs a measured lap.
5. **AMS2:** verify every §4.6 row against the shipped `SharedMemory.h`.
6. **rF2:** S397's terms for distributing a plugin built from the sample; the telemetry callback rate.
7. **iRacing:** counsel on ToU §6.1(e) for the agent; the steering and acceleration sign conventions.
8. **Ports:** check 28770/28771 against the IANA registry (not done; the search budget was spent).
9. **Agent:** confirm on a real Windows 11 box that a logon-task agent opens every mapping above, and that a session-0
   service cannot (expected from [O10]).

---

## 13. Sources

Retrieved 2026-10-10 unless stated.

**Official**
- [O1] https://github.com/sector3studios/r3e-api/blob/29a3e9587d95edf70f6e32e40db317c6a9d0d5ef/sample-c/src/r3e.h
- [O2] https://github.com/sector3studios/r3e-api/blob/29a3e9587d95edf70f6e32e40db317c6a9d0d5ef/LICENSE ;
  https://github.com/sector3studios/r3e-api/blob/29a3e9587d95edf70f6e32e40db317c6a9d0d5ef/README.md ;
  https://github.com/sector3studios/r3e-api/blob/29a3e9587d95edf70f6e32e40db317c6a9d0d5ef/sample-c/src/sample.c
- [O3] https://github.com/sector3studios/r3e-api/commits/master/sample-c/src/r3e.h ; commits
  https://github.com/sector3studios/r3e-api/commit/ad2b1f3e68 (3.1),
  https://github.com/sector3studios/r3e-api/commit/faff6d6817 (3.4),
  https://github.com/sector3studios/r3e-api/commit/eeb930422d (3.5),
  https://github.com/sector3studios/r3e-api/commit/29a3e9587d (3.5 LRT)
- [O4] https://github.com/sector3studios/r3e-spectator-overlay/blob/master/r3e-data.json (repo licence: Unlicense)
- [O6] Kunos ACC Shared Memory v1.8.12. Thread: https://www.assettocorsa.net/forum/index.php?threads/acc-shared-memory-documentation.59965/ ;
  copy read: https://github.com/rrennoir/PyAccSharedMemory/blob/main/ACCSharedMemoryDocumentationV1.8.12.pdf
- [O7] Kunos ACE SharedFileOut Documentation v1:
  https://github.com/devology-uk/sim-racing-sdk/blob/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/research/ACE_SharedFileOut_Documentation_v1.pdf
- [O8] https://steamcommunity.com/sharedfiles/filedetails/?id=3707421508 (HTTP 429; not read)
- [O9] https://www.studio-397.com/modding-resources/ ; https://www.studio-397.com/wp-content/uploads/2023/03/rF2_Example_Plugin.7z ;
  https://www.studio-397.com/wp-content/uploads/2016/12/rFactorInternalsPlugin.pdf ; header text read from
  https://github.com/ianv1/BSTSharedMemoryMapPlugin/blob/master/Include/InternalsPlugin.hpp and
  https://github.com/ianv1/BSTSharedMemoryMapPlugin/blob/master/Include/PluginObjects.hpp
- [O10] https://learn.microsoft.com/en-us/windows/win32/termserv/kernel-object-namespaces (updated 2025-04-15)

**News**
- [N1] https://www.bsimracing.com/le-mans-ultimate-update-v1-2-full-changelog/ (2025-12-08)

**Code (licence in §1.1)**
- [C1] https://github.com/devology-uk/sim-racing-sdk/tree/c23c291140a5a5e8d0efbd80b733d4ad9bf96092/src
  (`SimRacingSdk.Acc.SharedMemory/Messages`, `SimRacingSdk.Ace.SharedMemory/Messages`,
  `SimRacingSdk.Ams2.SharedMemory/Messages/SharedMemoryPage.cs`, `SimRacingSdk.Lmu.SharedMemory/LmuSharedMemoryLock.cs`)
- [C2] https://github.com/Swizzjack/lmu-pitwall/blob/a171b80a7c8c1e02a9d029e32fd717c834d26e71/bridge/src/shared_memory/lmu_data.rs ;
  `…/reader.rs` ; `…/README.md` ;
  https://github.com/Swizzjack/lmu-pitwall/blob/a171b80a7c8c1e02a9d029e32fd717c834d26e71/tools/lmu-probe/README.md
- [C3] https://github.com/TinyPedal/pyLMUSharedMemory/blob/6cef58e22bf025268acee93e9e5ea4f569939c1b/lmu_data.py ;
  `…/lmu_mmap.py`
- [C4] https://github.com/kutu/pyirsdk/blob/1abbd64dffdc74377c215ffc783a0458bd81e614/irsdk.py ;
  `…/vars.txt` ; https://github.com/kutu/pyirsdk/commit/9880eeab3b
- [C5] https://github.com/mdjarv/assettocorsasharedmemory/tree/dc39bfacf0a70e415eaefdfc4743780e12b9f2f4
- [C6] https://github.com/rrennoir/PyAccSharedMemory
- [C7] https://github.com/albertowd/live-telemetry-evo/blob/develop/docs/SHARED_MEMORY.md
- [C8] https://github.com/ianv1/BSTSharedMemoryMapPlugin (GPL-3.0; README and S397 headers only)
- [C9] https://github.com/TheIronWolfModding/rF2SharedMemoryMapPlugin (GPL-3.0; not used)

**Via pitwall research (not re-fetched)**
- [F6] Reiza forum, AMS2 shared memory vs UDP: https://forum.reizastudios.com/posts/335128 (via [P2])
- [N14] https://www.bsimracing.com/assetto-corsa-evo-v0-5-update-released/ and
  [O20] https://support.505games.com/support/solutions/articles/150000225211-assetto-corsa-evo-0-6-changelog-15-apr-2026 (via [P2])
- iRacing ToU (2026-08-05): https://ir-core-sites.iracing.com/members/pdfs/20260805-iRacing_Terms_of_Use_and_EULA_dated_Aug_05_2026.pdf (via [P3] §7.6)
- ACC EULA: https://store.steampowered.com/eula/805550_eula_0 (via [P3])

## 14. pitwall references

- [P1] `docs/research/forza-ac-acc-iracing.md` (§2.1, §2.2, §3.1, §3.3, §4, §5)
- [P2] `docs/research/game-compatibility.md` (§1.3, §2.6, §3.10, §4, §5.2, §6, §9, §10)
- [P3] `docs/research/track-knowledge-sources.md` (L0b-ACC, §4.2, §6.1, §7.4, §7.6, Phase 6)
- [P4] `src/pitwall/ingest/capture.py` (pwcap format; `MAX_PAYLOAD` 65 535), `ingest/sources.py` (`UdpListener`,
  `src_port` = local port), `ingest/router.py` (per-port auto-detection), `ingest/gt7_heartbeat.py`,
  `adapters/base.py` (adapter purity), `model/telemetry.py` (`CarFrame`, `Game`, `FrameQuality`), `config.py` (ports)
- [P5] `docs/research/protocols/acc-broadcast.md`, `ac-remote-udp.md`, `pcars2-udp.md`
