"""Assetto Corsa Competizione shared-memory reader: the packet source for ``AccAdapter`` on the PC that runs ACC.

ACC has no socket. While it runs it keeps three named file mappings in the logged-in user's session -
``Local\\acpmf_physics`` (800 B), ``Local\\acpmf_graphics`` (1588 B) and ``Local\\acpmf_static`` (820 B), laid out
as Kunos' "ACC Shared Memory v1.8.12" documents (``adapters/acc/packets.py``,
``docs/research/acc-shared-memory-spec.md``). This module copies those pages on its own thread and hands each copy
that carries something new to the same ``handler(CapturedPacket)`` a ``UdpListener`` feeds: a 4-byte tag
(``PHYS`` / ``GRPH`` / ``STAT``) plus the whole page, so ``PacketRouter`` + ``AccAdapter``, the ``.pwcap`` capture
and ``pitwall replay`` treat ACC like any other packet stream.

Started from the reader Ed (Pitwall tester) sent with his ACC adapter on 2026-10-14 (``acc-adapter-for-james.patch``:
three pages, tagged snapshots, one polling thread), rebuilt around two problems found in review:

* **Open, never create.** Python's ``mmap.mmap(-1, size, tagname=...)`` calls ``CreateFileMapping``: with ACC not
  running it *creates* zero-filled pages under ACC's names, so a reader decodes blank pages forever (``/api/health``
  then says "live" all day and the never-restart-while-someone-drives guard never releases), and if Pitwall starts
  first, ACC and every other tool (SimHub, Crew Chief...) find mappings they did not size. This reader only ever
  calls ``OpenFileMappingW(FILE_MAP_READ, FALSE, name)`` + ``MapViewOfFile(FILE_MAP_READ)`` through ctypes and
  treats "not found" as "ACC is not running" (retried every ``RETRY_S``). Nothing it does can create, resize or
  write a mapping.
* **Nothing new, nothing sent.** A page copy becomes a snapshot only when it carries a change, decided by
  ``AccPageGate`` (pure; the synthetic generator ``pitwall.sim.acc_stream`` uses the same gate):

  - the first copy of a page after start-up is only a baseline: pages left behind by a game that crashed (or that
    another app keeps open after ACC quit) never produce a frame;
  - Graphics when its ``packetId`` (or ``status``) changed and ``status`` is LIVE, or when ``status`` moved away
    from the status of the last Graphics page sent (LIVE -> PAUSE / REPLAY / OFF: the transition the adapter needs
    to hold its clock or end the session). Menus (OFF), a pause and a replay therefore send at most one page each,
    whatever ACC keeps rewriting meanwhile: Kunos does not document whether a paused game or its menus keep
    stepping ``packetId``;
  - Physics when its ``packetId`` changed while the latest Graphics status is LIVE;
  - Static (no ``packetId``) when its bytes differ from the Static last sent, and only in front of a Graphics or
    Physics snapshot, so a Static page filled in the menus is sent with the first page on track; an all-zero Static
    is never sent (the adapter ignores it anyway).

  So a closed game, a game sitting in its menus, a paused game and a replay produce no accepted packets: the
  router's "live" and the dashboard's connection status follow someone actually driving.

Other decisions
---------------
* **Player names never leave the reader.** Static's ``playerName`` / ``playerSurname`` / ``playerNick`` (fields
  the adapter never decodes) are zeroed in every snapshot before it reaches the router or a capture, so ACC
  recordings can be shared without scrubbing.
* **Torn copies.** ACC writes the pages without a lock and Kunos documents no write order. A Physics or Graphics
  copy is re-checked against the page's ``packetId`` right after copying and copied again (up to
  ``TORN_RETRIES`` times) when it moved meanwhile; a page that keeps moving is skipped for that poll
  (``torn_reads``). Best effort only: if ACC writes ``packetId`` first, a torn copy cannot be detected this way.
* **Rate.** ``POLL_S`` = 1/60 s: Kunos rewrites Physics and Graphics once per graphics frame, so the reader samples
  a 60 Hz stream - enough for braking cues - and each poll costs three ``memcpy`` of < 2 KB.
* **Release probe.** A held view keeps a mapping alive after ACC quits (Windows deletes it with its last handle).
  After ``RELEASE_AFTER_S`` without any change the reader closes its views and opens them again at once: if ACC
  has gone (and no other app holds the pages) they are gone and the state says "ACC not running".
* **Session end.** ``on_idle`` (the runtime: flush the adapter, end the session) runs ``idle_timeout_s`` after
  the last snapshot, exactly like ``UdpListener``; the capture file closes with it (a new file per driving
  session) and the gate re-arms so the next session gets its Static page again.
* **Never blocks, never raises.** Copies, capture submit (non-blocking queue) and the handler run on the reader
  thread; handler exceptions are counted (``handler_errors``) and logged, read errors become state ``error`` and
  a retry.
* **Testable anywhere.** The page opener is injected (``opener(name, size) -> PageView | None``): tests use
  ``pitwall.sim.acc_stream.FakeAccMemory``; ``open_windows_page`` is the real one and exists only on Windows
  (``sys.platform == "win32"``; elsewhere ``AccUnavailable``). ``poll()`` runs one step synchronously.

States (``AccReaderState``, ``snapshot()['state']``): ``not_running`` (no pages: ACC is closed), ``waiting`` (pages
open but nothing new: menus, pause, replay), ``reading`` (snapshots in the last ``READING_S``), ``error`` (the pages
exist but cannot be read, e.g. ACC runs as administrator and Pitwall does not), ``stopped``. The runtime adds
``not_windows`` and ``off`` itself (no reader exists then). ``describe()`` turns each into the sentence the Connect
page shows.
"""

