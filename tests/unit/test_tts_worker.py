"""Natural radio voice: the Kokoro worker protocol, ``WorkerTts`` (against a fake worker that emits a sine),
the text front-end and lexicon, audio post-processing, the spoken-number check and the hub's use of all of it.

Nothing here needs the real worker venv; the real engine is covered by the opt-in ``pytest -m tts`` tests in
tests/voice/.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import random
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import FactSheet
from pitwall.config import Settings
from pitwall.core.live import LiveState
from pitwall.voice import audio_post
from pitwall.voice import tts as tts_mod
from pitwall.voice.factory import load_voice_choice, save_voice_choice
from pitwall.voice.hub import CUE_OUTPUT_ALLOWANCE_S, DELIVERY_LEAD_S, RadioClient, RadioHub
from pitwall.voice.scheduler import SPEECH_LATENCY_S
from pitwall.voice.speech import to_speech
from pitwall.voice.tts import (
    KOKORO_SAMPLE_RATE,
    KOKORO_VOICES,
    NullTts,
    TtsError,
    WorkerTts,
    build_tts,
    speech_mismatch,
    spoken_numbers,
)
from pitwall.voice.tts_lexicon import (
    GB_PHONEMES,
    LEXICON_PATH,
    Lexicon,
    fold_accents,
    known_names,
    load_lexicon,
    prepare_text,
    spell_numbers,
)
from pitwall.voice.tts_worker import (
    GAP_CLAUSE_S,
    GAP_SENTENCE_S,
    GAP_WORDS_S,
    HEADER,
    MAX_SEGMENT_CHARS,
    MIN_SEGMENT_CHARS,
    choose_voice,
    gap_after,
    quiet_cut,
    read_frame,
    segment_text,
    split_long,
    split_sentences,
    split_words,
    trim_edges,
    write_frame,
    write_json,
)
from pitwall.voice.types import AudioClip, DrivingState, MessageKind, Priority, RadioMessage, SttResult, SynthResult

SR = KOKORO_SAMPLE_RATE


def tone(seconds: float, dbfs: float = -20.0, freq: float = 220.0, rate: int = SR) -> np.ndarray:
    t = np.arange(round(seconds * rate)) / rate
    return (10 ** (dbfs / 20) * math.sqrt(2) * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def clip_of(x: np.ndarray, rate: int = SR) -> AudioClip:
    return AudioClip(np.clip(np.round(x * 32767), -32768, 32767).astype("<i2").tobytes(), rate)


def silence(seconds: float, rate: int = SR) -> np.ndarray:
    return np.zeros(round(seconds * rate))


# ============================================================================================ framing
def test_frames_round_trip_and_eof() -> None:
    buf = io.BytesIO()
    write_json(buf, b"H", {"id": "r1", "sample_rate": SR})
    write_frame(buf, b"A", b"\x01\x00\x02\x00")
    write_frame(buf, b"E", b"{}")
    buf.seek(0)
    kind, payload = read_frame(buf) or ("", b"")
    assert kind == "H" and json.loads(payload) == {"id": "r1", "sample_rate": SR}
    assert read_frame(buf) == ("A", b"\x01\x00\x02\x00")
    assert read_frame(buf) == ("E", b"{}")
    assert read_frame(buf) is None  # clean EOF
    truncated = io.BytesIO(HEADER.pack(b"A", 10) + b"abc")
    assert read_frame(truncated) is None  # EOF inside a frame


def test_malformed_frame_header_raises() -> None:
    with pytest.raises(ValueError):
        read_frame(io.BytesIO(b"Z\x01\x00\x00\x00x"))
    with pytest.raises(ValueError):
        read_frame(io.BytesIO(HEADER.pack(b"A", 1 << 30)))


def test_short_sentences_are_merged_before_synthesis() -> None:
    assert segment_text("Box, box. Box this lap for mediums.") == ["Box, box. Box this lap for mediums."]
    assert segment_text("Copy.") == ["Copy."]
    assert segment_text("Push now, the gap is closing. Copy.") == ["Push now, the gap is closing. Copy."]
    long = " ".join(f"Sentence number {i} is long enough to stand on its own." for i in range(12))
    segs = segment_text(long)
    assert len(segs) > 1 and all(len(s) <= MAX_SEGMENT_CHARS for s in segs)
    assert all(len(s) >= MIN_SEGMENT_CHARS for s in segs)
    assert " ".join(segs) == " ".join(long.split())
    # a short second sentence stays with the first: alone, Kokoro says it slowly (the evaluation's phrase 3)
    p3 = "Turn two: you're braking about thirteen metres earlier than your reference. That's costing you three tenths."
    assert segment_text(p3) == [p3]
    assert split_sentences("One. Two! Three? Four") == ["One.", "Two!", "Three?", "Four"]
    assert segment_text("   ") == []


def test_long_sentences_are_split_so_no_call_grows_with_the_text() -> None:
    # one run-on sentence (an LLM answer): split at clauses, then between words - never one huge call
    base = "you are braking a little early into the hairpin and losing time on the exit because the rear steps out"
    run_on = ((base + " and ") * 14)[:1400].rsplit(" ", 1)[0] + "."
    segs = segment_text(run_on)
    assert len(segs) >= 14 and max(map(len, segs)) <= MAX_SEGMENT_CHARS + MIN_SEGMENT_CHARS
    assert " ".join(segs) == run_on  # nothing lost or reordered
    assert sum(s.split()[0] in ("and", "into", "because") for s in segs[1:]) >= len(segs) // 2  # natural cuts
    clauses = "Fuel is fine, plus zero point four laps; tyres look good: the front left is the limit, " * 3
    segs = segment_text(clauses.strip())
    assert max(map(len, segs)) <= MAX_SEGMENT_CHARS + MIN_SEGMENT_CHARS
    assert all(s.endswith((",", ";", ":", ".")) for s in segs)  # cut after clause punctuation, not mid-clause
    assert split_long("Short sentence.") == ["Short sentence."]
    pieces = split_words("word " * 60, max_chars=100)
    assert len(pieces) == 3 and max(map(len, pieces)) - min(map(len, pieces)) <= 10  # even, not 100/100/99
    assert split_words("x" * 150, 100) == ["x" * 150]  # one word longer than the limit stays whole
    # a short tail still joins its neighbour (Kokoro is unstable on very short inputs)
    assert all(len(s) >= MIN_SEGMENT_CHARS for s in segment_text(run_on + " Copy."))
    # adversarial input never makes a call longer than a full segment plus a merged short piece
    rng = random.Random(7)
    words = [
        "turn",
        "brake",
        "earlier",
        "Verstappen",
        "Maggotts",
        "Becketts",
        "Parabolica",
        "Interlagos",
        "gap",
        "push",
        "and",
    ]
    for _ in range(300):
        text = " ".join(rng.choice(words) for _ in range(rng.randint(1, 80))) + ", one hundred point two."
        segs = segment_text(text)
        assert " ".join(segs) == text and max(map(len, segs)) < MAX_SEGMENT_CHARS + MIN_SEGMENT_CHARS


def test_inner_segment_edges_are_trimmed_to_a_natural_gap() -> None:
    rate = 24_000
    x = np.concatenate([silence(0.3), tone(1.0, -20.0), silence(0.6)])  # Kokoro-like padding at both ends
    y = trim_edges(x, rate, 0.15, 0.05)
    assert len(y) / rate == pytest.approx(0.15 + 1.0 + 0.05, abs=0.006)
    assert abs(y[0]) < 1e-6 and abs(y[-1]) < 1e-6  # faded where it was cut
    assert len(trim_edges(x, rate, None, 0.1)) / rate == pytest.approx(0.3 + 1.0 + 0.1, abs=0.006)
    assert len(trim_edges(x, rate, None, None)) == len(x)
    assert len(trim_edges(silence(0.5), rate, 0.1, 0.1)) == round(0.5 * rate)  # no speech: unchanged
    assert gap_after("Box this lap.") == GAP_SENTENCE_S and gap_after('He said "go."') == GAP_SENTENCE_S
    assert gap_after("Fuel is fine,") == GAP_CLAUSE_S and gap_after("then the rear") == GAP_WORDS_S


def test_choose_voice_falls_back_instead_of_failing() -> None:
    have = ["af_heart", "bf_emma", "bm_fable", "bm_george"]
    assert choose_voice("bf_emma", have) == "bf_emma"
    assert choose_voice("bm_fabel", have) == "bm_fable"  # a typo in the settings
    assert choose_voice("bm_fable", ["af_heart", "bf_emma"]) == "bf_emma"  # no default: first British voice
    assert choose_voice("x", ["af_heart"]) == "af_heart"
    with pytest.raises(ValueError):
        choose_voice("bm_fable", [])


def test_quiet_cut_lands_in_the_pause_between_words() -> None:
    rate = 24_000
    word, pause, nxt = tone(0.4, -20.0), silence(0.12), tone(0.3, -20.0, 300.0)
    x = np.concatenate([word, pause, nxt])
    # Kokoro's timings are coarse: the cut is found in the quiet run near them, not at them
    cut = quiet_cut(x, rate, word_end_s=0.38, next_start_s=0.54)
    assert 0.4 * rate < cut < 0.52 * rate
    cut = quiet_cut(x, rate, word_end_s=0.43, next_start_s=0.50)
    assert 0.4 * rate < cut < 0.52 * rate
    # no pause at all (the voice ran the words together): the quietest point of the gap
    joined = np.concatenate([tone(0.4, -20.0), tone(0.02, -38.0), tone(0.3, -20.0)])
    cut = quiet_cut(joined, rate, word_end_s=0.39, next_start_s=0.43)
    assert 0.395 * rate <= cut <= 0.425 * rate
    assert quiet_cut(x, rate, 0.5, 0.5) == round(0.5 * rate) or 0.4 * rate < quiet_cut(x, rate, 0.5, 0.5) < 0.52 * rate


# ============================================================================================ text front-end
@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("brake 105 metres earlier", "brake one hundred and five metres earlier"),
        ("thirteen metres", "thirteen metres"),
        ("plus 13 metres", "plus thirteen metres"),
        ("wear 12.3 percent", "wear twelve point three percent"),
        ("in 2nd gear on the 21st lap", "in second gear on the twenty-first lap"),
        ("1,234 laps", "one thousand two hundred and thirty-four laps"),
        ("gap -3", "gap minus three"),
        ("C3 tyres, F1 car", "C3 tyres, F1 car"),  # glued to letters: left to the G2P
    ],
)
def test_spell_numbers(text: str, spoken: str) -> None:
    assert spell_numbers(text) == spoken


def test_prepare_text_folds_accents_and_rewrites_names() -> None:
    assert (
        fold_accents("Sainte Dévote, Würth Kurve, Junção, Hülkenberg")
        == "Sainte Devote, Wurth Kurve, Juncao, Hulkenberg"
    )
    assert prepare_text("Maggotts & Becketts") == "Maggotts and Becketts"
    assert prepare_text("'S' Curves") == "S Curves"
    assert prepare_text("‘S’ do Senna") == "S do Senna"
    assert prepare_text("130R") == "one thirty R"
    assert prepare_text("Le Raidillon de l'Eau Rouge") == "Le Raidillon de Leau Rouge"
    assert prepare_text("Ferrari '26") == "Ferrari twenty-six"
    assert prepare_text("Bruxelles/Rivage") == "Bruxelles, Rivage"
    # the radio's own normaliser runs first; together they leave no digits for the G2P
    spoken = prepare_text(to_speech("T3 +0.341s, braking 13 m earlier. Lap 4: 1:05.7"))
    assert not any(c.isdigit() for c in spoken)
    assert "turn three" in spoken and "thirteen metres" in spoken and "one oh five point seven" in spoken


def test_lexicon_file_is_valid() -> None:
    raw = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    lex = load_lexicon()
    assert lex.words and lex.phrases
    assert len(lex.words) == len(raw["words"])
    for word, ps in lex.words.items():
        assert word.isascii() and word == word.strip() and " " not in word, word  # keys are folded single tokens
        assert set(ps) <= GB_PHONEMES, (word, sorted(set(ps) - GB_PHONEMES))
        assert "ˈ" in ps or len(ps) <= 3, f"{word}: no primary stress"
    lower = [w.lower() for w in lex.words]
    assert len(lower) == len(set(lower)), "case-insensitive duplicate keys"
    for name in ("Maggotts", "Sainz", "Suzuka", "Parabolica", "Eau", "Degner", "Ascari", "Interlagos"):
        assert name in lex.words  # the drops the evaluation saw
    assert load_lexicon(Path("/nonexistent/lexicon.json")) == Lexicon()


def test_known_names_cover_tracks_corners_teams_and_drivers() -> None:
    names = set(known_names())
    assert {"Suzuka", "Monza", "Carlos Sainz", "McLaren", "Abu Dhabi"} <= names
    assert any(n.startswith("Maggotts") for n in names)  # corner names from the track sheets ("&" or "and")
    assert len(names) > 250


# ============================================================================================ audio post-processing
def test_post_processing_trims_normalises_and_fades() -> None:
    raw = np.concatenate([silence(0.3), tone(1.0, -25.0), silence(0.5)])
    out = audio_post.process(clip_of(raw))
    assert out.sample_rate == SR
    m = audio_post.measure(out)
    assert m is not None
    assert m.rms_dbfs == pytest.approx(-17.0, abs=0.6)
    assert m.peak_dbfs <= -3.0 + 0.05
    assert m.lead_s <= audio_post.KEEP_LEAD_S + 0.006 and m.tail_s <= audio_post.KEEP_TAIL_S + 0.006
    assert out.duration_s == pytest.approx(1.0 + audio_post.KEEP_LEAD_S + audio_post.KEEP_TAIL_S, abs=0.02)
    x = np.frombuffer(out.pcm, "<i2").astype(float)
    assert abs(x[0]) < 50 and abs(x[-1]) < 50  # faded at both ends: no click


def test_post_processing_limits_peaks_of_spiky_speech() -> None:
    x = tone(1.0, -30.0)
    x[::2400] = 0.9  # sharp peaks: 20+ dB crest factor, like Kokoro's consonants
    out = audio_post.process(clip_of(x))
    m = audio_post.measure(out)
    assert m is not None
    assert m.peak_dbfs <= -3.0 + 0.05  # the ceiling holds
    assert m.rms_dbfs > -21.0  # and the level still came up


def test_post_processing_limits_a_loud_input_that_needs_no_gain() -> None:
    x = tone(1.0, -14.0)  # already above the -17 dBFS target: no gain stage runs
    x[::2400] = 0.99  # near-full-scale peaks
    m = audio_post.measure(audio_post.process(clip_of(x)))
    assert m is not None and m.peak_dbfs <= -3.0 + 0.05


def test_post_processing_leaves_silence_alone_and_caps_gain() -> None:
    quiet = clip_of(np.concatenate([silence(0.1), tone(0.5, -60.0)]))
    assert audio_post.process(quiet) == quiet  # below the speech threshold: nothing to normalise
    assert audio_post.process(AudioClip(b"", SR)) == AudioClip(b"", SR)
    soft = audio_post.process(clip_of(tone(0.5, -42.0)))
    m = audio_post.measure(soft)
    assert m is not None and m.rms_dbfs == pytest.approx(-42.0 + audio_post.MAX_GAIN_DB, abs=0.5)


# ============================================================================================ spoken-number check
@pytest.mark.parametrize(
    ("expected", "heard"),
    [
        ("thirteen metres earlier", "13 metres earlier."),
        ("Lap four, one oh five point seven.", "Lap 4, 1:05.7."),
        ("Lap four, one oh five point seven.", "Lap 4 1:05.7"),  # comma or not: same digits
        ("plus zero point four laps", "Plus 0.4 laps."),
        ("one hundred and five metres", "105 metres"),
        ("turn two, brake", "Turn to. Break."),  # homophones
        ("Box, box. Box this lap for mediums.", "Box box, box this lap for mediums."),
        ("Maggotts and Becketts", "Maggots and Beckets."),  # names are not compared
        ("Copy.", ""),  # nothing to check
        ("Eau Rouge, brake", "Oh Rouge, brake."),  # "oh" is only zero inside a number
        ("Into Eau Rouge you lost zero point two.", "Into Oh Rouge, you lost 0.2."),
        ("Lap four, one oh five point seven.", "Lap four, one o five point seven."),
    ],
)
def test_speech_check_accepts(expected: str, heard: str) -> None:
    assert speech_mismatch(expected, heard) is None


@pytest.mark.parametrize(
    ("expected", "heard", "why"),
    [
        ("thirteen metres earlier", "30 metres earlier", "numbers"),
        ("fifteen laps of fuel", "fifty laps of fuel", "numbers"),
        ("one oh five point seven", "one five point seven", "numbers"),
        ("turn nine", "", "numbers"),
        ("Box, box.", "Fox, fox.", "missing box"),
        ("Don't box this lap.", "Box this lap.", "missing don't"),
        ("Lift and coast into turn one.", "Left and coast into turn one.", "missing lift"),
    ],
)
def test_speech_check_rejects(expected: str, heard: str, why: str) -> None:
    reason = speech_mismatch(expected, heard)
    assert reason is not None and why in reason


def test_spoken_numbers() -> None:
    assert spoken_numbers("one twenty-nine point five") == "129.5"
    assert spoken_numbers("two thousand three hundred and fifty") == "2350"
    assert spoken_numbers("lap four, one oh five") == "4105"
    assert spoken_numbers("lap four then one oh five") == "4|105"
    assert spoken_numbers("one oh oh five") == "1005" and spoken_numbers("oh oh five") == "005"
    assert spoken_numbers("Oh Rouge, brake") == ""


# ============================================================================================ WorkerTts vs a fake worker
FAKE_WORKER = textwrap.dedent(
    """
    # Fake Kokoro worker: the real worker's server loop (pitwall.voice.tts_worker.serve) with a sine "engine".
    # Misbehaviour on request: SLOW (no answer in time), CRASH (exits), GARBAGE (malformed frame), OOPS (error).
    import argparse, json, math, os, struct, sys, threading, time
    from pitwall.voice import tts_worker as tw

    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="bm_fable")
    ap.add_argument("--speed", type=float, default=1.1)
    ap.add_argument("--fake-mode", default="ok")
    ap.add_argument("--fake-log", default=None)
    args, _ = ap.parse_known_args()
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    if args.fake_mode == "fatal-start":
        tw.write_json(out, b"X", {"id": None, "error": "no model", "fatal": True})
        sys.exit(1)
    if args.fake_mode == "never-ready":
        time.sleep(60)
        sys.exit(0)

    class Engine:
        sample_rate = 24000
        g2p_only = False
        voices = {v: v for v in ("bm_fable", "bm_george", "bf_emma", "bf_isabella", "af_heart")}

        def g2p(self, text):
            return text, [], []

        def synth(self, text, voice, speed):
            if args.fake_log:
                with open(args.fake_log, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"text": text, "voice": voice, "speed": speed}) + "\\n")
            if "SLOW" in text:
                time.sleep(5)
            if "CRASH" in text:
                os._exit(3)
            if "GARBAGE" in text:
                out.write(b"Zgarbage")
                time.sleep(5)
            if "OOPS" in text:
                raise ValueError("engine hiccup")
            if "DIE-LATER" in text:  # answer, then exit while idle
                threading.Timer(0.2, lambda: os._exit(4)).start()
            n_words = len(text.split())
            freq = 300.0 if voice.startswith("bf") else 150.0
            pad = [0] * 4800  # 0.2 s of silence each side, like Kokoro
            body = [int(3000 * math.sin(2 * math.pi * freq * i / 24000)) for i in range(int(0.1 * n_words * 24000))]
            pcm = struct.pack("<%dh" % (len(pad) * 2 + len(body)), *(pad + body + pad))
            yield pcm, (["Zzyzx"] if "Zzyzx" in text else [])

    voice = tw.choose_voice(args.voice, Engine.voices)  # the real worker's rule for an uninstalled voice
    tw.write_json(out, b"R", {"protocol": 1, "engine": "fake", "sample_rate": 24000, "voice": voice,
                              "voices": sorted(Engine.voices), "load_ms": 1.0, "warmup_ms": 1.0, "gpl_free": True})
    sys.exit(tw.serve(Engine(), sys.stdin.buffer, out, voice, args.speed))
    """
)


class FakeSay:
    """Stands in for ``SayTts`` at Kokoro's rate (a quieter, lower tone so tests can tell the engines apart)."""

    name = "say"
    voice = "Daniel"
    sample_rate = SR

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str) -> AudioClip:
        self.calls.append(text)
        return clip_of(np.concatenate([silence(0.1), tone(0.5, -26.0, 100.0), silence(0.1)]))


