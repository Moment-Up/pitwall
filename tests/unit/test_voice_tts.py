"""Voice output: speech normalisation tables, the macOS ``say`` engine (fake and real), the Windows ``sapi`` engine
(mocked PowerShell everywhere, real SAPI on Windows) and the TTS factory."""

from __future__ import annotations

import base64
import json
import logging
import random
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall.config import Settings
from pitwall.voice import tts as tts_mod
from pitwall.voice.speech import number_words, to_speech
from pitwall.voice.tts import (
    NullTts,
    SapiTts,
    SapiVoice,
    SayTts,
    SayVoice,
    TtsError,
    build_tts,
    choose_sapi_voice,
    parse_sapi_voices,
    parse_say_voices,
)


# ---------------------------------------------------------------- number words
@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "zero"),
        (7, "seven"),
        (13, "thirteen"),
        (20, "twenty"),
        (29, "twenty-nine"),
        (100, "one hundred"),
        (105, "one hundred and five"),
        (342, "three hundred and forty-two"),
        (1000, "one thousand"),
        (1005, "one thousand and five"),
        (2350, "two thousand three hundred and fifty"),
        (1_000_000, "one million"),
        (-3, "minus three"),
    ],
)
def test_number_words(n: int, words: str) -> None:
    assert number_words(n) == words


# ---------------------------------------------------------------- speech normalisation tables
CITATIONS = [
    ("Brake earlier [F3].", "Brake earlier."),
    ("Brake earlier [F3][F12] into the hairpin.", "Brake earlier into the hairpin."),
    ("Brake earlier [F3, F4].", "Brake earlier."),
    ("Brake earlier ([F3]).", "Brake earlier."),
    ("[F1] Box this lap.", "Box this lap."),
    ("Fuel is fine [F2], tyres too [F5].", "Fuel is fine, tyres too."),
]

CORNERS = [
    ("T7", "turn 7"),
    ("Turn 7", "turn 7"),
    ("turn 7", "turn 7"),
    ("Turn7", "turn 7"),
    ("Losing time in T10.", "Losing time in turn 10."),
    ("T3-T5", "turns 3 to 5"),
    ("T3–5", "turns 3 to 5"),
    ("T3/T4 chicane", "turns 3 and 4 chicane"),
    ("T3 - T5", "turns 3 to 5"),
    ("T3 -0.2s", "turn 3 minus zero point two"),  # a delta, not a corner range
    ("T3 -5 m", "turn 3 minus 5 metres"),
    ("Return to the pits", "Return to the pits"),
]

LAP_TIMES = [
    ("1:05.626", "one oh five point six"),
    ("Best lap 1:29.45.", "Best lap one twenty-nine point five."),  # half-up, not banker's rounding
    ("1:05.95", "one oh six point zero"),  # rounding carries into the seconds
    ("1:59.96", "two oh oh point zero"),  # ... and into the minutes
    ("1:00.4", "one oh oh point four"),
    ("1:10.04", "one ten point zero"),
    ("0:45.123", "forty-five point one"),
    ("2:05", "two oh five"),
    ("1:05.626s", "one oh five point six"),
    ("Lap 3: 1:05.626 (clean)", "Lap 3: one oh five point six (clean)"),
    ("-1:02.3 to the leader", "minus one oh two point three to the leader"),
    ("3:75", "3:75"),  # not a time: seconds out of range
]

DELTAS = [
    ("+0.341s", "plus zero point three four"),
    ("-0.08 s", "minus zero point zero eight"),
    ("+0.345s", "plus zero point three five"),
    ("+0.300s", "plus zero point three"),
    ("-1.000s", "minus one"),
    ("+1.5s", "plus one point five"),
    ("+12.25 s", "plus twelve point two five"),
    ("+0.004s", "plus zero point zero zero four"),  # a real gap is never rounded to zero
    ("+0.005s", "plus zero point zero one"),
    ("±0.2s", "plus or minus zero point two"),
    ("+/-0.2s", "plus or minus zero point two"),
    ("\u22120.3s", "minus zero point three"),  # unicode minus sign
    ("+0.3 sec", "plus zero point three"),
    ("Gap -0.25s.", "Gap minus zero point two five."),
    ("T3 +0.341s, T5 -0.120s", "turn 3 plus zero point three four, turn 5 minus zero point one two"),
]

SIGNED = [
    ("+13 m", "plus 13 metres"),
    ("-3.2 km/h", "minus 3.2 k p h"),
    ("+0.7 laps", "plus 0.7 laps"),
    ("(+1.2 kg)", "(plus 1.2 kilos)"),
    ("+1 m", "plus 1 metre"),
    ("+5%", "plus 5 percent"),
    ("-2 clicks of brake bias", "minus 2 clicks of brake bias"),
    ("T3 –0.2s", "turn 3 minus zero point two"),  # an en dash used as a minus sign
    ("T3 –5 m", "turn 3 minus 5 metres"),
    ("+" + "9" * 27 + "s", "plus " + "9" * 27),  # beyond Decimal precision: said as written, never raises
]

UNITS = [
    ("13 m", "13 metres"),
    ("13m", "13 metres"),
    ("1 m", "1 metre"),
    ("1.0 m", "1.0 metres"),
    ("0.675s quicker", "0.675 seconds quicker"),
    ("1 s", "1 second"),
    ("250 km/h", "250 k p h"),
    ("250kph", "250 k p h"),
    ("12.3%", "12.3 percent"),
    ("1.65 kg", "1.65 kilos"),
    ("1 kg", "1 kilo"),
    ("95 C", "95 degrees"),
    ("95°C", "95 degrees"),
    ("95 °C", "95 degrees"),
    ("95\u2103", "95 degrees"),
    ("12° of lock", "12 degrees of lock"),
    ("150 ms", "150 milliseconds"),
    ("5.8 km", "5.8 kilometres"),
    ("11500 rpm", "11500 r p m"),
    ("23.5 psi", "23.5 p s i"),
    ("20 m/s", "20 metres per second"),
    ("1.65 kg/lap", "1.65 kilos per lap"),
    ("1,234 m", "1,234 metres"),
    ("between 60%-70% wear", "between 60 to 70 percent wear"),  # a range, not "60% minus 70%"
    ("20%–30%", "20 to 30 percent"),
    ("90°C-100°C", "90 to 100 degrees"),
    ("1.2s-1.5s", "1.2 to 1.5 seconds"),
]

