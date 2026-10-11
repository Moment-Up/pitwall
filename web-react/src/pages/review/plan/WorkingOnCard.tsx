// A "Working on now" card (spec 6.8, 10.4): the corner (official label in a warning chip, then its name), a Pro
// TrendChip (better / same / worse over the last sessions, D5) at the right, the coach's latest observation verbatim
// (`text_simple` for simple wording), the evidence line, and See it (Compare at the corner's apex in that session).

import { Button, Card, Chip } from "@heroui/react";
import { TrendChip } from "@heroui-pro/react";
import { router } from "../../../lib/router";
import { itemEvidence, itemText } from "../../../lib/review/coaching";
import { comparePath } from "../../../lib/review/links";
import type { WorkingOn } from "../../../lib/review/plan";
import type { TrendWord } from "../../../lib/review/progress";

const CHIP: Record<TrendWord, { trend: "up" | "neutral" | "down"; text: string }> = {
  better: { trend: "up", text: "better" },
  same: { trend: "neutral", text: "same" },
  worse: { trend: "down", text: "worse" },
};

export function WorkingOnCard({
  w,
  sessionId,
  refLapId,
  atM,
  simple,
  textPx,
}: {
  w: WorkingOn;
  sessionId: string;
  refLapId: number | null;
  /** The corner's apex in game lap metres (Compare's `at=`). */
  atM: number | null;
  simple: boolean;
  textPx: number;
}) {
  const chip = w.trend ? CHIP[w.trend.trend] : null;
  return (
    <Card className="gap-3 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Chip color="warning" variant="soft" size="md">
          <Chip.Label className="font-bold">{w.label}</Chip.Label>
        </Chip>
        {w.name && <b className="text-[17px] font-semibold">{w.name}</b>}
        {chip && (
          <TrendChip trend={chip.trend} size="md" className="ml-auto">
            {chip.text}
          </TrendChip>
        )}
      </div>
      <p className="m-0 leading-[1.45] text-foreground" style={{ fontSize: textPx }}>
        {itemText(w.item, simple)}
      </p>
      <p className="m-0 text-[13px] text-muted">{itemEvidence(w.item)}</p>
      {w.trend && (
        <p className="m-0 text-[13px] text-muted">{w.trend.words}.</p>
      )}
      <div>
        <Button
          variant="secondary"
          className="min-h-11"
          onPress={() => router.navigate(comparePath(sessionId, { ref: refLapId, lap: w.item.latestLapId, at: atM }))}
        >
          See it
        </Button>
      </div>
    </Card>
  );
}
