"""F1 25 button probe, the live button test and Identify (Setup › Controls › Test).

Only F1 25 lets Pitwall see a wheel button: its Event ``BUTN`` carries pad-style bits and UDP Action 1-12
(``adapters.f1.enums.BUTTON_FLAGS``, spec appendix 8.9). Which physical control sets which bit is not documented:
the test reports only what it sees, and nothing here is "validated" (the owner's live run in the validation kit is).

* ``ButtonProbe``: subscribed to ``LiveState.subscribe_buttons`` whether or not voice is on. On the ingest thread it
  does O(1) work and takes no lock: ``seq += 1`` and one store into a fixed ring (64 slots) of
  ``(seq, t_unix, status, previous status, origin)``. ``since(seq)`` / ``feed()`` read it from API threads and the
  validation collector; a slot overwritten while it is read is detected by its sequence number and skipped.
* ``origin`` comes from ``LiveState.button_origin`` (set by ``SessionManager``): a replay or synthetic stream shares
  live state, so its presses show in the feed (labelled) but never count.
* ``TestRunner``: one test at a time (409 otherwise), advanced when the dashboard polls (4 Hz); events are kept by
  sequence number, so nothing is lost between polls. Item states: waiting -> detected / effect_seen ("56 -> 57") /
  other_bits ("We saw Circle or B, not UDP Action 3") / timeout (60 s) / skipped. Wheel push-to-talk is paused while
  a test runs (the hub's pause expires on its own if the page stops polling). An item's 60 s run only while F1 25 is
  live. Results are saved into the layout only from a live stream sent by a console or another PC (``saves``; each
  item says whether its result was ``saved``): a stream sent from this computer runs the test but saves nothing.
* Recorded F1 PS5 captures show the Right Stick direction bits changing all the time while driving, sometimes Up and
  Down together, so they probably follow the pedals [recorded, unverified]: they are shown but never reported as
  "other bits".
"""

from __future__ import annotations

import contextlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from pitwall.adapters.f1.enums import BUTTON_FLAGS, ERS_DEPLOY_MODE, button_names, udp_action_bit
from pitwall.controls.model import Assignment, Check, CheckResult, Layout, WheelDef

RING = 64
FEED = 20
ITEM_TIMEOUT_S = 60.0
IDLE_STOP_S = 60.0  # no poll for this long: the page is gone, the test ends (and wheel push-to-talk comes back)
PAUSE_REFRESH_S = 5.0  # re-arm the hub's wheel push-to-talk pause this often while polled
PAUSE_FOR_S = 15.0  # the hub resumes wheel push-to-talk on its own this long after the last re-arm
UDP_BITS = 0xFFF00000
NOISY_BITS = 0x00008000 | 0x00010000 | 0x00020000 | 0x00040000  # Right Stick directions (see module doc)
EFFECT_FIELDS = {"brake_bias": "brake_bias_front_pct", "ers_mode": "ers_deploy_mode"}


@dataclass(frozen=True, slots=True)
class ButtonEvent:
    seq: int
    t_unix: float
    status: int
    prev: int
    origin: str

    @property
    def pressed(self) -> int:
        return self.status & ~self.prev & 0xFFFFFFFF

    @property
    def released(self) -> int:
        return self.prev & ~self.status & 0xFFFFFFFF

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "t_unix": round(self.t_unix, 3),
            "status": self.status,
            "pressed": button_names(self.pressed),
            "released": button_names(self.released),
            "origin": self.origin,
        }


class ButtonProbe:
    """Lock-free ring of the last ``RING`` button events (single writer: the ingest thread)."""

    def __init__(self, origin_of: Callable[[], str] | None = None, size: int = RING) -> None:
        self._size = size
        self._ring: list[tuple[int, float, int, int, str] | None] = [None] * size
        self.seq = 0
        self._prev = 0
        self._origin_of = origin_of

    def on_button(self, status: int) -> None:
        """Ingest thread: O(1), no lock, no I/O."""
        origin = self._origin_of() if self._origin_of is not None else "live"
        seq = self.seq + 1
        self._ring[seq % self._size] = (seq, time.time(), status & 0xFFFFFFFF, self._prev, origin)
        self._prev = status & 0xFFFFFFFF
        self.seq = seq

    def since(self, seq: int) -> list[ButtonEvent]:
        """Events after ``seq`` that are still in the ring, oldest first."""
        last = self.seq
        first = max(seq + 1, last - self._size + 1, 1)
        out: list[ButtonEvent] = []
        for s in range(first, last + 1):
            item = self._ring[s % self._size]
            if item is not None and item[0] == s:
                out.append(ButtonEvent(*item))
        return out

    def feed(self, n: int = FEED) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.since(max(0, self.seq - n))]


