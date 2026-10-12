# Status

_Last updated: 2026-10-12 (v0.2.0: the nine features merged; nothing in this release has been run live on the rig
yet unless the Live column says so. After it: Gran Turismo 7 on the PS5, from the owner's races of 2026-10-11)._

What works, how far each part has been tested, and what is still unverified. Every claim is tied to one evidence
tier:

- **Synthetic**: generated telemetry with known, injected mistakes (`pytest -m synthetic`). Proves the algorithms.
- **Recorded**: real game output captured to a file and played back (committed excerpts in
  `tests/fixtures/recorded`, or the owner's captures replayed into a scratch database). Proves the decoders and the
  analysis cope with what the game really sends.
- **Live**: the real game on the real platform, end to end. Only live evidence upgrades a status to live - a run of
  the validation kit (Setup › Validation, `pitwall validate`) on the rig, or the owner's own sessions with their
  captures (F1 25 on 2026-10-10, GT7 on 2026-10-11) - and only by hand: `src/pitwall/capabilities.py` changes only
  with new evidence, written into the row with its date.

Merging the v0.2.0 lanes did not upgrade any tier; GT7 on the PS5 was upgraded after it (see
[below](#gran-turismo-7-on-the-ps5-2026-10-11)). The per-lane development notes (what was checked, on which
captures, with which numbers) are kept verbatim in [history.md](history.md).

## Verified vs unverified

One row per feature. "Next check" names the validation kit item that would give it live evidence; items marked
*(new)* are planned for the catalogue but not in it yet.

| Feature | Synthetic | Recorded | Live | Not yet verified | Next check |
|---|---|---|---|---|---|
| F1 25 telemetry, format 2025 (PS5) | yes | yes (Austria, Monza, Melbourne, Imola excerpts) | **yes** (Austria races, 2026-10-10: ~190k packets, 0 rejected, lap and sector times exact) | PC and Xbox (same spec, untested) | - |
| F1 25 2026 Season Pack (format 2026) | yes | no | no | everything beyond the spec | - |
| Coaching from your own reference lap (deterministic) | yes | yes | **yes** (coaching produced in the live races) | the radio and the card saying the same point, live | `ipad_one_message` |
| Live braking cues | yes | yes | no | timing on track | `cues_timing` |
| Radio: push-to-talk, speech recognition, voices | yes | yes | partly (a radio check over an iPad and one AirPod was heard; the F1 25 wheel button is read live) | a driver asking by push-to-talk; the new dashboard's Go live on an iPad; Kokoro and Windows voices on a radio | `radio_ptt`, `radio_kokoro` |
| Radio policy: speak windows, two (four) messages a lap, order, seat change | yes | yes (the v0.2.0 acceptance run, owner captures over loopback: at most 2 a lap at normal, every message in a calm stretch, the seat change; the 2 s gap after a held message failed there and is fixed since, unit-tested) | no | heard live on track | `radio_speak_windows`, `radio_budget` *(new)* |
| Engineer intents and instant answers while moving | yes (204-question fixture, every answer grounded and short enough for the radio) | yes (the acceptance run: every typed question on track got its intent, no "Copy, checking."; the long answers it found are shortened since, unit-tested) | no | asked by voice on track | `radio_ptt` |
| Lap naming on the radio and Drive ("That lap", "Out-lap", "Final lap") | yes | yes (Melbourne and Imola excerpts; 18 owner captures) | no | heard live; an out lap from the garage in practice; a pit-lane race start | `radio_speak_windows` |
| Drive at speed: moving or stopped, one status line, at most two chips, the cards | yes | yes (recorded snapshots; the Ready and Session complete cards measured with every slot filled, the reference control, goal row and drill blocks included, at 1180 x 820 and 1133 x 744 in a desktop browser) | no | on an iPad during a session | `ipad_glance` |
| Game selection and what each game sends | yes | yes (F1 25 and Assetto Corsa excerpts) | no | GT7, Forza or Assetto Corsa selected with a live console | `game_selection` |
| Driver profiles and seat changes | yes | yes | no | splitting a live session on a switch | `driver_switch` |
| Pace against the AI (F1 25) | yes | yes (six PS5 sessions, exact to the millisecond) | no | a real safety car; time trial and the 2026 format; a real "measured" level suggestion | `ai_pace_result` *(new)* |
| Technique: racing line, brake and throttle, handling balance, setup suggestions | yes | yes (F1 25 PS5 laps; the line on a GT7 capture) | no | lock-ups (every real capture had ABS on); a setup suggestion driven and checked | `technique_balance` *(new)* |
| Race strategy engineer (F1 25) | yes | yes (Austria and Monza excerpts; a full 71-lap Austria race) | no | safety car, VSC, rain and your own stop (synthetic only) | `strategy_calls` *(new)* |
| Race radio: flags, penalties, start and countdown, positions and rivals, damage (F1 25, GT7) | yes | yes (F1 25 PS5: yellow, blue, the start, laps to go, the finish, position changes and clean passes, gaps, warnings, time penalties, a drive-through and its service, wing/floor/diffuser damage, retirements, fastest laps; GT7 PS5: the start, lap one, laps to go, the finish and positions; 5 excerpts and 30 of the owner's races, see [below](#race-radio-unreleased)) | no | everything heard on track; the safety car, VSC, red flag, stop-go, disqualification, black flag, reminders, lap invalidations, the car ahead pitting, punctures, minutes left and faults (synthetic only); GT7 positions against the game's screen; Forza (community docs only) | `race_radio` *(new)* |
| Goals, streaks, badges, weekly digest, 3 things, session report | yes | yes (owner's PS5 captures replayed in a scratch database) | no | used after a live session | `goal_line` *(new)* |
| Reference choice and practice drills | yes | yes (owner's F1 25 captures through `scripts/coachref_check.py`; no committed excerpt has a complete lap) | no | a drill driven on purpose; another driver's lap as the live reference | `drill_cycle`, `reference_choice` *(new)* |
| Rig validation kit | yes | yes | n/a | nothing passes until it is run live, by design | every item |
| One-line install and `pitwall update` | yes | yes (end to end on macOS with a local fake GitHub and a real packaged zip) | no | the release workflow's installer steps (first run at the first tag); Windows and Linux beyond CI; a real service repoint | - |
| Track knowledge (sectors, marshal zones, official corner names) | yes | yes (Austria) | no | official names beyond Austria; tracks other than Austria | - |
| Rig walkthrough and rig check | yes | yes (Austria excerpt) | no | load-cell checks; the thresholds beyond one rig | - |
| Car setup recommendations (F1 25) | n/a | yes (the PS5 Austria setups fit every confirmed range) | no | a recommended setup driven and checked | - |
| Gran Turismo 7 (PS5) | yes | yes (3 excerpts of the owner's 2026-10-11 races; the 4 captures replayed: 4 sessions, all 11 timed laps exact) | **yes** (races on 2026-10-11: 277,467 packets, 0 rejected, every lap time equal to the game's) | the session and lap fixes made after that run, live; race position against the game's HUD; the steering scale; fuel units; PS4 | `gt7_ps5` |
| Forza Motorsport, Forza Horizon | yes | no | no | everything with the real games | - |
| Assetto Corsa (PS4 build on PS5) | yes | yes (probe excerpt, 2026-10-11) | protocol only (the probe script) | a lap stored, timed and coached end to end | `ac_ps5` |
| Cloud AI providers | mock servers only | n/a | no | a live cloud call | - |
| Dashboard v2 (React, HeroUI) | yes | yes (desktop browser at iPad and phone sizes) | no | on a real iPad in a live session | `ipad_endurance` |
| Windows | CI | CI | no | a game on a Windows PC | - |

## Gran Turismo 7 on the PS5 (2026-10-11)

The owner drove GT7 on a PS5 with Pitwall's live service and reported that it worked. The live service's heartbeat
and UDP 33740 listener recorded 277,467 packets in 4 captures (`data/captures/20261011-013533`, `-121256`,
`-124608`, `-182615` `_udp33740.pwcap`): all variant C (so game version 1.68 or later), 0 rejected, 0 decode errors,
59.9 Hz, 9 lost; 4 races on 2 circuits (a 0.92 km oval and a 3.8 km circuit) with 3 cars. Every lap time Pitwall
stored equalled the game's own last-lap field to the millisecond.

The same data showed three defects, fixed on 2026-10-12 and re-checked by replaying the 4 captures through the
current code into a scratch database (4 sessions, all 11 timed laps stored with the game's times; seeded with the
database's track ids, as the service is, both circuits get the ids the live run learned):

- **28 sessions for 4 races.** GT7 streams at 60 Hz in its menus, replays and the menus' background laps; every load,
  retry signal and car reset started a session. A session now opens after 0.5 s of driving (on track, not paused,
  the car moving) and ends on a load that is not a car reset, a car change, a retry, 2 s off track, or 2 s of the
  frozen stream below. A car reset (a 1-packet loading pulse with the car on track, the same lap and the lap timer
  running on) stays inside the session. The 23 empty sessions already stored are hidden from the session lists and
  counts, not deleted.
- **5 of 11 timed laps lost.** Race lap 1 was never placed on the track, and the resets split the races. Race lap 1
  is now anchored at the rolling start (every real one crossed within 1 m of the line) and marked "race start" (the
  game times it from the start signal, 150-383 ms before the line); a timed lap Pitwall cannot place keeps the game's
  time without a trace ("no trace").
- **The frozen stream after leaving a race was driving.** GT7 then repeats one packet (on track, not paused, 45.9
  m/s) for minutes; it was integrated into a 16.8 km "lap 5" while the dashboard showed 165 km/h. Those packets are
  now dropped and end the session after 2 s. "Moving" is judged on the velocity (at least 0.5 m/s), not on the speed
  field, which reads near 0 while the car slides sideways: a stream frozen mid-spin ends the session too (synthetic
  packets only; no real capture froze mid-spin). A repeated packet is never integrated.

Fields the recordings settled (now `recorded_validated`, each with its evidence in the adapter's field notes): speed
(0x4C is the car's speed along its own axis, not the path speed: it falls towards 0 when the car slides sideways, so
lap distance now integrates the velocity vector - 0.08-0.18 % short of the driven path on the 11 timed laps, where
the speed field fell 0.09-1.52 % short), throttle (0x13C is the pedal, 0x91 the throttle after TCS - the frames now
carry the pedal), brake, gear (forward gears; 0 and 15 stay unknown: 0 appeared only in spins with the clutch out,
and reverse and neutral were never selected), rpm, position, velocity, the tick clock, packet id, lap count, lap
times, the current-lap timer, lap total, best lap, car code, tyre temperatures, lap distance and track length (the
shortest lap of the session that matches the circuit: 914.7 m and 3,799.0 m). Still community-documented: steering
(the sign is right, but 0x128 clamps at +/-pi, so its scale tops out at 40 %), race position (a live position in
races, not yet compared with the HUD), the rev-limit RPM, clutch and the derived track id; fuel stays unread (100 /
100 throughout: the unit is still open).
Recorded-tier fixtures: `tests/fixtures/recorded/gt7_c_ps5_*` (the race start and 3 laps, leaving a race, a car
reset), pinned by `tests/recorded/test_gt7_ps5_real.py`.

## Race radio (unreleased)

The race radio (`src/pitwall/raceradio`, `docs/features.md`) has been run only on recordings and synthetic data; **it
has not been heard live**. Each call carries its tier (`tier` in `/api/race/live` and on the radio):

- **Recorded** (F1 25, PS5): yellow ahead, yellow here, blue flag, grid slot, lights out, laps to go, last lap, the
  finish, the lap-one summary, position changes, clean passes, the pit-exit position, gaps, fastest laps,
  retirements, warnings, time penalties (4/3, 4/4, 4/7, 4/29), a drive-through (0/34, a jump start in the Sakhir
  sprint) and its DTSV, and wing, floor and diffuser damage. GT7 (PS5): the grid slot, the lap-one summary, laps to
  go, last lap, the finish and position changes, from GT7's race position, not yet compared with the game's screen.
- **Synthetic only**: the safety car and VSC (no real capture had one), the red flag (urgent, past quiet mode), stop-go,
  disqualification, black flag and the serve reminders, lap invalidations (PENA 11/13/14/15), the car ahead pitting,
  punctures (tyre damage read 100 % in 10 real crashes, but each came with a terminal-damage retirement or a
  flashback, which silence the call), sidepod, brake, gearbox and engine damage, ERS and DRS faults, and minutes left
  in practice and qualifying. Forza positions follow community docs only.
- **Live**: none.

Checked on 2026-10-12 with `scripts/race_radio_check.py` over scratch copies of all the owner's F1 25 and GT7 captures
(35 sessions, 30 of them races: 26 F1 25, 4 GT7; 771,336 frames), every proactive call through the radio policy at
normal: 297 calls made, 239 heard, 3-7 heard in each 3-lap race; 0 "yellow ahead" calls for a zone that went yellow
at, behind or within 150 m of the car (5 of the 7 were followed by the player's own yellow within 20 s), 0 blue calls
without the car's blue flag or within 30 s of the last, 0 position calls that disagreed with the car's position or
came on lap one or within 5 s of a flashback, 0 penalty or warning calls without the matching event and time, 0
online names in any call (up to 20 known per session), 0 calls heard outside a speak window. The committed excerpts
(`tests/fixtures/recorded/*race-*-excerpt.pwcap`, scrubbed) pin a warning for contact, a 3 s penalty after a pass with
no "clean pass", one blue call, one combined damage call with the front-wing advice, and GT7's last lap and finish
(`tests/recorded/test_raceradio_real.py`). The red flag reaches the radio within 250 ms with the test voice
(`tests/unit/test_hub_race_calls.py`); with Kokoro it has not been measured. Ingest with the race radio attached:
median 2.9 us, p99 35 us per packet on 13,208 recorded packets (unchanged).

## Known gaps

Kept open for after v0.2.0 (none of them changes what Pitwall claims):

- **GT7:** the 2026-10-12 session and lap fixes have run only on the recordings; the PS4 is untested; `/api/health`
  reports "live" while GT7 streams in its menus, so `scripts/pitwall-service.sh restart-when-idle` waits as long as
  GT7 is open; a race whose every lap had a reset leaves its circuit unrecognised (no complete lap to measure).

- **Goals and recaps:** a lapped finisher's race is worded as finished but judged by the chequered-flag rule only
  later; incomplete laps; safety-car laps are judged by the live safety-car state, not stored per lap yet.
- **Game selection:** the owner's seven open questions from the game selection review.
- **Technique:** lock-ups are synthetic only; the rig check has no lock-up measure yet.
- **Race strategy:** the predicted rejoin place is right only 44.6 % of the time on a second session id; safety car,
  VSC, rain and your own stop are synthetic only.
- **Pace against the AI:** the active-car count and assist guards; the safety-car exclusion is synthetic only; time
  trial and the 2026 format are unverified; the "measured" suggestion has only been shown with made-up data.
- **Reference choice and drills:** the finished-drill card is tested as a render only; recorded evidence comes from a
  development script until an excerpt with a complete lap is committed. "Choose a corner…" on the Ready card shows
  between runs with a suggested drill only (the plan's slot limits); drills can always be started by radio.
- **Radio:** 3.4's goal-and-summary merge and answer topics are left for 0.2.1.
- **Race radio:** nothing heard live; F1 25's `gridPosition` is 0-based at a race start on the PS5 (pole = 0), so the
  race radio takes the grid slot from the position before lights out (the strategy engine's grid position is
  one off; not changed here). Online names in "who's ahead?" are opt-in (off) and use the `say` voice.
- **Review:** the Ask page (outside a session) offers only the AI question beyond the defaults; Sessions is not yet
  filtered by the selected game.
- **Validation kit:** the new catalogue items above (`radio_budget`, `strategy_calls`, `goal_line`, `drill_cycle`,
  `ai_pace_result`, `technique_balance`, `reference_choice`) are not in the catalogue yet.
- **Acceptance:** the end-to-end acceptance run of the v0.2.0 plan (section 8) ran once in a scratch folder on
  12 Oct (migrations and the rollback rehearsal on a copy of the live database passed). Its five failures (the Ready
  card with an old drill result, Session complete's order with a goal and a record, the phone Corners page, a held
  radio message inside the 2 s gap, the live snapshot size) are fixed since and re-checked one by one (browser fit
  measurements, the snapshot sizes on the committed Austria excerpt, unit tests); the full run has not been repeated.
- **Review:** the "AI reference" heads-up wording and the "SB your best today" legend keep their words until the 0.2.1
  vocabulary pass; Connect's game menu paths still use ">".
