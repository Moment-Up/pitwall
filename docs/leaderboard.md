# Family leaderboard and lap cards

The family leaderboard ranks the household's drivers on boards where the laps really race each other: same game,
track, layout, car, session type, conditions and assists. It is **local only**: it reads the Pitwall database on this
machine, makes no network call and uploads nothing. Household driver names stay on this machine (the names below are made up). Code:
`src/pitwall/leaderboard/` (`keys`, `board`, `service`, `lapcard`, `facts`), SQL in `storage/repo.py`
(`board_bests`, `board_record_laps`, `board_lap`), API in `api/routes_leaderboard.py`.

The last section, the **lap card**, is a format only: what one lap would look like if the owner ever opens an online
board (probably hosted on Lovable). Nothing sends it anywhere today.

## What counts on a board

A board lap is a **clean, valid, timed lap of real driving**:

- clean: complete, no flashback, not a pit, out or start lap (`LapTrace.clean`); valid: not marked invalid by the
  game. Only F1 sends lap validity; GT7, AC and Forza cannot tell a lap that cut a corner, so their boards say "This
  game does not say when a lap breaks track limits: a lap with a cut still counts here."
- real driving: never a synthetic session, never a replay of a recording, never a session no driver profile owns.
- at a known track: never a track id that is unknown, `-1` or `synthetic:`. GT7 tracks Pitwall identifies by their
  start line ("Unidentified GT7 circuit (3.80 km)") get boards: the id is the same every time the circuit is driven.

Evidence: unit and recorded-data tests (a read-only copy of the owner's database). Not live-validated.

## The board key

Every part is exact, and **an unknown value is its own bucket, never a wildcard**: a lap whose ABS setting was not
sent is on the "ABS unknown" board, never on the "ABS on" one. (Picking a reference lap to drive against,
`core.coachref`, stays looser on purpose: there an unknown value matches anything.)

| Part | Values |
|---|---|
| game | `f1_25`, `gt7`, `ac`, ... |
| track | the game's track id (`f1:17` Austria) |
| layout | lengths within 3 % of a group's shortest length are one layout, named by that length in whole metres (a shorter length stored later renames it; a key with the older name still finds the board); an unknown length is its own layout |
| car | the exact car id; unknown is its own board. F1 games add the car class family (F1 / F2 / other, from `carclass`) and the "equal car performance" setting, each unknown until the game sent it |
| category | `time_trial`, `qualifying`, `race`, `practice`, else `unknown` (GT7 and AC send no session type) |
| conditions | `dry` or `wet` (light rain, heavy rain and storm are wet), else `unknown` |
| assists | F1: braking assist, ABS, traction control, gearbox, racing line. Braking, gearbox and line come from the Session packet and count only once its tail is filled (F1 25 sends gearbox 0 for the first ~1.5 s of a session); ABS and TC come from the lap itself (the value on 90 % of its moving frames). AC: ABS and TC on / off. GT7, Forza and the other games report no assists: one "not reported" class |

The game version is shown on each row, not part of the key.

**String form** (`key` in the API, the badge key, the lap card): nine `~`-separated parts
`game~track~layout~car~class~equal~category~conditions~assists`. `?` is unknown, `-` "this game has no such
setting"; ids are percent-escaped (`%`, `~` and `?` only). Assists: F1 `b2.a1.t2.g3.l2` (braking 0-3, ABS 0-1, TC 0-2,
gearbox 1-3, line 0-2), AC `a1.t0`, other games `-`. Examples from the owner's data:

```
f1_25~f1:17~4323~f1:team:7~f1~0~race~dry~b2.a?.t?.g3.l2          Austria, Haas, race, dry; ABS and TC not stored
f1_25~f1:27~4910~f1:team:8~f1~0~race~dry~b2.a1.t2.g3.l2          Imola, McLaren, race, dry; ABS on, TC full
gt7~gt7:sf:380:120:15:3800:530~3799~gt7:car:3353~-~-~unknown~unknown~-
```

Laps stored before ABS and TC were recorded per lap (before feat/technique) have them unknown, so they sit on their
own boards.

## API

### `GET /api/leaderboard`

