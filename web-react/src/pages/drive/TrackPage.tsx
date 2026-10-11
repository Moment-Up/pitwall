// Drive › Track (design spec 5.2): the large map and the corner list, for learning a new track in practice. The
// picked corner lives in the page; nothing here writes to the server. Lane DV.

import { useMemo, useState } from "react";
import { useTrackPriors } from "../../components/viz";
import { useActiveDriver, useLive } from "../../hooks/stores";
import { useDriveModel } from "../../hooks/useDriveModel";
import { useEffectiveEntry } from "../../hooks/useGame";
import type { SnapshotNext } from "../../lib/drive/types";
import type { PageProps } from "../../routes";
import { TrackScreen } from "./track/TrackScreen";
import { trackView } from "./track/view";
import { useDriveEffects } from "./useDriveEffects";

export function TrackPage(_props: PageProps) {
  const model = useDriveModel();
  const maySleep = useDriveEffects(model);
  const snap = useLive((s) => s.snap) as SnapshotNext | null;
  const driver = useActiveDriver();
  const [selected, setSelected] = useState<string | null>(null);
  const simple = !!driver?.coaching?.simple_wording;
  const entry = useEffectiveEntry();
  const view = useMemo(() => trackView(snap, model, simple, entry), [snap, model, simple, entry]);
  const { outline } = useTrackPriors({
    game: snap?.session?.game,
    trackId: snap?.session?.track_id,
    lengthM: snap?.session?.track_length_m,
    model: snap?.track_model,
  });
  return (
    <TrackScreen
      model={model}
      snap={snap}
      view={view}
      selected={selected}
      onSelect={setSelected}
      maySleep={maySleep}
      outline={outline}
    />
  );
}
