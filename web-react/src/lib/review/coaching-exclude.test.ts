// workOnItems' `exclude` (lane motivation): the Summary's Work on list leaves out the point "3 things from this
// session" already shows, without refilling its corner with another point.
import { describe, expect, it } from "vitest";
import { workOnItems } from "./coaching";
import { fixtures } from "./testkit";

describe("workOnItems(analysis, exclude)", () => {
  it("drops exactly the excluded corner:kind, keeps the order of the rest", () => {
    const a = fixtures.austriaAnalysis();
    const all = workOnItems(a);
    expect(all.map((i) => i.key)).toContain("T4:low_min_speed");
    const rest = workOnItems(a, "T4:low_min_speed");
    expect(rest.map((i) => i.key)).toEqual(all.map((i) => i.key).filter((k) => k !== "T4:low_min_speed"));
    // the corner is not refilled by another of its points
    expect(rest.some((i) => i.corner === "T4")).toBe(false);
  });

  it("no exclude, or a key that is not in the list: the list as before", () => {
    const a = fixtures.austriaAnalysis();
    expect(workOnItems(a, null)).toEqual(workOnItems(a));
    expect(workOnItems(a, "T99:nothing")).toEqual(workOnItems(a));
  });
});
