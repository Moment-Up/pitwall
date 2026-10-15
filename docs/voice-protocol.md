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
| `{"type":"state", "ptt":bool, "listening":bool, "speaking":bool, "quiet":{"until_lap":int\|null,"indefinite":bool}, "intensity":str, "stt":str, "stt_reason":str\|null, "tts":str, "tts_voice":str\|null, "tts_voices":[str], "tts_active":str, "tts_ready":bool, "tts_neural":bool, "tts_status":str\|null, "telemetry":"live"\|"stale"\|"no_data", "ptt_source":"screen"\|"wheel"\|"remote"\|null, "ptt_actions":[int], "ptt_label":str\|null, "wheel_ptt_paused":bool, "cue_mode":str, "handsfree":{...}, "spotter":{"enabled":bool,"audio_ready":bool,"voice":str\|null}}` | Sent on connect and on every change, including when the voice engine comes up, goes down or changes voice. `stt` is the speech recognition engine (`parakeet`; `sherpa` = Parakeet on the CPU via sherpa-onnx, the Windows engine; `whispercpp`; `none`); `stt_reason` says why there is none (null when there is one). `tts` is the configured engine (`kokoro`, `say`, `sapi` on Windows, `none`); `tts_active` is what renders messages right now (`kokoro`, or `say` while the Kokoro worker starts/restarts or is not installed); `tts_status` is the worker's state (`starting`, `ready`, `restarting`, `unavailable`, `stopped`; null for `say`); `tts_voices` lists the selectable server voices (empty for `say`). `listening` is true while push-to-talk is down **or** a hands-free capture is running. `handsfree`: `{"available":bool, "reason":str\|null, "armed":int, "scope":"stationary"\|"driving", "active":bool, "paused":"moving"\|null, "capturing":bool, "follow_up":bool, "wake_words":["pitwall","radio"], "counts":{"heard":int,"addressed":int,"ignored":int,"rejected":int}}` - `armed` is how many devices turned hands-free on; `scope` is the seated driver's (`driving` only when their profile allows "Hands-free while driving"); `active` = available, armed and (scope `driving` or the car stationary); `paused` is `"moving"` while armed devices wait for the car to stop; `follow_up` while the next segment needs no wake word. `reason` starting with `starting:` (`"starting: downloading the speech model (42 %)"`, `"starting: loading the speech model"`) means the speech engine is still getting its model ready (Windows' first run): not available yet, and the device shows it as starting, not as a fault. |
| `{"type":"transcript","text":"...","stt_ms":int,"audio_s":float}` | What the server heard (after PTT release). Empty text = nothing understood. A hands-free question adds `"source":"handsfree","wake":"pitwall"\|"radio"`, its `text` is the question after the wake word, and it is sent **only** when the speech was addressed to the radio. |
| `{"type":"handsfree","event":"accepted"\|"rejected"\|"ignored"\|"addressed"\|"follow_up","seq":7,"reason":"...","audio_s":1.9,"wake":"pitwall"}` | To the device that sent the segment only. `reason` (rejected / ignored): `not_armed`, `unavailable`, `ptt`, `other_device`, `speaking`, `busy`, `paused_moving`, `rate_limited` (a `start` refused, checked in that order), `too_short`, `too_long`, `no_speech`, `stt_error`, `answer_limit` (a segment dropped), `echo`, `not_addressed` (transcribed and thrown away; never shown, stored or logged). `addressed` carries `wake`; `follow_up` means the next segment of this device needs no wake word. `audio_s` and `reason` are present only when they apply. |
| `{"type":"say","id":"m12","kind":"answer"\|"control"\|"cue"\|"alert"\|"lap_summary"\|"coaching"\|"strategy"\|"goal"\|"validation"\|"race"\|"spotter"\|"info","text":"display text","speech":"spoken text","sample_rate":24000,"n_bytes":int,"meta":{...}}` | A message follows. Immediately followed by one or more **binary** frames of int16 LE mono PCM at `sample_rate` totalling `n_bytes`, then `say_end`. If TTS is unavailable `n_bytes` is 0 (display only). A client speaks every `say` frame whatever its `kind`; a kind it does not know (a newer server) is only labelled `INFO`. **`sample_rate` is per message and must be honoured**: 24 000 Hz with Kokoro (and with its `say` fallback, rendered at 24 kHz so cue parts from both engines join), 22 050 Hz with the plain `say` engine. Kokoro audio arrives trimmed to ~40 ms of silence at each end, at about -17 dBFS speech RMS with peaks at most -3 dBFS. |
| `{"type":"say_end","id":"m12"}` | End of audio for `m12`. |
| `{"type":"cancel","id":"m12"}` | Stop playing `m12` (barge-in or superseded). |
| `{"type":"pong","t":12345.6,"server_ms":int}` | Echo for round-trip measurement. |
| `{"type":"error","message":"..."}` | Non-fatal error to show. On Windows without server speech recognition (`stt` `none`: sherpa-onnx not installed, or switched off), a push-to-talk utterance is answered with an error naming `stt_reason` and a spoken "No voice questions on this server. Type your question instead." instead of a transcript and "Say again?" (macOS keeps the transcript + "Say again?"). |

## Radio policy (one engineer)

Every message the radio says, whoever makes it, follows one table: `POLICY` in `voice/scheduler.py`, printed here by
`policy_markdown()` (the test `tests/unit/test_radio_policy.py` fails if this copy and the code differ) and served as
JSON by `GET /api/radio/policy` (Settings › Radio & voice shows it). Order 0 is decided at once, outside the queue;
the queue says the rest by priority, then this order, then first in first out.

| Order | Family | Who says it | Kind | Priority | Interrupts | Intensity | Quiet mode | Speak window | Per-lap budget | Switched off by |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | Spotter | `pitwall.spotter + voice.spotter_radio` | `spotter` | urgent (still there: high) | yes | quiet, normal, detailed | said | no | outside it | Spotter |
| 0 | Red flag and punctures | `raceradio via voice.urgent` | `alert` | urgent | yes | quiet, normal, detailed | said | no | outside it | always on |
| 0 | Answers | `voice.hub, voice.handsfree` | `answer`, `control` | high | no | quiet, normal, detailed | said | no | outside it | always on |
| 0 | Braking calls and corner reminders | `coach.cues` | `cue` | high | yes | normal, detailed | held | no | outside it | Braking calls |
| 1 | Flags, penalties, damage, safety car, fuel critical | `raceradio, strategy.radio, carhealth.radio` | `alert` | high / normal | no | quiet, normal, detailed | safety calls said, the rest held | yes | never held, spends it | Race calls (flags, penalties, damage); Car health (fuel) |
| 2 | Lap time | `voice.proactive` | `lap_summary` | normal | no | normal, detailed | held | yes | waits for it, spends it | Coaching amount |
| 3 | Race calls | `raceradio` | `race` | normal / high | no | normal, detailed | held | yes | waits for it, spends it | Race calls |
| 4 | Strategy | `strategy.radio` | `strategy` | from the call | no | normal, detailed | held | yes | waits for it, spends it | Coaching amount |
| 4 | Car health | `carhealth.radio` | `strategy` | from the call | no | normal, detailed | held | yes | waits for it, spends it | Car health |
| 5 | Goal reached | `motivation.radio` | `goal` | normal | no | normal, detailed | held | yes | waits for it, spends it | Coaching amount |
| 6 | Coaching point | `voice.proactive (coach.selection)` | `coaching` | normal (praise: low) | no | normal, detailed | held | yes | waits for it, spends it | Coaching amount |
| 7 | Detail | `strategy.radio, raceradio, carhealth.radio` | `info` | low | no | detailed | held | yes | waits for it, spends it | Coaching amount: Detailed |
| 8 | Validation prompts | `validate.kit` | `validation` | low | no | quiet, normal, detailed | held | yes | outside it | Setup › Validation run |

- **Who may interrupt:** only the urgent path - spotter calls, the red flag and a puncture (`Priority.URGENT`). An
  urgent call cuts anything but another urgent call (a red flag waits for a "Car left." on air and the other way
  round), and a spotter clear never cuts a braking cue. Nothing else cuts anything: a braking cue plays only on a free
  radio (dropped as `radio busy`, never late, when something is on air; proactive messages end before the next cue
  starts), and a lap time, race call, strategy or car health call, goal line or coaching point waits for a free radio,
  the 2 s gap, a speak window and the lap's budget. The driver's own answer replaces a proactive message on air (the
  driver asked) but waits for a braking call or an urgent call. A message an urgent call cut is said again once, in
  full.
- **Corner reminders** (kind `cue`, `meta.cue` `"reminder"`; braking-call mode `focus`): for a habit being worked on
  that is not a braking fault, a short phrase before its corner ("Turn 6, apex speed, 12 down"), pre-synthesised like a
  braking call and timed to END at least 1 s before the reference braking point. It starts its own length earlier, and
  speak windows close before that start. Only where the reference lap was off the brakes for the whole phrase; one call
  per corner a lap (a reminder wins over a braking call there); dropped, never late. Muted like braking calls (quiet
  intensity, quiet mode, voice off); none on pit or out laps, under a safety car or VSC, or on a standing-start lap 1.
  It is descriptive coaching, not a braking call: it starts only on a free radio (dropped otherwise) and never with a
  car alongside (`car alongside`), it cuts nothing (a spotter clear included), and any spotter call (a clear or "still
  there" included) or a braking call cuts it; it is never said again. Reminders and braking calls together are at most
  the profile's focus corners a lap (a beginner: one), for habits costing at least 0.05 s a lap on average that the
  latest lap could measure.
- **Habit lines** (coaching points with `meta.habit_event`: an announcement, "better", "still", "sorted"): the coach's
  habit tracker records a line when the radio puts it on air, not when the coach picks it, so a line held until it
  expired (quiet mode, the lap's budget) never makes a habit the one being worked on: it is announced again on a later
  lap. With no radio connected or its voice off the coach is screen-only and records a line when it picks it. Once it is on air the braking calls and corner reminders follow at once: a habit
  announced after the line gets its reminder on that same lap.
- **Race order:** alerts, then the lap time (carrying the line's race news), race calls, strategy and car health calls,
  the goal line, the coaching point, detail; validation prompts last. A higher priority goes first (cold tyres at the
  pit exit before the lap time).
- **One per-lap budget** (`TALK_PER_LAP`): quiet 0, normal 3, detailed 5 messages a lap while the car is on track
  and moving (10 km/h or more: the grid and the pit box are outside it), shared by every producer's routine messages
  (`lap_summary`, `race`, `strategy` and car health, `goal`, `coaching`, `info`). Alerts and the race milestones (`meta.race_allowance` false: the grid brief, lights out, the countdown, the
  finish, a move into P1) are never held by it but spend it, so a busy lap (a safety car, blue flags) leaves less room
  for routine talk. Inside it, race calls take at most 2 (3 detailed) and coaching 1 per analysed lap at normal; the
  producers keep their own limits (strategy and car health: one normal call a lap; goal lines: two a session). A
  message that does not fit waits for the next lap until it expires. Off track there is no budget.
- **One message per piece of news:**
  - *The line:* race news about the lap just finished (the lap-one position, a position change or clean pass within
    5 s of the line, the countdown, the race's fastest lap, the finish; `meta.merge_into_summary`)
    waits up to 6 s for that lap's `lap_summary` and is said inside it ("That lap, 1:25.4, personal best. Fastest lap
    of the race."): one message, one budget slot, `meta.merged_race_calls` the call ids (carrying the countdown, the
    finish or a move into P1 it is never held by the budget either). A summary holds at most 20 spoken words (the
    chequered flag always rides in the final lap's); news that does not fit goes on its own at once.
  - *The safety car:* the race radio's deployment call and race strategy's box-or-stay call both announce it
    (`meta.announces` `sc`; the strategy call's first words are `meta.announce_head`). Queued together they are one
    message ("Safety car, safety car. No overtaking. Pitting this lap is an option: ..."); the strategy call said
    within 60 s after the deployment call drops its head ("Pitting this lap is an option: ..."); a deployment call
    after the strategy call is dropped.
  - *Shared topics:* fuel (race strategy in F1 races, car health's tank fuel in Forza) and the gap (race strategy's gap
    calls, the race radio's gap report) are one topic each: a newer message replaces an unsaid one.
  - *Answers hold their topic:* for 30 s after the driver asked about the fuel, the gaps, the laps left or the weather,
    a proactive message on that topic below `high` priority is not said.
  - *Identical sentences* are not repeated within 60 s (flags, penalties and damage excepted: their rules space them).
  - *After the flag:* once the race radio's finish call is queued no coaching point is said (no next lap can use it).

## Behaviour

- **Push-to-talk** sources: on-screen button, or a wheel button mapped in F1 25 to a *UDP Action*, received through
  the game's `BUTN` telemetry event. The actions follow the seated driver's F1 25 layout in Setup › Controls
  (`ptt_actions` in `state`, additive, with `ptt_label` the control's name when known), plus the deploy setting
  `PITWALL_VOICE_PTT_BUTTON` (default UDP Action 1) as a fallback; a change applies at once, and a held wheel
  transmission whose action leaves the set ends. While Setup › Controls tests buttons, wheel push-to-talk is paused
  (`wheel_ptt_paused`, additive; it lapses on its own if the page stops polling). PTT down starts an utterance; release
  ends it (max 12 s). Audio while PTT is up is discarded (not stored, not transcribed).
- **Half-duplex gate**: while the device is playing a message (+300 ms tail) mic audio is discarded, so the
  engineer never answers itself. PTT down during playback = barge-in: server sends `cancel` and listens.
- **Mic stays open** for the whole session on the device (opening/closing it per PTT breaks AirPods routing
  on iOS); gating happens on the server.
- **Proactive messages** (lap summary, coaching, goal lines, strategy, race and car health calls, alerts, validation
  prompts) go through one policy (`voice/scheduler.py`, "Radio policy" above). They are queued by priority, then
  kind, and only spoken in a *speak window* (not braking, not cornering, no car alongside, enough time before the next
  braking zone or braking call; before the track's model is learned, the zones of the track knowledge and of the
  driver's own last three laps out of the pit lane); they respect quiet mode ("stop talking for 3 laps") and coaching intensity, the one
  per-lap budget, and expire when no longer actionable.
  - **Intensity:** `quiet` says answers, acknowledgements, alerts, spotter and urgent calls and validation prompts;
    `normal` adds the lap summary, `race` calls, `strategy` and car health calls, goal lines and coaching; `detailed`
    adds `info`.
  - **Seat change:** when another driver takes the seat, unsaid `lap_summary`, `goal` and `coaching` messages about
    the previous driver's laps are dropped; alerts, race, strategy and car health calls (about the car) stay.
  - **Coaching** (kind `coaching`): the lap's coach block `picked` points (`coach.selection`, the same points the Drive
    screen shows): the habit tracker's events first (`meta.habit_event` `fixed`, `improving`, `announce` or `still`;
    "Turn 6, losing 0.31 s: minimum speed 12 km/h down. 3 of the last 4 laps."), then a single lap's big fault (0.3 s
    or more, clearly measured; `meta.habit_event` null), then praise. A habit being worked on is not said again in full
    every lap (its corner reminder, above, does that), small one-offs are screen-only, and the same big fault two laps
    running is said once.
- **Race radio** (kind **`race`** and `alert`, `pitwall/raceradio`): race situation calls (position, the start and
  countdown, lap one, gaps, warnings, minor damage) are kind `race`: normal and detailed intensity, from the one
  per-lap budget (at most 2 of it a lap at `normal`, 3 at `detailed`). Calls marked `meta.race_allowance` false are
  said whatever the budget (and spend it): the grid brief and lights out (standing still), the countdown (at the
  line), the finish (after the flag) and a move into P1. News made at the line (`meta.merge_into_summary`) is said
  inside that lap's `lap_summary` ("That lap, 1:29.4. Two laps to go."): one message, kind `lap_summary`,
  `meta.merged_race_call` the first call id and `meta.merged_race_calls` all of them. A puncture is safety-critical:
  it goes as an urgent call (below). Flags, penalties
  and damage (`meta.repeat_ok`) are exempt from the 60 s identical-sentence filter: their own rules space them (a
  second blue flag 30 s after the first is said). After a flashback the server drops the unsaid `position` and
  `damage` calls (queued or held: the rewind undid them). Flags, penalties and damage that matter
  are `alert` (yellow, blue, the safety car, time penalties, major damage; a drive-through, stop-go, disqualification,
  black flag, a puncture or severe damage also past quiet mode); a rival's fastest lap and a far retirement are
  `info` (detailed only, never for simple wording). `meta` carries `topic` (`race:position`, `race:countdown`,
  `race:yellow`, `race:blue`, `race:sc`, `race:warning`; the gap report shares `strategy:gap` with strategy), `group`
  (flags, start, position, rivals, penalties, damage: the driver's toggles), `call` (`position_change`,
  `yellow_ahead`, ...), `urgent` (false), `tier` (`recorded`, `synthetic` or `community`: the evidence behind the
  call's rule), `synthetic` (the session is synthetic), `addressable` and `race_call` (the call id). A driver who asks
  for simple words hears each call's plain words. Text and speech never contain a player's online ID.
- **Urgent calls** (kind `alert`, `meta.urgent` true; the red flag and a puncture, safety-critical): said at once,
  past quiet mode, intensity, the driver's race call toggles, the speak window and the 2 s gap; they cut a cue or a
  proactive message (which is said again once), wait only for the driver's own transmission and never cut another
  urgent call - a spotter call included: urgent calls and spotter calls share one rule (`voice/scheduler.py`
  `may_interrupt`), so a red flag waits for a "Car left." on air and the other way round. With the voice off they are not said (the screen shows
  the red flag). Any server component posts one with `live.notify("radio_urgent", ...)` (`voice/urgent.py`); the
  latency from that notify to the first audio byte is a `latency` record of kind `urgent` in `/api/voice/status`.
- **Name addressing** (`voice/addressing.py`): now and then the radio says the seated driver's first name ("Up to P5,
  Sam."): at most once a minute, on messages marked `meta.addressable` (lap one, a gained place, a clean pass, the
  finish, the last lap, the driver's fastest lap) and once on the first proactive message after a seat change; never
  on an urgent call, a cue, an answer, an acknowledgement or a validation prompt. The name goes before the first
  sentence end, or first when that sentence already has a comma or colon ("Sam, that lap, 1:15.5."). The driver's
  "Say my name" toggle switches it off, and so does a Kokoro voice whose G2P would drop the name (asked once per
  driver through the worker's `g2p` request; nothing is logged).
- **Goal lines** (kind **`goal`**, `pitwall/motivation`): one short line when the driver reaches a goal, at most two a
  session, never with a lap time. `meta.topic` is `goal:<session id>`. A lap that takes a family board's record from
  another driver (`pitwall/leaderboard`, live note `family_record`) gets one line of the same kind under the same
  two-a-session cap ("New family record at Austria: you took it from Sam."), `meta.topic` `record:<session id>`.
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
    and nothing held (re-checked after synthesis; never in quiet mode; an `info` message, not a control),
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
- **Spotter calls** (kind **`spotter`**, F1 25, `pitwall/spotter` + `voice/spotter_radio.py`; off by default):
  `meta` = `{"spotter": "car_left"|"car_right"|"three_wide"|"clear_left"|"clear_right"|"clear_all_round"|"still_there"|
  "hold_your_line", "side": "left"|"right"|null, "seq": int, "phrase": str, "test"?: true}` (no car index, no names;
  `phrase` is what was said: `car_left` for a `still_there` or `hold_your_line` whose onset the driver never heard,
  `still_there_left` for a still there on the left). The audio is synthesised in advance and sent as PCM to **every**
  client, device-voice clients included (`n_bytes` > 0 and no `device_tts` flag: clients play PCM whenever there is
  some); without a clip, device-voice clients get the text as usual. Spotter calls are on the urgent path (the one
  rule, `voice/scheduler.py` `may_interrupt`, shared with the red flag): a spotter call cuts a cue, a proactive
  message, an answer or a hands-free capture (proactive messages and answers are said again once; the cue is
  dropped), never another spotter call or an urgent call (a red flag on air, or the other way round); it waits while
  the driver transmits. A clear never cuts a cue: it waits for the cue to end; a cue is not sent while any spotter
  call is on air (a cue cuts nothing). `still_there` is sent at `HIGH`
  priority and never cuts anything. A call lost while the radio was busy is made up when it is free (the driver hears
  the side as it is then). Every intensity and
  quiet mode include it; `voice_enabled` false mutes it. Older clients label the kind `INFO` and still play it. The
  `state` frame's `spotter` object says whether it is on, whether its audio is ready and the spotter's own voice
  (null = the engineer's). REST: `GET /api/spotter`, `PUT /api/spotter/settings`, `POST /api/spotter/test`.
- Latency is measured per stage (PTT release -> transcript -> answer -> first audio sent -> playback started).
  Spotter calls: packet received -> decided -> on every client queue -> `playback started` (`GET /api/spotter`).
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
