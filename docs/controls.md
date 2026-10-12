# Controls and button mapping (Setup › Controls)

Which button on your wheel does what, for any wheel and any researched game, and which buttons Pitwall can check.
Research-only guidance: nothing here is validated on your rig until you run the live checks below.

## What it does

- **Layout**: a diagram of your wheel with Pitwall's suggested place for each function (brake bias on an encoder,
  Talk to Pitwall on a plain thumb button, and so on), one sentence of reasoning each, and lists of what can't change
  while driving and what the game doesn't have.
- **Map it**: step-by-step cards for the game's own controls screen, in the game's menu order, with the game's own
  name for each action next to Pitwall's plain label.
- **Test** (F1 25 only): press each mapped UDP Action button; Pitwall shows what F1 25 reports. **Identify** shows what
  any control sends.
- **My wheel**: start from one of 23 researched templates (or from scratch), place controls on a 14-zone grid, and
  say what each one sends where you know it.
- **Printable card** (`card.html`, A4 landscape) and plain text for sharing.
- The **radio** follows the seated driver's F1 25 layout for push-to-talk, without a restart, and answers "which
  button is brake bias?" from the saved layout.

Everything is deterministic (no LLM). Pitwall suggests where things go, never the values to use.

## The four layers

1. **Physical control** on the rim, hub or button box (`WheelControl`: a kind such as button, encoder, rotary switch,
   funky switch, D-pad, thumbstick, rocker, paddle; a zone that sets how easy it is to reach).
2. **Signal** it sends on each platform (`Signal`, per PlayStation / Xbox / PC): a pad input (Cross, L3, D-pad up), a
   game-specific input only some games read (Fanatec GSB, Logitech ★, Thrustmaster encoders), a folded input shared
   with another control (the game can't tell them apart), a PC button number, nothing, or unknown.
3. **Game binding**: the function's action assigned to a control slot (`Assignment`: `brake_bias.inc` on the left
   encoder turned clockwise; in F1 25, Talk to Pitwall on UDP Action N).
4. **What Pitwall can see**: F1 25's `BUTN` event (pad-style bits and UDP Action 1-12, spec appendix 8.9), or a
   telemetry effect (F1 25 brake bias and ERS mode), or nothing.

## Evidence words

| Letter | Shown as | Meaning |
|---|---|---|
| V | Official | stated in a maker's manual, a publisher's controls page or a platform document |
| A | Inferred | read from official figures or tables, not stated in words |
| U | Community | community, retailer or press source, or not checked |
| D | Pitwall's suggestion | Pitwall's design choice |
| H | Your entry | what you entered |
| seen | Seen by Pitwall | observed by the F1 25 button test on your rig |

An assignment's evidence is the weakest of the game's row and the wheel's signal. The app never says "validated":
only the owner's live run in the validation kit (`wheel_buttons`) is evidence for `docs/status.md`.

## What Pitwall sees, per game

| Game | Wheel buttons | Values after a change |
|---|---|---|
| F1 25 (2025 and 2026 cars) | `BUTN`: UDP Action 1-12 and pad-style bits | brake bias (`brake_bias_front_pct`), ERS mode (`ers_deploy_mode`); fuel mix and pit limiter are in EA's spec but not mapped yet; the differential comes from the setup packet (live update unverified) |
| Gran Turismo 7 | nothing | only "TCS working", no level |
| Assetto Corsa (console) | nothing | TC and ABS on and working, no levels |
| ACC, Forza, iRacing, LMU, rFactor 2, AMS2, RaceRoom, AC EVO | nothing | not read by Pitwall |

Outside F1 25, Pitwall push-to-talk is the iPad's talk button, or Space on a keyboard on a Drive page.

## Not possible while driving (from the research)

- **Ride height**: in no researched game (F1 25 and GT7 show it only in the setup; iRacing's weight jacker on some
  oval cars is the nearest thing).
- **Aero**: wing angles are a setup item everywhere. F1 25 2026 cars switch Active Aero to Straight Line Mode on the
  DRS/S Mode button, inside the zones only; other games have DRS or a rear flap on cars that have it.
- **GT7 stability (ASM) and ABS**: pause menu only (Assistance Settings), not on a button. TCS changes on the MFD.
- **F1 25 traction control and ABS**: assists set in the menu.

The page lists these under "Can't change while driving in {game}" and "Not in {game}", using the catalogue's
sentences.

## How the suggestions are made (`controls/recommend.py`)

