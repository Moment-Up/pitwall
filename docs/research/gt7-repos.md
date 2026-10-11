# GT7 open-source repository review

Research date: 2026-10-10. Method: `gh repo view`, `gh api repos/OWNER/REPO/license`, and source read through `gh api .../contents`. Nothing was cloned into the project and nothing was executed.

**Clean-room rule for pitwall:** the ideas below are described in prose. Do not copy code from the GPL repositories (gt7dashboard, GT7Eng, and the GPL dependencies they pull in). The MIT repositories (gt7-udp, grandturismo-srs-proxy, sim-race-engineer) could legally be reused with attribution, but their GT7 layouts contain errors (noted below), so re-implement from `gt7-protocol.md` instead.

## Summary table

| Repo | Licence (SPDX) | Stack | Last commit | Stars | Sample captures |
|---|---|---|---|---|---|
| gt7coder/grandturismo-srs-proxy | **MIT** | Python 3.9, `pure_salsa20`, PyInstaller | 2022-07-28 (`f847da6`) | 16 | None |
| wesleyegberto/sim-race-engineer | **MIT** | Python ≥3.11, pygame-ce, pycryptodome, pandas/pyarrow (Parquet), Plotly Dash, piper-tts, ollama/anthropic/openai SDKs, pyserial, Arduino firmware | 2026-10-05 (`6befe8d`) | 3 | None (screenshots only) |
| neW1-/GT7Eng | **GPL-3.0-or-later** (`pyproject.toml`; GitHub reports GPL-3.0) | Python ≥3.11, `gt-telem` (GPL-3.0), FastAPI/uvicorn web HUD, faster-whisper, Piper / macOS `say`, OpenAI-compatible local LLM, Node ≥20 Discord bridge (discord.js, @discordjs/voice, opusscript, prism-media), BLE pixel displays (pypixelcolor), Home Assistant REST | 2026-07-10 (`701d150`) | 6 | `tests/fixtures/simple_race.jsonl`: 3 synthetic normalised frames, GPL-3.0-or-later |
| MacManley/gt7-udp | **MIT** (SPDX headers in source) | C++ Arduino library for ESP32/ESP8266, everard Salsa20 | 2026-09-18 (`a768574`, v2.1.3) | 75 | None |
| snipem/gt7dashboard | **GPL-3.0** (GitHub-detected; LICENSE is GPLv3 text; no "or later" grant found, so treat as GPL-3.0-only) | Python, Bokeh 3.6 server, pandas, scipy, pycryptodome, tabulate. Docker image and Windows PyInstaller build. | 2026-03-06 (`aac5bf3`) | 326 | `test_data/broad_bean_raceway_time_trial_4laps.json` (1.36 MB): processed per-tick lap arrays, not raw packets, GPL-3.0 |

Related references consulted (not in scope but relevant):
- Nenkai/PDTools: MIT, the reference implementation.
- zetetos/gt-telemetry: MIT. Go; supports all of A/B/~/C. Ships a Kaitai spec under CC0-1.0, a `demo.gtz` capture of decrypted packets, and circuit centreline JSONs.
- RaceCrewAI/gt-telem: GPL-3.0. Used by GT7Eng.
- Bornhall/gt7telemetry: GPL-3.0. gt7dashboard's ancestor.
- ddm999/gt7info: MIT-0. Car and course databases.

---

## 1. gt7coder/grandturismo-srs-proxy

- **What it does:** a one-file proxy. It polls GT Sport and GT7 alternately, sending a heartbeat `A` before every receive. It decrypts with the A-variant XOR, unpacks a 252-byte prefix and re-emits the result as a Sim Racing Studio "api" v102 UDP packet (port 33001) to drive motion rigs, wind and shakers. It forwards only when the on-track flag is set and the paused flag is clear.
- **Notable facts:** it carries the GT Sport parameters (key `Simulator Interface Packet ver 0.0`, ports 33339/33340). It sanity-checks the decrypted magic.
- **Weaknesses / do not reuse:**
  - The struct layout is from early 2022 reverse-engineering and is wrong in several places: it treats 8 bytes at 0x40 as IV, swallowing the fuel-level field, calls angular velocity "acceleration", and reads lap count as int32.
  - A heartbeat per packet is unnecessary.
  - The 5 s socket timeout loop alternates between games.
