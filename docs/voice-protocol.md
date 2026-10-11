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
| `{"type":"ptt","down":true}` / `{"type":"ptt","down":false}` | On-screen push-to-talk pressed / released. |
| `{"type":"playback","id":"m12","state":"started"\|"ended"}` | The device actually started/finished playing message `m12`. Used for the half-duplex gate and latency measurement. |
| `{"type":"stop_tts"}` | Barge-in: stop speaking now. |
| `{"type":"ask","text":"how are my tyres"}` | Typed question (same pipeline minus STT). |
| `{"type":"test_voice","text":"optional, max 200 chars"}` | Radio page "Test voice": the server voice says the text (default: a radio check) on every connected radio, as an `info` message. |
| `{"type":"settings","voice_enabled":true,"intensity":"quiet"\|"normal"\|"detailed","tts_mode":"device"\|"server","cue_mode":"off"\|"focus"\|"markers"\|"all","tts_voice":"bm_george"}` | Radio preferences; every field optional. `tts_mode`: who speaks on *this* device (its own Web Speech voice, or the Mac's PCM). `cue_mode` and `tts_voice` are server-wide: `tts_voice` switches the Mac's voice for every following message (Kokoro voices `bm_fable`, `bm_george`, `bf_emma`, `bf_isabella`; remembered across restarts in `data/radio_voice.json`). An unknown voice, or an engine without voices (`say`), is answered with an `error` frame and changes nothing. |
| `{"type":"ping","t":12345.6}` | Client clock in ms (performance.now()). |

## Server -> client

| Frame | Meaning |
|---|---|
| `{"type":"state", "ptt":bool, "listening":bool, "speaking":bool, "quiet":{"until_lap":int\|null,"indefinite":bool}, "intensity":str, "stt":str, "stt_reason":str\|null, "tts":str, "tts_voice":str\|null, "tts_voices":[str], "tts_active":str, "tts_ready":bool, "tts_neural":bool, "tts_status":str\|null, "telemetry":"live"\|"stale"\|"no_data", "ptt_source":"screen"\|"wheel"\|null, "cue_mode":str}` | Sent on connect and on every change, including when the voice engine comes up, goes down or changes voice. `stt` is the speech recognition engine (`parakeet`, `whispercpp`, `none`); `stt_reason` says why there is none (null when there is one). `tts` is the configured engine (`kokoro`, `say`, `sapi` on Windows, `none`); `tts_active` is what renders messages right now (`kokoro`, or `say` while the Kokoro worker starts/restarts or is not installed); `tts_status` is the worker's state (`starting`, `ready`, `restarting`, `unavailable`, `stopped`; null for `say`); `tts_voices` lists the selectable server voices (empty for `say`). |
| `{"type":"transcript","text":"...","stt_ms":int,"audio_s":float}` | What the server heard (after PTT release). Empty text = nothing understood. |
| `{"type":"say","id":"m12","kind":"answer"\|"control"\|"cue"\|"alert"\|"lap_summary"\|"coaching"\|"strategy"\|"goal"\|"validation"\|"info","text":"display text","speech":"spoken text","sample_rate":24000,"n_bytes":int,"meta":{...}}` | A message follows. Immediately followed by one or more **binary** frames of int16 LE mono PCM at `sample_rate` totalling `n_bytes`, then `say_end`. If TTS is unavailable `n_bytes` is 0 (display only). A client speaks every `say` frame whatever its `kind`; a kind it does not know (a newer server) is only labelled `INFO`. **`sample_rate` is per message and must be honoured**: 24 000 Hz with Kokoro (and with its `say` fallback, rendered at 24 kHz so cue parts from both engines join), 22 050 Hz with the plain `say` engine. Kokoro audio arrives trimmed to ~40 ms of silence at each end, at about -17 dBFS speech RMS with peaks at most -3 dBFS. |
| `{"type":"say_end","id":"m12"}` | End of audio for `m12`. |
| `{"type":"cancel","id":"m12"}` | Stop playing `m12` (barge-in or superseded). |
| `{"type":"pong","t":12345.6,"server_ms":int}` | Echo for round-trip measurement. |
| `{"type":"error","message":"..."}` | Non-fatal error to show. On Windows without server speech recognition (`stt` `none`), a push-to-talk utterance is answered with an error naming `stt_reason` and a spoken "No voice questions on this server. Type your question instead." instead of a transcript and "Say again?" (macOS keeps the transcript + "Say again?"). |

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
