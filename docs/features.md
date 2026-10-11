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
- [Pace against the AI](#pace-against-the-ai)

- [How the race engineer makes strategy calls](#how-the-race-engineer-makes-strategy-calls)
- [The AI engineer](#the-ai-engineer)
- [The classic dashboard](#the-classic-dashboard)

## Drive

Drive is the screen next to your wheel. It reads only live telemetry and the radio, so it works with no language
model at all. Values Pitwall does not know show as `-`, and synthetic data is labelled.

**What your game sends.** A `-` means "not known right now": the value has not arrived yet. Data the game never
sends is different, and once Pitwall knows the game ([Setup › Game](#game)) the screens say so in words where a
whole slot is missing: for example the sector cells read "Sectors · Not sent by GT7" in Gran Turismo 7, the Car
page names the tyre, fuel and ERS data your game does not send (or Pitwall does not read yet), and the delta is
marked "estimated" where Pitwall works out the lap distance itself. The words describe the data on screen: the game
that is sending right now, else the one you selected. Drive stays glanceable, with no banners: if a different game
than the one you selected is sending, the status line says so only while the car is stationary, and the other pages
show an alert with a button to switch.

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

**Goals on Drive.** While you drive, a reached goal shows only as a 6-second `GOAL REACHED` chip in the status band
(an incident chip wins over it); nothing else moves on track. The Ready card between runs shows one goal with its
progress bar (a goal reached this session first, then a lap-time goal for this track), and the Session complete
card shows [Today's 3 things](#todays-3-things) and up to two new badges. No animation and no sound.

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

The engineer knows what your game sends. Ask about data the game does not send, or that Pitwall does not read yet,
and the answer comes at once from that fact, never from the language model and never as an estimate: in Assetto
Corsa, "how are my tyres?" gets "Assetto Corsa doesn't send tyre temperatures, tyre wear, tyre pressures or brake
temperatures." This works before any session is recorded, from the selected game; with no game selected or
detected, the radio asks you to choose one on Setup › Game.

When you reach a goal the engineer says one short line after that lap's summary and before its coaching point:
"Goal reached: a lap under 1:10 at Austria." (beginners hear "You did it: ..."). It follows the same rules as a
lap summary: never at quiet intensity, during "stop talking" or with the radio off, only in a calm part of the lap,
and a newer lap's summary replaces it if it was not said in time. At most two goal lines per session; a race goal
is said after the flag. "How am I doing on my goal?" is answered from the facts, with or without a language model.

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

<!-- feat/technique -->
### Technique: racing line, brake and throttle, handling balance

Everything here compares you with **your own reference lap**, never with an "ideal" line: Pitwall does not know the
track edges, so the maps show where each lap went.

- **Compare** adds a technique card for the two laps: both lines on a map (zoom to any corner at true scale, with
  numbered markers at the biggest differences, e.g. "T3 apex: 1.5 m wider than your reference"), a chart of how far
  you were tighter (+) or wider (-) through the focused corner, a table of your inputs against the reference
  (brake peak and time to peak, how you released the brake, brake still on at turn-in, trail braking, coasting,
  throttle pick-up, the ramp to full throttle and lifts, lock-ups and wheelspin) and how the car handled on entry,
  mid-corner and exit.
- **Corners** adds a "Line, inputs and balance" section to each corner card: the line at turn-in, apex and track-out
  over the session, habits that repeat ("on 3 of 4 laps"), lock-up and wheelspin counts, and the handling chips.
- Notes describe what happened; they never tell you to brake later or earlier.
- Brake differences take your pedals into account: a stock CSL brake measures pedal travel, so only bigger
  differences are called out; a load cell shows finer ones. With the game's braking assist on, brake notes are
  greyed out (the game adds its own braking); with ABS on, lock-ups are not analysed.
- Handling balance (F1 25 only: it needs the game's tyre slip data) compares the front and rear tyres' slip angles
  at the limit. A problem must recur, and it counts as the car's only if it also shows on your best lap that
  session; otherwise it points at how the corner was driven. The thresholds are Pitwall's heuristics and the
  "How this is measured" sheet lists them.
- `uv run pitwall technique [SESSION_ID|latest] [--ref LAP_ID] [--car-format f1_2025|f1_2026] [--json]` prints the
  same analysis in the terminal.

Evidence: racing line and brake/throttle are tested on recorded F1 (PS5) laps, and the line on a GT7 capture;
balance and wheelspin on recorded F1 tyre slip data; lock-ups on synthetic data only (every real capture had ABS
on). Nothing has been checked during a live session yet.
<!-- /feat/technique -->

### Coaching

![Review › Coaching plan](screenshots/10-review-coaching-plan.png)

The coaching plan for a driver, track and car: the corners to work on now with their trend over sessions, habits
that repeat, and what the radio will focus on.

### Progress

![Review › Progress](screenshots/11-review-progress.png)

Progress at one track and car: the personal best, sessions and clean laps, and how the time lost at each corner
changed from session to session.

Coaching and Progress are the newest pages and have not been used after a live session yet.

### Today's 3 things

Every session's Summary (and Drive's Session complete card) starts with three short points: **one thing that went
well**, **one to work on** and **one piece of progress**. They are picked by fixed rules, never by a language model:

- *Went well*: a new personal best, else the strongest positive coaching point, a run of 3 or more clean laps, getting
  0.1 s or more faster from your first clean lap to your best, or every lap clean.
- *One to work on*: the coaching point that cost the most over the session (the coach's own words, simpler for
  beginners), else laps that did not count, no clean lap, or a single clean lap.
- *Progress*: a goal reached, new bests in two or more sessions in a row, a goal you moved closer to, the gap to
  your best here, your first clean laps at a track, or how many sessions you have driven this week.

Progress is worked out as it was at the end of that session, so a later session never changes it. Synthetic
sessions, replays and sessions with no driver profile get no progress point. Terminal: `uv run pitwall recap`.

### Goals

Each driver can have up to six active goals of four kinds: **a lap time** (a clean lap under a target, at one track
in one car or any car of the same class), **clean laps in a row** (2 to 50), **steady laps** (3, 5 or 10 clean laps
in a row within a spread, 0.1 to 10 s) and **a clean race** (an F1 race from lap 1 to the flag with no penalties, or
without touching another car either). Only laps driven after the goal was set count, and only your own real driving:
replays and synthetic sessions never do.

Pitwall suggests goals from your own history, with the reason shown: the best sectors you have driven added
together, your recent improvement, your best run of clean laps, your steadiest laps and your recent races. Nothing
is invented. A goal is marked reached once, after the lap that reached it, and stays reached; if that session is
later moved to another driver, the goal can be reopened.

Limits, shown in the dashboard: race goals work in F1 only (other games send no session type or penalties) and only
for races recorded from this version on (the race length is stored from schema v3). GT7, Assetto Corsa and Forza do
not report track limits, so there "clean" means no pit lap, reset or flashback. Terminal: `uv run pitwall goals
--suggest`.

### Badges and streaks

Badges are earned by your own driving and worked out from it, so they always match the laps: your first clean lap
at a track, your first time under a whole second at a track and car (between sessions, never within one), 3, 5, 10
and 20 clean laps in a row, 10 clean laps in one session, new bests in 2, 3 and 5 sessions in a row, 2, 4, 8 and 12
weeks in a row with a session (Monday to Sunday), 3 and 5 sessions in one week, a race with no penalties or without
contact, and 1, 3 and 10 goals reached. Streaks show weeks in a row, sessions this week, your best run of clean
laps and your new-best streaks.

### Weekly digest

One page per driver per week: sessions, laps and clean laps against the week before, the biggest improvements
and first laps at new tracks, goals reached and how far the others moved, badges and streaks. **Printable page**
opens a plain A4 page made on this computer, and **Copy as text** copies the same as Markdown for a message.
Nothing is sent anywhere. Terminal: `uv run pitwall digest [--week 2026-10-05] [--html week.html]`.

Goals, badges, recaps and the digest are tested on synthetic sessions and on real F1 25 PS5 captures replayed in a
scratch database; they have not been used after a live session yet.

### Ask

Ask the engineer about any session in plain words. The same question works from the terminal:
`uv run pitwall ask "Where am I losing time?"` (add `--no-llm` for the fact-based answer, `--show-facts` to see
the facts used). `uv run pitwall report` prints a Markdown report of the latest session.

## Setup

### Game

Tell Pitwall what you play: pick the game, then the platform (PS5, PS4, Xbox or PC). The main list has F1 25 (with
a switch for the 2026 Season Pack cars), Gran Turismo 7, Assetto Corsa, Forza Motorsport, Forza Horizon and
"Another game". Assetto Corsa Competizione, iRacing and F1 24 or older are under *More games*, so you can say you
play them even though Pitwall cannot read them. Each platform shows its support in the words of the
[supported games](../README.md#supported-games) table.

Choosing a game switches on its telemetry input and asks for the console's IP address where the game needs one
(required for Assetto Corsa). Gran Turismo 7's input is switched on once you enter the console's IP; without one it
would search your whole network for the console, so that happens only when you press *Search the network* (and
confirm). It never switches another game's input off, and it leaves alone an
input that is receiving packets at that moment. The choice is kept for the whole rig and survives restarts. A
driver can also have a usual game (Settings › Drivers › Edit › *Usually plays*): it is selected when that driver
takes the seat, unless a game is sending telemetry at that moment.

**What the game sends** lists Pitwall's features in six groups (timing, coaching, track, car and tyres, session and
race, setup and radio). Each is marked Supported, Estimated, Partial, Not sent, Not in Pitwall yet or Unknown, with
one sentence why; tap a row for the technical source. The marks come from the support matrix in
`src/pitwall/capabilities.py` and from what each game's decoder declares field by field, and are never stronger than
either. Some are cautious as a result: F1 25 on PS5 is tested live as a whole, but most of its features are rated
"Built from the official spec" until each has its own evidence.

The rest of Pitwall follows the choice. Setup › Connect lists your game first, the Rig walkthrough opens on it, Car
setup says when its recommendations are for F1 25 only, and Drive › Coach without telemetry shows that game's steps
(or asks what you are playing when nothing is chosen). Review uses each session's own game: a GT7 session has no
sector columns. When nothing is chosen and telemetry arrives, Pitwall suggests the game it sees, or the one you last
drove; it never chooses for you.

From the terminal: `uv run pitwall game list` (`--all` for every game), `uv run pitwall game show [<id>]`,
`uv run pitwall game set <id> [--console-ip <ip>]` and `uv run pitwall game clear`. Ids look like `gt7:ps5`;
[install.md](install.md#tell-pitwall-what-you-play) lists them.

Evidence: the selection, the feature lists and the game detection are tested with unit tests, synthetic streams and
the recorded F1 25 (PS5) and Assetto Corsa (PS5) excerpts. Selecting GT7, Forza or Assetto Corsa has not yet been
tried with a live console, and the page has not been used on an iPad.

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

<!-- feat/technique -->
**How the car handled** (session view): the handling symptoms that recur and also show on your best lap, with the
corners and laps, and a setup change to try for each, e.g. "Front Anti-Roll Bar 9 → 7". Each suggestion changes one
parameter by a small step from your stored setup and opens the experiment form, already filled in, with **Try
this**; after your next session the experiment's result also says how the balance moved. Symptoms that did not
show on your best lap are listed as driving points, without setup suggestions. Tyre pressures, camber, toe and ride
heights are never suggested. A setup change is something to try, not a guaranteed fix. Setup suggestions are for
F1 25 only and have not been driven and checked yet.
<!-- /feat/technique -->

### Validation
<!-- validation kit (lane validate) -->
A checklist of the live tests still pending on the rig (PS5, wheel, iPad at the wheel, one AirPod), for when you
are in the seat with the game running. Each test says why it matters, what to do step by step, and how it is
measured. While you drive, Pitwall collects evidence by itself (braking calls and your braking points, radio
messages against your brake and steering, push-to-talk round trips, the iPad's screen and wake lock, laps and
sessions of each game); you then tap **Worked** or **Didn't work**, tick what you checked and add a note.

- **Evidence tiers:** a test can only pass on live data from the console. Replays, synthetic streams and recordings
  sent from the Mac itself are shown but never count.
- **Results:** each test combines Pitwall's verdict with yours; when they disagree it says "to check". The
  thresholds that are first guesses are marked heuristic.
- **Radio commands** (optional): "start validation", then during a run "next test", "worked", "didn't work",
  "what's the test" and "finish validation" (with no run active the radio answers those words as usual). The radio
  can also say each test's brief in a calm moment (on by default, never into a braking zone, never in quiet mode).
- **Reports** are saved on the Mac (`data/validation/`) as JSON and Markdown; review them with `pitwall validate list`,
  `show` or `report`. They never change what Pitwall claims to support: the maintainer updates that by hand.
- **Privacy:** reports keep device facts only (no IP addresses, no microphone names, no driver names: "Driver #2").
  Your push-to-talk transcripts are included; "Leave out transcripts" on the report (on by default),
  `--redact-transcripts` or `?redact_transcripts=true` removes them.
<!-- end validation kit -->

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

<!-- --- lane install --- -->
**Updates.** Whether a newer Pitwall is out, what changed in it, and the one command that updates this computer
(`uv run pitwall update`, or the git steps in a git checkout), with a "Check now" button. While the page is open,
Pitwall asks GitHub at most once a day, never while someone is driving (`PITWALL_UPDATE_CHECK=auto`; `manual` or `off`
in `.env`). The page never
updates anything itself: updating replaces the server's own files, so it is always done in a terminal on the computer
running Pitwall. Drive never shows any of this.
<!-- --- end lane install --- -->

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

## Pace against the AI

F1 25 only. After a race, qualifying or practice session against the game's AI, Pitwall compares your best clean lap
with the typical AI car's best lap at the AI difficulty you raced. It uses only the game's own telemetry: every
car's lap list (the Session History packet) and the AI difficulty in the Session packet. No website data.

- **The typical AI car** is the median of the AI cars' best laps. An AI lap counts only when it was a normal flying
  lap the AI drove, seen from its start: not race lap 1, not a pit in- or out-lap, not under a safety car, VSC or red
  flag, not around a flashback, valid in the game, and timed consistently. When you skip to the results, F1 25
  finishes the other cars where they are and fills in their laps in progress: those times were never driven, so
  they are left out. Human opponents are never used, and neither are the laps a human drove before the game's AI
  took their car over (an online player leaving).
- **Nothing is guessed.** Pitwall needs a known AI difficulty (the game reports it a moment after the session starts)
  and clean laps from at least 5 AI cars; otherwise it says why there is no comparison, and Progress says a race
  there could not be compared rather than that there was none. A difficulty that changed during the session, even
  for its last minute, gives no comparison either.
- **Where it shows:** a "Pace vs AI" tile on Review › Session › Summary (the gap in words, your rank on best laps and
  each AI car's best lap), "Against the AI" on Review › Progress (each session at the track as a dot labelled with
  its AI difficulty), "Suggested AI difficulty" on Review › Coaching, and one line on Drive's Session complete card.
  Ask the engineer or the radio "how am I doing against the AI?", "what AI level should I use?" or "is the AI too
  hard?": the answers come from the stored facts, never from a language model. A parent viewing a child's pages
  reads the sentences about the child ("Sam's best lap"), not "your".
- **Suggested level.** Kept per track, car class (F1, F2, ...), session type and dry or wet. Once you have raced at
  two levels at least 5 apart at a track, Pitwall fits how the gap changes with the level and suggests the level
  where you would be level with the typical AI car, with a range and a confidence (a level beyond what your races
  support is an "or higher" / "or lower" bound, without a range). With one level raced, it borrows how the gap
  changed with the level at your other tracks and gives a rough estimate. With nothing to borrow from, it says
  whether to go up or down and which level to race next (five away, so a level can be measured). The same level can
  mean very different pace at different tracks, which is why nothing is shared between tracks except that slope.
- **Evidence:** recorded (six PS5 F1 25 sessions, exact to the millisecond) and synthetic, and the dashboard in a
  desktop browser. Not yet seen live through the service, never with a real safety car, and every track the owner
  has raced so far has a single AI level, so real suggestions are direction only for now. Older sessions have no AI
  data unless `pitwall ai-pace backfill --captures DIR` finds their raw captures.

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

<!-- feat/technique -->
The engineer also answers questions about your line ("how's my line through turn 3"), your technique ("am I locking
up", "trail braking at T5", "wheelspin") and the car's balance ("I've got understeer in turn 3"). These answers come
straight from the facts, so the radio gives them at once, without the AI model.
<!-- /feat/technique -->

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

There is no classic equivalent of Setup › Game, Review › Coaching or Review › Progress, and the classic
Settings › Display equivalent is only a light/dark toggle. The classic screens do not change with the chosen game: with the
classic dashboard, choose the game with `uv run pitwall game set <id>` (the engineer and the radio use it either
way).
