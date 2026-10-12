"""Attack and defend: where the player is quicker than the car directly ahead, and where the car behind is quicker
(``RacecraftView``, F1 races, on request only - never a proactive call).

**Segments** are the learned corners of the live track model (``seg_start_m``..``seg_end_m`` partition the lap,
``analysis.track``); they are named as the cues name them (``coach.cues.cue_labels``), else by their learned names.
Without a model the view says "corners not learned yet"; a changed model starts the clocks again.

**SegmentClock** (one per car from the field samples, ~10 Hz; one for the player from its frames): each boundary
crossing time is interpolated between the two samples around it - inside a lap at ``d_prev < b <= d``, at the line
when the lap number goes up with ``d_prev > L - 300`` and ``d < 300`` (interpolated over ``d_prev -> d + L``). Only the
boundary times of the last ``RACECRAFT_KEEP_LAPS`` laps are kept, never raw samples. A car-lap is usable when every
boundary was crossed, the car stayed out of the pit lane, no safety car / VSC ran, the lap was valid, it is not race
lap 1, and (the player) no flashback hit it.

**Verdict** (``SEG_MIN_S`` / ``MARGIN_S``): per segment, Δ = median of the player's last <= 3 usable laps - median of
that car's last <= 3 usable laps (at least two each; negative = the player is quicker). Attack: the most negative Δ;
``clear`` when it is at least ``SEG_MIN_S`` and ``MARGIN_S`` clear of the next one, ``spread`` when the player is
quicker there but not clearly there, ``none`` when the player is not quicker anywhere. Defend mirrors it (the car behind
quicker). On real F1 25 Austria (three sessions on two days) the attack corner was the same on every lap with a car
ahead (margins 0.16-0.97 s); on Imola no defend corner stood out (margins 0.00-0.14 s): "spread", never invented.

**Privacy** (human opponents included; the AI flag is ignored for the computation): in memory only and cleared when
the session ends; nothing goes to SQLite or the log per car; the view carries positions, car indexes and corners only
(no names; F1 names are never decoded here).
"""

from __future__ import annotations

import itertools
import statistics
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pitwall.carhealth import thresholds as T
from pitwall.model.telemetry import RaceTiming

REASON_NO_MODEL = "corners not learned yet"
REASON_NOT_RACE = "attack and defend need an F1 race (the other cars' positions)"
REASON_LEADING = "leading: there's no car ahead"
REASON_LAST = "last: there's no car behind"
REASON_LAPS = "needs two clean laps of you and that car"
REASON_NO_TIMING = "waiting for race timing"


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
class LapSegments:
    lap: int
    segs: tuple[float, ...]
    usable: bool


@dataclass(slots=True)
class _Open:
    lap: int
    times: list[float | None]  # [line, boundary 1, ...]: crossing times of the lap in progress
    pit: bool = False
    sc: bool = False
    invalid: bool = False
    flashback: bool = False


