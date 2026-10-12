"""Shared helpers for the Setup › Controls tests: wheels, a compact recommendation summary and golden files.

Golden files live in ``tests/fixtures/controls/``. They are written only when ``UPDATE_CONTROLS_GOLDEN=1`` is set (then
review the diff by hand); otherwise a test compares against them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pitwall.controls.catalog import Catalog, load_catalog
from pitwall.controls.model import WheelDef, parse_wheel
from pitwall.controls.recommend import Recommendation
from pitwall.controls.templates import template_wheel, virtual_wheel_id

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "controls"
CAT: Catalog = load_catalog()


def tmpl(tid: str) -> WheelDef:
    return template_wheel(CAT, tid, wheel_id=virtual_wheel_id(tid), now=0.0)


def custom_acc_wheel() -> WheelDef:
    """A home-made PC box: two encoders and eight buttons (four by each thumb), PC button numbers known."""
    controls: list[dict[str, Any]] = [
        {
            "id": "enc_l",
            "kind": "encoder",
            "label": "Left encoder",
            "zone": "left_thumb",
            "order": 0,
            "signals": {"pc": {"kind": "hid_button", "value": "1/2", "evidence": "H"}},
        },
        {
            "id": "enc_r",
            "kind": "encoder",
            "label": "Right encoder",
            "zone": "right_thumb",
            "order": 0,
            "signals": {"pc": {"kind": "hid_button", "value": "3/4", "evidence": "H"}},
        },
    ]
    for i in range(8):
        zone = "left_thumb" if i < 4 else "right_thumb"
        controls.append(
            {
                "id": f"b{i + 1}",
                "kind": "button",
                "label": f"Button {i + 1}",
                "zone": zone,
                "order": i + 1,
                "signals": {"pc": {"kind": "hid_button", "value": str(5 + i), "evidence": "H"}},
            }
        )
    return parse_wheel(
        {
            "id": "w_0000acc1",
            "rev": 1,
            "name": "Home-made box",
            "shape": "box",
            "platforms": ["pc"],
            "parts": [{"id": "rim", "kind": "button_box", "name": "Box"}],
            "controls": controls,
        }
    )


def summary(rec: Recommendation) -> dict[str, Any]:
    """What a golden file pins: where each function goes, push-to-talk, and the lists - not the wording."""
    return {
        "assignments": [
            f"{a.assignment.key} -> {a.assignment.control_id}:{a.assignment.slot} ({a.assignment.origin}, "
            f"ev {a.evidence})"
            for a in rec.assignments
        ],
        "pitwall_ptt": {k: v for k, v in rec.pitwall_ptt.items() if k != "text"},
        "not_on_wheel": [f"{x['function']} ({x['why']})" for x in rec.not_on_wheel],
        "not_in_game": [x["function"] for x in rec.not_in_game],
        "unplaced": [x["function"] for x in rec.unplaced],
        "reserved": [f"{x['control_id']} ({x['as']})" for x in rec.reserved],
    }


def golden(name: str, data: Any) -> Any:
    """The stored golden value (written first when ``UPDATE_CONTROLS_GOLDEN=1``)."""
    path = GOLDEN / f"{name}.json"
    if os.environ.get("UPDATE_CONTROLS_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))
