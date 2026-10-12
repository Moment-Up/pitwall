"""On-demand analysis of a stored session (used by the API, session reports and the AI fact builder).

Driver scoping: unless the caller names a reference lap, the reference is the session owner's pinned reference,
else their fastest clean lap at the track, so a session is only ever compared with its own driver's driving. The
owner's profile and personal best at the track are attached for the fact sheet. Results are cached per (session,
lap count, requested reference, owner, owner's profile, latest stored car setup): a renamed driver or a new skill
level is a new key, so a profile edit can never leave the engineer pitching answers at the old level, whoever made
the edit, and a setup changed in the garage reaches the setup facts before the next lap. A
re-assignment changes the owner of the session itself (a new key) and can change the reference of the owner's
other sessions, so the API calls ``invalidate()`` after one. The cache is bounded (``CACHE_ENTRIES``, oldest
first): every new lap of a live session is a new key, and an analysis holds every lap's distance-domain trace.

Pace vs AI: ``ai_pace`` is the session's stored ``session_ai_pace`` row (``repo.get_session_ai_pace``; its
``updated_unix`` is part of the cache key, so a new summary after a lap is never hidden by a cached analysis) and
``ai_suggestion`` the suggested AI level at this session's track, car class, category and weather
(``analysis.ai_level``) from the owner's own real driving. The suggestion exists only for driven (not replayed),
non-synthetic sessions that have a driver.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pitwall import carclass
from pitwall.analysis.ai_level import AiLevelKey, suggest_for_key
from pitwall.analysis.coaching import is_incident, observations_for_comparison
from pitwall.analysis.compare import (
    CornerDelta,
    LapAnalysis,
    LapComparison,
    analyse_lap,
    check_compatibility,
    compare,
    compat_meta,
    lengths_compatible,
)
from pitwall.analysis.laps import LapFlag
from pitwall.analysis.track import TrackModel
from pitwall.analysis.track_identity import corner_texts, identify
from pitwall.drivers import Driver
from pitwall.model.telemetry import TrackZones
from pitwall.storage import repo
from pitwall.storage.db import Database

CACHE_ENTRIES = 32
_CacheKey = tuple[str, int, int | None, int | None, tuple[tuple[str, Any], ...], int | None, float | None]


@dataclass(slots=True)
class CornerSummary:
    corner: str
    direction: str | None
    apex_m: float
    laps: int
    mean_time_delta_s: float | None
    median_time_delta_s: float | None
    mean_brake_point_delta_m: float | None
    brake_point_std_m: float | None  # consistency of your braking point across laps
    min_speed_std_kph: float | None
    mean_min_speed_delta_kph: float | None
    mean_exit_speed_delta_kph: float | None
    ref_brake_start_m: float | None
    ref_min_speed_kph: float | None
    ref_exit_speed_kph: float | None


@dataclass(slots=True)
class SessionAnalysis:
    session: dict[str, Any]
    laps: list[dict[str, Any]]
    model: TrackModel | None
    ref_lap_id: int | None
    ref_lap: dict[str, Any] | None
    comparisons: dict[int, LapComparison] = field(default_factory=dict)  # lap_id -> comparison vs ref
    analyses: dict[int, LapAnalysis] = field(default_factory=dict)
    corner_summary: list[CornerSummary] = field(default_factory=list)
    observations: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    # owner of the session (``Driver.summary()``) and their best clean lap at this track in this car
    # (``repo.personal_best``); None when the session has no driver or the driver has no clean lap here yet
    driver: dict[str, Any] | None = None
    personal_best: dict[str, Any] | None = None
    # the session's latest stored car setup (``repo.latest_setup``) for the setup facts; None until the game sent one
    setup: dict[str, Any] | None = None
    # pace vs AI (``repo.get_session_ai_pace``, ``SessionAiPace``) and the suggested AI level for this session's key
    # (``analysis.ai_level``); None when not applicable / not recorded
    ai_pace: dict[str, Any] | None = None
    ai_suggestion: dict[str, Any] | None = None

    @property
    def latest_compared_lap_id(self) -> int | None:
        return max(self.comparisons) if self.comparisons else None


def _mean(vals: list[float]) -> float | None:
    return round(float(np.mean(vals)), 3) if vals else None


def _std(vals: list[float]) -> float | None:
    return round(float(np.std(vals)), 2) if len(vals) >= 2 else None


class SessionAnalyzer:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._cache: dict[_CacheKey, SessionAnalysis] = {}
        self._lock = threading.Lock()

    def invalidate(self, session_id: str | None = None) -> None:
        """Drop cached analyses (of one session, or all). Call after anything that changes which driver owns a
        session: the owner decides the reference, and one re-assignment can change other sessions' references."""
        with self._lock:
            if session_id is None:
                self._cache.clear()
            else:
                for k in [k for k in self._cache if k[0] == session_id]:
                    del self._cache[k]

    def analyse(self, session_id: str, ref_lap_id: int | None = None) -> SessionAnalysis | None:
        with self.db.read() as c:
            sess = repo.get_session(c, session_id)
            if sess is None:
                return None
            laps = repo.list_laps(c, session_id)
            driver_id: int | None = sess.get("driver_id")
            drow = repo.get_driver(c, driver_id) if driver_id is not None else None
            profile = Driver.from_row(drow).summary() if drow is not None else None
            setup = repo.latest_setup(c, session_id)
            ai_pace = repo.get_session_ai_pace(c, session_id)
            key: _CacheKey = (
                session_id,
                len(laps),
                ref_lap_id,
                driver_id,
                tuple(sorted(profile.items())) if profile is not None else (),
                setup["id"] if setup is not None else None,  # a garage setup change before the next lap
                None if ai_pace is None else ai_pace.get("updated_unix"),  # a new AI pace summary
            )
            with self._lock:
                if key in self._cache:
                    return self._cache[key]
            family = carclass.family_of_row(sess)  # the car class family's own model (else one standing in)
            model = repo.load_track_model(c, sess["game"], sess["track_id"], family) if sess.get("track_id") else None
            if model is not None and not lengths_compatible(model.length_m, sess.get("track_length_m")):
                model = None  # the stored model is of another layout under the same track id (AC consoles)
            # official corner numbers and names; the session's game-native zones gate the sheet (sector check)
            zones = TrackZones.from_dict((sess.get("info") or {}).get("track_zones"))
            model = identify(model, zones=zones)[0] if model is not None else None
            if ref_lap_id is None and sess.get("track_id"):
                ref_lap_id = repo.pinned_reference(
                    c, sess["game"], sess["track_id"], sess.get("car_id"), driver_id=driver_id
                )
                if ref_lap_id is None:
                    best = repo.clean_laps_for(
                        c,
                        sess["game"],
                        sess["track_id"],
                        sess.get("car_id"),
                        limit=1,
                        driver_id=driver_id,
                        track_length_m=sess.get("track_length_m"),
                    )
                    ref_lap_id = int(best[0]["id"]) if best else None
            ref_row = repo.get_lap(c, ref_lap_id, with_trace=False) if ref_lap_id else None
            out = SessionAnalysis(session=sess, laps=laps, model=model, ref_lap_id=ref_lap_id, ref_lap=ref_row)
            out.setup = setup
            out.ai_pace = ai_pace
            out.ai_suggestion = _ai_suggestion(c, sess, ai_pace, driver_id)
            if driver_id is not None:
                out.driver = profile
                if sess.get("track_id"):
                    out.personal_best = repo.personal_best(
                        c, driver_id, sess["game"], sess["track_id"], sess.get("car_id")
                    )
            if model is None or not model.corners or ref_lap_id is None:
                return out
            ref_trace = repo.load_lap_trace(c, ref_lap_id)
            ref_sess = repo.get_session(c, ref_row["session_id"]) if ref_row else None
            if ref_trace is None or ref_sess is None:
                return out
            ref_trace.meta.update(session_ctx(ref_sess))
            ref_an = analyse_lap(ref_trace, model)
            out.analyses[ref_lap_id] = ref_an
            history: dict[str, list[CornerDelta]] = {}
            for lap in laps:
                if LapFlag.INCOMPLETE in lap["flags"]:
                    continue
                trace = repo.load_lap_trace(c, lap["id"])
                if trace is None:
                    continue
                trace.meta.update(session_ctx(sess))
                an = analyse_lap(trace, model) if lap["id"] != ref_lap_id else ref_an
                out.analyses[lap["id"]] = an
                if lap["id"] == ref_lap_id:
                    continue
                compat = check_compatibility(compat_meta(ref_trace.meta), compat_meta(trace.meta), ref_trace.clean)
                comp = compare(ref_an, an, compat)
                out.comparisons[lap["id"]] = comp
                out.observations[lap["id"]] = [
                    o.to_dict()
                    for o in observations_for_comparison(comp, history=history, corner_text=corner_texts(model))
                ]
                for cd in comp.corners:
                    if is_incident(cd):
                        continue
                    history.setdefault(cd.corner, []).append(cd)
                    del history[cd.corner][:-5]
        out.corner_summary = self._corner_summary(out)
        with self._lock:
            self._cache[key] = out
            while len(self._cache) > CACHE_ENTRIES:
                del self._cache[next(iter(self._cache))]  # insertion order: the oldest entry goes first
        return out

    @staticmethod
    def _corner_summary(sa: SessionAnalysis) -> list[CornerSummary]:
        if sa.model is None:
            return []
        rows: list[CornerSummary] = []
        usable = [c for lid, c in sa.comparisons.items() if c.compatibility.ok]
        for corner in sa.model.corners:
            # incidents (spins, contact, slow-downs) are reported as such, never averaged into technique deltas
            deltas = [cd for comp in usable for cd in comp.corners if cd.corner == corner.name and not is_incident(cd)]
            td = [d.time_delta_s for d in deltas if d.time_delta_s is not None]
            bp = [d.brake_point_delta_m for d in deltas if d.brake_point_delta_m is not None]
            bstart = [d.cmp.brake_start_m for d in deltas if d.cmp.brake_start_m is not None]
            msp = [d.cmp.min_speed_kph for d in deltas if d.cmp.min_speed_kph is not None]
            ms = [d.min_speed_delta_kph for d in deltas if d.min_speed_delta_kph is not None]
            ex = [d.exit_speed_delta_kph for d in deltas if d.exit_speed_delta_kph is not None]
            ref = deltas[0].ref if deltas else None
            rows.append(
                CornerSummary(
                    corner=corner.name,
                    direction=corner.direction,
                    apex_m=round(corner.apex_m, 1),
                    laps=len(deltas),
                    mean_time_delta_s=_mean(td),
                    median_time_delta_s=round(float(np.median(td)), 3) if td else None,
                    mean_brake_point_delta_m=_mean(bp),
                    brake_point_std_m=_std(bstart),
                    min_speed_std_kph=_std(msp),
                    mean_min_speed_delta_kph=_mean(ms),
                    mean_exit_speed_delta_kph=_mean(ex),
                    ref_brake_start_m=None if ref is None or ref.brake_start_m is None else round(ref.brake_start_m, 1),
                    ref_min_speed_kph=None if ref is None or ref.min_speed_kph is None else round(ref.min_speed_kph, 1),
                    ref_exit_speed_kph=None
                    if ref is None or ref.exit_speed_kph is None
                    else round(ref.exit_speed_kph, 1),
                )
            )
        return rows


