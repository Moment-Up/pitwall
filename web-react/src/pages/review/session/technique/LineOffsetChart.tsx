// The focused corner's line offset (feat/technique spec §9): a Pro LineChart of how far sideways your lap was from the
// reference line through the corner window, metres tighter (+) / wider (−), the reference as the 0 line, ticks at
// the reference's turn-in, apex and track-out. Inside unknown: the distance alone, "off the reference line". The shared
// cursor shows as a vertical line and can be scrubbed here too. Intermediate and advanced only (TechniqueDensity).
// Lazy pages only (Recharts).

import { LineChart } from "@heroui-pro/react/line-chart";
import { memo, useCallback, useMemo, type PointerEvent } from "react";
import { ReferenceLine, usePlotArea, useXAxisInverseScale, useXAxisScale } from "recharts";
import { useCursor } from "../../../../components/viz/useCursor";
import type { CompareCornerTechnique } from "../../../../lib/endpoints/technique";
import { offsetDomain, offsetRows, offsetTick, pointTicks } from "../../../../lib/technique/chart";
import type { CursorSync } from "../../../../lib/viz/cursor";

const MARGIN = { top: 8, right: 12, bottom: 0, left: 0 } as const;

function Cursor({ sync, a, b }: { sync: CursorSync; a: number; b: number }) {
  const plot = usePlotArea();
  const scale = useXAxisScale();
  const invert = useXAxisInverseScale();
  const cursor = useCursor(sync);
  const toMetres = useCallback(
    (e: PointerEvent<SVGRectElement>) => {
      const svg = e.currentTarget.ownerSVGElement;
      if (!svg || !invert) return null;
      const v = invert(e.clientX - svg.getBoundingClientRect().left);
      return typeof v === "number" && Number.isFinite(v) ? Math.min(b, Math.max(a, v)) : null;
    },
    [invert, a, b],
  );
  if (!plot) return null;
  const x = cursor != null && cursor >= a && cursor <= b && scale ? scale(cursor) : undefined;
  return (
    <g>
      {typeof x === "number" && Number.isFinite(x) && (
        <line x1={x} x2={x} y1={plot.y} y2={plot.y + plot.height} stroke="var(--accent)" strokeWidth={1.5} pointerEvents="none" />
      )}
      <rect
        x={plot.x}
        y={plot.y}
        width={Math.max(0, plot.width)}
        height={Math.max(0, plot.height)}
        fill="transparent"
        style={{ touchAction: "pan-y", cursor: "crosshair" }}
        aria-hidden="true"
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture?.(e.pointerId);
          const m = toMetres(e);
          if (m != null) sync.set(m);
        }}
        onPointerMove={(e) => {
          if (e.pointerType !== "mouse" && !e.currentTarget.hasPointerCapture?.(e.pointerId)) return;
          const m = toMetres(e);
          if (m != null) sync.set(m);
        }}
      />
    </g>
  );
}

export interface LineOffsetChartProps {
  corner: CompareCornerTechnique;
  sync?: CursorSync | null;
  height?: number;
}

export const LineOffsetChart = memo(function LineOffsetChart({ corner, sync = null, height = 150 }: LineOffsetChartProps) {
  const rows = useMemo(() => offsetRows(corner), [corner]);
  const known = corner.inside_known;
  const dom = useMemo(() => offsetDomain(rows, known), [rows, known]);
  const ticks = useMemo(() => pointTicks(corner), [corner]);
  if (rows.length < 2) return <p className="m-0 text-sm text-muted">No line offsets measured through this corner.</p>;
  const a = rows[0]!.d;
  const b = rows[rows.length - 1]!.d;
  const tickName = (v: number) => ticks.find((t) => Math.abs(t.d - v) < 0.5)?.label ?? "";
  const title = known
    ? "Metres tighter (+) or wider (−) than the reference line"
    : "Metres off the reference line (the inside of this corner is unknown)";
  return (
    <figure className="m-0 grid gap-1" aria-label={title}>
      <figcaption className="text-xs text-muted">{title}; the reference is the 0 line.</figcaption>
      <LineChart data={rows as unknown as Record<string, number>[]} height={height} margin={MARGIN} aria-label={title}>
        <LineChart.Grid vertical={false} />
        <LineChart.XAxis
          dataKey="d"
          type="number"
          domain={[a, b]}
          ticks={ticks.map((t) => t.d)}
          tickFormatter={tickName}
          allowDataOverflow
        />
        <LineChart.YAxis width={44} domain={dom.domain} ticks={dom.ticks} tickFormatter={offsetTick} allowDataOverflow />
        {ticks.map((t) => (
          <ReferenceLine key={t.key} x={t.d} stroke="var(--pw-line-strong)" strokeDasharray="3 3" />
        ))}
        <ReferenceLine y={0} stroke="var(--pw-ref)" strokeWidth={2} />
        <LineChart.Line
          dataKey="o"
          name="Your lap"
          type="linear"
          stroke="var(--pw-cmp)"
          strokeWidth={2}
          dot={false}
          activeDot={false}
          connectNulls={false}
          isAnimationActive={false}
        />
        {sync && <Cursor sync={sync} a={a} b={b} />}
      </LineChart>
    </figure>
  );
});
