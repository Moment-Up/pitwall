"""Deterministic radio message builders: lap summaries, coaching points and control acks.

No LLM is involved: every sentence is a template filled with numbers the analysis already validated, so these
messages work with the LLM down and cannot invent facts. The scheduler decides when (and whether) each one is
said; this module decides what is worth saying:

* **One selection, two channels** - which observations are said comes from ``coach.selection`` (D6), the same
  selection the Drive screen's coach card shows. ``core.live`` makes it once per lap and sends it with the
  ``lap`` notification (``coach``); given that block, ``lap_messages`` speaks exactly its ``picked`` points.
  Without it (older callers) the same shared function picks from the observations given.
* **Confidence** - only observations with ``confidence >= MIN_COACHING_CONFIDENCE`` reach the radio (the
  dashboard still shows the rest).
* **Habits, not every corner** - the corrective points are the habit tracker's events (``coach.habits``: a new
  habit announced with how often it happened, "better" when it halves, "still" after a few laps without progress,
  "sorted" when it stops) and the lap's big one-offs (``analysis.coaching.is_big_one_off``), never a small one-off
  or a habit already in focus (its corner reminder says that one). Normal intensity speaks the lap summary and one
  corrective point, and detailed up to two and the best positive one. Quiet intensity is minimal radio (alerts
  and answers only, as its acknowledgement says), so it builds no lap messages at all.
* **Only validated facts** - an observation's ``impact_s`` is the time lost (or gained) through the *whole
  corner*, shared by every observation there. So the radio states it as the corner's loss ("T4, losing 0.08 s:
  minimum speed 8 km/h down."), and only on the first point for a corner, never as the cost of one cause.
* **Radio brevity** - coaching is rebuilt from the observation's structured fields instead of reading the long
  dashboard sentence. Wording stays descriptive (compared with the reference); it never tells the driver to
  brake later. Against another driver's lap (coachref) the point names them (``ref_name``: "braking 12 m earlier
  than Sam") and the lap summary says the reference's radio label ("plus 0.792 to Sam's best").
* **Practice drills** (coachref) - while a drill runs the lap's coach block says ``drill_only``: no lap summary and
  no other point, only the drill attempt (a ``kind: "drill"`` point, spoken verbatim from its text).
* **Still actionable** - the final lap (the session ended on it) gets its summary but no coaching point: no next lap
  can use it. Lap messages expire ``LAP_MESSAGE_TTL_S`` after creation, a simple bound for "before
  the driver is well into the next lap". They carry ``lap_number`` and ``meta["lap_id"]``, so a later lap
  supersedes them and the scheduler's per-lap budget survives lap numbers restarting each session. Fuel calls are
  race strategy's (``strategy.radio``) for F1: it is the only source of F1 fuel alerts; car health
  (``carhealth.radio``) calls tank-level fuel for Forza.

* **The lap just finished, never "Lap N"** - a lap summary can only be said after the line, when the game's HUD
  (and the Drive header) already shows the next lap, so a bare "Lap 66, 1:13.897" sounds like the lap in progress.
  The summary names the lap by what it was: "That lap", "Opening lap" (race lap 1 from the grid), "Out-lap",
  "In-lap", "Pit lap" (in and out of the pit lane within one lap) or "Final lap" (the game says the driver's
  session ended on it). The game's lap number stays in ``lap_number`` and ``meta["lap_number"]``, as everywhere
  else (Review, the engineer, Drive's "L66" tags for older laps).

``lap`` and ``observations`` have the shapes ``LiveState.on_lap_result`` publishes (``lap_processor._lap_summary``
and ``Observation.to_dict``). ``speech`` is ``voice.speech.to_speech`` of the display text (lap times, corner
names, units), except the lap summary, whose reference delta is spoken in the radio convention ("plus zero point
zero eight") while the display keeps all three decimals.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from pitwall.analysis.coaching import HABIT_RATIO as HABIT_RATIO  # the one definition of a habit (re-exported)
from pitwall.coach.habits import EVENT_ANNOUNCE, EVENT_FIXED, EVENT_IMPROVING, EVENT_STILL, progress_amount
from pitwall.coach.selection import pick_points, record_coached
from pitwall.voice.scheduler import LAP_ID_KEY, Intensity, parse_intensity
from pitwall.voice.speech import to_speech
from pitwall.voice.types import MessageKind, Priority, RadioMessage

if TYPE_CHECKING:
    from pitwall.drivers import CoachingLimits

LAP_MESSAGE_TTL_S = 45.0
CONTROL_TTL_S = 10.0  # an acknowledgement that arrives late is just confusing
MIN_COACHING_CONFIDENCE = 0.6
CORRECTIVE_PER_LAP: dict[Intensity, int] = {"quiet": 0, "normal": 1, "detailed": 2}
POSITIVE_PER_LAP: dict[Intensity, int] = {"quiet": 0, "normal": 0, "detailed": 1}

_ids = itertools.count(1)


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def fmt_lap_time(ms: int) -> str:
    """``65706`` -> ``1:05.706``; sub-minute laps -> ``59.123``."""
    m, rem = divmod(ms, 60_000)
    return f"{m}:{rem / 1000:06.3f}" if m else f"{rem / 1000:.3f}"


def _message(
    msg_id: str,
    kind: MessageKind,
    priority: Priority,
    text: str,
    now_mono: float,
    ttl_s: float | None,
    *,
    lap_number: int | None = None,
    corner: str | None = None,
    bypass_quiet: bool = False,
    needs_speak_window: bool = True,
    meta: dict[str, object] | None = None,
    speech_source: str | None = None,
) -> RadioMessage:
    return RadioMessage(
        id=msg_id,
        kind=kind,
        priority=priority,
        text=text,
        speech=to_speech(text if speech_source is None else speech_source),
        created_mono=now_mono,
        expires_mono=None if ttl_s is None else now_mono + ttl_s,
        lap_number=lap_number,
        corner=corner,
        bypass_quiet=bypass_quiet,
        needs_speak_window=needs_speak_window,
        meta=meta or {},
    )


# ---------------------------------------------------------------------------------------------- lap summary
LAP_THAT = "That lap"
LAP_OPENING = "Opening lap"  # race lap 1 from the grid (standing start)
LAP_OUT = "Out-lap"
LAP_IN = "In-lap"
LAP_PIT = "Pit lap"  # into and out of the pit lane within one lap (a drive-through)
LAP_FINAL = "Final lap"  # the game says the driver's session ended with this lap (chequered flag)


def lap_label(lap: Mapping[str, Any]) -> str:
    """How the radio names the lap just finished: never by its bare number (see the module docstring).

    ``Final lap`` first (it is the one the driver is waiting for), then the pit laps, then race lap 1 from the grid.
    """
    if lap.get("final") is True:
        return LAP_FINAL
    flags = set(lap.get("flags") or ())
    if "pit_in" in flags and "pit_out" in flags:
        return LAP_PIT
    if "pit_in" in flags:
        return LAP_IN
    if "pit_out" in flags:
        return LAP_OUT
    if "standing_start" in flags or "race_start" in flags:
        return LAP_OPENING
    return LAP_THAT


def lap_summary_text(
    lap: Mapping[str, Any], best_clean_ms: int | None, reference: Mapping[str, Any] | None
) -> str | None:
    """'That lap, 1:05.706, plus 0.080 to your reference.' or None when the lap has no time.

    ``best_clean_ms`` is the best clean lap known so far (it may include this lap): a clean lap at or under it is
    called a personal best, or a session best when it is still slower than the reference (a faster lap from
    another session).
    """
    texts = _lap_summary(lap, best_clean_ms, reference)
    return None if texts is None else texts[0]


def _lap_summary(
    lap: Mapping[str, Any], best_clean_ms: int | None, reference: Mapping[str, Any] | None
) -> tuple[str, str] | None:
    """(display text, speech source): the speech source writes the delta as ``+0.080s`` for ``to_speech``."""
    ms = lap.get("lap_time_ms")
    if not isinstance(ms, int) or isinstance(ms, bool) or ms <= 0:
        return None
    head = [lap_label(lap), fmt_lap_time(ms)]
    delta = _reference_delta_ms(lap, ms, reference)
    new_best = lap.get("clean") and best_clean_ms is not None and ms <= best_clean_ms
    if new_best:
        head.append("personal best" if delta is None or delta <= 0 else "session best")
    shown, spoken = list(head), list(head)
    to_ref = (reference or {}).get("label_to") or "your reference"  # --- coachref --- e.g. "Sam's best"
    if new_best and delta is not None and delta < 0 and (reference or {}).get("own") is not False:
        # a new personal best against the driver's own reference: "personal best, 0.908 faster than before", never
        # "personal best, minus 0.908 to your best"
        gain = f"{abs(delta) / 1000:.3f} faster than before"
        shown.append(gain)
        spoken.append(gain)
    elif delta == 0:
        shown.append(f"level with {to_ref}")
        spoken.append(f"level with {to_ref}")
    elif delta is not None:
        shown.append(f"{'plus' if delta > 0 else 'minus'} {abs(delta) / 1000:.3f} to {to_ref}")
        spoken.append(f"{delta / 1000:+.3f}s to {to_ref}")
    flags = set(lap.get("flags") or ())
    notes = []
    if lap.get("valid") is False or "invalid" in flags:
        notes.append("That lap was invalidated.")
    if "flashback" in flags:
        notes.append("Flashback used.")
    return " ".join([", ".join(shown) + ".", *notes]), " ".join([", ".join(spoken) + ".", *notes])


def _reference_delta_ms(lap: Mapping[str, Any], ms: int, reference: Mapping[str, Any] | None) -> int | None:
    if not reference:
        return None
    ref_ms = reference.get("lap_time_ms")
    if not isinstance(ref_ms, int) or isinstance(ref_ms, bool) or ref_ms <= 0:
        return None
    if reference.get("lap_id") is not None and reference.get("lap_id") == lap.get("lap_id"):
        return None  # this lap *is* the reference
    return ms - ref_ms


# ---------------------------------------------------------------------------------------------- coaching
def _core(
    kind: object, v: float | None, exit_kph: float | None, ref_name: str | None, brief: bool = False
) -> str | None:
    """The point itself in a few words ("minimum speed 8 km/h down"), or None for an unknown kind or value. ``brief``
    leaves out "than your reference" (a habit line is long enough; another driver is always named)."""
    if v is None:
        return None
    ref = f" than {ref_name}" if ref_name else ("" if brief else " than your reference")
    if kind == "brake_early":
        return f"braking {abs(v):.0f} m earlier{ref}"
    if kind == "brake_late_overdrive":
        slower = f" but exiting {abs(exit_kph):.0f} km/h slower" if exit_kph is not None else ", no faster out"
        return f"braking {abs(v):.0f} m later{slower}"
    if kind == "low_min_speed":
        if ref_name:
            return f"{ref_name} was {abs(v):.0f} km/h faster in the middle of the corner"
        return f"minimum speed {abs(v):.0f} km/h down"
    if kind == "overspeed_apex":
        hurt = f", exit {abs(exit_kph):.0f} km/h down" if exit_kph is not None else ", hurting the exit"
        return f"{abs(v):.0f} km/h too much into the apex{hurt}"
    if kind == "late_throttle":
        return f"full throttle {abs(v):.0f} m later{ref}"
    if kind == "coasting":
        return f"{abs(v):.0f} m more coasting{ref}"
    if kind == "exit_gain":
        return f"good exit, {abs(v):.0f} km/h up"
    return None


_MOST_LAPS = "Most laps."  # a habit announced without statistics (simple wording, or a profile without them)


def _count(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _habit_counts(obs: Mapping[str, Any]) -> tuple[int, int] | None:
    """(laps seen, laps) of a tracker event (its ``habit``), or None."""
    h = obs.get("habit")
    if not isinstance(h, Mapping):
        return None
    seen, laps = _count(h.get("laps_seen")), _count(h.get("laps"))
    return (seen, laps) if seen is not None and laps else None


def _simple_body(obs: Mapping[str, Any]) -> str | None:
    """The observation's plain-words sentence without its corner name ("you were 12 km/h slower ...")."""
    t = obs.get("text_simple")
    if not isinstance(t, str) or ": " not in t:
        return None
    body = t.split(": ", 1)[1].strip()
    return body or None


