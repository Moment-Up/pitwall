"""How answers name driving techniques: the words the AI engineer's grounding check recognises as a technique claim
(spec: technique knowledge graph, section 3: "answers about technique cite only graph facts").

``TERMS`` maps each technique of the graph (and the causes Pitwall can name) to the phrasings that mean it ("heel and
toe", "rev-matching" and "blipping" all mean ``rev_match_downshift``). ``ai.grounding.check_grounding`` rejects an
answer that names one when none of the facts it cites (all facts when it cites none) is about that node - a fact
listing it in ``data["nodes"]`` (the technique knowledge facts, ``knowledge.facts``) or saying it in its own words. So
the engineer can explain trail braking to a trail-braking driver from the graph's facts, but cannot invent "try
heel-and-toe downshifts" for a paddle-shift car the facts never mention it for ("auto-blip", a paddle gearbox's
own blip, is not the driver's rev-matching).

``OTHER_TERMS`` are common coaching techniques the graph does not hold (threshold braking, a late apex ...): naming
one is accepted only when a supplied fact says it, never from the model's own knowledge.

``CAUSE_TERMS`` are the phrasings that name each cause of the graph - its name and the words an answer would use for it
("less grip", "wheelspin", "over-braking") - for the reason check only (``ai.grounding.reason_claims``): a cause a
supplied fact lists as not the reason (``data["not_the_reason"]``) must never be presented as why the fault happened.
They are broader than ``TERMS`` on purpose and never make a mention ungrounded by themselves.

Phrasings are case-insensitive regular expressions; a test keeps every key a technique or cause of the graph and
every graph technique listed, and every cause in ``CAUSE_TERMS`` with its own name recognised. Matching in ``TERMS`` is
deliberately narrow (distinctive phrases, not single common words), so an ordinary sentence about braking or the
throttle is never taken for a technique claim.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_RAW: Mapping[str, tuple[str, ...]] = {
    # --- techniques ---
    "flat_to_brake_marker": (r"\bflat(?: out)? (?:right )?(?:up )?to the brak\w* (?:marker|point|board)",),
    "fuel_save_lift_and_coast": (r"\blift[- ](?:and|&|n['’]?)[- ]coast\w*",),
    "fast_brake_attack": (r"\bbrake attack\b",),
    "progressive_brake_release": (
        r"\bprogressive(?:ly)? (?:brake )?releas\w*",
        r"\bbleed\w* (?:off )?the brake",
    ),
    "rev_match_downshift": (
        r"\bheel[- ](?:and|&|n)[- ]toe\w*",
        r"\brev[- ]?match\w*",
        # a blip of the throttle on a downshift; never "a blip of oversteer" or a paddle gearbox's own auto-blip
        r"(?<![\w-])blip\w* (?:the throttle|on (?:the|each|every|your) downshift\w*)",
        r"(?<!auto )(?<!auto-)\bthrottle blip\w*",
    ),
    "straight_line_braking": (r"\bstraight[- ]line brak\w*", r"\bbrak\w* in a straight line"),
    "consistent_brake_marker": (r"\bconsistent brak\w* (?:marker|point)s?",),
    "left_foot_braking": (r"\bleft[- ]foot(?:ed)?[- ]brak\w*",),
    "trail_braking": (r"\btrail[- ]?brak\w*",),
    "release_with_speed_to_spare": (r"\bspeed to spare\b",),
    "single_smooth_turn_in": (r"\bsaw\w* at the (?:steering )?wheel", r"\bone smooth turn[- ]in"),
    "coast_to_apex": (r"\bcoast\w* (?:in)?to the apex",),
    "throttle_at_rotation": (r"\bonce the car (?:has )?rotated\b",),
    "commit_throttle_no_lift": (r"\bcommit\w* to the throttle",),
    "unwind_with_throttle": (
        # unwinding the steering together with the throttle; "you unwind the steering" alone is no technique claim
        r"\bunwind\w*(?: the (?:steering|wheel|lock))? (?:with|as)(?: you)?(?: (?:add|apply|feed in|pick up|open|"
        r"squeeze)\w*)?(?: the)? throttle",
        r"\bthrottle as (?:you )?unwind\w*",
        r"\bopen\w* the steering as (?:you )?add\w* (?:the )?throttle",
    ),
    "use_track_width_exit": (
        r"\b(?:use|using|used) (?:all|the (?:full|whole) width) of the track",
        r"\b(?:use|using|used) all the track",
    ),
    # --- causes Pitwall names from measured signals ---
    "over_braking": (r"\bover-?brak\w*",),
    "early_turn_in": (r"\bearly turn[- ]in", r"\bturn\w* in (?:too )?early"),
    "waiting_for_rotation": (r"\bwait\w* for the car to (?:rotate|turn)",),
}
# Coaching techniques the graph does not hold: never claimed from the model's own knowledge.
_OTHER_RAW: tuple[str, ...] = (
    r"\bthreshold brak\w*",
    r"\blate[- ]apex\w*",
    r"\bdouble[- ]apex\w*",
    r"\bscandinavian flick",
    r"\bpower[- ]?slid\w*",
    r"\bhandbrake turn",
)

# Every cause: its TERMS (when it has some) and the other words that name it, for the reason check.
_CAUSE_RAW: Mapping[str, tuple[str, ...]] = {
    "over_braking": (r"\bbrak\w* (?:too much|too hard|more than (?:on )?(?:your|the) reference)",),
    "early_turn_in": (r"\bslowest point came (?:sooner|earlier)",),
    "low_grip": (
        r"\b(?:less|low|lower|lack of|short of|losing|lost|loss of) grip\b",
        r"\bslid\w* more\b",
        r"\bmore slid\w*",
        r"\bundersteer\w*",
        r"\block(?:ed|ing)?[- ]up\b|\block-?ups?\b|\bwheel locked\b",
    ),
    "traction_limited": (
        r"\btraction[- ]limited\b",
        r"\b(?:lack|short|loss) of traction\b",
        r"\bwheel ?spin\w*",
        r"\bwheels? spun\b",
        r"\boversteer\w*",
    ),
    "ready_earlier": (r"\bno grip loss\b", r"\bnothing (?:measured )?held (?:the|your) throttle back\b"),
    "early_brake_release": (
        r"\bearly brake release\b",
        r"\bbrak\w* ended (?:too )?(?:sooner|early|earlier)\b",
        r"\b(?:released?|releasing|off) the brakes? (?:too )?(?:early|soon|sooner|earlier)\b",
    ),
    "waiting_for_rotation": (r"\bwait\w* for (?:the car|it) to (?:rotate|turn)",),
    "carried_too_much_speed": (
        r"\bcarr(?:y|ied|ying) too much speed\b",
        r"\btoo (?:much speed|fast) (?:in|into|at)\b",
    ),
    "released_too_early_for_apex": (r"\breleas\w* (?:the brakes? )?too early for the apex\b",),
}

TERMS: Mapping[str, tuple[re.Pattern[str], ...]] = {
    k: tuple(re.compile(p, re.IGNORECASE) for p in v) for k, v in _RAW.items()
}
OTHER_TERMS: tuple[re.Pattern[str], ...] = tuple(re.compile(p, re.IGNORECASE) for p in _OTHER_RAW)
CAUSE_TERMS: Mapping[str, tuple[re.Pattern[str], ...]] = {
    k: tuple(re.compile(p, re.IGNORECASE) for p in (*_RAW.get(k, ()), *v)) for k, v in _CAUSE_RAW.items()
}
