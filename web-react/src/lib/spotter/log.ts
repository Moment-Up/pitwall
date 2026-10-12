// F1 spotter calls in the radio log (design spec 9.3): a run of consecutive spotter calls folds into ONE compact
// row ("Car left, clear left, three wide…"), so a busy start (about 30 calls a minute for a few seconds) never
// pushes the engineer's answers out of view on Drive › Radio. Settings › Radio & voice › Spotter lists every call in
// full (GET /api/spotter `recent`). Pure, tested in plain node (log.test.ts).

import type { LogEntry } from "../radio";

/** Calls written out in a folded row; older calls of the run are summarised by the count. */
export const RUN_SHOWN = 4;

export interface SpotterRun {
  /** Index (in the store's oldest-first log) of the run's oldest entry. */
  start: number;
  /** The newest entry's seq and time: the row's key and age. */
  seq: number;
  at: number;
  /** "Car left, clear left" (oldest first, the newest RUN_SHOWN); "… car right, clear right" when longer. */
  text: string;
  /** "(6 calls)" when the run holds more than one; null for a single call. */
  count: string | null;
  /** "2 not played" when the driver did not hear some of them (transmitting, audio paused); else null. */
  meta: string | null;
}

/** "Car left." -> "car left" (the run joins them in one sentence). */
function word(text: string): string {
  const t = text.trim().replace(/[.!]+$/, "");
  return t ? t[0]!.toLowerCase() + t.slice(1) : t;
}

function capFirst(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}

/**
 * The run of spotter entries that ends at index `end` (inclusive) of the store's log (oldest first), or null when
 * `log[end]` is not a spotter entry.
 */
export function spotterRun(log: readonly LogEntry[], end: number): SpotterRun | null {
  const last = log[end];
  if (!last || last.kind !== "spotter") return null;
  let start = end;
  while (start > 0 && log[start - 1]?.kind === "spotter") start -= 1;
  const entries = log.slice(start, end + 1);
  let calls = 0;
  let unheard = 0;
  for (const e of entries) {
    calls += Math.max(1, e.count);
    if (/not played|dropped/.test(e.meta)) unheard += Math.max(1, e.count);
  }
  const shown = entries.slice(-RUN_SHOWN).map((e) => word(e.text)).filter(Boolean);
  const body = shown.join(", ");
  const text = entries.length > RUN_SHOWN ? `… ${body}` : capFirst(body);
  return {
    start,
    seq: last.seq,
    at: last.at,
    text: text || "Spotter call",
    count: calls > 1 ? `(${calls} calls)` : null,
    meta: unheard ? `${unheard} not played` : null,
  };
}
