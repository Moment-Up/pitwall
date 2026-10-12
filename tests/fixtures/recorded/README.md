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
  20261011-224147, session ...314818, carcass tyre model): the start, the lap-1 baseline, the lap-1 pit stop and the
  exit on new tyres (carcass 30 C against 88 C), warm again on lap 3 - car health's cold-tyre call (1.25 MB). Only the
  Session, LapData, Event and CarTelemetry packets of the windows (`excerpt_capture.py --f1-packet-id`), each unchanged
- `f1_25_2025_ps5_bahrain-f2_race-lockups-abs-off-excerpt.pwcap`: the same capture's F2 Bahrain race (session
  ...752346, ABS off), lap 2: five lock-ups, wheels fully locked (slip -1.0) - car health's lock-up counts (1.52 MB).
  Only the Session, LapData, CarTelemetry, CarStatus and MotionEx packets of the windows, each unchanged
- `ac_ps5_ks_silverstone_probe-excerpt.pwcap`: Assetto Corsa (PS4 build) on PS5, live probe 2026-10-11
- `gt7_c_ps5_oval_race-start-3laps-excerpt.pwcap`: Gran Turismo 7 (variant C) on PS5, 2026-10-11 (20261011-013533,
  18.0-96.0 s): the load, the rolling start of a 10-lap race on a 0.92 km oval, laps 1-3 timed (24.286 / 23.222 /
  23.055 s), lap 3->4 - one session, lap times, race lap 1, the learned track id (1.74 MB)
- `gt7_c_ps5_oval_leave-race-frozen-excerpt.pwcap`: the same race, 117.0-128.0 s: lap 4->5, a pause, leaving the race
  and the frozen stream GT7 sends afterwards - the session ends, nothing frozen is integrated (0.25 MB)
- `gt7_c_ps5_3800m_car-reset-excerpt.pwcap`: GT7 on PS5, 2026-10-11 (20261011-124608, 349.5-353.5 s and
  457.5-461.0 s): a car reset during race lap 1 on a 3.8 km circuit, then lap 1->2 - the reset stays in the session
  (0.17 MB; the gap between the windows is an excerpt artefact)
