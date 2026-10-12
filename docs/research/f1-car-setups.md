# F1 25 car setups per track (2025 cars and 2026 Season Pack cars)

_Researched 2026-10-10 for cloud task 8. Data: `src/pitwall/carsetup/data/f1_25_setups.json` (the evidence below:
ranges, parameters, sources, cited setups, rules; the recommendations are built from it when it is loaded, by
`pitwall.carsetup.build`, and validated). Code: `src/pitwall/carsetup/`._

**Evidence tier.** Everything here is published community/press data plus pitwall's own reading of it. Pitwall
has not tested any of these setups in the game. The only real-game evidence is the recorded PS5 capture
(`tests/fixtures/recorded/f1_25_2025_ps5_austria_race-excerpt.pwcap`): both setups it contains fit every
confirmed menu range below (`tests/recorded/test_carsetup_real.py`).

## 1. Two car formats, never mixed

The 2026 Season Pack (launched 2026-06-03) adds 2026-regulation cars to F1 25. EA's UDP spec calls them "F1 26"
(Session `m_formula` 13). Pitwall keeps two car formats with their own ranges, setups and recommendations:
`f1_2025` (base-game cars: Career, Grand Prix, Time Trial, F1 World generic car, Braking Point teams) and
`f1_2026` (Season Pack cars). A 2025 setup is never shown for a 2026 car, and the reverse.

How a stored session maps to a car format (`carsetup/context.py`):

