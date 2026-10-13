"""The radio hub's spotter path (spec section 5): delivery rules, the one-slot mailbox, heard pairing, latency.

Lives beside ``voice.hub`` (the hub owns one ``SpotterRadio`` and calls its hooks; event loop only) so the shared hub
file only carries short, delimited hooks.

**When a call is played** (``deliver``):

====================================================  ===============================================================
voice off, no radio connected, spoken calls off        nothing played, counted ``dropped:<reason>``; ``heard`` reset
driver transmitting (PTT down)                         held in the mailbox (half duplex: playing would feed the mic)
a spotter call or a non-spotter urgent call on air     mailbox (equal ranks never cut each other)
a braking cue on air, the call is a clear              mailbox until the cue ends (a clear is never urgent enough to
                                                       cost a braking cue; it is said a moment later)
a cue, a proactive message or an answer/control        cut: a proactive message or answer/control is said again once
on air                                                 (``rehold_after_spotter``); a cut cue is dropped
the radio is idle                                      played at once
====================================================  ===============================================================

Which call may cut what on air is the scheduler's one rule, the urgent path shared with the race radio's red flag
and puncture (``scheduler.may_interrupt``: only urgent calls interrupt, never another urgent call), including its
clear-before-cue exception (``YIELDS_TO_CUE_KEY``, set on clears and "still there": they never cut a braking cue).
``still_there`` is HIGH, not URGENT: it never cuts anything and waits in the mailbox while the radio is busy; a car
arriving ("Car left.", "Three wide.") cuts a still there on air, and no other spotter call cuts another. A braking cue
never cuts a spotter call (the hub's cue gate asks the same rule: a cue plays only on a free radio).

**Mailbox**: one slot. A newer call replaces the held one unless it matters less (``still_there`` < a clear < an
onset, three wide or ``hold_your_line``): an onset waiting for the radio is never pushed out by a clear or a
``still_there`` (a clear lost that way is said by the resync below). A held clear is said as the sides are when it
is released (the resync below: "Clear all round." when the other side has gone too). Released when the spotter clip
on air ends (the device's ``ended`` report, or a backstop timer of the clip's length + 0.15 s + the measured start
latency), when PTT goes up, when the urgent call on air ends and on every hub tick. Before playing, the call is
re-checked against the worker's state: an onset needs its side(s) still occupied and is at most 1.0 s old; a clear
needs the side still clear, nothing newer on that side and at most 1.0 s; ``still_there`` needs the car still there
and at most 0.5 s. A ``final`` clear (decided as a gate closed with the positions still valid: the engine has
already moved to a new epoch) needs only the side still clear, and is dropped once the radio has heard from a newer
epoch.

**Heard pairing**: what the driver actually heard. An onset sets ``heard[side]`` (three wide: both), a clear resets
it (clear all round: both). A clear is never played for a side whose onset was not heard; an onset is not repeated
for a side already heard; a ``still_there`` or ``hold_your_line`` for a side not heard is said as that side's onset
(its onset was lost while the driver transmitted). An engine reset (a gate closed, a flashback) starts a new ``epoch``:
``heard`` resets.

**Resync**: a call can be lost in the mailbox (replaced by a newer call, held through a transmission, too old by the
time the radio is free: a clear decided early in a 1.6 s "three wide" clip). Whenever the radio is free and the
mailbox empty (a clip ended, PTT up, every tick), ``heard`` is compared with the worker's ``announced``: one onset is
said for a side announced and occupied but not heard ("Three wide." when both are), or one clear for a side heard but
no longer announced nor occupied. So the driver is never left with a car that has gone, and the next car on that side
is never dropped as ``already_heard``. Never while a newer engine call is still on its way to the loop (the worker's
``last_seq`` is ahead of what the loop received), never without the phrase's audio, and never across an epoch (a
muted spotter never says clear).

**Audio**: clips made in advance (``voice.spotter_audio``) go to every client, device-voice iPads included
(``RadioHub._deliver(pcm_to_all=True)``: the iPad plays PCM whenever ``n_bytes > 0``), so nothing is synthesised on
the iPad either. Without a clip, device-voice clients get the text (their own voice); a PCM-only radio gets nothing
(``audio_not_ready``): silence must not cut what is on air.

**Latency** (spec section 6): t0 packet received (``FieldMotion.t_recv_ns``), t1 engine decision, t2 PCM on every
client queue, t3 the device's ``playback started``. ``queued_ms = t2 - t0`` (target p95 <= 15 ms), ``started_ms =
t3 - t0``, both for calls played at once; a call that waited in the mailbox records ``held_ms`` (t2 - t1) instead,
so a wait behind another clip never reads as pipeline latency. ``ear_latency_s = median(started) + output
allowance`` goes back to the worker for its short-overlap suppression. One INFO line a minute while calls are made;
WARN when queued p95 exceeds 30 ms.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
from collections import Counter, deque
from typing import TYPE_CHECKING, Any

from pitwall.compat import recv_clock_ns
from pitwall.spotter.model import (
    CAR_LEFT,
    CAR_RIGHT,
    CLEAR_ALL_ROUND,
    CLEAR_KINDS,
    CLEAR_LEFT,
    CLEAR_RIGHT,
    HOLD_YOUR_LINE,
    LEFT,
    RIGHT,
    STILL_THERE,
    THREE_WIDE,
    Side,
    SpotterCall,
    SpotterState,
)
from pitwall.spotter.phrases import onset_phrase_id, phrase_id, phrase_text
from pitwall.spotter.settings import DEFAULTS, SpotterSettings
from pitwall.spotter.stats import Ring
from pitwall.voice.scheduler import YIELDS_TO_CUE_KEY, may_interrupt
from pitwall.voice.spotter_audio import SpotterAudio
from pitwall.voice.types import MessageKind, Priority, RadioMessage, SynthResult

if TYPE_CHECKING:
    from pitwall.spotter.worker import SpotterWorker
    from pitwall.voice.hub import RadioHub

log = logging.getLogger(__name__)

ONSET_MAX_AGE_S = 1.0  # [H]
CLEAR_MAX_AGE_S = 1.0  # [H]
STILL_MAX_AGE_S = 0.5  # [H]
BACKSTOP_PAD_S = 0.15
DEFAULT_START_S = 0.3  # deliver -> device "started" until measured
TEST_GAP_S = 1.2
MAX_PLAUSIBLE_NS = 5_000_000_000
EAR_MIN_SAMPLES = 3
LOG_EVERY_S = 60.0
QUEUED_WARN_MS = 30.0
RECENT = 20
SIDE_INDEX = {"left": LEFT, "right": RIGHT}
# what a held call is worth in the mailbox: a newer call that matters less never replaces it
_MAIL_RANK = {STILL_THERE: 0, CLEAR_LEFT: 1, CLEAR_RIGHT: 1, CLEAR_ALL_ROUND: 1}  # onsets, three wide, hold: 2
# phrases that never cut a braking cue (marked ``YIELDS_TO_CUE_KEY``): information, never a car arriving or closing in
_STILL = frozenset({"still_there_left", "still_there_right"})
_CUE_FIRST = frozenset({CLEAR_LEFT, CLEAR_RIGHT, CLEAR_ALL_ROUND}) | _STILL
_NEW_CAR = frozenset({CAR_LEFT, CAR_RIGHT, THREE_WIDE})  # may cut a still there on air


def _probe(priority: Priority, yields_to_cue: bool = False) -> RadioMessage:
    """A stand-in message for the scheduler's interrupt rule (it reads the kind, the priority and the cue mark)."""
    meta: dict[str, object] = {YIELDS_TO_CUE_KEY: True} if yields_to_cue else {}
    return RadioMessage(
        id="", kind=MessageKind.SPOTTER, priority=priority, text="", speech="", created_mono=0.0, meta=meta
    )


