# Game telemetry compatibility: what pitwall can support, on which platform

Research date: 2026-10-10. This is the definitive compatibility report for pitwall. It merges a multi-agent candidate sweep with adversarial verifier verdicts, plus spot checks made while writing (§11). It changes no code.

**Scope.** Every racing game with external telemetry that a Mac on the LAN could plausibly receive, either directly or through a documented Windows relay. The focus is the user's rig: PS5 + Fanatec GT DD Pro (`docs/research/rig-setup-sources.md` [P5]). Xbox and PC are covered second, for sharing pitwall with others.

**Not redone here.** The following are referenced, not repeated:
- protocol layouts in `forza-ac-acc-iracing.md` [P1], `gt7-protocol.md` [P2] and `f1-udp-spec.md` [P3];
- track-knowledge material in `track-knowledge-sources.md` [P4].

**Labels.** Every claim carries a bracketed source ID that resolves to a URL in §12. The prefix shows the kind of source:

| Prefix | Source kind | Weight |
|---|---|---|
| **O** | Official: developer/publisher doc, patch notes, spec, hardware-vendor KB | strongest |
| **N** | News article reprinting or reporting official notes | strong if it quotes notes |
| **V** | Ecosystem vendor: dashboard, motion-rig, coaching-app compatibility lists and setup docs | medium; often generic "PS4/5" tags |
| **C** | Open-source code, spec-header copies, or third-party captures | medium; licence noted |
| **F** | Forum or user report (dated) | weak alone |
| **P** | pitwall's own docs and code | internal |

**Verdicts** (from the verifier pass; the stricter verdict wins where verifiers disagreed):

| Verdict | Meaning |
|---|---|
| **Confirmed** | Official source, or several independent sources including real use on that platform |
| **Likely** | Official feature statement or several vendor docs, but no first-hand report on that platform |
| **Unverified** | Single generic vendor tag, or no evidence either way |
| **Conflicting** | Credible sources disagree; needs a pitwall probe |
| **No** | Explicit statements that no interface exists on that platform |

Platform wording follows the brief:
- **"works on console"** requires evidence of real console use;
- **"PC only"** means the interface exists but only on PC;
- **"unknown"** means there is no evidence either way.

These compatibility verdicts are separate from pitwall's own **validation tiers**: synthetic, recorded and live, as defined in CLAUDE.md and `docs/validation.md`.

**Research limits.**
- The shared web-search budget for this session was exhausted before writing, and my two extra searches were refused.
- Some sources returned 403/429 to non-browser fetchers: forums.ea.com, answers.ea.com, overtake.gg, help.fanatec.com, the Next Level Racing article and Kunos's Steam guide.
- §10 lists exactly what could not be settled. A follow-up session (or a real browser) can continue.

---

## 1. Executive summary

### 1.1 What the PS5 rig can add next, ranked

| Rank | Game (PS5) | Why | Verdict on PS5 | pitwall effort | Do this if |
|---|---|---|---|---|---|
| 1 | **Project Motor Racing** (native PS5, current title) | The official v2.3 notes (2026-09-23) say "Enabled UDP telemetry settings on console platforms" (re-fetched 2026-10-10) [O1]. The game pushes UDP to a configurable host on port 7576 [V27]. The data is rich: track and layout names, layout length, sector times and all-car race state [O3][C1]. | **Likely**: settings are official, but no first-hand PS5 stream report yet | **Gated**: a community MIT layout exists [C1] but some units are "best guess"; implement after a pitwall PS5 capture confirms it | always: newest console sim with telemetry |
| 2 | **Forza Horizon 5** on PS5 | If Data Out exists in the PS5 build, pitwall's existing 324-byte Forza adapter should apply unchanged [P1] | **Unverified**: no source confirms or denies it; soft signals lean Xbox/PC only [V26][V10][O24] | **None** if present | James owns FH5 on PS5: check Settings > HUD and Gameplay (bottom of the list) |
| 3 | **Gran Turismo Sport** (PS4 build) | Same Simulator Interface as GT7, with a different key, ports (33339/33340) and IV XOR, and a 296-byte packet [C4][P2] | **Likely**: RS Dash, SIM Dashboard and the SimHub wiki name PS5 [V33][V3][V22] | **S**: parameterise the GT7 receiver | owned; offline modes only since 2024-01-31 [N4] |
| 4 | **F1 24 / F1 23** (native PS5) | Same EA UDP family. The 2024 format is a 6-struct delta already documented in [P3] §6. F1 25 can also emit 2024/2023 [P3]. | **Confirmed** [V8][V9][V20][V39] | **S** (2024) / **S–M** (2023: needs EA's 2023 text [O8]) | James still plays F1 24/23, or for sharing |
| 5 | **Assetto Corsa** (PS4 build) | UDP 9996 handshake; layout already researched [P1] §2.2 | **Conflicting**: PS4 hardware confirmed; PS5 back-compat claimed by two vendors, denied by one (§1.2) | **Gated** (probe), then **M** | owned: run the live probe in §1.2 |
| 6 | **Project CARS 2** (PS4 build) | Rich pCARS2 UDP broadcast on 5606. The same parser also serves AMS2 and pCARS 3 on PC (§3.3). | **Unverified** on PS5: a single generic "PS4/5" vendor tag [V39] | **M–L** | owned; broadcast is fragile on Wi-Fi [V7] |
| 7 | F1 2019 / 2020 (PS4 builds), F1 2021 / F1 22 (native PS5) | Same EA UDP family; separate decoders per year | 2021/22: **Confirmed** [O5][O6]; 2019/2020 on PS5: **Unverified** [V39] | **M** each | low priority (legacy) |

**Not possible on PS5 (no console interface):**
- Assetto Corsa Competizione;
- EA SPORTS WRC;
- the DiRT and DiRT Rally series;
- GRID (2019) and GRID Legends;
- WRC Generations and WRC 7–10;
- Test Drive Unlimited Solar Crown;
- Project CARS 3;
- Rennsport;
- NASCAR 25.

Not yet released on PS5: Le Mans Ultimate (early-to-mid 2027) [N12], Assetto Corsa EVO (after PC 1.0) [N13], Forza Horizon 6 (2027-01-26) [N6] and Wreckfest 2 (no date) [N10]. See §8.

**Vendor lists add no other PS5 title.** Next Level Racing's console list names only GT7 and F1 25 on PlayStation [V46]. D-BOX's only PlayStation-exclusive title is GT7 [N18]. Sim Racing Telemetry's PlayStation titles are F1, Project CARS 1/2 and MotoGP 18 [V39]. None of these lists adds a PS5 title beyond PMR.

**Wheel caveat for every PS4-era title (ranks 3, 5, 6, 7).** Fanatec says older PlayStation games may not detect the GT DD Pro; the fix is PURPLE mode, which emulates a CSL Elite WB+ PS4 [O26]. Its PS4 list says those titles "should also function the same on PS5" but are "not fully tested" [O27]. The modes themselves are verified in [P5] (DARK BLUE = native PS5/PS4, PURPLE = PS4 compatibility). Which specific titles need PURPLE was not re-verified here, because help.fanatec.com returned 403 to the verifiers.

### 1.2 The Assetto Corsa PS4-on-PS5 answer

**Answer: it definitely worked on PS4 hardware. On PS5 (PS4 build via back-compat) it is unknown until pitwall probes it.**

| Question | Evidence | Verdict |
|---|---|---|
| Does the PS4 build serve the UDP 9996 Remote Telemetry protocol? | A PS4 tester got "UDP data with no problems" and noted a re-register per race mode (2017-02-24) [F1]. The same tester's capture of 8641 × 328-byte RTCarInfo is CC0-1.0, verified via the GitHub API [C8]. 328-byte packets were received "running on PS4" (2017-03-06) [F2]. On AC Ultimate Edition for PS4 the handshake reply showed circuit, driver and car names (2020-04-28) [F3]. DashPanel lists "Assetto Corsa (PC/PS4)" [V43]; its developer says "AC provides very limited data on PS4" [V44]. Track Titan lists PS4 (2026-05-19) [V42]. Nothing needs enabling in the game [F3]. | **Confirmed** (PS4 hardware) |
| Does it still work when the PS4 build runs on a PS5? | **Yes, per:** SIM Dashboard ("Assetto Corsa 1 UDP (PS4/PS5)"; "supported on PC, PS4 and PS5") [V2][V1], and Driver Apex ("PS4 and PS5"; undated; it also claims "no IP address configuration required", which contradicts the handshake model) [V45]. **No, per:** Track Titan ("not supported on PlayStation 5") [V42] and Sim Racing Studio ("PS4 only") [V41]. Sony's back-compat restrictions cover Second Screen/companion apps, not game-level LAN UDP [O23]. No dated first-hand PS5 report exists. | **Conflicting**, so probe |
| Latest console patch | PS4 patch 1.22 (2018-05-03); no console patch note found mentions telemetry or UDP [N5] | no official statement either way |
| What differs from PC? | RTLap (SUBSCRIBE_SPOT) was not delivered on PS4 in 2017 [F1]. Track strings may be wrong on console: an Overtake search snippet says console versions "don't send out proper track data" [F13]. The handshake reply size on console is unmeasured (408 B wide strings expected; 208 B if 8-bit). Bool padding is disputed (isInPit at 24 vs 26) [P1]. The console rate is unknown. "The game does not send a maximum rpm value" [V2]. | settle in the probe |
| Xbox One? | "No telemetry interface included in the Xbox Version" [V1]; RS Dash agrees [V29]; Track Titan lists Xbox as unsupported [V42] | **No** |

**Live probe plan.** Run it only with James's explicit go-ahead: it sends UDP to the PS5.

Precondition: a small probe script (none exists yet). The steps and safety limits below come from the candidate sweep; the protocol facts are from [O13][P1][C5][C6].

**0. Prerequisites.**
- Get the PS5's IPv4 from PS5 Settings > Network > Connection Status, or from pitwall's Connect-page sender list (the PS5 already appears there as an F1/GT7 sender).
- The Mac and PS5 must be on the same subnet, with no Wi-Fi client isolation.
- Note the AC version and the PS5 firmware.
- Get **on track** in Hotlap, Time Trial or Practice, not in menus. Close any other AC dashboard app.
- Run the script under pitwall's `uv` Python, which already has the macOS firewall allowance for inbound UDP.

**1. Socket.**
- Open one IPv4 UDP socket bound to an ephemeral port. Do not bind 9996.
- `connect()` it to `(ps5_ip, 9996)` so an ICMP port-unreachable surfaces as `ConnectionRefusedError`.
- Set a 1 MB receive buffer and a 0.5 s timeout.
- Log every inbound datagram with `time.monotonic_ns()` to a `.pwcap` (game hint `ac-remote`). Record the IP, versions, mode, car/track and a timestamped log of every op sent in `meta.extra`.

**2. HANDSHAKE.**
- Send `<iii` (1, 1, 0) every 2 s, at most 15 tries.
- Success is a 408-byte datagram from `ps5_ip:9996` with int32@200 == 4242 and int32@204 == 1.
- Decode the UTF-16LE strings at 0 (car), 100 (driver), 208 (track) and 308 (config). Cut each at NUL **or** `%`.
- Accept a 208-byte reply too, but flag it as the 8-bit-string variant (identifier@100, version@104, track@108, config@158).
- Any other size: log the hex and stop parsing.

**3. SUBSCRIBE_UPDATE.**
- Send (1, 1, 1) once. Expect 328-byte datagrams within 3 s.
- Validate each one:
  - bytes 0–1 = `a\0`;
  - int32@4 = 328;
  - speed_Kmh@8 ≈ 3.6 × speed_Ms@16;
  - gas@56 and brake@60 in [0, 1];
  - carPositionNormalized@308 in [0, 1);
  - lapTime@40 rises within a lap.
- Measure the rate over 60 s of driving (median and p95 inter-arrival). Also measure it stationary and paused.
- Settle three unknowns:
  - the gear encoding: select R, N and 1st;
  - the isInPit byte (24 vs 26): drive into the pit lane;
  - steer units: turn to full lock.
- If the stream is silent for 3 s, re-handshake, then re-subscribe once.

**4. SUBSCRIBE_SPOT.**
- Use a second socket with its own handshake, then send (1, 1, 2).
- Complete at least 2 laps. Expect 212-byte RTLap packets.
- If none arrive, that matches 2017 PS4 behaviour; derive laps from lapCount/lastLap instead.

**5. Lifecycle.**
- Return to the menu: expect silence.
- Start a new session: expect that a re-handshake is needed [F1].
- Change car or track, and restart a session.
- While the stream is silent, re-handshake every 3 s, as moza-rev does [C6].

**6. DISMISS.** Send (1, 1, 3) on both sockets. Expect the stream to stop within about 1 s.

**Safety limits.**
- Send only these well-formed 12-byte structs, and only to `ps5_ip:9996`.
- At most 1 send per 2 s while searching, and none while streaming. Hard cap: 100 sends and 10 minutes per run.
- No port scans.
- Broadcast discovery (one handshake to the directed subnet broadcast) only with a separate explicit OK.
- Inbound load is at most about 110 kB/s (PC rates are ~333 Hz [C6]).

**Outcomes.**

| Outcome | Meaning | Action |
|---|---|---|
| **A** | 408-byte reply plus a stable 328-byte stream with plausible values | Commit the `.pwcap` to `tests/fixtures/recorded`. Mark AC "PS4 build on PS5" as live-validated field by field. |
| **B** | Handshake only, no stream | Partial. Retry in another mode. |
| **C** | `ConnectionRefused` while on track | Negative: the socket is not open under back-compat. |
| **D** | Silence while on track | Wrong IP, filtering, or unsupported. Retest over wired Ethernet before concluding negative. |

**Third-party fixture.** The 2017 PS4 capture [C8] is CC0-1.0. With James's permission it can be downloaded into a fresh scratch directory and used as a third-party PS4 fixture (not PS5, and not pitwall's recorded tier).
- The `.raw` file splits cleanly into 328-byte records.
- The extensionless sibling is a Python pickle stream: **never unpickle it**. If its timing is needed, read it with `pickletools.genops`.