- **Ideas worth re-implementing:**
  - **Gate downstream outputs on state flags.** Emit nothing when not on track or when paused. pitwall's coaching/voice should use the same rule so it never speaks in menus.
  - **Probe multiple titles** by trying each game's port/key pair until the magic validates. This is useful if pitwall later supports GT Sport.
- **Captures:** none.

## 2. wesleyegberto/sim-race-engineer

- **What it does:** a desktop pygame dashboard for GT7 on macOS (afplay audio; Linux and Windows are TODO). It has the following parts:
  - (1) **Live dashboard:** gauges, G-meter, slip-angle bar, per-wheel slip borders, suspension bars, TCS/ASM/rev/handbrake chips, race-status badges.
  - (2) **Voice alerts:** one-way only, with no speech recognition. Offline **Piper** TTS (en_US/pt_BR voices auto-downloaded from HuggingFace) runs on a daemon thread with a queue. Each alert has its own cooldown. Alerts cover lap/best/final lap, fuel thresholds, pit window, temperatures, tyre "wear", race reports at 35/70 %, position changes, and strategy check-ins.
  - (3) **Strategy engine:**
    - *Auto strategy*, recomputed every lap: laps to fuel-out from average fuel per lap, laps to tyre limit from estimated wear rate, a recommended pit lap with a buffer, and a pit reason (FUEL/TYRES/both).
    - *Planned strategy*: up to 3 user-defined stops, with approaching/box-now/missed/reschedule alerts.
    - *Strategy advisor*: fuel needed to finish, fuel delta, stop count and windows, and a health state of ON_PLAN/REVISE/CRITICAL.
  - (4) **Recording:** one Parquet file per lap (Snappy) at about 60 Hz, written on lap completion so a crash loses at most one lap, and merged into `session.parquet` at session end.
  - (5) **Session analysis:** a separate `sim-race-analyze` Plotly Dash app with a track map coloured by speed or TCS/ASM, tyre temps over the lap, and time-series overlays across laps.
  - (6) **AI setup advisor:** aggregates per-lap statistics (tyre temps by zone, pressures, lateral-G distribution, slip angle, TCS/ASM intervention rates, pedal-trace counters) into a markdown prompt. That prompt goes to Ollama, Anthropic or an OpenAI-compatible server, with a GT7 "knowledge base" system prompt (camber from inner/outer temperature imbalance, pressure effects, etc.). It has Basic and Advanced levels and asks for output in GT7 setup-menu format.
  - (7) **Airflow fans** over USB serial (Arduino), with a speed-to-duty map, a kick-start pulse, a minimum sustain duty and a 100 ms keep-alive.
- **Critical data-quality problems (read before borrowing ideas):**
  - Its parser reads **tyre pressures from 0xD4–0xE0** and **inner/middle/outer tyre temps from 0xE4/0xF0/0xFC/0x108**. It also reads **handbrake from 0x110**. PDTools documents 0xD4–0xF3 as unset/reserved, and 0xFC, 0x108 and 0x110 are RPM-after-clutch and gear ratios 2 and 4. The pressure alerts, the camber/pressure diagnosis in the setup advisor, and the "inner zone > 110 °C wear proxy" are therefore built on non-telemetry values. **The setup advisor's advice is not grounded for GT7.**
  - It uses the base `A` packet only (296 bytes), so it has no steering.
  - It sends heartbeats every 100 ms. This works but is excessive.
  - Its roadmap describes ACC as "UDP JSON (graphics/physics/static), port 9000", which is incorrect. See `forza-ac-acc-iracing.md`.
