"""ACC shared-memory reader (``ingest/acc_shm_reader.py``): open-only, change-gated, capture and replay.

Every test here runs on any OS: the pages are ``pitwall.sim.acc_stream.FakeAccMemory`` (Windows' lifetime rule: a
mapping lives while the game or an open view holds it) behind the reader's injected opener, and ``poll()`` runs one
step on a fake clock. SYNTHETIC tier only - no real ACC page is involved; the one test that creates real named
mappings runs only on Windows (bottom of the file).
"""

from __future__ import annotations

import importlib.util
import math
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pitwall.adapters.acc import packets as P
from pitwall.adapters.acc.adapter import AccAdapter
from pitwall.ingest import acc_shm_reader as R
from pitwall.ingest.acc_shm_reader import (
    AccPageGate,
    AccReaderState,
    AccSharedMemoryReader,
    AccUnavailable,
    describe,
    probe_pages,
    without_player_names,
)
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID
from pitwall.model.telemetry import CarFrame, EventKind, GameEvent, LapCompletion, SessionInfo
from pitwall.sim.acc_stream import (
    AccPauseSpec,
    AccScenario,
    FakeAccMemory,
    acc_page_timeline,
    gate_states,
    generate_acc_session,
    static_body,
    write_acc_capture,
)
from pitwall.sim.track import pitwall_park

ROOT = Path(__file__).resolve().parents[2]
LIVE = int(P.AccStatus.LIVE)
OFF = int(P.AccStatus.OFF)
PAUSE = int(P.AccStatus.PAUSE)
REPLAY = int(P.AccStatus.REPLAY)
SHORT = AccScenario(flying_laps=1, outlap_fraction=0.2, menu_s=0.2, cooldown_s=0.5)


def physics(pid: int, **kw: Any) -> bytes:
    return P.PHYSICS.pack({"packetId": pid, "speedKmh": 120.0, "gas": 1.0, "gear": 5, **kw})


def graphics(pid: int, status: int = LIVE, **kw: Any) -> bytes:
    return P.GRAPHICS.pack({"packetId": pid, "status": status, **kw})


def static(track: str = "spa", car: str = "mclaren_720s_gt3", **kw: Any) -> bytes:
    return P.STATIC.pack(
        {"carModel": P.encode_wstring(car, 33), "track": P.encode_wstring(track, 33), "sectorCount": 3, **kw}
    )


def tags(snaps: list[bytes]) -> list[bytes]:
    return [s[: P.TAG_SIZE] for s in snaps]


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class Rig:
    """A reader on a fake memory and a fake clock, collecting what it forwards."""

    def __init__(self, mem: FakeAccMemory | None = None, **kw: Any) -> None:
        self.mem = mem or FakeAccMemory()
        self.clock = Clock()
        self.got: list[CapturedPacket] = []
        self.idle = 0
        kw.setdefault("on_idle", self._on_idle)
        self.reader = AccSharedMemoryReader(self.got.append, opener=self.mem.opener, clock=self.clock, **kw)

    def _on_idle(self) -> None:
        self.idle += 1

    def poll(self, n: int = 1, dt: float = R.POLL_S) -> int:
        sent = 0
        for _ in range(n):
            sent += self.reader.poll()
            self.clock.advance(dt)
        return sent

    def drive(self, n: int, start_pid: int, **graphics_kw: Any) -> None:
        """``n`` ticks on track: both pages step, one poll each."""
        for i in range(n):
            self.mem.write(physics(start_pid + i), graphics(start_pid + i, **graphics_kw))
            self.poll()


# ============================================================================================== gate (pure)
def test_first_copy_is_only_a_baseline() -> None:
    """Pages left by a game that crashed on track (status LIVE, nothing moving) never produce a snapshot."""
    gate = AccPageGate()
    assert gate.offer(physics(5), graphics(9), static()) == []
    for _ in range(100):
        assert gate.offer(physics(5), graphics(9), static()) == []
    assert gate.changes == 0


def test_on_track_sends_static_then_graphics_then_physics_and_static_once() -> None:
    gate = AccPageGate()
    gate.offer(physics(1), graphics(1, OFF), bytes(P.STATIC.size))
    out = gate.offer(physics(2), graphics(2), static())
    assert tags(out) == [P.TAG_STATIC, P.TAG_GRAPHICS, P.TAG_PHYSICS]
    assert [len(s) for s in out] == [P.STATIC_PAGE.snapshot_size, P.GRAPHICS_PAGE.snapshot_size, 804]
    assert tags(gate.offer(physics(3), graphics(3), static())) == [P.TAG_GRAPHICS, P.TAG_PHYSICS]
    assert tags(gate.offer(physics(4), graphics(3), static())) == [P.TAG_PHYSICS]  # only Physics moved
    assert gate.offer(physics(4), graphics(3), static()) == []  # nothing moved
    assert tags(gate.offer(physics(4), graphics(4), static("monza"))) == [P.TAG_STATIC, P.TAG_GRAPHICS]  # new track