def coaching_text(
    obs: Mapping[str, Any], with_impact: bool = True, *, simple: bool = False, counts: bool = True
) -> str:
    """Radio-length version of an ``Observation.to_dict()`` or a habit tracker event (``habit_event``, coach block
    shape); falls back to its own text for unknown kinds.

    ``with_impact`` states the corner's time loss/gain; pass False for a second point on an already costed corner.
    ``simple``: plain words for simple-wording profiles (no habit statistics). ``counts``: an announcement says how
    often the habit happened ("3 of the last 4 laps"; else "Most laps."), as profiles that mention consistency do.

    Tracker events (``coach.habits``; at most about 20 spoken words, so a habit line leaves out "than your
    reference")::

        announce   "Turn 6, losing 0.31 s: minimum speed 12 km/h down. 3 of the last 4 laps."
                   simple: "Turn 6: <the plain-words sentence> Most laps."
        improving  "Turn 6 better: 6 km/h down now, was 14."
        still      "Turn 6 still: minimum speed 12 km/h down, 5 of the last 5 laps."
        fixed      "Turn 6 sorted: clean on 2 of the last 3 laps."

    An ordinary point (a big one-off) is today's sentence, with no habit suffix.
    """
    corner = str(obs.get("corner_voice") or obs.get("corner") or "That corner")
    kind = obs.get("kind")
    event = obs.get("habit_event")
    v = _num(obs.get("value"))
    impact = _num(obs.get("impact_s"))
    evidence = obs.get("evidence")
    ev: Mapping[str, Any] = evidence if isinstance(evidence, Mapping) else {}
    exit_kph = _num(ev.get("exit_speed_delta_kph"))
    raw_name = obs.get("ref_name")  # --- coachref --- another driver's lap: name them
    ref_name = raw_name if isinstance(raw_name, str) and raw_name else None
    habit = _habit_counts(obs)

    if event == EVENT_FIXED:
        clean, of = _count(obs.get("clean_laps")), _count(obs.get("clean_of"))
        if simple or clean is None or not of:
            return f"{corner} sorted."
        return f"{corner} sorted: clean on {clean} of the last {of} laps."
    if event == EVENT_IMPROVING:
        now = progress_amount(str(kind), v)
        if now is not None:
            was = _num(obs.get("was_value"))
            tail = "" if simple or was is None else f", was {abs(was):.0f}"
            return f"{corner} better: {now} now{tail}."

    core = _core(kind, v, exit_kph, ref_name, brief=event in (EVENT_ANNOUNCE, EVENT_STILL))
    if core is None:
        return str(obs.get("text") or "").strip()
    if event == EVENT_STILL:
        tail = f", {habit[0]} of the last {habit[1]} laps" if habit and counts and not simple else ""
        return f"{corner} still: {core}{tail}."
    if event == EVENT_ANNOUNCE and simple:
        body = _simple_body(obs) or f"{core}."
        return f"{corner}: {body}" if body.endswith(_MOST_LAPS) else f"{corner}: {body} {_MOST_LAPS}"
    head = corner
    if with_impact and impact is not None and round(abs(impact), 2) > 0:
        head += f", {'gaining' if impact < 0 else 'losing'} {abs(impact):.2f} s"
    line = f"{head}: {core}."
    if event == EVENT_ANNOUNCE:
        line += f" {habit[0]} of the last {habit[1]} laps." if habit and counts else f" {_MOST_LAPS}"
    return line


