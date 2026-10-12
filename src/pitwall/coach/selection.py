"""One coaching message, two channels (D6): which of a lap's observations the coach picks.

The radio (``voice.proactive.lap_messages``) and the Drive screen (``snapshot.coach``, built by ``core.live``) take
their coaching points from this module, so the point the radio says about a corner is the point the coach card
shows for it (docs/ui/design-spec.md P7, section 13 D6). Deterministic, no LLM, no I/O.

* **Picked** - the points spoken for a lap, in speaking order: ``drivers.apply_coaching_limits`` over the lap's
  non-incident observations with the seated driver's limits (confidence and impact floors, allowed rule kinds,
  per-lap budget, a beginner's lap of grace before the same corner again). Incidents are never coaching points:
  the driver knows they spun. Without a seated driver the limits are ``coaching_limits("advanced", intensity)``,
  which ``drivers`` documents as identical to the radio before profiles existed.
* **By corner** - for each corner, the point the coach card shows when that corner is next: the picked point
  when the corner was picked (so screen and radio agree), else the corner's best point that passes the same
  filters (the per-lap budget and the repeat grace limit what is *said*, not what may be *shown*). Corrective
  points rank before praise, then by analysis ``priority``.
* **Quiet** - a driver on quiet intensity hears no lap coaching, but the screen still shows their points: the
  pick uses the same skill level at normal intensity and the block says ``radio_quiet``.
* **The radio's intensity** - the radio hub tells the selection its coaching intensity
  (``CoachSelection.set_radio_intensity``: the seated driver's, or the one a radio device chose). With nobody in the
  seat it sets the budget (``coaching_limits("advanced", intensity)``, exactly what the radio uses), so a Detailed
  radio picks two corrective points and one positive on the screen too; with a seated driver their profile sets
  the budget (as on the radio) and only a quiet radio matters (``radio_quiet``).

Observation dicts are ``analysis.coaching.Observation.to_dict()`` shapes. Blocks carry slim copies (``slim``:
``COACH_FIELDS`` and the scalar evidence) because the snapshot is sent many times a second; they hold everything
``voice.proactive.coaching_text`` reads, and the full observation stays in ``observations[]``.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import replace
from typing import Any

from pitwall.drivers import COACHING_INTENSITIES, CoachingLimits, apply_coaching_limits, coaching_limits

DEFAULT_SKILL = "advanced"  # no seated driver: the pre-profile radio (drivers.coaching_limits)
INCIDENT_KIND = "incident"
_UNBOUNDED = 1_000_000
# What the coach card, the Ready card and the Session complete card read (types.ts ``ObservationNext``).
COACH_FIELDS = (
    "id",
    "kind",
    "corner",
    "corner_label",
    "lap_number",
    "ref_lap_number",
    "metric",
    "value",
    "unit",
    "impact_s",
    "confidence",
    "priority",
    "positive",
    "consistency",
    "consistency_ratio",
    "text",
    "text_simple",
    "short",
    "corner_voice",
    "ref_name",  # --- coachref --- the other driver a point is measured against (None = the driver's own lap)
)


def radio_limits(limits: CoachingLimits | None, intensity: str = "normal") -> CoachingLimits:
    """The limits the radio speaks with: the seated driver's, else the pre-profile radio at ``intensity``."""
    return limits if limits is not None else coaching_limits(DEFAULT_SKILL, intensity)


def screen_limits(limits: CoachingLimits | None) -> CoachingLimits:
    """The limits the screen shows with: the radio's, except that quiet intensity still shows points."""
    lim = radio_limits(limits)
    if lim.max_per_lap > 0:
        return lim
    # race radio: keep the driver's wording choice (drivers.coaching_limits ``wording``)
    return replace(coaching_limits(lim.skill_level, "normal"), simple_wording=lim.simple_wording)


def _is_point(o: Mapping[str, Any]) -> bool:
    return o.get("kind") != INCIDENT_KIND


def pick_points(
    observations: Sequence[Mapping[str, Any]],
    limits: CoachingLimits | None,
    lap_number: int | None = None,
    last_coached: Mapping[str, int] | None = None,
    *,
    intensity: str = "normal",
) -> list[Mapping[str, Any]]:
    """The points the radio says for a lap, in speaking order (corrective first, then praise). Pure: the caller
    records them with ``record_coached`` once they are chosen. ``intensity`` only matters without ``limits``."""
    points = [o for o in observations if _is_point(o)]
    return list(apply_coaching_limits(points, radio_limits(limits, intensity), lap_number, last_coached))


def record_coached(
    picked: Sequence[Mapping[str, Any]], lap_number: int | None, last_coached: MutableMapping[str, int]
) -> None:
    """Remember the corners coached on ``lap_number`` (corrective points only; praise never blocks a corner)."""
    if lap_number is None:
        return
    for o in picked:
        corner = o.get("corner")
        if corner and not o.get("positive"):
            last_coached[str(corner)] = lap_number


def corner_points(
    observations: Sequence[Mapping[str, Any]],
    limits: CoachingLimits | None,
    lap_number: int | None,
    picked: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Mapping[str, Any]]:
    """``{corner: point}``: the picked point for picked corners, else the corner's best point under the screen's
    limits with no per-lap budget and no repeat grace."""
    lim = dataclasses.replace(
        screen_limits(limits),
        max_per_lap=_UNBOUNDED,
        max_corrective_per_lap=_UNBOUNDED,
        max_positive_per_lap=_UNBOUNDED,
        corner_repeat_gap_laps=0,
    )
    out: dict[str, Mapping[str, Any]] = {}
    for o in picked:
        corner = o.get("corner")
        if corner and str(corner) not in out:
            out[str(corner)] = o
    for o in apply_coaching_limits([o for o in observations if _is_point(o)], lim, lap_number):
        corner = o.get("corner")
        if corner and str(corner) not in out:
            out[str(corner)] = o
    return out


