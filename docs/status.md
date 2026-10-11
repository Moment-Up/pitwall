# Development status

_Last updated: 2026-10-11 (pace vs AI difficulty ported onto the public history as schema v4; earlier the same day:
game selection, technique, goals; public launch prep: release zips, install docs, Windows; dashboard v2 React +
HeroUI switch-over prep; previously 2026-10-10 evening: profiles, setup, cues, multi-game, track knowledge, cloud
AI)._

## Milestone 1 acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Runs locally on an Apple Silicon Mac | Done | `uv run pitwall serve` (Python 3.12, uv) |
| 2 | Receives or replays F1 telemetry | Done (replay + real UDP socket) | `pitwall send` -> UDP 20777 -> live dashboard; `pitwall replay` |
| 3 | Decodes speed, throttle, brake, steering, lap info | Done (live PS5, format 2025) | structs machine-checked vs EA spec; real PS5 race: lap + sector times match the game exactly |
| 4 | Records sessions persistently | Done | SQLite + raw `.pwcap` captures |
| 5 | Live telemetry in a browser | Done | Svelte dashboard, `/ws/live` (React dashboard v2: see below) |
| 6 | Braking events + distance-based lap comparison | Done | `analysis/braking.py`, `analysis/compare.py` |
| 7 | Measurable, evidence-based coaching observation | Done | e.g. "T2: braking about 13 m earlier than your reference (lap 1), losing 0.34 s" |
| 8 | Connects to local Qwen | Done | `pitwall llm-check` |
| 9 | Qwen answers using recorded telemetry | Done | grounded answers with fact citations (`pitwall ask`, Engineer tab, `pytest -m llm`) |
| 10 | Automated tests pass | Done | 1752 passed (unit + synthetic + recorded), mypy --strict, ruff |
| 11 | Documented start commands | Done | README, CLAUDE.md, Makefile |
| 12 | Unverified integrations identified | Done | capability matrix (`/api/capabilities`, Status tab) |

