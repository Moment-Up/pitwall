"""``ValidationKit``: run lifecycle, the current item, driver verdicts, persistence and radio prompts.

All state lives on the asyncio loop (API handlers are ``async``; the radio command handler is called on the loop by
the hub). Disk and database work goes to worker threads. At most one run is active; it is saved at most every 2 s
while it changes and at once after a driver action. On start-up an active run is resumed with a ``restart``
timeline event naming the gap. The kit never changes a capability status and never talks to the LLM.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pitwall import __version__
from pitwall.validate import evidence as E
from pitwall.validate import report as Rep
from pitwall.validate import rules as R
from pitwall.validate import voice as V
from pitwall.validate.catalog import BY_ID, CATALOG, Availability, availability, catalog_json, default_items
from pitwall.validate.collector import Collector
from pitwall.validate.model import (
    LIMITS,
    ClientSample,
    ClientState,
    DriverMark,
    ItemState,
    Run,
    ServerInfo,
    TimelineEvent,
    Window,
    dump,
    run_from_dict,
)
from pitwall.validate.store import ValidationStore, dumps, is_run_id, new_run_id

log = logging.getLogger(__name__)

SAVE_EVERY_S = 2.0
PROMPT_GAP_S = 30.0  # at least this long between validation prompts on the radio
PROMPT_TTL_S = 90.0
TIMELINE_API = 50


class KitError(Exception):
    """A request the kit refuses: ``status`` is the HTTP status (404 unknown, 409 state conflict)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _git_commit() -> str | None:
    root = Path(__file__).resolve().parents[3]
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha and all(c in "0123456789abcdef" for c in sha) else None