@pytest.fixture
def fake_worker(tmp_path: Path) -> Path:
    script = tmp_path / "fake_worker.py"
    script.write_text(FAKE_WORKER, encoding="utf-8")
    return script


def make_worker(
    script: Path, *, mode: str = "ok", log: Path | None = None, fallback: Any = "say", **kw: Any
) -> WorkerTts:
    extra = ["--fake-mode", mode] + (["--fake-log", str(log)] if log else [])
    opts: dict[str, Any] = {"start_timeout_s": 20.0, "deadline_base_s": 1.5, "backoff_s": (0.05,), **kw}
    return WorkerTts(
        python=Path(sys.executable),
        script=script,
        lexicon=None,
        fallback=FakeSay() if fallback == "say" else fallback,
        extra_args=extra,
        **opts,
    )


def wait_for(cond: Any, timeout_s: float = 20.0) -> None:
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > timeout_s:
            raise AssertionError("timed out waiting")
        time.sleep(0.02)


def test_worker_tts_speaks_through_the_worker_once_ready(fake_worker: Path, tmp_path: Path) -> None:
    log = tmp_path / "requests.jsonl"
    w = make_worker(fake_worker, log=log)
    try:
        early = w.synthesize_detailed("Radio check, loud and clear.")
        assert early.engine == "say" and not early.neural and early.fallback_reason  # routed to say until ready
        w.start()
        wait_for(lambda: w.ready)
        res = w.synthesize_detailed("Turn 3: brake 13 metres earlier.")
        assert res.engine == "kokoro" and res.neural and res.fallback_reason is None
        assert res.clip.sample_rate == SR
        m = audio_post.measure(res.clip)
        assert m is not None and m.rms_dbfs == pytest.approx(-17.0, abs=1.0) and m.lead_s < 0.05  # post-processed
        assert res.clip.duration_s == pytest.approx(0.1 * 6 + 0.08, abs=0.03)  # 6 words, silence trimmed
        sent = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
        assert sent["text"] == "Turn three: brake thirteen metres earlier."  # the text front-end ran first
        assert sent["voice"] == "bm_fable" and sent["speed"] == pytest.approx(1.1)
        d = w.diagnostics()
        assert d["ready"] and d["status"] == "ready" and d["served"] == {"say": 1, "kokoro": 1}
        assert d["synth_ms"]["n"] == 1 and d["pid"] is not None and d["gpl_free"] is True
        assert w.synthesize_detailed("   ").clip.pcm == b""
    finally:
        w.close()
    assert w.status == "stopped" and not w.ready