_PROBE_URGENT, _PROBE_HIGH = _probe(Priority.URGENT), _probe(Priority.HIGH)
_PROBE_CLEAR = _probe(Priority.URGENT, yields_to_cue=True)  # a clear: urgent, but it waits for a braking cue


def _mail_rank(call: SpotterCall) -> int:
    return _MAIL_RANK.get(call.kind, 2)


@dataclasses.dataclass(slots=True)
class _Inflight:
    call: SpotterCall
    t2_ns: int
    msg_id: str
    held: bool  # it waited in the mailbox: its stamps measure the wait, not the pipeline


class SpotterRadio:
    def __init__(self, hub: RadioHub) -> None:
        self.hub = hub
        self.worker: SpotterWorker | None = None
        self._origin: Any = None  # the worker of the newest call (a real-time replay has its own)
        self.settings: SpotterSettings = DEFAULTS
        self.audio = SpotterAudio(_trim)
        self.heard = [False, False]
        self._epoch: int | None = None
        self._mailbox: SpotterCall | None = None
        self._mailbox_reason: str | None = None
        self._inflight: dict[str, _Inflight] = {}
        self._backstop: asyncio.TimerHandle | None = None
        self._build_task: asyncio.Task[None] | None = None
        self._build_again = False
        self._audio_key: tuple[object, ...] | None = None
        self._test_task: asyncio.Task[None] | None = None
        self._seen_seq = 0  # newest engine seq received in this epoch (resync waits for calls still in flight)
        # stats
        self.received = 0
        self.resynced = 0
        self.spoken: Counter[str] = Counter()
        self.dropped: Counter[str] = Counter()
        self.queued_ms = Ring()  # t2 - t0 of calls played at once (the pipeline)
        self.handoff_ms = Ring()
        self.started_ms = Ring()
        self.held_ms = Ring()  # how long calls waited in the mailbox (decision -> on the client queues)
        self.deliver_to_start_ms = Ring()
        self.recent: deque[dict[str, Any]] = deque(maxlen=RECENT)
        self._log_mono = time.monotonic()
        self._log_spoken = 0
        self._log_dropped: Counter[str] = Counter()

    # ------------------------------------------------------------------ wiring (event loop)
    def attach(self, worker: SpotterWorker) -> None:
        """Calls of ``worker`` (and of a real-time replay's worker, through the runtime) come to this radio."""
        self.worker = worker
        worker.sink = self.on_call_threadsafe
        self.settings = worker.settings
        self.request_audio()

    def detach(self) -> None:
        w = self.worker
        if w is not None and w.sink == self.on_call_threadsafe:
            w.sink = None
        self.worker = None
        for task in (self._build_task, self._test_task):
            if task is not None:
                task.cancel()
        if self._backstop is not None:
            self._backstop.cancel()
            self._backstop = None

    def on_call_threadsafe(self, call: SpotterCall) -> None:
        """Worker sink (spotter thread): hand the call to the loop, never block."""
        loop = self.hub._loop
        if loop is None:
            return
        with contextlib.suppress(RuntimeError):  # loop closed: shutting down
            loop.call_soon_threadsafe(self.deliver, call)

    # ------------------------------------------------------------------ settings, audio
    def simple(self, wording: str | None = None) -> bool:
        """Simple (beginner) wording in effect: the setting (``wording`` overrides it: the API's just-saved value),
        "auto" following the seated driver's profile."""
        w = self.settings.wording if wording is None else wording
        if w != "auto":
            return w == "simple"
        limits = self.hub.coaching_limits
        return bool(limits is not None and limits.simple_wording)

    def effective_voice(self) -> str | None:
        """The spotter's own Kokoro voice (Kokoro engine only), else None: the engineer's voice."""
        v = self.settings.voice
        return v if v and getattr(self.hub.tts, "name", "") == "kokoro" else None

    def _synth(self, text: str) -> SynthResult:
        """Blocking (worker thread): the spotter voice when set, else exactly what the engineer's messages use."""
        voice = self.effective_voice()
        detailed = getattr(self.hub.tts, "synthesize_detailed", None)
        if voice is not None and callable(detailed):
            res = detailed(text, voice=voice)
            if isinstance(res, SynthResult):
                return res
        return self.hub._synth_detailed(text)

    def audio_key(self) -> tuple[object, ...]:
        tts = self.hub.tts
        return (
            id(tts),
            getattr(tts, "active", getattr(tts, "name", None)),
            self.effective_voice() or getattr(tts, "voice", None),
        )

    def request_audio(self, force: bool = False) -> None:
        """(Re)build the phrase audio if the spotter is on (or ``force``: the test button)."""
        if self.hub._loop is None or not (self.settings.enabled or force):
            return
        task = self._build_task
        if task is not None and not task.done():
            self._build_again = True
            return
        self._build_task = asyncio.get_running_loop().create_task(self._build(), name="spotter-audio")

    async def _build(self) -> None:
        try:
            while True:
                self._build_again = False
                hub = self.hub
                tts = hub.tts
                self._audio_key = self.audio_key()
                engine = str(getattr(tts, "name", "none"))
                primary_ready = getattr(tts, "active", engine) == engine
                fallback = getattr(tts, "synthesize_fallback", None)
                n = await self.audio.build(
                    engine=engine,
                    voice=self.effective_voice() or getattr(tts, "voice", None),
                    primary_ready=primary_ready,
                    synth=self._synth,
                    fallback=fallback if callable(fallback) else None,
                    fallback_name=str(getattr(tts, "fallback_name", None) or "say"),
                    heard=hub._heard if hub.verify_tts else None,
                    can_verify=hub._can_verify,
                )
                if n:
                    log.info("spotter audio: %d phrase(s) rendered (%s)", n, self.audio.status()["rendered_by"])
                    hub._send_state()
                if not self._build_again:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("spotter audio build failed; calls go out as text until it succeeds")

    # ------------------------------------------------------------------ hub hooks
    def tick(self, now: float) -> None:
        """Every hub tick (100 ms): follow settings, rebuild audio when the engine changed, release the mailbox."""
        w = self.worker
        if w is not None and w.settings is not self.settings:
            old, self.settings = self.settings, w.settings
            if self.settings.enabled and (not old.enabled or old.voice != self.settings.voice):
                self.request_audio()
            if not self.settings.enabled:
                self._mailbox = None
            self.hub._send_state()
        if self.settings.enabled and self._audio_key is not None and self.audio_key() != self._audio_key:
            self.request_audio()  # Kokoro came up (re-render the say clips), or the voice changed
        elif self.settings.enabled and self._audio_key is None and self._build_task is None:
            self.request_audio()
        self.release()
        self.resync()
        self._log_minute(now)

    def on_tts_changed(self) -> None:
        self.request_audio()

    def on_playback(self, msg_id: str, state: str) -> None:
        """A device's playback report (after the hub handled it)."""
        if state == "started":
            inf = self._inflight.pop(msg_id, None)
            if inf is not None:
                self._measure_started(inf)
        elif state == "ended":
            self.release()
            self.resync()

    def on_ptt_up(self) -> None:
        self.release()
        self.resync()

    def state_block(self) -> dict[str, Any]:
        """The ``spotter`` object of the radio ``state`` frame (docs/voice-protocol.md)."""
        return {
            "enabled": self.settings.enabled,
            "audio_ready": self.audio.ready(),
            "voice": self.effective_voice(),
        }

    def traffic(self) -> bool | None:
        """``DrivingState.traffic_alongside``: only while the spotter is on and active."""
        if not self.settings.enabled:
            return None
        blk = self.hub.live.spotter
        if not isinstance(blk, dict) or not blk.get("active"):
            return None
        return bool(blk.get("traffic"))

    # ------------------------------------------------------------------ delivery
    def deliver(self, call: SpotterCall, *, held: bool = False) -> str | None:
        """Play the call now, hold it in the mailbox, or drop it. Returns the drop/hold reason (None = played).
        ``held``: it comes out of the mailbox (its latency is recorded as a wait, not as the pipeline's)."""
        if self._mailbox is not None and self._mailbox is not call:
            self.release()  # an older held call goes first if it may (order kept); else this one replaces it
        self.received += 1
        hub = self.hub
        if call.origin is not None:
            self._origin = call.origin
        if not call.test:
            if call.epoch != self._epoch:
                if call.final:
                    return self._drop(call, "stale")  # the radio has already heard from a newer epoch
                self._epoch = call.epoch
                self.heard = [False, False]  # the engine forgot its traffic: so do we
                self._seen_seq = 0
            self._seen_seq = max(self._seen_seq, call.seq)
            if not self.settings.enabled:
                return self._drop(call, "disabled")
            if not self.settings.audio:
                return self._drop(call, "audio_off")
        if not hub.voice_enabled:
            self.heard = [False, False]
            return self._drop(call, "voice_off")
        if not hub.clients:
            self.heard = [False, False]
            return self._drop(call, "no_radio")
        block = self._block_reason(call)
        if block is not None:
            self._hold(call, block)
            return block
        if not call.test and not self._valid(call):
            return self._drop(call, "stale")
        return self._play(call, held)

    def _block_reason(self, call: SpotterCall) -> str | None:
        """Why the call must wait (None = play it now): the scheduler's interrupt rule plus the clear-before-cue
        exception (the module docstring)."""
        hub = self.hub
        if hub.ptt_down:
            return "ptt"
        on_air = hub._on_air_message()
        if on_air is None:
            return None
        m = on_air[0]
        if m.kind is MessageKind.SPOTTER:
            if call.kind in _NEW_CAR and m.meta.get("phrase") in _STILL:
                return None  # a car arriving cuts "Still left." (information about a car the driver knows)
            return "spotter_on_air"
        probe = _PROBE_CLEAR if call.kind in CLEAR_KINDS else _PROBE_URGENT if call.urgent else _PROBE_HIGH
        if may_interrupt(probe, m):
            return None
        if m.kind is MessageKind.CUE and call.kind in CLEAR_KINDS:
            return "cue_on_air"  # the rule's clear-before-cue exception
        return "urgent_on_air" if m.priority >= Priority.URGENT else "radio_busy"  # still_there never cuts anything

    def _hold(self, call: SpotterCall, reason: str) -> None:
        old = self._mailbox
        if old is not None:
            if _mail_rank(call) < _mail_rank(old):
                self._drop(call, reason, replaced=True)  # the held call matters more; a lost clear is resynced
                return
            self._drop(old, self._mailbox_reason or "replaced", replaced=True)
        self._mailbox = call
        self._mailbox_reason = reason

    def release(self) -> None:
        call = self._mailbox
        if call is None or self._block_reason(call) is not None:
            return
        reason = self._mailbox_reason or "mailbox"
        self._mailbox = self._mailbox_reason = None
        if call.kind in CLEAR_KINDS and not (call.test or call.final) and self.resync() is not None:
            return  # a held clear: said as the sides are now ("Clear all round." when the other side went too)
        if not call.test and not self._valid(call):
            self._drop(call, reason)  # waited too long (or the car went): counted under why it waited
            return
        self.received -= 1  # deliver counts it again
        self.deliver(call, held=True)

    def resync(self) -> str | None:
        """Say what the driver missed (see **Resync** above). Returns the call kind said, or None."""
        if self._mailbox is not None or self._epoch is None or not (self.settings.enabled and self.settings.audio):
            return None
        hub = self.hub
        if not hub.voice_enabled or not hub.clients:
            return None
        origin = self._origin if callable(getattr(self._origin, "state", None)) else self.worker
        st = origin.state() if origin is not None else None
        if not isinstance(st, SpotterState) or not st.active or st.epoch != self._epoch:
            return None
        if max(st.last_seq) > self._seen_seq:
            return None  # a newer engine call is on its way to the loop: it speaks for itself
        h, ann, occ = self.heard, st.announced, st.occupied
        onset = [ann[x] and occ[x] and not h[x] for x in (LEFT, RIGHT)]
        clear = [h[x] and not ann[x] and not occ[x] for x in (LEFT, RIGHT)]
        kind: str
        side: Side | None
        if any(onset):
            if all(ann) and all(occ):
                kind, side = THREE_WIDE, None
            else:
                kind, side = (CAR_LEFT, "left") if onset[LEFT] else (CAR_RIGHT, "right")
        elif any(clear):
            if all(clear):
                kind, side = CLEAR_ALL_ROUND, None
            else:
                kind, side = (CLEAR_LEFT, "left") if clear[LEFT] else (CLEAR_RIGHT, "right")
        else:
            return None
        now = recv_clock_ns()
        call = SpotterCall(kind, side, max(st.last_seq), st.epoch, 0.0, now, now, origin=origin)
        if self._block_reason(call) is not None:
            return None  # the next release, PTT up or tick tries again
        got = self._phrase(call)
        if isinstance(got, str) or (
            self.audio.get(got[0], self.simple()) is None and not any(c.device_tts for c in hub.clients)
        ):
            return None  # nothing to say, or no audio yet: never a drop counted every tick
        if self._play(call, held=True, resync=True) is not None:
            return None
        self.resynced += 1
        return kind

    def _state(self, call: SpotterCall) -> SpotterState | None:
        origin = call.origin
        if origin is not None and callable(getattr(origin, "state", None)):
            st = origin.state()
            return st if isinstance(st, SpotterState) else None
        return None if self.worker is None else self.worker.state()

    def _valid(self, call: SpotterCall) -> bool:
        st = self._state(call)
        if st is None:
            return True
        occ = st.occupied
        k = call.kind
        if call.final:  # decided as the gate closed: the engine is already in a newer epoch
            if k in (CLEAR_LEFT, CLEAR_RIGHT):
                return not occ[SIDE_INDEX[k[6:]]]
            return k == CLEAR_ALL_ROUND and not any(occ)
        if st.epoch != call.epoch:
            return False
        age = (recv_clock_ns() - call.t_decided_ns) / 1e9
        if k in (CAR_LEFT, CAR_RIGHT):
            return age <= ONSET_MAX_AGE_S and occ[SIDE_INDEX[k[4:]]]
        if k == THREE_WIDE:
            return age <= ONSET_MAX_AGE_S and occ[LEFT] and occ[RIGHT]
        if k == HOLD_YOUR_LINE:
            side = SIDE_INDEX.get(call.side or "")
            return age <= ONSET_MAX_AGE_S and (occ[side] if side is not None else any(occ))
        if k in (CLEAR_LEFT, CLEAR_RIGHT):
            x = SIDE_INDEX[k[6:]]
            return age <= CLEAR_MAX_AGE_S and not occ[x] and st.last_seq[x] == call.seq
        if k == CLEAR_ALL_ROUND:
            return age <= CLEAR_MAX_AGE_S and not any(occ) and st.last_seq == (call.seq, call.seq)
        if k == STILL_THERE:
            side = SIDE_INDEX.get(call.side or "")
            return age <= STILL_MAX_AGE_S and side is not None and occ[side]
        return False

    def _phrase(self, call: SpotterCall) -> tuple[str, list[int], list[int]] | str:
        """(phrase id, sides it sets heard, sides it clears) or a drop reason (heard pairing)."""
        h = self.heard
        k = call.kind
        if call.test:
            return (phrase_id(k, call.side), [], [])  # the test button: no real car, heard pairing untouched
        if k in (CAR_LEFT, CAR_RIGHT):
            x = SIDE_INDEX[k[4:]]
            return "already_heard" if h[x] else (k, [x], [])
        if k == THREE_WIDE:
            return "already_heard" if all(h) else (k, [LEFT, RIGHT], [])
        if k in (CLEAR_LEFT, CLEAR_RIGHT):
            x = SIDE_INDEX[k[6:]]
            return (k, [], [x]) if h[x] else "not_heard"
        if k == CLEAR_ALL_ROUND:
            return (k, [], [LEFT, RIGHT]) if any(h) else "not_heard"
        if k == STILL_THERE:
            side = call.side or "left"
            x = SIDE_INDEX[side]
            return (phrase_id(k, side), [], []) if h[x] else (onset_phrase_id(side), [x], [])
        if k == HOLD_YOUR_LINE:
            hx = SIDE_INDEX.get(call.side or "")
            if hx is not None and not h[hx]:
                return (onset_phrase_id(call.side or "left"), [hx], [])  # its onset was lost: say that first
            return (k, [], [])
        return "unknown"

    def _play(self, call: SpotterCall, held: bool = False, *, resync: bool = False) -> str | None:
        """Say the call now (heard pairing applied). ``resync``: made up by ``resync`` (no packet behind it: no
        latency is recorded)."""
        hub = self.hub
        got = self._phrase(call)
        if isinstance(got, str):
            return self._drop(call, got)
        pid, sets, clears = got
        simple = self.simple()
        text = phrase_text(pid, simple)
        clip = self.audio.get(pid, simple)
        if clip is None and not any(c.device_tts for c in hub.clients):
            self.request_audio(force=True)
            return self._drop(call, "audio_not_ready")  # silence must not cut what is on air
        now = time.monotonic()
        meta: dict[str, object] = {"spotter": call.kind, "side": call.side, "seq": call.seq, "phrase": pid}
        if pid in _CUE_FIRST:
            meta[YIELDS_TO_CUE_KEY] = True  # the urgent path's exception: it never cuts a braking cue
        if call.test:
            meta["test"] = True
        msg = RadioMessage(
            id=f"m{next(hub._ids)}",
            kind=MessageKind.SPOTTER,
            priority=Priority.URGENT if call.urgent else Priority.HIGH,
            text=text,
            speech=text,
            created_mono=now,
            bypass_quiet=True,
            needs_speak_window=False,
            meta=meta,
        )
        interrupted = hub._on_air_message()
        hub._deliver(msg, clip, None, None, pcm_to_all=True)
        t2 = recv_clock_ns()
        for x in sets:
            self.heard[x] = True
        for x in clears:
            self.heard[x] = False
        if interrupted is not None and interrupted[0].id != msg.id:
            self.rehold_after_spotter(interrupted, now)
        self.spoken[call.kind] += 1
        q = (t2 - call.t_recv_ns) / 1e6
        plausible = 0 <= t2 - call.t_recv_ns <= MAX_PLAUSIBLE_NS and not call.test and not resync
        if plausible and held:
            self.held_ms.add((t2 - call.t_decided_ns) / 1e6)
        elif plausible:
            self.queued_ms.add(q)
            self.handoff_ms.add((t2 - call.t_decided_ns) / 1e6)
            if q > QUEUED_WARN_MS:
                log.debug("spotter call %s queued %.1f ms after its packet", call.kind, q)
        self._inflight[msg.id] = _Inflight(call, t2, msg.id, held)
        while len(self._inflight) > 32:
            del self._inflight[next(iter(self._inflight))]
        self.recent.appendleft(
            {
                "t_unix": time.time(),
                "kind": call.kind,
                "side": call.side,
                "phrase": pid,
                "spoken": True,
                "held": held,
                "resync": resync,
                "queued_ms": round(q, 1) if plausible else None,
                "started_ms": None,
                "msg_id": msg.id,
                "test": call.test,
            }
        )
        self._arm_backstop(msg, clip)
        return None

    def rehold_after_spotter(self, interrupted: tuple[RadioMessage, Any], now: float) -> None:
        """A message a spotter call cut: a proactive message or an answer/control is said again once (a new id,
        when the hold slot is free); a cue is dropped (its moment has passed)."""
        hub = self.hub
        msg, clip = interrupted
        if msg.kind in (MessageKind.CUE, MessageKind.SPOTTER) or msg.expired(now) or msg.meta.get("personal") is True:
            return  # an answer carrying an online name is never held, said again or logged
        from pitwall.voice.hub import MAX_RESENDS, RESENT_KEY

        resent = msg.meta.get(RESENT_KEY, 0)
        count = resent if isinstance(resent, int) and not isinstance(resent, bool) else 0
        if count >= MAX_RESENDS:
            log.info("message %s cut again by the spotter: not said a third time", msg.id)
            return
        if hub._held is None:
            again = dataclasses.replace(msg, id=f"m{next(hub._ids)}", meta={**msg.meta, RESENT_KEY: count + 1})
            hub._held = (again, clip, None)

    def _drop(self, call: SpotterCall, reason: str, *, replaced: bool = False) -> str:
        self.dropped[reason] += 1
        self.recent.appendleft(
            {
                "t_unix": time.time(),
                "kind": call.kind,
                "side": call.side,
                "spoken": False,
                "reason": reason if not replaced else f"{reason} (replaced)",
                "queued_ms": None,
                "started_ms": None,
                "test": call.test,
            }
        )
        return reason

    def _arm_backstop(self, msg: RadioMessage, clip: Any) -> None:
        loop = self.hub._loop
        if loop is None:
            return
        if self._backstop is not None:
            self._backstop.cancel()
        dur = clip.duration_s if clip is not None and clip.pcm else self.hub._speech_duration(msg, None)
        start = self.deliver_to_start_ms.median()
        delay = dur + BACKSTOP_PAD_S + (DEFAULT_START_S if start is None else start / 1000.0)
        self._backstop = loop.call_later(delay, self._backstop_fired, msg.id)

    def _backstop_fired(self, msg_id: str) -> None:
        self._backstop = None
        hub = self.hub
        if hub.speaking_id == msg_id:
            hub._on_playback(msg_id, "ended", None)  # as if the device had reported it (it may never)
        else:
            self.release()
            self.resync()

    # ------------------------------------------------------------------ latency
    def _measure_started(self, inf: _Inflight) -> None:
        t3 = recv_clock_ns()
        call = inf.call
        self.deliver_to_start_ms.add((t3 - inf.t2_ns) / 1e6)
        dt = t3 - call.t_recv_ns
        started = dt / 1e6 if 0 <= dt <= MAX_PLAUSIBLE_NS and not call.test else None
        if started is not None and not inf.held:
            self.started_ms.add(started)  # the ear latency: from the packet, not counting a wait in the mailbox
        for r in self.recent:
            if r.get("msg_id") == inf.msg_id:
                r["started_ms"] = None if started is None else round(started)
                break
        med = self.started_ms.median()
        w = self.worker
        if w is not None and med is not None and len(self.started_ms) >= EAR_MIN_SAMPLES:
            from pitwall.voice.hub import CUE_OUTPUT_ALLOWANCE_S

            ear = min(1.0, max(0.1, med / 1000.0 + CUE_OUTPUT_ALLOWANCE_S))
            w.set_ear_latency(ear)

    def _log_minute(self, now: float) -> None:
        if now - self._log_mono < LOG_EVERY_S:
            return
        self._log_mono = now
        spoken = sum(self.spoken.values())
        new_drops = self.dropped - self._log_dropped
        calls = spoken - self._log_spoken
        self._log_spoken = spoken
        self._log_dropped = Counter(self.dropped)
        if not calls and not new_drops:
            return
        q, st = self.queued_ms.summary(1), self.started_ms.summary(0)
        age = self.worker.data_age_ms.summary(0) if self.worker is not None else {"p95": None}
        reasons = ", ".join(f"{k}: {v}" for k, v in sorted(new_drops.items()))
        line = (
            f"spotter: {calls} calls ({sum(new_drops.values())} dropped{': ' + reasons if reasons else ''})"
            f", queued p50/p95 {q['p50']}/{q['p95']} ms, started p95 {st['p95']} ms, data age p95 {age['p95']} ms"
        )
        p95 = q["p95"]
        if isinstance(p95, int | float) and p95 > QUEUED_WARN_MS:
            log.warning("%s (queued p95 above %.0f ms)", line, QUEUED_WARN_MS)
        else:
            log.info("%s", line)

    # ------------------------------------------------------------------ API
    def latency(self) -> dict[str, Any]:
        w = self._origin if callable(getattr(self._origin, "latency", None)) else self.worker
        out: dict[str, Any] = {"n": len(self.queued_ms)}
        if w is not None:
            out.update(w.latency())
        out["queued_ms"] = self.queued_ms.summary(1)
        out["handoff_ms"] = self.handoff_ms.summary(2)
        out["started_ms"] = self.started_ms.summary(0)
        out["held_ms"] = self.held_ms.summary(0)
        return out

    def counters(self) -> dict[str, Any]:
        return {
            "received": self.received,
            "spoken": dict(self.spoken),
            "dropped": dict(self.dropped),
            "resynced": self.resynced,
        }

    def status(self) -> dict[str, Any]:
        st = self.audio.status()
        st["engine"] = getattr(self.hub.tts, "name", None)
        st["voice"] = self.effective_voice() or getattr(self.hub.tts, "voice", None)
        return st

    def test(self) -> None:
        """POST /api/spotter/test: "Car left", then "Clear left" 1.2 s later, through the real delivery path."""
        task = self._test_task
        if task is not None and not task.done():
            return
        self._test_task = asyncio.get_running_loop().create_task(self._run_test(), name="spotter-test")

    async def _run_test(self) -> None:
        hub = self.hub
        if any(not c.device_tts for c in hub.clients) and not self.audio.ready():
            self.request_audio(force=True)
            task = self._build_task
            if task is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(task), timeout=30.0)
        for i, kind in enumerate((CAR_LEFT, CLEAR_LEFT)):
            if i:
                await asyncio.sleep(TEST_GAP_S)
            now = recv_clock_ns()
            self.deliver(
                SpotterCall(
                    kind=kind,
                    side="left",
                    seq=0,
                    epoch=-1,
                    session_time_s=0.0,
                    t_recv_ns=now,
                    t_decided_ns=now,
                    test=True,
                )
            )


def _trim(clip: Any) -> Any:
    from pitwall.voice.hub import trim_silence

    return trim_silence(clip)
