"""Who is in which car, as the radio may say it (F1 Participants).

``Roster.label(car)`` is one of:

* ``("driver", "Norris")`` - the car is AI-controlled **and** its driver id is in EA's driver table
  (``enums.DRIVERS``): the name comes from ``enums.DRIVER_RADIO_NAMES``, never from the packet. This also works on
  scrubbed fixtures, where the packet names are ``Driver NN`` but the driver ids are intact;
* ``("team", "the Williams")`` - the team id is in the spec's team table (the year suffix dropped);
* ``("number", "car 23")`` - the race number is known;
* ``("car", <fallback>)`` - nothing else ("the car ahead").

``Roster.personal(car)`` is True when a car's packet name is personal data: a human (``ai_controlled`` False), a car
whose control is unknown, or a driver id of 255 / 65535 (a network human - and in F1 World races the AI cars too, which
carry real players' online IDs [measured]).

Privacy invariant (pinned by ``tests/unit/test_raceradio_roster.py``): packet names are read only here, and the only
accessor that returns one is ``personal_name`` (for an opt-in answer path; nothing proactive uses it). Labels, calls,
views, facts, ``repr`` and logs never carry a packet name.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pitwall.adapters.f1 import enums
from pitwall.model.telemetry import Participant, Participants

LABEL_KINDS = ("driver", "team", "number", "car")
_YEAR_SUFFIX = re.compile(r"\s*'\d\d$")
GENERIC_NAME = re.compile(r"^(?:player|driver)\b", re.I)  # placeholders ("Player", "Driver 03"): never a person's name


def team_label(team_id: int | None) -> str | None:
    """ "the Williams" for a team id in the spec's table (year suffix dropped), else None."""
    if team_id is None:
        return None
    name = enums.TEAMS.get(team_id)
    if name is None or name in ("F1 Generic", "F1 Custom Team"):
        return None  # every car of an F1 World / custom grid shares it: it tells the cars apart no better than "a car"
    return "the " + _YEAR_SUFFIX.sub("", name)


class Roster:
    """The latest Participants table of the session (worker thread only)."""

    __slots__ = ("_cars", "player_index")

    def __init__(self) -> None:
        self._cars: dict[int, Participant] = {}
        self.player_index: int | None = None

    def __repr__(self) -> str:  # never the names
        return f"Roster(cars={len(self._cars)}, player_index={self.player_index})"

    def update(self, p: Participants) -> None:
        self._cars = {c.car_index: c for c in p.cars}
        self.player_index = p.player_index

    def __len__(self) -> int:
        return len(self._cars)

    def known(self) -> Iterable[int]:
        return self._cars.keys()

    def label(self, car_index: int | None, fallback: str = "a car") -> tuple[str, str]:
        """(kind, words) for ``car_index`` (see module docstring); ``fallback`` for an unknown car."""
        c = self._cars.get(car_index) if car_index is not None else None
        if c is None:
            return "car", fallback
        if c.ai_controlled is True and c.driver_id is not None:
            name = enums.DRIVER_RADIO_NAMES.get(c.driver_id)
            if name is not None:
                return "driver", name
        team = team_label(c.team_id)
        if team is not None:
            return "team", team
        if c.race_number is not None:
            return "number", f"car {c.race_number}"
        return "car", fallback

    def driver_name(self, car_index: int | None) -> str | None:
        """The official AI driver name of a car (``label`` kind "driver"), else None."""
        kind, words = self.label(car_index)
        return words if kind == "driver" else None

    def personal(self, car_index: int | None) -> bool:
        """The car's packet name is personal data (or nothing is known about the car)."""
        c = self._cars.get(car_index) if car_index is not None else None
        return c is None or c.ai_controlled is not True or c.driver_id is None

    def personal_name(self, car_index: int | None) -> str | None:
        """The packet name of a personal car, unless it is a generic placeholder. The ONLY accessor of a packet name:
        reserved for an opt-in on-request answer (never a proactive call, a fact, a log, a view or storage)."""
        if not self.personal(car_index):
            return None
        c = self._cars.get(car_index) if car_index is not None else None
        name = None if c is None else c.name.strip()
        if not name or GENERIC_NAME.match(name):
            return None
        return name
