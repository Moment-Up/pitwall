// Drive › Coach (design spec 4): while the car is moving, the iPad answers one question: what do I do next?
// The next corner and its braking call are the hero, the one coaching point sits under it, the delta is the strong
// second element, then sectors and lap times in timing colours, the lap ribbon and the radio strip. Lane DV.
//
// Eager in routes.tsx (the screen on the rig). One live-store subscription feeds one model per snapshot
// (useDriveModel); the delta is shown at most 10 times a second (useThrottledValue). Works fully with the LLM down:
// /ws/live and the radio store only (P10).

import { useConnectInfo } from "./coach/NoTelemetryCard";
import { CoachScreen } from "./coach/CoachScreen";
import { noTelemetryView, sameView } from "./coach/view";
import { useLive } from "../../hooks/stores";
import { useDriveModel } from "../../hooks/useDriveModel";
import type { SnapshotNext } from "../../lib/drive/types";
import { useThrottledValue } from "../../hooks/useThrottledValue";
import type { PageProps } from "../../routes";
import { useDriveEffects } from "./useDriveEffects";

/** The delta string changes at most every 100 ms (spec 4.5). */
export const DELTA_INTERVAL_MS = 100;

export function CoachPage(_props: PageProps) {
  const model = useDriveModel();
  const delta = useThrottledValue(model.delta, DELTA_INTERVAL_MS, sameView);
  const maySleep = useDriveEffects(model);
  const connect = useConnectInfo(model.state === "no_data");
  const listening = model.state === "no_data" ? noTelemetryView(connect).listening : null;
  // Only the Session complete card reads it (its corners by official label and name).
  const trackModel = useLive((s) => (model.card === "ended" ? ((s.snap as SnapshotNext | null)?.track_model ?? null) : null));
  return <CoachScreen model={model} delta={delta} maySleep={maySleep} listening={listening} trackModel={trackModel} />;
}
