"""Recorded acceptance for coachref (reference choice + practice drills) on real F1 captures. Dev tool.

    uv run python scripts/coachref_check.py data/captures/X.pwcap [more.pwcap ...] [--drill T7] [--laps 3]

Each capture is decoded with the production F1 adapter and replayed through the real pipeline (``LapProcessor`` +
``LiveState`` + ``CueEngine`` + ``CoachRef``) into a scratch database in a temporary directory that is deleted
afterwards. Nothing is sent anywhere: no network, no ports, no LLM, no voice. Two demo drivers stand in for the
household (never the players' names in the capture): **Ben** owns a session holding the capture's fastest clean
lap, **Ann** a session holding the other clean laps, and Ann's reference choice is "Ben's best". The script prints
the reference, Ann's reworded observations, the braking calls with Ann's own points and the drill outcomes, and
exits non-zero when an invariant fails:

* Ann's first lap: the reference is Ben's lap with ``brake_clamped``, and there is no braking call (no point of her
  own yet: ``no braking points of your own yet``).
* Every braking call is at or before Ann's own braking point at that corner (``brake_clamp_m``), never later.
* Observations against Ben name him and never say "your reference"; incidents keep their text; no text says
  "brake later"; every ``short`` is at most 48 characters.
* A synthetic copy of Ann's session never sees Ben's lap (synthetic sessions use the driver's own laps).
* A brake-point drill (``--drill`` corner, else the first corner with one available) on copies of Ann's recorded laps
  re-fed as attempts (not laps driven for the drill): the target is never later than Ann's own point, an attempt
  past the point is a hit only when the corner was faster, the drill completes after ``--laps`` attempts, and its
  texts follow the same wording rules. Only with 3 or more clean laps (drills need a learnt track model); captures
  with 2 clean laps run the other checks.
* With Ben's braking assist changed in the database, "Ben's best" is unavailable with the reason
  "Ben's laps here used a different braking assist", and Ann's next lap falls back to her own lap with that reason.

Evidence tier: recorded (the owner's real captures, replayed). Not live validation.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.analysis.coaching import SHORT_MAX_CHARS
from pitwall.analysis.laps import LapAssembler, LapTrace
from pitwall.analysis.track_identity import corner_texts
from pitwall.coach.cues import NO_OWN_POINTS
from pitwall.core.coachref import LEGACY_REASON, ChoiceRequest, CoachRef, CoachRefError, DrillRequest
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.drivers import DriverService
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import CarFrame, LapCompletion, SessionInfo
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter, dumps

T = TypeVar("T")
FORBIDDEN = ("brake later", "later braking point")


def decode_f1(path: Path) -> tuple[list[LapTrace], SessionInfo] | None:
    """The player's laps and the last session info of an F1 capture (None: not an F1 capture / no session)."""
    meta = CaptureReader(path).meta
    hint = str(meta.game_hint or "")
    if hint and "f1" not in hint:
        return None
    adapter = F1Adapter()
    laps: list[LapTrace] = []
    info: SessionInfo | None = None
    asm = LapAssembler(laps.append)
    for p in CaptureReader(path):
        for e in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(e, SessionInfo):
                info = e
                asm.set_track_length(e.track_length_m)
            elif isinstance(e, CarFrame):
                asm.feed(e)
            elif isinstance(e, LapCompletion):
                asm.feed_completion(e)
    return (laps, info) if info is not None else None


def _run_now[T](fn: Callable[[], T]) -> Future[T]:
    fut: Future[T] = Future()
    try:
        fut.set_result(fn())
    except BaseException as e:
        fut.set_exception(e)
    return fut


def _copy(lap: LapTrace, number: int) -> LapTrace:
    return LapTrace(
        lap_number=number,
        channels=lap.channels,
        lap_time_ms=lap.lap_time_ms,
        sector_times_ms=list(lap.sector_times_ms),
        valid=lap.valid,
        flags=set(lap.flags),
        meta=dict(lap.meta),
    )


def _ctx(info: SessionInfo) -> dict[str, Any]:
    return {
        "game": info.game.value,
        "track_id": info.track_id,
        "track_name": info.track_name,
        "track_length_m": info.track_length_m,
        "car_id": info.car_id,
        "weather": info.weather.condition,
        "track_temp_c": info.weather.track_temp_c,
        "assists": dict(info.assists),
        "setup_fp": None,
    }


