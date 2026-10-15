"""Grounding validation: every number in an AI answer must be traceable to a supplied fact, and every driving
technique it names to a fact about that technique.

If the answer cites facts, its numbers must come from the *cited* facts; otherwise from any supplied fact.
A number in the answer is accepted if it is a rounding of some number appearing in those facts (e.g.
fact "13.4 m" -> answer "13 m"), within 2% relative tolerance, or a trivially small integer (0-2). Sign is
ignored because facts say "-13 m (earlier)" where speech says "13 m earlier". Corner names ("T3", "Turn 3")
are identifiers, not measurements, and are excluded. Lap times "1:05.626" are compared in seconds.

Techniques (knowledge spec section 3: answers about technique cite only graph facts): a phrase that names a technique
or cause of the technique graph (``knowledge.terms.TERMS``: "trail braking", "heel and toe", "over-braking" ...) is
accepted only when one of the same facts is about it: a fact that declares its graph nodes (``data["nodes"]``, the
technique knowledge facts) is about exactly those, and any other fact is about what it says in its own words. A node
that one of those facts lists as not for this driver (``data["not_for_driver"]``: heel-and-toe for a paddle-shift
car, straight-line braking for a trail-braking driver) is never grounded, whatever another fact says. A common
technique the graph does not hold (``knowledge.terms.OTHER_TERMS``: "threshold braking", "a late apex" ...) is
accepted only when a fact says it. Otherwise it is an invented technique claim (``ungrounded_techniques``), and the
answer is not grounded.

Causes (``knowledge.graph.Cause.discriminates``): a cause whose base-rate check did not show it tells its fault apart
is what was also measured on a lap, never why the fault happened. A supplied fact lists those causes of its fault in
``data["not_the_reason"]`` (the technique knowledge facts); an answer that presents one of them as the reason - a
sentence naming the cause (``knowledge.terms.CAUSE_TERMS``) with a causal word ("because", "due to", "caused", "the
reason", "why", "led to", "down to" ...) that is not itself negated ("not the reason", "isn't why", "not because") - is
not grounded (``reason_claims``), whichever facts it cites, and the engineer falls back to the deterministic answer.

Coaching rules (CLAUDE.md; the technique graph's constraints, ``knowledge.graph.Constraint``): an answer that tells
the driver to brake later, brake less, release the brake earlier, carry more speed in or trail-brake more is not
grounded either (``constraint_breaches``), so the engineer falls back to the deterministic answer. Pitwall's own
descriptions stay allowed: a match that follows a subject or a determiner in its sentence ("you're braking 9 m later
than your reference", "the later braking isn't paying off") describes what happened; "Brake later", "Try braking
later", "You should carry more speed" do not.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pitwall.ai.facts import Fact
from pitwall.knowledge.graph import load_graph
from pitwall.knowledge.terms import CAUSE_TERMS, OTHER_TERMS, TERMS

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
    # coaching-rule breaches: "<constraint id>: <the words>" (an instruction to brake later, brake less ...)
    constraint_breaches: list[str] = field(default_factory=list)
    # a cause the facts say is not the reason, presented as one: "<cause id>: <the words naming it>"
    reason_claims: list[str] = field(default_factory=list)


def _listed(f: Fact, key: str) -> list[str] | None:
    v = f.data.get(key)
    return [x for x in v if isinstance(x, str)] if isinstance(v, list | tuple) else None


def _about(node_id: str, patterns: Sequence[re.Pattern[str]], f: Fact) -> bool:
    """Whether fact ``f`` is about technique-graph node ``node_id``: the nodes it declares when it declares them (the
    technique knowledge facts), else what it says in its own words."""
    nodes = _listed(f, "nodes")
    if nodes is not None:
        return node_id in nodes
    return any(p.search(f.text) or (f.say is not None and p.search(f.say)) for p in patterns)


def technique_claims(answer: str, facts: Sequence[Fact]) -> list[str]:
    """The technique phrases in ``answer`` that none of ``facts`` is about, or that one of them says is not for this
    driver (module docstring), as written."""
    text = _CITATION.sub(" ", answer)
    bad: list[str] = []
    not_for_driver = {x for f in facts for x in (_listed(f, "not_for_driver") or ())}
    for node_id, patterns in TERMS.items():
        hit = next((m for p in patterns if (m := p.search(text)) is not None), None)
        if hit is None:
            continue
        if node_id in not_for_driver or not any(_about(node_id, patterns, f) for f in facts):
            bad.append(hit.group(0))
    for p in OTHER_TERMS:
        m = p.search(text)
        if m is not None and not any(p.search(f.text) or (f.say is not None and p.search(f.say)) for f in facts):
            bad.append(m.group(0))
    return bad


# A coaching-rule match that follows one of these words in its sentence describes what happened ("you're braking 9 m
# later than your reference", "the later braking isn't paying off"): Pitwall's own observation wording, which an answer
# may repeat. Bare "you" is left out on purpose ("if you brake later ...").
_DESCRIBED = re.compile(
    r"(?:\b(?:you(?:'re|\u2019re| are| were|'ve been|\u2019ve been| have been)|we were|the|your|that|this|those)\s+)$",
    re.I,
)
_SENTENCE_END = re.compile(r"[.!?;:\n]")


def _described(text: str, start: int) -> bool:
    """Whether the words at ``start`` follow a subject or a determiner in their sentence (``_DESCRIBED``)."""
    before = text[:start]
    sentence = before[max((m.end() for m in _SENTENCE_END.finditer(before)), default=0) :]
    return _DESCRIBED.search(sentence) is not None


def constraint_breaches(answer: str) -> list[str]:
    """Instructions in ``answer`` the coaching rules forbid (the technique graph's constraints: brake later, brake less,
    release earlier, carry more speed, trail-brake more), as "<constraint id>: <words>", one per constraint; a match
    that describes what happened is not one (module docstring). Empty when the graph did not load."""
    text = _CITATION.sub(" ", answer)
    out: list[str] = []
    for c in load_graph().constraints:
        hit = next((m for p in c.patterns for m in p.finditer(text) if not _described(text, m.start())), None)
        if hit is not None:
            out.append(f"{c.id}: {hit.group(0)}")
    return out


# Words that make a sentence say why something happened. "so" and "from" alone are too common to count.
_CAUSAL = re.compile(
    r"\b(?:because|due to|caus(?:e|es|ed|ing)|reasons?|why|owing to|thanks to|down to|blame\w*|"
    r"result(?:s|ed|ing)? (?:of|from|in)|stem(?:s|med|ming)? from|(?:comes?|came|coming) from|"
    r"(?:led|leads?|leading) to|explain(?:s|ed|ing)?|responsible for|cost(?:s|ing)? you)\b",
    re.I,
)
# A causal word negated right before it ("not the reason", "isn't why", "not because", "not shown to be the cause"):
# the sentence says the cause is not the reason.
_NEGATED = re.compile(
    r"(?:\bnot|n['’]t|\bnever)\s+(?:(?:been\s+)?(?:shown|proven|known)\s+(?:to\s+be\s+)?)?"
    r"(?:(?:the|a|what|that)\s+)?(?:main\s+|only\s+|real\s+)?$",
    re.I,
)
# Sentence ends: a full stop that is not a decimal point ("0.3 s"), ! ? ; or a line break.
_SENTENCES = re.compile(r"(?<!\d)[.!?](?!\d)|[;\n]")


def reason_claims(answer: str, facts: Sequence[Fact]) -> list[str]:
    """Causes that ``facts`` list as not the reason (``data["not_the_reason"]``) presented as one in ``answer``
    (module docstring), as "<cause id>: <the words naming it>", one per cause."""
    ids = list(dict.fromkeys(x for f in facts for x in (_listed(f, "not_the_reason") or ())))
    if not ids:
        return []
    text = _CITATION.sub(" ", answer)
    out: list[str] = []
    for sentence in _SENTENCES.split(text):
        causal = [m for m in _CAUSAL.finditer(sentence) if not _NEGATED.search(sentence[: m.start()])]
        if not causal:
            continue
        for cid in ids:
            hit = next((m for p in CAUSE_TERMS.get(cid, ()) if (m := p.search(sentence)) is not None), None)
            if hit is not None and not any(o.startswith(f"{cid}: ") for o in out):
                out.append(f"{cid}: {hit.group(0)}")
    return out


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
    breaches = constraint_breaches(answer)
    reasons = reason_claims(answer, facts)  # every supplied fact: a cited one cannot make another cause the reason
    return GroundingResult(
        ok=not unknown and not bad and not techniques and not breaches and not reasons,
        cited=cited,
        unknown_citations=unknown,
        ungrounded_numbers=bad,
        ungrounded_techniques=techniques,
        constraint_breaches=breaches,
        reason_claims=reasons,
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
