# Recorded real-game captures

Put **real** game captures (`.pwcap`) here to enable the *recorded validation* tier
(`tests/recorded`). Pitwall records every live session automatically to `data/captures/`;
copy a capture here once you have checked it is genuine game output (not a synthetic stream).

Naming: `<game>_<format>_<platform>_<track>_<description>.pwcap`, e.g.
`f1_25_2025_ps5_spa_practice-5laps.pwcap`.

Licensing: only commit captures you recorded yourself. Third-party captures found online
(e.g. in unlicensed GitHub repositories) must not be added - see docs/licences.md.

Privacy: real captures carry player names. F1 25 sends every participant's online ID or name (Participants,
Lobby Info); Assetto Corsa sends yours (handshake reply, RTLap). Gran Turismo 7 sends no names: the script checks
that its only text fields (variant C surface letters and car category) hold the documented values. Before
committing, run `uv run python scripts/scrub_capture.py tests/fixtures/recorded/<file>.pwcap`: it rewrites only those
name fields (F1: the player's car becomes `Player`, every other car `Driver NN`; AC: `Player`) and LAN addresses in
the capture metadata (to 127.0.0.1), keeps every packet length, timestamp and all other bytes, checks that no
original name is left, and notes the scrub in the capture's description. `scripts/scrub_capture.py --check <files>`
only checks (exit 1 if a name or LAN address is left); `scripts/package_release.py` runs it on every capture in a
release.

Committed captures (each a byte-for-byte excerpt of the maintainer's own PS5 sessions, see
`scripts/excerpt_capture.py`, with the name fields then replaced by `scripts/scrub_capture.py`):
- `f1_25_2025_ps5_austria_race-excerpt.pwcap`: F1 25 v1.26, Austria race - standing start, lap changes, finish
- `f1_25_2025_ps5_monza_race-excerpt.pwcap`: F1 25, Monza race lap 3, 560-2250 m (T1-2, T4-5) - every packet
  unchanged apart from the participant names
- `f1_25_2025_ps5_melbourne_race-start-excerpt.pwcap`: F1 25, Melbourne 3-lap race - the grid 164 m behind the
  timing line (negative lap distance), lights out, lap 1->2 and lap 2->3 (lap numbering, standing start)
- `f1_25_2025_ps5_imola_race-pitstop-excerpt.pwcap`: F1 25, Imola race pit stop - lap 14 pit entry (4810 m) and the
  line crossed in the pit lane, lap 15 leaving the pit lane (exit 449 m), lap 15->16 (in-lap / out-lap flags)
- `f1_25_2025_ps5_jeddah-f2_race-pitstop-coldtyres-excerpt.pwcap`: F1 25 v1.26, F2 Jeddah race (2026-10-11,
  20261011-224147, session ...314818, carcass tyre model): the start, the lap-1 baseline, the lap-1 pit stop - the
  tyre change in the box (tyre age 1 -> 0, carcass 28 C against 88 C) and the exit on new tyres -, warm again on lap 3:
  car health's cold-tyre call, said in the box (1.54 MB). Only the Session, LapData, Event, CarTelemetry and CarStatus
  packets of the windows (`excerpt_capture.py --f1-packet-id`), each unchanged
- `f1_25_2025_ps5_bahrain-f2_race-lockups-abs-off-excerpt.pwcap`: the same capture's F2 Bahrain race (session
  ...752346, ABS off), lap 2: five lock-ups, wheels fully locked (slip -1.0) - car health's lock-up counts (1.52 MB).
  Only the Session, LapData, CarTelemetry, CarStatus and MotionEx packets of the windows, each unchanged
- `f1_25_2025_ps5_monza_race-start-spotter-excerpt.pwcap`: F1 25, Monza race of 2026-10-10 (20261010-204720,
  25.7-58.0 s from the first packet: lights out -2 s to +30 s) - the spotter's busiest moment: 6 overlaps of 0.3 s or
  more, two of them three wide (3.29 MB; `tests/recorded/test_spotter_recorded.py`)
- `ac_ps5_ks_silverstone_probe-excerpt.pwcap`: Assetto Corsa (PS4 build) on PS5, live probe 2026-10-11
- `gt7_c_ps5_oval_race-start-3laps-excerpt.pwcap`: Gran Turismo 7 (variant C) on PS5, 2026-10-11 (20261011-013533,
  18.0-96.0 s): the load, the rolling start of a 10-lap race on a 0.92 km oval, laps 1-3 timed (24.286 / 23.222 /
  23.055 s), lap 3->4 - one session, lap times, race lap 1, the learned track id (1.74 MB)