Either `key=<string form>`, or `game` + `track_id` with any of `length_m` (matched within 3 %), `car_id`,
`car_class` (`f1|f2|other|?|-`), `equal_performance` (`0|1|?|-`), `category`, `conditions`, `assists` (an assist
code). An unset field means any; `?` asks for the unknown bucket (`car_id=?` is the unknown-car board, never "any
car"). When several boards match, the one driven most recently is shown. 422: a key or field that does not parse.

```jsonc
{
  "key": "f1_25~f1:17~4323~f1:team:7~f1~0~race~dry~b2.a?.t?.g3.l2",   // null when nothing matched
  "fields": {"game": "f1_25", "track_id": "f1:17", "layout_m": 4323, "car_id": "f1:team:7", "car_class": "f1",
             "equal_performance": 0, "category": "race", "conditions": "dry",
             "assists": {"braking": 2, "abs": null, "tc": null, "gearbox": 3, "racing_line": 2},
             "assists_code": "b2.a?.t?.g3.l2"},
  "labels": {"game": "F1 25", "track": "Austria", "layout": "4.32 km", "car": "Haas", "car_class": "F1 car",
             "equal_performance": "Realistic car performance", "category": "Race", "conditions": "Dry",
             "assists": [{"key": "braking", "value": 2, "known": true, "label": "Braking assist medium"}, ...],
             "assists_text": "Braking assist medium, ABS unknown, ...", "title": "Austria · Haas · Race · Dry"},
  "rows": [{
    "position": 1, "driver_id": 1, "driver_name": "Sam", "lap_ms": 70549, "lap_id": 52, "lap_number": 64,
    "session_id": "a1b2c3d4e5f6", "set_unix": 1791668708.2, "date_text": "Sat 10 Oct",
    "leader": true, "gap_ms": null, "gap_pct": null, "gap_text": "Fastest",      // others: 3067, 4.35, "3.067 s behind"
    "clean_laps": 18, "assists": [...chips...], "best_sectors_ms": [16662, 31149, 22151],
    "theoretical_best_ms": 69962, "theoretical_gain_ms": 587, "game_version": "1.26",
    "vs": {}                                                   // gaps and bands to the optional rows, when present
  }],
  "no_time": [{"driver_id": 3, "driver_name": "Kim"}],        // household drivers with no lap on this board
  "record": {"driver_id": 1, "driver_name": "Sam", "lap_ms": 70549, "lap_id": 52, "session_id": "...",
             "set_unix": 1791668708.2, "date_text": "Sat 10 Oct"},
  "history": [{"lap_id": 40, "driver_name": "Sam", "lap_ms": 76577, "previous_ms": null,
               "previous_driver_name": null, "gain_ms": null, "changed_hands": false, "date_text": "Sat 10 Oct",
               "text": "Sam set the first record: 1:16.577", ...}],   // oldest first; "Jo took the record from Sam: ..."
  "evidence": {"track_limits_checked": true, "note": null, "counts": "Clean, valid laps of real driving only: ..."},
  "ea_rival": null,                                            // optional row (below)
  "real_f1": null,                                             // optional row (below)
  "boards_here": [ /* /api/records rows of every board at this track: the pickers' choices */ ],
  "matched": 1
}
```

Rows are fastest first (ties: the lap stored first). Times are neutral; the fastest row says `Fastest`. Best sectors
are each sector's best on its own across the driver's laps on the board; the theoretical best is their sum.

### `GET /api/records`

Optional `game`, `track_id`, `driver_id` (boards where that driver has a lap).
`{"boards": [{key, fields, labels, record, drivers, clean_laps, last_unix, track_limits_checked}], "count": n}`,
sorted by game, track, layout, car, category, conditions, assists.

### `GET /api/leaderboard/lapcard/{lap_id}?capture_hash=false`

The lap card (below) of any stored lap: 404 unknown lap, 409 a lap with no time. A lap that does not count on a
board still gets a card, with `evidence.counts` false and the reasons.

## Optional rows: EA rival and real F1

Two rows that are not household drivers plug into every board through `leaderboard/service.py`:

- `ea_rival_for(conn, key) -> Benchmark | None`: the F1 25 Time Trial rival from EA's leaderboard (UDP packet 14,
  stored per session by the packet-14 work). Only for F1 Time Trial boards: the latest stored rival dataset at
  `key.track_id` whose team is `key.car_id`. `Benchmark("ea_rival", lap_ms, "EA rival", caveat, detail)` with
  `detail` = `sectors_ms`, `assists` (TC, gearbox, ABS on / off as packet 14 sends them), `equal_performance`,
  `custom_setup`, `valid`, `seen_unix`, `session_id`, `evidence: "spec-decoded"` until a recorded Time Trial capture
  exists.
