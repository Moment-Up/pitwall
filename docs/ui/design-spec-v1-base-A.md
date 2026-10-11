# Pitwall UI: design spec v1 (base A) - SUPERSEDED

> **Superseded by [`design-spec.md`](design-spec.md) (v2, base C coach-first, React + HeroUI).** James preferred
> direction C; v1 used A as its base. Kept for the reasoning behind the decisions v2 carries over.

_2026-10-11. Status: **design, not implemented**. Synthesised from proposals A (timing screen minimal), B (pit wall
dense) and C (coach-first) and three judge reviews; all three judges picked A as the base. Clickable mockup:
[`mockup-v1-base-A.html`](mockup-v1-base-A.html) (self-contained, sample data only). The earlier proposals stay in this folder for the
reasoning behind each choice._

---

## 0. Summary

**Base: Direction A ("timing screen minimal").** Its Drive screen has one big delta, the next corner, a brake-marker
bar that empties, and square timing cells. It was the most glanceable of the three and the cheapest to build next to
the work already in progress. The best ideas from B and C are added to it, and the corner-name source is fixed.

| Topic | Final decision | From | Why |
|---|---|---|---|
| Drive focal point | 172 px delta, 2 decimals, rendered at most 10 times a second, `AHEAD`/`BEHIND`/`LEVEL` word, bar that fills left or right | A | The clearest number at 70 cm. The judges asked to drop A's trend chevron, so there isn't one |
| Delta colour | Neutral inside **±0.02 s**. Shows **`-` when stale** ("a frozen delta must never look current") | B | Stops the colour flickering around zero, and stops a stale value looking current |
| Next corner | Official label and name from **`track_model.corners[].label` / `display_name`**, never parsed from `corner_text.long` | judges | These fields are already in the live payload (`track_model_payload` → `to_dict(identity=True)`) |
| Braking cue | Cue kind chip (`BRAKE` / `MARKER`) plus distance and an emptying bar. Footer shows **last cue outcome** (`LAST T4 · ON TIME −3 m`). No red flash | B, A (P6) | Shows what the radio will say, without inviting a glance at the braking point |
| Timing colours | **Purple `REC`** = household record (needs D2). **Green `SB`/`PB`** = your best this session / all time. **Yellow** = slower. Purple is never faked | B, plus the F1 meaning of green | Purple never changes meaning between data tiers, and beginners in the household still earn green often |
| Colour timing | Drive cells are coloured **as set**. Tables are coloured by **current standing** | B | Instant feedback while driving, and "which lap had my best S2?" at a glance in tables |
| Status row | One fixed 56 px slot. **An outline means the data is in doubt** (stale, link lost). **A fill means the track says** (flags) | B | Nothing moves, and the two kinds of warning look different |
| Pre-session | "**James is in the seat** · Not you? Switch driver" Ready card (96 px avatar, 64 px button), target PB/REC, focus corners, Go live | C, A | The best protection against laps landing in the wrong profile on a three-driver rig |
| Radio on Drive | Radio pill in the status bar: **GO LIVE** when off; **hold to talk** when live. Latest message as a one-line ticker. The wheel button stays the main way to talk | C (compact) | No need to switch tab mid-session, and no extra row taken from the hero |
| Navigation | 4 areas: **Drive · Review · Setup · Settings**. 80 px rail on iPad and Mac, bottom tab bar on phone. Rail dims on track. **Drive lock** (hold 0.5 s to leave Drive on track) is on for beginner profiles | A, B | Reduces 10 tabs to 4, and stops a knee bump from swapping screens mid-lap |
| Dense view | **Drive › Car** is the dense pit wall (map, tyres, inputs, laps, coaching) for a spectator or second screen. It is never the driver's default | B | Keeps B's wall without putting it in the driver's peripheral vision |
| Review | Session **Summary** (B's Overview plus A's "story", with Work on and Went well), **Laps & compare** (one tab), **Corners** (coaching grouped by corner). Review › **Coaching** plan and **Progress** with "faster ↑" | B, C, A | Plain words for beginners, and the depth follows each profile's skill level |
| One message, two channels | **D6 `coach` block**: the screen shows the coaching point the radio picked under the seated driver's limits | C | Today `snapshot.observations` is unfiltered while the radio filters, so the two can disagree |
| Type | System condensed faces already on every Apple device (`DIN Condensed` numerals, `Avenir Next Condensed` labels). **Zero bytes to download.** Barlow Semi Condensed (OFL) is an optional fallback for non-Apple devices | revised | Measured on this Mac: both faces have tabular digits by default (section 6.3) |

**Here or cloud? Build the UI here, on the Mac.** The Drive screen only counts once it has been tried on the real
iPad at about 70 cm in the rig room. That needs live PS5 telemetry, the radio over Tailscale HTTPS (the mic and wake
lock need the secure origin), and the launchd service. A cloud session has none of these. It also sees only pushed
commits, and the working tree still has uncommitted work that the UI touches: the rig page (`SetupView.svelte`,
`rig.ts`) and the F1 adapter and telemetry model (`adapters/f1/adapter.py`, `model/telemetry.py`, which backend items
D1 and D3 also need), plus the new track-outline work (`api/routes_track.py`, untracked). **Send these to cloud
sessions once that work is committed and pushed:** the backend additions D1-D6 and the pure TypeScript logic modules
with their tests (lanes B, D and R in section 12). Each of them is self-contained and can be tested on recorded or
synthetic data.

**Decision needed first: which dashboard.** Commit `716468b` (2026-10-11 00:43) added `web-react/`, a React 19 +
HeroUI v3 + Tailwind dashboard served at `/next/`. Its README calls it "the successor to the Svelte dashboard in
`web/`". Only its Live page is ported so far. This spec follows the brief and targets `web/` (Svelte, no new
dependencies), but the design does not depend on the framework. The tokens, the route table, the Drive grid and
states, the pure `drive/logic/*.ts` modules and the backend work carry over unchanged, and section 13 maps every file
to its `web-react/` home. Building the shell in both would be wasted work.

---

## 1. Principles

| # | Rule | Consequence |
|---|---|---|
| P1 | **One focal number per screen.** On Drive it is the delta. Everything else is at least two sizes smaller and one brightness step lower | The eye lands in the same place on every glance |
| P2 | **Nothing moves while driving.** Panels are fixed slots. A state change swaps content inside a slot, never its size or position | A glance never has to search |
| P3 | **Each colour family has one job.** Purple, green and yellow mean timing. Red, amber, yellow, blue and cyan bands mean flags and state. Orange means "you" (your car, focus, primary action). Pink hatching means synthetic | Colour you can trust at a glance |
| P4 | **Colour is never the only signal.** Signs (`−` U+2212 and `+`), bar direction, the words `AHEAD`/`BEHIND`, the tags `REC`/`PB`/`SB`/`INV`, band words | Red-green colour blindness (about 1 man in 12), glare, night dim |
| P5 | **Unknown shows `-`.** No `0.000`, no `--:--.---`, no `—`. Stale values are dimmed and carry their age. A lost link blanks live values | "Unknown stays unknown", carried through to the UI |
| P6 | **The screen looks ahead and the radio does the timing.** No "BRAKE NOW" flash. The cue panel shows what is coming and empties a bar | Eyes stay on the road at the braking point |
| P7 | **Sentences only when stationary.** In the garage, pit lane or after the session, Drive can show the coach's sentence | Reading needs a stopped car |
| P8 | **Evidence tiers stay visible.** A hatched `SYNTHETIC` chip and a `REPLAY` chip appear on every screen that shows such data | Evidence-tier rule (CLAUDE.md) |
| P9 | **The UI adds no advice.** Coaching text is the deterministic coach's own (`analysis/coaching.py`) or the grounded engineer's. The UI formats it, ranks it and adds neutral descriptive words ("braked 12 m earlier"), never instructions | Coaching never recommends braking later on its own |
| P10 | **One message, two channels.** When D6 lands, the screen shows exactly the point the radio picked | The earpiece and the iPad never disagree |

---

## 2. Information architecture

### 2.1 Four areas

| Area | Sub-pages (sub-nav) | Answers | Replaces today |
|---|---|---|---|
| **Drive** | **Dash** (default) · **Car** · **Radio** | "How am I doing right now?" | Live, Radio |
| **Review** | **Sessions** (default) · **Coaching** · **Progress** · **Engineer**. A session opens with **Summary** · **Laps & compare** · **Corners** | "What happened, what do I work on, am I improving?" | Sessions, Session, Engineer |
| **Setup** | **Checklist** (default) · **Drivers** · **Connect** · **Rig** · **Car setup** | "Get the driver, game, rig and car ready" | Drivers (Profiles), Connect, Setup (rig), Car setup |
| **Settings** | **Display** (default) · **Radio & voice** · **AI engineer** · **System** | "How Pitwall behaves" | Settings, Status, the settings half of Radio |

### 2.2 Where each current view goes

| Current file | New home | Phase 1 (mounted unchanged) | Later |
|---|---|---|---|
| `views/LiveView.svelte` | Drive › Car | Also stands in for Dash until phase 2 | Phase 5: restyled as the pit wall (`drive/CarView.svelte`). Retired in phase 6 |
| `views/RadioView.svelte` | Drive › Radio | Wrapped as is | Phase 5: its settings panel moves to Settings › Radio & voice |
| `views/SessionsView.svelte` | Review › Sessions | Wrapped | Phase 3: `review/SessionsPage.svelte` |
| `views/SessionView.svelte` | Review › Session › Laps & compare | Wrapped | Phase 3: split into Summary / Laps & compare / Corners |
| `views/EngineerView.svelte` | Review › Engineer | Wrapped | Phase 3: accepts `session` and `question` query parameters |
| `views/ProfilesView.svelte` | Setup › Drivers | Wrapped | Phase 5 restyle |
| `views/ConnectView.svelte` | Setup › Connect | Wrapped | Phase 5 restyle |
| `views/SetupView.svelte` **(hot)** | Setup › Rig | Wrapped, with the same props `App.svelte` passes today | Phase 5 restyle, after the rig work lands |
| `views/CarSetupView.svelte` | Setup › Car setup | Wrapped | Phase 5 restyle |
| `views/SettingsView.svelte` | Settings › AI engineer | Wrapped | |
| `views/StatusView.svelte` | Settings › System | Wrapped | Adds build version and licences |

### 2.3 Routes

Hash routes. They work offline and need no server change. Every area remembers its last sub-page in `localStorage`
(wrapped in try/catch; the first sub-page is used when storage is unavailable).

| Canonical route | Page |
|---|---|
| `#/drive` · `#/drive/car` · `#/drive/radio` | Drive |
| `#/review/sessions` | Sessions |
| `#/review/s/<id>` · `#/review/s/<id>/laps?ref=<lap_id>&lap=<lap_id>&at=<metres or label>` · `#/review/s/<id>/corners` | Session |
| `#/review/coaching?driver=<id>&track=<track_id>&car=<car>` | Coaching plan |
| `#/review/progress?driver=<id>&track=<track_id>&car=<car>` | Progress |
| `#/review/engineer?session=<id>&q=<question>` | Engineer |
| `#/setup/checklist` · `#/setup/drivers` · `#/setup/connect` · `#/setup/rig` · `#/setup/car` (car setup) | Setup |
| `#/settings/display` · `#/settings/radio` · `#/settings/ai` · `#/settings/system` | Settings |

**Legacy redirects** use `history.replaceState`, so Back does not loop. They **keep the `?query` part of the hash**:
the radio store reads `#/radio?token=…`, and the redirect must not drop the token.

| Old | New | Note |
|---|---|---|
| `''`, `#/`, `#/live` | `#/drive` | |
| `#/radio` | `#/drive/radio` | **Permanent.** RadioView itself tells users to open `…:8443/#/radio` |
| `#/sessions` · `#/sessions/<id>` | `#/review/sessions` · `#/review/s/<id>` | Existing views link to these, so the redirect covers them without editing the views |
| `#/engineer` | `#/review/engineer` | |
| `#/setup` | `#/setup/rig` | Keeps the old meaning: it used to be the rig page |
| `#/profiles` · `#/connect` · `#/carsetup` | `#/setup/drivers` · `#/setup/connect` · `#/setup/car` | `DriverChip` links to `#/profiles` |
| `#/settings` · `#/status` | `#/settings/ai` · `#/settings/system` | Bare `#/settings` used to mean the AI settings |
| `#/review` (bare) | The area's remembered sub-page | Bare `#/setup` and `#/settings` are legacy links, handled above. In-app links always name the sub-page |

