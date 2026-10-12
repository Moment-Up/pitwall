"""Spotter phrase audio made in advance: cache per (engine, voice), trimming, the STT check (re-render, then the
fallback engine, then "unverified"), rebuilding, and no engine (text only). Fake engines; no real audio."""

from __future__ import annotations

from collections.abc import Callable

from pitwall.spotter.phrases import all_texts
from pitwall.voice.hub import trim_silence
from pitwall.voice.spotter_audio import SpotterAudio
from pitwall.voice.types import AudioClip, SynthResult

SR = 24_000
TEXTS = sorted({t for _p, _w, t in all_texts()})


def _clip(text: str, lead_s: float = 0.2) -> AudioClip:
    n = 4000 + 50 * TEXTS.index(text)  # a length per text: the fake STT tells them apart by it
    return AudioClip(b"\x00\x00" * int(lead_s * SR) + b"\x00\x20" * n + b"\x00\x00" * 2000, SR)


def _text_of(clip: AudioClip) -> str | None:
    for t in TEXTS:
        if len(trim_silence(_clip(t)).pcm) == len(clip.pcm):
            return t
    return None


class Engine:
    def __init__(self, name: str = "kokoro", neural: bool = True) -> None:
        self.name = name
        self.neural = neural
        self.calls: list[str] = []

    def __call__(self, text: str) -> SynthResult:
        self.calls.append(text)
        return SynthResult(_clip(text), self.name, self.neural, 5.0)


def _heard(mapping: Callable[[AudioClip], str | None]) -> Callable[[AudioClip], object]:
    async def heard(clip: AudioClip) -> str | None:
        return mapping(clip)

    return heard


async def _build(audio: SpotterAudio, synth: Engine, **kw: object) -> int:
    args: dict[str, object] = {
        "engine": "kokoro",
        "voice": "bm_fable",
        "primary_ready": True,
        "synth": synth,
        "fallback": None,
        "fallback_name": "say",
        "heard": None,
        "can_verify": lambda: False,
    }
    args.update(kw)
    return await audio.build(**args)  # type: ignore[arg-type]


async def test_every_phrase_is_built_trimmed_and_cached() -> None:
    audio = SpotterAudio(trim_silence)
    eng = Engine()
    assert await _build(audio, eng) == 18 and audio.ready()
    clip = audio.get("car_left", False)
    assert clip is not None and clip.pcm[:2] != b"\x00\x00"  # starts at speech onset
    assert audio.get("car_left", True) is not audio.get("car_left", False)
    assert await _build(audio, eng) == 0 and len(eng.calls) == 18  # cached: nothing re-rendered
    st = audio.status()
    assert st["phrases"] == 18 and st["unchecked"] == 18 and st["rendered_by"] == ["kokoro"]
    assert 0.1 < st["clip_s"]["car_left"] < 1.0 and sum(len(audio.clips) for _ in [0]) == 18


async def test_a_voice_change_rebuilds_and_fallback_clips_are_upgraded() -> None:
    audio = SpotterAudio(trim_silence)
    say = Engine("say", neural=False)
    await _build(audio, say, primary_ready=False)  # Kokoro still starting: its fallback rendered them
    assert audio.status()["rendered_by"] == ["say"]
    kokoro = Engine()
    assert await _build(audio, kokoro) == 18  # Kokoro is up: re-rendered phrase by phrase
    assert audio.status()["rendered_by"] == ["kokoro"]
    assert await _build(audio, kokoro, voice="bm_george") == 18 and audio.key == ("kokoro", "bm_george")


async def test_the_stt_check_passes_or_re_renders_then_falls_back_then_marks_unverified() -> None:
    texts = {pid: t for pid, w, t in all_texts() if w == "standard"}
    audio = SpotterAudio(trim_silence)
    eng = Engine()
    heard_left_as_right = {len(trim_silence(_clip(texts["car_left"])).pcm)}

    def hear(clip: AudioClip) -> str | None:
        if len(clip.pcm) in heard_left_as_right:
            return "car right"  # the dangerous mishearing, every time Kokoro says it
        return _text_of(clip) or "?"

    fallback_calls: list[str] = []

    def fallback(text: str) -> AudioClip:
        fallback_calls.append(text)
        return AudioClip(b"\x00\x30" * 9999, SR)  # the say voice: heard as "?" (misheard too)

    await _build(
        audio,
        eng,
        heard=_heard(hear),
        can_verify=lambda: True,
        fallback=fallback,
    )
    pc = audio.clips[("car_left", False)]
    assert eng.calls.count("Car left.") == 2  # rendered, then re-rendered once
    assert fallback_calls == ["Car left."] and pc.engine == "say" and pc.fallback and pc.verified is False
    assert audio.clips[("car_right", False)].verified is True
    st = audio.status()
    assert st["fallback"] == 1 and st["unverified"] == 1


async def test_unchecked_clips_are_checked_once_the_stt_is_loaded() -> None:
    audio = SpotterAudio(trim_silence)
    eng = Engine()
    await _build(audio, eng)
    assert audio.status()["unchecked"] == 18
    await _build(audio, eng, heard=_heard(_text_of), can_verify=lambda: True)
    assert audio.status()["unchecked"] == 0 and len(eng.calls) == 18  # checked, not re-rendered


async def test_no_engine_means_text_only() -> None:
    audio = SpotterAudio(trim_silence)

    def null(text: str) -> SynthResult:
        return SynthResult(AudioClip(b"", SR), "none", False, 0.0)

    assert await _build(audio, null) == 0  # type: ignore[arg-type]
    assert not audio.ready() and audio.get("car_left", False) is None
