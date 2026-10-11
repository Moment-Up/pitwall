# UI proposal A: "Timing screen minimal"

_Design proposal, 2026-10-10. Status: proposal only, nothing implemented. Mockup:
[`mockup-timing-screen.html`](mockup-timing-screen.html) (open it in Safari on the iPad as well as on the Mac)._

Direction A takes its cue from broadcast timing graphics: very large numerals, **one focal metric at a time**, and
everything else visually quieter. Of the directions it is the one most focused on at-a-glance reading. The look
is original: condensed numerals, hairline rules, square timing cells with a coloured top bar, and purple, green and
yellow used only to mean timing results. It uses no F1, FIA or team names, logos, fonts or livery colours.

The proposal covers the four goals:

1. **Glanceable while driving**: a new Drive screen for an iPad in landscape at about 70 cm (section 4).
2. **Simpler navigation**: 9 tabs become 4 areas, which work on an iPad rail and on a phone tab bar (sections 2-3).
3. **A distinctive pit-wall look**: tokens, type, components (section 5).
4. **Clearer review and coaching**: written for a beginner, with progress per driver (section 6).

Every value in this document comes from data that exists today (`/ws/live` snapshot, REST endpoints, driver
stats) **or** is marked **[needs backend Bn]** and listed in section 9. The UI never invents a value: when something
is unknown it shows `-`.

---

## 1. Design principles (the rules every screen follows)

