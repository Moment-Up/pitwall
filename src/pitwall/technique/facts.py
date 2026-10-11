"""Facts for the AI engineer from the technique analysis (topics ``line``, ``technique`` and ``balance``).

``technique_facts(sa)`` returns ``(topic, text, data, corner, say)`` tuples that ``ai.facts.build_fact_sheet`` adds
to the sheet. Like every fact, ``text`` is what the LLM reads and ``say`` the driver-facing sentence; every number in
``say`` is also in ``text`` or ``data``, so deterministic answers built from it pass ``check_grounding``.

Rules carried into the words:

* Line facts are relative to the driver's own reference lap ("wider" / "tighter"), never an ideal line.
* Technique facts describe; they never tell the driver to brake later (or earlier). Muted brake notes (the game's
  braking assist is on) never become facts.
* Balance facts say the thresholds are heuristics, separate the car from the driving, and setup facts are one
  change to try, never a fix (``carsetup.recommend.CAVEAT``).

The fact builder has no database: facts use the stock-brake tolerances (a subset of what the dashboard shows with a
load cell), and setup facts cannot see running experiments.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, get_args

import numpy as np

from pitwall.carsetup.catalog import CarFormat
from pitwall.carsetup.recommend import CAVEAT
from pitwall.core.session_analysis import SessionAnalysis
from pitwall.technique import thresholds as T
from pitwall.technique.balance import PHASE_SIMPLE
from pitwall.technique.inputs import TechniqueNote
from pitwall.technique.session import POINT_KEYS, SessionTechnique, TechniqueCorner, analyse_session, setup_engineer
from pitwall.technique.setup_map import SetupSuggestion

log = logging.getLogger(__name__)

FactTuple = tuple[str, str, dict[str, Any], str | None, str | None]
POINT_WORDS = {"turn_in": "turn-in", "apex": "apex", "track_out": "track-out"}
MAX_LINE_FACTS = 5
MAX_TECHNIQUE_FACTS = 6
MAX_SYMPTOM_FACTS = 3
LINE_SUMMARY_PREFIX = "Biggest line differences vs reference"
LINE_NONE_PREFIX = "Racing line vs reference"
HANDLING_PREFIX = "Handling summary (heuristic thresholds)"
SETUP_PREFIX = "Setup to try"
FORMATS: tuple[CarFormat, ...] = get_args(CarFormat)


def technique_facts(sa: SessionAnalysis) -> list[FactTuple]:
    """Technique facts for a session (empty when there is no track model). Never raises: a failure here must not
    take the rest of the fact sheet (and the engineer) down with it."""
    if sa.model is None or not sa.model.corners:
        return []
    try:
        st = analyse_session(sa)
        return [*_line_facts(st), *_technique_facts(st), *_balance_facts(st, sa)]
    except Exception:
        log.exception("technique facts failed for session %s", sa.session.get("id"))
        return []


def _side(v: float) -> str:
    return "wider" if v < 0 else "tighter"


def _loss_words(loss: float | None) -> tuple[str, str]:
    """(text clause, say clause) for a corner's time difference."""
    if loss is None:
        return "", ""
    if f"{abs(loss):.2f}" == "0.00":
        return "the same time through the corner", "the same time"
    if loss > 0:
        return f"cost {loss:.2f}s", f"it cost {loss:.2f}s"
    return f"gained {abs(loss):.2f}s", f"you gained {abs(loss):.2f}s there"


def _compared(c: TechniqueCorner) -> list[Any]:
    return [lc for lc in c.laps if lc.line is not None]


