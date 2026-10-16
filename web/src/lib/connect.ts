// The classic Connect card's words for ACC (Assetto Corsa Competizione on this PC). ACC has no port and no IP: its
// reader copies the game's shared memory, so its row has port 0 and no sources, and the backend writes the sentence
// (reader.message: not running, waiting, reading, access denied...). Pure and import-free: the backend's unit tests
// run it with Node (tests/unit/test_acc_runtime.py).

export interface AccReader {
  state: string;
  message: string;
  last_rx_s_ago: number | null;
}

export interface AccRow {
  key: string;
  enabled: boolean;
  selected?: boolean;
  active?: boolean;
  reader?: AccReader | null;
}

/** ACC is on while switched on or the selected game (its reader runs either way, on Windows). */
export function accOn(g: AccRow): boolean {
  return g.active ?? (g.enabled || g.selected === true);
}

/** The card's line: the reader's own sentence, never "listening on UDP 0" or "packets so far · idle". */
export function accSummary(g: AccRow): string {
  if (g.reader?.message) return g.reader.message;
  return accOn(g) ? "waiting for ACC" : "off";
}

/** Snapshots are arriving (the card's line shows as live). */
export function accLive(g: AccRow): boolean {
  const r = g.reader;
  return r?.state === "reading" && typeof r.last_rx_s_ago === "number" && r.last_rx_s_ago < 2;
}

/** sessions.source of a live ACC session: read from shared memory on this PC, not sent over the network. */
export const ACC_SOURCE = "acc-shm";

/** The status card's line while ACC is live (there is no sender IP to name). */
export function accStatusLine(packetsPerS: number): string {
  return `Reading ACC's shared memory on this PC · ${Math.round(packetsPerS)} pages/s`;
}
