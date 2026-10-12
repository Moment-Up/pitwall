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

Car class families (``pitwall.carclass``): track models are kept per family (``f1`` / ``f2`` / ``other``) and cached
per (game, track, family). A session's family uses its own model; until it has one, another family's model stands in
(``repo.load_track_model``: *borrowed*, shown as such) and is replaced by a model of the session's family as soon as
a clean lap of that family exists. One-off data repairs (``run_repairs``: the F1 25 one-shot laps) run on this thread
at start, before any lap.

Reference choice and practice drills (coachref, ``core/coachref.py``): with a ``CoachRef`` attached (the runtime
attaches one; tests and tools usually do not), the reference comes from the driver's chosen reference (their best,
the family record, another driver's best or a saved lap; compatible laps only) instead of the own-lap rule above,
which stays the default and the fallback. Against another driver's lap the observations are worded with that
driver's name (``coach.reference_wording``) and the comparison carries ``brake_clamp_m``: the driver's own braking
point per corner, so braking calls never go later than the driver has braked there (``coach.cues``). After every
stored lap the service evaluates an active drill (``CoachRef.after_lap``); while one runs, only the drill corner's
observations are published live (all are stored) and the lap's coaching is the drill's point. ``AnalysisWorker
.submit_task`` runs the service's own changes on this thread, so drill and reference state never needs a lock.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from pitwall import carclass
from pitwall.analysis.coaching import is_incident, observations_for_comparison
from pitwall.analysis.compare import (
    CornerDelta,
    CornerMetrics,
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
from pitwall.coach.reference_wording import reword_observations
from pitwall.core.ai_pace import AiPaceJob, AiPaceProcessor
from pitwall.core.live import BestsRequest, LiveState
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter, dumps

if TYPE_CHECKING:
    from pitwall.core.coachref import CoachRef, ResolvedReference

log = logging.getLogger(__name__)
T = TypeVar("T")

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
    # --- coachref ---
    last_ctx: dict[str, Any] | None = None  # the last lap's context (lap meta + session context)
    ref_desc: ResolvedReference | None = None  # how the current reference was chosen (None without coachref)
    clamp: dict[str, float] | None = None  # the braking clamp of the last comparison (another driver's lap)
    recent: dict[str, list[CornerMetrics]] = field(default_factory=dict)  # last laps per corner, no incidents
    # --- coachref ---


# --- coachref --- laps kept out of the drill baselines (coach.drills.NON_ATTEMPT_FLAGS: the same laps are no
# drill attempts), as are safety-car laps
_NOT_RECENT = frozenset(
    {
        LapFlag.INCOMPLETE,
        LapFlag.PIT_IN,
        LapFlag.PIT_OUT,
        LapFlag.FLASHBACK,
        LapFlag.STANDING_START,
        LapFlag.RACE_START,
        LapFlag.DISTANCE_JUMP,
        LapFlag.STALE_DATA,
    }
)


@dataclass(slots=True)
class CoachrefContext:
    """What the coachref service's tasks need about a session (``LapProcessor.coachref_context``): the context of
    its last lap (else of the live session), the shared track model, the current reference and its analysis, how
    it was chosen, the braking clamp, the driver's own reference analysis and the recent corner metrics."""

    session_id: str
    ctx: dict[str, Any] | None
    model: TrackModel | None
    ref: LapAnalysis | None
    desc: ResolvedReference | None
    clamp: dict[str, float] | None
    own: LapAnalysis | None
    recent: dict[str, list[CornerMetrics]]


# --- coachref ---


class LapProcessor:
    def __init__(
        self, db: Database, writer: DbWriter, live: LiveState | None = None, coachref: CoachRef | None = None
    ) -> None:
        self.db = db
        self.writer = writer
        self.live = live
        self.coachref = coachref  # --- coachref --- reference choice + drills (None: the own-lap rule only)
        self._models: dict[tuple[str, str, str | None], TrackModel] = {}  # (game, track, car class family)
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
            self._publish(sid, summary, [], None, self._after_lap(job, lap_id, None, None, None))
            return result

        model = self._track_model(sid, game, track_id, ctx, job.ground_plane, lap)
        if model is None or not model.corners:
            self._publish(sid, summary, [], None, self._after_lap(job, lap_id, None, None, None))
            return result

        driver_id, ref_id, desc = self._choose_reference(
            job.session_id, game, track_id, ctx.get("car_id"), exclude=lap_id, track_length_m=float(length), ctx=ctx
        )
        sc = self._sessions.setdefault(job.session_id, _SessionCache(driver_id=driver_id))
        if driver_id != sc.driver_id:
            sc.history.clear()  # the session changed hands: the previous owner's habits are not this driver's
            sc.recent.clear()  # --- coachref ---
            sc.driver_id = driver_id
        sc.last_ctx = {**lap.meta, **ctx}  # --- coachref ---
        ref_changed = ref_id != sc.ref_lap_id
        if ref_changed:
            sc.history.clear()  # deltas against a different reference are not comparable
            sc.ref_lap_id = ref_id
        # --- coachref --- a new descriptor for the same lap (another kind or label, frozen for a drill) is
        # republished too, without clearing the history (the deltas are still against the same lap)
        desc_changed = desc is not None and (sc.ref_desc is None or sc.ref_desc.to_dict() != desc.to_dict())
        sc.ref_desc = desc
        # --- coachref ---
        if ref_id is None:
            if ref_changed and self.live is not None and self._is_live(sid):
                self.live.set_reference(None, None)  # never leave another driver's lap as the live delta reference
            self._publish(sid, summary, [], None, self._after_lap(job, lap_id, model, None, None))
            return result

        ref = self._reference_analysis(ref_id, model, sid, ref_changed or desc_changed, desc)
        if ref is None:
            self._publish(sid, summary, [], None, self._after_lap(job, lap_id, model, None, None))
            return result
        cur = analyse_lap(lap, model)
        ref_ctx = {**ref.lap.meta}
        compat = check_compatibility(compat_meta(ref_ctx), compat_meta({**lap.meta, **ctx}), ref.lap.clean)
        comp = compare(ref, cur, compat)
        texts = corner_texts(model)  # official numbers/names (track sheets); join keys stay the learned names
        obs = observations_for_comparison(comp, history=sc.history, resolution_m=_resolution_m(lap), corner_text=texts)
        # --- coachref --- another driver's lap: their name in the texts, and their braking points clamped
        clamp: dict[str, float] | None = None
        if desc is not None and not desc.own:
            obs = reword_observations(obs, desc.ref_name, texts)
            clamp = self._brake_clamp(desc, driver_id, ctx, lap_id, model)
        sc.clamp = clamp
        under_sc = self._under_safety_car(sid)
        # --- coachref ---
        for cd in comp.corners:
            if is_incident(cd):
                continue  # a spin or contact says nothing about the driver's habits at this corner
            h = sc.history.setdefault(cd.corner, [])
            h.append(cd)
            del h[:-HISTORY_LAPS]
            if not (lap.flags & _NOT_RECENT) and not under_sc:  # --- coachref --- drill baselines: recent laps
                r = sc.recent.setdefault(cd.corner, [])
                r.append(cd.cmp)
                del r[:-HISTORY_LAPS]
        if obs:
            self.writer.submit(
                lambda c: repo.insert_observations(c, job.session_id, lap_id, ref_id, obs, model.version)
            )
        comp_dict = comp.to_dict()
        comp_dict["ref_lap_id"] = ref_id
        comp_dict["cmp_lap_id"] = lap_id
        comp_dict["corner_text"] = {k: {"short": t.short, "long": t.long, "voice": t.voice} for k, t in texts.items()}
        # --- coachref ---
        if desc is not None:
            comp_dict["reference"] = desc.to_dict()
        if clamp is not None:
            comp_dict["brake_clamp_m"] = clamp
        # --- coachref ---
        obs_dicts = [o.to_dict() for o in obs]
        result.update(observations=obs_dicts, comparison=comp_dict)
        drill = self._after_lap(job, lap_id, model, cur, comp)  # --- coachref ---
        live_obs = obs_dicts if drill is None else [o for o in obs_dicts if o.get("corner") == drill.get("corner")]
        self._publish(sid, summary, live_obs, comp_dict, drill)
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
        if self.coachref is not None:  # --- coachref --- the live session / seat changed: republish the choice
            try:
                self.coachref.on_context(req.session_id)
            except Exception:
                log.exception("coachref context refresh failed")

    # --- coachref ---
    def has_lap(self, session_id: str) -> bool:
        """A lap of ``session_id`` went through the pipeline (it then owns the session's reference)."""
        sc = self._sessions.get(session_id)
        return sc is not None and sc.last_ctx is not None

    def refresh_reference(self, session_id: str, *, load_model: bool = False) -> None:
        """Re-resolve ``session_id``'s reference now (a choice changed while the car was stopped, or the session's
        context is complete before its first lap): when the reference lap or its descriptor changed, the history is
        cleared and the new reference published. Without a lap of this session yet, the live session's context is
        used. ``load_model``: use the stored track model when none is in memory (a layout of another length never).
        Analysis thread only."""
        sc = self._sessions.get(session_id)
        ctx = dict(sc.last_ctx) if sc is not None and sc.last_ctx else self._live_ctx(session_id)
        if ctx is None:
            return
        game, track_id, length = ctx.get("game"), ctx.get("track_id"), ctx.get("track_length_m")
        if not (game and track_id and isinstance(length, int | float) and length > 0):
            return
        key = (str(game), str(track_id), ctx_family(ctx))
        model = self._models.get(key)
        if model is None and load_model:
            with self.db.read() as c:
                model = repo.load_track_model(c, key[0], key[1], key[2])
            if model is not None and not lengths_compatible(model.length_m, float(length)):
                model = None
            if model is not None and model.corners:
                if all(c.identity_tier is None for c in model.corners):  # stored models are learned-only
                    model, _ = identify(model)
                self._models[key] = model  # as LapProcessor._track_model would cache it
        if model is None or not model.corners:
            return
        driver_id, ref_id, desc = self._choose_reference(
            session_id, str(game), str(track_id), ctx.get("car_id"), None, float(length), ctx=ctx
        )
        if sc is None:
            sc = self._sessions.setdefault(session_id, _SessionCache(driver_id=driver_id))
        changed = ref_id != sc.ref_lap_id
        same_desc = (sc.ref_desc is not None and desc is not None and sc.ref_desc.to_dict() == desc.to_dict()) or (
            sc.ref_desc is None and desc is None
        )
        if changed:
            sc.history.clear()
            sc.ref_lap_id = ref_id
        sc.ref_desc = desc
        if not changed and same_desc:
            return
        if ref_id is None:
            if self.live is not None and self._is_live(session_id):
                self.live.set_reference(None, None)
            return
        self._reference_analysis(ref_id, model, session_id, True, desc)

    def coachref_context(self, session_id: str) -> CoachrefContext:
        """The session's coaching context for the coachref service (drill options and targets). Analysis thread."""
        sc = self._sessions.get(session_id)
        ctx = dict(sc.last_ctx) if sc is not None and sc.last_ctx else self._live_ctx(session_id)
        empty = CoachrefContext(session_id, ctx, None, None, None, None, None, {})
        if ctx is None:
            return empty
        game, track_id, length = ctx.get("game"), ctx.get("track_id"), ctx.get("track_length_m")
        if not (game and track_id):
            return empty
        key = (str(game), str(track_id), ctx_family(ctx))
        model = self._models.get(key)
        if model is None:
            with self.db.read() as c:
                model = repo.load_track_model(c, key[0], key[1], key[2])
            if model is not None and all(c.identity_tier is None for c in model.corners):
                model, _ = identify(model)
        if model is None or not model.corners:
            return CoachrefContext(session_id, ctx, model, None, None, None, None, {})
        len_f = float(length) if isinstance(length, int | float) and length > 0 else None
        desc = sc.ref_desc if sc is not None else None
        ref_id = sc.ref_lap_id if sc is not None else None
        driver_id = sc.driver_id if sc is not None else None
        if desc is None and self.coachref is not None:  # no lap of this session yet: resolve as the next lap will
            driver_id, ref_id, desc = self._choose_reference(
                session_id, key[0], key[1], ctx.get("car_id"), None, len_f, ctx=ctx, record=False
            )
        ref = self._analysis_for(ref_id, model) if ref_id is not None else None
        clamp: dict[str, float] | None = None
        own = ref
        if desc is not None and not desc.own and self.coachref is not None:
            with self.db.read() as c:
                own_id = self.coachref.own_reference(c, key[0], key[1], ctx.get("car_id"), driver_id, None, len_f)
            own = self._analysis_for(own_id, model) if own_id is not None else None
            # what the next lap's clamp will be: the last lap is now one of the driver's own laps too
            clamp = self._brake_clamp(desc, driver_id, ctx, None, model)
        recent = {k: list(v) for k, v in sc.recent.items()} if sc is not None else {}
        return CoachrefContext(session_id, ctx, model, ref, desc, clamp, own, recent)

    def _under_safety_car(self, session_id: str) -> bool:
        """A safety car (or VSC, formation lap) is out in the live session ``session_id`` now (the lap just ended)."""
        live = self.live
        info = live.session if live is not None and live.session_id == session_id else None
        status = info.safety_car_status if info is not None else None
        return status is not None and status != "none"

    def _live_ctx(self, session_id: str) -> dict[str, Any] | None:
        """A lap context built from the live session (no lap of ``session_id`` processed yet)."""
        live = self.live
        if live is None or live.session_id != session_id or live.session is None:
            return None
        from pitwall.core.coachref import ctx_from_session_info

        return ctx_from_session_info(live.session)

    def _brake_clamp(
        self,
        desc: ResolvedReference,
        driver_id: int | None,
        ctx: dict[str, Any],
        exclude: int | None,
        model: TrackModel,
    ) -> dict[str, float]:
        """The braking clamp against another driver's lap: the driver's own braking point per corner (their own
        reference by the own-lap rule, excluding the lap just driven); empty when they have no lap of their own.
        Frozen for a drill (``desc.clamp``)."""
        if desc.clamp is not None:
            return dict(desc.clamp)
        if self.coachref is None or driver_id is None:
            return {}
        length = ctx.get("track_length_m")
        len_f = float(length) if isinstance(length, int | float) and length > 0 else None
        with self.db.read() as c:
            own_id = self.coachref.own_reference(
                c, str(ctx.get("game")), str(ctx.get("track_id")), ctx.get("car_id"), driver_id, exclude, len_f
            )
        own = self._analysis_for(own_id, model) if own_id is not None else None
        if own is None:
            return {}
        return {k: float(m.brake_start_m) for k, m in own.corners.items() if m.brake_start_m is not None}

    def _after_lap(
        self, job: LapJob, lap_id: int, model: TrackModel | None, cur: LapAnalysis | None, comp: Any
    ) -> dict[str, Any] | None:
        """The coachref drill hook (``CoachRef.after_lap``); never raises into the lap pipeline."""
        if self.coachref is None:
            return None
        try:
            return self.coachref.after_lap(job, lap_id, model, cur, comp)
        except Exception:
            log.exception("drill evaluation failed")
            return None

    # --- coachref ---

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
        self,
        session_id: str,
        summary: dict[str, Any],
        obs: list[dict[str, Any]],
        comp: dict[str, Any] | None,
        drill: dict[str, Any] | None = None,  # --- coachref --- an active drill (CoachRef.after_lap)
    ) -> None:
        if self.live is not None and self._is_live(session_id):
            if drill is None:
                self.live.on_lap_result(summary, obs, comp)
            else:
                self.live.on_lap_result(summary, obs, comp, drill=drill)

    def _build_model(
        self,
        game: str,
        track_id: str,
        track_name: str | None,
        length: float,
        plane: tuple[str, str],
        family: str | None,
    ) -> TrackModel | None:
        """A new model version from the fastest clean laps of this length (and car class family), saved; None when
        there is no such lap. Shared by the live path and the one-off repair (``run_repairs``)."""
        with self.db.read() as c:
            rows = repo.clean_laps_for(c, game, track_id, None, limit=5, track_length_m=length, family=family)
            traces = [repo.load_lap_trace(c, r["id"]) for r in rows]
        used = [(int(r["id"]), t) for r, t in zip(rows, traces, strict=True) if t is not None]
        if not used:
            return None
        dts = [to_distance_domain(t, length) for _, t in used]
        model = build_track_model(
            game,
            track_id,
            track_name,
            length,
            dts,
            ground_plane=plane,
            source_lap_ids=[i for i, _ in used],
            car_family=family,
        )
        self.writer.call(lambda c: repo.save_track_model(c, model))
        self._ref_cache.clear()  # corner definitions changed
        log.info(
            "track model %s/%s v%d (%s) from %d laps: %d corners",
            game,
            track_id,
            model.version,
            family or "any car",
            len(dts),
            len(model.corners),
        )
        return model

    def _track_model(
        self, session_id: str, game: str, track_id: str, ctx: dict[str, Any], plane: tuple[str, str], lap: LapTrace
    ) -> TrackModel | None:
        family = ctx_family(ctx)
        key = (game, track_id, family)
        length = float(ctx["track_length_m"])
        model = self._models.get(key)
        if model is None:
            with self.db.read() as c:
                model = repo.load_track_model(c, game, track_id, family)
        # one track id, two lengths: another layout (AC consoles send no layout name). The model is rebuilt from
        # laps of this length only - never from a mix - and the other layout's model is not used meanwhile.
        other_layout = model is not None and not lengths_compatible(model.length_m, length)
        # another car class family's model (or a legacy one of unknown family) stands in until a clean lap of this
        # family exists; this lap being clean is that lap
        stand_in = (
            model is not None
            and family is not None
            and (model.car_family is None or model.car_family != family)
            and lap.clean
        )
        needs = model is None or other_layout or stand_in or (model.n_laps < TRACK_MODEL_TARGET_LAPS and lap.clean)
        if needs:
            built = self._build_model(game, track_id, ctx.get("track_name"), length, plane, family)
            if built is not None:
                model = built
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
                self.live.set_track_model(track_model_payload(model, family))
        return model

    # ------------------------------------------------------------------ one-off repairs (start of the service)
    def run_repairs(self) -> dict[str, Any] | None:
        """The F2 repair (``repo.repair_f2_v1``), once: delete the fake one-shot laps, tag every stored track model with
        its car class family, then rebuild a model of each family with clean laps at every track whose models were
        superseded (through ``_build_model``, the live code), as a new version. Guarded by the meta record
        (``repo.REPAIR_F2_V1_KEY``, status ``done``); an interrupted run resumes. Analysis thread only (the runtime
        submits it first); returns the record, None when it ran before."""
        with self.db.read() as c:
            rec = repo.repair_record(c)
        if rec is not None and rec.get("status") == "done":
            return None
        summary = self.writer.call(repo.repair_f2_v1)
        with self.db.read() as c:
            record = repo.repair_record(c) or {}
        rebuilt: list[dict[str, Any]] = []
        wanted: dict[tuple[str, str], set[str]] = {}  # (game, track) -> the families its superseded models were of
        for sup in record.get("superseded") or []:  # this run's and an interrupted earlier run's
            fams_of = {f for f in sup.get("families") or () if isinstance(f, str)}
            wanted.setdefault((str(sup["game"]), str(sup["track_id"])), set()).update(fams_of)
        for (game, track_id), families in sorted(wanted.items()):
            with self.db.read() as c:
                have = repo.track_model_families(c, game, track_id)
                fams = repo.track_clean_lap_families(c, game, track_id)
                old = repo.newest_track_model(c, game, track_id)
            plane = old.ground_plane if old is not None else ("pos_x_m", "pos_z_m")
            for f in fams:
                fam, length = f["fam"], f["track_length_m"]
                if fam not in families or fam in have or not isinstance(length, int | float) or length <= 0:
                    continue
                name = f["track_name"] if f["track_name"] else (old.track_name if old is not None else None)
                model = self._build_model(game, track_id, name, float(length), plane, fam)
                if model is not None:
                    rebuilt.append({"game": game, "track_id": track_id, "family": fam, "version": model.version})
        self._models.clear()
        with self.db.read() as c:
            record = repo.repair_record(c) or {}
        record.update(
            status="done",
            done_unix=round(time.time(), 3),
            tagged=summary["tagged"],
            rebuilt=[*(record.get("rebuilt") or []), *rebuilt],
        )
        self.writer.call(lambda c: repo.set_meta(c, repo.REPAIR_F2_V1_KEY, dumps(record)))
        if summary["deleted"] or summary["superseded"] or rebuilt:
            log.info(
                "repair %s: %d fake one-shot lap(s) deleted, %d track model(s) superseded, %d rebuilt",
                repo.REPAIR_F2_V1_KEY,
                len(summary["deleted"]),
                len(summary["superseded"]),
                len(rebuilt),
            )
        return record

    def _choose_reference(
        self,
        session_id: str,
        game: str,
        track_id: str,
        car_id: str | None,
        exclude: int | None,
        track_length_m: float | None = None,
        ctx: dict[str, Any] | None = None,  # --- coachref --- the lap's context (the chosen reference's filter)
        record: bool = True,  # --- coachref --- False: look only (nothing published, a pending choice stays)
    ) -> tuple[int | None, int | None, ResolvedReference | None]:
        """(session owner, reference lap id, how it was chosen). An unowned session (a replay, or one recorded before
        profiles or by a tool without a driver) keeps the pre-profile behaviour: references from all laps at the
        track. The fastest clean lap is taken from sessions of a compatible track length only (another layout under
        the same id is never a reference); a pinned reference is kept, and ``check_compatibility`` blocks it if it
        is not. With a coachref service the driver's chosen reference decides (``CoachRef.resolve``); this rule is
        its default and its fallback."""
        with self.db.read() as c:
            driver_id = repo.session_driver_id(c, session_id)
            if self.coachref is not None:  # --- coachref ---
                full = {**(ctx or {}), "game": game, "track_id": track_id, "car_id": car_id}
                full["track_length_m"] = track_length_m
                desc = self.coachref.resolve(c, session_id, driver_id, full, exclude, record=record)
                return driver_id, desc.lap_id, desc
            pinned = repo.pinned_reference(c, game, track_id, car_id, driver_id=driver_id)
            if pinned is not None and pinned != exclude:
                return driver_id, pinned, None
            for r in repo.clean_laps_for(
                c, game, track_id, car_id, limit=5, driver_id=driver_id, track_length_m=track_length_m
            ):
                if r["id"] != exclude:
                    return driver_id, int(r["id"]), None
        return driver_id, None, None

    def _reference_analysis(
        self,
        ref_id: int,
        model: TrackModel,
        session_id: str,
        ref_changed: bool = False,
        desc: ResolvedReference | None = None,
    ) -> LapAnalysis | None:
        """Analysis of the reference lap (cached per lap id). The live reference (delta bar, map trace) is
        published on a cache miss (e.g. re-analysed against a rebuilt track model) and whenever the session's
        reference changed, even to a cached lap - in both cases only while ``session_id`` is the live session."""
        cached = self._ref_cache.get(ref_id)
        if cached is not None:
            if ref_changed:
                self._publish_reference(session_id, ref_id, cached, desc)
            return cached
        an = self._analysis_for(ref_id, model)
        if an is not None:
            self._publish_reference(session_id, ref_id, an, desc)
        return an

    def _analysis_for(self, ref_id: int, model: TrackModel) -> LapAnalysis | None:
        """A stored lap analysed against ``model`` (cached per lap id; never published)."""
        cached = self._ref_cache.get(ref_id)
        if cached is not None:
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
        return an

    def _publish_reference(
        self, session_id: str, ref_id: int, an: LapAnalysis, desc: ResolvedReference | None = None
    ) -> None:
        if self.live is None or not self._is_live(session_id):
            return
        summary: dict[str, Any] = {
            "lap_id": ref_id,
            "lap_number": an.lap.lap_number,
            "lap_time_ms": an.lap.lap_time_ms,
            "session_id": an.lap.meta.get("session_id"),
        }
        if desc is not None:  # --- coachref --- the descriptor (kind, holder, labels, clamp, frozen)
            summary = {**desc.to_dict(), **summary}
        self.live.set_reference(summary, an.dtrace)


