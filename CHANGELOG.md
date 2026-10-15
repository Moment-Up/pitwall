# Changelog

What changed in each Pitwall release, newest first. Each release has a `## vX.Y.Z - YYYY-MM-DD` section of short
bullet points written for drivers, not developers. Changes waiting for the next release go under `## Unreleased`;
when a release is cut, that heading becomes the release's own (see [docs/releasing.md](docs/releasing.md)).

The release workflow copies a release's bullet points into its GitHub release notes under "What changed"
(`scripts/changelog_section.py`), and `pitwall update` and Settings › System show them before you update.

## Unreleased

- The radio coaches habits, not every corner: one at a time (two at Detailed), said once, then when it gets better,
  is still there 5 laps on, or is sorted. Synthetic and recorded laps; not live.
- A habit is said only when it costs 0.05 s a lap or more; pit, out, safety-car, flashback and invalid laps never
  count as habits. Synthetic and recorded laps; not live.
- A single lap's slip is said on the radio only when it cost 0.3 s or more; smaller ones stay on the Drive screen.
  Synthetic and recorded laps; not yet live.
- "Better" compares laps against the same reference, and for braking early needs a faster corner. Tested on
  synthetic laps.
- "Sorted" needs 2 of the corner's last 3 laps clean, and for braking early a faster corner. A new personal best no
  longer wipes the radio's memory of your habits. Tested on synthetic laps.
- Braking calls (Focus) follow your habits, with a corner reminder ("Turn 6, apex speed, 12 down") ending a second
  before braking; it never cuts the spotter. Synthetic and recorded laps; not live.
- Drive: the coach card says what a note is (Habit · 3 of 4 laps, Focus, Once, Sorted); between runs the Ready card
  says what the radio is working on. Checked in a desktop browser, not yet on an iPad.
- Today's 3 things: One to work on is a habit that is still there (else a big one-off), and a habit you sorted counts
  as went well. Tested on synthetic and recorded sessions.
- The demo (Try a demo replay) now shows the habits story in 10 laps: a habit announced, called and sorted, then a
  reminder for the next one. Settings › System lists what to look for. Synthetic.
- A habit the radio announces gets its corner reminder on the lap you hear it, not one lap later. Tested on synthetic
  laps; not live.
- Family records: everyone's best lap per track, car, session type, weather and assists, with the gaps and who held
  the record when. Stays on this computer. Unit tests and real laps; not live.
- The badge "Family record at <track>" for holding the family record when someone else drives there too. Tested on
  unit tests.
- Ask the engineer "What's the family record here?"; when a lap takes the record from another driver the radio says
  so in one short line. Tested on unit tests; not heard live.
- Lap cards: a lap in a small, versioned format for a possible online board later; built locally, never sent.

## v0.3.0 - 2026-10-13

- Setup › Controls: which button does what, for any wheel and any game. Not yet tested on the rig: research only.
- Wheels: 23 researched wheels, rims and button boxes (Fanatec, Logitech, Thrustmaster, MOZA, Simagic, Simucube,
  Cammus), or build your own. Research only.
- Games: 11 researched games or "Other game". Each button gets a reason, steps to map it in the game and a card to
  print. Research only.
- Setup › Controls lists what a game won't let you change while driving: ride height in any game, GT7's ASM and ABS,
  F1 25's TC and ABS. Research only.
- F1 25: Setup › Controls › Test checks your UDP Action buttons and a brake bias change; Identify shows what each
  control sends. Other games don't send button presses. Tested on recordings, not live.
- Radio push-to-talk follows your saved F1 25 layout without a restart (UDP Action 1 keeps working). Tested on
  synthetic data, not live.
- Ask the engineer "which button is brake bias?": it answers from your saved layout. Tested on synthetic data.
- F1 25 on a Logitech G923 starts from EA's own default buttons and only adds what is missing. Research only.
- Setup › Controls asks you to pick your wheel (brands first, or search) instead of assuming a Fanatec, and asks you
  to place the controls of a wheel the research has no drawing for. Research only.
- F1 25 recognises F2 cars: an "F2" chip on Drive (phones too), the car by name ("F2 · Art GP '24") and the "Sprint
  race" and "Feature race". Tested on recordings of PS5 F2 sessions; not yet live.
- One-shot qualifying no longer stores your lap twice or an empty second lap; those already stored are removed once
  at start and their corners rebuilt. Tested on recordings and a copy of the database.
- Drive shows a track's learned corners from the start of a session, not only after your first lap, so one-shot
  qualifying gets them too. Tested with unit tests.
