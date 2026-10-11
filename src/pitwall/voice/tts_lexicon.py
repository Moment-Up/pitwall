"""Text front-end for the neural TTS worker (Kokoro + misaki G2P): what pitwall sends the worker to read.

``to_speech`` (voice/speech.py) has already turned display text into radio speech: lap times and deltas are
words, units are spelled out, citations are gone. This module does the engine-specific rest, deterministically
and before G2P (docs/research/tts-evaluation.md section 6.3):

- **Numbers become words** with pitwall's own British ``number_words`` ("105" -> "one hundred and five",
  "12.3" -> "twelve point three", "2nd" -> "second"). misaki would otherwise run them through num2words, which
  reads "105" as "one hundred five" and drops the "point" in "1:05.7".
- **Accents are folded** ("Sainte Dévote" -> "Sainte Devote"): misaki only looks up ASCII spellings, and the
  lexicon is keyed by the folded spelling.
- **Phrase rewrites** from the lexicon (``"130R"`` -> "one thirty R", ``"l'Eau Rouge"`` -> "Leau Rouge"), plus
  "&" -> "and" and a slash between names -> a pause.

The lexicon itself (``data/lexicon.json``, ``words``) is applied inside the worker: with the GPL espeak fallback
switched off, misaki *silently drops* every word it does not know - including common names such as "Paul",
"Russell" or "Ferrari" [measured]. ``known_names()`` lists every corner, track, team and driver name pitwall can
say; the opt-in ``pytest -m tts`` test runs them all through the real G2P and fails on any dropped word.

Pure functions, no I/O except reading the packaged lexicon once.
"""

from __future__ import annotations

import functools
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from pitwall.voice.speech import number_words

__all__ = [
    "DRIVER_NAMES",
    "EXTRA_NAMES",
    "GB_PHONEMES",
    "LEXICON_PATH",
    "Lexicon",
    "known_names",
    "load_lexicon",
    "prepare_text",
    "spell_numbers",
]

LEXICON_PATH = Path(__file__).resolve().parent / "data" / "lexicon.json"

# misaki's British phoneme inventory (misaki.en.GB_VOCAB, Apache-2.0): a lexicon entry may only use these.
GB_PHONEMES = frozenset("AIQWYabdfhijklmnpstuvwzðŋɑɒɔəɛɜɡɪɹʃʊʌʒʤʧˈˌːθᵊ")

# Names the engineer may say that are not in the track sheets or the F1 enums (driver names, other circuits and
# corners the evaluation saw dropped). Coverage is checked by the opt-in lexicon test.
DRIVER_NAMES = (
    "Max Verstappen", "Lewis Hamilton", "Charles Leclerc", "Lando Norris", "Oscar Piastri", "George Russell",
    "Carlos Sainz", "Fernando Alonso", "Lance Stroll", "Pierre Gasly", "Esteban Ocon", "Alex Albon",
    "Yuki Tsunoda", "Liam Lawson", "Nico Hulkenberg", "Gabriel Bortoleto", "Oliver Bearman", "Kimi Antonelli",
    "Isack Hadjar", "Franco Colapinto", "Jack Doohan", "Sergio Perez", "Valtteri Bottas", "Zhou Guanyu",
    "Kevin Magnussen", "Daniel Ricciardo", "Logan Sargeant", "Arvid Lindblad", "Sebastian Vettel",
    "Kimi Raikkonen", "Michael Schumacher", "Ayrton Senna", "Alain Prost", "Niki Lauda", "Nigel Mansell",
    "Jenson Button", "Nico Rosberg", "Mark Webber", "Felipe Massa", "Rubens Barrichello", "David Coulthard",
    "Mika Hakkinen", "Jacques Villeneuve", "Gilles Villeneuve", "Jacky Ickx", "Emerson Fittipaldi",
    "Nelson Piquet", "Jack Brabham", "Jackie Stewart", "Jim Clark", "James Hunt", "Mario Andretti", "Jean Alesi",
    "Gerhard Berger", "Robert Kubica", "Romain Grosjean", "Daniil Kvyat", "Stoffel Vandoorne",
    "Antonio Giovinazzi", "Nicholas Latifi", "Nyck de Vries", "Marcus Ericsson", "Juan Manuel Fangio",
    "Stirling Moss", "Jochen Rindt", "Ronnie Peterson", "Alan Jones", "Kamui Kobayashi", "Pastor Maldonado",
    "Paul di Resta", "Heikki Kovalainen", "Giancarlo Fisichella", "Juan Pablo Montoya",
)  # fmt: skip
EXTRA_NAMES = (
    "Eau Rouge", "Raidillon", "Nurburgring", "Nordschleife", "Laguna Seca", "Tsukuba", "Interlagos", "Le Mans",
    "Spa-Francorchamps", "Hockenheim", "Paul Ricard", "Portimao", "Kyalami", "Brands Hatch", "Donington",
    "Mugello", "Daytona", "Sebring", "Watkins Glen", "Lusail", "Yas Marina", "Marina Bay", "Albert Park",
    "Autodromo Hermanos Rodriguez", "Montmelo", "Lesmo", "Maggotts", "Becketts", "Mirabeau", "Loews",
    "Fairmont", "Massenet", "Kemmel", "Fagnes", "Tamburello", "Pirelli",
)  # fmt: skip

