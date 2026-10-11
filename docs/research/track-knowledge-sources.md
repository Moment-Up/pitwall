# Track knowledge priors: knowing a circuit before the driver's first clean lap

Research date: 2026-10-10. Revision 2: this revision merges gap-fill round 1 into the first synthesis. It is a research document only; it changes no code.

**Question.** Today pitwall learns a track model only after the driver completes clean laps (`src/pitwall/analysis/track.py`). The model is a 5 m centreline plus corners `T1..Tn` found at speed minima. This document asks what licensable ways exist to know a circuit **up front**, covering:

- geometry;
- sectors;
- official corner numbers and names;
- braking zones;
- reference speeds;
- DRS / active-aero zones, pit lane and speed traps.

With that knowledge, the coach can give predictive braking cues from lap 1, the dashboard can show a correct map with sectors and named corners, and the AI engineer can use official corner names.

**Relationship to earlier work.** `docs/research/track-reference-sources.md` already covers FastF1, OpenF1, F1DB, MultiViewer, f1livedata.com, F1_Visualizer, gt7-track-visualizer and gt-telemetry. It also covers the landmark-warp / Procrustes mapping pipeline (§6.3) and the `TrackReference` data-model sketch (§6.7). This document cross-references those sections instead of repeating them.

**Method.**
- **Research.** Six research angles: open geodata, engineering datasets, game-native telemetry, braking publications, sim-racing projects, and commercial/community products. An adversarial verifier re-checked every angle's licences and claims against the actual LICENSE files and terms pages. **Where researcher and verifier disagree, this document follows the verifier.**
- **Probe and gap-fill.** A hands-on feasibility probe ran pitwall's own quasi-steady-state (QSS) solver on real-world geometry. Gap-fill round 1 then:
  - re-audited Pits n' Giggles (PnG) against its upstream fixes;
  - re-ran the physics prior on the *shippable* PnG geometry and against **pitwall's own recorded F1 25 captures** (Austria and Austria Reverse races, format 2025, PS5);
  - audited where F1DB's circuit SVGs came from;
  - worked out an ACC field model.
- **My spot checks during synthesis.**
  - The PnG `release-v5.0.0` head (`72f78aaf…`, 2026-10-10T13:21:55Z) and the blob SHAs of the changed segment files.
  - Crew Chief's licence year on each branch: `main` says "2019-2024", `master` says "2019-2022". Its `main` head is `cbd0f488` (2026-10-10), where `trackLandmarksData.json` is 1,038,538 B.
  - The current state of `src/pitwall`.
- **Handling of downloads.** All downloads stayed in the session scratchpad. No third-party code was executed. Nothing here is legal advice.
- **Process note.** One researcher's Wikipedia API request carried the user's e-mail address in its User-Agent header. Later requests used a generic User-Agent. No other personal data was sent.

**Labels used below.** Evidence tiers follow CLAUDE.md:
- **recorded** = pitwall's own real captures;
- **third-party capture** = someone else's real capture, read for facts only;
- **synthetic** = generated test data;
- **verified** = a verifier read the licence or terms text, or the data itself;
- **(unverified)** = not checked.

### What changed since revision 1

| Revision 1 statement | Correction |
|---|---|
| "pitwall has no recorded real captures yet" | **Outdated.** `data/captures/20261010-191501_udp20777.pwcap` (Austria race) and `-193550` (Austria Reverse race) are real PS5 F1 25 v1.26 captures in format 2025. An excerpt is committed as `tests/fixtures/recorded/f1_25_2025_ps5_austria_race-excerpt.pwcap`, but `tests/fixtures/recorded/README.md` still says "No captures are committed yet". `20261010-171304` (trackId −1, 3964 m) is almost certainly pitwall's own synthetic stream replayed over UDP: `sim/f1_stream.py` emits trackId −1 and the sectors sit at exact thirds. Confirm via its session UID. |
| L0b facts (AI analog brake 0.01–0.61, `m_surfaceType = 1` on kerbs, "9–10 of 22 cars moving", "AI braked ~80 m before a zone end") | These all came from **one** unlicensed third-party Bahrain 2026 clip (8.8 s). **Recorded tier now confirms the core facts in format 2025:** 20 of 22 slots live (19 AI + player), analog brake with 2.5k–2.9k partial-pressure samples per AI car, and lap distance populated for every car. The surface-type and zone-end observations remain third-party-only. A second weak public datum is PnG PR #343: 49 laps at Melbourne in format 2026, which the PR describes as "F1 26"; the data is not published. |
| "PnG's generator averages all on-track cars per lap-distance bin" (no citation); outline "point *i* ≈ lap distance *i·L/N*"; uneven 3.4–12.5 m spacing | **Cited and corrected.** At commit `13c30d7`, `apps/dev_tools/pcap_to_svg.py`, `lib/track_map_generator.py` and `apps/dev_tools/regenerate_svgs.py` average the world X/Z of all on-track, non-pit cars (lap ≥ 2) in **800 equal lap-distance bins**. So knot *i* ↔ (*i* + 0.5)·`m_trackLength`/800, verified to a median of 1.1 m against real `m_lapDistance` (§6.1 B). Spacing is uneven **by design**, because the driven line is shorter than lap distance in slow corners. Arc length must never be used as lap distance. |
| OSM coverage: "21 of 30 close within ±0.6 %", "verified extraction of 15 relations", "±0.3 % for 18 circuits"; no relation IDs | **Split by who measured what (§2 L1b, §4).** The researcher's batch run claims 21 rings closed within ±0.6 %. The verifier demoted Imola to "needs recipe", which leaves 20. The verifier independently re-fetched 15 relations and confirmed 10 closed rings (all within ±0.6 %). The "±0.3 % for 18" figure was the researcher's alone and is not separately tied to evidence. Relation IDs are now in §4. Way versions are **not** pinned in this document: snapshot date 2026-10-10, to be pinned by the Phase 5 build script. |
| §4 Montreal "PnG-seg 1–13 (kink omitted)" | **Wrong.** At the vendored pin `3490db9`, Turn 5 appears twice, T11 is absent, and the Wall of Champions is numbered 12–13 instead of 13–14. Fixed upstream by PR #343 / #345 (`release-v5.0.0`). |
| §4 Mexico "⚠ PnG length 4525 m vs 4304 official" (presented as a PnG error) | **Reframed.** 4525 m is probably the game's `m_trackLength`. Lovely Track Data also has 4525, and PnG's game-frame outline is 4455 m = 0.984×4525, a normal ratio for a driven line. F1 25's Mexico therefore appears to be about 5 % longer than the real circuit. **Monaco** is the real PnG error: `track_length` 3067 is truncated. Neither value has been checked against a capture. |
| Probe validated against "2019 Brembo figures via Motorionline" | That is a third-party republication, which §9 says not to rely on. §5 now compares against Brembo **originals**: the 2025 pages and the archived 2021 Brake Circuit Identity Cards. The 2019 values are shown only where no original was found, and are labelled as secondary. |
| Open question 11 ("is F1 26 a separate title?") | **Answered** by `docs/research/f1-udp-spec.md` §7: there is no standalone F1 26. "F1 26" is EA's name for the F1 25 2026 Season Pack, which uses UDP format 2026 and `m_formula` 13. |
| "Crew Chief names at 16 F1 25 venues" (no count evidence); licence year | Count from the verifier's parse of the 1,038,538 B file: named landmarks at 12 current venues plus Red Bull Ring (disputed; see §2 L2) plus 3 legacy venues. The licence reads "Copyright (c) 2019-2024 Britton IT Ltd" on `main` and "2019-2022" on `master` (I re-checked both). Pin `main`. |
| "Copse ≈ 270–300 km/h" | Driver accounts only. It stays **unverified**; it is not used as a validation number. |
| Legacy ids "not loadable (confirm)" | `f1-udp-spec.md` §8.3: ids 1, 8, 18, 21–25 and 28 are absent from both the F1 25 and 2026 EA documents. Treat them as not loadable in F1 25. |

---

## 1. Executive summary

**1. The game is the best source for the parts it scores, and pitwall now uses it.**
- **What it sends.** The F1 25 Session packet (2 Hz, from session start) carries:
  - `m_trackLength`;
  - sector 2/3 start metres;
  - up to 21 marshal-zone starts;
  - the pit speed limit;
  - in format 2026 (the 2026 Season Pack, marketed as "F1 26"), up to 4 DRS zones and 8 full plus 8 partial active-aero zones.
- **What pitwall does with it.** `adapters/f1/adapter.py` now decodes this into `model.TrackZones`. `analysis/track_skeleton.py` turns it into a lap-distance skeleton, and `web/src/lib/SectorBands.svelte` draws it.
- **Evidence (recorded tier).** On pitwall's own Austria and Austria Reverse captures, `m_trackLength` = 4323 m and S2/S3 = 1204.0/2934.9 m (forward) and 1388.6/3119.5 m (reverse).

**2. The other cars on track teach pitwall the circuit in the first minutes of any session that has AI cars.**
- **What is available.** Motion, LapData and CarTelemetry are sent for every car and are not affected by "Your Telemetry = Restricted" (spec text verified).
- **Recorded-tier evidence (Austria, Austria Reverse):**
  - 20 of 22 slots were live;
  - every AI car reports analog brake and full-lap distance;
  - the AI field's median speed minima (10 m bins) all fall inside the matching named PnG corner segments;
  - 100 % of AI laps braked at all 10 heavy stops.
- **Status.** Not implemented. The adapter still decodes only the player's car.

**3. A shippable corner-identity seed exists in the game's own lap metres, and pitwall already vendors it: Pits n' Giggles `assets/track-segments` (MIT).**
- **What pitwall has.** The 28 files are pinned at `3490db9` in `src/pitwall/trackdata/third_party/pits_n_giggles/` and seeded into 28 TOML track sheets. `analysis/track_identity.py` maps them onto learned models; Austria is hand-verified.
- **Provenance.** The tables are **hand-authored**: the maintainer wrote on PR #343 that "the whole track segments thing is a completely manual activity". Their lengths and sectors are the game's own values (proven at Austria, Austria Reverse and Bahrain to ≤ 1 m).
- **Action 1: re-pin to `72f78aaf`** (the `release-v5.0.0` head; there is no v5 tag yet). Exactly 5 of 28 files changed, all improvements: Melbourne (renumbered to the 2022+ 1–14), Montreal (duplicate T5 and T13–14 fixed), Baku, Las Vegas and Singapore (missing corners added).
- **Action 2: hand-fix three tracks** that the upstream validator cannot catch:
  - **Monaco:** T17–T19 are mislabelled, and `track_length` 3067 is truncated (the lap is probably about 3323 m; unverified);
  - **Baku:** T17–T20 are missing (flat kinks);
  - **Suzuka:** T18 is folded into the pit straight.
- **Outlines.** The sibling `track-maps/f1_2025` outlines (27 of 28; no Madrid) are an all-car mean line in game world X/Z. Their lap-distance mapping is verified to about 1 m.
- **Open legal point.** It is still unassessed whether EA has a claim over tables recorded from its game (§7.6).

