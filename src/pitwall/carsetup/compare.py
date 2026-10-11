"""The driver's setup vs a recommendation, parameter by parameter, in plain words.

Input is what pitwall stored from the game's CarSetups packet (``repo.latest_setup(...)["params"]``: key ->
``{"value": ...}``) or a ``CarSetup``; values are converted to menu values (``Parameter.menu_value``) before
comparing. Rules:

* Each difference says which way the recommendation moves the parameter and what that changes in the car's
  behaviour (the catalogue's sourced ``higher``/``lower`` texts). It never says the change will make the driver
  faster: ``CAVEAT`` (from ``recommend``) travels with every diff.
* Size is relative to the parameter's range so wing clicks and tyre psi compare fairly: ``same`` (within a
  quarter step), ``small`` (up to 10 % of the range), ``moderate`` (up to 25 %), ``large`` (more).
* A value beyond a confirmed menu limit of the car format is flagged (``in_range`` False): it usually means the car
  format is wrong (e.g. a 2026 car compared with a 2025 setup), so the summary says so instead of explaining the
  difference. Beyond an end that is only the bound of published setups (not a confirmed limit), ``in_range`` is
  ``None``: unusual, not impossible.
* A single-variable experiment is suggested only from a difference whose recommended value has at least medium
  confidence; it is the largest such difference, and it is phrased as something to test.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pitwall.carsetup.catalog import Catalog, Parameter
from pitwall.carsetup.recommend import CAVEAT, SetupResult, SetupRow
from pitwall.model.telemetry import CarSetup

Magnitude = Literal["same", "small", "moderate", "large", "unknown"]
Direction = Literal["higher", "lower", "same", "unknown"]
SMALL_FRACTION = 0.10
MODERATE_FRACTION = 0.25
SAME_STEPS = 0.25


@dataclass(frozen=True, slots=True)
class DiffRow:
    key: str
    label: str
    group: str
    order: int
    unit: str | None
    yours: float | None
    yours_display: str
    recommended: float | None
    recommended_display: str
    delta: float | None  # recommended - yours, in the parameter's unit
    steps: float | None  # delta in menu steps
    direction: Direction  # which way the recommendation moves the parameter from yours
    magnitude: Magnitude
    in_range: bool | None  # False = beyond a confirmed menu limit; None = unknown or only beyond observed bounds
    confidence: str
    derived: bool
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "order": self.order,
            "unit": self.unit,
            "yours": self.yours,
            "yours_display": self.yours_display,
            "recommended": self.recommended,
            "recommended_display": self.recommended_display,
            "delta": self.delta,
            "steps": self.steps,
            "direction": self.direction,
            "magnitude": self.magnitude,
            "in_range": self.in_range,
            "confidence": self.confidence,
            "derived": self.derived,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class Experiment:
    """A single-variable change worth testing (never presented as a fix)."""

    key: str
    label: str
    from_value: float
    to_value: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "from_value": self.from_value,
            "to_value": self.to_value,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class SetupDiff:
    recommendation_id: str
    rows: tuple[DiffRow, ...]  # menu order
    differing: int
    out_of_range: tuple[str, ...]  # keys whose stored value is outside the car format's range
    not_compared: tuple[str, ...]  # stored keys that are not setup-sheet parameters (e.g. fuel load)
    summary: str
    experiment: Experiment | None
    caveat: str = CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "rows": [r.to_dict() for r in self.rows],
            "differing": self.differing,
            "out_of_range": list(self.out_of_range),
            "not_compared": list(self.not_compared),
            "summary": self.summary,
            "experiment": self.experiment.to_dict() if self.experiment else None,
            "caveat": self.caveat,
        }


def stored_values(params: Mapping[str, Any] | CarSetup) -> dict[str, float]:
    """``{key: udp value}`` from a ``CarSetup`` or a stored ``params`` dict (``{key: {"value": v, ...}}``)."""
    if isinstance(params, CarSetup):
        return {k: float(p.value) for k, p in params.parameters.items()}
    out: dict[str, float] = {}
    for k, p in params.items():
        v = p.get("value") if isinstance(p, Mapping) else p
        if isinstance(v, int | float) and not isinstance(v, bool):
            out[str(k)] = float(v)
    return out


def _fmt(p: Parameter, v: float | None) -> str:
    return f"{v:.{p.decimals}f}" if v is not None else "unknown"


def _magnitude(delta: float, row: SetupRow) -> Magnitude:
    if row.step is not None and abs(delta) < SAME_STEPS * row.step:
        return "same"
    if row.min is None or row.max is None:
        return "unknown"
    frac = abs(delta) / (row.max - row.min)
    if frac <= SMALL_FRACTION:
        return "small"
    if frac <= MODERATE_FRACTION:
        return "moderate"
    return "large"


def _explain(p: Parameter, row: SetupRow, yours: float | None, magnitude: Magnitude, direction: Direction) -> str:
    rec = _fmt(p, row.value)
    unit = f" {p.unit}" if p.unit else ""
    if row.value is None:
        return f"No source gives a {p.label.lower()} value for this setup, so there is nothing to compare."
    if yours is None:
        return f"Your {p.label.lower()} is unknown (the game has not sent it); recommended {rec}{unit}."
    if direction == "same":
        return f"Matches the recommendation ({rec}{unit})."
    effect = p.higher if direction == "higher" else p.lower
    return f"Recommended {rec}{unit} is {direction} than yours ({_fmt(p, yours)}{unit}), a {magnitude} change: {effect}"


def diff_setup(cat: Catalog, result: SetupResult, stored: Mapping[str, Any] | CarSetup) -> SetupDiff:
    udp = stored_values(stored)
    rows: list[DiffRow] = []
    out_of_range: list[str] = []
    for row in result.rows:
        p = cat.param(row.key)
        if p is None:
            continue
        raw = udp.get(row.key)
        yours = p.menu_value(raw) if raw is not None else None
        rng = cat.range(result.car_format, row.key)
        in_range: bool | None = None
        if rng is not None and yours is not None:
            in_range = False if rng.outside_menu(yours) else (True if rng.contains(yours) else None)
        if in_range is False:
            out_of_range.append(row.key)
        delta: float | None = None
        steps: float | None = None
        direction: Direction = "unknown"
        magnitude: Magnitude = "unknown"
        if yours is not None and row.value is not None:
            delta = round(row.value - yours, p.decimals + 2)
            steps = round(delta / row.step, 2) if row.step else None
            magnitude = _magnitude(delta, row)
            direction = "same" if magnitude == "same" else ("higher" if delta > 0 else "lower")
        rows.append(
            DiffRow(
                key=row.key,
                label=p.label,
                group=p.group,
                order=p.order,
                unit=p.unit,
                yours=yours,
                yours_display=_fmt(p, yours),
                recommended=row.value,
                recommended_display=row.display,
                delta=delta,
                steps=steps,
                direction=direction,
                magnitude=magnitude,
                in_range=in_range,
                confidence=row.confidence,
                derived=row.derived,
                explanation=_explain(p, row, yours, magnitude, direction),
            )
        )
    sheet = {r.key for r in result.rows}
    not_compared = tuple(sorted(k for k in udp if k not in sheet))
    differing = [r for r in rows if r.direction in ("higher", "lower")]
    experiment = _experiment(cat, result, differing) if not out_of_range else None
    return SetupDiff(
        recommendation_id=result.id,
        rows=tuple(rows),
        differing=len(differing),
        out_of_range=tuple(out_of_range),
        not_compared=not_compared,
        summary=_summary(cat, result, rows, differing, out_of_range),
        experiment=experiment,
    )


_ORDER = {"large": 3, "moderate": 2, "small": 1}


def _experiment(cat: Catalog, result: SetupResult, differing: list[DiffRow]) -> Experiment | None:
    ranked = [
        r for r in differing if r.confidence in ("high", "medium") and r.yours is not None and r.recommended is not None
    ]
    if not ranked:
        return None

    def span(r: DiffRow) -> float:
        row = result.row(r.key)
        return (row.max - row.min) if row is not None and row.max is not None and row.min is not None else 1.0

    best = max(ranked, key=lambda r: (_ORDER.get(r.magnitude, 0), abs(r.delta or 0) / span(r), -r.order))
    p = cat.param(best.key)
    assert p is not None and best.yours is not None and best.recommended is not None
    unit = f" {p.unit}" if p.unit else ""
    return Experiment(
        key=best.key,
        label=p.label,
        from_value=best.yours,
        to_value=best.recommended,
        text=(
            f"Something to test, not a fix: change only {p.label.lower()} from {best.yours_display}{unit} to "
            f"{best.recommended_display}{unit}, then compare a few clean laps with the same tyres and fuel."
        ),
    )


def _summary(
    cat: Catalog, result: SetupResult, rows: list[DiffRow], differing: list[DiffRow], out_of_range: list[str]
) -> str:
    fmt_label = cat.formats[result.car_format].label
    if out_of_range:
        labels = ", ".join(r.label.lower() for r in rows if r.key in out_of_range)
        return (
            f"Your {labels} {'is' if len(out_of_range) == 1 else 'are'} outside the {fmt_label} range, so this "
            "setup is probably for other cars: check the car format before comparing."
        )
    known = [r for r in rows if r.direction != "unknown"]
    if not known:
        return "Your setup has not been received from the game yet, so there is nothing to compare."
    if not differing:
        return f"Your setup matches the recommendation on all {len(known)} parameters pitwall can compare."
    big = [r.label.lower() for r in differing if r.magnitude in ("large", "moderate")]
    tail = f" Biggest differences: {', '.join(big[:3])}." if big else " All differences are small."
    return f"{len(differing)} of {len(known)} parameters differ from the recommendation.{tail}"
