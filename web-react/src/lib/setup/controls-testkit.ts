// Setup › Controls test helpers (tests only; app code never imports this). Fixtures in src/test/fixtures/controls are
// { _fixture, body }:
//   contract-*.json    built from the controls design draft (overlay + research copies) in the shapes of the design's
//                      contract (now the types in lib/endpoints/controls.ts) by a development script, NOT server answers. The
//                      catalogue is a mechanical translation of the draft overlay; wheels, layouts, recommendations, the
//                      guide and the test states are hand-placed after the design's worked example (F1 25 on PS5 with
//                      the GT DD Pro wheel).
//   backend-b1-*.json  what the backend's own modules (src/pitwall/controls catalog / templates / recommend / steps)
//                      return when called directly in Python, before the HTTP API existed (a development script).
//                      Real backend output, not an HTTP answer: { wheel, rec, guide } per case, and the catalogue.
//   isolated-*.json    HTTP answers of an isolated `pitwall serve` (127.0.0.1, scratch data dir, LLM and voice off, no
//                      game) on the feat/controls worktree while the backend was in progress, after the dashboard saved
//                      the recommended F1 25 PS5 layout for the GT DD Pro template. Not a live rig.
// Every loader returns a fresh copy, so a test may change what it gets.

import type {
  ButtonsFeed,
  ControlsCatalog,
  ControlsState,
  ControlsTest,
  MapGuide,
  Recommendation,
  WheelDef,
} from "../endpoints/controls";

interface Wrapped<T> {
  _fixture: { source: string; status: number; note: string; edited?: string[] };
  body: T;
}

const ALL = import.meta.glob<unknown>("../../test/fixtures/controls/*.json", { eager: true, import: "default" });

function load<T>(name: string): Wrapped<T> {
  const f = ALL[`../../test/fixtures/controls/${name}.json`];
  if (!f) throw new Error(`no fixture ${name}`);
  return structuredClone(f) as Wrapped<T>;
}

export const cfix = {
  catalog: (): ControlsCatalog => load<ControlsCatalog>("contract-catalog").body,
  templateGtDdPro: (): WheelDef => load<WheelDef>("contract-template-gt-dd-pro").body,
  templateMcLaren: (): WheelDef => load<WheelDef>("contract-template-mclaren").body,
  templateMozaKs: (): WheelDef => load<WheelDef>("contract-template-moza-ks").body,
  stateEmpty: (): ControlsState => load<ControlsState>("contract-state-empty").body,
  stateJames: (): ControlsState => load<ControlsState>("contract-state-james").body,
  recF1Advanced: (): Recommendation => load<Recommendation>("contract-rec-f1-ps5-advanced").body,
  recF1Beginner: (): Recommendation => load<Recommendation>("contract-rec-f1-ps5-beginner").body,
  recGt7: (): Recommendation => load<Recommendation>("contract-rec-gt7-ps5").body,
  recOther: (): Recommendation => load<Recommendation>("contract-rec-other").body,
  guideF1: (): MapGuide => load<MapGuide>("contract-guide-f1").body,
  testRunning: (): ControlsTest => load<ControlsTest>("contract-test-running").body,
  testUnavailable: (): ControlsTest => load<ControlsTest>("contract-test-unavailable").body,
  buttons: (): ButtonsFeed => load<ButtonsFeed>("contract-buttons").body,
  /** The backend's catalogue (Catalog.to_api()). */
  backendCatalog: (): ControlsCatalog => load<ControlsCatalog>("backend-b1-catalog").body,
  /** The backend's template wheel, recommendation and guide for one case. */
  backendCase: (name: BackendCase): { wheel: WheelDef; rec: Recommendation; guide: MapGuide } =>
    load<{ wheel: WheelDef; rec: Recommendation; guide: MapGuide }>(`backend-b1-${name}`).body,
  isolated: {
    state: (): ControlsState => load<ControlsState>("isolated-state-saved").body,
    recTemplate: (): Recommendation => load<Recommendation>("isolated-rec-f1-ps5-template").body,
    guide: (): MapGuide => load<MapGuide>("isolated-guide-f1-ps5").body,
    buttons: (): unknown => load<unknown>("isolated-buttons").body,
    testNone: (): unknown => load<unknown>("isolated-test-none").body,
    testWaiting: (): ControlsTest => load<ControlsTest>("isolated-test-waiting").body,
    testStopped: (): unknown => load<unknown>("isolated-test-stopped").body,
  },
  meta: (name: string) => load<unknown>(name)._fixture,
  names: (): string[] => Object.keys(ALL).map((k) => k.replace(/^.*\/(.*)\.json$/, "$1")),
};

export type BackendCase = "f1-ps5-gtddpro-advanced" | "gt7-ps5-gtddpro-advanced" | "f1-xbox-mclaren-advanced" | "acc-pc-moza-ks-beginner";
export const BACKEND_CASES: readonly BackendCase[] = [
  "f1-ps5-gtddpro-advanced",
  "gt7-ps5-gtddpro-advanced",
  "f1-xbox-mclaren-advanced",
  "acc-pc-moza-ks-beginner",
];

/** James's saved GT DD Pro wheel (the state fixture's only wheel). */
export function jamesWheel(): WheelDef {
  const w = cfix.stateJames().wheels[0];
  if (!w) throw new Error("the James state has no wheel");
  return w;
}
