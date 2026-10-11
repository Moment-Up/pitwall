# GT DD Pro on PS5: button-by-button walkthrough

Research date: 2026-10-11. Rig: Fanatec Gran Turismo DD Pro base (5 Nm now, Boost Kit 180 coming) with its bundled
"Steering Wheel for Gran Turismo DD Pro", CSL Pedals (Load Cell Kit coming), PS5. This file explains *how* to set
the values in `rig-setup-sources.md` §6. It does not choose values. The machine-readable copy is
`gt-dd-pro-ps5-walkthrough.json`.

**Evidence labels**

| Label | Meaning |
|---|---|
| **[V]** | Read in an official Fanatec, EA or Polyphony source: manual text or figure, help article, product page, or a caption in Fanatec's own video |
| **[A]** | Seen in Fanatec's own video frames, which are only 320×180 pixels. It looks right, but small text can't be read with certainty |
| **[U]** | Owner report, community guide, or not confirmed |
| **[D]** | Worked out by us from verified facts |

Source tags such as `M p21` are listed in §12. `M pN` = printed page N of the GT DD Pro manual; the PDF page is N+4.

**Verifier pass (2026-10-11).** Every step was re-checked against the manual PDF, the Fanatec help-centre JSON, the
Explorer manuals, the quick-guide poster, FAQ36 and fresh frames of Fanatec's 2025 video. Changed text is tagged
**[fix]** (corrected) or **[new]** (added). The full list is in §14.

---

## 0. Cheat card (the five things that matter)

1. **The screen is on the steering wheel**, not the base: a small white screen at the top centre of the wheel, above
   the round GT logo. **[V]** PROD; M p19
2. **Tuning Menu button** = the **tiny round button just LEFT of that screen**. It is much smaller than the other
   buttons. **[V]** M p19 figure; GTP22
3. **Menu stick** = the stick at the **lower LEFT** of the wheel face, under the blue-ringed stick. Fanatec calls it
   "D-Pad" (manual) or "D-Stick" (2025 video). The four sticks with **coloured rings are not** the menu stick. **[V]** M p19; VID25
4. **LEFT / RIGHT = move between settings. UP / DOWN = change the value.** On the first item (the profile) UP/DOWN
   chooses the profile. There is no OK button: **every change is saved at once.** **[V]** VID25 ~10:20-11:40; FAQ36.
   **[fix]** Which of LEFT/RIGHT is "next" is not confirmed; if you go the wrong way, tilt the other way.
5. **Advanced menu:** short-press the Tuning button to open the menu, then **press and hold it for 3-4 s and let go when
   the screen changes.** **Never hold past 5 s**: a longer hold erases your custom profiles. **[V]** M p21; FAQ36; VID25
   **[fix]** (was "never keep holding to ~10 s"; one Fanatec caption can be read as 6 s in total, see §4)
   **[new]** Then pick `SET 1` on the profile item: the factory profile `AUTO` (A SET) ignores your changes (§5).

Base mode: the **power button is on the right-hand side of the base**. Its ring must glow **dark blue** (PlayStation)
for PS5. **[V]** M p15-16; H-MODES

---

## 1. Know your controls

