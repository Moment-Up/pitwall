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
| `{"type":"say","id":"m12","kind":"answer"\|"control"\|"cue"\|"alert"\|"lap_summary"\|"coaching"\|"info","text":"display text","speech":"spoken text","sample_rate":24000,"n_bytes":int,"meta":{...}}` | A message follows. Immediately followed by one or more **binary** frames of int16 LE mono PCM at `sample_rate` totalling `n_bytes`, then `say_end`. If TTS is unavailable `n_bytes` is 0 (display only). **`sample_rate` is per message and must be honoured**: 24 000 Hz with Kokoro (and with its `say` fallback, rendered at 24 kHz so cue parts from both engines join), 22 050 Hz with the plain `say` engine. Kokoro audio arrives trimmed to ~40 ms of silence at each end, at about -17 dBFS speech RMS with peaks at most -3 dBFS. |
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
- **Proactive messages** (lap summary, coaching, alerts) are queued by priority and only spoken in a
  *speak window* (not braking, not cornering, enough time before the next braking zone), respect quiet mode
  ("stop talking for 3 laps") and coaching intensity, and expire when no longer actionable.
- Latency is measured per stage (PTT release -> transcript -> answer -> first audio sent -> playback started).
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
