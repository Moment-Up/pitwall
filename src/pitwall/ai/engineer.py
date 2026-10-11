"""The AI race engineer: question -> intent -> relevant facts -> (LLM) -> grounding check -> answer.

* Intent detection is rule-based (instant, deterministic, works offline). Control commands such as
  "stop talking for a few laps" never reach the LLM.
* The LLM only rephrases/explains supplied facts. Answers whose numbers cannot be traced to the facts are
  retried once with feedback, then replaced by a deterministic answer built directly from the facts.
* If the LLM is unavailable the engineer still answers deterministically.
* Citations are bookkeeping: grounding checks the cited text (``EngineerAnswer.cited_text``), and the facts used
  are returned in ``EngineerAnswer.facts``. What the driver sees and hears (``text`` / ``speech``) never carries
  fact ids, observation labels or confidence scores (``grounding.display_text``).
* A question only about data the game does not send (or Pitwall does not read yet: ``games.capability_only``, e.g.
  tyres in Assetto Corsa) is answered deterministically from the sheet's ``game`` facts, without the LLM.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pitwall import games
from pitwall.ai.facts import AI_LEVEL_PREFIX, AI_PACE_PREFIX, LAST_LAP_PREFIX, NO_AI_COMPARISON, Fact, FactSheet
from pitwall.ai.grounding import GroundingResult, check_grounding, display_text
from pitwall.ai.providers import LLMProvider, LLMUnavailable

log = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class Intent:
    name: str
    corner: str | None = None
    quiet_laps: int | None = None


_WORDS_TO_NUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
_CORNER_RE = re.compile(r"\b(?:(?:turn|corner)\s*(\d{1,2}|" + "|".join(_WORDS_TO_NUM) + r")|t\s?(\d{1,2}))\b", re.I)

# One ordered intent table (v0.2.0 plan 4.1): the first match wins. Every lane's intents in one order, so a question
# that names two things goes where a driver means it ("inters" is weather before tyres, "damaged after the contact
# with the car ahead" is damage before gaps, "my position on the brake" is braking, not race position). The coachref
# drill rules join at the top (after radio_check) when that lane lands.
_AI = r"(?:ai|a\.?\s?i\.?|computer|bots?)"

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("radio_check", re.compile(r"\b(radio check|can you hear me|do you (?:read|copy)(?: me)?|mic check)\b", re.I)),
    (
        "control_quiet",
        re.compile(
            r"\b(stop talking|be quiet|quiet|shut up|silence|no more (?:talking|radio)|"
            r"leave me alone)\b",
            re.I,
        ),
    ),
    ("control_resume", re.compile(r"\b(resume|start talking|talk to me again|you can talk|coaching on)\b", re.I)),
    # pace vs AI difficulty: before "pace" (lap_times), "vs" (compare), "what should i" (focus) and "gap" (gaps)
    (
        "ai_level",
        re.compile(
            r"\b(?:ai|a\.?\s?i\.?)\s+(?:level|difficulty|setting|skill)s?\b|\b(?:what|which)\s+(?:ai\s+)?difficulty\b"
            r"|\bdifficulty\s+(?:should|level)\b|\b(?:turn|put|set|bump)\s+(?:the\s+)?(?:ai|a\.?\s?i\.?)\s+(?:up|down)\b"
            # parents' words: "is the AI too hard?", "should I make the AI harder?", "how hard should I set the AI?",
            # "what should I set the AI to?", "what AI should my son use?"
            r"|\b(?:ai|a\.?\s?i\.?|computer|bots?)\b[^.?!]*\b(?:too\s+(?:hard|easy|fast|slow)|harder|easier)\b"
            r"|\bhow\s+hard\b[^.?!]*\b(?:ai|a\.?\s?i\.?|computer|bots?)\b|\bset\s+(?:the\s+)?(?:ai|a\.?\s?i\.?)\b"
            r"|\b(?:what|which)\s+(?:ai|a\.?\s?i\.?)\s+should\b",
            re.I,
        ),
    ),
    (
        "ai_pace",
        re.compile(
            r"\b(?:against|vs\.?|versus|compared?\s+(?:to|with)|than|beat(?:ing)?)\s+(?:the\s+)?"
            r"(?:ai|a\.?\s?i\.?|computer|bots?)\b|\b(?:ai|a\.?\s?i\.?)\s+(?:pace|cars?|drivers?|field)\b"
            # "what's my gap to the AI?", "how far behind the AI am I?", "is the computer faster than me?"
            rf"|\bgap\b[^.?!]*\b{_AI}\b|\b(?:behind|ahead of|off|catch(?:ing)?)\s+(?:the\s+)?{_AI}\b"
            rf"|\b{_AI}\b[^.?!]*\b(?:faster|slower|quicker)\b",
            re.I,
        ),
    ),
    ("fuel", re.compile(r"\b(fuel|petrol|gas|lift and coast)\b", re.I)),
    # weather (one intent, two rules): the wet-tyre and forecast words before tyres ("should I box for inters?", "are
    # the tyres OK in the wet?"); the plain weather words last (below), so "where should I brake at turn 4 in the
    # rain?" stays braking and "what setup for rain?" setup
    ("weather", re.compile(r"\b(inters?|intermediates?|forecast|wet)\b", re.I)),
    ("tyres", re.compile(r"\b(tyres?|tires?|wear|degradation|deg|grip|tyre temps?)\b", re.I)),
    (
        "strategy",
        re.compile(
            r"\b(pit|box|strategy|stop window|pit window|undercut|overcut|stay out|when should i (?:pit|stop|box))\b",
            re.I,
        ),
    ),
    ("safety_car", re.compile(r"\b(safety car|vsc|virtual safety car)\b", re.I)),
    # data some games never send (games.INTENT_FEATURES), before setup ("front wing broken": "wing" alone stays a
    # setup question) and before gaps ("damaged after the contact with the car ahead")
    ("damage", re.compile(r"\b(damage|damaged|broken|repair|wing damage|floor damage)\b", re.I)),
    # race gaps and position, never the driver's own reference ("how far behind my best am I?") and "position" only as
    # race position ("my position on the brake for turn 4" is braking)
    (
        "gaps",
        re.compile(
            r"^(?!.*\b(?:best|reference|pb|personal best|delta|record)\b).*?"
            r"\b(gaps?|interval|car (?:ahead|behind|in front)|behind me|in front of me|how far (?:ahead|behind|back)|"
            r"catching|within a second|drs range|in drs|(?:what|which) position|race position|"
            r"position (?:am i|are we))\b",
            re.I,
        ),
    ),
    # --- feat/technique: handling balance (before setup: "understeer" asks how the car handled) ---
    (
        "balance",
        re.compile(
            r"\b(under-?steer\w*|over-?steer\w*|(?<!brake )balance|push(?:es|ing)? wide|snap(?:py|s)?|loose|"
            r"rear (?:end )?(?:steps?|stepping|kicks?|kicking) out|(?:won't|doesn't) turn(?: in)?)\b",
            re.I,
        ),
    ),
    # --- end feat/technique ---
    (
        "setup",
        re.compile(
            r"\b(set ?up|wing|understeer|oversteer|balance|diff|differential|anti.?roll|arb|"
            r"ride height|camber|toe|suspension|brake bias|pressures?)\b",
            re.I,
        ),
    ),
    # --- feat/technique: racing line (after setup) ---
    (
        "line",
        re.compile(
            r"\b(racing line|(?:my|the|your) line|wider|tighter|run(?:ning)? wide|apex(?:es)?(?!\s*speed)|"
            r"turn[- ]in point|track[- ]out)\b",
            re.I,
        ),
    ),
    # --- end feat/technique ---
    ("focus", re.compile(r"\b(one thing|work on|focus|improve|tip|advice|what should i)\b", re.I)),
    ("compare", re.compile(r"\b(compare|comparison|versus|vs|against my best|to my best|reference)\b", re.I)),
    # --- feat/technique: brake and throttle technique (after compare, before braking) ---
    (
        "technique",
        re.compile(
            r"\b(trail[- ]?brak\w*|lock(?:ing|ed|s)?[- ]?ups?|wheel ?spin\w*|traction|coast(?:ing)?|"
            r"on the (?:power|throttle)|brake release|releas\w+ the brake|smooth\w*)\b",
            re.I,
        ),
    ),
    # --- end feat/technique ---
    ("braking", re.compile(r"\b(brak\w*|brake point|where should i brake)\b", re.I)),
    # "how was my last lap / that lap": the lap just driven, not the best one (checked before lap_times)
    ("last_lap", re.compile(r"\b(?:last|previous|latest|that|this) lap\b(?!\s*times\b)", re.I)),
    ("lap_times", re.compile(r"\b(lap ?times?|fastest|best lap|pace|how fast)\b", re.I)),
    # "how am I doing (so far / overall / today / now)?" on its own is a summary, not a goal question
    (
        "summary",
        re.compile(
            r"\b(summary|summarise|summarize|debrief|how did (?:i|that) go|report)\b"
            r"|\bhow am i doing(?:\s+(?:so far|overall|today|now))?\s*[?.!]*\s*$",
            re.I,
        ),
    ),
    ("losing_time", re.compile(r"\b(losing time|lose time|where am i (?:slow|losing)|time loss|slow(?:er)?)\b", re.I)),
    # lane motivation (review #1): narrowed and after losing_time. "What's my target lap time?" stays lap_times, "am I
    # on target?" general; "how many sessions did I do this week?" is a goal question
    (
        "goals",
        re.compile(
            r"\b(goals?|streaks?|badges?|how am i doing (?:on|with) (?:my|the|that) goals?|how am i doing this week|"
            r"how many (?:sessions|laps)\b[^.?!]*\bthis week|(?:sessions|laps) this week)\b",
            re.I,
        ),
    ),
    # More data some games never send (games.INTENT_FEATURES): last, so they only catch questions no rule above
    # matched ("where should I brake at turn 4 in the rain?" stays braking, "which sector am I losing time in?"
    # losing_time, "was that lap slower because of the yellow?" last_lap). Flags and weather before sectors ("a yellow
    # in sector 2?"); the safety car and VSC have their own intent above.
    ("ers", re.compile(r"\b(ers|battery|deploy(?:ment)?|hybrid|harvest\w*|overtake mode|drs)\b", re.I)),
    ("flags", re.compile(r"\b(flags?|yellow|marshal\w*)\b", re.I)),
    ("weather", re.compile(r"\b(weather|rain(?:ing)?|drying|track temp\w*|air temp\w*)\b", re.I)),
    ("sectors", re.compile(r"\b(sectors?|splits?)\b", re.I)),
]

_TOPICS: dict[str, set[str]] = {
    # every intent keeps the "game" topic: what the game never sends is answered from it
    "fuel": {"session", "game", "fuel", "strategy"},
    "tyres": {"session", "game", "tyres", "strategy"},
    "strategy": {"session", "game", "fuel", "tyres", "strategy", "gaps"},
    "safety_car": {"session", "game", "strategy", "flags"},
    "gaps": {"session", "game", "gaps"},
    "weather": {"session", "game", "weather", "tyres", "strategy"},
    # damage / ERS / flags were "general" questions before game selection: same facts (plus ERS), so a game that sends
    # the data gets the answer it always got; a game that never sends it answers from its "game" fact
    "damage": {"session", "game", "laps", "corners", "observations", "reference", "fuel", "tyres"},
    "ers": {"session", "game", "ers", "laps", "corners", "observations", "reference", "fuel", "tyres"},
    "sectors": {"session", "game", "laps"},
    "flags": {"session", "game", "laps", "corners", "observations", "reference", "fuel", "tyres"},
    "setup": {"session", "game", "corners", "observations", "compare", "setup", "balance"},  # balance: feat/technique
    "focus": {"session", "game", "observations", "corners", "reference"},
    "goals": {"session", "game", "goals", "progress"},  # lane motivation
    "compare": {"session", "game", "compare", "reference", "laps"},
    "braking": {"session", "game", "corners", "observations", "reference"},
    "lap_times": {"session", "game", "laps", "reference"},
    "last_lap": {"session", "game", "laps", "reference", "compare"},
    "summary": {"session", "game", "laps", "corners", "observations", "fuel", "tyres", "ai", "goals", "strategy"},
    "ai_pace": {"session", "game", "ai"},  # pace vs AI difficulty
    "ai_level": {"session", "game", "ai"},
    "losing_time": {"session", "game", "corners", "compare", "observations", "reference"},
    "corner": {"session", "game", "reference"},
    # --- feat/technique ---
    "line": {"session", "game", "line", "reference"},
    "technique": {"session", "game", "technique", "reference", "observations"},
    "balance": {"session", "game", "balance", "setup"},
    # --- end feat/technique ---
    "general": {
        "session",
        "game",
        "laps",
        "corners",
        "observations",
        "reference",
        "fuel",
        "tyres",
        "ai",
        "gaps",
        "goals",
    },
}


def detect_intent(question: str) -> Intent:
    q = question.strip()
    corner = None
    m = _CORNER_RE.search(q)
    if m:
        raw = (m.group(1) or m.group(2)).lower()
        corner = f"T{_WORDS_TO_NUM.get(raw, raw)}"
    for name, rx in _RULES:
        if rx.search(q):
            if name == "control_quiet":
                n = re.search(r"\b(\d+|" + "|".join(_WORDS_TO_NUM) + r")\s+laps?\b", q, re.I)
                laps = None
                if n:
                    laps = int(_WORDS_TO_NUM.get(n.group(1).lower(), n.group(1)))
                elif re.search(r"\bfew laps\b", q, re.I):
                    laps = 3
                return Intent(name, quiet_laps=laps)
            if corner and name in ("braking", "losing_time", "general", "compare", "setup"):
                return Intent(name if name != "general" else "corner", corner=corner)
            return Intent(name, corner=corner)
    if corner:
        return Intent("corner", corner=corner)
    return Intent("general")


SYSTEM_PROMPT = """You are an experienced Formula 1 race engineer and driver coach talking to your driver.
Rules (strict):
- Use ONLY the FACTS provided. Never invent numbers, corners, laps, setup values or conditions.
- Cite the fact IDs you used in square brackets, e.g. [F3]. Citations are removed before the driver sees or hears
  the answer: never mention fact IDs, "coaching observation" labels or confidence scores in your words.