from __future__ import annotations

import functools
import logging
import struct
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pitwall.adapters.acc import packets as P
from pitwall.compat import recv_clock_ns, this_machine
from pitwall.ingest.capture import BackgroundCaptureWriter, CapturedPacket, CaptureMeta

log = logging.getLogger(__name__)

POLL_S = 1.0 / 60.0  # sample rate of the pages (ACC rewrites them once per graphics frame)
RETRY_S = 2.0  # look for ACC's pages again this often while they do not exist
RELEASE_AFTER_S = 10.0  # no change for this long: close the views and reopen them (has ACC quit?)
READING_S = 2.0  # a snapshot younger than this: state "reading" (live.LIVE_S)
TORN_RETRIES = 2  # extra copies of a page whose packetId moved during the copy
CAPTURE_GAME_HINT = "acc-shm"  # CaptureMeta.game_hint of every ACC capture (reader and synthetic generator)
SOURCE = "acc-shm"  # CaptureMeta.source of live ACC captures (and sessions.source, core.runtime.ACC_SOURCE)
NO_PORT = 0  # CapturedPacket.src_port of a snapshot: shared memory has no port
PROTOCOL = "acc-shared-memory-snapshots"
LAYOUT = "Kunos ACC Shared Memory v1.8.12"

FILE_MAP_READ = 0x0004  # winnt.h / memoryapi.h: read-only view (and read-only open)
ERROR_FILE_NOT_FOUND = 2  # OpenFileMappingW: no mapping of that name in this session
ERROR_ACCESS_DENIED = 5

_I32 = struct.Struct("<i")
_OFFSETS = {page.kind: P.field_offsets(page.layout) for page in P.PAGES}
PACKET_ID_OFFSET = _OFFSETS["physics"]["packetId"][0]  # 0 in both pages (the machine check pins the layouts)
assert _OFFSETS["graphics"]["packetId"][0] == PACKET_ID_OFFSET
STATUS_OFFSET = _OFFSETS["graphics"]["status"][0]
PRIVATE_STATIC_FIELDS = ("playerName", "playerSurname", "playerNick")  # personal: zeroed before anything sees them
_PRIVATE_SPANS: tuple[tuple[int, int], ...] = tuple(
    (_OFFSETS["static"][name][0], struct.calcsize("<" + _OFFSETS["static"][name][1])) for name in PRIVATE_STATIC_FIELDS
)
_ZERO_STATIC = bytes(P.STATIC_PAGE.size)
_ID_PAGES = frozenset({"physics", "graphics"})
_STATUS_WORDS = {int(s): s.name.lower() for s in P.AccStatus}  # 0 off, 1 replay, 2 live, 3 pause