def test_worker_timeout_kills_falls_back_and_restarts(fake_worker: Path) -> None:
    w = make_worker(fake_worker, deadline_base_s=0.4, deadline_per_speech_s=0.0)
    w.start()
    try:
        wait_for(lambda: w.ready)
        pid = w.diagnostics()["pid"]
        t0 = time.monotonic()
        res = w.synthesize_detailed("SLOW message please")
        assert time.monotonic() - t0 < 2.0  # the deadline, not the worker's 5 s
        assert res.engine == "say" and "timed out" in (res.fallback_reason or "")
        wait_for(lambda: w.ready and w.diagnostics()["pid"] not in (None, pid))
        assert w.diagnostics()["restarts"] >= 1
        assert w.synthesize_detailed("Back again.").engine == "kokoro"
    finally:
        w.close()


@pytest.mark.parametrize("trigger", ["CRASH", "GARBAGE"])
def test_worker_eof_or_bad_frame_falls_back_and_restarts(fake_worker: Path, trigger: str) -> None:
    w = make_worker(fake_worker)
    w.start()
    try:
        wait_for(lambda: w.ready)
        res = w.synthesize_detailed(f"{trigger} now")
        assert res.engine == "say" and res.fallback_reason
        wait_for(lambda: w.ready)
        assert w.diagnostics()["restarts"] >= 1
        assert w.synthesize_detailed("All good.").engine == "kokoro"
    finally:
        w.close()


