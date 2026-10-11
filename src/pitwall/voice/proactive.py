"""Deterministic radio message builders: lap summaries, coaching points, fuel alerts and control acks.

No LLM is involved: every sentence is a template filled with numbers the analysis already validated, so these
messages work with the LLM down and cannot invent facts. The scheduler decides when (and whether) each one is
said; this module decides what is worth saying:

* **One selection, two channels** - which observations are said comes from ``coach.selection`` (D6), the same
  selection the Drive screen's coach card shows. ``core.live`` makes it once per lap and sends it with the
  ``lap`` notification (``coach``); given that block, ``lap_messages`` speaks exactly its ``picked`` points.
  Without it (older callers) the same shared function picks from the observations given.
* **Confidence** - only observations with ``confidence >= MIN_COACHING_CONFIDENCE`` reach the radio (the
  dashboard still shows the rest).
* **Performance impact** - observations are ranked by the analysis ``priority`` (time impact x confidence,
  boosted for consistent habits). Normal intensity speaks the lap summary and the top corrective point, and
  detailed adds a second corrective point and the best positive one. Quiet intensity is minimal radio (alerts
  and answers only, as its acknowledgement says), so it builds no lap messages at all.
* **Only validated facts** - an observation's ``impact_s`` is the time lost (or gained) through the *whole
  corner*, shared by every observation there. So the radio states it as the corner's loss ("T4, losing 0.08 s:
  minimum speed 8 km/h down."), and only on the first point for a corner, never as the cost of one cause.
* **Radio brevity** - coaching is rebuilt from the observation's structured fields instead of reading the long
  dashboard sentence. Wording stays descriptive (compared with the reference); it never tells the driver to
  brake later.
* **Still actionable** - lap messages expire ``LAP_MESSAGE_TTL_S`` after creation, a simple bound for "before
  the driver is well into the next lap". They carry ``lap_number`` and ``meta["lap_id"]``, so a later lap
  supersedes them and the scheduler's per-lap budget survives lap numbers restarting each session. Fuel alerts
  share ``meta["topic"] = "fuel"``, so the newest estimate replaces an unsaid older one.

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

from pitwall.coach.selection import pick_points, record_coached
from pitwall.voice.scheduler import LAP_ID_KEY, TOPIC_KEY, Intensity, parse_intensity
from pitwall.voice.speech import to_speech
from pitwall.voice.types import MessageKind, Priority, RadioMessage

if TYPE_CHECKING:
    from pitwall.drivers import CoachingLimits

LAP_MESSAGE_TTL_S = 45.0
CONTROL_TTL_S = 10.0  # an acknowledgement that arrives late is just confusing
FUEL_ALERT_TTL_S = 120.0
MIN_COACHING_CONFIDENCE = 0.6
FUEL_TIGHT_LAPS = 0.3  # margin below this (but not short) is worth a heads-up
FUEL_LIMIT_LAPS = 0.05  # |margin| below this reads as "right on the limit"
CORRECTIVE_PER_LAP: dict[Intensity, int] = {"quiet": 0, "normal": 1, "detailed": 2}
POSITIVE_PER_LAP: dict[Intensity, int] = {"quiet": 0, "normal": 0, "detailed": 1}
HABIT_RATIO = 0.6  # detailed mode mentions consistency when the deviation shows up this often

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
def lap_summary_text(
    lap: Mapping[str, Any], best_clean_ms: int | None, reference: Mapping[str, Any] | None
) -> str | None:
    """'Lap 4, 1:05.706, plus 0.080 to your reference.' or None when the lap has no time.

    ``best_clean_ms`` is the best clean lap known so far (it may include this lap): a clean lap at or under it is
    called a personal best.
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
    n = lap.get("lap_number")
    head = [f"Lap {n}" if isinstance(n, int) else "Lap complete", fmt_lap_time(ms)]
    if lap.get("clean") and best_clean_ms is not None and ms <= best_clean_ms:
        head.append("personal best")
    shown, spoken = list(head), list(head)
    delta = _reference_delta_ms(lap, ms, reference)
    if delta == 0:
        shown.append("level with your reference")
        spoken.append("level with your reference")
    elif delta is not None:
        shown.append(f"{'plus' if delta > 0 else 'minus'} {abs(delta) / 1000:.3f} to your reference")
        spoken.append(f"{delta / 1000:+.3f}s to your reference")
    flags = set(lap.get("flags") or ())
    notes = []
    if lap.get("valid") is False or "invalid" in flags:
        notes.append("That lap was invalidated.")
    if "flashback" in flags:
        notes.append("Flashback used.")
    if "pit_in" in flags:
        notes.append("In-lap.")
    elif "pit_out" in flags:
        notes.append("Out-lap.")
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
def coaching_text(obs: Mapping[str, Any], detailed: bool = False, with_impact: bool = True) -> str:
    """Radio-length version of an ``Observation.to_dict()``; falls back to its own text for unknown kinds.

    ``with_impact`` states the corner's time loss/gain; pass False for a second point on an already costed corner.
    """
    corner = str(obs.get("corner_voice") or obs.get("corner") or "That corner")
    kind = obs.get("kind")
    v = _num(obs.get("value"))
    impact = _num(obs.get("impact_s"))
    evidence = obs.get("evidence")
    ev: Mapping[str, Any] = evidence if isinstance(evidence, Mapping) else {}
    exit_kph = _num(ev.get("exit_speed_delta_kph"))
    positive = bool(obs.get("positive"))

    core: str | None = None
    if v is not None:
        if kind == "brake_early":
            core = f"braking {abs(v):.0f} m earlier than your reference"
        elif kind == "brake_late_overdrive":
            slower = f" but exiting {abs(exit_kph):.0f} km/h slower" if exit_kph is not None else ", no faster out"
            core = f"braking {abs(v):.0f} m later{slower}"
        elif kind == "low_min_speed":
            core = f"minimum speed {abs(v):.0f} km/h down"
        elif kind == "overspeed_apex":
            hurt = f", exit {abs(exit_kph):.0f} km/h down" if exit_kph is not None else ", hurting the exit"
            core = f"{abs(v):.0f} km/h too much into the apex{hurt}"
        elif kind == "late_throttle":
            core = f"full throttle {abs(v):.0f} m later than your reference"
        elif kind == "coasting":
            core = f"{abs(v):.0f} m more coasting than your reference"
        elif kind == "exit_gain":
            core = f"good exit, {abs(v):.0f} km/h up"
    if core is None:
        return str(obs.get("text") or "").strip()

    head = corner
    if with_impact and impact is not None and round(abs(impact), 2) > 0:
        head += f", {'gaining' if impact < 0 else 'losing'} {abs(impact):.2f} s"
    line = f"{head}: {core}."
    ratio = _num(obs.get("consistency_ratio"))
    habit = obs.get("consistency")
    if detailed and not positive and habit and ratio is not None and ratio >= HABIT_RATIO:
        line += f" Same on {habit}."
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
                meta={LAP_ID_KEY: lap_id, "lap_time_ms": ms, "delta_ms": delta},
                speech_source=summary[1],
            )
        )

    costed: set[str] = set()  # corners whose loss was already stated (it is shared by all their observations)
    shared = _block_for(coach, lap)
    if shared is not None:
        chosen = [] if shared.get("radio_quiet") else list(shared.get("picked") or [])
    else:
        chosen = pick_points(observations, limits, lap_number, last_coached, intensity=level)
    if last_coached is not None:
        record_coached(chosen, lap_number, last_coached)
    detailed = level == "detailed" and (limits is None or limits.mention_consistency)
    simple = limits is not None and limits.simple_wording
    for obs in chosen:
        raw_corner = obs.get("corner")
        corner = str(raw_corner) if raw_corner else None
        with_impact = not simple and (corner is None or corner not in costed)
        text = coaching_text(obs, detailed=detailed and not simple, with_impact=with_impact)
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
                    "impact_s": obs.get("impact_s"),
                    "confidence": obs.get("confidence"),
                    "positive": positive,
                },
            )
        )
    return out


