# Development status

_Last updated: 2026-10-11 (public launch prep: release zips, install docs, Windows; earlier the same day: dashboard v2
React + HeroUI switch-over prep; previously 2026-10-10 evening: profiles, setup, cues, multi-game, track knowledge,
cloud AI)._

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
  checked against the expectations above. A zeroed CarStatus on the grid (ABS off, TC 0 before the start) no
  longer hides lap 1's assists.
- Known limits: slip and balance only for F1 25 (AC, GT7 and Forza do not map slip or yaw yet: unknown); a generic
  F1 car in UDP format 2025 cannot be told apart from a 2026 car, so the Setup page sends the car format the driver
  chose (`?car_format=`), and the engineer's "Setup to try" fact states a change only when it is the same on both
  cars; facts use the stock brake tolerances (the fact builder has no rig profile) and cannot see running
  experiments.
- Cross-lane: storing `wheel_slip_fl/fr` switches on the rig check's lock-up metric for new laps; with ABS on it
  reports "No front lock-ups detected" (still unknown) instead of "not recorded".

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
<!-- end lane motivation -->

## Next
1. Dashboard v2 rig acceptance (spec 14.5) on the iPad with live PS5 telemetry. Remove `/next/` and the Svelte
   fallback a week after the switch-over (2026-10-18).
2. Neural TTS (Kokoro bm_fable worker) as the default radio voice.
3. Rig setup review fixes + research revision 2 data.
4. Assetto Corsa: a full multi-lap session on the PS5 through the service (laps stored and timed, lap coaching,
   full-lap track length, R gear, steer unit); a layout-aware track id if the console ever names the layout.
5. Track knowledge wrap-up: verify all corner sheets, AI-field model, outline + heavy-stop prior.
6. Live validation on the PS5 of: cues, profiles split, GT7.
7. New adapters: Project Motor Racing (after a PS5 capture), GT Sport, F1 24/23, pcars2/AMS2; Windows relay.
