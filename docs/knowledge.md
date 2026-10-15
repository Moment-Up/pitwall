# Technique knowledge graph

Pitwall's driving-technique knowledge lives in plain TOML files in
[`src/pitwall/knowledge/graph/`](../src/pitwall/knowledge/graph/): the phases of a corner, the techniques for each
phase, the faults Pitwall can see in telemetry, their causes, what to say about them, and where every piece comes
from. You can read and extend it without touching code; Pitwall checks every file when it loads.

This guide is for contributors (Ed included): how the graph is built, the exact schema, the canonical ids, how to add
a source, and how to check your change.

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
- No text tells a driver to **brake later, brake less, release the brake earlier or carry more speed in**. Later
  braking is praised only when the corner got faster. `constraints.toml` enforces this on every load.
- **Unknown stays unknown.** A trait Pitwall does not know (the gearbox, ABS, the driving style) satisfies no
  condition, so style-specific nodes do not apply; universal nodes, measured against the driver's own reference lap,
  still do.
- **Evidence tiers are honest.** Published or brief knowledge is never presented as validated by Pitwall.
- **Paraphrase, cite, never copy.** Every source note is in our own words.

## How it is used

`pitwall.knowledge.graph.load_graph()` reads every `*.toml` in the folder once per process, validates it and returns
a frozen `TechniqueGraph`. If anything is wrong, the app logs every problem and runs without technique knowledge
(coaching works exactly as before); the tests fail instead. `GET /api/technique/knowledge` returns the whole graph as
JSON. Annotating observations, the driver's Context, the Review screens and the AI engineer's facts build on it.

What is in it: every point of Ed's corner brief and its self-check, every row of his technique-fault checklist and
every detector in his patches (the tables in [Ed's knowledge in the graph](#eds-knowledge-in-the-graph)), the eight
coaching kinds Pitwall says today, the causes Pitwall can already tell apart from what it measures, and published
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
| `abs`, `traction_control` | true / false | the game's assists, when it reports them (F1 25 does) |
| `gearbox` | paddle_autoblip, h_pattern, auto | paddles with auto-blip for the F1 family, otherwise unknown |
| `fuel_saving` | true / false | the race strategy asks for lift and coast |
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
signal's id and notes say which one, so code that reads signals looks them up by id. A game that does not send one of the channels cannot measure the signal (GT7 sends
no lateral g; AC's steering is not mapped).

### `[[fault]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `phase` | phase id | R | |
| `status` | str | R | `live` (a coaching rule says it today), `experimental` (computed, not coached), `planned` (not computed yet), `context_only` (background, never a driver fault) |
| `relative` | str | R | `reference` (against the driver's own reference lap) or `absolute` |
| `kind` | str | R for live | the coaching kind (`analysis/coaching.py` `COACHING_KINDS`); the fault's id must equal it; only live faults have one |
| `positive` | bool | | praise (exit_gain); must match the kind |
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

A discriminator (`[[cause.discriminators]]`):

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `signal` | signal id | R | |
| `test` | str | R | the test in plain words (shown as evidence; scanned by constraints) |
| `op` | str | R | `lt`, `le`, `gt`, `ge` (with `value`), or `true` / `false` |
| `value` | float | R for lt/le/gt/ge | compared with the signal's value (deltas: below zero is less than the reference) |
| `need` | str | | `all` (default) or `any` |
| `note` | str | | e.g. which code constant the value comes from |

A cause is named only when **every `need = "all"` discriminator holds and, if it has `need = "any"` ones, at least
one of those holds**. A signal that was not measured holds nothing: a cause is never named on missing evidence.

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
and the cause was measured.

### `[[constraint]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `text` | str | R | the rule in a few words (shown in the error) |
| `forbidden` | [str] | R | regular expressions, matched case-insensitively anywhere in a text |
| `scope` | [str] | | node types whose user-facing texts are scanned; default `["advice"]` |
| `except_praise` | bool | | praise (advice for a positive fault, the positive fault) is exempt |

Scanned texts: advice `radio`, `screen`, `review`, `summary`; technique `name`, `summary`, `detail`; fault, cause,
phase, signal and condition `name` and `summary`; a cause's discriminator `test` and `note`. The patterns catch
instructions ("brake later", "braking later", "later braking", "brake less", "release the brake earlier", "carry more
speed" and their variants) and let descriptions through ("you braked 12 m earlier than on your reference lap",
"braked later, slower out"). `never_brake_less` does not scan techniques, so a progressive release can still describe
the pressure coming off as the car slows. Change a pattern only with an example each way in
`tests/unit/test_knowledge_graph.py` (`CAUGHT`, `ALLOWED`).

### `[[source]]`

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `title` | str | R | |
| `author` | str | R | credit Ed as `Ed (Pitwall tester)` |
| `note` | str | R | what we took from it, in our own words |
| `url` | str | | http(s); leave out for a book |
| `date` | str | | YYYY, YYYY-MM or YYYY-MM-DD; leave out when unknown |

### Measurements (`[[fault.measured]]`, `[[signal.noise]]`)

| Field | Type | | Notes |
| --- | --- | --- | --- |
| `metric` | str | R | e.g. "fires on corner-laps", "time-to-peak delta p90" |
| `value` | float | R | |
| `unit` | str | R | e.g. %, s, m |
| `date` | str | R | YYYY-MM-DD or YYYY-MM |
| `source` | source id | R | the measurement's source (a `recorded` one) |
| `note` | str | | the sample and caveats, e.g. "667 corner-laps of real F1 25; F1 25 reports throttle 0.10 under braking" |

## Sources and tiers

Every node has a `tier`, and **its tier must be the tier of one of its sources**, so a claim is never stronger than
its evidence:

| Tier | Means | Typical source |
| --- | --- | --- |
| `expert` | published coaching knowledge, cited; not validated by Pitwall | a book, a coaching site |
| `brief` | from Ed's brief, checklist or patches; not validated by Pitwall | `ed_corner_brief`, `ed_fault_checklist`, `ed_patches` |
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
`pitwall_patch_review`, `pitwall_signal_spread`, `pitwall_technique_review`; Ed's: `ed_corner_brief`,
`ed_fault_checklist`, `ed_patches`; the seven pages Ed cited: `speedwaymedia_vector_analysis`,
`mysimrig_telemetry_beginners`, `srt_racing_lines`, `designjudges_driver_data`, `vrs_traction_circle`,
`coilovers_data_acquisition`, `wikipedia_understeer_oversteer`; other published coaching knowledge:
`bentley_speed_secrets`, `beckman_physics_of_racing_17`, `hpa_braking_technique`, `nasa_brake_release`,
`wikipedia_trail_braking`, `wikipedia_heel_and_toe`, `wikipedia_left_foot_braking`, `wikipedia_racing_line`,
`blayze_throttle_exit`, `blayze_consistency`, `racefans_lift_and_coast`).

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
`pitwall_style_review`).

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

[[advice]]
id = "over_braking_explain"
for = "over_braking"
skill = "any"
kind = "explain"
review = "On this lap you braked more than on your reference on the way in and reached the corner slower, so its slowest point was lower too."
tier = "brief"
sources = ["ed_corner_brief"]
```

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
