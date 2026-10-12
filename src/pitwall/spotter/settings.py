"""The ``"spotter"`` settings section (``SettingsStore``): defaults, strict validation for the API, lenient parsing of
what is stored. Off by default: the owner turns the spotter on after a live validation run (spec section 10)."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, replace
from typing import Any

log = logging.getLogger(__name__)

SECTION = "spotter"
WORDING_VALUES = ("auto", "standard", "simple")
START_DELAY_RANGE_S = (0.0, 20.0)
CAR_LENGTH_RANGE_M = (3.0, 7.0)
CAR_WIDTH_RANGE_M = (1.5, 2.5)


@dataclass(slots=True, frozen=True)
class SpotterSettings:
    enabled: bool = False  # master switch (Settings > Radio & voice > Spotter)
    audio: bool = True  # spoken calls (apply only when enabled)
    visual: bool = True  # iPad bars (apply only when enabled)
    qualifying: bool = False  # races always; qualifying and practice only when switched on; never time trial
    practice: bool = False
    start_delay_s: float = 5.0  # silent this long after lights out
    wording: str = "auto"  # auto = the seated driver's profile (simple_wording)
    voice: str | None = None  # None = the engineer's voice; a Kokoro voice name (Kokoro engine only)
    still_there: bool = True
    hold_your_line: bool = True
    car_length_m: float | None = None  # None = per formula (spotter.dims)
    car_width_m: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULTS = SpotterSettings()
_BOOL_KEYS = frozenset({"enabled", "audio", "visual", "qualifying", "practice", "still_there", "hold_your_line"})
_KEYS = frozenset(f.name for f in fields(SpotterSettings))


def _kokoro_voices() -> tuple[str, ...]:
    from pitwall.voice.tts import KOKORO_VOICES  # import here: voice.tts is heavy and optional for headless tools

    return KOKORO_VOICES


def _number(key: str, value: object, lo: float, hi: float, *, nullable: bool) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
        raise ValueError(f"{key} must be a number{' or null' if nullable else ''}")
    v = float(value)
    if not lo <= v <= hi:
        raise ValueError(f"{key} must be {lo:g}-{hi:g}, got {v:g}")
    return v


def _check(key: str, value: object) -> object:
    """One validated value (raises ``ValueError``)."""
    if key not in _KEYS:
        raise ValueError(f"unknown spotter setting {key!r}")
    if key in _BOOL_KEYS:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if key == "start_delay_s":
        return _number(key, value, *START_DELAY_RANGE_S, nullable=False)
    if key == "car_length_m":
        return _number(key, value, *CAR_LENGTH_RANGE_M, nullable=True)
    if key == "car_width_m":
        return _number(key, value, *CAR_WIDTH_RANGE_M, nullable=True)
    if key == "wording":
        if value not in WORDING_VALUES:
            raise ValueError(f"wording must be one of {', '.join(WORDING_VALUES)}")
        return value
    if key == "voice":
        voices = _kokoro_voices()
        if value is not None and value not in voices:
            raise ValueError(f"voice must be null (the engineer's voice) or one of {', '.join(voices)}")
        return value
    raise AssertionError(key)  # pragma: no cover - every field is handled above


def merge(current: SpotterSettings, update: Mapping[str, Any]) -> SpotterSettings:
    """A partial update applied strictly: an unknown key or a bad value raises ``ValueError`` (API: 422)."""
    values: dict[str, Any] = {k: _check(k, v) for k, v in update.items()}
    return replace(current, **values)


def parse_stored(section: Mapping[str, Any] | None) -> SpotterSettings:
    """The stored section, leniently: a bad or unknown stored value is dropped (default kept) and logged once."""
    out = DEFAULTS
    for k, v in (section or {}).items():
        try:
            one: dict[str, Any] = {k: _check(k, v)}
            out = replace(out, **one)
        except ValueError as e:
            log.warning("spotter setting %s ignored: %s", k, e)
    return out
