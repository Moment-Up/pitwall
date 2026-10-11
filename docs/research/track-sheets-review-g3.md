# Track-sheet review g3: F1 25 ids 13, 14, 15, 16, 19, 20, 26, 27

Hand review of the corner-identity track sheets (layer L2, `src/pitwall/analysis/track_identity.py`) for Suzuka (13),
Abu Dhabi (14), Texas / COTA (15), Brazil (16), Mexico (19), Baku (20), Zandvoort (26) and Imola (27). It follows the
standard of the one earlier hand-verified sheet, `17_austria.toml`: what was checked is cited in `checked_against`, the
evidence is in the notes, and disputed names stay unvoiced. Design source: `track-knowledge-sources.md` sections 2, 4
to 8. Date: 2026-10-10.

## 1. Result

| Track (id) | Verified turns | Sheet status | Corrections |
|---|---|---|---|
| Suzuka (13) | **14 of 14 entries (turns 1-18)** | hand-reviewed, `verified_formats = [2025]` | Turn 18 added (count 17 -> 18); [1, 2] split into T1 and T2; [3-6] split into T3-5 and T6; directions set; names classified; 'Casio Triangle' and 'Dunlop' (changed sponsor names) removed; '110R' and 'Reverse Bank' added |
| Abu Dhabi (14) | 0 of 13 | seeded, unchanged | none needed to numbering; 2 unconfirmed names (section 4.1) |
| Texas / COTA (15) | 0 of 12 | seeded, unchanged | 2 unconfirmed names (section 4.2) |
| Brazil (16) | 0 of 12 | seeded, unchanged | name text `‘S’ do Senna` -> `S do Senna` (section 4.3) |
| Mexico (19) | 0 of 8 | seeded, unchanged | stale name 'Foro Sol'; game length 4525 m to confirm (section 4.4) |
| Baku (20) | 0 of 11 | seeded, unchanged | **turns 17-20 missing** (count 16 -> 20) (section 4.5) |
| Zandvoort (26) | 0 of 13 | seeded, unchanged | **'Kumhobocht' is a former sponsor name**; T5/T6 'Slotemaker' disputed (section 4.6) |
| Imola (27) | 0 of 13 | seeded, unchanged | none needed (section 4.7) |

**Why only Suzuka is verified.** `track_identity.py` defines `verified = true` as "checked against recorded game
telemetry and an authoritative numbering reference", and every verified Austria turn cites a real capture. Only Suzuka
has a real capture (`data/captures/20261010-225601_udp20777.pwcap`, qualifying + race, 2026-10-10). The other seven
tracks have no pitwall capture (sessions in `data/pitwall.sqlite3` checked read-only at 23:52: Austria, Austria
Reverse, Silverstone, Silverstone Reverse, Monza, Montreal, Las Vegas, Suzuka). Their numbering, counts and windows
were checked against the FIA maps, F1DB and an ad hoc marker cross-check (all consistent, section 4), and directions
were derived from the FIA drawings, but a window has not been checked against a learned speed minimum, so they stay
`sheet_seeded`. That costs nothing until the driver races there: the first race gives a capture, and the field model
(19 other cars) gives about 50 flying laps of evidence from one race.

**Why the seven sheets were not edited.** An unverified sheet must equal the importer output
(`test_unreviewed_sheets_match_the_importer_output`) and may hold only `unclassified`, unvoiced names
(`test_seeded_sheets_never_voice_names`); the importer regenerates any sheet without a verified turn. The corrections
are therefore staged below, ready to apply together with the capture check.

## 2. Method

