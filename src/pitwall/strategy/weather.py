"""Weather now, the game's forecast for this session, and the slick / intermediate / wet crossover.

Real F1 25 races send 3 forecast samples (very short races) or 9 (full distance: 0, 5, 10, 15, 30, 45, 60, 90 and
120 minutes) for session type 15; the rain percentage dithers between 1 and 15 every few seconds and the weather
category moves between clear / light cloud / overcast. No rain has been seen in any real capture, so the rain paths
are synthetic only.

* Only samples of this session's type are used (practice and qualifying forecasts ride along in a race weekend).
* ``rain_pct`` is shown verbatim as the game's number; it is never turned into a probability.
* The next change is the first sample within ``HORIZON_MIN`` [H] whose category (dry / light rain / heavy rain)
  differs from now; it must be the same on two consecutive Session packets [H] before it counts.
* Crossover (game estimate, unverified in the wet): the fitted set is a slick and an available intermediate (or wet)
  set has a negative lap delta in the game's tyre model, or the reverse, on two consecutive TyreSets samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pitwall.model.telemetry import SessionInfo, TyreSetsInfo

HORIZON_MIN = 15  # [H] how far ahead a forecast change is announced
FORECAST_SHOWN_MIN = 60  # the view lists samples up to this far ahead ...
FORECAST_SHOWN_MAX = 4  # ... at most this many (the view rides every live snapshot)
DRY = frozenset({"clear", "light_cloud", "overcast"})
HEAVY = frozenset({"heavy_rain", "storm"})
SLICKS = frozenset({"soft", "medium", "hard", "super_soft"})
WET_TYRES = ("inter", "wet")
STABLE_SAMPLES = 2  # [H]


def category(weather: str | None) -> str | None:
    """Weather category: "dry" | "light_rain" | "heavy_rain" | None (unknown)."""
    if weather is None:
        return None
    if weather in DRY:
        return "dry"
    if weather == "light_rain":
        return "light_rain"
    if weather in HEAVY:
        return "heavy_rain"
    return None


@dataclass(slots=True, frozen=True)
class Crossover:
    compound: str  # "inter" | "wet" | "slick": what the game's tyre model now has faster than the fitted set
    gain_s: float


class WeatherTracker:
    def __init__(self) -> None:
        self.now: str | None = None
        self.rain_pct: float | None = None
        self.track_temp_c: float | None = None
        self.accuracy: str | None = None
        self.samples: list[dict[str, Any]] = []
        self._candidate: tuple[int, str | None] | None = None
        self._candidate_count = 0
        self.next_change: dict[str, Any] | None = None
        self._cross_candidate: tuple[str, float] | None = None
        self._cross_count = 0
        self.crossover: Crossover | None = None

    def on_session(self, info: SessionInfo) -> None:
        w = info.weather
        self.now = w.condition
        self.rain_pct = w.rain_percentage
        self.track_temp_c = w.track_temp_c
        acc = info.extra.get("forecast_accuracy")
        self.accuracy = {0: "perfect", 1: "approximate"}.get(acc) if isinstance(acc, int) else None
        stype = info.extra.get("session_type_id")
        raw = info.extra.get("forecast")
        samples = [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []
        if isinstance(stype, int):
            samples = [s for s in samples if s.get("session_type") == stype]
        self.samples = sorted(samples, key=lambda s: int(s.get("time_offset_min") or 0))
        now_sample = next((s for s in self.samples if s.get("time_offset_min") == 0), None)
        if now_sample is not None and isinstance(now_sample.get("rain_pct"), int | float):
            self.rain_pct = float(now_sample["rain_pct"])  # this session's own "now" sample
        cat_now = category(self.now)
        cand: tuple[int, str | None] | None = None
        for s in self.samples:
            off = s.get("time_offset_min")
            if not isinstance(off, int) or not 0 < off <= HORIZON_MIN:
                continue
            c = category(s.get("weather"))
            if c is not None and cat_now is not None and c != cat_now:
                cand = (off, s.get("weather"))
                break
        if cand == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate, self._candidate_count = cand, 1
        if cand is None:
            self.next_change = None
        elif self._candidate_count >= STABLE_SAMPLES:
            sample = next(s for s in self.samples if s.get("time_offset_min") == cand[0])
            self.next_change = {"in_min": cand[0], "weather": cand[1], "rain_pct": sample.get("rain_pct")}

    def on_tyre_sets(self, ts: TyreSetsInfo) -> None:
        fitted = next((s for s in ts.sets if s.fitted), None)
        cand: tuple[str, float] | None = None
        if fitted is not None and fitted.visual in SLICKS:
            best = min(
                (s for s in ts.sets if s.available and not s.fitted and s.visual in WET_TYRES and s.lap_delta_ms < 0),
                key=lambda s: s.lap_delta_ms,
                default=None,
            )
            if best is not None and best.visual is not None:
                cand = (best.visual, round(-best.lap_delta_ms / 1000, 1))
        elif fitted is not None and fitted.visual in WET_TYRES:
            best = min(
                (s for s in ts.sets if s.available and not s.fitted and s.visual in SLICKS and s.lap_delta_ms < 0),
                key=lambda s: s.lap_delta_ms,
                default=None,
            )
            if best is not None:
                cand = ("slick", round(-best.lap_delta_ms / 1000, 1))
        same = cand is not None and self._cross_candidate is not None and cand[0] == self._cross_candidate[0]
        self._cross_count = self._cross_count + 1 if same else (1 if cand is not None else 0)
        self._cross_candidate = cand
        if cand is None:
            self.crossover = None
        elif self._cross_count >= STABLE_SAMPLES:
            self.crossover = Crossover(cand[0], cand[1])

    def view(self, lap_time_s: float | None) -> dict[str, Any]:
        def laps(minutes: int | None) -> int | None:
            if minutes is None or lap_time_s is None or lap_time_s <= 0:
                return None
            return round(minutes * 60 / lap_time_s)

        forecast = [
            {
                "in_min": int(s["time_offset_min"]),
                "weather": s.get("weather"),
                "rain_pct": s.get("rain_pct"),
                "in_laps": laps(int(s["time_offset_min"])),
            }
            for s in self.samples
            if isinstance(s.get("time_offset_min"), int) and 0 < s["time_offset_min"] <= FORECAST_SHOWN_MIN
        ][:FORECAST_SHOWN_MAX]
        nc = None
        if self.next_change is not None:
            nc = {**self.next_change, "in_laps": laps(self.next_change["in_min"])}
        return {
            "now": self.now,
            "rain_pct": None if self.rain_pct is None else round(self.rain_pct),
            "track_temp_c": self.track_temp_c,
            "accuracy": self.accuracy,
            "forecast": forecast,
            "next_change": nc,
            "crossover": None
            if self.crossover is None
            else {"compound": self.crossover.compound, "gain_s": self.crossover.gain_s, "tier": "game"},
        }
