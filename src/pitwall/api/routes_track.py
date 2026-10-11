"""Track priors API: ``/api/track`` (mounted by ``api.app`` with ``app.include_router(router)``).

Endpoints
    GET /api/track/outline?game=&track_id=&track_length_m=
        The game-frame outline (layer L1a, tier ``shipped_seed``) from the vendored Pits n' Giggles maps: world X/Z
        knots with their game lap distance, and a TrackModel-compatible ``centreline`` (one point per 5 m of lap
        distance) so the dashboard can draw a map before pitwall has learned the track. Labelled
        "game outline (Pits n' Giggles)" and carries its MIT attribution.
    GET /api/track/prior?game=&track_id=&track_length_m=
        Physics heavy-stop windows (layer L1c, tier ``physics_predicted``): heads-up bands that start a window margin
        (``uncertainty_m``, 100 m) before the estimated onset, ``positional: false``, every position an ``est_*``
        field, with the measured onset error on real laps (``onset_error``, p90 70 m). Never braking targets.

``track_length_m`` should be the live session's ``m_trackLength`` (``snapshot.session.track_length_m``); without it
the track sheet's seeded ``lap_length_m`` is used and the response says so (``track_length_source``). Errors: 404 when
there is no outline for the game/track (other games, Madrid, legacy ids, synthetic tracks), 422 when the length gate
refuses the outline or no lap length is known (unknown stays unknown: no map rather than a wrong one).

Handlers are plain ``def`` (thread pool): the prior costs ~0.1 s on first use per track, then both responses are cached
in-process by (game, track, lap length). Nothing here calls an LLM or touches ingest.
"""

from __future__ import annotations

import functools
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from pitwall.analysis.brake_prior import build_brake_prior
from pitwall.analysis.track_geometry import OutlineError, build_outline, outline_key

router = APIRouter(prefix="/api/track", tags=["track"])

GameQ = Annotated[str, Query(min_length=1, max_length=32, description="pitwall game id, e.g. f1_25")]
TrackQ = Annotated[str, Query(min_length=1, max_length=64, description="pitwall track id, e.g. f1:17")]
LengthQ = Annotated[
    float | None, Query(gt=0, le=30_000, description="the session's track length in metres (m_trackLength)")
]


def _length_key(track_length_m: float | None) -> float | None:
    # float32 noise in m_trackLength must not split the cache
    return None if track_length_m is None else round(float(track_length_m), 1)


def _check_known(game: str, track_id: str) -> None:
    if outline_key(game, track_id) is None:
        raise HTTPException(404, f"no track outline for game={game!r} track_id={track_id!r}")


@functools.lru_cache(maxsize=64)
def _outline_payload(game: str, track_id: str, track_length_m: float | None) -> dict[str, Any]:
    return build_outline(game, track_id, track_length_m).to_payload()


@router.get("/outline")
def track_outline(game: GameQ, track_id: TrackQ, track_length_m: LengthQ = None) -> dict[str, Any]:
    _check_known(game, track_id)
    try:
        return _outline_payload(game, track_id, _length_key(track_length_m))
    except OutlineError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/prior")
def track_prior(game: GameQ, track_id: TrackQ, track_length_m: LengthQ = None) -> dict[str, Any]:
    _check_known(game, track_id)
    try:
        return build_brake_prior(game, track_id, _length_key(track_length_m)).to_payload()
    except OutlineError as e:
        raise HTTPException(422, str(e)) from e
