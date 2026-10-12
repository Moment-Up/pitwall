"""Car health acceptance checks on real captures (spec section 7): read-only, prints a pass/fail table.

    uv run python scripts/carhealth_check.py <capture.pwcap> [<capture> ...] [--json out.json] [--uid SUFFIX]

For each game session (session UID) in each capture: decodes with the game's adapter, builds the session's track
model from the player's clean laps (pass 1, like the lap processor after a few laps), then feeds a ``CarHealthEngine``
and, for F1 races, a ``StrategyEngine`` exactly as the session manager routes them (pass 2). Reports:

* cold tyres: the player's pit exits and safety-car ends, every ``tyres_cold`` / ``tyres_warm`` (seconds after the
  exit, lap), the baseline and the state at the end of each lap;
* temperatures: the engine range, the brake / engine words after two laps, every proactive call by topic;
* slip: lock-ups / wheelspin per lap with ABS and traction control, the slip calls;
* fuel (GT7 / Forza): the fuel block (status, numbers);
* rejoin (F1 races): every car's pit entry predicted the way ``strategy.rejoin`` does, with the pit loss measured on
  the session's other stops (leave-one-out), against the car's position 10 s after its exit; the player's own
  prediction from the engine (frozen through the lane); ``neighbour_stop`` statuses;
* racecraft (F1 races): the attack / defend verdicts at every line, the segment sums against the lap times;
* privacy: the views' keys (no names) and sizes.

Nothing is written (no database, no radio, no network). Real captures carry other players' names: run it in a scratch
folder, never commit its output for them. Never point it at the live data folder's files while they are written.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import orjson

from pitwall.adapters.base import PacketRejected
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.adapters.forza.adapter import ForzaAdapter
from pitwall.adapters.gt7.adapter import GT7Adapter
from pitwall.analysis.distance import to_distance_domain
from pitwall.analysis.laps import LapAssembler, LapTrace
from pitwall.analysis.track import build_track_model
from pitwall.analysis.track_identity import identify, track_model_payload
from pitwall.carhealth.engine import CarHealthEngine
from pitwall.carhealth.facts import add_car_health_facts
from pitwall.carhealth.slip import SlipCounter
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import (
    CarFrame,
    EventKind,
    FieldSample,
    GameEvent,
    LapCompletion,
    RaceTiming,
    SessionInfo,
    SessionType,
    TyreSetsInfo,
)
from pitwall.strategy import rejoin as rj
from pitwall.strategy.engine import StrategyEngine

SETTLE_S = 10.0


def _adapter(path: Path) -> Any:
    name = path.name
    if "udp33740" in name:
        return GT7Adapter()
    if "forza" in name:
        return ForzaAdapter()
    return F1Adapter(field_hz=10.0)


def _items(path: Path, adapter: Any) -> Any:
    for p in CaptureReader(path):
        try:
            items = adapter.decode(p.data, p.t_recv_ns)
        except PacketRejected:
            continue
        except Exception:
            continue
        yield from items


# ----------------------------------------------------------------------------------------------- pass 1: models
def learn_models(path: Path, uid_filter: str | None) -> dict[str, dict[str, Any]]:
    """Per session UID: the track model payload built from up to 5 of the player's clean laps."""
    laps: dict[str, list[LapTrace]] = defaultdict(list)
    info: dict[str, SessionInfo] = {}
    asm: dict[str, LapAssembler] = {}
    uid: str | None = None
    adapter = F1Adapter(field_hz=0.0, timing_hz=0.0) if "udp20777" in path.name else _adapter(path)
    for it in _items(path, adapter):
        if isinstance(it, SessionInfo):
            uid = it.session_uid
            if uid is None or (uid_filter and not uid.endswith(uid_filter)):
                uid = None
                continue
            info[uid] = it
            if uid not in asm:
                asm[uid] = LapAssembler(lambda lap, u=uid: laps[u].append(lap))
            asm[uid].set_track_length(it.track_length_m)
        elif uid is not None and isinstance(it, CarFrame):
            asm[uid].feed(it)
        elif uid is not None and isinstance(it, LapCompletion):
            asm[uid].feed_completion(it)
    out: dict[str, dict[str, Any]] = {}
    for u, ls in laps.items():
        inf = info[u]
        clean = [lap for lap in ls if lap.clean][:5]
        if not clean or not inf.track_length_m or not inf.track_id:
            continue
        dts = [to_distance_domain(t, inf.track_length_m) for t in clean]
        model = build_track_model(inf.game.value, inf.track_id, inf.track_name, inf.track_length_m, dts)
        model, _ = identify(model, zones=inf.track_zones, packet_format=inf.extra.get("packet_format"))
        out[u] = track_model_payload(model)
    return out


