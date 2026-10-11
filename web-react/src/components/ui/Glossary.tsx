import { Button, Popover } from "@heroui/react";
import { GLOSSARY } from "./glossary-terms";
import { cx } from "./kit";
import type { GlossaryProps } from "./types";

/**
 * Glossary `?` (spec 6.10, 10.4): a 44 px icon Button (the 22 px circle is the visual) that opens a HeroUI Popover
 * with the term in plain words. Tap to open, tap outside or Escape to close; nothing is hover-only. Explains terms,
 * never actions. Pages hide it for advanced profiles.
 */
export function Glossary({ term, label, className }: GlossaryProps) {
  const entry = GLOSSARY[term];
  return (
    <Popover>
      <Button
        isIconOnly
        variant="ghost"
        size="sm"
        aria-label={label ?? `What is ${entry.title.replace(/ \(.*\)$/, "").toLowerCase()}?`}
        className={cx("pw-gloss", className)}
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
