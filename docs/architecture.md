# Architecture

```
 Game (PS5 / Xbox / PC)                                 Phone / tablet / Mac browser
        | UDP 20777                                              ^   REST + WebSocket (/ws/live, 20 Hz pull)
        v                                                        |
 +--------------------+   CapturedPacket   +--------------+      |        +---------------------------+
 | UdpListener thread |------------------->| PacketRouter |      +--------| FastAPI (asyncio)          |
 |  (or ReplaySource) |                    |  auto-detect |               | /api/* /ws/* web-react/dist|
 +---------+----------+                    +------+-------+               +----+------------------+---+
           | non-blocking submit                  | adapter.decode()           |                  |
           v                                      v                            | reads            | asks
 +--------------------+              +-------------------------+               v                  v
 | BackgroundCapture  |              | GameAdapter (pure)      |     +----------------+  +------------------+
 | Writer (.pwcap,    |              |  F1 2025 / 2026 formats |     | SessionAnalyzer|  | RaceEngineer     |
 | zstd, raw packets) |              |  -> CarFrame / Session  |     |  (on demand)   |  | intent -> facts  |
 +--------------------+              |     Info / GameEvent /  |     +-------+--------+  | -> LLM -> ground |
                                     |     CarSetup / LapCompl.|             |           | -> fallback      |
                                     +------------+------------+             |           +---+--------------+
                                                  v                          |               | OpenAI-compatible
                                     +-------------------------+             |               v
                                     | SessionManager          |             |       llama-server (Qwen)
                                     |  LiveState (O(1) update)|             |       127.0.0.1:8081
                                     |  LapAssembler           |             |
                                     +------+----------+-------+             |
                         LapJob queue       |          | DbWriter queue      |
                                            v          v                     |
                          +------------------+    +------------------------+ |
                          | AnalysisWorker   |--->| SQLite (WAL)           |<+
                          |  persist lap     |    |  sessions, laps (npz), |
                          |  learn TrackModel|    |  events, setups,       |
                          |  pick reference  |    |  track_models (vers.), |
                          |  compare (dist.) |    |  reference_laps,       |
                          |  observations    |    |  observations, convos, |
                          |  drills          |    |  reference_choices,    |
                          +------------------+    |  drills, goals,        |
                                            ^     |  strategy_laps,        |
                                            |     |  pit_stops             |
                                            |     +------------------------+
                                            | DbWriter (strategy_laps, pit_stops)
 SessionManager --(deque append)--> +-------+--------------------+
   RaceTiming (<= 2 Hz, all cars),   | StrategyWorker ("strategy")|--> LiveState.strategy (on change)
   TyreSetsInfo, player frames,      |  StrategyEngine (pure,     |--> notify("strategy_call") -> RadioHub
   laps, events, session info        |  game clock, no LLM)       |    -> RadioScheduler speak windows
                                     +----------------------------+
```

## Threads and the critical path
| Thread | Work | Never does |
|---|---|---|
| `udp-<port>` | `recvfrom` -> monotonic timestamp -> capture queue -> decode -> session state | disk I/O, DB, analysis, LLM |
| `capture-writer` | zstd-compress raw packets to `.pwcap` (flush every 1 s) | - |
| `lap-analysis` | per-lap: persist, track model, reference, compare, coaching. Its one queue also takes bests refreshes (`BestsRequest`), AI pace summaries (`AiPaceJob`, `core/ai_pace.py`) and coachref tasks (`_Task`: reference choice, drill start / stop), in order with the laps | touch live sockets |
| `db-writer` | all SQLite writes, one transaction per job | - |
| `motivation` | after a live lap / at session end: mark goals reached (exactly once), notify `motivation` | run on ingest (its note handler only queues, O(1)) |
| `strategy` | race strategy engine (`pitwall/strategy`): gaps, pit loss, tyres, fuel, weather, calls; per-lap records | touch sockets, block ingest (fed by one lock-free deque append per item) |
| `spotter` | the spotter (`pitwall/spotter`): decodes every car's Motion, runs the state machine on the game clock, publishes `live.spotter`, hands calls to the radio loop | block ingest (fed by one `SimpleQueue.put` per Motion packet), touch the DB |
| asyncio (uvicorn) | REST, WebSocket snapshots (pull model), LLM calls (async HTTP) | block on DB (uses `to_thread`) |

