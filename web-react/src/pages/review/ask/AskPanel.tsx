// Ask the engineer (spec 6.7): today's EngineerView (web/src/views/EngineerView.svelte) on HeroUI Pro chat components:
// ChatConversation with ChatMessage (user / engineer), PromptSuggestion pills, a PromptInput, and under each answer the
// facts it was grounded on (ChatSources / ChatSource) with a Chip saying where it came from: `LLM · grounded`,
// `Deterministic` (fallback, or the LLM switched off) or `LLM down · deterministic`. The line "answers are grounded,
// or replaced by a deterministic answer" stays visible. Used by the session's Ask tab and by Review › Ask.
//
// Writes: POST /api/engineer/ask (the server stores the question and the answer when conversations are kept). The
// stored conversation is loaded once per session (GET /api/engineer/history); new answers are appended locally.

import { Chip, Label, Switch } from "@heroui/react";
import { ChatConversation, ChatLoader, ChatMessage, ChatSource, ChatSources, PromptInput, PromptSuggestion } from "@heroui-pro/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useApi } from "../../../hooks/useApi";
import type { EngineerAnswer } from "../../../lib/api";
import { reviewApi } from "../../../lib/endpoints/review";
import { SETTINGS_KEYS, systemApi } from "../../../lib/endpoints/settings";
import {
  answerEntry,
  citationParts,
  errorEntry,
  factsLabel,
  historyEntries,
  latencyText,
  SUGGESTIONS,
  topicLabel,
  type ChatEntry,
} from "../../../lib/review/ask";
import { ANSWER_SOURCE_LABEL } from "../../../lib/review/words";
import { errorText, useHistory } from "../session/data";

const SOURCE_COLOR = { grounded: "success", deterministic: "default", llm_down: "warning" } as const;

function AnswerText({ text }: { text: string }) {
  return (
    <p className="m-0 text-[15px] leading-relaxed whitespace-pre-wrap">
      {citationParts(text).map((p, i) =>
        p.kind === "text" ? (
          <span key={i}>{p.text}</span>
        ) : (
          <sup key={i} className="ml-0.5 font-mono text-[10px] text-ref">
            {p.id}
          </sup>
        ),
      )}
    </p>
  );
}

