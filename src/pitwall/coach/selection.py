"""One coaching message, two channels (D6): which of a lap's observations the coach picks.

The radio (``voice.proactive.lap_messages``) and the Drive screen (``snapshot.coach``, built by ``core.live``) take
their coaching points from this module, so the point the radio says about a corner is the point the coach card
shows for it (docs/ui/design-spec.md P7, section 13 D6). Deterministic, no LLM, no I/O.

* **Picked** - the points spoken for a lap, in speaking order: the habit tracker's events (``coach.habits``: a habit
  sorted, improving, announced as the new focus, still there) then the lap's big one-offs
  (``analysis.coaching.is_big_one_off``, by priority) as corrective points, then praise, all under the seated
  driver's limits (``drivers.apply_coaching_limits``: confidence and impact floors, allowed rule kinds, per-lap
  budget, a beginner's lap of grace before the same corner again). Small one-offs and habits that are not the
  focus are screen-only, and a focus habit is not repeated in full every lap (its corner reminder does that; the
  radio says when it improves, is still there after ``habits.STILL_AFTER`` laps, or is sorted). A big fault that
  also happened on the corner's previous lap is no one-off either (``HabitTracker.repeated``): the radio does not
  say the same sentence two laps running, and announces the habit once it is one. Incidents are never
  coaching points: the driver knows they spun. Without a seated driver the limits are
  ``coaching_limits("advanced", intensity)``, which ``drivers`` documents as identical to the radio before profiles
  existed. Without a tracker (``pick_points`` from older callers) a habit is said like a big one-off.
* **Habits** - ``CoachSelection`` owns the session's ``habits.HabitTracker``: updated once per compared lap (not on
  uncompared or drill laps), reset with the session and on a driver change, never on a reference change. Its focus
  slots follow the radio (``habits.focus_slots``: none when quiet, one for a beginner and at normal, two at
  detailed). The block carries its ``habits`` and ``focus`` lists, and every point says whether it is a habit
  (``habit``: status and counts) or a one-off (``one_off``).
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

Block contract (JSON; ``coach_block``)::

    {lap_number, lap_id, ref_lap_number, skill_level, simple_wording, radio_quiet,
     picked: [point],                 # radio order; tracker events have "habit_event" and their own "text"
     by_corner: {corner: point},      # the coach card's point per corner
     habits: [habit],                 # every habit of the session: focus, then seen, then fixed
     focus: [habit + {reminder}]}     # the habits being worked on, with their corner reminder (or None)

    point = slim observation + {picked, habit: {status, laps_seen, laps} | None, one_off: bool}
            (+ for a tracker event: habit_event "announce"|"improving"|"fixed"|"still", was_value, clean_laps,
            clean_of)
    habit = {corner, corner_label, corner_voice, kind, status: "focus"|"seen"|"fixed", laps_seen, laps,
             value (median of the laps it fired), unit, impact_s (mean), since_lap, short}
    reminder = {parts: [spoken corner, phrase], text: "T6: apex speed, 12 down"} | None
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import replace
from typing import Any

from pitwall.analysis.coaching import INCIDENT_KIND, is_big_one_off, is_corrective, is_habit
from pitwall.coach.habits import HabitTracker, focus_slots
from pitwall.drivers import COACHING_INTENSITIES, CoachingLimits, apply_coaching_limits, coaching_limits

DEFAULT_SKILL = "advanced"  # no seated driver: the pre-profile radio (drivers.coaching_limits)
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
    # --- habits (coach.habits) --- a tracker event and its numbers (None on an ordinary observation)
    "habit_event",
    "was_value",
    "clean_laps",
    "clean_of",
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


def _unbounded(lim: CoachingLimits) -> CoachingLimits:
    """``lim``'s filters (floors, kinds, repeat grace) with no per-lap budget."""
    return dataclasses.replace(
        lim, max_per_lap=_UNBOUNDED, max_corrective_per_lap=_UNBOUNDED, max_positive_per_lap=_UNBOUNDED
    )