def not_windows_text() -> str:
    """Why there is no ACC reader on this machine (any OS but Windows)."""
    return (
        "Assetto Corsa Competizione shares its telemetry only on the Windows PC that runs it (shared memory): "
        f"Pitwall must run on that PC, {this_machine()} can't read it"
    )


class AccUnavailable(RuntimeError):
    """ACC's shared memory cannot exist here (not Windows)."""


class PageView(Protocol):
    """One open, read-only view of a mapping."""

    def read(self, offset: int = 0, size: int | None = None) -> bytes: ...

    def close(self) -> None: ...


PageOpener = Callable[[str, int], PageView | None]  # (mapping name, bytes) -> view, None when absent; OSError else


class AccReaderState(StrEnum):
    NOT_WINDOWS = "not_windows"  # set by the runtime: no reader exists off Windows
    OFF = "off"  # set by the runtime: ACC neither enabled nor the selected game
    NOT_RUNNING = "not_running"  # ACC's pages do not exist: the game is closed
    WAITING = "waiting"  # pages open, nothing new: menus, paused, replay (or closed while another app holds them)
    READING = "reading"  # snapshots arriving
    ERROR = "error"  # the pages exist but cannot be opened or read
    STOPPED = "stopped"


def reader_supported() -> bool:
    """Whether ACC's shared memory can exist on this machine (ACC and its pages are Windows-only)."""
    return sys.platform == "win32"


def describe(state: str, acc_status: str | None = None, rate: float = 0.0, last_error: str | None = None) -> str:
    """The Connect page's sentence for a reader state (the backend writes every sentence)."""
    if state == AccReaderState.NOT_WINDOWS:
        return not_windows_text() + "."
    if state == AccReaderState.OFF:
        return "Off: select ACC on Setup › Game (or switch it on here) and Pitwall reads it on this PC."
    if state == AccReaderState.NOT_RUNNING:
        return f"ACC is not running on {this_machine()} (Pitwall looks for it every {RETRY_S:g} s)."
    if state == AccReaderState.WAITING:
        if acc_status == "pause":
            return "ACC is paused: Pitwall reads it again when you drive on."
        if acc_status == "replay":
            return "ACC is showing a replay: Pitwall reads it again when you are back on track."
        if acc_status == "live":
            return (
                "ACC says it is on track but its pages are not changing (the game may be frozen or closed while "
                "another app keeps them open)."
            )
        return "ACC is running but you are not on track (menus or loading): get on track."
    if state == AccReaderState.READING:
        return f"Reading ACC on {this_machine()} · {round(rate)} pages/s."
    if state == AccReaderState.ERROR:
        why = last_error or "unknown error"
        if "access" in why.lower() and "denied" in why.lower():
            return (
                f"Can't read ACC's shared memory: access denied ({why}). ACC is probably running as administrator: "
                "start Pitwall the same way, or ACC normally."
            )
        return f"Can't read ACC's shared memory: {why}."
    if state == AccReaderState.STOPPED:
        return "Stopped."
    return state


def without_player_names(static_body: bytes) -> bytes:
    """A Static page with ``playerName`` / ``playerSurname`` / ``playerNick`` zeroed (fields Pitwall never reads)."""
    if len(static_body) != P.STATIC_PAGE.size:
        return static_body
    buf = bytearray(static_body)
    for off, width in _PRIVATE_SPANS:
        buf[off : off + width] = bytes(width)
    return bytes(buf)


def packet_id(body: bytes) -> int:
    """``packetId`` of a Physics or Graphics page."""
    return int(_I32.unpack_from(body, PACKET_ID_OFFSET)[0])


def graphics_status(body: bytes) -> int:
    """``status`` (ACC_STATUS) of a Graphics page."""
    return int(_I32.unpack_from(body, STATUS_OFFSET)[0])


def status_word(status: int | None) -> str | None:
    """``off`` / ``replay`` / ``live`` / ``pause``; any other value is ``off`` (the adapter's reading); None: unseen."""
    if status is None:
        return None
    return _STATUS_WORDS.get(status, "off")