function EngineerMessage({ e }: { e: ChatEntry }) {
  const latency = latencyText(e.latencyMs);
  return (
    <ChatMessage.Assistant>
      <ChatMessage.Body className="pe-0 sm:pe-12">
        <ChatMessage.Bubble className={`rounded-[18px_18px_18px_6px] px-4 py-3 ${e.error ? "bg-surface-secondary" : "bg-surface shadow-surface"}`}>
          <ChatMessage.Content>
            {e.error ? <p className="m-0 text-[15px] text-bad">{e.text}</p> : <AnswerText text={e.text} />}
          </ChatMessage.Content>
        </ChatMessage.Bubble>
        {!e.error && (
          <div className="flex flex-wrap items-center gap-2">
            {e.source && (
              <Chip size="sm" variant="soft" color={SOURCE_COLOR[e.source]}>
                <Chip.Label>{ANSWER_SOURCE_LABEL[e.source]}</Chip.Label>
              </Chip>
            )}
            {e.replaced && <span className="text-xs text-muted">The LLM's answer failed the grounding check, so this one replaced it.</span>}
            {latency && <span className="text-xs text-faint">{latency}</span>}
          </div>
        )}
        {e.facts.length > 0 && (
          <ChatSources className="[&_.chat-source\_\_trigger-link]:max-w-none!">
            <ChatSources.Trigger className="min-h-11">{factsLabel(e)}</ChatSources.Trigger>
            <ChatSources.Content>
              <ul className="m-0 grid list-none gap-2 p-0">
                {e.facts.map((f) => (
                  <li key={f.id} className="grid gap-1">
                    <ChatSource sourceType="document" title={`${f.id} · ${topicLabel(f.topic)}`} />
                    <span className="text-sm text-muted">{f.text}</span>
                  </li>
                ))}
              </ul>
            </ChatSources.Content>
          </ChatSources>
        )}
      </ChatMessage.Body>
    </ChatMessage.Assistant>
  );
}

function UserMessage({ e }: { e: ChatEntry }) {
  return (
    <ChatMessage.User>
      <ChatMessage.Bubble className="max-w-[70%] rounded-[18px_18px_6px_18px] bg-surface-tertiary px-4 py-2.5">
        <ChatMessage.Content>
          <p className="m-0 text-[15px] whitespace-pre-wrap">{e.text}</p>
        </ChatMessage.Content>
      </ChatMessage.Bubble>
    </ChatMessage.User>
  );
}

function OptionSwitch({ selected, onChange, children }: { selected: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <Switch isSelected={selected} onChange={onChange}>
      <Switch.Content className="min-h-11">
        <Switch.Control>
          <Switch.Thumb />
        </Switch.Control>
        <Label className="text-sm">{children}</Label>
      </Switch.Content>
    </Switch>
  );
}

/** The local LLM's state as a chip ("Local LLM ready" / "LLM offline: deterministic answers"). */
export function LlmChip() {
  const { data, error } = useApi(SETTINGS_KEYS.llmHealth, systemApi.llmHealth, { maxAgeMs: 30_000 });
  if (!data && !error) return null;
  const ok = data?.ok === true;
  return (
    <Chip size="lg" variant="soft" color={ok ? "success" : "warning"}>
      <span aria-hidden="true" className={`inline-block size-2 rounded-full ${ok ? "bg-success" : "bg-warning"}`} />
      <Chip.Label>{ok ? "LLM ready" : "LLM offline: deterministic answers"}</Chip.Label>
    </Chip>
  );
}

export interface AskPanelProps {
  /** The session the questions are about; null asks about the seated driver's latest session (the server picks). */
  sessionId: string | null;
  /** `?q=`: pre-fills the question (never sent on its own). */
  initialQuestion?: string | null;
  /** Shown above the conversation (Review › Ask: the session picker and the LLM chip). */
  header?: ReactNode;
}

export function AskPanel({ sessionId, initialQuestion, header }: AskPanelProps) {
  const history = useHistory(sessionId);
  const [asked, setAsked] = useState<ChatEntry[]>([]);
  const [question, setQuestion] = useState(initialQuestion ?? "");
  const [busy, setBusy] = useState(false);
  const [useLlm, setUseLlm] = useState(true);
  const [speak, setSpeak] = useState(false);
  const seq = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // A new ?q= (another "Ask the engineer" link) replaces the draft.
  useEffect(() => {
    if (initialQuestion) setQuestion(initialQuestion);
  }, [initialQuestion]);

  const entries = [...historyEntries(history.data), ...asked];

  async function ask(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    const n = ++seq.current;
    setAsked((a) => [...a, { key: `q${n}`, role: "user", text: q, facts: [] }]);
    setQuestion("");
    setBusy(true);
    try {
      const a: EngineerAnswer = await reviewApi.ask(q, sessionId, useLlm);
      if (!mounted.current) return;
      setAsked((list) => [...list, answerEntry(a, `a${n}`)]);
      if (speak && typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(a.speech));
      }
    } catch (e) {
      if (mounted.current) setAsked((list) => [...list, errorEntry(errorText(e), `e${n}`)]);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <div className="grid max-w-[860px] grid-cols-1 gap-3">
      {header}
      <div className="flex max-h-[min(60vh,560px)] min-h-[220px] flex-col">
        <ChatConversation initial="instant">
          <ChatConversation.Content className="gap-3 py-2">
            {history.error && !history.data && (
              <p className="m-0 text-sm text-muted">The earlier conversation could not be loaded: {history.error.message}</p>
            )}
            {entries.length === 0 && !busy && (
              <div className="grid gap-1 py-6 text-center">
                <p className="m-0 text-[15px]">Ask your race engineer about {sessionId ? "this session" : "your latest session"}.</p>
                <p className="m-0 text-sm text-muted">Pick a question below or type your own.</p>
              </div>
            )}
            {entries.map((e) => (e.role === "user" ? <UserMessage key={e.key} e={e} /> : <EngineerMessage key={e.key} e={e} />))}
            {busy && (
              <ChatMessage.Assistant>
                <ChatMessage.Body>
                  <span className="flex items-center gap-2 text-sm text-muted">
                    <ChatLoader.Dots label="The engineer is thinking" />
                    {useLlm ? "The engineer is thinking (the local model takes a few seconds)" : "Working it out from the facts"}
                  </span>
                </ChatMessage.Body>
              </ChatMessage.Assistant>
            )}
            <ChatConversation.ScrollAnchor />
          </ChatConversation.Content>
          <ChatConversation.ScrollButton aria-label="Scroll to the newest answer" />
        </ChatConversation>
      </div>

      <PromptSuggestion aria-label="Suggested questions">
        {/* Chips in a row (spec 6.7, mockup), not Pro's default two-column list: Pro's CSS is unlayered, hence the `!`. */}
        <PromptSuggestion.Items className="flex! flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <PromptSuggestion.Item
              key={s}
              showEndIcon={false}
              className="min-h-11 w-auto! items-center! rounded-full! px-4! py-2!"
              isDisabled={busy}
              onPress={() => void ask(s)}
            >
              {s}
            </PromptSuggestion.Item>
          ))}
        </PromptSuggestion.Items>
      </PromptSuggestion>

      <PromptInput
        value={question}
        onValueChange={setQuestion}
        onSubmit={() => void ask(question)}
        status={busy ? "submitted" : "ready"}
        lockInputOnRun={false}
      >
        <PromptInput.Shell className="rounded-3xl">
          <PromptInput.Content>
            <PromptInput.TextArea
              aria-label="Question for the engineer"
              placeholder={sessionId ? "Ask the engineer about this session…" : "Ask the engineer about your latest session…"}
              className="min-h-11 text-[15px]"
            />
          </PromptInput.Content>
          <PromptInput.Toolbar>
            <PromptInput.ToolbarEnd>
              <PromptInput.Send aria-label="Ask" className="size-11" />
            </PromptInput.ToolbarEnd>
          </PromptInput.Toolbar>
        </PromptInput.Shell>
      </PromptInput>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <OptionSwitch selected={useLlm} onChange={setUseLlm}>
          Use the LLM (off: deterministic answers only)
        </OptionSwitch>
        <OptionSwitch selected={speak} onChange={setSpeak}>
          Read answers aloud on this device
        </OptionSwitch>
      </div>
      <p className="m-0 text-sm text-muted">
        Answers are grounded on the session's facts, or replaced by a deterministic answer. The engineer only sees validated
        facts computed from your telemetry; every number it says is checked against them.
      </p>
    </div>
  );
}
