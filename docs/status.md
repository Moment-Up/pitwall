# Status

_Last updated: 2026-10-14 (v0.2.0: the nine features merged; nothing in this release has been run live on the rig
yet unless the Live column says so. After it: Gran Turismo 7 on the PS5, from the owner's races of 2026-10-11; F2
cars in F1 25, recorded; v0.3.0's one radio engineer, recorded; habits and corner reminders, synthetic and
recorded)._

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
| F2 cars in F1 25 (PS5) | yes | yes (12 F2 sessions of 2026-10-11 replayed; 3 committed excerpts) | no | a live run; mandatory stops at longer race lengths; 2026 F2 cars | `f2_ps5` |
| Coaching from your own reference lap (deterministic) | yes | yes | **yes** (coaching produced in the live races) | the radio and the card saying the same point, live | `ipad_one_message` |
| Live braking cues | yes | yes | no | timing on track | `cues_timing` |
| Habits on the radio and Drive, corner reminders, the report's habit rules (unreleased) | yes (unit tests; 5 synthetic scenarios before / after) | yes (30 owner captures replayed before / after: [below](#habits-and-corner-reminders-unreleased)) | no | heard live; a reminder's real audio length and the driver's reaction to it; "sorted" said after a real fix | `cues_timing`, `ipad_one_message` |
| F1 spotter (cars alongside) | yes (16 scenarios, at 60, 20 and 10 Hz, formats 2025 and 2026: a corner, a spin and a gate closing included) | yes (26 owner PS5 race sessions, 169 min: every overlap of 1 s or more called (121/121), 0 wrong clears, no call while the player slides more than 30 degrees; ground truth from the same positions. The radio simulated at measured clip lengths on the same races: what the driver would hear) | no | heard on track; audio latency to the ear; format 2026; online lobbies beyond one race; the car box against the game's collision shapes; the clear said as a gate closes (synthetic only: it never happened in these races) | a live F1 race with the spotter on (manual) |
| Radio: push-to-talk, speech recognition, voices | yes | yes | partly (a radio check over an iPad and one AirPod was heard; the F1 25 wheel button is read live) | a driver asking by push-to-talk; the new dashboard's Go live on an iPad; Kokoro and Windows voices on a radio | `radio_ptt`, `radio_kokoro` |
| Radio: hands-free talking (wake word "Pitwall" / "Radio", stationary unless the driver allows it while driving; Bluetooth button) | yes (the wake word through the real speech engines on 119 macOS `say` clips: "Pitwall" 44/49 clean, 45/49 with an engine drone, "Radio" 26/28, 0 false accepts; the browser VAD rules on the same clips; the hub's rules unit-tested; end to end on an isolated server: `say` clips over `/ws/radio` while a recorded F1 25 race streamed over UDP, docs/research/handsfree.md 3.5) | yes (the stationary gate on 11 owner captures as the hub sees them, incident gaps of 2-4 s no longer counted as stops and the hint only at stops of 8 s or more (review round 2); real F1 25 button presses through the hub with hands-free armed: 38 of 38 UDP Action 1 presses keyed push-to-talk and cut the capture); no recorded voice | no | a real voice and AirPod on the rig (A9 recordings owed); the Bluetooth key and game controller on an iPad; hands-free while driving | `radio_handsfree` *(new)* |
| Radio policy (v0.3.0, one engineer: `voice/scheduler.py` `POLICY`, docs/voice-protocol.md "Radio policy"): one per-lap budget for every producer (3 normal, 5 detailed; alerts never wait but count), the race order, only spotter calls, the red flag and a puncture interrupt (and braking calls cut routine talk), the line's race news inside the lap time, the safety car announced once, shared fuel and gap topics, answers hold their topic, no coaching after the flag, speak windows from the driver's last laps on a new track; seat change | yes (`tests/unit/test_radio_policy.py`: every producer's message maps to a row and the row is what the scheduler does; the urgent path, `tests/unit/test_urgent_path.py`) | yes (8 owner races - 6 F1 25, 1 GT7 race, 1 AC probe - streamed at real time into an isolated server with a text-only radio, before and after, at quiet, normal and detailed: [below](#one-radio-engineer-v030-unreleased)) | no | heard live on track | `radio_speak_windows`, `radio_budget` *(new)* |
| Engineer intents and instant answers while moving | yes (204-question fixture, every answer grounded and short enough for the radio) | yes (the acceptance run: every typed question on track got its intent, no "Copy, checking."; the long answers it found are shortened since, unit-tested) | no | asked by voice on track | `radio_ptt` |
| Lap naming on the radio and Drive ("That lap", "Out-lap", "Final lap") | yes | yes (Melbourne and Imola excerpts; 18 owner captures) | no | heard live; an out lap from the garage in practice; a pit-lane race start | `radio_speak_windows` |
| Drive at speed: moving or stopped, one status line, at most two chips, the cards | yes | yes (recorded snapshots; the Ready and Session complete cards measured with every slot filled, the reference control, goal row and drill blocks included, at 1180 x 820 and 1133 x 744 in a desktop browser) | no | on an iPad during a session | `ipad_glance` |
| Game selection and what each game sends | yes | yes (F1 25 and Assetto Corsa excerpts) | no | GT7, Forza or Assetto Corsa selected with a live console | `game_selection` |
| Driver profiles and seat changes | yes | yes | no | splitting a live session on a switch | `driver_switch` |
| Pace against the AI (F1 25) | yes | yes (six PS5 sessions, exact to the millisecond) | no | a real safety car; time trial and the 2026 format; a real "measured" level suggestion | `ai_pace_result` *(new)* |
| Technique: racing line, brake and throttle, handling balance, setup suggestions | yes | yes (F1 25 PS5 laps; the line on a GT7 capture; lock-ups on the F2 Bahrain race with ABS off, 2026-10-11) | no | a setup suggestion driven and checked | `technique_balance` *(new)* |
| Race strategy engineer (F1 25) | yes | yes (Austria and Monza excerpts; a full 71-lap Austria race) | no | safety car, VSC, rain and your own stop (synthetic only) | `strategy_calls` *(new)* |
| Race radio: flags, penalties, start and countdown, positions and rivals, damage (F1 25, GT7) | yes | yes (F1 25 PS5: yellow, blue, the start, laps to go, the finish, position changes and clean passes, gaps, warnings, time penalties, a drive-through and its service, wing/floor/diffuser damage, retirements, fastest laps; GT7 PS5: the start, lap one, laps to go, the finish and positions; 5 excerpts and 30 of the owner's races, see [below](#race-radio-unreleased)) | no | everything heard on track; the safety car, VSC, red flag, stop-go, disqualification, black flag, reminders, lap invalidations, the car ahead pitting, punctures, minutes left and faults (synthetic only); GT7 positions against the game's screen; Forza (community docs only) | `race_radio` *(new)* |
| "Where will I come out?" (rejoin estimate, F1 races) | yes | yes (the Imola 32-lap race, every one of its 32 stops predicted with the loss of the other stops: within one place 78 %, within two 100 %, the range +-1 covered 91 %; both of the player's stops exact; the game's own value said P4 where the car came out P2) | no | a stop of your own called by voice; under a safety car (synthetic only) | - |
| Cold tyres after a stop (car health) | yes (the safety-car restart: synthetic only) | yes (two F2 stops on PS5 with the carcass model, 2026-10-11: "cold" in the box a second after the tyre change, 13 / 15 s before the pit exit, at 28-30 C against an 88 / 86 C baseline; warm again on lap 3 / 4 and the all-clear said on both (on Bahrain a lock-up note had taken the lap's slot before); two F1 stops with tyre blankets at Imola - 69 C in the box against 66-68 C - and the Austria and Suzuka races: no call) | no | heard live in the pit lane after a stop; a real safety-car restart | - |
| Tyre temperature bands, brakes and engine (car health) | yes | recorded values, no thresholds (engine 103-132 C, brake lap peaks up to about 1,030 C on every recorded F1 25 / F2 race; GT7 surface 37-196 C) | no | the "hot" band (unvalidated); Forza tyre temperatures | - |
| Lock-ups and wheelspin per lap (car health, F1) | yes | yes (per-lap counts equal the survey's on every lap of the F2 and Imola sessions but one wheelspin across a line; F2 Bahrain ABS off: 50 lock-ups in 9 laps; wheelspin with traction control full, medium and off) | no | the notes heard on the radio | - |
| Fuel from the tank level (Forza) | yes (generated laps: within 0.3 laps of the truth, low then critical) | no (community-documented `Dash.Fuel`) | no | everything with the real game | - |
| GT7 fuel | n/a | **not enabled**: all four owner captures read 100 / 100 (no fuel used) | no | a GT7 race with fuel use on, 5+ laps and a refuelling stop | - |
| Attack and defend corners (F1 races, on request) | yes | recorded consistency (Austria, three sessions on two days: the attack corner the same, T2 at 1.4 km, on 11 of 12 laps with a car ahead; Imola's defend pick "spread" or "none" on 61 % of laps instead of an invented corner; segment sums within 0.035 s of the game's lap times; laps timed on a 25 m grid from the race start, so a re-learned corner model no longer restarts them: with the model rebuilt after 1, 2, 3 and 5 clean laps as the lap processor does, the first verdict came on lap 65 of the Austria session joined on lap 62 and on lap 5 at Imola - the first laps with two clean laps of both cars; a scratch-server replay before the change gave laps 68 and 8) | no | asked by voice on track | - |
| Goals, streaks, badges, weekly digest, 3 things, session report | yes | yes (owner's PS5 captures replayed in a scratch database) | no | used after a live session | `goal_line` *(new)* |
| Reference choice and practice drills | yes | yes (owner's F1 25 captures through `scripts/coachref_check.py`; no committed excerpt has a complete lap) | no | a drill driven on purpose; another driver's lap as the live reference | `drill_cycle`, `reference_choice` *(new)* |
| Rig validation kit | yes | yes | n/a | nothing passes until it is run live, by design | every item |
| One-line install and `pitwall update` | yes | yes (end to end on macOS with a local fake GitHub and a real packaged zip) | no | the release workflow's installer steps (first run at the first tag); Windows and Linux beyond CI; a real service repoint | - |
| Track knowledge (sectors, marshal zones, official corner names) | yes | yes (Austria) | no | official names beyond Austria; tracks other than Austria | - |
| Rig walkthrough and rig check | yes | yes (Austria excerpt) | no | load-cell checks; the thresholds beyond one rig | - |
| Controls and button mapping (Setup › Controls) | unit (catalogue, recommendations for every template, game and preset, the button test, push-to-talk following the layout) | yes (BUTN bits named from the four committed F1 25 PS5 excerpts, labelled replay and never counted; the owner's 2026-10-10/11 captures replayed: 78 UDP Action 1 presses, none counted) | no | the owner's F1 button test: which GT DD Pro control sends which bit, a coloured stick on a UDP Action, a brake bias change seen; the radio on the mapped button; every other game's steps (research only) | `wheel_buttons` *(new)* |
| Car setup recommendations (F1 25) | n/a | yes (the PS5 Austria setups fit every confirmed range) | no | a recommended setup driven and checked | - |
| Gran Turismo 7 (PS5) | yes | yes (3 excerpts of the owner's 2026-10-11 races; the 4 captures replayed: 4 sessions, all 11 timed laps exact) | **yes** (races on 2026-10-11: 277,467 packets, 0 rejected, every lap time equal to the game's) | the session and lap fixes made after that run, live; race position against the game's HUD; the steering scale; fuel units; PS4 | `gt7_ps5` |
| Forza Motorsport, Forza Horizon | yes | no | no | everything with the real games | - |
| Assetto Corsa (PS4 build on PS5) | yes | yes (probe excerpt, 2026-10-11) | protocol only (the probe script) | a lap stored, timed and coached end to end | `ac_ps5` |
| Cloud AI providers | mock servers only | n/a | no | a live cloud call | - |
| Dashboard v2 (React, HeroUI) | yes | yes (desktop browser at iPad and phone sizes) | no | on a real iPad in a live session | `ipad_endurance` |
| Windows | CI | CI | no | a game on a Windows PC | - |
| Windows speech recognition (Parakeet via sherpa-onnx) | synthetic audio on macOS (the same engine and model: "Pitwall" 43/49, "Radio" 27/28, 0 false accepts, median 95 ms with 2 threads) | CI install (the `windows` job: `uv sync --all-extras --locked`, an import test, the doctor's sherpa-onnx line) | no | run on a Windows PC: download, latency (expect 2-4x the Mac's CPU figures), a spoken question | - |

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

## F2 in F1 25 (PS5): recorded

The owner drove F2 cars in F1 25 on 2026-10-11 (PS5, v1.26, UDP format 2025) with the live service: a Grand Prix
race at Melbourne in a 2025 F2 car (team id 214, capture `20261011-011513`), then one-shot qualifying and feature
races at Sakhir, Jeddah and Melbourne in the Art GP '24 (team 158, `20261011-224147`): 12 F2 sessions, every Session
packet with formula 2. Pitwall had no notion of the car's class: the car showed as "team_214" or a 2024 team name, an
F1 car format was asked for on Car setup, ERS showed as an empty store, and one-shot qualifying stored every lap
twice. Since 2026-10-12, recorded evidence (the two captures replayed through the current code into a scratch
database: 12 sessions, all classed F2 with the right labels, 24 timed laps, each one-shot session with its one lap
and no duplicate; fixtures `tests/fixtures/recorded/f1_25_2025_ps5_f2_*`, pinned by `tests/recorded/test_f2_ps5.py`):

- **What works (recorded):** the class from the formula (else the team id) with the labels "F2 · Art GP '24" /
  "F2 · Hitech '25" and "Sprint race" / "Feature race" (the sprint only in a weekend whose structure, sent by the
  game, also has a feature race: (15, 16) at Melbourne; (9, 16) at Sakhir and Jeddah); the 2025 F2 team ids
  209-219, which EA's document does not
  list, named after EA's own 465-475 (`docs/research/f1-udp-spec.md` section 10, item 19); no ERS (the game sends 0
  in every ERS field for every F2 car, item 20, and none is shown before the formula is known); the DRS fields (an
  open flap is said to be open: the game's DRS-allowed flag clears as the flap opens, item 20); F2 tyre compounds;
  the 60 km/h pit limit; one lap per one-shot qualifying and no empty "lap 2" after it (item 21; the 3 duplicate
  laps and the one-sample untimed laps already stored are deleted at the first start by the one-off repair
  `repair.f2_v1`, which also marks the 6 Sakhir and Jeddah track models built from them superseded and rebuilds both
  from clean F2 laps); the stored track model on Drive from the start of a session, so one-shot qualifying shows its
  corners (any game, tested with unit tests); track models, driver bests and consistency goals kept per class; F2 car
  setups (ranges from F2 evidence, 30 cited setups for 5 tracks); the physics warning with an F2 braking curve
  (fitted from the F2 AI field of these sessions, in sample: 64 stops on 3 tracks, median 0 m, p90 38 m, none
  outside the 100 m margin; the F1 default had median +26.5 m, p90 51 m and 1 stop outside); stop rules that are
  never claimed, asked only with rule words (a plain "do I need to pit?" keeps the strategy answer).
- **Not yet verified:** a live run (validation check `f2_ps5`, which can upgrade the class to live); whether F1 25
  enforces the mandatory stop and both compounds in longer F2 races (in a 5-lap race on the PS5 it did not); the
  2026 F2 cars and F2 cars in UDP format 2026 (recognised from the spec only: `spec_implemented`, no setups for the
  2026 cars, no recording); whether F2 teams differ in the game (records and bests are kept per car, so each F2 team
  has its own); a race-only F2 weekend (its "Race" is named "Race", not "Sprint race"); a final lap driven in
  exactly the previous lap's time (reported after 1 s without a new time; not recorded); the F2 range ends not yet
  confirmed in the game's setup screen (listed in `f2_ps5`).
- **Known gap:** the one-shot qualifying lap is not tagged as the session's final lap (the game turns the result
  "finished" 17 ms after the line), so the radio may give one coaching point after it.
- **Fixed after review (2026-10-12):** the 1-sample "lap 2" the game starts after the one-shot line is no longer
  stored (it was, as an untimed incomplete lap, in any session that ended just after a line crossing; the repair
  deletes those already stored); the F2 check `f2_ps5` fails on a stored one-sample lap.
- **Known gap:** older stored F2 sessions have no weekend structure, so their "Race" reads "Race" (not "Sprint
  race"); "Race 2" is still "Feature race".
- **End to end (2026-10-12):** both captures streamed over loopback UDP to a scratch server (the Melbourne race at
  1.5x, the Jeddah and Melbourne one-shot and feature sessions at 3x) with the dashboard at iPad and phone sizes:
  the F2 chip, "Sprint race" / "Feature race", "Super soft · 1 lap" and no ERS on Drive; F2 cars and the stop-rules
  line in Review; F2 setups with credits; the engineer's ERS, DRS, tyre, strategy and stop-rules answers (no LLM).

## Race radio (unreleased)

The race radio (`src/pitwall/raceradio`, `docs/features.md`) has been run only on recordings and synthetic data; **it
has not been heard live**. Each call carries its tier (`tier` in `/api/race/live` and on the radio):

- **Recorded** (F1 25, PS5): yellow ahead, yellow here, blue flag, grid slot (the formation-lap brief too: Imola),
  lights out, laps to go, last lap, the finish, the lap-one summary, position changes, clean passes, the pit-exit
  position, gaps, fastest laps, retirements, warnings, time penalties (4/3, 4/4, 4/7, 4/29), a drive-through (0/34,
  a jump start in the Sakhir sprint) and its DTSV, and wing, floor and diffuser damage. GT7 (PS5): the grid slot, the
  lap-one summary, laps to go, last lap, the finish and position changes, from GT7's race position, not yet compared
  with the game's screen.
- **Synthetic only**: the safety car and VSC (no real capture had one; green only at "resume race" or a Session status
  of none), the red flag (urgent, past quiet mode), stop-go, disqualification, black flag and the serve reminders,
  "Flag's out. Last lap." and the lapped last lap ("the leader finishes first": no capture produced them, so they are
  tagged synthetic), lap invalidations (PENA 11/13/14/15), the car ahead pitting,
  punctures (tyre damage read 100 % in 10 real crashes, but each came with a terminal-damage retirement or a
  flashback, which silence the call), sidepod, brake, gearbox and engine damage, ERS and DRS faults, and minutes left
  in practice and qualifying. Forza positions follow community docs only.
- **Live**: none.

Checked on 2026-10-12 (after the review fixes below) with `scripts/race_radio_check.py` over scratch copies of all
the owner's F1 25 and GT7 captures (36 sessions, 31 of them races: 27 F1 25, 4 GT7; 766,886 frames), every proactive
call through the radio policy at normal: 287 calls made, 262 heard, 3-10 heard in each 3-lap race; 0 "yellow ahead"
calls for a zone that went yellow at, behind or within 150 m of the car (6 of the 8 were followed by the player's own
yellow within 20 s), 0 blue calls without the car's blue flag or within 30 s of the last, 0 position calls that
disagreed with the car's position or came on lap one or within 5 s of a flashback, 0 penalty or warning calls without
the matching event and time, 0 online names in any call (up to 20 known per session), 0 calls sent outside a speak
window (brake and steering at the moment of sending). The script has no track model, so the speak window's look-ahead
to the next braking zone is not simulated: 97 of the 263 spoken intervals met a frame that braked or cornered, an upper
bound of what the live radio does with its look-ahead (unmeasured live). The committed excerpts
(`tests/fixtures/recorded/*race-*-excerpt.pwcap`, scrubbed) pin a warning for contact, a 3 s penalty after a pass with
no "clean pass", one blue call, one combined damage call with the front-wing advice, and GT7's last lap and finish
(`tests/recorded/test_raceradio_real.py`). The red flag reaches the radio within 250 ms with the test voice
(`tests/unit/test_hub_race_calls.py`); with Kokoro it has not been measured. Ingest with the race radio attached:
median 2.9 us, p99 35 us per packet on 13,208 recorded packets (unchanged).

Review fixes (2026-10-12, regression tests in `tests/unit/test_raceradio_review_fixes.py`; recorded on the owner's
captures where noted, else on hand-made data):

- Speak windows: before a learned track model exists (a new track, a joined race) the radio's look-ahead uses the AI
  field's braking zones and the physics prior's tags (`voice/field_zones.py`); "unknown" was taken as calm, and
  recorded runs put a lap time and a position call into Turn 1 and Turn 3 braking.
- The start and countdown no longer use the per-lap race allowance, a move into P1 always gets through, and "Two laps
  to go" is said only in races of 5 laps or more: Melbourne's 3-lap race heard 7 of 14 calls, without the move
  into the lead; now 10 of 13 with it [recorded]. A countdown at the line goes out inside the lap summary.
- Repeated blue flags, yellows and penalties are no longer swallowed by the 60 s identical-sentence filter: a lapped
  Austria run lost its second blue flag (33 s after the first); now all 4 are heard [recorded].
- Laps to go count the current lap ("2 laps to go" from 1.4 left; the second half of the last lap is "last lap"), and
  "how many laps left?", "what lap are we on?" and "is this the last lap?" have their own answer.
- "Who's leading?" names the leader (F1) or says the position, never the car ahead; "who's behind?" when last says
  so. An opt-in online name is only said for the car the answer's gap is about.
- GT7's grid slot is taken only before the rolling start (a join on lap 3 said "Up 5 from the grid"); F1's freezes
  once the car moves (a missed lights-out event and a lap-one stop made the stop's position the grid).
- A disqualification is said even when the lap data's "dsq" status arrives first; a flashback drops the unsaid
  position and damage calls; severe damage within 10 s of a damage call is said with what else broke.
- The finish says "on the road" with time penalties still to add, and never "Down N"; simple words never count
  places lost; the name goes first when the first sentence has a comma ("Sam, that lap, 1:15.5.").

## One radio engineer (v0.3.0, unreleased)

Every radio producer (lap summaries and coaching, goal lines, race strategy, the race radio, car health, the spotter,
hands-free answers, drills, validation prompts) now follows one table, `POLICY` in `voice/scheduler.py`, printed in
[voice-protocol.md](voice-protocol.md#radio-policy-one-engineer) and on Settings › Radio & voice ("What the radio
says"). **Recorded, not live**: 8 of the owner's captures (Suzuka, Bahrain and Jeddah 5-lap races, the Imola 32-lap
race, the Austria 71-lap race joined late, a Melbourne 3-lap race, a GT7 4-lap race, a 4-minute AC probe at
Silverstone) were streamed at real time (`POST /api/replay`, speed 1.0, the live path) into an isolated server with a
fresh database, the LLM off and a text-only radio (a device-voice client that reports playback at 2.9 words a second);
every message was recorded with its time, lap and lap distance, and the driver's brake during it. The same runs before
(HEAD 1960838) and after:

| Intensity | Laps | Engineer messages a lap (mean, max) | Laps over 3 / over 5 | Said while braking (from lap 3) | Cut by a braking call | Cut by the spotter | Same sentence again within 60 s |
|---|---|---|---|---|---|---|---|
| quiet, before / after | 18 | 0.39, 2 / 0.39, 2 | 0 / 0 | 2 of 7 (1 of 2) / 4 of 7 (2 of 2) | 0 / 0 | 0 / 0 | 0 / 0 |
| normal, before / after | 68 | 2.24, 5 / 2.21, 4 | 7, 0 / 8, 0 | 11 of 153 (6 of 121) / 8 of 151 (6 of 126) | 2 / 0 | 3 / 2 | 3 / 1 |
| detailed, before / after | 18 | 2.67, 6 / 2.33, 5 | 3, 1 / 2, 0 | 7 of 48 (2 of 27) / 6 of 42 (3 of 24) | 1 / 0 | 1 / 0 | 1 / 0 |

- Engineer messages exclude spotter calls (up to 36 on Suzuka's lap 1) and braking calls; a lap is the car's lap
  number when a message was sent, so a lap time said at the line can count on the lap before (Imola's "laps over 3"
  are mostly that).
- The line: race news at the line now rides in the lap time ("Opening lap, 1:26.788. P1 after lap one, up 2.";
  "That lap, 1:46.072, personal best. Fastest lap of the race. Two laps to go."): race calls heard went from 121 to
  142 of 228 made, 39 of them inside a lap time, with fewer transmissions (line splits 9 to 7 at normal, 3 to 1 at
  detailed). A lap time is said on every lap (Jeddah: 4 of 5 before, 5 of 5 after); no coaching point after the flag
  (Melbourne, GT7 and Suzuka at detailed said one before).
- A braking call no longer cuts a lap time or a coaching point (Austria before: a lap time cut by the spotter, said
  again and cut by a braking call); only the spotter cut anything after (Austria, said again once).
- Said while braking: most are a fresh database's first laps, before any braking zone is known. The driver's own last
  laps (`voice/lap_brakes.py`) are only used until a track model is learned (from the first clean lap), so they did
  not reduce this count in the measured runs (normal 6/121 before, 6/126 after). The quiet runs are 7 short
  yellow-flag alerts.
- After that run the chequered flag was made to always ride in the final lap's time (5 of 6 F1 races and the GT7 race
  still said "Chequered flag." and the final lap's time apart, over the word cap); re-run on Suzuka, Melbourne, Jeddah
  and the GT7 race at normal: the flag inside the final lap's time in all four, 1.94 engineer messages a lap, at most
  3, no lap over 3, nothing cut.
- AC: the probe has no timed lap, so the radio said nothing before and after. GT7: the lap-one position rides in the
  opening lap's time.
- Settings › Radio & voice groups every call family once: the seated driver's race calls (moved from the driver
  sheet, which keeps the radio words) with "say online players' names", car health, the spotter, hands-free with
  "Hands-free while <driver> drives" (also moved), and "What the radio says". Checked in a desktop browser at 800 and
  375 px wide; not yet on an iPad.
- Braking calls: the unify step had made them cut nothing, which dropped 3 braking calls as `radio busy` in these runs
  (Suzuka lap 5 T11 twice, Austria lap 68 T6). Restored after review: a braking call cuts routine talk (lap summary,
  coaching, race, health or strategy call, said again once) and a spotter clear, never an alert, an answer, an urgent
  call, a spotter car call or another cue. A puncture is on the urgent path (it cuts in, past the damage toggle; not
  after the flag); alerts spend the lap's budget.

## Habits and corner reminders (unreleased)

The radio coaches habits instead of every corner (docs/features.md "Habits: what the radio works on"): one definition
of a habit (`analysis/coaching.py`), habit memory kept through a new best (`core/lap_processor.py`), a habit tracker
(`coach/habits.py`) behind the radio's coaching pick and the coach card, braking calls and corner reminders from the
habits (`coach/cues.py`), and the report's habit rules (`motivation/recap.py`). **Synthetic and recorded, not live.**

How it was measured (2026-10-14): integration ddd7188 (before) and feat/habits (after) replayed the same captures,
read-only, through the real pipeline (packets, session manager, lap processor run synchronously, live state, coach
block, the radio's lap messages at normal intensity with nobody seated) with the braking calls in focus mode and a
simulated audio latency of 0.45 s (a reminder's length: the planner's word estimate). Corrective lines are the coaching
lines that are not praise; a silent lap is a compared lap without one; "same point next lap" is a line about the
corner and fault of a line on the previous compared lap.

Synthetic scenarios (`pitwall simulate`'s coaching demo as it was then, and the review's four), before / after:

| Scenario | Compared laps | Corrective lines | Silent laps | Same point next lap | Braking calls | First lap coached | After: announced, better, still, sorted |
|---|---|---|---|---|---|---|---|
| coaching demo of v0.3.0 (one-offs only; now `one_offs_scenario` in the tests) | 6 | 4 / 3 | 2 / 3 | 0 / 0 | 3 / 0 | 3 / 3 | 0, 0, 0, 0 |
| habit (design corner 3 brakes 15 m early, laps 3-10) | 9 | 8 / 4 | 1 / 5 | 4 / 1 | 7 / 6 | 3 / 3 | 1, 0, 1, 0 |
| pattern (four corners brake 12 m early, laps 3-9) | 8 | 7 / 5 | 1 / 3 | 1 / 0 | 12 / 10 | 3 / 3 | 1, 0, 1, 0 |
| improving (a new best every lap) | 7 | 0 / 0 | 7 / 7 | 0 / 0 | 0 / 0 | - / - | 0, 0, 0, 0 |
| pb_reset (a braking habit while another corner improves) | 9 | 5 / 2 | 4 / 7 | 4 / 0 | 5 / 6 | 2 / 2 | 1, 0, 0, 0 |

At detailed intensity the habit scenario went from 12 to 4 corrective lines and the pattern scenario from 14 to 7
(two habits announced, two "still"). The v0.3.0 coaching demo has no habit, so in focus mode it no longer makes a
braking call (before: "T2 brake" on laps 4-6 after one lap braking early); its radio lines lost the 0.08 s one-off on
lap 4. "improving" stays silent: each lap is a new best, so nothing loses time against the reference.

**The coaching demo tells the habits story (2026-10-14).** With only one-offs the demo showed no habit, no reminder,
no "sorted" and no braking call in focus mode, so `pitwall simulate` (and Drive's *Try a demo replay*, Settings ›
System) now writes ten laps that do (`sim/scenarios.py` `coaching_demo`; flashback on lap 5, invalid lap 10). Its
radio at Normal with nobody seated, in the corner names it learns: after lap 4 "T5, losing 0.23 s: braking 14 m
earlier. 2 of the last 3 laps."; "T5 brake" on laps 5-7; after lap 7 "T5 sorted: clean on 2 of the last 3 laps."; after
lap 8 "T4, losing 0.09 s: minimum speed 9 km/h down. 5 of the last 5 laps."; "T4: apex speed, 9 down" before T4 on laps
9 and 10; after lap 9 the big one-off "T2, losing 0.67 s: full throttle 31 m later than your reference."; lap 6's
small one-off (T1, 7 km/h) stays on the screen. The capture carries this list (`meta.extra["story"]`), `pitwall
simulate` prints it and Settings › System shows it after generating the demo. Pinned line for line by
`tests/synthetic/test_demo_story.py` in both packet formats, with the habit lines committed at the pick and on air.
**Synthetic only**; the Settings list and the Drive button have not been seen in a browser. A habit announced after
the line now gets its reminder on the lap the radio says it (`LiveState.habit_line_said` replans the cues): before,
with the radio hub running, it started a lap later.

30 of the owner's captures (F1 25 and GT7 on the PS5, 2026-10-10 to 13; every capture of 1 MB or more except the
synthetic demo and the AC probes), 28 sessions with a compared lap, before (integration ddd7188) / after (feat/habits
with the review fixes below; nobody seated, normal intensity, braking calls in Focus, harness replay with simulated
0.45 s audio latency):

| Session | Compared laps | Corrective lines | Silent laps | Same point next lap | After: announced, better, still, sorted | One-off lines | Braking calls | After: reminders (end before the braking point, min s) |
|---|---|---|---|---|---|---|---|---|
| Austria, 20261010-221749, 1 | 9 | 8 / 5 | 1 / 4 | 2 / 1 | 1, 1, 0, 0 | 8 / 3 | 13 / 0 | 5 (1.06) |
| Austria, 20261010-221749, 2 | 10 | 9 / 6 | 1 / 4 | 1 / 0 | 2, 0, 0, 0 | 9 / 4 | 9 / 0 | 0 |
| Imola race, 20261011-195612 | 30 | 29 / 17 | 1 / 13 | 4 / 0 | 5, 0, 0, 2 | 29 / 10 | 37 / 5 | 7 (1.08) |
| Bahrain / Jeddah, 20261011-224147, 3 | 5 | 4 / 2 | 1 / 3 | 0 / 0 | 0, 0, 0, 0 | 4 / 2 | 7 / 0 | 0 |
| Melbourne, 20261012-231555, 3 | 9 | 8 / 5 | 1 / 4 | 0 / 0 | 0, 0, 0, 0 | 8 / 5 | 6 / 0 | 0 |
| Melbourne race, 20261012-231555, 4 | 15 | 15 / 11 | 0 / 4 | 0 / 0 | 2, 0, 0, 0 | 15 / 9 | 27 / 2 | 0 |
| Melbourne race, 20261013-225521 | 18 | 18 / 10 | 0 / 8 | 2 / 1 | 2, 1, 0, 0 | 18 / 7 | 16 / 7 | 0 |
| 21 short sessions (1-4 compared laps) | 31 | 25 / 17 | 6 / 14 | 0 / 0 | 0, 0, 0, 0 | 25 / 17 | 7 / 0 | 0 |
| **All** | 127 | 116 / 73 | 11 / 54 | 9 / 2 | 12, 2, 0, 2 | 116 / 57 | 122 / 14 | 12 |

- Corrective lines per compared lap: 0.91 before, 0.57 after. No identical sentence was repeated in a session before
  or after; the same corner and fault on consecutive laps went from 9 to 2 (an announcement followed by its "better").
- Braking calls in Focus went from 122 to 14: they now follow braking habits that cost at least 0.05 s a lap and pass
  the profile's confidence floor, never one-offs. The "All" mode still calls every measured braking zone.
- The 12 reminders ended at least 1.06 s before the reference braking point; the cue engine dropped none late (0
  missed, 0 errors, before and after).
- The first lap with coaching is unchanged in 17 sessions, one lap later in 2 and gone in 6 short sessions whose only
  lines were small one-offs, now screen-only (3 sessions had none before or after).
- Today's 3 things changed in 7 of 28 sessions: three "Went well" became a sorted habit ("T6: sorted - clean on your
  last 3 laps (was braking about 12 m early)."), three "One to work on" moved to a repeated point still there (in
  224147, 5 a point repeated at 0.06 s replaced a single lap's 0.53 s: a habit before a one-off), and one session
  whose laps showed nothing repeated has no "One to work on".

Not verified: anything heard live, a reminder's real audio length and when a driver hears it, a "sorted" after a real
fix (the ones above come from recorded laps, not from a driver working on it), simple-wording and beginner wordings on
the radio beyond unit tests, and the coach card and Ready card on an iPad.

**Review fixes (2026-10-14, included in the table above).** A verified review of feat/habits found these, now fixed,
each with a unit, synthetic or pipeline test that failed before: "better" praised braking later on a lap where the
corner got slower, and compared numbers measured against two different reference laps; laps measured against a
reference that could not show the habit (it lost time at that corner some other way, it had the habit and left the
window, or it was another driver's lap or an older best) counted as clean, so "sorted" could follow a reference change;
"sorted" could come one recorded lap after the announcement; pit, out, safety-car, flashback, standing-start and
invalid laps counted as habit laps; braking calls on habits had no confidence floor; habits costing 0.02-0.08 s were
announced and held the only slot (now a 0.05 s floor); a reminder ranked like a braking call on air (it now plays only
on a free radio, cuts nothing and never plays with a car alongside); the radio's number and the reminder's differed;
blind habits kept their braking call; a beginner got two in-lap calls; an announcement the radio never said still made
the habit the focus (with no radio connected the screen-only coach records it when it picks it); the coach card's
"Once" and its counts disagreed with the evidence line; "braking N m later" followed "better" for a habit of braking
too late.

## Family leaderboard (unreleased)

Local family boards (docs/leaderboard.md): `/api/leaderboard`, `/api/records`, the record history, the family-record
badge, the engineer's `records` fact and intent, the radio line when a lap takes the record from another driver
(through the goal-line path), and the lap card format (`/api/leaderboard/lapcard/{id}`, local only). **Unit tests and
recorded data (a read-only copy of the owner's database); not live.** Nothing goes online.

On the copy (2026-10-15): 22 boards (20 F1 25, 2 GT7 unidentified circuits); all 120 clean laps of real driving land on
a board; one contested board (Austria · Haas · Race · Dry: the owner 1:10.549, the second profile +3.067 s, 4.35 %);
11 boards have ABS and TC unknown (laps stored before the per-lap assists), and the owner's F2 Sakhir laps split by ABS
(on / off), as designed. The record index takes about 60 ms there. Not yet verified: the radio line heard on track
(no household record has changed hands in a live session yet); the Records screen (Review › Progress) and the EA rival
and real-F1 rows, which plug into these boards.

## Known gaps

Kept open for after v0.2.0 (none of them changes what Pitwall claims):

- **GT7:** the 2026-10-12 session and lap fixes have run only on the recordings; the PS4 is untested; `/api/health`
  reports "live" while GT7 streams in its menus, so `scripts/pitwall-service.sh restart-when-idle` waits as long as
  GT7 is open; a race whose every lap had a reset leaves its circuit unrecognised (no complete lap to measure).

- **Family leaderboard:** the dashboard's purple REC (D2 `repo.lap_bests`: game + track + car + layout) is looser than a
  family board (which also splits session type, conditions and assists), so a lap can show REC while its board's
  record, and the radio's record line, belong to another lap. A layout's name is its shortest stored length: a new,
  shorter length within 3 % renames the board key; the API still finds the board by the older key, but the badge key
  changes with it.
- **Goals and recaps:** a lapped finisher's race is worded as finished but judged by the chequered-flag rule only
  later; incomplete laps; safety-car laps are judged by the live safety-car state, not stored per lap yet.
- **Game selection:** the owner's seven open questions from the game selection review.
- **Technique:** the rig check has no lock-up measure yet (lock-ups themselves are recorded since 2026-10-12: the F2
  Bahrain race with ABS off).
- **Spotter:** no validation-kit item yet (a live F1 race with the spotter on and the owner listening is the next,
  manual, check); it stays off by default until then.
- **Race strategy:** safety car, VSC, rain and your own stop are synthetic only. The rejoin estimate was rebuilt on
  real data (F1 25 zeroes the gaps 1-2 s before a car turns in, so the first rule had none for any AI stop at Imola);
  it is recorded on one race (Imola).
- **Car health:** nothing is live-validated. The recorded races were streamed end to end over UDP to a scratch server
  (2026-10-12, text-only radio): both F2 cold-tyre calls, the warm-again and lock-up notes were said, Drive showed the
  cold wheels and TYRES COLD, and the tyre-call switch silenced the call; never with the game running. The "hot" tyre
  band is display only and unvalidated; lock-ups and wheelspin are read for F1 only (GT7, Forza and Assetto Corsa slip
  is not read); GT7 fuel stays off until a recording shows it falling; Forza fuel is synthetic only; the safety-car
  restart arm of the cold-tyre call is synthetic only; a cold-tyre baseline is never carried across sessions (an F2
  race starts without blankets: no call on lap 1). The in-box judgement of new tyres reads the tyre age and compound
  (CarStatus): a stop whose change is not seen is judged on track after the exit, as before.
- **Pace against the AI:** the active-car count and assist guards; the safety-car exclusion is synthetic only; time
  trial and the 2026 format are unverified; the "measured" suggestion has only been shown with made-up data.
- **Reference choice and drills:** the finished-drill card is tested as a render only; recorded evidence comes from a
  development script until an excerpt with a complete lap is committed. "Choose a corner…" on the Ready card shows
  between runs with a suggested drill only (the plan's slot limits); drills can always be started by radio.
- **Radio:** 3.4's goal-and-summary merge and answer topics are left for 0.2.1.
- **Habits:** faults are measured against the reference lap, so a habit the reference lap itself has is invisible: a
  driver setting a new best every lap gets no coaching (the "improving" scenario), a habit whose new best has it gets
  no braking call or reminder while it cannot be measured (up to 5 laps, then it is forgotten without a word), and the
  report's "One to work on" can be empty for it. A habit is not counted against a reference it was never measured
  against (another driver's lap, a best from an earlier session) until a lap shows it there, so switching references
  mid-stint can let a habit be forgotten. With a radio connected, a habit line counts as said when it goes on air (with
  none, when the coach picks it); a line said in the instant between the next lap's analysis and its messages could be
  said twice (not seen in tests). Reminders need a radio connected; without one Drive shows the notes and "Working on". In the
  replays a reminder's length is the planner's estimate; the hub's measured audio length is unit-tested only. Markers
  and braking calls still assume a driver slower than the reference stays slower to the corner (reminders do not).
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
