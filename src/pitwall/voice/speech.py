"""Speech normalisation: engineer display text -> what the race engineer actually says on the radio.

Display text is written for the dashboard: fact citations (``[F12]``), corner ids (``T7``), lap times
(``1:05.626``), signed deltas (``+0.341s``), unit symbols (``km/h``, ``°C``), wheel codes (``FL``) and the odd
bit of markdown from the LLM. Read literally, a TTS engine says "bracket F twelve", "tee seven" and "one colon
zero five point six two six". ``to_speech`` rewrites those the way an engineer says them:

    "T3 +0.341s vs reference [F4]"        -> "turn 3 plus zero point three four versus reference"
    "Best lap 1:05.626, track 32 C"       -> "Best lap one oh five point six, track 32 degrees"
    "wear FL 12.3%, min speed -3.2 km/h"  -> "wear front left 12.3 percent, min speed minus 3.2 k p h"

Rules:

- **Numbers keep their meaning.** The only rounding is the conventional radio precision: lap times to a
  tenth and signed time deltas to hundredths, rounded half-up on the decimal digits as written (no float
  artefacts), and a non-zero delta is never rounded to zero ("+0.004s" -> "plus zero point zero zero four").
  Every other number stays as digits - TTS engines read digits correctly - with its sign spoken.
- **Time deltas drop the unit** ("+0.341s" -> "plus zero point three four"): on the radio a signed delta is
  seconds by convention. Other signed values keep theirs ("+13 m" -> "plus 13 metres").
- ``km/h`` becomes "k p h": the engineer's word, and ~12% shorter than "kilometres per hour" with
  ``say -v Daniel`` (2.47 s vs 2.80 s for a short sentence [measured]).
- **A dash is a range only when the text says so.** Unspaced (``T3-T5``, ``12–15``, ``laps 12-15``,
  ``60%-70%``), or spaced when both ends are marked as identifiers of one kind (``T3 - T5``, or a plural noun
  first: ``laps 12 – 15``). Any other spaced dash is punctuation and becomes a pause: LLM answers use it that
  way ("T4 – 13 m earlier", "Lap 12 – 14 laps to go"), and ``say`` drops it, so "box in 12 - 15 laps" is
  heard as "twelve fifteen laps" [measured, Parakeet transcript]. A hyphen or en dash attached to a number
  after a space is a minus sign ("T3 -0.2s", "T3 –0.2s").
- Rewrites are anchored on number and word boundaries, so identifiers such as ``F1``, ``f1_25``, ``C3`` and
  dates pass through untouched.
- Emoji and other pictographs are dropped: ``say`` reads their names ("chequered flag").
- Engine-neutral plain text (no ``say`` embedded commands); engine-specific escaping lives in the engine.

Pure function with precompiled patterns that never raises: thread-safe, ~0.1 ms for a long fact sentence.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

__all__ = ["number_words", "to_speech"]

_SMALL = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
)  # fmt: skip
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_SCALES = ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"))
_TENTH = Decimal("0.1")
_HUNDREDTH = Decimal("0.01")
_SIGN_WORDS = {"+": "plus", "-": "minus", "–": "minus", "±": "plus or minus"}


def number_words(n: int) -> str:
    """British English cardinal words: 7 -> "seven", 105 -> "one hundred and five", -3 -> "minus three"."""
    if n < 0:
        return "minus " + number_words(-n)
    if n < 20:
        return _SMALL[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f"-{_SMALL[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_SMALL[hundreds]} hundred" + (f" and {number_words(rest)}" if rest else "")
    value, scale = next((v, s) for v, s in _SCALES if n >= v)
    head, rest = divmod(n, value)
    words = f"{number_words(head)} {scale}"
    if rest:
        words += (" and " if rest < 100 else " ") + number_words(rest)
    return words


def _decimal_words(value: Decimal) -> str:
    """Non-negative decimal spoken digit by digit after the point: 0.34 -> "zero point three four"."""
    whole, _, frac = format(value, "f").partition(".")
    if not frac:
        return number_words(int(whole))
    return f"{number_words(int(whole))} point " + " ".join(_SMALL[int(c)] for c in frac)


def _delta_words(number: str) -> str:
    value = Decimal(number)
    try:
        rounded = value.quantize(_HUNDREDTH, ROUND_HALF_UP)
    except InvalidOperation:  # more digits than Decimal precision: not a real delta, so say it as written
        return number
    if rounded == 0 and value != 0:
        rounded = value  # a real (if tiny) gap must not be read out as "zero"
    return _decimal_words(rounded.normalize())


# --------------------------------------------------------------------------- unicode and markdown
_UNICODE = str.maketrans(  # minus sign, no-break / narrow / thin / figure spaces, degree look-alikes
    {
        "\u2212": "-",
        "\u00a0": " ",
        "\u202f": " ",
        "\u2009": " ",
        "\u2007": " ",
        "\u00ba": "°",
        "\u2103": "°C",
        "\u2109": "°F",
    }
)
_FENCE = re.compile(r"^[ \t]*```.*$", re.M)  # line patterns use [ \t] so they never eat a newline
_RULE = re.compile(r"^[ \t]*(?:[-*_][ \t]*){3,}$", re.M)
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.M)
_QUOTE = re.compile(r"^[ \t]*>+(?:[ \t]+|$)", re.M)  # ">3 laps" is a comparison, not a quote
_BULLET = re.compile(r"^[ \t]*(?:[-*+•]|\d{1,2}[.)])[ \t]+", re.M)
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_EM_STAR = re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])")
_EM_UNDERSCORE = re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")  # f1_25 stays intact
_STRIKE = re.compile(r"~~(.+?)~~")
_STRAY_MARKUP = re.compile(r"`+|(?<!\d )(?:(?<![\d*])\*++|(?<!\*)\*++(?!\d))(?! \d)")  # keep "2 * 3", "3*2"
_CITATION = re.compile(r"\s*\[\s*F\d+(?:\s*[,;/]\s*F?\d+)*\s*\]")


def _strip_markdown(text: str) -> str:
    for pattern in (_FENCE, _RULE, _HEADING, _QUOTE, _BULLET):
        text = pattern.sub("", text)
    # Lines become sentences so list items and headings get a pause instead of running together.
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    text = " ".join(line if i == len(lines) - 1 or line[-1] in ".!?;:," else line + "." for i, line in enumerate(lines))
    text = _LINK.sub(r"\1", text)
    text = _STRONG.sub(r"\2", text)
    text = _STRIKE.sub(r"\1", text)
    text = _EM_STAR.sub(r"\1", text)
    return _EM_UNDERSCORE.sub(r"\1", text)


# --------------------------------------------------------------------------- symbols and abbreviations
_SYMBOLS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\+/-"), "±"),
    (re.compile(r"\s*(?:->|→)\s*"), " to "),
    (re.compile(r"\s*&\s*"), " and "),
    (re.compile(r"≥\s*|(?<![\w<>=-])>=\s*(?=[\d+\-])"), "at least "),
    (re.compile(r"≤\s*|(?<![\w<>=-])<=\s*(?=[\d+\-])"), "at most "),
    (re.compile(r"(?<![\w<>=-])>\s*(?=[\d+\-])"), "more than "),
    (re.compile(r"(?<![\w<>=-])<\s*(?=[\d+\-])"), "less than "),
    (re.compile(r"(?:~|≈)\s*(?=[\d+\-])|≈"), "about "),
    (re.compile(r"±(?!\s*\d)"), "plus or minus"),
    (re.compile(r"#(?=\d)"), "number "),
    (re.compile(r"\bvs\b\.?"), "versus"),
    (re.compile(r"\be\.g\.,?", re.I), "for example,"),
    (re.compile(r"\bi\.e\.,?", re.I), "that is,"),
    (re.compile(r"\bapprox\b\.?"), "approximately"),
    (re.compile(r"\bavg\b\.?"), "average"),
    (re.compile(r"\bstd\.? dev\b\.?"), "standard deviation"),
)

# --------------------------------------------------------------------------- racing vocabulary
# "T3-T5", "T3-5", "T3–5", "T3 - T5", "T3 – T5"; never "T5 -0.12s" (a corner and a signed delta) or
# "T4 – 13 m" (a corner, a pause, a distance).
_CORNER_RANGE = re.compile(r"\bT(\d{1,2})(?:\s*[-–]\s*T|[-–])(\d{1,2})\b(?!\.\d)")
_CORNER_PAIR = re.compile(r"\bT(\d{1,2})\s*/\s*T?(\d{1,2})\b(?!\.\d)")
_CORNER = re.compile(r"\b(?:T|[Tt]urn\s*)(\d{1,2})\b")
_WHEELS = {"FL": "front left", "FR": "front right", "RL": "rear left", "RR": "rear right"}
_WHEEL = re.compile(r"\b(FL|FR|RL|RR)\b")
_WHEEL_PAIR = re.compile(r"\b(FL|FR|RL|RR)/(?=(?:FL|FR|RL|RR)\b)")  # "FL/FR temps"

# m:ss(.fff), optional sign and redundant "s"; seconds must be 00-59 so ratios and other noise are not misread.
_LAP_TIME = re.compile(r"(?<![\w.:+\-±])([+\-±]?)(\d{1,2}):([0-5]\d)(?:\.(\d+))?(?![\d:])(?:\s?s(?!\w))?")
# Integer ranges. An unspaced en dash always is one ("12–15"); an unspaced hyphen only next to a counted noun
# ("laps 12-15", "3-5 laps"), because "brake bias 56-44" is a split, not a range. A spaced dash only after a
# plural noun ("laps 12 – 15"): "Lap 12 – 14 laps to go" is a pause. Dates and decimals never match.
_RANGE_NOUN = r"(?i:laps?|turns?|corners?|sectors?)"
_RANGE_NOUNS = r"(?i:laps|turns|corners|sectors)"
_RANGE_END = r"(\d{1,3})(?![\w:\-–]|\.\d)"
_EN_DASH_RANGE = re.compile(rf"(?<![\w.:+\-–±])(\d{{1,3}})–{_RANGE_END}")
_NOUN_RANGE = re.compile(rf"\b(?:({_RANGE_NOUN}\s+\d{{1,3}})-|({_RANGE_NOUNS}\s+\d{{1,3}})\s*[-–]\s*){_RANGE_END}")
_RANGE_NOUN_AFTER = re.compile(rf"(?<![\w.:+\-–±])(\d{{1,3}})-(\d{{1,3}})(?=\s+{_RANGE_NOUN}\b)")


def _lap_time(m: re.Match[str]) -> str:
    sign, minutes, seconds, frac = m.group(1), int(m.group(2)), m.group(3), m.group(4)
    total = Decimal(minutes * 60) + Decimal(f"{seconds}.{frac}" if frac else seconds)
    tenths = int(total.quantize(_TENTH, ROUND_HALF_UP) * 10)  # rounding may carry into seconds and minutes
    mins, rest = divmod(tenths, 600)
    secs, tenth = divmod(rest, 10)
    if mins:
        secs_words = number_words(secs) if secs >= 10 else "oh " + ("oh" if secs == 0 else _SMALL[secs])
        words = f"{number_words(mins)} {secs_words}"
    else:
        words = number_words(secs)
    if frac:
        words += f" point {_SMALL[tenth]}"
    return f"{_SIGN_WORDS[sign]} {words}" if sign else words


# --------------------------------------------------------------------------- numbers with units
_UNIT_WORDS: dict[str, tuple[str, str]] = {  # symbol -> (plural, singular)
    "km/h": ("k p h", "k p h"),
    "kph": ("k p h", "k p h"),
    "mph": ("m p h", "m p h"),
    "m/s": ("metres per second", "metre per second"),
    "°C": ("degrees", "degree"),
    "°F": ("degrees Fahrenheit", "degree Fahrenheit"),
    "°": ("degrees", "degree"),
    "C": ("degrees", "degree"),
    "kg": ("kilos", "kilo"),
    "km": ("kilometres", "kilometre"),
    "ms": ("milliseconds", "millisecond"),
    "rpm": ("r p m", "r p m"),
    "psi": ("p s i", "p s i"),
    "%": ("percent", "percent"),
    "m": ("metres", "metre"),
    "secs": ("seconds", "second"),
    "sec": ("seconds", "second"),
    "s": ("seconds", "second"),
}
_SECONDS = frozenset({"s", "sec", "secs"})
# Longest symbols first so "km/h" wins over "km" and "m"; case-sensitive ("C" is Celsius, "m" is metres).
_UNIT = "|".join(re.escape(u) for u in sorted(_UNIT_WORDS, key=len, reverse=True))
# A sign never follows a value: "60%-70%" is a range (see _UNIT_RANGE), and "lap 5-6" is not "minus 6".
_SIGNED = re.compile(rf"(?<![\w.)\]%°])([+\-–±])(\d+(?:\.\d+)?)(?:\s?({_UNIT})(?!\w))?")
_UNSIGNED = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)\s?({_UNIT})(?!\w)")
# The same unit on both ends of an unspaced dash is a range: "60%-70%" -> "60 to 70 percent".
_UNIT_RANGE = re.compile(rf"(?<![\w.:+\-–±])(\d+(?:\.\d+)?)\s?({_UNIT})[-–](\d+(?:\.\d+)?)\s?\2(?!\w)")


def _unit_words(unit: str, number: str) -> str:
    plural, singular = _UNIT_WORDS[unit]
    return singular if number == "1" else plural


def _signed(m: re.Match[str]) -> str:
    sign, number, unit = m.group(1), m.group(2), m.group(3)
    if unit in _SECONDS:
        return f"{_SIGN_WORDS[sign]} {_delta_words(number)}"
    return f"{_SIGN_WORDS[sign]} {number}" + (f" {_unit_words(unit, number)}" if unit else "")


def _unsigned(m: re.Match[str]) -> str:
    return f"{m.group(1)} {_unit_words(m.group(2), m.group(1))}"


# --------------------------------------------------------------------------- punctuation
_PER_LAP = re.compile(r"\s*/\s*lap\b")
_SPACED_SLASH = re.compile(r"\s+/\s+")  # "sectors 21.1 / 22.4 / 22.0"
_SPACED_DASH = re.compile(r"\s+[-–—]+\s+|(?<=\w)—(?=\w)")  # ranges and signs are already words by now
_TIDY: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\s+"), " "),
    (re.compile(r"\(\s*\)"), ""),  # parentheses that only held citations
    (re.compile(r"\(\s+"), "("),
    (re.compile(r"\s+([.,;:!?)])"), r"\1"),
    (re.compile(r"([,;:])(?:\s*[,;:])+"), r"\1"),
    (re.compile(r"[,;:]\s*([.!?])"), r"\1"),
    (re.compile(r"\.(?:\s*\.)+"), "."),
    (re.compile(r"\s+"), " "),
)


# --------------------------------------------------------------------------- unspoken symbols
# Pictographs (category So, incl. emoji), lone surrogates (Cs: half of a split emoji escape), and the joiners,
# variation selectors, keycaps, skin tones and tags that build emoji sequences. Stripped last: "°" is So too.
_UNSPOKEN_CATEGORIES = frozenset({"So", "Cs"})
_EMOJI_PARTS = re.compile(r"[\u200d\ufe0e\ufe0f\u20e3\U0001f3fb-\U0001f3ff\U000e0020-\U000e007f]")


def _strip_symbols(text: str) -> str:
    if text.isascii():  # the common case costs one scan
        return text
    text = _EMOJI_PARTS.sub("", text)
    return "".join(" " if unicodedata.category(c) in _UNSPOKEN_CATEGORIES else c for c in text)


def to_speech(text: str) -> str:
    """Rewrite engineer display text as natural radio speech (see module docstring for the rules)."""
    text = text.translate(_UNICODE)
    text = _strip_markdown(text)
    text = _CITATION.sub("", text)
    for pattern, repl in _SYMBOLS:
        text = pattern.sub(repl, text)
    text = _CORNER_RANGE.sub(r"turns \1 to \2", text)
    text = _CORNER_PAIR.sub(r"turns \1 and \2", text)
    text = _CORNER.sub(r"turn \1", text)
    text = _LAP_TIME.sub(_lap_time, text)
    text = _UNIT_RANGE.sub(r"\1 to \3 \2", text)
    text = _EN_DASH_RANGE.sub(r"\1 to \2", text)
    text = _NOUN_RANGE.sub(lambda m: f"{m[1] or m[2]} to {m[3]}", text)
    text = _RANGE_NOUN_AFTER.sub(r"\1 to \2", text)
    text = _SIGNED.sub(_signed, text)
    text = _UNSIGNED.sub(_unsigned, text)
    text = _PER_LAP.sub(" per lap", text)
    text = _SPACED_SLASH.sub(", ", text)
    text = _SPACED_DASH.sub(", ", text)
    text = _WHEEL_PAIR.sub(r"\1 and ", text)
    text = _WHEEL.sub(lambda m: _WHEELS[m.group(1)], text)
    text = _STRAY_MARKUP.sub("", text)
    text = _strip_symbols(text)
    for pattern, repl in _TIDY:
        text = pattern.sub(repl, text)
    return text.strip(" ,;:")
