"""Live probe: does this console/PC answer Assetto Corsa remote telemetry, and what exactly does it send?

Run manually, with the driver's permission, while AC is *on track* (Hotlap, Time Trial or Practice - the game's
telemetry server only exists inside a session). Nothing needs configuring in the game. Follows the probe plan in
``docs/research/game-compatibility.md`` section 1.2:

1. binds one ephemeral UDP port (1 MB receive buffer), ``connect()``s it to ``<ip>:9996`` (so an ICMP
   port-unreachable surfaces as "refused") and sends HANDSHAKE - at most 5 attempts, 1 s apart, never faster
   (the 5 are a budget for the whole run: the SPOT socket below only gets what the first socket left);
2. prints every reply's size and, for a handshake reply, its decoded strings (car, driver, track, config) and the
   string encoding (408 B = UTF-16 as on PC, 208 B = 8-bit);
3. sends SUBSCRIBE_UPDATE once and records for ``--seconds``;
4. optionally (``--spot-seconds``) opens a *second* socket with its own handshake and sends SUBSCRIBE_SPOT, to see
   whether RTLap arrives (it did not on PS4 in 2017) and what else SPOT sends, while the update stream continues;
5. records *every* datagram received to a ``.pwcap`` at ``--out`` (``game_hint='ac-remote'``, ``synthetic=False``;
   metadata: target, ``--platform``, ``--note``, the decoded handshake and the ops sent so far) and writes a JSON
   summary next to it (``<out>.json``: verdict, histogram, rates, every check below, the full timestamped op log);
6. prints the packet-size histogram, rate and inter-arrival times and the facts the open questions need: identifier
   bytes, ``size`` field, plausibility checks (speed_Kmh = 3.6 x speed_Ms, pedals and spline position in range,
   lapTime rising within a lap), the flag bytes 20..27 (isInPit at 24 vs 26), raw ``steer`` range, raw gear values,
   ``lapCount`` / ``lastLap`` behaviour; then sends DISMISS on every socket and exits.

    uv run python scripts/probe_ac.py --ip 192.168.1.50 --platform ps5 --seconds 60 --spot-seconds 150 \\
        --note "AC 1.22 PS4 build, PS5 fw 25.x, Practice, Monza, Ferrari 458" --out ~/ac-probe-ps5.pwcap

Before the probe: switch the Assetto Corsa integration Off on pitwall's Connect page (the service's own client would
register with the same console; whether AC serves two clients is undocumented).

During the probe: drive, turn the wheel lock to lock (steer unit), select reverse, neutral and 1st (gear encoding),
cross the start/finish line (lapCount / lastLap timing; two laps for RTLap with --spot-seconds), enter the pit lane
or hit the rev limiter (isInPit 24 vs 26), pause once (does the stream stop?).

Safety: only well-formed 12-byte handshaker structs, only to ``<ip>:<port>``, only to a private-LAN (RFC 1918 /
link-local) or loopback address (``pitwall.ingest.ac_client.validate_console_ip``, checked again inside
``run_probe``); at most 5 handshakes, 2 subscribes and 2 dismisses per run, at least 1 s between handshakes; no
broadcast, no scanning; at most 10 minutes. ``--dry-run`` runs the same code against a SYNTHETIC loopback fake server
(``pitwall.sim.ac_stream.FakeAcServer``) and flags the capture synthetic - no packet leaves this machine.

Exit codes: 0 streaming, 1 handshake answered but no stream, 2 no reply, 3 refused (ICMP port unreachable),
4 usage error, 5 reply of an unknown size.
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import math
import select
import socket
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pitwall.adapters.ac import packets as P
from pitwall.compat import PORT_UNREACHABLE, recv_clock_ns
from pitwall.ingest.ac_client import CAPTURE_GAME_HINT, validate_console_ip
from pitwall.ingest.capture import CapturedPacket, CaptureMeta, CaptureWriter

MAX_ATTEMPTS = 5  # handshakes per run, all sockets together
MIN_ATTEMPT_INTERVAL_S = 1.0  # never handshake a real console faster than this (loopback dry runs may)
MAX_TOTAL_S = 600.0
RCVBUF_BYTES = 1 << 20
FLAG_OFFSETS = tuple(range(20, 28))  # six bools at 20..25 + two padding bytes (natural alignment)
RANGE_FIELDS = (
    "speed_Kmh",
    "gas",
    "brake",
    "clutch",
    "steer",
    "engineRPM",
    "carPositionNormalized",
    "accG_frontal",
    "accG_horizontal",
    "accG_vertical",
    "lapTime",
)
SPEED_TOL_KMH = 0.5

EXIT_STREAMING, EXIT_HANDSHAKE_ONLY, EXIT_NO_REPLY, EXIT_REFUSED, EXIT_USAGE, EXIT_UNEXPECTED = 0, 1, 2, 3, 4, 5


@dataclass(slots=True)
class CarInfoStats:
    """Aggregates over the RTCarInfo received on one socket (raw values: interpreting them is the probe's job)."""

    count: int = 0
    t_first_ns: int | None = None
    t_last_ns: int | None = None
    gaps_ms: list[float] = field(default_factory=list)
    identifier: Counter[int] = field(default_factory=Counter)  # byte 0 (spec: 'a')
    identifier_hi: Counter[int] = field(default_factory=Counter)  # byte 1 (0 if wchar_t, else padding)
    size_field: Counter[int] = field(default_factory=Counter)
    flag_bytes: dict[int, Counter[int]] = field(default_factory=lambda: {o: Counter() for o in FLAG_OFFSETS})
    gears: Counter[int] = field(default_factory=Counter)
    lap_counts: Counter[int] = field(default_factory=Counter)
    last_laps: list[int] = field(default_factory=list)
    lap_increments: int = 0
    lap_time_drops: int = 0  # lapTime went down without a lapCount increment
    speed_mismatch: int = 0  # |speed_Kmh - 3.6 * speed_Ms| > tolerance
    pedal_out_of_range: int = 0
    norm_out_of_range: int = 0
    non_finite: int = 0
    ranges: dict[str, list[float]] = field(default_factory=dict)
    _prev_lap: int | None = None
    _prev_lap_time: int | None = None

    def add(self, data: bytes, t_ns: int) -> None:
        p = P.parse_rt_car_info(data)
        if self.t_last_ns is not None:
            self.gaps_ms.append((t_ns - self.t_last_ns) / 1e6)
        if self.t_first_ns is None:
            self.t_first_ns = t_ns
        self.t_last_ns = t_ns
        self.count += 1
        self.identifier[data[0]] += 1
        self.identifier_hi[data[1]] += 1
        self.size_field[int(p["size"])] += 1
        for o in FLAG_OFFSETS:
            self.flag_bytes[o][data[o]] += 1
        gear = int(p["gear"])
        if len(self.gears) < 32 or gear in self.gears:
            self.gears[gear] += 1
        lap = int(p["lapCount"])
        if len(self.lap_counts) < 64 or lap in self.lap_counts:
            self.lap_counts[lap] += 1
        lap_time = int(p["lapTime"])
        if self._prev_lap is not None and lap == self._prev_lap + 1:
            self.lap_increments += 1
        elif self._prev_lap == lap and self._prev_lap_time is not None and lap_time < self._prev_lap_time:
            self.lap_time_drops += 1
        self._prev_lap, self._prev_lap_time = lap, lap_time
        last = int(p["lastLap"])
        if (not self.last_laps or self.last_laps[-1] != last) and len(self.last_laps) < 64:
            self.last_laps.append(last)
        values = {name: float(p[name]) for name in RANGE_FIELDS}
        values["speed_Ms"] = float(p["speed_Ms"])
        if not all(math.isfinite(v) for v in values.values()):
            self.non_finite += 1
        else:
            if abs(values["speed_Kmh"] - 3.6 * values["speed_Ms"]) > SPEED_TOL_KMH + 0.01 * values["speed_Kmh"]:
                self.speed_mismatch += 1
            if not all(0.0 <= values[k] <= 1.0 for k in ("gas", "brake")):
                self.pedal_out_of_range += 1
            if not 0.0 <= values["carPositionNormalized"] < 1.0:
                self.norm_out_of_range += 1
        for name in RANGE_FIELDS:
            v = values[name]
            if math.isfinite(v):
                r = self.ranges.setdefault(name, [v, v])
                r[0], r[1] = min(r[0], v), max(r[1], v)

    @property
    def rate_hz(self) -> float | None:
        if self.count < 2 or self.t_first_ns is None or self.t_last_ns is None or self.t_last_ns <= self.t_first_ns:
            return None
        return (self.count - 1) / ((self.t_last_ns - self.t_first_ns) / 1e9)

    def gap_stats(self) -> dict[str, float] | None:
        if not self.gaps_ms:
            return None
        gaps = sorted(self.gaps_ms)
        return {
            "median_ms": round(statistics.median(gaps), 2),
            "p95_ms": round(gaps[min(len(gaps) - 1, int(0.95 * len(gaps)))], 2),
            "max_ms": round(gaps[-1], 2),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "rate_hz": None if self.rate_hz is None else round(self.rate_hz, 2),
            "inter_arrival": self.gap_stats(),
            "identifier_byte0": _keys(self.identifier),
            "identifier_byte1": _keys(self.identifier_hi),
            "size_field": _keys(self.size_field),
            "flag_bytes": {str(o): _keys(c) for o, c in self.flag_bytes.items()},
            "flag_verdict": _flag_verdict(self) if self.count else None,
            "gear_raw": _keys(self.gears),
            "lap_count": _keys(self.lap_counts),
            "lap_increments": self.lap_increments,
            "last_lap_sequence": self.last_laps,
            "lap_time_drops_without_increment": self.lap_time_drops,
            "speed_mismatch": self.speed_mismatch,
            "pedal_out_of_range": self.pedal_out_of_range,
            "norm_out_of_range": self.norm_out_of_range,
            "non_finite": self.non_finite,
            "ranges": self.ranges,
        }


def _keys(c: Counter[int]) -> dict[str, int]:
    return {str(k): v for k, v in sorted(c.items())}


@dataclass(slots=True)
class ProbeResult:
    verdict: str  # "streaming" | "handshake_only" | "unexpected_reply" | "no_reply" | "refused"
    exit_code: int
    handshake_attempts: int = 0
    refused: int = 0
    handshake: P.HandshakeResponse | None = None
    reply_sizes: list[int] = field(default_factory=list)  # sizes received during the first handshake phase
    sizes: Counter[int] = field(default_factory=Counter)  # every datagram, whole probe
    car_info: CarInfoStats = field(default_factory=CarInfoStats)  # update socket
    spot_car_info: CarInfoStats = field(default_factory=CarInfoStats)  # spot socket (moza-rev: 1 Hz RTCarInfo?)
    spot_handshake: bool = False
    rt_laps: list[P.RtLap] = field(default_factory=list)
    ops: list[dict[str, Any]] = field(default_factory=list)  # every datagram sent, timestamped
    errors: list[str] = field(default_factory=list)  # socket errors other than ICMP refusals (bounded)
    recorded: int = 0
    capture: Path | None = None
    summary: Path | None = None
    lines: list[str] = field(default_factory=list)


def _fmt_range(r: list[float] | None) -> str:
    return "n/a" if r is None else f"[{r[0]:.4g} .. {r[1]:.4g}]"


def _flag_verdict(st: CarInfoStats) -> str:
    def values(o: int) -> set[int]:
        return set(st.flag_bytes[o])

    natural_ok = values(24) <= {0, 1} and values(25) <= {0, 1}
    pads_zero = values(26) == {0} and values(27) == {0}
    alt_ok = values(26) <= {0, 1} and values(27) <= {0, 1}
    if natural_ok and pads_zero and (values(24) == {0, 1} or values(25) == {0, 1}):
        return "isInPit/isEngineLimiterOn toggled at 24/25 with 26/27 always 0: natural alignment CONFIRMED"
    if values(24) == {0} and values(25) == {0} and alt_ok and (values(26) == {0, 1} or values(27) == {0, 1}):
        return "24/25 always 0 while 26/27 toggled: the 26/27 (Egocentrix) reading looks RIGHT - fix packets.py"
    if natural_ok and pads_zero:
        return "consistent with natural alignment, but 24/25 never toggled (enter the pits / hit the limiter)"
    return "INCONCLUSIVE: unexpected flag byte values (see the per-offset values above)"


def _describe_stream(st: CarInfoStats, label: str) -> list[str]:
    out: list[str] = []
    rate = st.rate_hz
    out.append(f"{label}: {st.count} RTCarInfo, rate {rate:.1f} Hz" if rate else f"{label}: {st.count} RTCarInfo")
    gs = st.gap_stats()
    if gs:
        out.append(f"  inter-arrival: median {gs['median_ms']} ms, p95 {gs['p95_ms']} ms, max {gs['max_ms']} ms")
    out.append(
        f"  identifier bytes 0/1: {dict(st.identifier)} / {dict(st.identifier_hi)} (spec: 97 = 'a'; wchar -> 0); "
        f"size field: {dict(st.size_field)} (expected {P.RT_CAR_INFO.size})"
    )
    out.append(
        f"  checks: speed_Kmh != 3.6 x speed_Ms in {st.speed_mismatch}, pedals out of 0..1 in "
        f"{st.pedal_out_of_range}, spline position out of [0, 1) in {st.norm_out_of_range}, lapTime dropped "
        f"without an increment {st.lap_time_drops}x, non-finite in {st.non_finite}"
    )
    flags = " ".join(f"@{o}={sorted(st.flag_bytes[o])}" for o in FLAG_OFFSETS)
    out.append(f"  flag bytes: {flags}")
    out.append(f"  -> {_flag_verdict(st)}")
    out.append(
        f"  gear raw values: {sorted(st.gears)} (community: 0 = R, 1 = N, 2 = 1st); "
        f"lapCount values: {sorted(st.lap_counts)}; increments seen: {st.lap_increments}"
    )
    out.append(f"  lastLap values (in order): {st.last_laps}")
    r = st.ranges
    out.append(
        f"  steer raw {_fmt_range(r.get('steer'))} (turn lock to lock to measure the unit); "
        f"clutch {_fmt_range(r.get('clutch'))}; gas {_fmt_range(r.get('gas'))}; brake {_fmt_range(r.get('brake'))}"
    )
    out.append(
        f"  speed_Kmh {_fmt_range(r.get('speed_Kmh'))}; "
        f"carPositionNormalized {_fmt_range(r.get('carPositionNormalized'))}; "
        f"accG_frontal {_fmt_range(r.get('accG_frontal'))}"
    )
    return out


def _describe(res: ProbeResult, ip: str, port: int, seconds: float) -> list[str]:
    out: list[str] = []
    hs = res.handshake
    if hs is not None:
        status = "OK" if hs.identifier == P.HANDSHAKE_STATUS_OK else "UNEXPECTED, spec says 4242"
        out.append(
            f"handshake reply: {hs.size} B ({hs.encoding}), status {hs.identifier} ({status}), version {hs.version}"
        )
        out.append(
            f"  car={hs.car_name!r} driver={hs.driver_name!r} track={hs.track_name!r} config={hs.track_config!r}"
        )
    other = [s for s in res.reply_sizes if s not in P.HANDSHAKE_RESPONSE_SIZES]
    if other:
        out.append(f"replies of unexpected size during the handshake: {sorted(set(other))}")
    if res.sizes:
        hist = ", ".join(f"{size} B x {n}" for size, n in sorted(res.sizes.items()))
        out.append(f"packet sizes (whole probe): {hist}")
    if res.car_info.count:
        out.extend(_describe_stream(res.car_info, "update socket"))
    if res.spot_handshake or res.spot_car_info.count or res.rt_laps:
        sp = res.spot_car_info
        out.append(
            f"spot socket: handshake {'answered' if res.spot_handshake else 'NOT answered'}; "
            f"RTLap packets: {len(res.rt_laps)}; RTCarInfo on the spot socket: {sp.count}"
            + (f" ({sp.rate_hz:.1f} Hz)" if sp.rate_hz else "")
        )
        for lap in res.rt_laps[:5]:
            out.append(f"  RTLap car#{lap.car_identifier} lap {lap.lap} time {lap.time_ms} ms car={lap.car_name!r}")
    if res.errors:
        out.append(f"socket errors: {res.errors}")
    if res.capture is not None:
        out.append(f"recorded {res.recorded} datagrams to {res.capture}")
    if res.summary is not None:
        out.append(f"summary written to {res.summary}")
    target = f"{ip}:{port}"
    st = res.car_info
    if res.verdict == "streaming":
        sizes = ", ".join(f"{s} B" for s in sorted(res.sizes))
        rate_txt = f"{st.rate_hz:.1f} Hz" if st.rate_hz else "an unmeasurable rate"
        out.append(f"VERDICT: STREAMING - RTCarInfo at {rate_txt} over {seconds:g} s (sizes seen: {sizes})")
    elif res.verdict == "handshake_only":
        out.append("VERDICT: HANDSHAKE OK, NO STREAM - the game answered but sent no RTCarInfo after SUBSCRIBE_UPDATE")
    elif res.verdict == "unexpected_reply":
        out.append(
            f"VERDICT: UNEXPECTED REPLY - {target} answered with {len(res.reply_sizes)} datagram(s) of size(s) "
            f"{sorted(set(res.reply_sizes))} that match no known handshake reply: inspect the capture"
        )
    elif res.verdict == "refused":
        out.append(
            f"VERDICT: REFUSED - {target} answered ICMP port unreachable: AC is not listening (not in a session yet; "
            "if you were on track, this console does not serve AC telemetry - outcome C)"
        )
    else:
        out.append(
            f"VERDICT: NO REPLY - nothing came back from {target} after {res.handshake_attempts} handshake(s) "
            "(not on track? wrong IP? Wi-Fi client isolation? the console may not serve remote telemetry)"
        )
    return out


def _summary(res: ProbeResult, ip: str, port: int, platform: str, note: str, synthetic: bool) -> dict[str, Any]:
    hs = res.handshake
    return {
        "target": f"{ip}:{port}",
        "platform": platform,
        "note": note,
        "synthetic": synthetic,
        "verdict": res.verdict,
        "exit_code": res.exit_code,
        "handshake_attempts": res.handshake_attempts,
        "refused": res.refused,
        "errors": res.errors,
        "handshake": None
        if hs is None
        else {
            "size": hs.size,
            "encoding": hs.encoding,
            "status": hs.identifier,
            "version": hs.version,
            "car": hs.car_name,
            "driver": hs.driver_name,
            "track": hs.track_name,
            "config": hs.track_config,
        },
        "handshake_phase_reply_sizes": res.reply_sizes,
        "sizes": _keys(res.sizes),
        "update": res.car_info.to_dict(),
        "spot": {
            "handshake_answered": res.spot_handshake,
            "rt_laps": [
                {"car_identifier": x.car_identifier, "lap": x.lap, "time_ms": x.time_ms, "car": x.car_name}
                for x in res.rt_laps
            ],
            "car_info": res.spot_car_info.to_dict(),
        },
        "ops": res.ops,
        "recorded": res.recorded,
        "capture": None if res.capture is None else str(res.capture),
    }


class _Probe:
    """Sockets, op log and the capture of one probe run (see ``run_probe``)."""

    def __init__(
        self,
        ip: str,
        port: int,
        res: ProbeResult,
        printer: Callable[[str], None],
        factory: Callable[[], socket.socket],
    ) -> None:
        self.ip, self.port, self.res, self.printer, self.factory = ip, port, res, printer, factory
        self.socks: dict[str, socket.socket] = {}
        self.registered: set[str] = set()
        self.handshakes_left = MAX_ATTEMPTS  # budget shared by every socket of the run
        self.writer: CaptureWriter | None = None
        self.buffer: list[CapturedPacket] = []  # datagrams received before the capture metadata is complete

    def open(self, label: str) -> socket.socket:
        s = self.factory()
        try:
            with contextlib.suppress(OSError):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RCVBUF_BYTES)
            s.bind(("0.0.0.0", 0))
            s.connect((self.ip, self.port))
            s.setblocking(False)
        except OSError:
            s.close()  # never leak a half-opened socket
            raise
        self.socks[label] = s
        self.printer(f"[{label}] socket {s.getsockname()[1]} -> {self.ip}:{self.port}")
        return s

    def send(self, label: str, op: P.Operation) -> None:
        self.res.ops.append({"t_ns": time.monotonic_ns(), "socket": label, "op": op.name})
        if op is P.Operation.HANDSHAKE:
            self.registered.add(label)
        try:
            self.socks[label].send(P.encode_handshaker(op))
        except PORT_UNREACHABLE:  # ECONNREFUSED (POSIX) / WSAECONNRESET (Windows)
            self.res.refused += 1
        except OSError as e:
            self.error(f"send {op.name} on {label}: {e}")

    def error(self, msg: str) -> None:
        if len(self.res.errors) < 20:
            self.res.errors.append(msg)
        self.printer(f"  error: {msg}")

    def record(self, data: bytes, t_ns: int, src_port: int) -> None:
        self.res.recorded += 1
        if self.writer is None:
            self.buffer.append(CapturedPacket(t_ns, src_port, data))
        else:
            self.writer.write(t_ns, src_port, data)

    def start_capture(self, path: Path, meta: CaptureMeta) -> None:
        self.writer = CaptureWriter(path, meta)
        for p in self.buffer:
            self.writer.write(p.t_recv_ns, p.src_port, p.data)
        self.buffer.clear()

    def pump(
        self,
        deadline: float,
        on_packet: Callable[[str, bytes, int, int], None],
        until: Callable[[], bool] | None = None,
    ) -> None:
        """Receive on every open socket until ``deadline`` (monotonic) or until ``until()`` is true."""
        while True:
            if until is not None and until():
                return
            left = deadline - time.monotonic()
            if left <= 0:
                return
            by_fd = {s.fileno(): (label, s) for label, s in self.socks.items()}
            readable, _, _ = select.select(list(by_fd), [], [], min(left, 0.2))
            for fd in readable:
                label, s = by_fd[fd]
                while True:
                    try:
                        data, addr = s.recvfrom(65535)
                    except (BlockingIOError, InterruptedError):
                        break
                    except PORT_UNREACHABLE:  # ECONNREFUSED (POSIX) / WSAECONNRESET (Windows)
                        self.res.refused += 1
                        break
                    except OSError as e:
                        self.error(f"receive on {label}: {e}")
                        break
                    t_ns = recv_clock_ns()  # QueryPerformanceCounter on Windows (monotonic ticks 15.6 ms there)
                    self.record(data, t_ns, int(addr[1]))
                    on_packet(label, data, t_ns, int(addr[1]))

    def handshake(
        self, label: str, attempts: int, interval_s: float, on_packet: Callable[[str, bytes, int, int], None]
    ) -> bool:
        def answered() -> bool:
            return (label == "update" and self.res.handshake is not None) or (
                label == "spot" and self.res.spot_handshake
            )

        if self.handshakes_left <= 0:
            self.printer(f"[{label}] no HANDSHAKE left (at most {MAX_ATTEMPTS} per run)")
        for i in range(min(attempts, self.handshakes_left)):
            self.handshakes_left -= 1
            if label == "update":
                self.res.handshake_attempts += 1
            self.printer(f"[{label}] HANDSHAKE {i + 1}/{attempts}")
            self.send(label, P.Operation.HANDSHAKE)
            self.pump(time.monotonic() + interval_s, on_packet, until=answered)
            if answered():
                return True
        return False

    def close(self) -> None:
        for label, s in self.socks.items():
            if label in self.registered:
                self.res.ops.append({"t_ns": time.monotonic_ns(), "socket": label, "op": "DISMISS"})
                with contextlib.suppress(OSError):
                    s.send(P.encode_handshaker(P.Operation.DISMISS))
                    self.printer(f"[{label}] DISMISS sent")
            with contextlib.suppress(OSError):
                s.close()
        self.socks.clear()


