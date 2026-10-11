# Rig setup sources: Fanatec GT DD Pro (5 Nm, then 8 Nm) + CSL Pedals (then Load Cell Kit) on PS5, for F1 25 and GT7

Research date: 2026-10-10. **Revision 2.** This document synthesises five research angles (Fanatec official, F1 25 in-game,
F1 community, GT7 and other titles, tuning methodology), each checked by an adversarial verifier, plus four gap-fill
passes run the same day:
- 5 Nm vs 8 Nm in-game strength
- firmware and F1 25 v1.25 behaviour
- BRF values from CSL Pedals Load Cell Kit owners
- GT7 after the 1.71 hotfix

Items a verifier rejected (keep=false) are dropped or listed in §10. Gap-fill items were read by the researcher but not
re-verified; they carry `verified: false` in the JSON. The machine-readable companion is
`docs/research/rig-presets-draft.json` (schema revision 2, see §12).

**Evidence labels used throughout**

| Label | Meaning |
|---|---|
| **[V]** | Read directly from the source: live page, Zendesk API, Wayback snapshot, manual PDF, transcript, description or forum post. Where a verifier ran, it confirmed the value |
| **[A]** | Approximate: read from low-resolution YouTube storyboard frames. Consistent with the source, but the digits are not legible |
| **[U]** | Unverified: a single community claim, a search snippet, an illegible value, an inferred key mapping, or sources that conflict |
| **[D]** | Derived by this synthesis (arithmetic or inference). Not a published value |
| **[H]** | pitwall heuristic threshold. Unsourced; calibrate it on recorded captures before using it for advice |

No source prose is reproduced. Setting values are facts. Short source phrases (a few words) appear only where the task
requires the source's own words for the preference classification.

---

## 1. Executive summary

- **On PS5 the only way to set the base is the on-wheel Tuning Menu**, with the base in **DARK BLUE**
  (native PlayStation) mode. The Fanatec App is Windows-only. It replaced Fanatec Control Panel and FanaLab in 2025; the current version is 1.6.1.3
  (2026-09-21). It needs the base in **RED** (PC) mode and is the only way to update firmware. The iOS/Android
  app works only through a Windows PC, and its own release notes say it does not currently work with the new Windows
  App. On PS5 you can read the values GT7 pushes to A SET by scrolling the on-wheel menu. **[V]**
- **Possible workaround (only partly verified):** custom slots are stored in the base. You can fill slots 1-5 from the Fanatec App in RED mode,
  then switch to DARK BLUE and select the slot on the wheel. Check the values on the wheel display afterwards. **[U]**
- **The task brief has the pedals wrong.** Stock **CSL Pedals use 12-bit contactless Hall sensors, not a
  potentiometer.** The brake measures position (travel). It has no BRF and no manual calibration. After every power-on, press each pedal
  fully once and release it. **[V]**
- **Most of the recommended values are only in the Advanced Tuning Menu.** The Standard menu shows only SEN, FF, NDP, SHO, MPS and BRF, and its
  lowest NDP is 25. Hold the Tuning button for about 4 s to switch menus, and use a **custom slot (1 SET-5 SET)**, not A SET. **[V]**
- **Fanatec's official F1 25 table (2025-07-01, CSL DD/GT DD, PC/PS5 column):** SEN 360, FF 100, FFS PEA, NDP 35,
  NFR/NIN OFF, INT 3, FEI 100, FOR/SPR/DPR 100. In-game: strength 80, effects 30/30/15, Wheel Damper 3, rotation
  360. The page uses one row for 5 Nm and 8 Nm. Fanatec's 2026 Season Pack page says nothing changed but lists different values: NDP 20,
  SEN AUTO, strength 50-70 for every base. **[V]**
- **Moving from 5 Nm to 8 Nm (revised):** keep FF 100 and **the same in-game strength** for every style except
  comfort. Every source that gives values for both torques uses the same in-game value at each: SimRacingSetup esports 80-100, SimRacingSetup 70 (built for
  8 Nm, also for 5), Fanatec 80 (one row) and Fanatec 2026 50-70 for every base. No source lowers it. **[V]** Forces
  rise up to 1.6x. Game-side clipping does not change if F1 25 sends a normalised force command **[D]**. For comfort,
  scale strength by 5/8. To feel the old 5 Nm forces exactly, set FF 63 **[D]**. Revision 1's general "lower in-game strength by 5/8" rule is **withdrawn**.
- **Firmware and the Boost Kit:** since base FW 1.9.0.2 (Fanatec App 1.5.1.2, 2026-06-16) the GT DD Pro **no longer
  offers FFS (Peak/Linear) with the Boost Kit**, and holding torque rose from 6 to 8 Nm (Fanatec changelog) **[V]**.
  Fanatec help articles updated in September 2026 still describe LIN/PEAK, so check the menu once the kit is fitted.
- **F1 25 v1.25 bug that matters for the 8 Nm kit:** since v1.25 (2026-09-07), Fanatec CSL DD / GT DD Pro owners report
  violent left-right oscillation or lost FFB after a session change (for example Qualifying to Race). It lasts until
  the base is power-cycled. EA confirmed the bug and on 2026-10-07 shared a fix with Fanatec for the next patch.
  **Every report that states a torque is at 8 Nm, and no PS5 report was found.** Workaround: pause and power-cycle the base
  between sessions. Do not tune NDP, INT or the damper against it; it happened at NDP 50 / INT 11. **[V]** (EA statements, forum
  reports); PS5 impact **[U]**.
- **FullForce (FUL)** exists on the GT DD Pro from base FW 1.9.0.2. No source shows that F1 25 implements it, so leave FUL at default
  for F1 **[U]**. GT7 uses it from 1.71.
- **Load Cell Kit:** set **BRF** (Lo, 010-100, Hi; default 050) in the base Tuning Menu over RJ12. Manual min/max needs a
  Windows PC. **Verified CSL Pedals LC owners (GTPlanet, 2022-2023, mostly GT7 on PS5 with a GT DD Pro)** settled on BRF
  30-90, median **55** (n=5). The often-cited "BRF 40-50" thread comes from 2020-2021, before CSL Pedals existed, so it
  covers different pedals and does not apply. Fanatec publishes no kg scale; a linear kg estimate is in §6.3 **[D]**.
- **GT7:** update **1.71 (2026-08-20)** made every earlier GT7 preset stale. **A SET** with in-game Max. Torque 4-5 and
  Sensitivity 1-2 is the current official-default route **[U community values]**. It needs hotfix firmware (App 1.5.4.x,
  2026-09). Only one full custom GT DD Pro setup has been published since the hotfix (8 Nm, comfort-leaning). FUL: default 100;
  if FFB drops out, go to 60, then OFF.
- **Rig check:** neither game sends FFB torque, so clipping cannot be measured. Telemetry can check:
  - noise at rest and whether 100% brake/throttle is reachable;
  - saturation plateaus and lock-ups against brake level;
  - brake-peak drift (the power-on calibration routine was skipped);
  - load-cell fault signatures;
  - steering full-lock share, centre offset and oscillation;
  - the v1.25 session-start oscillation;
  - braking-shape metrics (Joyce et al. 2025).
  See §8.

**Recommended starting points for this rig** (detail in §6; all values on a PS5 custom slot, Advanced menu):

| Situation | F1 25 + 2026 Season Pack |
|---|---|
| **Now: 5 Nm + CSL Hall pedals** | **official_default:** Fanatec 2025 (strength 80). **balanced:** SimRacingSetup 380° (strength 70). **competitive:** SRS esports 5 Nm row (NDP OFF-5, INT 0-5, effects 0, damper 0-3, strength 80-100; after v1.25 start 90-100 **[D]**). **realism:** F1withNick (NDP OFF, strength ~60, effects 25/25/15; torque [U]). **comfort:** no source; derived row (strength ~60, NDP 40-50, FOR/FEI 80-90) **[D]** |
| **After Boost Kit 180 (8 Nm)** | Same Tuning Menu values. FFS is gone (set PEA only if it is still shown). **Keep in-game strength**: official 80, balanced 70, competitive 90-100 (Carson after v1.25), realism start ~60 and raise in steps of 5. **comfort ~40 [D]**. With NDP OFF expect to need NDP 5-20 if the wheel oscillates hands-off. Power-cycle the base if the v1.25 session-change oscillation appears |
| **After Load Cell Kit** | BRF by style: official 050, balanced ~55, competitive/realism 65-75 (higher only on a rigid rig), comfort ~40 **[D from owner data]**. In game: brake saturation 0, deadzone 0 unless the rig check finds input at rest. Re-run the rig check |

GT7 (same base): use **A SET** + Max. Torque 4-5 / Sensitivity 1-2 at both torques. For details and the no-source styles see §6.4.

---

## 2. What can actually be set on PS5

| Surface | PS5? | What it controls | Source |
|---|---|---|---|
| On-wheel Tuning Menu (Tuning button + FunkySwitch/D-pad on the rim) | **Yes** (DARK BLUE mode) | All base parameters (§3.1). BRF once the LC kit is fitted. FUL on FullForce firmware (GT7 users set it on PS5) | GT DD Pro manual 5.6; help 43901256649233 **[V]** |
| Custom slots 1 SET-5 SET (Advanced) / C SET (Standard) | **Yes** | Stored in the base; each change is saved immediately. A PS5 DD+ owner keeps a dedicated F1 slot with SEN 360 | help 30312152662033; manual 5.6.1 **[V]**; forum.fanatec.com topic 20598 **[U]** |
| A SET (Auto Setup) | **Yes** | The game pushes values and the menu shows LOCKED. GT7 uses it (re-tuned in 1.71). You can read the values by scrolling. Use by F1 25 not documented **[U]** | manual; GT7 1.71 notice **[V]**; GTPlanet RS60NR 2026-09-30 |
| In-game controller menus (F1 25, GT7) | **Yes** | FFB gains, effects, rotation, calibration (F1 25 only), bindings | §3.5, §3.6 |
| Fanatec App (Windows) | **No** (needs RED PC mode) | Firmware (must match the App version), Tuning Menu values, LC Manual Mode min/max, game profiles | App comparison page; help 30893849063181, 47864233506065 **[V]** |
| Fanatec mobile app (iOS/Android, alpha) | **No** | Only works through a Windows PC; listed as not working with the new Windows App (App 1.5.3.1 and 1.6.1.3 known issues) | App Store; App 1.6.1.3 notes **[V]** |
| FanaLab / Control Panel game profiles, LEDs, display | **No** | PC-side only (FanaLab is legacy) | App comparison page **[V]** |

**Operating modes (power-button LED)** **[V]**:
- DARK BLUE: native PlayStation (PS5/PS4). Use this for F1 25 and GT7.
- PURPLE: PS4 compatibility; the base shows up as a CSL Elite WB+ PS4. Only for old titles such as F1 2020.
- RED: native PC (firmware, Fanatec App). App 1.6.1.3 shows a prompt asking PlayStation/Xbox-mode users to switch to it.
- YELLOW: PC compatibility.
- GREEN: Xbox; needs an Xbox-licensed rim.

The manual says USB updates run at up to 250 Hz in PlayStation mode. It is not documented whether the mode persists
across reboots and firmware updates **[U]**.

**Firmware path for a PS5 owner:**
1. Use a Windows PC with the Fanatec App, the base in RED mode, over USB.
2. Afterwards switch back to DARK BLUE, recalibrate the wheel centre and recheck the slots.

An LC firmware update also resets the LC manual calibration. To roll back, install the older App build: its firmware
must match the App version (help 47864233506065). Current firmware per App 1.6.1.3: **CSL DD/GT DD Pro base 1.9.2.3,
motor 1.1.2.2, QR 6.0.1.1; CSL Pedals LC 1.8**. **[V]**

