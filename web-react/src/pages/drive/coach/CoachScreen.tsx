// Drive › Coach, the screen on the rig (design spec 4; mockup "Drive › Coach"). Pure composition: everything comes
// from the Drive model (lib/drive/model.ts, lane DL), so every state renders from a fixture in tests.
//
//   status slot ─────────────────────────────────────────────────────────── 52   swapped, never stacked
//   hero: next corner + braking call (chamfer, accent edge) │ delta          290
//   coach card: the one coaching point                      │ (144 px)       120
//   sectors S1 S2 S3                                        │ lap times      132
//   lap ribbon ─────────────────────────────────────────────────────────── 56
//   radio strip ────────────────────────────────────────────────────────── 72
//
// States (4.7): ready / session complete / no telemetry swap the hero, coach and delta areas for one card; every
// other state keeps the slots and swaps content inside them (P2: nothing moves). Stale and offline dim the last
// content to 45 % and blank every running value.

import { Card, Skeleton } from "@heroui/react";
import { lazy, memo, Suspense } from "react";
import { DriveStatusSlot } from "../../../components/shell/DriveStatusSlot";
import type { DeltaView } from "../../../lib/drive/delta";
import type { DriveModel, EndedCard } from "../../../lib/drive/model";
import type { TrackModelNext } from "../../../lib/drive/types";
import { CoachCard } from "./CoachCard";
import { CoachRibbon } from "./CoachRibbon";
import { DeltaPanel } from "./DeltaPanel";
import { HeroPanel } from "./HeroPanel";
import { NoTelemetryCard } from "./NoTelemetryCard";
import { RadioStrip } from "./RadioStrip";
import { ReadyCard } from "./ReadyCard";
import { StatusContent } from "./StatusContent";
import { LapTimes, SectorCells } from "./TimingPanels";
import { barStep, endedCorners, heroText, sameProps } from "./view";
import "./coach.css";

// Pro KPI pulls Recharts in at module level: the card is its own chunk (spec 4.9, 4.11).
const SessionCompleteCard = lazy(async () => ({ default: (await import("./SessionCompleteCard")).SessionCompleteCard }));

/** Same size as the card, so nothing moves while its code arrives. */
function EndedFallback() {
  return (
    <Card className="pwc-end pwc-span3" aria-busy="true" aria-label="Loading the session summary">
      <Skeleton className="col-span-2 h-28 rounded-2xl" />
      <Skeleton className="h-20 rounded-2xl" />
      <Skeleton className="h-20 rounded-2xl" />
    </Card>
  );
}

const SessionCompleteSlot = memo(function SessionCompleteSlot({
  ended,
  legendTier,
  corners,
}: {
  ended: EndedCard;
  legendTier: 1 | 2;
  corners: { workOn: string | null; wentWell: string | null };
}) {
  return (
    <Suspense fallback={<EndedFallback />}>
      <SessionCompleteCard ended={ended} tier={legendTier} corners={corners} />
    </Suspense>
  );
}, sameProps);

export interface CoachScreenProps {
  model: DriveModel;
  /** The delta view at most 10 times a second (useThrottledValue). Default: model.delta. */
  delta?: DeltaView;
  /** The screen wake lock is wanted but refused / unsupported: "Screen may sleep" in the status slot. */
  maySleep?: boolean;
  /** "Listening on UDP 20777" while there is no telemetry (from /api/connect). */
  listening?: string | null;
  /** The live track model: names the Session complete card's corners by official label and name. */
  trackModel?: TrackModelNext | null;
}

export function CoachScreen({ model, delta, maySleep = false, listening = null, trackModel = null }: CoachScreenProps) {
  const s = model.status;
  const approach = model.hero.kind === "corner" ? barStep(model.hero.approach) : null;
  let middle;
  if (model.card === "ready" && model.ready) {
    middle = <ReadyCard ready={model.ready} refControl={model.ref} drill={model.drill} beginner={model.beginner} />;
  }
  else if (model.card === "ended" && model.ended) {
    middle = (
      <SessionCompleteSlot ended={model.ended} legendTier={model.tier} corners={endedCorners(model.ended, trackModel)} />
    );
  }
  else if (model.card === "no_data") middle = <NoTelemetryCard />;
  else {
    middle = (
      <>
        <HeroPanel hero={heroText(model.hero)} approach={approach} cue={model.cue} />
        <CoachCard coach={model.coach} />
        <DeltaPanel delta={delta ?? model.delta} refControl={model.ref} />
      </>
    );
  }
  return (
    <div className="pwc" data-state={model.state} data-dim={model.dim ? "" : undefined}>
      <DriveStatusSlot kind={s.kind} tone={s.tone} role={s.role} className="pwc-status">
        <StatusContent status={s} maySleep={maySleep} listening={listening} drill={model.drill.chip} />
      </DriveStatusSlot>
      {middle}
      <SectorCells sectors={model.sectors} />
      <LapTimes laps={model.laps} />
      <CoachRibbon ribbon={model.ribbon} />
      <RadioStrip outcome={model.lastCue?.words ?? null} />
    </div>
  );
}
