"""Runtime wiring of the rig validation kit: subscriptions, the sampler task, lap-analysis jobs, bounded buffers.

Attached only while a run is active (``ValidationKit``); everything below runs on the asyncio loop except the
three callbacks marked otherwise, which only copy a few fields and hand over with ``call_soon_threadsafe``.

* ``LiveState`` listener: ``"event"`` arrives on the **ingest thread** for every game event; the only work there is
  one frozenset membership test (and a hand-over for six rare kinds). ``"lap"`` arrives on the analysis thread.
* ``DriverService`` listener: on the API thread that changed the seat.
* Radio hub observer: on the loop (O(1) appends and joins by message id / cue sequence).
* Sampler: 2 Hz (telemetry, session, tier, cue mode, decode counters), every 2 s the Connect-page counters
  (``Runtime.input_status``) and the TTS worker's counters, 1 Hz the game choice while that test is current.
* Lap jobs: one at a time in a worker thread (``asyncio.to_thread``), queue of 20: the stored lap trace gives the
  driver's braking onsets and the brake / steering under each proactive message that played on that lap.
* Database reads (game sessions, driver switches): existing ``storage.repo`` functions in a worker thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import statistics
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from pitwall import carclass
from pitwall.adapters.f1.enums import button_names
from pitwall.storage import repo
from pitwall.validate import evidence as E
from pitwall.validate import rules as R
from pitwall.validate.model import (
    LIMITS,
    ButtonRecord,
    CueRecord,
    GameTransition,
    InputPhaseRecord,
    LapRecord,
    ProactiveRecord,
    PttRecord,
    SessionSummary,
    SwitchRecord,
    SynthRecord,
    Tier,
)

if TYPE_CHECKING:
    from pitwall.analysis.laps import LapTrace
    from pitwall.validate.kit import ValidationKit

log = logging.getLogger(__name__)

EVENT_KINDS = frozenset({"session_started", "session_ended", "lights_out", "red_flag", "chequered_flag", "flashback"})
EVENT_TEXT = {
    "session_started": "Session started",
    "session_ended": "Session ended",
    "lights_out": "Lights out",
    "red_flag": "Red flag",
    "chequered_flag": "Chequered flag",
    "flashback": "Flashback",
}
GAME_INTEGRATION = {
    "f1_25": "f1",
    "f1_24": "f1",
    "gt7": "gt7",
    "ac": "ac",
    "forza_motorsport": "forza",
    "forza_horizon": "forza",
    "acc": "acc",
}
GAME_NAMES = {
    "f1_25": "F1 25",
    "f1_24": "F1 24",
    "gt7": "Gran Turismo 7",
    "ac": "Assetto Corsa",
    "acc": "Assetto Corsa Competizione",
}
SAMPLE_S = 0.5
LAP_QUEUE = 20
DB_REFRESH_S = 10.0
PHASE_MAX_S = 30.0
PHASE_HZ = 10.0
RATE_SAMPLES = 500
SESSION_SCAN = 300  # most recent sessions read when collecting game sessions
PROACTIVE_MAX_LAPS = 2  # a message still unmeasured this many laps after it started is finalised with what exists
PTT_JOIN_S = 120.0  # an answer is joined to a transcript at most this long after it
SPEAK_KINDS = frozenset({"lap_summary", "coaching"})  # voice.types.MessageKind values the speak-window test judges


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _age(src: dict[str, Any]) -> float:
    """Seconds since a sender was last heard (``last_seen_s``; 0.0 is a fresh sender, missing is never fresh)."""
    v = _num(src.get("last_seen_s"))
    return 1e9 if v is None else v


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


class Collector:
    def __init__(self, kit: ValidationKit) -> None:
        self.kit = kit
        self.rt = kit.rt
        self.live = kit.rt.live
        self.hub = kit.hub
        self.loop = kit.loop
        self.tier: Tier = "unknown"
        self.sender: str | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._lap_q: asyncio.Queue[tuple[int, str | None, int]] = asyncio.Queue(maxsize=LAP_QUEUE)
        self._attached = False
        self._ptt_waiting: deque[PttRecord] = deque(maxlen=20)
        self._ptt_by_msg: dict[str, PttRecord] = {}
        self._synth_by_msg: dict[str, SynthRecord] = {}
        self._pro_by_msg: dict[str, ProactiveRecord] = {}
        self._pro_started_mono: dict[str, float] = {}
        self._cue_by_seq: dict[int, CueRecord] = {}
        self._seated: int | None = None
        self._last_db = 0.0
        self._db_task: asyncio.Task[None] | None = None
        self._phase: InputPhaseRecord | None = None
        self._phase_task: asyncio.Task[None] | None = None
        self._phase_values: dict[str, list[float]] = {}
        self._hb_errors0: int | None = None
        self._restarts0: int | None = None
        self.tts_restarts: int | None = None
        self.synth_p95_ms: float | None = None
        self._last_game: tuple[Any, ...] | None = None
        self._last_conn: str | None = None
        self._last_sid: str | None = None
        self._last_mode: str | None = None
        self._mode_changed = False  # the braking-call mode changed since the last lap was stored
        self._decode0: dict[str, dict[str, Any]] = {}  # adapter name -> its counters when the run started
        self._button_seq = 0  # Setup › Controls probe: last button event copied into the run

    # ------------------------------------------------------------------ lifecycle
    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True
        self._seated = self.rt.drivers.active_id
        self._decode0 = _adapter_counts(self.rt, self.live)
        controls = getattr(self.rt, "controls", None)
        self._button_seq = int(getattr(getattr(controls, "probe", None), "seq", 0) or 0)
        self.live.subscribe(self._on_live)
        self.rt.drivers.subscribe(self._on_driver_thread)
        if self.hub is not None and callable(getattr(self.hub, "add_observer", None)):
            self.hub.add_observer(self._on_radio)
        self._tasks = [
            self.loop.create_task(self._sampler(), name="validation-sampler"),
            self.loop.create_task(self._lap_worker(), name="validation-laps"),
        ]

    async def detach(self) -> None:
        if not self._attached:
            return
        self._attached = False
        self.live.unsubscribe(self._on_live)
        self.rt.drivers.unsubscribe(self._on_driver_thread)
        if self.hub is not None and callable(getattr(self.hub, "remove_observer", None)):
            self.hub.remove_observer(self._on_radio)
        self._close_phase()
        tasks = [*self._tasks, *(t for t in (self._phase_task, self._db_task) if t is not None)]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []

    # ------------------------------------------------------------------ helpers
    def _append(self, key: str, lst: list[Any], rec: Any) -> None:
        lst.append(rec)
        limit = LIMITS[key]
        if len(lst) > limit:
            del lst[: len(lst) - limit]
            self.kit.run_or_raise().dropped_records += 1
        self.kit.dirty()

    def tier_now(self) -> Tier:
        """Evidence tier of this moment (spec 5.1); the sender class comes from the last input sample."""
        live = self.live
        self.tier = R.tier_of(bool(live.synthetic), live.source, self.sender, str(live.connection().get("status")))
        return self.tier

    def _common(self) -> tuple[float, Tier, str | None, int | None]:
        return time.time(), self.tier_now(), self.live.session_id, self.rt.drivers.active_id

    # ------------------------------------------------------------------ LiveState (ingest / analysis threads)
    def _on_live(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "event":
            k = payload.get("kind")
            if k in EVENT_KINDS:  # O(1); everything else returns at once (ingest thread)
                with contextlib.suppress(RuntimeError):
                    self.loop.call_soon_threadsafe(self._on_game_event, k)
            return
        if kind != "lap":
            return
        lap = payload.get("lap") or {}
        coach = payload.get("coach") or {}
        picked = [str(p["id"]) for p in coach.get("picked") or [] if isinstance(p, dict) and p.get("id")]
        live = self.live
        s = live.session
        snap = {
            "lap": dict(lap),
            "session_id": live.session_id,
            "source": live.source,
            "synthetic": live.synthetic,
            "cue_mode": live.cues.mode,
            "picked": picked,
            "drill_only": bool(coach.get("drill_only")),  # coachref: the drill point is the lap's only message
            "n_obs": len(live.observations),
            "game": None if s is None else s.game.value,
            "track_id": None if s is None else s.track_id,
            "track_name": None if s is None else s.track_name,
        }
        with contextlib.suppress(RuntimeError):
            self.loop.call_soon_threadsafe(self._on_lap, snap)

    def _on_game_event(self, kind: str) -> None:
        if self.kit.run is None:
            return
        self.kit.timeline("session", EVENT_TEXT.get(kind, kind))

    def _on_lap(self, snap: dict[str, Any]) -> None:
        run = self.kit.run
        lap = snap["lap"]
        lap_id = _int(lap.get("lap_id"))
        number = _int(lap.get("lap_number"))
        if run is None or lap_id is None or number is None:
            return
        tier = R.tier_of(bool(snap["synthetic"]), snap["source"], self.sender, "live")
        # the mode is read when the lap is processed: a lap during which it changed was driven partly in each
        mode = "mixed" if self._mode_changed else snap["cue_mode"]
        self._mode_changed = False
        rec = LapRecord(
            t_unix=time.time(),
            tier=tier,
            session_id=snap["session_id"],
            driver_id=self.rt.drivers.active_id,
            lap_id=lap_id,
            lap_number=number,
            lap_time_ms=_int(lap.get("lap_time_ms")),
            clean=bool(lap.get("clean")),
            flags=[str(f) for f in lap.get("flags") or []],
            game=snap["game"],
            track_id=snap["track_id"],
            track_name=snap["track_name"],
            cue_mode=mode,
            n_observations=int(snap["n_obs"]),
            picked_ids=list(snap["picked"]),
            drill_only=bool(snap.get("drill_only")),
        )
        self._append("laps", run.evidence.laps, rec)
        try:
            self._lap_q.put_nowait((lap_id, rec.session_id, number))
        except asyncio.QueueFull:
            run.dropped_records += 1  # its calls stay without a matched onset; never blocks anything

    # ------------------------------------------------------------------ drivers (API thread)
    def _on_driver_thread(self, driver: Any) -> None:
        did = None if driver is None else _int(getattr(driver, "id", None))
        with contextlib.suppress(RuntimeError):
            self.loop.call_soon_threadsafe(self._on_driver, did, time.time())

    def _on_driver(self, driver_id: int | None, t: float) -> None:
        run = self.kit.run
        if run is None or driver_id == self._seated:
            return  # a profile edit, not a switch
        rec = SwitchRecord(
            t_unix=t,
            tier=self.tier_now(),
            session_id=self.live.session_id,
            driver_id=driver_id,
            from_driver_id=self._seated,
            to_driver_id=driver_id,
            session_before=self.live.session_id,
        )
        self._seated = driver_id
        self._append("switches", run.evidence.switches, rec)
        self.kit.timeline("note", f"Driver switch: #{rec.from_driver_id} to #{driver_id}")
        self.loop.call_later(R.SWITCH_SETTLE_S, self._settle_switch, rec)

    def _settle_switch(self, rec: SwitchRecord) -> None:
        rec.session_after = self.live.session_id
        snap = self.live.cues.snapshot()
        reason = snap.get("reason")
        rec.cue_reason_after = str(reason) if reason else None
        plan = self.live.cues.plan
        rec.cue_ref_lap_id = plan.ref_lap_id if plan.cues else None
        rec.settled = True
        self.kit.dirty()

    # ------------------------------------------------------------------ radio hub observer (loop)
    def _on_radio(self, kind: str, p: dict[str, Any]) -> None:
        run = self.kit.run
        if run is None:
            return
        handler = getattr(self, f"_radio_{kind}", None)
        if handler is not None:
            handler(p)

    def _radio_transcript(self, p: dict[str, Any]) -> None:
        t, tier, sid, did = self._common()
        src = p.get("ptt_source")
        rec = PttRecord(
            t_unix=t,
            tier=tier,
            session_id=sid,
            driver_id=did,
            id="",
            source=src if src in ("screen", "wheel") else "screen",
            client=None,
            transcript=str(p.get("text") or ""),
            stt_ms=_int(p.get("stt_ms")),
            audio_s=_num(p.get("audio_s")),
        )
        self._append("ptt", self.kit.run_or_raise().evidence.ptt, rec)
        if rec.transcript.strip():
            self._ptt_waiting.append(rec)

    def _join_ptt(self, p: dict[str, Any]) -> PttRecord:
        question = str(p.get("question") or "")
        now = time.time()
        for rec in reversed(self._ptt_waiting):
            if rec.transcript.strip() == question.strip() and now - rec.t_unix <= PTT_JOIN_S:
                self._ptt_waiting.remove(rec)
                return rec
        t, tier, sid, did = self._common()
        rec = PttRecord(
            t_unix=t, tier=tier, session_id=sid, driver_id=did, id="", source="typed", client=None, transcript=question
        )
        self._append("ptt", self.kit.run_or_raise().evidence.ptt, rec)
        return rec

    def _record_id(self, msg_id: str) -> str:
        """A question's record id: the answer's message id, prefixed with this service start's tag (message ids
        restart at m1 when the service restarts, and a resumed run keeps the earlier questions)."""
        return f"{self.kit.boot_tag}-{msg_id}" if msg_id else ""

    def _radio_answer(self, p: dict[str, Any]) -> None:
        rec = self._join_ptt(p)
        mid = str(p.get("msg_id") or "")
        rec.id = self._record_id(mid)
        rec.intent = p.get("intent")
        rec.answer = p.get("text")
        rec.grounded = p.get("grounded")
        rec.engineer_ms = _int(p.get("engineer_ms"))
        rec.answer_source = "llm" if p.get("llm") else ("fallback" if p.get("use_llm") else "deterministic")
        self._ptt_by_msg[mid] = rec
        self.kit.dirty()

    def _radio_command(self, p: dict[str, Any]) -> None:
        rec = self._join_ptt(p)
        mid = str(p.get("msg_id") or "")
        rec.id = self._record_id(mid)
        rec.intent = "validation"
        rec.answer = p.get("text")
        rec.grounded = True
        rec.answer_source = "command"
        self._ptt_by_msg[mid] = rec
        self.kit.dirty()

    def _radio_synth(self, p: dict[str, Any]) -> None:
        t, tier, _sid, _did = self._common()
        rec = SynthRecord(
            t_unix=t,
            tier=tier,
            msg_id=str(p.get("msg_id") or ""),
            kind=str(p.get("kind") or ""),
            engine=str(p.get("engine") or ""),
            neural=bool(p.get("neural")),
            synth_ms=_num(p.get("synth_ms")),
            fallback_reason=p.get("fallback_reason"),
        )
        self._append("synth", self.kit.run_or_raise().evidence.synth, rec)
        self._synth_by_msg[rec.msg_id] = rec
        _bound(self._synth_by_msg)

    def _radio_proactive(self, p: dict[str, Any]) -> None:
        if not p.get("needs_speak_window") or int(p.get("priority") or 0) >= 100:
            return  # urgent calls and messages without a speak window are not judged by the speak-window rule
        if p.get("kind") not in SPEAK_KINDS:
            return  # the speak-window test judges lap summaries and coaching (not alerts, not the kit's own prompts)
        t, tier, sid, did = self._common()
        meta = p.get("meta") or {}
        st = p.get("state") or {}
        ttb = _num(st.get("time_to_next_braking_s"))
        rec = ProactiveRecord(
            t_unix=t,
            tier=tier,
            session_id=sid,
            driver_id=did,
            id=str(p.get("msg_id") or ""),
            kind=str(p.get("kind") or ""),
            text=str(p.get("text") or ""),
            lap=_int(p.get("lap_number")),
            lap_id=_int(meta.get("lap_id")),
            observation_id=None if meta.get("observation_id") is None else str(meta.get("observation_id")),
            drill_id=_int(meta.get("drill_id")),
            held_s=round(float(_num(p.get("held_s")) or 0.0), 2),
            state_at_send={
                "on_track": bool(st.get("on_track")),
                "brake": _num(st.get("brake")),
                "steering": _num(st.get("steering")),
                "speed_kph": _num(st.get("speed_kph")),
                "ttb_s": None if ttb is None else round(ttb, 2),
            },
        )
        rec.cls = "off_track" if not rec.state_at_send["on_track"] else "unmeasured"
        self._append("proactive", self.kit.run_or_raise().evidence.proactive, rec)
        self._pro_by_msg[rec.id] = rec
        _bound(self._pro_by_msg)

    def _radio_deliver(self, p: dict[str, Any]) -> None:
        mid = str(p.get("msg_id") or "")
        s = self._synth_by_msg.get(mid)
        if s is not None:
            s.n_bytes = int(p.get("n_bytes") or 0)
            s.audio_clients = int(p.get("audio_clients") or 0)
        pro = self._pro_by_msg.get(mid)
        if pro is not None and s is not None:
            pro.engine = s.engine
        cut = self._pro_by_msg.get(str(p.get("cancelled_id") or ""))
        if cut is not None and cut.id != mid:
            cut.cut = True
        self.kit.dirty()

    def _radio_playback(self, p: dict[str, Any]) -> None:
        mid = str(p.get("msg_id") or "")
        state = p.get("state")
        frame = p.get("frame")
        brief = (
            None
            if not isinstance(frame, dict)
            else {
                "lap": _int(frame.get("lap")),
                "lap_distance_m": _num(frame.get("lap_distance_m")),
                "session_time_s": _num(frame.get("session_time_s")),
            }
        )
        mono = _num(p.get("t_mono")) or time.monotonic()
        if state == "started":
            ptt = self._ptt_by_msg.get(mid)
            if ptt is not None:
                lat = p.get("latency") or {}
                if lat:
                    ptt.to_playback_ms = _int(lat.get("to_playback_ms"))
                    ptt.to_first_audio_ms = _int(lat.get("to_first_audio_ms"))
                    ptt.tts_ms = _int(lat.get("tts_ms"))
                    ptt.stt_ms = ptt.stt_ms if ptt.stt_ms is not None else _int(lat.get("stt_ms"))
                    ptt.engineer_ms = ptt.engineer_ms if ptt.engineer_ms is not None else _int(lat.get("engineer_ms"))
                if ptt.client is None and p.get("client"):
                    ptt.client = str(p.get("client"))[:32]
            s = self._synth_by_msg.get(mid)
            if s is not None:
                s.started = True
            pro = self._pro_by_msg.get(mid)
            if pro is not None and not pro.started:
                pro.started = True
                pro.start_frame = brief
                self._pro_started_mono[mid] = mono
                if pro.state_at_send.get("on_track"):
                    pro.cls = "unmeasured"
        elif state == "ended":
            pro = self._pro_by_msg.get(mid)
            if pro is not None and pro.started and pro.end_frame is None:
                pro.end_frame = brief
                t0 = self._pro_started_mono.pop(mid, None)
                pro.duration_s = None if t0 is None else round(max(0.0, mono - t0), 2)
        self.kit.dirty()

    def _radio_cue(self, p: dict[str, Any]) -> None:
        seq = _int(p.get("seq"))
        lap = _int(p.get("lap"))
        nums = [_num(p.get(k)) for k in ("target_m", "aim_m", "d_m", "speed_kph", "ttg_s")]
        if seq is None or lap is None or any(x is None for x in nums):
            return  # a call without its position or speed cannot be measured, and is never stored as zeros
        target_m, aim_m, d_m, speed_kph, ttg_s = (float(x or 0.0) for x in nums)
        t, tier, sid, did = self._common()
        rec = CueRecord(
            t_unix=t,
            tier=tier,
            session_id=sid,
            driver_id=did,
            seq=seq,
            msg_id=p.get("msg_id"),
            lap=lap,
            corner=str(p.get("corner") or ""),
            kind=str(p.get("kind") or "brake"),
            heads_up=p.get("ref_lap_id") is None,
            focus=bool(p.get("focus")),
            target_m=round(target_m, 1),
            aim_m=round(aim_m, 1),
            d_m=round(d_m, 1),
            speed_kph=round(speed_kph, 1),
            ttg_s=round(ttg_s, 2),
            path=str(p.get("path") or "pcm"),
            outcome="dropped" if p.get("status") == "dropped" else "sent",
            drop_reason=p.get("reason") if p.get("status") == "dropped" else None,
            cue_mode=self.live.cues.mode,
            engine=p.get("engine"),
        )
        rec.cls = R.classify_cue(rec)
        self._append("cues", self.kit.run_or_raise().evidence.cues, rec)
        self._cue_by_seq[seq] = rec
        _bound(self._cue_by_seq)

    def _radio_cue_timing(self, p: dict[str, Any]) -> None:
        seq = _int(p.get("seq"))
        rec = None if seq is None else self._cue_by_seq.get(seq)
        if rec is None:
            return
        err = _num(p.get("error_m"))
        rec.error_m = None if err is None else round(err, 1)
        rec.latency_ms = _int(p.get("latency_ms"))
        E.enrich_cue(rec, None)
        self.kit.dirty()

    # ------------------------------------------------------------------ sampler (loop)
    async def _sampler(self) -> None:
        n = 0
        while True:
            await asyncio.sleep(SAMPLE_S)
            n += 1
            try:
                self._tick(n)
            except Exception:
                log.exception("validation sampler failed")

    def _tick(self, n: int) -> None:
        run = self.kit.run
        if run is None:
            return
        now = time.time()
        if n % 4 == 1:
            self._sample_inputs()
            self._sample_tts(run.selected_items)
        self._sample_live(now)
        self._sample_buttons(n)
        if run.current_item == "game_selection" and n % 2 == 0:
            self._sample_game(now)
        if n % 4 == 0:
            self.kit.recompute(now)
            self.kit.flush_prompt(now)
        if now - self._last_db >= DB_REFRESH_S and self._wants_db(run.selected_items):
            self._last_db = now
            self.schedule_db_refresh()
        self.kit.maybe_save(now)

    def _sample_live(self, now: float) -> None:
        run = self.kit.run_or_raise()
        live = self.live
        conn = live.connection()
        status = str(conn.get("status"))
        if status == "live" and self._last_conn != "live":
            self._sample_inputs()  # who is sending, before the first live sample is labelled
        tier = R.tier_of(bool(live.synthetic), live.source, self.sender, status)
        self.tier = tier
        s = live.session
        sid = live.session_id
        game = None if s is None else s.game.value
        hub = self.hub
        ctx = {
            "telemetry": status,
            "tier": tier,
            "game": game,
            "platform": None if s is None else s.platform.value,
            "track": None if s is None else (s.track_name or s.track_id),
            "session_id": sid,
            "packet_format": None if s is None else _int(s.extra.get("packet_format")),
            "game_version": None
            if s is None
            else (str(s.extra["game_version"]) if s.extra.get("game_version") is not None else None),
            "driver_id": self.rt.drivers.active_id,
            "radio_clients": 0 if hub is None else len(hub.clients),
            "cue_mode": live.cues.mode,
        }
        if ctx != run.context:
            run.context = ctx
            self.kit.touch()
        if status != self._last_conn:
            self._last_conn = status
            what = (
                f"Telemetry live: {GAME_NAMES.get(game or '', game or '-')}"
                + (f" on {ctx['platform'].upper()}" if ctx["platform"] and ctx["platform"] != "unknown" else "")
                + (f", {ctx['track']}" if ctx["track"] else "")
                if status == "live"
                else ("Telemetry stopped" if status == "stale" else "No telemetry")
            )
            self.kit.timeline("telemetry", what + ("" if tier in ("live", "unknown") else f" ({tier})"))
        if sid != self._last_sid and sid is not None:
            self._last_sid = sid
            self.kit.timeline("session", f"New session ({GAME_NAMES.get(game or '', game or '-')}, {tier})")
        if live.cues.mode != self._last_mode:
            self._mode_changed = self._last_mode is not None
            self._last_mode = live.cues.mode
            self.kit.timeline("cue_mode", f"Braking calls: {live.cues.mode}")
        if sid is not None and s is not None and status == "live":
            fresh = {k: s.extra[k] for k in _EXTRA_KEYS if k in s.extra}
            if s.formula is not None:
                fresh["formula"] = s.formula  # F2 (validation check f2_ps5)
            if s.formula == "F2":
                # an ERS value published for an F2 car (the adapter leaves it empty: F1 25 sends 0 for F2 cars)
                f = live.frame
                before = (run.session_extra.get(sid) or {}).get("ers_published")
                if f is not None:
                    fresh["ers_published"] = bool(before) or f.ers_store_j is not None
                elif isinstance(before, bool):
                    fresh["ers_published"] = before
            if fresh and run.session_extra.get(sid) != fresh:
                run.session_extra[sid] = fresh
                self.kit.dirty()
                if len(run.session_extra) > LIMITS["sessions"]:
                    del run.session_extra[next(iter(run.session_extra))]
        if sid is not None and status == "live" and tier != "unknown":
            prev = run.session_tiers.get(sid)
            if prev is None or (prev == "unknown"):
                run.session_tiers[sid] = tier
        stats = conn.get("decode")
        if isinstance(stats, dict) and stats and tier != "unknown":
            g = E.adapter_game(stats.get("adapter"))
            base = self._decode0.get(str(stats.get("adapter")))
            if g is not None and E.tally_decode(run.evidence.decode, f"{tier}|{g}", stats, base):
                self.kit.dirty()

    def _sample_buttons(self, n: int) -> None:
        """Setup › Controls: F1 25 presses from the probe's ring (read here on the loop, never on the ingest thread),
        and every 2 s the seated driver's F1 25 layout (its UDP Actions) for the wheel_buttons rule."""
        controls = getattr(self.rt, "controls", None)
        probe = getattr(controls, "probe", None)
        if controls is None or probe is None:
            return
        run = self.kit.run_or_raise()
        events = probe.since(self._button_seq)
        if events:
            self._button_seq = events[-1].seq
        for ev in events:
            pressed = ev.pressed
            if not pressed:
                continue
            tier: Tier
            if ev.origin == "live":
                tier = self.tier_now()
            elif ev.origin == "replay":
                tier = "recorded"
            elif ev.origin == "loopback":  # sent from this computer (the probe's tag)
                tier = "loopback"
            else:
                tier = "synthetic"
            rec = ButtonRecord(
                ev.t_unix,
                tier,
                self.live.session_id,
                self.rt.drivers.active_id,
                ev.seq,
                ev.status,
                button_names(pressed),
                ev.origin,
            )
            self._append("buttons", run.evidence.buttons, rec)
        if n % 4 == 2:
            try:
                snap = controls.layout_snapshot()
            except Exception:
                log.exception("validation: could not read the controls layout")
                return
            if snap != run.controls_layout:
                run.controls_layout = snap
                self.kit.touch()

    def _sample_inputs(self) -> None:
        run = self.kit.run_or_raise()
        try:
            rows = {str(r.get("key")): r for r in self.rt.input_status()}
        except Exception:
            log.exception("validation: input status failed")
            return
        s = self.live.session
        key = None if s is None else GAME_INTEGRATION.get(s.game.value)
        candidates = [rows[key]] if key in rows else list(rows.values())
        fresh: list[dict[str, Any]] = []
        for row in candidates:
            for src in row.get("sources") or []:
                if isinstance(src, dict) and _age(src) < 5.0:
                    fresh.append(src)
        fresh.sort(key=lambda x: float(x.get("last_seen_s") or 0.0))
        self.sender = R.sender_class(str(fresh[0].get("ip"))) if fresh else None
        for game in ("gt7", "ac"):
            row = rows.get(game)
            if not row or not row.get("enabled"):
                continue
            tally = run.evidence.inputs.setdefault(game, {"rates": [], "lan_sender": False})
            srcs = [x for x in row.get("sources") or [] if isinstance(x, dict) and _age(x) < 2.0]
            lan = [x for x in srcs if R.sender_class(str(x.get("ip"))) == "lan"]
            if lan:
                tally["lan_sender"] = True
                pps = _num(lan[0].get("packets_per_s"))
                if game == "gt7" and pps and pps > 0:
                    _push(tally["rates"], pps)
            if game == "gt7":
                hb = row.get("heartbeat") or {}
                sent, errs = _int(hb.get("sent")), _int(hb.get("errors"))
                if sent is not None:
                    if self._hb_errors0 is None:
                        self._hb_errors0 = errs or 0
                    tally["heartbeat_sent"] = max(int(tally.get("heartbeat_sent") or 0), sent)
                    tally["heartbeat_errors"] = max(0, (errs or 0) - self._hb_errors0)
                    tally["variant"] = hb.get("variant")
            else:
                client = row.get("client") or {}
                hs = _int(client.get("handshakes_answered"))
                if hs is not None:
                    tally["handshakes"] = max(int(tally.get("handshakes") or 0), hs)
                rate = _num(client.get("rate"))
                if rate and rate > 0 and lan:
                    _push(tally["rates"], rate)
                if client.get("packet_sizes"):
                    tally["packet_sizes"] = dict(client["packet_sizes"])
                tally["state"] = client.get("state")

    def _sample_tts(self, selected: list[str]) -> None:
        if "radio_kokoro" not in selected or self.hub is None:
            return
        diag = getattr(self.hub.tts, "diagnostics", None)
        if not callable(diag):
            return
        try:
            d = diag()
        except Exception:
            return
        restarts = _int(d.get("restarts"))
        if restarts is not None:
            if self._restarts0 is None:
                self._restarts0 = restarts
            self.tts_restarts = restarts - self._restarts0
        synth = d.get("synth_ms") or {}
        self.synth_p95_ms = _num(synth.get("p95")) if isinstance(synth, dict) else None

    def _sample_game(self, now: float) -> None:
        fn = getattr(self.live, "game_block", None)
        if not callable(fn):
            return
        try:
            gb = fn()
        except Exception:
            return
        if not isinstance(gb, dict):
            return
        detected = gb.get("detected")
        det_id = detected.get("entry_id") if isinstance(detected, dict) else None
        key = (gb.get("selected_id"), det_id, bool(gb.get("mismatch")))
        if key == self._last_game:
            return
        self._last_game = key
        rec = GameTransition(
            now,
            None if key[0] is None else str(key[0]),
            None if key[1] is None else str(key[1]),
            key[2],
            self.tier_now(),
        )
        self._append("game", self.kit.run_or_raise().evidence.game, rec)

    # ------------------------------------------------------------------ lap jobs (worker thread)
    async def _lap_worker(self) -> None:
        while True:
            lap_id, session_id, number = await self._lap_q.get()
            run = self.kit.run
            if run is None:
                continue
            lap_ids = {lap.lap_number: lap.lap_id for lap in run.evidence.laps if lap.session_id == session_id}
            pending: list[tuple[str, dict[str, Any] | None, dict[str, Any] | None, float | None]] = [
                (p.id, p.start_frame, p.end_frame, p.duration_s)
                for p in run.evidence.proactive
                if p.session_id == session_id
                and p.started
                and not p.measured
                and p.start_frame is not None
                and isinstance(p.start_frame.get("lap"), int)
                and p.start_frame["lap"] <= number
            ]
            try:
                onsets, measures = await asyncio.to_thread(self._lap_job, lap_id, number, lap_ids, pending)
            except Exception:
                log.exception("validation lap job failed (lap %s)", lap_id)
                continue
            run = self.kit.run
            if run is None:
                continue
            run.evidence.lap_onsets[str(lap_id)] = onsets
            if len(run.evidence.lap_onsets) > LIMITS["lap_onsets"]:
                for k in list(run.evidence.lap_onsets)[: len(run.evidence.lap_onsets) - LIMITS["lap_onsets"]]:
                    del run.evidence.lap_onsets[k]
            by_id = {p.id: p for p in run.evidence.proactive}
            for pid, m, final in measures:
                p = by_id.get(pid)
                if p is None:
                    continue
                E.apply_measure(p, m)
                p.measured = final
            self.kit.dirty()

    def _lap_job(
        self,
        lap_id: int,
        number: int,
        lap_ids: dict[int, int],
        pending: list[tuple[str, dict[str, Any] | None, dict[str, Any] | None, float | None]],
    ) -> tuple[list[float], list[tuple[str, E.PlaybackMeasure | None, bool]]]:
        traces: dict[int, LapTrace] = {}
        with self.rt.db.read() as c:
            trace = repo.load_lap_trace(c, lap_id)
            if trace is not None:
                traces[number] = trace
            wanted = {
                n
                for _pid, start, _end, _dur in pending
                if start is not None
                for n in range(int(start["lap"]), number + 1)
                if n in lap_ids and n not in traces
            }
            for n in wanted:
                tr = repo.load_lap_trace(c, lap_ids[n])
                if tr is not None:
                    traces[n] = tr
        onsets = [] if trace is None else E.braking_onsets(trace)
        out: list[tuple[str, E.PlaybackMeasure | None, bool]] = []
        for pid, start, end, dur in pending:
            assert start is not None
            end_raw = None if end is None else end.get("lap")
            end_lap = end_raw if isinstance(end_raw, int) else int(start["lap"])
            if end_lap > number:
                continue  # crosses into a lap not stored yet
            m = E.measure_playback(traces, start, end, dur)
            stale = number - int(start["lap"]) >= PROACTIVE_MAX_LAPS
            out.append((pid, m, m is None or m.complete or stale))
        return onsets, out

    # ------------------------------------------------------------------ database reads (worker thread)
    @staticmethod
    def _wants_db(selected: list[str]) -> bool:
        return any(i in selected for i in ("ac_ps5", "gt7_ps5", "f2_ps5", "driver_switch"))

    def schedule_db_refresh(self) -> None:
        if self._db_task is not None and not self._db_task.done():
            return
        self._db_task = self.loop.create_task(self.refresh_db())

    async def refresh_db(self) -> None:
        run = self.kit.run
        if run is None:
            return
        since = run.started_unix
        sids = set(run.session_tiers)
        settled = [s for s in run.evidence.switches if s.settled]
        switches = [(s.session_before, s.session_after, s.cue_ref_lap_id) for s in settled]
        try:
            sessions, switch_rows = await asyncio.to_thread(self._db_job, since, sids, switches)
        except Exception:
            log.exception("validation database read failed")
            return
        run = self.kit.run
        if run is None:
            return
        tiers = run.session_tiers
        out: list[SessionSummary] = []
        for row, laps, n_obs, corners in sessions:
            sid = str(row["id"])
            source = str(row.get("source") or "")
            tier: Tier = tiers.get(sid) or (
                "synthetic" if row.get("synthetic") else ("recorded" if source.startswith("replay:") else "unknown")
            )
            info = row.get("info") or {}
            out.append(
                SessionSummary(
                    session_id=sid,
                    game=str(row.get("game")),
                    tier=tier,
                    source=source.split(":", 1)[0],
                    started_unix=float(row.get("started_unix") or 0.0),
                    ended_unix=_num(row.get("ended_unix")),
                    track_id=row.get("track_id"),
                    track_name=row.get("track_name"),
                    track_length_m=_num(row.get("track_length_m")),
                    platform=row.get("platform"),
                    driver_id=_int(row.get("driver_id")),
                    game_session_uid=None if row.get("game_session_uid") is None else str(row.get("game_session_uid")),
                    laps=laps,
                    n_observations=n_obs,
                    corners=corners,
                    extra={**{k: info.get(k) for k in _EXTRA_KEYS if k in info}, **run.session_extra.get(sid, {})},
                )
            )
        run.evidence.sessions = out[-LIMITS["sessions"] :]
        for s, (before, after, laps_before, laps_after, owner) in zip(settled, switch_rows, strict=True):
            E.settle_switch(s, before, after, laps_before, laps_after, owner)
        self.kit.dirty()
        self.kit.recompute(time.time())

    def _db_job(
        self, since: float, sids: set[str], switches: list[tuple[str | None, str | None, int | None]]
    ) -> tuple[list[tuple[dict[str, Any], list[dict[str, Any]], int, int | None]], list[Any]]:
        sessions: list[tuple[dict[str, Any], list[dict[str, Any]], int, int | None]] = []
        corners_cache: dict[tuple[str, str, str | None], int | None] = {}
        switch_rows: list[Any] = []
        with self.rt.db.read() as c:
            rows = [
                r
                for r in repo.list_sessions(c, limit=SESSION_SCAN, include_empty=True)
                if float(r.get("started_unix") or 0) >= since - 1.0
            ]
            seen = {r["id"] for r in rows}
            for sid in sids - seen:
                r = repo.get_session(c, sid)
                if r is not None:
                    rows.append(r)
            for r in sorted(rows, key=lambda x: float(x.get("started_unix") or 0)):
                game = str(r.get("game"))
                if game not in ("gt7", "ac", "f1_25"):  # f1_25: the F2 check (f2_ps5)
                    continue
                laps = [
                    {
                        "lap_number": lap.get("lap_number"),
                        "lap_time_ms": lap.get("lap_time_ms"),
                        "clean": bool(lap.get("clean")),
                        "flags": list(lap.get("flags") or []),
                        "n_samples": lap.get("n_samples"),  # the F2 check: a one-sample lap, a short duplicate
                    }
                    for lap in repo.list_laps(c, str(r["id"]))
                ]
                n_obs = len(repo.list_observations(c, str(r["id"]), limit=50))
                corners = None
                tid = r.get("track_id")
                if isinstance(tid, str):
                    fam = carclass.family_of_row(r)  # the session's car class family
                    ck = (game, tid, fam)
                    if ck not in corners_cache:
                        model = repo.load_track_model(c, game, tid, fam)
                        corners_cache[ck] = None if model is None else len(model.corners)
                    corners = corners_cache[ck]
                sessions.append((r, laps, n_obs, corners))
            for before, after, ref in switches:
                b = None if before is None else repo.get_session(c, before)
                a = None if after is None else repo.get_session(c, after)
                lb = [] if before is None else repo.list_laps(c, before)
                la = [] if after is None else repo.list_laps(c, after)
                owner = None
                if ref is not None:
                    lap = repo.get_lap(c, ref, with_trace=False)
                    if lap is not None:
                        srow = repo.get_session(c, str(lap["session_id"]))
                        owner = None if srow is None else _int(srow.get("driver_id"))
                switch_rows.append((b, a, lb, la, owner))
        return sessions, switch_rows

    # ------------------------------------------------------------------ input check (loop)
    def start_phase(self, item_id: str, phase: str, rotation_deg: float | None) -> None:
        self._close_phase()
        if phase == "stop":
            return
        rec = InputPhaseRecord(
            item_id=item_id, phase=phase, start_unix=time.time(), rotation_deg=rotation_deg, tier=self.tier_now()
        )
        self._append("input_phases", self.kit.run_or_raise().evidence.input_phases, rec)
        self._phase = rec
        self._phase_values = {"steer": [], "throttle": [], "brake": [], "gear": []}
        self._phase_task = self.loop.create_task(self._phase_sampler(rec))

    async def _phase_sampler(self, rec: InputPhaseRecord) -> None:
        t0 = time.monotonic()
        last: Any = None
        while time.monotonic() - t0 < PHASE_MAX_S and self._phase is rec:
            f = self.live.frame
            # only new frames count: a stopped stream leaves the last frame in place, which is not a reading
            if f is not None and f is not last and self.live.connection().get("status") == "live":
                last = f
                for key, v in (("steer", f.steering), ("throttle", f.throttle), ("brake", f.brake), ("gear", f.gear)):
                    x = _num(v)
                    if x is not None:
                        self._phase_values[key].append(x)
            await asyncio.sleep(1.0 / PHASE_HZ)
        if self._phase is rec:
            self._close_phase()

    def _close_phase(self) -> None:
        rec, self._phase = self._phase, None
        if rec is None:
            return
        vals = self._phase_values
        steer = vals.get("steer") or []
        rec.end_unix = time.time()
        rec.samples = max(len(steer), len(vals.get("throttle") or []))
        rec.steer_mean = None if not steer else round(statistics.fmean(steer), 3)
        rec.steer_min = None if not steer else round(min(steer), 3)
        rec.steer_max = None if not steer else round(max(steer), 3)
        rec.throttle_max = None if not vals.get("throttle") else round(max(vals["throttle"]), 3)
        rec.brake_max = None if not vals.get("brake") else round(max(vals["brake"]), 3)
        rec.gear_min = None if not vals.get("gear") else int(min(vals["gear"]))
        s = self.live.session
        # the session's raw range is only this check's reading when the car sent inputs during it
        rng = None if s is None or rec.samples == 0 else s.extra.get("steer_raw_range")
        rec.steer_raw_range = [float(x) for x in rng] if isinstance(rng, list | tuple) and len(rng) == 2 else None
        self._phase_values = {}
        if self.kit.run is not None:
            self.kit.touch()


