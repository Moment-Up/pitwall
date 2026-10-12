# Radio protocol (`/ws/radio`)

The driver's device (iPad/iPhone Safari, one AirPod) is the microphone and speaker. It connects to
`wss://<mac>.<tailnet>.ts.net:8443/ws/radio` (HTTPS is required for `getUserMedia`; Tailscale Serve
provides it). Auth is the same as `/ws/live` (Tailscale identity, local, or token).

One WebSocket carries both JSON text frames and binary audio frames. Order is significant.

## Client -> server

| Frame | Meaning |
|---|---|
| binary | Microphone audio: int16 little-endian mono PCM at **16 000 Hz**, any length (client sends 512-sample = 1024-byte frames, ~32 ms). Sent continuously while the radio is live; the server decides what to keep. |
| `{"type":"hello","client":"ipad","sample_rate":16000,"version":1}` | First message after connect. |
| `{"type":"ptt","down":true}` / `{"type":"ptt","down":false}` | On-screen push-to-talk pressed / released. Optional `"source":"remote"`: a Bluetooth key or game controller button the device learned (any other value, or none, is `"screen"`). |
| `{"type":"vad","state":"start","seq":7}` / `{"type":"vad","state":"end","seq":7,"reason":"silence"\|"max"}` / `{"type":"vad","state":"abort","seq":7,"reason":"suppressed"\|"mic"}` | Hands-free only (see below): the device's voice detector heard speech start, end (after silence, or at its 8 s cap), or gave the segment up (it started playing, the button was pressed..., or `mic`: its microphone track ended or was reopened). `seq` is an integer the device increments per segment. Sent **after** the binary frame that triggered it, so the server already holds that audio. |
| `{"type":"playback","id":"m12","state":"started"\|"ended"}` | The device actually started/finished playing message `m12`. Used for the half-duplex gate and latency measurement. |
| `{"type":"stop_tts"}` | Barge-in: stop speaking now. |
| `{"type":"ask","text":"how are my tyres"}` | Typed question (same pipeline minus STT). |
| `{"type":"test_voice","text":"optional, max 200 chars"}` | Radio page "Test voice": the server voice says the text (default: a radio check) on every connected radio, as an `info` message. |
| `{"type":"settings","voice_enabled":true,"intensity":"quiet"\|"normal"\|"detailed","tts_mode":"device"\|"server","cue_mode":"off"\|"focus"\|"markers"\|"all","tts_voice":"bm_george","handsfree":false,"wake_word":"pitwall"\|"radio"}` | Radio preferences; every field optional. `handsfree` and `wake_word` are per device, like `tts_mode` (hands-free is off until the device sends `true`); any other `wake_word`, or a `handsfree` that is not a boolean, gets an `error` frame and changes neither. `tts_mode`: who speaks on *this* device (its own Web Speech voice, or the Mac's PCM). `cue_mode` and `tts_voice` are server-wide: `tts_voice` switches the Mac's voice for every following message (Kokoro voices `bm_fable`, `bm_george`, `bf_emma`, `bf_isabella`; remembered across restarts in `data/radio_voice.json`). An unknown voice, or an engine without voices (`say`), is answered with an `error` frame and changes nothing. |
| `{"type":"ping","t":12345.6}` | Client clock in ms (performance.now()). |

## Server -> client

| Frame | Meaning |
|---|---|
| `{"type":"state", "ptt":bool, "listening":bool, "speaking":bool, "quiet":{"until_lap":int\|null,"indefinite":bool}, "intensity":str, "stt":str, "stt_reason":str\|null, "tts":str, "tts_voice":str\|null, "tts_voices":[str], "tts_active":str, "tts_ready":bool, "tts_neural":bool, "tts_status":str\|null, "telemetry":"live"\|"stale"\|"no_data", "ptt_source":"screen"\|"wheel"\|"remote"\|null, "cue_mode":str, "handsfree":{...}}` | Sent on connect and on every change, including when the voice engine comes up, goes down or changes voice. `stt` is the speech recognition engine (`parakeet`; `sherpa` = Parakeet on the CPU via sherpa-onnx, the Windows engine; `whispercpp`; `none`); `stt_reason` says why there is none (null when there is one). `tts` is the configured engine (`kokoro`, `say`, `sapi` on Windows, `none`); `tts_active` is what renders messages right now (`kokoro`, or `say` while the Kokoro worker starts/restarts or is not installed); `tts_status` is the worker's state (`starting`, `ready`, `restarting`, `unavailable`, `stopped`; null for `say`); `tts_voices` lists the selectable server voices (empty for `say`). `listening` is true while push-to-talk is down **or** a hands-free capture is running. `handsfree`: `{"available":bool, "reason":str\|null, "armed":int, "scope":"stationary"\|"driving", "active":bool, "paused":"moving"\|null, "capturing":bool, "follow_up":bool, "wake_words":["pitwall","radio"], "counts":{"heard":int,"addressed":int,"ignored":int,"rejected":int}}` - `armed` is how many devices turned hands-free on; `scope` is the seated driver's (`driving` only when their profile allows "Hands-free while driving"); `active` = available, armed and (scope `driving` or the car stationary); `paused` is `"moving"` while armed devices wait for the car to stop; `follow_up` while the next segment needs no wake word. `reason` starting with `starting:` (`"starting: downloading the speech model (42 %)"`, `"starting: loading the speech model"`) means the speech engine is still getting its model ready (Windows' first run): not available yet, and the device shows it as starting, not as a fault. |
| `{"type":"transcript","text":"...","stt_ms":int,"audio_s":float}` | What the server heard (after PTT release). Empty text = nothing understood. A hands-free question adds `"source":"handsfree","wake":"pitwall"\|"radio"`, its `text` is the question after the wake word, and it is sent **only** when the speech was addressed to the radio. |
| `{"type":"handsfree","event":"accepted"\|"rejected"\|"ignored"\|"addressed"\|"follow_up","seq":7,"reason":"...","audio_s":1.9,"wake":"pitwall"}` | To the device that sent the segment only. `reason` (rejected / ignored): `not_armed`, `unavailable`, `ptt`, `other_device`, `speaking`, `busy`, `paused_moving`, `rate_limited` (a `start` refused, checked in that order), `too_short`, `too_long`, `no_speech`, `stt_error`, `answer_limit` (a segment dropped), `echo`, `not_addressed` (transcribed and thrown away; never shown, stored or logged). `addressed` carries `wake`; `follow_up` means the next segment of this device needs no wake word. `audio_s` and `reason` are present only when they apply. |
| `{"type":"say","id":"m12","kind":"answer"\|"control"\|"cue"\|"alert"\|"lap_summary"\|"coaching"\|"strategy"\|"goal"\|"validation"\|"info","text":"display text","speech":"spoken text","sample_rate":24000,"n_bytes":int,"meta":{...}}` | A message follows. Immediately followed by one or more **binary** frames of int16 LE mono PCM at `sample_rate` totalling `n_bytes`, then `say_end`. If TTS is unavailable `n_bytes` is 0 (display only). A client speaks every `say` frame whatever its `kind`; a kind it does not know (a newer server) is only labelled `INFO`. **`sample_rate` is per message and must be honoured**: 24 000 Hz with Kokoro (and with its `say` fallback, rendered at 24 kHz so cue parts from both engines join), 22 050 Hz with the plain `say` engine. Kokoro audio arrives trimmed to ~40 ms of silence at each end, at about -17 dBFS speech RMS with peaks at most -3 dBFS. |
| `{"type":"say_end","id":"m12"}` | End of audio for `m12`. |
| `{"type":"cancel","id":"m12"}` | Stop playing `m12` (barge-in or superseded). |
| `{"type":"pong","t":12345.6,"server_ms":int}` | Echo for round-trip measurement. |
| `{"type":"error","message":"..."}` | Non-fatal error to show. On Windows without server speech recognition (`stt` `none`: sherpa-onnx not installed, or switched off), a push-to-talk utterance is answered with an error naming `stt_reason` and a spoken "No voice questions on this server. Type your question instead." instead of a transcript and "Say again?" (macOS keeps the transcript + "Say again?"). |

## Behaviour

- **Push-to-talk** sources: on-screen button, or a wheel button mapped in F1 25 to a *UDP Action* (default
  UDP Action 1), received through the game's `BUTN` telemetry event. PTT down starts an utterance; release
  ends it (max 12 s). Audio while PTT is up is discarded (not stored, not transcribed).
- **Half-duplex gate**: while the device is playing a message (+300 ms tail) mic audio is discarded, so the
  engineer never answers itself. PTT down during playback = barge-in: server sends `cancel` and listens.
- **Mic stays open** for the whole session on the device (opening/closing it per PTT breaks AirPods routing
  on iOS); gating happens on the server.
- **Proactive messages** (lap summary, coaching, goal lines, strategy calls, alerts, validation prompts) go through one
  policy (`voice/scheduler.py`). They are queued by priority, then kind, and only spoken in a *speak window* (not
  braking, not cornering, enough time before the next braking zone); they respect quiet mode ("stop talking for 3
  laps") and coaching intensity, and expire when no longer actionable.
  - **Intensity:** `quiet` says answers, acknowledgements, alerts, cues and validation prompts; `normal` adds the lap
    summary, goal lines, coaching and `strategy` calls; `detailed` adds `info`.
  - **Order within a priority:** in a race lap the lap time, then the strategy call, then the goal line, then the
    coaching point; validation prompts last.
  - **Talk budget:** while the car is on track, at most 2 (`normal`) or 4 (`detailed`) messages of the kinds
    `lap_summary`, `goal`, `strategy`, `coaching` and `info` per lap. One that does not fit waits for the next lap
    (until it expires). Off track there is no budget. Alerts, urgent calls, cues, answers, acknowledgements and
    validation prompts never count; the safety-car box-or-stay call and critical fuel also bypass quiet mode.
  - **Seat change:** when another driver takes the seat, unsaid `lap_summary`, `goal` and `coaching` messages about
    the previous driver's laps are dropped; alerts and strategy calls (about the car) stay.
- **Goal lines** (kind **`goal`**, `pitwall/motivation`): one short line when the driver reaches a goal, at most two a
  session, never with a lap time. `meta.topic` is `goal:<session id>`.
- **Validation prompts** (kind **`validation`**, rig validation kit): spoken only while the driver runs a validation
  with radio prompts on, at every intensity, at least 30 s apart and never within 2 s of another message.
  `meta.topic` is `validation`.
- **Answers while moving:** while the car is on track at 8 km/h or more, every answer is deterministic (no LLM and no
  "Copy, checking."); the LLM explains only when the car is stationary, and in Review › Ask.
- **Strategy calls** (race strategy engineer, `pitwall/strategy`): an `alert` level call is sent as kind `alert`
  (every intensity), a `normal` one as kind **`strategy`** (normal and detailed intensity), a `detailed` one as kind
  `info` (detailed only). Their `meta` carries `topic` (`strategy:<topic>`, e.g. `strategy:sc_box`; a newer call on
  the same topic replaces an unsaid one), `strategy_call` (the call id), `level` and `audience`. Calls for experienced
  drivers are not sent to a driver whose profile asks for simple wording, who hears each call's plain words instead
  (the call's `text_simple`: "Pit this lap or next: your tyres are nearly worn out."). Max-speed replays make no
  calls.
- **Hands-free** (lane handsfree, `voice/handsfree.py`; evidence in [research/handsfree.md](research/handsfree.md)): a
  device that sends `"handsfree":true` runs an energy voice detector on its own microphone level and sends `vad`
  frames; the server keeps that device's last 0.5 s of audio (only while it may listen: not during push-to-talk,
  while the radio speaks or in its 300 ms tail, nor while hands-free is paused), captures from `start` to `end` (9 s
  watchdog), and transcribes one segment at a time (at most 2 waiting). It answers only when the transcript starts
  with the device's wake word ("Pitwall", heard as "Pit wall", "Big wall", "Pitbull"...; or "Radio"), after up to two
  fillers ("hey", "ok", "um"...). A close match ("Pitwall", "Pit wall", "Pigwall", within one edit) takes any
  question; a looser one ("Big wall", "Pitbull", "Paywall": two edits; "It all," with punctuation after it; "Ratio")
  only a racing question (an engineer intent other than general) or nothing at all; with little pre-roll (the first
  sound clipped) "Wall" / "Well" count before a racing question. Two words count as "pit wall" only when the second
  sounds like "wall" ("hit all" does not). The question is the text after it, without leading fillers; "Radio check"
  keeps its whole text. Everything else is dropped at once. The wake word alone, or with fillers only ("Pitwall,
  um."): after 1.2 s without a question the radio says "Go ahead." (at most one every 20 s, never over something on
  air, on track only in a speak window; with no moment for it within 2 s the device just gets the follow-up) and the
  device's next segment within 6 s of it ending needs no wake word (once) - but only a question about the car or the
  race (not an engineer intent of "general") is taken that way. The radio's own words coming back through the mic (a
  transcript that matches something said in the last 10 s) are dropped; a transcript that starts with the wake word
  is only compared with lines that start with it too ("Pitwall, box this lap?" after "Box this lap." is a question).
  Budgets: 12 transcriptions and 6 answers a minute; speech-engine errors reach the device at most once a minute.
  Answers follow the usual rules: deterministic while moving, the LLM only stationary. A radio check, "stop talking"
  and "you can talk" are answered before any session.
  - **Scope:** only while the car is stationary (no game data at all, paused or replay, data that stopped arriving -
    after 5 s more when the car was moving, as an incident gap is not a stop -, or under 3 km/h for 1.5 s - at once in
    the pits - until over 8 km/h; Drive's rule) unless the seated driver's profile has `handsfree_while_driving`. A
    capture still running when the car moves off is dropped (`rejected` / `paused_moving`). A `start` refused as
    `paused_moving` makes the radio say, once a session, at the next stop of at least 8 s with the radio quiet for 3 s
    and nothing held (re-checked after synthesis; never in quiet mode; an `info` message a braking call may cut),
    "Hands-free only listens when you stop. Your driver profile can turn it on for driving." (plus "On track, use
    your wheel button." / "...your talk button." when one was used this session; simple wording: "I can't hear you
    while you drive. Ask me when you stop.").
  - **Half-duplex:** anything going on air (a cue, an urgent call, an answer) ends a capture. One with at least 0.8 s
    of speech is still transcribed: if it was addressed, the device gets `rejected` / `speaking` and the radio says
    "Say again?" once it is free (on track in a speak window, within 6 s; it shares the "Go ahead." budget); anything
    else is dropped as `not_addressed`, a shorter one at once as `speaking`. Push-to-talk cuts a capture too (`ptt`).
    While a capture runs, a segment waits for or is in the speech engine, the wake word alone waits for its question,
    or "Say again?" waits, only urgent calls and braking calls go out; other proactive messages wait (at most about
    10 s).
  - `PITWALL_VOICE_HANDSFREE=false` refuses hands-free for every device (`available` false).
- Latency is measured per stage (PTT release -> transcript -> answer -> first audio sent -> playback started).
- **Validation commands** (rig validation kit, server side only, no protocol change): a question that fully matches
  "start validation" or, while a validation run is active, "next test", "worked", "didn't work", "what's the test" or
  "finish validation" is answered by fixed rules before the engineer, as a `control` message (`meta.intent` =
  `validation`). Anything else (and those words with no run active) reaches the engineer as before.
- **Server voice** (`voice/tts.py`): Kokoro-82M in a worker process, `say` as automatic fallback, so a message
  is never silent because the neural engine is starting or failed. Neural audio said ahead of time (cue parts,
  proactive messages) is checked by playing it through the STT: if a number or key word does not survive it is
  re-synthesised once, then sent in the fallback voice; a cue phrase is never split across two voices (if one
  part moved to the fallback voice, it says the whole phrase). Answers are checked after sending (logged only).
  `GET /api/voice/status` reports `tts_engine` (worker state, voice, synthesis p50/p95 ms, restarts, fallbacks,
  worker memory - `memory_mb.footprint_mb` now, `request_peak_mb` / `request_peak_max_mb` for the last and the
  largest recent synthesis -, `gpl_free`, words the G2P dropped) and `tts_check` (counts and the last mismatches;
  cue parts rendered before the STT was loaded are checked once it is).
- No streamed-PCM extension yet (tts-evaluation section 6.6): Kokoro renders a whole message in 0.08-0.22 s, so
  the buffered `say` + `n_bytes` path stays.

## REST (lane handsfree)

- `GET /api/voice/status`: the `state` frame's fields (including `handsfree`), plus per client `handsfree` (bool) and
  `wake_word`, and `handsfree_diag`: counters per reason, the last 20 hands-free events (event, reason, seq, client,
  audio length, and for transcribed or gated segments `level_dbfs` (the loudest 20 ms) and `voiced_s` (time over the
  -50 dBFS speech gate) - never any text), whether the car is stationary and for how long, whether hands-free holds
  the radio, the hint's state, the queue, the last minute's budgets and the server thresholds.
- `PATCH /api/drivers/{id}` with `{"handsfree_while_driving": bool}` (also accepted by `POST /api/drivers`); the
  driver's `preferences` and `summary()` return it. Default false; it sets the hands-free scope while that driver is
  in the seat.
