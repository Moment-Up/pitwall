"""Habit tracker: which corner faults keep coming back, which one the driver is working on, and when it is sorted.

A tester's verdict on the radio before this: "feedback every corner isn't helpful - need to identify trends". The
radio picked the lap's biggest point, so it jumped from corner to corner, repeated a habit word for word every lap
and never said when something was fixed. This module is the session's memory of habits; ``coach.selection`` turns
its events into the radio's corrective points and the coach block. Deterministic, no LLM, no I/O.

Ownership and threads: ``coach.selection.CoachSelection`` owns one tracker per live session (analysis thread, under
the selection's lock). It is reset with the session and when another driver takes the seat, never on a reference
change (``core.lap_processor`` re-bases its habit memory on a new best instead). ``update`` runs once per compared
lap; laps that were not compared (out laps, flashbacks, no reference) and practice-drill laps do not update it.

State per ``(corner, kind)``: the last ``HABIT_WINDOW`` compared laps of that corner - a corner counts as compared on
a lap when the comparison had it and it was not an incident there - with whether that kind fired, its value and its
impact. ``laps_seen`` / ``laps`` are those counts ("3 of the last 4 laps": the kind fired, i.e. lost time that way,
on 3 of the corner's last 4 compared laps). A ``(corner, kind)`` becomes a habit on a lap whose observation is one
by ``analysis.coaching.is_habit`` (the one definition) and whose window backs it (``backed``: at least
``HABIT_MIN_LAPS`` compared laps, ``HABIT_RATIO`` of them with it), so what the radio and the coach card say about
it ("3 of the last 4 laps") is true of the laps counted here. Status:

* ``seen``  - a habit, not on the radio (no free focus slot, or the radio's limits do not let it through).
* ``focus`` - announced on the radio and being worked on: at most ``focus_slots`` of them, one per corner.
* ``fixed`` - it stopped (``stopped``: absent on ``FIXED_CLEAN`` of the last ``FIXED_OF`` compared laps of its
  corner, the latest included, and at least ``FIXED_CLEAN`` compared laps after its status began, so the clean laps
  are laps after the announcement, never the gaps that were already inside "3 of the last 4") and those laps prove it
  sorted (``sorted_proof``): ``FIXED_CLEAN`` of them, the latest included, clean at the corner - no corrective point
  of any kind there, so "clean" is true - and, for a fault whose fix is braking later
  (``analysis.coaching.LATER_BRAKING_FIXES``), the corner faster on each of them than on every lap it fired on (the
  lap's own time through the corner, ``update``'s ``corner_times``: later braking is praised only when the corner got
  faster). A habit that stopped without that proof keeps its status (no "still": it did not fire) while the next laps
  may still prove it; after ``PROOF_WAIT`` such laps it is no habit any more and nothing is claimed: it leaves the
  focus without a word. A fixed entry (and any entry that is no habit) leaves the tracker once its window holds no lap
  where it fired; it becomes ``seen`` again when it is a habit again.

Reference-relative evidence: a fault is measured against the reference lap, so when the reference becomes a lap that
had the same fault (a new best set with the habit), a lap without it proves nothing: such laps are not counted for
that habit (``update``'s ``ref_lap_id``; a lap not counted cannot show it either when it becomes the reference), and
it is never called sorted because the reference moved. A habit that cannot be measured for ``HABIT_WINDOW`` compared
laps in a row is forgotten without a word (its slot frees).

Radio events, at most these per compared lap and in this order (``EVENT_ORDER``):

1. ``fixed``     - a focus habit stopped and is proven sorted; its slot frees.
2. ``improving`` - once per focus habit: it still fires, but at most ``IMPROVED_FRACTION`` of its size when announced.
3. ``announce``  - a habit seen on this lap takes a free slot (highest mean impact first; the radio's limits decide
   which ones may: ``eligible``).
4. ``still``     - a focus habit with no improvement ``STILL_AFTER`` compared laps after its announcement, then once
   per ``STILL_AFTER``.

Events are ``Observation.to_dict()``-shaped dicts with ``habit_event`` set (see ``event``), so the radio's limits and
the coach card treat them like any point. ``commit`` records the events the radio actually picked: an announcement
that did not get through leaves the habit ``seen``; ``improving`` and ``still`` are marked said. A ``fixed`` change of
status happens whether or not its line is picked. Progress events (``fixed``, ``improving``) carry the impact and
confidence of the announcement: they are about the habit that was announced, so the floors that let it through let
its progress through (this lap's smaller numbers stay in ``value``).

Wording: every event dict has a screen ``text`` / ``text_simple`` / ``short`` (descriptive, never an instruction to
brake later); the radio rebuilds its own sentence from the structured fields (``voice.proactive.coaching_text``).
``reminder_phrase`` is the short corner reminder of a focus habit (spoken before the corner by the cue engine).
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from pitwall.analysis.coaching import (
    HABIT_MIN_LAPS,
    HABIT_RATIO,
    INCIDENT_KIND,
    LATER_BRAKING_FIXES,
    is_corrective,
    is_habit,
    short_text,
)

if TYPE_CHECKING:
    from pitwall.drivers import CoachingLimits

__all__ = [
    "EVENT_ANNOUNCE",
    "EVENT_FIXED",
    "EVENT_IMPROVING",
    "EVENT_ORDER",
    "EVENT_STILL",
    "FIXED_CLEAN",
    "FIXED_OF",
    "HABIT_WINDOW",
    "IMPROVED_FRACTION",
    "PROOF_WAIT",
    "STATUS_FIXED",
    "STATUS_FOCUS",
    "STATUS_SEEN",
    "STILL_AFTER",
    "HabitTracker",
    "focus_slots",
    "progress_amount",
    "reminder",
    "reminder_phrase",
]

# [H] Compared laps of a corner remembered per (corner, kind): the lap processor's habit memory (HISTORY_LAPS 5) - a
# stint's worth, long enough to tell a habit from a one-off, short enough that an old habit fades within a run.
HABIT_WINDOW: Final = 5
# [H] Fixed = absent on 2 of the corner's last 3 compared laps, the latest included: one clean lap can be luck, two
# in three is a change; and the habit is not called fixed while it is still there on the latest lap.
FIXED_CLEAN: Final = 2
FIXED_OF: Final = 3
# [H] A habit that stopped but whose laps do not prove it sorted yet (another fault at the corner, or braking later on
# a first lap that is no faster while the driver adapts) waits this many compared laps for the proof, then leaves the
# focus without a word: one FIXED_OF window, so the proof can come from laps after the unproven ones.
PROOF_WAIT: Final = 3
# [H] "Improving" = at most half of its size when announced: well past the lap-to-lap scatter of one corner's metric
# (a few km/h, a few metres), so it is real progress, said once.
IMPROVED_FRACTION: Final = 0.5
# [H] A focus habit with no progress is mentioned again after 5 compared laps of its corner (then once per 5): the
# corner reminder says it every lap meanwhile, so the radio does not need to; five laps is one HABIT_WINDOW.
STILL_AFTER: Final = 5

STATUS_SEEN: Final = "seen"
STATUS_FOCUS: Final = "focus"
STATUS_FIXED: Final = "fixed"
EVENT_FIXED: Final = "fixed"
EVENT_IMPROVING: Final = "improving"
EVENT_ANNOUNCE: Final = "announce"
EVENT_STILL: Final = "still"
EVENT_ORDER: tuple[str, ...] = (EVENT_FIXED, EVENT_IMPROVING, EVENT_ANNOUNCE, EVENT_STILL)
_STATUS_RANK = {STATUS_FOCUS: 0, STATUS_SEEN: 1, STATUS_FIXED: 2}


def focus_slots(limits: CoachingLimits, quiet: bool) -> int:
    """How many habits the radio works on at once: none while the radio is quiet (the screen still shows habits and
    the tracker still tracks), one for a beginner at any intensity and at normal intensity, two at detailed."""
    if quiet or limits.max_per_lap <= 0:
        return 0
    if limits.skill_level == "beginner":
        return 1
    return 2 if limits.intensity == "detailed" else 1


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _round5(x: float) -> int:
    return int(5 * round(x / 5))


def reminder_phrase(kind: str, value: float | None) -> str | None:
    """The short corner reminder of a habit (without the corner name), from its typical value, rounded (speed to
    1 km/h, distance to 5 m): ``low_min_speed`` -> "apex speed, 12 down", ``late_throttle`` -> "throttle, 40 metres
    late", ``coasting`` -> "coasting, 30 metres". None for other kinds (braking habits get a braking call instead)
    and for an unknown value: no template, nothing said. Descriptive: never tells the driver to brake later."""
    v = _num(value)
    if v is None:
        return None
    a = abs(v)
    if kind == "low_min_speed":
        return f"apex speed, {round(a)} down"
    if kind == "late_throttle":
        return f"throttle, {_round5(a)} metres late"
    if kind == "coasting":
        return f"coasting, {_round5(a)} metres"
    return None


def reminder(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """``{"parts": [spoken corner, phrase], "text": "T6: apex speed, 12 down"}`` for a habit entry (``habits`` /
    ``focus`` shape), or None when its kind has no reminder template. The spoken corner is the radio form
    (``corner_voice``), else the label, else the learned name; the cue engine may say its own spoken label."""
    phrase = reminder_phrase(str(entry.get("kind") or ""), entry.get("value"))
    if phrase is None:
        return None
    corner = str(entry.get("corner") or "")
    label = str(entry.get("corner_label") or corner)
    spoken = str(entry.get("corner_voice") or label)
    return {"parts": [spoken, phrase], "text": f"{label}: {phrase}"}


def progress_amount(kind: str, value: float | None) -> str | None:
    """How big a habit is on one lap, in a few descriptive words ("6 km/h down", "braking 9 m early"), for the
    radio's "better" line; None for an unknown kind or value."""
    v = _num(value)
    if v is None:
        return None
    a = abs(v)
    phrases = {
        "brake_early": f"braking {a:.0f} m early",
        "brake_late_overdrive": f"braking {a:.0f} m later",
        "low_min_speed": f"{a:.0f} km/h down",
        "overspeed_apex": f"{a:.0f} km/h too fast in",
        "late_throttle": f"full throttle {a:.0f} m late",
        "coasting": f"{a:.0f} m coasting",
    }
    return phrases.get(kind)


