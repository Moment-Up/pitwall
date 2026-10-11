"""RECORDED tier: real Assetto Corsa (PS4 build) output from a PS5, captured by the live probe on 2026-10-11.

``scripts/probe_ac.py`` registered with the console (UPDATE socket, then a second SPOT socket after 120 s) while
James drove ``ks_audi_r8_plus`` at ``ks_silverstone``. The fixture is a byte-for-byte excerpt
(``scripts/excerpt_capture.py``) of four windows of that capture: the handshake, a pause and the pull-away
(0-12 s); the approach to the line, the crossing and 11 s of lap 2 (55-100 s); the SPOT socket's handshake reply
(119-122 s); a pause, the lap counter resetting into the pit box, the restored state and a teleport to the pit box
(163-176 s). Gaps between windows are excerpt artefacts.

Only facts of the real data are asserted (sizes, strings, byte values, the game's own lap time, where the spline
wraps relative to the increment, the pit-exit lane running off the racing line with isInPit = 0), plus what the
adapter makes of them: exactly one completion, the line at spline 0 from the first crossing, a track-length estimate
from lap 2 only (2945.3 m after 15 % of it - the excerpt holds every packet it uses, so it equals the full
capture's), and the restored state after the counter reset handled without a lap. The full capture's numbers
(14,356 RTCarInfo at 59.8 Hz, 0 rejected) are in docs/validation.md; it stays in data/captures (2.7 MB).

This is the RECORDED tier: the adapter ran on a recording. pitwall's own client and service have not yet run
against the console.
"""

from __future__ import annotations

import bisect
import itertools
import math
from pathlib import Path

import pytest

from pitwall.adapters.ac import packets as P
from pitwall.adapters.ac.adapter import ZERO_LINE_TOL, AcAdapter
from pitwall.analysis.laps import LapAssembler, LapTrace
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.model.telemetry import CarFrame, Emitted, EventKind, GameEvent, LapCompletion, Platform, SessionInfo

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "recorded" / "ac_ps5_ks_silverstone_probe-excerpt.pwcap"
LAP_1_MS = 138_817  # the game's own time for the lap completed at the crossing (lastLap and RTLap agree)
ESTIMATE_M = 2945.3  # the adapter's estimate: path / spline over the first 15 % of lap 2 (deterministic replay)
PIT_BOX_NORM = 0.07989  # spline position of the pit box (stationary, isInPit = 1)
RESTORED_NORM = 0.85695  # spline position of the state the game restored after the counter reset

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not FIXTURE.exists(), reason="real PS5 AC excerpt not present"),
]


@pytest.fixture(scope="module")
def packets() -> list[CapturedPacket]:
    reader = CaptureReader(FIXTURE)
    assert not reader.meta.synthetic and reader.meta.game_hint == "ac-remote"
    assert reader.meta.extra["platform"] == "ps5"
    return list(reader)


@pytest.fixture(scope="module")
def decoded(packets: list[CapturedPacket]) -> tuple[list[Emitted], AcAdapter]:
    adapter = AcAdapter(platform=Platform.PS5)
    out: list[Emitted] = []
    for p in packets:
        out += adapter.decode(p.data, p.t_recv_ns)
    out += adapter.flush()
    return out, adapter


def car_infos(packets: list[CapturedPacket]) -> list[tuple[CapturedPacket, dict[str, object]]]:
    return [(p, P.parse_rt_car_info(p.data)) for p in packets if len(p.data) == P.RT_CAR_INFO.size]


def _int(v: object) -> int:
    assert isinstance(v, int)
    return v


def _float(v: object) -> float:
    assert isinstance(v, float)
    return v


# ------------------------------------------------------------------------------------------------ the wire
def test_every_datagram_has_an_exact_ac_size_and_nothing_is_rejected(
    packets: list[CapturedPacket], decoded: tuple[list[Emitted], AcAdapter]
) -> None:
    sizes = {len(p.data) for p in packets}
    assert sizes == {408, 328, 212}  # handshake reply (UTF-16), RTCarInfo, RTLap
    assert all(p.src_port == P.AC_PORT for p in packets)
    _, adapter = decoded
    st = adapter.stats
    assert st.packets == len(packets) and st.decoded == len(packets)
    assert st.rejected == 0 and st.errors == 0 and st.ignored == 0, st.last_error
    assert "identifier_unexpected" not in st.by_type and "size_field_unexpected" not in st.by_type


