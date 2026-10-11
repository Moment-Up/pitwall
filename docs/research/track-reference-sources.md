# External track-reference sources: can they pre-seed pitwall track models?

Research date: 2026-10-10.

**Method.** I collected GitHub metadata with `gh api repos/<o>/<r>`, `.../license`, `.../git/trees`, `.../commits` and `.../contents`. I fetched f1livedata.com pages (home, `robots.txt`, `sitemap.xml`, `/terms`, `/about`, one circuit page and one guide) with `curl` into the scratchpad and stripped them to text. I read openf1.org, multiviewer.app and the formula1.com Legal Notices with WebFetch. The two gt7-track-visualizer sample CSVs were downloaded to the scratchpad and summarised with a script of my own (`python3 -I`); they were only read as data. **Nothing was cloned into the project, and no code from any of these repos was executed.** No code is reproduced here. The ideas are described in prose so they can be re-implemented clean-room.

**Context.** pitwall's `analysis/track.py` builds a `TrackModel` per `(game, track_id)` from clean laps. A model holds a 5 m ground-plane centreline (`pos_x_m`, `pos_z_m`) and corners `T1..Tn` taken from median-speed minima (prominence 8 km/h, spacing 60 m). The docstring already expects "an official-name mapping attached per track later". This document is about that mapping, plus pre-seeding a model before any clean lap exists.

---

## TL;DR

| Resource | What it really is | Licence / terms | Useful to pitwall? |
|---|---|---|---|
| **f1livedata.com** | Independent, ad-funded fan dashboard (one developer, Italian law). Live timing, telemetry vs distance, live track map, replays, plus F1DB-based circuit/season pages. | Site ToS (updated 27 Jul 2026): **personal, non-commercial**. No scraping or re-publishing "for commercial purposes", and no reuse of its original content without permission. **No public API**: `/api/` (internal FastAPI) and `/bundles/` are `Disallow`ed in robots.txt, except `/api/f1db/`. | **No as a data source.** Its guide pages carry useful *facts* about the F1 feed (brake is binary, DRS is 0 in 2026, see §1). |
| **SudeshnaPathak/F1_Visualizer** | Streamlit multipage app (13 pages). Close to a wrapper of FastF1's documentation gallery examples. | **MIT** (`LICENSE`, © 2025 SudeshnaPathak). README is empty. | **Ideas only, and minor ones.** All data comes from FastF1 (+ FastF1's Jolpica/Ergast wrapper). |
| **MacManley/gt7-track-visualizer** | GT7 UDP → CSV logger plus three Plotly scripts. Ships **2 raw single-lap recordings** of *fictional* tracks: `tracks/51.csv` Deep Forest and `tracks/793.csv` Lago Maggiore Centre. | **NO LICENSE** (API 404, no LICENSE file), so all rights are reserved. | **No.** Its outlines are in GT7's own world frame, but there are only 2 tracks, they are not reference centrelines, and they are unlicensed. Use **zetetos/gt-telemetry** (MIT, 85 GT7 circuit centrelines in game coordinates) instead. |
| FastF1 (theOehrly/Fast-F1, v3.8.3) | Python client for F1's live-timing archive (2018+), Jolpica-F1, and MultiViewer circuit markers. | Code **MIT**. The *data* is not MIT: F1 claims copyright and database rights over timing data, and the MultiViewer marker data has no published licence. | **Yes, as an optional, user-side fetch** for official corner numbers, reference outlines and reference speed traces for F1-calendar circuits. Never vendor its output. |
| OpenF1 (br-g/openf1) | REST/MQTT/WebSocket API, 2023+, about 3.7 Hz car data. | Repo LICENSE is **CC BY-NC-SA 4.0** (GitHub shows NOASSERTION). "Non-commercial". Live data needs the paid Sponsor tier. | Not needed: FastF1 covers 2018+ with the same feed, and the NC-SA terms are more restrictive. |
| F1DB (f1db/f1db) | Open F1 database with per-layout lap length and turn count, plus circuit SVGs. | **CC BY 4.0** | **Yes**, for the layout gate (lap length, turn count, direction). Requires attribution. |

