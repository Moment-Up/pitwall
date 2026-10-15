"""Family leaderboard API (``pitwall.leaderboard``; JSON contract in docs/leaderboard.md). Local only: nothing here
sends anything anywhere.

Endpoints
    GET /api/leaderboard?key=...                       Board of an exact key (``keys.encode``)
    GET /api/leaderboard?game&track_id[&length_m&car_id&car_class&equal_performance&category&conditions&assists]
                                                       Board picked by fields (unset = any; ``?`` = the unknown bucket;
                                                       several matches: the one driven most recently)
    GET /api/records?game&track_id&driver_id           RecordsIndex: every board with its record holder and time
    GET /api/leaderboard/lapcard/{lap_id}?capture_hash=false   LapCard (format ``pitwall.lapcard`` v1)

Handlers are plain ``def`` (FastAPI's thread pool): reads only, one short-lived read connection each. Errors: 404
unknown lap, 409 a lap card for a lap with no time, 422 a key or field that does not parse. Pydantic models live only
here (the query); the responses are the plain dicts ``leaderboard.service`` builds.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator

from pitwall.leaderboard import keys as K
from pitwall.leaderboard import service as S

router = APIRouter(tags=["leaderboard"])

_Id = Annotated[str, Field(min_length=1, max_length=128)]


class BoardQuery(BaseModel):
    """Either ``key`` alone, or ``game`` + ``track_id`` with optional key fields (string parts of a key)."""

    key: str | None = Field(default=None, min_length=1, max_length=600)
    game: _Id | None = None
    track_id: _Id | None = None
    length_m: float | None = Field(default=None, gt=0, le=100_000)
    car_id: _Id | None = None  # "?" = the unknown-car board
    car_class: Literal["f1", "f2", "other", "?", "-"] | None = None
    equal_performance: Literal["0", "1", "?", "-"] | None = None
    category: Literal["time_trial", "qualifying", "race", "practice", "unknown"] | None = None
    conditions: Literal["dry", "wet", "unknown"] | None = None
    assists: str | None = Field(default=None, min_length=1, max_length=64)  # an assist code: b2.a1.t2.g3.l2 / a1.t0 / -

    @model_validator(mode="after")
    def _key_or_track(self) -> BoardQuery:
        fields = (self.game, self.track_id, self.length_m, self.car_id, self.car_class, self.equal_performance)
        more = (self.category, self.conditions, self.assists)
        if self.key is not None:
            if any(v is not None for v in (*fields, *more)):
                raise ValueError("give either key, or game and track_id with optional fields")
            return self
        if self.game is None or self.track_id is None:
            raise ValueError("give key, or game and track_id")
        return self


def _db(request: Request) -> Any:
    return request.app.state.runtime.db


@router.get("/api/leaderboard")
def leaderboard(request: Request, q: Annotated[BoardQuery, Query()]) -> dict[str, Any]:
    try:
        if q.key is not None:
            key = K.decode(q.key)
            with _db(request).read() as c:
                return S.board_by_key(c, key)
        assert q.game is not None and q.track_id is not None
        if q.assists is not None:
            K.parse_assists(q.game, q.assists)  # 422 for a code that does not fit the game
        f = S.BoardFilter(
            game=q.game,
            track_id=q.track_id,
            length_m=q.length_m,
            car_id=q.car_id,
            car_class=q.car_class,
            equal_performance=q.equal_performance,
            category=q.category,
            conditions=q.conditions,
            assists=q.assists,
        )
    except K.BadKey as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    with _db(request).read() as c:
        return S.board_by_filter(c, f)


@router.get("/api/records")
def records(
    request: Request,
    game: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    track_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    driver_id: int | None = None,
) -> dict[str, Any]:
    with _db(request).read() as c:
        return S.records_index(c, game, track_id, driver_id)


@router.get("/api/leaderboard/lapcard/{lap_id}")
def lapcard(request: Request, lap_id: int, capture_hash: bool = False) -> dict[str, Any]:
    try:
        with _db(request).read() as c:
            return S.lap_card(c, lap_id, capture_hash=capture_hash)
    except S.LeaderboardNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except S.LeaderboardRefused as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