@dataclass
class Report:
    capture: str
    failures: list[str] = field(default_factory=list)
    skipped: str | None = None
    lines: list[str] = field(default_factory=list)
    numbers: dict[str, Any] = field(default_factory=dict)

    def say(self, line: str) -> None:
        self.lines.append(line)

    def check(self, ok: bool, what: str) -> None:
        if not ok:
            self.failures.append(what)
            self.lines.append(f"  FAIL {what}")


def _session(writer: DbWriter, driver: int, info: SessionInfo, sid: str, *, synthetic: bool = False) -> str:
    def job(c: sqlite3.Connection) -> None:
        repo.insert_session(c, sid, info.game.value, "udp:20777", synthetic, None, None, driver_id=driver)
        repo.update_session_info(c, sid, info)

    writer.call(job)
    return sid


def _texts_ok(rep: Report, texts: list[tuple[str, str | None]], where: str) -> None:
    for text, short in texts:
        low = text.lower()
        rep.check(not any(f in low for f in FORBIDDEN), f"{where}: an instruction to brake later: {text!r}")
        if short is not None:
            rep.check(len(short) <= SHORT_MAX_CHARS, f"{where}: short text over {SHORT_MAX_CHARS}: {short!r}")


def check_capture(path: Path, *, drill: str | None = None, drill_laps: int = 3) -> Report:
    """Run every check on one capture (see the module docstring)."""
    rep = Report(path.name)
    decoded = decode_f1(path)
    if decoded is None:
        rep.skipped = "not an F1 capture with session data"
        return rep
    laps, info = decoded
    clean = [lap for lap in laps if lap.clean and lap.lap_time_ms]
    if len(clean) < 2 or not info.track_id or not info.track_length_m:
        rep.skipped = f"{len(clean)} clean lap(s); at least 2 are needed (3 for a drill)"
        return rep
    ben_lap = min(clean, key=lambda lap: (lap.lap_time_ms or 0, lap.lap_number))
    ann_laps = [lap for lap in clean if lap is not ben_lap]
    rep.say(
        f"== {path.name}: {info.track_name} ({info.track_id}), braking assist {info.assists.get('braking')}, "
        f"Ben = lap {ben_lap.lap_number} ({ben_lap.lap_time_ms} ms), Ann = laps {[lap.lap_number for lap in ann_laps]}"
    )
    with tempfile.TemporaryDirectory(prefix="coachref-check-") as tmp:
        db = Database(Path(tmp) / "check.sqlite3")
        writer = DbWriter(db)
        live = LiveState()
        drivers = DriverService(db, writer, default_name="Ann")
        proc = LapProcessor(db, writer, live)
        svc = CoachRef(db, writer, live, drivers, run_task=_run_now, processor=proc)
        proc.coachref = svc
        try:
            _run(rep, info, ben_lap, ann_laps, db, writer, live, drivers, proc, svc, drill, drill_laps)
        finally:
            svc.close()
            writer.close()
    return rep


