"""Post-lap processing pipeline (runs off the ingest thread).

For each completed lap: persist -> (re)learn the track model -> pick a compatible reference ->
compare by distance -> derive evidence-based observations -> persist -> publish to live state.

Driver scoping: the reference is chosen from the session owner's laps only (their pinned reference, else their
fastest clean lap), so one driver's lap is never another driver's reference; a driver with no clean lap at the
track yet simply gets no comparison until they set one. The owner is re-read from the database for every lap (a
primary-key lookup on this background thread), so re-assigning a session takes effect on its next lap without
any cross-thread invalidation; the per-session coaching history is reset when the owner changes. Track models
are shared by all drivers: they are built from the fastest clean laps at the track whoever drove them.

Live publishing: results reach ``LiveState`` (dashboard, radio, delta bar, cue engine) only while the job's
session is still the live one. A driver change ends a session and starts the next one at once, so the previous
driver's flushed partial lap - or a complete lap still being analysed - would otherwise land in the new driver's
live state and be spoken to them. Persistence never depends on it: every lap is stored and analysed.

Bests (dashboard D2): after every stored lap, and whenever the live session's context changes
(``LiveState.set_bests_requester``, served by ``AnalysisWorker``), the live session's session / driver / household
bests are recomputed (``repo.lap_bests``) on this thread and published with ``LiveState.set_bests``. A
synthetic or replayed live session gets no driver or household bests.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pitwall.analysis.coaching import is_incident, observations_for_comparison
from pitwall.analysis.compare import (
    CornerDelta,
    LapAnalysis,
    analyse_lap,
    check_compatibility,
    compare,
    compat_meta,
    lengths_compatible,
)
from pitwall.analysis.distance import to_distance_domain
from pitwall.analysis.laps import LapFlag, LapTrace
from pitwall.analysis.track import TrackModel, build_track_model
from pitwall.analysis.track_identity import corner_texts, identify, track_model_payload
from pitwall.core.ai_pace import AiPaceJob, AiPaceProcessor
from pitwall.core.live import BestsRequest, LiveState
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

log = logging.getLogger(__name__)

TRACK_MODEL_TARGET_LAPS = 3  # rebuild the model until it is based on this many clean laps, then freeze
HISTORY_LAPS = 5


@dataclass(slots=True)
class LapJob:
    session_id: str
    lap: LapTrace
    context: dict[str, Any]  # game, track_id, track_name, track_length_m, car_id, weather, assists, setup_fp...
    ground_plane: tuple[str, str] = ("pos_x_m", "pos_z_m")


@dataclass(slots=True)
class _SessionCache:
    history: dict[str, list[CornerDelta]] = field(default_factory=dict)
    ref_lap_id: int | None = None
    driver_id: int | None = None


class LapProcessor:
    def __init__(self, db: Database, writer: DbWriter, live: LiveState | None = None) -> None:
        self.db = db
        self.writer = writer
        self.live = live
        self._models: dict[tuple[str, str], TrackModel] = {}
        self._ref_cache: dict[int, LapAnalysis] = {}
        self._sessions: dict[str, _SessionCache] = {}
        self.processed = 0

    # ------------------------------------------------------------------ public
    def process(self, job: LapJob) -> dict[str, Any]:
        t0 = time.perf_counter()
        lap, ctx = job.lap, job.context
        lap.meta.update({k: ctx.get(k) for k in ("game", "track_id", "car_id", "setup_fp", "track_temp_c")})
        lap.meta["weather"] = ctx.get("weather")
        lap_id = self.writer.call(lambda c: repo.insert_lap(c, job.session_id, lap, ctx.get("setup_fp")))
        lap.meta["lap_id"] = lap_id
        summary = _lap_summary(lap, lap_id)
        result: dict[str, Any] = {"lap_id": lap_id, "summary": summary, "observations": [], "comparison": None}

        sid = job.session_id
        game, track_id, length = ctx.get("game"), ctx.get("track_id"), ctx.get("track_length_m")
        if game and track_id:
            self._publish_bests(sid, str(game), str(track_id), ctx.get("car_id"), length)
        if not (game and track_id and length) or LapFlag.INCOMPLETE in lap.flags:
            self._publish(sid, summary, [], None)
            return result

        model = self._track_model(sid, game, track_id, ctx, job.ground_plane, lap)
        if model is None or not model.corners:
            self._publish(sid, summary, [], None)
            return result

        driver_id, ref_id = self._choose_reference(
            job.session_id, game, track_id, ctx.get("car_id"), exclude=lap_id, track_length_m=float(length)
        )
        sc = self._sessions.setdefault(job.session_id, _SessionCache(driver_id=driver_id))
        if driver_id != sc.driver_id:
            sc.history.clear()  # the session changed hands: the previous owner's habits are not this driver's
            sc.driver_id = driver_id
        ref_changed = ref_id != sc.ref_lap_id
        if ref_changed:
            sc.history.clear()  # deltas against a different reference are not comparable
            sc.ref_lap_id = ref_id
        if ref_id is None:
            if ref_changed and self.live is not None and self._is_live(sid):
                self.live.set_reference(None, None)  # never leave another driver's lap as the live delta reference
            self._publish(sid, summary, [], None)
            return result

        ref = self._reference_analysis(ref_id, model, sid, ref_changed)
        if ref is None:
            self._publish(sid, summary, [], None)
            return result
        cur = analyse_lap(lap, model)
        ref_ctx = {**ref.lap.meta}
        compat = check_compatibility(compat_meta(ref_ctx), compat_meta({**lap.meta, **ctx}), ref.lap.clean)
        comp = compare(ref, cur, compat)
        texts = corner_texts(model)  # official numbers/names (track sheets); join keys stay the learned names
        obs = observations_for_comparison(comp, history=sc.history, resolution_m=_resolution_m(lap), corner_text=texts)
        for cd in comp.corners:
            if is_incident(cd):
                continue  # a spin or contact says nothing about the driver's habits at this corner
            h = sc.history.setdefault(cd.corner, [])
            h.append(cd)
            del h[:-HISTORY_LAPS]
        if obs:
            self.writer.submit(
                lambda c: repo.insert_observations(c, job.session_id, lap_id, ref_id, obs, model.version)
            )
        comp_dict = comp.to_dict()
        comp_dict["ref_lap_id"] = ref_id
        comp_dict["cmp_lap_id"] = lap_id
        comp_dict["corner_text"] = {k: {"short": t.short, "long": t.long, "voice": t.voice} for k, t in texts.items()}
        obs_dicts = [o.to_dict() for o in obs]
        result.update(observations=obs_dicts, comparison=comp_dict)
        self._publish(sid, summary, obs_dicts, comp_dict)
        self.processed += 1
        log.info(
            "lap %s processed in %.0f ms: %d observations vs ref lap id %s",
            lap.lap_number,
            (time.perf_counter() - t0) * 1000,
            len(obs),
            ref_id,
        )
        return result

    def refresh_bests(self, req: BestsRequest) -> None:
        """The live session's context changed (``LiveState.set_bests_requester``): recompute its bests."""
        self._publish_bests(req.session_id, req.game, req.track_id, req.car_id, req.track_length_m)

    # ------------------------------------------------------------------ internals
    def _publish_bests(
        self, session_id: str, game: str, track_id: str, car_id: str | None, track_length_m: object
    ) -> None:
        """D2: recompute and publish the live session's bests (only while it is the live session)."""
        live = self.live
        if live is None or not self._is_live(session_id):
            return
        length = float(track_length_m) if isinstance(track_length_m, int | float) and track_length_m > 0 else None
        records = not (live.synthetic or repo.is_replay_source(live.source or ""))
        try:
            with self.db.read() as c:
                owner = repo.session_driver_id(c, session_id)
                bests = repo.lap_bests(c, session_id, game, track_id, car_id, owner, length, records=records)
        except Exception:
            log.exception("bests for session %s failed", session_id)
            return
        live.set_bests(session_id, bests)

    def _is_live(self, session_id: str) -> bool:
        """Whether ``session_id`` is the session live state shows now (checked right before each publish)."""
        return self.live is not None and self.live.session_id == session_id

    def _publish(
        self, session_id: str, summary: dict[str, Any], obs: list[dict[str, Any]], comp: dict[str, Any] | None
    ) -> None:
        if self.live is not None and self._is_live(session_id):
            self.live.on_lap_result(summary, obs, comp)

    def _track_model(
        self, session_id: str, game: str, track_id: str, ctx: dict[str, Any], plane: tuple[str, str], lap: LapTrace
    ) -> TrackModel | None:
        key = (game, track_id)
        length = float(ctx["track_length_m"])
        model = self._models.get(key)
        if model is None:
            with self.db.read() as c:
                model = repo.load_track_model(c, game, track_id)
        # one track id, two lengths: another layout (AC consoles send no layout name). The model is rebuilt from
        # laps of this length only - never from a mix - and the other layout's model is not used meanwhile.
        other_layout = model is not None and not lengths_compatible(model.length_m, length)
        needs = model is None or other_layout or (model.n_laps < TRACK_MODEL_TARGET_LAPS and lap.clean)
        if needs:
            with self.db.read() as c:
                rows = repo.clean_laps_for(c, game, track_id, None, limit=5, track_length_m=length)
                traces = [repo.load_lap_trace(c, r["id"]) for r in rows]
            clean = [t for t in traces if t is not None]
            if clean:
                dts = [to_distance_domain(t, length) for t in clean]
                model = build_track_model(
                    game,
                    track_id,
                    ctx.get("track_name"),
                    length,
                    dts,
                    ground_plane=plane,
                    source_lap_ids=[int(r["id"]) for r in rows],
                )
                new_model = model
                self.writer.call(lambda c: repo.save_track_model(c, new_model))
                self._ref_cache.clear()  # corner definitions changed
                log.info(
                    "track model %s/%s v%d from %d laps: %d corners",
                    game,
                    track_id,
                    model.version,
                    len(dts),
                    len(model.corners),
                )
            elif other_layout:
                assert model is not None
                log.info(
                    "track model %s/%s is for a %.0f m layout, this session's is %.0f m: none until a clean lap",
                    game,
                    track_id,
                    model.length_m,
                    length,
                )
                self._models.pop(key, None)
                return None
        if model is not None:
            if all(c.identity_tier is None for c in model.corners):  # stored models are learned-only
                model, mapping = identify(model)
                if mapping is not None:
                    log.info("corner identity %s/%s: %s", game, track_id, mapping.summary())
            self._models[key] = model
            if self.live is not None and self._is_live(session_id):
                self.live.set_track_model(track_model_payload(model))
        return model

    def _choose_reference(
        self,
        session_id: str,
        game: str,
        track_id: str,
        car_id: str | None,
        exclude: int,
        track_length_m: float | None = None,
    ) -> tuple[int | None, int | None]:
        """(session owner, reference lap id). An unowned session (a replay, or one recorded before profiles or by a
        tool without a driver) keeps the pre-profile behaviour: references from all laps at the track. The fastest
        clean lap is taken from sessions of a compatible track length only (another layout under the same id is
        never a reference); a pinned reference is kept, and ``check_compatibility`` blocks it if it is not."""
        with self.db.read() as c:
            driver_id = repo.session_driver_id(c, session_id)
            pinned = repo.pinned_reference(c, game, track_id, car_id, driver_id=driver_id)
            if pinned is not None and pinned != exclude:
                return driver_id, pinned
            for r in repo.clean_laps_for(
                c, game, track_id, car_id, limit=5, driver_id=driver_id, track_length_m=track_length_m
            ):
                if r["id"] != exclude:
                    return driver_id, int(r["id"])
        return driver_id, None

    def _reference_analysis(
        self, ref_id: int, model: TrackModel, session_id: str, ref_changed: bool = False
    ) -> LapAnalysis | None:
        """Analysis of the reference lap (cached per lap id). The live reference (delta bar, map trace) is
        published on a cache miss (e.g. re-analysed against a rebuilt track model) and whenever the session's
        reference changed, even to a cached lap - in both cases only while ``session_id`` is the live session."""
        cached = self._ref_cache.get(ref_id)
        if cached is not None:
            if ref_changed:
                self._publish_reference(session_id, ref_id, cached)
            return cached
        with self.db.read() as c:
            trace = repo.load_lap_trace(c, ref_id)
            lap_row = repo.get_lap(c, ref_id, with_trace=False)
            sess = repo.get_session(c, lap_row["session_id"]) if lap_row else None
        if trace is None or sess is None:
            return None
        trace.meta.update(
            {
                "game": sess["game"],
                "track_id": sess["track_id"],
                "track_length_m": sess.get("track_length_m"),
                "car_id": sess["car_id"],
                "weather": (sess.get("weather") or {}).get("condition"),
                "track_temp_c": (sess.get("weather") or {}).get("track_temp_c"),
                "assists": sess.get("assists"),
            }
        )
        an = analyse_lap(trace, model)
        self._ref_cache[ref_id] = an
        self._publish_reference(session_id, ref_id, an)
        return an

    def _publish_reference(self, session_id: str, ref_id: int, an: LapAnalysis) -> None:
        if self.live is None or not self._is_live(session_id):
            return
        self.live.set_reference(
            {
                "lap_id": ref_id,
                "lap_number": an.lap.lap_number,
                "lap_time_ms": an.lap.lap_time_ms,
                "session_id": an.lap.meta.get("session_id"),
            },
            an.dtrace,
        )