def test_menus_pause_and_replay_send_one_transition_page_each() -> None:
    gate = AccPageGate()
    gate.offer(physics(1), graphics(1, OFF), static())
    for pid in range(2, 50):  # the menus: Graphics steps (rendered), Physics too - neither is sent
        assert gate.offer(physics(pid), graphics(pid, OFF), static()) == []
    assert tags(gate.offer(physics(50), graphics(50), static())) == [P.TAG_STATIC, P.TAG_GRAPHICS, P.TAG_PHYSICS]
    out = gate.offer(physics(50), graphics(51, PAUSE), static())  # pause: the transition only
    assert tags(out) == [P.TAG_GRAPHICS] and R.graphics_status(out[0][P.TAG_SIZE :]) == PAUSE
    for pid in range(52, 80):  # paused: Graphics keeps stepping, Physics too (undocumented): nothing
        assert gate.offer(physics(pid), graphics(pid, PAUSE), static()) == []
    assert tags(gate.offer(physics(80), graphics(80), static())) == [P.TAG_GRAPHICS, P.TAG_PHYSICS]
    assert tags(gate.offer(physics(81), graphics(81, REPLAY), static())) == [P.TAG_GRAPHICS]
    assert gate.offer(physics(82), graphics(82, REPLAY), static()) == []
    assert tags(gate.offer(physics(83), graphics(83, OFF), static())) == [P.TAG_GRAPHICS]  # back to the menus
    for pid in range(84, 120):
        assert gate.offer(physics(pid), graphics(pid, OFF), static()) == []


def test_a_status_change_without_a_new_packet_id_is_a_change() -> None:
    gate = AccPageGate()
    gate.offer(physics(1), graphics(1), static())
    gate.offer(physics(2), graphics(2), static())
    assert tags(gate.offer(physics(2), graphics(2, PAUSE), static())) == [P.TAG_GRAPHICS]


def test_a_paused_start_sends_nothing_until_the_game_runs() -> None:
    """Pitwall started while ACC sat paused (or in a replay): no transition was ever sent, so nothing is."""
    gate = AccPageGate()
    gate.offer(physics(1), graphics(1, PAUSE), static())
    for pid in range(2, 30):
        assert gate.offer(physics(1), graphics(pid, PAUSE), static()) == []
        assert gate.offer(physics(1), graphics(pid, REPLAY), static()) == []
    assert tags(gate.offer(physics(2), graphics(40), static())) == [P.TAG_STATIC, P.TAG_GRAPHICS, P.TAG_PHYSICS]


def test_zero_static_is_never_sent_and_a_real_one_waits_for_the_track() -> None:
    gate = AccPageGate()
    gate.offer(physics(1), graphics(1, OFF), bytes(P.STATIC.size))
    assert gate.offer(physics(1), graphics(2, OFF), static()) == []  # filled in the menus: not sent yet
    out = gate.offer(physics(2), graphics(3), bytes(P.STATIC.size))  # zeroed meanwhile: the last real one is sent
    assert tags(out) == [P.TAG_STATIC, P.TAG_GRAPHICS, P.TAG_PHYSICS]
    assert out[0][P.TAG_SIZE :] == static()


def test_player_names_are_zeroed_and_nothing_else_changes() -> None:
    named = static(
        playerName=P.encode_wstring("Edward", 33),
        playerSurname=P.encode_wstring("Example", 33),
        playerNick=P.encode_wstring("EdX", 33),
    )
    clean = without_player_names(named)
    assert clean == static()  # exactly the page without the three names
    assert b"E\x00d\x00w" not in clean and len(clean) == P.STATIC.size
    gate = AccPageGate()
    gate.offer(physics(1), graphics(1, OFF), named)
    out = gate.offer(physics(2), graphics(2), named)
    assert out[0][P.TAG_SIZE :] == clean
    parsed = P.STATIC.unpack_from(out[0], P.TAG_SIZE)
    assert {parsed[f] for f in R.PRIVATE_STATIC_FIELDS} == {bytes(66)}
    assert P.decode_wstring(parsed["track"]) == "spa" and P.decode_wstring(parsed["carModel"]) == "mclaren_720s_gt3"


def test_rearm_resends_static_and_needs_a_live_page() -> None:
    gate = AccPageGate()
    gate.offer(physics(1), graphics(1, OFF), static())
    gate.offer(physics(2), graphics(2), static())
    gate.offer(physics(3), graphics(3, PAUSE), static())
    gate.rearm()  # the session ended while paused (idle timeout)
    assert gate.offer(physics(3), graphics(4, OFF), static()) == []  # no transition after a re-arm
    assert tags(gate.offer(physics(4), graphics(5), static())) == [P.TAG_STATIC, P.TAG_GRAPHICS, P.TAG_PHYSICS]


def test_status_words_and_sentences() -> None:
    assert [R.status_word(s) for s in (OFF, REPLAY, LIVE, PAUSE, 9, None)] == [
        "off",
        "replay",
        "live",
        "pause",
        "off",
        None,
    ]
    assert "not running" in describe("not_running")
    assert "paused" in describe("waiting", "pause")
    assert "replay" in describe("waiting", "replay")
    assert "not on track" in describe("waiting", "off")
    assert "another app" in describe("waiting", "live")
    assert describe("reading", rate=59.6).startswith("Reading ACC on ") and "60 pages/s" in describe(
        "reading", rate=59.6
    )
    assert "administrator" in describe("error", last_error="PermissionError: [Errno 5] access denied opening x")
    assert "Windows PC" in describe("not_windows") and "Setup › Game" in describe("off")


