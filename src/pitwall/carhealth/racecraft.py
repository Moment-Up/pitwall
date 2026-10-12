"""Attack and defend: where the player is quicker than the car directly ahead, and where the car behind is quicker
(``RacecraftView``, F1 races, on request only - never a proactive call).

**Grid clocks** (``GridClock``: one per car from the field samples, ~10 Hz; one for the player from its frames): the
crossing time of every ``RACECRAFT_GRID_M`` metres of the lap, interpolated between the two samples around it - inside a
lap at ``d_prev < x <= d``, and the line when the lap number goes up with ``d_prev > L - 300`` and ``d < 300``
(interpolated over ``d_prev -> d + L``). They run from the start of the race, before any corner is learned, and keep the
last ``RACECRAFT_KEEP_LAPS`` laps (about 240 numbers a lap on a 6 km track, ~250 kB for a full field; no raw samples).

**Segments** are the learned corners of the live track model (``seg_start_m``..``seg_end_m`` partition the lap,
``analysis.track``); they are named as the cues name them (``coach.cues.cue_labels``), else by their learned names. A
boundary's time is interpolated between the two grid crossings around it, so a new or changed model re-derives every
kept lap at once: the clocks never start again (on real Austria the model was rebuilt three times in laps 63-65, and
the old per-boundary clocks then had no lap of the player to compare until lap 68). Without a model the view says
"corners not learned yet". A car-lap is usable when every boundary was crossed, the car stayed out of the pit lane, no
safety car / VSC ran, the lap was valid, it is not race lap 1, and (the player) no flashback hit it.

**Verdict** (``SEG_MIN_S`` / ``MARGIN_S``): per segment, Δ = median of the player's last <= 3 usable laps - median of
that car's last <= 3 usable laps (at least two each; negative = the player is quicker). Attack: the most negative Δ;
``clear`` when it is at least ``SEG_MIN_S`` and ``MARGIN_S`` clear of the next one, ``spread`` when the player is
quicker there but not clearly there, ``none`` when the player is not quicker by ``SEG_MIN_S`` anywhere. Defend mirrors
it (the car behind quicker). ``lap_delta_s`` (Σ Δ) is the pace over the whole lap, which the words use too: "none"
is not "as quick everywhere". A named corner is kept until it drops out on ``RACECRAFT_HOLD_EVALS`` + 1 evaluations
in a row (a new lap of either car), so Drive's tag does not flicker. ``close``: the gap to that car is under
``CLOSE_GAP_S`` (the game's timing), unknown without a gap. On real F1 25 Austria (three sessions on two days) the
attack corner was the same on every lap with a car ahead (margins 0.16-0.97 s); on Imola no defend corner stood out
(margins 0.00-0.14 s): "spread", never invented.

**Privacy** (human opponents included; the AI flag is ignored for the computation): in memory only and cleared when
the session ends; nothing goes to SQLite or the log per car; the view carries positions, car indexes and corners only
(no names; F1 names are never decoded here).
"""

from __future__ import annotations

import itertools
import math
import statistics
from array import array
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pitwall.carhealth import thresholds as T
from pitwall.model.telemetry import RaceTiming

REASON_NO_MODEL = "corners not learned yet"
REASON_NOT_RACE = "attack and defend work in races only"
REASON_NOT_F1 = "attack and defend need the other cars' positions, which only F1 25 sends"
REASON_ENDED = "the session ended"
REASON_LEADING = "leading: there's no car ahead"
REASON_LAST = "last: there's no car behind"
REASON_MY_LAPS = "needs two clean laps of you"
REASON_THEIR_LAPS = "needs two clean laps of that car"
REASON_NO_TIMING = "waiting for race timing"
RESET_BACK_M = 50.0  # moving back along the lap more than this is a reset to the track: the lap is not timed


@dataclass(slots=True, frozen=True)
class Segments:
    """The learned corners as lap segments: ``starts[k]`` = the start of segment k (``starts[0]`` = 0)."""

    names: tuple[str, ...]
    texts: tuple[str, ...]
    starts: tuple[float, ...]
    length_m: float

    @property
    def key(self) -> tuple[Any, ...]:
        return (self.names, tuple(round(s, 1) for s in self.starts), round(self.length_m, 1))

    @classmethod
    def from_model(cls, model: Mapping[str, Any] | None, labels: Mapping[str, str] | None = None) -> Segments | None:
        """From the live ``track_model`` payload; None without at least two corners that partition the lap."""
        if not isinstance(model, Mapping):
            return None
        corners = [c for c in model.get("corners") or [] if isinstance(c, Mapping)]
        length = model.get("length_m")
        if len(corners) < 2 or not isinstance(length, int | float) or isinstance(length, bool) or length <= 0:
            return None
        try:
            ordered = sorted(corners, key=lambda c: float(c["seg_start_m"]))
            names = tuple(str(c["name"]) for c in ordered)
            starts = tuple(float(c["seg_start_m"]) for c in ordered)
        except (KeyError, TypeError, ValueError):
            return None
        if starts[0] > 1.0 or any(b <= a for a, b in itertools.pairwise(starts)):
            return None
        labels = labels or {}
        texts = tuple(labels.get(n) or n for n in names)
        return cls(names, texts, (0.0, *starts[1:]), float(length))