1. **Official numbering and count**: FIA F1 2025 event-notes circuit maps (corner numbers, sector lines "N m before
   Turn X", centreline length), F1DB `src/data/circuits` at `b457bedc` (CC BY 4.0: layout, turn count, direction),
   Wikipedia / the circuit's own site for names.
2. **Windows against game metres**: the game's S2/S3 starts plus the FIA sector-line offsets must land inside the named
   turn's window. PnG's lap length and sector starts equalled the game's Session packet on every captured track
   (Austria 4323 / 1204 / 2935, Suzuka 5809 / 2226 / 4690, Montreal 4371 / 1101 / 2500, Las Vegas 6200 / 1704 / 3377,
   Austria Reverse 1388.6 / 3119.5; lengths also Silverstone 5890 and Monza 5798), so they are used as game values
   where no capture exists.
3. **Ad hoc marker cross-check** (developer-only, never shipped or stored here, `track-knowledge-sources.md` section 2,
   L2 item 6): MultiViewer corner markers projected onto its outline and scaled to the sheet's lap length must fall in
   their windows, and the outline's heading change at each marker gives a turn direction. On the two captured tracks
   the derived directions equal the measured ones (Suzuka 18/18, Austria 10/10). Only pass/fail counts are recorded.
4. **Real data (Suzuka)**: the capture was split by `sessionUID` and decoded like the app (`F1Adapter` +
   `LapAssembler`); the learned `TrackModel` was built from the clean race laps with `build_track_model` and mapped
   with `identify(model, zones=info.track_zones)` (default min tier `sheet_verified`). Per-window speed, braking,
   steering and lateral g came from the player's laps; every AI car's flying laps (LapData + CarTelemetry, 1 m grid)
   gave field minima and 51 more single-lap models for a robustness check. Nothing was written to `data/`.

## 3. Suzuka (13): verified

**Sources.** Capture `20261010-225601` (F1 25 v1.26, PS5, UDP format 2025; race laps 3-5 clean; qualifying had one
invalid lap). FIA 2025 Japanese GP circuit map, doc 5, 03 Apr 2025:
https://www.fia.com/system/files/decision-document/2025_japanese_grand_prix_-_event_notes_-_circuit_map_pit_lane_quarantine_and_red_zone.pdf
(corners 1-18; S1 line 105 m before Turn 8; S2 line 270 m before Turn 15; centreline 5.807 km). F1DB `suzuka-2`:
5.807 km, 18 turns, clockwise. suzukacircuit.jp course guide (18 corners, 5.807 km) and F1 ticket pages (corner names
with T numbers). ja.wikipedia 鈴鹿サーキット (corner-by-corner description, 18 corners), en.wikipedia Suzuka_Circuit.

**Game-native checks.** Session packet: trackLength 5809 m, S2 2225.65 m, S3 4690.02 m; sheet 5809 / 2226 / 4690
(sector mismatch 0.35 m). FIA anchors: 2226 + 105 = 2331 m in T8's window (measured T8 minimum 2280-2303 m);
4690 + 270 = 4960 m in T15's window (measured left steering 4925-5175 m). The Lovely-vs-PnG S2 disagreement noted in
`track-knowledge-sources.md` section 4 is resolved: PnG equals the game.

**Errors found in the seed.** (1) PnG stops at Turn 17; the final right (Turn 18: FIA map, F1DB, circuit) lies inside
its "Pit Straight" 5500-5809 m. (2) 'Casio Triangle' is the chicane's historic name; the circuit now calls it 'Astemo
Chicane (T16-17)'. (3) 'Dunlop' (T7) is the traditional name, but the circuit's current ticket pages call it
'NIPPO Corner (T7)'. (4) The PnG count and the corner names were otherwise right.

**Per-turn evidence (race laps 3-5 medians; directions from steering sign and lateral g).**

| Official | Window (m) | Dir | Speed / braking | Learned (model of laps 3-5) | Name (kind, voiced) |
|---|---|---|---|---|---|
| T1 | 585-740 (split) | R | brake 585-650, min 245 km/h at 660 | T1 | - |
| T2 | 740-975 (split) | R | brake 725-805, min 155 at 846 | T2 | - |
| T3-5 | 1030-1460 (split) | L/R/L | T3 lift, no min; T4 min 183 at 1303; T5 min 177 at 1376 | T3, T4 (parts 1, 2) | S Curve (official, yes) |
| T6 | 1460-1700 (split) | R | brake 1475-1525, min 163 at 1549 | T5 | Reverse Bank (official, yes) |
| T7 | 1700-2125 | L | no braking, min 198 at 1849 | T6 | none (Dunlop vs NIPPO Corner) |
| T8 | 2190-2385 | R | brake 2225-2300, min 196 at 2280 | T7 | Degner 1 (traditional, yes) |
| T9 | 2385-2530 | R | brake 2385-2463, min 120 at 2495 | T8 | Degner 2 (traditional, yes) |
| T10 | 2720-2830 | R | flat, ~250 km/h, lateral 3.8 g | none (flat) | 110R (official, yes) |
| T11 | 2830-3000 | L | brake 2830-2937, min 60 at 2947 | T9 | Hairpin (traditional, yes) |
| T12 | 3050-3670 | R | flat, 181 -> 296 km/h | none (flat) | 200R (traditional, yes) |
| T13-14 | 3675-4100 | L | brake 3690-3800, min 135 at ~4009 | T10 | Spoon Curve (official, yes) |
| T15 | 4850-5180 | L | lift, min 283 at 5067 | T11 | 130R (official, yes) |
| T16-17 | 5300-5500 | R/L | brake 5275-5400, min 85 at 5404 and 83 at 5470 | T12, T13 (parts 1, 2) | none (Casio Triangle / Astemo Chicane) |
| T18 | 5530-5760 (new) | R | flat, lateral up to 2.5 g at 5575-5675 | none (flat) | - |

Directions: 10 right, 8 left; they agree with the FIA drawing, ja.wikipedia's descriptions and the marker-outline
cross-check. Windows: PnG's, except the three splits (at 740 m, after T1's right steering and about 100 m before T2's minimum; at 1460 m where
the steering changes from T5 to T6) and the new T18 window, which leaves a 30 m gap after the chicane so a late chicane
minimum joins T16-17 through the edge margin. The chicane stays one window: its two minima are 66 m apart, near the
60 m spacing rule, so a merged minimum can land on either side. The marker cross-check puts all 18 markers in their
reviewed windows.