def passes_limits(
    o: Mapping[str, Any],
    limits: CoachingLimits,
    lap_number: int | None = None,
    last_coached: Mapping[str, int] | None = None,
) -> bool:
    """Whether one point passes ``limits``' filters (floors, allowed kinds, a beginner's repeat grace), whatever the
    per-lap budget. The habit tracker asks it before an announcement takes a focus slot."""
    if limits.max_per_lap <= 0:
        return False
    return bool(apply_coaching_limits([o], _unbounded(limits), lap_number, last_coached))


def _priority(o: Mapping[str, Any]) -> float:
    p = o.get("priority")
    return float(p) if isinstance(p, int | float) and not isinstance(p, bool) else 0.0


def pick_points(
    observations: Sequence[Mapping[str, Any]],
    limits: CoachingLimits | None,
    lap_number: int | None = None,
    last_coached: Mapping[str, int] | None = None,
    *,
    intensity: str = "normal",
    events: Sequence[Mapping[str, Any]] | None = None,
    skip: Callable[[Mapping[str, Any]], bool] | None = None,
) -> list[Mapping[str, Any]]:
    """The points the radio says for a lap, in speaking order: corrective points first - the habit tracker's
    ``events`` in their order, then the big one-offs by priority - then praise, under ``limits`` (floors, kinds,
    repeat grace, per-lap budget). Pure: the caller records them with ``record_coached`` once they are chosen.
    ``intensity`` only matters without ``limits``. ``events`` None = no tracker (older callers): habits are said like
    big one-offs. ``skip``: observations never said as a one-off (a habit already in focus)."""
    lim = radio_limits(limits, intensity)
    if lim.max_per_lap <= 0:
        return []
    points = [o for o in observations if _is_point(o) and (skip is None or not skip(o))]
    if events is None:
        loose = [o for o in points if is_habit(o) or is_big_one_off(o)]
    else:
        loose = [o for o in points if is_big_one_off(o)]
    filters = _unbounded(lim)

    def allowed(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        keep = {id(o) for o in apply_coaching_limits(items, filters, lap_number, last_coached)}
        return [o for o in items if id(o) in keep]

    loose = sorted(allowed(loose), key=lambda o: (-_priority(o), str(o.get("id") or "")))
    corrective = [*allowed(list(events or ())), *loose][: lim.max_corrective_per_lap]
    praise = apply_coaching_limits([o for o in points if o.get("positive")], lim, lap_number, last_coached)
    return [*corrective, *praise][: lim.max_per_lap]


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


def _tag(d: dict[str, Any], tracker: HabitTracker | None) -> dict[str, Any]:
    """A block point's ``habit`` (``{status, laps_seen, laps}`` when it is a habit now; a "sorted" line keeps its
    ``fixed`` status; None without a tracker) and ``one_off`` (corrective and no habit)."""
    event = d.get("habit_event")
    corner, kind = d.get("corner"), d.get("kind")
    d["habit"] = None if tracker is None else tracker.habit_info(corner, kind, fixed=event is not None)
    d["one_off"] = event is None and is_corrective(d) and d["habit"] is None and not is_habit(d)
    return d


def coach_block(
    lap: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    limits: CoachingLimits | None,
    last_coached: MutableMapping[str, int] | None = None,
    *,
    intensity: str = "normal",
    tracker: HabitTracker | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """D6 ``coach`` block for one lap (contract in the module docstring). Screen and radio share it, so call it
    exactly once per lap: unless the radio is quiet it records the picked corners in ``last_coached`` (the caller's
    per-session state) and commits the picked tracker events to ``tracker`` (``HabitTracker.commit``).

    ``intensity`` is the radio's coaching intensity: the budget when ``limits`` is None (no seated driver, as on
    the radio), and a quiet radio with a seated driver says nothing either. ``tracker`` / ``events``: the session's
    habit tracker and this lap's events (``HabitTracker.update``, already run); without a tracker the pick is the
    stateless one (``pick_points`` with ``events`` None) and ``habits`` / ``focus`` are empty.

    ``radio_quiet``: the coaching intensity is quiet, so the radio says none of ``picked`` (the screen still shows
    them)."""
    lap_number = _int(lap.get("lap_number"))
    radio = radio_limits(limits, intensity)
    quiet = radio.max_per_lap <= 0 or intensity == "quiet"
    lim = screen_limits(radio)
    if tracker is None:
        picked = pick_points(observations, lim, lap_number, last_coached)
    else:

        def not_one_off(o: Mapping[str, Any]) -> bool:
            # a focus habit (its reminder says it), or the same fault as on the corner's previous lap (a pattern in
            # the making: the habit is announced when it is one, never the same sentence two laps running)
            corner, kind = o.get("corner"), o.get("kind")
            return tracker.in_focus(corner, kind) or tracker.repeated(corner, kind)

        picked = pick_points(observations, lim, lap_number, last_coached, events=list(events or ()), skip=not_one_off)
    if not quiet:
        if last_coached is not None:
            record_coached(picked, lap_number, last_coached)
        if tracker is not None:
            tracker.commit(picked)
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
        "picked": [_tag(slim(o, True), tracker) for o in picked],
        "by_corner": {c: _tag(slim(o, id(o) in picked_ids), tracker) for c, o in by_corner.items()},
        "habits": tracker.habits() if tracker is not None else [],
        "focus": tracker.focus() if tracker is not None else [],
    }


class CoachSelection:
    """Per-session coaching selection state, shared by the screen and the radio (owned by ``core.live``).

    ``set_limits`` follows the seated driver, ``set_radio_intensity`` the radio hub's coaching intensity; ``reset``
    starts a session. ``select`` is called once per completed lap (analysis thread) and returns that lap's block;
    ``current`` is the latest block whose lap had a usable comparison, which the screen keeps showing (with its lap
    number) through laps that could not be compared (out laps, flashbacks, a missing reference). The session's
    habit tracker (``coach.habits``) lives here: reset with the session and when another driver takes the seat."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._limits: CoachingLimits | None = None
        self._driver_id: int | None = None
        self._driver_known = False
        self._last_coached: dict[str, int] = {}
        self._current: dict[str, Any] | None = None
        self._intensity = "normal"  # the radio's coaching intensity (set_radio_intensity)
        self._habits = HabitTracker()

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
                self._habits.reset()  # the previous driver's habits are not this driver's
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
            self._habits.reset()

    # --- coachref ---
    def set_current(self, block: dict[str, Any]) -> None:
        """Show ``block`` as the current coaching (a practice drill's point, ``coach.drills.with_drill``)."""
        with self._lock:
            self._current = block

    # --- coachref ---

    def select(
        self,
        lap: Mapping[str, Any],
        observations: Sequence[Mapping[str, Any]],
        compared: bool,
        *,
        corners: Sequence[str] | None = None,
        ref_lap_id: int | None = None,
        corner_times: Mapping[str, float | None] | None = None,
        model_version: int | None = None,
    ) -> dict[str, Any]:
        """This lap's block. ``compared``: the lap had a usable comparison and is no drill lap (only then does it
        update the habit tracker and replace ``current``; a lap without one has no points, and the screen keeps the
        last lap that had). ``corners``: the corners the comparison had (``LapComparison.corners``), so the tracker
        sees which corners were driven clean; None = only the corners with an observation. ``ref_lap_id``: the lap
        it was compared with (a reference with the same fault proves no fix, ``HabitTracker.update``).
        ``corner_times`` / ``model_version``: the lap's own time through each corner and the track model version (a
        braking-early habit is called sorted only when its corner got faster)."""
        with self._lock:
            lap_number = _int(lap.get("lap_number"))
            radio = radio_limits(self._limits, self._intensity)
            quiet = radio.max_per_lap <= 0 or self._intensity == "quiet"
            events: list[dict[str, Any]] = []
            if compared:
                lim = screen_limits(radio)
                last = dict(self._last_coached)
                events = self._habits.update(
                    lap_number,
                    observations,
                    corners,
                    slots=focus_slots(radio, quiet),
                    eligible=lambda e: passes_limits(e, lim, lap_number, last),
                    lap_id=_int(lap.get("lap_id")),
                    ref_lap_id=ref_lap_id,
                    corner_times=corner_times,
                    model_version=model_version,
                )
            block = coach_block(
                lap,
                observations,
                self._limits,
                self._last_coached,
                intensity=self._intensity,
                tracker=self._habits,
                events=events,
            )
            if compared:
                self._current = block
            return block