1. The game's rows for the platform (a row with a platform note, such as Assetto Corsa's PC names, is unverified on a
   console).
2. Not on the wheel: pause-menu and menu settings, and what is set before the race. Not in the game: what it lacks.
3. The preset's functions (Beginner or Advanced, from the overlay), plus what the driver keeps ("I already have this
   on a button"). Talk to Pitwall comes first in F1 25.
4. The wheel's slots on the platform. Gear paddles, the wheel's own menu, mode and layer switches, analogue paddles
   and console system buttons stay for driving. Where the game's MFD default is the D-pad, the first D-pad is the
   MFD's. Game-specific signals are used last, with a warning; folded signals score lower and only one control per
   fold group is used; unknown signals say "check it in the game". GT DD Pro's coloured sticks are used only in GT7
   (community sources say other games can't read them; Identify can check that in F1 25).
5. Fixed by the game first (GT7 sets the GT DD Pro's coloured sticks itself), then what the driver keeps.
6. Talk to Pitwall (F1 25): a plain button whose signal is its own, thumb first, never an encoder, rotary switch,
   funky turn, gear paddle or folded signal.
7. The rest by priority: `suitability + 2 x reach x frequency + signal penalty`; ties break on the wheel's control
   order. F1 25's pit limiter shares the DRS button (the game's own default) only when no button is left.
8. What doesn't fit: "No free control left for {fn}. Use the MFD." where the game's MFD holds it.

## Storage

The SettingsStore section `"controls"` in `data/settings.json` (schema 1; no SQLite change): wheels (at most 12, 96
controls each), layouts (at most 32, 48 assignments each), the household's and each driver's choices. A missing
section means defaults; nothing is written until the first save. Every wheel and layout has a `rev`: a save with an
older `rev` gets a 409, so two iPads can't overwrite each other. A bad stored item is skipped and logged, never
hiding the rest. Bindings live per console user: drivers who share one should share a layout ("Everyone on this
console user", the default owner).

## How to test (F1 25)

1. Save a layout in Setup › Controls (keep your existing UDP Action button with "I already have this on a button").
2. Map the rest in F1 25 with Map it (Controls > your wheel's preset; groups Control Scheme, MFD Shortcuts, UDP Custom
   Actions). F1 25 may drop or swap an action that was already on a button: check its list after each change.
3. Back out to the garage or a menu (whether F1 25 sends presses while its controls screen is open is unknown), open
   Test and press each mapped button; change brake bias and ERS mode once. Wheel push-to-talk is paused while a test
   runs. An item's 60 seconds start only while F1 25 is live. Replays and generated streams show in the feed,
   labelled, and never count. A stream sent from this computer (`pitwall send`, a loopback replay, or F1 25 running
   on the same PC as Pitwall) runs the test and shows what it sees, but nothing is saved: the page says "Shown here,
   not saved", as the validation kit does for loopback streams.
4. Identify: tap a control, press it, and save what F1 25 reported as its PlayStation (or Xbox, PC) signal.
5. For evidence, run the validation kit's `wheel_buttons` item (Setup › Validation): it passes when every UDP Action
   in the seated driver's F1 25 layout reached Pitwall live during the run.

The owner's recorded PS5 captures (2026-10-10/11) contain 78 UDP Action 1 presses (push-to-talk) and pad-style bits;
the Right Stick direction bits change all the time while driving, sometimes Up and Down together, so they probably
follow the pedals (unverified): the test shows them but never reports them as "other buttons".

## API

`/api/controls` (`api/routes_controls.py`): catalogue, templates, state, wheels (create, replace, delete, export,
import, set a signal), recommendation, layouts (create, update, delete, guide, card.html, card.txt), driver choices,
the button test (start, poll, skip, stop) and the probe feed. The wire format is the dashboard's
`lib/endpoints/controls.ts` contract; the catalogue adds the diagram geometry (`diagram`) the card uses.

## Files

`src/pitwall/controls/`: `catalog.py` (research copies + overlay, validated), `model.py`, `templates.py`,
`recommend.py`, `steps.py`, `probe.py` (probe and test runner), `ptt.py`, `answer.py`, `card.py`, `service.py` (runtime
wiring), `data/` (`research_games.json` and `research_wheels.json`, byte-identical copies of
`docs/research/controls-games.json` and `controls-wheels.json`, and Pitwall's overlay `controls_pitwall.json`).
Research summary and sources: [research/controls-research.md](research/controls-research.md).
