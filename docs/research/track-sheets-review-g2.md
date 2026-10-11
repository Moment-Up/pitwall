# Track sheet review, group 2: F1 25 ids 1, 2, 3, 4, 5, 6, 9, 12

Hand review of the corner-identity track sheets (layer L2, `src/pitwall/trackdata/track_sheets/f1/`) for Paul
Ricard (1), Shanghai (2), Bahrain (3), Catalunya (4), Monaco (5), Montreal (6), Hungaroring (9) and Singapore (12).
Reviewed 2026-10-10/11 against FIA circuit maps, F1DB, Wikipedia/the circuits' own announcements and, where one
exists, pitwall's own recorded F1 25 capture. Design source: `docs/research/track-knowledge-sources.md` sections
2 (L2), 4.1 (per-track warnings), 6 (alignment and validation) and 8 (phase 2). The standard followed is
`17_austria.toml`.

## Summary

| Id | Track | Capture | Verified turns | Sheet changed | Result |
|---|---|---|---|---|---|
| 1 | Paul Ricard | none | - | no sheet | not in F1 25 (no PnG file, legacy id absent from EA's F1 25 spec); nothing to review |
| 2 | Shanghai | none | 0 / 14 entries (16 turns) | no | numbering 1-16 = FIA/F1DB; windows plausible; no names |
| 3 | Bahrain | none | 0 / 12 entries (15 turns) | no | numbering 1-15 = FIA/F1DB; S2 landmark 21 m before the T13 window |
| 4 | Catalunya | none | 0 / 12 entries (14 turns) | no | numbering 1-14 = FIA 2025/F1DB (2023+ layout); 6 of 8 names confirmed |
| 5 | Monaco | none | 0 / 15 entries (19 turns) | no | **numbering wrong at T17-T19** and lap length truncated; fix needs a capture |
| 6 | Montreal | **20261010-215916** | **10 / 10 entries (14 turns)** | **yes** | verified; T10-11 window split; names classified; one name dropped |
| 9 | Hungaroring | none | 0 / 12 entries (14 turns) | no | numbering = FIA main numbers (no 1A/12A); all 12 names official since 2026-07-24 |
| 12 | Singapore | none | 0 / 16 entries (19 turns) | no | numbering 1-19 = FIA/F1DB; 2 of 6 names confirmed, "Singapore Sling" historic |

Why only Montreal changed:

- **Verification needs recorded game telemetry.** `track_identity.py` defines `verified = true` as "checked against
  recorded game telemetry and an authoritative numbering reference". Of these tracks only Montreal has a pitwall
  capture (`data/captures`, scanned 2026-10-11: Austria, Austria Reverse, Silverstone, Silverstone Reverse, Monza,
  Montreal, Las Vegas, Suzuka). Reference checks alone cannot verify a window.
- **The tests forbid hand edits to unverified sheets.** `test_unreviewed_sheets_match_the_importer_output` requires
  every sheet without a verified turn to equal the importer output byte for byte, and
  `test_seeded_sheets_never_voice_names` requires every unverified turn to keep `voice_ok = false` and
  `kind = "unclassified"`. Corrections for the other tracks are therefore recorded here, ready to apply together
  with a capture (or, for Monaco's numbering, through the importer: see the final reply's INTEGRATION NEEDED).
- **No runtime impact meanwhile.** Seeded turns never attach at the default `sheet_verified` tier, and Monaco's
  truncated length (3067 m) fails the 1.5 % length gate against any plausible game length, so the wrong T17-T19
  numbers are never shown or spoken.

### General finding: Pits n' Giggles metres are the game's own

On all 8 layouts pitwall has captured, PnG's `track_length` equals the game's Session `m_trackLength` exactly and
PnG's sector values equal the game's S2/S3 starts rounded to the metre:

| Layout | Game length / S2 / S3 (capture) | PnG |
|---|---|---|
| Austria (17) | 4323 / 1203.96 / 2934.93 | 4323 / 1204 / 2935 |
| Austria Reverse (40) | 4323 / 1388.55 / 3119.52 | 4323 / 1388 / 3120 |
| Silverstone (7) | 5890 / 1812.85 / 4293.46 | 5890 / 1813 / 4294 |
| Silverstone Reverse (39) | 5890 / 1852.60 / 4338.05 | 5890 / 1853 / 4338 |
| Monza (11) | 5798 / 1897.79 / 3726.98 | 5798 / 1898 / 3727 |
| **Montreal (6)** | **4371 / 1100.91 / 2499.77** | **4371 / 1101 / 2500** |
| Las Vegas (31) | 6200 / 1703.80 / 3376.47 | 6200 / 1704 / 3377 |
| Suzuka (13) | 5809 / 2225.65 / 4690.02 | 5809 / 2226 / 4690 |

So for the uncaptured tracks the windows are very probably in the game frame already (Monaco's `track_length`
excepted). That is a strong prior, not verification: the window *contents* (which turn is where) still need driven
laps. All captures are F1 25 v1.26, UDP format 2025, PS5.

### FIA sector-line cross-check (method F, research section 6.1)

FIA maps state the timing lines relative to a turn ("S1 145 m before Turn 6"). Taking PnG's sector values as the
game's (see above), the referenced turn must fall in or near the window with that number (FIA turn reference points
are undefined, so +/-20-30 m is normal):

