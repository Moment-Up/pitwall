"""Car health call settings (household; ``SettingsStore`` section ``"car_health"``).

``{"tyre_calls": true, "wear_calls": true, "fuel_calls": true, "slip_calls": "detailed"}``: the first three switch the
cold-tyre, wear and fuel calls on or off; ``slip_calls`` is ``"off"``, ``"detailed"`` (lock-up and wheelspin notes on
the detailed radio only, the default) or ``"normal"`` (also at the normal intensity). Coaching intensity and voice
stay per driver (``drivers.DriverPreferences``). Immutable: the worker swaps the whole object through a store
listener.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

SECTION = "car_health"
SLIP_CHOICES = ("off", "detailed", "normal")
_BOOLS = ("tyre_calls", "wear_calls", "fuel_calls")


@dataclass(frozen=True, slots=True)
class HealthSettings:
    tyre_calls: bool = True
    wear_calls: bool = True
    fuel_calls: bool = True
    slip_calls: str = "detailed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULTS = HealthSettings()


def validate(values: Mapping[str, Any], base: HealthSettings = DEFAULTS) -> HealthSettings:
    """A partial update over ``base``; raises ``ValueError`` naming the bad key (the API answers 400)."""
    if not isinstance(values, Mapping):
        raise ValueError("settings must be an object")
    out = asdict(base)
    for k, v in values.items():
        if k in _BOOLS:
            if not isinstance(v, bool):
                raise ValueError(f"{k} must be true or false")
            out[k] = v
        elif k == "slip_calls":
            if v not in SLIP_CHOICES:
                raise ValueError(f"slip_calls must be one of {', '.join(SLIP_CHOICES)}")
            out[k] = v
        else:
            raise ValueError(f"unknown setting {k!r}")
    return HealthSettings(**out)


def from_stored(values: Mapping[str, Any] | None) -> HealthSettings:
    """The stored section, leniently: a bad or unknown value falls back to its default (never breaks start-up)."""
    out = asdict(DEFAULTS)
    for k, v in (values or {}).items():
        if (k in _BOOLS and isinstance(v, bool)) or (k == "slip_calls" and v in SLIP_CHOICES):
            out[k] = v
    return HealthSettings(**out)
