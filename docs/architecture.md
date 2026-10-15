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
                          |  obs.+knowledge  |    |  observations, convos, |
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
 SessionManager --(deque append)--> +----------------------------+
   every game: player frames, laps,  | RaceRadioWorker            |--> LiveState.race (<= 2 Hz, at once after a call)
   events (no buttons), session      |  ("raceradio")             |--> notify("race_call") -> RadioHub
   info; F1: RaceTiming and          |  RaceRadioEngine (pure,    |    -> raceradio.radio.race_message (driver's groups,
   Participants (never persisted,    |  receive-time clock,       |       wording) -> RadioScheduler (RACE allowance)
   never in live state or logs)      |  no LLM)                   |--> notify("radio_urgent") -> voice.urgent (red flag)
                                     +----------------------------+
 SessionManager --(deque append)--> +-------------------------------+
   player frames, laps, events,      | CarHealthWorker ("carhealth") |--> LiveState.car_health / racecraft
   session info (every game),        |  CarHealthEngine per session  |    (<= 1 Hz, on change)
   RaceTiming; FieldSamples only     |  (pure, game clock, no LLM,   |--> notify("health_call") -> RadioHub
   while wants_field (F1 races)      |   nothing persisted)          |    -> RadioScheduler speak windows
                                     +-------------------------------+
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
| `raceradio` | race radio engine (`pitwall/raceradio`): flags, start and countdown, positions, rivals, penalties, damage; the live `race` view | touch sockets or the database, block ingest (one deque append per item) |
| `carhealth` | car health (`pitwall/carhealth`): tyre temperatures against the warm laps, brakes, engine, lock-ups and wheelspin, tank-level fuel, attack / defend; calls | touch sockets or SQLite, block ingest (one deque append per item; field samples only while `wants_field`) |
| `spotter` | the spotter (`pitwall/spotter`): decodes every car's Motion, runs the state machine on the game clock, publishes `live.spotter`, hands calls to the radio loop | block ingest (fed by one `SimpleQueue.put` per Motion packet), touch the DB |
| asyncio (uvicorn) | REST, WebSocket snapshots (pull model), LLM calls (async HTTP) | block on DB (uses `to_thread`) |

Every ingest-thread hook of the v0.2.0 features is O(1) (a deque append, a field write or a counter). The combined
budget is checked on the Austria race excerpt by `tests/recorded/test_ingest_budget_combined.py` (decode, session
handling and every hook per packet: median, p99 and maximum under fixed limits), and with the race radio's sink and
adapter mappings by `tests/recorded/test_ingest_budget_raceradio.py` (median 2.9 us, p99 35 us, max 0.5 ms on 13 208
packets, M4 Max: unchanged).

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
change), both for the race strategy engine, and `Participants` (who drives which car, on change; to the race radio
only: never persisted, never in live state, names never logged) and `TimeTrialInfo` (Time Trial, packet 14, once a
second: session best, personal best and the EA rival's lap, with LapData's PB / rival car indexes; spec-decoded, no
recording yet; `snapshot.time_trial` and the latest per session in `session_time_trial`). `CarFrame` carries the
player's F1 `fia_flag`, `damage` (`CarDamage`) and `penalties` (`CarPenalties`), the objects rebuilt only when the game's values change. Units in field names; `None` = unknown; `Wheels` always FL, FR, RL, RR; per-game
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

## Car classes (`carclass.py`)
One module decides which kind of car a session was driven in, so no other module keeps its own formula or team
tables: `classify(game, formula, car_id, packet_format)` (and `classify_row` / `classify_info`) returns a `CarClass`
(`f1_2025`, `f1_2026`, `f1`, `f2`, `f1_classic`, `other`) with its family (`f1`, `f2`, `other`), label, whether it has
ERS, a chip flag and the capability status (`capabilities.CAR_CLASSES`, looked up lazily). The class is worked out at
read time from `SessionInfo.formula` (EA spec 8.12; `F2` = formula 2), else from the spec's team ids for rows stored
without a formula, never stored itself (schema 6 unchanged); non-F1 games get no class. `car_label` names the car
("F2 · Art GP '24", "F2 car", never a raw id; ids 209-219 in format 2025 are named after EA's 465-475, the observed
F2 2025 teams) and `session_label` the session ("Feature race" for F2's "Race 2", "Sprint race" for its "Race" only
when the game's weekend structure, stored as `extra["weekend_structure"]`, also has a "Race 2"; the F1 games' own
names in sentence case). The capability status is per variant: an F2 car no recording covers (UDP format 2026, the
2026 F2 cars) is `spec_implemented`. The live snapshot (`core/live.py`, recomputed only when the formula, car,
format, session type or weekend change), the session
rows of the API, the report, recap, digest, the engineer's facts and the car setup context all ask it.
`repo.family_sql()` is its SQL twin (checked against it row by row) for queries that filter or partition by family.