_EXTRA_KEYS = (
    "packet_variant",
    "best_lap_ms",
    "track_length_quality",
    "lap_distance_status",
    "steer_raw_range",
    "handshake_status",
    "handshake_encoding",
    "rtcarinfo_size_field",
    "packet_format",
    "game_version",
    "formula",  # F1 Session.formula (the F2 check)
    "session_type_id",  # F1 Session.sessionType (the F2 check: one-shot qualifying)
)


def _adapter_counts(rt: Any, live: Any) -> dict[str, dict[str, Any]]:
    """Every decoding adapter's counters now, by adapter name (the base the run's decode tally subtracts). Read on the
    loop from the runtime's inputs: plain integers the ingest threads only ever increase."""
    out: dict[str, dict[str, Any]] = {}
    routers = [getattr(i, "router", None) for i in dict(getattr(rt, "inputs", None) or {}).values()]
    ac = getattr(rt, "ac", None)
    routers.append(getattr(ac, "router", None) if ac is not None else None)
    for router in routers:
        for adapter in list(getattr(router, "adapters", None) or []):
            stats = getattr(adapter, "stats", None)
            info = getattr(adapter, "info", None)
            if stats is None or info is None:
                continue
            for _attempt in range(3):  # by_type can grow under the copy (ingest thread): try again
                try:
                    out[str(info.name)] = E.decode_counts(
                        {
                            "packets": stats.packets,
                            "rejected": stats.rejected,
                            "errors": stats.errors,
                            "by_type": dict(stats.by_type),
                        }
                    )
                    break
                except Exception:
                    continue
    pub = getattr(live, "decode_stats", None)  # the last published counters (an adapter not reached above)
    if isinstance(pub, dict) and pub.get("adapter") and str(pub["adapter"]) not in out:
        out[str(pub["adapter"])] = E.decode_counts(pub)
    return out


def _push(lst: list[Any], v: Any) -> None:
    lst.append(round(float(v), 1))
    if len(lst) > RATE_SAMPLES:
        del lst[: len(lst) - RATE_SAMPLES]


def _bound(d: dict[Any, Any], size: int = 500) -> None:
    while len(d) > size:
        del d[next(iter(d))]


__all__ = ["EVENT_KINDS", "Collector"]
