# Radio setup: iPad + one AirPod + wheel push-to-talk

Game audio stays on the TV; the race engineer talks in one AirPod connected to an iPad, which runs the Pitwall
dashboard. You talk back with a wheel button. Pitwall itself runs on your computer: a Mac with Apple Silicon has the
whole radio, including spoken questions; other computers differ (see [Voices and speech recognition by
platform](#voices-and-speech-recognition-by-platform)).

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
5. **Wheel push-to-talk (F1 25)**: Settings -> Controls -> your wheel -> assign a spare button to
   **UDP Action 1**. Pitwall receives presses through the game's telemetry (`BUTN` event); hold to talk,
   release to send. Change the action with `PITWALL_VOICE_PTT_BUTTON=udp_action_2` etc.
   UDP telemetry must be on (see [F1 25 settings](install.md#f1-25-tested-live-on-ps5)).

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

## Voices and speech recognition by platform

| Computer | The engineer's voice on the computer | Spoken questions (speech recognition) |
| --- | --- | --- |
| Mac with Apple Silicon | the natural voice (Kokoro, optional) or the macOS voices | Parakeet, installed by `uv sync --all-extras` |
| Intel Mac | the macOS voices | a whisper.cpp server |
| Windows | Windows' built-in voices (SAPI) | a whisper.cpp server |
| Linux | none: text only | a whisper.cpp server |

- **The iPad's own voice** works with every computer: Settings › Radio & voice › Engineer voice › This iPad (the
  iPad's Premium voices sound best). Typed questions also work everywhere.
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
  **Live**) and that the button is mapped to UDP Action 1 in the game's controls.
- *Push-to-talk is heard but not understood*: the computer has no speech recognition (see the
  [table above](#voices-and-speech-recognition-by-platform)); `uv run pitwall doctor` shows the voice setup. Type the
  question instead.
- *Engineer answers itself*: should not happen (server-side half-duplex gate) - report it with the time.
- *The voice sounds like the old robotic one* (Mac): the Mac voice line in Settings › Radio & voice says why
  (natural voice starting, restarting or not installed). Details: `GET /api/voice/status` -> `tts_engine`
  (`last_error`), and the server log (lines from `tts-worker`; `scripts/pitwall-service.sh logs` when Pitwall runs
  as the launchd service, `scripts\windows\service.ps1 logs` for the Windows task). Re-run `scripts/setup-tts.sh`
  if it is missing.
- *A name is skipped or mispronounced*: add it to `src/pitwall/voice/data/lexicon.json` (words the G2P dropped
  are listed in `tts_engine.dropped_words`), then `uv run pytest -m tts`.
