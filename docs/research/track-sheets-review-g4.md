# Track-sheet review, group 4: Jeddah (29), Miami (30), Las Vegas (31), Losail (32), Madrid (42)

Reviewed 2026-10-11 against the standard of `src/pitwall/trackdata/track_sheets/f1/17_austria.toml`. Schema, tiers and the
meaning of `verified` / `voice_ok` / `verified_formats`: `src/pitwall/analysis/track_identity.py`. Per-track warnings:
`docs/research/track-knowledge-sources.md` section 4.1.

## Summary

| Track (F1 id) | Real capture | Verified | Sheet changed | Corrections | Left unverified / unvoiced |
|---|---|---|---|---|---|
| Las Vegas (31) | `20261010-220510` (race, 3 laps, format 2025) | 8 of 8 entries = turns 1-17 | yes | layout name; "Sphere Section" classified as a nickname; directions added to the 4 single-direction turns | no name voiced ("Sphere Section" is a nickname, not an official name) |
| Jeddah (29) | none | 0 of 19 | no | none needed (numbering = FIA) | all: no game telemetry |
| Miami (30) | none | 0 of 13 | no | none needed (numbering = FIA) | all: no game telemetry; S1 length disagreement |
| Losail (32) | none | 0 of 12 | no | none needed (numbering = FIA) | all: no game telemetry |
| Madrid (42) | none (2026 Season Pack, format 2026) | 0 of 16 | no | 5A and 20A still missing (need a capture to place) | all: no format-2026 capture; T16 window edge |