- **Ideas worth independently re-implementing:**
  - **Tyre-wear estimate from rolling radius.** Per wheel, keep a rolling median of tyre radius, sampled sparsely (1 in 6 frames, about 30 s window) and only above about 5 m/s. Lock a baseline when the buffer first fills. Express wear as (baseline − current median) / an assumed usable depth (they use 7 mm). Treat a median that jumps above baseline by more than about 3 mm as a tyre change. **This is unvalidated:** before trusting it, validate that GT7's radius actually shrinks with wear by comparing against in-game wear after a stint.
  - **Pit-stop detection from fuel rising frame-to-frame**, held for about 30 frames to debounce.
  - **Cooldown per alert key plus priority ordering** (for example "fuel < 1 lap" outranks "fuel low"). Use "once per lap" or "once per bucket" semantics.
  - **Race checkpoints** at fixed race-percentage points (35 %/70 %) for a summary call. Strategy check-ins at 33/66 % for long races, or every N laps for short ones.
  - **Per-lap Parquet writes plus a session merge** for crash-safe recording, with a decoupled analysis process.
  - **Prompt grounding pattern** for an LLM setup advisor: aggregate into compact markdown tables, explicitly mark sections "data not available", and instruct the model not to infer from missing data. This pattern is good; the data feeding it is not (see above).
- **Captures:** none in the repo.

## 3. neW1-/GT7Eng

- **What it does:** a local macOS "race engineer" for GT7 on PS5.
  - It auto-discovers the PS5 through gt-telem, which broadcasts a PlayStation device-discovery query, and requests heartbeat type `B` by default.
  - It normalises frames into its own `TelemetryFrame` model.
  - It keeps race state: lap history, fuel per lap, a pit-required vs box-now distinction, timed-race mode when `total_laps == 0` (with a countdown that freezes on pause), retry/new-session detection, tyre age, and an incident/spin monitor.
  - It counts TC, ASM, wheelspin and lockup events.
  - It serves a FastAPI web HUD. Write actions are restricted to localhost and settings persist to `.env`.
  - It drives Discord voice in both directions, two BLE LED-matrix displays (gear/revs and coaching pages), and a Home Assistant fan.
  - JSONL capture/replay supports offline testing.
  - Live validation is documented (May 2026): about 60 Hz from the PS5, with spoken position, fuel, pit, lap and tyre Q&A over Discord.

### 3.1 Voice loop structure (as implemented)
- **Audio path:** there is no local microphone path. Driver audio goes **through Discord**:
  - A Node sidecar joins a private voice channel and subscribes only to the configured driver's Opus stream.
  - It ends a segment after **350 ms of silence** (discord.js `EndBehaviorType.AfterSilence`) and decodes to **48 kHz stereo PCM**.
  - It discards segments shorter than **450 ms** and caps them at **6 s**, wraps each one as WAV, and POSTs it to the Python service at `/api/discord/audio`.
  - There is a typed-chat endpoint (`/api/chat`) in the HUD, but no browser mic capture.
- **Push-to-talk:** there is no app-level PTT. Turn-taking relies on Discord's own voice activity detection or the user's Discord PTT key. The bot **pauses its receive streams while it is speaking**, so it never transcribes its own TTS.
- **STT:** **faster-whisper**.
  - The default model is `tiny.en`; `base.en` is recommended on a 16 GB M4. It runs with int8 compute and greedy decoding (beam size 1), with the language forced to English.
  - A VAD filter is applied first, with a retry without VAD if the result is empty. `condition_on_previous_text` is off.
  - A **command-vocabulary initial prompt and hotwords** bias recognition toward race-radio phrases.
  - Confidence = mean over segments of (1 + avg_logprob), clamped to [0, 1]. The threshold defaults to 0.55; 0.45 worked better on a headset.
- **Wake word:** not acoustic. In `wake_phrase` mode, the **transcript** must start with the configured phrase (default "engineer"). Saying only the phrase gets "Engineer online."
- **Modes:**
  - `quiet_driver`: no wake phrase. Strict deterministic commands only, plus optional LLM *intent repair*.
  - `quiet_driver_ai`: as quiet_driver, but high-confidence unknown speech goes to the LLM for free-form Q&A.
  - `wake_phrase`.
  - `silent` (Discord bridge).
