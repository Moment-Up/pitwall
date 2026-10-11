# Pitwall UI proposal B: "Pit wall" (dense)

> **Status:** design proposal only. Nothing in `web/src` or `src` is changed by this document.
> **Mockup:** [`mockup-pit-wall.html`](mockup-pit-wall.html). It is one self-contained file with no network
> requests. It shows the iPad-landscape Drive screen in every state, the navigation on iPad and phone, and one
> Review page. **All numbers, names and the circuit in it are sample data** (a made-up circuit, "Halden Ring", made-up
> times and placeholder family names). None of it comes from a real session.
> **Written against:** `web/src` and `src/pitwall` as of 2026-10-10 (commit `203ca12` plus the working tree).

---

## 0. The idea

On a real pit wall, engineers watch many screens, but at any moment one number matters most. Direction B gives
Pitwall the same shape:

- **The wall:** a strict grid of small, calm panels separated by hairlines, each with a header strip. Colour
  appears only when something needs attention.
- **The driver column:** one dominant column that carries only what a driver can take in with a glance of under
  half a second, at about 70 cm:
  - the **delta** to the reference lap;
  - the **corner that matters now**, with its official name;
  - the **next braking cue**;
  - **lap and sector times** in purple, green and yellow.

The wall serves a second person watching (another member of the household, or the driver once they stop in the pit). It never
competes with the driver column for the driver's glance.

**Key decisions**

1. **Nine tabs become four areas.** These are **Drive · Review · Setup · Settings**, each with 2 to 4 sub-pages.
   Every old URL still works (`#/radio` is on the iPad home screen).
2. **The Drive screen has two zones.** The driver column takes 7 of 12 columns and the wall takes 5 of 12. A
   **Focus** layout hides the wall. It is the default for drivers whose skill level is set to beginner.
3. **Purple, green and yellow keep their F1-timing meanings, adapted to a family rig:**
   - **purple** = the fastest anyone in the household has done here (same track, car and game);
   - **green** = your personal best;
   - **yellow** = completed, but not a best.

   The colours are shown only when the backend can prove them. Otherwise the time is shown neutral.
4. **No layout shift on Drive.** Every state (no data, pre-session, on track, pit, incident, stale, ended) swaps
   content inside fixed slots. A banner never pushes the delta down.
5. **The UI never writes coaching.** It shows the backend's observation `text` verbatim, plus the evidence behind
   it. A beginner glossary explains terms, never actions.
6. **Five small backend additions (D1 to D5, all additive)** unlock live sector colours, personal-best and
   household-record colours, and progress pages. Until each one lands, its UI shows `-` or neutral colours.

---

## 1. Design principles

1. **One glance, one answer.**
   - Anything the driver needs while moving is at least **32 px** (about 22 arc-minutes of capital height at 70 cm).
   - The hero delta is **144 px** (about 95 arc-minutes).
   - Smaller text on Drive (labels, the wall) is for a stationary reader.
2. **Colour is status, never decoration.** Each colour family has one job:
   - purple, green and yellow: timing only;
   - red, yellow, blue and cyan: flags and race state;
   - orange: "you" (your car, the selected item, primary actions).
3. **Calm by default.** A tyre inside its window is plain white, not green. Colour means "look here".
4. **Unknown stays unknown.**
   - A missing value renders as a single `-` in the tertiary colour. It is never `0` and never a guess.
   - Negative numbers use the true minus sign `−` (U+2212), so `-` can never be misread as a sign.
   - This mirrors the backend rule that adapters never fabricate values.
5. **A strict grid with no layout shift.**
   - Panels are fixed slots and states swap content within them.
   - Numbers use tabular figures, so digits do not jitter as they change.
6. **Deterministic first.** The UI only shows what `snapshot`, `/api/sessions/*/analysis`, `/api/compare` and the
   driver and radio stores provide. Derived values (session-best sectors, distance to the next corner) are computed
   from those facts and labelled as derived where that matters.
7. **Dark first, safe in a dim room.**
   - No large saturated fills on Drive. Status colours are tinted cells, edges and numerals.
   - Flag bands are the one exception, because a flag must interrupt.
   - A **Night** dim mode lowers luminance by a further 20 to 25%.
8. **Built for touch.**
   - Targets are at least **44 px** everywhere and at least **56 px** on Drive, in sheets and in the rail.
   - Nothing is hover-only.
   - Destructive or session-changing actions confirm inline, never through browser dialogs.

---

## 2. What the data supports today

Each element of the new UI is mapped to its source below. **Status** is one of:

- **have**: in the current API;
- **derive**: computed in the browser from fields that exist;
- **D1 to D5**: needs a backend addition (see section 9).

