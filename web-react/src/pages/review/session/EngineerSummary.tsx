// Engineer summary (spec 6.3 #8, optional): "Ask the engineer for a summary" calls /api/engineer/ask. The answer is
// grounded on the session's facts or replaced by a deterministic one; it is rendered with Pro Markdown and a chip
// saying which. Nothing else on the page depends on it. The answer is kept in the request cache for the visit.

import { Button, Card, Chip, Spinner } from "@heroui/react";
import { useState } from "react";
import { useApi } from "../../../hooks/useApi";
import type { EngineerAnswer } from "../../../lib/api";
import { cache } from "../../../lib/cache";
import { reviewApi, reviewKeys, SUMMARY_QUESTION } from "../../../lib/endpoints/review";
import { ANSWER_SOURCE_LABEL, answerSource } from "../../../lib/review/words";
import { errorText } from "./data";
import { LazyMarkdown } from "./LazyMarkdown";

const SOURCE_COLOR = { grounded: "success", deterministic: "default", llm_down: "warning" } as const;

export function EngineerSummary({ sessionId }: { sessionId: string }) {
  const key = reviewKeys.summary(sessionId);
  // Read-only view of the cache entry: nothing is fetched until the button is pressed.
  const { data } = useApi<EngineerAnswer>(key, () => Promise.reject(new Error("not asked")), { enabled: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      cache.set(key, await reviewApi.ask(SUMMARY_QUESTION, sessionId, true));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const source = data ? answerSource(data) : null;
  return (
    <Card className="gap-3 p-5">
      <Card.Header className="flex-row flex-wrap items-center justify-between gap-2">
        <Card.Title className="text-base font-semibold">Engineer summary</Card.Title>
        {source && (
          <Chip size="md" variant="soft" color={SOURCE_COLOR[source]}>
            <Chip.Label>{ANSWER_SOURCE_LABEL[source]}</Chip.Label>
          </Chip>
        )}
      </Card.Header>
      {data ? (
        <LazyMarkdown className="text-[15px] leading-relaxed" text={data.text} />
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" size="lg" className="min-h-12" isPending={busy} onPress={() => void ask()}>
            {busy && <Spinner size="sm" color="current" />}
            Ask the engineer for a summary
          </Button>
          {busy && <span className="text-sm text-muted">The local model can take half a minute.</span>}
        </div>
      )}
      {error && (
        <p role="alert" className="m-0 text-sm text-bad">
          The engineer could not answer: {error}
        </p>
      )}
      <p className="m-0 text-[13px] text-muted">
        Answers are grounded on the session's facts, or replaced by a deterministic answer.
      </p>
      {data && (
        <div>
          <Button variant="ghost" size="sm" className="min-h-11" isPending={busy} onPress={() => void ask()}>
            Ask again
          </Button>
        </div>
      )}
    </Card>
  );
}
