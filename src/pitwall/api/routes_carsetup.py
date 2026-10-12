"""Car setup API: ``/api/carsetup`` (mounted by ``api.app`` with ``app.include_router(router)``).

Endpoints
    GET  /api/carsetup/catalog                     car formats (tracks, ranges, latest handling patch), parameters
                                                   in menu order with their plain-words effects, sources and terms,
                                                   derivation rules, and which combinations have a recommendation
    GET  /api/carsetup/recommendation?car_format=&track_id=&session=&conditions=&style=&driver_id=&skill_level=
                                                   one recommendation with provenance on every value; without a
                                                   style, the driver's skill picks it (beginner -> stable)
    GET  /api/carsetup/sessions/{sid}?car_format=&session=&conditions=&style=&skill_level=
                                                   what the session needs (car format, session, dry/wet: each with
                                                   its reason), the driver's latest stored setup, the
                                                   recommendation and "your setup vs recommended"; a field pitwall
                                                   cannot tell (e.g. the car format of a generic car) is listed in
                                                   ``needs`` and is chosen with the query parameter of that name
    GET  /api/carsetup/experiments?track_id=&status=&session_id=&limit=
    POST /api/carsetup/experiments                 {before_session_id, parameter, to_value, hypothesis?, car_format?}
    GET  /api/carsetup/experiments/{id}
    POST /api/carsetup/experiments/{id}/start      {after_session_id}
    POST /api/carsetup/experiments/{id}/conclude
    POST /api/carsetup/experiments/{id}/abandon    {reason?}

Everything is deterministic (``pitwall.carsetup``); nothing here calls an LLM. Handlers are plain ``def`` so
FastAPI runs them in its thread pool (concluding an experiment loads lap traces). Errors: invalid values 422,
unknown sessions / experiments 404, a combination with no recommendation 404 with ``{reason, alternatives}``,
lifecycle conflicts (e.g. concluding a proposed experiment) 409, a missing or invalid catalogue file 503.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from pitwall import carclass
from pitwall.adapters.f1.enums import track_name
from pitwall.carsetup import experiments as exps
from pitwall.carsetup.catalog import FORMAT_FAMILY, Catalog, CatalogError, formats_of_family, load_catalog
from pitwall.carsetup.compare import diff_setup
from pitwall.carsetup.context import session_context
from pitwall.carsetup.recommend import (
    CAVEAT,
    RecommendationUnavailable,
    SetupRequest,
    SetupRequestError,
    SkillLevel,
    available,
    parse_car_format,
    parse_conditions,
    parse_session,
    parse_skill,
    parse_style,
    parse_track_id,
    recommend,
)
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.storage import repo

router = APIRouter(prefix="/api/carsetup", tags=["carsetup"])


class ProposeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before_session_id: str = Field(min_length=1)
    parameter: str = Field(min_length=1)
    to_value: float
    hypothesis: str | None = Field(default=None, max_length=500)
    car_format: str | None = None


class StartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_session_id: str = Field(min_length=1)


class AbandonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------------------------- helpers
def _catalog() -> Catalog:
    try:
        return load_catalog()
    except CatalogError as e:
        raise HTTPException(503, f"car setup catalogue unavailable: {e}") from e


def _runtime(request: Request) -> Any:
    rt = getattr(request.app.state, "runtime", None)
    if rt is None:
        raise HTTPException(503, "runtime unavailable")
    return rt


def _analyzer(request: Request) -> SessionAnalyzer:
    analyzer = getattr(request.app.state, "analyzer", None)
    if isinstance(analyzer, SessionAnalyzer):
        return analyzer
    analyzer = SessionAnalyzer(_runtime(request).db)
    request.app.state.analyzer = analyzer
    return analyzer


def _skill_of(row: dict[str, Any] | None) -> SkillLevel | None:
    prefs = (row or {}).get("preferences") or {}
    try:
        return parse_skill(prefs.get("skill_level"))
    except SetupRequestError:
        return None


def _driver_skill(request: Request, driver_id: int | None, skill_level: str | None) -> tuple[SkillLevel | None, str]:
    if skill_level is not None:
        return parse_skill(skill_level), "request"
    if driver_id is None:
        return None, "none"
    with _runtime(request).db.read() as c:
        row = repo.get_driver(c, driver_id)
    if row is None:
        raise HTTPException(404, f"driver {driver_id} not found")
    skill = _skill_of(row)
    return skill, "driver" if skill is not None else "none"


def _unavailable(e: RecommendationUnavailable) -> dict[str, Any]:
    return {"reason": e.reason, "alternatives": e.alternatives}


def _catalog_body(cat: Catalog) -> dict[str, Any]:
    return {
        "game": cat.game,
        "updated": cat.updated,
        "research_doc": cat.research_doc,
        "caveat": CAVEAT,
        "formats": [
            {
                "id": f.id,
                "label": f.label,
                "description": f.description,
                "latest_handling_patch": None
                if f.latest_handling_patch is None
                else {
                    "version": f.latest_handling_patch.version,
                    "date": f.latest_handling_patch.date,
                    "note": f.latest_handling_patch.note,
                    "source": f.latest_handling_patch.source,
                },
                "tracks": [{"id": t, "name": track_name(t)} for t in f.tracks],
                "notes": list(f.notes),
                # the format's own ranges (also under each parameter's "ranges"): F2's come from F2 evidence only
                "ranges": {
                    k: {
                        "min": r.min,
                        "max": r.max,
                        "step": r.step,
                        "min_confirmed": r.min_confirmed,
                        "max_confirmed": r.max_confirmed,
                        "confidence": r.confidence,
                        "sources": list(r.sources),
                        "note": r.note,
                    }
                    for k, r in f.ranges.items()
                },
            }
            for f in cat.formats.values()
        ],
        "parameters": [
            {
                "key": p.key,
                "label": p.label,
                "group": p.group,
                "order": p.order,
                "unit": p.unit,
                "decimals": p.decimals,
                "higher": p.higher,
                "lower": p.lower,
                "sources": list(p.sources),
                "ranges": {
                    fid: {
                        "min": r.min,
                        "max": r.max,
                        "step": r.step,
                        "min_confirmed": r.min_confirmed,
                        "max_confirmed": r.max_confirmed,
                        "confidence": r.confidence,
                        "note": r.note,
                    }
                    for fid, f in cat.formats.items()
                    if (r := f.ranges.get(p.key)) is not None
                },
            }
            for p in cat.parameters
        ],
        "sources": [
            {
                "id": s.id,
                "name": s.name,
                "url": s.url,
                "kind": s.kind,
                "terms_url": s.terms_url,
                "terms": s.terms,
                "use_policy": s.use_policy,
                "accessed": s.accessed,
                "setups": sum(1 for x in cat.source_setups.values() if x.source == s.id),
            }
            for s in cat.sources.values()
        ],
        "rules": [{"id": r.id, "description": r.description, "sources": list(r.sources)} for r in cat.rules.values()],
        "available": available(cat),
    }


# ---------------------------------------------------------------------------------------------- catalogue
@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    return _catalog_body(_catalog())


@router.get("/recommendation")
def get_recommendation(
    request: Request,
    car_format: str,
    track_id: str,
    session: str = "race",
    conditions: str = "dry",
    style: str | None = None,
    driver_id: int | None = None,
    skill_level: str | None = None,
) -> dict[str, Any]:
    cat = _catalog()
    try:
        skill, skill_source = _driver_skill(request, driver_id, skill_level)
        req = SetupRequest(
            car_format=parse_car_format(car_format),
            track_id=parse_track_id(track_id),
            session=parse_session(session),
            conditions=parse_conditions(conditions),
            style=parse_style(style) if style is not None else None,
            skill_level=skill,
        )
        res = recommend(cat, req)
    except SetupRequestError as e:
        raise HTTPException(422, str(e)) from e
    except RecommendationUnavailable as e:
        raise HTTPException(404, _unavailable(e)) from e
    return {**res.to_dict(), "skill_level": skill, "skill_source": skill_source}


# ---------------------------------------------------------------------------------------------- sessions
@router.get("/sessions/{sid}")
def get_session_setup(
    request: Request,
    sid: str,
    car_format: str | None = None,
    session: str | None = None,
    conditions: str | None = None,
    style: str | None = None,
    skill_level: str | None = None,
) -> dict[str, Any]:
    with _runtime(request).db.read() as c:
        sess = repo.get_session(c, sid)
        if sess is None:
            raise HTTPException(404, f"session {sid} not found")
        stored = repo.latest_setup(c, sid)
        driver = repo.get_driver(c, sess["driver_id"]) if sess.get("driver_id") is not None else None
    cat = _catalog()
    ctx = session_context(sess)
    try:
        fmt = parse_car_format(car_format) if car_format is not None else ctx.car_format
        if fmt is not None and car_format is not None and ctx.family is not None and FORMAT_FAMILY[fmt] != ctx.family:
            # never an F1 car's setups for an F2 car, or the reverse (F2 support)
            cls_label = ctx.car_class.label if ctx.car_class is not None else None
            raise SetupRequestError(
                f"car format {fmt!r} is not for this session's car ({cls_label or 'its class'}); "
                f"expected one of {', '.join(formats_of_family(ctx.family)) or 'none'}"
            )
        kind = parse_session(session) if session is not None else ctx.session
        cond = parse_conditions(conditions) if conditions is not None else ctx.conditions
        chosen_style = parse_style(style) if style is not None else None
        skill = parse_skill(skill_level) if skill_level is not None else _skill_of(driver)
    except SetupRequestError as e:
        raise HTTPException(422, str(e)) from e
    supported = "game" not in ctx.reasons and ctx.track_id is not None
    # the car format is asked only of an F1 car whose generation the game does not tell (never of an F2 car)
    asks = {"car_format": ctx.asks_car_format or car_format is not None, "session": True, "conditions": True}
    needs = [
        n
        for n, v in (("car_format", fmt), ("session", kind), ("conditions", cond))
        if v is None and supported and asks[n]
    ]
    labels = carclass.session_fields(sess)
    body: dict[str, Any] = {
        "session": {
            "id": sid,
            "game": sess.get("game"),
            "track_id": sess.get("track_id"),
            "track_name": sess.get("track_name"),
            "session_type": sess.get("session_type"),
            "session_type_raw": sess.get("session_type_raw"),
            "car_name": sess.get("car_name"),
            "car_class": labels["car_class"],
            "car_label": labels["car_label"],
            "session_label": labels["session_label"],
            "weather": sess.get("weather") or {},
            "synthetic": bool(sess.get("synthetic")),
            "driver": None
            if driver is None
            else {"id": driver["id"], "name": driver["name"], "skill_level": _skill_of(driver)},
        },
        "context": ctx.to_dict(),
        "chosen": {"car_format": fmt, "session": kind, "conditions": cond, "style": chosen_style},
        "needs": needs,
        "setup": None
        if stored is None
        else {
            "t_recv_ns": stored.get("t_recv_ns"),
            "fingerprint": stored.get("fingerprint"),
            "params": stored["params"],
        },
        "recommendation": None,
        "unavailable": None,
        "diff": None,
        "caveat": CAVEAT,
    }
    if not supported or ctx.track_id is None:
        body["unavailable"] = {
            "reason": ctx.reasons.get("game") or ctx.reasons.get("track_id", "unknown track"),
            "alternatives": [],
        }
        return body
    if fmt is None and not ctx.asks_car_format:
        # an F2 car with no setups (2026 F2 cars, or the team is not known) or a classic car: said, never asked
        body["unavailable"] = {"reason": ctx.reasons.get("car_format", "no setups for this car"), "alternatives": []}
        return body
    if fmt is None or kind is None or cond is None:
        body["unavailable"] = {
            "reason": "choose " + ", ".join(n.replace("_", " ") for n in needs) + " to see a recommendation",
            "alternatives": available(cat, fmt, ctx.track_id, ctx.family),
        }
        return body
    try:
        res = recommend(
            cat,
            SetupRequest(
                car_format=fmt,
                track_id=ctx.track_id,
                session=kind,
                conditions=cond,
                style=chosen_style,
                skill_level=skill,
            ),
        )
    except RecommendationUnavailable as e:
        body["unavailable"] = _unavailable(e)
        return body
    body["recommendation"] = res.to_dict()
    if stored is not None:
        body["diff"] = diff_setup(cat, res, stored["params"]).to_dict()
    return body


# ---------------------------------------------------------------------------------------------- experiments
def _exp_error(e: exps.ExperimentError | exps.ExperimentNotFound | SetupRequestError) -> HTTPException:
    if isinstance(e, exps.ExperimentNotFound):
        return HTTPException(404, str(e))
    if isinstance(e, exps.ExperimentError):
        return HTTPException(409 if e.conflict else 422, str(e))
    return HTTPException(422, str(e))


@router.get("/experiments")
def list_experiments(
    request: Request,
    track_id: str | None = None,
    status: str | None = None,
    session_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    if status is not None and status not in exps.STATUSES:
        raise HTTPException(422, f"unknown status {status!r}; expected one of {', '.join(exps.STATUSES)}")
    track = f"f1:{parse_track_id(track_id)}" if track_id is not None and _is_track(track_id) else track_id
    return exps.list_experiments(
        _runtime(request).db, track_id=track, status=status, session_id=session_id, limit=limit
    )


def _is_track(v: str) -> bool:
    try:
        parse_track_id(v)
    except SetupRequestError:
        return False
    return True


@router.post("/experiments", status_code=201)
def propose_experiment(request: Request, body: ProposeBody) -> dict[str, Any]:
    rt = _runtime(request)
    try:
        fmt = parse_car_format(body.car_format) if body.car_format is not None else None
        return exps.propose(
            rt.db,
            rt.writer,
            _catalog(),
            before_session_id=body.before_session_id,
            parameter=body.parameter,
            to_value=body.to_value,
            hypothesis=body.hypothesis,
            car_format=fmt,
        )
    except (exps.ExperimentError, exps.ExperimentNotFound, SetupRequestError) as e:
        raise _exp_error(e) from e


@router.get("/experiments/{exp_id}")
def get_experiment(request: Request, exp_id: int) -> dict[str, Any]:
    try:
        return exps.get_experiment(_runtime(request).db, exp_id)
    except exps.ExperimentNotFound as e:
        raise _exp_error(e) from e


@router.post("/experiments/{exp_id}/start")
def start_experiment(request: Request, exp_id: int, body: StartBody) -> dict[str, Any]:
    rt = _runtime(request)
    try:
        return exps.start(rt.db, rt.writer, exp_id, body.after_session_id)
    except (exps.ExperimentError, exps.ExperimentNotFound) as e:
        raise _exp_error(e) from e


@router.post("/experiments/{exp_id}/conclude")
def conclude_experiment(request: Request, exp_id: int) -> dict[str, Any]:
    rt = _runtime(request)
    try:
        return exps.conclude(rt.db, rt.writer, _analyzer(request), _catalog(), exp_id)
    except (exps.ExperimentError, exps.ExperimentNotFound) as e:
        raise _exp_error(e) from e


@router.post("/experiments/{exp_id}/abandon")
def abandon_experiment(request: Request, exp_id: int, body: AbandonBody | None = None) -> dict[str, Any]:
    rt = _runtime(request)
    try:
        return exps.abandon(rt.db, rt.writer, exp_id, body.reason if body is not None else None)
    except (exps.ExperimentError, exps.ExperimentNotFound) as e:
        raise _exp_error(e) from e
