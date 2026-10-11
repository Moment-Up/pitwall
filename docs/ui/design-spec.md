# Pitwall UI: design spec v2 (coach-first, React + HeroUI)

_2026-10-11. Status: **design, not implemented**. Version 2 replaces v1
([`design-spec-v1-base-A.md`](design-spec-v1-base-A.md), which used direction A as its base because the judges
preferred it). **James liked direction C (coach-first) most, so v2 starts from C**
([`proposal-coach-first.md`](proposal-coach-first.md)) and grafts only the compatible ideas of A
([`proposal-timing-screen.md`](proposal-timing-screen.md)) and B ([`proposal-pit-wall.md`](proposal-pit-wall.md)).
Target: the React dashboard in `web-react/` (React 19, HeroUI v3 `@heroui/react` 3.2.6, HeroUI Pro
`@heroui-pro/react` 1.0.0-beta.10, Tailwind CSS v4, Vite 8). Clickable mockup: [`mockup.html`](mockup.html)
(self-contained, every number is labelled sample data). v1's mockup is kept as
[`mockup-v1-base-A.html`](mockup-v1-base-A.html)._

_[critic] A critic pass (2026-10-11) checked this spec and the mockup against the user's choice (C), glanceability
at 70 cm, the installed HeroUI packages, the lanes and the existing API, and Review for beginners. Its edits are
marked **[critic]** in place and listed in section 17._

---

## 0. Summary

**The idea (C, unchanged).** While the car is moving, the iPad answers one question: **what do I do next?** The
hero is the **next corner** (official label and name), the **braking call** for it and the **one coaching point**
the engineer has for it, which is the same point the radio says. The delta to the reference is the strong second
element. Sector and lap times sit underneath in timing colours, the lap runs along a ribbon, and the radio lives
inside the Drive screen. Off track, **Review** is built around learning: what to work on, what went well, and
whether it is getting better, for each driver in the family.

### 0.1 What v2 keeps from C (the skeleton)

| C decision | Kept as |
|---|---|
| Four areas: **Drive · Review · Setup · Settings**, a left rail on iPad and a bottom tab bar on phones | Section 2 and 3. Sub-pages exactly as C: Drive = Coach · Car · Track · Radio; Review = Sessions · Coaching · Progress · Ask; Setup = Connect · Rig · Car setup; Settings = Drivers · Radio & voice · AI engineer · Display · System |
| **Drive › Coach hierarchy**: status row, then the hero (next corner + braking cue, chamfered card with the accent edge), the coach card under it, the delta in the right column, sectors and lap times below, the lap ribbon, the radio strip | Section 4. Same grid areas, same reading order, same slots |
| Radio inside Drive (strip with message, mic state, **Hold to talk** / **Go live**) and a mini radio bar elsewhere | 4.3 (radio strip), 3.5 (mini radio bar) |
| Pre-session **"Alex is in the seat · Not you? Switch driver"** Ready card | 4.9, enriched with v1's target and "between runs" content |
| Review in plain language: **Work on · Went well · Getting better?**, density by the viewed driver's skill level | Section 6 |
| One message, two channels (C's B6 = v1's D6): the screen shows the coaching point the radio picked | P7, D6 |
| Dark first, dim-room safe, Dim (night) mode, light theme for daytime Review, **Drive always dark** by default | Section 9 |

### 0.2 Grafts from A and B, and why none of them dilutes C