**Learned -> official mapping (real race, `identify(model, zones=info.track_zones)`, default tier):**
13/13 labelled, all `inside`; no learned corner for T10, T12, T18 (flat). Before the review the same call labelled
0/13 (every turn seeded).

| Learned | Apex (m) | Dir | Official | Part | Display (long) | Voice |
|---|---|---|---|---|---|---|
| T1 | 660 | right | T1 | | Turn 1 | Turn 1 |
| T2 | 846 | right | T2 | | Turn 2 | Turn 2 |
| T3 | 1303 | right | T3-5 | 1 | Turns 3-5, part 1 (S Curve) | Turns 3 to 5, S Curve, first part |
| T4 | 1376 | left | T3-5 | 2 | Turns 3-5, part 2 (S Curve) | Turns 3 to 5, S Curve, second part |
| T5 | 1549 | right | T6 | | Turn 6 (Reverse Bank) | Turn 6, Reverse Bank |
| T6 | 1849 | left | T7 | | Turn 7 | Turn 7 |
| T7 | 2280 | right | T8 | | Turn 8 (Degner 1) | Turn 8, Degner 1 |
| T8 | 2495 | right | T9 | | Turn 9 (Degner 2) | Turn 9, Degner 2 |
| T9 | 2947 | left | T11 | | Turn 11 (Hairpin) | Turn 11, Hairpin |
| T10 | 4009 | left | T13-14 | | Turns 13-14 (Spoon Curve) | Turns 13 to 14, Spoon Curve |
| T11 | 5067 | left | T15 | | Turn 15 (130R) | Turn 15, 130R |
| T12 | 5404 | right | T16-17 | 1 | Turns 16-17, part 1 | Turns 16 to 17, first part |
| T13 | 5470 | left | T16-17 | 2 | Turns 16-17, part 2 | Turns 16 to 17, second part |

