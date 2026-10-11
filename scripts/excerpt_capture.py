"""Cut time windows out of a real ``.pwcap`` into a small, highly compressed recorded-tier fixture.

Payloads and receive timestamps are copied byte-for-byte (nothing is decoded, edited or resampled), so the
excerpt is still real game output. The windows are recorded in the fixture metadata because the gaps
between them are an artefact of excerpting, not of the game.

    uv run python scripts/excerpt_capture.py data/captures/X.pwcap tests/fixtures/recorded/f1-25/Y.pwcap \\
        --window 668:682 --window 762:772 --description "F1 25 PS5 Austria race excerpt"

Window bounds are seconds from the first packet in the source capture.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pitwall.ingest.capture import CaptureMeta, CaptureReader, CaptureWriter


def parse_window(raw: str) -> tuple[float, float]:
    start, end = (float(x) for x in raw.split(":", 1))
    if end <= start:
        raise argparse.ArgumentTypeError(f"empty window {raw!r}")
    return start, end


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("dest", type=Path)
    ap.add_argument("--window", type=parse_window, action="append", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--level", type=int, default=19)
    a = ap.parse_args()

    reader = CaptureReader(a.source)
    if reader.meta.synthetic:
        raise SystemExit("refusing to excerpt a synthetic capture into the recorded tier")
    windows = sorted(a.window)
    meta = CaptureMeta(
        created_unix=reader.meta.created_unix,
        source=reader.meta.source,
        game_hint=reader.meta.game_hint,
        synthetic=False,
        description=a.description or reader.meta.description,
        extra={
            **reader.meta.extra,
            "excerpt_of": a.source.name,
            "excerpt_windows_s": [list(w) for w in windows],
            "note": "gaps between windows are excerpt artefacts, not game behaviour",
        },
    )
    t0: int | None = None
    kept = 0
    with CaptureWriter(a.dest, meta, level=a.level, flush_every_s=3600.0) as w:
        for pk in reader:
            t0 = pk.t_recv_ns if t0 is None else t0
            t = (pk.t_recv_ns - t0) / 1e9
            if any(lo <= t < hi for lo, hi in windows):
                w.write(pk.t_recv_ns, pk.src_port, pk.data)
                kept += 1
    print(f"{kept} packets -> {a.dest} ({a.dest.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
