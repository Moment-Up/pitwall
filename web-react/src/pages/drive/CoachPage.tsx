// Drive › Coach (design spec 4): while the car is moving, the iPad answers one question: what do I do next?
// The next corner and its braking call are the hero, the one coaching point sits under it, the delta is the strong
// second element, then sectors and lap times in timing colours, the lap ribbon and the radio strip. Lane DV.
//
// Eager in routes.tsx (the screen on the rig). One live-store subscription feeds one model per snapshot
// (useDriveModel); the delta is shown at most 10 times a second (useThrottledValue). Works fully with the LLM down:
// /ws/live and the radio store only (P10).
//
// Game selection (spec 5.3): with no telemetry and no game selected, the middle card asks "What are you playing?"
// (until "Not now" on this device); with a selected game the no-telemetry steps follow its guide. The game of the data
// on screen (detected, else selected) decides the sector slot and the delta header. Until the catalogue loads, or
// with a server that predates game selection, the page is exactly as before.

import { useMemo, useState } from "react";
import { GamePickerCard, pickerDismissed } from "./coach/GamePickerCard";
import { NoTelemetryCard, useConnectInfo } from "./coach/NoTelemetryCard";
import { CoachScreen } from "./coach/CoachScreen";
import { coachGameView, noTelemetryGame, noTelemetryView, sameView } from "./coach/view";
import { useLive } from "../../hooks/stores";
import { useDriveModel } from "../../hooks/useDriveModel";
import { useGameCatalog, useSnapshotGame } from "../../hooks/useGame";
import type { SnapshotNext } from "../../lib/drive/types";
import { effectiveEntry, selectedEntry } from "../../lib/game";
import { useThrottledValue } from "../../hooks/useThrottledValue";
import type { PageProps } from "../../routes";
import { useDriveEffects } from "./useDriveEffects";

/** The delta string changes at most every 100 ms (spec 4.5). */
export const DELTA_INTERVAL_MS = 100;

export function CoachPage(_props: PageProps) {
  const model = useDriveModel();
  const delta = useThrottledValue(model.delta, DELTA_INTERVAL_MS, sameView);
  const maySleep = useDriveEffects(model);
  const noData = model.state === "no_data";
  const connect = useConnectInfo(noData);
  const catalogue = useGameCatalog();
  const snapGame = useSnapshotGame();
  const selected = selectedEntry(catalogue, snapGame);
  const effective = effectiveEntry(catalogue, snapGame);
  const game = useMemo(() => coachGameView(effective), [effective]);
  const [notNow, setNotNow] = useState(pickerDismissed);
  const askGame = noData && !!catalogue && !!snapGame && snapGame.selected_id === null && !notNow;
  const listening = noData ? noTelemetryView(connect, noTelemetryGame(selected)).listening : null;
  // Only the Session complete card reads it (its corners by official label and name).
  const trackModel = useLive((s) => (model.card === "ended" ? ((s.snap as SnapshotNext | null)?.track_model ?? null) : null));
  const card = !noData ? undefined : askGame && catalogue ? (
    <GamePickerCard catalogue={catalogue} onNotNow={() => setNotNow(true)} />
  ) : (
    <NoTelemetryCard entry={selected} />
  );
  return (
    <CoachScreen
      model={model}
      delta={delta}
      maySleep={maySleep}
      listening={listening}
      trackModel={trackModel}
      game={game}
      noData={card}
    />
  );
}
