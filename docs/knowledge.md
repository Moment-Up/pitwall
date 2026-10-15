# Technique knowledge graph

Pitwall's driving-technique knowledge lives in plain TOML files in
[`src/pitwall/knowledge/graph/`](../src/pitwall/knowledge/graph/): the phases of a corner, the techniques for each
phase, the faults Pitwall can see in telemetry, their causes, what to say about them, and where every piece comes
from. You can read and extend it without touching code; Pitwall checks every file when it loads.

This guide is for contributors (Ed included): how the graph is built and used, the exact schema, how to add a node and
a source, how validation works, the canonical ids, how Ed's material maps onto it, and how to check your change.

## Why a graph

Good technique depends on the driver and the car. Ed's idealised-corner brief describes braking in a straight line
and coasting to the apex; the owner's fastest F1 25 laps trail-brake into 40 of 41 braking corners and rarely coast.
Both are right for someone. So every technique, fault, cause and piece of advice says **when it applies** (conditions
over the driver's Context: skill, detected braking style, car, gearbox, assists ...) and **where it comes from** (its
evidence tier and sources). Pitwall then coaches any driver within what fits them: a beginner, a trail-braker in an
F1 car, a classic car with an H-pattern gearbox.

The rules that never bend (from [CLAUDE.md](../CLAUDE.md)):

- Coaching is deterministic. The graph is data; no LLM writes it at runtime, and the AI engineer may explain its nodes
  but never invent one.
- No text tells a driver to **brake later, brake less, release the brake earlier, carry more speed in or
  trail-brake more**. Later braking is praised only when the corner got faster, and praise may describe it, never ask
  for it. `constraints.toml` enforces this on every text it scans, every time the graph loads, and on every answer of
  the AI engineer.
- **Unknown stays unknown.** A trait Pitwall does not know (the gearbox, ABS, the driving style) satisfies no
  condition, so style-specific nodes do not apply; universal nodes, measured against the driver's own reference lap,
  still do.