def _run(
    rep: Report,
    info: SessionInfo,
    ben_lap: LapTrace,
    ann_laps: list[LapTrace],
    db: Database,
    writer: DbWriter,
    live: LiveState,
    drivers: DriverService,
    proc: LapProcessor,
    svc: CoachRef,
    drill: str | None,
    drill_laps: int,
) -> None:
    ann = drivers.default_id
    ben = drivers.create("Ben").id
    ctx = _ctx(info)
    sb = _session(writer, ben, info, "ben")
    proc.process(LapJob(sb, _copy(ben_lap, ben_lap.lap_number), ctx))
    sa = _session(writer, ann, info, "ann")
    live.reset_session(sa, "udp:20777", False)
    live.on_session(info)
    live.cues.set_mode("all")  # every braking zone, so the clamp shows at every corner
    svc.set_choice(ChoiceRequest(kind="driver_best", target_driver_id=ben))
    number = 0
    for i, lap in enumerate(ann_laps):
        number += 1
        res = proc.process(LapJob(sa, _copy(lap, number), ctx))
        comp = res["comparison"]
        ref = live.reference or {}
        rep.say(
            f"  Ann lap {number} (capture lap {lap.lap_number}, {lap.lap_time_ms} ms): reference {ref.get('label')!r}"
        )
        if comp is None:
            rep.check(False, f"Ann lap {number}: no comparison against Ben's lap")
            continue
        model = proc._models.get((str(info.game.value), str(info.track_id)))
        texts = corner_texts(model) if model is not None else {}
        if i == 0:
            ben_ref = ref.get("lap_id") == comp.get("ref_lap_id") and ref.get("driver_name") == "Ben"
            rep.check(ben_ref, "lap 1: Ben's lap")
            rep.check(ref.get("brake_clamped") is True, "lap 1: brake_clamped")
            rep.check(live.cues.plan.cues == (), "lap 1: no braking call without an own point")
            rep.check(live.cues.plan.reason == NO_OWN_POINTS, f"lap 1: plan reason {live.cues.plan.reason!r}")
        clamp = comp.get("brake_clamp_m")
        rep.check(isinstance(clamp, dict), f"Ann lap {number}: brake_clamp_m present")
        ben_points = {c["corner"]: (c.get("ref") or {}).get("brake_start_m") for c in comp.get("corners") or ()}
        for cue in live.cues.plan.cues:
            own = (clamp or {}).get(cue.corner)
            label = texts[cue.corner].short if cue.corner in texts else cue.corner
            later = ben_points.get(cue.corner)
            note = ""
            if isinstance(later, float) and own is not None and later > own:
                note = f"  [clamped: Ben brakes {later - own:.1f} m later]"
                row = {"lap": number, "corner": label, "ben": round(later, 1), "own": round(own, 1)}
                rep.numbers.setdefault("clamped", []).append({**row, "cue": round(cue.target_m, 1)})
            rep.say(
                f"    call {label:>10}: Ben {later if later is None else round(later, 1)}  Ann own "
                f"{own if own is None else round(own, 1)}  -> {cue.target_m:.1f}{note}"
            )
            ok = own is not None and cue.target_m <= own + 1e-6
            rep.check(ok, f"{label}: call {cue.target_m:.1f} after own {own}")
        for o in res["observations"]:
            rep.say(f"    obs {o['kind']:>20}: {o['text']}")
            if o["kind"] != "incident":
                rep.check("Ben" in o["text"] and o.get("ref_name") == "Ben", f"obs names Ben: {o['text']!r}")
            rep.check("your reference" not in o["text"], f"obs mentions your reference: {o['text']!r}")
        _texts_ok(rep, [(o["text"], o.get("short")) for o in res["observations"]], f"Ann lap {number}")
    # synthetic sessions use the driver's own laps
    syn = _session(writer, ann, info, "ann-synthetic", synthetic=True)
    with db.read() as c:
        res_syn = svc.resolve(c, syn, ann, {**ctx, "track_length_m": info.track_length_m}, None)
    rep.check(res_syn.driver_id != ben and res_syn.reason == LEGACY_REASON, "synthetic session never sees Ben's lap")
    _drill(rep, info, ann_laps, live, proc, svc, sa, drill, drill_laps, number)
    _assist_mismatch(rep, info, ann_laps, writer, live, proc, svc, sa, ben, number + drill_laps + 1)