class SegmentClock:
    """Boundary crossing times of one car, interpolated between samples; the last laps' segment times."""

    __slots__ = ("_open", "_prev", "laps", "line_length_m", "seg")

    def __init__(self, seg: Segments, line_length_m: float | None = None) -> None:
        self.seg = seg
        self.line_length_m = line_length_m or seg.length_m  # where the game resets the lap distance
        self.laps: deque[LapSegments] = deque(maxlen=T.RACECRAFT_KEEP_LAPS)
        self._open: _Open | None = None
        self._prev: tuple[int, float, float] | None = None  # (lap, d, t)

    def add(
        self, lap: int, d: float, t: float, *, pit: bool = False, sc: bool = False, invalid: bool = False
    ) -> LapSegments | None:
        """One sample; returns the lap it completed, if any. O(segments) at most, O(1) usually."""
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
        L = self.line_length_m
        done: LapSegments | None = None
        if lap == plap:
            if d < pd - 50.0:
                self._open = None  # moved back along the lap (a reset to track)
                return None
            if op is not None:
                self._cross(op, pd, pt, d, t)
            return None
        if lap == plap + 1 and pd > L - T.LINE_WINDOW_M and d < T.LINE_WINDOW_M:
            span = (d + L) - pd
            t_line = pt + (L - pd) / span * (t - pt) if span > 0 else t
            if op is not None and op.lap == plap:
                op.times.append(t_line)
                done = self._finish(op)
            nxt = _Open(lap, [t_line] + [None] * (len(self.seg.starts) - 1), pit=pit, sc=sc, invalid=invalid)
            self._cross(nxt, 0.0, t_line, d, t)
            self._open = nxt
            return done
        self._open = None  # a jump (skipped lap, rewind): wait for the next line
        return None

    def _cross(self, op: _Open, d0: float, t0: float, d1: float, t1: float) -> None:
        starts = self.seg.starts
        for k in range(1, len(starts)):
            b = starts[k]
            if op.times[k] is None and d0 < b <= d1:
                op.times[k] = t0 + (b - d0) / (d1 - d0) * (t1 - t0) if d1 > d0 else t1

    def _finish(self, op: _Open) -> LapSegments | None:
        times = op.times
        if any(x is None for x in times):
            return None
        ts = [float(x) for x in times if x is not None]
        segs = tuple(b - a for a, b in itertools.pairwise(ts))
        if any(s <= 0 for s in segs):
            return None
        usable = not (op.pit or op.sc or op.invalid or op.flashback) and op.lap != 1
        rec = LapSegments(op.lap, segs, usable)
        self.laps.append(rec)
        return rec

    def flashback(self) -> None:
        """The player's flashback: the lap in progress is not timed (the clock also goes back)."""
        if self._open is not None:
            self._open.flashback = True

    def usable(self, n: int = T.RACECRAFT_LAPS) -> list[tuple[float, ...]]:
        return [lap.segs for lap in self.laps if lap.usable][-n:]


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
    player: SegmentClock | None = None
    cars: dict[int, SegmentClock] = field(default_factory=dict)
    timing: RaceTiming | None = None
    _cache_key: tuple[Any, ...] | None = None
    _cache: dict[str, Any] | None = None

    def set_segments(self, seg: Segments | None, line_length_m: float | None) -> None:
        """A (new) learned model: the clocks start again when the segments changed."""
        if line_length_m:
            self.line_length_m = line_length_m
        if seg is not None and self.seg is not None and seg.key == self.seg.key:
            if seg.texts != self.seg.texts:
                self.seg = seg  # the names changed (identity attached), not the geometry
            return
        if seg is None and self.seg is None:
            return
        self.seg = seg
        self.player = None if seg is None else SegmentClock(seg, self.line_length_m)
        self.cars = {}
        self._cache_key = self._cache = None

    def on_player(
        self, lap: int | None, d: float | None, t: float | None, *, pit: bool, sc: bool, invalid: bool
    ) -> bool:
        """A player frame; True when it completed a lap (the line)."""
        if self.player is None or lap is None or d is None or t is None:
            return False
        return self.player.add(lap, d, t, pit=pit, sc=sc, invalid=invalid) is not None

    def on_field(self, idx: int, lap: int, d: float, t: float, *, pit: bool, sc: bool, invalid: bool) -> None:
        seg = self.seg
        if seg is None:
            return
        clock = self.cars.get(idx)
        if clock is None:
            clock = self.cars[idx] = SegmentClock(seg, self.line_length_m)
        clock.add(lap, d, t, pit=pit, sc=sc, invalid=invalid)

    def flashback(self) -> None:
        if self.player is not None:
            self.player.flashback()

    def clear(self) -> None:
        """Privacy: the session ended - every per-car buffer goes."""
        self.cars = {}
        self.player = None if self.seg is None else SegmentClock(self.seg, self.line_length_m)
        self.timing = None
        self._cache_key = self._cache = None

    # ------------------------------------------------------------------ output
    def compute(self) -> dict[str, Any]:
        """``{"reason", "ahead", "behind"}`` (cached until an input changed)."""
        seg, rt, me_clock = self.seg, self.timing, self.player
        if seg is None or me_clock is None:
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
            len(me_clock.laps),
            me_clock.laps[-1].lap if me_clock.laps else None,
            me.position,
            None if ahead is None else (ahead.car_index, self._laps_key(ahead.car_index)),
            None if behind is None else (behind.car_index, self._laps_key(behind.car_index)),
        )
        if key == self._cache_key and self._cache is not None:
            return self._cache
        mine = me_clock.usable()
        out = {
            "reason": None,
            "ahead": self._side("ahead", ahead.car_index if ahead else None, ahead.position if ahead else None, mine),
            "behind": self._side(
                "behind", behind.car_index if behind else None, behind.position if behind else None, mine
            ),
        }
        self._cache_key, self._cache = key, out
        return out

    def _laps_key(self, idx: int) -> tuple[int, int | None]:
        c = self.cars.get(idx)
        return (0, None) if c is None else (len(c.laps), c.laps[-1].lap if c.laps else None)

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
        theirs = [] if clock is None else clock.usable()
        base["laps_compared"] = [len(mine), len(theirs)]
        if len(mine) < T.RACECRAFT_MIN_LAPS or len(theirs) < T.RACECRAFT_MIN_LAPS:
            base["reason"] = REASON_LAPS
            return base
        deltas = [a - b for a, b in zip(_median_segs(mine), _median_segs(theirs), strict=True)]
        v, k1, k2, margin = verdict(deltas, side)
        base.update(verdict=v, margin_s=margin, lap_delta_s=round(sum(deltas), 2))
        if v in ("clear", "spread") and k1 is not None:
            base["corner"] = {"name": seg.names[k1], "text": seg.texts[k1], "delta_s": round(deltas[k1], 2)}
        if k2 is not None and v in ("clear", "spread"):
            base["second"] = {"name": seg.names[k2], "text": seg.texts[k2], "delta_s": round(deltas[k2], 2)}
        return base
