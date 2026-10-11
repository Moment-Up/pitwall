"""Session report: measurable braking and cornering differences, as JSON and Markdown."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pitwall.ai.facts import fmt_lap
from pitwall.analysis.strategy import fuel_estimate, tyre_estimate
from pitwall.core.session_analysis import SessionAnalysis


def build_report(sa: SessionAnalysis) -> dict[str, Any]:
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

    md: list[str] = []
    title = f"# Session report - {s.get('track_name') or 'unknown track'} ({s.get('session_type_raw') or ''})"
    md.append(title)
    if s.get("synthetic"):
        md.append("\n> **SYNTHETIC DATA** - generated test telemetry, not a real driving session.\n")
    md.append(
        f"\nGame `{s.get('game')}` | car {s.get('car_name') or '?'} | source `{s.get('source')}` | "
        f"{len(laps)} laps, {len(clean)} clean\n"
    )
    if best:
        md.append(f"**Best clean lap:** lap {best['lap_number']} - {fmt_lap(best['lap_time_ms'])}")
    if sa.ref_lap:
        md.append(f"  \n**Reference:** lap {sa.ref_lap['lap_number']} ({fmt_lap(sa.ref_lap.get('lap_time_ms'))})\n")
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
        "best_lap": best,
        "reference": sa.ref_lap,
        "corners": corners,
        "biggest_losses": losses[:3],
        "observations": corrective[:12],
        "fuel": asdict(fuel),
        "tyres": asdict(tyres),
        "markdown": "\n".join(md),
    }