- **Evidence tiers are honest.** Published or brief knowledge is never presented as validated by Pitwall, and
  real-world data (real F1 laps, other people's sim laps) is never presented as proof about a game.
- **A cause is the reason only when it was shown to be.** A cause's evidence may hold just as often on corner-laps
  without its fault. Only a cause whose base-rate check showed otherwise (`discriminates = true`,
  [Checking a cause against its base rate](#checking-a-cause-against-its-base-rate)) is said as why: on the Drive
  coach card, in any radio form and by the AI engineer. The others are what was also measured on that lap.
- **Paraphrase, cite, never copy.** Every source note is in our own words.

## How it is used

`pitwall.knowledge.graph.load_graph()` reads every `*.toml` in the folder once per process, validates it and returns a
frozen `TechniqueGraph`; the app loads it while it starts. If anything is wrong, the app logs every problem at startup
and runs without technique knowledge (coaching works exactly as before); the tests fail instead. Everything below runs
after a lap is analysed, never on the path that reads the game's telemetry, and none of it uses a language model.

1. **The driver's Context** (`knowledge/context.py`): what Pitwall knows about who drives what (the keys are in the
   [condition table](#condition)). Anything not known is None and satisfies no condition.
2. **The detected style** (`knowledge/style.py`): from the driver's clean compared laps at the track (the last 5 per
   corner live; every clean lap of a stored session), the share of braking corners braked with the wheel turned for
   10 m or more (0.6 or more is `trail`, 0.2 or less `straight_line`, in between `mixed`) and coasted for 10 m or more
   (0.5 or more `often`, 0.2 or less `rare`, in between unknown). Each needs 2 laps and 6 braking corners where it was
   measured. Braking with the wheel turned needs the steering: a game that sends none (Assetto Corsa, GT7 variant A)
   leaves the braking style unknown, never `straight_line`, while coasting (the pedals only) is still detected. With
   the F1 braking assist on, the style is kept but flagged: the screens, the AI engineer and advice chosen for the
   style say some of the braking was the game's. These thresholds are Pitwall's judgement ([H] in the code).
3. **What the game sends** (`context.channel_status`): from each adapter's declared fields, a channel is `sent`,
   `not_sent` (the adapter declares it unsupported) or `unknown`. A signal with a `not_sent` channel is unavailable;
   an unknown channel never rules anything out.
4. **Fit** (`knowledge/annotate.py` `DriverKnowledge.fit`): a technique fits when its conditions hold; a fault applies
   when its conditions hold and every one of its signals is available; a cause can be named when its conditions hold
   (`ready_earlier` only with traction control off) and its signals are available; advice fits its fault or cause,
   the driver's skill (or `any`) and braking style (when it has one). Each "no" comes with a reason in words
   (`why_not`: "Only for: H-pattern gearbox (gearbox not known)", "GT7 does not send lateral g").
5. **Every coaching point is annotated**: its `knowledge` says the fault, whether it applies (and why not), the causes
   its lap's measurements named (each with the evidence: the discriminator's `test` and the value measured, and
   `discriminates`: whether the cause's base-rate check showed it tells its fault apart) and the advice for this
   driver. A point that does not apply is never said on the radio, never on the coach card and never
   a habit, but Review shows it with the reason. The eight live faults have no conditions and every game sends their
   channels, so they apply to everyone: coaching on them is unchanged.
6. **Advice is picked per form** (radio, screen, review): advice written for the driver's braking style first, then
   for their skill, then the `any` advice. The live faults' `any` advice is today's wording, so the radio reads as
   before; a cause's advice has no radio form, so causes show on screen only. **Only a cause that tells its fault
   apart is said as the reason**: it leads the stopped coach card's evidence line and Review's Work on line, and
   reads "Why: ..." in Review › Corners and the Compare explainer. Every other measured cause is shown in Review only,
   as "Also measured on this lap: ..." (never "why" or "because"), and How corners work lists it apart ("Also measured,
   not shown to tell it apart"). The live snapshot and the coach block carry only the causes that tell their fault
   apart.
7. **The API**: `GET /api/technique/knowledge` returns the whole graph with typed edges; `?session=<id>` adds that
   session's Context, style, channels and, on every condition, signal, technique, fault, cause and advice node,
   `applies` and `why_not`. Review › Coaching's "How corners work" is built from it. The live snapshot (`/ws/live`,
   up to 20 a second) carries only what the coach card reads: the coach block's copy without the evidence sentences,
   and on each observation whether it fits and the screen line of its first cause that tells its fault apart.
8. **The AI engineer** (`knowledge/facts.py`, topic `knowledge`) gets the Context, the style and, for each fault seen
   in the session, its node, measured causes (those that tell the fault apart as causes, the others as "also measured
   on these laps, not shown to tell this fault apart, so not the reason"), the techniques for that phase that fit the
   driver (named; summaries only on the most-seen fault, to keep the prompt small) and their sources with the tier in
   words; its driver-facing sentence names only a cause that tells the fault apart. An answer that names a technique
   none of its facts is about, or one the facts list as not for this driver (heel-and-toe for a paddle-shift car), is
   rejected, and so is an answer that breaks a constraint or presents a cause the facts list as not the reason as why
   the fault happened ("because of less grip"; `ai/grounding.py`, with the technique and cause words in
   `knowledge/terms.py`): the engineer explains the graph and never invents a technique or a reason.

What is in it: every point of Ed's corner brief and its self-check, every row of his technique-fault checklist and
every detector in his patches (the tables in [Ed's knowledge in the graph](#eds-knowledge-in-the-graph)), the eight
coaching kinds Pitwall says today, the causes Pitwall can name from what it measures (with the base-rate check that
says which of them tell their fault apart), and published
coaching knowledge, each with when it fits ([How it fits each driver](#how-it-fits-each-driver)).

## Files

One file per node type, by convention (any file may hold any node tables, and every `*.toml` is loaded):

| File | Tables | What |
| --- | --- | --- |
| `phases.toml` | `[[phase]]` | the six phases of a corner, fixed ids |
| `conditions.toml` | `[[condition]]` | predicates over the driver's Context |
| `techniques.toml` | `[[technique]]` | how to drive a phase, and when it fits |
| `signals.toml` | `[[signal]]` | values Pitwall measures, and where in the code |
| `faults.toml` | `[[fault]]` | what goes wrong; the live coaching kinds and planned detectors |
| `causes.toml` | `[[cause]]` | why a fault happens, and the evidence that tells it apart |
| `advice.toml` | `[[advice]]` | what to say: radio, screen, review |
| `constraints.toml` | `[[constraint]]` | phrasings no text may use |
| `sources.toml` | `[[source]]` | where knowledge comes from |

TOML tips: a list of tables is `[[fault]]` repeated; a sub-list belongs to the table above it (`[[fault.measured]]`,
`[[cause.discriminators]]`); long texts can use `"""triple quotes"""` (line breaks become spaces); regular
expressions go in `'single quotes'` so backslashes stay as written.

## Schema

**Common fields** (every node type): `id` (snake_case: `a-z`, `0-9` and single underscores, starting with a letter;
unique across the whole graph), `name` (short title), `summary` (one plain sentence), `tier` (below), `sources` (a
list of source ids, at least one) and optional `notes` (for contributors: measurements, reasoning, today's wording;
not shown to drivers and not scanned by constraints). Unknown fields are errors, so a typo never goes unnoticed.
Exceptions: a `condition` may leave `sources` out; `advice` may leave `name` and `summary` out (they default to its
target and review); a `source` has no `sources`, and its `name` and `summary` default to its title and note.

Types below: `str`, `int`, `float`, `bool`, `[id]` (a list of ids of the given node type, default empty), `[table]`
(a list of sub-tables). **Required** fields are marked R; everything else is optional.

### `[[phase]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `order` | int | R | 1 to 6, in driving order |

Exactly these six, in this order: `approach`, `braking`, `turn_in`, `mid_corner`, `apex`, `exit`.

### `[[condition]]`

Either **atomic** (`key` + `op` + `value`) or **compound** (`all_of` or `any_of`), exactly one form.

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `key` | str | R (atomic) | a Context key, below |
| `op` | str | R (atomic) | `eq`, `ne`, `in` for keys with named values; `true`, `false` for yes/no keys |
| `value` | str or [str] | R for eq/ne/in | one value (`eq`, `ne`) or a list (`in`); none for `true`/`false` |
| `all_of` | [condition] | | every listed condition holds |
| `any_of` | [condition] | | at least one listed condition holds |

Context keys and values (`CONTEXT_VALUES` in `graph.py`):

| Key | Values | Where Pitwall gets it |
| --- | --- | --- |
| `skill` | beginner, intermediate, advanced | the seated driver's profile |
| `braking_style` | trail, straight_line, mixed | detected from the driver's own clean laps at this track |
| `coasting` | rare, often | detected the same way |
| `game` | f1, gt7, forza, ac, acc | the session |
| `car_family` | f1, f2, other | the car class |
| `downforce` | high, medium, low | high for the F1 and F2 families, otherwise unknown |
| `abs`, `traction_control` | true / false | the game's assists when it reports them: F1 25 per lap (every lap must agree), Assetto Corsa's session flags |
| `gearbox` | paddle_autoblip, h_pattern, auto | paddles with auto-blip for the F1 family; automatic when an F1 game reports gearbox assist 3; otherwise unknown |
| `fuel_saving` | true / false | the live race strategy asks for lift and coast (unknown for a stored session) |
| `wet` | true / false | the session's weather |

**Unknown never satisfies a condition**, not even `ne` or `false`: "gearbox is not h_pattern" does not hold when the
gearbox is unknown. Compound conditions may not form a cycle. `conditions.toml` already defines one condition per
value (`skill_beginner`, `braking_style_trail`, `abs_off`, `gearbox_h_pattern`, `wet`, `dry` ...), plus
`skill_not_beginner`, `no_abs_low_downforce` and `gearbox_two_pedal` (paddles or automatic: no clutch pedal): reuse
them, and add a compound one when you need an "and" inside an
"or".

### `[[technique]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `phase` | phase id | R | |
| `detail` | str | R | a short paragraph for the detailed view |
| `applies_when` | [condition] | | all must hold |
| `applies_any` | [condition] | | at least one must hold |
| `alternatives` | [technique] | | techniques that do the same job another way; list each other both ways |
| `measured_by` | [signal] | | signals that show it in telemetry |
| `measured` | [table] | | numbers measured about it (how often real or other sim drivers use it): measurement tables, below |

Neither `applies_when` nor `applies_any` means the technique applies to everyone.

### `[[signal]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `code` | str | | `ClassName.field` where it is computed, e.g. `CornerMetrics.trail_brake_m`; leave out when Pitwall does not compute it yet |
| `unit` | str | R | m, s, km/h, m/s, g, deg, rpm, fraction, ratio, count, bool |
| `channels` | [str] | R | the CarFrame inputs it needs: brake, throttle, steering, clutch, gear, rpm, speed, g_lat, g_lon, wheel_slip, yaw_rate, body_slip, position, lap_distance |
| `noise` | [table] | | measured spread: measurement tables, below |

`code` must name a real field (or property) of one of these dataclasses: `CornerMetrics`, `CornerDelta`
(`analysis/compare.py`; deltas are this lap minus the reference), `BrakingEvent` (`analysis/braking.py`),
`CornerSummary` (`core/session_analysis.py`), `CornerInputs`, `SlipEvents` (`technique/inputs.py`), `PhaseBalance`
(`technique/balance.py`), `LapCornerTechnique` (`technique/session.py`), `CarFrame` (`model/telemetry.py`). A signal
computed somewhere else needs its class added to `SIGNAL_CLASSES` in `graph.py`. Several signals may share one code
when the field holds a value per phase or per point (`PhaseBalance.slip_diff_deg` for the entry, mid-corner and exit
balance; `SlipEvents.events` for lock-ups and wheelspin; `LapCornerTechnique.line` for the track-out offset): the
signal's id and notes say which one, so code that reads signals looks them up by id (`knowledge/annotate.py`
`TECHNIQUE_READERS`; a test keeps each reader's code equal to its signal's). A few signals compare this lap with the
reference lap at the same corner although their field is one lap's (`mid_understeer_vs_ref`, `mid_slide_vs_ref`,
`exit_wheelspin_vs_ref`, `exit_slide_vs_ref`, `exit_oversteer_vs_ref`): the reader computes the reference's value too,
so a symptom the reference lap shared names no cause. A game that does not
send one of the channels cannot measure the signal (GT7 sends no lateral g; AC's steering is not mapped).

### `[[fault]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `phase` | phase id | R | |
| `status` | str | R | `live` (a coaching rule says it today), `experimental` (computed, not coached), `planned` (not computed yet), `context_only` (background, never a driver fault) |
| `relative` | str | R | `reference` (against the driver's own reference lap) or `absolute` |
| `kind` | str | R for live | the coaching kind (`analysis/coaching.py` `COACHING_KINDS`); the fault's id must equal it; only live faults have one |
| `positive` | bool | | praise (exit_gain); must match the kind, and only a praise coaching kind may set it |
| `violates` | [technique] | | the techniques this fault breaks |
| `signals` | [signal] | | a live fault's signals must all have `code` |
| `thresholds` | [str] | | dotted paths of the numeric constants its rule uses, e.g. `pitwall.analysis.coaching.MIN_SPEED_KPH` (checked; the API shows their values) |
| `applies_when`, `applies_any` | [condition] | | as for techniques |
| `causes` | [cause] | | each cause lists this fault in its `explains` |
| `advice` | [advice] | | each advice names this fault in its `for` |
| `measured` | [table] | | firing rates and spreads measured on recorded laps: measurement tables, below |

### `[[cause]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `explains` | [fault] | R | each fault lists this cause in its `causes` |
| `discriminators` | [table] | | the evidence that tells this cause apart, below |
| `advice` | [advice] | | each advice names this cause in its `for` |
| `applies_when`, `applies_any` | [condition] | | as for techniques: when the cause can be named at all (`ready_earlier`: traction control off, where "no wheelspin" means something) |
| `discriminates` | bool | | default `false`. `true` only when the base-rate check (`measured`) for every live fault it explains passes the rule below: only then is the cause said as the reason |
| `measured` | [table] | | its base-rate checks, one per fault it explains (below) |

A base-rate check (`[[cause.measured]]`; [how to record one](#checking-a-cause-against-its-base-rate)):

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `fault` | fault id | R | one of the faults the cause `explains`; one check per fault |
| `fault_laps` | int | R | corner-laps where the fault fired and the cause's evidence could be measured |
| `fault_held` | int | R | of those, the ones where the evidence held (at most `fault_laps`) |
| `other_laps` | int | R | corner-laps without the fault where the evidence could be measured |
| `other_held` | int | R | of those, the ones where the evidence held: the base rate is `other_held / other_laps` |
| `date` | str | R | YYYY-MM-DD or YYYY-MM |
| `source` | source id | R | a `recorded` source that says which laps (the sample) |
| `note` | str | | the shares, the ratio and caveats about the sample |

A discriminator (`[[cause.discriminators]]`):

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `signal` | signal id | R | |
| `test` | str | R | the test in plain words (shown as evidence; scanned by constraints) |
| `op` | str | R | `lt`, `le`, `gt`, `ge` (with `value`), or `true` / `false` |
| `value` | float | R for lt/le/gt/ge | compared with the signal's value (deltas: below zero is less than the reference) |
| `need` | str | | `all` (default) or `any` |
| `note` | str | | e.g. which code constant the value comes from |

A cause is named only when **its conditions hold, every `need = "all"` discriminator holds and, if it has
`need = "any"` ones, at least one of those holds**. A signal that was not measured holds nothing: a cause is never named
on missing evidence. Name a cause for what was measured ("Slowest point came sooner", not "Early turn-in", since
Pitwall measures no turn-in), and check it against the base rate: evidence that holds about as often on the fault's
points as on every other corner-lap does not tell a cause apart, and the cause stays `discriminates = false`.

### `[[advice]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `for` | fault or cause id | R | which lists this advice back |
| `skill` | str | R | beginner, intermediate, advanced or any |
| `kind` | str | R | `describe` (what happened), `explain` (why), `drill` (something to practise) |
| `review` | str | R | one or two plain sentences, at most 320 characters |
| `radio` | str | | at most 8 words; leave out for a review-only explanation |
| `screen` | str | | at most 48 characters (the Drive screen's glance limit) |
| `style` | str | | trail, straight_line or mixed: only for drivers with that braking style |

Advice describes what happened and what the driver's own faster laps did. There are no placeholders: the numbers stay
in the observation's own text ("T6, losing 0.31 s"). A cause's advice gets onto the radio only when it has a radio form
and the cause was measured, and only a cause with `discriminates = true` may have a radio form (the radio says a
cause only as the reason); none has one today. For each form Pitwall picks advice written for the driver's braking
style first, then for their skill, then `any`; the annotation marks which forms came from advice written for the
driver (`tailored`), and Review shows that review text under the coach's own words.

### `[[constraint]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `text` | str | R | the rule in a few words (shown in the error) |
| `forbidden` | [str] | R | regular expressions, matched case-insensitively anywhere in a text |
| `scope` | [str] | | node types whose user-facing texts are scanned; default `["advice"]` |
| `except_praise` | bool | | praise (advice for a positive fault, the positive fault) may use the words to describe what paid off, never to instruct |

Scanned texts: advice `radio`, `screen`, `review`, `summary`; technique `name`, `summary`, `detail`; fault, cause,
phase, signal and condition `name` and `summary`; a cause's discriminator `test` and `note` (contributor `notes` and
source notes are not scanned). The patterns catch instructions ("brake later", "brake 10 m later", "try braking a few
metres later", "later braking", "delay your braking", "brake less", "ease up on the brake", "release the brake
earlier", "let the brake go earlier", "carry more speed", "more speed into", "trail brake more" and their variants) and
let descriptions through ("you braked 12 m earlier than on your reference lap", "braked later, slower out", "braking
started clearly later"). In praise, an instruction is still a breach: "Braking later paid off here" may stand, "Good
exit: brake later next lap" may not. The AI engineer's answers are checked against the same patterns, where a match
after a subject or a determiner ("you're braking 9 m later than your reference", "the later braking isn't paying off")
is Pitwall's own description. Change a pattern only with an example each way in `tests/unit/test_knowledge_graph.py`
(`CAUGHT`, `ALLOWED`).

### `[[source]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `title` | str | R | |
| `author` | str | R | credit Ed as `Ed (Pitwall tester)` |
| `note` | str | R | what we took from it, in our own words |
| `url` | str | | http(s); leave out for a book |
| `date` | str | | YYYY, YYYY-MM or YYYY-MM-DD; leave out when unknown |

### Measurements (`[[fault.measured]]`, `[[signal.noise]]`, `[[technique.measured]]`)

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `metric` | str | R | e.g. "fires on corner-laps", "time-to-peak delta p90" |
| `value` | float | R | |
| `unit` | str | R | e.g. %, s, m |
| `date` | str | R | YYYY-MM-DD or YYYY-MM |
| `source` | source id | R | the measurement's source: `recorded` for Pitwall's own laps, `external` for real-world or third-party data |
| `note` | str | | the sample and caveats, e.g. "667 corner-laps of real F1 25; F1 25 reports throttle 0.10 under braking" |

A cause's measurements are its base-rate checks, with their own fields (above, under `[[cause]]`).

## Sources and tiers

Every node has a `tier`, and **its tier must be the tier of one of its sources**, so a claim is never stronger than
its evidence:

| Tier | Means | Typical source |
| --- | --- | --- |
| `expert` | published coaching knowledge, cited; not validated by Pitwall | a book, a coaching site |
| `brief` | from Ed's brief, checklist or patches; not validated by Pitwall | `ed_corner_brief`, `ed_fault_checklist`, `ed_patches` |
| `external` | real-world or third-party data (real cars, other people's sim laps) measured by Pitwall's scripts; not Pitwall's recorded laps, not evidence about a game | `openf1_2025_qualifying`, `acgym_human_laps` |
| `synthetic` | checked on generated telemetry only | a synthetic evaluation |
| `recorded` | measured by Pitwall on recorded real laps, the measurement cited | `pitwall_style_review`, `pitwall_patch_review` |
| `live` | running in Pitwall and seen working live with a real game | `pitwall_coaching` |
| `design` | Pitwall's own rule or definition, not evidence | `pitwall_rules`; only conditions, constraints and sources |

An edge (a fault's cause, an advice, an alternative ...) carries the tier and sources of the node that makes the claim:
the cause for "this fault is caused by that", the advice for "say this", otherwise the node that lists the link. A
live fault explained by a brief cause shows that link as brief.

**Adding a source:** add a `[[source]]` to `sources.toml` with a new id, the title, the author, the date if known, the
URL if any, the tier and a note saying what we took, paraphrased. Never paste text from the source. Then cite it in
`sources = [...]` on the nodes that use it. The seven pages Ed cited for his checklist were read on 2026-10-15; each
note says what the graph takes from that page, and a node cites a page only for what the page says. A Pitwall
measurement (a firing rate, a spread) cites the `recorded` source that measured it, in the node's `sources` as well as
in the measurement's `source`.

**Real-world and third-party data** (tier `external`) is kept as measurements on the techniques it is about
(`[[technique.measured]]`), never as a node's own tier: it says how real or other sim drivers drive, not what fits a
driver or what Pitwall validated. Keep derived numbers only (no raw data in the repository; respect the data's
licence and credit it in the source), aggregates only (never a participant's name, initials or per-driver rows), and
say the data's limits in the source note. Today: real 2025 F1 qualifying laps from OpenF1 (CC BY-NC-SA 4.0: trail
braking into 72 % of 58 braking zones, none clearly in a straight line; the brake is an on/off flag with no steering)
and the AssettoCorsaGym human laps (CC BY 4.0: time to peak brake marks faster drivers most consistently; within one
driver, laps with more trail braking were not faster - hence `never_trail_brake_more`).

## Adding knowledge

Any change is a small edit to one or two TOML files, then the check below. A few common cases:

**A technique** (in `techniques.toml`): give it a new id, a `name`, a one-sentence `summary` a beginner can follow, a
`detail` paragraph, its `phase`, and who it is for: `applies_when` (all must hold) and `applies_any` (one must hold),
from `conditions.toml`; nothing means everyone. If it does the same job as another technique another way, list each
in the other's `alternatives`. List the signals that show it in `measured_by`. Set `tier` and `sources` honestly: a
technique from a coaching book is `expert` with that book as its source.

```toml
[[technique]]
id = "rev_match_downshift"
name = "Rev-matched downshifts"
phase = "braking"
summary = """With a manual gearbox and a clutch, give the throttle a quick stab with each downshift under braking: the
engine speed then matches the lower gear and the driven wheels are not jolted."""
detail = """On a downshift the engine has to spin faster to match the wheels in the lower gear. ... Only for an H-pattern
gearbox with a clutch: paddle-shift cars blip by themselves, so their throttle trace never shows it."""
applies_when = ["gearbox_h_pattern"]
measured_by = ["missed_blips"]
tier = "expert"
sources = ["ed_corner_brief", "wikipedia_heel_and_toe", "pitwall_patch_review"]
```

(shortened from the graph). Its notes say why the condition is there: on real F1 25 laps 69 % of downshifts have no
driver throttle near them, because the game blips on paddle downshifts, so the check means nothing with paddles, and
an unknown gearbox does not count as an H-pattern one.

**A condition** (in `conditions.toml`): only when the existing ones cannot say it. An "and" inside an "or" is a
compound condition (`all_of` / `any_of` naming other conditions), as `no_abs_low_downforce` does. A new Context key
or value is a code change (`CONTEXT_VALUES` in `graph.py` and where `knowledge/context.py` reads it).

**A fault** (in `faults.toml`): a new detector Pitwall does not compute yet is `status = "planned"`; one it computes
but does not coach is `experimental`. Name the techniques it breaks (`violates`), its signals (add any missing ones
to `signals.toml`, without `code` until Pitwall computes them), its conditions, and any firing rates measured on
recorded laps (`[[fault.measured]]`, citing the `recorded` source that measured them). Only code makes a fault `live`:
a coaching rule in `analysis/coaching.py`, its kind in `COACHING_KINDS`, and the fault's id equal to that kind.

**A cause** (in `causes.toml`): list the faults it explains in `explains` and add the cause to each fault's
`causes`. Give it discriminators that read computed signals only, each with its plain-words `test`: the cause is
named on a lap only when they hold on that lap's measurements. Prefer evidence relative to the reference lap: a
symptom both laps had does not explain why this lap was slower. Then run its base-rate check
([Checking a cause against its base rate](#checking-a-cause-against-its-base-rate)): until it passes, `discriminates`
stays false (the default), and the cause is shown only as also measured, never as why.

**Advice** (in `advice.toml`): `for` names the fault or cause, which lists the advice back in its `advice`. Write the
`review` (at most 320 characters) and, if it belongs on a screen or the radio, `screen` (48 characters) and `radio`
(8 words). Describe what happened against the driver's own reference lap; never instruct a later or lighter brake, an
earlier release or more speed (the constraints reject it). Add a `skill = "beginner"` variant in plain words, and a
`style` variant when the explanation differs for a braking style.

**A source**: see [Sources and tiers](#sources-and-tiers). Read the source first, paraphrase what you take, and cite
it only on nodes it supports.

### Checking a cause against its base rate

A cause's evidence can hold just as often on corner-laps without its fault: then it describes what was measured,
not why the fault happened. Check every cause before it may be said as the reason, and again when its
discriminators, a coaching threshold or the fault's rule change:

1. Run the check over recorded captures (real laps only; it refuses a synthetic capture):

   ```bash
   uv run python scripts/cause_base_rates.py data/captures/*.pwcap --date 2026-10-15
   ```

   Each capture is replayed into a scratch database in a temporary folder and analysed as Review does (every lap
   against its session's reference). For every cause and every live fault it explains, on the non-incident corner-laps
   of usable comparisons where the cause's evidence could be measured (every `need = "all"` signal measured and, with
   `need = "any"` ones, one of those), it counts the corner-laps where the fault fired and where the evidence held
   there, and the same for the corner-laps without the fault (the base rate). A corner-lap where the evidence could
   not be measured counts for neither. It prints a table (with how often the cause was named and whether the check
   passes the rule below) and the `[[cause.measured]]` blocks.
2. Paste each block under its cause in `causes.toml`, cite a `recorded` source that says which captures (add one to
   `sources.toml` for a new sample), and write the shares and caveats in `note`. Keep one check per fault: replace
   the old one (git keeps the history).
3. Set `discriminates = true` only when the check passes for every live fault the cause explains. **The rule** (`[H]`,
   `graph.DISCRIMINATES_RATIO` and the minimum counts): the evidence held on at least **twice** as large a share of
   the fault's corner-laps as of the other corner-laps, on at least **10** of the fault's corner-laps, with at least
   **30** other corner-laps measured. Below about twice the base rate the evidence changes the odds that it explains
   the point only a little. The validator rejects `discriminates = true` without a passing check, and a cause advice
   with a radio form on a cause that does not discriminate.

A cause whose faults are not coached yet (`released_too_early_for_apex`: `stepped_throttle` is planned) has nothing to
check against and never discriminates. A cause with conditions that never held in the sample (`ready_earlier` needs
traction control off) can be checked for its evidence, but say so in the note and check it again on laps where it
can be named.

## How validation works

`load_graph()` checks the whole graph when Pitwall starts (the app loads it at startup) and reports **every** problem
at once, each with its file, node and field; the tests run the same checks, so a broken graph never reaches a
release:

- **Shape:** ids are snake_case and unique across the graph; required fields are present; unknown fields and tables
  are errors; texts and lists have the right types; TOML syntax errors name the file and line.
- **References:** every id a node lists exists and is of the right type (a technique's `phase` is a phase, a fault's
  `causes` are causes ...); there are exactly the six phases, in order.
- **Two-way links agree:** a fault's `causes` and each cause's `explains`; a node's `advice` and each advice's `for`;
  `alternatives` both ways (never itself).
- **Conditions:** keys and values come from the Context vocabulary (`CONTEXT_VALUES`); `true` / `false` keys take no
  value; compound conditions have no cycle.
- **Signals and code:** a signal's `code` names a real field or property of one of `SIGNAL_CLASSES`; its channels and
  unit are known; a live fault's signals are all computed; `thresholds` name real numeric constants (the API shows
  their values).
- **Faults:** `kind` is set exactly when `status` is live, is a real coaching kind and equals the id; `positive`
  matches the praise kinds and only a praise kind is positive; the canonical ids have the right types
  (`missing_canonical()`).
- **Advice limits:** radio at most 8 words, screen at most 48 characters, review at most 320.
- **Base-rate checks:** each names a fault the cause explains, once; counts are whole numbers with the held counts no
  larger than their corner-laps; the source is a `recorded` one; `discriminates = true` needs a passing check for
  every live fault the cause explains (and at least one live fault); a cause advice with a radio form needs
  `discriminates = true`.
- **Tiers:** a node's tier is the tier of at least one of its sources (`design` only on conditions, constraints and
  sources), so no claim is stronger than its evidence.
- **Constraints:** every user-facing text of the node types in a constraint's `scope` passes every forbidden pattern
  (praise may describe, never instruct, where `except_praise` says so).

At runtime a graph that fails is logged with its problems and Pitwall runs without technique knowledge: coaching,
the radio and the dashboard work as they did before the graph, and `GET /api/technique/knowledge` answers 503 with the
list. The tests make it strict instead (`set_strict(True)` in `tests/conftest.py`), and further tests check the
content: the coverage tables below against the graph, the sample drivers' fits, every advice string against the
constraints with examples each way, and the signal readers against the real dataclasses.

## Canonical ids

The graph's content is written against these ids (`CANONICAL_*` in `graph.py`). A node with one of them must have the
listed type; `missing_canonical()` lists those still to write.

**Techniques:** `flat_to_brake_marker`, `fast_brake_attack`, `progressive_brake_release`, `rev_match_downshift`,
`straight_line_braking`, `trail_braking`, `release_with_speed_to_spare`, `single_smooth_turn_in`, `coast_to_apex`,
`throttle_at_rotation`, `commit_throttle_no_lift`, `unwind_with_throttle`, `use_track_width_exit`,
`consistent_brake_marker`, `left_foot_braking`, `fuel_save_lift_and_coast`.

**Faults, live** (the coaching kinds; `status = "live"`, `kind` = id): `brake_early`, `brake_late_overdrive`,
`overspeed_apex`, `low_min_speed`, `late_throttle`, `coasting`, `exit_gain` (praise: `positive = true`), `incident`.

**Faults, planned or experimental** (not live): `double_hump`, `slow_brake_attack`, `abrupt_brake_release`,
`pedal_overlap`, `lift_before_braking`, `steering_sawing`, `snatched_turn_in`, `early_apex`, `throttle_sawtooth`,
`stepped_throttle`, `low_throttle_acceptance`, `throttle_before_unwind`, `unused_grip_exit`, `missed_blip`,
`gear_change_while_cornering`, `lap_scatter`, `entry_understeer_from_release`, `aero_crossover`, and four that give
a checklist row or brief point a node of its own: `brake_lockup`, `exit_wheelspin`, `balance_symptom`,
`unused_track_exit`.

**Causes:** `over_braking`, `early_turn_in`, `low_grip`, `traction_limited`, `ready_earlier`, `early_brake_release`,
`waiting_for_rotation`, `carried_too_much_speed`, `released_too_early_for_apex`.

**Phases:** `approach`, `braking`, `turn_in`, `mid_corner`, `apex`, `exit`. **Conditions:** see `conditions.toml`.
**Sources:** see `sources.toml` (Pitwall's own: `pitwall_rules`, `pitwall_coaching`, `pitwall_style_review`,
`pitwall_patch_review`, `pitwall_signal_spread`, `pitwall_cause_base_rate`, `pitwall_technique_review`; Ed's: `ed_corner_brief`,
`ed_fault_checklist`, `ed_patches`; the seven pages Ed cited: `speedwaymedia_vector_analysis`,
`mysimrig_telemetry_beginners`, `srt_racing_lines`, `designjudges_driver_data`, `vrs_traction_circle`,
`coilovers_data_acquisition`, `wikipedia_understeer_oversteer`; other published coaching knowledge:
`bentley_speed_secrets`, `beckman_physics_of_racing_17`, `hpa_braking_technique`, `nasa_brake_release`,
`wikipedia_trail_braking`, `wikipedia_heel_and_toe`, `wikipedia_left_foot_braking`, `wikipedia_racing_line`,
`blayze_throttle_exit`, `blayze_consistency`, `racefans_lift_and_coast`; real-world and third-party data:
`openf1_2025_qualifying`, `acgym_human_laps`).

## How it fits each driver

Nine techniques have no conditions and fit everyone, judged against the driver's own reference lap:
`flat_to_brake_marker`, `fast_brake_attack`, `progressive_brake_release`, `consistent_brake_marker`,
`single_smooth_turn_in`, `throttle_at_rotation`, `commit_throttle_no_lift`, `unwind_with_throttle` and
`use_track_width_exit`. The eight live faults have no conditions either, so coaching on them is the same for every
driver. The rest fit only when the driver's Context says so, and an unknown trait fits nothing:

| Driver (what Pitwall knows) | Style-specific techniques that fit | Conditional faults that apply |
| --- | --- | --- |
| Nothing known yet | none | none |
| The owner: F1 25, detected trail-braking, F1 car (high downforce, paddles with auto-blip) | `trail_braking`, `left_foot_braking` | `aero_crossover` (background); `brake_lockup` too when the game reports ABS off |
| A beginner in GT7, nothing else known | `straight_line_braking`, `release_with_speed_to_spare`, `coast_to_apex` | none |
| A classic car: H-pattern gearbox, no ABS, low downforce | `rev_match_downshift`, `straight_line_braking`, `release_with_speed_to_spare`, `coast_to_apex` | `missed_blip`, `gear_change_while_cornering`, `brake_lockup` |
| An F1 race saving fuel, mixed braking style | `fuel_save_lift_and_coast`, `trail_braking`, `left_foot_braking` | `aero_crossover` (background) |

On the owner's recorded sessions the gearbox actually reads automatic (they drive with F1 25's gearbox assist 3) and
the braking assist is on: the fits are the same (both gearboxes are two-pedal), and the detected style carries the
braking-assist note ([status.md](status.md#technique-knowledge-graph-unreleased) has every session's Context and style).

Trail braking and the straight-line style (`straight_line_braking`, `release_with_speed_to_spare`, `coast_to_apex`)
are each other's alternatives; `flat_to_brake_marker` and `fuel_save_lift_and_coast` too. The same drivers are checked
in `tests/unit/test_knowledge_graph.py`.

## Ed's knowledge in the graph

Every point of Ed's corner brief, every row of his checklist and every detector in his patches has at least one node.
Each id below is tagged with its type, or for a fault with its status (`live`: coached today; `experimental`:
computed, not coached; `planned`: not computed yet; `context_only`: background). Firing rates are from Pitwall's
reviews of the owner's real F1 25 laps (667 to 681 corner-laps). `tests/unit/test_knowledge_graph.py` checks every
id, type and status in these three tables against the graph, so they cannot drift.

### The corner brief (2026-10-14)

<!-- coverage:brief -->
| # | Ed's point (paraphrased) | Graph nodes | Fits |
| --- | --- | --- | --- |
| 1 | Flat out to the braking point; no early lift | `flat_to_brake_marker` (technique), `fuel_save_lift_and_coast` (technique), `lift_before_braking` (planned), `brake_early` (live) | everyone; a lift is intended when the strategy saves fuel |
| 2 | Peak brake pressure almost at once | `fast_brake_attack` (technique), `slow_brake_attack` (experimental) | everyone |
| 3 | Bleed the pressure off as the car slows | `progressive_brake_release` (technique), `abrupt_brake_release` (experimental), `double_hump` (planned), `brake_lockup` (experimental), `entry_understeer_from_release` (planned) | everyone; lock-ups with ABS off |
| 4 | Blip the throttle on each downshift under braking | `rev_match_downshift` (technique), `missed_blip` (planned), `gear_change_while_cornering` (planned), `missed_blips` (signal) | H-pattern gearbox only: with paddles the game blips |
| 5 | Wheel straight while braking; off the brake before turning | `straight_line_braking` (technique), `trail_braking` (technique), `trail_brake_m` (signal), `brake_at_turn_in` (signal) | beginners, straight-line brakers, no ABS with low downforce; trail braking for trail brakers and high downforce |
| 6 | Off the brake with speed to spare, on purpose | `release_with_speed_to_spare` (technique), `low_min_speed` (live), `over_braking` (cause) | as point 5 |
| 7 | One smooth turn-in, then hold it; no sawing | `single_smooth_turn_in` (technique), `snatched_turn_in` (planned), `steering_sawing` (planned) | everyone |
| 8 | Off both pedals to the apex; cornering scrubs the speed | `coast_to_apex` (technique), `coasting` (live), `early_brake_release` (cause) | as point 5 (tier brief: the owner's laps go against it) |
| 9 | Throttle once the car has rotated, one smooth squeeze | `throttle_at_rotation` (technique), `late_throttle` (live), `waiting_for_rotation` (cause), `exit_wheelspin` (experimental) | everyone |
| 10 | No lift once on the throttle; a lift points to over-braking or an early turn-in | `commit_throttle_no_lift` (technique), `stepped_throttle` (planned), `throttle_sawtooth` (experimental), `over_braking` (cause), `early_turn_in` (cause) | everyone |
| 11 | Unwind the steering as the throttle goes on | `unwind_with_throttle` (technique), `throttle_before_unwind` (planned), `low_throttle_acceptance` (planned) | everyone |
| 12 | Change up as normal; use all the track on exit | `use_track_width_exit` (technique), `unused_track_exit` (experimental), `early_apex` (planned) | everyone |
| Self-check | An on-off-on throttle means over-braking | `stepped_throttle` (planned), `released_too_early_for_apex` (cause), `over_braking` (cause) | review only, never on the radio; tied to the driver's own reference lap |
<!-- /coverage:brief -->

The owner's measurements against points 5 and 8 (trail braking into 40 of 41 braking corners; more coasting slower in
22 of 35 corners) are on `trail_braking`, `straight_line_braking` and `coast_to_apex` (source
`pitwall_style_review`). Real-world data says the same of real F1 cars: none of 58 braking zones of the 2025 Austrian
and Japanese qualifying laps was clearly braked in a straight line (`openf1_2025_qualifying`, tier external, on
`trail_braking` and `straight_line_braking`). Point 6 is tier brief: no published source in the graph backs a full
release before turn-in.

### The technique-fault checklist (2026-10-13)

<!-- coverage:checklist -->
| Trace | Row (paraphrased) | Graph nodes | Pitwall today (Ed's status, then the review) |
| --- | --- | --- | --- |
| Brake | Double hump: pressure dips, then a second peak | `double_hump` (planned), `brake_reapplied` (signal) | Ed: not covered; half right (close stabs merge into one event). Ed's detector 11.7% |
| Brake | Slow ramp-up to peak | `slow_brake_attack` (experimental), `time_to_peak_s` (signal) | Ed: not covered; the attack time is measured after the session. His rule 19%; 68% of corner-laps are 0.05 s or more off the reference |
| Brake | Abrupt or stepped release | `abrupt_brake_release` (experimental), `release_time_delta_s` (signal) | built, descriptive, after the session. His rule 17%; 77% of corner-laps 0.05 s or more off |
| Brake | Brake and throttle together by accident | `pedal_overlap` (planned), `left_foot_braking` (technique) | partly (lock-up gating only). Ed's detector 66.8%: F1 25 reports 0.10 throttle under braking |
| Brake | Released too early for the apex | `released_too_early_for_apex` (cause), `stepped_throttle` (planned) | his throttle modulation; review-only explanation |
| Throttle | Sawtooth: on, off, on | `throttle_sawtooth` (experimental), `throttle_lifts` (signal) | Ed: not covered; counted after the session (a technique note and a habit) |
| Throttle | Throttle acceptance: lateral g at full throttle over the corner's peak | `low_throttle_acceptance` (planned), `throttle_acceptance` (signal) | not covered. Ed's detector 6.0%, wording inverted |
| Throttle | Throttle before the steering unwinds | `throttle_before_unwind` (planned) | not covered |
| Throttle | Over-cautious exit: full throttle late with grip to spare | `late_throttle` (live), `ready_earlier` (cause), `traction_limited` (cause) | partly: the causes tell no grip from grip left unused (F1 25: tyre slip) |
| Steering | Sawing mid-corner | `steering_sawing` (planned), `steering_reversals` (signal) | not covered. Ed's detector 22.6%, 3 to 5 reversals per corner on clean laps |
| Steering | Snatched turn-in | `snatched_turn_in` (planned), `turn_in_steer_time_s` (signal) | not covered |
| Steering | Early apex, then a second correction | `early_apex` (planned), `early_turn_in` (cause) | partly (the line measures offset, not apex timing). Ed's detector 32.6%, argmax jumps |
| Steering | Mid-corner unwind rate | `steering_unwind_s` (signal), `throttle_before_unwind` (planned) | not covered |
| Combined | Unused grip on the G-G diagram | `unused_grip_exit` (planned), `exit_grip_utilization_frac` (signal) | no G-G diagram. Ed's detector 9.5% |
| Combined | Driver or car: understeer and oversteer | `balance_symptom` (experimental), `low_grip` (cause) | built (F1 25 only), shown on the Technique page |
| Combined | Entry understeer from the release shape | `entry_understeer_from_release` (planned) | partly: the with-braking flag only |
| Consistency | Lap-to-lap scatter at one corner | `lap_scatter` (experimental), `consistent_brake_marker` (technique) | after the session, not live |
| Consistency | Coasting | `coasting` (live), `coast_to_apex` (technique), `trail_braking` (technique) | built and coached; explained by braking style |
| Consistency | Lift and coast before the braking zone | `lift_before_braking` (planned), `fuel_save_lift_and_coast` (technique) | not covered. Ed's detector 23.2%, inflated by a scan bug |
| Consistency | Lock-ups and wheelspin | `brake_lockup` (experimental), `exit_wheelspin` (experimental) | built (F1 25 only): per corner, and per lap by car health |
| Consistency | Gear change while cornering | `gear_change_while_cornering` (planned) | not covered; his patch's check fires on nearly every corner. H-pattern only (Pitwall's judgement) |
| Car | Aero crossover: lateral g against speed | `aero_crossover` (context_only), `aero_crossover_kph` (signal) | his fit, not wired; describes the car, not the driver |
<!-- /coverage:checklist -->

His suggested next steps: a G-G diagram (`unused_grip_exit`; Compare gains his g-force charts), sawtooth detection
(`throttle_sawtooth`) and lap-to-lap scatter as a signal of its own (`brake_point_std_m`, `min_speed_std_kph`).

### The patches (read as data, not applied)

<!-- coverage:patches -->
| Patch | Detector | Graph nodes |
| --- | --- | --- |
| technique faults | double hump | `double_hump` (planned), `brake_reapplied` (signal) |
| technique faults | pedal overlap | `pedal_overlap` (planned), `pedal_overlap_m` (signal) |
| technique faults | pre-brake coast (lift before braking) | `lift_before_braking` (planned), `pre_brake_coast_m` (signal) |
| technique faults | throttle dip after pick-up (throttle modulation) | `stepped_throttle` (planned), `throttle_dip_after_pickup` (signal) |
| technique faults | throttle acceptance | `low_throttle_acceptance` (planned), `throttle_acceptance_delta` (signal) |
| technique faults | steering reversals | `steering_sawing` (planned), `steering_reversals` (signal) |
| technique faults | steering peak offset (early apex) | `early_apex` (planned), `steering_peak_offset_delta_m` (signal) |
| technique faults | gear change while turning | `gear_change_while_cornering` (planned), `gear_change_while_turning` (signal) |
| technique faults | exit grip utilisation | `unused_grip_exit` (planned), `exit_grip_utilization_frac` (signal) |
| technique faults | aero crossover fit | `aero_crossover` (context_only), `aero_crossover_kph` (signal) |
| root cause and overlay | slow brake attack | `slow_brake_attack` (experimental), `time_to_peak_delta_s` (signal) |
| root cause and overlay | abrupt brake release | `abrupt_brake_release` (experimental), `release_time_delta_s` (signal) |
| root cause and overlay | throttle modulation root cause | `over_braking` (cause), `early_turn_in` (cause) |
| root cause and overlay | downshifts and missed blips | `missed_blip` (planned), `downshifts` (signal), `missed_blips` (signal) |
| root cause and overlay | Compare g-force charts | none: a screen (Review › Session › Compare), not knowledge |
| body slip and cadence | ACC fixes; a trend gate | none: adapter work, and the habit tracker replaces the trend gate |
| ACC adapter | ACC shared memory | none: a game adapter, separate work |
<!-- /coverage:patches -->

## An example

A live fault, one of its causes and the cause's review-only explanation, shortened from the graph (notes and the
other causes' nodes left out):

```toml
[[fault]]
id = "low_min_speed"
kind = "low_min_speed"
status = "live"
name = "Low minimum speed"
summary = "The slowest point of the corner was clearly slower than on the reference lap, and the corner cost time."
phase = "apex"
relative = "reference"
signals = ["min_speed_delta_kph"]
thresholds = ["pitwall.analysis.coaching.MIN_SPEED_KPH", "pitwall.analysis.coaching.MIN_TIME_LOSS_S"]
violates = ["release_with_speed_to_spare"]
causes = ["over_braking", "early_turn_in", "low_grip"]
advice = ["low_min_speed_describe", "low_min_speed_describe_beginner"]
tier = "live"
sources = ["pitwall_coaching"]

[[fault.measured]]
metric = "fires on corner-laps"
value = 41.7
unit = "%"
date = "2026-10-15"
source = "pitwall_signal_spread"

[[cause]]
id = "over_braking"
name = "Over-braking"
summary = "More braking than on the reference lap on the way in, so the car reached the corner slower than on that lap."
explains = ["low_min_speed", "stepped_throttle"]
advice = ["over_braking_explain", "over_braking_explain_beginner"]
tier = "brief"
sources = ["ed_corner_brief"]
discriminates = false

[[cause.discriminators]]
signal = "brake_point_delta_m"
test = "braked at least 8 m earlier than on the reference lap"
op = "le"
value = -8.0
need = "any"

[[cause.discriminators]]
signal = "entry_speed_delta_kph"
test = "at least 4 km/h slower at the corner entry than on the reference lap"
op = "le"
value = -4.0

[[cause.measured]]
fault = "low_min_speed"
fault_laps = 387
fault_held = 69
other_laps = 485
other_held = 71
date = "2026-10-15"
source = "pitwall_cause_base_rate"

[[advice]]
id = "over_braking_explain"
for = "over_braking"
skill = "any"
kind = "explain"
screen = "Braked earlier, reached the corner slower"
review = "On this lap you braked more than on your reference on the way in and reached the corner slower, so its slowest point was lower too."
tier = "brief"
sources = ["ed_corner_brief"]
```

On a lap where the driver braked 9.6 m earlier and reached the corner 18 km/h slower than on the reference lap, the
low minimum speed point carries the cause `over_braking` with both tests as its evidence. Its base-rate check found
that evidence on 18% of the owner's low minimum speed corner-laps and on 15% of the others (1.22 times the base rate,
below the rule's twice): it does not tell the fault apart, so the stopped coach card adds no cause line, Review reads
"Also measured on this lap: Braked earlier, reached the corner slower." with the evidence, the AI engineer lists it
as also measured and may not say the point happened because of it, and the radio says the point exactly as before.
The coasting cause `early_brake_release` passed its check (43% against 20%, 2.19 times): on its points the card's
evidence line leads with "Braking ended sooner, longer roll after" and Review reads "Why: ...".

Ed's self-check ("an on-off-on throttle means you over-braked") is the same kind of review-only explanation: the cause
`released_too_early_for_apex` (with `over_braking`) on the planned fault `stepped_throttle`, whose advice has no radio
or screen form and says only what was measured against the driver's own reference lap. His suggested fix ("release
the brake earlier and carry more speed") cannot be written: the constraints reject it.

## Checking a change

```bash
uv run pytest tests/unit/test_knowledge_graph.py tests/unit/test_knowledge_api.py -q
```

A broken graph lists every problem with its file, node and field, for example:

```
faults.toml: fault 'low_min_speed': causes: unknown id 'nope'
advice.toml: advice 'say': radio: 'Try braking later here' breaks constraint 'no_later' (...)
techniques.toml: technique 'tb': tier 'recorded' needs a source of that tier (its sources are expert)
```

Then run `make check` before committing, as for any change.