Every ingest-thread hook of the v0.2.0 features is O(1) (a deque append, a field write or a counter). The combined
budget is checked on the Austria race excerpt by `tests/recorded/test_ingest_budget_combined.py` (decode, session
handling and every hook per packet: median, p99 and maximum under fixed limits).

Backpressure: capture queue (200k packets) and lap queue are bounded; overflow is counted and logged, never
silent. Dashboard clients pull snapshots at a fixed rate, so a slow browser cannot slow ingest; per-client
notification queues drop the oldest message for that client only.

Measured (synthetic, M4 Max): full replay of a 7-lap, 117k-packet session including all analysis: ~0.6 s;
per-lap processing 7-18 ms; decode <30 us/packet.

## Data model
`model/telemetry.py`: `CarFrame` (high-rate, player car), `SessionInfo` (slow), `GameEvent` (discrete),
`CarSetup`, `LapCompletion`, `FieldSample` (all cars, field model) and `CarLapHistory` (one car's lap list as the
game reports it, F1 Session History; emitted only when it changed). Units in field names; `None` = unknown; `Wheels` always FL, FR, RL, RR; per-game

`CarSetup`, `LapCompletion`; F1 only: `FieldSample` (the other cars, field model), `RaceTiming` (every car's position,
gaps and pit state at <= 2 Hz, plus one at each pit-status change) and `TyreSetsInfo` (the player's tyre sets on
change), both for the race strategy engine. Units in field names; `None` = unknown; `Wheels` always FL, FR, RL, RR; per-game
ground plane declared by the adapter (`AdapterInfo.ground_plane`). Field provenance per game in
`AdapterInfo.fields` -> `/api/capabilities`.

## Game selection and capability profiles
`games.py` (pure, cached, no I/O) builds the game catalogue from `capabilities.PLANNED` (one entry per row and
platform, plus `other:any`) and, for each entry, the status of every user-facing feature (supported / partial /
not_sent / not_implemented / unknown) from `AdapterInfo.platforms` and `AdapterInfo.fields`, never stronger than the
weakest of them; a field the adapter does not declare is unknown, never "not sent". The selected game is a
`SettingsStore` section (`game`), served by `api/routes_game.py` and `pitwall game`. It drives setup flows (inputs,
guides, doctor, engineer answers with no session). What the screens say about live data follows the *effective*
game: the one detected from the live session (`LiveState.snapshot()` on the web thread, from state the ingest thread
already writes; the router stores one attribute per newly detected sender port, nothing per packet), else the
selected one. Before a session's first info packet the detection is the frame's game, else the game that started the
session (`reset_session(..., game)`). Its status counts only packets a decoder accepted (`last_accepted_mono`), so
stray packets never make old data "live"; a selection made after the data stopped wins over that stale data. A
platform the game does not report (Assetto Corsa) is taken from the input's configuration to pick the entry, never
for a mismatch; an ambiguous platform resolves to the weakest-evidence main entry. The selection never filters
packets or changes an adapter. Selecting GT7 switches its input on only with a console IP: without one the input
broadcasts its heartbeat to the whole LAN, so that is an explicit choice (Setup › Game "Search the network").

