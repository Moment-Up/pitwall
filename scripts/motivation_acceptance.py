"""Acceptance check of goals, badges, streaks, recaps and the weekly digest on real recorded captures (scratch only).

    cd <scratch> && uv run --project ~/Projects/pitwall-motivation python \\
        ~/Projects/pitwall-motivation/scripts/motivation_acceptance.py --data-dir <scratch>/data \\
        [--skill intermediate|beginner] [--now 2026-10-12] <captures...>

1. Replays the captures in file-name order into a fresh database under ``--data-dir`` (``Runtime.start_replay`` at
   full speed: no port is bound, nothing is sent anywhere).
2. Retags the replayed sessions IN THAT SCRATCH DATABASE ONLY: driver "Acceptance" (``--skill``), source
   ``udp:acceptance``, and ``started_unix`` from the capture name (``YYYYMMDD-HHMMSS``, local time) plus the order
   within the capture, so they count as that driver's real driving on the day it was recorded.
3. Prints JSON: per-session outcomes, recaps, suggestions per scope, badges, streaks and the digest of the week
   of the last session (and of ``--now``'s week).

It refuses a data directory inside a git worktree or the service's own data folders. It never copies or writes
captures; delete the scratch directory afterwards.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.drivers import default_initials
from pitwall.motivation import rules
from pitwall.motivation.service import MotivationService, load_history
from pitwall.storage import repo

_STAMP = re.compile(r"(\d{8})-(\d{6})")
FORBIDDEN = (Path.home() / "Projects" / "pitwall" / "data", Path.home() / "Projects" / "pitwall-release" / "data")


def _inside_git(path: Path) -> bool:
    return any((p / ".git").exists() for p in (path, *path.parents))


def check_data_dir(path: Path) -> Path:
    path = path.expanduser().resolve()
    for bad in FORBIDDEN:
        bad = bad.resolve()
        if path == bad or bad in path.parents:
            raise SystemExit(f"refusing to use {path}: that is the service's own data")
    if _inside_git(path):
        raise SystemExit(f"refusing to use {path}: it is inside a git worktree (use a scratch directory)")
    if (path / "pitwall.sqlite3").exists():
        raise SystemExit(f"refusing to use {path}: it already holds a database (use an empty scratch directory)")
    return path


def capture_unix(name: str) -> float | None:
    m = _STAMP.search(name)
    if m is None:
        return None
    return time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))


def replay(rt: Runtime, captures: list[Path]) -> None:
    for p in captures:
        t0 = time.perf_counter()
        r = rt.start_replay(p, speed=None)
        r.done.wait()
        rt.worker.join()
        rt.writer.flush()
        print(f"replayed {p.name}: {r.sent} packets in {time.perf_counter() - t0:.1f} s", file=sys.stderr)


def retag(rt: Runtime, skill: str) -> int:
    prefs = {"skill_level": skill, "initials": default_initials("Acceptance")}

    def job(c: Any) -> int:
        row = repo.find_driver_by_name(c, "Acceptance")
        did = int(row["id"]) if row is not None else repo.insert_driver(c, "Acceptance", prefs)
        repo.update_driver(c, did, preferences=prefs)
        sessions = repo.list_sessions(c, limit=100_000)
        sessions.sort(key=lambda s: (s["started_unix"], s["id"]))
        order: dict[str, int] = {}
        for s in sessions:
            if s["synthetic"]:
                continue
            src = str(s["source"])
            base = capture_unix(src)
            i = order.get(src, 0)
            order[src] = i + 1
            started = (base if base is not None else float(s["started_unix"])) + i
            repo.rewrite_session_origin(
                c, s["id"], source="udp:acceptance", started_unix=started, ended_unix=started + 600
            )
            repo.set_session_driver(c, s["id"], did)
        return did

    return int(rt.writer.call(job))


def session_rows(svc: MotivationService, driver_id: int) -> list[dict[str, Any]]:
    with svc.db.read() as c:
        h = load_history(c, driver_id)
    out = []
    for s in h.sessions:
        laps = h.laps_of(s.id)
        best = rules.fastest_clean(laps)
        w3 = rules.best_window(laps, 3, s.session_type)
        w5 = rules.best_window(laps, 5, s.session_type)
        row: dict[str, Any] = {
            "session_id": s.id,
            "started": datetime.fromtimestamp(s.started_unix).strftime("%Y%m%d-%H%M%S"),
            "game": s.game,
            "track": s.track_name,
            "track_id": s.track_id,
            "car": s.car_name,
            "car_id": s.car_id,
            "type": s.session_type,
            "total_laps": s.total_laps,
            "laps": [lap.lap_number for lap in laps],
            "clean": sum(1 for lap in laps if lap.clean),
            "best_ms": None if best is None else best.lap_time_ms,
            "best_run": len(rules.best_run(laps)),
            "w3_ms": None if w3 is None else w3.spread_ms,
            "w5_ms": None if w5 is None else w5.spread_ms,
            "ideal_ms": rules.ideal_lap(laps),
        }
        if s.is_race and s.is_f1:
            o = rules.race_outcome(s, laps, h.events.get(s.id, ()))
            row["race"] = {
                "finished": o.finished,
                "from_start": o.from_start,
                "evaluable": o.evaluable,
                "contacts": o.contacts,
                "penalties": o.penalties,
                "warnings": o.warnings,
                "flashbacks": o.flashbacks,
                "resets": o.resets,
                "no_penalties": o.no_penalties,
                "no_contact": o.no_contact,
            }
        out.append(row)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--skill", choices=("beginner", "intermediate", "advanced"), default="intermediate")
    ap.add_argument("--now", default=None, help="ISO date or datetime the reads are made at (default: now)")
    ap.add_argument("captures", nargs="+", type=Path)
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    data = check_data_dir(a.data_dir)
    captures = sorted((p.resolve() for p in a.captures), key=lambda p: p.name)
    now = datetime.fromisoformat(a.now).timestamp() if a.now else time.time()

    rt = Runtime(Settings(data_dir=data, llm_enabled=False, voice_enabled=False))
    try:
        replay(rt, captures)
        rt.motivation.join()
        driver_id = retag(rt, a.skill)
    finally:
        rt.close()

    from pitwall.storage.db import Database

    db = Database(data / "pitwall.sqlite3")
    svc = MotivationService(db, clock=lambda: now)
    sessions = session_rows(svc, driver_id)
    scopes: dict[tuple[str, str, str | None], str] = {}
    for s in sessions:
        if s["track_id"] is not None:
            scopes[(s["game"], s["track_id"], s["car_id"])] = s["session_id"]
    suggestions = {}
    for (game, track, car), sid in scopes.items():
        res = svc.suggestions_response(driver_id, from_session_id=sid)
        suggestions[f"{game} {track} {car}"] = {
            "scope_text": None if res["scope"] is None else res["scope"]["track_name"],
            "suggestions": [
                {"title": x["title"], "kind": x["kind"], "target": x["target"], "basis": x["basis"]["text"]}
                for x in res["suggestions"]
            ],
            "none_reason": res["none_reason"],
        }
    recaps = {}
    for s in sessions:
        r = svc.recap(s["session_id"])
        assert r is not None
        simple = r["simple"]
        things: dict[str, Any] = {}
        for k, v in r["things"].items():
            text = None if v is None else (v["text_simple"] if simple else v["text"])
            things[k] = None if v is None else {"source": v["source"], "text": text, "evidence": v["evidence"]}
        things["why_empty"] = r["why_empty"]
        things["badges_earned"] = [b["key"] for b in r["badges_earned"]]
        recaps[f"{s['started']} {s['track']} {s['type']} {s['session_id']}"] = things
    badges = svc.badges_response(driver_id)
    with db.read() as c:
        last_week = rules.week_of(max(s0.started_unix for s0 in load_history(c, driver_id).sessions))
    digest = svc.digest(driver_id, last_week)
    now_digest = svc.digest(driver_id, date.fromtimestamp(now))
    out = {
        "driver_id": driver_id,
        "skill": a.skill,
        "now": datetime.fromtimestamp(now).isoformat(),
        "sessions": sessions,
        "suggestions": suggestions,
        "recaps": recaps,
        "badges": [{"key": b["key"], "title": b["title"], "session_id": b["session_id"]} for b in badges["badges"]],
        "streaks": badges["streaks"],
        "digest": {k: v for k, v in digest.items() if k != "markdown"},
        "digest_markdown": digest["markdown"],
        "digest_now_week": {"week_start": now_digest["week_start"], "headline": now_digest["headline"]},
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
