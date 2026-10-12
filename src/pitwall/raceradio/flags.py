"""Flags and race control (group ``flags``, F1): red flag, safety car / VSC, yellow ahead, yellow here, blue.

* **Red flag** - RDFL, any mode but off, once per flag (a second RDFL within ``RED_FLAG_DEDUPE_S`` is the same one).
  The radio's first urgent call (``voice.urgent``): no group toggle, no speak window, quiet mode or intensity holds
  it. [synthetic]
* **Safety car / VSC** (races) - the Session packet's ``safetyCarStatus`` (2 Hz) and the SCAR event (types 1 full / 2
  virtual; events 0 deployed, 1 returning, 2 returned, 3 resume). SCAR type 0 and 3 (formation lap) are ignored [M]:
  real captures send them at the formation lap and an online start. One deployed / ending / green call per neutral
  period; a Session packet that contradicts a SCAR edge within ``SCAR_LAG_S`` is the 2 Hz packet lagging, not a new
  period. Green only on SCAR "resume" (3) or a Session status of none: "returned" (2) is the safety car entering the
  pit lane, and the field may not race until the line (F1 infringement 36, overtaking under the safety car). After a
  period closes the Session packet must read none before it can open another one (it lags the SCAR events); a SCAR
  "deployed" always does. [synthetic: no real capture has a safety car]
* **Yellow ahead** - a marshal zone showing yellow whose start lies ``YELLOW_MIN_AHEAD_M`` .. min(max(``YELLOW_NEAR_M``,
  ``YELLOW_LEAD_S`` x speed), ``YELLOW_MAX_M``) ahead of the car, once per zone and lap, at most every
  ``YELLOW_COOLDOWN_S``. A zone that turned yellow with the player inside it, less than ``YELLOW_MIN_AHEAD_M`` past its
  start or slow in the last ``YELLOW_SLOW_S`` is the player's own incident and never called while it stays yellow [M:
  most real yellows]. Where: the first corner of the learned track model in the zone, else the sector. Not under a
  safety car / VSC or red flag, in the pits or under ``YELLOW_MIN_KPH``. [recorded]
* **Yellow here** - the player's own FIA flag turning yellow, at most every ``YELLOW_HERE_GAP_S``, not within
  ``YELLOW_SLOW_S`` of being slow or of a flashback, not in the pits (0-3 calls a race with these guards, up to 14 in
  two laps without [M]); not under a safety car / VSC or red flag either (the whole track is neutralised). Confirmed
  ``YELLOW_HERE_CONFIRM_S`` later: still yellow, the car never slow and its damage unchanged meanwhile - real F1 25
  turns the player's own flag yellow in the very packet of the player's own crash [M: the Austria 71-lap run].
  [recorded]
* **Blue** - the player's own FIA flag blue for ``BLUE_HOLD_S``; one call per episode, at most every
  ``BLUE_COOLDOWN_S``. Never from the marshal zones: only 9 % of the player's real blue-flag samples had the zone at
  the car showing blue [M]. [recorded]

Not said: the green flag after a yellow (FIA 1), DRS enabled/disabled, double yellow (not on the wire).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from pitwall.analysis.track_skeleton import Zone
from pitwall.coach.cues import cue_labels
from pitwall.model.telemetry import CarFrame, GameEvent, SessionInfo
from pitwall.raceradio import wording as W
from pitwall.raceradio.model import CallSpec
from pitwall.raceradio.state import RaceState

NEUTRAL = ("full", "virtual")
SCAR_TYPES = {1: "full", 2: "virtual"}  # SCAR safetyCarType: 0 none and 3 formation lap are ignored [M]
SCAR_DEPLOYED, SCAR_RETURNING, SCAR_RETURNED, SCAR_RESUME = 0, 1, 2, 3
SCAR_LAG_S = 3.0  # [H] a Session packet (2 Hz) this soon after a SCAR edge is not believed over it
RED_FLAG_DEDUPE_S = 60.0
RED_FLAG_TTL_S = 15.0
RED_FLAG_TIMEOUT_S = 300.0  # as core.live: a red flag with no restart is assumed over after this
SC_TTL_S = 20.0
GREEN_TTL_S = 10.0
YELLOW_MIN_AHEAD_M = 150.0  # [H]
YELLOW_NEAR_M = 300.0  # [H]
YELLOW_LEAD_S = 10.0  # [H]
YELLOW_MAX_M = 1200.0  # [H]
YELLOW_MIN_KPH = 60.0  # [H]
YELLOW_COOLDOWN_S = 15.0  # [H]
YELLOW_SLOW_S = 10.0  # [H; M]
YELLOW_HERE_GAP_S = 30.0  # [H; M]
YELLOW_TTL_MAX_S = 15.0
YELLOW_HERE_TTL_S = 8.0
YELLOW_HERE_CONFIRM_S = 1.0  # [H; M] the player's own crash turns its FIA flag yellow in the same packet
YELLOW_EVAL_S = 0.1  # yellow ahead is evaluated at most 10 times a second
SLOW_KPH = 80.0  # [H] "slow": a spin, an off, a crash
BLUE_HOLD_S = 0.5  # [M: blue flickers 2 <-> 3/1/0]
BLUE_COOLDOWN_S = 30.0  # [H; M]
BLUE_TTL_S = 8.0
CORNER_LEAD_M = 15.0  # as voice.hub: a corner starts a little before its learned entry


class FlagWatcher:
    def __init__(self) -> None:
        self._red_t = -math.inf
        self.sc_status: str | None = None
        self.period = 0
        self._open = False
        self._period_kind: str | None = None
        self._period_calls: set[str] = set()
        self._scar_t = -math.inf
        self._need_none = False  # a period closed: the Session packet must read "none" before it opens another
        self._zone_flags: dict[int, str | None] = {}
        self._own: set[int] = set()
        self._called: set[tuple[int, int | None]] = set()
        self._last_yellow = -math.inf
        self._eval_t = -math.inf
        self._fia: str | None = None
        self._fia_since = -math.inf
        self._blue_episode_called = False
        self._last_blue = -math.inf
        self._here_since: float | None = None  # the player's FIA flag turned yellow (waiting for the confirmation)
        self._here_damage: object = None  # the damage values just before it did
        self._last_damage: object = None  # the previous frame's damage values
        self.yellow_ahead: dict[str, Any] | None = None  # the view's flags.yellow_ahead

    # ------------------------------------------------------------------ session
    def on_session(self, st: RaceState, info: SessionInfo, out: list[CallSpec]) -> None:
        status = info.safety_car_status
        if status == "none":
            self._need_none = False
        if status is not None and st.t - self._scar_t >= SCAR_LAG_S:
            self.sc_status = status
            if status in NEUTRAL and not self._open and not self._need_none:
                self._deploy(st, status, out)
            elif status == "none" and self._open:
                self._green(st, out)
        self._zones(st)

    def _zones(self, st: RaceState) -> None:
        """Marshal zones that turned yellow: the player's own incident when they were at or just past it, or slow."""
        sk = st.skeleton
        if sk is None or not sk.marshal_zones or sk.track_length_m is None:
            return
        f = st.frame
        pos = None if f is None else sk.position_m(f.lap_distance_m)
        for z in sk.marshal_zones:
            before = self._zone_flags.get(z.index)
            self._zone_flags[z.index] = z.flag
            if z.flag != "yellow":
                self._own.discard(z.index)
                continue
            if before == "yellow":
                continue
            past = None if pos is None else (pos - z.start_m) % sk.track_length_m
            if (
                (pos is not None and z.contains(pos))
                or (past is not None and past < YELLOW_MIN_AHEAD_M)
                or st.t - st.slow_t < YELLOW_SLOW_S
            ):
                self._own.add(z.index)

    # ------------------------------------------------------------------ events
    def on_event(self, st: RaceState, e: GameEvent, out: list[CallSpec]) -> None:
        code = e.code
        if code == "RDFL":
            if st.mode != "off" and st.t - self._red_t >= RED_FLAG_DEDUPE_S:
                self._red_t = st.t
                text, simple = W.RED_FLAG
                out.append(
                    CallSpec(
                        group="flags",
                        call="red_flag",
                        kind="alert",
                        priority="urgent",
                        text=text,
                        text_simple=simple,
                        ttl_s=RED_FLAG_TTL_S,
                        needs_window=False,
                        bypass_quiet=True,
                    )
                )
            st.red_flag_t = st.t
        elif code in ("LGOT", "SSTA", "SEND"):
            st.red_flag_t = None
        elif code == "SCAR":
            kind = SCAR_TYPES.get(e.payload.get("safetyCarType", -1))
            ev = e.payload.get("eventType")
            if kind is None:
                return  # type 0 (none) and 3 (formation lap): real captures send these at starts [M]
            self._scar_t = st.t
            if ev == SCAR_DEPLOYED:
                self.sc_status = kind
                if not self._open:
                    self._deploy(st, kind, out)
            elif ev == SCAR_RETURNING:
                if self._open and "ending" not in self._period_calls:
                    self._period_calls.add("ending")
                    full = (self._period_kind or kind) == "full"
                    text, simple = W.SC_ENDING if full else W.VSC_ENDING
                    self._say(st, out, "sc_ending", text, simple, SC_TTL_S, bypass=False, data={"type": kind})
            elif ev == SCAR_RESUME:  # "returned" (2) is the car entering the pit lane: no racing until the line
                self.sc_status = "none"
                if self._open:
                    self._green(st, out)

    def _deploy(self, st: RaceState, kind: str, out: list[CallSpec]) -> None:
        self.period += 1
        self._open = True
        self._period_kind = kind
        self._period_calls = {"deployed"}
        st.neutral = kind
        text, simple = W.SC_DEPLOYED if kind == "full" else W.VSC_DEPLOYED
        call = "sc_deployed" if kind == "full" else "vsc_deployed"
        self._say(st, out, call, text, simple, SC_TTL_S, bypass=True, data={"type": kind, "period": self.period})

    def _green(self, st: RaceState, out: list[CallSpec]) -> None:
        self._open = False
        self._need_none = True
        st.neutral = None
        if "green" not in self._period_calls:
            self._period_calls.add("green")
            text, simple = W.GREEN
            self._say(st, out, "green", text, simple, GREEN_TTL_S, bypass=False, data={"period": self.period})

    @staticmethod
    def _say(
        st: RaceState,
        out: list[CallSpec],
        call: str,
        text: str,
        simple: str,
        ttl: float,
        *,
        bypass: bool,
        data: dict[str, Any],
    ) -> None:
        if not st.race:
            return  # the safety car is a race thing (practice and qualifying flags come as yellows / red)
        out.append(
            CallSpec(
                group="flags",
                call=call,
                kind="alert",
                priority="high",
                text=text,
                text_simple=simple,
                ttl_s=ttl,
                bypass_quiet=bypass,
                topic="race:sc",
                data=data,
            )
        )

    # ------------------------------------------------------------------ frames
    def on_frame(self, st: RaceState, f: CarFrame, out: list[CallSpec]) -> None:
        t = st.t
        if st.red_flag_t is not None and t - st.red_flag_t > RED_FLAG_TIMEOUT_S and not st.in_pits:
            st.red_flag_t = None
        fia = f.fia_flag
        if fia != self._fia:
            self._fia = fia
            self._fia_since = t
            self._blue_episode_called = False
            self._here_since = t if fia == "yellow" else None
            self._here_damage = self._last_damage  # before this frame: a crash in this very packet counts
        self._last_damage = f.damage
        if self._here_since is not None and t - self._here_since >= YELLOW_HERE_CONFIRM_S:
            since, self._here_since = self._here_since, None
            if st.slow_t < since and f.damage == self._here_damage:  # not the player's own crash or spin
                self._yellow_here(st, f, out, since)
        if fia == "blue" and not self._blue_episode_called and t - self._fia_since >= BLUE_HOLD_S:
            self._blue_episode_called = True
            if t - self._last_blue >= BLUE_COOLDOWN_S and not st.in_pits and st.mode != "off":
                self._last_blue = t
                text, simple = W.BLUE_RACE if st.race else W.BLUE_SESSION
                out.append(
                    CallSpec(
                        group="flags",
                        call="blue_flag",
                        kind="alert",
                        priority="high",
                        text=text,
                        text_simple=simple,
                        ttl_s=BLUE_TTL_S,
                        topic="race:blue",
                    )
                )
        if t - self._eval_t >= YELLOW_EVAL_S:
            self._eval_t = t
            self._yellow_ahead(st, f, out)

    @staticmethod
    def _calm(st: RaceState) -> bool:
        return st.neutral is None and st.red_flag_t is None and not st.in_pits and st.mode in ("race", "session")

    def _yellow_here(self, st: RaceState, f: CarFrame, out: list[CallSpec], since: float) -> None:
        t = st.t
        if not self._calm(st) or t - self._last_yellow < YELLOW_HERE_GAP_S:
            return
        if since - st.slow_t < YELLOW_SLOW_S or since - st.flbk_t < YELLOW_SLOW_S:
            return  # the player's own spin / crash, or the flashback undoing it [M]
        self._last_yellow = t
        corner = self._corner_at(st, f.lap_distance_m)
        text, simple = W.yellow_here(corner)
        out.append(
            CallSpec(
                group="flags",
                call="yellow_here",
                kind="alert",
                priority="high",
                text=text,
                text_simple=simple,
                ttl_s=YELLOW_HERE_TTL_S,
                topic="race:yellow",
                data={"corner": corner},
            )
        )

    def _yellow_ahead(self, st: RaceState, f: CarFrame, out: list[CallSpec]) -> None:
        sk = st.skeleton
        v = f.speed_kph
        self.yellow_ahead = None
        if sk is None or not sk.marshal_zones or sk.track_length_m is None or v is None or not math.isfinite(v):
            return
        pos = sk.position_m(f.lap_distance_m)
        if pos is None:
            return
        length = sk.track_length_m
        yellow = sorted(
            ((z, (z.start_m - pos) % length) for z in sk.marshal_zones if z.flag == "yellow"), key=lambda za: za[1]
        )
        if not yellow:
            return
        first, first_m = yellow[0]
        self.yellow_ahead = {"zone": first.game_number, "ahead_m": round(first_m), "corner": None}
        if not self._calm(st) or v < YELLOW_MIN_KPH:
            return
        mps = v / 3.6
        window = min(max(YELLOW_NEAR_M, YELLOW_LEAD_S * mps), YELLOW_MAX_M)
        for z, ahead in yellow:
            if z.index in self._own:
                continue
            key = (z.game_number, st.lap)
            if key in self._called or not YELLOW_MIN_AHEAD_M <= ahead <= window:
                continue
            self._called.add(key)
            if st.t - self._last_yellow < YELLOW_COOLDOWN_S:
                continue
            self._last_yellow = st.t
            corner = self._corner_in(st, z)
            sector = None
            if corner is None:
                s = sk.sector_of(z.start_m)
                sector = None if s is None else s + 1
            self.yellow_ahead = {"zone": z.game_number, "ahead_m": round(ahead), "corner": corner}
            text, simple = W.yellow_ahead(corner, sector)
            out.append(
                CallSpec(
                    group="flags",
                    call="yellow_ahead",
                    kind="alert",
                    priority="high",
                    text=text,
                    text_simple=simple,
                    ttl_s=min(YELLOW_TTL_MAX_S, ahead / mps + 2.0),
                    topic="race:yellow",
                    data={"zone": z.game_number, "ahead_m": round(ahead), "corner": corner, "sector": sector},
                )
            )
            return

    # ------------------------------------------------------------------ corner names (the names cues use)
    @staticmethod
    def _corners(st: RaceState) -> tuple[list[Mapping[str, Any]], dict[str, str]]:
        model = st.track_model() if st.track_model is not None else None
        if not isinstance(model, Mapping):
            return [], {}
        corners = [c for c in model.get("corners") or [] if isinstance(c, Mapping)]
        labels = {name: lab.text for name, lab in cue_labels(model).items()}
        return corners, labels

    def _corner_in(self, st: RaceState, z: Zone) -> str | None:
        """The first corner of the learned track model whose entry lies in zone ``z`` (lap order from its start)."""
        sk = st.skeleton
        corners, labels = self._corners(st)
        if sk is None or sk.track_length_m is None or not corners:
            return None
        length = sk.track_length_m
        inside: list[tuple[float, str]] = []
        for c in corners:
            entry, name = c.get("entry_m"), c.get("name")
            if not isinstance(entry, int | float) or not isinstance(name, str):
                continue
            p = sk.position_m(float(entry))
            if p is not None and z.contains(p):
                inside.append(((p - z.start_m) % length, labels.get(name, name)))
        return min(inside)[1] if inside else None

    def _corner_at(self, st: RaceState, d: float | None) -> str | None:
        """The corner of the learned track model the car is in (its braking zone to its exit), else None."""
        if d is None:
            return None
        corners, labels = self._corners(st)
        for c in corners:
            entry, exit_, name = c.get("entry_m"), c.get("exit_m"), c.get("name")
            if not (isinstance(entry, int | float) and isinstance(exit_, int | float) and isinstance(name, str)):
                continue
            if entry - CORNER_LEAD_M <= d <= exit_:
                return labels.get(name, name)
        return None
