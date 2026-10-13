"""The car's own braking zones from its last laps: the speak window's fallback before a track model is learned (v0.3.0).

The radio's speak window (``voice.scheduler.speak_window_ok``) needs the time to the next braking zone. The hub takes
it from the learned track model, else from the track knowledge (``voice.field_zones``: the AI field's zones, the
physics prior's tags). On a new track, in a fresh database or a joined race neither may cover a corner, and "no zone
known" lets any sentence start: measured on the owner's recorded races replayed into a fresh database, lap summaries
and race calls ran into Suzuka's braking zones on laps 2-5 [M]. The driver's own last laps know where they braked.

``LapBrakeZones.observe`` is fed the live frame on every radio tick (10 Hz, the event loop, never the ingest thread):
a zone starts where the brake reaches ``ON`` and ends where it falls under ``OFF`` (one sample is a zone: a dab of the
pedal is a corner too). When the lap number goes up by one, the lap's zones join the last ``LAPS_KEPT`` laps' (where a
driver braked on one lap and lifted on the next is still a corner: Suzuka [M]) - unless the car was in the pit lane
during it (an in-lap or out-lap brakes for the pit entry and the limiter: Jeddah [M]); any other change (a flashback,
a new session, a restart) starts over without them. ``model()`` is the shape ``voice.hub.time_to_next_braking``
reads, or None. O(1) per tick; a lap keeps at most ``MAX_ZONES`` zones.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

ON = 0.3  # brake pedal (0..1) that starts a zone: real braking, not a trail of the pedal
OFF = 0.05  # the scheduler's "off the brake" (voice.scheduler.CALM_BRAKE)
LAPS_KEPT = 3
PIT_LANE = (1, 2)  # CarFrame.pit_status: in the pit lane, in the pit area
MAX_ZONES = 40


@dataclass(slots=True)
class LapBrakeZones:
    _lap: int | None = None
    _start: float | None = None
    _cur: list[tuple[float, float]] = field(default_factory=list)
    _laps: deque[list[tuple[float, float]]] = field(default_factory=lambda: deque(maxlen=LAPS_KEPT))
    _length: float | None = None
    _seen: object = None
    _pitted: bool = False  # the car was in the pit lane during this lap: its zones are not the track's

    def reset(self) -> None:
        self._lap, self._start, self._cur, self._length, self._seen = None, None, [], None, None
        self._pitted = False
        self._laps.clear()

    def observe(self, frame: Any, track_length_m: float | None) -> None:
        """One live frame (``CarFrame`` or None); the same frame twice is counted once."""
        if frame is None or frame is self._seen:
            return
        self._seen = frame
        lap, d, brake = frame.lap_number, frame.lap_distance_m, frame.brake
        if lap is None or d is None or brake is None or not (math.isfinite(d) and math.isfinite(brake)):
            return
        if track_length_m and math.isfinite(track_length_m) and track_length_m > 0:
            self._length = float(track_length_m)
        if lap != self._lap:
            if self._lap is not None and lap == self._lap + 1:
                if self._start is not None:  # braking across the line: close it at the line
                    self._close(self._length or self._start)
                if self._cur and not self._pitted:
                    self._laps.append(list(self._cur))
            else:
                self._laps.clear()  # a flashback, a new session: the zones of other laps are not this one's
            self._lap, self._start, self._cur, self._pitted = lap, None, [], False
        if getattr(frame, "pit_status", None) in PIT_LANE:
            self._pitted = True
        if self._start is None and brake >= ON and d >= 0.0:
            self._start = d
        elif self._start is not None and brake < OFF:
            self._close(d)

    def _close(self, end: float) -> None:
        start, self._start = self._start, None
        if start is not None and end >= start and len(self._cur) < MAX_ZONES:
            self._cur.append((start, end))

    def model(self) -> dict[str, Any] | None:
        """The last full laps' zones as ``{"length_m", "corners": [{"entry_m", "exit_m"}]}``, else None."""
        if not self._laps:
            return None
        return {
            "length_m": self._length,
            "corners": [{"entry_m": s, "exit_m": e} for lap in self._laps for s, e in lap],
        }


def merged(*models: dict[str, Any] | None) -> dict[str, Any] | None:
    """Several zone models as one (every zone of each; the first known length)."""
    present = [m for m in models if m]
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    length = next((m.get("length_m") for m in present if m.get("length_m")), None)
    return {"length_m": length, "corners": [c for m in present for c in (m.get("corners") or [])]}
