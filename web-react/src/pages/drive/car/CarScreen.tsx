// Drive › Car: the pit wall (design spec 5.1, graft from B; mockup driveCar). For a stationary reader: a parent on
// the phone, or a Mac next to the rig. Never the default page; on track with a beginner in the seat it sits behind
// the Drive lock. Pure composition from the Drive model and the snapshot, so every state renders from a fixture.
//
//   status slot (the same as Coach) ─────────────────────────────────────────────────────────── 52
//   Car (4)               │ Track map (5)                         │ Tyres & energy (3)          1.25fr
//   Inputs, last 12 s (4) │ Laps, current standing (5)            │ Coaching · last lap (3)     1fr
//   (in a race the Inputs slot shows the Strategy tile instead: race strategy, pitwall.strategy)

import { gameLength } from "../../../lib/drive/geometry";
import type { GameEntry } from "../../../lib/endpoints/game";
import type { DriveModel } from "../../../lib/drive/model";
import type { SnapshotNext } from "../../../lib/drive/types";
import type { HistoryPoint } from "../../../lib/live";
import type { BrakePrior, TrackOutline } from "../../../lib/viz/outline";
import { DriveFrame } from "../DriveFrame";
import { CarTile, CoachingTile, InputsTile, LapsTile, MapTile, TyresTile } from "./CarTiles";
import { carTile, coachingTile, lapsTile, mapTile, raceControlLine, tyresTile, WALL_LAPS } from "./view";
import { StrategyTile } from "./StrategyTile"; // race strategy (pitwall.strategy)
import { strategyTile } from "../../../lib/strategy/view"; // race strategy (pitwall.strategy)

export interface CarScreenProps {
  model: DriveModel;
  snap: SnapshotNext | null;
  history: readonly HistoryPoint[];
  /** Device clock, unix seconds (race-control ages). */
  nowS: number;
  maySleep?: boolean;
  /** The seated driver's profile wants plain wording (coaching texts). */
  simple?: boolean;
  outline?: TrackOutline | null;
  prior?: BrakePrior | null;
  /** The game of the data on screen (game selection): what it does not send is said in words, not dashes. */
  entry?: GameEntry | null;
}

export function CarScreen({
  model,
  snap,
  history,
  nowS,
  maySleep = false,
  simple = false,
  outline = null,
  prior = null,
  entry = null,
}: CarScreenProps) {
  // Every snapshot arrives as fresh JSON, so the views are cheap to rebuild and each tile is memoised on its
  // content instead: the laps and coaching tiles re-render once a lap, not per frame.
  const strategy = strategyTile(snap, model, { simple, nowS }); // race strategy (pitwall.strategy)
  return (
    <DriveFrame status={model.status} maySleep={maySleep} layout="car" dim={model.dim} state={model.state}>
      <CarTile v={carTile(snap, model, entry)} />
      <MapTile
        model={snap?.track_model}
        skeleton={snap?.skeleton}
        lengthM={gameLength(snap)}
        view={mapTile(snap, model)}
        outline={outline}
        prior={prior}
        raceControl={raceControlLine(snap?.events, nowS, entry)}
      />
      <TyresTile v={tyresTile(snap, entry)} />
      {/* --- race strategy (pitwall.strategy): in a race the Inputs slot shows the Strategy tile; the mode only
          changes at a session change, so the slot never swaps while driving (P2) --- */}
      {strategy.show ? <StrategyTile v={strategy} /> : <InputsTile history={history} dim={model.dim} />}
      <LapsTile v={lapsTile(snap, WALL_LAPS, entry)} />
      <CoachingTile v={coachingTile(snap, simple)} />
    </DriveFrame>
  );
}