def _confidence(obs: Mapping[str, Any]) -> float:
    return _num(obs.get("confidence")) or 0.0


def select_observations(
    observations: Sequence[Mapping[str, Any]], intensity: Intensity, lap_number: int | None = None
) -> list[Mapping[str, Any]]:
    """Corrective points first (by analysis priority), then the positive one, filtered by confidence: the shared
    selection (``coach.selection.pick_points``) with no seated driver at ``intensity``. Incidents are never
    points (the driver knows they spun; the radio stays quiet about it)."""
    return pick_points(observations, None, lap_number, intensity=intensity)


def _block_for(coach: Mapping[str, Any] | None, lap: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The shared D6 block when it belongs to ``lap`` (same lap id, else same lap number), else None."""
    if not coach:
        return None
    lap_id = lap.get("lap_id")
    if lap_id is not None or coach.get("lap_id") is not None:
        return coach if coach.get("lap_id") == lap_id else None
    return coach if coach.get("lap_number") == lap.get("lap_number") else None


# ---------------------------------------------------------------------------------------------- public builders
def lap_messages(
    lap: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    best_clean_ms: int | None,
    reference: Mapping[str, Any] | None,
    intensity: str,
    now_mono: float,
    *,
    limits: CoachingLimits | None = None,
    last_coached: dict[str, int] | None = None,
    coach: Mapping[str, Any] | None = None,
) -> list[RadioMessage]:
    """Lap summary followed by the coaching points worth saying for this lap, in speaking order.

    ``coach`` is the lap's shared D6 block (``coach.selection.coach_block``, sent by ``core.live`` with the ``lap``
    notification): its ``picked`` points are spoken as they are, so the radio says what the coach card shows, and
    nothing when it says ``radio_quiet``. Without it the points are picked here by the same shared function:
    ``limits`` is the seated driver's profile (``drivers.CoachingLimits``): a beginner hears fewer, simpler,
    higher-confidence points and the same corner is not repeated on consecutive laps (``last_coached`` maps
    corner -> lap last coached; the caller keeps it per session). ``None`` keeps the intensity-only selection.
    """
    level = parse_intensity(intensity)
    if level == "quiet":
        return []
    n = lap.get("lap_number")
    lap_number = n if isinstance(n, int) and not isinstance(n, bool) else None
    lap_id = lap.get("lap_id")
    key = f"lap{lap_id}" if lap_id is not None else f"n{lap_number}-{next(_ids)}"
    out: list[RadioMessage] = []

    summary = _lap_summary(lap, best_clean_ms, reference)
    drilling = _block_for(coach, lap)  # --- coachref --- a practice drill: only its point, no lap summary
    if drilling is not None and drilling.get("drill_only"):
        summary = None
    if summary is not None:
        ms = lap.get("lap_time_ms")
        delta = _reference_delta_ms(lap, ms, reference) if isinstance(ms, int) else None
        out.append(
            _message(
                f"{key}-summary",
                MessageKind.LAP_SUMMARY,
                Priority.NORMAL,
                summary[0],
                now_mono,
                LAP_MESSAGE_TTL_S,
                lap_number=lap_number,
                meta={LAP_ID_KEY: lap_id, "lap_number": lap_number, "lap_time_ms": ms, "delta_ms": delta},
                speech_source=summary[1],
            )
        )

    costed: set[str] = set()  # corners whose loss was already stated (it is shared by all their observations)
    shared = _block_for(coach, lap)
    if lap.get("final") is True and drilling is None:
        chosen = []  # the session ended on this lap (the chequered flag): no next lap can use a coaching point
    elif shared is not None:
        chosen = [] if shared.get("radio_quiet") else list(shared.get("picked") or [])
    else:
        chosen = pick_points(observations, limits, lap_number, last_coached, intensity=level)
    if last_coached is not None:
        record_coached(chosen, lap_number, last_coached)
    counts = limits is None or limits.mention_consistency
    simple = limits is not None and limits.simple_wording
    for obs in chosen:
        raw_corner = obs.get("corner")
        corner = str(raw_corner) if raw_corner else None
        with_impact = not simple and (corner is None or corner not in costed)
        text = coaching_text(obs, with_impact, simple=simple, counts=counts)
        if not text:
            continue
        if corner is not None:
            costed.add(corner)
        positive = bool(obs.get("positive"))
        out.append(
            _message(
                f"{key}-{obs.get('id') or next(_ids)}",
                MessageKind.COACHING,
                Priority.LOW if positive else Priority.NORMAL,
                text,
                now_mono,
                LAP_MESSAGE_TTL_S,
                lap_number=lap_number,
                corner=corner,
                meta={
                    LAP_ID_KEY: lap_id,
                    "observation_id": obs.get("id"),
                    "observation_kind": obs.get("kind"),
                    "habit_event": obs.get("habit_event"),  # habits: announce / improving / still / fixed
                    "impact_s": obs.get("impact_s"),
                    "confidence": obs.get("confidence"),
                    "positive": positive,
                    "drill_id": _drill_id(obs),  # coachref: a drill attempt's point (validation, acceptance R9)
                },
            )
        )
    return out


def _drill_id(obs: Mapping[str, Any]) -> int | None:
    """The drill a coaching point belongs to (``coach.drills.drill_point``'s ``drill.id``), else None."""
    d = obs.get("drill")
    i = d.get("id") if isinstance(d, Mapping) else None
    return i if isinstance(i, int) and not isinstance(i, bool) else None


def _control(text: str, now_mono: float, meta: dict[str, object]) -> RadioMessage:
    # the driver just asked for this: say it straight away, even in quiet mode
    return _message(
        f"ctl-{next(_ids)}",
        MessageKind.CONTROL,
        Priority.HIGH,
        text,
        now_mono,
        CONTROL_TTL_S,
        bypass_quiet=True,
        needs_speak_window=False,
        meta=meta,
    )


def quiet_ack(until_lap: int | None, indefinite: bool, now_mono: float) -> RadioMessage:
    """Acknowledge "stop talking" (``until_lap`` uses ``RadioScheduler.set_quiet`` semantics)."""
    if indefinite or until_lap is None:
        text = "Copy, going quiet until you call me. Urgent calls only."
    else:
        text = f"Copy, quiet until lap {until_lap}. Urgent calls only."
    return _control(text, now_mono, {"action": "quiet", "until_lap": until_lap, "indefinite": indefinite})


def resume_ack(now_mono: float) -> RadioMessage:
    return _control("Copy, radio back on.", now_mono, {"action": "resume"})


_INTENSITY_ACK: dict[Intensity, str] = {
    "quiet": "Copy, minimal radio: alerts and answers only.",
    "normal": "Copy, normal coaching: lap summary and one point a lap.",
    "detailed": "Copy, detailed coaching.",
}


def intensity_ack(intensity: str, now_mono: float) -> RadioMessage:
    level = parse_intensity(intensity)
    return _control(_INTENSITY_ACK[level], now_mono, {"action": "intensity", "intensity": level})