# ---------------------------------------------------------------------------------------------- the test
@dataclass(slots=True)
class TestItem:
    __test__ = False  # not a pytest class
    key: str
    kind: str  # "udp_action" | "effect" | "identify"
    prompt: str
    expect: dict[str, Any]
    state: str = "waiting"
    seen: list[str] = field(default_factory=list)
    detail: str | None = None
    started_unix: float = 0.0
    baseline: float | None = None
    saved: bool = False  # the result went into the layout

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "prompt": self.prompt,
            "expect": dict(self.expect),
            "state": self.state,
            "seen": list(self.seen),
            "detail": self.detail,
            "saved": self.saved,  # additive
        }


@dataclass(slots=True)
class ControlsTest:
    id: str
    layout_id: str | None
    game: str
    started_unix: float
    items: list[TestItem]
    seq: int  # probe sequence number already consumed
    current: int = 0
    last_poll_mono: float = 0.0
    last_pause_mono: float = 0.0
    available: bool = False
    why: str | None = None
    saves: bool = False  # results go into the layout (a live stream from a console or another PC)


ResultSink = Callable[[str, str, Check], None]  # (layout_id, assignment key, check)
# (presses count?, why, frame values). Not available: nothing counts and no item's clock runs (the test starts by
# itself when F1 25 is live). Available with a reason: the test runs and shows what it sees but saves nothing (a
# stream sent from this computer). Available with no reason: results are saved as "Seen by Pitwall".
Availability = Callable[[], tuple[bool, str | None, dict[str, float | None]]]


def _physical_hint(wheel: WheelDef | None, a: Assignment) -> str:
    c = wheel.control(a.control_id) if wheel is not None else None
    if c is None:
        return ""
    slot = {"cw": " clockwise", "ccw": " anticlockwise", "push": " (push)"}.get(a.slot or "", "")
    if a.slot in ("up", "down", "left", "right"):
        slot = f" {a.slot}"
    return f" ({c.label}{slot})"


def build_items(layout: Layout, wheel: WheelDef | None, label: Callable[[str], str]) -> list[TestItem]:
    """UDP Action items for every assignment with a UDP Action, then (F1 only) brake bias / ERS effect items."""
    items: list[TestItem] = []
    for a in layout.assignments:
        if a.udp_action is None:
            continue
        name = "Talk to Pitwall" if a.function == "ptt_pitwall" else label(a.function)
        items.append(
            TestItem(
                a.key,
                "udp_action",
                f"Press the button you mapped to {name} (UDP Action {a.udp_action}){_physical_hint(wheel, a)}.",
                {"bit": udp_action_bit(a.udp_action)},
            )
        )
    if layout.game == "f1_25":
        for a in layout.assignments:
            fld = EFFECT_FIELDS.get(a.function)
            if fld is None or a.control_id is None or a.action not in ("inc", "dec"):
                continue
            sign = "+" if a.action == "inc" else "−"
            items.append(
                TestItem(
                    a.key,
                    "effect",
                    f"On track or in the garage, press {label(a.function)} {sign} once{_physical_hint(wheel, a)}.",
                    {"field": fld, "direction": "change"},
                )
            )
    return items


def _fmt_value(fld: str, v: float | None) -> str:
    if v is None:
        return "-"
    if fld == "ers_deploy_mode":
        return ERS_DEPLOY_MODE.get(int(v), f"mode {int(v)}")
    return f"{v:g}"