## Analysis pipeline (deterministic)
1. **Lap assembly** (`analysis/laps.py`): lap boundaries from the game's lap counter + official lap time;
   flashbacks detected by session time going backwards (rewound samples dropped, lap flagged); pit in/out,
   joined-mid-lap, packet-loss gaps -> `incomplete`; game-declared invalid -> `invalid`; race lap 1 timed from the
   start signal (GT7 rolling starts) -> `race_start`; a lap the game timed that the adapter could not place on the
   track (`LapCompletion.untraced`) is stored with its time and no samples -> `no_trace` (+ `incomplete`). Only
   `clean` laps can be references or train the track model. Games that stream in their menus (GT7) decide in the
   adapter where a session starts and ends: it emits nothing outside a session and ends one with `session_ended`.
2. **Distance domain** (`analysis/distance.py`): every lap resampled to a 1 m grid by lap distance; time at
   each metre gives the cumulative delta. Edges extrapolated with measured speed (<=25 m).
3. **Track model** (`analysis/track.py`): corners = significant speed minima (prominence 8 km/h) of the
   median of up to 5 clean laps; entry = braking onset, exit = full throttle; analysis segments partition the
   lap so corner deltas sum to the lap delta. Versioned per (game, track); frozen after 3 laps.
4. **Braking** (`analysis/braking.py`): hysteresis 0.10/0.05, stab merging, sub-sample onset/release,
   time-to-peak, release time, trail-braking distance, coasting, throttle pickup/full.
5. **Comparison** (`analysis/compare.py`): compatibility gate (game/track/car/wet-dry/assists block;
   compound/setup/fuel/temperature warn), per-corner deltas.
6. **Coaching** (`analysis/coaching.py`): rules with thresholds above measurement resolution; measurement
   confidence vs habit consistency reported separately; later braking never suggested on its own.
7. **Strategy** (`analysis/strategy.py`): fuel/lap median over green laps, wear-rate regression, tyre-limited
   pit window.
8. **Technique** (`technique/`, feat/technique; on request, cached in memory, never stored): racing line as
   lateral offsets from the driver's own reference lap (`line.py`: coarse + fine nearest-point matching, inside side
   from the reference's curvature, so any frame handedness works); brake/throttle technique per corner on native
   samples with pedal-aware notes (`inputs.py`, `rig.py`); handling balance per corner phase from front-minus-rear
   tyre slip angle at the limit, slides from tail-out body slip or counter-steer, car-or-driving verdict from the
   best lap (`balance.py`); one-parameter setup suggestions for car symptoms that feed `carsetup.experiments`
   (`setup_map.py`). `session.py` orchestrates (`analyse_session` pure for facts, `TechniqueAnalyzer` with the DB
   for `/api/technique`), `thresholds.py` lists every threshold with a heuristic flag. Inputs: the lap trace's
   `TECHNIQUE_CHANNELS` (F1 MotionEx yaw rate, body slip, axle slip angles, per-wheel slip ratio; NaN for other
   games), decoded by the F1 adapter in one `unpack_from` per MotionEx packet; nothing else on the live path.