| Evidence | Car format |
|---|---|
| formula "F1 26", or team id 476-486 (format 2026 only) | `f1_2026` |
| UDP format 2026 with any other F1 formula / team | `f1_2025` (format 2026 reports 2026 cars as F1 26) |
| UDP format 2025 with a real 2025 team id (0-9) | `f1_2025` (2026 teams do not fit the 2025 field; F1Laps reports 2026 cars in format 2025 as "F1 Generic") |
| generic car (team 41 / 104) or unknown team in format 2025 | **unknown**: the driver picks (the real PS5 capture is this case: F1 World, "F1 Generic") |
| F2 (formula "F2", or the F2 team ids; `pitwall.carclass`) | `f2`, see [section 11](#11-f2-cars) |
| F1 Classic, Beta | no catalogue |

Sessions now store the game's formula (`repo._session_info_extra`), so new sessions can be told apart; older
sessions only have the packet format and the team id.

## 2. The setup sheet

Both car formats have the same setup sheet: the same items, labels and order (F1Laps' UDP-captured setup pages for
F1 25 and F1 26; RacingGames.gg; Traxion via search snippets). Menu order:

| # | Item (menu label) | Section | UDP field | Unit / note |
|---|---|---|---|---|
| 1 | Front Wing Aero | Aerodynamics | `m_frontWing` | integer |
| 2 | Rear Wing Aero | Aerodynamics | `m_rearWing` | integer |
| 3 | Differential Adjustment On Throttle | Transmission | `m_onThrottle` | %, higher = more locked |
| 4 | Differential Adjustment Off Throttle | Transmission | `m_offThrottle` | %, higher = more locked |
| 5 | Front Camber | Suspension Geometry | `m_frontCamber` | degrees, negative |
| 6 | Rear Camber | Suspension Geometry | `m_rearCamber` | degrees, negative |
| 7 | Front Toe-Out | Suspension Geometry | `m_frontToe` | degrees (positive; the label carries the direction) |
| 8 | Rear Toe-In | Suspension Geometry | `m_rearToe` | degrees (positive) |
| 9 | Front Suspension | Suspension | `m_frontSuspension` | higher = stiffer |
| 10 | Rear Suspension | Suspension | `m_rearSuspension` | higher = stiffer |
| 11 | Front Anti-Roll Bar | Suspension | `m_frontAntiRollBar` | higher = stiffer |
| 12 | Rear Anti-Roll Bar | Suspension | `m_rearAntiRollBar` | (EA's spec comment wrongly says "Front") |
| 13 | Front Ride Height | Suspension | `m_frontSuspensionHeight` | unitless integer |
| 14 | Rear Ride Height | Suspension | `m_rearSuspensionHeight` | unitless integer |
| 15 | Brake Pressure | Brakes | `m_brakePressure` | % |
| 16 | Front Brake Bias | Brakes | `m_brakeBias` | % to the front (equals CarStatus `m_frontBrakeBias`) |
| 17-20 | Front Right / Front Left / Rear Right / Rear Left Tyre Pressure | Tyres | four floats | psi; each wheel set separately (UDP order RL, RR, FL, FR) |

UDP to menu: identity for every item; floats are float32 (e.g. 24.299999 is 24.3), so pitwall rounds to the menu's
decimals (`Parameter.menu_value`). Exact label wording ("Front Wing Aero" vs "Front Wing") comes from third-party
transcriptions; F1Laps prints "Front Wing" and misspells "Break Pressure".

Not setup items (sent over UDP, never compared):

- **Engine braking** was a setup item in F1 24 (0-100 %). For both car formats in F1 25 it is gone: F1Laps shows
  it on F1 24 sheets only (its FAQ says each sheet shows "all the car settings you can adjust"), every UDP value
  seen is exactly 50 (including the PS5 driver's own setup, where every other item changed), and a guide and a
  video say it was removed. RacingGames.gg and Last Word On Gaming still print a value (50/55) on their F1 25
  sheets; pitwall does not record it. One effects source believed it still exists; the range evidence above
  outweighs it. Confidence: medium.
- **Ballast** (constant 6 in every capture; meaning undocumented) and **fuel load** (set on the race strategy
  screen, not the setup sheet).

## 3. Ranges and steps

An end is **confirmed** when it is the menu's own limit (many independent setups sit exactly on it and none go
beyond). Otherwise it is **observed**: the bound of the published values pitwall has seen, and the true limit may
be wider. The diff calls a driver's value impossible only beyond a confirmed end (`Range.outside_menu`).
Evidence: about 640 UDP-captured F1 25 setups and 370 2026-car setups on F1Laps (crawled 2026-10-10), the
published setups in section 6, and two independent range surveys that agreed on every confirmed end.

| Item | 2025 cars | 2026 cars | Step | Confidence | Note |
|---|---|---|---|---|---|
| Front Wing Aero | 0 to 50 | 0 to 50 | 1 | high | Both ends are populated in the published setups; identity with the UDP value. |
| Rear Wing Aero | 0 to 50 | 0 to 50 | 1 | high |  |
| Differential Adjustment On Throttle | 10 to 100 | 10 to 100 | 5 | high | The 5 % step is inferred: every published value is a multiple of 5. |
| Differential Adjustment Off Throttle | 10 to 100 | 10 to 100 | 5 | medium | The 5 % step is inferred; 100 is rarely used. |
| Front Camber | -3.50 to -2.50 | -3.50 to -2.50 | 0.1 | high |  |
| Rear Camber | -2.00 to -1.00 (seen) | -2.00 to -1.20 (seen) | 0.1 | medium | Minimum -2.00: hundreds of setups sit there and none below. F1Laps' chart axis (-2.2 to -0.7) is carried over from F1 24. Unconfirmed end(s) are the bounds of 635 published values pitwall has seen. |
| Front Toe-Out | 0.00 to 0.20 (seen) | 0.00 to 0.09 (seen) | 0.01 | medium | Front toe-out; minimum 0.00 is the most common value. Unconfirmed end(s) are the bounds of 642 published values pitwall has seen. |
| Rear Toe-In | 0.10 to 0.25 (seen) | 0.10 to 0.17 (seen) | 0.01 | medium | Rear toe-in; no published F1 25 setup goes below 0.10 (F1 24 went to 0.00). Unconfirmed end(s) are the bounds of 642 published values pitwall has seen. |
| Front Suspension | 2 (seen) to 41 | 20 (seen) to 41 | 1 | medium | Maximum 41 is a strong cluster; the minimum is not observed (F1 24 and the shared scale suggest 1). Unconfirmed end(s) are the bounds of 648 published values pitwall has seen. |
| Rear Suspension | 1 to 41 (seen) | 1 to 41 (seen) | 1 | medium | Minimum 1 is a strong cluster; the maximum is not observed for these cars (the shared scale suggests 41). Unconfirmed end(s) are the bounds of 648 published values pitwall has seen. |
| Front Anti-Roll Bar | 1 to 21 | 1 to 21 | 1 | high |  |
| Rear Anti-Roll Bar | 1 to 21 | 1 to 21 | 1 | high |  |
| Front Ride Height | 15 (seen) to 35 (seen) | 18 (seen) to 28 (seen) | 1 | low | No cluster at either end (ride height is a bottoming trade-off); F1 24's 10-40 is not confirmed for F1 25. Unconfirmed end(s) are the bounds of 648 published values pitwall has seen. |
| Rear Ride Height | 40 to 60 (seen) | 40 to 56 (seen) | 1 | medium | Minimum 40 is a strong cluster on almost every track; the maximum is unknown (F1 24's 100 is not adopted). Unconfirmed end(s) are the bounds of 648 published values pitwall has seen. |
| Brake Pressure | 85 (seen) to 100 | 93 (seen) to 100 | 1 | medium | Maximum 100 is certain; the minimum is unknown (F1 24: 80). Unconfirmed end(s) are the bounds of 648 published values pitwall has seen. |
| Front Brake Bias | 50 to 60 (seen) | 50 to 59 (seen) | 1 | medium | Front share. Minimum 50 is a cluster; the maximum is unknown (F1 24: 70). Unconfirmed end(s) are the bounds of 642 published values pitwall has seen. |
| Front Right Tyre Pressure | 22.5 to 29.5 | 22.5 to 29.5 | 0.1 | high | Each wheel is set separately. |
| Front Left Tyre Pressure | 22.5 to 29.5 | 22.5 to 29.5 | 0.1 | high |  |
| Rear Right Tyre Pressure | 20.5 to 26.5 | 20.5 to 26.5 | 0.1 | high |  |
| Rear Left Tyre Pressure | 20.5 to 26.5 | 20.5 to 26.5 | 0.1 | high |  |

"(seen)" marks an observed end: the bound of the published values, not a confirmed menu limit.

Differences between the formats: none found. Every value seen on unambiguous 2026 cars (Audi, Cadillac) lies within
the 2025-car bounds; the formats keep separate observed bounds because they have separate evidence.

## 4. Patch history

Handling-relevant F1 25 patches (EA's patch notes, as reported by RacingGames.gg, Bsimracing, RaceSimCentral and
others; ea.com reserves its content against scraping, so EA's own posts are cited as links only). A setup counts as
**current** when it states a game version at or after its car format's latest handling patch, or was published on
or after that patch's release day (`build.is_current`).

| Version | Date | Cars | What changed for handling / setups |
|---|---|---|---|
| launch | 2025-05-30 | 2025 | Reworked handling after F1 24 (Codemasters: back towards F1 23 traits) |
| 1.03 / 1.04 | 2025-06 | - | Track-surface fixes (Miami, Japan), AI starts; no car physics |
| **1.06** | **2025-07-07** | **2025** | **Player-car physics: front ride height and floor friction (underbody scraping costs less top speed); wet auto-gearbox upshifts. Latest handling patch for the 2025 cars.** |
| 1.07 | 2025-07-21 | 2025 | Spain T14 apex bump smoothed |
| 1.11 | 2025-08-18 | 2025 | Compound allocations at Montreal, Silverstone, Spa (selection, not the tyre model) |
| 1.12 | 2025-09-15 | - | AI braking/traction only |
| 1.16 / 1.17 | 2025-12-08 / 2026-02-02 | 2025 | Bahrain T4 bump; Bahrain T10 rumble strip that "could unsettle cars with certain setups" |
| 1.20 | 2026-06-03 | both | 2026 Season Pack: 2026 cars (active aero, Boost, about 15 % less downforce); brake/diff values set by mapped buttons fixed |
| 1.22 / 1.23 / 1.24 | 2026-06-15 .. 07-13 | 2026 | Overtake detection lines (Las Vegas, Monza); Madrid T5 sausage kerbs (older Madrid setups not comparable); Hotlap ERS in the wet. EA: Madrid can only be driven with 2026 cars |
| **1.25** | **2026-09-07** | **2026** | **Straight Mode closes unless the throttle is above 90 %; Boost in the wet with limited deployment; rapid wheel inputs follow the physics. Latest handling patch for the 2026 cars (GO Setups rebuilt its whole 2026 library after it).** |
| 1.26 | 2026-09-16 | - | Career-save crash fix (the build of the recorded PS5 capture) |

Known setup-related issue: force-feedback oscillation after a session change on v1.25 (EA forum reports; already in
`docs/research/rig-setup-sources.md`).

## 5. What each parameter does

Plain-words effects are in the catalogue (`parameters[].higher` / `.lower`, shown with every difference). They were
written in pitwall's own words from EA Help's F1 25 setup guide, RacingGames.gg, simracingcockpit.gg, Driver61,
f125game.com and Jarno Opmeer's F1 2021 guide (cited per parameter in the catalogue). Disagreements that matter:

- **On-throttle differential.** All sources agree higher = more locked. Most (simracingcockpit, Driver61,
  RacingGames, Traxion excerpt) say lower is more forgiving on exit and higher gives more drive but snaps; f125game
  says raising it fixes loose exits, and Jarno (F1 2021) stresses exit understeer and inside-wheel spin when too
  open. Pitwall follows the majority and says so.
- **Tyre pressures.** EA, RacingGames F1 25 and simracingcockpit say higher pressure runs cooler and lasts longer;
  f125game and Jarno say it overheats sooner. The effect texts state only what the sources agree on (contact
  patch, grip, top speed) and the explanation notes the disagreement.
- **2026 cars.** Active aero opens both wings in straight-mode zones; no accessible source says how the wing values
  interact with it. GamingBolt reports slimmer wings with less downforce and more throttle-sensitive exits.

## 6. Sources and terms

Only sources whose robots.txt and terms allow automated access were fetched; values are recorded as facts with
attribution and a link, never page text.

| Source | Kind | Setups cited | Terms (summary) | Policy |
|---|---|---|---|---|
| [F1Laps community setups](https://www.f1laps.com/) ([terms](https://www.f1laps.com/terms-of-service/)) | community_db | 349 | robots.txt allows the public setup pages and signals ai-input=yes; llms.txt points agents at the setup database; the terms reserve copyright in the site's materials and say nothing about automated access. Setups are submitted from players' own telemetry. Pitwall cites a few setups per track as attributed facts (values, author, date, link). | use |
| [RacingGames.gg (Gfinity)](https://racinggames.gg/) ([terms](https://racinggames.gg/page/website-terms-of-use/)) | press | 23 | robots.txt allows the articles; the terms allow personal non-commercial use and forbid reproducing content without permission, with no clause on automated access. Only individual setup values are recorded, with attribution and a link; no text is copied. | use_limited |
| [PPE.pl](https://www.ppe.pl/) ([terms](https://www.ppe.pl/regulamin_spolecznosci.html)) | press | 20 | robots.txt allows the guide pages; only community rules exist, with no clause on automated access; all rights reserved. Values only, with attribution. | use_limited |
| [Last Word On Gaming](https://lastwordongaming.com/) | press | 7 | robots.txt only disallows /wp-admin/; no terms-of-use page is published; all rights reserved. Values only, with attribution. | use_limited |
| [Gamosaurus](https://www.gamosaurus.com/) ([terms](https://www.gamosaurus.com/mentions-legales)) | setup_site | 12 | robots.txt allows the guide pages; the legal notice has no terms of use; all rights reserved. Values only, with attribution. Its setups are time-trial setups for a wheel. | use_limited |
| [u/derp3339 'F1 game setups (22-26)' public Google Sheet](https://docs.google.com/spreadsheets/d/1fUZKqMpARGJ1XEvsmGlOtN2_NVPOqLehPNiLH-YyYSI/) ([terms](https://policies.google.com/terms)) | creator | 43 | A public view-only sheet by a league racer; docs.google.com robots.txt allows /spreadsheet paths and Google's terms only bar automated access that ignores such instructions. The content belongs to its author: values only, with attribution. | use_limited |

Not used (checked 2026-10-10):

| Source | Why not |
|---|---|
| Sportskeeda, Dexerto, PCGamesN, Radio Times | robots.txt blocks AI agents |
| Game Rant / TheGamer (Valnet), GIGA.de, GameStar.de, Gamepressure, EarlyGame | robots.txt forbids automated access |
| GamesRadar+, VideoGamer, Simgasm, Sim Racing Configs | terms forbid scraping / data mining |
| EA (ea.com) | robots.txt reserves rights against scraping and text/data mining (EA Help is cited as a link only) |
| Traxion.gg, simracingsetup.com, OverTake.gg, Deltia's Gaming, Dot Esports, esports.gg, Operation Sports, Pro Game Guides network, Red Bull | bot walls (Cloudflare / AWS WAF) |
| YouTube, Reddit, X, Steam Community | terms or robots.txt forbid automated access (most esports-driver and creator setups live here, so they are missing) |
| Brendon Leigh Setups, Virtual Setup Engineer | paid; terms forbid scraping and sharing |
| Track Titan, GO Setups | paid membership content |
| f1gamesetup.com | values need a login |
| solox.gg | aggregates of F1Laps' fastest setups (would count F1Laps twice; includes half steps the menu cannot set) |
| f125game.com, FinalBoss.io, Ranko Universe | quality: generic or machine-written guides, values outside the menu ranges |

## 7. How the catalogue was built

1. **F1Laps** (community setups captured from players' own UDP telemetry): list pages per track, session filter and
   conditions, then up to six setup pages per list, about one request per 1.1 s, cached (robots.txt allows the
   pages and signals `ai-input=yes`; F1Laps' llms.txt points agents at the setup database for exactly this
   question). F1Laps files a setup under "F1 25" or "F1 26" by the UDP format it was captured in, so:
   - from "F1 25" setups published on or after 2026-06-03, only real 2025 team names are kept (a 2026 car in
     format 2025 shows up as the generic car);
   - from "F1 26" setups, the 2025-only team names (Kick Sauber, Racing Bulls, Braking Point teams) and the
     generation-ambiguous generic / My Team / custom cars are dropped; the rest use the 2026 team table (Audi,
     Cadillac, "RB").
   Per car format x track x session x conditions pitwall keeps the three fastest current setups (one per author;
   the newest three when none is current). Time trial, qualifying and sprint shootout count as qualifying.
2. **Other sources**: per-track research (three tracks per researcher), each file then re-checked by a second
   agent that re-opened every page and compared every value, date and session label. Values the menu cannot show
   (not on the step, beyond a confirmed limit) and engine braking are dropped with a log line; setups from the
   excluded sources above are skipped.
3. **Recommendations** (`carsetup/build.py`, deterministic, built at load and validated; never stored): for each car format x track
   x session x conditions x style, the candidates are the matching setups made for the current handling model
   (stated game version at/after the latest handling patch, or published on/after its date; otherwise all, with
   every value capped at low confidence). One candidate is used as published; with several, pitwall takes the
   *medoid* (the setup closest on average to the others, range-normalised), so a recommendation is always one
   coherent published setup, never a per-parameter mix. Per value: the agreeing setups (within 10 % of the range),
   the spread, and a disagreement note when the spread exceeds 25 % of the range. Confidence: high = three or
   more candidates with two thirds agreeing; medium = at least two agree; else low.
4. **Stable style** without a labelled stable setup is derived (rule `stable_v1`): rear wing +1, rear anti-roll bar
   -1, on-throttle differential -5, off-throttle differential +5, clamped to the range; changed values are marked
   derived, low confidence. Sources: f125game beginner tips (rear wing, rear ARB), EA Help ("more downforce when
   struggling for control"), simracingcockpit / Driver61 / RacingGames (differential directions). Guides agree on
   directions far more than on amounts, so the steps are minimal. Aggressive is never derived; wet is never derived
   from dry; a missing qualifying setup falls back to the race setup (and the reverse) with a note.

Coverage of the packaged catalogue (balanced style; S = single source, M = medoid of several):

**F1 25 cars (2025 regulations)** (306 cited setups)

| Track | Dry race | Dry quali | Wet race | Wet quali |
|---|---|---|---|---|
| Melbourne (0) | M3 | M3 | M3 | - |
| Shanghai (2) | M3 | M3 | M3 | - |
| Sakhir (Bahrain) (3) | M3 | M3 | M3 | - |
| Catalunya (4) | M4 | M4 | M3 | - |
| Monaco (5) | M3 | M3 | M3 | - |
| Montreal (6) | M3 | M4 | M3 | - |
| Silverstone (7) | M3 | M3 | M3 | - |
| Hungaroring (9) | M3 | M3 | M3 | - |
| Spa (10) | M3 | M3 | M3 | - |
| Monza (11) | M3 | M3 | M3 | - |
| Singapore (12) | M3 | M3 | M3 | - |
| Suzuka (13) | M3 | M3 | M3 | - |
| Abu Dhabi (14) | M3 | M3 | M3 | - |
| Texas (15) | M3 | M3 | M3 | - |
| Brazil (16) | M3 | M3 | M3 | - |
| Austria (17) | M3 | M3 | M3 | - |
| Mexico (19) | M3 | M3 | M3 | - |
| Baku (Azerbaijan) (20) | M3 | M3 | M3 | - |
| Zandvoort (26) | M3 | M3 | M3 | - |
| Imola (27) | M2 | M3 | M3 | - |
| Jeddah (29) | M3 | M3 | M3 | - |
| Miami (30) | M3 | M3 | M3 | - |
| Las Vegas (31) | M3 | M3 | M3 | - |
| Losail (32) | M3 | M3 | M3 | - |
| Silverstone (Reverse) (39) | M3 | M3 | M3 | - |
| Austria (Reverse) (40) | M3 | M3 | M2 | - |
| Zandvoort (Reverse) (41) | M3 | M3 | S1 | - |

**2026 Season Pack cars (2026 regulations)** (148 cited setups)

| Track | Dry race | Dry quali | Wet race | Wet quali |
|---|---|---|---|---|
| Melbourne (0) | S1 | M2 | M2 | - |
| Shanghai (2) | S1 | M4 | S1 | - |
| Sakhir (Bahrain) (3) | M3 | S1 | S1 | - |
| Catalunya (4) | S1 | S1 | M3 | - |
| Monaco (5) | S1 | S1 | S1 | - |
| Montreal (6) | M2 | M4 | M2 | - |
| Silverstone (7) | S1 | S1 | M2 | - |
| Hungaroring (9) | S1 | M3 | M2 | - |
| Spa (10) | S1 | M2 | S1 | - |
| Monza (11) | S1 | S1 | M3 | - |
| Singapore (12) | M3 | M2 | S1 | - |
| Suzuka (13) | S1 | M3 | S1 | - |
| Abu Dhabi (14) | M2 | M2 | - | - |
| Texas (15) | M3 | M2 | S1 | - |
| Brazil (16) | M2 | M3 | S1 | - |
| Austria (17) | M4 | M2 | M2 | - |
| Mexico (19) | M2 | S1 | S1 | - |
| Baku (Azerbaijan) (20) | S1 | M3 | M2 | - |
| Zandvoort (26) | S1 | M2 | S1 | - |
| Jeddah (29) | M3 | S1 | M2 | - |
| Miami (30) | S1 | S1 | M2 | - |
| Las Vegas (31) | M2 | M3 | S1 | - |
| Losail (32) | M2 | S1 | S1 | - |
| Madrid (42) | M2 | M2 | S1 | - |

## 8. Gaps and open questions

- Esports-driver and creator setups are mostly on YouTube, Reddit, X, Steam or paid sites, none of which allow
  automated access; the published-setup evidence is therefore community (F1Laps) and press-guide setups.
- Most press guides date from launch (May-June 2025) and state no game version; F1Laps setups state no version
  either (the publication date stands in for it).
- 2026 cars: one independent non-F1Laps source (u/derp3339's league sheet, June-August 2026); wet 2026 setups come
  from F1Laps only.
- Unconfirmed range ends (section 3) need an in-game check: front ride height, the rear ride height / toe / camber
  maxima, brake pressure minimum, brake bias maximum, front suspension minimum.
- Exact menu label wording and whether Ranked / some F1 World events lock the setup (a stored setup may then not be
  the driver's choice).
- No source documents how the 2026 wing values interact with active aero.
- Some F1Laps entries are the game's own preset: a player who never changed the setup still uploads it. Pitwall
  cannot tell these apart in general; where the preset is known (the AI cars' Austria setup in the PS5 capture:
  wings 10/12, differential 90/55), a recommendation can coincide with it, which is still a setup a fast lap was
  driven on.

## 9. Race engineer

`ai/facts.py` adds "setup" facts for F1 sessions (`carsetup.facts.session_setup_facts`): the recommendation with
its sources and confidence, the driver's latest stored setup vs recommended (the biggest differences with their
plain-words effect), one single-variable experiment, and the rule "rule out technique first". The setup intent
selects them; without the LLM the deterministic answer appends the diff after "rule out technique first". A
session pitwall cannot map (e.g. the generic car in format 2025) gets one fact that says why.

## 10. Updating

1. Re-run the research (sources, per-track setups, F1Laps crawl) and assemble the evidence into the JSON (values
   in menu units, one record per published setup, sources with their terms; one line per record).
2. `uv run python -m pitwall.carsetup.build` prints what the evidence produces; `uv run pytest
   tests/unit/test_carsetup.py tests/recorded/test_carsetup_real.py` validates ranges, steps, provenance, coverage
   and the real PS5 setups against the ranges.
3. When a patch changes handling, update the format's `latest_handling_patch`: older setups then stop counting as
   current.

## 11. F2 cars

_Added 2026-10-12 (F2 support). Data: the `f2` format and the `f1laps-25-f2-*` setups in
`src/pitwall/carsetup/data/f1_25_setups.json`; evidence crawl and selection scripts in the maintainer's scratch
folder (not shipped)._

**Format.** `f2` = "F2 cars (2024 and 2025 seasons)". It covers the F2 2024 teams (ids 158-168) always, and the 2025
teams (209-219 in UDP format 2025, observed; 465-475 in format 2026) when the session's formula is F2. The 2026 F2
cars (489-499) have no setups ("No setups for the 2026 F2 cars in Pitwall yet."), and an F2 car whose team is not
known has none either ("Pitwall can't tell which F2 car this is, so it shows no setups."): an F2 driver is never
asked to choose an F1 car format, and an F1 format is refused for an F2 session (and the reverse). No F2 handling
patch is known (v1.12 added the 2025 F2 cars; v1.13 changed tyres, colours and AI pit stops), so
`latest_handling_patch` is null and no F2 setup counts as out of date.

**Ranges rule.** F2 evidence only, never copied from the F1 car. Each range runs from the lowest to the highest value
in 730 published F2 setups (F1Laps' F2 team filters for F1 25, captured from players' own game data; e-mail-named
authors left out) and the owner's 21 recorded F2 setups (CarSetups packet, PS5, 2026-10-11; 9 distinct). An end is
*confirmed* (no `*` below) only when at least 5 published setups sit exactly on it, or when the owner reads it from
the game's F2 setup screen (validation check `f2_ps5` lists the unconfirmed ends). Steps are the menu's: wings 1,
differentials 5, camber 0.1, toe 0.01, tyre pressures 0.1, everything else 1. The F2 car differs from the F1 car in
two places: brake bias reaches 69 (one published setup; the F1 range stops at 60) and rear suspension stops at 26
(dozens of setups sit on it; the F1 range goes to 41). `tests/recorded/test_f2_ps5.py` checks that the owner's F2
setups fit.

| Parameter | F2 range (* = unconfirmed end) | Step | F1 2025 range |
|---|---|---|---|
| front_wing | 0 to 50 | 1 | 0 to 50 |
| rear_wing | 0 to 50 | 1 | 0 to 50 |
| diff_on_throttle | 10 to 100 | 5 | 10 to 100 |
| diff_off_throttle | 10 to 100 | 5 | 10 to 100 |
| front_camber | -3.5 to -2.5* | 0.1 | -3.5 to -2.5 |
| rear_camber | -2 to -1* | 0.1 | -2 to -1 |
| front_toe | 0 to 0.12* | 0.01 | 0 to 0.2 |
| rear_toe | 0.1 to 0.25 | 0.01 | 0.1 to 0.25 |
| front_suspension | 24* to 41 | 1 | 2 to 41 |
| rear_suspension | 1 to 26 | 1 | 1 to 41 |
| front_arb | 1 to 21 | 1 | 1 to 21 |
| rear_arb | 2* to 21 | 1 | 1 to 21 |
| front_ride_height | 15 to 35* | 1 | 15 to 35 |
| rear_ride_height | 40 to 60* | 1 | 40 to 60 |
| brake_pressure | 90* to 100 | 1 | 85 to 100 |
| brake_bias | 50 to 69* | 1 | 50 to 60 |
| tyre_pressure_fr | 22.5 to 29.5 | 0.1 | 22.5 to 29.5 |
| tyre_pressure_fl | 22.5 to 29.5 | 0.1 | 22.5 to 29.5 |
| tyre_pressure_rr | 20.5 to 26.5 | 0.1 | 20.5 to 26.5 |
| tyre_pressure_rl | 20.5 to 26.5 | 0.1 | 20.5 to 26.5 |

**Selection.** For each track, session (time trial counts as qualifying) and dry conditions: the 3 fastest setups by
the lap time the source shows, one per author. Left out: exact copies of a preset (the same values from 5 or more
authors at a track: 373 of the 730), authors whose name is an e-mail address (14 authors, 38 setups: left out
entirely, never masked, so no credit is stripped), values off the menu's steps, and wet or mixed setups (wet is
never made up from dry). Every cited setup keeps its source, link, author and publication date; its notes give the
lap time, the session and the team with its season as F1Laps labels them. One author is 2-3 s faster than everyone
else at every track; their setups are cited as published. Recommendations come from the existing builder
(`carsetup/build.py`, the medoid of the candidates); the stable variant's rule cites F1 25 guides about the F1 cars,
so it is not applied to F2 (an F2 beginner gets the balanced F2 setup, labelled as such).

| Track (EA id) | Session | Setups | Authors |
|---|---|---|---|
| Melbourne (0) | qualifying | 3 | idrisananda63, Saiyzzo, AlexZexu |
| Melbourne (0) | race | 3 | idrisananda63, JuiceWrld, adugo |
| Sakhir (3) | qualifying | 3 | idrisananda63, AlexZexu, pawsome |
| Sakhir (3) | race | 3 | idrisananda63, adugo, pawsome |
| Monaco (5) | qualifying | 3 | K33p1n, idrisananda63, AlexZexu |
| Monaco (5) | race | 3 | idrisananda63, AlexZexu, pawsome |
| Monza (11) | qualifying | 3 | idrisananda63, AlexZexu, SlickSticky |
| Monza (11) | race | 3 | idrisananda63, Cedum, AlexZexu |
| Jeddah (29) | qualifying | 3 | Saiyzzo, idrisananda63, AlexZexu |
| Jeddah (29) | race | 3 | AlexZexu, pawsome, SlickSticky |

Coverage is the 5 tracks the crawl covered (dry only). Elsewhere the page says "No F2 setups for this track in
Pitwall yet."; the driver's own setup, the experiments and the technique page's setup suggestions still work, sized
with the F2 ranges.
