# Recorded real-game captures

Put **real** game captures (`.pwcap`) here to enable the *recorded validation* tier
(`tests/recorded`). Pitwall records every live session automatically to `data/captures/`;
copy a capture here once you have checked it is genuine game output (not a synthetic stream).

Naming: `<game>_<format>_<platform>_<track>_<description>.pwcap`, e.g.
`f1_25_2025_ps5_spa_practice-5laps.pwcap`.

Licensing: only commit captures you recorded yourself. Third-party captures found online
(e.g. in unlicensed GitHub repositories) must not be added - see docs/licences.md.

Privacy: real captures carry player names. F1 25 sends every participant's online ID or name (Participants,
Lobby Info); Assetto Corsa sends yours (handshake reply, RTLap). Before committing, run
`uv run python scripts/scrub_capture.py tests/fixtures/recorded/<file>.pwcap`: it rewrites only those name fields
(F1: the player's car becomes `Player`, every other car `Driver NN`; AC: `Player`) and LAN addresses in the capture
metadata (to 127.0.0.1), keeps every packet length, timestamp and all other bytes, checks that no original name
is left, and notes the scrub in the capture's description. `scripts/scrub_capture.py --check <files>` only checks
(exit 1 if a name or LAN address is left); `scripts/package_release.py` runs it on every capture in a release.

Committed captures (each a byte-for-byte excerpt of the maintainer's own PS5 sessions, see
`scripts/excerpt_capture.py`, with the name fields then replaced by `scripts/scrub_capture.py`):
- `f1_25_2025_ps5_austria_race-excerpt.pwcap`: F1 25 v1.26, Austria race - standing start, lap changes, finish
- `f1_25_2025_ps5_monza_race-excerpt.pwcap`: F1 25, Monza race lap 3, 560-2250 m (T1-2, T4-5) - every packet
  unchanged apart from the participant names
- `ac_ps5_ks_silverstone_probe-excerpt.pwcap`: Assetto Corsa (PS4 build) on PS5, live probe 2026-10-11
