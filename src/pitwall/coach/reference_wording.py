"""Coaching wording against another driver's lap (coachref): deterministic, no LLM.

``analysis.coaching`` writes every observation against "your reference" (the driver's own lap). When the live
reference is another driver's lap (``core.coachref``: the family record, another driver's best or a saved lap of
theirs), ``LapProcessor`` passes the observations through ``reword_observations`` so the text names that driver
("Sam carries 6 km/h more through the slowest point"). The numbers come from the observation's own fields
(``value``, ``impact_s``, ``evidence``), so the wording cannot drift from the analysis. ``id``, ``kind``, ``value``,
``impact_s``, ``confidence``, ``evidence`` and the priority are unchanged; only ``text``, ``text_simple`` and
``short`` are rewritten and ``ref_name`` is set.

Rules kept from ``analysis.coaching``: every text describes what happened; none tells the driver to brake later
(``brake_early`` stays descriptive, as for the own reference). Reference lap numbers are never mentioned: they belong
to another driver's session. ``short`` keeps ``coaching.short_text``'s rule (the corner prefix only when it fits in
``SHORT_MAX_CHARS``); a body that would not fit falls back to the own-reference body, which does.

``descriptor_labels`` names a resolved reference for the screen (``label``), the radio (``label_to``, said after
"to" / "than") and the observation wording (``ref_name``).
"""

from __future__ import annotations

import dataclasses
import math
import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from pitwall.analysis.coaching import MIN_TIME_LOSS_S, SHORT_MAX_CHARS, Observation, short_text

if TYPE_CHECKING:
    from pitwall.analysis.track_identity import CornerText

__all__ = ["descriptor_labels", "lap_date", "reword_observation", "reword_observations"]

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def lap_date(set_unix: float | None) -> str | None:
    """``"3 Oct"`` (local time) for a lap stored at ``set_unix``; None when unknown. Fixed month names, so the
    wording never depends on the host's locale."""
    t = _num(set_unix)
    if t is None:
        return None
    tm = time.localtime(t)
    return f"{tm.tm_mday} {_MONTHS[tm.tm_mon - 1]}"


CONDITIONS_LABEL = "Best in these conditions"
FAMILY_RECORD_LABEL = "Family record"


def descriptor_labels(
    kind: str,
    own: bool,
    pinned: bool,
    holder_name: str | None,
    lap_number: int | None,
    set_unix: float | None,
    *,
    conditions: bool = False,
) -> tuple[str, str, str | None]:
    """``(label, label_to, ref_name)`` for a resolved reference (spec 3.3 table). ``conditions``: the family's best
    lap in these conditions is not the family record (a faster lap was set in other conditions): it is called "Best
    in these conditions", never "Family record" (plan 5.2: one label per definition; the record is the REC lap).

    ``label`` is shown on screen ("Sam's best"), ``label_to`` follows "to" / "than" on the radio ("plus 0.792 to
    Sam's best"), ``ref_name`` names the other driver in observation texts (None for the driver's own laps)."""
    name = holder_name or "Another driver"
    date = lap_date(set_unix)
    lap_txt = f"lap {lap_number}" if lap_number is not None else "a lap"
    if kind == "household_best" and conditions:
        if own:
            return f"{CONDITIONS_LABEL} (you)", "the best lap in these conditions", None
        return f"{CONDITIONS_LABEL} · {name}", "the best lap in these conditions", name
    if kind == "household_best":
        if own:
            return "Family record (you)", "the family record", None
        return f"Family record · {name}", "the family record", name
    if kind == "driver_best" and not own:
        return f"{name}'s best", f"{name}'s best", name
    if kind == "lap":
        if own:
            head = f"Your {lap_txt}"
            return (f"{head} · {date}" if date else head), "your saved lap", None
        bits = [name, lap_txt, *([date] if date else [])]
        return " · ".join(bits), f"{name}'s lap", name
    if pinned:
        return "Your pinned lap", "your pinned lap", None
    return "Your best", "your best", None


def _short(cshort: str, primary: str, fallback: str) -> str:
    body = primary if len(primary) <= SHORT_MAX_CHARS else fallback
    return short_text(cshort, body)