### 1.3 Prioritised protocol families to implement next

This list excludes F1, GT7 and Forza, which already exist. It is ordered by value to this PS5 user first, then by value for sharing (Xbox, then PC).

| # | Family | Games | Platforms | Mac reach | Value |
|---|---|---|---|---|---|
| 1 | `pmr-udp` | Project Motor Racing | PS5, Xbox Series, PC | direct (unicast 7576) | Only current PS5-native sim with new console telemetry; rich data |
| 2 | `ac-remote-udp` | Assetto Corsa (2014) | PS4 (PS5 back-compat probe), PC | direct (handshake to 9996) | Possible PS5 win; PC baseline is official; inputs + lap fraction |
| 3 | `pcars2-udp` | Project CARS 2 (PS4/XB1/PC), Automobilista 2 (PC), Project CARS 3 (PC) | PS4/XB1 (PS5 unverified), PC | direct (broadcast 5606) | One parser, three games; AMS2 is a major PC sim needing no relay |
| 4 | `windows-shm-relay` | RaceRoom, Le Mans Ultimate, ACC, iRacing, AC, AMS2 (shm), rFactor 2, AC EVO | PC | via a pitwall Windows relay | Unlocks the main PC sims; no PS5 value |
| 5 | `acc-broadcast` | ACC (PC) | PC | direct (UDP register) | All-car field model for track knowledge [P4]; no inputs |
| 6 | `ea-wrc-json` | EA SPORTS WRC (PC) | PC | direct (JSON-configured UDP) | Current rally title with a self-describing official schema; needs a stage (point-to-point) model |

Spec sources, licences and doc paths are in §9.

**Cheap extensions of existing families (not new families):**
- GT Sport (GT family);
- F1 formats 2024 and 2023, then 2022/2021/2020/2019 (F1 family);
- FH5 on PS5, if present (Forza family).

See §3.1 and §3.2.

---

## 2. Master table

Effort codes:

| Code | Meaning |
|---|---|
| **Exists** | in pitwall now ([P6]) |
| **S** | extension of an existing adapter |
| **M** | new adapter from a written spec or community doc |
| **L** | new transport or component (relay, schema decoder, stage model) |
| **Gated** | implementable from docs only after a pitwall capture or probe |
| **Blocked** | no usable spec, or a licence problem |
| **n/a** | nothing to implement |

Data richness codes:

| Code | Contents |
|---|---|
| **Full** | inputs, lap distance, sector times, tyres, fuel, track id |
| **Rich** | inputs, lap position, lap/sector timing, some tyre data |
| **Medium** | inputs, lap fraction or position, lap times; no tyres or sectors |
| **Basic** | motion/dash only, no lap structure |
| **?** | layout unknown |

### 2.1 Already in pitwall (for completeness)

| Game | Platform | Telemetry | Transport / port | Family | Richness | Evidence | Verdict | Effort |
|---|---|---|---|---|---|---|---|---|
| F1 25 (format 2025/2026) | PS5 | Yes | UDP push → Mac:20777 | ea-f1-udp | Full | [P6][O10] | Confirmed; pitwall **live-validated** (2026-10-10) | Exists |
| F1 25 | Xbox Series X\|S | Yes | same | ea-f1-udp | Full | [O28][O10][V42] | Confirmed (game); pitwall untested | Exists |
| F1 25 | PC | Yes | same | ea-f1-udp | Full | [O10] | Confirmed; pitwall untested | Exists |
| Gran Turismo 7 | PS5 / PS4 | Yes | heartbeat → console:33739, stream ← :33740, Salsa20 | gt-simulator-interface | Rich (no sectors, track id or wear) | [P2][V20][V22][V58][V48] | Confirmed (PS5); PS4 community only [P2]; pitwall synthetic only | Exists |
| Forza Motorsport (2023) | Xbox Series / PC | Yes | Data Out push (Dash 331) | forza-data-out | Rich (wear, TrackOrdinal) | [P1][V42][V26] | Confirmed | Exists |
| Forza Motorsport 7 | Xbox One / PC | Yes | Data Out (Dash 311) | forza-data-out | Medium+ | [V22][V26][V19] | Confirmed | Exists |
| Forza Horizon 4 | Xbox One / PC | Yes | Data Out (324) | forza-data-out | Medium+ | [V11][V59][V20] | Likely | Exists |
| Forza Horizon 4 | Xbox Series X\|S | **No** (broken, "will not be fixed") | — | — | — | [V11][V43] | Likely no (primary Known Issues page now redirects) | n/a |
| Forza Horizon 5 | Xbox One / Series / PC (Store) | Yes | Data Out (324) | forza-data-out | Medium+ | [V26][V10][V49] | Likely (SimHub wiki: "except on XBOX X which is broken"; Steam build broken) [V22] | Exists |
| Forza Horizon 5 | **PS5** | **Unknown** | — | — | — | [O24][V26][V10][V22] | **Unverified** | Exists if present |
| Forza Horizon 6 | Xbox Series / PC | Yes | Data Out (324), avoid ports 5200–5300 | forza-data-out | Medium+ | [O25][V47][V12] | Likely (the official doc lists no platforms) | Exists |
| Forza Horizon 6 | PS5 | not released (2027-01-26) | — | — | — | [N6][N7] | n/a | re-check after release |

### 2.2 PlayStation 5: native titles

| Game | Platform | Telemetry | Transport / port | Family | Richness | Evidence | Verdict | Effort |
|---|---|---|---|---|---|---|---|---|
| **Project Motor Racing** | **PS5** (v2.3+, 2026-09-23) | Yes (official setting; no stream report yet) | UDP push; Settings > Preferences: UDP Enabled, Frequency 60, Port 7576, Host = Mac IP | pmr-udp | Rich (community layout) | [O1][V27][V26][V21][N16] | **Likely** | **Gated** |
| F1 24 | PS5 / PS4 / Xbox / PC | Yes | UDP push 20777, format 2024 | ea-f1-udp | Full | [V8][V20][V39][O9][P3] | Confirmed | S |
| F1 23 | PS5 / PS4 / Xbox / PC | Yes | UDP push 20777, format 2023 | ea-f1-udp | Full | [V9][V20][V39][O8] | Confirmed | S–M |
| F1 22 | PS5 (native) / PS4 / Xbox / PC | Yes | UDP push; rate 10/20/30/60 Hz | ea-f1-udp | Full | [O6][V37][O7] | Confirmed | M |
| F1 2021 | PS5 (native) / PS4 / Xbox / PC | Yes | UDP push; formats Legacy–2021 | ea-f1-udp | Full | [O5][V36][C26] | Confirmed | M |
| EA SPORTS WRC | PS5 / Xbox Series | **No** | — | — | — | [V1][V57][V20][O31]; the only console claim is unsourced speculation [F7] | **No** (PC only) | n/a |
| Assetto Corsa Competizione | PS5 / PS4 / Xbox | **No** | — | — | — | [V1][V38][V23][V20][V42] | **No** | n/a |
| GRID Legends, GRID (2019) | consoles | **No** | — | — | — | [V1][V15][O29] | Likely no | n/a |
| DiRT 5 | all platforms | **No** | — | — | — | [V1][V20] | Likely no | n/a |
| WRC Generations / WRC 10 | PS5 / PS4 / Xbox | **No** | — | — | — | [V14][V1] | Likely no (PC only) | n/a |
| Test Drive Unlimited Solar Crown | PS5 / Xbox Series | **No** | — | — | — | [V1][V16] | Likely no (PC only) | n/a |
| Rennsport | PS5 / Xbox / PC | **No** interface found | — | — | — | [O22][F14][N19] | Likely no | n/a |
| NASCAR 25 | PS5 / Xbox | **No** | — | — | — | [F16][V20] | Likely no | n/a |
| Need for Speed (all), CarX Drift Racing Online, Wreckfest (PS5), The Crew Motorfest | PS5 | **No** / no evidence | — | — | — | [V1][F17] | Likely no | n/a |
| MotoGP 24/25, RIDE 5, TT Isle of Man 3, Tokyo Xtreme Racer, JDM, Dakar Desert Rally, Hot Wheels Unleashed 2 | PS5 | unknown, no evidence | — | — | — | absent from [V20][V39][V46]; [N23][N24] | Unverified (not searched in depth) | n/a |

### 2.3 PS4 titles on PS5 (backward compatibility)

