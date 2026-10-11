// Lap times as a HeroUI Pro LineChart (design spec v2, 6.3 #4 and #7, 6.9 "Getting faster?", 10.4): one dot per lap
// (or per session), the y axis REVERSED and labelled "↑ faster", m:ss.S ticks. Clean laps are filled dots joined by
// a line, coloured by their timing status (green PB / SB, purple REC only with D2 data, else plain); laps that are
// not clean are hollow (tap shows the reason in words); a lap without a time shows "-" at the slow edge; far slower
// not-clean laps (out laps) sit at the slow edge marked off scale (lib/viz/charts.ts lapChartModel). Reference lines
// (the reference lap, the family record) are dashed with a label. Tap or press a clean dot -> `onSelect` (Compare).
//
// Every dot has a 44 px target (P12) and is keyboard focusable. Lazy pages only: this module imports Recharts.

import { LineChart } from "@heroui-pro/react/line-chart";
import { memo, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ReferenceLine, type DotItemDotProps } from "recharts";
import {
  lapChartModel,
  lapPointsSignature,
  lapPointWords,
  timeTick,
  type LapChartModel,
  type LapDotKind,
  type LapPoint,
} from "../../lib/viz/charts";
import { lapTime } from "../../lib/format";
import { finite } from "../../lib/viz/scale";

export interface LapTimeLine {
  ms: number;
  label: string;
  /** "ref" cyan (the reference lap), "neutral" grey, "rec" purple: ONLY with D2 data (spec 4.6 / 14.5 #5). */
  tone: "ref" | "rec" | "neutral";
}

export interface LapTimesChartProps {
  points: readonly LapPoint[];
  lines?: readonly LapTimeLine[];
  height?: number;
  /** Word before the x value in captions ("Lap"; "" for dates). */
  xName?: string;
  /** Tap / Enter on a clean dot (e.g. open Compare with that lap). */
  onSelect?: (p: LapPoint) => void;
  /** Accessible name ("Lap times, higher is faster"). */
  label: string;
  className?: string;
}

const MARGIN = { top: 12, right: 16, bottom: 0, left: 0 } as const;
const Y_AXIS_W = 56;
const HIT_R = 22; // 44 px target

const LINE_COLOUR: Record<LapTimeLine["tone"], string> = {
  ref: "var(--pw-ref)",
  rec: "var(--pw-rec)",
  neutral: "var(--pw-line-strong)",
};

function dotColour(p: LapPoint): string {
  switch (p.status) {
    case "rec":
      return "var(--pw-rec)";
    case "pb":
    case "sb":
      return "var(--pw-pb)";
    default:
      return "var(--foreground)";
  }
}

interface DotCtx {
  model: LapChartModel;
  xName: string;
  onPick: (p: LapPoint) => void;
  canSelect: boolean;
}

function LapDot({ kind, cx, cy, p, ctx }: { kind: LapDotKind; cx: number; cy: number; p: LapPoint; ctx: DotCtx }) {
  const off = ctx.model.offScale.has(p.id);
  const words = lapPointWords(p, { xName: ctx.xName, offScale: off });
  const action = kind === "clean" && ctx.canSelect ? ", open in Compare" : kind === "other" ? ", show why" : "";
  const onKey = (e: KeyboardEvent<SVGGElement>) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    ctx.onPick(p);
  };
  const strong = p.status === "rec" || p.status === "pb" || p.status === "sb";
  return (
    <g
      role={kind === "none" ? undefined : "button"}
      tabIndex={kind === "none" ? undefined : 0}
      aria-label={kind === "none" ? undefined : `${words}${action}`}
      onClick={kind === "none" ? undefined : () => ctx.onPick(p)}
      onKeyDown={kind === "none" ? undefined : onKey}
      style={{ cursor: kind === "none" ? undefined : "pointer" }}
      data-lap={String(p.id)}
    >
      {kind !== "none" && <circle cx={cx} cy={cy} r={HIT_R} fill="transparent" />}
      {kind === "clean" && <circle cx={cx} cy={cy} r={strong ? 7 : 5} fill={dotColour(p)} />}
      {kind === "other" && <circle cx={cx} cy={cy} r={5} fill="var(--surface)" stroke="var(--pw-faint)" strokeWidth={2} />}
      {kind === "other" && off && (
        <path d={`M${cx - 4} ${cy + 9} L${cx + 4} ${cy + 9} L${cx} ${cy + 14} Z`} fill="var(--pw-faint)" aria-hidden="true" />
      )}
      {kind === "none" && (
        <text x={cx} y={cy - 4} textAnchor="middle" fill="var(--pw-faint)" style={{ font: "600 12px var(--pw-font-sans)" }}>
          -
        </text>
      )}
      {p.tag && kind === "clean" && (
        <text x={cx + 11} y={cy + 4} textAnchor="start" fill={dotColour(p)} style={{ font: "800 11px var(--pw-font-sans)" }}>
          {p.tag}
        </text>
      )}
    </g>
  );
}

