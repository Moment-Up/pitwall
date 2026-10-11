// A "Work on" card (spec 6.3 #2, 10.4): the corner (official label and name), a 120 px map with the corner
// highlighted, the coach's text verbatim (`text_simple` for simple wording), the evidence line, and three actions:
// See it on the lap (Compare at the apex), Why? (the comparison's numbers in plain words, a Disclosure) and Ask the
// engineer (pre-filled). Beginners: 18 px text and no signed badge (the evidence line says the amount in words).

import { Button, Card, Chip, Disclosure } from "@heroui/react";
import { CornerTag } from "../../../components/ui";
import type { ReviewTrackModel } from "../../../lib/endpoints/review";
import { router } from "../../../lib/router";
import { itemEvidence, itemText, type CoachingItem } from "../../../lib/review/coaching";
import { modelToGameM } from "../../../lib/review/compare";
import { cornerIdentity } from "../../../lib/review/corners";
import type { Density } from "../../../lib/review/density";
import { askPath, comparePath, workOnQuestion } from "../../../lib/review/links";
import { signedSeconds, whyText } from "../../../lib/review/words";
import { CornerMap } from "./CornerMap";

export interface WorkOnCardProps {
  item: CoachingItem;
  sessionId: string;
  model: ReviewTrackModel | null | undefined;
  refLapId: number | null;
  density: Pick<Density, "signedBadges" | "simpleWording" | "workOnTextPx">;
  /** The session's lap length (game metres): Compare's `at=` is in game metres. */
  gameLengthM?: number | null;
  /** Preview (Sessions, iPad): no actions. */
  compact?: boolean;
}

export function WorkOnCard({ item, sessionId, model, refLapId, density, gameLengthM = null, compact = false }: WorkOnCardProps) {
  const id = cornerIdentity(model, item.corner, item.latest.corner_label);
  const text = itemText(item, density.simpleWording);
  const why = whyText({
    where: id.spoken,
    evidence: item.latest.evidence ?? {},
    lapNumber: item.latest.lap_number,
    refLapNumber: item.latest.ref_lap_number,
  });

  return (
    <Card className="gap-3 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Chip color="warning" variant="soft" size="md">
          <Chip.Label>Work on</Chip.Label>
        </Chip>
        <CornerTag label={id.label} name={id.name} size="md" />
        {density.signedBadges && item.latest.impact_s != null && (
          <span
            className="pw-num ml-auto text-xl text-behind"
            aria-label={`about ${Math.abs(item.latest.impact_s).toFixed(2)} seconds a lap lost here`}
          >
            {signedSeconds(item.latest.impact_s)}
          </span>
        )}
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_96px] items-start gap-4 sm:grid-cols-[minmax(0,1fr)_120px]">
        <p className="m-0 leading-[1.45] text-foreground" style={{ fontSize: density.workOnTextPx }}>
          {text}
        </p>
        <CornerMap
          model={model}
          highlight={item.corner}
          className="size-24 sm:size-[120px]"
          label={`Track map with ${id.full} highlighted`}
        />
      </div>
      <p className="m-0 text-[13px] text-muted">{itemEvidence(item)}</p>
      {!compact && (
        <Disclosure className="grid gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              className="min-h-11"
              onPress={() =>
                router.navigate(
                  comparePath(sessionId, { ref: refLapId, lap: item.latestLapId, at: modelToGameM(id.apexM, model?.length_m, gameLengthM) }),
                )
              }
            >
              See it on the lap
            </Button>
            <Disclosure.Heading className="m-0">
              <Disclosure.Trigger className="button button--ghost min-h-11 rounded-full px-4 text-sm font-medium">
                Why?
                <Disclosure.Indicator className="size-4" />
              </Disclosure.Trigger>
            </Disclosure.Heading>
            <Button
              variant="ghost"
              className="min-h-11"
              onPress={() => router.navigate(askPath(sessionId, workOnQuestion(id.spoken, id.label)))}
            >
              Ask the engineer
            </Button>
          </div>
          <Disclosure.Content>
            <Disclosure.Body style={{ padding: 0 }} className="rounded-2xl bg-surface-secondary px-4 py-3 text-sm leading-relaxed text-muted">
              {why ?? "The comparison carries no numbers for this point."}{" "}
              <span className="text-faint">A description from the comparison, not advice.</span>
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      )}
    </Card>
  );
}
