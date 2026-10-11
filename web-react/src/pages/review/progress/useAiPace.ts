// Pace vs AI for the viewed driver at the scope's track (any car: the cards group by car class): one request and one
// cache entry shared by Progress ("Against the AI") and the Coaching plan ("Suggested AI level"). `missing`: the
// server predates AI pace (its router answered 404), so the cards are left out.

import { useApi } from "../../../hooks/useApi";
import { isMissingRoute, reviewApi, reviewKeys, type DriverAiPace } from "../../../lib/endpoints/review";
import { aiPaceQuery } from "../../../lib/review/aipace";
import type { Scope } from "../../../lib/review/progress";

export interface AiPaceData {
  data: DriverAiPace | undefined;
  error: Error | null;
  missing: boolean;
}

export function useAiPace(driverId: number | null, scope: Scope | null): AiPaceData {
  const q = scope ? aiPaceQuery({ game: scope.track.game, trackId: scope.track.trackId }) : null;
  const r = useApi(
    driverId != null && q ? reviewKeys.aiPace(driverId, q) : null,
    () => reviewApi.driverAiPace(driverId as number, q ?? {}),
    { maxAgeMs: 60_000 },
  );
  return { data: r.data, error: r.error, missing: isMissingRoute(r.error) };
}
