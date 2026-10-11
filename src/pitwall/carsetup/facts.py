"""Setup facts for the race engineer (``ai/facts.py``), built from a recommendation and the driver's setup diff.

``session_setup_facts`` is what ``ai.facts.build_fact_sheet`` calls: it maps the stored session to the catalogue
(``context``), picks the recommendation for the driver's skill (``recommend``) and diffs the session's latest stored
setup (``compare``). Each entry is ``(topic, text, data)`` ready for ``FactSheet.add``. Texts carry every number
the engineer may say (``ai/grounding.py`` checks numbers against the cited facts), name the recommendation's
provenance and confidence, and repeat the rule that a setup change is an experiment, never a guaranteed fix.
Sessions of other games get no setup facts; an F1 session pitwall cannot map (e.g. the car format is ambiguous)
gets one fact saying why, so the engineer can tell the driver what is missing.
"""

from __future__ import annotations

import logging
from typing import Any

from pitwall.carsetup.catalog import CatalogError, load_catalog
from pitwall.carsetup.compare import SetupDiff, diff_setup
from pitwall.carsetup.context import F1_GAMES, session_context
from pitwall.carsetup.recommend import (
    CAVEAT,
    RecommendationUnavailable,
    SetupRequest,
    SetupRequestError,
    SetupResult,
    parse_skill,
    recommend,
)

log = logging.getLogger(__name__)

TOPIC = "setup"
MAX_DIFF_FACTS = 5


def setup_facts(
    result: SetupResult | None, diff: SetupDiff | None, unavailable: str | None = None
) -> list[tuple[str, str, dict[str, Any]]]:
    """Fact entries for "what setup should I run here?" and "what's different from the recommended setup?"."""
    if result is None:
        why = unavailable or "no recommendation is available for this session"
        return [(TOPIC, f"Setup recommendation: none ({why}).", {"available": False})]
    authors = sorted({ref.source_name for ref in result.setups.values()})
    known = [r for r in result.rows if r.value is not None]
    values = ", ".join(f"{r.label} {r.display}{(' ' + r.unit) if r.unit else ''}" for r in known)
    derived = [r.label for r in result.rows if r.derived]
    low = [r.label for r in result.rows if r.confidence == "low" and r.value is not None]
    head = (
        f"Recommended {result.style} {result.conditions} {result.session} setup for {result.track_name} "
        f"({result.car_format.replace('_', ' ')} cars), from {', '.join(authors) or 'no named source'}: {values}."
    )
    out: list[tuple[str, str, dict[str, Any]]] = [
        (TOPIC, head, {"id": result.id, "values": {r.key: r.value for r in known}, "sources": authors})
    ]
    caveats = []
    if derived:
        caveats.append(f"pitwall derived {', '.join(derived)} (not published by a source)")
    if low:
        caveats.append(f"low confidence: {', '.join(low)}")
    caveats.extend(result.notes)
    if caveats:
        out.append((TOPIC, "Setup recommendation caveats: " + "; ".join(caveats) + ".", {"id": result.id}))
    if diff is not None:
        out.append((TOPIC, f"Driver's setup vs recommended: {diff.summary}", {"differing": diff.differing}))
        changes = [r for r in diff.rows if r.direction in ("higher", "lower")]
        changes.sort(key=lambda r: {"large": 0, "moderate": 1, "small": 2}.get(r.magnitude, 3))
        for r in changes[:MAX_DIFF_FACTS]:
            out.append(
                (
                    TOPIC,
                    f"{r.label}: driver {r.yours_display}, recommended {r.recommended_display} "
                    f"({r.magnitude} difference, {r.confidence} confidence). {r.explanation}",
                    {"key": r.key, "yours": r.yours, "recommended": r.recommended, "delta": r.delta},
                )
            )
        if diff.experiment is not None:
            out.append((TOPIC, diff.experiment.text, diff.experiment.to_dict()))
    out.append((TOPIC, CAVEAT, {}))
    return out


def session_setup_facts(
    session: dict[str, Any], stored_setup: dict[str, Any] | None, skill_level: object = None
) -> list[tuple[str, str, dict[str, Any]]]:
    """Setup facts for a stored session row (``repo.get_session``) and its latest stored setup
    (``repo.latest_setup``); ``skill_level`` is the session driver's (beginner -> stable setup)."""
    if session.get("game") not in F1_GAMES:
        return []
    ctx = session_context(session)
    keys = ("track_id", "car_format", "session", "conditions")
    missing = [ctx.reasons.get(k, f"{k} unknown") for k in keys if getattr(ctx, k) is None]
    if missing:
        return setup_facts(None, None, "; ".join(missing))
    assert ctx.car_format and ctx.track_id is not None and ctx.session and ctx.conditions
    try:
        skill = parse_skill(skill_level) if skill_level is not None else None
    except SetupRequestError:
        skill = None
    try:
        cat = load_catalog()
        res = recommend(cat, SetupRequest(ctx.car_format, ctx.track_id, ctx.session, ctx.conditions, skill_level=skill))
    except RecommendationUnavailable as e:
        return setup_facts(None, None, e.reason)
    except CatalogError:
        log.exception("car setup catalogue unavailable")
        return []
    diff = diff_setup(cat, res, stored_setup["params"]) if stored_setup is not None else None
    return setup_facts(res, diff)
