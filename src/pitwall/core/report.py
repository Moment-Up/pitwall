"""Session report: measurable braking and cornering differences, as JSON and Markdown.

``pitwall report`` and ``GET /api/sessions/{id}/report`` (Review › Session report). Besides the laps, corners and
coaching observations: the game as "F1 25 · PS5" (``games.display_label``), the pace against the AI (F1), and - when
the caller passes the session's recap (``session_report`` does) - "Today's 3 things" and the goals the session reached,
in the words the Summary and the Session complete card use (plan F7). Deterministic; no language model.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from pitwall.ai.facts import fmt_lap
from pitwall.analysis.strategy import fuel_estimate, tyre_estimate
from pitwall.core.session_analysis import SessionAnalysis
from pitwall.games import display_label

if TYPE_CHECKING:
    from pitwall.core.live import LiveState
    from pitwall.core.session_analysis import SessionAnalyzer
    from pitwall.storage.db import Database

log = logging.getLogger(__name__)

# The labels of the Summary's "3 things" (plan 5.1: Work on names its scope).
THING_LABELS = (
    ("went_well", "Went well"),
    ("work_on", "One to work on (this session)"),
    ("progress", "Progress"),
)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun if n == 1 else noun + 's'}"


def _things_md(recap: Mapping[str, Any]) -> list[str]:
    """The "Today's 3 things" and goals reached sections, from a ``SessionRecap`` (``MotivationService.recap``)."""
    things = recap.get("things") or {}
    why = recap.get("why_empty") or {}
    out: list[str] = ["\n## Today's 3 things\n"]
    shown = [(label, t) for key, label in THING_LABELS if isinstance(t := things.get(key), Mapping) and t.get("text")]
    if not shown:  # a session with no timed lap, a replay, ...: one reason, not three
        reason = next((str(why[k]) for k, _ in THING_LABELS if why.get(k)), "Nothing to say about this session")
        out.append(f"_{reason}._")
    for key, label in THING_LABELS:
        t = things.get(key)
        if isinstance(t, Mapping) and t.get("text"):
            evidence = f" _({t['evidence']})_" if t.get("evidence") else ""
            out.append(f"- **{label}:** {t['text']}{evidence}")
        elif shown and why.get(key):
            out.append(f"- **{label}:** _{why[key]}._")
    reached = [g for g in recap.get("goals_achieved") or () if isinstance(g, Mapping)]
    if reached:
        out.append("\n## Goals reached\n")
        for g in reached:
            where = f" ({g['scope_text']})" if g.get("scope_text") else ""
            done = g.get("achieved") or {}
            out.append(f"- {g.get('title')}{where}" + (f": {done['text']}" if done.get("text") else ""))
    return out


def session_report(
    db: Database,
    sa: SessionAnalysis,
    *,
    analyzer: SessionAnalyzer | None = None,
    live: LiveState | None = None,
) -> dict[str, Any]:
    """``build_report`` with the session's recap (read-only; reuses ``sa``). A failing recap never fails the report:
    it is logged and the report is built without the 3 things."""
    recap: dict[str, Any] | None = None
    sid = str(sa.session.get("id") or "")
    try:
        from pitwall.motivation.service import MotivationService

        recap = MotivationService(db, analyzer=analyzer, live=live).recap(sid, analysis=sa)
    except Exception:
        log.exception("session report: the recap of %s failed (report continues without it)", sid)
    return build_report(sa, recap)


def build_report(sa: SessionAnalysis, recap: Mapping[str, Any] | None = None) -> dict[str, Any]:
    s = sa.session
    laps = sa.laps
    clean = [lap for lap in laps if lap["clean"] and lap.get("lap_time_ms")]
    best = min(clean, key=lambda x: x["lap_time_ms"]) if clean else None
    obs_all = [o for lid in sorted(sa.observations) for o in sa.observations[lid]]
    corrective = sorted((o for o in obs_all if not o["positive"]), key=lambda o: -o["priority"])
    fuel = fuel_estimate(laps, (laps[-1]["meta"] or {}).get("fuel_end_kg") if laps else None, None, None)
    tyres = tyre_estimate(laps)
    corners = [asdict(c) for c in sa.corner_summary]
    losses = sorted((c for c in corners if c["mean_time_delta_s"] is not None), key=lambda c: -c["mean_time_delta_s"])

    game = display_label(s.get("game"), s.get("platform"))
    md: list[str] = []
    title = f"# Session report - {s.get('track_name') or 'unknown track'} ({s.get('session_type_raw') or ''})"
    md.append(title)
    if s.get("synthetic"):
        md.append("\n> **SYNTHETIC DATA** - generated test telemetry, not a real driving session.\n")
    md.append(
        f"\nGame: {game} | car {s.get('car_name') or '?'} | source `{s.get('source')}` | "
        f"{_count(len(laps), 'lap')}, {len(clean)} clean\n"
    )
    if best:
        md.append(f"**Best clean lap:** lap {best['lap_number']} - {fmt_lap(best['lap_time_ms'])}")
    if sa.ref_lap:
        md.append(f"  \n**Reference:** lap {sa.ref_lap['lap_number']} ({fmt_lap(sa.ref_lap.get('lap_time_ms'))})\n")
    # the summary first (pace vs AI, Today's 3 things, goals reached), then the tables
    ai = sa.ai_pace
    if ai is not None and ai.get("status") == "ok" and ai.get("gap_ms") is not None:
        gap = int(ai["gap_ms"]) / 1000
        md.append(
            f"\n**Pace vs AI (difficulty {ai['ai_difficulty']}):** best clean lap {fmt_lap(ai['driver_best_ms'])} vs "
            f"the typical AI car's {fmt_lap(ai['ai_ref_ms'])}: {abs(gap):.3f}s {'slower' if gap > 0 else 'faster'} "
            f"({float(ai['gap_pct']):+.2f}%), {ai['field_rank']} of {ai['field_size']} on best laps."
        )
    elif ai is not None:
        md.append(f"\n**Pace vs AI:** {str(ai.get('status')).replace('_', ' ')}.")
    if recap is not None:
        md += _things_md(recap)
    md.append("\n## Laps\n\n| Lap | Time | Clean | Flags | vs ref |\n|---:|---:|:---:|---|---:|")
    by_id = {lid: c for lid, c in sa.comparisons.items()}
    for lap in laps:
        comp = by_id.get(lap["id"])
        delta = f"{comp.total_delta_s:+.3f}s" if comp and comp.total_delta_s is not None else ""
        md.append(
            f"| {lap['lap_number']} | {fmt_lap(lap.get('lap_time_ms'))} | {'yes' if lap['clean'] else 'no'} | "
            f"{', '.join(lap['flags'])} | {delta} |"
        )
    if corners:
        md.append("\n## Corners (average vs reference)\n")
        md.append("| Corner | Dir | Laps | Time | Brake point | Brake-point spread | Min speed | Exit speed |")
        md.append("|---|---|---:|---:|---:|---:|---:|---:|")
        for c in corners:

            def f(v: float | None, fmt: str) -> str:
                return "" if v is None else format(v, fmt)

            md.append(
                f"| {c['corner']} | {c['direction'] or ''} | {c['laps']} | {f(c['mean_time_delta_s'], '+.3f')}s | "
                f"{f(c['mean_brake_point_delta_m'], '+.0f')} m | {f(c['brake_point_std_m'], '.1f')} m | "
                f"{f(c['mean_min_speed_delta_kph'], '+.1f')} km/h | {f(c['mean_exit_speed_delta_kph'], '+.1f')} km/h |"
            )
        md.append(
            "\nBrake point: negative = earlier than reference. Spread = std-dev of your braking point "
            "across laps (consistency)."
        )
    if corrective:
        md.append("\n## Top coaching observations\n")
        for o in corrective[:8]:
            md.append(
                f"- **Lap {o['lap_number']}** - {o['text']} _(confidence {o['confidence']:.2f}"
                + (f", {o['consistency']}" if o.get("consistency") else "")
                + ")_"
            )
    md.append("\n## Fuel & tyres\n")
    if fuel.per_lap_kg is not None:
        md.append(f"- Fuel: {fuel.per_lap_kg:.2f} kg/lap (median of {fuel.laps_used} green laps)")
    if tyres.wear_rate_pct_per_lap:
        r = tyres.wear_rate_pct_per_lap
        md.append(f"- Tyre wear per lap: FL {r[0]:.2f}% FR {r[1]:.2f}% RL {r[2]:.2f}% RR {r[3]:.2f}%")
    md.append("\n_All figures are computed deterministically from recorded telemetry._")
    return {
        "session": s,
        "game_label": game,
        "best_lap": best,
        "reference": sa.ref_lap,
        "corners": corners,
        "biggest_losses": losses[:3],
        "observations": corrective[:12],
        "fuel": asdict(fuel),
        "tyres": asdict(tyres),
        "ai_pace": sa.ai_pace,
        "three_things": None if recap is None else recap.get("things"),
        "goals_achieved": [] if recap is None else list(recap.get("goals_achieved") or ()),
        "markdown": "\n".join(md),
    }
