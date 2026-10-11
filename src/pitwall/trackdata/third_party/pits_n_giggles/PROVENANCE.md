# Provenance: Pits n' Giggles `assets/track-segments`

| | |
|---|---|
| Upstream | https://github.com/ashwin-nat/pits-n-giggles |
| Path | `assets/track-segments/` (data files only; no code is vendored) |
| Pinned commit | `72f78aaf19910cea0aaa302cf69905daa6f331f4` ("Harden track segment data: validated TrackSegmentsClassifier and missing corners (#345)", committed 2026-10-10T13:21:55Z), the head of the `release-v5.0.0` branch (there is no v5 tag yet) |
| Previous pin | `3490db9e3c4fe1031d51b6749f206695c3b06687` ("Hotfix v4.4.2 (#336)", 2026-09-21, the head of `main` when first vendored). `72f78aaf` is 25 commits ahead of it and changes exactly 5 of the 28 files, all fixes: Melbourne (renumbered to the 2022+ layout, 1-14), Montreal (duplicate turn 5 and missing turn 11 fixed, Wall of Champions now 13-14), Baku (turns 13-14 added), Las Vegas and Singapore (missing corners added). Upstream PRs #343 and #345. `main` does **not** carry these fixes, which is why the pin follows the release branch (`docs/research/track-knowledge-sources.md` section 1, item 3, Action 1) |
| Latest commit touching the path | on `release-v5.0.0`: `72f78aaf` (the pin); on `main`: `3490db9` (both checked 2026-10-10 with `gh api repos/ashwin-nat/pits-n-giggles/commits?path=assets/track-segments&sha=<branch>`) |
| Fetched | 3490db9: 2026-10-10. The 5 changed files at 72f78aaf: 2026-10-10, with `gh api -H "Accept: application/vnd.github.raw" repos/ashwin-nat/pits-n-giggles/contents/<path>?ref=72f78aaf19910cea0aaa302cf69905daa6f331f4`. The other 23 files and `LICENSE` have the same blob SHA-1 at both commits (GitHub contents API listing at 72f78aaf), so they were not re-fetched |
| Licence | MIT. GitHub's licence detection reports `MIT`; the `LICENSE` file was read in full and is the standard MIT text; its blob is identical at both commits |
| Copyright line | `Copyright (c) [2024] [Ashwin Natarajan]` (the square brackets are literal in the upstream file, left from the licence template) |
| Modifications | none: files are byte-identical to upstream (git blob SHA-1s below match the GitHub tree at the pinned commit) |
| Squash-merge risk | if upstream squash-merges `release-v5.0.0`, `72f78aaf` may become unreachable on GitHub; the vendored copy and the SHA-1s below remain the record |

`LICENSE` in this directory is the upstream file, byte-identical (blob `8d23eef7c81cc358ae7e6d4b33186cc6704fa5b8`).
The MIT notice must ship with these files and with anything substantially derived from them (the seeded
track sheets in `src/pitwall/trackdata/track_sheets/f1/` say so in their header).

## Files

| File | Git blob SHA-1 at the pin | F1 track id |
|---|---|---|
| `Abu_Dhabi.json` | `a20206d76f9741ffd2aaaea02bcd469837c1ef3c` | 14 |
| `Austria.json` | `be0496329e4d7b1ef7c1c6cd09f7e6c20897821a` | 17 |
| `Austria_Reverse.json` | `ba1e5b765829788fe525f67929e12f1a9441385c` | 40 |
| `Baku_Azerbaijan.json` | `ce094f535f24a2ee891e44ee4c70ba03fd397871` | 20 |
| `Brazil.json` | `bb751f0abecb6865610ac263092a736363ebff0f` | 16 |
| `Catalunya.json` | `7e9792f69d6f3608e77a9525bc8ed0d80a65483b` | 4 |
| `Hungaroring.json` | `01cd8664feab52252b0bbd5aebc816d6bff5110d` | 9 |
| `Imola.json` | `e333e0a951fbfe2e31172dd221fb5db7d3478d1e` | 27 |
| `Jeddah.json` | `e2a1ed91331bda4e6729d8bfda527d0052eafc8b` | 29 |
| `Las_Vegas.json` | `49ea26d4855a7b59cacbf7d4a260f9f0e575a1fb` | 31 |
| `Lusail.json` | `e17cac2e2d05c2bf4b5aa2dd9db492351e460848` | 32 |
| `Madrid.json` | `234002e19883ff789c9260442e3c37358684d18e` | 42 |
| `Melbourne.json` | `bfa2a057b35d0de3271173b90e429eaf787efa7c` | 0 |
| `Mexico.json` | `eb5a8290835ed59c066ad3c8a53fe5eb1807666f` | 19 |
| `Miami.json` | `aed3805458df6eea8c771ab56593e0c27ce19bb9` | 30 |
| `Monaco.json` | `c59f78e330d36a5722e52acbaa804fdf5c4e08aa` | 5 |
| `Montreal.json` | `5489e1ae17303d9d60ed8a173c0dc031c84b9611` | 6 |
| `Monza.json` | `65f9c8f76fbd9954ec865747241930dfbb32ee46` | 11 |
| `Sakhir_Bahrain.json` | `5c1e70fb7470c9ecc4ee7ecf47be5609a9d6821e` | 3 |
| `Shanghai.json` | `9459be907628f832f2dd8c03d130ffd6803678c9` | 2 |
| `Silverstone.json` | `96badd7e91df3a03167fa442ad51a1fe0c8ca5b3` | 7 |
| `Silverstone_Reverse.json` | `ef578eb0e83a8d46181b38c0fd7a377084af4e63` | 39 |
| `Singapore.json` | `ff07b7bbec7e0775dbcd297830a35a49c8238584` | 12 |
| `Spa.json` | `14ea221ccaf4b8325d7e748bf65ff211ec2d4853` | 10 |
| `Suzuka.json` | `b6af5f461380b953a00ef6b877e80e82f4a4d21c` | 13 |
| `Texas.json` | `cb032121b26d214c8ccc8e6729a47279822486e4` | 15 |
| `Zandvoort.json` | `9c9f57fb422ea7ac3de97ecde23e67ce7700b4b8` | 26 |
| `Zandvoort_Reverse.json` | `14ee1dad82ff49029fa1c3bf724b6bafd1dab9f2` | 41 |