def ctx_family(ctx: dict[str, Any] | None) -> str | None:
    """The car class family (``carclass``) of a lap context (``LapJob.context`` / ``coachref.ctx_from_*``)."""
    if not ctx:
        return None
    return carclass.family_of(ctx.get("game"), ctx.get("formula"), ctx.get("car_id"), ctx.get("packet_format"))


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
        "final": lap.meta.get("final"),  # the driver's last lap of the session (None = the game does not say)
        "tyre_compound": lap.meta.get("tyre_compound"),
        "fuel_used_kg": (
            round(lap.meta["fuel_start_kg"] - lap.meta["fuel_end_kg"], 3)
            if lap.meta.get("fuel_start_kg") is not None and lap.meta.get("fuel_end_kg") is not None
            else None
        ),
    }


# --- coachref ---
@dataclass(slots=True)
class _Task:
    """A callable run on the analysis thread (``AnalysisWorker.submit_task``); its result or error goes to ``fut``."""

    fn: Callable[[], Any]
    fut: Future[Any]

    def run(self) -> None:
        if not self.fut.set_running_or_notify_cancel():
            return
        try:
            self.fut.set_result(self.fn())
        except BaseException as e:
            self.fut.set_exception(e)


TASK_PUT_TIMEOUT_S = 2.0
# --- coachref ---


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
        self._q: queue.Queue[LapJob | BestsRequest | AiPaceJob | _Task | None] = queue.Queue(maxsize=1000)
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

    # --- coachref ---
    def submit_task(self, fn: Callable[[], T]) -> Future[T]:
        """Run ``fn`` on the analysis thread, in order with the laps (the coachref service's changes). Never call it
        from the ingest thread: it waits up to ``TASK_PUT_TIMEOUT_S`` for queue space (``queue.Full`` after)."""
        fut: Future[T] = Future()
        self._q.put(_Task(fn, fut), timeout=TASK_PUT_TIMEOUT_S)
        return fut

    # --- coachref ---

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
                elif isinstance(job, _Task):  # --- coachref ---
                    job.run()
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
