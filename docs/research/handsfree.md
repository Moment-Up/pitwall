# Hands-free talking and Windows speech recognition: research and evidence

Lane handsfree (2026-10-12). Code: `src/pitwall/voice/handsfree.py`, `src/pitwall/voice/stt_sherpa.py`, the hooks in
`src/pitwall/voice/hub.py`, `web-react/src/lib/handsfree.ts`; checks: `scripts/handsfree_check.py`. Protocol:
[voice-protocol.md](../voice-protocol.md). Setup: [radio-setup.md](../radio-setup.md#talking-to-the-engineer).

**Evidence tiers here.** *Recorded*: the owner's real captures, used only for the stationary gate and the wheel
button. *Synthetic*: macOS `say` audio through the real speech engines on the Mac. *Unit*: pure rules. *Live*: none.
No recorded human voice exists yet, so the "real voice" check (A9) is owed.

## 1. What was asked

The radio could only be keyed by the on-screen button, Space on a Mac, or F1 25's wheel button (UDP Action 1 through
the game's `BUTN` event). GT7, Assetto Corsa and Forza send no button data, and the wheel is plugged into the PS5, so
in those games the driver had to take a hand off the wheel to ask anything. On Windows, spoken questions needed a
separate whisper.cpp server.

## 2. Findings

### Talking without the game

1. **AirPods stem presses and Bluetooth media keys cannot reach a web page.** Press-to-mute for AirPods is a
   CallKit / `AVAudioApplication` feature for native apps (WWDC23 session 10233). On iOS, Media Session handlers need
   the page to be "Now Playing", in practice an `<audio>`/`<video>` element playing; the radio deliberately avoids
   those elements because mixing them with microphone capture degrades both ([voice-stack.md](voice-stack.md) 5.2).
   Not attempted; a native iOS shell could do it.
2. **Bluetooth keyboard-type buttons work.** Page turners and pedals that present only as a keyboard (AirTurn,
   PageFlip, Donner) deliver `keydown`/`keyup` to Safari pages. Keyboard-plus-pointer devices stopped delivering key
   events in iPadOS 18.4+ in Desktop Mode (WebKit bugs 301563 and 290779), and iPad Safari defaults to Desktop Mode,
   so the docs say to pick a keyboard-only device. Some send key repeat while held and some a single tap: hold and
   tap must both work.
3. **A spare Bluetooth game controller can work**: Safari supports `navigator.getGamepads()` (MFi, Xbox and
   DualSense since iOS 14.5). It needs one press to wake the API; per-button mapping is unverified. It must be a spare
   controller (the wheel and the console's controller are on the PS5). Not tested on a device.
4. **No wheel buttons outside F1 25** (GT7 `adapters/gt7/adapter.py`, Assetto Corsa and Forza adapters: no button
   fields in their protocols).

### Windows speech recognition

| Option | Licence | Install on Windows | Model / quality (measured, synthetic) | Verdict |
|---|---|---|---|---|
| **sherpa-onnx 1.13.8** (2026-09-10) | Apache-2.0 | `sherpa-onnx` + `sherpa-onnx-core` only; win_amd64 core 16.9 MB, win_arm64, win32; cp312/cp313; ONNX Runtime bundled | Parakeet TDT 0.6B **v2 int8**, the Mac's model family. See A4 below | **Chosen** |
| sherpa-onnx + v3 int8 (multilingual) | same | same | "Pitwall" recall 0.53; often heard as "Pall" or "Well" | Rejected |
| onnx-asr 0.12.0 | MIT | needs onnxruntime and numpy; excludes several onnxruntime versions | same Parakeet ONNX models | Viable fallback, not chosen |
| faster-whisper 1.2.1 | MIT | ctranslate2, tokenizers, onnxruntime, av, huggingface-hub | Whisper hallucinates on near-silence, a risk for always-on listening | Rejected |
| whisper.cpp sidecar | MIT | manual | already supported (`voice/stt.py` `WhisperCppStt`) | Kept as an option |

**Model pins** (`voice/stt_sherpa.py` `CATALOGUE`): Hugging Face `csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8`,
revision `1ab9323565ddb038682214b292f588070a538ce2`:

| File | Bytes | sha256 |
|---|---|---|
| `encoder.int8.onnx` | 652184296 | `a32b12d17bbbc309d0686fbbcc2987b5e9b8333a7da83fa6b089f0a2acd651ab` |
| `decoder.int8.onnx` | 7257753 | `b6bb64963457237b900e496ee9994b59294526439fbcc1fecf705b31a15c6b4e` |
| `joiner.int8.onnx` | 1739080 | `7946164367946e7f9f29a122407c3252b680dbae9a51343eb2488d057c3c43d2` |
| `tokens.txt` | 9384 | `ec182b70dd42113aff6c5372c75cac58c952443eb22322f57bbd7f53977d497d` |

Licence: NVIDIA `parakeet-tdt-0.6b-v2`, CC-BY-4.0 (the conversion's card says cc-by-4.0 too). API used:
`sherpa_onnx.OfflineRecognizer.from_transducer(encoder, decoder, joiner, tokens, num_threads=..., decoding_method=
"greedy_search", model_type="nemo_transducer", provider="cpu")`, then `create_stream()`, `accept_waveform(16000,
float32)`, `decode_stream(s)`, `s.result.text`.

**Packaging note.** uv locks `sherpa-onnx` from its `linux_armv7l` wheel, whose metadata omits the
`sherpa-onnx-core` dependency every other wheel declares; the `voice` extra therefore lists `sherpa-onnx-core` too
(both `sys_platform == 'win32'`), and the lock gains exactly those two packages. The core wheel declares Apache-2.0
but ships no licence file, and bundles ONNX Runtime (MIT) without its notice ([licences.md](../licences.md)).

## 3. Data checks

### 3.1 Recorded: the stationary gate on real captures (A1)

The 12 owner captures (8 F1 25 races, 4 GT7) decoded with the real adapters and run through the shipped
`MotionGate` as the hub sees them (`scripts/handsfree_check.py --captures`, scratch copies, deleted afterwards): a
packet gap over `LIVE_S` (2 s) makes the data stale 2 s after the last packet, and a car that was moving stays
moving for `STALE_STILL_AFTER_S` (5 s) more before it counts as stationary (review round 2, section 3.6).

| Capture | Game / session | Min | Stationary share | Windows (>=5 s / >=15 s) | Flips | Longest still (s) | Stops after driving (min: s) |
|---|---|---|---|---|---|---|---|
| 20261010-191501 | F1 25 race | 4.4 | 3.2% | 2 (1/0) | 2 | 8.4 | none (the grid at the start) |
| 20261010-203637 | F1 25 race | 5.4 | 0.0% | 1 (0/0) | 1 | 0.0 | none: 3 incident gaps stay moving |
| 20261010-215916 | F1 25 race | 4.2 | 5.2% | 2 (1/0) | 2 | 13.1 | none (the grid at the start) |
| 20261010-221749 | F1 25 race | 28.6 | 13.6% | 4 (2/1) | 7 | 215.4 | 4.4: 14.0, 12.6: 215.4, 20.2: 4.4 |
| 20261010-225601 | F1 25 qualifying + race | 12.0 | 19.1% | 3 (3/2) | 5 | 95.6 | 1.1: 30.5, 1.8: 95.6, 11.8: 11.2 |
| 20261011-010607 | F1 25 race | 5.3 | 5.5% | 3 (2/0) | 4 | 8.9 | 0.7: 8.9 |
| 20261011-183245 | F1 25 race | 8.4 | 0.0% | 0 | 0 | 0.0 | none: 2 incident gaps stay moving |
| 20261011-185757 | F1 25 race (pit stop) | 5.6 | 19.0% | 6 (4/2) | 12 | 27.5 | 1.3: 9.4, 2.0: 8.7, 2.7: 2.9, 2.8: 0.8, 4.1: 27.5, 4.9: 15.0 |
| 20261011-013533 | GT7 | 1.8 | 4.1% | 1 (0/0) | 1 | 4.3 | none |
| 20261011-124608 | GT7 | 16.6 | 28.4% | 3 (2/1) | 6 | 274.6 | 0.4: 1.9, 4.3: 274.6, 13.0: 5.7 |
| 20261011-182615 | GT7 | 3.1 | 2.9% | 1 (1/0) | 1 | 5.4 | none |
| 20261011-121256 | GT7 | 0 player frames decoded (not investigated) | | | | | |

- **What changed in round 2.** The first table counted a packet gap as stationary from its last frame. On the real
  races those gaps are mostly incidents (a spin or a flashback: 3-28 km/h, then 3.0-3.7 s without data, then 92 or
  95 km/h within 5 s): the stationary scope opened mid-race and the "paused while driving" hint was said as the car
  drove on. With the 5 s hold, 203637 and 183245 have no stop at all after driving (5 incident gaps stay moving;
  round 1 had them 3.9 % and 1.7 % stationary), and the windows that end in a menu or the stream's end start 7 s
  later (010607: 8.9 s instead of 15.9 s; 124608 and 185757: 7 s shorter).
- **The hint's stops.** The hint now waits for a stop of at least `HINT_SETTLE_S` (8 s): the short ones above (1.9 s
  in 124608, 2.9 s and 0.8 s in 185757, 4.4 s in 221749) are never used.
- **No frame above 8 km/h is classed stationary** in any capture, except frames the game itself flags paused or
  replay (counted apart: 1-2 per F1 race, 2544 in the qualifying + race capture, 260-341 per GT7 capture).
- **When the stationary scope listens:** on the grid, in the pits, in the garage and menus (after the hold) and after
  the flag; with no game data at all (any game, telemetry not set up). In a race the car is still for 0-28 % of the
  time.
- **Why the hysteresis matters.** A single 8 km/h threshold flipped up to 22 times in 5.6 minutes; the hysteresis
  rule flips 0-12 times per capture.
- `--moving-start` (the design scan's start: moving before the first frame) gives the three races that begin on the
  grid one flip more and a first window 1.5 s shorter; the table uses the shipped start (a stopped car is stationary
  at once, as Drive's `motion.ts`).

### 3.2 Recorded: real button presses through the hub (A2)

- **Committed excerpts** (`tests/recorded/test_handsfree_recorded.py`): the Melbourne and Austria excerpts carry real
  `BUTN` events but no UDP Action press (Right Stick Up/Down only). Replayed through `LiveState` into the hub with
  hands-free armed: with the default UDP Action 1 mask nothing keys the mic; pointed at the Right Stick bits as a
  stand-in, every recorded press keys push-to-talk and every release ends it, and every press cut the hands-free
  capture in progress.
- **The owner's full races** (scratch copies, deleted): 38 real UDP Action 1 presses in 7 of the 8 F1 25 races
  (5, 10, 1, 13, 1, 1, 7, 0). Replayed the same way with the default mask and hands-free armed: 38 push-to-talk downs
  and 38 releases, each cutting the capture in progress. GT7: no button events, as expected.

### 3.3 Synthetic: the wake word through the real speech engines (A3, A4, A5)

119 clips: 7 `say` voices (Daniel, Samantha, Fred, Ralph, Kathy, Junior, Albert) x 17 phrases (7 "Pitwall", 4
"Radio", 6 negatives, `scripts/handsfree_check.py` `PROBE`), each with 0.5 s of lead-in (the pre-roll). Scored with
the shipped `match_wake` (`--wake`).

| Engine | Condition | "Pitwall" recall | "Radio" recall | False accepts | Median decode |
|---|---|---|---|---|---|
| Parakeet MLX v3 (Mac GPU) | clean | 44/49 | 26/28 | 0/70 and 0/91 | 44 ms |
| Parakeet MLX v3 | engine drone, 10 dB SNR | 45/49 | 26/28 | 0/70 and 0/91 | 44 ms |
| Parakeet MLX v3 | pink noise, 15 dB SNR | 35/49 | 24/28 | 0/70 and 0/91 | 46 ms |
| sherpa v2 int8 (Mac CPU, 2 threads, the shipped `SherpaParakeetStt`) | clean | 43/49 | 27/28 | 0/70 and 0/91 | 95 ms |
| sherpa v2 int8 | engine drone, 10 dB SNR | 39/49 | 26/28 | 0/70 and 0/91 | 103 ms |
| sherpa v3 int8 (design probe) | clean | 26/49 | 23/28 | 0 | |

- A3 (Parakeet: >= 0.85 clean and with the drone, "Radio" >= 0.85, no false accept): passed (0.90 / 0.92 / 0.93).
- A4 (sherpa v2: >= 0.80, no false accept, median <= 150 ms with 2 threads): passed (0.88, 95 ms). The sherpa engine
  loaded and hash-checked its offline folder in 1.8 s; max RSS 2.09 GB. With the engine drone it falls to 0.80.
- **How "Pitwall" gets written:** "Pitwall", "Pit wall", "Pitwal", "Pittwall", "Pitball", "Pitbull", "Pit well",
  "Pigwall", "Bidwall", "Big wall", "Bit wall", "Tidwall", "Pidwall", "Hitwall", "It wall", "Fit wall", "Pitfall",
  "Pitmull" - all accepted. Misses: "It all...", "Fedwall", "Two". "Pitfall" or "pit wall" in the middle of a sentence
  is never accepted: the match must be at the start.
- **Round 2 (review findings 2 and 8, UX H3).** A match is now graded. Within one edit of "pitwall" (on one word or two
  joined) it takes any question; two edits ("Big wall", "Bidwall", "Pitbull", "Paywall", "Pinball"), "It all," with
  punctuation after it, or one edit from "radio" ("Ratio") only a racing question (an engineer intent other than
  "general") or nothing at all. Two words count as "pit wall" only when the second sounds like "wall" (wall, well,
  ball, bull, fall, mall, mull), so "Hit all the apexes", "Fit all four tyres" are not the wake word. "a" and "k" (a
  clipped onset: "A pit wall", "K pit wall") are fillers before "Pitwall", "k" is a first letter, and with less than
  0.25 s of pre-roll "Wall" / "Well" / "Twell" count before a racing question. Fillers after the wake word are not the
  question ("Pitwall, um." is the wake word alone; "right" stays when more follows: "right front tyre?"). Scored on
  the same transcripts (scratch, `wake_eval.py`), shipped -> round 2:

  | Transcripts | "Pitwall" recall | "Radio" recall | False accepts |
  |---|---|---|---|
  | Parakeet clean / drone 10 dB / pink 15 dB | 44 -> 45 / 45 -> 45 / 35 -> 34 of 49 | unchanged | 0 -> 0 |
  | sherpa v2 clean / drone 10 dB | 43 -> 43 / 41 -> 40 of 49 | unchanged | 0 -> 0 |
  | Onset probe (80-250 ms of the onset removed, 48 positives) | 22 -> 30, 45 with the clipped rule | | |
  | 34 negatives, including every false accept the review found | | | 0 of 34 (both words, clipped or not) |

  The two lost: "Hey big wall! Where should I be?" and "Tidwall, how are my timers?" (garbled questions after a
  two-edit match). One extra gain: "A bit wall! Where should I bid?". "He pitwall wins a ditch." is no longer
  accepted. "Pit wall says box" is still the wake word (strong, at the start); "Hey, radio" is the wake word alone
  by design (the driver calls the radio by name).
- **A5 (text):** the 204-question engineer intents fixture gives 0 "Pitwall" accepts; "Radio" matches only "Radio
  check", which keeps its whole text as the question (`tests/unit/test_handsfree.py`).
- **Engineer lines** that begin with "Pitwall" (game capability answers) and the test phrase "Radio check, loud and
  clear" are why the echo guard exists; the loop is blocked in `tests/unit/test_hub_handsfree.py`.
- One refinement over the design: "pitwall" is tried on the next two words joined and on the next word alone, and the
  closer one wins (the two-word span on a tie), so "Pitwall, OK?" keeps "OK" as the question instead of hearing
  "pitwallok". Recall and false accepts are unchanged by it (it only moves the end of the matched span).

### 3.4 Synthetic: the browser VAD rules (A6)

The section 4.2 rules (energy per 32 ms frame, 1 s calibration, threshold floor + 12 dB and at least -50 dBFS, start
on 4 voiced of 5, end after 22 silent, cap at 250, floor tracking) run on the same clips with 3 s of pink noise in
front (`--rms`; the clips' speech is about -20 dBFS active):

| Condition | Single segment | Split | Missed | False segments |
|---|---|---|---|---|
| Quiet room (as rendered and 20 dB quieter) | 237/238 | 1 | 0 | 0 |
| 30 dB SNR | 119/119 | 0 | 0 | 0 |
| 20 dB SNR | 117/119 | 2 | 0 | 0 |
| 10 dB SNR | 109/119 | 7 | 3 | 0 |
| 0 dB SNR | 0/119 (refuses by design) | 0 | 119 | 0 |

The traces are committed as `tests/fixtures/handsfree/vad_rms.json.gz` (714 traces, one RMS value per frame, with this
table as `expected`); `tests/unit/test_handsfree.py` checks the Python reference reproduces it, and
`web-react/src/lib/handsfree.backend.test.ts` checks the shipped TypeScript `EnergyVad` reproduces it exactly. Median
onset lag 0-224 ms, which the 0.5 s pre-roll covers.

**Two rules added in the dashboard** (`web-react/src/lib/handsfree.ts`). The traces above play the voice 20 dB under
its rendered level (noise -40 dBFS at 0 dB SNR). The dashboard's own traces keep the voice at its rendered level
(about -19 dBFS active), so 0 dB SNR means noise at about -19 dBFS, far above the -35 dBFS floor clamp. There the
section 4.2 rules alone captured 118 of 119 clips at 0 dB SNR - mostly noise from
the 3 s lead-in, in back-to-back 8 s segments - and gave 1 false segment at 10 dB. So a voiced frame must also be
10 dB above the noise estimate itself (not clamped), and above -26 dBFS of noise the device stops listening (the chip
says "Hands-free · too noisy"): there speech cannot be told from noise by its energy. Both rules only matter in noise
louder than about -33 dBFS, so they change nothing on the backend's traces above. On the dashboard's traces (all
synthetic, `say` voices plus pink noise; a committed subset in
`web-react/src/test/fixtures/handsfree/vad-traces.synthetic.json`):

| Condition | Single segment | Split | Missed | False segments |
|---|---|---|---|---|
| Quiet room | 237/238 | 1 | 0 | 0 |
| 30 dB SNR | 119/119 | 0 | 0 | 0 |
| 20 dB SNR | 117/119 | 2 | 0 | 0 |
| 10 dB SNR | 115/119 | 4 | 0 | 0 |
| 0 dB SNR | 0 segments | | | 0 |

Median time from speech start to the confirmed start: 96-320 ms, inside the 0.5 s pre-roll; in 10 dB noise 12 clips
start more than 0.5 s late because the first word is buried in the noise.

### 3.5 End to end on an isolated server (integration)

A scratch server (its own data folder and ports, LLM off, text-only radio, Parakeet on) with one emulated browser on
`/ws/radio`: real-time 16 kHz microphone frames carrying the macOS `say` clips, `vad` frames sent after the audio they
confirm (start about 250 ms after the speech onset), device TTS that reports playback. Then a real F1 25 race excerpt
(about 3 minutes, a scratch copy, deleted) streamed over loopback UDP with `pitwall send`. 31 of 31 checks passed:

- off by default; the device arms with `settings`; an unknown wake word gets an `error` frame;
- stationary (no telemetry): "Pitwall, how are my tyres?" addressed, the `transcript` frame carries only the question
  ("how are my tires?", `source: handsfree`) and the radio answers; "What's for dinner tonight?" ignored as
  `not_addressed` with no transcript, no reply and no text in any frame or log line; "Pitwall." alone gets "Go ahead."
  and the next sentence is answered without the wake word; "Radio, how much fuel have I got?" with the "Radio" wake
  word; a remote-button push-to-talk cuts a capture in progress (`ptt`) and reports `ptt_source: remote`;
- while the race streams: `paused: moving` once the car moves; a start then is refused (`paused_moving`); the seated
  driver's profile switched to "Hands-free while driving" (`PATCH /api/drivers/1`) turns the scope to `driving`, and a
  question while moving gets the deterministic tyre answer (no language model); back off, the scope returns to
  `stationary`; the race's UDP Action 1 press keys push-to-talk with hands-free armed; the "paused while driving" hint
  is said once (round 1 said it at the first stationary moment; since round 2 it waits for a stop of 8 s, see 3.6);
- `/api/voice/status`: `clients[].handsfree`, and `handsfree_diag` with reasons and counts but no text.

### 3.6 Review round 2 (correctness and radio-feel reviews)

Every finding was reproduced or checked, then fixed with a unit test in `tests/unit/test_hub_handsfree.py` /
`test_handsfree.py` (hub probes, synthetic) and, for motion, the recorded scan in 3.1.

- **The hint** (finding 1, UX M1): said only at a stop of at least 8 s, with the radio quiet for 3 s and nothing held,
  re-checked after synthesis (the car may have moved off), never in quiet mode or at minimal intensity, and sent as an
  `info` message a braking call may cut (not a control message that blocks braking calls); new words: "Hands-free only
  listens when you stop. Your driver profile can turn it on for driving." (+ the wheel or talk button when one was
  used), simple: "I can't hear you while you drive. Ask me when you stop." Not said on a quiet stretch of track: a
  refusal while moving is often engine noise, and the Drive chip already says "paused · driving".
- **Incident gaps** (findings 1, 5, 9): the 5 s stale hold (3.1); a capture still running when the car moves off is
  dropped (`paused_moving`); the copy says the stationary scope also listens when no game data arrives.
- **"Pitwall, um."** (finding 2) is the wake word alone; **the echo guard** (finding 3) compares a transcript that
  starts with the wake word only with lines that start with it.
- **Holding the radio** (finding 4): a capture, a segment in the speech engine, the wake word alone waiting for its
  question, and "Say again?" waiting all hold non-urgent messages; "Go ahead." waits for what is on air (it cut a lap
  summary that was then lost) and, on track, for a speak window (finding 7), else the window opens silently after 2 s.
  A capture started while "Go ahead." is still pending takes the follow-up and "Go ahead." is not said.
- **A question cut by a braking call** (UX H1): with at least 0.8 s of speech it is still transcribed; if it was
  addressed, "Say again?" once the radio is free (on track in a speak window); chatter is dropped as before.
- **After "Go ahead."** (UX H2) only a racing question (intent other than "general") is taken without the wake word.
- **Before any session** (UX H4) a radio check, "stop talking" and "you can talk" are answered (an empty fact sheet;
  "quiet for 3 laps" still needs a lap to count from).
- **Windows' first run** (UX H5): while the speech model downloads or loads, `handsfree.reason` is
  `starting: downloading the speech model (NN %)`, the chip shows it, a failed load is retried every 30 s while a
  device listens, and push-to-talk says "Speech recognition is still starting. Type it, or try again in a minute."
- **The browser** (finding 6) aborts an open segment (`reason: mic`) when its microphone track ends or is reopened.
- **The speech gate** (finding 10) is -50 dBFS like the browser's and push-to-talk's; each segment's loudest 20 ms
  and voiced seconds are in `handsfree_diag.events`. Unverified until a real voice is recorded (A9).
- **Copy** (UX L1, M2): "the computer", not "Mac", in hands-free text; the talk-button help names the device; the
  keyboard-only advice is in the Bluetooth button's hint; Drive › Radio has "Also while driving (name)" for the seated
  driver.
- **Not done here** (other lanes): shorter answers while moving (UX M3: engineer phrasing), "Copy, checking." with the
  language model switched off, number rounding and "k p h" / brackets in speech (UX L2), "Say again?" for a wheel
  press with no speech in menus (push-to-talk behaviour).

### 3.7 Owed

- **A7 (CI, Windows):** the `windows` job runs `uv sync --all-extras --locked` (as the one-line installer does), so it
  installs sherpa-onnx and its core from the lock; its pytest runs the Windows-only import test in
  `tests/unit/test_stt_sherpa.py`, and its doctor step fails unless `voice_stt` is ok and names sherpa-onnx and a
  `voice_handsfree` check exists. The model itself (661 MB) is never downloaded in CI: no test connects a radio with the
  real engine.
- **A8 (CI, macOS):** no sherpa installed, `build_stt` still returns `ParakeetStt`, `make check` green.
- **A9 (a real voice):** the owner reads `SCRIPT` (24 lines, `scripts/handsfree_check.py`) on the rig with the iPad
  and one AirPod, one `NN.wav` per line starting with at least 1 s of the room's noise, into `data/handsfree-samples/`
  (never committed); `scripts/handsfree_check.py --audio data/handsfree-samples` reports recall, false accepts and
  VAD splits.
- **A10 (live):** the planned validation item `radio_handsfree`.

## 4. Risks

- Real AirPod levels are unknown: iOS voice processing and Bluetooth HFP at 16 kHz may change the noise floor and the
  SNR. The thresholds are heuristics with a diagnostic view; A9 is needed.
- The `say` voices clip the "P" of "Pitwall", so recall with real voices may differ either way.
- The Windows engine has never run on a Windows PC: expect 2-4x the Mac's CPU figures.
- Hands-free while driving: a braking call cuts a capture ("Say again?" if it was addressed), and a capture or the
  wake word alone waiting for its question holds back non-urgent radio messages (at most about 10 s).
- Gamepad buttons in Safari are unverified.

## Sources

- https://developer.apple.com/videos/play/wwdc2023/10233
- https://developer.mozilla.org/en-US/docs/Web/API/MediaSessionAction
- https://bugs.webkit.org/show_bug.cgi?id=301563
- https://bugs.webkit.org/show_bug.cgi?id=205448
- https://www.airturn.com/blogs/support/faq
- https://samueleddy.com/writing/ios-safari-audio-sessions/
- https://pypi.org/project/sherpa-onnx/1.13.8/
- https://pypi.org/project/onnx-asr/
- https://pypi.org/project/faster-whisper/
- https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-transducer/nemo-transducer-models.html
- https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8

Crew Chief (MIT) was read only for the gap analysis of what drivers expect; nothing of its code, audio or text is used.
