"""Radio commands of the rig validation kit: parsing and reply texts (pure, deterministic).

The radio hub asks ``ValidationKit.voice_command`` before the engineer; only a full match of one of these patterns
on the normalised text is a command, so ordinary questions ("where should I brake in turn 3", "start talking",
"give me a report") always reach the engineer. Replies are British English, at most 25 words, numbers as digits
(the hub's ``to_speech`` reads them).
"""

from __future__ import annotations

import re
from typing import Literal

Command = Literal["start", "next", "worked", "didnt", "status", "finish"]

FILLERS = frozenset({"ok", "okay", "right", "engineer", "pitwall", "radio", "please"})
_PUNCT = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")

PATTERNS: tuple[tuple[Command, re.Pattern[str]], ...] = (
    ("start", re.compile(r"(start|begin) (a )?(validation|validation run|rig test|test run)")),
    ("next", re.compile(r"(next|skip)( the| this)? (test|check)")),
    ("worked", re.compile(r"(it|that|test)? ?(worked|passed)")),
    ("didnt", re.compile(r"(it|that|test)? ?(didnt work|did not work|failed)")),
    (
        "status",
        re.compile(r"(whats|what is) the (test|current test)|repeat (the )?(test|instructions)|validation status"),
    ),
    ("finish", re.compile(r"(finish|stop|end) (the )?validation")),
)

NO_RUN = "No validation running. Say start validation."


def normalise(text: str) -> str:
    """Lower case, no punctuation ("didn't" -> "didnt"), single spaces, leading fillers and a trailing "please"
    dropped."""
    t = _PUNCT.sub("", text.lower().replace("’", "'"))
    words = _SPACES.sub(" ", t).strip().split(" ")
    while words and words[0] in FILLERS:
        words.pop(0)
    while words and words[-1] == "please":
        words.pop()
    return " ".join(w for w in words if w)


def parse_command(text: str) -> Command | None:
    t = normalise(text)
    if not t:
        return None
    for cmd, pat in PATTERNS:
        if pat.fullmatch(t):
            return cmd
    return None


def first_sentence(text: str) -> str:
    return text.split(". ", 1)[0].rstrip(".")


def brief_body(radio_brief: str) -> str:
    """'Validation: braking calls. Three laps...' -> 'braking calls. Three laps...' (for 'First test: ...')."""
    return radio_brief.split(": ", 1)[1] if radio_brief.startswith("Validation: ") else radio_brief


def started(first_brief: str | None) -> str:
    if first_brief is None:
        return "Validation started. No test is available on this server."
    return f"Validation started. First test: {brief_body(first_brief)}"


def already_running(short: str | None) -> str:
    return f"Validation is already running. Current test: {short}." if short else "Validation is already running."


def next_test(brief: str | None) -> str:
    if brief is None:
        return "That was the last test. Say finish validation, or tap Finish on the iPad."
    return f"Next test: {brief_body(brief)}"


def marked(short: str, worked: bool) -> str:
    if worked:
        return f"Marked {short} as worked."
    return f"Marked {short} as didn't work. Add a note on the iPad when you stop."


def status(index: int, total: int, short: str, first_reason: str | None) -> str:
    base = f"Test {index} of {total}: {short}."
    if not first_reason:
        return base
    reason = first_sentence(first_reason)
    words = (base + " " + reason + ".").split()
    return " ".join(words[:25]) if len(words) > 25 else f"{base} {reason}."


def finished(worked: int, didnt: int, review: int) -> str:
    return f"Validation finished. {worked} worked, {didnt} didn't, {review} to review. Report saved."


def verdict_prompt(short: str, verdict: str) -> str:
    """Proactive prompt when an item's automatic verdict first turns pass or fail (spec 6.5)."""
    what = "enough data" if verdict == "pass" else "something looks wrong"
    return f"{short[:1].upper()}{short[1:]}: {what}. Say worked or didn't work, or tap on the iPad."
