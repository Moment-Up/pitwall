# Status

_Last updated: 2026-10-12 (v0.2.0: the nine features merged; nothing in this release has been run live on the rig
yet unless the Live column says so)._

What works, how far each part has been tested, and what is still unverified. Every claim is tied to one evidence
tier:

- **Synthetic**: generated telemetry with known, injected mistakes (`pytest -m synthetic`). Proves the algorithms.
- **Recorded**: real game output captured to a file and played back (committed excerpts in
  `tests/fixtures/recorded`, or the owner's captures replayed into a scratch database). Proves the decoders and the
  analysis cope with what the game really sends.
- **Live**: the real game on the real platform, end to end. Only a run of the validation kit (Setup › Validation,
  `pitwall validate`) on the rig upgrades a status, and only by hand: `src/pitwall/capabilities.py` changes only with
  new evidence.

Merging the v0.2.0 lanes did not upgrade any tier. The per-lane development notes (what was checked, on which
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
| Goals, streaks, badges, weekly digest, 3 things, session report | yes | yes (owner's PS5 captures replayed in a scratch database) | no | used after a live session | `goal_line` *(new)* |
| Reference choice and practice drills | yes | yes (owner's F1 25 captures through `scripts/coachref_check.py`; no committed excerpt has a complete lap) | no | a drill driven on purpose; another driver's lap as the live reference | `drill_cycle`, `reference_choice` *(new)* |
| Rig validation kit | yes | yes | n/a | nothing passes until it is run live, by design | every item |
| One-line install and `pitwall update` | yes | yes (end to end on macOS with a local fake GitHub and a real packaged zip) | no | the release workflow's installer steps (first run at the first tag); Windows and Linux beyond CI; a real service repoint | - |
| Track knowledge (sectors, marshal zones, official corner names) | yes | yes (Austria) | no | official names beyond Austria; tracks other than Austria | - |
| Rig walkthrough and rig check | yes | yes (Austria excerpt) | no | load-cell checks; the thresholds beyond one rig | - |
| Car setup recommendations (F1 25) | n/a | yes (the PS5 Austria setups fit every confirmed range) | no | a recommended setup driven and checked | - |
| Gran Turismo 7, Forza Motorsport, Forza Horizon | yes | no | no | everything with the real games | `gt7_ps5` |
| Assetto Corsa (PS4 build on PS5) | yes | yes (probe excerpt, 2026-10-11) | protocol only (the probe script) | a lap stored, timed and coached end to end | `ac_ps5` |
| Cloud AI providers | mock servers only | n/a | no | a live cloud call | - |
| Dashboard v2 (React, HeroUI) | yes | yes (desktop browser at iPad and phone sizes) | no | on a real iPad in a live session | `ipad_endurance` |
| Windows | CI | CI | no | a game on a Windows PC | - |

## Known gaps

Kept open for after v0.2.0 (none of them changes what Pitwall claims):

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