**Recommendation.** For **F1 25** (and GT7 on real circuits), add an optional "reference overlay" that pitwall builds **on the user's machine** with FastF1. Map it onto the learned lap-distance model by (1) lap-distance fraction, (2) a monotone landmark warp (speed minima plus sector boundaries), and (3) a similarity-transform (Procrustes/ICP) cross-check of the outlines. Assign official numbers by *segment membership*, never by exact metres. Keep pitwall's own `T1..Tn` as the internal key. For **GT7** lap distance, project live X/Z onto a reference centreline in the same frame: from gt-telemetry (MIT) or from pitwall's own learned centreline. gt7-track-visualizer cannot be used for this.

---

## 1. f1livedata.com

**What it is.** The `/about` page describes a free, independent web app "built and maintained by a single motorsport-software enthusiast". It is funded by AdSense and voluntary support, and its Terms are governed by Italian law. Features:
- **Live timing:** lap times, S1–S3, gaps and intervals.
- **Car telemetry:** speed, throttle, brake, gear, RPM and DRS, plotted against track distance for up to 5 drivers.
- **Live track map:** real-time car positions.
- **Strategy and race events:** tyre stints and degradation, pit stops, race control and team radio.
- **Archive:** custom dashboards, an archive of past sessions, and **replays** of recorded sessions.
- **Reference pages:** circuits, teams and seasons, built on **F1DB** (CC BY 4.0). Circuit pages show lap length, turn count, direction, layout history and an SVG outline.

**Data provenance.** `/about` says timing and telemetry "originate from Formula 1's official live data feed", processed in real time. `/terms` §3 calls it "a third-party data feed". It does not say whether it uses FastF1, OpenF1 or its own SignalR client. Its telemetry is its own resampling, at **400 points per lap**: 8.2 m per sample at Monaco and 17.3 m at Spa, per its guide.

**API.** There is **no documented public API.** `robots.txt` describes `/api/` as internal JSON APIs proxied by nginx to FastAPI services, and disallows them. The exception is `/api/f1db/*` (static F1DB records). It also disallows `/bundles/`: replay `.jsonl` session recordings served from Cloudflare R2. These endpoints are technically fetchable, but they are undocumented and blocked for crawlers. Terms §4 forbids scraping, harvesting, systematic extraction or re-publishing "for commercial purposes", and §5 forbids reusing original content without permission. **Do not integrate it.**

**Positions.** The live map shows car x/y, but only through the private API. There is no published way to get geometry.

**Facts worth keeping**, from its "F1 telemetry channels" guide, measured on 2026 data. These apply to any consumer of the F1 feed, including FastF1:
- **Brake is binary.** On a 400-sample Spa pole lap, 369 samples are 0 and 21 are 100. Intermediate values are interpolation artefacts. FastF1 likewise types `Brake` as `bool`. Real data therefore gives **brake onset location and duration only, never trail-brake shape**.
- **DRS reads 0 on every sample in 2026**, because active aero replaced DRS.
- `ngear == 0` means missing, not neutral. Throttle and brake can read 104. Treat values above 100 as full or invalid; FastF1's docs say the same for throttle 104.

---

## 2. SudeshnaPathak/F1_Visualizer

