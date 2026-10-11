// Everything Drive renders, from one live-store subscription (design spec 4.10, 4.11). Lane DV.
//
// driveModel() (lib/drive/model.ts, lane DL) runs once per snapshot (20 Hz) and once a second on a clock tick (red
// flag age, the 6 s incident chip). Its memo (the newest session-phase event, the chequered flag, the last corner
// shown) is carried from one call to the next. Panels receive plain view models and are memoised on their content,
// so a panel re-renders only when its own strings change.
//
// Lane motivation: the newest /ws/live goal note feeds the 6 s GOAL REACHED chip; the session recap is fetched only
// while the last model was in the garage or ended (pages/drive/coach/useRecap.ts), never on track. The state is kept
// as React state, so the fetch switches on with one extra render when the state changes (rare), not per snapshot.

import { useEffect, useMemo, useRef, useState } from "react";
import { driveModel, type DriveModel } from "../lib/drive/model";
import type { DriveMemo, DriveState } from "../lib/drive/state";
import type { SnapshotNext } from "../lib/drive/types";
import type { DriveMotivation } from "../lib/motivation/drive";
import { useRecap } from "../pages/drive/coach/useRecap";
import { useActiveDriver, useDrivers, useLive, usePrefs } from "./stores";

/** Device clock in whole unix seconds, ticking once a second while mounted. */
export function useSecondTick(): number {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    const t = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

export function useDriveModel(): DriveModel {
  // The live snapshot carries the backend additions D1-D6 as optional fields (lib/drive/types.ts).
  const snap = useLive((s) => s.snap) as SnapshotNext | null;
  const connected = useLive((s) => s.connected);
  const driver = useActiveDriver();
  const drivers = useDrivers((s) => s.drivers);
  const driveLock = usePrefs((p) => p.driveLock);
  const nowS = useSecondTick();
  const memo = useRef<DriveMemo | null>(null);
  const note = useLive((s) => s.lastMotivation);
  const [lastState, setLastState] = useState<DriveState | null>(null);
  const r = useRecap(snap?.session_id, snap?.laps.length ?? 0, note, lastState, snap?.bests?.scope?.car_id ?? null);
  const motivation = useMemo<DriveMotivation>(
    () => ({ note: r.note, recap: r.recap, status: r.status }),
    [r.note, r.recap, r.status],
  );

  const model = useMemo(
    () => driveModel({ snap, connected, nowS, driver, drivers, prefs: { driveLock }, memo: memo.current, motivation }),
    [snap, connected, nowS, driver, drivers, driveLock, motivation],
  );
  useEffect(() => {
    memo.current = model.memo;
    setLastState((prev) => (prev === model.state ? prev : model.state));
  }, [model]);
  return model;
}
