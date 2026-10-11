import { Chip } from "@heroui/react";
import { cx } from "./kit";
import type { CornerTagProps } from "./types";
import { Unknown } from "./Unknown";

/**
 * A corner chip (spec 10.6): official label in bold ("T15"), the official name when the track sheet has one
 * ("Stowe"), and for a cue focus corner an accent outline plus the word FOCUS (colour is never the only signal).
 * Names are data from the verified track sheets; the UI never invents or parses them.
 */
export function CornerTag({ label, name, focus = false, size = "md", className }: CornerTagProps) {
  const hasLabel = typeof label === "string" && label.trim() !== "";
  const hasName = typeof name === "string" && name.trim() !== "";
  return (
    <Chip size={size} className={cx("pw-corner", className)} data-focus={focus ? "" : undefined}>
      <Chip.Label className="pw-corner__inner">
        {hasLabel ? <b className="pw-corner__label">{label}</b> : <Unknown label="corner unknown" />}
        {hasName ? <span className="pw-corner__name">{name}</span> : null}
        {focus ? (
          <span className="pw-corner__focus">
            FOCUS<span className="sr-only"> corner</span>
          </span>
        ) : null}
      </Chip.Label>
    </Chip>
  );
}