def _ai_suggestion(
    c: Any, sess: dict[str, Any], ai_pace: dict[str, Any] | None, driver_id: int | None
) -> dict[str, Any] | None:
    """The suggested AI level for this session's key from the owner's own real driving (never for a replay, a
    synthetic session or a session without a driver)."""
    if (
        ai_pace is None
        or driver_id is None
        or sess.get("synthetic")
        or repo.is_replay_source(str(sess.get("source") or ""))
        or not sess.get("track_id")
    ):
        return None
    key = AiLevelKey(
        game=str(sess["game"]),
        track_id=str(sess["track_id"]),
        car_class=ai_pace.get("car_class"),
        session_category=str(sess.get("session_type") or "unknown"),
        weather_class=ai_pace.get("weather_class"),
    )
    points = repo.driver_ai_pace_points(c, driver_id, game=key.game, car_class=key.car_class)
    return suggest_for_key(key, points)


def session_ctx(sess: dict[str, Any]) -> dict[str, Any]:
    w = sess.get("weather") or {}
    return {
        "game": sess.get("game"),
        "track_id": sess.get("track_id"),
        "track_length_m": sess.get("track_length_m"),
        "car_id": sess.get("car_id"),
        "weather": w.get("condition"),
        "track_temp_c": w.get("track_temp_c"),
        "assists": sess.get("assists") or {},
    }
