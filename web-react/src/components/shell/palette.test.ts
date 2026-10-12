// ⌘K finds a page by its label, summary and keywords (integration plan 1.1, acceptance B10): the palette's Pro Command
// filters a page's `textValue` (routes.tsx pageSearchText) with a case-insensitive "contains", as below.
import { describe, expect, it, vi } from "vitest";
import { AREAS, pageSearchText } from "../../routes";

// The eager Coach page pulls in HeroUI (which needs a browser); the registry itself does not.
vi.mock("../../pages/drive/CoachPage", () => ({ CoachPage: () => null }));

function find(q: string): string[] {
  const needle = q.toLowerCase();
  return AREAS.flatMap((a) => a.pages.filter((p) => pageSearchText(a, p).toLowerCase().includes(needle)).map((p) => `${a.id}/${p.id}`));
}

describe("⌘K page search", () => {
  it("finds Goals for goal, badge, streak and week; Coaching for drill and AI level; Car for strategy", () => {
    for (const q of ["goal", "badge", "streak", "week", "printable"]) expect(find(q), q).toContain("review/goals");
    for (const q of ["drill", "AI level", "habits"]) expect(find(q), q).toContain("review/coaching");
    for (const q of ["strategy", "fuel", "pit"]) expect(find(q), q).toContain("drive/car");
    expect(find("validate")).toContain("setup/validation");
    expect(find("FFB")).toContain("setup/rig");
    for (const q of ["buttons", "button box", "push to talk", "PTT", "brake bias", "encoder", "funky switch", "UDP Action"]) {
      expect(find(q), q).toContain("setup/controls");
    }
    expect(find("update")).toContain("settings/system");
    expect(find("usual game")).toContain("settings/drivers");
  });

  it("every page has a one-line summary and lower-case keywords; Review lists Goals between Progress and Ask", () => {
    for (const a of AREAS) {
      for (const p of a.pages) {
        expect(p.summary.length, `${a.id}/${p.id}`).toBeGreaterThan(0);
        for (const k of p.keywords) expect(k, `${a.id}/${p.id}`).toBe(k.toLowerCase());
      }
    }
    const review = AREAS.find((a) => a.id === "review")!.pages.map((p) => p.id);
    expect(review).toEqual(["sessions", "coaching", "progress", "goals", "ask"]);
  });
});