- F2 cars have no ERS: Drive shows none and the engineer says so. DRS questions get a DRS answer, and an open flap is
  said to be open. Tested on recordings.
- The engineer never says a pit stop is not mandatory (F1 25 doesn't send the rules); "Do I need to pit?" still gets
  the strategy answer. Tested on recordings.
- Car setups for the F2 car: F2 ranges and cited community setups (author, link, source, notes) for 5 tracks;
  elsewhere "No F2 setups for this track in Pitwall yet". Ranges not yet checked in the game.
- Learned corners, the heavy-stop warning and "Your best here" are kept apart for F1 and F2 cars. Tested on
  recordings.
- Setup › Game lists the car classes and how each was tested: F2 on recordings, F1 live.
- Race radio: flags and race control in a race, the red flag at once even in quiet mode. Tested on recordings (F1 25,
  PS5); safety car, VSC and red flag on synthetic data only.
- Race radio: your grid slot, lights out, laps to go, the last lap and the finish. Tested on recordings of F1 25 and
  GT7 races.
- Race radio: your position after lap one, places gained or lost, clean passes and gaps every three laps. Tested on
  recordings; GT7 positions not yet checked against its screen.
- Race radio: penalties and warnings with the reason, car damage and punctures (F1 25). Tested on recordings;
  punctures, stop-go and disqualification on synthetic data only.
- The radio speaks as one engineer: at most 3 messages a lap at normal and 5 at detailed, from every source together;
  alerts never wait. Measured on recorded races, not yet heard live.
- Only the spotter, a red flag and a puncture cut in. A braking call no longer cuts the lap time, which was then said
  twice. Measured on recorded races, not yet heard live.
- Before a track is learned (your first clean lap), the radio also keeps clear of where you braked on your last laps.
  Measured on recorded races, not yet heard live.
- News at the line rides in the lap time ("That lap, 1:25.4, personal best. Fastest lap of the race.") and the
  safety car is announced once. Tested on recordings and synthetic data.
- Settings › Radio & voice: every call family in one place (race calls, car health, spotter, hands-free) and "What
  the radio says", the radio's rules as the code has them.
- Race radio words: Automatic, Simple or Standard per driver in Settings › Drivers. Other cars are named by AI
  driver, team or number, never an online ID.
- Ask "who's ahead?", "do I have a penalty?", "what's my damage?" or "how was sector 2?"; "what position am I?" now
  works in GT7 too.
- The radio sometimes uses your first name ("Up to P5, Sam."), at most once a minute.
- Car health: the radio says new tyres are cold after a stop (in the pit lane) and when they are warm again. Tested
  on recordings of two F2 stops on PS5; not yet heard live.
- Car health on Drive: tyre temperatures against your own warm laps, brake and engine temperatures, and lock-ups and
  wheelspin per lap (F1 25). Recorded values; the "hot" band is not yet checked.
- Ask "how's the car?", "how are my brakes?" or "is the engine OK?": the answer is about that part, never the tyres
  instead. Not yet asked live.
- F1 races: ask "where will I come out if I pit now?"; Drive shows "Box now ≈ P7 (P6–8)" near the pit window, under
  a safety car and in the pit lane. Tested on a recorded Imola race.
- F1 races: ask "where can I pass?" or "am I under attack?" for the corner where you, or the car behind, is quicker.
  Tested on recordings.
- Forza: laps of fuel from how fast the tank level falls (synthetic data only). GT7 fuel stays off until a recording
  shows it going down.
- Settings › Radio & voice: Car health calls, for the whole household (tyre temperature, tyre wear, fuel, and the
  lock-up and wheelspin notes).
- Radio: hands-free talking. Say "Pitwall" or "Radio", then your question. Off until you turn it on; only while
  stopped unless the driver allows it while driving. Not yet tried with a real voice.
- Radio: a Bluetooth page turner, foot pedal or game controller can be your talk button (Settings › Radio & voice),
  held or tapped. Not yet tested on an iPad.
- Windows: spoken questions work with built-in speech recognition (Parakeet via sherpa-onnx), downloaded on first
  run with its progress shown. Not yet run on a Windows PC.
- Spotter (F1 25, off by default): "Car left.", "Clear left.", "Three wide." on the radio, and amber bars at the
  edges of Drive on the iPad. Tested on 26 recorded PS5 races; not yet heard on track.
- Settings › Radio & voice › Spotter: switch it on, pick its words and voice, choose sessions and test it. Set the
  game's UDP send rate to 60 Hz.
- Spotter calls and the red flag cut in over anything but each other; every other message waits for a calm moment
  and its share of the lap. Tested with unit tests and recordings; not yet heard live.

## v0.2.1 - 2026-10-12

- Gran Turismo 7 on PS5 is tested live (the owner's races on 2026-10-11, lap times equal to the game's). PS4 is
  still untested.
- GT7: one session per race. Menus, replays, loading screens and car resets no longer start sessions, and the empty
  ones already stored are hidden. Tested on recordings of those races.
- GT7: every lap the game times is kept, including race lap 1 (marked "race start") and laps around a car reset.
  Tested on recordings.
- GT7: leaving a race no longer shows the car still moving or adds a long fake lap; the session ends. Tested on
  recordings (a race left mid-spin: on synthetic data only).
- GT7: lap distance follows the car's velocity (within about 0.2 % per lap; the speed it used before fell up to
  1.5 % short on laps with an off). Tested on recordings.
