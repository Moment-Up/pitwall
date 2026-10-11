# Track-sheet review, group 1 (2026-10-10)

Hand review of the pitwall track sheets (corner identity, layer L2; schema in
`src/pitwall/analysis/track_identity.py`) for seven F1 25 layouts:

- 7 Silverstone
- 11 Monza
- 39 Silverstone Reverse
- 40 Austria Reverse
- 41 Zandvoort Reverse
- 10 Spa
- 0 Melbourne

The review follows the standard of the first verified sheet, `17_austria.toml`:
- a turn is `verified = true` only when its number, its direction and its game-metre window were checked;
- every verified turn carries `checked_against`;
- a name is voiced only when it is confirmed as current and undisputed;
- disputed names are left out, or left seeded, and the reason goes in the notes.

Design background: `docs/research/track-knowledge-sources.md`, sections 2, 4, 5, 6, 7 and 8.

## Summary

| Id | Layout | Verified / turns | Voiced | Changes to the seed | Evidence tier |
|---|---|---|---|---|---|
| 7 | Silverstone | **14 / 14** (18 official turns) | 14 | Names classified; "Farm Curve" → "Farm"; "Maggotts & Becketts" → "Maggotts and Becketts"; directions added. Windows unchanged. | recorded (real PS5 race) + FIA 2025 map |
| 11 | Monza | **7 / 7** (11 official turns) | 6 | T6 window end 2650 → 2700 m. Current official names, with the old names as second names. Directions added. | recorded + FIA 2025 map |
| 39 | Silverstone Reverse | **14 / 14** (names only) | 14 | Names aligned with the forward sheet; directions added. Windows unchanged. | recorded + position match to forward laps |
| 40 | Austria Reverse | **5 / 7** (names only) | 5 | Red Bull Mobile window end 343 → 383 m. "Rauch" and "Schlossgold" left seeded (name dispute). | recorded + position match to forward laps |
| 41 | Zandvoort Reverse | 0 / 10 | 0 | none: no capture exists | references only |
| 10 | Spa | 0 / 13 | 0 | none: no capture exists | references only |
| 0 | Melbourne | 0 / 14 | 0 | none: no capture exists | references only |

**Why 41, 10 and 0 are unchanged.**
- No capture of these layouts exists in `data/captures`. All 27 files were scanned for Session packets on 2026-10-10 at 23:45; the 13 small ones carry no session at all. The windows therefore cannot be checked against game telemetry, and no turn may be verified.
- A sheet with no verified turn must equal the importer's output byte for byte (`test_unreviewed_sheets_match_the_importer_output`).
- The findings below are recorded here. The suggested importer notes are in the final reply (INTEGRATION NEEDED).

**Runtime effect of the changes:**
- With the default `min_tier = sheet_verified`, the real learned models of 7, 11, 39 and 40 now get official labels.
- Before the review, these four sheets attached nothing (all seeded).
- Spa, Melbourne and Zandvoort Reverse still attach nothing.

## Method

### Game data

Real F1 25 PS5 races, UDP format 2025:

| Capture | Layout |
|---|---|
| `20261010-202758` + `20261010-203637` | Silverstone |
| `20261010-204720` + `20261010-205007` | Monza |
| `20261010-205449` | Silverstone Reverse |
| `20261010-193550` | Austria Reverse |
| `20261010-191501` | Austria (forward; used only for position matching) |

How the data was processed:
- Each capture was replayed headless into a scratch data directory: `PITWALL_DATA_DIR=<tmp> uv run pitwall replay <capture>`. No UDP or HTTP port was bound and nothing was written to `data/`.
- Every lap, clean and partial, was resampled to lap distance with `analysis.distance.to_distance_domain`.
- Per lap, three things were measured:
  1. Speed minima, with the same rule as `build_track_model`: prominence 8 km/h, spacing 60 m.
  2. Steering and lateral-g sign through each sheet window. Steering above 0 is right; on these captures g_lat above 0 is a left turn.
  3. Brake and throttle.

The learned models were mapped with `identify(model, zones=...)`, using the session's own `TrackZones` (format 2025).

Two sets of models were mapped:
- the replayed ones;
- the live models in `data/pitwall.sqlite3`, read with `sqlite3 -readonly`.