### 2.4 Global chrome (every page)

- **Connection pill**: `● LIVE` / `STALE 8 s` / `NO DATA` / `NO LINK` (WebSocket closed). It carries a hatched
  `SYNTHETIC` chip when `connection.synthetic` is set, and `REPLAY` when `connection.source` starts with `replay:`.
- **Driver**: the seated driver's avatar (colour and initials). It sits at the bottom of the rail on iPad and Mac, and
  top right in the phone app bar. A tap opens the existing "Who's in the seat?" sheet (`DriverChip` behaviour).
- **Radio pill**: `RADIO ○` (not live) or `RADIO ●` (live; dot green when the mic is OK, amber when it is silent or
  muted). On Drive › Dash it is the push-to-talk control (section 4.3). Elsewhere a tap opens Drive › Radio.
- **Lap toast**: "Lap 7 analysed · 2 coaching points → Review". It appears **only when not on track**. On track, Dash
  never shows toasts.

---

## 3. Navigation

### 3.1 Layout by width

| Layout | Condition | Primary nav | Sub-nav |
|---|---|---|---|
| iPad landscape, Mac | `min-width: 1000px` | **Left rail**, 80 px | Segmented control in the page header, 44 px tall (Drive: in the rail, see 3.2) |
| iPad portrait, small laptop | 700-999 px | **Bottom tab bar**, 64 px plus safe area | Segmented control |
| Phone | `< 700px` | **Bottom tab bar**, 56 px plus `env(safe-area-inset-bottom)`. Labels always visible | Horizontally scrollable pills under a 48 px app bar (area title, radio pill, driver avatar) |
| Desktop | `min-width: 1440px` | The rail widens to 200 px and lists sub-pages as a tree | none |

### 3.2 Components

- **Rail (80 px):** Pitwall mark (64 px, goes to Drive); 4 items of 76 px (a 28 px line icon above a 13 px caps label);
  then a spacer, Night dim (56 px), driver avatar (48 px) and connection dot. The active item gets a 3 px orange bar
  on its left edge.
- **Drive's sub-pages live in the rail.** Dash has no page header: every pixel goes to the numerals. While Drive is
  active, the rail shows **Dash · Car · Radio** as three 44 px caps items under the DRIVE item. Every other area uses
  the segmented control in its page header. On phone, every area (Drive included) uses the pill row under the app
  bar.
- **Tab bar:** 4 items, each at least 72 × 56 px. The Drive item carries a small live dot when telemetry is live, so
  the way back to the timing screen is obvious.
- **Icons:** inline SVG drawn for Pitwall (steering wheel, stopwatch with a lap curve, wrench, sliders). No icon
  font and no external request.
- **Targets:** at least 44 × 44 px everywhere, 56 px on Drive and in sheets, 64 px for actions pressed in gloves
  (Go live, Switch driver, Open Drive, Review this session).

### 3.3 Drive behaviour while on track

- **Rail and status bar dim** to 40 % opacity when the state is `on_track` (setting: Dim navigation on track, on by
  default). Any touch restores full opacity for 5 s. Hit targets keep their size. Banners never dim.
- **Drive lock** (setting: Off / **Beginner profiles** (default) / Everyone). It applies when the state is `on_track`
  and the seated driver matches the setting. Leaving Dash (to Car, Radio or another area) then needs a **0.5 s
  press** on a rail or tab item, and an orange ring fills under the finger. A short tap shows the toast "Hold to
  leave Drive while driving". The lock is off in the pit, before and after the session, and while stale.
- **Screen wake lock** while telemetry is live on any Drive page (`lib/wake.ts`). It works alongside the radio's own
  wake lock.
- **Home-screen web app:** `web/index.html` gets `apple-mobile-web-app-capable`,
  `apple-mobile-web-app-status-bar-style=black-translucent`, and a `manifest.webmanifest` with
  `display: standalone` and `orientation: landscape`. Drive then gets the full 820 px height with no Safari bars.
  It is static and offline; no service worker is needed.

### 3.4 Other patterns

- **Sheets:** pickers (driver, lap A/B, track/car, cue mode) are bottom sheets on phone and anchored popovers on
  iPad. Rows are 56 px. Escape or a tap outside closes them.
- **Keyboard (Mac):** `1`-`4` switch area, `[` and `]` switch sub-page, and Space is push-to-talk while the radio is
  live and a Drive page is open (the existing Radio page behaviour).
- **Confirmations** happen inline, never through browser dialogs. Examples: pin as reference, reassign a session,
  switch driver while a session is live.

---

## 4. Drive › Dash (iPad landscape)

### 4.1 Viewport and legibility

The baseline is **1180 × 820 CSS px**: an 11-inch iPad or iPad Air in landscape, as a home-screen web app. One CSS
px is 0.192 mm. The iPad mini is 1133 × 744 at 0.156 mm per px. In Safari with toolbars, subtract about 70 px of
height. Sizes scale with `clamp()` on `dvh` (section 6.1), so every one of these still fits without scrolling.

Visual angle is the cap height (0.70 × font size for the condensed faces) at 700 mm. In-vehicle display guidance
(ISO 15008) asks for at least 20′ and prefers 24′ or more.

