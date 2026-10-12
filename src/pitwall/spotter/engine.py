"""The spotter's state machine: pure (no threads, no I/O, no clock reads; every time comes in as an argument).

Driven by ``SpotterWorker`` (live and replays), the tests, the offline scorer (``spotter.score``) and
``scripts/spotter_check.py``. Every duration is measured on the GAME clock (header ``sessionTime``): delivery from the
console is bunched (on the owner's PS5 about 1 packet in 10 arrives 45-75 ms late, p99 ~90 ms), so three packets
arriving within 1 ms must not make a 50 ms overlap look like 1 ms. The rules are the spec's (section 3); values marked
[H] in ``SpotterParams`` are heuristics tuned on 25 real PS5 race sessions (docs/research/f1-spotter-data.md).

Per packet, when every gate is open:

1. **Who is alongside, per side, with hysteresis.** A car joins a side when it is not in line (``|lat| >= 0.5 W``),
   overlaps lengthwise (``|lon| < reach``) and is within one lane (``gap <= 2.5 m``); it stays while ``|lat| >=
   0.35 W``, ``gap <= 3.0 m`` and ``|lon| < reach + 1.5 m``. ``raw(side)`` = the side has members.
2. **Onset** after 50 ms of continuous ``raw``: "car left/right", or "three wide" when the other side is announced
   (or both reach onset in the same packet: one call). Not spoken when every member's overlap is predicted to end
   before the audio reaches the ear (``ear_latency_s + 0.15 s``): counted as ``suppressed_short``, re-checked on the
   next packet, still shown on the iPad.
3. **Clear** after 150 ms with no member and no car *arriving* on that side: one within 1.0 s of overlapping on both
   axes (lengthwise closing faster than 0.5 m/s, sideways faster than 1.0 m/s). "Clear all round" ends an episode
   that went three wide. Both sides clearing in the same packet make one call.
4. **Still there** 4 s after the side's last call, then every 6 s, at most 2 per episode; **hold your line** once
   per episode when an announced car side by side (overlapping lengthwise by half a car or more) is within 0.4 m and
   closing sideways at 0.8 m/s or more for 150 ms, at least 1 s after that side's onset.

Gates (section 3.6, the first closed one is ``reason``): a closed gate forgets all traffic and never says "clear"
(a muted spotter never says clear), with one exception: when the gate that closes leaves the positions valid (the
player slowed below 20 km/h, entered the pit lane or finished), a side announced and empty at that packet, with
nothing arriving, gets its clear (``SpotterCall.final``), so the driver is not left believing a car is still there.
"spin" closes while the player slides more than 30 degrees from the direction of travel (or travels backwards): left
and right turn with the car, so no call would mean anything; it opens again 0.3 s after the slide is back under 15
degrees (the next car alongside is a new episode; nothing is said about the traffic before the slide). A flashback,
or the game clock going back by more than 50 ms, resets and mutes for 1 s of game time. Each reset bumps ``epoch``, so
the radio forgets which onsets the driver heard.

Relative speeds (``Rel.vr`` / ``vl``) include the player's frame rotation (``spotter.geometry``), so two cars holding
a constant gap through a corner are not "closing".
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

from pitwall.model.telemetry import EventKind, SessionInfo
from pitwall.spotter.dims import CarDims, dims_for
from pitwall.spotter.geometry import Basis, Rel, relative
from pitwall.spotter.model import (
    CAR_LEFT,
    CAR_RIGHT,
    CLEAR_ALL_ROUND,
    CLEAR_LEFT,
    CLEAR_RIGHT,
    HOLD_YOUR_LINE,
    LEFT,
    RIGHT,
    SIDES,
    STILL_THERE,
    THREE_WIDE,
    DecodedMotion,
    PacketTrace,
    SpotterCall,
    SpotterState,
)
from pitwall.spotter.settings import DEFAULTS, SpotterSettings

RACE_TYPES = frozenset({15, 16, 17})
QUALIFYING_TYPES = frozenset(range(5, 15))
PRACTICE_TYPES = frozenset({1, 2, 3, 4})
TIME_TRIAL_TYPE = 18  # never: rival and PB ghost cars occupy slots (LapData tail timeTrialPBCarIdx / RivalCarIdx)
SAFETY_CAR_SILENT = frozenset({"full", "virtual", "formation_lap"})
RESULT_ACTIVE = 2
FINAL_CLEAR_GATES = frozenset({"pit", "finished", "slow"})  # the positions are still valid when these close
_EPS = 1e-6


@dataclass(slots=True, frozen=True)
class SpotterParams:
    """Every tunable of the state machine ([H] = heuristic, see the module docstring)."""

    onset_s: float = 0.05  # lane brief
    clear_s: float = 0.15  # lane brief
    lat_enter_frac: float = 0.50  # [H] |lat| >= this x W to join a side (not in line)
    lat_stay_frac: float = 0.35  # [H] ... to stay
    gap_enter_m: float = 2.5  # [H] one lane of slack, body to body
    gap_stay_m: float = 3.0  # [H]
    lon_stay_margin_m: float = 1.5  # [H] extra lengthwise reach before an alongside car counts as gone
    close_gap_m: float = 0.4  # [H] red on the iPad
    arrival_horizon_s: float = 1.0  # [H] no "clear" while a car will overlap within this
    arrival_lon_mps: float = 0.5  # [H] lengthwise closing speed that counts as arriving
    arrival_lat_mps: float = 1.0  # [H] sideways closing speed that counts as arriving
    short_margin_s: float = 0.15  # [H] an onset must outlast the ear latency by this much to be spoken
    default_ear_latency_s: float = 0.30  # coach/cues.py DEFAULT_LATENCY_S 0.25 + output allowance 0.05
    min_ear_latency_s: float = 0.1
    max_ear_latency_s: float = 1.0
    still_first_s: float = 4.0  # [H]
    still_every_s: float = 6.0  # [H]
    still_max: int = 2  # [H] per episode
    # hold your line (review of 12 Oct, 26 owner race sessions): 0.4 m / 0.5 m/s / 0.1 s on every member fired on 56
    # of 190 onsets (29%), a third of them for cars no longer overlapping lengthwise (members by the stay margin) or
    # only diagonally; with the frame's rotation, 0.8 m/s for 0.15 s and half a car of side-by-side overlap: 21 of
    # 193 (11%). Onsets, clears and recall unchanged (docs/research/f1-spotter-data.md, "Review fixes").
    hold_gap_m: float = 0.4  # [H]
    hold_closing_mps: float = 0.8  # [H]
    hold_sustain_s: float = 0.15  # [H]
    hold_after_onset_s: float = 1.0  # [H]
    hold_overlap_frac: float = 0.5  # [H] the bodies overlap lengthwise by at least this x L: side by side
    vert_max_m: float = 3.0  # [H] crossover bridges
    speed_on_kph: float = 30.0  # [H] the spotter arms above this ...
    speed_off_kph: float = 20.0  # [H] ... and disarms below this
    spin_on_deg: float = 30.0  # [H] slip (heading vs direction of travel) above this: "spin" (backwards: 180)
    spin_off_deg: float = 15.0  # [H] ... and back under this ...
    spin_calm_s: float = 0.3  # [H] ... for this long (game clock) before the gate opens again
    spin_min_mps: float = 5.0  # below this the slip angle means nothing (the "slow" gate covers it)
    rewind_s: float = 0.05  # the game clock going back by more than this = a flashback / rewind
    flashback_mute_s: float = 1.0
    traffic_hold_s: float = 1.0  # [H] proactive radio waits this long after a side cleared
    low_rate_hz: float = 30.0  # below this the status warns: set the UDP send rate to 60 Hz


PARAMS = SpotterParams()
RATE_WINDOW = 61  # session times kept for the Motion rate (about 1 s at 60 Hz)
AGE_WINDOW = 120  # receive - game clock offsets kept for the data age (about 2 s at 60 Hz)


def _sign(x: float) -> float:
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def enters(r: Rel, width_m: float, p: SpotterParams = PARAMS) -> bool:
    """The geometric ground truth for one car (and the rule to join a side): not in line, overlapping lengthwise,
    within one lane. Obstacle filters (racing, not above/below) are the caller's."""
    return abs(r.lat) >= p.lat_enter_frac * width_m and abs(r.lon) < r.reach and r.gap <= p.gap_enter_m