- GT7: the throttle shown is your pedal, not the throttle after traction control. Tested on recordings.
- The README and install guide no longer say the one-line installer is unreleased.

## v0.2.0 - 2026-10-12

Each line ends with how it was tested: on recordings (real captures played back), on synthetic (generated) data, or
live on the rig. Nothing here has been tested live unless it says so.

- Tell Pitwall which game you play in Setup › Game: it says what that game sends, and each driver can have a usual
  game. Tested on recordings (F1 25) and synthetic GT7; not live with GT7, Forza or AC.
- Pace against the AI (F1 25): how your best lap compares with the AI cars, and a suggested AI difficulty for each
  track. Tested on recordings of PS5 races; not yet tested live.
- Technique (F1 25): your racing line, braking and throttle, and how the car handled, corner by corner. Tested on
  recordings; lock-ups only on synthetic data (every real recording had ABS on).
- A race engineer for F1 25 races: gaps, tyres, fuel, pit stops, safety car and weather, by radio and on Drive ›
  Car. Tested on recordings (a 71-lap race); safety car, VSC and rain synthetic only.
- Goals, streaks, badges and a weekly summary for every driver in Review › Goals, and three things after every
  session (also in the session report). Tested on recordings; not yet tested live.
- Badges only for tracks Pitwall can name and laps of 30 s or more, cars always by name; counts say what they count
  ("3 sessions with a timed lap"). Tested on recordings.
- Choose what the delta compares you with (your best, the family record or another driver's lap) and practise one
  corner with drills. Tested on recordings with a development script; not yet tested live.
- Test your rig with Setup › Validation and `pitwall validate`. Nothing passes until it is run live, by design.
- The radio talks less and in better places: at most two messages a lap at normal intensity, plus braking cues,
  safety alerts and your answers. Checked on recordings over loopback; not yet tested live.
- Questions asked while moving get an instant, short answer from the facts, never "Copy, checking", flags and safety
  car included. Tested on recordings and synthetic data; not yet tested live.
- The radio names the lap you just finished ("That lap", "Out-lap", "Final lap") and says "personal best" only when
  it is one. Tested on recordings; not yet heard live.
- On track, Drive shows only what helps at speed; the Ready and Session complete cards wait for the car to stop.
  Tested on recordings in a desktop browser at iPad sizes; not yet on an iPad.
- Install with one command on macOS, Linux or Windows; it checks the download and keeps your sessions in one data
  folder. Tested end to end on macOS; Linux and Windows through CI only.
- Update with `uv run pitwall update`: it shows what changed, backs up the database and never runs while someone is
  driving; `--rollback` goes back. Tested end to end on macOS; Windows through CI only.
- Settings › System says whether a newer version is out and how to update; Pitwall asks GitHub only when you press
  Check now (`PITWALL_UPDATE_CHECK`: manual, auto or off).
- A fresh install's first driver profile starts at the intermediate level; existing profiles keep theirs.
- `pitwall doctor` reports the last update check (it never contacts GitHub itself). Bug report and feature request
  forms, a security policy and contribution notes on GitHub.

## v0.1.0 - 2026-10-11

- First public release: a zip with the dashboard prebuilt (no Node.js or HeroUI Pro licence needed), checked on
  Windows, macOS and Linux before publishing.
- F1 25 telemetry tested live on a PS5; GT7, Forza and Assetto Corsa built from community documentation (see
  `uv run pitwall capabilities` for the evidence behind each).
- Deterministic coaching from your own reference lap, braking cues, the race-engineer radio and an optional
  language model that only rephrases checked facts.
