// Radio chips for race radio (pitwall.raceradio; race-radio spec 10.3): RACE for race-situation calls, URGENT for an
// alert the radio says at once (the red flag, voice/urgent.py). Static markup in plain node for the chip component.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { LogEntry } from "../../lib/radio";
import { logRows } from "../../pages/drive/radio/view";
import { KIND_CHIP, kindChip, URGENT_CHIP } from "./radio-view";
import { RadioKindChip } from "./RadioMessage";

const text = (markup: string): string => markup.replace(/<[^>]+>/g, "").trim();

describe("race radio chips", () => {
  it("RACE: a race-situation call, in the accent colour", () => {
    expect(KIND_CHIP.race).toEqual({ label: "RACE", tone: "accent" });
    expect(kindChip("race")).toEqual({ label: "RACE", tone: "accent" });
  });

  it("URGENT: an alert whose meta says urgent; any other alert stays ALERT", () => {
    expect(URGENT_CHIP).toEqual({ label: "URGENT", tone: "danger" });
    expect(kindChip("alert", { urgent: true })).toEqual(URGENT_CHIP);
    expect(kindChip("alert", { urgent: false })).toEqual({ label: "ALERT", tone: "warning" });
    expect(kindChip("alert", null)).toEqual({ label: "ALERT", tone: "warning" });
    expect(kindChip("alert")).toEqual({ label: "ALERT", tone: "warning" });
  });

  it("only alerts turn URGENT (a newer server's urgent flag on another kind keeps that kind's chip)", () => {
    expect(kindChip("race", { urgent: true })).toEqual({ label: "RACE", tone: "accent" });
    expect(kindChip("answer", { urgent: true }).label).toBe("ENGINEER");
    expect(kindChip("brand_new_kind", { urgent: true }).label).toBe("INFO");
    expect(kindChip(null, { urgent: true }).label).toBe("RADIO");
  });

  it("the chip component shows URGENT for an urgent alert, RACE for a race call", () => {
    expect(text(renderToStaticMarkup(createElement(RadioKindChip, { kind: "alert", urgent: true })))).toBe("URGENT");
    expect(text(renderToStaticMarkup(createElement(RadioKindChip, { kind: "alert" })))).toBe("ALERT");
    expect(text(renderToStaticMarkup(createElement(RadioKindChip, { kind: "race", size: "sm" })))).toBe("RACE");
  });

  it("log rows carry the urgent flag (Drive › Radio's log chips)", () => {
    const entry = (seq: number, over: Partial<LogEntry> = {}): LogEntry => ({
      seq,
      at: 1_000_000,
      kind: "alert",
      text: `t${seq}`,
      meta: "text only",
      id: `m${seq}`,
      count: 1,
      ...over,
    });
    const rows = logRows([entry(1), entry(2, { urgent: true }), entry(3, { kind: "race" })], 1_000_000);
    expect(rows.map((r) => [r.seq, r.kind, r.urgent])).toEqual([
      [3, "race", false],
      [2, "alert", true],
      [1, "alert", false],
    ]);
  });
});
