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
| assists | F1: braking assist, ABS, traction control, gearbox, racing line. Braking, gearbox and line come from the Session packet and count only once its tail is filled (F1 25 sends gearbox 0 for the first ~1.5 s of a session); ABS and TC come from the lap itself (the value on 90 % of its moving frames). AC: ABS and TC on / off. ACC: the lap's TC level as a number on ACC's own scale (about 0-11 on a GT3; never on / off, ACC documents no "off" level), so laps at different levels never share a board. GT7, Forza and the other games report no assists: one "not reported" class |

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
car"). When several boards match, the one driven most recently is shown. With either form, `car_generation`
(`f1_2025|f1_2026`) is the driver's answer when the game cannot tell a 2025 from a 2026 car (below); it never
changes which board is shown. 422: a key or field that does not parse.

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
    "vs": {"real_f1": {"gap_ms": 6578, "gap_pct": 10.28, "gap_text": "6.578 s slower", "band": null}}
                                         // one entry per optional row present ("ea_rival", "real_f1"); else {}
  }],
  "no_time": [{"driver_id": 3, "driver_name": "Kim"}],        // household drivers with no lap on this board
  "record": {"driver_id": 1, "driver_name": "Sam", "lap_ms": 70549, "lap_id": 52, "session_id": "...",
             "set_unix": 1791668708.2, "date_text": "Sat 10 Oct"},
  "history": [{"lap_id": 40, "driver_name": "Sam", "lap_ms": 76577, "previous_ms": null,
               "previous_driver_name": null, "gain_ms": null, "changed_hands": false, "date_text": "Sat 10 Oct",
               "text": "Sam set the first record: 1:16.577", ...}],   // oldest first; "Jo took the record from Sam: ..."
  "evidence": {"track_limits_checked": true, "note": null, "counts": "Clean, valid laps of real driving only: ..."},
  "ea_rival": null,                                            // optional row (below): Time Trial boards only
  "real_f1": {"kind": "real_f1", "lap_ms": 63971, "label": "Real F1 pole 2025 · Lando Norris", ...},  // (below)
  "real_f1_note": null,            // an F1-car board with no real_f1 row: why, in plain words; else null
  "real_f1_asks_generation": false, // true: the game cannot tell a 2025 from a 2026 car here (ask, car_generation)
  "boards_here": [ /* /api/records rows of every board at this track: the pickers' choices */ ],
  "matched": 1
}
```

Rows are fastest first (ties: the lap stored first). Times are neutral; the fastest row says `Fastest`. Best sectors
are each sector's best on its own across the driver's laps on the board; the theoretical best is their sum.

### `GET /api/records`

Optional `game`, `track_id`, `driver_id` (boards where that driver has a lap), `car_generation` (as above, for every
board whose car generation the game could not tell).
`{"boards": [{key, fields, labels, record, drivers, clean_laps, last_unix, track_limits_checked, vs}], "count": n}`,
sorted by game, track, layout, car, category, conditions, assists. `vs` is the record's gap and band to the board's
optional rows: `{"real_f1": {"lap_ms", "label", "gap_ms", "gap_pct", "gap_text", "band"}, "ea_rival": {...}}`, only
the rows present (`{}` for most boards).

### `GET /api/leaderboard/lapcard/{lap_id}?capture_hash=false`

The lap card (below) of any stored lap: 404 unknown lap, 409 a lap with no time. A lap that does not count on a
board still gets a card, with `evidence.counts` false and the reasons.

## Optional rows: EA rival and real F1

Two rows that are not household drivers, found by `leaderboard/service.py` for every board. Each is
`{...detail, "kind", "lap_ms", "label", "caveat", "banded"}` (`board.Benchmark.to_dict`), and every driver row gets
`vs[kind] = {gap_ms, gap_pct, gap_text, band}`: `gap_ms` positive = slower than the row, `gap_text` "6.578 s slower" /
"0.549 s faster" / "Same time", and GT7-style bands [H]: `gold` within 3 % (or faster), `silver` within 5 %, `bronze`
within 10 %, else null (`trackdata.real_f1.band_for`, one rule for both rows; `banded` false: gaps only, no band).

**EA rival** (`ea_rival_for`): the rival the driver picked from EA's Time Trial leaderboard, from UDP packet 14
(`session_time_trial`, schema v7; `repo.latest_tt_rival`). Only on F1 Time Trial boards with a known car: the latest
valid, timed rival lap stored at the board's track and layout (3 %), in the board's exact car (the rival's team), with
the board's "equal car performance" setting (unknown matches only unknown), from real sessions only (never synthetic,
never a replay). The rival's TC, ABS and gearbox flags are on / off and do not line up with the board's assist
classes, so they are shown, never matched. **Spec-decoded**: no recorded Time Trial capture yet (docs/status.md).

```jsonc
"ea_rival": {
  "kind": "ea_rival", "lap_ms": 64500, "label": "EA rival", "banded": true,
  "caveat": "The rival you picked from EA's Time Trial leaderboard, as the game sends it. Its assists and setup may
             differ from yours. Read from EA's spec: not yet seen in a recording.",
  "sectors_ms": [16000, 28000, 20500],                       // null for a sector the game sent as 0
  "assists": {"traction_control": false, "anti_lock_brakes": true, "gearbox_assist": false},   // null = unknown
  "assists_text": "Traction control off, ABS on, Gearbox assist off",
  "equal_performance": false, "custom_setup": false, "valid": true, "car_name": "McLaren",
  "seen_unix": 1791656220.0, "date_text": "Sat 10 Oct",      // when Pitwall stored it (the game gives no date)
  "session_id": "a1b2c3d4e5f6",
  "evidence": "spec-decoded", "evidence_level": "spec_implemented"   // capabilities: F1_25_INFO.fields["time_trial"]
}
```

**Real F1** (`real_f1_row`): a real car's pole from `src/pitwall/trackdata/real_f1_benchmarks.json` (F1DB v2026.17.0,
CC BY 4.0). Only on F1-car boards (never F2, classic F1 or an unknown class) of a track whose current real layout
matched the game's lap within 3 %, and only when the board's own layout is that length. The pole is the one of the
season the car models: a 2025 car (the base game's teams) gets the 2025 pole, a 2026 Season Pack car the 2026 pole
(real 2026 cars lap a few percent slower). The generic car in UDP format 2025 (F1 World, or a 2026 car) cannot be told
apart: no row, `real_f1_note` says why and `real_f1_asks_generation` is true; the screen may ask the driver and pass
`car_generation`, which fills in only a generation the game did not tell (`generation_chosen` true). A pole slower
than that race's fastest lap (Las Vegas 2025: probably a wet qualifying; F1DB has no weather) is shown with
`banded: false` and a `band_note`. The caveat is always set, and `source` carries the credit CC BY 4.0 asks for: any
screen showing a real time shows the caveat and a short linked credit ("Real F1 times: F1DB, CC BY 4.0").

```jsonc
"real_f1": {
  "kind": "real_f1", "lap_ms": 63971, "label": "Real F1 pole 2025 · Lando Norris", "banded": true,
  "caveat": "Real Formula 1 times, set by real cars in real sessions. F1 25 is not the real car, ...",
  "what": "pole", "what_text": "Pole lap: qualifying P1's deciding lap", "time_text": "1:03.971",
  "year": 2025, "date": "2025-06-28", "driver": "Lando Norris", "grand_prix": "Austrian Grand Prix",
  "season": 2025, "generation": "f1_2025", "generation_chosen": false, "band_note": null,
  "race_fastest_lap": {"time_ms": 67924, "time_text": "1:07.924", "year": 2025, "date": "2025-06-29",
                       "driver": "Oscar Piastri", "grand_prix": "Austrian Grand Prix", "session": "race", "lap": 59},
  "lap_record": {..., "label": "Fastest race lap on this layout (F1DB)"},   // not "the official lap record"
  "layout": {"f1db_layout_id": "spielberg-3", "layout_length_m": 4326, "game_length_m": 4323},
  "source": {"name": "F1DB", "version": "v2026.17.0", "released": "2026-10-11", "url": "...", "release_url": "...",
             "licence": "CC BY 4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0/",
             "attribution": "Real Formula 1 times and circuit layouts: F1DB v2026.17.0 by ..."}
}
```

`real_f1_note` (null when the row is there or the board is not an F1-car board): "Real Formula 1 has no time on this
layout." (reverse and short layouts, Hanoi), "The game's lap here is not the real circuit's length, so a real time
would not compare." (Monaco, Mexico at F1DB v2026.17.0, or a session of another length), "The game does not say
whether this is a 2025 or a 2026 car, so there is no real season to compare with.", "Real Formula 1 has no pole time
here for 2025." (Madrid).

## On screen: Review › Progress, Records

The React dashboard's Records section (`web-react/src/pages/review/progress/{FamilyBoardCard,TimesToBeatCard,
RecordHistoryCard,useRecords}`, pure logic in `web-react/src/lib/review/records.ts`, client in
`web-react/src/lib/endpoints/leaderboard.ts`) follows the page's driver, track and car:

- **Which board**: `GET /api/records?game&track_id&driver_id=<viewed driver>` lists the boards here where that driver
  has a lap; the section opens the newest of them in the page's car (any car: the newest of all), by key. A driver
  with no board here gets the server's pick by fields (`game`, `track_id`, `car_id`). The family board is always one
  exact key: the old any-car fallback (each driver's best at the track in any car) is gone.
- **Pickers**: one per key part that differs between the boards here (car, session type, weather, car performance,
  layout, assists), from `boards_here`; assists are named by the settings that differ ("ABS on" / "ABS off"). Picking
  a value opens the board that keeps the most of the other parts, newest first on a tie. With the page's car set, the
  pickers stay in that car unless it has no board here (then every board here, and a note says the car differs).
- **Rows**: the server's gap words ("3.067 s behind"), the percentage, date and clean laps beyond the beginner's view,
  best sectors and their sum for advanced drivers; household drivers with no lap there say so. A column per optional
  row gives each driver's `vs` gap and the band chip (gold / silver / bronze, none when `band` is null) with the band
  rule under the board.
- **Width**: the cells wrap to their narrowest (the "in the seat" chip under the name, a band chip over its gap), and
  below the `lg` breakpoint (iPad portrait) an advanced driver's best sectors leave the table for a list under the
  board, so a Time Trial board with both times to beat fits 820 px without sideways scrolling (measured: 652 px of
  table in 652 px). From iPad landscape the sectors are a column; on a phone the table scrolls inside the card.
- **Times to beat**: each optional row with its caveat, always; the real pole with the linked F1DB credit ("Real F1
  times: F1DB, CC BY 4.0"); the EA rival labelled spec-decoded; `real_f1_note` in muted text; a 2025 car / 2026 car
  choice when `real_f1_asks_generation` (sent back as `car_generation`, kept while the page is open).
- **Record history**: newest first; beginners see the latest change, intermediate 4, advanced 8, then Show all.
- The requests live under the dashboard cache's `driver-sessions:` prefix, so every completed lap, driver switch or
  session moved to another driver refreshes the board.

## Badge, engineer and radio

- **Badge** `family_record:<key>` ("Family record at Austria", `motivation/badges.py`): a board is contested from the
  first lap of its second driver. The driver holding the record then earns it, and so does every driver who sets a
  new record afterwards: one per driver per board, dated by the session of the record lap, kept after the record is
  lost. Like the other track badges it needs an identified track and a lap of at least 30 s. It is listed on
  Review › Goals with the others; the Session complete card leaves it out when the Best lap tile's REC tag is the same
  lap (`web-react/src/lib/drive/complete.ts`: each fact once), and shows it when the tile's REC is another lap (the
  looser game + track + car + layout best) or there is no REC.
- **Engineer fact** (topic `records`, `leaderboard/facts.py`): the family record of the board the session drives on,
  its holder, the others' gaps, and where the session's driver stands ("The family record here is 1:10.549, by Sam.
  Your best here is 3.067s off it."). Intent `records`: "What's the family record here?", "Who holds the record?",
  "Who's fastest in the family?"; answered deterministically on the radio.
- **Radio line**: when a live lap takes a board's record from another driver ("New family record at Austria: you
  took it from Sam."; a beginner hears "You did it: the family record at Austria is yours, faster than Sam."). It goes
  through the goal-line path: the motivation worker publishes a `family_record` live note, the hub makes a `GOAL`
  message (speak windows, the per-lap budget, at most two goal or record lines per session), and it never states a lap
  time. Improving your own record is a personal best, which the lap summary already says. The note also reaches
  `/ws/live` as `{"type": "family_record", "data": {...}}`; the dashboard does not show it (Drive shows no pop-ups on
  track), and the Records section and the badges refresh after the lap anyway.

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

An online board (step 4 of the leaderboard plan) is a decision for the owner, not something Pitwall does on its own.
Nothing in this branch sends anything; these are the questions to settle before any code is written:

1. **Who runs and moderates it**: removing laps, handling reports, answering access and deletion requests, and
   what happens to the data if the board is closed.
2. **UK GDPR and the ICO Children's code**: whoever hosts it is the data controller (a privacy notice, a lawful basis,
   a retention period, where the data is stored). A family rig means children may use it, and the Children's code
   covers services likely to be used by under-18s even when they are not aimed at them: high-privacy defaults, no
   nudging to share, no profiling.
3. **Child profiles never go online by default**: opt-in per profile and per board by a grown-up, with a versioned
   notice (the pattern of the cloud AI privacy notice); a profile's online laps can be withdrawn.
4. **Identity**: the separate `online_name` only (never the household profile name, a PSN / Xbox / Steam id or an
   e-mail), plus a random install id; whether an install needs an account at all.
5. **Categories**: Time Trial only (fixed conditions, game-validated laps, assists in packet 14) or every session
   type; which assist classes are separate boards; F1 25 only at first or GT7 / AC too (their laps can only say
   "track limits not checked").
6. **What a lap card carries**: the v1 fields only, or per-corner metrics as well (brake start, trail-braking, minimum
   speed), which would be the more interesting dataset and the more personal one.
7. **Licences**: one for submitted data (for example CC0 or CC BY) and one for the repository itself (it has none
   today). EA rival times and real-F1 times are never submitted as laps: the EA rival is EA's leaderboard data seen
   in the player's game, and a real-F1 row shown online needs the F1DB credit there too (docs/licences.md).
8. **Hosting**: Lovable (with its Supabase backend) is the owner's likely choice (below); a static GitHub board or
   lap cards shared as files are the alternatives in the research.
9. **Anti-cheat trust tiers**: UDP is unauthenticated (`pitwall send` already streams a capture over real UDP), so any
   lap can be forged and a signature proves only which install sent it. Tiers: self-reported (the card alone), with
   capture (a redacted capture whose hash matches, re-run with `pitwall replay` to recompute the time), reviewed.
   Plausibility checks Pitwall can run: game validity (F1 only), the clean-lap rules, the synthetic flag and
   `SYNTHETIC_SESSION_UID`, replay exclusion, session type and game mode, assists and equal performance, game
   version, layout length, sectors summing to the lap time, and a lap not far faster than a known benchmark (the EA
   rival, a real-F1 time).

### If the board is hosted on Lovable (design notes, step 4)

Lovable builds a web app (a React front end) with a hosted Supabase backend (Postgres, auth, storage and server-side
functions). How that would meet Pitwall, if the owner goes ahead; none of it exists yet and the details are to be
checked against Lovable's and Supabase's terms and current features when the board is built:

- **Pitwall stays local.** The board is a separate app in its own repository; Pitwall only ever sends a lap card
  when a driver presses "Share this lap" for a lap on a board their profile opted into, and reads the public board
  with one GET (like the update check) only when that is switched on. No background upload, no telemetry stream.
- **One write path.** Cards arrive through one server-side function that checks the format and version (it refuses
  a version it does not know), the evidence flags (`counts` true, not synthetic, not a replay), the plausibility
  checks above and a rate limit per install id. The database is closed to direct writes by row-level security: a
  Supabase project's public (anon) key ships in every browser app, so it must not be enough to insert a lap.
- **What is stored**: the lap card's fields and the install id. No household names, no captures (a capture hash at
  most), no traces, no other players' data; the EA rival and real-F1 rows are not stored as laps.
- **Region and deletion**: a project region the owner's privacy notice names (UK or EU), a retention period, and a
  way for an install to delete its laps (a delete token kept on that machine).
- **Secrets**: Pitwall would hold only the board's public URL and anon key (public by design); no service-role or
  admin key ever goes in Pitwall's settings, its repository or a release zip.
- **The contract is the lap card**: format `pitwall.lapcard` version 1 above. A change that alters a field's meaning
  bumps the version on both sides.

## Evaluation on the owner's data (2026-10-15)

The final run of the branch on a fresh read-only copy of the owner's database (the database file with its `-wal` and
`-shm` copied into a scratch folder, then sqlite3's `.backup` of the copy; the original was never opened). The owner
is "the owner" and the second household profile "the second profile" here.

**Boards.** 22 boards: 20 F1 25, 2 GT7 (both "Unidentified GT7 circuit", no session type, weather or assists from
GT7). All 120 clean, valid, timed laps of real driving (owned, live UDP sessions at known tracks) are on a board. The
owner holds all 22 records. One board is contested: Austria · Haas · Race · Dry (`b2.a?.t?.g3.l2`): the owner
1:10.549 (18 clean laps, best sectors adding up to 1:09.962), the second profile 1:13.616 (+3.067 s, 4.35 %; 5 clean
laps); its record history is three records by the owner (1:16.577, 1:11.745, 1:10.549), so the record has never
changed hands and the owner earns one family-record badge. 11 boards have ABS unknown (laps stored before the
per-lap assists), 8 ABS on, 1 ABS off: the owner's Sakhir F2 laps split into two boards by ABS, as designed. No Time
Trial session is stored, so no board has an EA rival row. The record index takes about 9 ms (5 runs).

| Board (session type and weather in the key; all dry) | Assists | Record (the owner) | Real F1 row (F1-car boards) |
|---|---|---|---|
| Austria · Haas · Race | `b2.a?.t?.g3.l2` | 1:10.549 (contested) | 2025 pole 1:03.971 (Norris): +10.28 %, no band |
| Austria · F1 Generic · Race | `b0.a?.t?.g3.l2` | 1:18.351 | asks the generation (2025: +22.48 %; 2026: +18.51 %; no band) |
| Austria (Reverse) · F1 Generic · Race | `b0.a?.t?.g3.l2` | 1:29.483 | none: real F1 has no time on this layout |
| Imola · McLaren · Race | `b2.a1.t2.g3.l2` | 1:20.886 | 2025 pole 1:14.670 (Piastri): +8.32 %, **bronze** |
| Jeddah · F2 Art GP '24 · Race | `b3.a1.t2.g3.l2` | 1:45.401 | none (F2) |
| Las Vegas · F1 Generic · Race | `b2.a?.t?.g3.l2` | 1:36.953 | asks (2025: pole 1:47.934 was slower than the race's fastest lap: -10.17 %, no band; 2026: not raced yet) |
| Melbourne · F2 Art GP '24 · Qualifying | `b3.a1.t?.g3.l2` | 1:31.525 | none (F2) |
| Melbourne · F2 Hitech '25 · Race | `b2.a?.t?.g3.l2` | 1:35.588 | none (F2) |
| Melbourne · McLaren · Race | `b1.a1.t2.g3.l2` | 1:23.772 | 2025 pole 1:15.096 (Norris): +11.55 %, no band |
| Melbourne · McLaren · Practice | `b1.a1.t2.g3.l2` | 1:23.634 | 2025 pole 1:15.096: +11.37 %, no band |
| Miami · F1 Generic · Race | `b2.a?.t?.g3.l2` | 1:33.117 | asks (2025: +8.02 % bronze; 2026: +6.06 % bronze) |
| Montreal · F1 Generic · Race | `b2.a?.t?.g3.l2` | 1:15.523 | asks (2025: +6.52 % bronze; 2026: +4.06 % **silver**) |
| Monza · F1 Generic · Race | `b0.a?.t?.g3.l2` | 1:28.663 | asks (2025: +12.53 %, no band; 2026: +8.41 % bronze) |
| Sakhir · F2 Art GP '24 · Race | `b0.a0.t1.g3.l2` (ABS off) | 1:48.897 | none (F2) |
| Sakhir · F2 Art GP '24 · Race | `b0.a1.t1.g3.l2` (ABS on) | 1:46.540 | none (F2) |
| Shanghai · McLaren · Practice | `b0.a1.t2.g3.l2` | 1:49.642 | 2025 pole 1:30.641 (Piastri): +20.96 %, no band |
| Silverstone · F1 Generic · Race | `b1.a?.t?.g3.l2` | 1:43.819 | asks (2025: +22.30 %; 2026: +17.83 %; no band) |
| Silverstone (Reverse) · F1 Generic · Race | `b2.a?.t?.g3.l2` | 1:34.318 | none: real F1 has no time on this layout |
| Suzuka · F1 Generic · Race | `b1.a1.t2.g3.l2` | 1:35.707 | asks (2025: +10.03 %, no band; 2026: +7.80 % bronze) |
| Suzuka · unknown car · Race | `b2.a?.t?.g3.l2` | 1:36.360 | none (car unknown) |
| GT7 unidentified circuit (0.92 km) · car 919 | `-` | 0:23.055 | - |
| GT7 unidentified circuit (3.80 km) · car 3353 | `-` | 1:43.358 | - |

So 5 of the 20 F1 boards get a real pole as they are; the 7 generic-car boards (UDP format 2025 cannot say whether
the generic car is a 2025 or a 2026 car) get one once the driver answers the 2025 / 2026 question on screen.

**F1DB coverage** (`src/pitwall/trackdata/real_f1_benchmarks.json`, F1DB v2026.17.0): 23 of the 37 F1 track ids are
matched (the game's lap within 3 % of F1DB's current layout).

| F1 25 track (id) | F1DB layout, length vs the game's | 2025 pole | 2026 pole | Fastest race lap on the layout |
|---|---|---|---|---|
| Melbourne (0) | melbourne-2, 5278 / 5276 m | 1:15.096 Norris | 1:18.518 Russell | 1:19.813 Leclerc 2024 |
| Shanghai (2) | shanghai-1, 5451 / 5441 m | 1:30.641 Piastri | 1:32.064 Antonelli | 1:32.238 Schumacher 2004 |
| Sakhir (3) | bahrain-1, 5412 / 5408 m | 1:29.841 Piastri | - | 1:30.252 Schumacher 2004 |
| Catalunya (4) | catalunya-6, 4657 / 4664 m | 1:11.546 Piastri | 1:14.679 Russell | 1:15.743 Piastri 2025 |
| Montreal (6) | montreal-6, 4361 / 4371 m | 1:10.899 Russell | 1:12.578 Russell | 1:13.078 Bottas 2019 |
| Silverstone (7) | silverstone-8, 5891 / 5890 m | 1:24.892 Verstappen | 1:28.111 Antonelli | 1:27.097 Verstappen 2020 |
| Hungaroring (9) | hungaroring-3, 4381 / 4378 m | 1:15.372 Leclerc | 1:17.207 Norris | 1:16.627 Hamilton 2020 |
| Spa (10) | spa-francorchamps-4, 7004 / 7007 m | 1:40.562 Norris | 1:44.361 Antonelli | 1:44.701 Pérez 2024 |
| Monza (11) | monza-7, 5793 / 5798 m | 1:18.792 Verstappen | 1:21.786 Gasly | 1:20.901 Norris 2025 |
| Singapore (12) | marina-bay-4, 4927 / 4928 m | 1:29.158 Russell | 1:31.373 Verstappen | 1:33.808 Hamilton 2025 |
| Suzuka (13) | suzuka-2, 5807 / 5809 m | 1:26.983 Verstappen | 1:28.778 Antonelli | 1:30.965 Antonelli 2025 |
| Abu Dhabi (14) | yas-marina-2, 5281 / 5280 m | 1:22.207 Verstappen | - | 1:25.637 Magnussen 2024 |
| Texas (15) | austin-1, 5513 / 5514 m | 1:32.510 Verstappen | - | 1:36.169 Leclerc 2019 |
| Brazil (16) | interlagos-2, 4309 / 4294 m | 1:09.511 Norris | - | 1:10.540 Bottas 2018 |
| Austria (17) | spielberg-3, 4326 / 4323 m | 1:03.971 Norris | 1:06.113 Russell | 1:05.619 Sainz 2020 |
| Baku (20) | baku-1, 6003 / 5994 m | 1:41.117 Verstappen | 1:42.526 Russell | 1:43.009 Leclerc 2019 |
| Zandvoort (26) | zandvoort-5, 4259 / 4258 m | 1:08.662 Piastri | 1:11.163 Norris | 1:11.097 Hamilton 2021 |
| Imola (27) | imola-3, 4909 / 4910 m | 1:14.670 Piastri | - | 1:15.484 Hamilton 2020 |
| Jeddah (29) | jeddah-1, 6174 / 6175 m | 1:27.294 Verstappen | - | 1:30.734 Hamilton 2021 |
| Miami (30) | miami-1, 5412 / 5410 m | 1:26.204 Verstappen | 1:27.798 Antonelli | 1:29.708 Verstappen 2023 |
| Las Vegas (31) | las-vegas-1, 6201 / 6200 m | 1:47.934 Norris (slower than the race's fastest lap: gaps, no band) | - | 1:33.365 Verstappen 2025 |
| Losail (32) | lusail-1, 5419 / 5417 m | 1:19.387 Piastri | - | 1:22.384 Norris 2024 |
| Madrid (42, 2026 Season Pack) | madring-1, 5416 / 5411 m | - (first raced 2026) | 1:31.824 Norris | 1:35.587 Russell 2026 |

Not matched (no real row, `real_f1_note` says why): **Monaco** (5): the track sheet's 3067 m against F1DB's 3337 m
(8.1 %; the sheet's length is known to be truncated, a recorded Monaco session will settle it); **Mexico** (19): the
game's 4525 m against F1DB's 4304 m (4.9 %; the game's lap appears longer than the real circuit, not yet confirmed by
a recording); the **reverse layouts** Silverstone (39), Austria (40) and Zandvoort (41): real F1 never raced them.
Not in F1 25 (no game length to check): Paul Ricard (1), Hockenheim (8), Sochi (18), Portimão (28), Hanoi (25: no
F1DB circuit) and the short layouts of Sakhir, Silverstone, Texas and Suzuka (21-24). A "-" 2026 pole is a race not
yet run at F1DB v2026.17.0 or not on the 2026 calendar: a 2026 car there gets no real row until a newer F1DB release
is built in.

Bands against real poles are the [H] GT7 thresholds; the owner's records are 8-21 % off the real pole on the 5 boards
that get one as they are (4-22 % with the generic car's generation answered), so most boards show gaps without a
band. Worth the owner's look before release.