WHEELS = [
    ("wear FL 12.3%, FR 13.4%", "wear front left 12.3 percent, front right 13.4 percent"),
    ("limited by the RL tyre", "limited by the rear left tyre"),
    ("RR 91 C", "rear right 91 degrees"),
    ("FL/FR temps", "front left and front right temps"),
]

MARKDOWN = [
    ("**Box this lap.**", "Box this lap."),
    ("Brake *earlier*.", "Brake earlier."),
    ("Brake _earlier_.", "Brake earlier."),
    ("__Box__ now", "Box now"),
    ("Check `T3`.", "Check turn 3."),
    ("## Summary\nBrake earlier into T3", "Summary. Brake earlier into turn 3"),
    (
        "Two things:\n- Brake 10 m earlier into T3\n- Carry speed through T5\n",
        "Two things: Brake 10 metres earlier into turn 3. Carry speed through turn 5",
    ),
    ("1. Brake earlier\n2. Turn in later", "Brake earlier. Turn in later"),
    ("> Box this lap", "Box this lap"),
    ("See [the data](https://example.com/x).", "See the data."),
    ("```\nBox box\n```", "Box box"),
    ("---\nBox", "Box"),
    ("*Note*: 3*2", "Note: 3*2"),  # deleting the star would say "32"
    ("lap 3*", "lap 3"),
]

SYMBOLS = [
    ("T3 vs T5", "turn 3 versus turn 5"),
    ("T3 vs. reference", "turn 3 versus reference"),
    ("~1.2 kg left", "about 1.2 kilos left"),
    ("≈3 laps", "about 3 laps"),
    ("≥ 3 laps", "at least 3 laps"),
    (">3 laps", "more than 3 laps"),
    ("<2 laps", "less than 2 laps"),
    ("T3 -> T5", "turn 3 to turn 5"),
    ("fuel & tyres", "fuel and tyres"),
    ("e.g. T3", "for example, turn 3"),
    ("brake point varies by 2.1 m (std dev)", "brake point varies by 2.1 metres (standard deviation)"),
    ("avg 1.65 kg", "average 1.65 kilos"),
    ("car #3", "car number 3"),
    ("Box box 🏁", "Box box"),  # say reads emoji names ("chequered flag")
    ("Great job ✅ T3 👍🏽", "Great job turn 3"),
    ("3️⃣ laps", "3 laps"),
    ("Box \ud83d now", "Box now"),  # lone surrogate from a split emoji escape
]

PUNCTUATION = [
    ("  Box   this\tlap  ", "Box this lap"),
    ("Box this lap .", "Box this lap."),
    ("", ""),
    ("   ", ""),
    ("Not enough data yet - complete a few laps.", "Not enough data yet, complete a few laps."),
    ("Not enough data — complete a few laps.", "Not enough data, complete a few laps."),
    ("sectors 21.123 / 22.456 / 22.047", "sectors 21.123, 22.456, 22.047"),
    ("laps 12-15.", "laps 12 to 15."),
    ("Turns 3-5 are the problem", "Turns 3 to 5 are the problem"),
    ("box in 2-3 laps", "box in 2 to 3 laps"),
    ("stint 12–15", "stint 12 to 15"),
]

# A dash is a range only when unspaced or with the same identifier kind on both ends; any other spaced dash is a
# pause. `say` drops a spaced dash, so "T4 - 13 m" was heard as "turn 413 metres" and an en dash read as a range.
DASHES = [
    ("T4 – 13 m earlier on the brakes", "turn 4, 13 metres earlier on the brakes"),
    ("T4 - 13 m earlier on the brakes", "turn 4, 13 metres earlier on the brakes"),
    ("Lap 12 – 14 laps to go", "Lap 12, 14 laps to go"),
    ("Lap 12 - 14 laps to go", "Lap 12, 14 laps to go"),
    ("T4 – 2 tenths", "turn 4, 2 tenths"),
    ("T12 – 3 laps in a row", "turn 12, 3 laps in a row"),
    ("Turn 3 - 5 laps", "turn 3, 5 laps"),
    ("box in 12 – 15 laps", "box in 12, 15 laps"),  # ambiguous with "Lap 12 – 14 laps": never invent a range
    ("Lap 3 — 1:05.626", "Lap 3, one oh five point six"),
    ("Gap - 0.3s", "Gap, 0.3 seconds"),  # say drops a spaced hyphen, so this was never heard as a minus
    ("T3 – T5", "turns 3 to 5"),
    ("T3 -T5", "turns 3 to 5"),
    ("laps 12 – 15", "laps 12 to 15"),
    ("Turns 3 - 5", "Turns 3 to 5"),
]

UNTOUCHED = [
    "F1 25 at Spa",
    "C3 compound",
    "f1_25 session",
    "lap 3 of 12",
    "2026-10-10",
    "P3 on the grid",
    "3 sectors",
    "5 laps old",
    "brake bias 56.5",
    "brake bias 56-44",  # a split, not a range
    "lap 5-6.5",
    "confidence 0.82",
    "2 * 3",
    "I'm in the pits",
]