9. **Pace vs AI difficulty** (F1 only; game telemetry only). Ingest thread: the F1 adapter turns Session History
   into `CarLapHistory` when a car's lap list changes (a byte-slice compare per packet) and reports
   `SessionInfo.ai_difficulty` only when the Session tail is filled in (gearboxAssist 1-3); `core/ai_pace.py`
   `AiPaceCollector` keeps the latest lap list per car, the difficulty readings, weather, safety car and red flag
   periods and flashbacks of one *game* session (O(1) per item, reset on a new game session UID). The adapter also
   watches every car's LapData with two strided byte slices per packet (result and pit status): a car finished away
   from the line (a results skip, a retirement) marks its lap in progress as filled in by the game, and pit-lane laps
   join the stint-derived pit laps; an AI flag turning on after a human's marks the laps before the takeover. After every lap of the player
   and at the session's end `SessionManager` hands a bounded snapshot (`AiPaceJob`) to the analysis worker's queue
   without blocking (dropped when full); `AiPaceProcessor` summarises it (`analysis/ai_pace.py`: eligible AI laps,
   the typical AI car = median of the AI cars' best laps, gap and rank), stores `session_ai_pace` through the writer
   and publishes `snapshot.ai_pace`. `analysis/ai_level.py` turns a driver's stored points into a suggested AI level
   on request (`GET /api/drivers/{id}/ai-pace`, the engineer's facts). Synthetic sessions and replays are stored but
   never feed a driver's series or suggestions.

   pit window; with ``stint_only`` the current stint's wear with whole-percent bounds, the game's laps-left figure
   and new-set life, the fuel-burn model and lift and coast (used by `pitwall/strategy`).
8. **Race strategy** (`pitwall/strategy/`, worker thread, off the ingest path): gaps with a settle rule against the
   game's own glitches, every car's pit visits and the measured pit loss, undercut / rejoin, safety car / VSC,
   forecast, and rate-limited proactive calls through the radio scheduler. Per-lap `StrategyLapRecord`s and pit
   stops are stored (tables `strategy_laps`, `pit_stops`, schema v5) for Review › Strategy. The live view
   (`strategy`, about 2-3.5 kB) rides the static merge on `/ws/live` (`api/live_feed.py`): sent when
   `LiveState.strategy_rev` moved, at most every 2 s, and in a new session's first snapshot, left out otherwise (the
   client keeps it, `lib/live.ts` `STATIC_KEYS`).

### Reference choice and practice drills (coachref)
`core/coachref.py` (`CoachRef`, created by the runtime and attached to the `LapProcessor`) plugs into the lap
pipeline at four points, all on the `lap-analysis` thread:
1. **Resolver before compare.** `LapProcessor._choose_reference` asks `CoachRef.resolve` for the session driver's
   chosen reference (`reference_choices`: own best by default, family record, another driver's best or a saved
   lap; compatible laps only, real driving only). No stored choice, an unowned, synthetic or replayed session ->
   the own-lap rule, unchanged. The descriptor (kind, holder, labels, `brake_clamped`, `frozen`) is merged into
   `snapshot.reference` and the comparison (`reference`).
2. **Reword and clamp.** Against another driver's lap the observations are reworded with their name
   (`coach/reference_wording.py`, stored that way too) and the comparison carries `brake_clamp_m` (the driver's own
   braking point per corner); `coach/cues.reference_braking_zones` calls `min(their point, own point)` and skips a
   corner with no own point. Review analyses are never re-based on another driver.
3. **Drill hook.** After every stored lap `CoachRef.after_lap` evaluates an active drill (`coach/drills.py`, pure):
   the attempt becomes the lap's single coaching point (`kind: "drill"`, `coach.drills.with_drill`), live
   observations are filtered to the drill corner (all are stored), the cue plan holds only that corner
   (`CueEngine.set_drill_corner`) and the reference and clamp are frozen until the drill ends. A lap in other
   conditions than the drill's start (`DrillSpec.context`: car, layout, wet/dry, assists) stops it and never uses
   the frozen reference; grid starts, resets, stale data and safety-car laps are no attempts.
4. **`AnalysisWorker.submit_task`.** API and radio changes (choice, drill start / stop) run as tasks in the same
   queue as the laps, so drill and reference state need no lock; callers wait at most 5 s for a task to start (HTTP
   503 after, and the task is withdrawn), and one already running is waited for.
5. **Before the first lap.** The live session's context request (`LiveState` -> `AnalysisWorker.request_bests`,
   also sent when the session's wet/dry or assists change: F1's first packets carry default assists) reaches
   `CoachRef.on_context`, which resolves and publishes the seated driver's chosen reference while no lap of the
   session is in yet (`LapProcessor.refresh_reference`), so the delta runs from the first lap.