**Robustness (single-lap models).** 54 models (the player's 3 clean laps, plus the field's 51 flying laps of 19 cars:
18 AI cars and the player's car) mapped with the reviewed
sheet and the game zones. Every labelled learned corner is `inside` its window, except one `edge` match at T16-17.
15 AI single-lap minima stayed unlabelled: 14 refused by the direction veto (noisy AI steering at a single-lap apex,
e.g. a T17 minimum at 5556 m that fell in the T18 window) and 1 between windows (2600 m). None was mislabelled. How
often each turn produced a learned minimum: T2, T6, T9, T11 about every lap; T1 11/54; T7 31/54; T15 29/54; T3, T10,
T12 and T18 almost never (flat).

## 4. Staged reviews (no capture yet; apply when one exists)

Each table lists the PnG window (unchanged), the direction to expect, and the name decision. To verify: race the
track once, then (1) confirm the Session packet's trackLength and S2/S3 equal the sheet's; (2) build the learned model
from clean laps and check every learned minimum lies in its window with the expected steering sign; (3) set
`verified = true`, `checked_against` and `verified_formats = [2025]`, classify the names and set `voice_ok` as staged.
The FIA anchor is "game S2 (or S3) start + the FIA offset" and must fall in the named window. The marker check passed
for every numbered turn.

### 4.1 Abu Dhabi (14)

FIA 2025 Abu Dhabi GP circuit map, doc 4, 04 Dec 2025 (version 4):
https://www.fia.com/system/files/decision-document/2025_abu_dhabi_grand_prix_-_event_notes_-_circuit_map_pit_lane_drawing_emergency_exits_map_quarantine_zone_and_red_zones.pdf
Corners 1-16, centreline 5.281 km; S1 line 205 m before T5, S2 line 100 m before T9. F1DB `yas-marina-2` (2021-):
5.281 km, 16 turns, anticlockwise. Sheet: 5280 m, S2/S3 1211/3538. Anchors: 1211 + 205 = 1416 m in T5 (1290-1550);
3538 + 100 = 3638 m in T9 (3550-3950). Numbering 1-16 correct; marker check 16/16.

| Turns | Window | Direction | Names |
|---|---|---|---|
| T1 | 311-480 | left | - |
| T2 | 550-725 | left | - |
| T3 | 725-990 | right | - |
| T4 | 990-1110 | left (slight; measure) | - |
| T5 | 1290-1550 | left (hairpin) | - |
| T6-7 | 2525-2800 | none (left-right) | - |
| T8 | 2850-3050 | unclear kink (measure) | - |
| T9 | 3550-3950 | left | 'Marsa Corner': no reference found (en.wikipedia and the FIA map name no corners); keep unvoiced, drop unless a source appears |
| T10-11 | 4050-4300 | right | - |
| T12 | 4320-4430 | right | - |
| T13-14 | 4430-4720 | left | 'Hotel Section': informal (the track passes under the W hotel); `nickname`, never voiced |
| T15 | 4780-4985 | right | - |
| T16 | 5030-5185 | right | - |

### 4.2 Texas / COTA (15)

FIA 2025 United States GP circuit map, doc 4, 16 Oct 2025:
https://www.fia.com/system/files/decision-document/2025_united_states_grand_prix_-_event_notes_-_circuit_map_pit_lane_drawing_emergency_exits_map_quarantine_zone_map_red_zones_map.pdf
Corners 1-20, centreline 5.513 km; S1 line 55 m before T7, S2 line 65 m before T13. F1DB `austin-1`: 5.513 km,
20 turns, anticlockwise. Sheet: 5514 m, S2/S3 1661/3923. Anchors: 1716 m in T7-9 (1640-2060); 3988 m in T13-14
(3950-4170). Numbering 1-20 correct; marker check 20/20.

| Turns | Window | Direction | Names |
|---|---|---|---|
| T1 | 530-750 | left | 'Big Red' (en.wikipedia: "the first corner called Big Red"): `nickname`, voice after capture |
| T2 | 780-1060 | right | - |
| T3-6 | 1060-1640 | none (L-R-L-R) | 'The Esses': descriptive, `traditional` |
| T7-9 | 1640-2060 | none (L-R-L) | - |
| T10 | 2130-2280 | left | - |
| T11 | 2400-2660 | left (hairpin) | 'The Bobby Pin': no reference found; drop |
| T12 | 3650-3860 | left | - |
| T13-14 | 3950-4170 | right | - |
| T15 | 4235-4375 | left | - |
| T16-18 | 4430-4960 | right | - |
| T19 | 4960-5150 | left | - |
| T20 | 5260-5440 | left | 'The Andretti': no reference found; drop |

### 4.3 Brazil / Interlagos (16)

FIA 2025 São Paulo GP circuit map, doc 5, 06 Nov 2025 (version 3):
https://www.fia.com/system/files/decision-document/2025_sao_paulo_grand_prix_-_event_notes_-_circuit_map_pit_lane_drawing_emergency_exits_map_quarantine_zone_and_red_zones_map.pdf
Corners 1-15, centreline 4.309 km; S1 line 168 m before T4, S2 line 85 m before T12. F1DB `interlagos-2`: 4.309 km,
15 turns, anticlockwise. Sheet: 4294 m (the game's length is expected to differ from the real 4309 m; confirm), S2/S3
1215/3160. Anchors: 1383 m in T4-5 (1290-1700); 3245 m in T12 (3185-3335). Numbering 1-15 correct; marker check 15/15.
Names: all 12 PnG names equal en.wikipedia's numbered corner list (`traditional`, undisputed); directions from
en.wikipedia's lap description, the FIA drawing and the marker outline agree.

| Turns | Window | Direction | Name (all `traditional`, voice after capture) |
|---|---|---|---|
| T1-2 | 220-530 | none (left-right) | S do Senna (fix the text: PnG has typographic quotes `‘S’ do Senna`) |
| T3 | 530-800 | left | Curva do Sol |
| T4-5 | 1290-1700 | left | Descida do Lago |
| T6-7 | 1950-2240 | right | Ferradura |
| T8 | 2270-2415 | right | Laranjinha |
| T9 | 2415-2590 | left | Pinheirinho |
| T10 | 2660-2850 | right | Bico de Pato |
| T11 | 2870-3115 | left | Mergulho |
| T12 | 3185-3335 | left | Junção |
| T13 | 3350-3500 | left | Café |
| T14 | 3550-3825 | left | Subida dos Boxes |
| T15 | 3900-4170 | left | Arquibancadas |

### 4.4 Mexico City (19)

FIA 2025 Mexico City GP circuit map, doc 3, 23 Oct 2025 (version 2):
https://www.fia.com/system/files/decision-document/2025_mexico_city_grand_prix_-_event_notes_-_circuit_map_pit_lane_drawing_emergency_exits_map_and_quarantine_zone_area.pdf
Corners 1-17, centreline 4.304 km; S1 line 136 m before T4, S2 line 242 m before T12. F1DB `mexico-city-3`
(2015-): 4.304 km, 17 turns, clockwise. Sheet: **4525 m**, 5.1 % longer than the real circuit; probably F1 25's own
`m_trackLength` (research section 4) but unconfirmed. Anchors in the sheet's metres: 2037 + 136 = 2173 m in T4-5
(2060-2300); 3592 + 242 = 3834 m in T12 (3740-3910). Markers scaled to 4525 m: 17/17 inside. Numbering 1-17 correct.

| Turns | Window | Direction | Names |
|---|---|---|---|
| T1-3 | 1160-1512 | none (R-L-R) | Ese Moisés Solana (en/es.wikipedia: still so called): `traditional`, voice after capture |
| T4-5 | 2060-2300 | none (L-R) | 'Ese del Lago': the wikis use it for the pre-2015 layout only; hold, unvoiced |
| T6 | 2300-2470 | right (hairpin) | candidate 'Recorte Rebaque' (named 2002, pre-2015 numbering): hold |
| T7-11 | 2660-3370 | none (L-R-L-R-L) | Esses: descriptive, `traditional` |
| T12 | 3740-3910 | right | named after Adrián Fernández in 2016 (en/es.wikipedia); exact name text unknown: hold |
| T13-15 | 3910-4175 | none (stadium section) | **'Foro Sol' is stale**: the stadium is Estadio GNP Seguros since 2024 (en.wikipedia); drop |
| T16 | 4175-4275 | right | - |
| T17 | 4275-4525 | right | 'Nigel Mansell Turn' (turn 17 named after Mansell in 2015, en/es.wikipedia; traditional 'Peraltada'): `official`, voice after capture |

### 4.5 Baku (20)

FIA 2025 Azerbaijan GP circuit map, doc 5, 18 Sep 2025:
https://www.fia.com/system/files/decision-document/2025_azerbaijan_grand_prix_-_event_notes_-_circuit_map_pit_lane_quarantine_zone_and_red_zone.pdf
Corners **1-20**, centreline 6.003 km; S1 line 46 m before T5, S2 line 56 m before T16, speed trap 210 m after T20.
F1DB `baku-1`: 6.003 km, 20 turns, anticlockwise. Sheet: 5994 m, S2/S3 2034/4082. Anchors: 2080 m in T5-6
(2000-2215); 4138 m in T16 (4020-4210). Turns 1-16 correct (16/16 markers inside); **turns 17-20 are missing**: flat
kinks on the run to the line, inside PnG's straight 4210-5994 m (research estimate about 4267 / 4506 / 4661 / 4974 m).
Correction: `official_turn_count = 20` and four new windows placed from the capture's steering trace, e.g. about
110 m wide around each kink, with gaps between them (T17 right, T18 left, T19 right, T20 right, all slight).

| Turns | Window | Direction | Names |
|---|---|---|---|
| T1 | 180-400 | left | - |
| T2 | 570-715 | left | - |
| T3 | 1410-1580 | left | - |
| T4 | 1680-1810 | right | - |
| T5-6 | 2000-2215 | none (L-R) | - |
| T7 | 2450-2600 | right | - |
| T8-12 | 2700-2960 | none (castle) | 'Castle Section': common usage, no reference checked; `nickname`, hold |
| T13 | 3230-3385 | left | - |
| T14 | 3465-3650 | left | - |
| T15 | 3650-3800 | left | - |
| T16 | 4020-4210 | left | - |
| T17-T20 | new | R, L, R, R (slight) | - |

### 4.6 Zandvoort (26)

FIA 2025 Dutch GP circuit map, doc 3, 28 Aug 2025:
https://www.fia.com/system/files/decision-document/2025_dutch_grand_prix_-_event_notes_-_circuit_map_pit_lane_map_emergency_exit_map_quarantine_zone_and_red_zones_.pdf
Corners 1-14, centreline 4.259 km; S1 line 110 m before T7, S2 line 150 m before T11. F1DB `zandvoort-5` (2021-):
4.259 km, 14 turns, clockwise. Sheet: 4258 m, S2/S3 1489/2967. Anchors: 1599 m in T7 (1555-1830); 3117 m in T11-12
(2990-3270). Numbering 1-14 correct; marker check 14/14. Names from en.wikipedia (list cited to the FIA 2026 Dutch GP
media guide) and nl.wikipedia.

| Turns | Window | Direction | Names |
|---|---|---|---|
| T1 | 200-480 | right | Tarzanbocht (`traditional`, voice after capture) |
| T2 | 600-760 | right | Gerlachbocht (`traditional`) |
| T3 | 760-960 | left (banked) | Hugenholtzbocht (`traditional`) |
| T4 | 1027-1140 | right | Hunserug (`traditional`) |
| T5 | 1150-1350 | left | - |
| T6 | 1350-1555 | right | **'Slotemakerbocht' disputed**: en.wikipedia puts Slotemaker at T6 (T5 nameless), nl.wikipedia puts 'Rob Slotemakerbocht' at T5 ('Bocht 6' at T6). Hold, unvoiced |
| T7 | 1555-1830 | right | Scheivlak (`traditional`) |
| T8 | 1920-2150 | right | Mastersbocht (`traditional`; formerly Marlboro) |
| T9 | 2150-2350 | right | - (formerly Renault) |
| T10 | 2400-2650 | left | - (sponsor-named 'CM.com' per en.wikipedia; formerly Vodafone) |
| T11-12 | 2990-3270 | none (R-L) | Hans Ernstbocht (`traditional`) |
| T13 | 3380-3600 | right | **'Kumhobocht' is a former sponsor name** (en/nl.wikipedia: now nameless): drop |
| T14 | 3600-3950 | right (banked) | Arie Luyendykbocht (`traditional`; nl spelling Luyendijk) |

Dropping 'Kumhobocht' here requires dropping it from `41_zandvoort_reverse.toml` too
(`test_reverse_layouts_carry_names_only` requires the reverse names to be a subset of the forward names).

### 4.7 Imola (27)

FIA 2025 Emilia-Romagna GP circuit map, doc 5, 15 May 2025 (version 3):
https://www.fia.com/system/files/decision-document/2025_emilia_romagna_grand_prix_-_race_director_event_notes_-_circuit_map_pit_lane_emergency_exits_quarantine_zone_and_red_zones.pdf
Corners 1-19, centreline 4.909 km; S1 line 115 m before T7, S2 line 190 m before T14. F1DB `imola-3` (2020-2025):
4.909 km, 19 turns, anticlockwise. Sheet: 4910 m, S2/S3 1800/3389. Anchors: 1915 m in T7 (1800-2000); 3579 m in
T14-15 (3450-3670). Numbering 1-19 correct; marker check 19/19. All seven PnG names are long-standing
(en/it.wikipedia) and sit on the expected turns.

| Turns | Window | Direction | Names (`traditional`, voice after capture) |
|---|---|---|---|
| T1 | 200-310 | right (kink) | - |
| T2-4 | 780-1150 | none (L-R-L) | Variante Tamburello |
| T5-6 | 1420-1700 | none (L-R) | Variante Villeneuve |
| T7 | 1800-2000 | left | Tosa |
| T8 | 2280-2420 | right (kink) | - |
| T9 | 2430-2640 | left | Piratella |
| T10 | 2670-2780 | left | - |
| T11-12 | 2840-3115 | right | Acque Minerali |
| T13 | 3115-3200 | left (kink) | - |
| T14-15 | 3450-3670 | none (R-L) | Variante Alta |
| T16 | 4080-4250 | right | - |
| T17-18 | 4250-4560 | left | Rivazza |
| T19 | 4660-4910 | right (kink) | - |

## 5. Sources

- FIA 2025 decision documents (event notes, circuit maps), URLs per track above; read, never shipped.
- F1DB https://github.com/f1db/f1db `src/data/circuits` at `b457bedc`, CC BY 4.0 (facts only).
- Suzuka Circuit: https://www.suzukacircuit.jp/eng/course_s/ and https://www.suzukacircuit.jp/eng/f1/ticket/.
- Wikipedia (facts only): en Suzuka_Circuit, ja 鈴鹿サーキット, en Yas_Marina_Circuit, en Circuit_of_the_Americas,
  en Interlagos_Circuit, en/es Autódromo_Hermanos_Rodríguez, en Baku_City_Circuit, en/nl Circuit_Zandvoort,
  en Imola_Circuit, it Autodromo_Enzo_e_Dino_Ferrari (fetched 2026-10-10).
- Pits n' Giggles track segments at `72f78aa` (vendored, MIT).
- MultiViewer circuit markers: ad hoc developer cross-check only (no licence); no positions are recorded here.