Verify: `git hash-object track-segments/<file>` must print the SHA-1 above (the unit tests check this).

## What pitwall uses them for

- **Seed only.** `scripts/import_track_segments.py` (dev-only) turns each file into a pitwall track sheet
  (`track_sheets/f1/<id>_<slug>.toml`): official turn numbers, complex grouping, corner names and corner windows in
  F1 game lap-distance metres. Straights, PnG's reverse-layout numbering and generic numbered names are not used.
- **Not read at runtime.** The app reads only the track sheets (`pitwall.analysis.track_identity`). The JSON ships
  as the provenance record of the seed and so the MIT notice travels with it.
- **Identity, never positions.** Windows only decide which official turn a *learned* corner belongs to; apex,
  braking and every coaching position still come from the driver's own laps.

## Known data issues (pitwall's import and the research audit, 2026-10-10)

- Fixed by the re-pin to `72f78aaf`: Montreal's duplicate turn 5 / missing turn 11 / Wall of Champions numbered
  12-13 (now 13-14), Melbourne's pre-2022 numbering 1-16 (Ascari was turn 13, now 11), Baku's missing turns 13-14,
  and missing corners at Las Vegas and Singapore.
- Still open at the pin (`docs/research/track-knowledge-sources.md` section 1, item 3, Action 2): Monaco turns
  17-19 mislabelled and `track_length` 3067 truncated; Baku turns 17-20 (flat kinks) missing; Suzuka turn 18
  folded into the pit straight. Mexico's 4525 m is probably F1 25's own `m_trackLength` (real circuit 4304 m);
  neither Monaco nor Mexico has been checked against a capture. The identity length gate refuses a sheet whose
  length differs from the game's by more than 1.5 %.
- Reverse layouts (ids 39-41) carry numbering that does not exist officially, and their windows look like mirrored
  forward windows offset by about 40 m.
- Austria (id 17) was checked against a real F1 25 capture: `track_length` 4323 m and the sector values
  (1204 / 2935 m) equal the game's Session packet (4323 m; 1203.96 / 2934.93 m), and every learned speed minimum
  falls in the expected window. See `track_sheets/f1/17_austria.toml` (reviewed against the 3490db9 copy, whose
  `Austria.json` blob is identical at `72f78aaf`).
- Every seeded sheet is unreviewed. The runtime attaches only hand-verified turns by default
  (`track_identity.identify(min_tier="sheet_verified")`), so seeded numbers and names are never shown or spoken
  as fact.

## Open question: review before any commercial release

