// Validation kit test helpers (tests only; app code never imports this). Fixtures in src/test/fixtures/validation:
//   example-run.json  the lane's shared fixture (design/example-run.json, also used by the backend's golden test):
//                     { run: Run with ?detail=full evidence, report_excerpt: ValidationReport }
//   catalog.json      { _fixture, body: Catalog }, hand-written from the spec's catalogue (section 11)
//   recorded-*.json   { _fixture, body }: answers of the real backend on an isolated scratch server (voice and LLM off)
//                     after replaying the committed recorded F1 and AC excerpts (tier "recorded", nothing counts)
// Every loader returns a fresh copy, so a test may change what it gets.

import type { Catalog, CatalogItem, ItemState, Run, RunSummary, ValidationReport } from "../endpoints/validation";

interface Wrapped<T> {
  _fixture: { source: string; status: number; note: string; edited?: string[] };
  body: T;
}

const ALL = import.meta.glob<unknown>("../../test/fixtures/validation/*.json", { eager: true, import: "default" });

function load<T>(name: string): T {
  const f = ALL[`../../test/fixtures/validation/${name}.json`];
  if (!f) throw new Error(`no fixture ${name}`);
  return structuredClone(f) as T;
}

export const vfix = {
  catalog: (): Catalog => load<Wrapped<Catalog>>("catalog").body,
  /** The compact Run (what the page polls): the example without its evidence. */
  run: (): Run => {
    const r = load<{ run: Run }>("example-run").run;
    delete r.evidence;
    return r;
  },
  /** The Run with ?detail=full. */
  runFull: (): Run => load<{ run: Run }>("example-run").run,
  report: (): ValidationReport => load<{ report_excerpt: ValidationReport }>("example-run").report_excerpt,
  /** Recorded answers of the real backend (scratch server, recorded replays; see each file's _fixture). */
  recordedCatalog: (): Catalog => load<Wrapped<Catalog>>("recorded-catalog-voice-off").body,
  recordedRun: (): Run => load<Wrapped<Run>>("recorded-run-replays-finished").body,
  recordedReport: (): ValidationReport => load<Wrapped<ValidationReport>>("recorded-report-replays").body,
  summary: (): RunSummary => {
    const r = vfix.run();
    return { id: r.id, label: r.label, status: r.status, started_unix: r.started_unix, ended_unix: r.ended_unix, current_item: r.current_item, counts: r.counts, tiers: r.tiers };
  },
};

/** A pending item state with no evidence (for runs built in tests). */
export function pendingState(id: string, over: Partial<ItemState> = {}): ItemState {
  return {
    id,
    status: "pending",
    windows: [],
    marks: [],
    skip_reason: null,
    auto: { verdict: "no_evidence", reasons: [], checks: [], metrics: {}, tier: null, updated_unix: 1791833412 },
    result: "not_run",
    ...over,
  };
}

/** A run whose tests are `ids` (states from the example where it has them, else pending). */
export function runWith(ids: string[], over: Partial<Run> = {}): Run {
  const base = vfix.run();
  const states = new Map(base.items.map((s) => [s.id, s]));
  return { ...base, selected_items: ids, items: ids.map((id) => states.get(id) ?? pendingState(id)), ...over };
}

export function itemOf(catalog: Catalog, id: string): CatalogItem {
  const i = catalog.items.find((x) => x.id === id);
  if (!i) throw new Error(`no catalogue item ${id}`);
  return i;
}
