// The glossary `?` for strategy terms (lane "strategy"): the kit's Glossary button and popover (components/ui,
// spec 6.10), fed from lib/strategy/words.ts so the shared glossary list stays untouched. Terms only, never actions.

import { Button, Popover } from "@heroui/react";
import { STRATEGY_GLOSSARY, type StrategyTerm } from "../../../../lib/strategy/words";

/** `word`: a labelled button ("Box ?") for a row of terms, instead of the bare `?` beside a title. */
export function StrategyGlossary({ term, word, className = "" }: { term: StrategyTerm; word?: string; className?: string }) {
  const entry = STRATEGY_GLOSSARY[term];
  // "What is pit loss?", "What is safety car and VSC?" (only the first letter lowered: acronyms stay as written)
  const question = `What is ${entry.title.charAt(0).toLowerCase()}${entry.title.slice(1)}?`;
  return (
    <Popover>
      {word ? (
        <Button
          variant="ghost"
          size="sm"
          aria-label={question}
          className={`min-h-11 gap-1.5 px-2 text-sm font-medium text-muted ${className}`}
        >
          {word}
          <span aria-hidden="true" className="pw-gloss__dot">
            ?
          </span>
        </Button>
      ) : (
        <Button
          isIconOnly
          variant="ghost"
          size="sm"
          aria-label={question}
          className={`pw-gloss ${className}`}
        >
          <span aria-hidden="true" className="pw-gloss__dot">
            ?
          </span>
        </Button>
      )}
      <Popover.Content placement="top" className="pw-gloss__pop">
        <Popover.Dialog>
          <Popover.Heading className="pw-gloss__title">{entry.title}</Popover.Heading>
          <p className="pw-gloss__text">{entry.text}</p>
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  );
}
