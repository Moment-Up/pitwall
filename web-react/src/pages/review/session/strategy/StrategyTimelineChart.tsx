// Review › Strategy: the race timeline (lane "strategy"; strategy spec 10). Two HeroUI Pro LineCharts on the same
// lap axis (same margins and y-axis width, so the laps line up):
//   1. position as a step line, the y axis REVERSED and labelled "↑ better" (P1 at the top), in orange (you, P3);
//   2. the gaps to the car ahead (blue, solid) and behind (white, dashed) at the line, with a dashed 1 s line;
// on both, the player's stops as dashed verticals with a compound chip ("M → H") and safety car / VSC laps as shaded
// amber bands with their words ("VSC"). Under them, aligned to the plot area, a stint bar (compound colour ring + text
// label) and a weather row (words, the game's rain figure verbatim). A sentence for screen readers says the same.
// Lazy page only: this module imports Recharts.

import { LineChart } from "@heroui-pro/react/line-chart";
import { memo, useMemo } from "react";
import { ReferenceArea, ReferenceLine } from "recharts";
import type { StrategyLapRecord } from "../../../../lib/strategy/types";
import type { TimelineChartModel } from "../../../../lib/strategy/timeline";
import { one, UNKNOWN } from "../../../../lib/strategy/words";

const Y_W = 44;
const MARGIN = { top: 16, right: 16, bottom: 0, left: 0 } as const;

function LapTooltip({
  active,
  label,
  byLap,
}: {
  active?: boolean;
  label?: number | string;
  byLap: Map<number, StrategyLapRecord>;
}) {
  if (!active || label == null) return null;
  const r = byLap.get(Number(label));
  if (!r) return null;
  const gap = (ms: number | null, car: number | null) =>
    ms == null ? UNKNOWN : `${one(ms / 1000)} s${car != null ? ` (car ${car})` : ""}`;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__header">Lap {r.lap}</div>
      <div className="chart-tooltip__item">
        <span className="chart-tooltip__label">Position</span>
        <span className="chart-tooltip__value pw-num">{r.position != null ? `P${r.position}` : UNKNOWN}</span>
      </div>
      <div className="chart-tooltip__item">
        <span className="chart-tooltip__label">Car ahead</span>
        <span className="chart-tooltip__value pw-num">{gap(r.gap_ahead_ms, r.ahead_car)}</span>
      </div>
      <div className="chart-tooltip__item">
        <span className="chart-tooltip__label">Car behind</span>
        <span className="chart-tooltip__value pw-num">{gap(r.gap_behind_ms, r.behind_car)}</span>
      </div>
    </div>
  );
}

/** SC / VSC bands and the player's stops. Their words go on the position panel only (the stop's chip at the top, the
 * band's word at the bottom, so they never collide when a stop falls under a safety car). */
function Marks({ model, labels }: { model: TimelineChartModel; labels: boolean }) {
  return (
    <>
      {model.bands.map((b) => (
        <ReferenceArea
          key={`band${b.start}`}
          x1={b.start - 0.5}
          x2={b.end + 0.5}
          fill="var(--pw-flag-sc)"
          fillOpacity={0.18}
          ifOverflow="hidden"
          label={labels ? { value: b.short, position: "insideBottom", fill: "var(--warning)", fontSize: 11, fontWeight: 700 } : undefined}
        />
      ))}
      {model.stops.map((s) => (
        <ReferenceLine
          key={`stop${s.lap}`}
          x={s.lap}
          stroke="var(--pw-line-strong)"
          strokeDasharray="5 4"
          strokeWidth={1.5}
          label={labels ? { value: s.label, position: "insideTopLeft", fill: "var(--muted)", fontSize: 11, fontWeight: 700 } : undefined}
        />
      ))}
    </>
  );
}

export interface StrategyTimelineChartProps {
  model: TimelineChartModel;
  laps: readonly StrategyLapRecord[];
}

