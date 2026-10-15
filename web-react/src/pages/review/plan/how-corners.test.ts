// Render tests for Review › Coaching › "How corners work" (static markup in plain node, like the Settings render tests),
// on the real graph payload: a beginner reads the narrative with Ed's straight-line corner fitting them; the owner's
// session variant (hand-made Context) gets trail braking as theirs and the detail; another driver's plan names them;
// a server before the graph leaves the section out. Nothing on screen tells a driver to brake later.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { ApiError } from "../../../lib/api";
import { cache } from "../../../lib/cache";
import { knowledgeKeys } from "../../../lib/endpoints/knowledge";
import { BEGINNER_GT7, knowledgeFixtures, OWNER_F1, withSession } from "../../../lib/knowledge/testkit";
import { HowCornersWork, type HowCornersWorkProps } from "./HowCornersWork";

afterEach(() => cache.clear());

function html(props: HowCornersWorkProps): string {
  return renderToStaticMarkup(createElement(HowCornersWork, props));
}

/** Text without tags, entities decoded enough for matching words. */
function text(markup: string): string {
  return markup
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ");
}

/** The phase card that starts with this phase name (between its heading and the next card's). */
function card(t: string, phase: string, next: string): string {
  const a = t.indexOf(` ${phase} `);
  const b = t.indexOf(` ${next} `, a + 1);
  return t.slice(a, b < 0 ? undefined : b);
}

describe("How corners work", () => {
  it("a beginner reads the narrative: what fits them, Ed's corner first, no detail, Ed credited", () => {
    cache.set(knowledgeKeys.graph(null), knowledgeFixtures.graph());
    const m = html({ sessionId: null, skill: "beginner", level: "beginner", name: null });
    const t = text(m);
    expect(t).toContain("How corners work");
    expect(t).toMatch(/A corner in 6 phases/);
    expect(t).toContain("not something Pitwall has checked on your laps");
    const braking = card(t, "Braking", "Turn-in");
    expect(braking).toContain("Straight-line braking Fits you");
    expect(braking).toContain("Matches: Beginner.");
    expect(t).toContain("Matched to your level only");
    // Narrative density: no "How it works" folds, no tier chips, the faults not coached yet left out, 18 px text.
    expect(t).not.toContain("How it works");
    expect(t).not.toContain("Not coached yet");
    expect(t).not.toContain("Published coaching Fits");
    expect(m).toContain("font-size:18px");
    expect(t).toContain("What Pitwall checks");
    expect(t).toMatch(/From Ed \(Pitwall tester\): Idealised corner brief and self-check/);
    expect(t).toContain("Show the detail");
  });

  it("the owner's session (trail-braking F1 driver, advanced): trail braking is theirs, everything open", () => {
    const sid = "332904dbe3de";
    cache.set(knowledgeKeys.graph(sid), withSession(knowledgeFixtures.graph(), OWNER_F1));
    const t = text(html({ sessionId: sid, skill: "advanced", level: "advanced", name: null }));
    const turnIn = card(t, "Turn-in", "Mid-corner");
    expect(turnIn).toMatch(/Trail braking Fits you/);
    expect(turnIn).toContain("Matches: Trail-braking driver; High downforce.");
    expect(turnIn).toContain("For other drivers");
    expect(card(t, "Braking", "Turn-in")).toMatch(/Rev-matched downshifts For other drivers .*For: H-pattern gearbox\./);
    expect(t).toContain("Matched to the driver and car of your last session here.");
    expect(t).toContain("Trail-braking driver");
    expect(t).toMatch(/Not coached yet \(\d+\)/);
    expect(t).toContain("Measured by:");
    expect(t).toContain("(not measured yet)");
    expect(t).toContain("Causes Pitwall can tell apart: Over-braking · Early turn-in · Less grip");
    expect(t).toContain("Fires on corner-laps (Ed's detector): 66.8% (2026-10-14)");
    expect(t).not.toContain("Show the detail");
  });

  it("a coached fault the server rules out for this session shows why, never as 'for other drivers'", () => {
    const sid = "gt7session";
    const why = "This game does not send a channel this check needs.";
    cache.set(knowledgeKeys.graph(sid), withSession(knowledgeFixtures.graph(), BEGINNER_GT7, { late_throttle: { applies: false, why_not: why } }));
    const t = text(html({ sessionId: sid, skill: "beginner", level: "beginner", name: null }));
    const checks = t.slice(t.indexOf("What Pitwall checks"));
    expect(checks).toContain(`Does not apply here Late to full throttle`);
    expect(checks).toContain(why);
    expect(checks).not.toContain("For other drivers");
  });

  it("another driver's plan names them", () => {
    cache.set(knowledgeKeys.graph(null), knowledgeFixtures.graph());
    const t = text(html({ sessionId: null, skill: "beginner", level: "beginner", name: "Alex" }));
    expect(t).toContain("Fits Alex");
    expect(t).toContain("Coached on Alex's laps today");
    expect(t).not.toContain("Fits you");
  });

  it("a server before the graph leaves the section out; a graph that did not load says so", async () => {
    await cache.load(knowledgeKeys.graph(null), () => Promise.reject(new ApiError(404, "Not Found"))).catch(() => {});
    expect(html({ sessionId: null, skill: null, level: "intermediate", name: null })).toBe("");
    cache.clear();
    await cache
      .load(knowledgeKeys.graph(null), () => Promise.reject(new ApiError(503, "technique knowledge is unavailable: the graph did not load (2 problems)")))
      .catch(() => {});
    expect(text(html({ sessionId: null, skill: null, level: "intermediate", name: null }))).toContain(
      "How corners work could not be loaded: technique knowledge is unavailable: the graph did not load (2 problems).",
    );
  });

  it("no rendered words ask for later braking, less braking, an earlier release or more speed in", () => {
    const g = knowledgeFixtures.graph();
    // Every constraint, the praise exception included: the section shows no praise text that would need it.
    const patterns = g.constraints.flatMap((c) => c.forbidden.map((p) => new RegExp(p, "i")));
    cache.set(knowledgeKeys.graph(null), g);
    for (const level of ["beginner", "intermediate", "advanced"] as const) {
      const all = text(html({ sessionId: null, skill: level, level, name: null }));
      // Up to the sources: a source's note may quote the rule itself ("never recommends braking later"), and the
      // server's constraints do not scan sources either (pitwall.knowledge.graph TEXT_FIELDS).
      const t = all.slice(0, all.indexOf("Where this comes from"));
      expect(t.length).toBeGreaterThan(2000);
      for (const re of patterns) expect(re.test(t), `${level}: ${re}`).toBe(false);
    }
  });
});
