// Distance charts for Review › Compare (design spec v2, 6.5 and 10.4): HeroUI Pro LineChart / AreaChart (Recharts)
// with one shared cursor. Pro's chart roots do not forward Recharts' `syncId` (checked in 1.0.0-beta.10:
// LineChartRoot passes only data and margin to Recharts), so the charts share a CursorSync store instead
// (lib/viz/cursor.ts): scrubbing any chart moves the cursor on every chart, the ribbon and the map, and only the
// cursor layer re-renders (the series are memoised), which keeps 4 charts x 1 200 points smooth on the iPad.
//
// Touch: drag along a chart to scrub (vertical swipes still scroll the page: touch-action pan-y); the cursor stays
// where it was left. Keyboard: the plot is a slider (arrows move 10 m, shift 100 m). Mouse: hover follows.
// Lazy pages only: this module imports Recharts (never import it from Drive).

import { AreaChart } from "@heroui-pro/react/area-chart";
import { LineChart } from "@heroui-pro/react/line-chart";
import { memo, useCallback, useMemo, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { ReferenceArea, ReferenceLine, usePlotArea, useXAxisInverseScale, useXAxisScale } from "recharts";
import { metres, num } from "../../lib/format";
import { SECTOR_COLOUR_VARS } from "../../lib/skeleton";
import { distanceTick, distanceTicks, niceDomain, valuesAt } from "../../lib/viz/charts";
import { createCursorSync, type CursorSync } from "../../lib/viz/cursor";
import { clamp, finite } from "../../lib/viz/scale";
import { useCursor } from "./useCursor";

/** Chart margins and the y axis width: the plot area starts TRACE_PLOT_INSET.left px from the chart's left edge. */
export const TRACE_MARGIN = { top: 8, right: 8, bottom: 0, left: 0 } as const;
export const TRACE_Y_AXIS_W = 44;
/** Pass to LapRibbon's `inset` (same container width) so the ribbon lines up with the plot area. */
export const TRACE_PLOT_INSET = { left: TRACE_MARGIN.left + TRACE_Y_AXIS_W, right: TRACE_MARGIN.right } as const;

export interface TraceSeries {
  /** Row key ("a" reference, "b" your lap, "delta"). */
  key: string;
  /** Words for the readout and the accessible name ("Reference", "Your lap"). */
  label: string;
  /** A token: var(--pw-ref), var(--pw-cmp), var(--pw-behind), ... */
  colour: string;
  width?: number;
  dash?: string;
  /** Area charts: fill opacity (default 0.25). */
  fillOpacity?: number;
}

export interface TraceChartProps {
  /** Rows ascending by `d` (game lap metres): alignTraces / deltaRows. */
  rows: Record<string, number>[];
  series: readonly TraceSeries[];
  kind?: "line" | "area";
  height?: number;
  /** x domain [0, lengthM]; default the last row's distance. */
  lengthM?: number | null;
  yDomain?: [number, number];
  yTicks?: number[];
  yFormat?: (v: number) => string;
  /** A line at y = 0 (delta charts). */
  zeroLine?: boolean;
  /** Neutral sector bands in game metres (skeleton sectors). */
  bands?: readonly { a: number; b: number }[];
  /** The shared cursor; a private one when absent. */
  sync?: CursorSync;
  /** Distance ticks under the plot (default true; hide on all but the last chart). */
  xAxis?: boolean;
  /** Show the values at the cursor above the plot (default true). */
  readout?: boolean;
  /** Unit after readout values ("km/h", "%", "s"). */
  unit?: string;
  /** Accessible name of the plot ("Speed: reference and your lap"). */
  label: string;
  className?: string;
}

const plainNumber = (v: number) => num(v);

/** The cursor line plus a transparent, focusable scrub surface over the plot area (rendered inside the chart). */
function CursorLayer({ sync, lengthM, label }: { sync: CursorSync; lengthM: number; label: string }) {
  const plot = usePlotArea();
  const scale = useXAxisScale();
  const invert = useXAxisInverseScale();
  const cursor = useCursor(sync);
  const toMetres = useCallback(
    (e: PointerEvent<SVGRectElement>) => {
      const svg = e.currentTarget.ownerSVGElement;
      if (!svg || !invert) return null;
      const x = e.clientX - svg.getBoundingClientRect().left;
      const v = invert(x);
      return finite(v) ? clamp(v, 0, lengthM) : null;
    },
    [invert, lengthM],
  );
  if (!plot) return null;
  const cx = cursor != null && scale ? scale(cursor) : undefined;
  const onDown = (e: PointerEvent<SVGRectElement>) => {
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const m = toMetres(e);
    if (m != null) sync.set(m);
  };
  const onMove = (e: PointerEvent<SVGRectElement>) => {
    if (e.pointerType !== "mouse" && !e.currentTarget.hasPointerCapture?.(e.pointerId)) return;
    const m = toMetres(e);
    if (m != null) sync.set(m);
  };
  const onKey = (e: KeyboardEvent<SVGRectElement>) => {
    const step = e.shiftKey ? 100 : 10;
    const now = sync.get() ?? 0;
    if (e.key === "ArrowRight") sync.set(clamp(now + step, 0, lengthM));
    else if (e.key === "ArrowLeft") sync.set(clamp(now - step, 0, lengthM));
    else if (e.key === "Home") sync.set(0);
    else if (e.key === "End") sync.set(lengthM);
    else return;
    e.preventDefault();
  };
  return (
    <g>
      {finite(cx) && (
        <line x1={cx} x2={cx} y1={plot.y} y2={plot.y + plot.height} stroke="var(--accent)" strokeWidth={1.5} pointerEvents="none" />
      )}
      <rect
        x={plot.x}
        y={plot.y}
        width={Math.max(0, plot.width)}
        height={Math.max(0, plot.height)}
        fill="transparent"
        style={{ touchAction: "pan-y", cursor: "crosshair" }}
        tabIndex={0}
        role="slider"
        aria-label={`${label}: cursor`}
        aria-valuemin={0}
        aria-valuemax={Math.round(lengthM)}
        aria-valuenow={cursor != null ? Math.round(cursor) : undefined}
        aria-valuetext={cursor != null ? metres(cursor) : "no cursor"}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onKeyDown={onKey}
      />
    </g>
  );
}

/** Values of every series at the cursor ("at 4 810 m · Reference 212 · Your lap 205 km/h"). */
function Readout({
  rows,
  series,
  sync,
  format,
  unit,
}: {
  rows: Record<string, number>[];
  series: readonly TraceSeries[];
  sync: CursorSync;
  format: (v: number) => string;
  unit: string | undefined;
}) {
  const cursor = useCursor(sync);
  const at = cursor != null ? valuesAt(rows, cursor, series.map((s) => s.key)) : null;
  return (
    <div className="flex min-h-5 flex-wrap items-center gap-x-3 text-xs text-muted" aria-live="off">
      {at ? (
        <>
          <span className="pw-num">at {metres(at.d)}</span>
          {series.map((s) => {
            const v = at.values[s.key];
            return (
              <span key={s.key} className="inline-flex items-center gap-1">
                <i aria-hidden="true" style={{ display: "inline-block", width: 10, height: 3, borderRadius: 2, background: s.colour }} />
                {s.label} <b className="pw-num font-semibold text-foreground">{v == null ? "-" : format(v)}</b>
              </span>
            );
          })}
          {unit && <span>{unit}</span>}
        </>
      ) : (
        <span>Drag along the chart to read values</span>
      )}
    </div>
  );
}

export const TraceChart = memo(function TraceChart({
  rows,
  series,
  kind = "line",
  height = 150,
  lengthM,
  yDomain,
  yTicks,
  yFormat = plainNumber,
  zeroLine = false,
  bands,
  sync: shared,
  xAxis = true,
  readout = true,
  unit,
  label,
  className,
}: TraceChartProps) {
  const own = useMemo(() => createCursorSync(), []);
  const sync = shared ?? own;
  const last = rows.length ? rows[rows.length - 1]?.d : undefined;
  const L = finite(lengthM) && lengthM > 0 ? lengthM : finite(last) && last > 0 ? last : 1;
  const ticks = useMemo(() => distanceTicks(L), [L]);
  // Without an explicit domain: nice round ticks over the series' values (not Recharts' auto 85 / 170 / 255).
  const auto = useMemo(() => (yDomain ? null : niceDomain(rows, series.map((s) => s.key))), [yDomain, rows, series]);
  const yDom = yDomain ?? auto?.domain;
  const yTk = yTicks ?? auto?.ticks;

  // Everything but the cursor, memoised: a cursor move re-renders only CursorLayer and Readout.
  const statics = useMemo((): ReactNode[] => {
    const Grid = kind === "area" ? AreaChart.Grid : LineChart.Grid;
    const X = kind === "area" ? AreaChart.XAxis : LineChart.XAxis;
    const Y = kind === "area" ? AreaChart.YAxis : LineChart.YAxis;
    const out: ReactNode[] = [
      <Grid key="grid" vertical={false} />,
      <X
        key="x"
        dataKey="d"
        type="number"
        domain={[0, L]}
        ticks={ticks}
        tickFormatter={distanceTick}
        hide={!xAxis}
        allowDataOverflow
      />,
      <Y
        key="y"
        width={TRACE_Y_AXIS_W}
        domain={yDom ?? ["auto", "auto"]}
        ticks={yTk}
        tickFormatter={(v: number) => yFormat(v)}
        allowDataOverflow={yDom != null}
      />,
    ];
    (bands ?? []).forEach((b, i) =>
      out.push(
        <ReferenceArea
          key={`band${i}`}
          x1={b.a}
          x2={b.b}
          fill={SECTOR_COLOUR_VARS[i % 3]}
          fillOpacity={0.35}
          ifOverflow="hidden"
          strokeOpacity={0}
        />,
      ),
    );
    if (zeroLine) out.push(<ReferenceLine key="zero" y={0} stroke="var(--pw-line-strong)" strokeWidth={1} />);
    for (const s of series) {
      if (kind === "area") {
        out.push(
          <AreaChart.Area
            key={s.key}
            dataKey={s.key}
            name={s.label}
            type="linear"
            stroke={s.colour}
            strokeWidth={s.width ?? 1.5}
            strokeDasharray={s.dash}
            fill={s.colour}
            fillOpacity={s.fillOpacity ?? 0.25}
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />,
        );
      } else {
        out.push(
          <LineChart.Line
            key={s.key}
            dataKey={s.key}
            name={s.label}
            type="linear"
            stroke={s.colour}
            strokeWidth={s.width ?? 1.75}
            strokeDasharray={s.dash}
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />,
        );
      }
    }
    return out;
  }, [kind, L, ticks, xAxis, yDom, yTk, yFormat, bands, zeroLine, series]);

  const Root = kind === "area" ? AreaChart : LineChart;
  return (
    <div className={className}>
      {readout && <Readout rows={rows} series={series} sync={sync} format={yFormat} unit={unit} />}
      <Root data={rows} height={height} margin={TRACE_MARGIN} aria-label={label}>
        {statics}
        <CursorLayer sync={sync} lengthM={L} label={label} />
      </Root>
    </div>
  );
});
