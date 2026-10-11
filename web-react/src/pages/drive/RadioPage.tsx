// Drive › Radio (design spec 5.3): talk to the race engineer. `#/radio?token=…` (Home Screen icons,
// docs/radio-setup.md) lands here with its token (the shell's redirect keeps the query; lib/auth reads it). The
// radio store is module level (lane A), so the radio keeps running when this page closes; outside Drive the mini
// radio bar (shell) shows its latest message and Hold to talk. Lane DV.

import { useLive } from "../../hooks/stores";
import { useDriveModel } from "../../hooks/useDriveModel";
import type { SnapshotNext } from "../../lib/drive/types";
import type { PageProps } from "../../routes";
import { RadioScreen } from "./radio/RadioScreen";
import { useDriveEffects } from "./useDriveEffects";

export function RadioPage(_props: PageProps) {
  const model = useDriveModel();
  const maySleep = useDriveEffects(model);
  const liveCueMode = useLive((s) => (s.snap as SnapshotNext | null)?.cues?.mode ?? null);
  return <RadioScreen model={model} maySleep={maySleep} liveCueMode={liveCueMode} />;
}
