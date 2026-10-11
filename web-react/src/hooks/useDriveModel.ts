// Everything Drive renders, from one live-store subscription (design spec 4.10, 4.11). Lane DV.
//
// driveModel() (lib/drive/model.ts, lane DL) runs once per snapshot (20 Hz) and once a second on a clock tick (red
// flag age, the 6 s incident chip). Its memo (the newest session-phase event, the chequered flag, the last corner
// shown) is carried from one call to the next. Panels receive plain view models and are memoised on their content,
// so a panel re-renders only when its own strings change.

import { useEffect, useMemo, useRef, useState } from "react";
import { driveModel, type DriveModel } from "../lib/drive/model";
import { driveMismatch } from "../lib/game";
import type { DriveMemo } from "../lib/drive/state";
import type { SnapshotNext } from "../lib/drive/types";
import { useActiveDriver, useDrivers, useLive, usePrefs } from "./stores";
import { useGameCatalog, useSnapshotGame } from "./useGame";

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
  // Another game's real data while the car stands still (game selection): the status slot says so (never a banner).
  const catalogue = useGameCatalog();
  const game = useSnapshotGame();
  const stopped = useLive((s) => {
    const v = s.snap?.frame?.speed_kph;
    return s.snap?.frame == null ? "none" : typeof v === "number" && Number.isFinite(v) && v < 5 ? "slow" : "moving";
  });
  const mismatch = useMemo(
    () => driveMismatch(game, catalogue, stopped === "none" ? null : { speed_kph: stopped === "slow" ? 0 : null }),
    [game, catalogue, stopped],
  );

  const model = useMemo(
    () => driveModel({ snap, connected, nowS, driver, drivers, prefs: { driveLock }, memo: memo.current, mismatch }),
    [snap, connected, nowS, driver, drivers, driveLock, mismatch],
  );
  useEffect(() => {
    memo.current = model.memo;
  }, [model]);
  return model;
}
