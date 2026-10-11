"""The game's own tyre model (F1 TyreSets, player car): laps left, new-set life and the gain of a new set.

Real F1 25 (PS5): at the end of the Austria excerpt the fitted softs are 11 % worn with 22 laps left (usable life 27).
``lapDeltaTime`` is versus the *fitted* set: new mediums -158 ms (faster), hards +291, inters +3325, wets +4977 and
unused softs -608. Over the full Austria race the gain of
new mediums over the fitted mediums grows 0.274 -> 1.003 s across laps 62-70, about 0.091 s a lap per lap: the
game's degradation model. Everything here is tier ``game`` (the game's estimate).

* Candidates for the next set: available, not fitted, dry, at most ``CANDIDATE_MAX_WEAR`` % worn.
* ``game_laps_left`` = the fitted set's ``lifeSpan``; ``new_set_life`` = the most durable candidate's.
* Next set (for the gain): the fastest candidate that lasts to the flag (life >= laps remaining - 1), else the most
  durable one; ``d0`` = its gain now (s a lap).
* ``g`` = least-squares slope of that compound's gain sampled at the player's line crossings over the stint (at
  least ``DEG_MIN_LAPS``), used only when >= ``DEG_MIN_S_PER_LAP2``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pitwall.model.telemetry import TyreSet, TyreSetsInfo

DRY = frozenset({"soft", "medium", "hard"})
CANDIDATE_MAX_WEAR = 5  # [H] a scrubbed set still counts as new
DEG_MIN_LAPS = 3
DEG_MAX_LAPS = 8
DEG_MIN_S_PER_LAP2 = 0.005  # [H] flatter than this is noise in a 1 ms field


@dataclass(slots=True)
class GameTyres:
    last: TyreSetsInfo | None = None
    lap_at: int | None = None  # the player's lap when ``last`` arrived (the game sends TyreSets about once a second)
    _fitted_key: tuple[int | None, str | None] | None = None
    # compound -> [(player lap, gain of the best new set of that compound over the fitted set, s)]
    _gains: dict[str, list[tuple[int, float]]] = field(default_factory=dict)

    def on_tyre_sets(self, ts: TyreSetsInfo, lap: int | None = None) -> None:
        self.lap_at = lap
        fitted = _fitted(ts)
        key = (ts.fitted_index, None if fitted is None else fitted.visual)
        if key != self._fitted_key:
            self._fitted_key = key
            self._gains.clear()  # a new stint: the degradation series starts again
        self.last = ts

    def on_line(self, lap: int) -> None:
        """The player started ``lap``: sample each dry compound's best new-set gain for the degradation slope."""
        for compound, s in self._best_by_compound().items():
            series = self._gains.setdefault(compound, [])
            gain = -s.lap_delta_ms / 1000
            series[:] = [p for p in series if p[0] != lap]
            series.append((lap, gain))
            del series[:-DEG_MAX_LAPS]

    def rewind_to_lap(self, lap: int) -> None:
        for series in self._gains.values():
            series[:] = [p for p in series if p[0] < lap]

    # ------------------------------------------------------------------ queries
    def fitted(self) -> TyreSet | None:
        return None if self.last is None else _fitted(self.last)

    def candidates(self) -> list[TyreSet]:
        if self.last is None:
            return []
        return [
            s
            for s in self.last.sets
            if s.available and not s.fitted and s.visual in DRY and s.wear_pct <= CANDIDATE_MAX_WEAR
        ]

    def _best_by_compound(self) -> dict[str, TyreSet]:
        out: dict[str, TyreSet] = {}
        for s in self.candidates():
            assert s.visual is not None
            cur = out.get(s.visual)
            if cur is None or s.lap_delta_ms < cur.lap_delta_ms:
                out[s.visual] = s
        return out

    def game_laps_left(self, lap: int | None = None) -> int | None:
        """The fitted set's laps left, less the laps started since the sample: just after the line the last sample
        is up to a second old and still counts the lap just finished."""
        f = self.fitted()
        if f is None:
            return None
        stale = max(0, lap - self.lap_at) if lap is not None and self.lap_at is not None else 0
        return max(0, f.life_span_laps - stale)

    def usable_life(self) -> int | None:
        f = self.fitted()
        return None if f is None else f.usable_life_laps

    def new_set_life(self) -> int | None:
        c = self.candidates()
        return max((s.life_span_laps for s in c), default=None)

    def next_set(self, laps_remaining: float | None) -> TyreSet | None:
        c = self.candidates()
        if not c:
            return None
        if laps_remaining is not None:
            lasting = [s for s in c if s.life_span_laps >= laps_remaining - 1]
            if lasting:
                return min(lasting, key=lambda s: (s.lap_delta_ms, -s.life_span_laps))
        return max(c, key=lambda s: (s.life_span_laps, -s.lap_delta_ms))

    def gain(self, laps_remaining: float | None) -> tuple[str, float, float | None] | None:
        """(compound, d0 = gain now in s/lap, g = degradation slope s/lap per lap or None) of the next set."""
        nxt = self.next_set(laps_remaining)
        if nxt is None or nxt.visual is None:
            return None
        d0 = max(0.0, -nxt.lap_delta_ms / 1000)
        return nxt.visual, round(d0, 3), self.degradation(nxt.visual)

    def degradation(self, compound: str) -> float | None:
        pts = self._gains.get(compound) or []
        if len(pts) < DEG_MIN_LAPS:
            return None
        x = np.array([p[0] for p in pts], dtype=np.float64)
        y = np.array([p[1] for p in pts], dtype=np.float64)
        if np.ptp(x) == 0:
            return None
        g = float(np.polyfit(x, y, 1)[0])
        return round(g, 4) if g >= DEG_MIN_S_PER_LAP2 else None


def _fitted(ts: TyreSetsInfo) -> TyreSet | None:
    if ts.fitted_index is not None and 0 <= ts.fitted_index < len(ts.sets):
        return ts.sets[ts.fitted_index]
    return next((s for s in ts.sets if s.fitted), None)
