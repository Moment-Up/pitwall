# Review of existing F1 25 UDP telemetry repositories

Research date: 2026-10-10. Method: `gh repo view`, `gh api repos/<o>/<r>/license`, `gh api .../commits`, and reading source.
Source was read through `gh api` raw contents, or from a shallow clone in a fresh `$TMPDIR` directory for f126-race-engineer. **No code was executed.**
Only ideas are described below. No code is reproduced except identifiers. Wire-format facts are checked against the official EA spec in `f1-udp-spec.md`.

## Summary table

| Repo | Licence (SPDX) | Stack | Created → last commit (default branch) | Formats | Scope | Sample captures |
|---|---|---|---|---|---|---|
| [skrx7392/f126-race-engineer](https://github.com/skrx7392/f126-race-engineer) | **NO LICENSE** (API 404, no LICENSE file) | Python 3.14 (FastAPI, numpy/scipy, zstandard, psycopg 3), Svelte 5 + TS, Postgres, k8s | 2026-08-06 → **2026-08-07** (28 commits; later pushes are Dependabot branches only, latest 2026-10-09) | 2025 + 2026, auto-detected | Full pipeline: capture, replay, live pit wall, analysis, strategy, LLM debrief | **Yes**: `tests/fixtures/bahrain_p1_2026_trimmed.cap` (≈1.0 MB, 1,032 datagrams, format 2026, PS5). No licence, so all rights reserved |
| [Alex-DSGN/F1-25-Telemetry](https://github.com/Alex-DSGN/F1-25-Telemetry) | **NO LICENSE** (API 404, no LICENSE file; `package.json` declares `"license": "MIT"` but no licence text is shipped) | Node.js (`dgram` + `ws`), vanilla JS/HTML/CSS | 2026-01-03 → **2026-02-20** (11 commits) | 2025 only (hard-coded) | Live LAN dashboard: lap table, race tower, pedal traces | No (demo-mode generator only). Contains EA's F1 25 structures `.txt` verbatim, renamed `.md` |
| [coicoikolokoy/f1-25-udp-telemetry](https://github.com/coicoikolokoy/f1-25-udp-telemetry) | **NO LICENSE** (README shows an MIT badge, but the linked LICENSE file does not exist) | Python (stdlib socket/struct), SQLite WAL, Flask, Chart.js, Streamlit | 2026-08-01 → **2026-08-22** (13 commits) | 2025 only, partial and buggy | Minimal per-lap logger + charts + 2D map | No (`*.db` is gitignored and was never committed; only PNG screenshots) |
| [edoofra/F1_2024_telemetry_analyzer](https://github.com/edoofra/F1_2024_telemetry_analyzer) | **MIT** (`Copyright (c) 2025 Edoardo Fratus`) | Java 21, Spring Boot 3.5, Spring Integration IP, Postgres + Flyway, Testcontainers | 2025-08-16 → **2026-06-02** (15 commits) | Header + Session only (2024/2025 layout) | Ingestion skeleton: ring buffer, header and session parsing, session persistence | No. Contains EA's `Data Output from F1 25 v3.pdf` verbatim (EA copyright, not MIT) |

**Licensing implications for pitwall.** Three of the four repos have no licence, so their code and data cannot be copied or vendored. Re-implement ideas independently from the official spec. The MIT repo (edoofra) contains little worth reusing. The EA spec files that two repos redistribute remain EA's copyright ("provided under license from EA for reference purposes only"). Link to EA's page rather than vendoring them.

---

## 1. skrx7392/f126-race-engineer (primary focus)

**What it is.** A "personal race engineer" for F1 25 with the 2026 Season Pack, captured from a PS5. A single Python service:
1. receives UDP on :20777;
2. writes every datagram losslessly to disk before parsing;
3. parses formats 2025 and 2026 per packet;
4. keeps a live session model and pushes it to a Svelte "pit wall" over WebSocket (10 Hz "fast" frames, 1 Hz "slow" frames, events immediately);
5. writes decimated rows to Postgres (telemetry at 20 Hz, wear at 1 Hz, laps, stints, events);
6. serves read-only analysis endpoints: lap compare, corners, stints/degradation, pre-race strategy, career/season progress;
7. can write a grounded post-session LLM debrief.

It deploys as a single k8s pod with `hostPort 20777/udp`. `decisions.md` states that the code was written autonomously by Claude (an orchestrator plus seven parallel subagents) over roughly two days.

### 1.1 Protocol handling (2025 / 2026)

- **Dispatch.** The parser reads the uint16 `packetFormat` at offset 0 and the packet ID at offset 6. It picks a per-format layout table, so 2025 and 2026 datagrams can be interleaved with no sticky state. The 29-byte header is shared.
- **Layout source.** The layouts were transcribed from third-party libraries, *not* EA's spec: `MacManley/f1-25-udp` C headers for 2025 and `volodymyr-fed/F1Game.UDP` C# v26 for 2026. EA's forum returned 403 to the authors. The 2026 layout was confirmed against their own live PS5 capture. All packet sizes they pin in tests match the official sizes in `f1-udp-spec.md` §3.
- **Layout tables as data.** The 2026 tables are built by importing the 2025 field tables and applying only the documented deltas: 24 cars, int16 g-force, uint8 engine temperature, uint16 IDs, ERS harvest limit, Session tail, CarTelemetry2 (ID 16), COLL severity. Tests pin the exact wire size of every packet, so a transcription slip fails CI instead of silently mis-decoding.
- **Error policy.** The parser never raises. Short, unknown, size-mismatched or hostile datagrams increment counters (`size_mismatch_total`, `unknown_packet_id_total`, …) and are dropped. The size check is strict equality.
- **Skipping.** IDs 5, 9, 12, 13 and 15 are counted but not decoded. By the authors' measurement this saves about 25% of decode volume.
- **2026 merge cache.** In format 2026 the "energy" fields (from CarStatus, ID 7) and the aero mode (from CarTelemetry2, ID 16) are folded into the CarTelemetry view through a small per-session cache. The cache resets on a session-UID change but **ignores UID 0**. This was a real bug: menu packets carry UID 0 and used to wipe the cache.
- **Event decoding.** Payloads are decoded per 4-character code. Unknown codes yield an event with empty details, so the v1.2 codes PMEN/PMDI/OVEN/OVDI come through but are not decoded. Optional u8 fields with value 255 are treated as "absent" (e.g. PENA `time = 255` on warnings).
- **Measured cadence** (60 Hz setting, PS5): IDs 0, 2, 6, 7, 13 and 16 follow the menu rate. Other IDs run at 20 Hz (11, 12), 10 Hz (10), 2 Hz (1, 5), 1 Hz (15) and 0.2 Hz (4). This is useful corroboration of the spec's frequencies.
- **Observed quirks worth reusing:** `gameYear` stays 25 in format 2026; `playerCarIndex` is often 21 rather than 0; menu packets have `sessionUID == 0`; FinalClassification is also emitted after qualifying with stale "points"; `gridPosition == 0` means "no slot"; `tyreAgeLaps` counts laps *completed* on the set.

### 1.2 Session lifecycle model (idea worth copying)

Identity has three levels:
- **session**: one `sessionUID`. A new UID closes the old session as `finished` if a FinalClassification was seen, otherwise `superseded`.
- **segment**: a restart inside the same UID (session time rewinds to about 0), or activity resuming after a timeout.
- **generation**: a flashback. Session time goes backwards by more than 0.05 s within a segment. Every row written after the rewind belongs to the new generation, and readers take the newest generation per lap.

Rules:
- UID-0 packets are ignored.
- If the first packet seen has session time > 60 s, the session is flagged "joined in progress". Laps before that arrive only through SessionHistory, without fuel or speed context.
- A 1 Hz `tick()` detects silence: "STALLED" after 5 s with no packets, and the session is retired after 30 min.
- Two subtle bugs they fixed, both worth testing for:
  - The player index must be absorbed from each header *before* lifecycle callbacks run. Otherwise callbacks see the previous packet's index.
  - Per-lap accumulators (fuel, top speed, ERS) must be cleared on a flashback. Otherwise the re-driven lap inherits the abandoned timeline's numbers.

### 1.3 Capture and replay format (`.f1raw`)

**File layout:**
- 6-byte magic: ASCII `F1RAW` followed by format byte 0x01.
- `uint32` LE length of a UTF-8 **JSON metadata** blob, then the blob: `capture_version`, `host`, `started_wall_ns`, `started_monotonic_ns`, `session_uid` (as a *string*, because u64 overflows JSON doubles), `segment`.
- A **zstd stream (level 3)** of records. Each record is `uint64 recv_monotonic_ns`, `uint64 recv_wall_ns`, `uint16 payload_len`, then the raw datagram bytes. The format stores no knowledge of F1 packets.

**Crash safety.** Every periodic flush (fsync about every 1 s) *ends a complete zstd frame*, and the next write opens a new frame. A file truncated by a crash therefore decodes cleanly up to the last flush. The reader walks frames explicitly and reports where the salvageable prefix ends.

**Naming and lifecycle:**
- Files are named `{UTC ISO-8601 basic}_{session_uid}_{segment}.f1raw` (no colons, for portability).
- While being written the file has an extra `.open` suffix; it is renamed on clean close.
- Name collisions get a `-N` suffix; files are never overwritten.
- The file is rotated when the state layer learns the real session UID or detects a new segment. The writer starts with `session_uid = "unknown"`.

**Doctrine.** The raw log is the source of truth. The database is a derived index that can be rebuilt with a `backfill` command after parser fixes. Size is roughly 40-80 MB per race-hour compressed.

**Test fixture format (`.cap`).** A simpler format used only for fixtures: repeated `<uint64 monotonic_ns, uint16 len>` followed by the payload, uncompressed. A tool converts `.cap` to `.f1raw`.

**Replay:**
- Replay pushes exactly the same `(bytes, recv_monotonic_ns, recv_wall_ns)` tuples onto the same queue the live UDP listener feeds, so no consumer needs a "live vs replay" branch.
- It carries the **original recorded timestamps**, not re-feed time. Derived lap times are therefore identical at any replay speed. Re-feed time is exposed separately for progress bars.
- Pacing comes from recorded *monotonic* deltas (not wall time, which can jump under NTP). Gaps are divided by the speed factor and scheduled against an absolute timeline so latency does not accumulate. `speed=max` never sleeps.
- With `loop`, timestamps jump backwards each pass. Consumers must already handle that because flashbacks do the same.
- **Backpressure:** replay blocks on a full queue rather than dropping, so replayed results equal live results.

### 1.4 Distance-based lap alignment and comparison

1. **Clean a lap trace.** Take stored samples (20 Hz) with `lap_distance_m` and `session_time_s`. Drop NaNs and sort by distance. Apply a "running-maximum" mask that keeps a sample only if it strictly exceeds all previous kept samples; this removes duplicates and flashback back-jumps in one pass. Apply the same mask on session time. Bridge isolated NaN holes in other channels by linear interpolation against distance. Require at least 2 samples.
2. **Common grid.** Use a uniform **5 m** grid (about 60 ms at 300 km/h; about 1,100 points per lap; capped at 4,096 points). It spans only the distance range *both* laps cover, so there is no extrapolation. Grid points outside a lap's coverage are NaN ("no opinion").
3. **Resample.** Continuous channels (speed, throttle, brake, steer, rpm) are linearly interpolated against distance. Discrete channels (gear, DRS/aero) use nearest-sample "hold", so there is no gear 4.5. Time at each grid point is session time interpolated against distance.
4. **Cumulative delta.** Measure elapsed time for each lap from the *first grid point both laps cover*. Delta = subject elapsed − reference elapsed, in ms; positive means the subject is slower. The curve therefore starts at exactly 0. It is NaN wherever either lap is missing.
5. **Guards.**
   - Refuse to compare laps with different `track_id` (an unknown track compares only with unknown).
   - The API output rounds distance to centimetres. It then de-duplicates equal neighbours, keeping the later sample, because slow running (standing start, pit lane) produces equal rounded distances that break chart bisect.
6. **Live delta** (in-session, separate code path).
   - For the current lap, keep a list of `(lapDistance, currentLapTimeInMS, sessionTime)`, appended only when distance strictly increases.
   - The reference is the session's fastest *valid* completed lap. Its trace is closed by appending `(trackLength, lapTime)`.
   - Live delta = current lap ms − reference elapsed at the same distance (bisect plus linear interpolation; proportional interpolation before the reference's first sample).
   - On a flashback, samples after the rewind session time are truncated.

### 1.5 Corner segmentation and braking detection

The design principle is that **a corner is a sustained speed minimum**. This needs no track map and no per-circuit corner list; the game provides none. Segmentation runs on the *subject* lap only, over the same 5 m grid. Every threshold is expressed in physical units (metres, km/h, pedal fraction), not samples, so it survives a grid change.

**Corner detection:**
1. **Smooth speed.** Apply a Savitzky-Golay filter with a **45 m** window (9 grid points; kept odd and long enough for the polynomial) and **polynomial order 2**. Order 2 keeps the depth and position of a parabolic minimum. The window erases throttle and kerb ripple but does not smear a hairpin's 60-80 m slow section. Fall back to the raw curve when the lap is shorter than the window.
2. **Find apexes.** Run peak-finding on the *negated* smoothed speed:
   - minimum **prominence 8 km/h**, measured against the local shoulders on either side, so it works the same for an 80 km/h hairpin and a 250 km/h sweeper;
   - minimum apex spacing **80 m**, so chicanes, S-bends and double apexes collapse into one braking event;
   - a cap of **40** corners.
3. **Entry and exit.**
   - For each apex, limit the search to half the gap to each neighbouring apex.
   - Find the *shoulder maximum* of smoothed speed in that range.
   - Entry is the **last** point before the apex where speed has recovered **90%** of the way from apex speed back to the shoulder. Exit is the **first** such point after the apex. (100% would chase noisy straight-line peaks.)
4. **Classify** by the minimum raw resampled speed inside [entry, exit]: slow < 120 km/h, medium 120-200 km/h, fast ≥ 200 km/h.
5. **Time loss per corner.** Loss = cumulative delta at exit − cumulative delta at entry. The remainder is "straights" loss: total delta − sum of corner losses.
6. **Reference handling.** The reference lap (session best, or the best lap at that circuit from *another* session) is never segmented itself. It is only read through the subject's windows. Corner numbering therefore stays stable regardless of which reference is chosen. They explicitly refuse to use the subject lap as its own reference.

**Braking point detection:**
- Search backwards from the apex, starting no earlier than the previous corner's exit and at most **400 m** before the apex.
- Treat the brake as applied when the brake input is above **0.10**. A resting pedal is slightly non-zero; above about 0.15 would miss light trail braking.
- Keep only runs that persist for at least **15 m** (3 grid points). This rejects dabs and downshift blips.
- The braking point is the start of the **last** sustained run before the apex, not the first. A mid-straight dab is not the corner's braking event.
- The same window is applied to the reference lap. Output includes `brake_point_delta_m` (negative = braked earlier) and the minimum-speed delta.

**Caveat they document.** These "corners" are detected braking zones. At Jeddah, 8 zones were detected for 27 official turns. Never label them "Turn N"; identify them by apex distance. Flat-out kinks without a speed dip are invisible to this method.

### 1.6 Stints, degradation, strategy (deterministic calculations)

**Stints and degradation.**
- Stints come from the game (state layer, one row per tyre set), or are reconstructed from compound changes in the lap table.
- These laps are flagged, not hidden, and excluded from fits: no time, invalid, out-lap, in-lap (the pit lap belongs to the stint it started on), and outliers above **107%** of the stint median.
- Degradation is a least-squares line of lap time against tyre age. It needs at least **4** usable laps.
- r² is reported to 3 decimals with a word: strong ≥ 0.8, fair ≥ 0.5, weak otherwise. A near-zero residual counts as a perfect fit, avoiding 0/0.

**Strategy (pre-race, "measured or omitted").** Every model input is measured at this circuit by this driver. There is no tyre database.
- *Evidence tiers.* Race and sprint stints beat practice stints, because practice runs on a light car and shows roughly double the wear and degradation. The tier travels with each number.
- *Wear rate.* % per lap of the worst wheel, regressed over lap number; needs at least 2 laps.
- *Derived degradation* for a compound with a wear rate but no lap-time fit:
  - Regress lap time against *cumulative* worst-wheel wear on one stint that has at least 4 clean laps and covers at least 2% of wear. Discard one-lap wear steps above 15%.
  - This gives a track-level ms-per-wear-% coefficient. Multiply it by the other compound's wear rate.
  - The result is labelled `derived`, and its assumption is stated in the output.
- *Wear cliff* = **28%** telemetry wear. This was measured at Jeddah and Miami. The in-game display reads about 2× the telemetry value.
- *Fuel.* Mean burn over racing laps, plus a 0.45-lap margin.
- *Pit loss.* The pit lap's time minus the clean-lap median at the same circuit. The default of 21 s is used only when no stop was recorded, and is flagged when used.
- *Plan enumeration:*
  - 1 and 2 stops, the two-compound rule, minimum stint length 3 laps, at most 12 plans.
  - Stint lengths are allocated greedily by marginal lap cost. Stint cost `L·base + deg·L(L−1)/2` is convex, so greedy allocation is exact.
  - Pit windows are exact feasibility bounds derived from the wear caps.
  - Negative fitted slopes are reported raw but clamped to 0 for planning.
- *Ranking.* By projected race time when every compound has a time model. Otherwise a stated heuristic (fewest stops, softer compound earlier) with all time fields null.

**Career.**
- A weekend is a run of consecutive sessions at one circuit, split on gaps over 48 h.
- The season increments when a circuit repeats.
- The last race-type session of a weekend is the GP; earlier ones are sprints. The wire format labels sprints as plain "Race"/"Race 2".
- Manual pins live in a separate table keyed by `session_uid`, so they survive database rebuilds.

### 1.7 Deterministic AI fact sheets (grounded debrief)

The split is that **all arithmetic is in a deterministic builder, and the LLM only writes prose**.

**Determinism.** The fact sheet is a pure function of database rows: no clocks, sorted iteration only, every float rounded on output. A test asserts that two consecutive builds are byte-identical. A sheet version and a prompt version are stored with every debrief.

**Missing data.** Fields that cannot be computed are *omitted*, and the reason goes into an `omitted` map. A zero always means "measured as zero", never "missing".

**Units.** Unit suffixes are part of every key (`_ms`, `_s`, `_kmh`, `_kg`, `_m`, `_c`, `_pct`). A `units` block restates them along with the **sign conventions**, for example "positive time_loss = slower than reference" and "negative brake_point_delta_m = braked earlier".

**Sections:**
- **session**: metadata.
- **result**: race sessions only. For non-race sessions a narrow `standing` block is used instead, because qualifying classification is stale.
- **pace**: laps completed, timed, valid and invalidated; best lap with sectors; median and IQR (Q1/Q3) over "representative" laps (valid, timed, not excluded by the stint engine); median − best.
- **stints**: compound, laps, tyre life, slope, r² and confidence word.
- **fuel**: median burn per lap, excluding refuels. A lap whose start fuel exceeds the previous lap's end fuel by more than 0.2 kg was a garage reset. Burns outside 0.05-5 kg are rejected.
- **events**: counts of safety cars, penalties, flashbacks and stops. A u8 value of 255 is treated as n/a.
- **weather**.
- **corners**: the best lap compared against the session's second-best lap and against the best lap at the circuit from another session. It reports the **top 3 corners with positive time loss** (apex distance, loss, minimum-speed delta, brake-point delta) plus an in-band caveat that corner numbers are not official turn numbers.

**LLM prompt contract (paraphrased).**
- Use only numbers that appear in the sheet; never calculate, convert or estimate.
- "Omitted" means unknown, not zero. No speculation about setup or rivals.
- Metric units and the sheet's sign conventions.
- Name corners by apex distance, never "Turn N". Do not quote "weak" degradation slopes.
- 200-300 words of plain prose addressed to "you", leading with the outcome that matters for the session type.
- End with exactly one concrete focus item drawn from the largest measured weakness.

**Operation.**
- The model is never in the live loop. Generation runs only on a clean session close (after flushing the DB writer) or from the CLI.
- Debriefs are stored append-only together with their fact sheet, so every sentence can be audited.
- Any OpenAI-compatible endpoint can be used.

### 1.8 Quality concerns

- **No licence.** Code and fixture are all-rights-reserved. Use the ideas only.
- **Spec provenance.** The parser was transcribed from third-party libraries, not EA's documents. Two concrete divergences from the official spec:
  1. The 2026 g-force divisor is **1024**, derived empirically. EA's PDF says **1000.0f**. Their residual test compared 256, 512, 2048 and 4096 but not 1000, so it cannot distinguish the 2.4% difference.
  2. The Season 8 (PDF v1.2) events PMEN, PMDI, OVEN and OVDI are not decoded.
- **README inaccuracy.** The README says "Your Telemetry: Public" is needed to see rivals' data. Per the spec, that setting only controls what *other* players see of *your* car.
- **Very young and AI-generated.** Two days of commits, one star. Many thresholds are tuned on a handful of personal sessions (Jeddah, Miami, Montreal, Bahrain): wear cliff 28%, prominence 8 km/h, pit loss defaults.
- **Heavy operational footprint** for a personal tool: Postgres, k8s/Traefik/cert-manager, an internet-exposed dashboard relying on a "read-only" invariant.
- **Python 3.14-only syntax.** Unparenthesised multi-except, PEP 758.
- **Strict size check.** Exact-size validation means any future EA layout tweak drops every packet of that type. This is visible in counters but is a hard failure mode.
- **Corner method limits.** It cannot see flat-out kinks, and complexes under 80 m are merged.
- **Fixture privacy.** The fixture's Participants packets include driver names, including what looks like the owner's in-game name.

### 1.9 Sample captures

| File | Status | Details |
|---|---|---|
| `tests/fixtures/bahrain_p1_2026_trimmed.cap` | committed, **no licence** | 999,235 B; 1,032 datagrams; every header `packetFormat=2026, gameYear=25, v1.24`; IDs 0,1,2,3,4,5,6,7,10,11,12,13,15,16 present. Bahrain Practice 1 at a 10 Hz send rate, cut around the hardest braking event (−4.5 g). Record format: `<QH` (monotonic ns, length) + payload |
| `bahrain_p1_2026.cap` (10 MB, 10 Hz), `bahrain_p1_60hz_2026.cap` (25 MB, 60 Hz) | **not published** (gitignored) | referenced by skipped tests |

There is no licence on the repo, so the fixture is not redistributable. pitwall should record its own captures for golden tests.

---

## 2. Alex-DSGN/F1-25-Telemetry

- **Licence:** NO LICENSE. GitHub detects none and there is no LICENSE file. `package.json` contains `"license": "MIT"`, but without licence text that is only a metadata claim; treat it as unlicensed.
- **Stack:** Node.js. A single ~2,000-line `backend/server.js` uses `dgram` for UDP and `ws` to broadcast state, and serves static `public/` (vanilla JS, ~45 KB `app.js`). The docs are in Russian.
- **Dates:** created 2026-01-03, last commit 2026-02-20 (11 commits).
- **What it implements:**
  - Format 2025 parsing of Session, LapData, Participants, CarTelemetry, CarStatus, CarDamage and SessionHistory, with per-car strides hard-coded to the official 2025 sizes and 22 cars.
  - Live dashboard: current lap time, best lap, lap table (time, delta to PB, validity, sectors), session-best sectors highlighted, a race table (position, change versus first-seen position, gap ahead and to leader, tyre stint stack, pit indicator, stops), player throttle/brake traces versus previous and best lap, fuel surplus/deficit in laps, ERS %, penalties and warnings.
  - A synthetic demo mode.
- **Ideas worth noting** (simple but practical):
  - SessionHistory (ID 11) is the authoritative per-car lap and sector table, with LapData as the live fallback.
  - A per-car **pit-lane tracker**: from `m_pitLaneTimerActive` rising to falling, keep the max `m_pitLaneTimeInLaneInMS` and the max `m_pitStatus`, and attribute them to the entry lap.
  - Cache the last non-zero sector times, because LapData zeroes sectors at lap start.
  - Pedal-trace decimation: record a point when the car has moved **5 m or 80 ms**, whichever comes first.
  - Fuel margin = `m_fuelRemainingLaps` − laps remaining.
  - The CarDamage per-car stride is derived defensively from the datagram length.
- **Quality concerns:**
  - No `packetFormat` check. Format 2026 (24 cars, changed strides) would be silently misparsed.
  - "Delta vs best" is whole-lap elapsed time against best lap time, **not distance-aligned**, so it is meaningless mid-lap.
  - Everything lives in global mutable state in one file. No tests, no persistence or replay, and ERS % is computed from a constant.
- **Captures:** none.
- **Bundled spec:** `F1_25_Telemetry_Output_Structures.md` is byte-identical (SHA-256 `49ccead…`) to EA's official F1 25 `.txt`. That is EA's copyright.

## 3. coicoikolokoy/f1-25-udp-telemetry

- **Licence:** NO LICENSE. The README displays an MIT badge linking to a `LICENSE` file that does not exist.
- **Stack:** Python with stdlib `socket` and `struct` for ingestion; SQLite in WAL mode; Flask REST (port 5001); Chart.js dashboards (full and "lite"); Streamlit, pandas and matplotlib inspection scripts; a mock UDP sender.
- **Dates:** created 2026-08-01, last commit 2026-08-22 (13 commits).
- **What it implements:**
  - Player-car-only decoding of Motion (world X/Z), LapData (lap distance, current lap number) and CarTelemetry (speed, throttle, steer, brake).
  - A three-table SQLite schema (tracks → laps → telemetry_samples). A new lap row is created only when the lap number increases by exactly 1.
  - APIs listing laps and returning telemetry downsampled to ≤600 points.
  - A 2D track map drawn from world X/Z with an offscreen-canvas outline cache.
- **Ideas worth noting:** using X/Z world positions for a track map; a cheap lap-segmentation rule (strict N→N+1) that ignores menu bounces; capping chart payloads at about 600 points.
- **Quality concerns (significant):**
  - **The LapData per-car stride is 56 bytes; the official value is 57.** Any `m_playerCarIndex` > 0 therefore reads the wrong bytes. The code forces the index to 0 for LapData and adds range "sanity filters" that mask the garbage (e.g. the "1.28e+36" distances the README mentions).
  - No `packetFormat` or `sessionUID` handling. The PacketID enum stops at 7.
  - The default `current_track_id = 11` carries the comment "Spa", but 11 is Monza.
  - The mock sender writes header bytes in the wrong slots.
  - The README advertises scripts and backup databases that are not in the repo, in heavy marketing language.
  - A per-sample SQLite insert at 60 Hz.
- **Captures:** none. `*.db` is gitignored and the full commit history contains only PNG screenshots of maps and charts.

## 4. edoofra/F1_2024_telemetry_analyzer

- **Licence:** **MIT** ("Copyright (c) 2025 Edoardo Fratus").
- **Stack:** Java 21, Spring Boot 3.5.4 (web, webflux, websocket, data-JPA/JDBC), Spring Integration IP (`UnicastReceivingChannelAdapter`) for UDP, PostgreSQL + Flyway, Testcontainers, Micrometer/Prometheus, Maven, GitHub Actions. A `CLAUDE.md` indicates AI-assisted development.
- **Dates:** created 2025-08-16, last commit 2026-06-02 (15 commits).
- **What it implements:**
  - The ingestion pipeline: UDP adapter → channel (sync or async queue of 1,000) → handler → **bounded ring buffer** (capacity 10,000, overwrites the oldest, read-write lock, atomic stats) → background poller (10 ms) → header parser (29 bytes; offsets match the spec) → dispatcher.
  - **Only the Session packet (ID 1) is parsed.** It uses absolute offsets that match the official 2025 layout, and accepts any length ≥ 753, so a 2026 Session packet also parses correctly up to its shared prefix.
  - A Session entity opened and closed on `sessionUID` change, with a 5-minute snapshot of mutable fields.
  - REST stats and health endpoints: DEGRADED when the drop rate exceeds 5%.
  - The README's React UI, lap analysis and exports are **not implemented**. Despite the "F1 2024" name, comments and the track table target F1 25.
- **Ideas worth noting:** decoupling the socket thread from processing with a bounded, overwrite-oldest ring buffer plus drop accounting, and a health state derived from the drop rate. Testcontainers-based integration tests for persistence.
- **Quality concerns:** very early stage, with no lap or telemetry decoding. Committed build artefacts (`target/`, `.idea/`). The README does not match the code.
- **Captures:** none (test resources contain only properties).
- **Bundled spec:** `Data Output from F1 25 v3.pdf` is byte-identical to EA's official PDF (SHA-256 `850199d1…`). It is EA material and not covered by the repo's MIT licence.

---

## 5. Ideas pitwall should implement independently (synthesis)

1. **Lossless raw capture before parsing.** Use an append-only, length-prefixed record log with receive timestamps (monotonic and wall) and per-flush compression frames for crash safety. Keep it parser-agnostic, and make it the source of truth with re-derivation/backfill. f126 shows the value; design our own container (e.g. our own magic, a versioned header and JSON metadata).
2. **Replay through the identical ingest path**, carrying the original timestamps, with pacing from monotonic deltas and blocking backpressure. Replays then become deterministic test fixtures.
3. **Per-packet dispatch on `(packetFormat, packetId)`** with exact-size tables generated from the official structs (see `f1-udp-spec.md`). Count unknown or mismatched packets and drop them; never crash. Tolerate unknown event codes.
4. **Session / segment / generation identity**, ignoring UID 0. Flashback handling is a data-integrity feature: discard or version samples after the rewind.
5. **Distance-domain analysis.** Clean traces to be strictly increasing; use a uniform grid (about 5 m); interpolate continuous channels linearly and hold discrete ones; NaN outside coverage; cumulative delta anchored at the first common point.
6. **Corner and braking-zone segmentation from speed minima** (smoothing + prominence + spacing + shoulder-recovery bounds), and braking point = start of the last sustained brake run before the apex. Tune thresholds on our own data. Refer to corners by distance, or map them to official turn numbers through a per-track table, which pitwall could add as an improvement.
7. **Deterministic, unit-suffixed, omission-aware fact sheets** as the only input to the AI coach, with prompt rules forbidding new numbers, sign conventions stated in-band, and versioned prompt and sheet stored with every output.
8. **Measured-only strategy maths** with explicit evidence tiers and "untested"/"derived" labels instead of invented defaults.
9. **Operational metrics.** Track packets/s, kernel drop counts (raise SO_RCVBUF to MiB scale) and stall detection after N seconds of silence.
