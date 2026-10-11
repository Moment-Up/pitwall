"""The AI race engineer: question -> intent -> relevant facts -> (LLM) -> grounding check -> answer.

* Intent detection is rule-based (instant, deterministic, works offline). Control commands such as
  "stop talking for a few laps" never reach the LLM.
* The LLM only rephrases/explains supplied facts. Answers whose numbers cannot be traced to the facts are
  retried once with feedback, then replaced by a deterministic answer built directly from the facts.
* If the LLM is unavailable the engineer still answers deterministically.
* Citations are bookkeeping: grounding checks the cited text (``EngineerAnswer.cited_text``), and the facts used
  are returned in ``EngineerAnswer.facts``. What the driver sees and hears (``text`` / ``speech``) never carries
  fact ids, observation labels or confidence scores (``grounding.display_text``).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pitwall.ai.facts import LAST_LAP_PREFIX, Fact, FactSheet
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
    ("fuel", re.compile(r"\b(fuel|petrol|gas|lift and coast)\b", re.I)),
    # race strategy (pitwall.strategy): only the wet-tyre and forecast words before tyres ("should I go on inters")
    ("weather", re.compile(r"\b(inters?|intermediates?|forecast)\b", re.I)),
    ("tyres", re.compile(r"\b(tyres?|tires?|wear|degradation|deg|grip|tyre temps?)\b", re.I)),
    (
        "strategy",
        re.compile(
            r"\b(pit|box|strategy|stop window|pit window|undercut|overcut|safety car|vsc|virtual safety car|"
            r"stay out|when should i (?:pit|stop|box))\b",
            re.I,
        ),
    ),
    (
        "setup",
        re.compile(
            r"\b(set ?up|wing|understeer|oversteer|balance|diff|differential|anti.?roll|arb|"
            r"ride height|camber|toe|suspension|brake bias|pressures?)\b",
            re.I,
        ),
    ),
    ("focus", re.compile(r"\b(one thing|work on|focus|improve|tip|advice|what should i)\b", re.I)),
    ("compare", re.compile(r"\b(compare|comparison|versus|vs|against my best|to my best|reference)\b", re.I)),
    ("braking", re.compile(r"\b(brak\w*|brake point|where should i brake)\b", re.I)),
    # "how was my last lap / that lap": the lap just driven, not the best one (checked before lap_times)
    ("last_lap", re.compile(r"\b(?:last|previous|latest|that|this) lap\b(?!\s*times\b)", re.I)),
    ("lap_times", re.compile(r"\b(lap ?times?|fastest|best lap|pace|how fast)\b", re.I)),
    ("summary", re.compile(r"\b(summary|summarise|summarize|debrief|how did (?:i|that) go|report)\b", re.I)),
    ("losing_time", re.compile(r"\b(losing time|lose time|where am i (?:slow|losing)|time loss|slow(?:er)?)\b", re.I)),
    # --- race strategy (pitwall.strategy): last, so they only take questions no rule above matched ("a good wet
    # setup" stays setup, "my pace in the wet" lap_times, "losing time to the car ahead" losing_time) ---
    ("weather", re.compile(r"\b(weather|rain(?:ing)?|wet|drying|track temp(?:erature)?)\b", re.I)),
    (
        "gaps",
        re.compile(
            r"\b(gap(?!\s+to\s+(?:my|the)\s+(?:best|reference|pb|personal))s?|interval|car (?:ahead|behind|in front)|"
            r"behind me|in front of me|how far (?:ahead|behind|back)|catching|drs|within a second|"
            r"(?:what|which) position am i|my (?:race )?position|race position|what place am i|p\d{1,2})\b",
            re.I,
        ),
    ),
    # --- end race strategy ---
]

_TOPICS: dict[str, set[str]] = {
    "fuel": {"session", "fuel", "strategy"},
    "tyres": {"session", "tyres", "strategy"},
    "strategy": {"session", "fuel", "tyres", "strategy", "gaps"},  # + gaps: race strategy (pitwall.strategy)
    "gaps": {"session", "gaps"},  # race strategy (pitwall.strategy)
    "weather": {"session", "weather", "tyres"},  # race strategy (pitwall.strategy)
    "setup": {"session", "corners", "observations", "compare", "setup"},
    "focus": {"session", "observations", "corners", "reference"},
    "compare": {"session", "compare", "reference", "laps"},
    "braking": {"session", "corners", "observations", "reference"},
    "lap_times": {"session", "laps", "reference"},
    "last_lap": {"session", "laps", "reference", "compare"},
    "summary": {"session", "laps", "corners", "observations", "fuel", "tyres"},
    "losing_time": {"session", "corners", "compare", "observations", "reference"},
    "corner": {"session", "reference"},
    "general": {"session", "laps", "corners", "observations", "reference", "fuel", "tyres"},
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
        if not use_llm or self.provider is None:
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

    def first(topic: str, corner: str | None = None, contains: str | None = None) -> Fact | None:
        for f in facts:
            topic_ok = f.topic == topic and (corner is None or (f.corner or "").lower() in sheet.corners_for(corner))
            if topic_ok and (contains is None or contains in f.text):
                return f
        return None

    def say(*fs: Fact | None) -> str:
        chosen = [f for f in fs if f is not None]
        if not chosen:
            return "I don't have enough data for that yet - complete a few clean laps and ask again."
        return " ".join(f"{f.plain} [{f.id}]" for f in chosen)

    n = intent.name
    if n == "fuel":
        return say(first("fuel"))
    if n == "tyres":
        return say(first("tyres"), first("tyres", contains="surface temps"))
    if n == "strategy":
        return say(first("strategy"), first("fuel"), first("tyres"))
    if n == "gaps":  # race strategy (pitwall.strategy)
        return say(
            first("gaps", contains="ahead") or first("gaps", contains="leading"), first("gaps", contains="behind")
        )
    if n == "weather":  # race strategy (pitwall.strategy)
        return say(first("weather"), first("weather", contains="crossover"))
    if n in ("corner", "braking", "losing_time", "setup") and intent.corner:
        obs = first("observations", corner=intent.corner)
        return say(first("corners", corner=intent.corner), obs or first("compare", corner=intent.corner))
    if n in ("losing_time", "braking"):
        return say(first("corners", contains="Biggest"), first("observations"))
    if n == "focus":
        obs = first("observations")
        return say(obs) if obs else say(first("corners", contains="Biggest"))
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
        )
    if n == "summary":
        return say(
            first("laps", contains="Best clean"),
            first("laps", contains="personal best"),
            first("corners", contains="Biggest"),
            first("observations"),
            first("fuel"),
        )
    return say(first("laps", contains="Best clean"), first("observations"))
