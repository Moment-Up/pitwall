// "Getting steadier?" (spec 6.9, D5): the spread of clean laps per session (slowest minus fastest) as a Pro
// BarChart, one computed sentence, smaller is steadier. Before D5 the server sends no spread: "-" and why.

import { Card } from "@heroui/react";
import { BarChart } from "@heroui-pro/react/bar-chart";
import { useMemo } from "react";
import { Glossary, Unknown } from "../../../components/ui";
import { sessionLabels, type SessionPoint } from "../../../lib/review/progress";
import { spreadSeconds } from "../../../lib/review/words";

export function SteadierCard({
  points,
  sentence,
  available,
  caption,
  glossary,
}: {
  points: readonly SessionPoint[];
  sentence: string;
  /** D5 answered (spreads are known). */
  available: boolean;
  caption: boolean;
  glossary: boolean;
}) {
  const rows = useMemo(() => {
    const labels = sessionLabels(points, Date.now());
    return points
      .map((p, i) => ({ day: labels[i] ?? "", id: p.sessionId, spread: p.spreadMs }))
      .filter((r): r is { day: string; id: string; spread: number } => r.spread != null)
      .map((r) => ({ day: r.day, id: r.id, v: r.spread / 1000 }));
  }, [points]);

  return (
    <Card className="gap-3 p-5">
      <Card.Header className="gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <Card.Title className="text-base font-semibold">Getting steadier?</Card.Title>
          {glossary && <Glossary term="steadiness" className="-my-2 -mr-2" />}
        </div>
        {available ? (
          <p className="m-0 text-base leading-snug text-foreground">{sentence}</p>
        ) : (
          <p className="m-0 flex items-center gap-2 text-sm text-muted">
            <Unknown className="text-xl" />
            The spread of clean laps per session needs a newer Pitwall server.
          </p>
        )}
      </Card.Header>
      {available && caption && rows.length > 0 && (
        <p className="m-0 text-sm text-muted">Each bar is how far apart the clean laps of one session were. Smaller is steadier.</p>
      )}
      {available && rows.length > 0 && (
        <BarChart data={rows} height={170} margin={{ top: 22, right: 8, bottom: 0, left: 0 }}>
          <BarChart.Grid vertical={false} stroke="var(--surface-tertiary)" />
          <BarChart.XAxis dataKey="day" tickLine={false} axisLine={false} interval={0} tick={{ fill: "var(--muted)", fontSize: 13 }} />
          <BarChart.YAxis hide domain={[0, "auto"]} />
          <BarChart.Bar
            dataKey="v"
            radius={8}
            maxBarSize={46}
            fill="var(--surface-tertiary)"
            isAnimationActive={false}
            label={{
              position: "top",
              fill: "var(--foreground)",
              fontSize: 14,
              fontFamily: "var(--pw-font-num)",
              formatter: (v: unknown) => (typeof v === "number" ? spreadSeconds(v * 1000) : ""),
            }}
          />
        </BarChart>
      )}
    </Card>
  );
}