| Game | Platform | Telemetry | Transport / port | Family | Richness | Evidence | Verdict | Effort |
|---|---|---|---|---|---|---|---|---|
| **Assetto Corsa** (incl. Ultimate Edition) | PS4 hardware | Yes | Mac → console:9996 handshake, console replies to sender | ac-remote-udp | Medium | [F1][F2][F3][C8][V43][V42][V2] | **Confirmed** | M |
| Assetto Corsa | **PS5 (PS4 build)** | Conflicting | same | ac-remote-udp | Medium | yes: [V2][V1][V45]; no: [V42][V41] | **Conflicting** | **Gated** (probe §1.2) |
| Assetto Corsa | Xbox One | **No** | — | — | — | [V1][V29][V42] | **No** | n/a |
| Gran Turismo Sport | PS4 | Yes | heartbeat → console:33339, stream ← :33340; Salsa20 key `Simulator Interface Packet ver 0.0`, IV2 = seed XOR 0xDEADBEAF; 296 B | gt-simulator-interface | Medium (GT7 variant A) | [C4][V33][V22][V3][P2] | **Confirmed** | S |
| Gran Turismo Sport | PS5 (PS4 build) | Yes (vendor-named) | same | gt-simulator-interface | Medium | [V33][V3][V22] | **Likely** | S |
| Project CARS 2 | PS4 (patch 2.0+), Xbox One | Yes | broadcast 255.255.255.255:5606 (fixed); Options > System: UDP Frequency 1–9, Protocol "Project CARS 2" | pcars2-udp | Full-ish (no setup) | [N1][V30][F4][V4][V22][V26][C10] | **Confirmed** | M–L |
| Project CARS 2 | PS5 / Xbox Series (back-compat) | Vendor tag only | same | pcars2-udp | Full-ish | [V39][V40] | **Unverified** (SIM Dashboard's "slow" page does **not** name PS5 [V7]) | Gated |
| Project CARS (original) | PS4 (patch 7.0+), Xbox One | Yes | broadcast 255.255.255.255:5606; Gameplay > UDP 1–9 (60/s … 1/s) | pcars1-udp | Medium (layout not retrieved) | [N2][F5][V31][V5][C9]; SimHub does not support it on PS4 [V24] | **Confirmed** (PS4); Xbox One vendor-only | **Blocked** (no reachable spec) |
| Project CARS (original) | PS5 (back-compat) | Vendor tag only | same | pcars1-udp | — | [V39] | Unverified | Blocked |
| F1 2019 | PS4 / Xbox One / PC | Yes | UDP push 20777, format 2019 | ea-f1-udp (2019) | Full | [V34][O11][V39] | Confirmed | M |
| F1 2019 | PS5 (back-compat) | Vendor tag only | same | ea-f1-udp | Full | [V39] | Unverified | M |
| F1 2020 | PS4 / Xbox One / PC | Yes (console needs game v1.02+) | UDP push 20777, format 2020 | ea-f1-udp (2020) | Full | [V35][O12][C22] | Confirmed | M |
| F1 2020 | PS5 (back-compat) | Vendor tag only | same | ea-f1-udp | Full | [V39] | Unverified | M |
| MotoGP 18 (motorcycle) | PS4 / Xbox One / PC | Yes | UDP broadcast, undocumented | milestone (no spec) | ? | [V39][F10][V18][V25][N17] | Likely | **Blocked** (Milestone "refused to publish the telemetry structure" [V25]; bike game) |
| Project CARS 3 | PS4 / Xbox One (PS5 back-compat) | **No** ("NOT(!) unlocked on Consoles") | — | — | — | [V6][V32][V26] | Likely no (one pre-launch motion-seat guide disagrees; it could not be read [V60]) | n/a |
| DiRT Rally 2.0, DiRT Rally, DiRT 4 | PS4 / Xbox One | **No** | — | — | — | [V1][V20][V52] | Confirmed no (DR2.0); likely no (DiRT 4) | n/a |
| WRC 7 / 8 / 9 / 10 | PS4 / Xbox | **No** ("modding is not possible") | — | — | — | [V1] | Likely no | n/a |
| NASCAR Heat 3 / 4 / 5 | PS4 / PS5 / Xbox | **No** | — | — | — | [V1][F9] | Likely no | n/a |
| V-Rally 4, Driveclub, Dakar 18, Gravel | PS4 | **No** / unknown | — | — | — | [V1][V20][V25] | Likely no; Gravel unverified | n/a |

### 2.4 Xbox (for sharing)

| Game | Platform | Telemetry | Transport | Family | Verdict | Effort |
|---|---|---|---|---|---|---|
| F1 2019 → F1 25 | Xbox One / Series | Yes | UDP push | ea-f1-udp | Confirmed [O28][V20][V39] | Exists (2025/26) / S–M (older) |
| Forza (FM7, FM2023, FH4 on One, FH5, FH6) | Xbox | Yes | Data Out | forza-data-out | see §2.1 | Exists |
| Project Motor Racing | Xbox Series X\|S (v2.3+) | Yes (official "console platforms") | UDP 7576 | pmr-udp | **Likely** [O1]. No third-party Xbox evidence; SIMRIG lists PMR as "PC / PlayStation" only [V26]. | Gated |
| Project CARS 2 | Xbox One | Yes | broadcast 5606 | pcars2-udp | Confirmed (vendor docs) [V4][V26][V30] | M–L |
| Project CARS (original) | Xbox One | Yes | broadcast 5606 | pcars1-udp | Likely (vendor-only) [V5][V40][V41] | Blocked |
| Assetto Corsa, ACC, EA WRC, DiRT, GRID, WRC, pCARS 3 | Xbox | **No** | — | — | [V1] | n/a |

### 2.5 PC titles the Mac can receive directly (no relay)

| Game | Telemetry | Transport / port | Family | Richness | Evidence | Verdict | Effort |
|---|---|---|---|---|---|---|---|
| Project Motor Racing | Yes | UDP 7576; Host unicast or multicast 224.0.0.150 (community-reported PC default) | pmr-udp | Rich | [O2][O3][V13][V28][V21][V50][C1][C2][C3] | Confirmed | Gated |
| Automobilista 2 | Yes | broadcast 255.255.255.255:5606, Options > System, UDP Protocol "Project CARS 2" | pcars2-udp | Full-ish | [V55][C6][C9][F6] | Confirmed | M–L (shared with pCARS 2) |
| Project CARS 2 / Project CARS 3 | Yes | broadcast 5606 | pcars2-udp | Full-ish | [V4][V6][V32] | Confirmed (PC2) / Likely (PC3) | shared |
| Assetto Corsa (2014) | Yes | Mac → PC:9996 handshake (always on once a session loads) | ac-remote-udp | Medium | [O13][C6][C5][P1] | Confirmed | M |
| Assetto Corsa Competizione | Yes (no inputs) | Broadcasting API, register to PC:`updListenerPort` (often 9000) | acc-broadcast | Medium (all cars; no inputs, tyres or fuel) | [P1] §3.2 | Confirmed (community protocol from Kunos SDK sample) | M |
| EA SPORTS WRC | Yes (since v1.3) | `Documents/My Games/WRC/telemetry/config.json`: per-packet `ip`, port, `frequencyHz`, `bEnabled` (default session_update → 20777, others → 20778, all disabled) | ea-wrc-json | Rich (stage distance and length, location/route ids) | [N8][C18][V57][F11] | Confirmed | L |
| DiRT Rally 2.0 / DiRT Rally / DiRT 4 | Yes | `hardware_settings_config.xml` `<udp enabled extradata="3" ip port="20777">` | codemasters-legacy (66 × f32) | Medium | [V52][C17][C23] | Confirmed (no official spec) | M |
| GRID Legends / GRID (2019) | Yes | same XML mechanism | codemasters-legacy | Medium | [V15] | Likely | M (shared) |
| WRC Generations | Yes | `Documents/My Games/WRCG/UserSettings.cfg` `WRC.Telemetry.EnableTelemetry = true;` | KT/Nacon (users report SimHub's DR2 plugin works) | ? | [V53][F8] | Likely | Blocked (no spec) |
| Test Drive Unlimited Solar Crown | Yes | `UserSettings.cfg` `Rc2.Telemetry.*` (address, port 20777) | KT/Nacon | ? | [V16][V21] | Likely | Blocked (no spec) |
| Live for Speed | Yes | OutSim / OutGauge UDP to any IP:port in `cfg.txt` | outgauge / outsim | Rich (OutSimPack2 has lap distance) | [O17][C15][F15] | Confirmed (spec ships with the game) | S–M |
| BeamNG.drive | Yes | OutGauge + MotionSim (`BNG1`), IP/port in Options > Other | outgauge + beamng-motionsim | Basic (no laps) | [O15][V54][V51] | Confirmed | S (low value) |
| KartKraft | Yes | FlatBuffers (`KKFB`) to one or more endpoints | kartkraft-flatbuffers | Rich | [O16][V56][N20] | Confirmed (repo dormant since 2023) | S–M |
| Kart Racing Pro | Yes | game-shipped `proxy_udp64.dlo` + `proxy_udp.ini` | piboso-proxy-udp | ? (changes between releases) | [O19][C20] | Likely | Blocked (no spec) |
| Richard Burns Rally (RSF / NGP) | Yes | RSF Launcher > Advanced > Telemetry, ip:port list (e.g. 6776) | rbr-ngp | Rich | [C16][V21] | Likely | Blocked (header unlicensed) |
| Wreckfest 2 (Early Access) | Yes (since 2025-08-28) | `telemetry/config.json`, UDP 23123 | own (no public spec) | ? | [N9][V17][C19][V21] | Confirmed (exists) | Blocked (no spec) |

### 2.6 PC titles that need a Windows relay

| Game | Interface | Family | Richness | Evidence | Verdict | Effort |
|---|---|---|---|---|---|---|
| iRacing | `Local\IRSDKMemMapFileName` mmap, or post-session `.ibt` | irsdk | Full (no live world XYZ) | [P1] §4, [C11] | Confirmed | L (relay); track-data legal hold [P4] |
| Le Mans Ultimate | native `LMU_Data` mmap (v1.2+, needs Enable Plugins ON + restart); REST :6397 (local) | rf2-style shm (LMU native) | Full | [N11][C12][V51][V21] | Confirmed | L |
| rFactor 2 | Internals plugin DLL → shm (no native output) | rf2-shm | Full | [C13][C24][V51] | Confirmed | L (own plugin) |
| RaceRoom | `$R3E` mmap, no plugin | r3e-shm | Full (track/layout ids, lap distance) | [O14][V51] | Confirmed | L, then S |
| Assetto Corsa EVO (EA 0.x) | `Local\acevo_pmf_physics/graphics/static` | ac-evo-shm | Rich (no tyre wear) | [C14][O20][V51][N14][O21] | Likely (Kunos guide unfetched) | L (layout still changing) |
| ACC / AC | `Local\acpmf_*` | acc/ac shm | Full | [P1] §2.1, §3.1 | Confirmed | L |
| Automobilista 2 (shm) | `$pcars2$` | pcars2-shm | Full+ | [V55][V51][F6] | Confirmed | L (UDP alternative exists) |
| Euro Truck Sim 2 / American Truck Sim | SCS SDK plugin; **runs on macOS too** | scs-sdk | Basic (no laps) | [O18][O30][C21] | Confirmed | L; out of scope |

---

## 3. Per-protocol-family sections

### 3.1 ea-f1-udp: extend the existing F1 adapter (formats 2019–2024)

- **What exists.** pitwall decodes formats 2025 and 2026 and rejects older formats with a message [P6][P3].
- **Transport.** Identical across years: one-way UDP push, default port 20777, optional broadcast, no handshake [O5][O6][P3] §9.
- **Format 2024.** Six structs differ from 2025, and the delta is fully listed in [P3] §6:
  - Participants: 48-character names;
  - Lobby;
  - FinalClassification;
  - CarDamage: no `tyreBlisters`;
  - MotionEx: 237 B;
  - no LapPositions packet.

  This also lets F1 25 users who left UDP Format on 2024 connect. Effort **S**.
- **Format 2023.** The 2023→2024 delta is **not** in pitwall's docs. EA's F1 23 spec [O8] is behind forums that return 403 to non-browser fetchers, so read it in a real browser. Effort **S–M**.
- **Formats 2022 / 2021 / 2020 / 2019.** Each has its own sizes and header:
  - 2020 added `m_secondaryPlayerCarIndex` and the Final Classification and Lobby packets [O12];
  - 2019 sizes are Motion 1343, Session 149, Lap 843, Event 32, Participants 1104, Setups 843, Telemetry 1347, Status 1143 [O11].

  The specs come from the defunct Codemasters forum via mirrors [O11][O12] (mirror licence unknown: implement from the text, do not copy package code) and from EA [O7]. Effort **M** each; low priority.
- **Console notes.**
  - F1 22 on console needs the UDP Format toggled to another value and back to 2022 "due to a bug in the F1 2022 game" [V37]. The Connect tab should say so.
  - F1 2020 on console needs game v1.02 or later [V35].
  - EA's F1 22 PS5 page lists formats only up to 2021. This is an EA copy-paste error [O6].
- **Send rates per title** (Thrustmaster): F1 25 and the 2026 DLC at 60 Hz with format 2026; F1 24 at 60 Hz with 2023; F1 23 at 120 Hz with 2023; F1 2019–22 at 20 Hz with 2020 [O28].
- **Track knowledge.** The same Session-packet skeleton as F1 25 (track length, sector starts) per year's track-ID appendix [P4] §2 L0a.

### 3.2 gt-simulator-interface: GT Sport as a GT7 sibling

- **Protocol.** The same heartbeat/Salsa20 interface [P2] "Older titles":
  - console port 33339, receiver port 33340;
  - key `Simulator Interface Packet ver 0.0`;
  - IV seed at 0x40, IV2 = seed XOR 0xDEADBEAF;
  - input 0x128 (296) bytes;
  - decrypted magic shared with GT7 (PDTools, MIT) [C4].
- **Implementation.** Parameterise `ingest/gt7_heartbeat.py` and the GT7 adapter by (ports, key, XOR) and dispatch on the 296-byte length. No B, `~` or C variants are known for GT Sport.
- **Limits.**
  - Online services ended 2024-01-31, so only offline sessions produce data [N4].
  - RS Dash says its "Advanced Analysis" cannot work with GTS output [V33].
  - RS Dash also mentions a "NAT Type 2" requirement; this is unexplained and unverified.
  - Field-for-field identity with GT7 variant A is inferred from PDTools' single parser. Confirm it with a capture.
- **Track knowledge.** There is no track id; geometry matching is needed. GT7 signatures [P4] may not transfer to GTS (unverified).

### 3.3 pcars2-udp: Project CARS 2, Automobilista 2, Project CARS 3 (PC)

- **Transport.**
  - One-way **broadcast to 255.255.255.255:5606**. The port is fixed, there is no destination-IP field and no handshake [V30][C10][F4].
  - Console: Options > System ("Configurate External Apps"): UDP Frequency 1–9 (1 = fastest, about 60/s) and UDP Protocol Version "Project CARS 2" (pick PC2, not PC1). Patch 2.0 or later is required [V4][N1].
  - AMS2: Options > System, the same two fields [V55]. tcpdump shows `255.255.255.255:5606` [C6].
  - A limited broadcast leaves only the sender's default-route interface, so the Mac must be on that L2 segment.
- **Reliability (the main risk).**
  - SIM Dashboard removed console pCARS 1/2 from its iOS app as "slow, unreliable", with "a negative impact on the whole local network". It advises 5 GHz Wi-Fi, a medium frequency and disabling router UDP-flood protection [V4][V7].
  - The console sometimes sends on the wrong interface (LAN vs Wi-Fi) [V4].
  - Crew Chief's pCARS2 network mode is commented out: "TODO: reinstate this when it actually works" [C9].
  - **Measure the real rate on a capture.**
- **Layout (sources disagree, so captures are mandatory).**
  - All sources agree on a 12-byte packet base (packet number, category number, partial index/number, packet type at byte 10, version at byte 11) [C9][C10].
  - They disagree on struct sizes:

    | Source | Telemetry | Race definition | Participants | Timings | Game state | Time stats |
    |---|---|---|---|---|---|---|
    | SMS header copy (tyretrack) [C10] | 559 | 308 | 1136 | 1063 (handler v3) | 24 | 1024 |
    | Second header copy (mplutka) [C10] | 556 | — | — | 1059 (v1) | — | — |
    | Crew Chief MIT mirror [C9] | 538 | 308 | 1040 | 993 | 24 | 784 |

  - Header offset comments are unreliable: for example, sJoyPad0 is commented 376 but computes to 373 under `pack(1)`.
  - **Dispatch on (packet type, version, datagram length)** and settle the layout per game with pitwall captures. Crew Chief also logs "undocumented" weather and vehicle-names packets [C9].
  - The race-definition and participants packets are front-loaded and then backed off ("logarithmic decrease") [C10]. Start the listener before entering a session.
- **Data.**
  - Unfiltered throttle, brake, steer and clutch; speed, rpm, gear.
  - Tyre temps (tread/layer/carcass/rim/air, L/C/R) and wear; brake temps; fuel; damage.
  - Track location and variation strings plus **track length**; per-car u16 **current lap distance**, sector, lap and sector times; ambient and track temperature; rain [C10][C9].
  - No setup packet.
- **Track knowledge.** Excellent: names, length and per-car lap distance give L0a + L0b in the [P4] sense.
- **Game status.** Project CARS 1, 2 and 3 are delisted. pCARS 3 servers shut down 2026-02-24, so only owners and disc buyers have it [N3]. AMS2 is the live PC title. pCARS 3 console UDP is not unlocked [V6][V32].

### 3.4 pmr-udp: Project Motor Racing

**Platforms.**

| Platform | Evidence | Verdict |
|---|---|---|
| PC | Since launch: "PMR does have UDP telemetry ... Settings > Preferences" [O2]. Sector-time fix in 2.0.0.2 [O3]. SimHub closed-beta support "with Straight4's help", 2025-10-13 [V21]. Qubic: "fully supported" [V50]. | Confirmed |
| Consoles | v2.3 (2026-09-23): "Enabled UDP telemetry settings on console platforms" [O1]. SIMRIG has a console setup page [V27] and lists "PC / PlayStation" [V26]. SimHub updated its PMR setup instructions on 2026-09-30 [V21]. | Likely (PS5, Xbox) |

**Counter-evidence for consoles.**
- No first-hand console stream report found, about 2.5 weeks after release.
- SIM Dashboard still lists PMR on consoles as having no telemetry interface [V1]. This is undated and probably pre-v2.3.
- SimHub shows PMR without a "(PC + Consoles)" tag [V20].
- Console builds have lagged PC before: consoles were rolled back from 1.5.0.5 to 1.5.0.4 in Jan 2026 [N15].
- Hotfix 2.3.0.1 says only "Multiple fixes and improvements" [O4].

**Transport.**
- One-way UDP push: UDP Enabled, UDP Frequency (default 60), UDP Port (default 7576), UDP Host [V27][V13][V28].
- On console set Host = the Mac's LAN IP (unicast).
- On PC the default appears to be multicast 224.0.0.150. That value comes from Simulator-Controller's default [C3] and an Asetek search snippet only. The MIT SDK has it as a constant but defaults to unicast `0.0.0.0:7576` (verified 2026-10-10) [C1].
- SimHub's auto-config forces multicast off (9.10.13, 2025-11-26) [V21]. SIMRIG warns that non-local hosts on PC can cause "performance and network issues" [V28].
- SIM Dashboard reports the game sometimes stops sending until UDP is toggled off and on (PC) [V13].
- There is a single destination, so fan out on the Mac. One community tool defaults to port 7580 [C2]; use the in-game value.

**Format.**
- The game's own format, explicitly **not** the pCARS2/SMS protocol [C2].
- Header: uint8 packet type, then uint16 LE version.
- Types:
  - 0 **RaceInfo** v1: track, layout, season, weather, session and game-mode strings, plus layout length;
  - 1 **ParticipantRaceState** v1: all cars, with position, lap, lap times, `LapProgressFraction`, current sector, sector times, pit status and flags;
  - 2 **ParticipantVehicleTelemetry** v2: inputs, per-wheel slip and temperatures, pressure, setup values, chassis, drivetrain, suspension;
  - 3 **SessionStopped**.

  Type and version facts were verified in the MIT SDK on 2026-10-10 [C1][C2].
- Strings and float arrays are uint8-length-prefixed, so packets are variable length [C2].
- **There is no official byte-level spec.** The MIT SDK marks several units "best guess, not empirically confirmed" and cites a 2026-09-13 rig capture [C1]. That makes it community-documented, reverse-engineered data in the same tier as GT7.

**Plan.**
1. James enables UDP on PS5 PMR (Host = Mac IP, Port 7576) and pitwall records raw `.pwcap`. This needs the capture-only mode in §3.10.
2. Ask Straight4 (forum/Discord) for the spec, citing their SimHub collaboration.
3. Implement pitwall's own decoder from the MIT SDK's documented facts plus the captures. Fields whose units stay unconfirmed are `None` ("unknown stays unknown").

**Track knowledge.**
- RaceInfo track and layout strings plus layout length give identity.
- Lap distance = `LapProgressFraction` × length.
- Sector boundaries come from the race state of all cars.
- The all-car race state supports an L0b field model [P4].

### 3.5 ac-remote-udp: Assetto Corsa (2014)

- **Protocol.** The Kunos spec [O13] and pitwall's byte layout [P1] §2.2:
  - handshake struct = 3 × int32 (identifier, version, operationId);
  - ops 0 HANDSHAKE, 1 SUBSCRIBE_UPDATE, 2 SUBSCRIBE_SPOT, 3 DISMISS;
  - 408-byte handshake response (UTF-16LE strings), 328-byte RTCarInfo, 212-byte RTLap.
- **PC.** The interface "is unconditionally on once a session is loaded"; RTCarInfo arrives at about 333 Hz, and the client re-handshakes every 3 s after menu silence [C6]. Size dispatch 408/328/212 is confirmed by an MIT client [C5].
- **Rate.** Reported rates conflict (~333 Hz [C6], 60 Hz, ~20 Hz [P1]). Measure them.
- **Console.** See §1.2.
- **Data.** Inputs, speed, gear/rpm, `carPositionNormalized` (0..1), world XYZ, lap times, per-wheel slip/load. **No** fuel, tyre temps, wear, sectors or weather. RS Dash says console data is lap times only, with no sector data [V29].
- **pitwall shape.** A handshake-capable ingest source, like the GT7 heartbeat in `ingest/gt7_heartbeat.py`, plus a pure adapter (ADR-002).
- **Track knowledge.** Handshake track and config strings (disputed on console [F13]). Lap distance needs a learned length: `carPositionNormalized` × the L3 model length.

### 3.6 acc-broadcast and ac-evo (possible)

- **ACC Broadcasting** is fully described in [P1] §3.2:
  - register with protocol version 4 to `updListenerPort` from `broadcasting.json`, which is UTF-16LE;
  - per-car realtime updates with `splinePosition`, km/h, gear and lap info;
  - TRACK_DATA with `trackId` and `trackMeters`.

  It has **no inputs**, so it cannot drive input coaching. It does feed the L0b-ACC field model planned in [P4] Phase 6. Only after counsel: the ACC EULA questions are in [P4] §3.
- **New lead (unverified).** The MIT SDK [C1] added an AC EVO ("ACE") UDP client on 2026-07-27 with the commit message "Added port of ACC UDP protocol to ACE UDP". It reads `Documents\ACE\...\broadcasting.json`. No Kunos changelog mentions a broadcasting API for AC EVO [O20], and Steam users were still asking for "UDP telemetry data out" [F12]. Treat it as a question to settle (§10), not a capability.

### 3.7 ea-wrc-json: EA SPORTS WRC (PC only)

- **Availability.** UDP was added on PC in v1.3 [N8]. There is none on consoles [V1][V57].
- **Configuration.** `Documents/My Games/WRC/telemetry/config.json` (schema 2) assigns packets to endpoints [C18]:
  - session_update → 127.0.0.1:20777 with `frequencyHz` −1;
  - start/end/pause/resume → 20778;
  - every packet `bEnabled` false by default (D-BOX is on by default).
- **Spec.** The game-generated `readme/channels.json` plus `udp/<structure>.json` are a **self-describing official spec**: little-endian, "packed in order of ID", a single "session" scope, and 66 channels including `stage_current_distance`, `stage_length`, `location_id`, `route_id`, vehicle position, inputs and gear [C18].
- **Known issue.** Adding certain channels in 1.8.0 broke output; EA staff advised regenerating the folder [F11].
- **pitwall shape.** A schema-driven decoder that reads the user's own JSON (or a pinned `wrc` layout). Do **not** vendor the GPL repo's copy [C18].
- **Track knowledge.** A stage (point-to-point) model is needed: location_id/route_id = track id, `stage_length` = length, `stage_current_distance` = distance.
- **Port clash.** The default 20777 collides with F1. Tell users to choose another port (§3.10).

### 3.8 Other PC families (later)

- **codemasters-legacy (DiRT Rally 1/2.0, DiRT 4, GRID 2019/Legends; PC).**
  - XML-enabled UDP, `extradata="3"`, a fixed 66 × float32 (264 B) packet [V52][C23].
  - Codemasters never published a spec; the MIT dr2_logger documents the layout and has stage tables [C17].
  - Track identity is by stage length.
- **outgauge / outsim (Live for Speed; BeamNG OutGauge).**
  - LFS ships `docs/InSim.txt` and `OutSimPack.txt` with the game [O17][C15].
  - OutSim `Opts` bits select blocks; `OSO_DISTANCE` adds `CurrentLapDist` and `IndexedDistance`.
  - Only the user's or viewed car is sent [C15].
  - LFS commercial-use terms are unchecked.
  - BeamNG's OutGauge hardcodes several fields to 0, and its MotionSim (`BNG1`) has no laps [O15].
- **kartkraft-flatbuffers.** Official MIT schema [O16] with `TrackConfig` (name, `trackLengthMetres`, `numSectors`) and `normalisedTrackPos` per kart. Niche.
- **Blocked:**
  - Kart Racing Pro (no spec; changes between releases [C20]);
  - RBR NGP (only an unlicensed header [C16]);
  - Wreckfest 2 (no spec [N9]);
  - WRC Generations / TDU Solar Crown (no spec [V53][V16]; their `*.Telemetry` key styles suggest a shared KT format, unverified);
  - Project CARS 1 (no reachable layout);
  - MotoGP 18 (Milestone withheld the structure [V25]).

### 3.9 forza-data-out on PS5

- **FH5 PS5** (released 2025-04-29 [O24]): no source mentions Data Out on PS5.
  - SIMRIG lists FH5 as "PC / XBOX" [V26].
  - SIM Dashboard's FH5 page tells users to enable the "Xbox platform" [V10].
  - Sim Racing Studio lists FH5 under a combined "PS4/5 and Xbox" heading, without saying which platform [V41].

  This costs one menu check (§1.1, rank 2).
- **FH6 PS5** is dated 2027-01-26 [N6].

### 3.10 Cross-cutting ingest requirements and ports

**Prerequisites in pitwall:**
- **Decoder-less raw capture mode.** `UdpListener` already writes `.pwcap`, but the CLI has no capture-only command for an arbitrary port (`src/pitwall/cli.py` defines serve, simulate, replay, send, sessions, report, ask, llm-check, capabilities and token). Add one, for example `pitwall capture --port N`, plus a Connect-page toggle. It is the first step for PMR, pCARS2, FH5-on-PS5 and GT Sport.
- **Broadcast reception** on 5606 (pcars2-udp).
- **Optional multicast join** (PMR on PC only; on console, use unicast).
- **Handshake-capable sources** (AC; ACC broadcast registration), following the GT7 heartbeat pattern.

**Port plan.** None of these clash with the ports Pitwall refuses because other local services commonly use them
(`integrations.RESERVED_PORTS`: 1234, 5432, 8081, 8091, 8092, 8888) or with pitwall's HTTP port 8770.

| Port | Use | Note |
|---|---|---|
| 20777 | F1 (in) | **clashes** with the EA WRC / DR2 / GRID / TDU defaults: give those a different port |
| 33740 | GT7 (in) | |
| 33340 | GT Sport (in) | |
| 7576 | PMR (in) | |
| 5606 | pCARS2 / AMS2 broadcast (in) | |
| 9996 | AC (out to console/PC) | |
| ~9000 | ACC broadcasting (out to PC) | |
| 20777 / 20778 | EA WRC defaults | |
| 6776 | RBR | |
| 5000 | KartKraft | example |
| 4444 | BeamNG | |
| 23123 | Wreckfest 2 | |

---

## 4. What needs a Windows relay

This follows [P1] §6 recommendation 2: one pitwall-defined relay protocol. A small Windows service reads the mapping and streams timestamped frames over UDP to the Mac; pitwall records them as `.pwcap` like any other source. Key the relay frames on each game's own version field (`R3E_VERSION`, LMU header version, AC EVO `sm_version`).

| Order | Game | Mapping / mechanism | Spec source | Licence of the spec | Notes |
|---|---|---|---|---|---|
| 1 | RaceRoom | `$R3E`, v3.5, no plugin | `sample-c/src/r3e.h` [O14] | **Unlicense** (official Sector3 repo) | Cleanest first target: track_id, layout_id, layout_length, lap_distance(_fraction), raw inputs [O14] |
| 2 | Le Mans Ultimate | `LMU_Data` (100 Hz telemetry, 5 Hz scoring); Settings > Gameplay > Enable Plugins ON + restart | game-shipped SharedMemory header in `Support/` [N11] | not checked: read the notice before use | Do **not** use the GPL rF2 plugin [C13]. REST :6397 may be localhost-only (unverified) [C12]. |
| 3 | ACC | `Local\acpmf_*` | Kunos ACC Shared Memory PDF v1.8.12 [P1] §3.1 | Kunos doc (forum login) | Adds inputs, tyres and rain forecasts that broadcasting lacks [P1] |
| 4 | iRacing | irsdk mmap at 60 Hz (`_ST` 360 Hz sub-samples) | pyirsdk [C11] | MIT | Track-data use is on legal hold per iRacing ToU [P4] |
| 5 | AC (2014) | `Local\acpmf_*` | Kunos Shared Memory Reference; mdjarv port (MIT) [P1] §2.1 | Kunos doc / MIT port | Only if richer data than UDP 9996 is wanted |
| 6 | AMS2 | `$pcars2$` | game-shipped `SharedMemory.h` (Support folder) [F6] | not checked | The UDP family (§3.3) covers most needs without a relay |
| 7 | rFactor 2 | Internals plugin → shm | ISI/S397 InternalsPlugin sample (#7 or #8 per derived READMEs) [C24] | terms unverified | Must write pitwall's own plugin; TheIronWolf plugin and TinyPedal are GPL-3.0 [C13] |
| 8 | AC EVO | `acevo_pmf_physics` (~333 Hz) / graphics / static | Kunos Steam guide #3707421508 [O21] (unfetched) | official | Reworked in 0.5 and 0.6 [N14][O20]; tyre wear is all zeros; key on `sm_version` [C14]. `npos` + `track_length_m` exist, contradicting the "AC EVO (no lap distance)" row in [P4] §6.1. |
| — | ETS2 / ATS | SCS SDK plugin (also on macOS) | SCS SDK 1.15 [O18] | not stated on wiki | No laps: not a coaching target |

---

## 5. Games with no telemetry

### 5.1 No interface on any platform

| Game | Evidence |
|---|---|
| DiRT 5 | "no telemetry interface"; SIM Dashboard asks users to request it from Codemasters [V1] |
| V-Rally 4, Driveclub, Dakar 18, FIA European Truck Racing | [V1] |
| Need for Speed (all titles incl. Unbound), CarX Drift Racing Online | [V1] |
| Wreckfest (2018) | no official output; only memory hacks [V1][F17] |
| The Crew / The Crew 2 | "only a motion interface for raceseats but no telemetry data" [V1]. Motorfest: an unanswered SimHub request [F18]. |
| NASCAR Heat 3 / 4 / 5 | [V1][F9]. SimHub lists Heat 5 without a platform tag [V20]; the PC mechanism is unknown, possibly memory reading. |
| Rennsport | official FAQ: "SimHub integration is not currently supported" [O22] |
| NASCAR 25 (PS5 / Xbox) | "There is no planned support for telemetry" (SimXperience forum, undated) [F16]. The iRacing–Cosworth Pi Toolbox is a first-party tool, not a feed [N21]. |
| Gravel, Hot Wheels Unleashed 2, Tokyo Xtreme Racer, JDM, MotoGP 24/25, RIDE 5, TT IoM 3 | no evidence found; absent from every list checked [V20][V39][V46]. Unverified, not proven negative. |

### 5.2 Interface on PC only (console builds have none)

| Game | Evidence |
|---|---|
| ACC | [V1][V38][V23][V42] |
| EA WRC | [V1][V57] |
| GRID / GRID Legends | [V1] |
| DiRT Rally / 2.0 / DiRT 4 | [V1][V20] |
| WRC 7–10 / Generations | [V1][V14] |
| TDU Solar Crown | [V1] |
| Project CARS 3 | [V6][V32] |
| Assetto Corsa (Xbox One only; PS4 has it) | [V1] |
| Forza Horizon 4 on Xbox Series X\|S (broken) | [V11] |

---

## 6. Licensing notes

pitwall rule: implement from specifications and community documentation; never copy GPL or unlicensed code ([P7], CLAUDE.md).

| Source | Licence | Use |
|---|---|---|
| EA F1 UDP specs, 2019–2026 [O7]–[O12] | published by EA/Codemasters for third-party apps | implement from spec. Readthedocs mirrors [O11][O12]: package licence unknown; use the text, not the code. |
| cm-telemetry [C22]; f1-2021-udp [C26] | MIT | read for facts |
| Kunos AC Remote Telemetry spec [O13] | no licence stated (public Google Doc) | implement from spec |
| rickwest/ac-remote-telemetry-client [C5], crmne/moza-rev [C6] | MIT | read with attribution |
| iimetra/assetto-corsa-telemetry-4j [C7] | MIT per README only; **no LICENSE file** | treat as unlicensed: facts only |
| Egocentrix/AC-UDP-Connection, MrDoor1234/assetto-corsa-telemetry | no licence | facts only |
| rusty-telemetry [C25] | AGPL-3.0 | do not copy |
| ch3p4ll3/ACUDP [C25] | GPL-3.0 | do not copy |
| vthinsel/Python_UDP_Receiver capture [C8] | **CC0-1.0** | usable as a third-party fixture after download with permission; never unpickle |
| SMS_UDP_Definitions.hpp (all copies) [C10] | **no licence text** | read as a spec; do not vendor |
| Crew Chief PC2 structs [C9] | MIT, Britton IT Ltd | readable with attribution |
| lmirel/mfc | GPL-3.0 | do not copy |
| saildeep/pcars2-udp, jamesremuscat/pcars | no licence | facts only |
| devology-uk/sim-racing-sdk [C1] | **MIT** (GitHub API, re-checked 2026-10-10) | readable for PMR/ACC/AMS2/LMU facts with attribution. It is reverse-engineered ("best guess" units). |
| Ricozwar/pmr-results-helper [C2] | **proprietary**, "All rights reserved" | facts only, never copy |
| SeriousOldMan/Simulator-Controller [C3] | NOASSERTION | facts (defaults) only |
| Nenkai/PDTools [C4] | MIT | GT Sport crypto facts |
| sector3studios/r3e-api [O14] | **Unlicense** | the header may be used directly |
| LMU game-shipped SharedMemory header [N11] | not checked | read its notice before relay work |
| TheIronWolf rF2SharedMemoryMapPlugin [C13], TinyPedal | GPL-3.0 | **do not copy**; use the ISI/S397 sample (terms unverified) |
| albertowd/live-telemetry-evo [C14] | no licence | orientation only; implement from Kunos's guide [O21] |
| kutu/pyirsdk [C11] | MIT | relay-side reference |
| iRacing ToU | — | legal hold for track data [P4] |
| KartKraft schema [O16] | MIT (official) | usable |
| BeamNG protocol files [O15] | bCDDL (permissive per BeamNG) | usable |
| LFS `InSim.txt` / `OutSimPack.txt` | game docs | the copy in KamileonPL/lfs-pit-wall sits in a GPL-3.0 repo, but the file is LFS's own [C15]. Check LFS commercial-use terms. |
| RBR `TelemetryData.h` [C16] | no licence notice | unlicensed until RSF/NGP grant permission |
| ErlerPhilipp/dr2_logger [C17] | MIT | DR2 layout facts with attribution |
| Spacefreak18/simapi [C23] | LGPL-3.0 | do not copy |
| EA WRC readme/channels.json | game-generated official spec | read the user's own files. The vAzhure copy [C18] is in a GPL-3.0 repo: do not vendor. |
| timderes/krp-app, thomas4f/mxbmrp3 [C20]; SYSTEMATI0N/WF2_DSX [C19]; RenCloud/scs-sdk-plugin [C21] | MIT | facts only (no specs for these games) |
| Funbit/ets2-telemetry-server | GPL-3.0 | do not copy |

---

## 7. Suggested `capabilities.py` updates

These are suggestions only. They need a separate change with tests, and statuses may only be upgraded with evidence.

| Row | Today [P6] | Suggest | Evidence |
|---|---|---|---|
| "Assetto Corsa (original) – PS4 / Xbox One – UNVERIFIED" | one row | Split into three rows: **PS4: COMMUNITY_DOCUMENTED** (console use 2017–2020); **PS5 (PS4 build): UNVERIFIED** (vendor conflict, probe pending); **Xbox One: UNSUPPORTED** | §1.2 |
| (missing) Project Motor Racing | — | Add rows: **PC: COMMUNITY_DOCUMENTED, not implemented** (layout community-only); **PS5/Xbox: UNVERIFIED** (official setting, no stream seen) | §3.4 |
| (missing) Gran Turismo Sport | — | **PS4/PS5: COMMUNITY_DOCUMENTED, not implemented** | §3.2 |
| (missing) Project CARS 2 / AMS2 | — | **PS4/XB1/PC: COMMUNITY_DOCUMENTED, not implemented**; **PS5: UNVERIFIED** | §3.3 |
| "F1 24 / older – UNSUPPORTED" | rejected with a message | Keep until implemented, but note format 2024 is a known small delta [P3] §6 | §3.1 |
| Forza Horizon note "FH5 on PS5: Data Out not confirmed" | already correct | add "FH4 Data Out broken on Xbox Series X\|S" | [V11] |
| (missing) explicit console negatives | — | EA WRC, GRID, DiRT, WRC Gen, TDU SC, pCARS3 on consoles: UNSUPPORTED | §5.2 |

Doc staleness spotted in passing:
- `docs/status.md` still says GT7 and Forza are "not implemented", while `capabilities.py` marks them implemented.
- [P4] §6.1 row G says AC EVO has no lap distance.

---

## 8. Not released yet: re-check dates

| Game | Platform | Status | Source |
|---|---|---|---|
| Forza Horizon 6 | PS5 | dated 2027-01-26 | [N6][N7] |
| Le Mans Ultimate | PS5 / Xbox | "early-to-mid 2027" | [N12] |
| Assetto Corsa EVO | PS5 / Xbox | after PC 1.0; port in development by a satellite team | [N13] |
| Wreckfest 2 | consoles | no date; "once we're ready, we'll talk about the console release" | [N10] |

When each ships, check whether the console build keeps its PC telemetry; the original Wreckfest on PS5 had none [V1].

---

## 9. Prioritised protocol families: spec sources and doc paths

Ordered by value for this PS5 user, then for sharing (Xbox, then PC). This excludes F1, GT7 and Forza; their extensions are in §3.1, §3.2 and §3.9. Each doc path is where the byte-level protocol write-up should live before implementation.

| # | Family | Games | Why this rank | Spec sources | Spec licence | Doc path |
|---|---|---|---|---|---|---|
| 1 | **pmr-udp** | Project Motor Racing (PS5, Xbox Series, PC) | Only current PS5-native sim with newly enabled console UDP [O1]; rich data, Mac-direct | No official spec. Official notes and FAQ [O1][O2][O3]; MIT community decoder [C1]; proprietary parser, facts only [C2]; vendor setup [V27][V28][V13]; pitwall PS5 captures (to make); request to Straight4 | community MIT + own captures | `docs/research/protocols/pmr-udp.md` |
| 2 | **ac-remote-udp** | Assetto Corsa 2014 (PS4 build on PS5: probe; PC: confirmed) | Possible PS5 win with a ready probe plan; official PC spec; existing layout [P1] §2.2 | Kunos spec [O13]; MIT clients [C5][C6]; PS4 forum evidence [F1][F2][F3]; CC0 PS4 capture [C8] | spec unlicensed (public doc); clients MIT | `docs/research/protocols/ac-remote-udp.md` |
| 3 | **pcars2-udp** | Project CARS 2 (PS4/XB1; PS5 unverified), Automobilista 2 (PC), Project CARS 3 (PC) | Some PS5 chance; for sharing, one parser covers three games including AMS2 with no relay | SMS_UDP_Definitions.hpp copies [C10] (no licence; read as spec); Crew Chief MIT mirror [C9]; moza-rev AMS2 observations [C6]; Reiza forum [F6]; vendor setup [V4][V30][V55] | header unlicensed; mirror MIT | `docs/research/protocols/pcars2-udp.md` |
| 4 | **windows-shm-relay** | RaceRoom → LMU → ACC → iRacing → AC → AMS2 shm → rF2 → AC EVO | Unlocks the main PC sims for sharing; no PS5 value | r3e.h [O14]; LMU shipped header [N11]; Kunos ACC/AC shared-memory docs [P1]; pyirsdk [C11]; Kunos AC EVO guide [O21]; ISI InternalsPlugin sample [C24] | Unlicense / per-game / MIT; avoid GPL [C13] | `docs/research/protocols/windows-shm-relay.md` |
| 5 | **acc-broadcast** | Assetto Corsa Competizione (PC); possibly AC EVO (unverified) | Mac-direct all-car field model for track knowledge [P4]; no inputs | [P1] §3.2 (Kunos SDK C# sample `ksBroadcastingNetwork` described in prose); MIT SDK [C1] for cross-check | Kunos SDK sample (no licence); ACC EULA questions [P4] | `docs/research/protocols/acc-broadcast.md` |
| 6 | **ea-wrc-json** | EA SPORTS WRC (PC) | Current title with a self-describing official schema; Mac-direct; needs a stage model | game-generated readme/channels.json and udp/*.json (read from the user's install; the GPL copy [C18] for orientation only); v1.3 notes [N8]; EA staff note [F11] | official game files | `docs/research/protocols/ea-wrc-json.md` |

**After these:** codemasters-legacy (DR2.0/GRID), outgauge/outsim (LFS), kartkraft-flatbuffers.

---

## 10. Open questions

1. **PMR on PS5.**
   - Does a stream actually arrive?
   - Which packet versions, rate and sizes does it use?
   - Is the default Host on console multicast?
   - Do the console and PC layouts match? (Console builds have lagged PC [N15].)

   Settle all of these with one capture. Also ask Straight4 for the spec.
2. **AC on PS5 back-compat.** Run the probe in §1.2. Also settle the console handshake reply size (408 vs 208 B), the RTLap behaviour, the track strings [F13], isInPit (24 vs 26), the gear encoding and the rate.
3. **FH5 Data Out on PS5.** Settle with a menu check. If present, verify by the 324-byte length and sanity values.
4. **pCARS 2 on PS5.**
   - Does the broadcast arrive?
   - Which struct revision does the final console patch emit (telemetry 556, 559 or 538 bytes)?
   - What is the real rate on Wi-Fi vs Ethernet?
5. **GT Sport on PS5.** Is the 296-byte decrypted layout identical to GT7 variant A? Do GT7 track signatures transfer?
6. **GT DD Pro mode per PS4 title.** Is PURPLE needed for AC, GT Sport, pCARS 2 and F1 2019/2020? Fanatec's article [O26] returned 403 to the verifiers. Does the F1 2021 PS5 build need compatibility mode? (A Fanatec index title suggests it might; unverified.)
7. **AC EVO.** Is there an ACC-style `broadcasting.json` (the MIT SDK commit of 2026-07-27 [C1])? Read Kunos's Steam guide [O21] in a browser. Confirm that `npos` × `track_length_m` gives lap distance, and correct [P4] §6.1 row G.
8. **LMU REST :6397.** Can it be reached off localhost? The licence of the shipped header is also unchecked.
9. **Store availability (not verified).** Current store availability of F1 2019/2020/2021/22 and GT Sport. Project CARS 1/2/3 delistings are confirmed [N3].
10. **Project CARS 1.** An official layout document (needed before any implementation).
11. **F1 23 and F1 22 spec text.** EA's forums return 403 to non-browser fetchers; read them in a real browser.
12. **Unsearched.** Hot Wheels Unleashed 2, Tokyo Xtreme Racer, MotoGP 24/25 and other 2025–26 console racers were not searched in depth. Also unsearched: the content of the 2022 GTPlanet Kunos interview chapter "UDP app support on PS5 and XSX" [N22].
13. **Disputed vendor claims.** "RS Dash NAT Type 2" for GT Sport [V33]. SimHub's unexplained "Nascar Heat 5" support entry [V20].
14. **Search budget.** This session's web-search budget was exhausted. A follow-up message can continue the searches above.

---

## 11. Verification performed while writing (2026-10-10)

| Check | Result |
|---|---|
| PMR v2.3 notes [O1] re-fetched | "Version 2.3", September 23, 2026: CONSOLES section "Enabled UDP telemetry settings on console platforms"; intro "along with enabling UDP telemetry on consoles"; a separate PS5 crash fix |
| devology-uk/sim-racing-sdk via GitHub API [C1] | licence **MIT**, pushed 2026-10-10. `PmrPacketType` = RaceInfo 0, ParticipantRaceState 1, ParticipantVehicleTelemetry 2, SessionStopped 3. Expected versions 1/1/2. `DefaultPort = 7576`, `DefaultMulticastGroup = "224.0.0.150"`, constructor default `useMulticast = false` (binds 0.0.0.0:7576) |
| Same repo, AC EVO | `SimRacingSdk.Ace.Udp` is ACC-broadcast-shaped, with the commit "Added port of ACC UDP protocol to ACE UDP" (2026-07-27). `AcePathProvider` reads `broadcasting.json` under a Documents "ACE" folder. Unverified as a real game feature (§10 item 7). |
| pitwall CLI | no capture-only command for arbitrary ports (`cli.py` commands: serve, simulate, replay, send, sessions, report, ask, llm-check, capabilities, token) |
| Web search | refused: the session budget was exhausted before writing |

---

## 12. Sources

Retrieval dates are 2026-10-10 unless a date is given. "(403)" = the page refused non-browser fetches; the content is as reported by search snippets or earlier pitwall research.

### pitwall (P)
- [P1] `docs/research/forza-ac-acc-iracing.md`
- [P2] `docs/research/gt7-protocol.md`
- [P3] `docs/research/f1-udp-spec.md`
- [P4] `docs/research/track-knowledge-sources.md`
- [P5] `docs/research/rig-setup-sources.md`
- [P6] `src/pitwall/capabilities.py`
- [P7] `docs/licences.md`

### Official (O)
- [O1] Project Motor Racing Version 2.3 notes (2026-09-23): https://projectmotorracing.com/newsArticle.php?articleCode=NjU1Y2M3ODc4
- [O2] Project Motor Racing FAQ (2025-11-25): https://projectmotorracing.com/newsArticle.php?articleCode=NmNjNmE0MjQy&lang=en
- [O3] Project Motor Racing update 2.0.0.2 (2026-04-09): https://projectmotorracing.com/newsArticle.php?articleCode=NGI1YmMyZDI5
- [O4] Project Motor Racing hotfix 2.3.0.1 (2026-10-05): https://projectmotorracing.com/newsArticle.php?articleCode=ZDk3NTVhYTFl
- [O5] EA, F1 2021 PS5 telemetry settings: https://www.ea.com/able/resources/f1-2021/ps5/telemetry
- [O6] EA, F1 22 PS5 telemetry settings: https://www.ea.com/able/resources/f1-22/ps5/telemetry
- [O7] EA, F1 22 UDP specification thread (403): https://forums.ea.com/discussions/f1-games-franchise-discussion-en/f1-22-udp-specification/8418392
- [O8] EA, F1 23 UDP specification (403): https://answers.ea.com/t5/General-Discussion/F1-23-UDP-Specification/m-p/12633159
- [O9] EA, F1 24 UDP specification (403): https://answers.ea.com/t5/General-Discussion/F1-24-UDP-Specification/td-p/13745220
- [O10] EA, F1 25 UDP specification: https://forums.ea.com/discussions/f1-25-general-discussion-en/discussion-f1%C2%AE-25-udp-specification/12187351
- [O11] Codemasters F1 2019 UDP specification (forum topic 38920; mirror): https://f1-2019-telemetry.readthedocs.io/en/latest/telemetry-specification.html
- [O12] Codemasters F1 2020 UDP specification (forum topic 50942; mirror): https://f1-2020-telemetry.readthedocs.io/en/stable/telemetry-specification.html
- [O13] Kunos, Assetto Corsa Remote Telemetry UDP specification: https://docs.google.com/document/d/1KfkZiIluXZ6mMhLWfDX1qAGbvhGRC3ZUzjVIt5FQpp4/pub
- [O14] Sector3 Studios r3e-api (Unlicense; pushed 2026-03-20): https://github.com/sector3studios/r3e-api
- [O15] BeamNG protocols documentation (2025-01-24): https://documentation.beamng.com/modding/protocols
- [O16] Motorsport Games KartKraft telemetry schema (MIT): https://github.com/motorsportgames/kartkraft-telemetry
- [O17] Live for Speed programmer docs: https://www.lfs.net/programmer ; LFS manual: https://en.lfsmanual.net/wiki/OutGauge , https://en.lfsmanual.net/wiki/OutSim
- [O18] SCS Telemetry SDK (edited 2026-09-29): https://modding.scssoft.com/wiki/Documentation/Engine/SDK/Telemetry
- [O19] Kart Racing Pro plugins: https://www.kartracing-pro.com/?page=plugins
- [O20] 505 Games, Assetto Corsa EVO 0.6 changelog (2026-04-15): https://support.505games.com/support/solutions/articles/150000225211-assetto-corsa-evo-0-6-changelog-15-apr-2026
- [O21] Kunos, AC EVO Shared Memory Documentation Steam guide (HTTP 429, not read): https://steamcommunity.com/sharedfiles/filedetails/?id=3707421508
- [O22] Rennsport FAQ: https://www.rennsport.gg/faq/
- [O23] Sony, PS5 backward compatibility: https://www.playstation.com/en-gb/support/games/ps5-backward-compatibility-games/
- [O24] PlayStation, Forza Horizon 5 support: https://www.playstation.com/en-us/support/games/forza-horizon-5-support
- [O25] Playground, Forza Horizon 6 Data Out documentation (2026-05-15; 403 on re-fetch): https://support.forza.net/hc/en-us/articles/51744149102611-Forza-Horizon-6-Data-Out-Documentation
- [O26] Fanatec, GT DD Pro Blue vs Purple mode (updated 2026-09-19; 403 to verifiers): https://help.fanatec.com/hc/en-us/articles/45694330932369-GT-DD-Pro-PlayStation-Blue-Mode-vs-Purple-Mode-Compatibility-with-Older-Games
- [O27] Fanatec PS4 compatibility list: https://www.fanatec.com/uk/en/s/faq-playstation-4-games-simulations-compatibility-list
- [O28] Thrustmaster SF1000 F1 telemetry KB: https://support.thrustmaster.com/en/kb/1786-en/
- [O29] EA, GRID Legends PS5 accessibility docs: https://www.ea.com/able/resources/grid/grid-legends/ps5
- [O30] SCS blog, telemetry SDK (2015-02-12): https://blog.scssoft.com/2015/02/a-look-on-technical-side-telemetry-sdk.html
- [O31] PCGamingWiki, EA Sports WRC (403 to verifier): https://www.pcgamingwiki.com/wiki/EA_Sports_WRC

### News (N)
- [N1] GTPlanet, Project CARS 2 patch 2.0 on PS4 (2017-10-12): https://www.gtplanet.net/project-cars-2-patch-2-0-launches-ps4/
- [N2] onpsx.de, Project CARS update 7 brings third-party apps to consoles (2015-12-16): https://onpsx.de/news/project-cars-update-7-bringt-unterstutzung-fur-3rd-party-programme-auf-die-konsolen/
- [N3] GTPlanet, Project CARS 3 final pitstop (2025-07-26): https://www.gtplanet.net/project-cars-3-makes-final-pitstop-20250726
- [N4] GTPlanet, GT Sport online services end (2023-09-29): https://www.gtplanet.net/?p=128552
- [N5] GTPlanet, Assetto Corsa 1.22 on PS4 (2018-05-03): https://www.gtplanet.net/surprise-assetto-corsa-1-22-patch-lands-on-playstation-4/
- [N6] VGC, Forza Horizon 6 dated for PS5 (2026-10-08): https://www.videogameschronicle.com/news/forza-horizon-6-officially-dated-for-ps5-alongside-an-expansion/
- [N7] Playday, FH6 PS5 delay report (2026-09-08): https://playday.one/2026/09/08/forza-horizon-6-ps5-port-to-be-delayed-into-2027-per-new-report/
- [N8] Overtake, EA WRC 1.3 patch notes (403): https://www.overtake.gg/news/ea-sports-wrc-update-1-3-brings-performance-fixes.1481/page/ea-sports-wrc-update-1-3-patch-notes.271/
- [N9] Traxion, Wreckfest 2 adds telemetry (2025-08-28): https://traxion.gg/wreckfest-2-updates-ai-adds-new-cars-telemetry-and-familiar-track/
- [N10] Traxion, Wreckfest 2 on PS5 and Xbox (2026-08-09): https://traxion.gg/wreckfest-2-on-ps5-and-xbox-just-a-few-more-laps-to-the-finish-line/
- [N11] bsimracing, LMU v1.2 full changelog (2025-12-08): https://www.bsimracing.com/le-mans-ultimate-update-v1-2-full-changelog/
- [N12] Traxion, LMU console versions early-to-mid 2027 (2026-03-11): https://traxion.gg/le-mans-ultimate-console-versions-on-track-for-early-to-mid-2027/
- [N13] Traxion, AC EVO console versions in development (2025-06-27): https://traxion.gg/assetto-corsa-evo-ps5-and-xbox-series-xs-versions-in-development/
- [N14] bsimracing, AC EVO v0.5 (2026-02-12): https://www.bsimracing.com/assetto-corsa-evo-v0-5-update-released/
- [N15] Traxion, PMR console players miss out (2026-01-17): https://traxion.gg/project-motor-racings-latest-update-promises-change-but-console-players-miss-out/
- [N16] Rankouniverse, PMR telemetry guide (2026-09-23): https://www.rankouniverse.com/guide-ai-giochi/project-motor-racing/project-motor-racing-telemetry-en?lang=en
- [N17] GoNintendo, MotoGP 18 Sim Racing Telemetry (2018-07-19): https://gonintendo.com/archives/288092-motogp-18-introduces-sim-racing-telemetry-to-analyze-your-performances-and-compare
- [N18] GTPlanet, GT7 gets D-BOX support (2024-01-30): https://www.gtplanet.net/gran-turismo-7-gets-official-d-box-motion-rig-support/
- [N19] Gematsu, Rennsport coming to PS5/Xbox (2025-03): https://www.gematsu.com/2025/03/rennsport-coming-to-ps5-xbox-series-in-2025
- [N20] bsimracing, KartKraft telemetry build: https://bsimracing.com/?p=78137
- [N21] Traxion, iRacing and Cosworth telemetry tools: https://traxion.gg/iracing-and-cosworth-team-up-to-provide-free-sim-racing-telemetry-tools/
- [N22] bsimracing, ACC PS5/XSX launch interview (2022-02-22): https://bsimracing.com/assetto-corsa-competizione-ps5-xbox-series-x-launch-interview-by-gtplanet
- [N23] Gematsu, Tokyo Xtreme Racer PS5 (launch 2026-02-26): https://www.gematsu.com/2025/11/tokyo-xtreme-racer-for-ps5-launches-february-26-2026
- [N24] WeArePlayStation, JDM on PS5: https://www.weareplaystation.fr/communautes/jeux-independants/actualites-communaute/jdm-japanese-drift-master-debarque-sur-playstation-5-avec-contenu-complet

### Vendors (V)
- [V1] SIM Dashboard, Unsupported Games: http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Unsupported_Games
- [V2] SIM Dashboard, Assetto Corsa (PS4/PS5): http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Assetto_Corsa
- [V3] SIM Dashboard, Gran Turismo Sport: http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Gran_Turismo_Sport
- [V4] SIM Dashboard, Project Cars 2 (console): http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Project_Cars_2
- [V5] SIM Dashboard, Project Cars (console): http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Project_Cars
- [V6] SIM Dashboard, Project Cars 3: http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Project_Cars_3
- [V7] SIM Dashboard, "Project Cars 1 and 2 are slow": http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Issues/Project_Cars_1_and_2_are_slow
- [V8] SIM Dashboard, F1 24 (console): http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/F1_24
- [V9] SIM Dashboard, F1 23 (console): http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/F1_23
- [V10] SIM Dashboard, Forza Horizon 5 (console): http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Forza_Horizon_5
- [V11] SIM Dashboard, Forza Horizon 4 (console): https://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Forza_Horizon_4
- [V12] SIM Dashboard, Forza Horizon 6 (console): https://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Forza_Horizon_6
- [V13] SIM Dashboard, Project Motor Racing (PC): http://www.stryder-it.de/simdashboard/help/en/For_PC_Gamers/Game_Configuration/Project_Motor_Racing
- [V14] SIM Dashboard, WRC Generations (console): http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/WRC_Generations
- [V15] SIM Dashboard, GRID Legends (PC): http://www.stryder-it.de/simdashboard/help/en/For_PC_Gamers/Game_Configuration/GRID_Legends
- [V16] SIM Dashboard, TDU Solar Crown (PC): http://www.stryder-it.de/simdashboard/help/en/For_PC_Gamers/Game_Configuration/TDUSC
- [V17] SIM Dashboard, Wreckfest 2 (PC): http://www.stryder-it.de/simdashboard/help/en/For_PC_Gamers/Game_Configuration/Wreckfest_2
- [V18] SIM Dashboard, "MotoGP 18 is slow": http://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Issues/MotoGP_18_is_slow
- [V19] SIM Dashboard, Forza Motorsport 7 and Forza Motorsport (console): https://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Forza_Motorsport_7 , https://www.stryder-it.de/simdashboard/help/en/For_PS4_and_XBox_One_Gamers/Game_Configuration/Forza_Motorsport
- [V20] SimHub, supported games: https://www.simhubdash.com/supported-games/
- [V21] SimHub changelog (9.10.2 2025-10-13 to 9.13.2 2026-10-07): https://www.simhubdash.com/download-2/
- [V22] SimHub wiki, games config and troubleshooting (rev. 2026-06-24): https://github.com/SHWotever/SimHub/wiki/SimHub-Basics----Games-config-and-troubleshooting
- [V23] SimHub forum, ACC PS5 (2022-01-29, 2024-01-01): https://www.simhubdash.com/community-2/simhub/simhub-acc-ps5-setup/
- [V24] SimHub forum, Project Cars on PS4 (2020-07-17): https://www.simhubdash.com/community-2/simhub/project-cars-on-ps4-with-simhub/
- [V25] SimHub 6.5.4 notes (2018-09-20): https://www.simhubdash.com/simhub-6-5-4/
- [V26] SIMRIG supported games: https://www.simrig.se/documentation/control-center/supported-games.html
- [V27] SIMRIG, Project Motor Racing (Console): https://www.simrig.se/documentation/control-center/game-setup/project-motor-racing-console.html
- [V28] SIMRIG, Project Motor Racing (PC): https://www.simrig.se/documentation/control-center/game-setup/project-motor-racing.html
- [V29] RS Dash, Assetto Corsa: https://www.rsdash.com/rs-dash-ac
- [V30] RS Dash, Project CARS 2: https://www.rsdash.com/rs-dash-pcars2
- [V31] RS Dash, Project CARS: https://www.rsdash.com/rs-dash-pcars1
- [V32] RS Dash, Project CARS 3: https://www.rsdash.com/rs-dash-pcars3
- [V33] RS Dash, GT Sport: https://www.rsdash.com/rs-dash-gts
- [V34] RS Dash, F1 2019: https://www.rsdash.com/rs-dash-f12019
- [V35] RS Dash, F1 2020: https://www.rsdash.com/rs-dash-f12020
- [V36] RS Dash, F1 2021: https://www.rsdash.com/rs-dash-f12021
- [V37] RS Dash, F1 22: https://www.rsdash.com/rs-dash-f12022
- [V38] RS Dash, ACC: https://www.rsdash.com/rs-dash-acc
- [V39] Sim Racing Telemetry, App Store listing: https://apps.apple.com/us/app/sim-racing-telemetry/id1288695792
- [V40] Sim Racing Telemetry, Steam listing: https://store.steampowered.com/app/845210/Sim_Racing_Telemetry/
- [V41] Sim Racing Studio, console list: https://www.simracingstudio.com/console
- [V42] Track Titan, supported games (2026-05-19): https://intercom.help/track-titan/en/articles/6227990-which-games-are-supported-by-track-titan
- [V43] DashPanel, Steam listing: https://store.steampowered.com/app/715670/DashPanel/
- [V44] DashPanel, App Store listing: https://apps.apple.com/us/app/-/id1441894380
- [V45] Driver Apex, Assetto Corsa telemetry (undated): https://driverapex.com/games/assetto-corsa-telemetry/
- [V46] Next Level Racing, Motion Compatibility on Console (2026-05-27; 403 on re-fetch): https://support.nextlevelracing.com/hc/en-us/articles/16164543318799-Motion-Compatibility-on-Console
- [V47] D-BOX, Forza Horizon activation: https://support.d-box.com/en/knowledge/how-do-i-activate-d-box-haptic-in-forza-horizon
- [V48] D-BOX, GT7 activation: https://support.d-box.com/en/knowledge/how-to-activate-d-box-haptics-in-gran-turismo-7
- [V49] DOF Reality FAQ: https://dofreality.com/faq/
- [V50] Qubic Manager 2.173 (2025-12-03): https://qubicsystem.com/2025/12/qubic-manager-new-version-2-173/
- [V51] motion4sim supported games: https://docs.motion4sim.com/software/motionsystem/supported-games
- [V52] Simucube, DiRT Rally: https://docs.simucube.com/TunerSoftware/games/DirtRally.html
- [V53] Simucube, WRC Generations: https://docs.simucube.com/TunerSoftware/games/WRC%20Generations.html
- [V54] Simucube, BeamNG: https://docs.simucube.com/TunerSoftware/games/BeamNG.html
- [V55] Moza, Automobilista 2: https://support.mozaracing.com/en/support/solutions/articles/70000628772-automobilista-2-ams2-
- [V56] Moza, KartKraft: https://support.mozaracing.com/en/support/solutions/articles/70000628233-kartkraft
- [V57] oesimracing, SimHub console and games guides (2026-08-04): https://oesimracing.com/simhub/console/ , https://oesimracing.com/simhub/games/
- [V58] Coach Dave Academy, Delta in GT7 (2025-01-16): https://coachdaveacademy.com/documentation/how-to-enable-delta-in-gt7/
- [V59] xsimulator console FAQ: https://xsimulator.net/community/faq/consoles.27/category
- [V60] Motionhouse, "[Console] Project Cars 3" (2020-08-25; 403): https://en-motionhouse.imweb.me/16/?bmode=view&idx=4604831

### Code, spec copies, captures (C)
- [C1] devology-uk/sim-racing-sdk (MIT; pushed 2026-10-10): https://github.com/devology-uk/sim-racing-sdk , PMR UDP: https://github.com/devology-uk/sim-racing-sdk/tree/master/src/SimRacingSdk.Pmr.Udp
- [C2] Ricozwar/pmr-results-helper (proprietary; created 2026-09-22): https://github.com/Ricozwar/pmr-results-helper
- [C3] SeriousOldMan/Simulator-Controller (NOASSERTION): https://github.com/SeriousOldMan/Simulator-Controller
- [C4] Nenkai/PDTools (MIT): https://github.com/Nenkai/PDTools/blob/master/PDTools.Crypto/SimulationInterface/SimulatorInterfaceCryptorGTSport.cs , https://github.com/Nenkai/PDTools/blob/master/PDTools.SimulatorInterface/SimulatorInterfaceClient.cs
- [C5] rickwest/ac-remote-telemetry-client (MIT): https://github.com/rickwest/ac-remote-telemetry-client
- [C6] crmne/moza-rev (MIT; 2026-10-05): https://github.com/crmne/moza-rev
- [C7] iimetra/assetto-corsa-telemetry-4j (no LICENSE file): https://github.com/iimetra/assetto-corsa-telemetry-4j
- [C8] vthinsel/Python_UDP_Receiver AC capture commit (CC0-1.0; 2017-02-24): https://github.com/vthinsel/Python_UDP_Receiver/commit/21d6b5f54faed66d81c13942b6439fd3fa53534a
- [C9] Crew Chief V4 (MIT, Britton IT Ltd): https://gitlab.com/mr_belowski/CrewChiefV4/-/blob/master/CrewChiefV4/PCars2/PCars2UDPTelemetryDataStruct.cs , https://gitlab.com/mr_belowski/CrewChiefV4/-/blob/master/CrewChiefV4/GameDefinition.cs
- [C10] SMS_UDP_Definitions.hpp copies (no licence): https://github.com/tyretrack/server/blob/master/docs/SMS_UDP_Definitions.hpp , https://github.com/mplutka/tm-bt-led/blob/master/lib/pcars2-udp/SMS_UDP_Definitions.hpp , https://github.com/saildeep/pcars2-udp/blob/master/SMS_UDP_Definitions.hpp
- [C11] kutu/pyirsdk (MIT): https://github.com/kutu/pyirsdk
- [C12] Swizzjack/lmu-pitwall (MIT; 2026-08-03): https://github.com/Swizzjack/lmu-pitwall
- [C13] TheIronWolfModding/rF2SharedMemoryMapPlugin (GPL-3.0): https://github.com/TheIronWolfModding/rF2SharedMemoryMapPlugin
- [C14] albertowd/live-telemetry-evo SHARED_MEMORY.md (no licence; 2026-08-02): https://github.com/albertowd/live-telemetry-evo/blob/develop/docs/SHARED_MEMORY.md
- [C15] KamileonPL/lfs-pit-wall (contains LFS's own InSim.txt / OutSimPack.txt): https://github.com/KamileonPL/lfs-pit-wall
- [C16] fixfactory/SliProSuperPro (RBR NGP header, no licence notice): https://github.com/fixfactory/SliProSuperPro
- [C17] ErlerPhilipp/dr2_logger (MIT): https://github.com/ErlerPhilipp/dr2_logger
- [C18] vazhure/vAzhureRacingHub (GPL-3.0; contains EA WRC game-generated telemetry docs): https://github.com/vazhure/vAzhureRacingHub
- [C19] SYSTEMATI0N/WF2_DSX (MIT): https://github.com/SYSTEMATI0N/WF2_DSX
- [C20] timderes/krp-app (MIT): https://github.com/timderes/krp-app ; thomas4f/mxbmrp3 (MIT): https://github.com/thomas4f/mxbmrp3
- [C21] RenCloud/scs-sdk-plugin (MIT): https://github.com/RenCloud/scs-sdk-plugin ; Funbit/ets2-telemetry-server (GPL-3.0): https://github.com/Funbit/ets2-telemetry-server
- [C22] ozkar99/cm-telemetry (MIT): https://github.com/ozkar99/cm-telemetry
- [C23] Spacefreak18/simapi PR 19 (LGPL-3.0): https://github.com/Spacefreak18/simapi/pull/19
- [C24] ianv1/BSTSharedMemoryMapPlugin: https://github.com/ianv1/BSTSharedMemoryMapPlugin
- [C25] (do not copy) rusty-telemetry (AGPL-3.0): https://codeberg.org/jhunnius/rusty-telemetry ; ch3p4ll3/ACUDP (GPL-3.0); Egocentrix/AC-UDP-Connection (no licence): https://github.com/Egocentrix/AC-UDP-Connection
- [C26] f1-2021-udp npm (MIT): https://cdn.jsdelivr.net/npm/f1-2021-udp@1.15.989/README.md

### Forums and user reports (F)
- [F1] xsimulator, Assetto Corsa plugin thread (vthinsel, 2017-02-24 and 2017-03-24): https://www.xsimulator.net/community/threads/assetto-corsa-plugin.9823/
- [F2] assettocorsamods, UDP format update (2017-03-06): https://assettocorsamods.net/threads/udp-format-update.896/
- [F3] xsimulator, Assetto Corsa UDP (Consoles) (2017-10-31 to 2021-05-22): https://www.xsimulator.net/community/threads/assetto-corsa-udp-consoles-manual-plugin-start.11101/ , page 2: https://www.xsimulator.net/community/threads/assetto-corsa-udp-consoles-manual-plugin-start.11101/page-2 , page 3: https://www.xsimulator.net/community/threads/assetto-corsa-udp-consoles-manual-plugin-start.11101/page-3
- [F4] xsimulator, pCARS 2 console UDP (2018-01-25, 2019-02-13): https://xsimulator.net/community/goto/post?id=166501
- [F5] GTPlanet, telemetry apps for console (2016-02-21): https://www.gtplanet.net/forum/threads/telemetry-apps-for-console.338889/page-6
- [F6] Reiza forum, AMS2 shared memory vs UDP (2025-08-29 to 2025-09-02): https://forum.reizastudios.com/posts/335128
- [F7] Steam, EA WRC console speculation (2023-11-02): https://steamcommunity.com/app/1849250/discussions/0/3941272762723530353
- [F8] Steam, WRC Generations telemetry (Nacon reply, 2022-10-27): https://steamcommunity.com/app/1953520/discussions/0/3462731694141335573/
- [F9] Steam, NASCAR Heat 5 no telemetry (2021-09-12): https://steamcommunity.com/app/1265860/discussions/0/4263206669458435109
- [F10] Steam, Sim Racing Telemetry developer on MotoGP 18 (2019-03-21): https://steamcommunity.com/app/845210/discussions/0/3362406825547351487
- [F11] EA forums, WRC 1.8.0 broken UDP fields (403): https://forums.ea.com/discussions/wrc-technical-issues-en/broken-udp-telemetry-fields-in-version-1-8-0/8405061
- [F12] Steam, AC EVO UDP request (2025-01): https://steamcommunity.com/app/3058630/discussions/0/756141976595764426
- [F13] Overtake, telemetry tool for AC (search snippet only; 403): https://www.overtake.gg/threads/telemetry-tool-for-ac.193511/
- [F14] SimXperience forum, Rennsport (about 2023): https://www.simxperience.com/forum/accuforce-v2-community-q-a-3/rennsport-1003
- [F15] LFS forum, OutGauge moderator post: https://lfs.net/forum/post/131511
- [F16] SimXperience forum, NASCAR 25: https://www.simxperience.com/forum/general-community-q-a-1/nascar-25-1522
- [F17] Steam, Wreckfest telemetry (2019): https://steamcommunity.com/app/228380/discussions/0/540739405557254336/?ctp=2
- [F18] SimHub forum, The Crew Motorfest request (2024-11-14): https://www.simhubdash.com/community-2/simhub/hopefully-telemetry-data-support-can-be-added-for-the-game-the-crew-motorfest/
