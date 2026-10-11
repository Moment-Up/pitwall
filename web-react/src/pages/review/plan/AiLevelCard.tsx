// "Suggested AI level" (AI pace spec 8): shown on the Coaching plan when the server has a suggestion for this driver
// at this track (one per car class, session category and weather, newest first). A measured or estimated level shows
// large ("AI 38") with its range, a confidence chip and the server's sentence; with only one level raced here, the
// guidance sentence alone ("Race at a couple of difficulty levels here and Pitwall can suggest one"). The numbers and
// the sentence are the server's (analysis/ai_level.py); this card never computes a level.

import { Card, Chip } from "@heroui/react";
import { Glossary } from "../../../components/ui";
import type { AiLevelSuggestion } from "../../../lib/endpoints/review";
import { suggestionView, type SuggestionView } from "../../../lib/review/aipace";

/** At most this many keys on the card (classes and categories raced here). */
export const AI_LEVEL_MAX = 3;

function Suggestion({ v, label }: { v: SuggestionView; label: boolean }) {
  return (
    <section className="grid gap-2" aria-label={`AI level for ${v.keyLabel}`} data-ai-basis={v.kind}>
      {label && <h3 className="m-0 text-sm font-semibold text-muted">{v.keyLabel}</h3>}
      {v.kind === "level" && v.level && (
        <>
          <p className="m-0 flex flex-wrap items-baseline gap-x-3">
            <span className="pw-num text-[48px] leading-none">{v.level}</span>
            {v.bound && <span className="text-lg font-semibold text-muted">{v.bound}</span>}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {v.range && (
              <Chip variant="soft">
                <Chip.Label className="pw-num text-[15px]">{v.range}</Chip.Label>
              </Chip>
            )}
            {v.confidence && (
              <Chip variant="soft" color={v.confidence.tone}>
                <Chip.Label>{v.confidence.label}</Chip.Label>
              </Chip>
            )}
            {v.estimate && (
              <Chip variant="soft">
                <Chip.Label>Estimated from other tracks</Chip.Label>
              </Chip>
            )}
          </div>
        </>
      )}
      <p className="m-0 text-[15px] leading-snug text-foreground">{v.text}</p>
      {v.note && <p className="m-0 text-sm text-muted">{v.note}</p>}
    </section>
  );
}

export function AiLevelCard({ suggestions, glossary }: { suggestions: readonly AiLevelSuggestion[]; glossary: boolean }) {
  const views = suggestions.slice(0, AI_LEVEL_MAX).map(suggestionView);
  if (!views.length) return null;
  return (
    <Card className="gap-3 p-5" data-ai-level-card>
      <Card.Header className="gap-1">
        <div className="flex items-center justify-between gap-2">
          <Card.Title className="text-base font-semibold">Suggested AI level</Card.Title>
          {glossary && <Glossary term="ai_difficulty" className="-my-2 -mr-2" />}
        </div>
        {views.length === 1 && <p className="m-0 text-sm text-muted">{views[0]!.keyLabel}</p>}
      </Card.Header>
      <div className="grid gap-5">
        {views.map((v, i) => (
          <Suggestion key={`${v.keyLabel}|${i}`} v={v} label={views.length > 1} />
        ))}
      </div>
    </Card>
  );
}
