// Test helpers for the coachref fixtures (src/test/fixtures/coachref/*.json): hand-written from the spec's JSON
// contract (6.2 / 6.3) for the moments the tests need (Suzuka, Sam). Every file carries `_fixture` (tier "edited");
// API bodies are returned as they are, the "live-*" blocks are merged into a Drive fixture. Real server output (spec
// 13 A7, src/test/fixtures/coachref-recorded/) holds them to the same key sets: lib/endpoints/coachref.recorded.test.ts.
// Imported only by *.test.ts.

import type { SnapshotNext } from "../lib/drive/types";

const ALL = import.meta.glob<unknown>("./fixtures/coachref/*.json", { eager: true, import: "default" });

const BY_NAME = new Map(
  Object.entries(ALL).map(([path, body]) => [path.slice(path.lastIndexOf("/") + 1).replace(/\.json$/, ""), body]),
);

export const COACHREF_FIXTURES: readonly string[] = [...BY_NAME.keys()].sort();

/** A deep copy of one fixture (tests may edit it). */
export function crFixture<T>(name: string): T {
  const body = BY_NAME.get(name);
  if (body === undefined) throw new Error(`no coachref fixture ${name}`);
  return structuredClone(body) as T;
}

interface LiveBlock {
  reference?: SnapshotNext["reference"];
  coachref?: SnapshotNext["coachref"];
  coach?: SnapshotNext["coach"];
  cues_drill_corner?: string | null;
}

/** A Drive snapshot with a "live-*" block merged in (reference descriptor, coachref, and a drill's coach block). */
export function withLive<T extends SnapshotNext>(s: T, name: string): T {
  const b = crFixture<LiveBlock>(name);
  if (b.reference !== undefined) s.reference = b.reference;
  if (b.coachref !== undefined) s.coachref = b.coachref;
  if (b.coach !== undefined) s.coach = b.coach;
  if (b.cues_drill_corner !== undefined && s.cues) s.cues = { ...s.cues, drill_corner: b.cues_drill_corner };
  return s;
}
