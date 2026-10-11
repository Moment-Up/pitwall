"""Build the catalogue's ``recommendations`` from its cited ``source_setups`` (deterministic, no I/O, no LLM).

``catalog.load_catalog_file`` calls this when it loads the packaged file (which stores the evidence only) and then
validates the result, so recommendations always follow from the cited setups. ``uv run python -m
pitwall.carsetup.build`` prints what the packaged evidence produces (counts per car format and selection rule).

How one recommendation (car format x track x session x conditions x style) is built:

1. **Candidates**: the source setups for that car format, track, session (a source's "both" counts for race and
   qualifying) and conditions whose style label fits: ``balanced`` takes unlabelled and balanced setups, ``stable``
   and ``aggressive`` only setups their source labelled so. Car formats and dry/wet are never mixed.
2. **Recency**: a candidate is current when it states a game version at or after the format's latest handling
   patch, or states none but was published on or after that patch's release day. If any candidate is current, the
   others are dropped (they were tuned for different physics); otherwise all are kept and every value's confidence
   is capped at ``low``.
3. **Selection**: one candidate -> it is used as published (``single_source``). Two or more -> the *medoid*: the
   setup whose values are, on average, closest to all the others (each parameter's difference divided by that
   parameter's range). Taking one whole real setup keeps it coherent (wing levels, ride heights and suspension tuned
   together), where a per-parameter median could combine values no driver ever ran. The selection is pitwall's
   choice, but every value is exactly what that source published, so values are not ``derived``.
   Ties go to the newest game version, then the newest publication date, then the setup id.
4. **Agreement**: per parameter, the candidates within ``AGREE_FRACTION`` of the range of the selected value are
   its ``sources``; the candidates' min/max is its ``spread``; a spread wider than ``DISAGREE_FRACTION`` of the
   range is written up as a disagreement instead of being averaged away. Confidence: ``high`` = three or more
   candidates and at least two thirds agree; ``medium`` = at least two agree; else ``low``.
5. **Stable variant** (``stable`` style without a labelled stable setup): the balanced recommendation with the
   catalogue rule ``stable_v1`` applied: one small step each in the directions the cited guides agree make an F1 25
   car more forgiving (rear wing +1, rear anti-roll bar -1, on-throttle differential -5, off-throttle +5; the
   catalogue rule records the sources and the one guide that disagrees on the on-throttle direction), clamped to
   the format's range. Changed values are ``derived`` with the rule id; unchanged ones keep their provenance. No
   other style is ever derived, and wet is never derived from dry.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pitwall.carsetup.catalog import (
    CONDITIONS,
    SESSIONS,
    STYLES,
    CarFormat,
    Catalog,
    Conditions,
    Confidence,
    FormatInfo,
    SessionKind,
    SourceSetup,
    Style,
    load_catalog_file,
    patch_key,
)

AGREE_FRACTION = 0.10  # a candidate "agrees" when within 10 % of the parameter's range of the selected value
DISAGREE_FRACTION = 0.25  # spreads wider than 25 % of the range are reported as disagreements
STABLE_RULE_ID = "stable_v1"
# Applied to the balanced recommendation when no source labels a stable setup (catalogue rule ``stable_v1``). Each
# entry is one small step, in the parameter's own unit, in the direction the cited guides give for a car that snaps
# on exit or is nervous on entry; the guides give directions more reliably than amounts, so the steps are minimal.
STABLE_ADJUST: Mapping[str, float] = {
    "rear_wing": +1.0,
    "rear_arb": -1.0,
    "diff_on_throttle": -5.0,
    "diff_off_throttle": +5.0,
}


def _span(info: FormatInfo, key: str) -> float | None:
    r = info.ranges.get(key)
    return (r.max - r.min) if r is not None else None


def _distance(a: SourceSetup, b: SourceSetup, info: FormatInfo) -> float:
    """Mean range-normalised difference over the parameters both setups give (1.0 when they share none)."""
    diffs = []
    for k, va in a.values.items():
        vb = b.values.get(k)
        span = _span(info, k)
        if vb is not None and span:
            diffs.append(abs(va - vb) / span)
    return sum(diffs) / len(diffs) if diffs else 1.0


def _newest_first(s: SourceSetup) -> tuple[Any, ...]:
    return (tuple(-p for p in patch_key(s.patch)), _neg_date(s.published), s.id)


def _neg_date(d: str | None) -> tuple[int, ...]:
    return tuple(-int(p) for p in d.split("-")) if d else (1,)  # undated sorts after every dated setup


def medoid(cands: Sequence[SourceSetup], info: FormatInfo) -> SourceSetup:
    ordered = sorted(cands, key=_newest_first)
    return min(ordered, key=lambda s: sum(_distance(s, o, info) for o in ordered if o is not s))


def _candidates(
    cat: Catalog, fmt: CarFormat, track: int, session: SessionKind, cond: Conditions, style: Style
) -> tuple[list[SourceSetup], bool]:
    """Candidate setups and whether they are current (at/after the latest handling patch)."""
    pool = [
        s
        for s in cat.setups_for(fmt, track)
        if s.covers(session)
        and s.conditions == cond
        and ((s.style in (None, "balanced")) if style == "balanced" else s.style == style)
    ]
    lhp = cat.formats[fmt].latest_handling_patch
    current = [s for s in pool if is_current(s, lhp.version, lhp.date)]
    return (current, True) if current else (pool, False)


def is_current(s: SourceSetup, patch: str, patch_date: str) -> bool:
    """Made for the current handling model: a stated game version at or after ``patch``, or (no version stated)
    published on or after the day that patch was released (a full date is needed; "2025-08" is ambiguous)."""
    if s.patch is not None:
        return patch_key(s.patch) >= patch_key(patch)
    return s.published is not None and len(s.published) == 10 and s.published >= patch_date


def _confidence(n: int, agree: int, current: bool) -> Confidence:
    if n >= 3 and agree * 3 >= n * 2:
        level: Confidence = "high"
    elif agree >= 2:
        level = "medium"
    else:
        level = "low"
    return level if current else "low"


def _fmt_num(v: float) -> str:
    return f"{v:g}"


def _build_one(
    cat: Catalog, fmt: CarFormat, track: int, session: SessionKind, cond: Conditions, style: Style
) -> dict[str, Any] | None:
    cands, current = _candidates(cat, fmt, track, session, cond, style)
    if not cands:
        return None
    info = cat.formats[fmt]
    chosen = cands[0] if len(cands) == 1 else medoid(cands, info)
    values: dict[str, Any] = {}
    disagreements: list[str] = []
    for p in cat.parameters:
        span = _span(info, p.key)
        given = [(s, s.values[p.key]) for s in cands if p.key in s.values]
        if span is None or not given:
            continue
        v = chosen.values.get(p.key)
        agreeing = [s for s, x in given if v is not None and abs(x - v) <= AGREE_FRACTION * span + 1e-9]
        lo, hi = min(x for _, x in given), max(x for _, x in given)
        if len(given) >= 2 and hi - lo > DISAGREE_FRACTION * span:
            disagreements.append(
                f"{p.label}: the {len(given)} setups range from {_fmt_num(lo)} to {_fmt_num(hi)}; the recommended "
                f"setup has {_fmt_num(v) if v is not None else 'no value'}."
            )
        values[p.key] = {
            "value": v,
            "from_setup": chosen.id if v is not None else None,
            "sources": sorted(s.id for s in agreeing),
            "patches": sorted({s.patch for s in agreeing if s.patch}, key=patch_key),
            "confidence": _confidence(len(given), len(agreeing), current) if v is not None else "low",
            "derived": False,
            "rule": None,
            "spread": [lo, hi] if len(given) >= 2 else None,
        }
    notes: list[str] = []
    if not current:
        notes.append(
            f"No candidate is known to be made for game version {info.latest_handling_patch.version} or later (the "
            f"latest handling patch, {info.latest_handling_patch.date}); every value is capped at low confidence."
        )
    if session == "qualifying" and any(s.session == "both" for s in cands):
        notes.append("Includes setups their sources published for both qualifying and the race.")
    return {
        "id": f"{fmt}:{track}:{session}:{cond}:{style}",
        "car_format": fmt,
        "track_id": track,
        "session": session,
        "conditions": cond,
        "style": style,
        "selection": "single_source" if len(cands) == 1 else "medoid",
        "from_setup": chosen.id,
        "candidates": sorted(s.id for s in cands),
        "base": None,
        "values": values,
        "disagreements": disagreements,
        "notes": notes,
    }


def _derive_stable(cat: Catalog, balanced: dict[str, Any]) -> dict[str, Any]:
    fmt: CarFormat = balanced["car_format"]
    info = cat.formats[fmt]
    values: dict[str, Any] = {k: dict(v) for k, v in balanced["values"].items()}
    changed: list[str] = []
    for key, delta in STABLE_ADJUST.items():
        cur = values.get(key)
        rng = info.ranges.get(key)
        if cur is None or cur["value"] is None or rng is None:
            continue
        new = rng.snap(cur["value"] + delta)
        if new == cur["value"]:
            continue  # already at the stable end of the range
        p = cat.param(key)
        changed.append(f"{p.label if p else key} {_fmt_num(cur['value'])} -> {_fmt_num(new)}")
        values[key] = {
            "value": new,
            "from_setup": cur["from_setup"],
            "sources": [],
            "patches": [],
            "confidence": "low",
            "derived": True,
            "rule": STABLE_RULE_ID,
            "spread": cur["spread"],
        }
    notes = [
        "No source publishes a stable setup for this combination; pitwall derived one from the balanced "
        f"recommendation with rule {STABLE_RULE_ID}"
        + (f" ({'; '.join(changed)})." if changed else " (no change was needed: already at the stable end).")
    ]
    return {
        **balanced,
        "id": balanced["id"].rsplit(":", 1)[0] + ":stable",
        "style": "stable",
        "selection": "derived",
        "base": balanced["id"],
        "values": values,
        "notes": notes + list(balanced["notes"]),
    }


def build_recommendations(cat: Catalog) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fmt, info in cat.formats.items():
        for track in info.tracks:
            for session in SESSIONS:
                for cond in CONDITIONS:
                    built: dict[Style, dict[str, Any]] = {}
                    for style in STYLES:
                        rec = _build_one(cat, fmt, track, session, cond, style)
                        if rec is not None:
                            built[style] = rec
                    if "stable" not in built and "balanced" in built:
                        built["stable"] = _derive_stable(cat, built["balanced"])
                    out.extend(built[s] for s in STYLES if s in built)
    return out


def summary(cat: Catalog) -> str:
    counts: dict[tuple[str, str], int] = {}
    for rec in cat.recommendations.values():
        k = (rec.car_format, rec.selection)
        counts[k] = counts.get(k, 0) + 1
    lines = [f"{len(cat.source_setups)} cited setups -> {len(cat.recommendations)} recommendations"]
    lines += [f"  {fmt:8} {sel:13} {n}" for (fmt, sel), n in sorted(counts.items())]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - maintenance entry point
    from pitwall.carsetup.catalog import DEFAULT_PATH

    print(summary(load_catalog_file(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH)))
