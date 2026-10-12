// The radio log folds a run of spotter calls into one row (lib/spotter/log.ts, design spec 9.3), and Drive › Radio's
// logRows (pages/drive/radio/view.ts) uses it, so a busy start never pushes the engineer's answers out of view.
import { describe, expect, it } from "vitest";
import { logRows } from "../../pages/drive/radio/view";
import type { LogEntry, LogKind } from "../radio";
import { RUN_SHOWN, spotterRun } from "./log";

let seq = 0;
function e(kind: LogKind, text: string, meta = "", at = 1_000_000): LogEntry {
  seq += 1;
  return { seq, at, kind, text, meta, id: kind === "spotter" || kind === "answer" ? `m${seq}` : null, count: 1 };
}

describe("spotterRun", () => {
  it("is null for anything but a spotter entry", () => {
    const log = [e("answer", "Box this lap.")];
    expect(spotterRun(log, 0)).toBeNull();
    expect(spotterRun(log, 5)).toBeNull();
  });

  it("one call: its words, no count", () => {
    const log = [e("answer", "Box."), e("spotter", "Car left.", "0.5 s audio")];
    expect(spotterRun(log, 1)).toMatchObject({ start: 1, text: "Car left", count: null, meta: null });
  });

  it("a run: oldest first in one sentence, counted", () => {
    const log = [e("spotter", "Car left."), e("spotter", "Clear left."), e("spotter", "Three wide, you're in the middle.")];
    expect(spotterRun(log, 2)).toMatchObject({
      start: 0,
      seq: log[2]!.seq,
      text: "Car left, clear left, three wide, you're in the middle",
      count: "(3 calls)",
    });
  });

  it("a long run writes the newest RUN_SHOWN calls and counts the rest", () => {
    const words = ["Car left.", "Clear left.", "Car right.", "Clear right.", "Car left.", "Hold your line."];
    const log = words.map((w) => e("spotter", w));
    const run = spotterRun(log, log.length - 1)!;
    expect(RUN_SHOWN).toBe(4);
    expect(run.text).toBe("… car right, clear right, car left, hold your line");
    expect(run.count).toBe("(6 calls)");
  });

  it("says how many the driver did not hear", () => {
    const log = [e("spotter", "Car left.", "not played: you were transmitting"), e("spotter", "Clear left.", "0.4 s audio · dropped: audio paused, newer message")];
    expect(spotterRun(log, 1)?.meta).toBe("2 not played");
  });
});

describe("Drive › Radio log rows", () => {
  it("folds each run into one row, newest first, and keeps the answers around them as they are", () => {
    const log = [
      e("answer", "Box this lap.", "", 1_000_000),
      e("spotter", "Car left.", "0.5 s audio", 1_001_000),
      e("spotter", "Clear left.", "0.5 s audio", 1_002_000),
      e("answer", "Mediums are fine.", "", 1_003_000),
      e("spotter", "Car right.", "0.5 s audio", 1_004_000),
    ];
    const rows = logRows(log, 1_004_500);
    expect(rows.map((r) => [r.kind, r.text, r.count])).toEqual([
      ["spotter", "Car right", null],
      ["answer", "Mediums are fine.", null],
      ["spotter", "Car left, clear left", "(2 calls)"],
      ["answer", "Box this lap.", null],
    ]);
    expect(rows[0]?.age).toBe("now");
    expect(rows[2]?.seq).toBe(log[2]!.seq); // keyed by the run's newest entry
    expect(rows[2]?.meta).toBeNull(); // the per-clip "0.5 s audio" is noise in a run
  });

  it("thirty calls at the start are one row, so the answer before them is still the second row", () => {
    const log = [e("answer", "Good start.")];
    for (let i = 0; i < 30; i++) log.push(e("spotter", i % 2 ? "Clear left." : "Car left."));
    const rows = logRows(log, 1_000_000);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ kind: "spotter", count: "(30 calls)" });
    expect(rows[1]).toMatchObject({ kind: "answer", text: "Good start." });
  });
});
