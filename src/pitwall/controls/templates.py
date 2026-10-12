"""Wheel templates: research templates normalised into ``WheelDef`` drafts, and which wheel a page opens on.

Completeness (catalogue): ``full`` = controls plus signals (a maker's table), ``controls`` = kinds and positions but no
signals, ``counts`` = numbers only (generic "Button 1..n" in zone ``unplaced``). Every field keeps the template's
evidence letter; research text that is a guess became signal ``unknown`` with the text in the control's note.

Default wheel for a driver (spec 2.5): the driver's ``wheel_id`` -> the household's -> a virtual (unsaved) wheel
from the rig profile (rim ``gt_dd_pro_bundled`` -> ``fanatec_gt_dd_pro_wheel``) -> none ("Pick your wheel"). The
rig's ``rim`` enum is not changed.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from pitwall.controls.catalog import Catalog
from pitwall.controls.model import ControlsState, NotFound, WheelDef, new_wheel_id

RIM_TEMPLATES = {"gt_dd_pro_bundled": "fanatec_gt_dd_pro_wheel"}  # rig profile rim -> controls template
SHORT_NAMES = {
    "fanatec_gt_dd_pro_wheel": "GT DD Pro wheel",
    "fanatec_csl_elite_mclaren_gt3_v2": "McLaren GT3 V2",
    "fanatec_cs_formula_v25": "Formula V2.5",
    "fanatec_csl_p1_v2": "CSL P1 V2",
    "fanatec_csl_elite_wrc": "CSL Elite WRC",
    "fanatec_cs_f1_esports_v2": "F1 Esports V2",
    "fanatec_podium_button_module_rally": "Button Module Rally",
    "logitech_g923_ps": "G923 (PS)",
    "logitech_g923_xbox": "G923 (Xbox)",
    "logitech_pro_racing_wheel_xbox": "PRO Racing Wheel",
    "logitech_rs_wheel_hub": "RS Wheel Hub",
    "thrustmaster_t248": "T248",
    "thrustmaster_t_gt_ii": "T-GT II",
    "thrustmaster_sf1000_addon": "SF1000 add-on",
    "thrustmaster_ts_pc_racer": "TS-PC Racer wheel",
    "moza_es_esx": "MOZA ES / ESX",
    "moza_cs_v2p": "MOZA CS V2P",
    "moza_gs_v2p": "MOZA GS V2P",
    "moza_ks": "MOZA KS",
    "moza_fsr2": "MOZA FSR2",
    "simagic_gt_neo": "Simagic GT NEO",
    "simucube_tahko_gt21": "Tahko GT-21",
    "cammus_c12": "Cammus C12",
    "custom": "My wheel",
}


def virtual_wheel_id(template_id: str) -> str:
    """A stable id for an unsaved template wheel (so a recommendation of the draft is reproducible)."""
    return "w_" + hashlib.sha1(template_id.encode()).hexdigest()[:8]


def template_wheel(
    cat: Catalog, template_id: str, *, wheel_id: str | None = None, name: str | None = None, now: float | None = None
) -> WheelDef:
    """The template expanded to a ``WheelDef`` draft (rev 0 until saved)."""
    t = cat.templates.get(template_id)
    if t is None:
        raise NotFound(f"unknown template {template_id!r}")
    ts = time.time() if now is None else now
    return WheelDef(
        id=wheel_id or new_wheel_id(),
        rev=0,
        name=(name or SHORT_NAMES.get(template_id) or t.name)[:40],
        template=template_id,
        template_version=cat.version,
        shape=t.shape,
        platforms=t.signal_platforms,
        parts=t.parts,
        controls=t.controls,
        created_unix=ts,
        updated_unix=ts,
    )


@dataclass(frozen=True, slots=True)
class DefaultWheel:
    wheel_id: str | None  # a saved wheel
    template: str | None  # else a template to start from (unsaved)
    source: str  # "driver" | "household" | "rig" | "none"


def default_wheel(state: ControlsState, driver_id: int | None, rig_rim: str | None) -> DefaultWheel:
    for source, dc in (("driver", state.driver(driver_id)), ("household", state.household)):
        if dc.wheel_id is not None and state.wheel(dc.wheel_id) is not None:
            return DefaultWheel(dc.wheel_id, None, source)
    tid = RIM_TEMPLATES.get(rig_rim or "")
    if tid is not None:
        return DefaultWheel(None, tid, "rig")
    return DefaultWheel(None, None, "none")


def resolve_wheel(cat: Catalog, state: ControlsState, wheel_id: str | None, template: str | None) -> WheelDef:
    """A saved wheel by id, else a template draft (stable virtual id). ``NotFound`` when neither exists."""
    if wheel_id:
        w = state.wheel(wheel_id)
        if w is not None:
            return w
        if wheel_id in cat.templates:  # a template id given where a wheel id was expected
            return template_wheel(cat, wheel_id, wheel_id=virtual_wheel_id(wheel_id), now=0.0)
        raise NotFound(f"unknown wheel {wheel_id!r}")
    if template:
        return template_wheel(cat, template, wheel_id=virtual_wheel_id(template), now=0.0)
    raise NotFound("no wheel: pick your wheel or a template")