| # | Rule | Why |
|---|---|---|
| P1 | **One focal number per screen.** On Drive it is the delta to the reference lap. Everything else is at least 2 sizes smaller and one brightness step lower. | The driver's eye lands in the same place every glance. |
| P2 | **Nothing moves while driving.** The layout is fixed. State changes recolour or replace the content of a panel but never move or resize panels. | A glance must not have to search. |
| P3 | **Colour means timing.** Purple, green and yellow mean timing results only. Status uses its own hues (amber for stale, red for danger, yellow flag bands). Driver colours appear only in avatars. | Colour you can trust at a glance. |
| P4 | **Never colour alone.** Every coloured state also has a sign, a direction or a word (`−`/`+`, the bar's fill direction, the `BEST`/`PB` micro-labels, `INVALID`). | Colour-vision deficiency (red-green affects about 1 in 12 men) and glare. |
| P5 | **Unknown shows `-`.** Placeholders never look like data (no `0.000`, no `--:--.---`). Stale values are dimmed and carry their age. Values are blanked when the link is lost. | "Unknown stays unknown" (CLAUDE.md), carried through to the UI. |
| P6 | **The screen looks ahead and the radio does the timing.** The iPad shows what is coming on the straight. It never flashes "BRAKE NOW". Braking calls stay audio (`coach/cues.py`). | Eyes stay on the road at the braking point. |
| P7 | **More detail only when stationary.** In the pit, the garage or after the session, the Drive screen can show sentences (last-lap summary, the top coaching point). | You have time to read only when the car is stopped. |
| P8 | **Evidence tiers stay visible.** Synthetic data carries a hatched `SYNTHETIC` chip on every screen, and replays carry `REPLAY`. | Evidence tiers rule (CLAUDE.md). |
| P9 | **The UI adds no advice.** Coaching text comes from the deterministic coach (`analysis/coaching.py`) or the grounded engineer. The UI only formats it, ranks it and links to the evidence. | No advice outside validated facts. Coaching never suggests braking later on its own. |

---

## 2. Information architecture

### 2.1 Four top-level areas

| Area | Sub-pages (tabs) | Replaces today | Main device |
|---|---|---|---|
| **Drive** | **Dash** (default) · **Car** · **Radio** | Live (split: glance items go to Dash, detail to Car), Radio | iPad on the rig |
| **Review** | **Sessions** · **Progress** · **Engineer**. Inside a session: **Summary** · **Laps** · **Compare** · **Coaching** | Sessions, Session, Engineer | iPad / phone / Mac |
| **Setup** | **Checklist** (default) · **Connect** · **Drivers** · **Rig** | Connect, Drivers (Profiles), Setup (rig) | any |
| **Settings** | **Engineer AI** · **Radio & voice** · **Display** · **System** | Settings, the Radio page's settings panel, Status | Mac / iPad |

What moves where:

- **Live → Drive › Dash** keeps only what you need at a glance: delta, next corner, sectors, lap, last and best,
  and the lap strip. **Live → Drive › Car** takes the rest: speed, gear and pedals, tyres, fuel and ERS, the 12 s
  input trace, the full track map with live marshal flags, the lap table and the latest coaching (all of the current
  `LiveView` panels, restyled).
- **Radio → Drive › Radio** holds Go live, push-to-talk, Radio check, Stop talking and the radio log. The radio's
  **settings** (voice source, device voice, rate, intensity, cue mode) move to **Settings › Radio & voice**. The
  radio itself is a store (`radio.svelte.ts`), so it keeps running when you switch sub-page. Dash shows a radio pill
  and the latest message.
- **Engineer → Review › Engineer**, a session-scoped chat. Every coaching card and corner row gets an
  **Ask the engineer** button that opens it with a pre-filled question (for example "Why am I losing time at T9?").
- **Status → Settings › System** holds health, the local LLM, captures, replay and simulate, and the capability
  matrix. Replay and simulate are developer tools, so they belong in System and not in Review.
- **Setup › Checklist** is new, a pre-flight page: game connected (`/api/connect`), who is in the seat (drivers),
  radio state (radio store), the last rig-check counts (`/api/rig/check`) and "Open Drive". Every line already
  exists as data. The page only puts them together.
- **Driver chip** (who is in the seat) is global: at the bottom of the rail on iPad, top right on the phone, and
  shown large on Drive's pre-session state.

### 2.2 Routes (hash router, offline, no new dependency)

| New route | Page | Legacy routes redirected here |
|---|---|---|
| `#/drive` | Drive › Dash | `#/live`, `#/` |
| `#/drive/car` | Drive › Car | none |
| `#/drive/radio` | Drive › Radio | `#/radio` (**must keep working**: `docs/radio-setup.md` and iPad bookmarks use it) |
| `#/review` | Review › Sessions | `#/sessions` |
| `#/review/s/:id` · `/laps` · `/compare` · `/coaching` | Session detail | `#/sessions/:id` |
| `#/review/progress[/:driverId]` | Progress | none |
| `#/review/engineer[?session=:id]` | Engineer | `#/engineer` |
| `#/setup` · `/connect` · `/drivers` · `/rig` | Setup | `#/connect`, `#/profiles`, `#/setup` → `#/setup/rig` |
| `#/settings` (`/ai`) · `/radio` · `/display` · `/system` | Settings | `#/settings`, `#/status` → `#/settings/system` |

Each area remembers its last sub-page in `localStorage` (inside try/catch; if storage is not available the area
opens on its first sub-page).

### 2.3 Navigation pattern

| Layout | Breakpoint | Primary nav | Sub-nav |
|---|---|---|---|
| **iPad landscape / Mac** | `min-width: 1000px` | **Left rail**, 80 px wide: 4 items of 72 px (icon 28 px plus label 13 px), driver avatar (48 px) and connection dot at the bottom | Segmented control in the page header (min height 44 px) |
| **iPad portrait / small laptop** | 700-999 px | Bottom tab bar, 64 px plus safe area | Segmented control |
| **Phone** | `< 700px` | **Bottom tab bar**, 4 items, 56 px plus `env(safe-area-inset-bottom)`. The label is always visible. | Horizontally scrollable pill row under a 48 px app bar (area title plus driver chip) |

- The rail sits on the left because landscape has width to spare and height is scarce. A top bar would take a row
  away from the numerals.
- **On Drive while on track** the rail and the status bar dim to 40 % opacity (P1: they recede). Any touch
  restores full opacity for 5 s. Hit targets keep their size.
- Every target is at least 44 × 44 CSS px. On Drive the targets are 56 px. The two pre-session actions (Start
  radio, Switch driver) are 64 px tall because they are pressed in gloves.
- The four icons are inline SVG, drawn for pitwall (a steering wheel, a stopwatch with a lap curve, a wrench, a
  gear). No icon font and no external request.

---

## 3. Area overview (wireframes)

```
iPad landscape (rail)                                Phone portrait (tab bar)
+--------+-----------------------------------+       +------------------------+
| (logo) | page header + segmented sub-nav   |       | Drive             (JR) |  app bar 48
|        |                                   |       | [Dash] Car  Radio      |  pill row 44
| DRIVE  |                                   |       |                        |
| REVIEW |          page content             |       |      page content      |
| SETUP  |                                   |       |                        |
| SETTNG |                                   |       +------------------------+
|        |                                   |       | Drive Review Setup Set |  tab bar 56
|  (JR)  |                                   |       |   ^                    |  + safe area
|   *    |                                   |       +------------------------+
+--------+-----------------------------------+
 80 px rail: 4 items x 76 px, driver avatar and connection dot at the bottom
```

---

## 4. Drive › Dash: iPad landscape

### 4.1 Target devices and why the sizes are what they are

| Device | CSS viewport (landscape, home-screen app) | mm per CSS px |
|---|---|---|
| iPad 10th gen / iPad Air 11" | 1180 × 820 | 0.192 |
| iPad Pro 11" | 1210 × 834 | 0.192 |
| iPad Pro 13" | 1376 × 1032 | 0.192 |
| iPad mini | 1133 × 744 | 0.156 |
| Same, in Safari with toolbars | about 60-70 px less height | none |

**Baseline: 1180 × 820.** Every size below is the value at that baseline. Sizes scale with `clamp()` on viewport
height (section 5.3), so the iPad mini and Safari-with-toolbars still fit, and the 13" gets bigger numerals.

**Readability at 70 cm.** In-vehicle display guidance (ISO 15008) asks for characters of about 20 arcmin
minimum, 24 preferred. At 700 mm, 24 arcmin is a 4.9 mm cap height, which is about **36-40 px** of condensed type
on a 264-ppi iPad. The rules:

- Anything you read **while moving** is ≥ 40 px. The delta is 172 px: its digits are about 23 mm tall, about
  1.9° of view.
- Labels (`DELTA`, `S1`, `LAST`) are 18 px. They are read once and learned by position, never read while driving.
- **iPad mini** (smaller pixels): Settings › Display › Drive text size **Large** scales the Drive tokens by
  1.2. The Drive screen suggests it once when it detects a 1133 × 744 viewport.

### 4.2 Layout grid (on track)

```
 1180 × 820  (rail 80 + content 1100, padding 20, gaps 12)
┌──────┬───────────────────────────────────────────────────────────────────────────────┐
│      │ STATUS BAR                                                             56 px  │
│      │ ● LIVE  Austria · Practice · F1 25        "Lap 7 …" (radio)   ◉ RADIO  ☾  JR  │
│      ├────────────────────────────────────────────────┬──────────────────────────────┤
│ RAIL │ DELTA HERO                         7fr ≈ 609px │ NEXT CORNER        5fr ≈ 435 │
│  80  │  DELTA · REF L5 1:06.412                       │ NEXT CORNER        ◆ FOCUS   │
│      │                                                │ T9  ↱                        │
│      │        −0.21                      (172 px)     │ Rindt Kurve                  │
│      │                                                │ ▮▮▮▮▮▮▮▯▯▯  BRAKE MARKER     │
│      │  ◀━━━━━━━━━━━━━━━━┃            ▶               │ 285 m                        │
│      │  −1.0    AHEAD     0     BEHIND    +1.0  ⌄     │ Ref apex 150 km/h · early 3/5│
│      ├──────────────┬────────┬────────┬────────┬──────┴──────┬───────────────────────┤
│      │ LAP 8        │ S1 BEST│ S2   PB│ S3   ▸ │ LAST        │ BEST                  │
│      │ 0:55.2       │ 17.198 │ 29.087 │   -    │ 1:06.701    │ 1:06.412       148 px │
│      ├──────────────┴────────┴────────┴────────┴─────────────┴───────────────────────┤
│      │ LAP STRIP |S1━━━━━━|S2━━━━━━━━━━━━|S3━━━━━━━━━| T1 T3 T4 T6 T7 ▲T9 T10  64 px │
└──────┴───────────────────────────────────────────────────────────────────────────────┘
```

```css
/* Drive › Dash, iPad landscape (sketch, the real values live in tokens.css) */
.dash {
  display: grid; height: 100dvh; padding: 20px; gap: 12px;
  grid-template-columns: 7fr 5fr;
  grid-template-rows: 56px minmax(0, 1fr) 148px 64px;   /* hero ≈ 476 px at 820 high */
  grid-template-areas: "status status" "delta next" "timing timing" "strip strip";
  background: var(--bg-0);
}
.timing { grid-template-columns: 1.5fr repeat(3, 1fr) 1.15fr 1.15fr; }
@media (max-width: 999px), (orientation: portrait) {         /* iPad portrait, phone landscape */
  .dash { grid-template-columns: 1fr; grid-template-rows: 48px auto auto auto 56px;
          grid-template-areas: "status" "delta" "next" "timing" "strip"; }
}
```

### 4.3 What each panel shows (and from which data)

**Status bar (56 px, `--text-2`, dims while on track)**

| Element | Size | Source | Unknown / edge cases |
|---|---|---|---|
| Connection pill `● LIVE` / `STALE 8 s` / `NO DATA` / `NO LINK` | 18 px caps, pill 36 px | `snap.connection.status`, `last_packet_age_s`, `live.connected` | `NO LINK` when the WebSocket is closed |
| `SYNTHETIC` (hatched) / `REPLAY` chip | 18 px | `connection.synthetic`, `connection.source` starts with `replay` | Always shown when true (P8) |
| Track · session type · game | 22 px | `session.track_name`, `session_type`, `game` | `-` for an unknown track. The car name is omitted on Dash (it can be a team name, and it lives on Car). |
| Latest radio message (shown for 8 s) | 22 px, one line, ellipsis | radio store `current` | Hidden when the radio is off |
| Radio pill `◉ RADIO LIVE` / `RADIO OFF` | 56 px target | radio store `conn`, `mic` | Tapping it opens Drive › Radio |
| Night dim toggle ☾ | 56 px target | client setting | See section 5.6 |
| Race position `P5` (race sessions only) | 22 px | `frame.race_position` | Hidden outside races, `-` when null |

**Delta hero (the focal metric)**

| Element | Spec | Source |
|---|---|---|
| Label | `DELTA · REF L5 1:06.412` 18 px `--text-3`. For beginners (skill level from the driver profile) it reads `VS YOUR TARGET LAP · 1:06.412` | `snap.reference.lap_number`, `lap_time_ms` |
| Number | `−0.21` **172 px**, weight 700, tabular. U+2212 minus for ahead, `+` for behind, `±0.00` inside ±0.005 s. 2 decimals, re-rendered at most 10 times a second so the last digit does not flicker. Colour: `--ahead` (green) when below −0.005, `--behind` (red) when above +0.005, `--text-1` otherwise. | `snap.delta_s` |
| Word | `AHEAD` / `BEHIND` 22 px caps next to the bar centre (P4) | sign of `delta_s` |
| Bar | 28 px tall, full panel width, centre tick. It fills **left** from the centre when ahead and **right** when behind. Scale ±1.0 s, clamped, with an overflow chevron at the end. | `delta_s` |
| Trend chevron | small ⌄ / ⌃ (gaining / losing) from the slope of `delta_s` over the last 2 s of snapshots. Hidden while there are fewer than 2 s of samples. | client history of `delta_s` (derived, not invented) |
| Unknown / invalid | `-` in `--text-3` with one reason line (24 px): "No reference lap yet: drive one clean lap", "Out lap". **Invalid lap:** the number stays, because it is a real measurement, but it is drawn in `--text-2` with no green/red, and the reason line reads "This lap will not count". | `reference == null`, `delta_s == null`, `frame.lap_invalid` |

**Next corner**

| Element | Spec | Source |
|---|---|---|
| Which corner | The first corner in the learned model whose `apex_m` is after `frame.lap_distance_m` (wrapping at the line). It stays on a corner until you pass its apex, then moves on. Deterministic, O(n) over at most about 20 corners. | `snap.track_model.corners`, `frame.lap_distance_m` |
| Corner id | `T9` **112 px** plus a direction glyph (64 px SVG arrow, right or left) | `cornerLabel(model, name)`, `corner.direction` |
| Official name | `Rindt Kurve` 40 px. Shown **only** when the hand-verified track sheet maps it (`corner_text[name].long`). Never guessed. Sponsor names follow the sheet. | `track_model.corner_text` |
| Distance | When a cue is planned for this corner: `BRAKE MARKER` label plus `285 m` (44 px) and a draining bar (16 px) from 400 m down to 0. Otherwise `IN 340 m` to `entry_m`. | `snap.cues.next.corner` / `in_m`. Otherwise `corner.entry_m − lap_distance_m` |
| Context line | `Ref apex 150 km/h` and, for focus corners, the cue plan's reason (for example "braking early · 3 of the last 5 laps") at 24 px `--text-2` | `corner.ref_min_speed_kph`, `cues.focus`, the cue spec's `reason` |
| Focus tag | `◆ FOCUS` in accent orange when the corner is in `cues.focus` | `cues.focus` |
| Unknown | No track model yet: the panel shows `-` and "Corners appear after the first clean lap" (24 px) | `track_model == null` |

The panel never shows a "brake now" flash (P6). When the bar reaches 0 it simply empties. The radio says the word.

**Timing strip (148 px)**

| Cell | Spec | Source |
|---|---|---|
| LAP | label `LAP 8` (`LAP 8 / 20` in a race), running clock `0:55.2` **56 px**, tenths while running. When the lap completes, the cell shows the final `1:06.218` to the millisecond in its timing colour for 6 s, then the clock resumes. An invalid lap shows `INVALID` under the clock in `--danger` and the colours stop. | `frame.lap_number`, `session.total_laps`, `current_lap_time_ms`, `lap_invalid`, `laps[0]` |
| S1 / S2 / S3 | `17.198` **44 px** with a 6 px coloured top bar and a micro-label (`BEST` for purple, `PB` for green). The current sector has a 2 px `--text-1` outline and `▸`. Future sectors show `-`. | **Current lap: [needs backend B1]**. Until B1 lands, the cells show the **last completed lap's** sectors under a `LAST LAP` caption: `laps[0].sector_times_ms` (exact game values). The current sector is still marked from `frame.sector`. |
| LAST | `1:06.701` 40 px, coloured like a completed lap | `frame.last_lap_time_ms` |
| BEST | `1:06.412` 40 px, purple when it is the session best | min of clean `laps[].lap_time_ms` |

**Timing colours (purple / green / yellow).** F1 timing means purple = fastest of anyone, green = the driver's own
best, yellow = no improvement. With a single car on track and a family of drivers, Direction A maps them like this:

| Colour | Tier 1: client-only, ships first | Tier 2: [needs backend B2] |
|---|---|---|
| **Purple** `BEST` | fastest of that sector or lap **in this session** | **record**: fastest any family driver has done at this game + track + car (real sessions only) |
| **Green** `PB` | not used in Tier 1 (in a single-driver session it is the same as purple) | this driver's **personal best** (all sessions), but not the record |
| **Yellow** | completed, slower than the session best | completed, slower than the driver's PB |
| no colour, `-` | not reached, unknown, or invalid lap | same |

Invalid laps and laps flagged `flashback`, `pit_in`, `pit_out`, `paused`, `stale_data` or `distance_jump` are
never coloured purple or green. They show their time in `--text-2` with the flag word.

**Lap strip (64 px)**: a linear lap, more glanceable than a map

- 0 m to `track_length_m`. The three sector spans come from `snap.skeleton.sectors` (game-native). This lap's
  completed sectors are tinted in their timing colour, the current sector in `--surface-3`, and later sectors in
  `--surface-2`. Sector identity (S1/S2/S3) is shown by ticks and labels, **not** by the red/blue/yellow
  `SECTOR_COLOURS` used today, because those collide with timing yellow (P3).
- Corner ticks with short labels (16 px) from `track_model.corners[].apex_m`. The next corner's label is
  `--text-1`, the others `--text-3`.
- Car marker: a 14 px accent-orange triangle at `lap_distance_m`.
- The next cue's braking zone is a short orange segment at the cue target.
- Live marshal yellow zones are hatched `--flag-yellow` over their `segments_m` (same rule as today: live flags
  only, `marshal_flags`).

### 4.4 States

The state is a **pure function** `driveState(snapshot, wsConnected, now)` in `web/src/drive/driveState.ts`, unit
tested. Priority order (the first match wins):

| # | State | Detected from | What the screen does |
|---|---|---|---|
| 1 | **Link lost** | `!live.connected` | Status pill `NO LINK` in `--danger`. Every live value becomes `-`, because we can no longer vouch for it. Session context (track, driver) stays. A banner reads "Reconnecting to pitwall…" with the retry countdown. |
| 2 | **No data** | `connection.status == "no_data"` | Hero: `WAITING FOR TELEMETRY` (56 px). A 3-step checklist from `/api/connect` (listening port, game setting path from the guide, last sender seen). Buttons: **Open Connect** (64 px) and *Demo replay* (goes to Settings › System). Every timing cell shows `-`. |
| 3 | **Session ended** | an event of kind `session_ended` or `chequered_flag` in `snap.events` for this `session_id` **[B5 makes this server-side]** | Hero: `SESSION COMPLETE`. Shows the best lap (purple if it is a session or Tier-2 record), laps and clean laps, the gain from the first clean lap to the best, the single top coaching point (the first non-positive observation by priority), and a 64 px button **Review this session** → `#/review/s/:id`. |
| 4 | **Red flag** | a `red_flag` event | A full red band (`--flag-red`, white text 56 px `RED FLAG`). Delta hidden. |
| 5 | **Stale** | `connection.status == "stale"` | Values dimmed to 35 % opacity and stamped `PAUSED? NO DATA FOR 8 s`. The values are the **last known** ones and are labelled as such. |
| 6 | **Pit lane** | `frame.pit_status == 1` | The hero becomes `PIT LANE` plus speed vs limit: `78 / 80 km/h` (172 px speed, green under the limit, red over it). Limit from `skeleton.pit_speed_limit_kph`. If unknown, the limit shows `-` and the speed stays neutral. |
| 7 | **In pit / garage, after a run** | `frame.pit_status == 2` and `laps.length > 0` | Stationary means time to read (P7). Hero: the last lap's time and its delta. Right panel: **one thing for the next run**, the top observation text at 28 px. Timing strip unchanged. |
| 8 | **Pre-session** | session known, `laps.length == 0` and (`pit_status == 2` or speed < 1 km/h) **[B3 makes this exact]** | The "Ready" card: the driver in the seat (large avatar plus **Switch driver** 64 px), reference (`L5 1:06.412 · today` or "none yet"), cue mode and focus corners (`cues.mode`, `cues.focus`), radio state with **Start radio** (64 px: unlocks audio and the mic and takes the wake lock, the existing `radio.goLive()`). Track length and sector lengths from `skeleton`. |
| 9 | **On track** | otherwise | As in 4.2. |

Banners **overlay** the status bar row on track (they never move panels, P2) and go away when they clear:

| Banner | Trigger | Look | ARIA |
|---|---|---|---|
| `YELLOW · S2 · ZONE 7` | any `marshal_flags[].flag == "yellow"`. The sector is derived from the zone's `start_m` and `skeleton.sectors`. | `--flag-yellow` band, black text 28 px, hatched zone on the lap strip | `aria-live=polite` |
| `SAFETY CAR` / `VIRTUAL SAFETY CAR` / `FORMATION LAP` | `session.safety_car_status` in `full`, `virtual` or `formation_lap` | `--flag-sc` band. Adds "cues paused" when `cues.muted` | polite |
| `LAP INVALID` | `frame.lap_invalid` | `--danger` text in the LAP cell plus a thin red underline on the status bar. **No reason is shown** because the game does not tell us one. | polite |
| `CONTACT` | a `collision` event in the last 10 s | `--danger` band for 4 s, then gone | polite |

### 4.5 Drive › Car and Drive › Radio

- **Car** (glanceable while stationary, readable when parked): the current `LiveView` panels in the new style.
  Speed and gear, pedals and steering, rpm bar, tyres (four-corner grid FL FR / RL RR, surface temperature 32 px in
  its band colour, inner temperature, pressure, wear, brake temperature), fuel and ERS, the 12 s input trace (uPlot),
  the full track map with the live car and marshal flags, a lap timing tower (10 rows), and the latest coaching.
- **Radio**: the current `RadioView` stage (Go live, PTT, Radio check, Stop talking, mic meter, status chips, radio
  log). Its settings panel moves to Settings › Radio & voice.

### 4.6 Phone (Drive)

The phone is mostly for watching someone else drive (a parent watching a child) and for review. Portrait,
single column: status 48 · delta (`clamp(88px, 26vw, 120px)`) · next corner (id 64 px, name 28 px, distance
36 px) · a 3-cell sector row (32 px) · LAP / LAST / BEST row (28 px) · lap strip 48 · tab bar 56. Phone landscape
uses the iPad grid with the compact token scale.

---

## 5. Visual system

### 5.1 Colour tokens (dark first)

Contrast is measured against `--bg-0` (#050608) and `--surface-1` (#11151b), WCAG 2.x.

| Token | Dark | vs bg-0 / surface-1 | Light | vs white | Use |
|---|---|---|---|---|---|
| `--bg-0` | `#050608` | none | `#f5f6f8` | none | Drive background (near-black, little glare in a dim room) |
| `--bg-1` | `#0b0e12` | none | `#eceff3` | none | App background |
| `--surface-1` | `#11151b` | none | `#ffffff` | none | Panels |
| `--surface-2` | `#171c24` | none | `#eceff3` | none | Raised, selected segment, future sectors |
| `--surface-3` | `#222a35` | none | `#dfe4eb` | none | Current sector on the lap strip |
| `--line` | `#252c37` | none | `#d9dee6` | none | Hairlines (1 px) |
| `--text-1` | `#eef1f5` | 17.9 / 16.2 | `#0d1117` | 18.9 | Values |
| `--text-2` | `#a9b2bf` | 9.5 / 8.6 | `#4a5463` | 7.7 | Secondary values |
| `--text-3` | `#7c8696` | 5.5 / 5.0 | `#5f6977` | 5.6 | Labels, `-` |
| `--accent` | `#ff6a2b` | 7.1 / 6.4 | `#c2410c` | 5.2 | Pitwall orange: car marker, focus, primary button |
| `--t-best` (purple) | `#c58cff` | 8.3 / 7.5 | `#6d28d9` | 7.1 | Record / session best |
| `--t-pb` (green) | `#2fe37f` | 12.0 / 10.8 | `#047857` | 5.5 | Personal best |
| `--t-slower` (yellow) | `#ffd23f` | 14.0 / 12.7 | `#8a5a00` | 5.9 | Completed, no improvement |
| `--ahead` | = `--t-pb` | 12.0 | `#047857` | 5.5 | Delta below 0 |
| `--behind` | `#ff5466` | 6.5 / 5.9 | `#c81e3a` | 5.7 | Delta above 0, over the pit limit |
| `--live` / `--ok` | `#2fe37f` | 12.0 | `#047857` | 5.5 | Connection live |
| `--warn` | `#ffb020` | 11.1 / 10.0 | `#9a5b00` | 5.4 | Stale, warnings |
| `--danger` | `#ff5466` | 6.5 | `#c81e3a` | 5.7 | Link lost, invalid, contact |
| `--info` / `--ref-trace` | `#4cc3ff` | 10.2 / 9.2 | `#0369a1` | 5.9 | Reference trace, info |
| `--flag-yellow` | `#ffd23f` band, `#0d1117` text (13.1) | none | same | none | Marshal yellow |
| `--flag-sc` | `#ffb020` band, `#0d1117` text | none | same | none | Safety car |
| `--flag-red` | `#ff3347` band, `#ffffff` text | none | same | none | Red flag |
| `--synthetic` | `#ff7ac0` plus 45° hatch | 8.5 | `#be185d` | none | Synthetic chip (purple is no longer used for it: P3) |
| `--throttle` / `--brake` | `#2fe37f` / `#ff5466` | none | `#047857` / `#c81e3a` | none | Input traces (Car, Compare) |

- **Light theme** is kept. Timing colours become **filled chips** there, because coloured text on white is too
  weak: purple `#6d28d9` with white text (7.1:1), green `#047857` with white (5.7:1), yellow `#ffd23f` with
  `#0d1117` (13.1:1).
- **Colour-vision mode** (Settings › Display › "Red-green safe"): `--ahead`/`--t-pb`/`--live` become `#4cc3ff`
  and `--behind`/`--danger` become `#ff9f1c`. The P4 redundancy (signs, bar direction, `BEST`/`PB`/`INVALID`
  words) is always on in both modes.
- **Legacy aliases** keep the existing views working during migration: `--bg → --bg-1`, `--panel → --surface-1`,
  `--panel-2 → --surface-2`, `--border → --line`, `--text → --text-1`, `--muted → --text-2`, `--faint → --text-3`,
  `--gain → --ahead`, `--loss → --warn`, `--bad → --danger`, `--best → --t-best`, `--ref → --info`.

### 5.2 Typography

| Role | Face | Notes |
|---|---|---|
| **Numerals and labels** (timing) | **Barlow Semi Condensed** 500/700, self-hosted woff2 in `web/public/fonts/`, Latin subset (about 25 KB per weight), SIL OFL 1.1 (add it to `docs/licences.md`) | Condensed, DIN-like, original. Not the F1 broadcast face. `font-variant-numeric: tabular-nums` on every number (check `tnum` survives the subset). Fallback stack: `"DIN Condensed", "Roboto Condensed", "Arial Narrow", system-ui`. |
| Body text (Review sentences, Settings) | `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` | Best readability for paragraphs. No download. |
| Code / IDs | `ui-monospace, "SF Mono", Menlo, monospace` | Fact IDs, capture names |

Labels: caps, `letter-spacing: .08em`, weight 600, `--text-3`. Numbers never use caps spacing.

### 5.3 Type scales

**Drive scale** (glance). Values at the 1180 × 820 baseline. ×1.2 with the "Large" setting.

| Token | Baseline | Definition | Used for |
|---|---|---|---|
| `--d-hero` | 172 px | `clamp(88px, min(21vh, 26vw), 220px)` | Delta, pit speed |
| `--d-xl` | 112 px | `clamp(64px, 13.6vh, 140px)` | Corner id |
| `--d-l` | 56 px | `clamp(40px, 6.8vh, 72px)` | Lap clock, state titles |
| `--d-m` | 44 px | `clamp(32px, 5.4vh, 56px)` | Sector times, distance to the brake marker |
| `--d-s` | 40 px | `clamp(28px, 4.9vh, 48px)` | Corner name, LAST, BEST |
| `--d-xs` | 24 px | `clamp(20px, 2.9vh, 28px)` | Context lines, reasons (read when stationary) |
| `--d-label` | 18 px | `clamp(15px, 2.2vh, 22px)` | Labels |

**App scale** (Review / Setup / Settings, read up close; the base goes up from 14 to 16 px):
12 (chart axes only) · 14 (captions) · **16 body**, line-height 1.5 · 20 section titles · 24 page titles ·
32 KPI values · 48 KPI hero.

### 5.4 Spacing, shape, elevation

- Spacing scale 4 · 8 · 12 · 16 · 20 · 24 · 32 · 40 · 48 · 64 (`--s-1` … `--s-10`). Drive uses 12 between
  panels and 20 inside them.
- Radii: `--r-cell: 2px` (timing cells: square, the timing-screen signature), `--r-panel: 6px`,
  `--r-pill: 999px`.
- No shadows and no blur on Drive (`backdrop-filter` costs frame time in iPad Safari). Elevation comes from surface
  steps and 1 px hairlines. Panels use `contain: layout paint`.
- Timing cells have a **6 px coloured top bar** (the "tab"). This is the most recognisable element of the look.

### 5.5 Components

| Component | Purpose | Key spec |
|---|---|---|
| `TimingValue` | Any time or number with state | `value`, `state: best\|pb\|slower\|invalid\|neutral\|unknown`, `size` token. Renders `-` for null. Tabular. |
| `TimingCell` | Sector, lap or last/best cell | Top bar (6 px), label (18 px), micro-label (`BEST`/`PB`), `TimingValue` |
| `DeltaHero` | Focal delta | Number, word, bar, chevron, reason line |
| `NextCorner` | Next corner | Id, direction glyph, official name, distance bar, context line, focus tag |
| `LapStrip` | Linear lap | Sectors, corner ticks, car marker, cue zone, yellow zones |
| `StatusBar` / `FlagBanner` | Context / interruptions | Banners take over the status row (P2) |
| `StatePanel` | No data / pre / pit / ended | Title (`--d-l`), 1-3 lines, one or two 64 px actions |
| `NavRail` / `TabBar` / `SubNav` | Navigation | Section 2.3 |
| `DriverChip` (existing) | Who is in the seat | Unchanged behaviour, restyled |
| `CoachingCard` | One observation | Corner (official name), observation text, evidence, Ask button (6.3) |
| `KpiTile` | Review summary numbers | Label 14 · value 32 · context 14 |
| `TimingTower` | Lap or session list | Rows 48 px (56 px on touch), alternating `--surface-1`/`--bg-1`, coloured time cells |
| `Chart` (uPlot, existing) | Traces and progress | Tokens for grid and axes. Reference trace `--info`, compared lap `--text-1` |
| `Badge` | `SYNTHETIC`, `REPLAY`, `CLEAN`, flags | Synthetic is hatched |

### 5.6 Motion, brightness, accessibility

- Drive animations: only the bar fills (≤ 100 ms linear) and a single 600 ms fade when a sector completes. Nothing
  flashes (WCAG 2.3.1). `prefers-reduced-motion` turns the fade off.
- **Night dim** (☾ on Drive, remembered per device): `--text-1` drops to `#c9cdd3`, `--bg-0` becomes `#000`, and
  timing colours lose 15 % lightness. Contrast stays ≥ 7:1 for the hero. For a dark room, together with iPad
  brightness.
- Screen reader: `DeltaHero` has an `aria-label` such as "0.21 seconds ahead of reference lap 5". Banners use
  `aria-live`. Focus ring: 2 px `--accent`, offset 2 px. Each area's page header has its own `h1`.
- Home-screen web app: add a small `manifest.webmanifest` (`display: standalone`, `orientation: landscape`) and
  `apple-mobile-web-app-capable`. Drive then gets the full 820 px of height with no Safari chrome. Static and
  offline, no service worker needed.

---

## 6. Review area

### 6.1 Sessions (timing-tower list)

```
REVIEW  [Sessions] Progress  Engineer                            filter: (Everyone) (JR) (S) (A)
┌──────────┬────┬────────────────┬───────────┬──────┬────────────┬──────────────┐
│ Today    │ JR │ Austria        │ Practice  │ 12/8 │ 1:06.412 ◆ │ −0.384 vs PB │  ◆ = purple: new PB
│ Today    │ S  │ Austria        │ Time trial│ 8/6  │ 1:09.880   │ +0.122 vs PB │
│ Yesterday│ JR │ Austria        │ Race      │ 20/17│ 1:06.796   │ -            │
│ 2 Oct    │ A  │ Austria ▨SYNTH │ Practice  │ 10/10│ 1:05.900   │ not counted  │  ▨ = hatched, never a PB
└──────────┴────┴────────────────┴───────────┴──────┴────────────┴──────────────┘
```

- Grouped by day. Rows are 56 px on touch, and the whole row is the target. Columns: when, driver avatar (existing
  reassign select kept on wide screens and moved into the session header on phones), track, session type,
  laps / clean laps, best clean (purple when it was a PB at that point), Δ vs the driver's previous best at that
  track (computed from the loaded sessions list. Exact with **B4**. `-` when there is no earlier session). Synthetic
  and replay rows are hatched and never count towards PBs (this matches `repo.py`).
- Phone: two-line rows (track + best on line 1; driver, type, laps, when on line 2).

### 6.2 Session › Summary ("the story of the session")

Written for a beginner. Every number has a plain-words label, and a `?` opens a one-line glossary.

```
Austria · Practice · Today 18:40 · JR in the seat · F1 25 · PS5                [Ask the engineer]
┌──────────────┬──────────────┬──────────────────┬──────────────────────┐
│ BEST LAP     │ CLEAN LAPS   │ GAINED TODAY     │ STEADIEST CORNER     │   KpiTile x4
│ 1:06.412 ◆PB │ 8 of 12      │ −1.284 s         │ T1 ±2.1 m braking    │
│ lap 5        │ 4 not used ? │ first clean→best │ spread ?             │
└──────────────┴──────────────┴──────────────────┴──────────────────────┘
 LAP TIMES  ▁▃▂▅▆█▇▆▇█▇█  (bars per lap; not-clean laps hatched; reference line)       uPlot
 WHERE THE TIME IS  (average vs your reference, across 8 laps)
   T9  Rindt Kurve   ████████ +0.12 s   braking ~12 m early
   T3                █████    +0.07 s   lower minimum speed
   T1  Niki Lauda K. ▏        −0.01 s   on par
 COACHING POINTS (top 3, from the coach)                         WENT WELL
   [T9] "T9: you're braking about 12 m earlier than …"           [T6] "T6: good - exit speed …"
 [Compare laps]  [See all coaching]  [Session report]  [Pin lap 5 as reference]
```

| Block | Source (exists today) |
|---|---|
| Best lap, clean count | `/api/sessions/:id` laps (`clean`, `lap_time_ms`, `flags`) |
| Gained today | first clean lap time minus best clean lap time (derived) |
| Steadiest corner | the lowest `brake_point_std_m` in `analysis.corner_summary` (with ≥ 3 laps) |
| Lap times chart | laps. Not-clean laps hatched with their flag in the tooltip. Reference lap line. |
| Where the time is | `corner_summary[].mean_time_delta_s`, sorted. Detail words from `mean_brake_point_delta_m` / `mean_min_speed_delta_kph` with signs only, no advice (P9) |
| Coaching points | `analysis.observations`, non-positive, sorted by `priority` (as `core/report.py` does) |
| PB marker | Tier 1: best of the driver's sessions at this track in the loaded list. Exact with **B4**. |

"Not used" explains flags in plain words: *flashback*, *pit in/out*, *paused*, *invalid (game)*,
*incomplete*, *standing start*, *jump in lap distance*.

### 6.3 Session › Coaching

One `CoachingCard` per observation, grouped by corner and ranked by priority, with positives in their own "Went
well" column.

```
┌ T9 · Rindt Kurve · right-hander ────────────────────────────── costs 0.12 s a lap ┐
│ T9: you're braking about 12 m earlier than your reference (lap 5),                │
│ losing 0.12 s through the corner.                                                 │
│ Seen on 3 of your last 5 laps · confidence: high                                  │
│ [speed trace of this corner: lap 8 vs reference, 400 m window]  [Ask the engineer]│
└───────────────────────────────────────────────────────────────────────────────────┘
```

- The text is the coach's own (`observation.text`). Simpler wording for beginners exists today only on the radio
  (`simple_wording` in `voice/proactive.py`). A plain-words variant for cards belongs in the coach **[B6]**, never
  in the UI. The UI adds **no** advice (P9).
- Confidence in words: ≥ 0.8 high, 0.6-0.8 medium, < 0.6 low. The numeric value stays in a details disclosure.
  This is a display rule, documented on the card's `?`.
- The mini trace slices `/api/laps/:id/trace` for both laps to the corner's `seg_start_m … seg_end_m` (uPlot,
  speed plus brake). Incident observations ("that looks like an incident") are shown greyed with "not used for
  technique advice".
- Beginner profiles show the top `coaching.max_per_lap` cards first, with "show all" below. The limits are the
  driver's own coaching limits from `/api/drivers`.

### 6.4 Session › Laps and Compare

- **Laps**: timing tower (lap, time, S1-S3 coloured per Tier 1/2, Δ ref, status words). Tap a row to choose
  **Compare**. Long-press (or a ⋯ button) opens *Use as reference / Pin as reference* (existing
  `POST /api/references`).
- **Compare**: two large selectors at the top (`REFERENCE L5 1:06.412` / `COMPARED L8 1:06.218`), each opening a
  sheet with the timing tower. Then: the delta-by-distance chart with sector bands (`SectorBands` + `Chart`,
  existing), the track map coloured by corner delta (existing `segmentDelta`), the speed / throttle / brake /
  steering charts synced on one cursor (existing), and the corner table (Δ time, brake point, minimum speed, exit
  speed, full throttle). Compatibility warnings stay prominent (`comparison.compatibility`).
- Phone: corner table first (it is what you act on), then the delta chart. The raw traces sit behind
  "Show telemetry".

### 6.5 Progress (per driver, over time)

```
REVIEW  Sessions [Progress] Engineer          driver: (JR) (S) (A)   track: [Austria ▾]
 BEST CLEAN LAP PER SESSION                                    1:10 ┤•
                                                               1:08 ┤   •  •
 PB ◆ 1:06.412 (today)                                         1:06 ┤          •  ◆
                                                                    └──────────────── date
 FAMILY BOARD · Austria · F1 25                 CORNERS OVER TIME   [needs B4]
  ◆ JR  1:06.412                                  T9  ▇▆▅▃▂  getting closer (−0.08 s)
    S   1:09.880   +3.468                         T3  ▃▃▄▃▃  steady
    A   -          no clean lap yet
 HABITS [needs B4]: "braking early at T9": 3 of 5 laps → 1 of 6 laps
```

| Block | Tier 1 (data today) | Tier 2 |
|---|---|---|
| Best clean lap per session over time | `/api/drivers/:id/sessions` → `best_clean_ms`, `started_unix`, `track_id`, `synthetic` (synthetic excluded by default, with a toggle) | B4 adds median clean lap and spread per session |
| Current PB | `driver.stats.best_laps` (track, time, `set_unix`) | B4: PB history (each improvement) |
| Family board | every driver's `stats.best_laps` for the track. Gap to the leader. Purple for the record. | none |
| Corners over time | not shown in Tier 1 | B4: per corner, mean Δ vs the current reference per session |
| Habits | not shown in Tier 1 | B4: count of observation kinds per corner per session |
| Totals | `stats.sessions`, `laps`, `clean_laps`, `tracks` | none |

The beginner framing: "Getting faster?" (best lap trend), "Getting steadier?" (spread, Tier 2), "What changed?"
(habits, Tier 2). Every chart carries one sentence of computed fact ("Your best here dropped 1.3 s over 4
sessions"). The sentence is computed, never an LLM.

### 6.6 Engineer

Today's chat, inside Review, with the session pre-selected from wherever you came from. The "How answers work"
and model status move to a collapsible side panel. Suggestion chips become 44 px pills. Fact citations stay.

---

## 7. Setup and Settings

**Setup** (getting ready to drive):

- **Checklist** (landing): four rows, each with a state dot and one action:
  1. **Game**: `/api/connect` telemetry status ("Receiving F1 25 from 192.0.2.30 · 60 packets/s" / "Listening on
     UDP 20777, waiting for the game") → *Connect*.
  2. **Driver**: who is in the seat → *Switch*.
  3. **Radio**: radio store state (link, mic, wake lock, HTTPS warning) → *Start radio*.
  4. **Rig**: last rig check counts (pass / warn / fail / unknown) → *Rig*.
  Then a 64 px **Open Drive** button.
- **Connect**: today's ConnectView (games, setup guides, live senders, open on another device). The status banner
  moves to the top.
- **Drivers**: today's ProfilesView (cards, seat, edit). Touch sizes already meet 44 px.
- **Rig**: today's SetupView (rig, recommendations, rig check, evidence labels).

**Settings** (configuring the app):

- **Engineer AI**: today's SettingsView (cloud / local model, fallback, test, usage, what gets sent).
- **Radio & voice**: the settings panel moved out of RadioView (voice on/off, device vs Mac voice, device voice,
  rate, coaching intensity, braking cue mode).
- **Display**: theme (Dark / Light / Match device), Drive text size (Standard / Large), Night dim default,
  colour vision (Standard / Red-green safe), "Dim navigation while on track" (on).
- **System**: today's StatusView (health, LLM, captures, replay, simulate, capability matrix) plus build version
  and licences.

---

## 8. Migration plan from the current views

Each phase can ship on its own, keeps `make check` and `npm run check` green, and is checked on the iPad before
the next one starts. Phases 1-3 change **only new files plus `App.svelte` and `app.css`**. Existing views are
wrapped, not edited, so they do not collide with the engineers working in `web/src/views` now.

| Phase | Scope | Files | Done when |
|---|---|---|---|
| **0 · Tokens and font** | `web/src/styles/tokens.css` (section 5 plus legacy aliases), self-hosted Barlow Semi Condensed, `docs/licences.md` entry, manifest | new files, `app.css` imports | Existing views look the same apart from the colour tweaks. Contrast checker script passes. |
| **1 · Shell and routes** | `Shell.svelte`, `NavRail`, `TabBar`, `SubNav`, `routes.ts` (table plus legacy redirects, last sub-page memory). Existing views mounted unchanged inside the 4 areas. Old Live becomes Drive › Car for now. | `App.svelte` plus `web/src/shell/*` | All 10 legacy hashes land on the right page. 44 px audit passes. Phone and iPad both navigable. |
| **2 · Drive › Dash** | `driveState.ts`, `timing.ts` (Tier 1 colouring), `nextCorner.ts`: **pure TS with unit tests** run by `node --test` (Node's built-in type stripping, no new dependency). Then `DeltaHero`, `NextCorner`, `TimingStrip`, `LapStrip`, `StatusBar`, `FlagBanner`, `StatePanel`. | `web/src/drive/*`, `web/tests/*` | Replay of the recorded Austria fixture reaches the on-track, pit, ended and stale states. Glance test on the rig (section 10). |
| **3 · Review** | Split `SessionView` into Summary / Laps / Compare / Coaching (reusing `Chart`, `TrackMap`, `SectorBands`). Restyle the sessions list. Progress Tier 1. Engineer moves. | `web/src/review/*` | A beginner (the family test) can say, from the Summary alone, what their best lap was and where they lost the most time. |
| **4 · Backend data** (Python, separate PRs with tests) | B1-B6 (section 9) | `adapters/f1`, `model/telemetry.py`, `core/live.py`, `storage/repo.py`, `api/*` | Tier 2 colours and Progress Tier 2 switched on. |
| **5 · Setup and Settings** | Checklist page, radio settings moved, Display settings (CVD, Night, Large) | `web/src/setup/*`, `web/src/settings/*` | Old RadioView and Status pages reachable only through redirects. |
| **6 · Clean-up** | Remove the legacy aliases once no view uses them. Rename the moved views. Update `docs/status.md` and `docs/architecture.md`. | none | `rg -- '--panel-2\|--muted'` finds nothing. |

### Where to build it (here or in the cloud)

**Do the UI upgrade here, in the local Mac session.** Hand only isolated pieces to cloud sessions.

- The working tree has **uncommitted** changes in `web/src` (`RadioView`, `ConnectView`, `radio.svelte.ts`) and in
  the voice backend. A cloud session sees only the pushed commits, so a cloud rewrite of the shell or of Drive
  would be built on stale files and conflict when merged.
- Drive can only be judged with the running service (`pitwall serve` plus replay or the PS5), on the iPad
  over Tailscale HTTPS at 70 cm in the real room light. Wake lock, audio unlock and the mic need the secure
  Tailscale origin. None of that exists in the cloud (`docs/cloud-tasks.md`).
- **Good cloud tasks** (self-contained, testable without the Mac): the backend additions B1-B6 (Python plus
  tests, synthetic and recorded tiers), the pure TS modules from phase 2 (`driveState.ts`, `timing.ts`,
  `nextCorner.ts`, with tests), and design iterations on this static mockup.

---

## 9. Data the UI needs that does not exist yet

All of it is deterministic, follows "unknown stays unknown", and is optional: the UI works in Tier 1 without it.

| Id | Addition | Why | Notes |
|---|---|---|---|
| **B1** | `frame.sector_times_ms: [s1, s2, null]` for the **current** lap, as the game reports them | Live sector colours on the current lap | F1 LapData already carries `sector1TimeMSPart` / `sector2TimeMSPart`. The adapter reads them at lap completion today. `None` for games that do not provide them (GT7, Forza). |
| **B2** | `snapshot.sector_bests` (static, every 5 s): `{session: [...], driver_pb: [...], record: {times: [...], driver_id}}` and `reference.sector_times_ms`, for game + track + car, real sessions only | Tier 2 purple / green / yellow semantics | Computed from stored laps. Synthetic and replays excluded (as for PBs today). |
| **B3** | `frame.driver_status` (`in_garage`, `out_lap`, `in_lap`, `flying_lap`, `on_track`) | Exact pre-session / out-lap state | F1 `DRIVER_STATUS` enum exists in `adapters/f1/enums.py`. `None` elsewhere. |
| **B4** | `GET /api/drivers/:id/progress?game&track_id[&car]` → per session: best clean, median clean, clean count, lap-time spread, per-corner mean Δ vs the current reference, observation-kind counts. Plus PB history. | Progress Tier 2 | Aggregates over existing tables. Read-only. |
| **B5** | `snapshot.session_state` (`running` / `ended` / `red_flag`) maintained server-side from events | Ended / red-flag states that do not depend on the last-10 event window | Small `LiveState` addition. |
| **B6** | `observation.text_simple`: a one-idea plain-words variant written by the coach for drivers whose limits set `simple_wording` | Beginner-friendly coaching cards in Review | Same facts and numbers as `text`, generated deterministically in `analysis/coaching.py` (the radio already does this in `voice/proactive.py`). |

---

## 10. Acceptance checks (on the rig)

1. **Glance test**: the iPad on its mount at about 70 cm, room lights as when racing. Within a 0.5 s glance the
   driver can say the delta's sign and first digit, and the next corner. Run it for each driver (adult, child).
2. **Contrast audit**: a script checks every token pair in section 5.1 (≥ 7:1 for Drive values, ≥ 4.5:1 for
   text, ≥ 3:1 for UI shapes).
3. **Target audit**: every interactive element ≥ 44 × 44, and Drive actions ≥ 56.
4. **Honesty audit**: with the game paused, unplugged and in replay, no screen shows a number that is not in the
   snapshot. `SYNTHETIC` is visible on a synthetic replay on every page.
5. **States**: the recorded Austria fixture, the synthetic coaching demo, and a live PS5 session together reach
   every Drive state in section 4.4.
6. **Beginner test**: another driver in the household (a beginner) opens Review › Summary for their own last session and explains their
   best lap and their biggest time loss without help.

---

## Appendix: Drive element → data map

| Element | Field(s) |
|---|---|
| Connection | `connection.status`, `last_packet_age_s`, `synthetic`, `source`. WebSocket `live.connected` |
| Delta | `delta_s`, `reference.{lap_number, lap_time_ms}` |
| Next corner | `track_model.corners[].{name, apex_m, entry_m, direction, ref_min_speed_kph}`, `track_model.corner_text`, `frame.lap_distance_m` |
| Brake marker | `cues.{mode, next.{corner, in_m}, focus, muted, reason}`, the cue plan's `reason` |
| Lap | `frame.{lap_number, current_lap_time_ms, last_lap_time_ms, lap_invalid, sector, race_position}`, `session.total_laps` |
| Sectors | `laps[0].sector_times_ms` (Tier 1). B1 / B2 later. |
| Lap strip | `skeleton.{track_length_m, sectors, marshal_zones}`, `marshal_flags`, `track_model.corners`, `frame.lap_distance_m` |
| Pit | `frame.pit_status`, `frame.speed_kph`, `skeleton.pit_speed_limit_kph` |
| Flags | `marshal_flags`, `session.safety_car_status`, `events[].kind` |
| Ended | `events[].kind` (`session_ended`, `chequered_flag`), `laps`, `observations` |
| Driver | `/api/drivers` (active, preferences, coaching limits) |
| Radio | radio store (`conn`, `mic`, `wake`, `current`) |
