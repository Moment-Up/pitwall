"""Braking zones for the speak window when the driver has no learned track model yet (race radio review, UX 1).

The radio's speak window (``voice.scheduler.speak_window_ok``) needs the time to the next braking zone. The hub reads
it from the learned track model (``LiveState.track_model``, layer L3) and the next braking cue; on a new track, a
joined race or the first laps that model does not exist yet, and "unknown" counted as calm: real F1 25 races sent a
lap summary at 302 km/h in the very frame the brake went on, and a position call 0.4 s before full braking [M].

``knowledge_model`` turns the resolved track knowledge (``LiveState.track_knowledge``: ``core.track_knowledge``) into
the same ``{"length_m", "corners": [{"entry_m", "exit_m"}]}`` shape ``voice.hub.time_to_next_braking`` reads:

* the knowledge's corners (learned or the AI field's, layer L0b), entry to exit;
* every braking zone of the AI field, from its earliest onset (the onset's lower quartile when known) to where the
  next throttle phase starts (else its minimum-speed point) - any support, since a speak window errs towards silence;
* the physics prior's gated severity tags (layer L1c), their whole window.

A zone that runs over the line is split in two. Pure, O(zones); one result is cached per knowledge object (the
resolver publishes a new dict on every change, at most every few seconds), so the hub's tick costs a dict lookup.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_cache: tuple[object, dict[str, Any] | None] | None = None


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and v == v else None


def _add(out: list[dict[str, float]], start: float | None, end: float | None, length: float | None) -> None:
    if start is None or end is None:
        return
    if end >= start or not length:
        out.append({"entry_m": start, "exit_m": max(start, end)})
        return
    out.append({"entry_m": start, "exit_m": length})  # over the line: to the line, then from it
    out.append({"entry_m": 0.0, "exit_m": end})


def build(knowledge: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The speak-window model of ``knowledge`` (see the module docstring); None when it has no zone."""
    if not isinstance(knowledge, Mapping):
        return None
    length = _num(knowledge.get("track_length_m"))
    zones: list[dict[str, float]] = []
    for c in knowledge.get("corners") or ():
        if isinstance(c, Mapping):
            _add(zones, _num(c.get("entry_m")), _num(c.get("exit_m")), length)
    for z in knowledge.get("braking_zones") or ():
        if not isinstance(z, Mapping):
            continue
        onset = _num(z.get("onset_m"))
        early = _num(z.get("onset_q25_m"))
        start = onset if early is None or onset is None else min(onset, early)
        end = _num(z.get("end_m"))
        if end is None:
            end = _num(z.get("min_speed_m"))
        _add(zones, start, end, length)
    for t in knowledge.get("severity_tags") or ():
        if isinstance(t, Mapping):
            _add(zones, _num(t.get("window_start_m")), _num(t.get("window_end_m")), length)
    if not zones:
        return None
    return {"length_m": length, "corners": zones}


def knowledge_model(knowledge: Mapping[str, Any] | None, track_id: str | None) -> dict[str, Any] | None:
    """``build`` for the live session's track (knowledge of another track - the resolver has not caught up with a new
    session yet - is ignored), with a one-entry cache keyed by the knowledge object itself (event loop only)."""
    global _cache
    if knowledge is None or not track_id or knowledge.get("track_id") != track_id:
        return None
    if _cache is not None and _cache[0] is knowledge:
        return _cache[1]
    model = build(knowledge)
    _cache = (knowledge, model)
    return model
