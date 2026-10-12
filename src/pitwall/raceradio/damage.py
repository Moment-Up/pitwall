"""Damage and punctures (group ``damage``; F1 races, practice and qualifying): the player's ``CarFrame.damage``.

* **Settle** - evaluated ``SETTLE_S`` after the last change of any value [M: contact damage steps up within 0.6 s;
  Jeddah's floor went 3 -> 16 -> 28 -> 31 -> 33 in 0.45 s], so one crash is one call, not one per step.
* **Grades** [H, from the real values]: wings, floor, diffuser and sidepod minor 10-29, major 30-59, severe 60 and
  more (100 = the part is gone); brakes (any wheel) major 30-59, severe 60+; gearbox and engine never by level (they
  rise like wear [M]: +1 every few laps) - a step of ``STEP_MIN`` points within ``STEP_WINDOW_S`` is major, a blown or
  seized engine severe; a DRS or ERS fault once per session each.
* **Puncture** [H; M: wear never jumps]: a wheel's tyre damage at ``PUNCTURE_MIN`` or more that rose by
  ``PUNCTURE_JUMP`` within ``PUNCTURE_WINDOW_S``. Always said first.
* **When** - a part's grade rises above the grade last said for it: one message, the puncture first, then up to two
  parts by grade. A non-severe call waits ``COOLDOWN_S`` [H] after the last damage call; severe damage and punctures
  always go. Puncture and severe: ALERT HIGH past quiet mode; major: ALERT HIGH; minor: RACE NORMAL.
* **Re-baseline, silently** - after a flashback (the game restores the pre-crash values [M]) the next settled values
  become the said grades; a value going down (a pit-stop repair: the wing reads 0 again [M]) lowers its grade; the
  first values of a session (joined with damage already on the car) are the baseline. ``retired`` silences it all.
* **Box advice** [H] - a puncture in a race with more than one lap left: "Box this lap."; a severe front wing with more
  than two laps left: "Box for a new front wing." (``advise_box`` in the call's data).

[recorded: wings, floor, diffuser; synthetic: punctures (the 100 % reading is real, but every real one came with a
retirement or a flashback), sidepod, brakes, gearbox and engine steps, faults, a blown or seized engine]
"""

from __future__ import annotations

import math
from collections import deque

from pitwall.model.telemetry import CarDamage, CarFrame, GameEvent
from pitwall.raceradio import wording as W
from pitwall.raceradio.model import CallKind, CallPriority, CallSpec
from pitwall.raceradio.state import RaceState

SETTLE_S = 1.5  # [M]
COOLDOWN_S = 20.0  # [H]
PUNCTURE_MIN = 90  # [H; M]
PUNCTURE_JUMP = 40  # [H; M]
PUNCTURE_WINDOW_S = 3.0  # [H]
STEP_MIN = 10  # [H]
STEP_WINDOW_S = 5.0  # [H]
HISTORY_S = 6.0
DAMAGE_TTL_S = 20.0
VIEW_PARTS = 3  # the RaceView stays under 1.2 kB
WHEELS = ("FL", "FR", "RL", "RR")
AERO = ("front_left_wing", "front_right_wing", "rear_wing", "floor", "diffuser", "sidepod")
NONE, MINOR, MAJOR, SEVERE = 0, 1, 2, 3
# Parts a call on the owner's real captures named (scripts/race_radio_check.py). A puncture read 100 % in 10 real
# crashes, but every one ended in a retirement or a flashback first, so the puncture call itself is synthetic only.
RECORDED_PARTS = frozenset({"front_left_wing", "front_right_wing", "front_wing", "rear_wing", "floor", "diffuser"})


def aero_grade(pct: int) -> int:
    return SEVERE if pct >= 60 else MAJOR if pct >= 30 else MINOR if pct >= 10 else NONE


def brake_grade(pct: int) -> int:
    return SEVERE if pct >= 60 else MAJOR if pct >= 30 else NONE


def aero_values(d: CarDamage) -> dict[str, int]:
    return {
        "front_left_wing": d.front_left_wing_pct,
        "front_right_wing": d.front_right_wing_pct,
        "rear_wing": d.rear_wing_pct,
        "floor": d.floor_pct,
        "diffuser": d.diffuser_pct,
        "sidepod": d.sidepod_pct,
    }


