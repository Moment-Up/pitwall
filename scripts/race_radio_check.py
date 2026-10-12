"""Run the race radio headless over captures: the call timeline, counts per group and the acceptance checks.

    uv run python scripts/race_radio_check.py <capture.pwcap> [...] [--json] [--marks] [--uid UID]
    uv run python scripts/race_radio_check.py --synthetic

Decodes with the game's adapter (as the packet router picks it) and feeds one ``RaceRadioEngine`` per game session
(a new session UID or a session-ended event starts the next, as ``core.session.SessionManager`` does), then runs
every call through a ``RadioScheduler`` with a ``DrivingState`` from the frames (normal intensity, the radio policy's
speak windows; no track model, so the braking-zone part of the window is not simulated) and reports when each would
have been said. No database, no radio, no network; read-only on the capture.

Privacy: the script NEVER prints a packet name. It prints label kinds and official AI driver names (EA's driver
table) only; the check that no call, view or urgent payload carries a personal name (a car with driver id 255 /
65535, a human, or one whose control is unknown) compares against the in-memory Participants table and prints a count.
Run it with the working directory in a scratch folder on someone's real session, and never commit its output for one.

Acceptance checks (race-radio spec 11.4) per race session:

1. at most ``MAX_CALLS_SHORT`` race calls heard in a race of up to 3 laps, ``MAX_CALLS_LONG`` up to 12 laps, never
   more than ``MAX_CALLS_ANY`` (RACE + ALERT the scheduler hands out; INFO and answers excluded; the calls made before
   the radio policy are reported too);
2. no ``yellow_ahead`` for a zone that turned yellow while the player was inside it or less than 150 m past its start;
3. at least half of the ``yellow_ahead`` calls are followed by the player's own FIA yellow within 20 s (informational
   when there are fewer than 4);
4. ``blue_flag`` only while the player's FIA flag is blue, at most one every 30 s;
5. every ``position_change`` says the LapData position at the call; none within 5 s of a flashback; none on lap 1;
6. every ``penalty`` / ``warning`` maps to a PENA of the player (type, infringement, time);
7. no personal name anywhere (count);
8. every non-urgent call the scheduler hands out on track is in a speak window (brake < 0.05, |steer| < 0.12) at the
   moment it is sent, except the grid brief and lights out (standing on the grid / at the launch). Reported too, not
   failed: ``spoken_overlaps``, the calls whose spoken interval (send + ``LATENCY_S``, then ``estimate_speech_s``) met
   a frame that was braking or cornering. The script has no track model, so the speak window's braking-zone look-ahead
   (the learned model, or before it the AI field's braking zones: ``voice.field_zones``) is not simulated and those
   overlaps are an upper bound of what the live radio does.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import sys
from collections import Counter, deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pitwall.adapters.base import GameAdapter, PacketRejected
from pitwall.analysis.track_skeleton import build_track_skeleton
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.integrations import all_adapters
from pitwall.model.telemetry import (
    CarFrame,
    EventKind,
    FrameQuality,
    GameEvent,
    Participants,
    SessionInfo,
)
from pitwall.raceradio.countdown import Memo
from pitwall.raceradio.engine import RaceRadioEngine
from pitwall.raceradio.model import RaceCall
from pitwall.raceradio.radio import race_message
from pitwall.voice.scheduler import CALM_BRAKE, CALM_STEERING, RadioScheduler, estimate_speech_s
from pitwall.voice.types import DrivingState, Priority, RadioMessage
from pitwall.voice.urgent import urgent_message

MAX_CALLS_SHORT = 10  # races of up to 3 laps
MAX_CALLS_LONG = 20  # up to 12 laps
MAX_CALLS_ANY = 25
YELLOW_CONFIRM_S = 20.0
BLUE_EVERY_S = 30.0
FLBK_S = 5.0
LATENCY_S = 0.6  # dispatch -> audio (voice.scheduler SPEECH_LATENCY_S)
NOT_DRIVING = FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING


@dataclass
class SessionRun:
    index: int
    uid: str | None
    engine: RaceRadioEngine
    t0: float
    scheduler: RadioScheduler = field(default_factory=lambda: RadioScheduler("normal"))
    calls: list[dict[str, Any]] = field(default_factory=list)
    dispatched: list[dict[str, Any]] = field(default_factory=list)
    busy_until: float = -math.inf
    frames: int = 0
    laps: int = 0
    names: set[str] = field(default_factory=set)  # personal packet names (in memory only; never printed)
    zone_onsets: dict[int, list[tuple[float, float | None]]] = field(default_factory=dict)  # zone -> (t, pos past)
    zone_flags: dict[int, str | None] = field(default_factory=dict)
    fia: deque[tuple[float, str | None]] = field(default_factory=lambda: deque(maxlen=200_000))
    penas: list[tuple[float, dict[str, Any]]] = field(default_factory=list)
    flbk: list[float] = field(default_factory=list)
    lgot: list[float] = field(default_factory=list)
    payload_blobs: list[str] = field(default_factory=list)
    speaking: list[dict[str, Any]] = field(default_factory=list)  # dispatched calls whose audio may still be playing


def decode(packets: Iterable[CapturedPacket]) -> Iterator[tuple[CapturedPacket, Any]]:
    """Every decoded item with its packet, the adapter picked per sender port as the router does."""
    adapters = all_adapters()
    by_port: dict[int, GameAdapter] = {}
    for p in packets:
        a = by_port.get(p.src_port)
        if a is None:
            a = next((c for c in adapters if c.can_decode(p.data)), None)
            if a is None:
                continue
            by_port[p.src_port] = a
        try:
            items = a.decode(p.data, p.t_recv_ns)
        except PacketRejected:
            continue
        for item in items:
            yield p, item


def _state(f: CarFrame | None, connected: bool = True) -> DrivingState:
    if f is None:
        return DrivingState(False, None, None, None, None, None, None)
    on_track = connected and not (f.quality & NOT_DRIVING)
    return DrivingState(on_track, f.speed_kph, f.brake, f.steering, f.lap_number, f.lap_distance_m, None)


def _message(call: RaceCall, now: float) -> RadioMessage | None:
    if call.urgent:
        return urgent_message(call.urgent_payload(now), now)
    return race_message(call.to_dict(), now)


def run(packets: Iterable[CapturedPacket], uid_filter: str | None = None) -> list[dict[str, Any]]:
    sessions: list[SessionRun] = []
    cur: SessionRun | None = None
    t_first: float | None = None
    participants: Participants | None = None
    first: list[float] = []
    memo: Memo = {}  # as the race radio worker: a formation-lap session's brief is not said again by the race after it

    def tap(ps: Iterable[CapturedPacket]) -> Iterator[CapturedPacket]:
        for p in ps:
            if not first:
                first.append(p.t_recv_ns / 1e9)
            yield p

    for p, item in decode(tap(packets)):
        t = p.t_recv_ns / 1e9
        t_first = first[0]
        rel = round(t - t_first, 2)
        if (
            isinstance(item, SessionInfo)
            and item.session_uid
            and cur is not None
            and cur.uid
            and item.session_uid != cur.uid
        ):
            cur = None
        if isinstance(item, GameEvent) and item.kind is EventKind.BUTTON:
            continue
        if isinstance(item, Participants):
            participants = item  # as core.session.SessionManager: handed to every session that starts after it
        if cur is None:
            if isinstance(item, Participants):
                continue
            cur = SessionRun(len(sessions), None, RaceRadioEngine(f"session-{len(sessions)}", memo=memo), t_first)
            sessions.append(cur)
            if participants is not None:
                _observe(cur, participants, t)
                cur.engine.feed(participants)
        if isinstance(item, SessionInfo) and item.session_uid:
            cur.uid = item.session_uid
        _observe(cur, item, t)
        cur.engine.feed(item)
        for call in cur.engine.take_calls():
            st = cur.engine.st
            d = call.to_dict()
            cur.payload_blobs.append(json.dumps(d))
            if call.urgent:
                cur.payload_blobs.append(json.dumps(call.urgent_payload(t)))
            cur.calls.append(
                {
                    **d,
                    "t": rel,
                    "t_abs": t,
                    "frame_position": st.position,
                    "fia": None if st.frame is None else st.frame.fia_flag,
                    "speed": None if st.frame is None else st.frame.speed_kph,
                }
            )
            msg = _message(call, t)
            if msg is not None:
                cur.scheduler.enqueue(msg)
        if isinstance(item, CarFrame):
            _spoken(cur, item, t)
            _dispatch(cur, item, t, t_first)
        if isinstance(item, GameEvent) and item.kind is EventKind.SESSION_ENDED:
            cur = None
    results = []
    for s in sessions:
        if uid_filter is not None and s.uid != uid_filter:
            continue
        s.payload_blobs.append(json.dumps(s.engine.view()))
        results.append(_result(s))
    return results


def _observe(s: SessionRun, item: Any, t: float) -> None:
    if isinstance(item, CarFrame):
        s.frames += 1
        s.fia.append((t, item.fia_flag))
    elif isinstance(item, Participants):
        for c in item.cars:
            if c.name and (c.ai_controlled is not True or c.driver_id is None):
                s.names.add(c.name)  # in memory only: the check prints a count
    elif isinstance(item, GameEvent):
        if item.code == "PENA" and item.payload.get("vehicleIdx") == item.payload.get("player_idx"):
            s.penas.append((t, dict(item.payload)))
        elif item.code == "FLBK":
            s.flbk.append(t)
        elif item.code == "LGOT":
            s.lgot.append(t)
    elif isinstance(item, SessionInfo) and item.track_zones is not None:
        sk = build_track_skeleton(item)
        f = s.engine.st.frame
        pos = None if f is None else sk.position_m(f.lap_distance_m)
        for z in sk.marshal_zones or ():
            before = s.zone_flags.get(z.game_number)
            s.zone_flags[z.game_number] = z.flag
            if z.flag == "yellow" and before != "yellow" and sk.track_length_m:
                inside = pos is not None and z.contains(pos)
                past = None if pos is None else (pos - z.start_m) % sk.track_length_m
                s.zone_onsets.setdefault(z.game_number, []).append((t, -1.0 if inside else past))


def _calm(f: CarFrame) -> bool:
    return (f.brake or 0.0) < CALM_BRAKE and abs(f.steering or 0.0) < CALM_STEERING


def _spoken(s: SessionRun, f: CarFrame, t: float) -> None:
    """Mark the dispatched calls whose (estimated) audio is playing in a frame that brakes or corners on track."""
    if not s.speaking:
        return
    on_track = not (f.quality & NOT_DRIVING)
    keep = []
    for d in s.speaking:
        if t > d["_end"]:
            continue
        keep.append(d)
        if t >= d["_start"] and on_track and not _calm(f):
            d["_ref"]["spoken_overlap"] = True
    s.speaking = keep


def _dispatch(s: SessionRun, f: CarFrame, t: float, t_first: float) -> None:
    state = _state(f)
    speaking = t < s.busy_until
    msg = s.scheduler.next_message(state, t, speaking)
    if msg is None:
        return
    s.busy_until = t + LATENCY_S + estimate_speech_s(msg.speech)
    d = {
        "t": round(t - t_first, 2),
        "id": msg.id,
        "call": msg.meta.get("call"),
        "text": msg.text,
        "urgent": msg.priority >= Priority.URGENT,
        "needs_window": msg.needs_speak_window,
        "on_track": state.on_track,
        "brake": f.brake,
        "steering": f.steering,
        "speed": f.speed_kph,
        "lap": f.lap_number,
        "kind": msg.kind.value,
        "spoken_overlap": False,
    }
    s.dispatched.append(d)
    if msg.needs_speak_window and msg.priority < Priority.URGENT:
        s.speaking.append({"_start": t + LATENCY_S, "_end": s.busy_until, "_ref": d})


def _result(s: SessionRun) -> dict[str, Any]:
    eng = s.engine
    st = eng.st
    info = st.info
    calls = s.calls
    proactive = [c for c in calls if c["kind"] in ("race", "alert")]
    total = st.total_laps
    checks: dict[str, Any] = {}
    if st.mode == "race" or any(c["call"] == "lap1_summary" for c in calls):
        heard = [d for d in s.dispatched if d["kind"] in ("race", "alert")]
        limit = MAX_CALLS_SHORT if (total or 99) <= 3 else MAX_CALLS_LONG if (total or 99) <= 12 else MAX_CALLS_ANY
        checks["1_count"] = {"heard": len(heard), "made": len(proactive), "limit": limit, "ok": len(heard) <= limit}
    bad_yellow = []
    confirmed = 0
    yellows = [c for c in calls if c["call"] == "yellow_ahead"]
    for c in yellows:
        onsets = [o for o in s.zone_onsets.get(c["data"]["zone"], []) if o[0] <= c["t_abs"]]
        if onsets and (onsets[-1][1] is not None and (onsets[-1][1] < 0 or onsets[-1][1] < 150.0)):
            bad_yellow.append(c["t"])
        if any(c["t_abs"] <= ft <= c["t_abs"] + YELLOW_CONFIRM_S and fl == "yellow" for ft, fl in s.fia):
            confirmed += 1
    checks["2_own_yellow"] = {"violations": bad_yellow, "ok": not bad_yellow}
    checks["3_yellow_confirmed"] = {
        "confirmed": confirmed,
        "calls": len(yellows),
        "ok": len(yellows) < 4 or confirmed * 2 >= len(yellows),
    }
    blues = [c for c in calls if c["call"] == "blue_flag"]
    blue_bad = [c["t"] for c in blues if c["fia"] != "blue"]
    blue_fast = [b["t"] for a, b in itertools.pairwise(blues) if b["t_abs"] - a["t_abs"] < BLUE_EVERY_S]
    checks["4_blue"] = {
        "calls": len(blues),
        "not_blue": blue_bad,
        "too_soon": blue_fast,
        "ok": not (blue_bad or blue_fast),
    }
    pos_bad = []
    for c in calls:
        if c["call"] != "position_change":
            continue
        said = c["data"].get("position")
        if said != c["frame_position"] or (c["lap"] or 0) <= 1 or any(0 <= c["t_abs"] - tf < FLBK_S for tf in s.flbk):
            pos_bad.append(c["t"])
        m = re.search(r"P(\d+)", c["text"])
        if m is None or int(m.group(1)) != said:
            pos_bad.append(c["t"])
    checks["5_position"] = {"violations": pos_bad, "ok": not pos_bad}
    pen_bad = []
    for c in calls:
        if c["call"] not in ("penalty", "warning"):
            continue
        d = c["data"]
        match = [
            p
            for tp, p in s.penas
            if 0 <= c["t_abs"] - tp <= 1.0
            and p.get("penaltyType") == d.get("penalty_type")
            and p.get("infringementType") == d.get("infringement")
        ]
        if not match:
            pen_bad.append(c["t"])
        elif c["call"] == "penalty" and d.get("penalty_type") == 4:
            tm = match[-1].get("time")
            if tm not in (None, 255) and str(tm) not in c["text"]:
                pen_bad.append(c["t"])
    checks["6_penalties"] = {"violations": pen_bad, "ok": not pen_bad}
    leaked = sum(1 for blob in s.payload_blobs for name in s.names if len(name) >= 3 and name in blob)
    checks["7_names"] = {"personal_names_known": len(s.names), "leaks": leaked, "ok": leaked == 0}
    window_bad = []
    for d in s.dispatched:
        if d["urgent"] or not d["on_track"]:
            continue
        calm = (d["brake"] or 0.0) < CALM_BRAKE and abs(d["steering"] or 0.0) < CALM_STEERING
        launch = d["call"] in ("grid_brief", "lights_out") and (
            (d["speed"] or 0.0) < 5.0 or any(0 <= d["t"] + s.t0 - tl <= 3.0 for tl in s.lgot)
        )
        if not calm and not launch:
            window_bad.append(d["t"])
    overlaps = [d["t"] for d in s.dispatched if d.get("spoken_overlap")]
    checks["8_speak_window"] = {
        "violations": window_bad,
        "dispatched": len(s.dispatched),
        "spoken_overlaps": overlaps,  # informational: no braking-zone look-ahead here (module docstring)
        "ok": not window_bad,
    }
    by_group = Counter(c["group"] for c in calls)
    return {
        "session": s.index,
        "uid": s.uid,
        "game": None if st.game is None else st.game.value,
        "mode": st.mode,
        "reason": st.reason,
        "session_type": None if info is None else (info.session_type_raw or info.session_type.value),
        "track": None if info is None else info.track_name,
        "total_laps": total,
        "frames": s.frames,
        "calls": [
            {
                k: c[k]
                for k in (
                    "t",
                    "lap",
                    "group",
                    "call",
                    "kind",
                    "priority",
                    "text",
                    "tier",
                    "ttl_s",
                    "needs_window",
                    "data",
                )
            }
            for c in calls
        ],
        "counts": dict(by_group),
        "dispatched": s.dispatched,
        "checks": checks,
        "ok": all(v["ok"] for v in checks.values()),
        "view": eng.view(),
    }


def marks(packets: Iterable[CapturedPacket]) -> list[tuple[float, str, str]]:
    """Capture-relative receive times of the radio-relevant events (for excerpt windows). No names."""
    out: list[tuple[float, str, str]] = []
    first: list[float] = []  # the capture's first packet, decodable or not (excerpt_capture.py counts from it)

    def tap(ps: Iterable[CapturedPacket]) -> Iterator[CapturedPacket]:
        for p in ps:
            if not first:
                first.append(p.t_recv_ns / 1e9)
            yield p

    last_fia: str | None = None
    last_pos: int | None = None
    last_dmg: Any = None
    for p, item in decode(tap(packets)):
        rel = round(p.t_recv_ns / 1e9 - first[0], 2)
        if isinstance(item, GameEvent):
            pl = item.payload.get("player_idx")
            code = item.code or ""
            if code in ("SSTA", "STLG", "LGOT", "CHQF", "SEND", "SCAR", "RDFL", "FLBK"):
                out.append((rel, code, ""))
            elif code == "PENA" and item.payload.get("vehicleIdx") == pl:
                d = item.payload
                out.append((rel, "PENA", f"{d.get('penaltyType')}/{d.get('infringementType')} time={d.get('time')}"))
            elif code == "OVTK" and pl in (item.payload.get("overtakingVehicleIdx"), item.payload.get(
                    "beingOvertakenVehicleIdx")):  # fmt: skip
                out.append((rel, "OVTK+" if item.payload.get("overtakingVehicleIdx") == pl else "OVTK-", ""))
            elif code == "COLL" and pl in (item.payload.get("vehicle1Idx"), item.payload.get("vehicle2Idx")):
                out.append((rel, "COLL", ""))
            elif code in ("FTLP", "RTMT", "DTSV", "SGSV"):
                out.append((rel, code, f"me={item.payload.get('vehicleIdx') == pl}"))
        elif isinstance(item, CarFrame):
            if item.fia_flag != last_fia:
                out.append((rel, "FIA", str(item.fia_flag)))
                last_fia = item.fia_flag
            if item.race_position != last_pos and item.race_position:
                out.append((rel, "POS", f"{last_pos}->{item.race_position} lap {item.lap_number}"))
                last_pos = item.race_position
            if item.damage is not None and item.damage != last_dmg:
                d = item.damage
                out.append((rel, "DMG", f"wings {d.front_left_wing_pct}/{d.front_right_wing_pct}/{d.rear_wing_pct} "
                                        f"floor {d.floor_pct} tyres {d.tyres_pct.as_tuple()}"))  # fmt: skip
                last_dmg = item.damage
    return out


def print_report(res: dict[str, Any]) -> None:
    head = (
        f"=== session {res['session']} ({res['game']}, {res['session_type']}, {res['track']}, {res['total_laps']} laps)"
    )
    print(head + f": mode {res['mode']}" + (f" ({res['reason']})" if res["reason"] else ""))
    for c in res["calls"]:
        print(f"  {c['t']:>8.2f}  L{c['lap']!s:>3}  {c['kind']:<5} {c['priority']:<6} {c['call']:<20} {c['text']}")
    print(f"  counts: {res['counts']}  dispatched: {len(res['dispatched'])}")
    for name, chk in res["checks"].items():
        print(f"  check {name}: {'ok' if chk['ok'] else 'FAIL'} { ({k: v for k, v in chk.items() if k != 'ok'}) }")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("captures", nargs="*", type=Path)
    ap.add_argument("--uid", help="only this game session UID")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a timeline")
    ap.add_argument("--marks", action="store_true", help="print the radio-relevant event marks (excerpt windows)")
    ap.add_argument("--synthetic", action="store_true", help="run the synthetic race radio stream instead")
    args = ap.parse_args(argv)
    sources: list[tuple[str, Iterable[CapturedPacket]]] = []
    if args.synthetic:
        from pitwall.sim.raceradio_stream import race_radio_demo

        sources.append(("synthetic race-radio-demo", race_radio_demo()[0]))
    sources += [(str(p.name), CaptureReader(p)) for p in args.captures]
    if not sources:
        ap.print_usage(sys.stderr)
        return 2
    failed = False
    for name, packets in sources:
        if args.marks:
            print(f"== {name}")
            for m in marks(packets):
                print(f"  {m[0]:>9.2f} {m[1]:<6} {m[2]}")
            continue
        results = run(packets, args.uid)
        if args.json:
            print(json.dumps({"capture": name, "sessions": results}, indent=1))
        else:
            print(f"## {name}")
            for res in results:
                print_report(res)
        failed = failed or not all(r["ok"] for r in results)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
