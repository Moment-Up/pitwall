// F1 spotter view rules (lib/spotter/view.ts) over the contract fixtures (src/test/fixtures/spotter, design spec 8.3):
// the block parser, every state the Drive edge bars can be in, the block geometry and the words.
import { describe, expect, it } from "vitest";
import { spotterFixture, spotterFixtureMeta, SPOTTER_FIXTURE_NAMES } from "../../test/spotter";
import type { SpotterBlock } from "./types";
import { SPOTTER_REASONS } from "./types";
import {
  BARS_STALE_MS,
  barSpanM,
  barsView,
  blockGeometry,
  callText,
  DEFAULT_CAR_LENGTH_M,
  parseSpotterBlock,
  reasonText,
  REASON_TEXT,
  type BarsContext,
} from "./view";

const LIVE: BarsContext = { connected: true, status: "live", fresh: true };
const block = (name: Parameters<typeof spotterFixture>[0]): SpotterBlock => {
  const b = parseSpotterBlock(spotterFixture(name));
  if (!b) throw new Error(`${name} did not parse`);
  return b;
};

describe("fixtures", () => {
  it("are all labelled contract (hand-written from the spec, never game compatibility)", () => {
    expect(SPOTTER_FIXTURE_NAMES.length).toBeGreaterThanOrEqual(12);
    for (const n of SPOTTER_FIXTURE_NAMES) expect(spotterFixtureMeta(n as "live-clear").tier).toBe("contract");
  });
});

describe("parseSpotterBlock", () => {
  it("keeps spec 8.3's example as it is", () => {
    expect(parseSpotterBlock(spotterFixture("live-alongside-left"))).toEqual({
      v: 1,
      enabled: true,
      active: true,
      reason: null,
      left: { state: "alongside", lon_m: -1.8, gap_m: 0.9, cars: 1 },
      right: { state: "clear", lon_m: null, gap_m: null, cars: 0 },
      three_wide: false,
      traffic: true,
      rate_hz: 59.8,
      seq: 1234,
      length_m: null,
    });
  });

  it("ignores a newer version, a missing block and anything that is not an object", () => {
    expect(parseSpotterBlock(spotterFixture("live-newer-version"))).toBeNull();
    for (const raw of [undefined, null, "spotter", 1, [], { v: "1" }]) expect(parseSpotterBlock(raw)).toBeNull();
  });

  it("unknown stays unknown: malformed numbers are null, an unknown side state is not drawn, an unknown reason is null", () => {
    const b = parseSpotterBlock({
      v: 1,
      enabled: "yes",
      active: true,
      reason: "brand_new_gate",
      left: { state: "behind_close", lon_m: 1, gap_m: 1, cars: 1 },
      right: { state: "alongside", lon_m: Number.NaN, gap_m: "0.2" },
      rate_hz: Number.POSITIVE_INFINITY,
      length_m: 12,
    });
    expect(b).toMatchObject({
      enabled: false, // only `true` turns anything on
      reason: null,
      left: { state: "clear", lon_m: null, gap_m: null, cars: 0 },
      right: { state: "alongside", lon_m: null, gap_m: null, cars: 1 },
      three_wide: false,
      rate_hz: null,
      seq: 0,
      length_m: null, // outside 3-7 m: not a car length
    });
  });

  it("a clear side never carries a position or cars, even when the server sends them", () => {
    const b = parseSpotterBlock({ v: 1, left: { state: "clear", lon_m: 2, gap_m: 1, cars: 3 } });
    expect(b?.left).toEqual({ state: "clear", lon_m: null, gap_m: null, cars: 0 });
  });
});

describe("barsView: hidden whenever the data is in doubt", () => {
  const b = () => block("live-alongside-left");

  it.each([
    ["no block (older server, no F1 session)", null, LIVE, "no_block"],
    ["socket down", "b", { ...LIVE, connected: false }, "offline"],
    ["stream stale", "b", { ...LIVE, status: "stale" }, "not_live"],
    ["stream idle", "b", { ...LIVE, status: "idle" }, "not_live"],
    ["status unknown", "b", { ...LIVE, status: null }, "not_live"],
    ["no new block within the stale window", "b", { ...LIVE, fresh: false }, "not_fresh"],
  ] as const)("%s", (_what, which, ctx, hidden) => {
    const v = barsView(which === "b" ? b() : null, ctx);
    expect(v).toEqual({ hidden, left: null, right: null, three_wide: false });
  });

  it("switched off (or bars off): nothing", () => {
    expect(barsView(block("live-off"), LIVE).hidden).toBe("off");
    expect(barsView({ ...b(), enabled: false }, LIVE).hidden).toBe("off");
  });

  it("a closed gate (safety car): nothing, even with a car alongside (a muted spotter shows nothing)", () => {
    const sc = block("live-safety-car");
    expect(barsView(sc, LIVE).hidden).toBe("inactive");
    expect(barsView({ ...sc, left: { state: "alongside", lon_m: 0, gap_m: 1, cars: 1 } }, LIVE)).toMatchObject({
      hidden: "inactive",
      left: null,
    });
  });

  it("the stale window is short enough to hide a paused game's last bars before the next 5 s snapshot", () => {
    expect(BARS_STALE_MS).toBeGreaterThanOrEqual(300); // > a few 50 ms snapshot periods plus Wi-Fi bunching
    expect(BARS_STALE_MS).toBeLessThanOrEqual(1000);
  });
});

