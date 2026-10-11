// Your best here (spec 6.3 #7): a small Pro LineChart of this driver's best clean lap per session at this track
// (y reversed, "faster ↑"), one computed sentence (never an LLM), and a link to Progress. Synthetic and replay
// sessions never count. Before D5 the car is not filtered, and the card says so when the cars differ.

import { Button, Card } from "@heroui/react";
import { LineChart } from "@heroui-pro/react/line-chart";
import { useMemo } from "react";
import { useApi } from "../../../hooks/useApi";
import { reviewApi, reviewKeys, type SessionDetail } from "../../../lib/endpoints/review";
import { lapTime } from "../../../lib/format";
import { router } from "../../../lib/router";
import { bestHereSentence, bestHereSeries, clockTick, timeAxis } from "../../../lib/review/charts";
import { progressPath } from "../../../lib/review/links";
import { dayTitle } from "../../../lib/review/words";

export function BestHereCard({ session, caption }: { session: SessionDetail; caption: boolean }) {
  const driverId = session.driver_id;
  const { data, error } = useApi(driverId != null ? reviewKeys.driverSessions(driverId) : null, () =>
    reviewApi.driverSessions(driverId as number),
  );
  const points = useMemo(() => (data ? bestHereSeries(data, session) : []), [data, session]);
  const axis = useMemo(() => timeAxis(points.map((p) => p.s)), [points]);
  const now = Date.now();
  const rows = points.map((p, i) => ({ n: i + 1, s: p.s }));
  const cars = new Set((data ?? []).filter((r) => points.some((p) => p.sessionId === r.id)).map((r) => r.car_name ?? ""));

  return (
    <Card className="gap-3 p-5">
      <Card.Header className="flex-row flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <Card.Title className="text-base font-semibold">Your best here</Card.Title>
        <Button
          variant="ghost"
          size="sm"
          className="min-h-11"
          onPress={() => router.navigate(progressPath({ driver: driverId, track: session.track_id }))}
        >
          Progress
        </Button>
      </Card.Header>
      {driverId == null ? (
        <p className="m-0 text-sm text-muted">This session has no driver, so it belongs to nobody's progress.</p>
      ) : error && !data ? (
        <p className="m-0 text-sm text-muted">Could not load this driver's sessions: {error.message}</p>
      ) : !data ? (
        <p className="m-0 text-sm text-muted">Loading…</p>
      ) : (
        <>
          <p className="m-0 text-[15px]">{bestHereSentence(points)}.</p>
          {caption && points.length >= 2 && (
            <p className="m-0 text-sm text-muted">Each dot is your best clean lap in one session here, oldest on the left.</p>
          )}
          {points.length >= 2 && (
            <LineChart data={rows} height={150} margin={{ top: 10, right: 12, bottom: 0, left: 4 }}>
              <LineChart.Grid vertical={false} stroke="var(--surface-tertiary)" />
              <LineChart.XAxis dataKey="n" hide />
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
              <LineChart.Tooltip
                cursor={false}
                content={({ active, label }) => {
                  const p = active ? points[Number(label) - 1] : undefined;
                  if (!p) return null;
                  return (
                    <div className="rounded-xl bg-overlay px-3 py-2 text-sm shadow-overlay">
                      <div className="font-semibold">{p.current ? "This session" : dayTitle(p.startedUnix, now)}</div>
                      <div className="pw-num text-base">{lapTime(p.ms)}</div>
                    </div>
                  );
                }}
              />
              <LineChart.Line
                dataKey="s"
                type="linear"
                stroke="var(--pw-line-strong)"
                strokeWidth={1.5}
                isAnimationActive={false}
                dot={({ cx, cy, index }) => (
                  <circle
                    key={index}
                    cx={cx}
                    cy={cy}
                    r={points[index]?.current ? 6 : 4}
                    fill={points[index]?.current ? "var(--accent)" : "var(--foreground)"}
                  />
                )}
                activeDot={false}
              />
            </LineChart>
          )}
          <p className="m-0 text-[13px] text-muted">
            Real sessions only: replays and synthetic data are left out.
            {cars.size > 1 ? " The car may differ between sessions." : ""}
            {points.some((p) => p.current) ? " The orange dot is this session." : ""}
          </p>
        </>
      )}
    </Card>
  );
}
