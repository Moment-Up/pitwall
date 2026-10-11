// "What changed?" (spec 6.9, D5): corner trends as small multiples (one Pro LineChart per corner: the mean time lost
// against the driver's current reference in each compared session, higher = less lost) with a TrendChip, one computed
// sentence, and the coach's habit counts per session. Before D5: "-" and why.

import { Button, Card } from "@heroui/react";
import { TrendChip } from "@heroui-pro/react";
import { LineChart } from "@heroui-pro/react/line-chart";
import { useState } from "react";
import { ReferenceLine } from "recharts";
import { Unknown } from "../../../components/ui";
import type { CornerTrend, HabitTrend, TrendWord } from "../../../lib/review/progress";
import { lostWords } from "../../../lib/review/progress";
import { plural } from "../../../lib/review/words";

const CHIP: Record<TrendWord, { trend: "up" | "neutral" | "down"; text: string }> = {
  better: { trend: "up", text: "better" },
  same: { trend: "neutral", text: "same" },
  worse: { trend: "down", text: "worse" },
};

function CornerMini({ t }: { t: CornerTrend }) {
  const rows = t.values.map((v, i) => ({ x: i + 1, s: v.s }));
  const lo = Math.min(0, ...t.values.map((v) => v.s));
  const hi = Math.max(0, ...t.values.map((v) => v.s));
  const pad = Math.max(0.02, (hi - lo) * 0.15);
  const chip = CHIP[t.trend];
  return (
    <div className="grid content-start gap-1.5 rounded-2xl bg-surface-secondary p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 text-[15px] font-semibold leading-tight">{t.long}</div>
        <TrendChip trend={chip.trend} size="sm">
          {chip.text}
        </TrendChip>
      </div>
      <LineChart data={rows} height={72} margin={{ top: 6, right: 6, bottom: 2, left: 6 }} aria-hidden="true">
        <LineChart.XAxis dataKey="x" hide type="number" domain={[0.7, rows.length + 0.3]} />
        <LineChart.YAxis hide reversed domain={[lo - pad, hi + pad]} />
        <ReferenceLine y={0} stroke="var(--pw-line-strong)" strokeDasharray="3 3" />
        <LineChart.Line
          dataKey="s"
          type="linear"
          stroke="var(--foreground)"
          strokeWidth={1.5}
          dot={{ r: 3, fill: "var(--foreground)", strokeWidth: 0 }}
          activeDot={false}
          isAnimationActive={false}
        />
      </LineChart>
      <p className="m-0 text-[13px] leading-snug text-muted">
        {lostWords(t.first)} a lap at first, {lostWords(t.last)} last time
      </p>
    </div>
  );
}

function habitLine(h: HabitTrend): string {
  return h.counts.map((c) => `${c.count} in ${plural(c.laps, "lap")}`).join(" → ");
}

export function ChangesCard({
  available,
  trends,
  habits,
  sentence,
  compared,
  caption,
  initial,
}: {
  /** D5 answered. */
  available: boolean;
  trends: readonly CornerTrend[];
  habits: readonly HabitTrend[];
  sentence: string;
  compared: number;
  caption: boolean;
  /** Corners shown before "Show all". */
  initial: number;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? trends : trends.slice(0, initial);
  return (
    <Card className="gap-3 p-5">
      <Card.Header className="gap-1.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <Card.Title className="text-base font-semibold">What changed?</Card.Title>
          {available && compared > 0 && (
            <span className="text-sm text-muted">{plural(compared, "session")} compared with the same reference lap</span>
          )}
        </div>
        {available ? (
          <p className="m-0 text-base leading-snug text-foreground">{sentence}</p>
        ) : (
          <p className="m-0 flex items-center gap-2 text-sm text-muted">
            <Unknown className="text-xl" />
            Corner trends and habit counts need a newer Pitwall server.
          </p>
        )}
      </Card.Header>
      {available && caption && shown.length > 0 && (
        <p className="m-0 text-sm text-muted">
          Each small chart is one corner: the time lost against the reference lap in each session, oldest on the left.
          Higher is better. The dashed line is level with the reference.
        </p>
      )}
      {available && shown.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {shown.map((t) => (
            <CornerMini key={t.key} t={t} />
          ))}
        </div>
      )}
      {available && trends.length > initial && (
        <div>
          <Button variant="ghost" className="min-h-11" onPress={() => setAll((v) => !v)}>
            {all ? "Show fewer corners" : `Show all ${trends.length} corners`}
          </Button>
        </div>
      )}
      {available && habits.length > 0 && (
        <div className="grid gap-2 pt-1">
          <h3 className="m-0 text-[15px] font-semibold">Habits the coach counted</h3>
          <ul className="m-0 grid list-none gap-1.5 p-0">
            {habits.map((h) => (
              <li key={h.kind} className="flex flex-wrap items-baseline justify-between gap-x-4 text-sm">
                <span>{h.words}</span>
                <span className="pw-num text-[15px] text-muted">{habitLine(h)}</span>
              </li>
            ))}
          </ul>
          <p className="m-0 text-[13px] text-muted">Times each point fired per session, oldest first, over every corner.</p>
        </div>
      )}
    </Card>
  );
}
