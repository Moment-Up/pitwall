"""Radio audio post-processing for neural TTS output (docs/research/tts-evaluation.md section 6.4).

Kokoro renders quiet (speech RMS -22 to -27 dBFS [measured], too quiet for one AirPod in a noisy room) with
0.26-0.39 s of silence before the first word and 0.2-0.7 s after the last, which adds straight to the time
until the driver hears anything. ``process`` makes every clip uniform, in about a millisecond:

1. **Trim** leading and trailing silence to ``KEEP_LEAD_S`` / ``KEEP_TAIL_S`` (40 ms): speech is a 5 ms frame
   whose RMS is above -45 dBFS (and above 40 dB below the clip's peak, so a loud clip's breath is not "speech").
2. **Normalise** the RMS *of the speech frames* (pauses do not count) to ``TARGET_RMS_DBFS`` (-17 dBFS), with
   the gain capped at +20 dB so near-silent output is never blown up into noise.
3. **Limit** peaks to ``PEAK_CEILING_DBFS`` (-3 dBFS), whether or not gain was applied (a ``say`` voice that is
   already loud enough is still limited). Kokoro's crest factor is 13-20 dB [measured], so plain
   gain would either clip or stop short of the target. The limiter is a look-ahead gain envelope: per sample the
   gain that keeps it under the ceiling, a 10 ms minimum filter (look-ahead and hold), then a 10 ms moving
   average. Because the averaging window is no wider than the minimum filter's, the smoothed gain never exceeds
   what any sample needs, so the ceiling holds exactly while the gain moves over ~20 ms (no clicks, no
   audible distortion on the short consonant peaks it touches).
4. **Fade** in over 5 ms and out over 15 ms, so a clip that starts on a transient or ends mid-sound does not click.
5. Convert to int16 with clipping.

Pure numpy/scipy, thread-safe. The sample rate is kept (Kokoro's native 24 kHz is sent as is: the radio protocol
carries ``sample_rate`` per message and the clients honour it).
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import minimum_filter1d, uniform_filter1d

from pitwall.voice.types import AudioClip

__all__ = [
    "FADE_IN_S",
    "FADE_OUT_S",
    "KEEP_LEAD_S",
    "KEEP_TAIL_S",
    "MAX_GAIN_DB",
    "PEAK_CEILING_DBFS",
    "TARGET_RMS_DBFS",
    "Loudness",
    "measure",
    "process",
]

KEEP_LEAD_S = 0.04
KEEP_TAIL_S = 0.04
FADE_IN_S = 0.005
FADE_OUT_S = 0.015
TARGET_RMS_DBFS = -17.0
PEAK_CEILING_DBFS = -3.0
MAX_GAIN_DB = 20.0
SILENCE_DBFS = -45.0
SILENCE_BELOW_PEAK_DB = 40.0
FRAME_S = 0.005
LIMITER_WINDOW_S = 0.010

type _F = NDArray[np.float64]


def _db(x: float) -> float:
    return 20.0 * math.log10(x) if x > 0 else -math.inf


def _amp(db: float) -> float:
    return float(10.0 ** (db / 20.0))


class Loudness:
    """Speech-frame RMS, peak (dBFS) and the silence before / after speech (s) of a clip."""

    __slots__ = ("lead_s", "peak_dbfs", "rms_dbfs", "tail_s")

    def __init__(self, rms_dbfs: float, peak_dbfs: float, lead_s: float, tail_s: float) -> None:
        self.rms_dbfs = rms_dbfs
        self.peak_dbfs = peak_dbfs
        self.lead_s = lead_s
        self.tail_s = tail_s

    def __repr__(self) -> str:
        return (
            f"Loudness(rms={self.rms_dbfs:.1f} dBFS, peak={self.peak_dbfs:.1f} dBFS, "
            f"lead={self.lead_s:.3f} s, tail={self.tail_s:.3f} s)"
        )


def _floats(clip: AudioClip) -> _F:
    return np.frombuffer(clip.pcm, dtype="<i2", count=clip.n_samples).astype(np.float64) / 32768.0


def _speech_frames(x: _F, rate: int) -> tuple[_F, int]:
    """Per-frame RMS and the frame length (samples)."""
    frame = max(1, round(FRAME_S * rate))
    n = len(x) // frame
    if n == 0:
        return np.zeros(0), frame
    rms = np.sqrt(np.mean(x[: n * frame].reshape(n, frame) ** 2, axis=1))
    return rms, frame


def _active(rms: _F, peak: float) -> NDArray[np.bool_]:
    threshold = max(_amp(SILENCE_DBFS), peak * _amp(-SILENCE_BELOW_PEAK_DB))
    return rms > threshold


def measure(clip: AudioClip) -> Loudness | None:
    """Loudness of the speech in a clip; ``None`` if it has no speech."""
    x = _floats(clip)
    if x.size == 0:
        return None
    peak = float(np.max(np.abs(x)))
    rms, frame = _speech_frames(x, clip.sample_rate)
    act = _active(rms, peak)
    if not act.any():
        return None
    idx = np.flatnonzero(act)
    speech_rms = float(np.sqrt(np.mean(rms[act] ** 2)))
    lead = idx[0] * frame / clip.sample_rate
    tail = (len(x) - (idx[-1] + 1) * frame) / clip.sample_rate
    return Loudness(_db(speech_rms), _db(peak), lead, max(0.0, tail))


def _limit(y: _F, ceiling: float, rate: int) -> _F:
    mag = np.abs(y)
    if mag.size == 0 or float(mag.max()) <= ceiling:
        return y
    need = np.minimum(1.0, ceiling / np.maximum(mag, 1e-12))
    win = max(1, round(LIMITER_WINDOW_S * rate))
    held = minimum_filter1d(need, size=2 * win + 1, mode="nearest")
    gain = uniform_filter1d(held, size=win | 1, mode="nearest")  # odd, <= the hold window: never above `need`
    out: _F = y * np.minimum(gain, need)
    return out


def process(
    clip: AudioClip,
    *,
    target_rms_dbfs: float = TARGET_RMS_DBFS,
    peak_ceiling_dbfs: float = PEAK_CEILING_DBFS,
    keep_lead_s: float = KEEP_LEAD_S,
    keep_tail_s: float = KEEP_TAIL_S,
) -> AudioClip:
    """Trim, normalise, limit and fade a clip (see the module docstring). A clip with no speech is returned
    unchanged; the sample rate is never changed."""
    rate = clip.sample_rate
    x = _floats(clip)
    if x.size == 0 or rate <= 0:
        return clip
    peak = float(np.max(np.abs(x)))
    rms, frame = _speech_frames(x, rate)
    act = _active(rms, peak)
    if not act.any():
        return clip
    idx = np.flatnonzero(act)
    start = max(0, idx[0] * frame - round(keep_lead_s * rate))
    end = min(len(x), (idx[-1] + 1) * frame + round(keep_tail_s * rate))
    y = x[start:end].copy()

    # speech frames of the trimmed clip (frame grid kept), for the RMS after each gain stage
    mask = np.zeros(len(x), dtype=bool)
    mask[: act.size * frame] = np.repeat(act, frame)
    speech = mask[start:end]
    target = _amp(target_rms_dbfs)
    ceiling = _amp(peak_ceiling_dbfs)
    budget = _amp(MAX_GAIN_DB)
    for _ in range(3):  # the limiter takes back a little level: make it up, at most twice more
        level = float(np.sqrt(np.mean(y[speech] ** 2)))
        if level <= 0 or _db(level) >= target_rms_dbfs - 0.3:
            break
        gain = min(target / level, budget)
        if gain <= 1.0001:
            break
        budget /= gain
        y = _limit(y * gain, ceiling, rate)
    y = _limit(y, ceiling, rate)  # also when no gain was needed: a loud input keeps the -3 dBFS ceiling

    n_in = min(len(y), max(1, round(FADE_IN_S * rate)))
    n_out = min(len(y), max(1, round(FADE_OUT_S * rate)))
    y[:n_in] *= np.linspace(0.0, 1.0, n_in, endpoint=False) + 1.0 / n_in
    y[len(y) - n_out :] *= np.linspace(1.0, 0.0, n_out)

    pcm = np.clip(np.round(y * 32767.0), -32768, 32767).astype("<i2").tobytes()
    return AudioClip(pcm, rate)
