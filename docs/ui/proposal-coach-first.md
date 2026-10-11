# Pitwall UI proposal C: "Coach-first"

Direction C of the UI upgrade. **Design only**: nothing under `web/src` or `src` was changed by this proposal.
Companion mockup: [`mockup-coach-first.html`](mockup-coach-first.html) (one self-contained file, no network; open
it on the iPad or any browser). Every number in the mockup is **sample data** and is labelled as such.

---

## 0. The idea

While the car is moving, the screen answers one question: **what do I do next?**

The hero is the **next corner** (official name from the track sheet), the **braking call** for it and the **one
coaching point** the engineer has for it. The only other big number is the **delta to the reference**. Sector and
lap times sit underneath in timing-screen colours. Car telemetry, traces, logs and settings move one tap away.

Off track, **Review** is built around learning: what to work on, what went well, and whether it is getting better,
for each driver in the family.

Five decisions:

1. **Four areas instead of ten tabs:** Drive, Review, Setup, Settings. A left rail on iPad landscape and a bottom tab
   bar on phones.
2. **Drive = the Coach screen.** Hero (next corner, cue, coaching point), big delta, sectors, a lap ribbon and a radio
   strip. The radio is merged into Drive, so nobody has to switch tabs mid-session. Today Live and Radio are separate
   tabs, and the iPad can only show one of them.
3. **Pre-session "who's in the seat" screen**, so laps land in the right profile. This matters with three drivers
   sharing one rig.
4. **Timing colours with one fixed meaning everywhere:** purple = your all-time best, green = your best this session,
   yellow = slower. Anything unknown shows as `-`.
5. **Review starts in plain language** ("Work on", "Went well", "Getting better?"). Distance traces are one level
   deeper, and how much the page shows depends on the driver's skill level.

---

## 1. Principles

| Principle | What it means in practice |
| --- | --- |
| Next action first | The next corner and its cue have the largest, fixed slot. Nothing moves around while driving. |
| Glance budget | A glance on a straight is about 0.5 s. Glance-critical items are at least 32 px (at least 20 arcmin at 70 cm, see 5.7). Each one keeps a fixed position and is shown with colour, shape and text together. |
| Truthful | The UI shows only what the server sent. Unknown or not reported = `-` in the muted colour. Negative numbers use a real minus `−` (U+2212), so they never look like "unknown". The UI never writes coaching advice. Coaching text comes from `analysis/coaching.py` and cue text from `coach/cues.py`, shown verbatim. Synthetic data is always badged. |
| Deterministic on track | Drive uses only the `/ws/live` snapshot and the radio store. The LLM never decides what is on screen, and Drive works fully with the LLM down. |
| One message, two channels | The coaching point on screen is the one the radio picked for this lap (B6). The screen and the earpiece never disagree. |
| Touch on a rig | Touch targets are at least 44 px everywhere and at least 56 px on Drive. No hover-only actions. The only long-press is push-to-talk. |
| Dark first, dim-room safe | Near-black background, off-white text and no large bright areas. The only exceptions are safety bands (flags). The light theme stays for daytime review. An optional Dim mode is available for night sessions. |
| Offline on the LAN | System fonts, inline SVG icons and no new runtime dependency (uPlot stays). |

---

## 2. What exists today

### 2.1 Views and where they go

| Today | Content | Moves to |
| --- | --- | --- |
| `#/live` `LiveView` | Connection strip; car (speed, gear, rpm, pedals, steering); timing (lap, delta, cue strip); map; tyres, fuel and ERS; 12 s input trace; coaching list; lap table | Drive > Coach (delta, timing, cue, coaching); Drive > Car (car, tyres, fuel, inputs); Drive > Track (map) |
| `#/radio` `RadioView` | Go live, push-to-talk, current message, log, voice settings | Drive (radio strip) and Drive > Radio; voice settings move to Settings > Radio & voice |
| `#/sessions` `SessionsView` | Session table, driver filter, re-assign a session | Review > Sessions |
| `#/sessions/:id` `SessionView` | Reference/comparison lap picker, map by corner, distance charts, corner table, observations, corner summary, report | Review > Session (Summary, Laps, Compare, Corners) |
| `#/engineer` `EngineerView` | Engineer chat (LLM or deterministic, grounded, with facts) | Review > Session > Ask (scoped) and Review > Ask |
| `#/setup` `SetupView` | Rig settings and rig check | Setup > Rig |
| (cloud task 8) `CarSetupView` | Car setups per track | Setup > Car setups |
| `#/connect` `ConnectView` | Game telemetry setup, live UDP senders, open on another device | Setup > Connect |
| `#/profiles` `ProfilesView` | Driver cards | Settings > Drivers (switching stays in the driver chip everywhere) |
| `#/settings` `SettingsView` | AI engineer (providers, keys, usage) | Settings > AI engineer |
| `#/status` `StatusView` | Health, captures, simulate/replay, capability matrix | Settings > System |

### 2.2 Problems in the current UI

- Live shows about 45 values in 8 panels at 12-40 px. The delta to the reference, the most useful number while
  driving, is 40 px, the same size as the running lap time. The braking cue is a 12 px strip.
- The iPad can only show one page. Live and Radio are separate tabs, so the driver chooses between seeing the delta
  and controlling the radio.
- 9 tabs plus the driver chip, connection status and theme button overflow on a phone. The nav scrolls sideways.
- Contrast: `button.primary` puts white text on orange (2.86:1, fails WCAG AA). `--faint` `#5b6574` on the background
  is 3.3:1 and is used for meaningful text.
- Purple means both "best lap" (`--best`) and "synthetic data" (`.badge.synthetic`). A timing screen needs purple to
  mean exactly one thing.
- Unknown values show as `—`, `--:--.---` or `–` depending on the formatter. The rule becomes one glyph: `-`.

---

## 3. Information architecture

### 3.1 Four areas

| Area | Question it answers | Pages (sub-nav) | Opens on |
| --- | --- | --- | --- |
| **Drive** | What do I do next? | Coach · Car · Track · Radio | Coach |
| **Review** | How did it go? What do I work on? Am I getting better? | Sessions · Coaching · Progress · Ask | Last page used; first time: Sessions |
| **Setup** | Are the game, the rig and the car set up right? | Connect · Rig · Car setups | Connect until the first packet ever arrives, then Rig |
| **Settings** | How does Pitwall behave, and for whom? | Drivers · Radio & voice · AI engineer · Display · System | Drivers |

These elements are always visible in the shell, in every area:

- **driver chip**: who is in the seat, one tap to switch (the existing `DriverChip`);
- **connection pill**: LIVE, STALE or IDLE;
- **SYNTHETIC badge** whenever the stream is synthetic;
- **mini radio bar** while the radio is live and the user is outside Drive. The radio store is module-level, so it
  keeps running on every page.

### 3.2 Routes