The live models are the same as the replayed ones for 7, 11 and 39. For 40 the live model is v2 and the replay v3.

### Reverse layouts: position matching

Reverse names are attached by **physical identity**, not by mirrored metres:
- every sample of a clean reverse lap was matched by ground position (`pos_x_m` / `pos_z_m`, nearest neighbour) to a clean forward lap of the same circuit;
- from the matched samples, each reverse window was turned into the forward lap metres it covers.

| Reverse layout | Lateral match | Forward metres |
|---|---|---|
| Silverstone Reverse vs forward lap of `203637` | median 1.2 m, p95 4.8 m | 5890 − d_rev + **259 m**: the reverse timing line is 259 m away from the forward one |
| Austria Reverse vs forward lap 2 of `191501` | median 1.3 m, p95 4.7 m | 4323 − d_rev + **0 m**: same timing line |

### References

The FIA PDFs were read by hand and are not stored. Only facts are used, and no prose is copied (licensing section 7).

| Key | Reference |
|---|---|
| `fia:2025-britain-circuit-map-v2` | https://www.fia.com/system/files/decision-document/2025_british_grand_prix_-_event_notes_-_circuit_map_v2.pdf (doc 6, 03 Jul 2025): corners 1-18; S1 110 m before T6; S2 50 m after T14; speed trap 140 m before T15; centreline 5.891 km |
| `fia:2025-monza-circuit-map` | https://www.fia.com/system/files/decision-document/2025_monza_event_-_circuit_map_-_monza_2025.pdf (doc 3, 04 Sep 2025): corners 1-11; S1 233 m before T4; S2 215 m before T8; speed trap 212 m before T1; centreline 5.793 km |
| FIA 2024 Belgian GP map | https://www.fia.com/sites/default/files/decision-document/2024%20Belgian%20Grand%20Prix%20-%20Event%20Notes%20-%20Circuit%20Map,%20Pit%20Lane%20Drawing%20and%20Red%20Zones%20V2.pdf: corners 1-19; S1 145 m before T5; S2 48 m before T15; speed trap 30 m after T4; centreline 7.004 km. No 2025 Spa map could be found. |
| FIA 2023 Australian GP map | https://www.fia.com/sites/default/files/decision-document/2023%20Australian%20Grand%20Prix%20-%20Event%20Notes%20-%20Circuit%20Map%20and%20Red%20Zone.pdf (2022+ layout): corners 1-14; S1 120 m before T6; S2 140 m before T9; speed trap 120 m before T1; centreline 5.278 km. No 2024/2025 map could be found. |
| `f1db:v2026.16.1` | `src/data/circuits/*.yml` at release tag v2026.16.1 (CC BY 4.0), facts only: Silverstone 18 turns, Monza 11, Spa 19, Albert Park 14 (layout melbourne-2), Zandvoort 14; all clockwise |
| Silverstone names | formula1.com "EXPLAINED: How every Silverstone corner got its name"; en.wikipedia Silverstone_Circuit |
| Monza names | monzanet.it "The circuit" (the circuit's own page); formula1.com Monza corner names; it.wikipedia and en.wikipedia |
| Spa names | formula1.com Spa corner names; en.wikipedia Circuit_de_Spa-Francorchamps |
| Zandvoort names | en.wikipedia Circuit_Zandvoort |
| Melbourne names | en.wikipedia Albert_Park_Circuit, which names no corners |

## 7 Silverstone: 14/14 verified

### Game skeleton

| | Game | Sheet |
|---|---|---|
| `trackLength` | 5890 m | 5890 m |
| S2 / S3 start | 1812.85 / 4293.46 m | 1813 / 4294 m (0.54 m) |

The FIA landmarks fall inside the expected windows:
- **S1 110 m before T6:** 1813 + 110 = 1923 m, inside Brooklands [1800, 2070).
- **S2 50 m after T14:** 4293 − 50 = 4243 m, inside Chapel [4100, 4290) and in the measured left at 4160-4290 m. This confirms **Chapel = T14**, the research flag.

### Numbering

Numbering 1-18 matches the FIA 2025 map, F1DB (18) and F1.com. Complexes stay as PnG has them: T10-13 Maggotts and Becketts, and T17-18 Club.

### Per turn

Laps 1-6 are the replayed laps. Laps 5 and 6 are the complete clean laps; lap 6 includes spins.

| Turn | Name | Direction | Window | Recorded minima / behaviour |
|---|---|---|---|---|
| T1 | Abbey | R | 280-500 | lift/brake, 219-260 km/h at 396-454 m |
| T2 | Farm | L | 500-690 | flat, no minimum |
| T3 | Village | R | 780-950 | 78-112 km/h at 910-950 m (on or near the window end) |
| T4 | The Loop | L | 960-1125 | clean minimum ~88-92 km/h at 1030-1057 m; spins on 4 laps |
| T5 | Aintree | L | 1140-1350 | part throttle, no minimum |
| T6 | Brooklands | L | 1800-2070 | 124-152 km/h at 1994-2069 m |
| T7 | Luffield | R | 2070-2385 | 100-108 km/h at 2143-2256 m |
| T8 | Woodcote | R | 2400-2715 | flat |
| T9 | Copse | R | 2950-3260 | 241-256 km/h at 3018-3143 m |
| T10-13 | Maggotts and Becketts | mixed | 3520-4100 | T10 L flat 3540-3640; T11 R minimum ~233 at 3740-3760; T12 L 3820-3920; T13 R minimum 162-168 at 3975-3987 |
| T14 | Chapel | L | 4100-4290 | flat; the 4123 m minimum on lap 6 is a spin |
| T15 | Stowe | R | 4880-5260 | 180-204 km/h at 4959-4974 m |
| T16 | Vale | L | 5420-5560 | 80-95 km/h at 5522-5559 m; left-to-right change at 5555-5565 m |
| T17-18 | Club | R | 5560-5840 | T17 minima 46-84 km/h at 5570-5666 m; T18 right 5705-5860 m |

Directions: 10 right, 8 left. They agree with the FIA drawing (clockwise).

### Names

All are the current official names, confirmed by F1.com (2026 article) and en.wikipedia, and all are voiced.
- PnG's "Farm Curve" becomes **"Farm"**.
- "Maggotts & Becketts" becomes **"Maggotts and Becketts"**, to avoid "&" in speech.

### Learned → official mapping

Live model v2 (laps 25 and 26). The replay's v2 is identical.
- Status: `mapped`, scale 1.0000, sector mismatch 0.54 m, format 2025 verified.
- 9 of 10 learned corners labelled.

| Learned | Apex m | Dir | v min | Official | Name | Match | Voice |
|---|---|---|---|---|---|---|---|
| T1 | 115 | - | 141 | - | - | none | Corner at 120 metres |
| T2 | 450 | right | 256 | T1 | Abbey | inside | Turn 1, Abbey |
| T3 | 989 | left | 44 | T3-4 (merged T3) | The Loop | inside | Turns 3 to 4 |
| T4 | 2143 | right | 105 | T7 | Luffield | inside | Turn 7, Luffield |
| T5 | 3113 | right | 246 | T9 | Copse | inside | Turn 9, Copse |
| T6 | 3761 | right | 233 | T10-13 (1) | Maggotts and Becketts | inside | Turns 10 to 13, Maggotts and Becketts, first part |
| T7 | 3987 | right | 164 | T10-13 (2) | Maggotts and Becketts | inside | Turns 10 to 13, Maggotts and Becketts, second part |
| T8 | 4123 | left | 124 | T14 | Chapel | inside | Turn 14, Chapel |
| T9 | 4962 | right | 194 | T15 | Stowe | inside | Turn 15, Stowe |
| T10 | 5568 | right | 80 | T16-18 (merged T16) | Club | inside | Turns 16 to 18 |

How to read the odd rows:
- **T1 (115 m)** and the low T3 and T8 minima come from spins on the 132 s lap 6, which the game still counted as clean. This is driver data, not a sheet error. The learned model is built from only 2 laps and will improve with more.
- **T3 is labelled T3-4** because the spin-polluted minimum sits in The Loop and Village merges into it. Merged labels are never voiced by name, which is the intended behaviour.

## 11 Monza: 7/7 verified

### Game skeleton

| | Game | Sheet |
|---|---|---|
| `trackLength` | 5798 m | 5798 m |
| S2 / S3 start | 1897.79 / 3726.98 m | 1898 / 3727 m (0.21 m) |

The FIA landmarks fall in the measured corners:
- **S1 233 m before T4:** 1898 + 233 = 2131 m, in the measured Roggia left at 2095-2160 m.
- **S2 215 m before T8:** 3727 + 215 = 3942 m, in the measured first Ascari left at 3900-3990 m.

### Numbering

Numbering 1-11 matches the FIA 2025 map, F1DB (11) and F1.com. Curva del Serraglio is not numbered (F1.com and the circuit both say so).

### Per turn

Lap 4 is the clean lap; laps 1-3 are standing-start or partial laps.

| Turn | Name displayed (second name) | Direction | Window | Recorded |
|---|---|---|---|---|
| T1-2 | Prima Variante (Variante del Rettifilo) | R then L | 770-1015 | T1 right 885-960, minima 54-80 at 913; T2 left 965-1010, minima 28-88 at 976-987 |
| T3 | Curva Biassono (Curva Grande) | R | 1060-1860 | flat |
| T4-5 | Variante della Roggia (Seconda Variante) | L then R | 1950-2250 | T4 left 2095-2160, T5 right 2170-2215, minima 85-108 at 2155-2185 |
| T6 | Lesmo 1 | R | **2400-2700** (was 2650) | 171-187 at 2490-2580; exit minima at 2651 and 2682 |
| T7 | Lesmo 2 | R | 2755-2970 | 144-170 at 2828-2846 |
| T8-10 | Variante Ascari | L-R-L | 3790-4240 | T8 left 3900-3990 (minima 135-161 at 3886-3918 and 154-167 at 3974-3999), T9 right 4020-4100, T10 left 4120-4220 |
| T11 | Curva Alboreto (Parabolica) | R | 5000-5540 | 127-207 at 5110-5320 |

### Correction

**T6 (Lesmo 1) window end moved from 2650 to 2700 m.**
- The right-hander runs to 2655-2665 m.
- The clean lap's exit minimum at 2651 m was only an edge match.
- Lap 2's minimum at 2682 m would have been unlabelled (more than 25 m outside the window).
- Lesmo 2 braking starts at about 2780 m.

### Names

Names follow the circuit's own page (monzanet.it), F1.com and it.wikipedia:

| Turn | Displayed and voiced | Kept as second name | Notes |
|---|---|---|---|
| T1-2 | Prima Variante | Variante del Rettifilo | F1.com: the Rettifilo name was dropped in 2000 |
| T3 | Curva Biassono (**not voiced**) | Curva Grande | The circuit, F1.com and it.wikipedia say Biassono (renamed 1972); en.wikipedia and PnG still say Curva Grande. T3 is flat-out, so learned corners practically never take this label. |
| T4-5 | Variante della Roggia | Seconda Variante | The circuit lists both; Roggia is the distinctive word |
| T6 / T7 | Lesmo 1 / Lesmo 2 | - | F1.com's form; PnG: "Curva di Lesmo 1/2" |
| T8-10 | Variante Ascari | - | - |
| T11 | Curva Alboreto | Parabolica | All four references agree Alboreto is the current official name; "Parabolica" is not voiced |

### Learned → official mapping

Live model v1 (lap 30). The replay's v1 is identical.
- Status: `mapped`, scale 1.0000, sector mismatch 0.21 m, format 2025 verified.
- 11 of 11 learned corners labelled. T3 has no learned corner (flat).

| Learned | Apex m | Dir | v min | Official | Name | Match | Voice |
|---|---|---|---|---|---|---|---|
| T1 | 830 | - | 152 | T1-2 (1) | Prima Variante | inside | Turns 1 to 2, Prima Variante, first part |
| T2 | 913 | right | 80 | T1-2 (2) | Prima Variante | inside | Turns 1 to 2, Prima Variante, second part |
| T3 | 984 | left | 28 | T1-2 (3) | Prima Variante | inside | Turns 1 to 2, Prima Variante, third part |
| T4 | 2176 | right | 85 | T4-5 | Variante della Roggia | inside | Turns 4 to 5, Variante della Roggia |
| T5 | 2504 | right | 186 | T6 (1) | Lesmo 1 | inside | Turn 6, Lesmo 1, first part |
| T6 | 2651 | right | 187 | T6 (2) | Lesmo 1 | inside (was edge before the fix) | Turn 6, Lesmo 1, second part |
| T7 | 2829 | right | 170 | T7 | Lesmo 2 | inside | Turn 7, Lesmo 2 |
| T8 | 3904 | left | 135 | T8-10 (1) | Variante Ascari | inside | Turns 8 to 10, Variante Ascari, first part |
| T9 | 3974 | left | 154 | T8-10 (2) | Variante Ascari | inside | Turns 8 to 10, Variante Ascari, second part |
| T10 | 5110 | right | 192 | T11 (1) | Curva Alboreto | inside | Turn 11, Curva Alboreto, first part |
| T11 | 5220 | right | 173 | T11 (2) | Curva Alboreto | inside | Turn 11, Curva Alboreto, second part |

Learned T1 (830 m, no direction) is a lift for traffic in the braking zone of T1. It lies inside the T1-2 window and correctly belongs to that complex.

## 39 Silverstone Reverse: 14/14 verified (names only)

### Game skeleton

| | Game | Sheet |
|---|---|---|
| `trackLength` | 5890 m | 5890 m |
| S2 / S3 start | 1852.60 / 4338.05 m | 1853 / 4338 m (0.40 m) |

The game's reverse sectors are the mirrored forward sectors shifted by the same +259 m as the position match: 5890 − 4294 + 259 ≈ 1855, and 5890 − 1813 + 259 ≈ 4336.

### Windows and directions

The windows are PnG's, unchanged. Each window was matched by position to the forward window of the same name, and every recorded speed minimum on the 3 clean laps lies inside the window of its physical corner.

| Name | Reverse window | Forward metres it covers | Direction | Recorded |
|---|---|---|---|---|
| Club | 275-555 | 5596-5874 (T17-18) | L | 194-202 at 353-403; 95-103 at 491-511 |
| Vale | 555-695 | 5455-5595 (T16) | R | 95-97 at 611-624 |
| Stowe | 855-1235 | 4915-5294 (T15) | L | 154-189 at 1028-1061 |
| Chapel | 1825-2015 | 4135-4324 (T14) | R | flat |
| Maggotts and Becketts | 2015-2595 | 3555-4134 (T10-13) | mixed | L at 2052-2061, R at 2296-2326, L at ~2428 |
| Copse | 2855-3165 | 2985-3294 (T9) | L | 222-241 at 2976-2989 |
| Woodcote | 3400-3715 | 2435-2749 (T8) | L | flat |
| Luffield | 3730-4045 | 2105-2419 (T7) | L | 98-111 at 3903-3934 |
| Brooklands | 4045-4315 | 1835-2104 (T6) | R | 137-148 at 4124-4175 |
| Aintree | 4765-4975 | 1175-1384 (T5) | R | fast, no minimum of its own |
| The Loop | 4990-5155 | 995-1159 (T4) | R | 83-90 at 5044-5118 |
| Village | 5165-5335 | 815-984 (T3) | L | 103-112 at 5207-5236 |
| Farm | 5425-5615 | 535-724 (T2) | R | flat |
| Abbey | 5615-5835 | 315-534 (T1) | L | 259-269 at 5787-5803 (lift) |

### Names

The names are the forward sheet's, spelled the same way ("Farm", "Maggotts and Becketts"). They are voiced, because the physical identity is measured to within about 2 m.

### Learned → official mapping

Live model v3 (3 laps). The replay's v3 is identical.
- Status: `mapped`, scale 1.0000, sector mismatch 0.40 m, format 2025 verified.
- 12 of 12 learned corners labelled.

| Learned | Apex m | Dir | v min | Name | Match | Voice |
|---|---|---|---|---|---|---|
| T1 | 363 | left | 202 | Club (1) | inside | Club, first part |
| T2 | 493 | left | 99 | Club (2) | inside | Club, second part |
| T3 | 621 | right | 96 | Vale | inside | Vale |
| T4 | 1035 | left | 174 | Stowe | inside | Stowe |
| T5 | 2061 | left | 156 | Maggotts and Becketts (1) | inside | Maggotts and Becketts, first part |
| T6 | 2296 | right | 223 | Maggotts and Becketts (2) | inside | Maggotts and Becketts, second part |
| T7 | 2989 | left | 234 | Copse | inside | Copse |
| T8 | 3930 | left | 111 | Luffield | inside | Luffield |
| T9 | 4175 | right | 145 | Brooklands | inside | Brooklands |
| T10 | 5114 | right | 90 | The Loop | inside | The Loop |
| T11 | 5218 | left | 111 | Village | inside | Village |
| T12 | 5803 | left | 262 | Abbey | inside | Abbey |

No learned corner falls in Chapel, Woodcote, Aintree or Farm: all four are flat-out.

## 40 Austria Reverse: 5/7 verified (names only)

### Game skeleton

| | Game | Sheet |
|---|---|---|
| `trackLength` | 4323 m | 4323 m |
| S2 / S3 start | 1388.55 / 3119.52 m | 1388 / 3120 m (0.55 m) |

These values are also exactly the mirrored forward sectors: 4323 − 2934.93 = 1388.07 and 4323 − 1203.96 = 3119.04. This matches the 0 m position-match offset: both layouts use the same timing line.

### Windows, directions and names

| Name | Reverse window | Forward metres it covers | Direction | Recorded | Status |
|---|---|---|---|---|---|
| Red Bull Mobile | **193-383** (was 193-343) | 3980-4130 (T10) | L | 110-156 at 342-363 | verified, voiced |
| Rindt Kurve | 383-633 | 3691-3940 (T9) | L | 161-178 at 497-541 | verified, voiced |
| Würth Kurve | 1123-1383 | 2941-3200 (T7) | R | 174-181 at 1207-1312 | verified, voiced |
| "Rauch" | 1413-1743 | 2581-2910 (T6) | R | 138-159 at 1489-1612 | **seeded**: name unresolved |
| "Schlossgold" | 1983-2233 | 2091-2341 (T4) | L | 14-82 at 2078-2162 (spins, lock-ups) | **seeded**: name unresolved |
| Remus | 2823-3083 | 1241-1501 (T3) | L | 43-57 at 2922-2929 | verified, voiced |
| Niki Lauda Kurve | 3738-3963 | 361-586 (T1) | L | 76-120 at 3809-3896 | verified, voiced |

**Correction: the Red Bull Mobile window now ends at 383 m (was 343 m).**
- All 3 recorded minima sat at 342-363 m, on or past PnG's end, and the learned 353 m was only an edge match.
- The left steering runs to about 360-375 m.
- The new end meets the Rindt Kurve window.

**Disputed: forward T4 and T6.**
- The forward review (`17_austria.toml`) could not settle these sponsor names: PnG says T4 "Schlossgold" and T6 "Rauch", while the FIA 2021 map puts "Rauch" at T4.
- Their reverse windows are physically confirmed, but they stay `verified = false` with unclassified names. They are therefore unlabelled at the default tier.

**PnG's three unnamed reverse corners** (forward T8, T5 and T2) are not listed, because a reverse turn needs a name.

### Learned → official mapping

Live model v2 (laps 18 and 19).
- Status: `mapped`, scale 1.0000, sector mismatch 0.55 m, format 2025 verified.
- 6 of 9 learned corners labelled.

| Learned | Apex m | Dir | v min | Name | Match | Voice |
|---|---|---|---|---|---|---|
| T1 | 353 | left | 117 | Red Bull Mobile | inside (was edge) | Red Bull Mobile |
| T2 | 504 | left | 166 | Rindt Kurve | inside | Rindt Kurve |
| T3 | 1229 | right | 180 | Würth Kurve | inside | Würth Kurve |
| T4 | 1598 | right | 148 | - | below_min_tier ("Rauch") | Corner at 1600 metres |
| T5 | 2078 | left | 98 | - | below_min_tier ("Schlossgold") | Corner at 2080 metres |
| T6 | 2162 | right | 69 | - | below_min_tier ("Schlossgold") | Corner at 2160 metres |
| T7 | 2929 | left | 44 | Remus (1) | inside | Remus, first part |
| T8 | 2992 | - | 138 | Remus (2) | inside | Remus, second part |
| T9 | 3861 | left | 113 | Niki Lauda Kurve | inside | Niki Lauda Kurve |

The replay's v3 (3 laps) gives the same result, except that two learned corners (1489 and 1612 m) fall in the "Rauch" window.

## 41 Zandvoort Reverse: not verified (no capture)

**Windows.**
- PnG's reverse windows are exact mirrors of its forward windows (reverse = 4258 − forward, offset 0).
- PnG's reverse sector values (1293 / 2770) are its mirrored forward sectors (4258 − 2967 = 1291; 4258 − 1489 = 2769).
- That fits a shared timing line, as at Austria (offset 0). Silverstone shows that a reverse layout can also move the timing line (+259 m). Without a capture, neither the offset nor the windows can be checked.

**Names, from en.wikipedia (2020+ layout; forward turn numbers):**

| Name | Status |
|---|---|
| Tarzan (T1), Gerlach (T2), Hugenholtz (T3), Hunserug (T4), Slotemaker (T6), Scheivlak (T7) | current |
| Masters (T8) | current; formerly Marlboro |
| Hans Ernst (T11-12) | current; formerly Audi S |
| Arie Luyendyk (T14) | current; formerly Bos Uit. Dutch spelling "Luyendijk" also used. |
| T13 | **disputed** |

**T13 is the dispute.** PnG's "Kumhobocht" is outdated or disputed: en.wikipedia lists T13 as a "Nameless corner (formerly Kumho corner)", and the Red Bull track guide calls it "Bend 13". It must not be verified or voiced as "Kumhobocht".

**Next step:** capture a Zandvoort Reverse session (a few clean laps), then repeat the position match against a forward Zandvoort capture.

## 10 Spa: not verified (no capture)

**Numbering.**
- 1-19 matches the FIA 2024 map and F1DB (19).
- PnG's sector values agree with the FIA lines:
  - S1 145 m before T5: 2324 + 145 = 2469 m, inside Les Combes [2290, 2575).
  - S2 48 m before T15: 5065 + 48 = 5113 m, inside PnG's T15 window [5090, 5310).
- These are PnG's values, not yet the game's.

**Names disagree with F1.com:**

| Turn | F1.com | PnG |
|---|---|---|
| T9 | Jacky Ickx Curve (formerly "No Name"). en.wikipedia instead says "turn 11 has been called the Jacky Ickx corner" since 2018, so the number is **disputed**. | "Jacky Ickx/No Name" |
| T8 | Bruxelles (also called Rivage) | "Bruxelles/Rivage" (alias form) |
| T12-13 | Fagnes | "Fagnes Chicane" |
| T14 | Campus (formerly Stavelot) | Campus |
| T15 | Curve Paul Frère | **"Stavelot"** |
| T16-17 | Blanchimont | T16 **"Paul Frère Curve"**, T17 Blanchimont |

PnG's T15 and T16 names do not match F1.com and must not be verified as they stand.

**Next step:** capture Spa, check the windows and directions, then settle the T14-T17 names.

## 0 Melbourne: not verified (no capture)

**Numbering.**
- 1-14 matches the FIA 2023 map (2022+ layout, corners 1-14, centreline 5.278 km) and F1DB layout melbourne-2 (14 turns, 5.278 km).
- PnG's sector values agree with the FIA lines:
  - S1 120 m before T6: 1757 + 120 = 1877 m, inside the T6 window [1750, 1947).
  - S2 140 m before T9: 3179 + 140 = 3319 m, inside the T9 window [3175, 3365).

**Windows.** The T7 [1948, 2030) and T8 [2030, 2100) windows are short: 82 m and 70 m. The research's MultiViewer cross-check put the T8 marker 88 m past its window. They need a capture.

**Names.** PnG's Brabham T1, Jones T2, Whiteford T5, Ascari T11, Stewart T12 and Prost T13 have no authoritative source: en.wikipedia names no corners, and the official AGP guide numbers turns only. They must stay unverified and unvoiced.

## Open items

1. **Captures needed** for Spa, Melbourne and Zandvoort Reverse, and ideally for forward Zandvoort, so the reverse can be position-matched.
2. **Format 2026.** Every verified sheet here has `verified_formats = [2025]`, so 2026 Season Pack sessions stay at the seeded tier until a format-2026 capture of each layout is checked.
3. **Silverstone T10-13 could be split into single turns.** The recorded internal structure is in the sheet notes: T10 L, T11 R ~3750 m, T12 L, T13 R ~3980 m. Splitting would give learned corners exact numbers (T11, T13) instead of "T10-13 part n". It should wait until more laps confirm the boundaries.
4. **Austria forward T4 and T6 sponsor names** are still unresolved. This also blocks the two reverse windows.
