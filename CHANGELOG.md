# Changelog

What changed in each Pitwall release, newest first. Each release has a `## vX.Y.Z - YYYY-MM-DD` section of short
bullet points written for drivers, not developers. Changes waiting for the next release go under `## Unreleased`;
when a release is cut, that heading becomes the release's own (see [docs/releasing.md](docs/releasing.md)).

The release workflow copies a release's bullet points into its GitHub release notes under "What changed"
(`scripts/changelog_section.py`), and `pitwall update` and Settings › System show them before you update.

## Unreleased

- F1 25 recognises F2 cars: an "F2" chip on Drive, the car by name ("F2 · Art GP '24") and the "Sprint race" and
  "Feature race". Tested on recordings of PS5 F2 sessions; not yet live.
- One-shot qualifying no longer stores your lap twice; the extra laps already stored are removed once at start and
  their learned corners rebuilt. Tested on recordings and a copy of the database.
- F2 cars have no ERS: Drive shows none and the engineer says so. DRS questions now get a DRS answer. Tested on
  recordings.
- The engineer never says a pit stop is not mandatory: F1 25 doesn't send a race's stop rules, so Pitwall says they
  are unknown. Tested on recordings.
- Car setups for the F2 car: F2 ranges and cited community setups (author, link, source) for 5 tracks; elsewhere "No
  F2 setups for this track in Pitwall yet". Ranges not yet checked in the game.
- Learned corners, the heavy-stop warning and "Your best here" are kept apart for F1 and F2 cars. Tested on
  recordings.
- Setup › Game lists the car classes and how each was tested: F2 on recordings, F1 live.

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