_FOLD = str.maketrans(
    {
        "ß": "ss", "ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ł": "l", "Ł": "L",
        "đ": "d", "Đ": "D", "ı": "i", "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"', "–": "-",
        "—": " - ", " ": " ",
    }
)  # fmt: skip
_QUOTED_LETTER = re.compile(r"""['"]([A-Za-z])['"]""")
_YEAR_APOSTROPHE = re.compile(r"(?<![\w'])'(?=\d\d\b)")  # "Ferrari '26" -> "Ferrari 26"
_SLASH = re.compile(r"(?<=[A-Za-z])\s*/\s*(?=[A-Za-z])")
_AMP = re.compile(r"\s*&\s*")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_ORDINAL = re.compile(r"(?<![\w.])(\d{1,4})(st|nd|rd|th)\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])(-)?(\d+)(?:\.(\d+))?(?![\w])")
_SPACES = re.compile(r"\s+")

_ORDINAL_WORDS = {
    "one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
    "twelve": "twelfth",
}  # fmt: skip
_DIGITS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


@dataclass(frozen=True, slots=True)
class Lexicon:
    words: dict[str, str] = field(default_factory=dict)  # folded word -> misaki phonemes (used by the worker)
    phrases: dict[str, str] = field(default_factory=dict)  # literal rewrite before G2P (used here)
    _phrase_re: re.Pattern[str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Lexicon:
        words = data.get("words") or {}
        phrases = data.get("phrases") or {}
        if not isinstance(words, dict) or not isinstance(phrases, dict):
            raise ValueError("lexicon 'words' and 'phrases' must be objects")
        w = {str(k): str(v) for k, v in words.items() if not str(k).startswith("_")}
        p = {str(k): str(v) for k, v in phrases.items() if not str(k).startswith("_")}
        rx = None
        if p:
            alts = "|".join(re.escape(k) for k in sorted(p, key=len, reverse=True))
            rx = re.compile(rf"(?<![\w'])(?:{alts})(?![\w'])")
        return cls(w, p, rx)

    def rewrite(self, text: str) -> str:
        if self._phrase_re is None:
            return text
        return self._phrase_re.sub(lambda m: self.phrases[m.group(0)], text)


@functools.cache
def load_lexicon(path: Path = LEXICON_PATH) -> Lexicon:
    """The packaged lexicon (cached). A missing or broken file gives an empty lexicon, never an exception."""
    try:
        return Lexicon.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Lexicon()


def fold_accents(text: str) -> str:
    """Latin accents and ligatures to ASCII ("Würth" -> "Wurth", "Junção" -> "Juncao"); typographic quotes
    and dashes to ASCII. Non-Latin scripts pass through."""
    text = text.translate(_FOLD)
    decomposed = unicodedata.normalize("NFKD", text)
    return unicodedata.normalize("NFC", "".join(c for c in decomposed if not unicodedata.combining(c)))


def _ordinal(n: int) -> str:
    words = number_words(n)
    head, sep, last = words.rpartition(" ")
    last_head, dash, unit = last.rpartition("-")
    if unit in _ORDINAL_WORDS:
        unit = _ORDINAL_WORDS[unit]
    elif unit.endswith("y"):
        unit = unit[:-1] + "ieth"
    else:
        unit += "th"
    return f"{head}{sep}{last_head}{dash}{unit}"


def _number(m: re.Match[str]) -> str:
    minus, whole, frac = m.group(1), m.group(2), m.group(3)
    # more than 12 digits is an identifier, not a quantity: digit by digit
    spoken = " ".join(_DIGITS[int(c)] for c in whole) if len(whole) > 12 else number_words(int(whole))
    if frac is not None:
        spoken += " point " + " ".join(_DIGITS[int(c)] for c in frac)
    return f"minus {spoken}" if minus else spoken


def spell_numbers(text: str) -> str:
    """Bare numbers to British words. Numbers glued to letters ("F1", "C3", "T7") are left to the G2P, which
    reads them letter + digit."""
    text = _THOUSANDS.sub("", text)
    text = _ORDINAL.sub(lambda m: _ordinal(int(m.group(1))), text)
    return _NUMBER.sub(_number, text)


def prepare_text(text: str, lexicon: Lexicon | None = None) -> str:
    """Speech text (``to_speech`` output) -> what the Kokoro worker reads. Never raises."""
    lex = load_lexicon() if lexicon is None else lexicon
    text = lex.rewrite(fold_accents(text))
    text = _QUOTED_LETTER.sub(r"\1", text)
    text = _YEAR_APOSTROPHE.sub("", text)
    text = _AMP.sub(" and ", text)
    text = _SLASH.sub(", ", text)
    text = spell_numbers(text)
    return _SPACES.sub(" ", text).strip()


def known_names() -> list[str]:
    """Every corner, layout, track, team and driver name pitwall knows (for the lexicon coverage test)."""
    from pitwall.adapters.f1.enums import TEAMS, TRACKS

    names: set[str] = set(DRIVER_NAMES) | set(EXTRA_NAMES) | set(TRACKS.values()) | set(TEAMS.values())
    try:
        from pitwall.analysis.track_identity import load_sheets

        for sheet in load_sheets("f1"):
            names.add(sheet.layout)
            for turn in sheet.turns:
                names.update(n.text for n in turn.names)
    except Exception:  # broken sheets are the track-identity tests' business
        pass
    return sorted(names)
