"""The printable controls card (server-rendered HTML, A4 landscape, no scripts) and its plain-text form.

Follows the ``digest.html`` precedent: ``GET /api/controls/layouts/{id}/card.html`` opens in a new tab (``?token=``
works for the access check), the browser prints it or saves it as PDF. Every name a driver typed is HTML-escaped. The
diagram uses the catalogue's geometry, the same boxes as the dashboard. The card says "Research only" and shows test
results with their dates; it never says "validated".
"""

from __future__ import annotations

import html
import time
from collections.abc import Mapping, Sequence
from typing import Any

from pitwall.controls.catalog import PTT_FUNCTION, Catalog, native_parts, split_name
from pitwall.controls.model import Assignment, Layout, WheelDef
from pitwall.controls.recommend import Recommendation

PLATFORM_LABELS = {"ps5": "PS5", "ps4": "PS4", "xbox": "Xbox", "pc": "PC"}
CHECK_WORDS = {
    "detected": "Seen by Pitwall",
    "effect_seen": "Seen by Pitwall",
    "other_bits": "Other buttons seen",
    "not_seen": "Not seen",
}


def _e(v: object) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _date(t: float) -> str:
    return time.strftime("%d %b %Y", time.localtime(t))


def _marker(cat: Catalog, a: Assignment) -> str:
    if a.function == PTT_FUNCTION:
        return "PITWALL"
    f = cat.functions.get(a.function)
    short = f.short if f is not None else a.function[:6].upper()
    return short + {"inc": "+", "dec": "−"}.get(a.action, "") + ("↻" if a.slot in ("cw", "ccw") else "")