- Every number you say must appear in the cited facts (you may round it). Do not compute new numbers.
- If the facts do not contain the answer, say exactly what data is missing.
- Be brief and radio-style: 1-3 short sentences unless the driver asks for detail.
- Corner names: use them exactly as the facts give them (official "Turn 10 (Red Bull Mobile)" where known,
  otherwise pitwall's own T-numbers from the speed trace).
- Setup questions: first check whether the facts point to technique (entry speed, braking point, brake
  release, throttle) before suggesting setup. Present any setup change as a single-variable experiment,
  not a guaranteed fix.
- If the facts say the data is SYNTHETIC, mention that briefly.
- If a fact says the game does not send some data, or that Pitwall does not read it, say so plainly; never
  estimate it.
- If the session fact says the driver is a beginner, use plain words and give one point at a time."""


@dataclass(slots=True)
class EngineerAnswer:
    text: str  # what the driver sees: no fact ids, labels or confidence scores (grounding.display_text)
    speech: str  # the same for TTS (the radio's text front-end turns units and lap times into words)
    intent: str
    corner: str | None
    facts: list[dict[str, Any]]
    grounded: bool | None
    fallback: bool
    model: str | None = None
    latency_ms: int = 0
    llm_attempts: int = 0
    grounding_issues: list[str] = field(default_factory=list)
    control: dict[str, Any] | None = None
    cited_text: str = ""  # the answer as grounded, with its [F12] citations (internal: audits, debugging)


class RaceEngineer:
    def __init__(self, provider: LLMProvider | None, max_tokens: int = 350, temperature: float = 0.2) -> None:
        self.provider = provider
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def answer(
        self, question: str, sheet: FactSheet, history: list[dict[str, str]] | None = None, use_llm: bool = True
    ) -> EngineerAnswer:
        t0 = time.perf_counter()
        intent = detect_intent(question)
        if intent.name in ("control_quiet", "control_resume"):
            return self._control(intent, t0)
        if intent.name == "radio_check":
            text = "Loud and clear. Radio check OK."
            return EngineerAnswer(
                text=text,
                speech=text,
                intent=intent.name,
                corner=None,
                facts=[],
                grounded=True,
                fallback=False,
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        facts = self._select(intent, sheet)
        det = deterministic_answer(intent, facts, sheet)
        # only data the game never sends / Pitwall does not read: a known fact, not something to explain
        capability = games.capability_only(intent.name, games.entry_of_sheet(sheet))
        if not use_llm or self.provider is None or capability:
            return self._finish(det, intent, facts, None, True, None, t0, 0, [])

        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in (history or [])[-4:]:
            messages.append({"role": "user" if h["role"] == "user" else "assistant", "content": h["text"]})
        messages.append({"role": "user", "content": f"FACTS:\n{FactSheet.render(facts)}\n\nDRIVER: {question}"})
        issues: list[str] = []
        attempts = 0
        model = None
        for _ in range(2):
            attempts += 1
            try:
                res = await self.provider.chat(messages, max_tokens=self.max_tokens, temperature=self.temperature)
            except LLMUnavailable as e:
                issues.append(f"llm unavailable: {e}")
                break
            model = res.model
            text = res.text.strip()
            g = check_grounding(text, facts)
            said = display_text(text, facts)  # an answer of citations alone says nothing to the driver
            if g.ok and said:
                return self._finish(text, intent, facts, g, False, model, t0, attempts, issues)
            issues.append(_describe(g) if said else "empty answer")
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role": "user",
                    "content": "That answer used numbers or citations not present in the FACTS ("
                    + _describe(g)
                    + "). Answer again using only numbers that appear in the cited facts.",
                }
            )
        return self._finish(det, intent, facts, None, True, model, t0, attempts, issues)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _select(intent: Intent, sheet: FactSheet) -> list[Fact]:
        topics = _TOPICS.get(intent.name, _TOPICS["general"])
        return sheet.select(topics, corner=intent.corner)

    def _control(self, intent: Intent, t0: float) -> EngineerAnswer:
        if intent.name == "control_quiet":
            laps = intent.quiet_laps
            text = f"Copy, radio quiet for {laps} laps." if laps else "Copy, radio quiet until you call me."
            control = {"action": "quiet", "laps": laps}
        else:
            text, control = "Copy, coaching back on.", {"action": "resume"}
        return EngineerAnswer(
            text=text,
            speech=text,
            intent=intent.name,
            corner=None,
            facts=[],
            grounded=True,
            fallback=False,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            control=control,
        )

    @staticmethod
    def _finish(
        text: str,
        intent: Intent,
        facts: list[Fact],
        g: GroundingResult | None,
        fallback: bool,
        model: str | None,
        t0: float,
        attempts: int,
        issues: list[str],
    ) -> EngineerAnswer:
        cited = set(g.cited) if g else set()
        used = [f for f in facts if f.id in cited] if cited else facts
        shown = display_text(text, facts)
        return EngineerAnswer(
            text=shown,
            speech=shown,
            intent=intent.name,
            corner=intent.corner,
            # "text" is what the LLM read (sources, audits); "plain" the same statement in the driver's words
            facts=[{"id": f.id, "topic": f.topic, "text": f.text, "plain": f.plain} for f in used],
            grounded=True if fallback else (g.ok if g else None),
            fallback=fallback,
            model=model,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            llm_attempts=attempts,
            grounding_issues=issues,
            cited_text=text,
        )


def _describe(g: GroundingResult) -> str:
    parts = []
    if g.ungrounded_numbers:
        parts.append("unsupported numbers: " + ", ".join(g.ungrounded_numbers))
    if g.unknown_citations:
        parts.append("unknown citations: " + ", ".join(g.unknown_citations))
    return "; ".join(parts) or "ok"


def deterministic_answer(intent: Intent, facts: list[Fact], sheet: FactSheet) -> str:
    """Template answers composed only from the facts' driver-facing sentences (``Fact.plain``), each followed by its
    citation, so the result is grounded by construction (``check_grounding`` accepts it). ``RaceEngineer`` shows the
    driver ``display_text`` of it: the same sentences without the citations."""

    def first(
        topic: str, corner: str | None = None, contains: str | None = None, group: str | None = None
    ) -> Fact | None:
        for f in facts:
            topic_ok = f.topic == topic and (corner is None or (f.corner or "").lower() in sheet.corners_for(corner))
            group_ok = group is None or f.data.get("group") == group
            if topic_ok and group_ok and (contains is None or contains in f.text):
                return f
        return None

    def say(*fs: Fact | None) -> str:
        chosen = list({f.id: f for f in fs if f is not None}.values())  # a fact said once (tyres: no wear fact)
        if not chosen:
            return "I don't have enough data for that yet - complete a few clean laps and ask again."
        return " ".join(f"{f.plain} [{f.id}]" for f in chosen)

    n = intent.name
    if n in ("ai_pace", "ai_level") and first("ai") is None:
        return NO_AI_COMPARISON  # not an F1 session against AI cars (or from before pace vs AI): laps would not help
    if n == "ai_pace":
        return say(first("ai", contains=AI_PACE_PREFIX))
    if n == "ai_level":
        return say(first("ai", contains=AI_LEVEL_PREFIX) or first("ai", contains=AI_PACE_PREFIX))
    game = first("game", group=n) if n in games.INTENT_FEATURES else None  # what this game never sends
    if n == "fuel":
        return say(first("fuel"), game)
    if n == "tyres":
        return say(first("tyres"), first("tyres", contains="surface temps"), game)
    if n == "strategy":
        return say(first("strategy"), first("fuel"), first("tyres"), game)
    # Deterministic branches that share facts (plan 4.5): weather, safety car, gaps, then goals, AI pace and technique.
    if n == "weather":
        # race strategy's weather and crossover facts; else what the game never sends; else the session fact (weather)
        weather = first("weather")
        if weather is not None:
            return say(weather, first("weather", contains="crossover"))
        return say(game) if game is not None else say(first("session"))
    if n == "safety_car":
        # race strategy's safety-car fact ("Safety car deployed ...", "Virtual safety car deployed ..."), else a flags
        # fact about it; a game that never sends flags is answered from its capability fact
        sc = first("strategy", contains="afety car") or first("flags", contains="afety car")
        if sc is not None:
            return say(sc)
        return say(game) if game is not None else say(first("session"))
    if n == "gaps":  # race strategy (pitwall.strategy)
        gap = first("gaps", contains="ahead") or first("gaps", contains="leading")
        if gap is not None or first("gaps") is not None:
            return say(gap, first("gaps", contains="behind"))
        return say(game) if game is not None else say(first("session"))
    general = (first("laps", contains="Best clean"), first("observations"))  # the answer before these intents
    if n == "ers":
        ers = first("ers")
        return say(ers, game) if ers is not None or game is not None else say(*general)
    if n == "sectors":
        if game is not None:
            return say(game)
        return say(first("laps", contains="Theoretical"), first("laps", contains="Best clean"))
    if n in ("damage", "flags"):
        # the game sends it but the sheet has no fact about it (F1 flags): the general answer, never "complete a
        # few clean laps" (more laps would not help)
        return say(game) if game is not None else say(*general)
    # --- feat/technique: racing line, technique and balance answers (before the generic corner branch) ---
    if n in ("line", "technique", "balance"):
        return _technique_answer(n, intent.corner, facts, sheet, first, say)
    # --- end feat/technique ---
    if n in ("corner", "braking", "losing_time", "setup") and intent.corner:
        obs = first("observations", corner=intent.corner)
        return say(first("corners", corner=intent.corner), obs or first("compare", corner=intent.corner))
    if n in ("losing_time", "braking"):
        return say(first("corners", contains="Biggest"), first("observations"))
    if n == "focus":
        obs = first("observations")
        return say(obs) if obs else say(first("corners", contains="Biggest"))
    if n == "goals":  # lane motivation: the goals reached / active (two at most), then this week
        goal_facts = [f for f in facts if f.topic == "goals"][:2]
        return say(*goal_facts, first("progress", contains="This week"))
    if n == "compare":
        return say(first("compare"), first("reference"))
    if n == "last_lap":
        last = first("laps", contains=LAST_LAP_PREFIX)
        lap = last.data.get("lap") if last is not None else None
        # the latest comparison only when it is about that same lap (it can lag a lap that was not comparable);
        # its per-corner facts belong to it, so the corner that cost the most on that lap comes with it
        comp = next((f for f in facts if f.topic == "compare" and lap is not None and f.data.get("lap") == lap), None)
        worst = None
        if comp is not None:
            # a corner lost to an incident (spin, contact, slow-down) is not technique: its observation says so,
            # and its braking / speed differences are not advice
            losses = [
                f
                for f in facts
                if f.topic == "compare" and not f.data.get("incident") and (f.data.get("time_delta_s") or 0.0) > 0.0
            ]
            worst = max(losses, key=lambda f: float(f.data["time_delta_s"]), default=None)
            if last is not None and comp.data.get("ref_lap") == last.data.get("best_lap"):
                comp = None  # the same lap pair as the last-lap fact's gap to the best: saying it twice is noise
        return say(last, comp, worst)
    if n == "lap_times":
        return say(
            first("laps", contains="Best clean"),
            first("laps", contains="personal best"),
            first("laps", contains="Theoretical"),
        )
    if n == "setup":
        diff = first("setup", contains="Driver's setup vs recommended")
        return "Before changing the setup, let's rule out technique. " + say(
            first("corners", contains="Biggest"),
            first("observations"),
            diff or first("setup", contains="Recommended") or first("setup", contains="Setup recommendation: none"),
            first("setup", contains="Something to test") if diff else None,
            first("balance", contains="Handling summary"),  # feat/technique (absent: no change)
            first("balance", contains="Setup to try"),  # feat/technique
            game,
        )
    if n == "summary":
        ai = first("ai", contains=AI_PACE_PREFIX)
        return say(
            first("laps", contains="Best clean"),
            first("laps", contains="personal best"),
            first("corners", contains="Biggest"),
            first("observations"),
            first("fuel"),
            ai if ai is not None and ai.data.get("status") == "ok" else None,  # only an actual comparison
        )
    return say(first("laps", contains="Best clean"), first("observations"))


# --- feat/technique --------------------------------------------------------------------------------------------
def _technique_answer(
    n: str,
    corner: str | None,
    facts: list[Fact],
    sheet: FactSheet,
    first: Callable[..., Fact | None],
    say: Callable[..., str],
) -> str:
    """Deterministic answers for the ``line``, ``technique`` and ``balance`` intents (``pitwall.technique.facts``)."""
    keys = sheet.corners_for(corner) if corner else set()

    def at_corner(topic: str, contains: str | None = None) -> list[Fact]:
        out = []
        for f in facts:
            if f.topic != topic or (contains is not None and contains not in f.text):
                continue
            listed = {str(c).lower() for c in f.data.get("corners", ()) if isinstance(c, str)}
            if (f.corner or "").lower() in keys or listed & keys:
                out.append(f)
        return out

    if n == "line":
        hit = at_corner("line")[:1] if corner else []
        return say(*hit) if hit else say(first("line", contains="Biggest line") or first("line"))
    if n == "technique":
        hit = at_corner("technique")[:2] if corner else []
        if hit:
            return say(*hit)

        # the session facts (no corner): a corner's technique fact can mention wheelspin too
        def session_fact(prefix: str) -> Fact | None:
            return next((f for f in facts if f.topic == "technique" and f.text.startswith(prefix)), None)

        return say(session_fact("Braking assist"), session_fact("Lock-ups"), session_fact("Wheelspin"))
    if corner:
        sym = [f for f in at_corner("balance") if "Setup to try" not in f.text]
        if sym:
            setup = at_corner("balance", contains="Setup to try")
            return say(sym[0], setup[0] if setup else None)
    return say(first("balance", contains="Handling summary"), first("balance", contains="Setup to try"))


# --- end feat/technique ---
