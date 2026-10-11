// "Where the time is" (spec 6.3 #5, 10.4): Pro BarChart (horizontal bars) of each corner's mean time lost or gained
// against the reference over the session's compared laps, most lost first, with neutral words from the signs of the
// brake point and speed differences ("braked about 12 m earlier"). Descriptions, never advice.

import { Card } from "@heroui/react";
import { BarChart } from "@heroui-pro/react/bar-chart";
import { useMemo } from "react";
import { Cell, ReferenceLine } from "recharts";
import type { CornerSummaryRow, ReviewTrackModel } from "../../../lib/endpoints/review";
import { cornerBars, deltaAxis, type CornerBar } from "../../../lib/review/charts";
import { MINUS } from "../../../lib/format";

const TONE_FILL: Record<CornerBar["tone"], string> = {
  lost: "var(--pw-behind)",
  gained: "var(--pw-ahead)",
  level: "var(--muted)",
};

function lostOrGained(b: CornerBar): string {
  const s = Math.abs(b.deltaS).toFixed(2);
  if (b.tone === "lost") return `about ${s} s a lap lost`;
  if (b.tone === "gained") return `about ${s} s a lap gained`;
  return "level with the reference";
}

export function WhereTimeIsCard({
  summary,
  model,
  caption,
  signed,
}: {
  summary: readonly CornerSummaryRow[];
  model: ReviewTrackModel | null | undefined;
  caption: boolean;
  /** Signed numbers on the axis (not for beginners: they get words). */
  signed: boolean;
}) {
  const bars = useMemo(() => cornerBars(summary, model), [summary, model]);
  const rows = useMemo(() => bars.map((b) => ({ corner: b.label, key: b.key, value: b.deltaS })), [bars]);
  const described = bars.filter((b) => b.tone !== "level").slice(0, 4);
  const axis = useMemo(() => deltaAxis(bars.map((b) => b.deltaS)), [bars]);
  const tick = (v: number): string => {
    if (Math.abs(v) < 1e-9) return "0";
    const t = Math.abs(v).toFixed(axis.digits);
    return signed ? `${v > 0 ? "+" : MINUS}${t}` : t;
  };

  return (
    <Card className="gap-3 p-5">
      <Card.Header className="flex-row flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <Card.Title className="text-base font-semibold">Where the time is</Card.Title>
        <span className="text-sm text-muted">seconds a lap, against the reference</span>
      </Card.Header>
      {caption && (
        <p className="m-0 text-sm text-muted">
          Each bar is a corner. Bars to the right lost time against your reference lap, bars to the left gained time.
        </p>
      )}
      {bars.length === 0 ? (
        <p className="m-0 py-6 text-center text-sm text-muted">
          No corner comparison yet: it needs a reference lap and a learned track.
        </p>
      ) : (
        <BarChart data={rows} layout="vertical" height={Math.max(160, 30 * rows.length + 30)} margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
          <BarChart.Grid horizontal={false} stroke="var(--surface-tertiary)" />
          <BarChart.XAxis
            type="number"
            domain={axis.domain}
            ticks={axis.ticks}
            tickLine={false}
            axisLine={false}
            tick={{ fill: "var(--muted)", fontSize: 14, fontFamily: "var(--pw-font-num)", style: { fontSize: 14 } }}
            tickFormatter={tick}
          />
          <BarChart.YAxis
            type="category"
            dataKey="corner"
            width={52}
            tickLine={false}
            axisLine={false}
            interval={0}
            tick={{ fill: "var(--foreground)", fontSize: 13, fontWeight: 600, style: { fontSize: 13 } }}
          />
          <ReferenceLine x={0} stroke="var(--muted)" strokeWidth={1.5} />
          <BarChart.Tooltip
            cursor={{ fill: "var(--surface-secondary)" }}
            content={({ active, payload }) => {
              const key = active ? (payload?.[0]?.payload as { key?: string } | undefined)?.key : undefined;
              const b = bars.find((x) => x.key === key);
              if (!b) return null;
              return (
                <div className="max-w-64 rounded-xl bg-overlay px-3 py-2 text-sm shadow-overlay">
                  <div className="font-semibold">{b.full}</div>
                  <div>{lostOrGained(b)}</div>
                  {b.words.length > 0 && <div className="text-muted">{b.words.join(", ")}</div>}
                </div>
              );
            }}
          />
          <BarChart.Bar dataKey="value" radius={4} isAnimationActive={false} maxBarSize={18}>
            {bars.map((b) => (
              <Cell key={b.key} fill={TONE_FILL[b.tone]} />
            ))}
          </BarChart.Bar>
        </BarChart>
      )}
      {described.length > 0 && (
        <ul className="m-0 grid list-none gap-2 p-0">
          {described.map((b) => (
            <li key={b.key} className="text-sm leading-snug">
              <span className="font-semibold">{b.full}</span>
              <span className="text-muted">
                {" "}
                · {lostOrGained(b)}
                {b.words.length > 0 ? ` · ${b.words.join(", ")}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
