"""Technique knowledge for a stored session (spec: technique knowledge graph, sections 2 and 3): its driver's Context
and detected style, its observations annotated, and the per-node fit the API serves.

``annotate_session(sa)`` runs inside ``core.session_analysis.SessionAnalyzer.analyse`` (cached with the analysis):
the Context comes from the session row (game, car, weather, assists), its laps' assists, the owner's profile
(``SessionAnalysis.driver``: their skill) and the style detected from the session's clean laps (``knowledge.style``:
every clean analysed lap of the session, the reference among them, incident corners left out); fuel saving is unknown
here (a stored session has no strategy view; the API adds the live one). Every observation dict of
``SessionAnalysis.observations`` gets its ``knowledge`` annotation (``knowledge.annotate``), the same as the live lap
processor gives it, so Review shows a point that does not fit the driver with its reason and the measured causes.

``annotate_pair`` does the same for a lap pair (``GET /api/compare``), with the compared lap's session's Context.
``session_payload`` is ``GET /api/technique/knowledge?session=<id>``: the whole graph plus the session's Context,
style, channels and every condition, signal, technique, fault, cause and advice node's ``applies`` / ``why_not``.

Deterministic; no LLM, no I/O beyond what the analysis already loaded.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from pitwall.analysis.coaching import is_incident
from pitwall.analysis.compare import CornerMetrics
from pitwall.knowledge.annotate import DriverKnowledge, LapSignals
from pitwall.knowledge.context import Context, channels_payload, session_row_context
from pitwall.knowledge.graph import TechniqueGraph, load_graph
from pitwall.knowledge.style import Style, braking_assist_of, detect_style

if TYPE_CHECKING:
    from pitwall.analysis.compare import LapAnalysis, LapComparison
    from pitwall.analysis.track import TrackModel
    from pitwall.core.session_analysis import SessionAnalysis

log = logging.getLogger(__name__)

FIT_LISTS = ("conditions", "signals", "techniques", "faults", "causes", "advice")


@dataclass(frozen=True, slots=True)
class SessionKnowledge:
    """A session's Context, detected style and game (``SessionAnalysis.knowledge``)."""

    context: Context
    style: Style
    game: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"context": self.context.to_dict(), "style": self.style.to_dict(), "game": self.game}


def clean_corner_metrics(sa: SessionAnalysis) -> dict[str, list[CornerMetrics]]:
    """``{corner: [CornerMetrics of each clean analysed lap]}`` of the session (the style detector's input); a corner
    lost to an incident on a lap is left out of that lap."""
    out: dict[str, list[CornerMetrics]] = {}
    for lap in sa.laps:
        lid = lap.get("id")
        an = sa.analyses.get(lid) if isinstance(lid, int) else None
        if an is None or not lap.get("clean"):
            continue
        comp = sa.comparisons.get(lid) if isinstance(lid, int) else None
        incidents = {cd.corner for cd in comp.corners if is_incident(cd)} if comp is not None else set()
        for name, m in an.corners.items():
            if name not in incidents:
                out.setdefault(name, []).append(m)
    return out


def session_knowledge(sa: SessionAnalysis, *, fuel_saving: bool | None = None) -> SessionKnowledge:
    style = detect_style(clean_corner_metrics(sa), braking_assist_of(sa.session.get("assists")))
    skill = (sa.driver or {}).get("skill_level")
    ctx = session_row_context(sa.session, sa.laps, skill=skill, style=style, fuel_saving=fuel_saving)
    game = sa.session.get("game")
    return SessionKnowledge(ctx, style, game if isinstance(game, str) else None)


def annotate_session(sa: SessionAnalysis, graph: TechniqueGraph | None = None) -> SessionKnowledge | None:
    """Annotate every observation of ``sa`` in place and return the session's knowledge; None without a graph (the
    observations stay as they were). Never raises: a knowledge bug leaves the analysis as before the graph."""
    g = graph if graph is not None else load_graph()
    if not g.valid:
        return None
    try:
        sk = session_knowledge(sa)
        dk = DriverKnowledge(g, sk.context, sk.game, sk.style.braking_assist)
        ref = sa.analyses.get(sa.ref_lap_id) if sa.ref_lap_id is not None else None
        corners = {c.name: c for c in sa.model.corners} if sa.model is not None else {}
        for lap_id, observations in sa.observations.items():
            comp = sa.comparisons.get(lap_id)
            deltas = {cd.corner: cd for cd in comp.corners} if comp is not None else {}
            dk.annotate_all(observations, LapSignals(deltas, sa.analyses.get(lap_id), ref, corners))
        return sk
    except Exception:
        log.exception("technique knowledge annotation failed (session %s)", sa.session.get("id"))
        for observations in sa.observations.values():
            for o in observations:
                o.pop("knowledge", None)
        return None


def annotate_pair(
    observations: list[dict[str, Any]],
    comp: LapComparison,
    lap: LapAnalysis,
    ref: LapAnalysis,
    model: TrackModel,
    sk: SessionKnowledge | None,
    graph: TechniqueGraph | None = None,
) -> None:
    """Annotate a lap pair's observation dicts in place (``GET /api/compare``) for the compared lap's session (``sk``:
    its driver's Context and style; None = nothing known about the driver). Never raises."""
    g = graph if graph is not None else load_graph()
    if not g.valid:
        return
    try:
        dk = (
            DriverKnowledge(g, sk.context, sk.game, sk.style.braking_assist)
            if sk is not None
            else DriverKnowledge(g, Context())
        )
        corners = {c.name: c for c in model.corners}
        dk.annotate_all(observations, LapSignals({cd.corner: cd for cd in comp.corners}, lap, ref, corners))
    except Exception:
        log.exception("technique knowledge annotation failed (lap pair)")
        for o in observations:
            o.pop("knowledge", None)


def session_payload(
    sa: SessionAnalysis, graph: TechniqueGraph | None = None, *, fuel_saving: bool | None = None
) -> dict[str, Any]:
    """The whole graph (``TechniqueGraph.to_payload``) for one session: plus ``session_id``, ``context``, ``style``,
    ``channels`` (``{channel: {status, words, caveat}}``) and, on every condition, signal, technique, fault, cause and
    advice node, ``applies`` / ``why_not`` for this driver. ``fuel_saving``: the live strategy's (None = unknown)."""
    g = graph if graph is not None else load_graph()
    sk = sa.knowledge if sa.knowledge is not None else session_knowledge(sa)
    ctx = sk.context if fuel_saving is None else replace(sk.context, fuel_saving=fuel_saving)
    dk = DriverKnowledge(g, ctx, sk.game, sk.style.braking_assist)
    fits = dk.node_fits()
    out = g.to_payload()
    for key in FIT_LISTS:
        for node in out[key]:
            f = fits.get(node["id"])
            if f is not None:
                node.update(f.to_dict())
    out.update(
        session_id=sa.session.get("id"),
        context=ctx.to_dict(),
        style=sk.style.to_dict(),
        channels=channels_payload(sk.game),
    )
    return out


def seen_faults(sa: SessionAnalysis) -> dict[str, list[Mapping[str, Any]]]:
    """``{fault id: [the annotated observations of it]}``, newest lap first (the AI engineer's facts)."""
    out: dict[str, list[Mapping[str, Any]]] = {}
    for lap_id in sorted(sa.observations, reverse=True):
        for o in sa.observations[lap_id]:
            k = o.get("knowledge")
            if isinstance(k, Mapping) and isinstance(k.get("fault"), str):
                out.setdefault(str(k["fault"]), []).append(o)
    return out
