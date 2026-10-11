// Lap times (spec 6.3 #4, 10.4): Pro LineChart, a dot per lap, the y axis reversed and labelled "faster ↑", filled
// dots for clean laps and hollow ones for laps that are not clean, the reference lap as a dashed line, the best clean
// lap tagged. Tap a clean lap -> Compare that lap; tap a lap that is not clean -> its reason in words, with Compare.
// Nothing animates (spec 9.5: the data does not move on its own).

import { Button, Card } from "@heroui/react";
import { LineChart } from "@heroui-pro/react/line-chart";
import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { ReferenceLine } from "recharts";
import { TimingValue } from "../../../components/ui";
import type { LapRow } from "../../../lib/api";
import type { RefLap } from "../../../lib/endpoints/review";
import { lapTime } from "../../../lib/format";
import { router } from "../../../lib/router";
import { clockTick, lapChartRows, lapPoints, timeAxis, type LapPoint } from "../../../lib/review/charts";
import { comparePath } from "../../../lib/review/links";
import type { TimingStatus } from "../../../components/ui/types";

export interface LapTimesCardProps {
  sessionId: string;
  laps: readonly LapRow[];
  bestLapId: number | null;
  bestStatus: TimingStatus;
  refLap: RefLap | null;
  /** One plain sentence under the title (beginners, intermediate). */
  caption: boolean;
}

interface DotProps {
  cx?: number;
  cy?: number;
  index: number;
}

