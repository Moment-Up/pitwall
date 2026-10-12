# F1 25 data for the spotter (cars alongside)

Evidence tier: **recorded** (the owner's own PS5 captures, UDP format 2025). Nothing here is live-validated: no
spotter call has yet been heard in a driven race. Format 2026 (the 2026 Season Pack) is spec-implemented and
synthetic only. Method: scratch copies of `data/captures/*_udp20777.pwcap` (19 captures over 1 MB, all PS5), decoded
with the spec-checked structs (`docs/research/f1-udp-spec.md`; this note does not change it). Only Motion, Session,
LapData, Event and, for the right-vector check, the player's CarTelemetry were read: **no participant names**. The
copies were deleted afterwards. Scripts: `scripts/spotter_check.py` (scoring) and the design study's scripts (no data
in them). Two passes: the design study (12 Oct 2026, a numpy prototype) and the build lane (the same day, the
production `pitwall.spotter` engine through `scripts/spotter_check.py`).

## What the game sends

- **Every car's position, velocity and forward/right vectors at the menu send rate.** Measured 55.6-59.9 Hz at the
  60 Hz setting (the game clock steps 16.68 ms). Positions are new in every packet: 2 repeated positions in 166k
  packets of moving cars. Displacement against velocity x dt: p1 0.97 - p99 1.02 for offline AI cars, p1 0.88 - p99
  1.17 for human cars online (network extrapolation).
- **LapData arrives in the same frame as Motion, just before it** (frame skew 0 in 100% of packets), so a Motion packet
  is paired with the latest LapData reference at no cost (`FieldMotion.lap`).
- **Packets are almost never lost but arrive in bunches.** Receive-clock lateness against the game clock, above its
  running minimum: p50 2-9 ms, p90 43-75 ms, p99 88-115 ms (the PS5 -> Mac network, probably Wi-Fi). Every spotter
  duration is therefore measured on the game clock (header `sessionTime`): three packets arriving within 1 ms must not
  make a 50 ms overlap look like 1 ms.
- **The game clock** stays at 0.0 on the grid; LGOT (lights out) arrives with session time 0.0 and the race clock runs
  from there. After FLBK (flashback) Motion stops for about 1.1 s and resumes with the clock rewound.
- **The direction vectors are unit length** (|forward| 0.99994-1.0000002, |forward.right| <= 5.7e-5); the heading
  differs from the direction of travel by p50 0.4-0.8 deg, p99 3-10 deg (spins excluded).