def test_worker_error_for_one_message_does_not_restart(fake_worker: Path) -> None:
    w = make_worker(fake_worker)
    w.start()
    try:
        wait_for(lambda: w.ready)
        pid = w.diagnostics()["pid"]
        res = w.synthesize_detailed("OOPS that one")
        assert res.engine == "say" and "engine hiccup" in (res.fallback_reason or "")
        assert w.synthesize_detailed("Next one.").engine == "kokoro"
        assert w.diagnostics()["pid"] == pid and w.diagnostics()["restarts"] == 0
    finally:
        w.close()


def test_worker_reports_dropped_words(fake_worker: Path) -> None:
    w = make_worker(fake_worker)
    w.start()
    try:
        wait_for(lambda: w.ready)
        w.synthesize("Into Zzyzx corner.")
        assert w.diagnostics()["dropped_words"] == {"Zzyzx": 1}
    finally:
        w.close()


def test_worker_that_never_starts_keeps_the_radio_on_say(fake_worker: Path) -> None:
    w = make_worker(fake_worker, mode="fatal-start", backoff_s=(30.0,))
    w.start()
    try:
        wait_for(lambda: w.status == "restarting")
        assert "no model" in (w.diagnostics()["last_error"] or "")
        assert w.synthesize_detailed("Copy.").engine == "say"
        assert w.active == "say" and w.measured_synth_s() is None
        assert w.typical_synth_s == tts_mod.SAY_TYPICAL_SYNTH_S
    finally:
        w.close()