| UI element | Source (field) | Status |
|---|---|---|
| Delta to reference | `snapshot.delta_s` (server interpolates the reference lap's distance trace) | have |
| Reference label ("vs REF L5 · 1:28.904") | `snapshot.reference.{lap_number, lap_time_ms, session_id}` | have |
| Corner now / next, distance to it | `track_model.corners[].{seg_start_m, seg_end_m, entry_m, apex_m}` + `frame.lap_distance_m` | derive |
| Official corner name | `track_model.corner_text[name].{short, long}` (only where a track sheet is verified; Austria today) | have |
| Next braking cue + countdown | `cues.next.{corner, text, kind, in_m}`, `cues.mode`, `cues.muted`, `cues.focus` | have |
| Last cue outcome ("on time" / "late +6 m") | `cues.last.{error_m, status, reason, age_s}` − `cues.timing.margin_m` (same rule as `LiveView`) | have |
| Current lap time, lap n / total, position | `frame.current_lap_time_ms`, `frame.lap_number`, `session.total_laps`, `frame.race_position` | have |
| Sector in progress + progress bar | `frame.sector`, `skeleton.sectors[].{start_m, end_m}`, `frame.lap_distance_m` | derive |
| **Completed sector times of the running lap** | not in `frame_to_dict` | **D1** |
| Completed laps with sector times | `snapshot.laps[]` (20 newest: `lap_time_ms`, `sector_times_ms`, `clean`, `valid`, `flags`) | have |
| Session-best lap / sectors | from `snapshot.laps[]` (clean laps only) | derive |
| **Personal-best and household-record lap and sector times** | `/api/drivers` has `stats.best_laps` (lap only, per track); sectors and car scope missing | **D2** |
| Flags | `marshal_flags[]`, `skeleton.marshal_zones[]`, `session.safety_car_status` (`none` / `full` / `virtual` / `formation_lap`), `events[]` (`red_flag`, `chequered_flag`, `session_ended`, `penalty`, `collision`, `pit_entry`, `pit_exit`, `fastest_lap`) | have |
| Pit state, pit speed limit | `frame.pit_status` (0 none / 1 pit lane / 2 pit area), `skeleton.pit_speed_limit_kph` | have |
| Lap invalid | `frame.lap_invalid` | have |
| Connection | `connection.{status, last_packet_age_s, packets_per_s, synthetic, source}` | have |
| Tyres, brakes, fuel, ERS, inputs | `frame.*` (wheel order FL, FR, RL, RR) | have |
| Coaching, latest lap | `snapshot.observations[]` (`text`, `corner`, `impact_s`, `confidence`, `positive`, `consistency`) | have |
| Coaching, whole session | `/api/sessions/{id}/analysis` (`observations` per lap, `corner_summary`, `comparisons`) | have |
| Lap compare | `/api/compare?ref=&lap=`, `/api/laps/{id}/trace` | have |
| Radio state | `radio` store (`conn`, `mic`, `phase`, `server.cue_mode`, `intensity`, `ptt`, `quiet`, `tts*`) | have |
| Driver in the seat, skill level | `drivers` store (`active`, `preferences.{colour, initials, skill_level}`, `coaching`) | have |
| Progress: best lap per session over time | `/api/drivers/{id}/sessions` (`best_clean_ms`, `started_unix`, `track_*`, `car_name`) | have (lap level) |
| **Progress: consistency, corner trends** | not available | **D3** |
| Household leaderboard per track | `stats.best_laps` of every driver | have (lap level) |

**Snapshot cadence.** `/ws/live` pushes snapshots at up to `live_ws_hz` = 20 Hz. `track_model` and `skeleton`
arrive every 5 s, and `marshal_flags` with every snapshot. Drive animations must therefore tolerate a 50 ms update
step, as noted under Motion in section 6.7.

---

## 3. Information architecture

### 3.1 Four areas

| Area | Question it answers | Sub-pages | Replaces today |
|---|---|---|---|
| **Drive** | "How am I doing right now?" | **Timing** (default), **Car**, **Radio** | Live, Radio |
| **Review** | "What happened, what should I work on, am I improving?" | **Sessions** → Session (Overview · Laps & compare · Coaching), **Progress**, **Engineer** | Sessions, Session, Engineer |
| **Setup** | "Get the driver, rig and game ready" | **Drivers**, **Rig**, **Connect** | Drivers (Profiles), Setup, Connect |
| **Settings** | "How Pitwall behaves" | **Display**, **Radio & voice**, **AI engineer**, **System** | Settings, Status, the settings half of Radio |

Where each current view goes:

| Current view | New home | Change |
|---|---|---|
| `LiveView` | Drive › Car (the dense all-telemetry page). Its parts also feed the Drive › Timing wall | Re-skinned with new tokens; layout unchanged in phase 1 |
| `RadioView` | Drive › Radio (Go live, push-to-talk, radio check, log, cue mode, quiet) | Voice and device settings move to Settings › Radio & voice |
| `SessionsView` | Review › Sessions | Table becomes a card list grouped by day |
| `SessionView` | Review › Session, split into three tabs | Phase 4 |
| `EngineerView` | Review › Engineer (also opened from a session with that session preselected) | Re-skinned |
| `ProfilesView` | Setup › Drivers | Re-skinned |
| `SetupView` | Setup › Rig | Re-skinned |
| `ConnectView` | Setup › Connect | Re-skinned |
| `SettingsView` | Settings › AI engineer | Re-skinned |
| `StatusView` | Settings › System (health, LLM, captures / replay / synthetic demo, capability matrix) | Re-skinned |

### 3.2 Global chrome, on every page

- **Connection pill:** `● LIVE` (green dot), `● STALE 6 s` (amber), `○ NO DATA` (grey). If the stream is
  synthetic it also carries a hatched **SYNTHETIC** marker, and **REPLAY** when `connection.source` is a replay.
- **Driver chip:** the existing `DriverChip`, with the avatar colour and initials of the driver in the seat. It
  opens the "Who's in the seat?" sheet.
- **Radio pill:** `RADIO ●` when the radio is live (dot green when the mic is OK, amber when the mic is silent or
  muted), `RADIO ○` when the radio is not live. Tapping it opens Drive › Radio, or a "Go live" sheet when the radio
  is not live. Today the radio state is only visible on the Radio tab.
- **Theme:** moves into Settings › Display. A quick toggle remains in the rail footer, next to Night dim.

### 3.3 Routes

```
#/drive                 Drive › Timing          (default route; "/" and "" land here)
#/drive/car             Drive › Car
#/drive/radio           Drive › Radio
#/review                Review › Sessions
#/review/s/<id>         Review › Session › Overview
#/review/s/<id>/laps    Review › Session › Laps & compare   (?ref=<lap_id>&lap=<lap_id>&at=<corner>)
#/review/s/<id>/coach   Review › Session › Coaching
#/review/progress       Review › Progress      (?driver=<id>&track=<track_id>&car=<car>)
#/review/engineer       Review › Engineer      (?session=<id>)
#/setup/drivers  #/setup/rig  #/setup/connect
#/settings/display  #/settings/radio  #/settings/ai  #/settings/system
```

**Legacy redirects** use `history.replaceState`, so the back button does not loop:

| Old route | New route |
|---|---|
| `#/live` | `#/drive` |
| `#/radio` | `#/drive/radio` |
| `#/sessions` | `#/review` |
| `#/sessions/<id>` | `#/review/s/<id>` |
| `#/engineer` | `#/review/engineer` |
| `#/setup` | `#/setup/rig` |
| `#/profiles` | `#/setup/drivers` |
| `#/connect` | `#/setup/connect` |
| `#/settings` | `#/settings/ai` |
| `#/status` | `#/settings/system` |

`docs/radio-setup.md` documents `…:8443/#/radio`, so that redirect is permanent.

### 3.4 Device layouts

| Device / width | Navigation | Drive › Timing | Other areas |
|---|---|---|---|
| **iPad landscape** (≥ 1024 px, landscape): the primary target | Left **rail** 64 px + **top bar** 48 px with sub-tabs | Driver column (7/12) + wall (5/12), no scrolling | 12-column grid, panels in rows |
| iPad portrait / small tablet (768–1023) | Rail 64 px + top bar | Driver column full width on top (fixed); wall 2 columns below (only the wall scrolls) | Single or two columns |
| **Phone** (< 768) | **Bottom tab bar** with the 4 areas (64 px + safe area); sub-tabs as a scrollable segmented bar at the top | Focus layout only. Wall tiles live on Drive › Car | Single column, tables become cards |
| Desktop (≥ 1440) | Rail expands to 208 px and lists sub-pages as a tree | Driver column (6/12) + wall with 3 sub-columns | Max width 1680 |

---

## 4. Navigation pattern

- **Rail (iPad and desktop):**
  - Four items, each 64 × 64 px: a 24 px line icon above an 11 px uppercase label.
  - The active item has a 3 px orange bar on its left edge and the raised panel fill.
  - The rail footer holds a 44 px Night dim toggle, the theme toggle and the connection dot.
  - The Pitwall mark at the top goes to Drive.
- **Sub-tabs:**
  - A segmented control at the left of the top bar, 44 px tall, at least 88 px per segment.
  - Every area remembers its last sub-page (in `localStorage`, wrapped in try/catch like the current theme code).
- **Bottom tab bar (phone):**
  - The same four areas, each at least 72 × 56 px, plus the safe-area inset.
  - The Drive item carries a small live dot when telemetry is live, so the way back to the timing screen is
    obvious.
- **Drive lock:**
  - Applies when telemetry is live, the car is on track (`pit_status` is 0) and Drive is open.
  - The rail dims to 40% and hides its labels.
  - Leaving Drive needs a press of 0.5 s on a rail item; an orange ring fills under the finger. A short tap shows
    the toast "Hold to leave Drive while on track".
  - This stops an elbow or knee bump from swapping screens mid-lap.
  - It is off in the pit, before the session, after the session and when telemetry is stale. It is a setting in
    Settings › Display, default on.
- **Sheets:**
  - Pickers (driver, cue mode, lap A/B on phone, track/car on Progress) open as bottom sheets on phone and as
    anchored popovers on iPad. Rows are 56 px.
  - Escape or a tap outside closes them, as `DriverChip` already does.
- **Lap notifications:**
  - The `lap` WebSocket message raises a toast, "Lap 7 analysed · 2 coaching points → Review".
  - It appears only when the driver is **not** on track, for example in the pit.
  - On track, the Drive › Timing wall updates silently.
- **Keyboard (desktop):** keys `1` to `4` switch area, `[` and `]` switch sub-tab, and Space is push-to-talk
  (existing behaviour on the Radio page; on Drive pages only when the radio is live).
- **Screen wake:** Drive pages request a screen wake lock while telemetry is live. The radio store already does
  this on Go live, and the same helper can be reused.

---

## 5. Drive › Timing (iPad landscape)

### 5.1 Viewport and grid

The target is iPad 11-inch landscape, **1180 × 820 CSS px**, run as a **home-screen web app** (standalone, no
Safari toolbars). This needs two small additions to `web/index.html`: `apple-mobile-web-app-capable` and a web
manifest with `display: standalone`, and the status bar should use `black-translucent`.

In a normal Safari tab the visible height is about 740 px. All rows below are fractional with minimum sizes, so the
screen still fits without scrolling.

A 13-inch iPad (1366 × 1024 or 1376 × 1032) uses the same grid. Type grows by up to 1.15× through `clamp()` on
the container width.

```
x:  0     64 72                                        710 718                         1172 1180
    ┌─────┬──────────────────────────────────────────────────────────────────────────────────┐ y=0
    │ ◢   │ [ TIMING | CAR | RADIO ]   Halden Ring · Practice · Dry · track 31°C  ●LIVE RADIO● (JR)│ top bar 48
    │     ├────────────────────────────────────────────┬─────────────────────────────────────┤ y=48
    │DRIVE│ ┌ STATUS SLOT ─────────────────── 56 ───┐  │ ┌ TRACK MAP ───────────── 1.45fr ─┐ │ y=56
    │     │ │ LAP 8 · SECTOR 2 · TRACK CLEAR  FOCUS │  │ │ circuit, car, sectors, flags    │ │
    │REVIEW│ ├ DELTA ───────────────────── 1.2fr ───┤  │ │ RC: last race-control event     │ │
    │     │ │ DELTA · vs REF L5 · 1:28.904         │  │ ├ TYRES & ENERGY ─┬ INPUTS ─ 1fr ─┤ │
    │SETUP│ │            −0.21                     │  │ │ FL FR / RL RR   │ thr/brk trace │ │
    │     │ │ AHEAD ◀━━━━━━━━━━━┃            ▶ BEHIND│  │ ├ LAPS ──────────────── 1.1fr ───┤ │
    │SETT.│ ├ CORNER ─────────────┬ NEXT CUE ─ 1fr ─┤  │ │ L  TIME     S1    S2    S3   Δ │ │
    │     │ │ NEXT  T5  240 m     │ BRAKE  T5       │  │ ├ COACHING · LAST LAP ──── 1fr ─┤ │
    │     │ │ LAKESIDE            │ 180 m ▬▬▬▬▬▬░░░ │  │ │ [T5] text … +0.18 s            │ │
    │ ☾ ◐ │ ├ TIMING ─────────────────── 1.35fr ───┤  │ │ [T8] text … +0.09 s            │ │
    │  ●  │ │ LAP  0:47.3   S1 27.402  S2 ▸  S3 -   │  │ │ [T3] GOOD text … −0.06 s       │ │
    │     │ │ LAST 1:29.047  BEST 1:28.904  REC …   │  │ └────────────────────────────────┘ │
    └─────┴────────────────────────────────────────────┴─────────────────────────────────────┘ y=820
         content box: x 72→1172 (1100 px), y 56→812 (756 px); gutters 8 px
```

The exact sizes at 1180 × 820:

| Element | Size |
|---|---|
| Rail | 64 px wide; items 64 × 64 |
| Top bar | 48 px tall |
| Content box | 1100 × 756 px; padding 8; gutter 8 |
| 12-column grid | 12 × 84.3 px columns with 8 px gutters |
| **Driver column** | columns 1–7 = **638 px** wide. Rows: status slot **56 px** fixed, then delta / corner and cue / timing at **1.2fr / 1fr / 1.35fr**, which is about **229 / 190 / 257 px**. Minimums: delta 200, corner and cue 160, timing 210. Below a 760 px viewport height, the hero steps down to 120 px |
| **Wall** | columns 8–12 = **454 px** wide. Rows: map / tyres and inputs / laps / coaching at **1.45fr / 1fr / 1.1fr / 1fr**, which is about **233 / 161 / 177 / 161 px**. The tyres and inputs row splits into two tiles of 223 px |
| Panel chrome | 1 px hairline border (`--line`); 26 px header strip (`--panel-2`) with an 11–12 px uppercase label on the left and a state or evidence tag on the right; inner padding 12 px; corner radius 6 px |

### 5.2 Driver column, panel by panel

**A. Status slot (56 px, always present).** This one fixed slot is where the state of the session speaks. Its
content is swapped, never stacked.

- On track and clear, a calm single line on `--panel`:
  - `LAP 8 / 25` (25 only if `total_laps` is known) · `SECTOR 2` · `P4` (race sessions only) · `● TRACK CLEAR`;
  - on the right, the cue mode chip `CUES · FOCUS`.
  - Type is 22 px semibold, labels in `--fg-3`, values in `--fg`.
- Incident and pit states replace it with a **flag band**:
  - a full-width fill in the flag colour with dark ink;
  - 26 px bold uppercase;
  - a 3 px pulsing edge for the first 2 s only, then steady.
  - See section 5.5 for which band shows when.

**B. Delta (≈ 229 px).** The hero.

- **Label row (16 px, `--fg-3`):** `DELTA · vs REF L5 · 1:28.904`. When the reference lap comes from another
  session, a date is appended (`· 3 Oct`).
- **Number:** **144 px**, weight 700, tabular figures, letter-spacing −0.02em.
  - Two decimals while driving (`−0.21`), and one decimal at 10 s or more (`+12.4`). The three-decimal value is
    available on Drive › Car.
  - Colour:
    - `--gain` (green) when below −0.02 s;
    - `--loss` (coral) when above +0.02 s;
    - `--fg` inside ±0.02 s, so it does not flicker between colours on the line.
  - `-` when `delta_s` is null: no reference yet, before the lap distance is valid, or stale telemetry.
- **Delta bar:** 20 px tall, full width, on a number line from −1.0 to +1.0 s.
  - The fill grows from a centre tick: left in green when ahead, right in coral when behind.
  - Ticks at ±0.25, ±0.5 and ±1.0. A caret at the end shows a clamped value.
  - End labels `AHEAD ◀` and `▶ BEHIND` (12 px) give the meaning without colour.
- **No reference yet:** the panel shows `-` with the line "Your first clean lap becomes the reference" (20 px,
  `--fg-2`).

**C. Corner and next cue (≈ 190 px).** Two cells.

- **Corner cell (55%)**, "the corner that matters now":
  - If `lap_distance_m` is inside a corner's `seg_start_m … seg_end_m`, it shows `NOW` and that corner.
  - Otherwise it shows `NEXT`, the next corner and the distance to its `entry_m`, rounded to 10 m.
  - Layout: corner short label (`T5`) at **64 px** bold, distance at **36 px** on the same line, and the official
    name (`LAKESIDE`) at **32 px** uppercase semibold beneath. The following corner sits at 16 px in `--fg-3`.
  - Without a `corner_text` entry the learned name is shown and no official name is invented. Before a track model
    exists, the cell shows `-` and "Corners appear after the first clean lap".
  - Focus corners (`cues.focus`) get a 2 px orange outline on the label.
- **Cue cell (45%):**
  - The cue word is `cues.next.text`, for example `BRAKE` or a corner marker word, at **48 px** bold, coloured
    `--brake` for braking calls and `--fg` for marker calls.
  - Below it are the corner and distance (`T5 · 180 m`, **36 px**) and a **countdown bar**. The bar's width is
    `in_m / 300 m` and it empties as the braking point approaches.
  - Footer (16 px): the last cue's outcome, using the same rule as today's `LiveView`. Examples: `Last T4 · on time
    (−3 m)` in `--fg-3`, `Last T4 · late +6 m` in `--loss`, or `dropped (reason)`.
  - When `cues.mode` is `off`: "Cues off · Drive › Radio" in `--fg-3`.
  - When `cues.muted` is set: `MUTED · safety car` or `MUTED · radio off` in `--fg-2`.

**D. Timing (≈ 257 px).**

- **Row 1:** `LAP` label and the running lap time at **56 px**. While running it shows **tenths only**
  (`0:47.3`), because flickering milliseconds cannot be read. A completed time shows thousandths.
  - When `lap_invalid` is true, the running time is drawn struck through in `--fg-3` with an `INVALID` tag in
    `--loss`.
- **Row 2:** three **sector cells** (S1, S2, S3), each about 205 × 84 px.
  - A completed sector shows its time at **36 px**, tinted by its timing status, with an 18% fill, a 4 px top edge
    in the status colour and numerals in that colour. It also carries a small tag: `REC` for purple, `PB` for
    green, none for yellow.
  - The running sector shows `S2 ▸` with a thin progress bar. The bar's position comes from `lap_distance_m`
    against the sector bounds in the skeleton, so it is derived from real data.
  - Future sectors show `-`.
  - Completed sector times of the running lap need **D1**. Until D1 lands, completed cells show `✓` with no time,
    and their colour stays neutral.
- **Row 3:** `LAST`, `BEST` (best of this session) and `REC` (household record), each at **36 px**:
  - LAST and BEST are coloured by timing status;
  - REC is always purple and shows the record holder's initials in their avatar colour (from D2).
  - Any missing value is `-`.

The game's own on-screen display already shows speed, gear and RPM, so the driver column leaves them out on
purpose. They live in the wall's Inputs tile and on Drive › Car.

### 5.3 Wall tiles (dense, for a stationary reader)

All wall text uses the same scale: tile values 18–28 px, table cells 14–15 px, labels 11–12 px uppercase.

1. **Track map** (reuses `TrackMap.svelte`; header shows the track name, the corner count, and whether names are
   learned or official):
   - The circuit is coloured **per sector by the current lap's timing status**: completed sectors in
     purple/green/yellow, the current sector in `--fg`, future sectors in `--line-strong`.
   - Your car is an orange dot with a white ring.
   - The next corner is labelled in orange, and focus corners have a ring.
   - Braking zones (`entry_m` → `apex_m`) are short red strokes.
   - Live yellow marshal zones are a thick yellow overlay (`liveFlags`).
   - Footer line: the newest race-control event (`RC · Lap 7 · Pit exit · 2 min ago`).
2. **Tyres and energy** (header `TYRES · SOFT · 6 LAPS`):
   - A 2 × 2 grid in wheel order FL FR / RL RR. Each cell shows surface temperature at 24 px, then wear % and
     pressure at 12 px.
   - Temperature colour: cold in blue, in window in plain `--fg`, hot in amber, overheating in red. The thresholds
     are the existing `tyreTempColor` bands; only the in-window colour changes.
   - Footer: `Fuel 18.4 kg · +1.2 laps (game) · ERS 2.8 MJ`. Brake temperatures stay on Drive › Car.
3. **Inputs:**
   - Throttle and brake bars (12 × 64 px) plus a uPlot trace of the last 12 s (existing `Chart`, about 90 px tall).
   - Above them: `212 km/h · 6 · bias 56% · DRS -`.
4. **Laps** (5 newest, newest first; header `LAPS · REF L5`):
   - Columns: Lap · Time · S1 · S2 · S3 · Δ ref. Times and sectors are coloured by timing status (numerals only,
     with no cell fills, to stay calm).
   - Invalid laps are struck through with an `INV` tag. Pit laps are tagged `PIT`, and the reference lap gets a `R`
     marker.
   - The header tag shows `best sectors 1:28.821` (derived from clean laps).
5. **Coaching · last lap** (header `COACHING · L7 vs REF L5`):
   - Up to 3 observations from `snapshot.observations`, each a row with a corner tag, the backend text (15 px,
     2-line clamp) and the impact (`+0.18 s`).
   - Corrective tags are coral and positive tags are green with the word `GOOD`.
   - Footer link: `Review session →`, shown only when not on track.

### 5.4 Type sizes on Drive

Arc-minutes are approximate. They assume the iPad's CSS pixel is 0.19 mm, a viewing distance of 70 cm, and a
capital height of about 0.72 × the font size. Automotive display guidance (for example ISO 15008) puts in-car
glance text at roughly 20 arc-minutes of character height or more. Everything a driver reads while moving is above
that.

| Token | Use | Size / weight | Cap height | ≈ arc-min at 70 cm |
|---|---|---|---|---|
| `drive-hero` | delta | 144 / 700 | 104 px | 98′ |
| `drive-xl` | corner label (T5) | 64 / 700 | 46 px | 43′ |
| `drive-l` | running lap time | 56 / 650 | 40 px | 38′ |
| `drive-m` | cue word, official corner name | 48 / 700 and 32 / 600 | 35 / 23 px | 33′ / 22′ |
| `drive-s` | sector, LAST / BEST / REC, distances | 36 / 650 | 26 px | 24′ |
| `drive-min` | smallest drive-critical value | 32 / 600 | 23 px | 22′ |
| `drive-status` | status slot, flag band | 22–26 / 650–700 | 16–19 px | 15–18′ (bands rely on colour + position) |
| `label` | panel labels | 12–16 / 600 caps, +0.08em | 9–12 px | for a stationary reader |
| `wall-value` / `wall-text` | wall tiles | 18–28 / 600; 15 / 400 | 13–20 px | for a stationary reader |

In the **Focus** layout the same tokens step up one size: the delta goes to 184 px and the sector cells to 44 px.

### 5.5 States

The states are evaluated top-down and the first match wins. A pure function `driveState(snapshot, now)` in
`web/src/lib/drive/state.ts` returns one of these, so the logic is testable and identical on iPad and phone.

| # | State | Trigger (exact data condition) | Status slot | Delta | Corner / cue | Timing | Wall |
|---|---|---|---|---|---|---|---|
| 1 | **No data** | `connection.status == "no_data"` | "Waiting for telemetry" (grey) | Replaced by a checklist card: UDP port listening (from `/api/connect`), packets received: none, "Point the game's UDP telemetry at this Mac". Buttons: **Setup › Connect** and **Run synthetic demo** (Settings › System). The demo is labelled synthetic | Hidden behind the card | All `-` | Tiles at 40% opacity, values `-` |
| 2 | **Stale** | `connection.status == "stale"` (no packet for 2 s or more; server threshold) | **Amber-outlined** band: `NO SIGNAL · 6 s · game paused or in a menu?` | `-` (a frozen delta must never look current) | Dimmed to 45% | Running time `-`; LAST, BEST, REC stay (they are facts) | Dimmed to 45%, last values kept |
| 3 | **Session ended** | newest `events[]` entry is `session_ended` or `chequered_flag` (until the next session reset) | Neutral band: `SESSION ENDED` or `CHEQUERED FLAG` | Replaced by **Summary**: best lap (coloured), laps (clean / total), best sectors combined, gap to PB | Replaced by **Work on next time**: the top 2 observations (backend text, 22 px) | A 56 px button **Review session →**, plus LAST / BEST / REC | Laps tile grows to show all laps (scrolls) |
| 4 | **Red flag** | newest `events[]` entry is `red_flag` (any newer event clears it; at most 120 s) | **Red** band, white ink: `RED FLAG` | `-` | Cues are muted by the server | Running time kept | Unchanged |
| 5 | **In pit** | `frame.pit_status ∈ {1, 2}` | **Cyan** band: `PIT LANE · LIMIT 80 · 78 km/h` (1) or `IN GARAGE` (2). The speed turns `--loss` when above the limit. Limit from `skeleton.pit_speed_limit_kph`, else `-` | Replaced by **Stint**: laps this stint, best, tyre compound + age, fuel | Replaced by **Top point from the last lap**: the highest-priority observation, backend text at 26 px with its evidence line. The driver is stationary, so reading is allowed | Unchanged | Unchanged |
| 6 | **Pre-session** | live; `frame` present; `pit_status` 0 or null; no completed laps; and `current_lap_time_ms` 0/null or `lap_distance_m` < 0 (grid or out-lap before the line) | Neutral: `WAITING FOR START · PRACTICE` | Replaced by **Ready check**: Reference (`L5 · 1:28.904 · 3 Oct` or "none yet"); Radio (**Go live**, 64 px, if not live); Cues (mode + focus corners); Track model (learned n corners, official names yes/no) | Shows the first corner as `NEXT` | LAST and BEST `-`; REC shown | Live |
| 7 | **Safety car** | `session.safety_car_status ∈ {full, virtual}` (formation lap counts as pre-session) | **Yellow** band: `SAFETY CAR` or `VIRTUAL SAFETY CAR · cues muted` | Shown but dimmed with an `SC` tag (the delta is real but not meaningful) | The cue cell shows `MUTED · safety car` (from `cues.muted`) | Normal | Normal |
| 8 | **Yellow flag** | any `marshal_flags[].flag == "yellow"` | **Yellow** band: `YELLOW · SECTOR 2 · ZONE 7 AHEAD`. The zone comes from `skeleton.marshal_zones`; "ahead" means the zone starts within the next 1000 m, otherwise `YELLOW · SECTOR n` | Normal | Normal | Normal | The map shows the yellow overlay |
| 9 | **Lap invalid** | `frame.lap_invalid == true` | Small coral `INVALID` chip at the right of the normal line | Normal, with an `INV` tag on the label row | Normal | Running time struck through | Normal |
| 10 | **On track** | none of the above | `LAP 8 · SECTOR 2 · ● TRACK CLEAR` | As in 5.2 | As in 5.2 | As in 5.2 | As in 5.3 |

**Transient events.** These are not states. `penalty`, `collision`, `fastest_lap` and `pit_entry` / `pit_exit`
appear for 6 s as a chip at the right of the status slot (`PENALTY`, `CONTACT`, `FASTEST LAP`). They are also
written to the map tile's race-control line.

**Evidence markers.** These are not states either:

- With `connection.synthetic`, a hatched `SYNTHETIC DATA` marker sits in the top bar and the delta label.
- When `connection.source` starts with `replay:`, a `REPLAY` marker shows.
- Synthetic marking uses a pattern and words, **never a timing colour.** Today it uses the purple best colour,
  which would clash with purple timing.

### 5.6 Focus layout

- **What it is:** a toggle in the top bar, Pit wall ⇄ Focus (also in Settings › Display).
  - The wall is hidden and the driver column spans all 12 columns.
  - Delta and corner/cue sit side by side on top, with timing full width below.
  - Type steps up one size.
- **Default per driver:** Focus for beginners (`skill_level == "beginner"`), Pit wall otherwise. A manual choice
  is remembered per driver, in `localStorage`, keyed by driver id.
- **Phone:** always uses Focus.

### 5.7 Drive › Car and Drive › Radio

- **Drive › Car** is today's dense `LiveView` content, re-gridded as a pit-wall page. It is for a second person or
  a second screen, for example a Mac display.
  - **Car:** speed, gear, RPM, pedals, steering, G, brake bias, DRS, ERS.
  - **Tyres:** surface and inner temperatures, pressures, wear, brake temperatures.
  - **Fuel.**
  - **Inputs:** 12 s trace.
  - **Telemetry health:** packets per second, rejected and unrecognised counts, source. This moves here from the
    Live strip.
- **Drive › Radio** is today's `RadioView` stage: **Go live**, the big push-to-talk button, Radio check, Stop
  talking, the radio log, and quick controls for **cue mode**, **coaching intensity** and **quiet**.
  - Voice selection, the device voice, speed, the Mac voice and the TTS diagnostics move to Settings › Radio &
    voice.
  - The radio store is module-level, so the radio keeps running when the driver switches to Drive › Timing.
    Today's code already behaves this way; the pill makes it visible.

---

## 6. Visual system

### 6.1 Colour tokens

These are defined on `:root` in `app.css`. The old names (`--gain`, `--loss`, `--best`, `--accent` and so on)
remain as aliases until every view has migrated. Contrast ratios are WCAG 2.x, computed for these exact hex values
against the panel colour.

**Dark (default)**

| Token | Hex | Role | Contrast on `--panel` |
|---|---|---|---|
| `--bg` | `#07090C` | page background | - |
| `--panel` | `#0D1116` | panel body | - |
| `--panel-2` | `#121820` | panel header strip, table head | - |
| `--raise` | `#19212B` | controls, selected row, active rail item | - |
| `--line` | `#1F2832` | hairlines and grid | - |
| `--line-strong` | `#2B3744` | dividers, inactive track | - |
| `--fg` | `#ECF0F4` | primary text and values | 16.5 : 1 |
| `--fg-2` | `#A9B3BF` | secondary text | 8.9 : 1 |
| `--fg-3` | `#7D8996` | labels, `-` unknown | 5.3 : 1 (4.6 on `--raise`) |
| `--t-purple` | `#C08CFF` | **household record** | 7.6 : 1 |
| `--t-green` | `#34E08A` | **personal best** | 11.0 : 1 |
| `--t-yellow` | `#FFD43B` | **completed, not a best** | 13.3 : 1 |
| `--gain` | `= --t-green` | delta ahead, positive coaching | 11.0 : 1 |
| `--loss` | `#FF6B5E` | delta behind, corrective coaching, over-limit | 6.8 : 1 |
| `--flag-yellow` | `#FFD43B` | yellow / SC band (dark ink, 14 : 1) | - |
| `--flag-red` | `#D7263D` fill / `#FF4552` text | red flag band (white ink, 5.0 : 1) | 5.6 : 1 |
| `--flag-blue` | `#5A9BFF` | blue flag (when the game reports it) | 6.8 : 1 |
| `--pit` | `#4CC6E8` | pit band (dark ink, 10 : 1), pit tags | 9.5 : 1 |
| `--accent` | `#FF6A2B` | you: car dot, selection, primary buttons (**dark ink** on fills: 6.5 : 1; white is only 2.9 : 1) | 6.6 : 1 |
| `--ref` | `#38BDF8` | reference lap in charts | 8.8 : 1 |
| `--throttle` / `--brake` | `#34E08A` / `#FF4D5E` | input traces, braking cue word | 11.0 / 5.8 : 1 |
| `--temp-cold` / `--temp-hot` / `--temp-over` | `#5A9BFF` / `#FFB020` / `#FF4552` | tyre and brake temperatures | ≥ 5.6 : 1 |

**Light (kept)**

- `--bg #F2F4F7`, `--panel #FFFFFF`, `--panel-2 #F3F5F8`, `--line #DCE2EA`.
- Text: `--fg #0E1318` (18.7), `--fg-2 #46515E` (8.1), `--fg-3 #5F6B78` (5.4).
- Timing text colours: purple `#7B3FE0` (5.8), green `#0A7A42` (5.4), and for yellow text `#8A6200` (5.5).
- Other text colours: loss `#C2352A` (5.5), pit `#0A6A8A` (6.1), accent text `#B8460F` (5.4), ref `#0A6CA3` (5.7).
- In light mode the sector cells use **solid fills with dark ink**: purple `#7B3FE0` takes white ink (5.8),
  green `#16A35A` takes dark ink (5.7), yellow `#FFD43B` takes dark ink (13.1).

**Night dim** (`[data-dim="night"]`, dark only):

- `--fg` becomes `#C9CFD6` (12.7 : 1).
- Status colours drop 15% in lightness. The large Drive numerals keep their hue.
- It is meant for racing in a dark room, where full-white numerals bloom.

### 6.2 Timing colours

Purple, green and yellow have one meaning each, everywhere: Drive, the wall, Review and Progress.

| Colour | Meaning | Rule (scope = same game + track + car; clean laps only; never synthetic or replay sessions, matching the storage rules for references and PBs) |
|---|---|---|
| **Purple** `REC` | Household record | Faster than every previous time by **any** driver profile in this household |
| **Green** `PB` | Personal best | Faster than this driver's previous best, but not a household record |
| **Yellow** | Completed, not a best | A time exists and is slower than this driver's best |
| **Neutral** (`--fg`) | No comparison possible | First lap ever here, comparison data unavailable (D2 not landed), or an invalid lap (struck through) |

**When a time is coloured.**

- **Drive sector cells and LAST** are coloured *as set*: the status at the moment the time was completed. This is
  instant feedback, so a green S1 stays green for that lap.
- **Tables** (the wall's laps tile, Review laps, Progress) are coloured by *current standing*:
  - only the times that are still the best in their column are green or purple;
  - every other completed time is yellow.

  This answers "which lap had my best S2?" at a glance.

**Phase-1 fallback (before D2).** Bests are computed from this session's `snapshot.laps` only:

- **green** = this session's best;
- **yellow** = slower than this session's best;
- **purple is not shown.**

The legend then says "best of this session". Purple is never faked.

Each status also carries a non-colour cue: the `REC` or `PB` tag, and its position in the tables. Colour-blind
users (green and yellow can merge under deuteranopia) can still read it. A **Colour assist** setting adds the tags
to every timing cell, including the wall tables.

**Sector identity colours change.** The existing `SECTOR_COLOURS` (S1 red, S2 blue, S3 yellow) would collide with
timing yellow. Sector identity becomes **position and labels**: neutral alternating tints (`--panel-2` /
`--raise`) with `S1 S2 S3` labels and boundary ticks in `--fg-2`. On maps and bands, sectors are coloured only by
timing status.

### 6.3 Status and flag colours

| Situation | Treatment |
|---|---|
| Track clear | `● TRACK CLEAR` with a green dot, in the status slot (no band) |
| Yellow flag, safety car, virtual safety car | Yellow band with dark ink |
| Red flag | Red band with white ink |
| Pit lane / garage | Cyan band with dark ink |
| No signal (stale) | Amber **outline** band with amber text on `--panel` (an outline means "the data is in doubt", a fill means "the track says") |
| Session ended | Neutral `--raise` band with `--fg` text |
| Invalid lap | Coral chip |
| Synthetic / replay | Hatched marker with words, never a timing colour |

### 6.4 Typography

- **Families.**
  - The default is the system stack, which works offline everywhere with no dependency:
    - UI: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif` (SF Pro on iPad);
    - data tables: `ui-monospace, "SF Mono", Menlo, Consolas, monospace`;
    - big numerals: SF Pro with `font-variant-numeric: tabular-nums`, which looks less "terminal" than mono at
      144 px.
  - Optional, for a more distinctive timing-screen voice: bundle two SIL OFL fonts as local woff2 subsets in
    `web/public/fonts/` (each about 30–40 KB), with no CDN:
    - a condensed grotesque for uppercase labels and corner names (for example *Barlow Semi Condensed*);
    - a mono for tables (for example *JetBrains Mono*).
  - Record both in `docs/licences.md`. Do not use any font associated with F1 or broadcast graphics.
- **Scale outside Drive** (for a stationary reader at 40–60 cm):

  | Token | Size / weight | Use |
  |---|---|---|
  | `h1` | 28 / 700 | page title |
  | `h2` | 20 / 650 | section heading |
  | `body` | 16 / 400, line height 1.5 | running text |
  | `table` | 15 / 400, tabular | table cells |
  | `small` | 13 / 400 | secondary text |
  | `label` | 12 / 600, uppercase, +0.08em | panel labels |
  | `kpi` | 32 / 650, tabular | KPI tile values |

  The current base of 14 px goes up to 16 px. On an iPad, 14 px is too small for beginners reading reviews.
- **Number formatting:**
  - lap `1:28.904`; running lap `0:47.3`; sector `27.402`; delta `−0.21` / `+0.183 s`;
  - distances `180 m` (rounded to 10 m on Drive); speeds `212 km/h`;
  - unknown `-`. Units sit in a smaller weight after a thin space.

### 6.5 Spacing, grid, shape

- 4 px base unit. Scale: 4 · 8 · 12 · 16 · 24 · 32 · 48.
- Panels: radius **6 px** (sharper and more technical than today's 10), 1 px `--line` border, header strip 26 px.
  No shadows inside the grid. Only floating sheets and popovers get a shadow.
- Grid: 12 columns, gutter 8 px on Drive and 12 px elsewhere. Panels align to rows; nothing floats.
- Hairline tables: rows 36 px on iPad (44 px when the row is tappable), with numbers right-aligned.

### 6.6 Components

New components go in `web/src/lib/ui/` and `web/src/lib/drive/`. Existing components are kept as noted.

| Component | Purpose | Notes |
|---|---|---|
| `Panel` | header strip + body | props: `label`, `tag` (evidence or state), `state` (dim / stale) |
| `Rail`, `BottomBar`, `SubTabs` | navigation | 64 px items; hold-to-leave for Drive lock |
| `Pill` | connection / radio / synthetic / replay | live dot; hatched evidence variant |
| `StatusSlot` | fixed 56 px slot with line or band variants | drives section 5.5 |
| `DeltaHero` | number + bar | ±0.02 s neutral band; `-` when null |
| `CornerCell`, `CueCell` | corner that matters + next cue | official name only from `corner_text` |
| `SectorCell`, `TimingTriplet` | sector times; LAST / BEST / REC | timing status → tint, edge, tag |
| `TimingTable` | laps with coloured cells | `INV`, `PIT` and `R` tags |
| `KpiTile` | Review KPIs | value + label + delta + evidence |
| `CoachingCard` | observation with corner tag, text, impact, consistency, a "why" drawer (evidence) and "show on chart" | text verbatim from backend |
| `TyreGrid` | FL FR / RL RR | calm colour scale |
| `Segmented`, `Sheet`, `Toast`, `EmptyState`, `Glossary` | basics | 44–56 px targets |
| Kept | `TrackMap` (+ `sectorStatus`, `focus` props), `Chart` (uPlot), `SectorBands` (neutral tints), `DriverChip` | - |

### 6.7 Motion

- Drive numbers never animate (they tick at the snapshot rate). Bars ease over 80 ms linear, which suits the 20 Hz
  updates.
- A completed sector's cell flashes once: an 8 px glowing edge for 600 ms, so the change is seen in the periphery.
  A new flag band pulses its edge for 2 s, then holds steady.
- `prefers-reduced-motion` turns both into instant changes.
- No page transitions on Drive. Elsewhere, cross-fades of 120 ms or less.

### 6.8 Accessibility

- Body text is at least 4.5 : 1, and large numerals and UI parts at least 3 : 1 (see 6.1).
- No information is carried by colour alone: signs, `AHEAD` / `BEHIND` labels, `REC` / `PB` tags, band words.
- Touch targets are at least 44 px, and 56 to 64 px on Drive, in the rail and in sheets.
- Dynamic Type: honoured on the Review, Setup and Settings pages through `rem` sizing. Drive uses fixed px sizes,
  tuned for 70 cm.
- Screen readers:
  - every tile has an `aria-label` summary (for example "Delta minus 0.21 seconds, ahead of reference lap 5");
  - flag bands use `role="status"`, and use `role="alert"` for red flags;
  - values that only animate get `aria-live="off"`, so the 20 Hz updates are not announced.

### 6.9 Copy rules

- **Unknown is `-`.** No "—", no "--:--.---", no `0`. Placeholders such as "No laps yet" explain why, in words.
- **Negative sign is `−`.** `format.ts`'s `signed()` already does this.
- **Coaching text is the backend's text.** The UI may add an evidence line, built from the observation's own
  fields: `value`, `unit`, `impact_s`, `confidence` and `consistency`.
  - The UI never adds advice of its own, and in particular never "brake later". This follows the project rule that
    later braking is praised only when the corner got faster.
- **Plain words for beginners.** These are labels and a glossary, never new advice.
  - Labels: "Time lost here" instead of "Δt", "Braked" instead of "Brake pt Δ", "Slowest speed" instead of
    "V-min".
  - The glossary explains terms: reference lap, delta, braking point, apex, minimum speed, exit speed, clean lap,
    consistency.

---

## 7. Review area

Review's sub-tabs are **Sessions · Progress · Engineer**. A session has its own tabs: **Overview · Laps & compare
· Coaching**, plus a Report action, which keeps today's markdown report in a sheet.

### 7.1 Sessions

The list keeps today's server-side filter by driver.

- **"Last session" hero card** on top:
  - track · session type · when · driver avatar;
  - best lap (timing-coloured), laps (clean / total), and the number of coaching points;
  - a 56 px **Open** button.
- **Card list** grouped by day (Today, Yesterday, then dates):
  - each card is 72 px tall with the driver avatar, track, session type, car and when;
  - right side: best clean lap (timing-coloured), laps (clean / total), and evidence chips (`SYNTHETIC` hatched,
    `REPLAY`).
- **Filter chips** (44 px): Everyone · each driver (avatar), plus a track picker.
- **Reassigning** a session to another driver, which already exists, moves into the card's overflow menu (`⋯`) as
  a sheet. The tiny inline select goes. The existing confirmation copy is kept.
- **Phone:** the same cards, full width.

### 7.2 Session › Overview

This page is the answer to "how did it go and what's next?", in one screen on an iPad.

- **Header:** track · type · date · driver · car · weather; the evidence chips; the actions **Ask the engineer
  about this session** and **Report**.
- **KPI tiles** (5 across on iPad, 2 across on phone):
  - **Best clean lap**, timing-coloured, with the gap to the previous PB (`New PB · −0.146`).
  - **Laps**, clean / total.
  - **Best sectors combined**, derived from the clean laps' sectors, with "0.130 s on the table".
  - **Consistency**, for example "0.29 s, the spread of the last 3 clean laps" (derived from the laps).
  - **Reference used** (`L5 · 1:28.904`, with a link to Laps & compare).
- **What to work on** (up to 3 cards; beginners see 1 plus "Show more"):
  - Built from the session's observations, ranked by `priority` and `impact_s`, preferring corners with a repeated
    `consistency`.
  - Each card has a corner tag with its official name, a mini map with the corner highlighted, the **backend
    `text`**, an evidence line (`Seen on 3 of last 4 laps · ≈ 0.18 s a lap · confidence 0.82`) and **Show on chart
    →**, which opens Laps & compare zoomed to that corner (`?at=T5`).
  - Positive observations appear as a separate **"Going well"** strip in green.
- **Laps:** a compact timing table with timing colours, `INV` / `PIT` / `R` tags and the Δ to the reference. A
  tapped row opens Laps & compare with that lap as B.
- **Progress here:** a small chart of this driver's best lap at this track and car over the last sessions, with
  "faster ↑". It links to Progress.

### 7.3 Session › Laps & compare

- **Lap pickers:** two large 56 px buttons, **A: Reference** (cyan) and **B: Compare** (fg). Each opens a sheet
  listing laps with time, sectors and status. Only clean laps can be A, as today.
  - **Pin as reference** stays, placed next to A. Its confirmation is inline.
- **Delta-by-distance chart** at full width on top, with neutral sector bands and corner markers using official
  short labels. Below it, the synced **speed**, **throttle** and **brake** charts (uPlot, cursor-synced as today).
  - **Steering** and **gear** sit behind "More channels". That is the default for beginners; advanced drivers see
    them open.
- **Right column on iPad:** the track map coloured by corner delta (green gained, coral lost, neutral within
  ±0.01 s), and a **corner table** in plain words:

  | Corner | Time lost here | Braked | Slowest speed | Exit speed | Full throttle |
  |---|---|---|---|---|---|

  - Signs read as words in tooltips and in beginner mode: "12 m earlier", "4 km/h slower".
- **Compatibility warnings** (`comparison.compatibility`) appear as an amber strip above the charts. A blocked
  comparison shows the blocking reason instead of the charts.
- **Phone:** pickers on top, then the delta chart, the corner list as cards, and the other charts collapsed.

### 7.4 Session › Coaching

- Observations for **every lap**, grouped **by corner**, not by lap. This answers "what keeps happening at T5?".
  - Each corner group shows the corner name, the session averages from `corner_summary` (time, brake-point mean
    and spread, minimum speed) and the laps where an observation fired. Each observation shows its text and evidence.
- A filter switches between Corrective, Going well and All.
- The beginner glossary is pinned on the right on iPad, and is a sheet on phone.

### 7.5 Progress, per driver

- **Pickers:** driver (avatars, 56 px) and track + car (a sheet listing the combinations this driver has driven,
  from their sessions).
- **Best lap per session over time** (uPlot):
  - points coloured by timing status (PB green, household record purple);
  - the y-axis is **inverted and labelled "faster ↑"**, so beginners read up as good;
  - synthetic and replay sessions are excluded, as in the server's PB rules.
- **Laps driven per week** (bars) and **clean-lap rate**. Both are derivable from the session list (`lap_count`) and,
  with D3, from clean counts.
- **Corner trends (D3):** small multiples, one per corner, of the mean time lost against the reference per session.
  "T5 is getting better" becomes visible at a glance.
- **Milestones:** new PB, first clean lap at a track, first session at a new track. All are derived from the
  sessions and `best_laps`.
- **Household board:** per track + car, the best lap of each driver, with avatars and the record in purple. This
  data exists today in each driver's `stats.best_laps`. It is a gentle family competition and needs no new data.

### 7.6 Engineer

This is today's `EngineerView`, restyled. It sits under Review because it answers questions about recorded sessions.

- Session context is preselected when opened from a session.
- Suggestion chips are 44 px.
- An LLM status pill sits in the header, and the facts drawer is kept.
- The rule "answers are grounded or replaced by a deterministic answer" is shown as one line of explanation,
  unchanged.

### 7.7 Beginner mode

Beginner mode is driven by the **driver's profile** (`skill_level`), not a global switch. The pages below change
only for the profile being viewed. For example, a beginner's sessions open simplified, and an advanced driver's open in full.

| Page | Beginner | Intermediate / advanced |
|---|---|---|
| Drive | Focus layout by default | Pit wall |
| Overview | 1 "work on" card + Going well; plain labels; glossary links | 3 cards; technical labels |
| Laps & compare | Delta + speed + throttle/brake; corner table in words | All channels |
| Coaching | Corrective items limited to the top corner | All |
| Progress | "faster ↑" chart, milestones, household board first | Corner trends first |

The coaching *content* already adapts on the server (`coaching.simple_wording`, `max_corrective_per_lap`). The UI
only changes how much it shows.

---

## 8. Setup and Settings

**Setup** (the garage, used before driving):

| Page | Content | Notes |
|---|---|---|
| **Drivers** | Profile cards (today's `ProfilesView`): colour, initials, skill level, coaching, stats, "Put in the seat" | First, because "who's driving" comes first. The driver chip's "Manage profiles" links here |
| **Rig** | Today's `SetupView`: recommended wheel base, game and pedal settings per driver, provenance tags (V / A / U / D / H), upgrades, known issues, **Rig check** | Rig check results use the status palette (pass = green dot, warn = amber, fail = coral, unknown = `-`), never timing colours |
| **Connect** | Today's `ConnectView`: telemetry status, games (integrations), game setup guides with copy buttons, live senders, open on another device (Tailscale / LAN URLs) | The Drive no-data card links here |

**Settings** (how Pitwall behaves; rarely visited):

| Page | Content |
|---|---|
| **Display** | Theme (dark / light), Night dim, Drive layout default (Pit wall / Focus / follow the skill level), Colour assist tags, Drive lock, delta neutral band (±0.02 s) |
| **Radio & voice** | Moved from `RadioView`'s settings block: voice on / off, engineer voice (device / Mac), device voice, speaking speed, Mac voice, TTS status and diagnostics |
| **AI engineer** | Today's `SettingsView`: off / local / cloud, keys, fallback, test, usage, what gets sent |
| **System** | Today's `StatusView`: health, worker errors, local LLM status, captures and replay, **synthetic demo** (clearly labelled), capability matrix, version |

---

## 9. Backend data additions

All additions are additive and return `None`/`null` when unknown. They follow the "unknown stays unknown" and
evidence-tier rules. None of them is required for phases 0–2. The UI degrades as described in each row.

| ID | Addition | Where | UI without it |
|---|---|---|---|
| **D1** | `frame.current_lap_sector_ms: [s1, s2]`, the completed sector times of the running lap, from the game's own lap data. The F1 adapter already reads `sector1TimeMSPart` / `MinutesPart` for completed laps. Zeroes become `None` | `model/telemetry.py` `CarFrame`, F1 adapter, `frame_to_dict` | Completed sectors of the running lap show `✓` (no time, neutral colour) |
| **D2** | `snapshot.bests = { driver: {lap_ms, sectors_ms[3], lap_id, set_unix}, household: {lap_ms, sectors_ms[3], driver_id, …}, session: {...} }` for the current game + track + car. Clean laps only; synthetic and replay sessions excluded; sector bests are per sector (`min(s1_ms)` …), so they need not come from one lap. Sent with the 5 s static payload and recomputed after each lap | `storage/repo.py` query; `LiveState` | Session-only fallback: green = session best, no purple |
| **D3** | `GET /api/drivers/{id}/progress?game&track&car` returns per session: `started_unix`, best clean lap, clean / total laps, spread of clean laps, and per corner `mean_time_delta_s` vs the driver's reference | analyzer + repo | Progress shows lap-level charts and the household board only |
| **D4** (optional) | `snapshot.session_state`: `pre`, `running`, `ended`, decided server-side from the events (`lights_out`, `session_started`, `chequered_flag`, `session_ended`), so phone and iPad agree exactly | `LiveState` | The client derives it as in 5.5 |
| **D5** (optional) | `/api/live` exposes `cues.focus` with official labels, plus `corner_text` voice strings for the cue word | cues snapshot | The client maps through `corner_text` |

---

## 10. Migration plan

Each phase ships on its own, keeps every route working, and passes `make check` (which already runs
`npm run check` / `svelte-check`). The service is restarted afterwards (`scripts/pitwall-service.sh restart`). No
existing view is deleted until its replacement is in use.

| Phase | Scope | Files (new / changed) | Done when |
|---|---|---|---|
| **0 · Tokens** | Add the new tokens and light / night values; alias the old names; `format.ts` placeholders become `-`; the synthetic badge becomes hatched; sector identity colours become neutral | `app.css`, `lib/format.ts`, `lib/SectorBands.svelte` (`SECTOR_COLOURS`), `lib/TrackMap.svelte` | Every page renders unchanged apart from colours; contrast spot-checked; light theme OK |
| **1 · Shell** | Rail, bottom bar, sub-tabs, top-bar pills (connection, radio, driver), route table + legacy redirects, remembered sub-page, PWA meta (standalone) | `App.svelte` (shell only), new `lib/ui/Rail.svelte`, `BottomBar.svelte`, `SubTabs.svelte`, `Pill.svelte`, `lib/routes.ts`; `index.html`, `public/manifest.webmanifest` | The nine old views reachable under the four areas; `#/radio` and the other old links redirect; phone shows the bottom bar |
| **2 · Drive** | `DriveTiming` view: status slot, delta, corner + cue, timing, wall tiles, Focus layout, Drive lock, wake lock. `LiveView` becomes Drive › Car. `RadioView` stage becomes Drive › Radio (settings block moves in phase 5) | new `views/drive/DriveTiming.svelte`, `lib/drive/{state.ts, DeltaHero, CornerCell, CueCell, SectorCell, TimingTriplet, StatusSlot, Wall*}.svelte`; `TrackMap.svelte` gains `sectorStatus` and `focus` props | Every state in 5.5 reproduced by replaying `pitwall simulate` captures and the recorded Austria excerpt; checked on the real iPad at 70 cm in the dim room (see the acceptance test below) |
| **3 · Data** | D1, D2 (then D3); backend owners, with tests at the synthetic and recorded tiers | `model/telemetry.py`, `adapters/f1/adapter.py`, `core/live.py`, `storage/repo.py`, `api/app.py` + tests | Live S1/S2 colours and REC/PB on Drive; protocol test still green |
| **4 · Review** | Sessions card list; Session split into Overview / Laps & compare / Coaching; beginner mode; Engineer under Review | `views/review/*` (from `SessionsView`, `SessionView`, `EngineerView`) | A beginner can find "what to work on" from their last session in 2 taps |
| **5 · Progress + regroup** | Progress page (lap level, then D3); household board; Setup and Settings regrouping; Radio settings move | `views/review/Progress.svelte`, `views/settings/{Display, RadioVoice}.svelte` | All four areas complete; old view files removed or slimmed |
| **6 · Polish** | Optional bundled OFL fonts, Night dim tuning, reduced motion, screen-reader labels, light theme pass | `public/fonts`, `docs/licences.md` | Accessibility checklist (6.8) passes |

**Testing without new dependencies.**

- The pure Drive logic (`driveState`, corner-that-matters, timing status, formatters) lives in plain `.ts` modules.
- It can be unit-tested with `node --test` using Node's built-in TypeScript type stripping (Node 22.6 or later),
  so no vitest is needed.
- Fixtures are recorded snapshots in JSON, captured from a synthetic replay and from the recorded Austria excerpt.

**Acceptance test for glanceability (phase 2), on the real rig:**

- Mount the iPad at about 70 cm in the usual dim room.
- Each family driver does 3 laps with Drive › Timing visible.
- Afterwards, each driver must be able to say whether they were ahead or behind, roughly by how much, and the name
  of the next corner, from glances alone.
- If anyone squints, raise `drive-*` one step.

**Coordination.** Other engineers are editing `RadioView`, `ConnectView` and `radio.svelte.ts` right now (see
`git status`). Phase 1 touches only `App.svelte` and new files. Phase 2 moves `RadioView` without editing its
internals, and its settings move waits until their branch lands.

---

## 11. Build here or in the cloud?

| Work | Where | Why |
|---|---|---|
| Phase 2 (Drive), the on-device acceptance test, Night dim tuning | **Here** | Needs the real iPad at the rig, live PS5 telemetry, Tailscale HTTPS for the radio, the launchd service, and the dim room. Synthetic data cannot tell you whether 144 px reads at 70 cm |
| Phase 0–1 (tokens, shell, routes) | Either; **here** is simpler | Pure frontend, but it touches `App.svelte` while other engineers are editing views locally. Local avoids merge pain |
| Phase 3 data additions (D1–D3) | **Cloud is fine** | Spec-driven backend work with tests at the synthetic and recorded tiers (`tests/fixtures/recorded` is in the repo). It fits the `docs/cloud-tasks.md` pattern |
| Phase 4–5 (Review, Progress) | **Cloud is fine**, then a local look on the iPad | Uses stored sessions; `pitwall simulate` + `replay` produce data in any environment. Final check on the iPad |

---

## 12. Open questions for James

1. **Purple semantics.** Is purple the household record (proposed) or "my all-time best" with green for "best this
   session"? The proposal favours the household record because three people share the rig.
2. **Which iPad?** The grid is tuned for 11-inch (1180 × 820). A 13-inch iPad gets more room for the wall; an iPad
   mini (1133 × 744) should default to Focus.
3. **Speed and gear on the driver column?** They are left out because the game's own display shows them. Say if
   you want them back.
4. **Drive lock default.** On, as proposed, or off?
5. **Fonts.** Stay with the system stack (zero bytes), or bundle the two OFL fonts for a more distinctive look?