The windows and sector values were evidently measured from F1 game telemetry (they match the game's own
Session-packet values), and the authoring method is undocumented upstream. MIT covers only the author's rights.
Whether Electronic Arts could claim tables recorded from its game under the EA User Agreement section 2 ("may not
... copy, modify or distribute any EA Service, Content") has **not been assessed**
(`docs/research/track-knowledge-sources.md` section 7.6, question 1). Corner numbers and names themselves are
real-world facts. **Review before any commercial release**; the fallback is to stop shipping these files and the
segment windows derived from them (keep numbers and names, re-derive windows from field-observed or user data).

---

# Provenance: Pits n' Giggles `assets/track-maps/f1_2025` (outline prior, layer L1a)

| | |
|---|---|
| Upstream | https://github.com/ashwin-nat/pits-n-giggles |
| Path | `assets/track-maps/f1_2025/` vendored as `track-maps/f1_2025/` (27 SVG outlines + `svg_transforms.json`; data only, no code) |
| Pinned commit | `72f78aaf19910cea0aaa302cf69905daa6f331f4`, the same pin as `track-segments` above (head of `release-v5.0.0`) |
| Latest commit touching the path | `13c30d7dbfc33e413316c0fe3b5ed747e6b2cbc1` ("Release v4.0.0 (#259)", 2026-04-25T15:56:43Z) on **both** `release-v5.0.0` and `main` (checked 2026-10-11 with `gh api repos/ashwin-nat/pits-n-giggles/commits?path=assets/track-maps/f1_2025&sha=<branch>`). The GitHub contents API lists identical names and blob SHA-1s at `13c30d7` and `72f78aaf`, so the research doc's `13c30d7` pin and this one are the same bytes |
| Fetched | 2026-10-11, each file with `gh api -H "Accept: application/vnd.github.raw" repos/ashwin-nat/pits-n-giggles/contents/assets/track-maps/f1_2025/<file>?ref=72f78aaf19910cea0aaa302cf69905daa6f331f4` |
| Licence | MIT, the repository `LICENSE` in this directory (blob `8d23eef7c81cc358ae7e6d4b33186cc6704fa5b8`, identical at both commits). `Copyright (c) [2024] [Ashwin Natarajan]` |
| Modifications | none: every file is byte-identical to upstream (git blob SHA-1s below match the GitHub listing at the pin) |
| Not vendored | `assets/track-maps/f1_2023`, `f1_2024` (other games); any upstream code (`apps/dev_tools/generate_track_map.py`, `regenerate_svgs.py`, `apps/frontend/js/trackMap.js` were read only to confirm the documented transform convention `svgX = a*worldX + b*worldZ + c`, `svgY = d*worldX + e*worldZ + f`) |

## Files (track-maps)

| File | Git blob SHA-1 at the pin | F1 track id |
|---|---|---|
| `f1_2025/Abu_Dhabi.svg` | `1652a49c55e19fafd63101c5addbc18e760f9ce9` | 14 |
| `f1_2025/Austria.svg` | `85b5da6038c3ae6b62944171650a983ffcf0f65f` | 17 |
| `f1_2025/Austria_Reverse.svg` | `06d960c0d1960f31a1c63cc9f7da5ac9ab555858` | 40 |
| `f1_2025/Baku_Azerbaijan.svg` | `0d1341ff3a4bb7253862a76256dd29d76b284fb4` | 20 |
| `f1_2025/Brazil.svg` | `c6734fdd410a9607305f82d88d8e7399d7553a74` | 16 |
| `f1_2025/Catalunya.svg` | `13cf2eb674ed4deffbd02d3d1405b418775e75e1` | 4 |
| `f1_2025/Hungaroring.svg` | `a7feb8b6e417ee15ff0f01d88bd7efc235a8d80a` | 9 |
| `f1_2025/Imola.svg` | `a05eb18bfd1036df5ac8a53ea7ead2fffe46c6a0` | 27 |
| `f1_2025/Jeddah.svg` | `3ae7deb2b39a35b1bcf9f963c7bccbdabd61e4ab` | 29 |
| `f1_2025/Las_Vegas.svg` | `47d1de9a83a94fcd22a3bef86813aed8837154b0` | 31 |
| `f1_2025/Losail.svg` | `7848e7d93cd71d8b4fb52c809f893023717bdc9f` | 32 |
| `f1_2025/Melbourne.svg` | `4c774ce70fc0663040722de03f3cd12f478aa592` | 0 |
| `f1_2025/Mexico.svg` | `b1a4aba47e3db17d69fbacc4c42c33af1d117394` | 19 |
| `f1_2025/Miami.svg` | `268d3af69e0c27d98f32ff331a93a68b140d8d11` | 30 |
| `f1_2025/Monaco.svg` | `9fd8c49ff6eddda276c0b904e13ee3e3a6db4492` | 5 |
| `f1_2025/Montreal.svg` | `e58afac58b6939ae5d483bf46ccd7aee1bbc851b` | 6 |
| `f1_2025/Monza.svg` | `a7bbb363aae04f0a6607bd503e78f032adb7032e` | 11 |
| `f1_2025/Sakhir_Bahrain.svg` | `6bb741dc8c650040746e2f7d536545334061f7ec` | 3 |
| `f1_2025/Shanghai.svg` | `f827eab4a56470c8dc0604b1b9c3d3c42080df71` | 2 |
| `f1_2025/Silverstone.svg` | `44f4ef4865fd531022c7fb1cff1f9556612fdad5` | 7 |
| `f1_2025/Silverstone_Reverse.svg` | `26af6b9125214967b79bee450336e50682aa44c7` | 39 |
| `f1_2025/Singapore.svg` | `db689ca80030555dd0da12615f6b57262cc9c3eb` | 12 |
| `f1_2025/Spa.svg` | `2161166f57cc03e42b1583ecb1d51650496d6765` | 10 |
| `f1_2025/Suzuka.svg` | `4d392d15299d5d9ed5a7da1370ddecb255d3a4ef` | 13 |
| `f1_2025/Texas.svg` | `5b4596809ccfda24945bd018fb5aa9bc4e5d007f` | 15 |
| `f1_2025/Zandvoort.svg` | `bd683bccdade8c6d13713aa43950517104182bd7` | 26 |
| `f1_2025/Zandvoort_Reverse.svg` | `5928bc38eb2f8baf0918fc093685d6d8cd014ba4` | 41 |
| `f1_2025/svg_transforms.json` | `182e71ea901f1550e8f4b459fe6e43269b820562` | all 27 |

Madrid (42) has no outline at the pin. Verify: `git hash-object track-maps/<file>` must print the SHA-1 above (the unit
tests in `tests/unit/test_track_geometry.py` check this).

## What pitwall uses the outlines for

- **Read at runtime** by `pitwall.analysis.track_geometry` (stdlib XML only; the per-track affine is inverted in
  pitwall's own code). Each SVG polyline is 800 knots plus a closing duplicate: the mean world X/Z of the field per
  lap-distance bin. Knot *i* maps to game lap distance (*i* + 0.5) x `m_trackLength` / 800.
- **Dashboard (tier `shipped_seed`):** a dashed map labelled "game outline (Pits n' Giggles)" before pitwall has
  learned the track from the driver's laps. Never the driver's line and never a target.
- **Physics prior (tier `physics_predicted`, `pitwall.analysis.brake_prior`):** curvature for pitwall's own QSS
  solver, which yields "heavy stop ahead" heads-up windows. Every position is an `est_*` estimate, never a braking
  point; the window starts a 100 m margin before the estimated onset.
- **Measured on pitwall's own PS5 F1 25 captures (2026-10-10/11, 10 layouts incl. Miami and Melbourne, 23 clean
  laps):** the inverted outline lies a median 0.5-1.2 m from the driver's clean laps (RMS 1.0-7.5 m; the larger values
  are laps with offs), and the index mapping agrees with the game's lap distance to a median +1.0 to +1.3 m (p05-p95
  +0.1 to +1.9 m). The axis convention is F1's `m_worldPositionX/Z` = pitwall's `pos_x_m` / `pos_z_m` unchanged; the
  three alternatives sit 67-86 m away.