def test_uninstalled_voice_at_start_falls_back_to_the_default(fake_worker: Path, tmp_path: Path) -> None:
    log = tmp_path / "requests.jsonl"
    w = make_worker(fake_worker, log=log, voice="bm_nobody", backoff_s=(30.0,))
    w.start()
    try:
        wait_for(lambda: w.ready)  # a stale or mistyped voice must not keep Kokoro from starting
        d = w.diagnostics()
        assert w.voice == "bm_fable" and d["restarts"] == 0 and d["consecutive_failures"] == 0
        assert w.synthesize_detailed("Box this lap.").engine == "kokoro"
        assert json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["voice"] == "bm_fable"
    finally:
        w.close()


def test_worker_crash_while_idle_is_noticed_by_the_next_message(
    fake_worker: Path, caplog: pytest.LogCaptureFixture
) -> None:
    w = make_worker(fake_worker, backoff_s=(30.0,))
    w.start()
    try:
        wait_for(lambda: w.ready)
        assert w.synthesize_detailed("DIE-LATER please").engine == "kokoro"
        proc = w._proc
        assert proc is not None
        wait_for(lambda: proc.poll() is not None)  # the worker died between messages
        with caplog.at_level("WARNING", logger="pitwall.voice.tts"):
            res = w.synthesize_detailed("Next message.")
        assert res.engine == "say" and not w.ready and w.active == "say"
        assert "exited" in (w.diagnostics()["last_error"] or "")
        assert not any("uses kokoro" in r.getMessage() for r in caplog.records)  # the log names the real voice
    finally:
        w.close()


def test_missing_venv_is_reported_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(tts_mod, "UNAVAILABLE_RECHECK_S", 0.01)
    w = WorkerTts(python=tmp_path / "nope" / "python", lexicon=None, fallback=FakeSay())
    with caplog.at_level("DEBUG", logger="pitwall.voice.tts"):
        w.start()
        time.sleep(0.3)  # many re-checks
        w.close()
    unavailable = [r for r in caplog.records if "unavailable" in r.getMessage()]
    assert len(unavailable) > 3 and sum(r.levelname == "WARNING" for r in unavailable) == 1


def test_missing_venv_is_reported_and_say_speaks(tmp_path: Path) -> None:
    w = WorkerTts(python=tmp_path / "nope" / "python", lexicon=None, fallback=FakeSay())
    w.start()
    try:
        wait_for(lambda: w.status == "unavailable")
        assert "setup-tts.sh" in (w.diagnostics()["last_error"] or "")
        assert w.synthesize_detailed("Copy.").engine == "say"
    finally:
        w.close()


def test_no_fallback_and_no_worker_raises_tts_error(tmp_path: Path) -> None:
    w = WorkerTts(python=tmp_path / "nope", lexicon=None, fallback=None)
    with pytest.raises(TtsError):
        w.synthesize("Copy.")
    assert w.active == "none"


def test_voice_switch_applies_to_the_next_message(fake_worker: Path, tmp_path: Path) -> None:
    log = tmp_path / "requests.jsonl"
    w = make_worker(fake_worker, log=log)
    with pytest.raises(ValueError):
        w.set_voice("Jamie (Premium)")
    w.start()
    try:
        wait_for(lambda: w.ready)
        assert w.voices == list(KOKORO_VOICES)
        w.set_voice("bf_emma")
        w.synthesize("Box this lap.")
        assert json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["voice"] == "bf_emma"
        w.set_voice("af_heart")  # any installed English voice is accepted by the API
        with pytest.raises(ValueError):
            w.set_voice("zz_nobody")
        assert w.voice == "af_heart"
    finally:
        w.close()


def test_measured_synth_time_needs_three_calls(fake_worker: Path) -> None:
    w = make_worker(fake_worker)
    w.start()
    try:
        wait_for(lambda: w.ready)
        assert w.measured_synth_s() is None
        for _ in range(3):
            w.synthesize("Push now.")
        v = w.measured_synth_s()
        assert v is not None and 0 < v < 1.5
    finally:
        w.close()


# ============================================================================================ build_tts never raises
def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