def fuel_alert(fuel_margin_laps: float | None, now_mono: float, lap_number: int | None = None) -> RadioMessage | None:
    """Alert when the fuel margin to the finish is short or tight (``strategy.FuelEstimate.margin_laps``).

    Short on fuel bypasses quiet mode (the driver needs it regardless) but still waits for a speak window: it is
    important, not a split-second safety call. The id names the severity, so a critical alert is never mistaken
    for a duplicate of the same lap's tight one; the shared topic lets the newest alert replace an unsaid one.
    """
    m = _num(fuel_margin_laps)
    if m is None or m >= FUEL_TIGHT_LAPS:
        return None
    critical = m <= -FUEL_LIMIT_LAPS
    severity = "crit" if critical else "tight"
    msg_id = f"fuel-{severity}-lap{lap_number}" if lap_number is not None else f"fuel-{severity}-{next(_ids)}"
    meta: dict[str, object] = {TOPIC_KEY: "fuel", "fuel_margin_laps": round(m, 2)}
    if critical:
        text = f"Fuel critical: {abs(m):.1f} laps short to the finish."
        return _message(
            msg_id,
            MessageKind.ALERT,
            Priority.HIGH,
            text,
            now_mono,
            FUEL_ALERT_TTL_S,
            lap_number=lap_number,
            bypass_quiet=True,
            meta=meta,
        )
    if abs(m) < FUEL_LIMIT_LAPS:
        text = "Fuel is tight: right on the limit to the finish."
    else:
        text = f"Fuel is tight: plus {m:.1f} laps to the finish."
    return _message(
        msg_id, MessageKind.ALERT, Priority.NORMAL, text, now_mono, FUEL_ALERT_TTL_S, lap_number=lap_number, meta=meta
    )


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