- **NLU:** an ordered keyword/regex intent parser handles fuel, burn rate, last-lap fuel, pit, pit age, laps left, time left, last/best lap, position, tyres, status, keep quiet, more fuel updates, radio check, and set race duration. Deterministic code owns all race math.
- **LLM:** any OpenAI-compatible local server. The recommended model is `gemma-4-e4b-it-4bit` on 16 GB Apple Silicon, with max tokens about 80 and thinking disabled.
  - **Intent repair** maps a noisy transcript to one of about 15 whitelisted commands, with its own confidence threshold.
  - **Free-form Q&A** receives only the race-state snapshot, request date/time and a short memory. The system prompt forbids inventing data and says fuel is a percentage.
- **Short-turn memory:** one structured fact (for example "best lap = lap 2, 1:32.1") is kept for 60 s. Follow-ups like "which lap was that?" are resolved deterministically before any LLM fallback.
- **TTS:** **Piper** (an example voice is `en_GB-alba-medium`), with **macOS `say`** as fallback. Output is cached on disk by a SHA-256 of the text. An optional "radio" wrapper adds a short 880 Hz pre-tone and 420 Hz post-tone. The Python side queues jobs; the bridge **polls for jobs every 1000 ms** and acknowledges playback.
- **Latency:**
  - No end-to-end numbers are published. The latency budget is managed by small STT models, low LLM max tokens and a short timeout (default 8 s; 20 s suggested with the local server).
  - STT, LLM and TTS run in worker threads (`asyncio.to_thread`) so telemetry ingestion never stalls.
  - **Driver requests pre-empt queued alerts**: the bridge clears pending audio, pauses job polling during processing, then polls immediately for the answer.
  - Structural latency adds up to roughly 0.35 s (silence end) + STT + intent/LLM + TTS + up to 1 s (job poll).
- **Weak spots:**
  - Water and oil temperature alerts (≥110 / ≥130 °C) can never fire, because GT7 sends constants of 85 and 110.
  - Position comes from the 0x84 field that PDTools documents as pre-race only (conflicting; see `gt7-protocol.md`).
  - Off-track detection is listed as TODO. Variant `C` surface type would solve it.

### 3.2 Ideas worth independently re-implementing
- **Deterministic-first voice pipeline with LLM fallback.** Use a whitelisted intent set, LLM intent repair constrained to that whitelist, and free-form LLM only above a confidence gate, answering strictly from a state snapshot.
- **Self-echo suppression:** mute STT while the engineer speaks. **Barge-in priority:** driver speech cancels queued alerts.
- **Vocabulary-biased STT:** an initial prompt/hotwords list of the command phrases, plus a VAD-then-no-VAD retry.
- **Alert coalescing:** wait about 1.5 s for position changes to settle, then speak the net change ("Gained 3 places, now P10").
- **Timed-race handling:** `total_laps == 0` means timed. Get the duration from the user (by voice: "set race duration to 30 minutes"). Count down only while racing, not while paused.
- **Session retry detection:** time of day rewinds by 10 s or more, the packet id restarts with start-like speed, or the lap resets to 1 after loading/menu. On detection, reset fuel history so stale data does not trigger "box now".
- **Pit service and tyre-age inference:** fuel rises by ≥ 1 point over the stint minimum, or ≥ 2 tyre radii jump up by ≥ 1.5 %.
- **Fuel strategy wording:** separate "stint range" from "margin to finish". Reserve "box this lap" for a range of about one lap or less. Require at least two clean lap samples before urgent calls.
- **Short-lived structured memory** for follow-up questions, kept out of the LLM where possible.
- **Telemetry-stale alerts** throttled, with silent reconnect, to avoid voice loops when packets flap.
- **JSONL capture/replay** of normalised frames for deterministic tests.

- **Captures:** only the synthetic 3-frame fixture (GPL-3.0-or-later). There are no real recordings.

## 4. MacManley/gt7-udp