def run_probe(
    ip: str,
    port: int,
    out: Path,
    *,
    seconds: float = 20.0,
    attempts: int = MAX_ATTEMPTS,
    attempt_interval_s: float = 1.0,
    spot_seconds: float = 0.0,
    synthetic: bool = False,
    platform: str = "unknown",
    note: str = "",
    printer: Callable[[str], None] = print,
    socket_factory: Callable[[], socket.socket] | None = None,
) -> ProbeResult:
    ip = check_target(ip)  # also here, not only in main(): no caller can aim the probe off the LAN
    attempts = max(1, min(MAX_ATTEMPTS, attempts))
    if not ipaddress.IPv4Address(ip).is_loopback:
        attempt_interval_s = max(attempt_interval_s, MIN_ATTEMPT_INTERVAL_S)
    res = ProbeResult(verdict="no_reply", exit_code=EXIT_NO_REPLY, capture=out)
    probe = _Probe(ip, port, res, printer, socket_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)))
    phase = ["handshake"]

    def on_packet(label: str, data: bytes, t_ns: int, src_port: int) -> None:
        res.sizes[len(data)] += 1
        kind = P.kind_of(len(data))
        if phase[0] == "handshake":
            res.reply_sizes.append(len(data))
            printer(f"  [{label}] reply: {len(data)} B")
        if kind is P.PacketKind.HANDSHAKE_RESPONSE:
            if label == "update" and res.handshake is None:
                res.handshake = P.parse_handshake_response(data)
            elif label == "spot":
                res.spot_handshake = True
        elif kind is P.PacketKind.RT_CAR_INFO:
            (res.spot_car_info if label == "spot" else res.car_info).add(data, t_ns)
        elif kind is P.PacketKind.RT_LAP:
            res.rt_laps.append(P.parse_rt_lap(data))

    try:
        probe.open("update")
        probe.handshake("update", attempts, attempt_interval_s, on_packet)
        hs = res.handshake
        probe.start_capture(
            out,
            CaptureMeta(
                source=f"ac-probe:{port}",
                game_hint=CAPTURE_GAME_HINT,
                synthetic=synthetic,
                description=("SYNTHETIC dry run (fake loopback server) - " if synthetic else "")
                + f"Assetto Corsa remote telemetry live probe ({platform})",
                extra={
                    "probe": "scripts/probe_ac.py",
                    "target": f"{ip}:{port}",
                    "platform": platform,
                    "note": note,
                    "seconds": seconds,
                    "spot_seconds": spot_seconds,
                    "handshake": None
                    if hs is None
                    else {"size": hs.size, "car": hs.car_name, "track": hs.track_name, "config": hs.track_config},
                    "ops_before_capture": list(res.ops),
                    "summary": "see the .json written next to this capture for the full op log and checks",
                },
            ),
        )
        if hs is None:
            if res.reply_sizes:
                res.verdict, res.exit_code = "unexpected_reply", EXIT_UNEXPECTED
            elif res.refused:
                res.verdict, res.exit_code = "refused", EXIT_REFUSED
            return res
        res.verdict, res.exit_code = "handshake_only", EXIT_HANDSHAKE_ONLY
        phase[0] = "update"
        printer(f"[update] SUBSCRIBE_UPDATE: recording for {seconds:g} s")
        probe.send("update", P.Operation.SUBSCRIBE_UPDATE)
        probe.pump(time.monotonic() + seconds, on_packet)
        if spot_seconds > 0:
            phase[0] = "spot"
            spot_end = time.monotonic() + spot_seconds
            probe.open("spot")
            if probe.handshake("spot", attempts, attempt_interval_s, on_packet):
                printer(f"[spot] SUBSCRIBE_SPOT: recording for {max(0.0, spot_end - time.monotonic()):.0f} s")
                probe.send("spot", P.Operation.SUBSCRIBE_SPOT)
            probe.pump(spot_end, on_packet)
        if res.car_info.count:
            res.verdict, res.exit_code = "streaming", EXIT_STREAMING
        return res
    finally:
        probe.close()
        if probe.writer is None:  # failed before the capture opened (e.g. socket error): keep what arrived
            probe.start_capture(out, CaptureMeta(source=f"ac-probe:{port}", game_hint="ac-remote", synthetic=synthetic))
        assert probe.writer is not None
        probe.writer.close()
        res.summary = out.with_name(out.name + ".json")
        res.summary.write_text(
            json.dumps(_summary(res, ip, port, platform, note, synthetic), indent=2), encoding="utf-8"
        )
        res.lines = _describe(res, ip, port, seconds)
        for line in res.lines:
            printer(line)