- **Licence:** **MIT** (SPDX `MIT`; `LICENSE` "Copyright (c) 2025 SudeshnaPathak").
- **Activity:** created 2025-02-15, last push 2026-03-13, 30 commits, 1 star. Homepage: `f1-visualizer.streamlit.app`.
- **Stack:** Python and Streamlit 1.42, with FastF1 **3.4.4** (pinned), matplotlib, seaborn, Plotly and pandas.
- **Repo contents:** `Welcome.py` plus 13 `pages/*.py`. It also commits a 72 MB `assets/Skyfall.mp4`, which is likely third-party media and irrelevant. README is a title only.
- **Data source:** **FastF1 only.** `fastf1.get_session(...).load()` for timing and telemetry, and `fastf1.ergast.Ergast` (the Jolpica/Ergast wrapper) for the standings heatmap. No OpenF1, no own data.
- **What it computes** (each page follows FastF1's gallery examples very closely):
  - *Track Map:* fastest-lap X/Y, rotated by `CircuitInfo.rotation`. Corner numbers (`Number`+`Letter`) are drawn offset along each marker's `Angle`.
  - *Speed + Corners:* speed against integrated distance, with dotted verticals at `CircuitInfo.corners['Distance']`.
  - *Speed on Track:* track outline coloured by speed.
  - *Speed Overlay:* two drivers' fastest laps against distance.
  - *Other pages:* gear-shift map, tyre strategies, position changes, lap-time distribution and scatter, team pace, qualifying results, plot styling.
- **Ideas worth re-implementing independently** (all trivial):
  1. Annotate distance-axis traces with official turn labels.
  2. Rotate track maps by the circuit's official-map rotation, so pitwall's web map matches the TV and official orientation.
  3. Speed-coloured track map for the web UI.

  There is nothing novel to borrow, and there is no corner-mapping or cross-frame logic.

---

## 3. MacManley/gt7-track-visualizer

- **Licence:** **NO LICENSE.** `gh api .../license` returns 404, there is no LICENSE file and GitHub reports `license: null`. Default copyright applies, so the code and the CSVs may not be copied or redistributed.
- **Activity:** created 2024-04-18, last push 2024-04-23 (6 commits), 8 stars. The same author's `MacManley/gt7-udp` is MIT, but that does not extend to this repo.
- **What it does:**
  - `gt7_udp_csv_parser.py` sends the heartbeat, decrypts with Salsa20 (pycryptodome) and unpacks the original 296-byte "A" packet. It appends 39 columns to `data.csv` at about 60 Hz.
  - Three Plotly scripts plot every CSV in `data/` as a 3D line (`-posX`, `posZ`, `posY`), optionally coloured by speed or throttle/brake.
- **Data shipped:** the README says samples are in `data/`, but they are in `tracks/`. The CSV columns are elapsed time, flags, car ID, gears, pedals, RPM, speed, tyre temps, `posX/posY/posZ`, rotation, world and angular velocity, road plane, best/last lap and a wall-clock "ongoingLap". There is **no lap distance, no track ID and no corner data.**

| File | Track (README ID table) | Rows | Duration | Rate | X range (m) | Z range (m) | Y (up) range (m) |
|---|---|---|---|---|---|---|---|
| `tracks/51.csv` (3.0 MB) | Deep Forest Raceway (fictional) | 5,622 | 93.8 s | ≈60 Hz | −477…866 | −264…212 | −4…47 |
| `tracks/793.csv` (1.6 MB) | Autodrome Lago Maggiore – Centre (fictional) | 2,900 | 48.4 s | ≈60 Hz | −362…311 | −272…348 | 1…21 |

Both laps were driven in car 3531, a Mercedes-AMG GT3 '20 per the README.

- **Frame:** these are raw packet positions, so they are **in exactly the same GT7 world frame as pitwall's live GT7 telemetry** (metres, Y up). A position could be projected onto them directly, with no registration. However:
  - each file is one driven racing line, not a centreline, and the loop is not closed or cleaned;
  - only **2 tracks** are covered, and neither is a real-world circuit;
  - the files are unlicensed.

  **Conclusion: no value as GT7 reference geometry.**
- **Two small takeaways:**
  1. The plots use **(−X, Z)** as the map plane. GT7's world frame appears mirrored relative to a conventional top-down map, so **any registration against real-world outlines must allow a reflection.**
  2. The README's ~110-entry **track-ID → name table** is factual, but take IDs and names from **ddm999/gt7info `course.csv` (MIT-0)**, which is licensed. GT7 packets carry no track ID, so it must be inferred from geometry (see `gt7-protocol.md` §9).
- **Better GT7 source (already noted in `gt7-repos.md`):** **zetetos/gt-telemetry**, **MIT**, Go, last push 2026-09-14. `data/circuits/` holds **85 circuit JSONs** with a JSON schema. Each has `name`, `variationName`, `default`, `country`, `lengthMetres`, `lastModified`, `coordinates.circuit[]` (x,y,z in GT7 world frame) and `coordinates.startingLine`. For example, `red_bull_ring.json` has `lengthMetres` 4286 and 5,373 points, about 0.8 m spacing.

  Coverage includes the real F1-calendar circuits **Spa, Monza, Suzuka, Red Bull Ring, Interlagos, Barcelona-Catalunya, Yas Marina and Circuit Gilles Villeneuve**, plus Le Mans, the Nürburgring variants, Fuji, Watkins Glen, Road Atlanta, Laguna Seca, Mount Panorama and others.

  MIT requires shipping the copyright and permission notice with any copy. Prefer fetching the files at install or first run, or vendor them with the notice.

---

## 4. Underlying open data sources

### 4.1 FastF1 (`theOehrly/Fast-F1`, MIT, v3.8.3 released 2026-04-29, about 5.4k stars)

- **Where the data comes from:**
  - *Timing and telemetry:* the F1 live-timing static archive, `https://livetiming.formula1.com` (mirror `livetiming-mirror.fastf1.dev`). Available from 2018, usually 30–120 min after a session.
  - *Results and schedule history:* Jolpica-F1 (Ergast successor).
  - *Circuit markers:* the **MultiViewer API**, `https://api.multiviewer.app/api/v1/circuits/{circuit_key}/{year}`.
  - *Live recording:* FastF1's SignalR client now **requires an F1TV Access/Pro/Premium subscription**, per `docs/api_reference/livetiming.rst`. pitwall needs only the historical archive.
- **Telemetry channels** (from the `Telemetry` docstring):
  - *Car data:* `Speed` km/h, `RPM`, `nGear`, `Throttle` 0–100 % (104 means error), `Brake` **bool**, `DRS`.
  - *Position data:* `X/Y/Z` in **1/10 m**, plus `Status` OnTrack/OffTrack.

  Car data and position data are separate streams with their own timestamps. FastF1's accuracy guide says the API sample rate is "about 4-5 Hz" and the data is "somewhat jittery". It warns against computing on interpolated or merged data, and against **integrated distance** (`add_distance()` integrates speed).
- **`Session.get_circuit_info()` → `CircuitInfo`:**
  - `corners`, `marshal_lights` and `marshal_sectors` DataFrames, each with `X, Y` (same 1/10 m frame as position data), `Number`, `Letter` (e.g. "2A"), `Angle` (label-offset direction) and `Distance`.
  - `rotation`, in degrees, to align with the official map.
  - `Distance` is not part of the source data. FastF1 computes it from a loaded reference lap: each marker takes the `Distance` of the nearest **original 'pos' sample**.
  - The docstring warns: *"This data has been manually created and is not highly accurate but sufficient for visualization."*
  - It contains **corner numbers only, not names** such as "Copse" or "Eau Rouge".
- **Coverage for F1 25 track IDs** (pitwall `adapters/f1/enums.py`):
  - **Reference data exists (2018+):** Melbourne, Paul Ricard, Shanghai, Sakhir, Catalunya, Monaco, Montreal, Silverstone, Hockenheim, Hungaroring, Spa, Monza, Singapore, Suzuka, Abu Dhabi, Texas, Brazil, Austria, Sochi, Mexico, Baku, Zandvoort, Imola, Portimão, Jeddah, Miami, Las Vegas and Losail. Madrid (id 42) is covered only if the 2026 event's data is in the archive; verify.
  - **No reference data:** Hanoi (never raced); the short layouts (ids 21–24) unless one matches a raced layout under the layout gate; and the reverse layouts (39–41). Official numbering does not exist for reversed tracks.
  - **Pick the season whose layout matches the game.** F1 25 corresponds to the **2025** layouts and car rules. 2026 data uses different cars (active aero, DRS=0) and should not be used for F1 25 speed priors. Layout changes such as Melbourne 2022, Catalunya 2023 and Singapore 2023 make the year matter; the F1DB per-layout length gate catches mismatches.

### 4.2 OpenF1 (`br-g/openf1`)

- Repo `LICENSE` is **CC BY-NC-SA 4.0**; GitHub reports "NOASSERTION". The openf1.org site content is under the same licence.
- The FAQ says OpenF1 is "intended for educational purposes, personal learning projects, research, and non-commercial fan engagement" and asks other uses to "contact us to discuss appropriate licensing".
- Historical data from **2023** is free with no key: 3 req/s, 30 req/min.
- **Live data requires the Sponsor tier** (€9.90/month). The home page says car telemetry (location, speed, throttle, brake, RPM, gear) is sampled at **3.7 Hz**. Units of x/y/z are not stated on the home page; it is the same F1 feed that FastF1 documents as 1/10 m.
- It describes itself as an unofficial community project, and its footer says it "does not claim ownership of Formula 1 data".
- **For pitwall:** it adds nothing over FastF1 for historical reference laps, has shorter history and more restrictive (NC-SA) terms. Skip it.

### 4.3 MultiViewer (source of FastF1's corner markers)

- A fan-made desktop F1TV client. Its footer says it is "unofficial", "non-commercial, fan-made" and that "Data is used for non-commercial, fair use."
- **No public API documentation, terms or licence for `api.multiviewer.app`** could be found. FastF1 credits MultiViewer "for providing this data to FastF1".
- **Treat the corner coordinates as unlicensed for redistribution.** Fetch them at runtime on the user's machine through FastF1, and do not bake them into pitwall's repo or releases.

### 4.4 F1DB (`f1db/f1db`, CC BY 4.0)

- Per-circuit YAML records direction, lat/long, current `length` (km, 3 dp) and `turns`, plus a `layouts[]` history with length and turns per layout id. For example, Silverstone layout `silverstone-8` (2010–present) is 5.891 km with 18 turns.
- SVG outlines come in 4 styles. They are schematic, so don't use them for metric registration.
- **Use it for the layout gate and for "expected number of official turns"**, with attribution.

---

## 5. Legal position: be precise, don't overstate (not legal advice)

1. **Formula 1's own terms.** The formula1.com Legal Notices say materials on the site, "including, but not limited to live timing data, historical race data", "are protected by copyrights, database rights, trademarks and/or other intellectual property rights". They also say site material "is for your personal, non-commercial use only". The F1 App terms add a prohibition on using the app "in an automated manner" that could impair services. The live-timing endpoints FastF1 reads are not a licensed public API; FastF1, OpenF1, MultiViewer and f1livedata all describe themselves as **unofficial** and (except FastF1, which does not address it) non-commercial. Where the EU/UK *sui generis* database right applies, systematic extraction can be restricted even when individual facts are not copyrightable.
2. **Code licences are not data licences.** FastF1's MIT licence covers FastF1's code only. Data it downloads stays under F1's terms, and the MultiViewer markers come with no published licence. F1_Visualizer's MIT licence is likewise irrelevant to the data.
3. **Trademarks.** "F1", "FORMULA 1" and related marks belong to Formula One Licensing B.V. pitwall should not use them in branding. Descriptive use plus the standard "unofficial, not associated" notice is what every project above does.
4. **Facts versus compilations.** A turn number, a lap length or a corner name is a fact. A curated compilation of corner coordinates (MultiViewer) or a timing database can still carry rights. Hand-authoring our own per-track tables of turn number to pitwall corner, made from our own F1 25 laps and public track maps, is the cleanest option.
5. **Practical policy for pitwall:**
   - make FastF1 an **optional extra** (`pitwall[f1ref]`);
   - fetch on the **user's machine** for the user's personal use, and cache under the user data dir;
   - **never commit or redistribute** FastF1-derived files (outlines, corner XY, speed traces) in the repo, tests or releases;
   - label the overlay as unofficial reference data;
   - if pitwall ever becomes a commercial product, this path needs a data licence from FOM, or must be dropped in favour of hand-curated tables.

   CC BY 4.0 (F1DB), MIT (gt-telemetry) and MIT-0 (gt7info) data can be shipped with attribution. gt7-track-visualizer (no licence) cannot.

---

## 6. Engineering: mapping real-world references onto pitwall's lap-distance model

### 6.1 Frames and units

| Source | Plane | Units | Distance coordinate | Origin of distance |
|---|---|---|---|---|
| FastF1 position | X/Y (Z = altitude) | **dm** (÷10 → m) | `Distance` integrated from speed (drifts, up to ~1 %) | lap-start timing-line crossing (interpolated) |
| FastF1 `CircuitInfo` | X/Y, same frame | dm | nearest original 'pos' sample of the reference lap | same |
| F1 25 UDP | `m_worldPositionX/Z` (Y up) | m | `m_lapDistance` (game-computed; negative before the line) | game S/F line; `m_trackLength` (m) given; `m_sector2/3LapDistanceStart` (m) given |
| GT7 UDP | X/Z (Y up) | m | **none**; must be derived | n/a |
| gt-telemetry circuits | x/z (y up), same frame as GT7 UDP | m | arc length of `circuit[]` | `startingLine` |
| pitwall `TrackModel` | (`pos_x_m`, `pos_z_m`) every 5 m | m | `length_m` grid | game's line |

The real and game frames differ by an unknown **rotation, translation, scale (≈0.1 after the dm conversion) and possibly a reflection**. Distance origins can differ by a constant, and integrated real distances by a ≤1–2 % scale.

### 6.2 Step 0: layout gate (reject before mapping)

- Same track variant: no reverse or short layouts.
- `|L_game − L_F1DB(layout,year)| / L_F1DB < 1.5 %`.
- After registration (step 3), scale within 1.00 ± 0.03 and residual below the threshold.
- Optionally, F1DB `turns` equals the count of FastF1 corners with distinct numbers.

If any check fails, store nothing and fall back to the learned-only model.

### 6.3 Pipeline for F1 25 (lap distance available on both sides)

The **reference artefact** is built once per (circuit, season) on the user's machine with FastF1 and cached as about 50 KB of JSON:
- `L_ref`;
- `outline[]` (x, y, z in m, plus s_frac) from the fastest qualifying lap's **original pos samples**;
- `corners[]` (number, letter, x, y, s_frac), with markers re-projected onto the outline polyline rather than snapped to the nearest 4 Hz sample;
- `speed(s_frac)` from original car samples;
- `brake_onsets[]`: brake False→True transitions, with ± half a sample interval as uncertainty;
- real **sector boundaries** as s_frac, from `Sector1SessionTime`/`Sector2SessionTime` interpolated into the lap's position and time;
- provenance: year, session, driver, FastF1 version, and an "unofficial" flag.

1. **Coarse alignment by fraction.** `s = d / L` on both sides. This is accurate to roughly 0.5–2 % of a lap (25–120 m), from origin offsets, integration drift and line choice. It is enough to tell T1 from T5, not enough for chicanes.
2. **Monotone landmark warp (main step).**
   - **Landmarks.** On the reference side, take reference speed minima (same detector as `build_track_model`, using the same km/h prominence) plus S1/S2 and S2/S3 boundaries. On the game side, take pitwall corners' `apex_m` plus F1 25's `m_sector2/3LapDistanceStart`.
   - **Alignment.** Match the two landmark sequences with an order-preserving dynamic-programming alignment that allows gaps, like sequence alignment. The cost is `|Δs|·L + α·|Δv_min|/v_scale`, with a gap penalty; sector boundaries are forced matches. Corner order is fixed and the lap is cyclic, so this is O(n·m) and robust: an extra or missing minimum costs one gap and does not shift the rest.
   - **Warp.** Fit a piecewise-linear monotone map `w: s_ref → d_game` through the matched pairs, anchored at 0 → 0 and 1 → `L_game`.
   - **Alternative.** DTW on z-normalised speed profiles within a ±3 % Sakoe-Chiba band does the same job, but is less explainable and more sensitive to the F1 25 car versus real car speed difference. Use it only as a fallback when fewer than 4 landmarks match.
3. **Geometric cross-check (shape registration).**
   - Take correspondences from step 2: about 500 points at equal warped arc length on the reference outline and on pitwall's centreline.
   - Fit a closed-form **similarity transform with reflection allowed** (Umeyama/Procrustes via SVD). Try det = +1 and det = −1 and keep the lower residual.
   - Refine with 3–5 point-to-line ICP iterations, restricted to a ±50 m arc-length window so it cannot jump across nearby track sections (Suzuka's crossover, Monaco's harbour).
   - Optionally add elevation as a third dimension: real Z/10 against game Y, after removing the mean, gives a strong check at Spa, COTA and Suzuka.
   - **Gate:** scale 1.00 ± 0.03, RMS ≤ 12 m, 95th percentile ≤ 25 m. Then project each official corner's XY through the transform onto pitwall's centreline to get `d_geo`.
4. **Reconcile.** For each official corner, compare `d_warp = w(s_ref)` with `d_geo`:
   - if they agree within 30 m, accept `d_official = mean`;
   - otherwise mark the corner "uncertain": keep it in the overlay, but don't voice its name.
5. **Label assignment by segment membership, not nearest metre.**
   - Each official corner goes to the pitwall corner whose `[seg_start_m, seg_end_m)` contains `d_official`.
   - **Several official corners can map to one pitwall corner.** Chicanes and esses merge under the 60 m spacing rule; for example, Silverstone's Maggotts–Becketts–Chapel complex would become one or two pitwall corners carrying several labels. Display them as "Turns 10–11".
   - Official turns that contain no speed minimum (flat kinks) become **markers** with only `d_official`. They are useful for speech ("flat through Turn 7"), but no corner analysis runs on them.
   - Pitwall corners left without a label keep `Tn` and are spoken by distance.
   - Corner names ("Copse") come from a **hand-curated per-track YAML** keyed by official number, because FastF1, OpenF1 and F1DB carry none.
6. **Re-run on every model version.** When `build_track_model` produces a new version, re-map it. The overlay records the `TrackModel.version` it was mapped against.

### 6.4 Pre-seeding before any clean lap (F1 25)

F1 25 sends `m_trackLength` and `m_lapDistance` from the first packet. A **provisional model (version 0, `source="reference"`)** can therefore be created immediately:
- corner apexes at `s_ref·L_game`, with official labels;
- entry and exit from the reference speed and brake-onset trace, scaled the same way;
- no centreline; or the reference outline transformed later, once the first partial lap provides positions for step 3.

Use it for **naming and coarse "which corner" coaching only.** Real-car speeds and brake points are not F1 25 car or assist targets. The binary brake channel at about 4 Hz gives onsets only to about ±(v·Δt/2), roughly ±10 m at 300 km/h. When the first learned model is built, it **replaces** v0 and the full pipeline re-maps the labels. Learned per-car references remain the only source of braking targets.

### 6.5 Expected accuracy (estimates to be validated, see 6.8)

| Quantity | Expected error | Dominant cause |
|---|---|---|
| Fraction-only corner position | 25–120 m (0.5–2 % of lap) | origin offset, FastF1 integrated-distance drift, line differences |
| Landmark-warp apex position | ±5–15 m in slow and medium corners; ±15–25 m in fast sweeps | ~4 Hz FastF1 sampling (≈6 m at 80 km/h, ≈20 m at 300 km/h between samples), apex-minimum flatness, pitwall 1 m grid and 5 m centreline |
| Shape-registration residual (RMS) | 3–8 m on faithfully modelled circuits; >12 m means a layout mismatch | racing line vs racing line lateral offset (±5 m), feed jitter, game modelling differences |
| Official **marker** position itself | ±10–30 m | MultiViewer markers are hand-placed for display ("not highly accurate") at an arbitrary point of the corner |
| **Official label identity** | Correct for all corners that have a speed minimum, once the gates pass. Complexes under ~60 m become multi-label (by design). | Segment-membership assignment absorbs the ±30 m marker error |
| Reference brake-onset location | ±10–20 m | binary brake at ~4 Hz |

The design choice that matters: **official data supplies identity, not position.** All positional coaching keeps using pitwall's learned apex, entry and exit distances.

### 6.6 GT7

- **Lap distance.** GT7 has no lap-distance field. Derive it by projecting live (X, Z), plus Y to disambiguate crossovers, onto a centreline **in the same GT7 world frame**:
  - before any lap, use gt-telemetry's circuit (MIT; ≈0.8 m spacing, `startingLine` gives s = 0);
  - after clean laps, use pitwall's own learned centreline.

  Use a windowed search around the previous projection (±100 m) and wrap at `lengthMetres`. Expected error is ≤1–2 m along track at 60 Hz, with lateral offset irrelevant. **No registration is needed, because the frames are identical.** The same would hold for gt7-track-visualizer's CSVs, but they cover only two fictional tracks and are unlicensed.
- **Track identification.** Match the first few hundred metres of positions against all candidate centrelines by nearest-distance RMS, or use the start-line-crossing approach described in `gt7-protocol.md`. Names come from gt7info `course.csv` (MIT-0).
- **Official corner numbers on real circuits.** This covers Spa, Monza, Suzuka, Red Bull Ring, Interlagos, Barcelona, Yas Marina and CGV. Run §6.3 steps 3–5 with the FastF1 outline against the GT7 centreline:
  - **reflection must be allowed** (GT7 maps are drawn as −X/Z);
  - the distance origin is GT7's `startingLine`, which can differ from F1's timing line, so estimate a cyclic offset from the registration;
  - choose a FastF1 year whose layout matches the GT7 variant: for example, GT7 "Barcelona GP Layout" against "No Chicane", or Spa F1 against the 24h layout.

  **Do not use real F1 speed or brake traces as GT7 priors.** The cars are too different; use only the step-2 landmark warp after pitwall has its own laps. For fictional GT7 tracks, corners stay `T1..Tn`. Hand-curated names are optional.

### 6.7 Data-model sketch (for a later ADR)

- Add a separate, versioned `TrackReference` record keyed by `(game, track_id)` and mapped against a specific `TrackModel.version`. It holds:
  - `provenance`: source, season, session, FastF1 version, licence note, `unofficial=True`;
  - `official_corners[]`: number, letter, name?, `d_official`, `uncertain`, `pitwall_corner`;
  - `markers[]` for flat turns;
  - the fit diagnostics: scale, RMS, p95, reflection, warp anchors.
- Don't mutate `Corner`; the coach and facts layer join on `pitwall_corner`. This keeps the learned model authoritative and the overlay disposable.

### 6.8 Validation plan

1. **Ground truth.** Hand-label official turn numbers on pitwall models for 3 circuits with different difficulties: Monza (few, well-separated corners), Silverstone (fast complexes) and Monaco (dense, slow, tunnel). Use our own F1 25 laps and the public official track maps.
2. **Metrics.** Label accuracy, |`d_official` − hand label|, registration scale, RMS and p95, and how often the gate rejects.
3. **Negative tests.** Feed a wrong-year layout (Catalunya 2022 against the game's post-2023 layout) and a reverse layout. Both must be rejected by the gate.
4. **GT7.** Check the projection-derived lap distance against the integrated speed × dt distance on our own captures. Check track ID on a crossover circuit (Suzuka).

---

## 7. Recommendations

1. **Do not use f1livedata.com or gt7-track-visualizer as data sources.** The first has no public API, robots-disallowed internal endpoints and restrictive terms. The second has no licence and only 2 fictional tracks. Neither is needed.
2. **F1_Visualizer:** nothing to adopt beyond UI ideas: turn labels on distance traces, official-map rotation and a speed-coloured map.
3. **Add an optional FastF1-based reference overlay** for F1 25, and for GT7 on the overlapping real circuits:
   - user-side fetch and cache, never vendored;
   - mapping as in §6.3: fraction, then landmark warp, then Procrustes/ICP cross-check, then segment-membership labels;
   - gated by the F1DB layout check.
4. **GT7 lap distance:** adopt gt-telemetry (MIT) centrelines with attribution for pre-seeding and track ID, and switch to pitwall's learned centreline once available.
5. **Corner names:** hand-curate small per-track YAMLs keyed by official number. They are pitwall's own work and freely shippable.

## 8. Open questions

- Does F1 25's `m_lapDistance` origin coincide with F1's timing line on every circuit? The warp absorbs a constant offset, but it should be logged.
- Are F1 25's `m_sector2/3LapDistanceStart` the real sector boundaries? If not, downgrade them from forced to soft landmarks.
- Is the F1 25 world frame mirrored relative to real-world X/Y? The registration handles both cases; record the result per track.
- Does the Madrid 2026 event exist in the FastF1 archive and match the F1 25 Season Pack layout?
- Do GT7 world coordinates for a given course stay stable across game updates? gt-telemetry's `lastModified` dates suggest they are re-captured; re-validate them periodically.

## Sources

- f1livedata.com: https://f1livedata.com/ , https://f1livedata.com/robots.txt , https://f1livedata.com/terms , https://f1livedata.com/about , https://f1livedata.com/f1-telemetry-explained/ , https://f1livedata.com/circuit/silverstone
- https://github.com/SudeshnaPathak/F1_Visualizer (LICENSE, requirements.txt, pages/*.py)
- https://github.com/MacManley/gt7-track-visualizer (README.md, gt7_udp_csv_parser.py, tracks/51.csv, tracks/793.csv)
- FastF1: https://github.com/theOehrly/Fast-F1 (README "Notice"; `fastf1/mvapi/data.py` CircuitInfo docstring; `fastf1/mvapi/api.py`; `fastf1/core.py` Telemetry docstring; `fastf1/_api.py`; `docs/data_reference/howto_accurate_calculations.rst`; `docs/data_reference/index.rst`; `docs/api_reference/livetiming.rst`)
- OpenF1: https://openf1.org/ ; https://github.com/br-g/openf1 (LICENSE: CC BY-NC-SA 4.0)
- MultiViewer: https://multiviewer.app/
- Formula 1 Legal Notices: https://www.formula1.com/en/information/legal-notices.7egvZU48hzrypubGBNcQKt
- F1DB: https://github.com/f1db/f1db (CC BY 4.0; `src/data/circuits/silverstone.yml`)
- zetetos/gt-telemetry: https://github.com/zetetos/gt-telemetry (MIT; `data/circuits/`, `data/circuits/schema/circuit-schema.json`)
- ddm999/gt7info: https://github.com/ddm999/gt7info (MIT-0)
- pitwall internal: `src/pitwall/analysis/track.py`, `src/pitwall/adapters/f1/enums.py`, `docs/research/f1-udp-spec.md`, `docs/research/gt7-protocol.md`, `docs/research/gt7-repos.md`
