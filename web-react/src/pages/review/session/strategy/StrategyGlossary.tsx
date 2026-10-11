// The glossary `?` for strategy terms (lane "strategy"): the kit's Glossary button and popover (components/ui,
// spec 6.10), fed from lib/strategy/words.ts so the shared glossary list stays untouched. Terms only, never actions.

import { Button, Popover } from "@heroui/react";
import { STRATEGY_GLOSSARY, type StrategyTerm } from "../../../../lib/strategy/words";

export function StrategyGlossary({ term, className = "" }: { term: StrategyTerm; className?: string }) {
  const entry = STRATEGY_GLOSSARY[term];
  return (
    <Popover>
      <Button
        isIconOnly
        variant="ghost"
        size="sm"
        aria-label={`What is ${entry.title.toLowerCase()}?`}
        className={`pw-gloss ${className}`}
      >
        <span aria-hidden="true" className="pw-gloss__dot">
          ?
        </span>
      </Button>
      <Popover.Content placement="top" className="pw-gloss__pop">
        <Popover.Dialog>
          <Popover.Heading className="pw-gloss__title">{entry.title}</Popover.Heading>
          <p className="pw-gloss__text">{entry.text}</p>
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  );
}
