# Rig setup and rig check

The **Setup** tab gives recommended settings for your rig, game and driver, step by step in the order you meet
them on the wheel and in the game, and a **rig check** that reads your last session's telemetry to see whether the
hardware reports what you do. Everything here is deterministic; no AI model is involved.

Sources: `docs/research/rig-setup-sources.md` (research **revision 2**, 2026-10-10). The app loads two files:

- `src/pitwall/rig/data/rig_research.json`: a byte-for-byte copy of `docs/research/rig-presets-draft.json`
  (schema revision 2: 20 presets, 11 load-cell owner reports, the game x torque x style wheel table, the
  game x pedals x style pedal table, the torque rules and 19 rig-check metrics). A unit test keeps the two copies
  identical, so a new research revision is copied in whole and re-validated.
- `src/pitwall/rig/data/rig_pitwall.json`: what pitwall adds: preset codes (F1-F11 with F5a/F5b, G1-G8), the
  pickers, rims, on-wheel menu order, known issues, open questions, guide steps, driver rules and the rig-check
  display units and thresholds (checked against the research thresholds at load).

## Using it on the iPad

1. Pick the **driver**, the **game** (F1 25 or GT7) and a **style**: Official, Balanced, Competitive, Realism or
   Comfort. The style and the wheel force are saved per driver, each on its own, so changing one never resets the
   other. While a driver's saved preferences are loading (or if they fail to load) a style tap only changes what
   you see; it never saves to the wrong driver.
2. Check **My rig**. Flip **Boost Kit 180 fitted** or **Load Cell Kit fitted** on the day you fit them, and confirm.
   pitwall records the date so the rig check can compare sessions before and after, and knows which pedals each
   session used. The switch only moves once the change is recorded; cancel or an error leaves it as it was. The
   API refuses an event that would not change the rig (fitting a kit that is already fitted, removing one that is
   not), because the history is replayed to know which hardware each earlier session had.
3. Work down the four sections. **Copy** puts a single value (or a whole section) on the clipboard. Tap a row to
   see where the value comes from.

## Applying the settings on PS5

- **Base mode:** short-press the power button until the LED is **DARK BLUE** (native PlayStation). The Fanatec App
  only works on a Windows PC in RED mode, and you need it for every firmware update.
- **Tuning Menu:** hold the Tuning button for about 4 s for the **Advanced** menu. Most values (INT, FEI, FOR,
  NDP below 25, the 1 SET-5 SET slots) do not exist in the Standard menu; rows marked **ADV** need it.
