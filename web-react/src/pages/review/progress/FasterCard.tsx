// "Getting faster?" (spec 6.9): one computed sentence (never an LLM), then the best clean lap per session with the
// y axis reversed ("faster ↑"); D5 adds the typical (median) clean lap. A dot is purple REC or green PB when that
// session's best lap holds the family record or the driver's best ever (the one rule, lib/bests.ts, the same badge it
// has on Review and Drive); other dots are plain. The family's fastest time is a neutral grey line: the record of the
// family board shown under Records, said with that board's session type and weather (lib/review/records.ts
// familyLine), since the chart's sessions may include other boards'.

import { Card } from "@heroui/react";
import { useMemo } from "react";
import { TimingTag } from "../../../components/ui";
import type { BestBadge } from "../../../lib/bests";
import { router } from "../../../lib/router";
import { sessionPath } from "../../../lib/review/links";
import { recordBadge, sessionLabels, type SessionPoint } from "../../../lib/review/progress";
import { ProgressChart, type ProgressChartLine, type ProgressChartPoint } from "./ProgressChart";

export interface FasterCardProps {
  points: readonly SessionPoint[];
  sentence: string;
  /** Each session's badge (lib/bests.ts); null until known (every dot plain). */
  badges: ReadonlyMap<string, BestBadge> | null;
  /** The family board's record in words (`familyLine`); null without one. */
  familyLine: { ms: number; label: string } | null;
  showMedian: boolean;
  caption: boolean;
  multiCar: boolean;
  family: number;
}

export function FasterCard({ points, sentence, badges, familyLine, showMedian, caption, multiCar, family }: FasterCardProps) {
  const chartPoints = useMemo<ProgressChartPoint[]>(() => {
    const labels = sessionLabels(points, Date.now());
    return points.map((p, i) => ({
      id: p.sessionId,
      x: i + 1,
      xLabel: labels[i] ?? "",
      bestMs: p.bestMs,
      medianMs: p.medianMs,
      status: recordBadge(badges, p.sessionId),
      carName: p.carName,
    }));
  }, [points, badges]);
  // The family's fastest time as a neutral line when there is a family to compare with.
  const line: ProgressChartLine | null = familyLine && family > 1 ? { ...familyLine, tone: "neutral" } : null;
  const shownTags = (["rec", "pb"] as const).filter((t) => chartPoints.some((p) => p.status === t));
  // A trend needs two sessions with a clean lap; one dot is not a chart (the sentence says so).
  const chart = points.filter((p) => p.bestMs != null).length >= 2;

  return (
    <Card className="gap-3 p-5">
      <Card.Header className="gap-1.5">
        <Card.Title className="text-base font-semibold">Getting faster?</Card.Title>
        <p className="m-0 text-base leading-snug text-foreground">{sentence}</p>
      </Card.Header>
      {caption && chart && (
        <p className="m-0 text-sm text-muted">
          Each dot is the best clean lap of one session here, oldest on the left. Higher is faster.
          {showMedian ? " The dashed line is the typical clean lap of each session." : ""}
        </p>
      )}
      {chart && (
        <ProgressChart
          points={chartPoints}
          line={line}
          showMedian={showMedian}
          onOpen={(id) => router.navigate(sessionPath(id))}
          label="Best clean lap per session, higher is faster"
        />
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {chart && shownTags.length > 0 && (
          // The legend for the tags the chart shows (no SB here: every session's best is its own).
          <p className="pw-legend">
            {shownTags.map((t) => (
              <span key={t} className="pw-legend__item">
                <TimingTag status={t} decorative />
                <span>{t === "rec" ? "family record" : "your best ever"}</span>
              </span>
            ))}
          </p>
        )}
        <p className="m-0 text-[13px] text-muted">
          {chart ? "Tap a dot to open that session." : ""}
          {multiCar ? " Cars differ between these sessions, so not every change is the driver's." : ""}
        </p>
      </div>
    </Card>
  );
}