def diagram_svg(cat: Catalog, wheel: WheelDef, assignments: Sequence[Assignment]) -> str:
    """The wheel outline, its zones and one marker per assigned control, stacked per zone. ``aria-hidden``: the
    table on the card is the readable version."""
    geo = cat.diagram
    shapes: Mapping[str, Any] = geo["shapes"]
    shape = shapes.get(wheel.shape) or shapes["round"]
    w, h = geo["viewbox"]
    by_control: dict[str, list[str]] = {}
    for a in assignments:
        if a.control_id is not None:
            by_control.setdefault(a.control_id, []).append(_marker(cat, a))
    parts = [
        f'<svg viewBox="0 0 {w} {h}" width="100%" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">',
        f'<path d="{_e(shape["outline"])}" fill="#f4f4f4" stroke="#333" stroke-width="2" fill-rule="evenodd"/>',
    ]
    zone_rows: dict[str, int] = {}
    for c in sorted(wheel.controls, key=lambda c: (c.zone, c.order)):
        marks = by_control.get(c.id)
        if not marks:
            continue
        x, y, zw, zh = shape["zones"][c.zone]
        row = zone_rows.get(c.zone, 0)
        zone_rows[c.zone] = row + 1
        ty = y + 12 + row * 13
        if ty > y + zh:
            continue  # a full zone: the table lists every control anyway
        text = f"{c.label[:12]}: {' '.join(dict.fromkeys(marks))}"
        fit = max(8, int((zw - 4) / 5.4))  # about 5.4 user units per character at font size 10
        # a white halo keeps the label readable where it crosses the wheel's outline
        font = (
            'font-size="10" font-weight="600" font-family="Helvetica, Arial, sans-serif" stroke="#fff" '
            'stroke-width="3" paint-order="stroke" stroke-linejoin="round"'
        )
        parts.append(
            f'<text x="{x + 2}" y="{ty}" {font}>{_e(text if len(text) <= fit else text[: fit - 1] + "…")}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _rows(cat: Catalog, layout: Layout, wheel: WheelDef, rec: Recommendation | None) -> list[tuple[str, ...]]:
    game = cat.games.get(layout.game)
    game_label = game.label if game is not None else (layout.game_name or "the game")
    out: list[tuple[str, ...]] = []
    menus: dict[tuple[str, str | None], list[str]] = {}  # a menu function's directions on one control: one row
    for a in layout.assignments:
        if a.action in ("up", "down", "left", "right", "select") and a.control_id is not None:
            menus.setdefault((a.function, a.control_id), []).append("push" if a.slot == "push" else str(a.slot))
    done: set[tuple[str, str | None]] = set()
    for a in layout.assignments:
        c = wheel.control(a.control_id)
        ctl = c.label if c is not None else ("(your button)" if a.function == PTT_FUNCTION else "-")
        group = (a.function, a.control_id)
        if group in menus:
            if group in done:
                continue
            done.add(group)
            ctl += f" ({', '.join(menus[group])})"
        elif c is not None and a.slot not in (None, "press"):
            ctl += f" ({a.slot})"
        label = "Talk to Pitwall" if a.function == PTT_FUNCTION else cat.label(a.function)
        label += {"inc": " +", "dec": " −"}.get(a.action, "")
        if a.function == PTT_FUNCTION and a.udp_action:
            native = f"UDP Action {a.udp_action}"
        else:
            row = game.functions.get(a.function) if game is not None else None
            native = native_parts(row, a.action)[0] if row is not None else ""
            if group in menus and row is not None and row.native_found:  # one row for a menu's directions
                native = split_name(row.native_name.split(";")[0])[0]
        check = ""
        if a.check is not None:
            check = f"{CHECK_WORDS.get(a.check.result, a.check.result)} {_date(a.check.t_unix)}"
        elif a.origin == "game_default":
            check = f"{game_label}'s own default"
        if a.origin == "game_fixed" and game is not None:
            fx = cat.fixed_for(game.id, wheel.template, a.function)
            label += " (set by the game; colour community-reported)" if fx is None or fx.evidence != "V" else ""
        out.append((ctl, label, native, check))
    return out


def _ptt_line(layout: Layout, wheel: WheelDef, rec: Recommendation | None) -> str | None:
    """From the saved layout (F1 25: the button and its UDP Action), else the recommendation's words (the iPad)."""
    a = next((x for x in layout.assignments if x.function == PTT_FUNCTION and x.udp_action), None)
    if a is not None:
        c = wheel.control(a.control_id)
        where = f"hold {c.label}" if c is not None else "hold your talk button"
        return (
            f"{where[0].upper() + where[1:]}: UDP Action {a.udp_action} in F1 25 (Controls, then your wheel's entry, "
            "then UDP Custom Actions)."
        )
    if rec is not None and rec.pitwall_ptt.get("path") == "screen":
        return str(rec.pitwall_ptt.get("text") or "") or None
    return None


def card_html(
    cat: Catalog,
    layout: Layout,
    wheel: WheelDef,
    rec: Recommendation | None,
    *,
    driver_name: str | None = None,
) -> str:
    game = cat.games.get(layout.game)
    game_label = game.label if game is not None else (layout.game_name or "Other game")
    title = " · ".join(
        x for x in ("Controls", driver_name, game_label, PLATFORM_LABELS.get(layout.platform), wheel.name) if x
    )
    rows = "".join("<tr>" + "".join(f"<td>{_e(v)}</td>" for v in r) + "</tr>" for r in _rows(cat, layout, wheel, rec))
    cant = ""
    if rec is not None:
        sections = (
            (f"Can't change while driving in {game_label}", rec.not_on_wheel),
            (f"Not in {game_label}", rec.not_in_game),
        )
        for heading, group in sections:
            texts = dict.fromkeys(x["text"] for x in group)  # one line per sentence
            if texts:
                cant += f"<h2>{_e(heading)}</h2><ul>{''.join(f'<li>{_e(t)}</li>' for t in texts)}</ul>"
    ptt_text = _ptt_line(layout, wheel, rec)
    ptt = f'<p class="ptt"><b>Talk to Pitwall:</b> {_e(ptt_text)}</p>' if ptt_text else ""
    where = ""
    if game is not None:
        note = "" if game.menu.evidence else " (exact menu path not researched)"
        where = f"<p>Map them in {_e(game.menu.where)}{_e(note)}.</p>"
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<style>
@page {{ size: A4 landscape; margin: 12mm; }}
body {{ font-family: Helvetica, Arial, sans-serif; color: #111; background: #fff; margin: 0; padding: 0 4mm;
  font-size: 11pt; }}
.wrap {{ display: grid; grid-template-columns: 2fr 3fr; gap: 8mm; }} .wrap > div {{ min-width: 0; }}
td {{ overflow-wrap: anywhere; }}
h1 {{ font-size: 16pt; margin: 0 0 4mm; }} h2 {{ font-size: 12pt; margin: 4mm 0 2mm; }}
table {{ border-collapse: collapse; width: 100%; font-size: 10pt; }}
td, th {{ border-bottom: 1px solid #ccc; padding: 1.2mm 1.5mm; text-align: left; vertical-align: top; }}
.small {{ font-size: 8.5pt; color: #444; }} .ptt {{ margin: 2mm 0; }}
</style></head><body>
<h1>{_e(title)}</h1>
<div class="wrap"><div>{diagram_svg(cat, wheel, layout.assignments)}{ptt}{where}</div>
<div><table><thead><tr><th>Control</th><th>Function</th><th>What {_e(game_label)} calls it</th>
<th>Test</th></tr></thead><tbody>{rows}</tbody></table>{cant}</div></div>
<p class="small">Research only: nothing here is validated on your rig. Test results come from Pitwall's F1 25 button
test ("Seen by Pitwall"). Evidence: Official = a maker or publisher document; Inferred = from official figures;
Community = a community or third-party source; Pitwall's suggestion = Pitwall's design.
Printed {_e(_date(time.time()))}.</p>
</body></html>
"""


def card_text(
    cat: Catalog, layout: Layout, wheel: WheelDef, rec: Recommendation | None, *, driver_name: str | None = None
) -> str:
    game = cat.games.get(layout.game)
    game_label = game.label if game is not None else (layout.game_name or "Other game")
    head = " · ".join(
        x for x in ("Controls", driver_name, game_label, PLATFORM_LABELS.get(layout.platform), wheel.name) if x
    )
    lines = [head, ""]
    for ctl, label, native, check in _rows(cat, layout, wheel, rec):
        extra = f" [{native}]" if native else ""
        lines.append(f"{ctl}: {label}{extra}" + (f" ({check})" if check else ""))
    if rec is not None:
        lines += ["", "Talk to Pitwall: " + (_ptt_line(layout, wheel, rec) or "")]
        sections = (
            (f"Can't change while driving in {game_label}:", rec.not_on_wheel),
            (f"Not in {game_label}:", rec.not_in_game),
        )
        for heading, group in sections:
            if group:
                lines += ["", heading, *(f"- {t}" for t in dict.fromkeys(x["text"] for x in group))]
    lines += ["", "Research only: nothing here is validated on your rig."]
    return "\n".join(lines) + "\n"