| Track | FIA statement | Implied turn position | Sheet window | Result |
|---|---|---|---|---|
| Shanghai | S1 150 m before T6; S2 143 m before T11 | 1567; 3128 | T6 1430-1670; T11 3000-3165 | inside; inside |
| Bahrain | S1 at T5; S2 48 m before T13 | 1800; 4049 | T5-7 1735-2100; T13 4070-4275 | inside; **21 m before** |
| Catalunya | S1 50 m before T4; S2 89 m before T10 | 1674; 3499 | T4 1570-1955; T10 3350-3570 | inside; inside |
| Monaco | S1 60 m before T5; S2 67 m before T13 | 1119; 2537 | T5 1070-1180; T13-14 2480-2625 | inside; inside |
| Montreal | S1 145 m before T6; S2 190 m before T10 | 1246; 2690 | T6 1175-1290; T10 2550-2800 | inside; inside (game values) |
| Hungaroring | S1 85 m before T4; S2 100 m after T11 | 1774; 3146 | T4 1680-1855; T11 3015-3205 | inside; inside |
| Singapore | S1 150 m before T7; S2 140 m before T14 | 1806; 3616 | T7 1700-1860; T14 3500-3700 | inside; inside |

Monaco's two landmarks fit at PnG's metres although its `track_length` is 3067 m: the windows are in a ~3.3 km
game frame and only the length field is truncated (agrees with the research: MultiViewer markers fit 17/19 at
3323 m, 4/19 at 3067 m). **Never rescale Monaco's windows**; replace `lap_length_m` with the captured length.

---

## Montreal (id 6): verified

**Evidence.**

- Capture `data/captures/20261010-215916_udp20777.pwcap`: real F1 25 v1.26 PS5 race, UDP format 2025, 87 204
  packets; Session packet trackLength 4371 m, S2 start 1100.91 m, S3 start 2499.77 m (sheet 1101/2500: 0.23 m).
  Replayed read-only into a temp directory (`PITWALL_DATA_DIR=<scratch> uv run pitwall replay ...`): 3 laps, laps 2
  and 3 clean; learned model v2 from laps 2+3 is identical to the live database's `f1:6` v2.
- Player laps 2 and 3: speed, brake, throttle, steering, lateral g by lap distance.
- Field: Lap Data + Car Telemetry packets for all 22 slots, joined by frame: 42 complete car-laps (19 AI + player),
  264 speed minima (prominence >= 8 km/h, spacing >= 60 m, as `build_track_model`).
- FIA F1 2024 Canadian GP Event Notes, Circuit Map (doc 6, 06 Jun 2024, map version 3): corners 1-14; S1 145 m
  before T6; S2 190 m before T10; speed trap 250 m before T13; centreline 4.361 km.
- F1DB `montreal`: layout montreal-6 (2002-2008, 2010-2019, 2022-), 4.361 km, 14 turns, clockwise.
- en.wikipedia "Circuit Gilles Villeneuve": 14 turns; turns 1-2 "known as the Senna 'S'"; turn 10 the 180-degree
  hairpin; "Turn 14 is dubbed the Wall of Champions".
- formula1.com "What makes the Canadian Grand Prix special": "Virage Senna at Turn 1", "the hairpin at L'Epingle",
  the Wall of Champions "on the outside of the final chicane".

