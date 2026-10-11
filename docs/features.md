# Pitwall features

A tour of what Pitwall does, screen by screen. The screenshots show the new dashboard (`web-react/`) at iPad
landscape size in a desktop browser, with telemetry from real F1 25 sessions recorded on a PS5. The driver names
are demo profiles. Every [release](install.md#install-from-a-release) has the new dashboard prebuilt. The classic
dashboard (`web/`), which you get when you build from source without a HeroUI Pro licence, covers most of the same
ground with a different layout; the [last section](#the-classic-dashboard) maps one to the other.

**Evidence.** Pitwall separates three kinds of evidence: *synthetic* (generated telemetry with known mistakes),
*recorded* (real game output captured to a file) and *live* (the real game, end to end). The new dashboard has been
tested with recorded and synthetic sessions in a desktop browser, not yet on a real iPad during a live session.
Where a feature has less evidence than that, this page says so. [status.md](status.md) has the full record.

- [Drive](#drive)
- [Radio](#radio)
- [Review](#review)
- [Setup](#setup)
- [Settings](#settings)
- [How the coach decides what to say](#how-the-coach-decides-what-to-say)
- [How the race engineer makes strategy calls](#how-the-race-engineer-makes-strategy-calls)
- [The AI engineer](#the-ai-engineer)
- [The classic dashboard](#the-classic-dashboard)

## Drive

Drive is the screen next to your wheel. It reads only live telemetry and the radio, so it works with no language
model at all. Values Pitwall does not know show as `-`, and synthetic data is labelled.

### Coach

![Drive › Coach on track](screenshots/01-drive-coach.png)

The next corner, how far away it is, and a braking cue when one is due. On the right, the live delta to your
reference lap, a level gauge and the projected lap time. Below, the corner point from your last lap ("Work on"
or "Good"), the last lap's sectors and the lap times. The radio strip at the bottom shows what the engineer last
said and has the push-to-talk button.

![Drive › Coach under a yellow flag](screenshots/02-drive-yellow-flag.png)

Game flags take over the status band: here a yellow flag in sector 2, also hatched on the track ribbon at the
bottom. The delta and the coaching keep running.

![Drive › Session complete](screenshots/03-drive-session-complete.png)

When the session ends, Drive shows the best lap, the number of clean laps, the time gained, one thing to work on
and one thing that went well. Before a session starts it shows a Ready card, and without telemetry it shows what to
check plus a button to try the synthetic demo.

### Car

![Drive › Car](screenshots/04-drive-car.png)

The pit wall view: speed, gear, throttle, brake and steering, the track map with the car's position, tyres and
fuel, the lap table and the last lap's coaching.

In an F1 25 race of 8 laps or more the inputs tile becomes a **Strategy** tile (in a shorter sprint the pit, undercut
and fuel rows would never change, so the inputs trace keeps its place): the gap to the car ahead and behind (with the
trend, "close" within a second and DRS range), the pit window and the best lap to stop, the undercut on the car ahead
and the threat from behind (the laps to go when no stop is needed), the fuel margin to the flag (with how long to
lift and coast when you are short), and the weather forecast ("after the flag" when a change comes too late to
matter). Under a safety car or VSC the weather row shows what a stop costs now against under green. Amber is kept
for what to act on or watch now. The footer shows the newest call while it holds (up to two lines). Numbers that
come from the game's own tyre model say "(game)", rules of thumb say "(estimate)", and anything not yet known is
`-`. A driver whose profile asks for simple wording gets plain words ("Laps to go", "close", "lift early"). Race strategy is tested on recorded PS5 races and synthetic ones; **not yet validated live**, and safety car,
rain and your own pit stop are synthetic only (see [how the race engineer makes strategy
calls](#how-the-race-engineer-makes-strategy-calls)).

### Track

![Drive › Track](screenshots/05-drive-track.png)

The track map follows the car and highlights the next corner. Each corner lists what the coach said about it on
the last lap. Corners are learned from your own laps. Official corner names appear only where a track sheet has
been checked by hand, which so far is Austria.

## Radio

![Drive › Radio](screenshots/06-drive-radio.png)

The race engineer. Tap **Go live** once (the browser needs a tap before it plays audio), then hold the button,
the Space bar on a Mac, or a wheel button mapped to F1 25's UDP Action 1, and ask. Questions about fuel, tyres,
lap times and radio control are answered at once from telemetry. Analysis questions go to the language model if
there is one; the engineer says "Copy, checking" and answers a few seconds later. Without a model, the answer is
built from the facts, as in this screenshot. You can also type questions. Spoken questions need speech
recognition on the computer: built in on a Mac with Apple Silicon, and a whisper.cpp server elsewhere (Windows,
Linux, Intel Macs); typed questions work everywhere.

The engineer speaks on its own too: a summary after each lap and a coaching point, but only in a calm part of the
lap (off the brake, steering nearly straight, with time to finish before the next braking zone). "Stop talking for
two laps" and "You can talk again" work as you would expect. This timing is tested on replayed sessions; it has
not yet been heard in a live session.

**Braking calls** have four modes. *Focus* (the default) calls "brake" only for the one to three corners where you
lose the most time under braking. *Markers* says the corner name before every braking zone. *All* calls every
braking zone. *Off* is silent. Braking calls are tested on synthetic and recorded data and **not yet validated
live on track**.

In a race the engineer also makes **strategy calls**: the safety car or VSC opportunity to pit, critical or tight
fuel, the pit window opening and its last laps, the car behind pitting (cover the undercut), a rain forecast, and,
at the detailed setting, the car behind coming within a second, the undercut on the car ahead, a car ahead pitting
and gap trends. They wait for the same calm part of the lap; quiet intensity keeps only the alerts. A driver with
simple wording hears every call in plain words ("Pit this lap or next: your tyres are nearly worn out.") and never
the ones meant for experienced drivers. With the radio off, the newest strategy alert still shows in the Coach
screen's radio strip. Ask
"when should I pit?", "gap to the car ahead?", "is it going to rain?" or "fuel?" for an instant answer from the
live strategy. How these are decided: [below](#how-the-race-engineer-makes-strategy-calls).

Evidence: a radio check over an iPad and one AirPod through Tailscale has been heard on hardware, using the classic
dashboard's Radio page. The new dashboard's Go live and push-to-talk over Tailscale have not been tried on an iPad yet.
The F1 25 wheel button is read live from the game on PS5, but spoken questions from the iPad, by screen or wheel
push-to-talk, are still to be tested by a driver. The natural voice (Kokoro) is tested on synthetic phrases only, and
Windows' built-in voices in CI only (not yet heard on a radio). Setup: [install.md](install.md#the-voice-radio-optional)
and [radio-setup.md](radio-setup.md).

## Review

### Sessions

![Review › Sessions](screenshots/07-review-sessions.png)

Every session for the selected driver, newest first, with a preview of the selected one and its main thing to
work on. Each session has Summary, Laps, Compare, Corners and Ask tabs, and races also have a **Strategy** tab:
grid to finish, stops and the measured pit loss, a timeline of position and gaps with your stops, safety-car laps
and the weather, your stints, every car's measured pit stops (with why a stop was left out of the pit loss), and
the strategy calls the radio made. Races recorded before strategy tracking say so instead.

![Review › Session summary](screenshots/08-review-session-summary.png)

The summary: best lap, clean laps, improvement and consistency, the best sectors combined, and the corners ranked
by how much time they cost.

![Review › Compare](screenshots/09-review-compare-light.png)

Compare puts two laps side by side when they share the car, track and conditions: time gained or lost along the
lap, a map coloured by where the time went, and per-corner detail. Laps that cannot be fairly compared (different
car, track, wet or dry, or assists) are refused; smaller differences such as tyre compound or fuel give a warning.
This screenshot uses the light theme.

### Coaching

![Review › Coaching plan](screenshots/10-review-coaching-plan.png)

The coaching plan for a driver, track and car: the corners to work on now with their trend over sessions, habits
that repeat, and what the radio will focus on.

### Progress

![Review › Progress](screenshots/11-review-progress.png)

Progress at one track and car: the personal best, sessions and clean laps, and how the time lost at each corner
changed from session to session.

Coaching and Progress are the newest pages and have not been used after a live session yet.

### Ask

Ask the engineer about any session in plain words. The same question works from the terminal:
`uv run pitwall ask "Where am I losing time?"` (add `--no-llm` for the fact-based answer, `--show-facts` to see
the facts used). `uv run pitwall report` prints a Markdown report of the latest session.

## Setup

### Connect

![Setup › Connect](screenshots/12-setup-connect.png)

The exact in-game telemetry settings for each game, with copy buttons and this computer's address. It confirms when
packets arrive: who is sending, packets per second, decoded and rejected counts, and the capture being recorded.
This is also where Gran Turismo 7, Forza, Assetto Corsa and raw recording are switched on. The screenshot shows a
recorded capture streamed from the Mac itself to test port 20790 (in the game, use 20777), and is cropped above
the IP address row.

### Rig

![Setup › Rig](screenshots/13-setup-rig.png)

A walkthrough for the Fanatec GT DD Pro wheel base (5 Nm, or 8 Nm with the Boost Kit 180) and CSL pedals, for
F1 25 (PS5 or PC) and Gran Turismo 7 (PS5). Pick a style (Official, Balanced, Competitive, Realism or Comfort) and
go through the wheel's menu one item at a time. Each value shows the recommended setting, the factory default, how
well the sources agree, and whether it is verified, approximate, unverified, derived by Pitwall or a heuristic.
Lighter force for younger or newer drivers goes in their own slot.

The **rig check** reads your last session's telemetry (19 measures) to see whether the hardware reports what you
do. Its thresholds are heuristics from one rig, and the load-cell checks are unverified. Details:
[rig-setup.md](rig-setup.md).

### Car setup

![Setup › Car setup](screenshots/14-setup-car-setup.png)

F1 25 car setup recommendations built from a catalogue of 454 published setups (27 tracks for the 2025 cars, 24
for the 2026 Season Pack cars, never mixed). Choose the track, session, weather and driving style; each value shows
its confidence, and disagreements between sources are called out. You can compare your own setup with the
recommendation and try one change at a time. No recommended setup has yet been driven and checked by Pitwall.

## Settings

### Drivers

Profiles for everyone who shares the rig. The driver in the seat owns the session: their reference laps, personal
bests and coaching follow them, and the radio and braking calls switch with them. Switching driver during a live
session hands the seat over, splitting the session if laps were already driven (verified on synthetic streams
only). Each profile has a skill level (beginner, intermediate, advanced) and a coaching intensity (quiet, normal,
detailed); see [below](#how-the-coach-decides-what-to-say).

### Radio & voice

![Settings › Radio & voice](screenshots/15-settings-radio-voice.png)

Who speaks (the computer or the iPad's own voice), which voice, the speaking speed, the braking calls mode and how
much coaching the engineer gives. The computer speaks with the macOS voices or the optional natural voice on a Mac,
and with Windows' built-in voices on Windows.

### AI engineer

Off, Local or Cloud, with a model per purpose (a capable one for the dashboard, a fast one for the radio) and an
optional fallback. Cloud stays off until you accept the privacy notice. See [The AI engineer](#the-ai-engineer).

### Display

Theme, keeping Drive dark, Drive text size, night dimming, a colour-vision mode (green becomes blue, red becomes
orange), fading the navigation while you drive, and the Drive lock (hold for half a second to leave Drive while
driving; on for beginners by default).

### System

Server health, the model server, your captures with Replay buttons, the synthetic demo, the game support matrix
with its evidence, and the version.

## How the coach decides what to say

Everything here is fixed rules applied to your telemetry. No language model is involved.

1. **Clean laps only.** Laps with a flashback, a pit stop, missing packets or a game-declared invalid lap are kept
   but never used as a reference or to learn the track.
2. **Your own reference.** Each lap is compared with your fastest compatible clean lap: same game, track, car,
   wet or dry, and assists.
3. **By distance, not time.** Both laps are resampled to a 1 m grid by lap distance, so the delta is known at every
   metre. Corners are found where speed drops on the median of your clean laps, and the lap is split into segments
   around them, so the corner deltas add up to the lap delta.
4. **Measured differences only.** For each corner Pitwall measures the braking point, time to peak brake, release,
   trail braking, coasting, minimum speed, exit speed and throttle pick-up. A rule fires only when the corner lost
   time (at least 0.02 s) and the difference is clearly bigger than the measurement can resolve: for example a
   braking point 8 m away from the reference, or 4 km/h at the apex.
5. **Ranked by what it costs you.** Priority is time lost multiplied by confidence, with a boost for habits that
   repeat over recent laps. Confidence (how clear the measurement is) and consistency (how often it happens) are
   reported separately.
6. **Never "brake later".** Braking later than your reference is called over-driving when it costs exit speed;
   praise is only for a faster exit that gained time. Braking cues err early: a cue that would land after your
   reference braking point is dropped rather than said late, and no cue is given when you arrive faster than on
   the reference lap.
7. **Incidents are not technique.** A corner that cost 2 s or more, or an apex below half the reference speed, is
   treated as a spin, contact or slow-down. It is mentioned once and never coached.
8. **Matched to the driver.** The skill level sets the floors and the rules allowed. A beginner hears at most one
   point a lap, only when the measurement confidence is at least 0.75 and the corner is worth 0.1 s, only about
   the braking point, apex speed and throttle, in simple words, and with a lap's grace before the same corner
   again. Intensity sets how
   many points a lap: quiet gives none (the screen still shows them), normal one, detailed up to three.
9. **One message, two channels.** The point the radio says about a corner is the point the Coach screen shows for
   it. This is tested on synthetic and recorded data; it has not yet been seen in a live session.

## How the race engineer makes strategy calls

Everything here is deterministic (no language model) and runs on its own thread, so it never slows telemetry. It
uses only F1 25 data: every car's position, gaps and pit status (twice a second), your car's fuel, tyre wear and
lap times, the game's tyre sets and forecast, and the safety-car state. Other games show no strategy tile and keep
the per-lap fuel and tyre answers.

- **Gaps.** A gap is shown only once it has *settled*: for 4 s nothing changed (your position, the car next to you,
  its pit status) and neither car is in the pit lane. The game reports the old car's gap for about two seconds after
  an overtake and nonsense while a car is in the pit lane, so unsettled values are never shown as new. The trend is
  the gap at the line over the last three to five laps against the same car.
- **Tyres and the pit window.** Wear per lap is measured over your current stint only (a stop starts a new one) and
  shown with a range, because the game reports wear in whole percent. The window closes at the earlier of that
  projection to 70 % wear and the game's own laps-left figure, opens when a new set reaches the flag, and the
  best lap comes from the game's tyre model (how much faster a new set is, and how fast that grows).
- **Pit loss.** Measured from this race's own stops, any car's: the in-lap and out-lap against that car's pace
  before the stop. A long stop (repair), a penalty, a stop with no clean lap before it, or one with the safety car
  or VSC on only some of its laps (the other cars' laps are then no fair reference) is left out, with the reason.
  Under a safety car or VSC a measured stop is used if there is one; otherwise the green loss is halved (VSC 0.6),
  a rule of thumb shown as an estimate.
- **Undercut.** A new set's gain per lap (the game's tyre model, else the field's measured stops): the undercut on
  the car ahead is likely below 70 % of that gain, marginal up to it. Where you rejoin if you box now comes from
  everyone's gap to the leader plus the pit loss, next to the game's own estimate.
- **Fuel.** Fuel per lap is the median of your clean laps; the margin is what the tank lasts against the laps left,
  shown next to the game's own figure. When you are short, lift and coast is worked out from a model of fuel burn
  against throttle fitted on your own driving: so many seconds of lift a lap, *before* your braking point, braking
  at the same point. The engineer never tells you to brake later.
- **Weather.** The game's forecast for this session; a change counts once two forecasts in a row agree, and the
  rain percentage is the game's number, not a probability.

| Call | When | Level |
|---|---|---|
| Safety car / VSC: pitting this lap (or next) is an option | a stop is needed soon or a new set reaches the flag; once per period; "this lap" only once a stop in this race has shown where the pit entry is | alert |
| Safety car: no stop needed | the tyres reach the flag | normal |
| Fuel critical / tight | at the line, margin below -0.05 / 0.3 laps after two clean laps | alert / normal |
| Pit window open, last laps of the window | the window opens; the lap before it closes; once per stint (again only if the window moves three laps earlier); says so when it is the game's tyre figure, and waits three laps after a stop when only that figure closes the window | normal / alert |
| Car behind is pitting: cover the undercut | the car behind enters the pit lane while your window is open | normal |
| Rain forecast / dry forecast | a change to rain (or dry) within 15 minutes, before the flag | alert / normal |
| Car behind is within a second (DRS) | it comes within a second; once per car per ten laps | detailed |
| Undercut looks on, a car ahead pitting, gap trends | experienced drivers, detailed setting | detailed |

At most one normal and two detailed calls a lap; nothing on lap 1 (except the safety car and critical fuel), on your
final lap (a lapped car's race ends a lap early: the laps left count that), in the pit lane, on a formation lap or
under a red flag, and nothing about the gaps under a safety car or VSC. Evidence: gaps, fuel, tyre wear, the game's tyre
sets, the forecast and other cars' pit stops are checked on real PS5 races (committed excerpts, and a full-distance
Austria race by `scripts/strategy_check.py`); safety car, VSC, rain, the inters crossover and your own stop are
synthetic only (`race-strategy-demo`). Nothing is validated live yet.

## The AI engineer

The engineer turns Pitwall's facts into conversation. It never sees raw telemetry. For each question Pitwall picks
the relevant facts from the stored session analysis, numbers them, and sends them with the question. Any fact the
answer cites must exist, and every number in it must be a rounding of a number in the cited facts (or in the facts
it was given, if it cites none). An answer that fails gets one retry; after that, Pitwall answers from the facts
itself. Commands such as "stop talking" never go to the model.

It works with a local model (llama.cpp, LM Studio, Ollama, MLX or any OpenAI-compatible server) or a cloud model
(Anthropic Claude, OpenAI, OpenRouter, Google Gemini, Groq, Mistral or another OpenAI-compatible service). Cloud
calls send only the fact sheet, the question (as text, never audio) and your last few exchanges; driver names are
replaced with "the driver", and you can set a daily budget. Cloud providers are tested against mock servers only.
Details: [llm-providers.md](llm-providers.md).

## The classic dashboard

The classic dashboard (`web/`) is what you get when you build Pitwall from source without a HeroUI Pro licence
(releases include the new dashboard, prebuilt). It is served automatically when the new dashboard is not built and
receives fixes only.

| Classic tab | Closest page in the new dashboard |
|---|---|
| Live | Drive › Car: car, timing, track, tyres, fuel, inputs, coaching and laps on one page (no Coach screen or session cards) |
| Sessions | Review › Sessions and the session tabs |
| Engineer | Review › Ask |
| Radio | Drive › Radio and Settings › Radio & voice |
| Setup | Setup › Rig, including the rig check |
| Car setup | Setup › Car setup |
| Drivers | Settings › Drivers |
| Connect | Setup › Connect |
| Settings | Settings › AI engineer |
| Status | Settings › System |

There is no classic equivalent of Review › Coaching or Review › Progress, and the classic Settings › Display
equivalent is only a light/dark toggle.