@dataclass(slots=True)
class LapGrid:
    """One completed lap of one car: ``times[k]`` = when it crossed ``k * grid_m`` (``times[0]`` the line; NaN where it
    was not seen), ``end`` = the next line."""

    lap: int
    times: array[float]
    end: float
    usable: bool


@dataclass(slots=True)
class _Open:
    lap: int
    times: array[float]
    pit: bool = False
    sc: bool = False
    invalid: bool = False
    flashback: bool = False


class GridClock:
    """One car's grid crossing times, interpolated between samples; the last laps, and their segment times for any
    corner model."""

    __slots__ = ("_open", "_prev", "grid_m", "laps", "length_m", "n")

    def __init__(self, length_m: float, grid_m: float = T.RACECRAFT_GRID_M) -> None:
        self.length_m = float(length_m)  # where the game resets the lap distance
        self.grid_m = grid_m
        self.n = max(1, math.ceil(self.length_m / grid_m))  # grid points k * grid_m < length_m
        self.laps: deque[LapGrid] = deque(maxlen=T.RACECRAFT_KEEP_LAPS)
        self._open: _Open | None = None
        self._prev: tuple[int, float, float] | None = None  # (lap, d, t)

    def add(
        self, lap: int, d: float, t: float, *, pit: bool = False, sc: bool = False, invalid: bool = False
    ) -> LapGrid | None:
        """One sample; returns the lap it completed, if any. Usually O(1): the grid points since the last sample."""
        prev, self._prev = self._prev, (lap, d, t)
        op = self._open
        if op is not None and lap == op.lap:
            op.pit |= pit
            op.sc |= sc
            op.invalid |= invalid
        if prev is None:
            return None
        plap, pd, pt = prev
        if t <= pt:
            self._open = None  # the clock went back (flashback / restart): this lap is not timed
            return None
        L = self.length_m
        if lap == plap:
            if d < pd - RESET_BACK_M:
                self._open = None  # moved back along the lap (a reset to track)
                return None
            if op is not None:
                self._cross(op, pd, pt, d, t)
            return None
        if lap == plap + 1 and pd > L - T.LINE_WINDOW_M and d < T.LINE_WINDOW_M:
            span = (d + L) - pd
            t_line = pt + (L - pd) / span * (t - pt) if span > 0 else t
            done: LapGrid | None = None
            if op is not None and op.lap == plap:
                self._cross(op, pd, pt, L, t_line)
                done = self._finish(op, t_line)
            times = array("d", [math.nan]) * self.n
            times[0] = t_line
            nxt = _Open(lap, times, pit=pit, sc=sc, invalid=invalid)
            self._cross(nxt, 0.0, t_line, d, t)
            self._open = nxt
            return done
        self._open = None  # a jump (skipped lap, rewind): wait for the next line
        return None

    def _cross(self, op: _Open, d0: float, t0: float, d1: float, t1: float) -> None:
        g = self.grid_m
        first = max(1, math.floor(d0 / g) + 1)  # grid points strictly after d0 ...
        last = min(self.n - 1, math.floor(d1 / g))  # ... up to d1
        times = op.times
        for k in range(first, last + 1):
            if math.isnan(times[k]):
                x = k * g
                times[k] = t0 + (x - d0) / (d1 - d0) * (t1 - t0) if d1 > d0 else t1

    def _finish(self, op: _Open, end: float) -> LapGrid:
        usable = not (op.pit or op.sc or op.invalid or op.flashback) and op.lap != 1
        rec = LapGrid(op.lap, op.times, end, usable)
        self.laps.append(rec)
        return rec

    def flashback(self) -> None:
        """The player's flashback: the lap in progress is not timed (the clock also goes back)."""
        if self._open is not None:
            self._open.flashback = True

    # ------------------------------------------------------------------ segments
    def time_at(self, rec: LapGrid, x: float) -> float | None:
        """When the car crossed ``x`` m that lap: between the grid crossings around it; None if one is missing."""
        if x <= 0.0:
            return rec.times[0]
        if x >= self.length_m:
            return rec.end
        g = self.grid_m
        k = int(x // g)
        x0, t0 = k * g, rec.times[k]
        x1, t1 = ((k + 1) * g, rec.times[k + 1]) if k + 1 < self.n else (self.length_m, rec.end)
        if math.isnan(t0) or math.isnan(t1) or x1 <= x0:
            return None
        return t0 + (x - x0) / (x1 - x0) * (t1 - t0)

    def segments(self, rec: LapGrid, seg: Segments) -> tuple[float, ...] | None:
        """That lap's time in each segment of ``seg`` (they sum to the lap time), or None when it cannot be timed."""
        ts: list[float] = [rec.times[0]]
        for b in seg.starts[1:]:
            tb = self.time_at(rec, b)
            if tb is None:
                return None
            ts.append(tb)
        ts.append(rec.end)
        out = tuple(b - a for a, b in itertools.pairwise(ts))
        return None if any(s <= 0 for s in out) else out

    def usable(self, seg: Segments, n: int = T.RACECRAFT_LAPS) -> list[tuple[float, ...]]:
        out = [s for rec in self.laps if rec.usable and (s := self.segments(rec, seg)) is not None]
        return out[-n:]


def _median_segs(laps: Sequence[tuple[float, ...]]) -> list[float]:
    return [statistics.median(col) for col in zip(*laps, strict=True)]


def verdict(deltas: Sequence[float], side: str) -> tuple[str, int | None, int | None, float | None]:
    """(verdict, best segment, second segment, margin) for ``side`` "ahead" (attack) or "behind" (defend)."""
    if len(deltas) < 2:
        return "none", None, None, None
    sign = 1.0 if side == "ahead" else -1.0  # attack: the most negative Δ; defend: the most positive
    order = sorted(range(len(deltas)), key=lambda k: sign * deltas[k])
    k1, k2 = order[0], order[1]
    best = sign * deltas[k1]
    margin = abs(deltas[k1] - deltas[k2])
    if best > -T.SEG_MIN_S:
        return "none", k1, k2, round(margin, 3)
    return ("clear" if margin >= T.MARGIN_S else "spread"), k1, k2, round(margin, 3)


@dataclass(slots=True)
class Racecraft:
    """One session's attack / defend state. Not thread-safe (the car health worker owns it)."""

    seg: Segments | None = None
    line_length_m: float | None = None
    player: GridClock | None = None
    cars: dict[int, GridClock] = field(default_factory=dict)
    timing: RaceTiming | None = None
    _cache_key: tuple[Any, ...] | None = None
    _cache: dict[str, Any] | None = None
    _held: dict[str, tuple[int, dict[str, Any], int]] = field(default_factory=dict)  # side -> (car, clear side, misses)

    def set_length(self, line_length_m: float | None) -> None:
        """The game's lap length (where the lap distance resets); a different one starts the clocks again."""
        if not line_length_m or line_length_m <= 0 or line_length_m == self.line_length_m:
            return
        changed = self.line_length_m is not None
        self.line_length_m = float(line_length_m)
        if changed:
            self.player = None
            self.cars = {}
            self._invalidate()

    def set_segments(self, seg: Segments | None, line_length_m: float | None = None) -> None:
        """A (new) learned model: every kept lap is re-derived from the grid clocks (they keep running)."""
        self.set_length(line_length_m)
        old = self.seg
        if seg is old or (seg is not None and old is not None and seg.key == old.key and seg.texts == old.texts):
            return
        geometry = seg is None or old is None or seg.key != old.key
        self.seg = seg
        self._invalidate()
        if geometry:
            self._held = {}  # a held corner of the old model may not exist in the new one

    def _invalidate(self) -> None:
        self._cache_key = self._cache = None

    def _length(self) -> float | None:
        return self.line_length_m or (None if self.seg is None else self.seg.length_m)

    def on_player(
        self, lap: int | None, d: float | None, t: float | None, *, pit: bool, sc: bool, invalid: bool
    ) -> bool:
        """A player frame; True when it completed a lap (the line)."""
        if lap is None or d is None or t is None:
            return False
        if self.player is None:
            length = self._length()
            if length is None:
                return False
            self.player = GridClock(length)
        return self.player.add(lap, d, t, pit=pit, sc=sc, invalid=invalid) is not None

    def on_field(self, idx: int, lap: int, d: float, t: float, *, pit: bool, sc: bool, invalid: bool) -> None:
        clock = self.cars.get(idx)
        if clock is None:
            length = self._length()
            if length is None:
                return
            clock = self.cars[idx] = GridClock(length)
        clock.add(lap, d, t, pit=pit, sc=sc, invalid=invalid)

    def flashback(self) -> None:
        if self.player is not None:
            self.player.flashback()

    def clear(self) -> None:
        """Privacy: the session ended - every per-car buffer goes."""
        self.cars = {}
        self.player = None
        self.timing = None
        self._held = {}
        self._invalidate()

    # ------------------------------------------------------------------ output
    def compute(self) -> dict[str, Any]:
        """``{"reason", "ahead", "behind"}`` (the verdicts cached until a lap or a neighbour changed; ``close`` from the
        latest timing)."""
        seg, rt, me_clock = self.seg, self.timing, self.player
        if seg is None:
            return {"reason": REASON_NO_MODEL, "ahead": None, "behind": None}
        if rt is None:
            return {"reason": REASON_NO_TIMING, "ahead": None, "behind": None}
        me = next((c for c in rt.cars if c.is_player), None)
        if me is None:
            return {"reason": REASON_NO_TIMING, "ahead": None, "behind": None}
        by_pos = {c.position: c for c in rt.cars if c.result_status == "active"}
        ahead, behind = by_pos.get(me.position - 1), by_pos.get(me.position + 1)
        key = (
            seg.key,
            seg.texts,
            _laps_key(me_clock),
            me.position,
            None if ahead is None else (ahead.car_index, _laps_key(self.cars.get(ahead.car_index))),
            None if behind is None else (behind.car_index, _laps_key(self.cars.get(behind.car_index))),
        )
        out = self._cache
        if key != self._cache_key or out is None:
            mine = [] if me_clock is None else me_clock.usable(seg)
            out = {
                "reason": None,
                "ahead": self._side(
                    "ahead", ahead.car_index if ahead else None, ahead.position if ahead else None, mine
                ),
                "behind": self._side(
                    "behind", behind.car_index if behind else None, behind.position if behind else None, mine
                ),
            }
            self._hold(out)
            self._cache_key, self._cache = key, out
        gaps = {"ahead": me.gap_ahead_ms, "behind": None if behind is None else behind.gap_ahead_ms}
        res = dict(out)
        for side in ("ahead", "behind"):
            s = out[side]
            if s is not None and s.get("car_index") is not None:
                g = gaps[side]
                res[side] = {**s, "close": None if g is None else g < T.CLOSE_GAP_S * 1000.0}
        return res

    def _hold(self, out: dict[str, Any]) -> None:
        """A named (clear) corner is kept while it drops out on at most ``RACECRAFT_HOLD_EVALS`` evaluations in a row
        against the same car."""
        for side in ("ahead", "behind"):
            s = out[side]
            held = self._held.get(side)
            if s is None or s.get("car_index") is None:
                self._held.pop(side, None)
            elif s["verdict"] == "clear":
                self._held[side] = (s["car_index"], s, 0)
            elif (
                held is not None
                and held[0] == s["car_index"]
                and s["verdict"] in ("spread", "none")
                and held[2] < T.RACECRAFT_HOLD_EVALS
            ):
                out[side] = held[1]
                self._held[side] = (held[0], held[1], held[2] + 1)
            else:
                self._held.pop(side, None)

    def _side(self, side: str, idx: int | None, pos: int | None, mine: list[tuple[float, ...]]) -> dict[str, Any]:
        seg = self.seg
        assert seg is not None
        base: dict[str, Any] = {
            "car_index": idx,
            "position": pos,
            "laps_compared": None,
            "verdict": "unknown",
            "corner": None,
            "second": None,
            "margin_s": None,
            "lap_delta_s": None,
            "reason": None,
        }
        if idx is None:
            base["reason"] = REASON_LEADING if side == "ahead" else REASON_LAST
            return base
        clock = self.cars.get(idx)
        theirs = [] if clock is None else clock.usable(seg)
        base["laps_compared"] = [len(mine), len(theirs)]
        if len(mine) < T.RACECRAFT_MIN_LAPS:
            base["reason"] = REASON_MY_LAPS
            return base
        if len(theirs) < T.RACECRAFT_MIN_LAPS:
            base["reason"] = REASON_THEIR_LAPS
            return base
        deltas = [a - b for a, b in zip(_median_segs(mine), _median_segs(theirs), strict=True)]
        v, k1, k2, margin = verdict(deltas, side)
        base.update(verdict=v, margin_s=margin, lap_delta_s=round(sum(deltas), 2))
        if v in ("clear", "spread") and k1 is not None:
            base["corner"] = {"name": seg.names[k1], "text": seg.texts[k1], "delta_s": round(deltas[k1], 2)}
        if k2 is not None and v in ("clear", "spread"):
            base["second"] = {"name": seg.names[k2], "text": seg.texts[k2], "delta_s": round(deltas[k2], 2)}
        return base


def _laps_key(c: GridClock | None) -> tuple[int, int | None]:
    return (0, None) if c is None else (len(c.laps), c.laps[-1].lap if c.laps else None)