**Milestone 1 signed off on hardware (2026-10-10):** F1 25 v1.26 on PS5, UDP format 2025, Austria races.
About 190k packets with 0 rejected; every packet size matches EA's spec; lap and sector times decode exactly as
the game reports them; real coaching produced (e.g. "T9: braking about 10 m earlier than your reference (lap 2),
losing 0.12 s"). Recorded tier: `tests/fixtures/recorded/f1_25_2025_ps5_austria_race-excerpt.pwcap`
(byte-for-byte excerpt, see `scripts/excerpt_capture.py`; player names replaced with `scripts/scrub_capture.py`).

## Verified vs unverified
- F1 25 format 2025 on **PS5: live-validated** + recorded-tier fixture. PC / Xbox: same spec, not yet tested.
- F1 25 format 2026 (Season Pack): implemented from EA's spec; **synthetic-validated only**.
- Real-game behaviours now handled (all seen in the PS5 data, all covered by tests): race lap 1 starts ~132 m
  past the line and sits stationary on the grid; lap distance can jump ~150 m in one frame; the final race lap
  completes via `resultStatus` 2->3 (not a lap increment) and lap distance wraps one frame before that; sector
  times are zeroed one packet before the status change; button events arrive in menus.
- **Other games** (see `docs/research/game-compatibility.md` for every game/platform with evidence):
  - GT7 (`adapters/gt7`, Salsa20 + heartbeat) and Forza Data Out (`adapters/forza`): implemented from community /
    official docs, **synthetic-validated only**; enabled per game on the Connect page (`integrations.py`).
  - Assetto Corsa remote UDP (`adapters/ac`, `ingest/ac_client.py`, `scripts/probe_ac.py`): wired into the runtime
    and Connect page. PS4 build on **PS5: protocol confirmed live by the probe script, decoder recorded-validated**
    (2026-10-11: handshake answered, RTCarInfo at 59.8 Hz with 0 rejected; replayed: one real crossing timed by the
    game's lastLap and completed once, a restored state not counted, spline 0 = line); recorded-tier fixture
    `tests/fixtures/recorded/ac_ps5_ks_silverstone_probe-excerpt.pwcap`. **Unverified**: pitwall's own client and
    service against the console (no AC lap has been stored, timed or coached end to end), RTLap at a line crossing
    (the service does not subscribe to it), a full-lap track length on PS5 (the partial-lap estimate is good to a
    few %, so laps it scaled are void unless a full lap confirms it within 0.5 %; after the first full lap the
    length is fixed). **Open: layouts share a track id on PS5** (`trackConfig` = track name): only the track length
    tells them apart - stored geometry is rejected by the first full lap's length check, and references,
    comparisons and track models are restricted to sessions within 3 % of the session's length; switching layouts
    rebuilds the (per-track-id) track model, and older sessions of the other layout lose their corner analysis
    until it is rebuilt for them. isInPit is 0 while driving the pit lane (only the pit box is detected).
    PS4 / PC: community-documented.
  - Assetto Corsa Competizione on PS5: **tested 2026-10-11, no telemetry** (ports 9000 and 9996 refused).
  - Project Motor Racing / Project CARS 2 / AMS2 / ACC broadcast / EA WRC: protocol specs in
    `docs/research/protocols/`; not implemented. "Record another game" captures raw packets (e.g. PMR on 7576).
- **Driver profiles** (`drivers.py`, schema v2): per-driver sessions, references, PBs, coaching limits; the radio
  and cues follow the seated driver. Split-on-switch verified on synthetic streams only.
- **Live braking cues** (`coach/cues.py`): synthetic/recorded-verified; **not yet validated live**.
- **Reference choice and practice drills** (coachref, `core/coachref.py`, `coach/drills.py`,
  `coach/reference_wording.py`, `/api/coachref`, schema v3): unit + synthetic + recorded-tested
  (`scripts/coachref_check.py` on the owner's F1 25 PS5 captures, replayed into a scratch database: Las Vegas,
  Melbourne F2, Silverstone (Reverse), Austria (Reverse), plus Silverstone and Miami with two clean laps); **not
  live-validated**. Braking clamp verified on real laps: Silverstone (Reverse) T5 Maggotts and Becketts call at
  1960.8 m instead of the other lap's 1982.1 m (a call 21.3 m later than the driver had braked, prevented); Austria
  (Reverse) 1140.9 m instead of 1155.8 m; Melbourne F2 T9 4030.2 m; Las Vegas T12 3108.7 m. Brake-point drill at
  Austria (Reverse) 2929 m against the other lap's earlier point (2787.8 m), on copies of two recorded laps re-fed
  as attempts (`scripts/coachref_check.py`, not laps driven for a drill): +1.1 m past the point with the corner
  0.2 s slower (a miss: an attempt past the point is a hit only when the corner was faster), +11.5 m (an incident
  there), +1.1 m again; Las Vegas T1 +0.5 m and 0.01 s faster, a hit. Drill tolerances and steps are heuristics
  (`coach/drills.py`). Review fixes (unit-tested; the conditions and candidate ones also on the Las Vegas capture):
  radio drill commands act only on an imperative (a question asks for the status, a negation does nothing); a lap
  in other conditions (car, layout, wet/dry, assists) stops the drill and never uses its frozen reference; grid
  starts, resets, stale data and safety-car laps are no attempts and no baselines; another driver's ten fastest
  laps in other conditions no longer hide a comparable one; a request refused as busy never takes effect later; the
  chosen reference is published before the first lap (and again when F1's real assists replace the defaults of
  the first packets); the last result waits for its driver until Done; "who am I compared with?" names the
  reference. No committed recorded fixture has a complete lap, so `tests/recorded/test_coachref_real.py` skips
  today. End to end on an isolated scratch server (real F1 25 captures streamed over loopback UDP, demo drivers,
  headless browser at iPad and phone sizes): Drive's `Delta to` control and picker, the moving lock, the reference
  before the first lap, no braking calls on a first lap against another driver, the fallback reason, drills from
  the drill sheet and the radio, the drill chip / hero / coach card, the Session complete drill line, a drill
  carried into the next session and stopped by a driver change (result kept until Done), Review › Coaching's
  Drills, Review › Session "Drill this" and Review › Compare "Drive against this lap". The dashboard's contract
  test runs on bodies recorded from an earlier build of that server
  (`web-react/src/test/fixtures/coachref-recorded/`: key sets and values; some sentences have since been reworded).
  Follow-up: AC's ABS/TC and F1's formula are checked for other drivers' laps only; own references keep the older
  rule.
- **Track knowledge**: game-native skeleton (sectors, marshal zones; DRS/aero for 2026) verified on the real
  Austria capture; official corner identity verified for Austria only (other sheets seeded, not shown). Field model
  (AI cars), outline and physics prior: planned (research doc section 8).
- **Rig setup** (`rig/`, Setup tab): research revision 2 catalogue with provenance on every value (8 Nm keeps the
  in-game strength; FFS is a check after the Boost Kit); the beginner force default keeps its 5 Nm weight after the
  Boost Kit and the preview shows each driver's peak torque. Telemetry rig check (19 metrics): synthetic
  known-answer tests + recorded Austria excerpt; thresholds are heuristics calibrated on the 2026-10-10 PS5 races
  (Hall brake). Load-cell checks unverified (no load-cell session yet).
- **Cloud AI** (`ai/provider_registry.py`, Settings tab): Claude / OpenAI-compatible providers, keys pinned to vendor
  hosts, budget cap, name redaction. Mock-transport tests only; no live cloud call yet.
- **Voice**: Parakeet STT + macOS `say` / device voices live. Neural TTS chosen (`docs/research/tts-evaluation.md`:
  Kokoro bm_fable via mlx-audio); **not integrated yet**.
- Session resume after a service restart (same game session UID) and incident detection (spins/contact never
  coached as technique): implemented and tested.

- **Car setups per track** (`carsetup/`, Car setup tab, `/api/carsetup`, engineer setup facts): sourced catalogue of
  454 published F1 25 setups (27 tracks for the 2025 cars, 24 for the 2026 Season Pack cars, never mixed), menu
  ranges with confirmed vs observed ends, deterministic recommendations with provenance, "your setup vs recommended"
  and single-variable setup experiments. Real-data check: the PS5 Austria setups fit every confirmed 2025-car range
  (`tests/recorded/test_carsetup_real.py`); no recommended setup has been driven or validated by pitwall.
  See `docs/research/f1-car-setups.md`.

- **Race strategy engineer** (`pitwall/strategy`, tables `strategy_laps` / `pit_stops`, Drive › Car strategy tile,
  Review › Strategy, `/api/strategy/live`, `/api/sessions/{sid}/strategy`, strategy radio calls and intents): **unit + synthetic;
  recorded** for decoding (every car's LapData as `RaceTiming`, the player's TyreSets), gaps, fuel, tyre wear,
  TyreSets, forecast and AI pit-stop timing (committed PS5 Austria and Monza excerpts; the full 71-lap Austria race
  checked manually with `scripts/strategy_check.py`: car 14's stop measures 18.9 s, burn model b1 0.0236 kg/s
  R^2 0.85, fuel within 0.35 laps of the game's figure at every lap end, predicted rejoin within one place of the
  game's in 72.7 % of samples over both session UIDs but only 44.6 % in the second). Safety car / VSC, rain, the
  inters/wets crossover and the player's own pit stop are **synthetic only** (`race-strategy-demo`; one real
  player stop's entry, exit, lane and stationary times were seen in the owner's 2026-10-11 Austria capture, checked
  manually, but the capture ends on the out-lap, so its loss was not measured). Heuristics are
  marked `[H]` in the code (70 % wear limit, the undercut bands, the SC/VSC loss factors, traffic 1 s, the ideal-lap
  cost model, lift-and-coast limits, the 15 min forecast horizon). End to end on an isolated server (2026-10-11):
  the full Austria race streamed over UDP at 6x gave the same lap records and car 14 stop (18.9 s) as the headless
  check, the Drive tile and Review › Strategy rendered at iPad and phone sizes, and the radio answered the
  strategy, gaps, fuel, tyres and weather intents instantly (no LLM); the synthetic race's VSC box, rain, fuel and
  undercut-threat calls were said in speak windows at normal intensity. **Not live-validated**;
  `capabilities.py` is unchanged. Review fixes (2026-10-11, unit + synthetic, the recorded fixtures regenerated): a
  flashback into a stop re-opens it (no phantom one-lap stop), a lapped player's race ends a lap early (no false
  "fuel critical"), the fuel verdict is judged at the line, pit-window calls are said once (not "laps 19 to 19"
  every three laps) and wait three laps after a stop when only the game's figure closes the window, no rain call
  for a change after the flag, no gap calls under SC / VSC ("within a second" is detail now), "this lap" only once
  the pit entry is known; every call has plain words for simple wording (radio, tile, Review), the tile is shown in
  races of 8 laps or more, and the Coach radio strip shows the newest strategy alert while the radio is off.

## Dashboard v2 (React + HeroUI, `web-react/`), 2026-10-11

Built to the approved design (`docs/ui/design-spec.md` v2, coach-first; `docs/ui/mockup.html`) in lanes (spec 14.1).
It replaces the Svelte dashboard (`web/`, now frozen to fixes only) at `/`, with `/next/` kept as an alias for a week
(`web-react/README.md` "Switch-over"). **Switched over 2026-10-11:** `src/pitwall/api/app.py` serves `web-react/dist`
(built with `npm run build:root`, which `scripts/release.sh` and `make web-react` now do) at `/` and `/next/`; the
Svelte build is only a fallback for missing files and is served alone only while web-react is not built. `index.html`
is `no-cache`, hashed assets immutable; responses over 1 kB are gzip-compressed.

- **Built:** Drive › Coach (every state, band and overlay of spec 4.7-4.9, the Ready / No telemetry / Session complete
  cards, radio strip, Drive lock, screen wake lock), Drive › Car (pit wall), Track and Radio; Review › Sessions, the
  session page (Summary, Laps, Compare, Corners, Ask) and Review › Ask; Setup › Connect, Rig (walkthrough, all
  settings, rig check, upgrades) and Car setup; Settings › Drivers, Radio & voice, AI engineer, Display and System;
  the shell (rail, phone tab bar, mini radio bar, legacy redirects of every Svelte hash including
  `#/radio?token=…`). Every Svelte view has a React page (`web-react/src/switchover.test.ts`).
- **Review › Coaching plan and Progress** (phase 3) are built on D5; against a server without D5 they say so instead
  of guessing.
- **Backend additions:** D2 (bests), D4 (session state), D5 (progress, `clean_lap_count`) and D6 (one coaching point
  for screen and radio) are implemented with unit, synthetic and recorded tests (D4 also against the recorded Austria
  excerpt); the radio speaks the shared selection (`voice/hub.py` passes the lap's `coach` block, and the hub's
  intensity sets the selection's budget when nobody is seated). Not yet seen live. D1 (current-lap sectors) and D3 (driver status) are not built: the UI
  uses its documented fallbacks (last lap's sectors; the pit-status/speed garage heuristic).
- **Evidence tier: unit + recorded/synthetic fixtures + desktop browser only.** `npm run check` (tsc strict + vitest)
  passes; pages were checked in desktop Chromium against the live API (read-only) at iPad landscape and portrait,
  phone and light theme, and the `build:root` output was served at `/` and `/next/` the way the proposed `app.py`
  does. **Unverified:** the real iPad at 70 cm (Safari, Home Screen app, wake lock), a live PS5 session on Drive,
  the glance and family tests (spec 14.5), the React radio's Go live and push-to-talk over Tailscale HTTPS, the
  demo replay button and driver switching from the new UI. Purple (household record) needs D2 live; until the
  service runs the new backend only green SB and yellow appear.

## Game selection and capability profiles (branch `game-selection`, 2026-10-11)
- **Built:** the user tells Pitwall what they play (Setup › Game; `pitwall game list|show|set|clear`;
  `GET/PUT/DELETE /api/game`, `GET /api/games`). `src/pitwall/games.py` derives the catalogue from the
  `capabilities.py` rows x platforms (plus "Another game") and each entry's 23 feature statuses (supported, partial,
  not sent, not in Pitwall yet, unknown) from the adapters' `AdapterInfo.fields` plus a few code facts, each pinned
  by a unit test. Selecting a game switches on its input (it never turns another input off, and leaves alone an input
  that is receiving packets); the live snapshot carries the detected game, a mismatch (game, platform or F1 UDP
  format; real live data only) and a suggestion. The dashboard names data the game does not send instead of showing
  `-`; the engineer and the radio answer questions about such data deterministically (no LLM), also before any
  session; `pitwall doctor` has a `game` check; `/setup-pitwall` selects the game in step 6. A driver can have a
  usual game (Settings › Drivers › *Usually plays*), selected when they take the seat while no telemetry is live.
- **No capability status changed.** Feature evidence is the weakest of the row, the platform and each field's level,
  so F1 25 on PS5 (live-validated as a whole) shows most features at spec_implemented until per-field evidence is
  recorded. Known gaps: FM7 and Forza Horizon 6 have no row, so no entry of their own; GT7's energy-recovery value and
  wheel buttons are classified from community docs only.
- **Evidence tier: unit + synthetic + recorded.** Recorded: the F1 25 PS5 Austria and Monza excerpts resolve to
  `f1_25:ps5` and raise a `game` mismatch against another selected game; the Assetto Corsa PS5 excerpt resolves to
  `ac:ps5` and its fact sheet says the tyre data is not sent. Synthetic: the F1 demo with GT7 selected raises no
  mismatch. Headless-browser check on a scratch server: the first-run picker, choosing GT7 PS5 in Setup › Game (server
  without UDP), the GT7 wording on Drive, then the recorded Austria excerpt streamed over loopback UDP with GT7
  selected (mismatch on Review/Setup, on Drive only while stationary) and the one-tap switch to F1 25 PS5 while live. **Not verified:** any live console run of selection or mismatch (GT7, Forza and Assetto Corsa selection
  is tested through the API without sockets only); Setup › Game and the per-game Drive wording on a real iPad; the
  GT7 heartbeat or AC client started by a selection on real hardware.
- **Review round 1 (2026-10-11):** Assetto Corsa on PC no longer says it "doesn't send" what its Windows shared
  memory has (fuel, tyres, damage, ERS, DRS, flags, sectors, session type, weather): "Not in Pitwall yet", pinned to
  the research doc; consoles keep "not sent". The radio/engineer question types for damage, ERS, flags, weather and
  sectors no longer take over older questions ("brake at turn 4 in the rain" stays braking) and are instant only when
  the game really lacks the data; F1 questions about data it sends go to the LLM as before. A new session is no longer
  named after another port's game; an AC stream follows the configured platform; selecting GT7 without a console IP
  never starts a LAN broadcast; "Official corner names" is partial (8 of 28 F1 25 track sheets hand-checked; none for
  the 2026 format); `pitwall game set/clear` never write settings.json when a server answers slowly or with an error;
  the Connect hint names the port's own decoder. Dashboard: the AC/GT7 console IP leads the Drive card and is focused
  after choosing, a paused game keeps its mismatch (and a game chosen after the data stopped replaces it), the Drive
  mismatch band opens Setup › Game, "Not sent" is no longer red, games with nothing available collapse their 23 rows,
  idle inputs from earlier choices can be turned off from the result lines. Headless-browser check on a scratch
  server (loopback only, GT7 heartbeat and AC client stubbed): the screenshots are in the review scratch folder.

## Rig validation kit (branch `feat/validate`, 2026-10-11)
<!-- validation kit (lane validate) -->
Setup › Validation and `pitwall validate` turn the pending live checks into a guided checklist with evidence
(`src/pitwall/validate/`, `/api/validation`, docs/validation.md "Rig validation kit"). 12 tests: Home Screen app and
wake lock, glance test (each driver), one coaching message, one hour on Drive (optional), push-to-talk over Tailscale
with an AirPod, speak windows, the natural voice, braking-call timing, AC on the PS5, GT7 on the PS5, the game-choice
banner (only when the game-selection feature is present) and driver switching. Each test gets an automatic verdict
from fixed rules (thresholds that are first guesses are labelled heuristic) plus the driver's Worked / Didn't work;
disagreement is "to check". Reports are files only: `<data_dir>/validation/<run_id>/{run.json, report.json,
report.md}` (no database change).
- **Evidence tiers are kept apart:** every record is tagged live / recorded / synthetic / loopback (a recording sent
  with `pitwall send`) / unknown, and only live evidence can pass. **The kit never changes a capability status:** the
  report lists candidates for the maintainer as text (the package cannot import `capabilities.py`; a test checks it).
- **Never in the time-critical path:** the only code on the ingest thread is one membership test on the game-event
  kind; the cue engine, scheduler and Drive are unchanged. The radio hub gained an observer hook (one delimited
  block, nine one-line calls, zero cost without an observer) and an optional command handler. The LLM never sees
  validation state; the radio commands ("start validation", "next test", "worked", "didn't work", "what's the
  test", "finish validation") are answered by fixed rules before the engineer.
- **Evidence tier of the kit itself: unit + synthetic + recorded replays (+ the dashboard in a desktop browser).
  Not yet used on the rig.** Checked on 2026-10-11 against an isolated scratch server: the committed recorded excerpts
  replay as `recorded` and nothing passes; a synthetic stream and a recorded excerpt sent over loopback UDP are
  labelled `synthetic` and `loopback`; a scratch copy of the owner's real GT7 capture (`20261011-124608_udp33740`)
  shows variant C, 0 rejected, 21 GT7 sessions of which 17-18 are menus / loading ("streaming, not driving") and the
  laps 1:45.151 / 1:45.596 / 1:43.358 on the derived 3.80 km circuit (the game's best lap equals Pitwall's when
  sampled live); the owner's real F1 race capture (`20261010-221749_udp20777`, calls on all) matches 84 of 86 calls
  to a braking onset within 100 m (onset minus point: median +0.1 m, p10 -11.1 m, p90 +15.7 m). These are replays:
  they do not upgrade any status above. Also checked there: the radio commands through the typed-question path on a
  text-only radio (no speech recognition, no voice; ordinary questions such as "how are my tyres" and "radio check"
  still reach the engineer), and Setup › Validation in headless Chromium at 1180 × 820, 820 × 1180 and 390 × 844 in
  both themes (start, verdicts, a confirmation, a note, next, skip, finish, reports, Open report, Download JSON; no
  sideways scroll, no console errors; device reports arrive as `browser` / `localhost` and stop after finish).
- **Review fixes (2026-10-11, unit + synthetic + recorded, not live):** a telemetry pause no longer reads as a missing
  iPad report and the screen test reads only its own window; radio prompts only for the current test, and with no run
  only "start validation" is a command; adapter counters from before the run never fail AC / GT7; the glance test
  cannot pass without live laps; JSON reports honour "Leave out transcripts" (on by default). Re-checked on the
  isolated scratch server (replays, a loopback stream, headless Chromium at 1180 × 820 and 390 × 844).
<!-- end validation kit -->

## Known limitations
- Corner numbers are learned from speed minima (flat-out kinks are not corners). Official numbering/names apply only
  where a track sheet is hand-verified (Austria so far).
- Track model freezes after 3 clean laps; rebuild-on-demand is not exposed in the UI yet.
- Local LLM latency: ~9-12 s per answer with the 27B dense model at ~15 tok/s; the Mac is memory-constrained
  (swap in use). Too slow for conversational voice - see recommendations in the milestone report.

## Phase 5 - voice radio (2026-10-10)
- Built: radio hub (PTT on screen or wheel UDP Action, half-duplex gate, barge-in, question pipeline with instant
  deterministic answers and "Copy, checking" before LLM answers, quiet/resume commands, proactive lap summaries and
  coaching in speak windows), Parakeet STT, macOS `say` TTS + iPad device voices, iPad Radio page, Connect tab,
  Tailscale HTTPS, launchd service.
- **Live-validated on hardware:** iPad Safari + one AirPod over Tailscale: radio check heard (server voice and
  device voice). Speech input (PTT) on the iPad: pending driver test.
- Synthetic: proactive messages timing tested against replayed sessions (see tests/unit/test_voice_hub.py).
- Not yet: predictive in-lap braking cues (phase 6), neural TTS heard in a live session, Pi Bluetooth bridge.
- Neural radio voice (2026-10-10/11): Kokoro-82M (mlx-audio on Metal) in a worker process with `say` as the
  automatic fallback, a racing-name lexicon, audio post-processing and a Parakeet spoken-number check of
  pre-synthesised audio. Tested: unit tests against a fake worker, and opt-in `pytest -m tts` against the real
  engine (six phrases and every cue part in all four voices, memory bound, no GPL module loaded).
  **Evidence tier: synthetic only.** Naturalness was judged on six synthetic phrases (UTMOSv2 and listening in
  the voice lab, docs/research/tts-evaluation.md) and intelligibility by Parakeet round trips of synthetic text;
  it has not been heard during a live session yet (the `live` tier).

## Windows support and Claude Code setup (branch `windows-support`, 2026-10-11)
- Built: `compat.py` (per-platform folders, receive clock, file names, atomic replace, UDP socket options),
  Windows SAPI radio voice (`tts_engine=sapi`, in-box PowerShell, no new dependency), a clear "no voice questions"
  radio reply on Windows when the server has no speech recognition, `scripts/windows/` (install, run, firewall, Task
  Scheduler service, smoke test; `scripts/windows/README.md`), `pitwall doctor` (read-only setup check, `--json`)
  and the `/setup-pitwall` Claude Code skill (`.claude/skills/setup-pitwall/`) for macOS and Windows. CLAUDE.md is
  now contributor-neutral (with generic safety rules); the owner's machine notes live in the gitignored
  `CLAUDE.local.md`, which has to be copied into each checkout. On Windows only, opening the database retries a
  transient "database is locked" (up to ~3 s; seen once on the CI runner when four threads open a legacy database
  together); macOS raises at once, as before.
- **Evidence tier: CI-tested on Windows**, NOT live-validated with a game on a Windows PC. The `windows` CI job
  (GitHub `windows-latest`) runs the unit suite (default tiers, as on macOS) and mypy, `install.ps1 -NonInteractive`
  (Svelte dashboard, private data-folder ACL checked by doctor), the smoke test (a recorded F1 25 capture and a
  synthetic one streamed over loopback UDP; sessions and analysis of the synthetic laps checked through the API)
  under PowerShell 7 and Windows PowerShell 5.1, the background service under 5.1 (task registration and start,
  keep-alive restart after the server is killed, `stop` refused while telemetry is live, `stop`, `uninstall`), the
  firewall rules, and `pitwall doctor` there (PowerShell firewall-rule, network-profile, data-folder ACL and SAPI
  probes). The real SAPI synthesis tests run on the runner too (its voices: Microsoft David and Zira, en-US). Not
  exercised there: a console sending over the LAN, the task starting at a real logon, registering it as a non-admin,
  Windows' "allow access" firewall prompt, winget installs, the SAPI voice heard on a radio, Assetto Corsa against a
  real PS5.
- Mac behaviour is unchanged (same paths, clock, socket options, voices and radio replies; the no-STT push-to-talk
  reply is Windows-only); Windows code is guarded by `sys.platform`. Additive on macOS: the radio state's
  `stt_reason` field, and the Connect page's Tailscale link now comes from `tailscale serve status` (the serve that
  forwards to this Pitwall; the old `:8443` guess only when that cannot be read). Capability statuses in
  `capabilities.py` are unchanged.
- Windows limits: no server speech recognition by default (Parakeet needs Apple silicon; `stt_engine=whispercpp`
  with a whisper.cpp server is the untested alternative; typed questions and device voices work); SAPI starts one
  PowerShell per message (a persistent worker would be faster; cue timing on Windows is unmeasured);
  `time.monotonic` still ticks at 15.6 ms on Python 3.12 outside the receive clock; `service.ps1 stop` / `restart`
  end the server with `Stop-Process` (no clean shutdown like launchd's SIGTERM: the open capture loses its unflushed
  tail, queued database writes are lost and the session is not closed - a loopback shutdown endpoint would fix it);
  the Connect page lists only the default route's address (Windows' host-name lookup also returns Hyper-V / WSL
  `vEthernet` addresses with no interface names).

## Public launch prep: releases and install docs (2026-10-11)
- **Repository:** to be published as a new public repository, `github.com/Moment-Up/pitwall`, with a fresh history
  (the earlier private repository becomes an archive). The docs no longer mention a private repository or
  invitations. **Licence:** none chosen yet - all rights reserved; people are welcome to download, install and use
  Pitwall for their own racing, and a formal licence will follow (README "Licence and credits"; `pyproject.toml`
  keeps "Proprietary - all rights reserved"). HeroUI Pro stays separately licensed and is not covered.
- **Release zips** (`pitwall-<version>.zip` + `.sha256`, first tag `v0.1.0`): `scripts/package_release.py` adds the
  prebuilt React dashboard, `THIRD_PARTY_NOTICES.txt` and `RELEASE.txt` to the source at the tag, so users need only
  uv (no Node.js, no HeroUI Pro licence). `.github/workflows/release.yml`: **build** (Ubuntu, the only job with
  `HEROUI_AUTH_TOKEN`) -> **verify** (Windows, macOS, Linux runners: SHA-256, unzip, `uv sync`,
  `scripts/verify_release.py` serves the prebuilt dashboard and stores and analyses a SYNTHETIC stream; on Windows
  also `install.ps1 -NonInteractive` without Node.js, `pitwall doctor` and `smoke.ps1`) -> **publish** (tags only).
  Owner steps: `docs/releasing.md`.
- **Install paths** (README "Install", `docs/install.md`): 1. a release (recommended; macOS, Windows, Linux),
  2. Claude Code `/setup-pitwall` in an unzipped release or a clone (macOS, Windows), 3. from source (the new
  dashboard needs the builder's own HeroUI Pro licence; without one the classic dashboard is served). The skill
  detects a release folder (`RELEASE.txt` + `web-react/dist` built for `/`) and skips every dashboard build and
  Node.js/HeroUI step; in a clone without a licence it offers to download and verify the latest release and to run
  Pitwall from the unzipped folder (it never copies `dist` into the clone). `install.ps1` has a matching
  release-folder branch (default `-Dashboard auto` keeps the prebuilt dashboard, no Node.js or git).
- **Evidence tier: release pipeline not yet run on GitHub** (no release published yet, the workflow is not on the
  public repository's default branch yet). Run locally on macOS (Apple Silicon) on 2026-10-11: a zip packaged with
  `package_release.py` from a clean commit was checked with `shasum -a 256 -c`, unzipped, installed with
  `uv sync --all-extras` and run from the unzipped folder (served the prebuilt dashboard byte for byte; the synthetic
  demo simulated, replayed, reported and streamed over loopback UDP), and `scripts/verify_release.py` passed there.
  Not yet run: a release folder on Windows or Linux (the first `verify` run will be), the background services from a
  release folder, the release-to-release data move, the skill end to end in a release folder (its macOS
  release-folder branch was walked on 2026-10-11: steps 0, 3, 4, 5 and 9; the game, Tailscale and service steps were
  not), and the skill on a Windows PC at all (it drives the CI-tested scripts there).
- **Linux:** still not run with Pitwall itself. CI only builds the dashboards on Ubuntu; the release workflow's
  Linux `verify` job will be the first run of the server on Linux (synthetic telemetry, no game).

## Technique analysis: racing line, brake technique, handling balance, setup engineer (branch `feat/technique`, 2026-10-11)
- Built: F1 MotionEx decode (yaw rate, body slip, per-wheel slip ratio and slip angle; 8 new lap channels, no schema
  change), `pitwall.technique` (line, inputs, balance, setup map, pedal/assist awareness), `/api/technique`
  (session, balance, lap pair), engineer facts and intents (`line`, `technique`, `balance`, answered without the
  LLM on the radio), the experiment result's balance change, `pitwall technique` CLI, the `technique-demo`
  synthetic scenario. Units and signs: [research/f1-motion-ex-units.md](research/f1-motion-ex-units.md).
- Evidence tiers (nothing is live-validated):
  - racing line and brake/throttle technique: **recorded** (F1 25 PS5 races in a scratch replay; the GT7 line on the
    owner's capture, not committed); the committed recorded tests check MotionEx units and signs on the Monza and
    Austria excerpts;
  - wheelspin and handling balance: **recorded** (F1 MotionEx). Miami: Turn 3 mid-corner understeer on 3 of 3 laps
    including the best lap (verdict car); Silverstone Reverse: Stowe and Village mid-corner understeer verdict car,
    Club, Vale and Brooklands verdict driving. The thresholds are heuristics;
  - lock-ups: **synthetic only** (every real capture had ABS on);
  - setup suggestions: **unit / synthetic**. That a suggested change fixes a symptom is unverified.
- Integration run (scratch server, LLM off): the Miami and Silverstone Reverse races streamed over loopback UDP with
  `pitwall send` (the live ingest path decodes every MotionEx packet) and replayed; API, engineer and radio text
  questions (`line`, `technique`, `balance` answered without the LLM) and the dashboard at iPad and phone sizes were
  checked against the expectations above. A lap's ABS and traction control are the value seen on at least 90 % of
  its moving frames (else unknown): a zeroed CarStatus on the grid, or for the first seconds of a session joined at
  speed (TC 0 for 2.4 s at 281 km/h), no longer hides the lap's assists; a switch mid-lap still makes it unknown.
- Review fixes (2026-10-11, unit / synthetic / recorded-tested): a chosen `ref_lap_id` must exist (404) and be on the
  session's game, track and layout (422); speed classes come from the track model, never the chosen reference;
  line and inputs say "no other lap compared" instead of "within 1 m everywhere"; standing starts and laps more than
  7 % off the best clean lap stay out of the balance and the habits; the "car" verdict is about the session's best
  clean lap only; "ABS off" only when every lap had it off; no brake bias or pressure suggestion with the braking
  assist on; no setup facts for synthetic sessions; one short spoken sentence per technique fact, answers led by
  what was asked (lock-ups, wheelspin, trail braking, oversteer...) and corners by curated name.
- Known limits: slip and balance only for F1 25 (AC, GT7 and Forza do not map slip or yaw yet: unknown); a generic
  F1 car in UDP format 2025 cannot be told apart from a 2026 car, so the Setup page sends the car format the driver
  chose (`?car_format=`), and the engineer's "Setup to try" fact states a change only when it is the same on both
  cars; facts use the stock brake tolerances (the fact builder has no rig profile) and cannot see running
  experiments.
- Cross-lane: storing `wheel_slip_fl/fr` switches on the rig check's lock-up metric for new laps; with ABS on for
  every lap it now says "ABS on: the game prevents lock-ups." (still unknown) rather than "No front lock-ups
  detected" (`rig/rig_check.py`, delimited feat/technique line).

## Goals, streaks and summaries for every driver (lane motivation, schema v3), 2026-10-11
<!-- lane motivation -->
- **Built:** goals (lap time, clean laps in a row, steady laps, clean F1 race) with suggestions from the driver's own
  history, badges and streaks, Today's 3 things per session, the weekly digest (JSON, Markdown, printable HTML), the
  `motivation` worker and `/ws/live` note, one radio line per reached goal (at most two a session), engineer facts and
  the `goals` intent, `pitwall goals | recap | digest` (`src/pitwall/motivation/`, `api/routes_motivation.py`).
- **Evidence: unit and synthetic tested; recorded-tested on F1 25 PS5 captures in scratch (not committed); not
  validated live.** `scripts/motivation_acceptance.py` replayed 17 of the owner's captures (F1 25, GT7, AC) into a
  scratch database: 9 evaluable races (6 without a penalty, none without contact), Austria/Haas suggestion "a lap
  under 1:10.000" (ideal lap 1:09.962), the expected badges and recaps. A scratch `serve` (HTTP 8825 / UDP 20825)
  fed the 2026-10-10 Austria capture with `pitwall send`: one `motivation` note, the goal "a lap under 1:12.000"
  reached on lap 63 (1:11.745), one radio line queued. Committed fixtures: `tests/recorded/test_motivation_recorded.py`.
- **Limits:** race goals are F1 only (GT7, AC and Forza send no session type or penalties) and only for sessions
  recorded from this version (`total_laps` is stored in `sessions.info` from v3; older races are not evaluable). In
  GT7, AC and Forza "clean" means no pit lap, reset or flashback (no track-limit data). Race lap 1 is skipped by
  steady-lap windows because F1 25 flags only some race lap 1s as standing starts.
- **Migration checked by hand:** a v2 database made by the base commit's code (`git archive 181d85c src`, Austria
  fixture replayed) opened with this branch: version 3, `goals` and `ix_goals_driver` created, sessions and laps
  intact, a goal created and a recap served; reopening is idempotent; the old build reopening it writes version 2 and
  ignores `goals`, and this build sets 3 again with the goal intact.
- **Read budgets** (scratch, 2 000 sessions / 20 000 laps with 8 KB traces, M4 Max): recap 122 ms, badges 126 ms,
  digest 137 ms, goals 93 ms; the worker's first lap of a session 94 ms (once), then 0.5 ms a lap.
- **Dashboard, end to end in scratch (recorded data over real UDP, not a game):** the built React dashboard on a
  scratch server (LLM off, text-only radio). A seated driver with the goal "a lap under 1:12.000" at Austria/Haas and
  the 2026-10-10 Austria capture sent with `pitwall send --speed 10`: one `motivation` note, the GOAL REACHED chip on
  Drive at iPad (1180x820) and phone (390x844) size, the radio line queued, the Session complete card's three things
  and badge, "Goal reached" in Summary, and the radio question "How am I doing on my goal?" answered from facts.
  Review Progress (goals, the goal sheet with a server refusal, the week, badges) and Summary checked at both sizes on
  the replayed captures. The Svelte dashboard still works with a goal note on the socket. Not validated live.
- **Fixes after review (2026-10-11):** the `goals` intent no longer takes over braking, target-lap, best-lap or
  comparison questions (new `week` and `badges` intents answer "how many laps this week?" and "what badges have I
  got?"); reopening a reached goal is refused while the driver's own laps still reach it (409 `still_reached`, Reopen
  is offered only for a session now someone else's); best-lap badges and recaps name the car; untimed sessions get no
  three things and are not counted in the week; race lap 1 left out of in-session gains; mid-session incomplete laps
  end a clean run; a lapped finish (or a red-flag finish) counts when F1's chequered flag was recorded and the last
  lap ended after it; laps overlapping the safety car / VSC (F1 `SCAR` events, lap receive times from the lap meta)
  are left out of steady laps; steady-lap suggestions are tied to one track; the Drive recap is fetched again once
  the car is known (the Ready card's lap-time goal row); another driver's session is never celebrated as the seated
  driver's; every goal reached in a session is named, celebration first; no empty progress bars; radio-safe spoken
  goal facts; id-only F1 car names ("Unknown team (id 214)") are left out; a driver with no sessions can be given a
  goal; `repo.scratch_relabel_session` (was `rewrite_session_origin`) refuses a database inside a git checkout.
  **Evidence:** unit and synthetic tests; the 22 owner captures replayed in scratch again (same 9 evaluable races,
  6 without a penalty, 18 badges; every recorded CHQF comes 3-6 s before the last lap's end, as the lapped-finish
  rule assumes; the one `SCAR` event, a "resume race" with no deployment, marks no lap); a scratch server fed the
  Suzuka capture over loopback UDP (Ready card goal row once the car arrived, GOAL REACHED, "2 goals reached" first on
  Session complete, "Sam's session" after the seat moved). A real lapped finish and a real safety car are not in the
  captures: those two rules are unit-tested only. Not validated live.
<!-- end lane motivation -->

## Pace vs AI difficulty (branch `ai-pace`, schema v4, 2026-10-11)
- Built: the driver's best clean lap against the typical AI car of the same session (the median of the AI cars' best
  representative laps), from the game's own telemetry only: F1 Session History (packet 11, every car's lap list)
  and `Session.aiDifficulty`. No website data. `sessions.ai_difficulty` and the `session_ai_pace` table (schema
  v4 - developed as v3 next to goals and renumbered when both landed; additive migration, no backfill: older
  sessions stay unknown; `pitwall ai-pace backfill --captures DIR` fills them from raw captures, never creating
  sessions). Per driver x track x car class x session category x weather
  over time (`GET /api/drivers/{id}/ai-pace`), a suggested AI level in three tiers (measured fit over at least two
  levels five apart, an estimate from the driver's own slope at other tracks, or direction only), engineer facts and
  two deterministic radio intents ("how am I doing against the AI?", "what AI level should I use?", and parents'
  words such as "is the AI too hard?"), Review › Session summary tile, Review › Progress "Against the AI" (a race that
  could not be compared says why), Review › Coaching "Suggested AI difficulty" (a bound has no range; with one level
  raced, the next level to try, five away), and one line on Drive's Session complete card. Code: `adapters/f1/adapter.py` (`_on_session_history`), `core/ai_pace.py`
  (ingest-side collector, worker processor, backfill), `analysis/ai_pace.py`, `analysis/ai_level.py`.
- Ingest stays O(1): a Session History packet costs a byte-slice compare; a car's lap list is decoded and emitted
  about once per lap (about 4 % of history packets). A LapData packet adds two strided 22-byte slices (every car's
  result and pit status) and a compare; cars are looked at one by one only when one changed. The summary runs on the
  analysis worker after every lap of the player and at the session's end; a full queue drops the AI job (never a
  lap).
- What real data showed (PS5 F1 25 captures, 2026-10-10/11): the first 2-3 Session packets of every session have an
  unfilled tail (aiDifficulty 0, gearboxAssist 0), so a reading only counts when gearboxAssist is 1-3; once ignored,
  every session read a single level (16 sessions), so a second level marks the session "difficulty changed". When
  the driver skips to the results, F1 25 marks every remaining car finished where it is, one LapData packet after the
  player's own finish (7 races; cars up to 3.1 km from the line), and fills in their laps in progress: those laps are
  left out (`results_skip`: a result leaving "active" more than 50 m past the line; cars that really finish flip
  1-24 m past it), and the 1.3 s completion-timing check (driven laps agree within 1.1 s) is the backstop. A stint's
  endLap is the lap before the in-lap (two AI stops checked against LapData's pit status): the in- and out-laps are
  endLap + 1 and + 2, and every lap LapData shows a car in the pit lane is a pit lap too. In a real online lobby a
  human's car was taken over by the AI mid-race (its slot read aiControlled 0, then 1): the laps up to the takeover
  are left out (`not_ai_driven`). Scenario modes pre-fill history laps (rejected as not observed); online lobbies
  report the lobby's level; Session History of the previous session arrives at the start of a new one and is
  ignored. Red flags (until the next lights out) and laps faster than 90 % of the typical AI best are left out
  too (defensive: no real capture had either).
- **Evidence tier: recorded + synthetic + desktop browser.** Recorded fixtures (Austria excerpt: level 35, 19 AI cars,
  every LapData lap time equals the history time; Monza excerpt: too few AI cars), an opt-in acceptance test on the
  full captures (`PW_AIPACE_REAL_CAPTURES=<dir>`: exact ms for Austria +5.06 % / rank 20 of 20, Silverstone +7.67 %,
  Melbourne F2 -3.26 % / rank 1 of 22 (fastest AI 1:37.642, the fastest lap an AI car drove), the Austria scenario
  -4.96 % / -6.51 %, Monza and the online Suzuka lobby too few AI cars), every accepted AI lap cross-checked against
  every car's LapData (448 laps: the same time, never in the pit lane, never ended off the line), a synthetic
  pipeline test with known injected laps, and the captures streamed over loopback UDP into a scratch server and
  checked in headless Chromium at iPad and phone sizes. **Unverified:** a live session through the service, a real
  safety car, VSC or red flag (synthetic or unit evidence only), time trial, the format 2026 Season Pack
  (spec-only), and the measured / estimated suggestion tiers on real data (every track and class the owner has raced
  so far has a single level, so every real suggestion is direction only).
- Follow-ups: the field model still treats slots past numActiveCars as unknown (a real scenario had an active AI car
  in slot 18 with numActiveCars 17; the AI pace path uses the slot flag); assists stored from the unfilled Session
  tail at the start of a session should get the same gearboxAssist guard; car-performance mode and career R&D are not
  in the suggestion key (they only widen the fit's spread); the suggestion assumes the gap is linear in level over
  the measured span; a pause longer than the idle timeout splits a session and the second part loses its earlier
  AI laps (`not_observed`).

<!-- --- lane install --- -->
## One-line install, `pitwall update`, community files, README GIF (2026-10-11)
- **One-line installer and `pitwall update`:** unit-tested; recorded-tested end to end on macOS Apple Silicon (local
  fake GitHub, real packaged zip, Austria fixture streamed before and after an update).
  `scripts/install/install.sh` (POSIX sh: tests under sh and dash), `install.ps1` (Windows PowerShell 5.1 and 7),
  `src/pitwall/install/` (`pitwall install-finish`, `pitwall update [--check|--rollback]`), `/api/update` and
  Settings › System's update card, doctor's offline `update` check, `PITWALL_UPDATE_CHECK=auto|manual|off`.
- **Release workflow steps:** not yet run on GitHub until the first tag (installer assets, "What changed" from
  CHANGELOG.md, the `--from-zip` install in verify, the `installer-smoke` job).
- **Service repoint (launchd / Task Scheduler) and legacy adoption:** unit-tested with fakes only, not run on a real
  service. The review fixes (service script exit codes, the new version's own tag before success, a second "nobody
  drives" check just before the switch, a paused game counting as driving for 2 minutes, a failed move-back that
  leaves the old service stopped, renamed release folders, `~` and conflicting data folders, downgrades) are
  unit-tested with the same fakes.
- **Windows and Linux:** CI only.
- **README GIF:** recorded tier (real PS5 capture streamed over loopback UDP), not live.
- Community files: issue forms, PR template, CONTRIBUTING.md, SECURITY.md, CHANGELOG.md. Capability statuses in
  `capabilities.py` are unchanged.
<!-- --- end lane install --- -->

## Next
1. Dashboard v2 rig acceptance (spec 14.5) on the iPad with live PS5 telemetry. Remove `/next/` and the Svelte
   fallback a week after the switch-over (2026-10-18).
2. Neural TTS (Kokoro bm_fable worker) as the default radio voice.
3. Rig setup review fixes + research revision 2 data.
4. Assetto Corsa: a full multi-lap session on the PS5 through the service (laps stored and timed, lap coaching,
   full-lap track length, R gear, steer unit); a layout-aware track id if the console ever names the layout.
5. Track knowledge wrap-up: verify all corner sheets, AI-field model, outline + heavy-stop prior.
6. Live validation on the PS5 of: cues, profiles split, GT7. Run it with Setup › Validation (rig validation kit).
7. New adapters: Project Motor Racing (after a PS5 capture), GT Sport, F1 24/23, pcars2/AMS2; Windows relay.