# ---------------------------------------------------------------------------------------------- gate (pure)
class AccPageGate:
    """Which page copies become snapshots (module docstring). Pure and single-threaded; ``offer`` returns the
    snapshots to forward, Static first, then Graphics, then Physics (the adapter opens a session on Graphics and
    wants Static before it)."""

    __slots__ = ("_sent_static", "_sent_status", "changes", "graphics_id", "physics_id", "static", "status")

    def __init__(self) -> None:
        self.physics_id: int | None = None
        self.graphics_id: int | None = None
        self.status: int | None = None  # the latest Graphics status seen (sent or not)
        self.static: bytes | None = None  # the latest non-empty Static seen, player names zeroed
        self.changes = 0  # page changes seen, sent or not ("is ACC writing at all")
        self._sent_status: int | None = None  # status of the last Graphics snapshot
        self._sent_static: bytes | None = None

    def rearm(self) -> None:
        """A session ended (idle): the next snapshot needs Static again, and only a LIVE page restarts the stream."""
        self._sent_status = None
        self._sent_static = None

    def offer(self, physics: bytes | None, graphics: bytes | None, static: bytes | None) -> list[bytes]:
        out: list[bytes] = []
        g_send: bytes | None = None
        if graphics is not None:
            pid, status = packet_id(graphics), graphics_status(graphics)
            seen = self.graphics_id is not None
            changed = seen and (pid != self.graphics_id or status != self.status)
            self.graphics_id, self.status = pid, status
            if changed:
                self.changes += 1
                live = status == P.AccStatus.LIVE
                if live or (self._sent_status is not None and status != self._sent_status):
                    g_send = graphics
        p_send: bytes | None = None
        if physics is not None:
            pid = packet_id(physics)
            changed = self.physics_id is not None and pid != self.physics_id
            self.physics_id = pid
            if changed:
                self.changes += 1
                if self.status == P.AccStatus.LIVE:
                    p_send = physics
        if static is not None:
            body = without_player_names(static)
            if body != _ZERO_STATIC and body != self.static:
                if self.static is not None:
                    self.changes += 1
                self.static = body
        if (g_send is not None or p_send is not None) and self.static is not None and self.static != self._sent_static:
            out.append(P.snapshot(P.STATIC_PAGE, self.static))
            self._sent_static = self.static
        if g_send is not None:
            out.append(P.snapshot(P.GRAPHICS_PAGE, g_send))
            self._sent_status = self.status
        if p_send is not None:
            out.append(P.snapshot(P.PHYSICS_PAGE, p_send))
        return out


# ---------------------------------------------------------------------------------------------- Windows
class WindowsPageView:
    """A read-only ``MapViewOfFile`` view of one of ACC's mappings (``open_windows_page``)."""

    def __init__(self, k32: Any, handle: int, address: int, size: int) -> None:
        self._k32 = k32
        self._handle: int | None = handle
        self._address = address
        self.size = size

    def read(self, offset: int = 0, size: int | None = None) -> bytes:
        import ctypes

        if self._handle is None:
            raise OSError("view closed")
        n = self.size - offset if size is None else size
        if offset < 0 or n < 0 or offset + n > self.size:
            raise ValueError(f"read {offset}+{n} outside a {self.size}-byte view")
        return ctypes.string_at(self._address + offset, n)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        self._k32.UnmapViewOfFile(self._address)
        self._k32.CloseHandle(handle)


@functools.cache
def _kernel32() -> Any:
    """kernel32 with typed signatures for the four calls the reader needs (Windows only)."""
    if sys.platform != "win32":
        raise AccUnavailable(not_windows_text())
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenFileMappingW.restype = wintypes.HANDLE
    k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    k32.MapViewOfFile.restype = wintypes.LPVOID
    k32.UnmapViewOfFile.argtypes = [wintypes.LPCVOID]
    k32.UnmapViewOfFile.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32


