from __future__ import annotations

import os
from pathlib import Path

import pytest

from pitwall.ingest.capture import (
    BackgroundCaptureWriter,
    CapturedPacket,
    CaptureMeta,
    CaptureReader,
    CaptureWriter,
    write_capture,
)


def _packets(n: int) -> list[CapturedPacket]:
    return [CapturedPacket(1_000_000 * i, 20777, os.urandom(50 + i % 1300)) for i in range(n)]


def test_roundtrip_preserves_bytes_order_and_meta(tmp_path: Path) -> None:
    pkts = _packets(500)
    path = tmp_path / "a.pwcap"
    write_capture(path, pkts, CaptureMeta(game_hint="f1_25", synthetic=True, description="t"))
    reader = CaptureReader(path)
    assert reader.meta.game_hint == "f1_25"
    assert reader.meta.synthetic is True
    got = list(reader)
    assert got == pkts
    assert reader.truncated is False


def test_truncated_capture_yields_complete_prefix(tmp_path: Path) -> None:
    pkts = _packets(2000)
    path = tmp_path / "t.pwcap"
    w = CaptureWriter(path, CaptureMeta())
    for p in pkts:
        w.write(p.t_recv_ns, p.src_port, p.data)
    w.flush()  # simulate the periodic block flush before a crash; never closed
    size = path.stat().st_size
    with path.open("r+b") as fh:
        fh.truncate(size - 37)  # cut mid-block
    got = list(CaptureReader(path))
    assert 0 < len(got) <= len(pkts)
    assert got == pkts[: len(got)]


def test_rejects_non_capture_file(tmp_path: Path) -> None:
    path = tmp_path / "x.pwcap"
    import zstandard

    path.write_bytes(zstandard.ZstdCompressor().compress(b"NOTACAPTURE"))
    with pytest.raises(ValueError):
        CaptureReader(path)


def test_background_writer_writes_everything(tmp_path: Path) -> None:
    pkts = _packets(3000)
    path = tmp_path / "bg.pwcap"
    bw = BackgroundCaptureWriter(path, CaptureMeta())
    for p in pkts:
        bw.submit(p)
    bw.close()
    assert bw.dropped == 0
    assert list(CaptureReader(path)) == pkts
