// "Against the AI" chart (AI pace spec 8): one dot per session here, the gap from the driver's best clean lap to the
// typical AI car's best lap in percent, the y axis REVERSED so faster is up (as on every Review chart), a zero line
// "level with the typical AI car", each dot labelled with its AI difficulty. Tooltip: date, AI difficulty, typical AI
// best, your best, rank. Every dot has a 44 px target and opens that session (tap, Enter or Space). Sessions without a
// clean lap have no gap and are not drawn (the list under the chart has them). Lazy page only (Recharts).

import { LineChart } from "@heroui-pro/react/line-chart";
import { memo, useCallback, useEffect, useMemo, useRef, type KeyboardEvent, type ReactNode } from "react";
import { ReferenceLine, type DotItemDotProps } from "recharts";
import { lapTime } from "../../../lib/format";
import { dotWords, gapAxis, gapTick, ordinal, pctWords, type AiDot } from "../../../lib/review/aipace";
import { finite } from "../../../lib/review/words";

const MARGIN = { top: 22, right: 18, bottom: 0, left: 0 } as const;
const HIT_R = 22;

type Row = Record<string, number> & { x: number; gap: number };

interface Ctx {
  byX: ReadonlyMap<number, AiDot>;
  open: (id: string) => void;
}

function Dot({ cx, cy, d, ctx }: { cx: number; cy: number; d: AiDot; ctx: Ctx }) {
  const onKey = (e: KeyboardEvent<SVGGElement>) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    ctx.open(d.sessionId);
  };
  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={`${d.xLabel}: ${dotWords(d)}. Open the session`}
      onClick={() => ctx.open(d.sessionId)}
      onKeyDown={onKey}
      style={{ cursor: "pointer" }}
      data-session={d.sessionId}
    >
      <circle cx={cx} cy={cy} r={HIT_R} fill="transparent" />
      <circle cx={cx} cy={cy} r={6} fill="var(--foreground)" />
      <text x={cx} y={cy - 11} textAnchor="middle" fill="var(--foreground)" style={{ font: "700 13px var(--pw-font-num)" }}>
        {d.level}
      </text>
    </g>
  );
}

function renderer(ctx: Ctx) {
  return (props: DotItemDotProps): ReactNode => {
    const { cx, cy, payload, index } = props;
    const key = `ai-${index}`;
    const row = payload as Row | undefined;
    const d = row && finite(row.x) ? ctx.byX.get(row.x) : undefined;
    if (!d || !finite(cx) || !finite(cy)) return <g key={key} />;
    return <Dot key={key} cx={cx} cy={cy} d={d} ctx={ctx} />;
  };
}

function Tip({ active, label, byX }: { active?: boolean; label?: number | string; byX: Ctx["byX"] }) {
  if (!active || label == null) return null;
  const d = byX.get(Number(label));
  if (!d) return null;
  const rows: [string, string, boolean][] = [
    ["AI difficulty", String(d.level), true],
    ["Typical AI best", lapTime(d.aiRefMs), true],
    ["Your best", lapTime(d.driverBestMs), true],
    ["Gap", pctWords(d.gapPct) ?? "-", false],
  ];
  if (d.rank != null && d.fieldSize != null) rows.push(["On best laps", `${ordinal(d.rank)} of ${d.fieldSize}`, false]);
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__header">{d.xLabel}</div>
      {rows.map(([k, v, num]) => (
        <div key={k} className="chart-tooltip__item">
          <span className="chart-tooltip__label">{k}</span>
          <span className={`chart-tooltip__value${num ? " pw-num" : ""}`}>{v}</span>
        </div>
      ))}
    </div>
  );
}

export interface AiPaceChartProps {
  dots: readonly AiDot[];
  onOpen: (sessionId: string) => void;
  height?: number;
  /** Whose best laps ("your" / "Sam's"): the chart's accessible name. */
  poss?: string;
}

export const AiPaceChart = memo(function AiPaceChart({ dots, onOpen, height = 220, poss = "your" }: AiPaceChartProps) {
  const openRef = useRef(onOpen);
  useEffect(() => {
    openRef.current = onOpen;
  }, [onOpen]);
  const open = useCallback((id: string) => openRef.current(id), []);
  const sig = dots.map((d) => `${d.sessionId}:${d.gapPct ?? ""}:${d.level}:${d.xLabel}`).join("|");

  const model = useMemo(() => {
    const plotted = dots.filter((d): d is AiDot & { gapPct: number } => d.gapPct != null);
    const rows: Row[] = plotted.map((d, i) => ({ x: i + 1, gap: d.gapPct }));
    const byX = new Map(plotted.map((d, i) => [i + 1, d]));
    const axis = gapAxis(rows.map((r) => r.gap));
    const every = Math.max(1, Math.ceil(rows.length / 8));
    const xTicks = rows.map((r) => r.x).filter((_, i, all) => i % every === 0 || i === all.length - 1);
    return { rows, byX, axis, xTicks };
  }, [sig]);

  const ctx = useMemo<Ctx>(() => ({ byX: model.byX, open }), [model, open]);
  const dot = useMemo(() => renderer(ctx), [ctx]);

  if (!model.rows.length) return null;
  const pad = model.rows.length === 1 ? 1 : 0.5;
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-medium text-muted">
        <span aria-hidden="true">↑ faster than the typical AI car</span>
        <span>The number on a dot is the AI difficulty</span>
      </div>
      <LineChart
        data={model.rows}
        height={height}
        margin={MARGIN}
        role="group"
        aria-label={`${poss.charAt(0).toUpperCase()}${poss.slice(1)} best lap against the typical AI car per session, higher is faster`}
      >
        <LineChart.Grid vertical={false} />
        <LineChart.XAxis
          dataKey="x"
          type="number"
          domain={[1 - pad, model.rows.length + pad]}
          ticks={model.xTicks}
          interval={0}
          tickFormatter={(x: number) => model.byX.get(x)?.xLabel ?? ""}
          allowDecimals={false}
        />
        <LineChart.YAxis
          reversed
          width={84}
          domain={[-model.axis.max, model.axis.max]}
          ticks={model.axis.ticks}
          tickFormatter={(v: number) => gapTick(v)}
        />
        <ReferenceLine
          y={0}
          stroke="var(--pw-line-strong)"
          strokeDasharray="5 4"
          strokeWidth={1.5}
          label={{ value: "level with the typical AI car", position: "insideBottomRight", fill: "var(--muted)", fontSize: 11 }}
        />
        <LineChart.Line
          dataKey="gap"
          name="Gap to the typical AI car"
          type="linear"
          stroke="none"
          dot={dot}
          activeDot={false}
          isAnimationActive={false}
        />
        <LineChart.Tooltip cursor={false} content={<Tip byX={model.byX} />} />
      </LineChart>
    </div>
  );
});