def open_windows_page(name: str, size: int) -> WindowsPageView | None:
    """OPEN an existing named mapping read-only and map ``size`` bytes of it; None when no mapping of that name exists
    (ACC is not running). Never creates one. Raises ``OSError`` for anything else (access denied, a mapping smaller
    than ``size``) and ``AccUnavailable`` off Windows."""
    if sys.platform != "win32":
        raise AccUnavailable(not_windows_text())
    import ctypes

    k32 = _kernel32()
    handle = k32.OpenFileMappingW(FILE_MAP_READ, False, name)
    if not handle:
        err = ctypes.get_last_error()
        if err == ERROR_FILE_NOT_FOUND:
            return None
        if err == ERROR_ACCESS_DENIED:
            raise PermissionError(err, f"access denied opening {name}")
        raise OSError(err, f"OpenFileMappingW({name}) failed: {ctypes.FormatError(err).strip()}")
    address = k32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, size)
    if not address:
        err = ctypes.get_last_error()
        k32.CloseHandle(handle)
        raise OSError(err, f"MapViewOfFile({name}, {size} B) failed: {ctypes.FormatError(err).strip()}")
    return WindowsPageView(k32, int(handle), int(address), size)


def probe_pages(opener: PageOpener | None = None, pages: Sequence[P.Page] = P.PAGES) -> str:
    """Are ACC's pages there right now (``pitwall doctor``)? Opens each read-only and closes it at once.

    ``present`` (all three), ``absent`` (none), ``partial``, ``denied: <error>``, ``error: <error>``, or
    ``unsupported`` off Windows. Creates nothing."""
    if opener is None:
        if not reader_supported():
            return "unsupported"
        opener = open_windows_page
    found = 0
    for page in pages:
        try:
            view = opener(page.mapping, page.size)
        except PermissionError as e:
            return f"denied: {e}"
        except (OSError, AccUnavailable) as e:
            return f"error: {e}"
        if view is not None:
            found += 1
            view.close()
    return "present" if found == len(pages) else "absent" if found == 0 else "partial"