def _clear_side_view() -> dict[str, Any]:
    return {"state": "clear", "lon_m": None, "gap_m": None, "cars": 0}


class SpotterEngine:
    """One stream's spotter. Not thread-safe: one thread feeds it (the worker); others read ``view_dict`` /
    ``state_obj``, which are immutable objects swapped whole."""

    def __init__(self, settings: SpotterSettings = DEFAULTS, params: SpotterParams = PARAMS) -> None:
        self.params = params
        self.settings = settings
        self.ear_latency_s = params.default_ear_latency_s
        self.suppressed_short = 0
        self.invalid = 0
        self.packets = 0
        self._seq = 0
        self._epoch = 0
        self._info: SessionInfo | None = None
        self.dims: CarDims = dims_for(None)
        self.trace = PacketTrace()
        self.motion_hz: float | None = None
        self.data_age_ms: float | None = None
        self.reason: str | None = "not_available" if settings.enabled else "disabled"
        self.active = False
        self.state_obj = SpotterState()
        self.view_dict: dict[str, Any] = {}
        # per session (``_new_session``)
        self._lights_out_t: float | None = None
        self._mute_pending = False
        self._mute_until: float | None = None
        self._last_t: float | None = None
        self._moving = False
        self._spinning = False
        self._spin_calm_t: float | None = None
        self._prev_basis: tuple[float, Basis] | None = None  # the frame's rotation (geometry.relative)
        self._seen_motion = False
        self._times: deque[float] = deque(maxlen=RATE_WINDOW)
        self._offsets: deque[float] = deque(maxlen=AGE_WINDOW)
        # per episode (``_reset_episode``)
        self._members: list[set[int]] = [set(), set()]
        self._raw = [False, False]
        self._since: list[float | None] = [None, None]
        self._announced = [False, False]
        self._episode_three = False
        self._onset_t: list[float | None] = [None, None]
        self._last_call_t: list[float | None] = [None, None]
        self._last_call_still = [False, False]
        self._still_count = 0
        self._hold_since: float | None = None
        self._hold_said = False
        self._suppressed_ep = [False, False]
        self._last_occ_t: list[float | None] = [None, None]
        self._last_seq = [0, 0]
        self._sides_view: list[dict[str, Any]] = [_clear_side_view(), _clear_side_view()]
        self._new_session()
        self._publish(None)

    # ------------------------------------------------------------------ inputs
    def apply_settings(self, settings: SpotterSettings) -> None:
        self.settings = settings
        self._update_dims()
        if not settings.enabled:
            self._reset_episode()
            self.active = False  # off: no Motion reaches the engine until it is on again (the worker skips it)
            self.reason = "disabled"
        self._publish(None)

    def set_ear_latency(self, seconds: float) -> None:
        """Fire -> heard, measured by the radio hub; clamped to 0.1-1.0 s."""
        if math.isfinite(seconds):
            p = self.params
            self.ear_latency_s = min(p.max_ear_latency_s, max(p.min_ear_latency_s, seconds))

    def feed_session(self, info: SessionInfo) -> None:
        self._info = info
        self._update_dims()

    def feed_event(self, kind: EventKind | str, session_time_s: float | None) -> None:
        k = kind.value if isinstance(kind, EventKind) else str(kind)
        if k == EventKind.LIGHTS_OUT.value:
            self._lights_out_t = session_time_s if session_time_s is not None and math.isfinite(session_time_s) else 0.0
        elif k == EventKind.FLASHBACK.value:
            self._reset_episode()
            self._mute_pending = True
            self._prev_basis = None
            self._publish(None)
        elif k in (EventKind.SESSION_STARTED.value, EventKind.SESSION_ENDED.value):
            self._reset_episode()
            self._lights_out_t = None
            self._last_t = None
            self._prev_basis = None
            self._publish(None)

    def reset(self) -> None:
        """A new (or no) session: forget everything about the old one."""
        self._new_session()
        self._info = None
        self._update_dims()
        self.reason = "not_available" if self.settings.enabled else "disabled"
        self.active = False
        self._publish(None)

    def mark_stale(self) -> None:
        """No Motion for 250 ms of receive time (the worker's queue timeout): Motion is sent only while the player
        is in control. Forget the traffic, say nothing."""
        if not self._seen_motion:
            return
        self._reset_episode()
        if self.settings.enabled:
            self.reason = "stale"
        self.active = False
        self._publish(None)

    # ------------------------------------------------------------------ the packet
    def feed_motion(self, m: DecodedMotion, now_ns: int, *, red_flag: bool = False) -> list[SpotterCall]:
        """One decoded Motion packet; returns the calls decided on it. ``now_ns`` is the decision time (t1)."""
        p = self.params
        s = self.settings
        self.packets += 1
        self._seen_motion = True
        t = m.session_time_s
        self._track_rate(m)
        if self._last_t is not None and t < self._last_t - p.rewind_s:
            self._reset_episode()  # flashback / restart: the game clock went back
            self._mute_until = t + p.flashback_mute_s
            self._prev_basis = None
        elif self._mute_pending:
            self._mute_until = t + p.flashback_mute_s
        self._mute_pending = False
        self._last_t = t
        trace = self.trace
        trace.gt = (False, False)
        trace.announced = (False, False)
        trace.gate_open = False
        trace.speed_kph = None
        if not s.enabled:
            self._close("disabled")
            return []
        b, rels = relative(m, self.dims.length_m, self.dims.width_m, p.vert_max_m, self._prev_basis)
        if b is None:
            self.invalid += 1  # skipped: counted, no state change
            self._prev_basis = None
            return []
        self._prev_basis = (t, b)
        speed = b.speed_kph
        trace.speed_kph = speed
        self._moving = speed >= (p.speed_off_kph if self._moving else p.speed_on_kph)
        self._update_spin(b, t)
        reason = self._gate(m, t, red_flag)
        if reason is not None:
            final = self._final_clears(reason, t, rels, m, now_ns)
            self._close(reason)
            return final
        self.active = True
        self.reason = None
        trace.gate_open = True
        calls = self._step(t, rels, m, now_ns)
        trace.announced = (self._announced[LEFT], self._announced[RIGHT])
        return calls

    # ------------------------------------------------------------------ outputs
    def view(self) -> dict[str, Any]:
        """The live snapshot's ``spotter`` block (spec section 8.3)."""
        return self.view_dict

    def state(self) -> SpotterState:
        return self.state_obj

    @property
    def send_rate_low(self) -> bool:
        return self.motion_hz is not None and self.motion_hz < self.params.low_rate_hz

    # ------------------------------------------------------------------ internals
    def _new_session(self) -> None:
        self._lights_out_t = None
        self._mute_pending = False
        self._mute_until = None
        self._last_t = None
        self._moving = False
        self._spinning = False
        self._spin_calm_t = None
        self._prev_basis = None
        self._seen_motion = False
        self._times = deque(maxlen=RATE_WINDOW)
        self._offsets = deque(maxlen=AGE_WINDOW)
        self.motion_hz = None
        self.data_age_ms = None
        self._reset_episode()

    def _reset_episode(self) -> None:
        self._epoch += 1
        self._members = [set(), set()]
        self._raw = [False, False]
        self._since = [None, None]
        self._announced = [False, False]
        self._episode_three = False
        self._onset_t = [None, None]
        self._last_call_t = [None, None]
        self._last_call_still = [False, False]
        self._still_count = 0
        self._hold_since = None
        self._hold_said = False
        self._suppressed_ep = [False, False]
        self._last_occ_t = [None, None]
        self._last_seq = [0, 0]
        self._sides_view = [_clear_side_view(), _clear_side_view()]

    def _update_dims(self) -> None:
        info = self._info
        s = self.settings
        self.dims = dims_for(None if info is None else info.formula, s.car_length_m, s.car_width_m)

    def _track_rate(self, m: DecodedMotion) -> None:
        t = m.session_time_s
        times = self._times
        if times and t < times[-1] - self.params.rewind_s:
            times.clear()
        times.append(t)
        if len(times) >= 10:
            steps = [b - a for a, b in zip(times, list(times)[1:], strict=False) if 0.0 < b - a < 1.0]
            total = sum(steps)
            self.motion_hz = len(steps) / total if steps and total > 0 else self.motion_hz
        offset = m.t_recv_ns / 1e9 - t
        self._offsets.append(offset)
        self.data_age_ms = (offset - min(self._offsets)) * 1000.0

    def _gate(self, m: DecodedMotion, t: float, red_flag: bool) -> str | None:
        """The first closed gate after "disabled" (spec section 3.6), else None. "stale" is the worker's."""
        s = self.settings
        status = m.status
        if status is None or m.player_index >= len(status):
            return "not_available"  # no LapData yet: who is racing (and whether we are) is unknown
        info = self._info
        stype = None if info is None else info.extra.get("session_type_id")
        if not (
            stype in RACE_TYPES
            or (s.qualifying and stype in QUALIFYING_TYPES)
            or (s.practice and stype in PRACTICE_TYPES)
        ):
            return "session_type"
        if red_flag:
            return "red_flag"
        sc = None if info is None else info.safety_car_status
        if sc is None or sc in SAFETY_CAR_SILENT:
            return "safety_car"  # unknown stays unknown: silent until the session says there is none
        lo = self._lights_out_t
        if stype in RACE_TYPES and lo is not None and lo <= t < lo + s.start_delay_s:
            return "start"
        extra = info.extra if info is not None else {}
        if extra.get("game_paused") or extra.get("is_spectating"):
            return "paused"
        if self._mute_until is not None and t < self._mute_until:
            return "flashback"
        pit, _drv, res = status[m.player_index]
        if pit != 0:
            return "pit"
        if res != RESULT_ACTIVE:
            return "finished"
        if self._spinning:
            return "spin"
        if not self._moving:
            return "slow"
        return None

    def _update_spin(self, b: Basis, t: float) -> None:
        """The "spin" gate's state, with hysteresis: slip above ``spin_on_deg`` (or travelling backwards) closes it;
        it opens once the slip stays at or under ``spin_off_deg`` for ``spin_calm_s`` of game time."""
        p = self.params
        v, f, r = b.v, b.f, b.r
        vf = v[0] * f[0] + v[1] * f[1] + v[2] * f[2]
        vs = v[0] * r[0] + v[1] * r[1] + v[2] * r[2]
        if math.hypot(vf, vs) < p.spin_min_mps:
            self._spinning = False  # too slow for a slip angle: the "slow" gate decides
            self._spin_calm_t = None
            return
        slip = math.degrees(math.atan2(abs(vs), vf))
        if slip > p.spin_on_deg:
            self._spinning = True
            self._spin_calm_t = None
        elif self._spinning:
            if slip > p.spin_off_deg:
                self._spin_calm_t = None
            elif self._spin_calm_t is None:
                self._spin_calm_t = t
            elif t - self._spin_calm_t >= p.spin_calm_s - _EPS:
                self._spinning = False
                self._spin_calm_t = None

    def _final_clears(self, reason: str, t: float, rels: list[Rel], m: DecodedMotion, now_ns: int) -> list[SpotterCall]:
        """A gate that leaves the positions valid closes (``FINAL_CLEAR_GATES``): the clear of every announced side
        that is empty at this packet with nothing arriving (the module docstring). Called before ``_close``."""
        announced = self._announced
        if reason not in FINAL_CLEAR_GATES or not self.active or not any(announced):
            return []
        width = self.dims.width_m
        members, _gt = self._membership(rels, width)
        clear = [announced[x] and not members[x] and not self._arriving(x, rels, width) for x in (LEFT, RIGHT)]
        if not any(clear):
            return []
        if all(clear) or (self._episode_three and not any(announced[x] and not clear[x] for x in (LEFT, RIGHT))):
            return [self._call(CLEAR_ALL_ROUND, None, t, m, now_ns, final=True)]
        x = LEFT if clear[LEFT] else RIGHT
        return [self._call(CLEAR_LEFT if x == LEFT else CLEAR_RIGHT, x, t, m, now_ns, final=True)]

    def _close(self, reason: str) -> None:
        if self.active or any(self._announced) or any(self._raw):
            self._reset_episode()  # forget the traffic: no "clear" after a gate closed
        self.active = False
        self.reason = reason
        self._publish(None)

    def _short(self, members: set[int], rels: dict[int, Rel]) -> bool:
        """Every member's overlap is predicted to end before the call is heard (+ margin)."""
        limit = self.ear_latency_s + self.params.short_margin_s
        for j in members:
            r = rels[j]
            if r.vr > 0.1:
                remaining = (r.reach - r.lon) / r.vr
            elif r.vr < -0.1:
                remaining = (r.lon + r.reach) / -r.vr
            else:
                return False
            if remaining >= limit:
                return False
        return True

    def _arriving(self, side: int, rels: list[Rel], width_m: float) -> bool:
        """A car on that side will overlap (both axes) within ``arrival_horizon_s``: no "clear" yet."""
        p = self.params
        for r in rels:
            if not r.obstacle or (r.lat < 0) != (side == LEFT) or abs(r.lat) < p.lat_enter_frac * width_m:
                continue
            dl = abs(r.lon) - r.reach
            cv = -_sign(r.lon) * r.vr
            t_lon = 0.0 if dl <= 0 else (dl / cv if cv > p.arrival_lon_mps else math.inf)
            dg = r.gap - p.gap_enter_m
            cl = -_sign(r.lat) * r.vl
            t_lat = 0.0 if dg <= 0 else (dg / cl if cl > p.arrival_lat_mps else math.inf)
            if max(t_lon, t_lat) <= p.arrival_horizon_s:
                return True
        return False

    def _call(
        self,
        kind: str,
        side: int | None,
        t: float,
        m: DecodedMotion,
        now_ns: int,
        onset_ms: float | None = None,
        *,
        final: bool = False,
    ) -> SpotterCall:
        self._seq += 1
        if side is None:
            self._last_seq = [self._seq, self._seq]
        else:
            self._last_seq[side] = self._seq
        return SpotterCall(
            kind=kind,
            side=None if side is None else SIDES[side],
            seq=self._seq,
            epoch=self._epoch,
            session_time_s=t,
            t_recv_ns=m.t_recv_ns,
            t_decided_ns=now_ns,
            onset_game_ms=onset_ms,
            final=final,
        )

    def _membership(self, rels: list[Rel], width: float) -> tuple[list[set[int]], list[bool]]:
        """Who is alongside per side (join / stay hysteresis against ``_members``) and the geometric truth."""
        p = self.params
        members: list[set[int]] = [set(), set()]
        gt = [False, False]
        old = self._members
        for r in rels:
            if not r.obstacle:
                continue
            side = LEFT if r.lat < 0 else RIGHT
            if enters(r, width, p):
                gt[side] = True
                members[side].add(r.idx)
            elif (
                r.idx in old[side]
                and abs(r.lat) >= p.lat_stay_frac * width
                and r.gap <= p.gap_stay_m
                and abs(r.lon) < r.reach + p.lon_stay_margin_m
            ):
                members[side].add(r.idx)
        return members, gt

    def _step(self, t: float, rels: list[Rel], m: DecodedMotion, now_ns: int) -> list[SpotterCall]:
        p = self.params
        s = self.settings
        width = self.dims.width_m
        obst = {r.idx: r for r in rels if r.obstacle}
        members, gt = self._membership(rels, width)
        self._members = members
        self.trace.gt = (gt[LEFT], gt[RIGHT])
        raw = self._raw
        since = self._since
        for x in (LEFT, RIGHT):
            r_now = bool(members[x])
            if r_now != raw[x]:
                raw[x] = r_now
                since[x] = t
                if not r_now:
                    self._suppressed_ep[x] = False
            if r_now:
                self._last_occ_t[x] = t

        announced = self._announced
        calls: list[SpotterCall] = []
        # onsets
        ready = [False, False]
        for x in (LEFT, RIGHT):
            sx = since[x]
            if raw[x] and not announced[x] and sx is not None and t - sx >= p.onset_s - _EPS:
                if self._short(members[x], obst):
                    if not self._suppressed_ep[x]:
                        self._suppressed_ep[x] = True
                        self.suppressed_short += 1
                    continue
                ready[x] = True

        def onset_ms(x: int) -> float | None:
            sx = since[x]
            return None if sx is None else (t - sx) * 1000.0

        if ready[LEFT] and ready[RIGHT]:
            for x in (LEFT, RIGHT):
                self._announce(x, t)
            self._episode_three = True
            ms = [v for v in (onset_ms(LEFT), onset_ms(RIGHT)) if v is not None]
            calls.append(self._call(THREE_WIDE, None, t, m, now_ns, max(ms) if ms else None))
        else:
            for x in (LEFT, RIGHT):
                if not ready[x]:
                    continue
                self._announce(x, t)
                if announced[1 - x]:
                    self._episode_three = True
                    calls.append(self._call(THREE_WIDE, None, t, m, now_ns, onset_ms(x)))
                else:
                    calls.append(self._call(CAR_LEFT if x == LEFT else CAR_RIGHT, x, t, m, now_ns, onset_ms(x)))
        # clears
        clear_ready = [False, False]
        for x in (LEFT, RIGHT):
            sx = since[x]
            if (
                announced[x]
                and not raw[x]
                and (sx is None or t - sx >= p.clear_s - _EPS)
                and not self._arriving(x, rels, width)
            ):
                clear_ready[x] = True
        if clear_ready[LEFT] and clear_ready[RIGHT]:
            announced[LEFT] = announced[RIGHT] = False
            self._episode_three = False
            calls.append(self._call(CLEAR_ALL_ROUND, None, t, m, now_ns))
        else:
            for x in (LEFT, RIGHT):
                if not clear_ready[x]:
                    continue
                other = 1 - x
                announced[x] = False
                if not announced[other] and self._episode_three and not self._arriving(other, rels, width):
                    self._episode_three = False
                    calls.append(self._call(CLEAR_ALL_ROUND, None, t, m, now_ns))
                else:
                    calls.append(self._call(CLEAR_LEFT if x == LEFT else CLEAR_RIGHT, x, t, m, now_ns))
                    if not announced[other]:
                        self._episode_three = False
        # still there
        if s.still_there and self._still_count < p.still_max:
            due: list[int] = []
            for x in (LEFT, RIGHT):
                last = self._last_call_t[x]
                if announced[x] and raw[x] and last is not None:
                    wait = p.still_every_s if self._last_call_still[x] else p.still_first_s
                    if t - last >= wait - _EPS:
                        due.append(x)
            if due:
                x = min(due, key=lambda k: min(obst[j].gap for j in members[k]))
                self._still_count += 1
                for k in (LEFT, RIGHT):
                    if announced[k]:
                        self._last_call_t[k] = t
                        self._last_call_still[k] = True
                calls.append(self._call(STILL_THERE, x, t, m, now_ns))
        # hold your line
        if s.hold_your_line and not self._hold_said:
            close_side: int | None = None
            for x in (LEFT, RIGHT):
                onset_t = self._onset_t[x]
                if not announced[x] or onset_t is None or t - onset_t < p.hold_after_onset_s - _EPS:
                    continue
                for j in members[x]:
                    r = obst[j]
                    if (
                        r.gap <= p.hold_gap_m
                        and -_sign(r.lat) * r.vl >= p.hold_closing_mps
                        and r.reach - abs(r.lon) >= p.hold_overlap_frac * self.dims.length_m
                    ):
                        close_side = x
            if close_side is not None:
                if self._hold_since is None:
                    self._hold_since = t
                if t - self._hold_since >= p.hold_sustain_s - _EPS:
                    self._hold_said = True
                    calls.append(self._call(HOLD_YOUR_LINE, close_side, t, m, now_ns))
            else:
                self._hold_since = None
        if not announced[LEFT] and not announced[RIGHT]:
            self._still_count = 0
            self._hold_said = False
            self._hold_since = None
            self._last_call_t = [None, None]
            self._last_call_still = [False, False]
        # the bars: instant, no debounce
        views: list[dict[str, Any]] = []
        for x in (LEFT, RIGHT):
            mem = members[x]
            if not mem:
                views.append(_clear_side_view())
                continue
            near = min((obst[j] for j in mem), key=lambda r: abs(r.lon))
            close = any(obst[j].gap <= p.close_gap_m for j in mem)
            views.append(
                {
                    "state": "close" if close else "alongside",
                    "lon_m": round(near.lon, 1),
                    "gap_m": round(near.gap, 1),
                    "cars": len(mem),
                }
            )
        self._sides_view = views
        self._publish(t)
        return calls

    def _announce(self, x: int, t: float) -> None:
        self._announced[x] = True
        self._onset_t[x] = t
        self._last_call_t[x] = t
        self._last_call_still[x] = False

    def _traffic(self, t: float | None) -> bool:
        if not self.active:
            return False
        if any(self._raw) or any(self._announced):
            return True
        if t is None:
            return False
        hold = self.params.traffic_hold_s
        return any(last is not None and t - last < hold for last in self._last_occ_t)

    def _publish(self, t: float | None) -> None:
        s = self.settings
        traffic = self._traffic(t)
        left, right = self._sides_view if self.active else (_clear_side_view(), _clear_side_view())
        self.view_dict = {
            "v": 1,
            "enabled": s.enabled and s.visual,
            "active": self.active,
            "reason": self.reason,
            "left": left,
            "right": right,
            "three_wide": self.active and left["cars"] > 0 and right["cars"] > 0,
            "traffic": traffic,
            "rate_hz": None if self.motion_hz is None else round(self.motion_hz, 1),
            "seq": self.packets,
            "length_m": round(self.dims.length_m, 2),  # the car box in use (spotter/dims.py or the override): bar scale
        }
        self.state_obj = SpotterState(
            active=self.active,
            occupied=(self.active and self._raw[LEFT], self.active and self._raw[RIGHT]),
            announced=(self._announced[LEFT], self._announced[RIGHT]),
            last_seq=(self._last_seq[LEFT], self._last_seq[RIGHT]),
            epoch=self._epoch,
            traffic=traffic,
        )
