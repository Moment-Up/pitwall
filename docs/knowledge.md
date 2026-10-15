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
`skill_not_beginner` and `no_abs_low_downforce`: reuse them, and add a compound one when you need an "and" inside an
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
(`technique/balance.py`), `CarFrame` (`model/telemetry.py`). A signal computed somewhere else needs its class added
to `SIGNAL_CLASSES` in `graph.py`. A game that does not send one of the channels cannot measure the signal (GT7 sends
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
`sources = [...]` on the nodes that use it. The sources Ed cited for his checklist are already there, marked "not yet
reviewed": when you have read one, rewrite its note to say what the graph takes from it.

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
`gear_change_while_cornering`, `lap_scatter`, `entry_understeer_from_release`, `aero_crossover`.

**Causes:** `over_braking`, `early_turn_in`, `low_grip`, `traction_limited`, `ready_earlier`, `early_brake_release`,
`waiting_for_rotation`, `carried_too_much_speed`, `released_too_early_for_apex`.

**Phases:** `approach`, `braking`, `turn_in`, `mid_corner`, `apex`, `exit`. **Conditions:** see `conditions.toml`.
**Sources:** see `sources.toml` (Pitwall's own: `pitwall_rules`, `pitwall_coaching`, `pitwall_style_review`,
`pitwall_patch_review`; Ed's: `ed_corner_brief`, `ed_fault_checklist`, `ed_patches`; published: `bentley_speed_secrets`
and the seven Ed cited).

## An example

A fault, its cause and the cause's review-only explanation, as in the seed graph:

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
causes = ["over_braking"]
advice = ["low_min_speed_describe"]
tier = "live"
sources = ["pitwall_coaching"]

[[cause]]
id = "over_braking"
name = "Over-braking"
summary = "More braking than on the reference lap on the way in, so the car reached the corner slower than on that lap."
explains = ["low_min_speed"]
advice = ["over_braking_explain"]
tier = "brief"
sources = ["ed_corner_brief"]

[[cause.discriminators]]
signal = "brake_point_delta_m"
test = "braked at least 8 m earlier than on the reference lap"
op = "le"
value = -8.0
need = "any"

[[advice]]
id = "over_braking_explain"
for = "over_braking"
skill = "any"
kind = "explain"
review = "On this lap you braked more than on your reference on the way in and reached the corner slower, so its slowest point was lower too."
tier = "brief"
sources = ["ed_corner_brief"]
```

Ed's self-check ("an on-off-on throttle means you over-braked") becomes exactly this kind of review-only explanation,
tied to the driver's own faster laps. His suggested fix ("release the brake earlier and carry more speed") cannot be
written: the constraints reject it.

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
