"""Raw packet capture format (``.pwcap``) - write and read.

Layout (the whole file is one zstd stream, flushed block-wise so a crash loses < 1 s of data)::

    b"PWCAP1\\n"
    <uint32 LE json_len><json metadata bytes>
    repeated records:
        <int64 LE t_recv_ns><uint16 LE src_port><uint32 LE length><payload bytes>

``t_recv_ns`` is the host monotonic clock at receipt; replay preserves the inter-packet spacing.
Raw payloads are stored exactly as received, so improved decoders can reprocess historical sessions.
"""

from __future__ import annotations

import io
import json
import logging
import queue
import struct
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import zstandard

log = logging.getLogger(__name__)

MAGIC = b"PWCAP1\n"
_REC = struct.Struct("<qHI")
_LEN = struct.Struct("<I")
MAX_PAYLOAD = 65535


@dataclass(slots=True, frozen=True)
class CapturedPacket:
    t_recv_ns: int
    src_port: int
    data: bytes


@dataclass(slots=True)
class CaptureMeta:
    created_unix: float = field(default_factory=time.time)
    source: str = "udp"
    game_hint: str | None = None
    synthetic: bool = False  # True for generated telemetry - never evidence of live compatibility
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "created_unix": self.created_unix,
                "source": self.source,
                "game_hint": self.game_hint,
                "synthetic": self.synthetic,
                "description": self.description,
                "extra": self.extra,
            }
        ).encode()

    @classmethod
    def from_json(cls, raw: bytes) -> CaptureMeta:
        d = json.loads(raw)
        return cls(
            created_unix=d.get("created_unix", 0.0),
            source=d.get("source", "udp"),
            game_hint=d.get("game_hint"),
            synthetic=bool(d.get("synthetic", False)),
            description=d.get("description", ""),
            extra=d.get("extra", {}),
        )


class CaptureWriter:
    """Synchronous capture writer. Not thread-safe; see ``BackgroundCaptureWriter`` for live use."""

    def __init__(self, path: Path, meta: CaptureMeta, level: int = 3, flush_every_s: float = 1.0) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: BinaryIO = path.open("wb")
        self._zw = zstandard.ZstdCompressor(level=level).stream_writer(self._fh, closefd=False)
        self._zw.write(MAGIC)
        meta_raw = meta.to_json()
        self._zw.write(_LEN.pack(len(meta_raw)) + meta_raw)
        self._flush_every_ns = int(flush_every_s * 1e9)
        self._last_flush = time.monotonic_ns()
        self.packets = 0
        self.bytes_in = 0
        self.closed = False

    def write(self, t_recv_ns: int, src_port: int, data: bytes) -> None:
        if len(data) > MAX_PAYLOAD:
            raise ValueError(f"payload too large: {len(data)}")
        self._zw.write(_REC.pack(t_recv_ns, src_port, len(data)))
        self._zw.write(data)
        self.packets += 1
        self.bytes_in += len(data)
        now = time.monotonic_ns()
        if now - self._last_flush >= self._flush_every_ns:
            self.flush()

    def flush(self) -> None:
        self._zw.flush(zstandard.FLUSH_BLOCK)
        self._fh.flush()
        self._last_flush = time.monotonic_ns()

    def close(self) -> None:
        if self.closed:
            return
        self._zw.flush(zstandard.FLUSH_FRAME)
        self._zw.close()  # type: ignore[no-untyped-call]
        self._fh.close()
        self.closed = True

    def __enter__(self) -> CaptureWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class BackgroundCaptureWriter:
    """Moves compression and disk I/O off the receive thread.

    ``submit`` never blocks. If the queue overflows (disk stalled for many seconds) packets are counted
    in ``dropped`` and a warning is logged - capture loss is always visible, never silent.
    """

    def __init__(self, path: Path, meta: CaptureMeta, max_queue: int = 200_000) -> None:
        self._writer = CaptureWriter(path, meta)
        self._q: queue.Queue[CapturedPacket | None] = queue.Queue(maxsize=max_queue)
        self.dropped = 0
        self._thread = threading.Thread(target=self._run, name="capture-writer", daemon=True)
        self._thread.start()

    @property
    def path(self) -> Path:
        return self._writer.path

    @property
    def packets(self) -> int:
        return self._writer.packets

    def submit(self, pkt: CapturedPacket) -> None:
        try:
            self._q.put_nowait(pkt)
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 1000 == 0:
                log.warning("capture queue full; %d packets not written to %s", self.dropped, self.path)

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                break
            try:
                self._writer.write(item.t_recv_ns, item.src_port, item.data)
            except Exception:  # pragma: no cover - disk errors
                log.exception("capture write failed")
        self._writer.close()

    def close(self, timeout: float = 10.0) -> None:
        self._q.put(None)
        self._thread.join(timeout)


class CaptureReader:
    """Streams packets from a ``.pwcap`` file. Tolerates truncated files (e.g. after a crash)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.truncated = False
        with self._open() as r:
            self.meta = self._read_header(r)

    def _open(self) -> io.BufferedReader:
        fh = self.path.open("rb")
        reader = zstandard.ZstdDecompressor().stream_reader(fh, closefd=True, read_across_frames=True)
        return io.BufferedReader(reader, buffer_size=1 << 20)

    @staticmethod
    def _read_exact(r: io.BufferedReader, n: int) -> bytes:
        buf = r.read(n)
        return buf if buf is not None else b""

    def _read_header(self, r: io.BufferedReader) -> CaptureMeta:
        magic = self._read_exact(r, len(MAGIC))
        if magic != MAGIC:
            raise ValueError(f"{self.path} is not a pwcap file")
        (n,) = _LEN.unpack(self._read_exact(r, _LEN.size))
        return CaptureMeta.from_json(self._read_exact(r, n))

    def __iter__(self) -> Iterator[CapturedPacket]:
        with self._open() as r:
            self._read_header(r)
            while True:
                try:
                    head = self._read_exact(r, _REC.size)
                    if not head:
                        return
                    if len(head) < _REC.size:
                        self.truncated = True
                        return
                    t_ns, port, length = _REC.unpack(head)
                    data = self._read_exact(r, length)
                    if len(data) < length:
                        self.truncated = True
                        return
                except zstandard.ZstdError:
                    self.truncated = True
                    log.warning("capture %s is truncated; stopping at last complete record", self.path)
                    return
                yield CapturedPacket(t_ns, port, data)


def write_capture(path: Path, packets: Iterator[CapturedPacket] | list[CapturedPacket], meta: CaptureMeta) -> int:
    with CaptureWriter(path, meta) as w:
        for p in packets:
            w.write(p.t_recv_ns, p.src_port, p.data)
        return w.packets
