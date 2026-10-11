# Tasks for Claude Code cloud sessions

These run without the maintainer's Mac, the PS5 or the local Qwen: cloud sessions only see this repository (no `data/`,
no live service, no UDP from a console). Each task is self-contained: paste the prompt into a new cloud session on
`Moment-Up/pitwall`. Every task must:

- read `CLAUDE.md` first and follow its non-negotiable rules;
- work on its own branch and open a pull request (never push to `main`);
- keep `uv run ruff check src tests`, `uv run mypy` and `uv run pytest -q` green (and `cd web && npm run check` if
  web files change);
- touch only the files the task names, and list anything else it needs under "Integration needed" in the PR body;
- never claim live/console validation: cloud sessions can only produce synthetic or recorded-tier evidence.

The local Mac session merges the PRs, wires them into the running service and validates on the PS5.

**Status (2026-10-10 late):** tasks 1-5 are being done in the local Mac session - do **not** start them in the
cloud. Start **task 8 (car setups)** now. Start tasks 6 and 7 once the local session says the Assetto Corsa work has
landed (they edit the same integration files).

---

## 1. Assetto Corsa: review, fix and wire in
> Review and finish the Assetto Corsa remote-telemetry integration: `src/pitwall/adapters/ac/`,
> `src/pitwall/ingest/ac_client.py`, `src/pitwall/sim/ac_stream.py`, `scripts/probe_ac.py`, `tests/unit/test_ac.py`,
> spec `docs/research/protocols/ac-remote-udp.md`. First do an adversarial review (offsets vs the Kunos spec, steer /
> gear / g units, lap logic without RTLap, lap distance never fabricated before the track length is learned, client
> rate limits and socket hygiene, no code copied from GPL/AGPL/unlicensed repos) and fix what you find. Then wire it
> into the multi-game framework: an `ac` integration in `src/pitwall/integrations.py` that needs a console IP, a
> client-source path in `src/pitwall/core/runtime.py` (the client is the packet source, like `UdpListener`), the AC
> guide in `src/pitwall/connect.py`, and the capability rows in `src/pitwall/capabilities.py` (PC/PS4
> community-documented, PS5 unverified, Xbox One unsupported). Tests must use 127.0.0.1 only.

## 2. Rig setup: review fixes + research revision 2
> Fix the rig Setup component (`src/pitwall/rig/`, `src/pitwall/api/routes_rig.py`, `web/src/views/SetupView.svelte`,
> `web/src/lib/rig.ts`, `tests/unit/test_rig.py`, `tests/recorded/test_rig_check_real.py`, `docs/rig-setup.md`).
> Known review findings: brake_at_rest_max ignores ghost readings >= 10% at full throttle; 8 Nm safety text claims
> the force was already reduced when it was not; GT7 steering metrics use F1's normalisation (GT7 uses a nominal
> 900 deg); `/check?baseline=upgrade` can compare a session with itself; merged double stops counted as re-applies;
> GT7 realism Max. Torque labelled verified against a source value of 6; upgrade switch desync on cancel; per-driver
> prefs leak during a driver switch; MPS/AP rows shown for a rim without them; PC/PS5 presets mis-tagged.
> Then migrate the catalog to research revision 2 (`docs/research/rig-setup-sources.md`,
> `docs/research/rig-presets-draft.json` schema 2): keep in-game strength at 8 Nm (only comfort scales), FFS likely
> gone with the Boost Kit, load-cell BRF from exact-kit owners (median 55), the F1 25 v1.25 session-change
> oscillation bug as a known issue, 19 rig-check metrics.

## 3. Verify the corner-identity track sheets
> Hand-verify `src/pitwall/trackdata/track_sheets/f1/*.toml` (all except `17_austria.toml`, which is the standard to
> follow) against FIA circuit maps (cite PDFs), F1DB and Wikipedia: turn numbers, directions, game-metre windows,
> names. Only mark `verified=true` what you actually checked; `voice_ok` only for current, undisputed names; reverse
> layouts get names only. Priority: 7 Silverstone, 11 Monza, 39 Silverstone Reverse, 40 Austria Reverse, then the
> rest. Read `src/pitwall/analysis/track_identity.py` and `docs/research/track-knowledge-sources.md` section 4 first.
> Keep `tests/unit/test_track_identity.py` green.

## 4. Track knowledge: AI-field model (layer L0b)
> Implement `docs/research/track-knowledge-sources.md` section 8 "Phase 3": decode all car slots in the F1 adapter
> (decimated, ingest-safe), `src/pitwall/analysis/field_model.py` (5 m bins, robust medians, the section 2 filters,
> brake onsets, provisional corners, support counts) and `src/pitwall/core/track_knowledge.py` (resolver with
> L3 > L0b > L1c precedence). Synthetic AI cars with injected brake points in `src/pitwall/sim/f1_stream.py`;
> recorded-tier test on `tests/fixtures/recorded/f1_25_2025_ps5_austria_race-excerpt.pwcap` (it contains the AI
> field). Never present AI data as the driver's target; heads-ups are placed conservatively early.

