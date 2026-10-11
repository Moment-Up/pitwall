// Data hooks for the technique blocks (feat/technique spec §6, §9). Cached by key (lib/endpoints/technique.ts):
// session-level results under "analysis:<id>", so a completed lap of the live session refreshes them; a comparison of
// two stored laps keeps a minute (the track model can grow). The server computes on request and caches in memory.

import { useApi } from "../../../../hooks/useApi";
import type { CarFormat } from "../../../../lib/endpoints/carsetup";
import { techniqueApi, techniqueKeys } from "../../../../lib/endpoints/technique";

/** One session's technique against its reference (or `refLapId`). */
export function useTechnique(sid: string | null, refLapId?: number | null) {
  return useApi(sid ? techniqueKeys.session(sid, refLapId) : null, () => techniqueApi.session(sid as string, refLapId), {
    maxAgeMs: 60_000,
  });
}

/** The handling balance and setup suggestions of one session (Setup › Car setup), sized for `carFormat` (the page's). */
export function useTechniqueBalance(sid: string | null, carFormat?: CarFormat | null) {
  return useApi(sid ? techniqueKeys.balance(sid, carFormat) : null, () => techniqueApi.balance(sid as string, carFormat), {
    maxAgeMs: 60_000,
  });
}

/** Line, inputs and balance of two laps. */
export function useTechniqueCompare(ref: number | null, lap: number | null) {
  const ok = ref != null && lap != null && ref !== lap;
  return useApi(ok ? techniqueKeys.compare(ref, lap) : null, () => techniqueApi.compare(ref as number, lap as number), {
    maxAgeMs: 60_000,
  });
}