export const StrategyTimelineChart = memo(function StrategyTimelineChart({ model, laps }: StrategyTimelineChartProps) {
  const byLap = useMemo(() => new Map(laps.map((l) => [l.lap, l])), [laps]);
  const x = (
    <LineChart.XAxis
      dataKey="lap"
      type="number"
      domain={model.xDomain}
      ticks={model.xTicks}
      interval={0}
      allowDataOverflow
      tickFormatter={(v: number) => `L${v}`}
    />
  );
  const tooltip = <LineChart.Tooltip cursor={{ stroke: "var(--pw-line-strong)" }} content={<LapTooltip byLap={byLap} />} />;
  // Recharts' types want plain records; laps without a value simply leave the key out (a gap in the line).
  const rows = model.rows as Record<string, number | string>[];
  return (
    <div className="grid gap-2">
      <div className="text-xs font-medium text-muted" aria-hidden="true">
        Position · ↑ better
      </div>
      <LineChart data={rows} height={180} margin={MARGIN} role="img" aria-label={`Position by lap. ${model.summary}`}>
        <LineChart.Grid vertical={false} />
        {x}
        <LineChart.YAxis
          reversed
          width={Y_W}
          domain={model.positionDomain}
          ticks={model.positionTicks}
          allowDecimals={false}
          tickFormatter={(v: number) => `P${v}`}
        />
        <Marks model={model} labels />
        <LineChart.Line
          dataKey="position"
          name="Position"
          type="stepAfter"
          stroke="var(--accent)"
          strokeWidth={2.5}
          dot={false}
          activeDot={{ r: 4 }}
          connectNulls
          isAnimationActive={false}
        />
        {tooltip}
      </LineChart>

      {model.hasGaps && (
        <>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-medium text-muted" aria-hidden="true">
            <span>Gaps at the line, seconds</span>
            <span className="inline-flex items-center gap-1.5">
              <svg width="18" height="6" aria-hidden="true">
                <line x1="0" y1="3" x2="18" y2="3" stroke="var(--pw-ref)" strokeWidth="2.5" />
              </svg>
              car ahead
            </span>
            <span className="inline-flex items-center gap-1.5">
              <svg width="18" height="6" aria-hidden="true">
                <line x1="0" y1="3" x2="18" y2="3" stroke="var(--foreground)" strokeWidth="2" strokeDasharray="4 3" />
              </svg>
              car behind
            </span>
          </div>
          <LineChart data={rows} height={150} margin={MARGIN} role="img" aria-label="Gaps to the cars ahead and behind by lap">
            <LineChart.Grid vertical={false} />
            {x}
            <LineChart.YAxis width={Y_W} domain={model.gapDomain} ticks={model.gapTicks} interval={0} allowDataOverflow />
            <Marks model={model} labels={false} />
            <ReferenceLine
              y={1}
              stroke="var(--pw-line-strong)"
              strokeDasharray="2 4"
              label={{ value: "1 s", position: "insideBottomRight", fill: "var(--muted)", fontSize: 11 }}
            />
            <LineChart.Line
              dataKey="ahead"
              name="Car ahead"
              type="linear"
              stroke="var(--pw-ref)"
              strokeWidth={2.5}
              dot={{ r: 2.5, fill: "var(--pw-ref)", strokeWidth: 0 }}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
            <LineChart.Line
              dataKey="behind"
              name="Car behind"
              type="linear"
              stroke="var(--foreground)"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={{ r: 2.5, fill: "var(--foreground)", strokeWidth: 0 }}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
            {tooltip}
          </LineChart>
        </>
      )}

      {/* Rows under the plot area: the same left offset as the y axis, the same right margin. */}
      <div className="grid gap-1.5" style={{ marginLeft: Y_W + MARGIN.left, marginRight: MARGIN.right }}>
        {model.stints.length > 0 && (
          <div className="relative h-8" role="list" aria-label="Stints">
            {model.stints.map((s) => (
              <div
                key={s.key}
                role="listitem"
                className="absolute inset-y-0 flex min-w-0 items-center gap-1.5 overflow-hidden rounded-xl border-x-2 border-surface bg-surface-tertiary px-2 text-xs font-semibold"
                style={{ left: `${s.fromPct}%`, width: `${s.widthPct}%` }}
                title={s.words}
                aria-label={s.words}
              >
                <span className="inline-block size-3 flex-none rounded-full border-[3px]" style={{ borderColor: s.colour }} aria-hidden="true" />
                <span className="truncate max-sm:hidden">{s.label}</span>
                <span className="truncate sm:hidden">{s.short}</span>
              </div>
            ))}
          </div>
        )}
        {model.weather.length > 0 && (
          <div className="relative h-7" role="list" aria-label="Weather">
            {model.weather.map((w) => (
              <div
                key={w.key}
                role="listitem"
                className="absolute inset-y-0 flex min-w-0 items-center overflow-hidden rounded-xl border-x-2 border-surface bg-surface-secondary px-2 text-xs text-muted"
                style={{ left: `${w.fromPct}%`, width: `${w.widthPct}%` }}
                title={w.words}
                aria-label={w.words}
              >
                <span className="truncate max-sm:hidden">{w.label}</span>
                <span className="truncate sm:hidden">{w.short}</span>
              </div>
            ))}
          </div>
        )}
        {model.weatherLine && <p className="m-0 text-xs text-muted sm:hidden">{model.weatherLine}</p>}
        {model.bands.length > 0 && (
          <p className="m-0 text-xs text-muted">Shaded laps: {model.bands.map((b) => b.words).join("; ")}.</p>
        )}
      </div>
      <p className="sr-only">{model.summary}</p>
    </div>
  );
});
