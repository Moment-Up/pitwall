import { describe, expect, it } from "vitest";
import { DENSITY, densityFor, moreDetail, UNKNOWN_DRIVER_LEVEL, viewedDriver } from "./density";
import { driver, fixtures } from "./testkit";

const james = driver(1, "James", "advanced");
const alex = { ...driver(2, "Alex", "beginner"), active: true };
const jo = driver(3, "Jo", "intermediate");
const family = [james, alex, jo];

describe("density by the viewed session's driver (spec 6.10)", () => {
  it("[critic] takes the session's driver, never the seated one: Alex in the seat, James's session is advanced", () => {
    expect(alex.active).toBe(true);
    const d = densityFor(james.id, family);
    expect(d.level).toBe("advanced");
    expect(d.driver?.name).toBe("James");
    expect(d.source).toBe("driver");
    expect(d.workOn).toBe(5);
    expect(d.kpiTiles).toBe(6);
  });

  it("a beginner's session opens simplified even when an advanced driver holds the iPad", () => {
    const d = densityFor(alex.id, [{ ...james, active: true }, { ...alex, active: false }, jo]);
    expect(d.level).toBe("beginner");
    expect(d.workOn).toBe(1);
    expect(d.summary).toBe("core");
    expect(d.workOnHeading).toBe("One thing to work on");
    expect(d.workOnTextPx).toBe(18);
    expect(d.signedBadges).toBe(false);
    expect(d.simpleWording).toBe(true);
  });

  it("follows the table row by row", () => {
    expect(DENSITY.beginner).toMatchObject({ kpiTiles: 4, workOn: 1, glossary: true, chartCaptions: true });
    expect(DENSITY.intermediate).toMatchObject({ kpiTiles: 4, workOn: 3, summary: "all", glossary: true, signedBadges: true });
    expect(DENSITY.advanced).toMatchObject({ kpiTiles: 6, workOn: 5, glossary: false, chartCaptions: false });
    expect(DENSITY.beginner.compareCharts).toEqual(["delta", "speed"]);
    expect(DENSITY.intermediate.compareCharts).toEqual(["delta", "speed", "pedals"]);
    expect(DENSITY.advanced.compareCharts).toEqual(["delta", "speed", "pedals", "steering"]);
    // Progress, Records: beginners see less of the family board
    expect([DENSITY.beginner.records, DENSITY.intermediate.records, DENSITY.advanced.records]).toEqual(["plain", "some", "all"]);
  });

  it("a session without a known driver (replay, deleted profile) shows the intermediate density", () => {
    expect(densityFor(null, family)).toMatchObject({ level: UNKNOWN_DRIVER_LEVEL, source: "unknown", driver: null });
    expect(densityFor(99, family).source).toBe("unknown");
    expect(densityFor(1, []).source).toBe("unknown");
  });

  it("anyone can expand: an override changes the view, not the profile", () => {
    const d = densityFor(alex.id, family, "advanced");
    expect(d.level).toBe("advanced");
    expect(d.source).toBe("override");
    expect(d.driverLevel).toBe("beginner");
    expect(d.simpleWording).toBe(false);
    expect(moreDetail("beginner")).toBe("intermediate");
    expect(moreDetail("intermediate")).toBe("advanced");
    expect(moreDetail("advanced")).toBe("advanced");
  });

  it("simple wording follows the profile's coaching limits", () => {
    const plainJo = { ...jo, coaching: { ...jo.coaching, simple_wording: true } };
    expect(densityFor(jo.id, [plainJo]).simpleWording).toBe(true);
    expect(densityFor(jo.id, [jo]).simpleWording).toBe(false);
  });

  it("works on the recorded profile", () => {
    const list = fixtures.drivers().drivers;
    expect(viewedDriver(1, list)?.name).toBe("James");
    expect(densityFor(1, list).level).toBe("advanced");
  });
});
