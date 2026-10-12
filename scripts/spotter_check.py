"""Score the spotter on real captures (scratch copies only): per-session and total rows at 60, 20 and 10 Hz.

    uv run python scripts/spotter_check.py /tmp/scratch/caps/*.pwcap [--rates 1,3,6] [--json out.json] [--sessions]

``--rates`` are decimation factors of the capture's Motion stream (1 = as recorded, 3 = every third packet: the game's
20 Hz send rate from a 60 Hz capture, 6 = 10 Hz). The ground truth is geometric, from the same positions as the
spotter (``pitwall.spotter.score``): it validates data, timing and the state machine, not what the driver saw.
Prints counts and track ids only: no participant names are read (only Motion, Session, LapData and Event packets are
decoded). Never point it at a capture you may not keep on this machine; delete scratch copies after.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pitwall.spotter.score import public, score_capture, summarise

ACCEPT_60 = {"long": 1.0, "precision": 0.99, "wrong_clear_rate": 0.01, "flap_rate": 0.10, "p50": 55, "p95": 70}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captures", nargs="+", type=Path)
    ap.add_argument("--rates", default="1,3,6", help="decimation factors (1 = as recorded)")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--sessions", action="store_true", help="print every session's row")
    a = ap.parse_args(argv)
    out: dict[str, object] = {}
    for dec in (int(x) for x in a.rates.split(",")):
        t0 = time.perf_counter()
        rows = []
        for path in a.captures:
            got = score_capture(path, decimate=dec)
            rows.extend(got)
            if a.sessions:
                for r in got:
                    print(f"[x{dec}] {path.name}", json.dumps(public(r)), flush=True)
        total = summarise(rows)
        total["decimate"] = dec
        total["seconds"] = round(time.perf_counter() - t0, 1)
        print(f"TOTAL x{dec}:", json.dumps(total), flush=True)
        out[f"x{dec}"] = {"total": total, "sessions": [public(r) for r in rows]}
    if a.json is not None:
        a.json.write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