def reword_observation(
    o: Observation, ref_name: str, corner_text: Mapping[str, CornerText] | None = None
) -> Observation:
    """One observation worded against ``ref_name``'s lap (see the module docstring); incidents and unknown kinds
    keep their text."""
    ct = (corner_text or {}).get(o.corner)
    cname = ct.long if ct else o.corner
    cshort = ct.short if ct else o.corner
    ev: Mapping[str, Any] = o.evidence if isinstance(o.evidence, Mapping) else {}
    d = round(abs(o.value))
    exit_delta = _num(ev.get("exit_speed_delta_kph"))
    e = round(abs(exit_delta)) if exit_delta is not None else 0
    impact = _num(o.impact_s)
    loss_txt = f", losing {impact:.2f} s through the corner" if impact is not None and impact >= MIN_TIME_LOSS_S else ""
    name = ref_name
    text: str | None = None
    simple = ""
    short = ""
    if o.kind == "brake_early":
        text = f"{cname}: you're braking about {d} m earlier than {name}{loss_txt}."
        simple = f"you braked about {d} m earlier than {name}."
        short = _short(cshort, f"braked {d} m earlier than {name}", f"braked {d} m earlier")
    elif o.kind == "brake_late_overdrive":
        text = (
            f"{cname}: you're braking {d} m later than {name} but exiting {e} km/h slower - the later braking isn't "
            f"paying off{loss_txt}."
        )
        simple = f"the later braking did not pay off - you came out {e} km/h slower than {name}."
        short = _short(cshort, f"braked later, {e} km/h slower out", f"braked later, {e} km/h slower out")
    elif o.kind == "low_min_speed":
        ref_m = ev.get("ref")
        lap_m = ev.get("lap")
        ref_v = _num(ref_m.get("min_speed_kph")) if isinstance(ref_m, Mapping) else None
        lap_v = _num(lap_m.get("min_speed_kph")) if isinstance(lap_m, Mapping) else None
        speeds = f" ({ref_v:.0f} vs {lap_v:.0f} km/h)" if ref_v is not None and lap_v is not None else ""
        text = f"{cname}: {name} carries {d} km/h more through the slowest point{speeds}{loss_txt}."
        simple = f"{name} was {d} km/h faster at the slowest point."
        short = _short(cshort, f"{name} carries {d} km/h more", f"{d} km/h slower mid-corner")
    elif o.kind == "overspeed_apex":
        text = (
            f"{cname}: you carry {d} km/h more into the apex than {name} but exit {e} km/h slower - too much entry "
            "speed is compromising the exit."
        )
        simple = f"the extra speed in cost you on the way out: {e} km/h slower than {name}."
        short = _short(cshort, f"faster in, {e} km/h slower out", f"faster in, {e} km/h slower out")
    elif o.kind == "late_throttle":
        text = f"{cname}: {name} is back on full throttle {d} m sooner{loss_txt}."
        simple = f"{name} got back to full throttle about {d} m sooner."
        short = _short(cshort, f"{name} full throttle {d} m sooner", f"full throttle {d} m later")
    elif o.kind == "coasting":
        text = (
            f"{cname}: about {d} m more coasting (no brake, no throttle) than {name} between brake release and "
            "throttle."
        )
        simple = f"you spent about {d} m more off both pedals than {name}."
        short = _short(cshort, f"{d} m more coasting than {name}", f"{d} m more coasting")
    elif o.kind == "exit_gain":
        gain = -impact if impact is not None else 0.0
        text = f"{cname}: good - your exit is {d} km/h faster than {name}'s and you gained {gain:.2f} s there."
        simple = f"good exit - {d} km/h faster than {name}."
        short = _short(cshort, f"good exit, {d} km/h up on {name}", f"good exit, {d} km/h faster")
    if text is None:  # incident (no technique advice either way) or a kind this module does not know
        return dataclasses.replace(o, ref_name=name)
    return dataclasses.replace(o, text=text, text_simple=f"{cname}: {simple}", short=short, ref_name=name)


def reword_observations(
    obs: Sequence[Observation], ref_name: str | None, corner_text: Mapping[str, CornerText] | None = None
) -> list[Observation]:
    """Copies of ``obs`` worded against ``ref_name``'s lap. ``ref_name`` None (an own reference) returns them
    unchanged."""
    if not ref_name:
        return list(obs)
    return [reword_observation(o, ref_name, corner_text) for o in obs]
