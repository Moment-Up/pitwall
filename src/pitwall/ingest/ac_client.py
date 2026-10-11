"""Assetto Corsa remote-telemetry client: registers with the game over UDP and is the packet source for its stream.

AC does not push telemetry anywhere by itself. Its in-session "ACServer" listens on UDP 9996 of the machine (or
PS4/PS5) running the game; a client sends a 12-byte ``handshaker`` (HANDSHAKE), receives a ``handshakerResponse``,
sends the same struct with SUBSCRIBE_UPDATE and from then on receives RTCarInfo "for every physics step" at the
address it sent from. DISMISS unregisters. The server only exists while a session is loaded, so a client has to
re-register for every session (community reports, PS4: "nothing to configure in the game; handshake needed per race
session"; the PS4 build on a PS5 answered and streamed at 60 Hz in the 2026-10-11 probe). This module does exactly
that, on one thread, and hands every datagram to the same handler a ``UdpListener`` would - so ``PacketRouter`` +
``AcAdapter`` see an ordinary packet stream. It subscribes to updates only: laps and lap times come from RTCarInfo
(``lapCount``/``lapTime``/``lastLap``), so the service never receives RTLap. ``subscribe_spot=True`` would send
SUBSCRIBE_SPOT on the *same* socket right after SUBSCRIBE_UPDATE - **unvalidated, keep it off**: the PS5 probe
(``scripts/probe_ac.py``) validated SPOT only on a second socket with its own handshake, and that socket received no
RTCarInfo, so whether a SPOT subscription replaces the update stream on one socket is unknown.

Surface (mirrors ``UdpListener`` so the runtime can treat both alike): ``handler(CapturedPacket)``, ``capture_dir``
(raw ``.pwcap`` via ``BackgroundCaptureWriter``, a new file per driving session), ``on_idle`` after
``idle_timeout_s`` without any datagram, ``received``, ``handler_errors``, ``capture``, ``source_snapshot()``,
``start()``, ``stop()``. Plus ``snapshot()`` (client state for the Connect page) and thread-safe
``set_console_ip()``.

Design decisions
----------------
* **One socket, ephemeral local port, ``connect()``-ed to (console, 9996).** AC replies to the sender's address, so
  no fixed local port is needed (nothing to collide with pitwall's other listeners or other apps), and the kernel
  drops datagrams from any other host. On a connected UDP socket an ICMP "port unreachable" (the console is up but
  no AC session is listening) surfaces as ``ConnectionRefusedError`` (Windows: ``ConnectionResetError``, i.e.
  ``WSAECONNRESET``, which is kept switched on for this socket because it is the refusal signal): reported as state
  ``refused``, never raised.
* **State machine** (``AcClientState``): ``idle`` (no console IP) -> ``handshaking`` (HANDSHAKE every
  ``handshake_interval_s``, 2 s by default) -> ``subscribed`` (reply received, SUBSCRIBE_UPDATE sent) ->
  ``streaming`` (RTCarInfo arriving). If the stream stops for ``stream_timeout_s`` (game paused and silent, back in
  the menus, a new session loading, Wi-Fi drop) or never starts after subscribing, the client sends DISMISS,
  closes the socket and starts again from ``handshaking`` on a *fresh* ephemeral port, so the game always sees a new
  registration and can never end up streaming to us twice. ``resubscribe=False`` stops after the first stream
  instead (manual tools).
* **Rate limit.** Never more than one HANDSHAKE per ``min_handshake_interval_s`` (1 s) whatever the state changes,
  so a flapping network cannot turn the client into a packet storm on the user's LAN. The 1 s floor is enforced for
  every non-loopback target whatever the caller passes (shorter intervals exist only for loopback tests). After
  ``backoff_after_s`` (2 min) without a stream - no answer, refusals, socket errors (a console in rest mode makes
  macOS report ``EHOSTDOWN``), or handshakes answered but no RTCarInfo after subscribing - the handshake interval
  stretches to ``backoff_interval_s`` (6 s), re-registration cycles included: an enabled integration with the
  console off or in another game stays a trickle, not a 2 s beacon all day. Only RTCarInfo resets the back-off.
* **Private LAN only.** ``validate_console_ip`` accepts RFC 1918 (10/8, 172.16/12, 192.168/16) and link-local
  (169.254/16) unicast addresses, plus loopback for tests; anything else - a public address, Tailscale's 100.64/10,
  multicast, a ``.0`` / ``.255`` network or broadcast-looking address - raises, so a typo can never send packets off
  the LAN or to every device on it.
* **Two different timeouts.** ``stream_timeout_s`` (3 s) only re-registers; ``idle_timeout_s`` (the session idle
  timeout, 60 s by default) closes the capture file and calls ``on_idle`` (session end), exactly like
  ``UdpListener``. Handshake replies count as traffic, so a long pause during which the game still answers keeps
  the session alive.
* **Never blocks ingest.** Receive, capture submit (non-blocking queue) and handler run on the client thread; sends
  are 12-byte datagrams on the same thread. ``CapturedPacket.src_port`` is the datagram's real source port (the
  game's 9996), which keeps captures self-describing.
* The client only *classifies* datagrams by size (``packets.kind_of``) to drive its state machine; decoding is the
  adapter's job. The handshake reply is decoded once more here (pure function) only to show car/track on the
  Connect page.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import socket
import threading
import time
from collections.abc import Callable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

from pitwall.adapters.ac import packets as P
from pitwall.compat import PORT_UNREACHABLE, recv_clock_ns, this_machine
from pitwall.ingest.capture import BackgroundCaptureWriter, CapturedPacket, CaptureMeta
from pitwall.ingest.sources import RCVBUF_BYTES, SourceStats

log = logging.getLogger(__name__)

DEFAULT_HANDSHAKE_INTERVAL_S = 2.0
DEFAULT_MIN_HANDSHAKE_INTERVAL_S = 1.0
DEFAULT_STREAM_TIMEOUT_S = 3.0
DEFAULT_BACKOFF_AFTER_S = 120.0
DEFAULT_BACKOFF_INTERVAL_S = 6.0
LAN_MIN_HANDSHAKE_INTERVAL_S = 1.0  # hard floor for any non-loopback target, whatever the caller passes
MIN_INTERVAL_S = 0.02  # lower bound for loopback tests; production uses the defaults above
MAX_TRACKED_SIZES = 32  # bounded histogram of datagram sizes (a misbehaving sender cannot grow it)
POLL_S = 0.25
CAPTURE_GAME_HINT = "ac-remote"  # CaptureMeta.game_hint of every AC capture (client, probe, synthetic writer)

_LOOPBACK = ipaddress.IPv4Network("127.0.0.0/8")
_LAN_NETWORKS = tuple(
    ipaddress.IPv4Network(n)
    for n in (
        "10.0.0.0/8",  # RFC 1918
        "172.16.0.0/12",  # RFC 1918
        "192.168.0.0/16",  # RFC 1918
        "169.254.0.0/16",  # link-local (console cabled straight to the Mac)
    )
)


class AcClientState(StrEnum):
    IDLE = "idle"  # no console IP configured (or resubscribe=False and the stream ended)
    HANDSHAKING = "handshaking"  # sending HANDSHAKE, waiting for a handshakerResponse
    SUBSCRIBED = "subscribed"  # reply received, SUBSCRIBE_UPDATE sent, waiting for RTCarInfo
    STREAMING = "streaming"  # RTCarInfo arriving
    REFUSED = "refused"  # ICMP port unreachable: console up, but no AC session listening on 9996
    STOPPED = "stopped"


def validate_console_ip(ip: str | None, *, allow_loopback: bool = True) -> str | None:
    """Normalise a target address, or None for "no target". Raises ``ValueError`` for anything but a private-LAN
    (RFC 1918 or link-local) IPv4 unicast literal - or loopback when ``allow_loopback`` (tests, dry runs).

    This is the one gate every AC packet destination passes (client constructor, ``set_console_ip``, the probe and
    the integration settings), so nothing pitwall sends for AC can leave the local network.
    """
    if ip is None or str(ip).strip() == "":
        return None
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError as e:
        raise ValueError(f"{ip!r} is not an IP address (e.g. 192.168.1.50)") from e
    if not isinstance(addr, ipaddress.IPv4Address):
        raise ValueError(f"AC remote telemetry needs an IPv4 address, got {ip!r}")
    if addr in _LOOPBACK:
        if allow_loopback:
            return str(addr)
        raise ValueError(f"{ip!r} is {this_machine()}: give the console's / PC's LAN address")
    if not any(addr in net for net in _LAN_NETWORKS):
        raise ValueError(
            f"{ip!r} is not a private LAN address (10.x, 172.16-31.x, 192.168.x): pitwall only talks to devices on "
            "your own network"
        )
    if addr.packed[3] in (0, 255):  # x.x.x.0 / x.x.x.255: network or broadcast address on a home /24
        raise ValueError(f"{ip!r} looks like a network or broadcast address: give the console's own address")
    return str(addr)


class AcRemoteClient:
    """Handshake/subscribe client for AC's remote telemetry; also the packet source of its stream."""

    def __init__(
        self,
        console_ip: str | None,
        handler: Callable[[CapturedPacket], None],
        *,
        port: int = P.AC_PORT,
        capture_dir: Path | None = None,
        on_idle: Callable[[], None] | None = None,
        idle_timeout_s: float = 60.0,
        stream_timeout_s: float = DEFAULT_STREAM_TIMEOUT_S,
        handshake_interval_s: float = DEFAULT_HANDSHAKE_INTERVAL_S,
        min_handshake_interval_s: float = DEFAULT_MIN_HANDSHAKE_INTERVAL_S,
        backoff_after_s: float = DEFAULT_BACKOFF_AFTER_S,
        backoff_interval_s: float = DEFAULT_BACKOFF_INTERVAL_S,
        resubscribe: bool = True,
        subscribe_spot: bool = False,  # UNVALIDATED on one socket (see the module docstring): keep False
        bind: str = "0.0.0.0",
        socket_factory: Callable[[], socket.socket] | None = None,
        capture_meta_extra: Mapping[str, Any] | None = None,
    ) -> None:
        for name, v in (
            ("idle_timeout_s", idle_timeout_s),
            ("stream_timeout_s", stream_timeout_s),
            ("handshake_interval_s", handshake_interval_s),
            ("min_handshake_interval_s", min_handshake_interval_s),
            ("backoff_after_s", backoff_after_s),
            ("backoff_interval_s", backoff_interval_s),
        ):
            if not v >= MIN_INTERVAL_S:
                raise ValueError(f"{name} must be >= {MIN_INTERVAL_S}")
        if handshake_interval_s < min_handshake_interval_s:
            raise ValueError("handshake_interval_s must be >= min_handshake_interval_s")
        if not 1 <= port <= 65535:
            raise ValueError("port must be 1..65535")
        self.port = port
        self.handler = handler
        self.capture_dir = capture_dir
        self.on_idle = on_idle
        self.idle_timeout_s = idle_timeout_s
        self.stream_timeout_s = stream_timeout_s
        self.handshake_interval_s = handshake_interval_s
        self.min_handshake_interval_s = min_handshake_interval_s
        self.backoff_after_s = backoff_after_s
        self.backoff_interval_s = max(backoff_interval_s, handshake_interval_s)
        self.resubscribe = resubscribe
        self.subscribe_spot = subscribe_spot
        if subscribe_spot:
            log.warning(
                "AC client: SUBSCRIBE_SPOT on the update socket is unvalidated (the PS5 probe used a second socket); "
                "the RTCarInfo stream may stop"
            )
        self.bind = bind
        self.capture_meta_extra = dict(capture_meta_extra or {})
        self._factory = socket_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        self._poll_s = min(POLL_S, stream_timeout_s / 4, handshake_interval_s / 4, idle_timeout_s / 4)

        # counters / status (written by the client thread only; read anywhere)
        self.capture: BackgroundCaptureWriter | None = None
        self.received = 0
        self.handler_errors = 0
        self.sent = 0
        self.sent_by_op: dict[str, int] = {op.name: 0 for op in P.Operation}
        self.handshakes_answered = 0
        self.refused = 0
        self.cycles = 0  # re-registrations after the stream stopped
        self.last_error: str | None = None
        self.packet_sizes: dict[int, int] = {}
        self.sources: dict[str, SourceStats] = {}
        self.state = AcClientState.IDLE
        self.last_handshake: dict[str, Any] | None = None

        self._ip = validate_console_ip(console_ip)
        self._pending_ip: tuple[str | None] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ac-remote", daemon=True)
        self._sock: socket.socket | None = None
        self._local_port: int | None = None
        self._registered = False  # a HANDSHAKE went out on the current socket (DISMISS it on the way out)
        self._next_handshake = 0.0
        self._last_handshake_sent: float | None = None
        self._no_stream_since: float | None = None  # first HANDSHAKE since RTCarInfo last arrived (back-off clock)
        self._last_logged_error: str | None = None
        self._subscribed_at = 0.0
        self._last_stream_rx = 0.0
        self._last_rx: float | None = None
        self._idle_notified = True  # nothing to report until the first datagram (UdpListener semantics)
        if self._ip is not None:
            self.state = AcClientState.HANDSHAKING

    # ------------------------------------------------------------------ public API
    @property
    def console_ip(self) -> str | None:
        return self._ip

    @property
    def local_port(self) -> int | None:
        return self._local_port

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()
        log.info("AC remote telemetry client -> %s:%d", self._ip or "(no console IP)", self.port)

    def stop(self, timeout_s: float = 3.0) -> None:
        """Stop the thread; sends DISMISS if the game may have registered us, closes socket and capture."""
        self._stop.set()
        self._wake.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout_s)
        if not self._thread.is_alive():
            self._shutdown()  # idempotent: the thread may already have done it

    def set_console_ip(self, ip: str | None) -> None:
        """Retarget (None = stop talking to anyone). Thread-safe; applied by the client thread at once."""
        new = validate_console_ip(ip)
        with self._lock:
            if new == self._ip and self._pending_ip is None:
                return
            self._pending_ip = (new,)
        self._wake.set()

    def source_snapshot(self) -> list[dict[str, object]]:
        now = time.monotonic()
        live = sorted(list(self.sources.values()), key=lambda s: now - s.last_mono)  # list(): one atomic copy
        return [s.snapshot(now) for s in live]

    def snapshot(self) -> dict[str, Any]:
        """Client status for the Connect page / API (safe to call from any thread)."""
        now = time.monotonic()
        last = self._last_rx
        # The socket is connect()-ed, so every tracked source is the game; the freshest one carries the rate.
        sources = list(self.sources.values())
        src = max(sources, key=lambda s: s.last_mono) if sources else None
        rate = 0.0
        if src is not None and now - src.last_mono < 2.0:
            rate = round(src.rate_pps, 1)
        return {
            "state": self.state.value,
            "console_ip": self._ip,
            "port": self.port,
            "local_port": self._local_port,
            "sent": self.sent,
            "sent_by_op": dict(self.sent_by_op),
            "received": self.received,
            "handshakes_answered": self.handshakes_answered,
            "refused": self.refused,
            "cycles": self.cycles,
            "last_error": self.last_error,
            "rate": rate,
            "last_rx_s_ago": None if last is None else round(now - last, 1),
            "packet_sizes": {str(k): v for k, v in sorted(self.packet_sizes.items())},
            "last_handshake": None if self.last_handshake is None else dict(self.last_handshake),
            "capture": str(self.capture.path) if self.capture else None,
            "handler_errors": self.handler_errors,
        }

    # ------------------------------------------------------------------ thread
    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._apply_pending_target()
                now = time.monotonic()
                self._check_idle(now)
                if self._ip is None or self.state is AcClientState.IDLE:
                    self._wake.wait(self._poll_s)
                    self._wake.clear()
                    continue
                if self._sock is None and not self._open_socket():
                    self._wake.wait(self.handshake_interval_s)
                    self._wake.clear()
                    continue
                self._timers(now)
                self._receive_one()
        except Exception:  # pragma: no cover - a bug here must not kill the process silently
            log.exception("AC remote telemetry client crashed")
            self.last_error = "client thread crashed (see server log)"
        finally:
            self._shutdown()

    def _receive_one(self) -> None:
        sock = self._sock
        if sock is None:
            return
        try:
            data, addr = sock.recvfrom(65535)
        except TimeoutError:
            return
        except PORT_UNREACHABLE:  # ECONNREFUSED (POSIX) / WSAECONNRESET (Windows) on the connected socket
            self._on_refused()
            return
        except OSError as e:
            if self._stop.is_set():
                return
            self._on_socket_error(e)
            return
        self._on_datagram(data, (str(addr[0]), int(addr[1])))

    def _timers(self, now: float) -> None:
        st = self.state
        if st in (AcClientState.HANDSHAKING, AcClientState.REFUSED):
            if now >= self._next_handshake:
                self._send_handshake(now)
        elif st is AcClientState.SUBSCRIBED:
            if now - self._subscribed_at > self.stream_timeout_s:
                self._restart_cycle(now, "no RTCarInfo after subscribing")
        elif st is AcClientState.STREAMING and now - self._last_stream_rx > self.stream_timeout_s:
            self._restart_cycle(now, "stream stopped")

    # ------------------------------------------------------------------ sending
    def _send(self, op: P.Operation) -> bool:
        sock = self._sock
        if sock is None:
            return False
        try:
            sock.send(P.encode_handshaker(op))
        except PORT_UNREACHABLE:
            self._on_refused()
            return False
        except OSError as e:
            self._on_socket_error(e)
            return False
        self.sent += 1
        self.sent_by_op[op.name] += 1
        return True

    def _min_gap_s(self) -> float:
        """Minimum time between two HANDSHAKEs: the configured value, but never under 1 s for a real target."""
        ip = self._ip
        if ip is not None and ipaddress.IPv4Address(ip) in _LOOPBACK:
            return self.min_handshake_interval_s
        return max(self.min_handshake_interval_s, LAN_MIN_HANDSHAKE_INTERVAL_S)

    def _send_handshake(self, now: float) -> None:
        last = self._last_handshake_sent
        gap = self._min_gap_s()
        if last is not None and now - last < gap:
            self._next_handshake = last + gap
            return
        if self._no_stream_since is None:
            self._no_stream_since = now
        self._last_handshake_sent = now
        self._next_handshake = now + max(self._handshake_interval(now), gap)
        if self._send(P.Operation.HANDSHAKE):
            self._registered = True

    def _handshake_interval(self, now: float) -> float:
        """The normal interval, or the back-off interval once there has been no stream for ``backoff_after_s``."""
        since = self._no_stream_since
        if since is not None and now - since >= self.backoff_after_s:
            return self.backoff_interval_s
        return self.handshake_interval_s

    def _restart_cycle(self, now: float, reason: str) -> None:
        """DISMISS, fresh socket, back to handshaking (or idle when ``resubscribe`` is off)."""
        log.info("AC remote telemetry: %s; re-registering with %s:%d", reason, self._ip, self.port)
        self.cycles += 1
        self._close_socket(dismiss=True)
        if self.resubscribe:
            self.state = AcClientState.HANDSHAKING
            last = self._last_handshake_sent  # answered but no stream for a long time: cycles back off too
            self._next_handshake = now if last is None else max(now, last + self._handshake_interval(now))
        else:
            self.state = AcClientState.IDLE

    # ------------------------------------------------------------------ receiving
    def _on_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        t_ns = recv_clock_ns()
        now = time.monotonic()
        self.received += 1
        self._last_rx = now
        self._idle_notified = False
        self._last_logged_error = None
        self._track(addr, len(data), now)
        n = len(data)
        if n in self.packet_sizes or len(self.packet_sizes) < MAX_TRACKED_SIZES:
            self.packet_sizes[n] = self.packet_sizes.get(n, 0) + 1

        kind = P.kind_of(n)
        if kind is P.PacketKind.HANDSHAKE_RESPONSE:
            self.handshakes_answered += 1
            self._remember_handshake(data)
            waiting = self.state in (AcClientState.HANDSHAKING, AcClientState.REFUSED)
            if waiting and self._send(P.Operation.SUBSCRIBE_UPDATE):
                if self.subscribe_spot:
                    self._send(P.Operation.SUBSCRIBE_SPOT)
                self.state = AcClientState.SUBSCRIBED
                self._subscribed_at = now
                log.info("AC handshake answered by %s (%d B); subscribed to updates", addr[0], n)
        elif kind is P.PacketKind.RT_CAR_INFO:
            if self.state is not AcClientState.STREAMING:
                log.info("AC telemetry streaming from %s:%d", *addr)
                self.last_error = None  # a refusal from before the session loaded is history now
            self.state = AcClientState.STREAMING
            self._last_stream_rx = now
            self._registered = True
            self._no_stream_since = None

        if self.capture is None and self.capture_dir is not None:
            self._open_capture()
        pkt = CapturedPacket(t_ns, addr[1], data)
        if self.capture is not None:
            self.capture.submit(pkt)
        try:
            self.handler(pkt)
        except Exception:
            self.handler_errors += 1
            log.exception("AC packet handler failed")

    def _remember_handshake(self, data: bytes) -> None:
        try:
            hs = P.parse_handshake_response(data)
        except P.PacketError:
            return
        self.last_handshake = {
            "size": hs.size,
            "encoding": hs.encoding,
            "status": hs.identifier,
            "version": hs.version,
            "car": hs.car_name,
            "track": hs.track_name,
            "config": hs.track_config,
        }

    def _on_refused(self) -> None:
        self.refused += 1
        if self.state is not AcClientState.REFUSED:
            log.info("AC remote telemetry: %s:%d refused (no AC session listening)", self._ip, self.port)
        self.last_error = (
            "connection refused (ICMP port unreachable): AC is not on track yet (its telemetry server only exists "
            "in a session; the PS5 serves it once you are on track)"
        )
        if self.state in (AcClientState.SUBSCRIBED, AcClientState.STREAMING):
            self._close_socket(dismiss=False)  # the game's server is gone: nothing to dismiss
            self.cycles += 1
            self.state = AcClientState.REFUSED if self.resubscribe else AcClientState.IDLE
        else:
            self.state = AcClientState.REFUSED  # keep handshaking on the normal schedule until a session loads

    def _log_error_once(self, msg: str) -> None:
        """Warn once per distinct error (a Wi-Fi outage must not write a log line every 2 s for hours)."""
        if msg != self._last_logged_error:
            self._last_logged_error = msg
            log.warning("AC remote telemetry: %s", msg)

    def _on_socket_error(self, e: OSError) -> None:
        self.last_error = f"{type(e).__name__}: {e}"
        self._log_error_once(f"socket error: {e}")
        self._close_socket(dismiss=False)
        if self.state is not AcClientState.IDLE:
            self.state = AcClientState.HANDSHAKING
        # never earlier than already scheduled: a send failing with EHOSTDOWN (console off) keeps the back-off
        self._next_handshake = max(self._next_handshake, time.monotonic() + self.handshake_interval_s)

    def _track(self, addr: tuple[str, int], n_bytes: int, now: float) -> None:
        st = self.sources.get(addr[0])
        if st is None:
            if len(self.sources) >= 4:  # connected socket: only the console can reach us; stay bounded anyway
                stalest = min(self.sources.values(), key=lambda s: s.last_mono)
                del self.sources[stalest.ip]
            st = self.sources[addr[0]] = SourceStats(addr[0], addr[1], now)
        st.hit(n_bytes, now)

    def _check_idle(self, now: float) -> None:
        last = self._last_rx
        if self._idle_notified or last is None or now - last <= self.idle_timeout_s:
            return
        self._idle_notified = True
        self._close_capture()  # a fresh file per driving session
        if self.on_idle is not None:
            try:
                self.on_idle()
            except Exception:
                log.exception("AC on_idle callback failed")

    # ------------------------------------------------------------------ socket / capture lifecycle
    def _open_socket(self) -> bool:
        assert self._ip is not None
        s: socket.socket | None = None
        try:
            s = self._factory()
            with contextlib.suppress(OSError):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RCVBUF_BYTES)
            s.bind((self.bind, 0))
            s.connect((self._ip, self.port))
            s.settimeout(self._poll_s)
            local_port = int(s.getsockname()[1])
        except OSError as e:
            if s is not None:  # created but not usable: never leak the descriptor (this retries every 2 s)
                with contextlib.suppress(OSError):
                    s.close()
            self.last_error = f"cannot open socket to {self._ip}:{self.port}: {e}"
            self._log_error_once(self.last_error)
            return False
        self._sock = s
        self._local_port = local_port
        self._registered = False
        return True

    def _close_socket(self, dismiss: bool) -> None:
        s = self._sock
        if s is None:
            return
        if dismiss and self._registered:
            with contextlib.suppress(OSError):
                s.send(P.encode_handshaker(P.Operation.DISMISS))
                self.sent += 1
                self.sent_by_op[P.Operation.DISMISS.name] += 1
        with contextlib.suppress(OSError):
            s.close()
        self._sock = None
        self._local_port = None
        self._registered = False

    def _apply_pending_target(self) -> None:
        with self._lock:
            pending = self._pending_ip
            self._pending_ip = None
        if pending is None:
            return
        (new,) = pending
        if new == self._ip:
            return
        log.info("AC remote telemetry target %s -> %s", self._ip, new)
        self._close_socket(dismiss=True)
        self._ip = new
        self._no_stream_since = None
        self.last_error = None
        if new is None:
            self.state = AcClientState.IDLE
        else:
            self.state = AcClientState.HANDSHAKING
            self._next_handshake = time.monotonic()

    def _open_capture(self) -> None:
        if self.capture_dir is None:
            return
        name = time.strftime("%Y%m%d-%H%M%S") + f"_ac{self.port}.pwcap"
        self.capture = BackgroundCaptureWriter(
            self.capture_dir / name,
            CaptureMeta(
                source=f"ac-remote:{self.port}",
                game_hint=CAPTURE_GAME_HINT,
                description="live capture (Assetto Corsa remote telemetry client)",
                extra={**self.capture_meta_extra, "protocol": "ac-remote-udp"},
            ),
        )
        log.info("recording raw AC packets to %s", self.capture.path)

    def _close_capture(self) -> None:
        if self.capture is not None:
            self.capture.close()
            log.info("capture closed: %s (%d packets)", self.capture.path, self.capture.packets)
            self.capture = None

    def _shutdown(self) -> None:
        self._close_socket(dismiss=True)
        self._close_capture()
        self.state = AcClientState.STOPPED