The app keeps the existing hash router, with no router dependency. The router becomes a small module that parses
`#/<area>/<page>/<params>`.

```
#/drive                 Coach (default)        #/review                      Sessions (list, master-detail on iPad)
#/drive/car             Car                    #/review/s/<id>               Session > Summary
#/drive/track           Track                  #/review/s/<id>/laps          Session > Laps
#/drive/radio           Radio                  #/review/s/<id>/compare?ref=<lapId>&lap=<lapId>&at=<m>
                                               #/review/s/<id>/corners       Session > Corners
#/setup/connect         Connect                #/review/s/<id>/ask           Session > Ask (engineer, scoped)
#/setup/rig             Rig (+ rig check)      #/review/coaching             Coaching plan (per driver)
#/setup/car             Car setups             #/review/progress             Progress (per driver / track / car)
                                               #/review/ask                  Engineer (any session)
#/settings/drivers  /radio  /ai  /display  /system
```

The old routes redirect, so bookmarks and Home Screen icons keep working. `docs/radio-setup.md` tells people to open
`#/radio`.

| Old | New |
| --- | --- |
| `#/live` | `#/drive` |
| `#/radio` | `#/drive/radio` |
| `#/sessions` | `#/review` |
| `#/sessions/<id>` | `#/review/s/<id>` |
| `#/engineer` | `#/review/ask` |
| `#/setup` | `#/setup/rig` |
| `#/connect` | `#/setup/connect` |
| `#/profiles` | `#/settings/drivers` |
| `#/settings` | `#/settings/ai` |
| `#/status` | `#/settings/system` |

The last page used in each area is remembered per device (localStorage, wrapped in try/catch, harmless when missing).

### 3.3 Devices and roles

