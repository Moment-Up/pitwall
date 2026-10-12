// Race radio endpoints (lane "radio"; race-radio spec 9.4): typed client for the live race view and the household's
// race-radio settings. Server side: src/pitwall/api/routes_race.py.
//
//   raceKeys.live       GET /api/race/live        (the snapshot carries the same block; this is for a page that
//                                                  mounts without /ws/live). `mode: "off"` with a reason when nothing
//                                                  is live.
//   raceKeys.settings   GET /api/race/settings    (P2) {"online_names": false}
//                       PUT /api/race/settings    the same body; answers the stored settings
//
// A server without race radio (or without the P2 settings) answers FastAPI's own 404 ("Not Found"): `isMissingRoute`
// (endpoints/review) tells it apart, and the page then hides the setting instead of showing an error.

import { ApiError } from "../api";
import { authFetch } from "../auth";
import type { RaceSettings, RaceView } from "../raceradio/types";
import { raceOf } from "../raceradio/view";

export const raceKeys = {
  live: "race:live",
  settings: "race:settings",
} as const;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
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

/** The settings as stored: a value that is not `true` reads as off (the household default: names are never said). */
export function normaliseRaceSettings(raw: unknown): RaceSettings {
  const o = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return { online_names: o.online_names === true };
}

export const raceApi = {
  /** The live race view; null for a contract this dashboard does not know (a newer version). */
  live: async (): Promise<RaceView | null> => raceOf(await req<unknown>("/api/race/live")),
  /** The household's race-radio settings (P2). */
  settings: async (): Promise<RaceSettings> => normaliseRaceSettings(await req<unknown>("/api/race/settings")),
  /** Store the settings; answers what the server stored. */
  saveSettings: async (s: RaceSettings): Promise<RaceSettings> =>
    normaliseRaceSettings(
      await req<unknown>("/api/race/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ online_names: s.online_names === true }),
      }),
    ),
};
