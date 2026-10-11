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
                          |  observations    |    |  observations, convos  |
                          +------------------+    +------------------------+
```

## Threads and the critical path
| Thread | Work | Never does |
|---|---|---|
| `udp-<port>` | `recvfrom` -> monotonic timestamp -> capture queue -> decode -> session state | disk I/O, DB, analysis, LLM |
| `capture-writer` | zstd-compress raw packets to `.pwcap` (flush every 1 s) | - |
| `lap-analysis` | per-lap: persist, track model, reference, compare, coaching | touch live sockets |
| `db-writer` | all SQLite writes, one transaction per job | - |
| asyncio (uvicorn) | REST, WebSocket snapshots (pull model), LLM calls (async HTTP) | block on DB (uses `to_thread`) |

Backpressure: capture queue (200k packets) and lap queue are bounded; overflow is counted and logged, never
silent. Dashboard clients pull snapshots at a fixed rate, so a slow browser cannot slow ingest; per-client
notification queues drop the oldest message for that client only.

Measured (synthetic, M4 Max): full replay of a 7-lap, 117k-packet session including all analysis: ~0.6 s;
per-lap processing 7-18 ms; decode <30 us/packet.

## Data model
`model/telemetry.py`: `CarFrame` (high-rate, player car), `SessionInfo` (slow), `GameEvent` (discrete),
`CarSetup`, `LapCompletion`. Units in field names; `None` = unknown; `Wheels` always FL, FR, RL, RR; per-game
ground plane declared by the adapter (`AdapterInfo.ground_plane`). Field provenance per game in
`AdapterInfo.fields` -> `/api/capabilities`.

## Analysis pipeline (deterministic)
1. **Lap assembly** (`analysis/laps.py`): lap boundaries from the game's lap counter + official lap time;
   flashbacks detected by session time going backwards (rewound samples dropped, lap flagged); pit in/out,
   joined-mid-lap, packet-loss gaps -> `incomplete`; game-declared invalid -> `invalid`. Only `clean` laps
   can be references or train the track model.
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

## AI engineer
`ai/facts.py` builds an ID-tagged fact sheet from the stored session analysis (the model never sees raw
telemetry). `ai/engineer.py`: rule-based intent (works offline; control commands never reach the LLM) ->
topic-filtered facts -> LLM with strict system prompt -> `ai/grounding.py` (every number must be a rounding
of a number in the cited facts; citations must exist) -> one corrective retry -> deterministic fallback.
`ai/providers.py`: OpenAI-compatible provider with model discovery and a circuit breaker.
Technique facts (topics `line`, `technique`, `balance`) come from `technique/facts.py`; their intents are answered
deterministically and are radio fast intents (feat/technique).

## Dashboard (`web-react/`)
React 19 + TypeScript (strict) + Vite + Tailwind v4 + HeroUI v3 / HeroUI Pro, built to `docs/ui/design-spec.md` (v2,
coach-first). FastAPI serves the built `web-react/dist` as static files at `/` and, for a week after the switch-over,
at `/next/` (an alias of the same files); `index.html` is served `no-cache` and the hashed `assets/*` immutable. The
Svelte dashboard in `web/` is frozen to fixes only and served only when `web-react/dist` is not built.
`web-react/README.md` has the layout and the switch-over details.

- **Routes** are hash routes `#/<area>/<page>[/<param>][?<query>]` over four areas: Drive (Coach, Car, Track,
  Radio), Review (Sessions, Coaching, Progress, Ask), Setup (Connect, Rig, Car setup) and Settings (Drivers, Radio &
  voice, AI engineer, Display, System). Every Svelte hash (`#/live`, `#/radio?token=…`, `#/sessions/<id>`, ...) is
  rewritten in place, keeping its query (`src/lib/route-parse.ts`).
- **Data:** one `/ws/live` socket for the whole app (snapshots at 20 Hz, the static payload every 5 s), the radio's
  `/ws/radio`, and REST through typed endpoint modules (`src/lib/endpoints/`) behind a request cache that a completed
  lap invalidates. Same origin and the same auth as the API: a LAN device's token cookie, or `?token=` remembered for
  the tab and sent on sockets and fetches.
- **Drive is deterministic** (spec P10): it reads only `/ws/live` and the radio store and works with the LLM down. Its
  rules (state, corner ahead, delta, timing colours, cues, the coaching point) are pure functions in
  `src/lib/drive/` tested on recorded and synthetic fixtures; unknown values show `-`, synthetic data is labelled.
  Drive › Coach is in the first bundle and every other page loads lazily; Recharts stays out of the Drive bundle (the
  Session complete card loads it on demand).

## Storage
SQLite WAL (`data/pitwall.sqlite3`). Lap traces stored as compressed float32 npz blobs (~19 channels).
Raw packets in `data/captures/*.pwcap` (zstd, ~2.5 MB per 7 min at 60 Hz) for reprocessing.

## Security
HTTP binds 0.0.0.0:8770; localhost is trusted, LAN clients need the access token (`pitwall token`), which
becomes an httpOnly cookie. The dashboards' static files carry no data and are served without a token; every `/api`
request and WebSocket is checked. Replay paths are confined to `data/captures`. The MCP dev tool is read-only and
loopback-only.