describe("barsView: what each state draws", () => {
  it("clear: live, nothing lit", () => {
    expect(barsView(block("live-clear"), LIVE)).toEqual({ hidden: null, left: null, right: null, three_wide: false });
  });

  it("alongside left, 1.8 m behind: an amber left bar with the car block below the middle", () => {
    const v = barsView(block("live-alongside-left"), LIVE);
    expect(v.hidden).toBeNull();
    expect(v.right).toBeNull();
    expect(v.left).toMatchObject({ tone: "alongside", cars: 1, label: "left alongside 1.8 m behind" });
    expect(v.left!.blockTopPct! + v.left!.blockHeightPct / 2).toBeGreaterThan(50); // behind = below the middle
  });

  it("close right, 2.4 m ahead: a red right bar with the block above the middle", () => {
    const v = barsView(block("live-close-right"), LIVE);
    expect(v.left).toBeNull();
    expect(v.right).toMatchObject({ tone: "close", label: "right close 2.4 m ahead" });
    expect(v.right!.blockTopPct! + v.right!.blockHeightPct / 2).toBeLessThan(50);
  });

  it("three wide: both bars, flagged", () => {
    const v = barsView(block("live-three-wide"), LIVE);
    expect(v.left?.tone).toBe("alongside");
    expect(v.right?.tone).toBe("alongside");
    expect(v.three_wide).toBe(true);
    expect(v.left?.label).toBe("left alongside 0.6 m ahead");
    expect(v.right?.label).toBe("right alongside level"); // within half a metre
  });

  it("outside a three-wide: one bar that counts both cars", () => {
    const v = barsView(block("live-outside-three-wide"), LIVE);
    expect(v.left).toBeNull();
    expect(v.right).toMatchObject({ tone: "alongside", cars: 2 });
    expect(v.three_wide).toBe(false);
  });

  it("a car alongside whose position is unknown lights the bar without a block (never a guessed place)", () => {
    const v = barsView({ ...block("live-clear"), left: { state: "alongside", lon_m: null, gap_m: null, cars: 1 } }, LIVE);
    expect(v.left).toMatchObject({ tone: "alongside", blockTopPct: null, label: "left alongside" });
  });
});

describe("blockGeometry (ahead at the top, spec 9.1: the bar spans -(L+1.5) .. +(L+1.5) m)", () => {
  it("the F1 default: 7 m either way, a 5.5 m block is 39 % of the bar", () => {
    expect(DEFAULT_CAR_LENGTH_M).toBe(5.5);
    expect(barSpanM(null)).toBe(7);
    expect(blockGeometry(0, null)).toEqual({ topPct: 30.4, heightPct: 39.3 });
  });

  it("ahead moves up, behind moves down, and the block never leaves the bar", () => {
    expect(blockGeometry(3, null).topPct).toBeLessThan(30.4);
    expect(blockGeometry(-3, null).topPct).toBeGreaterThan(30.4);
    expect(blockGeometry(7, null).topPct).toBe(0);
    expect(blockGeometry(99, null).topPct).toBe(0);
    expect(blockGeometry(-7, null).topPct).toBe(60.7);
    expect(blockGeometry(-99, null).topPct).toBe(60.7);
  });

  it("uses the block's car length when the server sends one (F2 5.3 m), else the F1 default", () => {
    expect(barSpanM(5.3)).toBeCloseTo(6.8, 6);
    expect(blockGeometry(0, 5.3).heightPct).toBe(39);
    expect(barSpanM(Number.NaN)).toBe(7);
    expect(barSpanM(20)).toBe(7);
  });

  it("an unknown position has no block", () => {
    expect(blockGeometry(null, null).topPct).toBeNull();
    expect(blockGeometry(Number.NaN, null).topPct).toBeNull();
  });
});

describe("words", () => {
  it("every gate reason has plain words; anything else is 'Inactive', never raw", () => {
    for (const r of SPOTTER_REASONS) expect(REASON_TEXT[r]).toMatch(/^[A-Z]/);
    expect(reasonText("safety_car")).toBe("Silent: safety car");
    expect(reasonText("start")).toBe("Waiting for the start");
    expect(reasonText("brand_new_gate")).toBe("Inactive");
    expect(reasonText(null)).toBe("Inactive");
    expect(reasonText("toString")).toBe("Inactive");
  });

  it("call ids in words", () => {
    expect(callText("car_left")).toBe("car left");
    expect(callText("clear_all_round")).toBe("clear all round");
    expect(callText("still_there", "right")).toBe("still there (right)");
    expect(callText("still_there")).toBe("still there");
    expect(callText("hold_your_line")).toBe("hold your line");
    expect(callText("hold_your_line", "left")).toBe("hold your line (left)");
    expect(callText("car_left", "right")).toBe("car left"); // the id already says the side
    expect(callText("rm -rf")).toBe("call");
    expect(callText(null)).toBe("call");
  });
});