| Graft | From | What exactly | Why it does not dilute C |
|---|---|---|---|
| **Very large delta** | A (and B's precision rules) | The delta grows from C's 108 px mono (3 decimals) to **144 px** condensed numerals with **2 decimals**, rendered at most 10 times a second; neutral inside **±0.02 s** with the word `LEVEL`; `AHEAD` / `BEHIND` word; a ±1.0 s bar with end labels; `-` the moment telemetry is stale | It stays in C's secondary column (5 of 12 columns), right of and level with the hero, with no accent edge and no chamfer. The hero label grows from 96 to **112 px** at the same time, so the hero keeps the largest panel area (7 columns, two rows with the coach card), first reading position (top left), the only accent edge and the only coloured band (the cue). The delta is read peripherally (colour, sign, bar direction); the hero is what the eye fixates. No state ever moves the delta into the hero's slot. **[critic]** Checked on the rendered mockups: the 144 px condensed `−0.21` covers less ink (about 215 × 105 px) than C's own 108 px monospace `−0.214` (about 360 × 75 px), so the graft makes the delta taller, not heavier, and C's balance holds |
| **Fixed status slot with flag semantics** | B | C's 48 px status bar becomes a 52 px slot whose content is swapped, never stacked. **An outline means the data is in doubt** (stale, offline). **A fill means the track says** (flags, pit, session state). Band priority, 6 s incident chips and the wake-lock chip all live in this one slot | C already turned its status bar into the flag band. B only adds rules for what wins and how doubt looks. No other slot changes and the hero never moves down |
| **Dense "Car" wall for a second screen** | B | Drive › Car is B's pit wall: map, car, tyres and energy, inputs trace, laps by current standing, last-lap coaching, race control | It is a separate sub-page that is never the default. On track with a beginner in the seat it is behind the Drive lock. The Coach screen keeps C's calm layout; the wall is for a parent on the phone, or a Mac next to the rig |
| **Lap clock in tenths while running** | A, B | `LAP 1:09.5` while running; the completed lap shows milliseconds | Same cell, less flicker; nothing added |
| **Last braking-call outcome** | B (v1) | The radio strip shows the cue that just played with its outcome (`CUE · T7 brake · on time −3 m`) | It is the radio's own message, shown in C's radio strip. No new element |
| **Timing colour rule set** | B, v1 | **Purple `REC`** = household record, **green `PB` / `SB`** = your best ever / today, **yellow** = slower; Drive cells coloured **as set**, tables by **current standing** | Same cells and tags as C. Only the meaning of purple changes (C: your PB). Reason: purple then never changes meaning when D2 lands, and beginners in the household still earn green often (open question Q1 keeps C's meaning one rule away) |
| **Drive lock for beginners** | v1 (answers C's Q3) | On track, leaving Drive › Coach needs a 0.5 s hold for beginner profiles | It protects C's hero from a knee bump; nothing on the screen changes |
| **Condensed timing numerals** | v1 | `DIN Condensed` (shipped with iPadOS and macOS, zero bytes) for numerals | It is what lets the larger delta and three 40 px sector times fit C's columns |

### 0.3 Considered and left out

| Idea | From | Why not |
|---|---|---|
| Delta as the single focal number, corner panel beside it | A, v1 | That is A's hierarchy, not C's. James chose C |
| B's wall beside the driver column on the main Drive screen, and B's Focus toggle | B | Puts dense tiles in the driver's peripheral vision; C's Coach is already the "focus" layout |
| Emptying cue bar in a separate cue panel | A, v1 | C's hero already has one approach bar; two bars for one distance is a duplicate |
| Radio as a pill in the status row instead of a strip | v1 | C's radio strip (message, mic state, a 56 px button) is a core part of "radio inside Drive" |
| "Sentences only when stationary" | v1 (P7) | Conflicts with C's coaching point on track. Replaced by a length rule and D6's `short` text (4.5) |
| Setup › Checklist landing and Drivers under Setup | v1 | C keeps Drivers in Settings; readiness lives on Drive's Ready card and Setup › Connect |
| Caps micro-labels everywhere (Avenir Next Condensed) | v1 | HeroUI's look uses sentence-case labels. Caps stay only for short signal words (`BRAKE`, `AHEAD`, `PB`, flag bands) |
| Pro `AppLayout` + `Sidebar` for the rail | HeroUI Pro | Its collapsed sidebar is a 48 px icon-only strip with labels hidden (`--sidebar-width-collapsed: 48px` in `sidebar.css`) and it turns into a sheet on small screens. C needs a labelled 72 px rail and a phone tab bar (3.2) |

### 0.4 Kept from v1 (framework-independent, compatible with C)

The D6 `coach` block (one message on screen and radio); unknown = `-` and stale rules; the status-row semantics;
the Drive lock; the colour families (one job each: timing, flags/state, orange = you, pink hatch = synthetic); the
corner-ahead rule (apex based); official corner labels from `track_model.corners[].label / display_name`; evidence
chips (`SYNTHETIC`, `REPLAY`); night dim and red-green safe colours; the legibility method (ISO 15008 visual angle at
70 cm); backend additions **D1-D6**; the acceptance tests on the rig.

**Here or cloud?** As in v1: build the Drive screen here on the Mac, because it only counts once tried on the real
iPad at 70 cm with live PS5 telemetry and the radio over Tailscale HTTPS. Pure logic modules, Review pages and the
backend additions can go to cloud sessions once the current uncommitted work is pushed (section 14.4).

---

## 1. Principles

| # | Rule | In practice |
|---|---|---|
| P1 | **Next action first** (C) | The next corner and its cue have the largest, fixed slot. The delta is the strong second element |
| P2 | **Nothing moves while driving** (C, B) | Fixed slots. A state change swaps content inside a slot, never its size or position. No banner pushes anything down |
| P3 | **Each colour family has one job** (v1) | Purple / green / yellow = timing. Red, amber, yellow, blue and cyan **bands** = flags and state. Orange = you (your car, focus, primary action). Pink hatching = synthetic. Red text = behind / brake |
| P4 | **Colour is never the only signal** | Signs (`−` U+2212, `+`), bar direction, the words `AHEAD` / `BEHIND` / `LEVEL`, tags `REC` / `PB` / `SB` / `INV`, band words |
| P5 | **Unknown is `-`** | Never `0.000`, `--:--.---` or `—`. Stale values dim and carry their age. A lost link blanks live values (the live store already clears them) |
| P6 | **The screen looks ahead, the radio does the timing** | No "BRAKE NOW" flash; the cue shows what is coming and how far |
| P7 | **One message, two channels** | The coach card shows the point the radio picked (D6). Before D6 the screen falls back to the top observation and says nothing it cannot back |
| P8 | **Evidence tiers stay visible** | `SYNTHETIC` (hatched) and `REPLAY` chips on every screen that shows such data |
| P9 | **The UI adds no advice** | Coaching text is `analysis/coaching.py`'s or the grounded engineer's, verbatim. The UI may add neutral descriptions ("braked 12 m earlier"), never instructions. It never recommends braking later on its own |
| P10 | **Deterministic on track** | Drive uses `/ws/live` and the radio store only. It works fully with the LLM down |
| P11 | **HeroUI first, custom only for the domain** | HeroUI v3 / Pro components for every container, control, list, chart and overlay. Custom components only where none fits: live numerals, the lap ribbon, the track map, flag bands, the live inputs trace |
| P12 | **Touch on a rig** | Targets ≥ 44 px everywhere, ≥ 56 px for Drive actions and sheet rows, ≥ 64 px for glove actions (Go live, Switch driver, Review this session, Done next). The Drive sub-nav Segment is 44 px: it is used when stopped, and on track it sits behind the Drive lock for beginners |

---

## 2. Information architecture

### 2.1 Four areas (C)

| Area | Question | Sub-pages (route id) | Opens on |
|---|---|---|---|
| **Drive** | What do I do next? | **Coach** `coach` · **Car** `car` · **Track** `track` · **Radio** `radio` | Coach |
| **Review** | How did it go, what do I work on, am I getting better? | **Sessions** `sessions` · **Coaching** `coaching` · **Progress** `progress` · **Ask** `ask`. A session has **Summary · Laps · Compare · Corners · Ask** | The last page used; first time Sessions |
| **Setup** | Are the game, the rig and the car set up right? | **Connect** `connect` · **Rig** `rig` · **Car setup** `car` | Connect until the first real session exists, then the last page used (default Rig) |
| **Settings** | How does Pitwall behave, and for whom? | **Drivers** `drivers` · **Radio & voice** `radio` · **AI engineer** `ai` · **Display** `display` · **System** `system` | Drivers |

### 2.2 Where today's views go

| Svelte view (`web/src/views`) | React page (`web-react/src/pages`) |
|---|---|
| `LiveView` | `drive/CoachPage.tsx` (new screen), `drive/CarPage.tsx` (B's wall), `drive/TrackPage.tsx`. Today's `drive/DrivePage.tsx` becomes `CarPage` material and is then deleted |
| `RadioView` | `drive/RadioPage.tsx` (stage, log, cue mode, intensity); voice settings to `settings/RadioVoicePage.tsx` |
| `SessionsView` | `review/SessionsPage.tsx` |
| `SessionView` | `review/SessionPage.tsx` + `review/session/{SummaryTab,LapsTab,CompareTab,CornersTab,AskTab}.tsx` |
| `EngineerView` | `review/AskPage.tsx` (any session) and `AskTab` (scoped) |
| `SetupView` (rig, **hot file**) | `setup/RigPage.tsx` + `setup/rig/*` (walkthrough, all settings, rig check, upgrades) |
| `CarSetupView` | `setup/CarSetupPage.tsx` + `setup/car/*` |
| `ConnectView` | `setup/ConnectPage.tsx` |
| `ProfilesView` | `settings/DriversPage.tsx` (switching stays in the rail's driver menu) |
| `SettingsView` | `settings/AiEnginePage.tsx` |
| `StatusView` | `settings/SystemPage.tsx` |

### 2.3 Routes

Hash routes in the format `web-react` already parses: `#/<area>/<page>[/<param>][?<query>]`
(`src/lib/route-parse.ts`; `param` is every segment after the page, so `#/review/sessions/<id>/compare` gives
`param = "<id>/compare"`). The query inside the hash is kept as is.

| Route | Page |
|---|---|
| `#/drive/coach` · `#/drive/car` · `#/drive/track` · `#/drive/radio` | Drive |
| `#/review/sessions` | Sessions list (iPad: master-detail) |
| `#/review/sessions/<id>` | Session › Summary |
| `#/review/sessions/<id>/laps` · `/compare?ref=<lap_id>&lap=<lap_id>&at=<metres>` · `/corners` · `/ask?q=<question>` | Session tabs |
| `#/review/coaching?driver=<id>&track=<track_id>&car=<car>` | Coaching plan |
| `#/review/progress?driver=<id>&track=<track_id>&car=<car>` | Progress |
| `#/review/ask?session=<id>&q=<question>` | Engineer (any session) |
| `#/setup/connect` · `#/setup/rig` · `#/setup/rig/walk/<section>/<n>` · `#/setup/rig/settings` · `#/setup/rig/check` · `#/setup/rig/upgrades` | Setup › Connect, Rig (walkthrough is the default view) |
| `#/setup/car?format=&track=&session=&conditions=&style=` · `#/setup/car/session/<id>` | Car setup (recommendation; one session's setup vs recommended) |
| `#/settings/drivers` · `/radio` · `/ai` · `/display` · `/system` | Settings |

### 2.4 Redirects (keep the `?query`)

Rewritten with `history.replaceState` (no history entry), keeping the query inside the hash: the radio reads
`#/radio?token=…` and must not lose the token.

| Old | New | Note |
|---|---|---|
| `''`, `#/`, `#/live`, `#/drive`, `#/drive/live` | `#/drive/coach` | `#/drive/live` is the interim `web-react` id (served at `/next/`) |
| `#/radio` | `#/drive/radio` | Permanent: `docs/radio-setup.md` and Home Screen icons use it |
| `#/sessions` · `#/sessions/<id>` | `#/review/sessions` · `#/review/sessions/<id>` | |
| `#/engineer` · `#/review/compare` | `#/review/ask` · `#/review/sessions` | `review/compare` is the interim id; Compare needs a session |
| `#/setup` (bare) · `#/connect` · `#/carsetup` | `#/setup/rig` · `#/setup/connect` · `#/setup/car` | Bare `#/setup` was the Svelte rig page |
| `#/profiles` | `#/settings/drivers` | |
| `#/settings` (bare) · `#/settings/engine` | `#/settings/ai` | Bare `#/settings` was the Svelte AI page |
| `#/status` · `#/settings/status` | `#/settings/system` | |
| `#/review` (bare) | the remembered sub-page | In-app links always name the sub-page |

### 2.5 Landing rules

- Every area remembers its last sub-page per device (`localStorage` key `pitwall-area-pages`, read and written in
  `try/catch`; when storage is unavailable the area's first page is used).
- Setup lands on Connect while `GET /api/sessions` has no non-synthetic session, so a first-time user starts at the
  game's telemetry settings.
- After a session ends, the Drive "Session complete" card links to the session's Summary. Review never opens by itself.

### 2.6 Global chrome (every page)

| Element | Where | Spec |
|---|---|---|
| **Connection** | Rail foot (dot) and Drive's status slot (pill); phone app bar (pill) | `Live` / `Stale 6 s` / `No data` / `Offline` (the dashboard's own socket is down). Existing `badgeFor()` |
| **Evidence chips** | Drive's status slot; Review headers and rows | Hatched pink `SYNTHETIC` when `connection.synthetic`; `REPLAY` when `connection.source` starts with `replay:` |
| **Driver** | Rail foot (avatar); phone app bar | Tap opens the existing "Who's in the seat?" menu (`DriverSwitcher`) |
| **Night dim** | Rail foot (moon button, 56 px) | Toggles `prefs.night` |
| **Mini radio bar** | Floating, bottom centre of the content area, outside Drive, while the radio is live | 3.5 |
| **Toasts** | Top right, only when not on track | "Lap 7 analysed · 2 coaching points" with an Open action. Drive never shows toasts on track |

---

## 3. Navigation and shell

### 3.1 Layout by width

| Width | Primary nav | Sub-nav | Drive |
|---|---|---|---|
| ≥ 1024 px (iPad landscape, Mac) | **Rail**, 72 px | Pro `Segment` in the area header (Drive: inside the status slot) | Full grid (4.2) |
| 768-1023 px (iPad portrait, split view) | Rail, 72 px | Segment | Landscape: the grid with compact rows (4.2). Portrait: the portrait stack at iPad scale (5.4) |
| < 768 px (phone) | **Bottom tab bar**, 64 px + `env(safe-area-inset-bottom)` | Horizontally scrolling Segment under a 52 px app bar | Portrait stack (5.4) |

Content max width 1680 px (Mac), centred.

### 3.2 Rail, tab bar, area header

- **Rail (72 px, full height).** Background = page background with a 1 px `--border` hairline on its right edge
  (HeroUI taste: the nav matches the page, not a contrasting panel). Top: the Pitwall mark (the existing zig-zag
  glyph, 28 px, links to Drive). Four items, each 72 × 64: a 24 px icon above an 11 px / 600 label, always visible.
  **Active item:** a 56 × 56 tile in `--surface-secondary` with the icon in `--accent` and the label in
  `--foreground`; inactive items `--muted`. Foot (spacing, no divider): night dim (moon, 56 px), the seated driver's
  avatar (40 px in a 56 px target, opens the driver menu) and the connection dot (10 px).
- **Tab bar (phone).** The same four items, 64 px tall plus the safe area, labels always shown, active item in
  `--accent`. The Drive item carries a small live dot while telemetry is live, so the way back to the timing screen
  is obvious.
- **Area header (Review, Setup, Settings).** 64 px: page title (24 px / 600, sentence case), the sub-nav Segment,
  then the area's actions on the right (for example **Session report**). Content starts 24 px below it.
- **Drive has no area header.** Its sub-nav Segment sits at the right end of the status slot, saving a row.
- **Icons:** `@gravity-ui/icons` (already a dependency, MIT): `Speedometer` (Drive), `ChartLine` (Review), `Wrench`
  (Setup), `Gear` (Settings), `Moon`, `Microphone`. No icon font, no external request.

### 3.3 Drive while on track

"On track" means the state is `on_track` (4.7): telemetry live and `pit_status == 0`.

- **The rail dims** to 55 % opacity (setting *Dim navigation on track*, default on). Any touch restores it for 5 s.
  Hit targets keep their size. Bands never dim.
- **Drive lock** (setting: Off / **Beginner profiles** (default) / Everyone). When it applies, leaving Drive › Coach
  (to Car, Track, Radio or another area) needs a **0.5 s hold** on the rail item, tab or Segment item: Pro
  `PressableFeedback.HoldConfirm` (`duration={500}`, `sweep="up"`) fills the item in orange under the finger. A short
  tap shows the 2 s hint "Hold to leave Drive while driving" inside the status slot (no toast). Off in the pit, before
  and after the session, and while stale. **[critic]** Wiring (checked against `hold-confirm.d.ts` of
  1.0.0-beta.10): only `HoldConfirm`'s `onComplete` navigates; while the lock applies the item's own `onPress` shows
  the hint and never navigates; `resetOnComplete` stays `true`; the lock is a prop of the shared nav-item component,
  so the rail, the tab bar and the Drive Segment cannot disagree.
- **Screen wake lock** while telemetry is live on any Drive page (`src/lib/wake.ts`, alongside the radio's own
  wake lock). When the browser refuses it, the status slot shows a `Screen may sleep` chip.
- **Home Screen web app:** `index.html` gets `apple-mobile-web-app-capable`,
  `apple-mobile-web-app-status-bar-style=black-translucent` and `viewport-fit=cover`, plus
  `public/manifest.webmanifest` (`display: standalone`, `orientation: landscape`, `background_color` = the dark
  background). Drive then gets the full height with no Safari bars.

### 3.4 Other patterns

- **Pickers** (driver, lap A/B, track and car, cue mode) are Pro `Sheet`s on phone (bottom, snap points) and HeroUI
  `Popover` / `Select` on iPad. Rows ≥ 56 px. Escape or a tap outside closes them.
- **Provenance and "Why?"** open a Pro `Sheet` (right side on iPad, bottom on phone). No hover-only content anywhere
  (no `HoverCard` on touch pages).
- **Confirmations** are inline (HeroUI `AlertDialog` only for destructive actions: delete a driver, reassign a
  session). Never browser dialogs.
- **Keyboard (Mac):** `1`-`4` switch area, `[` / `]` switch sub-page, Space is push-to-talk on Drive pages while the
  radio is live (as today), `⌘K` opens a Pro `Command` palette (jump to session, page or setting).

### 3.5 Mini radio bar

Outside Drive, while `radio.phase == "live"`: a Pro `ActionBar` floating pill, bottom centre of the content area
(above the tab bar on phone). Prefix: live dot + `Radio`. Content: the latest message (one line, ellipsis, 8 s).
Suffix: a 48 px **Hold to talk** button (same `PushToTalkButton` as Drive) and an icon button that opens
Drive › Radio. The radio store is module level, so the radio keeps running on every page. While the bar is
visible, every page pads its bottom by 96 px so the bar never covers a primary action (for example the rig
walkthrough's **Done, next**).

---

## 4. Drive › Coach (iPad landscape)

### 4.1 Viewport and legibility

Baseline: **1180 × 820 CSS px** (11" iPad / iPad Air landscape) as a Home Screen web app. The iPadOS status bar
overlaps the top 24 px (`black-translucent`), so the app area is **1180 × 796**; minus the 72 px rail the Drive
content is **1108 × 796**. One CSS px is 0.192 mm (0.156 mm on the iPad mini, 1133 × 744).

Visual angle = cap height (0.70 × font size for both SF Pro and DIN Condensed) at 700 mm. ISO 15008 asks about
20′ for in-vehicle glance text (16′ minimum). 20′ at 700 mm is a 4.1 mm cap height, a **30 px font**. Pitwall's floor
for anything read while moving is **32 px**; coach text is read on straights only.

| Token | Size at baseline | Cap height | At 70 cm (11") | iPad mini (compact rows) | Used for |
|---|---|---|---|---|---|
| `--pw-d-delta` | 144 px | 19.4 mm | **95′** | 124 px, 67′ | Delta, pit speed |
| `--pw-d-corner` | 112 px | 15.1 mm | 74′ | 96 px, 52′ | Corner label `T15`; **[critic]** labels over 4 characters (`T10-13`) at 88 px, 58′ (4.5 long corner rule); `PIT` at 96 px |
| `--pw-d-xl` | 44 px | 5.9 mm | 29′ | 38 px, 20′ | Corner name, distance to the corner; **[critic]** a name over 14 characters at 32 px on its own line |
| `--pw-d-l` | 40 px | 5.4 mm | 27′ | 34 px, 18′ → **Large 21′** | Cue text and distance, sector times |
| `--pw-d-m` | 32 px | 4.3 mm | 21′ | 28 px, 15′ → Large 18′ | Lap times, projected lap |
| `--pw-d-s` | 26 px | 3.5 mm | 17′ | 24 px | Coach text (straights only; **[critic]** never smaller while moving), **[critic]** flag-band words (800, caps) |
| `--pw-d-xs` | 22 px | 3.0 mm | 15′ | 20 px | Status slot values, radio message (not glance critical); coach text only when stationary. **[critic]** 15′ is under ISO 15008's 16′ minimum, so nothing glance-critical uses this size |
| `--pw-d-label` | 15 px | | | 14 px | Panel labels, learned by position |

Sizes are `clamp()`s on `dvh` (section 11). On the iPad mini Drive suggests the **Large** text size (× 1.12) once.

### 4.2 Grid

```
 x=0  72 84                                         712 722                           1168 1180
 ┌────┬──────────────────────────────────────────────────────────────────────────────────┐ y=24 (under iPadOS bar)
 │ ⌁  │ ● Live  Silverstone · Practice · Lap 7 / -   SYNTHETIC?   [Coach|Car|Track|Radio] │ 52  STATUS SLOT
 │    ├──────────────────────────────────────────────┬───────────────────────────────────┤
 │Drv │ Next corner · right                  FOCUS ◣ │ Delta to reference · Lap 4 today  │
 │Rev │ T15   Stowe                          320 m   │                                   │
 │Set │ ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░ (approach, last 400 m)  │             −0.21                 │ 290 HERO
 │Set │ ┌[BRAKE]  T15 brake              in 250 m┐   │             AHEAD                 │
 │    │ └────────────────────────────────────────┘   │  ◀ ahead ━━━━━┃          behind ▶ │
 │    ├──────────────────────────────────────────────┤                                   │
 │    │ [Work on · L6] Stowe: you braked about 12 m  │  Projected 1:30.77                │ 120 COACH
 │    │ earlier than on your reference lap and lost… │                                   │
 │    ├───────────────┬──────────────┬───────────────┼───────────────────────────────────┤
 │    │ S1   SB       │ S2   REC     │ S3  running   │ Lap   1:09.5                      │ 132 SECTORS / LAPS
 │    │ 29.318        │ 36.904       │ ▓▓▓▓░░░░      │ Last  1:31.512  +0.53             │
 │ ☾  │ −0.023 best   │ family record│               │ Best  1:30.986  SB                │
 │(JR)├───────────────┴──────────────┴───────────────┴───────────────────────────────────┤
 │ ●  │ S1 ┊ T1 T2 T3 T4 T5 ┊S2 T6 T7 T8 T9 T10-13 T14 ┊S3 ▲ T15 T16 T17-18              │ 56 RIBBON
 │    ├──────────────────────────────────────────────────────────────────────────────────┤
 │    │ [LAP] Lap 6: 1:31.512, plus 0.5 on your best.  8 s   ● Mic live  [ Hold to talk ]│ 72 RADIO STRIP
 └────┴──────────────────────────────────────────────────────────────────────────────────┘ y=820
```

```css
/* src/pages/drive/coach/CoachPage.module.css (or Tailwind arbitrary values on the root). Baseline 1108 × 796. */
.coach {
  display: grid;
  height: 100dvh;                         /* minus the safe-area top inset, applied by the shell */
  padding: 12px;
  gap: 10px;
  grid-template-columns: repeat(12, minmax(0, 1fr));                 /* 81.2 px columns */
  grid-template-rows: 52px minmax(0, 1fr) 120px 132px 56px 72px;     /* hero row = 290 px */
  grid-template-areas:
    "status status status status status status status status status status status status"
    "hero   hero   hero   hero   hero   hero   hero   delta  delta  delta  delta  delta"
    "coach  coach  coach  coach  coach  coach  coach  delta  delta  delta  delta  delta"
    "sect   sect   sect   sect   sect   sect   sect   laps   laps   laps   laps   laps"
    "ribbon ribbon ribbon ribbon ribbon ribbon ribbon ribbon ribbon ribbon ribbon ribbon"
    "radio  radio  radio  radio  radio  radio  radio  radio  radio  radio  radio  radio";
}
/* Boxes at baseline: status 1084×52 · hero 628×290 · coach 628×120 · delta 446×420 · sectors 3×203×132 ·
   laps 446×132 · ribbon 1084×56 · radio 1084×72. */
@media (max-height: 760px) {   /* iPad mini, Safari with toolbars */
  .coach { padding: 8px; gap: 8px; grid-template-rows: 44px minmax(0, 1fr) 104px 112px 44px 64px; }
}
@media (max-width: 767px) { /* phone: portrait stack, 5.4 */ }
```

### 4.3 Panels

All numbers use the condensed numeral face with tabular figures. Sizes at the baseline.

| # | Panel | Shows | Source | Type | Unknown / edge |
|---|---|---|---|---|---|
| 1 | **Status slot** 1084 × 52 | Connection pill; track; session type; `Lap 7 / 25` (total only when known); `P4` (races only); evidence chips; transient chip (6 s); `Screen may sleep` chip; the **Segment** (Coach · Car · Track · Radio) at the right end | `connection.*`, `session.{track_name, session_type, total_laps}`, `frame.{lap_number, race_position}`, `events[]` | 22 px / 600 values, 15 px muted labels; **[critic]** band words 26 px / 800 caps, band detail 20 px | `-` per value. Bands replace the left part (4.8); the Segment stays |
| 2 | **Next corner** (hero) 628 × 290 | `Next corner` + direction (`right`, with an arrow icon) or `In corner`; **label** `T15` (112 px / 800 sans); **official name** `Stowe` (44 px / 700); **distance** `320 m` to `entry_m` (44 px numerals, rounded to 10 m), hidden while in the corner; **approach bar** (fills over the last 400 m before `entry_m`); `FOCUS` chip when the corner is a cue focus corner | `track_model.corners[].{name, label, display_name, entry_m, apex_m, direction}`, `frame.lap_distance_m`, `skeleton.track_length_m`, `cues.focus` | | No model: "Corners appear after your first clean lap" (26 px, muted). No official name: label only (the learned name when there is no label). **[critic]** Long corner rule (4.5) instead of wrapping: v2's "may wrap to two lines" overflowed the 290 px hero for Silverstone's `T10-13` Maggotts and Becketts (rendered). `direction == null` (complexes) shows no arrow and no word |
| 3 | **Cue band** (inside the hero) 80 px | Kind chip `BRAKE` (solid `--pw-behind`, dark ink) or `MARKER` (neutral); the cue text verbatim (`T15 brake`, 40 px / 700); `in 250 m` (40 px numerals) | `cues.next.{kind, text, in_m, corner}`, `cues.{mode, muted, reason}` | | Cue for another corner: "Next call: T3 brake · 1.4 km" (26 px). Mode off: "Calls off" (muted). Muted: "Calls paused: safety car". No plan: the server's `reason` ("no reference lap yet"). **[critic]** `muted == "radio off"` is not a pause of the screen: `CueEngine.snapshot()` reports it whenever no radio is connected (`coach/cues.py`, `self._sink is None`), which is the normal case for a driver without an earpiece, and `next` is still computed. The band keeps the cue and adds a small `Radio off` chip |
| 4 | **Coach card** 628 × 120 | Chip `Work on · L6` (warning soft) or `Good · L6` (success soft), then the coaching point (4.5) | D6 `coach.by_corner[next]` (`short`, else `text_simple` for simple-wording profiles, else `text`); before D6 the top `observations[]` entry for that corner by `priority` | 26 px / 500, up to 3 lines (4.5); **[critic]** never below 26 px while moving | "No note for T15 on lap 6" (muted). No reference: "Coaching starts after your first clean lap" |
| 5 | **Delta** 446 × 420 | Label `Delta to reference` and the reference chip (`Lap 4 · 1:30.986 · today`, or `3 Oct` when from another session); beginners read `vs your target lap`. **Number** (144 px); word `AHEAD` / `BEHIND` / `LEVEL` (22 px caps); **bar** (28 px, ±1.0 s, ticks at ±0.25 / ±0.5, chevron when clamped, end labels `◀ ahead` and `behind ▶`); **Projected** `1:30.77` (32 px), hidden for beginners | `delta_s`, `reference.{lap_number, lap_time_ms, session_id}` | | `-` (muted) with one reason line (22 px): "No reference yet: your first clean lap becomes the reference" / "Out lap" / "No signal". Projected `-` on an invalid lap |
| 6 | **Sector cells** 3 × 203 × 132 | `S1` `S2` `S3`; time (40 px); timing tag and tint (4.6); a small line under it (`−0.023 vs your best`, 15 px). The **running** sector shows a progress bar and its elapsed time in `--muted`; later sectors show `-` | **D1** `frame.current_lap_sector_ms`; bests **D2** (session best from `laps[]` before D2); `frame.sector`, `skeleton.sectors` | | Before D1: each cell's label reads `S1 · last lap L6` and the cells show `laps[0].sector_times_ms`, dimmed, coloured as set, with no running outline (last-lap values must never look current) |
| 7 | **Lap times** 446 × 132 | `Lap` running clock (tenths) + `INVALID` chip; `Last` + delta to reference; `Best` (session best clean) + tag | `frame.{current_lap_time_ms, lap_invalid, last_lap_time_ms}`, `laps[]`, D2 | 32 px numerals, 15 px labels | `-` |
| 8 | **Lap ribbon** 1084 × 56 | The lap as a straight strip: neutral grey sector bands labelled S1 S2 S3; a tick per corner with labels for the next corner and focus corners; brake notches at `cues.cues[].target_m`; DRS zones dashed; yellow marshal zones hatched in `--pw-flag-yellow`; the car (orange triangle) | `skeleton.{track_length_m, sectors, drs_zones, marshal_zones}` + `marshal_flags`, `track_model.corners`, `cues.cues[]`, `frame.lap_distance_m` | 13 px / 700 labels | No skeleton: one neutral band. No model: no ticks. Static SVG; only the car moves (`transform`) |
| 9 | **Radio strip** 1084 × 72 | Kind chip (`ENGINEER`, `LAP`, `CUE`, `ALERT`) + current message (22 px, one line, ellipsis) + age; for a cue, its outcome (`on time −3 m`, `late +6 m`, `dropped`); mic state chip; **Hold to talk** (220 × 56); **Go live** instead while the radio is not live (the user gesture iOS needs for audio and the mic); **Listen only** on plain HTTP (tap explains HTTPS) | radio store `current`, `phase`, `mic`, `conn`, `server.ptt`; `cues.last.{status, error_m, reason}`, `cues.timing.margin_m` | | "Radio quiet" (muted) |

**Signature:** the hero card's **top-right corner is chamfered** (a 22 px 45° cut, `clip-path`) and carries a 3 px
`--accent` edge along its top, from the rounded top-left corner to the cut. No other panel has either. It reads as a
pit board and is the one place orange appears on the Coach screen apart from your car on the ribbon and the focus tag.

### 4.4 Graft check (what the eye sees, in order)

1. **Hero** (top left, the largest area, the accent edge, the red cue band): `T15 Stowe 320 m`, `BRAKE in 250 m`.
2. **Delta** (top right, the largest numeral, no accent): `−0.21 AHEAD` and the bar direction, usually read
   peripherally.
3. **Coach card** (under the hero): the sentence, on the next straight.
4. Sectors and lap times, ribbon, radio strip: learned by position, read when wanted.

This is C's order. A's graft only made item 2 easier to read; it did not move it ahead of item 1.

### 4.5 Rules (pure functions, unit-tested)

All in `web-react/src/lib/drive/*.ts` (4.10). They import types only and are tested with vitest in plain node.

- **Corner ahead (v1 rule).** Map game metres to model metres by lap fraction (`skeleton.track_length_m` →
  `track_model.length_m`), as the Svelte `TrackMap.toModel` does. The shown corner is the first corner whose
  `apex_m` lies ahead of the car, wrapping at the line; it stays until the car passes its apex. Before `entry_m` the
  head reads `Next corner` with the distance to `entry_m`; after it, `In corner` and no distance.
- **Corner text.** Label = `corners[].label` (official, e.g. `T15`, `T10-13`) → else `corner_text[name].short` →
  else the learned `name`. Official name = `corners[].display_name`, shown only when set (the server sets it only from
  a verified or seeded track sheet). Never parsed from `corner_text.long`.
- **[critic] Long corner rule.** When the label is longer than 4 characters (`T10-13`, `T17-18`) or the name longer
  than 14 (`Maggotts and Becketts`), the corner row becomes two lines: the label at 88 px (`line-height .85`) with
  the distance at the right, then the name at 32 px on one full-width line (ellipsis only past about 34 characters).
  The row is 114 px and the hero's gaps drop from 10 to 8 px: 16 + 26 + 8 + 114 + 8 + 10 + 8 + 80 + 16 = 286 ≤ 290.
  Labels never wrap (`white-space: nowrap`). `cornerAhead()` returns `layout: "one" | "two"` so the rule is tested,
  with fixtures for Silverstone (`T10-13`, `T17-18`) and Austria's longest names.
- **Cue matching.** `cues.next.corner` is the learned corner name, the same key as `track_model.corners[].name`.
  If it is not the shown corner, the band shows the next call as a secondary line.
- **[critic] Cue muting.** `cues.muted` replaces the band with "Calls paused: <reason>" except when it is
  `"radio off"` (no radio connected): then the band keeps `cues.next` and shows a `Radio off` chip, because the
  screen looks ahead whether or not anyone is listening (P6). `cues.mode == "off"` still reads "Calls off".
- **Coaching point.** D6 `coach.by_corner[shown corner]`; text = `short` when present, else `text_simple` for
  profiles with `coaching.simple_wording`, else `text`. Fallback before D6: `observations` with `corner == shown`,
  highest `priority` first. The UI never filters by its own thresholds and never composes advice.
  **Length rule** (replaces v1's "sentences only when stationary"): up to 60 characters at 30 px; up to 130 at 26 px
  (3 lines). **[critic]** Longer texts stay at 26 px and are clamped to 3 lines (the verbatim prefix and an
  ellipsis); v2 dropped them to 22 px, which is 14.5′ at 70 cm, under ISO 15008's 16′ minimum. D6's `short`
  (≤ 48 characters) removes the clamp in practice. The fixture test asserts every `short` fits 2 lines at 26 px in
  588 px and reports (not fails) texts that need the clamp. In pit, garage and after the session the card shows the
  full `text` at 22 px (stationary).
- **Delta.** Tone `ahead` when `delta_s < −0.02`, `behind` when `> +0.02`, `level` in between (word `LEVEL`,
  `--foreground`). Two decimals; one decimal at 10 s or more (`+12.4`). The string is recomputed at most every
  100 ms (`useThrottledValue`). Invalid lap or safety car: tone `muted` (`--muted`, no green/red, an `SC` / `INV`
  chip). Stale or offline: `-`. The minus sign is U+2212 drawn at `scaleX(.62)` so it does not push the digits.
- **Projected lap** = `reference.lap_time_ms + delta_s × 1000`, `-` when either is unknown or the lap is invalid.
- **Lap clock.** Running: `m:ss.t` (tenths). Completed: `m:ss.SSS` in its timing colour for 6 s, then the clock
  resumes.
- **Approach bar.** `fill = clamp(1 − toEntryM / 400, 0, 1)`; hidden in the corner and when the distance is unknown.

### 4.6 Timing colours

One rule set on Drive, Car, Review and Progress. Scope: same **game + track + car**, **clean laps only**, **never
synthetic or replay sessions** (the storage rules for references and PBs).

| Colour | Tag | Meaning | Before D2 | With D2 |
|---|---|---|---|---|
| **Purple** | `REC` | Household record: faster than every earlier time by **any** profile | **Never shown** | Shown |
| **Green** | `PB` | Your all-time best here, not a record | Not shown | Shown |
| **Green** | `SB` | Your best **this session** | From `laps[]` | From `bests.session` |
| **Yellow** | none | Completed, slower than your session best | Shown | Shown |
| Neutral | none | Nothing to compare yet, or unknown | Shown | Shown |
| Grey | `INV` | Invalid, or not clean (`flashback`, `pit_in`, `pit_out`, `paused`, `stale_data`, `distance_jump`); the reason in words | Shown | Shown |

- **As set** on Drive: a sector or lap keeps the colour it had when completed.
- **Current standing** in tables (Car wall laps, Review laps, Progress): only times that are still the best are
  green or purple; every other completed time is yellow.
- D2 only **adds** purple and `PB`. Nothing changes meaning when it lands.
- Legend on every timing surface: `REC family record · PB your best ever · SB your best today` (before D2:
  `SB your best today`).
- Dark theme: coloured numerals on a 10 % tint of the same colour. Light theme: solid fills with ink (purple and
  green with white ink, yellow with dark ink), because coloured text on white is too weak. **Exception, light tables
  and lists:** slower times are plain `--foreground` text (a column of yellow chips is noise and yellow text fails on
  white); only `REC` / `PB` / `SB` times are filled, and they keep their tags.

### 4.7 States

`driveState(snapshot, wsConnected, nowS)` returns one state plus overlays; the first match wins. The same function
drives iPad, phone and Mac.

| # | State | Trigger | Status slot | Hero + coach | Delta | Sectors / laps | Ribbon | Radio strip |
|---|---|---|---|---|---|---|---|---|
| 1 | **Offline** | `!live.connected` | **Outline** `--pw-bad`: `Offline · reconnecting…` | Last content dimmed, live values `-` | `-` | `-` | No car | Unchanged (the radio has its own socket) |
| 2 | **No telemetry** | `connection.status == "no_data"` | Neutral: `Waiting for telemetry` | **No-telemetry card** spans hero, coach and delta (4.9) | (in card) | `-` | Empty band | Go live offered |
| 3 | **Stale** | `connection.status == "stale"` | **Outline** amber: `No signal · 6 s · game paused or in a menu?` | Dimmed to 45 %; **[critic]** the corner distance and the cue's `in … m` show `-` and the approach bar hides (by the delta's own rule: a frozen "in 250 m" must never look current). Label, name and cue text stay (facts) | **`-`** (a frozen delta must never look current) | Lap and the running sector `-`; completed sectors, Last, Best stay (facts) | Dimmed, no car | Unchanged |
| 4 | **Session complete** | D4 `session_state == "ended"`; before D4 the newest event is `session_ended` or `chequered_flag` | Neutral **fill**: `Session complete` / `Chequered flag` | **Session complete card** spans hero, coach and delta (4.9) | (in card) | Kept | Kept, no car | Lap summary |
| 5 | **Red flag** | D4 `red_flag`; before D4 the newest event is `red_flag`, < 120 s old, nothing newer | **Red fill**, white ink: `RED FLAG` (`role="alert"`) | Hero kept; cue band `Calls paused` | `-` | Kept | Kept | Unchanged |
| 6 | **Pit lane** | `frame.pit_status == 1` | **Cyan fill**: `PIT LANE · limit 80 km/h` | Hero: `PIT` (96 px; **[critic]** `PIT LANE` at 112 px plus a 144 px speed cannot share the 596 px row, and the band already says "pit lane") and **speed / limit** `78` (144 px) `/ 80` (56 px) `km/h`; over the limit `--pw-bad` + `OVER`. Coach card: the last lap's top point, full text, with its evidence line | `-` + "No delta in the pit lane" | Kept | Car at the pit | Unchanged |
| 7 | **In the garage** | `frame.pit_status == 2` (D3: `driver_status == "in_garage"`), or session known and no lap started | Neutral: `Ready · Practice` | **Ready card** spans hero, coach and delta (4.9): pre-session or between runs | (in card) | `-` before the first lap, else kept | Corners and sectors, no car | Go live / live |
| 8 | **On track** | Otherwise | Normal line | 4.3 | 4.3 | 4.3 | 4.3 | 4.3 |

**Overlays** (combine with states 5 to 8):

| Overlay | Trigger | Treatment |
|---|---|---|
| Safety car | `session.safety_car_status` is `full`, `virtual` or `formation_lap` | **Amber fill**: `SAFETY CAR · calls paused` / `VIRTUAL SAFETY CAR` / `FORMATION LAP`. Delta in `--muted` with an `SC` chip (real but not meaningful). The cue band shows the server's muted reason |
| Yellow flag | any `marshal_flags[].flag == "yellow"` | **Yellow fill**, dark ink: `YELLOW · Sector 3 · zone 16 · 380 m ahead` (distance when the zone starts within 1000 m). The zone is hatched on the ribbon. No blinking |
| Blue flag | `flag == "blue"` | **Blue fill**, white ink: `BLUE FLAG · let the car behind through` |
| Invalid lap | `frame.lap_invalid` | No band. `INVALID` chip next to Lap, colouring stops, delta muted, projected `-` |
| Incident | new `penalty`, `collision`, `flashback`, `fastest_lap`, `pit_entry`, `pit_exit` event | A 6 s chip at the right of the status line, left of the Segment: `PENALTY`, `CONTACT`, `FLASHBACK · lap won't count`, `FASTEST LAP` |

### 4.8 Status slot semantics (B)

- **One slot, content swapped, never stacked.** Its height never changes.
- **Outline = the data is in doubt** (offline, stale): a 2 px coloured outline, the slot's own background, coloured
  text. **Fill = the track says** (red, safety car, yellow, blue, pit, session complete): a solid band with ink chosen
  for contrast (9.2). **[critic]** Band words are 26 px / 800 caps (17′ at 70 cm; v2's mockup used 20 px, 14′),
  the detail after them 20 px.
- **Priority:** offline > stale > red > safety car > yellow > blue > pit > session complete > ready > normal. When the
  data is in doubt, no flag is shown as current.
- The Segment stays at the right end in every state (dark ink variant on light bands), so the driver can always
  leave.
- Bands appear without animation. Red flag uses `role="alert"`; every other band `role="status"`.

### 4.9 State cards

**Ready card** (state 7). C's card, three columns and a footer, spanning hero, coach and delta (1084 × 420):

1. **Seat:** 72 px avatar; "**James** is in the seat" (32 px); skill chip; **Not you? Switch driver** (64 px,
   secondary). The best protection against laps landing in the wrong profile on a three-driver rig.
2. **Before the first lap: Target.** "Your best here 1:30.986 · 3 Oct" (from `drivers.active.stats.best_laps` for
   this game and track; per car with D2); "Family record 1:30.412 · Jo" (D2, purple, with the holder's avatar);
   "Delta reference: Lap 4 · today", or "none yet: your first clean lap becomes the reference".
   **Between runs** (laps > 0): **Last run**: best lap coloured as set, laps clean / total, gained since the first
   clean lap.
3. **Today:** focus corners (`cues.focus`, by official label and name, each with `cues.cues[].reason`, e.g.
   "braking early · 3 of last 5 laps"); braking calls mode; radio state (`Radio off` or `Radio live · mic OK`).
   **Go live** itself stays in the radio strip below (220 × 56), the one place it appears on Drive, so there is never
   a second copy. Between runs this column leads with **One thing for the next run** (D6 pick, full text, evidence
   line).

Footer (15 px, muted): `5 890 m · S2 1 813 m · S3 4 294 m · 14 corners learned · names: verified track sheet`.

**Session complete card** (state 4): Pro `KPIGroup` of four tiles (best lap coloured with tag and lap number; clean
laps / laps; gained today; gap to your best and to the family record with D2), one **Work on** and one **Went well**
(D6 `coach.picked`, else top observations by priority), and **Review this session** (64 px, primary) →
`#/review/sessions/<id>`. **[critic]** `SessionCompleteCard` is a `React.lazy` chunk: Pro `KPI`
(`dist/components/kpi/kpi.js`) imports `AreaChart` and therefore Recharts at module level, which would otherwise land
in the eager Drive bundle (4.11). Its Suspense fallback is a same-size `Skeleton`, so nothing moves.

**No-telemetry card** (state 2): a Pro `Stepper` (vertical) with three steps whose values come from
`GET /api/connect`: "Turn on UDP telemetry in the game", "IP `192.0.2.20` · port `20777`", "Drive out of the
garage" (with the last sender seen, if any). Buttons: **Open Setup › Connect** (64 px, primary) and **Try a demo
replay** (secondary; starts the synthetic demo from Settings › System and says so).

### 4.10 Logic modules (`web-react/src/lib/drive/`)

```ts
// types.ts - fields the backend adds (all optional; absent = unknown, never guessed)
export interface Bests { lap_ms: number | null; sectors_ms: [number | null, number | null, number | null] }
export interface CueSnapshot {                      // coach/cues.py CueEngine.snapshot() - exists today
  mode: "off" | "focus" | "markers" | "all"; armed: boolean; muted: string | null; reason: string | null;
  ref_lap_number: number | null; focus: string[];
  cues: { corner: string; kind: "brake" | "marker"; target_m: number; text: string; focus: boolean; reason: string }[];
  next: { corner: string; text: string; kind: "brake" | "marker"; in_m: number } | null;
  last: { corner: string; text: string; status?: "pending" | "sent" | "dropped"; reason?: string | null;
          error_m?: number | null; age_s?: number | null } | null;
  timing: { latency_ms: number; path: string; margin_m: number };
}
export interface CornerIdentity { label?: string | null; display_name?: string | null; identity_tier?: string | null }
export type ObservationNext = Observation & { short?: string | null; text_simple?: string | null };        // D6
export interface SnapshotNext extends Snapshot {
  cues?: CueSnapshot;
  frame: (Frame & { current_lap_sector_ms?: [number | null, number | null] | null;                         // D1
                    driver_status?: "in_garage" | "out_lap" | "in_lap" | "flying_lap" | "on_track" | null }) | null; // D3
  bests?: { session: Bests; driver: (Bests & { set_unix: number | null }) | null;
            household: (Bests & { driver_id: number | null }) | null } | null;                               // D2
  session_state?: "running" | "ended" | "red_flag" | null;                                                   // D4
  coach?: { lap_number: number; picked: ObservationNext[]; by_corner: Record<string, ObservationNext> } | null; // D6
}

// state.ts
export type DriveState = "offline" | "no_data" | "stale" | "ended" | "red_flag" | "pit_lane" | "garage" | "on_track";
export interface DriveOverlays {
  safetyCar: "full" | "virtual" | "formation_lap" | null;
  yellow: { zone: number; sector: number | null; aheadM: number | null } | null;
  blue: boolean; invalid: boolean;
  chip: { kind: "penalty" | "collision" | "flashback" | "fastest_lap" | "pit_entry" | "pit_exit"; ageS: number } | null;
}
export function driveState(s: SnapshotNext | null, wsConnected: boolean, nowS: number): { state: DriveState; overlays: DriveOverlays };
export function statusSlot(state: DriveState, o: DriveOverlays, s: SnapshotNext | null):
  { kind: "normal" | "outline" | "fill"; tone: "bad" | "warn" | "red" | "sc" | "yellow" | "blue" | "pit" | "neutral" | null; text: string; role: "status" | "alert" };

// corner.ts
export interface CornerView { name: string; label: string; officialName: string | null; direction: "left" | "right" | null;
  phase: "next" | "in"; toEntryM: number | null; approach: number | null; focus: boolean; focusReason: string | null;
  layout: "one" | "two" }                                        // [critic] long corner rule (4.5)
export function cornerAhead(model: TrackModel | null | undefined, lapDistanceM: number | null, gameLengthM: number | null,
  cues: CueSnapshot | undefined): CornerView | null;

// delta.ts
export const DELTA_NEUTRAL_S = 0.02, DELTA_SCALE_S = 1.0;
export interface DeltaView { text: string; tone: "ahead" | "behind" | "level" | "muted" | "unknown";
  word: "AHEAD" | "BEHIND" | "LEVEL" | null; bar: number /* −1..1 */; clamped: boolean; projectedMs: number | null;
  refLabel: string | null; reason: string | null; aria: string }
export function deltaView(s: SnapshotNext | null, state: DriveState, o: DriveOverlays, beginner: boolean): DeltaView;

// timing.ts
export type TimingStatus = "rec" | "pb" | "sb" | "slower" | "neutral" | "invalid";
export function bestsOf(s: SnapshotNext): { tier: 1 | 2; session: Bests; driver: Bests | null; household: Bests | null };
export function statusAsSet(t: number | null, before: { session: number | null; driver: number | null; household: number | null },
  clean: boolean, tier: 1 | 2): TimingStatus;
export function standing(times: (number | null)[], clean: boolean[], best: { driver: number | null; household: number | null },
  tier: 1 | 2): TimingStatus[];
export function lapClock(ms: number | null, running: boolean): string;            // "1:09.5" | "1:31.512" | "-"
export function sectorCells(s: SnapshotNext): { caption: string | null; cells: { label: string; text: string;
  status: TimingStatus | "running" | "future"; sub: string | null; progress: number | null }[] };

// cues.ts, coach.ts, ribbon.ts
export function cueView(c: CueSnapshot | undefined, shownCorner: string | null):
  { next: CueLine | null; note: string | null; radioOff: boolean };   // [critic] muted "radio off" keeps `next`
export function lastCueOutcome(c: CueSnapshot | undefined): { corner: string; words: string; tone: "ok" | "late" | "dropped" } | null;
export function coachPoint(s: SnapshotNext, corner: string | null, simple: boolean, moving: boolean):
  { tag: "work_on" | "good" | null; lap: number | null; text: string | null;
    size: 30 | 26 | 22 /* [critic] 22 only when !moving */; clamp: boolean; empty: string | null };
export function ribbon(s: SnapshotNext): { lengthM: number | null; sectors: { a: number; b: number; label: string }[];
  corners: { at: number; label: string; next: boolean; focus: boolean }[]; cueNotches: number[];
  drs: [number, number][]; yellow: [number, number][]; car: number | null };   // fractions 0..1

// model.ts - everything Coach renders, computed once per snapshot
export function driveModel(input: { snap: SnapshotNext | null; connected: boolean; nowS: number;
  driver: Driver | null; prefs: Prefs }): DriveModel;
```

**Fixtures:** JSON snapshots captured from `pitwall replay` of the recorded Austria fixture
(`tests/fixtures/recorded`) and from `pitwall simulate` (synthetic, named as such), saved in
`web-react/src/test/fixtures/`. Together they reach every state and overlay above.

### 4.11 Performance on iPad Safari (React)

- **One subscription, one model.** `useDriveModel()` reads the live store once per snapshot and memoises
  `driveModel()` on the snapshot's identity; panels receive plain view models and are `memo`ised, so a panel
  re-renders only when its own strings change.
- **Live numerals are plain text.** No `NumberValue`, NumberFlow or `motion` on Drive (they animate). The delta
  string changes at most at 10 Hz.
- **HeroUI on Drive:** containers and press targets only (`Card`, `Chip`, `Button`, `Segment`, `ProgressBar` with
  `transition-none`). No `Tooltip`, `Popover` or other portal opens on Drive while on track; the driver menu and the
  Drive lock hint are the only overlays and neither updates per snapshot.
- **No shadows and no `backdrop-filter`** inside `.pw-drive` (`--surface-shadow: none`).
- **Ribbon and map are static SVG**, memoised on the skeleton and model; only the car marker moves, by `transform`.
- **Bars** use `transform: scaleX()` with an 80 ms linear transition (0 under `prefers-reduced-motion`).
- **Code splitting:** Review, Setup and Settings pages and every Pro chart / Markdown import are
  `React.lazy`, so the Drive bundle stays small on the iPad. **[critic]** That includes Pro `KPI` (it imports
  `AreaChart`), so Drive's Session complete card is lazy too. Root imports from `@heroui-pro/react` are safe on Drive
  (`sideEffects: ["*.css"]`, and the root index does not re-export charts, `kpi`, `markdown` or `code-block`); a
  build check greps the Drive chunk for `recharts` and fails if it is there.
- **Budget:** no long task over 50 ms in 10 minutes of iPad Safari profiling; memory flat over one hour.

---

## 5. Drive › Car, Track, Radio; phones and other sizes

Every Drive sub-page keeps the **status slot** at the top (same component, same states and bands), so the session's
state speaks in the same place whichever page is open.

### 5.1 Drive › Car: the pit wall (graft from B)

For a stationary reader: a parent on the phone, or a Mac screen next to the rig. Never the default page.

```
┌ status slot (same as Coach) ──────────────────────────────────────────────────────────────┐
├ Car (4 col) ───────────┬ Track map (5 col) ─────────────────────┬ Tyres & energy (3 col) ──┤
│ 212 km/h   6           │ circuit, sectors by timing status,     │ FL 92° FR 95°            │
│ rpm ▓▓▓▓▓▓▓▓░          │ car, next corner, focus rings,         │ RL 98° RR 101°           │
│ throttle ▓▓▓▓▓▓▓       │ brake zones, live yellow zones         │ wear · pressure          │
│ brake ░                │ RC · Lap 7 · Pit exit · 2 min ago      │ fuel 18.4 kg · ERS 2.8 MJ│
├ Inputs, last 12 s ─────┼ Laps (current standing) ──────────────┼ Coaching · last lap ─────┤
│ speed / throttle / brk │ L  time      S1     S2     S3    Δref  │ [T15] text … +0.11 s     │
│ trace                  │ 7  1:31.512  29.3   36.9   25.3  +0.53 │ [T9 good] text … −0.04 s │
└────────────────────────┴────────────────────────────────────────┴──────────────────────────┘
```

| Tile | Content | Component |
|---|---|---|
| Car | Speed, gear, RPM (bar turns `--pw-bad` above 94 % of max), throttle, brake, steering, brake bias, DRS, ERS | HeroUI `Card` + `Meter` (`transition-none`, as today's `DrivePage`) + custom numerals |
| Track map | `TrackMap` (custom SVG port of `TrackMap.svelte`): sectors coloured by this lap's timing status as set, car dot, next corner label, focus rings, brake zones, live yellow zones; footer = newest race-control event | Custom `TrackMap` in a `Card` |
| Tyres & energy | 2 × 2 in FL FR / RL RR order: surface temperature (in-window values in plain `--foreground`, cold blue, hot amber, over red: `tyreTempColor` bands), wear, pressure; fuel kg + game's laps estimate; ERS store | `Card` + custom `TyreGrid` |
| Inputs | Speed, throttle and brake over the last 12 s (`live.history`), redrawn at 10 Hz | Custom `LiveTrace` (canvas). Not a Pro chart: Recharts re-rendering at 20 Hz is too heavy on the iPad |
| Laps | 8 newest, current standing colours, `INV` and `PIT` tags, `R` on the reference | Pro `DataGrid` (`variant="secondary"`, no selection, `rowHeight={44}`) with `TimingValue` cells |
| Coaching · last lap | Up to 3 observations (D6 `picked`, else top by priority): corner chip, text (15 px, 2-line clamp), impact | Pro `ListView` (read only, no hover) |
| Telemetry health | Packets/s, rejected, unrecognised, source (moved from today's Live strip) | Footer line of the Car tile |

### 5.2 Drive › Track (C)

For learning a new track in practice. Left (7 columns): the large `TrackMap` with the live car, the current corner
highlighted, sector labels, yellow zones and brake notches. Right (5 columns): the corner list (Pro `ListView`),
each row with the official label and long name, direction, `FOCUS` chip, and what the coach said about it on the
last lap (verbatim). Tapping a row selects it on the map; its **See it on the lap** button opens Review › Compare at
that corner.

### 5.3 Drive › Radio (C)

The stage from today's `RadioView`: the current message (28 px), a **160 px round Hold to talk** button (HeroUI
`Button`, `onPressStart` / `onPressEnd`, also Space on a Mac), **Go live**, **Radio check**, **Stop talking**, and a
mic level `Meter`. A compact row of two Pro `Segment`s that change between runs: **Braking calls** (Off · Focus ·
Markers · All) and **Coaching** (Quiet · Normal · Detailed). The log below as a Pro `ListView` (kind chip, text,
time). Voice choice, speed, the Mac voice and diagnostics move to Settings › Radio & voice.

### 5.4 Phones and other sizes

| Device | Drive › Coach | Other areas |
|---|---|---|
| **Phone portrait** (390 × 844) | One column: app bar 52 (area title, connection pill, avatar) · status/flag band 44 · **delta** (`clamp(88px, 26vw, 120px)` + bar) · **next corner** (label 64, name 28, distance 32) · cue band (28 px) · coach text (18 px, 3 lines) · three sector cells (28 px) · Lap / Last / Best row (24 px) · radio mini strip 56 · tab bar 64. The ribbon is hidden. Mostly for a parent watching; the delta goes first because a spectator reads it, not the next action | Single column. Tables become two-line rows (`DataGrid` → `ListView` below 600 px). Session tabs scroll horizontally |
| **Phone landscape** (844 × 390) | The landscape grid with compact rows, rail hidden, the tab bar as a 56 px side strip | Single column |
| **iPad portrait** (820 × 1180) | The phone order at iPad scale, rail kept | Two columns where useful |
| **iPad mini** (1133 × 744) | The landscape grid, compact rows; suggests **Large** once | |
| **iPad 13"** (1376 × 1032) | The same grid; type grows through `clamp()` to its caps | |
| **Mac** | The same grid, centred, max width 1680. Drive › Car is the natural Mac page | Rail + content, max width 1680 |

---

## 6. Review

Review pages are read up close (sofa, desk, between runs). HeroUI's normal app density applies: body 16 px, labels
14 px, page titles 24 px, cards with 24 px radius and 16-24 px padding. Every page states which driver it is about
(avatar + name in the header) and shows evidence chips on synthetic and replay data.

### 6.1 Sessions (`#/review/sessions`)

- **Filter row:** a Pro `Segment` of drivers (Everyone, then each driver with their avatar; the existing
  server-side filter) and a track `Select`. **[critic]** It starts on the **seated driver** (from `drivers.active`),
  not Everyone, so another driver who just drove lands on their own last session in one tap (acceptance 6);
  Everyone is one tap away and the choice is remembered per device.
- **"Last session" card** at the top: track · type · when · driver avatar; best lap (`TimingValue`); clean / total
  laps; coaching points count; **Open** (56 px).
- **List grouped by day** (Today, Yesterday, then dates; short sentence-case group titles). Rows (64 px; two lines on
  phone): driver avatar, track (17 px / 600), session type, car, laps clean / total (**[critic]** `repo.list_sessions`
  returns `lap_count` and `best_clean_ms` but no clean count; before D5 the row reads `12 laps`, D5 adds
  `clean_lap_count`), **best clean lap** as a
  `TimingValue` (`PB set` chip when the driver's `stats.best_laps` points at this session), evidence chips. A row
  action menu (`Dropdown` in a ghost `Button`) holds **Reassign to…**, which opens a `Modal` with the existing
  confirmation copy.
- **iPad:** master-detail. List 360 px on the left; the right side previews the selected session (header, the four
  KPI tiles, the first Work on card, **Open session**). **Phone:** list, then push to the session.
- **Empty state** (Pro `EmptyState`): "No sessions yet. Put a driver in the seat and drive a lap" with **Open Drive**.

### 6.2 Session page (`#/review/sessions/<id>`)

Header: HeroUI `Breadcrumbs` (Sessions › Silverstone · Practice), title, chips (driver avatar + name, car, weather,
date, `SYNTHETIC` / `REPLAY`), actions: **Ask the engineer** (secondary) and **Session report** (opens the existing
markdown report in a Pro `Sheet` rendered by Pro `Markdown`). Tabs: HeroUI `Tabs` (secondary variant):
**Summary · Laps · Compare · Corners · Ask**.

### 6.3 Summary: "how did it go, and what next?"

The beginner's page. Top to bottom (general to specific):

1. **KPI tiles** (Pro `KPIGroup` of `KPI`s; 4 across on iPad, 2 × 2 on phone): **Best lap** (timing colour + tag,
   "lap 9"); **Clean laps** ("9 of 12", with a glossary `?` that explains what makes a lap not clean); **Gained
   today** (first clean lap → best clean lap, **[critic]** written `1.20 s` with a `TrendChip` "faster", never a bare
   `−1.20`: to a beginner a minus reads as a loss); **Steadiness** ("your clean laps
   were within 1.4 s of each other", max − min of clean laps). Advanced profiles add **Best sectors combined** and
   **Gap to your best ever / family record** (D2).
2. **Work on** (1 / 3 / 5 cards for beginner / intermediate / advanced, "Show more" for the rest). Source:
   `analysis.observations`, non-positive, ranked by `priority` then `impact_s`, preferring a repeated `consistency`.
   Each card (HeroUI `Card`): corner chip (official label and name), a 120 px mini map with the corner highlighted, the
   coach's text verbatim (`text_simple` for simple-wording profiles), an evidence line ("Seen on 3 of your last 5
   laps · about 0.11 s a lap · confidence high"), and three buttons: **See it on the lap** (→ Compare `?at=<apex>`),
   **Why?** (HeroUI `Disclosure` with the comparison numbers in plain words) and **Ask the engineer** (pre-filled
   "Why am I losing time at Stowe?"). **[critic]** For beginners the heading reads **One thing to work on**, the
   text is 18 px, and the card has no signed `+0.11 s` badge (the evidence line says "about 0.11 s a lap" in words).
3. **Went well:** positive observations (up to 3) as a Pro `ItemCardGroup` of `ItemCard`s with a success icon.
4. **Lap times:** Pro `LineChart` with a dot per lap, the **y axis reversed and labelled "faster ↑"**, filled dots
   for clean laps, hollow for not clean (reason on tap), a reference line, the best lap tagged. Tap a dot → Compare
   that lap.
5. **Where the time is:** Pro `BarChart` (horizontal) of `corner_summary[].mean_time_delta_s`, sorted, with plain
   words from the signs of `mean_brake_point_delta_m` and `mean_min_speed_delta_kph` ("braked about 12 m earlier",
   "4 km/h slower at the slowest point"). Descriptions, not advice.
6. **Track map coloured by corner** (custom `TrackMap`, green gained, red lost, neutral within ±0.01 s).
7. **Your best here:** a small Pro `LineChart` of this driver's best clean lap per session at this track (reversed
   y, "faster ↑"); links to Progress.
8. **Engineer summary (optional):** "Ask the engineer for a summary" calls `/api/engineer/ask`. The answer is
   rendered with Pro `Markdown`, with a `Chip` `LLM · grounded` or `Deterministic`. Nothing else depends on it.

**[critic] Beginner density.** Eight blocks is a lot for a first-time driver. For a beginner's session the page
shows 1-4 (tiles, one Work on, Went well, lap times, which carries the "higher = faster" sentence), then one
**More detail** button (HeroUI `Disclosure`) that opens 5-8. Intermediate and advanced see everything. This keeps
C's "Summary is the beginner's page" true without hiding anything.

### 6.4 Laps

Pro `DataGrid` (sortable): Lap · Time · S1 · S2 · S3 · Δ ref · Status (flags in words: "pit out", "invalid",
"flashback"). Times are `TimingValue` cells coloured by **current standing**. Each row has two 44 px buttons,
**Set as reference** and **Compare**, replacing today's 16 px radio buttons; **Pin as reference** keeps its server
call behind an inline confirmation.

### 6.5 Compare (`/compare?ref=&lap=&at=`)

- **Pickers:** two 56 px HeroUI `Select`s: **A · Reference** (cyan `--pw-ref` dot) and **B · Your lap**. Options
  list lap time, sectors (standing colours) and status words. Only clean laps can be A, as today. A can also be
  **another driver's best lap** here (family compare: their `stats.best_laps`; `/api/compare` accepts any two lap ids
  and keeps its compatibility checks).
- **Compatibility** (`comparison.compatibility`): warnings as a HeroUI `Alert` (warning) above the charts; a block
  shows its reason instead of the charts.
- **Charts** (Pro charts, Recharts `syncId` so one cursor drives all; data from `/api/laps/{id}/trace?step=5`):
  1. the **lap ribbon** as the distance header (sectors, corners with official labels; **[critic]** a label closer
     than 34 px to the previous drawn one is skipped, the cursor, next and focus corners always draw: with every
     label on, Silverstone printed "T3T4" and "T10-1314");
  2. **delta by distance** (`LineChart`, zero line, neutral sector bands);
  3. **speed** (`LineChart`, A in `--pw-ref`, B in `--pw-cmp`);
  4. **throttle and brake** (`AreaChart`), collapsed for beginners behind **Show pedals**;
  5. **steering** (`LineChart`), advanced only.
  **[critic]** Chart titles are words, not letters ("Time gained or lost: your lap against the reference", not
  "B vs A"), and for beginner and intermediate drivers each chart has one fixed plain sentence under its title
  ("The line goes up where your lap lost time and down where it gained time"; "Blue is the reference lap, white is
  your lap. Each dip is a corner"). They explain the chart, never what to do.
- **Right column (iPad):** the map following the cursor and the **corner explainer** card, which turns
  `comparison.corners` numbers into neutral words ("At Stowe you braked 12 m earlier, slowest speed 4 km/h lower,
  0.11 s slower") with the coach's observation for that corner under it.
- **Corner table** in plain words (Pro `DataGrid`): Corner · Time lost here · Braked · Slowest speed · Exit speed ·
  Full throttle.
- Phone: pickers, corner list as cards, then the delta chart; other charts behind **Show telemetry**.

### 6.6 Corners: "what keeps happening at Stowe?"

Coaching grouped **by corner**, sorted by average time lost: one HeroUI `Card` per corner with the official label
and name, the session averages from `corner_summary` (time, brake point mean and spread, slowest speed), a `FOCUS`
chip when the corner is in the live cue focus, and the laps where an observation fired (text + evidence). Filter: a
Pro `Segment` **Work on · Went well · All**. Incident observations are greyed with "not used for technique advice".
Tap a card → Compare at that corner.

### 6.7 Ask (session tab and `#/review/ask`)

Today's `EngineerView` on Pro chat components: `ChatConversation` with `ChatMessage` (user / assistant), a
`PromptInput` with `PromptSuggestion` chips ("Where did I lose the most time?", "What went well?"), and the facts each
answer was grounded on as `ChatSources` / `ChatSource`. Each answer carries a `Chip`: `LLM · grounded`,
`Deterministic` (fallback) or `LLM down · deterministic`. The line "answers are grounded, or replaced by a
deterministic answer" stays visible. The session is preselected from the route; `?q=` pre-fills the question.

### 6.8 Coaching plan (`#/review/coaching`)

Per driver (Pro `Segment` with avatars) and per track + car (`Select`s):

| Block | Content | Data |
|---|---|---|
| **Working on now** | Up to 3 corners, each with a Pro `TrendChip` (better / same / worse), the latest observation verbatim and **See it** | Before D5: the latest session's `corner_summary` (no trend). D5: the last 3-5 sessions with trends |
| **Habits** | Observations that carry a `consistency` string ("4 of the last 5 laps"), verbatim | `analysis.observations` |
| **Recently fixed** | Corners whose average loss fell below the coaching threshold | D5 |
| **The radio will focus on** | `cues.focus` with `cues.cues[].reason` | Live snapshot when this driver is in the seat and a plan exists; else `-` with the reason |

### 6.9 Progress (`#/review/progress`)

Driver `Segment`, track + car `Select`. Framed as three questions; each chart carries **one computed sentence**
(never an LLM): "Your best here dropped 1.3 s over 4 sessions".

| Block | Before D5 | With D5 | Component |
|---|---|---|---|
| Headline tiles: best here, sessions, clean laps, PBs this month | `/api/drivers/{id}/sessions`, `stats` (**[critic]** clean laps per track need D5's `clean_lap_count`; before it the tile shows laps) | Same | Pro `KPIGroup` + `KPI` with `KPI.Trend` and a `KPI.Chart` sparkline |
| **Getting faster?** Best clean lap per session, **y reversed "faster ↑"**, PB points green, record purple (D2) | Synthetic and replay excluded (toggle to show) | Adds the median clean lap | Pro `LineChart` |
| **Getting steadier?** Spread of clean laps per session | - | Shown | Pro `BarChart` |
| **What changed?** Corner trends (small multiples), habit counts | - | Shown | Pro `LineChart` grid |
| **Milestones** (first clean lap at a track, each new PB with its gain, first 10-clean-lap session) | Derived | PB history | Pro `Timeline` |
| **Family board** per track + car | Every driver's `stats.best_laps`, gap to the leader. **[critic]** No purple before D2: `best_laps` is per game + track (any car), so it is not the timing scope (game + track + car) and v2's "record in purple" broke 4.6 and acceptance 5. Times neutral, the leader marked with the word `Fastest`, and a "car may differ" note when the cars differ | Car scope exact; the record in purple with `REC` (D2) | Pro `DataGrid` with avatars and `TimingValue` |
| Totals | `stats.{sessions, laps, clean_laps, tracks}` | | Footer line |

### 6.10 Density by skill level

Read from the **viewed** driver's `preferences.skill_level`, not a global switch: a beginner's sessions open
simplified and an advanced driver's in full. Anyone can expand.

| Page | Beginner | Intermediate | Advanced |
|---|---|---|---|
| Drive › Coach | Delta label "vs your target lap"; projected hidden; Drive lock on; coaching text `text_simple` | Projected shown | Projected shown |
| Summary KPI tiles | 4 | 4 | 6 |
| Work on cards | 1 (+ Show more) | 3 | 5 |
| Compare charts | Delta + speed | + pedals | + pedals + steering |
| Corner table | Time + plain sentence | + braked, slowest speed | All columns, technical labels allowed |
| Glossary `?` buttons | Shown | Shown | Hidden |
| Progress | Getting faster?, milestones, family board first | Same | Corner trends first |
| **[critic]** Summary blocks | 1-4, then **More detail** | All | All |
| **[critic]** Compare chart captions | Shown | Shown | Hidden |
| **[critic]** Work on badge | Words only ("about 0.11 s a lap") | `+0.11 s` | `+0.11 s` |

**[critic]** In the mockup v2 took the density from the *seated* driver (Alex in the seat made James's session look
like a beginner's). The rule is the **viewed** session's driver; `lib/review/density.ts` takes the session's
`driver_id`, never `drivers.active`, and has a test for exactly that case.

### 6.11 Goals, badges and the weekly digest (lane motivation)

Data: M1-M5 (section 13). Every number comes from the viewed driver's own real driving (never replays; synthetic
only behind the development switch, and then flagged). Nothing here is written by a language model.

- **Summary (6.3): Today's 3 things.** Right after the KPI tiles, three item cards: Went well, One to work on,
  Progress (shown as **Goal reached** when its `source` is `goal_reached`). Wording follows the viewed driver's
  density (6.10: `text_simple` when `simple`), with the evidence line under the text. Work on with a `lap_id` links
  to Compare; a progress item with a `goal_id` links to the goals card. An empty item shows `-` and its `why_empty`.
  Beginners get the existing Work on / Went well blocks under **More detail**; for others the Work on list leaves
  out the item whose `corner:kind` is `things.work_on.observation_key` and is headed "More to work on".
- **Progress (6.9): goals, week, badges.** Under the scope bar: the goals card (active goals with a progress bar and
  text, "Why this target?" for suggested goals, archive / delete / reopen; goals reached in the last 30 days; an
  empty state with the top two suggestions) and the week card (‹ › week navigation, headline, totals, sessions,
  improvements, goals moved, badges; **Printable page** opens `/api/drivers/{id}/digest.html`, **Copy as text**
  copies `markdown`). Then the badges card: streak tiles (weeks in a row, sessions this week, best clean run, PB
  streak) and the badge grid, newest first. Adding a goal: Suggested (each card sets its `create` body as is) or
  Make your own (lap time with "this car" / "any {class} car" when the scope has a `car_class`, clean laps 2-50,
  steady laps 3/5/10 + seconds, clean race with the note "Pitwall can only check this in F1 races"). 409 and 422
  show the server's `detail` inline. Non-F1 scopes add: "This game does not report track limits, so 'clean' means
  no pit lap, reset or flashback."
- **Drive (P1, P2, P10).** On track only the status chip `GOAL REACHED` for 6 s after a `motivation` note of the
  live session (an incident chip wins). The Ready card's goal row and the Session complete card's three things
  and badges are fetched only when the car is stopped (`garage` / `ended`). No animation, no sound.

---

## 7. Setup

### 7.1 Connect (`#/setup/connect`)

Today's `ConnectView` content on HeroUI: a Pro `Stepper` (vertical) per game: turn on UDP telemetry, IP and port
(values from `/api/connect`, each with a copy `Button`), format and rate, drive out. **Live senders** as a Pro
`ListView` (source, game, packets/s, last seen; a `Chip` `Live` / `Stale`). **Open Pitwall on another device:** the
Tailscale HTTPS URL and the LAN token URL in **[critic]** `CopyField`s (monospace value + copy `Button`; v2 named Pro
`CodeBlock`, which needs `shiki`), plus a note on why the radio needs HTTPS.

### 7.2 Rig (`#/setup/rig`): walkthrough first

The page has a Pro `Segment`: **Walkthrough · All settings · Rig check · Upgrades**. Data:
`GET /api/rig/recommendations?game=&platform=&driver_id=` (sections `base`, `wheel`, `ingame`, `pedals`, each with
`steps` and `rows` in menu order; every row has `value`, `range`, `factory_default`, `changed_from_default`,
`needs_advanced`, `locked`, `instruction` and `provenance`), `GET /api/rig/check`, `GET/PUT /api/rig/profile`,
`POST /api/rig/upgrades`.

**Walkthrough (default view).** The user sits in the rig and changes settings on the wheel's tuning menu or in the
game, with the iPad at about 70 cm. So the step view is a **glance screen**, like Drive:

```
┌ Rig setup for James · F1 25 · PS5 · GT DD Pro 5 Nm · CSL pedals            [Change rig] ┐
│  ① Base mode ─── ② Wheel menu ─── ③ In game ─── ④ Pedals ─── ⑤ Check on track            │  Pro Stepper (horizontal)
├──────────────────────────────────────────────────────────┬───────────────────────────────┤
│ Wheel menu · 3 of 13                                     │ SEN  1080         done        │
│                                                          │ FF   78        ◀ now          │
│  [FF]  Force feedback strength                           │ FFS  check on your base       │
│                                                          │ NDP  OFF                      │
│                 78                       (96 px)         │ NFR  0                        │
│                                                          │ NIN  OFF                      │
│  Range 70-85 · factory 100 · changed   [Sourced · 3]     │ INT  OFF                      │
│  Your strength scale (beginner) lowers it from 85.        │ FEI  100                      │
│                                                          │ FOR  100                      │
│  [Why this value?]                                       │ SPR  OFF                      │
│                                                          │ DPR  OFF                      │
│  [ ‹ Previous ]                        [ Done, next › ]  │ FUL  -                        │
└──────────────────────────────────────────────────────────┴───────────────────────────────┘
```

- **Stepper** across the top: Pro `Stepper` (horizontal, `size="lg"`) over the five sections (base mode, wheel
  tuning menu in the wheel's own order, in-game settings, pedals, check on track). Completed sections show a check.
- **Step card** (HeroUI `Card`, the hero chamfer reused so it reads as "the thing to do now"): the **menu code** as
  it appears on the wheel's display (`FF`, monospace in a `Kbd`), the plain label, the **value at 96 px** (condensed
  numerals; the user reads it from the seat while pressing wheel buttons), then chips: range, factory default,
  `Changed` when `changed_from_default`, `Advanced menu` when `needs_advanced`, `Set by the game` when `locked`,
  evidence (`Verified`, `Unverified`, `Derived by Pitwall`; never presented as more certain than `provenance.evidence`).
  Row notes verbatim (15 px). **Why this value?** opens a Pro `Sheet` with the provenance: basis presets with code
  and date, other presets' values, consensus, derivation, stale warnings and citations (links).
- **Instruction rows** (`instruction: true`, e.g. FFS after the Boost Kit) show the instruction text at 26 px
  instead of a number. Section `steps` (e.g. "press the throttle and brake fully once after every power-on") appear
  as their own step cards before the rows they belong to.
- **Navigation:** **‹ Previous** (secondary) and **Done, next ›** (primary), both 64 px and at the bottom where a
  thumb reaches them from the seat. The right column is a Pro `ListView` of every row in the section with its value
  and a done tick; tapping a row jumps to it.
- **Progress** is remembered per device and per recommendation (`localStorage`, `try/catch`): ticks are a
  convenience, never data. When the recommendation changes (another style, a firmware note), ticks for changed rows
  are cleared and the row shows `Updated`.
- **Done:** the last step (**Check on track**) explains the rig check ("drive 3 clean laps, then open Rig check") and
  links to it.

**All settings.** The same rows as an editable reference, one HeroUI `Card` per section with Pro `CellSelect` rows
for the hardware profile (platform, wheel base, torque, pedals, rim), a Pro `RadioButtonGroup` for the driver's style
(Official, Balanced, Competitive, Realism, Comfort, each with its description; `Comfort` says "mostly derived"), and a
Pro `CellSlider` for the strength scale. Each section has **Copy section** (plain text in menu order).

**Rig check.** Results of `/api/rig/check` as a Pro `ListView`: label, measured value, target, status `Chip` (pass
green, warn amber, fail red, unknown `-`; status colours, never timing colours), and a `Disclosure` with the
threshold note. "Compare with before the upgrade" when an upgrade baseline exists.

**Upgrades.** Pro `Timeline` of the rig's upgrade history, then **What changes with the Boost Kit 180** (the
`UpgradePreview`: row diffs as a Pro `DataGrid`, steps, peak torque before / after), and **Record an upgrade**
(`Modal` with a date field).

The rig page files are **hot** today (`SetupView.svelte`, `rig.ts`, `routes_rig.py`, `rig/*` are uncommitted):
port it only after that work lands (14.3).

### 7.3 Car setup (`#/setup/car`)

Data: `GET /api/carsetup/catalog`, `/recommendation`, `/sessions/{sid}`, `/experiments`.

- **The request as a sentence** (Pro `InlineSelect`s inside a 24 px line): "Setup for the **2025 car** at
  **Silverstone**, **Race**, **Dry**, **Stable**". Without a chosen style the driver's skill picks it (beginner →
  stable) and the line says so ("chosen for a beginner").
- **Summary card:** the style reason (`style_reason`), selection note, number of sources, the catalogue caveat, and
  `disagreements` as a HeroUI `Alert` (warning) when sources disagree.
- **Groups in menu order** (Aerodynamics, Transmission, Suspension Geometry, Suspension, Brakes, Tyres), each a
  `Card` with **Copy section**. Each row: label, **value** (24 px numerals, menu-formatted `display` + unit), a range
  track showing min-max with the recommended value and the sources' spread (custom `RangeMarker`, read only), and a
  chip for confidence / `Derived` / number of sources. Tapping a row opens a Pro `Sheet` with its sources (author,
  date, patch, verified) and rule.
- **Your setup vs recommended** (from a session's stored setup: `#/setup/car/session/<id>`, or "Use my latest
  session"): Pro `DataGrid` Parameter · Yours · Recommended · Difference, changed rows first; `needs` (a field Pitwall
  cannot tell, such as the car format) asked with a `Select`.
- **Experiments** (one parameter at a time, before / after sessions): Pro `ItemCard`s with a Pro `Stepper`
  (Proposed → Running → Concluded); **Start an experiment** (`Modal`: parameter, new value, hypothesis); the
  concluded result shows the lap-time and corner deltas with their caveats verbatim.
- **Sources:** Pro `ListView` of the setups behind the recommendation, with links.

---

## 8. Settings

| Page | Content | Components |
|---|---|---|
| **Drivers** (default) | One card per driver: avatar, name, skill, coaching intensity, stats (sessions, laps, clean laps, tracks), `In the seat` chip, **Put in the seat**, **Edit**. Edit opens a Pro `Sheet`: name, initials, colour, skill level (with what it changes), coaching intensity, voice on/off. Delete through an `AlertDialog` | Pro `ItemCardGroup` / `ItemCard`; HeroUI `TextField`, `ColorSwatchPicker`; Pro `RadioButtonGroup` (skill), `Segment` (intensity), `CellSwitch` (voice) |
| **Radio & voice** | Moved from `RadioView`'s settings block: voice on/off, engineer voice (device / Mac), device voice, speaking speed, Mac voice, TTS status and diagnostics. Braking calls mode and coaching intensity are also on Drive › Radio | Pro `CellSwitch`, `CellSelect`, `CellSlider`; HeroUI `Disclosure` (diagnostics) |
| **AI engineer** | Off / local / cloud, model, keys, privacy note ("what gets sent"), **Test**, usage today, the last request | Pro `Segment`, `CellSelect`; HeroUI `TextField` (`type="password"`), `Button`; Pro `KPI` (usage), **[critic]** a `<pre>` in a HeroUI `Card` (last request; not Pro `CodeBlock`) |
| **Display** | Theme (Dark / Light / Match device), **Drive always dark** (on), Drive text size (Standard / Large), Night dim, Colour vision (Standard / Red-green safe), Dim navigation on track (on), Drive lock (Off / **Beginner profiles** / Everyone), each with a live preview (a timing cell and the delta) | Pro `Segment`, `CellSwitch`; HeroUI `Card` (preview). Stored per device |
| **System** | Health, worker errors, local LLM health, captures with **Replay**, the **synthetic demo** (labelled SYNTHETIC), the capability matrix with evidence tiers, build version, licences | Pro `KPIGroup`, `ListView`, `DataGrid`; HeroUI `Chip` (tiers) |

---

## 9. Visual system: HeroUI v3 with a pit-wall identity

### 9.1 What comes from HeroUI, what is ours

| From HeroUI v3 (default look) | Ours (pit-wall identity, original) |
|---|---|
| Rounded cards (`min(32px, radius-3xl)` = 24 px at `--radius: 0.5rem`), surface steps for depth, no shadow in dark | The **chamfered hero card** with the accent edge (Drive › Coach, and the rig walkthrough's step card) |
| Pill buttons (`rounded-3xl`), soft chips, segmented controls with a sliding indicator, `Tabs` secondary variant | **Timing cells**: tinted fills + `REC` / `PB` / `SB` / `INV` tags in the three timing colours |
| System sans, `text-sm` controls, sentence-case titles, muted descriptions, generous spacing (4 px grid) | **Condensed tabular numerals** (`DIN Condensed`) for every time, distance and delta |
| Semantic tokens (`--accent`, `--surface`, `--muted`, `--success`, `--warning`, `--danger`) | **Flag bands** (filled for track facts, outlined for doubt) and the **hatched SYNTHETIC** chip |
| Focus rings, React Aria press and keyboard behaviour | Pitwall orange as the only brand colour; the zig-zag mark; the lap ribbon |

### 9.2 Colour

Dark is the default. Contrast is WCAG 2.x, computed for this spec (`scripts/contrast.mjs`, 14.2, recomputes it from
`tokens.css` and fails the build below target). Targets: 4.5:1 for text, 3:1 for control boundaries and bands' large
words; **Drive glance values aim at 7:1** and are never below 4.5:1 (all of them are ≥ 32 px, WCAG "large text").

| Role | Dark | Light | Night (dark only) | Contrast (dark on surface · light on white) |
|---|---|---|---|---|
| `--background` | `#06080b` | `#f3f5f8` | `#000000` | |
| `--surface` (cards) | `#0f1318` | `#ffffff` | `#0a0c10` | |
| `--surface-secondary` | `#161b22` | `#eef1f5` | `#101319` | |
| `--surface-tertiary` / `--default` | `#1e252e` | `#e3e8ef` | `#181d25` | |
| `--border` / `--separator` | `#2a323d` / `#1e252e` | `#d9dee6` / `#e3e8ef` | `#1a1f27` | decorative |
| `--pw-line-strong` (control boundary) | `#5d6878` | `#848e9d` | `#444d5a` | 3.3 · 3.3 |
| `--foreground` | `#eef1f5` | `#0c1016` | `#c9ced6` | 16.5 · 19.1 (night 12.4) |
| `--muted` | `#a3adbb` | `#4d5766` | `#8b94a1` | 8.2 · 7.3 (night 6.4) |
| `--pw-faint` (labels, `-`) | `#808b9b` | `#5f6977` | `#78828f` | 5.4 · 5.6 (night 5.0) |
| `--accent` (fill) / `--accent-foreground` | `#ff6a2b` / ink `#0c1016` | `#c2410c` / white | `#e0602a` | ink on accent 6.7 · white on accent 5.2; accent text 6.5 · 5.2 |
| `--pw-rec` (purple) | `#c58cff` | fill `#6d28d9`, white ink | `#b07ae6` | 7.6 (6.6 on its tint) · 7.1 |
| `--pw-pb` (green, also `--success`, `--pw-ahead`) | `#2fe37f` | fill/text `#047857`, white ink | `#28c46e` | 11.0 (9.2 on tint) · 5.5 |
| `--pw-slower` (yellow) | `#ffd23f` | fill `#ffd23f`, dark ink | `#e0b836` | 12.9 (10.5 on tint) · ink 13.2 |
| `--pw-behind` (also `--danger`, `--pw-brake`) | `#ff5466` | `#c81e3a` | `#e04a5a` | 6.0 · 5.7 (night 4.9, ≥ 32 px only) |
| `--warning` / `--pw-stale` | `#ffb020` | `#9a5b00` | `#e09a1c` | 10.2 · 5.4 |
| `--pw-ref` (reference trace, info) | `#4cc3ff` | `#0369a1` | | 9.4 · 5.9 |
| `--pw-synthetic` (+ 45° hatch) | `#ff7ac0` | `#be185d` | | 7.8 · 6.0 |
| Flag bands (fill / ink) | yellow `#ffd23f` / `#0c1016` · safety car `#ffb020` / `#0c1016` · red `#d7263d` / white · blue `#2563eb` / white · pit `#4cc3ff` / `#0c1016` | same | same | 13.2 · 10.4 · 5.0 · 5.2 · 9.6 |
| Red-green safe (`data-cvd="rg"`) | green → `#4cc3ff`, red → `#ff9f1c` | green → `#0369a1`, red → `#9f4706` | | 9.4 / 9.1 · 5.9 / 6.2 |

Rules:

- **Purple means timing only.** The synthetic chip moves to pink with a hatch (today `--pw-synthetic` is purple).
- **Sector identity is neutral.** Today's broadcast S1 red / S2 blue / S3 yellow (`--pw-sector-1..3`) clash with red =
  behind and yellow = slower / yellow flag; they become three grey steps and sectors are told apart by their labels.
- **Slower is yellow, behind is red.** Today's `--pw-loss` (amber for a slower delta) goes; amber now means "stale or
  warning" only.
- **Orange = you:** your car, the focus tag, the primary action, the hero's edge. Nothing else is orange.

### 9.3 Typography

| Role | Stack | Use |
|---|---|---|
| **Numerals** `--pw-font-num` | `"DIN Condensed", "DIN Alternate", "Avenir Next Condensed", "Barlow Semi Condensed", "Roboto Condensed", "Arial Narrow", sans-serif`, weight 700, `font-variant-numeric: tabular-nums` | Every time, delta, distance, sector and setting value. Ships with iPadOS and macOS (zero bytes); v1 measured its digits as tabular and its `+ − ±` as real glyphs. The minus is drawn at `scaleX(.62)`. Original typefaces, not any broadcast face |
| **UI** `--font-sans` | `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Segoe UI", Roboto, sans-serif` (HeroUI's default feel) | Everything else: labels, titles, body |
| **Code** `--pw-font-mono` | `ui-monospace, "SF Mono", Menlo, Consolas, monospace` | Fact ids, IPs, tokens, wheel menu codes |

- Titles and section headings in **sentence case** (HeroUI taste), never all caps. Caps only for short signal words:
  `AHEAD`, `BEHIND`, `LEVEL`, `BRAKE`, `MARKER`, `FOCUS`, timing tags, flag-band words.
- App scale (Review, Setup, Settings; `rem`, follows Dynamic Type): body 16 px / 1.5, secondary 14 px, controls
  14 px (HeroUI default), card titles 16 px / 600, page titles 24 px / 600, KPI values 32 px numerals, table cells
  15 px numerals.
- Drive scale: 4.1 (fixed glance tokens, not Dynamic Type).
- Non-Apple devices fall back to Roboto Condensed or Arial Narrow. Bundling Barlow Semi Condensed (SIL OFL) is an
  optional later task with a `docs/licences.md` entry.

### 9.4 Shape, spacing, elevation

- `--radius: 0.5rem` (HeroUI default; today's `0.625rem` makes cards 30 px round, too soft for a dense Drive grid).
  Cards 24 px, fields 12 px, buttons and chips pills. Drive strips ≤ 72 px tall use `rounded-2xl` (16 px).
- Spacing on HeroUI's 4 px grid: card padding 16 px (Drive) / 20-24 px (app pages); gaps 10 px on Drive, 16-24 px
  elsewhere; page top padding 24 px under the area header.
- Elevation from surface steps only; no shadows in dark (HeroUI's own dark default) and none anywhere inside Drive.
- Borders only where they carry meaning: the rail's edge, outline bands, the focus ring, control boundaries.
- Hatching means "not real data" (synthetic). The mockup's dashed "needs D-n" outline is a mockup-only convention.

### 9.5 Motion

- Drive numerals never animate; bars move with an 80 ms linear transition; a completed sector does one 600 ms fade
  of its tint. Nothing pulses, glows or blinks (WCAG 2.3.1); bands appear without animation.
- App pages may use HeroUI's built-in transitions (tabs indicator, sheets). `prefers-reduced-motion` turns them off
  (HeroUI's own `motion-reduce` rules plus our tokens).

### 9.6 Copy rules

- Unknown is `-`. Empty states say why in words ("No laps yet: drive a clean lap").
- Minus `−` (U+2212). Times `m:ss.SSS`, sectors `ss.SSS`, distances `285 m`, thousands with a thin space in prose
  (`5 890 m`).
- Coaching text is the backend's. The UI may add an evidence line from the observation's fields (`impact_s`,
  `confidence`, `consistency`): "Seen on 3 of your last 5 laps · about 0.12 s a lap · confidence high". Confidence in
  words: high ≥ 0.8, medium 0.6-0.8, low < 0.6.
- Plain labels: "Time lost here" (not Δt), "Braked" (not "Brake pt Δ"), "Slowest speed" (not V-min), "Clean laps",
  "Your target lap" (beginners) or "Reference" (others). The glossary explains terms, never actions.
- **[critic]** Signed deltas (`−0.21`, `+0.11 s`) belong to Drive, Compare, tables and advanced density. Review
  tiles and beginner cards say the direction in words: "2.50 s faster", "about 0.11 s a lap lost here".

### 9.7 Brand and trademarks

Pitwall name and zig-zag mark, Pitwall orange. Gravity UI icons (MIT). No F1, FIA, FOM, game publisher or team
names, logos, wordmarks, liveries or typefaces in the chrome; track, car and corner names appear only as data (the
verified track sheets). Purple / green / yellow timing and flag colours are generic motorsport conventions, used with
original styling.

---

## 10. Component map: HeroUI v3, HeroUI Pro, custom

### 10.1 Imports and how to check an API

```ts
// OSS (MIT): @heroui/react 3.2.6
import { Alert, AlertDialog, Avatar, Breadcrumbs, Button, Card, Chip, ColorSwatchPicker, Disclosure, Dropdown, Kbd,
  Meter, Modal, Popover, ProgressBar, ScrollShadow, Select, Skeleton, Tabs, TextField, Toast, Tooltip } from "@heroui/react";
// Pro (licensed): components exported from the package root
import { ActionBar, CellSelect, CellSlider, CellSwitch, ChatConversation, ChatMessage, ChatSource, ChatSources, Command,
  DataGrid, EmptyState, InlineSelect, ItemCard, ItemCardGroup, KPIGroup, ListView, PressableFeedback, PromptInput,
  PromptSuggestion, RadioButtonGroup, Segment, Sheet, Stepper, Timeline, TrendChip } from "@heroui-pro/react";
// Pro components that are ONLY exported from a subpath (checked against dist/components/index.d.ts of
// 1.0.0-beta.10): kpi, line-chart, area-chart, bar-chart, composed-chart, pie-chart, radar-chart, radial-chart,
// markdown, code-block, number-stepper, carousel, map, resizable, rich-text-editor, chat-tool.
import { KPI } from "@heroui-pro/react/kpi";
import { LineChart } from "@heroui-pro/react/line-chart";
import { AreaChart } from "@heroui-pro/react/area-chart";
import { BarChart } from "@heroui-pro/react/bar-chart";
import { Markdown } from "@heroui-pro/react/markdown";   // [critic] needs its peer dependencies, see below
// [critic] No CodeBlock: it imports `shiki` (not installed, several MB of grammars) for two URLs and one request
// dump. Use the custom `CopyField` (10.6) and a plain `<pre>` in a `Card` instead.
```

- **[critic] Peer dependencies that are not installed.** Checked against `web-react/node_modules` on 2026-10-11:
  `@heroui-pro/react/markdown` imports `react-markdown`, `remark-gfm`, `remark-breaks`, `streamdown` and `marked`,
  none of which is in `package.json`, so the session report and the engineer summary would not build. Lane S adds
  them in phase 0 (exact versions that satisfy Pro's `peerDependencies`, each licence checked and recorded in
  `docs/licences.md`) before lane R uses `Markdown`. `code-block` (`shiki`), `map` (`maplibre-gl`) and
  `rich-text-editor` (`@tiptap/*`) are not used. The root `@heroui-pro/react` import graph needs only installed
  packages (walked from `dist/index.js`: `@heroui/react`, `react-aria(-components)`, `react-stately`, `motion`,
  `react-resizable-panels`, `@internationalized/*`, `tailwind-variants`).

- `EmptyState` exists in both packages; use the Pro one (Media / Title / Description / Content slots).
- Before building with a component, read its types in `web-react/node_modules/@heroui-pro/react/dist/components/<name>/`
  (or `@heroui/react/dist/components/<name>/`) and the docs at heroui.pro/docs/react and heroui.com/docs/react. The
  HeroUI Pro MCP may not be available to every session. Never copy Pro source into the repo.
- Subpath imports (charts, `KPI`, `Markdown`) are only used in lazily loaded pages (on Drive: the lazy Session
  complete card, 4.9), which keeps Recharts and the markdown renderer out of the Drive bundle.

### 10.2 Shell

| Element | Component | Notes |
|---|---|---|
| App frame | Custom `AppShell` (**[critic]** exists today as `src/components/AppShell.tsx`, with `AreaNav`, `BottomTabBar` and `AreaTabs` inside it; lane S moves it to `src/components/shell/` and splits it) | Grid: rail + main; phone: app bar + main + tab bar. Not Pro `AppLayout` (0.3) |
| Rail | Custom `NavRail` of HeroUI `Link`-styled items, HeroUI `Tooltip` only on the Mac (pointer: fine) | 72 px; 3.2 |
| Drive lock on rail / tab / Segment items | Pro `PressableFeedback` + `PressableFeedback.HoldConfirm` (`duration={500}`) | Wraps the item only while the lock applies |
| Phone tab bar | Custom `BottomTabBar` (exists inside `AppShell.tsx`; moved to `shell/BottomTabBar.tsx`, restyled) | 64 px + safe area |
| Phone app bar | Custom `PhoneAppBar` | Title, connection pill, avatar |
| Area header | Custom `AreaHeader` = title + Pro `Segment` (`size="lg"`) + actions (HeroUI `Button`s) | |
| Driver menu | Existing `DriverSwitcher` (HeroUI `Dropdown`) moved to the rail foot | Keeps its live-session note and error handling |
| Connection | Existing `ConnectionStatus` (`src/components/ConnectionStatus.tsx`) renamed `StatusPill` (HeroUI `Chip` soft + `StatusDot`) | |
| Mini radio bar | Pro `ActionBar` (Prefix / Content / Suffix; `isOpen` = radio live and not on Drive) | 3.5. **[critic]** File `shell/MiniRadioBar.tsx`, owned by lane S, built from lane A's `radio/*` components |
| Toasts | HeroUI `Toast` (`Toast.Provider` in `App`) | Suppressed on track |
| Command palette | Pro `Command` | Mac `⌘K` |

### 10.3 Drive › Coach

| Element | Component | Custom part |
|---|---|---|
| Status slot | HeroUI `Card` (`rounded-2xl`, `p-0`) | `StatusLine` (pill, track, session, lap), `FlagBand` (fill/outline variants, `role`), HeroUI `Chip`s for evidence, incident, wake-lock; Pro `Segment` (`size="md"`) for the sub-pages |
| Hero (next corner) | HeroUI `Card` + `.pw-chamfer` class | `CornerHero`: label, name, distance numerals, `TurnIcon` (custom SVG left/right arrow); HeroUI `Chip` (`FOCUS`, accent outline); HeroUI `ProgressBar` (`aria-label="Approach"`, `transition-none`) |
| Cue band | inside the hero | `CueBand`: HeroUI `Chip` (`BRAKE` solid behind / `MARKER` default), text, distance |
| Coach card | HeroUI `Card` | `CoachPoint`: HeroUI `Chip` (`Work on · L6` warning soft / `Good · L6` success soft) + text with the length rule |
| Delta | HeroUI `Card` | `DeltaNumber` (span, 10 Hz), `DeltaBar` (two divs, `scaleX`), reference `Chip`, projected `TimingValue` |
| Sector cells | HeroUI `Card` (`variant="secondary"`) ×3 | `TimingCell` (tint + tag + value + sub line); running sector: HeroUI `ProgressBar` |
| Lap times | HeroUI `Card` | three `TimingRow`s (`TimingValue` + `TimingTag`); `INVALID` HeroUI `Chip` (danger soft) |
| Ribbon | HeroUI `Card` (`p-0`) | `LapRibbon` (SVG, shared with Review › Compare) |
| Radio strip | HeroUI `Card` | `RadioMessage` (HeroUI `Chip` kind + text + age), mic HeroUI `Chip`, `PushToTalkButton` (HeroUI `Button` `size="lg"`, `onPressStart` / `onPressEnd`, 220 × 56), `GoLiveButton` (HeroUI `Button` primary) |
| Ready card | HeroUI `Card` spanning the hero, coach and delta areas | HeroUI `Avatar` (72 px), `Button` (Switch driver opens `DriverSwitcher`), `Chip`s (focus corners, skill), `TimingValue`s |
| Session complete card | HeroUI `Card` | Pro `KPIGroup` + `KPI` (static, fine on Drive when stopped), Pro `ItemCard` ×2, HeroUI `Button` (64 px) |
| No-telemetry card | Pro `EmptyState` + Pro `Stepper` (vertical) | HeroUI `Button`s |
| Lock hint | Text inside the status slot (no toast) | |

### 10.4 Review

| Element | Component |
|---|---|
| Driver filter, density filter, Work on / Went well / All | Pro `Segment` (items with HeroUI `Avatar`) |
| Track, car, lap pickers | HeroUI `Select` (iPad), Pro `Sheet` with Pro `ListView` (phone) |
| Session list | Pro `ListView` per day group; row actions HeroUI `Dropdown` in a ghost `Button`; reassign HeroUI `Modal` |
| Last session card | HeroUI `Card` |
| Session header | HeroUI `Breadcrumbs` (no underline), `Chip`s, `Button`s; report: Pro `Sheet` + Pro `Markdown` |
| Session tabs | HeroUI `Tabs` (secondary) |
| KPI tiles | Pro `KPIGroup` + `KPI` (`KPI.Title`, `KPI.Content` with a `TimingValue` for times since `KPI.Value` formats plain numbers, `KPI.Trend` = `TrendChip`) |
| Work on card | HeroUI `Card` (Header / Content / Footer), `Chip` (corner), custom `TrackMap` (mini), HeroUI `Disclosure` (Why?), `Button`s |
| Went well | Pro `ItemCardGroup` + `ItemCard` |
| Lap times, best-here, progress charts | Pro `LineChart` (reversed `YAxis`, custom tick formatter `m:ss.S`, `ChartTooltip`) |
| Where the time is | Pro `BarChart` (horizontal) |
| Laps table, corner table, family board, capability matrix | Pro `DataGrid` |
| Compare traces | Pro `LineChart` / `AreaChart` with a shared Recharts `syncId`; `LapRibbon` header; custom `TrackMap` with cursor |
| Compatibility | HeroUI `Alert` |
| Corner cards | HeroUI `Card` |
| Ask | Pro `ChatConversation`, `ChatMessage`, `PromptInput`, `PromptSuggestion`, `ChatSources` / `ChatSource`; HeroUI `Chip` (grounded / deterministic) |
| Coaching plan | HeroUI `Card`, Pro `TrendChip`, Pro `ListView` (habits) |
| Milestones | Pro `Timeline` |
| Glossary `?` | HeroUI `Popover` on a 44 px icon `Button` |
| Empty states | Pro `EmptyState` |

### 10.5 Setup

| Element | Component |
|---|---|
| Connect steps | Pro `Stepper` (vertical); copy `Button`s; **[critic]** custom `CopyField` (URLs) |
| Live senders | Pro `ListView` + `Chip` |
| Rig views | Pro `Segment` (Walkthrough · All settings · Rig check · Upgrades) |
| Walkthrough sections | Pro `Stepper` (horizontal, `size="lg"`) |
| Step card | HeroUI `Card` + `.pw-chamfer`, `Kbd` (menu code), custom `SettingValue` (96 px numerals), `Chip`s, `Button`s (64 px) |
| Row list beside the step | Pro `ListView` |
| Provenance / sources | Pro `Sheet` |
| Hardware profile | Pro `CellSelect` rows |
| Driver style | Pro `RadioButtonGroup` |
| Strength scale | Pro `CellSlider` |
| Rig check | Pro `ListView` + `Chip` (status) + HeroUI `Disclosure` |
| Upgrade history | Pro `Timeline`; diffs Pro `DataGrid`; record upgrade HeroUI `Modal` |
| Car setup request | Pro `InlineSelect` ×5 in a sentence |
| Setup groups | HeroUI `Card` per group; custom `RangeMarker` per row; HeroUI `Chip`s |
| Yours vs recommended | Pro `DataGrid` |
| Experiments | Pro `ItemCard` + Pro `Stepper`; new experiment HeroUI `Modal` |

### 10.6 Shared custom components (`src/components/ui`, `src/components/viz`, `src/components/radio`)

| Component | Props (essentials) | Used by |
|---|---|---|
| `TimingValue` | `ms`, `kind` (lap, sector or delta), `status: TimingStatus`, `size`, `running?` | Everywhere a time appears. `-` for null. Dark: coloured text; light: filled chip |
| `TimingTag` | `status` → `REC` / `PB` / `SB` / `INV` chip | Drive, Review, Progress |
| `TimingCell` | `label`, `value`, `status`, `sub`, `progress` | Drive sectors, Ready card, Review tiles |
| `TimingLegend` | `tier` | Every timing surface |
| `EvidenceChips` | `synthetic`, `replay` | Drive, Review |
| `CornerTag` | `label`, `name`, `focus?` | Drive, Review, Track |
| `Glossary` | `term` | Review (beginners) |
| `Unknown` | – | Renders the `-` in `--pw-faint` with `aria-label="unknown"` |
| **[critic]** `CopyField` | `value`, `label`, `mono?` | Setup › Connect (URLs, IP, port), Settings › System. Replaces Pro `CodeBlock` (no `shiki`) |
| `SettingValue` | `value`, `unit`, `size` | Rig walkthrough, car setup |
| `RangeMarker` | `min`, `max`, `value`, `spread?` | Car setup |
| `LapRibbon` | `ribbon` view model (4.10), `height` | Drive Coach, Review Compare |
| `TrackMap` | `model`, `skeleton`, `car?`, `highlight?`, `segmentDelta?`, `cursorM?`, `flags?` | Car wall, Track, Review |
| `LiveTrace` | `history`, `hz` | Car wall |
| `PushToTalkButton`, `GoLiveButton`, `RadioMessage`, `MicChip` | radio store | Drive strip, Radio page, mini radio bar |

---

## 11. `web-react/src/styles/tokens.css` update plan

Keep the file's structure (HeroUI semantic variables per scheme, then `--pw-*` domain tokens, then `@theme inline`)
and its import into the `theme` layer after `@heroui/styles` and `@heroui-pro/react/css`. Changes:

1. `--radius` `0.625rem` → `0.5rem` (cards 24 px, fields 12 px).
2. Recolour the HeroUI semantic variables for both schemes (9.2): darker dark background, the surface steps,
   `--muted`, `--accent` (light: `#c2410c` with white ink), `--success` = timing green, `--warning` = amber,
   `--danger` = behind red. Every variable set for one scheme is also set for the other.
3. Replace the domain tokens: `--pw-rec`, `--pw-pb`, `--pw-slower` (+ light fill/ink pairs), `--pw-ahead`,
   `--pw-behind`, `--pw-stale`, `--pw-ref`, `--pw-cmp`, `--pw-synthetic` (pink) + `--pw-hatch-synthetic`, flag bands
   with inks, neutral `--pw-sector-1..3`, `--pw-line-strong`, `--pw-faint`. **[critic] Deprecate, do not remove yet,**
   `--pw-sector-best`, `--pw-sector-pb`, `--pw-sector-slower`, `--pw-gain` and `--pw-loss` (and their `text-*`
   utilities): keep them as aliases of the new tokens (`--pw-gain` → `--pw-ahead`, `--pw-loss` → `--pw-stale`,
   `--pw-sector-best` → `--pw-pb`, …) with a `/* deprecated */` comment. v2 had lane T fix the call sites "in the
   same change", but two of them belong to other lanes in the same phase: `components/DriverSwitcher.tsx` (lane S,
   phase 0) and `pages/drive/DrivePage.tsx` (lane DV). So: T changes its own `lib/format.ts` `deltaClass`
   (`text-gain` / `text-loss` → `text-ahead` / `text-behind`); S changes `DriverSwitcher.tsx` (`text-loss` →
   `text-warning`) in its phase 0 shell work; `DrivePage.tsx` keeps the aliases until DV deletes it (phase 2, when
   `CarPage` replaces it); T removes the aliases in phase 3 after `grep -rn "pw-gain\|pw-loss\|sector-best\|text-gain\|text-loss" src`
   is empty.
4. Add the Drive scale (`--pw-d-*`), layout tokens (`--pw-rail-w`, `--pw-status-h`, …), touch targets and fonts.
5. Add the night, red-green-safe, Large and `.pw-drive` blocks.
6. Extend `@theme inline` so Tailwind utilities exist for all of them (`text-pw-rec`, `bg-flag-yellow`,
   `font-num`, `text-d-delta`, …).

Paste-ready:

```css
/* Pitwall design tokens (docs/ui/design-spec.md v2, section 9 and 11). Dark is the default (index.html sets
 * class="dark" data-theme="dark"). Imported into the `theme` layer after @heroui/styles and @heroui-pro/react/css.
 * Colours are oklch (HeroUI convention); hex in comments. Contrast: web-react/scripts/contrast.mjs. */

@layer base {
  :root,
  :host {
    --radius: 0.5rem;
    --field-radius: calc(var(--radius) * 1.5);

    --pw-font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Segoe UI", Roboto, sans-serif;
    --pw-font-num: "DIN Condensed", "DIN Alternate", "Avenir Next Condensed", "Barlow Semi Condensed",
      "Roboto Condensed", "Arial Narrow", sans-serif;
    --pw-font-mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    --pw-font-timing: var(--pw-font-num); /* old name, kept until every .timing use is migrated */

    --pw-touch: 44px;        /* everywhere */
    --pw-touch-drive: 56px;  /* Drive and sheets */
    --pw-touch-glove: 64px;  /* Go live, Switch driver, Review this session, Done next */
    --pw-rail-w: 72px;
    --pw-tabbar-h: 64px;
    --pw-appbar-h: 52px;
    --pw-status-h: 52px;

    /* Drive glance scale (baseline values at 1180 × 820 in comments). Not Dynamic Type. */
    --pw-drive-k: 1;
    --pw-d-delta: calc(clamp(104px, 17.6dvh, 172px) * var(--pw-drive-k));  /* 144 */
    --pw-d-corner: calc(clamp(84px, 13.6dvh, 132px) * var(--pw-drive-k));  /* 112 */
    --pw-d-xl: calc(clamp(34px, 5.4dvh, 52px) * var(--pw-drive-k));        /*  44 */
    --pw-d-l: calc(clamp(30px, 4.9dvh, 48px) * var(--pw-drive-k));         /*  40 */
    --pw-d-m: calc(clamp(26px, 3.9dvh, 38px) * var(--pw-drive-k));         /*  32 */
    --pw-d-s: calc(clamp(22px, 3.2dvh, 30px) * var(--pw-drive-k));         /*  26 */
    --pw-d-xs: calc(clamp(18px, 2.7dvh, 24px) * var(--pw-drive-k));        /*  22 */
    --pw-d-label: clamp(13px, 1.85dvh, 16px);                              /*  15 */

    /* Flag bands: the same in every theme (filled, with ink). */
    --pw-flag-yellow: oklch(0.8789 0.1617 90.94);   --pw-flag-yellow-ink: oklch(0.1717 0.0141 258.35); /* #ffd23f / #0c1016 13.2:1 */
    --pw-flag-sc: oklch(0.8131 0.1650 75.04);       --pw-flag-sc-ink: oklch(0.1717 0.0141 258.35);     /* #ffb020 10.4:1 */
    --pw-flag-red: oklch(0.5707 0.2087 21.14);      --pw-flag-red-ink: oklch(1 0 0);                   /* #d7263d 5.0:1 */
    --pw-flag-blue: oklch(0.5461 0.2152 262.88);    --pw-flag-blue-ink: oklch(1 0 0);                  /* #2563eb 5.2:1 */
    --pw-pit: oklch(0.7753 0.1352 234.51);          --pw-pit-ink: oklch(0.1717 0.0141 258.35);         /* #4cc3ff 9.6:1 */

    /* Tyre surface temperature bands (unchanged meaning; in-window is plain foreground, not green). */
    --pw-tyre-cold: oklch(0.7535 0.1390 232.66);
    --pw-tyre-cool: oklch(0.8276 0.1013 230.32);
    --pw-tyre-hot: oklch(0.8131 0.1650 75.04);
    --pw-tyre-over: oklch(0.6841 0.2060 18.57);
  }

  /* ---------------------------------------------------------------- light */
  :root,
  .light,
  [data-theme="light"] {
    color-scheme: light;
    --background: oklch(0.9695 0.0045 258.32);           /* #f3f5f8 */
    --foreground: oklch(0.1717 0.0141 258.35);           /* #0c1016 19.1:1 on white */
    --surface: oklch(1 0 0);                             /* #ffffff */
    --surface-foreground: var(--foreground);
    --surface-secondary: oklch(0.9570 0.0063 255.48);    /* #eef1f5 */
    --surface-secondary-foreground: var(--foreground);
    --surface-tertiary: oklch(0.9292 0.0109 256.70);     /* #e3e8ef */
    --surface-tertiary-foreground: var(--foreground);
    --overlay: oklch(1 0 0);
    --overlay-foreground: var(--foreground);
    --muted: oklch(0.4538 0.0277 258.37);                /* #4d5766 7.3:1 */
    --default: oklch(0.9292 0.0109 256.70);
    --default-foreground: var(--foreground);
    --field-background: oklch(1 0 0);
    --field-foreground: var(--foreground);
    --border: oklch(0.8991 0.0122 259.82);               /* #d9dee6 */
    --separator: oklch(0.9292 0.0109 256.70);
    --segment: oklch(1 0 0);
    --segment-foreground: var(--foreground);
    --accent: oklch(0.5534 0.1739 38.40);                /* #c2410c fill and text, 5.2:1 */
    --accent-foreground: oklch(1 0 0);                   /* white on accent 5.2:1 */
    --success: oklch(0.5081 0.1049 165.61);              /* #047857 */
    --success-foreground: oklch(1 0 0);
    --warning: oklch(0.5310 0.1190 65.12);               /* #9a5b00 */
    --warning-foreground: oklch(1 0 0);
    --danger: oklch(0.5382 0.2004 19.91);                /* #c81e3a */
    --danger-foreground: oklch(1 0 0);

    --pw-faint: oklch(0.5173 0.0253 256.79);             /* #5f6977 5.6:1 */
    --pw-line-strong: oklch(0.6436 0.0253 258.37);       /* #848e9d 3.3:1 */
    --pw-rec: oklch(0.4907 0.2412 292.58);   --pw-rec-fg: oklch(1 0 0);   --pw-rec-bg: var(--pw-rec);     /* #6d28d9 7.1:1 */
    --pw-pb: oklch(0.5081 0.1049 165.61);    --pw-pb-fg: oklch(1 0 0);    --pw-pb-bg: var(--pw-pb);       /* #047857 5.5:1 */
    --pw-slower: oklch(0.8789 0.1617 90.94); --pw-slower-fg: var(--foreground); --pw-slower-bg: var(--pw-slower); /* 13.2:1 */
    --pw-ahead: var(--pw-pb);
    --pw-behind: var(--danger);
    --pw-brake: var(--danger);
    --pw-throttle: var(--pw-pb);
    --pw-stale: var(--warning);
    --pw-bad: var(--danger);
    --pw-ref: oklch(0.5000 0.1193 242.75);               /* #0369a1 */
    --pw-cmp: var(--foreground);
    --pw-synthetic: oklch(0.5246 0.1990 3.96);           /* #be185d */
    --pw-sector-1: oklch(0.8830 0.0128 255.51);          /* #d3d9e1 neutral steps: identity by label */
    --pw-sector-2: oklch(0.8459 0.0159 257.20);          /* #c6cdd7 */
    --pw-sector-3: oklch(0.8080 0.0178 256.29);          /* #b9c1cc */
    --pw-status-live: var(--pw-pb);
    --pw-status-stale: var(--pw-stale);
    --pw-status-idle: var(--pw-faint);
    --pw-status-offline: var(--pw-bad);
    --pw-tyre-optimal: var(--foreground);
  }

  /* ---------------------------------------------------------------- dark (default) */
  .dark,
  [data-theme="dark"] {
    color-scheme: dark;
    --background: oklch(0.1331 0.0082 254.42);           /* #06080b */
    --foreground: oklch(0.9570 0.0063 255.48);           /* #eef1f5 16.5:1 on surface */
    --surface: oklch(0.1848 0.0120 254.13);              /* #0f1318 */
    --surface-foreground: var(--foreground);
    --surface-secondary: oklch(0.2202 0.0157 256.82);    /* #161b22 */
    --surface-secondary-foreground: var(--foreground);
    --surface-tertiary: oklch(0.2617 0.0197 254.84);     /* #1e252e */
    --surface-tertiary-foreground: var(--foreground);
    --overlay: oklch(0.2202 0.0157 256.82);
    --overlay-foreground: var(--foreground);
    --muted: oklch(0.7442 0.0231 256.75);                /* #a3adbb 8.2:1 */
    --default: oklch(0.2617 0.0197 254.84);
    --default-foreground: var(--foreground);
    --field-background: oklch(0.2202 0.0157 256.82);
    --field-foreground: var(--foreground);
    --border: oklch(0.3143 0.0227 256.40);               /* #2a323d */
    --separator: oklch(0.2617 0.0197 254.84);
    --segment: oklch(0.3143 0.0227 256.40);
    --segment-foreground: var(--foreground);
    --accent: oklch(0.7025 0.1956 40.75);                /* #ff6a2b 6.5:1 */
    --accent-foreground: oklch(0.1717 0.0141 258.35);    /* dark ink 6.7:1 (white fails) */
    --success: oklch(0.8074 0.1971 152.73);              /* #2fe37f */
    --success-foreground: oklch(0.1717 0.0141 258.35);
    --warning: oklch(0.8131 0.1650 75.04);               /* #ffb020 */
    --warning-foreground: oklch(0.1717 0.0141 258.35);
    --danger: oklch(0.6841 0.2060 18.57);                /* #ff5466 6.0:1 */
    --danger-foreground: oklch(0.1717 0.0141 258.35);

    --pw-faint: oklch(0.6332 0.0273 257.67);             /* #808b9b 5.4:1 */
    --pw-line-strong: oklch(0.5138 0.0288 257.68);       /* #5d6878 3.3:1 */
    --pw-rec: oklch(0.7410 0.1690 305.53);   --pw-rec-fg: var(--pw-rec);
    --pw-rec-bg: color-mix(in oklab, var(--pw-rec) 10%, var(--surface));        /* #c58cff 7.6:1, 6.6:1 on tint */
    --pw-pb: oklch(0.8074 0.1971 152.73);    --pw-pb-fg: var(--pw-pb);
    --pw-pb-bg: color-mix(in oklab, var(--pw-pb) 10%, var(--surface));          /* #2fe37f 11.0:1, 9.2:1 on tint */
    --pw-slower: oklch(0.8789 0.1617 90.94); --pw-slower-fg: var(--pw-slower);
    --pw-slower-bg: color-mix(in oklab, var(--pw-slower) 10%, var(--surface));  /* #ffd23f 12.9:1, 10.5:1 on tint */
    --pw-ahead: var(--pw-pb);
    --pw-behind: var(--danger);
    --pw-brake: var(--danger);
    --pw-throttle: var(--pw-pb);
    --pw-stale: var(--warning);
    --pw-bad: var(--danger);
    --pw-ref: oklch(0.7753 0.1352 234.51);               /* #4cc3ff 9.4:1 */
    --pw-cmp: var(--foreground);
    --pw-synthetic: oklch(0.7538 0.1782 349.43);         /* #ff7ac0 7.8:1 */
    --pw-sector-1: oklch(0.3369 0.0229 253.60);          /* #2f3843 */
    --pw-sector-2: oklch(0.3825 0.0244 253.12);          /* #3a4450 */
    --pw-sector-3: oklch(0.4303 0.0258 252.72);          /* #46515e */
    --pw-status-live: var(--pw-pb);
    --pw-status-stale: var(--pw-stale);
    --pw-status-idle: var(--pw-faint);
    --pw-status-offline: var(--pw-bad);
    --pw-tyre-optimal: var(--foreground);
  }

  /* Night dim (dark only): for a dark room with the iPad brightness low. */
  :root[data-night="on"]:is(.dark, [data-theme="dark"]) {
    --background: oklch(0 0 0);
    --surface: oklch(0.1540 0.0092 264.28);              /* #0a0c10 */
    --surface-secondary: oklch(0.1864 0.0132 264.18);    /* #101319 */
    --surface-tertiary: oklch(0.2293 0.0173 259.75);     /* #181d25 */
    --border: oklch(0.2379 0.0171 259.76);
    --pw-line-strong: oklch(0.4173 0.0247 257.52);
    --foreground: oklch(0.8499 0.0124 259.82);           /* #c9ced6 12.4:1 */
    --muted: oklch(0.6635 0.0219 257.49);                /* #8b94a1 6.4:1 */
    --pw-faint: oklch(0.6028 0.0231 254.98);             /* #78828f 5.0:1 */
    --accent: oklch(0.6425 0.1729 41.13);                /* #e0602a */
    --success: oklch(0.7236 0.1753 152.98);              /* #28c46e */
    --warning: oklch(0.7371 0.1492 74.87);               /* #e09a1c */
    --danger: oklch(0.6219 0.1854 18.35);                /* #e04a5a 4.9:1, used at >= 32 px only */
    --pw-rec: oklch(0.6779 0.1619 305.59);               /* #b07ae6 */
    --pw-pb: oklch(0.7236 0.1753 152.98);
    --pw-slower: oklch(0.7965 0.1466 90.85);             /* #e0b836 */
  }

  /* Red-green safe colour vision: green -> blue, red -> orange. Signs, words, tags and bar direction stay. */
  :root[data-cvd="rg"] {
    --pw-pb: oklch(0.5000 0.1193 242.75);  --pw-behind: oklch(0.5043 0.1341 48.21);   /* light: #0369a1 / #9f4706 */
    --pw-brake: var(--pw-behind); --pw-bad: var(--pw-behind); --success: var(--pw-pb); --danger: var(--pw-behind);
  }
  :root[data-cvd="rg"]:is(.dark, [data-theme="dark"]) {
    --pw-pb: oklch(0.7753 0.1352 234.51);  --pw-behind: oklch(0.7828 0.1680 66.20);   /* dark: #4cc3ff / #ff9f1c */
  }

  :root[data-drive-size="large"] { --pw-drive-k: 1.12; }

  /* Drive: no shadows, no blur. (Drive always dark is applied to <html> by prefs.effectiveTheme, see below.) */
  .pw-drive { --surface-shadow: none; }

  .pw-hatch-synthetic {
    background-image: repeating-linear-gradient(135deg,
      color-mix(in oklab, var(--pw-synthetic) 24%, transparent) 0 6px, transparent 6px 12px);
  }
}

@theme inline {
  --font-sans: var(--pw-font-sans);
  --font-num: var(--pw-font-num);
  --font-mono: var(--pw-font-mono);
  --font-timing: var(--pw-font-num);

  --text-d-delta: var(--pw-d-delta);   --text-d-corner: var(--pw-d-corner);  --text-d-xl: var(--pw-d-xl);
  --text-d-l: var(--pw-d-l);           --text-d-m: var(--pw-d-m);            --text-d-s: var(--pw-d-s);
  --text-d-xs: var(--pw-d-xs);         --text-d-label: var(--pw-d-label);

  --color-faint: var(--pw-faint);       --color-line-strong: var(--pw-line-strong);
  --color-pw-rec: var(--pw-rec);        --color-pw-rec-fg: var(--pw-rec-fg);       --color-pw-rec-bg: var(--pw-rec-bg);
  --color-pw-pb: var(--pw-pb);          --color-pw-pb-fg: var(--pw-pb-fg);         --color-pw-pb-bg: var(--pw-pb-bg);
  --color-pw-slower: var(--pw-slower);  --color-pw-slower-fg: var(--pw-slower-fg); --color-pw-slower-bg: var(--pw-slower-bg);
  --color-ahead: var(--pw-ahead);       --color-behind: var(--pw-behind);
  --color-brake: var(--pw-brake);       --color-throttle: var(--pw-throttle);
  --color-stale: var(--pw-stale);       --color-bad: var(--pw-bad);
  --color-ref: var(--pw-ref);           --color-cmp: var(--pw-cmp);                --color-synthetic: var(--pw-synthetic);
  --color-sector-1: var(--pw-sector-1); --color-sector-2: var(--pw-sector-2);      --color-sector-3: var(--pw-sector-3);
  --color-status-live: var(--pw-status-live);   --color-status-stale: var(--pw-status-stale);
  --color-status-idle: var(--pw-status-idle);   --color-status-offline: var(--pw-status-offline);
  --color-flag-yellow: var(--pw-flag-yellow);   --color-flag-yellow-ink: var(--pw-flag-yellow-ink);
  --color-flag-sc: var(--pw-flag-sc);           --color-flag-sc-ink: var(--pw-flag-sc-ink);
  --color-flag-red: var(--pw-flag-red);         --color-flag-red-ink: var(--pw-flag-red-ink);
  --color-flag-blue: var(--pw-flag-blue);       --color-flag-blue-ink: var(--pw-flag-blue-ink);
  --color-pit: var(--pw-pit);                   --color-pit-ink: var(--pw-pit-ink);
  --color-tyre-cold: var(--pw-tyre-cold);       --color-tyre-cool: var(--pw-tyre-cool);
  --color-tyre-optimal: var(--pw-tyre-optimal); --color-tyre-hot: var(--pw-tyre-hot); --color-tyre-over: var(--pw-tyre-over);
}
```

Also in `src/styles/index.css`: `.timing` uses `var(--pw-font-num)`; add `.pw-chamfer` (the hero cut and the
accent edge), `.pw-num` (numerals with the narrowed minus), and `.pt-safe` on the shell root.

```css
@layer utilities {
  .pw-chamfer { clip-path: polygon(0 0, calc(100% - 22px) 0, 100% 22px, 100% 100%, 0 100%); position: relative; }
  .pw-chamfer::before { content: ""; position: absolute; top: 0; left: 24px; right: 30px; height: 3px;
                        border-radius: 0 0 3px 3px; background: var(--accent); }
}
```

`lib/prefs.ts` sets on `<html>`: `class` and `data-theme` from `effectiveTheme(route)` (the chosen theme, or match
device; **dark whenever a Drive page is open and *Drive always dark* is on**, so the rail, the Drive grid and any
overlay all switch together), `data-night="on"`, `data-cvd="rg"`, `data-drive-size="large"`. The Drive root carries
`pw-drive`.

---

## 12. Routes, pages and the data layer

### 12.1 `src/routes.tsx`

Keep `AREAS` as the single source of truth for the rail, the tab bar, the Segments and the page registry; replace
the placeholder fields (`planned`, `ports`, `pro`) with a lazily loaded component per page once a page is real.

```tsx
export interface PageDef { id: string; label: string; summary: string; component: LazyExoticComponent<ComponentType<PageProps>> }
export const AREAS: AreaDef[] = [
  { id: "drive", label: "Drive", icon: Speedometer, pages: [
    { id: "coach", label: "Coach", summary: "What to do next", component: CoachPage /* eager: not lazy */ },
    { id: "car", label: "Car", ... }, { id: "track", label: "Track", ... }, { id: "radio", label: "Radio", ... } ] },
  { id: "review", label: "Review", icon: ChartLine, pages: [ sessions, coaching, progress, ask ] },
  { id: "setup", label: "Setup", icon: Wrench, pages: [ connect, rig, car ] },
  { id: "settings", label: "Settings", icon: Gear, pages: [ drivers, radio, ai, display, system ] },
];
```

`App.tsx` renders `AREAS[area].pages[page].component` inside `<Suspense fallback={<PageSkeleton/>}>`; the session
detail is `SessionsPage` with `param` parsed by `parseSessionParam(param) → { id, tab }`, and the rig walkthrough is
`RigPage` with `parseRigParam(param) → { view, section, n }`.

### 12.2 `src/lib/route-parse.ts` (+ tests)

- `DEFAULT_PAGE`: `drive: "coach"`, `review: "sessions"`, `setup: "rig"`, `settings: "drivers"`.
- New `AREA_ALIASES` for area-qualified interim ids: `drive/live → drive/coach`, `review/compare → review/sessions`,
  `settings/engine → settings/ai`, `settings/status → settings/system`.
- `legacyRedirect`: `live → /drive/coach`, `engineer → /review/ask`, `carsetup → /setup/car`; the others stay (2.4).
- `areaPath(area, remembered?)`: the remembered sub-page when known, else `DEFAULT_PAGE`.
- New tests: every row of 2.4 including `#/radio?token=abc → #/drive/radio?token=abc`, the aliases, unknown pages
  falling back to the area's default, and session / rig params.

### 12.3 Stores and hooks

| Module | Kind | Owner lane | What |
|---|---|---|---|
| `lib/live.ts` (exists) | store | S (frozen API) | `/ws/live`, static merge, 12 s history, offline clearing |
| `lib/drivers.ts` (exists) | store | S | Profiles, active driver, switching |
| `lib/prefs.ts` (new; `theme.ts` becomes a re-export) | store | S | theme, driveAlwaysDark, night, cvd, driveSize, dimNav, driveLock; per device, `try/catch` storage |
| `lib/router.ts` (exists) | store | S | + remembered sub-pages |
| `lib/radio.ts` (new) | store | A | Port of `web/src/lib/radio.svelte.ts` with the same public API (`phase`, `conn`, `mic`, `current`, `log`, `server`, `pttHeld`, `goLive()`, `pttPress()`, `pttRelease()`, `stop()`, settings) on the `Store` base class; `public/mic-worklet.js` copied |
| `lib/cache.ts` (new) | store | S | Request cache keyed by URL: dedupe, `invalidate(prefix)`, `refetchOnFocus`; no new dependency |
| `lib/wake.ts` (new) | helper | DV | Screen wake lock while live on Drive |
| `hooks/stores.ts` (exists) | hooks | S | `useLive`, `useDrivers`, `useActiveDriver`, `useRoute`, + `usePrefs`, `useRadio` |
| `hooks/useApi.ts` (new) | hook | S | `useApi(key, fetcher, { intervalMs?, enabled? })` → `{ data, error, loading, refresh }` over `cache.ts` |
| `hooks/useDriveModel.ts` (new) | hook | DV | `driveModel()` memoised per snapshot + a 1 Hz `nowS` tick |
| `hooks/useThrottledValue.ts` (new) | hook | DV | The 10 Hz delta string |

**Invalidation:** a `lap` event on `/ws/live` invalidates `session:<live session id>`, `analysis:<id>`, `sessions`
and `driver-sessions:<driver>`; a driver switch invalidates `sessions` and `rig:recommendations`; a successful
mutation invalidates its own prefix. Polling only where the data changes on its own: `/api/connect` every 2 s while
Setup › Connect or the no-telemetry card is visible, `/api/health` every 10 s on Settings › System.

### 12.4 Endpoint modules (`src/lib/endpoints/`)

`src/lib/api.ts` stays frozen (it is the shared merge point); each lane adds a typed module, and new response types
live there.

| Module | Owner | Endpoints |
|---|---|---|
| `review.ts` | R | `/api/sessions`, `/api/sessions/{id}`, `/analysis`, `/report`, `/events`, `/api/laps/{id}/trace`, `/api/compare`, `POST /api/references`, `POST /api/drivers/sessions/{id}/assign`, `/api/drivers/{id}/sessions`, D5 `/api/drivers/{id}/progress`, `/api/engineer/ask`, `/api/engineer/history`, `/api/engineer/facts` |
| `rig.ts` | X | `/api/rig/catalog`, `/profile` (GET/PUT), `/upgrades`, `/drivers/{id}/prefs`, `/recommendations`, `/check` |
| `carsetup.ts` | X | `/api/carsetup/catalog`, `/recommendation`, `/sessions/{sid}`, `/experiments` (+ start / conclude / abandon) |
| `connect.ts` | X | `/api/connect`, `/api/integrations` |
| `settings.ts` | Y | `/api/llm/*`, `/api/voice/status`, `/api/health`, `/api/llm/health`, `/api/capabilities`, `/api/captures`, `/api/replay`, `/api/simulate` |

---

## 13. Data contract and backend additions

**have** = in the current API; **derive** = computed in the browser from existing fields; **D1-D6** = backend
additions. Each is additive, `null` when unknown, follows the evidence tiers, and has a UI fallback until it lands.

| UI element | Source | Status |
|---|---|---|
| Delta, reference label | `delta_s`, `reference.{lap_number, lap_time_ms, session_id}` | have |
| Projected lap | `reference.lap_time_ms + delta_s` | derive |
| Corner ahead, distance, approach | `track_model.corners[].{entry_m, apex_m}`, `frame.lap_distance_m`, `skeleton.track_length_m` | derive |
| Official label and name | `track_model.corners[].{label, display_name, identity_tier}` (in the live payload via `track_model_payload`) | have |
| Cue next, last outcome, focus, notches, mode | `cues.{next, last, timing.margin_m, focus, cues[], mode, muted, reason}` (**[critic]** `muted` is `"radio off"` whenever no radio is connected; `next` is still sent, 4.5) | have |
| Lap clock, lap n / total, invalid, position | `frame.*`, `session.total_laps` | have |
| Current-lap sectors | none | **D1** |
| Completed laps with sectors | `laps[]` (20 newest) | have |
| Session best lap and sectors | `laps[]` | derive (exact with D2) |
| PB and household record (lap and sectors, per car) | `drivers[].stats.best_laps` (lap only, per track) | **D2** |
| Exact garage / out lap | `frame.pit_status`, speed (heuristic) | **D3** |
| Session ended / red flag | `events[]` (last 10) | derive (exact with D4) |
| Flags, safety car, pit lane and limit | `marshal_flags`, `skeleton.{marshal_zones, pit_speed_limit_kph}`, `session.safety_car_status`, `frame.pit_status` | have |
| Coaching point on Drive | `observations[]` (unfiltered) | **D6** for parity with the radio |
| Session review | `/api/sessions/{id}`, `/analysis`, `/report`, `/api/compare`, `/api/laps/{id}/trace` | have |
| Progress beyond lap level | `/api/drivers/{id}/sessions` | **D5** |
| **[critic]** Clean laps per session in lists (Sessions rows, Progress tiles) | `repo.list_sessions` has `lap_count`, `best_clean_ms` only | **D5** (`clean_lap_count`) |
| Rig walkthrough, rig check, upgrades | `/api/rig/recommendations` (sections, steps, rows, provenance), `/api/rig/check`, `/api/rig/profile` | have (hot, 14.3) |
| Car setup | `/api/carsetup/*` | have |

| Id | Addition | Files | UI without it |
|---|---|---|---|
| **D1** | `frame.current_lap_sector_ms: [s1, s2]` from the game's lap data (F1 `sector1TimeMSPart` / `MinutesPart`, already parsed for completed laps). `null` for games that do not send them | `model/telemetry.py`, `adapters/f1/adapter.py`, `core/live.py` (`frame_to_dict`), tests (`test_f1_protocol.py` stays green) | Sector cells show the last lap under `Last lap · L6` |
| **D2** | `snapshot.bests = {session, driver, household}`, each `{lap_ms, sectors_ms[3]}` (+ `set_unix` / `driver_id`), for the current game + track + car; clean laps only; synthetic and replay excluded; sector bests per sector; sent with the 5 s static payload and recomputed after each lap | `storage/repo.py`, `core/live.py`, `core/lap_processor.py`, tests | Green `SB` and yellow only; no purple, no `PB` |
| **D3** | `frame.driver_status` from F1's driver status (`in_garage`, `flying_lap`, `in_lap`, `out_lap`, `on_track`); `null` elsewhere | `adapters/f1/adapter.py`, `model/telemetry.py`, `core/live.py` | Garage state uses the `pit_status` / speed heuristic |
| **D4** | `snapshot.session_state`: `running` / `ended` / `red_flag`, kept server-side from events (`session_started`, `lights_out`, `chequered_flag`, `session_ended`, `red_flag`) | `core/live.py`, tests | Derived from the last 10 events |
| **D5** | `GET /api/drivers/{id}/progress?game&track_id&car`: per session `{session_id, started_unix, laps, clean_laps, best_clean_ms, median_clean_ms, spread_ms, corners: {corner: mean_time_delta_s}, habits: {kind: count}}` plus PB history. **[critic]** Plus `clean_lap_count` on every `repo.list_sessions` row (one `SUM(l.clean)`; `/api/sessions` and `/api/drivers/{id}/sessions` both use it) | `storage/repo.py`, `api/routes_drivers.py`, tests | Progress shows lap level and the family board only; Coaching has no trends; session rows show `12 laps` |
| **D6** | `snapshot.coach = {lap_number, picked: [...], by_corner: {...}}`: the observations the radio picks for the latest lap under the seated driver's limits (`drivers.apply_coaching_limits`). Each observation also gains `text_simple` (one idea, plain words) and `short` (≤ 48 characters, for glance use), both written by the deterministic coach from the same facts and never "brake later" on its own | New `coach/selection.py` (shared selection), `core/live.py`, `analysis/coaching.py`, and `voice/proactive.py` switched to the shared selection in the same PR | Drive shows the top observation by priority, which may differ from what the radio said |

**Lane motivation (M1-M5)** - goals, badges, streaks, recaps and the weekly digest; types in
`web-react/src/lib/endpoints/motivation.ts` mirror the Python exactly (`src/pitwall/motivation/`,
`api/routes_motivation.py`). Only goals are stored (schema v3); everything else is derived when read.

| Id | Addition | Files | UI without it |
|---|---|---|---|
| **M1** | `GET /api/sessions/{sid}/recap` -> `SessionRecap`: `things.{went_well, work_on, progress}` (`ThingItem`: `source`, `text`, `text_simple`, `evidence`, `lap_id`, `observation_key`, `goal_id`, `values`), `why_empty`, `goals_achieved`, `goals_progress`, `badges_earned`, `synthetic`, `replay`, `ended` | `motivation/recap.py`, `motivation/service.py` | Summary and Session complete keep the D6 Work on / Went well |
| **M2** | `GET/POST /api/drivers/{id}/goals`, `PATCH/DELETE .../goals/{goal_id}`, `GET .../goals/suggestions` -> `GoalsResponse`, `Goal`, `SuggestionsResponse` (409/422 bodies `{detail, code}`). `SuggestionsResponse.scope.car_class` carries the scope car's class when the game reports one (for "any {class} car"), while `car_label` stays the car's name | `motivation/goals.py`, `motivation/suggest.py`, `storage/repo.py` (table `goals`) | No goals card, no goal row on Ready |
| **M3** | `GET /api/drivers/{id}/badges?synthetic=false` -> `BadgesResponse` (`badges[]` newest first, `streaks`) | `motivation/badges.py` | No badges card or tiles |
| **M4** | `GET /api/drivers/{id}/digest?week=YYYY-MM-DD` -> `WeeklyDigest` (with `markdown`); `GET .../digest.html` the printable page | `motivation/digest.py`, `motivation/html.py` | No week card |
| **M5** | `/ws/live` message `{"type": "motivation", "data": MotivationNote}` (`kind: "goals_achieved"`, `session_id`, `lap_id`, `lap_number`, `t`, `goals[]`), sent once when the worker marks goals reached | `motivation/worker.py`, `core/runtime.py` | No `GOAL REACHED` chip |

Not needed: C's B3 (corners already carry `label` and `display_name`). Confirmed: `cues.next.corner` and
`cues.cues[].corner` are the learned corner names, the keys of `track_model.corners[].name` and `corner_text`.
Later, `GET /api/track/outline` (uncommitted `api/routes_track.py`) can draw the circuit before the first clean lap,
labelled as a shipped seed with its MIT attribution; `GET /api/track/prior` is "never braking targets" and never
feeds the Drive cue.

---

## 14. Implementation plan

### 14.1 Lanes and file ownership

**A file has exactly one owner in any phase.** Paths are under `web-react/` unless they start with `src/pitwall`.

| Lane | Owns (creates or edits) | Must not edit | Where |
|---|---|---|---|
| **S · Shell & shared plumbing** | `index.html`, `public/manifest.webmanifest`, `README.md`, `src/App.tsx`, `src/main.tsx`, `src/routes.tsx`, `src/lib/{route-parse,router,prefs,theme,cache,live,drivers,auth,store}.ts` + tests, `src/hooks/{stores,useApi}.ts`, `src/components/shell/*`, `src/components/{Brand,StatusPill,DriverSwitcher,DriverAvatar,ThemeToggle}.tsx`, `src/pages/NotFoundPage.tsx`, **every page stub at creation** (then handed over), removal of `ProSlot.tsx` / `PlaceholderPage.tsx` at the end. **[critic]** Also `package.json` / `package-lock.json` (every new dependency goes through S, including Pro `Markdown`'s peer dependencies, 10.1), `vite.config.ts`, `vitest.config.ts`, `tsconfig*.json`, the `DriverSwitcher.tsx` token fix (11 step 3), `shell/MiniRadioBar.tsx` (from A's `radio/*`) and the Drive status slot **frame** `shell/DriveStatusSlot.tsx` (kind, tone, role, the Segment, the lock hint; DV supplies its content) | Page bodies after hand-over | Here |
| **T · Tokens & UI kit** | `src/styles/{tokens,index}.css`, `scripts/contrast.mjs`, `src/components/ui/*` (TimingValue, TimingTag, TimingCell, TimingLegend, EvidenceChips, CornerTag, Glossary, Unknown, SettingValue, RangeMarker, **[critic]** CopyField), `src/lib/format.ts` (phase 0: unknown → `-`), `src/lib/skeleton.ts` (neutral sector colours) | Pages; **[critic]** call sites in other lanes' files (11 step 3: deprecated aliases instead) | Here (visual) |
| **V · Visualisation kit** | `src/components/viz/*` (LapRibbon, TrackMap, LiveTrace, chart wrappers `LapTimesChart`, `TraceChart`), `src/lib/viz/*` (pure geometry: lap fraction mapping, ribbon layout, map projection) + tests | Pages | Cloud OK for the pure parts |
| **A · Radio** | `src/lib/radio.ts` + tests, `public/mic-worklet.js`, `src/components/radio/*` (PushToTalkButton, GoLiveButton, RadioMessage, MicChip) | `web/src/lib/radio.svelte.ts` (read only, it is the reference) | Here (needs HTTPS + the AirPod) |
| **DL · Drive logic** | `src/lib/drive/*` (types, state, corner, delta, timing, cues, coach, ribbon, model) + tests, `src/test/fixtures/drive/*.json` (**[critic]** a sub-folder, so R's fixtures never collide) | `.tsx` files | **Cloud OK** |
| **DV · Drive views** | `src/pages/drive/**` (CoachPage + `coach/*`, CarPage, TrackPage, RadioPage), `src/hooks/{useDriveModel,useThrottledValue}.ts`, `src/lib/wake.ts`; deletes `pages/drive/DrivePage.tsx` once CarPage replaces it; **[critic]** the status slot's content and the lazy `SessionCompleteCard` | `src/lib/drive/*` (asks DL); `shell/DriveStatusSlot.tsx` (asks S) | Here (iPad, PS5) |
| **R · Review** | `src/pages/review/**`, `src/lib/review/*` (KPIs, plain words, density, progress derivations) + tests, `src/lib/endpoints/review.ts`, **[critic]** `src/test/fixtures/review/*.json` | Drive files; `package.json` (asks S) | Cloud first, then here |
| **X · Setup** | `src/pages/setup/**` (ConnectPage, RigPage + `rig/*` walkthrough, CarSetupPage + `car/*`), `src/lib/setup/*` (walkthrough order and progress, setup formatting) + tests, `src/lib/endpoints/{rig,carsetup,connect}.ts` | Shell | Here (rig page needs the rig) |
| **Y · Settings** | `src/pages/settings/**`, `src/lib/endpoints/settings.ts` | `src/lib/prefs.ts` (Display page calls its API; S owns it) | Cloud OK, then here |
| **B · Backend** | D1-D6 Python and tests. **One engineer, serial PRs**: `core/live.py` is touched by D1-D4 and D6 | `adapters/f1/adapter.py`, `model/telemetry.py` until the field-model work in them lands | Cloud OK |

**Stub trick.** In phase 0 lane S creates every page file listed in 12.1 as a stub (`<PageStub title=... />`) and
registers it in `routes.tsx`. After that, lanes DV, R, X and Y only fill files they own; nobody else edits
`routes.tsx` or `App.tsx`. **Interfaces first:** DL publishes `src/lib/drive/types.ts` and `model.ts` signatures,
A publishes `src/lib/radio.ts`'s public types, T publishes the `ui/*` prop types, all on day 1 of phase 0, so views can
be built against them in parallel.

### 14.2 Phases

Each phase keeps `make check` and `make web-react-check` (tsc strict + vitest) green. After each: `make web-react`,
`scripts/pitwall-service.sh restart`, and a look on the iPad at `https://…:8443/next/`.

| Phase | Lanes in parallel | Tasks | Done when |
|---|---|---|---|
| **0 · Foundations** (1-2 days) | S ∥ T ∥ DL ∥ A ∥ B | **S:** route ids and redirects (2.3-2.5) + tests, `prefs.ts`, `cache.ts` / `useApi`, the shell (rail, tab bar, app bar, area header, Segment sub-nav), page stubs, PWA meta, README (Pro is installed), **[critic]** Pro `Markdown`'s peer dependencies + `docs/licences.md`, the `DriverSwitcher.tsx` token fix. **T:** `tokens.css` (11), `contrast.mjs`, `TimingValue` / `TimingTag` / `TimingCell` / `EvidenceChips` / `Unknown`, `format.ts` unknown → `-`, neutral sectors. **DL:** `types.ts`, `state.ts`, `delta.ts`, `corner.ts`, `timing.ts` + fixtures. **A:** `radio.ts` port + tests. **B:** D4, then D6 | Every legacy hash lands on the right page (including `#/radio?token=…`); the 44 px audit passes; the phone tab bar works; contrast script passes in dark, light, night and red-green safe; fixtures reach every Drive state |
| **1 · Drive Coach** | DV ∥ V ∥ DL ∥ R ∥ X ∥ Y ∥ B | **DV:** CoachPage with every state and overlay (4.7), Ready / Session complete / No-telemetry cards, radio strip, Drive lock, wake lock. **V:** LapRibbon (first), TrackMap port, LiveTrace. **DL:** cues, coach, ribbon, model. **R:** Sessions + Summary. **X:** Car setup (not hot). **Y:** Drivers, AI engineer, System ports. **B:** D2 | Replays of the recorded Austria fixture and `pitwall simulate` reach every state; **glance test passed by each family driver on the rig** (14.5); no long task over 50 ms in 10 min of iPad Safari profiling |
| **2 · Depth** | DV ∥ R ∥ X ∥ Y ∥ B | **DV:** Car wall, Track, Radio page (**[critic]** the mini radio bar is S's file; DV only checks it on the rig). **R:** Laps, Compare, Corners, Ask. **X:** Connect; Rig walkthrough, all settings, rig check, upgrades (after the rig work lands). **Y:** Radio & voice (moved from RadioView), Display. **B:** D1 and D3 (after the adapter work lands) | A beginner can say their best lap and biggest time loss from the Summary alone; they find "what to work on" in 2 taps; the rig walkthrough can be followed from the seat |
| **3 · Progress and switch-over** | R ∥ S ∥ B | **R:** Coaching plan, Progress, family board, milestones. **B:** D5. **S:** serve `web-react` at `/` (`npm run build:root`, FastAPI static mount), keep `/next/` as an alias for a week, freeze `web/` to fixes only, remove `ProSlot` / `PlaceholderPage`, update `docs/status.md`, `docs/architecture.md`, `docs/radio-setup.md` (URLs) | Each driver's Progress answers "getting faster?" with one computed sentence; every Svelte view has a React page; old links work |

### 14.3 Hot files (check `git status` before each phase)

At the time of writing these are uncommitted: `web/src/lib/rig.ts`, `web/src/views/SetupView.svelte`,
`src/pitwall/rig/*` (incl. `rig/data/rig_pitwall.json`, `rig_research.json`), `src/pitwall/api/routes_rig.py`,
`src/pitwall/adapters/{f1,ac}/adapter.py`, `src/pitwall/model/telemetry.py`, `src/pitwall/sim/f1_stream.py`,
`docs/rig-setup.md`, plus the untracked `analysis/{brake_prior,field_model,track_geometry}.py`,
`api/routes_track.py`, `core/track_knowledge.py` and this `docs/ui/` folder. Until a file's work lands:

- lane X builds Car setup and Connect first and ports the Rig page last, against the API as committed;
- lane B leaves D1 and D3 until the adapter and telemetry changes are committed;
- the React radio store is a **port**; `web/src/lib/radio.svelte.ts` stays the reference and is not edited.

### 14.4 Here or cloud

| Work | Where | Why |
|---|---|---|
| S, T, DV, A, the rig walkthrough, phase-end checks, all acceptance | **Here** | Needs the iPad at 70 cm, the PS5, Tailscale HTTPS for the mic and wake lock, the launchd service, the rig room's light, and the uncommitted hot files |
| DL, V (pure parts), R (logic and first build), Y, B | **Cloud is fine** once the current work is committed and pushed | Self-contained and testable on recorded and synthetic data (`tests/fixtures/recorded`, `pitwall simulate`). Follow `docs/cloud-tasks.md`: own branch, PR, "Integration needed" list; never claim live evidence. Cloud CI needs the `HEROUI_AUTH_TOKEN` secret for `npm ci` (README) |

### 14.5 Acceptance on the rig

1. **Glance test.** iPad on its mount at ~70 cm, room lights as when racing. Each driver does 3 laps. From 0.5 s
   glances they can say the **next corner and whether a braking call is coming**, the **delta's sign and first
   digit**, and read the coaching point on a straight. If anyone squints, raise the Drive tokens one step or switch
   on Large.
2. **Hierarchy check (C).** Asked "what did you look at first?", drivers name the corner and cue, not the delta.
   If most name the delta, step the delta down to 132 px.
3. **States.** The recorded fixture, the synthetic demo and a live PS5 session together reach every state and
   overlay in 4.7. Nothing moves when a state changes. **[critic]** Also: Silverstone's `T10-13` Maggotts and
   Becketts and `T17-18` Club fit the hero without wrapping (long corner rule); with the radio off the braking cue
   still shows; paused, every running distance on Drive reads `-`.
4. **One message.** With D6, every coaching point the radio says on a lap equals the coach card for that corner.
5. **Honesty.** Paused, unplugged and in replay, no value appears that the snapshot does not contain; `SYNTHETIC`
   shows on every page during the demo; purple never appears without D2 (**[critic]** including the family board
   and the Progress chart's record line).
6. **Family test.** Two other drivers (a beginner and an intermediate) each open their own last session's Summary
   and explain their best lap and biggest time loss without help; the beginner follows the rig walkthrough for one
   section on their own. **[critic]**
   "Their own" works from the default view: with them in the seat, Review › Sessions opens on their sessions and
   their Summary shows beginner density even when an advanced driver is the one holding the iPad.
7. **Performance.** One hour on Coach keeps a steady frame rate on the iPad and memory flat.
8. **Radio.** The radio stays live across areas; push-to-talk works from the strip, the mini bar and the wheel.

---

## 15. What changed from v1

| Topic | v1 (base A) | v2 (base C) |
|---|---|---|
| Base direction | A, timing screen minimal (the judges' pick) | **C, coach-first (James's pick)** |
| Drive focal point | 172 px delta, the one focal number; corner and cue beside it | **Next corner + braking cue + one coaching point** are the hero; the delta is the strong secondary at 144 px |
| Drive grid | Status · delta \| corner & cue · six timing cells · lap strip | C's grid: status · hero + coach \| delta · sectors \| lap times · ribbon · **radio strip** |
| Coaching on track | Sentences only when stationary | C's coach card on track with a length rule and D6 `short` / `text_simple` |
| Radio on Drive | Pill in the status row | C's radio strip with a 56 px Hold to talk; the last cue's outcome shows there |
| Drive sub-pages | Dash · Car · Radio | **Coach · Car · Track · Radio** (C) |
| Setup | Checklist · Drivers · Connect · Rig · Car setup | **Connect · Rig · Car setup** (C); Drivers back in Settings; the rig page leads with a **glance walkthrough** |
| Settings | Display (default) · Radio & voice · AI · System | **Drivers** (default) · Radio & voice · AI engineer · Display · System (C) |
| Rail | 80 px, Drive sub-pages listed in the rail | 72 px, labelled; Drive sub-pages in the status slot's Segment (C) |
| Framework | Svelte `web/` primary, `web-react/` noted | **`web-react/` (React 19 + HeroUI v3 + HeroUI Pro)**; every element mapped to a component (10) |
| Look | Square timing cells with 6 px top bars, caps labels, 6 px panel radius | HeroUI rounded cards (24 px), pill controls, sentence-case labels; identity from the chamfered hero, tinted timing cells, condensed numerals, flag bands |
| Tokens | New `web/src/styles/tokens.css` with legacy aliases | `web-react/src/styles/tokens.css` rewritten in HeroUI variables + `--pw-*` (11) |
| Charts | uPlot | Pro charts (Recharts) in Review; custom canvas `LiveTrace` for the live trace; nothing animated on Drive |
| Kept | | D6, unknown/stale rules, status-row semantics, Drive lock, colour families and timing rule set, corner-ahead rule, evidence chips, night and red-green modes, D1-D6, rig acceptance |

---

## 16. Open questions for James

1. **Purple.** Household record (v2, from B and v1) or your own all-time best (C's original)? It is one rule in
   `lib/drive/timing.ts`; green `SB` / `PB` keeps rewarding each driver either way.
2. **Delta size.** 144 px keeps C's hero first. If the glance test shows the delta is too quiet, it can go to 156 px
   before it starts to compete with the corner label.
3. **Drive lock default:** beginner profiles only (proposed), everyone, or off?
4. **Which iPad** is on the rig? The 11" is the baseline; a mini gets compact rows and suggests Large.
5. **Spectator mode on the phone** (C's Q5): a read-only Drive (no push-to-talk, no driver switch) for whoever is
   watching?
6. **Red flag clearing.** No "red flag cleared" event is decoded today; D4 clears it on `lights_out`,
   `session_started` or `session_ended`. Confirm against a real capture.
7. **Speed and gear on Coach?** Left off (the game's HUD shows them); they are on Drive › Car.

---

## 17. Critic pass (2026-10-11)

Method: read this spec, C's proposal and both mockups; rendered `mockup.html` and `mockup-coach-first.html`
headless (Playwright Chromium, 1180 × 820 iPad frame) in every Drive state, the Review pages for an advanced and a
beginner driver, and a copy with Silverstone's `T10-13` as the next corner; checked every named component against
`web-react/node_modules/@heroui/react` 3.2.6 and `@heroui-pro/react` 1.0.0-beta.10 (exports, props, imports); checked
the data against `core/live.py`, `coach/cues.py`, `analysis/coaching.py`, `analysis/track.py`, `drivers.py`,
`storage/repo.py` and the route list. Every edit is marked **[critic]** in place.

### 17.1 Verified, no change needed

- **C is the base, not A relabelled.** Four areas and C's sub-pages; C's grid areas and reading order (hero + coach
  card left, delta right, sectors | lap times, ribbon, radio strip); radio inside Drive with Hold to talk / Go live;
  the Ready card with "Not you? Switch driver"; plain-language Review. The rendered v2 Coach screen is C's screen with
  condensed numerals. The 144 px delta is taller than C's 108 px monospace delta but covers less ink, so it does not
  take the focal point (0.2).
- **Components exist.** Every Pro name in 10.1 is a root export of 1.0.0-beta.10 (`ActionBar` … `TrendChip`,
  including `ChatSource` / `ChatSources`, `KPIGroup`, `PressableFeedback.HoldConfirm` with `duration`, `sweep`,
  `onComplete`), `KPI` and the charts are subpath-only as stated, `Segment` has `size` sm/md/lg, `Stepper` has
  `orientation` and `size`, `Sheet` has `placement` and `snapPoints`, `DataGrid` has `variant` primary/secondary and
  `rowHeight`, `ActionBar` has Prefix / Content / Suffix and `isOpen`. Every OSS name exists in 3.2.6 (`Card` variants
  default/secondary/tertiary/transparent, `Tabs` primary/secondary). Gravity UI icons named in 3.2 exist.
- **Data exists.** `observations[].priority` is in the payload (`Observation.to_dict`), corners carry `label`,
  `display_name`, `identity_tier` via `track_model_payload`, `cues` has `next`, `last.{status, reason, error_m,
  age_s}`, `timing.margin_m`, `focus`, `cues[].reason`; every endpoint in 12.4 is routed today, including
  `PATCH /api/drivers/{id}` for the Drivers sheet.

### 17.2 Changed

| # | Check | Finding | Change |
|---|---|---|---|
| 1 | Glance (2) | Silverstone's `T10-13` + "Maggotts and Becketts" wrapped the 112 px label into a second line over the approach bar (rendered); `direction: null` printed "null" in the mockup | Long corner rule (4.5, 4.1, 4.3 #2, 4.10 `layout`, 14.5 #3); mockup implements it |
| 2 | Glance (2) | Coach text could drop to 22 px on track (14.5′, under ISO 15008's 16′) | 26 px floor while moving, 3-line clamp, 22 px only when stationary (4.1, 4.3 #4, 4.5, 4.10); mockup |
| 3 | Glance (2) | Flag-band words were 20 px in the mockup (14′) for the most safety-relevant text | 26 px / 800 caps (4.1, 4.3 #1, 4.8); mockup |
| 4 | Honesty / glance | Stale froze "320 m" and "in 250 m" (dimmed) while the delta went to `-` | Every running distance shows `-` when stale (4.7 #3, 14.5 #3); mockup |
| 5 | Data (4) | `cues.muted` is `"radio off"` whenever no radio is connected, so the hero's BRAKE cue would vanish for any driver without an earpiece | `radio off` keeps the cue with a `Radio off` chip (4.3 #3, 4.5, 4.10, 13) |
| 6 | Components (3) | Pro `Markdown` needs `react-markdown`, `remark-gfm`, `remark-breaks`, `streamdown`, `marked`; Pro `CodeBlock` needs `shiki`; none is installed | S adds Markdown's peers (licences checked); `CodeBlock` replaced by a custom `CopyField` / `<pre>` (7.1, 8, 10.1, 10.5, 10.6, 14.1, 14.2) |
| 7 | Components (3) / perf | Pro `KPI` imports `AreaChart` (Recharts) at module level; the Session complete card on Drive would pull Recharts into the eager Drive bundle | `SessionCompleteCard` is lazy; build check for `recharts` in the Drive chunk (4.9, 4.11) |
| 8 | Lanes (4) | Lane T's token removal edited `DriverSwitcher.tsx` (S) and `DrivePage.tsx` (DV) in the same phase; nobody owned `package.json`; DL and R shared `src/test/fixtures/`; the mini radio bar and the status slot had two owners | Deprecated aliases until phase 3; S owns `package.json`, configs, `MiniRadioBar.tsx` and the status-slot frame (DV the content); fixtures split by lane (11 step 3, 14.1, 14.2). The phase 0 code already in `web-react/` matches this (deprecated `--color-loss` / `--color-sector-best` aliases in `tokens.css`; `MiniRadioBar.tsx` and `DriveStatusSlot.tsx` under `shell/`) |
| 9 | Data (4) | Sessions rows and Progress tiles show clean-lap counts, but `repo.list_sessions` has no clean count | D5 adds `clean_lap_count`; `12 laps` before it (6.1, 6.9, 13); mockup's "Today's data" toggle shows it |
| 10 | Honesty | The family board showed the record in purple before D2 from `stats.best_laps` (per track, any car), against 4.6 and acceptance 5 | Neutral with the word `Fastest` before D2 (6.9, 14.5 #5); mockup |
| 11 | Beginners (5) | The mockup took Review density from the **seated** driver (Alex in the seat made James's session look like a beginner's; every row opened James's session); the list opened on Everyone | Density by the viewed session's driver (6.10); list starts on the seated driver (6.1); mockup rows open their own session, with an Alex (beginner) Summary |
| 12 | Beginners (5) | `−1.20 s` "gained" reads as a loss to a beginner; red `+0.11 s` badges; eight Summary blocks; "B vs A" chart titles | Gains in words (6.3, 9.6); beginner cards without signed badges, "One thing to work on"; blocks 5-8 behind More detail; plain chart captions (6.5, 6.10); mockup |
| 13 | Spec vs mockup | Pit hero: `PIT LANE` 112 px + 144 px speed cannot share a 596 px row; mockup showed `PIT` + 132 px | `PIT` 96 px + speed 144 px in both (4.7 #6); mockup |
| 14 | Mockup data | Pit "Last" was lap 6 while the radio said lap 7; "Today's data" S1 marked SB though L4 was faster; the Laps tab coloured the slower S1 green and an invalid lap's sectors yellow; Compare ribbon labels collided ("T3T4"); Settings opened on Display | Fixed in the mockup (Settings opens on Drivers as in 2.1; ribbon label spacing rule) |

### 17.3 Left for James (no change made)

- Q1 (purple = household record or own PB) and Q2 (delta size) stay open; the ink check in 0.2 suggests 144 px does
  not compete with the hero, and acceptance 2 is the real test.
