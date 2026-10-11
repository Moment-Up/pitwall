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
//
// Game selection (spec 5.3) changes only: the no-telemetry card (the picker while no game is selected, else the
// selected game's steps), one muted sector cell when the game sends no sectors, and "· estimated" on the delta header
// when the game sends no lap distance. Nothing else on Coach mentions the game (glanceable).

import { Card, Skeleton } from "@heroui/react";
import { lazy, memo, Suspense, type ReactNode } from "react";
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
import { barStep, endedCorners, estimatedDelta, heroText, NO_COACH_GAME, sameProps, type CoachGameView } from "./view";
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
  /** What the game of the data on screen changes (game selection 5.3): the sector slot, the delta header. */
  game?: CoachGameView;
  /** The no-telemetry card to show instead of the default one (the game picker, or the selected game's steps). */
  noData?: ReactNode;
  /** Show `noData` although the model has data: the stale data is an old game's, and another game was chosen since. */
  showNoData?: boolean;
}

export function CoachScreen({
  model,
  delta,
  maySleep = false,
  listening = null,
  trackModel = null,
  game = NO_COACH_GAME,
  noData,
  showNoData = false,
}: CoachScreenProps) {
  const s = model.status;
  const approach = model.hero.kind === "corner" ? barStep(model.hero.approach) : null;
  let middle;
  if (showNoData && noData) middle = noData;
  else if (model.card === "ready" && model.ready) {
    middle = <ReadyCard ready={model.ready} refControl={model.ref} drill={model.drill} beginner={model.beginner} />;
  }
  else if (model.card === "ended" && model.ended) {
    middle = (
      <SessionCompleteSlot ended={model.ended} legendTier={model.tier} corners={endedCorners(model.ended, trackModel)} />
    );
  }
  else if (model.card === "no_data") middle = noData ?? <NoTelemetryCard />;
  else {
    middle = (
      <>
        <HeroPanel hero={heroText(model.hero)} approach={approach} cue={model.cue} />
        <CoachCard coach={model.coach} />
        <DeltaPanel delta={estimatedDelta(delta ?? model.delta, game.deltaEstimated)} refControl={model.ref} />
      </>
    );
  }
  return (
    <div className="pwc" data-state={model.state} data-dim={model.dim ? "" : undefined}>
      <DriveStatusSlot kind={s.kind} tone={s.tone} role={s.role} className="pwc-status">
        <StatusContent status={s} maySleep={maySleep} listening={listening} drill={model.drill.chip} />
      </DriveStatusSlot>
      {middle}
      <SectorCells sectors={model.sectors} unavailable={game.sectors} />
      <LapTimes laps={model.laps} />
      <CoachRibbon ribbon={model.ribbon} />
      <RadioStrip outcome={model.lastCue?.words ?? null} />
    </div>
  );
}
