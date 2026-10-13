// The radio's one policy (v0.3.0): GET /api/radio/policy serves `voice.scheduler.POLICY` (one row per call family)
// with its live constants (the per-lap budget). Settings › Radio & voice prints it, so the page can never drift from the
// code. A server without the endpoint answers FastAPI's own 404: the card is left out.

import { ApiError } from "../api";
import { authFetch } from "../auth";

export type RadioIntensity = "quiet" | "normal" | "detailed";
export type FamilyBudget = "waits" | "spends" | "free";

export interface RadioFamily {
  key: string;
  label: string;
  rank: number;
  interrupts: boolean;
  intensities: RadioIntensity[];
  quiet_mode: "said" | "held" | "some";
  speak_window: boolean;
  budget: FamilyBudget;
  setting: string;
  note: string;
}

export interface RadioPolicy {
  families: RadioFamily[];
  talkPerLap: Record<RadioIntensity, number>;
  racePerLap: Record<RadioIntensity, number>;
}

export const RADIO_POLICY_KEY = "radio:policy";
const LEVELS: readonly RadioIntensity[] = ["quiet", "normal", "detailed"];
const BUDGETS: readonly FamilyBudget[] = ["waits", "spends", "free"];

function perLap(raw: unknown): Record<RadioIntensity, number> | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const out = {} as Record<RadioIntensity, number>;
  for (const l of LEVELS) {
    const v = o[l];
    if (typeof v !== "number" || !Number.isFinite(v)) return null;
    out[l] = v;
  }
  return out;
}

function familyOf(raw: unknown): RadioFamily | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const budget = BUDGETS.find((b) => b === o.budget);
  const quiet = o.quiet_mode === "said" || o.quiet_mode === "held" || o.quiet_mode === "some" ? o.quiet_mode : null;
  if (typeof o.key !== "string" || typeof o.label !== "string" || !budget || !quiet) return null;
  const intensities = Array.isArray(o.intensities)
    ? o.intensities.filter((i): i is RadioIntensity => LEVELS.includes(i as RadioIntensity))
    : [];
  return {
    key: o.key,
    label: o.label,
    rank: typeof o.rank === "number" ? o.rank : 99,
    interrupts: o.interrupts === true,
    intensities,
    quiet_mode: quiet,
    speak_window: o.speak_window === true,
    budget,
    setting: typeof o.setting === "string" ? o.setting : "",
    note: typeof o.note === "string" ? o.note : "",
  };
}

/** The served policy, read leniently: unknown rows are skipped; null when the shape is not the one this page knows. */
export function radioPolicyOf(raw: unknown): RadioPolicy | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const c = o.constants && typeof o.constants === "object" ? (o.constants as Record<string, unknown>) : {};
  const talk = perLap(c.talk_per_lap);
  const race = perLap(c.race_per_lap);
  if (!Array.isArray(o.families) || !talk || !race) return null;
  const families = o.families.map(familyOf).filter((f): f is RadioFamily => f !== null);
  return { families, talkPerLap: talk, racePerLap: race };
}

export const radioPolicyApi = {
  get: async (): Promise<RadioPolicy | null> => {
    const r = await authFetch("/api/radio/policy");
    if (!r.ok) throw new ApiError(r.status, r.statusText);
    return radioPolicyOf(await r.json());
  },
};
