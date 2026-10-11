"""Pick the setup recommendation for a session: car format x track x session x conditions x style.

Pure function of the catalogue and the request (no I/O, no LLM). Rules:

* **Car formats are never mixed** and **wet is never served from dry**: a missing combination is
  ``RecommendationUnavailable`` with the reason and the alternatives that do exist, so the driver chooses.
* **Skill-aware style.** Without an explicit style, beginners get ``stable`` first, everyone else ``balanced``.
  An aggressive request with no aggressive setup falls back to balanced and says so.
* **Session stand-ins are labelled.** With no setup for the requested session (e.g. no qualifying setup), the
  other session's setup is shown with a note; its values keep their own provenance.
* **A setup is never a guaranteed fix.** Every result carries ``CAVEAT``: rule out technique first, then change one
  thing at a time (``ai/engineer.py`` SYSTEM_PROMPT applies the same rule to the race engineer).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pitwall.adapters.f1.enums import track_name
from pitwall.carsetup.catalog import (
    CAR_FORMATS,
    CONDITIONS,
    SESSIONS,
    STYLES,
    CarFormat,
    Catalog,
    Conditions,
    Confidence,
    Parameter,
    Recommendation,
    RecValue,
    SessionKind,
    SourceSetup,
    Style,
)

SkillLevel = Literal["beginner", "intermediate", "advanced"]
SKILL_LEVELS: tuple[SkillLevel, ...] = ("beginner", "intermediate", "advanced")

CAVEAT = (
    "A setup is a starting point, not a guaranteed fix: rule out technique first (braking point, entry speed, "
    "brake release, throttle), then change one thing at a time and compare laps."
)


class SetupRequestError(ValueError):
    """The request names a car format, session, conditions, style or skill pitwall does not know (HTTP 422)."""


class RecommendationUnavailable(LookupError):
    """No recommendation exists for the request; ``alternatives`` lists the catalogue keys that do (HTTP 404)."""

    def __init__(self, reason: str, alternatives: list[dict[str, Any]]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.alternatives = alternatives


@dataclass(frozen=True, slots=True)
class SetupRequest:
    car_format: CarFormat
    track_id: int
    session: SessionKind
    conditions: Conditions
    style: Style | None = None  # None = pick from the skill level
    skill_level: SkillLevel | None = None


@dataclass(frozen=True, slots=True)
class SetupRef:
    """Attribution for one cited setup."""

    id: str
    source: str
    source_name: str
    url: str
    author: str | None
    published: str | None
    patch: str | None
    session: str
    conditions: str
    style: str | None
    input: str | None
    verified: str


@dataclass(frozen=True, slots=True)
class SetupRow:
    key: str
    label: str
    group: str
    order: int
    value: float | None
    display: str  # menu-formatted, copy-friendly ("-3.50", "24.3")
    unit: str | None
    min: float | None
    max: float | None
    step: float | None
    confidence: Confidence
    derived: bool
    rule: str | None
    from_setup: str | None
    sources: tuple[str, ...]
    patches: tuple[str, ...]
    spread: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class SetupResult:
    id: str
    car_format: CarFormat
    track_id: int
    track_name: str
    session: SessionKind
    conditions: Conditions
    style: Style
    requested_session: SessionKind
    requested_style: Style
    style_reason: str
    selection: str
    rows: tuple[SetupRow, ...]
    setups: dict[str, SetupRef]
    disagreements: tuple[str, ...]
    notes: tuple[str, ...]
    caveat: str = CAVEAT
    groups: tuple[str, ...] = field(default=())

    def row(self, key: str) -> SetupRow | None:
        return next((r for r in self.rows if r.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "car_format": self.car_format,
            "track_id": self.track_id,
            "track_name": self.track_name,
            "session": self.session,
            "conditions": self.conditions,
            "style": self.style,
            "requested_session": self.requested_session,
            "requested_style": self.requested_style,
            "style_reason": self.style_reason,
            "selection": self.selection,
            "groups": list(self.groups),
            "rows": [_row_dict(r) for r in self.rows],
            "setups": {k: _ref_dict(v) for k, v in self.setups.items()},
            "disagreements": list(self.disagreements),
            "notes": list(self.notes),
            "caveat": self.caveat,
        }


def _row_dict(r: SetupRow) -> dict[str, Any]:
    return {
        "key": r.key,
        "label": r.label,
        "group": r.group,
        "order": r.order,
        "value": r.value,
        "display": r.display,
        "unit": r.unit,
        "min": r.min,
        "max": r.max,
        "step": r.step,
        "confidence": r.confidence,
        "derived": r.derived,
        "rule": r.rule,
        "from_setup": r.from_setup,
        "sources": list(r.sources),
        "patches": list(r.patches),
        "spread": list(r.spread) if r.spread is not None else None,
    }


def _ref_dict(s: SetupRef) -> dict[str, Any]:
    return {
        "id": s.id,
        "source": s.source,
        "source_name": s.source_name,
        "url": s.url,
        "author": s.author,
        "published": s.published,
        "patch": s.patch,
        "session": s.session,
        "conditions": s.conditions,
        "style": s.style,
        "input": s.input,
        "verified": s.verified,
    }


# ---------------------------------------------------------------------------------------------- parsing
def parse_car_format(v: object) -> CarFormat:
    if v in CAR_FORMATS:
        return v
    raise SetupRequestError(f"unknown car format {v!r}; expected one of {', '.join(CAR_FORMATS)}")


def parse_session(v: object) -> SessionKind:
    if v in SESSIONS:
        return v
    raise SetupRequestError(f"unknown session {v!r}; expected one of {', '.join(SESSIONS)}")


def parse_conditions(v: object) -> Conditions:
    if v in CONDITIONS:
        return v
    raise SetupRequestError(f"unknown conditions {v!r}; expected one of {', '.join(CONDITIONS)}")


def parse_style(v: object) -> Style:
    if v in STYLES:
        return v
    raise SetupRequestError(f"unknown style {v!r}; expected one of {', '.join(STYLES)}")


def parse_skill(v: object) -> SkillLevel:
    if v in SKILL_LEVELS:
        return v
    raise SetupRequestError(f"unknown skill level {v!r}; expected one of {', '.join(SKILL_LEVELS)}")


def parse_track_id(v: object) -> int:
    """EA track id from ``17`` or ``"f1:17"``."""
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v[3:] if v.startswith("f1:") else v
        if s.isdigit():
            return int(s)
    raise SetupRequestError(f"track id {v!r} is not an F1 25 track id (e.g. 17 or f1:17)")


# ---------------------------------------------------------------------------------------------- helpers
def default_style(skill: SkillLevel | None) -> tuple[Style, str]:
    if skill == "beginner":
        return "stable", "beginner driver: a stable setup first"
    if skill is None:
        return "balanced", "no driver skill level known: balanced setup"
    return "balanced", f"{skill} driver: balanced setup"


def ref_for(cat: Catalog, s: SourceSetup) -> SetupRef:
    src = cat.sources[s.source]
    return SetupRef(
        id=s.id,
        source=s.source,
        source_name=src.name,
        url=s.url,
        author=s.author,
        published=s.published,
        patch=s.patch,
        session=s.session,
        conditions=s.conditions,
        style=s.style,
        input=s.input,
        verified=s.verified,
    )


def _row(cat: Catalog, fmt: CarFormat, p: Parameter, v: RecValue | None) -> SetupRow:
    rng = cat.range(fmt, p.key)
    value = v.value if v is not None else None
    return SetupRow(
        key=p.key,
        label=p.label,
        group=p.group,
        order=p.order,
        value=value,
        display=f"{value:.{p.decimals}f}" if value is not None else "unknown",
        unit=p.unit,
        min=rng.min if rng else None,
        max=rng.max if rng else None,
        step=rng.step if rng else None,
        confidence=v.confidence if v is not None else "low",
        derived=v.derived if v is not None else False,
        rule=v.rule if v is not None else None,
        from_setup=v.from_setup if v is not None else None,
        sources=v.sources if v is not None else (),
        patches=v.patches if v is not None else (),
        spread=v.spread if v is not None else None,
    )


def available(cat: Catalog, car_format: CarFormat | None = None, track_id: int | None = None) -> list[dict[str, Any]]:
    """Catalogue keys that have a recommendation (optionally for one car format / track)."""
    return [
        {
            "car_format": r.car_format,
            "track_id": r.track_id,
            "session": r.session,
            "conditions": r.conditions,
            "style": r.style,
            "derived": r.selection == "derived",
        }
        for r in cat.recommendations.values()
        if (car_format is None or r.car_format == car_format) and (track_id is None or r.track_id == track_id)
    ]


def result_for(cat: Catalog, rec: Recommendation, req_session: SessionKind, req_style: Style, why: str) -> SetupResult:
    rows = tuple(
        _row(cat, rec.car_format, p, rec.values.get(p.key))
        for p in cat.parameters
        if cat.range(rec.car_format, p.key) is not None
    )
    cited = {rec.from_setup, *rec.candidates} | {sid for r in rows for sid in (*r.sources, r.from_setup or "")}
    setups = {sid: ref_for(cat, cat.source_setups[sid]) for sid in sorted(x for x in cited if x)}
    groups: list[str] = []
    for r in rows:
        if r.group not in groups:
            groups.append(r.group)
    return SetupResult(
        id=rec.id,
        car_format=rec.car_format,
        track_id=rec.track_id,
        track_name=track_name(rec.track_id),
        session=rec.session,
        conditions=rec.conditions,
        style=rec.style,
        requested_session=req_session,
        requested_style=req_style,
        style_reason=why,
        selection=rec.selection,
        rows=rows,
        setups=setups,
        disagreements=rec.disagreements,
        notes=rec.notes,
        groups=tuple(groups),
    )


# ---------------------------------------------------------------------------------------------- entry point
def recommend(cat: Catalog, req: SetupRequest) -> SetupResult:
    """The recommendation for ``req``, or ``RecommendationUnavailable`` (never a different car format or dry for
    wet)."""
    info = cat.formats.get(req.car_format)
    if info is None:
        raise RecommendationUnavailable(f"the catalogue has no {req.car_format} cars", available(cat))
    if req.track_id not in info.tracks:
        raise RecommendationUnavailable(
            f"{track_name(req.track_id)} is not drivable with {info.label}", available(cat, req.car_format)
        )
    style, why = (req.style, "requested") if req.style is not None else default_style(req.skill_level)
    other: SessionKind = "race" if req.session == "qualifying" else "qualifying"
    attempts: list[tuple[SessionKind, Style, str | None]] = [(req.session, style, None)]
    if style != "balanced":
        attempts.append((req.session, "balanced", f"No {style} setup for this combination; showing balanced."))
    attempts.append(
        (other, style, f"No {req.session} setup is published for these conditions; showing the {other} setup.")
    )
    if style != "balanced":
        attempts.append(
            (
                other,
                "balanced",
                f"No {req.session} or {style} setup for these conditions; showing the balanced {other} setup.",
            )
        )
    for session, st, note in attempts:
        rec = cat.find(req.car_format, req.track_id, session, req.conditions, st)
        if rec is None:
            continue
        res = result_for(cat, rec, req.session, style, why)
        if note is None:
            return res
        return replace(res, notes=(note, *res.notes))
    alts = available(cat, req.car_format, req.track_id)
    if req.conditions == "wet" and any(a["conditions"] == "dry" for a in alts):
        reason = (
            f"No wet setup is published for {track_name(req.track_id)} ({info.label}); pitwall does not turn a dry "
            "setup into a wet one. A dry setup is available."
        )
    else:
        reason = f"No {req.conditions} setup is published for {track_name(req.track_id)} ({info.label})."
    raise RecommendationUnavailable(reason, alts)