**Per turn** (player laps 2/3; field = all complete car-laps; directions from steering sign and lateral g; FIA
drawing agrees for every turn: 6 left, 8 right):

| Turn | Dir | Window (m) | Player | Field minima | Status |
|---|---|---|---|---|---|
| T1-2 Virage Senna | L then R | 170-500 | brake from 112-131 m; left 211-296, right 289-415; min 75/71 km/h at 362/341 m (lap 2 also 95 km/h at 278 m in T1) | 47: 256-419 m (43 R, 4 L) | verified, voiced |
| T3-4 | R then L | 630-880 | brake 643-726; right 690-771 (min 140/133 at 737/725); left 766-838 | 44: 725-877 m | verified |
| T5 | R | 950-1130 | flat, 230-260 km/h, up to 3.9 g right at 950-1110 | none | verified (flat) |
| T6 | L | 1175-1290 | brake 1158-1247; left 1215-1298; min 101/98 at 1275/1284 | 42: 1267-1284 m, all L | verified |
| T7 | R | 1290-1570 | right 1300-1445 on throttle | none | verified (flat) |
| T8-9 | R then L | 1880-2150 | brake 1897-2010; right 1974-2058 (min 124/135 at 2011/2005); left 2062-2126 | 42: 2005-2104 m (38 R, 4 L) | verified, name dropped |
| T10 The Hairpin | R | 2550-2800 | brake 2577-2697; min 62/59 at 2718/2729 | 42: 2699-2729 m, all R | verified, voiced; **window split** |
| T11 | L | 2800-2880 | flat left kink 2810-2890 (field median steering), +0.8 to +1.5 g | none | verified (flat); **new entry** |
| T12 | R | 3180-3250 | flat right bend, field steering peak 3200-3220, 285-300 km/h | none | verified (flat) |
| T13-14 Wall of Champions | R then L | 3850-4070 | brake 3747-3901; right 3870-3937 (min 135/148 at 3909/3891); left 3939-4010 (min 141/156 at 4000/4003) | 43: 3891-4000 m (42 R, 1 L) | verified, voiced |

Only 4 of 264 field minima fall outside every window (40, 78, 147 m: lap starts; 1741 m: one car on the straight).
The flat turns 5, 7, 11 and 12 have no minimum on any car-lap, so learned models normally have no corner for them.

**Corrections and decisions.**