- `gt7_c_ps5_oval_leave-race-frozen-excerpt.pwcap`: the same race, 117.0-128.0 s: lap 4->5, a pause, leaving the race
  and the frozen stream GT7 sends afterwards - the session ends, nothing frozen is integrated (0.25 MB)
- `gt7_c_ps5_3800m_car-reset-excerpt.pwcap`: GT7 on PS5, 2026-10-11 (20261011-124608, 349.5-353.5 s and
  457.5-461.0 s): a car reset during race lap 1 on a 3.8 km circuit, then lap 1->2 - the reset stays in the session
  (0.17 MB; the gap between the windows is an excerpt artefact)
- `f1_25_2025_ps5_f2_one-shot-quali-line-excerpt.pwcap`: F1 25 v1.26 on PS5, F2 car (Art GP '24, formula F2),
  2026-10-11 (20261011-224147, 571.6-579.0 s and 737.0-745.0 s): Sakhir one-shot qualifying - the session start, the
  line crossing (lap 1 -> 2, 1:56.133) and the result turning "finished" 17 ms later with the last-lap time unchanged
  (one lap stored, never a second) (0.54 MB)
- `f1_25_2025_ps5_f2_jeddah_race-excerpt.pwcap`: the same capture, 3228.1-3236.0 s, 3356.5-3359.0 s and
  3427.5-3429.5 s: Jeddah feature race ("Race 2") - the start, the DRS enabled event, DRS allowed for a moment; 0 in
  every ERS field, F2 tyre sets (actual 11 / 13 / 15, visual 19 / 21 / 15), a 60 km/h pit limit (0.98 MB)
- `f1_25_2025_ps5_f2_melbourne_gp-excerpt.pwcap`: F1 25 v1.26 on PS5, 2026-10-11 (20261011-011513, 100.0-101.0 s
  and 136.5-146.0 s): a Grand Prix race in a 2025 F2 car - the player's team id 214 and the 22-car field on team ids
  209-219, which EA's document does not list (1.12 MB)
- Race radio (`tests/recorded/test_raceradio_real.py`, cut with `scripts/excerpt_capture.py`, names scrubbed; times
  are seconds into the source capture, found with `scripts/race_radio_check.py --marks`):
  - `f1_25_2025_ps5_austria-reverse_race-yellow-warnings-excerpt.pwcap`: F1 25, Austria (Reverse) race lap 1
    (20261010-193550, 89-93 s and 103-117 s): a contact warning (PENA 5/4) at 91.15 s; the player's own FIA flag
    yellow 105.31 s, green, yellow again, green, none while cars stream past after its own contact (1.98 MB)
  - `f1_25_2025_ps5_monza_race-pass-then-penalty-excerpt.pwcap`: F1 25, Monza race lap 2 (20261010-204720,
    126-141 s): a pass to P1 at 129.16 s and a 3 s corner-cutting penalty (PENA 4/7) 0.9 s later, the place lost at
    135.17 s, the own FIA flag yellow at 137.69 s (1.60 MB)
  - `f1_25_2025_ps5_austria_race-blue-damage-excerpt.pwcap`: F1 25, Austria race lap 69, lapped (20261011-185757,
    100-116 s and 125-132 s): FIA blue at 103.01 s and 110.15 s, a crash at 111.57 s (both front wings gone, a
    puncture), PENA 16/42 (retired) at 112.48 s; a flashback at 126.24 s, RTMT re-sent at 126.98 s (1.63 MB)
  - `f1_25_2025_ps5_jeddah_race-damage-steps-excerpt.pwcap`: F1 25, Jeddah sprint lap 1 (20261011-224147,
    3236-3250 s): contact damage stepping up from 3240.43 s (front wing 71 -> 100, floor 10 -> 99 within 0.8 s), a
    contact warning at 3244.37 s, a flashback at 3247.25 s (1.18 MB)
  - `gt7_c_ps5_3800m_race-last-lap-finish-excerpt.pwcap`: GT7 on PS5, 4-lap race on the 3.8 km circuit
    (20261011-124608, 1198-1210 s and 1302-1310 s): the lap 3 -> 4 line at 1203.24 s, lap 4 done (P4) at 1306.71 s
    (0.45 MB; the excerpt starts mid-race, so its grid is an artefact)