The family keys three things: **track models** (`analysis/track.py` `TrackModel.car_family` and `superseded`, in the
stored JSON; `repo.load_track_model(..., family)` picks the family's newest model, else a legacy one of unknown
family, else another family's, which is *borrowed* and shown as such; `core/lap_processor.py` caches models per
(game, track, family), publishes the stored model to the live screen when a session's context arrives, before its
first lap, and replaces a borrowed model - or a legacy one of unknown family, captioned as such - on the family's
first clean lap), the **physics heavy-stop
warning** (`analysis/brake_prior.py` `default_envelope(family)`: the default model for F1, `F2_ENVELOPE` fitted from
the F2 AI field for F2, none for `other`; `PriorRefresher` keys on the family, so one family's AI fit never carries
over), and the **setup car format** (`carsetup.catalog.FORMAT_FAMILY`: an F2 session is only ever offered the `f2`
format). The F1 adapter reports no ERS (None) for F2 cars (formula 2: the game sends 0), and none before the
session's first Session packet (the formula is not known yet), and reads the DRS fields of Car Status; the one-shot
qualifying finish is reported as one lap (`_on_lap_data`), and `LapAssembler.flush` drops an in-progress lap of
fewer than 2 samples (the frame after a one-shot line). A one-off repair (`repo.repair_f2_v1`, meta key
`repair.f2_v1`, run by `LapProcessor.run_repairs` on the analysis worker at start) removed the one-shot duplicate
laps and the one-sample untimed laps stored before those fixes and rebuilt the track models made from them.

## Analysis pipeline (deterministic)
1. **Lap assembly** (`analysis/laps.py`): lap boundaries from the game's lap counter + official lap time;
   flashbacks detected by session time going backwards (rewound samples dropped, lap flagged); pit in/out,
   joined-mid-lap, packet-loss gaps, a lap of fewer than 2 samples or short of the line -> `incomplete`;
   game-declared invalid -> `invalid`; race lap 1 timed from the
   start signal (GT7 rolling starts) -> `race_start`; a lap the game timed that the adapter could not place on the
   track (`LapCompletion.untraced`) is stored with its time and no samples -> `no_trace` (+ `incomplete`). Only
   `clean` laps can be references or train the track model. Games that stream in their menus (GT7) decide in the
   adapter where a session starts and ends: it emits nothing outside a session and ends one with `session_ended`.
2. **Distance domain** (`analysis/distance.py`): every lap resampled to a 1 m grid by lap distance; time at
   each metre gives the cumulative delta. Edges extrapolated with measured speed (<=25 m).
3. **Track model** (`analysis/track.py`): corners = significant speed minima (prominence 8 km/h) of the
   median of up to 5 clean laps; entry = braking onset, exit = full throttle; analysis segments partition the
   lap so corner deltas sum to the lap delta. Versioned per (game, track), one model per car class family (built
   from that family's clean laps only); frozen after 3 laps.
4. **Braking** (`analysis/braking.py`): hysteresis 0.10/0.05, stab merging, sub-sample onset/release,
   time-to-peak, release time, trail-braking distance, coasting, throttle pickup/full.
5. **Comparison** (`analysis/compare.py`): compatibility gate (game/track/car/wet-dry/assists block;
   compound/setup/fuel/temperature warn), per-corner deltas.
6. **Coaching** (`analysis/coaching.py`): rules with thresholds above measurement resolution; measurement
   confidence vs habit consistency reported separately; later braking never suggested on its own. One definition
   of a habit for every consumer (`is_corrective`, `is_habit`, `is_big_one_off`; see "Habits and corner
   reminders" below).
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
   client keeps it, `lib/live.ts` `STATIC_KEYS`). Where the player comes out if they box now is
   `strategy/rejoin.py`: every car's gap to the leader (the game's, else chained from the car in front, else the
   last known value up to 15 s old: F1 25 zeroes the gaps 1-2 s before a pit entry), cars in the lane at their entry
   gap plus the loss, a position range and road traffic modulo one lap; frozen through the player's own stop.
