"""RECORDED tier: real Gran Turismo 7 output from the owner's PS5 (variant C), captured live on 2026-10-11.

The owner drove GT7 on a PS5 with Pitwall's live service ("it worked fine"): its heartbeat and UDP 33740 listener
recorded 277,467 packets in 4 captures (data/captures/20261011-013533 / -121256 / -124608 / -182615), 0 rejected.
The data also showed three defects of the adapter of that day, fixed since and pinned here: 4 races became 28 stored
sessions (menus, replays, background laps and car resets all started one), 5 of the 11 laps the game timed never
reached the lap list (race lap 1 was never anchored; resets split the races), and after leaving a race GT7 repeats
one frozen packet that was integrated into a 16.8 km "lap". Replaying the 4 captures now gives 4 sessions with all
11 timed laps, each equal to the game's own last-lap field.

Fixtures (byte-for-byte excerpts, ``scripts/excerpt_capture.py --game-hint gt7``; GT7 sends no names,
``scripts/scrub_capture.py`` checked the text fields and the metadata):

* ``gt7_c_ps5_oval_race-start-3laps-excerpt.pwcap`` (20261011-013533, 18.0-96.0 s): the menus' last packets, the
  load, the rolling start of a 10-lap race (car 919, 14 cars) on a 0.92 km banked oval, laps 1-3 timed, lap 3->4.
* ``gt7_c_ps5_oval_leave-race-frozen-excerpt.pwcap`` (same capture, 117.0-128.0 s): lap 4->5, a pause, leaving the
  race from the pause menu, and the frozen stream that follows (CarOnTrack set, not paused, 45.9 m/s, unchanging).
* ``gt7_c_ps5_3800m_car-reset-excerpt.pwcap`` (20261011-124608, 349.5-353.5 s and 457.5-461.0 s): a car reset during
  race lap 1 on a 3.8 km circuit (car 1370), then lap 1->2. The gap between the windows is an excerpt artefact.

Only facts of the real data are asserted (sizes, field values and their relations, the game's own lap times), plus
what the adapter and the lap assembler make of them. This is the RECORDED tier: the adapter ran on recordings; the
live run of the same day is what the capability matrix's PS5 row records.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from pitwall.adapters.gt7 import packets as P
from pitwall.adapters.gt7.adapter import OPEN_TICKS, STALL_END_TICKS, GT7Adapter, TrackSignature, _signature
from pitwall.analysis.laps import LapAssembler, LapFlag, LapTrace
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.model.telemetry import (
    CarFrame,
    Emitted,
    EventKind,
    FrameQuality,
    GameEvent,
    LapCompletion,
    SessionInfo,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
RACE = FIXTURES / "gt7_c_ps5_oval_race-start-3laps-excerpt.pwcap"
FROZEN = FIXTURES / "gt7_c_ps5_oval_leave-race-frozen-excerpt.pwcap"
RESET = FIXTURES / "gt7_c_ps5_3800m_car-reset-excerpt.pwcap"

OVAL_ID = "gt7:sf:0:100:90:920:340"  # learned on 2026-10-11 by the live service; the same id comes back on replay
RACE_LAPS_MS = {1: 24_286, 2: 23_222, 3: 23_055}  # the game's own last-lap field (0x7C) at each increment
TICK_MS = 1000.0 / 60.0

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(
        not (RACE.exists() and FROZEN.exists() and RESET.exists()), reason="real PS5 GT7 excerpts not present"
    ),
]


# ------------------------------------------------------------------------------------------------ helpers
Row = tuple[CapturedPacket, dict[str, Any], bytes]  # packet, decrypted fields, signature


def _rows(path: Path) -> list[Row]:
    reader = CaptureReader(path)
    assert not reader.meta.synthetic and reader.meta.source == "udp:33740" and reader.meta.game_hint == "gt7"
    out: list[Row] = []
    for p in reader:
        v, plain = P.decrypt(p.data)
        out.append((p, P.unpack(v, plain), _signature(plain)))
    return out


@pytest.fixture(scope="module")
def race() -> list[Row]:
    return _rows(RACE)


@pytest.fixture(scope="module")
def frozen() -> list[Row]:
    return _rows(FROZEN)


@pytest.fixture(scope="module")
def reset() -> list[Row]:
    return _rows(RESET)


class Run:
    """The adapter over one excerpt, fed to a lap assembler exactly as the session manager does."""

    def __init__(self, rows: list[Row], known: Iterable[str] = ()) -> None:
        self.adapter = GT7Adapter(known_track_ids=known)
        self.order: list[tuple[int, Emitted]] = []  # (row index, item)
        self.laps: list[LapTrace] = []
        asm: LapAssembler | None = None
        for i, (p, _, _) in enumerate(rows):
            for e in self.adapter.decode(p.data, p.t_recv_ns):
                self.order.append((i, e))
                if isinstance(e, GameEvent) and e.kind == EventKind.SESSION_ENDED:
                    if asm is not None:
                        asm.flush()
                    asm = None
                elif isinstance(e, SessionInfo):
                    asm = asm or LapAssembler(self.laps.append)
                    asm.set_track_length(e.track_length_m)
                elif isinstance(e, CarFrame):
                    assert asm is not None
                    asm.feed(e)
                elif isinstance(e, LapCompletion):
                    assert asm is not None
                    asm.feed_completion(e)
        if asm is not None:
            asm.flush()

    def items[T](self, kind: type[T]) -> list[tuple[int, T]]:
        return [(i, e) for i, e in self.order if isinstance(e, kind)]

    @property
    def frames(self) -> list[CarFrame]:
        return [e for _, e in self.items(CarFrame)]

    @property
    def ended(self) -> list[str | None]:
        return [e.code for _, e in self.items(GameEvent) if e.kind == EventKind.SESSION_ENDED]

    def lap(self, n: int) -> LapTrace:
        return next(lap for lap in self.laps if lap.lap_number == n)


@pytest.fixture(scope="module")
def race_run(race: list[Row]) -> Run:
    return Run(race)


@pytest.fixture(scope="module")
def frozen_run(frozen: list[Row]) -> Run:
    return Run(frozen)


@pytest.fixture(scope="module")
def reset_run(reset: list[Row]) -> Run:
    return Run(reset)


def _increments(rows: list[Row]) -> list[int]:
    """Row indexes where the lap counter increments with the car on track."""
    return [
        i
        for i in range(1, len(rows))
        if rows[i][1]["lap_count"] == rows[i - 1][1]["lap_count"] + 1 and rows[i][1]["flags"] & P.Flags.CAR_ON_TRACK
    ]


def _driving(rows: list[Row]) -> list[dict[str, Any]]:
    """Fields of the packets with the car on track and nothing loading."""
    return [
        f for _, f, _ in rows if f["flags"] & P.Flags.CAR_ON_TRACK and not f["flags"] & P.Flags.LOADING_OR_PROCESSING
    ]


# ------------------------------------------------------------------------------------------------ the wire
@pytest.mark.parametrize("name", ["race", "frozen", "reset"])
def test_every_packet_is_variant_c_and_nothing_is_rejected(name: str, request: pytest.FixtureRequest) -> None:
    rows: list[Row] = request.getfixturevalue(name)
    run: Run = request.getfixturevalue(f"{name}_run")
    assert {len(p.data) for p, _, _ in rows} == {368}  # variant C: game >= 1.68 (gt7-protocol.md section 2)
    assert {p.src_port for p, _, _ in rows} == {P.RECEIVE_PORT}
    st = run.adapter.stats
    assert st.packets == len(rows) and st.rejected == 0 and st.errors == 0, st.last_error
    assert st.by_type["variant_C"] == len(rows)
    ids = [f["packet_id"] for _, f, _ in rows]
    gaps = [b - a for a, b in itertools.pairwise(ids) if b - a != 1]
    assert gaps == ([6236] if name == "reset" else [])  # +1 per packet; the reset excerpt's one gap is its cut
    for _, f, _ in rows:
        assert f["reserved"] == bytes(32)  # 0xD4..0xF3 unset: the synthetic marker can never collide
        assert f["water_temp"] == 85.0 and f["oil_temp"] == 110.0  # not simulated (doc section 4)


def test_field_values_and_relations_on_the_oval(race: list[Row]) -> None:
    drv = _driving(race)
    assert len(drv) > 4500
    speed = [f["speed"] for f in drv]
    vmag = [math.hypot(*f["velocity"]) for f in drv]
    assert min(speed) > 22.0 and max(speed) < 51.0  # m/s (a rolling start: never below 22 m/s on track)
    # 0x4C is never above the velocity magnitude (it drops below it while sliding: not the path speed)
    assert all(s <= m * 1.001 + 1e-6 for s, m in zip(speed, vmag, strict=True))
    assert all(abs(math.sqrt(sum(x * x for x in f["rotation"])) - 1.0) < 1e-3 for f in drv)  # a unit quaternion
    assert {(f["fuel_level"], f["fuel_capacity"]) for f in drv} == {(100.0, 100.0)}  # no fuel used: unit unsettled
    temps = [t for f in drv for t in f["tyre_surface_temp"]]
    assert min(temps) >= 37.0 and max(temps) <= 196.0
    assert max(f["engine_rpm"] for f in drv) < 8_870 and {f["rev_alert_max_rpm"] for f in drv} == {10_000}
    assert {f["gears"] & 0x0F for f in drv} <= {2, 3, 4} and {f["gears"] >> 4 for f in drv} <= {4, 15}
    assert {f["car_code"] for _, f, _ in race} == {919}
    assert {(f["surface_type"], f["car_category"]) for f in drv} == {(b"TTTT", b"GRN\x00")}
    # throttle: 0x91 is below the pedal (0x13C) on every packet where TCS intervenes - 0x91 is the throttle after TCS
    tcs = [f for f in drv if f["flags"] & P.Flags.TCS_ACTIVE]
    assert len(tcs) > 2000 and all(f["throttle"] < f["throttle_alt"] for f in tcs)
    # race position (0x84) during the race: within 1..14 (0x86 = the field), moving one place at a time
    racing = [f for f in drv if f["lap_count"] >= 1]
    assert {f["num_cars_pre_race"] for f in racing} == {14}
    pos = [f["pre_race_position"] for f in racing]
    assert all(1 <= p <= 14 for p in pos) and all(abs(b - a) <= 1 for a, b in itertools.pairwise(pos))


def test_frames_carry_the_pedal_the_reverse_gear_and_the_road_wheel_steering_sign(
    race: list[Row], race_run: Run, reset: list[Row], reset_run: Run
) -> None:
    by_id = {f["packet_id"]: f for _, f, _ in race}
    for fr in race_run.frames:
        assert fr.throttle == pytest.approx(by_id[fr.frame_id]["throttle_alt"] / 255)  # the pedal (0x13C)
    a = race_run.adapter
    assert a.steering_sign == -1.0 and a._steer_agree > 1000 and a._steer_disagree == 0  # 0x128 left positive
    # gear nibble 0 decodes as reverse (Kaitai; 15 = neutral never appears on a real capture)
    raw0 = {f["packet_id"] for _, f, _ in reset if f["gears"] & 0x0F == 0}
    assert raw0 and {fr.gear for fr in reset_run.frames if fr.frame_id in raw0} == {-1}
    assert all(f["gears"] & 0x0F != 15 for rows in (race, reset) for _, f, _ in rows)


# ------------------------------------------------------------------------------------------------ lap timing
def test_lap_times_are_the_games_own_and_the_tick_clock_agrees(race: list[Row], race_run: Run) -> None:
    inc = _increments(race)
    assert [race[i][1]["lap_count"] for i in inc] == [1, 2, 3, 4]
    comps = [e for _, e in race_run.items(LapCompletion)]
    assert [(c.lap_number, c.lap_time_ms) for c in comps] == sorted(RACE_LAPS_MS.items())
    for c, i in zip(comps, inc[1:], strict=True):
        f = race[i][1]
        assert f["last_lap_ms"] == c.lap_time_ms  # updated in the very packet of the increment
        assert 0 <= c.lap_time_ms - race[i - 1][1]["current_lap_ms"] <= TICK_MS  # 0x15C one tick before the line
        assert f["best_lap_ms"] == min(ms for n, ms in RACE_LAPS_MS.items() if n <= c.lap_number)
    # game time = packets / 60: flying laps within 10 ms; race lap 1 also counts the timer's run to the line
    ticks = [race[b][1]["packet_id"] - race[a][1]["packet_id"] for a, b in itertools.pairwise(inc)]
    start_timer = race[inc[0]][1]["current_lap_ms"]
    assert 150 <= start_timer <= 383  # the lap-1 timer started before the line (rolling start)
    assert abs(ticks[0] * TICK_MS + start_timer - RACE_LAPS_MS[1]) <= 20
    assert all(abs(t * TICK_MS - RACE_LAPS_MS[n]) <= 10 for n, t in ((2, ticks[1]), (3, ticks[2])))


def test_race_lap_1_is_anchored_at_the_start_and_flagged_and_laps_2_3_are_clean(race: list[Row], race_run: Run) -> None:
    comps = {c.lap_number: c for _, c in race_run.items(LapCompletion)}
    assert comps[1].race_start is True and comps[1].valid is None and comps[1].untraced is False
    assert all(comps[n].race_start is None and comps[n].valid is None for n in (2, 3))
    start = race[_increments(race)[0]][1]
    assert math.hypot(*start["velocity"]) > 25.0  # the 0 -> 1 increment came at speed: a rolling start
    lap1, lap2, lap3 = (race_run.lap(n) for n in (1, 2, 3))
    assert lap1.lap_time_ms == RACE_LAPS_MS[1] and LapFlag.RACE_START in lap1.flags and not lap1.clean
    assert lap1.channels["distance_m"][0] < 1.0  # anchored at the increment
    for lap in (lap2, lap3):
        assert lap.clean and lap.lap_time_ms == RACE_LAPS_MS[lap.lap_number], lap.flags
    assert LapFlag.INCOMPLETE in race_run.lap(4).flags  # cut by the excerpt's end


def test_lap_distance_follows_the_position_path(race_run: Run) -> None:
    """Integrated velocity magnitude vs the 3D path of the same frames: within 0.25 % on every anchored lap (the
    speed field would have lost 0.3-0.6 % on these laps)."""
    by_lap: dict[int, list[CarFrame]] = {}
    for fr in race_run.frames:
        if fr.lap_distance_m is not None and fr.lap_number and not fr.quality & FrameQuality.PAUSED:
            by_lap.setdefault(fr.lap_number, []).append(fr)
    for n in (1, 2, 3):
        fr = by_lap[n]
        path = sum(
            math.dist(
                (a.pos_x_m or 0, a.pos_y_m or 0, a.pos_z_m or 0), (b.pos_x_m or 0, b.pos_y_m or 0, b.pos_z_m or 0)
            )
            for a, b in itertools.pairwise(fr)
        )
        integrated = (fr[-1].lap_distance_m or 0.0) - (fr[0].lap_distance_m or 0.0)
        assert abs(integrated - path) / path < 0.0025, (n, integrated, path)
        assert 900.0 < path < 940.0


# ------------------------------------------------------------------------------------------------ sessions
def test_the_race_is_one_session_opened_after_the_load(race: list[Row], race_run: Run) -> None:
    st = race_run.adapter.stats.by_type
    assert st["sessions"] == 1 and st["loading"] == 28 and race_run.ended == []
    uids = {e.session_uid for _, e in race_run.items(SessionInfo)}
    first_load = next(i for i, (_, f, _) in enumerate(race) if f["flags"] & P.Flags.LOADING_OR_PROCESSING)
    last_load = max(i for i, (_, f, _) in enumerate(race) if f["flags"] & P.Flags.LOADING_OR_PROCESSING)
    assert first_load == 5 and last_load == first_load + 27  # 5 packets of the menus' background, then the load
    i_open = last_load + OPEN_TICKS  # the session opens at the OPEN_TICKS-th live packet after the load
    assert uids == {f"gt7:{race[i_open][0].t_recv_ns}"} and race_run.order[0][0] == i_open
    assert st["no_session"] == first_load + OPEN_TICKS - 1


def test_leaving_the_race_freezes_the_stream_and_ends_the_session(frozen: list[Row], frozen_run: Run) -> None:
    paused = [i for i, (_, f, _) in enumerate(frozen) if f["flags"] & P.Flags.PAUSED]
    assert len(paused) == 260 and paused == list(range(paused[0], paused[-1] + 1))  # one 4.3 s pause
    after = frozen[paused[-1] + 1 :]
    # the frozen stream: CarOnTrack set, not paused, 45.9 m/s, nothing but the packet id (and nonce) changing - and the
    # same state as the pause (the signature ignores the paused bit)
    assert len(after) > STALL_END_TICKS
    assert {s for _, _, s in after} == {frozen[paused[-1]][2]}
    assert all(f["flags"] & P.Flags.CAR_ON_TRACK and not f["flags"] & P.Flags.PAUSED for _, f, _ in after)
    assert {round(f["speed"], 1) for _, f, _ in after} == {45.9}
    run = frozen_run
    assert run.ended == ["frozen"] and run.adapter.stats.by_type["frozen"] == STALL_END_TICKS - 1
    i_end = next(i for i, e in run.items(GameEvent))
    assert i_end == paused[-1] + STALL_END_TICKS  # after 2 s of it
    assert run.adapter.session_uid is None and len({e.session_uid for _, e in run.items(SessionInfo)}) == 1
    frames = run.frames
    assert all(fr.frame_id <= frozen[paused[-1]][1]["packet_id"] for fr in frames)  # nothing after the pause
    lap5 = [fr for fr in frames if fr.lap_number == 5 and fr.lap_distance_m is not None]
    at_pause = next(fr for fr in lap5 if fr.quality & FrameQuality.PAUSED)
    assert lap5[-1].lap_distance_m == at_pause.lap_distance_m  # the frozen stream was never integrated
    assert 60.0 < (at_pause.lap_distance_m or 0.0) < 100.0
    # lap 4 ended at the line inside the excerpt: the game's time, stored without a trace (the session opened mid-lap)
    (c4,) = [e for _, e in run.items(LapCompletion)]
    inc = _increments(frozen)
    assert c4.lap_number == 4 and c4.lap_time_ms == frozen[inc[0]][1]["last_lap_ms"] == 23_482 and c4.untraced
    lap4 = run.lap(4)
    assert lap4.n == 0 and {LapFlag.NO_TRACE, LapFlag.INCOMPLETE} <= lap4.flags and not lap4.clean
    assert LapFlag.INCOMPLETE in run.lap(5).flags  # left mid-lap


def test_a_car_reset_is_a_teleport_inside_the_session(reset: list[Row], reset_run: Run) -> None:
    loading = [i for i, (_, f, _) in enumerate(reset) if f["flags"] & P.Flags.LOADING_OR_PROCESSING]
    assert len(loading) == 1  # the reset is a 1-packet loading pulse...
    i = loading[0]
    before, pulse, after = reset[i - 1][1], reset[i][1], reset[i + 1][1]
    assert pulse["flags"] & P.Flags.CAR_ON_TRACK  # ...with the car on track throughout
    assert all(f["flags"] & P.Flags.CAR_ON_TRACK for f in (before, after))
    assert {(f["car_code"], f["lap_count"], f["total_laps"]) for f in (before, pulse, after)} == {(1370, 1, 2)}
    assert 0 < after["current_lap_ms"] - before["current_lap_ms"] <= 2 * TICK_MS  # the lap timer runs on
    assert 25.0 < math.dist(before["position"], after["position"]) < 70.0  # put back on track
    run = reset_run
    st = run.adapter.stats.by_type
    assert st["car_reset"] == 1 and st["sessions"] == 1 and run.ended == []
    pid_after = after["packet_id"]
    inc = _increments(reset)
    assert len(inc) == 1 and reset[inc[0]][1]["lap_count"] == 2
    # after the reset the lap is not on the track any more (its distance is unknown) until the line
    lap1_after = [fr for fr in run.frames if fr.lap_number == 1 and fr.frame_id >= pid_after]
    assert lap1_after and all(fr.lap_distance_m is None for fr in lap1_after)
    lap2 = [fr for fr in run.frames if fr.lap_number == 2]
    assert lap2[0].lap_distance_m is not None and lap2[0].lap_distance_m < 1.0
    (c1,) = [e for _, e in run.items(LapCompletion)]
    assert c1.lap_number == 1 and c1.lap_time_ms == reset[inc[0]][1]["last_lap_ms"] == 125_838
    assert {fr.race_position for fr in run.frames} <= set(range(1, 9))  # 0x84 within the 8-car field


# ------------------------------------------------------------------------------------------------ track identity
def test_the_oval_is_learned_with_the_id_of_the_live_run(race_run: Run) -> None:
    infos = race_run.items(SessionInfo)
    i_track = next(i for i, e in race_run.order if isinstance(e, SessionInfo) and e.track_id)
    i_comp3 = next(i for i, e in race_run.order if isinstance(e, LapCompletion) and e.lap_number == 3)
    assert i_track == i_comp3  # learned at lap 3's line: laps 2 and 3 agree (lap 1, 932 m, did not agree with lap 2)
    last = infos[-1][1]
    assert last.track_id == OVAL_ID and race_run.adapter.known_track_ids == [OVAL_ID]
    assert last.track_length_m == pytest.approx(914.7, abs=0.1)  # this session's lap 2, measured
    sig = TrackSignature.parse(OVAL_ID)
    assert sig is not None and sig.turn_deg == 340  # one loop of a banked oval, less the dead band
    assert last.extra["track_id_derived"] is True


def test_a_known_oval_is_identified_from_race_lap_1(race: list[Row]) -> None:
    run = Run(race, known=[OVAL_ID])
    i_track = next(i for i, e in run.order if isinstance(e, SessionInfo) and e.track_id)
    i_comp1 = next(i for i, e in run.order if isinstance(e, LapCompletion) and e.lap_number == 1)
    assert i_track == i_comp1 and {e.track_id for _, e in run.items(SessionInfo) if e.track_id} == {OVAL_ID}
    assert run.adapter.known_track_ids == [OVAL_ID]  # nothing new learned


# ------------------------------------------------------------------------------------------------ end to end
def test_end_to_end_one_listed_session_with_the_games_lap_times(tmp_path: Path) -> None:
    """Both oval excerpts through the router, the session manager and the database, as the live service runs them."""
    from pitwall.config import Settings
    from pitwall.core.runtime import Runtime
    from pitwall.core.session import SessionManager
    from pitwall.ingest.router import PacketRouter
    from pitwall.storage import repo

    rt = Runtime(Settings(data_dir=tmp_path / "data", llm_enabled=False, voice_enabled=False))
    try:
        for path in (RACE, FROZEN):
            sessions = SessionManager(rt.writer, rt.live, rt.worker, source=f"replay:{path.name}")
            router = PacketRouter([GT7Adapter(known_track_ids=[OVAL_ID])], sessions, rt.live)
            for p in CaptureReader(path):
                router.handle(p)
            router.finish()
        rt.worker.join()
        rt.writer.flush()
        with rt.db.read() as c:
            rows = repo.list_sessions(c, 10)
            assert len(rows) == 2 == len(repo.list_sessions(c, 10, include_empty=True))
            race_row = next(r for r in rows if r["source"] == f"replay:{RACE.name}")
            assert race_row["track_id"] == OVAL_ID and race_row["car_id"] == "gt7:car:919"
            laps = {lap["lap_number"]: lap for lap in repo.list_laps(c, race_row["id"])}
            assert {n: laps[n]["lap_time_ms"] for n in (1, 2, 3)} == RACE_LAPS_MS
            assert [n for n, lap in sorted(laps.items()) if lap["clean"]] == [2, 3]
            assert "race_start" in laps[1]["flags"]
            frozen_row = next(r for r in rows if r["source"] == f"replay:{FROZEN.name}")
            events = repo.list_events(c, frozen_row["id"])
            assert [(e["kind"], e["code"]) for e in events] == [("session_ended", "frozen")]
            flaps = {lap["lap_number"]: lap for lap in repo.list_laps(c, frozen_row["id"])}
            assert flaps[4]["lap_time_ms"] == 23_482 and flaps[4]["n_samples"] == 0 and "no_trace" in flaps[4]["flags"]
            assert repo.load_lap_trace(c, flaps[4]["id"]) is None  # no trace to analyse
        assert rt.worker.errors == 0 and rt.writer.errors == 0
    finally:
        rt.close()


def test_session_counts_in_the_excerpts() -> None:
    """One session per excerpt, whatever the menus, loading screens, pauses and resets around it."""
    counts = Counter[str]()
    for path in (RACE, FROZEN, RESET):
        run = Run(_rows(path))
        counts[path.name] = run.adapter.stats.by_type["sessions"]
    assert set(counts.values()) == {1}
