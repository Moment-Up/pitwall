# Validation guide

Three evidence tiers - never mix them up:

| Tier | What it proves | How |
|---|---|---|
| **Synthetic** | Our algorithms recover *known, injected* driving errors from a byte-exact packet stream | `uv run pytest` (default) |
| **Recorded** | The decoder copes with *real game output* (sizes, ranges, lap structure) | captures in `tests/fixtures/recorded/` -> `uv run pytest -m recorded` |
| **Live** | A specific game + platform works end-to-end on your network | steps below + `uv run pytest -m live tests/live -s` |

A capability may be marked `live_validated` in `src/pitwall/capabilities.py` only after the live steps pass
on that platform.

## Rig validation kit
<!-- validation kit (lane validate) -->
The live tests still pending (docs/status.md) are run from **Setup › Validation** on the iPad, in the seat:

1. Start a run (all available tests that are not optional; the one-hour test is opt-in). Or say "start validation"
   on the radio.
2. For each test, follow its steps; Pitwall collects the evidence as you drive. Then tap **Worked** or **Didn't
   work**, tick the boxes and add a note. "Next test" moves on; "Skip for now" leaves a test out.
3. **Finish and save**: `data/validation/<run_id>/report.md` and `report.json` are written.
4. Review: `uv run pitwall validate list`, `uv run pitwall validate show latest`, `uv run pitwall validate report
   latest --out report.md` (`--json`, `--redact-transcripts`).
5. If you agree with a test's evidence, add a row to the Results log below and upgrade `src/pitwall/capabilities.py`
   and docs/status.md **by hand**. The report's "What this run can support" section names the lines; the kit itself
   never changes a status.

Only live evidence (telemetry from the console on the network) can pass; replays (`recorded`), synthetic streams and
`pitwall send` over loopback are shown and labelled but never count.
<!-- end validation kit -->

## Live validation: F1 25 on PS5 (repeat for Xbox / PC)

1. On the Mac: `uv run pitwall serve`. Note the printed `Game telemetry: UDP <mac-ip>:20777`.
   (macOS may ask to allow incoming connections for Python - allow it.)
2. On the PS5, F1 25 -> Settings -> Telemetry Settings:
   - UDP Telemetry: **On**
   - UDP Broadcast Mode: **Off**
   - UDP IP Address: the Mac's IP (the `<mac-ip>` printed in step 1, e.g. 192.0.2.10)
   - UDP Port: **20777**
   - UDP Send Rate: **60 Hz** (20 Hz works; coaching precision is ~4 m at 20 Hz vs ~1.4 m at 60 Hz)
   - UDP Format: **2025** (or **2026** with the 2026 Season Pack - both are supported)
   - Your Telemetry: **Public** (otherwise some fields for other cars are zeroed; player data is unaffected)
3. Start a Time Trial or Practice session. Within a second the dashboard (http://127.0.0.1:8770, or the LAN URL
   from `uv run pitwall token` on a phone/tablet) should show **LIVE** with ~100-500 packets/s.
   - Check: speed, gear, throttle/brake bars and steering follow your inputs; track name and session type are right.
   - Check Status page: `rejected` stays at 0.
4. Drive 3+ clean laps. Expected:
   - The track map appears after lap 1; corners T1..Tn are labelled.
   - Lap times in the Laps table match the in-game lap times **to the millisecond**.
   - From lap 2: coaching observations and the live delta to the reference.
5. Deliberately brake ~20 m early for one corner on one lap. The next lap's observations should report it.
6. Use a flashback mid-lap: that lap must show the `flashback` flag and must not become the reference.
7. Ask the engineer (Engineer tab): "Where am I losing the most time?" - the answer must cite facts.
8. Stop driving. After 60 s idle the session closes and the raw capture appears in Status -> Captures.
9. Cut a small, byte-for-byte excerpt of that capture into `tests/fixtures/recorded/` (full races are ~30 MB):
   `uv run python scripts/excerpt_capture.py data/captures/<file>.pwcap tests/fixtures/recorded/f1_25_<format>_ps5_<track>.pwcap --window <s>:<s> ...`
   Then replace the player names in it (F1 25 sends every participant's online ID or name; AC sends yours):
   `uv run python scripts/scrub_capture.py tests/fixtures/recorded/<file>.pwcap` (only the name fields change, see the
   script). Run `uv run pytest -m recorded` and commit it (your own recording).
10. Optional automated check while the game streams: `uv run pytest -m live tests/live -s`
    (stop `pitwall serve` first - it owns port 20777).

Record the result (date, platform, game version from the Status/decode info, format, pass/fail) in
`docs/status.md`, then upgrade the platform's entry in `src/pitwall/capabilities.py`.

### Results log

| Date | Game / version | Platform | Format | Result | Evidence |
|---|---|---|---|---|---|
| 2026-10-10 | F1 25 v1.26 | PS5 | 2025 | **Pass**: 0 rejected of ~190k packets; lap + sector times exact; coaching and wheel push-to-talk working | `tests/recorded/test_f1_25_ps5_austria.py` |
| 2026-10-11 | Assetto Corsa (PS4 build, back-compat) | PS5 | AC remote UDP (408 / 328 / 212 B) | **Protocol pass (probe script, live) / decoder recorded-validated**: `scripts/probe_ac.py`, 240 s; handshake answered (UTF-16, 4242); 14,356 RTCarInfo at 59.8 Hz, 0 rejected; isInPit at byte 24; RTLap (212 B) decodes on a second SPOT socket, but none arrived at a crossing (that socket opened after it). Replayed offline: one real crossing, lap 1 = 138,817 ms from lastLap in the crossing packet, completed once; the restored state after a counter reset is not a lap; spline 0 = line. pitwall's own client/service path was **not** run against the console, and no lap time reached the database in the full runtime replay (lap 1 had no distance trace). Lap coaching not yet tried | `tests/recorded/test_ac_ps5_real.py`, `docs/research/protocols/ac-remote-udp.md` §6 |
| 2026-10-11 | Assetto Corsa (PS4 build), review re-check | PS5 (recording) | as above | **Recorded only**: same capture after the review fixes. Track-length estimate from lap 2 only (the out-lap's pit-exit lane runs ~29 m off the line with isInPit 0): 2945.3 m after 15 % of lap 2, identical on the excerpt and the full capture (was 2966.0 vs 2914.1); 1.0 % below the 2974.5 m of all 1.76 clean laps. Full runtime replay into a scratch DB: 2 sessions, 3 incomplete laps stored, 0 clean, no track model, 0 observations, no duplicate lap | `tests/recorded/test_ac_ps5_real.py` (11 tests) |

### Troubleshooting
- Nothing received: Mac firewall, wrong IP (Mac IP changes with DHCP - consider a DHCP reservation), PS5 and
  Mac on different subnets/VLANs, or UDP Broadcast Mode on.
- Packets rejected with "unsupported packetFormat 2024": set UDP Format to 2025/2026.
- Lap times off by one lap: report it with a capture - this is exactly what the recorded tier is for.