def test_handshake_reply_is_utf16_with_the_documented_status(packets: list[CapturedPacket]) -> None:
    replies = [P.parse_handshake_response(p.data) for p in packets if len(p.data) == 408]
    assert len(replies) == 2  # UPDATE socket at the start, SPOT socket at 120 s: same identity
    for hs in replies:
        assert hs.wide and hs.identifier == P.HANDSHAKE_STATUS_OK and hs.version == 1
        assert hs.car_name == "ks_audi_r8_plus" and hs.track_name == "ks_silverstone"
        assert hs.track_config == "ks_silverstone"  # the console repeats the track name: no layout on the wire
        assert hs.driver_name  # the player's name: "Player" in this fixture (scripts/scrub_capture.py)
    assert replies[0] == replies[1]


def test_rt_car_info_identity_bytes_and_isinpit_at_24(packets: list[CapturedPacket]) -> None:
    rows = car_infos(packets)
    assert len(rows) > 4000
    assert {p.data[0] for p, _ in rows} == {ord("a")} and {p.data[1] for p, _ in rows} == {0}
    assert {_int(v["size"]) for _, v in rows} == {328}
    assert {p.data[24] for p, _ in rows} == {0, 1}  # isInPit toggles (natural alignment)
    assert {p.data[26] for p, _ in rows} == {0} and {p.data[27] for p, _ in rows} == {0}  # padding stays 0
    assert {p.data[25] for p, _ in rows} == {0}  # isEngineLimiterOn: never on in this capture (still unverified)
    in_pit_speeds = [_float(v["speed_Kmh"]) for p, v in rows if p.data[24] == 1]
    assert in_pit_speeds and max(in_pit_speeds) < 1.0  # only ever set with the car stopped in the pit box


def test_speed_units_and_world_position_in_metres(packets: list[CapturedPacket]) -> None:
    rows = car_infos(packets)
    for _, v in rows:
        kmh, ms = _float(v["speed_Kmh"]), _float(v["speed_Ms"])
        assert kmh == pytest.approx(3.6 * ms, rel=1e-5, abs=1e-4)
    # carCoordinates path == integral of speed_Ms over the lap clock (the 11 s of lap 2 after the crossing): metres
    t0 = packets[0].t_recv_ns
    path = integral = 0.0
    for (_, a), (pb, b) in itertools.pairwise(rows):
        if _int(a["lapCount"]) != 1 or _int(b["lapCount"]) != 1 or pb.t_recv_ns - t0 > 100e9:
            continue
        dt = (_int(b["lapTime"]) - _int(a["lapTime"])) / 1000.0
        if not 0.0 < dt < 0.1:
            continue
        ca, cb = a["carCoordinates"], b["carCoordinates"]
        assert isinstance(ca, tuple) and isinstance(cb, tuple)
        path += math.dist(ca, cb)
        integral += 0.5 * (_float(a["speed_Ms"]) + _float(b["speed_Ms"])) * dt
    assert path > 400.0 and path == pytest.approx(integral, rel=2e-3)


def test_the_spline_wraps_at_the_line_two_packets_before_the_increment(packets: list[CapturedPacket]) -> None:
    rows = [v for _, v in car_infos(packets)]
    inc = next(i for i in range(1, len(rows)) if _int(rows[i]["lapCount"]) == _int(rows[i - 1]["lapCount"]) + 1)
    wrap = next(
        i
        for i in range(1, len(rows))
        if _float(rows[i - 1]["carPositionNormalized"]) > 0.99 and _float(rows[i]["carPositionNormalized"]) < 0.01
    )
    assert 0 <= inc - wrap <= 3  # observed: 2 packets (33 ms)
    crossing = rows[inc]
    assert _float(crossing["carPositionNormalized"]) < ZERO_LINE_TOL
    assert _int(crossing["lapTime"]) < 50  # the lap clock restarts at the line
    assert _int(crossing["lastLap"]) == LAP_1_MS and _int(rows[inc - 1]["lastLap"]) == 0  # updated in that packet
    assert _int(crossing["bestLap"]) == LAP_1_MS


def test_rt_lap_arrives_on_ps5_with_the_lap_time(packets: list[CapturedPacket]) -> None:
    laps = [P.parse_rt_lap(p.data) for p in packets if len(p.data) == P.RT_LAP.size]
    hs = P.parse_handshake_response(next(p.data for p in packets if len(p.data) == 408))
    assert [(r.lap, r.time_ms) for r in laps] == [(-1, 0), (0, LAP_1_MS)]  # reset marker, then lap index 0
    assert all(r.car_name == hs.car_name and r.driver_name == hs.driver_name for r in laps)