@dataclass(slots=True)
class _Lap:
    """One compared lap of a corner, for one kind: did it fire, and its value and impact when it did; the lap's id;
    whether the corner was clean (no corrective point of any kind there; unknown = not clean); the lap's own time
    through the corner and the track model version that time was measured with (None = unknown / unversioned)."""

    fired: bool
    value: float | None = None
    impact_s: float | None = None
    lap_id: int | None = None
    clean: bool = False
    time_s: float | None = None
    model: int | None = None


@dataclass(slots=True)
class _Habit:
    corner: str
    kind: str
    laps: deque[_Lap] = field(default_factory=lambda: deque(maxlen=HABIT_WINDOW))
    status: str | None = None  # None = tracked, not a habit
    since_lap: int | None = None  # the lap the current status started on
    status_at: int = 0  # the corner's compared-lap count when the current status started
    obs: Mapping[str, Any] | None = None  # the latest observation of this kind here (names, unit, wordings)
    fired_now: bool = False  # it fired on the corner's latest compared lap
    # the announcement (status focus)
    announced_value: float | None = None
    announced_impact: float | None = None
    announced_confidence: float | None = None
    still_at: int = 0  # the corner's compared-lap count at the announcement or the last "still"
    improving_said: bool = False
    # laps that could not show it (compared with a lap that had it), and how many in a row (``HabitTracker.update``)
    blind_ids: deque[int] = field(default_factory=lambda: deque(maxlen=2 * HABIT_WINDOW))
    blind_run: int = 0
    unproven: int = 0  # compared laps in a row it has stopped without proof of a fix (``PROOF_WAIT``)

    def counts(self) -> tuple[int, int]:
        return sum(1 for lap in self.laps if lap.fired), len(self.laps)

    def backed(self) -> bool:
        """The window itself shows a habit: ``HABIT_MIN_LAPS`` laps or more, ``HABIT_RATIO`` of them with it."""
        seen, laps = self.counts()
        return laps >= HABIT_MIN_LAPS and seen / laps >= HABIT_RATIO

    def fired_values(self) -> list[float]:
        return [lap.value for lap in self.laps if lap.fired and lap.value is not None]

    def typical_value(self) -> float | None:
        """Median value over the laps it fired in the window (the reminder's number)."""
        vals = self.fired_values()
        return round(statistics.median(vals), 3) if vals else None

    def mean_impact(self) -> float | None:
        vals = [lap.impact_s for lap in self.laps if lap.fired and lap.impact_s is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    def stopped(self, corner_laps: int) -> bool:
        """Absent on ``FIXED_CLEAN`` of the last ``FIXED_OF`` compared laps, the latest included, with at least
        ``FIXED_CLEAN`` compared laps since the status began (``corner_laps``: the corner's count now)."""
        last = list(self.laps)[-FIXED_OF:]
        clean = sum(1 for lap in last if not lap.fired)
        settled = corner_laps - self.status_at >= FIXED_CLEAN
        return bool(last) and not last[-1].fired and clean >= FIXED_CLEAN and settled

    def sorted_proof(self) -> int | None:
        """How many of the last ``FIXED_OF`` compared laps show the habit sorted (``proves``), or None when they do
        not prove it: at least ``FIXED_CLEAN`` of them, the latest included."""
        last = list(self.laps)[-FIXED_OF:]
        good = [lap for lap in last if self.proves(lap)]
        if not last or not self.proves(last[-1]) or len(good) < FIXED_CLEAN:
            return None
        return len(good)

    def proves(self, lap: _Lap) -> bool:
        """One lap shows the habit sorted: it did not fire and the corner was clean (no corrective point of any kind:
        "clean on 2 of the last 3 laps" is true of the corner, not only of this kind). For a fault whose fix is later
        braking (``LATER_BRAKING_FIXES``) the corner was also faster than on every lap in the window the fault fired
        on, all times known and measured with the same corner definitions (track model version): later braking is
        praised only when the corner got faster; unknown stays unknown."""
        if lap.fired or not lap.clean:
            return False
        if self.kind not in LATER_BRAKING_FIXES:
            return True
        lost = [x for x in self.laps if x.fired]
        t = lap.time_s
        return (
            t is not None
            and bool(lost)
            and all(x.time_s is not None and x.model == lap.model and t < x.time_s for x in lost)
        )

    def blind(self, ref_lap_id: int | None) -> bool:
        """The reference lap ``ref_lap_id`` is a lap where this fault fired (in the window), or a lap that could not
        show it itself: compared with it, a lap without the fault says nothing about the habit."""
        if ref_lap_id is None:
            return False
        return ref_lap_id in self.blind_ids or any(lap.fired and lap.lap_id == ref_lap_id for lap in self.laps)

    def improved(self) -> bool:
        """Fired on the latest lap at most ``IMPROVED_FRACTION`` of its announced size."""
        now = self.laps[-1].value if self.laps and self.laps[-1].fired else None
        was = self.announced_value
        return now is not None and was is not None and abs(now) <= IMPROVED_FRACTION * abs(was)


class HabitTracker:
    """Per-session habit state (see the module docstring). Not thread-safe: its owner (``CoachSelection``) holds a
    lock around every call."""

    def __init__(self) -> None:
        self._habits: dict[tuple[str, str], _Habit] = {}
        self._corner_laps: dict[str, int] = {}  # corner -> compared laps of it this session

    def reset(self) -> None:
        self._habits.clear()
        self._corner_laps.clear()

    # ------------------------------------------------------------------ per compared lap
    def update(
        self,
        lap_number: int | None,
        observations: Sequence[Mapping[str, Any]],
        corners: Collection[str] | None = None,
        *,
        slots: int = 1,
        eligible: Callable[[Mapping[str, Any]], bool] | None = None,
        lap_id: int | None = None,
        ref_lap_id: int | None = None,
        corner_times: Mapping[str, float | None] | None = None,
        model_version: int | None = None,
    ) -> list[dict[str, Any]]:
        """Record one compared lap and return its radio events (``EVENT_ORDER``).

        ``observations`` are the lap's ``Observation.to_dict()`` shapes; ``corners`` the corners the comparison had
        (None = unknown: then only corners with an observation count as compared, so nothing can be seen fixed).
        ``lap_id`` / ``ref_lap_id``: this lap and the reference it was compared with. A lap without a fault proves
        nothing when the reference lap itself had that fault (a new best set with the habit, ``_blind``): such a
        lap is not counted for that habit, so it is never called sorted because the reference moved.
        ``corner_times``: this lap's own time through each compared corner (``CornerMetrics.segment_time_s``: it does
        not depend on the reference, which moves with every new best) and ``model_version`` the track model those
        corners come from; a braking-early habit is only called sorted when the corner got faster
        (``_Habit.sorted_proof``), so without times it stops without a word.
        ``slots`` is ``focus_slots`` of the radio's limits. ``eligible`` says whether an announcement could pass the
        radio's limits (floors, allowed kinds, a beginner's repeat grace); an ineligible habit stays ``seen`` and
        does not block another from the free slot."""
        points: dict[tuple[str, str], Mapping[str, Any]] = {}
        incidents: set[str] = set()
        for o in observations:
            corner, kind = o.get("corner"), o.get("kind")
            if not corner or not kind:
                continue
            if kind == INCIDENT_KIND:
                incidents.add(str(corner))
            elif is_corrective(o):
                points.setdefault((str(corner), str(kind)), o)
        names = [str(c) for c in corners] if corners is not None else [c for c, _ in points]
        compared = {c for c in names if c not in incidents}
        dirty = {c for c, _ in points}  # corners with a corrective point of any kind on this lap
        times = corner_times or {}
        for c in compared:
            self._corner_laps[c] = self._corner_laps.get(c, 0) + 1
        for h in self._habits.values():
            h.fired_now = False
        for key in points:
            if key[0] in compared and key not in self._habits:
                h = self._habits[key] = _Habit(*key)
                # the corner's earlier compared laps (in the window) were clean of this kind: it was not tracked
                # (or forgotten after a window without it)
                h.laps.extend(_Lap(False) for _ in range(min(self._corner_laps[key[0]] - 1, HABIT_WINDOW - 1)))
        recorded: set[tuple[str, str]] = set()
        for key, h in self._habits.items():
            if h.corner not in compared:
                continue
            fired = points.get(key)
            if fired is None and h.blind(ref_lap_id):
                # measured against a lap with the same fault: its absence is no evidence, and this lap cannot show
                # it either when it becomes the reference
                if lap_id is not None:
                    h.blind_ids.append(lap_id)
                h.blind_run += 1
                continue
            h.blind_run = 0
            recorded.add(key)
            h.fired_now = fired is not None
            t = _num(times.get(h.corner))
            if fired is None:
                h.laps.append(_Lap(False, lap_id=lap_id, clean=h.corner not in dirty, time_s=t, model=model_version))
            else:
                v, impact = _num(fired.get("value")), _num(fired.get("impact_s"))
                h.laps.append(_Lap(True, v, impact, lap_id, time_s=t, model=model_version))
                h.obs = fired

        events: list[dict[str, Any]] = []
        ordered = sorted(self._habits.values(), key=lambda h: (h.corner, h.kind))
        # 1. fixed: a habit that stopped and is proven sorted (only a focus habit's is said; its slot frees). One that
        # stopped without the proof waits PROOF_WAIT laps for it, then is no habit: nothing claimed, the slot frees.
        for h in ordered:
            if (h.corner, h.kind) not in recorded or h.status not in (STATUS_FOCUS, STATUS_SEEN):
                continue
            if not h.stopped(self._corner_laps.get(h.corner, 0)):
                h.unproven = 0
            elif h.sorted_proof() is not None:
                if h.status == STATUS_FOCUS:
                    events.append(self.event(h, EVENT_FIXED, lap_number))
                self._set_status(h, STATUS_FIXED, lap_number)
            else:
                h.unproven += 1
                if h.unproven >= PROOF_WAIT:
                    self._set_status(h, None, lap_number)
        # habits on this lap (one definition: analysis.coaching.is_habit)
        for key, o in points.items():
            again = self._habits.get(key)
            if again is not None and again.status in (None, STATUS_FIXED) and is_habit(o) and again.backed():
                self._set_status(again, STATUS_SEEN, lap_number)
        focus = [h for h in ordered if h.status == STATUS_FOCUS]
        if 0 < slots < len(focus):  # fewer slots now (a lower intensity): keep the biggest, the rest are just seen
            focus.sort(key=lambda h: (-(h.mean_impact() or 0.0), h.corner, h.kind))
            for h in focus[slots:]:
                self._set_status(h, STATUS_SEEN, lap_number)
            focus = focus[:slots]
        # 2. improving
        for h in focus:
            if h.corner in compared and h.fired_now and not h.improving_said and h.improved():
                events.append(self.event(h, EVENT_IMPROVING, lap_number))
        # 3. announce: habits seen on this lap take the free slots, biggest mean impact first, one per corner
        free = slots - len(focus)
        busy = {h.corner for h in focus}
        candidates = [
            h
            for h in ordered
            if h.status == STATUS_SEEN
            and h.fired_now
            and h.corner in compared
            and h.backed()
            and is_habit(points[(h.corner, h.kind)])
        ]
        candidates.sort(key=lambda h: (-(h.mean_impact() or 0.0), h.corner, h.kind))
        for h in candidates:
            if free <= 0:
                break
            if h.corner in busy:
                continue
            ev = self.event(h, EVENT_ANNOUNCE, lap_number)
            if eligible is not None and not eligible(ev):
                continue
            events.append(ev)
            busy.add(h.corner)
            free -= 1
        # 4. still: no progress STILL_AFTER compared laps after the announcement (or the last "still")
        for h in focus:
            due = self._corner_laps.get(h.corner, 0) - h.still_at >= STILL_AFTER
            if h.corner in compared and h.fired_now and due and not h.improved():
                events.append(self.event(h, EVENT_STILL, lap_number))
        # forget what no longer fired anywhere in its window (focus habits stay until they are fixed), and what
        # could not be measured for a whole window (unknown stays unknown: no "sorted", and the slot frees)
        for key, h in list(self._habits.items()):
            gone = h.status != STATUS_FOCUS and h.laps and not any(lap.fired for lap in h.laps)
            if gone or h.blind_run >= HABIT_WINDOW:
                del self._habits[key]
        return events

    def commit(self, picked: Sequence[Mapping[str, Any]]) -> None:
        """The radio picked these points (``coach.selection``): record the tracker events among them. An announced
        habit becomes the focus; ``improving`` is said once; ``still`` restarts its count."""
        for p in picked:
            ev = p.get("habit_event")
            h = self._habits.get((str(p.get("corner")), str(p.get("kind"))))
            if h is None or ev is None:
                continue
            if ev == EVENT_ANNOUNCE and h.status == STATUS_SEEN:
                self._set_status(h, STATUS_FOCUS, _lap_of(p))
                h.announced_value = _num(p.get("value"))
                h.announced_impact = _num(p.get("impact_s"))
                h.announced_confidence = _num(p.get("confidence"))
                h.still_at = self._corner_laps.get(h.corner, 0)
                h.improving_said = False
            elif ev == EVENT_IMPROVING and h.status == STATUS_FOCUS:
                h.improving_said = True
            elif ev == EVENT_STILL and h.status == STATUS_FOCUS:
                h.still_at = self._corner_laps.get(h.corner, 0)

    def _set_status(self, h: _Habit, status: str | None, lap_number: int | None) -> None:
        h.status = status
        h.since_lap = lap_number
        h.status_at = self._corner_laps.get(h.corner, 0)
        h.unproven = 0
        if status != STATUS_FOCUS:
            h.announced_value = h.announced_impact = h.announced_confidence = None
            h.improving_said = False

    # ------------------------------------------------------------------ views (coach block)
    def in_focus(self, corner: object, kind: object) -> bool:
        h = self._habits.get((str(corner), str(kind)))
        return h is not None and h.status == STATUS_FOCUS

    def repeated(self, corner: object, kind: object) -> bool:
        """It fired on the corner's latest compared lap and on the one before: a pattern in the making, no longer a
        one-off (the radio does not say the same sentence two laps running; it announces the habit when it is one)."""
        h = self._habits.get((str(corner), str(kind)))
        return h is not None and len(h.laps) >= 2 and h.laps[-1].fired and h.laps[-2].fired

    def habit_info(self, corner: object, kind: object, *, fixed: bool = False) -> dict[str, Any] | None:
        """``{"status", "laps_seen", "laps"}`` of a habit (a coach block point's ``habit``): ``seen`` or ``focus``,
        and ``fixed`` too when ``fixed`` (a "sorted" line); None for anything that is not a habit now."""
        h = self._habits.get((str(corner), str(kind)))
        if h is None or h.status is None or (h.status == STATUS_FIXED and not fixed):
            return None
        seen, laps = h.counts()
        return {"status": h.status, "laps_seen": seen, "laps": laps}

    def habits(self) -> list[dict[str, Any]]:
        """Every habit (``focus``, then ``seen``, then ``fixed``; bigger mean impact first): the block's ``habits``."""
        hs = [h for h in self._habits.values() if h.status is not None]
        hs.sort(key=lambda h: (_STATUS_RANK[h.status or ""], -(h.mean_impact() or 0.0), h.corner, h.kind))
        return [self._entry(h) for h in hs]

    def focus(self) -> list[dict[str, Any]]:
        """The focus habits with their corner reminder (``reminder``; None for kinds without one): ``focus``."""
        return [{**e, "reminder": reminder(e)} for e in self.habits() if e["status"] == STATUS_FOCUS]

    def _entry(self, h: _Habit) -> dict[str, Any]:
        o = h.obs or {}
        seen, laps = h.counts()
        return {
            "corner": h.corner,
            "corner_label": o.get("corner_label"),
            "corner_voice": o.get("corner_voice"),
            "kind": h.kind,
            "status": h.status,
            "laps_seen": seen,
            "laps": laps,
            "value": h.typical_value(),  # median over the laps it fired in the window
            "unit": o.get("unit"),
            "impact_s": h.mean_impact(),  # mean over the laps it fired in the window
            "since_lap": h.since_lap,
            "short": o.get("short"),
        }

    # ------------------------------------------------------------------ events
    def event(self, h: _Habit, event: str, lap_number: int | None) -> dict[str, Any]:
        """An observation-shaped dict for a radio event (``habit_event``): the habit's names and kind, this lap's
        number, its counts (``consistency`` "3 of the last 4 laps"), the radio's numbers and screen wordings.

        ``announce`` / ``still`` carry this lap's observation (value, impact, confidence, evidence); ``improving``
        this lap's value and ``was_value`` (its size when announced); ``fixed`` the typical value it had and
        ``clean_laps`` of ``clean_of``. Progress events keep the announcement's impact and confidence."""
        o = h.obs or {}
        seen, laps = h.counts()
        label = str(o.get("corner_label") or h.corner)
        long_name = _long_name(o, label)
        progress = event in (EVENT_FIXED, EVENT_IMPROVING)
        now = event != EVENT_FIXED and h.fired_now
        value = _num(o.get("value")) if now else h.typical_value()
        impact = h.announced_impact if progress and h.announced_impact is not None else _num(o.get("impact_s"))
        conf = h.announced_confidence if progress and h.announced_confidence is not None else _num(o.get("confidence"))
        if event == EVENT_FIXED:
            impact = impact if impact is not None else h.mean_impact()
        d: dict[str, Any] = {
            "id": f"L{lap_number}:{h.corner}:{h.kind}:{event}",
            "kind": h.kind,
            "corner": h.corner,
            "corner_label": o.get("corner_label"),
            "corner_voice": o.get("corner_voice"),
            "lap_number": lap_number,
            "ref_lap_number": o.get("ref_lap_number"),
            "metric": o.get("metric"),
            "value": value,
            "unit": o.get("unit"),
            "impact_s": impact,
            "confidence": conf,
            "priority": round(max(0.0, impact or 0.0) * (conf or 0.0), 4),
            "positive": False,
            "consistency": f"{seen} of the last {laps} laps",
            "consistency_ratio": round(seen / laps, 2) if laps else None,
            "ref_name": o.get("ref_name"),
            "evidence": dict(o.get("evidence") or {}) if now else {},
            "habit_event": event,
            "habit": {"status": h.status, "laps_seen": seen, "laps": laps},
            "was_value": None,
            "clean_laps": None,
            "clean_of": None,
        }
        if event == EVENT_FIXED:
            last = list(h.laps)[-FIXED_OF:]
            clean = h.sorted_proof() or sum(1 for lap in last if h.proves(lap))
            d.update(clean_laps=clean, clean_of=len(last))
            d["text"] = f"{label}: sorted - clean on {clean} of the last {len(last)} laps."
            d["text_simple"] = f"{long_name}: sorted - clean on your last laps."
            d["short"] = short_text(label, "sorted")
        elif event == EVENT_IMPROVING:
            d["was_value"] = h.announced_value
            amount = progress_amount(h.kind, value) or "smaller"
            was = f", was {abs(h.announced_value):.0f}" if h.announced_value is not None else ""
            d["text"] = f"{label}: better - {amount} now{was}."
            d["text_simple"] = f"{long_name}: better - {amount} now."
            d["short"] = short_text(label, f"better, {amount}")
        elif event == EVENT_ANNOUNCE:
            d["text"] = f"{o.get('text') or label} Seen on {seen} of the last {laps} laps."
            d["text_simple"] = f"{o.get('text_simple') or label} Most laps."
            d["short"] = o.get("short")
        else:  # still
            d["text"] = f"{o.get('text') or label} Still on {seen} of the last {laps} laps."
            d["text_simple"] = o.get("text_simple")
            d["short"] = o.get("short")
        return d


def _long_name(o: Mapping[str, Any], label: str) -> str:
    """The corner's long name as the observation's simple wording starts with it ("Turn 10 (Remus)"), else ``label``."""
    simple = o.get("text_simple")
    if isinstance(simple, str) and ": " in simple:
        return simple.split(": ", 1)[0]
    return label


def _lap_of(p: Mapping[str, Any]) -> int | None:
    n = p.get("lap_number")
    return n if isinstance(n, int) and not isinstance(n, bool) else None
