// "Suggested AI difficulty" (AI pace spec 8): shown on the Coaching plan when the server has a suggestion for this
// driver at this track (one per car class, session category and weather, newest first). A measured or estimated level
// shows large ("AI 38", "about AI 20" for an estimate) with its range (never for an "or higher" / "or lower" bound), a
// confidence chip, where it comes from ("Measured here" / "Estimated from other tracks") and a sentence about the
// viewed driver. With one level raced here so far, the way to move is the headline ("Lower than AI 35") with a "Not
// enough levels raced yet" chip and the next level to try. Every number is the server's (analysis/ai_level.py); the
// sentence is built from its fields for whoever is viewed (lib/review/aipace.ts suggestionSentence).

import { Card, Chip } from "@heroui/react";
import { Glossary } from "../../../components/ui";
import type { AiLevelSuggestion } from "../../../lib/endpoints/review";
import { suggestionAim, suggestionView, type AiWho, type SuggestionView } from "../../../lib/review/aipace";

/** At most this many keys on the card (classes and categories raced here). */
export const AI_LEVEL_MAX = 3;

function Suggestion({ v, label }: { v: SuggestionView; label: boolean }) {
  return (
    <section className="grid gap-2" aria-label={`AI difficulty for ${v.keyLabel}`} data-ai-basis={v.kind}>
      {label && <h3 className="m-0 text-sm font-semibold text-muted">{v.keyLabel}</h3>}
      {v.kind === "level" && v.level ? (
        <p className="m-0 flex flex-wrap items-baseline gap-x-3">
          <span className="pw-num text-[48px] leading-none">{v.level}</span>
          {v.bound && <span className="text-lg font-semibold text-muted">{v.bound}</span>}
        </p>
      ) : (
        v.headline && <p className="m-0 text-[28px] font-semibold leading-tight">{v.headline}</p>
      )}
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
        {v.measured && (
          <Chip variant="soft">
            <Chip.Label>Measured here</Chip.Label>
          </Chip>
        )}
        {v.estimate && (
          <Chip variant="soft">
            <Chip.Label>Estimated from other tracks</Chip.Label>
          </Chip>
        )}
        {v.kind === "direction" && (
          <Chip variant="soft" color="warning">
            <Chip.Label>Not enough levels raced yet</Chip.Label>
          </Chip>
        )}
      </div>
      <p className="m-0 text-[15px] leading-snug text-foreground">{v.text}</p>
      {v.note && <p className="m-0 text-sm text-muted">{v.note}</p>}
    </section>
  );
}

export interface AiLevelCardProps {
  suggestions: readonly AiLevelSuggestion[];
  glossary: boolean;
  /** Who the sentences are about ("your" / "Sam's"). */
  who: AiWho;
  /** The car the driver used per car class, newest (for "F1 World class (F1 Generic)"). */
  carNames?: ReadonlyMap<string, string>;
}

export function AiLevelCard({ suggestions, glossary, who, carNames }: AiLevelCardProps) {
  const shown = suggestions.slice(0, AI_LEVEL_MAX);
  const views = shown.map((s) => suggestionView(s, who, carNames?.get(s.key.car_class?.trim() ?? "") ?? null));
  if (!views.length) return null;
  return (
    <Card className="gap-3 p-5" data-ai-level-card>
      <Card.Header className="gap-1">
        <div className="flex items-center justify-between gap-2">
          <Card.Title className="text-base font-semibold">Suggested AI difficulty</Card.Title>
          {glossary && <Glossary term="ai_difficulty" className="-my-2 -mr-2" />}
        </div>
        {views.length === 1 && <p className="m-0 text-sm text-muted">{views[0]!.keyLabel}</p>}
        <p className="m-0 text-sm text-muted">{suggestionAim(shown[0]?.target_gap_pct)}</p>
      </Card.Header>
      <div className="grid gap-5">
        {views.map((v, i) => (
          <Suggestion key={`${v.keyLabel}|${i}`} v={v} label={views.length > 1} />
        ))}
      </div>
    </Card>
  );
}
