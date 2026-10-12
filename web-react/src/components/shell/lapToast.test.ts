import { describe, expect, it } from "vitest";
import type { Observation } from "../../lib/api";
import { lapToastEvidence, lapToastTitle } from "./lapToast";

const obs = (n: number): Observation[] => Array.from({ length: n }, (_, i) => ({ id: String(i) }) as Observation);

describe("lapToastTitle (spec 2.6)", () => {
  it.each([
    [{ lap_number: 7 }, 2, "Lap 7 done · 2 coaching points"],
    [{ lap_number: 7 }, 1, "Lap 7 done · 1 coaching point"],
    [{ lap_number: 7 }, 0, "Lap 7 done"],
    [{ lap_number: 3 }, 5, "Lap 3 done · 5+ coaching points"], // the server sends at most 5
    [{}, 2, "Lap done · 2 coaching points"], // unknown lap number: not invented
    [{ lap_number: null }, 0, "Lap done"],
    [{ lap_number: 66 }, 2, "Lap 66 done · 2 coaching points"], // the game's number of the lap just finished
  ])("%j with %i observations", (lap, n, want) => {
    expect(lapToastTitle({ lap, observations: obs(n) })).toBe(want);
  });
});

describe("lapToastEvidence", () => {
  it("labels synthetic and replayed laps, and nothing else", () => {
    expect(lapToastEvidence({ synthetic: true, source: "replay:x.pwcap" })).toMatch(/^Synthetic/);
    expect(lapToastEvidence({ synthetic: false, source: "replay:x.pwcap" })).toMatch(/^Replay/);
    expect(lapToastEvidence({ synthetic: false, source: "udp:192.168.1.20" })).toBeNull();
    expect(lapToastEvidence(null)).toBeNull();
  });
});