def check_target(ip: str) -> str:
    """Only a private-LAN (or loopback) IPv4 unicast address may be probed: a typo must never reach the internet."""
    try:
        target = validate_console_ip(ip, allow_loopback=True)
    except ValueError as e:
        raise ValueError(f"{e} - give the console's / PC's private LAN IPv4 address (e.g. 192.168.1.50)") from e
    if target is None:
        raise ValueError("give the console's / PC's private LAN IPv4 address (e.g. 192.168.1.50)")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", help="LAN IPv4 address of the PS4/PS5/PC running AC")
    ap.add_argument("--port", type=int, default=P.AC_PORT)
    ap.add_argument("--out", type=Path, required=True, help="where to write the .pwcap recording (+ .json summary)")
    ap.add_argument("--seconds", type=float, default=20.0, help="how long to record after SUBSCRIBE_UPDATE")
    ap.add_argument("--attempts", type=int, default=MAX_ATTEMPTS, help=f"handshake attempts (max {MAX_ATTEMPTS})")
    ap.add_argument("--spot-seconds", type=float, default=0.0, help="then also SUBSCRIBE_SPOT (second socket)")
    ap.add_argument("--platform", choices=("ps5", "ps4", "pc", "xbox", "unknown"), default="unknown")
    ap.add_argument("--note", default="", help="AC version, firmware, game mode, car/track (stored in the capture)")
    ap.add_argument("--force", action="store_true", help="overwrite --out if it exists")
    ap.add_argument("--dry-run", action="store_true", help="probe a SYNTHETIC loopback fake server instead")
    a = ap.parse_args(argv)

    if a.out.exists() and not a.force:
        print(f"{a.out} exists (use --force to overwrite)", file=sys.stderr)
        return EXIT_USAGE
    total = a.seconds + a.spot_seconds
    if not a.seconds > 0 or a.spot_seconds < 0 or total > MAX_TOTAL_S or not 1 <= a.port <= 65535:
        print(f"--seconds > 0, --spot-seconds >= 0, together <= {MAX_TOTAL_S:g}; --port 1..65535", file=sys.stderr)
        return EXIT_USAGE
    common: dict[str, Any] = {
        "seconds": a.seconds,
        "attempts": a.attempts,
        "spot_seconds": a.spot_seconds,
        "platform": a.platform,
        "note": a.note,
    }
    if a.dry_run:
        from pitwall.sim.ac_stream import FakeAcServer

        print("DRY RUN: probing a SYNTHETIC fake AC server on 127.0.0.1 (no packet leaves this machine)")
        rt_lap = P.encode_rt_lap(0, 1, "PITWALL-SYNTHETIC", P.SYNTHETIC_CAR_NAME, 90_000)
        with FakeAcServer(rate_hz=100.0, rt_lap=rt_lap) as srv:
            res = run_probe("127.0.0.1", srv.port, a.out, synthetic=True, **common)
        return res.exit_code
    if not a.ip:
        print("--ip is required (or use --dry-run)", file=sys.stderr)
        return EXIT_USAGE
    try:
        ip = check_target(a.ip)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return EXIT_USAGE
    print(
        "Switch the Assetto Corsa integration Off on pitwall's Connect page while this runs: the game may serve only "
        "one client, and the service re-registering would make this recording look unstable."
    )
    return run_probe(ip, a.port, a.out, **common).exit_code


if __name__ == "__main__":
    raise SystemExit(main())
