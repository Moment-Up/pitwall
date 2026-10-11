// "Getting faster?" chart (spec 6.9, 10.4): Pro LineChart with one dot per session (its best clean lap), the y axis
// REVERSED and labelled "faster ↑", m:ss.S ticks; with D5 a dashed line of the median clean lap per session; a dashed
// line for the fastest time in the family (neutral). A dot is purple REC or green PB when that session's best lap holds
// the family record or the driver's best ever (the caller passes the one rule's badges, lib/bests.ts); otherwise it
// is plain. A session with no clean lap shows "-" at the slow edge. Every dot has a 44 px target and opens that
// session (tap, Enter or Space).
//
// Lazy page only (Recharts). The axis and row shaping reuse lane V's pure `lapChartModel` (lib/viz/charts.ts).

import { LineChart } from "@heroui-pro/react/line-chart";
import { memo, useCallback, useEffect, useMemo, useRef, type KeyboardEvent, type ReactNode } from "react";
import { ReferenceLine, type DotItemDotProps } from "recharts";
import type { TimingStatus } from "../../../components/ui/types";
import { lapTime } from "../../../lib/format";
import { lapChartModel, timeTick, type LapPoint } from "../../../lib/viz/charts";
import { finite } from "../../../lib/review/words";

export interface ProgressChartPoint {
  /** Session id. */
  id: string;
  x: number;
  /** "3 Oct", "Today". */
  xLabel: string;
  bestMs: number | null;
  medianMs: number | null;
  status: TimingStatus;
  carName: string | null;
}

export interface ProgressChartLine {
  ms: number;
  label: string;
  /** "rec" purple only with exact D5 data for every driver (spec 4.6, 14.5 #5). */
  tone: "rec" | "neutral";
}

export interface ProgressChartProps {
  points: readonly ProgressChartPoint[];
  line?: ProgressChartLine | null;
  height?: number;
  showMedian: boolean;
  onOpen: (sessionId: string) => void;
  label: string;
}

const MARGIN = { top: 14, right: 16, bottom: 0, left: 0 } as const;
const HIT_R = 22;

function dotFill(s: TimingStatus): string {
  if (s === "rec") return "var(--pw-rec)";
  if (s === "pb" || s === "sb") return "var(--pw-pb)";
  return "var(--foreground)";
}

function words(p: ProgressChartPoint, showMedian: boolean): string {
  const best = p.bestMs != null ? `best ${lapTime(p.bestMs)}` : "no clean lap";
  const med = showMedian && p.medianMs != null ? `, typical ${lapTime(p.medianMs)}` : "";
  const tag = p.status === "pb" ? ", a PB" : p.status === "rec" ? ", the family record" : "";
  return `${p.xLabel}: ${best}${med}${tag}`;
}

interface Ctx {
  byX: ReadonlyMap<number, ProgressChartPoint>;
  showMedian: boolean;
  open: (id: string) => void;
}

function Dot({ cx, cy, p, ctx, none }: { cx: number; cy: number; p: ProgressChartPoint; ctx: Ctx; none: boolean }) {
  const onKey = (e: KeyboardEvent<SVGGElement>) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    ctx.open(p.id);
  };
  const strong = p.status === "pb" || p.status === "rec";
  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={`${words(p, ctx.showMedian)}. Open the session`}
      onClick={() => ctx.open(p.id)}
      onKeyDown={onKey}
      style={{ cursor: "pointer" }}
      data-session={p.id}
    >
      <circle cx={cx} cy={cy} r={HIT_R} fill="transparent" />
      {none ? (
        <text x={cx} y={cy - 4} textAnchor="middle" fill="var(--pw-faint)" style={{ font: "600 13px var(--pw-font-sans)" }}>
          -
        </text>
      ) : (
        <circle cx={cx} cy={cy} r={strong ? 7 : 5.5} fill={dotFill(p.status)} />
      )}
      {strong && !none && (
        <text x={cx + 11} y={cy + 4} fill={dotFill(p.status)} style={{ font: "800 11px var(--pw-font-sans)" }}>
          {p.status === "rec" ? "REC" : "PB"}
        </text>
      )}
    </g>
  );
}

function renderer(kind: "clean" | "none", ctx: Ctx) {
  return (props: DotItemDotProps): ReactNode => {
    const { cx, cy, payload, index } = props;
    const key = `${kind}-${index}`;
    const row = payload as Record<string, number> | undefined;
    const p = row && finite(row.x) ? ctx.byX.get(row.x) : undefined;
    if (!p || !finite(cx) || !finite(cy) || !finite(row?.[kind])) return <g key={key} />;
    return <Dot key={key} cx={cx} cy={cy} p={p} ctx={ctx} none={kind === "none"} />;
  };
}

function Tip({ active, label, byX, showMedian }: { active?: boolean; label?: number | string; byX: Ctx["byX"]; showMedian: boolean }) {
  if (!active || label == null) return null;
  const p = byX.get(Number(label));
  if (!p) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__header">{p.xLabel}</div>
      <div className="chart-tooltip__item">
        <span className="chart-tooltip__label">Best clean lap</span>
        <span className="chart-tooltip__value pw-num">{lapTime(p.bestMs)}</span>
      </div>
      {showMedian && (
        <div className="chart-tooltip__item">
          <span className="chart-tooltip__label">Typical clean lap</span>
          <span className="chart-tooltip__value pw-num">{lapTime(p.medianMs)}</span>
        </div>
      )}
      {p.carName && (
        <div className="chart-tooltip__item">
          <span className="chart-tooltip__label">Car</span>
          <span className="chart-tooltip__value">{p.carName}</span>
        </div>
      )}
    </div>
  );
}

