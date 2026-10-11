// Glossary `?` for technique terms (feat/technique spec §9): the UI kit's Glossary pattern (a 44 px icon Button
// opening a HeroUI Popover, the same `.pw-gloss` styles) with the technique entries of lib/technique/glossary.ts.
// Explains terms, never actions. Pages hide it for advanced profiles (TechniqueDensity.glossary).

import { Button, Popover } from "@heroui/react";
import { TECHNIQUE_GLOSSARY, type TechniqueTerm } from "../../../../lib/technique/glossary";

/** `labelled`: the term is written beside the `?` (where several terms sit together, so each `?` says what it explains). */
export function TechniqueGlossary({ term, labelled = false, className }: { term: TechniqueTerm; labelled?: boolean; className?: string }) {
  const entry = TECHNIQUE_GLOSSARY[term];
  return (
    <Popover>
      {labelled ? (
        <Button
          variant="ghost"
          size="sm"
          aria-label={`What is ${entry.title.toLowerCase()}?`}
          className={`min-h-11 gap-1.5 px-2 text-xs font-normal text-muted ${className ?? ""}`}
        >
          <span aria-hidden="true" className="pw-gloss__dot">
            ?
          </span>
          <span aria-hidden="true">{entry.title}</span>
        </Button>
      ) : (
        <Button
          isIconOnly
          variant="ghost"
          size="sm"
          aria-label={`What is ${entry.title.toLowerCase()}?`}
          className={className ? `pw-gloss ${className}` : "pw-gloss"}
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
