"""Controls and button mapping API: ``/api/controls`` (Setup › Controls; mounted by ``api.app``).

Endpoints (contract: the dashboard's ``lib/endpoints/controls.ts``)
    GET    /catalog                                  ControlsCatalog (+ additive ``diagram`` geometry)
    GET    /templates/{id}                           a template expanded to a WheelDef draft (rev 0, unsaved)
    GET    /state?driver_id=                         the section, the effective push-to-talk, the page's defaults
    POST   /wheels                                   {name, template?, shape?, platforms?, parts?, controls?}
    PUT    /wheels/{id}                              full replace, with the ``rev`` read (409 when stale)
    DELETE /wheels/{id}                              409 while a layout uses it (the detail names them)
    GET    /wheels/{id}/export                       {"schema": "pitwall.controls.wheel/1", "wheel": WheelDef}
    POST   /wheels/import                            that file -> a new wheel (new id; evidence H but template fields)
    PUT    /wheels/{id}/controls/{cid}/signal        {platform, signal, rev?} (Identify: "Save as this signal")
    GET    /recommendation?game=&platform=&wheel_id=&template=&driver_id=&preset=&game_name=&functions=
                                                     a Recommendation (never saved)
    POST   /layouts                                  {game, platform, wheel_id, owner, preset, assignments? |
                                                      from_recommendation} -> Layout (the owner's choice points at it)
    PUT    /layouts/{id}                             {rev, preset?, owner?, assignments?, game_name?, other_functions?}
    DELETE /layouts/{id}
    GET    /layouts/{id}/guide?platform=             MapGuide ("Map it")
    GET    /layouts/{id}/card.html?driver_id=        printable card (text/html, no scripts; ?token= for a new tab)
    GET    /layouts/{id}/card.txt?driver_id=         plain text ("Copy as text")
    PUT    /drivers/{driver_id}                      partial {wheel_id?, preset?, layouts?}; "household" for the console
    POST   /test                                     {layout_id, mode?} -> ControlsTest (409 while one runs)
    GET    /test                                     ControlsTest | null (advances the test; poll at 4 Hz)
    POST   /test/{id}/skip | /test/{id}/stop
    GET    /buttons?since=                           the probe feed (Identify outside a test)

Storage: the SettingsStore section ``"controls"`` (``controls.model``), read-modify-write under ``model.write_lock``;
no SQLite change. Handlers are plain ``def`` (thread pool). 404 unknown ids, 409 stale ``rev`` / a running test / a
wheel in use, 422 invalid input in plain English. Nothing here calls an LLM, and nothing says "validated".
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import replace
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from pitwall import games
from pitwall.adapters.f1.enums import button_names
from pitwall.controls import model as M
from pitwall.controls.card import card_html, card_text
from pitwall.controls.catalog import PTT_FUNCTION, Catalog, in_sentence, load_catalog
from pitwall.controls.probe import TestItem, build_items
from pitwall.controls.recommend import Recommendation, allowed_actions, other_rows, recommend
from pitwall.controls.steps import guide
from pitwall.controls.templates import default_wheel, resolve_wheel, template_wheel
from pitwall.storage import repo

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/controls", tags=["controls"])

WheelId = Annotated[str, Path(pattern=r"^w_[0-9a-f]{8}$")]
LayoutId = Annotated[str, Path(pattern=r"^l_[0-9a-f]{8}$")]
ControlId = Annotated[str, Path(pattern=r"^[a-z0-9_]{1,40}$")]
TestId = Annotated[str, Path(pattern=r"^t_[0-9a-f]{8}$")]
EXPORT_SCHEMA = "pitwall.controls.wheel/1"
NO_BUTTONS = "{game} doesn't send button presses, so Pitwall can't test your wheel here. Check each button in the game."


# ---------------------------------------------------------------------------------------------- bodies
class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignalIn(_Body):
    kind: Literal["pad", "game_specific", "folded", "hid_button", "hid_hat", "hid_axis", "none", "unknown"]
    value: str | None = Field(default=None, max_length=60)
    per_slot: dict[str, Annotated[str, Field(max_length=60)]] | None = None
    evidence: Literal["V", "A", "U", "D", "H", "seen"] = "H"
    source_ids: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=16)
    seen: dict[str, Any] | None = None


class ControlIn(_Body):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    part: str | None = Field(default=None, max_length=40)
    kind: str = Field(max_length=20)
    label: str = Field(max_length=M.MAX_LABEL)
    zone: str = Field(default="unplaced", max_length=20)
    order: int = Field(default=0, ge=0, le=999)
    reach: str | None = Field(default=None, max_length=10)
    push: bool = False
    positions: int | None = Field(default=None, ge=2, le=M.MAX_POSITIONS)
    mps_mode: str | None = Field(default=None, max_length=10)
    signals: dict[str, SignalIn] = Field(default_factory=dict)
    evidence: Literal["V", "A", "U", "D", "H", "seen"] = "H"
    note: str = Field(default="", max_length=M.MAX_NOTE)


class PartIn(_Body):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    kind: Literal["rim", "hub", "button_box", "wheel_bundle"] = "rim"
    name: str = Field(max_length=M.MAX_NAME)


class WheelCreate(_Body):
    name: str = Field(min_length=1, max_length=M.MAX_NAME)
    template: str | None = Field(default=None, max_length=64)
    shape: Literal["round", "d", "formula", "box"] | None = None
    platforms: list[Literal["ps", "xbox", "pc"]] | None = None
    parts: list[PartIn] | None = Field(default=None, max_length=8)
    controls: list[ControlIn] | None = Field(default=None, max_length=M.MAX_CONTROLS)


class WheelPut(_Body):
    rev: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=M.MAX_NAME)
    template: str | None = Field(default=None, max_length=64)
    template_version: str | None = Field(default=None, max_length=32)
    shape: Literal["round", "d", "formula", "box"] = "round"
    platforms: list[Literal["ps", "xbox", "pc"]] = Field(default_factory=list)
    parts: list[PartIn] = Field(min_length=1, max_length=8)
    controls: list[ControlIn] = Field(default_factory=list, max_length=M.MAX_CONTROLS)
    # read-only fields the dashboard may send back unchanged
    id: str | None = None
    created_unix: float | None = None
    updated_unix: float | None = None


class SignalPut(_Body):
    platform: Literal["ps", "xbox", "pc"]
    signal: SignalIn
    rev: int | None = Field(default=None, ge=0)


class CheckIn(_Body):
    result: Literal["detected", "effect_seen", "other_bits", "not_seen"]
    t_unix: float
    detail: str = Field(default="", max_length=120)
    origin: Literal["live"] = "live"


class AssignmentIn(_Body):
    key: str | None = Field(default=None, max_length=50)
    function: str = Field(pattern=r"^[a-z0-9_]{1,32}$")
    action: str = Field(pattern=r"^[a-z0-9_]{1,16}$")
    control_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,40}$")
    slot: str | None = Field(default=None, max_length=10)
    udp_action: int | None = Field(default=None, ge=1, le=12)
    origin: Literal["recommended", "driver", "game_fixed", "kept", "game_default"] = "driver"
    check: CheckIn | None = None


class LayoutCreate(_Body):
    game: str = Field(pattern=r"^[a-z0-9_]{1,32}$")
    platform: Literal["ps5", "ps4", "xbox", "pc"]
    wheel_id: str = Field(pattern=r"^w_[0-9a-f]{8}$")
    owner: Literal["household"] | int = "household"
    preset: Literal["beginner", "advanced"] = "advanced"
    game_name: str | None = Field(default=None, max_length=M.MAX_NAME)
    other_functions: list[Annotated[str, Field(max_length=32)]] | None = Field(default=None, max_length=40)
    assignments: list[AssignmentIn] | None = Field(default=None, max_length=M.MAX_ASSIGNMENTS)
    from_recommendation: bool = False


class LayoutPut(_Body):
    rev: int = Field(ge=0)
    preset: Literal["beginner", "advanced"] | None = None
    owner: Literal["household"] | int | None = None
    game_name: str | None = Field(default=None, max_length=M.MAX_NAME)
    other_functions: list[Annotated[str, Field(max_length=32)]] | None = Field(default=None, max_length=40)
    assignments: list[AssignmentIn] | None = Field(default=None, max_length=M.MAX_ASSIGNMENTS)


class DriverPut(_Body):
    wheel_id: str | None = Field(default=None, pattern=r"^w_[0-9a-f]{8}$")
    preset: Literal["beginner", "advanced"] | None = None
    layouts: dict[Annotated[str, Field(max_length=48)], str | None] | None = None


class TestStart(_Body):
    layout_id: str | None = Field(default=None, pattern=r"^l_[0-9a-f]{8}$")
    mode: Literal["layout", "identify"] = "layout"
    # additive: test only these assignment keys ("Try again" on one item)
    keys: list[Annotated[str, Field(max_length=50)]] | None = Field(default=None, max_length=M.MAX_ASSIGNMENTS)


# ---------------------------------------------------------------------------------------------- helpers
def _rt(request: Request) -> Any:
    return request.app.state.runtime


def _store(request: Request) -> Any:
    store = getattr(_rt(request), "store", None)
    if store is None:
        raise HTTPException(503, "settings store unavailable")
    return store


def _service(request: Request) -> Any:
    svc = getattr(_rt(request), "controls", None)
    if svc is None:
        raise HTTPException(503, "controls unavailable")
    return svc


def _cat() -> Catalog:
    return load_catalog()


def _422(e: Exception) -> HTTPException:
    return HTTPException(422, str(e))


def _driver_row(request: Request, driver_id: int | None) -> dict[str, Any] | None:
    if driver_id is None:
        return None
    try:
        with _rt(request).db.read() as c:
            row = repo.get_driver(c, driver_id)
    except sqlite3.OperationalError:
        return {"id": driver_id, "name": None, "preferences": {}}
    if row is None:
        raise HTTPException(404, f"unknown driver {driver_id}")
    return row


def _skill_preset(row: dict[str, Any] | None) -> str:
    prefs = (row or {}).get("preferences") or {}
    return "beginner" if prefs.get("skill_level") == "beginner" else "advanced"


def _seated(request: Request) -> int | None:
    v = getattr(getattr(_rt(request), "drivers", None), "active_id", None)
    return v if isinstance(v, int) else None


def _rig(request: Request) -> tuple[str | None, str | None]:
    """The rig profile's (platform, rim), via the rig module's lenient parser - but only the keys the stored section
    holds: ``RigProfile`` defaults to the owner's own rig (PS5, GT DD Pro), which a new household doesn't have."""
    from pitwall.rig.recommend import RigProfile

    try:
        raw = _store(request).get("rig")
        if not isinstance(raw, dict) or not raw:
            return None, None
        p = RigProfile.from_stored(raw)
    except Exception:
        return None, None
    # a stored value the rig module rejected falls back to its default there: that is not this household's either
    return (p.platform if raw.get("platform") == p.platform else None), (p.rim if raw.get("rim") == p.rim else None)


def _setting_udp(request: Request) -> int:
    from pitwall.controls.ptt import setting_action

    settings = getattr(_rt(request), "settings", None)
    return setting_action(getattr(settings, "voice_ptt_button", None))


def _wheel_from_create(cat: Catalog, body: WheelCreate) -> M.WheelDef:
    now = time.time()
    start: M.WheelDef | None = None  # what the evidence is carried from: the template's draft, else nothing
    if body.template:
        if body.template not in cat.templates:
            raise HTTPException(404, f"unknown template {body.template!r}")
        w = template_wheel(cat, body.template, name=body.name, now=now)
        w = replace(w, rev=1)
        if body.controls is None and body.parts is None:
            return w
        start = w
        raw = {**w.to_dict(), "name": body.name}
    else:
        raw = {
            "id": M.new_wheel_id(),
            "rev": 1,
            "name": body.name,
            "template": None,
            "template_version": None,
            "shape": "round",
            "platforms": [],
            "parts": [{"id": "rim", "kind": "rim", "name": body.name}],
            "controls": [],
            "created_unix": now,
            "updated_unix": now,
        }
    if body.shape is not None:
        raw["shape"] = body.shape
    if body.platforms is not None:
        raw["platforms"] = list(body.platforms)
    if body.parts is not None:
        raw["parts"] = [p.model_dump() for p in body.parts]
    if body.controls is not None:
        raw["controls"] = [c.model_dump(exclude_none=False) for c in body.controls]
    try:
        made = M.parse_wheel(raw)
    except M.ControlsValidationError as e:
        raise _422(e) from e
    return _carry_evidence(made, start if start is not None else replace(made, controls=()), cat)


def _check_assignments(cat: Catalog, game: str, wheel: M.WheelDef, asg: list[M.Assignment]) -> None:
    """What the game can do: a known function of the game, an action it has, nothing on a button that the game keeps
    in a menu or on its MFD pages, and UDP Actions only for Talk to Pitwall in F1 25."""
    g = cat.games.get(game)
    label = g.label if g is not None else "This game"
    for a in asg:
        if a.function not in cat.functions:
            raise HTTPException(422, f"{a.key}: {a.function!r} is not a function Pitwall knows")
        if a.udp_action is not None and (a.function != PTT_FUNCTION or g is None or g.button_path != "f1_butn"):
            raise HTTPException(422, f"{a.key}: UDP Actions are only for Talk to Pitwall in F1 25")
        if a.function == PTT_FUNCTION:
            if (g is None or g.button_path != "f1_butn") and (a.control_id is not None or a.udp_action is not None):
                raise HTTPException(422, f"{label} doesn't send button presses: Talk to Pitwall can't go on the wheel")
            if a.action != "hold":
                raise HTTPException(422, f"{a.key}: Talk to Pitwall is held, so its action is hold")
            continue
        if g is not None and a.function not in g.functions:
            raise HTTPException(422, f"{a.key}: {g.label} has no {in_sentence(cat.label(a.function))}")
        row = g.functions[a.function] if g is not None else other_rows(cat, [a.function]).get(a.function)
        if a.origin == "game_fixed":
            fixed = any(
                fx.game == game and fx.template == wheel.template and fx.controls.get(a.function) == a.control_id
                for fx in cat.fixed_by_game
            )
            if not fixed:
                raise HTTPException(422, f"{a.key}: {label} doesn't fix this on {wheel.name}")
            continue
        if row is not None and (row.binding in ("menu", "none", "mfd") or row.in_race in ("no", "pause_menu")):
            where = "on its MFD pages" if row.binding == "mfd" else "in a menu"
            raise HTTPException(422, f"{a.key}: in {label} this is changed {where}, so it can't go on a button")
        if a.action not in allowed_actions(cat, a.function, row):
            raise HTTPException(422, f"{a.key}: {label} has no {a.action!r} for {in_sentence(cat.label(a.function))}")
    if g is not None:  # one button for both in the game (GT7: DRS is the Overtake button)
        on: dict[str, set[str | None]] = {}
        for a in asg:
            on.setdefault(a.function, set()).add(a.control_id)
        for fn, ctls in on.items():
            row = g.functions.get(fn)
            if row is not None and row.always_shared and row.shares_with:
                host = on.get(row.shares_with[0])
                if host is not None and ctls != host:
                    raise HTTPException(
                        422,
                        f"In {g.label}, {in_sentence(cat.label(fn))} uses the {cat.label(row.shares_with[0])} button: "
                        "put them on the same control.",
                    )


def _assignments(items: list[AssignmentIn]) -> list[M.Assignment]:
    out: list[M.Assignment] = []
    for i, a in enumerate(items):
        try:
            out.append(M.parse_assignment(a.model_dump(), f"assignments[{i}]"))
        except M.ControlsValidationError as e:
            raise _422(e) from e
    return out


def _rec_for_layout(request: Request, cat: Catalog, state: M.ControlsState, lay: M.Layout) -> Recommendation | None:
    wheel = state.wheel(lay.wheel_id)
    if wheel is None:
        return None
    try:
        return recommend(
            cat,
            wheel,
            lay.game,
            lay.platform,
            lay.preset,
            [],
            udp_action=_setting_udp(request),
            other_functions=lay.other_functions or (),
            game_name=lay.game_name,
        )
    except KeyError:
        return None


def _owner_ok(request: Request, owner: str | int) -> None:
    if owner != "household":
        _driver_row(request, int(owner))


# ---------------------------------------------------------------------------------------------- catalogue
@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    return _cat().to_api()


@router.get("/templates/{template_id}")
def get_template(template_id: Annotated[str, Path(pattern=r"^[a-z0-9_]{1,64}$")]) -> dict[str, Any]:
    cat = _cat()
    if template_id not in cat.templates:
        raise HTTPException(404, f"unknown template {template_id!r}")
    from pitwall.controls.templates import virtual_wheel_id

    w = template_wheel(cat, template_id, wheel_id=virtual_wheel_id(template_id), now=0.0)
    return w.to_dict()


# ---------------------------------------------------------------------------------------------- state
@router.get("/state")
def get_state(request: Request, driver_id: int | None = None) -> dict[str, Any]:
    cat = _cat()
    state = M.load_state(_store(request))
    did = driver_id if driver_id is not None else _seated(request)
    row = _driver_row(request, did) if did is not None else None
    sel = getattr(_rt(request).live, "game_selection", None)
    entry = games.entry(sel.id) if sel is not None else None
    cgame = cat.game_for_key(entry.game_key) if entry is not None else None
    rig_platform, rig_rim = _rig(request)
    platform = entry.platform if entry is not None and entry.platform in M.PLATFORMS else rig_platform
    dw = default_wheel(state, did, rig_rim)
    dc = state.driver(did)
    ptt = _service(request).ptt_now()
    return {
        **state.to_section(),
        "ptt": ptt,
        "defaults": {
            "driver_id": did,
            "game": cgame.id if cgame is not None else None,
            "platform": platform if platform in M.PLATFORMS else None,
            "wheel_id": dw.wheel_id,
            "template": dw.template,
            "preset": dc.preset or state.household.preset or _skill_preset(row),
        },
    }


# ---------------------------------------------------------------------------------------------- wheels
@router.post("/wheels", status_code=201)
def create_wheel(request: Request, body: WheelCreate) -> dict[str, Any]:
    cat = _cat()
    wheel = _wheel_from_create(cat, body)
    store = _store(request)
    with M.write_lock:
        state = M.load_state(store)
        try:
            state = state.with_wheel(wheel)
        except M.ControlsValidationError as e:
            raise HTTPException(409, str(e)) from e
        M.save_state(store, state)
    return wheel.to_dict()


def _same_signal(a: M.Signal | None, b: M.Signal | None) -> bool:
    if a is None or b is None:
        return False
    return (a.kind, a.value, dict(a.per_slot)) == (b.kind, b.value, dict(b.per_slot))


def _carry_evidence(new: M.WheelDef, cur: M.WheelDef, cat: Catalog) -> M.WheelDef:
    """Evidence is never taken from the client: an unchanged control or signal keeps what was stored (or the
    template's research letter); anything changed is your entry (H). "Seen by Pitwall" comes only from Identify."""
    tmpl = cat.templates.get(new.template or "")
    tmpl_controls = {c.id: c for c in tmpl.controls} if tmpl is not None else {}
    out: list[M.WheelControl] = []
    for c in new.controls:
        old = cur.control(c.id)
        base = tmpl_controls.get(c.id)
        if old is not None and old.kind == c.kind:
            ev: M.Evidence = old.evidence
        elif base is not None and base.kind == c.kind:
            ev = base.evidence
        else:
            ev = "H"
        sigs: dict[str, M.Signal] = {}
        for plat, sig in c.signals.items():
            prev = old.signals.get(plat) if old is not None else None
            orig = base.signals.get(plat) if base is not None and base.kind == c.kind else None
            if _same_signal(sig, prev) and prev is not None:
                sigs[plat] = prev
            elif _same_signal(sig, orig) and orig is not None:
                sigs[plat] = orig
            else:
                sigs[plat] = replace(sig, evidence="H", seen=None, source_ids=())
        out.append(replace(c, evidence=ev, signals=sigs))
    return replace(new, controls=tuple(out))


@router.put("/wheels/{wheel_id}")
def put_wheel(request: Request, wheel_id: WheelId, body: WheelPut) -> dict[str, Any]:
    store = _store(request)
    with M.write_lock:
        state = M.load_state(store)
        cur = state.wheel(wheel_id)
        if cur is None:
            raise HTTPException(404, f"unknown wheel {wheel_id}")
        if body.rev != cur.rev:
            raise HTTPException(409, f"{cur.name} was changed elsewhere (rev {cur.rev}): reload and try again")
        raw = body.model_dump(exclude={"id", "created_unix", "updated_unix"})
        raw.update({"id": wheel_id, "rev": cur.rev + 1, "created_unix": cur.created_unix, "updated_unix": time.time()})
        try:
            wheel = _carry_evidence(M.parse_wheel(raw), cur, _cat())
        except M.ControlsValidationError as e:
            raise _422(e) from e
        cat = _cat()
        for lay in state.layouts_using(wheel_id):
            try:
                M.check_layout_against_wheel(lay, wheel)
            except M.ControlsValidationError as e:
                g = cat.games.get(lay.game)
                game = g.label if g is not None else (lay.game_name or lay.game)
                plat = {"ps5": "PS5", "ps4": "PS4", "xbox": "Xbox", "pc": "PC"}.get(lay.platform, lay.platform)
                raise HTTPException(
                    409, f"Your {game} layout on {plat} ({lay.id}) uses this: {e}. Change that layout first."
                ) from e
        M.save_state(store, state.with_wheel(wheel))
    return wheel.to_dict()


@router.delete("/wheels/{wheel_id}")
def delete_wheel(request: Request, wheel_id: WheelId) -> dict[str, Any]:
    store = _store(request)
    with M.write_lock:
        state = M.load_state(store)
        if state.wheel(wheel_id) is None:
            raise HTTPException(404, f"unknown wheel {wheel_id}")
        using = state.layouts_using(wheel_id)
        if using:
            names = ", ".join(f"{x.game} on {x.platform} ({x.id})" for x in using)
            raise HTTPException(409, f"Layouts use this wheel: {names}. Delete them first.")
        M.save_state(store, state.without_wheel(wheel_id))
    return {"deleted": wheel_id}


@router.get("/wheels/{wheel_id}/export")
def export_wheel(request: Request, wheel_id: WheelId) -> dict[str, Any]:
    state = M.load_state(_store(request))
    w = state.wheel(wheel_id)
    if w is None:
        raise HTTPException(404, f"unknown wheel {wheel_id}")
    return {"schema": EXPORT_SCHEMA, "exported_unix": time.time(), "wheel": w.to_dict()}


@router.post("/wheels/import", status_code=201)
def import_wheel(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """A wheel file from ``export``: new id, rev 1; evidence becomes H (your entry) except fields carried over from
    the template it started from (those keep the research letter)."""
    if len(json.dumps(body)) > 400_000:
        raise HTTPException(422, "the file is too large")
    if body.get("schema") != EXPORT_SCHEMA or not isinstance(body.get("wheel"), dict):
        raise HTTPException(422, f"not a Pitwall wheel file (expected schema {EXPORT_SCHEMA})")
    cat = _cat()
    raw = dict(body["wheel"])
    now = time.time()
    tmpl = cat.templates.get(str(raw.get("template") or ""))
    tmpl_controls = {c.id: c for c in tmpl.controls} if tmpl is not None else {}
    controls = []
    raw_controls = raw.get("controls") or []
    if not isinstance(raw_controls, list):
        raise HTTPException(422, "controls: expected a list")
    for c in raw_controls:
        if not isinstance(c, dict):
            raise HTTPException(422, "controls: expected objects")
        c = dict(c)
        base = tmpl_controls.get(str(c.get("id")))
        same = base is not None and base.kind == c.get("kind")
        c["evidence"] = base.evidence if same and base is not None else "H"
        sigs = {}
        raw_sigs = c.get("signals") or {}
        if not isinstance(raw_sigs, dict):
            raise HTTPException(422, "signals: expected an object of platform -> signal")
        for p, s in raw_sigs.items():
            if not isinstance(s, dict):
                raise HTTPException(422, "signals: expected objects")
            bs = base.signals.get(p) if same and base is not None else None
            keep = bs is not None and bs.kind == s.get("kind") and bs.value == s.get("value")
            sigs[p] = {
                **s,
                "evidence": bs.evidence if keep and bs is not None else "H",
                "seen": None,
                "source_ids": list(bs.source_ids) if keep and bs is not None else [],
            }
        c["signals"] = sigs
        controls.append(c)
    raw.update({"id": M.new_wheel_id(), "rev": 1, "controls": controls, "created_unix": now, "updated_unix": now})
    try:
        wheel = M.parse_wheel(raw)
    except M.ControlsValidationError as e:
        raise _422(e) from e
    store = _store(request)
    with M.write_lock:
        state = M.load_state(store)
        try:
            state = state.with_wheel(wheel)
        except M.ControlsValidationError as e:
            raise HTTPException(409, str(e)) from e
        M.save_state(store, state)
    return wheel.to_dict()


SEEN_WINDOW_S = 120.0  # Identify: the press must be this recent


def _evidence_checked(request: Request, platform: str, sig: M.Signal) -> M.Signal:
    """What you type is your entry (H). "Seen by Pitwall" only when the probe saw that pad button pressed from F1 25
    live, sent by a console or another PC (not this computer), in the last two minutes; the press it saw is kept."""
    if sig.evidence != "seen":
        return replace(sig, evidence="H", seen=None, source_ids=())
    cat = _cat()
    pd = cat.pad_def(platform, sig.value) if sig.kind == "pad" and not sig.per_slot else None
    if pd is None or pd.bit is None:
        raise HTTPException(422, "Only one console button that F1 25 reports can be saved as seen by Pitwall.")
    probe = _service(request).probe
    now = time.time()
    hit = next(
        (
            e
            for e in reversed(probe.since(max(0, probe.seq - 64)))
            if e.origin == "live" and e.pressed & pd.bit and now - e.t_unix <= SEEN_WINDOW_S
        ),
        None,
    )
    if hit is None:
        raise HTTPException(
            409,
            f"Pitwall hasn't seen {pd.label} pressed from F1 25 on your console or PC in the last two minutes. "
            "Press the control again with F1 25 sending telemetry.",
        )
    plat = sig.seen.platform if sig.seen is not None else {"ps": "ps5", "xbox": "xbox", "pc": "pc"}[platform]
    seen = M.Seen(hit.t_unix, tuple(button_names(hit.pressed)), "f1_25", plat)
    return replace(sig, seen=seen, source_ids=())


@router.put("/wheels/{wheel_id}/controls/{control_id}/signal")
def put_signal(request: Request, wheel_id: WheelId, control_id: ControlId, body: SignalPut) -> dict[str, Any]:
    store = _store(request)
    with M.write_lock:
        state = M.load_state(store)
        w = state.wheel(wheel_id)
        if w is None:
            raise HTTPException(404, f"unknown wheel {wheel_id}")
        c = w.control(control_id)
        if c is None:
            raise HTTPException(404, f"{w.name} has no control {control_id!r}")
        if body.rev is not None and body.rev != w.rev:
            raise HTTPException(409, f"{w.name} was changed elsewhere (rev {w.rev}): reload and try again")
        try:
            sig = M.parse_signal(body.signal.model_dump(), "signal")
            for slot in sig.per_slot:
                if not M.valid_slot(c.kind, slot, c.positions):
                    raise M.ControlsValidationError(f"signal.per_slot: {slot!r} is not a slot of {c.label}")
        except M.ControlsValidationError as e:
            raise _422(e) from e
        sig = _evidence_checked(request, body.platform, sig)
        nc = replace(c, signals={**c.signals, body.platform: sig})
        nw = replace(
            w,
            controls=tuple(nc if x.id == control_id else x for x in w.controls),
            rev=w.rev + 1,
            updated_unix=time.time(),
        )
        M.save_state(store, state.with_wheel(nw))
    return nw.to_dict()


# ---------------------------------------------------------------------------------------------- recommendation
@router.get("/recommendation")
def get_recommendation(
    request: Request,
    game: Annotated[str, Query(pattern=r"^[a-z0-9_]{1,32}$")],
    platform: Literal["ps5", "ps4", "xbox", "pc"],
    wheel_id: Annotated[str | None, Query(max_length=64)] = None,
    template: Annotated[str | None, Query(max_length=64)] = None,
    driver_id: int | None = None,
    preset: Literal["beginner", "advanced"] | None = None,
    game_name: Annotated[str | None, Query(max_length=M.MAX_NAME)] = None,
    functions: Annotated[str | None, Query(max_length=800)] = None,
) -> dict[str, Any]:
    cat = _cat()
    if game != "other" and game not in cat.games:
        raise HTTPException(404, f"unknown game {game!r}")
    state = M.load_state(_store(request))
    try:
        wheel = resolve_wheel(cat, state, wheel_id, template)
    except M.NotFound as e:
        raise HTTPException(404, str(e.args[0] if e.args else e)) from e
    row = _driver_row(request, driver_id)
    dc = state.driver(driver_id)
    level = preset or dc.preset or state.household.preset or _skill_preset(row)
    existing = state.layout_for(driver_id, game, platform)
    kept: list[M.Assignment] = []
    udp = _setting_udp(request)
    if existing is not None and existing.wheel_id == wheel.id:
        kept = [a for a in existing.assignments if a.origin == "kept"]
        udp = next((a.udp_action for a in existing.assignments if a.function == PTT_FUNCTION and a.udp_action), udp)
    other = [f for f in (functions or "").split(",") if f] if game == "other" else []
    rec = recommend(
        cat,
        wheel,
        game,
        platform,
        level,
        kept,
        driver_id=driver_id,
        udp_action=udp,
        other_functions=other,
        game_name=game_name,
    )
    return rec.to_dict()


# ---------------------------------------------------------------------------------------------- layouts
def _new_layout(request: Request, cat: Catalog, state: M.ControlsState, body: LayoutCreate) -> M.Layout:
    if body.game != "other" and body.game not in cat.games:
        raise HTTPException(404, f"unknown game {body.game!r}")
    wheel = state.wheel(body.wheel_id)
    if wheel is None:
        raise HTTPException(404, f"unknown wheel {body.wheel_id}: save the wheel first")
    _owner_ok(request, body.owner)
    given = _assignments(body.assignments or [])
    if body.from_recommendation:
        kept = [a for a in given if a.origin == "kept"]
        udp = next((a.udp_action for a in kept if a.function == PTT_FUNCTION and a.udp_action), _setting_udp(request))
        rec = recommend(
            cat,
            wheel,
            body.game,
            body.platform,
            body.preset,
            kept,
            udp_action=udp,
            other_functions=body.other_functions or (),
            game_name=body.game_name,
        )
        asg = list(rec.plain_assignments())
    else:
        asg = given
    _check_assignments(cat, body.game, wheel, asg)
    now = time.time()
    raw = {
        "id": M.new_layout_id(),
        "rev": 1,
        "game": body.game,
        "game_name": body.game_name,
        "platform": body.platform,
        "wheel_id": body.wheel_id,
        "owner": body.owner,
        "preset": body.preset,
        "other_functions": body.other_functions if body.game == "other" else None,
        "assignments": [a.to_dict() for a in asg],
        "created_unix": now,
        "updated_unix": now,
    }
    try:
        lay = M.parse_layout(raw)
        M.check_layout_against_wheel(lay, wheel)
    except M.ControlsValidationError as e:
        raise _422(e) from e
    return lay


@router.post("/layouts", status_code=201)
def create_layout(request: Request, body: LayoutCreate) -> dict[str, Any]:
    cat = _cat()
    store = _store(request)
    with M.write_lock:
        state = M.load_state(store)
        lay = _new_layout(request, cat, state, body)
        try:
            state = state.with_layout(lay)
        except M.ControlsValidationError as e:
            raise HTTPException(409, str(e)) from e
        M.save_state(store, state.with_owner_choice(lay))
    return lay.to_dict()


@router.put("/layouts/{layout_id}")
def put_layout(request: Request, layout_id: LayoutId, body: LayoutPut) -> dict[str, Any]:
    cat = _cat()
    store = _store(request)
    with M.write_lock:
        state = M.load_state(store)
        cur = state.layout(layout_id)
        if cur is None:
            raise HTTPException(404, f"unknown layout {layout_id}")
        if body.rev != cur.rev:
            raise HTTPException(409, f"This layout was changed elsewhere (rev {cur.rev}): reload and try again")
        wheel = state.wheel(cur.wheel_id)
        if wheel is None:
            raise HTTPException(404, f"the layout's wheel {cur.wheel_id} is gone")
        asg = _assignments(body.assignments) if body.assignments is not None else list(cur.assignments)
        _check_assignments(cat, cur.game, wheel, asg)
        owner = body.owner if body.owner is not None else cur.owner
        _owner_ok(request, owner)
        raw = {
            **cur.to_dict(),
            "rev": cur.rev + 1,
            "preset": body.preset or cur.preset,
            "owner": owner,
            "game_name": body.game_name if body.game_name is not None else cur.game_name,
            "other_functions": body.other_functions
            if body.other_functions is not None
            else (list(cur.other_functions) if cur.other_functions is not None else None),
            "assignments": [a.to_dict() for a in asg],
            "updated_unix": time.time(),
        }
        try:
            lay = M.parse_layout(raw)
            M.check_layout_against_wheel(lay, wheel)
        except M.ControlsValidationError as e:
            raise _422(e) from e
        state = state.with_layout(lay)
        if owner != cur.owner:  # the old owner's choice no longer points at it; the new owner's does
            old = state.household if cur.owner == "household" else state.driver(cur.owner)
            kept = M.DriverControls(old.wheel_id, old.preset, {k: v for k, v in old.layouts.items() if v != lay.id})
            state = replace(state, household=kept) if cur.owner == "household" else state.with_driver(cur.owner, kept)
            state = state.with_owner_choice(lay)
        M.save_state(store, state)
    return lay.to_dict()


@router.delete("/layouts/{layout_id}")
def delete_layout(request: Request, layout_id: LayoutId) -> dict[str, Any]:
    store = _store(request)
    with M.write_lock:
        state = M.load_state(store)
        if state.layout(layout_id) is None:
            raise HTTPException(404, f"unknown layout {layout_id}")
        M.save_state(store, state.without_layout(layout_id))
    return {"deleted": layout_id}


def _layout_and_wheel(request: Request, layout_id: str) -> tuple[M.ControlsState, M.Layout, M.WheelDef]:
    state = M.load_state(_store(request))
    lay = state.layout(layout_id)
    if lay is None:
        raise HTTPException(404, f"unknown layout {layout_id}")
    wheel = state.wheel(lay.wheel_id)
    if wheel is None:
        raise HTTPException(404, f"the layout's wheel {lay.wheel_id} is gone")
    return state, lay, wheel


@router.get("/layouts/{layout_id}/guide")
def get_guide(
    request: Request, layout_id: LayoutId, platform: Literal["ps5", "ps4", "xbox", "pc"] | None = None
) -> dict[str, Any]:
    _state, lay, wheel = _layout_and_wheel(request, layout_id)
    return guide(
        _cat(),
        lay.game,
        platform or lay.platform,
        wheel,
        lay.assignments,
        game_name=lay.game_name,
        other_functions=lay.other_functions or (),
    )


def _driver_name(request: Request, driver_id: int | None) -> str | None:
    row = _driver_row(request, driver_id) if driver_id is not None else None
    name = (row or {}).get("name")
    return str(name) if name else None


@router.get("/layouts/{layout_id}/card.html", response_class=HTMLResponse)
def get_card_html(request: Request, layout_id: LayoutId, driver_id: int | None = None) -> HTMLResponse:
    cat = _cat()
    state, lay, wheel = _layout_and_wheel(request, layout_id)
    body = card_html(
        cat, lay, wheel, _rec_for_layout(request, cat, state, lay), driver_name=_driver_name(request, driver_id)
    )
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/layouts/{layout_id}/card.txt", response_class=PlainTextResponse)
def get_card_txt(request: Request, layout_id: LayoutId, driver_id: int | None = None) -> PlainTextResponse:
    cat = _cat()
    state, lay, wheel = _layout_and_wheel(request, layout_id)
    body = card_text(
        cat, lay, wheel, _rec_for_layout(request, cat, state, lay), driver_name=_driver_name(request, driver_id)
    )
    return PlainTextResponse(body, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------------------------- drivers
@router.put("/drivers/{driver_id}")
def put_driver(
    request: Request, driver_id: Annotated[str, Path(pattern=r"^(household|[1-9]\d{0,9})$")], body: DriverPut
) -> dict[str, Any]:
    store = _store(request)
    sent = body.model_fields_set
    with M.write_lock:
        state = M.load_state(store)
        if driver_id != "household":
            _driver_row(request, int(driver_id))
        cur = state.household if driver_id == "household" else state.driver(driver_id)
        if "wheel_id" in sent and body.wheel_id is not None and state.wheel(body.wheel_id) is None:
            raise HTTPException(404, f"unknown wheel {body.wheel_id}")
        layouts = dict(cur.layouts)
        for k, v in (body.layouts or {}).items():
            game, _, platform = k.partition(":")
            if not game or platform not in M.PLATFORMS:
                raise HTTPException(422, f"{k!r}: expected <game>:<platform>")
            if v is None:
                layouts.pop(k, None)
                continue
            lay = state.layout(v)
            if lay is None:
                raise HTTPException(404, f"unknown layout {v}")
            if lay.slot_key != k:
                raise HTTPException(422, f"{v} is a layout for {lay.slot_key}, not {k}")
            layouts[k] = v
        new = M.DriverControls(
            body.wheel_id if "wheel_id" in sent else cur.wheel_id,
            body.preset if "preset" in sent else cur.preset,
            layouts,
        )
        state = replace(state, household=new) if driver_id == "household" else state.with_driver(driver_id, new)
        state = M.save_state(store, state)
    return {"driver_id": driver_id, **new.to_dict()}


# ---------------------------------------------------------------------------------------------- test
@router.post("/test", status_code=201)
def start_test(request: Request, body: TestStart) -> dict[str, Any]:
    cat = _cat()
    svc = _service(request)
    lay: M.Layout | None = None
    wheel: M.WheelDef | None = None
    items: list[TestItem]
    if body.layout_id is not None:
        _state, lay, wheel = _layout_and_wheel(request, body.layout_id)
        game = cat.games.get(lay.game)
        if game is None or game.button_path != "f1_butn":
            label = game.label if game is not None else (lay.game_name or "This game")
            raise HTTPException(422, NO_BUTTONS.format(game=label))
    if body.mode == "identify":
        items = [TestItem("identify", "identify", "Press a control on your wheel on its own, twice.", {})]
    else:
        if lay is None:
            raise HTTPException(422, "Pick a saved F1 25 layout to test.")
        items = build_items(lay, wheel, cat.label)
        if body.keys is not None:
            want = set(body.keys)
            items = [it for it in items if it.key in want]
        if not items:
            raise HTTPException(422, "This layout has no UDP Action or brake bias / ERS buttons to test.")
    try:
        return dict(svc.tests.start(lay, items))
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e


@router.get("/test")
def get_test(request: Request) -> dict[str, Any] | None:
    out = _service(request).tests.poll()
    return None if out is None else dict(out)


@router.post("/test/{test_id}/skip")
def skip_test_item(request: Request, test_id: TestId) -> dict[str, Any]:
    try:
        return dict(_service(request).tests.skip(test_id))
    except KeyError as e:
        raise HTTPException(404, "no such test running") from e


@router.post("/test/{test_id}/stop")
def stop_test(request: Request, test_id: TestId) -> dict[str, Any]:
    try:
        out = _service(request).tests.stop(test_id)
    except KeyError as e:
        raise HTTPException(404, "no such test running") from e
    return {"stopped": test_id, "test": out}


@router.get("/buttons")
def get_buttons(request: Request, since: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
    probe = _service(request).probe
    events = probe.since(since) if since else probe.since(max(0, probe.seq - 20))
    return {"seq": probe.seq, "presses": [e.to_dict() for e in events]}