def _line_facts(st: SessionTechnique) -> list[FactTuple]:
    av = st.available["line"]
    ref = st.ref_lap_number
    if not av.ok:
        text = f"{LINE_NONE_PREFIX}: not available. {av.reason}"
        return [("line", text, {}, None, None)]
    rows: list[tuple[float, float, TechniqueCorner, str, Any, float]] = []
    for c in st.corners:
        pick = _line_pick(c)
        if pick is None:
            continue
        key, lc, v = pick
        ps = c.line.points.get(key) if c.line is not None else None
        median = ps.median_offset_m if ps is not None and ps.median_offset_m is not None else 0.0
        rows.append((max(abs(median), abs(v) * 0.5), abs(v), c, key, lc, v))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    out: list[FactTuple] = []
    for _, _, c, key, lc, v in rows[:MAX_LINE_FACTS]:
        assert c.line is not None
        ps = c.line.points[key]
        assert ps is not None
        pw = POINT_WORDS[key]
        known = c.line.inside_known
        loss_t, loss_s = _loss_words(lc.time_delta_s)
        if known:
            side = _side(v)
            count = ps.laps_wider if v < 0 else ps.laps_tighter
            text = (
                f"Racing line at {c.long_name}: on lap {lc.lap_number} the {pw} was {abs(v):.1f} m {side} than your "
                f"reference lap (lap {ref}); {side} by {T.LINE_NOTABLE_M:.0f} m or more on {count} of {ps.laps} "
                "compared laps"
            )
            say = (
                f"On lap {lc.lap_number} you were {abs(v):.1f} m {side} than your reference at the {pw} of "
                f"{c.long_name}"
            )
        else:
            text = (
                f"Racing line at {c.long_name}: on lap {lc.lap_number} the {pw} was {abs(v):.1f} m off your "
                f"reference lap's line (lap {ref}; which side is unknown on a near-straight); median "
                f"{abs(ps.median_offset_m or 0.0):.1f} m over {ps.laps} compared laps"
            )
            say = f"On lap {lc.lap_number} you were {abs(v):.1f} m off your reference line at the {pw} of {c.long_name}"
        if loss_t:
            text += f"; {c.long_name} {loss_t}"
            say += f", and {loss_s}"
        data = {
            "lap": lc.lap_number,
            "ref_lap": ref,
            "offset_m": round(v, 2),
            "median_offset_m": round(ps.median_offset_m or 0.0, 2),
            "laps": ps.laps,
            "time_delta_s": lc.time_delta_s,
        }
        out.append(("line", text + ".", data, c.corner, say + "."))
    if out:
        parts = []
        for _, _, c, key, lc, v in rows[:3]:
            assert c.line is not None
            ps = c.line.points[key]
            assert ps is not None
            med = ps.median_offset_m or 0.0
            if abs(med) >= T.LINE_NOTABLE_M:  # a pattern: the session median is off the reference
                how = f"{abs(med):.1f} m {_side(med)}" if c.line.inside_known else f"{abs(med):.1f} m off the line"
                parts.append(f"{c.long_name} {POINT_WORDS[key]} {how} (median of {_laps(ps.laps)})")
            else:  # one lap off, the others close: name that lap rather than a near-zero median
                how = f"{abs(v):.1f} m {_side(v)}" if c.line.inside_known else f"{abs(v):.1f} m off the line"
                parts.append(f"{c.long_name} {POINT_WORDS[key]} {how} on lap {lc.lap_number}")
        text = f"{LINE_SUMMARY_PREFIX} (lap {ref}): " + "; ".join(parts) + "."
        out.append(("line", text, {"ref_lap": ref}, None, None))
    else:
        laps = max((len(_compared(c)) for c in st.corners), default=0)
        text = (
            f"{LINE_NONE_PREFIX} (lap {ref}): within {T.LINE_NOTABLE_M:.0f} m at the turn-in, apex and track-out of "
            f"every corner over {laps} compared laps."
        )
        out.append(("line", text, {"ref_lap": ref, "laps": laps}, None, None))
    return out


def _laps(n: int) -> str:
    return f"{n} lap" if n == 1 else f"{n} laps"


def _line_pick(c: TechniqueCorner) -> tuple[str, Any, float] | None:
    """The point and lap a corner's line fact is about: the latest compared lap when it is notably off the
    reference, else the lap and point furthest off (at least ``LINE_NOTABLE_M``); None when every lap is close."""
    laps = _compared(c)
    if c.line is None or not laps:
        return None

    def biggest(lc: Any) -> tuple[str, float] | None:
        vals = [(k, float(lc.line[k])) for k in POINT_KEYS if lc.line.get(k) is not None]
        return max(vals, key=lambda kv: abs(kv[1]), default=None)

    latest = biggest(laps[-1])
    if latest is not None and abs(latest[1]) >= T.LINE_NOTABLE_M:
        return latest[0], laps[-1], latest[1]
    best: tuple[str, Any, float] | None = None
    for lc in laps:
        b = biggest(lc)
        if b is not None and abs(b[1]) >= T.LINE_NOTABLE_M and (best is None or abs(b[1]) > abs(best[2])):
            best = (b[0], lc, b[1])
    return best


def _mean_loss(c: TechniqueCorner) -> float:
    vals = [lc.time_delta_s for lc in c.laps if lc.time_delta_s is not None and not lc.incident]
    return float(np.mean(vals)) if vals else 0.0