FACT_SENTENCES = [
    (
        "Best clean lap this session: lap 3 in 1:05.626. [F2]",
        "Best clean lap this session: lap 3 in one oh five point six.",
    ),
    (
        "Lap 3: 1:05.626 (clean) sectors 21.123 / 22.456 / 22.047.",
        "Lap 3: one oh five point six (clean) sectors 21.123, 22.456, 22.047.",
    ),
    (
        "Theoretical best from best clean sectors: 1:04.951 (0.675s quicker than the best clean lap).",
        "Theoretical best from best clean sectors: one oh five point zero (0.675 seconds quicker than the best clean lap).",
    ),
    (
        "T3 (left-hander, apex at 345 m), average time vs reference +0.341s over 5 laps; brake point on average "
        "13 m earlier than reference; minimum speed -3.2 km/h vs reference (123 km/h) [F7]",
        "turn 3 (left-hander, apex at 345 metres), average time versus reference plus zero point three four over 5 "
        "laps; brake point on average 13 metres earlier than reference; minimum speed minus 3.2 k p h versus "
        "reference (123 k p h)",
    ),
    (
        "Fuel: using 1.65 kg per lap (median of 4 green laps); 12.3 kg in the tank, enough for 7.5 laps; margin to "
        "the finish +0.7 laps (+1.2 kg)",
        "Fuel: using 1.65 kilos per lap (median of 4 green laps); 12.3 kilos in the tank, enough for 7.5 laps; "
        "margin to the finish plus 0.7 laps (plus 1.2 kilos)",
    ),
    (
        "Current tyre surface temps FL 95 C, FR 96 C, RL 90 C, RR 91 C.",
        "Current tyre surface temps front left 95 degrees, front right 96 degrees, rear left 90 degrees, rear right "
        "91 degrees.",
    ),
    (
        "Lap 7 T4 vs reference: time -0.08 s, brake point +13 m (negative = earlier), min speed +2.5 km/h.",
        "Lap 7 turn 4 versus reference: time minus zero point zero eight, brake point plus 13 metres (negative = "
        "earlier), min speed plus 2.5 k p h.",
    ),
    (
        "**Box this lap.** You're losing +0.4s in T7 [F3, F4].",
        "Box this lap. You're losing plus zero point four in turn 7.",
    ),
]

ALL_CASES = (
    CITATIONS + CORNERS + LAP_TIMES + DELTAS + SIGNED + UNITS + WHEELS + MARKDOWN + SYMBOLS + PUNCTUATION + DASHES
) + FACT_SENTENCES


@pytest.mark.parametrize(("text", "spoken"), ALL_CASES)
def test_to_speech(text: str, spoken: str) -> None:
    assert to_speech(text) == spoken


@pytest.mark.parametrize("text", UNTOUCHED)
def test_to_speech_leaves_identifiers_and_plain_numbers_alone(text: str) -> None:
    assert to_speech(text) == text


@pytest.mark.parametrize("spoken", sorted({s for _, s in ALL_CASES}))
def test_to_speech_is_idempotent(spoken: str) -> None:
    assert to_speech(spoken) == spoken


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


@pytest.mark.parametrize(
    "text",
    [
        t
        for t, _ in CITATIONS + CORNERS + SIGNED + UNITS + WHEELS + SYMBOLS + PUNCTUATION + DASHES + FACT_SENTENCES
        if not re.search(r"\d:\d\d|[+\-–±\u2212]\d+(?:\.\d+)?\s?s\b|F\d|#\d", t)
    ]
    + UNTOUCHED,
)
def test_to_speech_preserves_every_number(text: str) -> None:
    """Outside lap times and time deltas (spelled out by design), every number survives digit-for-digit."""
    assert _NUM.findall(to_speech(text)) == _NUM.findall(text)