# ------------------------------------------------------------------------------------------------ the adapter
def test_exactly_one_completion_timed_by_the_game(decoded: tuple[list[Emitted], AcAdapter]) -> None:
    out, adapter = decoded
    comps = [e for e in out if isinstance(e, LapCompletion)]
    assert [(c.lap_number, c.lap_time_ms, c.valid) for c in comps] == [(1, LAP_1_MS, None)]
    # the restored state (lapCount 0 -> 1 without the lap clock restarting) and the RTLap the game re-sent with it
    # are recognised, not turned into a second lap 1
    st = adapter.stats.by_type
    assert st["increment_without_lap_start"] == 1 and st["rt_lap_unmatched"] == 1 and st["rt_lap_without_time"] == 1


def _uid_frames(out: list[Emitted]) -> list[tuple[str, CarFrame]]:
    """CarFrames tagged with the session they belong to (the latest SessionInfo before them)."""
    uid, rows = "", []
    for e in out:
        if isinstance(e, SessionInfo):
            uid = e.session_uid or ""
        elif isinstance(e, CarFrame):
            rows.append((uid, e))
    return rows


def test_line_at_the_first_crossing_and_length_estimated_on_lap_2_only(
    decoded: tuple[list[Emitted], AcAdapter],
) -> None:
    out, adapter = decoded
    comp = next(e for e in out if isinstance(e, LapCompletion))
    frames = [e for e in out if isinstance(e, CarFrame)]
    assert all(f.lap_distance_m is None for f in frames if f.t_recv_ns < comp.t_recv_ns)  # the out-lap has none
    at_line = [e for e in out if isinstance(e, SessionInfo) and e.t_recv_ns <= comp.t_recv_ns][-1]
    assert at_line.extra["ac_line_norm"] == 0.0 and at_line.extra["ac_line_source"] == "spline_zero"
    assert at_line.track_length_m is None  # the out-lap (pit-exit lane included) is not used for the length
    est = next(e for e in out if isinstance(e, SessionInfo) and e.track_length_m is not None)
    # pinned: a regression of a few metres in the estimate maths fails here (GP would be 5891 m)
    assert est.track_length_m == pytest.approx(ESTIMATE_M, abs=0.5)
    assert est.extra["track_length_estimate_fraction"] == 0.15 and est.extra["track_length_quality"] == "estimate"
    assert est.extra["track_length_source"] == "derived:path_over_spline_estimate"
    assert 9.5 < (est.t_recv_ns - comp.t_recv_ns) / 1e9 < 11.0  # ~10 s into lap 2
    lap2 = [f for f in frames if f.lap_number == 2 and f.t_recv_ns < est.t_recv_ns + 20e9]
    assert lap2[0].t_recv_ns == comp.t_recv_ns  # the crossing packet itself opens lap 2
    with_d = [f for f in lap2 if f.lap_distance_m is not None]
    assert with_d and with_d[0].t_recv_ns == est.t_recv_ns
    assert all(f.lap_distance_m is None for f in lap2 if f.t_recv_ns < est.t_recv_ns)
    assert 0.149 * ESTIMATE_M < (with_d[0].lap_distance_m or 0.0) < 0.152 * ESTIMATE_M  # true position, mid-lap
    assert adapter.stats.by_type["line_spline_zero"] == 1 and "line_candidate" not in adapter.stats.by_type
    assert adapter.stats.by_type["length_estimated"] == 1 and "length_learned" not in adapter.stats.by_type


