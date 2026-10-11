// Ask the engineer (spec 6.7; behaviour reference web/src/views/EngineerView.svelte): the conversation model for a
// session, built from the stored history and new answers. Pure; tested in node.
//
// The engineer only explains validated facts (ai/facts.py): an LLM answer must pass the grounding check or it is
// replaced by a deterministic answer composed from the facts themselves. Each answer therefore carries where it came
// from (`LLM · grounded`, `Deterministic`, `LLM down · deterministic`) and the facts it used ([F12] citations).

import type { EngineerAnswer } from "../api";
import type { EngineerHistoryRow, SessionListRow } from "../endpoints/review";
import { answerSource, replacedAfterGrounding, type AnswerSource } from "./words";

export interface ChatFact {
  id: string;
  topic: string;
  text: string;
}

export interface ChatEntry {
  key: string;
  role: "user" | "engineer";
  text: string;
  /** Engineer answers only. */
  source?: AnswerSource;
  facts: ChatFact[];
  latencyMs?: number | null;
  /** The LLM's answer failed the grounding check and was replaced (a live answer that says so). */
  replaced?: boolean;
  /** The request failed: the text is the error in words. */
  error?: boolean;
}

/** Questions to start with, each phrased the way the engineer's intent rules read it (ai/engineer.py; every one is a
 * row of tests/fixtures/intents.json): "losing the most time" asks for the biggest losses, "one thing to work on" for
 * the focus point, "how did the car handle" for the handling balance, "summary" for the debrief. */
export const ASK = {
  losing: "Where am I losing the most time?",
  workOn: "Give me one thing to work on.",
  handling: "How did the car handle?",
  line: "Where was my line different?",
  pit: "When should I pit?",
  gapAhead: "What's the gap to the car ahead?",
  ai: "How am I doing against the AI?",
  goals: "How am I doing on my goals?",
  summary: "Give me a summary of this session.",
} as const;

/** At most this many suggestions show (one row of pills on an iPad). */
export const MAX_SUGGESTIONS = 6;

/** The pace vs AI question ("against the AI" is an ai_pace intent; the answer also names the suggested AI level). */
export const AI_SUGGESTION: string = ASK.ai;

/** What the session (and the driver) has, so that every suggestion can be answered. */
export interface AskSuggestionOptions {
  /** Raced against the AI (F1 sessions with an AI difficulty). */
  aiPace?: boolean;
  /** Technique data: the racing line and the handling balance were measured. */
  technique?: boolean;
  /** A race with strategy records (pit window, gaps). */
  strategy?: boolean;
  /** The driver has goals. */
  goals?: boolean;
}

/**
 * The questions to start with for a session (v0.2.0 plan 4.7), at most `MAX_SUGGESTIONS`, in this priority: where the
 * time goes and one thing to work on; with technique data, the handling and the line; in a race with strategy
 * records, the pit and the gap ahead; raced against the AI, the AI; with goals, the goals; then the summary.
 */
export function askSuggestions(opts: AskSuggestionOptions = {}): readonly string[] {
  const out: string[] = [ASK.losing, ASK.workOn];
  if (opts.technique) out.push(ASK.handling, ASK.line);
  if (opts.strategy) out.push(ASK.pit, ASK.gapAhead);
  if (opts.aiPace) out.push(ASK.ai);
  if (opts.goals) out.push(ASK.goals);
  out.push(ASK.summary);
  return out.slice(0, MAX_SUGGESTIONS);
}

/** The questions for a session with nothing extra (no technique, strategy, AI or goals). */
export const SUGGESTIONS: readonly string[] = askSuggestions();

/** Where a stored answer came from: the history keeps `fallback` and `model`, not the grounding issues, so an LLM
 * failure and "LLM off" both read as deterministic. */
export function historySource(row: Pick<EngineerHistoryRow, "fallback" | "model" | "grounded">): AnswerSource {
  const fallback = row.fallback === true || row.fallback === 1;
  return answerSource({ fallback, grounded: row.grounded == null ? null : Boolean(row.grounded), model: row.model, llm_attempts: 0 });
}

function facts(list: readonly { id: string; topic?: string; text: string }[] | null | undefined): ChatFact[] {
  return (list ?? []).map((f) => ({ id: f.id, topic: f.topic ?? "", text: f.text }));
}

/** The stored conversation as chat entries (oldest first, as the server sends it). */
export function historyEntries(rows: readonly EngineerHistoryRow[] | null | undefined): ChatEntry[] {
  return (rows ?? []).map((r) =>
    r.role === "user"
      ? { key: `h${r.id}`, role: "user", text: r.text, facts: [] }
      : {
          key: `h${r.id}`,
          role: "engineer",
          text: r.text,
          source: historySource(r),
          facts: facts(r.facts),
          latencyMs: r.latency_ms,
        },
  );
}

/** A fresh answer as a chat entry. */
export function answerEntry(a: EngineerAnswer, key: string): ChatEntry {
  return {
    key,
    role: "engineer",
    text: a.text,
    source: answerSource(a),
    facts: facts(a.facts),
    latencyMs: a.latency_ms,
    replaced: replacedAfterGrounding(a),
  };
}

/** A failed request as a chat entry ("The engineer could not answer: no sessions recorded yet…"). */
export function errorEntry(message: string, key: string): ChatEntry {
  return { key, role: "engineer", text: `The engineer could not answer: ${message}`, facts: [], error: true };
}

export type TextPart = { kind: "text"; text: string } | { kind: "cite"; id: string };

/** Split an answer at its fact citations: "… 1.30 seconds [F32]." -> text, cite F32, text. */
export function citationParts(text: string): TextPart[] {
  const out: TextPart[] = [];
  const re = /\[(F\d+)\]/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push({ kind: "text", text: text.slice(last, m.index) });
    out.push({ kind: "cite", id: m[1]! });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

/** "14.8 s" for an answer's latency (under a second: "0.2 s"); null when unknown. */
export function latencyText(ms: number | null | undefined): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return null;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** "Built from 3 facts" / "Grounded on 1 fact" for the sources disclosure. */
export function factsLabel(e: Pick<ChatEntry, "facts" | "source">): string {
  const n = e.facts.length;
  const what = `${n} ${n === 1 ? "fact" : "facts"}`;
  return e.source === "grounded" ? `Grounded on ${what}` : `Built from ${what}`;
}

/** Topic words for a fact's chip ("laps" -> "Laps"). */
export function topicLabel(topic: string): string {
  const t = topic.replace(/_/g, " ").trim();
  return t ? t[0]!.toUpperCase() + t.slice(1) : "Fact";
}

/**
 * The session Ask opens on (`#/review/ask`): the route's `session`, else the live session, else the seated driver's
 * newest session, else the newest session. Unknown ids from the route are kept (the server says if it is gone).
 */
export function defaultAskSession(
  rows: readonly Pick<SessionListRow, "id" | "driver_id" | "started_unix">[],
  opts: { route?: string | null; live?: string | null; seated?: number | null },
): string | null {
  if (opts.route) return opts.route;
  if (opts.live && rows.some((r) => r.id === opts.live)) return opts.live;
  const newest = [...rows].sort((a, b) => b.started_unix - a.started_unix);
  if (opts.seated != null) {
    const mine = newest.find((r) => r.driver_id === opts.seated);
    if (mine) return mine.id;
  }
  return newest[0]?.id ?? null;
}
