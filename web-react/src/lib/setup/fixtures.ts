// Recorded API answers for lane X's tests (src/lib/setup/fixtures/*.json). Each file is
// { _fixture: { source, status, note, edited? }, body } where body is exactly what the endpoint sent (read-only GETs
// on the live service, 2026-10-11); "edited" lists every hand-changed field. The connect fixtures have the access
// token and private host names replaced; the rig catalogue has its presets and owner reports removed (unused, size). Test-only: nothing in the app imports this module.

import type {
  CarSetupCatalog,
  Combination,
  FormatInfo,
  ParamRange,
  RecommendationResponse,
  SessionSetupResponse,
  SetupExperiment,
  Unavailable,
} from "../endpoints/carsetup";
import type { ConnectInfo } from "../endpoints/connect";
import type { DriverPrefsResponse, Recommendation, RigCatalog, RigCheck, RigProfile } from "../endpoints/rig";

interface FixtureFile<T> {
  _fixture: { source: string; status: number; note: string; edited?: string[] };
  body: T;
}

const ALL = import.meta.glob<FixtureFile<unknown>>("./fixtures/*.json", { eager: true, import: "default" });

function load<T>(name: string): FixtureFile<T> {
  const f = ALL[`./fixtures/${name}.json`];
  if (!f) throw new Error(`no fixture ${name}`);
  // structuredClone: tests may mutate what they get
  return structuredClone(f) as FixtureFile<T>;
}

/** F2 support (carsetup-f2-contract-edited.json): the contract's F2 car format, F2-only ranges from the research crawl,
 * the F2 combinations, and three session answers (Sakhir with F2 setups, Silverstone without, a 2026 F2 car). */
export interface F2Contract {
  format: FormatInfo;
  ranges: Record<string, ParamRange>;
  available: Combination[];
  sessions: { sakhir: SessionSetupResponse; silverstone: SessionSetupResponse; f2_2026: SessionSetupResponse };
}

/** The recorded catalogue with the contract's F2 format added (format, per-parameter ranges, combinations). */
function catalogWithF2(): CarSetupCatalog {
  const cat = load<CarSetupCatalog>("carsetup-catalog").body;
  const f2 = load<F2Contract>("carsetup-f2-contract-edited").body;
  cat.formats.push(f2.format);
  for (const p of cat.parameters) {
    const r = f2.ranges[p.key];
    if (r) p.ranges.f2 = r;
  }
  cat.available.push(...f2.available);
  return cat;
}

export const fixtures = {
  catalog: () => load<CarSetupCatalog>("carsetup-catalog").body,
  /** F2 support: the recorded catalogue plus the contract's F2 format (edited). */
  catalogWithF2,
  f2: () => load<F2Contract>("carsetup-f2-contract-edited").body,
  recSilverstone: () => load<RecommendationResponse>("carsetup-rec-silverstone").body,
  recSilverstoneBeginner: () => load<RecommendationResponse>("carsetup-rec-silverstone-beginner").body,
  unavailableImola2026: () => load<{ detail: Unavailable }>("carsetup-unavailable-imola-2026"),
  sessionNeedsFormat: () => load<SessionSetupResponse>("carsetup-session-needs-format").body,
  sessionDiff: () => load<SessionSetupResponse>("carsetup-session-diff").body,
  experimentsEdited: () => load<SetupExperiment[]>("carsetup-experiments-edited").body,
  connectNoData: () => load<ConnectInfo>("connect-no-data").body,
  connectF1Live: () => load<ConnectInfo>("connect-f1-live-edited").body,
  rigCatalog: () => load<RigCatalog>("rig-catalog").body,
  rigProfile: () => load<RigProfile>("rig-profile").body,
  rigPrefsJames: () => load<DriverPrefsResponse>("rig-prefs-1").body,
  rigRecF1James: () => load<Recommendation>("rig-rec-f1-james").body,
  rigRecGt7James: () => load<Recommendation>("rig-rec-gt7-james").body,
  rigRecF1ComfortBeginner: () => load<Recommendation>("rig-rec-f1-comfort-beginner").body,
  rigCheckF1James: () => load<RigCheck>("rig-check-f1-james").body,
  rigCheckGt7James: () => load<RigCheck>("rig-check-gt7-james").body,
  rigCheck404: () => load<{ detail: string }>("rig-check-404"),
  rigRec422Gt7Pc: () => load<{ detail: string }>("rig-rec-422-gt7-pc"),
  meta: (name: string) => load<unknown>(name)._fixture,
};