`verified = true` needs a check against recorded game telemetry *and* an authoritative numbering reference
(`track_identity.py`, "Only verified turns by default"). Jeddah, Miami, Losail and Madrid have no capture in
`data/captures` (the database lists F1 25 sessions only for ids 6, 7, 11, 13, 17, 31, 39 and 40), so their windows cannot
be checked against game data and nothing there is verified. Those four sheets are left byte-identical to the importer
output: a hand edit to a sheet with no verified turn fails `test_unreviewed_sheets_match_the_importer_output` and is
undone by the next importer run. The numbering checks below are recorded here and proposed as importer review notes
(see the reply's INTEGRATION NEEDED).

## Las Vegas (31): verified

### Method

- Replayed `data/captures/20261010-220510_udp20777.pwcap` (real PS5 F1 25 v1.26 race, UDP format 2025) read-only into a
  scratch data dir (`PITWALL_DATA_DIR=<scratch> uv run pitwall replay ...`): 110,950 packets, session `58a5df5b6a14`,
  3 laps (103.640 s from the grid, 98.192 s, 96.953 s). The learned model (v3, 7 corners) has the same apexes as the
  live database's `f1:31` v3 model.
- For every lap: speed, brake, throttle and steering on a 1 m distance grid, plus heading change from world position
  (`pos_x_m`, `pos_z_m`, 20 m smoothing). Heading over a lap: -357 deg (anti-clockwise). Negative steering, negative
  heading rate and positive `g_lat` all mean left, which matches the steering-sign convention of `analysis/track.py`.
- Session packet: `trackLength` 6200 m, S2 start 1703.80 m, S3 start 3376.47 m (`f1_session@2025`). PnG: 6200 m,
  1704 / 3377 m, so the sector gate mismatch is 0.53 m.

### References

- FIA 2025 Las Vegas GP Event Notes, Circuit Map V2 (doc 2, 19 Nov 2025, map "version 2, issued 19.11.25"):
  https://www.fia.com/system/files/decision-document/2025_las_vegas_grand_prix_-_event_notes_-_circuit_map_v2_pit_lane_drawing_emergency_map_exits_quarantine_zone_and_red_zones.pdf
  Corners 1-17. S1 90 m after T5. S2 140 m after T12. Speed trap 140 m before T14. DRS detection 1 10 m after T2,
  activation 1 20 m after T4, detection 2 710 m after T12 (drawn at T13), activation 2 870 m before T14. Centreline
  6.201 km.
- FIA 2024 Las Vegas GP Event Notes, Circuit Map and Red Zones (doc 9, 21 Nov 2024): the same numbering and landmarks.
  https://www.fia.com/sites/default/files/decision-document/2024%20Las%20Vegas%20Grand%20Prix%20-%20Event%20Notes%20-%20Circuit%20Map%20and%20Red%20Zones.pdf
- F1DB `src/data/circuits/las-vegas.yml` at `766ef481c6eabe64bcbe83fe7ed33b65fdfe6860` (CC BY 4.0): 17 turns,
  ANTI_CLOCKWISE, 6.201 km.
- en.wikipedia "Las Vegas Strip Circuit" (raw text read 2026-10-11): 17 corners, counterclockwise. T1 hairpin, a slight
  left, then a fast right onto the streets. A slow 90-degree right off Koval Lane, then a long sweeping left round the
  Sphere, a left-right section and a faster left onto Sands Avenue. T10-11 are high-speed bends and T12 a slow left
  onto the Strip. T13 is a slight sweeping left, T14-16 three slow corners and T17 a fast left.
- formula1.com, "BARRETTO: Why the Las Vegas Grand Prix could be the greatest show on Earth" (10 Nov 2023): the Sphere
  sits on the inside of Turns 7, 8 and 9.

### Per turn (laps 2-3 unless stated; lap 1 started from the grid)

| Official | PnG window | Direction | Telemetry | Landmark check |
|---|---|---|---|---|
| T1 | 185-770 (T1-4) | left | braking 179-180 m, minimum 117-119 km/h at 296-333 m, heading peak 290-380 m | - |
| T2 | 185-770 | left | second left at 395-465 m, full throttle, 127 -> 166 km/h | DRS detection 1 is "10 m after T2" |
| T3 | 185-770 | right | 470-650 m with a lift, minimum 182-197 km/h at 550-600 m | - |
| T4 | 185-770 | right | 650-770 m, flat; heading +135 deg over T3-4 | DRS activation 1 "20 m after T4" |
| T5 | 1415-1655 | right | braking 1442-1447 m, minimum 105-107 km/h at 1594-1606 m, +91 deg | S1 line 90 m after T5: 1704 - 90 = 1614 m, inside |
| T6 | 1685-2310 (T6-9) | left | flat sweeping left 1710-1935 m, 200-260 km/h | - |
| T7 | 1685-2310 | left | braking 1937-1940 m, minimum 96-103 km/h at 2043-2070 m | - |
| T8 | 1685-2310 | right | 2085-2160 m, minimum 95-97 km/h at 2118-2123 m | - |
| T9 | 1685-2310 | left | braking 2200 m, minimum 86-98 km/h at 2227-2282 m | - |
| T10 | 2630-3110 (T10-11) | right | flat, +71 to +73 deg, strongest 2730-2790 m (gentle from about 2530 m) | - |
| T11 | 2630-3110 | left | flat, -52 to -61 deg, strongest 3050-3110 m | - |
| T12 | 3110-3310 | left | braking 3110 m, minimum 88-95 km/h at 3226-3268 m | S2 line 140 m after T12: 3377 - 140 = 3237 m, inside |
| T13 | 3900-4230 | left | flat, 310-330 km/h; the Strip bends left 0.04-0.09 deg/m from 3575 to 4300 m | DRS detection 2 (drawn at T13) 710 m after T12: about 3946 m, inside |
| T14 | 5030-5375 (T14-16) | left | braking 5054-5060 m, minimum 90-93 km/h at 5219-5220 m | - |
| T15 | 5030-5375 | right | 5230-5280 m, +21 deg | - |
| T16 | 5030-5375 | left | 5285-5420 m, -41 deg, accelerating 150 -> 225 km/h (tail about 45 m past the window) | - |
| T17 | 5945-6200 | left | flat, 300-315 km/h, from about 5980 m through the line and about 60 m beyond | - |

Left: 1, 2, 6, 7, 9, 11, 12, 13, 14, 16, 17. Right: 3, 4, 5, 8, 10, 15. This matches the FIA drawing and the
Wikipedia description. PnG's complexes are kept: they are correct, and splitting them is fragile. The learned T14
apex (5220 m) sits 10 m before the T14/T15 direction change. A split T1-2 | T3-4 at about 470 m would be safe (both
minima are more than 100 m from the change) and could be done later. Mixed-direction complexes carry no `direction`.

### Learned -> official (real data, `identify(model, zones=<capture zones>)`, default min tier)

Replay model v3 (3 laps): `f1:31 Las Vegas Strip Circuit (model v3, min tier sheet_verified): 7/7 labelled`. Sector
mismatch 0.53 m, format 2025, format verified.

| Learned | Apex m | Dir | Min km/h | Official | Part | Name | Match | Voice |
|---|---|---|---|---|---|---|---|---|
| T1 | 334 | left | 117 | T1-4 (T1) | 1 | - | inside | no |
| T2 | 593 | right | 182 | T1-4 (T3) | 2 | - | inside | no |
| T3 | 1607 | right | 105 | T5 | - | - | inside | no |
| T4 | 2121 | right | 95 | T6-9 (T7/T8) | 1 | Sphere Section | inside | no |
| T5 | 2282 | left | 86 | T6-9 (T9) | 2 | Sphere Section | inside | no |
| T6 | 3229 | left | 92 | T12 | - | - | inside | no |
| T7 | 5220 | left | 90 | T14-16 (T14) | - | - | inside | no |

The sheet turns with no learned corner are T10-11, T13 and T17, all flat. The coach's "T6" on the real Vegas race is
the official Turn 12, and its "T7" is Turns 14-16. Models built from lap 1, lap 2 or lap 3 alone, and from all three,
give the same 7/7 mapping, with no edge, merged or direction-conflict match. The live database's `f1:31` v3 model maps
identically.

### Observation outside this review: Vegas lap 1 is not flagged as a standing start

In F1 25 the Vegas grid slot sits at about 2.6 m of lap distance. That is below `EDGE_TOLERANCE_M`, so
`LapAssembler` (`analysis/laps.py`, the `f.lap_distance_m > EDGE_TOLERANCE_M` branch) never sets `standing_start`.
Lap 1 (103.6 s, 0 km/h for the first samples) is therefore stored clean and used in the track model and as a reference;
the replay's coaching said "lap 2: T1 ... gained 5.08 s" against lap 1. The live session `5b7ca53ce764` has the same
problem. Identity is unaffected, because the corner positions are the same. Suggested fix (owner of `analysis/laps.py`):
also flag lap 1 as a standing start when the first frame is slow (`speed_kph < 5`) with `current_lap_time_ms < 1000`,
whatever its distance.

## Jeddah (29): not verified (no capture)

- FIA 2023 Saudi Arabian GP Event Notes, Circuit Map V4 (doc 20, 17 Mar 2023; enclosure "SAUDI_CIRCUIT_23 FIA_V6"):
  https://www.fia.com/sites/default/files/decision-document/2023%20Saudi%20Arabian%20Grand%20Prix%20-%20Event%20Notes%20-%20Circuit%20Map%20V4.pdf
  Corners 1-27. S1 265 m before T13. S2 120 m before T22. Speed trap 200 m before T27. Centreline 6.174 km. No 2024 or
  2025 map was found online.
- F1DB `jeddah.yml` @766ef48: 27 turns, ANTI_CLOCKWISE, 6.174 km. Wikipedia: 27 turns, 6.174 km.
- Numbering: PnG uses 1-27, each once and in lap order, which equals the FIA count. Complexes: T1-3, T5-10 ("The
  Esses"), T16-17 and T22-23.
- Windows against the FIA landmarks, using PnG's sector values (which equalled the game's at Austria and Las Vegas):
  - T13 at 2108 + 265 = 2373 m, inside T13 (2300-2630).
  - T22 at 4174 + 120 = 4294 m, inside T22-23 (4190-4480).
  - Lap 6175 m vs 6174 m.
- Warnings for the capture-based review:
  - The T11 window (1840-1880) is only 40 m long, and the MultiViewer T11 marker lies 26 m outside it (research
    section 4).
  - "Hairpin" (T13) is a description, not a name: drop it or classify it as a nickname. "The Esses" is a nickname.
  - Jeddah is a fast street circuit: expect several flat turns with no learned minimum.

## Miami (30): not verified (no capture)

- FIA 2023 Miami GP Event Notes, Circuit Map and Red Zone (doc 2, 4 May 2023):
  https://www.fia.com/sites/default/files/decision-document/2023%20Miami%20Grand%20Prix%20-%20Event%20Notes%20-%20Circuit%20Map%20and%20Red%20Zone.pdf
  Corners 1-19. S1 110 m after T8. S2 70 m after T16. Speed trap 150 m before T17. Centreline 5.412 km.
- FIA 2026 Miami circuit map (F2 stewards doc 2, 30 Apr 2026, version 5):
  https://www.fia.com/system/files/decision-document/2026_miami_event_-_circuit_map_-_miami_2026.pdf
  The same numbering and sector landmarks. Sector lengths 1.866 / 1.730 / 1.816 km.
- F1DB `miami.yml` @766ef48: 19 turns, ANTI_CLOCKWISE, 5.412 km. Wikipedia: 19 turns.
- Numbering: PnG 1-19 equals the FIA. Complexes: T1-2, T4-8 ("The Esses") and T14-15.
- Windows against the landmarks at PnG's sector values (1817 / 3686):
  - T8 at 1817 - 110 = 1707 m, inside T4-8 (1025-1725) but 18 m from its end.
  - T16 at 3686 - 70 = 3616 m, inside T16 (3540-3640).
- Open: the FIA sector 1 is 1866 m, against PnG's 1817 m (49 m). If the game used the FIA line, T8 would sit at about
  1756 m, 31 m past the T4-8 window, which is beyond the 25 m edge margin. A capture must settle the game's S2 start;
  the research doc already lists Lovely-vs-PnG sector disagreements at Miami.
- Names: "Stadium Section" on T12 alone is not confirmed by any source read; "The Esses" is a nickname.

## Losail (32): not verified (no capture)

- FIA 2025 Qatar circuit map (stewards doc 4, 27 Nov 2025, version 2):
  https://www.fia.com/system/files/decision-document/2025_lusail_event_-_circuit_map_-_qatar_2025.pdf
  Corners 1-16. S1 80 m before T6. S2 75 m before T12. Speed trap 205 m before T1. Centreline 5.419 km.
- F1DB `lusail.yml` @766ef48: 16 turns, CLOCKWISE, 5.419 km. Wikipedia: 16 turns.
- Numbering: PnG 1-16 equals the FIA. Complexes: T4-5, T8-9 and T12-14.
- Windows against the landmarks:
  - T6 at 2109 + 80 = 2189 m, inside T6 (2080-2300).
  - T12 at 3678 + 75 = 3753 m, inside T12-14 (3650-4325).
  - Lap 5417 m vs 5419 m.
- Names: "Hairpin" (T6) is a description: drop it or classify it as a nickname.

## Madrid (42): not verified (no format-2026 capture)

- FIA 2026 Madrid circuit map (F2/F3 stewards doc 5, 10 Sep 2026, "version 2, issued 10.09.26"):
  https://www.fia.com/system/files/decision-document/2026_madrid_event_-_circuit_map_-_madrid_2026.pdf
  Corners 1-22 plus 5A and 20A. Sector lengths 1.839 / 2.049 / 1.526 km. S1 85 m before T7. S2 40 m before T16. Speed
  trap 160 m before T5. Centreline 5.414 km.
  The research doc cites the F1 map as doc 6; this F2/F3 sheet carries the same circuit data.
- F1DB `madring.yml` @766ef48: 22 turns, CLOCKWISE, 5.416 km. Wikipedia: 22 turns, and "two extra corners designated
  5A and 20A". formula1.com Madring circuit guide: 22 turns, 5.414 km; the only corner name it uses is La Monumental
  (the banked curve after a chicane, consistent with PnG's T12).
- Numbering: PnG 1-22 equals the FIA's integers. 5A and 20A are missing, as the importer note says. 5A lies inside
  PnG's T5-6 window. 20A sits between T20 and T21 on the FIA drawing, but PnG's T20 (4680-4850) and T21 (4850-5000)
  windows are adjacent. Placing "T20a" needs a capture.
- Windows against the landmarks:
  - At PnG's sectors (1805 / 3857): T7 at 1890 m, inside T7-8 (1790-2030); T16 at 3897 m, 3 m before the end of T14-16
    (3420-3900).
  - At the FIA's sector lengths (1839 / 3888): T7 at 1924 m and T16 at 3928 m, which is in T17's window.
  - The research doc's advice stands: use the game's S2/S3. Check T16 and T17 against a format-2026 capture.
- Names other than La Monumental (Hortaleza, El Búnker, La Chicane, Las Enlazadas de Valdebebas, Norte, El Parque)
  were not found in formula1.com, FIA or Wikipedia sources: they stay unclassified.

## Remaining sheets

Other reviewers changed sheets 6, 7, 11, 13, 39 and 40 during this review (all have captures). No other sheet could be
identified as unassigned with certainty. The remaining seeded sheets have no capture, so none could be verified: 0, 2,
3, 4, 5, 9, 10, 12, 14, 15, 16, 19, 20, 26, 27 and 41 (Zandvoort Reverse). None was touched.