def test_the_pit_exit_lane_runs_off_the_line_with_isinpit_zero(packets: list[CapturedPacket]) -> None:
    """t = 6-12 s: the car pulls away down the pit-exit lane, ~29 m off lap 2's line, isInPit 0, path/spline short.
    That is why the estimate starts at the first crossing."""
    t0 = packets[0].t_recv_ns
    rows = [(round((p.t_recv_ns - t0) / 1e9, 3), v) for p, v in car_infos(packets)]
    lap2 = sorted((_float(v["carPositionNormalized"]), v["carCoordinates"]) for t, v in rows if 88.7 < t < 100.0)
    norms = [n for n, _ in lap2]
    offsets, path, prog = [], 0.0, 0.0
    lane = [(t, v) for t, v in rows if 6.1 <= t <= 12.0]
    for (_, a), (_, b) in itertools.pairwise(lane):
        assert _int(b["isInPit"]) == 0
        ca, cb = a["carCoordinates"], b["carCoordinates"]
        assert isinstance(ca, tuple) and isinstance(cb, tuple)
        path += math.dist(ca, cb)
        prog += _float(b["carPositionNormalized"]) - _float(a["carPositionNormalized"])
        j = min(bisect.bisect_left(norms, _float(b["carPositionNormalized"])), len(norms) - 1)
        other = lap2[j][1]
        assert isinstance(other, tuple)
        offsets.append(math.dist(cb, other))
    assert max(offsets) > 25.0  # metres off the racing line at the same spline position
    assert prog > 0.04 and path / prog < 0.97 * ESTIMATE_M  # reads short: it would bias a length estimate


def test_back_to_pits_starts_a_new_session(decoded: tuple[list[Emitted], AcAdapter]) -> None:
    out, adapter = decoded
    events = [e for e in out if isinstance(e, GameEvent)]
    assert [e.kind for e in events if e.kind in (EventKind.SESSION_STARTED, EventKind.SESSION_ENDED)] == [
        EventKind.SESSION_STARTED,
        EventKind.SESSION_ENDED,
        EventKind.SESSION_STARTED,
    ]
    assert next(e for e in events if e.kind is EventKind.SESSION_ENDED).payload["reason"] == "lap_counter_reset"
    assert len({e.session_uid for e in out if isinstance(e, SessionInfo)}) == 2
    assert adapter.stats.by_type["teleport"] >= 1 and adapter.stats.by_type["lap_time_reset"] == 1
    pit = [f for f in out if isinstance(f, CarFrame) and f.pit_status == 2]
    assert pit and all(f.speed_kph is not None and f.speed_kph < 1.0 for f in pit)
    assert all(f.pit_status in (None, 2) for f in out if isinstance(f, CarFrame))  # isInPit 0 -> unknown


def test_session_two_starts_from_the_estimate_and_never_measures_the_restored_lap(
    decoded: tuple[list[Emitted], AcAdapter],
) -> None:
    out, adapter = decoded
    infos = [e for e in out if isinstance(e, SessionInfo)]
    uid2 = infos[-1].session_uid
    first2 = next(i for i in infos if i.session_uid == uid2)
    assert first2.track_length_m == pytest.approx(ESTIMATE_M, abs=0.5)  # session 1's estimate, stored geometry
    assert first2.extra["track_length_source"] == "known" and first2.extra["track_length_quality"] == "estimate"
    s2 = [f for uid, f in _uid_frames(out) if uid == uid2]
    box = [f for f in s2 if f.lap_number == 1 and f.lap_distance_m is not None]
    assert box and all(f.pit_status == 2 for f in box)
    assert all(f.lap_distance_m == pytest.approx(PIT_BOX_NORM * ESTIMATE_M, abs=0.5) for f in box)
    restored = [f for f in s2 if f.lap_number == 2]
    assert restored[0].lap_distance_m == pytest.approx(RESTORED_NORM * ESTIMATE_M, abs=0.5)  # unanchored, true spot
    teleport_t = next(f.t_recv_ns for f in restored if f.pit_status == 2)  # sent to the pit box, clock running
    assert all(f.lap_distance_m is None for f in restored if f.t_recv_ns >= teleport_t)
    assert any(f.lap_distance_m is not None for f in restored if f.t_recv_ns < teleport_t)
    # nothing in this recording can become a reference: no completed lap had a measured, confirmed scale
    assert not [lap for lap in _assemble_by_session(out) if lap.clean]
    assert "length_learned" not in adapter.stats.by_type and "estimate_scaled_lap_void" not in adapter.stats.by_type


def _assemble_by_session(out: list[Emitted]) -> list[LapTrace]:
    """One ``LapAssembler`` per adapter session, as the session manager runs them."""
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append)
    uid: str | None = None
    for e in out:
        if isinstance(e, SessionInfo):
            if e.session_uid != uid:
                asm.flush()
                asm, uid = LapAssembler(laps.append), e.session_uid
            asm.set_track_length(e.track_length_m)
        elif isinstance(e, CarFrame):
            asm.feed(e)
        elif isinstance(e, LapCompletion):
            asm.feed_completion(e)
    asm.flush()
    return laps
