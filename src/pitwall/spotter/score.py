"""Offline scoring of the spotter on a capture (``scripts/spotter_check.py``, recorded tests). Never on a live path.

Ground truth (spec section 2.4) is GEOMETRIC: per packet, a side is occupied when a racing car overlaps the player
lengthwise within one lane (``engine.enters``: the engine's own join rule, no hysteresis, no debounce), counted only
while the spotter's gates are open. It is computed from the same positions and the same car box as the spotter, so a
score validates the data, timing, state machine, chatter, flapping and send-rate sensitivity - NOT that the box
matches the game's collision shapes or what the driver sees on screen.

The engine can be fed every ``decimate``-th Motion packet (``decimate=3`` from a 60 Hz capture = the game's 20 Hz send
rate); the ground truth always uses every packet, and the engine's gate and announced state are carried forward
between the packets it saw.

Measures (per session and summed): overlaps of 1 s or longer called; recall of overlaps of 0.3 s or more (an onset
call or the side announced within the overlap); precision of onset calls (one with no overlap on that side within
0.3 s before to 0.1 s after is false); wrong clears (a clear while that side has an overlap now or within 0.2 s);
flaps (a "car" call within 1 s after a "clear" on the same side); decision delay from the overlap's start on the game
clock and on the receive clock (network bunching included); onset calls heard too late (no overlap and not announced
0.45 s after the call); calls per gated minute.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.model.telemetry import FieldMotion, GameEvent, SessionInfo
from pitwall.spotter.engine import PARAMS, SpotterEngine, SpotterParams, enters
from pitwall.spotter.geometry import decode, relative
from pitwall.spotter.model import CAR_LEFT, CAR_RIGHT, LEFT, RIGHT, THREE_WIDE, SpotterCall
from pitwall.spotter.settings import SpotterSettings

SCORING = SpotterSettings(enabled=True)  # races only, start delay 5 s, every call kind on
_FEED = frozenset({P.PacketId.MOTION, P.PacketId.SESSION, P.PacketId.LAP_DATA, P.PacketId.EVENT})
EAR_S = 0.45  # an onset call is "heard too late" when nothing is alongside this long after it
MEANINGFUL_S = 0.3
LONG_S = 1.0
HIT_WINDOW_S = 0.5


@dataclass
class SessionTrace:
    """One game session (sessionUID) of a capture, per Motion packet."""

    uid: int
    engine: SpotterEngine
    formula: str | None = None
    track_id: str | None = None
    network_game: bool | None = None
    packet_format: int | None = None
    st: list[float] = field(default_factory=list)
    t_rx: list[float] = field(default_factory=list)
    gt: list[tuple[bool, bool]] = field(default_factory=list)
    gate: list[bool] = field(default_factory=list)
    ann: list[tuple[bool, bool]] = field(default_factory=list)
    calls: list[tuple[int, SpotterCall]] = field(default_factory=list)


def _uid(data: bytes) -> int:
    return int.from_bytes(data[7:15], "little") if len(data) >= P.HEADER.size else 0


def _f1_packets(packets: Iterable[CapturedPacket]) -> Iterator[CapturedPacket]:
    """Only what the spotter reads (Motion, Session, LapData, Event): the rest is never decoded."""
    for p in packets:
        d = p.data
        if len(d) >= P.HEADER.size and d[6] in _FEED:
            yield p


def collect(
    packets: Iterable[CapturedPacket],
    *,
    decimate: int = 1,
    settings: SpotterSettings = SCORING,
    params: SpotterParams = PARAMS,
    min_motion: int = 600,
) -> list[SessionTrace]:
    """Run the engine over a packet stream (every ``decimate``-th Motion) and record the per-packet traces."""
    adapter = F1Adapter(field_hz=0.0, timing_hz=0.0, field_motion=True)
    sessions: dict[int, SessionTrace] = {}
    current: SessionTrace | None = None
    k = 0
    for pkt in _f1_packets(packets):
        uid = _uid(pkt.data)
        if uid:
            tr = sessions.get(uid)
            if tr is None:
                tr = sessions[uid] = SessionTrace(uid, SpotterEngine(settings, params))
            current = tr
        if current is None:
            continue
        try:
            items = adapter.decode(pkt.data, pkt.t_recv_ns)
        except Exception:
            continue
        eng = current.engine
        for e in items:
            if isinstance(e, SessionInfo):
                eng.feed_session(e)
                current.formula = e.formula
                current.track_id = e.track_id
                current.network_game = e.network_game
            elif isinstance(e, GameEvent):
                eng.feed_event(e.kind, e.session_time_s)
            elif isinstance(e, FieldMotion):
                _motion(current, e, k % decimate == 0, params)
                k += 1
    return [tr for tr in sessions.values() if len(tr.st) >= min_motion]


def _motion(tr: SessionTrace, fm: FieldMotion, fed: bool, params: SpotterParams) -> None:
    m = decode(fm)
    if m is None:
        return
    tr.packet_format = m.packet_format
    eng = tr.engine
    i = len(tr.st)
    tr.st.append(m.session_time_s)
    tr.t_rx.append(m.t_recv_ns / 1e9)
    if fed:
        calls = eng.feed_motion(m, m.t_recv_ns)
        tr.gate.append(eng.trace.gate_open)
        tr.ann.append(eng.trace.announced)
        tr.calls.extend((i, c) for c in calls)
        if eng.trace.gate_open:
            tr.gt.append(eng.trace.gt)
            return
    else:
        tr.gate.append(tr.gate[-1] if tr.gate else False)
        tr.ann.append(tr.ann[-1] if tr.ann else (False, False))
    if not tr.gate[-1]:
        tr.gt.append((False, False))
        return
    width = eng.dims.width_m
    _b, rels = relative(m, eng.dims.length_m, width, params.vert_max_m)
    gl = gr = False
    for r in rels:
        if r.obstacle and enters(r, width, params):
            if r.lat < 0:
                gl = True
            else:
                gr = True
    tr.gt.append((gl, gr))


def _episodes(arr: np.ndarray, st: np.ndarray) -> list[tuple[int, int, float, float]]:
    """(start index, end index exclusive, start t, end t) of the runs of True."""
    d = np.diff(np.concatenate([[0], arr.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    out = []
    n = len(st)
    for a, b in zip(starts.tolist(), ends.tolist(), strict=True):
        s0, e0 = int(a), int(b)
        t1 = float(st[min(e0, n - 1)]) if e0 < n else float(st[-1])
        out.append((s0, e0, float(st[s0]), t1))
    return out


def score_trace(tr: SessionTrace) -> dict[str, Any]:
    """The measures of one session (see the module docstring)."""
    st = np.asarray(tr.st, dtype=np.float64)
    t_rx = np.asarray(tr.t_rx, dtype=np.float64)
    gate = np.asarray(tr.gate, dtype=bool)
    gt = np.asarray(tr.gt, dtype=bool).reshape(-1, 2) & gate[:, None]
    ann = np.asarray(tr.ann, dtype=bool).reshape(-1, 2)
    n = len(st)
    steps = np.diff(st)
    steps = steps[(steps > 0) & (steps < 1.0)]
    dt = float(np.median(steps)) if steps.size else 1 / 60
    fps = 1.0 / dt
    side_gt = {LEFT: gt[:, LEFT], RIGHT: gt[:, RIGHT]}
    both = ann[:, LEFT] & ann[:, RIGHT]
    side_ann = {LEFT: ann[:, LEFT] | both, RIGHT: ann[:, RIGHT] | both}
    offset = t_rx - st
    episodes = [(x, *ep) for x in (LEFT, RIGHT) for ep in _episodes(side_gt[x], st)]
    meaningful = [e for e in episodes if e[4] - e[3] >= MEANINGFUL_S]
    hit, missed = 0, 0
    delays: list[float] = []
    rx_delays: list[float] = []
    for x, s0, e0, t0, _t1 in meaningful:
        an = side_ann[x]
        hi = int(np.searchsorted(st, t0 + HIT_WINDOW_S))
        seg = an[s0 : max(s0 + 1, min(e0, hi))]
        if an[s0]:
            hit += 1
            delays.append(0.0)
            rx_delays.append(0.0)
        elif seg.any():
            hit += 1
            k = s0 + int(np.argmax(seg))
            delays.append(float(st[k] - t0))
            base = float(offset[max(0, s0 - 120) : s0 + 1].min())
            rx_delays.append(float(t_rx[k] - (t0 + base)))
        elif not an[s0:e0].any():
            missed += 1
    long_eps = [e for e in episodes if e[4] - e[3] >= LONG_S]
    long_hit = sum(1 for x, s0, e0, _t0, _t1 in long_eps if side_ann[x][s0:e0].any())
    onset = [(i, c) for i, c in tr.calls if c.kind in (CAR_LEFT, CAR_RIGHT, THREE_WIDE)]
    w_back, w_fwd, w_clear = round(0.3 * fps), round(0.1 * fps) + 1, round(0.2 * fps) + 1
    k_ear = round(EAR_S * fps)

    def sides(c: SpotterCall) -> list[int]:
        return [LEFT, RIGHT] if c.side is None else [LEFT if c.side == "left" else RIGHT]

    false = sum(1 for i, c in onset if not any(side_gt[x][max(0, i - w_back) : i + w_fwd].any() for x in sides(c)))
    late = 0
    for i, c in onset:
        j = min(i + k_ear, n - 1)
        if not any(side_gt[x][j] or ann[j, x] for x in sides(c)):
            late += 1
    wrong_clear = 0
    clear_lag: list[float] = []
    for i, c in tr.calls:
        if not c.kind.startswith("clear_"):
            continue
        if any(side_gt[x][i : i + w_clear].any() for x in sides(c)):
            wrong_clear += 1
        for x in sides(c):
            past = np.flatnonzero(side_gt[x][: i + 1])
            if past.size:
                clear_lag.append(float(st[i] - st[past[-1]]))
    flaps = 0
    last_clear: dict[str, float] = {}
    for _i, c in tr.calls:
        if c.kind.startswith("clear_") and c.side:
            last_clear[c.side] = c.session_time_s
        if c.kind in (CAR_LEFT, CAR_RIGHT) and c.side in last_clear and c.session_time_s - last_clear[c.side] < 1.0:
            flaps += 1
    gated_min = float(gate.sum()) * dt / 60.0
    kinds = Counter(c.kind for _i, c in tr.calls)
    eng = tr.engine
    return {
        "uid": f"{tr.uid & 0xFFFFFF:06x}",
        "formula": tr.formula,
        "track_id": tr.track_id,
        "online": tr.network_game,
        "format": tr.packet_format,
        "dims": (eng.dims.length_m, eng.dims.width_m),
        "motion_hz": None if eng.motion_hz is None else round(eng.motion_hz, 1),
        "gated_min": round(gated_min, 2),
        "gt_episodes": len(episodes),
        "gt_meaningful": len(meaningful),
        "hit": hit,
        "missed": missed,
        "long_n": len(long_eps),
        "long_hit": long_hit,
        "onset_calls": len(onset),
        "false_onsets": false,
        "late_heard": late,
        "wrong_clears": wrong_clear,
        "clears": sum(v for k, v in kinds.items() if k.startswith("clear_")),
        "flaps": flaps,
        "calls": sum(kinds.values()),
        "kinds": dict(kinds),
        "suppressed_short": eng.suppressed_short,
        "_delays": delays,
        "_rx_delays": rx_delays,
        "_clear_lag": clear_lag,
    }


def _pct(values: list[float], qs: tuple[float, ...], scale: float = 1000.0) -> list[int] | None:
    if not values:
        return None
    return [round(float(np.percentile(values, q)) * scale) for q in qs]


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over sessions (the table of spec section 2.3)."""

    def tot(k: str) -> int:
        return int(sum(r[k] for r in rows))

    delays = [d for r in rows for d in r["_delays"]]
    rx = [d for r in rows for d in r["_rx_delays"] if d > 0]
    lag = [d for r in rows for d in r["_clear_lag"]]
    gated = sum(r["gated_min"] for r in rows)
    kinds: Counter[str] = Counter()
    for r in rows:
        kinds.update(r["kinds"])
    meaningful = tot("gt_meaningful")
    onset = tot("onset_calls")
    return {
        "sessions": len(rows),
        "gated_min": round(gated, 1),
        "gt_episodes": tot("gt_episodes"),
        "gt_meaningful": meaningful,
        "hit": tot("hit"),
        "recall": round(tot("hit") / max(1, meaningful), 3),
        "missed": tot("missed"),
        "long_called": f"{tot('long_hit')}/{tot('long_n')}",
        "onset_calls": onset,
        "false_onsets": tot("false_onsets"),
        "precision": round(1 - tot("false_onsets") / max(1, onset), 3),
        "wrong_clears": tot("wrong_clears"),
        "clears": tot("clears"),
        "flaps": tot("flaps"),
        "late_heard": tot("late_heard"),
        "suppressed_short": tot("suppressed_short"),
        "calls": tot("calls"),
        "calls_per_min": round(tot("calls") / gated, 2) if gated > 0 else None,
        "delay_game_ms_p50_p95_max": _pct(delays, (50, 95, 100)),
        "delay_rx_ms_p50_p95_p99": _pct(rx, (50, 95, 99)),
        "clear_lag_ms_p50_p95": _pct(lag, (50, 95)),
        "kinds": dict(sorted(kinds.items())),
    }


def score_capture(path: Path, *, decimate: int = 1, settings: SpotterSettings = SCORING) -> list[dict[str, Any]]:
    """Score every race session of one capture (sessions without gated racing are left out)."""
    rows = []
    for tr in collect(CaptureReader(path), decimate=decimate, settings=settings):
        row = score_trace(tr)
        if row["gated_min"] > 0:
            row["capture"] = path.name
            rows.append(row)
    return rows


def public(row: dict[str, Any]) -> dict[str, Any]:
    """A row without its raw sample lists (printing, JSON)."""
    return {k: v for k, v in row.items() if not k.startswith("_")}
