"""Gran Turismo 7 heartbeat: asks the console to keep streaming telemetry to this host.

GT7 sends nothing until it receives a heartbeat - a single ASCII byte selecting the packet variant (``A``,
``B``, ``~`` or ``C``) - on UDP 33739, and then unicasts encrypted packets to UDP 33740 on the heartbeat's
source host. The console stops after roughly 1000 packets without a heartbeat (doc section 1). Receiving is
done by the ordinary ``UdpListener`` on 33740; this module only sends.

Design:

* Its own daemon thread, so a slow or failing ``sendto`` can never stall telemetry ingest.
* One heartbeat on start, then every ``interval_s`` (1.6 s default: ~100 packets at 60 Hz, as gt7dashboard
  does, comfortably inside the console's timeout and cheap). ``poke()`` sends one immediately, e.g. after a
  receive gap (doc recommendation: re-send after any gap longer than ~1 s).
* Never crashes on network errors: an unreachable console, a dropped interface or a bad address is counted in
  ``errors`` / ``last_error`` (shown on the Connect page) and retried on the next beat with a fresh socket.
* Sends from an ephemeral socket by default; the console replies to port 33740 regardless of the source
  port (doc section 1, community-inferred). Pass ``sock`` to send from a specific socket instead (for example
  the listener's socket bound to 33740, which is what PDTools and gt7dashboard do).
* ``console_ip=None`` broadcasts to 255.255.255.255 (discovery, as gt7dashboard does); the first telemetry
  packet then reveals the console's address, which can be pinned with ``set_console_ip``. Broadcasting enables
  ``SO_BROADCAST`` on whichever socket sends, the provided ``sock`` included (without it every beat fails with
  EACCES).
* Windows: a console without GT7 running answers each beat with ICMP "port unreachable", which Windows would report
  as ``WSAECONNRESET`` on the sending socket; reporting is switched off on every socket the heartbeat sends from
  (``compat.ignore_udp_port_unreachable``; a no-op elsewhere).
"""

from __future__ import annotations

import contextlib
import logging
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from pitwall.adapters.gt7.packets import CONSOLE_PORT, VARIANTS
from pitwall.compat import ignore_udp_port_unreachable

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 1.6
BROADCAST_IP = "255.255.255.255"
MIN_INTERVAL_S = 0.01


def _validate_ip(ip: str | None) -> str | None:
    """None = broadcast discovery; otherwise the same LAN-only gate as Assetto Corsa (a second line of defence
    behind the Connect-page validation), so the heartbeat can never be aimed off the local network."""
    if ip is None or ip.strip() == "":
        return None
    from pitwall.ingest.ac_client import validate_console_ip

    return validate_console_ip(ip)


def _validate_variant(variant: str) -> str:
    if variant not in VARIANTS:
        raise ValueError(f"unknown GT7 packet variant {variant!r} (expected one of {sorted(VARIANTS)})")
    return variant


class GT7Heartbeat:
    """Periodically sends the variant byte to ``<console_ip>:33739`` from a background thread."""

    def __init__(
        self,
        console_ip: str | None,
        variant: str = "C",
        *,
        port: int = CONSOLE_PORT,
        interval_s: float = DEFAULT_INTERVAL_S,
        sock: socket.socket | None = None,
        socket_factory: Callable[[], socket.socket] | None = None,
    ) -> None:
        if interval_s < MIN_INTERVAL_S:
            raise ValueError(f"interval_s must be >= {MIN_INTERVAL_S}")
        self._ip = _validate_ip(console_ip)
        self._variant = _validate_variant(variant)
        self.port = port
        self.interval_s = interval_s
        self._external_sock = sock
        self._external_broadcast = False  # SO_BROADCAST already enabled on ``sock``
        if sock is not None:
            ignore_udp_port_unreachable(sock)  # Windows: ICMP replies must not fail the owner's recvfrom
        self._factory = socket_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()  # guards target/variant/socket against setters from other threads
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.sent = 0
        self.errors = 0
        self.last_error: str | None = None
        self.last_sent_mono: float | None = None

    # ------------------------------------------------------------------ configuration
    @property
    def console_ip(self) -> str | None:
        return self._ip

    @property
    def variant(self) -> str:
        return self._variant

    def set_console_ip(self, ip: str | None) -> None:
        """Retarget (None = broadcast). Takes effect immediately."""
        new = _validate_ip(ip)
        with self._lock:
            if new != self._ip:
                self._ip = new
                self._drop_socket()  # the broadcast option differs between targets
        self.poke()

    def set_variant(self, variant: str) -> None:
        """Request a different packet variant; the console switches on the next heartbeat (sent now)."""
        with self._lock:
            self._variant = _validate_variant(variant)
        self.poke()

    # ------------------------------------------------------------------ lifecycle
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gt7-heartbeat", daemon=True)
        self._thread.start()
        log.info(
            "GT7 heartbeat -> %s:%d every %.1f s (variant %s)",
            self._target(),
            self.port,
            self.interval_s,
            self._variant,
        )

    def poke(self) -> None:
        """Send a heartbeat as soon as possible (e.g. after a receive gap)."""
        self._wake.set()

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout_s)
        with self._lock:
            self._drop_socket()

    # ------------------------------------------------------------------ internals
    def _target(self) -> str:
        return self._ip or BROADCAST_IP

    def _drop_socket(self) -> None:
        if self._sock is not None and self._sock is not self._external_sock:
            with contextlib.suppress(OSError):
                self._sock.close()
        self._sock = None

    def _socket(self) -> socket.socket:
        ext = self._external_sock
        if ext is not None:
            if self._ip is None and not self._external_broadcast:
                # Broadcasting needs SO_BROADCAST on the sending socket (EACCES otherwise) - also on the caller's
                # socket. Set once; harmless if the target later becomes a unicast address. A failure is logged and
                # the beat's sendto then fails and is counted like any other send error.
                try:
                    ext.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    self._external_broadcast = True
                except OSError as e:
                    log.warning("GT7 heartbeat: cannot enable broadcast on the provided socket: %s", e)
            return ext
        if self._sock is None:
            s = self._factory()
            ignore_udp_port_unreachable(s)
            if self._ip is None:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._sock = s
        return self._sock

    def send_once(self) -> bool:
        """Send one heartbeat now (also used by the thread). Returns False on failure; never raises."""
        with self._lock:
            payload = VARIANTS[self._variant].heartbeat
            target = (self._target(), self.port)
            try:
                self._socket().sendto(payload, target)
            except Exception as e:  # OSError in practice (unreachable, no route, bad socket): count, retry
                self.errors += 1
                self.last_error = f"{type(e).__name__}: {e}"
                if self.errors in (1, 10, 100) or self.errors % 1000 == 0:
                    log.warning("GT7 heartbeat to %s:%d failed (%d so far): %s", *target, self.errors, e)
                self._drop_socket()  # retry with a fresh socket (interface changes, closed sockets)
                return False
            self.sent += 1
            self.last_sent_mono = time.monotonic()
            return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self.send_once()  # never raises: failures are counted and retried on the next beat
            self._wake.wait(self.interval_s)
            self._wake.clear()

    def snapshot(self) -> dict[str, Any]:
        """Status for the Connect page / API."""
        last = self.last_sent_mono
        return {
            "console_ip": self._ip,
            "target": f"{self._target()}:{self.port}",
            "variant": self._variant,
            "running": self.running,
            "interval_s": self.interval_s,
            "sent": self.sent,
            "errors": self.errors,
            "last_error": self.last_error,
            "last_sent_s_ago": None if last is None else round(time.monotonic() - last, 1),
        }
