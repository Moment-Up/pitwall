"""Online players' names in "who's ahead?" answers: an opt-in household setting, off by default (race-radio spec P2).

Proactive calls never say a personal name (``raceradio.roster``). With ``SettingsStore`` section ``race_radio``
``{"online_names": true}`` the answer to "who's ahead?" / "who's behind?" may say the online ID of the car ahead or
behind when the race radio has no official AI driver name for it, unless the game sends a generic placeholder
("Player", "Driver 03"). The name lives only in memory and in that one spoken answer:

* ``LiveState.race_roster`` holds a ``NeighbourNames`` for the live session (set by the race radio worker; never in a
  snapshot, never serialised, its ``repr`` empty of names);
* the radio hub marks the answer ``meta.personal``: its history and observers keep "[online name]" in place of the
  name, the after-send audio check is skipped, and the audio comes from the fallback voice (``say``), so the neural
  engine's dropped-word warning can never log it (a device voice speaks it on the device);
* nothing writes it to the database, the logs or ``/api/voice/status``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pitwall.raceradio import answers

if TYPE_CHECKING:
    from pitwall.ai.facts import FactSheet
    from pitwall.raceradio.engine import RaceRadioEngine

SECTION = "race_radio"
REDACTED = "[online name]"
_BEHIND = re.compile(r"\b(behind|chasing|following)\b", re.I)


def online_names_enabled(section: Mapping[str, Any] | None) -> bool:
    """The household setting; anything but an explicit true is off."""
    return isinstance(section, Mapping) and section.get("online_names") is True


class NeighbourNames:
    """The online name of the live session's car ahead or behind (worker-owned engine state, read from the loop: one
    int and two dict lookups, safe without a lock in CPython). Never serialised; ``repr`` carries no name."""

    __slots__ = ("_engine",)

    def __init__(self, engine: RaceRadioEngine) -> None:
        self._engine = engine

    def __repr__(self) -> str:
        return "NeighbourNames()"

    @property
    def session_id(self) -> str:
        return self._engine.session_id

    def name(self, side: str, car_index: int | None = None) -> str | None:
        """The personal name of the car on ``side`` ("ahead" | "behind"), None for an official AI driver, a generic
        placeholder or an unknown car. ``car_index``: the car the answer's position and gap are about (the snapshot's,
        up to 0.5 s old); a different car on that side now gives None, never one car's name with another's gap."""
        eng = self._engine
        gaps = eng.rivals.gaps
        idx = (gaps.ahead if side == "ahead" else gaps.behind).car_index
        if idx is None or car_index is None or idx != car_index:
            return None
        roster = eng.st.roster
        if roster.label(idx)[0] == "driver":
            return None  # the official name is said already
        return roster.personal_name(idx)


def side_of(question: str | None) -> str:
    return "behind" if _BEHIND.search(question or "") else "ahead"


def personal_who(sheet: FactSheet, question: str | None, names: NeighbourNames) -> tuple[str, str] | None:
    """(answer, name): "<name> is ahead, P4, 1.2 seconds." from the race facts with the online name of that same car
    for the label; None for "who's leading?" (the leader is not a neighbour), the player leading, or no such name."""
    if answers.asks_leader(question):
        return None
    side = side_of(question)
    d = answers.race_fact(sheet, side)
    pos = answers.race_fact(sheet, "position")
    if d is None or (pos is not None and pos.get("position") == 1 and side == "ahead"):
        return None
    idx = d.get("car_index")
    name = names.name(side, idx if isinstance(idx, int) and not isinstance(idx, bool) else None)
    if not name:
        return None
    return answers.neighbour_text({**d, "label": name, "label_kind": "name"}, side), name


def redact(text: str, name: str) -> str:
    return text.replace(name, REDACTED)