| Device | Main use | Navigation |
| --- | --- | --- |
| iPad landscape on the rig (primary) | Drive; Review between runs | Left rail, 64 px |
| iPad portrait / on the sofa | Review, Settings | Left rail if ≥ 768 px wide, else bottom tab bar |
| Phone | "Pit wall" for whoever is watching (a parent following a child's session), quick Review | Bottom tab bar, 56 px + safe area |
| Mac browser | Everything; Review with wide charts | Left rail; content max 1680 px |

Breakpoints:

| Width | Layout |
| --- | --- |
| ≥ 1024 px, landscape | Full Drive grid (5.1) |
| 768-1023 px | Rail; Drive "compact landscape": delta sits beside the hero, ribbon labels hidden |
| < 768 px | Bottom tab bar; Drive portrait stack (5.6); sub-nav as horizontally scrolling pills |

---

## 4. Navigation pattern

**Rail (iPad / desktop).** 64 px wide, full height, `--surface-1` with a 1 px right hairline.

- Top: the Pitwall mark (the existing zig-zag glyph), 32 px.
- Four items, each 64 × 64: 24 px icon with an 11 px / 600 label under it. Active item: `--text` with a 3 px
  `--accent` bar on its left edge. Inactive items: `--text-2`.
- Bottom: connection dot (LIVE green, STALE amber, IDLE grey) and the seated driver's avatar (tap = driver menu).
- While on track (connection live and `pit_status == 0`), the rail fades to 55 % opacity. It stays fully tappable, and
  leaving Drive needs no confirmation.

**Tab bar (phone).** 56 px plus `env(safe-area-inset-bottom)`. The same four icons, labels always shown, and the
active item in `--accent`.

**Sub-nav.** A segmented control in the area header: 44 px high, pills, the active pill filled with `--surface-3` and
in `--text`. On Drive it sits at the right end of the status bar, to save a row.

**Area header (all areas except Drive).** 56 px: page title (22 px / 700), sub-nav, then area actions (for example
"Session report").

**Mac keyboard.** Keys 1-4 switch areas. Space = push-to-talk, on Drive and Drive > Radio only (as today).

**Deep links.** Compare links carry `ref`, `lap` and `at` (metres), so an engineer answer or a coaching card can open
the exact corner.

---

## 5. Drive (iPad landscape)

### 5.1 Viewport and grid

The reference viewport is **1180 × 796 CSS px**: an 11" iPad / iPad Air in landscape, running as a Home Screen web
app below the iPadOS status bar. 1 CSS px is about 0.19 mm on 11" and 13" iPads. The grid has fixed rows for the
strips and one flexible hero row. The same layout fits 1194 × 810 (iPad Pro 11"), 1366 × 1000 (13"; type scales with
`clamp()`) and 1133 × 720 (iPad mini, where the hero row shrinks to 240 px). The mockup measures exactly these boxes: hero 633 × 294, coach 633 × 120, delta 449 × 424, sectors 633 × 132, lap times 449 × 132, ribbon 1092 × 56, radio 1092 × 72.

```
 x=0   64                                                                                                  1180
 ┌─────┬──────────────────────────────────────────────────────────────────────────────────────────────────┐ y=0
 │     │ ● LIVE  Silverstone · Time trial · LAP 7          SYNTHETIC?   [Coach|Car|Track|Radio]  (JR) ▾ │ 48
 │  P  ├───────────────────────────────────────────────────────┬──────────────────────────────────────────┤
 │     │ NEXT CORNER · right            FOCUS         320 m    │ DELTA TO REFERENCE · PB 1:30.986         │
 │ ─── │  T15  Stowe                                           │                                          │
 │ Drv │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░ (approach bar)        │              −0.214                      │
 │ Rev │ ┌─────────────────────────────────────────────────┐   │          AHEAD  ◀━━━━━━━│                │ 294
 │ Set │ │ BRAKE   T15 brake                    in 250 m   │   │                                          │
 │ ⚙   │ └─────────────────────────────────────────────────┘   │  PROJECTED  1:30.772                     │
 │     ├───────────────────────────────────────────────────────┤                                          │
 │     │ [WORK ON · L6] T15: you're braking about 12 m earlier │                                          │ 120
 │     │ than your reference (lap 9), losing 0.11 s through... │                                          │
 │     ├─────────────────┬─────────────────┬───────────────────┼──────────────────────────────────────────┤
 │     │ S1         SB   │ S2          PB  │ S3      running   │ LAP   1:09.534                           │ 132
 │     │ 29.318          │ 36.904          │ ▓▓▓▓░░░░░░        │ LAST  1:31.512  +0.526                   │
 │     │ −0.023 vs PB    │ −0.077 vs PB    │ 3.312             │ BEST  1:31.390  SB                       │
 │     ├─────────────────┴─────────────────┴───────────────────┴──────────────────────────────────────────┤
 │     │ S1 ░░░░░ T3 ░░ T6 ░░░ S2 ░░ T9 ░░░░ T10-13 ░ T14 S3 ░░░░░▲car░░ T15 ░░ T16 ░ T17-18 │ (ribbon)    │ 56
 │ (●) ├──────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ (JR)│ LAP  Lap 6: 1:31.512, plus 0.5 on your best.        8 s     ● Mic live      [ HOLD TO TALK ]     │ 72
 └─────┴──────────────────────────────────────────────────────────────────────────────────────────────────┘ y=796
```

```css
/* Drive > Coach: the content area right of the 64 px rail. Load-bearing numbers. */
.drive {
  display: grid;
  padding: 12px;
  gap: 10px;
  height: 100dvh;
  grid-template-columns: repeat(12, minmax(0, 1fr));          /* 1092 px inner → 81.8 px columns */
  grid-template-rows: 48px minmax(240px, 1fr) 120px 132px 56px 72px; /* hero row = 294 px at 796 px */
  grid-template-areas:
    "status status status status status status status status status status status status"
    "next   next   next   next   next   next   next   delta  delta  delta  delta  delta"
    "coach  coach  coach  coach  coach  coach  coach  delta  delta  delta  delta  delta"
    "sect   sect   sect   sect   sect   sect   sect   laps   laps   laps   laps   laps"
    "ribbon ribbon ribbon ribbon ribbon ribbon ribbon ribbon ribbon ribbon ribbon ribbon"
    "radio  radio  radio  radio  radio  radio  radio  radio  radio  radio  radio  radio";
}
/* next/coach/sect: 7 cols = 633 px; delta/laps: 5 cols = 449 px; sect is a nested 3-col grid (204 px boxes). */
```

### 5.2 Panels

Sizes are at the reference viewport. All numbers use tabular figures.

| # | Panel | Shows | Source (today unless marked B-n, see section 10) | Type | When unknown |
| --- | --- | --- | --- | --- | --- |
| 1 | **Status bar** (48 px) | Connection pill; track name; session type; `LAP n` (`/ total` when known); SYNTHETIC badge; sub-nav; driver chip | `connection.status`, `connection.synthetic`, `session.track_name`, `session.session_type`, `frame.lap_number`, `session.total_laps`, `drivers.active` | 17 px / 600; labels 13 px caps | Track `-`, lap `-` |
| 2 | **Next corner** (hero, 633 × 294) | Label `NEXT CORNER` + direction arrow; **corner label** (`T15`) and **official name** (`Stowe`); **distance to the corner** (`320 m`); approach bar (fills over the last 400 m); `FOCUS` tag when the corner is one of the cue focus corners | `track_model.corners` (`entry_m`, `exit_m`, `direction`), `track_model.corner_text[name].short`, official name (**B3**), `frame.lap_distance_m`, `cues.focus` | Label 96 px / 800; name 44 px / 700; distance 44 px mono | No model yet: "Track map learns on your first clean lap" (20 px, muted). Name missing: label only. |
| 3 | **Cue band** (inside the hero, 84 px) | Cue kind chip (`BRAKE` red / `MARKER` neutral); cue text verbatim (`T15 brake`); `in 250 m` | `cues.next.kind`, `.text`, `.in_m`, `.corner` (shown when it matches the next corner, otherwise "Next call: T3 brake · 1.4 km" at 24 px); `cues.mode`, `cues.muted`, `cues.reason` | Chip 28 px / 800 caps; text 40 px / 700; distance 40 px mono | Mode off: "Calls off" (muted). Muted: "Calls paused: safety car". No plan: the server's `reason` ("no reference lap yet"). |
| 4 | **Coach card** (633 × 120) | Inline tag `WORK ON · L6` (amber) or `GOOD · L6` (green), then the observation text verbatim; up to 3 lines | **B6** `coach.by_corner[next]`; until then the highest-priority `observations[]` entry for the next corner | 26 px / 550, up to 3 lines, line height 1.2 | "No note for T15 on lap 6" (muted). No reference: "Coaching starts after your first clean lap". |
| 5 | **Delta panel** (449 × 424) | Label `DELTA TO REFERENCE` + reference identity (`PB · 1:30.986 · 3 Oct` or `Lap 4 · this session`); **delta** `−0.214`; word `AHEAD` / `BEHIND`; delta bar (±1.0 s full scale, ticks at ±0.5); `PROJECTED 1:30.772` | `delta_s`, `reference.lap_time_ms`, `reference.lap_number`, `reference.session_id` (= current session → "this session") | Delta 108 px / 700 mono; word 24 px caps; projected 32 px mono | Delta `-`, bar hidden. Projected `-` when either input is unknown or the lap is invalid. |
| 6 | **Sector boxes** (3 × 204 × 132) | `S1` `S2` `S3`; time; colour state + tag (`PB` purple, `SB` green, none yellow); `−0.023 vs PB`; the running sector shows a progress bar and its elapsed time | Current-lap splits (**B1**); bests (**B2**); sector bounds `skeleton.sectors`; `frame.sector`, `frame.lap_distance_m` | Time 40 px / 700 mono; tag 13 px / 800 | Without B1: the boxes show the **last lap's** sectors under a `LAST LAP` caption, and the running box shows only the progress bar. |
| 7 | **Lap times** (449 × 132) | `LAP` running time (+ `INVALID` tag); `LAST` + delta to reference; `BEST` (session best clean) + tag | `frame.current_lap_time_ms`, `frame.lap_invalid`, `frame.last_lap_time_ms`, `laps[]`, **B2** for PB | 32 px / 700 mono; labels 13 px caps | `-` |
| 8 | **Lap ribbon** (1092 × 56) | The lap as a horizontal strip: neutral grey sector bands labelled S1/S2/S3; a tick per corner, with labels only for the next corner and focus corners; a red notch at each cue braking point; yellow overlay on yellow-flag marshal zones; DRS zones dashed; car marker (triangle) | `skeleton.sectors`, `skeleton.marshal_zones` + `marshal_flags`, `skeleton.drs_zones`, `track_model.corners`, `cues.cues[].target_m`, `frame.lap_distance_m` | Labels 13 px / 700 mono | No skeleton: one neutral band. No model: no corner ticks. |
| 9 | **Radio strip** (1092 × 72) | Kind tag (`ENGINEER`, `LAP`, `CUE`, `ALERT`...) + current message (22 px, one line, ellipsis) + age; mic state; **HOLD TO TALK** button (220 × 56); when the radio is not live, a **GO LIVE** button instead (the user gesture iOS needs to unlock audio and the microphone) | `radio.current`, `radio.mic`, `radio.conn`, `radio.phase`, `radio.server.ptt` | 22 px / 550; button 20 px / 800 | "Radio quiet" (muted) |

Visual detail: the hero card has the signature **chamfered top-right corner** (16 px 45° cut) and a 3 px accent top
edge. No other panel has either.

### 5.3 Rules (pure functions, unit-tested)

All of these live in `web/src/lib/drive/*.ts` as pure functions of the snapshot, so they can be tested without a
browser.

- **Next corner.** Sort `track_model.corners` by `entry_m`. With `d = frame.lap_distance_m`:
  - while `entry_m ≤ d < exit_m` of a corner, show that corner as `NOW`, with no distance;
  - otherwise show the first corner with `entry_m > d` (wrapping to the first corner, distance + lap length), with
    `distance = entry_m − d`.
  - Track-model metres are the learned centreline's. When comparing with skeleton or cue metres, map by lap fraction,
    as `TrackMap.toModel` already does.
- **Corner text.** The large label is `corner_text[name].short` as sent ("T15", "T10-13", or "565 m" for an
  unlabelled corner on a mapped model). The official name is shown only when the server sends it separately (**B3**).
  The UI never parses "Turn 15 (Stowe)". Long names ("Maggotts and Becketts") shrink to 32 px and then wrap to two
  lines.
- **Cue matching.** `cues.next.corner` is assumed to be the learned corner name (open question Q6). If it is not the
  next corner, the band shows the next call as a secondary line.
- **Coaching point.** The UI uses B6 `coach.by_corner[next]` when present. Fallback: `observations` with
  `corner == next`, highest `priority` first. The UI never filters by its own thresholds (the server already applies
  confidence and impact limits) and never composes advice.
- **Delta colour.** `delta_s ≤ −0.005` → `--ahead` with the word AHEAD; `≥ +0.005` → `--behind` with BEHIND; anything
  in between uses `--text` with the word LEVEL. The bar grows left when ahead and right when behind, so direction
  reads without colour.
- **Projected lap** = `reference.lap_time_ms + delta_s × 1000`, labelled PROJECTED. It is `-` when the lap is invalid
  or either input is unknown.
- **Timing colours.** For a completed sector or lap time `t`, compared with the seated driver's bests for the same
  game, track and car:
  - purple + `PB` when `t ≤ personal best` (B2; equal counts: it matched the best);
  - green + `SB` when `t ≤ session best`;
  - yellow (no tag) otherwise;
  - neutral grey + `-` tag when there is nothing to compare with;
  - invalid laps are always neutral grey with an `INV` tag and never set a best (the F1 convention).
  - Phase-1 fallback without B2: the session best comes from `laps[]` (only the last 20 laps are in the snapshot,
    hence B2). A purple lap is possible from `drivers.active.stats.best_laps` (lap time only). Purple sectors wait for
    B2.

### 5.4 States

States are evaluated in this order. Overlays (bottom half of the table) combine with the base state.

| State | Detected by (snapshot fields) | Screen |
| --- | --- | --- |
| **No data** | `connection.status == "no_data"` | Hero becomes a 3-step checklist: "Turn on UDP telemetry in the game", "IP `<mac lan_ip>`, port `<udp_port>`", "Drive out of the garage" (values from `/api/connect`). Buttons: Open Setup > Connect, Try a demo replay (Settings > System). Delta, sectors and ribbon are hidden. The radio strip still offers GO LIVE. |
| **Stale** | `connection.status == "stale"` | Every value freezes and dims to 45 %. A centred overlay chip reads "Telemetry paused · 6 s" (`last_packet_age_s`), typically the game paused or in a menu. |
| **Garage / pre-session** | Live, `frame.pit_status == 2`, or no frame on track yet | **"Ready" card** replaces hero and delta: the seated driver's avatar (72 px), "**Alex** is in the seat", a 56 px **Not you? Switch driver** button, "Target: PB 1:30.986 (3 Oct)", "Focus today: T15 Stowe, T3 Village" (`cues.focus`, else "-"), GO LIVE for the radio. This screen is the main defence against laps landing in the wrong profile. |
| **Pit lane** | `frame.pit_status == 1` | Hero: `PIT LANE` (64 px) and **speed / limit** `79 / 80 km/h` (`frame.speed_kph` against `skeleton.pit_speed_limit_kph`; red above the limit). The coach card shows the last lap's summary: time, delta to reference, top point. Delta is `-`. |
| **On track** | Live, `pit_status == 0` | Normal Coach screen (5.1). |
| **Session ended** | `events[]` contains `session_ended`, or `chequered_flag` followed by pit/garage or stale | **Session complete card**: laps (clean/total), best lap with timing colour, gain against the first clean lap, one "Work on" and one "Went well" (server observations), a 56 px **Review this session** button → `#/review/s/<session_id>`. |
| *Overlay:* yellow flag | `marshal_flags[i].flag == "yellow"` | The status bar turns into a yellow band (same 48 px row) with dark ink: "YELLOW FLAG · Sector 3 · zone 16 · 380 m ahead" (distance from `skeleton.marshal_zones[i].start_m` and lap distance). The sub-nav and driver chip stay on it. The ribbon highlights the zone. No blinking. |
| *Overlay:* blue flag | `flag == "blue"` | Blue band, white ink: "BLUE FLAG · let the car behind through". |
| *Overlay:* safety car | `session.safety_car_status` is `full`, `virtual` or `formation_lap` | Amber band: "SAFETY CAR", "VIRTUAL SAFETY CAR" or "FORMATION LAP". The cue band shows the server's muted reason. |
| *Overlay:* red flag | Latest `events[].kind == "red_flag"` | Red band, white ink: "RED FLAG · 2 min ago". It clears on `lights_out`, `session_started` or `session_ended` (Q2). |
| *Overlay:* invalid lap | `frame.lap_invalid` | `INVALID` tag next to LAP; sectors grey; projected `-`. |
| *Overlay:* incident toast | New `collision`, `penalty` or `flashback` event | A 10 s chip at the right of the radio strip: "PENALTY · <code>", "COLLISION", "FLASHBACK · lap won't count". |

### 5.5 Drive sub-pages

- **Car:** today's LiveView car, tyres, fuel and input-trace panels with the new tokens. Values are at least 22 px,
  tyres in a 2 × 2 grid in FL, FR, RL, RR order, plus DRS, ERS store and brake bias. uPlot appears only here.
- **Track:** the existing `TrackMap`, large, with the live car, the current corner highlighted, sector colours,
  yellow zones and cue braking points (`cues.cues[].target_m`) as red ticks. Below it, a corner list with official
  long names. Tapping a corner shows what the engineer said about it on the last lap. This page is for learning a new
  track in practice.
- **Radio:** the existing `RadioView` stage (current message, big push-to-talk, radio check, stop talking) and the
  log. The settings panel moves to Settings > Radio & voice. Cue mode and coaching intensity stay here as a compact
  segmented row, because they are changed between runs.

### 5.6 Phone and portrait

Phone portrait (390 × 844) is the "pit wall" for whoever is watching. Top to bottom:

1. status line (40 px) and flag band;
2. delta (88 px number + bar);
3. next corner (`T15` 64 px, name 28 px, distance 32 px);
4. cue band (28 px);
5. coach text (18 px, 3 lines);
6. three sector boxes (24 px times);
7. radio mini bar (56 px);
8. tab bar.

The ribbon is hidden. Phone landscape uses the compact-landscape layout.

### 5.7 Legibility at about 70 cm

- On 11" and 13" iPads 1 CSS px ≈ 0.19 mm (0.156 mm on the iPad mini, so sizes there read about 18 % smaller).
  Cap height ≈ 0.72 × font size for SF Pro and SF Mono.
- ISO 15008 (in-vehicle displays) recommends a character height of about 20 arcmin, with 16 arcmin as the minimum.
  At 700 mm, 20 arcmin is 700 × tan(20′) ≈ 4.1 mm ≈ 21 px cap height, which gives **≥ 30 px font size**.
- Pitwall's floor for glance-critical values is **32 px** (4.4 mm cap height ≈ 21.6′).

| Item | Size | Cap height | Visual angle at 70 cm |
| --- | --- | --- | --- |
| Delta | 108 px | 14.8 mm | 72′ |
| Corner label (`T15`) | 96 px | 13.1 mm | 64′ |
| Distance / cue / sector times | 40-44 px | 5.5-6.0 mm | 27-30′ |
| Lap times | 32 px | 4.4 mm | 21.6′ |
| Coach text (read on straights, not mid-corner) | 26 px | 3.6 mm | 17.6′ (above the 16′ minimum) |
| Labels (learned by position, not read while driving) | 13-14 px | n/a | n/a |

Contrast for every Drive value is at least 7:1 (section 6.1). In Dim mode the text drops to `#c9ced6` (12.8:1) so it
does not glare in a dark room.

### 5.8 Performance on iPad Safari

- Coach has no uPlot, no `backdrop-filter` and no shadows.
- The ribbon is a static SVG. Only the car marker moves, using `transform`.
- Text nodes update only when their formatted string changes.
- Rendering follows the snapshot rate (`live_ws_hz`); nothing animates faster.
- The delta bar width transitions in 80 ms (disabled under `prefers-reduced-motion`). Nothing blinks (WCAG 2.3.1).
- Wake lock: Drive requests the screen wake lock on its first tap, using the same API the radio uses. It shows a
  "Screen may sleep" chip in the status bar when that is not possible.

---

## 6. Visual system

### 6.1 Colour tokens

**Dark (default).** Contrast ratios are WCAG 2.x, measured against `--bg` / `--surface-1`.

| Token | Value | Use | Contrast |
| --- | --- | --- | --- |
| `--bg` | `#050608` | Page background (near-black; true black on OLED iPads is fine too) | - |
| `--surface-1` | `#0d1015` | Panels, rail | - |
| `--surface-2` | `#151a21` | Raised: inputs, sector boxes, chips | - |
| `--surface-3` | `#1d242d` | Active pill, hover | - |
| `--line` | `#252d38` | Hairlines (1 px) | non-text |
| `--line-strong` | `#3a4554` | Focus rings, dividers in tables | non-text |
| `--text` | `#eef1f5` | Primary text (off-white to limit glare) | 17.9 / 16.8 |
| `--text-2` | `#a3adbb` | Secondary text, labels | 8.9 / 8.4 |
| `--text-3` | `#7a8596` | Tertiary / unknown `-` (replaces `#5b6574`, which was 3.3:1) | 5.4 / 5.1 |
| `--accent` | `#ff6a2b` | Pitwall orange: active nav, hero top edge, primary buttons (**dark ink** `#0c1016` on it, 6.7:1) | 7.1 / 6.7 |
| `--t-purple` | `#b97cff` | Personal best (PB) | 7.1 / 6.7 |
| `--t-green` | `#22d36f` | Session best (SB) | 10.3 / 9.6 |
| `--t-yellow` | `#ffd23f` | Slower than your session best | 14.0 / 13.2 |
| `--ahead` | `#22d36f` | Delta ahead | 10.3 / 9.6 |
| `--behind` | `#ff4d5e` | Delta behind; brake cue; over the pit limit | 6.3 / 5.9 |
| `--brake` / `--throttle` / `--ref` | `#ff4d5e` / `#22d36f` / `#38bdf8` | Traces (unchanged meaning) | ≥ 5.9 |
| `--flag-yellow` | `#ffd23f` band, ink `#0c1016` | Yellow flag | 13.2 (ink on band) |
| `--flag-blue` | `#2563eb` band, ink `#ffffff` | Blue flag | 5.2 |
| `--flag-red` | `#d11a2a` band, ink `#ffffff` | Red flag | 5.4 |
| `--flag-sc` | `#ffb020` band, ink `#0c1016` | Safety car / VSC / formation lap | 10.4 |
| `--status-live` / `--status-stale` / `--status-off` | `#22d36f` / `#ffb020` / `#7a8596` | Connection pill | ≥ 5.1 |
| `--synthetic` | `#f472b6` + 45° stripes | SYNTHETIC badge (no longer purple) | 7.7 |

Tints for timing cells: the sector colour mixed at 14 % into `--surface-2`, with the coloured text on top (purple
6.2:1, green 8.3:1, yellow 10.8:1).

**Light.** Kept for daytime Review. Drive defaults to dark ("Drive always dark", Settings > Display).

| Token | Value | Contrast on `#f3f5f8` / `#ffffff` |
| --- | --- | --- |
| `--bg` / `--surface-1` / `--surface-2` / `--surface-3` | `#f3f5f8` / `#ffffff` / `#eef1f5` / `#e3e8ef` | - |
| `--line` / `--line-strong` | `#d9dee6` / `#b8c1cd` | non-text |
| `--text` / `--text-2` / `--text-3` | `#0c1016` / `#4d5766` / `#5f6977` | 17.5 / 6.7 / 5.1 |
| `--accent` (text) / accent fill | `#c2410c` / `#ff6a2b` with ink `#0c1016` | 4.7 / 6.7 |
| `--t-purple` / `--t-green` / `--t-yellow` (text) | `#7c3aed` / `#0f7a3d` / `#8a5a00` | 5.2 / 5.0 / 5.4 |
| `--behind` / `--ref` / `--flag-sc` (text) | `#c81e3a` / `#0369a1` / `#a3480a` | 5.2 / 5.4 / 6.0 (on white) |
| `--synthetic` | `#be185d` | 5.5 |

In light theme the sector cells use **solid fills with dark ink** (dark ink on purple 6.7:1, on green 9.6:1, on yellow
13.2:1), so the colours keep the same strength as on the dark timing screen.

**Dim (Drive only, optional).** `--text: #c9ced6` (12.8:1), `--text-2: #8e98a6` (6.9:1), and the sector and flag
colours at 85 % lightness. For night sessions in a dark room.

### 6.2 Meaning: colour is never the only signal

| Meaning | Colour | Also shown by |
| --- | --- | --- |
| Personal best | Purple | `PB` tag; lowest luminance of the three timing colours (0.32 against green 0.48 and yellow 0.68), so it still separates for red/green colour vision deficiency |
| Session best | Green | `SB` tag |
| Slower | Yellow | No tag; the delta to PB is printed |
| Ahead / behind | Green / red | Sign (`−` / `+`), the words AHEAD / BEHIND, bar direction |
| Brake cue | Red | `BRAKE` word chip |
| Focus corner | Accent outline | `FOCUS` tag |
| Flags | Band colour | Words in the band ("YELLOW FLAG") |
| Unknown | `--text-3` | The `-` glyph itself |

Sector **identity** (which sector a stretch of track belongs to) is neutral grey with S1/S2/S3 labels. Today's
`SECTOR_COLOURS` (S1 red, S2 blue, S3 yellow, used by `SectorBands` and `TrackMap`) would clash with yellow =
"slower" and the yellow flag, so they move to grey steps in Phase 0.

### 6.3 Typography

There are no web fonts (offline LAN):

- sans: `-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif` (SF Pro on iPad);
- numerals: `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace` with `font-variant-numeric: tabular-nums`.

The timing-screen look comes from monospaced numerals, uppercase micro-labels with wide tracking, and strict
alignment. It does not come from a licensed or trademarked typeface.

| Token | Size / weight / tracking | Use |
| --- | --- | --- |
| `--d-hero` | `clamp(88px, 9.2vw, 132px)` / 700 mono / −0.02em | Delta |
| `--d-xxl` | `clamp(72px, 8.1vw, 112px)` / 800 sans | Corner label `T15`, `PIT LANE` |
| `--d-xl` | 44 px / 700 | Corner name, distance |
| `--d-l` | 40 px / 700 mono | Cue text, sector times |
| `--d-m` | 32 px / 700 mono | Lap times, projected |
| `--d-s` | 26 px / 550 | Coach text |
| `--d-xs` | 22 px / 550 | Radio strip, secondary Drive text |
| `--label` | 13 px / 700 / caps / 0.14em | Panel labels everywhere |
| `--h1` / `--h2` / `--h3` | 28 / 22 / 18 px, 700 | Review / Setup / Settings headings |
| `--body` | 16 px / 400, line height 1.5 | Body on iPad (up from 14 px) |
| `--table` | 15 px mono | Timing tables |
| `--small` | 13 px | Footnotes only, never essential data |

### 6.4 Spacing, shape, motion

- **Spacing scale (px):** 4, 8, 12, 16, 24, 32, 48, 64. Panels use 16 px padding (12 px on Drive strips); the Drive
  gap is 10 px.
- **Radii:** chips 6, cards 10, big buttons 14, pills 999. The hero chamfer is a `clip-path` 16 px cut at the top
  right.
- **Lines:** 1 px hairlines; 3 px coloured edges carry meaning (active nav, coach tag, sector state).
- **Elevation:** none in dark; light theme cards get `0 1px 2px rgb(0 0 0 / .06)`.
- **Motion:** state changes cross-fade in 120 ms and the delta bar moves in 80 ms; under `prefers-reduced-motion`
  there is no motion. Nothing ever blinks.

### 6.5 Components

| Component | Spec |
| --- | --- |
| `NavRail` / `TabBar` / `SubNav` | Section 4 |
| `StatusPill` | Dot + LIVE / STALE n s / IDLE; 28 px high |
| `SyntheticBadge` | Pink text, 45° stripes, "SYNTHETIC"; shown everywhere synthetic data appears (Drive, Review rows and headers, charts) |
| `FlagBanner` | Takes over the status-bar row (48 px; 56 px on other pages): icon + caps text, ink chosen per 6.1 |
| `NextCornerCard` | Chamfered hero; label, name, distance, approach bar, `FOCUS` tag |
| `CueBand` | Kind chip + text + distance; muted/off/reason variants |
| `CoachCard` | 3 px left edge in amber (`WORK ON`) or green (`GOOD`); verbatim text; "from lap n" |
| `DeltaPanel` | Number, word, bar, reference identity, projected |
| `TimingCell` | Time + state (pb/sb/slower/neutral/invalid) + tag; used for sectors and laps on Drive and in Review tables |
| `SectorBox` | `TimingCell` + label + running progress |
| `LapRibbon` | SVG strip (5.2 #8); reused in Review > Compare as the distance axis header |
| `RadioStrip` / `MiniRadioBar` | Current message + mic state + 56 px PTT, or GO LIVE |
| `ReadyCard` / `SessionCompleteCard` / `ChecklistCard` | Drive states (5.4) |
| `StatTile` | Label + 32 px value + timing state; Review summary |
| `WorkOnCard` | Corner, plain sentence, server observation, "See it on the lap" button → Compare `at=` |
| `TimingTable` | Tower style: alternate row shading, mono 15 px, sector cells as `TimingCell` |
| `TrendChart` | uPlot line/points over dates (Progress) |
| `Glossary` | 44 px "?" button that opens a plain definition ("Reference lap: the lap we compare you with, usually your best clean lap") |
| `SegmentedControl`, `BigButton` (56 px), `EmptyState` | Shared primitives |

### 6.6 Brand and trademarks

- The Pitwall name and the existing zig-zag glyph, with Pitwall orange as the only brand colour.
- Original icons, drawn as inline SVG: steering wheel (Drive), stopwatch with chart (Review), wrench (Setup), gear
  (Settings).
- No F1, FIA, FOM, game publisher or team names, logos, wordmarks, liveries or team colours, and no "Formula1" type.
- Purple/green/yellow timing colours and the red/blue/yellow sector-flag conventions are generic motorsport
  conventions, used with original styling.
- Circuit and corner names are factual data from the verified track sheets (`src/pitwall/trackdata/track_sheets`).

---

## 7. Review

### 7.1 Sessions (`#/review`)

**iPad: master-detail.**

- Left: session list (360 px).
  - Driver filter chips with avatars at the top (the existing server-side filter).
  - Rows grouped by day ("Today", "Yesterday", dates). Each row: track (17 px / 700), session type, car, laps,
    best clean lap as a `TimingCell` (purple when it was a PB at the time, with B5), SYNTHETIC badge, owner avatar.
  - Re-assigning a session stays in the row's overflow menu (56 px rows).
- Right: the selected session's Summary.

**Phone:** list → push to the session.

**Empty states** keep today's guidance ("Put them in the seat before they drive").

### 7.2 Session (`#/review/s/<id>`)

The sub-nav is Summary · Laps · Compare · Corners · Ask. The header shows track, date, car, driver avatar, session
type, SYNTHETIC badge, and a "Session report" action (the existing markdown report).

**Summary**, the beginner's page:

- **Four tiles:**
  - best clean lap (timing colour, "PB" when it is the driver's best);
  - clean laps / laps;
  - consistency, the spread of clean laps (max − min, computed from `laps`);
  - gap to PB.
- **Work on** (up to 1 / 3 / 5 cards for beginner / intermediate / advanced). Source: `analysis.corner_summary`
  sorted by `mean_time_delta_s` (losses only), with the observation text for that corner from
  `analysis.observations`. Each card shows the corner label and name, "about 0.11 s per lap here", the server's
  sentence, and a **See it on the lap** button → Compare at `at=apex_m`.
- **Went well:** positive observations (`exit_gain`), up to 3.
- **Lap times chart** (uPlot): one point per lap, filled = clean, hollow = flagged, purple marker for a PB. Tap a
  point → Compare that lap.
- **Track map coloured by corner:** the existing `TrackMap` `segmentDelta` from the corner summary means.
- **Engineer summary (optional):** "Ask the engineer for a summary" calls the existing `/api/engineer/ask`. The answer
  is badged `LLM · grounded` or `deterministic`, as today. Nothing on the page depends on it.

**Laps:** a `TimingTable` with columns lap, time, S1, S2, S3, Δ ref, status (flags in words: "pit out", "invalid",
"flashback"). Sector cells use the 5.3 rule. The reference and comparison pickers become two 44 px buttons per row
("Set as reference", "Compare"), replacing the 16 px radio buttons. "Pin as reference" keeps its server call.

**Compare:**

- Two large pickers: **Your lap** against **Reference / Best this session / Lap n / another driver's best** (family
  compare; the existing `/api/compare` already takes any two lap ids).
- Charts, in this order:
  1. the lap ribbon as a distance header (sectors, corners with official names);
  2. delta by distance;
  3. speed (both lines);
  4. throttle and brake, collapsed for beginners ("Show pedals");
  5. steering, advanced only.
- The map follows the cursor.
- A corner explainer, synced with the cursor, turns `comparison.corners` numbers into neutral words: "At T15 you
  braked 12 m earlier, minimum speed 4 km/h lower, 0.11 s slower". This is description, not advice. The advice is the
  server observation shown under it.
- Compatibility warnings and blocks stay visible, as today.

**Corners:** one card per corner, sorted by average time lost.

- Card contents: official long name; average time against the reference; brake-point spread (consistency, `brake_point_std_m`); minimum-speed delta; and the `FOCUS` tag when the corner is in the live cue focus.
- Tap a card → Compare at that corner.

**Ask:** `EngineerView`, scoped to this session, with suggestion chips and a facts toggle.

### 7.3 Coaching (`#/review/coaching`)

Per driver (avatar chips) and per track + car, built around a short plan:

- **Working on now:** up to 3 corners. Today this comes from the latest session's corner summary; with **B5**, from
  the last 3-5 sessions. Each corner has a trend arrow (getting better / same / worse, B5), the latest server
  observation, and a "See it" link.
- **Habits:** observations that carry a `consistency` string ("4 of the last 5 laps"), shown verbatim.
- **Recently fixed:** corners whose average loss dropped below the coaching threshold (B5).
- **What the radio will focus on next time:** `cues.focus` with the server's reasons (`cues.cues[].reason`).

### 7.4 Progress (`#/review/progress`)

Per driver, track and car.

| Chart / list | Data | Available |
| --- | --- | --- |
| Best clean lap per session over time, purple dot when a new PB was set | `/api/drivers/{id}/sessions` (`best_clean_ms`, `started_unix`, `track_id`, `car_name`) | Today |
| Laps driven per week (bar) | Same (`lap_count`) | Today |
| Consistency per session (median and spread of clean laps) | **B5** | Later |
| Corner heat table: rows = corners, columns = sessions, cell = mean time against the driver's PB reference, `-` where not driven | **B5** | Later |
| Milestones: first clean lap at a track, each new PB (with the gain), first session with 10 clean laps | Derived from the rows above (facts only, no invented goals) | Today / B5 |
| Family table: each driver's PB per track + car | `drivers[].stats.best_laps` | Today |

### 7.5 Beginner and experienced drivers

The driver's `skill_level`, already in the profile, sets Review's default density. The driver can always expand it.

| | Beginner | Intermediate | Advanced |
| --- | --- | --- | --- |
| Summary "Work on" cards | 1 | 3 | 5 |
| Compare charts by default | Delta + speed | + pedals | + steering |
| Corner table columns | Time, plain sentence | + brake point, min speed | All |
| Glossary "?" buttons | Shown | Shown | Hidden |
| Words | "braked 12 m earlier" | same | "Brake pt −12 m" allowed |

---

## 8. Setup

| Page | Content | Source |
| --- | --- | --- |
| **Connect** | Game telemetry steps (copy buttons), live UDP senders, "Open Pitwall on another device" (Tailscale HTTPS / LAN token URL) | `ConnectView` as is (being edited now), restyled later |
| **Rig** | Wheel base, game and pedal settings for the seated driver; rig check; upgrades | `SetupView`, split into sub-sections: Settings · Rig check · Upgrades |
| **Car setups** | Car setups per track (cloud task 8) | `CarSetupView` when it lands: the lead adds a route here instead of an App tab |

Setup opens on Connect until the first packet has ever been received, because that is the first-run path.

## 9. Settings

| Page | Content | Source |
| --- | --- | --- |
| **Drivers** | Profiles: colour, initials, skill, coaching intensity, stats; "Put in the seat" | `ProfilesView` |
| **Radio & voice** | Voice on/off, engineer voice (device / Mac), device voice and speed, Mac voice, coaching intensity, braking cues mode, diagnostics | `RadioView` settings panel, moved |
| **AI engineer** | Off / local / cloud, keys, tests, usage, what gets sent | `SettingsView` |
| **Display** (new) | Theme (dark / light / system), Drive always dark (on), Dim mode, Drive text size (Large / Extra large = +15 %), purple scope (Q1), show mini-map on Coach (off) | Local per device (localStorage) |
| **System** | Health, LLM health, captures with replay and simulate, capability matrix | `StatusView` |

---

## 10. Data contract and backend additions

Everything on Drive and in Review maps to an existing field, apart from the additions below. Until each one ships,
the UI shows the fallback described in 5.2 and 5.3 and never fills the gap with a guess.

| ID | Addition | Why | Notes |
| --- | --- | --- | --- |
| **B1** | Current-lap sector splits on the live frame: `sector1_time_ms`, `sector2_time_ms` | Current-lap sector boxes and running sector time | The F1 adapter already unpacks `sector1TimeMSPart` / `MinutesPart` (`adapters/f1/packets.py`) but emits them only at lap completion. Carry them on `CarFrame` and `frame_to_dict`. `None` for games that do not report them. |
| **B2** | `bests` in the snapshot for the seated driver and the same game, track and car: `session {lap_ms, sectors_ms[3]}` and `personal {lap_ms, sectors_ms[3], lap_id, set_unix}` | Purple / green / yellow sectors and laps; "vs PB" | Personal sector bests = best individual clean sector ever (the F1 convention). The live `laps[]` list is capped at 20, so the session best must come from the server. Replays never count (as today). |
| **B3** | `corner_text[name]` gains `label` ("T15") and `name` ("Stowe" or null) | Corner label and official name in separate slots | The UI must not parse "Turn 15 (Stowe)". |
| **B4** | `reference.sector_times_ms` | "vs reference" per sector when the reference is not the PB | Can be folded into B2. |
| **B5** | `GET /api/drivers/{id}/progress?track_id=&car=`: per session `{session_id, started_unix, laps, clean_laps, best_clean_ms, median_clean_ms, spread_ms, corners: {corner: mean_time_delta_s}}` plus PB history | Progress and Coaching beyond lap times | Corner deltas against the driver's PB reference at the time; SQL in `storage/repo.py`. |
| **B6** | `coach` block in the snapshot: the observation(s) the radio picked for the latest lap under the seated driver's limits (`drivers.apply_coaching_limits`), plus `by_corner` (top observation per corner) | The screen and the earpiece say the same thing; beginners see one point | Today `snapshot.observations` is unfiltered while `voice/proactive.py` filters, so they can differ. |
| **B7** | Optional `phase` (`garage`, `pit_lane`, `on_track`, `ended`) and `flag_state` in the snapshot | All clients (iPad, phone, radio) agree on the state | Until then, the client derives it per 5.4. |
| **B8** | Observation `short` (≤ 40 chars, descriptive, same rules as `text`: never "brake later" on its own) | Phone and glance use | Without it the full text is shown, never truncated mid-meaning. |

---

## 11. Migration plan

Each phase is a shippable PR that leaves `make check` and `cd web && npm run check` green. After each phase:
`make web`, `scripts/pitwall-service.sh restart`, a check on the iPad, and an update to `docs/status.md` and the web
section of `docs/architecture.md`. Nothing is called "done" in status until it has been used on the rig with the real
game (evidence tier: live).

| Phase | Scope | Files | Risk / notes |
| --- | --- | --- | --- |
| **0. Foundations** | Token set (6.1) with **aliases** for the old names (`--panel → --surface-1`, `--muted → --text-2`, `--faint → --text-3`, `--best → --t-purple`, `--gain → --ahead`, `--loss`, `--bad`), so every existing view keeps working. Dark ink on `button.primary`. Separate `--synthetic`. Neutral `SECTOR_COLOURS` (6.2). One `UNKNOWN = "-"` in `format.ts`. | `web/src/app.css`, `web/src/lib/format.ts`, `web/src/lib/SectorBands.svelte` (one constant) | Low. A visual pass of all ten views. |
| **1. Shell and routes** | Rail, tab bar, sub-nav, area header, mini radio bar; hash router with the legacy redirects (3.2). **Existing views are mounted unchanged** under their new routes. | New: `web/src/lib/router.svelte.ts`, `web/src/shell/{NavRail,TabBar,SubNav,AreaHeader,MiniRadioBar}.svelte`. Changed: `web/src/App.svelte` only | Low. No conflict with the voice and connect work in progress, which edits `RadioView`, `ConnectView` and `radio.svelte.ts`. |
| **2. Drive > Coach** | The new Coach screen with every state; LiveView split into Drive > Car; Drive > Track. | New: `web/src/views/drive/{DriveCoach,DriveCar,DriveTrack}.svelte`, `web/src/lib/drive/{state,nextCorner,timing}.ts`, components from 6.5 | Medium; the most value. Pure modules tested with `node --test` (TypeScript type stripping: Node 22.6+ with `--experimental-strip-types`, on by default from 23.6), so no new dependency. Validate states with `pitwall simulate` + replay, then live on the PS5 + iPad. |
| **3. Backend B1, B2, B3, B6** | Live data for current-lap sectors, bests, corner names, the radio's coaching pick | `adapters/f1/adapter.py`, `model/telemetry.py`, `core/live.py`, `analysis/track_identity.py`, `storage/repo.py`, tests (`test_f1_protocol.py` stays green) | Medium. Each is small and unit-testable. The UI lights up purple and green with no further change. |
| **4. Review** | Sessions master-detail; new Summary; `SessionView` split into Laps / Compare / Corners; Ask (scoped `EngineerView`) | `web/src/views/review/*` | Medium. Can be developed against synthetic and recorded sessions. |
| **5. Progress and Coaching** | B5 endpoint + the two pages + family compare | `api/routes_drivers.py`, `storage/repo.py`, `web/src/views/review/{Progress,Coaching}.svelte` | Medium |
| **6. Settings consolidation** | Radio & voice settings move out of `RadioView`; new Display page; Status becomes System; rig Setup split into sub-sections | `RadioView.svelte`, new `SettingsDisplay.svelte`, `SetupView.svelte` | Wait until the current voice work and cloud task 2 (rig fixes) have landed: same files. |

Acceptance checks for Drive:

- Delta, next corner and cue are readable at 70 cm in a dim room.
- A first-time driver can say "where am I losing time" from the Summary in under a minute.
- Every unknown value renders `-`.
- No layout shift when values go unknown.
- A 1-hour session keeps a steady frame rate on the iPad.
- The radio stays live while moving between areas.

---

## 12. Build it here or in the cloud?

This answers the request that started the work: **do the UI upgrade here, in the local Mac session**, and hand
well-specified pieces to cloud sessions once the current work is committed.

Why here:

- Drive has to be judged on the real iPad at the rig, with live PS5 telemetry, Tailscale HTTPS, the AirPod radio
  (microphone and wake lock only work on the secure page) and the launchd service. Cloud sessions have none of these.
  Their evidence tier stops at synthetic and recorded.
- The working tree has about 25 uncommitted files, including `RadioView`, `ConnectView` and `radio.svelte.ts`, which
  the new shell must host. A cloud session only sees what is pushed to `Moment-Up/pitwall`.
- Visual iteration (Browser pane preview, then the iPad) is a fast local loop.

Good cloud tasks (after a commit, following `docs/cloud-tasks.md`):

- the backend additions B1-B3, B5 and B6 (pure Python with unit tests, recorded fixtures);
- the Review pages (Phase 4-5), built against synthetic and recorded sessions.

Phases 0-2 and 6 belong here.

## 13. Open questions

- **Q1. Purple scope.** Is purple your all-time best (the default proposed) or the **family record** on that track
  and car (a playful option: purple = fastest anyone in the family)? This could be offered in Settings > Display.
- **Q2. Red flag lifetime.** The game sends no "red flag cleared" event that we decode today. The proposal clears the
  band on `lights_out` / `session_started` / `session_ended`; confirm against a real capture.
- **Q3. Leaving Drive on track.** No confirmation is proposed (the radio keeps running). Is that right for the
  youngest driver, or should the rail lock while moving?
- **Q4. Pre-session gating.** Should GO LIVE on the Ready card also confirm the driver ("Driving as Alex?")?
- **Q5. Phone as pit wall.** A read-only viewer mode (no push-to-talk, no driver switch) for spectators?
- **Q6. Cue corner names.** Confirm that `cues.next.corner` is the learned corner name used as the key in
  `track_model.corners` and `corner_text`.