def _clock(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


class ValidationKit:
    def __init__(self, settings: Any, rt: Any, hub: Any | None, loop: asyncio.AbstractEventLoop) -> None:
        self.settings = settings
        self.rt = rt
        self.hub = hub
        self.loop = loop
        self.store = ValidationStore(settings.data_dir)
        self.run: Run | None = None
        self.collector: Collector | None = None
        self._dirty = False
        self._last_save = 0.0
        self._save_lock: asyncio.Lock | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._n_drivers = self._count_drivers()
        self._last_prompt_mono = -1e9
        self._pending_prompt: tuple[str, str, float] | None = None  # (text, why, monotonic time queued)
        self._prompt_ids = 0
        self._closed = False
        self._finishing = False
        self.boot_tag = secrets.token_hex(2)  # prefixes question record ids (message ids restart with the service)
        if hub is not None and getattr(hub, "command_handler", "missing") is None:
            hub.command_handler = self.voice_command
        rid = self.store.find_active()
        if rid is not None:
            try:
                data = self.store.load_run(rid)
                run = run_from_dict(data)
            except (OSError, ValueError) as e:
                log.warning("validation: active run %s could not be resumed: %s", rid, e)
            else:
                self.run = run
                now = time.time()
                since = run.last_saved_unix or run.started_unix
                self.timeline("restart", f"Service restarted: no evidence between {_clock(since)} and {_clock(now)}")
                self._attach()
                log.info("validation run %s resumed", rid)

    # ------------------------------------------------------------------ plumbing
    def _count_drivers(self) -> int:
        try:
            return len(self.rt.drivers.list_drivers())
        except Exception:
            return 1

    async def refresh_drivers(self) -> None:
        self._n_drivers = await asyncio.to_thread(self._count_drivers)

    def _spawn(self, coro: Any) -> None:
        task = self.loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (exc := task.exception()) is not None:
            log.error("validation task failed: %r", exc, exc_info=exc)

    def run_or_raise(self) -> Run:
        if self.run is None:
            raise KitError(409, "no active run")
        return self.run

    def touch(self) -> None:
        """Something the compact ``Run`` shows changed: bump the version (the page re-renders) and save soon."""
        if self.run is not None:
            self.run.version += 1
            self._dirty = True

    def dirty(self) -> None:
        """Evidence changed (saved soon); the version moves when a verdict, metric or the timeline does."""
        if self.run is not None:
            self._dirty = True

    def timeline(self, kind: str, text: str) -> None:
        run = self.run
        if run is None:
            return
        run.timeline.append(TimelineEvent(time.time(), kind, text))
        if len(run.timeline) > LIMITS["timeline"]:
            del run.timeline[: len(run.timeline) - LIMITS["timeline"]]
        self.touch()

    def availability(self) -> Availability:
        hub = self.hub
        stt_reason = None
        if hub is not None:
            with contextlib.suppress(Exception):
                stt_reason = hub.state().get("stt_reason")
        return Availability(
            hub=hub is not None,
            stt=None if hub is None else getattr(hub.stt, "name", None),
            stt_reason=stt_reason,
            tts=None if hub is None else getattr(hub.tts, "name", None),
            game_block=callable(getattr(self.rt.live, "game_block", None)),
            drivers=self._n_drivers,
        )

    def catalog(self) -> dict[str, Any]:
        return catalog_json(self.availability())

    def _attach(self) -> None:
        if self.collector is None:
            self.collector = Collector(self)
            self.collector.attach()

    async def _detach(self) -> None:
        c, self.collector = self.collector, None
        if c is not None:
            await c.detach()

    # ------------------------------------------------------------------ persistence
    def _lock(self) -> asyncio.Lock:
        if self._save_lock is None:
            self._save_lock = asyncio.Lock()
        return self._save_lock

    async def save_now(self, run: Run | None = None) -> None:
        run = run or self.run
        if run is None:
            return
        async with self._lock():
            run.last_saved_unix = time.time()
            data = dumps(run.json_obj())
            self._dirty = False
            self._last_save = time.monotonic()
            await asyncio.to_thread(self.store.save_run, run.id, data)

    def maybe_save(self, now: float) -> None:
        if self._dirty and time.monotonic() - self._last_save >= SAVE_EVERY_S:
            self._dirty = False
            self._last_save = time.monotonic()
            self._spawn(self.save_now())

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        hub = self.hub
        if hub is not None and getattr(hub, "command_handler", None) == self.voice_command:
            hub.command_handler = None
        await self._detach()
        if self.run is not None:
            await self.save_now()
        for t in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    # ------------------------------------------------------------------ verdicts
    def _tts_info(self) -> tuple[str | None, int | None, float | None]:
        c = self.collector
        name = None if self.hub is None else getattr(self.hub.tts, "name", None)
        return name, (None if c is None else c.tts_restarts), (None if c is None else c.synth_p95_ms)

    def recompute(self, now: float | None = None, run: Run | None = None) -> bool:
        """Every item's automatic verdict and result. True when anything changed (the version is bumped)."""
        run = run or self.run
        if run is None:
            return False
        now = time.time() if now is None else now
        vs = E.views(run)
        avail = self.availability() if run is self.run else None
        tts, restarts, p95 = self._tts_info() if run is self.run else (None, None, None)
        changed = False
        for it in run.items:
            cat = BY_ID.get(it.id)
            if cat is None:
                continue
            ok, reason = (True, None) if avail is None else availability(cat, avail)
            if avail is None and it.auto.verdict == "unavailable":
                ok, reason = False, (it.auto.reasons[0] if it.auto.reasons else None)
            attest: dict[str, bool] = {}
            for m in it.marks:
                attest.update(m.attestations)
            ctx = E.AutoContext(now, it.windows, attest, ok, reason, tts, restarts, p95)
            auto = E.compute_auto(it.id, vs, ctx)
            result = R.item_result(auto, it.marks, cat.per_driver, it.status == "skipped")
            if not auto.same_as(it.auto) or result != it.result:
                old = it.auto.verdict
                it.auto = auto
                it.result = result
                changed = True
                # only the current test is prompted: "worked" / "didn't work" on the radio always mark that one
                current = it.id == run.current_item
                turned = auto.verdict in ("pass", "fail") and old != auto.verdict
                if run is self.run and current and turned and not it.marks:
                    self._verdict_prompt(it.id, auto.verdict)
        if changed and run is self.run:
            self.touch()
        return changed

    # ------------------------------------------------------------------ radio prompts (spec 6.5)
    def _verdict_prompt(self, item_id: str, verdict: str) -> None:
        run = self.run
        if run is None or item_id in run.prompted:
            return
        run.prompted.append(item_id)
        self.prompt(V.verdict_prompt(BY_ID[item_id].short, verdict), "verdict")

    def prompt(self, text: str, why: str) -> None:
        """Queue a validation prompt (newest wins) for the next moment the rate limit allows."""
        run = self.run
        if run is None or not run.radio_prompts or self.hub is None:
            return
        self._pending_prompt = (text, why, time.monotonic())
        self.flush_prompt(time.time())

    def _announce(self, text: str) -> None:
        """A follow-up reply to the driver's own radio command (e.g. the counts once the report is saved): queued at
        once for the next speak window, whatever the prompt setting and the rate limit."""
        hub = self.hub
        if hub is None:
            return
        from pitwall.voice.types import MessageKind, Priority, RadioMessage

        mono = time.monotonic()
        self._prompt_ids += 1
        msg = RadioMessage(
            id=f"v{self._prompt_ids}",
            kind=MessageKind.CONTROL,
            priority=Priority.NORMAL,
            text=text,
            speech=hub.to_speech(text),
            created_mono=mono,
            expires_mono=mono + PROMPT_TTL_S,
            bypass_quiet=True,
            needs_speak_window=True,
            meta={"topic": "validation"},
        )
        try:
            hub.scheduler.enqueue(msg)
        except Exception:
            log.exception("validation reply could not be queued")

    def flush_prompt(self, _now: float) -> None:
        hub = self.hub
        pending = self._pending_prompt
        if pending is None or hub is None:
            return
        mono = time.monotonic()
        if mono - pending[2] > PROMPT_TTL_S:
            self._pending_prompt = None  # no radio came in time: a stale brief is never said
            return
        if not getattr(hub, "clients", None) or mono - self._last_prompt_mono < PROMPT_GAP_S:
            return
        from pitwall.voice.types import MessageKind, Priority, RadioMessage

        text, _why, _queued = pending
        self._pending_prompt = None
        self._last_prompt_mono = mono
        self._prompt_ids += 1
        msg = RadioMessage(  # the radio policy's VALIDATION kind: every intensity, last in line, never the gap
            id=f"v{self._prompt_ids}",
            kind=MessageKind.VALIDATION,
            priority=Priority.LOW,
            text=text,
            speech=hub.to_speech(text),
            created_mono=mono,
            expires_mono=mono + PROMPT_TTL_S,
            bypass_quiet=False,
            needs_speak_window=True,
            meta={"topic": "validation"},
        )
        try:
            hub.scheduler.enqueue(msg)
        except Exception:
            log.exception("validation prompt could not be queued")

    # ------------------------------------------------------------------ run lifecycle
    def _server_info(self) -> ServerInfo:
        hub = self.hub
        return ServerInfo(
            pitwall_version=__version__,
            git_commit=None,
            os=sys.platform,
            voice_enabled=hub is not None,
            llm_enabled=bool(getattr(self.settings, "llm_enabled", False)),
            stt=None if hub is None else getattr(hub.stt, "name", None),
            tts=None if hub is None else getattr(hub.tts, "name", None),
        )

    def start_run(
        self, items: list[str] | None, label: str | None, radio_prompts: bool | None, brief: bool = True
    ) -> Run:
        if self.run is not None or self._finishing:
            raise KitError(409, "a validation run is already active")
        avail = self.availability()
        if items is None:
            chosen = default_items(avail)
        else:
            unknown = [i for i in items if i not in BY_ID]
            if unknown:
                raise KitError(404, f"unknown test: {', '.join(unknown)}")
            off = [i for i in items if not availability(BY_ID[i], avail)[0]]
            if off:
                raise KitError(409, f"not available on this server: {', '.join(off)}")
            wanted = set(items)
            chosen = [it.id for it in CATALOG if it.id in wanted]
        now = time.time()
        run = Run(
            id=new_run_id(now),
            label=label,
            status="active",
            started_unix=now,
            server=self._server_info(),
            selected_items=chosen,
            items=[ItemState(it_id) for it_id in chosen],
            radio_prompts=True if radio_prompts is None else radio_prompts,
        )
        self.run = run
        self._dirty = True
        self.timeline("item", "Validation started")
        if chosen:
            self._set_current(run, chosen[0], now)
        self.recompute(now)
        self._attach()
        self._spawn(self._fill_commit(run))
        if brief and chosen:
            self.prompt(BY_ID[chosen[0]].radio_brief, "brief")
        return run

    async def _fill_commit(self, run: Run) -> None:
        sha = await asyncio.to_thread(_git_commit)
        if sha is not None:
            run.server.git_commit = sha
            if run is self.run:
                self.touch()

    def _active(self, run_id: str) -> Run:
        run = self.run
        if run is None or run.id != run_id:
            if is_run_id(run_id) and self.store.run_dir(run_id).exists():
                raise KitError(409, "this run is not active")
            raise KitError(404, "unknown run")
        return run

    def _item(self, run: Run, item_id: str) -> ItemState:
        it = run.item(item_id)
        if it is None:
            raise KitError(404, f"test {item_id!r} is not part of this run")
        return it

    def _close_window(self, it: ItemState, now: float) -> None:
        if it.windows and it.windows[-1].end_unix is None:
            it.windows[-1].end_unix = now

    def _set_current(self, run: Run, item_id: str | None, now: float) -> None:
        cur = run.item(run.current_item) if run.current_item else None
        if cur is not None and cur.id != item_id:
            self._close_window(cur, now)
            if cur.status == "current":
                cur.status = "done" if cur.marks else "pending"
            self.timeline("item", f"{BY_ID[cur.id].title}: left")
            if self.collector is not None:
                self.collector.start_phase(cur.id, "stop", None)
        run.current_item = item_id
        if item_id is not None:
            it = self._item(run, item_id)
            if it.status != "current":
                it.status = "current"
                it.skip_reason = None
                it.windows.append(Window(now))
                self.timeline("item", f"{BY_ID[it.id].title}: started")
        self.touch()

    def set_current(self, run_id: str, item_id: str, brief: bool = True) -> Run:
        run = self._active(run_id)
        self._item(run, item_id)
        ok, reason = availability(BY_ID[item_id], self.availability())
        if not ok:
            raise KitError(409, reason or "not available")
        self._set_current(run, item_id, time.time())
        if brief:
            self.prompt(BY_ID[item_id].radio_brief, "brief")
        self.recompute()
        return run

    def _next_id(self, run: Run) -> str | None:
        """The next pending test after the current one, in catalogue order (no wrap-around: after the last test the
        driver finishes, or picks an earlier one on the page)."""
        order = run.selected_items
        start = order.index(run.current_item) + 1 if run.current_item in order else 0
        for i in order[start:]:
            it = run.item(i)
            if it is not None and it.status == "pending" and i != run.current_item:
                return i
        return None

    def next_item(self, run_id: str, brief: bool = True) -> Run:
        run = self._active(run_id)
        nxt = self._next_id(run)
        self._set_current(run, nxt, time.time())
        if brief and nxt is not None:
            self.prompt(BY_ID[nxt].radio_brief, "brief")
        self.recompute()
        return run

    def verdict(
        self,
        run_id: str,
        item_id: str,
        verdict: str | None,
        notes: str = "",
        attestations: dict[str, bool] | None = None,
        extra: dict[str, str] | None = None,
        source: str = "screen",
    ) -> Run:
        run = self._active(run_id)
        it = self._item(run, item_id)
        cat = BY_ID[item_id]
        did = self.rt.drivers.active_id
        keys = {a.key for a in cat.attestations}
        att = {k: bool(v) for k, v in (attestations or {}).items() if k in keys}
        if cat.per_driver or verdict is None:
            it.marks = [m for m in it.marks if m.driver_id != did]
        if verdict is not None:
            if verdict not in ("worked", "didnt"):
                raise KitError(422, "verdict must be worked or didnt")
            prev = next((m for m in reversed(it.marks) if m.driver_id == did), None)
            merged = {**(prev.attestations if prev else {}), **att}
            it.marks.append(
                DriverMark(
                    driver_id=did,
                    verdict="worked" if verdict == "worked" else "didnt",
                    notes=notes[:2000],
                    attestations=merged,
                    extra={str(k)[:32]: str(v)[:64] for k, v in (extra or {}).items()},
                    at_unix=time.time(),
                    source="voice" if source == "voice" else "screen",
                )
            )
            if it.status == "pending":
                it.status = "done"
            said = "worked" if verdict == "worked" else "didn't work"
            self.timeline("item", f"{cat.title}: {said} ({source})")
        elif not it.marks and it.status == "done":
            it.status = "pending"
        self.touch()
        self.recompute()
        return run

    def skip(self, run_id: str, item_id: str, reason: str | None) -> Run:
        run = self._active(run_id)
        it = self._item(run, item_id)
        now = time.time()
        was_current = run.current_item == item_id
        if was_current:
            nxt = self._next_id(run)
            self._set_current(run, nxt, now)
        self._close_window(it, now)
        it.status = "skipped"
        it.skip_reason = (reason or "")[:200] or None
        self.timeline("item", f"{BY_ID[item_id].title}: skipped")
        self.touch()
        self.recompute()
        return run

    def input_check(self, run_id: str, item_id: str, phase: str, rotation_deg: float | None) -> Run:
        run = self._active(run_id)
        self._item(run, item_id)
        phases = BY_ID[item_id].input_check
        if phases is None:
            raise KitError(409, "this test has no input check")
        if phase != "stop" and phase not in phases:
            raise KitError(409, f"phase {phase!r} is not part of this test's input check")
        if self.collector is not None:
            self.collector.start_phase(item_id, phase, rotation_deg)
        self.touch()
        return run

    def mark_ptt(self, run_id: str, record_id: str, heard_right: bool | None) -> Run:
        run = self._active(run_id)
        rec = next((p for p in reversed(run.evidence.ptt) if p.id == record_id and record_id), None)
        if rec is None:
            raise KitError(404, "unknown question")
        rec.heard_right = heard_right
        self.touch()
        self.recompute()
        return run

    async def finish(self, run_id: str, notes: str | None, status: str = "finished") -> Run:
        run = self._active(run_id)
        if self._finishing:
            raise KitError(409, "this run is already finishing")
        self._finishing = True
        try:
            return await self._finish(run, notes, status)
        finally:
            self._finishing = False

    async def _finish(self, run: Run, notes: str | None, status: str) -> Run:
        now = time.time()
        collector = self.collector
        if collector is not None:
            await collector.refresh_db()
        self._set_current(run, None, now)
        for it in run.items:
            self._close_window(it, now)
        if notes:
            run.notes = notes[:2000]
        self.recompute(now)
        await self._detach()
        run.status = "finished" if status == "finished" else "aborted"
        run.ended_unix = now
        self.timeline("item", "Validation finished" if status == "finished" else "Validation aborted")
        try:
            report = Rep.build_report(run, now)
            md = Rep.render_markdown(report, run)
            self.run = None  # from here every other request sees no active run (start waits for _finishing)
            await self.save_now(run)
            await asyncio.to_thread(self.store.save_report, run.id, report, md)
        except Exception:
            # the run stays active in memory and on disk, so Finish can be tried again
            log.exception("validation run %s could not be finished", run.id)
            run.status = "active"
            run.ended_unix = None
            self.run = run
            self.timeline("note", "Saving the report failed: the run is still active")
            self._attach()
            with contextlib.suppress(Exception):
                await self.save_now(run)
            raise
        return run

    # ------------------------------------------------------------------ device reports (spec 6.4)
    def client_report(self, body: dict[str, Any]) -> None:
        run = self.run
        if run is None or body.get("run_id") != run.id:
            raise KitError(409, "no active run")
        now = time.time()
        cid = str(body["client_id"])
        state = next((c for c in run.client_states if c.client_id == cid), None)
        if state is None:
            if len(run.client_states) >= LIMITS["clients"]:
                oldest = min(run.client_states, key=lambda c: c.last_unix)
                run.client_states.remove(oldest)
                run.dropped_records += 1
            state = ClientState(client_id=cid, device=str(body["device"]), first_seen_unix=now, last={}, last_unix=now)
            run.client_states.append(state)
            self.timeline("client", f"New device: {body['device']} ({body.get('origin_kind')})")
        seq = int(body.get("seq") or 0)
        prev_seq = state.samples[-1].seq if state.samples else None
        if prev_seq is not None and seq < prev_seq:
            state.reloads += 1
            self.timeline("client", f"{state.device} page reloaded")
        conn = self.rt.live.connection()
        tier = self.collector.tier_now() if self.collector is not None else "unknown"
        wake = body.get("wake") or {}
        radio = body.get("radio")
        fps = body.get("fps_10s")
        endurance = run.current_item == "ipad_endurance"
        sample = ClientSample(
            t_unix=now,
            seq=seq,
            visible=body.get("visibility") == "visible",
            route=str(body.get("route") or ""),
            wake_wanted=bool(wake.get("wanted")),
            wake_state=str(wake.get("state") or "off"),
            telemetry=str(conn.get("status")),
            tier=tier,
            standalone=bool(body.get("standalone")),
            secure_context=bool(body.get("secure_context")),
            radio_phase=None if not isinstance(radio, dict) else str(radio.get("phase")),
            fps_10s=float(fps) if isinstance(fps, int | float) and endurance else None,
            endurance=endurance,
        )
        state.samples.append(sample)
        if len(state.samples) > LIMITS["client_samples"]:
            del state.samples[: len(state.samples) - LIMITS["client_samples"]]
            run.dropped_records += 1
        state.device = str(body["device"])
        state.last = dict(body)
        state.last_unix = now
        state.reports += 1
        self.touch()

    # ------------------------------------------------------------------ API views
    def run_api(self, run: Run, detail: str = "compact", now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        ctx = run.context or {
            "telemetry": "no_data",
            "tier": "unknown",
            "game": None,
            "platform": None,
            "track": None,
            "session_id": None,
            "packet_format": None,
            "game_version": None,
            "driver_id": None,
            "radio_clients": 0,
            "cue_mode": None,
        }
        out = {
            **Rep.run_summary(run),
            "format": run.format,
            "version": run.version,
            "selected_items": list(run.selected_items),
            "radio_prompts": run.radio_prompts,
            "server": dump(run.server),
            "items": [dump(it) for it in run.items],
            "context": ctx,
            "clients": [E.client_summary(c, now) for c in run.client_states],
            "timeline": [dump(e) for e in reversed(run.timeline[-TIMELINE_API:])],
            "notes": run.notes,
            "dropped_records": run.dropped_records,
        }
        if detail == "full":
            out["evidence"] = run.evidence.contract_dict()
        return out

    def load(self, run_id: str) -> Run:
        """The run in memory when active, else from disk (blocking: call in a worker thread)."""
        if not is_run_id(run_id):
            raise KitError(404, "unknown run")
        if self.run is not None and self.run.id == run_id:
            return self.run
        try:
            data = self.store.load_run(run_id)
        except (OSError, ValueError) as e:
            raise KitError(404, f"run unreadable: {e}") from e
        if data is None:
            raise KitError(404, "unknown run")
        try:
            return run_from_dict(data)
        except ValueError as e:
            raise KitError(404, str(e)) from e

    async def get_run(self, run_id: str, detail: str) -> dict[str, Any]:
        if self.run is not None and self.run.id == run_id:
            return self.run_api(self.run, detail)
        run = await asyncio.to_thread(self.load, run_id)
        return self.run_api(run, detail, run.ended_unix or time.time())

    async def report(self, run_id: str, redact: bool = False) -> tuple[dict[str, Any], Run]:
        now = time.time()
        if self.run is not None and self.run.id == run_id:
            self.recompute(now)
            return Rep.build_report(self.run, now, redact), self.run
        run = await asyncio.to_thread(self.load, run_id)
        stored = None if redact else await asyncio.to_thread(self.store.load_report, run_id)
        return (stored or Rep.build_report(run, run.ended_unix or now, redact)), run

    async def report_md(self, run_id: str, redact: bool) -> str:
        if not redact and (self.run is None or self.run.id != run_id) and is_run_id(run_id):
            md = await asyncio.to_thread(self.store.load_report_md, run_id)
            if md is not None:
                return md
        report, run = await self.report(run_id, redact)
        return Rep.render_markdown(report, run)

    # ------------------------------------------------------------------ radio commands (spec 7; loop)
    def voice_command(self, text: str) -> str | None:
        """A validation command's reply, or None for the engineer. With no run active only "start validation" is a
        command: "passed", "it worked" or "next test" said in an ordinary session reach the engineer as usual."""
        cmd = V.parse_command(text)
        if cmd is None:
            return None
        run = self.run
        if cmd == "start":
            if run is not None:
                cur = BY_ID.get(run.current_item or "")
                return V.already_running(None if cur is None else cur.short)
            try:
                run = self.start_run(None, None, None, brief=False)
            except KitError:
                return "Validation could not start. Use Setup, Validation on the iPad."
            self._spawn(self.save_now())
            first = BY_ID.get(run.current_item or "")
            return V.started(None if first is None else first.radio_brief)
        if run is None or self._finishing:
            return None
        if cmd == "next":
            order = run.selected_items
            before = order.index(run.current_item) if run.current_item in order else len(order)
            self.next_item(run.id, brief=False)
            self._spawn(self.save_now())
            nxt = BY_ID.get(run.current_item or "")
            if nxt is not None and order.index(nxt.id) < before:
                return V.back_to(nxt.radio_brief)  # after the last test: an earlier one still to do
            return V.next_test(None if nxt is None else nxt.radio_brief)
        cur_state = run.item(run.current_item) if run.current_item else None
        if cmd in ("worked", "didnt"):
            if cur_state is None:
                return "No test is current. Say next test."
            cat = BY_ID[cur_state.id]
            self.verdict(run.id, cur_state.id, cmd, source="voice")
            self._spawn(self.save_now())
            return V.marked(cat.short, cmd == "worked", self._driver_name() if cat.per_driver else None)
        if cmd == "status":
            if cur_state is None:
                return "No test is current. Say next test, or finish validation."
            idx = run.selected_items.index(cur_state.id) + 1
            cat = BY_ID[cur_state.id]
            return V.status(idx, len(run.selected_items), cat.short, cat.radio_brief)
        # finish: the counts are said once the report is saved (the final recompute can change them)
        self._spawn(self._finish_by_voice(run.id))
        return V.FINISHING

    def _driver_name(self) -> str | None:
        drv = getattr(self.rt.drivers, "active", None)
        name = getattr(drv, "name", None)
        return str(name) if name else None

    async def _finish_by_voice(self, run_id: str) -> None:
        try:
            run = await self.finish(run_id, None)
        except Exception:
            self._announce(V.FINISH_FAILED)
            raise
        counts = {k: 0 for k in ("pass", "fail", "needs_review")}
        for it in run.items:
            if it.result in counts:
                counts[it.result] += 1
        self._announce(V.finished(counts["pass"], counts["fail"], counts["needs_review"]))