def _resolution_m(lap: LapTrace) -> float:
    d = lap.channels["distance_m"]
    if len(d) < 3:
        return 2.0
    import numpy as np

    steps = np.diff(d)
    steps = steps[np.isfinite(steps) & (steps > 0)]
    return float(np.percentile(steps, 90)) if len(steps) else 2.0


def _lap_summary(lap: LapTrace, lap_id: int) -> dict[str, Any]:
    return {
        "lap_id": lap_id,
        "lap_number": lap.lap_number,
        "lap_time_ms": lap.lap_time_ms,
        "sector_times_ms": lap.sector_times_ms,
        "valid": lap.valid,
        "clean": lap.clean,
        "flags": sorted(lap.flags),
        "tyre_compound": lap.meta.get("tyre_compound"),
        "fuel_used_kg": (
            round(lap.meta["fuel_start_kg"] - lap.meta["fuel_end_kg"], 3)
            if lap.meta.get("fuel_start_kg") is not None and lap.meta.get("fuel_end_kg") is not None
            else None
        ),
    }


class AnalysisWorker:
    """Runs ``LapProcessor`` on a background thread with a bounded queue (laps are never dropped).

    The same FIFO queue carries the pace vs AI jobs (``AiPaceJob``, ``core.ai_pace``): a lap's ``insert_lap`` runs
    before the AI pace job submitted right after it, so the summary always sees that lap. An AI pace job is never
    worth blocking ingest for: on a full queue it is dropped (``ai_dropped``) and the next lap or the session's end
    supersedes it.
    """

    def __init__(self, processor: LapProcessor) -> None:
        self.processor = processor
        self.ai_pace = AiPaceProcessor(processor.db, processor.writer, processor.live)
        self._q: queue.Queue[LapJob | BestsRequest | AiPaceJob | None] = queue.Queue(maxsize=1000)
        self._thread = threading.Thread(target=self._run, name="lap-analysis", daemon=True)
        self.errors = 0
        self.ai_dropped = 0
        self._thread.start()
        if processor.live is not None:
            processor.live.set_bests_requester(self.request_bests)

    def submit(self, job: LapJob) -> None:
        self._q.put(job)

    def submit_ai_pace(self, job: AiPaceJob) -> None:
        """Called on the ingest thread: queue an AI pace summary, never blocking (see the class docstring)."""
        try:
            self._q.put_nowait(job)
        except queue.Full:
            self.ai_dropped += 1
            log.warning("analysis queue full: AI pace job for %s dropped", job.session_id)

    def request_bests(self, req: BestsRequest) -> None:
        """Called on the ingest thread: queue a bests refresh, never blocking (a full queue drops it; the next
        lap recomputes the bests anyway)."""
        try:
            self._q.put_nowait(req)
        except queue.Full:
            log.warning("analysis queue full: bests refresh for %s dropped", req.session_id)

    def _run(self) -> None:
        while True:
            job = self._q.get()
            try:
                if job is None:
                    return
                if isinstance(job, BestsRequest):
                    self.processor.refresh_bests(job)
                elif isinstance(job, AiPaceJob):
                    self.ai_pace.process(job)
                else:
                    self.processor.process(job)
            except Exception:
                self.errors += 1
                log.exception("lap processing failed")
            finally:
                self._q.task_done()

    def join(self) -> None:
        self._q.join()

    def close(self) -> None:
        live = self.processor.live
        if live is not None:
            live.set_bests_requester(None)
        self._q.put(None)
        self._thread.join(10)