# ----------------------------------------------------------------------------------------------- pass 2
class Session:
    def __init__(self, uid: str, model: dict[str, Any] | None) -> None:
        self.uid = uid
        self.model = model
        self.engine = CarHealthEngine(f"uid:{uid}", track_model=lambda: model, clock=lambda: 0.0)
        self.strategy = StrategyEngine(f"uid:{uid}")
        self.info: SessionInfo | None = None
        self.calls: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.pit_exits: list[tuple[float, int | None]] = []
        self.sc_ends: list[tuple[float, int | None]] = []
        self.engine_temps: list[float] = []
        self.slip_laps: list[dict[str, Any]] = []
        self.lap_states: list[dict[str, Any]] = []
        self.racecraft: list[dict[str, Any]] = []
        self.seg_checks: list[tuple[int, float, float]] = []
        self.lap_ms: dict[int, int] = {}
        self.brake_words: list[tuple[int, str | None]] = []
        self.engine_words: list[tuple[int, str | None]] = []
        self.view_sizes: list[tuple[int, int]] = []
        self.fuel_views: list[dict[str, Any]] = []
        self.fuel_levels: list[float] = []  # the game's tank level (min, max) seen: does it ever fall?
        self.player_rejoin_at_entry: list[dict[str, Any]] = []
        self.neighbour: list[str] = []
        # rejoin evaluation (every car's pit entry)
        self.prev: tuple[float, RaceTiming, dict[int, Any], dict[int, float]] | None = None
        self.entries: list[dict[str, Any]] = []
        self.exits: dict[int, list[tuple[float, int]]] = defaultdict(list)
        self.positions: list[tuple[float, dict[int, int]]] = []
        self._prev_pit: int | None = None
        self._prev_sc: str | None = None
        self._lap: int | None = None
        self._t = 0.0
        self._player_in_lane = False
        self._tyre_key: tuple[str, bool] | None = None
        # the survey's per-lap slip counts (no flashback drop, the last partial lap included): checks detection only
        self.raw_slip = SlipCounter()
        self.raw_laps: dict[int, tuple[int, int]] = {}
        self._raw_lap: int | None = None

    def feed(self, it: Any) -> None:
        e = self.engine
        if isinstance(it, SessionInfo):
            if self.info is not None and self._prev_sc in ("full", "virtual") and it.safety_car_status == "none":
                self.sc_ends.append((self._t, self._lap))
            self._prev_sc = it.safety_car_status
            self.info = it
            level = it.extra.get("fuel_fraction")
            if isinstance(level, int | float) and not isinstance(level, bool):
                lv = float(level)
                self.fuel_levels = [min([lv, *self.fuel_levels[:1]]), max([lv, *self.fuel_levels[1:]])]
        if isinstance(it, FieldSample):
            if e.wants_field:
                e.feed(it)
            return
        if isinstance(it, GameEvent) and it.kind == EventKind.BUTTON:
            return
        if isinstance(it, TyreSetsInfo):
            self.strategy.feed(it)
            return
        if isinstance(it, RaceTiming):
            self._timing(it)
        if not isinstance(it, RaceTiming | CarFrame | LapCompletion | SessionInfo | GameEvent):
            return
        lines = e.lines
        e.feed(it)
        if not isinstance(it, TyreSetsInfo):
            self.strategy.feed(it)
        for c in e.take_calls():
            d = c.to_dict()
            d["t"] = self._t
            self.calls.append(d)
        if isinstance(it, CarFrame):
            self._frame(it)
        if isinstance(it, LapCompletion) and it.lap_time_ms:
            self.lap_ms[it.lap_number] = it.lap_time_ms
        if e.lines != lines:
            self._line()

    def _frame(self, f: CarFrame) -> None:
        if f.session_time_s is not None:
            self._t = f.session_time_s
        if f.engine_temp_c is not None and f.speed_kph and f.speed_kph > 60:
            self.engine_temps.append(f.engine_temp_c)
        pit = f.pit_status
        if pit is not None and self._prev_pit and not pit:
            self.pit_exits.append((self._t, f.lap_number))
        if pit is not None:
            self._prev_pit = pit
        self._lap = f.lap_number
        self.raw_slip.on_frame(f)
        if f.lap_number is not None and f.lap_number != self._raw_lap:
            if self._raw_lap is not None:
                last = self.raw_slip.on_line(self._raw_lap, f.lap_number)
                if last is not None:
                    self.raw_laps[self._raw_lap] = (last["lockups"], last["wheelspin"])
            self._raw_lap = f.lap_number
        t = self.engine.tyres
        key = (t.state, t.armed)
        if key != self._tyre_key:
            self._tyre_key = key
            self.events.append(
                {
                    "t": round(self._t, 1),
                    "lap": f.lap_number,
                    "state": t.state,
                    "armed": t.armed,
                    "index": None if t.index_c is None else round(t.index_c, 1),
                    "base": t.baseline_index(),
                }
            )

    def _line(self) -> None:
        e = self.engine
        lap = e.slip.last_lap
        if lap is not None:
            self.slip_laps.append({**lap, "abs": e.slip.abs_on, "tc": e.slip.tc})
        view = e.view()
        tyres = view["tyres"]
        self.lap_states.append(
            {
                "lap": self._lap,
                "state": tyres.get("state"),
                "index": tyres.get("index_c"),
                "base": tyres.get("baseline_c"),
                "src": tyres.get("baseline_source"),
                "model": tyres.get("model"),
            }
        )
        self.brake_words.append((self._lap or 0, (view["brakes"] or {}).get("word")))
        self.engine_words.append((self._lap or 0, (view["engine"] or {}).get("word")))
        if view.get("fuel") is not None:
            self.fuel_views.append({"lap": self._lap, **view["fuel"]})
        rc = e.racecraft_view()
        self.view_sizes.append((len(orjson.dumps(view)), len(orjson.dumps(rc))))
        if rc["mode"] == "race":
            self.racecraft.append(
                {"lap": self._lap, "ahead": rc["ahead"], "behind": rc["behind"], "reason": rc["reason"]}
            )
        clock, seg = e.racecraft.player, e.racecraft.seg
        if clock is not None and clock.laps and seg is not None:
            last = clock.laps[-1]
            segs = clock.segments(last, seg)
            ms = self.lap_ms.get(last.lap)
            if ms and segs is not None:
                self.seg_checks.append((last.lap, sum(segs), ms / 1000.0))

    def _timing(self, rt: RaceTiming) -> None:
        prev = self.prev
        if prev is not None:
            _, prt, presolved, plane = prev
            before = {c.car_index: c for c in prt.cars}
            for c in rt.cars:
                b = before.get(c.car_index)
                if b is not None and not b.pit_status and c.pit_status and c.result_status == "active":
                    self.entries.append(
                        {
                            "car": c.car_index,
                            "player": c.is_player,
                            "lap": b.lap_number,
                            "t": rt.session_time_s,
                            "pos_before": b.position,
                            "prev_rt": prt,
                            "resolved": presolved,
                            "in_lane": plane,
                        }
                    )
                if b is not None and b.pit_status and not c.pit_status:
                    self.exits[c.car_index].append((rt.session_time_s, c.position))
        self.positions.append((rt.session_time_s, {c.car_index: c.position for c in rt.cars}))
        me = next((c for c in rt.cars if c.is_player), None)
        in_lane = me is not None and rj.player_in_lane(me)
        if in_lane and not self._player_in_lane:
            v = self.strategy.view()
            self.player_rejoin_at_entry.append({"t": rt.session_time_s, "rejoin": (v.get("pit") or {}).get("rejoin")})
        self._player_in_lane = in_lane

    def after_timing(self, rt: RaceTiming) -> None:
        self.prev = (rt.session_time_s, rt, dict(self.strategy.pits.resolved), self.strategy.pits.in_lane_entries())
        ns = ((self.strategy.view().get("pit") or {}).get("neighbour_stop")) if self.strategy.mode == "race" else None
        if ns:
            self.neighbour.append(str(ns.get("status")))