- **What it does:** an Arduino C++ library for ESP32/ESP8266.
  - `begin(ip, variant)` binds 33740 and selects the heartbeat character (`A`, `B`, `~` or `C`; anything else falls back to A).
  - `sendHeartbeat()` sends the single character to 33739.
  - `readData()` reads a datagram, **detects the variant by length (296/316/344/368)**, picks the XOR (**A 0xDEADBEAF, B 0xDEADBEEF, ~ 0x55FABB4F, C 0xDEADBEEF**), builds the nonce as IV2‖IV1 and decrypts into a packed struct.
  - Helpers decode the gear nibbles, flags, powertrain type (from fuel capacity), tyre linear speed (radius × ω × 3.6) and slip ratio.
  - The README documents all four packet structures, surface letters, flags, and a 500+ row car-ID table (derived from ddm999/gt7info).
- **Encryption and heartbeat facts it states:**
  - The key string. Its README says 39 bytes; it is actually 38, and the first 32 are used.
  - "Heartbeat every 1000 packets (~16 s) or the connection will cease."
  - B "not available in Sport Mode". `~` "not available in Replays". These are unverified claims.
- **Caveats:**
  - The README prose says `PacketC : public PacketB`, but the header is correct (`PacketTilda`).
  - Field semantics for `~` unknowns are speculative ("torque vectors").
  - The `startlightsexploit` example uses an observation that the in-game **time of day (0x80) does not advance until lights-out** in rolling and grid starts, and triggers a servo on the first change. Its use in public lobbies is disclaimed by the author. pitwall should take only the observation, as a **race-start detector**.
- **Ideas worth re-implementing:** length-based variant dispatch with a per-variant XOR table; a defensive fallback to the A layout on unknown lengths; derived per-wheel linear speed and slip ratio; and race-start detection from time of day starting to advance.
- **Captures:** none.

## 5. snipem/gt7dashboard

- **What it does:** a Bokeh web dashboard (`bokeh serve`) forked from Bornhall's script.
  - A background thread binds 33740, heartbeats `A` (to the console IP or broadcast 255.255.255.255), sends a heartbeat every 100 packets and on 10 s timeouts, decrypts, filters by increasing packet id, and logs per-tick arrays while "in race" (flag bit 0, or "always record" for replays) and not paused.
  - It finalises a lap when the lap counter changes. Laps can be saved and loaded as JSON (with pickle legacy).
  - Car names come from the ddm999 CSV.

### 5.1 How it compares laps without a lap-distance field
1. **Synthetic distance axis.** For each tick, add speed (km/h ÷ 3.6 → m/s) × a fixed **16.668 ms** tick (taken from GTPlanet) to a running sum, giving metres since lap start. Ticks are assumed uniform, with no correction for dropped packets.
2. **Live lap clock.** Elapsed ticks ÷ 60, corrected by a running "special packet time": after each lap, the difference between the game's reported last-lap time and the tick-derived time is accumulated and applied to later laps, which absorbs tick-rate drift.
3. **Time delta vs reference.**
   - For each lap, build a series of distance indexed by elapsed time.
   - Resample it onto a 10 ms grid and linearly interpolate.
   - Invert it to elapsed time indexed by distance.
   - Outer-join the reference and comparison laps on distance, interpolate the gaps, and subtract (comparison − reference).
   - Plot the delta against distance. Above or below zero shows where time was lost or gained.
4. **Median lap.** Take laps within ±10 s of the best lap and compute an **element-wise median by tick index** for every per-tick array. This is aligned by sample index, not by distance, so it smears corners when laps differ in length.
5. **Speed consistency ("variance").**
   - Take the N fastest laps (default 3, within 5 % of the fastest, excluding replays and empty laps).
   - Merge their speed traces on the synthetic distance axis and interpolate.
   - Plot the standard deviation of speed across laps against distance. High values mark inconsistent corners.
6. **Corner and straight markers.** Run scipy `find_peaks` on speed (and on negated speed) with a minimum peak width of 100 samples (~1.7 s). Valleys are corners (minimum speed) and peaks are straights (maximum speed). A table compares the last lap's and the reference lap's peak/valley speeds in order.

