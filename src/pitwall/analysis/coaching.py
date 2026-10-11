"""Evidence-based coaching observations from lap comparisons.

Every observation is produced by a deterministic rule from measured deltas, carries the numbers it was
derived from (``evidence``), and states its confidence. No LLM is involved here; the AI engineer may later
explain these observations but must not invent new ones.

Design notes:
* Thresholds sit well above measurement resolution (one sample spacing at the game's send rate).
* "Brake later" is never suggested on its own: later braking is only praised when the corner segment was
  also faster, and is flagged as over-driving when it costs exit speed.
* ``confidence`` is *measurement* confidence (how clearly the delta exceeds threshold and sample resolution).
  ``consistency_ratio`` is separate: the fraction of recent laps showing the same deviation (habit vs one-off).
  Priority = time impact x confidence, boosted for consistent habits.
* Every observation is written three ways from the same facts (D6, docs/ui/design-spec.md): ``text`` (full, with
  the numbers), ``text_simple`` (one idea in plain words for simple-wording profiles: the main number only, no
  secondary numbers, no reference lap number, no habit statistics) and ``short`` (at most ``SHORT_MAX_CHARS``
  characters, for a glance on the Drive screen). All three describe what happened; none of them tells the driver
  to brake later.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from pitwall.analysis.compare import CornerDelta, LapComparison

if TYPE_CHECKING:
    from pitwall.analysis.track_identity import CornerText

MIN_TIME_LOSS_S = 0.02
BRAKE_POINT_M = 8.0
MIN_SPEED_KPH = 4.0
EXIT_SPEED_KPH = 3.0
THROTTLE_M = 15.0
COAST_M = 15.0
# One corner costing this much, or an apex below half the reference speed, is an incident (spin, contact, off-track,
# a yellow/safety-car slow-down), not a technique difference: report it once and give no technique advice from it.
INCIDENT_LOSS_S = 2.0
INCIDENT_SPEED_FRAC = 0.5
INCIDENT_MIN_REF_KPH = 60.0  # below this the reference itself is a hairpin crawl; ratios are meaningless
SHORT_MAX_CHARS = 48  # ``Observation.short``: readable in a glance on the Drive screen


@dataclass(slots=True)
class Observation:
    id: str
    kind: str
    corner: str
    lap_number: int
    ref_lap_number: int
    metric: str
    value: float
    unit: str
    impact_s: float | None
    confidence: float
    text: str
    evidence: dict[str, Any] = field(default_factory=dict)
    consistency: str | None = None
    consistency_ratio: float | None = None
    positive: bool = False
    corner_label: str | None = None  # official short label ("T10"), from analysis/track_identity.py
    corner_voice: str | None = None  # radio form ("Turn 10, Red Bull Mobile"); None = speak ``corner``
    text_simple: str | None = None  # one idea, plain words (simple-wording profiles)
    short: str | None = None  # <= SHORT_MAX_CHARS characters, for glance use
    # --- coachref --- the other driver the texts name when the reference is their lap (coach.reference_wording)
    ref_name: str | None = None

    @property
    def priority(self) -> float:
        base = abs(self.impact_s or 0.0) * self.confidence
        if self.consistency_ratio is not None:
            base *= 0.6 + 0.4 * self.consistency_ratio
        return base * (0.5 if self.positive else 1.0)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["priority"] = round(self.priority, 4)
        return d


def _r(x: float, nd: int = 0) -> float:
    return round(x, nd) if nd else float(round(x))


def _mag_conf(value: float, threshold: float, resolution: float) -> float:
    """0..1: how far the magnitude clears both the rule threshold and 2x measurement resolution."""
    floor = max(threshold, 2 * resolution)
    return max(0.0, min(1.0, 0.5 + 0.5 * (abs(value) - floor) / floor))


def _consistency(
    history: list[CornerDelta], attr: str, sign: int, threshold: float, current: float
) -> tuple[float, str] | None:
    """Fraction of recent laps (including this one) showing the same deviation."""
    vals = [getattr(h, attr) for h in history if getattr(h, attr) is not None] + [current]
    if len(vals) < 3:
        return None
    hits = sum(1 for v in vals if v * sign >= threshold)
    return hits / len(vals), f"{hits} of the last {len(vals)} laps"


def short_text(corner: str, body: str) -> str:
    """``"T15: braked 12 m earlier"``, or the body alone when the corner name would push it past
    ``SHORT_MAX_CHARS`` (the Drive screen shows the corner beside it anyway)."""
    line = f"{corner}: {body}"
    return line if len(line) <= SHORT_MAX_CHARS else body[:SHORT_MAX_CHARS]


def _evidence(cd: CornerDelta) -> dict[str, Any]:
    keys = (
        "time_delta_s",
        "brake_point_delta_m",
        "min_speed_delta_kph",
        "exit_speed_delta_kph",
        "entry_speed_delta_kph",
        "throttle_full_delta_m",
        "coast_delta_m",
    )
    ev: dict[str, Any] = {k: round(v, 3) for k in keys if (v := getattr(cd, k)) is not None}
    ev["ref"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in asdict(cd.ref).items()}
    ev["lap"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in asdict(cd.cmp).items()}
    return ev


def is_incident(cd: CornerDelta) -> bool:
    """A corner lost to an incident rather than technique (see ``INCIDENT_LOSS_S``): exclude it from averages,
    consistency history and technique advice."""
    loss = cd.time_delta_s
    if loss is None or loss <= 0:
        return False
    ref_min, cmp_min = cd.ref.min_speed_kph, cd.cmp.min_speed_kph
    crawled = (
        ref_min is not None
        and cmp_min is not None
        and ref_min >= INCIDENT_MIN_REF_KPH
        and cmp_min < INCIDENT_SPEED_FRAC * ref_min
    )
    return loss >= INCIDENT_LOSS_S or crawled


def observations_for_comparison(
    comp: LapComparison,
    history: dict[str, list[CornerDelta]] | None = None,
    resolution_m: float = 1.5,
    corner_text: Mapping[str, CornerText] | None = None,
) -> list[Observation]:
    """Rules applied per corner. ``history`` maps corner -> deltas from other recent laps vs same reference.

    ``corner_text`` (``track_identity.corner_texts(model)``) names corners officially in the text ("Turn 10 (Red
    Bull Mobile)"); ``Observation.corner`` stays the learned join key so ids and history are unaffected.
    """
    if not comp.compatibility.ok:
        return []
    history = history or {}
    out: list[Observation] = []
    L, R = comp.cmp_lap_number, comp.ref_lap_number

    for cd in comp.corners:
        loss = cd.time_delta_s
        hist = history.get(cd.corner, [])
        ev = _evidence(cd)
        ct = (corner_text or {}).get(cd.corner)
        cname = ct.long if ct else cd.corner
        cshort = ct.short if ct else cd.corner

        def add(
            kind: str,
            metric: str,
            value: float,
            unit: str,
            text: str,
            conf: float,
            cons: tuple[float, str] | None,
            simple: str,
            short: str,
            positive: bool = False,
            corner: str = cd.corner,
            evidence: dict[str, Any] = ev,
            impact: float | None = loss,
            label: str | None = ct.short if ct else None,
            voice: str | None = ct.voice if ct else None,
            long_name: str = cname,
            short_name: str = cshort,
        ) -> None:
            out.append(
                Observation(
                    id=f"L{L}:{corner}:{kind}",
                    kind=kind,
                    corner=corner,
                    lap_number=L,
                    ref_lap_number=R,
                    metric=metric,
                    value=round(value, 3),
                    unit=unit,
                    impact_s=None if impact is None else round(impact, 3),
                    confidence=round(conf, 2),
                    text=text,
                    evidence=evidence,
                    consistency=cons[1] if cons else None,
                    consistency_ratio=round(cons[0], 2) if cons else None,
                    positive=positive,
                    corner_label=label,
                    corner_voice=voice,
                    text_simple=f"{long_name}: {simple}",
                    short=short_text(short_name, short),
                )
            )

        if is_incident(cd) and loss is not None:
            add(
                "incident",
                "time_delta_s",
                loss,
                "s",
                f"{cname}: lost {loss:.1f} s - that looks like an incident (spin, contact, off-track or a slow-down), "
                "so no technique advice from this corner on this lap.",
                0.9,
                None,
                "that looked like an incident, so there is no advice from this corner on this lap.",
                "incident, no advice this lap",
            )
            continue

        losing = loss is not None and loss >= MIN_TIME_LOSS_S
        bp = cd.brake_point_delta_m
        ms = cd.min_speed_delta_kph
        ex = cd.exit_speed_delta_kph
        loss_txt = f", losing {loss:.2f} s through the corner" if losing and loss is not None else ""

        if bp is not None and bp <= -BRAKE_POINT_M and losing:
            add(
                "brake_early",
                "brake_point_delta_m",
                bp,
                "m",
                f"{cname}: you're braking about {_r(-bp):.0f} m earlier than your reference (lap {R}){loss_txt}.",
                _mag_conf(bp, BRAKE_POINT_M, resolution_m),
                _consistency(hist, "brake_point_delta_m", -1, BRAKE_POINT_M, bp),
                f"you braked about {_r(-bp):.0f} m earlier than on your reference lap.",
                f"braked {_r(-bp):.0f} m earlier",
            )
        elif bp is not None and bp >= BRAKE_POINT_M and losing and ex is not None and ex <= -EXIT_SPEED_KPH:
            add(
                "brake_late_overdrive",
                "brake_point_delta_m",
                bp,
                "m",
                f"{cname}: you're braking {_r(bp):.0f} m later than your reference but exiting "
                f"{_r(-ex):.0f} km/h slower - the later braking isn't paying off{loss_txt}.",
                _mag_conf(bp, BRAKE_POINT_M, resolution_m),
                _consistency(hist, "brake_point_delta_m", 1, BRAKE_POINT_M, bp),
                f"the later braking did not pay off - you came out {_r(-ex):.0f} km/h slower.",
                f"braked later, {_r(-ex):.0f} km/h slower out",
            )

        if ms is not None and ms <= -MIN_SPEED_KPH and losing:
            add(
                "low_min_speed",
                "min_speed_delta_kph",
                ms,
                "km/h",
                f"{cname}: minimum speed is {_r(-ms):.0f} km/h lower than your reference "
                f"({cd.cmp.min_speed_kph:.0f} vs {cd.ref.min_speed_kph:.0f} km/h){loss_txt}.",
                _mag_conf(ms, MIN_SPEED_KPH, 1.0),
                _consistency(hist, "min_speed_delta_kph", -1, MIN_SPEED_KPH, ms),
                f"you were {_r(-ms):.0f} km/h slower at the slowest point of the corner.",
                f"{_r(-ms):.0f} km/h slower mid-corner",
            )
        elif ms is not None and ms >= MIN_SPEED_KPH and ex is not None and ex <= -EXIT_SPEED_KPH and losing:
            add(
                "overspeed_apex",
                "min_speed_delta_kph",
                ms,
                "km/h",
                f"{cname}: you're carrying {_r(ms):.0f} km/h more into the apex but exiting "
                f"{_r(-ex):.0f} km/h slower - too much entry speed is compromising the exit.",
                _mag_conf(ms, MIN_SPEED_KPH, 1.0),
                _consistency(hist, "min_speed_delta_kph", 1, MIN_SPEED_KPH, ms),
                f"the extra speed into the corner cost you on the way out: {_r(-ex):.0f} km/h slower.",
                f"faster in, {_r(-ex):.0f} km/h slower out",
            )

        tf = cd.throttle_full_delta_m
        if tf is not None and tf >= THROTTLE_M and losing:
            add(
                "late_throttle",
                "throttle_full_delta_m",
                tf,
                "m",
                f"{cname}: you're reaching full throttle {_r(tf):.0f} m later than your reference{loss_txt}.",
                _mag_conf(tf, THROTTLE_M, resolution_m),
                _consistency(hist, "throttle_full_delta_m", 1, THROTTLE_M, tf),
                f"you got back to full throttle about {_r(tf):.0f} m later than on your reference lap.",
                f"full throttle {_r(tf):.0f} m later",
            )

        co = cd.coast_delta_m
        if co is not None and co >= COAST_M and losing:
            add(
                "coasting",
                "coast_delta_m",
                co,
                "m",
                f"{cname}: about {_r(co):.0f} m more coasting (no brake, no throttle) than your reference "
                "between brake release and throttle.",
                _mag_conf(co, COAST_M, resolution_m),
                _consistency(hist, "coast_delta_m", 1, COAST_M, co),
                f"you spent about {_r(co):.0f} m more off both pedals than on your reference lap.",
                f"{_r(co):.0f} m more coasting",
            )

        if ex is not None and ex >= EXIT_SPEED_KPH and loss is not None and loss <= -MIN_TIME_LOSS_S:
            add(
                "exit_gain",
                "exit_speed_delta_kph",
                ex,
                "km/h",
                f"{cname}: good - exit speed is up {_r(ex):.0f} km/h on your reference and you gained "
                f"{-loss:.2f} s there.",
                _mag_conf(ex, EXIT_SPEED_KPH, 1.0),
                None,
                f"good exit - you came out {_r(ex):.0f} km/h faster than on your reference lap.",
                f"good exit, {_r(ex):.0f} km/h faster",
                positive=True,
            )
    out.sort(key=lambda o: o.priority, reverse=True)
    return out


def top_focus(observations: list[Observation], n: int = 1) -> list[Observation]:
    """The highest-priority corrective observations with at least moderate confidence."""
    return [o for o in observations if not o.positive and o.confidence >= 0.5][:n]