# ---------------------------------------------------------------------------------------------- reader
class AccSharedMemoryReader:
    """Polls ACC's three pages on its own thread and forwards what changed (module docstring).

    Surface like ``UdpListener`` / ``AcRemoteClient``: ``handler(CapturedPacket)``, ``capture_dir`` (raw ``.pwcap``,
    a new file per driving session), ``on_idle`` after ``idle_timeout_s`` without a snapshot, ``received``,
    ``handler_errors``, ``capture``, ``start()``, ``stop()``, ``running``, plus ``snapshot()`` for the Connect page
    and ``poll()`` (one synchronous step, for tests)."""

    def __init__(
        self,
        handler: Callable[[CapturedPacket], None],
        *,
        opener: PageOpener | None = None,
        capture_dir: Path | None = None,
        on_idle: Callable[[], None] | None = None,
        idle_timeout_s: float = 60.0,
        poll_s: float = POLL_S,
        retry_s: float = RETRY_S,
        release_after_s: float = RELEASE_AFTER_S,
        capture_meta_extra: Mapping[str, Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        pages: Sequence[P.Page] = P.PAGES,
    ) -> None:
        if opener is None:
            if not reader_supported():
                raise AccUnavailable(not_windows_text())
            opener = open_windows_page
        for name, v in (
            ("idle_timeout_s", idle_timeout_s),
            ("poll_s", poll_s),
            ("retry_s", retry_s),
            ("release_after_s", release_after_s),
        ):
            if not v > 0:
                raise ValueError(f"{name} must be > 0")
        if [p.kind for p in pages] != [p.kind for p in P.PAGES]:
            raise ValueError("pages must be the physics, graphics and static pages, in that order")
        self.handler = handler
        self.capture_dir = capture_dir
        self.on_idle = on_idle
        self.idle_timeout_s = idle_timeout_s
        self.poll_s = poll_s
        self.retry_s = retry_s
        self.release_after_s = release_after_s
        self.capture_meta_extra = dict(capture_meta_extra or {})
        self.pages = tuple(pages)
        self._opener = opener
        self._clock = clock

        # counters / status (written by the reader thread only; read anywhere)
        self.capture: BackgroundCaptureWriter | None = None
        self.received = 0  # snapshots forwarded
        self.by_page: dict[str, int] = {p.kind: 0 for p in P.PAGES}
        self.handler_errors = 0
        self.torn_reads = 0
        self.polls = 0
        self.opens = 0  # successful opens of the three pages
        self.releases = 0  # release probes (views closed after a quiet spell)
        self.last_error: str | None = None
        self.gate = AccPageGate()

        self._views: dict[str, PageView] | None = None
        self._presence = "unknown"  # unknown | absent | open | error | stopped
        self._next_open = 0.0
        self._last_activity = 0.0
        self._last_rx: float | None = None
        self._idle_notified = True  # nothing to report until the first snapshot (UdpListener semantics)
        self._rate = 0.0
        self._rate_t0 = 0.0
        self._rate_n = 0
        self._last_logged_error: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="acc-shm", daemon=True)

    # ------------------------------------------------------------------ public API
    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    @property
    def state(self) -> AccReaderState:
        p = self._presence
        if p == "stopped":
            return AccReaderState.STOPPED
        if p == "error":
            return AccReaderState.ERROR
        if p != "open":
            return AccReaderState.NOT_RUNNING
        last = self._last_rx
        if last is not None and self._clock() - last < READING_S:
            return AccReaderState.READING
        return AccReaderState.WAITING

    @property
    def pages_open(self) -> bool:
        return self._views is not None

    def start(self) -> None:
        self._thread.start()
        log.info(
            "ACC shared-memory reader started (%s, read-only, never created)", ", ".join(p.mapping for p in self.pages)
        )

    def stop(self, timeout_s: float = 3.0) -> None:
        """Stop the thread, close the views (UnmapViewOfFile + CloseHandle) and the capture."""
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout_s)
        if not self._thread.is_alive():
            self._shutdown()  # idempotent: the thread may already have done it

    def snapshot(self) -> dict[str, Any]:
        """Reader status for the Connect page / API (safe to call from any thread)."""
        now = self._clock()
        last = self._last_rx
        state = self.state
        rate = round(self._rate, 1) if last is not None and now - last < READING_S else 0.0
        acc_status = status_word(self.gate.status) if self._views is not None else None
        return {
            "state": state.value,
            "message": describe(state.value, acc_status, rate, self.last_error),
            "pages_open": self._views is not None,
            "acc_status": acc_status,
            "received": self.received,
            "by_page": dict(self.by_page),
            "rate": rate,
            "last_rx_s_ago": None if last is None else round(max(0.0, now - last), 1),
            "opens": self.opens,
            "releases": self.releases,
            "torn_reads": self.torn_reads,
            "last_error": self.last_error,
            "capture": str(self.capture.path) if self.capture else None,
            "handler_errors": self.handler_errors,
        }

    def poll(self) -> int:
        """One step: open the pages if due, copy them, forward what changed. Returns the snapshots forwarded."""
        if self._presence == "stopped":
            return 0
        now = self._clock()
        self.polls += 1
        self._check_idle(now)
        if self._views is None and (now < self._next_open or not self._open(now)):
            return 0
        try:
            copies = [self._copy(page) for page in self.pages]
        except (OSError, ValueError) as e:
            self._fail(f"reading the pages failed: {e}", now)
            return 0
        before = self.gate.changes
        snaps = self.gate.offer(copies[0], copies[1], copies[2])
        if self.gate.changes != before:
            self._last_activity = now
        if snaps:
            t_ns = recv_clock_ns()
            for snap in snaps:
                self._forward(snap, t_ns, now)
        elif now - self._last_activity >= self.release_after_s:
            self._release_probe(now)
        return len(snaps)

    # ------------------------------------------------------------------ thread
    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self.poll()
                self._stop.wait(self.poll_s if self._views is not None else min(self.retry_s, 0.25))
        except Exception:  # pragma: no cover - a bug here must not kill the process silently
            log.exception("ACC shared-memory reader crashed")
            self.last_error = "reader thread crashed (see server log)"
        finally:
            self._shutdown()

    # ------------------------------------------------------------------ pages
    def _open(self, now: float) -> bool:
        views: dict[str, PageView] = {}
        try:
            for page in self.pages:
                view = self._opener(page.mapping, page.size)
                if view is None:
                    self._close(views)
                    if self._presence == "open":
                        log.info("ACC shared memory is gone: ACC is not running")
                    self._presence = "absent"
                    self.last_error = None
                    self._next_open = now + self.retry_s
                    return False
                views[page.kind] = view
        except (OSError, AccUnavailable) as e:
            self._close(views)
            self._fail(f"{type(e).__name__}: {e}", now)
            return False
        if self._presence != "open":
            log.info("ACC shared memory found: reading it (nothing is sent until you are on track)")
        self._views = views
        self._presence = "open"
        self.opens += 1
        self.last_error = None
        self._last_logged_error = None
        self._last_activity = now
        return True

    def _copy(self, page: P.Page) -> bytes | None:
        views = self._views
        assert views is not None
        view = views[page.kind]
        for _ in range(TORN_RETRIES + 1):
            body = view.read(0, page.size)
            if len(body) != page.size:
                raise ValueError(f"{page.mapping}: read {len(body)} of {page.size} bytes")
            if (
                page.kind not in _ID_PAGES
                or view.read(PACKET_ID_OFFSET, 4) == body[PACKET_ID_OFFSET : PACKET_ID_OFFSET + 4]
            ):
                return body
            self.torn_reads += 1
        return None  # still moving: skip this page for this poll

    def _release_probe(self, now: float) -> None:
        """Quiet for ``release_after_s``: drop our views and look again at once (were we keeping ACC's pages alive?)."""
        self.releases += 1
        self._close_views()
        self._next_open = now
        self._open(now)
        self._last_activity = now

    def _fail(self, msg: str, now: float) -> None:
        self._close_views()
        self._presence = "error"
        self.last_error = msg
        self._next_open = now + self.retry_s
        if msg != self._last_logged_error:  # once per distinct error, not every 2 s for hours
            self._last_logged_error = msg
            log.warning("ACC shared memory: %s", msg)

    def _close_views(self) -> None:
        views, self._views = self._views, None
        if views:
            self._close(views)

    @staticmethod
    def _close(views: Mapping[str, PageView]) -> None:
        for view in views.values():
            try:
                view.close()
            except OSError:  # pragma: no cover - closing a view is best effort
                log.debug("closing an ACC page view failed", exc_info=True)

    # ------------------------------------------------------------------ forwarding
    def _forward(self, data: bytes, t_ns: int, now: float) -> None:
        page = P.page_of(data)
        self.received += 1
        if page is not None:
            self.by_page[page.kind] += 1
        self._last_rx = now
        self._idle_notified = False
        self._rate_n += 1
        if now - self._rate_t0 >= 1.0:
            self._rate = self._rate_n / (now - self._rate_t0) if self._rate_t0 else 0.0
            self._rate_n = 0
            self._rate_t0 = now
        if self.capture is None and self.capture_dir is not None:
            self._open_capture()
        pkt = CapturedPacket(t_ns, NO_PORT, data)
        if self.capture is not None:
            self.capture.submit(pkt)
        try:
            self.handler(pkt)
        except Exception:
            self.handler_errors += 1
            log.exception("ACC snapshot handler failed")

    def _check_idle(self, now: float) -> None:
        last = self._last_rx
        if self._idle_notified or last is None or now - last <= self.idle_timeout_s:
            return
        self._idle_notified = True
        self._close_capture()  # a fresh file per driving session
        self.gate.rearm()  # the next session needs Static again (the adapter is reset by on_idle)
        if self.on_idle is not None:
            try:
                self.on_idle()
            except Exception:
                log.exception("ACC on_idle callback failed")

    def _open_capture(self) -> None:
        if self.capture_dir is None:
            return
        name = time.strftime("%Y%m%d-%H%M%S") + "_acc.pwcap"
        self.capture = BackgroundCaptureWriter(
            self.capture_dir / name,
            CaptureMeta(
                source=SOURCE,
                game_hint=CAPTURE_GAME_HINT,
                description="live capture (Assetto Corsa Competizione shared memory, PHYS/GRPH/STAT snapshots)",
                extra={
                    **self.capture_meta_extra,
                    "protocol": PROTOCOL,
                    "layout": LAYOUT,
                    "snapshot_sizes": {p.kind: p.snapshot_size for p in P.PAGES},
                    "player_names": "zeroed by the reader",
                },
            ),
        )
        log.info("recording ACC snapshots to %s", self.capture.path)

    def _close_capture(self) -> None:
        if self.capture is not None:
            self.capture.close()
            log.info("capture closed: %s (%d snapshots)", self.capture.path, self.capture.packets)
            self.capture = None

    def _shutdown(self) -> None:
        self._close_views()
        self._close_capture()
        self._presence = "stopped"
