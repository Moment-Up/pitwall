# Radio setup: iPad + one AirPod + wheel push-to-talk

Game audio stays on the TV; the race engineer talks in one AirPod connected to an iPad, which runs the Pitwall
dashboard. You talk back with a wheel button (F1 25), the on-screen button, a Bluetooth button, or hands-free with a
wake word ([Talking to the engineer](#talking-to-the-engineer)). Pitwall itself runs on your computer: a Mac with
Apple Silicon has the whole radio, including spoken questions; other computers differ (see [Voices and speech
recognition by platform](#voices-and-speech-recognition-by-platform)).

Replace `<your-computer>.<your-tailnet>.ts.net` below with your computer's Tailscale name (the Tailscale app shows
it; the dashboard's Connect page shows the full address too), and `8443` with the port you chose. Install and
Tailscale steps: [install.md](install.md#open-it-on-an-ipad-or-phone).

| Where | Address (tailnet only) |
| --- | --- |
| Dashboard (opens on Drive › Coach) | **`https://<your-computer>.<your-tailnet>.ts.net:8443/`** |
| Radio page (Drive › Radio) | `https://<your-computer>.<your-tailnet>.ts.net:8443/#/drive/radio` |
| Radio & voice settings | `https://<your-computer>.<your-tailnet>.ts.net:8443/#/settings/radio` |
| Old dashboard links (`#/radio`, `#/radio?token=…`, `#/live`, ...) | still work: they open the same page in the new dashboard |
| `…:8443/next/` (where the new dashboard was tried out) | a temporary alias of `/`, to be removed: use the addresses above |

These are the new dashboard's addresses (prebuilt in every release). The classic dashboard, which you get when you
build from source without a HeroUI Pro licence, has its Radio page at `…:8443/#/radio`.

## One-time setup

1. **Tailscale on the iPad**: install the Tailscale app and sign in to the same tailnet as the computer; the iPad
   must show as connected.
2. **On the computer**: `tailscale serve status` lists the ports already served; pick one that is not listed
   (8443 here). Then `tailscale serve --bg --https=8443 http://127.0.0.1:8770` exposes Pitwall at
   **`https://<your-computer>.<your-tailnet>.ts.net:8443`** (tailnet only). Your Tailscale login is trusted
   automatically - no token needed on your own devices. Remove with `tailscale serve --https=8443 off`.
3. **iPad Safari**: open the URL above, then Share -> *Add to Home Screen* (wake lock works in Home Screen
   web apps on iPadOS 18.4+). Open it from the Home Screen icon from now on. An icon saved from the old dashboard
   (including one saved on `#/radio?token=…`) keeps working; one saved from `…/next/` should be added again from the
   address above.
4. **AirPods hopping**: on your iPhone and Mac, Bluetooth -> AirPods (i) -> *Connect to This iPhone/Mac* ->
   **When Last Connected to This iPhone/Mac**, so the AirPod stays on the iPad during a session.
5. **Wheel push-to-talk (F1 25)**: in F1 25, **Controls > (your wheel's preset) > UDP Custom Actions**, assign a
   spare button to **UDP Action 1** (or the action Pitwall's **Setup › Controls** shows for the driver in the seat).
   Pitwall receives presses through the game's telemetry (`BUTN` event); hold to talk, release to send. The radio
   follows the seated driver's saved F1 25 layout without a restart; `PITWALL_VOICE_PTT_BUTTON=udp_action_2` (etc.)
   changes the fallback action, which keeps working too. Setup › Controls › Test shows whether the button reaches
   Pitwall. UDP telemetry must be on (see [F1 25 settings](install.md#f1-25-tested-live-on-ps5)). In other games
   Pitwall can't see wheel buttons: use the on-screen button (or Space on a keyboard).
<!-- --- spotter --- -->
6. **Spotter (F1 25, optional)**: switch it on in Settings > Radio & voice > Spotter. It needs the game's **UDP Send
   Rate at 60 Hz** (at the default 20 Hz calls come about 70 ms later; the card warns below 30 Hz). A **wired**
   PS5 and computer help: on the owner's Wi-Fi about 1 packet in 10 arrived 45-75 ms late (p99 about 90 ms), and
   that delay is added to every call. Settings > Radio & voice > Spotter > **Test spotter** says "Car left", then
   "Clear left" on the connected radio. The calls are recorded in advance in the radio's voice (or the spotter's
   own Kokoro voice), so the iPad plays them as audio even when it speaks the engineer's messages with its own voice.
<!-- --- end spotter --- -->

## Each session

1. Put one AirPod in; make sure it is connected to the **iPad** (Control Centre -> audio output).
2. Open Pitwall: **Drive › Coach** has the radio strip at the bottom. Tap **Go live** there (or on Drive › Radio;
   iOS needs this tap to allow audio). Allow the microphone.
3. Keep the iPad **unlocked with Pitwall in front** (mount it; once the radio is live the page keeps the screen
   awake, and so do the Drive pages while telemetry is live - if the browser refuses, Drive shows `Screen may
   sleep`). iPadOS cuts the microphone if Safari goes to the background or the screen locks. The radio keeps
   running on every page: outside Drive a floating radio bar has **Hold to talk** and a button back to
   Drive › Radio.
4. Say "radio check" (hold the wheel button, or **Hold to talk** on screen; Space on a Mac's Drive pages) - the
   engineer should answer in the AirPod. Drive › Radio also has a **Radio check** button.

Evidence: a radio check over an iPad and one AirPod through Tailscale has been heard on hardware, with a Mac and
the classic dashboard's Radio page. The new dashboard's Go live and push-to-talk over Tailscale have not been tried
on an iPad yet, and spoken questions are still to be tested by a driver.

## Talking to the engineer

Push-to-talk is the default. Every way of talking goes to the same engineer, with the same rules (deterministic
answers while moving, the language model only when stopped).

| Way | Games | How |
| --- | --- | --- |
| Hold the big button, or Space on a keyboard | all | Drive › Radio, the radio strip or the floating radio bar |
| A wheel button | F1 25 only | map a spare button to **UDP Action 1** (step 5 above); GT7, Assetto Corsa and Forza send no button data |
| A Bluetooth button | all | a page turner, pedal or spare game controller paired with the iPad (below) |
| Hands-free | all | start with **"Pitwall"** (or **"Radio"**): "Pitwall, what's my fuel?" (below) |

**Bluetooth button** (Settings › Radio & voice › Talking to the engineer › *Set up*, then press the button). It works
held (talk while held) or tapped (tap to start; it stops when you go quiet, at the next press, or after 12 s).

- Use a device that presents itself **only as a keyboard** (a page turner or foot pedal such as AirTurn, PageFlip or
  Donner). iPadOS 18.4 and later stopped passing key presses from keyboard-plus-pointer devices to Safari in Desktop
  Mode (WebKit bugs 301563 and 290779), and iPad Safari uses Desktop Mode by default.
- A **spare** Bluetooth game controller paired with the iPad also works (Safari's Gamepad API; press any button once to
  wake it). The wheel and the console's own controller are paired with the PS5, so they cannot be used. Not yet tried
  on an iPad.
- **AirPods stem presses and headphone play/pause buttons cannot reach a web page on iPad** (they belong to native
  apps that hold a call or the "Now Playing" slot), so they cannot be used as the button.

**Hands-free** (Settings › Radio & voice, or the switch under the segments on Drive › Radio; off on every device until
you turn it on there, and the first time it asks you to confirm). While the radio is live, the iPad listens for
speech; the computer turns what it hears into text and answers only when it starts with the wake word you chose,
"Pitwall" or "Radio" ("Hey Pitwall", "OK Pitwall" work too). Everything else is thrown away at once: never shown,
saved or logged. The screen shows when it is listening ("Listening for "Pitwall"", "Hearing you…").

- Say the wake word alone ("Pitwall." or "Pitwall, um.") and the engineer says "Go ahead." - then ask, without the
  wake word, within 6 seconds. Only a question about the car or the race is taken that way: anything else said then
  is thrown away like any other talk.
- **Only while the car is stopped** (on the grid, in the pits, in the garage and menus, after the flag; also when no
  game data arrives at all, e.g. a game Pitwall does not read) unless the driver in the seat turns on **Hands-free
  while driving**: in their profile (Settings › Drivers), or with **Also while driving** under the hands-free switch on
  Drive › Radio while they are seated. On track it shows "Hands-free paused · driving" and a sentence you started
  just before moving off is dropped; if you try to talk, the engineer tells you once a session, at a stop of at least
  8 seconds, that hands-free only listens when you stop. A short stop (a spin, a flashback, the grid just before
  lights out) does not count. On the owner's real races the car is still for only 0-28 % of a race.
- While you are talking hands-free, and while the engineer waits for your question after "Go ahead.", the radio
  holds its own messages back (urgent calls still go out). On track a braking call still cuts in: if you had started
  with the wake word, the engineer says "Say again?" after it.
- It needs speech recognition on the computer (the table below). `PITWALL_VOICE_HANDSFREE=false` turns it off for
  every device.
- Settings › Radio & voice › Diagnostics shows the microphone level, the noise floor and the threshold, and how many
  segments were heard, ignored or too long. `GET /api/voice/status` -> `handsfree_diag` has the server's side (counts
  per reason, never any words).

- On Windows the speech model downloads the first time (about 660 MB): until it is ready hands-free shows "Hands-free
  starting…" with the download's progress, and a push-to-talk question gets "Speech recognition is still starting".

Evidence: synthetic and recorded only. The wake word was checked with macOS `say` voices through the real speech
engines, and the stopped/moving rule on 11 of the owner's real captures; hands-free has not been tried on the rig, with
a real voice, an AirPod or engine noise yet, and the Bluetooth button has not been tried on an iPad
([research/handsfree.md](research/handsfree.md)).

## Voices and speech recognition by platform

| Computer | The engineer's voice on the computer | Spoken questions (speech recognition) |
| --- | --- | --- |
| Mac with Apple Silicon | the natural voice (Kokoro, optional) or the macOS voices | Parakeet, installed by `uv sync --all-extras` |
| Intel Mac | the macOS voices | a whisper.cpp server, or sherpa-onnx installed by hand |
| Windows | Windows' built-in voices (SAPI) | Parakeet (English) on the CPU via sherpa-onnx, installed by `uv sync --all-extras` (CI-installed, not yet tried on a Windows PC) |
| Linux | none: text only | a whisper.cpp server, or sherpa-onnx installed by hand |

- **The iPad's own voice** works with every computer: Settings › Radio & voice › Engineer voice › This iPad (the
  iPad's Premium voices sound best). Typed questions also work everywhere.
- **Parakeet via sherpa-onnx** (Windows): the speech model (NVIDIA Parakeet TDT 0.6B v2, English, about 660 MB)
  downloads from Hugging Face the first time a radio connects, into `%LOCALAPPDATA%\pitwall\stt` (pinned files,
  checked by size and SHA-256); until it is ready a spoken question gets "speech model downloading (NN %)". Offline:
  copy `encoder.int8.onnx`, `decoder.int8.onnx`, `joiner.int8.onnx` and `tokens.txt` from
  `huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8` (revision `1ab9323`) into a folder and set
  `PITWALL_STT_SHERPA_DIR` to it (`HF_HUB_OFFLINE=1` stops the download). `PITWALL_STT_THREADS` sets the CPU threads
  (default: half the cores, 1-4). On the Mac's CPU a 3 s question takes about 0.1 s; expect a few times that on a
  PC. `uv run pitwall doctor` says whether it is installed and the model ready. On Linux or an Intel Mac,
  `uv pip install 'sherpa-onnx>=1.13.8,<1.14'` and `PITWALL_STT_ENGINE=sherpa` use it too.
- **whisper.cpp**: run a [whisper.cpp](https://github.com/ggml-org/whisper.cpp) server and set
  `PITWALL_STT_ENGINE=whispercpp` and `PITWALL_WHISPERCPP_URL` (default `http://127.0.0.1:8178`) in `.env`. This path
  has only been tested against a mock server. Without speech recognition, push-to-talk cannot take spoken questions;
  on Windows the radio says so.
- **Windows voices**: `uv run pitwall doctor` lists the voices installed on the PC, and
  `PITWALL_TTS_SAPI_VOICE=Hazel` in `.env` picks one (part of its name is enough; by default an en-GB voice if one
  is installed). `PITWALL_TTS_SAPI_RATE` (-10 to 10) sets the speed. They are CI-tested but have not been heard on a
  radio yet. Windows' newer "natural" voices are not available to Pitwall. The dashboard calls the computer's voice
  "Mac voice" on Windows too.

## The engineer's voice on a Mac

With the natural voice installed, the Mac speaks with **Kokoro** (a neural voice running locally on the Mac's GPU,
in its own process; Apple Silicon only). Default voice **Fable** (British male, `bm_fable`) at 1.1x speed;
alternatives George (British male), Emma and Isabella (British female). Pick one under **Settings › Radio & voice ›
Mac voice** (it applies to every radio and is remembered; it is set over the radio link, so Go live first) and press
**Test voice** to hear it. The iPad must be set to **Engineer voice: Mac voice** to hear the Mac's audio; the first
time the Mac reports the natural voice, a device that used its own voice is switched to it once - switch back to
*This iPad* if you prefer the iPad's Premium voice. The braking calls (Off, Focus, Markers, All) and how much
coaching the engineer gives are on Drive › Radio and Settings › Radio & voice. The natural voice has been tested on
synthetic phrases only; it has not been heard in a live session yet.

One-time install on the Mac (about 1 GB, offline afterwards):

```bash
scripts/setup-tts.sh              # venv + pinned packages + pinned model, then an offline self-test
```

Then restart Pitwall (when nobody is driving) so it picks up the voice. Kokoro, `bm_fable` and 1.1x are the
defaults; `PITWALL_TTS_VOICE` and `PITWALL_TTS_SPEED` in `.env` change them.

If the natural voice is not installed, still starting (about 2-10 s after Pitwall starts) or crashes, the macOS
voice (`PITWALL_TTS_FALLBACK_VOICE`, default Daniel) speaks instead and Settings › Radio & voice says so (the Mac
voice line); the worker restarts by itself. `PITWALL_TTS_ENGINE=say` uses the macOS voices only.

To compare voices by ear, open `/api/voicelab` on the iPad (`PITWALL_VOICELAB_DIR`): the
`pitwall-radio-kokoro-x1.1__*` folders are exactly what the radio plays; the rest are the evaluation's samples
(docs/research/tts-evaluation.md).

## What you can say

"How are my tyres?" · "What's my fuel situation?" · "Where am I losing time?" · "Where should I brake for
turn one?" · "Compare that lap to my best." · "Give me one thing to work on." · "Stop talking for two laps." ·
"You can talk again." · "Start a drill on turn 3." · "How's my drill going?" · "Stop the drill." · "Who am I
compared with?"

Fuel, tyres, lap times, radio control, practice drills and "who am I compared with?" are answered instantly, without
the language model. Only a command starts or stops a drill ("start a drill on turn 3", "please stop the drill"): a
question about a drill ("how did the drill go?", "should I do a drill at turn 4?") gets its status, and "don't stop
the drill" changes nothing. A
drill keeps the radio on its corner: one line a lap ("Turn 3 drill, 2 of 5: on the point. 2 hits."), no lap
summary and braking calls for that corner only, until it ends or you stop it. Name the skill to choose it ("a
braking drill", "minimum speed", "exit", "entry") and the length ("for three laps", 3 to 10).

While the car is moving every answer is built from the facts at once, never by the language model and never with
"Copy, checking". Stopped, analysis questions go to the language model if you set one up (Settings › AI engineer):
the engineer says "Copy, checking" and answers a few seconds later. Without a model, the answer is built from the
facts.

## What the radio says at each intensity

The coaching intensity is set per driver (Settings › Drivers) and changed on the radio ("stop talking for two laps",
"you can talk again"). On track the radio says at most two messages a lap of its own at normal intensity and four at
detailed, in a calm part of the lap; braking cues, alerts and your answers do not count towards that.

| | quiet | normal | detailed | "quiet for N laps" | voice off |
|---|---|---|---|---|---|
| Answers, acknowledgements | yes | yes | yes | yes | on screen |
| Urgent alerts; safety car box or stay out; critical fuel | yes | yes | yes | yes | on screen |
| Lap summary, goal line, coaching point, drill point | - | 2 a lap | 4 a lap | held | - |
| Strategy calls | - | within the 2 | within the 4, plus detailed notes | held | - |
| Validation prompts (during a run you started) | yes | yes | yes | held | - |

In a race the order is the lap time, then the strategy call, then the goal line, then the coaching point; a message
that does not fit waits for the next lap or expires. When another driver sits down, the previous driver's unsaid lap
messages are dropped. At quiet intensity drill points show on the screen only. Full table:
[features.md](features.md#what-the-radio-says).

**Race radio.** In a race the engineer also calls flags, the start and laps to go, positions, gaps, penalties and
damage ([features.md](features.md#race-radio)), with an allowance of its own (two race calls a lap at normal, three
at detailed) so they never push out the lap summary or the coaching point. Each driver chooses the groups they hear
in Settings › Drivers › Race radio (flags, start, position, rivals, penalties, damage, "say my name sometimes"; the
red flag is always on) and the radio's words (Automatic: simple words for beginners; Simple; Standard). Ask "who's
ahead?", "do I have a penalty?", "what's my damage?" or "how was sector 2?" at any time.

## Troubleshooting

- *No microphone permission prompt / mic unavailable*: you are on http:// - use the https Tailscale URL.
- *Audio comes out of the iPad speaker*: reconnect the AirPod to the iPad, then tap Go live again.
- *Wheel button does nothing*: check UDP telemetry is reaching Pitwall (the connection pill on Drive says
  **Live**) and that the button is mapped to the UDP Action Setup › Controls shows (UDP Action 1 by default) in the
  game's controls; Setup › Controls › Test shows what F1 25 reports when you press it.
- *Push-to-talk is heard but not understood*: the computer has no speech recognition (see the
  [table above](#voices-and-speech-recognition-by-platform)); `uv run pitwall doctor` shows the voice setup. Type the
  question instead.
- *Engineer answers itself*: should not happen (server-side half-duplex gate) - report it with the time.
- *Hands-free never answers*: the chip says why ("Hands-free unavailable": no speech recognition on the computer;
  "paused · driving": the car is moving and the driver's profile does not allow it). Start with the wake word you
  chose, clearly, then the question. Settings › Radio & voice › Diagnostics shows whether speech was heard at all.
- *A Bluetooth button does nothing*: check it is a keyboard-only device (see [above](#talking-to-the-engineer)), set
  it up again under Settings › Radio & voice, and keep Pitwall in front on a Drive page.
- *The voice sounds like the old robotic one* (Mac): the Mac voice line in Settings › Radio & voice says why
  (natural voice starting, restarting or not installed). Details: `GET /api/voice/status` -> `tts_engine`
  (`last_error`), and the server log (lines from `tts-worker`; `scripts/pitwall-service.sh logs` when Pitwall runs
  as the launchd service, `scripts\windows\service.ps1 logs` for the Windows task). Re-run `scripts/setup-tts.sh`
  if it is missing.
- *A name is skipped or mispronounced*: add it to `src/pitwall/voice/data/lexicon.json` (words the G2P dropped
  are listed in `tts_engine.dropped_words`), then `uv run pytest -m tts`.
