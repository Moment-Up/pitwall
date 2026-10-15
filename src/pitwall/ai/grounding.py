"""Grounding validation: every number in an AI answer must be traceable to a supplied fact, and every driving
technique it names to a fact about that technique.

If the answer cites facts, its numbers must come from the *cited* facts; otherwise from any supplied fact.
A number in the answer is accepted if it is a rounding of some number appearing in those facts (e.g.
fact "13.4 m" -> answer "13 m"), within 2% relative tolerance, or a trivially small integer (0-2). Sign is
ignored because facts say "-13 m (earlier)" where speech says "13 m earlier". Corner names ("T3", "Turn 3")
are identifiers, not measurements, and are excluded. Lap times "1:05.626" are compared in seconds.

Techniques (knowledge spec section 3: answers about technique cite only graph facts): a phrase that names a technique
or cause of the technique graph (``knowledge.terms.TERMS``: "trail braking", "heel and toe", "over-braking" ...) is
accepted only when one of the same facts is about it - lists the node in ``data["nodes"]`` (the technique knowledge
facts) or says it in its own words; a common technique the graph does not hold (``knowledge.terms.OTHER_TERMS``:
"threshold braking", "a late apex" ...) only when a fact says it. Otherwise it is an invented technique claim
(``ungrounded_techniques``), and the answer is not grounded.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pitwall.ai.facts import Fact
from pitwall.knowledge.terms import OTHER_TERMS, TERMS

_CITATION = re.compile(r"\[(F\d+)\]")
_CORNER = re.compile(r"\b(?:T|Turn\s*|turn\s*|corner\s*|Corner\s*)(\d+)\b")
_LAPTIME = re.compile(r"(?<![\d.])(\d{1,2}):(\d{2}(?:\.\d+)?)")
_NUMBER = re.compile(r"(?<![A-Za-z\d._])[-+]?\d+(?:\.\d+)?(?![\d_])")  # skip identifiers like f1_25


def _numbers(text: str) -> list[tuple[float, int]]:
    """(value, decimals) for every number in ``text``; lap times are converted to seconds."""
    out: list[tuple[float, int]] = []
    text = _CITATION.sub(" ", text)
    text = _CORNER.sub(" ", text)

    def laptime(m: re.Match[str]) -> str:
        secs = int(m.group(1)) * 60 + float(m.group(2))
        dec = len(m.group(2).split(".")[1]) if "." in m.group(2) else 0
        out.append((secs, dec))
        return " "

    text = _LAPTIME.sub(laptime, text)
    for m in _NUMBER.finditer(text):
        s = m.group(0)
        dec = len(s.split(".")[1]) if "." in s else 0
        out.append((float(s), dec))
    return out


def fact_numbers(facts: list[Fact]) -> list[float]:
    vals: list[float] = []
    for f in facts:
        vals.extend(abs(v) for v, _ in _numbers(f.text))
        for v in f.data.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append(abs(float(v)))
    return vals


def _matches(x: float, dec: int, pool: list[float]) -> bool:
    x = abs(x)
    if dec == 0 and x <= 2:
        return True
    half_ulp = 0.5 * 10 ** (-dec) + 1e-9
    return any(abs(x - y) <= half_ulp or (y != 0 and abs(x - y) / abs(y) <= 0.02) for y in pool)


@dataclass(slots=True)
class GroundingResult:
    ok: bool
    cited: list[str] = field(default_factory=list)
    unknown_citations: list[str] = field(default_factory=list)
    ungrounded_numbers: list[str] = field(default_factory=list)
    ungrounded_techniques: list[str] = field(default_factory=list)  # technique phrases no considered fact is about


def _about(node_id: str, patterns: Sequence[re.Pattern[str]], f: Fact) -> bool:
    """Whether fact ``f`` is about technique-graph node ``node_id``: it lists it, or says it in its own words."""
    nodes = f.data.get("nodes")
    if isinstance(nodes, list | tuple) and node_id in nodes:
        return True
    return any(p.search(f.text) or (f.say is not None and p.search(f.say)) for p in patterns)


def technique_claims(answer: str, facts: Sequence[Fact]) -> list[str]:
    """The technique phrases in ``answer`` that none of ``facts`` is about (module docstring), as written."""
    text = _CITATION.sub(" ", answer)
    bad: list[str] = []
    for node_id, patterns in TERMS.items():
        hit = next((m for p in patterns if (m := p.search(text)) is not None), None)
        if hit is not None and not any(_about(node_id, patterns, f) for f in facts):
            bad.append(hit.group(0))
    for p in OTHER_TERMS:
        m = p.search(text)
        if m is not None and not any(p.search(f.text) or (f.say is not None and p.search(f.say)) for f in facts):
            bad.append(m.group(0))
    return bad


def check_grounding(answer: str, facts: list[Fact]) -> GroundingResult:
    by_id = {f.id: f for f in facts}
    cited = list(dict.fromkeys(_CITATION.findall(answer)))
    unknown = [c for c in cited if c not in by_id]
    known_cited = [by_id[c] for c in cited if c in by_id]
    considered = known_cited if known_cited else facts
    pool = fact_numbers(considered)
    bad = []
    for v, dec in _numbers(answer):
        if not _matches(v, dec, pool):
            bad.append(f"{v:.{dec}f}")
    techniques = technique_claims(answer, considered)
    return GroundingResult(
        ok=not unknown and not bad and not techniques,
        cited=cited,
        unknown_citations=unknown,
        ungrounded_numbers=bad,
        ungrounded_techniques=techniques,
    )


def strip_citations(text: str) -> str:
    """For speech: remove [F12] markers and tidy whitespace."""
    return re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s*\[F\d+\](?:\s*,?\s*\[F\d+\])*", "", text)).strip()


# Internal bookkeeping that must never reach the driver (dashboard text or radio): fact ids in any bracket style
# ("[F12]", "[F3, F4]", "(F12)", "(facts F3 and F4)"), "fact F12" mentions, and the observation label/confidence
# the facts carry for the LLM ("Coaching observation (lap 71, confidence 1.00): ...", "confidence 0.85").
_ID_LIST = r"F\d+(?:\s*(?:,|;|/|and|&)\s*F?\d+)*"
_ID_NUM = re.compile(r"F?(\d+)")
_BRACKETED_IDS = re.compile(
    r"\s*[\[(]\s*(?P<kw>(?:(?:see|per|from)\s+)?(?:facts?\s+)?)(?P<ids>" + _ID_LIST + r")\s*[\])]", re.I
)
_FACT_MENTION = re.compile(
    r",?\s*\b(?:(?:see|per|from|according to|as in)\s+)?facts?\s+(?P<ids>" + _ID_LIST + r")\b", re.I
)
_ID_WORD = re.compile(r"\bF\d+\b")
_OBS_LABEL = re.compile(
    r"\bcoaching observation\s*\([^()]*\b(?:lap|confidence)\b[^()]*\)\s*:?\s*"  # the fact's own label
    r"|(?:^|(?<=[.!?]\s))coaching observation\s*:\s*",  # or its bare form opening a sentence
    re.I,
)
_CONF_PAREN = re.compile(r"\s*\((?:[^()]*?[,;]\s*)?confidence\s*(?:of\s*)?[:=]?\s*\d+(?:\.\d+)?%?[^()]*\)", re.I)
# "Confidence: 0.9 - the data is clear." opens a sentence: the score goes with the separator after it
_CONF_LEAD = re.compile(
    r"(?:^|(?<=[.!?]\s))(?:with\s+)?(?:a\s+)?confidence\s*(?:of\s*)?[:=]?\s*\d+(?:\.\d+)?%?"
    r"(?:\s*[-\u2013\u2014:;,.]\s*|\s+|$)",
    re.I,
)
_CONF_PHRASE = re.compile(r",?\s*\b(?:with\s+)?(?:a\s+)?confidence\s*(?:of\s*)?[:=]?\s*\d+(?:\.\d+)?%?", re.I)
# a full stop that ends an abbreviation, not a sentence: the word after it keeps its case ("e.g. lap 3")
_ABBREVIATION_END = re.compile(r"(?:\b(?:e\.g|i\.e|etc|vs|cf|approx|incl)\.)\s*$", re.I)


def display_text(text: str, facts: Sequence[Fact] | None = None) -> str:
    """What the driver sees and hears for a (grounded) answer: no fact ids, no observation labels, no confidence
    scores. Grounding runs on the cited text before this; the citations stay in ``EngineerAnswer.cited_text`` and
    ``EngineerAnswer.facts``. Only bookkeeping goes: the answer's own words and numbers are kept.

    ``facts``: the facts the answer could cite. Then only their ids count as bookkeeping, and a bare "(F2)" whose
    token the facts themselves use as a word (an F2 car, the F1 25 game) stays: it is part of the answer, not a
    citation. Square-bracket citations ("[F2]") always go: the engineer is told to cite that way. ``None`` treats
    every ``F<n>`` in a citation form as an id."""
    known = None if facts is None else {f.id for f in facts}
    words: set[str] = set()
    for f in facts or ():
        words.update(_ID_WORD.findall(f.text))
        words.update(_ID_WORD.findall(f.plain))

    def ids_of(m: re.Match[str]) -> list[str]:
        return [f"F{n}" for n in _ID_NUM.findall(m.group("ids"))]

    def bookkeeping(ids: list[str], explicit: bool) -> bool:
        if known is not None and not all(i in known for i in ids):
            return False  # not ids of this answer's facts: words ("Formula F7"), kept as written
        return explicit or not any(i in words for i in ids)

    def bracketed(m: re.Match[str]) -> str:
        explicit = m.group(0).lstrip().startswith("[") or bool(m.group("kw").strip())
        return "" if bookkeeping(ids_of(m), explicit) else m.group(0)

    def mention(m: re.Match[str]) -> str:
        return "" if bookkeeping(ids_of(m), True) else m.group(0)

    out = strip_citations(text)
    out = _BRACKETED_IDS.sub(bracketed, out)
    out = _FACT_MENTION.sub(mention, out)
    out = _OBS_LABEL.sub("", out)
    out = _CONF_PAREN.sub("", out)
    out = _CONF_LEAD.sub("", out)
    out = _CONF_PHRASE.sub("", out)
    out = re.sub(r"\(\s*\)", "", out)  # parentheses that only held bookkeeping
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    out = re.sub(r"[,;:]+([.!?])", r"\1", out)  # "lap 4,." -> "lap 4."
    out = re.sub(r"(^|[.!?]\s+)[,;:]+\s*", r"\1", out.strip())  # a sentence that started with a removed mention

    def capital(m: re.Match[str]) -> str:
        if _ABBREVIATION_END.search(m.string[: m.start(2)]):
            return m.group(0)
        return m.group(1) + m.group(2).upper()

    out = re.sub(r"(^|[.!?]\s+)([a-z])", capital, out)
    return out.strip()