def _drill(
    rep: Report,
    info: SessionInfo,
    ann_laps: list[LapTrace],
    live: LiveState,
    proc: LapProcessor,
    svc: CoachRef,
    sid: str,
    corner: str | None,
    drill_laps: int,
    number: int,
) -> None:
    ctx = _ctx(info)
    model = proc._models.get((str(info.game.value), str(info.track_id)))
    learned = [c.name for c in model.corners] if model is not None else []
    if model is None or model.n_laps < 3:
        rep.say(f"  drill: not checked (the track model is learnt from {model.n_laps if model else 0} clean lap(s))")
        return
    # a corner given as a learned key ("T7") is used as it is; otherwise it is resolved like the radio does
    candidates: list[tuple[str | None, str | None]] = [(c, None) for c in learned]
    if corner:
        candidates = [(corner, None)] if corner in learned else [(None, corner)]
    view = None
    for key, ref in candidates:
        try:
            opts = svc.drill_options(corner=key, corner_ref=ref)
            if not opts["available"]:
                rep.say(f"  drill at {key or ref}: {opts['reason']}")
                continue
            kinds = {k["kind"]: k for k in opts["kinds"]}
            if not kinds.get("brake_point", {}).get("available"):
                rep.say(f"  drill at {key or ref}: {kinds.get('brake_point', {}).get('reason')}")
                continue
            view = svc.start_drill(DrillRequest(corner=key, corner_ref=ref, kind="brake_point", laps=drill_laps))
            rep.say(f"  drill options note: {kinds['brake_point'].get('note')!r}")
            break
        except CoachRefError as e:
            rep.say(f"  drill at {key or ref}: {e}")
    if view is None:
        rep.check(corner is None, f"no brake-point drill possible at {corner}")
        rep.say("  drill: none possible")
        return
    clamp = (live.last_comparison or {}).get("brake_clamp_m") or {}
    own = clamp.get(view["corner"])
    rep.say(
        f"  drill {view['corner_label']} brake point: target {view['target']:.1f} (Ann own {own}), "
        f"tolerance {view['tolerance']:.0f} m, {view['target_text']}"
    )
    rep.check(own is not None and view["target"] <= own + 1e-6, "drill target never later than Ann's own point")
    order = [ann_laps[-1], ann_laps[0]]
    for k in range(drill_laps):
        number += 1
        lap = order[k % len(order)] if len(ann_laps) > 1 else ann_laps[0]
        proc.process(LapJob(sid, _copy(lap, number), ctx))
    done = (live.coachref or {}).get("drill") or {}
    for a in done.get("attempts") or ():
        rep.say(
            f"    attempt {a['attempt']}: {a['outcome']:>10} delta {a['delta']}  corner time "
            f"{a['corner_time_delta_s']}  {a['text']}"
        )
        late = isinstance(a["delta"], float) and a["delta"] >= 0.5
        faster = isinstance(a["corner_time_delta_s"], float) and a["corner_time_delta_s"] < 0
        rep.check(not (late and a["outcome"] == "hit") or faster, f"attempt {a['attempt']}: a late hit, not faster")
    rep.say(f"  drill result: {done.get('summary_text')!r}")
    rep.numbers["drill"] = {
        "corner": view["corner_label"],
        "target": view["target"],
        "attempts": [a["delta"] for a in done.get("attempts") or ()],
        "hits": done.get("hits"),
    }
    rep.check(done.get("status") == "completed" and len(done.get("attempts") or ()) == drill_laps, "drill completed")
    _texts_ok(rep, [(a["text"], a["short"]) for a in done.get("attempts") or ()], "drill")


def _assist_mismatch(
    rep: Report,
    info: SessionInfo,
    ann_laps: list[LapTrace],
    writer: DbWriter,
    live: LiveState,
    proc: LapProcessor,
    svc: CoachRef,
    sid: str,
    ben: int,
    number: int,
) -> None:
    current = info.assists.get("braking")
    other = (int(current) + 1) % 4 if isinstance(current, int) else 1
    assists = {**info.assists, "braking": other}
    writer.call(lambda c: c.execute("UPDATE sessions SET assists=? WHERE id='ben'", (dumps(assists),)))
    opts = svc.options()
    ben_opt = next(o for o in opts["options"] if o["kind"] == "driver_best" and o["target_driver_id"] == ben)
    want = "Ben's laps here used a different braking assist"
    rep.say(
        f"  braking assist {current} vs {other}: Ben's best available={ben_opt['available']}, {ben_opt['reason']!r}"
    )
    rep.check(ben_opt["available"] is False and ben_opt["reason"] == want, "assist mismatch: option unavailable")
    proc.process(LapJob(sid, _copy(ann_laps[0], number), _ctx(info)))
    cr = live.coachref or {}
    fell_back = cr.get("reason") == want and cr.get("used_kind") == "own_best"
    rep.check(fell_back, f"assist mismatch fallback: {cr.get('reason')!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("captures", nargs="+", type=Path)
    ap.add_argument("--drill", help="corner for the brake-point drill (e.g. T7); default: the first possible")
    ap.add_argument("--laps", type=int, default=3, help="drill laps (3-10)")
    ap.add_argument("--json", action="store_true", help="also print the key numbers as JSON")
    args = ap.parse_args(argv)
    failed = 0
    for path in args.captures:
        rep = check_capture(path, drill=args.drill, drill_laps=args.laps)
        if rep.skipped:
            print(f"== {path.name}: skipped ({rep.skipped})")
            continue
        print("\n".join(rep.lines))
        if args.json:
            with contextlib.suppress(TypeError):
                print(json.dumps({"capture": rep.capture, **rep.numbers}))
        print(f"  {'OK' if not rep.failures else f'{len(rep.failures)} FAILURE(S)'}")
        failed += bool(rep.failures)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
