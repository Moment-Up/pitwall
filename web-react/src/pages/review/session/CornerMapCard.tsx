// Corners on the map (spec 6.3 #6): the learned track coloured by corner, green where time was gained, red where it
// was lost, neutral within ±0.01 s, from the session's corner summary. Drawn by the shared TrackMap (lane V) with the
// session's own skeleton (neutral sector steps, S2 / S3 ticks); never a live flag (a stored session has none).

import { Card } from "@heroui/react";
import { useMemo } from "react";
import { TrackMap } from "../../../components/viz";
import type { CornerSummaryRow, ReviewTrackModel } from "../../../lib/endpoints/review";
import type { TrackSkeleton } from "../../../lib/skeleton";
import { cornerDeltaMap } from "../../../lib/review/charts";

export function CornerMapCard({
  summary,
  model,
  skeleton = null,
  lengthM = null,
}: {
  summary: readonly CornerSummaryRow[];
  model: ReviewTrackModel | null | undefined;
  skeleton?: TrackSkeleton | null;
  lengthM?: number | null;
}) {
  const deltas = useMemo(() => cornerDeltaMap(summary), [summary]);
  const hasMap = (model?.centreline?.length ?? 0) >= 3;
  return (
    <Card className="gap-3 p-5">
      <Card.Header>
        <Card.Title className="text-base font-semibold">Corners on the map</Card.Title>
      </Card.Header>
      {hasMap ? (
        <TrackMap
          model={model}
          skeleton={skeleton}
          lengthM={lengthM}
          segmentDelta={deltas}
          labels="all"
          height={300}
          label="Track map coloured by time gained or lost at each corner"
        />
      ) : (
        <p className="m-0 py-6 text-center text-sm text-muted">No map yet: Pitwall learns the track from a clean lap.</p>
      )}
      <div className={`flex flex-wrap gap-4 text-[13px] text-muted ${hasMap ? "" : "hidden"}`}>
        <span className="flex items-center gap-1.5">
          <i className="inline-block size-2.5 rounded-sm bg-behind" /> time lost
        </span>
        <span className="flex items-center gap-1.5">
          <i className="inline-block size-2.5 rounded-sm bg-ahead" /> time gained
        </span>
        <span className="flex items-center gap-1.5">
          <i className="inline-block size-2.5 rounded-sm bg-muted" /> within 0.01 s
        </span>
      </div>
    </Card>
  );
}