def _pos_at(s: Session, car: int, t: float) -> int | None:
    for tt, pos in s.positions:
        if tt >= t:
            return pos.get(car)
    return None


def evaluate_rejoin(s: Session) -> dict[str, Any]:
    pits = s.strategy.pits
    losses = {
        (v.car_index, v.entry_lap): v.pit_loss_ms
        for v in pits.visits
        if v.final and not v.excluded and not v.neutralised and v.pit_loss_ms
    }
    lap_times = [ms / 1000 for lap, ms in s.lap_ms.items() if lap > 1]
    lap_s = statistics.median(lap_times) if lap_times else None
    rows = []
    for e in s.entries:
        key = (e["car"], e["lap"])
        others = [x for k, x in losses.items() if k != key]
        exits = [x for x in s.exits.get(e["car"], []) if x[0] >= e["t"]]
        if not others or not exits:
            continue
        loss = rj.Loss.of(
            statistics.median(others) / 1000, min(others) / 1000, max(others) / 1000, len(others), "measured"
        )
        prt: RaceTiming = e["prev_rt"]
        me = next(c for c in prt.cars if c.car_index == e["car"])
        r = rj.predict(
            me, prt.cars, resolved=e["resolved"], loss=loss, game_position=None, in_lane=e["in_lane"], lap_s=lap_s
        )
        if r is None or r.get("position") is None:
            rows.append({"car": e["car"], "player": e["player"], "lap": e["lap"], "pred": None})
            continue
        t_exit, pos_exit = exits[0]
        actual = _pos_at(s, e["car"], t_exit + SETTLE_S) or pos_exit
        rows.append(
            {
                "car": e["car"],
                "player": e["player"],
                "lap": e["lap"],
                "pred": r["position"],
                "low": r["position_low"],
                "high": r["position_high"],
                "actual": actual,
                "err": r["position"] - actual,
                "unknown_cars": r["unknown_cars"],
            }
        )
    errs = [abs(r["err"]) for r in rows if r.get("pred") is not None]
    cover = [r["low"] - 1 <= r["actual"] <= r["high"] + 1 for r in rows if r.get("pred") is not None]
    player = []
    for pe in s.player_rejoin_at_entry:
        rjv = pe["rejoin"] or {}
        exits = [
            x for x in s.exits.get(s.strategy.timing.player_index if s.strategy.timing else -1, []) if x[0] >= pe["t"]
        ]
        if exits:
            actual = _pos_at(s, s.strategy.timing.player_index, exits[0][0] + SETTLE_S) if s.strategy.timing else None
            player.append(
                {
                    "pred": rjv.get("position"),
                    "frozen": rjv.get("frozen"),
                    "game": rjv.get("game_position"),
                    "actual": actual,
                }
            )
    return {
        "n": len(errs),
        "unpredicted": sum(1 for r in rows if r.get("pred") is None),
        "within1": round(sum(1 for x in errs if x <= 1) / len(errs), 3) if errs else None,
        "within2": round(sum(1 for x in errs if x <= 2) / len(errs), 3) if errs else None,
        "max": max(errs) if errs else None,
        "range_pm1": round(sum(cover) / len(cover), 3) if cover else None,
        "player": player,
        "rows": rows,
        "neighbour": dict(sorted({k: s.neighbour.count(k) for k in set(s.neighbour)}.items())),
    }