**4. A physics prior identifies heavy stops reliably but places them too late. It may name a heavy stop; it must not place one.**
- **Identification works.** On the shippable PnG lines, a σ-ensemble gate produced **0 false voiced zones** on 5 tracks against Brembo's 2021 per-turn cards and caught 21 of 26 heavy stops (§5.2).
- **Placement does not, with the default model.** On real F1 25 data its onsets are **late**: median +11 to +17 m against this driver and +34 to +43 m against the AI (§5.3). Late cues would implicitly coach later braking, which CLAUDE.md forbids.
- **Policy.** Before the driver's own laps exist, the coach may voice only a **non-positional** "heavy stop next, Turn 1" tag at least 2 s ahead.
- **A possible fix.** A brake envelope calibrated from AI full-brake samples (about 4.0 g at 300 km/h, against the default model's 5.5 g) brought this driver's onset error to a median of 0 to +4.5 m with p90 23 m. That is only n = 5 stops per track on 2 tracks, so it is promising but not yet a basis for positional cues.

**5. Corner names come from a hand-curated, pitwall-owned track sheet per layout, keyed by official turn number.**
- **Seeds:** PnG and Crew Chief (both MIT).
- **Fact cross-checks:** OSM (ODbL), Wikipedia (CC BY-SA, facts only) and Wikidata (CC0).
- **Human-only authority:** FIA circuit maps and the formula1.com corner-name explainers. Read them; never ship them.
- **F1DB:** used only for facts (layout length, official turn count). F1DB's circuit **SVG assets are Motorsport Magazine artwork copied path-for-path** under a repo-wide CC BY label, so they are rejected (§9).

**6. OpenStreetMap (ODbL) is the only clean source of real-world geometry. With the game frame available, it is a secondary need.**
- **Coverage.** 20 of 30 base circuits close directly (10 of them re-confirmed by the verifier), 8 need layout recipes, and 2 are incomplete.
- **Why it is secondary.** It is needed for pit-lane geometry and track width before driving, Madrid's outline, and secondary games. It must ship as a **separate ODbL file**.
- **Other geometry sets.** Every other "MIT/LGPL" F1 geometry set examined is OSM-derived or of unclear origin.

**7. No licensable real-world braking dataset exists.** Brembo's figures are for validation only, unless Brembo gives written permission.

**8. Secondary games.**
- **ACC (PC only):** the Kunos broadcast API supports the same field model. ACC Race Control (MIT) ships field-median speed maps and sector lines for 24 of 25 ACC tracks.
- **GT7:** MIT and MIT-0 identity and geometry tables exist.
- **iRacing:** stays on legal hold (ToU §§4.1, 6.1(d)(e)(f), 6.2, 6.3, 6.5).

**The learned model (L3) stays authoritative for positions and braking targets.** Priors provide identity, sectors, maps and heads-ups.

**What pitwall can know on day one (F1 25; 28 current track ids = 24 real circuits + Madrid + 3 reverse layouts).**

| Knowledge | Track ids | Source / layer | When available | Status in pitwall |
|---|---|---|---|---|
| Lap length, S2/S3 start (m), marshal zones, pit speed limit, assists | 28 / 28 | game Session packet (L0a) | first Session packet | **implemented**; recorded-verified at Austria and Austria Reverse |
| DRS zones; full and partial active-aero zones | 28 / 28, format 2026 only | L0a | first Session packet | decoded; synthetic-validated only |
| Official turn numbers in game metres | 25 forward layouts. With the v5 re-pin: 22 complete and matching F1DB; Baku, Suzuka and Monaco need hand fixes. Reverse layouts: names only. | PnG → track sheet (L2) | before the session (shipped) | sheets seeded at the old pin; Austria verified; identity not yet wired into facts or voice |
| Corner names | 17 layouts with ≥ 6 named corners, 3 with 3–5, 8 with ≤ 2 (Shanghai has none). **Voice-ready: Austria only.** | track sheet (L2) | before the session | curation pending for 27 layouts |
| Map outline in the game world frame | 27 / 28 (no Madrid) | PnG outline (L1a), or field-learned (L0b) | shipped (subject to §7.6), or after about one lap of AI driving | not implemented |
| AI reference: line, speed profile, brake onsets, pit lane | 28 / 28 in any session with AI (Time Trial excluded unless ghosts stream) | field model (L0b) | first minutes of practice, qualifying or race | not implemented; recorded evidence at Austria |
| "Heavy stop next" severity tags | 27 (wherever a game-frame line exists), plus field-learned | physics prior (L1c), σ-ensemble gated | before the first lap | not implemented; positional cues **not** allowed |
| Real-world centreline, pit lane, start node, width (edge polygons at 6 circuits) | 20 closed + 8 recipe of 30 base circuits | OSM track pack (L1b) | shipped; registered after the first partial lap | not implemented |

---

## 2. Recommended layered architecture for track-knowledge priors

```
L3  Learned from the driver's own clean laps (existing)        -> authoritative positions and braking targets
L2  Identity: official numbers, names, landmarks (curated)     -> labels only, never positions
L1  Geometry and physics priors (shipped / computed)           -> map, provisional corners, severity tags
L0  Game-native runtime data (session skeleton + field)        -> exact sectors and zones; AI reference
L4  Optional user-side sources (FastF1, AC files, ...)         -> only on the user's machine, never shipped
```

**Precedence rules.**
- **Positions** (apex, entry, brake onset), highest first:
  1. L3, the driver's own laps;
  2. L0b, the AI field (support ≥ 3 car-laps);
  3. L1c, physics: severity only, no position in speech;
  4. L1a/L1b, positions mapped by fraction.
- **Sectors and zones:** always L0a, because the game is the scorer. Shipped sector values (PnG, ACC Race Control) are cross-checks only.
- **Identity:** always L2. It attaches to whichever model is current by segment membership (track-reference-sources.md §6.3 step 5; implemented in `analysis/track_identity.py`).
- **Supersession:** a higher layer supersedes a lower one but never edits it. Every prior records the `TrackModel.version` it was mapped against.

### Layer 0: game-native runtime data (exact, free, nothing shipped)

#### L0a: session skeleton (implemented)

**Sources.** The Session packet (ID 1) in formats 2025 and 2026, as described in pitwall's `docs/research/f1-udp-spec.md` and in EA's specification (https://forums.ea.com/blog/f1-games-game-info-hub-en/ea-sports%E2%84%A2-f1%C2%AE25-2026-season-pack-udp-specification/12187347). Fields:

| Field | Type / notes |
|---|---|
| `m_trackLength` | u16, metres |
| `m_sector2LapDistanceStart`, `m_sector3LapDistanceStart` | f32, metres |
| `MarshalZone[21]` | lap-fraction starts plus flag. Unsorted, and can wrap: Bahrain's zone 0 starts at 0.9539; Austria's zone at 0.9908 covers the line. |
| `m_pitSpeedLimit` | |
| Assists | including the braking-assist and dynamic-racing-line settings |
| Format 2026 only | `DRSZone[4]` and full/partial `ActiveAeroZone[8]`, as lap fractions of `m_trackLength` |

**Licence.** EA gives no explicit permission grant:
- The spec carries a "provided under license from EA for reference purposes only" disclaimer and an F1/FIA trademark notice.
- Its Overview describes the output as meant for "external applications", which is the strongest support for reading runtime consumption as intended.
- The EA User Agreement (https://www.ea.com/legal/user-agreement, last updated 14 May 2026) §2 and §7.C bind the player.
- **Rule:** consume at runtime only. Nothing needs to be shipped, because the packet repeats every 0.5 s.

**Accuracy.** The values are exact by definition for the game's own scoring.
- Recorded tier: at Austria, `m_trackLength` is 4323 m against 4318 m for the real circuit.
- Third-party clip: Bahrain is 5408 m in both F1 2021 and F1 25, against 5412 m real. Bahrain's marshal-zone starts agree within 0.0042 lap (about 23 m) across those game years.
- The fraction denominator is confirmed: (lapDistance + activation distance) / 5408 reproduces the Session aero-zone starts to 4 decimal places.
- **Unverified:** whether S2/S3 are the official FIA sector lines. Austria is consistent: the FIA puts the S1 line 170 m before T3 and the S2 line 60 m before T7, and both land inside the matching PnG windows (`17_austria.toml`). Madrid is not: PnG's game-value sectors sit 31–34 m before the FIA 2026 lines (§4).

**Alignment.** None needed.

**Confidence.** `tier=game_native`, confidence 1.0.

**What it feeds.**
- **Dashboard:** sector-coloured lap axis and map; DRS/aero zone bands (format 2026).
- **Coach:** sector context for deltas. Zone ends are coarse search windows for braking-zone detection, never cue points.
- **Engineer:** sector and zone facts, the pit speed limit, and whether the driver uses the braking-assist or dynamic-racing-line setting (a driver who follows the braking line needs different cues).

#### L0b: F1 field model (learn the track from the other cars in the same session)

**Sources** (all-car arrays):

| Packet | Fields used |
|---|---|
| Motion (ID 0) | world X/Y/Z |
| LapData (ID 2) | `m_lapDistance`, `m_pitStatus`, `m_pitLaneTimerActive`, `m_sector`, `m_driverStatus`, `m_resultStatus`, `m_speedTrapFastestSpeed`, `m_currentLapInvalid` |
| CarTelemetry (ID 6) | speed, throttle, analog brake, gear, drs, `m_surfaceType[4]` |
| CarStatus (ID 7) | `m_drsAllowed`, `m_drsActivationDistance` |
| CarTelemetry2 (ID 16, format 2026) | `m_activeAeroActivationDistance`, `m_overtakeActivationDistance` |

**Licence.** Same as L0a. The "Restricted" setting hides only some CarStatus, CarDamage and Tyre Sets fields of **human** players (verified from the spec PDF). Online human opponents also stream, so using their data is a product privacy and consent question.

**Evidence.**
- **Recorded tier: pitwall's own Austria and Austria Reverse races.** Format 2025, about 38 complete AI car-laps plus 2 human laps per race.
  - 20 of 22 slots live (19 AI cars, player at index 19).
  - Analog brake with 2.5k–2.9k partial-pressure samples per AI car.
  - Lap distance runs 0..4323 for every car.
  - Median AI-field speed minima (10 m bins, pit excluded) all fall inside the PnG segment with the matching name: Niki Lauda T1 at 475 m, 117 km/h; Remus T3 at 1415 m, 59 km/h; Schlossgold T4 at 2235 m, 97 km/h; Rauch T6, Würth T7, Rindt T9 and Red Bull Mobile T10. The same holds on the reverse layout.
  - The interquartile range of AI brake onset per corner is 2–26 m.
- **Third-party only (Bahrain 2026 P1 clip, 8.8 s):**
  - kerb contact as `m_surfaceType = 1`;
  - one AI car began braking about 80 m before a zone end;
  - 9–10 of 22 cars were moving, with the rest in the garage at large negative lap distance.
- **Public but unpublished datum:** PnG PR #343 cites 49 Melbourne laps in format 2026 in which "no car" drops below 262 km/h between 2350 m and 3130 m.
- **Unverified:**
  - whether AI telemetry is populated in **every** session type (Time Trial has no AI);
  - how AI difficulty affects brake points;
  - whether format 2025's `m_drsActivationDistance` reconstructs DRS zones.

**AI vs human.** On Austria the AI braked **20–30 m earlier** than this human, so a heads-up placed at the AI onset errs early. That is the safe direction under CLAUDE.md.

**Method** (clean room; PnG's generator confirms the binning idea):
1. **Bin** each eligible car's samples into 5 m lap-distance bins. Per bin, take the median across cars and laps of: X/Z (line), Y (elevation), speed, brake onset, minimum speed and throttle pickup. Brake onset is the first bin whose median brake exceeds **0.1** after a throttle phase; see the pedal-noise note below.
2. **Filters:**
   - `resultStatus` active and `driverStatus` flying lap;
   - `pitStatus` 0;
   - no safety car and no flashback;
   - more than about 40 m to the car ahead;
   - skip race lap 1;
   - drop negative lap distance.
3. **Pit lane:** AI cars leave the garage at session start, so their out-laps trace the pit lane. Transitions of `m_pitStatus` and `m_pitLaneTimerActive` give the pit entry and exit lap distances.
4. **Speed-trap location:** lap distance at SPTP events, or at changes of `m_speedTrapFastestSpeed` (unverified).
5. **Corners:** run the existing speed-minimum detector on the medians to get a provisional `T1..Tn`, then label it through L2.

**Pedal-noise note (recorded tier).** The **player's** brake channel in the Austria capture has a noise floor:
- only 961 of 15,771 samples are exactly 0;
- 11,677 samples sit in 0 < brake < 0.0046;
- 5,734 of the 6,455 samples with throttle > 0.9 also have brake > 0.

Possible causes are the CSL pedals' resting load or the deadzone (unverified). `analysis/braking.py` uses `BRAKE_ON` = 0.10, so it is unaffected. Any new logic that tests `brake > 0` (field onsets, trail braking, overlap detection) must use a real threshold instead.

**Alignment.** None: the field shares the player's frame and lap distance.

**Confidence.** `tier=field_observed`. `support` = cars × laps per bin. Uncertainty comes from the across-car spread. Label output "AI reference", never "your target".

**What it feeds.**
- **Dashboard:** a correct map and pit lane within the first minute of practice.
- **Coach:** lap-1 heads-ups at the AI onset (which errs early).
- **Engineer:** facts such as "the AI field's minimum at Turn 1 is about 117 km/h" (Austria, recorded), always tagged as AI.

#### L0b-ACC: the same field model for Assetto Corsa Competizione (PC only)

**Source.** The Kunos broadcasting SDK protocol (version 4). The SDK ships in the game install; protocol thread: https://www.assettocorsa.net/forum/index.php?threads/lets-talk-about-broadcasting-programmers-thread.53826/

- **REALTIME_CAR_UPDATE, per car:** world X/Y (2-D), yaw, `carLocation` (Track / PitEntry / Pitlane / PitExit), integer km/h, `splinePosition` and lap counters. There is **no** brake, throttle or steering channel.
- **TRACK_DATA:** `trackName`, `trackId`, and `trackMeters` (int32).
- **Field layout check:** the field layout was confirmed by decoding a real 101-byte sample: Red Bull Ring, trackId 26, 4318 m.

**Licence.**
- There is no SDK licence file. The Kunos readme says the SDK "can be directly used in your own .Net application".
- The ACC EULA (https://store.steampowered.com/eula/805550_eula_0) covers the SDK as part of the "Software Product" (§4.2). It grants a personal licence (§5A), forbids derivative works (§5C.4) and forbids extraction (§6C). It says nothing about UDP or broadcasting.
- **Rule:** consume at runtime only, and implement the wire protocol clean-room in Python. Never copy the Kunos C# files. The MIT labels on Crew Chief and on framf0rt's repo do not cover the Kunos-authored files those repos contain.
- Driver names arrive in ENTRY_LIST_CAR, so captures of other people's online sessions must never be redistributed.

**Accuracy.**
- **Sampling** is not the bottleneck. Monte Carlo at 50/100/250 ms with integer km/h gives a per-car-lap onset bias of +2–3 m (late) and an SD of 1/2/5 m. A median over 10 car-laps has an SD below 1 m.
- **Dominant error terms (estimated):** km/h-vs-spline latency and online network lag. Estimate ±10 m with an offline AI field and ±20 m online (**unvalidated**).
- **Lap metres** are `splinePosition × trackMeters`, the same for player and field. But `trackMeters` is the official length, not a measured spline length (scale error of about 1–2 %, unverified), and the offset of spline 0 from the timing line is unverified.
- **World position** works only on game version ≥ 1.10.1. The fix appears in a secondary republication of the patch notes; the primary Kunos post was not located.

**Brake onset without a brake channel.** Per car, compute decel_i = Δkm/h / 3.6 / Δt. The onset is the last pre-brake sample before two consecutive samples above 0.5 g; GT3 braking is about 1.2–1.6 g, while a lift plus drag is about 0.2–0.3 g. Use class-aware thresholds and lower them in the wet.

**Seeds and limits.**
- **Seeds:** ACC Race Control `.trackData` (MIT, 24 tracks) and Crew Chief ACC names and sectors (§3, §4.2).
- **Modes without a field:** Hotlap, Hotstint and Superpole carry only the player car.
- **Consoles:** console ACC has no interface. The user's rig is a PS5, so this needs ACC on a Windows PC.

#### L0c: Time Trial ghost (unverified)

- **What exists.** LapData carries `m_timeTrialPBCarIdx` and `m_timeTrialRivalCarIdx`. Packet 14 gives PB and rival lap and sector times at 1 Hz. The game UI offers "Rival Telemetry Mode" (Off / Brakes Only / Full).
- **Why it matters.** If the ghost slots carry Motion and CarTelemetry, a downloaded leaderboard ghost is a top-driver reference in the exact game frame for the one mode with no AI.
- **Evidence so far is negative.** In an F1 2021 Time Trial example, the ghost participant slots showed stationary positions and zero telemetry. A pitwall capture is needed (V7).

### Layer 1: geometry and physics priors

#### L1a: game-frame outline seed (Pits n' Giggles `assets/track-maps/f1_2025`, MIT)

**Source.** https://github.com/ashwin-nat/pits-n-giggles/tree/13c30d7dbfc33e413316c0fe3b5ed747e6b2cbc1/assets/track-maps/f1_2025 (pin `13c30d7`, v4.0.0, 2026-04-25; unchanged at the v5 head).
- 27 SVGs, one per current layout: all except Madrid. Each holds an 801-point polyline (800 bins plus a closing duplicate) and a start/finish line.
- `svg_transforms.json` holds a per-track affine fitted from world to SVG, with a maximum error of 0.001 px.

**What the outline is.** It is the mean world X/Z of all on-track, non-pit cars (lap ≥ 2) per lap-distance bin. That is the de-facto racing line: real cars sit a median 0.3 m from it (p95 2.0 m). It carries no width, elevation or pit lane.

**Licence.** MIT, "Copyright (c) [2024] [Ashwin Natarajan]"; LICENSE blob `8d23eef7`, identical at all pins. MIT covers only the author's own rights. The outline is recorded F1 25 output, and EA's possible claim on it is unassessed (§7.6).

**Accuracy (gap-fill inversion).**
- **Path length vs `m_trackLength`:** 0.981–0.994 on 26 tracks. Monaco is 1.061, which is physically impossible and proves its PnG `track_length` is wrong.
- **Path length vs F1DB real length:** 0.975–0.995 everywhere except Mexico (1.035).
- **Lateral noise on straights:** 0.06–0.22 m RMS. That is enough to create phantom curvature unless σ ≥ 7.5 m (§5.2).
- **Segment spacing:** 84–94 % of segments are within ±5 % of L/800. Short segments sit at the slowest corners, and the longest is the start/finish join.

**Alignment.**
- Invert the 2×2 affine (a = e = 0, b = −d = px per metre) to recover F1 25 world X/Z.
- **Lap distance:** knot *i* ↔ (*i* + 0.5)·`m_trackLength`/800 (§6.1 B). Never use arc length as lap distance.
- **Length gate:** |800·median(segment spacing) − `m_trackLength`| < 1 %. This replaces revision 1's path-length gate, which would wrongly reject Monaco.
- **Unverified:** the axis and sign convention against pitwall's `pos_x_m` / `pos_z_m`; that is a one-capture check. Also unverified: whether the 2026 Season Pack changed any geometry. Bahrain matches it (lateral p95 0.7 m); nothing else has been checked.

**Confidence.** `tier=shipped_seed`. Lateral uncertainty about 1 m against the field line; along-track about 1–4 m once gated.

**What it feeds.**
- **Dashboard:** a correct map before any driving, including in Time Trial.
- **Physics:** the curvature source for L1c, after arc-length resampling.

#### L1b: real-world geometry from an OSM-derived track pack (ODbL)

**Sources.**
- **OpenStreetMap** `highway=raceway` ways and `type=circuit` relations. Snapshot dated 2026-10-10; relation IDs are listed per track in §4.
- **Fill-ins:**
  - markthebault/open-racetrack-db (data ODbL, code MIT) layout recipes;
  - `area:highway=raceway` edge polygons, which give width at 6 circuits;
  - DEMs for elevation (L1d).

**Licence.** ODbL 1.0 (https://opendatacommons.org/licenses/odbl/1-0/); obligations are in §7.2.

**Coverage. Who measured what:**
- **Researcher batch run** (own 2-core / chaining over 30+ relations): 21 of 30 base circuits close within ±0.6 % of official length. The researcher also claims ±0.3 % for 18 of them, which is not tied to evidence.
- **Verifier.** Re-fetched 15 relations with `relation/<id>/full.json` and confirmed 10 closed rings:

  | Circuit | Ring length vs official |
  |---|---|
  | Spa | 6995 vs 7004 m |
  | Silverstone (after removing 23 duplicated ways) | 5881 vs 5891 m |
  | Suzuka | 5807 vs 5807 m |
  | Monza | 5794 vs 5793 m |
  | COTA | 5502 vs 5513 m |
  | Interlagos | 4308 vs 4309 m |
  | Zandvoort | 4253 vs 4259 m |
  | Melbourne | 5308 vs 5278 m |
  | Yas Marina | 5297 vs 5281 m |
  | Portimão | 4648 vs 4653 m |

  The verifier demoted Imola to "recipe": its 2-core is 5073 m and has branches.
- **Result: 20 closed, 8 need recipes, 2 incomplete:**
  - recipes: Austria, Jeddah, Miami, Las Vegas, Madrid, Paul Ricard, Monaco, Imola;
  - incomplete: Sochi and Hanoi (open-racetrack-db closed Hanoi at 5618.6 m from 2020 road data).

**Accuracy.**
- Independent traces agree with OSM to 0.3–3.5 m mean. That measures consistency, not ground truth.
- The literature figure for OSM road accuracy is about 6 m mean (Haklay 2010, about English roads in 2008).
- OSM gives a centreline: expect ±5–7 m lateral offset from a driven line in corners, and a racing line about 1 % shorter.
- **Frame evidence.** TUMFTM's OSM-derived racelines registered onto PnG's game-frame lines needed a reflection (det = −1) on all 4 tracks tested. Scale was 0.997–1.002 and RMS 1.2–2.9 m; Zandvoort's 16.9 m maximum comes from a layout change.

**Alignment.** Use method E (§6.1): local ENU, then similarity with reflection, then windowed ICP against the game X/Z of the first partial lap. Before positions exist, map by lap fraction, for identity only.

**Confidence.** `tier=shipped_seed`, with fit diagnostics stored on the mapping.

**What it feeds.**
- Pit-lane geometry, start node and track width before driving.
- Madrid's pre-session outline (PnG has none).
- Geometry for secondary games.
- A geometric cross-check on L1a.

#### L1c: physics-derived braking zones and speed profile (pitwall's own code)

**Method.** pitwall's forward/backward QSS solver (`src/pitwall/sim/driver.py`).
- **Basis:** Velenis & Tsiotras 2008 (https://doi.org/10.1007/s10957-008-9381-7) and Kapania, Subosits & Gerdes (https://arxiv.org/abs/1902.00606), where QSS predicted 136.4 s against a professional's 137.7 s.
- **Pipeline:**
  1. Fit a periodic spline in chord length.
  2. **Resample at 1 m of true arc length** (physics only).
  3. Take curvature from the heading derivative, Gaussian-smoothed.
  4. Solve.
  5. Map zone positions back to lap distance through the knot table.
- **Minimum-curvature lines,** where needed, are implemented from Heilmeier et al. 2019 (https://doi.org/10.1080/00423114.2019.1631455). **Never** use the LGPL TUMFTM code: `trajectory_planning_helpers` imports GPL-2.0+ `quadprog`.

**Gates (from §5.2).**
- **Smoothing σ ≥ 7.5 m** (default 10 m). Below that, straight-line noise exceeds k_flat = 0.0065 m⁻¹ (R 154 m) and creates phantom zones.
- **σ-ensemble voice gate:** a zone is voiced only if it has a speed drop ≥ 100 km/h **and** apex R < 90 m at **every** σ in {5, 10, 15, 20} m.
- **Brake envelope:** the default 14 + 0.0058·v² (5.5 g at 300 km/h) is too strong for F1 25. Fit decel = b0 + b1·v² per game from AI samples with brake ≥ 0.95, using −`gForceLongitudinal`·g. Austria gave 23.6 + 0.00228·v² (4.0 g); Austria Reverse gave 21.1 + 0.00250·v² (3.9 g).

**Accuracy.**
- **Identification:** robust. 0 gated false zones on 7 layouts; 21 of 26 Brembo heavy stops caught.
- **Placement:** see §5.3. With the default model, onsets are late by a median of 11–45 m (p90 35–67 m). With the calibrated envelope, this driver's error is a median of 0 to +4.5 m, p90 23 m (n = 5 per track, 2 tracks).
- **Minimum speeds are not usable as targets.** The Monza T1 minimum moves from 72 to 124 km/h as σ goes from 0 to 20 m.

**Confidence.** `tier=physics_predicted`. Uncertainty ±35 m (p90 at the default envelope) until V5 passes.

**What it feeds.**
- **Coach:** only the non-positional severity tag ("heavy stop next, Turn 1"), at least 2 s ahead (about 150 m or more at 300 km/h, which exceeds the measured p90 onset error).
- **Dashboard:** braking windows shaded and labelled "estimate".
- **Engineer:** facts labelled "estimate".

#### L1d: elevation and banking

- **F1 25 and GT7:** world Y beats any DEM, and F1 25 also sends pitch, roll and vertical g.
- **DEMs are optional,** for a 3D map or a banking prior before any lap:
  - AHN4/AHN5 (CC0): Zandvoort banking;
  - USGS 3DEP (public domain): COTA, Miami, Las Vegas;
  - UK EA LIDAR composite DTM (Open Government Licence; version assumed to be v3): Silverstone;
  - Copernicus GLO-30: free, with notices, but a 30 m surface model from about 2011–2015 that predates several circuits.
- **Banking dominates where present.** At 19° bank the banked/flat speed ratio is 1.43–1.59. Zandvoort's Scheivlak stays out of voice only because of its apex radius (R 105–109 m).
- **Grade matters little** for F1: about 1.2 m of braking distance per 5 % grade.

### Layer 2: identity (official numbers, names, landmarks)

**Sources, in order of use.**

1. **Pits n' Giggles `assets/track-segments` (MIT).** Seeds numbering, complex grouping, names and segment ranges, all in game metres.
   - **Current pin:** `3490db9` (v4.4.2), vendored. **Recommended re-pin:** `72f78aaf19910cea0aaa302cf69905daa6f331f4` (the `release-v5.0.0` head, 2026-10-10).
   - Exactly 5 of 28 files changed between the two:

     | File | Old blob | New blob |
     |---|---|---|
     | Baku | `bc1a26ad` | `ce094f53` |
     | Las Vegas | `671d3043` | `49ea26d4` |
     | Melbourne | `027bce5c` | `bfa2a057` |
     | Montreal | `5944a2e8` | `5489e1ae` |
     | Singapore | `3ed552e1` | `ff07b7bb` |

     The other 23 are byte-identical, including Monaco `c59f78e3`, Mexico `eb5a8290`, Suzuka `b6af5f46` and Madrid `234002e1`.
   - When the v5.0.0 tag is cut, accept it only if these blob SHAs match. Do **not** pin `beta/5.0.0-beta.1` (`d0f5a28`): it sits on a diverged line and lacks all 5 fixes.
   - Upstream PRs:
     - **#343** (https://github.com/ashwin-nat/pits-n-giggles/pull/343): Melbourne and Montreal numbering. The author cross-checked it against MultiViewer markers and 49 recorded laps.
     - **#345** (https://github.com/ashwin-nat/pits-n-giggles/pull/345): adds missing corners and a 1..N contiguity validator. Its own "checked in the sim" box is unticked.

2. **Crew Chief `trackLandmarksData.json` (MIT, Britton IT Ltd).** A name vocabulary.
   - Pin `main` at `cbd0f488` (Release 4.19.5.4, 2026-10-10). URL: https://gitlab.com/mr_belowski/CrewChiefV4/-/blob/main/CrewChiefV4/trackLandmarksData.json
   - **Content:** 737 entries, 495 with landmarks. There is no F1-game key, so distances are per sim.
   - **Named landmarks at venues F1 25 has:**
     - 12 current venues: Melbourne (2013 layout, stale), Monaco, Montreal, Silverstone, Hungaroring, Spa, Monza, Suzuka, Interlagos, Mexico, Zandvoort, Imola;
     - Red Bull Ring: disputed (the commercial-community researcher counted 6 names; the ACC gap-fill found the AC entry has `turnN` tokens only);
     - 3 legacy venues: Paul Ricard, Hockenheim, Portimão.
   - `turnN` tokens are Crew Chief sound IDs, not official numbers. Silverstone has Stowe as token turn13 (officially T15), and Spa reuses turn4 and turn6.
   - It is most valuable for secondary sims (471 iRacing entries, though iRacing is on hold; 21 AC; 8 ACC; 51 AMS2; 10 LMU), where its frame matches the game.

3. **Fact cross-checks:**
   - OSM named raceway spans (ODbL). Names lifted from OSM go in the ODbL file.
   - Wikipedia circuit articles (CC BY-SA). Use them for facts; do not bulk-extract.
   - Wikidata (CC0) IDs and its few corner items, e.g. Q2166679 Eau Rouge/Raidillon, Q177416 Tamburello, Q122205345 Alboreto Curve.

4. **Human-only authority checks.** Read these; never ship or embed them:
   - FIA circuit-map PDFs: official turn numbers, sector lines relative to turns, speed trap, DRS, 2026 Straight-Mode/Overtake points;
   - formula1.com "how every corner got its name" articles;
   - team explainers.

5. **F1DB (CC BY 4.0) release data files.** Facts only: layout id, length, official turn count, direction. **The SVG assets are not used** (§9).

6. **MultiViewer circuits API.** No licence, and the site footer says "non-commercial, fair use". At most an **ad hoc developer cross-check of marker positions** (the method PR #343 used). Never in CI, never cached in the repo, never shipped. Pitwall's own recorded field minima are the preferred check.

**Licence.** The track sheets are pitwall's own work: facts, independently selected and arranged. MIT notices travel with the seeds they come from.

**Accuracy and known errors in the seed** (number-in-segment test against MultiViewer markers scaled to the PnG `track_length`, v5):
- **All markers inside:** 17 layouts (Shanghai, Bahrain, Miami, Imola, Catalunya, Austria, Silverstone, Spa, Zandvoort, Monza, Texas, Mexico, Brazil, Las Vegas, Lusail, Abu Dhabi and Hungaroring), counting numbered turns only.
- **Within marker accuracy (±10–30 m):** Melbourne, Montreal, Singapore and Jeddah.
- **Missing numbers:** Suzuka T18 and Baku T17–T20.
- **Monaco:** 4 of 19 markers fit at 3067 m and 17 of 19 at 3323 m.
- **PnG #345's validator** enforces only contiguous 1..N. It cannot catch missing *trailing* turns, number/name mismatches, or a wrong `track_length`. Pitwall's importer needs its own checks (Phase 2).

**Alignment.** PnG ranges are already in game metres. `analysis/track_identity.py` scales windows by `model.length_m / sheet.lap_length_m`, with a 1.5 % gate and a 25 m edge margin. **Caveat:** the gate must compare the sheet against the game's `m_trackLength`, never the real circuit length. Monaco's sheet is **truncated**, not scaled, so when the length is fixed its windows must not be rescaled.

**Confidence.** Per turn: `sources`, `checked_against`, name `kind` (official, traditional, sponsor, nickname, unclassified), `verified` and `voice_ok`. Tiers are `sheet_verified` and `sheet_seeded`. Names change over time, for example the Hungaroring's 2026 driver names, Parabolica → Curva Alboreto, and sponsor names at the Red Bull Ring and Catalunya.

**What it feeds.**
- **Dashboard:** named corners on the map and traces.
- **Engineer:** official names in facts.
- **Coach:** spoken names only when `voice_ok` is set and the mapping is certain; otherwise "Turn N" or a distance.

### Layer 3: learned from the driver's laps (existing)

Layer 3 is unchanged: `build_track_model` runs after clean laps and freezes after 3. The live cues in `coach/cues.py` use only measured reference onsets from the driver's own fastest compatible lap.

When a new model version appears, re-run the identity mapping and retire the positional priors from L0b and L1 for coaching. Keep the priors for the map until the learned centreline covers the lap.

### Layer 4: optional user-side sources

- **FastF1 reference overlay** (track-reference-sources.md §6.3): fetched user-side, never vendored.
- **Assetto Corsa local track files**, read at runtime on the user's PC:
  - `data/sections.ini` names;
  - `drs_zones.ini`;
  - `ai/fast_lane.ai` speed, brake and width.

  The AC EULA bars "training ... or commercial purposes" without written permission, so this needs legal review first.
- **FIA circuit-map PDFs:** human curation only.
- **Brembo figures:** validation only.

### Representing confidence

```
Provenance
  tier:            game_native | field_observed | shipped_seed | curated | physics_predicted | learned | user_side
  source:          "f1_session@2025" | "pits_n_giggles@72f78aaf" | "osm_trackpack@<build-date>" | "qss@<model-hash>"
                   | "acc_race_control@42f87f55" | ...
  licence:         runtime | MIT | ODbL-1.0 | CC-BY-4.0 | CC0 | pitwall
  uncertainty_m:   float | None   (along-track)
  confidence:      0..1
  support:         int            (laps x cars, or number of agreeing sources)
  mapped_to_model: (game, track_id, version) | None
```

| Consumer | Rule |
|---|---|
| Coach: positional heads-up ("brake soon" timed to a point) | Allowed only from `learned` (the existing cues), or `field_observed` with support ≥ 3 car-laps. For field data, place the cue at the field onset plus its uncertainty, **earlier**. Never phrased as a target. |
| Coach: severity tag ("heavy stop next, Turn 1") | Allowed from `physics_predicted` zones that pass the σ-ensemble gate, fired at least 2 s ahead, **no position words**. |
| Coach: corner names in speech | Only `curated` names with `voice_ok` and a certain mapping. Otherwise "Turn N" or a distance. |
| Dashboard | Draw everything, styled by tier: solid = game_native/learned; dashed = seed/field; shaded = physics windows labelled "estimate". Show "© OpenStreetMap contributors" whenever an OSM-derived layer is drawn. |
| AI engineer | Facts in `ai/facts.py` carry their tier. Grounding keeps "estimate" / "AI reference" wording for any tier that is not learned. Never present a prior as the driver's measured data. |

---

## 3. Source matrix

The licences below are as verified. "Commercial" means usable inside proprietary pitwall.

| Source | Provides | Licence (verified) | Commercial | Obligations | F1 25 coverage | Verdict |
|---|---|---|---|---|---|---|
| F1 25 UDP Session packet | length, S2/S3 (m), marshal zones, pit limit, assists; format 2026 adds DRS and active-aero zones | No grant; "reference purposes" disclaimer; EA User Agreement | unclear (runtime consumption is the documented purpose) | Runtime only; never redistribute captures; no F1/FIA marks in branding | all ids the game loads | **Adopt (L0a)**; implemented |
| F1 25 UDP all-car arrays | other cars' X/Y/Z, lap distance, speed, analog brake, gear, pit status, DRS/aero activation distances | same | unclear (same) | Runtime only; privacy of online human players | all ids, in sessions with other cars; **recorded at Austria** | **Adopt (L0b)** |
| F1 25 Time Trial packet + ghost slots | rival/PB lap and sector times; ghost telemetry unknown | same | unclear | same | all ids, Time Trial only | **Test (V7)** |
| pitwall's own F1 25 captures (`data/captures/`) | ground truth for everything above | user's own recordings | n/a (internal) | do not redistribute other users' captures | Austria, Austria Reverse (format 2025) | **Validation basis**; extend (§6.2) |
| Pits n' Giggles `track-segments` | official numbers, complexes, names, straight names, S1/S2, all in game lap metres | MIT © Ashwin Natarajan (LICENSE blob `8d23eef7`) | yes, with obligations (EA question §7.6) | MIT notice; pin commit plus per-file blob SHAs; per-row provenance | 28/28 current ids | **Adopt as L2 seed**; re-pin to `72f78aaf` |
| Pits n' Giggles `track-maps/f1_2025` + `svg_transforms.json` | game-world all-car mean line (801 points) | MIT (same) | yes, with obligations; EA question | MIT notice; counsel before commercial release | 27/28 (no Madrid) | **Adopt (L1a)**, or fetch user-side if counsel prefers |
| F1DB release data (circuits) | layout id, length, official turn count, direction, lat/long | CC BY 4.0 | yes, with obligations | Attribution, licence URI, indication of changes; no DRM | all current venues plus madring and legacy (Sochi renamed `sirius` on 2026-10-02) | **Adopt** (layout gate and turn-count check); pin a release tag |
| F1DB `src/assets/circuits` SVGs | schematic outlines | repo-wide CC BY 4.0 label, but 20 of 30 tested files are Motorsport Magazine paths copied anchor-for-anchor | **no** | n/a | 160 layouts × 4 styles | **Reject** (§9) |
| OpenStreetMap raceway / circuit relations | centreline, start/finish node, pit lane, named spans, a few refs, width | ODbL 1.0 | yes, with obligations | Attribution; separate ODbL derivative DB; §4.6 offer; no DRM; do not rely on "insubstantial" | 20 closed, 8 recipe, 2 incomplete (of 30) | **Adopt (L1b)** as a separate file |
| markthebault/open-racetrack-db | closed draft traces for 30/30; recipes pinned to OSM way and version | data ODbL 1.0, code MIT | yes, with obligations | ODbL as OSM | 30/30 (draft; reviewed by an AI agent; timing missing) | **Use recipes as hints**; regenerate from our own pinned snapshot |
| chendo/OpenTrackData | turn lat/lon with numbers and names (42 circuits) | data ODbL 1.0, code MIT | yes, with obligations | ODbL | 24 current circuits | **Cross-check only** (default widths, bad lap lengths) |
| Wikidata | CC0 IDs, OSM relation crosswalk (P402), lengths, a few corner items | CC0 | yes | none | circuit items for all; corner items sparse | **Adopt** for IDs and crosswalk |
| Crew Chief `trackLandmarksData.json` | ordered corner names plus spans per sim | MIT © 2019-2024 Britton IT Ltd (on `main`) | yes, with obligations | MIT notice; exclude `tracks.zip`, `lap_lengths.json`, `iracing-track.json` (Garage 61 / iRacing sourced) and iRacing-only entries | 12 current venues (+ Red Bull Ring disputed) + 3 legacy; no F1-game key | **Adopt as name vocabulary**; secondary sims |
| MultiViewer circuits API | corner markers, marshal sectors | none; "non-commercial, fair use" | no | never ship or cache | 23/24 real venues; no Madrid, reverse or legacy | **Ad hoc developer cross-check only** |
| Wikipedia circuit articles | name ↔ turn-number facts | CC BY-SA 4.0 text | facts yes; copied text is share-alike | Don't copy prose; don't bulk-extract | varies | **Human reference** |
| FIA circuit maps / Event Notes PDFs | official numbering, sector lines relative to turns, speed trap, DRS, 2026 zones, centreline length | © FOWC drawings; FIA T&C §3.5–3.9 | no | manual reference only | 24 GPs (2025), 17 events (2026, incl. Madring), some 2021 legacy events | **Human authority** |
| Brembo Brake Circuit Identity Cards (2021, Wayback) | every braking zone per turn: entry/exit speed, distance, time, g | no licence; "please quote Brembo as source"; ToU all rights reserved | unclear | Attribute; written permission before shipping | 20 circuits (2021 cars) | **Validation only**; request permission |
| Brembo per-GP pages (2025/26) + archived 2021–24 news | toughest corner per GP; braking-event counts | Brembo ToU | unclear | same | 24 (2025) + 17 (2026; Madrid simulated) | **Validation only** |
| ACC broadcasting API (Kunos SDK protocol) | all-car 2-D position, km/h, spline, pit location; track name and length | no SDK licence; ACC EULA §§4.2, 5A, 5C, 6C | unclear | Runtime only; clean-room protocol; no Kunos code | n/a (ACC PC: 25 tracks) | **Adopt (L0b-ACC)** after counsel |
| ACC Race Control `.trackData` (LennysLounge/ACC-Race-Control @ `42f87f55`) | 200-bin field-median speed maps, sector lines, speed trap, heading map | MIT © 2021 Leonard Schüngel | yes, with obligations (Kunos question for game-derived tables) | MIT notice; convert once to JSON with a whitelist parser, **never** Java deserialisation | n/a (ACC: 24 of 25 tracks; no Red Bull Ring) | **Adopt as ACC seed** |
| ACC shared memory (via a Windows relay) | 3-D positions of all cars, player sector index | Kunos documentation; EULA | unclear | runtime only | n/a | Optional (elevation) |
| AHN4 / AHN5 (Netherlands) | 0.5 m DTM | CC0 | yes | none | Zandvoort (+ reverse) | Optional |
| USGS 3DEP | 1 m DEM | public domain | yes | credit requested | COTA, Miami, Las Vegas | Optional |
| UK EA LIDAR composite DTM | 1 m DTM | Open Government Licence (version assumed v3) | yes, with obligations | OGL attribution | Silverstone | Optional |
| Copernicus GLO-30 | 30 m DSM | Copernicus WorldDEM-30 licence | yes, with obligations | Art. 6 notices | global (pre-2015, surface model) | Fallback only |
| QSS / min-curvature papers | methods | papers | yes | implement; do not copy text or code | n/a | **Method basis (L1c)** |
| zetetos/gt-telemetry, ddm999/gt7info `course.csv`, gt7-datalogger `track-signatures.json`, bluemanos Forza ordinals | GT7 / Forza identity and geometry | MIT / MIT-0 / MIT / MIT | yes | notices; **not** gt7-datalogger `tracks.json` (Sony / Fandom-sourced) | n/a | **Adopt for secondary games** |
| AC local track files | names, DRS, AI line | Kunos EULA (private use) | unclear | runtime read only; legal review | n/a | **User-side (L4)** |
| Lovely Track Data | names, apex points, sectors, pit points | CC BY-NC-SA 4.0 (README only) | **no** | n/a | 25 F1 25 files | **Reject**; facts-only cross-check of lengths |
| TUMFTM racetrack-database | centreline, width, min-curvature line | LGPL label on OSM-derived data | unclear | LGPL and ODbL conflict | 14 current layouts, 4 stale | **Internal validation only** |
| bacinger/f1-circuits | coarse WGS84 outlines | MIT label; upstream is an anonymous Google My Maps layer | unclear | provenance gap | 29/30 | **Internal QA only** |

Rejected sources and the reasons for rejecting them are in §9.

---

## 4. Per-track coverage

### 4.1 F1 25

**Key.**

| Abbreviation | Meaning |
|---|---|
| **G** | Session packet (L0a). **G✓** = verified on pitwall's own capture. |
| **F** | Field model at runtime. **F✓** = AI-field minima checked against named segments on a recorded capture. |
| **PnG** | Pits n' Giggles segments at `72f78aaf` (v5 head) unless "pin" (`3490db9`, currently vendored) is stated. **MV n/m** = number-in-segment test against MultiViewer markers (developer-side facts). |
| **PnG-map** | Game-frame outline (L1a). |
| **OSM rNNN** | Relation ID; length researcher / verifier vs official. "Closed" = within ±0.6 %; "recipe" = needs a curated variant. Snapshot 2026-10-10; way versions not pinned. |
| **QSS** | Physics prior (L1c): severity tags only. |
| **CC** | Crew Chief names. |
| **BIC** | Brembo 2021 identity card (validation only). |
| **Brembo pg** | Brembo 2025/26 page or archived 2022–24 news (one corner; validation only). |

⚠ marks a hand fix that is required before `verified` or `voice_ok`. Name counts are named corner segments in PnG.

| Track (F1 id) | Geometry | Racing line | Corner numbers | Corner names | Braking data | Game-native sectors |
|---|---|---|---|---|---|---|
| Melbourne (0) | PnG-map; OSM r280443 closed 5308/5308 vs 5278 (+0.57 %, 2022 layout) | F; PnG-map | PnG 1–14 = F1DB 14 (MV 13/14; T8 marker 88 m past its segment). **Pin had the pre-2022 1–16 (MV 7/14): re-pin.** | PnG 6 (Brabham T1, Jones T2, Whiteford T5, Ascari T11, Stewart T12, Prost T13) **unverified** (the official AGP guide numbers turns only) → `voice_ok=false`; CC stale (2013) | F; QSS; Brembo pg (2022–24 news) | G |
| Shanghai (2) | PnG-map; OSM r2094941 closed 5456 vs 5451 | F; PnG-map | PnG 1–16 = F1DB (MV 16/16) | **none** | F; QSS; Brembo pg | G |
| Sakhir (3) | PnG-map; OSM r284538 closed 5412/5412; Outer r11987742; edge polygon r18662483 | F; PnG-map (2026 pack matches: lateral p95 0.7 m) | PnG 1–15 (MV 15/15) | sparse: PnG 1 | F; QSS; BIC 8 zones | G (third-party capture: 5408 m; S2/S3 1799.5/4001.1 = PnG 1800/4001) |
| Catalunya (4) | PnG-map; OSM r284540 no-chicane 4664 vs 4657 (r2049529 with chicane, 4680: negative test) | F; PnG-map | PnG 1–14 (MV 14/14) | PnG 8 sponsor/historic ⚠ curate | F; QSS; BIC 2021/22 (pre-2023 layout) | G |
| Monaco (5) | PnG-map (path 3253 m); OSM r148194 recipe (41 street ways, 6 m gap; street names only) | F; PnG-map | PnG 1–19 unchanged at v5 but **⚠ T17–T19 mislabelled**: PnG has "La Rascasse" = T17 and "Anthony Noghes" = T18–19; the FIA 2025 map and F1.com have T17 = unnamed left, T18 = La Rascasse, T19 = Antony Noghès | PnG 15 ⚠ fix spellings (Chicaine→Chicane, Massanet→Massenet, Anthony→Antony); "Louis Chiron" for T13–14 is an alias (F1.com: T13–16 "Swimming Pool"); CC 14 | F; QSS (with L = 3337, all 11 BIC zones fall in the right segments, 0 false); BIC 11 (T1 298→109 km/h, 103 m) | G. **⚠ PnG `track_length` 3067 is truncated** (outline 1.061× it; MV fits 4/19 at 3067 vs 17/19 at 3323). Probable `m_trackLength` ≈ 3310–3340, most likely 3323 (Lovely F1 24/25); **unverified**, needs a capture. PnG s1/s2 1059/2470 agree with FIA "S1 60 m before T5" only on a ~3323 m lap. |
| Montreal (6) | PnG-map; OSM r284595 closed 4363 vs 4361 | F; PnG-map | PnG 1–14 = F1DB 14 (MV 13/14; T12 marker 26 m before its segment). **Pin was wrong:** T5 twice, T11 absent, Wall of Champions numbered 12–13 (MV 9/14). #343 renumbered; #345 added T11 inside "The Hairpin" [10, 11] at 2550–2880 m and T12 at 3180–3250 m. | PnG 4: Virage Senna T1–2, Pont de la Concorde T8–9 (unverified), The Hairpin T10–11 (voice "Turn 10"; T11 is a flat kink), Wall of Champions T13–14; CC 3 | F; QSS; Brembo pg (2022–24) | G |
| Silverstone (7) | PnG-map; OSM r51160 closed 5881 after de-duplication vs 5891 (23 ways listed twice); 18 names; pit lane (Wing pits) | F; PnG-map | PnG 1–18 (MV 18/18); Maggotts/Becketts T10–13; Chapel = T14 confirmed positionally | PnG 14; OSM 18; CC 12–15; Wikipedia complete (folds Maggotts into Becketts) | F; QSS (Club lift; Becketts over-call at σ = 10); BIC 7 zones, none at Abbey or Copse (T3 320→125, 130 m); 2025 page T3 295→130, 115 m | G |
| Hungaroring (9) | PnG-map; OSM r284557 closed 4372 vs 4381 (no names) | F; PnG-map | PnG 1–14 (MV 14/14; sub-markers 1A and 12A outside) | PnG 12, including the 2026 official driver names ⚠ `valid_from` (F1 25 base game = 2025 names; Wikipedia: T1 Piquet, T2 Hamilton, T4 Mansell, T11 Alesi, T12 Schumacher, T13 Senna) | F; QSS; BIC 2021/22 (11 zones) | G |
| Spa (10) | PnG-map; OSM r284560 closed 7004 / 6995 vs 7004; 14 names; start node; pit lane | F; PnG-map | PnG 1–19 (MV 19/19); complexes match the F1.com explainer | PnG 13; OSM 14; CC 12–14; Wikidata Q2166679 | F; QSS (Malmedy lift and Pouhon 314→239 are false zones, never voiced); BIC 7 (T1 311→86, 120 m); 2025 page T5 327→176, 93 m | G |
| Monza (11) | PnG-map; OSM r284565 closed 5798 / 5794 vs 5793; 10 names | F; PnG-map | PnG 1–11 (MV 11/11) | PnG 7 ⚠ "Parabolica" → official Curva Alboreto alias; OSM 10; Wikidata Q122205345 | F; QSS (0 false at σ ≥ 10); BIC 2021 (T1 353→88, 135 m) and 2023; 2025 page T1 337→89, 129 m | G |
| Singapore (12) | PnG-map; OSM r421263 closed 4955 vs 4940 (2023 layout; street names) | F; PnG-map | PnG 1–19 = F1DB 19 (the pin lacked T6 and T15); MV 17/19 (T2 6 m, T15 22 m off, within marker accuracy) | PnG 6 (Sheares T1, Memorial T7, Stamford T8, Padang T9, Singapore Sling T10 ⚠, Connaught T14), curate | F; QSS; Brembo pg (2022–24) | G |
| Suzuka (13) | PnG-map; OSM r284570 closed 5808 / 5807 vs 5807 (14 names, Japanese + English) | F; PnG-map | PnG 1–17 correct (MV 17/17). **⚠ T18** (the final right, about 5629 m by MV) is folded into "Pit Straight" 5500–5809; add it as a flat marker (F1DB 18) | PnG 9 ⚠ "Casio Triangle" is the old chicane name; OSM 14; CC 6–10 | F; QSS; Brembo pg (2025: Corner 16, 303→103, 106 m) | G (Lovely S2 differs by 64 m from PnG; unresolved) |
| Abu Dhabi (14) | PnG-map; OSM r11378665 closed 5289 / 5297 vs 5281 (2021 layout); edge polygon r18145580 (≈13.3 m) | F; PnG-map | PnG 1–16 (MV 16/16) | sparse: PnG 2 | F; QSS; BIC (6 zones; check the card's layout year) | G |
| Texas / COTA (15) | PnG-map; OSM r6537729 closed 5503 / 5502 vs 5513; ways named "Turn 1"…"Turn 20" | F; PnG-map | PnG 1–20 (MV 20/20); OSM agrees | PnG 4 informal | F; QSS; BIC 9 | G |
| Brazil / Interlagos (16) | PnG-map; OSM r6781071 closed 4300 / 4308 vs 4309; 14 names (OSM spells "Pinherinho"); edge polygon r17956608 | F; PnG-map | PnG 1–15 (MV 15/15) | PnG 12 (T10–T15 match the Mercedes-AMG explainer); OSM 14; CC 7–11 | F; QSS; BIC 7 | G (Lovely differs by 45–47 m; unresolved) |
| Austria / Red Bull Ring (17) | PnG-map; OSM r5309181 recipe (MotoGP chicane and long-lap branches; 14-way chain 4309 vs 4318) | **F✓**; PnG-map (index mapping verified, §6.1 B) | PnG 1–10 (MV 10/10); **sheet hand-verified** (`17_austria.toml`) | PnG 7 sponsor-style ⚠ T4/T6 names unresolved (FIA 2021 map vs PnG) | **F✓** (AI minima inside named segments); QSS (V5, §5.3); BIC 7 | **G✓** 4323 m; S2/S3 1204.0/2934.9 = PnG 1204/2935 |
| Mexico City (19) | PnG-map (path 4455 m); OSM r16251935 closed 4308 vs 4304; edge polygon r17956306 (≈12.6 m) | F; PnG-map | PnG 1–17 = F1DB 17 (MV 17/17 at 4525) | PnG 5; Wikidata "Nigel Mansell turn"; CC 6–7 | F; QSS; BIC 10 | G. **Game length 4525 m** (probable `m_trackLength`; Lovely F1 24/25 also 4525; outline 0.984×) vs real 4304. F1 25's Mexico appears **about 5 % longer than the real circuit**, so the F1DB ±1.5 % layout gate and the 1.00 ± 0.03 registration scale gate need a per-track game-scale allowance. Unverified until captured. |
| Baku (20) | PnG-map; OSM r11266687 closed 5974 vs 6003 (street names) | F; PnG-map | PnG 1–16 of 20 (#345 added T13 and T14; T1–T16 all inside their own segments). **⚠ T17–T20 absent:** flat kinks on the Neftchilar Avenue run (MV ≈ 4267/4506/4661/4974 m, all inside PnG's straight at 4210–5994 m); add them as flat markers | sparse: PnG 1 (Castle Section T8–12); typo "Zarifa Aliyeva Steet" | F; QSS; BIC 11 | G |
| Zandvoort (26) | PnG-map; OSM r13545573 closed 4262 / 4253 vs 4259; 11 names; width on 24 ways | F; PnG-map | PnG 1–14 (MV 14/14) | PnG 12; OSM 10–11; Wikidata 6 items with coordinates | F; QSS **needs banking** (Scheivlak 324→217 is kept out of voice only by its R of 105–109 m); BIC 9 | G |
| Imola (27) | PnG-map; OSM r9291096 recipe (2-core 5073 m with branches; refs 1–21 are not official) | F; PnG-map | PnG 1–19 (MV 19/19) | PnG 7; OSM 8; CC 8; Wikidata Tamburello Q177416, Variante Bassa | F; QSS; BIC 8 | G |
| Jeddah (29) | PnG-map; OSM recipe (no circuit relation; F1 and ePrix branches; open-racetrack-db recipe) | F; PnG-map | PnG 1–27 (MV 25/27; T11 +26 m, T18 +8 m: boundary noise) | sparse: PnG 2 generic | F; QSS (fast street circuit: false-zone risk); BIC 7 (Wayback `id_` URL) | G |
| Miami (30) | PnG-map; OSM recipe (r20204222 holds only a sub-relation; open-racetrack-db 5409.8 m hypothesis) | F; PnG-map | PnG 1–19 (MV 19/19) | sparse: PnG 2 | F; QSS; Brembo pg (2024: T17 320→73, 126 m) | G (Lovely differs by 29–47 m; PnG length 5410 vs Lovely 5412) |
| Las Vegas (31) | PnG-map; OSM r16696508 recipe (2-core 6320 with branches vs 6201; open-racetrack-db 6210) | F; PnG-map | PnG 1–17 complete (the pin lacked T10, T11 and T13); MV 17/17 | sparse: PnG 1 (Sphere Section T6–9) | F; QSS; Brembo pg (T14 350→102, 143 m) | G |
| Losail (32) | PnG-map; OSM r21297662 closed 5420 vs 5419; edge polygon r18052714 | F; PnG-map | PnG 1–16 (MV 16/16) | sparse: PnG 1 | F; QSS; BIC 7 | G |
| Silverstone Reverse (39) | PnG-map; OSM r51160 reversed | F; PnG-map | **no official numbering** (PnG's 1–18 is invented; sheet keeps names only) | PnG 14 (place names still apply) | F; QSS on reversed geometry; no real-world data | G |
| Austria Reverse (40) | PnG-map; OSM recipe reversed | **F✓**; PnG-map (index mapping verified) | no official numbering | PnG 7 | **F✓**; QSS (V5, §5.3) | **G✓** 4323 m; S2/S3 1388.6/3119.5 = PnG 1388/3120 |
| Zandvoort Reverse (41) | PnG-map; OSM reversed | F; PnG-map | no official numbering | PnG 12 | F; QSS (banking reversed) | G |
| Madrid / Madring (42, 2026 pack) | **no PnG-map**; F at runtime; OSM route r18813472 (recipe; match with the Season Pack layout unverified) | F only | PnG 1–22 matches the FIA 2026 map (doc 6, 10 Sep 2026: corners 1–22 plus sub-corners 5A and 20A; centreline 5.414 km). Store 5A and 20A as letters. Not in MV (404). | PnG 7 (Hortaleza, El Búnker, La Monumental, …) | F; QSS once geometry exists; Brembo 2026 page (simulated; T1 294→137, 99 m) | G (format 2026 only). PnG s1/s2 1805/3857 sit 31–34 m before the FIA lines (1839/3888): **use the game's S2/S3.** |

**Legacy and short ids** (1 Paul Ricard, 8 Hockenheim, 18 Sochi, 21–24 short layouts, 25 Hanoi, 28 Portimão) are absent from EA's F1 25 and 2026 documents (`f1-udp-spec.md` §8.3), so treat them as not loadable. Pitwall keeps no priors for them, and the field model covers them if one ever appears. Reference notes for completeness:
- **OSM:** Hockenheim r284588 closed 4573 vs 4574; Portimão route r7509968 closed 4645 / 4648 vs 4653; Paul Ricard r10316343 5773 vs 5842 (wrong variant); Sochi and Hanoi incomplete.
- **Brembo cards:** Paul Ricard (2020), Sochi, Portimão.

### 4.2 ACC (PC only; secondary game)

**Key.**
- **F** = L0b-ACC field model.
- **ARC** = ACC Race Control seed (heavy stops counted as speed minima / drops ≥ 60 km/h).
- **CC** = Crew Chief names: "same" = ACC frame; "AC×k" = AC frame rescaled by k; "warp" = another sim's entry, needs the landmark warp.

Geometry for every row is F: a 2-D outline from world X/Y on game version ≥ 1.10.1. Elevation needs the shared-memory relay.

| Track (broadcast name / id, `trackMeters`) | Speed and braking | Names | Sectors |
|---|---|---|---|
| Monza / monza, 5793 | F; ARC (6 / 5) | CC same, 7 | ARC + CC |
| Zolder / Zolder, 4011 | F; ARC (7 / 6) | CC same, 11 | ARC + CC (Δ 19.6 m) |
| Brands Hatch / brands_hatch, 3908 | F; ARC (9 / 6) | CC same, 10 | ARC + CC |
| Spa / Spa, 7004 | F; ARC (9 / 7) | CC same, 11 | ARC + CC |
| Silverstone, 5891 | F; ARC (9 / 5) | CC warp, 12–15 | ARC + CC |
| Paul Ricard / Paul_Ricard, 5842 | F; ARC (8 / 5) | CC warp (rF2 layout unverified) | ARC + CC |
| Misano, 4226 | F; ARC (7 / 6) | CC warp, 7 | ARC + CC |
| Nürburgring GP, 5137 | F; ARC (11 / 7) | CC same (turnN only); rF2 warp, 11 | ARC + CC |
| Barcelona, 4655 | F; ARC (9 / 5) | none | ARC + CC |
| Hungaroring, 4381 | F; ARC (11 / 7) | none | ARC + CC |
| Zandvoort, 4252 | F; ARC (9 / 6) | CC warp, 4 | ARC |
| Kyalami, 4522 | F; ARC (9 / 5) | none | ARC |
| Mount Panorama, 6213 | F; ARC (8 / 7) | CC warp, 11 | ARC |
| Suzuka, 5807 | F; ARC (10 / 5) | CC warp, 6–8 | ARC |
| Laguna Seca, 3602 | F; ARC (9 / 4) | CC warp, 3 | ARC |
| Imola, 4959 | F; ARC (8 / 7) | CC AC×1.0195, 8 | ARC |
| Oulton Park, 4307 | F; ARC (8 / 7) | CC warp, 10 | ARC |
| Donington, 4020 | F; ARC (7 / 7) | CC AC×1.0295, 8 | ARC |
| Snetterton, 4779 | F; ARC (10 / 6) | CC warp, 12 | ARC |
| Watkins Glen, 5552 | F; ARC (9 / 6) | CC warp, 4 | ARC defaults only → derive at runtime |
| COTA, 5513 | F; ARC (10 / 7) | none | ARC |
| Indianapolis, 4167 | F; ARC (12 / 4) | none | ARC |
| Valencia, 4005 | F; ARC (9 / 7) | none | ARC |
| Red Bull Ring, 4318 | F only (no ARC file) | none (AC entry is turnN only) | runtime only |
| 24H Nürburgring, 25300 (25378 per Race-Element; unverified) | F; ARC 1000-bin (42 / 18) | none | ARC defaults → derive at runtime |

**Cross-validation of the two MIT sources.** ARC speed minima fall inside Crew Chief's ACC-keyed spans for 60 of 62 corners on 7 tracks. ARC sector lines are always **later** than Crew Chief's, by +3.0 to +19.6 m (median +9 m), which fits event lag at a 250 ms update interval.

---

## 5. Feasibility probe results

### 5.1 Original probe: TUMFTM geometry, default model (local validation only)

**Setup.** `pitwall.sim.driver.solve_lap` with the default `VehicleModel`:
- μ_lat 1.65 g, aero 0.0047;
- brake 14 + 0.0058·v²;
- 920 W/kg, v_max 95 m/s.

The geometry was TUMFTM racetrack-database CSVs (`e59595d`, 2020 data), used locally only (§9). They were splined at 1 m and smoothed at σ = 10 m. Braking zones were extracted with pitwall's `analysis/braking.py` thresholds.

**Reference values.**
- Primary (Brembo originals): the 2025 pages, and the archived 2021 Brake Circuit Identity Cards via Wayback.
- Secondary: 2019 figures via Motorionline (a republication), used only where no original was found.
- Pole times: FIA and Wikipedia.

**Lap times.**

| Track | Racing line (min-curvature) | Centreline | 2025 pole |
|---|---|---|---|
| Spa | 106.1 s (+5.5 %) | 117.5 s (+16.9 %) | 100.562 s |
| Monza | 82.2 s (+4.4 %) | 90.7 s (+15 %) | 78.792 s |
| Silverstone | 89.4 s (+5.3 %) | 107.0 s (+26 %) | 84.892 s |

**Heavy stops (racing line) against published figures.**

| Corner | Predicted entry→min, distance, time | Brembo original | Secondary (2019, Motorionline) | Agreement |
|---|---|---|---|---|
| Spa La Source (T1) | 301→77 km/h, 115 m, 2.75 s | 2025 page: 295→81, 2.9 s. 2021 card: 311→86, 120 m | 303→85, 116 m | distance −5 m (vs 2021); minimum −4 to −9 km/h |
| Spa Les Combes (T5) | 339→132 km/h, 102 m | 2025 page: 327→176, 93 m, 1.48 s | – | distance +9 m; **minimum −44 km/h** (medium corner too slow) |
| Spa Bus Stop | 339→80 km/h, 124 m, 2.66 s | none located | 321→91, 128 m | secondary only; entry limited by the model's speed cap |
| Monza Rettifilo (T1) | 339→82 km/h, 122 m, 2.53 s | 2025 page: 337→89, 129 m, 2.75 s. 2021 card: 353→88, 135 m | 349→87, 137 m | distance −7 m (vs 2025); minimum −6/−7 km/h |
| Monza Roggia | 335→105 km/h, 110 m, 2.09 s | none located | 334→119, 117 m, 2.09 s | secondary only; minimum −14 km/h |
| Silverstone Village (T3) | 312→93 km/h, 114 m | 2025 page: 295→130, 115 m, 2.33 s. 2021 card: 320→125, 130 m | – | distance −1 m (vs 2025); **minimum −32 to −37 km/h** |
| Monza heavy-zone count | 6 | Brembo 2025 ranking page: 6 brakings per lap | (6) | match |
| Silverstone braking | 12 zones, 15.75 s | 2025 page: 8 events, 11 s. 2021 card: 7 zones | – | over-predicted |

**Where the probe failed.**
- **Fast corners** (R ≈ 100–200 m) are hypersensitive, because v² = μgR / (1 − aero·R). Result: false zones at Raidillon (324→278), Abbey (320→221) and Copse (331→244). The Brembo 2021 Silverstone card lists no braking at Abbey or Copse.
- **Medium corners** come out too slow (Les Combes, Village).
- **Centreline geometry** keeps big-stop onsets within 1–11 m of the racing line but makes minimum speeds far too low.
- **Model limits:**
  - a 342 km/h cap;
  - no elevation, banking, ERS or active aero;
  - no friction ellipse: `VehicleModel` brakes at full `brake(v)` even at the lateral limit;
  - lifts are flagged as light braking.

### 5.2 Gap-fill: the shippable input (PnG game-frame outlines)

**Setup.**
- Same solver and default model.
- Input: the inverted PnG `f1_2025` outlines, splined in chord length, resampled at 1 m of arc length, curvature from heading, and zones mapped back to lap distance through the knot table.
- Ground truth: Brembo 2021 per-turn cards (originals) for Spa, Monza, Silverstone, Monaco and Zandvoort.
- Monaco used L = 3337 m because the PnG header value is wrong.
- A "false zone" is a predicted drop of 15 km/h or more at a turn where Brembo lists no braking.

**False zones / predicted zones, by smoothing σ.**

| Track | σ 0 | 5 | 10 | 15 | 20 | 30 | 40 m |
|---|---|---|---|---|---|---|---|
| Spa | 4/14 | 2/12 | 2/12 | 2/12 | 2/12 | 2/12 | 2/12 |
| Monza | 7/17 | 1/10 | 0/7 | 0/7 | 0/7 | 0/7 | 0/4 |
| Silverstone | 6/15 | 2/13 | 1/10 | 2/10 | 2/10 | 1/9 | 1/8 |
| Monaco | 5/21 | 1/16 | 0/14 | 0/14 | 0/12 | 0/10 | 0/9 |
| Zandvoort | 9/18 | 3/12 | 1/10 | 1/10 | 1/10 | 1/10 | 1/10 |

The remaining false zones per track:
- **Spa:** Malmedy lift; Pouhon 314→239 km/h at R 119 m. Raidillon appears only at σ = 0.
- **Silverstone:** Club 148→126 km/h and small Copse lifts. There is no Abbey zone at any σ.
- **Zandvoort:** Scheivlak 324→217 km/h at R 105–109 m.
- **Monza at σ = 40:** two of its 4 predicted zones are misses (Ascari, Parabolica), not false zones.

**Findings.**
- **Noise floor.** On straights the outlines have 0.06–0.22 m RMS lateral noise. At σ = 0 that gives |k| p99 up to 0.017 m⁻¹, above k_flat = 0.0065 m⁻¹, which creates phantom corners on the Monza main straight and at start/finish joins.
  - **σ = 7.5 m** is the smallest value that keeps every straight on all 8 outlines below k_flat; use 10 m.
  - Dropping the last knots does not fix the joins; smoothing does.
- **Voice gate.** Voice only when the drop is ≥ 100 km/h and R < 90 m **at every σ in {5, 10, 15, 20}**. Across the 5 tracks this gives:
  - 21 voiced zones, **0 false**, 0 over-calls;
  - 21 of 26 Brembo heavy stops caught;
  - misses: Monza Ascari and Parabolica, Silverstone Stowe, Monaco Grand Hotel and the Monaco pool (all with R > 90 m, or a drop just under 100 km/h).
  - A single σ = 10 would over-call Silverstone Becketts (R 90 vs 97 m).
- **Positions.**
  - **Against the TUMFTM-based run:** PnG onsets differ by −10 to +3 m (median −5 m, n = 12).
  - **Across σ 5–20:** onsets move a median 5 m (p90 17 m, max 35 m at the Nouvelle Chicane).
  - **Against Brembo 2021:** model braking distances are a median **13 m shorter** than Brembo's stopping distances (n = 23).
  - **Minimum speeds** are not usable as targets: Monza T1 moves from 72 to 124 km/h as σ goes from 0 to 20 m.
- **Index vs arc-length parameterisation.** Using index (lap distance) as arc length moves onsets by at most 7 m, but it inflates apex radius by 5–30 % and minimum speed by a median of +7 km/h. That flips the voice gate at the margin, so physics must use arc length.
- **Lap time** is not a validation metric. Monza ranges from 85.5 s at σ = 0 to 68.2 s at σ = 40.

### 5.3 Gap-fill: real F1 25 game data (recorded tier, pitwall's own captures)

**Austria and Austria Reverse races** (format 2025; 2 human laps per track, so n = 5 gated stops each):
- **Identification:** all 10 gated zones are corners where **100 %** of AI laps braked, and every corner the cars braked for was predicted.
- **Default-model placement fails V5** (V5: median ≤ 15 m, p90 ≤ 30 m). Predicted onsets are **late**:

  | Track | vs human: median / p90 | vs AI: median / p90 |
  |---|---|---|
  | Austria | +16.5 m / 34.6 m | +43 m / 58 m |
  | Austria Reverse | +11 m / 34.9 m | +34 m / 67 m |

- **Calibrated brake envelope.** Each track's fit (from AI samples with brake ≥ 0.95) was applied to the *other* track:

  | Track | vs human: median / p90 |
  |---|---|
  | Austria | 0.0 m / 22.6 m |
  | Austria Reverse | +4.5 m / 22.8 m |

  - This **passes V5 for this one driver**.
  - The AI is still +21 to +30 m late, because the AI brakes 20–30 m earlier than this human.
  - On the five Brembo tracks the calibrated envelope cuts the braking-distance bias from −13 m to −4 m and leaves false-zone counts unchanged.
- **Third-party Bahrain 2026 clip:**
  - AI car at T13: predicted onset 4017.9 m, observed 4018.5 m, but its entry speed was 249 km/h against a predicted 314 km/h;
  - human at T11: braked 46 m *earlier* than predicted.

### 5.4 Verdict

1. **Identification is feasible now.** On shippable game-frame lines (27 layouts), a σ-ensemble-gated physics prior names the heavy stops with no false voiced zones in 7 tested layouts.
2. **Placement is not yet feasible.** With the default model, predicted onsets are late, which would implicitly coach later braking. Until a per-game calibrated envelope passes V5 on recorded **Time Trial** captures at 3 or more tracks, the coach may voice only:
   - the non-positional severity tag at least 2 s ahead;
   - field-observed heads-ups;
   - the driver's own learned cues.

   The dashboard may shade L1c windows labelled "estimate".
3. **The real calibration source is the field model.** The brake envelope is two constants per game, fitted from AI full-brake samples. This makes L0b plus L1c a coherent pair: L0b supplies the calibration and lap-1 positions in sessions with AI; L1c covers Time Trial and gives severity before any car has driven.
4. **Still open:**
   - fast corners (R 100–200 m);
   - friction-ellipse coupling, banking and elevation;
   - the cause of the AI-vs-human gap (AI difficulty was not read);
   - cross-validation beyond Austria.

---

## 6. Alignment methods and validation

### 6.1 Methods

| # | Method | Applies to | Accuracy | Status |
|---|---|---|---|---|
| A | **Native lap distance**: use metres as given | L0a, L0b, PnG segments, ACC Race Control | frame exact; content = source accuracy (PnG windows 100–600 m) | **recorded**: PnG length and sectors equal the game's to ≤ 1 m at Austria and Austria Reverse; third-party: Bahrain |
| B | **PnG outline index mapping**: knot *i* ↔ (*i* + 0.5)·`m_trackLength`/800, after inverting the affine | L1a | along-track: median +1.1 m (p05–p95 +0.4 to +1.5 m, max 3.9 m, n = 3000) at Austria and Austria Reverse; +1.0 m (max 1.6 m) at Bahrain 2026. Lateral: real cars median 0.3 m (p95 2.0 m) from the line. **Arc length as lap distance errs by −16 to −60 m.** | **recorded-verified**. Axis/sign against `pos_x_m` / `pos_z_m`: confirm in code once |
| C | **Fraction mapping**: d = s/L_src × `m_trackLength` | any 1-D source before positions exist | 0.5–2 % of a lap (25–120 m) | identity and "which corner is next" only |
| D | **Monotone landmark warp** (track-reference-sources.md §6.3 step 2): sector boundaries (forced), marshal zones (soft, game-static), speed minima (DP with gaps) | 1-D sources with landmarks (OSM spans, Crew Chief names, FastF1) | ±5–15 m slow and medium corners; ±15–25 m fast sweeps (estimate) | unvalidated |
| E | **Similarity registration with reflection + windowed point-to-line ICP** (Umeyama) | OSM ENU → game X/Z | TUMFTM (OSM-derived) racelines → PnG game lines: **det = −1 on all 4 tracks**, scale 0.997–1.002, RMS 1.2–2.9 m. OSM centreline vs driven line: expect RMS 3–6 m. Gates: scale 1.00 ± 0.03 **with a per-track game-scale allowance (Mexico ≈ 1.05)**; ring length vs `m_trackLength` within 1.5 % (same allowance); RMS ≤ 12 m | partly validated (registration onto the game frame via TUMFTM; no OSM-to-capture run yet) |
| F | **FIA relative landmarks**: "S1 110 m before Turn 6" → d(Turn 6) − 110 | human-curated FIA facts | ±20–30 m (the turn reference point is undefined) | used: Austria (consistent), Monaco, Madrid |
| G | **Projection onto a same-frame spline** (windowed search with wrap) | GT7 / AC EVO (no lap distance) | ≤ 1–2 m along track | earlier doc §6.6 |
| H | **Direct geodetic projection** | iRacing `.ibt` lat/lon | metre level | on hold (legal) |
| I | **ACC spline metres**: s = `splinePosition` × `trackMeters` | L0b-ACC, ACC Race Control, Crew Chief ACC entries | same frame for player and field. Unverified: `trackMeters` is the official length, not the spline length (about 1–2 % scale error); the spline-0 offset from the timing line; non-monotonic steps at small intervals | Phase-0 ACC capture needed (V9) |

**Geodesy for E.** Project WGS84 to a local ENU tangent plane at the start node, using ellipsoidal radii; this is exact to < 0.01 % over a circuit. Do **not** use spherical haversine: it is up to 0.3 % off east–west at 50° N (open-racetrack-db's Spa trace is 6994.7 m with haversine, against 7004 m with ellipsoidal radii from the same ways). Test both det = +1 and det = −1, because F1 25's X/Z frame is a reflection of real east/north.

**OSM ring extraction.**
1. De-duplicate members.
2. Take the graph 2-core of the relation's non-pit ways. A greedy chain fails on Silverstone and Monaco.
3. Choose the loop that obeys the oneway direction and passes the length gate.
4. Set s = 0 at the `start` node or at `raceway=finish|start-finish`. Where the start and finish nodes differ, the finish is the timing line.
5. Pin way IDs and versions.

### 6.2 Validation plan (real F1 25 laps)

**Status.** Two real races are recorded (Austria and Austria Reverse, format 2025, PS5). One excerpt is committed as a recorded-tier fixture.

**Results so far:**
- **V1:** PnG matches the game's values at both layouts.
- **V3:** partial. AI minima fall inside the named segments; every AI car's brake and lap distance are populated.
- **V5:** fails with the default model; passes with the calibrated envelope for one driver (n = 5 per track).

**Capture campaign.** Short practice sessions with AI on track. Time Trial needs only a few seconds for the Session packet; the other purposes need the listed laps.

| Capture | Purpose |
|---|---|
| Monaco, Mexico (any session, even a few seconds) | `m_trackLength`: Monaco expected about 3323 m, Mexico 4525 m |
| Suzuka, Baku | flat-kink markers T18 and T17–T20; S2 disagreement with Lovely at Suzuka |
| Bahrain in format 2025 **and** 2026 | DRS zone derivation in 2025; zone tables in 2026 |
| Spa, Monza, Silverstone | L1c comparison on the probe tracks (V5 beyond Austria) |
| Monaco, Zandvoort | L1c; banking |
| Madrid | 2026 pack; geometry for a later outline |
| Brazil, Miami | Lovely vs PnG sector disagreement (45–64 m) |
| Time Trial ×3 tracks, with and without a downloaded rival ghost | L0c (V7); V5 in Time Trial conditions |
| One session at two AI difficulty levels | the AI-vs-human onset gap |

**Checks and pass criteria.**

| ID | Check | Pass criterion |
|---|---|---|
| V1 | Session skeleton: `m_trackLength`, S2/S3, marshal count, zone tables. Compare with the PnG `track_length` and s1/s2, and with FIA "N m before Turn k" sector lines. | PnG \|Δ\| ≤ 2 m. FIA \|Δ\| ≤ 30 m decides whether game sectors equal the official ones; if they do not, demote them to soft warp landmarks. **Passed: Austria, Austria Reverse.** |
| V2 | PnG frame: project the player's positions onto the inverted outline; check axes, sign and the index mapping. | median along-track ≤ 2 m; lateral ≤ 3 m. **Passed** (gap-fill measurement); add it as a recorded test. |
| V3 | Field model: (a) AI telemetry populated per session type; (b) field corners vs learned corners after 3 clean laps; (c) AI-vs-driver onset distribution. | (b) apex \|Δ\| ≤ 15 m and the same corner count. Partial at Austria. |
| V4 | Identity: hand-label official turns on learned models for Monza, Silverstone, Monaco and Montreal. | 100 % correct labels for corners that have a minimum; complexes multi-labelled; reverse layouts never take forward numbers. Austria done. |
| V5 | Physics prior: per gated stop, \|onset_pred − onset_driver\|; false-zone rate. | median ≤ 15 m, p90 ≤ 30 m on ≥ 3 tracks of **Time Trial** captures before any *positional* L1c cue. Default model **fails**; calibrated envelope passes 2 race layouts for one driver. |
| V6 | OSM registration: scale, reflection, RMS, p95. Negative test: the Catalunya with-chicane relation against the game layout. | negative test rejected by the gate; det = −1 chosen. |
| V7 | Time Trial ghost slots: positions, lap distance, brake? | decides L0c. |
| V8 | Promotion | Upgrade `capabilities.py` only after V1–V5 pass on recorded evidence; log per-track results in `docs/validation.md`. |
| V9 | ACC Phase 0 (PC): delivered update interval at 50 and 100 ms; km/h-vs-spline latency; spline-0 offset; `trackMeters` vs the integrated lap; world-position units; `focusedCarIndex` = player. Offline AI practice at Monza, Spa and Donington. | Onset median ≤ 10 m vs ARC / Crew Chief landmarks; 90 % of minima inside the names' spans. |
| V10 | Importer checks on every PnG re-pin: blob SHAs; max turn number vs F1DB; `track_length` vs captured `m_trackLength`; recorded field minima inside segments with the same number. | Any failure blocks `verified`. |

---

## 7. Licensing guidance

pitwall is proprietary. The rule of thumb:
- runtime game data and pitwall-authored facts are clean;
- permissive data ships with its notices;
- share-alike data lives in its own file;
- everything else stays on the user's machine or out.

### 7.1 Can ship in the repo (with notices)

| Data | Licence | What to ship | Obligation |
|---|---|---|---|
| pitwall track sheets (`src/pitwall/trackdata/track_sheets/f1/*.toml`) | pitwall | curated facts | none. Do not copy prose or bulk-extract from Wikipedia, the FIA, F1.com, racingcircuits.info or Motorsport Magazine; hand-author from several references. |
| PnG `track-segments` (re-pin `72f78aaf`, with a blob-SHA table in `PROVENANCE.md`) | MIT | vendored JSON (already done at `3490db9`) | "Copyright (c) [2024] [Ashwin Natarajan]" plus the MIT permission notice. The #343/#345 changes are covered by the repo licence (GitHub ToS D.6, inbound = outbound). |
| PnG `track-maps/f1_2025` outlines (`13c30d7`) | MIT | inverted outlines plus the affine | MIT notice. **Counsel before commercial release** (§7.6); fallback is a user-side fetch at first run. |
| Crew Chief landmark names (`main` @ `cbd0f488`) | MIT | names and order only | "Copyright (c) 2019-2024 Britton IT Ltd" plus the MIT notice. Not `tracks.zip`, `lap_lengths.json`, `iracing-track.json` or iRacing-only entries. |
| ACC Race Control `.trackData`, converted to JSON (`42f87f55`) | MIT | speed maps, sector lines, speed trap | "Copyright (c) 2021 Leonard Schüngel" plus the MIT notice. Kunos question for game-derived tables (§7.6). |
| F1DB release data (pin a release tag, e.g. v2026.16.1) | CC BY 4.0 | layout-gate table | Attribution (§7.5). **Use only the release data files, never the repo tree's SVG assets.** |
| Wikidata IDs, labels, lengths | CC0 | crosswalk | none (courtesy credit) |
| gt-telemetry (MIT), gt7info (MIT-0), gt7-datalogger signatures (MIT), Forza ordinals (MIT) | as stated | secondary-game tables | notices where MIT |
| AHN DTM extracts; USGS 3DEP extracts | CC0; public domain | optional elevation | none; "3DEP data courtesy of the U.S. Geological Survey" |

### 7.2 Ship only as a separate share-alike file: the OSM track pack (ODbL 1.0)

Licence: https://opendatacommons.org/licenses/odbl/1-0/. OSMF guidance: https://osmfoundation.org/wiki/Licence/Licence_and_Legal_FAQ.

- **One file** (e.g. `osm-trackpack.geojson`), keyed by pitwall `track_id`. It holds the rings, start node, pit lane, named spans, refs and way-version provenance. It is **licensed under ODbL** (§4.4) and keeps the notices (§4.2).
- **Public offer.** Offer the file publicly and free in machine-readable form, or offer the recipe or alterations file (§4.6). No DRM unless an unrestricted parallel copy is offered (§4.7).
- **Do not rely on "insubstantial".** Extracting about 30 circuits systematically counts as substantial (guideline endorsed 2014-06-06).
- **Collective Database.** Keep learned, field and physics data keyed to pitwall's own lap distance and linked to OSM only by reference. Never merge it into OSM geometry. Then share-alike does not reach it (guideline endorsed 2016-06-17).
- **Attribution.** Rendered maps and spoken names derived from the pack are Produced Works. Show "© OpenStreetMap contributors" with a link to https://www.openstreetmap.org/copyright next to any OSM-derived map, and on the About screen.
- **Extraction.** Extract at build time from Geofabrik, the planet file or a pinned Overpass response. The OSM editing API forbids read-only use, and public Overpass is not an app backend.
- **Third-party data in the pack.** If open-racetrack-db recipes are reused, keep its notice. If Copernicus GLO-30 is used, include its Art. 6 notices.

### 7.3 User-side only (never shipped or cached centrally)

- **F1 25 UDP data.** Runtime use by nature. Never redistribute captures or tables built from other users' sessions. Opt-in corpus aggregation would need its own terms and a privacy review.
- **FastF1 overlay** (earlier doc).
- **Assetto Corsa local files.** Legal review first.
- **FIA circuit maps.** Manual reading only; FIA T&C §3.7 and §3.9.
- **Brembo figures.** Internal validation only until written permission exists.
- **MultiViewer markers.** Ad hoc developer cross-check only; never in CI or in the repo.

### 7.4 Do not use

- **Non-commercial licences:** Lovely Track Data and its derivatives; FABDEM; A2RL; RACECAR.
- **Copyleft:** GPL and AGPL projects.
- **Licence conflict:** TUMFTM, for shipping.
- **No licence or unclear provenance, for shipping:** bacinger, scluba, SergioSediq, the Garage 61 export, prule/acc-client.
- **Laundered artwork:** F1DB `src/assets/circuits` SVGs, julesr0y/f1-circuits-svg and its re-upload, Motorsport Magazine maps. Do not use them for shipping, as a user-side fetch, as the dashboard map, or for registration or QA overlays.
- **Proprietary products:** Track Titan, Coach Dave, VRS, trophi.ai, F1Laps.
- **Game files and screen capture:** F1 game ERP files; computer-vision capture of the dynamic racing line (EA User Agreement §2 and §7.C).
- **iRacing-recorded data:** ToU "Data" clause.
- **FOM timing data.**

### 7.5 Attribution text (draft for `THIRD_PARTY_NOTICES` and the About screen)

```
Track corner segments and track outlines for the F1 25 game derive from Pits n' Giggles
(https://github.com/ashwin-nat/pits-n-giggles), Copyright (c) [2024] [Ashwin Natarajan], MIT License.
[full MIT permission notice]

Corner-name vocabulary derives in part from Crew Chief V4 (https://gitlab.com/mr_belowski/CrewChiefV4),
Copyright (c) 2019-2024 Britton IT Ltd, MIT License. [full MIT permission notice]

[if ACC support ships] ACC track speed maps and sector lines derive from ACC Race Control
(https://github.com/LennysLounge/ACC-Race-Control), Copyright (c) 2021 Leonard Schüngel, MIT License.
[full MIT permission notice]

Circuit geometry (osm-trackpack): © OpenStreetMap contributors, available under the Open Database License
(ODbL) 1.0, https://www.openstreetmap.org/copyright. The derived track pack is itself licensed under the
ODbL 1.0 and is available at <public URL>.

Circuit layout ids, lengths, turn counts and directions: F1DB by Marcel Overdijk and contributors
(https://github.com/f1db/f1db), CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/); values selected and
converted. F1DB circuit SVG assets are not used.
Circuit identifiers: Wikidata (CC0).
[if used] Elevation: 3DEP data courtesy of the U.S. Geological Survey; AHN (Rijkswaterstaat), CC0.

pitwall is unofficial and is not associated with Formula 1, the FIA, Electronic Arts, Codemasters,
Kunos Simulazioni or 505 Games. F1 and related marks are trademarks of Formula One Licensing B.V.
```

### 7.6 Questions for counsel before any commercial release

1. **EA, game-derived data.** Does shipping tables or geometry recorded from F1 25 telemetry touch EA User Agreement §2 ("may not ... copy, modify or distribute any EA Service, Content")? This covers the PnG outlines, and the PnG segment windows and sector values, which equal the game's own values. Corner numbers and names are real-world facts.
2. **EA, the runtime channel.** Is commercial use of the documented UDP channel within §7.C? F1Laps sells UDP-based analysis openly, which shows practice but is not a licence.
3. **ODbL.** Is an embedded, OSM-derived polyline used only for computation a Produced Work or a Derivative Database? This document assumes the conservative separate-file approach.
4. **Brembo.** Written permission for per-turn braking facts.
5. **Kunos / 505 Games.** Commercial runtime use of the ACC broadcast and shared-memory interfaces, and shipping game-derived ACC tables (ACC Race Control, Crew Chief metres). Also Kunos's position on coaching tools that read Assetto Corsa files.
6. **iRacing.** ToU (August 2026): §4.1 "Data", §6.1(d) (AI models), §6.1(e) (data-collecting software), §6.1(f) (making Sim information available for value), §6.2, §6.3 and §6.5 (personal, non-commercial interfaces only).
7. **MultiViewer.** Whether even developer-side verification against an unlicensed, "non-commercial" API is acceptable for a commercial product. Default: do not depend on it.

---

## 8. Implementation plan for pitwall (smallest valuable step first)

Each phase ends with:
- `make check` passing;
- `docs/status.md`, `docs/licences.md` and `docs/architecture.md` updated;
- capability statuses changed only with evidence.

The status column reflects `src/pitwall` on 2026-10-10.

| Phase | Scope | Status |
|---|---|---|
| 0 | Recorded captures | **partly done** (Austria, Austria Reverse) |
| 1 | L0a session skeleton | **done** (decode, `TrackZones`, `track_skeleton.py`, `SectorBands.svelte`) |
| 2 | L2 identity | **seeded** (28 TOML sheets from the PnG pin; `track_identity.py` and tests; Austria verified). Not yet wired into lap processing, facts or voice. |
| 3 | L0b field model (F1) | not started |
| 4 | L1a outline + L1c severity prior | not started |
| 5 | L1b OSM pack | not started |
| 6 | Secondary games (ACC field model first) | research done |
| 7 | User-side sources, L0c | not started |

### Phase 0: captures (no code)

Run the §6.2 campaign. Monaco and Mexico need only seconds each. Promote byte-for-byte excerpts with `scripts/excerpt_capture.py`, and update `tests/fixtures/recorded/README.md`, which still says no captures are committed.

### Phase 2 completion: identity, the next smallest valuable step

1. **Re-pin PnG to `72f78aaf`.** Re-vendor only the 5 changed files and update the blob-SHA table in `PROVENANCE.md`. Re-run `scripts/import_track_segments.py` for Melbourne, Montreal, Baku, Las Vegas and Singapore. These sheets are unreviewed, so the importer may overwrite them.
2. **Add importer checks** (V10):
   - max turn number = F1DB turn count for the layout;
   - no duplicate or gapped numbers;
   - recorded field minima fall in the matching segments when a capture exists;
   - store `lap_length_m` from captured `m_trackLength` once known.

   Have `official_turn_count` come from F1DB instead of "the highest PnG number".
3. **Hand fixes, in the sheets only:**
   - **Monaco:** T17 unnamed; T18 La Rascasse; T19 Antony Noghès; fix spellings; mark `lap_length_m` unknown until captured. Its windows are truncated, not scaled: never rescale them.
   - **Baku:** add T17–T20 as flat markers at about 4267, 4506, 4661 and 4974 m (MultiViewer facts, scaled; re-check against a capture).
   - **Suzuka:** add T18 as a flat marker at about 5629 m.
   - **Madrid:** letter labels T5A and T20A.
   - **Mexico:** note "game length 4525 m (probable); real 4304 m".
4. **Fix the length gate** in `track_identity.py`: compare against the Session `m_trackLength`, not the learned path length. Do this if it does not already.
5. **Wire identity into the runtime:**
   - `core/lap_processor.py`: map on each new `TrackModel.version`;
   - `ai/facts.py`: corner facts carry `official_label`, `name` and `identity_tier`;
   - `voice/proactive.py` and `coach/cues.py`: names only with `voice_ok`.
6. **Curate names,** one track at a time, with V4 against recorded captures. Priority: tracks the user drives.
7. **Optional, needs the user's go-ahead:** upstream issues or PRs to PnG for Monaco (labels and length), Baku T17–T20 and Suzuka T18. Posting is public and needs the user's explicit permission.

### Phase 3: F1 field model (L0b)

- **`adapters/f1/adapter.py`:** decode Motion, LapData and CarTelemetry for **all** slots, plus the DRS and aero activation distances from CarStatus and CarTelemetry2. Emit a compact `FieldSample` per car (index, lap distance, X/Y/Z, speed, brake, throttle, gear, pit status, driver status). Decimate to ≤ 10 Hz per car and hand off through a bounded queue, so the UDP thread stays O(1).
- **`analysis/field_model.py`:**
  - 5 m bins with robust medians and the §2 L0b filters;
  - support counts;
  - pit-lane path and entry/exit;
  - speed-trap location;
  - format-2025 DRS activation;
  - **the per-game brake-envelope fit** (AI samples with brake ≥ 0.95: decel = b0 + b1·v² from −`gForceLongitudinal`·g).
- **Storage:** bump `SCHEMA_VERSION` 2 → 3 with a new table `track_references(id, game, track_id, kind, version, mapped_model_version, source, licence, created_unix, payload JSON, UNIQUE(game, track_id, kind, version))`. `track_models` stays for learned models only. All SQL goes in `storage/repo.py`.
- **`core/track_knowledge.py`:** a resolver that applies the §2 precedence and tiers and pushes a `TrackKnowledge` snapshot to `LiveState`.
- **Coach:** lap-1 heads-ups at the field onset (support ≥ 3 car-laps), placed earlier by the uncertainty. The "never later" rule is unchanged. Any new brake-onset logic uses thresholds of 0.05 or more (pedal-noise note in §2).
- **Tests:**
  - extend `sim/f1_stream.py` to emit AI cars with injected brake points (synthetic tier);
  - recover each onset within one bin;
  - ignore pit and out-lap cars;
  - test queue back-pressure;
  - recorded tier: Austria minima inside named segments (V3).

### Phase 4: outline (L1a) and severity prior (L1c)

- **Data:** the PnG outlines plus `svg_transforms.json`, vendored or fetched depending on §7.6.
- **`analysis/track_geometry.py`:**
  - affine inversion;
  - the index map (*i* + 0.5)·L/800;
  - length gate |800·median spacing − L| < 1 %;
  - periodic chord-length spline;
  - 1 m arc-length resampling;
  - heading-derivative curvature.
- **`analysis/brake_prior.py`:**
  - solve at σ ∈ {5, 10, 15, 20} m;
  - extract zones with the `braking.py` thresholds;
  - apply the σ-ensemble gate;
  - map positions back through the knot table;
  - use the field-fitted envelope when available, otherwise the default **with positional output suppressed**.
- **`sim/driver.py`:** friction-ellipse coupling; optional grade and bank terms from game Y and roll. Existing synthetic ground-truth tests must stay green.
- **Coach:** the severity tag only ("heavy stop next, Turn N", at least 2 s ahead). **Web:** shaded "estimate" windows.
- **Tests:**
  - closed-form cases (constant-radius speed; straight-line braking distance);
  - phantom-curvature test on a noisy straight;
  - recorded-tier V2 (index mapping on the Austria excerpt) and V5.

### Phase 5: OSM track pack and registration (L1b)

- **`scripts/build_osm_trackpack.py`**, run at build time by maintainers. Input: a Geofabrik extract or a pinned Overpass response. Steps:
  1. de-duplicate members;
  2. take the 2-core ring with the oneway and length gate (F1DB / Wikidata lengths, with game-scale allowances);
  3. apply recipes for Austria, Jeddah, Miami, Las Vegas, Madrid, Imola, Monaco and Paul Ricard;
  4. extract the start node, pit lane and named spans;
  5. record way-version provenance;
  6. compute ENU.

  Output: `osm-trackpack.geojson`, plus `LICENSE-ODbL` and a README, published publicly.
- **`analysis/registration.py`:** Umeyama with det ±1 (expect −1), windowed ICP, gates and diagnostics.
- **Uses:** pit-lane geometry and width before driving; Madrid's outline; secondary games.
- **Tests:**
  - synthetic similarity with reflection;
  - wrong-layout negative test;
  - attribution rendered wherever an OSM layer is drawn.

### Phase 6: secondary games

| Game | Track identity | Geometry / lap distance | Names / identity | Steps |
|---|---|---|---|---|
| ACC (PC) | TRACK_DATA `trackName` / `trackId` / `trackMeters`; a pitwall-authored 25-track crosswalk | s = spline × `trackMeters` (player and field share the frame); L0b-ACC field model; ARC seed (MIT, 24/25 tracks) | Crew Chief: same frame for 4 tracks, Donington ×1.0295 and Imola ×1.0195, landmark warp for 13, none for 7; sectors from ARC (22 curated) + Crew Chief (10) + runtime derivation | 1. Clean-room Python broadcast client plus `.pwcap` capture. 2. V9 Phase-0 capture. 3. Reuse `analysis/field_model.py` with an ACC sample adapter (onset from deceleration). 4. ARC import with notice, converting Java serialisation through a whitelist parser. 5. Crew Chief names with the warp and a 90 % gate. 6. Upgrade `capabilities.py` only after recorded evidence. |
| ACC (console) | – | – | – | Unsupported: no interface |
| AC | `trackName` / `trackConfig` | user-side `fast_lane.ai`; field model would need an in-game Python app | user-side `sections.ini`; Crew Chief (21) | after EULA review |
| GT7 | gt7-datalogger signatures (MIT) | gt-telemetry centrelines (MIT), method G | gt7info (MIT-0) | per earlier doc |
| Forza | ordinal table (MIT) | field model not possible (no other cars) | – | – |
| iRacing | – | `CarIdxLapDistPct` × length at 60 Hz (trivial) | – | **legal hold** (ToU) |

### Phase 7: optional user-side sources and the Time Trial ghost

- The FastF1 overlay, as in the earlier doc.
- L0c (the ghost reference), if V7 shows populated slots.

### Follow-ups in other docs (out of scope for this file)

- **`docs/research/track-reference-sources.md`:** the TL;DR row ("plus circuit SVGs") and §4.4 should say "do not use F1DB SVG assets at all (Motorsport Magazine copies; see track-knowledge-sources §9)". It should also note that the F1DB id `sochi` became `sirius` on 2026-10-02.
- **`docs/licences.md`:**
  - F1DB row: "data only; SVG assets not used";
  - PnG row: re-pin to `72f78aaf`;
  - add rows for Crew Chief and ACC Race Control when they are used.
- **`src/pitwall/trackdata/third_party/pits_n_giggles/PROVENANCE.md`:**
  - "Known data issues": Mexico 4525 is probably the game length, not an error; Monaco is truncated;
  - the generator facts from §2 L1a.
- **`tests/fixtures/recorded/README.md`:** it still says no captures are committed.

---

## 9. Rejected or unsuitable sources

| Source | Reason |
|---|---|
| **F1DB circuit SVG assets** (`f1db/f1db src/assets/circuits`; 160 layouts × 4 styles; added in `3493684f`, 2026-02-26; credited to Jules Roy) | The repo-wide CC BY 4.0 licence cannot cover third-party artwork (CC BY §1 covers only rights the licensor "has authority to license"; §5 disclaims non-infringement). In an anchor-sequence test, **20 of the 30 layouts tested** are Motorsport Magazine's own Illustrator circuit paths, resized with identical anchors (residual ≤ 0.0004 % of the diagonal). Examples: silverstone-8, monaco-6, monza-7, spa-francorchamps-4, madring-1 at `3493684f`. MSM's terms are personal and non-commercial and forbid reproduction or distribution. f1db issue #113 confirms Madring was first taken from MSM and later re-traced from formula1.com. The other layouts (Shanghai, Sakhir, COTA, Baku, Miami, Red Bull Ring, sirius-1) have no documented source. The outlines are schematic anyway. F1DB **data** is unaffected. |
| julesr0y/f1-circuits-svg (deleted) and MisterSix2295/f1-circuits-svg (re-upload, MIT) | Upstream of the F1DB SVGs; the same Motorsport Magazine provenance. |
| Motorsport Magazine circuit database maps | "Strictly for personal, non-commercial use"; no reproduction or systematic storage. Usable as a human reference only. |
| formula1.com track outline SVGs | All rights reserved; the current F1DB madring-1 is a hand-tracing of one. |
| Wikimedia Commons "Circuit Sochi.svg" | CC BY-SA, with a questionable base; not the source of F1DB sirius-1. |
| Lovely Track Data | CC BY-NC-SA 4.0 (README footer only); names credited to racingcircuits.info (all rights reserved); 12 of 25 F1 25 files carry only generic T-names. Superseded by PnG. Its *lengths* were useful as a facts-only cross-check (Monaco 3323, Mexico 4525). |
| tobi/track-atlas, irdashies `tracks-bundle.json`, iracing-adaptive-coach, iracedeck corners | Lovely NC-SA data re-bundled under MIT or non-commercial labels; irdashies `tracks.json` is iRacing-owned. |
| TUMFTM racetrack-database / laptime-simulation | LGPL label on OSM-derived data; unnamed imagery source; stale layouts. Internal validation only (used in §5). |
| TUMFTM global_racetrajectory_optimization, trajectory_planning_helpers | LGPL code that imports GPL-2.0+ `quadprog`. |
| f1tenth_racetracks, TUM-AVS/GGGVDiagrams, OpenLAP, mantazzo/F1TV-HUD-Reworked, RiddleTime/Race-Element, GPL GT7 projects | GPL-3.0. |
| SpeedHQ/RaceIQ | AGPL-3.0 (the richest F1 25 geometry, including track edges, but unshippable). Design idea kept: facts without positions, and geometry without names. |
| bacinger/f1-circuits, SergioSediq/f1-circuits, scluba/f1-circuit-geodata | Anonymous Google My Maps upstream / an unattributed copy / undocumented and OSM-coincident. |
| Wikimedia Commons SVG maps; Commons Data geoshapes | Mostly CC BY-SA; the CC0 Firkin series is outline-only (2014–18); some are derived from formula1.com; Data pages state no provenance. |
| Overture Maps transportation | ODbL plus TomTom; no raceway class. |
| SRTM / NASADEM; FABDEM | Flown in 2000, before most venues existed; FABDEM is non-commercial. |
| A2RL V_max, RACECAR, Stanford Revs, TUMFTM f1-timing-database | Non-commercial or irrelevant. |
| Simulator Controller | CC BY-NC-SA plus GPL; no shipped F1 25 track data. |
| Garage 61 `tracks.zip` and API | No licence on the export (iRacing-derived lat/lon); API terms unreadable. |
| prule/acc-client | No licence; used for facts only (it decoded the ACC message layout). |
| Track Titan, Coach Dave Delta, VRS, trophi.ai, F1Laps, Sim Racing Setups, SRT, Racelogic, AiM, RaceChrono, Garmin Catalyst, APEX Pro, Corner Scorer | Proprietary or unlicensed. Ideas kept: a 4-phase corner model, speech timed to arrival, and a "true optimal lap" built from the driver's own segments. |
| F1 Track Vectors (F1Laps, Gumroad) | No usage terms. |
| racingcircuits.info, Formula1.com, Mercedes-AMG F1 explainers, Pirelli previews, YouTube guides | All rights reserved, or personal and non-commercial. Human fact-checking only. |
| iRacing Data API assets and data recorded inside iRacing (ircorners, JRT-Trackmaps, Crew Chief iRacing entries) | The iRacing ToU claims "Data" and bars derivative works and commercial exploitation. |
| F1 25 game files (ERP), screen capture of the dynamic racing line, EA Racenet | EA User Agreement §2 and §7.C; no Racenet API. The same knowledge is available legally via L0b. |
| TracingInsights/2025 and 2026 | FOM timing data relabelled Apache-2.0. |
| Unlicensed F1 25 apps (Suh0161, f125-telemetry, BoxBoxF1Coach corner data, …), CG-67-R1/Send-It, RHughes33/LapSimulation | No licence, or all rights reserved. |
| jlsp124/f1-dual-engineer | Duplicate of PnG. |
| PnG `beta/5.0.0-beta.1` tag (`d0f5a28`) | Diverged line; lacks all five segment fixes. |
| Crew Chief `Track_splines/ASSETTO_EVO` | Single driven laps for AC EVO only. |
| Brembo third-party republications (thebrakereport, Motorionline, …) | Copies of Brembo material. Use the originals (§5 now does). |

---

## 10. Open questions

1. **`m_trackLength` for Monaco and Mexico.** The expected values are about 3323 m and 4525 m. Does the 2026 Season Pack use the same lengths as the base game? Lovely's f12025 files are copies of f12024. (Phase 0; seconds of capture each.)
2. **AI telemetry coverage.** Is the AI field populated in every session type, including career and online? Do Time Trial ghost slots carry telemetry? (V3, V7.)
3. **The AI-vs-human gap.** On Austria the AI braked 20–30 m earlier than this driver. How does that depend on AI difficulty, and does the calibrated envelope generalise beyond 2 layouts, 1 driver and n = 5? (V5.)
4. **Official sectors.** Are the game's S2/S3 the FIA lines? Austria is consistent; Madrid is 31–34 m off. (V1.) The Lovely/PnG sector disagreements at Brazil, Miami and Suzuka S2 are unresolved.
5. **DRS in format 2025.** Can DRS zones be reconstructed from `m_drsActivationDistance` / `m_drsAllowed`?
6. **Madrid geometry.** Which OSM variant matches the Season Pack layout? There is no PnG outline.
7. **Naming policy.** For voiced names: official current names (Hungaroring 2026, Curva Alboreto), traditional names, or the names the game's commentary uses? Sponsor names change yearly; Austria's T4/T6 are already unresolved. Melbourne's driver names and Montreal's "Pont de la Concorde" are unverified.
8. **PnG upstream.** Whether the `release-v5.0.0` branch is squash-merged, which could orphan `72f78aaf`; keep the vendored copy and the SHAs regardless. Whether to file issues or PRs for Monaco, Baku and Suzuka; that needs the user's permission.
9. **The unknown capture `20261010-171304`** (trackId −1, 3964 m). Almost certainly synthetic; confirm via its session UID.
10. **Pedal noise.** Is the player's brake noise floor (< 0.0046 at rest) the CSL pedals' resting load or a deadzone setting? It matters for any `brake > 0` logic and for the coming load-cell upgrade.
11. **ACC measurements** (V9): the update rate actually delivered, km/h-vs-spline latency, the spline-0 offset, the `trackMeters` scale, and whether `focusedCarIndex` identifies the player. All need ACC on a Windows PC.
12. **Legal** (§7.6): EA game-derived data; commercial use of the UDP channel; embedded ODbL polylines; Brembo; Kunos/505; iRacing; MultiViewer.
13. **Calibration ceiling.** Can field- or driver-calibrated envelopes plus a friction ellipse make fast corners (R 100–200 m) safe to cue?
14. **Product name.** An unrelated, unlicensed GitHub project is also called "pitwall" (mlnomadpy/pitwall).

---

## Sources

**Game-native**
- EA F1 25 / 2026 Season Pack UDP spec: https://forums.ea.com/blog/f1-games-game-info-hub-en/ea-sports%E2%84%A2-f1%C2%AE25-2026-season-pack-udp-specification/12187347 ; pitwall `docs/research/f1-udp-spec.md` (§7: no standalone F1 26; §8.3: track ids)
- EA User Agreement: https://www.ea.com/legal/user-agreement
- pitwall's own captures: `data/captures/20261010-191501_udp20777.pwcap`, `20261010-193550_udp20777.pwcap`; `tests/fixtures/recorded/f1_25_2025_ps5_austria_race-excerpt.pwcap`
- Third-party Bahrain 2026 clip (unlicensed; facts only): https://github.com/skrx7392/f126-race-engineer/blob/main/tests/fixtures/bahrain_p1_2026_trimmed.cap

**Corner identity and game-frame seeds**
- Pits n' Giggles: https://github.com/ashwin-nat/pits-n-giggles (LICENSE at `72f78aaf`: https://github.com/ashwin-nat/pits-n-giggles/blob/72f78aaf19910cea0aaa302cf69905daa6f331f4/LICENSE ; segments at the v5 head: https://github.com/ashwin-nat/pits-n-giggles/tree/72f78aaf19910cea0aaa302cf69905daa6f331f4/assets/track-segments ; maps at `13c30d7`: https://github.com/ashwin-nat/pits-n-giggles/tree/13c30d7dbfc33e413316c0fe3b5ed747e6b2cbc1/assets/track-maps/f1_2025 ; PRs https://github.com/ashwin-nat/pits-n-giggles/pull/343 and https://github.com/ashwin-nat/pits-n-giggles/pull/345)
- Crew Chief V4: https://gitlab.com/mr_belowski/CrewChiefV4 (LICENSE on `main`; `CrewChiefV4/trackLandmarksData.json`)
- F1DB: https://github.com/f1db/f1db (LICENSE; data `src/data/circuits` at `b457bedc`; SVG provenance: issue #113, commit `3493684f`)
- MultiViewer API (developer cross-check only): https://api.multiviewer.app/api/v1/circuits/{key}/{year}
- FIA documents: https://www.fia.com/documents/championships/fia-formula-one-world-championship-14/season/season-2025-2071 ; Monaco 2025 map: https://www.fia.com/system/files/decision-document/2025_monaco_event_-_circuit_map_-_monaco_2025_0.pdf ; FIA T&C: https://www.fia.com/file/83930/download
- formula1.com explainers (human reference): https://www.formula1.com/en/latest/article/explained-how-every-monaco-corner-got-its-name.5ClYqWmfpeUpsRJA6mDNaX ; Madring guide: https://www.formula1.com/en/latest/article/circuit-guide-everything-you-need-to-know-about-the-madring.NF7Mh3iag3w9GUPlihwJA
- Mercedes-AMG Interlagos names: https://www.mercedesamgf1.com/news/how-the-interlagos-corners-got-their-names
- Wikidata: https://www.wikidata.org/wiki/Wikidata:Licensing ; Wikipedia: https://en.wikipedia.org/wiki/Silverstone_Circuit
- Motorsport Magazine terms: https://www.motorsportmagazine.com/terms

**Geometry**
- OpenStreetMap: https://www.openstreetmap.org/copyright ; ODbL https://opendatacommons.org/licenses/odbl/1-0/ ; OSMF FAQ https://osmfoundation.org/wiki/Licence/Licence_and_Legal_FAQ ; Substantial guideline https://osmfoundation.org/wiki/Licence/Community_Guidelines/Substantial_-_Guideline ; Collective Database guideline https://osmfoundation.org/wiki/Licence/Community_Guidelines/Collective_Database_Guideline_Guideline ; Attribution guidelines https://osmfoundation.org/wiki/Licence/Attribution_Guidelines ; API policy https://operations.osmfoundation.org/policies/api/ ; example relation https://www.openstreetmap.org/relation/284560
- open-racetrack-db: https://github.com/markthebault/open-racetrack-db ; OpenTrackData: https://github.com/chendo/opentrackdata
- Rejected geometry: https://github.com/TUMFTM/racetrack-database ; https://github.com/bacinger/f1-circuits ; https://github.com/scluba/f1-circuit-geodata ; https://github.com/SpeedHQ/RaceIQ

**Elevation**
- Copernicus GLO-30 licence: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf ; AHN: https://data.overheid.nl/dataset/47567-actueel-hoogtebestand-nederland--ahn--dtm ; UK EA: https://www.data.gov.uk/dataset/lidar-composite-dtm-2020-1m ; USGS 3DEP: https://developers.google.com/earth-engine/datasets/catalog/USGS_3DEP_1m

**Braking data (validation only)**
- Brembo 2025: https://www.brembo.com/en/motorsport/formula1/2025-numbers ; https://www.brembo.com/en/motorsport/formula1/2025/facts-formula1-gp-uk ; https://www.brembo.com/en/motorsport/formula1/infernal-circuits ; 2026 Belgium: https://www.brembo.com/en/motorsport/formula1/2026/facts-belgium-2026 ; Terms: https://www.brembogroup.com/en/terms-of-use
- 2021 Brake Circuit Identity Cards (Wayback), e.g. Spa: https://mediakit.brembo.com/index.php/component/phocadownload/category/359-english?download=1658:gp-belgium-circuit-de-spa-francorchamps (archived copies of 2022-06-29); Monaco: http://web.archive.org/web/20220629231318/https://mediakit.brembo.com/index.php/component/phocadownload/category/359-english?download=1616:gp-monaco-circuit-de-monaco
- Secondary (shown only where no original was found): https://f1grandprix.motorionline.com/en/formula-1-gp-belgio-brembo-analizza-limpegno-dei-sistemi-frenanti-sul-tracciato-di-spa/ ; https://f1grandprix.motorionline.com/en/formula-1-gp-italia-brembo-analizza-limpegno-dei-sistemi-frenanti-sul-tracciato-di-monza/
- Pole times: https://api.fia.com/news/f1-norris-takes-belgium-pole-ahead-piastri-and-leclerc ; https://api.fia.com/news/f1-verstappen-sets-new-monza-record-take-pole-ahead-norris-and-piastri ; https://en.wikipedia.org/wiki/2025_British_Grand_Prix

**Methods**
- Kapania, Subosits & Gerdes: https://arxiv.org/abs/1902.00606 ; Velenis & Tsiotras: https://doi.org/10.1007/s10957-008-9381-7 ; Heilmeier et al.: https://doi.org/10.1080/00423114.2019.1631455 ; Duhr et al.: https://doi.org/10.1109/tvt.2022.3172473 ; Subosits & Gerdes: https://doi.org/10.1109/tiv.2019.2904390 ; Lovato & Massaro: https://doi.org/10.1080/00423114.2021.1878242 ; Perantoni & Limebeer: https://doi.org/10.1115/1.4028253 ; Haklay 2010: https://ideas.repec.org/a/sae/envirb/v37y2010i4p682-703.html

**Secondary games**
- ACC broadcasting thread: https://www.assettocorsa.net/forum/index.php?threads/lets-talk-about-broadcasting-programmers-thread.53826/ ; Kunos readme (mirror; facts only): https://github.com/framf0rt/ACCBroadcastingTool-Modified/blob/master/KunosReadme/readme.txt ; ACC EULA: https://store.steampowered.com/eula/805550_eula_0
- ACC Race Control: https://github.com/LennysLounge/ACC-Race-Control/tree/master/base/src/main/resources/trackdata (MIT; pin `42f87f55ffa8cc7332c686ab7c15bb98df1c090d`)
- ACC v1.10.1 notes (secondary): https://racesimcentral.net/assetto-corsa-competizione-v1-10-1-fixes-api-sector-times-for-nurburgring-24h/
- GT7 / Forza: https://github.com/zetetos/gt-telemetry ; https://github.com/ddm999/gt7info ; https://github.com/jbhoorasingh/gt7-datalogger ; https://github.com/bluemanos/forza-motorsport-car-track-ordinal
- AC EULA: https://store.steampowered.com/eula/244210_eula_0 ; iRacing ToU: https://ir-core-sites.iracing.com/members/pdfs/20260805-iRacing_Terms_of_Use_and_EULA_dated_Aug_05_2026.pdf

**Research artefacts** (session scratchpad, not in the repo; `.../scratchpad/track-research/`)
- `probe/` — original probe
- `png-physics-gapfill/` — shippable-path and Austria V5 scripts and outputs
- `png-v5-audit/` — re-pin audit; MultiViewer copies stay local
- `acc-field-model/` — ACC Monte Carlo, `.trackData` reader, cross-checks
- `game-native/`, `open-geodata/`, `open-geodata-verify/`, `sim-projects-verify/` — angle data