# ============================================================================================== reader
def test_closed_game_sends_nothing_and_no_page_is_ever_created() -> None:
    rig = Rig()
    assert rig.poll(300) == 0
    assert rig.reader.state is AccReaderState.NOT_RUNNING and not rig.reader.pages_open
    assert not any(rig.mem.exists(p.mapping) for p in P.PAGES)  # open-only: nothing appeared under ACC's names
    # one look every RETRY_S (300 polls of 1/60 s = 5 s): 3 attempts, each stopping at the first missing page
    assert rig.mem.open_calls == [P.PHYSICS_MAPPING] * 3
    snap = rig.reader.snapshot()
    assert snap["state"] == "not_running" and snap["received"] == 0 and snap["acc_status"] is None
    assert rig.got == [] and rig.idle == 0


def test_menus_waiting_then_reading_on_track() -> None:
    rig = Rig()
    rig.mem.start_game()
    rig.poll(2 * 60 // 4)  # finds the pages within RETRY_S
    assert rig.reader.pages_open and rig.reader.state is AccReaderState.WAITING
    for pid in range(1, 120):  # the menus: Graphics steps with status OFF, Static not filled in yet
        rig.mem.write(physics(0), graphics(pid, OFF))
        rig.poll()
    assert rig.got == [] and rig.reader.snapshot()["acc_status"] == "off"
    rig.mem.write(static=static())
    rig.drive(90, 1000)
    snap = rig.reader.snapshot()
    assert snap["state"] == "reading" and snap["acc_status"] == "live"
    assert snap["by_page"] == {"physics": 90, "graphics": 90, "static": 1} and snap["received"] == 181
    assert rig.got[0].data[: P.TAG_SIZE] == P.TAG_STATIC and {p.src_port for p in rig.got} == {R.NO_PORT}
    assert all(P.page_of(p.data) is not None for p in rig.got)
    assert snap["rate"] > 0 and snap["last_rx_s_ago"] == 0.0


def test_pause_is_one_page_then_waiting() -> None:
    rig = Rig()
    rig.mem.start_game()
    rig.mem.write(physics(1), graphics(1, OFF), static())
    rig.poll()
    rig.drive(10, 2)
    n = len(rig.got)
    for pid in range(20, 400):  # 6 s paused: Graphics keeps stepping, Physics frozen
        rig.mem.write(graphics=graphics(pid, PAUSE))
        rig.poll()
    assert len(rig.got) == n + 1 and R.graphics_status(rig.got[-1].data[P.TAG_SIZE :]) == PAUSE
    assert rig.reader.state is AccReaderState.WAITING and "paused" in rig.reader.snapshot()["message"]


def test_game_closed_under_our_views_is_found_by_the_release_probe() -> None:
    """A held view keeps ACC's mapping alive after the game quits; the quiet spell releases it and the reader sees
    that ACC has gone - and the pages are gone too: the reader never kept them alive for long, never re-created them."""
    rig = Rig()
    rig.mem.start_game()
    rig.mem.write(physics(1), graphics(1, OFF), static())
    rig.poll()
    rig.drive(30, 2)
    rig.mem.quit_game()
    assert rig.mem.exists(P.PHYSICS_MAPPING)  # still held by our views
    sent = rig.poll(round(R.RELEASE_AFTER_S * 60) + 5)
    assert sent == 0  # frozen pages: nothing new
    assert rig.reader.state is AccReaderState.NOT_RUNNING and rig.reader.releases == 1
    assert not any(rig.mem.exists(p.mapping) for p in P.PAGES) and rig.mem.views_open == 0
    assert "not running" in rig.reader.snapshot()["message"]


def test_another_app_holding_the_pages_keeps_them_waiting() -> None:
    rig = Rig()
    rig.mem.start_game()
    simhub = rig.mem.opener(P.GRAPHICS_MAPPING, P.GRAPHICS_PAGE.size)  # another tool's view
    assert simhub is not None
    rig.mem.write(physics(1), graphics(1, OFF), static())
    rig.poll()
    rig.drive(5, 2)
    rig.mem.quit_game()
    rig.poll(round(R.RELEASE_AFTER_S * 60) + 5)
    # physics/static vanished with our views, graphics is kept by the other app: not all three pages -> not running
    assert rig.reader.state is AccReaderState.NOT_RUNNING
    simhub.close()
    assert not rig.mem.exists(P.GRAPHICS_MAPPING)


def test_access_denied_is_an_error_with_a_fix_and_retries() -> None:
    mem = FakeAccMemory()
    mem.start_game()
    mem.denied = True
    rig = Rig(mem)
    rig.poll(10)
    snap = rig.reader.snapshot()
    assert snap["state"] == "error" and "administrator" in snap["message"] and "access denied" in snap["last_error"]
    calls = len(mem.open_calls)
    rig.poll(60)  # 1 s: no retry yet
    assert len(mem.open_calls) == calls
    mem.denied = False
    rig.poll(120)
    assert rig.reader.pages_open and rig.reader.state is AccReaderState.WAITING and rig.reader.last_error is None


def test_handler_errors_are_counted_never_raised() -> None:
    mem = FakeAccMemory()
    mem.start_game()
    calls: list[int] = []

    def boom(pkt: CapturedPacket) -> None:
        calls.append(1)
        raise RuntimeError("router bug")

    clock = Clock()
    reader = AccSharedMemoryReader(boom, opener=mem.opener, clock=clock)
    mem.write(physics(1), graphics(1, OFF), static())
    reader.poll()
    for pid in range(2, 6):
        mem.write(physics(pid), graphics(pid))
        clock.advance(R.POLL_S)
        reader.poll()
    assert reader.handler_errors == len(calls) == 9 and reader.received == 9


class _TornView:
    """A view whose packetId moves while it is being copied (ACC writing during the copy)."""

    def __init__(self, inner: R.PageView, moves: int) -> None:
        self.inner, self.moves, self.reads = inner, moves, 0

    def read(self, offset: int = 0, size: int | None = None) -> bytes:
        self.reads += 1
        data = self.inner.read(offset, size)
        if offset == R.PACKET_ID_OFFSET and size == 4 and self.moves > 0:
            self.moves -= 1
            return (int.from_bytes(data, "little", signed=True) + 1).to_bytes(4, "little", signed=True)
        return data

    def close(self) -> None:
        self.inner.close()


@pytest.mark.parametrize(("moves", "sent"), [(1, True), (R.TORN_RETRIES + 1, False)])
def test_torn_copies_are_copied_again_or_skipped(moves: int, sent: bool) -> None:
    mem = FakeAccMemory()
    mem.start_game()
    torn: dict[str, _TornView] = {}

    def opener(name: str, size: int) -> R.PageView | None:
        view = mem.opener(name, size)
        if view is not None and name == P.PHYSICS_MAPPING:
            torn["v"] = _TornView(view, 0)
            return torn["v"]
        return view

    got: list[CapturedPacket] = []
    reader = AccSharedMemoryReader(got.append, opener=opener, clock=Clock())
    mem.write(physics(1), graphics(1, OFF), static())
    reader.poll()
    mem.write(physics(2), graphics(2))
    torn["v"].moves = moves
    reader.poll()
    assert (P.TAG_PHYSICS in tags([p.data for p in got])) is sent
    assert reader.torn_reads == min(moves, R.TORN_RETRIES + 1)


def test_idle_ends_the_session_closes_the_capture_and_rearms(tmp_path: Path) -> None:
    rig = Rig(capture_dir=tmp_path, idle_timeout_s=5.0)
    rig.mem.start_game()
    rig.mem.write(physics(1), graphics(1, OFF), static(playerName=P.encode_wstring("Edward", 33)))
    rig.poll()
    rig.drive(30, 2)
    cap = rig.reader.capture
    assert cap is not None and rig.reader.snapshot()["capture"] == str(cap.path)
    for pid in range(40, 400):  # back in the menus for 6 s: the session ends after idle_timeout_s
        rig.mem.write(graphics=graphics(pid, OFF))
        rig.poll()
    assert rig.idle == 1 and rig.reader.capture is None
    (path,) = tmp_path.glob("*_acc.pwcap")  # closed with the session
    first = CaptureReader(path)
    assert first.meta.game_hint == R.CAPTURE_GAME_HINT == "acc-shm" and first.meta.source == "acc-shm"
    assert first.meta.extra["protocol"] == R.PROTOCOL and first.meta.extra["layout"].startswith("Kunos")
    data = [p.data for p in first]
    assert len(data) == 62 and data == [p.data for p in rig.got]  # Static + 30 x (Graphics, Physics) + the menus
    assert "Edward".encode("utf-16-le") not in b"".join(data)  # the player's name never reaches a capture
    rig.drive(3, 500)  # back on track: Static again (the adapter was reset by on_idle), a new capture file
    assert [p.data[: P.TAG_SIZE] for p in rig.got[62:]] == [P.TAG_STATIC] + [P.TAG_GRAPHICS, P.TAG_PHYSICS] * 3
    assert rig.reader.capture is not None
    rig.reader.stop()
    assert rig.reader.capture is None


@pytest.mark.parametrize("held", [PAUSE, REPLAY])
@pytest.mark.parametrize("stepping", [True, False])
def test_a_pause_or_replay_longer_than_the_idle_timeout_keeps_the_session(held: int, stepping: bool) -> None:
    """A paused single-player race (or a replay from the pause menu) for minutes is one session: the game is still
    running, so ``on_idle`` waits while the pages are open and say PAUSE / REPLAY (whether or not ACC keeps stepping
    ``packetId``). Back on track, the stream goes on without a new Static page or a new capture file."""
    rig = Rig(idle_timeout_s=5.0)
    rig.mem.start_game()
    rig.mem.write(physics(1), graphics(1, OFF), static())
    rig.poll()
    rig.drive(30, 2)
    rig.mem.write(graphics=graphics(40, held))
    rig.poll()
    for pid in range(41, 41 + 60 * 120):  # two minutes
        if stepping:
            rig.mem.write(graphics=graphics(pid, held))
        rig.poll()
    assert rig.idle == 0 and rig.reader.state is AccReaderState.WAITING
    n = len(rig.got)
    rig.drive(3, 9000)
    assert tags([p.data for p in rig.got[n:]]) == [P.TAG_GRAPHICS, P.TAG_PHYSICS] * 3  # same session, no Static


def test_a_paused_game_still_ends_its_session_when_it_quits_or_after_the_ceiling() -> None:
    rig = Rig(idle_timeout_s=5.0)
    rig.mem.start_game()
    rig.mem.write(physics(1), graphics(1, OFF), static())
    rig.poll()
    rig.drive(10, 2)
    rig.mem.write(graphics=graphics(20, PAUSE))
    rig.poll(60 * 8)
    assert rig.idle == 0
    rig.mem.quit_game()  # quits while paused: the release probe finds the pages gone, then the session ends
    rig.poll(round(R.RELEASE_AFTER_S * 60) + 5)
    assert rig.reader.state is AccReaderState.NOT_RUNNING and rig.idle == 1
    # left paused and forgotten (or another app keeps the pages, still saying PAUSE): the ceiling ends it
    rig = Rig(idle_timeout_s=5.0)
    rig.mem.start_game()
    rig.mem.write(physics(1), graphics(1, OFF), static())
    rig.poll()
    rig.drive(10, 2)
    rig.mem.write(graphics=graphics(20, PAUSE))
    rig.poll()
    rig.poll(1, dt=R.PAUSED_IDLE_S - 10.0)
    rig.poll()
    assert rig.idle == 0
    rig.poll(2, dt=20.0)
    assert rig.idle == 1


def test_stop_closes_every_view_and_the_thread() -> None:
    mem = FakeAccMemory()
    mem.start_game()
    reader = AccSharedMemoryReader(lambda _p: None, opener=mem.opener, poll_s=0.005)
    reader.start()
    deadline = time.monotonic() + 5
    while not reader.pages_open and time.monotonic() < deadline:
        time.sleep(0.01)
    assert reader.running and mem.views_open == 3
    reader.stop()
    assert not reader.running and mem.views_open == 0 and reader.state is AccReaderState.STOPPED
    assert reader.poll() == 0  # a stopped reader does nothing
    reader.stop()  # idempotent


def test_threaded_reader_forwards_a_live_stream() -> None:
    mem = FakeAccMemory()
    mem.start_game()
    got: list[CapturedPacket] = []
    lock = threading.Lock()

    def handler(p: CapturedPacket) -> None:
        with lock:
            got.append(p)

    reader = AccSharedMemoryReader(handler, opener=mem.opener, poll_s=0.002)
    mem.write(physics(1), graphics(1, OFF), static())
    reader.start()
    try:
        _wait(lambda: reader.polls > 3)
        for pid in range(2, 30):
            mem.write(physics(pid), graphics(pid))
            before = reader.polls
            _wait(lambda b=before: reader.polls > b + 1)
        _wait(lambda: reader.by_page["physics"] >= 28)
    finally:
        reader.stop()
    with lock:
        kinds = [P.page_of(p.data).kind for p in got]  # type: ignore[union-attr]
    assert kinds.count("static") == 1 and kinds.count("physics") == 28 and kinds.count("graphics") == 28


def _wait(cond: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.002)


class _CoarseEvent(threading.Event):
    """``Event.wait`` as on Windows: CPython waits on a lock with a millisecond kernel timeout that ends on the
    default 15.625 ms timer tick, so 1/60 s (17 ms) lasts two ticks (31.25 ms). ``time.sleep`` uses a
    high-resolution timer there since Python 3.11."""

    TICK_S = 1 / 64

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is None or self.is_set():
            return super().wait(timeout)
        return super().wait(math.ceil(timeout / self.TICK_S - 1e-9) * self.TICK_S)


def _poll_rate(reader: AccSharedMemoryReader, seconds: float = 1.5) -> float:
    reader.start()
    try:
        _wait(lambda: reader.pages_open)
        p0, t0 = reader.polls, time.monotonic()
        time.sleep(seconds)
        return (reader.polls - p0) / (time.monotonic() - t0)
    finally:
        reader.stop()


def test_the_reader_samples_at_60_hz_even_where_event_wait_is_coarse() -> None:
    """The poll loop keeps its own deadline and sleeps with ``time.sleep``, so a Windows-like ``Event.wait`` (the
    stop signal) cannot halve the documented 60 Hz to about 32 Hz."""
    mem = FakeAccMemory()
    mem.start_game()
    reader = AccSharedMemoryReader(lambda _p: None, opener=mem.opener)
    reader._stop = _CoarseEvent()
    rate = _poll_rate(reader)
    assert 48.0 <= rate <= 66.0, rate
    assert not reader.running and mem.views_open == 0  # stop still ends the thread and closes the views


@pytest.mark.skipif(sys.platform != "win32", reason="the real Windows timer: Windows CI only")
def test_windows_poll_rate_is_about_60_hz() -> None:  # pragma: no cover - Windows CI
    mem = FakeAccMemory()
    mem.start_game()
    rate = _poll_rate(AccSharedMemoryReader(lambda _p: None, opener=mem.opener), seconds=3.0)
    assert rate >= 50.0, rate


def test_bad_arguments_and_pages() -> None:
    mem = FakeAccMemory()
    with pytest.raises(ValueError, match="poll_s"):
        AccSharedMemoryReader(lambda _p: None, opener=mem.opener, poll_s=0)
    with pytest.raises(ValueError, match="pages"):
        AccSharedMemoryReader(lambda _p: None, opener=mem.opener, pages=(P.GRAPHICS_PAGE,))


@pytest.mark.skipif(sys.platform == "win32", reason="off Windows only")
def test_off_windows_there_is_no_reader_and_no_real_opener() -> None:
    assert not R.reader_supported()
    with pytest.raises(AccUnavailable, match="Windows PC"):
        AccSharedMemoryReader(lambda _p: None)
    with pytest.raises(AccUnavailable):
        R.open_windows_page(P.PHYSICS_MAPPING, P.PHYSICS_PAGE.size)
    assert probe_pages() == "unsupported"


def test_probe_pages_opens_read_only_and_closes() -> None:
    mem = FakeAccMemory()
    assert probe_pages(mem.opener) == "absent"
    mem.start_game()
    assert probe_pages(mem.opener) == "present" and mem.views_open == 0
    mem.denied = True
    assert probe_pages(mem.opener).startswith("denied")
    mem.denied = False
    held = mem.opener(P.STATIC_MAPPING, P.STATIC_PAGE.size)
    mem.quit_game()
    assert probe_pages(mem.opener) == "partial"
    assert held is not None
    held.close()
    assert probe_pages(mem.opener) == "absent" and not mem.exists(P.STATIC_MAPPING)


# ============================================================================================== generator
def test_generated_stream_is_exactly_what_the_reader_forwards() -> None:
    """The synthetic generator and the reader share the gate: the reader polling the generator's page timeline
    forwards byte for byte the snapshots ``generate_acc_session`` produces."""
    sc = AccScenario(flying_laps=1, outlap_fraction=0.2, menu_s=0.3, cooldown_s=0.5, pause=AccPauseSpec(5.0, 1.0))
    states, _truth = acc_page_timeline(sc)
    rig = Rig()
    rig.mem.start_game()
    for st in states:
        rig.mem.show(st)
        rig.poll()
    generated, _ = generate_acc_session(sc)
    assert [p.data for p in rig.got] == [p.data for p in generated] == [p.data for p in gate_states(states)]
    statuses = [R.graphics_status(p.data[P.TAG_SIZE :]) for p in generated if p.data[:4] == P.TAG_GRAPHICS]
    assert statuses[0] == LIVE and statuses.count(PAUSE) == 1 and statuses[-1] == OFF


def test_generated_session_decodes_with_its_ground_truth() -> None:
    sc = AccScenario(flying_laps=2, invalid_laps=frozenset({3}), menu_s=0.2, cooldown_s=0.5)
    packets, truth = generate_acc_session(sc)
    adapter = AccAdapter()
    out = [item for p in packets for item in adapter.decode(p.data, p.t_recv_ns)] + adapter.flush()
    assert adapter.stats.rejected == 0 and adapter.stats.errors == 0
    info = next(e for e in out if isinstance(e, SessionInfo))
    assert info.extra["track_length_source"] == "static_track_spline_length"
    assert info.track_length_m == pytest.approx(pitwall_park().length_m, rel=1e-6)
    assert info.session_uid == str(SYNTHETIC_SESSION_UID)  # Static names SYNTHETIC_CAR_MODEL
    laps = {c.lap_number: c for c in out if isinstance(c, LapCompletion)}
    assert sorted(laps) == [1, 2, 3]
    for n, ms in truth.lap_times_ms.items():
        assert laps[n].lap_time_ms == ms and laps[n].valid is truth.valid[n], n
    assert laps[3].valid is False and laps[2].valid is True
    frames = [f for f in out if isinstance(f, CarFrame)]
    assert len(frames) == truth.live_ticks  # every tick on track, none from the menus or the pause
    assert max(f.speed_kph or 0 for f in frames) > 100 and all(f.steering is not None for f in frames)
    ended = [e for e in out if isinstance(e, GameEvent) and e.kind is EventKind.SESSION_ENDED]
    assert [e.payload["reason"] for e in ended] == ["status_off"]


def test_static_body_names_the_synthetic_car_and_no_player() -> None:
    body = static_body(SHORT, pitwall_park())
    d = P.STATIC.unpack_from(body)
    assert P.decode_wstring(d["carModel"]) == P.SYNTHETIC_CAR_MODEL
    assert all(d[f] == bytes(66) for f in R.PRIVATE_STATIC_FIELDS)


def test_synthetic_capture_is_flagged_and_replays_into_a_stored_session(tmp_path: Path) -> None:
    from pitwall.config import Settings
    from pitwall.core.runtime import Runtime
    from pitwall.storage import repo

    path = tmp_path / "acc.pwcap"
    truth = write_acc_capture(path, AccScenario(flying_laps=2, menu_s=0.2, cooldown_s=0.5), name="acc-unit")
    meta = CaptureReader(path).meta
    assert meta.synthetic and meta.game_hint == "acc-shm" and "SYNTHETIC" in meta.description
    rt = Runtime(Settings(_env_file=None, data_dir=tmp_path / "d", llm_enabled=False))  # type: ignore[call-arg]
    try:
        rep = rt.start_replay(path, speed=None)
        assert rep.done.wait(60)
        sid = rt.live.session_id
        rt.worker.join()
        rt.writer.flush()
        with rt.db.read() as c:
            row = repo.get_session(c, sid) if sid else None
            laps = repo.list_laps(c, sid) if sid else []
    finally:
        rt.close()
    assert row is not None and row["game"] == "acc" and row["synthetic"] and row["platform"] == "pc"
    assert row["track_id"] == "synthetic:acc-unit"  # never pollutes a real ACC track
    timed = {lap["lap_number"]: lap["lap_time_ms"] for lap in laps}
    for n, ms in truth.lap_times_ms.items():
        assert timed[n] == ms, n


def test_replay_decodes_acc_only_from_acc_captures(tmp_path: Path) -> None:
    """A capture that does not carry the ACC hint never has ACC snapshots decoded (as with AC)."""
    from pitwall.config import Settings
    from pitwall.core.runtime import Runtime
    from pitwall.ingest.capture import CaptureMeta, write_capture

    packets, _ = generate_acc_session(SHORT)
    path = tmp_path / "other.pwcap"
    write_capture(path, packets, CaptureMeta(source="udp:20777", synthetic=True))
    rt = Runtime(Settings(_env_file=None, data_dir=tmp_path / "d", llm_enabled=False))  # type: ignore[call-arg]
    try:
        rep = rt.start_replay(path, speed=None)
        assert rep.done.wait(30)
        assert rt.live.session_id is None and rt.live.unrecognised == len(packets)
    finally:
        rt.close()


# ============================================================================================== capture tools
def _scrub_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scrub_capture", ROOT / "scripts" / "scrub_capture.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["scrub_capture"] = mod  # dataclasses resolve annotations through sys.modules
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop("scrub_capture", None)
        raise
    return mod


def test_scrub_capture_replaces_acc_player_names(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from pitwall.ingest.capture import CaptureMeta, write_capture

    scrub = _scrub_module()
    named = static(
        playerName=P.encode_wstring("Edward", 33),
        playerSurname=P.encode_wstring("Example", 33),
        playerNick=P.encode_wstring("EdX99", 33),
    )
    packets = [
        CapturedPacket(1, 0, P.snapshot(P.STATIC_PAGE, named)),
        CapturedPacket(2, 0, P.snapshot(P.GRAPHICS_PAGE, graphics(1))),
        CapturedPacket(3, 0, P.snapshot(P.PHYSICS_PAGE, physics(1))),
    ]
    path = tmp_path / "x_acc.pwcap"
    write_capture(path, packets, CaptureMeta(source=R.SOURCE, game_hint=R.CAPTURE_GAME_HINT))
    stats = scrub.scrub(path, None, level=3, write=True)
    assert stats.fields == {
        "acc_static_playerName": 1,
        "acc_static_playerSurname": 1,
        "acc_static_playerNick": 1,
    }
    out = list(CaptureReader(path))
    d = P.STATIC.unpack_from(out[0].data, P.TAG_SIZE)
    assert {P.decode_wstring(d[f]) for f in R.PRIVATE_STATIC_FIELDS} == {"Player"}
    assert P.decode_wstring(d["track"]) == "spa" and [p.data for p in out[1:]] == [p.data for p in packets[1:]]
    assert not scrub.scrub(path, None, level=3, write=False).originals  # --check passes now
    # the reader's own captures need nothing: names never reach them
    clean = tmp_path / "reader_acc.pwcap"
    write_acc_capture(clean, SHORT)
    again = scrub.scrub(clean, None, level=3, write=False)
    assert not again.fields and not again.originals and again.not_inspected == 0
    capsys.readouterr()


# ============================================================================================== Windows only
# The Windows-only test below plays ACC under ACC's real mapping names. On a gaming PC a Pitwall started at logon may
# be looking for those pages right now: its pages are SYNTHETIC (the generator's car), so should that reader catch
# them they become a session flagged synthetic (``synthetic:`` track id), never a real ACC session in the user's
# data; and off CI the test does not run at all while a local Pitwall server is listening.
WINDOWS_TEST_STATIC = {"track": "pitwall_mapping_test", "car": P.SYNTHETIC_CAR_MODEL}


def real_mappings_skip_reason(environ: Mapping[str, str], server_listening: Callable[[], bool]) -> str | None:
    """Why the real-mapping test must not run here (None: it may). CI always may: no Pitwall runs there."""
    if environ.get("CI"):
        return None
    if server_listening():
        return "a Pitwall server runs on this PC: its ACC reader could open the test's pages"
    return None


def _pitwall_listening() -> bool:
    """Something accepts connections on this PC's Pitwall port (a connect only; nothing is sent)."""
    import socket

    from pitwall.config import Settings

    try:
        with socket.create_connection(("127.0.0.1", Settings().http_port), timeout=0.5):
            return True
    except OSError:
        return False


def test_the_windows_mapping_test_writes_only_synthetic_pages() -> None:
    a = AccAdapter()
    a.decode(P.snapshot(P.STATIC_PAGE, static(**WINDOWS_TEST_STATIC)), 1)
    info = next(e for e in a.decode(P.snapshot(P.GRAPHICS_PAGE, graphics(2)), 2) if isinstance(e, SessionInfo))
    assert info.session_uid == str(SYNTHETIC_SESSION_UID)
    assert real_mappings_skip_reason({"CI": "true"}, lambda: True) is None
    assert real_mappings_skip_reason({}, lambda: False) is None
    assert "Pitwall server" in (real_mappings_skip_reason({}, lambda: True) or "")


@pytest.mark.skipif(sys.platform != "win32", reason="real named mappings exist only on Windows")
def test_windows_real_mappings_are_read_and_never_created() -> None:  # pragma: no cover - Windows CI
    import ctypes
    import os
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileMappingW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPCWSTR,
    ]
    k32.CreateFileMappingW.restype = wintypes.HANDLE
    k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    k32.MapViewOfFile.restype = wintypes.LPVOID
    k32.UnmapViewOfFile.argtypes = [wintypes.LPCVOID]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    invalid_handle = wintypes.HANDLE(-1)
    page_readwrite, file_map_write, error_already_exists = 0x04, 0x0002, 183

    if probe_pages() != "absent":
        pytest.skip("ACC (or another app) has its pages open on this PC: never touch them")
    why = real_mappings_skip_reason(os.environ, _pitwall_listening)
    if why is not None:
        pytest.skip(why)
    # 1. absent: the real opener answers None and the reader leaves no mapping behind
    assert R.open_windows_page(P.PHYSICS_MAPPING, P.PHYSICS_PAGE.size) is None
    clock = Clock()
    got: list[CapturedPacket] = []
    reader = AccSharedMemoryReader(got.append, clock=clock)
    for _ in range(5):
        reader.poll()
        clock.advance(R.RETRY_S)
    assert reader.state is AccReaderState.NOT_RUNNING and got == []
    assert probe_pages() == "absent"  # nothing was created under ACC's names
    reader.stop()

    # 2. this test plays ACC: real named mappings with ACC's names and sizes, written with packed pages
    handles: list[tuple[int, int]] = []
    views: dict[str, int] = {}
    try:
        for page in P.PAGES:
            h = k32.CreateFileMappingW(invalid_handle, None, page_readwrite, 0, page.size, page.mapping)
            assert h, ctypes.get_last_error()
            if ctypes.get_last_error() == error_already_exists:
                k32.CloseHandle(h)
                pytest.skip("ACC started meanwhile: never write to its pages")
            addr = k32.MapViewOfFile(h, file_map_write, 0, 0, page.size)
            assert addr
            handles.append((int(h), int(addr)))
            views[page.kind] = int(addr)

        def write(page: P.Page, body: bytes) -> None:
            ctypes.memmove(views[page.kind], body, len(body))

        write(P.STATIC_PAGE, static(**WINDOWS_TEST_STATIC, playerName=P.encode_wstring("Edward", 33)))
        write(P.GRAPHICS_PAGE, graphics(1, OFF))
        write(P.PHYSICS_PAGE, physics(1))
        assert probe_pages() == "present"
        clock = Clock()
        got = []
        reader = AccSharedMemoryReader(got.append, clock=clock)
        reader.poll()  # opens (read-only) and takes the baseline
        assert reader.pages_open and got == []
        for pid in range(2, 12):
            write(P.GRAPHICS_PAGE, graphics(pid))
            write(P.PHYSICS_PAGE, physics(pid, speedKmh=150.0 + pid))
            clock.advance(R.POLL_S)
            reader.poll()
        kinds = [P.page_of(p.data).kind for p in got]  # type: ignore[union-attr]
        assert kinds.count("static") == 1 and kinds.count("physics") == 10 and kinds.count("graphics") == 10
        last = P.PHYSICS.unpack_from(got[-1].data, P.TAG_SIZE)
        assert last["packetId"] == 11 and last["speedKmh"] == pytest.approx(161.0)
        assert "Edward".encode("utf-16-le") not in got[0].data
        reader.stop()
    finally:
        for h, addr in handles:
            k32.UnmapViewOfFile(addr)
            k32.CloseHandle(h)
    # 3. the test's handles are closed: the mappings are gone, and opening never re-creates them (a reader elsewhere
    # that opened them meanwhile holds them until its release probe, at most RELEASE_AFTER_S)
    _wait(lambda: probe_pages() == "absent", timeout_s=R.RELEASE_AFTER_S + 3.0)
    assert R.open_windows_page(P.GRAPHICS_MAPPING, P.GRAPHICS_PAGE.size) is None
    assert probe_pages() == "absent"
