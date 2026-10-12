"""Spotter phrases synthesised ahead of time (owned by the radio hub; spec section 5.4).

A spotter call must sound the moment it is decided: every phrase of both wording sets (standard and simple) is
rendered once per TTS engine and voice, trimmed to speech onset (``hub.trim_silence``) and kept (18 clips, well under
1 MB). Nothing here runs on a delivery path: ``get`` is a dict lookup.

* **Build** (``build``): at hub start once TTS is up, when the spotter is switched on, and when the engine, its voice
  or the spotter's own voice setting changes. Each phrase is rendered in a worker thread. Until Kokoro is ready its
  ``say`` fallback renders them; they are re-rendered once Kokoro is up, phrase by phrase (a phrase always has audio).
* **Check**: when the STT model is loaded, each clip is transcribed. The key words must be heard in order and
  "left"/"right" must match exactly (``spotter.phrases.heard_mismatch``): mishearing left as right would be dangerous.
  A mismatch re-renders once, then uses the fallback engine; a phrase that still fails is marked ``unverified`` (shown
  in status) and still used.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pitwall.spotter.phrases import all_texts, heard_mismatch
from pitwall.voice.types import AudioClip, SynthResult

log = logging.getLogger(__name__)

Synth = Callable[[str], SynthResult]  # blocking: run in a worker thread
Fallback = Callable[[str], AudioClip]  # blocking
Heard = Callable[[AudioClip], Awaitable[str | None]]
Trim = Callable[[AudioClip], AudioClip]


@dataclass(slots=True, frozen=True)
class PhraseClip:
    clip: AudioClip
    engine: str  # the engine that rendered it
    verified: bool | None  # True: the STT heard it right; False: kept although it did not; None: not checked
    fallback: bool  # moved to the fallback engine by the check (never re-rendered by the primary)

    @property
    def duration_s(self) -> float:
        return self.clip.duration_s


class SpotterAudio:
    """The phrase cache for one (engine, voice). Event-loop only."""

    def __init__(self, trim: Trim) -> None:
        self._trim = trim
        self.key: tuple[str, str | None] | None = None
        self.clips: dict[tuple[str, bool], PhraseClip] = {}  # (phrase id, simple) -> clip
        self.builds = 0
        self.last_error: str | None = None

    def get(self, pid: str, simple: bool) -> AudioClip | None:
        pc = self.clips.get((pid, simple))
        return None if pc is None else pc.clip

    def ready(self) -> bool:
        return len(self.clips) == len(all_texts())

    def clear(self) -> None:
        self.clips.clear()
        self.key = None

    async def build(
        self,
        *,
        engine: str,
        voice: str | None,
        primary_ready: bool,
        synth: Synth,
        fallback: Fallback | None,
        fallback_name: str,
        heard: Heard | None,
        can_verify: Callable[[], bool],
    ) -> int:
        """Render what is missing or stale for ``(engine, voice)``; returns how many phrases were (re)rendered.

        ``primary_ready``: the engine itself (not its fallback) renders now; clips its fallback rendered earlier are
        then re-rendered. ``heard`` (async STT) checks clips when ``can_verify()``."""
        key = (engine, voice)
        if key != self.key:
            self.clips = {}
            self.key = key
        done = 0
        for pid, wording, text in all_texts():
            simple = wording == "simple"
            check = heard if heard is not None and can_verify() else None  # the STT is loaded, nobody transmits
            cur = self.clips.get((pid, simple))
            stale = cur is not None and not cur.fallback and cur.engine != engine and primary_ready
            unchecked = cur is not None and cur.verified is None and check is not None
            if cur is not None and not stale and not unchecked:
                continue
            if cur is not None and unchecked and not stale:
                result = await self._check(pid, simple, text, cur, synth, fallback, fallback_name, check)
            else:
                try:
                    res = await asyncio.to_thread(synth, text)
                except Exception as e:
                    self.last_error = f"{pid}: {e}"
                    log.warning("spotter audio %r: synthesis failed (%s)", text, e)
                    continue
                clip = self._trim(res.clip)
                if not clip.n_samples:
                    continue  # no engine (NullTts): device voices speak the text
                pc = PhraseClip(clip, res.engine, None, False)
                result = await self._check(pid, simple, text, pc, synth, fallback, fallback_name, check)
            if key != self.key:
                return done  # the engine or voice changed meanwhile: a newer build owns the cache
            self.clips[(pid, simple)] = result
            done += 1
        self.builds += 1
        return done

    async def _check(
        self,
        pid: str,
        simple: bool,
        text: str,
        pc: PhraseClip,
        synth: Synth,
        fallback: Fallback | None,
        fallback_name: str,
        heard: Heard | None,
    ) -> PhraseClip:
        if heard is None:
            return pc
        got = await heard(pc.clip)
        if got is None:
            return pc  # could not check now (STT not loaded, driver transmitting): a later build tries again
        why = heard_mismatch(pid, simple, got)
        if why is None:
            return PhraseClip(pc.clip, pc.engine, True, pc.fallback)
        log.warning("spotter audio %r heard as %r (%s): re-rendering", text, got, why)
        try:
            res = await asyncio.to_thread(synth, text)
            again = self._trim(res.clip)
        except Exception:
            again = AudioClip(b"", pc.clip.sample_rate)
            res = None
        if res is not None and again.n_samples:
            got2 = await heard(again)
            if got2 is not None and heard_mismatch(pid, simple, got2) is None:
                return PhraseClip(again, res.engine, True, False)
        if fallback is not None and pc.engine != fallback_name:
            try:
                fb = self._trim(await asyncio.to_thread(fallback, text))
            except Exception as e:
                log.warning("spotter audio %r: fallback voice failed (%s)", text, e)
            else:
                if fb.n_samples:
                    got3 = await heard(fb)
                    ok = got3 is not None and heard_mismatch(pid, simple, got3) is None
                    if not ok:
                        log.warning("spotter audio %r: the fallback voice is misheard too; kept, unverified", text)
                    return PhraseClip(fb, fallback_name, ok, True)
        log.warning("spotter audio %r: misheard after re-rendering; kept, unverified", text)
        return PhraseClip(pc.clip, pc.engine, False, pc.fallback)

    def status(self) -> dict[str, Any]:
        engines = sorted({pc.engine for pc in self.clips.values()})
        return {
            "ready": self.ready(),
            "engine": None if self.key is None else self.key[0],
            "rendered_by": engines,
            "voice": None if self.key is None else self.key[1],
            "phrases": len(self.clips),
            "unverified": sum(1 for pc in self.clips.values() if pc.verified is False),
            "unchecked": sum(1 for pc in self.clips.values() if pc.verified is None),
            "fallback": sum(1 for pc in self.clips.values() if pc.fallback),
            "clip_s": {pid: round(pc.duration_s, 2) for (pid, simple), pc in self.clips.items() if not simple},
            "clip_s_simple": {pid: round(pc.duration_s, 2) for (pid, simple), pc in self.clips.items() if simple},
            "error": self.last_error,
        }
