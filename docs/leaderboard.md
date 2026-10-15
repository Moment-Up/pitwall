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
- The whole record index takes about 60 ms on this database (both window-function queries about 11 ms); with the
  optional rows wired in, about 10-13 ms on a later run of the merged branch (a different load on the machine).
- Optional rows (merged branch, 2026-10-15): no EA rival (no Time Trial session is recorded). A real-F1 row on 5 of
  the 20 F1 boards, the ones in a 2025 team's car: Imola · McLaren · Race +8.32 % (bronze), Austria · Haas · Race
  +10.28 %, Melbourne · McLaren · Race +11.55 % and · Practice +11.37 %, Shanghai · McLaren · Practice +20.96 % (no
  band). 7 boards in the generic car (UDP format 2025) ask for the car generation instead (with "2025": Miami and
  Montreal bronze; with "2026": Montreal silver, Miami, Monza and Suzuka bronze); the two reverse layouts have no real
  layout; the 5 F2 boards and the unknown-car board get no row.
