"""Live fuel: burn windows for the throttle model, the fuel status, and where to lift and coast.

Real F1 25 (PS5, full Austria race): fuel in the tank is continuous (about 0.0005 kg steps), 1.37-1.46 kg a lap,
fuel mix always "standard". One-second windows of player frames fit ``rate = 0.00118 + 0.0238 * throttle`` kg/s
with R^2 0.85 over 734 windows (about 92 kg/h at full throttle). The windows here use only representative driving:
not in the pit lane, not paused / replay / not racing / rewound, above ``MIN_SPEED_KPH``, no safety car.

Lift and coast is always *before* the normal braking point, braking at the same point: the corners named are the
ones after the longest straights of the learned track (named like the braking cues). Nothing here ever says brake
later.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any

from pitwall.analysis.strategy import BurnModel, fit_burn_model
from pitwall.coach.cues import cue_labels
from pitwall.model.telemetry import CarFrame, FrameQuality

WINDOW_S = 1.0  # [R] one-second windows of session time
MIN_WINDOW_S = 0.8
MAX_WINDOW_S = 1.5  # a longer gap between frames is packet loss: no window
MAX_RATE_KG_S = 0.2  # [R] above this is a refuel / reset, not burn
KEEP_WINDOWS = 900
MIN_SPEED_KPH = 50.0
FUEL_TIGHT_LAPS = 0.3  # = voice.proactive.FUEL_TIGHT_LAPS
FUEL_LIMIT_LAPS = 0.05  # = voice.proactive.FUEL_LIMIT_LAPS
MIN_GREEN_LAPS = 2
LNC_CORNERS = 3
_BAD = (
    FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING | FrameQuality.NOT_RACING | FrameQuality.FLASHBACK_SEGMENT
)


class BurnWindows:
    """One-second fuel-burn windows ``(end time, kg/s, mean throttle)`` from the player's frames."""

    def __init__(self) -> None:
        self.windows: deque[tuple[float, float, float]] = deque(maxlen=KEEP_WINDOWS)
        self._t0: float | None = None
        self._fuel0 = 0.0
        self._thr = 0.0
        self._n = 0
        self._model: BurnModel | None = None
        self._added = 0  # windows ever added (the deque rolls)
        self._fitted_at = -1

    def feed(self, f: CarFrame, neutral: bool) -> None:
        t, fuel, thr = f.session_time_s, f.fuel_kg, f.throttle
        ok = (
            t is not None
            and fuel is not None
            and thr is not None
            and not neutral
            and not f.pit_status
            and not (f.quality & _BAD)
            and (f.speed_kph or 0.0) > MIN_SPEED_KPH
        )
        if not ok:
            self._t0 = None
            return
        assert t is not None and fuel is not None and thr is not None
        if self._t0 is None or t < self._t0:
            self._start(t, fuel, thr)
            return
        dt = t - self._t0
        if dt >= WINDOW_S:
            if MIN_WINDOW_S <= dt <= MAX_WINDOW_S and self._n:
                rate = (self._fuel0 - fuel) / dt
                if 0.0 <= rate <= MAX_RATE_KG_S:
                    self.windows.append((t, rate, self._thr / self._n))
                    self._added += 1
            self._start(t, fuel, thr)
            return
        self._thr += thr
        self._n += 1

    def _start(self, t: float, fuel: float, thr: float) -> None:
        self._t0, self._fuel0, self._thr, self._n = t, fuel, thr, 1

    def rewind(self, t: float) -> None:
        while self.windows and self.windows[-1][0] > t:
            self.windows.pop()
        self._t0 = None
        self._fitted_at = -1

    def model(self) -> BurnModel | None:
        """The burn model, refitted after every 30 new windows (cheap: <= 900 points)."""
        if self._fitted_at < 0 or self._added - self._fitted_at >= 30:
            self._model = fit_burn_model([(r, thr) for _, r, thr in self.windows])
            self._fitted_at = self._added
        return self._model


def fuel_status(margin_laps: float | None, green_laps: int) -> str:
    if margin_laps is None or green_laps < MIN_GREEN_LAPS:
        return "unknown"
    if margin_laps <= -FUEL_LIMIT_LAPS:
        return "short"
    if margin_laps < FUEL_TIGHT_LAPS:
        return "tight"
    return "ok"


def lift_corners(track_model: Mapping[str, Any] | None, n: int = LNC_CORNERS) -> list[str]:
    """Up to ``n`` learned corners with the longest straight before them (entry - previous exit, cyclic), in lap
    order, named as the braking cues and the track view name them. Empty without a learned track."""
    if not isinstance(track_model, Mapping):
        return []
    corners = [c for c in track_model.get("corners") or [] if isinstance(c, Mapping)]
    length = track_model.get("length_m")
    if len(corners) < 2 or not isinstance(length, int | float):
        return []
    try:
        ordered = sorted(corners, key=lambda c: float(c["entry_m"]))
        straights = []
        for k, c in enumerate(ordered):
            prev = ordered[k - 1]
            gap = (float(c["entry_m"]) - float(prev["exit_m"])) % float(length)
            straights.append((gap, float(c["entry_m"]), str(c["name"])))
    except (KeyError, TypeError, ValueError):
        return []
    labels = cue_labels(track_model)
    top = sorted(sorted(straights, reverse=True)[:n], key=lambda s: s[1])
    return [labels[name].text if name in labels else name for _, _, name in top]