| Token | Size (baseline) | Cap height | At 70 cm (11") | At 70 cm (mini, Standard → Large) | Used for |
|---|---|---|---|---|---|
| `--d-hero` | 172 px | 23.1 mm | **113′** | 92′ | Delta, pit speed |
| `--d-xl` | 112 px | 15.1 mm | 74′ | 60′ | Corner label |
| `--d-l` | 56 px | 7.5 mm | 37′ | 30′ → 36′ | Lap clock, state titles |
| `--d-m` | 48 px | 6.5 mm | 32′ | 26′ → 31′ | Sector times, cue distance |
| `--d-s` | 40 px | 5.4 mm | 26′ | 21′ → **26′** | Official name, LAST, BEST |
| `--d-xs` | 24 px | 3.2 mm | 16′ | for a stationary reader | Context lines, sentences when stopped |
| `--d-label` | 18 px | 2.4 mm | 12′ | for a stationary reader | Labels, learned by position |

**Rule: anything read while moving is at least `--d-s` (40 px).** On the iPad mini the Drive screen suggests the
**Large** text size (× 1.2) once, the first time it sees a viewport of 1133 × 744 or smaller.

### 4.2 Grid (on track)

```
1180 × 820 · rail 80 · content 1100 × 820 · padding 20 · gaps 12 (8 inside the timing strip)
x: 0      80  100                                     711 723                             1160 1180
   ┌──────┬──────────────────────────────────────────────────────────────────────────────────┐ y 0
   │ mark │                                                                                  │ 20
   │      │ STATUS SLOT 1060 × 56                                                            │
   │DRIVE │ ● LIVE  Kestrel Park · Practice · LAP 8/20 · S2   "Lap 7: 1:28.9…"  [◉ HOLD TO TALK] ☾│ 76
   │ ·dash│ ┌ DELTA 611 × 476 ──────────────────────────┐ ┌ CORNER & CUE 437 × 476 ────────────┐ │ 88
   │  car │ │ DELTA · REF L5 1:28.904      PROJ 1:28.69 │ │ NEXT CORNER                ◆ FOCUS │ │
   │ radio│ │                                           │ │ T9 ↱                      (112 px) │ │
   │REVIEW│ │             −0.21          (172 px)       │ │ Kestrel                    (40 px) │ │
   │SETUP │ │                 AHEAD                     │ │ [BRAKE]  285 m             (48 px) │ │
   │SETTNG│ │ ◀━━━━━━━━━━━━━━━━┃                  ▶      │ │ ▮▮▮▮▮▮▮▮▮▯▯▯▯▯▯  (emptying bar)     │ │
   │      │ │ −1.0          AHEAD 0 BEHIND         +1.0 │ │ braking early · 3 of last 5 laps   │ │
   │      │ │                                           │ │ LAST T7 · ON TIME −3 m             │ │
   │      │ └───────────────────────────────────────────┘ └────────────────────────────────────┘ │ 564
   │  ☾   │ ┌ LAP 225 ──┬ S1 150 ┬ S2 150 ┬ S3 150 ┬ LAST 172 ──┬ BEST 172 ──┐               │ 576
   │ (JR) │ │ LAP 8/20  │ S1  SB │ S2 REC │ S3  ▸  │ LAST       │ BEST    SB │  148 px       │
   │  ●   │ │ 0:41.6    │ 27.402 │ 33.118 │   -    │ 1:28.941   │ 1:28.904   │               │
   │      │ └───────────┴────────┴────────┴────────┴────────────┴────────────┘               │ 724
   │      │ LAP STRIP 1060 × 64  |S1 ░░░░ T1 T2 T3 T4 |S2 ░ T5 T6 T7 T8 |S3 ▲T9 T10 T11        │ 736
   └──────┴──────────────────────────────────────────────────────────────────────────────────┘ 820
```

```css
/* web/src/drive/DashView.svelte (root). Values at 1180 × 820; rows flex with the viewport. */
.dash {
  display: grid;
  height: 100dvh;
  padding: 20px;
  gap: 12px;
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);          /* 611 / 437 */
  grid-template-rows: var(--status-h) minmax(0, 1fr) 148px 64px;  /* 56 / 476 / 148 / 64 */
  grid-template-areas: "status status" "delta corner" "timing timing" "strip strip";
  background: var(--bg-0);
}
.timing { display: grid; gap: 8px; grid-template-columns: 1.5fr repeat(3, 1fr) 1.15fr 1.15fr; } /* 225/150×3/172×2 */
.panel  { contain: layout paint; }                                 /* no shadows, no backdrop-filter on Drive */
@media (max-height: 700px) { .dash { grid-template-rows: 48px minmax(0, 1fr) 124px 52px; padding: 12px; gap: 8px; } }
@media (max-width: 999px), (orientation: portrait) {               /* iPad portrait, phone: section 5 */
  .dash { grid-template-columns: 1fr; height: auto; min-height: 100dvh;
          grid-template-rows: auto auto auto auto auto; grid-template-areas: "status" "delta" "corner" "timing" "strip"; }
}
```

### 4.3 Panels

**Status slot (1060 × 56).** This one fixed slot is where the session's state speaks. Its content is swapped,
never stacked. Bands (flags, pit, stale, link lost) fill the slot **to the left of the radio pill and the Night dim
button**, which stay usable in every state. On phone the band spans the whole row, because the radio pill lives in
the app bar there.

| Element | Spec | Source | Unknown / edge |
|---|---|---|---|
| Connection pill | 36 px pill, 18 px caps | `connection.status`, `last_packet_age_s`, `live.connected` | `NO LINK` when the WebSocket is closed |
| Evidence chips | `SYNTHETIC` (hatched pink), `REPLAY` | `connection.synthetic`, `connection.source` | Always shown when true (P8) |
| Context line | `Kestrel Park · Practice · LAP 8/20 · S2 · P4`, 22 px. Labels in `--text-3`, values in `--text-2` | `session.track_name`, `session_type`, `frame.lap_number`, `session.total_laps`, `frame.sector`, `frame.race_position` (race only) | `-` for unknown. The car name is left out: it can be a team name, and it lives on Car |
| Radio ticker | The latest radio message for 8 s, 20 px, one line with ellipsis | radio store `current` | Hidden when the radio is not live |
| Radio pill (200 × 56) | **Not live:** `GO LIVE`, and a tap calls `radio.goLive()` inside the gesture. **Live:** `HOLD TO TALK` with a mic dot; press calls `radio.pttPress()` and release calls `radio.pttRelease()`. While talking: `TALKING…` | radio store `phase`, `mic`, `pttHeld` | `micCapable == false` (plain HTTP): `LISTEN ONLY`, and a tap explains HTTPS |
| Night dim | ☾ 56 px | `prefs.night` | |
| Transient chip | 6 s at the right: `PENALTY`, `CONTACT`, `FLASHBACK · LAP WON'T COUNT`, `FASTEST LAP`, `PIT ENTRY` / `PIT EXIT` | newest `events[]` with `t` in the last 6 s | |

**Delta (611 × 476).** The focal metric.

| Element | Spec | Source |
|---|---|---|
| Label | `DELTA · REF L5 1:28.904` (18 px, `--text-3`). Adds `· 3 Oct` when the reference lap is from another session. **Beginner** profiles read `VS YOUR TARGET LAP · 1:28.904` | `reference.{lap_number, lap_time_ms, session_id}` |
| Projected | `PROJ 1:28.69` (24 px, `--text-2`), top right. Hidden for beginners, `-` on an invalid lap | `reference.lap_time_ms + delta_s × 1000` (derived) |
| Number | **172 px**, weight 700, tabular. U+2212 for ahead, `+` for behind. Two decimals; one decimal at 10 s or more (`+12.4`). Rendered at most 10 times a second. The sign glyph is drawn 0.62 wide so it does not push the digits | `delta_s` |
| Colour | `--ahead` when `delta_s < −0.02`, `--behind` when `> +0.02`, `--text-1` otherwise (word `LEVEL`). Invalid lap or safety car: `--text-2` with no green or red | `delta_s`, `frame.lap_invalid`, `session.safety_car_status` |
| Word | `AHEAD` / `BEHIND` / `LEVEL`, 22 px caps, under the number (P4) | sign |
| Bar | 28 px, full width, centre tick. Fills **left** in green when ahead and **right** in red when behind. Scale ±1.0 s with ticks at ±0.25, ±0.5 and ±1.0, and a chevron at the end when the value is clamped. End labels `◀ AHEAD`, `BEHIND ▶` | `delta_s` |
| Unknown | `-` in `--text-3` plus one reason line (24 px): "No reference lap yet: your first clean lap becomes the reference", "Out lap", "No signal" | `reference == null`, `delta_s == null`, state |
| Screen reader | `aria-label="0.21 seconds ahead of reference lap 5"`. The number itself is `aria-live="off"` | |

**Corner & cue (437 × 476).**

| Element | Spec | Source |
|---|---|---|
| Which corner | The first corner whose `apex_m` lies ahead of the car (wrapping at the line). It stays until the car passes its apex. The head reads `NEXT CORNER · 340 m` before `entry_m` and `IN CORNER` after it. Game metres map to model metres by lap fraction (`skeleton.track_length_m` → `track_model.length_m`), as `TrackMap.toModel` already does | `track_model.corners[].{name, entry_m, apex_m, direction}`, `frame.lap_distance_m`, `skeleton.track_length_m` |
| Label | `T9` at **112 px**, plus a 64 px direction arrow (SVG) | `corners[].label` (official) → else `corner_text[name].short` → else the learned `name` |
| Official name | `Kestrel` at 40 px. Shown **only** when `corners[].display_name` is set, which the server does only for a verified track sheet. Names longer than 14 characters drop to 32 px and wrap to two lines. Never parsed from `corner_text.long` | `corners[].display_name` |
| Focus tag | `◆ FOCUS`, orange outline, top right | `cues.focus` contains the corner's learned name |
| Cue | **Kind chip** `BRAKE` (outlined in `--brake`) or `MARKER` (outlined in `--text-2`), 18 px. **Distance** `285 m` at 48 px. **Emptying bar** 16 px: its width is `in_m / 400`, and it empties as the braking point approaches, with no flash at zero (P6). The cue text is shown only when the cue belongs to a different corner from the one displayed: `Next call: T11 brake · 1.4 km` (24 px) | `cues.next.{kind, corner, in_m, text}`. `cues.next.corner` is the learned corner name (`coach/cues.py` builds it from the comparison corners), the same key as `track_model.corners[].name` |
| Why focus | Focus corners only: the cue plan's reason at 24 px `--text-2`, for example "braking early · 3 of last 5 laps" | `cues.cues[].reason` for that corner |
| Last cue outcome | Footer, 18 px, shown for 90 s: `LAST T7 · ON TIME −3 m` (`--text-3`), `LAST T7 · LATE +6 m` (`--warn`), `LAST T7 · DROPPED (reason)`. Same rule as today's `LiveView`: `error_m − timing.margin_m > 0` is late | `cues.last.{corner, status, error_m, reason, age_s}`, `cues.timing.margin_m` |
| Cues off or muted | `Calls off · Drive › Radio` (mode `off`). `Calls paused: safety car` / `radio off` (`cues.muted`). `cues.reason` when there is no plan ("no reference lap yet") | `cues.mode`, `cues.muted`, `cues.reason` |
| No model | `-` and "Corners appear after your first clean lap" (24 px) | `track_model == null` |

**Timing strip (1060 × 148).** Six square cells. Each has a 6 px top bar in its timing colour, an 18 px label, a
15 px tag (`REC` / `PB` / `SB` / `INV`) in the bar colour, and a tabular value.

| Cell | Value | Source | Notes |
|---|---|---|---|
| **LAP** (225) | `LAP 8/20`. Running clock `0:41.6` at **56 px**, **tenths only** while running. When a lap completes, the final time to the millisecond shows in its colour for 6 s, then the clock resumes | `frame.{lap_number, current_lap_time_ms, lap_invalid}`, `session.total_laps`, `laps[0]` | Invalid lap: the clock turns `--text-2`, an `INVALID` tag appears in `--danger`, and colouring stops |
| **S1 S2 S3** (150 each) | `27.402` at **48 px**. The current sector gets a 2 px `--text-1` outline and a ▸ (SVG). Future sectors show `-` | **D1** `frame.current_lap_sector_ms`. **Fallback before D1:** a caption `LAST LAP · L7` spans the three cells, values come from `laps[0].sector_times_ms`, slightly dimmed, coloured by their status as set. **No current-sector outline** on these cells, so last-lap values never look current; the lap strip still shows where the car is | D1 is small (the F1 adapter already parses the sector parts) and should land **before Drive sign-off**, so the fallback is short-lived |
| **LAST** (172) | `1:28.941` at 40 px, coloured as set | `frame.last_lap_time_ms`; status from `laps[0]` | `-` before the first lap |
| **BEST** (172) | `1:28.904` at 40 px. Your session best, tagged `SB`, or `PB` / `REC` when it is also one of those | min of clean `laps[].lap_time_ms`, exact with D2 `bests.session` (the snapshot keeps only 20 laps) | Synthetic and replay sessions never set PB or REC |

**Lap strip (1060 × 64).** A straight-line lap. It is easier to read at a glance than a circuit map, and it is a
static SVG in which only the car marker moves (by `transform`).

- 0 m to `skeleton.track_length_m`. Sectors come from `skeleton.sectors`. **Sector identity is shown by labels and
  ticks**, not by the red/blue/yellow `SECTOR_COLOURS`, which clash with timing yellow (P3). Completed sectors of
  this lap get a 6 px top bar in their timing colour as set (the same signature as the timing cells), the current
  sector uses `--surface-3`, and later sectors `--surface-2`.
- Corner ticks with 16 px labels at `apex_m` (mapped to game metres). The next corner's label is `--text-1`, the
  others `--text-3`. Focus corners get an orange dot.
- Cue notches: a 2 px orange tick at each `cues.cues[].target_m`.
- DRS zones dashed (`skeleton.drs_zones`). Live yellow marshal zones are hatched `--flag-yellow` (`marshal_flags`
  joined to `skeleton.marshal_zones`).
- Car: a 14 px orange triangle at `frame.lap_distance_m`.
- No skeleton: one neutral band. No model: no corner ticks.

### 4.4 Timing colours

One rule set everywhere: Drive, the Car wall, Review and Progress. The scope is the same **game + track + car**,
**clean laps only**, **never synthetic or replay sessions**, which matches the storage rules for references and PBs.

| Colour | Tag | Meaning | Tier 1 (data today) | Tier 2 (with D2) |
|---|---|---|---|---|
| **Purple** | `REC` | Household record: faster than every earlier time by **any** driver profile | **Never shown** | Shown |
| **Green** | `PB` | Your all-time personal best here, and not a record | Not shown | Shown |
| **Green** | `SB` | Your best **this session** (the F1 meaning of green) | From `laps[]` | From `bests.session` |
| **Yellow** | none | Completed, slower than your session best | Shown | Shown |
| Neutral | none | Nothing to compare yet (the session's first sector), or unknown | Shown | Shown |
| Grey, struck | `INV` | Invalid, or a lap that is not clean (`flashback`, `pit_in`, `pit_out`, `paused`, `stale_data`, `distance_jump`). The flag shows in plain words | Shown | Shown |

- **As set** on Drive: a sector or lap is coloured by its status at the moment it was completed. A green S1 stays
  green for that lap.
- **Current standing** in tables (the Car wall's laps, Review laps, Progress): only times that are still the best in
  their column are green or purple. Every other completed time is yellow.
- Tier 2 only **adds** purple and the `PB` tag. Nothing changes meaning when D2 lands, so no driver has to unlearn
  a colour.
- The legend on every timing surface reads `REC family record · PB your best ever · SB your best today`. On Tier 1
  it reads `SB your best today` only.

### 4.5 States

A pure function `driveState(snapshot, wsConnected, now)` in `web/src/drive/logic/driveState.ts` (section 4.6)
returns one state plus overlays. The first matching state wins. The same function drives the iPad, phone and Mac
layouts.

| # | State | Trigger (exact) | Status slot | Left (delta) | Right (corner & cue) | Timing | Lap strip |
|---|---|---|---|---|---|---|---|
| 1 | **Link lost** | `!live.connected` | Outline band in `--danger`: `NO LINK · reconnecting…` | `-` | `-` | All `-`. Track and driver stay | Car hidden |
| 2 | **No data** | `connection.status == "no_data"` | `WAITING FOR TELEMETRY` (neutral) | **No-data card** spanning both panels: three steps from `/api/connect` ("Turn on UDP telemetry", "IP `192.0.2.20` port `20777`", last sender seen) plus **Open Connect** (64 px) and **Demo replay** (goes to Settings › System; labelled SYNTHETIC) | | All `-` | Empty |
| 3 | **Stale** | `connection.status == "stale"` (no packet for 2 s or more) | **Amber outline** band: `NO SIGNAL · 8 s · game paused or in a menu?` | `-` (a frozen delta must never look current) | Dimmed to 40 %, with `8 s old` | LAP `-`. Sectors, LAST and BEST stay (they are facts) | Dimmed |
| 4 | **Session ended** | D4 `session_state == "ended"`. Until D4: newest event is `session_ended` or `chequered_flag` (events reset with the session) | Neutral fill: `SESSION COMPLETE` / `CHEQUERED FLAG` | **Session complete card** spanning both panels: best lap (coloured, tag), laps clean/total, gained today (first clean lap → best), gap to PB and REC (D2), **one Work on** and **one Went well** (D6 `coach.picked`, else top observations by priority), and **Review this session** (64 px) | | Kept | Kept |
| 5 | **Red flag** | D4 `red_flag`. Until D4: the newest event is `red_flag`, within 120 s, with no newer event | **Red fill**, white ink: `RED FLAG` (`role="alert"`) | `-` | Cue cell: `Calls paused` | Kept | Kept |
| 6 | **Pit lane** | `frame.pit_status == 1` | **Cyan fill**: `PIT LANE · LIMIT 80` | **Speed / limit** `78 / 80 km/h` at hero size. Over the limit: `--danger` plus the word `OVER`. Limit `-` when `skeleton.pit_speed_limit_kph` is unknown | **One thing for the next run** (D6 pick, 28 px, verbatim, with its evidence line) and **Went well** | Kept | Car at the pit lane |
| 7 | **Between runs** | `frame.pit_status == 2` and `laps.length > 0` (D3: `driver_status == "in_garage"`) | **Cyan fill**: `IN GARAGE` | **Last lap** at hero size, coloured as set, plus its delta and flags in words | **One thing for the next run** (28 px, evidence line) and **Went well**. Driver row: `James in the seat · Switch` (56 px), because handovers happen here | Kept | Static |
| 8 | **Pre-session** | Session known, `laps.length == 0` and (`pit_status == 2` or `speed_kph < 1` or `current_lap_time_ms` is 0 or null). D3 makes it exact | Neutral: `READY · PRACTICE` | **Ready card** spanning both panels (below) | | `-` | Corners and sectors, no car |
| 9 | **On track** | Otherwise | Context line (4.3): `Kestrel Park · Practice · LAP 8/20 · S2` | Delta | Corner & cue | Live | Live |

**Ready card (pre-session).** It has three columns and a footer:

1. **Seat:** 96 px avatar; "**James** is in the seat" (40 px); skill chip; **Not you? Switch driver** (64 px).
2. **Target:** "Your best here" (PB from `drivers.active.stats.best_laps` for this game and track; with D2, per
   car); "Family record" (D2, with the holder's avatar); "Delta reference" (`L5 1:28.904 · today`, or "none yet:
   your first clean lap becomes the reference").
3. **Today:** focus corners (`cues.focus`, shown by official label and name, with `cues.cues[].reason`); braking
   calls mode (`cues.mode`); radio (**Go live**, 64 px, or `Radio live · mic OK`).

Footer: `4 210 m · S1 1 380 m · S2 1 400 m · S3 1 430 m · 11 corners learned · official names: verified sheet`
(`skeleton`, `track_model`).

**Overlays** combine with states 6 to 9. Band priority in the slot: red > safety car > yellow > blue > pit > normal.

| Overlay | Trigger | Treatment |
|---|---|---|
| Safety car | `session.safety_car_status` is `full`, `virtual` or `formation_lap` | Amber fill: `SAFETY CAR · calls paused` / `VIRTUAL SAFETY CAR` / `FORMATION LAP`. The delta is shown in `--text-2` with an `SC` tag: it is real but not meaningful |
| Yellow flag | any `marshal_flags[].flag == "yellow"` | Yellow fill, dark ink: `YELLOW · SECTOR 2 · ZONE 7 · 380 m AHEAD`. The distance shows when the zone starts within the next 1 000 m. The zone is hatched on the lap strip. No blinking |
| Blue flag | `flag == "blue"` | Blue fill: `BLUE FLAG` |
| Lap invalid | `frame.lap_invalid` | No band. The LAP cell shows `INVALID`, colouring stops, the delta goes to `--text-2`, and projected shows `-`. The game sends no reason, so none is shown |

### 4.6 Pure logic modules (unit-tested, no DOM)

These live in `web/src/drive/logic/`, import nothing but types, use only erasable TypeScript (no `enum`, no
`namespace`, no parameter properties), and import each other with `.ts` extensions. Tests run with
`node --test web/tests` (Node 25's built-in type stripping, so there is no new dependency).

```ts
// drive/types.ts: fields the backend adds (all optional; absent = unknown, never guessed)
export interface Bests { lap_ms: number | null; sectors_ms: [number | null, number | null, number | null] }
export interface CueSnapshot {                       // coach/cues.py CueEngine.snapshot(), exists today
  mode: "off" | "focus" | "markers" | "all"; armed: boolean; muted: string | null; reason: string | null;
  ref_lap_number: number | null; focus: string[];
  cues: { corner: string; kind: "brake" | "marker"; target_m: number; text: string; focus: boolean; reason: string }[];
  next: { corner: string; text: string; kind: "brake" | "marker"; in_m: number } | null;
  last: { corner: string; text: string; status?: "pending" | "sent" | "dropped"; reason?: string | null;
          error_m?: number | null; age_s?: number | null } | null;
  timing: { latency_ms: number; path: string; margin_m: number };
}
export interface SnapshotNext extends Snapshot {
  cues?: CueSnapshot;
  frame: (Frame & { current_lap_sector_ms?: [number | null, number | null] | null;                 // D1
                    driver_status?: "in_garage" | "out_lap" | "in_lap" | "flying_lap" | "on_track" | null }) | null; // D3
  bests?: { session: Bests; driver: (Bests & { set_unix: number | null }) | null;
            household: (Bests & { driver_id: number | null }) | null } | null;                       // D2
  session_state?: "running" | "ended" | "red_flag" | null;                                            // D4
  coach?: { lap_number: number; picked: Observation[]; by_corner: Record<string, Observation> } | null; // D6
}

// drive/logic/driveState.ts
export type DriveState = "link_lost" | "no_data" | "stale" | "ended" | "red_flag" | "pit_lane"
                       | "between_runs" | "pre_session" | "on_track";
export interface DriveOverlays {
  safetyCar: "full" | "virtual" | "formation_lap" | null;
  yellow: { zone: number; sector: number | null; aheadM: number | null } | null;
  blue: boolean; invalid: boolean;
  chip: { kind: "penalty" | "collision" | "flashback" | "fastest_lap" | "pit_entry" | "pit_exit"; ageS: number } | null;
}
export function driveState(s: SnapshotNext | null, wsConnected: boolean, nowUnixS: number):
  { state: DriveState; overlays: DriveOverlays };

// drive/logic/corner.ts
export interface CornerView { name: string; label: string; officialName: string | null;
  direction: "left" | "right" | null; phase: "next" | "in"; toEntryM: number | null; focus: boolean; focusReason: string | null }
export function cornerAhead(model: TrackModel | null | undefined, lapDistanceM: number | null,
  gameLengthM: number | null, cues: CueSnapshot | undefined): CornerView | null;

// drive/logic/delta.ts
export const DELTA_NEUTRAL_S = 0.02, DELTA_SCALE_S = 1.0;
export interface DeltaView { text: string; tone: "ahead" | "behind" | "level" | "muted" | "unknown";
  word: "AHEAD" | "BEHIND" | "LEVEL" | null; bar: number /* −1..1 */; clamped: boolean;
  projectedMs: number | null; reason: string | null; aria: string }
export function deltaView(s: SnapshotNext | null, state: DriveState, overlays: DriveOverlays, beginner: boolean): DeltaView;

// drive/logic/timing.ts
export type TimingStatus = "rec" | "pb" | "sb" | "slower" | "neutral" | "invalid";
export function bestsOf(s: SnapshotNext): { tier: 1 | 2; session: Bests; driver: Bests | null; household: Bests | null };
export function statusAsSet(t: number | null, before: { session: number | null; driver: number | null;
  household: number | null }, clean: boolean, tier: 1 | 2): TimingStatus;
export function standing(times: (number | null)[], clean: boolean[], best: { driver: number | null;
  household: number | null }, tier: 1 | 2): TimingStatus[];
export function lapClock(ms: number | null, running: boolean): string;   // "0:41.6" running, "1:28.941" done, "-" unknown

// drive/logic/cues.ts
export interface CueView { kind: "brake" | "marker"; corner: string; inM: number; fill: number; forShownCorner: boolean; text: string }
export interface LastCueView { corner: string; words: string; tone: "ok" | "late" | "dropped" }
export function cueView(c: CueSnapshot | undefined, shownCorner: string | null):
  { next: CueView | null; last: LastCueView | null; note: string | null };

// drive/logic/lapStrip.ts
export function lapStrip(s: SnapshotNext): { lengthM: number | null;
  sectors: { a: number; b: number; label: string; status: TimingStatus | "current" | "future" }[];
  corners: { at: number; label: string; next: boolean; focus: boolean }[];
  cueNotches: number[]; drs: [number, number][]; yellow: [number, number][]; car: number | null };  // fractions 0..1
```

**Test fixtures** are JSON snapshots captured from `pitwall replay` of the recorded Austria fixture
(`tests/fixtures/recorded`) and from `pitwall simulate` (synthetic, and named as such). Between them, the fixtures
reach every state and overlay above.

### 4.7 Drive › Car and Drive › Radio

- **Car = the pit wall.** It is dense and built for a stationary reader: a parent on the phone, or a second screen on
  the Mac. It uses a 12-column grid: Car (speed, gear, rpm, pedals, steering), Track map (`TrackMap` with the live
  car, sectors coloured by timing status, live flags, braking zones), Tyres & energy (FL FR / RL RR; the in-window
  temperature is plain `--text-1`, not green, so colour means "look here"), Inputs (uPlot, last 12 s), Laps (current
  standing), Coaching · last lap, and Race control (newest events). Phase 1 mounts `LiveView` unchanged here, and
  phase 5 restyles it as `drive/CarView.svelte`.
- **Radio:** today's `RadioView` stage (Go live, big push-to-talk, Radio check, Stop talking, mic meter, log).
  Cue mode and coaching intensity stay here as a compact segmented row, because they change between runs. The voice
  settings move to Settings › Radio & voice in phase 5.

---

## 5. Phones and other sizes

| Device | Drive › Dash | Other areas |
|---|---|---|
| **Phone portrait** (390 × 844) | One column: app bar 48 (area, radio pill, avatar) · status/flag band 40 · delta (`clamp(88px, 26vw, 120px)` plus bar) · corner (label 64, name 28, cue chip and distance 36) · three sector cells (32) · LAP / LAST / BEST row (28) · lap strip 48 · tab bar 56. Mostly for a parent watching. The radio pill stays in the app bar | Single column. Tables become two-line rows. Session tabs become a scrollable pill row |
| **Phone landscape** (844 × 390) | The iPad grid with the compact scale (`max-height: 700px` rule): no rail, and the tab bar collapses to a 44 px side strip | Single column |
| **iPad portrait** (820 × 1180) | One column in the same order as the phone, at iPad scale. Bottom tab bar | Two columns where useful |
| **iPad mini** (1133 × 744) | The landscape grid. Suggests **Large** text once (section 4.1) | |
| **iPad 13"** (1376 × 1032) | The same grid. Type grows through `clamp()` up to the caps | |
| **Mac** | The same grid, centred, maximum width 1680. Drive › Car is the natural Mac page | Rail plus content, maximum width 1680 |

---

## 6. Visual system

### 6.1 Tokens (paste-ready)

Save this as `web/src/styles/tokens.css` and make it the first `@import` in `web/src/app.css`. Alternatively,
replace the two `:root` blocks at the top of `app.css` with it. The **legacy aliases** at the end keep every
existing view working unchanged. `lib/prefs.svelte.ts` sets `data-theme`, `data-night`, `data-cvd` and
`data-drive-size` on `<html>`.

```css
/* =========================================================================================
   Pitwall design tokens (docs/ui/design-spec.md section 6). Dark first.
   Contrast ratios (WCAG 2.x) are measured against --surface-1 unless noted.
   ========================================================================================= */
:root {
  color-scheme: dark;

  /* surfaces */
  --bg-0: #050608;          /* Drive background: near-black, least glare in a dim room */
  --bg-1: #0b0e12;          /* app background */
  --surface-1: #11151b;     /* panels */
  --surface-2: #171c24;     /* raised, selected segment, future sectors */
  --surface-3: #222a35;     /* current sector, pressed */
  --line: #252c37;          /* hairlines (decorative) */
  --line-strong: #5d6878;   /* control borders: 3.2:1 */

  /* text */
  --text-1: #eef1f5;        /* values             16.2:1 */
  --text-2: #a9b2bf;        /* secondary           8.6:1 */
  --text-3: #8590a0;        /* labels and "-"      5.7:1 */

  /* you / action */
  --accent: #ff6a2b;        /* your car, focus, primary action   6.4:1 */
  --on-accent: #0d1117;     /* ink on accent fills               6.6:1 */

  /* timing (bar colour, value colour, value fill). One meaning each, everywhere. */
  --t-purple: #c58cff;  --t-purple-fg: #c58cff;  --t-purple-bg: transparent;   /* REC  7.5:1 */
  --t-green:  #2fe37f;  --t-green-fg:  #2fe37f;  --t-green-bg:  transparent;   /* PB/SB 10.8:1 */
  --t-yellow: #ffd23f;  --t-yellow-fg: #ffd23f;  --t-yellow-bg: transparent;   /* slower 12.7:1 */

  /* delta */
  --ahead: #2fe37f;
  --behind: #ff5466;        /* 5.9:1 */

  /* status */
  --live: #2fe37f;
  --warn: #ffb020;          /* stale, warnings     10.0:1 */
  --danger: #ff5466;        /* link lost, invalid, over the pit limit   5.9:1 */
  --info: #4cc3ff;          /* reference trace, info   9.2:1 */
  --synthetic: #ff7ac0;     /* SYNTHETIC: hatched + words, never a timing colour   7.7:1 */
  --hatch-synthetic: repeating-linear-gradient(135deg,
      color-mix(in srgb, var(--synthetic) 24%, transparent) 0 6px, transparent 6px 12px);

  /* flags and bands: filled, with words */
  --flag-yellow: #ffd23f;  --flag-yellow-ink: #0d1117;   /* 13.1:1 */
  --flag-sc: #ffb020;      --flag-sc-ink: #0d1117;       /* 10.4:1 */
  --flag-red: #d7263d;     --flag-red-ink: #ffffff;      /*  5.0:1 */
  --flag-blue: #4cc3ff;    --flag-blue-ink: #0d1117;     /*  9.5:1 */
  --pit: #4cc3ff;          --pit-ink: #0d1117;           /*  9.5:1 */

  /* inputs */
  --throttle: #2fe37f;
  --brake: #ff5466;

  /* type */
  --font-num: "DIN Condensed", "DIN Alternate", "Avenir Next Condensed", "Barlow Semi Condensed",
              "Roboto Condensed", "Arial Narrow", sans-serif;
  --font-label: "Avenir Next Condensed", "Barlow Semi Condensed", "Roboto Condensed", "DIN Condensed",
                "Arial Narrow", sans-serif;
  --font-ui: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;

  /* Drive scale (glance). Baseline values at 1180 × 820 in comments. */
  --drive-k: 1;                                                             /* 1.2 with Large */
  --d-hero:  calc(clamp(88px, min(21dvh, 26vw), 220px) * var(--drive-k));   /* 172 */
  --d-xl:    calc(clamp(64px, 13.6dvh, 140px) * var(--drive-k));           /* 112 */
  --d-l:     calc(clamp(40px, 6.8dvh, 72px) * var(--drive-k));             /*  56 */
  --d-m:     calc(clamp(34px, 5.85dvh, 60px) * var(--drive-k));            /*  48 */
  --d-s:     calc(clamp(28px, 4.9dvh, 52px) * var(--drive-k));             /*  40 */
  --d-xs:    calc(clamp(20px, 2.9dvh, 28px) * var(--drive-k));             /*  24 */
  --d-label: calc(clamp(15px, 2.2dvh, 22px) * var(--drive-k));             /*  18 */

  /* app scale (Review, Setup, Settings: read up close) */
  --fs-axis: 12px; --fs-caption: 14px; --fs-body: 16px; --fs-title: 20px; --fs-page: 24px;
  --fs-kpi: 32px; --fs-kpi-hero: 48px;
  --lh-body: 1.5;

  /* spacing, shape, targets, chrome */
  --s-1: 4px; --s-2: 8px; --s-3: 12px; --s-4: 16px; --s-5: 20px; --s-6: 24px; --s-7: 32px; --s-8: 40px;
  --s-9: 48px; --s-10: 64px;
  --r-cell: 2px;   /* timing cells: square, the signature */
  --r-panel: 6px;
  --r-pill: 999px;
  --hit: 44px; --hit-drive: 56px; --hit-glove: 64px;
  --rail-w: 80px; --tabbar-h: 56px; --appbar-h: 48px; --status-h: 56px;
  --bar-top: 6px;  /* timing cell top bar */
  --focus-ring: 0 0 0 2px var(--bg-1), 0 0 0 4px var(--accent);

  /* motion */
  --t-fast: 100ms;   /* bar fills, linear */
  --t-fade: 600ms;   /* one fade when a sector completes */
}

/* light theme (kept). Timing values become filled chips: coloured text on white is too weak. */
:root[data-theme="light"] {
  color-scheme: light;
  --bg-0: #f5f6f8; --bg-1: #eceff3; --surface-1: #ffffff; --surface-2: #eceff3; --surface-3: #dfe4eb;
  --line: #d9dee6; --line-strong: #848e9d;                                   /* 3.3:1 on white */
  --text-1: #0d1117; --text-2: #4a5463; --text-3: #5b6574;                   /* 18.9 / 7.7 / 5.9 */
  --accent: #b93c0a; --on-accent: #ffffff;                                   /* 4.9 on --surface-2 / 5.7 ink */
  --t-purple: #6d28d9;  --t-purple-fg: #ffffff;  --t-purple-bg: #6d28d9;     /* white on fill 7.1:1 */
  --t-green:  #047857;  --t-green-fg:  #ffffff;  --t-green-bg:  #047857;     /* 5.5:1 */
  --t-yellow: #ffd23f;  --t-yellow-fg: #0d1117;  --t-yellow-bg: #ffd23f;     /* 13.1:1 */
  --ahead: #047857; --behind: #c81e3a;                                       /* 5.5 / 5.7 */
  --live: #047857; --warn: #9a5b00; --danger: #c81e3a; --info: #0369a1; --synthetic: #be185d;
  --pit: #0369a1; --pit-ink: #ffffff;
  --throttle: #047857; --brake: #c81e3a;
  --focus-ring: 0 0 0 2px var(--bg-1), 0 0 0 4px var(--accent);
}

/* night dim: dark theme only, for a dark room together with low iPad brightness. Hero stays above 7:1. */
:root[data-night="on"]:not([data-theme="light"]) {
  --bg-0: #000000; --bg-1: #030405; --surface-1: #0a0c10; --surface-2: #101319; --surface-3: #181d25;
  --line: #1a1f27; --line-strong: #444d5a;
  --text-1: #c9ced6; --text-2: #8b94a1; --text-3: #78828f;                   /* 12.4 / 6.4 / 5.0 */
  --accent: #e0602a;
  --t-purple: #b07ae6; --t-purple-fg: #b07ae6;
  --t-green: #28c46e;  --t-green-fg: #28c46e;
  --t-yellow: #e0b836; --t-yellow-fg: #e0b836;
  --ahead: #28c46e; --behind: #e04a5a; --live: #28c46e; --warn: #e09a1c; --danger: #e04a5a;
}

/* red-green safe colour vision: green → blue, red → orange. Signs, bar direction and tags stay on. */
:root[data-cvd="rg"] {
  --t-green: #4cc3ff; --t-green-fg: #4cc3ff; --ahead: #4cc3ff; --live: #4cc3ff; --throttle: #4cc3ff;
  --behind: #ff9f1c; --danger: #ff9f1c; --brake: #ff9f1c;
}
:root[data-theme="light"][data-cvd="rg"] {
  --t-green: #0369a1; --t-green-fg: #ffffff; --t-green-bg: #0369a1; --ahead: #0369a1; --live: #0369a1;
  --throttle: #0369a1; --behind: #9f4706; --danger: #9f4706; --brake: #9f4706;     /* 5.9 / 5.4 on --surface-2 */
}

/* Drive text size Large (iPad mini, or anyone who wants it) */
:root[data-drive-size="large"] { --drive-k: 1.2; }

/* phone: Drive goes to one column with its own glance scale */
@media (max-width: 699px) {
  :root {
    --d-hero: calc(clamp(88px, 26vw, 120px) * var(--drive-k));
    --d-xl: calc(64px * var(--drive-k)); --d-l: calc(40px * var(--drive-k)); --d-m: calc(32px * var(--drive-k));
    --d-s: calc(28px * var(--drive-k)); --d-xs: 18px; --d-label: 14px;
    --status-h: 40px;
  }
}

@media (prefers-reduced-motion: reduce) { :root { --t-fast: 0ms; --t-fade: 0ms; } }

/* ---- legacy aliases: existing views keep working. Remove in phase 6 once nothing uses them. ---- */
:root {
  --bg: var(--bg-1);
  --panel: var(--surface-1);
  --panel-2: var(--surface-2);
  --border: var(--line);
  --text: var(--text-1);
  --muted: var(--text-2);
  --faint: var(--text-3);          /* was #5b6574 (3.3:1); now 5.7:1 */
  --gain: var(--ahead);
  --loss: var(--warn);
  --bad: var(--danger);
  --best: var(--t-purple);
  --ref: var(--info);
  --cmp: var(--text-1);
  --radius: var(--r-panel);
  --mono: var(--font-mono);
  --sans: var(--font-ui);
}
```

Phase 0 also makes four rule changes in `app.css`:

- `button.primary` takes `color: var(--on-accent)`. White on orange is 2.86:1 today and fails WCAG.
- `.badge.synthetic` takes `color: var(--synthetic); border-color: var(--synthetic); background: var(--hatch-synthetic)`.
  Purple then means timing only.
- A global `:focus-visible { outline: 0; box-shadow: var(--focus-ring); }`.
- `.num` uses `font-family: var(--font-num)`, but **only inside the new shell**. Existing views keep `--mono` until
  they are restyled, so their table columns do not shift.

### 6.2 Contrast (measured)

All ratios were computed with the WCAG 2.x formula. Targets: **7:1** for Drive values, **4.5:1** for text, **3:1**
for UI boundaries and large bands.

| Pair | Dark | Light | Night |
|---|---|---|---|
| `--text-1` on panel | 16.2 | 18.9 | 12.4 |
| `--text-2` on panel | 8.6 | 7.7 | 6.4 |
| `--text-3` on panel | 5.7 | 5.9 | 5.0 |
| `--t-purple` / `--t-green` / `--t-yellow` on panel (dark) or ink on fill (light) | 7.5 / 10.8 / 12.7 | 7.1 / 5.5 / 13.1 | 6.3 / 8.6 / 10.3 |
| `--ahead` / `--behind` on `--bg-0` | 12.0 / 6.5 | 5.1 / 5.2 | 9.2 / 5.3 |
| `--accent` on panel; ink on accent | 6.4; 6.6 | 4.9 on `--surface-2`; 5.7 | 5.5 |
| `--warn` / `--info` / `--synthetic` | 10.0 / 9.2 / 7.7 | 5.4 / 5.9 / 6.0 | |
| `--line-strong` (control boundary) | 3.2 | 3.3 | |
| Flag ink on fill: yellow / amber / red / blue | 13.1 / 10.4 / 5.0 / 9.5 | same | |
| Red-green safe: blue / orange on panel | 9.2 / 8.9 | 5.1 / 5.4 | |

`web/scripts/contrast.mjs` (phase 0) recomputes this table from `tokens.css` and fails when a pair drops below its
target.

### 6.3 Typography

| Role | Stack | Notes |
|---|---|---|
| **Numerals** (timing, delta, distances) | `--font-num`: **DIN Condensed** (700) → DIN Alternate → Avenir Next Condensed → Barlow Semi Condensed → Roboto Condensed → Arial Narrow | Ships with macOS and iPadOS, so nothing is downloaded. **Measured on this Mac:** all ten digits are the same width (tabular by default), and `+`, `−` and `±` are the font's own glyphs. The sign is wide (1.6 × a digit), so the delta draws it at `scaleX(.62)`. ▸ and the arrows are SVG, because these faces do not have them. Original typefaces, not any broadcast face |
| **Labels** (caps) | `--font-label`: **Avenir Next Condensed** 600 | Real weights (500 / 600 / 700). Caps, `letter-spacing: .08em`, `--text-3` |
| **Body** (Review sentences, Settings) | `--font-ui`: system-ui | Best for paragraphs. 16 px, line height 1.5 |
| **Code / IDs** | `--font-mono` | Fact IDs, capture names, IPs |

**Non-Apple devices** fall through to Roboto Condensed or Arial Narrow. If one of them joins the rig, bundle
**Barlow Semi Condensed** 500 and 700 (SIL OFL 1.1, Latin subset of about 25 KB per weight, in
`web/public/fonts/`, with a `docs/licences.md` entry). That is an optional phase 6 task.

Numbers never use caps letter-spacing. Every number uses `font-variant-numeric: tabular-nums`, which does no harm
in faces that are already tabular.

### 6.4 Shape, elevation, signature

- **Square timing cells** (`--r-cell: 2px`) with a **6 px top bar** in the timing colour. This is the signature
  element, recognisable from across the room.
- Panels: `--r-panel` 6 px, 1 px `--line` hairline, `--surface-1`. Elevation comes from surface steps, never from
  shadows. **No `backdrop-filter` on Drive** (it costs frame time in iPad Safari).
- Panel headers (Review, Car wall): an 18 px caps label on the left and a state or evidence tag on the right.
- Hatching means "not real data" (synthetic). A dashed outline means "planned / needs backend" (only in mockups and
  docs, never in the app).
- **Trademarks:** no F1, FIA or team names, logos, typefaces or livery colours in the UI chrome. Track and car names
  appear only as data from the game. The Pitwall mark is our own.

### 6.5 Motion

- Drive numbers never animate. They change at the snapshot rate, and the delta at no more than 10 Hz.
- Bars ease over `--t-fast` (100 ms linear), which suits 20 Hz updates.
- A completed sector does **one** 600 ms fade of its fill. There are no pulses, glows or blinking (WCAG 2.3.1), and
  flag bands appear without animation.
- `prefers-reduced-motion` sets both durations to 0.
- Pages outside Drive may cross-fade in 120 ms or less. Drive has no page transitions.

### 6.6 Copy rules

- Unknown is `-`. Empty states say why, in words ("No laps yet: drive a clean lap").
- The minus sign is `−` (U+2212). Times are `m:ss.SSS`, sectors `ss.SSS`, and distances `285 m` (a space before the
  unit, a thin space for thousands in prose: `4 210 m`).
- Coaching text is the backend's own text. The UI may add an evidence line built from the observation's fields
  (`impact_s`, `confidence`, `consistency`): "Seen on 3 of your last 5 laps · about 0.12 s a lap · confidence high".
- Confidence in words: high when ≥ 0.8, medium when 0.6 to 0.8, low when < 0.6. The number stays in the "Why?"
  drawer.
- Plain labels: "Time lost here" (not "Δt"), "Braked" (not "Brake pt Δ"), "Slowest speed" (not "V-min"), "Clean
  laps", "Your target lap" (beginners) or "Reference" (others). The glossary explains terms, never actions.

---

## 7. Components → files

New files only. Existing files are listed where they are reused. **Owner** is the lane from section 12.

| Component | File (new) | Reuses / data | Phase · lane |
|---|---|---|---|
| Tokens | `web/src/styles/tokens.css` | Section 6.1 | 0 · T |
| Primitives: `Button`, `Pill`, `Badge` (incl. synthetic hatch), `Segmented`, `Sheet`, `Toast` (+ `toast.svelte.ts`), `Avatar`, `Icon` (inline SVG set), `EmptyState` | `web/src/ui/*.svelte` | Tokens | 1 · T |
| `TimingValue` (value + status → colour, fill, tag; `-` for null) | `web/src/ui/TimingValue.svelte` | `drive/logic/timing.ts` | 1 · T |
| `TimingCell` (top bar, label, tag, value; sizes `drive` / `app`) | `web/src/ui/TimingCell.svelte` | `TimingValue` | 1 · T |
| `KpiTile` | `web/src/ui/KpiTile.svelte` | | 1 · T |
| Router (route table, redirects that keep `?query`, remembered sub-pages, `replaceState`) | `web/src/lib/router.svelte.ts`, `web/src/lib/routes.ts` | | 1 · S |
| Display prefs (theme, night, cvd, drive size, dim nav, drive lock), with try/catch storage, setting `data-*` on `<html>` | `web/src/lib/prefs.svelte.ts` | Replaces the theme code in `App.svelte` | 1 · S |
| `Shell`, `NavRail`, `TabBar`, `SubNav`, `AppBar`, `ConnPill`, `RadioPill`, `DriverButton` (wraps `DriverChip`), `driveLock.svelte.ts` | `web/src/shell/*` | `live`, `radio` (read and call only), `drivers` | 1 · S |
| `App.svelte` | **edited** (shell only) | Mounts `Shell`; existing views become pages | 1 · S |
| Page stubs for every new page (so `routes.ts` is never edited by other lanes) | `web/src/{drive,review,setup,settings}/*Page.svelte` | Placeholder "Coming in phase n" | 1 · S |
| Pure formatters (`UNKNOWN`, `lapClock`, `timeMs`, `sectorMs`, `signedDelta`, `metres`, `ago`) | `web/src/lib/fmt.ts` | `format.ts` stays as it is | 1 · D |
| Drive logic | `web/src/drive/logic/{driveState,corner,delta,timing,cues,lapStrip,flags}.ts`, `web/src/drive/types.ts` | Section 4.6 | 1 · D |
| Tests and fixtures | `web/tests/drive/*.test.ts`, `web/tests/fixtures/*.json` | `node --test` | 1 · D |
| `DashView` (grid, state switch, 10 Hz delta throttle) | `web/src/drive/DashView.svelte` | `live`, logic | 2 · DV |
| `StatusSlot`, `FlagBand`, `EventChip` | `web/src/drive/StatusSlot.svelte`, `FlagBand.svelte` | | 2 · DV |
| `DeltaHero` | `web/src/drive/DeltaHero.svelte` | `deltaView` | 2 · DV |
| `CornerCue` | `web/src/drive/CornerCue.svelte` | `cornerAhead`, `cueView` | 2 · DV |
| `TimingStrip` | `web/src/drive/TimingStrip.svelte` | `TimingCell`, `timing.ts` | 2 · DV |
| `LapStrip` (static SVG; the car moves by `transform`) | `web/src/drive/LapStrip.svelte` | `lapStrip` | 2 · DV |
| State panels: `ReadyCard`, `BetweenRuns`, `PitLane`, `SessionComplete`, `NoData` | `web/src/drive/states/*.svelte` | `drivers`, `radio`, `/api/connect` | 2 · DV |
| Wake lock helper | `web/src/lib/wake.ts` | | 2 · DV |
| `CarPage` (phase 1–4: wraps `LiveView`; phase 5: `CarView` wall) | `web/src/drive/CarPage.svelte` | `TrackMap`, `Chart` | 1 / 5 · S / DV |
| `RadioPage` (wraps `RadioView`) | `web/src/drive/RadioPage.svelte` | | 1 · S |
| Review logic (KPIs, density by skill, plain words, progress derivations) | `web/src/review/logic/*.ts`, `web/tests/review/*.test.ts` | | 2 · R |
| `SessionsPage`, `SessionPage` (tabs), `SummaryTab`, `LapsCompareTab`, `CornersTab` | `web/src/review/*.svelte` | `Chart`, `TrackMap`, `SectorBands` (read only), `/api/sessions/*`, `/api/compare` | 3 · R |
| `WorkOnCard`, `CoachingCard`, `TimingTable`, `LapTimesChart`, `CornerBars`, `CornerExplainer`, `FamilyBoard`, `Glossary` | `web/src/review/*.svelte` | | 3 · R |
| `CoachingPage`, `ProgressPage` | `web/src/review/*.svelte` | `/api/drivers/{id}/sessions`, D5 | 4 · R |
| `EngineerPage` (wraps `EngineerView`, passes `session`/`q`) | `web/src/review/EngineerPage.svelte`, small edit to `views/EngineerView.svelte` (not a hot file) | | 3 · R |
| `ChecklistPage` (+ `setup/logic/checklist.ts`) | `web/src/setup/ChecklistPage.svelte` | `/api/connect`, `drivers`, `radio`, `/api/rig/check` | 3 · X |
| `DisplayPage` | `web/src/settings/DisplayPage.svelte` | `prefs` | 3 · X |
| `RadioVoicePage` | `web/src/settings/RadioVoicePage.svelte` | Moved from `RadioView` | 5 · X |
| Contrast script | `web/scripts/contrast.mjs` | `tokens.css` | 0 · T |
| PWA meta, manifest | `web/index.html` (edit), `web/public/manifest.webmanifest` | | 0 · T |

---

## 8. Review

### 8.1 Sessions (`#/review/sessions`)

- **"Last session" card** at the top: track · type · when · driver avatar; best lap (timing-coloured); laps
  (clean/total); coaching points count; **Open** (56 px).
- **List grouped by day** (Today, Yesterday, then dates), as timing-tower rows (56 px; two lines on phone).
  Columns: driver avatar, track, session type, laps clean/total, **best clean lap**, `PB set` when the driver's
  `stats.best_laps` entry points at this session, and evidence chips (`SYNTHETIC` hatched, `REPLAY`).
- **Filter chips** (44 px): Everyone, then each driver (the existing server-side filter), plus a track picker.
- **Reassign** (exists today) moves to the row's `⋯` menu as a sheet, with the existing confirmation copy.
- **iPad:** master-detail (list 360 px, selected Summary on the right). **Phone:** list, then push to the session.

### 8.2 Session › Summary (`#/review/s/<id>`): "how did it go, and what next?"

Header: track · type · date · driver avatar · car · weather · evidence chips. Actions: **Ask the engineer about
this session** (opens Review › Engineer with `?session=`) and **Report** (today's markdown report, in a sheet).

1. **KPI tiles** (4 across on iPad, 2 × 2 on phone; label 14, value 32, context 14, and a `?` glossary button):
   **Best lap** (timing-coloured with tag, "lap 5"), **Clean laps** ("8 of 12 · 4 not used ?", where the `?`
   explains flags in words), **Gained today** (first clean lap minus best clean lap), **Steadiest corner** (lowest
   `brake_point_std_m` over at least 3 laps, from `corner_summary`). Advanced profiles add **Best sectors combined**
   and **Reference used**.
2. **Work on** (1 / 3 / 5 cards by skill level). Source: `analysis.observations`, non-positive, ranked by
   `priority` then `impact_s`, preferring corners with a repeated `consistency`. Each card shows a corner tag
   (official label and name), a **mini map** (`TrackMap`, 120 px, corner highlighted), the **coach's text
   verbatim** (D6 `text_simple` for profiles with `simple_wording`), an evidence line, and three buttons: **See it on
   the lap** (→ Laps & compare `?at=<apex>`), **Why?** (a drawer with that corner's comparison numbers in plain
   words) and **Ask the engineer** (pre-filled: "Why am I losing time at T9?").
3. **Went well**: positive observations (up to 3), in green.
4. **Lap times**: uPlot bars, one per lap, **taller = faster** and labelled "faster ↑" (the same convention as
   Progress). Laps that are not clean are hatched, with the reason in words on tap. A reference line. The best lap
   is tagged.
5. **Where the time is**: corner bars from `corner_summary[].mean_time_delta_s`, sorted. Detail words come from the
   signs of `mean_brake_point_delta_m` and `mean_min_speed_delta_kph` ("braked about 12 m earlier", "4 km/h slower at
   the slowest point"). These are descriptions, not advice.
6. **Your best here**: a small chart of this driver's best clean lap per session at this track, with the **y axis
   inverted and labelled "faster ↑"**. It links to Progress.

### 8.3 Session › Laps & compare (`/laps?ref=&lap=&at=`)

- Two 56 px pickers: **A · Reference** (cyan) and **B · Compare**. Each opens a sheet listing laps with time,
  sectors (current-standing colours) and status words. Only clean laps can be A, as today. **Pin as reference**
  sits next to A, with an inline confirmation.
- **Family compare:** A can be another driver's best lap at this track, from their `stats.best_laps`. The existing
  `/api/compare` already accepts any two lap ids, and its compatibility checks still apply.
- Charts (uPlot, cursor-synced): **delta by distance** with neutral sector bands and corner labels, then
  **speed**. **Pedals** are collapsed for beginners ("Show pedals"). **Steering** is shown for advanced profiles
  only.
- iPad right column: the **track map coloured by corner delta** (green gained, red lost, neutral within ±0.01 s)
  and the **corner explainer**. It follows the cursor and turns `comparison.corners` numbers into neutral words, for
  example: "At T9 you braked 12 m earlier, slowest speed 4 km/h lower, 0.11 s slower". The coach's observation for
  that corner sits under it.
- Corner table in plain words: Corner · Time lost here · Braked · Slowest speed · Exit speed · Full throttle.
- **Compatibility warnings** (`comparison.compatibility`) appear as an amber strip above the charts. A blocked
  comparison shows its reason instead of the charts.
- Phone: the pickers, the corner list as cards, then the delta chart. The other charts sit behind "Show telemetry".

### 8.4 Session › Corners (`/corners`): "what keeps happening at T9?"

- Coaching is grouped **by corner**, sorted by average time lost. Each group shows the official label and name,
  the session averages from `corner_summary` (time, brake point mean and spread, slowest speed), and the laps where
  an observation fired, each with its text and evidence.
- Filter: Work on · Went well · All. Incident observations are greyed with "not used for technique advice".
- The glossary is pinned on the right on iPad, and is a sheet on phone.

### 8.5 Review › Coaching (`#/review/coaching`): the plan

Per driver (avatar chips) and per track and car.

| Block | Content | Data |
|---|---|---|
| **Working on now** | Up to 3 corners, each with a trend arrow (better / same / worse), the latest observation verbatim, and **See it** | Tier 1: latest session's `corner_summary` (no arrow). D5: the last 3 to 5 sessions, with arrows |
| **Habits** | Observations carrying a `consistency` string ("4 of the last 5 laps"), verbatim | `analysis.observations` |
| **Recently fixed** | Corners whose average loss fell below the coaching threshold | D5 |
| **What the radio will focus on next time** | `cues.focus` with `cues.cues[].reason` | Live snapshot, when this driver is in the seat and a plan exists. Otherwise `-` with the reason |

### 8.6 Review › Progress (`#/review/progress`)

Driver chips (56 px) and a track + car picker (a sheet of the combinations this driver has driven). The page is
framed as three questions, and each chart carries **one computed sentence** (never an LLM): "Your best here dropped
1.3 s over 4 sessions".

| Block | Tier 1 (today) | With D5 |
|---|---|---|
| **Getting faster?** Best clean lap per session, **y inverted, "faster ↑"**. PB points green, household record purple (D2) | `/api/drivers/{id}/sessions` (`best_clean_ms`, `started_unix`, `track_id`, `car_name`, `synthetic`). Synthetic and replay excluded by default, with a toggle | Adds the median clean lap |
| **Getting steadier?** Spread of clean laps per session | none | Shown |
| **What changed?** Corner trends (small multiples) and habit counts | none | Shown |
| **Milestones** | First clean lap at a track, each new PB with its gain, first session with 10 clean laps (derived) | PB history |
| **Family board** per track + car | Every driver's `stats.best_laps`, the gap to the leader, the record in purple | Car scope exact |
| Totals | `stats.{sessions, laps, clean_laps, tracks}` | |

### 8.7 Review › Engineer

Today's `EngineerView`, with the session preselected from `?session=` and the question pre-filled from `?q=`. The
LLM status pill sits in the header. The "How answers work" text moves into a collapsible side panel, the facts drawer
is kept, and suggestion chips are 44 px. The line "answers are grounded, or replaced by a deterministic answer"
stays.

### 8.8 Density by skill level

Read from the **viewed** driver's `preferences.skill_level`, not from a global switch. A beginner's sessions open
simplified and an advanced driver's open in full. Anyone can expand.

| Page | Beginner | Intermediate | Advanced |
|---|---|---|---|
| Drive › Dash | Delta label "vs your target lap"; projected hidden; Drive lock on | Projected shown | Projected shown |
| Summary: KPI tiles | 4 | 4 | 6 |
| Summary: Work on cards | 1 (+ "Show more") | 3 | 5 |
| Coaching text | D6 `text_simple` where present | `text` | `text` |
| Compare charts | Delta + speed | + pedals | + pedals + steering |
| Corner table | Time + plain sentence | + braked, slowest speed | All columns, technical labels allowed |
| Glossary `?` buttons | Shown | Shown | Hidden |
| Progress | "Getting faster?", milestones, family board first | Same | Corner trends first |

---

## 9. Setup and Settings

**Setup** (getting ready to drive):

| Page | Content | Notes |
|---|---|---|
| **Checklist** (landing) | Four rows, each with a state dot, one line and one action: **Game** (`/api/connect` telemetry: "Receiving F1 25 from 192.0.2.30 · 60 packets/s" or "Listening on UDP 20777, waiting for the game" → *Connect*). **Driver** (who is in the seat → *Switch*). **Radio** (link, mic, wake lock, HTTPS warning → *Go live*). **Rig** (last rig check: pass / warn / fail / unknown counts → *Rig*). Then **Open Drive** (64 px) | Every row is existing data, put together. Setup opens here, and on Connect until the first packet has ever been received |
| **Drivers** | Today's `ProfilesView` (cards, put in the seat, edit) | First in the sub-nav after Checklist, because "who's driving" comes first |
| **Connect** | Today's `ConnectView` (now including Assetto Corsa) | Wrapped in phase 1, restyled in phase 5 |
| **Rig** **(hot)** | Today's `SetupView` (rig, recommendations, rig check, provenance tags). Rig check uses status dots (pass green, warn amber, fail red, unknown `-`), never timing colours | Wrapped until the rig fixes land |
| **Car setup** | Today's `CarSetupView` (recommendations, diff, experiments; `/api/carsetup`) | Wrapped in phase 1. Its old `#/carsetup` tab redirects here |

**Settings** (how Pitwall behaves, rarely visited):

| Page | Content |
|---|---|
| **Display** | Theme (Dark / Light / Match device), Drive text size (Standard / Large), Night dim, Colour vision (Standard / Red-green safe), Dim navigation on track (on), Drive lock (Off / **Beginner profiles** / Everyone), and a live preview of a timing cell and the delta under each choice. Stored per device |
| **Radio & voice** | Moved from `RadioView`'s settings block in phase 5: voice on/off, engineer voice (device / Mac), device voice, speaking speed, Mac voice, TTS status and diagnostics |
| **AI engineer** | Today's `SettingsView` |
| **System** | Today's `StatusView` (health, worker errors, local LLM, captures and replay, **synthetic demo** clearly labelled, capability matrix), plus build version and licences |

---

## 10. Accessibility and honesty checklist

- [ ] Every token pair meets its target (6.2). `contrast.mjs` passes in light, dark, night and red-green safe.
- [ ] Every interactive element is at least 44 × 44. Drive actions are at least 56, and glove actions 64.
- [ ] Nothing relies on colour alone: signs, bar direction, `AHEAD`/`BEHIND`/`LEVEL`, `REC`/`PB`/`SB`/`INV` tags,
      band words.
- [ ] `DeltaHero` and timing cells have `aria-label` summaries. Fast-changing values are `aria-live="off"`.
      Banners are `role="status"`, and the red flag is `role="alert"`. Each page has one `h1`.
- [ ] Focus ring: 2 px `--accent` with a 2 px offset, on every control. Keyboard can reach everything on Mac.
- [ ] `prefers-reduced-motion` respected. Nothing flashes more than 3 times a second.
- [ ] Review, Setup and Settings use `rem` sizes, so they follow Dynamic Type. Drive uses fixed glance tokens.
- [ ] **Honesty audit:** with the game paused, unplugged and in replay, no screen shows a number that is not in the
      snapshot or the API. `SYNTHETIC` is visible on every page during a synthetic replay. Purple never appears
      without D2.
- [ ] Unknown is `-` everywhere. `rg -- '—|--:--' web/src` finds no placeholders.

---

## 11. Data contract

**have** means in the current API. **derive** means computed in the browser from existing fields. **D1 to D6** are
backend additions. Each is additive, returns `null` when unknown, follows the evidence tiers, and has a fallback in
the UI until it lands.

| UI element | Source | Status |
|---|---|---|
| Delta, reference label | `delta_s`, `reference.{lap_number, lap_time_ms, session_id}` | have |
| Projected lap | `reference.lap_time_ms + delta_s` | derive |
| Corner ahead, distance | `track_model.corners[].{entry_m, apex_m, seg_*}`, `frame.lap_distance_m`, `skeleton.track_length_m` | derive |
| Official label and name | `track_model.corners[].{label, display_name, identity_tier}` (in the live payload via `track_model_payload`) | have |
| Cue next, last outcome, focus, notches | `cues.{next, last, timing.margin_m, focus, cues[].{target_m, reason}, mode, muted, reason}` | have |
| Lap clock, lap n/total, invalid, position | `frame.*`, `session.total_laps` | have |
| Completed sectors, current lap | none | **D1** |
| Completed laps with sectors | `laps[]` (20 newest) | have |
| Session best lap and sectors | `laps[]` | derive (exact with D2) |
| PB and household record (lap and sectors, per car) | `drivers[].stats.best_laps` (lap only, per track) | **D2** |
| Exact garage / out-lap | `frame.pit_status`, `speed_kph` (heuristic) | **D3** |
| Session ended / red flag | `events[]` (last 10) | derive (exact with **D4**) |
| Flags, safety car | `marshal_flags`, `skeleton.marshal_zones`, `session.safety_car_status` | have |
| Pit lane, pit limit | `frame.pit_status`, `skeleton.pit_speed_limit_kph` | have |
| Coaching point shown on Drive | `observations[]` (unfiltered) | **D6** for parity with the radio |
| Session review | `/api/sessions/{id}`, `/analysis`, `/report`, `/api/compare`, `/api/laps/{id}/trace` | have |
| Progress beyond lap level | `/api/drivers/{id}/sessions` | **D5** |
| Radio state, driver | `radio` store, `drivers` store | have |
| Rig check counts | `/api/rig/check` (`pass`, `warn`, `fail`, `info`, `unknown`) | have |

| Id | Addition | Files | UI without it |
|---|---|---|---|
| **D1** | `frame.current_lap_sector_ms: [s1, s2]` from the game's own lap data (F1 `sector1TimeMSPart` / `MinutesPart`, which are already parsed for completed laps). `null` for games that do not send them | `model/telemetry.py`, `adapters/f1/adapter.py`, `core/live.py` (`frame_to_dict`), tests (`test_f1_protocol.py` stays green) | Sector cells show the last lap under a `LAST LAP · L7` caption |
| **D2** | `snapshot.bests = {session, driver, household}`, each `{lap_ms, sectors_ms[3]}` (plus `set_unix` / `driver_id`), for the current game + track + car. Clean laps only. Synthetic and replay excluded. Sector bests per sector. Sent with the 5 s static payload and recomputed after each lap | `storage/repo.py`, `core/live.py`, `core/lap_processor.py`, tests | Green `SB` and yellow only; no purple, no `PB` |
| **D3** | `frame.driver_status` from F1's driver status (`in_garage`, `flying_lap`, `in_lap`, `out_lap`, `on_track`); `null` elsewhere | `adapters/f1/adapter.py`, `model/telemetry.py`, `core/live.py` | Pre-session and between runs use the `pit_status` / speed heuristic |
| **D4** | `snapshot.session_state`: `running` / `ended` / `red_flag`, kept server-side from events (`session_started`, `lights_out`, `chequered_flag`, `session_ended`, `red_flag`) | `core/live.py`, tests | Derived from the last 10 events |
| **D5** | `GET /api/drivers/{id}/progress?game&track_id&car`: per session `{session_id, started_unix, laps, clean_laps, best_clean_ms, median_clean_ms, spread_ms, corners: {corner: mean_time_delta_s}, habits: {kind: count}}`, plus PB history | `storage/repo.py`, `api/routes_drivers.py`, tests | Progress shows lap level and the family board only |
| **D6** | `snapshot.coach = {lap_number, picked: [...], by_corner: {...}}`: the observations the radio picks for the latest lap under the seated driver's coaching limits (`apply_coaching_limits`). Each observation also gains `text_simple` (one idea, plain words, same facts, never "brake later" on its own) written by the coach | New `coach/selection.py` (shared selection), `core/live.py`, `analysis/coaching.py`, and `voice/proactive.py` switched to the shared selection in the same PR (the voice work is committed) | Drive shows the top observation by priority, which may differ from what the radio said |

Not needed: proposal C's B3 (separate corner label and name). Corners already carry `label` and `display_name`.
Also confirmed: `cues.next.corner` and `cues.cues[].corner` are the learned corner names, the same keys as
`track_model.corners[].name` and `corner_text`.

**Work in progress elsewhere that the UI can use later:** `GET /api/track/outline` (uncommitted
`api/routes_track.py`) returns the game's circuit outline before Pitwall has learned the track, labelled as a
shipped seed with its MIT attribution. Once it lands, the Car map and the Ready card can draw the circuit before the
first clean lap, with that label. Corner ticks on the lap strip still need the learned model. `GET /api/track/prior`
(physics heavy-stop windows) is "never braking targets", so it never feeds the Drive cue panel.

---

## 12. Implementation plan

### 12.1 Lanes (parallel engineers) and file ownership

Each lane owns its files outright. **A file has exactly one owner in any phase**, so lanes never edit the same
file.

| Lane | Owns (creates or edits) | Must not edit |
|---|---|---|
| **T · tokens & primitives** | `web/src/styles/tokens.css`, `web/src/app.css`, `web/src/ui/*`, `web/scripts/contrast.mjs`, `web/index.html`, `web/public/manifest.webmanifest`. Phase 0 only: `web/src/lib/format.ts` (unknown glyph → `-`) and `web/src/lib/SectorBands.svelte` (`SECTOR_COLOURS` → neutral tints, `.syn` → `--synthetic`) | Views, `App.svelte` |
| **S · shell & routing** | `web/src/App.svelte`, `web/src/lib/router.svelte.ts`, `web/src/lib/routes.ts`, `web/src/lib/prefs.svelte.ts`, `web/src/shell/*`, page stubs and wrappers (`drive/CarPage.svelte`, `drive/RadioPage.svelte`, every `*Page.svelte` stub) | Hot files (12.3), `api.ts` |
| **D · Drive logic** (cloud OK) | `web/src/drive/logic/*`, `web/src/drive/types.ts`, `web/src/lib/fmt.ts`, `web/tests/drive/*`, `web/tests/fixtures/*`, `web/package.json` (`"test": "node --test tests/"`), `web/tsconfig.json` (`allowImportingTsExtensions: true`) | Svelte files |
| **DV · Drive views** | `web/src/drive/*.svelte` (except the wrappers S created), `web/src/drive/states/*`, `web/src/lib/wake.ts`. Fills in the stub `drive/DashView.svelte` | `drive/logic/*` (asks lane D) |
| **R · Review** | `web/src/review/**`, `web/tests/review/*`, `web/src/views/EngineerView.svelte` (small prop change), and later `TrackMap.svelte` / `Chart.svelte` if a prop is needed (phase 3 only) | Drive files |
| **X · Setup & Settings** | `web/src/setup/**`, `web/src/settings/**`; in phase 5, `web/src/views/RadioView.svelte` (settings move) | Shell |
| **B · Backend** (cloud OK) | D1-D6 Python and tests. **One engineer, serial PRs**, because D1, D2, D3, D4 and D6 all touch `core/live.py` | `adapters/f1/adapter.py` and `model/telemetry.py` (D1, D3) until the uncommitted field-model work in them lands |

**Stub trick.** In phase 1, lane S creates every new page file as a stub ("Coming in phase n") and registers it in
`routes.ts`. After that, lanes DV, R and X only fill in files they own. Nobody else edits `routes.ts` or
`App.svelte`.

**Shared types.** New response types live in each lane's own module (`drive/types.ts`, `review/types.ts`) and
extend `Snapshot` with optional fields. `web/src/lib/api.ts` stays frozen during the upgrade, so it never becomes a
merge point.

### 12.2 Phases

Each phase ships on its own and keeps `make check` green (it already runs `npm run check`). Once lane D adds the
script, `cd web && npm test` must stay green too. After each phase: `make web`,
`scripts/pitwall-service.sh restart`, and a look on the iPad.

| Phase | Lanes in parallel | File-level tasks | Where | Done when |
|---|---|---|---|---|
| **0 · Foundations** (½-1 day) | T | Create `styles/tokens.css` (6.1). In `app.css`: import it, then fix `button.primary` ink, the synthetic hatch and the focus ring. In `format.ts`, change the unknown glyph to `-`. In `SectorBands.svelte`, make the sector colours neutral. Add the PWA meta to `index.html` and create `manifest.webmanifest`. Create `scripts/contrast.mjs` | **Here** | All 11 existing views render with only colour changes; contrast script passes; old Live checked on the iPad |
| **1 · Shell + logic + D1** | **S** ∥ **T** ∥ **D** ∥ **B** | **S:** `router.svelte.ts`, `routes.ts` (table, legacy redirects keeping `?query`, remembered sub-pages), `prefs.svelte.ts`, `shell/*`, `App.svelte` mounting the existing views (Dash = LiveView for now), all page stubs. **T:** `ui/*` primitives including `TimingValue` and `TimingCell`. **D:** `drive/types.ts`, `drive/logic/*`, `lib/fmt.ts`, tests and fixtures, `package.json` test script, tsconfig flag. **B:** D1 | S, T **here**. D, B **cloud** (after commit) | Every legacy hash lands on the right page, including `#/radio?token=…`; the 44 px audit passes; phone tab bar works; the radio keeps running across areas; `npm test` is green with fixtures for every state; D1 is green on the recorded fixture |
| **2 · Drive Dash** | **DV** ∥ **B** ∥ **R** | **DV:** `DashView`, `StatusSlot`, `FlagBand`, `DeltaHero`, `CornerCue`, `TimingStrip`, `LapStrip`, `states/*`, `wake.ts`; Drive lock wiring through `shell/driveLock.svelte.ts` (S hands over the file). **B:** D2, then D3. **R:** `review/logic/*` with tests | DV **here** (iPad, PS5). B, R **cloud** | Replays of the recorded Austria fixture and `pitwall simulate` reach every state and overlay; **glance test passed by each family driver on the rig**; no long task over 50 ms in 10 minutes of iPad Safari profiling |
| **3 · Review + Setup/Settings** | **R** ∥ **X** ∥ **B** | **R:** `SessionsPage`, `SessionPage` (Summary / Laps & compare / Corners), cards, charts, `EngineerPage` and the `EngineerView` prop. **X:** `ChecklistPage`, `DisplayPage`. **B:** D4, then D6 (`coach/selection.py`, `core/live.py`, `analysis/coaching.py`) | R **cloud then here** (looked at on the iPad). X **here**. B **cloud** | A beginner can say their best lap and biggest time loss from the Summary alone; they find "what to work on" in 2 taps; Checklist reflects real state |
| **4 · Coaching plan + Progress** | **R** ∥ **B** | **R:** `CoachingPage`, `ProgressPage`, `FamilyBoard`, milestones. **B:** D5 (`repo.py`, `routes_drivers.py`) | Cloud, then a look here | Each driver's progress page answers "getting faster?" with one computed sentence |
| **5 · Moves inside existing views** (`SetupView` only after the rig work lands) | **X** ∥ **DV** ∥ **S** | **X:** Radio settings move to `settings/RadioVoicePage.svelte` (edits `RadioView.svelte`). **DV:** `CarView` wall replaces the `LiveView` wrap. **S:** restyle wrappers for `ConnectView`, `CarSetupView`, `ProfilesView`, `DriverChip`, then `SetupView` | **Here** | The old views are reachable only through redirects; the Radio page is controls only |
| **6 · Clean-up** | T ∥ S | Remove the legacy aliases; base font to 16 px; `.num` uses `--font-num` everywhere; delete `LiveView` and `SessionView` once unused; add the web tests to `make check` in the `Makefile`; update `docs/status.md`, `docs/architecture.md`, and `docs/licences.md` only if Barlow is bundled | Here | `rg -- '--panel-2\|--muted\|--faint' web/src` finds nothing |

### 12.3 Hot files: wrap, don't edit

The radio, voice and Connect work was committed in `716468b`. At 01:00 on 2026-10-11 these files are still being
edited (uncommitted): `web/src/lib/rig.ts`, `web/src/views/SetupView.svelte`, `src/pitwall/rig/*`,
`src/pitwall/api/routes_rig.py`, `src/pitwall/adapters/f1/adapter.py`, `src/pitwall/model/telemetry.py`,
`src/pitwall/sim/f1_stream.py`, `docs/status.md`, plus the untracked track-outline and field-model modules. Check
`git status` again before each phase. Until a file's branch lands:

- the new UI mounts the view unchanged inside the shell, and every edit to it waits for phase 5;
- backend item D1 and D3 wait for the adapter and telemetry work;
- the new UI **reads and calls** the radio store's public API (`phase`, `conn`, `mic`, `current`, `pttHeld`,
  `goLive()`, `pttPress()`, `pttRelease()`) and does not edit `radio.svelte.ts`. The store is shared by every page, so
  this keeps the radio stable while the shell changes around it.

### 12.4 Here or cloud, per lane

| Work | Where | Why |
|---|---|---|
| Phase 0, lane S, lane DV, lane X, phase 5, all on-rig acceptance | **Here** | Needs the iPad at 70 cm, the PS5, Tailscale HTTPS for the mic and wake lock, the launchd service, the room light, and the uncommitted hot files |
| Lane D (pure logic + tests), lane B (D1-D6), lane R logic and first build of the pages | **Cloud is fine** once the current work is committed and pushed | Self-contained, testable on recorded and synthetic data (`tests/fixtures/recorded`, `pitwall simulate`). Follow `docs/cloud-tasks.md`: own branch, PR, list "Integration needed". They can never claim live evidence |

### 12.5 Acceptance on the rig

1. **Glance test.** iPad on its mount at about 70 cm, room lights as when racing. Each driver does 3 laps. From
   0.5 s glances they can say the delta's sign and first digit, the next corner, and whether a braking call is
   coming. If anyone squints, raise the Drive tokens one step or switch on Large.
2. **States.** The recorded fixture, the synthetic demo and a live PS5 session together reach every state and
   overlay in 4.5. Nothing moves when a state changes.
3. **Honesty.** Paused, unplugged and in replay, no value appears that the snapshot does not contain.
4. **Family test.** Two other drivers (a beginner and an intermediate) each open their own last session's Summary
   and explain their best lap and biggest time loss without help.
5. **Performance.** One hour on Dash keeps a steady frame rate on the iPad, and memory does not grow.
6. **Radio.** The radio stays live while moving between areas, and push-to-talk works from the Dash pill and from
   the wheel.

---

## 13. Which dashboard: `web/` or `web-react/`

**The situation (2026-10-11).** Commit `716468b` added `web-react/`: React 19, HeroUI v3 (with HeroUI Pro installed
under licence), Tailwind v4, Vite 8, vitest, served by FastAPI at `/next/`. Its README calls it "the successor to the
Svelte dashboard". It already has the four areas, a hash router with query-preserving legacy redirects
(`src/lib/route-parse.ts`, with tests), and a token file meant to take the design (`src/styles/tokens.css`). Only
Drive › Live is ported. Every other page is a placeholder, so Review, Setup and Settings still live in `web/`.

| | Stay on `web/` (Svelte) | Move to `web-react/` |
|---|---|---|
| Features today | All 11 views work | Live only. The rest must be ported before the old app can go |
| Dependencies | None new (Svelte, uPlot) | React, HeroUI (+ Pro), Tailwind, already committed |
| Shell work | New (lane S) | Mostly there: adjust `routes.tsx` and `route-parse.ts` to section 2.3 |
| Drive screen | Plain Svelte + tokens | Plain React elements + tokens. **No HeroUI components on Dash** (no portals, animation layers or overlays at 20 Hz) |
| Risk | Two shells exist if `web-react/` carries on anyway | The porting effort before parity, and a heavier bundle on the iPad |

**Recommendation: decide once, before phase 1, and freeze the other dashboard apart from fixes.** If James means
`web-react/` to replace `web/`, build this design there: the effort then goes into ports that are needed anyway, and
nothing gets built twice. If not, pause `web-react/` and follow section 12 as written.

**File map if the target is `web-react/`** (the design, phases and lanes stay the same):

| Spec item | `web/` path (section 12) | `web-react/` home |
|---|---|---|
| Tokens (6.1) | `web/src/styles/tokens.css` | `web-react/src/styles/tokens.css`: keep the HeroUI semantic variables, replace the `--pw-*` domain tokens with section 6.1 (prefixed `--pw-`), and set `--pw-font-timing` to the `--font-num` stack (today it is monospace) |
| Routes, redirects | `web/src/lib/routes.ts`, `router.svelte.ts` | `web-react/src/routes.tsx` and `src/lib/route-parse.ts`. Changes: `DEFAULT_PAGE` drive → `dash` (or keep the id `live` labelled Dash), setup → `checklist`, settings → `display`; Drivers moves from Settings to Setup; Review gets Coaching, Progress and Engineer; the session gets Summary / Laps & compare / Corners |
| Display prefs | `web/src/lib/prefs.svelte.ts` | Extend `web-react/src/lib/theme.ts` (night, colour vision, drive size, dim nav, drive lock) |
| Shell (rail, tab bar, Drive sub-pages in the rail) | `web/src/shell/*` | `web-react/src/components/AppShell.tsx` |
| Drive logic and tests | `web/src/drive/logic/*.ts`, `node --test` | `web-react/src/lib/drive/*.ts`, vitest. The same code, because it is framework-free |
| Drive views | `web/src/drive/*.svelte` | `web-react/src/pages/drive/*` (`DrivePage.tsx` becomes Dash) |
| Review, Setup, Settings | `web/src/review/*`, `setup/*`, `settings/*` | `web-react/src/pages/{review,setup,settings}/*`. HeroUI components are fine here |
| Charts and map | `Chart.svelte` (uPlot), `TrackMap.svelte` | Port as thin React wrappers around uPlot and the same SVG logic. The brief keeps uPlot |

**Other coordination risks**

- **Uncommitted work** (12.3). Cloud lanes must wait for a commit and push, or they will build on stale files.
- **`core/live.py` is a merge point** for D1 to D6. Keep one backend engineer and serial PRs.
- **D1 and D3** edit `adapters/f1/adapter.py` and `model/telemetry.py`, which the field-model work is changing now.

---

## 14. Open questions for James

1. **Purple.** Household record (proposed, follows the broadcast convention) or "my all-time best"? Green `SB`/`PB`
   already gives each driver frequent rewards. If purple should be personal, it is one rule in `timing.ts`.
2. **Which iPad** is on the rig? The 11" is the baseline. A mini defaults to Large.
3. **Drive lock default:** beginner profiles only (proposed), everyone, or off?
4. **Speed and gear on Dash?** They are left off because the game's HUD shows them. They are on Car.
5. **`web/` or `web-react/`** (section 13). This one blocks phase 1.
6. **Red flag clearing.** No "red flag cleared" event is decoded today. D4 clears it on `lights_out`,
   `session_started` or `session_ended`; confirm against a real capture.
