// Race strategy endpoints (lane "strategy"; strategy spec 7.1): typed client for the live strategy view and a
// session's strategy timeline. Server side: src/pitwall/api/routes_strategy.py.
//
//   strategyKeys.live            GET /api/strategy/live              (the snapshot carries the same block at 20 Hz;
//                                                                     this is for a page that mounts without /ws/live)
//   strategyKeys.session(id)     GET /api/sessions/{id}/strategy     (Review › Strategy). Under "session:<id>", so the
//                                                                     live session's completed lap refreshes it with
//                                                                     the session row (hooks/useApi.ts)
//
// A server without the strategy engine answers FastAPI's own 404 ("Not Found"): `isMissingRoute` (endpoints/review)
// tells it apart from the route's "session not found".

import { ApiError } from "../api";
import { authFetch } from "../auth";
import type { StrategyTimeline, StrategyView } from "../strategy/types";
import { strategyOf } from "../strategy/view";

export const strategyKeys = {
  live: "strategy:live",
  session: (id: string) => `session:${id}:strategy`,
} as const;

async function req<T>(path: string): Promise<T> {
  const r = await authFetch(path);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = (await r.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not json */
    }
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

/** A timeline with every list present (an older or partial payload never crashes the page; unknown stays unknown). */
export function normaliseTimeline(raw: Partial<StrategyTimeline> & { session_id?: string }): StrategyTimeline {
  const list = <T>(v: T[] | null | undefined): T[] => (Array.isArray(v) ? v : []);
  return {
    session_id: String(raw.session_id ?? ""),
    available: raw.available === true,
    reason: typeof raw.reason === "string" ? raw.reason : null,
    total_laps: raw.total_laps ?? null,
    grid_position: raw.grid_position ?? null,
    finish_position: raw.finish_position ?? null,
    laps: list(raw.laps),
    stints: list(raw.stints),
    stops: list(raw.stops),
    field_stops: list(raw.field_stops),
    pit_loss: raw.pit_loss ?? null,
    safety_car_periods: list(raw.safety_car_periods),
    weather: list(raw.weather),
    calls: list(raw.calls),
  };
}

const enc = encodeURIComponent;

export const strategyApi = {
  /** The live strategy view; `mode: "off"` with a reason when nothing is live. Null for a contract this dashboard
   * does not know (a newer version). */
  live: async (): Promise<StrategyView | null> => strategyOf(await req<unknown>("/api/strategy/live")),
  /** One session's strategy timeline (404 when the session does not exist). */
  session: async (id: string): Promise<StrategyTimeline> =>
    normaliseTimeline(await req<Partial<StrategyTimeline>>(`/api/sessions/${enc(id)}/strategy`)),
};
