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