function dotRenderer(kind: LapDotKind, ctx: DotCtx) {
  return (props: DotItemDotProps): ReactNode => {
    const { cx, cy, payload, index } = props;
    const key = `${kind}-${index}`;
    const x = (payload as Record<string, number> | undefined)?.x;
    const p = finite(x) ? ctx.model.byX.get(x) : undefined;
    if (!p || !finite(cx) || !finite(cy) || !finite((payload as Record<string, number>)[kind])) return <g key={key} />;
    return <LapDot key={key} kind={kind} cx={cx} cy={cy} p={p} ctx={ctx} />;
  };
}

function LapTooltip({
  active,
  label,
  model,
  xName,
}: {
  active?: boolean;
  label?: number | string;
  model: LapChartModel;
  xName: string;
}) {
  if (!active || label == null) return null;
  const p = model.byX.get(Number(label));
  if (!p) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__header">{xName ? `${xName} ${p.xLabel ?? p.x}` : (p.xLabel ?? String(p.x))}</div>
      <div className="chart-tooltip__item">
        <span className="chart-tooltip__label">{p.clean ? "Clean" : `Not clean${p.reason ? `: ${p.reason}` : ""}`}</span>
        <span className="chart-tooltip__value pw-num">{lapTime(p.ms)}</span>
      </div>
    </div>
  );
}

export const LapTimesChart = memo(function LapTimesChart({
  points,
  lines = [],
  height = 220,
  xName = "Lap",
  onSelect,
  label,
  className,
}: LapTimesChartProps) {
  // Parents rebuild `points` / `lines` / `onSelect` on every render: key the model on the content and keep the
  // callback in a ref, so a parent re-render never re-runs Recharts or re-mounts the dots (focus would be lost).
  const sig = lapPointsSignature(points, lines.map((l) => l.ms)) + lines.map((l) => `${l.label}:${l.tone}`).join(",");
  const model = useMemo(() => lapChartModel(points, lines.map((l) => l.ms)), [sig]);
  const refLines = useMemo(() => lines, [sig]);
  const selectRef = useRef(onSelect);
  useEffect(() => {
    selectRef.current = onSelect;
  }, [onSelect]);
  const canSelect = onSelect != null;
  const [picked, setPicked] = useState<LapPoint | null>(null);
  const onPick = useCallback((p: LapPoint) => {
    const select = selectRef.current;
    if (p.clean && select) select(p);
    else setPicked((prev) => (prev?.id === p.id ? null : p));
  }, []);
  const renderers = useMemo(() => {
    const ctx: DotCtx = { model, xName, onPick, canSelect };
    return { clean: dotRenderer("clean", ctx), other: dotRenderer("other", ctx), none: dotRenderer("none", ctx) };
  }, [model, xName, onPick, canSelect]);
  // The chart element itself is memoised: Recharts re-mounts its dot layer on every render (z-index portal), so a
  // parent re-render with the same data must not reach it.
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
          tickFormatter={(x: number) => model.byX.get(x)?.xLabel ?? String(x)}
          allowDecimals={false}
        />
        <LineChart.YAxis
          reversed
          width={Y_AXIS_W}
          domain={model.domain}
          ticks={model.ticks}
          tickFormatter={(v: number) => timeTick(v)}
          allowDataOverflow
        />
        {refLines.map((l, i) => (
          <ReferenceLine
            key={`line${i}`}
            y={l.ms}
            stroke={LINE_COLOUR[l.tone]}
            strokeDasharray="5 4"
            strokeWidth={1.5}
            ifOverflow="extendDomain"
            label={{ value: l.label, position: "insideTopRight", fill: l.tone === "rec" ? "var(--pw-rec)" : "var(--muted)", fontSize: 11 }}
          />
        ))}
        <LineChart.Line
          dataKey="clean"
          name="Clean laps"
          type="linear"
          stroke="var(--pw-line-strong)"
          strokeWidth={1.5}
          connectNulls
          dot={renderers.clean}
          activeDot={false}
          isAnimationActive={false}
        />
        <LineChart.Line
          dataKey="other"
          name="Not clean"
          stroke="none"
          dot={renderers.other}
          activeDot={false}
          isAnimationActive={false}
          legendType="none"
        />
        <LineChart.Line
          dataKey="none"
          name="No time"
          stroke="none"
          dot={renderers.none}
          activeDot={false}
          isAnimationActive={false}
          legendType="none"
        />
        <LineChart.Tooltip cursor={false} content={<LapTooltip model={model} xName={xName} />} />
      </LineChart>
    ),
    [model, renderers, refLines, height, label, xName],
  );
  if (model.empty) {
    return (
      <div className={className}>
        <p className="m-0 text-sm text-muted">No timed laps yet: drive a clean lap.</p>
      </div>
    );
  }
  return (
    <div className={className}>
      <div className="mb-1 text-xs font-medium text-muted" aria-hidden="true">
        ↑ faster
      </div>
      {chart}
      <p className="m-0 mt-1 min-h-5 text-xs text-muted" aria-live="polite">
        {picked ? lapPointWords(picked, { xName, offScale: model.offScale.has(picked.id) }) : null}
      </p>
    </div>
  );
});