@pytest.fixture
def say_stub(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    made: list[dict[str, Any]] = []

    def fake_say(**kw: Any) -> FakeSay:
        made.append(kw)
        return FakeSay()

    monkeypatch.setattr(tts_mod, "SayTts", fake_say)
    monkeypatch.setattr(tts_mod.sys, "platform", "darwin")
    monkeypatch.setattr(tts_mod.platform, "machine", lambda: "arm64")
    return made


def test_build_tts_kokoro_wraps_say_at_24k(say_stub: list[dict[str, Any]], tmp_path: Path) -> None:
    t = build_tts(_settings(tts_engine="kokoro", tts_voice="bm_george", tts_worker_python=tmp_path / "py"))
    assert isinstance(t, WorkerTts) and t.voice == "bm_george" and t.python == tmp_path / "py"
    assert t.sample_rate == SR and say_stub[-1]["sample_rate"] == SR and say_stub[-1]["voice"] == "Daniel"
    assert not t.ready  # not started by the factory: the hub starts it
    # a macOS voice left over from the `say` days becomes the fallback voice
    t2 = build_tts(_settings(tts_engine="kokoro", tts_voice="Jamie (Premium)"))
    assert isinstance(t2, WorkerTts) and t2.voice == "bm_fable" and say_stub[-1]["voice"] == "Jamie (Premium)"
    # the driver's last pick wins over the setting
    t3 = build_tts(_settings(tts_engine="kokoro", tts_voice="bm_fable"), voice_override="bf_emma")
    assert isinstance(t3, WorkerTts) and t3.voice == "bf_emma"


def test_build_tts_kokoro_never_raises(monkeypatch: pytest.MonkeyPatch, say_stub: list[dict[str, Any]]) -> None:
    def broken(**_: Any) -> WorkerTts:
        raise RuntimeError("worker class exploded")

    monkeypatch.setattr(tts_mod, "WorkerTts", broken)
    t = build_tts(_settings(tts_engine="kokoro"))
    assert isinstance(t, FakeSay)  # falls back to say
    monkeypatch.setattr(tts_mod.platform, "machine", lambda: "x86_64")
    assert isinstance(build_tts(_settings(tts_engine="kokoro")), FakeSay)  # no Apple silicon: say itself
    monkeypatch.setattr(tts_mod.sys, "platform", "linux")
    assert isinstance(build_tts(_settings(tts_engine="kokoro")), NullTts)


def test_build_tts_bad_speed_is_rejected_by_settings() -> None:
    with pytest.raises(ValueError):
        _settings(tts_speed=9.0)


@pytest.mark.usefixtures("no_pitwall_env")
def test_settings_default_to_kokoro_bm_fable() -> None:
    s = _settings()
    assert (s.tts_engine, s.tts_voice, s.tts_speed, s.tts_verify) == ("kokoro", "bm_fable", 1.1, True)


def test_voice_choice_is_remembered_per_engine(tmp_path: Path) -> None:
    path = tmp_path / "radio_voice.json"
    assert load_voice_choice(path, "kokoro") is None
    save_voice_choice(path, "kokoro", "bf_isabella")
    assert load_voice_choice(path, "kokoro") == "bf_isabella"
    assert load_voice_choice(path, "say") is None
    path.write_text("{broken", encoding="utf-8")
    assert load_voice_choice(path, "kokoro") is None


# ============================================================================================ the hub with a neural engine
class NeuralTts:
    """A fake Kokoro: neural audio whose length encodes the text, a fallback, voices and measured timing."""

    name = "kokoro"
    neural = True
    sample_rate = SR
    typical_synth_s: float | None = None

    def __init__(self, measured: float | None = None) -> None:
        self.voice = "bm_fable"
        self.voices = list(KOKORO_VOICES)
        self.active = "kokoro"
        self.ready = True
        self.status = "ready"
        self.calls: list[tuple[str, str]] = []
        self.fallback_calls: list[str] = []
        self.measured = measured
        self.started = self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    def set_voice(self, voice: str) -> None:
        if voice not in self.voices:
            raise ValueError(f"unknown voice {voice!r}")
        self.voice = voice

    def measured_synth_s(self) -> float | None:
        return self.measured

    def synthesize_detailed(self, text: str) -> SynthResult:
        self.calls.append((text, self.voice))
        engine = "kokoro" if self.active == "kokoro" else "say"
        clip = clip_of(np.concatenate([silence(0.05), tone(0.05 * len(text)), silence(0.05)]))
        return SynthResult(clip, engine, engine == "kokoro", 12.0, None if engine == "kokoro" else "worker starting")

    def synthesize(self, text: str) -> AudioClip:
        return self.synthesize_detailed(text).clip

    def synthesize_fallback(self, text: str) -> AudioClip:
        self.fallback_calls.append(text)
        return clip_of(tone(0.4, -20.0, 100.0))

    def diagnostics(self) -> dict[str, Any]:
        return {"status": self.status, "restarts": 0}


class EchoStt:
    """A loaded STT that 'hears' scripted transcripts (the last one repeats)."""

    name = "parakeet"
    loaded = True

    def __init__(self, *heard: str) -> None:
        self.heard = list(heard)
        self.clips: list[AudioClip] = []

    def warmup(self) -> None:
        return None

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        self.clips.append(clip)
        text = self.heard.pop(0) if len(self.heard) > 1 else (self.heard[0] if self.heard else "")
        return SttResult(text, self.name, 5, clip.duration_s)


class QueueScheduler:
    speech_latency_s = SPEECH_LATENCY_S

    def __init__(self) -> None:
        self.queue: list[RadioMessage] = []

    def enqueue(self, m: RadioMessage) -> None:
        self.queue.append(m)

    def next_message(self, state: DrivingState, now: float, speaking: bool) -> RadioMessage | None:
        return None if speaking or not self.queue else self.queue.pop(0)

    def set_intensity(self, i: str) -> None:
        return None


async def neural_hub(tts: Any, stt: Any, **kw: Any) -> tuple[RadioHub, RadioClient, list[Any]]:
    hub = RadioHub(
        LiveState(), RaceEngineer(None), stt, tts, QueueScheduler(), fact_sheet=FactSheet, to_speech=to_speech, **kw
    )
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    client = RadioClient(send=send)
    await hub.connect(client)
    await settle(3)
    return hub, client, sent


async def settle(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0.01)


def proactive(text: str) -> RadioMessage:
    return RadioMessage(
        "p1", MessageKind.COACHING, Priority.NORMAL, text, to_speech(text), time.monotonic(), needs_speak_window=False
    )


async def test_hub_starts_and_closes_the_engine_and_reports_it() -> None:
    tts = NeuralTts()
    hub, _client, sent = await neural_hub(tts, EchoStt(""))
    assert tts.started
    state = [m for m in sent if isinstance(m, dict) and m.get("type") == "state"][-1]
    assert state["tts"] == "kokoro" and state["tts_voice"] == "bm_fable" and state["tts_voices"] == list(KOKORO_VOICES)
    assert state["tts_ready"] is True and state["tts_neural"] is True and state["tts_active"] == "kokoro"
    status = hub.status()
    assert status["tts_engine"]["status"] == "ready" and "tts_check" in status
    await hub.stop()
    assert tts.closed


async def test_hub_voice_change_over_the_radio_rebuilds_cue_audio_and_is_saved() -> None:
    tts = NeuralTts()
    saved: list[str] = []
    hub, client, sent = await neural_hub(tts, EchoStt(""), persist_voice=saved.append)
    hub._cue_parts["turn 1"] = clip_of(tone(0.2))
    hub._cue_tts, hub._cue_voice = hub.tts, "bm_fable"
    await hub.on_text(client, {"type": "settings", "tts_voice": "bf_emma"})
    await settle()
    assert tts.voice == "bf_emma" and saved == ["bf_emma"]
    assert "turn 1" not in hub._cue_parts  # the old voice's audio is gone
    state = [m for m in sent if isinstance(m, dict) and m.get("type") == "state"][-1]
    assert state["tts_voice"] == "bf_emma"
    await hub.on_text(client, {"type": "settings", "tts_voice": "Jamie"})
    await settle()
    assert any(isinstance(m, dict) and m.get("type") == "error" and "unknown voice" in m["message"] for m in sent)
    assert tts.voice == "bf_emma"
    await hub.stop()


async def test_hub_voice_change_needs_an_engine_with_voices() -> None:
    class PlainTts:
        name = "say"
        sample_rate = 22_050

        def synthesize(self, text: str) -> AudioClip:
            return AudioClip(b"\x01\x00" * 100, 22_050)

    hub, _client, _sent = await neural_hub(PlainTts(), EchoStt(""))
    with pytest.raises(ValueError):
        hub.set_tts_voice("bm_fable")
    assert hub.state()["tts_voices"] == [] and hub.state()["tts_neural"] is False
    await hub.stop()


async def test_cue_timing_uses_the_engines_measured_synthesis_time() -> None:
    fast = NeuralTts(measured=0.12)
    hub, _c, _s = await neural_hub(fast, EchoStt(""))
    seeded = hub._cue_latency_s("pcm")
    assert seeded == pytest.approx(max(DELIVERY_LEAD_S, SPEECH_LATENCY_S - 0.12) + CUE_OUTPUT_ALLOWANCE_S)
    fast.measured = None  # nothing measured yet, no parts timed: the engine's typical figure, else 0.4 s
    fast.typical_synth_s = 0.26
    assert hub._cue_latency_s("pcm") == pytest.approx(SPEECH_LATENCY_S - 0.26 + CUE_OUTPUT_ALLOWANCE_S)
    await hub.stop()


async def test_proactive_message_failing_the_number_check_is_resynthesised_then_falls_back() -> None:
    tts = NeuralTts()
    stt = EchoStt("Braking thirty metres earlier.")  # always mishears
    hub, _c, sent = await neural_hub(tts, stt)
    assert hub._tick_task is not None
    hub._tick_task.cancel()
    hub.scheduler.enqueue(proactive("Braking 13 metres earlier."))
    await hub._tick(time.monotonic())
    await settle()
    assert len(tts.calls) == 2 and tts.fallback_calls == ["Braking 13 metres earlier."]
    say = [m for m in sent if isinstance(m, dict) and m.get("type") == "say"][-1]
    assert say["n_bytes"] == round(0.4 * SR) * 2  # the fallback voice's audio went out
    assert hub.tts_check["mismatch"] == 1 and hub.tts_check["fallback"] == 1
    assert hub.tts_check_log[0]["outcome"] == "fallback voice"
    await hub.stop()


async def test_proactive_message_fixed_by_resynthesis_keeps_the_neural_voice() -> None:
    tts = NeuralTts()
    stt = EchoStt("Braking 30 metres earlier.", "Braking 13 metres earlier.")
    hub, _c, _sent = await neural_hub(tts, stt)
    assert hub._tick_task is not None
    hub._tick_task.cancel()
    hub.scheduler.enqueue(proactive("Braking 13 metres earlier."))
    await hub._tick(time.monotonic())
    assert len(tts.calls) == 2 and not tts.fallback_calls
    assert hub.tts_check["fixed"] == 1
    await hub.stop()


async def test_number_check_is_skipped_when_stt_is_not_loaded() -> None:
    tts = NeuralTts()
    stt = EchoStt("thirty")
    stt.loaded = False
    hub, _c, _sent = await neural_hub(tts, stt)
    assert hub._tick_task is not None
    hub._tick_task.cancel()
    hub.scheduler.enqueue(proactive("Braking 13 metres earlier."))
    await hub._tick(time.monotonic())
    assert len(tts.calls) == 1 and not stt.clips and hub.tts_check["skipped"] == 1
    await hub.stop()


async def test_cue_parts_are_checked_and_fallback_parts_upgraded_when_ready() -> None:
    tts = NeuralTts()
    tts.active, tts.ready = "say", False  # worker still starting: parts come from the fallback
    stt = EchoStt("Turn nine.")
    hub, _c, _s = await neural_hub(tts, stt)
    clip = await hub._cue_part_audio("turn 9")
    assert clip is not None and hub._cue_part_engine["turn 9"] == "say" and not stt.clips  # say is not checked
    tts.active, tts.ready = "kokoro", True
    await hub._upgrade_cue_parts()
    assert hub._cue_part_engine["turn 9"] == "kokoro" and len(stt.clips) == 1 and hub.tts_check["ok"] == 1
    stt.heard = ["Turn five."]
    hub._cue_parts.clear()
    await hub._cue_part_audio("turn 9")
    assert hub._cue_part_engine["turn 9"] == "say" and "turn 9" in hub._cue_part_pinned  # mismatch twice: say
    await hub._upgrade_cue_parts()
    assert hub._cue_part_engine["turn 9"] == "say"  # pinned: not upgraded back to the misread voice
    await hub.stop()


async def test_cue_parts_rendered_before_the_stt_loaded_are_checked_once_it_is() -> None:
    tts = NeuralTts()
    stt = EchoStt("Turn five.", "Turn five.")  # Kokoro misread it: both renders fail the check
    stt.loaded = False  # Parakeet still warming up (service restart during a session)
    hub, _c, _s = await neural_hub(tts, stt)
    assert hub._tick_task is not None
    hub._tick_task.cancel()
    clip = await hub._cue_part_audio("turn 9")
    assert clip is not None and hub._cue_part_engine["turn 9"] == "kokoro" and "turn 9" in hub._cue_part_unchecked
    requested: list[bool] = []
    hub._request_cue_audio = lambda: requested.append(True)  # type: ignore[method-assign]
    hub._check_tts_engine(time.monotonic() + 100)
    assert not requested  # cannot check yet: nothing to do
    stt.loaded = True
    hub._check_tts_engine(time.monotonic() + 200)
    assert requested  # the STT is up: the cue audio pass runs the check
    await hub._upgrade_cue_parts()
    assert hub._cue_part_engine["turn 9"] == "say" and "turn 9" in hub._cue_part_pinned  # checked, fell back
    assert not hub._cue_part_unchecked and hub.tts_check["fallback"] == 1
    await hub.stop()


async def test_a_cue_phrase_is_said_in_one_voice() -> None:
    tts = NeuralTts()
    stt = EchoStt("Turn five.", "Turn five.", "Brake.")  # "turn 9" fails twice (pinned to say), "brake" passes
    hub, _c, _s = await neural_hub(tts, stt)
    assert await hub._cue_part_audio("turn 9") is not None and await hub._cue_part_audio("brake") is not None
    assert hub._cue_part_engine == {"turn 9": "say", "brake": "kokoro"}
    phrase = await hub._phrase_audio(("T9", "brake"), 1)
    assert phrase is not None
    assert tts.fallback_calls == ["turn 9", "brake"]  # the fallback voice says the whole phrase
    fb = hub._cue_fallback_parts["brake"]
    clip, offset = phrase
    assert offset == pytest.approx(hub._cue_parts["turn 9"].duration_s + 0.06, abs=1e-3)
    assert clip.duration_s == pytest.approx(offset + fb.duration_s, abs=1e-3)
    assert hub._cue_parts["brake"] is not fb  # the Kokoro part stays cached for phrases without a pinned part
    await hub.stop()


async def test_answers_are_audited_after_sending_not_held() -> None:
    tts = NeuralTts()
    stt = EchoStt("Thirty laps of fuel.")
    hub, _c, sent = await neural_hub(tts, stt)
    msg = hub._msg(MessageKind.ANSWER, Priority.HIGH, "Thirteen laps of fuel.", bypass=True)
    await hub.say(msg, None, None)
    assert hub.speaking_id == msg.id  # delivered at once, before any check
    await settle()
    assert [m for m in sent if isinstance(m, dict) and m.get("type") == "say"]
    assert len(tts.calls) == 1 and not tts.fallback_calls  # not re-synthesised
    assert hub.tts_check["audit_mismatch"] == 1
    await hub.stop()


async def test_worker_engine_starts_after_a_delay_or_when_a_radio_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    from pitwall.voice import hub as hub_mod

    tts = NeuralTts()
    hub = RadioHub(LiveState(), RaceEngineer(None), EchoStt(""), tts, QueueScheduler(), FactSheet, to_speech)
    hub.start()
    await settle(3)
    assert not tts.started  # a short-lived app (tests, tools) never spawns the worker
    await hub.stop()
    assert not tts.started and not tts.closed

    monkeypatch.setattr(hub_mod, "TTS_START_DELAY_S", 0.02)
    tts2 = NeuralTts()
    hub2 = RadioHub(LiveState(), RaceEngineer(None), EchoStt(""), tts2, QueueScheduler(), FactSheet, to_speech)
    hub2.start()
    await settle(5)
    assert tts2.started  # the server started: the worker follows shortly
    await hub2.stop()
    assert tts2.closed


async def test_test_voice_message_speaks_on_every_radio() -> None:
    tts = NeuralTts()
    hub, client, sent = await neural_hub(tts, EchoStt(""))
    await hub.on_text(client, {"type": "test_voice"})
    await settle()
    say = [m for m in sent if isinstance(m, dict) and m.get("type") == "say"]
    assert say and say[-1]["kind"] == "info" and say[-1]["sample_rate"] == SR and "Radio check" in say[-1]["text"]
    await hub.on_text(client, {"type": "test_voice", "text": "Box, box."})
    await settle()
    assert [m for m in sent if isinstance(m, dict) and m.get("type") == "say"][-1]["text"] == "Box, box."
    await hub.stop()


def test_keep_warm_only_after_idle(fake_worker: Path, tmp_path: Path) -> None:
    log = tmp_path / "requests.jsonl"
    w = make_worker(fake_worker, log=log)
    w.start()
    try:
        wait_for(lambda: w.ready)
        assert not w.keep_warm()  # just started: not idle
        assert w.keep_warm(idle_s=0.0)
        assert json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["text"] == "Copy."
        d = w.diagnostics()
        assert d["keep_warms"] == 1 and d["synth_ms"]["n"] == 0  # not counted as a message
    finally:
        w.close()


async def test_hub_keeps_the_engine_warm_only_while_a_session_is_live() -> None:
    calls: list[float] = []
    tts = NeuralTts()
    tts.keep_warm = lambda: calls.append(time.monotonic()) or True  # type: ignore[attr-defined]
    hub, _c, _s = await neural_hub(tts, EchoStt(""))
    assert hub._tick_task is not None
    hub._tick_task.cancel()
    await hub._tick(time.monotonic() + 100)
    await settle()
    assert calls == []  # telemetry not live
    hub.live.connection = lambda: {"status": "live"}  # type: ignore[method-assign]
    await hub._tick(time.monotonic() + 200)
    await settle()
    assert len(calls) == 1
    await hub._tick(time.monotonic() + 205)  # checked at most every KEEP_WARM_CHECK_S
    await settle()
    assert len(calls) == 1
    await hub.stop()
