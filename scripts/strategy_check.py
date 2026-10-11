"""Run the race strategy engine headless over a capture: per-lap records, pit stops, the final view and the calls.

    uv run python scripts/strategy_check.py <capture.pwcap> [--uid UID] [--json]
    uv run python scripts/strategy_check.py --synthetic race-strategy-demo [--json]

Decodes with ``F1Adapter`` and feeds a ``StrategyEngine`` per game session UID directly: no database, no radio, no
network. Read-only on the capture; nothing is written. Run it with the working directory in a scratch folder when
the capture is someone's real session (real captures carry other players' names: never commit them or this
script's output for them).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pitwall.adapters.base import PacketRejected
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.model.telemetry import SessionInfo
from pitwall.strategy.engine import StrategyEngine


def run(packets: list[CapturedPacket] | Any, uid_filter: str | None = None) -> list[dict[str, Any]]:
    adapter = F1Adapter(field_hz=0.0)
    engines: list[tuple[str, StrategyEngine, dict[str, Any]]] = []
    cur: StrategyEngine | None = None
    cur_uid: str | None = None
    out: dict[str, Any] = {}
    for p in packets:
        try:
            items = adapter.decode(p.data, p.t_recv_ns)
        except PacketRejected:
            continue
        for item in items:
            if isinstance(item, SessionInfo) and item.session_uid and item.session_uid != cur_uid:
                if cur is not None:
                    cur.end()
                cur_uid = item.session_uid
                cur = StrategyEngine(f"uid:{cur_uid}")
                out = {"records": {}, "stops": [], "calls": []}
                engines.append((cur_uid, cur, out))
            if cur is None:
                continue
            cur.feed(item)
            for lap, rec in cur.take_records():
                out["records"][lap] = rec
            out["stops"].extend(cur.take_stops())
            out["calls"].extend(c.to_dict() for c in cur.take_calls())
    results: list[dict[str, Any]] = []
    for uid, eng, o in engines:
        if uid_filter is not None and uid != uid_filter:
            continue
        eng.end()
        for lap, rec in eng.take_records():
            o["records"][lap] = rec
        o["stops"].extend(eng.take_stops())
        stops: dict[tuple[int, int], dict[str, Any]] = {}
        for s in o["stops"]:
            stops[(s["car_index"], s["entry_lap"])] = s  # upsert semantics, like the database
        results.append(
            {
                "uid": uid,
                "mode": eng.mode,
                "reason": eng.reason,
                "records": [o["records"][k] for k in sorted(o["records"])],
                "stops": list(stops.values()),
                "calls": o["calls"],
                "view": eng.view(),
                "burn_model": None
                if eng.d.burn is None
                else {"b0": eng.d.burn.b0, "b1": eng.d.burn.b1, "r2": eng.d.burn.r2, "windows": eng.d.burn.windows},
                "burn_windows": len(eng.burn.windows),
                "pit_loss": eng.pits.green_loss(),
                "pit_entry_m": eng.pits.pit_entry_m(),
            }
        )
    return results


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def print_report(res: dict[str, Any]) -> None:
    print(f"=== session uid {res['uid']}: mode {res['mode']}" + (f" ({res['reason']})" if res["reason"] else ""))
    print(
        "lap  pos  time      ahead(car)    behind(car)   pit   stops cmp     age wear(FL,FR,RL,RR)   fuel  /lap  "
        "margin game  sc     weather   window       uc   threat"
    )
    for r in res["records"]:
        w = r.get("window")
        win = "-" if not w else f"{w['open']}-{w['close']}" + (f"~{w['ideal']}" if w.get("ideal") else "")
        print(
            f"{r['lap']:>3}  {_fmt(r['position']):>3}  {_fmt(r['lap_time_ms']):>8}  "
            f"{_fmt(r['gap_ahead_ms']):>6}({_fmt(r['ahead_car']):>2})    "
            f"{_fmt(r['gap_behind_ms']):>6}({_fmt(r['behind_car']):>2})"
            f"   {_fmt(r['pit']):>5} {_fmt(r['stops']):>5} {_fmt(r['compound']):>7} {_fmt(r['tyre_age_laps']):>3} "
            f"{_fmt(r['wear_pct']):>18}  {_fmt(r['fuel_kg']):>5} {_fmt(r['fuel_per_lap_kg'], 3):>5} "
            f"{_fmt(r['fuel_margin_laps']):>6} {_fmt(r['game_fuel_margin_laps']):>5} {r['safety_car']:>6} "
            f"{_fmt(r['weather']):>9} {win:>12} "
            f"{_fmt(r['undercut_ahead']):>8} {_fmt(r['undercut_threat']):>8}"
        )
    print("pit visits:")
    for s in sorted(res["stops"], key=lambda s: (s["entry_lap"], s["car_index"])):
        print(
            f"  car {s['car_index']:>2}{' (player)' if s['is_player'] else ''}: L{s['entry_lap']} at "
            f"{_fmt(s['entry_lap_distance_m'], 0)} m -> L{_fmt(s['exit_lap'])} at "
            f"{_fmt(s['exit_lap_distance_m'], 0)} m; "
            f"lane {_fmt(s['lane_time_ms'])} ms, stationary {_fmt(s['stationary_ms'])} ms, laps {s['laps_ms']}, "
            f"pace before {_fmt(s['pace_before_ms'])} after {_fmt(s['pace_after_ms'])}, loss {_fmt(s['pit_loss_ms'])} "
            f"ms, neutralised {_fmt(s['neutralised'])}, excluded {_fmt(s['excluded'])}, "
            f"{_fmt(s['compound_before'])} -> {_fmt(s['compound_after'])}"
        )
    print(f"session pit loss: {res['pit_loss']}; pit entry {res['pit_entry_m']} m")
    print(f"burn model: {res['burn_model']} ({res['burn_windows']} windows)")
    print("calls:")
    for c in res["calls"]:
        print(f"  L{c['lap']} [{c['level']}/{c['topic']}] {c['text']}")
    print("final view:")
    print(json.dumps(res["view"], indent=1)[:6000])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("capture", nargs="?", type=Path)
    ap.add_argument("--uid", help="only this game session UID")
    ap.add_argument("--json", action="store_true", help="print JSON instead of tables")
    ap.add_argument("--synthetic", metavar="SCENARIO", help="run a synthetic scenario instead of a capture")
    args = ap.parse_args(argv)
    if args.synthetic:
        from pitwall.sim.strategy_stream import SCENARIOS

        if args.synthetic not in SCENARIOS:
            print(f"unknown scenario; options: {sorted(SCENARIOS)}", file=sys.stderr)
            return 2
        packets, _truth = SCENARIOS[args.synthetic]()
        results = run(packets, args.uid)
    elif args.capture is not None:
        results = run(CaptureReader(args.capture), args.uid)
    else:
        ap.print_usage(sys.stderr)
        return 2
    if args.json:
        print(json.dumps(results, indent=1))
    else:
        for res in results:
            print_report(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
