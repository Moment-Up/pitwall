import { Chip } from "@heroui/react";
import { cx, tagFor } from "./kit";
import type { TimingTagProps } from "./types";

/**
 * REC / PB / SB / INV tag (spec 4.6, 10.6): a HeroUI Chip filled with the timing colour and its ink, so the meaning
 * never rests on colour alone. Slower, neutral and unknown statuses render nothing. Screen readers hear the tag and
 * its meaning ("REC, family record"). `decorative` hides the meaning when the text next to it already says it
 * (legends).
 */
export function TimingTag({ status, size = "sm", className, decorative = false }: TimingTagProps) {
  const tag = tagFor(status);
  if (!tag) return null;
  return (
    <Chip size="sm" className={cx("pw-ttag", className)} data-status={status ?? undefined} data-size={size}>
      <Chip.Label>
        {tag.text}
        {!decorative && <span className="sr-only">, {tag.meaning}</span>}
      </Chip.Label>
    </Chip>
  );
}