### 5.2 How it detects braking points
- A **braking point** is any tick where brake goes from **exactly 0 to > 0** relative to the previous tick. It is placed at the car's (X, Z) world position and drawn as circles on the 2-D race-line map for the last lap (blue) and the reference lap (magenta). This is optional (`GT7_ADD_BRAKEPOINTS=true`) because Bokeh renders it slowly.
- Separately, race-line **mode colouring**: braking where brake > throttle, throttle where throttle > brake, and coasting where both are 0. Each mode is plotted as its own masked line on the map, and braking/coasting/throttle traces are plotted against distance.
- Limitations: there is no threshold or hysteresis, so trail-brake taps and noise create extra points. Points are not matched between laps by corner, so the comparison is visual only. There is no brake-release or peak-pressure analysis.

### 5.3 Other per-lap metrics
- Per-mille of ticks at full throttle, full brake, throttle and brake overlapping, coasting, and tyres spinning (any wheel's surface-speed ratio > 1.1; the RR channel is wrongly computed from FR, a bug), plus tyres over 100 °C.
- Fuel consumed per lap. A relative **fuel-map table** (mixture −5..+5) uses GTPlanet-sourced constants of 8 % consumption and 4 % power per level.
- Max speed, minimum body height, and a yaw-rate trace (computed from the 0x20 quaternion component, so it is not a true rate).

### 5.4 Ideas worth independently re-implementing (prose only; GPL)
- Distance-aligned lap comparison via time↔distance inversion and join. pitwall should use a **centreline projection** for distance instead of speed integration, and **corner-matched braking points**: detect brake onset with a threshold and debounce, and match to the nearest corner apex by distance.
- Consistency band = speed standard deviation across the best N laps on a common distance grid.
- Corner/straight segmentation from speed minima and maxima with a minimum width.
- Correcting the live lap clock against the game-reported lap time.
- Broadcast-heartbeat discovery.
- **Captures:** `test_data/broad_bean_raceway_time_trial_4laps.json`, 4 laps of processed arrays. It is GPL-3.0, as part of the repo. Don't vendor it into pitwall's tests; record our own.

---

## Cross-repo lessons for pitwall
1. **Re-implement the parser from PDTools (MIT) and the gt7-udp README (MIT) layout,** not from sim-race-engineer or srs-proxy, whose layouts contain wrong fields.
2. **Request variant `C`** with fallback. It provides steering, current-lap time and surface type, which removes several heuristics that GT7Eng and gt7dashboard needed.
3. **Treat water/oil temperatures as constants**, and do not alert on them.
4. **Lap distance** should come from a reference centreline. zetetos/gt-telemetry's MIT circuit JSONs (about 1 m point spacing plus `lengthMetres`) are a permissive starting point. Fall back to speed integration.
5. **Voice:** GT7Eng's "deterministic first, whitelisted LLM intent repair, gated free-form" design, plus barge-in and self-echo suppression, fits a coach. Add a local mic path with real PTT (a wheel button via HID) rather than depending on Discord.

## Sources
- https://github.com/gt7coder/grandturismo-srs-proxy (`main.py`, `gt_packet_definition.py`, `srs_packet_definition.py`)
- https://github.com/wesleyegberto/sim-race-engineer (`README.md`, `docs/tech.md`, `docs/roadmap.md`, `src/simraceengineer/telemetry/gt7/parser.py`, `receiver.py`, `tire_wear_estimator.py`, `analysis/setup_advisor/*`)
- https://github.com/neW1-/GT7Eng (`README.md`, `pyproject.toml`, `src/gt7eng/{stt,tts,voice,llm,telemetry,state,config}.py`, `bridge/discord/{README.md,src/bot.js,src/config.js}`)
- https://github.com/MacManley/gt7-udp (`README.md`, `src/GT7UDPParser.{h,cpp}`, `library.properties`)
- https://github.com/snipem/gt7dashboard (`gt7dashboard/gt7communication.py`, `gt7helper.py`, `gt7diagrams.py`, `main.py`, `README.md`)
- https://github.com/Nenkai/PDTools, https://github.com/zetetos/gt-telemetry, https://github.com/RaceCrewAI/gt-telem, https://github.com/Bornhall/gt7telemetry, https://github.com/ddm999/gt7info
