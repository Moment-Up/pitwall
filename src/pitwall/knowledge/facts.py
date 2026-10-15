"""Facts for the AI engineer from the technique graph (topic ``knowledge``; spec: technique knowledge graph, section
3): the driver's Context and detected style, and for each fault seen this session its graph node, the causes Pitwall
measured, the techniques for that phase of the corner (those that fit this driver and those for other drivers) and
where the knowledge comes from, with its evidence tier.

``knowledge_facts(sa)`` returns ``(topic, text, data, say)`` tuples that ``ai.facts.build_fact_sheet`` adds last to
the sheet. Like every fact, ``text`` is what the LLM reads and ``say`` the driver-facing sentence; every number in
``say`` is also in ``text`` or ``data``, so deterministic answers built from it pass ``check_grounding``. ``data
["nodes"]`` lists the graph nodes a fact is about: an answer that names a technique (``knowledge.terms``) is grounded
only by a fact about it (``ai.grounding``), so the engineer explains the graph's techniques and never invents one.

Rules carried into the words: tiers are said as what they are (published coaching knowledge and Ed's brief are not
validated by Pitwall); node texts come from the graph, whose constraints keep every one free of "brake later", "brake
less", "release the brake earlier" and "carry more speed"; unknown stays unknown ("not known", never a guess).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from pitwall.knowledge.annotate import DriverKnowledge
from pitwall.knowledge.context import Context
from pitwall.knowledge.graph import Cause, Fault, Phase, Source, TechniqueGraph, load_graph
from pitwall.knowledge.style import COAST_M, MIN_BRAKING_CORNERS, MIN_LAPS, TRAIL_BRAKE_M, Style

if TYPE_CHECKING:
    from pitwall.core.session_analysis import SessionAnalysis

TOPIC = "knowledge"
CONTEXT_PREFIX = "Technique knowledge for this driver"
FAULT_PREFIX = "Technique knowledge"
FactTuple = tuple[str, str, dict[str, Any], str | None]
MAX_FAULT_FACTS = 8  # one per coaching kind at most
MAX_SOURCES = 4

TIER_WORDS: Mapping[str, str] = {
    "expert": "published coaching knowledge, not validated by Pitwall",
    "brief": "from Ed's brief (a Pitwall tester), not validated by Pitwall",
    "synthetic": "checked on generated laps only",
    "recorded": "measured by Pitwall on recorded laps",
    "live": "a Pitwall coaching rule",
    "design": "Pitwall's own definition",
}
STATUS_WORDS: Mapping[str, str] = {
    "live": "Pitwall coaches it",
    "experimental": "Pitwall measures it but does not coach it",
    "planned": "Pitwall does not measure it yet",
    "context_only": "background about the car, not a fault of the driver",
}
STYLE_WORDS: Mapping[str, str] = {"trail": "trail-braking", "straight_line": "straight-line braking", "mixed": "mixed"}
CONTEXT_WORDS: tuple[tuple[str, str], ...] = (
    ("skill", "skill"),
    ("game", "game"),
    ("car_family", "car"),
    ("downforce", "downforce"),
    ("gearbox", "gearbox"),
    ("abs", "ABS"),
    ("traction_control", "traction control"),
    ("wet", "track"),
    ("fuel_saving", "fuel saving"),
)
VALUE_WORDS: Mapping[str, str] = {
    "paddle_autoblip": "paddles with auto-blip",
    "h_pattern": "H-pattern",
    "auto": "automatic",
    "f1": "F1",
    "f2": "F2",
    "gt7": "GT7",
    "forza": "Forza",
    "ac": "Assetto Corsa",
    "acc": "ACC",
}


def _value(key: str, v: object) -> str:
    if isinstance(v, bool):
        if key == "wet":
            return "wet" if v else "dry"
        if key == "fuel_saving":
            return "asked for" if v else "not asked for"
        return "on" if v else "off"
    s = str(v)
    return VALUE_WORDS.get(s, s.replace("_", " "))


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


def _join(words: Sequence[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _context_fact(g: TechniqueGraph, ctx: Context, style: Style, fits: Sequence[str]) -> FactTuple:
    known = [f"{label} {_value(k, v)}" for k, label in CONTEXT_WORDS if (v := getattr(ctx, k)) is not None]
    unknown = [label for k, label in CONTEXT_WORDS if getattr(ctx, k) is None]
    data: dict[str, Any] = {
        "context": ctx.to_dict(),
        "style": style.to_dict(),
        "min_laps": MIN_LAPS,
        "min_braking_corners": MIN_BRAKING_CORNERS,
        "trail_brake_m": TRAIL_BRAKE_M,
        "coast_m": COAST_M,
        "nodes": list(fits),
    }
    if ctx.braking_style is not None:
        style_txt = (
            f"braking style {STYLE_WORDS.get(ctx.braking_style, ctx.braking_style)} (detected: braking with the wheel "
            f"turned for {TRAIL_BRAKE_M:.0f} m or more in {style.trail_corners} of {style.braking_corners} braking "
            f"corners over {style.laps} clean laps)"
        )
        say = (
            f"Your braking style here is {STYLE_WORDS.get(ctx.braking_style, ctx.braking_style)}: braking with the "
            f"wheel turned in {style.trail_corners} of {style.braking_corners} braking corners."
        )
        if style.assisted:  # the game's braking assist braked too: say so, never present it as all the driver's
            style_txt += "; the game's braking assist was on, so some of that braking was the game's"
            say += " The game's braking assist was on, so some of that braking was the game's, not yours."
    elif style.no_steering:  # the game sends no steering: braking with the wheel turned is never measured
        style_txt = (
            "braking style not known: the laps carry no steering, so braking with the wheel turned cannot be measured "
            f"(in {style.unsteered_corners} braking corners)"
        )
        say = "I can't tell your braking style here: this game sends no steering."
    else:
        style_txt = (
            f"braking style not detected yet (it needs {MIN_LAPS} clean laps with {MIN_BRAKING_CORNERS} braking "
            f"corners; so far {style.laps} laps, {style.braking_corners} braking corners)"
        )
        say = (
            f"I haven't detected your braking style yet: it needs {MIN_LAPS} clean laps with "
            f"{MIN_BRAKING_CORNERS} braking corners."
        )
    coast_txt = (
        f"coasting {ctx.coasting} (off both pedals for {COAST_M:.0f} m or more in {style.coast_corners} of "
        f"{style.coast_measured} braking corners)"
        if ctx.coasting is not None
        else "coasting not detected"
    )
    text = (
        f"{CONTEXT_PREFIX} (Pitwall's technique graph): {'; '.join([style_txt, coast_txt, *known])}"
        + (f". Not known: {_join(unknown)}" if unknown else "")
        + ". A technique or fault that needs something not known does not apply to this driver; techniques that fit: "
        + (_join([n.name for t in fits if (n := g.node(t)) is not None]) if fits else "only the universal ones")
        + "."
    )
    return TOPIC, text, data, say


def _source_words(g: TechniqueGraph, ids: Sequence[str]) -> list[str]:
    out: list[str] = []
    for sid in dict.fromkeys(ids):
        s = g.get(sid, Source)
        if s is not None:
            out.append(f"{s.title} ({s.author})")
    return out[:MAX_SOURCES]


def _fault_fact(
    g: TechniqueGraph, dk: DriverKnowledge, fault: Fault, observations: Sequence[Mapping[str, Any]]
) -> FactTuple:
    n = len(observations)
    fit = dk.fit(fault)
    counts: Counter[str] = Counter()
    for o in observations:
        k = o.get("knowledge") or {}
        for c in k.get("causes") or ():
            if isinstance(c, Mapping) and isinstance(c.get("id"), str):
                counts[c["id"]] += 1
    cause_bits: list[str] = []
    for cid, k in counts.most_common():
        c = g.get(cid, Cause)
        if c is not None:
            cause_bits.append(f"{c.name} on {k} of them ({TIER_WORDS[c.tier]})")
    phase = g.get(fault.phase, Phase)
    techniques = g.techniques_for(fault.phase)
    fits = [t for t in techniques if dk.fit(t).applies]
    others = [t for t in techniques if not dk.fit(t).applies]
    parts = [
        f"{FAULT_PREFIX} - {fault.name} ({STATUS_WORDS[fault.status]}; {TIER_WORDS[fault.tier]}): {fault.summary}",
        f"Seen {_times(n)} this session"
        + ("" if fit.applies else f"; not coached for this driver: {fit.why_not}")
        + ".",
        ("Causes Pitwall measured: " + "; ".join(cause_bits) + ".") if cause_bits else "No cause measured.",
    ]
    where = phase.name.lower() if phase is not None else fault.phase.replace("_", " ")
    if fits:
        parts.append(
            f"Techniques for the {where} that fit this driver: "
            + "; ".join(f"{t.name} ({TIER_WORDS[t.tier]}): {t.summary}" for t in fits)
        )
    if others:
        parts.append(
            "For other drivers, not this one: " + "; ".join(f"{t.name} ({dk.fit(t).why_not})" for t in others) + "."
        )
    cause_sources = [s for cid in counts if (c := g.get(cid, Cause)) is not None for s in c.sources]
    srcs = _source_words(g, [*fault.sources, *cause_sources])
    if srcs:
        parts.append("Sources: " + "; ".join(srcs) + ".")
    top = counts.most_common(1)
    top_cause = g.get(top[0][0], Cause) if top else None
    say = f"{fault.name}: seen {_times(n)} this session" + (
        f"; the cause measured most often: {top_cause.name.lower()}, on {top[0][1]} of them." if top_cause else "."
    )
    data: dict[str, Any] = {
        "fault": fault.id,
        "count": n,
        "applies": fit.applies,
        "causes": dict(counts),
        "nodes": [fault.id, *counts, *(t.id for t in techniques)],
    }
    return TOPIC, " ".join(parts), data, say


def knowledge_facts(sa: SessionAnalysis, graph: TechniqueGraph | None = None) -> list[FactTuple]:
    """The technique knowledge facts of a session (module docstring); none without a graph."""
    from pitwall.knowledge.session import seen_faults, session_knowledge

    g = graph if graph is not None else load_graph()
    if not g.valid:
        return []
    sk = sa.knowledge if sa.knowledge is not None else session_knowledge(sa)
    dk = DriverKnowledge(g, sk.context, sk.game)
    styled = [t.id for t in g.techniques if (t.applies_when or t.applies_any) and dk.fit(t).applies]
    out = [_context_fact(g, sk.context, sk.style, styled)]
    seen = seen_faults(sa)
    ranked = sorted(seen.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for fid, observations in ranked[:MAX_FAULT_FACTS]:
        fault = g.get(fid, Fault)
        if fault is not None:
            out.append(_fault_fact(g, dk, fault, observations))
    return out
