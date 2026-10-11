// The shared chart cursor as React state (lib/viz/cursor.ts): Compare's charts, the lap ribbon and the map read the
// same distance. Recharts-free, so pages can use it without loading the chart chunk.

import { useSyncExternalStore } from "react";
import type { CursorSync } from "../../lib/viz/cursor";

/** The cursor in game lap metres (null = none); re-renders the caller when it moves. */
export function useCursor(sync: CursorSync): number | null {
  return useSyncExternalStore(sync.subscribe, sync.get, sync.get);
}