9. **Car health** (`pitwall/carhealth/`, worker thread `carhealth`, off the ingest path, nothing persisted): one
   `CarHealthEngine` per session (a few at most, LRU) runs the tyre monitor (the session's temperature model:
   carcass only when the F1 session simulates it; 1 C histograms per lap and per stint; the warm baseline frozen at a
   pit entry; the cold-tyre rule armed at a tyre change in the box - judged there on the new set's first second -
   at a pit exit without one, or at a safety-car end), brakes and engine against the session's own laps (F1),
   lock-ups and wheelspin per lap (F1 MotionEx, the technique thresholds), the tank-level fuel estimator (Forza; GT7
   switched off) and the attack / defend grid clocks (every car's crossing time every 25 m of the lap from the race
   start, the last 5 laps; any learned corner model is derived from them, the cars directly ahead and behind, the
   last 3 clean laps each; F1 races, per-car buffers dropped at the session's end). It publishes `car_health` and `racecraft` at most once a second (and at a lap line or a call) and its calls
   (`health_call`) go through the radio scheduler with the existing kinds. Routes: `/api/car-health/*`,
   `/api/racecraft/live` (`/api/health` is the service's own health check).

9. **Race radio** (`pitwall/raceradio/`, worker thread, off the ingest path, every game): the rules of
   `flags.py` (red flag, safety car / VSC, yellow ahead and here, blue from the player's own FIA flag), `countdown.py`
   (grid brief, lights out, laps to go with `strategy.laps_left`'s lapped-car rule, finish, minutes left),
   `positions.py` (lap-one summary, settled changes, clean passes, pit exit), `rivals.py` (gap reports from its own
   `strategy.gaps.GapTracker`, a car ahead pitting, fastest laps, retirements), `penalties.py` and `damage.py`, clocked
   by the receive time (F1's session clock reads 0 during the start lights and runs backwards after a flashback).
   `roster.py` is the only reader of Participants names: calls say official AI driver names from EA's table, a team
   or a race number. Calls go to the radio hub as `race_call` notes (`radio.py` applies the seated driver's groups and
   wording) and the red flag as the urgent note (`voice/urgent.py`); after a flashback a `race_retract` note drops
   the unsaid position and damage calls. The live `RaceView` (`model.py`, at most 1.3 kB) rides `/ws/live` when it
   changed (`ON_CHANGE_KEYS`) and `GET /api/race/live`. Deterministic answers (`answers.py`: who is ahead / behind /
   leading, the position in any game, laps to go, penalties, damage, sector deltas) come from the `race` facts
   (`ai/facts.py`). No storage: nothing of the race radio is persisted. Until the driver has a learned track model,
   the radio's speak window looks ahead to the AI field's braking zones (`voice/field_zones.py`).

### Habits and corner reminders
What the radio, the coach card, the braking calls and the report say about a corner is decided once, by the same
rules (deterministic, no LLM; docs/features.md "Habits: what the radio works on"):
1. **Habit memory** (`core/lap_processor.py`, `lap-analysis` thread): the last `HISTORY_LAPS` (5) corner deltas per
   corner, each with its lap id and track model version. A new reference (a new best, `refresh_reference`) re-bases
   them on it (`_rebase_history` with `analysis.compare.corner_delta`, before the lap's observations) instead of
   clearing them; only another driver in the seat clears them. `observations_for_comparison` sets each point's
   `consistency_ratio` from that memory; `analysis.coaching.is_habit` / `is_big_one_off` classify the point.
2. **Habit tracker** (`coach/habits.py`, pure, owned by `coach/selection.CoachSelection` under its lock): updated
   once per compared lap from `LiveState.on_lap_result` (with the comparison's corners, the reference lap id, the
   lap's own corner times and the track model version) when the lap is habit evidence (the comparison's
   `habit_evidence`, set by the lap processor: no pit-in, out, flashback, standing-start, invalid or safety-car lap).
   Per (corner, kind) over the corner's last 5 counted laps: `seen`, `focus` (on the radio; 1 slot at normal, 2 at
   detailed, 0 when quiet; a habit costing at least `HABIT_MIN_IMPACT_S` on average, and one costing twice as much
   takes a small one's slot) and `fixed` (proven: clean corner, and for braking early a faster corner). A lap without
   the fault counts only against a reference known to show it (the session's `good_refs` / `blind_refs` per habit),
   and "better" compares values measured against the same reference. It emits `fixed`, `improving`, `announce` and
   `still` events; `coach_block` makes the radio's `picked` from them plus the lap's big one-offs under the driver's
   limits, and adds `habits` and `focus` (with each focus habit's corner reminder) to the coach block.
   `voice/proactive.coaching_text` words the events; Drive reads the same block (`snapshot.coach`). With a radio hub
   running (`CoachSelection.commit_on_delivery`) a habit line is recorded when the hub puts it on air
   (`RadioHub._deliver` -> `LiveState.habit_line_said` -> `CoachSelection.confirm_said`), so a line that expired
   unsaid never makes a focus habit; the cue plan follows at once (`CueEngine.set_habits`), so the habit's reminder
   starts on the lap the driver hears it.
3. **Braking calls and corner reminders** (`coach/cues.py`): `LiveState` passes the block's `focus` and `habits` to
   `CueEngine.on_lap_result`; in focus mode `build_cue_plan` plans braking calls for braking habits
   (`select_habit_corners`: confidence floor, impact floor) and a `REMINDER` cue for each other focus habit, only at a
   measured reference braking zone with a calm (off-brake) stretch long enough for the phrase, together at most the
   profile's focus corners, never for a habit the latest lap could not show (`blind`). A reminder fires its spoken
   length plus 1 s before the braking point; the hub (`voice/hub.py`) pushes the pre-synthesised length
   (`CueTiming.durations_s`) and the scheduler's speak windows close before a cue's start (`seconds_to_next_cue`).
   A reminder ranks below a braking call on air (`scheduler.interrupt_rank` 0): it plays only on a free radio, never
   with a car alongside, and spotter and braking calls cut it. `on_frame` stays O(1) and lock-free.
4. **Report** (`motivation/recap.py`, mirrored by `web-react/src/lib/review/coaching.ts`): "One to work on" is a
   point repeated and still there, else a big one-off (else nothing when laps were compared); a habit that stopped on
   the corner's last 3 compared laps (clean, and faster for braking early) "went well". The TypeScript copies of the
   constants are pinned by `tests/unit/test_motivation_recap.py`.

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

### Technique knowledge graph (`knowledge/`)
`knowledge/graph.py` loads the driving-technique knowledge from TOML files in `knowledge/graph/` (packaged data,
standard-library `tomllib`): the six phases of a corner, techniques, conditions over the driver's Context, signals
(each naming the dataclass field that computes it, e.g. `CornerDelta.min_speed_delta_kph`), faults (the live coaching
kinds by `analysis/coaching.py` `COACHING_KINDS`, plus planned detectors), causes with the evidence that tells them
apart, advice, constraints (forbidden phrasings: no "brake later", "brake less", "release the brake earlier", "carry
more speed" or "trail brake more"; praise may describe later braking, never ask for it) and sources, every node with
its evidence tier (`external` for real-world or third-party data measured by Pitwall's scripts, kept as measurements
on techniques). `load_graph()` validates once per process (references, mirrored edges, code paths, thresholds, advice
limits, tiers backed by sources, constraints on every scanned text); the app's lifespan loads it at startup in a
worker thread, a broken graph is logged and the app runs without it, while tests make it raise. Nothing on the
time-critical path; no LLM. Contributor guide and schema: [docs/knowledge.md](knowledge.md).

Using it, on the analysis worker after a lap's observations (step 6 above), never on the ingest thread:
- **Context** (`knowledge/context.py`, frozen, every field None = unknown): skill from the seated driver's profile;
  braking style and coasting detected (`knowledge/style.py`, below); game; car family (`carclass`); downforce high for
  the F1 and F2 families; gearbox paddles with auto-blip for the F1 family, automatic when an F1 game reports
  gearbox assist 3; ABS and traction control from F1 25's per-lap assists (all laps must agree) or Assetto Corsa's
  session flags; fuel saving from the live strategy's lift and coast; wet from the weather. Per-game channel
  availability comes from the adapters' declared fields: only an UNSUPPORTED field makes a channel `not_sent`; an
  undeclared or UNVERIFIED one is `unknown` and never rules a node out.
- **Style** (`knowledge/style.py`, [H] thresholds): over the driver's clean compared laps (the lap processor keeps the
  last 5 per corner in `_SessionCache.style_laps`: no incidents, no safety car; a stored session uses every clean
  analysed lap), the share of braking corner-laps with 10 m or more of trail braking (0.6 or more trail, 0.2 or less
  straight-line, else mixed) and with 10 m or more of coasting (0.5 or more often, 0.2 or less rare, else unknown);
  2 laps and 6 braking corner-laps at least, counting only corner-laps where the value was measured: trail braking
  needs the steering (`analysis.braking` leaves `trail_brake_m` None without it), so a game that sends none keeps the
  braking style unknown. Under the F1 braking assist the style is kept and flagged (`braking_assist`): the screens,
  the AI engineer and advice chosen for the style say some of the braking was the game's.
- **Annotation** (`knowledge/annotate.py` `DriverKnowledge`): every published observation dict gets an additive
  `knowledge` key: `{fault, name, status, tier, applies, why_not, causes, advice, digest}`. `applies` is False when the
  fault's conditions fail for the Context or the game does not send a channel one of its signals needs. Causes are
  named only when the cause's conditions hold (`ready_earlier`: traction control off) and from measured values
  (`graph.Discriminator.holds`; an unmeasured value holds nothing), each with its evidence; a corner's inputs and
  balance (`technique.session.lap_corner`) are computed only when a cause needs them, and the reference lap's only for
  the causes compared with it (`low_grip`, `traction_limited`). Advice per form (radio, screen,
  review): a style match first, then the driver's skill, then `any`; `tailored` marks advice written for the driver.
  Observations are stored as before, without it; the comparison carries `knowledge: {digest, context, style}`. Any
  error leaves the lap's observations unannotated (coached as before the graph).
- **Applies** (`analysis.coaching.applies`): a point that does not fit the driver is never picked for the radio, never
  on the coach card and never a habit (`coach.selection`, `coach.habits`, `motivation.recap.rank_points`), but still
  makes its corner unclean for the habit tracker and the recap's "sorted" check. None of the eight live kinds has a
  condition and every adapter sends their channels, so coaching on them is unchanged on every game (recorded A/B in
  docs/status.md).
- **Where it goes:** the coach block's points carry a slim copy (`annotate.slim`: applies, why_not, causes with their
  measured values and screen line, advice), and the `/ws/live` snapshot's observations only what the card reads from
  one (`annotate.card_slim`: applies and the first cause's screen line; `core/live.py`); the full annotation stays in
  the lap notification and the session's analysis, so twenty snapshots a second stay small. Stored sessions are
  annotated inside `SessionAnalyzer.analyse` (`knowledge/session.py`, cached with the analysis); `GET /api/compare`
  and `GET /api/coachref/compare` (Review › Compare) annotate the lap pair for the compared lap's driver.
- **API:** `GET /api/technique/knowledge` (the whole validated graph with typed edges) and `?session=<id>` (plus the
  session's `context`, `style`, `channels` and `applies` / `why_not` on every condition, signal, technique, fault,
  cause and advice node; 404 for an unknown session), `api/routes_knowledge.py`, orjson.
- **Screens** (`web-react`): Review › Coaching's "How corners work" (`pages/review/plan/HowCornersWork.tsx`, rules in
  `lib/knowledge/view.ts`) from the session variant; the coach card's stationary evidence line, Review's Work on
  cards, Corners notes and Compare's explainer show the measured cause and, for a point that does not fit, its reason
  (`lib/knowledge/annotation.ts`); Compare adds Ed's g-force charts (hidden when no lap has g) and the corner's phase
  markers from `CornerMetrics` (`lib/review/phase-markers.ts`).

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
deterministically and are radio fast intents (feat/technique). Technique knowledge facts (topic `knowledge`,
`knowledge/facts.py`, last on the sheet; seen by the technique, focus, braking and losing-time intents): the driver's
Context and detected style, and per fault seen this session its graph node, the measured causes, the techniques for
that phase that fit (named; summaries on the most-seen fault only) and its sources with their tier in words. Their
`data["nodes"]` names the graph nodes a fact is about and `data["not_for_driver"]` the techniques that do not fit, and
`ai/grounding.py` rejects an answer that names a technique (`knowledge/terms.py`, kept in step with the graph by a
test) no considered fact is about or one a fact says is not for this driver (`ungrounded_techniques`), and an answer
that breaks one of the graph's constraints (`constraint_breaches`): the engineer explains the graph's techniques and
never invents one.

## Radio policy (`voice/scheduler.py`)
One scheduler decides what is said and when, and one table says it: `POLICY` (a `CallFamily` row per call family:
spotter, red flag and punctures, answers, braking calls, alerts, lap time, race calls, strategy, car health, goal,
coaching, detail, validation), printed in docs/voice-protocol.md ("Radio policy") by `policy_markdown()`, served by
`GET /api/radio/policy` to Settings › Radio & voice, and pinned against the live rules by
`tests/unit/test_radio_policy.py`. Message kinds (`voice/types.py`): `answer` and `control` (the driver's own questions
and commands), `cue` (braking calls), `alert`, `lap_summary`, `race`, `strategy` (car health's normal calls too),
`goal`, `coaching` (also a drill point), `info` (detail) and `validation` (the kit's prompts); `family_of(msg)` maps a
message to its row. `ALLOWED_KINDS` per intensity: quiet = answers, control, alerts, spotter, cues (muted by the hub)
and validation; normal adds lap summaries, race calls, strategy and car health calls, goals and coaching; detailed adds
info. Pending messages are dispatched by (priority, `KIND_RANK`, arrival), the race order: alerts, lap summary, race
calls, strategy and car health, goal, coaching, info, validation. On track ONE per-lap budget, `TALK_PER_LAP` (0 / 3
/ 5), is shared by every producer's routine messages (`BUDGETED`: lap summary, race, strategy, goal, coaching, info);
alerts and the race milestones (`race_allowance` false) are never held by it but spend it; inside it race calls take at
most `RACE_PER_LAP` (2 / 3) and coaching `COACHING_PER_LAP` per analysed lap. Every proactive message waits for a
speak window (off the brake, steering nearly straight, no car alongside, time before the next braking zone or cue;
before a track model is learned the zones come from the track knowledge, `voice/field_zones.py`, and from where the
driver braked on their last three laps out of the pit lane, `voice/lap_brakes.py`);
the 2 s gap, the 60 s repeat filter and topic replacement (newest wins) still apply. One message per piece of news:
race news made at the line rides inside the lap summary (`SUMMARY_MERGE_KEY`, at most `MERGE_MAX_WORDS`), the safety
car is announced once across the race radio and race strategy (`ANNOUNCE_KEY`), fuel and the gap are topics shared
across producers (`SHARED_TOPICS`), and an answer holds its topic for 30 s (`ANSWER_TOPICS`; the hub reports answers
with `note_spoken`). The gap also holds for a message the hub synthesised and held while something else was on air: it
is released 2 s after the radio went quiet, never at once (`RadioHub._gap_ok`). Only an urgent call cuts a proactive
message, which is then said again once (`MAX_RESENDS`). `RadioHub.apply_driver` calls `drop_driver_messages()` when
another driver sits down (unsaid lap summaries, goals and coaching go; strategy, race calls and alerts stay), and a new
live session id calls `reset_session()` (the queue, budgets, repeat filter, announcement and answer memories and a
lap-bounded quiet period belong to the old session). The final lap gets its summary but no coaching point.
The red flag is the first producer of `Priority.URGENT` (`voice/urgent.py`: any thread posts `radio_urgent`; the hub
queues it past quiet mode, intensity, the speak window and the gap). `voice/addressing.py` works the seated driver's
first name into an addressable message after the scheduler hands it out (at most once a minute), before synthesis.
Questions are answered short on the radio (`deterministic_answer(short=True)`: one or two facts in their spoken
form). Strategy (`strategy/radio.py`) is the only source of F1 fuel alerts; car health (`carhealth/radio.py`) calls
Forza's tank-level fuel, cold tyres after a stop, wear outside F1 races and (detailed by default) lock-up and
wheelspin notes, with the strategy kinds (alert / strategy / info) and topics `health:<topic>`.
The `say` frames are in [voice-protocol.md](voice-protocol.md).

## Hands-free talking and speech engines (`voice/handsfree.py`, `voice/stt_sherpa.py`)
Lane handsfree ([research/handsfree.md](research/handsfree.md)). `HandsFreeController` is the hub's hands-free side,
called from small hooks marked `# --- hands-free (lane handsfree) ---` in `voice/hub.py` (connect/disconnect, `stop`,
`state()`, `on_text` for `vad` / `settings` / the `ptt` source, `on_audio`, `_ptt_down_now`, `_deliver`, `_tick`,
`_after_synthesis`, `apply_driver`, `_follow_session`, `status()`, and two in the question pipeline: a spoken reply
while the speech model is still starting in `_handle_utterance`, and an empty fact sheet for a radio check / quiet /
resume before any session in `_answer`); everything runs on the event loop and nothing on the UDP thread. Per armed device it keeps a 0.5 s ring buffer (filled only when it may listen; a frame from an unarmed
device is dropped at once), captures between the browser's `vad` start and end, and processes one segment at a time
(at most two queued): length checks, the STT energy gate at -50 dBFS (the browser's), the speech engine in a worker
thread, `match_wake` (pure: up to two fillers; "pitwall" on one or two joined words, within one edit for any question
and two edits only before a racing question; "radio" on one word), then the echo guard (the radio's last 10 s of
words; an addressed transcript only against lines that start with the wake word). An addressed question goes to the
hub's own `_answer` (deterministic while moving); anything else is dropped without a trace (logs and observers carry
reasons, lengths and levels only). `MotionGate` is Drive's stationary rule (`web-react/src/lib/drive/motion.ts`) plus
the frame's paused/replay flags and a 5 s hold when the stream stops while the car moves (an incident gap), updated at
10 Hz in the tick; the scope is the seated driver's `handsfree_while_driving` (`drivers.py`, stored in the preferences
JSON: no schema change). While `holds_radio` (a capture, a segment in the speech engine, the wake word alone waiting
for its question, "Say again?" waiting), the tick and `_after_synthesis` treat the radio as busy (only urgent calls go
out); anything delivered ends the capture ("Say again?" when an addressed one is cut). Its own replies ("Go ahead.",
"Say again?") wait for a free radio and, on track, a speak window; the once-a-session "paused while driving" hint waits
for a settled stop and is an `info` message (not a control message). The browser side (`web-react/src/lib/handsfree.ts`: the energy VAD,
the learned Bluetooth key or gamepad button) is the dashboard's.
Speech engines (`voice/stt.py` `build_stt`): Parakeet through parakeet-mlx on Apple silicon; elsewhere
`stt_engine=parakeet` resolves to `SherpaParakeetStt` when sherpa-onnx imports (the `voice` extra installs it on
Windows): Parakeet TDT 0.6B v2 int8 on the CPU, its four files pinned by revision, size and SHA-256, downloaded on the
first `warmup()` to `<app support>/stt/` (or read from `PITWALL_STT_SHERPA_DIR`), with the same gate, resampling and
racing-term corrections as Parakeet. `pitwall doctor` reports both (`voice_stt`, `voice_handsfree`).

<!-- --- spotter --- -->
## Spotter fast path (`spotter/`, `voice/spotter_radio.py`)

F1 25 only (the other games send the player's car only). No LLM anywhere on this path.

```
UDP thread: F1Adapter._on_motion --(FieldMotion: 2 packet refs + 4 ints)--> SessionManager.handle (first branch)
            +-> SpotterWorker.submit(item): SimpleQueue.put (C, non-blocking)                 [~1 us, no decode]
            SessionInfo and GameEvent{lights_out, flashback, red_flag, session_started, session_ended,
            chequered_flag} also forwarded; reset(session_id) on SessionManager._start / end()
spotter thread: q.get(timeout=0.25) -> [off: count, return] decode (subset_struct) -> SpotterEngine.feed_motion
            -> live.spotter (swap)
            +-> calls -> sink(call) = SpotterRadio.on_call_threadsafe -> loop.call_soon_threadsafe(deliver)
asyncio loop: SpotterRadio.deliver -> mailbox / cut rules -> RadioHub._deliver(PCM made in advance, pcm_to_all)
```

The engine (`spotter/engine.py`) is pure: every time comes in as an argument and every duration is on the game clock
(header `sessionTime`), so receive bunching cannot shorten a debounce. Geometry (`spotter/geometry.py`): each car is
an `L x W` box (`spotter/dims.py`, per formula) in the player's frame from its forward and right vectors
(`worldRightDir` is the driver's right on real data); relative speeds include the frame's rotation (the player's
vectors in the previous packet), so a constant gap through a corner is not "closing". Gates, in order: disabled, not
available, session type, red flag, safety car (unknown counts as on), lights out + delay, paused, stale (no Motion for
250 ms), flashback mute, pit, finished, spin (slip above 30 degrees, open again 0.3 s under 15), slow; a closed gate
forgets the traffic and never says "clear", except pit, finished and slow, which leave the positions valid: an
announced side empty at that packet gets its clear (`SpotterCall.final`). The live block (`spotter` in every
`/ws/live` snapshot, about 230 bytes, with the car `length_m` in use for the bar scale) is swapped whole on every
Motion item and does not bump `LiveState.version`; `api/live_feed.py` sends a changed block without a new frame, so
the block going stale when Motion stops (a pause) reaches the iPad at once.
Offline: `spotter/score.py` (geometric ground truth) behind `scripts/spotter_check.py` and the recorded tests.

Radio priority contract: the one urgent path (`voice/scheduler.py` `may_interrupt`, asked by the scheduler, the hub's
urgent slot, cue gate and answers, and `voice/spotter_radio.py`): only urgent calls interrupt (Priority.URGENT:
spotter calls, the red flag and a puncture from `voice/urgent.py`), never another urgent call (a red flag waits for a
spotter call on air, and a spotter call for the red flag); a spotter clear or "still there" (`YIELDS_TO_CUE_KEY`) never
cuts a braking cue. A braking cue cuts nothing: it plays on a free radio only (dropped, never late, as `radio busy`),
and an answer waits for a cue or urgent call on air. Everything else follows the per-lap budget and speak windows.
Spotter messages (`MessageKind.SPOTTER`) never go through the scheduler queue (its 100 ms tick is too
slow), are exempt from the budget, gap, repeat filter and speak window, and are allowed at every intensity. While a
car is alongside (`DrivingState.traffic_alongside`) no speak window opens, so a lap summary never starts wheel to
wheel. The spotter's own refinements, in `voice/spotter_radio.py`: its clears and still theres carry the clear-before-cue
mark (they never cut a cue), the mailbox never lets a clear or a still there push out a held onset, and a resync says what the driver missed (heard vs the worker's announced state) whenever the radio is free.
Delivery, the one-slot mailbox, heard pairing, the resync and the latency stamps are in `voice/spotter_radio.py`; the
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

## Family leaderboard (`leaderboard/`)
Local boards of the household's laps (docs/leaderboard.md). `keys.py` (pure) turns a lap's raw columns into an exact
board key (game, track, layout within 3 %, car with the F1 class family and equal performance, session category,
dry / wet, assist class; an unknown value is its own bucket) and its string form; `board.py` (pure) merges the repo
rows into boards, the record index, the record history and the family-record takes; `service.py` is the database side
(read-only) shared by `api/routes_leaderboard.py` (`/api/leaderboard`, `/api/records`, `/api/leaderboard/lapcard/{id}`),
the motivation badges and worker, and `facts.py` (the engineer's topic `records`). Two SQL reads in `storage/repo.py`
use window functions over raw key columns (`board_bests`: each driver's best per partition with the clean-lap count,
best sectors, first and latest lap; `board_record_laps`: laps faster than every earlier lap of their partition);
Python merges the partitions of one key (lengths within 3 %, "clear" and "overcast" both dry) and runs the record
again over the merged rows. The boards store nothing of their own. After each live lap the motivation worker asks
whether the lap took its board's record from another driver and publishes `live.notify("family_record", note)`; the
radio hub turns it into one `GOAL` line (`motivation.radio.record_message`, the goal lines' gate and topic rules).
Two optional rows: `service.ea_rival_for` (the F1 25 Time Trial rival, `repo.latest_tt_rival` over
`session_time_trial`, schema v7) and `service.real_f1_row` (the real pole from `trackdata.real_f1`, F1DB, of the season
`board_generation` reads from the board's car via `carclass`, or the driver's `car_generation` answer);
`board.with_benchmarks` adds them, each driver's gap and band (`real_f1.band_for`), and `board.index_versus` the
record's to each index row. `lapcard.py` builds the versioned lap card locally; nothing goes online. On screen, Review ›
Progress's Records section (`web-react`: `lib/endpoints/leaderboard.ts`, pure `lib/review/records.ts`,
`pages/review/progress/useRecords.ts`) reads `/api/records?driver_id` to open the viewed driver's newest board here,
then `/api/leaderboard?key`; its pickers are built from `boards_here`.

## Dashboard (`web-react/`)
React 19 + TypeScript (strict) + Vite + Tailwind v4 + HeroUI v3 / HeroUI Pro, built to `docs/ui/design-spec.md` (v2,
coach-first). FastAPI serves the built `web-react/dist` as static files at `/` and, for a week after the switch-over,
at `/next/` (an alias of the same files); `index.html` is served `no-cache` and the hashed `assets/*` immutable. The
Svelte dashboard in `web/` is frozen to fixes only and served only when `web-react/dist` is not built.
`web-react/README.md` has the layout and the switch-over details.

- **Routes** are hash routes `#/<area>/<page>[/<param>][?<query>]` over four areas: Drive (Coach, Car, Track,
  Radio), Review (Sessions, Coaching, Progress, Goals, Ask), Setup (Game, Connect, Rig, Controls, Car setup, Validation;
  it opens on Game) and Settings (Drivers, Radio & voice, AI engineer, Display, System). Every Svelte hash (`#/live`, `#/radio?token=…`, `#/sessions/<id>`,
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
  selected). Sent when they changed: `ai_pace`, `coachref` (the reference choice and drill), `lap_totals` (the
  whole session's lap counts), `car_health` and `racecraft` (car health, at most once a second); `strategy` when it
  changed, at most every 2 s. The static keys go every 5 s
  (`last_comparison` always; `track_model`, `skeleton` and `track_knowledge` only when they changed). A new session's
  first snapshot and one a minute carry everything. Absent means keep the last value within the session, `null`
  none (`lib/live.ts` `STATIC_KEYS`).
- **Technique knowledge on points** (`lib/knowledge/annotation.ts`): a point's `knowledge` (the slim copy on Drive,
  the full annotation in Review) is read, never recomposed: the measured cause's screen line leads the evidence line;
  a point the graph says does not fit the driver is never the card's point (`fitsDriver`, as the radio) and Review
  shows it greyed with the graph's reason.
- **Two car class encodings** until the 0.2.1 single source: goals and badges store `car_class` as
  `"<game>:formula:<name>"`, pace against the AI as the game's class name (`"F1 World"`); they are never joined.

## Controls and button mapping (`controls/`)
Setup › Controls ([controls.md](controls.md)): which button does what, for any wheel and researched game. The
catalogue (`controls/catalog.py`) joins two verbatim research files with Pitwall's overlay and validates them at load
(every research row covered, sources resolve, presets assignable mid-race, kinds, zones and slots valid). Wheels,
layouts and per-driver choices live in the SettingsStore section `"controls"` (no SQLite change; `rev` per object, 409
when stale). Recommendations (`recommend.py`), "Map it" steps (`steps.py`) and the printable card (`card.py`) are pure
and deterministic. Only F1 25 lets Pitwall see a button: `ControlsService` (`controls/service.py`, built by `Runtime`
whether or not voice is on) subscribes a `ButtonProbe` to `LiveState.subscribe_buttons` (ingest thread: a sequence
number and one store into a 64-slot ring, no lock, no I/O). `SessionManager` labels each press `live`, `replay` or
`synthetic` (`LiveState.on_button(status, origin)`) so replays never count. The button test advances when the
dashboard polls; live results are written into the layout's `assignment.check`. Push-to-talk follows the seated
driver's F1 25 layout: `PttFollower` recomputes on a change of the `"controls"` or `"game"` section or the seat and
hands the UDP Actions to `RadioHub.set_ptt_actions` on the hub's loop (the deploy setting stays as a fallback); the
test pauses wheel push-to-talk (`suspend_wheel_ptt`, which lapses on its own). The engineer's `controls_where` intent
("which button is brake bias?") is answered by `ControlsService.answer`, never the LLM.

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
functions in worker threads. Rules are pure (`validate/rules.py`, `validate/evidence.py`). Setup › Controls'
`wheel_buttons` reads the controls probe's ring on the sampler tick (never on the ingest thread) into the additive
`evidence.buttons`, and copies the seated driver's F1 25 layout into the additive `run.controls_layout`. State is saved as files
only, `<data_dir>/validation/<run_id>/` (atomic writes, at most every 2 s), so no schema change. Radio commands are
answered by `RadioHub.command_handler` before the engineer; the LLM never sees validation state.
<!-- end validation kit -->

## Storage
SQLite WAL (`data/pitwall.sqlite3`), schema v7 (`storage/db.py`). Every migration is additive and idempotent, run in
one `BEGIN IMMEDIATE` transaction on open; `_migrate` checks columns, not version numbers, so any older database
converges (tests: `tests/unit/test_db_migrations.py`, v2 to v6 fixtures; nothing reads `meta.schema_version`).

| Version | Lane | Changes |
|---|---|---|
| v1 | - | initial schema |
| v2 | profiles | `reference_laps.driver_id` and the per-driver indexes |
| v3 | motivation | `goals`, `ix_goals_driver`; `sessions.info.total_laps` (JSON, no DDL); the 0.1.0 database |
| v4 | pace vs AI | `sessions.ai_difficulty` (added last, by `ALTER TABLE`), `session_ai_pace` |
| v5 | race strategy | `strategy_laps`, `pit_stops`, `ix_pit_stops_session` (new tables only) |
| v6 | coachref | `reference_choices`, `drills`, `ix_drills_driver` (new tables only) |
| v7 | leaderboard | `session_time_trial`: the latest F1 25 Time Trial data per session, the EA rival in columns (`repo.latest_tt_rival`) (new table only) |

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