def part_values(d: CarDamage) -> dict[str, int]:
    """Every graded part's percentage (the view's parts)."""
    out = aero_values(d)
    for w, v in zip(WHEELS, d.brakes_pct.as_tuple(), strict=True):
        out[f"brakes_{w}"] = v
    return out


class DamageWatcher:
    def __init__(self) -> None:
        self.cur: CarDamage | None = None
        self._changed_t = -math.inf
        self._pending = False
        self._history: deque[tuple[float, CarDamage, CarDamage | None]] = deque()  # (t, new values, the ones before)
        self._spoken: dict[str, int] = {}
        self._punctured: set[str] = set()  # wheels whose puncture was said
        self._puncture_seen: set[str] = set()  # wheels that jumped since the last evaluation
        self._faults_said: set[str] = set()
        self._last_call = -math.inf
        self._rebaseline = True  # the first values of a session are the baseline
        self._retry_at: float | None = None

    # ------------------------------------------------------------------ input
    def on_event(self, st: RaceState, e: GameEvent, out: list[CallSpec]) -> None:
        if e.code == "FLBK":
            self._rebaseline = True
            self._pending = True
            self._changed_t = st.t

    def on_frame(self, st: RaceState, f: CarFrame, out: list[CallSpec]) -> None:
        d = f.damage
        if d is None or d == self.cur:
            return
        t = st.t
        before = [v for tt, v, _b in self._history if t - tt <= PUNCTURE_WINDOW_S]
        if self.cur is not None:
            before.append(self.cur)
        for i, w in enumerate(WHEELS):
            now = d.tyres_pct.as_tuple()[i]
            low = min((b.tyres_pct.as_tuple()[i] for b in before), default=now)
            if now >= PUNCTURE_MIN and now - low >= PUNCTURE_JUMP:
                self._puncture_seen.add(w)
        self._history.append((t, d, self.cur))
        self.cur = d
        self._changed_t = t
        self._pending = True
        while self._history and t - self._history[0][0] > HISTORY_S:
            self._history.popleft()

    def tick(self, st: RaceState, out: list[CallSpec]) -> None:
        if self._pending and st.t - self._changed_t >= SETTLE_S:
            self._pending = False
            self._evaluate(st, out)
        elif self._retry_at is not None and st.t >= self._retry_at:
            self._retry_at = None
            self._evaluate(st, out)

    # ------------------------------------------------------------------ evaluation
    def grades(self, st: RaceState) -> dict[str, int]:
        d = self.cur
        if d is None:
            return {}
        g = {p: aero_grade(v) for p, v in aero_values(d).items()}
        for w, pct in zip(WHEELS, d.brakes_pct.as_tuple(), strict=True):
            g[f"brakes_{w}"] = brake_grade(pct)
        recent: list[CarDamage] = []
        for tt, after, before in self._history:
            if st.t - tt <= STEP_WINDOW_S + SETTLE_S:
                recent.extend(x for x in (after, before) if x is not None)  # the values before a change count too
        for part, now in (("gearbox", d.gearbox_pct), ("engine", d.engine_pct)):
            low = min((getattr(x, f"{part}_pct") for x in recent), default=now)
            g[part] = MAJOR if now - low >= STEP_MIN else NONE  # wear-like: only a sudden step is news
        g["engine_failure"] = SEVERE if d.engine_blown or d.engine_seized else NONE
        return g

    def _evaluate(self, st: RaceState, out: list[CallSpec]) -> None:
        d = self.cur
        if d is None:
            return
        grades = self.grades(st)
        tyres = dict(zip(WHEELS, d.tyres_pct.as_tuple(), strict=True))
        if self._rebaseline or st.retired or st.mode == "off":
            self._rebaseline = False
            self._spoken = dict(grades)
            self._punctured = {w for w, v in tyres.items() if v >= PUNCTURE_MIN}
            self._puncture_seen.clear()
            self._faults_said |= {k for k in ("drs_fault", "ers_fault") if getattr(d, k)}
            return
        for p, g in grades.items():
            if g < self._spoken.get(p, NONE):
                self._spoken[p] = g  # repaired: said again only if it breaks again
        self._punctured = {w for w in self._punctured if tyres[w] >= PUNCTURE_MIN}
        for fault in ("drs_fault", "ers_fault"):
            if getattr(d, fault) and fault not in self._faults_said:
                self._faults_said.add(fault)
                text, simple = W.FAULTS[fault]
                out.append(self._spec("fault", "race", "normal", text, simple, {"fault": fault}))
        punctures = [w for w in WHEELS if w in self._puncture_seen and w not in self._punctured]
        self._puncture_seen.clear()
        up = {p: g for p, g in grades.items() if g > self._spoken.get(p, NONE)}
        if not punctures and not up:
            return
        severe = bool(punctures) or any(g == SEVERE for g in up.values())
        if not severe and st.t - self._last_call < COOLDOWN_S:
            self._retry_at = self._last_call + COOLDOWN_S
            return
        self._last_call = st.t
        self._spoken.update(up)
        self._punctured.update(punctures)
        said: dict[str, int] = {}
        for p, g in up.items():  # both front wings say "front wing", in the left wing's place
            if p in ("front_left_wing", "front_right_wing") and "front_left_wing" in up and "front_right_wing" in up:
                said["front_wing"] = max(said.get("front_wing", NONE), g)
            else:
                said[p] = g
        engine_failure = said.pop("engine_failure", NONE) == SEVERE
        parts = sorted(said.items(), key=lambda pg: (-pg[1], list(said).index(pg[0])))[:2]
        left, _source = st.laps_left()
        advice = advice_simple = None
        if punctures and st.race and left is not None and left > 1:
            advice, advice_simple = W.BOX_PUNCTURE
        elif (
            SEVERE in (up.get("front_left_wing"), up.get("front_right_wing"))  # news in this call, not an old wing
            and st.race
            and left is not None
            and left > 2
        ):
            advice, advice_simple = W.BOX_FRONT_WING
        named = [(p, W.GRADES[g]) for p, g in parts]
        text, simple = W.damage(named, punctures, advice, advice_simple)
        if engine_failure:
            f_text, f_simple = W.FAULTS["engine_failure"]
            text, simple = f"{f_text} {text}".strip(), f"{f_simple} {simple}".strip()
        top = max([*up.values(), SEVERE if punctures else NONE])
        kind: CallKind = "race" if top == MINOR else "alert"
        priority: CallPriority = "normal" if top == MINOR else "high"
        data = {
            "parts": [{"part": p, "grade": W.GRADES[g]} for p, g in parts],
            "puncture": punctures,
            "engine_failure": engine_failure,
            "advise_box": advice is not None,
        }
        spec = self._spec("damage", kind, priority, text, simple, data)
        spec.bypass_quiet = top == SEVERE
        if engine_failure or punctures or any(p not in RECORDED_PARTS for p, _g in parts):
            spec.tier = "synthetic"  # no real capture made this call (see RECORDED_PARTS)
        out.append(spec)

    # ------------------------------------------------------------------ view
    def view(self) -> dict[str, object] | None:
        d = self.cur
        if d is None:
            return None
        graded = [
            (g, v, p)
            for p, v in part_values(d).items()
            if (g := (brake_grade(v) if p.startswith("brakes_") else aero_grade(v))) > NONE
        ]
        graded.sort(key=lambda gvp: (-gvp[0], -gvp[1]))  # the worst first: the view keeps VIEW_PARTS of them
        parts = [{"part": p, "pct": v, "grade": W.GRADES[g]} for g, v, p in graded[:VIEW_PARTS]]
        top = graded[0][0] if graded else NONE
        puncture = [w for w, v in zip(WHEELS, d.tyres_pct.as_tuple(), strict=True) if v >= PUNCTURE_MIN]
        if puncture or d.engine_blown or d.engine_seized:
            top = SEVERE
        return {"grade": W.GRADES[top], "parts": parts, "puncture": puncture}

    @staticmethod
    def _spec(
        call: str, kind: CallKind, priority: CallPriority, text: str, simple: str, data: dict[str, object]
    ) -> CallSpec:
        return CallSpec(
            group="damage",
            call=call,
            kind=kind,
            priority=priority,
            text=text,
            text_simple=simple or None,
            ttl_s=DAMAGE_TTL_S,
            data=data,
        )