- **`worldRightDir` is the driver's RIGHT.** Test: whether the player's velocity (and, separately, its heading) turns
  towards `worldRightDir` over 100 ms when the steering (CarTelemetry `steer`, +1 = full right per EA) is above 30%
  lock at more than 80 km/h. On the 18 real captures (the build lane's check): velocity agreement 0.87-1.0, heading
  0.88-1.0 per capture; the lowest are two Austria sessions with slides. (A 19th file, `20261010-171304`, is a
  synthetic stream that was sent over UDP: synthetic UID, zero right vectors; the spotter skips such packets.)
  `forward x right` points down (-Y) in every session, consistent with `analysis/track_geometry.py` (F1's X/Z plane
  is mirrored), so the lateral offset to the right is `d . right` and up is `right x forward`. Of the committed
  excerpts only Monza turns enough to test it (151 samples, 1.0): `tests/recorded/test_spotter_recorded.py`.
- **Car sizes on the game's track** (minimum centre separations, p0.1): side by side 1.7-2.2 m (F1), 1.8-2.0 m (F2),
  matching widths of 2.0 and 1.9 m; nose to tail 5.3-5.5 m (F1), 4.9-5.0 m (F2: the game's F2 box looks shorter than
  the real 5.28 m). The spotter's box (`spotter/dims.py`): F1 5.50 x 2.00 m, F2 5.30 x 1.90 m, F1 26 5.30 x 1.90 m
  (length estimated), per `SessionInfo.formula`, overridable in settings. A box that errs large only calls earlier
  and clears later.
- **Overlaps** (25-26 race sessions, 170 gated minutes): 267-270 episodes, 220 of 0.3 s or more; duration p10 0.15 s,
  p50 0.94 s, p90 3.5 s; relative speed at onset p50 4.7 m/s, p90 13.4, p99 27.
- **The start is where it matters most**: 5-15 s after lights out a car is alongside 45% of the time (about 12
  overlaps a minute); 15-60 s 16%; after a minute 2% (about 1 a minute).
- **Crossover bridges**: the Suzuka online race never had a car above or below the player while overlapping, so the
  3 m vertical filter is tested synthetically only.

## The spotter on these sessions (build lane, production engine)

`scripts/spotter_check.py` on the 19 scratch copies (26 race sessions with gated racing, 170.3 gated minutes; the
design study counted 25 sessions because its start gate differed). The ground truth is geometric: a side is
occupied while a racing car overlaps the player lengthwise within one lane - from the **same positions and the same
car box** as the spotter. It validates the data, the timing, the state machine, chatter and flapping, and the send
rate; it does NOT validate that the box matches the game's collision shapes or what the driver sees.

After the review fixes (12 Oct 2026, below: the spin gate, the frame's rotation, hold your line side by side):

| Send rate | Overlaps >= 1 s called | Recall (>= 0.3 s) | Precision ("car" calls) | Wrong "clear" | Flaps | Decision delay, game clock p50 / p95 | Receive clock p50 / p95 / p99 | Calls per min |
|---|---|---|---|---|---|---|---|---|
| 60 Hz (as recorded) | 121/121 | 0.955 | 0.995 (1 of 193) | 0 of 178 | 12 | 50 / 67 ms | 57 / 132 / 182 ms | 2.53 |
| 20 Hz (every 3rd packet) | 121/121 | 0.945 | 0.995 | 1 of 173 | 9 | 67 / 133 ms | 87 / 160 / 212 ms | 2.47 |
| 10 Hz (every 6th packet) | 121/121 | 0.932 | 0.995 | 1 of 166 | 8 | 133 / 184 ms | 155 / 237 / 264 ms | 2.34 |

169.3 gated minutes (1 minute less than before: the spin gate). At 60 Hz: 30 short overlaps were deliberately not
spoken (the overlap would end before the audio reaches the ear), 18 onset calls would still be heard after their
overlap ended. Calls by kind: car left 93, car right 80, three wide 20, clear left 94, clear right 76, clear all round
8, still there 37, hold your line 21. Before the fixes (the build lane): 123/123, recall 0.945, 0 wrong of 184, 2.75
calls a minute, hold your line 56.

By car type at 60 Hz (every overlap of 1 s or more called in each): F1 World 11 sessions (49/49, 0 wrong clears, the
one false onset), F2 8 sessions (45/45, 0), F1 Modern 6 (17/17, 0), and the one **online** race (Suzuka, F1 Generic,
18 human players: 12/12, 0 wrong clears, 0 false onsets).

Acceptance (spec section 12.1) at 60 Hz: overlaps >= 1 s 100% (yes), precision >= 0.99 (0.995), wrong clears <= 1 per
100 clears (0), flaps <= 10% of "car" calls (6.2%), delay p50 <= 55 / p95 <= 70 ms (50 / 67), calls per gated minute
<= 4 (2.53). At 20 Hz: overlaps >= 1 s 100% (yes), wrong clears <= 2 (1), delay p95 <= 140 ms (133). All met. These
are the engine's decisions; what the driver hears is below ("The radio, simulated").

How the parameters were tuned (design study, same ground truth): with a 0.5 m clear margin, no lateral in-line
hysteresis and no arrival hold there were 9 wrong clears; lateral hysteresis (in line: enter at 0.5 W, stay at 0.35 W)
plus the two-axis arrival hold brought it to 2; a 1.5 m lengthwise stay margin to 0, at the cost of clear lag (p50
250 -> 350 ms, p95 1.0 -> 1.3 s). Without short-overlap suppression 26 "car" calls would have been heard after the
overlap ended (18 with it), while every overlap of 1 s or more stayed called.

Committed recorded fixtures: the Austria race excerpt (3 overlaps of 0.3 s or more; the call sequence is pinned) and
`f1_25_2025_ps5_monza_race-start-spotter-excerpt.pwcap` (Monza race of 10 Oct, 25.7-58.0 s from the first packet:
lights out -2 s to +30 s; scrubbed with `scripts/scrub_capture.py`): 6 overlaps of 0.3 s or more, all called, 2 three
wide, 0 wrong clears, 0 false onsets, delay p95 62 ms (84 ms at 20 Hz).

## Review fixes (12 Oct 2026)

Two reviews of the lane (correctness on these captures; radio feel with the radio simulated and streamed at real
time). The same 19 scratch copies, deleted afterwards; scripts in the review's scratch folder (no data in them).

- **Relative speeds turn with the player.** `(v_j - v_p).r` is not how fast `lat` changes in the player's frame: the
  frame turns. Against finite differences of `lat` and `lon` over consecutive packets (76 593 samples of cars near
  the player above 60 km/h), the error was p50 0.63 / p90 3.7 / p99 7.3 m/s sideways (0.53 / 2.6 / 5.1 lengthwise);
  with the rotation term from the player's previous vectors (`spotter.geometry`) 0.02 / 0.16 / 1.2 (0.02 / 0.33 / 1.3).
  Synthetic: two cars holding a 0.2 m gap through a 100 m right-hander read as closing at 1 m/s before ("hold your
  line" fired), not now (scenario `o_corner_side_by_side`).
- **Spin gate.** 12 of 468 calls were made with the player sliding more than 30 degrees (up to 174: a race-start
  crash). Now none: the gate closed 39 times in the 26 sessions (169.3 of 170.3 gated minutes left). On the Austria
  excerpt the first "car right" moves from 83.73 s (mid-slide, 34 degrees) to 84.35 s.
- **Hold your line** was 56 of 190 onsets (29%): a third for cars that were no longer overlapping lengthwise (members
  by the 1.5 m stay margin) or only diagonally, and 12 with the gap actually opening (frame rotation). Now 21 of 193
  (11%), 3 opening (by +-50 ms finite differences, nearest car): side by side (half a car of lengthwise overlap),
  0.8 m/s for 0.15 s, gap 0.4 m. Variants measured: 0.3 m / 0.8 m/s / 0.15 s without the overlap rule 40 (21%); with
  1.5 m of overlap 26.
- **The clear when a gate closes** (slow, pit, finished): implemented and synthetic only. On these sessions it never
  happened: the review's example (191501, "slow" closing 135 ms after the side emptied) was a spin, now the spin gate.
- **Off costs nothing:** a Motion item with the spotter off is counted and dropped, 0.1 us instead of 10.8 us (Monza
  excerpt, 1930 items); on, 33.6 us median, unchanged.

### The radio, simulated

The engine's decisions run through the real `SpotterRadio` with a fake hub that plays each clip for its measured
length (car left 0.45 s, clears 0.5-0.75 s, "Three wide." 0.7 s, others 0.5-0.6 s) plus 0.2 s to start, then counts
the stretches where the driver's belief (what was heard) differs from the engine's for a second or more, within one
episode (a gate that closes forgets the episode on purpose). Before the fixes, with the 1.6 s "Three wide, you're in
the middle.": 9 stretches where the driver still believed a car that had gone (1.6-9.4 s) and 1 where a car was not
heard for 1.2 s; 9 later onsets dropped as "already heard". After (the resync, the mailbox order, a held clear said as
the sides are, a car arriving cutting "Still left."): 2 stretches of 1.05 s, none unheard, 3 onsets "already heard"
(the driver was right: the car had come back). With the old 1.6 s phrase the same logic leaves 8 stretches, at most
1.6 s. Committed as a recorded test on the Monza race-start excerpt (`tests/recorded/test_spotter_radio_recorded.py`):
the driver kept the left car 5.8 s after it had gone before, under 1 s now.

## Cost

Relative geometry for 22 cars: 8.7 us per packet in pure Python (10 us with numpy) on the M4 Max (design study). On
the ingest thread the spotter costs one `FieldMotion` object and one `SimpleQueue.put` per Motion packet:
`tests/recorded/test_ingest_budget_combined.py` measured median 2.83 / p99 33.4 us / max 0.46 ms per packet with it,
2.71 / 33.3 / 0.45 without (Austria excerpt, 13 208 packets).

## Pipeline latency and the spoken phrases (build lane, not live)

- **Live-like pipeline** (spec 12.2): a scratch server (HTTP 8925, UDP 20925, `say`, no LLM) received the Monza race
  capture over loopback UDP at 1x (`pitwall send`, the original packet timing, Wi-Fi bunching included) with a
  WebSocket radio client that reports "playback started" as soon as a clip has arrived. 14 calls: decision p50 0.2 /
  max 0.9 ms after the packet's receipt; PCM on the client queue p50 0.4 / max 1.4 ms (9 calls played at once); 4
  calls waited in the mailbox behind the clip on air (p50 0.31 s, max 0.65 s); 1 replaced there; 0 packets skipped.
  The ear (iPad Web Audio + AirPod) is not in this measurement.
- **Phrase check** (`scripts/spotter_phrases_check.py`, spec 12.3; Parakeet transcribing each trimmed clip): Kokoro
  `bm_fable`, `bm_george`, `bf_emma`, `bf_isabella`: 0 mismatches in 72 renders (both wordings). The `say` fallback:
  2 of 18 ("Car right." heard as "Alright.", "Clear left." as "Play left."): no left/right swap; at run time such a
  clip is re-rendered, then kept and shown as unverified (`voice/spotter_audio.py`). Standard clips last 0.5-1.1 s
  after trimming, except "Three wide, you're in the middle." (1.3-1.9 s), since shortened to "Three wide." (0.69 s
  with `say`, radio review), with "Cars on both sides." and "Steady, car close." for beginners and "Still left." /
  "Still right." (the side: "Still there." was ambiguous after three wide).

## Not known yet

- Whether the box matches the game's collision shapes and what the driver sees ("clear" when the mirror says clear).
- The ear latency on the iPad and AirPod (A2DP when the mic is closed, HFP when open); the spotter learns
  fire -> "playback started" from the device and adds a 50 ms output allowance.
- Format 2026; PC and Xbox (same spec); online lobbies beyond one race; ovals and multiclass.
