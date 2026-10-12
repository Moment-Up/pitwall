"""Penalties and warnings (group ``penalties``; F1 races, practice and qualifying): the player's PENA, DTSV, SGSV.

Per penalty type (EA spec section 8.10; the words in ``wording``):

=====================================  ========================  =======================  ============
type                                   call                      kind                     bypass quiet
=====================================  ========================  =======================  ============
0 drive-through, 1 stop-go, 6 DSQ,     ``penalty``               ALERT HIGH               yes
17 black flag timer
4 time (``time`` s; 255 = not set),    ``penalty``               ALERT HIGH               no
8 parked too long, 9 tyre regulations
2 grid penalty, 7 formation lap        ``penalty``               RACE NORMAL              no
3 reminder                             ``serve_reminder``        ALERT HIGH               yes
5 warning                              ``warning``               RACE NORMAL              no
10, 12                                 not said: the lap summary already says "That lap was invalidated"
11, 13                                 ``next_lap_invalid``      RACE NORMAL              no
14, 15                                 ``previous_lap_invalid``  RACE NORMAL              no
16 retired                             not said: the player is ``retired`` (only urgent calls until a flashback)
=====================================  ========================  =======================  ============

Track-limit warnings (infringements 7-9, 25-29) say the count from LapData ``cornerCuttingWarnings``, read
``COUNT_DELAY_S`` after the PENA (the counters update in the same 0.1 s [M]); contact warnings (3, 4) say "contact". At
most one warning call every ``WARNING_EVERY_S`` [H]. Never said: how many warnings are left before a penalty (EA's spec
does not say). [recorded: warnings 5/4, 5/7, 5/27; time penalties 4/3, 4/4, 4/7, 4/29; 12/28; a drive-through 0/34
and its DTSV; synthetic: the rest, including stop-go, reminders and the lap invalidations 11/13/14/15]
"""

from __future__ import annotations

import math

from pitwall.model.telemetry import GameEvent
from pitwall.raceradio import wording as W
from pitwall.raceradio.model import RECORDED_PENALTY_TYPES, CallKind, CallPriority, CallSpec
from pitwall.raceradio.state import RaceState

WARNING_EVERY_S = 20.0  # [H]
COUNT_DELAY_S = 0.3  # [M]
PENALTY_TTL_S = 30.0
MINOR_TTL_S = 20.0
BYPASS_TYPES = frozenset({0, 1, 6, 17})
ALERT_TYPES = frozenset({4, 8, 9})
RACE_TYPES = frozenset({2, 7})
SILENT_TYPES = frozenset({10, 12})
NEXT_INVALID = frozenset({11, 13})
PREVIOUS_INVALID = frozenset({14, 15})
REMINDER, WARNING, RETIRED = 3, 5, 16


class PenaltyWatcher:
    def __init__(self) -> None:
        self._last_warning = -math.inf
        self._pending: tuple[float, int | None] | None = None  # (due, infringement): a track-limit warning

    def on_event(self, st: RaceState, e: GameEvent, out: list[CallSpec]) -> None:
        p = e.payload
        me = p.get("player_idx")
        if e.code in ("DTSV", "SGSV") and p.get("vehicleIdx") == me:
            text, simple = W.served(e.code)
            spec = self._spec("penalty_served", "race", "normal", text, simple, MINOR_TTL_S, data={"code": e.code})
            spec.tier = "recorded" if e.code == "DTSV" else "synthetic"  # no real stop-go yet
            out.append(spec)
            return
        if e.code != "PENA" or p.get("vehicleIdx") != me:
            return
        ptype, inf, time_s = p.get("penaltyType"), p.get("infringementType"), p.get("time")
        if not isinstance(ptype, int):
            return
        inf = inf if isinstance(inf, int) else None
        data: dict[str, object] = {
            "penalty_type": ptype,
            "infringement": inf,
            "time_s": time_s if isinstance(time_s, int) else None,
        }
        if ptype == RETIRED:
            st.retired = True
            return
        if ptype in SILENT_TYPES or st.mode == "off":
            return
        if ptype in NEXT_INVALID:
            out.append(self._spec("next_lap_invalid", "race", "normal", W.NEXT_LAP_INVALID, None, MINOR_TTL_S, data))
        elif ptype in PREVIOUS_INVALID:
            text = W.PREVIOUS_LAP_INVALID
            out.append(self._spec("previous_lap_invalid", "race", "normal", text, None, MINOR_TTL_S, data))
        elif ptype == REMINDER:
            text, simple = W.serve_reminder(inf)
            out.append(self._spec("serve_reminder", "alert", "high", text, simple, PENALTY_TTL_S, data, bypass=True))
        elif ptype == WARNING:
            if st.t - self._last_warning < WARNING_EVERY_S:
                return
            self._last_warning = st.t
            if inf in W.TRACK_LIMIT_INFRINGEMENTS:
                self._pending = (st.t + COUNT_DELAY_S, inf)  # the counter is read once the game has updated it
            else:
                out.append(self._warning(inf, None, data))
        else:
            built = W.penalty(ptype, inf, time_s if isinstance(time_s, int) else None)
            if built is None:
                return  # a penalty type the spec does not list: never guessed
            text, simple = built
            if ptype in BYPASS_TYPES:
                spec = self._spec("penalty", "alert", "high", text, simple, PENALTY_TTL_S, data, bypass=True)
            elif ptype in ALERT_TYPES:
                spec = self._spec("penalty", "alert", "high", text, simple, PENALTY_TTL_S, data)
            else:
                spec = self._spec("penalty", "race", "normal", text, simple, MINOR_TTL_S, data)
            spec.tier = "recorded" if ptype in RECORDED_PENALTY_TYPES else "synthetic"
            out.append(spec)

    def tick(self, st: RaceState, out: list[CallSpec]) -> None:
        pending = self._pending
        if pending is None or st.t < pending[0]:
            return
        self._pending = None
        f = st.frame
        count = None if f is None or f.penalties is None else f.penalties.corner_cutting_warnings
        out.append(self._warning(pending[1], count, {"penalty_type": WARNING, "infringement": pending[1]}))

    def _warning(self, inf: int | None, count: int | None, data: dict[str, object]) -> CallSpec:
        text, simple = W.warning(inf, count)
        spec = self._spec("warning", "race", "normal", text, simple, MINOR_TTL_S, {**data, "track_limits": count})
        spec.topic = "race:warning"
        return spec

    @staticmethod
    def _spec(
        call: str,
        kind: CallKind,
        priority: CallPriority,
        text: str,
        simple: str | None,
        ttl: float,
        data: dict[str, object],
        *,
        bypass: bool = False,
    ) -> CallSpec:
        return CallSpec(
            group="penalties",
            call=call,
            kind=kind,
            priority=priority,
            text=text,
            text_simple=simple,
            ttl_s=ttl,
            bypass_quiet=bypass,
            data=dict(data),
        )