def slim(o: Mapping[str, Any], picked: bool) -> dict[str, Any]:
    """The coach card's copy of an observation: ``COACH_FIELDS``, the scalar evidence (the per-lap metric dicts
    ``evidence.ref`` / ``evidence.lap`` stay in ``observations[]``) and whether the coach picked it."""
    d = {k: o.get(k) for k in COACH_FIELDS}
    ev = o.get("evidence")
    d["evidence"] = (
        {k: v for k, v in ev.items() if isinstance(v, int | float) and not isinstance(v, bool)}
        if isinstance(ev, Mapping)
        else {}
    )
    d["picked"] = picked
    return d


def _int(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def coach_block(
    lap: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    limits: CoachingLimits | None,
    last_coached: MutableMapping[str, int] | None = None,
    *,
    intensity: str = "normal",
) -> dict[str, Any]:
    """D6 ``coach`` block for one lap. Screen and radio share it, so call it exactly once per lap: it records the
    picked corners in ``last_coached`` (the caller's per-session state) unless the radio is quiet.

    ``intensity`` is the radio's coaching intensity: the budget when ``limits`` is None (no seated driver, as on
    the radio), and a quiet radio with a seated driver says nothing either.

    ``{lap_number, lap_id, ref_lap_number, skill_level, simple_wording, radio_quiet, picked: [...],
    by_corner: {corner: ...}}``. ``radio_quiet``: the coaching intensity is quiet, so the radio says none of
    ``picked`` (the screen still shows them)."""
    lap_number = _int(lap.get("lap_number"))
    radio = radio_limits(limits, intensity)
    quiet = radio.max_per_lap <= 0 or intensity == "quiet"
    lim = screen_limits(radio)
    picked = pick_points(observations, lim, lap_number, last_coached)
    if last_coached is not None and not quiet:
        record_coached(picked, lap_number, last_coached)
    picked_ids = {id(o) for o in picked}
    by_corner = corner_points(observations, radio, lap_number, picked)
    refs = [_int(o.get("ref_lap_number")) for o in observations]
    return {
        "lap_number": lap_number,
        "lap_id": _int(lap.get("lap_id")),
        "ref_lap_number": next((r for r in refs if r is not None), None),
        "skill_level": lim.skill_level,
        "simple_wording": lim.simple_wording,
        "radio_quiet": quiet,
        "picked": [slim(o, True) for o in picked],
        "by_corner": {c: slim(o, id(o) in picked_ids) for c, o in by_corner.items()},
    }


class CoachSelection:
    """Per-session coaching selection state, shared by the screen and the radio (owned by ``core.live``).

    ``set_limits`` follows the seated driver, ``set_radio_intensity`` the radio hub's coaching intensity; ``reset``
    starts a session. ``select`` is called once per completed lap (analysis thread) and returns that lap's block;
    ``current`` is the latest block whose lap had a usable comparison, which the screen keeps showing (with its lap
    number) through laps that could not be compared (out laps, flashbacks, a missing reference)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._limits: CoachingLimits | None = None
        self._driver_id: int | None = None
        self._driver_known = False
        self._last_coached: dict[str, int] = {}
        self._current: dict[str, Any] | None = None
        self._intensity = "normal"  # the radio's coaching intensity (set_radio_intensity)

    @property
    def limits(self) -> CoachingLimits | None:
        return self._limits

    @property
    def radio_intensity(self) -> str:
        return self._intensity

    @property
    def current(self) -> dict[str, Any] | None:
        return self._current

    def set_limits(self, driver_id: int | None, limits: CoachingLimits | None) -> None:
        """The seated driver changed or edited their profile. Like the radio (``RadioHub.apply_driver``) the
        corner grace restarts; a different driver also loses the previous driver's coach card."""
        with self._lock:
            if self._driver_known and driver_id != self._driver_id:
                self._current = None
            self._driver_known = True
            self._driver_id = driver_id
            self._limits = limits
            self._last_coached.clear()

    def set_radio_intensity(self, intensity: str) -> None:
        """The radio's coaching intensity changed (``RadioHub``: the seated driver's, or a radio device's choice).
        The next lap's pick uses it; the card on screen and the corner grace are left alone. Unknown values are
        ignored."""
        if intensity in COACHING_INTENSITIES:
            with self._lock:
                self._intensity = intensity

    def reset(self) -> None:
        with self._lock:
            self._last_coached.clear()
            self._current = None

    # --- coachref ---
    def set_current(self, block: dict[str, Any]) -> None:
        """Show ``block`` as the current coaching (a practice drill's point, ``coach.drills.with_drill``)."""
        with self._lock:
            self._current = block

    # --- coachref ---

    def select(
        self, lap: Mapping[str, Any], observations: Sequence[Mapping[str, Any]], compared: bool
    ) -> dict[str, Any]:
        """This lap's block. ``compared``: the lap had a usable comparison (only then does it replace
        ``current``; a lap without one has no points, and the screen keeps the last lap that had)."""
        with self._lock:
            block = coach_block(lap, observations, self._limits, self._last_coached, intensity=self._intensity)
            if compared:
                self._current = block
            return block
