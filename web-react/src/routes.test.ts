import { describe, expect, it, vi } from "vitest";
import { AREA_IDS, AREA_PAGES } from "./lib/route-parse";
import { AREAS, pageById, registeredPages } from "./routes";

// The eager Coach page pulls in HeroUI (which needs a browser); the registry itself does not. Lazy pages are not
// loaded by importing routes.tsx.
vi.mock("./pages/drive/CoachPage", () => ({ CoachPage: () => null }));

describe("page registry (src/routes.tsx)", () => {
  it("registers exactly the router's pages, in the same order, each with a component", () => {
    expect(AREAS.map((a) => a.id)).toEqual([...AREA_IDS]);
    expect(registeredPages()).toEqual(Object.fromEntries(AREA_IDS.map((a) => [a, [...AREA_PAGES[a]]])));
    for (const a of AREA_IDS) {
      for (const p of AREA_PAGES[a]) {
        const def = pageById(a, p);
        expect(def?.component, `${a}/${p}`).toBeTruthy();
      }
    }
  });

  it("labels follow the spec (2.1)", () => {
    expect(Object.fromEntries(AREAS.map((a) => [a.label, a.pages.map((p) => p.label)]))).toEqual({
      Drive: ["Coach", "Car", "Track", "Radio"],
      Review: ["Sessions", "Coaching", "Progress", "Goals", "Ask"],
      Setup: ["Game", "Connect", "Rig", "Controls", "Car setup", "Validation"],
      Settings: ["Drivers", "Radio & voice", "AI engineer", "Display", "System"],
    });
  });
});