**Firmware and game timeline** (check a preset's date against this):

| Date | Event | Effect on presets |
|---|---|---|
| 2025-07-01 | Fanatec F1 25 recommended-settings page | Baseline official F1 values (page still unrevised 2026-10-10) |
| 2026-05-05 | App 1.4.2.3 (base 1.8.0.6) | BRF reset after base restart fixed; endstop independent of FF; ClubSport DD/DD+ holding torque raised |
| 2026-06-03 | F1 25 2026 Season Pack (v1.20); Fanatec 2026 page | New official F1 values that conflict with 2025 |
| 2026-06-08 | App 1.4.3.4 (base 1.8.1.7, motor 1.0.3.2) | **Last pre-FullForce firmware**; the downgrade target some users chose for the v1.25 oscillation |
| 2026-06-16 | App 1.5.1.2 (base 1.9.0.2, motor 1.1.0.1) | FUL added at 5 and 8 Nm (also on QR1). **Boost Kit: holding torque 6 → 8 Nm; FFS removed.** NFR shaking fixed. Base shutdowns followed (interim advice: FF ≤ 75 for Boost Kit users) |
| 2026-06-24 | App 1.5.2.3 (base 1.9.0.3) | Shutdown hotfix. Known issues: DPR weaker than intended; endstop scales with FF again |
| 2026-08-11 | App 1.5.3.1 (base 1.9.1.1, motor 1.1.1.1) | **DPR corrected; graininess at high NDP fixed; endstop independent of FF again** |
| 2026-08-20 | GT7 1.71 | FFB torque/friction, understeer vibration and wheel throttle/brake input changed; ABS changed; A SET re-tuned; FullForce on GT DD Pro. **All earlier GT7 presets stale** |
| 2026-09-03 / 09-11 | App 1.5.4.1 / 1.5.4.2 | Hotfix for GT DD Pro FFB loss, oscillation and shutdowns after GT7 1.71. Firmware numbers not listed; base 1.9.2.3 inferred |
| 2026-09-07 | F1 25 v1.25 | **S Mode/DRS stays active only while throttle > 90%.** Closer input-to-physics match for wheels during rapid input changes; FFB frame-rate fix; Moza/Simucube stability. **Introduced the session-change oscillation on Fanatec DD bases.** Players report lighter FFB |
| 2026-09-16 | F1 25 v1.26 | Career crash fix only; does not fix the oscillation |
| 2026-09-21 | App 1.6.1.3 | No new CSL DD/GT DD Pro firmware. Known issues: GT DD Pro can lose FFB in GT7; SPR/DPR not working in the GT7 menu; FullForce weaker than intended; set SEN manually for F1 games |
| 2026-10-01 / 10-07 | EA status posts | Bug came from a fix for players mixing Fanatec with other brands; fix sent to Fanatec for approval (10-07); no ETA (10-08) |
| 2026-10-15 | GT7 Spec IV Part 1 (DG Edge headline only, **[U]**) | Re-check GT7 values after it |

---

## 3. Parameter reference

### 3.1 GT DD Pro Tuning Menu (all reachable on PS5)

Primary sources: the GT DD Pro manual §5.6 (`www3.corsair.com/Files/Fanatec/Documentation/GT-DD-PRO-Manual-EN_01.pdf`)
and Fanatec help 43901256649233 (created 2026-02-16, updated 2026-08-31; covers CSL DD, GT DD Pro and QR2L). The help
centre HTML returns 403, so it was read via `help.fanatec.com/api/v2/help_center/en-us/articles/<id>.json`. The legacy FAQ
`fanatec.com/us-en/faq/details/id/36` describes **older bases**: its INT default (6) and SHO 0-100 are **wrong for the
GT DD Pro**.

| Key | Menu | Range | Default | Meaning / notes |
|---|---|---|---|---|
| SETUP | both | Standard: A SET + C SET. Advanced: A SET + 1 SET-5 SET | Standard menu | Hold Tuning ~4 s to toggle (the FAQ says 3 s). Hold ~6 s more to reset custom slots (returns to Standard) **[V]** |
| SEN | both | Std 180-1080 or AUTO; Adv 90-2520 or AUTO | AUTO | Total rotation lock to lock. A fixed value overrides the game. **Set it manually for F1** (App 1.6.1.3 known issue with AUTO in F1 games). Lower = more direct |
| FF | both | Std 005-100; Adv OFF, 001-100 | 100 | % of maximum motor torque. Fanatec: take extra force from FF rather than in-game gain, to avoid clipping. Endstop independent of FF on current firmware. The display and Fanatec web pages call it "FFB" |
| FFS | Adv | LIN / PEA | PEA (manual 5.6.4) | PEA = full peak; LIN = lower max, steadier hold. **Not offered with the Boost Kit from base FW 1.9.0.2** (App 1.5.1.2 changelog) **[V]**. Still shown at 5 Nm **[A]**. Help articles still describe it (conflict) |
| NDP | both | Std 25-100; Adv OFF, 01-100 | 50 | Damping driven by steering speed and acceleration. Fanatec's first fix for oscillation. Higher = calmer, slower, less detail. Below 25 needs the Advanced menu. Graininess at high NDP fixed in 1.9.1.1 |
| NFR | Adv | OFF, 001-100 | OFF | Friction. Calms oscillation; high values cost responsiveness and detail |
| NIN | Adv | OFF, 001-100 | OFF | Steering mass for light rims. Can stop oscillation starting, but can keep it going once started |
| INT | Adv | OFF, 01-20 | **11** | FFB filter. OFF = raw. Fanatec F1 uses 3; its oscillation guide keeps 1-5 |
| FEI | Adv | 000-100 (step size unverified) | 100 | How sharp effects feel. Fanatec F1 25: lower to 90 or 80 if harsh |
| FOR | Adv | OFF, 010-120 | 100 | Game constant-force channel. Above 100 amplifies, risks clipping and heats the motor. Fanatec: keep 100; use 80-90 only to reduce fatigue |
| SPR | Adv | OFF, 010-120 | 100 | Game spring/centring. Low or OFF stops re-centring after centre calibration. **Known issue: not working in the GT7 menu on GT DD Pro** |
| DPR | Adv | OFF, 010-120 | 100 | Game damper channel (inferred to include F1 25 Wheel Damper). Corrected in base FW 1.9.1.1, so DPR advice from earlier firmware may feel different |
| FUL | Adv **[U]** | OFF-100 **[U]** | 100 | FullForce strength. Added by base FW 1.9.0.2 (5 and 8 Nm). Fanatec's FullForce games list (2026-02-10) names iRacing, GT7 and AC EVO. **No confirmed effect in F1 25.** Known issue: weaker than intended on CSL DD/GT DD Pro. Fanatec's main Tuning Menu article still documents FUL only for Podium/CS DD |
| BLI | Adv | OFF, 001-100 | OFF | Pedal vibration at a brake %. **Needs ClubSport Pedals V3/V3i; not usable with CSL Pedals or the LC kit.** A preset that sets BLI was made with CSP V3 pedals |
| SHO | both | OFF / ON | ON | Shown only when a rim or pedal with vibration motors is connected. CSL pedals have none; motors in the bundled rim are unverified |
| MPS | both | AUTO / ENC / CONST / PULSE | AUTO | Not supported by the bundled GT DD Pro rim |
| AP | Adv | CbP / CH / bt / AnA | CbP | Analogue paddles. Not supported by the bundled rim ("ACP" in some sources) |
| BRF | both (LC only) | Lo, 010-100, Hi | 050 | See §3.4 |

### 3.2 Torque by PSU, FFS and firmware **[V]** (manual 5.6.4; help 30312080999825; App 1.5.1.2 changelog)

| PSU | FFS = PEA | FFS = LIN | On base FW ≥ 1.9.0.2 |
|---|---|---|---|
| Standard 90 W | **5 Nm** | 4 Nm | FFS still present **[A]** |
| Boost Kit 180 (180 W) | **8 Nm** | ~6 Nm | **FFS not offered**; 8 Nm peak, holding torque raised from 6 to 8 Nm |

The Boost Kit replaces the PSU. The base detects it and releases the extra torque automatically; Fanatec documents no
setup step. Only the original PSU or the Boost Kit 180 may be used. With FF 100, the same command gives 1.6x the torque
at 8 Nm **[D]**. Fanatec rates 5 Nm for rims up to about 35 cm and says the Boost Kit adds headroom and lowers clipping
risk (help 30312079505553). No thermal-derating data exists for the GT DD Pro at 8 Nm **[U]**. A community user saw the PC App report 8 Nm
in AUTO and slot 5 but 6 Nm in slots 1-4 (GTPlanet 2026-09-12) **[U]**: check what your slots report.

### 3.3 CSL Pedals (stock): Hall position brake **[V]**

| Item | Value |
|---|---|
| Sensors | 12-bit contactless Hall on throttle and brake (not potentiometers) |
| Brake feel | Travel-based; a stiffer spring plus PU foam gives the progression |
| Calibration | Automatic min/max. **After every power-on, press each pedal fully and release before driving.** No manual calibration, no BRF |
| Console connection | RJ12 into the wheel base (the only console path) |
| In-game adjustment | F1 25: per-axis deadzone/linearity/saturation (§3.5). GT7: none documented (an unverified claim says Options > Controllers can calibrate, §3.6) |

### 3.4 CSL Pedals Load Cell Kit **[V]**

| Key | Range / value | Notes |
|---|---|---|
| BRF | Lo, 010-100, Hi; default **050** | Force needed for 100% brake; Lo = lightest. Acts as the brake maximum over RJ12. Shown in the Standard and Advanced menus once the LC brake is detected. Fanatec states only "approx. 10 kg minimum" sensitivity; no kg table and no maximum |
| kg mapping **[D]/[U]** | ~10 kg at 010 (Fanatec); ~60 kg at the pedal face for 100% at BRF MAX (one community measurement, super_gt 2022, possibly Fanatec-affiliated) | A linear fit between the two (unverified): BRF 40 ≈ 27 kg, 55 ≈ 35 kg, 70 ≈ 43 kg, 90 ≈ 54 kg. The "90 kg" often quoted is the **CSL Elite Pedals V2** load cell, not this kit |
| Manual Mode (min/max) | Brake min (deadzone) and throttle min/max; brake max = BRF | **Windows Fanatec software only**. Saved to the pedal; reset by an LC firmware update. A CSL LC owner on PS5 set deadzones once on a laptop and they persisted on PS5 **[U]** |
| Auto-calibration | Active when Manual Mode is off | Press each pedal fully after power-on (a community note says to hold the brake at max for 2-3 s). Otherwise values can drift during a session |
| Hardware | 12-bit load cell, 65 Shore elastomer stack, LC firmware 1.8 | Replaces the brake; the old brake can become the clutch. No Fanatec tuning elastomers are sold for it |
| Wiring | RJ12 from the accelerator module's "Wheel Base / Load Cell" port to the LC "Load Cell" port; accelerator to base | **Never connect RJ12 and USB at the same time.** Update base firmware first |
| Known issues | BRF reset after restart (2022 drivers; again until App 1.4.2.3, May 2026); "BRF shown as 0% in the App" (fixed in 1.6.1.3) | If the brake reads input at rest: update firmware and reset the pedals via PC (help 50374908960273) |

**BRF does not transfer between Fanatec pedal models.**
- CSL Elite LC (V1) manual: 65 Shore up to ~20 kg = BRF Lo-40; 85 Shore up to ~40 kg = Lo-70; 95 Shore up to ~90 kg = full range.
- ClubSport V3: BRF range Lo, 001-100.
- Podium: calibrated for 150 kg at the plate.
- Some 2019-2020 base firmware inverted the BRF direction (Fanatec staff, GTPlanet 2020-11-11).

### 3.5 F1 25 in-game (incl. 2026 Season Pack)

Path: Settings > Controls, Vibration & Force Feedback > [wheel preset] > **Calibration** / **Vibration & Force
Feedback**. If options are missing, set **Settings Filter** to **Expert** (Triangle). **EA publishes no F1 25 slider
ranges or wheel-preset defaults.** EA's per-menu pages exist only for F1 22, and F1 22 defaults are kept only where
labelled as such.

| Key | Section | Range | Default | Notes |
|---|---|---|---|---|
| VIB_FFB | Vibration & FFB | On / Off | unverified (F1 22: On) | Community PS5 report: toggling it restores FFB lost mid-race **[U]** |
| VIB_FFB_STRENGTH | Vibration & FFB | 0 to >100 (110, ~115 and 120 seen; max unverified, ~150 by slider proportion) | unverified | Overall game gain. **No clipping meter, and no published measurement of game-side clipping against this value.** The same author gives the same value at 5 and 8 Nm; game version moved values more than torque did (§5.2) |
| ON_TRACK_EFFECTS | Vibration & FFB | unverified (0-70 seen) | unverified | Canned road texture; Fanatec's 2026 page omits it |
| RUMBLE_STRIP_EFFECTS | Vibration & FFB | unverified (0-40 seen) | unverified | Canned kerb effect |
| OFF_TRACK_EFFECTS | Vibration & FFB | unverified (0-25 seen) | unverified | Grass/gravel |
| PIT_STOP_EFFECTS | Vibration & FFB | unverified (0-50 seen) | unverified | Added after F1 22. No driving effect |
| WHEEL_DAMPER | Vibration & FFB | unverified (0-10 seen) | unverified (F1 22: 50) | Game-side damping; adds to base NDP; scaled by DPR |
| MAX_WHEEL_ROTATION | Vibration & FFB | unverified (300-400 used) | unverified (F1 22 F1/F2: 360) | Physical degrees for full in-game lock. Set SEN to the same number |
| STEERING_RATE | Calibration | % | 100% on the EA F1 25 gamepad screenshot | Meant for sticks. Wheel guides leave it at 100% |
| STEERING_/THROTTLE_/BRAKE_ DEADZONE, LINEARITY, SATURATION | Calibration | 0-100 (F1 22 PS5 docs; F1 25 unverified) | 0, except **Brake Linearity 25**, on EA's F1 25 gamepad screenshot. Opmeer says brake linearity defaults to 25. PS5 wheel defaults unverified | Deadzone = initial travel (force with a load cell) ignored. Linearity = less sensitive start. Saturation = 100% before full travel. Throttle and brake keys depend on the pedals (JSON `pedal_dependent`) |
| BRAKE_PRESSURE | Car setup | % (range unverified) | unverified | UDP CarSetups `m_brakePressure`. Lower it if you lock too easily (Trophi/Driver61) |
| OVERTAKE_ERS_MODE | Controls - Generic | Hold / Toggle | Toggle | Global; in 2026 content it also governs Overtake |
| UDP_ACTION_1..12 | UDP Custom Actions | any button | Unassigned | BUTN bits 0x00100000-0x80000000. pitwall radio PTT uses Action 1 (docs/radio-setup.md) |
| BIND_DRS_SMODE / BIND_OVERTAKE_BOOST / BIND_PUSH_TO_TALK | Bindings | any button | L2 / R2 / Unassigned in EA's G923 example | Active Aero reuses the DRS binding; since v1.25, S Mode needs throttle > 90%. GT DD Pro pre-mapped bindings unpublished |
| UDP_TELEMETRY | Telemetry Settings | On/Off, IP, port, format 2025/2026 | port 20777; format default **conflicting [U]** | pitwall parses both formats |

Not in F1 25: **Understeer Enhance** (an F1 22 item) or any in-game FFB smoothing. Ignore DualSense triggers and
Logitech Trueforce on this rig.

### 3.6 GT7 in-game

Path: pre-race Quick Menu > Settings > Controller Settings (also while paused). The official manual
(`gran-turismo.com/gb/gt7/manual/drivingoption/04`; text via `/gb/gt7/api/manual/?u=/drivingoption/04`) gives
setting names and meanings **but no ranges or defaults**.

| Key | Range | Default | Notes |
|---|---|---|---|
| FFB_MAX_TORQUE | 1-10 (community) | unverified | Game scale, not Nm; reportedly non-linear (high values compress). Higher = duller tyre response in hard corners |
| FFB_SENSITIVITY | 1-10 (community) | unverified | How fast resistance builds at turn-in. 1 = slowest ramp. Fanatec uses 1 |
| CONTROLLER_STEERING_SENSITIVITY | unverified | unverified | DualSense only |
| COUNTERSTEERING_ASSIST | Weak / Strong (+ Off) | unverified | Fanatec: Off for wheel users |
| ABS | Default / Weak / Off | Default | Changes how brake input becomes deceleration; changed in 1.71 |
| VIBRATION | unverified (25-150 quoted) | unverified | Post-1.71 users list it; disabling it removed FullForce effects for one user **[U]** |
| CONTROLLER_CALIBRATION | min/max/deadzone (claimed) | unverified | One community claim (RS60NR, 2025-01, pre-1.71) says Options > Controllers stores pedal min/max/deadzone. A 2022 Fanatec forum statement says GT7 has none. **Verify on the PS5** |

---

## 4. Preset catalogue

Values are as published. OFF and 0 are the same on the base. "—" = not given by the source. **Torque** = the torque
the values may be applied at (JSON `applies_to_torque_nm`).

### 4.1 F1 25: GT DD Pro / CSL DD class (every value is a Tuning Menu or in-game item, so all are reachable on PS5)

**Sources**

| # | Preset | Author | Published | Game version | Source platform | Torque | Pedals | Style (source words → class) | Conf. |
|---|---|---|---|---|---|---|---|---|---|
| F1 | Fanatec official, PC/PS5 column | Fanatec | 2025-07-01 | 2025 cars | PC/PS5 | 5 and 8 (not distinguished) | — | "simply a reference" → official_default | high |
| F2 | Fanatec official, Xbox column (**not for PS5**) | Fanatec | 2025-07-01 | 2025 cars | Xbox | 5 and 8 | — | official_default | high |
| F3 | Fanatec official 2026 Season Pack | Fanatec | 2026-06-03 | v1.20, pre-v1.25 | not split | 5 and 8 (one range, every base) | — | "the strength of your base and personal preference" → official_default | medium |
| F4 | SimRacingSetup 380° (F1 25 and "F1 26" pages) | Rich (SRS) | 2025-05-26 (mod. 2025-10-08); 2026-06-03 | both | PC/PS5 | built for 8, "can be used" at 5 → 5 and 8 | — | "most sim racers" → balanced | high |
| F5a | SRS esports table, CSL DD (5Nm) row | Carson (FVR) | 2025-10-08 | 2025 cars | not stated | **5** | — | "fastest Esports drivers" → competitive | medium |
| F5b | SRS esports table, CSL DD (8Nm power kit) row | Carson (FVR) | 2025-10-08 | 2025 cars | not stated | **8** | — | competitive | medium |
| F6 | Carson F1, F1 25 video | Carson F1 | 2025-06-26 | 2025 cars | PC (Control Panel) | 8 | load cell, model not shown | "like an esports driver" → competitive | medium |
| F7 | Carson F1, F1 26 video + 2026-09-07 description | Carson F1 | 2026-06-30 / 09-07 | **v1.25+** | PC (App, FullForce FW) | 8 | — | competitive | medium |
| F8 | Alessandro Fin, F1 25 | Alessandro Fin | 2025-06-02 | 2025 cars | PC (Control Panel) | 8 (GT DD Pro + Boost Kit) | load cell, model not shown | no style → balanced **[D]** | low |
| F9 | Alessandro Fin, F1 26 | Alessandro Fin | 2026-06-24 | v1.20, pre-v1.25 | PC (old Control Panel) | 8 (inferred) | — | "precise, consistent and predictable" → competitive | low |
| F10 | Matt212 | Matt212 | 2025-05-28 | 2025 cars | PC (FanaLab) | 8 (GT DD Pro + Boost Kit) | CSL Elite load cell | no style → balanced **[D]** | medium |
| F11 | F1withNick "most realistic" | F1withNick | 2026-07-10 | v1.20, pre-v1.25 | PC (App) | 5 **[U]** (FFS still shown; "5 Nm" not legible) | **stock CSL Pedals [A]** | "MOST REALISTIC" → realism | low |

**Tuning Menu values**

| # | SEN | FF | FFS | NDP | NFR | NIN | INT | FEI | FOR | SPR | DPR | Other |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 | 360 | 100 | PEA | 35 | OFF | OFF | 3 | 100 | 100 | 100 | 100 | — |
| F2 | 360 | 100 | PEA | 45 | OFF | OFF | 3 | 100 | N/A | N/A | N/A | — |
| F3 | AUTO (match in-game if it fails) | 100 | PEA | 20 | OFF | OFF | 3 | 100 | 100 | 100 | 100 | — |
| F4 | 380 | 100 | PEA | 35 | OFF | OFF | 3 | 100 | 100 | 100 | 100 | — |
| F5a/F5b | 300-360 or AUTO | 100 | PEA | OFF or ≤5 | OFF | OFF | 0-5 | 100 | 100 * | 100 | 100 | * labelled "FFS" by the source; FOR inferred |
| F6 | 360 | 100 | PEA | OFF | OFF | OFF | ~2 [A] | ~90 [A] (spoken 100) | 100 | 100 | 100 | pedal: BRF ~40 [A] (model unknown) |
| F7 | 360 | 100 | not shown (Boost Kit FW) | OFF | OFF | OFF | ~1 [A] | ~90 [A] | ~100 | ~100 | 100 | FUL ~100 [A] |
| F8 | 330 | 100 | PEA | ~50 [A] | ~10 [A] | ~10 [A] | ~3 [A] | 100 | 100 | 100 | 100 | pedal: BRF 55 [U] (model unknown) |
| F9 | ~310 [A] | 100 | PEA | ~30 [A] | ~15 [A] | ~5 [A] | ~6 [A] | 100 | 100 | 100 | 100 | — |
| F10 | 400 | 80 | PEA | 50 | OFF | OFF | 11 | 100 | 110 | 100 | 100 | pedal: BRF 30 (CSL Elite LC) |
| F11 | 360 | 100 | PEA | OFF | OFF | OFF | ~3 [A] | 100 | ~100 | ~100 | ~100 | FUL ~100 [A] |

**In-game values**

| # | Strength | On Track | Rumble | Off Track | Pit Stop | Damper | Rotation | Calibration |
|---|---|---|---|---|---|---|---|---|
| F1 | 80 | 30 | 30 | 15 | — | 3 | 360 | — |
| F2 | 70 | 30 | 30 | 15 | — | 5 | 360 | — |
| F3 | 50-70 | — | 0-20 | 0-20 | 0-20 | 0-3 | 360 (slightly lower possible) | — |
| F4 | 70 | 30 | 30 | 15 | — | 3 | 380 | steering linearity ~5 |
| F5a/F5b | 80-100 (**same at 5 and 8 Nm**) | 0 | 0 | 0 | 0 | 0-3 | 300-360 | — |
| F6 | 90 on screen [A]; spoken 75-90 at 8 Nm | 0 | 0 | 0 | 0 | 1 (spoken: off) | 360 (spoken 300-360) | — |
| F7 | **90-100 at 8 Nm** (description) | 0 | 0 | 0 | 0 | 0 | 360 | — |
| F8 | 100 | 15 | 15 | 10 | 0 | 0 | ~330 | — |
| F9 | ~115 [A] | 0 | 0 | 0 | 0 | 0 | ~310 | brake deadzone 3 [U] |
| F10 | 110 | 70 | 40 | 25 | 50 | 0 | 400 | — |
| F11 | ~60 [A] | ~25 | ~25 | ~15 | 0 | 0 | 360 | brake deadzone 3, brake linearity 3 [U] |

URLs:
- F1/F2: `https://www.fanatec.com/explorer/games/f1-2024/f1-25-fanatec-recommended-settings/`
- F3: `https://www.fanatec.com/us/en/explorer/products/racing-wheels-wheel-bases/f1-25-2026-season-pack-launches-today/`
- F4: `https://web.archive.org/web/20260712081334/https://simracingsetup.com/ea-sports-f1/f1-25-fanatec-wheel-settings/` and `https://web.archive.org/web/20260610154916/https://simracingsetup.com/ea-sports-f1/f1-26-fanatec-wheel-settings/`
- F5: `https://web.archive.org/web/20260509143649/https://simracingsetup.com/ea-sports-f1/f1-25-fanatec-wheel-settings-esports/`
- F6: `https://www.youtube.com/watch?v=67fkv68XPRc`
- F7: `https://www.youtube.com/watch?v=hGUFX4C-KJk`
- F8: `https://www.youtube.com/watch?v=fN72kvthVrU`
- F9: `https://www.youtube.com/watch?v=b1HmTpQ0KZk`
- F10: `https://www.youtube.com/watch?v=gOrxAbx1sMI`
- F11: `https://www.youtube.com/watch?v=RN_TQcpQMgA`

Source caveats:
- **F1:** re-fetched 2026-10-10; still dated 2025-07-01. SimRacingCockpit (Richard Baxter; modified 2026-09-27) republishes these values and says v1.25 is the current build, but did no new testing. The page's bonus tip (lower Tuning Menu FF if the base clips) conflicts with Fanatec help 43901256649233 (raise FF, lower in-game strength).
- **F3:** claims to match F1 25 but does not. Gives one in-game range for every base from 5 Nm to Podium, so it cannot support a torque-scaling rule **[D]**.
- **F4:** the live page was re-read 2026-10-10 and is unchanged. The F1 26 page also says default presets are not tuned for competitive consistency. It lists FullForce values for ClubSport/Podium bases and claims FullForce effects in F1 26 without evidence. Classified balanced because the site's own esports page calls this its guide for most sim racers.
- **F5a/F5b:** identical in three Wayback snapshots (2025-11 to 2026-05). Same author, same table: FF 100 and in-game 80-100 at both 5 and 8 Nm. Strength is lowered only for bases above 8 Nm (§5.2).
- **F6:** the spoken values contradict the screen for FEI and damper; both are recorded.
- **F7:** the 2026-09-07 update is in the description. It says to raise in-game strength by 10-20 because the game added damper and inertia; that cause is **[U]** (EA's notes say only "closer input-to-physics match"), but several players report lighter FFB after v1.25.
- **F8/F9:** music-only videos, values from storyboards.
- **F10:** transcript-confirmed. It lowers FF and raises in-game strength and FOR, the opposite of Fanatec's advice.
- **F11:** title and description say only "CSL DD QR2". All 548 channel uploads were checked: there is no 8 Nm follow-up, and the 2026-09-19 "more realistic" video has no FFB values.

### 4.2 F1 25: other Fanatec bases (context for the torque question; not in the JSON)

| Base | FF | In-game | Peak scale [D] (base Nm × FF × strength, if linear) |
|---|---|---|---|
| Fanatec 2025: CSL DD / GT DD at 5 Nm | 100 | 80 | 4.0 Nm |
| Fanatec 2025: CSL DD / GT DD at 8 Nm | 100 | 80 | 6.4 Nm |
| Fanatec 2025: ClubSport DD (12 Nm then) | 75 | 100 | 9.0 Nm |
| Fanatec 2025: ClubSport DD+ (15 Nm then) | 65 | 100 | 9.75 Nm |
| Fanatec 2025: Podium DD1 (20 Nm) | 55 | 60 | 6.6 Nm |
| Fanatec 2025: Podium DD2 (25 Nm) | 50 | 50 | 6.25 Nm |
| SRS esports: CSL DD 5 Nm / 8 Nm | 100 | 80-100 | 4.0-5.0 / 6.4-8.0 Nm |
| SRS esports: ClubSport DD 12 Nm / DD+ 15 Nm | 80-90 | 60-70 / 50-60 | 5.8-7.6 / 6.0-8.1 Nm |
| SRS 380 page: ClubSport DD / DD+ / DD1 / DD2 | 70 / 60 / 50 / 45 | 100 / 100 / 55 / 45 | 8.4 / 9.0 / 5.5 / 5.1 Nm |
| Fanatec 2026: every base | CS DD/DD+ 70 (FUL 50), DD1/DD2 60, Podium DD 60 (FUL 50) | 50-70 | — |

Torque ratings for 2025 tables predate App 1.4.2.3, which raised ClubSport DD holding torque to 15 Nm and DD+ to 18 Nm, so the cross-base Nm figures are approximate.

### 4.3 F1 25: kept for reference but not presets for this rig

| Source | Why it is not a preset here |
|---|---|
| Jarno Opmeer, F1 25 (2025-06-01, `https://www.youtube.com/watch?v=ZyCpIu_34kw`) | PC; Fanatec base model unknown and probably high torque, so **strength 65 does not transfer**. What transfers: effects 0, damper 0, rotation 300 (says 270-360 works), no steering deadzone/linearity/saturation, deadzone only if input at rest, **brake linearity left at its default 25**. He judges clipping by feel to start above about 65-70 on his base |
| Carson F1, **F1 24** FFB guide (2024-12-09, `https://www.youtube.com/watch?v=_IfqK3kKHzA`), **F1 24 only** | Same menu item names. 8 Nm: FF max, FFS Peak, effects 0, in-game **55-70**. His short F1 24 video (9sHaM9DzW6I, 2025-01-07) gives 50-70 for "CSL DD". Kept only to show **version drift**: the same creator at the same 8 Nm went 55-70 (F1 24), then 75-90 (F1 25), then 90-100 (after v1.25) |
| SRS all-wheels guide (350°, mod. 2025-06-10) | Older revision of F4 by the same author |
| RacingGames.gg (2025-06-18, upd. 2026-08-26) | Generic, not direct-drive (T248R/G923): 60 / 15 / 10 / 10 / 0, damper 10, rotation 310, brake deadzone 6 |
| Gaspedal "Improved FFB" mod (OverTake.gg) | PC-only file mod; never reachable on PS5 |
| EA Forums bug report (Raziel_Orion, 2026-09-10, CSL DD 8 Nm, PC, v1.25) | A bug report, not a recommendation: FF 100, NDP 50, NFR/NIN OFF, INT 11, FEI/FOR/SPR/DPR 100, in-game 75. **The session-change oscillation still happened with this heavy damping** |
| EA default bindings (2026 hub, G923 example); EA F1 25 gamepad calibration screenshot | Used only for the binding and default notes in §3.5 |

### 4.4 GT7: GT DD Pro (PS5)

Everything before **1.71 (2026-08-20)** is stale. None of the pre-1.71 presets sets FUL.

| # | Preset | Author | Published / GT7 era | Torque | Pedals | Style (source → class) | Status | Conf. |
|---|---|---|---|---|---|---|---|---|
| G1 | Fanatec official GT7 (PS4/PS5) | Dominic Brennan (Fanatec forum admin) | 2022-03-03, launch | "suitable for 5 Nm and 8 Nm" | — | "reasonable baseline values" → official_default | superseded by G2 | medium |
| G2 | GT7 Auto Setup (A SET) after 1.71 | Polyphony notice; values from a community readout | 2026-08-20 | readout at 8 Nm; applies to both **[U]** | — | "optimised set of parameters" → official_default | **current** | medium |
| G3 | SimRacingSetup GT7 GT DD Pro | Rich (SRS) | mod. 2024-03-20 (pre-1.49) | — | — | balanced **[D]** | stale | low |
| G4 | DG Edge "Best settings for GT DD Pro" | Mihael Matika | 2023-06-29, upd. 2025-02-18 | 8 | ClubSport V3 + BPK | balanced **[D]** | stale | low |
| G5 | Abarth_71 (GTPlanet + Google Doc) | Abarth_71 | 2025-02-07 (~1.55) | 8 | Simnet | comfort **[D]** | stale | low |
| G6 | Greg G. "2026 settings" | Greg G. (DG Edge forum) | ~2026-04-21 (pre-1.71) | 8 | ClubSport V3 + perf. kit | "rawest and most 'linear'" → realism | stale | low |
| G7 | Doughtinator | Chris Doughty | 2026-06-26 (pre-1.71) | 5 only (FFS LIN) | — | balanced **[D]** | stale | low |
| G8 | TheNormsk, custom slot after the hotfix | TheNormsk (GTPlanet #1206) | 2026-09-30, 1.71 + hotfix | 8 (5 Nm base + official 8 Nm PSU) | CSL Elite V2 | "8 Nm is plenty", "tuned down" → comfort **[D]** | **current** | low |
| G9 | PirovacBoy (markdown only) | PirovacBoy (GTPlanet 13915486) | 2022-12-29 (pre-1.49) | 8 | **CSL Pedals + LC Kit** | "most pleasant driving experience" → balanced **[D]** | stale | low |
| G10 | Abarth_71 2023 (markdown only) | Abarth_71 (GTPlanet 13973048) | 2023-03-16 (pre-1.49) | 5 **[U]** | **CSL Pedals + LC Kit** | trail-brake modulation → competitive **[D]** | stale | low |

| # | SEN | FF | FFS | NDP | NFR | NIN | INT | FEI | FOR | SPR | DPR | FUL | Pedal | Max. Torque | Sensitivity | Other |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| G1 | AUTO | 100 | PEA | 38 | OFF | OFF | 2 | 100 | 100 | 100 | 100 | — | — | 5 | 1 | Countersteering Off |
| G2 | **A SET** (read-only); readout: AUTO | 100 | — | 40 | 2 | OFF | 4 | 100 | 100 | 100 | 100 | 100 | — | 4-5 (community) | 1-2 (community) | — |
| G3 | AUTO | 100 | PEA | 50 | OFF | OFF | 1 | 95 | 100 | 100 | 100 | — | — | 6 | 1 | Countersteering Off |
| G4 | AUTO | 100 | PEA | 15 | 10 | 5 | 3 | 100 | 100 | OFF | 50 | — | BRF 100 (CSP V3) | 6 (Gr.1 3, Gr.2 4, Gr.3 5-6, Gr.4 7) | 10 | — |
| G5 | — | 100 | PEA | 42 | 25 | 10 | 15 | 80 | 80 | n/a | n/a | — | — | 6 | 10 | — |
| G6 | AUTO | 100 | PEA | 20 | 5 | OFF | 5 | 90 | 100 | OFF | OFF | — | BRF 60, BLI 100 (CSP V3) | 6 (by class as G4) | 1 | — |
| G7 | AUTO | 100 | **LIN** | OFF | OFF | OFF | 2 | 100 | 100 | 100 | 50 | — | — | 5 | 1 | — |
| G8 | AUTO | **70** | — | 16 | 6 | 0 | 2 | **60** | 90 | 100 | 100 | 100 | BRF 60 (CSL Elite V2) | **9** | 1 | Controller sensitivity 0 (no wheel effect) |
| G9 | AUTO | 100 | PEA | 30 | 10 | 0 (0-2 max) | 1 | 100 | 100 | 100 | 100 | — | **BRF 70 (CSL LC)** | 5 | 1 | — |
| G10 | AUTO | 100 | PEA | OFF | 4 | OFF | OFF | 100 | 110 | OFF | OFF | — | **BRF 85 (CSL LC)** | 5 | 1 | — |

Notes:
- **G1:** read via Wayback (the live forum returns 403). A Fanatec ambassador (2022-03-04) put Max. Torque ~6 at the edge of clipping on 8 Nm. Fanatec's FAQ (30/05/2022) briefly advised Max. Torque 10 after 1.15, which 1.16 reverted.
- **G2:** the only GT DD Pro A SET readout: CrUzO, GTPlanet p.37 #1106, 2026-08-20, App 1.5.3.1, before the hotfix. **No 5 Nm readout and no post-hotfix readout exists**; GTPlanet pages 37-41 and the 1.71 thread pages 26-40 were checked. The in-game guidance comes from RS60NR (p.41, a DD+ owner). Pre-hotfix A SET users:
  - VTEC Driver: 5 Nm, Max. Torque 5 / Sensitivity 3 (p.38, 2026-08-23);
  - mprohorenko: 8 Nm, FW 1.9.1.1, FUL 100, 5 / 3; FFB dropped out five times one evening, a later session was clean.
- **G4:** a second block for a 330 mm rim: NDP 50, NFR 25, NIN 30, INT OFF, in-game 10/10.
- **G5:** says SPR and DPR do nothing in GT7 except centre the wheel in menus.
- **G7:** FFS LIN does not exist with the Boost Kit on current firmware, and gives 4 Nm on a 5 Nm base.
- **G8:** the wheel values come from the post's attached image, read in the gap-fill pass. Peak scale 8 × 0.7 = 5.6 Nm, close to a 5 Nm base at FF 100 **[D]**. Replies: FEI is "quite low" (bliprunner); try A SET with 4-5 / 1-2 (RS60NR). The poster later moved to a DD+.
- **G9/G10:** the only GT7 presets made on the user's exact pedals, but pre-1.49 and stale. Their BRF values are used in §4.6; they are not JSON presets. G9's owner reported a jittery LC signal under constant pressure (2022-03-29) and a sudden cap at ~30% input at BRF 70 (2023-07-11): see the §8 fault signatures.

URLs:
- G1: `https://forum.fanatec.com/topic/7660-gran-turismo-7-ps4ps5-fanatec-recommended-settings/` (Wayback 20250806160629)
- G2: `https://www.gran-turismo.com/gb/gt7/news/00_3638095.html` and `https://www.gtplanet.net/forum/threads/fanatec-general-discussion.426258/page-37#post-14638399`
- G3: `http://web.archive.org/web/20260418003245/https://simracingsetup.com/product-guides/gt7-force-feedback-settings-fanatec/`
- G4: `https://dg-edge.com/best-settings-for-fanatec-gt-dd-pro-in-2023/`
- G5: `https://www.gtplanet.net/forum/threads/fanatec-clubsport-f1-clubsport-dd-settings-for-gt7-v1-55-and-new-fanatec-driver-464.430637/`
- G6: `https://www.dg-edge.com/community/forum/articles-3/best-settings-for-fanatec-gt-dd-pro-in-2023-161`
- G7: `https://doughtinator.com/en-us/blogs/resources/fanatec-gt-dd-pro-wheel-settings`
- G8: `https://www.gtplanet.net/forum/threads/fanatec-general-discussion.426258/page-41#post-14652059`
- G9: `https://www.gtplanet.net/forum/posts/13915486/`
- G10: `https://www.gtplanet.net/forum/posts/13973048/`

### 4.5 GT7 after 1.71: data points (not presets)

| Who / when | Base | Firmware | Report |
|---|---|---|---|
| Lightsider74, 2026-09-05 (p.39) | **5 Nm** | hotfix | FUL 100, about an hour in GT7, no issues. The only post-hotfix 5 Nm data point |
| Blade_Rudder, 2026-09-04 (p.39) | torque not stated | hotfix (manual) | FUL 60 → 100, no issues so far |
| gelagmeierter, 2026-09-23 (p.40) | 8 Nm | unknown | FF 100, in-game 10, for two years; turned FullForce off because it felt muted (fits the known "weaker than intended" issue) |
| CrUzO, 2026-08-22/25 (p.38) | 8 Nm | pre-hotfix (1.9.1.1) | FUL 23, NDP 20, Max. Torque 5, Sensitivity 2 still disconnected; FUL OFF + Vibration off stopped it. Superseded by the hotfix |
| RS60NR, 2026-08-27 | DD+ | pre-hotfix | Sensitivity 9-10 gives a very fast torque ramp on the base |
| Shackster, 2026-08-22 | GT DD Pro | 1.9.1.1 | Sensitivity 2 → 5 at torque 4 / FF 100 caused an immediate disconnect; FF 80 was fine |
| Haitauer, 2026-08-29/09-01 | GT DD Pro | pre-hotfix | FF 90 instead of 100 felt smoother and stopped shutdowns |
| Wolver76, 2026-08-30 | PS5 Pro, GT DD Pro | pre-hotfix | Torque 5, Sensitivity 4, Vibration 150, FF 100, FUL 40 still lost FFB, with a sustained pull to one side |

These reports support a fallback of 10-20% headroom (FF 80-90) and lower Sensitivity if FFB drops out. App 1.6.1.3 still
lists "can lose FFB in GT7" as a known issue.

### 4.6 CSL Pedals Load Cell Kit: BRF reports from owners

Only reports where the pedal model is the **CSL Pedals LC Kit** (all GTPlanet; the JSON lists them as `pedal_reports`).

| Owner | Date | BRF | Stock? | Context | Latest for owner? |
|---|---|---|---|---|---|
| PirovacBoy | 2022-03-19 | 50 | yes | GT7 launch, GT DD Pro 8 Nm, PS5 | no |
| PirovacBoy | 2022-12-29 (and "always 70" 2023-07-11) | **70** | yes | G9 | **yes** |
| priesty_lfc | 2022-03-23 | **55** | yes | GT DD Pro (Boost Kit assumed), PS5; set via laptop; 100 could not reach max braking | **yes** |
| Theiceman1 | 2022-03-29 | 60 | yes | first test 100 "quite hard", 55 sweet spot; lap times improved | no |
| Theiceman1 | 2022-11-17 | **40** | yes | GT DD Pro, PS5 | **yes** |
| Abarth_71 | 2022-11-18 | 85 | **no** (one 3DRAP progressive elastomer) | — | no |
| Abarth_71 | 2023-03-16 | 85 | yes | G10 | no |
| Abarth_71 | 2023-07-13 | **90** | yes | GT Omega Lite rig; on a modified Playseat he had to go lower | **yes** |
| 0x15e | 2022-10-25 | **~30** | yes (model inferred) | "so stiff"; low BRF made the brake hard to manage at times | **yes** (stock) |
| 0x15e | 2022-11-17 | 65 | **no** (Misumi TM20X25 spring replacing two elastomers) | NLR GT Lite | no |
| super_gt | 2022-04-14 | MAX | **no** (travel limited to 12 mm) | Measured ~60 kg for 100% at BRF MAX on a stock kit; possibly Fanatec-affiliated | — |

**Stock, latest per owner: 30, 40, 55, 70, 90 → median 55, n=5 [D].** Modified pedals ran higher. No CSL LC owner report
exists for F1 25 or for GT7 after 1.71.

Why owners moved BRF:
- **Up:** the stock 65 Shore stack is stiff with little travel. More force for 100% gives more travel and finer trail-brake modulation, and stock elastomers soften over time (Abarth_71).
- **Down:** the default felt like a wall, or 100% could not be reached (priesty_lfc, Theiceman1).
- **Mounting:** a light stand or Playseat forces a lower BRF.

**Not CSL Pedals LC (kept apart, do not transfer):**
- GTPlanet thread 391868 (2020-2021: Groundfish 40-60, NSP525 40-50, DoctorNuu 20-30, FBGT 60, Deadpool 60-70). These are CSL Elite LC V1 or ClubSport pedals, posted before the CSL Pedals were revealed on 2021-05-10, partly on firmware with inverted BRF.
- Yard_Sale 80 (old CSL Elite LC).
- fastone371 30-50 (ClubSport V3).
- Kriptical 60 (ClubSport DD+ 18 Nm, GT7 1.71; pedal not stated).
- Oi Oi JC 65 (sets BLI, so probably ClubSport V3).
- Matt212 30 (CSL Elite LC), Greg G 60 and Matika 100 (ClubSport V3); Carson ~40 and Fin 55 (load cell, model not shown).

### 4.7 Other PS5 titles (not in the JSON)

| Title | What exists | Caveat |
|---|---|---|
| ACC | Fanatec official (PS4 version, **PURPLE** mode, 2020/2021): SEN per car, FF 100, PEA, NDP 25, NFR 5, INT 6, Gain 70, Dynamic Damping 100. SRS (2025-09-29, PC/Xbox/PS4): FFB 90, NDP 5, NFR 10, INT 2, SPR 90, Gain 79, DD 18. Abarth_71 "ACC (PS5)" 8 Nm: NDP 5, NFR 15, NIN 7, INT 5, SPR 30, DPR 80, Gain 67 | PS4 era. The console version reportedly has no Damper slider. Match SEN per car on console |
| EA SPORTS WRC | SRS (Mjolnir, 2023-11-01): SEN 900, FF 95, NFR 10, NIN 15, INT 3, self-aligning torque 80 (65 at 8 Nm), etc. Stated to apply to the GT DD Pro on PS5 | 2023 launch version |

---

## 5. Consensus and disagreement per parameter

### 5.1 F1 25 (F1, F3-F11; F5a/F5b counted once; range midpoints; Opmeer added for effects and damper only)

| Parameter | n | Median | Range | Consensus? |
|---|---|---|---|---|
| SEN / in-game rotation (fixed values) | 9 | **360** | 310-400 | Strong around 360 (Fanatec: matches a real F1 wheel). Esports 300-360, SRS 380, Matt212 400 |
| FF | 10 | **100** | 80-100 | Near-unanimous (Matt212 80) |
| FFS | 9 | **PEA** | PEA only | Unanimous where present. Not offered with the Boost Kit on FullForce firmware |
| NDP | 10 | **25** | OFF-50 | **Split:** OFF-5 (esports, realism: F5, F6, F7, F11); 20-35 (Fanatec, SRS); 50 (Fin 2025, Matt212) |
| NFR / NIN | 10 | **OFF** | OFF-15 / OFF-10 | Only Fin uses them |
| INT | 10 | **3** | 1-11 | Strong 1-3; Fin 6, Matt212 11 (the default) |
| FEI | 10 | **100** | 90-100 | Carson 90 on screen |
| FOR / SPR / DPR | 10 | **100** | 100-110 | Unanimous apart from Matt212's FOR 110 |
| In-game strength | 10 | **90** | 60-115 | **Split by game version and style, not by torque** (§5.2) |
| On Track Effects | 10 | **7.5** | 0-70 | **Split:** 0 (esports-style); 15-30 (official, balanced, realism); 70 (Matt212) |
| Rumble Strip | 11 | **10** | 0-40 | Same split; Fanatec 2026 lowered it to 0-20 |
| Off Track | 11 | **10** | 0-25 | Same split |
| Pit Stop | 9 | **0** | 0-50 | Strong 0 |
| Wheel Damper | 11 | **0** | 0-3 | **Strong 0-3** (Xbox Fanatec 5; RacingGames 10 is an outlier) |
| Steering calibration | — | 0/0/0 | linearity 0-5 | Strong 0; SRS suggests linearity ~5 |
| Brake linearity | — | — | 0 / 3 / 25 | **Split:** Carson 0, F1withNick 3, Opmeer and THOMB 25 (the default per Opmeer). No CSL LC owner data |

**Clipping remedy.** These pieces of advice look contradictory, but they agree once you separate game-side clipping
from base output **[D]**:
- Fanatec's F1 25 page: set weight in game; lower base FF if the wheel clips.
- The manual and help: take extra force from FF rather than in-game gain.
- SRS and Carson: keep FF at 100.

Lowering in-game strength reduces game-side clipping. Lowering FF only scales torque; it cannot undo a command that is
already saturated.

### 5.2 Torque versus in-game strength (the 8 Nm question)

| Evidence | 5 Nm | 8 Nm | Same author? |
|---|---|---|---|
| SRS esports table (F5a/F5b) | FF 100, 80-100 | FF 100, 80-100 | yes, same table |
| SRS 380 (F4) | "can be used" at 5: 70 | built for 8: 70 | yes |
| Fanatec 2025 (F1) | one CSL DD/GT DD row: 80 | same row | yes |
| Fanatec 2026 (F3) | 50-70 for every base, 5 Nm to Podium | same | yes |
| Carson F1 24 → F1 25 → v1.25 (all 8 Nm) | — | 55-70 → 75-90 → 90-100 | yes; **game version** moved the value |
| Only source that lowers strength at 8 Nm | Meathead/f125game.com (55-65 → 45-55) | — | **rejected** (§10) |

Conclusions:
- **[V]** No credible source lowers in-game strength going from 5 to 8 Nm.
- **[D]** If F1 25 sends a normalised force command (not documented for PS5 **[U]**), the base outputs command × FF ×
  maximum torque. At the same in-game strength, game-side clipping is unchanged at 8 Nm and every force is 1.6x larger.
  Scaling strength by 5/8 matches the old weight with more headroom: a weight choice (comfort), not a clipping fix.
- **[D]** Cross-base peak scales (§4.2) put the authors' 8, 12 and 15 Nm targets around 6-8 Nm. At 5 Nm the user sits
  below that range, so the kit moves them up to the authors' target, not past it.
- Fanatec says the Boost Kit adds headroom and that higher-torque bases lower clipping risk (help 30312079505553). It
  never tells 8 Nm owners to cut in-game strength.
- **Caution [D]:** base FW ≥ 1.9.0.2 raised Boost Kit holding torque from 6 to 8 Nm. Long high-load corners therefore
  feel heavier than they did for creators on older firmware. If the first sessions are tiring, step down 5-10.
- **No measurement** of F1 25 game-side clipping against strength exists on PC or PS5. Every F1 25 clipping number
  (for example Opmeer's "above 65-70" by feel) is **[U]**.

### 5.3 GT7 (G1-G10)

| Parameter | n | Median | Range | Notes |
|---|---|---|---|---|
| SEN | 9 | AUTO | AUTO (one user 600 for GT3) | Strong |
| FF | 10 | 100 | 70-100 | G8 tuned down to 70 |
| NDP | 10 | **25** | OFF-50 | Fanatec 38; A SET readout 40; post-hotfix custom 16 |
| NFR | 10 | **4.5** | OFF-25 | A SET 2 |
| NIN | 10 | OFF | OFF-10 | |
| INT | 10 | **2** | OFF-15 | Abarth 15 is the outlier; A SET 4 |
| FEI | 10 | 100 | 60-100 | G8 60 |
| FOR | 10 | 100 | 80-110 | |
| SPR / DPR | — | — | — | **Moot**: known issue (not working in the GT7 menu); users say they do nothing while driving |
| Max. Torque | 10 | **5.5** | 3-9 | Pre-1.71: 5-6 (3-7 by class). Post-1.71: guidance 4-5 with A SET; 8 Nm reports 5 to 10, **no consensus** |
| Sensitivity | 10 | **1** | 1-10 | **Split:** 1 (most) vs 10 (Matika, Abarth). Before the hotfix, high Sensitivity together with high torque and high FUL was linked to disconnects |
| FUL | — | 100 | OFF-100 | Default 100 after the hotfix; interim advice was below 100 or OFF |

### 5.4 BRF (Load Cell Kit)

| Population | n | Median | Range | Use? |
|---|---|---|---|---|
| **CSL Pedals LC owners, stock, latest per owner** | 5 | **55** | 30-90 | **Yes**: the basis for §6.3 |
| CSL Pedals LC, all stock reports | 9 | 55 | 30-90 | consistent |
| CSL Pedals LC, modified | 3 | — | 65-MAX | no (non-comparable stacks) |
| F1 creators, mixed or unknown load cells (Carson ~40, Fin 55, Matt212 30) | 3 | 40 | 30-55 | no (models differ) |
| Revision 1 "median ~48" (mixed, non-CSL) | — | — | — | **withdrawn** |

---

## 6. Recommendations for this rig (PS5, GT DD Pro, CSL Pedals → Boost Kit 180 → Load Cell Kit)

### 6.0 Steps common to every style

1. **DARK BLUE** mode. Hold Tuning ~4 s for the **Advanced** menu and pick a **custom slot** (suggested: 1 SET = F1 25,
   2 SET = GT7 custom, 3 SET = experiments). Do **not** use A SET for F1 25.
2. Firmware (Windows PC, RED mode): be on the current set (base 1.9.2.3) before fitting the Boost Kit or the LC kit. Then
   return to DARK BLUE, recalibrate the wheel centre and recheck the slot values.
3. **Set SEN to the same number as F1 25 Maximum Wheel Rotation.** Do not rely on AUTO in F1. Turn the wheel 90° and check
   the in-game wheel matches.
4. Stock CSL pedals, and the LC kit without Manual Mode: after **every power-on**, press each pedal fully once (hold the
   brake at max 2-3 s) and release.
5. F1 25 calibration baseline: steering 0/0/0; throttle 0/0/0; brake deadzone 0 and saturation 0. For brake linearity see the pedal tables.
6. Change one thing at a time and record it next to the capture (§7).
7. **F1 25 v1.25 bug:** if the wheel oscillates or loses FFB after a session change, pause and power-cycle the base. Do
   not tune against it.
8. Leave **FUL** at its default for F1 (no confirmed effect).

### 6.1 Now: GT DD Pro 5 Nm + CSL Pedals (Hall position brake), F1 25 + 2026 Season Pack (v1.25+)

| Item | official_default (F1) | balanced (F4) | competitive (F5a, F6, F7) | realism (F11) | comfort **[D], no source** |
|---|---|---|---|---|---|
| SEN | 360 | 380 | 360 (300-360) | 360 | 360 |
| FF / FFS | 100 / PEA | 100 / PEA | 100 / PEA | 100 / PEA | 100 / PEA |
| NDP | 35 | 35 | OFF (≤5) | OFF | 40-50 |
| NFR / NIN | OFF | OFF | OFF | OFF | OFF (a little NFR only for oscillation) |
| INT | 3 | 3 | 1-3 (source 0-5) | 3 | 3-5 |
| FEI | 100 | 100 | 90-100 | 100 | 80-90 |
| FOR / SPR / DPR | 100 | 100 | 100 | 100 | FOR 80-90; SPR/DPR 100 |
| VIB_FFB_STRENGTH | 80 | 70 | 80-100 (5 Nm row); after v1.25 start at 90-100 **[D]** | ~60 [A], raise in steps of 5 while mid-corner load still feels distinct | ~60 |
| On Track / Rumble / Off Track / Pit Stop | 30 / 30 / 15 / 0 | 30 / 30 / 15 / 0 | 0 / 0 / 0 / 0 | 25 / 25 / 15 / 0 | ≤15 / ≤10 / ≤10 / 0 |
| WHEEL_DAMPER | 3 | 3 | 0 (0-3) | 0 | 3-5 |
| MAX_WHEEL_ROTATION | 360 | 380 | 360 | 360 | 360 |
| Steering linearity | 0 | ~5 | 0 | 0 | 0 |
| Confidence | high | high | medium | low | derived |

Pedal calibration, stock CSL (Hall), F1 25:

| Item | official / balanced / comfort | competitive | realism |
|---|---|---|---|
| Brake deadzone | 0 (1-3 only if the rig check finds input at rest) | 0 | 3 [U] (F1withNick, who appears to use CSL Pedals) |
| Brake saturation | 0 | 0 | 0 |
| Brake linearity | leave the preset default (EA gamepad default 25; PS5 wheel default unverified) | 25 [U] (Opmeer keeps the default; a less sensitive start can help trail braking on a position pedal, Joyce et al. 2025 **[D]**) | 3 [U] |
| Throttle deadzone / linearity / saturation | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

- **Official alternative (F3, 2026 page):** NDP 20, INT 3, strength 50-70, Rumble/Off/Pit 0-20, damper 0-3, rotation 360,
  SEN manual. Newer, but generic across bases, and it contradicts F1.
- **Realism:** SRS esports argues kerbs are felt mostly through the seat; the only self-declared realism preset (F11)
  keeps 25/25/15. Real F1 steering torque is far above 8 Nm (no credible figure found), so realism here means the
  strongest force that still feels unclipped and linear.
- **Competitive:** a lab study (Murphy et al. 2026, n=59, iRacing GT3) found faster laps with mid-intensity FFB than with
  high or no FFB. Esports F1 sources run 80-100. Neither tested F1 25 on a 5 Nm base.
- **Comfort:** no F1 25 source. Built from Fanatec guidance (FOR 80-90 to reduce fatigue, FEI 80-90 if harsh, NDP as the
  calming tool) with low effects to cut noise.
- **Oscillation:** if the wheel oscillates hands-off on straights with NDP OFF, raise NDP in steps of 5 first.

### 6.2 After the Boost Kit 180 (8 Nm)

1. Fit the kit; the base detects it. **FFS is not offered with the Boost Kit on base FW ≥ 1.9.0.2**. If it is still shown,
   set PEA (LIN = ~6 Nm). Note what each slot reports as max torque (a user saw 6 Nm in slots 1-4 **[U]**).
2. Keep every Tuning Menu value from §6.1. The endstop does not depend on FF on current firmware.
3. **Keep the in-game strength (rule f1_torque_5_to_8_keep_strength).** Forces rise up to 1.6x.

| Item | official_default | balanced | competitive | realism | comfort |
|---|---|---|---|---|---|
| Tuning Menu | as §6.1 | as §6.1 (F4 is built for 8 Nm) | as §6.1; Carson 8 Nm: NDP OFF, INT ~1, FEI ~90 | as §6.1 | as §6.1 |
| VIB_FFB_STRENGTH | **80** [V] (alternative 50-70) | **70** [V] | **90-100** [V] (Carson after v1.25; SRS 8 Nm row 80-100 before v1.25); start 95 **[D]** | **start ~60**, raise in steps of 5 **[D]** | **~40 [D]** (5/8 of ~60), or keep 60 with FF 63 |
| WHEEL_DAMPER | 3 | 3 | **0** (Carson) | 0 | 3-5 |
| Confidence | high | high | medium | low | derived |

- **Exact A/B against the old 5 Nm feel [D]:** FF 63 with unchanged in-game values reproduces the 5 Nm torque map,
  including its clipping. Use it for a back-to-back test, then return to FF 100.
- **First sessions [D]:** holding torque is now 8 Nm, so long corners feel heavier than on older-firmware 8 Nm presets.
  Step down 5-10 if tiring.
- **8 Nm oscillation:** comments on Fin's 8 Nm video report hands-off oscillation compared with 5 Nm **[U]**. With NDP OFF,
  expect to need NDP 5-20.
- **v1.25 session-change bug:** every report that states a torque is at 8 Nm, so the user may first meet it after
  fitting the kit **[D]**. Power-cycle the base between sessions until EA's patch lands. Downgrading to pre-FullForce
  firmware (App 1.4.3.4 / base 1.8.1.7) fixed it for some PC users, but it also removes GT7 FullForce, the GT7 hotfix
  and the 8 Nm holding-torque change. Not recommended while a fix is pending.
- **Hardware:** QR2 is reportedly recommended for 8 Nm, but only in a low-reliability support reply **[U]**. Keep airflow
  around the passively cooled base.

### 6.3 After the CSL Pedals Load Cell Kit

1. Update base firmware first. Install as in §3.4 and **never connect RJ12 and USB together**. On PS5 the LC kit works
   only through the base.
2. **BRF** (Tuning Menu; visible in the Standard menu too):

| Style | BRF start | kg estimate **[D, unverified linear model]** | Basis |
|---|---|---|---|
| official_default | 050 | ~32 kg | Factory default |
| balanced | ~55 (50-60) | ~35 kg | Median of CSL LC owners' latest stock values (n=5) |
| competitive | 65-75 (start 70) | ~43 kg | More force for 100% gives more travel and finer trail-brake modulation (Abarth_71 85-90, PirovacBoy 70). Above 75 only on a rigid cockpit |
| realism | 65-75 (start 65) | ~41 kg | Highest force you can repeat for 10 hard stops without lifting off the seat. Joyce et al. 2025 calibrated at 38 kg (≈ BRF 60 on this model) |
| comfort | ~40 (35-45) | ~27 kg | Theiceman1 40; below ~40 the brake became hard to manage (0x15e at ~30) |

   Method: choose a firm press you can **repeat every lap**, not your maximum. EveZone suggests ~70-80% of your physical
   limit; SimXPro says 100% should not need straining. Do 10 identical stops. If the peaks vary a lot, lower BRF. If
   100% comes too easily (long plateaus at 100%), raise it.
3. **F1 25:**
   - Brake saturation 0 (fix the range with BRF).
   - Brake deadzone 0. Load cells can show 2-3% at rest, so use 1-3 only if the rig check finds it, and check that it does not swallow trail-brake input.
   - Brake linearity: no CSL LC owner data for F1 25. The pedal now measures force, not travel, so retune it from the rig check. In Joyce et al. 2025 the load cell gave longer trail braking than a Hall pedal, mainly because of the response curve.
4. Without a PC there is no manual min/max: do the press-fully routine after every power-on. If the brake reads at
   rest: firmware update plus pedal reset via PC.
5. PS5 lock-margin levers: higher BRF, lower **Brake Pressure** in the F1 25 car setup, more brake linearity.
   **BLI is not available** (ClubSport V3 only).
6. **GT7:** BRF is the only lever (the in-game calibration claim is **[U]**). 2022 reports describe the LC brake as very
   sensitive in GT7. 1.71 changed brake input, so recheck. The owner BRF values above were mostly set in GT7.
7. Recheck BRF after every base restart or firmware update (history of reset bugs).
8. **Fault signatures are hardware, not reasons to change BRF** (§8):
   - the peak suddenly far below 100% at the usual press;
   - the signal oscillating under constant pressure;
   - light pressure reading full brake;
   - input with the foot off the pedal.

### 6.4 GT7 at 5 Nm and 8 Nm (needs App ≥ 1.5.4.2 hotfix firmware)

| Style | 5 Nm | 8 Nm | Confidence |
|---|---|---|---|
| official_default | **A SET**; Max. Torque 4-5, Sensitivity 1-2 (community; a 5 Nm owner ran 5 / 3 before the hotfix); Countersteering Off | same; post-hotfix 8 Nm reports range 5-10 | medium |
| balanced | **No post-1.71 source.** Use official_default | same | — |
| competitive | **No source with values.** GT World Series drivers used the GT DD Pro at 8 Nm with **stock CSL Pedals** until late 2024 (hardware only). Use official_default | same | — |
| realism | G6 (8 Nm source, pre-1.71, stale): custom slot SEN AUTO, NDP 20, NFR 5, NIN OFF, INT 5, FEI 90, FOR 100, SPR/DPR 100 (source OFF; moot), FUL 100; Max. Torque 6 by class (Gr.1 3, Gr.2 4, Gr.3 5-6, Gr.4 7), Sensitivity 1. At 5 Nm the same Max. Torque gives less force | G6 as published | low |
| comfort | **No 5 Nm source.** Derived from G8 at equal peak torque **[D]**: FF 100, FUL 100, NDP 16, NFR 6, NIN OFF, INT 2, FEI 60, FOR 90, SPR/DPR 100; Max. Torque 9, Sensitivity 1 | **G8** (post-hotfix): FF 70, FUL 100, NDP 16, NFR 6, NIN OFF, INT 2, FEI 60, FOR 90, SPR/DPR 100; Max. Torque 9, Sensitivity 1 | low |

- To customise A SET: read its values on the wheel while GT7 runs and copy them into a custom slot. The only readout
  (8 Nm, pre-hotfix) is SEN AUTO, FF 100, FUL 100, NDP 40, NFR 2, NIN OFF, INT 4, FEI/FOR/SPR/DPR 100.
- **FUL:** 100 on hotfix firmware. If FFB drops out or the base disconnects: FUL 60, then OFF; then FF 80-90 and a lower
  Sensitivity (§4.5).
- **5 → 8 Nm:** Fanatec's GT7 values are stated to suit both torques. Restart at Max. Torque 5 (4-5 with A SET) and
  step up.
- Fanatec's GT7 wobble article: raise NDP first, then NFR, then NIN. Some cars may need their own slot.

---

## 7. Tuning methodology

Sources: Fanatec F1 25 and oscillation pages, SimXPro, Murphy 2026, Joyce 2025, HP Academy.

1. **Fix the test:** same car, track, weather and fuel; one long high-load corner plus one kerb section. Change **one
   setting at a time** and record it next to the capture.
2. **Rotation first:** SEN equal to in-game rotation; confirm the 90° alignment. Steering deadzone and saturation stay at 0.
3. **Strength without a clipping meter (F1 25 on PS5):** in the high-load corner, adjust in-game strength in small steps.
   Stop when load building and releasing mid-corner is still distinct and heavy corners feel different from light
   ones. Do not fix numbness with more damping; lower the gain first. Clipping on kerbs matters little on direct drive;
   clipping on smooth high-load corners is the problem. One guide matches the clipping onset found in a sim with a
   meter (ACC, iRacing, LMU); with FF 100 that onset also does not depend on base torque **[D]**.
4. **5 → 8 Nm:** keep the in-game value. Optionally A/B with FF 63 for the exact old feel. Choose comfort (×5/8) only if
   the new weight is tiring.
5. **Detail versus noise:** use the lowest INT that removes grain (Fanatec: 3), then FEI 90/80 if still harsh.
6. **Stability ladder (Fanatec):** NDP in steps of 5 → INT low (1-5) → lower overall strength → a little NFR → NIN with
   care. Keep damping in one place (NDP) and the in-game damper low (0-3) **[D]**. Oscillation at a session boundary
   in F1 25 v1.25+ is the game bug (§9), not a tuning problem.
7. **Pedals:** get the hardware range right first (BRF; press-fully calibration). Use in-game saturation only to close a
   remaining gap **[U]**.
8. **Revalidate** after any firmware update, game patch (F1 v1.25; GT7 1.71; GT7 Spec IV) or hardware change.

---

## 8. Telemetry rig check

**What telemetry can and cannot show.** F1 25 sends `m_throttle`/`m_brake` (0-1) and `m_steer` (−1..+1) at up to
~60 Hz on PS5. These are processed inputs, very likely after in-game calibration **[U]**. GT7 sends:
- brake byte 0x92 (input);
- throttle 0x91 (possibly after TCS);
- an alternative brake byte (possibly after ABS);
- steering-wheel rotation in radians (packet variant B+).

See docs/research/gt7-protocol.md. **Neither game sends FFB torque.**

**Verify processing order once [D]:** in Time Trial, stationary, compare telemetry with the calibration bar at rest,
mid-travel and full. Then set Brake Saturation from 0 to 20 and check that the same press reads higher.

**Braking event** (Joyce et al. 2025, Sensors 25(13):3872): a non-zero brake run with peak > 10%, with ≥ 100 zero frames
on each side at 50 Hz (use 120 at 60 Hz). Per event:
- BA: mean non-zero brake;
- TPB: time from onset to max;
- TBD: time from the last frame at peak to 0;
- BD: total brake time.

Their reference values are **ACC GT3, not F1**: TPB 0.31-0.38 s, TBD 0.94-1.26 s, BD 1.94-2.16 s, BA 56-63%.

| Metric | Definition | Good **[H]** unless sourced | If high | If low |
|---|---|---|---|---|
| `brake_at_rest_max` | max brake while throttle ≥ 0.95 on straights | ≤ 0.005 | Hall: press-fully routine, mechanics. LC: elastomer/piston preload, firmware + pedal reset. Then BRAKE_DEADZONE +1..3 | — |
| `throttle_at_rest_min` | per-lap minimum throttle | 0.0 | Press-fully routine; THROTTLE_DEADZONE +1..2 | — |
| `throttle_peak_straights` | p99 throttle on straights | ≥ 0.99; **> 0.90 required for S Mode/DRS since v1.25** (sourced) | — | Press-fully routine; small THROTTLE_SATURATION; pedal stop |
| `brake_peak_heavy_zones` | median event peak, entry > 250 km/h | ≥ 0.95 | — | Hall: press-fully, small BRAKE_SATURATION. LC: lower BRF. A sudden collapse: see `brake_peak_vs_history` |
| `brake_time_at_full_pct` | % of braking time at ≥ 0.99, plus flat tops > 0.3 s in low-speed zones | ≤ ~30%; flat tops not concentrated in slow corners with lock-ups | LC: raise BRF. Both: saturation 0, add linearity, lower Brake Pressure; bleed off as downforce falls | see `brake_peak_heavy_zones` |
| `brake_time_to_peak_s` | TPB | near the driver's best laps (ACC ref 0.31-0.38 s) | Hesitant, segmented application | Stabbing; check lock-ups |
| `trail_brake_duration_s` | TBD | near best laps (ACC ref 0.94-1.26 s) | — | Abrupt release: brake linearity, technique |
| `brake_reapply_count` | brake falls ≥ 10 pts then rises ≥ 10 pts before release | 0-1 per lap | Braking too early / modulation (HP Academy) | — |
| `lockup_at_full_brake_share` | share of front lock-ups starting at brake ≥ 0.99 | low | Raise BRF (LC), lower Brake Pressure, add linearity | Lock-ups at partial brake late in the zone: technique |
| `drs_drop_light_brake` | `m_drs` 1→0 while 0 < brake < 0.05 | 0 | Ghost brake: as `brake_at_rest_max` | — |
| `brake_peak_drift_session` | stops 8-10 peak minus stops 1-3 peak at similar entry speed | ≤ 0.05 | Press-fully routine skipped after power-on (auto-calibration); LC: consider PC Manual Mode | — |
| `brake_hold_noise` (LC) | std dev of brake in near-constant holds ≥ 0.3 s | ≤ 0.02, stable across sessions | Hardware/firmware (wiring, never RJ12 + USB together, elastomer seating); not a BRF reason | — |
| `brake_peak_vs_history` (LC) | session heavy-stop peak vs the driver's history at the same BRF | within ±0.10 | Light pressure reads full: possibly a damaged load cell (Fanatec staff); support | Sudden collapse (one owner capped at ~30% at BRF 70): recheck BRF on the wheel, firmware, support. **Do not lower BRF to compensate** |
| `steer_full_lock_share` | time at abs(steer) ≥ 0.99 outside slow hairpins | ~0 (Monaco hairpin needs ~21-22° road-wheel lock vs ~17° normally) | Rotation too low, or STEERING_SATURATION > 0 | — |
| `steer_centre_offset` | abs(median steer) on straights | ≤ 0.01 | Recalibrate the wheel centre | — |
| `steer_roadwheel_linearity` | fit of `m_steer` vs MotionEx `m_frontWheelsAngle` | linear (R² ≥ 0.98) | — | A kink shows linearity or deadzone is set |
| `straight_oscillation_rate` | reversals/s on straights with abs(steer) < 0.05 after low-pass | low (calibrate) | NDP +5, INT 1-5, lower strength, NIN with care. Exclude the brief FFB bump when Straight Mode toggles (reported on PS5 Pro; not a fault) | — |
| `session_start_oscillation` | large rapid reversals with no pedal input in the first seconds after a new `m_sessionUID`/session type, or while paused | none | **Known v1.25 bug:** power-cycle the base. Do not raise NDP/INT/damper. Recheck after the next F1 25 patch | — |
| `steering_reversal_rate` | SWRR per minute (Markkula & Engström 2006; SAE J2944) | driver-relative | Smoothness coaching (ranked a lap-time predictor, Hojaji et al.) | — |

**Lock-up detection.** Use F1 MotionEx `m_wheelSlipRatio` and `m_wheelSpeed` (order RL, RR, FL, FR; sign and units
**[U]**, confirm on a recording). HP Academy flags a lock-up when braking with a left-right front wheel-speed difference
above 10 km/h. Whether F1 25 sends UDP while paused is **[U]**, which limits `session_start_oscillation` to on-track
frames.

---

## 9. Known issues to surface in the Setup UI (not user mis-tuning)

**F1 25 v1.25 session-change oscillation / FFB loss on Fanatec CSL DD / GT DD Pro.**
- Symptoms: after a session change or restart (Q1 to Q2, Qualifying to Race), the wheel oscillates hard or loses FFB.
  On pause it can drive to the end stop. Power-cycling only the base fixes it.
- It happened even at NDP 50 / INT 11, and FUL OFF did not help (GT DD Pro 8 Nm user, Fanatec forum topic 20597,
  2026-10-08). ClubSport DD owners reported it unaffected.
- Every report that states a torque is at 8 Nm (about 12 CSL DD Boost Kit users plus GT DD Pro 8 Nm users). The one
  5 Nm CSL DD report describes muddier FFB, not oscillation. No PS5 report was found, so the PS5 impact is unknown.
- EA timeline: confirmed on its side (09-16); introduced while fixing a crash for players mixing brands (10-01); fix
  shared with Fanatec for approval (10-07); no ETA (10-08).
- Sources: EA thread 13695137 (150 replies, INVESTIGATING), 13701405 (GT DD Pro, PC), 13701710 (CSL DD 8 Nm config),
  forum.fanatec.com topic 20597.

**Other F1 25 issues:**
- After v1.25, players on several brands report lighter or less detailed FFB (EA thread 13746020); pre-September
  strength values may feel lighter. A DD+ owner on PS5 Pro reports a small bump when Straight Mode switches; ignore it
  in the rig check.
- v1.04 fixed FFB stopping after a Time Trial restart. Reports of FFB dropping mid-race on PS5 (fixed by toggling
  Vibration & FFB) and of wrong UDP data with the 2026 pack on a PS5 DD Pro are **[U]**.

**Fanatec App 1.6.1.3 known issues:**
- The GT DD Pro can lose FFB in GT7, with the wheel spinning.
- SPR/DPR do not work in the GT7 menu.
- FullForce is weaker than intended on CSL DD/GT DD Pro.
- SEN AUTO misbehaves in F1 games, so set it manually.
- Heavy oscillation after leaving menus (R3E/rF2/BeamNG) is still listed.
- The mobile app does not work with the new Windows App.

**Pedals and firmware:**
- BRF resets after a restart (fixed in App 1.4.2.3); BRF shown as 0% in the App (fixed in 1.6.1.3).
- A firmware update resets the LC manual calibration and may change the mode.

**GT7:** Spec IV Part 1 is reported for 2026-10-15 (headline only); re-check GT7 values afterwards.

---

## 10. Rejected or downgraded items

| Item | Reason |
|---|---|
| Revision 1 rule "lower in-game strength by 5/8 at 8 Nm" (general) | No source does this; every same-author pair keeps the value. Kept only for comfort **[D]** |
| Revision 1 BRF "community median ~48" | Mixed non-CSL pedals. Replaced by CSL LC owners only (median 55) |
| GTPlanet 391868 "CSL LC users BRF 40-50" (2020-2021) | CSL Elite LC V1 / ClubSport, before the CSL Pedals existed; partly on inverted-BRF firmware |
| Gap-fill advice "start 8 Nm F1 lower, then raise from clipping telemetry" | Clipping is not in F1 25 telemetry; contradicts the same-author evidence. Kept as a first-session caution only |
| Meathead / f125game.com | No byline; lists items that do not exist (DRI, Understeer Enhance); damper 20-35; FFS LINEAR contradicts its own advice. Also the only source lowering strength at 8 Nm |
| SIMGASM 2026 guide | Generic retailer guide; recommends a non-existent F1 25 option; ambiguous date |
| Fanatec F1 23 PlayStation preset | F1 23; only F1 24 fallbacks are allowed |
| Fanatec ACC PS4 preset | PURPLE mode, PS4 version; "SHO 100" cannot be set today. Context only (§4.7) |
| Fanatec support replies (F1 24, 2024-12-09; GT7 8 Nm, 2024-12-28) | Ranges only, not official; the GT7 reply's parameter names do not exist |
| PirovacBoy GT7 1.15 fix; Ricky Smith "drift" collection | 1.15 compensation values, obsolete since 1.16; the Ricky Smith post was mislabelled |
| CrUzO post-1.71 tuned preset (FUL 23) | Superseded by the author (disconnects) and by the hotfix. His A SET readout is kept (G2) |
| Fanatec GT7 baseline via admin.forum snippet | Duplicate of G1; superseded as "official" by 1.71 A SET |
| Kriptical (DD+ 18 Nm), Oi Oi JC (CSP V3) GT7 posts | Not the user's base or pedals; BRF kept only as contrast (§4.6) |
| Param: separate "LIN" (FFB linearity) on GT DD Pro | Does not exist; linearity is FFS LIN/PEA |
| Param: INT default 6, SHO 0-100 | Legacy FAQ for older bases |
| Param: BLI for this rig; Combined Pedals (LC) | BLI needs ClubSport V3; Combined Pedals is PC-only and for legacy games |
| Param: Understeer Enhance; in-game FFB smoothing | Not in F1 25 menus |
| F1 22 effect "ranges 0-100"; F1 22 pad defaults as wheel defaults | False attribution; gamepad preset |
| UDP Format default "new players get 2026" | Not in any reachable source; SRS says the reverse |
| Brake Pressure "100% common baseline" | Not in the cited source |
| "GT DD Pro has no Xbox mode" | Wrong: Xbox depends on the rim |
| RacingGames "default brake saturation 25%" | EA's screenshot shows Brake *Linearity* 25 |
| R55NA "stock CSL LC at 5% and still too stiff" | Conflicts with the documented 010 minimum **[U]** |

**Unreachable during research:**
- forum.fanatec.com: 403 to WebFetch and curl. Read via Wayback and, in the gap-fill, a browser pane without solving any CAPTCHA.
- help.fanatec.com HTML: 403; the Zendesk API was used.
- simracingsetup.com: reCAPTCHA; read via Wayback, plus one browser re-read.
- forums.ea.com: 403 to fetch; patch notes and bug threads read via a browser pane and MP1st/BoxThisLap.
- Reddit (old and new): login wall or 403, so **no Reddit data**. GTPlanet says Fanatec staff post mainly on r/Fanatec.
- OverTake.gg: 403; Wayback used.
- YouTube transcripts: blocked; storyboards and descriptions used. The paid vidIQ tools were deliberately not used.
- WebSearch: the shared 200-search budget ran out during the gap-fill passes, so some discovery searches were not run: other 5 → 8 Nm creators, F1 25 clipping measurements on PC tools, YouTube GT7 1.71 videos and Reddit threads.

---

## 11. Open questions (verify on the user's hardware or with new sources)

1. After fitting the Boost Kit on base 1.9.2.3: is **FFS** gone, and what max torque does each slot report (8 Nm, or 6 Nm
   in slots 1-4 as one user saw)?
2. Does the **v1.25 session-change oscillation** occur on PS5, and at 5 Nm? Does EA's next patch fix it?
3. Is **FUL** shown on this base's PS5 menu at 5 Nm, and does F1 25 do anything with it?
4. Does F1 25 use **A SET**? Does SEN AUTO work in F1 25 on PS5?
5. F1 25 PS5 **wheel-preset defaults** (strength, effects, damper, rotation, calibration; Brake Linearity 25?) and the
   slider maxima.
6. Are UDP `m_brake`, `m_throttle` and `m_steer` reported before or after in-game calibration and ABS? Is UDP sent while paused?
7. Do slots and LC min/max set in the Fanatec App persist unchanged in DARK BLUE mode on PS5?
8. Does the bundled GT DD Pro rim have vibration motors and a display for reading Tuning Menu values?
9. GT7 1.71 **A SET** values at **5 Nm** and after the hotfix. What does the in-game "Vibration" setting do? Does GT7 have the
   claimed Options > Controllers pedal calibration?
10. BRF kg mapping and load cell capacity of the CSL Pedals LC Kit; a CSL LC owner report for F1 25 brake linearity.
11. Does F1 25 v1.25 add game-side damper/inertia (Carson's claim)? A measurement of F1 25 game-side clipping against
    strength (PC FFB-graph tools).
12. The pedal-curve Tuning Menu item reportedly added by FullForce firmware: its name and values.
13. Sign and scale of F1 MotionEx `m_wheelSlipRatio`; units of `m_wheelSpeed`. GT7 throttle/brake byte semantics.
14. GT7 Spec IV (2026-10-15?) FFB changes.

---

## 12. JSON companion: `docs/research/rig-presets-draft.json` (schema revision 2)

Top-level keys:
- `version` (1, as required), `schema_revision` (2), `generated_from`, `generated_on`, `conventions`
- `hardware`: wheel base params with structured `value_type`/`min`/`max`/`enum_values`/`default_value`, plus `firmware_eras`; pedal models
- `games`: params plus `versions`
- `presets` (20)
- `pedal_reports` (11)
- `recommendations` (`wheel` 20, `pedals` 20, `rules`, `common_steps`, `brf_owner_stats`)
- `rig_check` (19)

Fixes made for revision 2:
- **Platform:** `platform` is always one of `games[].platforms` and means where pitwall offers the preset.
  `applies_to_platforms`, `source_platform` (pc | ps5 | ps4 | xbox | pc_ps5 | playstation | not_split | not_stated) and
  `ps5_reachable` are separate fields. Filtering `game=f1_25, platform=ps5` returns 11 presets, covering every style
  except comfort, which has no source.
- **Torque:** `torque_nm` is the source's own torque. `applies_to_torque_nm` (filter on this) and `torque_basis`
  (source_states | source_says_both | source_does_not_distinguish | inferred) are added. SRS esports is split into
  5 Nm and 8 Nm rows; SRS 380 and the Fanatec presets apply to [5, 8]; F1withNick is 5 with `torque_basis` inferred.
- **Pedals:** `pedals` records the source's pedal model and `pedals_basis` how that is known. BRF/BLI moved from
  `wheel_settings` into `pedal_settings`, with `transferable_to_pedals` (empty unless the model is the CSL Pedals LC).
  Reference pedal models (ClubSport V3, CSL Elite LC, CSL Elite V2, unknown load cell, Simnet) are catalogued so the
  keys validate.
- **Values:** every setting is `{value, min, max, evidence, as_published?, note?}` with evidence V/A/U/D. OFF = 0 for
  numeric parameters whose range starts with OFF. Values were range-checked against the params; the validation script
  found 0 errors.
- **Sources:** every source is an object (presets and rig_check alike). Preset sources carry `values_evidence`,
  `access`, `value_extraction`, `game_version`, `software`, `source_hardware`, `source_platform` and `source_words`.
  `verified` now means "an adversarial verifier re-checked it"; gap-fill sources are `false`.
- **Versions:** each preset has `game_version.id` / `predates`, `firmware.era` / `era_basis` / `predates`, `status`
  (current | stale | superseded | not_for_ps5), `stale` and `stale_reasons`. All pre-1.71 GT7 presets are `stale: true`.
- **Recommendations:** the §6 tables are in machine-readable form: `wheel[game, torque_nm, preference]` and
  `pedals[game, pedals, preference]`. No-source styles are explicit entries with `sourced: false`: derived values
  (F1 comfort, GT7 5 Nm comfort) or empty with `fallback_to` (GT7 balanced/competitive). The torque rescaling rules,
  BRF-by-style values (with kg estimates) and GT7 A SET guidance are included.