export function LapTimesCard({ sessionId, laps, bestLapId, bestStatus, refLap, caption }: LapTimesCardProps) {
  const points = useMemo(() => lapPoints(laps, bestLapId), [laps, bestLapId]);
  const rows = useMemo(() => lapChartRows(points), [points]);
  const refS = refLap?.lap_time_ms ? refLap.lap_time_ms / 1000 : null;
  const axis = useMemo(() => timeAxis(points.map((p) => p.s), refS), [points, refS]);
  const [picked, setPicked] = useState<LapPoint | null>(null);
  const byLap = useMemo(() => new Map(points.map((p) => [p.lap, p])), [points]);
  const refOther = refLap && refLap.session_id !== sessionId;
  const bestColour = bestStatus === "sb" ? "var(--pw-pb)" : "var(--foreground)";

  function open(p: LapPoint) {
    if (p.clean) router.navigate(comparePath(sessionId, { ref: refLap?.id ?? null, lap: p.lapId }));
    else setPicked(p);
  }

  function onKey(e: KeyboardEvent, p: LapPoint) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open(p);
    }
  }

  const dot =
    (series: "clean" | "other") =>
    ({ cx, cy, index }: DotProps): ReactNode => {
      const row = rows[index];
      const p = row ? byLap.get(row.lap as number) : undefined;
      if (!p || cx == null || cy == null || (series === "clean") !== p.clean) return <g key={`${series}-${index}`} />;
      const label = `Lap ${p.lap}, ${lapTime(p.ms)}${p.clean ? "" : `, not clean: ${p.reason}`}${p.best ? ", best lap" : ""}`;
      return (
        <g
          key={`${series}-${index}`}
          role="button"
          tabIndex={0}
          aria-label={p.clean ? `${label}. Compare this lap` : label}
          onClick={() => open(p)}
          onKeyDown={(e) => onKey(e, p)}
          className="cursor-pointer outline-none focus-visible:[&>circle:last-child]:stroke-focus"
        >
          {/* A 44 px touch target around a small dot (P12). */}
          <circle cx={cx} cy={cy} r={22} fill="transparent" />
          {p.clean ? (
            <circle cx={cx} cy={cy} r={p.best ? 7 : 5} fill={p.best ? bestColour : "var(--foreground)"} />
          ) : (
            <circle cx={cx} cy={cy} r={5} fill="var(--surface)" stroke="var(--pw-faint)" strokeWidth={2} />
          )}
        </g>
      );
    };

  return (
    <Card className="gap-3 p-5">
      <Card.Header className="flex-row flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <Card.Title className="text-base font-semibold">Lap times</Card.Title>
        <span className="text-sm text-muted">higher = faster · tap a lap to compare it</span>
      </Card.Header>
      {caption && (
        <p className="m-0 text-sm text-muted">
          Each dot is one lap. Higher on the chart means a faster lap; hollow dots are laps that did not count.
        </p>
      )}
      {points.length > 0 && <span className="-mb-2 pl-1 text-xs text-muted" aria-hidden="true">↑ faster</span>}
      {points.length === 0 ? (
        <p className="m-0 py-6 text-center text-sm text-muted">No timed laps in this session.</p>
      ) : (
        <LineChart data={rows} height={230} margin={{ top: 12, right: 12, bottom: 4, left: 4 }}>
          <LineChart.Grid vertical={false} stroke="var(--surface-tertiary)" />
          <LineChart.XAxis
            dataKey="lap"
            type="number"
            domain={["dataMin - 0.5", "dataMax + 0.5"]}
            allowDecimals={false}
            ticks={points.map((p) => p.lap)}
            tickLine={false}
            axisLine={false}
            tick={{ fill: "var(--muted)", fontSize: 13, style: { fontSize: 13 } }}
          />
          <LineChart.YAxis
            reversed
            domain={axis.domain}
            ticks={axis.ticks}
            tickFormatter={(v: number) => clockTick(v)}
            width={56}
            tickLine={false}
            axisLine={false}
            tick={{ fill: "var(--muted)", fontSize: 14, fontFamily: "var(--pw-font-num)", style: { fontSize: 14 } }}
          />
          {refS != null && (
            <ReferenceLine
              y={refS}
              stroke="var(--pw-ref)"
              strokeDasharray="5 4"
              strokeWidth={1.5}
              ifOverflow="extendDomain"
            />
          )}
          <LineChart.Tooltip
            cursor={false}
            content={({ active, label }) => {
              const p = active ? byLap.get(Number(label)) : undefined;
              if (!p) return null;
              return (
                <div className="rounded-xl bg-overlay px-3 py-2 text-sm shadow-overlay">
                  <div className="font-semibold">Lap {p.lap}</div>
                  <div className="pw-num text-base">{lapTime(p.ms)}</div>
                  <div className="text-muted">{p.clean ? (p.best ? "best clean lap" : "clean") : `not clean: ${p.reason}`}</div>
                </div>
              );
            }}
          />
          <LineChart.Line
            dataKey="clean"
            type="linear"
            stroke="var(--pw-line-strong)"
            strokeWidth={1.5}
            connectNulls
            isAnimationActive={false}
            dot={dot("clean")}
            activeDot={false}
          />
          <LineChart.Line
            dataKey="other"
            type="linear"
            stroke="none"
            isAnimationActive={false}
            dot={dot("other")}
            activeDot={false}
            legendType="none"
          />
        </LineChart>
      )}
      <div className={`flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted ${points.length ? "" : "hidden"}`} aria-label="Legend">
        <span className="flex items-center gap-1.5">
          <i className="inline-block size-2.5 rounded-full bg-foreground" /> clean lap
        </span>
        <span className="flex items-center gap-1.5">
          <i className="inline-block size-2.5 rounded-full border-2 border-faint" /> not clean
        </span>
        {bestLapId != null && (
          <span className="flex items-center gap-1.5">
            <i className="inline-block size-3 rounded-full" style={{ background: bestColour }} />
            {bestStatus === "sb" ? "best today (SB)" : "best lap"}
          </span>
        )}
        {refS != null && (
          <span className="flex items-center gap-1.5">
            <i className="inline-block h-0 w-4 border-t-2 border-dashed border-ref" /> reference{" "}
            <TimingValue ms={refLap?.lap_time_ms} kind="lap" size="body" />
            {refOther ? " (another session)" : refLap ? ` (lap ${refLap.lap_number})` : ""}
          </span>
        )}
      </div>
      {picked && (
        <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-surface-secondary px-4 py-2.5 text-sm" role="status">
          <span>
            Lap {picked.lap} · <span className="pw-num text-base">{lapTime(picked.ms)}</span> · not clean: {picked.reason}
          </span>
          <Button
            size="sm"
            variant="secondary"
            className="ml-auto min-h-11"
            onPress={() => router.navigate(comparePath(sessionId, { ref: refLap?.id ?? null, lap: picked.lapId }))}
          >
            Compare this lap
          </Button>
          <Button size="sm" variant="ghost" className="min-h-11" onPress={() => setPicked(null)}>
            Close
          </Button>
        </div>
      )}
    </Card>
  );
}