class TestRunner:
    """One button test at a time. Thread-safe (API handlers run in a thread pool)."""

    __test__ = False  # not a pytest class

    def __init__(
        self,
        probe: ButtonProbe,
        availability: Availability,
        on_result: ResultSink | None = None,
        on_pause: Callable[[bool], object] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.probe = probe
        self.availability = availability
        self.on_result = on_result
        self.on_pause = on_pause
        self.clock = clock
        self._lock = threading.Lock()
        self.test: ControlsTest | None = None

    # -------------------------------------------------------------- lifecycle
    def start(self, layout: Layout | None, items: list[TestItem], game: str = "f1_25") -> dict[str, Any]:
        with self._lock:
            self._expire_locked()
            if self.test is not None:
                raise RuntimeError("a button test is already running")
            now = time.time()
            for it in items:
                it.started_unix = now
            self.test = ControlsTest(
                id="t_" + secrets.token_hex(4),
                layout_id=layout.id if layout is not None else None,
                game=game,
                started_unix=now,
                items=items,
                seq=self.probe.seq,
                last_poll_mono=self.clock(),
            )
            self._pause(True)
            self._advance_locked()
            return self._state_locked()

    def stop(self, test_id: str) -> dict[str, Any] | None:
        with self._lock:
            t = self.test
            if t is None or t.id != test_id:
                raise KeyError(test_id)
            for it in t.items[t.current :]:
                if it.state == "waiting" and it.kind != "identify":
                    it.state = "skipped"
            out = self._state_locked()
            self.test = None
            self._pause(False)
            return out

    def skip(self, test_id: str) -> dict[str, Any]:
        with self._lock:
            t = self.test
            if t is None or t.id != test_id:
                raise KeyError(test_id)
            if t.current < len(t.items):
                t.items[t.current].state = "skipped"
                self._next_locked(t, self.availability()[2])
            return self._state_locked()

    def poll(self) -> dict[str, Any] | None:
        with self._lock:
            self._expire_locked()
            if self.test is None:
                return None
            self.test.last_poll_mono = self.clock()
            if self.clock() - self.test.last_pause_mono >= PAUSE_REFRESH_S:
                self._pause(True)
            self._advance_locked()
            return self._state_locked()

    @property
    def running(self) -> bool:
        return self.test is not None

    # -------------------------------------------------------------- internals (lock held)
    def _pause(self, on: bool) -> None:
        if self.test is not None:
            self.test.last_pause_mono = self.clock()
        if self.on_pause is not None:
            with contextlib.suppress(Exception):  # the radio is optional; a test must run without it
                self.on_pause(on)

    def _expire_locked(self) -> None:
        t = self.test
        if t is not None and self.clock() - t.last_poll_mono > IDLE_STOP_S:
            self.test = None
            self._pause(False)

    def _next_locked(self, t: ControlsTest, values: dict[str, float | None] | None = None) -> None:
        """Move to the next item; an effect item takes its baseline from the values of this moment."""
        t.current += 1
        if t.current < len(t.items):
            it = t.items[t.current]
            it.started_unix = time.time()
            it.baseline = None
            if it.kind == "effect" and values is not None:
                it.baseline = values.get(str(it.expect.get("field")))

    def _record(self, t: ControlsTest, it: TestItem, result: str, detail: str) -> None:
        if self.on_result is None or t.layout_id is None or not t.saves:
            return
        with contextlib.suppress(Exception):  # a failed save never stops the test
            self.on_result(t.layout_id, it.key, Check(cast(CheckResult, result), time.time(), detail, "live"))
            it.saved = True

    def _advance_locked(self) -> None:
        t = self.test
        if t is None:
            return
        available, why, values = self.availability()
        t.available, t.why, t.saves = available, why, available and why is None
        events = self.probe.since(t.seq)
        if events:
            t.seq = events[-1].seq
        # A press counts whenever it is live (F1 sends button events from menus too, with little else, so the
        # stream can look stale between presses); it is saved only while ``t.saves``.
        for ev in events:
            if t.current >= len(t.items):
                break
            it = t.items[t.current]
            if ev.origin != "live":
                continue
            pressed = ev.pressed
            if not pressed:
                continue
            names = button_names(pressed)
            if it.kind == "identify":
                for n in names:
                    if n not in it.seen:
                        it.seen.append(n)
                it.detail = "Seen: " + ", ".join(it.seen[-6:])
                continue
            if it.kind == "udp_action":
                bit = int(it.expect["bit"])
                if pressed & bit:
                    it.state = "detected"
                    it.detail = f"{BUTTON_FLAGS[bit]} seen"
                    self._record(t, it, "detected", it.detail)
                    self._next_locked(t, values)
                    continue
                other = pressed & ~NOISY_BITS
                if other:
                    for n in button_names(other):
                        if n not in it.seen:
                            it.seen.append(n)
                    it.state = "other_bits"
                    it.detail = (
                        f"We saw {', '.join(it.seen)}, not {BUTTON_FLAGS[bit]}: this button may be mapped to "
                        "something else."
                    )
        # effect items and timeouts: only while F1 25 is live (the 60 s of an item start when it is)
        now = time.time()
        if t.current < len(t.items) and not available:
            t.items[t.current].started_unix = now
        elif t.current < len(t.items):
            it = t.items[t.current]
            if it.kind == "effect":
                fld = str(it.expect["field"])
                v = values.get(fld)
                if it.baseline is None:
                    it.baseline = v
                elif v is not None and v != it.baseline:
                    direction = "up" if v > it.baseline else "down"
                    it.state = "effect_seen"
                    it.expect = {**it.expect, "direction": direction}
                    it.detail = f"{_fmt_value(fld, it.baseline)} → {_fmt_value(fld, v)} ({direction})"
                    self._record(t, it, "effect_seen", it.detail)
                    self._next_locked(t, values)
            if t.current < len(t.items):
                it = t.items[t.current]
                if it.kind != "identify" and now - it.started_unix > ITEM_TIMEOUT_S:
                    if it.state == "other_bits":  # keeps its state: what was seen is the useful answer
                        self._record(t, it, "other_bits", it.detail or "other buttons seen")
                    else:
                        it.state = "timeout"
                        it.detail = "Nothing seen in 60 s."
                        self._record(t, it, "not_seen", "nothing seen in 60 s")
                    self._next_locked(t, values)

    def _state_locked(self) -> dict[str, Any]:
        t = self.test
        assert t is not None
        return {
            "id": t.id,
            "layout_id": t.layout_id,
            "started_unix": t.started_unix,
            "available": t.available,
            "why": t.why,
            "saves": t.saves,  # additive: false while the stream comes from this computer (shown, not saved)
            "wheel_ptt_paused": self.on_pause is not None,
            "current": t.current,
            "items": [it.to_dict() for it in t.items],
            "feed": self.probe.feed(FEED),
        }