Storage (schema v6, new tables only): `reference_choices` (per driver, `game`/`track_id` `''` = every track; cascade
on driver delete) and `drills` (one row per drill, attempts as JSON; kept with a NULL driver when the driver is
deleted). API: `api/routes_coachref.py` (`/api/coachref/...`). Radio: drill intents in `ai/engineer.py` answered by
`CoachRef.radio_command` without the LLM (only an imperative starts or stops a drill; "who am I compared with?"
is a deterministic `reference` answer from `ai/facts.py`), and a `drill` fact (the running drill, or the result of one
driven in the session) for focus and summary questions. A drill attempt's radio message carries `meta.drill_id`, so the
validation kit can tell the lap's one drill point. The family's best lap in these conditions is labelled "Best in
these conditions" whenever it is not the family record (the REC lap in any conditions).

## AI engineer
`ai/facts.py` builds an ID-tagged fact sheet from the stored session analysis (the model never sees raw
telemetry). `ai/engineer.py`: rule-based intent (works offline; control commands never reach the LLM) ->
topic-filtered facts -> LLM with strict system prompt -> `ai/grounding.py` (every number must be a rounding
of a number in the cited facts; citations must exist) -> one corrective retry -> deterministic fallback.
`ai/providers.py`: OpenAI-compatible provider with model discovery and a circuit breaker.
`_RULES` is one ordered intent table (first match wins), pinned by `tests/fixtures/intents.json` (every question's
intent and corner, and a grounded deterministic answer for each). The radio never asks the LLM for its fast intents,
for a question only about data the game never sends (`games.capability_only`), or for any question while the car is
moving (on track at 8 km/h or more, or speed unknown): `deterministic_answer` covers every intent.
Technique facts (topics `line`, `technique`, `balance`) come from `technique/facts.py`; their intents are answered
deterministically and are radio fast intents (feat/technique).

