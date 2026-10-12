"""Packet sources: live UDP listener and capture replay. Each runs on its own thread.

The UDP thread does the minimum per datagram: timestamp, hand to the capture writer (non-blocking), decode.
Decoding is a few tens of microseconds per packet; heavy work happens on background workers.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path

from pitwall.compat import bind_udp_exclusive, ignore_udp_port_unreachable, recv_clock_ns
from pitwall.ingest.capture import BackgroundCaptureWriter, CapturedPacket, CaptureMeta, CaptureReader

log = logging.getLogger(__name__)

RCVBUF_BYTES = 4 * 1024 * 1024
MAX_TRACKED_SOURCES = 32


class SourceStats:
    """Per-sender counters for the Connect page (which device is sending, how fast). Receive-thread writes only."""

    __slots__ = ("bytes", "first_mono", "ip", "last_mono", "packets", "port", "rate_count", "rate_pps", "rate_t0")

    def __init__(self, ip: str, port: int, now: float) -> None:
        self.ip = ip
        self.port = port
        self.packets = 0
        self.bytes = 0
        self.first_mono = now
        self.last_mono = now
        self.rate_t0 = now
        self.rate_count = 0
        self.rate_pps = 0.0

    def hit(self, n_bytes: int, now: float) -> None:
        self.packets += 1
        self.bytes += n_bytes
        self.last_mono = now
        self.rate_count += 1
        if now - self.rate_t0 >= 1.0:
            self.rate_pps = self.rate_count / (now - self.rate_t0)
            self.rate_count = 0
            self.rate_t0 = now

    def snapshot(self, now: float) -> dict[str, object]:
        age = now - self.last_mono
        return {
            "ip": self.ip,
            "port": self.port,
            "packets": self.packets,
            "bytes": self.bytes,
            "packets_per_s": round(self.rate_pps if age < 2.0 else 0.0, 1),
            "last_seen_s": round(age, 1),
            "connected_s": round(self.last_mono - self.first_mono, 1),
        }


class UdpListener:
    def __init__(
        self,
        port: int,
        handler: Callable[[CapturedPacket], None],
        bind: str = "0.0.0.0",
        capture_dir: Path | None = None,
        on_idle: Callable[[], None] | None = None,
        idle_timeout_s: float = 60.0,
    ) -> None:
        self.port = port
        self.bind = bind
        self.handler = handler
        self.capture_dir = capture_dir
        self.on_idle = on_idle
        self.idle_timeout_s = idle_timeout_s
        self.capture: BackgroundCaptureWriter | None = None
        self.received = 0
        self.handler_errors = 0
        self.last_ip: str | None = None  # the sender of the last datagram (receive thread; read by Setup › Controls)
        self.sources: dict[str, SourceStats] = {}
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RCVBUF_BYTES)
            bind_udp_exclusive(self._sock, (bind, port))  # SO_REUSEADDR on POSIX; exclusive on Windows
        except OSError:
            self._sock.close()  # a port in use is retried by the runtime: never leak a socket per attempt
            raise
        # Windows: the socket may also send (a GT7 heartbeat can be given it); an ICMP reply must not fail recvfrom
        ignore_udp_port_unreachable(self._sock)
        self._sock.settimeout(0.5)
        self._thread = threading.Thread(target=self._run, name=f"udp-{port}", daemon=True)

    def start(self) -> None:
        self._thread.start()
        log.info("listening for telemetry on udp://%s:%d", self.bind, self.port)

    def _open_capture(self) -> None:
        if self.capture_dir is None:
            return
        name = time.strftime("%Y%m%d-%H%M%S") + f"_udp{self.port}.pwcap"
        self.capture = BackgroundCaptureWriter(
            self.capture_dir / name, CaptureMeta(source=f"udp:{self.port}", description="live capture")
        )
        log.info("recording raw packets to %s", self.capture.path)

    def _close_capture(self) -> None:
        if self.capture is not None:
            self.capture.close()
            log.info("capture closed: %s (%d packets)", self.capture.path, self.capture.packets)
            self.capture = None

    def _run(self) -> None:
        last = 0.0
        idle_notified = True
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(65535)
            except TimeoutError:
                if not idle_notified and time.monotonic() - last > self.idle_timeout_s:
                    idle_notified = True
                    self._close_capture()  # a fresh file per driving session
                    if self.on_idle:
                        self.on_idle()
                continue
            except ConnectionResetError:
                if self._stop.is_set():
                    break
                continue  # Windows: ICMP "port unreachable" for a datagram this socket sent; nothing was received
            except OSError:
                if self._stop.is_set():
                    break
                raise
            t_ns = recv_clock_ns()
            last = time.monotonic()
            idle_notified = False
            self.received += 1
            self._track(addr, len(data), last)
            if self.capture is None and self.capture_dir is not None:
                self._open_capture()
            pkt = CapturedPacket(t_ns, self.port, data)
            if self.capture is not None:
                self.capture.submit(pkt)
            try:
                self.handler(pkt)
            except Exception:
                self.handler_errors += 1
                log.exception("packet handler failed")
        self._close_capture()

    def _track(self, addr: tuple[str, int], n_bytes: int, now: float) -> None:
        ip = str(addr[0])
        self.last_ip = ip
        st = self.sources.get(ip)
        if st is None:
            if len(self.sources) >= MAX_TRACKED_SOURCES:  # bounded: evict the stalest sender
                stalest = min(self.sources.values(), key=lambda s: s.last_mono)
                del self.sources[stalest.ip]
            st = self.sources[ip] = SourceStats(ip, int(addr[1]), now)
            log.info("telemetry source connected: %s:%d", ip, addr[1])
        st.hit(n_bytes, now)

    def source_snapshot(self) -> list[dict[str, object]]:
        now = time.monotonic()
        live = sorted(list(self.sources.values()), key=lambda s: now - s.last_mono)
        return [s.snapshot(now) for s in live]

    def stop(self) -> None:
        self._stop.set()
        self._sock.close()
        self._thread.join(5)


class ReplaySource:
    """Feeds a ``.pwcap`` through the same handler as live UDP.

    ``speed=None`` replays as fast as possible (analysis/tests); ``speed=1.0`` reproduces original timing.
    """

    def __init__(
        self,
        path: Path,
        handler: Callable[[CapturedPacket], None],
        speed: float | None = 1.0,
        on_done: Callable[[], None] | None = None,
        loop: bool = False,
    ) -> None:
        self.path = path
        self.reader = CaptureReader(path)
        self.handler = handler
        self.speed = speed
        self.on_done = on_done
        self.loop = loop
        self.sent = 0
        self.done = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self.run, name="replay", daemon=True)

    @property
    def meta(self) -> CaptureMeta:
        return self.reader.meta

    def start(self) -> None:
        self._thread.start()

    def run(self) -> None:
        try:
            while True:
                self._play_once()
                if not self.loop or self._stop.is_set():
                    break
        finally:
            try:
                if self.on_done:
                    self.on_done()  # ends the session (last lap, final AI pace job): part of the replay
            finally:
                self.done.set()  # after on_done, so a waiter sees everything the replay produced

    def _play_once(self) -> None:
        t0_cap: int | None = None
        t0_wall = recv_clock_ns()
        for pkt in self.reader:
            if self._stop.is_set():
                return
            if self.speed:
                if t0_cap is None:
                    t0_cap = pkt.t_recv_ns
                due = t0_wall + (pkt.t_recv_ns - t0_cap) / self.speed
                wait = (due - recv_clock_ns()) / 1e9
                if wait > 0.002:
                    time.sleep(wait)
            self.handler(pkt)
            self.sent += 1

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(5)