- **Slots:** the first row is the slot (pitwall's suggestion: 1 SET F1 25, 2 SET GT7, 3 SET experiments). Custom
  slots save every change immediately. Do not use A SET for F1 25. For GT7's Official style, A SET is the point:
  GT7 pushes its own values (rows marked **A SET**, read-only; they are a community readout at 8 Nm).
- **Rim items:** MPS and AP are never shown as rows. The bundled GT DD Pro rim has no multi-position switch or
  analogue paddles; whether it has vibration motors (SHO) is unverified. For another rim pitwall does not know which
  of them it has, so a step says to leave them at their defaults.
- **Driver force:** a younger or newer driver gets a lighter wheel through a lower **FF** in their own spare slot
  (4 SET). Switching drivers is then one menu change. Beginners default to 60% force on the 5 Nm base (about 3 Nm)
  and never get NDP below 20. The default is a weight, not a ratio: on the 8 Nm base it drops by the ratio of the two
  tables' peak torques (40% for most tables, 55% for GT7 Comfort, whose 8 Nm table already runs FF 70), so the
  Boost Kit never makes a beginner's wheel heavier (about 3.2 Nm after rounding FF to 5). F1 Comfort keeps 60%: its
  8 Nm table already lowers the in-game strength by 5/8. A force you set on the driver's slider is a share of the
  table's FF and is used as given; after the Boost Kit the safety box and the upgrade preview say how much heavier
  it gets and which setting keeps the old weight. These are pitwall rules, not published values.
- **SEN must equal Maximum Wheel Rotation** in F1 25. Do not use AUTO in F1 (known issue).
- **Stock CSL Pedals** have Hall sensors and nothing to set. After **every power-on**, press the throttle and brake
  fully once and release them before driving.
- Change one thing at a time, drive the same car and track, and run the rig check again.

## Reading the labels

| Label | Meaning |
|---|---|
| **V** Verified | Read from the source (page, manual, help centre, transcript). |
| **A** Approx. | Read from low-resolution video frames: right ballpark, digits not certain. |
| **U** Unverified | Single source, community claim or conflicting sources. |
| **D** Derived | Computed, inferred or picked by pitwall. Marked "pitwall derived" or "pitwall pick in range". |
| **H** Heuristic | A pitwall rig-check threshold. Not a published number: use it to compare sessions. |

How a value is labelled (checked for every value when the catalogue loads):

- **Sourced:** a basis preset publishes exactly this value. The label is never better than that preset's own label:
  a value read from a video frame stays A even where the research table said V.
- **Pick in a range:** a preset publishes a range (Competitive strength 90-100 at 8 Nm) and pitwall shows a start
  value inside it (95). The value is D; the range keeps its own label.
- **Made for the other torque:** only presets written for the other torque publish the value (GT7 Realism at 5 Nm
  comes from Greg G.'s 8 Nm setup). The row says so and keeps the published label.
- **Cited:** a manual or a single expert (BRF 050 factory default; Opmeer's brake linearity 25). Only these rows
  list the source under "Cited", with the row's own label; a derived row next to them (brake deadzone 0, throttle
  calibration 0) never borrows it.
- **Check on your base:** not a number. FFS after the Boost Kit is one (see below).
- "Sources disagree" means the published presets split on that setting. The row detail lists every other preset's
  value, with the platform the author set it up on and the torques it applies to.

## When the upgrades arrive

- **Boost Kit 180 (8 Nm):** the Tuning Menu values stay as at 5 Nm, with three exceptions: FFS becomes **check on
  your base** (below), **GT7 Comfort** runs FF 70 instead of 100 (G8 is an 8 Nm setup), and a driver with a lighter
  wheel gets a lower FF (see *Driver force*). **The in-game strength stays the same:** no source lowers it from 5 to
  8 Nm (SimRacingSetup's esports table, its 380 page, Fanatec's one CSL DD/GT DD row and Fanatec's 2026 page all use
  the same value at both torques). At FF 100 the base peaks at 8 Nm instead of 5 Nm (1.6x); the texts quote the
  peak from the FF row actually shown. Only **F1 Comfort** scales the strength by 5/8 (60 becomes 40, marked
  derived) to keep the 5 Nm weight. Competitive goes from 90 to 95 (Carson after v1.25 runs 90-100 at 8 Nm; 95 is
  pitwall's pick). GT7's Max. Torque is never rescaled; for GT7 Official, research 6.4 says restart at Max. Torque 5
  (4-5 with A SET) and step up.
  For an exact A/B with the old 5 Nm feel (F1 25, full-strength slot only), set FF 63 for one test, with the 5 Nm
  in-game strength where the 8 Nm table changed it (Comfort 60, Competitive 90), then go back to the 8 Nm values.
  A driver with a lighter slot never gets this step: their FF is already lower. Holding torque is 8 Nm on current
  firmware, so if the first sessions are tiring: in F1 25 step the strength down by 5-10; in GT7 lower Max. Torque
  by 1-2 (it runs 1-10) or FF by 10-20 in a custom slot; or use Comfort (not offered when Comfort is already the
  style). The step and the safety box say "stays", "goes up" or "is lowered" from the two tables, never from intent,
  and their evidence label is never stronger than either table's value (F1 Realism's 60 at 8 Nm is D).
- **FFS:** shown as **check on your base**: Fanatec removed FFS for Boost Kit bases on base firmware 1.9.0.2 or later
  (App 1.5.1.2 changelog), but its help articles still describe LIN/PEAK. Set PEA only if it is still shown; note
  what each slot reports as maximum torque.
- **Load Cell Kit:** update the base firmware first, never connect RJ12 and USB together. **BRF** appears at the
  end of the Tuning Menu. Starting points come from owners of this exact kit (GTPlanet, stock elastomers, latest
  value each: 30, 40, 55, 70, 90, median 55): Official 050 (factory default), Balanced 055 (050-060), Competitive
  070 (065-075), Realism 065 (065-075), Comfort 040 (035-045). The kg figures next to them are an unverified linear
  estimate. Tune it so a firm press you can repeat every lap reaches 100%. A peak that suddenly falls far below
  100%, a signal that jitters under constant pressure, a light press reading full brake or input with the foot off
  are hardware faults, not reasons to change BRF.

The Setup tab lists both upgrades under **When the next upgrade arrives**, with exactly which values change and the
driver's peak wheel torque before and after (for example a beginner: FF 60 -> 40, about 3.0 -> 3.2 Nm).

## Known issues (not your tuning)

- **F1 25 v1.25 session-change oscillation:** since v1.25 (2026-09-07) CSL DD / GT DD Pro owners report violent
  left-right oscillation or lost FFB after a session change (Qualifying to Race) until the base is power-cycled.
  Pause and power-cycle the base; do not tune NDP, INT or the damper against it. Every report that states a torque
  is at 8 Nm; no PS5 report was found. EA shared a fix with Fanatec on 2026-10-07. The rig check flags it.
- Also listed in the tab: lighter FFB reported after v1.25, the GT7 FFB-loss and SPR/DPR issues (Fanatec App
  1.6.1.3), FullForce weaker than intended, SEN AUTO in F1, BRF resets, GT7 Spec IV (re-check after 2026-10-15).

## What the rig check means

The check reads the clean laps of the latest real F1 25 or GT7 session (or every usable lap: standing-start and
track-limit laps keep valid inputs); a session of a game it does not cover (Assetto Corsa) is skipped unless you
pick it. A synthetic (generated) session is used only when no real one exists, and is marked. It cannot
see pedal force, BRF, SEN or force-feedback torque: neither F1 25 nor GT7 sends FFB torque, so clipping cannot be
measured. 19 metrics:

| Metric | What it tells you |
|---|---|
| Brake at rest | Highest brake reading on straights with the throttle at 95% or more, away from real braking (brake 10%+ with the throttle at 20% or less): 0.5 s around it and the 1.5 s before it starts are skipped. Should be 0. A reading in the measured samples counts however large, and a throttle feathered below 95% never hides the full-throttle samples next to it. |
| Throttle at rest / Full throttle reached | The pedal returns to 0 and reaches 100%. Since F1 25 v1.25, DRS/S Mode needs throttle above 90%. |
| Full brake in heavy stops | Peak brake in stops entered above 250 km/h. Should reach about 100%. |
| Braking time at 100% | Long plateaus at 100% mean the pedal saturates and you lose modulation. |
| Time to peak / trail-brake release | Your braking shape. Compare with your own best sessions (the reference values are ACC GT3). |
| Brake re-applications | Brake eased off by 10+ points, then pressed 10+ points again within the same stop, per lap with measured stops (a lap whose stops were all cut by lost data is unknown, not 0). A full release or the throttle at 20%+ ends the stop, so two corners braked close together are two stops. |
| Brake peak drift | The last three firm stops (single press, entered above 250 km/h) against the first three. The session's first stops are on the start lap, so its stops count here even when only clean laps are checked. A change means the press-fully routine was skipped after power-on. |
| Brake noise in steady holds | The research statistic: standard deviation of the brake while it is held steady (0.3 s or more), after removing the driver's slow change through the hold with a quadratic fit. An oscillation of 1 Hz or faster under constant pressure counts at full size; slower ones cannot be told from the driver's own modulation. A load-cell check (wiring, elastomer seating); with the Hall brake it is shown for comparison. |
| Heavy-stop peak against your history | Load cell only. Needs earlier sessions at the same BRF; pitwall does not record BRF, so it stays unknown. |
| Time at full lock / centre offset | Rotation too low, or the wheel centre needs recalibrating. |
| Oscillation on straights / reversal rate | Steering activity. Your hands count too, so compare before and after a change. |
| Oscillation after a session change | The F1 25 v1.25 bug: bursts of large steering reversals in the first 30 s of the session while standing still or with no pedal pressed. Paused and garage frames are not recorded. |

Lock-ups against brake level, DRS closed by a light brake touch, and steering against road-wheel angle show as
**unknown**: pitwall does not record wheel slip, DRS state or wheel angle in lap traces yet (and the sign and scale of
F1's wheel slip ratio are open question 13).

**Known limits.** Brake at rest skips the 1.5 s before every real stop, so a ghost reading that shows *only* there
is missed (a constant preload still shows on the rest of the straight), and a brush of the brake at full throttle
earlier than that counts like a rig fault: check the lap before acting on a single short reading. Brake noise
includes whatever the driver does inside a hold faster than a gentle curve.

**GT7:** pitwall reads GT7 steering on a fixed nominal 900 deg scale (the adapter's normalisation; the magnitude is
community-documented), but GT7 sets each car's lock itself (SEN AUTO) and does not report it. Time at full lock and
centre offset are therefore **unknown** for GT7 unless a lock is given (`rotation_deg`), and then informational;
oscillation and reversal rates are informational, measured in wheel degrees on that scale. GT7's throttle and brake
values may be reported after traction control and ABS (unverified).

With an upgrade recorded, the check also shows **before → now** against the latest session of the same driver and
game from before the upgrade (real and synthetic sessions are never compared). Until you have driven since the
upgrade, it says so instead of comparing a session with itself. A session with no driver gets no baseline, so one
driver's session is never compared with another's.

## Real data (PS5, F1 25, GT DD Pro 5 Nm, stock CSL Hall pedals)

**Committed excerpt** (`tests/fixtures/recorded/f1_25_2025_ps5_austria_race-excerpt.pwcap`, four ~5 s windows of
the Austria race, recorded tier): brake at rest 0.001% (pass, 9 s of full-throttle straights), throttle at rest
0.002% and 100% reached, centre offset 0.06%, no time at full lock, session-start oscillation 0 bursts over 8.2 s
on the grid (pass: the session clock stands still there while the driver revs, so time is counted in samples). The
windows are cut around the start/finish line, so they hold no complete braking zone: every braking metric, drift
and hold noise are unknown, never guessed. 6 pass, 2 info, 11 unknown.

**Full Austria race** (the capture behind the excerpt, replayed in memory; lap 2 is the only clean lap):

| Metric | Clean lap 2 | All 3 laps |
|---|---|---|
| Brake at rest | 0.92% (warn) | 0.92% (warn, about 0.4 s in total) |
| Throttle at rest / full throttle | 0.002% / 100% | 0.002% / 100% |
| Full brake in heavy stops | 100% (4 stops) | 100% (10 stops) |
| Braking time at 100% | 38% (warn) | 32% (warn) |
| Time to peak / trail release | 0.35 s / 0.60 s | 0.37 s / 0.49 s |
| Brake re-applications | 2 per lap (warn) | 1.0 per lap (pass) |
| Brake peak drift | 0 points (pass, 6 firm stops with the start lap's) | 0 points (pass, 8 firm stops) |
| Brake noise in steady holds | unknown (no hold) | 0.37% (info: Hall brake) |
| Session-start oscillation | 0 bursts in 9.3 s (pass) | 0 bursts in 9.3 s (pass) |
| Time at full lock / centre offset | 0% / 0.32% | 0% / 0.06% |
| Oscillation on straights / reversal rate | 3.5/s / 93/min | 3.2/s / 83/min |

**The other real sessions of 2026-10-10** (all usable laps: Austria Reverse, Silverstone in two sessions,
Silverstone Reverse, Monza, Montreal, Las Vegas, Suzuka qualifying and race, and a later Austria race recorded as two
sessions of laps 62-71): brake at rest passes everywhere except Las Vegas, which reads about 2.2% for 1 s while
accelerating out of a slow corner at full throttle (a foot resting on the brake), flagged warn. The later Austria
race read 5.4% (fail) before the 1.5 s approach guard: a 5% brush of the brake at full throttle 0.9 s before a real
stop, the driver's foot and not the rig; it now passes. Braking time at 100% is 20-47% in the races (warn above 30%
at Austria Reverse, Monza, Montreal and one of the later Austria sessions). Brake peak drift is between -2.6 and +3.0 points everywhere it can
be measured (pass). Hold noise of the Hall brake (the research statistic) is 0.00-1.19% per session (the load-cell
limit is 2%; a straight-line detrend instead of the quadratic one read up to 1.76% at Las Vegas, from the driver's
dip-and-recover inside a hold). Session-start oscillation is 0 on every grid it could check (the second Silverstone
session, Suzuka qualifying and the laps-62-71 Austria sessions have no grid). Re-applications run 0.5-4 per lap, all genuine
eases-and-presses inside one stop.

The brake sits at 100% for about a third of braking time and the stock brake is easy to bottom out: with a
travel-based Hall brake that is the end of the pedal travel, which the Load Cell Kit and BRF address. Until then,
keep Brake Saturation at 0 and consider a little brake linearity or lower Brake Pressure in the car setup.

What changed against the first rig-check version: real braking now needs the throttle at 20% or less (F1 25 reads
a steady 10% throttle inside many real stops), and a re-application must happen within one stop (a release or the
throttle ends it). The brake peak drift compares firm stops only: the research's literal "stops 8-10 against stops
1-3 at a similar entry speed" mixed light lifts with full stops and swung by +-30 points on these races from
driving alone.

## Limits

- The research covers the GT DD Pro on PS5 (and the PC/PS5 F1 column). GT7 has no post-1.71 balanced or
  competitive source, so those styles fall back to Official and say so. Every GT7 preset before update 1.71
  (2026-08-20) is stale; GT7 Realism uses one stale 8 Nm setup.
- F1 Comfort and GT7 Comfort at 5 Nm have no source: every value is derived and marked.
- Open questions (FFS after the Boost Kit, FUL on PS5, the v1.25 bug on PS5, F1 25 wheel-preset defaults...) are
  listed under **Verify on your hardware**.
- Rig-check thresholds are heuristics calibrated on seven real races with one rig. Trust the comparisons more than
  the absolute pass/warn. The load-cell checks have not seen a load-cell session yet.