function signature(points: readonly ProgressChartPoint[], line: ProgressChartLine | null | undefined, median: boolean): string {
  return `${points.map((p) => `${p.id}:${p.x}:${p.xLabel}:${p.bestMs ?? ""}:${p.medianMs ?? ""}:${p.status}`).join("|")}#${line ? `${line.ms}:${line.tone}:${line.label}` : ""}#${median ? 1 : 0}`;
}

export const ProgressChart = memo(function ProgressChart({
  points,
  line,
  height = 240,
  showMedian,
  onOpen,
  label,
}: ProgressChartProps) {
  const sig = signature(points, line, showMedian);
  const openRef = useRef(onOpen);
  useEffect(() => {
    openRef.current = onOpen;
  }, [onOpen]);
  const open = useCallback((id: string) => openRef.current(id), []);

  const model = useMemo(() => {
    const lap: LapPoint[] = points.map((p) => ({ id: p.id, x: p.x, xLabel: p.xLabel, ms: p.bestMs, clean: true }));
    const extra = [
      ...(showMedian ? points.map((p) => p.medianMs).filter((v): v is number => finite(v)) : []),
      ...(line ? [line.ms] : []),
    ];
    const m = lapChartModel(lap, extra);
    const byX = new Map(points.map((p) => [p.x, p]));
    // At most ~8 labelled sessions on the axis (the last one always); every dot stays.
    const every = Math.max(1, Math.ceil(m.xTicks.length / 8));
    const xTicks = m.xTicks.filter((_, i, all) => i % every === 0 || i === all.length - 1);
    const rows = m.rows.map((r) => {
      const p = byX.get(r.x!);
      return showMedian && p && finite(p.medianMs) ? { ...r, median: p.medianMs } : r;
    });
    return { ...m, rows, byX, xTicks };
  }, [sig]);

  const ctx = useMemo<Ctx>(() => ({ byX: model.byX, showMedian, open }), [model, showMedian, open]);
  const dots = useMemo(() => ({ clean: renderer("clean", ctx), none: renderer("none", ctx) }), [ctx]);

  const chart = useMemo(
    () => (
      <LineChart data={model.rows} height={height} margin={MARGIN} role="group" aria-label={label}>
        <LineChart.Grid vertical={false} />
        <LineChart.XAxis
          dataKey="x"
          type="number"
          domain={model.xDomain}
          ticks={model.xTicks}
          interval={0}
          tickFormatter={(x: number) => model.byX.get(x)?.xLabel ?? ""}
          allowDecimals={false}
        />
        <LineChart.YAxis
          reversed
          width={56}
          domain={model.domain}
          ticks={model.ticks}
          tickFormatter={(v: number) => timeTick(v)}
          allowDataOverflow
        />
        {line && (
          <ReferenceLine
            y={line.ms}
            stroke={line.tone === "rec" ? "var(--pw-rec)" : "var(--pw-line-strong)"}
            strokeDasharray="5 4"
            strokeWidth={1.5}
            ifOverflow="extendDomain"
            label={{ value: line.label, position: "insideTopRight", fill: line.tone === "rec" ? "var(--pw-rec)" : "var(--muted)", fontSize: 11 }}
          />
        )}
        {showMedian && (
          <LineChart.Line
            dataKey="median"
            name="Typical clean lap"
            type="linear"
            stroke="var(--muted)"
            strokeDasharray="4 4"
            strokeWidth={1.5}
            connectNulls
            dot={{ r: 3.5, fill: "var(--surface)", stroke: "var(--muted)", strokeWidth: 1.5, strokeDasharray: "0" }}
            activeDot={false}
            isAnimationActive={false}
          />
        )}
        <LineChart.Line
          dataKey="clean"
          name="Best clean lap"
          type="linear"
          stroke="var(--pw-line-strong)"
          strokeWidth={2}
          connectNulls
          dot={dots.clean}
          activeDot={false}
          isAnimationActive={false}
        />
        <LineChart.Line
          dataKey="none"
          name="No clean lap"
          stroke="none"
          dot={dots.none}
          activeDot={false}
          isAnimationActive={false}
          legendType="none"
        />
        <LineChart.Tooltip cursor={false} content={<Tip byX={model.byX} showMedian={showMedian} />} />
      </LineChart>
    ),
    [model, dots, line, height, label, showMedian],
  );

  if (model.empty) return <p className="m-0 py-6 text-center text-sm text-muted">No clean laps here yet: drive a clean lap.</p>;
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-medium text-muted">
        <span aria-hidden="true">↑ faster</span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-0.5 w-5 bg-[var(--pw-line-strong)]" />
          Best clean lap
        </span>
        {showMedian && (
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block w-5 border-t-2 border-dashed border-[var(--muted)]" />
            Typical clean lap
          </span>
        )}
      </div>
      {chart}
    </div>
  );
});