def run_capture(path: Path, uid_filter: str | None = None) -> dict[str, Any]:
    f1 = "udp20777" in path.name
    models = learn_models(path, uid_filter) if f1 else {}
    adapter = _adapter(path)
    sessions: dict[str, Session] = {}
    cur: Session | None = None
    for it in _items(path, adapter):
        if isinstance(it, SessionInfo):
            uid = it.session_uid or "none"  # GT7 / Forza may send no session id: one session per capture then
            if uid_filter and not uid.endswith(uid_filter):
                cur = None
                continue
            if uid not in sessions:
                sessions[uid] = Session(uid, models.get(uid))
            cur = sessions[uid]
        if cur is None:
            continue
        cur.feed(it)
        if isinstance(it, RaceTiming):
            cur.after_timing(it)
    out: dict[str, Any] = {"capture": path.name, "sessions": {}}
    for uid, s in sessions.items():
        info = s.info
        e = s.engine
        e_view = e.view()
        sheet_facts: list[str] = []
        try:
            from pitwall.ai.facts import FactSheet

            fs = FactSheet()
            add_car_health_facts(
                fs, {"session_id": e.session_id, "car_health": e_view, "racecraft": e.racecraft_view()}
            )
            sheet_facts = [f"{f.text} || {f.plain}" for f in fs.facts]
        except Exception as ex:  # report, never crash the check
            sheet_facts = [f"facts failed: {ex!r}"]
        race = info is not None and info.session_type is SessionType.RACE
        rec: dict[str, Any] = {
            "track": None if info is None else info.track_name,
            "type": None if info is None else info.session_type_raw,
            "formula": None if info is None else info.formula,
            "tyre_model": None if info is None else info.extra.get("tyre_temperature_model"),
            "model_corners": None if s.model is None else [(c["name"], round(c["apex_m"])) for c in s.model["corners"]],
            "pit_exits": s.pit_exits,
            "tyre_events": s.events,
            "sc_ends": s.sc_ends,
            "calls": [
                {**{k: c[k] for k in ("topic", "level", "lap", "t", "text")}, "in_pit": bool(c["data"].get("in_pit"))}
                for c in s.calls
            ],
            "lap_states": s.lap_states,
            "engine_range": None if not s.engine_temps else (min(s.engine_temps), max(s.engine_temps)),
            "brake_words": s.brake_words,
            "engine_words": s.engine_words,
            "slip_laps": [
                {
                    k: lap[k]
                    for k in ("lap", "lockups", "wheelspin", "wheelspin_spoken", "abs", "tc", "pit", "flashback")
                }
                for lap in s.slip_laps
            ],
            "fuel": s.fuel_views[-3:],
            "fuel_levels": s.fuel_levels,
            "raw_slip_laps": {
                **{str(k): v for k, v in s.raw_laps.items()},
                **(
                    {}
                    if s._raw_lap is None
                    else {f"{s._raw_lap}*": (s.raw_slip.current()["lockups"], s.raw_slip.current()["wheelspin"])}
                ),
            },
            "view_sizes_max": None
            if not s.view_sizes
            else (max(a for a, _ in s.view_sizes), max(b for _, b in s.view_sizes)),
            "racecraft": s.racecraft,
            "seg_checks": s.seg_checks,
            "facts": sheet_facts,
            "final_view": e_view,
        }
        if race and f1:
            s.strategy.end()
            rec["rejoin"] = evaluate_rejoin(s)
        out["sessions"][uid] = rec
        e.end()
        if e.racecraft.cars:
            rec["privacy_error"] = "per-car buffers survived end()"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("captures", nargs="+", type=Path)
    ap.add_argument("--uid", help="only session UIDs ending with this")
    ap.add_argument("--json", type=Path, help="write the full results here")
    args = ap.parse_args(argv)
    results = [run_capture(p, args.uid) for p in args.captures]
    if args.json:
        args.json.write_bytes(orjson.dumps(results, option=orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS, default=str))
    for r in results:
        for uid, s in r["sessions"].items():
            print(f"== {r['capture']} ...{uid[-6:]} {s['track']} {s['type']} {s['formula']} model={s['tyre_model']}")
            print(f"   pit exits {[(round(t, 1), lap) for t, lap in s['pit_exits']]}  sc ends {s['sc_ends']}")
            for ev in s["tyre_events"]:
                print(f"   tyres {ev}")
            for c in s["calls"]:
                print(f"   call {c['topic']:<15} {c['level']:<8} lap {c['lap']} t {round(c['t'], 1)}: {c['text']}")
            print(f"   engine {s['engine_range']}  brakes {s['brake_words'][-1:] if s['brake_words'] else None}")
            if s.get("rejoin"):
                rr = s["rejoin"]
                print(
                    f"   rejoin n {rr['n']} unpredicted {rr['unpredicted']} <=1 {rr['within1']} <=2 {rr['within2']} "
                    f"max {rr['max']} range+-1 {rr['range_pm1']} player {rr['player']} neighbour {rr['neighbour']}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
