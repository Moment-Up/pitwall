// Car health endpoints (lane "health"; lane spec 3.11 / 3.12): typed client for the live car-health view, the live
// racecraft view and the household's car-health radio settings. Server side: src/pitwall/api/routes_carhealth.py
// (`/api/health` is the service's own health route, so this lane lives under /api/car-health and /api/racecraft).
//
//   carHealthKeys.live        GET /api/car-health/live      (the snapshot carries the same block; this is for a page
//                                                           that mounts without /ws/live)
//   carHealthKeys.racecraft   GET /api/racecraft/live       (mode "off" with a reason without a live F1 race)
//   carHealthKeys.settings    GET / PUT /api/car-health/settings   (Settings › Radio & voice, "Car health calls")
//
// A server without the health lane answers FastAPI's own 404 ("Not Found"): `isMissingRoute` (endpoints/review) tells
// it apart. PUT sends Content-Type: application/json (the server refuses JSON-less writes: cross-site protection) and
// answers 400 with the reason in words for a bad value.

import { ApiError } from "../api";
import { authFetch } from "../auth";
import type { CarHealthSettings, CarHealthView, RacecraftView } from "../carhealth/types";
import { carHealthOf, carHealthSettingsOf, racecraftOf } from "../carhealth/view";
import { errorText } from "./settings";

export const carHealthKeys = {
  live: "carhealth:live",
  racecraft: "racecraft:live",
  settings: "carhealth:settings",
} as const;

/** A non-2xx answer: `detail` is the server's words, ready to show (no "400:" prefix). An ApiError, so
 * isMissingRoute() recognises an older server. */
export class CarHealthError extends ApiError {
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(status, detail);
    this.name = "CarHealthError";
    this.detail = detail;
  }
}

/** The words to show for anything a car-health call threw (the server's detail, without the status prefix). */
export function carHealthErrorText(e: unknown): string {
  if (e instanceof CarHealthError) return e.detail;
  return e instanceof Error ? e.message : String(e);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = errorText(((await r.json()) as { detail?: unknown }).detail, detail);
    } catch {
      /* not json */
    }
    throw new CarHealthError(r.status, detail || `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

/** A settings answer this dashboard understands, else an error (the card then says so; nothing is guessed). */
function settingsOrThrow(raw: unknown): CarHealthSettings {
  const v = carHealthSettingsOf(raw);
  if (!v) throw new CarHealthError(502, "The server sent car health settings this dashboard doesn't understand");
  return v;
}

export const carHealthApi = {
  /** The live car-health view; null without a live session or for a contract this dashboard does not know. */
  live: async (): Promise<CarHealthView | null> => carHealthOf(await req<unknown>("/api/car-health/live")),
  /** The live racecraft view (mode "off" with a reason outside F1 races); null for an unknown contract. */
  racecraft: async (): Promise<RacecraftView | null> => racecraftOf(await req<unknown>("/api/racecraft/live")),
  /** The household's car-health radio settings. */
  settings: async (): Promise<CarHealthSettings> => settingsOrThrow(await req<unknown>("/api/car-health/settings")),
  /** Save all four settings; answers with the settings as stored (400 with the reason for a bad value). */
  saveSettings: async (body: CarHealthSettings): Promise<CarHealthSettings> =>
    settingsOrThrow(
      await req<unknown>("/api/car-health/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    ),
};
