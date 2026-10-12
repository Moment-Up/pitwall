# Changelog

What changed in each Pitwall release, newest first. Each release has a `## vX.Y.Z - YYYY-MM-DD` section of short
bullet points written for drivers, not developers. Changes waiting for the next release go under `## Unreleased`;
when a release is cut, that heading becomes the release's own (see [docs/releasing.md](docs/releasing.md)).

The release workflow copies a release's bullet points into its GitHub release notes under "What changed"
(`scripts/changelog_section.py`), and `pitwall update` and Settings › System show them before you update.

## Unreleased

- Race radio: flags and race control in a race, the red flag at once even in quiet mode. Tested on recordings (F1 25,
  PS5); safety car, VSC and red flag on synthetic data only.
- Race radio: your grid slot, lights out, laps to go, the last lap and the finish. Tested on recordings of F1 25 and
  GT7 races.
- Race radio: your position after lap one, places gained or lost, clean passes and gaps every three laps. Tested on
  recordings; GT7 positions not yet checked against its screen.
- Race radio: penalties and warnings with the reason, car damage and punctures (F1 25). Tested on recordings;
  punctures, stop-go and disqualification on synthetic data only.
- Race calls have their own allowance (two a lap at normal), so they never push out the lap summary. Not yet heard
  live.
- Settings › Drivers: switch race radio groups off and choose Automatic, Simple or Standard words. Other cars are
  named by AI driver, team or number, never an online ID.
- Ask "who's ahead?", "do I have a penalty?", "what's my damage?" or "how was sector 2?"; "what position am I?" now
  works in GT7 too.
- The radio sometimes uses your first name ("Up to P5, Sam."), at most once a minute.

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