Steering wheel face, as you sit in the seat (drawn from manual p19 and Fanatec's 2025 video; not to scale):

```
                        ~~~~ curved light strip (RevLEDs) ~~~~
                 [L2 tab]  (T)[ SCREEN ][R2 tab]
                 (small btn)            (small btn ≡)
   (green-ring stick)                         (red-ring stick)
   (blue-ring stick)        ( GT logo )       (yellow-ring stick)
   [MENU STICK]                                     △
   lower left                                     □   ○
                                                    ✕
                 [L3 tab]   (PS button)   [R3 tab]
 (T) = Tuning Menu button (tiny, just left of the screen)
```
**[new]** The light strip, the L3/R3 tabs and the PS button are added from Fanatec's 2025 video frames **[A]** and the
product page ("Diffused RevLED strip") **[V]**.

| # | What | Where exactly | How you know you have the right one | Source | Status |
|---|---|---|---|---|---|
| 1 | **Screen** | Small white OLED window, top centre of the steering wheel, directly above the GT logo and just below the curved light strip. **The base has no screen.** | It shows menu text when you short-press the Tuning button. **[new]** With the menu closed it may be blank or show game data such as the gear ("telemetry output (where supported)") | PROD ("White OLED display for Tuning Menu access"); M p19 ("shown on the display of the connected steering wheel"); GTP22; VID25 frames 10:20-10:30 | **[V]** |
| 2 | **Tuning Menu button** | Tiny round button immediately **left of the screen**, between the screen and the "L2" tab | One short press: the screen turns on and shows a menu item | M p19 figure "Tuning Menu button"; M p17, EXP K and QG figures; GTP22 ("small black button just to the left of the LCD screen"); VID25 ~10:20, 11:00, 11:45 (finger on it) | **[V]** for position. **Printed label/symbol: not confirmed**. Fanatec's drawings use a "three sliders" icon for "Enter/Exit Tuning Menu", but no source shows that icon on the button itself |
| 3 | **Menu stick** ("D-Pad" / "D-Stick" / "5-way directional stick for menu navigation") | Lower **left** of the wheel face, below the blue-ringed stick | With the menu open, a tilt left or right changes what the screen shows | M p19 figure "D-Pad"; EXP M step 2; PROD; FAQ36 ("directional stick"); VID25 ~10:20 caption "navigate with the D-Stick" | **[V]**. "No coloured ring" is **[A]** |
| 4 | **The four coloured-ring sticks** (green and blue on the left, red and yellow on the right) | Upper and middle of each side | They are game buttons ("Four additional 5-way directional sticks"). **Do not use them for the menu** | PROD; VID25 frames | **[V]** for what they are. **[fix]** The ring colours are **[A]** (video frames only; the product page names no colours) |
| 5 | **PlayStation face buttons** | Lower right: △ top, □ left, ○ right, ✕ bottom | Needed only for button combinations (§10) | VID25 frames | **[A]** |
| 6 | **Two small round hub buttons** | Top of the hub: one under the L2 tab (left), one under the R2 tab (right). The right one shows a three-line **≡** symbol | Used only in button combinations (§2 step 6, §10) | M p16, p17 figures; VID25 frames | **[A]**. **Names not confirmed**: the shapes look like the PlayStation CREATE and OPTIONS buttons, but Fanatec's manual does not name them |
| 7 | **Power button** | On the **right-hand side of the wheel base**, towards the front (wheel end), marked with the ⏻ symbol. Its ring lights up in the mode colour | It glows after power-on | M p15 (5.2); EXP H; QG panel I drawing (front corner) **[A]**; VID25 06:15-06:40 | **[V]** |

**Directions (the part the manual leaves out)** **[V]** VID25 captions (re-read from fresh frames, 10:30-11:40):
- In a custom profile: "switch settings with **left or right** and adjust the value with **up or down**".
- On the profile item: "**Up and down** switches between different setup profiles".
- In A SET (Auto): "Right or left ... switches the setting. Up or down **shows** the value set by the game".

GTPlanet (2022) says the same. It adds that moving **up** from "AUTO" reaches "SET 1", then "SET 2" **[U]**. That suggests
UP steps forward or increases, but **which way is "next" and whether UP raises a value is not confirmed**. Watch the
number on the screen.

**What the screen shows [new]** **[A]** (fresh 320×180 frames of VID25, 10:30-11:45): on the profile item it shows one
word, for example `AUTO`, `C SET` or `SET 4`. On a setting it shows the **value in big digits** (for example `1080`,
`2520`), a **small label in the top corner** (too small to read in the frames; probably the item name such as `SEN`),
and for numbers a **bar along the bottom**. So: big number = value, small text = which setting you are on.

---

## 2. Power on and check the operating mode

0. **[new] Put the steering wheel on the base.** On the current QR2 Lite version: press the wheel firmly onto the base's
   quick release. The top of the base-side part is more rounded than the bottom, so it only fits one way. To take the
   wheel off, pull the sleeve on the wheel's quick release while pulling the wheel towards you. *Check:* the wheel does
   not wobble or come off when you pull it gently. **[V]** EXP E; VID25 05:35-05:55, 11:55 captions. Older bundles came with
   **QR1 Lite** (M p4); if yours has that, follow the drawings on M p10 instead **[U]** (which version you have is not
   known).
1. **Plug everything in before power-on**: wheel on the quick release, pedals into the base, USB to the PS5.
   Devices connected later may not be detected. *Check:* cables seated. **[V]** M p6 (4.1 ATTENTION)
   - **[new]** Pedals: the RJ12 cable goes from the throttle module's port **"Wheel Base / Load Cell"** to the base port
     **"Pedals"** **[V]** M p2, p11, p13.
   - **[new]** Power: plug the power brick into the base **before** plugging it into the wall **[V]** M p1.
   - USB: use the supplied "USB Type-A to Type-C" cable **[V]** M p5, M p6. The USB-A end goes into the PS5 and the
     USB-C end into the base **[D]**; which PS5 port is not specified.
2. **Press the power button for about 1 second.** The base runs a start-up calibration and the wheel moves on its own.
   **Keep your hands off the wheel** until it stops. *Check:* the button ring lights and the wheel settles.
   **[V]** M p15 (5.2); VID25 06:05-06:10 caption **[fix]** (timestamp)
3. **Wait until start-up has finished** before you touch the mode. Mode presses during start-up may be ignored.
   **[V]** H-STARTUP
4. **Read the ring colour** around the power button:

   | Colour | Mode | Use on this rig |
   |---|---|---|
   | **Dark blue** | PlayStation (native) | **Yes: PS5, F1 25, GT7** |
   | Purple | PS4 compatibility: the base pretends to be an old CSL Elite Wheel Base+ PS4 | Only for old games such as F1 2020 |
   | Red | PC (native) | Windows PC, firmware updates |
   | Yellow | PC compatibility | Old PC games |

   **[V]** M p16 (5.3); EXP I; H-MODES; H-BLUE; VID25 06:15-06:35. Manual and video say "blue". The help centre says
   "DARK BLUE" because the ClubSport DD+ also has a light-blue mode. The GT DD Pro has no light-blue mode. Green (Xbox)
   needs an Xbox wheel, so you will not see it with this wheel (H-MODES).
5. **If it is not dark blue, tap the power button** (short press, under 1 s) **once**. Wait for the colour to change,
   then repeat until it is dark blue. With this wheel there are four colours, so at most three taps are needed **[D]**.
   - Do **not** hold it: **3 s = base turns off** (M p15).
   - Holding 8 s while the base is off starts bootloader mode, which is for firmware rescue only (M p29). Avoid it.

   *Check:* the ring is dark blue. **[V]** M p15-16; VID25 06:15 ("press the power button shortly while the base is
   on"). The colour order is **not confirmed**. **[new]** The video shows the colours in the order blue → red → purple
   → yellow **[A]**, which may be the tap order.
6. *Alternative (not needed):* manual p16 also shows a wheel combination for changing modes: press the small round
   button under the **L2** tab and **△** at the same time. The combination exists **[V]** (M p16; EXP I; QG panel F);
   the two buttons are identified from figure positions only **[A]**.
7. **The mode is remembered** after power off and on, **except after a firmware update**. Check the colour after any
   update. **[V]** M p16 NOTE

---

## 3. Open the menu, move, change a value, close

1. **Short-press the Tuning button.** The screen lights up. **[fix]** In Fanatec's video it opens on the **profile item**
   (`AUTO` at 10:30) **[A]**; no Fanatec text says the menu always opens there. If you see a number instead of a profile
   name, tilt LEFT or RIGHT until a profile name appears. Profile names: Fanatec's text says `A SET`, `C SET`,
   `1 SET`…`5 SET`; the OLED in the 2025 video shows `AUTO`, `C SET` and `SET 4` **[A]** (owners also report `SET 1`…,
   GTP22 **[U]**). *Check:* a profile name is shown. **[V]** M p20-21; FAQ36 for the profile names in text.
2. **Tilt the menu stick LEFT or RIGHT** to move to another setting. *Check:* the value and the small label change.
   **[V]** VID25 ("Left and right switches between the available settings"). **[fix]** The earlier text said RIGHT = next
   as if verified; which way is "next" is **[U]**.
3. **Tilt UP or DOWN** to change the value. *Check:* the big number changes and the bar under it grows or shrinks **[A]**.
   **[V]** VID25 ("Up and down adjusts the values"); FAQ36
4. **There is nothing to confirm.** The new value is used and saved at once, in the base's own memory. It survives power
   off, and the PS5 doesn't need to be involved. **[V]** FAQ36 ("The value is saved and will be used from this moment
   on"); EXP-TM ("stores 5 custom presets ... in the Base's internal memory")
5. **Short-press the Tuning button again to close the menu.** *Check:* the menu text disappears. **[V]** VID25 11:45
   ("To exit the Tuning Menu, press the Tuning Menu button"); QG panel H step 3; EXP M step 3
6. **[new] When to do it:** the menu works at any time, even while a game is running (EXP-TM: "accessed at any time ...
   even on consoles") **[V]**. Do it while stopped or paused, not while driving.

---

## 4. Standard or Advanced? How to tell, how to switch, how not to erase everything

**How to tell which menu you are in** **[V]** M p20-21; EXP M; FAQ36

1. Open the menu and stay on the first item. Tilt UP/DOWN through the profiles:
   - **Standard** offers only two: Auto and Custom (`A SET` and `C SET`; on the OLED `AUTO` and `C SET` **[A]**).
   - **Advanced** offers Auto plus five custom slots (`A SET`, `1 SET`…`5 SET`; on the OLED `SET 1`…`SET 5` **[A]**).
   - **[new]** Easiest test: if you can find any profile with a number in it, you are in Advanced.
2. Or tilt LEFT/RIGHT through the items:
   - **Standard** shows only `SEN`, `FF`, `NDP`, plus `BRF` once a load-cell brake is fitted. `SHO` and `MPS` appear
     only with hardware that supports them. Fanatec's video calls these "the three core parameters".
   - **Advanced** also shows **`FFS`, `NFR`, `NIN`, `INT`, `FEI`, `FOR`, `SPR`, `DPR`**. **[fix]** `FUL` (FullForce)
     exists on the GT DD Pro since the June 2026 firmware **[V]** (PROD note; H-TORQUE; FF-BLOG), but which menu shows it
     and where is **[U]**.
   - If you can see `INT` or `FEI`, you are in Advanced. Because the item label is small on the OLED (§1), the profile
     test in step 1 is easier.
3. Another clue: in Standard, `NDP` stops at 25 and `FF` stops at 005. In Advanced both go down to `OFF`. **[V]** M p22-23

**How to switch** (the same action toggles both ways)

1. **Short-press** the Tuning button so the menu is open. **[V]** FAQ36 ("press the tuning menu button to open the
   tuning menu first, then press it again and hold it"); VID25 11:00 ("While in the Tuning Menu..."); D431 ("while
   being in the Tuning Menu"); GTP22. The manual and H-ADV just say "press and hold" without this step.
2. **Press and hold** the Tuning button. Count slowly: "one-thousand-one, one-thousand-two, one-thousand-three…".
   Fanatec gives two hold times: **3 s** (FAQ36, VID25 11:00, D431) and **4 s** (M p21, H-ADV, EXP M).
   **[V]** (conflict noted)
3. **Watch the screen and let go as soon as it changes.** A 2022 GTPlanet guide says the screen confirms with
   "MOD CHANGED TO ADVANCED" while you are still holding. The exact text on current firmware is **[U]**. *Check:* the
   profile item now offers `SET 1`…`SET 5` (Advanced) or only `AUTO`/`C SET` (Standard).
4. **Danger: do not keep holding.** The manual and H-ADV say an **additional 6 s** (≈10 s in total) **resets every
   custom profile to factory values and returns you to Standard**. **[V]** M p21; H-ADV; EXP M.
   **[fix]** EXP M's picture caption reads "Hold the Tuning Menu Button for 6 seconds to perform a reset", which can be
   read as 6 s in total. Do not rely on having 10 s.
   - **Avoid it:** let go by **5 s at the latest**.
   - If nothing happened, let go, wait a moment, and try again. Do not "hold a bit longer".
   - **[new]** Before your first switch, write your slot values down (pitwall Setup tab) so a reset costs only re-typing.
5. Whether your slot values survive a normal Standard↔Advanced toggle (without the long reset) is **not confirmed**.
   Only the long hold is documented as erasing them. **[U]**

---

## 5. Choose your custom slot (do this before changing anything)

1. Be in the **Advanced** menu (§4).
2. Open the menu and go to the profile item (§3 step 1). **Tilt UP/DOWN until it shows `1 SET`** (on the OLED most
   likely `SET 1` **[A]**). Suggested plan: 1 SET = F1 25, 2 SET = GT7 custom, 3 SET = experiments
   (`rig-setup-sources.md` §6.0) **[D]**. *Check:* the name is shown. **[V]** VID25 11:20 ("Up and down switches between
   different setup profiles")
3. **Selecting a profile activates it.** Close the menu with that profile showing. *Check:* re-open the menu; the first
   item still shows your slot. **[V]** FAQ36 ("Select the Custom setup to activate it"). The re-open check is **[D]**.
4. **What `A SET` (Auto Setup) means:**
   - The game controls the values. You can **view but not change** them. When you try to change one, the screen shows
     the game's value. **[V]** M p20; driver 431 notes
   - When a game is actively using it, Fanatec's text says the screen shows `A.SET.` (with dots). **[V]** M p20.
     **[fix]** How that looks on this OLED (which shows `AUTO` for the profile in the 2025 video) is **[U]**.
   - **[new]** If no game is sending values, A SET simply uses the factory defaults (SEN AUTO, FF 100, NDP 50 …).
     **[V]** M p20; FAQ36
   - **Auto Setup is the factory default** on the GT DD Pro. A new or reset wheel therefore starts in a profile where
     your changes do nothing. **[V]** D431 ("factory default for ... GT DDPRO"); VID25 shows `AUTO` on first opening **[A]**
   - A GT DD Pro owner on PS5 wrote that the settings on the wheel "say there locked" (Fanatec forum, 2022). After he
     switched to Advanced they were **still** locked, because he was still on Auto Setup. The exact on-screen word
     ("LOCKED"?) is **not confirmed**. **[U]** FORUM-LOCK
   - **[new] Switching to Advanced may leave you on A SET.** Always pick `1 SET` afterwards (this step). **[U]**
     FORUM-LOCK (one owner's experience); no Fanatec text says which profile is active after a switch.
5. **Changes save immediately and stay in the base** (§3 step 4). Each of 1 SET…5 SET keeps its own values.
   **[V]** EXP-TM; FAQ36

---

## 6. Change each value (the items in our recommendations)

**Procedure:**
1. Select your slot (§5).
2. Tilt **RIGHT** once (or LEFT, see §3) and read the small label in the corner of the screen. **[fix]** The label is
   small; the big digits are the value (§1, "What the screen shows") **[A]**.
3. Tilt **UP/DOWN** until the big number shows the target.
4. Move to the next item and repeat. Do this for every item on your sheet.
5. **[fix]** To pick `OFF`: the manual lists OFF just before the lowest number (`OFF 001 … 100`), so it is probably one
   step **below** the lowest number **[D]**, not verified. (For BLI the manual lists OFF after 100.)
6. Close the menu. Re-open it and re-read two items to be sure they stuck.

**[V]** VID25; FAQ36. The order in which items appear is **not confirmed**. The manual describes them in the order SEN,
FF, FFS, NDP, NFR, NIN, INT, FEI, FOR/SPR/DPR, BLI, SHO, MPS, AP, BRF.

**[new] SEN, the first value you will change.** SEN starts at `AUTO`. The manual lists AUTO **after** the highest
number (`90 … 2520 AUTO`), so one step from AUTO probably lands on 2520 (Advanced) or 1080 (Standard), and you then
step down to 360 **[D]**. If you land on 90 instead, go the other way. The step size, and whether holding the stick
scrolls faster, are **[U]**. Fanatec's video shows `2520` on screen in Advanced (11:25) **[A]**.

| Item | Name in the manual (other spellings seen) | Menu | What the value looks like / range | Factory default | Fanatec F1 25 value (PC/PS5 column, CSL DD/GT DD) | Source |
|---|---|---|---|---|---|---|
| **SEN** Sensitivity (degrees of rotation, lock to lock) | `SEN` | Both | Degrees: Std **180…1080**, Adv **90…2520**, or **`AUTO`**. Step size not confirmed | `AUTO` | **360** (set by hand; see §11) | M p22; H-TM |
| **FF** Force feedback strength (% of motor) | `FF` (Fanatec web pages and the PC App: **`FFB`**) | Both | Std **005…100**; Adv **`OFF`, 001…100** | 100 | **100** | M p22; FAN-F125; H-6NM image |
| **FFS** Force feedback scaling | `FFS` | Adv | **`LIN` / `PEA`** (App, help and Fanatec F1 page: **`LINEAR` / `PEAK`**) | `PEA` | **PEA/PEAK**. rig-setup-sources §3.1 says that with the Boost Kit on base FW ≥ 1.9.0.2 this item is no longer offered. **[fix]** Fanatec help 50420340753297 (updated 2026-09-24) still tells 8 Nm owners to set FFS to PEAK, so this is a conflict: **if FFS is shown, set PEA** | M p23; D431 ("PEAK" / "LINEAR"); H-6NM |
| **NDP** Natural damper | `NDP` | Both | Std **25…100**; Adv **`OFF`, 01…100** | 50 | **35** | M p23 |
| **NFR** Natural friction | `NFR` | Adv | **`OFF`, 001…100** | `OFF` | **OFF** | M p24 |
| **NIN** Natural inertia | `NIN` | Adv | **`OFF`, 001…100** | `OFF` | **OFF** | M p24 |
| **INT** FFB interpolation (smoothing filter) | `INT` | Adv | **`OFF`, 01…20** | **11** | **3** | M p24 |
| **FEI** Force effect intensity | `FEI` | Adv | **000…100** (000 smoothest, 100 sharpest). Step 10 on older bases per FAQ36 **[U]** for the GT DD Pro | 100 | **100** (90 or 80 if harsh) | M p24; FAQ36 |
| **FOR** Force effect | `FOR` | Adv | **`OFF`, 010…120** | 100 | **100** | M p25 |
| **SPR** Spring effect | `SPR` | Adv | **`OFF`, 010…120**. Low or OFF stops the base re-centring the wheel after a centre calibration | 100 | **100** | M p25 |
| **DPR** Damper effect | `DPR` | Adv | **`OFF`, 010…120** | 100 | **100** | M p25 |
| **BRF** Brake force (Load Cell Kit only) | `BRF` | Both, **only when a load-cell brake is detected** | **`Lo`, 010…100, `Hi`** (Lo = least force for 100% brake) | 050 | Style-dependent (rig-setup-sources §6.3) | M p28; EXP M; LCK 4.5 |
| FUL FullForce (firmware from June 2026) | `FUL` | Menu and position **[U]** | `OFF`…100 per H-TM, but H-TM still lists FUL as "ONLY for Podium DD, CS DD and CS DD+" (out of date) **[U]** for the GT DD Pro | 100 **[U]** | Leave at default for F1 | **[fix]** FullForce on the GT DD Pro is **[V]**: PROD special note; H-TORQUE; FF-BLOG (2026-06-16). Known issue: weaker than intended (APP1613) |
| SHO, MPS, AP, BLI | — | — | Ignore. MPS/AP are not supported by the bundled wheel; BLI needs ClubSport V3 pedals | — | — | M p25-27 |

How numbers appear on the screen: the manual writes them with leading zeros (`050`, `001`, `010`; `01` for NDP and INT).
Fanatec's 2025 video shows the OLED with a value plus a bar **[A]**. **Exact formatting is not confirmed**: leading
zeros, a `%` or `°` sign, and whether the label reads `FF` or `FFB`. Treat `FF`=`FFB` and `PEA`=`PEAK` as the same
thing.

Physical check for SEN **[V]/[D]**: the manual says SEN 90 lets the wheel turn only 45° each way (M p22). So with
**SEN 360** the base should stop the wheel at **about half a turn (180°) each way** from centre.

---

## 7. CSL Pedals (stock, Hall sensors): routine after every power-on

1. Pedals connect to the base by RJ12. Plug them in **before** power-on. **[V]** M p6, p13
2. **After every power-on, before driving:**
   - Press the **throttle** all the way down, then let it come all the way back.
   - Press the **brake** as far as it goes, then let it all the way back.
   - Do the clutch too if one is fitted.

   **[V]** M p30 ("every pedal lever must initially be pushed to the maximum position and then fully released")
3. *Check:* in pitwall's **Live** tab (F1 25 UDP telemetry on, car on track), the brake bar is **0 at rest** and
   **100 at full press**, and the throttle bar behaves the same. **[D]** (pitwall `LiveView` throttle/brake bars). Whether
   F1 25's own Calibration screen shows live input bars is **[U]**.
4. Stock CSL Pedals have **no BRF**. The brake is position-based. **[V]** M p28 ("Not supported by the included CSL Pedals")

---

## 8. After the Load Cell Kit arrives: where BRF appears

1. **Update the base firmware first** (Windows PC, base in RED mode). Then return to DARK BLUE. **[V]** LCK 4.4; M p15 (5.1)
   **[new]** This needs a **Windows** PC with the Fanatec App; a Mac cannot do it (M p3, p15: "A Windows PC is
   required"). After any firmware update, expect "CAL" on the wheel (§10) and re-check the mode colour (§2 step 7).
2. **Wire it as LCK 4.4 says.** Check the printed port labels as you go. **[V]** LCK 4.4
   - Short RJ12 cable (from the kit): accelerator module port **"Wheel Base / Load Cell"** to load-cell module port
     **"Load Cell"**.
   - Load-cell module to the **wheel base**, using the long RJ12 cable that came with the CSL Pedals.
   - The old brake can go to the **"Clutch"** port.
   - **Never connect RJ12 and USB at the same time.**
3. Power on (§2), then do the **press-fully-and-release routine for every pedal** (LCK 6: needed when Manual Mode is not
   set). **[V]** LCK 6. **[fix]** That Manual Mode is never set on a PS5-only rig is **[D]**: it can only be turned on
   from the PC software (LCK 4.5).
4. Open the menu, choose your slot, and tilt LEFT/RIGHT through the items until **`BRF`** appears. It shows in **both
   Standard and Advanced**, but **only when the load-cell brake is detected**. If you never see BRF, check the wiring
   and firmware (LCK 6). **[V]** M p21; EXP M
5. UP/DOWN sets **`Lo`, 010…100, `Hi`**; default **050**. Lower = less force needed for 100% brake. *Check:* pitwall's
   Live brake bar reaches 100 at the firm press you chose. **[V]** M p28 (range); check **[D]**
6. Re-check BRF after a base restart or firmware update. Earlier firmware had BRF-reset bugs (rig-setup-sources §3.4). **[V]**
7. Note: manual p28 says BRF is available when the pedals are connected "to a wheel base via RJ12 and to a PC via USB",
   while LCK 4.4 says never connect both. **[fix]** The same "RJ12 and ... USB" sentence is repeated in the online GT DD
   Pro manual (EXP M, BRF), H-TM and LCK 4.5; only EXP M's Standard-menu note says simply "when a pedal set featuring a
   load cell brake is connected". LCK 4.5 adds that BRF "can be accessed via the wheel base Tuning Menu as well".
   **On PS5 use RJ12 only.** **[V]** (conflict noted)

---

## 9. In the games

### 9.1 F1 25 (PS5)

1. From the **main menu or the pause menu**: **Settings → Controls, Vibration & Force Feedback**.
   **[U]** SRS25 (2025-05-26), BK25 (2025-05-28; path "Settings > Controls, Vibration & Force Feedback > [wheel] >
   Calibration"). EA's F1 22 PS5 pages list the same top-level item (EA-F122 "Controls"), but EA publishes no F1 25 page.
2. **Select your wheel's entry** in the device list, not the Wireless Controller. The **exact name** F1 25 shows for the
   GT DD Pro is **not confirmed**. **[U]** (EA's F1 22 page calls these entries "Wireless Controller Preset 1/2" and
   puts Calibration and Vibration & Force Feedback inside them.)
3. **Calibration** (inside the wheel entry): **Steering / Throttle / Brake Deadzone, Linearity, Saturation**, each
   0-100, default 0 in EA's F1 22 docs **[V]** EA-F122 calibration. **[fix]** **Steering Rate** is **not** in EA's F1 22
   list; it appears only in BK25's F1 25 list **[U]**. F1 25 ranges are **[U]**.
4. **Vibration & Force Feedback** (inside the wheel entry). **[fix]** The two sources differ:
   - EA, F1 22 **[V]**: Vibration & Force Feedback (On/Off), Vibration & Force Feedback Strength, On Track Effects,
     Rumble Strip Effects, Off Track Effects, Wheel Damper, Understeer Enhance, **Maximum Wheel Rotation (F1 & F2)**
     (default 360) and **Maximum Wheel Rotation (Super Cars)** (default 900).
   - BK25, F1 25 **[U]**: the same first six, plus **Pit Stop Effects**, and a single **Maximum Wheel Rotation**. No
     Understeer Enhance listed. BK25 writes the sub-menu as "Vibration & Feedback".

   So in F1 25 expect "Pit Stop Effects", and possibly more than one rotation item: set the one for F1 cars.
5. **Set Maximum Wheel Rotation to the same number as SEN on the wheel** (for example 360 and 360).
   *Check:* turn the real wheel to 90°. The in-game wheel should also be at 90°. If not, Fanatec's fix is to change SEN
   until they match. **[V]** H-ANGLE. H-ANGLE also warns that some games' wheel animation is not realistic, so a small
   mismatch can be the game, not your settings.
6. If menu items seem to be missing, F1 25 may be showing a reduced set. Look for a settings-filter toggle (set it to
   "Expert"). **[U]** (rig-setup-sources §3.5; not confirmed in an EA source)
7. Do not rely on SEN `AUTO` in F1. Fanatec's App 1.6.1.3 known-issues list says to set SEN manually for F1 games. That
   note describes a PC symptom; PS5 behaviour is **[U]**. **[V]** APP1613
8. *Tip* **[U]**: the DualSense controller is usually the easiest way to move through F1 25's menus. The wheel's
   PlayStation buttons (✕ / ○) may also work.

### 9.2 GT7 (PS5)

1. Before a race, the **Quick Menu** appears. Choose **Settings → Controller Settings**. **[V]** GT7M (`drivingoption/01`,
   `/04`)
2. Under **Steering Force Feedback** you find **Force Feedback Max. Torque** and **Force Feedback Sensitivity**.
   **[V]** GT7M `/04`. The official manual gives **no ranges**; owners use 1-10 **[U]**.
3. On the wheel, GT7 can use **A SET**: the game pushes the values, which you can read but not change (§5). For a custom
   GT7 feel use 2 SET. **[fix]** Source: Auto Setup in general is M p20 **[V]**; that GT7 uses it comes from
   rig-setup-sources §2 / §6.4 (GT7 1.71 notice), not from the manual.
4. Whether Controller Settings can also be reached while paused is **[U]**.
5. **[new] Known GT DD Pro issues in GT7** (APP1613, 2026-09-21) **[V]**: the base "can lose FFB in GT7 with the wheel
   spinning uncontrollably", and "SPR and DPR settings are not working in GT7 menu". If the wheel spins on its own, take
   your hands off and hold the power button 3 s to turn the base off (§11).

---

## 10. Centre calibration (when "CAL" flashes, or the wheel is off-centre)

1. "CAL" flashing on the wheel screen is normal after a base firmware update. **[V]** H-CAL; M p17
2. **Short-press the Tuning button** (open the menu). **[V]** M p17 step 1; QG panel G; VID25 08:40-08:45
3. **Hold the wheel dead straight.** **[V]** M p17 step 2
4. **Press together:** the small round button **under the R2 tab** (top-right of the hub, ≡ symbol) **and ✕** (bottom
   face button). The positions are **[V]** (highlighted in M p17, EXP K and QG panel G figures); the names ✕ and "≡" are
   **[A]** (video frames).
5. *Check:* **"CAL" disappears.** Then short-press the Tuning button to exit. **[V]** VID25 08:50-09:00 captions; M p17 step 4
6. If the wheel still won't return to centre, check that **SPR** is not low or OFF (M p25).

---

## 11. Common mistakes and how to recover

| # | Symptom | Cause | Fix | Source |
|---|---|---|---|---|
| 1 | Values won't change; the wheel "says locked" | You are in **A SET** (Auto Setup, `AUTO` on the screen), which is the factory default | Profile item → `C SET` (Standard) or `1 SET` (Advanced), then change values | M p20; D431; FORUM-LOCK **[V]/[U]** |
| 2 | Even custom profiles can't be changed; the menu seems frozen | Firmware fault (Fanatec "Tuning Menu is locked" article). **[fix]** H-LOCK only says "locked, and no adjustments can be made"; rule out A SET (#1, #16) first | Re-flash the base firmware from a **Windows** PC with the Fanatec App (base in RED), then back to DARK BLUE | H-LOCK **[V]** |
| 3 | Can't find INT, FEI, FOR, FFS…; NDP won't go below 25 | You are in the **Standard** menu | Switch to Advanced (§4) | M p21-23 **[V]** |
| 4 | Held the Tuning button too long: back in Standard, all your numbers back to default | Custom-profile **reset** (hold of 4 s + 6 s more per the manual; possibly sooner, see §4) | Switch to Advanced again, select 1 SET, and re-enter from your sheet (pitwall Setup tab). Defaults after a reset: SEN AUTO, FF 100, FFS PEA, NDP 50, NFR/NIN OFF, INT 11, FEI 100, FOR/SPR/DPR 100 | M p21-25 **[V]** |
| 5 | Pressing the coloured sticks does nothing in the menu | Wrong stick | Use the lower-left menu stick | M p19; PROD **[V]** |
| 6 | Wheel not recognised properly in a PS5 game | Base not in **dark blue** mode. Purple makes it pretend to be an older base; after a firmware update the mode can change | Tap the power button until dark blue (§2) | M p16; H-BLUE **[V]** |
| 7 | Base switched off while you tried to change mode | Held power for 3 s instead of tapping | Power on again. Slots are stored in the base | M p15; EXP-TM **[V]** |
| 8 | In-game wheel turns more or less than the real one | SEN ≠ Maximum Wheel Rotation, or SEN AUTO in F1 | Set SEN by hand to the same number as Maximum Wheel Rotation; do the 90° check | H-ANGLE; APP1613 **[V]** |
| 9 | "CAL" flashing / wheel off-centre after a firmware update | Centre calibration needed | §10 | H-CAL; M p17 **[V]** |
| 10 | Wheel doesn't spring back to centre | SPR low/OFF, or calibration | SPR 100; centre calibration | M p25 **[V]** |
| 11 | Brake/throttle don't reach 100%, or show input at rest (stock CSL) | Power-on routine skipped | Press each pedal fully and release (§7) | M p30 **[V]** |
| 12 | BRF not in the menu | Stock CSL Pedals (no BRF), or load cell not detected | Check wiring per LCK 4.4 and firmware | M p28; LCK 6 **[V]** |
| 13 | LC brake shows input with the foot off | Load-cell fault/drift | Firmware update and pedal reset on a PC | H-LCREST **[V]** |
| 14 | FFS missing after fitting the Boost Kit | Expected on base FW ≥ 1.9.0.2 per rig-setup-sources §3.1 | Nothing to fix. **[fix]** If FFS *is* still shown, set PEA (H-6NM, updated 2026-09-24, still describes it) | rig-setup-sources §3.1 (App 1.5.1.2 changelog, not re-read here) **[U]**; H-6NM **[V]** |
| 15 | F1 25: violent oscillation or lost FFB after a session change | F1 25 v1.25 game bug | Pause and power-cycle the base. Do not retune for it | rig-setup-sources §1 **[V]** |
| 16 | **[new]** You switched to Advanced and see more items, but values still won't change | Still on A SET / `AUTO` | Go to the profile item and pick `SET 1` | FORUM-LOCK **[U]** |
| 17 | **[new]** Pressing the Tuning button shows nothing on the screen | Bent pins in the quick release, or a faulty wheel/base | Check the pins inside the quick release; try another wheel if you have one; contact Fanatec | M p30 **[V]** |
| 18 | **[new]** The menu opens on a number, not a profile name | Menu did not open on the profile item | Tilt LEFT or RIGHT until a profile name (`AUTO`, `C SET`, `SET n`) appears | §3 step 1 **[D]** |
| 19 | **[new]** GT7: FFB lost and the wheel spins on its own | Known GT DD Pro issue in GT7 (APP1613) | Hands off the wheel; hold power 3 s to switch the base off; power on again | APP1613 **[V]**; recovery M p15 **[V]** |

---

## 12. Sources

| Tag | Source | Date | Notes |
|---|---|---|---|
| M | GT DD Pro manual (EN, Rev. 04), `www3.corsair.com/Files/Fanatec/Documentation/GT-DD-PRO-Manual-EN_01.pdf`. Pages used: 1-6, 10-11, 13, 15 (5.1-5.2), 16 (5.3 Modes), 17 (5.4 Centre Calibration), 19 (5.6 + rim figure), 20-21 (5.6.1), 22-28 (5.6.2-5.6.15), 29-30 (Troubleshooting) | PDF created 2022-09-26 | Read in full; figures rendered and inspected. Describes the QR1 Lite bundle; the rim and menu are the same as the QR2 Lite version (EXP) |
| QG | GT DD Pro Quick Guide poster, `fanatec.com/media/pdf/7c/12/4d/GT-DD-PRO-QG-SIE-EU-AU-US_Web_02.pdf`, page 2 panels E (ON & OFF), F (MODES), G (CENTER CALIBRATION), H (TUNING OPTIONS) | 2023-03-02 | Figures only; re-checked by the verifier |
| EXP | Fanatec Explorer online manual, GT DD Pro (QR2), `fanatec.com/us/en/explorer/products/racing-wheels-wheel-bases/gran-turismo-dd-pro/`, sections H, I, K, M | read 2026-10-11 | |
| EXP-TM | Fanatec Explorer "Unlocking Performance: The Fanatec Tuning Menu", `fanatec.com/us/en/explorer/products/steering-wheel/fanatec-tuning-menu-for-performance/` | read 2026-10-11 | Custom presets stored in the base |
| PROD | Fanatec GT DD Pro 5 Nm QR2L bundle page, `fanatec.com/eu/en/p/sim-racing-bundles/crd-9020007-eu/gran-turismo-dd-pro-5nm-qr2l-eu` | read 2026-10-11 | Wheel features list |
| VID25 | Fanatec, "Gran Turismo® DD Pro (QR2 Lite) - Video Guide", YouTube `28SrBLy-V_M` (linked from PROD) | 2025-05-15 | No narration. On-screen captions read from YouTube storyboard frames (320×180, one every 5 s). Verifier timestamps: 05:15-05:55 connections and wheel attach, 06:00-06:40 power/modes, 08:40-09:00 centre calibration, 09:50-11:45 Tuning Menu, 11:55 wheel detach |
| FAQ36 | Fanatec FAQ "What can be set in the Tuning Menu of my wheel?", `fanatec.com/uk/en/s/faq-what-can-be-set-wheel-tuning-menu` | legacy, multi-base | 3 s hold; "A SET" on 1" OLED; up/down adjusts; saved at once |
| H-TM | Fanatec help 43901256649233 (Tuning Menu parameters), via `help.fanatec.com/api/v2/help_center/en-us/articles/43901256649233.json` | updated 2026-08-31 | Ranges match the manual. Still says FUL is "ONLY for Podium DD, CS DD and CS DD+" (out of date for the GT DD Pro) |
| H-TORQUE | Fanatec help 48812077676177 "Wheel Base Torque FAQ" | updated 2026-07-31 | **[new]** "As of June 2026, FullForce is supported on ... Gran Turismo DD Pro" |
| FF-BLOG | Fanatec Explorer "FullForce arrives on CSL DD and GT DD Pro", `fanatec.com/eu/en/explorer/products/racing-wheels-wheel-bases/fullforce-arrives-on-csl-dd-and-gran-turismo-dd-pro/` | 2026-06-16 | **[new]** FullForce on GT DD Pro via the Fanatec App update |
| H-ADV | Fanatec help 30312152662033 "How do I change to the advanced tuning menu?" | updated 2026-09-01 | 4 s / +6 s reset |
| H-MODES | Fanatec help 49452636576017 "Wheel Base Compatibility Modes - A Primer" | 2026-08-03 | DARK BLUE = PS5 |
| H-BLUE | Fanatec help 45694330932369 "GT DD Pro - PlayStation Blue Mode vs. Purple Mode" | updated 2026-09-19 | |
| H-STARTUP | Fanatec help 51364321050897 "Changing modes after the wheel base has completed its initial startup process" | 2026-09-29 | |
| H-CAL | Fanatec help 51462672436113 '"CAL" = "Center Calibration" flashes continuously' | 2026-10-01 | |
| H-ANGLE | Fanatec help 30312080760593 "The steering wheel angle does not match…" | updated 2026-09-02 | 90° check |
| H-LOCK | Fanatec help 43900063462289 "The Tuning Menu is locked, and no adjustments can be made" | updated 2026-08-31 | Firmware re-flash |
| H-6NM | Fanatec help 30312080999825 / 50420340753297 (Boost Kit shows 6 Nm → FFS LINEAR vs PEAK) | updated 2026-09 | PC App labels `[FFB]`, `LINEAR` |
| H-LCREST | Fanatec help 50374918547985 (load-cell input at rest) | updated 2026-10-10 | |
| APP1613 | Fanatec App v1.6.1.3 release notes, help 51115557248017 | 2026-09-21 | "adjust the SEN manually for F1 games" |
| D431 | Fanatec driver 431 changelog, `forum.fanatec.com/discussion/comment/74347` (Wayback 2024-08-01 snapshot) | 2021-11-26 | Standard/Advanced, Auto Setup = factory default, 3 s hold, PEAK/LINEAR naming |
| FORUM-LOCK | Fanatec forum thread, `forum.fanatec.com/discussion/comment/77758` (Wayback 2024-08-01) | 2022-01-18/19 | Owner report: settings "locked" in Auto Setup |
| GTP22 | GTPlanet, J. Greer, "Gran Turismo 7's Latest Update Nerfed the Fanatec GT DD Pro: Here's How to Fix It" | 2022-05-29 | Button position, "MOD CHANGED TO ADVANCED", AUTO/SET 1 list, left/right + up/down |
| LCK | Fanatec Explorer CSL Pedals Load Cell Kit manual, `fanatec.com/us/en/explorer/products/pedals/csl-pedals-load-cell-kit/`, sections 4.4, 4.5, 6 | read 2026-10-11 | |
| FAN-F125 | Fanatec "F1 25 Fanatec Wheel Bases Recommended Settings", `fanatec.com/us/en/explorer/games/f1-2024/f1-25-fanatec-recommended-settings/` | read 2026-10-11 | Uses `FFB`, `PEAK` |
| EA-F122 | EA accessibility pages, F1 22 PS5: `ea.com/able/resources/f1-22/ps5/controls`, `/calibration`, `/vibration-force` | F1 22 | EA has no equivalent F1 25 page. No "Steering Rate" or "Pit Stop Effects"; has "Understeer Enhance" and two rotation items |
| BK25 | Brian Koponen, "Best F1 25 Settings for Thrustmaster T248", `briankoponen.com/f1-25-thrustmaster-t248-settings/` (menu path) | 2025-05-28 | Community; source of "Steering Rate" and "Pit Stop Effects" |
| SRS25 | SimRacingSetup, "F1 25 Controls Guide for PS5, Xbox & PC" | updated 2025-05-26 | Community |
| GT7M | Gran Turismo 7 official manual, `gran-turismo.com/gb/gt7/manual/drivingoption/01` and `/04` (text via `/gb/gt7/api/manual/?u=/drivingoption/04`) | read 2026-10-11 | |

---

## 13. What could not be verified (check on the real wheel)

1. **Printed label or symbol on the Tuning Menu button.** Its position is certain. No source shows legible text on it.
2. **Names of the two small round hub buttons** (under L2 and R2). They look like PlayStation CREATE and OPTIONS in
   Fanatec's video, at 320×180.
3. **Exact OLED wording:**
   - profile names: the 2025 video shows `AUTO`, `C SET`, `SET 4` **[A]**, while Fanatec's text says `A SET`,
     `1 SET`; FAQ36 says `A SET` on "1'' OLED" wheels
   - **[new]** whether the small label above the value is the three-letter name (`SEN`) or an icon
   - `FF` vs `FFB`, and `PEA`/`LIN` vs `PEAK`/`LINEAR`
   - leading zeros, `%`/`°` signs; the bar under numbers is seen in the video **[A]**
4. **Which of LEFT/RIGHT is "next", and whether UP increases a value.** GTPlanet implies UP steps forward.
5. **The order of items** in the menu, and where `BRF` and `FUL` sit in it. **[new]** Whether the menu always opens on
   the profile item.
6. **Hold time:** Fanatec says 3 s in some places and 4 s in others. Whether the confirmation text on current firmware
   is "MOD CHANGED TO ADVANCED", and what the screen shows during and after a reset. **[new]** Whether the reset comes
   6 s after the menu change (manual, H-ADV) or at 6 s in total (one EXP caption).
7. **Whether slot values survive a normal Standard↔Advanced toggle**, and **[new]** which profile is active after it.
8. **Whether the screen literally shows the word "LOCKED" in A SET.**
9. **Step sizes** (SEN, FEI), and whether holding the stick auto-repeats. **[new]** Where `AUTO` sits in the SEN list
   and where `OFF` sits in the other lists.
10. **The order of mode colours** when tapping the power button (video suggests blue → red → purple → yellow **[A]**).
11. **Display size.** "1-inch 128×64" appeared only in a search summary, not on a Fanatec page.
12. **BRF:** whether it is stored per slot or globally, and the manual's wording about "RJ12 and USB" (see §8 step 7).
13. **F1 25:**
    - the wheel entry's exact name
    - the "Vibration & Force Feedback" vs "Vibration & Feedback" sub-menu label
    - **[new]** whether "Steering Rate", "Pit Stop Effects", "Understeer Enhance" and one or two "Maximum Wheel
      Rotation" items exist (sources differ, §9.1)
    - the Settings Filter / Expert toggle
    - whether Calibration shows live input bars
    - slider ranges and defaults (EA documents F1 22 only)
    - whether SEN AUTO misbehaves on PS5
    - whether F1 25 uses A SET
14. **GT7:**
    - ranges of Max. Torque and Sensitivity
    - whether Controller Settings is reachable while paused
15. **Whether the DualSense or the wheel's ✕/○ are the easier way** to move through F1 25 menus.
16. **[new] Which quick release your base has** (QR1 Lite in the 2022 manual, QR2 Lite on current bundles); the
    wheel-attach step differs.
17. **[new] FUL on the GT DD Pro:** which menu shows it, its position and range. FullForce itself is confirmed.
18. **[new] FFS with the Boost Kit:** removed (rig-setup-sources §3.1) or still shown (H-6NM, 2026-09-24).

---

## 14. Verifier corrections (2026-10-11)

Primary sources re-read: manual PDF (all pages, figures rendered at 400 dpi), QG poster page 2, EXP (GT DD Pro QR2
and Load Cell Kit), EXP-TM, PROD, FAQ36, help JSON 43901256649233, 30312152662033, 49452636576017, 45694330932369,
51364321050897, 51462672436113, 30312080760593, 43900063462289, 30312080999825, 50420340753297, 50374918547985,
51115557248017, 48812077676177, D431 and FORUM-LOCK snapshots, GTP22, GT7M, EA-F122, BK25, FAN-F125, FF-BLOG, and the
VID25 storyboard frames for 05:15-12:00.

**Confirmed as written:** screen position; Tuning button position (tiny, left of the screen, right of the L2 tab);
menu stick lower left; LEFT/RIGHT = setting, UP/DOWN = value or profile; no confirm button, saved at once; exit with a
short press; 3 s vs 4 s conflict; +6 s reset back to Standard; Standard = A SET + C SET with SEN/FF/NDP (+BRF);
Advanced = A SET + 1-5 SET; every range and default in §6; Fanatec F1 25 values; power button side, 1 s on, 3 s off,
8 s bootloader; four LED colours; mode memory except after firmware updates; CAL combo positions; pedal power-on
routine; LCK wiring and "never RJ12 and USB together"; GT7 menu path.

**Corrected [fix]:**
1. §3 step 1: the menu opening on the profile item was marked [V]; no text says so. Now [A] with a recovery step.
2. §0, §3, §6: "RIGHT = next" was presented as verified. Only "left/right switches setting" is verified.
3. §6 step 5: "OFF is below the lowest number" was marked [V]; it is [D] from the manual's list order.
4. §0, §4: reset timing. One Fanatec caption can be read as 6 s total; the safe limit is now "never past 5 s".
5. §1: ring colours of the four sticks are [A], not [V].
6. FUL: FullForce on the GT DD Pro is confirmed by Fanatec (June 2026); H-TM still says otherwise.
7. §9.1: "Steering Rate" and "Pit Stop Effects" were credited to EA's F1 22 pages; they are not there (BK25 only).
   EA's F1 22 list also has "Understeer Enhance" and two rotation items.
8. §8 step 7: the "RJ12 and USB" wording is also in the online manual, H-TM and LCK, not only the PDF.
9. §8 step 3: "Manual Mode is never set on PS5" is [D], not [V].
10. §9.2 step 3: GT7 using A SET comes from rig-setup-sources, not the manual.
11. §6 FFS row, §11 #14: FFS removal with the Boost Kit conflicts with a help article updated 2026-09-24.
12. §5: how `A.SET.` looks on this OLED is unknown; the video shows `AUTO`.
13. VID25 timestamps corrected throughout.

**Added [new]:** wheel attach step; port names (base "Pedals", pedal "Wheel Base / Load Cell"); power brick order;
what the screen shows (big value, small label, bar); screen may show game data when the menu is closed; menu works
while a game runs; SEN-from-AUTO direction hint; A SET uses factory defaults when no game sends values; switching to
Advanced may leave you on A SET; Windows-only firmware updates; GT7 known issues; mistakes #16-19.