1. **T10/T11 split.** PnG release-v5.0.0 (#345) added the missing T11 by widening the hairpin's segment to
   "[10, 11]" 2550-2880 m. The FIA map puts "11" just past the hairpin, and the capture shows a separate flat left
   kink at 2810-2890 m after the hairpin's right steering ends at ~2800 m. The learned hairpin corner was therefore
   labelled "Turns 10-11 (The Hairpin)". Now T10 = 2550-2800 m (right, "The Hairpin"), T11 = 2800-2880 m (left,
   flat). T11's centre (2840 m) is more than 60 m past the hairpin minimum, so it is reported absent, not merged.
2. **Directions added** to the single turns (T5, T6, T7, T10, T11, T12). Complexes T1-2, T3-4, T8-9 and T13-14 are
   left/right pairs off one braking zone and stay grouped without a direction (no veto), as PnG has them; the learned
   model finds both minima of the final chicane, which become "T13-14" parts 1 and 2.
3. **Names.** "Virage Senna" (T1-2, `traditional`), "The Hairpin" and "L'Épingle" (T10, `traditional`) and "Wall of
   Champions" (T13-14, `nickname`: the wall on the outside of the T14 exit) are confirmed by two independent sources
   each and voiced. **"Pont de la Concorde" (PnG T8-9) is dropped:** only en.wikipedia uses it ("the very fast Pont
   de la Concorde corner (Turn 8)"), in a passage whose other numbers ("turns 12 & 13" for the final chicane) are not
   the FIA numbering, and formula1.com does not name the corner.
4. **Windows otherwise unchanged** (PnG's). The T6/T7 boundary at 1290 m is 6 m after the latest field minimum and
   before the steering switch at 1296-1302 m; a later T6 minimum would steer left inside T7's right-hand window and
   be vetoed (unlabelled), not mislabelled.
5. `verified_formats = [2025]`: format-2026 (Season Pack) sessions stay at the seeded tier until checked.

**Learned -> official mapping** (`identify(model, zones=<capture TrackZones>)`, default tier `sheet_verified`; the
same for the replayed and the live database's models v1 and v2):

| Learned | Apex (m) | Dir | Official | Part | Match | Voice |
|---|---|---|---|---|---|---|
| T1 | 352 | right | T1-2 (Virage Senna) | | inside | "Turns 1 to 2, Virage Senna" |
| T2 | 737 | right | T3-4 | | inside | "Turns 3 to 4" |
| T3 | 1281 | left | T6 | | inside | "Turn 6" |
| T4 | 2011 | right | T8-9 | | inside | "Turns 8 to 9" |
| T5 | 2722 | right | T10 (The Hairpin) | | inside | "Turn 10, The Hairpin" |
| T6 | 3908 | right | T13-14 (Wall of Champions) | 1 | inside | "Turns 13 to 14, Wall of Champions, first part" |
| T7 | 4003 | left | T13-14 (Wall of Champions) | 2 | inside | "Turns 13 to 14, Wall of Champions, second part" |

No learned corner (absent): T5, T7, T11, T12. Sector mismatch 0.23 m, length scale 1.0000, format 2025 verified.
Before this review the same model mapped "T5 -> T10-11" and, at the default tier, labelled nothing.

---

## Shanghai (id 2): not verified (no capture)

- **FIA:** 2024 Chinese GP Event Notes, Circuit Map (version 1, issued 17.04.24): corners 1-16, centreline 5.451 km,
  S1 150 m before T6, S2 143 m before T11, speed trap 240 m before T14. **F1DB** `shanghai`: shanghai-1, 5.451 km,
  16 turns, clockwise.
- **Numbering:** PnG 1-16 matches (complexes T9-10 and T14-15). Research: MultiViewer markers 16/16 inside.
- **Windows:** in lap order, 120-349 m long, last ends at 5230 m of 5441 m; both FIA sector landmarks inside the
  right windows. Sheet length 5441 m vs FIA 5451 m (-0.18 %): plausible game length, unconfirmed.
- **Directions (FIA drawing, provisional until measured):** T1 R, T2 R, T3 L, T4 L, T5 R, T6 R, T7 L, T8 R, T9 L,
  T10 L, T11 L, T12 R, T13 R, T14 R, T15 R (small on the drawing; confirm), T16 L. So the T9-10 complex is left
  and T14-15 probably right.
- **Names:** none in PnG; none needed.
- **To verify:** one race/practice capture with AI; check the T7/T8 boundary (2200 m, left into right) and the snail
  T1-T4 windows against steering.

## Bahrain (id 3): not verified (no capture)

- **FIA:** 2024 Bahrain GP Event Notes, Circuit Map and Red Zone (version 0, issued 30.01.2024): corners 1-15,
  centreline 5.412 km, S1 at T5, S2 48 m before T13, speed trap 158 m before T1. **F1DB** `bahrain`: bahrain-1,
  5.412 km, 15 turns, clockwise.
- **Numbering:** PnG 1-15 matches (complexes T5-7 and T14-15). MultiViewer 15/15.
- **Windows:** lap order fine, 100-365 m; S1 landmark inside T5-7. The S2 landmark (4049 m) is 21 m before the T13
  window (4070-4275): within FIA reference-point slack, but check T13's window start on a capture. Sheet length 5408
  m = the game's (third-party clip; research section 4.1) vs FIA 5412 m.
- **Directions (drawing):** T1 R, T2 L, T3 R, T4 R, T5 L, T6 R, T7 L, T8 R, T9 L, T10 L, T11 L, T12 R, T13 R,
  T14 R, T15 R. T14-15 can carry `direction = "right"`; T5-7 is mixed.
- **Names:** "Schumacher" (T1) is confirmed: en.wikipedia, the first corner was renamed after Michael Schumacher in
  2014. Classify `official` when verified; voicing OK.

## Catalunya (id 4): not verified (no capture)

- **FIA:** 2025 Barcelona event (FIA F2 stewards' doc 1, 29 May 2025), Circuit Map, "Formula 1 Aramco Gran Premio de España
  2025" (version 1, issued 24/04/25): corners 1-14, centreline 4.657 km, S1 50 m before T4, S2 89 m before T10,
  speed trap 220 m before T1. **F1DB** `catalunya`: catalunya-6 (2023-), 4.657 km, 14 turns, clockwise (the
  2007-2022 chicane layouts had 16).
- **Numbering:** PnG 1-14 is the 2023+ (no-chicane) numbering. MultiViewer 14/14.
- **Windows:** lap order fine, 110-470 m; both landmarks inside. Sheet 4664 m vs FIA 4657 m (+0.15 %).
- **Directions (drawing):** T1 R, T2 L, T3 R, T4 R, T5 L, T6 L, T7 L, T8 R, T9 R, T10 L, T11 L, T12 R, T13 R, T14 R.
- **Names:** en.wikipedia confirms T1 Elf, T3 Renault, T4 Repsol, T5 Seat, T9 Campsa, T10 La Caixa (all
  `sponsor`/historic sponsor names, long-standing; voice only if a current circuit source still uses them). **"Banc
  de Sabadell" (T12) and "New Holland" (T14) are not confirmed** by any source found: leave them out when verifying.
  PnG's "Elf" sits on the T1-2 complex; Wikipedia gives Elf for Turn 1.

## Monaco (id 5): not verified (no capture); numbering error confirmed

- **FIA:** 2025 Monaco event (FIA F3 stewards' doc 10, 22 May 2025), "Circuit Map - Monaco 2025", enclosing the F1 map Formula 1 TAG Heuer Grand
  Prix de Monaco 2025 (version 1, issued 07.05.25): corners 1-19, centreline 3.337 km, S1 60 m before T5, S2 67 m
  before T13, speed trap 188 m before T10. **F1DB** `monaco`: monaco-6 (2003-2019, 2021-), 3.337 km, 19 turns,
  clockwise.
- **Numbering error (research Action 2, confirmed on the FIA 2025 drawing):** after the swimming pool (T13 L, T14 R,
  T15 R, T16 L) the FIA map numbers **T17 = the left kink** beside the pool, **T18 = La Rascasse** (right) and **T19 =
  Antony Noghès** (right). PnG has "La Rascasse" as T17 (2820-2960 m) and "Anthony Noghes" as T18-19 (2970-3067 m),
  i.e. its last three numbers are shifted by one and the real T17 has no window.
- **Lap length:** PnG 3067 m is truncated (FIA 3337 m; both FIA sector landmarks fit at PnG's metres, so the windows
  are in a ~3.3 km game frame). The length gate refuses this sheet against any plausible game length, so nothing is
  labelled today.
- **Spellings:** "Massanet" -> **Massenet** (T3); "Anthony Noghes" -> **Antony Noghès** (T19; en.wikipedia "Virage
  Antony Noghès"). "Louis Chiron" for T13-14 is an alias (research section 4.1: formula1.com calls T13-16 the Swimming Pool);
  "Grand Hotel Hairpin" vs en.wikipedia's "Fairmont Hairpin" (formerly Station/Loews) is a hotel/sponsor name that
  changes: do not voice either until a current circuit source settles it.
- **Directions (drawing):** T1 R, T2 L, T3 L, T4 R, T5 R, T6 L, T7 R, T8 R, T9 R (tunnel), T10 L, T11 R, T12 L, T13 L,
  T14 R, T15 R, T16 L, T17 L, T18 R, T19 R.
- **To fix (needs a capture, any session, even seconds for the length):** set `lap_length_m` to the game's
  `m_trackLength` (expected ~3323-3337 m) **without rescaling windows**; renumber PnG's 2820-2960 window to T18 La
  Rascasse; make the last window T19 Antony Noghès and extend it to where the right-hander ends; add T17 (left kink)
  between T15-16 (ends 2800 m) and T18 (starts 2820 m) only if the capture shows room (it may need T15-16's end moved
  back); check every window with steering. A numbering-only stop-gap through the importer is in the final reply.

## Hungaroring (id 9): not verified (no capture)

- **FIA:** 2025 Budapest event (stewards' doc 4, 31 Jul 2025), "Circuit Map - Budapest 2025", enclosing the F1 map Formula 1 Lenovo
  Hungarian Grand Prix 2025 (version 1, issued 08.07.25): corners 1, 1A, 2-12, 12A, 13, 14; centreline 4.381 km; S1
  85 m before T4, S2 100 m after T11, speed trap 310 m before T1. **F1DB** `hungaroring`: hungaroring-3 (2003-),
  4.381 km, 14 turns, clockwise.
- **Numbering:** PnG 1-14 matches the FIA main numbers (complexes T6-7, T8-9). The FIA sub-corners **1A** (right
  kink between T1 and T2) and **12A** (left kink between T12 and T13) are missing; research: MultiViewer sub-markers
  1A and 12A fall outside PnG's segments. Add them as lettered entries (`numbers = [1]`, `label = "T1a"`;
  `numbers = [12]`, `label = "T12a"`) once a capture locates them; they are flat, so they only matter for absent
  reporting.
- **Windows:** lap order fine, 130-335 m; both landmarks inside. Sheet 4378 m vs FIA 4381 m.
- **Directions (drawing):** T1 R, 1A R, T2 L, T3 R, T4 L, T5 R, T6 R, T7 L, T8 L, T9 R, T10 L, T11 R, T12 R, 12A L,
  T13 L, T14 R.
- **Names: all 12 PnG names are official and current.** The Hungaroring announced them on 2026-07-24 (40th
  anniversary; hungaroring.hu "The Hungaroring's corners have officially been named"): T1 Piquet, T2 Hamilton, T3
  Spring, T4 Mansell, T5 Mogyoród, T6-7 Driving Center, T8-9 Buda / Pest, T10 Danube, T11 Alesi, T12 Schumacher, T13
  Senna, T14 Szisz; en.wikipedia agrees for 1, 2, 4, 11, 12, 13. They post-date F1 25's 2025 base season but are the
  corners' current real names, so they can be classified `official` and voiced when the turns are verified. Spelling
  fix: "Mogyorod" -> **Mogyoród**. The importer's review note ("2026 renames ... check before voicing") is resolved.

## Singapore (id 12): not verified (no capture)

- **FIA:** 2024 Singapore GP Event Notes, Circuit Map, Pit Lane Drawing and Red Zones (doc 4, 19 Sep 2024; map
  version A, issued 26.07.24): corners 1-19, centreline 4.940 km, S1 150 m before T7, S2 140 m before T14, speed trap
  150 m before T1. **F1DB** `marina-bay`: marina-bay-4 (2023-), 4.927 km, 19 turns, anti-clockwise (23 turns before
  the 2023 change, which replaced old turns 16-19 with a straight).
- **Numbering:** PnG 1-19 (the re-pin added T6 and T15) matches. Research: MultiViewer 17/19 (T2 6 m and T15 22 m off,
  within marker accuracy).
- **Windows:** lap order fine; T2 is only 60 m (480-540) between T1 and T3 (a left-right-left sequence: plausible but
  tight, check on a capture); both landmarks inside. Sheet 4928 m vs FIA 4940 m / F1DB 4927 m.
- **Directions (drawing):** T1 L, T2 R, T3 L, T4 L, T5 R, T6 R, T7 L, T8 R, T9 L, T10 L, T11 R, T12 L, T13 L, T14 R,
  T15 L, T16 R, T17 L, T18 L, T19 L. T18-19 can carry `direction = "left"`; T11-12 and T16-17 are mixed.
- **Names:** en.wikipedia confirms **Sheares** (T1, after President Benjamin Sheares) and **Memorial** (T7, near the
  civilian war memorial; PnG "Memorial Corner"). **"Singapore Sling" (T10) is historic:** it named the T10 chicane
  removed in 2013 ("Turn 10 is now a flowing left-hander") - do not voice. "Stamford" (T8: Wikipedia only places the
  Stamford grandstand between T7 and T8), "Padang" (T9) and "Connaught" (T14) are unconfirmed - leave out.

## Paul Ricard (id 1)

No sheet and none needed: Paul Ricard is not in F1 25 (no Pits n' Giggles file; the research lists id 1 among the
legacy ids absent from EA's F1 25 and 2026 documents, `f1-udp-spec.md` section 8.3). `find_sheet("f1_25", "f1:1")`
returns `None`, so a session there would simply keep learned names.

## What a capture must check (all uncaptured tracks)

1. Session packet: `m_trackLength` = sheet `lap_length_m`; S2/S3 starts = `sector_starts_m` (expected to <= 1 m).
2. Replay into a temp dir; for each clean player lap and every complete field car-lap: speed minima inside the
   window with the matching number; steering sign = the drawing's direction; flat turns without minima.
3. `identify(model, zones=...)` table: every learned corner labelled `inside`, no `direction_conflict`.
4. Then: set `verified`, `checked_against`, directions, name kinds and `voice_ok` per this document;
   `verified_formats = [2025]` for a format-2025 capture.

The scratch tools used for Montreal (replay into a temp dir; per-lap minima and steering; field minima from Lap
Data + Car Telemetry) are simple to rebuild from `analysis.distance.to_distance_domain`, `analysis.track` and
`adapters.f1.packets`; a committed `scripts/` helper would make the next reviews faster (not done: outside this
review's files).

## Sources

FIA documents are read-only authority checks (never shipped or embedded; research section 2, L2 item 4).

- FIA 2024 Canadian GP, Event Notes - Circuit Map, Pit Lane Drawing and Red Zones (doc 6):
  https://www.fia.com/sites/default/files/decision-document/2024%20Canadian%20Grand%20Prix%20-%20Event%20Notes%20-%20Circuit%20Map,%20Pit%20Lane%20Drawing%20and%20Red%20Zones.pdf
- FIA 2024 Chinese GP, Event Notes - Circuit Map, Pit Lane Drawing and Red Zone:
  https://FIA.com/sites/default/files/decision-document/2024%20Chinese%20Grand%20Prix%20-%20Event%20Notes%20-%20Circuit%20Map,%20Pit%20Lane%20Drawing%20and%20Red%20Zone.pdf
- FIA 2024 Bahrain GP, Event Notes - Circuit Map and Red Zone:
  https://FIA.com/sites/default/files/decision-document/2024%20Bahrain%20Grand%20Prix%20-%20Event%20Notes%20-%20Circuit%20Map%20and%20Red%20Zone.pdf
- FIA 2025 Barcelona event, Circuit Map - Barcelona 2025 (doc 1):
  https://www.fia.com/system/files/decision-document/2025_barcelona_event_-_circuit_map_-_barcelona_2025.pdf
- FIA 2025 Monaco event, Circuit Map - Monaco 2025 (doc 10):
  https://www.fia.com/system/files/decision-document/2025_monaco_event_-_circuit_map_-_monaco_2025_0.pdf
- FIA 2025 Budapest event, Circuit Map - Budapest 2025 (doc 4):
  https://www.fia.com/system/files/decision-document/2025_budapest_event_-_circuit_map_-_budapest_2025.pdf
- FIA 2024 Singapore GP, Event Notes - Circuit Map, Pit Lane Drawing and Red Zones (doc 4):
  https://www.fia.com/sites/default/files/decision-document/2024%20Singapore%20Grand%20Prix%20-%20Event%20Notes%20-%20Circuit%20Map,%20Pit%20Lane%20Drawing%20and%20Red%20Zones.pdf
- F1DB (CC BY 4.0) circuit files, facts only: https://github.com/f1db/f1db/tree/main/src/data/circuits
  (`montreal.yml`, `shanghai.yml`, `bahrain.yml`, `catalunya.yml`, `monaco.yml`, `hungaroring.yml`, `marina-bay.yml`)
- Wikipedia (CC BY-SA, facts only): https://en.wikipedia.org/wiki/Circuit_Gilles_Villeneuve ,
  https://en.wikipedia.org/wiki/Circuit_de_Monaco , https://en.wikipedia.org/wiki/Hungaroring ,
  https://en.wikipedia.org/wiki/Circuit_de_Barcelona-Catalunya , https://en.wikipedia.org/wiki/Bahrain_International_Circuit ,
  https://en.wikipedia.org/wiki/Marina_Bay_Street_Circuit
- formula1.com, "What makes the Canadian Grand Prix special":
  https://www.formula1.com/en/latest/article/what-makes-the-canadian-grand-prix-special-and-why-you-should-see-it.2UUd1w4v0JrhufeZtpxyHg
- Hungaroring, "The Hungaroring's corners have officially been named" (2026-07-24):
  https://hungaroring.hu/site/en/media/news/the-hungarorings-corners-have-officially-been-named
- Pits n' Giggles `assets/track-segments` at `72f78aa` (MIT): vendored, see
  `src/pitwall/trackdata/third_party/pits_n_giggles/PROVENANCE.md`.