def _technique_facts(st: SessionTechnique) -> list[FactTuple]:
    out: list[FactTuple] = []
    ref = st.ref_lap_number
    if st.available["inputs"].ok:
        corners = sorted(st.corners, key=lambda c: -_mean_loss(c))
        n = 0
        for c in corners:
            if n >= MAX_TECHNIQUE_FACTS:
                break
            latest = next((lc for lc in reversed(c.laps) if lc.all_notes), None)
            notes: list[TechniqueNote] = [x for x in (latest.notes if latest else []) if not x.muted]
            habits = [h for h in c.habits if not h.muted][:1]
            if not notes and not habits:
                continue
            bits: list[str] = []
            plain: list[str] = []
            if notes and latest is not None:
                bits.append(f"on lap {latest.lap_number} vs reference lap {ref}: " + " ".join(x.text for x in notes))
                plain.append(f"On lap {latest.lap_number}: " + " ".join(x.text_simple for x in notes))
            if habits:
                bits.append("Habit: " + habits[0].text)
                plain.append(habits[0].text_simple)
            text = f"Brake and throttle technique at {c.long_name} " + " ".join(bits)
            say = f"{c.long_name}. " + " ".join(plain)
            data: dict[str, Any] = {"ref_lap": ref, "metrics": len(notes) + len(habits)}
            if latest is not None:
                data["lap"] = latest.lap_number
            out.append(("technique", text, data, c.corner, say))
            n += 1
    out.extend(_slip_facts(st))
    return out


def _slip_facts(st: SessionTechnique) -> list[FactTuple]:
    out: list[FactTuple] = []
    a = st.assists
    if a.braking_assist:
        out.append(
            (
                "technique",
                a.notes[0],  # "Braking assist is on (medium): ..."
                {"braking_assist": a.braking_assist},
                None,
                "The game's braking assist is on, so the brake figures are not all yours.",
            )
        )
    if not st.available["slip"].ok:
        return out
    # lock-ups
    if a.abs:
        out.append(
            (
                "technique",
                "Lock-ups: ABS is on, so the game prevents them and lock-ups are not analysed.",
                {},
                None,
                None,
            )
        )
    else:
        hits: list[tuple[str, int, list[int]]] = []
        for c in st.corners:
            laps = [lc.lap_number for lc in c.laps if lc.inputs and lc.inputs.lockup.events]
            ev = sum(lc.inputs.lockup.events or 0 for lc in c.laps if lc.inputs and lc.inputs.lockup.events)
            if laps:
                hits.append((c.long_name, ev, laps))
        if hits:
            parts = [
                f"{name}: {ev} on lap{'s' if len(laps) > 1 else ''} {', '.join(map(str, laps))}"
                for name, ev, laps in hits
            ]
            total = sum(h[1] for h in hits)
            out.append(
                (
                    "technique",
                    f"Lock-ups under braking this session ({total} in total, ABS off): " + "; ".join(parts) + ".",
                    {"lockups": total},
                    None,
                    None,
                )
            )
        else:
            out.append(("technique", "Lock-ups: none detected under braking this session (ABS off).", {}, None, None))
    # wheelspin
    spins: list[tuple[str, float, list[int]]] = []
    for c in st.corners:
        laps = [lc.lap_number for lc in c.laps if lc.inputs and lc.inputs.wheelspin.events]
        tot = sum(lc.inputs.wheelspin.total_s or 0.0 for lc in c.laps if lc.inputs and lc.inputs.wheelspin.events)
        if laps:
            spins.append((c.long_name, tot, laps))
    tc = f" (traction control {'full' if a.traction_control == 2 else 'medium'})" if a.traction_control else ""
    if spins:
        spins.sort(key=lambda x: -x[1])
        parts = [
            f"{name} {tot:.2f}s on lap{'s' if len(laps) > 1 else ''} {', '.join(map(str, laps))}"
            for name, tot, laps in spins[:4]
        ]
        out.append(
            (
                "technique",
                f"Wheelspin on corner exits this session{tc}: " + "; ".join(parts) + ".",
                {"wheelspin_s": round(sum(x[1] for x in spins), 2)},
                None,
                None,
            )
        )
    else:
        out.append(
            (
                "technique",
                f"Wheelspin: none lasting {T.SPIN_MIN_S:.1f}s or more on the corner exits this session{tc}.",
                {},
                None,
                None,
            )
        )
    return out


