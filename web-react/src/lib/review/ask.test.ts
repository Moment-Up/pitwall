import { describe, expect, it } from "vitest";
import type { EngineerAnswer } from "../api";
import {
  answerEntry,
  citationParts,
  defaultAskSession,
  errorEntry,
  factsLabel,
  historyEntries,
  historySource,
  latencyText,
  SUGGESTIONS,
  topicLabel,
} from "./ask";
import { askPath, engineerPath, lapsPath, workOnQuestion } from "./links";
import { fixtures } from "./testkit";
import { answerSource, replacedAfterGrounding } from "./words";

/** An answer as POST /api/engineer/ask returns it (constructed here: the live API is never written to in tests). */
function answer(over: Partial<EngineerAnswer> = {}): EngineerAnswer {
  return {
    session_id: "s",
    text: "Turn 3 cost the most [F17].",
    speech: "Turn 3 cost the most.",
    intent: "losing_time",
    corner: null,
    facts: [{ id: "F17", topic: "corners", text: "Turn 3 (right-hander): average time vs reference +0.412s over 9 laps." }],
    grounded: true,
    fallback: false,
    model: "qwen",
    latency_ms: 14761,
    llm_attempts: 1,
    grounding_issues: [],
    control: null,
    ...over,
  };
}

describe("where an answer came from (spec 6.7)", () => {
  it("LLM · grounded, Deterministic, LLM down · deterministic", () => {
    expect(answerSource(answer())).toBe("grounded");
    expect(answerSource(answer({ fallback: true, model: null, llm_attempts: 0 }))).toBe("deterministic");
    expect(answerSource(answer({ fallback: true, grounding_issues: ["llm unavailable: connection refused"] }))).toBe("llm_down");
    expect(answerSource(answer({ fallback: true, grounding_issues: ["unsupported numbers: 3.2"] }))).toBe("deterministic");
  });

  it("a canned reply that never went to the LLM (radio check) is not 'LLM · grounded'", () => {
    expect(answerSource(answer({ intent: "radio_check", model: null, llm_attempts: 0, fallback: false, grounded: true }))).toBe(
      "deterministic",
    );
  });

  it("says when the LLM's answer was replaced after the grounding check", () => {
    expect(replacedAfterGrounding(answer({ fallback: true, grounding_issues: ["unsupported numbers: 3.2"] }))).toBe(true);
    expect(replacedAfterGrounding(answer({ fallback: true, grounding_issues: ["llm unavailable: x"] }))).toBe(false);
    expect(answerEntry(answer({ fallback: true, grounding_issues: ["empty answer"] }), "a").replaced).toBe(true);
  });

  it("stored answers: fallback and model decide (the history keeps no grounding issues)", () => {
    expect(historySource({ fallback: 0, model: "qwen.gguf", grounded: 1 })).toBe("grounded");
    expect(historySource({ fallback: 1, model: "qwen.gguf", grounded: 1 })).toBe("deterministic");
    expect(historySource({ fallback: 0, model: null, grounded: 1 })).toBe("deterministic");
  });
});

describe("conversation model", () => {
  it("turns the stored history into chat entries with their facts", () => {
    const e = historyEntries(fixtures.history());
    expect(e.map((x) => x.role)).toEqual(["user", "engineer"]);
    expect(e[1]).toMatchObject({ source: "grounded", latencyMs: 14761 });
    expect(e[1]!.facts.map((f) => f.id)).toEqual(["F32"]);
    expect(historyEntries(null)).toEqual([]);
  });

  it("splits citations out of the text", () => {
    expect(citationParts("Focus on Turn 6 [F32], then T3 [F17].")).toEqual([
      { kind: "text", text: "Focus on Turn 6 " },
      { kind: "cite", id: "F32" },
      { kind: "text", text: ", then T3 " },
      { kind: "cite", id: "F17" },
      { kind: "text", text: "." },
    ]);
    expect(citationParts("no facts")).toEqual([{ kind: "text", text: "no facts" }]);
  });

  it("small words: latency, facts label, topics, errors", () => {
    expect(latencyText(14761)).toBe("14.8 s");
    expect(latencyText(null)).toBeNull();
    expect(factsLabel({ facts: [{ id: "F1", topic: "laps", text: "" }], source: "grounded" })).toBe("Grounded on 1 fact");
    expect(factsLabel({ facts: [], source: "deterministic" })).toBe("Built from 0 facts");
    expect(topicLabel("observations")).toBe("Observations");
    expect(errorEntry("409: no sessions recorded yet", "e")).toMatchObject({ error: true, text: "The engineer could not answer: 409: no sessions recorded yet" });
  });

  it("suggestions are phrased the way the engineer's intent rules read them", () => {
    expect(SUGGESTIONS).toContain("Where am I losing the most time?");
    expect(SUGGESTIONS).toContain("What went well?");
    expect(SUGGESTIONS.some((s) => /summary/i.test(s))).toBe(true);
  });
});

describe("which session Ask opens on", () => {
  const rows = [
    { id: "a", driver_id: 1, started_unix: 100 },
    { id: "b", driver_id: 2, started_unix: 300 },
    { id: "c", driver_id: 1, started_unix: 200 },
  ];
  it("route, then live, then the seated driver's newest, then the newest", () => {
    expect(defaultAskSession(rows, { route: "zzz" })).toBe("zzz");
    expect(defaultAskSession(rows, { live: "a", seated: 2 })).toBe("a");
    expect(defaultAskSession(rows, { live: "gone", seated: 1 })).toBe("c");
    expect(defaultAskSession(rows, {})).toBe("b");
    expect(defaultAskSession([], {})).toBeNull();
  });
});

describe("links", () => {
  it("Ask pre-fills a corner question with the official label so the engineer finds the corner", () => {
    expect(workOnQuestion("Stowe", "T15")).toBe("Why am I losing time at Stowe (T15)?");
    expect(workOnQuestion("T3", "T3")).toBe("Why am I losing time at T3?");
    expect(workOnQuestion("Stowe")).toBe("Why am I losing time at Stowe?");
    expect(askPath("abc", "Why?")).toBe("/review/sessions/abc/ask?q=Why%3F");
  });

  it("Laps with a page reference and the engineer for any session", () => {
    expect(lapsPath("abc", 54)).toBe("/review/sessions/abc/laps?ref=54");
    expect(lapsPath("abc", null)).toBe("/review/sessions/abc/laps");
    expect(engineerPath("abc", null)).toBe("/review/ask?session=abc");
    expect(engineerPath(null, "Hi")).toBe("/review/ask?q=Hi");
  });
});