## 5. Track knowledge: map before the first lap + heavy-stop prior (L1a / L1c)
> Implement section 8 "Phase 4" of `docs/research/track-knowledge-sources.md`: vendor the Pits n' Giggles
> `assets/track-maps/f1_2025` outlines + `svg_transforms.json` (MIT, same pin and PROVENANCE as the vendored
> track-segments), `src/pitwall/analysis/track_geometry.py` (affine inversion, smoothing, curvature, length gate),
> `src/pitwall/analysis/brake_prior.py` (pitwall's own QSS solver, gated to heavy stops, heads-up windows only) and
> `src/pitwall/api/routes_track.py`. Check the outline's axes against the player's line in the Austria fixture.

## 6. New adapters from the protocol specs
> Implement game adapters from `docs/research/protocols/`: `pcars2-udp.md` (Project CARS 2 / Automobilista 2 /
> Project CARS 3), `acc-broadcast.md` (ACC broadcasting client) and `ea-wrc-json.md` (EA SPORTS WRC). One package per
> family under `src/pitwall/adapters/`, a synthetic generator under `src/pitwall/sim/`, unit tests, honest
> `AdapterInfo` support levels, and an integration entry + Connect guide. Never guess layouts the specs leave open.

## 7. GT Sport and older F1 formats
> Extend the GT7 adapter for Gran Turismo Sport (same Simulator Interface, different key and ports 33339/33340: see
> `docs/research/game-compatibility.md`) and the F1 adapter for UDP formats 2024 and 2023 (F1 24 / F1 23), machine-
> checked against the published specs like `tests/unit/test_f1_protocol.py`. Synthetic tests only.

## 8. F1 car setups per track (start this one now)
> Build per-track car setup recommendations for EA SPORTS F1 25 (2025 cars) and the 2026 Season Pack cars, and
> compare them with the driver's actual setup. Pitwall already receives the player's setup over UDP: read
> `src/pitwall/adapters/f1/adapter.py` (CarSetups packet -> `CarSetup` in `src/pitwall/model/telemetry.py`),
> `src/pitwall/storage/repo.py` (`insert_setup`, `latest_setup`), the `setups` and `setup_experiments` tables in
> `src/pitwall/storage/db.py`, and `src/pitwall/ai/facts.py`. The 2026 Season Pack changes the cars (active aero,
> different packet fields) - keep its setups separate and never mix the two formats.
> 1. **Research** (write `docs/research/f1-car-setups.md`): for every F1 25 track id (see
>    `src/pitwall/adapters/f1/enums.py`), community setups for race and qualifying, dry and wet: front/rear wing,
>    differential on/off throttle, engine braking, camber/toe, suspension, anti-roll bars, ride height, brake
>    pressure and bias, tyre pressures. Sources: F1 esports drivers, well-known setup sites and creators. Cite every
>    source with date and game patch; prefer setups published after the latest handling patches; record disagreement
>    between sources instead of averaging blindly; note each source's terms (do not scrape sites whose terms forbid
>    it; record values as facts with attribution, never copy page text). Also capture the game's in-game parameter
>    ranges and steps per format (F1 25 vs 2026 pack) from EA's UDP spec and the game.
> 2. **Catalog** `src/pitwall/carsetup/data/f1_25_setups.json` (+ a typed loader with schema validation, stdlib only):
>    per track x car format x session type (race / qualifying) x conditions (dry / wet) x style (balanced / stable /
>    aggressive), each value with source(s), patch, confidence, and a flag when pitwall derived it (e.g. a consensus
>    of several sources). Unknown stays unknown.
> 3. **Logic** `src/pitwall/carsetup/recommend.py` and `compare.py`: pick the recommendation for the current
>    session (track, format, session type, weather from `SessionInfo`), diff it against the driver's latest stored
>    setup parameter by parameter, and explain each difference in plain words (what it changes in the car's
>    behaviour). Skill-aware: beginners get a stable setup first. Never present a setup change as a guaranteed fix;
>    the engineer's rule is to rule out technique first (see `src/pitwall/ai/engineer.py` SYSTEM_PROMPT).
> 4. **Setup experiments** (phase 8): an API to propose a single-variable change, link the before/after sessions,
>    and compare lap time, corner deltas and tyre wear from existing analysis (`setup_experiments` table already
>    exists; add repo functions there).
> 5. **API + UI**: `src/pitwall/api/routes_carsetup.py` (APIRouter `/api/carsetup`, the lead mounts it) and a new
>    `web/src/views/CarSetupView.svelte` + `web/src/lib/carsetup.ts`: pick track / session / conditions / style,
>    show the setup in the game's menu order with copy-friendly values, "your setup vs recommended" diff when a
>    session has a stored setup, sources and confidence badges. iPad-friendly. Do not edit `App.svelte` or
>    `SetupView.svelte` (the lead adds the tab).
> 6. **Facts**: describe (do not apply) the change needed in `src/pitwall/ai/facts.py` so the engineer can answer
>    "what setup should I run here?" and "what's different from the recommended setup?" from these facts.
> 7. **Tests**: catalog validation (every value within the game's range and step, every value sourced or flagged
>    derived), recommendation selection, diff on the `CarSetup` decoded from
>    `tests/fixtures/recorded/f1_25_2025_ps5_austria_race-excerpt.pwcap` (it contains real CarSetups packets),
>    experiments lifecycle, API via TestClient.