- `real_f1_for(key) -> Benchmark | None`: the real-F1 benchmark of an F1 track from
  `src/pitwall/trackdata/real_f1_benchmarks.json` (F1DB, CC BY 4.0). Only for F1 boards of a track whose current
  layout is matched. `Benchmark("real_f1", pole_ms, "Real F1 pole 2025 · <driver>", caveat, detail)`; the caveat is
  always set (a real car's time: F1 25 is not the real car and conditions differ); `detail` carries the year, driver,
  what the time is, the F1DB version and attribution, and the race fastest lap and lap record.

Both return None until their data lands. With a row present, `board.with_benchmarks` adds it to the board
(`Benchmark.to_dict()`: `{...detail, kind, lap_ms, label, caveat}`) and gives every driver row
`vs[kind] = {gap_ms, gap_pct, band}`: GT7-style bands [H], `gold` within 3 % (or faster), `silver` within 5 %,
`bronze` within 10 %, else null.

## Badge, engineer and radio

- **Badge** `family_record:<key>` ("Family record at Austria", `motivation/badges.py`): a board is contested from the
  first lap of its second driver. The driver holding the record then earns it, and so does every driver who sets a
  new record afterwards: one per driver per board, dated by the session of the record lap, kept after the record is
  lost. Like the other track badges it needs an identified track and a lap of at least 30 s.
- **Engineer fact** (topic `records`, `leaderboard/facts.py`): the family record of the board the session drives on,
  its holder, the others' gaps, and where the session's driver stands ("The family record here is 1:10.549, by Sam.
  Your best here is 3.067s off it."). Intent `records`: "What's the family record here?", "Who holds the record?",
  "Who's fastest in the family?"; answered deterministically on the radio.
- **Radio line**: when a live lap takes a board's record from another driver ("New family record at Austria: you
  took it from Sam."; a beginner hears "You did it: the family record at Austria is yours, faster than Sam."). It goes
  through the goal-line path: the motivation worker publishes a `family_record` live note, the hub makes a `GOAL`
  message (speak windows, the per-lap budget, at most two goal or record lines per session), and it never states a lap
  time. Improving your own record is a personal best, which the lap summary already says.

## The lap card (format v1, for a future online board)

A small JSON object for one lap. `GET /api/leaderboard/lapcard/{lap_id}` builds it on this machine; nothing sends it.

| Field | Meaning |
|---|---|
| `format`, `version` | `"pitwall.lapcard"`, `1`. A change that alters a field's meaning bumps the version |
| `board` | `key` (string form) plus every key field (as `fields` above); null for a lap at an unknown track |
| `labels` | game, track, layout, car, category, conditions and assists in words (public names only) |
| `lap_ms`, `sectors_ms` | the lap time and the three sectors (null when the game sent none) |
| `date` | the day the lap was stored, `YYYY-MM-DD` (local); never the time of day |
| `game` | `id`, `version` (F1: "1.26"), `platform` (null when unknown), `packet_format` |
| `pitwall_version` | the Pitwall version that built the card |
| `assists` | the assist values of the key (null for a game that reports none) |
| `evidence` | `timed`, `clean`, `valid` (null: not reported by the game), `track_limits_checked`, `synthetic`, `replay`, `owned`, `track_known`, `track_identified` (a named track, not GT7's "Unidentified ..."), `counts` (true when the lap counts on the local board) and `reasons` |
| `capture_sha256` | only with `?capture_hash=true`: SHA-256 of the session's capture file, null when there is none. The capture itself is never part of a card: it holds every raw packet, other players' names included |
| `online_name` | a separate display name for an online board: empty by default, never the household profile name and never a PSN / Xbox / Steam id |

The card never names the household driver and never carries traces, setups or other players' data.

### What an online board needs from the owner first

An online board (step 4 of the leaderboard plan) is a decision for the owner, not something Pitwall does on its own:

1. **Who runs and moderates it**: removing laps, handling reports and deletion requests.
2. **UK GDPR and the ICO Children's code**: whoever hosts it is the data controller. A family rig means children may
   use it, and the Children's code covers services likely to be used by under-18s even when not aimed at them.
3. **Child profiles never go online by default**: opt-in per profile, per board, with a versioned notice (the pattern
   of the cloud AI privacy notice).
4. **Categories**: Time Trial only (fixed conditions, game-validated laps, assists in packet 14) or every session
   type; which assist classes are separate boards.
5. **Licence for submitted data** (for example CC0 or CC BY) and a licence for the repository itself (it has none
   today).
6. **Hosting**: Lovable (with Supabase) is the owner's likely choice; a static GitHub board or shared lap cards are
   the alternatives in the research.
7. **Anti-cheat trust tiers**: UDP is unauthenticated (`pitwall send` already streams a capture over real UDP), so any
   lap can be forged and a signature proves only which install sent it. Tiers: self-reported (the card alone), with
   capture (a redacted capture whose hash matches, re-run with `pitwall replay` to recompute the time), reviewed.
   Plausibility checks Pitwall can run: game validity (F1 only), the clean-lap rules, the synthetic flag and
   `SYNTHETIC_SESSION_UID`, replay exclusion, session type and game mode, assists and equal performance, game
   version, layout length, sectors summing to the lap time, and a lap not far faster than a known benchmark (the EA
   rival, a real-F1 time).

## Evaluation on the owner's data (2026-10-15)

A read-only copy of the owner's database (`.backup` of a copy; the original was never opened for writing):

- 22 boards: 20 F1 25, 2 GT7 (both "Unidentified GT7 circuit", no session type, weather or assists from GT7).
  All 120 clean laps of real driving are on a board.
- One contested board: Austria · Haas · Race · Dry (`b2.a?.t?.g3.l2`): the owner 1:10.549, the second profile
  1:13.616 (+3.067 s, 4.35 %). The owner holds every record and earns one family-record badge.
- 11 boards have ABS unknown (laps stored before the per-lap assists), 8 ABS on, 1 ABS off (Sakhir, F2): the
  owner's Sakhir F2 laps split into two boards by ABS, as designed.
- The whole record index takes about 60 ms on this database (both window-function queries about 11 ms).