def test_to_speech_never_raises_and_always_encodes() -> None:
    """The hub builds the message from ``to_speech``: an exception there would lose the text as well as the audio."""
    pieces = [*"0123456789 .,:;+-–—±*_#>~[]()/%°CTFLRms\n", "km/h", "laps", "Lap ", "1:05.", "9" * 40, "**", "`"]
    pieces += ["🏁", "\ufe0f", "\u200d", "\ud83d", "\u2212", "[F3]", "e.g."]
    rng = random.Random(25)
    for _ in range(3000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
        out = to_speech(text)
        out.encode("utf-8")  # no lone surrogates left for the say text file or the JSON wire
        assert "\n" not in out and "  " not in out, (text, out)


def test_to_speech_output_is_plain_text() -> None:
    noisy = "## Plan\n- **T3**: brake +5 m earlier [F2]\n- `FL` at 102°C -> cool it\n> ~0.2s/lap"
    out = to_speech(noisy)
    assert not re.search(r"[*_`#>\[\]]|->|°|%|\s{2,}|\n", out), out
    assert (
        out
        == "Plan. turn 3: brake plus 5 metres earlier. front left at 102 degrees to cool it. about 0.2 seconds per lap"
    )


# ---------------------------------------------------------------- say voice listing
def test_parse_say_voices_handles_spaces_parentheses_and_numeric_regions() -> None:
    listing = "\n".join(
        [
            "Daniel              en_GB    # Hello! My name is Daniel.",
            "Bad News            en_US    # Hello! My name is Bad News.",
            "Eddy (English (UK)) en_GB    # Hello! My name is Eddy.",
            "Majed               ar_001   # مرحبًا! اسمي ماجد.",
            "",
            "garbage line without a locale",
        ]
    )
    assert parse_say_voices(listing) == [
        SayVoice("Daniel", "en_GB"),
        SayVoice("Bad News", "en_US"),
        SayVoice("Eddy (English (UK))", "en_GB"),
        SayVoice("Majed", "ar_001"),
    ]


# ---------------------------------------------------------------- SayTts against a fake `say` (macOS, Linux)
# The fake is a shebang script, which Windows cannot execute; SayTts itself only ever runs on macOS (build_tts uses
# SAPI on Windows), so the ``fake_say`` tests are skipped there rather than given a Windows-only launcher.
_FAKE_SAY = r'''#!@PYTHON@
"""Stand-in for macOS `say`: logs argv + the -f text, prints a voice list or writes a WAV per FAKE_SAY_MODE."""
import json, os, sys, time, wave

args = sys.argv[1:]
mode = os.environ.get("FAKE_SAY_MODE", "ok")
record = {"argv": args}
if "-f" in args:
    with open(args[args.index("-f") + 1], encoding="utf-8") as fh:
        record["text"] = fh.read()
with open(os.environ["FAKE_SAY_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\n")
if args[:2] == ["-v", "?"]:
    if mode == "list_fail":
        sys.exit(1)
    if mode == "list_binary":  # Latin-1 and a stray byte: not valid UTF-8 or ASCII
        sys.stdout.buffer.write("Am\u00e9lie             fr_CA    # Bonjour, je m'appelle Am\u00e9lie.\n".encode("latin-1"))
        sys.stdout.buffer.write(b"Broken \xff\xfe          en_US    # \x80\x81\n")
        sys.stdout.buffer.flush()
    print("Daniel              en_GB    # Hello! My name is Daniel.")
    print("Eddy (English (UK)) en_GB    # Hello! My name is Eddy.")
    sys.exit(0)
if mode == "fail":
    print("speech synthesis failed", file=sys.stderr)
    sys.exit(3)
if mode == "hang":
    time.sleep(30)
if mode == "no_output":
    sys.exit(0)
out = args[args.index("-o") + 1]
rate = int(next(a for a in args if a.startswith("--data-format=")).split("@")[1])
with wave.open(out, "wb") as w:
    w.setnchannels(2 if mode == "stereo" else 1)
    w.setsampwidth(2)
    w.setframerate(16000 if mode == "wrong_rate" else rate)
    w.writeframes(b"\x10\x00\xf0\xff" * (rate // 20))  # 0.1 s of a tiny square wave
'''


@pytest.fixture
def fake_say(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    if sys.platform == "win32":
        pytest.skip("macOS 'say' engine; the fake 'say' is a shebang script")
    script = tmp_path / "say"
    script.write_text(_FAKE_SAY.replace("@PYTHON@", sys.executable), encoding="utf-8")
    script.chmod(0o755)
    log = tmp_path / "say.log"
    monkeypatch.setenv("FAKE_SAY_LOG", str(log))
    monkeypatch.delenv("FAKE_SAY_MODE", raising=False)
    return str(script), log


def _calls(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _synth_calls(log: Path) -> list[dict[str, Any]]:
    return [c for c in _calls(log) if c["argv"][:2] != ["-v", "?"]]


def test_say_resolves_voice_case_insensitively_to_its_exact_name(fake_say: tuple[str, Path]) -> None:
    exe, _ = fake_say
    assert SayTts(voice="daniel", say_path=exe).voice == "Daniel"  # `say -v daniel` would silently fall back
    assert SayTts(voice="eddy (english (uk))", say_path=exe).voice == "Eddy (English (UK))"


def test_say_missing_voice_falls_back_to_system_default_with_warning(
    fake_say: tuple[str, Path], caplog: pytest.LogCaptureFixture
) -> None:
    exe, log = fake_say
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.tts"):
        engine = SayTts(voice="Nobody", say_path=exe)
    assert engine.voice is None
    assert "'Nobody' is not installed" in caplog.text
    assert "Daniel" in caplog.text  # lists what is available
    engine.synthesize("Box this lap.")
    assert "-v" not in _synth_calls(log)[-1]["argv"]


def test_say_voice_listing_failure_falls_back_to_default(
    fake_say: tuple[str, Path], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    exe, _ = fake_say
    monkeypatch.setenv("FAKE_SAY_MODE", "list_fail")
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.tts"):
        assert SayTts(voice="Daniel", say_path=exe).voice is None
    assert "cannot list" in caplog.text


@pytest.mark.parametrize("locale", ["C.UTF-8", "en_US.US-ASCII"])
def test_say_voice_listing_survives_undecodable_bytes(
    fake_say: tuple[str, Path], monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    """The real listing has sample text in every script; no locale may turn it into a construction failure."""
    exe, _ = fake_say
    monkeypatch.setenv("FAKE_SAY_MODE", "list_binary")
    monkeypatch.setenv("LC_ALL", locale)
    monkeypatch.setenv("LANG", locale)
    voices = tts_mod.list_say_voices(exe)
    assert SayVoice("Daniel", "en_GB") in voices
    assert any(v.locale == "fr_CA" for v in voices)
    assert SayTts(voice="Daniel", say_path=exe).voice == "Daniel"


def test_say_bad_executable_path_falls_back_to_default_voice(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.tts"):
        assert SayTts(voice="Daniel", say_path="say\x00").voice is None  # subprocess raises ValueError
    assert "cannot list" in caplog.text


def test_say_drops_lone_surrogates(fake_say: tuple[str, Path]) -> None:
    exe, log = fake_say
    SayTts(say_path=exe).synthesize("Box \ud83d now")  # UnicodeEncodeError before the fix
    assert _synth_calls(log)[-1]["text"] == "Box   now"


def test_say_staging_failure_raises_tts_error(fake_say: tuple[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    exe, _ = fake_say
    engine = SayTts(say_path=exe)

    def no_tempdir(*_: Any, **__: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tts_mod.tempfile, "TemporaryDirectory", no_tempdir)
    with pytest.raises(TtsError, match="No space left on device"):
        engine.synthesize("Box this lap.")


def test_say_passes_text_by_file_and_requests_wire_format(fake_say: tuple[str, Path]) -> None:
    exe, log = fake_say
    engine = SayTts(voice="Daniel", rate_wpm=210, sample_rate=24_000, say_path=exe)
    text = "-0.3 is the gap; --help is not an option here."
    clip = engine.synthesize(text)
    call = _synth_calls(log)[-1]
    argv = call["argv"]
    assert call["text"] == text
    assert all(text not in a for a in argv)  # never in argv, so a leading "-" cannot be read as a flag
    assert argv[:4] == ["-v", "Daniel", "-r", "210"]
    assert "--file-format=WAVE" in argv
    assert "--data-format=LEI16@24000" in argv
    assert clip.sample_rate == 24_000
    assert clip.n_samples == 24_000 // 10
    assert clip.pcm[:4] == b"\x10\x00\xf0\xff"


def test_say_neutralises_embedded_speech_commands(fake_say: tuple[str, Path]) -> None:
    exe, log = fake_say
    SayTts(say_path=exe).synthesize("[[volm 0]]Box this lap[[rate 50]]")
    sent = _synth_calls(log)[-1]["text"]
    assert "[[" not in sent and "]]" not in sent
    assert "Box this lap" in sent


@pytest.mark.parametrize("mode", ["ok", "fail"])
def test_say_removes_temp_files(fake_say: tuple[str, Path], monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    exe, log = fake_say
    engine = SayTts(say_path=exe)
    monkeypatch.setenv("FAKE_SAY_MODE", mode)
    if mode == "ok":
        engine.synthesize("Box this lap.")
    else:
        with pytest.raises(TtsError):
            engine.synthesize("Box this lap.")
    argv = _synth_calls(log)[-1]["argv"]
    text_file = Path(argv[argv.index("-f") + 1])
    wav_file = Path(argv[argv.index("-o") + 1])
    assert text_file.parent == wav_file.parent
    assert text_file.parent.name.startswith("pitwall-tts-")
    assert not text_file.parent.exists()


def test_say_empty_text_returns_empty_audio_without_running_say(fake_say: tuple[str, Path]) -> None:
    exe, log = fake_say
    engine = SayTts(say_path=exe)
    clip = engine.synthesize("  \n ")
    assert clip.pcm == b"" and clip.sample_rate == engine.sample_rate
    assert _synth_calls(log) == []


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("fail", "exited with 3: speech synthesis failed"),
        ("no_output", "no readable WAV"),
        ("stereo", "expected mono 16-bit 22050 Hz"),
        ("wrong_rate", "16000 Hz"),
    ],
)
def test_say_failures_raise_tts_error(
    fake_say: tuple[str, Path], monkeypatch: pytest.MonkeyPatch, mode: str, message: str
) -> None:
    exe, _ = fake_say
    engine = SayTts(say_path=exe)
    monkeypatch.setenv("FAKE_SAY_MODE", mode)
    with pytest.raises(TtsError, match=re.escape(message)):
        engine.synthesize("Box this lap.")


def test_say_timeout_raises_tts_error(fake_say: tuple[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    exe, _ = fake_say
    engine = SayTts(say_path=exe, timeout_s=0.5)
    monkeypatch.setenv("FAKE_SAY_MODE", "hang")
    with pytest.raises(TtsError, match=re.escape("timed out after 0.5 s")):
        engine.synthesize("Box this lap.")


def test_say_missing_binary_raises(tmp_path: Path) -> None:
    with pytest.raises(TtsError):
        SayTts(say_path=str(tmp_path / "no-such-say"), voice=None).synthesize("Box.")


@pytest.mark.parametrize(
    "kwargs", [{"rate_wpm": 0}, {"rate_wpm": 2000}, {"sample_rate": 4000}, {"sample_rate": 96_000}, {"timeout_s": 0}]
)
def test_say_rejects_bad_parameters(fake_say: tuple[str, Path], kwargs: dict[str, Any]) -> None:
    exe, _ = fake_say
    with pytest.raises(ValueError):
        SayTts(say_path=exe, **kwargs)


def test_say_warmup_never_raises(fake_say: tuple[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    exe, _ = fake_say
    engine = SayTts(say_path=exe)
    monkeypatch.setenv("FAKE_SAY_MODE", "fail")
    engine.warmup()


def test_null_tts_returns_empty_audio() -> None:
    engine = NullTts()
    clip = engine.synthesize("Box this lap.")
    assert engine.name == "none"
    assert clip.pcm == b"" and clip.sample_rate == 22_050 and clip.duration_s == 0.0


# ---------------------------------------------------------------- real macOS `say`
needs_say = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("say") is None, reason="macOS 'say' not available"
)


def _peak(pcm: bytes) -> int:
    return int(np.abs(np.frombuffer(pcm, dtype="<i2").astype(np.int32)).max())


@pytest.fixture(scope="module")
def real_say() -> SayTts:
    return SayTts(voice="Daniel", rate_wpm=200)


@pytest.mark.voice
@needs_say
def test_real_say_synthesises_plausible_speech(real_say: SayTts) -> None:
    speech = to_speech("T3 is costing you +0.341s [F4]. Brake 13 m earlier, minimum speed -3.2 km/h.")
    clip = real_say.synthesize(speech)
    assert clip.sample_rate == 22_050
    assert len(clip.pcm) > 0 and len(clip.pcm) % 2 == 0
    expected_s = len(speech.split()) / real_say.rate_wpm * 60
    assert 0.5 * expected_s < clip.duration_s < 2.0 * expected_s, (clip.duration_s, expected_s)
    assert _peak(clip.pcm) > 1000  # audible speech, not silence


@pytest.mark.voice
@needs_say
def test_real_say_reads_text_starting_with_a_dash(real_say: SayTts) -> None:
    clip = real_say.synthesize("-v ? is not a flag here")
    assert clip.duration_s > 0.5 and _peak(clip.pcm) > 1000


@pytest.mark.voice
@needs_say
def test_real_say_honours_rate() -> None:
    text = "Box this lap, box this lap. Confirm tyres."
    slow = SayTts(rate_wpm=150).synthesize(text)
    fast = SayTts(rate_wpm=300).synthesize(text)
    assert slow.duration_s > 1.3 * fast.duration_s


@pytest.mark.voice
@needs_say
def test_real_say_voice_validation() -> None:
    names = {v.name for v in tts_mod.list_say_voices()}
    assert SayTts(voice="NoSuchVoice123").voice is None
    if "Daniel" in names:
        assert SayTts(voice="daniel").voice == "Daniel"


# ---------------------------------------------------------------- factory
def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.mark.parametrize("engine", ["none", "None", "off", ""])
def test_build_tts_disabled(engine: str) -> None:
    tts = build_tts(_settings(tts_engine=engine))
    assert isinstance(tts, NullTts)


def test_build_tts_unknown_engine_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.tts"):
        tts = build_tts(_settings(tts_engine="kokoro9000"))
    assert isinstance(tts, NullTts)
    assert "unknown TTS engine" in caplog.text


def test_build_tts_off_macos_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod.sys, "platform", "linux")
    tts = build_tts(_settings(tts_engine="say"))
    assert isinstance(tts, NullTts)
    assert "macOS" in tts.reason


def test_build_tts_engine_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(**_: Any) -> SayTts:
        raise TtsError("say exploded")

    monkeypatch.setattr(tts_mod.sys, "platform", "darwin")
    monkeypatch.setattr(tts_mod, "SayTts", broken)
    tts = build_tts(_settings(tts_engine="say"))
    assert isinstance(tts, NullTts)
    assert tts.reason == "say exploded"


def test_build_tts_bad_rate_never_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod.sys, "platform", "darwin")
    assert isinstance(build_tts(_settings(tts_engine="say", tts_rate_wpm=5)), NullTts)


@pytest.mark.voice
@needs_say
def test_build_tts_uses_settings_on_macos() -> None:
    tts = build_tts(_settings(tts_engine="say", tts_voice="Daniel", tts_rate_wpm=180))
    assert isinstance(tts, SayTts)
    assert tts.rate_wpm == 180
    assert tts.sample_rate == 22_050
    names = {v.name for v in tts_mod.list_say_voices()}
    assert tts.voice == ("Daniel" if "Daniel" in names else None)


# ---------------------------------------------------------------- Windows SAPI engine against a mocked PowerShell
SAPI_VOICES = [
    {"name": "Microsoft David Desktop", "culture": "en-US", "gender": "Male"},
    {"name": "Microsoft Hazel Desktop", "culture": "en-GB", "gender": "Female"},
    {"name": "Microsoft Zira Desktop", "culture": "en-US", "gender": "Female"},
]


class FakePowerShell:
    """Stands in for ``subprocess.run`` of ``powershell.exe -EncodedCommand ...``: checks the call is shaped the
    way the real script expects, then writes the voice list or a WAV like System.Speech would."""

    def __init__(self) -> None:
        self.mode = "ok"  # ok | fail | no_output | stereo | wrong_rate | hang | oserror
        self.voices: Any = SAPI_VOICES
        self.calls: list[dict[str, Any]] = []

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        env = kw["env"]
        call = {"cmd": cmd, "env": env, "kw": kw}
        self.calls.append(call)
        if self.mode == "oserror":
            raise FileNotFoundError(2, "The system cannot find the file specified", cmd[0])
        if self.mode == "hang":
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])
        assert cmd[1:5] == ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand"]
        assert "System.Speech" in base64.b64decode(cmd[5]).decode("utf-16-le")
        assert kw["stdin"] is subprocess.DEVNULL and kw["capture_output"] is True and kw["check"] is False
        assert kw["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = Path(env["PWSAPI_OUT"])
        if env["PWSAPI_MODE"] == "list":
            if self.mode == "list_fail":
                Path(env["PWSAPI_ERR"]).write_text("Add-Type: cannot load System.Speech", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 3, b"", b"")
            out.write_text(json.dumps(self.voices), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        call["text"] = Path(env["PWSAPI_TEXT"]).read_text(encoding="utf-8")
        if self.mode == "fail":
            Path(env["PWSAPI_ERR"]).write_text("Cannot set voice. No matching voice is installed.", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 3, b"", b"#< CLIXML noise")
        if self.mode == "fail_stderr_only":
            return subprocess.CompletedProcess(cmd, 1, b"", b"powershell exploded")
        if self.mode == "no_output":
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        rate = int(env["PWSAPI_SAMPLE_RATE"])
        with wave.open(str(out), "wb") as w:
            w.setnchannels(2 if self.mode == "stereo" else 1)
            w.setsampwidth(2)
            w.setframerate(16000 if self.mode == "wrong_rate" else rate)
            w.writeframes(b"\x10\x00\xf0\xff" * (rate // 20))  # 0.1 s of a tiny square wave
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    def synth_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["env"].get("PWSAPI_MODE") == "speak"]


@pytest.fixture
def fake_ps(monkeypatch: pytest.MonkeyPatch) -> FakePowerShell:
    fake = FakePowerShell()
    monkeypatch.setattr(tts_mod.subprocess, "run", fake)
    return fake


PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def test_sapi_lists_voices_once_and_prefers_a_british_voice(fake_ps: FakePowerShell) -> None:
    engine = SapiTts(powershell=PS)
    assert engine.name == "sapi" and engine.voice == "Microsoft Hazel Desktop"
    assert [c["env"]["PWSAPI_MODE"] for c in fake_ps.calls] == ["list"]
    assert engine.installed_voices[0] == SapiVoice("Microsoft David Desktop", "en-US", "Male")
    assert fake_ps.calls[0]["cmd"][0] == PS


@pytest.mark.parametrize(
    ("wanted", "voice"),
    [
        ("Microsoft Zira Desktop", "Microsoft Zira Desktop"),
        ("microsoft david desktop", "Microsoft David Desktop"),  # case-insensitive, passed by its exact name
        ("zira", "Microsoft Zira Desktop"),  # a unique part is enough
        ("Desktop", "Microsoft Hazel Desktop"),  # ambiguous: falls back to the British voice
        ("Daniel", "Microsoft Hazel Desktop"),  # a macOS voice name means nothing here
    ],
)
def test_sapi_voice_choice(fake_ps: FakePowerShell, wanted: str, voice: str) -> None:
    assert SapiTts(voice=wanted, powershell=PS).voice == voice


def test_sapi_voice_choice_without_british_or_english_voices() -> None:
    us = [SapiVoice("Microsoft Zira Desktop", "en-US"), SapiVoice("Microsoft Hedda Desktop", "de-DE")]
    assert choose_sapi_voice(None, us) == "Microsoft Zira Desktop"  # English text needs an English voice
    assert choose_sapi_voice(None, [SapiVoice("Microsoft Hedda Desktop", "de-DE")]) is None  # system default
    assert choose_sapi_voice(None, []) is None


def test_sapi_missing_voice_warns_with_the_installed_english_voices(
    fake_ps: FakePowerShell, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.tts"):
        SapiTts(voice="Nobody", powershell=PS)
    assert "'Nobody' is not installed" in caplog.text and "Microsoft Hazel Desktop" in caplog.text


def test_sapi_voice_listing_failure_uses_the_system_default(
    fake_ps: FakePowerShell, caplog: pytest.LogCaptureFixture
) -> None:
    fake_ps.mode = "list_fail"
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.tts"):
        engine = SapiTts(voice="Hazel", powershell=PS)
    assert engine.voice is None and engine.installed_voices == []
    assert "cannot list Windows voices" in caplog.text and "System.Speech" in caplog.text


def test_parse_sapi_voices_tolerates_powershell_shapes() -> None:
    one = {"name": "Microsoft Zira Desktop", "culture": "en-US", "gender": "Female"}
    assert parse_sapi_voices(json.dumps(one)) == [SapiVoice("Microsoft Zira Desktop", "en-US", "Female")]
    assert parse_sapi_voices("") == [] and parse_sapi_voices("[]") == []
    assert parse_sapi_voices(json.dumps([{"name": ""}, {"culture": "en-GB"}, "x", one])) == [
        SapiVoice("Microsoft Zira Desktop", "en-US", "Female")
    ]
    with pytest.raises(TtsError):
        parse_sapi_voices("not json")


def test_sapi_passes_text_by_file_and_requests_wire_format(fake_ps: FakePowerShell) -> None:
    engine = SapiTts(voice="Hazel", rate=2, sample_rate=24_000, powershell=PS)
    text = "-0.3 is the gap; it's \"plus\" $(Remove-Item x) `n 'quoted' <speak>not SSML</speak>."
    clip = engine.synthesize(text)
    call = fake_ps.synth_calls()[-1]
    assert call["text"] == text  # verbatim, from the UTF-8 file
    assert all(text not in a for a in call["cmd"])  # never on the command line...
    assert all(text not in v for k, v in call["env"].items() if k.startswith("PWSAPI_"))  # ...nor in the env
    assert call["env"]["PWSAPI_VOICE"] == "Microsoft Hazel Desktop"
    assert (call["env"]["PWSAPI_RATE"], call["env"]["PWSAPI_SAMPLE_RATE"]) == ("2", "24000")
    assert clip.sample_rate == 24_000 and clip.n_samples == 24_000 // 10
    assert clip.pcm[:4] == b"\x10\x00\xf0\xff"


def test_sapi_system_default_voice_is_passed_as_empty(fake_ps: FakePowerShell) -> None:
    fake_ps.voices = [{"name": "Microsoft Hedda Desktop", "culture": "de-DE", "gender": "Female"}]
    engine = SapiTts(powershell=PS)
    engine.synthesize("Box this lap.")
    assert engine.voice is None and fake_ps.synth_calls()[-1]["env"]["PWSAPI_VOICE"] == ""


def test_sapi_text_is_utf8_and_drops_lone_surrogates(fake_ps: FakePowerShell) -> None:
    engine = SapiTts(powershell=PS)
    engine.synthesize("Eau Rouge \u2014 Ste. D\u00e9vote \ud83d now")
    assert fake_ps.synth_calls()[-1]["text"] == "Eau Rouge \u2014 Ste. D\u00e9vote   now"


def test_sapi_empty_text_returns_empty_audio_without_running(fake_ps: FakePowerShell) -> None:
    engine = SapiTts(powershell=PS)
    clip = engine.synthesize("  \n ")
    assert clip.pcm == b"" and clip.sample_rate == engine.sample_rate
    assert fake_ps.synth_calls() == []


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("fail", "exited with 3: Cannot set voice. No matching voice is installed."),
        ("fail_stderr_only", "exited with 1: powershell exploded"),
        ("no_output", "no readable WAV"),
        ("stereo", "expected mono 16-bit 22050 Hz"),
        ("wrong_rate", "16000 Hz"),
        ("hang", "timed out after 30 s"),
        ("oserror", "cannot run"),
    ],
)
def test_sapi_failures_raise_tts_error(fake_ps: FakePowerShell, mode: str, message: str) -> None:
    engine = SapiTts(powershell=PS)
    fake_ps.mode = mode
    with pytest.raises(TtsError, match=re.escape(message)):
        engine.synthesize("Box this lap.")


@pytest.mark.parametrize("mode", ["ok", "fail"])
def test_sapi_removes_temp_files(fake_ps: FakePowerShell, mode: str) -> None:
    engine = SapiTts(powershell=PS)
    fake_ps.mode = mode
    if mode == "ok":
        engine.synthesize("Box this lap.")
    else:
        with pytest.raises(TtsError):
            engine.synthesize("Box this lap.")
    env = fake_ps.synth_calls()[-1]["env"]
    text_file, wav_file = Path(env["PWSAPI_TEXT"]), Path(env["PWSAPI_OUT"])
    assert text_file.parent == wav_file.parent == Path(env["PWSAPI_ERR"]).parent
    assert text_file.parent.name.startswith("pitwall-tts-")
    assert not text_file.parent.exists()


def test_sapi_staging_failure_raises_tts_error(fake_ps: FakePowerShell, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = SapiTts(powershell=PS)

    def no_tempdir(*_: Any, **__: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tts_mod.tempfile, "TemporaryDirectory", no_tempdir)
    with pytest.raises(TtsError, match="No space left on device"):
        engine.synthesize("Box this lap.")


@pytest.mark.parametrize("kwargs", [{"rate": -11}, {"rate": 11}, {"sample_rate": 4000}, {"timeout_s": 0}])
def test_sapi_rejects_bad_parameters(fake_ps: FakePowerShell, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        SapiTts(powershell=PS, **kwargs)
    assert fake_ps.calls == []  # validated before any process runs


def test_sapi_without_powershell_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod, "find_powershell", lambda: None)
    with pytest.raises(TtsError, match="PowerShell"):
        SapiTts()


def test_find_powershell_prefers_system32(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = tmp_path / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path))
    monkeypatch.setattr(tts_mod.shutil, "which", lambda _name: r"C:\evil\powershell.exe")
    assert tts_mod.find_powershell() == str(exe)
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path / "missing"))
    assert tts_mod.find_powershell() == r"C:\evil\powershell.exe"  # only when System32 has none


def test_sapi_warmup_never_raises(fake_ps: FakePowerShell) -> None:
    engine = SapiTts(powershell=PS)
    fake_ps.mode = "fail"
    engine.warmup()


def test_sapi_diagnostics(fake_ps: FakePowerShell) -> None:
    d = SapiTts(powershell=PS).diagnostics()
    assert d["engine"] == "sapi" and d["voice"] == "Microsoft Hazel Desktop"
    assert "Microsoft Hazel Desktop (en-GB)" in d["installed_voices"] and d["powershell"] == PS


def test_sapi_script_is_the_encoded_command() -> None:
    encoded = tts_mod._encoded_command(tts_mod._SAPI_SCRIPT)
    assert base64.b64decode(encoded).decode("utf-16-le") == tts_mod._SAPI_SCRIPT
    assert "SetOutputToWaveFile" in tts_mod._SAPI_SCRIPT and "SpeakSsml" not in tts_mod._SAPI_SCRIPT


# ---------------------------------------------------------------- factory on Windows
@pytest.fixture
def windows_sapi(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """``sys.platform`` reads win32 and ``SapiTts`` is a recorder (no PowerShell needed on any OS)."""
    made: list[dict[str, Any]] = []

    class RecordingSapi:
        name = "sapi"

        def __init__(self, **kw: Any) -> None:
            made.append(kw)
            self.sample_rate = kw["sample_rate"]
            self.voice = kw.get("voice")

    monkeypatch.setattr(tts_mod, "SapiTts", RecordingSapi)
    monkeypatch.setattr(tts_mod.sys, "platform", "win32")
    return made


@pytest.mark.parametrize(
    ("engine", "rate"), [("kokoro", 24_000), ("kokoro-mlx", 24_000), ("say", 22_050), ("sapi", 22_050)]
)
def test_build_tts_uses_sapi_on_windows(windows_sapi: list[dict[str, Any]], engine: str, rate: int) -> None:
    tts = build_tts(_settings(tts_engine=engine, tts_sapi_voice="Hazel", tts_sapi_rate=-2))
    assert tts.name == "sapi" and tts.sample_rate == rate
    assert windows_sapi[-1] == {"voice": "Hazel", "rate": -2, "sample_rate": rate}


def test_build_tts_sapi_defaults_to_automatic_voice(windows_sapi: list[dict[str, Any]]) -> None:
    build_tts(_settings(tts_engine="kokoro", tts_voice="bm_fable"))  # a Kokoro voice is not a SAPI voice
    assert windows_sapi[-1]["voice"] is None and windows_sapi[-1]["rate"] == 0


def test_build_tts_sapi_failure_is_text_only_radio(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(**_: Any) -> SapiTts:
        raise TtsError("Windows PowerShell (powershell.exe) not found")

    monkeypatch.setattr(tts_mod, "SapiTts", broken)
    monkeypatch.setattr(tts_mod.sys, "platform", "win32")
    for engine in ("kokoro", "say", "sapi"):
        tts = build_tts(_settings(tts_engine=engine))
        assert isinstance(tts, NullTts) and "PowerShell" in tts.reason


def test_build_tts_sapi_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    said: list[dict[str, Any]] = []

    def fake_say(**kw: Any) -> NullTts:
        said.append(kw)
        return NullTts(name="say")

    monkeypatch.setattr(tts_mod, "SayTts", fake_say)
    monkeypatch.setattr(tts_mod.sys, "platform", "darwin")
    assert build_tts(_settings(tts_engine="sapi")).name == "say" and said[-1]["voice"] == "Daniel"
    monkeypatch.setattr(tts_mod.sys, "platform", "linux")
    tts = build_tts(_settings(tts_engine="sapi"))
    assert isinstance(tts, NullTts) and "macOS" in tts.reason


def test_sapi_settings_are_validated() -> None:
    with pytest.raises(ValueError):
        _settings(tts_sapi_rate=11)
    s = _settings()
    assert (s.tts_sapi_voice, s.tts_sapi_rate) == ("", 0)


# ---------------------------------------------------------------- real Windows SAPI (Windows only; CI runs it)
def _real_sapi_or_skip() -> SapiTts:
    if sys.platform != "win32":
        pytest.skip("Windows SAPI voices exist only on Windows")
    if tts_mod.find_powershell() is None:
        pytest.skip("Windows PowerShell not found")
    engine = SapiTts()
    if not engine.installed_voices:
        pytest.skip("no SAPI voice installed on this Windows machine")
    return engine


@pytest.fixture(scope="module")
def real_sapi() -> SapiTts:
    return _real_sapi_or_skip()


def test_real_sapi_synthesises_plausible_speech(real_sapi: SapiTts) -> None:
    speech = to_speech("T3 is costing you +0.341s [F4]. Brake 13 m earlier, minimum speed -3.2 km/h.")
    clip = real_sapi.synthesize(speech)
    assert clip.sample_rate == 22_050 and len(clip.pcm) > 0 and len(clip.pcm) % 2 == 0
    words = len(speech.split())
    assert words / 5.0 < clip.duration_s < words / 1.0, (clip.duration_s, words)  # 60-300 words per minute
    assert _peak(clip.pcm) > 1000  # audible speech, not silence


def test_real_sapi_reads_hostile_text_verbatim(real_sapi: SapiTts) -> None:
    for text in ("-v ? is not a flag here", 'it\'s "plus" $(Remove-Item x); <speak>not SSML</speak>'):
        clip = real_sapi.synthesize(text)
        assert clip.duration_s > 0.5 and _peak(clip.pcm) > 1000, text


def test_real_sapi_renders_the_requested_rate(real_sapi: SapiTts) -> None:
    fast = SapiTts(voice=real_sapi.voice, rate=6, sample_rate=24_000)
    clip = fast.synthesize("Box this lap, box this lap. Confirm tyres.")
    assert clip.sample_rate == 24_000 and clip.duration_s > 0.3
    slow = real_sapi.synthesize("Box this lap, box this lap. Confirm tyres.")
    assert slow.duration_s > 1.1 * clip.duration_s


def test_real_build_tts_on_windows_speaks_with_sapi() -> None:
    _real_sapi_or_skip()
    tts = build_tts(_settings(tts_engine="kokoro"))  # the default engine cannot run on Windows: SAPI takes over
    assert tts.name == "sapi"
    assert tts.synthesize("Radio check.").duration_s > 0.3