- **Physics prior onset error, same captures (19 clean flying laps, 75 stops; `brake_prior.ONSET_EVIDENCE`):** the
  estimate is later than the driver's first brake application (`brake_prior.driver_onset`: the first application of
  the braking chain that holds the stop's minimum) at 81 % of stops, median +18 m, **p90 |error| 70 m**, worst +148 m
  late and -88 m early; Monza T1-2 on a clean lap is +88 m (driver at 718 m from 337 km/h, estimate 806 m). The 100 m
  window margin covers 72 of 75 stops; the other three are adjacent-corner chains the solve takes flat (Suzuka T1 ->
  T2 twice, Silverstone Reverse). The research section 5.3 calibrated envelope gives p90 62 m. An earlier figure of
  "p90 42 m, +/-45 m" matched some stops to the wrong (nearest) minimum and is withdrawn. Committed recorded check:
  `tests/fixtures/recorded/f1_25_2025_ps5_monza_race-excerpt.pwcap` (lap 3, 560-2250 m).

## Known data issues (track-maps)

- Monaco's outline is 1.061 x the seeded `track_length` 3067 m (which is truncated); pitwall's length gate refuses it
  unless the session supplies the game's `m_trackLength` (probably about 3323 m; unverified).
- The F1 world X/Z plane is mirrored relative to a plot with +X right and +Z up: positive heading-derivative
  curvature is a left turn (checked against every hand-verified turn direction of the Austria, Austria Reverse,
  Monza and Silverstone sheets and the driver's steering at Austria). Upstream's SVGs are drawn unmirrored.
- Whether the 2026 Season Pack changed any geometry is unverified beyond Bahrain (research section 2, "L1a").

## Open question for the outlines: review before any commercial release

The outlines are recorded F1 25 telemetry output (the field's mean line), so the EA User Agreement section 2 question
above applies to them too (`docs/research/track-knowledge-sources.md` section 7.6, question 1): MIT covers only the
author's rights. **Review before any commercial release**; the fallback is a user-side fetch at first run instead of
shipping these files (pitwall's own code and the physics prior would be unchanged).
