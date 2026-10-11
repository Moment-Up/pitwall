// Drive › Car (design spec 5.1): the dense pit wall from direction B, for a second screen. It replaces the interim
// live view (DrivePage.tsx, deleted). One live-store subscription feeds the Drive model (status slot, states,
// dimming) and the tiles; the inputs trace draws the store's 12 s history at 10 Hz. Works fully with the LLM down
// (P10): /ws/live only. Lane DV.

import { useActiveDriver, useLive } from "../../hooks/stores";
import { useDriveModel, useSecondTick } from "../../hooks/useDriveModel";
import type { SnapshotNext } from "../../lib/drive/types";
import { useTrackPriors } from "../../components/viz";
import type { PageProps } from "../../routes";
import { CarScreen } from "./car/CarScreen";
import { useDriveEffects } from "./useDriveEffects";

export function CarPage(_props: PageProps) {
  const model = useDriveModel();
  const maySleep = useDriveEffects(model);
  const snap = useLive((s) => s.snap) as SnapshotNext | null;
  const history = useLive((s) => s.history);
  const driver = useActiveDriver();
  const nowS = useSecondTick();
  const { outline } = useTrackPriors({
    game: snap?.session?.game,
    trackId: snap?.session?.track_id,
    lengthM: snap?.session?.track_length_m,
    model: snap?.track_model,
  });
  return (
    <CarScreen
      model={model}
      snap={snap}
      history={history}
      nowS={nowS}
      maySleep={maySleep}
      simple={!!driver?.coaching?.simple_wording}
      outline={outline}
    />
  );
}