## Radio policy (`voice/scheduler.py`)
One scheduler decides what is said and when. Message kinds (`voice/types.py`): `answer` and `control` (the driver's
own questions and commands), `cue` (braking calls), `alert`, `lap_summary`, `strategy`, `goal`, `coaching` (also a
drill point), `info` (detailed strategy notes) and `validation` (the kit's prompts). `ALLOWED_KINDS` per intensity:
quiet = answers, control, alerts, cues and validation; normal adds lap summaries, goals, coaching and strategy;
detailed adds info. Pending messages are dispatched by (priority, `KIND_RANK`, arrival): cues, answers and control
first, then alerts, lap summary, strategy, goal, coaching, info, validation. On track, `TALK_PER_LAP` (0 / 2 / 4)
caps the budgeted kinds (lap summary, goal, strategy, coaching, info) per driving lap; alerts, cues, answers and
validation are outside it. Every proactive message waits for a speak window (off the brake, steering nearly straight,
time before the next braking zone); the 2 s gap, the 60 s repeat filter and topic replacement (newest wins) still
apply. The gap also holds for a message the hub synthesised and held while something else was on air: it is released
2 s after the radio went quiet, never at once (`RadioHub._gap_ok`). A message cut by a braking cue is said again once
(`MAX_RESENDS`). `RadioHub.apply_driver` calls `drop_driver_messages()` when another driver sits down (unsaid lap
summaries, goals and coaching go; strategy and alerts stay), and a new live session id calls `reset_session()` (the
queue, budgets, repeat filter and a lap-bounded quiet period belong to the old session). The safety-car box and stay
calls and critical fuel are alerts outside the budget. The final lap gets its summary but no coaching point.
Questions are answered short on the radio (`deterministic_answer(short=True)`: one or two facts in their spoken
form). Strategy (`strategy/radio.py`) is the only source of fuel alerts.
The `say` frames are in [voice-protocol.md](voice-protocol.md).

<!-- --- spotter --- -->
## Spotter fast path (`spotter/`, `voice/spotter_radio.py`)

F1 25 only (the other games send the player's car only). No LLM anywhere on this path.

```
UDP thread: F1Adapter._on_motion --(FieldMotion: 2 packet refs + 4 ints)--> SessionManager.handle (first branch)
            +-> SpotterWorker.submit(item): SimpleQueue.put (C, non-blocking)                 [~1 us, no decode]
            SessionInfo and GameEvent{lights_out, flashback, red_flag, session_started, session_ended,
            chequered_flag} also forwarded; reset(session_id) on SessionManager._start / end()
spotter thread: q.get(timeout=0.25) -> decode (subset_struct) -> SpotterEngine.feed_motion -> live.spotter (swap)
            +-> calls -> sink(call) = SpotterRadio.on_call_threadsafe -> loop.call_soon_threadsafe(deliver)
asyncio loop: SpotterRadio.deliver -> mailbox / cut rules -> RadioHub._deliver(PCM made in advance, pcm_to_all)
```

The engine (`spotter/engine.py`) is pure: every time comes in as an argument and every duration is on the game clock
(header `sessionTime`), so receive bunching cannot shorten a debounce. Geometry (`spotter/geometry.py`): each car is
an `L x W` box (`spotter/dims.py`, per formula) in the player's frame from its forward and right vectors
(`worldRightDir` is the driver's right on real data). Gates, in order: disabled, not available, session type, red
flag, safety car (unknown counts as on), lights out + delay, paused, stale (no Motion for 250 ms), flashback mute,
pit, finished, slow; a closed gate forgets the traffic and never says "clear". The live block (`spotter` in every
`/ws/live` snapshot, about 230 bytes, with the car `length_m` in use for the bar scale) is swapped whole on every
Motion item and does not bump `LiveState.version`; `api/live_feed.py` sends a changed block without a new frame, so
the block going stale when Motion stops (a pause) reaches the iPad at once.
Offline: `spotter/score.py` (geometric ground truth) behind `scripts/spotter_check.py` and the recorded tests.

Radio priority contract (`voice/scheduler.py`, `interrupt_rank` / `may_interrupt`, the same rule as the radio lane's
urgent path): urgent (Priority.URGENT: urgent alerts and spotter calls) > cue > everything else; equal ranks never
cut each other. Spotter messages (`MessageKind.SPOTTER`) never go through the scheduler queue (its 100 ms tick is too
slow), are exempt from the budget, gap, repeat filter and speak window, and are allowed at every intensity. While a
car is alongside (`DrivingState.traffic_alongside`) no speak window opens, so a lap summary never starts wheel to
wheel. Delivery, the one-slot mailbox, heard pairing and the latency stamps are in `voice/spotter_radio.py`; the
phrase audio (both wordings, per engine and voice, STT-checked when the model is loaded) in
`voice/spotter_audio.py`. Settings: `SettingsStore` section `"spotter"` (`spotter/settings.py`), applied by attribute
swaps; nothing is persisted in the database.
<!-- --- end spotter --- -->

## Goals, badges and summaries (`motivation/`)
Pure rules (`rules.py`: clean runs, steady-lap windows, scopes, F1 race outcomes, personal bests, week arithmetic),
`goals.py`, `suggest.py`, `badges.py`, `recap.py` (Today's 3 things), `digest.py` + `html.py` (weekly digest),
`service.py` (the database side, shared by the API `api/routes_motivation.py`, the CLI and the worker), `facts.py`
(engineer facts, topics `goals` and `progress`) and `radio.py` (the goal line). Only goals are stored (table `goals`,
schema v3); badges, streaks, recaps and digests are derived from laps and events when read, from the driver's real
driving only (never replays, synthetic only on request). `worker.py` listens to `LiveState` notes (`lap`,
`event:session_ended`), evaluates on its own thread, flips a goal with one `UPDATE ... WHERE status='active'` and only
then publishes `live.notify("motivation", note)`: `/ws/live` forwards it as `{"type": "motivation"}` and the radio
hub queues one `GOAL` line (no lap identity, so it never holds its lap's coaching back). API reads never write. History reads take only the lap columns before `meta`;
F1 races with a safety car, or with a chequered flag but no stored last lap (a lapped finish), also read two receive
times from the lap meta (`t_recv_start_ns`, `t_recv_end_ns`, the events' clock) to judge the finish and leave laps
behind the safety car out of steady laps.

## Dashboard (`web-react/`)
React 19 + TypeScript (strict) + Vite + Tailwind v4 + HeroUI v3 / HeroUI Pro, built to `docs/ui/design-spec.md` (v2,
coach-first). FastAPI serves the built `web-react/dist` as static files at `/` and, for a week after the switch-over,
at `/next/` (an alias of the same files); `index.html` is served `no-cache` and the hashed `assets/*` immutable. The
Svelte dashboard in `web/` is frozen to fixes only and served only when `web-react/dist` is not built.
`web-react/README.md` has the layout and the switch-over details.

- **Routes** are hash routes `#/<area>/<page>[/<param>][?<query>]` over four areas: Drive (Coach, Car, Track,
  Radio), Review (Sessions, Coaching, Progress, Goals, Ask), Setup (Game, Connect, Rig, Car setup, Validation; it opens
  on Game) and Settings (Drivers, Radio & voice, AI engineer, Display, System). Every Svelte hash (`#/live`, `#/radio?token=…`, `#/sessions/<id>`,
  ...) is rewritten in place, keeping its query (`src/lib/route-parse.ts`).
- **Data:** one `/ws/live` socket for the whole app (snapshots at 20 Hz, the static payload every 5 s), the radio's
  `/ws/radio`, and REST through typed endpoint modules (`src/lib/endpoints/`) behind a request cache that a completed
  lap invalidates. Same origin and the same auth as the API: a LAN device's token cookie, or `?token=` remembered for
  the tab and sent on sockets and fetches.
- **Drive is deterministic** (spec P10): it reads only `/ws/live` and the radio store and works with the LLM down. Its
  rules (state, corner ahead, delta, timing colours, cues, the coaching point) are pure functions in
  `src/lib/drive/` tested on recorded and synthetic fixtures; unknown values show `-`, synthetic data is labelled.
  Drive › Coach is in the first bundle and every other page loads lazily; Recharts stays out of the Drive bundle (the
  Session complete card loads it on demand). `lib/drive/motion.ts` decides moving or stationary with hysteresis
  (stationary under 3 km/h for 1.5 s or with no live frame, moving over 8 km/h) and gates the cards, the game
  mismatch line and the full coaching text; `state.ts` `statusSlot` is the one priority order of the status line and
  `chipsOf` the stateless chip rule (the highest-ranked short-lived chip within its life; DRILL as the persistent
  chip); `complete.ts` `dedupeComplete` shows each fact of Session complete once, by the server's `fact_key`.
- **Live snapshot keys** (`core/live.py`; what each `/ws/live` snapshot carries is `api/live_feed.py`'s rule): every
  snapshot has the frame, session, laps (the newest 20) and events (every-car events carry `player` when F1 says whose
  they are), `session_state`, `coach`, `bests` (D2) and `game` (with `selected_source` / `selected_by`: why the game is
  selected). Sent when they changed: `ai_pace`, `coachref` (the reference choice and drill) and `lap_totals` (the
  whole session's lap counts); `strategy` when it changed, at most every 2 s. The static keys go every 5 s
  (`last_comparison` always; `track_model`, `skeleton` and `track_knowledge` only when they changed). A new session's
  first snapshot and one a minute carry everything. Absent means keep the last value within the session, `null`
  none (`lib/live.ts` `STATIC_KEYS`).
- **Two car class encodings** until the 0.2.1 single source: goals and badges store `car_class` as
  `"<game>:formula:<name>"`, pace against the AI as the game's class name (`"F1 World"`); they are never joined.

## Rig validation kit (`validate/`)
<!-- validation kit (lane validate) -->
`ValidationKit` (created in the app lifespan, `app.state.validation`) runs one validation run at a time on the asyncio
loop; `/api/validation` (`api/routes_validate.py`) and `pitwall validate` (`validate/cli.py`) sit on top. While a run
is active its `Collector` subscribes to `LiveState` (game events on the ingest thread: one frozenset test and, for six
rare kinds, a `call_soon_threadsafe`; lap notifications on the analysis thread: a few fields copied), to
`DriverService` and to the radio hub's observer hook (`RadioHub.add_observer`; nine hook calls in `voice/hub.py`
build their payload only when an observer is attached, and an observer error is logged, never raised into the hub).
A 2 Hz sampler reads telemetry status, session, tier and cue mode; lap traces (braking onsets, brake and steering
under each proactive message) and game sessions / driver switches are read with existing `storage/repo.py`
functions in worker threads. Rules are pure (`validate/rules.py`, `validate/evidence.py`). State is saved as files
only, `<data_dir>/validation/<run_id>/` (atomic writes, at most every 2 s), so no schema change. Radio commands are
answered by `RadioHub.command_handler` before the engineer; the LLM never sees validation state.
<!-- end validation kit -->

## Storage
SQLite WAL (`data/pitwall.sqlite3`), schema v6 (`storage/db.py`). Every migration is additive and idempotent, run in
one `BEGIN IMMEDIATE` transaction on open; `_migrate` checks columns, not version numbers, so any older database
converges (tests: `tests/unit/test_db_migrations.py`, v2 to v5 fixtures; nothing reads `meta.schema_version`).

| Version | Lane | Changes |
|---|---|---|
| v1 | - | initial schema |
| v2 | profiles | `reference_laps.driver_id` and the per-driver indexes |
| v3 | motivation | `goals`, `ix_goals_driver`; `sessions.info.total_laps` (JSON, no DDL); the 0.1.0 database |
| v4 | pace vs AI | `sessions.ai_difficulty` (added last, by `ALTER TABLE`), `session_ai_pace` |
| v5 | race strategy | `strategy_laps`, `pit_stops`, `ix_pit_stops_session` (new tables only) |
| v6 | coachref | `reference_choices`, `drills`, `ix_drills_driver` (new tables only) |

Lap traces stored as compressed float32 npz blobs (~19 channels); a `no_trace` lap has none (`n_samples` 0), and
`repo.load_lap_trace` returns None for it. Empty sessions (ended, with no timed lap, no lap trace beyond a stub and
nothing else stored) are hidden from the session lists, latest-session lookups and per-driver counts (`repo._listed`),
never deleted.
Raw packets in `data/captures/*.pwcap` (zstd, ~2.5 MB per 7 min at 60 Hz) for reprocessing.

## Install and update (`install/`)
<!-- --- lane install --- -->
The one-line installers (`scripts/install/install.sh`, `install.ps1`) download, check (SHA-256, zip paths) and
unpack a release into `<home>/pitwall-<version>/`, run `uv sync`, and hand over to that version's own
`pitwall install-finish` (`install/activate.py`): data folder (`<home>/data`, or a hand-installed release's adopted
`data/`), SQLite online backup, `.env` carried forward with an absolute `PITWALL_DATA_DIR`, the launchd agent or the
"Pitwall" task repointed (a service running from elsewhere is never touched; unless the new version answers with
its own tag on `GET /api/update/version` within 90 s, everything is put back), then `install.json`
(`install/layout.py`). `pitwall update` (`install/commands.py`) does the same in Python
(`install/stage.py`). `install/check.py` keeps the update status (`<data>/update_check.json`) behind `/api/update`
(`api/routes_update.py`: one GitHub request in a worker thread, never while telemetry is live) and doctor's
offline "Updates" check. None of it touches ingest, analysis or the language model, and nothing installs from the
dashboard.
<!-- --- end lane install --- -->

## Security
HTTP binds 0.0.0.0:8770; localhost is trusted, LAN clients need the access token (`pitwall token`), which
becomes an httpOnly cookie. The dashboards' static files carry no data and are served without a token; every `/api`
request and WebSocket is checked. Replay paths are confined to `data/captures`. The MCP dev tool is read-only and
loopback-only.
