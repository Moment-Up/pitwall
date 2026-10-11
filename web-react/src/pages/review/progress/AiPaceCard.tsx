// "Against the AI" (AI pace spec 8): the viewed driver's sessions against the game's AI at this track, grouped by car
// class (default: the class of the newest session; a Segment when there are several) and session category (a toggle
// only when there is more than one). On top, the server's suggestion sentence for the series on screen (verbatim);
// then the dot chart (gap to the typical AI car, higher is faster, each dot labelled with its AI difficulty) and the
// same sessions as an accessible list. Only the game's own telemetry; synthetic sessions never count; a server without
// AI pace answers 404 and the card is left out.

import { Card, Skeleton } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import { useMemo, useState, type Key } from "react";
import { Glossary } from "../../../components/ui";
import type { DriverAiPace, SessionCategory } from "../../../lib/endpoints/review";
import { href, router } from "../../../lib/router";
import {
  aiSeries,
  aiSeriesSentence,
  categoryTab,
  dotWords,
  suggestionForSeries,
} from "../../../lib/review/aipace";
import { sessionPath } from "../../../lib/review/links";
import { AiPaceChart } from "./AiPaceChart";

export interface AiPaceCardProps {
  game: string;
  trackId: string;
  trackLabel: string;
  /** The answer of `/api/drivers/{id}/ai-pace?game&track_id` (undefined while loading). */
  data: DriverAiPace | undefined;
  error: Error | null;
  /** The scope is a synthetic track (synthetic sessions never count against the AI). */
  syntheticTrack: boolean;
  /** Sessions the page knows are synthetic (left out again, whatever the server sends). */
  syntheticIds: ReadonlySet<string>;
  /** "your" / "Alex's". */
  poss: string;
  caption: boolean;
  glossary: boolean;
}

export function AiPaceCard({
  game,
  trackId,
  trackLabel,
  data,
  error,
  syntheticTrack,
  syntheticIds,
  poss,
  caption,
  glossary,
}: AiPaceCardProps) {
  const [classKey, setClassKey] = useState<string | null>(null);
  const [category, setCategory] = useState<SessionCategory | null>(null);
  const view = useMemo(
    () => aiSeries(data?.points ?? [], { classKey, category, nowMs: Date.now(), synthetic: syntheticIds }),
    [data, classKey, category, syntheticIds],
  );
  const suggestion = useMemo(
    () => (data ? suggestionForSeries(data.suggestions, { game, trackId }, view) : null),
    [data, game, trackId, view],
  );
  const sentence = aiSeriesSentence(view, suggestion, { poss });

  const header = (
    <Card.Header className="flex-row items-center justify-between gap-2">
      <Card.Title className="text-base font-semibold">Against the AI</Card.Title>
      {glossary && <Glossary term="typical_ai_car" className="-my-2 -mr-2" />}
    </Card.Header>
  );

  if (!data) {
    return (
      <Card className="gap-3 p-5" aria-busy={!error || undefined}>
        {header}
        {error ? (
          <p role="alert" className="m-0 text-sm text-bad">
            Pace against the AI could not be loaded: {error.message}
          </p>
        ) : (
          <Skeleton className="h-40 w-full rounded-2xl" />
        )}
      </Card>
    );
  }

  return (
    <Card className="gap-3 p-5" data-ai-card>
      {header}
      {!sentence ? (
        <p className="m-0 text-base text-muted">
          {syntheticTrack
            ? "Synthetic sessions never count against the AI: only real races here do."
            : `No races against the AI at ${trackLabel} yet.`}
        </p>
      ) : (
        <>
          <p className="m-0 text-base leading-snug text-foreground">{sentence}</p>
          {(view.classes.length > 1 || view.categories.length > 1) && (
            <div className="flex flex-wrap items-center gap-2">
              {view.classes.length > 1 && (
                <Segment
                  aria-label="Car class"
                  selectedKey={view.classKey}
                  onSelectionChange={(k: Key) => {
                    setClassKey(String(k));
                    setCategory(null);
                  }}
                >
                  {view.classes.map((c) => (
                    <Segment.Item key={c.key} id={c.key} className="h-11 px-4">
                      {c.label}
                    </Segment.Item>
                  ))}
                </Segment>
              )}
              {view.categories.length > 1 && (
                <Segment
                  aria-label="Session type"
                  selectedKey={view.category}
                  onSelectionChange={(k: Key) => setCategory(String(k) as SessionCategory)}
                >
                  {view.categories.map((c) => (
                    <Segment.Item key={c} id={c} className="h-11 px-4">
                      {categoryTab(c)}
                    </Segment.Item>
                  ))}
                </Segment>
              )}
            </div>
          )}
          {caption && view.plotted > 0 && (
            <p className="m-0 text-sm text-muted">
              Each dot is one session here: how far {poss} best clean lap was from the typical AI car's best lap. Higher
              is faster; on the dashed line {poss === "your" ? "you were" : "they were"} level.
            </p>
          )}
          {view.plotted > 0 && <AiPaceChart dots={view.dots} onOpen={(id) => router.navigate(sessionPath(id))} />}
          <ul className="m-0 grid list-none gap-1.5 p-0" aria-label="Sessions against the AI">
            {[...view.dots].reverse().map((d) => (
              <li key={d.sessionId} className="flex flex-wrap items-baseline gap-x-2 text-sm leading-snug">
                <a className="min-h-11 shrink-0 py-2.5 font-semibold text-foreground underline-offset-2 hover:underline sm:min-h-0 sm:py-0" href={href(sessionPath(d.sessionId))}>
                  {d.xLabel}
                </a>
                <span className="text-muted">{dotWords(d)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