def _balance_facts(st: SessionTechnique, sa: SessionAnalysis) -> list[FactTuple]:
    av = st.available["balance"]
    if not av.ok:
        return [("balance", f"{HANDLING_PREFIX}: not available. {av.reason}", {}, None, None)]
    car = [s for s in st.symptoms if s.verdict == "car"]
    driving = [s for s in st.symptoms if s.verdict == "driving"]
    laps = len({lc.lap_id for c in st.corners for lc in c.laps if lc.balance})
    if st.symptoms:
        parts = []
        if car:
            parts.append(
                "the car: " + "; ".join(f"{PHASE_SIMPLE[s.phase]} {s.cls} at {', '.join(s.corner_labels)}" for s in car)
            )
        if driving:
            parts.append(
                "the driving (not on the best lap): "
                + "; ".join(f"{PHASE_SIMPLE[s.phase]} {s.cls} at {', '.join(s.corner_labels)}" for s in driving)
            )
        text = f"{HANDLING_PREFIX}, measured from tyre slip at the limit over {laps} laps: " + ". ".join(parts) + "."
    else:
        text = (
            f"{HANDLING_PREFIX}, measured from tyre slip at the limit over {laps} laps: no understeer or oversteer "
            "recurs at any corner this session."
        )
    out: list[FactTuple] = [("balance", text, {"laps": laps, "car": len(car), "driving": len(driving)}, None, None)]
    for s in car[:MAX_SYMPTOM_FACTS] + driving[:MAX_SYMPTOM_FACTS]:
        data = {
            "laps": s.laps,
            "laps_total": s.laps_total,
            "median_slip_diff_deg": round(s.median_slip_diff_deg, 1),
            "corners": list(s.corners),
        }
        out.append(("balance", s.text, data, s.corners[0] if s.corners else None, s.text_simple))
    suggestions, fmt_note = _fact_suggestions(st, sa)
    if suggestions:
        seen: set[str] = set()
        by_symptom = {s.id: s for s in st.symptoms}
        for sg in suggestions:
            if sg.symptom_id in seen or sg.blocked is not None or len(seen) >= MAX_SYMPTOM_FACTS:
                continue
            seen.add(sg.symptom_id)
            sym = by_symptom.get(sg.symptom_id)
            corner = sym.corners[0] if sym and sym.corners else None
            p_from = _fmt(sg.from_value)
            p_to = _fmt(sg.to_value)
            text = (
                f"{SETUP_PREFIX} for this symptom ({sg.symptom_text}): {sg.label} {p_from} -> {p_to}{fmt_note}. "
                f"{sg.why} Expected: {sg.effect} One change, then compare a session. {CAVEAT}"
            )
            say = f"Something to try: {sg.label} from {p_from} to {p_to}. {sg.why} One change, then compare a session."
            data = {"from_value": sg.from_value, "to_value": sg.to_value, "corners": list(sym.corners) if sym else []}
            out.append(("balance", text, data, corner, say))
    return out


def _fact_suggestions(st: SessionTechnique, sa: SessionAnalysis) -> tuple[list[SetupSuggestion], str]:
    """The setup suggestions to state as facts, and a note for their text. The fact builder cannot know the car
    format the driver chose on the Setup page, so when the game's generic car hides it (as in every F1 25 session
    sent in UDP format 2025 with the generic car) a change is stated only when it is the same on the 2025 and the
    2026 car; any other suggestion stays blocked."""
    eng = setup_engineer(st, sa.setup)
    if eng is None:
        return [], ""
    if eng.car_format is not None:
        return eng.suggestions, ""
    per = [setup_engineer(st, sa.setup, car_format=fmt) for fmt in FORMATS]
    if any(e is None or e.car_format is None for e in per):
        return eng.suggestions, ""
    a, b = per[0], per[1]
    assert a is not None and b is not None
    other = {(x.symptom_id, x.parameter): x for x in b.suggestions}
    out: list[SetupSuggestion] = []
    for x in a.suggestions:
        o = other.get((x.symptom_id, x.parameter))
        same = (
            x.blocked is None
            and o is not None
            and o.blocked is None
            and (x.from_value, x.to_value) == (o.from_value, o.to_value)
        )
        out.append(x if same else replace(x, to_value=None, blocked=x.blocked or "differs by car format"))
    return out, " (the same change on the 2025 and the 2026 car)"


def _fmt(v: float | None) -> str:
    if v is None:
        return "unknown"
    return f"{v:g}"
